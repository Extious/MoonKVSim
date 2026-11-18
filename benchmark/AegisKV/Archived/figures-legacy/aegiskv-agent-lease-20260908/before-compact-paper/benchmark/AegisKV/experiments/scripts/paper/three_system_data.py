"""Audit and reduce raw DES records for paired, individual-workflow figures."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

SYSTEMS = ("mooncake", "dram", "aegis")
LABELS = dict(zip(SYSTEMS, ("Mooncake", "DRAM-only AegisKV", "AegisKV"), strict=True))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024**2), b""):
            h.update(block)
    return h.hexdigest()


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def percentile(values, q):
    return float(np.percentile(values, q)) if len(values) else None


def accumulate_windows(output, start_ns, end_ns, value, width_ns, *, integral=False):
    """Time-weighted values, or already-integrated bytes, without sample bias."""
    if end_ns <= start_ns:
        return
    rate = value / (end_ns - start_ns) if integral else value / width_ns
    for i in range(start_ns // width_ns, (end_ns - 1) // width_ns + 1):
        overlap = min(end_ns, (i + 1) * width_ns) - max(start_ns, i * width_ns)
        output[i] += overlap * rate


def reduce_run(path: Path, output: Path, width_ns=1_000_000_000):
    manifest_path = path.with_name(path.name.replace(".json.gz", ".manifest.json"))
    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "PASS"
    assert sha(path) == manifest["raw_sha256"], f"raw changed: {path}"
    with gzip.open(path, "rt") as f:
        raw = json.load(f)
    payload, rep = raw["payload"], raw["representative"]
    assert payload["status"] == "PASS"
    audit = payload["output_audit"]
    assert audit["expected_output_tokens"] == audit["external_output_tokens"]
    assert audit["duplicate_or_missing_tokens"] == audit["stale_route_output_count"] == 0
    metrics, obs = payload["metrics"], rep["mechanism"]
    details = {r["span_id"]: r for r in raw["span_details"]}
    scheduler_admissions = {
        r["spec"]["request_id"]: r["route_history"][0]["timestamp_ns"]
        for r in rep["continuous_batch_scheduler"]["requests"]
    }
    assert len(details) == manifest["workload"]["requests"]
    end = metrics["workload_end_ns"]
    size = (end + width_ns - 1) // width_ns
    ids = sorted(manifest["workload"]["workflow_ids"])
    groups = defaultdict(list)
    requests = []
    hbm_wait_started, hbm_wait_ns = {}, defaultdict(int)
    preemptions = defaultdict(int)
    for e in rep["scheduler_preemption_events"]:
        for rid in e["preempted_request_ids"]:
            preemptions[rid] += 1
    for e in obs["store_hbm_wait_events"]:
        rid = e["span_id"]
        if e["event"] == "HBM_WAIT":
            assert rid not in hbm_wait_started
            hbm_wait_started[rid] = e["timestamp_ns"]
        elif rid in hbm_wait_started:
            hbm_wait_ns[rid] += e["timestamp_ns"] - hbm_wait_started.pop(rid)
    assert not hbm_wait_started, "unterminated foreground HBM wait"
    for original in obs["requests"]:
        row = dict(original)
        d = details[row["span_id"]]
        # Store-wait retries can lose cache residency. Use served final tokens,
        # not the optimistic lookup observed when the request first arrived.
        row["local_hit_tokens"] = d["reused_primary_tokens"]
        row["dram_hit_tokens"] = d["reused_store_tokens"]
        row["peer_hit_tokens"] = d["reused_peer_tokens"]
        row["scheduler_ready_ns"] = scheduler_admissions[row["span_id"]]
        row["scheduler_queue_ns"] = row["first_compute_ns"] - row["scheduler_ready_ns"]
        row["foreground_hbm_wait_ns"] = hbm_wait_ns[row["span_id"]]
        row["preemptions"] = preemptions[row["span_id"]]
        assert row["scheduler_queue_ns"] >= 0
        row["total_hit_tokens"] = sum(
            row[k] for k in ("local_hit_tokens", "dram_hit_tokens", "peer_hit_tokens")
        )
        assert 0 <= row["total_hit_tokens"] <= row["prompt_tokens"]
        assert row["precompute_wait_ns"] >= 0 and row["ttft_ns"] >= 0
        assert d["external_output_emissions"] == d["output_tokens"]
        groups[row["workflow_id"]].append(row)
        requests.append(row)
    assert set(groups) == set(ids)
    cpu_by_workflow = defaultdict(int)
    for row in obs["policy_cpu"]:
        if row["span_id"] in details:
            cpu_by_workflow[details[row["span_id"]]["workflow_id"]] += row["cpu_ns"]
    queue_by_workflow = defaultdict(int)
    for row in obs["cpu_queue"]:
        if row["operation"] == "foreground_lookup":
            queue_by_workflow[details[row["span_id"]]["workflow_id"]] += row["queue_ns"]
    transfers = {r["transfer_id"]: r for r in rep["transfers"]}
    foreground = []
    foreground_by_workflow = defaultdict(list)
    copy_by_workflow = defaultdict(lambda: defaultdict(float))
    for transfer in transfers.values():
        wid = details[transfer["span_id"]]["workflow_id"]
        cause = transfer["cause"]
        category = (
            "foreground"
            if cause == "AEGIS_FOREGROUND_STORE_RESTORE"
            else "recovery"
            if cause.startswith("AEGIS_RECOVERY_")
            else "background"
        )
        copy_by_workflow[wid][category] += transfer["transferred_bytes"]
        if cause == "AEGIS_PEER_HBM_PROTECTION":
            copy_by_workflow[wid]["peer_put"] += transfer["transferred_bytes"]
        elif cause == "AEGIS_STORE_DRAM_PROTECTION":
            copy_by_workflow[wid]["dram_put"] += transfer["transferred_bytes"]
        if category != "foreground" or transfer["status"] != "COMMITTED":
            continue
        bottleneck = min(
            payload["resource_model"]["rate_resources"][rid]
            for rid in transfer["rate_resource_ids"]
        )
        row = {
            "span_id": transfer["span_id"],
            "bytes": transfer["bytes"],
            "duration_ms": (transfer["end_ns"] - transfer["ready_ns"]) / 1e6,
            "service_slowdown": (transfer["end_ns"] - transfer["start_ns"])
            / 1e9
            / (transfer["bytes"] / bottleneck),
        }
        foreground.append(row)
        foreground_by_workflow[wid].append(row)
    workflows = []
    for i, wid in enumerate(ids, 1):
        rows = groups[wid]
        tokens = sum(r["prompt_tokens"] for r in rows)
        assert (
            max(r["completed_ns"] for r in rows) - min(r["released_ns"] for r in rows)
            == metrics["workflow_completion_time_ns"]["by_workflow_id"][wid]
        )
        workflows.append(
            {
                "index": i,
                "workflow_id": wid,
                "requests": len(rows),
                "prompt_tokens": tokens,
                "wct_s": metrics["workflow_completion_time_ns"]["by_workflow_id"][wid] / 1e9,
                "total_hit_pct": 100 * sum(r["total_hit_tokens"] for r in rows) / tokens,
                "dram_hit_pct": 100 * sum(r["dram_hit_tokens"] for r in rows) / tokens,
                "request_hit_pct": 100 * sum(r["total_hit_tokens"] > 0 for r in rows) / len(rows),
                "mean_precompute_wait_s": float(np.mean([r["precompute_wait_ns"] for r in rows]))
                / 1e9,
                "p95_precompute_wait_s": percentile([r["precompute_wait_ns"] for r in rows], 95)
                / 1e9,
                "mean_ttft_s": float(np.mean([r["ttft_ns"] for r in rows])) / 1e9,
                "mean_scheduler_queue_s": float(np.mean([r["scheduler_queue_ns"] for r in rows]))
                / 1e9,
                "p95_scheduler_queue_s": percentile([r["scheduler_queue_ns"] for r in rows], 95)
                / 1e9,
                "reference_admission_cpu_ms": cpu_by_workflow[wid] / 1e6,
                "mean_foreground_hbm_wait_s": float(
                    np.mean([r["foreground_hbm_wait_ns"] for r in rows])
                )
                / 1e9,
                "preemptions": sum(r["preemptions"] for r in rows),
                "foreground_cpu_queue_ms": queue_by_workflow[wid] / 1e6,
                "background_copy_gib": copy_by_workflow[wid]["background"] / 1024**3,
                "peer_copy_gib": copy_by_workflow[wid]["peer_put"] / 1024**3,
                "dram_copy_gib": copy_by_workflow[wid]["dram_put"] / 1024**3,
                "foreground_copy_gib": copy_by_workflow[wid]["foreground"] / 1024**3,
                "foreground_get_p95_ms": percentile(
                    [r["duration_ms"] for r in foreground_by_workflow[wid]], 95
                ),
                "foreground_get_slowdown_p95": percentile(
                    [r["service_slowdown"] for r in foreground_by_workflow[wid]], 95
                ),
            }
        )
    hbm = {}
    pressure = {}
    for gpu, timeline in rep["gpu_hbm_timelines"].items():
        arrays = {k: np.zeros(size) for k in ("free_gib", "peer_gib", "active_gib", "restore_gib")}
        low_ns, minimum = 0, float("inf")
        for i, row in enumerate(timeline):
            accounts = row["accounts"]
            assert min(accounts.values()) >= 0
            assert sum(accounts.values()) == row["capacity_bytes"], (gpu, row)
            start = row["timestamp_ns"]
            stop = min(end, timeline[i + 1]["timestamp_ns"] if i + 1 < len(timeline) else end)
            if start >= end:
                break
            assert stop >= start
            minimum = min(minimum, accounts["FREE"])
            if accounts["FREE"] < 1024**3:
                low_ns += stop - start
            values = {
                "free_gib": accounts["FREE"],
                "peer_gib": accounts["PEER_PROTECTION_KV"] + accounts["PEER_PROTECTION_PENDING"],
                "active_gib": accounts["ACTIVE_PRIMARY_KV"],
                "restore_gib": accounts["FOREGROUND_STORE_RESTORE_RESERVED"]
                + accounts["RECOVERY_DEST_RESERVED"],
            }
            for key, value in values.items():
                accumulate_windows(arrays[key], start, stop, value / 1024**3, width_ns)
        # Normalize the final partial bin to its actual duration.
        fraction = (end - (size - 1) * width_ns) / width_ns
        for arr in arrays.values():
            arr[-1] /= fraction
        hbm[gpu] = {k: v.tolist() for k, v in arrays.items()}
        pressure[gpu] = {
            "free_below_1gib_pct": low_ns / end * 100,
            "minimum_free_gib": minimum / 1024**3,
        }
    network = {
        k: np.zeros(size)
        for k in (
            "total_gbs",
            "foreground_gbs",
            "protection_gbs",
            "recovery_gbs",
            "peer_put_gbs",
            "dram_put_gbs",
        )
    }
    total_flow_bytes = defaultdict(float)
    capacity = manifest["parameters"]["peer_bandwidth_bytes_per_second"]
    for r in rep["flow_rate_intervals"]:
        if "peer-fabric-rate" not in r["path_resource_ids"]:
            continue
        total_flow_bytes[r["transfer_id"]] += r["transferred_bytes"]
        start, stop = r["start_ns"], min(r["end_ns"], end)
        if stop <= start:
            continue
        transferred = r["transferred_bytes"] * (stop - start) / (r["end_ns"] - start)
        kind = (
            "foreground_gbs"
            if r["cause"] == "AEGIS_FOREGROUND_STORE_RESTORE"
            else "recovery_gbs"
            if r["cause"].startswith("AEGIS_RECOVERY_")
            else "protection_gbs"
        )
        keys = [kind, "total_gbs"]
        if r["cause"] == "AEGIS_PEER_HBM_PROTECTION":
            keys.append("peer_put_gbs")
        elif r["cause"] == "AEGIS_STORE_DRAM_PROTECTION":
            keys.append("dram_put_gbs")
        for key in keys:
            accumulate_windows(network[key], start, stop, transferred, width_ns, integral=True)
    for arr in network.values():
        arr /= width_ns
        arr[-1] /= (end - (size - 1) * width_ns) / width_ns
    assert max(network["total_gbs"], default=0) <= capacity / 1e9 + 1e-5
    assert np.allclose(network["peer_put_gbs"] + network["dram_put_gbs"], network["protection_gbs"])
    for tid, transferred in total_flow_bytes.items():
        t = transfers[tid]
        assert abs(transferred - t["transferred_bytes"]) <= max(2, transferred * 1e-8), (
            tid,
            transferred,
            t["transferred_bytes"],
        )
    prompt = sum(r["prompt_tokens"] for r in requests)
    summary = {
        "workflows": len(ids),
        "requests": len(requests),
        "workload_end_s": end / 1e9,
        "mean_wct_s": float(np.mean([r["wct_s"] for r in workflows])),
        "p95_wct_s": percentile([r["wct_s"] for r in workflows], 95),
        "total_hit_pct": 100 * sum(r["total_hit_tokens"] for r in requests) / prompt,
        "dram_hit_pct": 100 * sum(r["dram_hit_tokens"] for r in requests) / prompt,
        "request_hit_pct": 100 * sum(r["total_hit_tokens"] > 0 for r in requests) / len(requests),
        "mean_precompute_wait_s": float(np.mean([r["precompute_wait_ns"] for r in requests])) / 1e9,
        "p95_precompute_wait_s": percentile([r["precompute_wait_ns"] for r in requests], 95) / 1e9,
        "p99_ttft_s": percentile([r["ttft_ns"] for r in requests], 99) / 1e9,
        "p99_request_tpot_s": percentile(
            [r["request_tpot_ns"] / 1e9 for r in requests if r["request_tpot_ns"] is not None], 99
        ),
        "reference_admission_cpu_s": sum(r["cpu_ns"] for r in obs["policy_cpu"]) / 1e9,
        "reference_admission_calls": len(obs["policy_cpu"]),
        "scheduler_preemptions": sum(preemptions.values()),
        "foreground_hbm_wait_s": sum(hbm_wait_ns.values()) / 1e9,
        "p95_scheduler_queue_s": percentile([r["scheduler_queue_ns"] for r in requests], 95) / 1e9,
        "foreground_transfer_p95_ms": percentile([r["duration_ms"] for r in foreground], 95),
        "foreground_slowdown_p95": percentile([r["service_slowdown"] for r in foreground], 95),
        "physical_transferred_gib": sum(total_flow_bytes.values()) / 1024**3,
        "background_peer_gib": sum(v["peer_put"] for v in copy_by_workflow.values()) / 1024**3,
        "background_dram_gib": sum(v["dram_put"] for v in copy_by_workflow.values()) / 1024**3,
        "failed_allocation_attempts": sum(not r["succeeded"] for r in obs["allocation_attempts"]),
        "store_hbm_wait_count": sum(r["event"] == "HBM_WAIT" for r in obs["store_hbm_wait_events"]),
        "store_hit_lost_during_hbm_wait_count": sum(
            r["event"] == "CACHE_EXPIRED_OR_EVICTED_RECOMPUTE" for r in obs["store_hbm_wait_events"]
        ),
        "modeled_controller_service_s": sum(r["service_ns"] for r in obs["cpu_queue"]) / 1e9,
        "foreground_cpu_queue_sum_ms": sum(queue_by_workflow.values()) / 1e6,
    }
    result = {
        "schema": "moonkvsim.three_system_figure_data.v1",
        "extractor_sha256": sha(__file__),
        "manifest": manifest,
        "raw_path": str(path.resolve()),
        "manifest_sha256": sha(manifest_path),
        "summary": summary,
        "workflows": workflows,
        "requests": requests,
        "policy_cpu": obs["policy_cpu"],
        "cpu_queue": obs["cpu_queue"],
        "hbm": hbm,
        "hbm_pressure": pressure,
        "network": {k: v.tolist() for k, v in network.items()},
        "window_ns": width_ns,
        "foreground_transfers": foreground,
        "failures": [r for r in raw["span_details"] if r["failure_at_ns"] is not None],
        "failure_events": rep["failure_events"],
        "recovery_events": rep["recovery_events"],
        "agent_lease_events": obs.get("agent_lease_events", []),
        "agent_lifecycle": obs.get("agent_lifecycle", []),
        "foreground_budget": obs["foreground_budget"],
        "step_contention": obs.get("step_contention", []),
        "budget": {
            "observations": len(obs["foreground_budget"]),
            "mode": manifest["configuration"]["peer_mode"],
        },
        "audit": {
            "status": "PASS",
            "hbm_conservation": True,
            "output_exactly_once": True,
            "link_bytes_conserved": True,
            "link_capacity_respected": True,
            "workflow_id_coverage": True,
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    system = manifest["system"]
    (output / f"{system}.json").write_text(json.dumps(result, separators=(",", ":")) + "\n")
    write_csv(output / f"{system}-workflows.csv", workflows)
    write_csv(output / f"{system}-requests.csv", requests)
    write_csv(output / f"{system}-foreground-transfers.csv", foreground)
    print(
        json.dumps({"input": str(path), "summary": summary, "audit": result["audit"]}), flush=True
    )


def load_case(directory):
    data = {s: json.loads((Path(directory) / f"{s}.json").read_text()) for s in SYSTEMS}
    a = data["mooncake"]["manifest"]
    for b in data.values():
        m = b["manifest"]
        for key in (
            "source_snapshot_sha256",
            "parameters",
            "workload",
            "failure_reference_sha256",
            "failure_schedule",
            "cpu_calibration_sha256",
        ):
            assert a[key] == m[key], f"unpaired configuration: {key}"
        assert b["audit"]["status"] == "PASS"
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--systems", nargs="+", default=SYSTEMS)
    args = parser.parse_args()
    for system in args.systems:
        reduce_run(args.input / f"{system}.json.gz", args.output)


if __name__ == "__main__":
    main()
