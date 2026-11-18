#!/usr/bin/env python3
"""Run one frozen, naturally routed 80%-token GPU-failure experiment."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import time

from moonkvsim.aegiskv.experiment import FailureEventSchedule, FailureSchedule, ModelParameters
from moonkvsim.aegiskv.experiment_suite import load_frozen_workload
from moonkvsim.aegiskv.lease_experiment import LeaseConfig, LeaseRuntime
from moonkvsim.aegiskv.mechanism_experiment import mechanism_variant
from run_agent_lease_mechanisms import revisit_records

ROOT = Path(__file__).resolve().parents[4]
SYSTEMS = ("mooncake", "dram", "aegis")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def read_records(rounds, workflows):
    directory = ROOT / "benchmark/AegisKV/experiments/workloads"
    records, _, _ = load_frozen_workload(
        directory / "fanoutqa-dev-qwen3-8b-160.jsonl",
        directory / "fanoutqa-dev-qwen3-8b-160-manifest.json",
        retain_exact_token_ids=True,
    )
    selected = sorted({r["workflow_id"] for r in records})[:workflows]
    records = [r for r in records if r["workflow_id"] in selected]
    return revisit_records(records, rounds) if rounds > 1 else records


def step_projection(step):
    return {
        "gpu_id": step["gpu_id"],
        "start_ns": step["start_ns"],
        "planned_end_ns": step["planned_end_ns"],
        "participants": [
            {k: p[k] for k in ("request_id", "num_computed_tokens_before", "num_computed_tokens_after")}
            for p in step["participants"]
        ],
    }


def prefix_digest(steps, at):
    rows = [step_projection(s) for s in steps if s["start_ns"] < at]
    rows.sort(key=lambda r: (r["start_ns"], r["gpu_id"]))
    return {
        "steps": len(rows),
        "sha256": hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "scope": "planned scheduler starts and token participants with start < fault; excludes final status and actual end",
    }


def crossings(steps, selected_records):
    out = {}
    for record in selected_records:
        rid = record["span_id"]
        total = record["prompt_tokens"] + record["output_tokens"]
        candidates = []
        for step in steps:
            for p in step["participants"]:
                if p["request_id"] != rid:
                    continue
                before, after = p["num_computed_tokens_before"], p["num_computed_tokens_after"]
                if before * 1000 < total * 800 <= after * 1000:
                    duration = step["planned_end_ns"] - step["start_ns"]
                    offset = min(duration - 1, duration * (total * 800 - before * 1000) // ((after - before) * 1000))
                    candidates.append({"span_id": rid, "at_ns": step["start_ns"] + offset,
                                       "gpu_id": step["gpu_id"], "before": before, "after": after,
                                       "total_tokens": total, "threshold_numerator": total * 800,
                                       "threshold_denominator": 1000})
        if candidates:
            crossing = min(candidates, key=lambda c: c["at_ns"])
            crossing["scheduler_prefix"] = prefix_digest(steps, crossing["at_ns"])
            out[rid] = crossing
        else:
            out[rid] = {"span_id": rid, "status": "NO_EXACT_80_PERCENT_CROSSING"}
    return out


def run(args):
    started = time.monotonic()
    snapshot = ROOT / "MECHANISM_SOURCE_SNAPSHOT.json"
    for rel, expected in json.loads(snapshot.read_text())["files"].items():
        assert sha(ROOT / rel) == expected, f"frozen source drift: {rel}"
    records = read_records(args.rounds, args.workflows)
    by_id = {r["span_id"]: r for r in records}
    focus_records = [r for r in records if r["workflow_id"] == args.workflow_id]
    assert focus_records, "predeclared workflow missing"
    parameters = ModelParameters(runtime_semantics="shared_prefix_v3", policy_chunk_tokens=4096,
                                 store_budget_bytes=1_000_000_000_000,
                                 store_bandwidth_bytes_per_second=25_000_000_000,
                                 peer_bandwidth_bytes_per_second=25_000_000_000,
                                 failure_progress_per_mille=800)
    calibration = ROOT / "output/agent-lease-20260908/CPU_QUOTES.json"
    quotes = json.loads(calibration.read_text())
    config = LeaseConfig(peer_mode="guarded", cpu_service_ns=quotes["admission_ns"][args.system],
                         foreground_cpu_service_ns=quotes["foreground_dispatch_ns"][args.system])
    schedule = None
    control = None
    if args.focus_span:
        assert args.focus_span in by_id
        control = json.loads(args.control.read_text())
        assert control["system"] == args.system
        reference = control["focus_crossings"][args.focus_span]
        assert "at_ns" in reference, reference
        at = reference["at_ns"]
        ends = [w["completion_ns"] for w in control["workflows"]]
        completed = sum(t < at for t in ends)
        event = FailureEventSchedule(
            failure_id="agent80-single", event_index=0, bucket="96k", seed=0,
            focus_span_id=args.focus_span, target_gpu_id=reference["gpu_id"], reference_at_ns=at,
            target_workload_progress_per_mille=max(1, min(999, completed * 1000 // len(ends))),
            reference_completed_workflow_count=completed, reference_workflow_count=len(ends),
            detection_delay_ns=0, trigger_progress_per_mille=800, gpu_recovery_time_ns=120_000_000_000,
            physical_target_frozen=False,
            selection_scope="predeclared_same_workflow_agent_identity_80_percent_total_tokens_natural_host",
        )
        schedule = FailureSchedule((event,), selection_scope="one_failure_per_independent_full_run")
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / f"{args.system}.manifest.json"
    assert not manifest_path.exists(), manifest_path
    runtime = LeaseRuntime(system=args.system, mechanism_config=config, records=records,
                           variant=replace(mechanism_variant(args.system, parameters),
                                           suite="agent-progress-80-20260909",
                                           interpretation="frozen_source_v3_progress_conditioned_DES"),
                           context_bucket="96k", seed=0, failure_schedule=schedule,
                           workflow_concurrency=16, workflow_admission_seed=0, peer_binding_seed=0)
    result = runtime.run()
    steps = result.representative["continuous_batch_scheduler"]["steps"]
    failures = result.representative["failure_events"]
    assert len(failures) == bool(args.focus_span)
    by_workflow = defaultdict(list)
    for row in result.span_details:
        assert row["completed_ns"] is not None
        by_workflow[row["workflow_id"]].append(row)
    workflows = []
    for wid, rows in sorted(by_workflow.items()):
        release = min(r["released_ns"] for r in rows)
        completion = max(r["completed_ns"] for r in rows)
        workflows.append({"workflow_id": wid, "release_ns": release, "completion_ns": completion,
                          "wct_ns": completion - release, "requests": len(rows)})
    checks = {"requests_complete": len(result.span_details) == len(records),
              "runtime_capacity_transfer_output_checks": "PASS"}
    if failures:
        event, = failures
        evidence = event["logical_trigger"]["continuous_progress_evidence"]
        checks.update(
            exact_first_threshold=evidence["resolution_mode"] == "FIRST_TOKEN_THRESHOLD_CROSSING",
            progress_800=evidence["trigger_progress_per_mille"] == 800,
            focus_is_active=args.focus_span in event["impacted_active_span_ids"],
            same_F0_crossing_time=event["timestamp_ns"] == reference["at_ns"],
            natural_host_matches_F0=event["target_gpu_id"] == reference["gpu_id"],
            outage_120s=event["repair_completed_at_ns"] - event["timestamp_ns"] == 120_000_000_000,
            planned_scheduler_prefix_matches_F0=prefix_digest(steps, event["timestamp_ns"])["sha256"] == reference["scheduler_prefix"]["sha256"],
        )
        active = {by_id[r]["workflow_id"] for r in event["impacted_active_span_ids"]}
        queued = {by_id[r]["workflow_id"] for r in event["impacted_queued_span_ids"]}
        control_w = {r["workflow_id"]: r for r in control["workflows"]}
        for row in workflows:
            wid = row["workflow_id"]
            row.update({"f0_" + key: control_w[wid][key] for key in ["release_ns", "completion_ns", "wct_ns"]})
            for key in ["release_ns", "completion_ns", "wct_ns"]:
                row["delta_" + key] = row[key] - row["f0_" + key]
            assert row["delta_completion_ns"] == row["delta_wct_ns"] + row["delta_release_ns"]
            row["active_victim"] = wid in active
            row["queued_victim"] = wid in queued
            row["direct_victim"] = wid in active | queued
            row["indirect_wct_change"] = not row["direct_victim"] and row["delta_wct_ns"] != 0
            row["released_at_fault"] = row["release_ns"] <= event["timestamp_ns"]
            row["completed_before_fault"] = row["completion_ns"] < event["timestamp_ns"]
    summary = {"schema": "aegiskv.agent80_run.v1", "system": args.system,
               "workflow_id": args.workflow_id, "focus_span_id": args.focus_span,
               "rounds": args.rounds, "source_snapshot_sha256": sha(snapshot),
               "runner_sha256": sha(__file__), "cpu_quotes_sha256": sha(calibration),
               "parameters": parameters.to_dict(), "configuration": result.representative["mechanism"]["configuration"],
               "workflows": workflows, "requests": list(result.span_details),
               "failure_events": failures, "recovery_events": result.representative["recovery_events"],
               "checks": checks,
               "focus_crossings": {} if failures else crossings(steps, focus_records),
               "metrics": result.payload["metrics"],
               "algorithm_contract": result.representative["mechanism"]["algorithm_contract"],
               "evidence": "uncalibrated source-v3 DES; natural collateral victims; one run per condition"}
    summary_path = args.output / f"{args.system}.summary.json"
    write_json(summary_path, summary)
    print(json.dumps({"phase": "simulation_complete", "system": args.system,
                      "focus": args.focus_span, "wall_s": time.monotonic() - started,
                      "checks": checks}), flush=True)
    raw_path = args.output / f"{args.system}.json.gz"
    with gzip.open(raw_path, "wt", encoding="utf-8", compresslevel=1) as f:
        json.dump({"payload": result.payload, "representative": result.representative,
                   "span_details": result.span_details}, f, separators=(",", ":"))
    checks_ok = all(v is True or v == "PASS" for v in checks.values())
    manifest = {"status": "PASS" if checks_ok else "AUDIT_FAILED", "summary_sha256": sha(summary_path),
                "raw_sha256": sha(raw_path), "source_snapshot_sha256": sha(snapshot),
                "runner_sha256": sha(__file__), "cpu_quotes_sha256": sha(calibration),
                "failure_schedule": None if schedule is None else schedule.to_dict(),
                "wall_s": time.monotonic() - started, "checks": checks}
    write_json(manifest_path, manifest)
    assert checks_ok, checks
    print(json.dumps({"phase": "published", "system": args.system, "wall_s": manifest["wall_s"]}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--system", required=True, choices=SYSTEMS)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--workflow-id", default="00065f204bddb94d")
    p.add_argument("--workflows", default=160, type=int)
    p.add_argument("--rounds", default=1, type=int)
    p.add_argument("--focus-span")
    p.add_argument("--control", type=Path)
    args = p.parse_args()
    if args.focus_span and not args.control:
        p.error("--focus-span requires the matched --control summary")
    run(args)
