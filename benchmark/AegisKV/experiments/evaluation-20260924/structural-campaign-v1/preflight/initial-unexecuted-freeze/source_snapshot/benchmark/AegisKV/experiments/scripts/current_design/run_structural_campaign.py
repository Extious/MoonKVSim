#!/usr/bin/env python3
"""Frozen constructed-intervention campaign, separate from observed trace evidence.

prepare freezes 143 jobs and source inputs; run re-execs the snapshotted runner.
All agents execute one original DAG. No fitting or outcome-based selection occurs.
"""
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from pathlib import Path
from statistics import mean
from time import monotonic

ROOT = Path(__file__).resolve().parents[5]
RELATIVE_SCRIPT = Path(__file__).resolve().relative_to(ROOT)
sys.path.insert(0, str(ROOT / "python"))

from moonkvsim.aegiskv.current.__main__ import (  # noqa: E402
    digest,
    encoded,
    load_workload,
    manifest,
    percentile,
    run_one,
    write_json,
)
from moonkvsim.aegiskv.current.model import Config, Failure  # noqa: E402
from moonkvsim.aegiskv.evaluation_campaign import model_config, save_workload  # noqa: E402
from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile  # noqa: E402
from moonkvsim.aegiskv.evaluation_scenarios import (  # noqa: E402
    SCENARIO_NAMES,
    SyntheticPhaseDemand,
    build_evaluation_scenario,
)

INPUTS = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/inputs"
SEEDS = (7, 19, 41)
POLICIES = ("none", "dram", "aegiskv")
FAULTS = ("F0", "left.prefill", "left.decode")
_INPUT_CACHE = {}
_PROFILE_CACHE = {}


