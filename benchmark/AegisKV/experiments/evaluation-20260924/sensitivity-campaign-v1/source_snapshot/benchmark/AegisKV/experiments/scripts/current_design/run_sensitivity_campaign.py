#!/usr/bin/env python3
"""Prespecified four-workflow, one-fault resource/prediction sensitivity.

protocol writes a reviewable design without freezing sources or running DES.
prepare freezes source/input copies; run executes only those copied sources.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from math import ceil
from pathlib import Path
from statistics import mean
from time import monotonic, process_time

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
)
from moonkvsim.aegiskv.current.model import Config, Failure  # noqa: E402
from moonkvsim.aegiskv.evaluation_campaign import (  # noqa: E402
    CausalLengthPredictor,
    model_config,
    save_workload,
    with_priors_and_arrivals,
)
from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile  # noqa: E402
from moonkvsim.aegiskv.evaluation_workload import load_fanoutqa_agents  # noqa: E402

BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
INPUTS = BASE / "inputs"
POLICIES = ("none", "dram", "aegiskv")
MODEL = "Qwen3-8B"
_CACHE = {}


def object_sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def matrix(base):
    """Deduplicate the common central condition, retaining every factor alias."""
    configs, aliases, identities = [], [], {}

    def add(factor, value, changes, multiplier=1.0, *, control=False):
        config = replace(base, **changes)
        key = object_sha(dict(config=asdict(config), prediction_multiplier=multiplier))
        if key not in identities:
            identity = "center" if not configs else f"condition-{len(configs):02d}"
            identities[key] = identity
            configs.append(
                dict(id=identity, config=asdict(config), prediction_multiplier=multiplier)
            )
        aliases.append(
            dict(
                factor=factor,
                value=value,
                condition=identities[key],
                local_control=control,
            )
        )

    add("center", "core", {})
    for value in (8, 16, 32, 64):
        add("h2d_GBps", value, dict(h2d_bytes_per_second=value * 1e9))
    for value in (0.25, 1, 256):
        add("dram_GiB_per_host", value, dict(dram_bytes_per_host=int(value * 1024**3)))
    for value in (0, 32, 128, 4096):
        add(
            "hbm_cap_MiB_per_rank",
            value,
            dict(
                hbm_cap_bytes=value * 1024**2,
                initial_quota_bytes=min(128, value) * 1024**2,
            ),
        )
    for value in (0.5, 1.0, 2.0):
        add("online_prediction_multiplier", value, {}, multiplier=value)
    # Local one-factor pair: both use the same TTL; neither shares center TTL.
    for value in (0.1, 200):
        add(
            "prediction_latency_ms_at_TTL100ms",
            value,
            dict(
                prediction_ttl_ns=100_000_000,
                prediction_latency_ns=round(value * 1e6),
            ),
            control=value == 0.1,
        )
    for value in (0.0, 0.05, 0.1):
        add("compute_dma_slowdown", value, dict(compute_dma_slowdown=value))
    for value in (1, 10, 100):
        add("failure_detection_ms", value, dict(failure_detection_ns=value * 1_000_000))
    for value in (0, 0.01, 1):
        add("tolerance_seconds", value, dict(tolerance_ns=round(value * 1e9)))
    for value in (64, 256, 1024):
        add("checkpoint_tokens", value, dict(checkpoint_tokens=value))
    assert len(configs) == 21 and len(aliases) == 29
    assert all(c["config"]["depth"] == base.depth for c in configs)
    assert all(c["config"]["slack_guard_ns"] == base.slack_guard_ns for c in configs)
    return configs, aliases


def design(priors_source):
    split_path, bundle_path = (
        INPUTS / "fanoutqa-workflow-split.json",
        INPUTS / "fanoutqa-bundle.json",
    )
    split = json.loads(split_path.read_text())
    assert digest(bundle_path) == split["source_bundle_sha256"]
    ids = split["native_eval_ids"][:4]
    assert len(ids) == 4 and not set(ids) & set(split["native_train_ids"])
    agents = load_fanoutqa_agents(bundle_path, workflow_ids=ids, max_context_tokens=40960)
    agents = tuple(
        replace(a, calls=tuple(replace(c, output_limit_tokens=512) for c in a.calls))
        for a in agents
    )
    profile_path = INPUTS / f"duration-profiles/{MODEL}.json"
    profile = GridDurationProfile(profile_path)
    priors = json.loads(priors_source.read_text())[MODEL]
    assert set(priors["training_workflows"]) == set(split["native_train_ids"])
    config = replace(
        model_config(profile, dp=8),
        depth=priors["depth_choice"]["depth"],
        slack_guard_ns=priors["slack_guard_ns"],
    )
    interval = round(priors["mean_training_workflow_service_ns"] / 8 / 0.65)
    agents = with_priors_and_arrivals(agents, priors, interval)
    candidates = [a for a in agents if a.workflow == ids[2]]
    # max is stable on source order: selection never reads outputs or outcomes.
    target = max(candidates, key=lambda a: len(a.calls[0].prompt))
    call = target.calls[0]
    failure = Failure(target.key, invocation=0, progress=0.8, scope="worker")
    descriptor = dict(
        selection="third selected workflow, longest prompt, source-order tie",
        selection_uses_outputs=False,
        agent=target.key,
        prompt_tokens=len(call.prompt),
        output_tokens=len(call.output),
        total_tokens=len(call.tokens),
        logical_trigger_tokens=ceil(len(call.tokens) * 0.8),
        phase="prefill" if ceil(len(call.tokens) * 0.8) <= len(call.prompt) else "decode",
    )
    assert descriptor["logical_trigger_tokens"] >= 3 * 1024
    conditions, aliases = matrix(config)
    protocol = dict(
        schema="aegiskv.four-workflow-sensitivity.v1",
        status="proposed_not_executed",
        models=[MODEL],
        workflows=ids,
        agents=len(agents),
        repeats_per_workflow=1,
        workflow_selection="first four native heldout IDs in original source order",
        faults=1,
        failure=asdict(failure),
        failure_descriptor=descriptor,
        policies=list(POLICIES),
        conditions=conditions,
        factor_aliases=aliases,
        unique_conditions=len(conditions),
        planned_runs=len(conditions) * 6,
        fault_conditions=["F0", "F1"],
        nominal_load=0.65,
        arrival_interval_ns=interval,
        baseline_config=asdict(config),
        priors=priors,
        input_sha256={
            str(p.relative_to(ROOT)): digest(p)
            for p in (split_path, bundle_path, profile_path, priors_source)
        },
        comparisons=[
            "F1 minus own-condition own-policy F0 for each original workflow",
            "three policies paired on identical input, arrival times and fault identity",
            "factor levels share one central result; repeated centers never increase sample size",
        ],
        frozen_parameters="role priors, guard, L, K, arrivals, exact prompt/output IDs",
        derived_parameters=[
            "initial HBM quota=min(128MiB, cap) for valid cap constraints",
            "checkpoint64 forces <=64-token forward segments; checkpoint1024 keeps chunk256",
            "stale local pair uses TTL100ms at both latency0.1ms and latency200ms",
        ],
        statistics="n=1 fixed fault; four dependent workflow observations; no population CI",
        binding_audit=[
            "capacity_waits/reselections, per-host DRAM peaks, checkpoint commits, protection",
            "per-rank HBM replica peaks, quota changes, hot bytes and protection at failure",
            "coarse prediction return age vs TTL plus existing aggregate fallback counter",
            "no complete master-budget rejection count exists; do not infer one",
        ],
        evidence_limits=[
            "human DAG with constructed FanOutQA prompts; one native-context pass",
            "dense Qwen3-8B profile-informed simulation; no physical calibration",
            "DP8/four workflows studies a local capacity boundary, not population load",
            "one deterministic length-selected fault is not a random fault sample",
            "fixed-L H2D sensitivity, not retrained per-bandwidth L selection",
            "stale return-age counts are not exact timeout/fallback-cause counts",
        ],
    )
    return protocol, agents, profile_path


def prepare(out, priors_source, *, draft=False):
    out.mkdir(parents=True, exist_ok=True)
    if (out / "PLAN.json").exists():
        raise FileExistsError("Do not overwrite a frozen campaign")
    protocol, agents, profile_path = design(priors_source)
    if draft:
        write_json(out / "PROTOCOL-DRAFT.json", protocol)
        print(json.dumps(protocol["failure_descriptor"]), flush=True)
        print(
            f"protocol only: {protocol['planned_runs']} planned runs; no source freeze or DES",
            flush=True,
        )
        return
    (out / "workloads").mkdir(exist_ok=True)
    (out / "profiles").mkdir(exist_ok=True)
    saved_profile = out / "profiles" / profile_path.name
    shutil.copy2(profile_path, saved_profile)
    write_json(out / "PRIORS.json", {MODEL: protocol["priors"]})
    workload_path = out / "workloads/fanoutqa-four-native-eval.json.gz"
    content_hash = save_workload(workload_path, agents)
    workload = dict(
        path=str(workload_path.relative_to(out)),
        sha256=digest(workload_path),
        content_sha256=content_hash,
    )
    jobs = []
    for condition in protocol["conditions"]:
        for policy in POLICIES:
            f0 = f"{condition['id']}-{policy}-F0"
            for fault in ("F0", "F1"):
                jobs.append(
                    dict(
                        id=f"{condition['id']}-{policy}-{fault}",
                        condition=condition["id"],
                        config=condition["config"],
                        prediction_multiplier=condition["prediction_multiplier"],
                        policy=policy,
                        fault=fault,
                        f0_id=f0,
                        failure=protocol["failure"] if fault == "F1" else None,
                        detailed_logs=condition["id"] == "center" and policy == "aegiskv",
                    )
                )
    assert len(jobs) == 126 and len({j["id"] for j in jobs}) == 126
    source = manifest(out)
    for path in [*sorted((ROOT / "python/moonkvsim").rglob("*.py")), Path(__file__).resolve()]:
        relative = path.relative_to(ROOT)
        saved = out / "source_snapshot" / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
        source["source_sha256"][str(relative)] = digest(saved)
    source.update(
        original_root=str(ROOT),
        source_execution="snapshotted Python modules",
        profile_sha256=digest(saved_profile),
        workload=workload,
        priors_sha256=digest(out / "PRIORS.json"),
        physical_execution=False,
    )
    protocol["status"] = "frozen_before_execution"
    write_json(out / "PROTOCOL.json", protocol)
    write_json(
        out / "PLAN.json",
        dict(
            jobs=jobs,
            protocol=protocol,
            workload=workload,
            profile=str(saved_profile.relative_to(out)),
        ),
    )
    source["control_sha256"] = {
        name: digest(out / name) for name in ("PLAN.json", "PROTOCOL.json", "PRIORS.json")
    }
    write_json(out / "MANIFEST.json", source)
    print(f"frozen {len(jobs)} runs at {out}", flush=True)


def verify(out):
    source = json.loads((out / "MANIFEST.json").read_text())
    for relative, expected in source["source_sha256"].items():
        assert digest(out / "source_snapshot" / relative) == expected, relative
    for name, expected in source["control_sha256"].items():
        assert digest(out / name) == expected, name
    plan = json.loads((out / "PLAN.json").read_text())
    assert digest(out / plan["profile"]) == source["profile_sha256"]
    assert digest(out / plan["workload"]["path"]) == plan["workload"]["sha256"]
    return plan


def verify_complete(out, job, plan):
    path = out / "runs" / job["id"]
    marker = json.loads((path / "COMPLETE.json").read_text())
    assert marker["id"] == job["id"]
    assert marker["job_sha256"] == object_sha(job)
    assert marker["priors_sha256"] == digest(out / "PRIORS.json")
    assert marker["profile_sha256"] == digest(out / plan["profile"])
    for name, expected in marker["artifact_sha256"].items():
        assert digest(path / name) == expected, (job["id"], name)
    result = json.loads((path / "summary.json").read_text())
    assert digest(path / "config.json") == object_sha(job["config"])
    assert digest(path / "failure.json") == object_sha(job["failure"])
    assert result["config_sha256"] == object_sha(job["config"])
    assert result["workload_sha256"] == plan["workload"]["content_sha256"]
    assert result["policy"] == job["policy"]
    assert result["duration_profile"] == "GridDurationProfile"
    assert result["attention_demand_provider"] == "dense"
    assert all(
        result[k] is True for k in ("complete", "output_tokens_exact", "terminal_allocations_zero")
    )
    assert result["oracle_reservation_count"] == 0
    if job["failure"]:
        assert result["failure"]["agent"] == job["failure"]["agent"]
        assert result["failure"]["invocation"] == job["failure"]["invocation"]
        assert (
            result["failure"]["logical_tokens"]
            == plan["protocol"]["failure_descriptor"]["logical_trigger_tokens"]
        )
    else:
        assert result["failure"] is None
    return marker, result


def execute(payload):
    out_text, job, plan = payload
    out = Path(out_text)
    target = out / "runs" / job["id"]
    if (target / "COMPLETE.json").exists():
        return verify_complete(out, job, plan)[0]
    if target.exists():
        raise FileExistsError(f"Partial run preserved: {target}")
    key = str(out)
    if key not in _CACHE:
        agents = load_workload(out / plan["workload"]["path"])
        assert object_sha([asdict(a) for a in agents]) == plan["workload"]["content_sha256"]
        _CACHE[key] = agents, GridDurationProfile(out / plan["profile"])
    agents, profile = _CACHE[key]
    priors = plan["protocol"]["priors"]
    config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
    predictor = CausalLengthPredictor(
        profile,
        config,
        priors["role_output_tokens"],
        tuple(priors["training_workflows"]),
        multiplier=job["prediction_multiplier"],
    )
    wall, cpu = monotonic(), process_time()
    run_one(
        target,
        config,
        agents,
        job["policy"],
        Failure(**job["failure"]) if job["failure"] else None,
        predictor=predictor,
        duration_profile=profile,
        retain_detailed_logs=job["detailed_logs"],
    )
    write_json(
        target / "COMPLETE.json",
        dict(
            id=job["id"],
            job_sha256=object_sha(job),
            priors_sha256=digest(out / "PRIORS.json"),
            profile_sha256=digest(out / plan["profile"]),
            wall_seconds=monotonic() - wall,
            process_cpu_seconds=process_time() - cpu,
            artifact_sha256={
                name: digest(target / name)
                for name in (
                    "summary.json",
                    "config.json",
                    "failure.json",
                    "events.jsonl.gz",
                    "flows.jsonl.gz",
                )
            },
        ),
    )
    return verify_complete(out, job, plan)[0]


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize(out):
    plan = verify(out)
    results, raw, paired, binding = {}, [], [], []
    for job in plan["jobs"]:
        marker, result = verify_complete(out, job, plan)
        results[job["id"]] = result
        fields = {k: job[k] for k in ("id", "condition", "policy", "fault")}
        raw.append(
            dict(
                **fields,
                mean_wct_s=mean(r["wct_ns"] for r in result["workflows"].values()) / 1e9,
                max_wct_s=max(r["wct_ns"] for r in result["workflows"].values()) / 1e9,
                **{f"metric_{k}": v for k, v in result["metrics"].items()},
                **{f"peak_{k}": v for k, v in result["peak_bytes"].items()},
                wall_seconds=marker["wall_seconds"],
                process_cpu_seconds=marker["process_cpu_seconds"],
            )
        )
        with gzip.open(out / "runs" / job["id"] / "events.jsonl.gz", "rt") as stream:
            events = [json.loads(line) for line in stream]
        predictions = [e for e in events if e["kind"] == "prediction"]
        stale = [
            e
            for e in predictions
            if e["time_ns"] - e["submitted_ns"] > job["config"]["prediction_ttl_ns"]
        ]
        dram_peak = max(
            (v for k, v in result["peak_bytes"].items() if k.startswith("dram:")), default=0
        )
        hbm_peak = max(
            (v for k, v in result["peak_bytes"].items() if k.startswith("replica:hbm:")), default=0
        )
        binding.append(
            dict(
                **fields,
                dram_capacity_bytes_per_host=job["config"]["dram_bytes_per_host"],
                peak_single_host_dram_bytes=dram_peak,
                peak_single_host_dram_fraction=dram_peak / job["config"]["dram_bytes_per_host"],
                dram_append_capacity_waits=result["metrics"].get("dram_append_capacity_waits", 0),
                dram_reselections=result["metrics"].get("dram_reselections", 0),
                master_budget_rejections_complete_count_available=False,
                hbm_cap_bytes=job["config"]["hbm_cap_bytes"],
                peak_single_rank_replica_hbm_bytes=hbm_peak,
                checkpoint_commits=result["metrics"].get("checkpoint_commits", 0),
                hot_bytes=result["metrics"].get("hot_bytes", 0),
                target_protected_checkpoint_tokens=next(
                    (
                        r.get("checkpoint_tokens", 0)
                        for r in result["recoveries"]
                        if r["agent"] == plan["protocol"]["failure"]["agent"]
                    ),
                    0,
                ),
                prediction_reply_events=len(predictions),
                replies_older_than_TTL=len(stale),
                accepted_replies_older_than_TTL=sum(bool(e["accepted"]) for e in stale),
                slack_fallback_observations=result["metrics"].get("slack_fallback_observations", 0),
                exact_timeout_count_available=False,
            )
        )
    for job in plan["jobs"]:
        if job["fault"] == "F0":
            continue
        f0, f1 = results[job["f0_id"]], results[job["id"]]
        assert f0["config_sha256"] == f1["config_sha256"]
        assert f0["workload_sha256"] == f1["workload_sha256"]
        assert f0["workflows"].keys() == f1["workflows"].keys()
        for workflow, normal in f0["workflows"].items():
            delta = f1["workflows"][workflow]["wct_ns"] - normal["wct_ns"]
            paired.append(
                dict(
                    id=job["id"],
                    condition=job["condition"],
                    policy=job["policy"],
                    workflow=workflow,
                    target_workflow=workflow == job["failure"]["agent"].split("/")[0],
                    f0_wct_s=normal["wct_ns"] / 1e9,
                    f1_wct_s=f1["workflows"][workflow]["wct_ns"] / 1e9,
                    delta_wct_s=delta / 1e9,
                    relative_delta=delta / normal["wct_ns"],
                    failure_wall_time_s=f1["failure"]["time_ns"] / 1e9,
                )
            )
    write_csv(out / "raw-runs.csv", raw)
    write_csv(out / "paired-workflows.csv", paired)
    write_csv(out / "binding-diagnostics.csv", binding)
    write_csv(out / "factor-aliases.csv", plan["protocol"]["factor_aliases"])
    write_json(
        out / "AUDIT.json",
        dict(
            complete=True,
            planned_runs=len(plan["jobs"]),
            verified_runs=len(raw),
            paired_workflow_rows=len(paired),
            same_id_faults=1,
            population_confidence_intervals=False,
            negative_deltas_retained=True,
            source_and_result_hashes_verified=True,
            detailed_flow_audit_claim=False,
            missing_instrumentation=[
                "complete master budget denial count",
                "cause-specific timeout count",
            ],
            outputs_sha256={
                name: digest(out / name)
                for name in (
                    "raw-runs.csv",
                    "paired-workflows.csv",
                    "binding-diagnostics.csv",
                    "factor-aliases.csv",
                )
            },
        ),
    )
    print(f"audited {len(raw)} runs and {len(paired)} paired workflow rows", flush=True)


def run(out, workers, limit):
    plan = verify(out)
    records, todo = [], []
    for job in plan["jobs"]:
        target = out / "runs" / job["id"]
        if (target / "COMPLETE.json").exists():
            records.append(verify_complete(out, job, plan)[0])
        elif target.exists():
            raise FileExistsError(f"Partial run requires inspection: {target}")
        else:
            todo.append(job)
    if limit is not None:
        todo = todo[:limit]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(execute, (str(out), job, plan)) for job in todo]
        for future in as_completed(futures):
            record = future.result()
            records.append(record)
            write_json(out / "RUNS.json", sorted(records, key=lambda r: r["id"]))
            write_json(
                out / "STATUS.json",
                dict(completed=len(records), total=len(plan["jobs"]), latest=record["id"]),
            )
            print(
                f"{len(records)}/{len(plan['jobs'])} {record['id']} {record['wall_seconds']:.2f}s",
                flush=True,
            )
    if len(records) == len(plan["jobs"]):
        summarize(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("protocol", "prepare", "run", "summarize"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--priors-source", type=Path, default=BASE / "formal-core-v1/PRIORS.json")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command in ("run", "summarize"):
        frozen = out / "source_snapshot" / RELATIVE_SCRIPT
        if frozen.resolve() != Path(__file__).resolve():
            command = [
                sys.executable,
                str(frozen),
                args.command,
                "--out",
                str(out),
                "--workers",
                str(args.workers),
            ]
            if args.limit is not None:
                command += ["--limit", str(args.limit)]
            os.execv(sys.executable, command)
    if args.command in ("prepare", "protocol"):
        prepare(out, args.priors_source.resolve(), draft=args.command == "protocol")
    elif args.command == "run":
        run(out, args.workers, args.limit)
    else:
        summarize(out)


if __name__ == "__main__":
    main()
