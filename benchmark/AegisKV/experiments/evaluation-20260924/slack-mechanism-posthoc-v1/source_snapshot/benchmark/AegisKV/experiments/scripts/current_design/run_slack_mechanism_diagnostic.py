#!/usr/bin/env python3
"""Ten prespecified post-hoc constructed DRAM/Slack mechanism runs.

The observational subclass only copies state at the original failure entry.
No simulator implementation, policy, timing, or scheduling rule is changed.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import random
import shutil
import sys
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[5]
RELATIVE_SCRIPT = Path(__file__).resolve().relative_to(ROOT)
sys.path.insert(0, str(ROOT / "python"))

from moonkvsim.aegiskv.current.__main__ import (  # noqa: E402
    digest,
    encoded,
    load_workload,
    manifest,
    run_one,
    write_json,
    write_lines,
)
from moonkvsim.aegiskv.current.model import Agent, Config, Failure, Invocation  # noqa: E402
from moonkvsim.aegiskv.current.runtime import CurrentRuntime  # noqa: E402
from moonkvsim.aegiskv.current.tracker import Estimate, Tracker  # noqa: E402
from moonkvsim.aegiskv.evaluation_campaign import model_config, save_workload  # noqa: E402
from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile  # noqa: E402

CAMPAIGNS = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"


def read(path):
    return json.loads(path.read_text())


def value_hash(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def prepare(out):
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    for name in ("runs", "profiles", "workloads"):
        (out / name).mkdir()
    profile_file = out / "profiles/Qwen3-8B.json"
    shutil.copy2(CAMPAIGNS / "inputs/duration-profiles/Qwen3-8B.json", profile_file)
    profile = GridDurationProfile(profile_file)
    config = replace(
        model_config(profile, dp=3),
        hosts=(0, 0, 1),
        hbm_cap_bytes=0,
        initial_quota_bytes=0,
        max_time_ns=300 * 10**9,
        slack_guard_ns=0,
    )
    rng = random.Random(7)
    specs = [
        ("root", (), 512, 16, 5),
        ("a_critical", ("root",), 1024, 8192, 120),
        ("b_expensive", ("root",), 8192, 2048, 40),
        ("join", ("a_critical", "b_expensive"), 512, 16, 5),
    ]
    agents = tuple(
        Agent(
            "wf0",
            name,
            parents,
            (
                Invocation(
                    tuple(rng.randrange(32_000) for _ in range(prompt)),
                    tuple(rng.randrange(32_000) for _ in range(output)),
                    model=profile.data["model"],
                    output_limit_tokens=16_384,
                ),
            ),
            prior * 10**9,
            role=name,
        )
        for name, parents, prompt, output, prior in specs
    )
    workload_hash = save_workload(out / "workloads/workflow.json.gz", agents)
    failure = Failure("wf0/a_critical", 0, (1536 - 0.5) / 9216, "worker")
    jobs = []
    for budget in (5 * 2**30 // 4, 4 * 2**30):
        for variant, policy, slack in (("dag", "dram", "dag"), ("zero", "dram", "zero")):
            for fault in (False, True):
                identity = f"dram{budget}-{variant}-F{int(fault)}"
                jobs.append(
                    dict(
                        id=identity,
                        budget_bytes=budget,
                        variant=variant,
                        policy=policy,
                        config=asdict(
                            replace(config, dram_bytes_per_host=budget, slack_mode=slack)
                        ),
                        failure=asdict(failure) if fault else None,
                        f0_id=f"dram{budget}-{variant}-F0",
                    )
                )
    for fault in (False, True):
        jobs.append(
            dict(
                id=f"restart-F{int(fault)}",
                budget_bytes=5 * 2**30 // 4,
                variant="restart",
                policy="none",
                config=asdict(replace(config, dram_bytes_per_host=5 * 2**30 // 4)),
                failure=asdict(failure) if fault else None,
                f0_id="restart-F0",
            )
        )
    arithmetic = []
    for frontier in (1280, 1536, 8192, 8448, 8704):
        committed = config.checkpoint_bytes(frontier)
        append = config.prefix_bytes(256) + config.layers * config.metadata_layer_bytes(
            frontier + 256
        )
        arithmetic.append(
            dict(
                frontier=frontier,
                complete_bytes=committed,
                next_append_bytes=append,
                committed_plus_pending_bytes=committed + append,
            )
        )
    tight = 5 * 2**30 // 4
    assert config.checkpoint_bytes(8192) > 9 * 2**30 // 8
    assert all(r["committed_plus_pending_bytes"] < tight for r in arithmetic)
    assert config.checkpoint_bytes(1280) + config.checkpoint_bytes(8448) > tight
    protocol_source = (
        CAMPAIGNS / "structural-campaign-v1/reports/POSTHOC_SLACK_MECHANISM_PROTOCOL.md"
    )
    shutil.copy2(protocol_source, out / "PROTOCOL.md")
    write_json(
        out / "PLAN.json",
        dict(
            schema="aegiskv.posthoc-slack-mechanism.v1",
            evidence="post-hoc constructed mechanism diagnostic; not natural evidence or predictor validation",
            jobs=jobs,
            profile="profiles/Qwen3-8B.json",
            profile_sha256=digest(profile_file),
            workload="workloads/workflow.json.gz",
            workload_sha256=workload_hash,
            workload_compressed_sha256=digest(out / "workloads/workflow.json.gz"),
            protocol_sha256=digest(out / "PROTOCOL.md"),
            capacity_arithmetic=arithmetic,
            rejected_before_execution_budget_bytes=9 * 2**30 // 8,
            tight_budget_bytes=tight,
            no_outcome_based_selection=True,
            observer="Read-only _fail entry wrapper plus after-event invariant snapshots; no extra DES events; offline Slack reconstruction on copied Tracker state.",
        ),
    )
    source = manifest(out)
    for path in [*sorted((ROOT / "python/moonkvsim").rglob("*.py")), Path(__file__).resolve()]:
        relative = path.relative_to(ROOT)
        target = out / "source_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        source["source_sha256"][str(relative)] = digest(target)
    source.update(
        {
            "original_root": str(ROOT),
            "plan_sha256": digest(out / "PLAN.json"),
            "execution": "frozen snapshot with read-only diagnostic hooks",
        }
    )
    write_json(out / "MANIFEST.json", source)
    write_json(
        out / "SEAL.json",
        {n: digest(out / n) for n in ("PLAN.json", "MANIFEST.json", "PROTOCOL.md")},
    )
    print("frozen 10 runs; no simulation executed", flush=True)


def verify(out):
    for name, expected in read(out / "SEAL.json").items():
        assert digest(out / name) == expected
    plan, source = read(out / "PLAN.json"), read(out / "MANIFEST.json")
    for name, expected in source["source_sha256"].items():
        assert digest(out / "source_snapshot" / name) == expected, name
    assert digest(out / plan["profile"]) == plan["profile_sha256"]
    assert digest(out / plan["workload"]) == plan["workload_compressed_sha256"]
    assert len(plan["jobs"]) == len({j["id"] for j in plan["jobs"]}) == 10
    return plan


def snapshot(runtime):
    states = {}
    for key, state in runtime.states.items():
        states[key] = {
            name: getattr(state, name)
            for name in (
                "call",
                "worker",
                "peer",
                "computed",
                "durable",
                "epoch",
                "started",
                "submitted",
                "finished",
            )
        }
        states[key]["checkpoint_identity"] = state.checkpoint.identity if state.checkpoint else None
        states[key]["recovering_identity"] = state.recovering.identity if state.recovering else None
    checkpoints = []
    for cp in runtime.checkpoints:
        if cp.retired and not (cp.frontier or cp.pending or cp.readers):
            continue
        row = {
            name: getattr(cp, name)
            for name in (
                "key",
                "identity",
                "source",
                "peer",
                "frontier",
                "pending",
                "pending_bytes",
                "readers",
                "retired",
            )
        }
        row.update(
            host=runtime.config.hosts[cp.peer],
            account=cp.account,
            allocated_bytes=runtime.ledgers[f"dram:{runtime.config.hosts[cp.peer]}"].bytes_in(
                cp.account
            ),
        )
        checkpoints.append(row)
    return dict(
        time_ns=runtime.des.now_ns,
        fault_fired=runtime.fault_fired,
        states=states,
        checkpoints=checkpoints,
        tracker={k: asdict(v) for k, v in runtime.tracker.states.items()},
        dram_accounts={
            k: dict(v.accounts) for k, v in runtime.ledgers.items() if k.startswith("dram:")
        },
        queues={str(k): list(v) for k, v in runtime.queues.items()},
        busy=dict(runtime.busy),
        alive=sorted(runtime.alive),
    )


class ObservedRuntime(CurrentRuntime):
    """Copy state at the original failure boundary; invoke base method once."""

    failure_entry = None

    def _fail(self, target):
        self.failure_entry = snapshot(self)
        super()._fail(target)


def offline_scores(frame, agents, config, profile):
    tracker = Tracker(agents, config)
    tracker.states = {k: Estimate(**v) for k, v in frame["tracker"].items()}
    raw_slack = tracker.slack(frame["time_ns"])
    result = {}
    for key, state in frame["states"].items():
        full = profile.duration(
            0, state["durable"], "prefill", config.prefill_chunk_tokens, config.checkpoint_tokens
        )
        slack = raw_slack[key] if config.slack_mode == "dag" else 0
        result[key] = dict(
            guarded_dag_slack_ns=raw_slack[key],
            effective_slack_ns=slack,
            full_reconstruction_ns=full,
            exposure_ns=max(0, full - slack),
            computed_checkpoint_candidate_bytes=config.checkpoint_bytes(
                state["computed"] // config.checkpoint_tokens * config.checkpoint_tokens
            )
            * config.tp,
        )
    return dict(agents=result, fallback_workflows=sorted(tracker.fallback_workflows))


def binding(out, plan, job):
    return dict(
        id=job["id"],
        plan_sha256=digest(out / "PLAN.json"),
        manifest_sha256=digest(out / "MANIFEST.json"),
        job_sha256=value_hash(job),
        workload_sha256=plan["workload_sha256"],
        profile_sha256=plan["profile_sha256"],
    )


def validate(out, plan, job):
    path = out / "runs" / job["id"]
    complete, result = read(path / "COMPLETE.json"), read(path / "summary.json")
    for key, expected in binding(out, plan, job).items():
        assert complete[key] == expected
    for name, expected in complete["artifacts_sha256"].items():
        assert digest(path / name) == expected
    assert read(path / "config.json") == job["config"]
    assert read(path / "failure.json") == job["failure"]
    assert result["workload_sha256"] == plan["workload_sha256"]
    assert result["config_sha256"] == digest(path / "config.json")
    assert result["policy"] == job["policy"] and result["predictor"] == "prior_predictor"
    assert result["duration_profile"] == "GridDurationProfile"
    assert (
        result["complete"]
        and result["terminal_allocations_zero"]
        and result["output_tokens_exact"]
        and not result["oracle_reservation_count"]
    )
    assert result["detailed_event_and_flow_logs_retained"]
    if job["failure"]:
        assert (
            result["failure"]["agent"],
            result["failure"]["invocation"],
            result["failure"]["logical_tokens"],
        ) == ("wf0/a_critical", 0, 1536)
    else:
        assert result["failure"] is None
    return result


def execute(out, plan, job, agents):
    path = out / "runs" / job["id"]
    if (path / "COMPLETE.json").exists():
        return validate(out, plan, job)
    path.mkdir(exist_ok=False)
    config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
    failure = Failure(**job["failure"]) if job["failure"] else None
    write_json(path / "config.json", asdict(config))
    write_json(path / "failure.json", asdict(failure) if failure else None)
    profile = GridDurationProfile(out / plan["profile"])
    runtime = ObservedRuntime(
        config,
        agents,
        policy=job["policy"],
        failure=failure,
        duration_profile=profile,
        retain_detailed_logs=True,
    )
    transitions, last_signature = [], None

    def observe(_des):
        nonlocal last_signature
        frame = snapshot(runtime)
        signature = (
            tuple(
                (
                    k,
                    v["worker"],
                    v["peer"],
                    v["call"],
                    v["checkpoint_identity"],
                    v["recovering_identity"],
                    v["finished"],
                )
                for k, v in frame["states"].items()
            ),
            tuple(
                (cp["identity"], cp["frontier"], cp["pending"], cp["retired"], cp["readers"])
                for cp in frame["checkpoints"]
            ),
            tuple(frame["busy"].items()),
            frame["fault_fired"],
        )
        if signature != last_signature:
            transitions.append(frame)
            last_signature = signature

    runtime.des.register_invariant("read-only-posthoc-mechanism-observer", observe)
    start = monotonic()
    try:
        result = runtime.run()
    except Exception as error:
        write_json(
            path / "FAILED.json",
            dict(type=type(error).__name__, message=str(error), time_ns=runtime.des.now_ns),
        )
        raise
    result.update(
        workload_sha256=plan["workload_sha256"], config_sha256=digest(path / "config.json")
    )
    write_json(path / "summary.json", result)
    write_lines(path / "events.jsonl.gz", runtime.events)
    write_lines(path / "flows.jsonl.gz", (asdict(x) for x in runtime.flow_model.intervals))
    with gzip.open(path / "journal.jsonl.gz", "wb") as stream:
        stream.write(runtime.des.journal.to_jsonl_bytes())
    write_lines(path / "state-transitions.jsonl.gz", transitions)
    entry = runtime.failure_entry
    write_json(
        path / "fault-state.json",
        dict(
            frame=entry,
            offline_scores=offline_scores(
                entry, agents, config, GridDurationProfile(out / plan["profile"])
            ),
        )
        if entry
        else None,
    )
    write_json(
        path / "COMPLETE.json",
        {
            **binding(out, plan, job),
            "wall_seconds": monotonic() - start,
            "artifacts_sha256": {p.name: digest(p) for p in sorted(path.iterdir()) if p.is_file()},
        },
    )
    validate(out, plan, job)
    return result


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)


def verify_observer_transparency(out, plan, agents):
    job = next(j for j in plan["jobs"] if j["id"] == "restart-F1")
    target = out / "validation/restart-F1-base-runtime"
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
        run_one(
            target,
            config,
            agents,
            job["policy"],
            Failure(**job["failure"]),
            duration_profile=GridDurationProfile(out / plan["profile"]),
            journal=True,
            retain_detailed_logs=True,
        )
    observed = out / "runs/restart-F1"
    assert (target / "summary.json").read_bytes() == (observed / "summary.json").read_bytes()
    trace_equal = {}
    for name in ("events.jsonl.gz", "flows.jsonl.gz"):
        trace_equal[name] = gzip.decompress((target / name).read_bytes()) == gzip.decompress(
            (observed / name).read_bytes()
        )
        assert trace_equal[name]
    write_json(
        out / "OBSERVATION_TRANSPARENCY.json",
        dict(
            passed=True,
            experiment_samples_added=0,
            validation_runs=1,
            job_id=job["id"],
            job_sha256=value_hash(job),
            summary_byte_identical=True,
            base_summary_sha256=digest(target / "summary.json"),
            observed_summary_sha256=digest(observed / "summary.json"),
            decompressed_traces_identical=trace_equal,
            base_runtime_source_sha256=digest(
                out / "source_snapshot/python/moonkvsim/aegiskv/current/runtime.py"
            ),
            limitation="Journal differs by the explicitly registered read-only observer invariant records; no extra DES events or policy outputs.",
        ),
    )


def summarize(out):
    plan = verify(out)
    transparency = read(out / "OBSERVATION_TRANSPARENCY.json")
    assert transparency["passed"] and transparency["summary_byte_identical"]
    assert (
        digest(out / "validation/restart-F1-base-runtime/summary.json")
        == transparency["base_summary_sha256"]
    )
    assert digest(out / "runs/restart-F1/summary.json") == transparency["observed_summary_sha256"]
    results = {j["id"]: validate(out, plan, j) for j in plan["jobs"]}
    rows, pairs = [], []
    for job in plan["jobs"]:
        result = results[job["id"]]
        row = {k: job[k] for k in ("id", "budget_bytes", "variant", "policy")}
        row.update(
            fault=job["failure"] is not None,
            wct_s=result["workflows"]["wf0"]["wct_ns"] / 1e9,
            **{f"metric_{k}": v for k, v in result["metrics"].items()},
            **{f"peak_{k}": v for k, v in result["peak_bytes"].items()},
        )
        if job["failure"]:
            f0 = results[job["f0_id"]]
            assert result["config_sha256"] == f0["config_sha256"]
            fault_state = read(out / "runs" / job["id"] / "fault-state.json")
            primary = next(r for r in result["recoveries"] if r["agent"] == "wf0/a_critical")
            pair = dict(
                id=job["id"],
                budget_bytes=job["budget_bytes"],
                variant=job["variant"],
                f0_wct_s=f0["workflows"]["wf0"]["wct_ns"] / 1e9,
                f1_wct_s=row["wct_s"],
                delta_wct_s=row["wct_s"] - f0["workflows"]["wf0"]["wct_ns"] / 1e9,
                failure=result["failure"],
                interrupted_agents=sorted({r["agent"] for r in result["recoveries"]}),
                primary_recovery=primary,
                fault_state=fault_state,
            )
            pairs.append(pair)
        rows.append(row)
    write_csv(out / "raw-runs.csv", rows)
    write_json(out / "PAIRED_RESULTS.json", pairs)
    write_json(
        out / "AUDIT.json",
        dict(
            passed=True,
            runs=len(rows),
            pairs=len(pairs),
            source_and_inputs_bound=True,
            all_outputs_count_exact=True,
            terminal_allocations_zero=True,
            no_oracle_reservations=True,
            all_outcomes_retained=True,
            physical_model_execution=False,
            seal_sha256=digest(out / "SEAL.json"),
            summary_sha256={
                j["id"]: digest(out / "runs" / j["id"] / "summary.json") for j in plan["jobs"]
            },
        ),
    )
    print("validated 10 post-hoc runs / 5 F1-F0 pairs", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "summarize"))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command != "prepare":
        frozen = out / "source_snapshot" / RELATIVE_SCRIPT
        if frozen.resolve() != Path(__file__).resolve():
            os.execv(sys.executable, [sys.executable, str(frozen), args.command, "--out", str(out)])
    if args.command == "prepare":
        prepare(out)
    elif args.command == "run":
        plan = verify(out)
        agents = load_workload(out / plan["workload"])
        assert value_hash([asdict(a) for a in agents]) == plan["workload_sha256"]
        for number, job in enumerate(plan["jobs"], 1):
            execute(out, plan, job, agents)
            write_json(out / "STATUS.json", dict(completed=number, total=10, latest=job["id"]))
            print(f"{number}/10 {job['id']}", flush=True)
        verify_observer_transparency(out, plan, agents)
        summarize(out)
    else:
        summarize(out)


if __name__ == "__main__":
    main()
