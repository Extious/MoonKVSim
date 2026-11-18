#!/usr/bin/env python3
"""Predeclared binding-budget test of Slack selection.

The budget and interference coefficient are fixed from earlier evidence before
any run in this directory. Outcomes are not used to choose another budget,
coefficient, load, or fault. Oracle durations come from this campaign's DRAM
healthy run and are not refit after the oracle arm.
"""

from __future__ import annotations

import json
import os
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from moonkvsim.aegiskv.current.__main__ import digest, load_workload, write_json, write_lines
from moonkvsim.aegiskv.current.model import Config, Failure
from moonkvsim.aegiskv.current.runtime import CurrentRuntime
from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile
from moonkvsim.aegiskv.evaluation_walltime_predictor import WalltimePredictor

ROOT = Path(__file__).resolve().parents[5]
PARENT = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/walltime-primary-v3"
OUT = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/mechanism-decision-v1"
MODEL = "Qwen3-8B"
WORKLOAD = "Qwen3-8B-load0.9"
DRAM_BYTES = 8 * 1024**3
DMA = 0.01
POLICIES = ("all_dram", "dram", "oracle")


class F0DurationOracle:
    name = "f0-duration-oracle"
    training_workflows = ()

    def __init__(self, durations: dict[str, int]):
        self.durations = durations
        self.key: str | None = None

    def __call__(self, context) -> int:
        del context
        if self.key is None:
            raise RuntimeError("oracle predictor called outside submission")
        return self.durations[self.key]


class OracleRuntime(CurrentRuntime):
    def __init__(self, config, agents, durations, **kwargs):
        self._oracle = F0DurationOracle(durations)
        super().__init__(
            config,
            agents,
            predictor=self._oracle,
            oracle_duration_ns=durations,
            **kwargs,
        )

    def _submit(self, state):
        previous = self._oracle.key
        self._oracle.key = state.spec.key
        try:
            super()._submit(state)
        finally:
            self._oracle.key = previous


def read_json(path: Path):
    return json.loads(path.read_text())


def parent_jobs():
    plan = read_json(PARENT / "PLAN.json")
    selected = [
        job
        for job in plan["jobs"]
        if job["model"] == MODEL
        and job["workload"] == WORKLOAD
        and job["policy"] in {"all_dram", "dram"}
        and job["fault_index"] in {-1, 0, 1, 2, 3, 4}
    ]
    if len(selected) != 12:
        raise RuntimeError(f"expected 12 parent jobs, found {len(selected)}")
    return plan, selected


def build_job(parent_job, policy: str):
    if policy == "oracle" and parent_job["policy"] != "dram":
        raise RuntimeError("oracle jobs are cloned from the DRAM parent")
    config = dict(parent_job["config"])
    config["dram_bytes_per_host"] = DRAM_BYTES
    config["compute_dma_slowdown"] = DMA
    if policy == "oracle":
        config["slack_mode"] = "oracle"
        config["slack_guard_ns"] = 0
        runtime_policy = "dram"
    else:
        runtime_policy = policy
    fault = "F0" if parent_job["failure"] is None else f"F1-{parent_job['fault_index']}"
    return dict(
        id=f"{MODEL}-load0.9-{policy}-{fault}",
        policy=policy,
        runtime_policy=runtime_policy,
        model=MODEL,
        workload=WORKLOAD,
        fault=fault,
        fault_index=parent_job["fault_index"],
        failure=parent_job["failure"],
        config=config,
        source_job_id=parent_job["id"] if policy != "oracle" else f"{MODEL}-load0.9-dram-{fault}",
        predictor="models/Qwen3-8B.json" if policy != "oracle" else "f0-duration-oracle",
        changed_from_parent=["dram_bytes_per_host", "compute_dma_slowdown"]
        + (["slack_mode", "slack_guard_ns"] if policy == "oracle" else []),
    )


