#!/usr/bin/env python3
"""Predeclared external modeled baselines on the sealed primary matrix.

Rules are fixed in EXTERNAL_POLICY_RULES before any run in this directory.
Outcomes are not used to change a policy, load, fault, or budget.
"""

from __future__ import annotations

import json
import os
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from moonkvsim.aegiskv.current.__main__ import digest, load_workload, write_json, write_lines
from moonkvsim.aegiskv.current.model import Config, Failure
from moonkvsim.aegiskv.current.runtime import EXTERNAL_POLICY_RULES, CurrentRuntime
from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile
from moonkvsim.aegiskv.evaluation_walltime_predictor import WalltimePredictor

ROOT = Path(__file__).resolve().parents[5]
PARENT = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/walltime-primary-v3"
OUT = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/external-baseline-v1"
POLICIES = ("fixed_checkpoint", "load_aware_checkpoint", "tail_shadow")
SEALED = ("none", "all_dram", "dram", "aegiskv")
FAULTS = (-1, 0, 1, 2, 3, 4)


def read_json(path: Path):
    return json.loads(path.read_text())


def parent_jobs():
    plan = read_json(PARENT / "PLAN.json")
    selected = [
        job
        for job in plan["jobs"]
        if job["policy"] == "dram" and job["fault_index"] in FAULTS
    ]
    if len(selected) != 36:
        raise RuntimeError(f"expected 36 dram parent templates, found {len(selected)}")
    return plan, selected


def build_job(parent_job, policy: str):
    if policy not in EXTERNAL_POLICY_RULES:
        raise RuntimeError(f"unknown external policy {policy}")
    fault = "F0" if parent_job["failure"] is None else f"F1-{parent_job['fault_index']}"
    job_id = parent_job["id"].replace("-dram-", f"-{policy}-")
    return dict(
        id=job_id,
        policy=policy,
        model=parent_job["model"],
        workload=parent_job["workload"],
        fault=fault,
        fault_index=parent_job["fault_index"],
        failure=parent_job["failure"],
        config=dict(parent_job["config"]),
        source_job_id=parent_job["id"],
        rule=EXTERNAL_POLICY_RULES[policy],
    )


def protocol(plan, jobs):
    return dict(
        schema="aegiskv.external-baseline.v1",
        status="frozen_before_execution",
        question=(
            "On the sealed primary workload, do a modeled fixed checkpoint, a modeled "
            "load-aware checkpoint and retry, and a modeled tail shadow change workflow "
            "completion relative to restart and to complete DRAM checkpoint-and-replay?"
        ),
        not_reproductions=(
            "These arms are modeled policies on this data-parallel runtime. They are not "
            "DéjàVu, LUMEN, or GhostServe. DéjàVu's pipeline streaming, LUMEN's "
            "draft-assisted progressive recovery, and GhostServe's shadow protocol are "
            "not implemented."
        ),
        parent=str(PARENT.relative_to(ROOT)),
        parent_plan_sha256=digest(PARENT / "PLAN.json"),
        rules=EXTERNAL_POLICY_RULES,
        placement_does_not_read="workflow slack, exposed delay E, or HBM gain G",
        unchanged=(
            "256 GiB host DRAM, compute_dma_slowdown 0, workload, arrivals, five fault "
            "identities, profiles, hashed-text predictor, K, L, and lambda"
        ),
        dma_note="Backup traffic is uncharged. This campaign does not replace the 8 GiB binding cell.",
        jobs=jobs,
        workloads={
            name: plan["workloads"][name]
            for name in sorted({job["workload"] for job in jobs})
        },
    )


def prepare():
    plan, selected = parent_jobs()
    jobs = [build_job(job, policy) for job in selected for policy in POLICIES]
    if len(jobs) != 108 or len({job["id"] for job in jobs}) != 108:
        raise RuntimeError("job ids are not the 108 predeclared runs")
    # Parent id is "{model}-load{rho}-dram-F0"; split once so "Qwen3-8B" stays intact.
    for job, parent in zip(jobs, [p for p in selected for _ in POLICIES]):
        expected = parent["id"].replace("-dram-", f"-{job['policy']}-")
        if job["id"] != expected:
            raise RuntimeError(f"job id {job['id']} != {expected}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runs").mkdir(exist_ok=True)
    payload = protocol(plan, jobs)
    path = OUT / "PROTOCOL.json"
    if path.exists() and read_json(path) != payload:
        raise RuntimeError("existing protocol differs from the predeclared campaign")
    if not path.exists():
        write_json(path, payload)
    return payload


