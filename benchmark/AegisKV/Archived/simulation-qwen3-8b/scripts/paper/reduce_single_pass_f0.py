"""Reduce complete, original-DAG F0 runs into cache and WCT diagnostics.

The input is the published F0 of the agent80 campaign. This program never
runs a simulator and rejects repeated DAGs and nonzero failure schedules.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[5]
WORKLOAD = ROOT / "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl"


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def union_length(intervals):
    end, total = -1, 0
    for start, stop in sorted(intervals):
        assert stop >= start
        total += max(0, stop - max(end, start))
        end = max(end, stop)
    return total


def csv_write(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def reduce(directory, system, output):
    manifest_path = directory / f"{system}.manifest.json"
    summary_path = directory / f"{system}.summary.json"
    raw_path = directory / f"{system}.json.gz"
    manifest = json.loads(manifest_path.read_text())
    original_summary = json.loads(summary_path.read_text())
    assert manifest["status"] == "PASS" and manifest["failure_schedule"] is None
    assert sha(raw_path) == manifest["raw_sha256"]
    assert sha(summary_path) == manifest["summary_sha256"]
    assert original_summary["rounds"] == 1 and not original_summary["failure_events"]
    assert original_summary["system"] == system
    with WORKLOAD.open() as stream:
        records = {r["span_id"]: r for r in map(json.loads, stream)}
    assert len(records) == 1304 and len({r["workflow_id"] for r in records.values()}) == 160
    print(f"Reading published single-pass raw: {system}", flush=True)
    with gzip.open(raw_path, "rt") as stream:
        raw = json.load(stream)
    rep, payload = raw["representative"], raw["payload"]
    assert payload["status"] == "PASS" and not rep["failure_events"]
    audit = payload["output_audit"]
    assert audit["duplicate_or_missing_tokens"] == audit["stale_route_output_count"] == 0
    assert audit["expected_output_tokens"] == audit["external_output_tokens"]
    details = {r["span_id"]: r for r in raw["span_details"]}
    obs = rep["mechanism"]
    observations = {r["span_id"]: r for r in obs["requests"]}
    assert set(records) == set(details) == set(observations)
    assert all(details[k]["output_tokens"] == records[k]["output_tokens"] for k in records)
    assert all(observations[k]["prompt_tokens"] == records[k]["prompt_tokens"] for k in records)

    steps, gpu_intervals = defaultdict(list), defaultdict(list)
    prefill, recomputed_prefill = defaultdict(int), defaultdict(int)
    for step in rep["continuous_batch_scheduler"]["steps"]:
        assert step["status"] == "COMPLETED", step["status"]
        start, stop = step["start_ns"], step["effective_end_ns"]
        for p in step["participants"]:
            rid = p["request_id"]
            n = records[rid]["prompt_tokens"]
            before, after = p["num_computed_tokens_before"], p["num_computed_tokens_after"]
            work = max(0, min(n, after) - min(n, before))
            prefill[rid] += work
            if p.get("recompute", False):
                recomputed_prefill[rid] += work
            gpu_intervals[rid].append((start, stop))
            steps[rid].append(dict(start_ns=start, end_ns=stop, gpu_id=step["gpu_id"],
                                   before=before, after=after, phase=p["phase"],
                                   origin=p["origin"], prefill_tokens=work))

    gets, preemptions, cpu = defaultdict(list), defaultdict(list), defaultdict(list)
    byte_counts = defaultdict(int)
    for t in rep["transfers"]:
        byte_counts[t["cause"]] += t["transferred_bytes"]
        if t["cause"] == "AEGIS_FOREGROUND_STORE_RESTORE":
            assert t["status"] == "COMMITTED"
            gets[t["span_id"]].append((t["ready_ns"], t["end_ns"]))
    for e in obs["cpu_queue"]:
        if e["operation"] == "foreground_lookup":
            cpu[e["span_id"]].append((e["start_ns"], e["end_ns"]))
    timeline_times = {g: [r["timestamp_ns"] for r in rows]
                      for g, rows in rep["gpu_hbm_timelines"].items()}
    for e in rep["scheduler_preemption_events"]:
        gpu, at = e["target_gpu_id"], e["timestamp_ns"]
        idx = bisect_right(timeline_times[gpu], at) - 1
        hbm = rep["gpu_hbm_timelines"][gpu][idx] if idx >= 0 else None
        for p in e["preemption_details"]:
            rid = p["victim_request_id"]
            restart = next(s["start_ns"] for s in steps[rid] if s["start_ns"] >= at)
            preemptions[rid].append(dict(**p, timestamp_ns=at, resume_ns=restart,
                                         wait_ns=restart-at, gpu_id=gpu,
                                         hbm_at_or_before=hbm))

    requests, groups = {}, defaultdict(list)
    for rid, record in records.items():
        d, observed = details[rid], observations[rid]
        start, stop = d["released_ns"], d["completed_ns"]
        assert start is not None and stop is not None and stop >= start
        assert start == observed["released_ns"] and stop == observed["completed_ns"]
        local, dram, peer = (d[k] for k in ("reused_primary_tokens", "reused_store_tokens", "reused_peer_tokens"))
        hits = local + dram + peer
        assert 0 <= hits <= record["prompt_tokens"]
        clip = lambda intervals: [(max(start, a), min(stop, b)) for a, b in intervals
                                  if max(start, a) < min(stop, b)]
        g, t, c = clip(gpu_intervals[rid]), clip(gets[rid]), clip(cpu[rid])
        gpu_ns, gpu_get_ns, total_busy_ns = (union_length(v) for v in (g, g+t, g+t+c))
        row = dict(system=system, workflow_id=record["workflow_id"], span_id=rid,
                   prompt_tokens=record["prompt_tokens"], output_tokens=record["output_tokens"],
                   local_hit_tokens=local, dram_hit_tokens=dram, peer_hit_tokens=peer,
                   total_hit_tokens=hits, released_ns=start, completed_ns=stop,
                   latency_ns=stop-start, first_compute_ns=observed["first_compute_ns"],
                   first_wait_ns=observed["first_compute_ns"]-start, ttft_ns=observed["ttft_ns"],
                   prefill_executed_tokens=prefill[rid],
                   prefill_after_preemption_tokens=recomputed_prefill[rid],
                   gpu_step_ns=gpu_ns, get_exclusive_ns=gpu_get_ns-gpu_ns,
                   dispatch_cpu_exclusive_ns=total_busy_ns-gpu_get_ns,
                   queue_other_ns=stop-start-total_busy_ns,
                   preemptions=len(preemptions[rid]),
                   preemption_wait_ns=sum(e["wait_ns"] for e in preemptions[rid]))
        assert row["queue_other_ns"] >= 0
        requests[rid] = row
        groups[row["workflow_id"]].append(row)

    workflows, paths = [], {}
    wct_reference = payload["metrics"]["workflow_completion_time_ns"]["by_workflow_id"]
    for wid, rows in sorted(groups.items()):
        start, stop = min(r["released_ns"] for r in rows), max(r["completed_ns"] for r in rows)
        assert stop-start == wct_reference[wid]
        current = max(rows, key=lambda r: (r["completed_ns"], r["span_id"]))["span_id"]
        path = []
        while current:
            path.append(current)
            parents = records[current]["parent_span_ids"]
            current = max(parents, key=lambda k: (requests[k]["completed_ns"], k)) if parents else None
        path.reverse()
        gap, previous = 0, start
        for rid in path:
            assert requests[rid]["released_ns"] >= previous
            gap += requests[rid]["released_ns"] - previous
            previous = requests[rid]["completed_ns"]
        assert sum(requests[r]["latency_ns"] for r in path) + gap == stop-start
        paths[wid] = path
        sums = {key: sum(r[key] for r in rows) for key in
                ("prompt_tokens", "output_tokens", "local_hit_tokens", "dram_hit_tokens", "peer_hit_tokens",
                 "total_hit_tokens", "prefill_executed_tokens", "prefill_after_preemption_tokens", "preemptions", "preemption_wait_ns")}
        row = dict(system=system, workflow_id=wid, requests=len(rows), release_ns=start,
                   completion_ns=stop, wct_s=(stop-start)/1e9, **sums)
        for key in ("local", "dram", "peer", "total"):
            row[key+"_hit_pct"] = 100*row[key+"_hit_tokens"]/row["prompt_tokens"]
        row["request_hit_pct"] = 100*sum(r["total_hit_tokens"] > 0 for r in rows)/len(rows)
        for key in ("gpu_step_ns", "get_exclusive_ns", "dispatch_cpu_exclusive_ns", "queue_other_ns"):
            row["critical_"+key] = sum(requests[r][key] for r in path)
        row["critical_dependency_gap_ns"] = gap
        assert sum(row[k] for k in row if k.startswith("critical_")) == stop-start
        workflows.append(row)

    totals = {k: sum(w[k] for w in workflows) for k in
              ("prompt_tokens", "local_hit_tokens", "dram_hit_tokens", "peer_hit_tokens", "total_hit_tokens",
               "prefill_executed_tokens", "prefill_after_preemption_tokens", "preemptions", "preemption_wait_ns")}
    summary = dict(workflows=160, requests=1304, rounds=1, **totals,
                   mean_wct_s=float(np.mean([w["wct_s"] for w in workflows])),
                   batch_s=payload["metrics"]["workload_end_ns"]/1e9,
                   p99_ttft_s=float(np.percentile([r["ttft_ns"] for r in requests.values()], 99))/1e9,
                   hit_request_count=sum(r["total_hit_tokens"] > 0 for r in requests.values()),
                   reference_control_cpu_s=sum(r["cpu_ns"] for r in obs["policy_cpu"])/1e9,
                   modeled_controller_service_s=sum(r["service_ns"] for r in obs["cpu_queue"])/1e9,
                   transfer_bytes=dict(byte_counts))
    for key in ("local", "dram", "peer", "total"):
        summary[key+"_hit_pct"] = 100*summary[key+"_hit_tokens"]/summary["prompt_tokens"]
    output.mkdir(parents=True, exist_ok=True)
    result = dict(schema="aegiskv.single_pass_f0_diagnosis.v1", system=system,
                  inputs={str(p):sha(p) for p in [raw_path,summary_path,manifest_path,WORKLOAD]},
                  source_snapshot_sha256=manifest["source_snapshot_sha256"],
                  cpu_quotes_sha256=manifest["cpu_quotes_sha256"],
                  parameters=original_summary["parameters"], configuration=original_summary["configuration"],
                  summary=summary, workflows=workflows, requests=list(requests.values()),
                  critical_paths=paths, preemptions=dict(preemptions), steps=dict(steps),
                  output_audit=audit,
                  definitions={"cache_hit":"served normal-path prefix counters; not lifetime computation avoided",
                               "prefill":"sum of executed prompt-position advances, including repeated advances after preemption",
                               "critical_path":"realized latest-completing parent chain; may differ across systems",
                               "latency_partition":"GPU step union; GET exclusive of GPU; dispatch CPU exclusive of both; remainder queue/other; plus dependency gaps",
                               "gpu_step":"elapsed duration of batches containing this request, not exclusive GPU utilization",
                               "inference":"one uncalibrated DES run per system, same original 160 DAGs; no native GPU execution"})
    with gzip.open(output/f"{system}.diagnosis.json.gz", "wt") as stream:
        json.dump(result, stream, separators=(",", ":"))
    csv_write(output/f"{system}-workflows.csv", workflows)
    csv_write(output/f"{system}-requests.csv", list(requests.values()))
    (output/f"{system}-summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps({"system":system,"summary":summary}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--system", choices=["mooncake", "dram", "aegis"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reduce(args.input, args.system, args.output)