def protocol(plan, jobs):
    return dict(
        schema="aegiskv.mechanism-decision.v1",
        status="frozen_before_execution",
        question=(
            "When Peer DRAM is below the observed healthy host peak and checkpoint "
            "traffic slows compute, does predictor Slack retain a different protected "
            "set and workflow outcome than filling the same budget without the "
            "exposure threshold, and does substituting healthy-run durations change that outcome?"
        ),
        parent=str(PARENT.relative_to(ROOT)),
        parent_plan_sha256=digest(PARENT / "PLAN.json"),
        workload_sha256=plan["workloads"][WORKLOAD]["sha256"],
        workload_content_sha256=plan["workloads"][WORKLOAD]["content_sha256"],
        profile_sha256=digest(PARENT / "profiles" / f"{MODEL}.json"),
        predictor_sha256=digest(PARENT / "models" / f"{MODEL}.json"),
        model=MODEL,
        workload=WORKLOAD,
        workflows=62,
        dram_bytes_per_host=DRAM_BYTES,
        dram_budget_reason=(
            "8 GiB is below the 15.048 GiB healthy AegisKV host peak at this load "
            "in walltime-primary-v3, and it is one of the four capacities already "
            "used by capacity-slack-ablation. It was not selected from this campaign's outcomes."
        ),
        compute_dma_slowdown=DMA,
        dma_reason=(
            "0.01 is the third of the four coefficients already reported by the "
            "low-DMA extension (0.002, 0.005, 0.01, 0.02). It is not a measured "
            "device coefficient and was not selected from this campaign's outcomes."
        ),
        arms=dict(
            all_dram="policy all_dram; every exposed Agent is eligible; scarce slots follow predictor exposure order",
            dram="policy dram; eligibility requires exposed delay above 10 ms; predictor Slack and the 0.910 s guard",
            oracle=(
                "policy dram; Slack CPM uses each Agent's submission-to-completion "
                "latency from this campaign's dram-F0; guard is 0; durations are not refit"
            ),
        ),
        unchanged="workload, arrivals, five fault identities, profile, K, L, lambda, and the hashed-text predictor on the non-oracle arms",
        jobs=jobs,
    )


def prepare():
    plan, selected = parent_jobs()
    dram_jobs = [job for job in selected if job["policy"] == "dram"]
    all_jobs = [job for job in selected if job["policy"] == "all_dram"]
    jobs = [build_job(job, "all_dram") for job in all_jobs]
    jobs += [build_job(job, "dram") for job in dram_jobs]
    jobs += [build_job(job, "oracle") for job in dram_jobs]
    if len(jobs) != 18 or len({job["id"] for job in jobs}) != 18:
        raise RuntimeError("job ids are not the 18 predeclared runs")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runs").mkdir(exist_ok=True)
    payload = protocol(plan, jobs)
    path = OUT / "PROTOCOL.json"
    if path.exists() and read_json(path) != payload:
        raise RuntimeError("existing protocol differs from the predeclared campaign")
    if not path.exists():
        write_json(path, payload)
    return payload


def durations_from_dram_f0() -> dict[str, int]:
    summary = read_json(OUT / "runs" / f"{MODEL}-load0.9-dram-F0" / "summary.json")
    counts: dict[str, int] = {}
    durations: dict[str, int] = {}
    for row in summary["requests"]:
        counts[row["agent"]] = counts.get(row["agent"], 0) + 1
        durations[row["agent"]] = row["latency_ns"]
    if any(count != 1 for count in counts.values()) or len(durations) != 503:
        raise RuntimeError(f"dram-F0 did not yield one latency for each of 503 Agents ({len(durations)})")
    if any(type(value) is not int or value <= 0 for value in durations.values()):
        raise RuntimeError("dram-F0 latency is not a positive integer")
    return durations