def workflow_wct(summary) -> dict[str, int]:
    return {key: row["wct_ns"] for key, row in summary["workflows"].items()}


def smoke():
    path = OUT / "SMOKE.json"
    if path.exists():
        payload = read_json(path)
        if payload.get("workflow_wct_match") is not True:
            raise RuntimeError("recorded smoke test does not match the sealed dram F0 run")
        return payload
    parent = next(
        job
        for job in read_json(PARENT / "PLAN.json")["jobs"]
        if job["id"] == "Qwen3-8B-load0.9-dram-F0"
    )
    agents = load_workload(PARENT / "workloads" / "Qwen3-8B-load0.9.json.gz")
    config = Config(**{**parent["config"], "hosts": tuple(parent["config"]["hosts"])})
    predictor = WalltimePredictor.from_dict(read_json(PARENT / "models" / "Qwen3-8B.json"))
    if config.slack_guard_ns != predictor.slack_guard_ns:
        raise RuntimeError("smoke guard differs from the frozen predictor")
    runtime = CurrentRuntime(
        config,
        agents,
        policy="dram",
        failure=None,
        predictor=predictor,
        duration_profile=GridDurationProfile(PARENT / "profiles" / "Qwen3-8B.json"),
        retain_detailed_logs=False,
    )
    summary = runtime.run()
    sealed = read_json(PARENT / "runs" / "Qwen3-8B-load0.9-dram-F0" / "summary.json")
    current, reference = workflow_wct(summary), workflow_wct(sealed)
    mismatch = sorted(key for key in reference if current.get(key) != reference[key])
    payload = dict(
        id="Qwen3-8B-load0.9-dram-F0",
        policy="dram",
        workflows=len(reference),
        workflow_wct_match=mismatch == [],
        mismatched_workflows=mismatch[:8],
        mismatch_count=len(mismatch),
    )
    write_json(path, payload)
    if mismatch:
        raise RuntimeError(
            f"smoke WCT mismatch on {len(mismatch)} workflows; do not cite sealed primary numbers"
        )
    print("smoke match", len(reference), flush=True)
    return payload


def execute(job: dict):
    target = OUT / "runs" / job["id"]
    if (target / "COMPLETE.json").exists():
        return job["id"], "skipped"
    if target.exists():
        raise RuntimeError(f"incomplete run directory exists: {target}")
    target.mkdir()
    try:
        agents = load_workload(PARENT / "workloads" / f"{job['workload']}.json.gz")
        config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
        failure = Failure(**job["failure"]) if job["failure"] else None
        predictor = WalltimePredictor.from_dict(read_json(PARENT / "models" / f"{job['model']}.json"))
        if config.slack_guard_ns != predictor.slack_guard_ns:
            raise RuntimeError("guard differs from the frozen predictor")
        if config.dram_bytes_per_host != 256 * 1024**3 or config.compute_dma_slowdown != 0:
            raise RuntimeError("external baseline changed the sealed DRAM cap or DMA coefficient")
        runtime = CurrentRuntime(
            config,
            agents,
            policy=job["policy"],
            failure=failure,
            predictor=predictor,
            duration_profile=GridDurationProfile(PARENT / "profiles" / f"{job['model']}.json"),
            retain_detailed_logs=False,
        )
        summary = runtime.run()
        if not all(
            summary.get(key) is True
            for key in ("complete", "terminal_allocations_zero", "output_tokens_exact")
        ):
            raise RuntimeError("runtime acceptance failed")
        if summary.get("external_policy_rule") != job["rule"]:
            raise RuntimeError("run rule differs from the predeclared protocol")
        agents_committed = sorted(
            {event["agent"] for event in runtime.events if event["kind"] == "checkpoint_commit"}
        )
        write_json(target / "config.json", job["config"])
        write_json(target / "failure.json", job["failure"])
        write_json(target / "summary.json", summary)
        write_json(target / "checkpoint-agents.json", agents_committed)
        write_lines(target / "events.jsonl.gz", runtime.events)
        write_json(
            target / "COMPLETE.json",
            dict(id=job["id"], complete=True, summary_sha256=digest(target / "summary.json")),
        )
        return job["id"], "complete"
    except Exception:
        write_json(target / "FAILED.json", dict(traceback=traceback.format_exc()))
        raise


