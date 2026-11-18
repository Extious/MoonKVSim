#!/usr/bin/env python3
"""Independently reconstruct paired WCT and 80%-token faults from raw runs."""
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import argparse
import gzip
import hashlib
import json
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--campaign", required=True, type=Path)
    p.add_argument("--source", required=True, type=Path)
    args = p.parse_args()
    directory = args.campaign.resolve()
    protocol = read(directory/"PROTOCOL.json")
    status = read(directory/"STATUS.json")
    assert status["status"] == "PASS" and len(status["completed"]) == 24
    snapshot = args.source/"MECHANISM_SOURCE_SNAPSHOT.json"
    assert sha(snapshot) == protocol["source_snapshot_sha256"]
    source = read(snapshot)
    for rel, digest in source["files"].items():
        assert sha(args.source/rel) == digest, rel
    cases = {p["case"]: p for p in protocol["positions"]}
    quotes_sha = sha(args.source/"output/agent-lease-20260908/CPU_QUOTES.json")

    def crossing_from_steps(steps, spec):
        total = spec["prompt_tokens"] + spec["output_tokens"]
        candidates = []
        for step in steps:
            for participant in step["participants"]:
                if participant["request_id"] != spec["span_id"]:
                    continue
                before = participant["num_computed_tokens_before"]
                after = participant["num_computed_tokens_after"]
                if before*5 < total*4 <= after*5:
                    duration = step["planned_end_ns"] - step["start_ns"]
                    at = step["start_ns"] + min(duration-1, duration*(total*4-before*5)//((after-before)*5))
                    candidates.append((at, step["gpu_id"], before, after))
        assert candidates, spec["span_id"]
        return min(candidates)

    def prefix_from_steps(steps, at):
        projection = []
        for step in steps:
            if step["start_ns"] < at:
                projection.append({k: step[k] for k in ("gpu_id", "start_ns", "planned_end_ns")})
                projection[-1]["participants"] = [
                    {k: r[k] for k in ("request_id", "num_computed_tokens_before", "num_computed_tokens_after")}
                    for r in step["participants"]]
        projection.sort(key=lambda row: (row["start_ns"], row["gpu_id"]))
        return hashlib.sha256(json.dumps(projection, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def audit(job):
        case, system = job
        folder = directory/"runs"/case
        manifest = read(folder/f"{system}.manifest.json")
        summary_path = folder/f"{system}.summary.json"
        raw_path = folder/f"{system}.json.gz"
        assert manifest["status"] == "PASS"
        assert manifest["runner_sha256"] == protocol["runner_sha256"]
        assert manifest["source_snapshot_sha256"] == protocol["source_snapshot_sha256"]
        assert manifest["cpu_quotes_sha256"] == quotes_sha
        assert sha(raw_path) == manifest["raw_sha256"]
        assert sha(summary_path) == manifest["summary_sha256"]
        summary = read(summary_path)
        with gzip.open(raw_path, "rt") as f:
            raw = json.load(f)
        steps = raw["representative"]["continuous_batch_scheduler"]["steps"]
        details = {r["span_id"]: r for r in raw["span_details"]}
        assert len(details) == protocol["requests_per_run"]
        assert {r["span_id"]: r for r in summary["requests"]} == details
        workflows = defaultdict(list)
        for detail in details.values():
            assert detail["released_ns"] is not None and detail["completed_ns"] is not None
            workflows[detail["workflow_id"]].append(detail)
        assert len(workflows) == 160
        for row in summary["workflows"]:
            ds = workflows[row["workflow_id"]]
            release = min(d["released_ns"] for d in ds)
            completion = max(d["completed_ns"] for d in ds)
            assert (release, completion, completion-release) == (row["release_ns"], row["completion_ns"], row["wct_ns"])
        failures = raw["representative"]["failure_events"]
        assert failures == summary["failure_events"]
        result = {"case": case, "system": system, "requests": len(details), "workflows": 160,
                  "raw_sha256": manifest["raw_sha256"], "summary_sha256": manifest["summary_sha256"]}
        if case == "f0":
            assert not failures
            for spec in cases.values():
                crossing = summary["focus_crossings"][spec["span_id"]]
                assert crossing_from_steps(steps, spec) == tuple(crossing[k] for k in ("at_ns", "gpu_id", "before", "after"))
                assert prefix_from_steps(steps, crossing["at_ns"]) == crossing["scheduler_prefix"]["sha256"]
        else:
            event, = failures
            spec = cases[case]
            rid = spec["span_id"]
            assert rid in event["impacted_active_span_ids"]
            proof = event["logical_trigger"]["continuous_progress_evidence"]
            assert proof["resolution_mode"] == "FIRST_TOKEN_THRESHOLD_CROSSING"
            total = spec["prompt_tokens"] + spec["output_tokens"]
            before, after = proof["num_computed_tokens_before"], proof["num_computed_tokens_after"]
            assert before*5 < total*4 <= after*5
            duration = proof["step_end_ns"] - proof["step_start_ns"]
            offset = min(duration-1, duration*(total*4-before*5)//((after-before)*5))
            assert event["timestamp_ns"] == proof["step_start_ns"] + offset
            assert event["target_gpu_id"] == proof["first_crossing_evidence"]["target_gpu_id"]
            assert crossing_from_steps(steps, spec) == (event["timestamp_ns"], event["target_gpu_id"], before, after)
            assert event["repair_completed_at_ns"] == event["timestamp_ns"] + 120_000_000_000
            control = read(directory/"runs/f0"/f"{system}.summary.json")
            reference = control["focus_crossings"][rid]
            assert (event["timestamp_ns"], event["target_gpu_id"]) == (reference["at_ns"], reference["gpu_id"])
            assert prefix_from_steps(steps, event["timestamp_ns"]) == reference["scheduler_prefix"]["sha256"]
            cw = {w["workflow_id"]: w for w in control["workflows"]}
            active = {details[r]["workflow_id"] for r in event["impacted_active_span_ids"]}
            queued = {details[r]["workflow_id"] for r in event["impacted_queued_span_ids"]}
            for row in summary["workflows"]:
                wid = row["workflow_id"]
                for key in ("wct_ns", "release_ns", "completion_ns"):
                    assert row["delta_"+key] == row[key] - cw[wid][key]
                assert row["delta_completion_ns"] == row["delta_wct_ns"] + row["delta_release_ns"]
                if min(row["release_ns"], cw[wid]["release_ns"]) < event["timestamp_ns"]:
                    assert row["delta_release_ns"] == 0, "release changed before first fault"
                if min(row["completion_ns"], cw[wid]["completion_ns"]) < event["timestamp_ns"]:
                    assert row["delta_completion_ns"] == row["delta_wct_ns"] == 0, "completed workflow changed before first fault"
                assert row["active_victim"] == (wid in active)
                assert row["queued_victim"] == (wid in queued)
                assert row["indirect_wct_change"] == (wid not in active|queued and row["delta_wct_ns"] != 0)
            focal = next(w for w in summary["workflows"] if w["workflow_id"] == protocol["workflow_id"])
            assert focal["delta_release_ns"] == 0
            result.update(failure_at_ns=event["timestamp_ns"], gpu=event["target_gpu_id"],
                          focal_delta_wct_ns=focal["delta_wct_ns"], active_workflow_ids=sorted(active),
                          queued_workflow_ids=sorted(queued))
        print(json.dumps({"audited": job}), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=3) as pool:
        audits = list(pool.map(audit, status["completed"]))
    report = {"status": "PASS", "source_files_checked": len(source["files"]),
              "full_runs": 24, "F0_runs": 3, "F1_runs": 21, "raw_runs_reconstructed": audits,
              "workflow_pairs": 3360, "focus_pairs": 21, "repeats_per_condition": 1,
              "protocol_sha256": sha(directory/"PROTOCOL.json"), "auditor_sha256": sha(__file__),
              "cpu_quotes_sha256": quotes_sha,
              "scope": "raw hashes, exact input source, same-ID WCT/release/completion, first raw scheduler token crossing and natural host, paired pre-fault scheduler projection, victim identities; no hardware calibration"}
    (directory/"RUN_AUDIT.json").write_text(json.dumps(report, indent=2)+"\n")


if __name__ == "__main__":
    main()
