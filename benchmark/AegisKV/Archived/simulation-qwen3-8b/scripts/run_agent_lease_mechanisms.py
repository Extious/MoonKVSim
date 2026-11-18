#!/usr/bin/env python3
"""Execute a frozen, paired Mooncake / DRAM AegisKV / AegisKV diagnostic."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import time
from pathlib import Path

from moonkvsim.aegiskv.experiment import FailureEventSchedule, FailureSchedule, ModelParameters
from moonkvsim.aegiskv.experiment_suite import load_frozen_workload
from moonkvsim.aegiskv.lease_experiment import (
    LeaseConfig as MechanismConfig,
    LeaseRuntime as MechanismRuntime,
)
from moonkvsim.aegiskv.mechanism_experiment import mechanism_variant
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[4]


def revisit_records(records, rounds=2):
    """Controlled exact-input revisits; never presented as observed user turns.

    All original DAG nodes, token IDs, durations and workflow IDs are retained.
    Roots of the next round depend on all leaves of the preceding round.
    """
    children = {p for r in records for p in r["parent_span_ids"]}
    leaves = {}
    for r in records:
        if r["span_id"] not in children:
            leaves.setdefault(r["workflow_id"], []).append(r["span_id"])
    result = []
    for round_id in range(rounds):
        suffix = f":revisit-{round_id}"
        for record in records:
            r = copy.deepcopy(record)
            r["span_id"] += suffix
            r["parent_span_ids"] = [p + suffix for p in record["parent_span_ids"]]
            if not r["parent_span_ids"] and round_id:
                r["parent_span_ids"] = [
                    p + f":revisit-{round_id - 1}" for p in leaves[r["workflow_id"]]
                ]
            r["dependency_release_rule"] = (
                "parent_completion_plus_recorded_delay"
                if r["parent_span_ids"]
                else "observed_root_arrival"
            )
            r["parent_edges"] = [
                {
                    "parent_span_id": p,
                    "origin": "inferred",
                    "confidence": 1.0,
                    "inference_rule": "controlled_exact_input_revisit_dag",
                }
                for p in r["parent_span_ids"]
            ]
            r["schema"] = "moonkvsim.controlled_revisit_trace.v1"
            r["evidence_class"] = "controlled_exact_input_revisit"
            r["parent_edge_origin"] = "inferred" if r["parent_span_ids"] else "none"
            r["parent_edge_confidence"] = 1.0 if r["parent_span_ids"] else None
            r["synthetic"] = True
            r["mechanism_revisit_round"] = round_id
            r["mechanism_original_span_id"] = record["span_id"]
            result.append(r)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--systems", nargs="+", default=["mooncake", "dram", "aegis"])
    p.add_argument("--workflows", type=int, default=160)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--concurrency", type=int, default=16)
    p.add_argument("--store-gib", type=float, default=1000e9 / 1024**3)
    p.add_argument("--bandwidth-gbs", type=float, default=25)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--failure-reference", type=Path)
    p.add_argument("--failures", type=int, choices=[0, 1, 2], default=0)
    p.add_argument("--failure-progress-permille", type=int, choices=[250, 500, 750])
    p.add_argument(
        "--peer-mode",
        choices=["guarded", "capacity_guarded_exploration"],
        default="guarded",
    )
    p.add_argument("--cpu-calibration", type=Path)
    p.add_argument("--cpu-scale", type=float, default=1.0)
    p.add_argument("--no-slack", action="store_true")
    p.add_argument("--eager-refresh", action="store_true")
    p.add_argument("--strict-free-gain", action="store_true")
    p.add_argument("--static-peer", action="store_true")
    p.add_argument("--dma-slowdown", type=float, default=0.0)
    args = p.parse_args()
    snapshot = ROOT / "MECHANISM_SOURCE_SNAPSHOT.json"
    if snapshot.exists():
        frozen = json.loads(snapshot.read_text())
        for name, digest in frozen["files"].items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"frozen source drift: {name}")
    directory = ROOT / "benchmark/AegisKV/experiments/workloads"
    records, _, _ = load_frozen_workload(
        directory / "fanoutqa-dev-qwen3-8b-160.jsonl",
        directory / "fanoutqa-dev-qwen3-8b-160-manifest.json",
        retain_exact_token_ids=True,
    )
    selected = sorted({r["workflow_id"] for r in records})[: args.workflows]
    records = [r for r in records if r["workflow_id"] in selected]
    if args.rounds > 1:
        records = revisit_records(records, args.rounds)
    parameters = ModelParameters(
        runtime_semantics="shared_prefix_v3",
        policy_chunk_tokens=4096,
        store_budget_bytes=round(args.store_gib * 1024**3),
        store_bandwidth_bytes_per_second=round(args.bandwidth_gbs * 1e9),
        peer_bandwidth_bytes_per_second=round(args.bandwidth_gbs * 1e9),
    )
    args.output.mkdir(parents=True, exist_ok=True)
    schedule = None
    if args.failures:
        if args.failure_reference is None:
            p.error("--failures requires a matched Mooncake F0 --failure-reference")
        with gzip.open(args.failure_reference, "rt") as f:
            reference = json.load(f)
        details = {r["span_id"]: r for r in reference["span_details"]}
        assert set(details) == {r["span_id"] for r in records}
        focal = min(records, key=lambda r: (-r["prompt_tokens"], r["span_id"]))
        selection_scope = "longest_input_prompt_then_causal_descendant_predeclared_rule"
        if args.failure_progress_permille is not None:
            if args.failures != 1:
                p.error("progress-stratified selection requires exactly one failure")
            # Freeze selection from Mooncake's no-fault trace, before seeing any
            # failed run. Use a 60% fresh-prefill crossing with at least two
            # complete 4K chunks; select nearest completed-workflow fraction.
            eligible = {
                r["span_id"]: r
                for r in records
                if r["prompt_tokens"] >= 16384 and r.get("mechanism_revisit_round", 0) == 0
            }
            ends_for_selection = [
                max(r["completed_ns"] for r in details.values() if r["workflow_id"] == w)
                for w in selected
            ]
            candidates = []
            seen = set()
            for step in reference["representative"]["continuous_batch_scheduler"]["steps"]:
                for participant in step["participants"]:
                    rid = participant["request_id"]
                    if rid not in eligible or rid in seen:
                        continue
                    threshold = eligible[rid]["prompt_tokens"] * 600 // 1000
                    before = participant["num_computed_tokens_before"]
                    after = participant["num_computed_tokens_after"]
                    if before <= threshold < after:
                        seen.add(rid)
                        at = step["start_ns"] + (step["planned_end_ns"] - step["start_ns"]) * (
                            threshold - before
                        ) // (after - before)
                        completed = sum(end < at for end in ends_for_selection)
                        distance = abs(
                            completed * 1000 - args.failure_progress_permille * len(selected)
                        )
                        candidates.append((distance, at, rid))
            if not candidates:
                raise ValueError("no eligible progress-stratified prefill crossing")
            focal = eligible[min(candidates)[2]]
            selection_scope = f"first_round_nearest_F0_completed_workflow_{args.failure_progress_permille}_permille_prompt_ge_16384_tie_earliest_then_id"
        focus = [focal]
        if args.failures == 2:
            descendants = {focal["span_id"]}
            for _ in range(len(records)):
                new = {r["span_id"] for r in records if set(r["parent_span_ids"]) & descendants}
                if new <= descendants:
                    break
                descendants |= new
            candidates = [r for r in records if r["span_id"] in descendants - {focal["span_id"]}]
            if not candidates:
                raise ValueError("second logical failure requires a causal descendant")
            focus.append(
                min(
                    candidates,
                    key=lambda r: (-details[r["span_id"]]["compute_start_ns"], r["span_id"]),
                )
            )
        ends = {
            w: max(r["completed_ns"] for r in details.values() if r["workflow_id"] == w)
            for w in selected
        }
        events = []
        for index, record in enumerate(focus):
            span_id = record["span_id"]
            threshold = record["prompt_tokens"] * 600 // 1000
            crossing = []
            for step in reference["representative"]["continuous_batch_scheduler"]["steps"]:
                for participant in step["participants"]:
                    if participant["request_id"] != span_id:
                        continue
                    before = participant["num_computed_tokens_before"]
                    after = participant["num_computed_tokens_after"]
                    if before <= threshold < after:
                        at = step["start_ns"] + (step["planned_end_ns"] - step["start_ns"]) * (
                            threshold - before
                        ) // (after - before)
                        crossing.append((at, step["gpu_id"]))
            if not crossing:
                raise ValueError("failure focus has no fresh prefill crossing")
            at, gpu = min(crossing)
            count = sum(end < at for end in ends.values())
            events.append(
                FailureEventSchedule(
                    f"mechanism-fault-{index}",
                    index,
                    "96k",
                    args.seed,
                    span_id,
                    gpu,
                    at,
                    max(1, min(999, count * 1000 // len(selected))),
                    count,
                    len(selected),
                    0,
                    600,
                    120_000_000_000,
                    selection_scope=selection_scope,
                )
            )
        schedule = FailureSchedule(
            tuple(events), selection_scope="input_selected_logical_focus_paired_across_systems"
        )
        (args.output / "failure-plan.json").write_text(
            json.dumps(schedule.to_dict(), indent=2) + "\n"
        )
    calibration = (
        {} if args.cpu_calibration is None else json.loads(args.cpu_calibration.read_text())
    )
    for system in args.systems:
        start = time.monotonic()
        config = MechanismConfig(
            peer_mode=args.peer_mode,
            cpu_service_ns=round(
                calibration.get("admission_ns", {}).get(system, 0) * args.cpu_scale
            ),
            foreground_cpu_service_ns=round(
                calibration.get("foreground_dispatch_ns", {}).get(
                    system, calibration.get("foreground_lookup_ns", 0)
                )
                * args.cpu_scale
            ),
            slack_enabled=not args.no_slack,
            eager_refresh=args.eager_refresh,
            strict_free_gain=args.strict_free_gain,
            static_peer=args.static_peer,
            dma_slowdown=args.dma_slowdown,
        )
        runtime = MechanismRuntime(
            system=system,
            mechanism_config=config,
            records=records,
            variant=replace(
                mechanism_variant(system, parameters),
                suite="agent-subleases-20260908",
                interpretation="agent_subleases_guarded_AIMD_modeled",
            ),
            context_bucket="96k",
            seed=args.seed,
            failure_schedule=schedule,
            workflow_concurrency=args.concurrency,
            workflow_admission_seed=args.seed,
            peer_binding_seed=0,
        )
        result = runtime.run()
        output = args.output / f"{system}.json.gz"
        if output.exists():
            raise FileExistsError(output)
        with gzip.open(output, "wt", encoding="utf-8") as f:
            json.dump(
                {
                    "payload": result.payload,
                    "representative": result.representative,
                    "span_details": result.span_details,
                },
                f,
                separators=(",", ":"),
            )
        manifest = {
            "schema": "moonkvsim.agent_lease_run.v1",
            "status": "PASS",
            "source_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest()
            if snapshot.exists()
            else None,
            "parameters": parameters.to_dict(),
            "system": system,
            "variant": runtime.variant.to_dict(),
            "algorithm_contract": result.representative["mechanism"]["algorithm_contract"],
            "configuration": result.representative["mechanism"]["configuration"],
            "workload": {
                "workflows": len(selected),
                "requests": len(records),
                "revisit_rounds": args.rounds,
                "workflow_ids": selected,
                "seed": args.seed,
                "concurrency": args.concurrency,
                "input_sha256": hashlib.sha256(
                    (directory / "fanoutqa-dev-qwen3-8b-160.jsonl").read_bytes()
                ).hexdigest(),
            },
            "raw_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "cpu_calibration_sha256": None
            if args.cpu_calibration is None
            else hashlib.sha256(args.cpu_calibration.read_bytes()).hexdigest(),
            "failure_reference_sha256": None
            if args.failure_reference is None
            else hashlib.sha256(args.failure_reference.read_bytes()).hexdigest(),
            "failure_schedule": None if schedule is None else schedule.to_dict(),
            "evidence": {
                "gpu_timing": "uncalibrated_continuous_batch_DES",
                "policy_cpu": "measured_Python_reference_thread_CPU_time",
                "serving_cpu": "modeled_single_controller_service_queue",
                "native_serving_measurement": False,
                "qos_certified": False,
                "algorithm3_mode": args.peer_mode,
            },
        }
        (args.output / f"{system}.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "system": system,
                    "workflows": len(selected),
                    "requests": len(records),
                    "wall_s": round(time.monotonic() - start, 2),
                    "reuse": result.payload["metrics"]["cache_reuse_tokens"],
                    "raw_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