def run_pool(jobs, workers):
    pending = [job for job in jobs if not (OUT / "runs" / job["id"] / "COMPLETE.json").exists()]
    if not pending:
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(execute, job) for job in pending]
        for future in as_completed(futures):
            job_id, status = future.result()
            print(status, job_id, flush=True)


def mean_wct(summary) -> int:
    values = [row["wct_ns"] for row in summary["workflows"].values()]
    return sum(values) // len(values)


def target_delta(healthy, failed, failure) -> int | None:
    if not failure:
        return None
    workflow = failure["agent"].split("/", 1)[0]
    return failed["workflows"][workflow]["wct_ns"] - healthy["workflows"][workflow]["wct_ns"]


def sealed_summary(model, workload, policy, fault):
    del model
    path = PARENT / "runs" / f"{workload}-{policy}-{fault}" / "summary.json"
    return read_json(path)


def summarize(jobs):
    by_id = {}
    rows = []
    for job in jobs:
        summary = read_json(OUT / "runs" / job["id"] / "summary.json")
        by_id[job["id"]] = summary
        committed = read_json(OUT / "runs" / job["id"] / "checkpoint-agents.json")
        target = None
        agent_latency = None
        if job["failure"]:
            target_agent = job["failure"]["agent"]
            matched = [row for row in summary["recoveries"] if row["agent"] == target_agent]
            if len(matched) != 1:
                raise RuntimeError(f"{job['id']} target recovery count is {len(matched)}")
            agent_latency = matched[0]["latency_ns"]
            workflow = target_agent.split("/", 1)[0]
            target = summary["workflows"][workflow]["wct_ns"]
        rows.append(
            dict(
                id=job["id"],
                policy=job["policy"],
                model=job["model"],
                workload=job["workload"],
                fault=job["fault"],
                mean_wct_ns=mean_wct(summary),
                target_wct_ns=target,
                agent_latency_ns=agent_latency,
                checkpoint_commits=summary["metrics"].get("checkpoint_commits", 0),
                checkpoint_agents=len(committed),
                peak_replica_dram=summary["peak_bytes"].get("replica_dram", 0),
                peak_replica_hbm=summary["peak_bytes"].get("replica_hbm", 0),
            )
        )
    comparisons = []
    for job in jobs:
        if job["fault"] == "F0":
            continue
        healthy = by_id[job["id"].replace(job["fault"], "F0")]
        failed = by_id[job["id"]]
        delta = target_delta(healthy, failed, job["failure"])
        sealed_deltas = {}
        for policy in SEALED:
            sealed_h = sealed_summary(job["model"], job["workload"], policy, "F0")
            sealed_f = sealed_summary(job["model"], job["workload"], policy, job["fault"])
            sealed_deltas[policy] = target_delta(sealed_h, sealed_f, job["failure"])
        comparisons.append(
            dict(
                id=job["id"],
                policy=job["policy"],
                model=job["model"],
                workload=job["workload"],
                fault=job["fault"],
                target_delta_wct_ns=delta,
                sealed_target_delta_wct_ns=sealed_deltas,
                mean_failure_wct_ns=mean_wct(failed),
                agent_latency_ns=next(
                    row["agent_latency_ns"] for row in rows if row["id"] == job["id"]
                ),
            )
        )
    write_json(OUT / "SUMMARY.json", dict(runs=rows, target_deltas=comparisons))


def main():
    workers = int(os.environ.get("AEGISKV_WORKERS", "12"))
    payload = prepare()
    smoke()
    run_pool(payload["jobs"], workers)
    summarize(payload["jobs"])
    write_json(OUT / "STATUS.json", dict(status="COMPLETE", runs=108))
    print("COMPLETE", OUT)


if __name__ == "__main__":
    main()