def prepare(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if (out / "PLAN.json").exists():
        raise FileExistsError("refusing to overwrite a frozen plan")
    for directory in ("workloads", "profiles", "runs"):
        (out / directory).mkdir(exist_ok=True)
    profile_path = out / "profiles/Qwen3-8B.json"
    shutil.copy2(INPUTS / "duration-profiles/Qwen3-8B.json", profile_path)
    profile = GridDurationProfile(profile_path)
    jobs, workloads = [], {}
    cases = [(name, 8, SEEDS, POLICIES, FAULTS) for name in SCENARIO_NAMES]
    cases += [
        ("history_reuse", size, (7,), ("dram", "aegiskv"), ("F0", "left.decode"))
        for size in (32, 128)
    ]
    for name, count, seeds, policies, faults in cases:
        for seed in seeds:
            workload_id = f"{name}-n{count}-s{seed}"
            scenario = build_evaluation_scenario(
                name, model=profile.data["model"], workflows=count, seed=seed
            )
            config = replace(
                model_config(profile, dp=4), hosts=tuple(scenario.metadata["recommended_hosts"])
            )
            if scenario.demand_provider:
                config = replace(config, attention="synthetic_sparse")
            scenario.validate_config(config)
            path = out / "workloads" / f"{workload_id}.json.gz"
            workload_hash = save_workload(path, scenario.agents)
            write_json(path.with_suffix(".metadata.json"), scenario.metadata)
            workloads[workload_id] = {
                "path": str(path.relative_to(out)),
                "sha256": workload_hash,
                "metadata": str(path.with_suffix(".metadata.json").relative_to(out)),
            }
            for policy in policies:
                for fault in faults:
                    identity = f"{workload_id}-{policy}-{fault}"
                    detailed = (
                        name in {"forkjoin_skew", "long_decode_drift"}
                        and count == 8
                        and seed == 7
                        and policy == "aegiskv"
                        and fault == "left.decode"
                    )
                    jobs.append(
                        {
                            "id": identity,
                            "scenario": name,
                            "workflows": count,
                            "seed": seed,
                            "policy": policy,
                            "fault": fault,
                            "workload_id": workload_id,
                            "config": asdict(config),
                            "failure": asdict(scenario.failures[fault]) if fault != "F0" else None,
                            "failure_descriptor": scenario.metadata["faults"].get(fault),
                            "demand_provider": asdict(scenario.demand_provider)
                            if scenario.demand_provider
                            else None,
                            "retain_detailed_logs": detailed,
                            "f0_id": f"{workload_id}-{policy}-F0",
                        }
                    )
    assert len(jobs) == 143
    assert sum(job["retain_detailed_logs"] for job in jobs) == 2
    source = manifest(out)
    # Snapshot all Python modules and this runner: workers never import mutable
    # live sources while another agent edits the repository.
    for path in [*sorted((ROOT / "python/moonkvsim").rglob("*.py")), Path(__file__).resolve()]:
        relative = path.relative_to(ROOT)
        target = out / "source_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        source["source_sha256"][str(relative)] = digest(target)
    source.update(
        {
            "timing": "AIC mixed empirical/silicon GridDurationProfile plus shared byte-flow DES",
            "original_root": str(ROOT),
            "source_execution": "snapshotted Python modules",
            "prediction": "fixed role prior constants; no predictor-accuracy evidence",
            "workload_class": "constructed four-Agent, multi-invocation interventions",
            "native_sparse_model": False,
            "reservation": "known prompt plus submitted fixed 16384-token output cap",
        }
    )
    write_json(out / "MANIFEST.json", source)
    write_json(
        out / "PLAN.json",
        {
            "schema": "aegiskv.structural-campaign.v1",
            "job_count": len(jobs),
            "seeds": SEEDS,
            "policies": POLICIES,
            "scenarios": SCENARIO_NAMES,
            "main_matrix": "5 scenarios x 3 seeds x 3 policies x 3 faults x 8 workflows = 135 runs",
            "scale_matrix": "history_reuse x {32,128} workflows x seed7 x {dram,aegiskv} x {F0,left.decode} = 8 runs",
            "profile": "profiles/Qwen3-8B.json",
            "profile_sha256": digest(profile_path),
            "workloads": workloads,
            "jobs": jobs,
            "statistical_unit": "workflow paired to own-policy F0; seed is a constructed replicate",
            "causal_claim_limits": [
                "Synthetic random token IDs, prescribed lengths, DAG and arrival process are interventions.",
                "Role remaining-time priors are fixed proxies, not trained or accuracy-validated predictions.",
                "Long-decode hot-bank selection is synthetic; its compute durations use a dense Qwen3 profile.",
                "No native attention kernel, physical GPU execution, or real serving trace is reproduced.",
                "Same-ID logical progress faults occur at policy-specific wall times; capacity loss can delay collateral work.",
                "Three constructed seeds do not establish population-tail significance; no request-level confidence interval.",
                "Detailed logs retained for exactly two prespecified runs; all runs retain summaries and coarse events.",
            ],
        },
    )
    print(f"frozen {len(jobs)} jobs in {out}", flush=True)


def verify(out: Path) -> dict:
    plan = json.loads((out / "PLAN.json").read_text())
    source = json.loads((out / "MANIFEST.json").read_text())
    for name, expected in source["source_sha256"].items():
        if digest(out / "source_snapshot" / name) != expected:
            raise ValueError(f"frozen source changed: {name}")
    if digest(out / plan["profile"]) != plan["profile_sha256"]:
        raise ValueError("frozen profile changed")
    return plan


def execute(payload) -> dict:
    out_text, job, specification, profile_relative = payload
    out = Path(out_text)
    target = out / "runs" / job["id"]
    complete = target / "COMPLETE.json"
    if complete.exists():
        record = json.loads(complete.read_text())
        if digest(target / "summary.json") != record["summary_sha256"]:
            raise ValueError(f"completed summary changed: {job['id']}")
        if digest(target / "config.json") != record["config_sha256"]:
            raise ValueError(f"completed config changed: {job['id']}")
        return record
    if target.exists():
        raise FileExistsError(f"partial run preserved; inspect before retry: {target}")
    path = out / specification["path"]
    if path not in _INPUT_CACHE:
        agents = load_workload(path)
        actual = hashlib.sha256(encoded([asdict(agent) for agent in agents])).hexdigest()
        if actual != specification["sha256"]:
            raise ValueError("workload hash mismatch")
        _INPUT_CACHE[path] = agents
    profile_path = out / profile_relative
    if profile_path not in _PROFILE_CACHE:
        _PROFILE_CACHE[profile_path] = GridDurationProfile(profile_path)
    config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
    failure = Failure(**job["failure"]) if job["failure"] else None
    provider = SyntheticPhaseDemand(**job["demand_provider"]) if job["demand_provider"] else None
    start = monotonic()
    result = run_one(
        target,
        config,
        _INPUT_CACHE[path],
        job["policy"],
        failure,
        duration_profile=_PROFILE_CACHE[profile_path],
        demand_provider=provider,
        retain_detailed_logs=job["retain_detailed_logs"],
        journal=job["retain_detailed_logs"],
    )
    if result["workload_sha256"] != specification["sha256"]:
        raise ValueError("run changed the workload")
    if result["oracle_reservation_count"]:
        raise ValueError("formal campaign used future output length for primary reservation")
    descriptor = job["failure_descriptor"]
    if descriptor and result["failure"]["logical_tokens"] != descriptor["logical_trigger_tokens"]:
        raise ValueError("actual failure differs from frozen logical phase trigger")
    record = {
        "id": job["id"],
        "summary_sha256": digest(target / "summary.json"),
        "config_sha256": digest(target / "config.json"),
        "wall_seconds": monotonic() - start,
    }
    write_json(complete, record)
    return record


def run(out: Path, workers: int) -> None:
    plan = verify(out)
    records = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = {
            pool.submit(
                execute, (str(out), job, plan["workloads"][job["workload_id"]], plan["profile"])
            ): job
            for job in plan["jobs"]
        }
        for future in as_completed(pending):
            record = future.result()
            records.append(record)
            write_json(
                out / "STATUS.json",
                {"completed": len(records), "total": len(pending), "latest": record["id"]},
            )
            print(
                f"{len(records)}/{len(pending)} {record['id']} {record['wall_seconds']:.2f}s",
                flush=True,
            )
    write_json(out / "RUNS.json", sorted(records, key=lambda row: row["id"]))
    summarize(out)


def write_csv(path: Path, rows: list[dict]) -> None:
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def summarize(out: Path) -> None:
    plan = verify(out)
    results, raw, paired, checks, audits = {}, [], [], [], []
    for job in plan["jobs"]:
        path = out / "runs" / job["id"]
        complete = json.loads((path / "COMPLETE.json").read_text())
        if digest(path / "summary.json") != complete["summary_sha256"]:
            raise ValueError("summary hash mismatch")
        result = json.loads((path / "summary.json").read_text())
        results[job["id"]] = result
        wct = [value["wct_ns"] / 1e9 for value in result["workflows"].values()]
        fields = {
            key: job[key] for key in ("id", "scenario", "workflows", "seed", "policy", "fault")
        }
        raw.append(
            {
                **fields,
                "mean_wct_s": mean(wct),
                "p95_wct_s": percentile(wct, 0.95),
                "p99_wct_s": percentile(wct, 0.99),
                "max_wct_s": max(wct),
                "run_wall_seconds": complete["wall_seconds"],
                "failure_time_s": result["failure"]["time_ns"] / 1e9 if result["failure"] else "",
                "recoveries": len(result["recoveries"]),
                **{f"metric_{key}": value for key, value in result["metrics"].items()},
                **{f"peak_{key}": value for key, value in result["peak_bytes"].items()},
            }
        )
        if job["retain_detailed_logs"]:
            with gzip.open(path / "events.jsonl.gz", "rt") as stream:
                events = [json.loads(line) for line in stream]
            updates = [
                event for event in events if event.get("kind", event.get("event")) == "topk_update"
            ]
            audits.append(
                {
                    **fields,
                    "event_count": len(events),
                    "topk_update_events": len(updates),
                    "event_fields": list(events[0]) if events else [],
                    "events_sha256": digest(path / "events.jsonl.gz"),
                    "flows_sha256": digest(path / "flows.jsonl.gz"),
                    "journal_sha256": digest(path / "journal.jsonl.gz"),
                    "recoveries": result["recoveries"],
                    "failure": result["failure"],
                }
            )
    for job in plan["jobs"]:
        if job["fault"] == "F0":
            continue
        f0, f1 = results[job["f0_id"]], results[job["id"]]
        valid = {
            "id": job["id"],
            "same_workload": f0["workload_sha256"] == f1["workload_sha256"],
            "same_config": f0["config_sha256"] == f1["config_sha256"],
            "same_workflows": f0["workflows"].keys() == f1["workflows"].keys(),
            "complete": f0["complete"] and f1["complete"],
            "outputs_exact": f0["output_tokens_exact"] and f1["output_tokens_exact"],
            "no_leaks": f0["terminal_allocations_zero"] and f1["terminal_allocations_zero"],
            "no_oracle_reservation": not (
                f0["oracle_reservation_count"] or f1["oracle_reservation_count"]
            ),
        }
        checks.append(valid)
        if not all(value for key, value in valid.items() if key != "id"):
            raise ValueError(f"paired validity check failed: {job['id']}")
        victims = {row["agent"].split("/")[0] for row in f1["recoveries"]}
        for workflow in f0["workflows"]:
            normal = f0["workflows"][workflow]["wct_ns"] / 1e9
            failed = f1["workflows"][workflow]["wct_ns"] / 1e9
            paired.append(
                {
                    **{
                        key: job[key]
                        for key in ("scenario", "workflows", "seed", "policy", "fault")
                    },
                    "id": job["id"],
                    "workflow": workflow,
                    "target_workflow": workflow == job["failure"]["agent"].split("/")[0],
                    "interrupted_workflow": workflow in victims,
                    "f0_wct_s": normal,
                    "f1_wct_s": failed,
                    "delta_wct_s": failed - normal,
                    "relative_delta": (failed - normal) / normal,
                }
            )
    aggregates = []
    groups = defaultdict(list)
    for row in paired:
        groups[(row["scenario"], row["workflows"], row["policy"], row["fault"])].append(row)
    for (scenario, count, policy, fault), values in groups.items():
        deltas = [row["delta_wct_s"] for row in values]
        target = [row["delta_wct_s"] for row in values if row["target_workflow"]]
        aggregates.append(
            {
                "scenario": scenario,
                "workflows": count,
                "policy": policy,
                "fault": fault,
                "constructed_seeds": len({row["seed"] for row in values}),
                "workflow_observations": len(values),
                "mean_delta_wct_s": mean(deltas),
                "p95_delta_wct_s": percentile(deltas, 0.95),
                "p99_delta_wct_s": percentile(deltas, 0.99),
                "target_mean_delta_wct_s": mean(target),
                "negative_delta_count": sum(value < 0 for value in deltas),
            }
        )
    write_csv(out / "raw-runs.csv", raw)
    write_csv(out / "paired-workflows.csv", paired)
    write_csv(out / "summary.csv", aggregates)
    write_json(
        out / "VALIDATION.json",
        {"all_passed": True, "runs": len(raw), "pairs": len(checks), "checks": checks},
    )
    write_json(out / "TRACE_AUDIT.json", audits)
    write_json(
        out / "SUMMARY.json",
        {
            "runs": len(raw),
            "paired_workflow_rows": len(paired),
            "descriptive_only": True,
            "rows": aggregates,
            "claim_limits": plan["causal_claim_limits"],
        },
    )
    (out / "README.md").write_text(
        "# Constructed structural campaign v1\n\n"
        "143 frozen runs: five prescribed four-Agent DAG interventions, three seeds and three policies; "
        "additional history-reuse scale controls use 32 and 128 independent workflows. "
        "Each DAG executes once. Workload token IDs, arrivals, role priors and phase-drift patterns are constructed.\n\n"
        "Qwen3-8B TP1 / DP4 uses the pinned AIC duration grid; no GPU inference is executed. "
        "All calls declare a fixed 16K output cap for admission. Role priors are hand-set proxies; "
        "this campaign cannot establish remaining-time prediction accuracy. Long-decode drift combines "
        "constructed sparse selection with dense-model compute cost; it is not a native sparse model run.\n\n"
        "PLAN.json freezes the matrix, every workload hash, failure identity and total-token trigger. "
        "MANIFEST.json and source_snapshot/ pin the executed sources. Formal run results live in runs/. "
        "smoke/ is excluded from all formal tables. Two prespecified formal runs retain detailed "
        "event, flow and journal logs, indexed by TRACE_AUDIT.json.\n\n"
        "raw-runs.csv contains one row per run and all counters; paired-workflows.csv contains same-ID "
        "F1 minus its own-policy F0, including negative and collateral outcomes. summary.csv reports "
        "descriptive mean/p95/p99 without significance claims or request-as-independent confidence intervals. "
        "The worker or host remains failed, so collateral capacity-loss effects are part of F1.\n\n"
        "VALIDATION.json checks hashes, paired input/config/IDs, exact outputs, zero residual allocations "
        "and absence of output-length-oracle admission. Evidence remains modeled and uncalibrated for "
        "integrated serving: no continuous batching or measured DMA/compute interference is represented.\n"
    )
    print(f"summarized {len(raw)} runs / {len(paired)} paired workflows", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "summarize"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command != "prepare":
        frozen = out / "source_snapshot" / RELATIVE_SCRIPT
        if frozen.resolve() != Path(__file__).resolve():
            os.execv(
                sys.executable,
                [
                    sys.executable,
                    str(frozen),
                    args.command,
                    "--out",
                    str(out),
                    "--workers",
                    str(args.workers),
                ],
            )
    if args.command == "prepare":
        prepare(out)
    elif args.command == "run":
        run(out, args.workers)
    else:
        summarize(out)


if __name__ == "__main__":
    main()