def execute(job: dict, durations: dict[str, int] | None):
    target = OUT / "runs" / job["id"]
    if (target / "COMPLETE.json").exists():
        return job["id"], "skipped"
    if target.exists():
        raise RuntimeError(f"incomplete run directory exists: {target}")
    target.mkdir()
    try:
        agents = load_workload(PARENT / "workloads" / f"{WORKLOAD}.json.gz")
        config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
        failure = Failure(**job["failure"]) if job["failure"] else None
        profile = GridDurationProfile(PARENT / "profiles" / f"{MODEL}.json")
        write_json(target / "config.json", job["config"])
        write_json(target / "failure.json", job["failure"])
        if job["policy"] == "oracle":
            if durations is None:
                raise RuntimeError("oracle arm started before dram-F0 durations")
            write_json(target / "oracle-durations.json", durations)
            runtime = OracleRuntime(
                config,
                agents,
                durations,
                policy=job["runtime_policy"],
                failure=failure,
                duration_profile=profile,
                retain_detailed_logs=False,
            )
        else:
            predictor = WalltimePredictor.from_dict(read_json(PARENT / "models" / f"{MODEL}.json"))
            if config.slack_guard_ns != predictor.slack_guard_ns:
                raise RuntimeError("guard differs from the frozen predictor")
            runtime = CurrentRuntime(
                config,
                agents,
                policy=job["runtime_policy"],
                failure=failure,
                predictor=predictor,
                duration_profile=profile,
                retain_detailed_logs=False,
            )
        summary = runtime.run()
        if not all(
            summary.get(key) is True
            for key in ("complete", "terminal_allocations_zero", "output_tokens_exact")
        ):
            raise RuntimeError("runtime acceptance failed")
        if summary.get("oracle_reservation_count") != 0:
            raise RuntimeError("oracle reservation appeared")
        write_json(target / "summary.json", summary)
        write_lines(target / "events.jsonl.gz", runtime.events)
        write_json(
            target / "COMPLETE.json",
            dict(id=job["id"], complete=True, summary_sha256=digest(target / "summary.json")),
        )
        return job["id"], "complete"
    except Exception:
        write_json(target / "FAILED.json", dict(traceback=traceback.format_exc()))
        raise


def run_pool(jobs, durations, workers):
    pending = [job for job in jobs if not (OUT / "runs" / job["id"] / "COMPLETE.json").exists()]
    if not pending:
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(execute, job, durations) for job in pending]
        for future in as_completed(futures):
            job_id, status = future.result()
            print(status, job_id, flush=True)


def target_workflow(summary, failure):
    if not failure:
        return None
    workflow = failure["agent"].split("/", 1)[0]
    return summary["workflows"][workflow]["wct_ns"]


def summarize(jobs):
    rows = []
    by_id = {}
    for job in jobs:
        summary = read_json(OUT / "runs" / job["id"] / "summary.json")
        by_id[job["id"]] = summary
        rows.append(
            dict(
                id=job["id"],
                policy=job["policy"],
                fault=job["fault"],
                checkpoint_commits=summary["metrics"].get("checkpoint_commits", 0),
                dram_budget_skips=summary["metrics"].get("dram_budget_skips", 0),
                slack_fallback_observations=summary["metrics"].get("slack_fallback_observations", 0),
                modeled_dma_compute_slowdown_ns=summary["metrics"].get(
                    "modeled_dma_compute_slowdown_ns", 0
                ),
                target_wct_ns=target_workflow(summary, job["failure"]),
            )
        )
    comparisons = []
    for fault in ("F1-0", "F1-1", "F1-2", "F1-3", "F1-4"):
        for policy in POLICIES:
            healthy = by_id[f"{MODEL}-load0.9-{policy}-F0"]["workflows"]
            failed = by_id[f"{MODEL}-load0.9-{policy}-{fault}"]
            agent = next(job["failure"]["agent"] for job in jobs if job["id"].endswith(f"{policy}-{fault}"))
            workflow = agent.split("/", 1)[0]
            delta = failed["workflows"][workflow]["wct_ns"] - healthy[workflow]["wct_ns"]
            comparisons.append(dict(policy=policy, fault=fault, target_delta_wct_ns=delta))
    write_json(OUT / "SUMMARY.json", dict(runs=rows, target_deltas=comparisons))


def main():
    workers = int(os.environ.get("AEGISKV_WORKERS", "8"))
    payload = prepare()
    jobs = payload["jobs"]
    phase1 = [job for job in jobs if job["policy"] != "oracle"]
    phase2 = [job for job in jobs if job["policy"] == "oracle"]
    run_pool(phase1, None, workers)
    duration_path = OUT / "ORACLE_DURATIONS.json"
    if not duration_path.exists():
        durations = durations_from_dram_f0()
        write_json(duration_path, durations)
    else:
        durations = {key: int(value) for key, value in read_json(duration_path).items()}
    run_pool(phase2, durations, workers)
    summarize(jobs)
    write_json(OUT / "STATUS.json", dict(status="COMPLETE", runs=18))
    print("COMPLETE", OUT)


if __name__ == "__main__":
    main()
