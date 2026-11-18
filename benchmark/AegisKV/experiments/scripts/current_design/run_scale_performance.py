#!/usr/bin/env python3
"""Independent same-version, fresh-process structural scale timing campaign.

Inputs and configurations are copied unchanged from structural-campaign-v1.
Prepare only after the chosen runtime optimization has passed equivalence checks.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
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
    percentile,
    run_one,
    write_json,
)
from moonkvsim.aegiskv.current.model import Config, Failure  # noqa: E402
from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile  # noqa: E402

CONFIG_DEFAULT_ADDITIONS = {"slack_mode": "dag"}


def value_hash(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def read(path):
    return json.loads(path.read_text())


def prepare(out, origin, equivalence):
    if out.exists():
        raise FileExistsError(f"refusing to replace a scale campaign: {out}")
    parent = read(origin / "PLAN.json")
    evidence = read(equivalence)
    origin_jobs = [
        j
        for j in parent["jobs"]
        if j["scenario"] == "history_reuse"
        and j["seed"] == 7
        and j["policy"] in {"dram", "aegiskv"}
        and j["fault"] in {"F0", "left.decode"}
    ]
    jobs = []
    for original in origin_jobs:
        job = json.loads(json.dumps(original))
        normalized = json.loads(
            encoded(asdict(Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})))
        )
        assert all(normalized[k] == v for k, v in job["config"].items())
        additions = {k: v for k, v in normalized.items() if k not in job["config"]}
        assert all(CONFIG_DEFAULT_ADDITIONS.get(k) == v for k, v in additions.items()), additions
        job["config"] = normalized
        jobs.append(job)
    assert len(jobs) == 12
    assert {(j["workflows"], j["policy"], j["fault"]) for j in jobs} == {
        (n, p, f) for n in (8, 32, 128) for p in ("dram", "aegiskv") for f in ("F0", "left.decode")
    }
    assert all(not j["retain_detailed_logs"] and j["demand_provider"] is None for j in jobs)
    out.mkdir(parents=True)
    for name in ("workloads", "profiles", "runs", "logs", "provenance"):
        (out / name).mkdir()
    shutil.copy2(origin / "PLAN.json", out / "provenance/structural-PLAN.json")
    shutil.copy2(origin / "MANIFEST.json", out / "provenance/structural-MANIFEST.json")
    shutil.copy2(equivalence, out / "provenance/optimization-equivalence.json")
    shutil.copy2(origin / parent["profile"], out / parent["profile"])
    workloads = {}
    for key in sorted({j["workload_id"] for j in jobs}):
        specification = dict(parent["workloads"][key])
        for field in ("path", "metadata"):
            shutil.copy2(origin / specification[field], out / specification[field])
        specification["compressed_sha256"] = digest(out / specification["path"])
        specification["metadata_sha256"] = digest(out / specification["metadata"])
        workloads[key] = specification
    plan = {
        "schema": "aegiskv.scale-performance.v2",
        "jobs": jobs,
        "job_count": 12,
        "workloads": workloads,
        "profile": parent["profile"],
        "profile_sha256": parent["profile_sha256"],
        "origin": str(origin),
        "origin_plan_sha256": digest(origin / "PLAN.json"),
        "origin_manifest_sha256": digest(origin / "MANIFEST.json"),
        "optimization_equivalence_sha256": digest(equivalence),
        "optimization_equivalence": evidence,
        "declared_config_default_additions": CONFIG_DEFAULT_ADDITIONS,
        "protocol": {
            "matrix": "history_reuse x {8,32,128} workflows x seed7 x {dram,aegiskv} x {F0,left.decode}",
            "logging": "summary only for every point; no policy/forward detailed-event records or flow intervals",
            "processes": "one fresh Python subprocess per job; configurable concurrent jobs",
            "wall_cpu_interval": "after input/profile loading, includes simulation and output serialization",
            "peak_rss_scope": "fresh job subprocess lifetime including imports/input loading; no prior jobs",
            "comparison": "all scales use one frozen runtime; original campaign remains a separate version",
            "statistics": "one timing per case, descriptive resource costs, no timing CI or population inference",
            "evidence": "modeled service, constructed workload; simulator CPU/RSS are physical host-process costs",
        },
    }
    write_json(out / "PLAN.json", plan)
    source = manifest(out)
    for path in [*sorted((ROOT / "python/moonkvsim").rglob("*.py")), Path(__file__).resolve()]:
        relative = path.relative_to(ROOT)
        target = out / "source_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        source["source_sha256"][str(relative)] = digest(target)
    source.update(
        {
            "source_execution": "frozen snapshot; fresh subprocess per job",
            "original_root": str(ROOT),
            "plan_sha256": digest(out / "PLAN.json"),
        }
    )
    write_json(out / "MANIFEST.json", source)
    write_json(
        out / "SEAL.json",
        {"PLAN.json": digest(out / "PLAN.json"), "MANIFEST.json": digest(out / "MANIFEST.json")},
    )
    print(f"froze {len(jobs)} scale jobs", flush=True)


def verify(out):
    for name, expected in read(out / "SEAL.json").items():
        assert digest(out / name) == expected, name
    plan, source = read(out / "PLAN.json"), read(out / "MANIFEST.json")
    assert source["plan_sha256"] == digest(out / "PLAN.json")
    for name, expected in source["source_sha256"].items():
        assert digest(out / "source_snapshot" / name) == expected, name
    assert digest(out / plan["profile"]) == plan["profile_sha256"]
    for specification in plan["workloads"].values():
        assert digest(out / specification["path"]) == specification["compressed_sha256"]
        assert digest(out / specification["metadata"]) == specification["metadata_sha256"]
    for name, expected in (
        ("structural-PLAN.json", plan["origin_plan_sha256"]),
        ("structural-MANIFEST.json", plan["origin_manifest_sha256"]),
        ("optimization-equivalence.json", plan["optimization_equivalence_sha256"]),
    ):
        assert digest(out / "provenance" / name) == expected
    origin = read(out / "provenance/structural-PLAN.json")
    origin_jobs = {j["id"]: j for j in origin["jobs"]}
    assert len(plan["jobs"]) == len({j["id"] for j in plan["jobs"]}) == 12
    for job in plan["jobs"]:
        original = origin_jobs[job["id"]]
        assert {k: v for k, v in original.items() if k != "config"} == {
            k: v for k, v in job.items() if k != "config"
        }
        assert all(job["config"][k] == v for k, v in original["config"].items())
        additions = {k: v for k, v in job["config"].items() if k not in original["config"]}
        assert all(
            plan["declared_config_default_additions"].get(k) == v for k, v in additions.items()
        )
    return plan


def binding(out, plan, job):
    return {
        "id": job["id"],
        "job_sha256": value_hash(job),
        "plan_sha256": digest(out / "PLAN.json"),
        "manifest_sha256": digest(out / "MANIFEST.json"),
        "workload_sha256": plan["workloads"][job["workload_id"]]["sha256"],
        "profile_sha256": plan["profile_sha256"],
    }


def validate_result(out, plan, job):
    target = out / "runs" / job["id"]
    record, result = read(target / "COMPLETE.json"), read(target / "summary.json")
    for key, value in binding(out, plan, job).items():
        assert record[key] == value, (job["id"], key)
    for name, expected in record["artifacts_sha256"].items():
        assert digest(target / name) == expected, (job["id"], name)
    assert read(target / "config.json") == job["config"]
    assert read(target / "failure.json") == job["failure"]
    assert result["config_sha256"] == digest(target / "config.json")
    assert result["workload_sha256"] == record["workload_sha256"]
    assert result["policy"] == job["policy"]
    assert result["predictor"] == "prior_predictor"
    assert result["duration_profile"] == "GridDurationProfile"
    assert result["attention_demand_provider"] == "dense"
    assert (
        result["complete"] and result["output_tokens_exact"] and result["terminal_allocations_zero"]
    )
    assert not result["oracle_reservation_count"]
    assert not result["detailed_event_and_flow_logs_retained"]
    assert len(result["workflows"]) == job["workflows"]
    if job["failure"] is None:
        assert result["failure"] is None
    else:
        descriptor = job["failure_descriptor"]
        for actual, expected in (
            ("agent", "agent"),
            ("invocation", "invocation"),
            ("logical_tokens", "logical_trigger_tokens"),
        ):
            assert result["failure"][actual] == descriptor[expected]
        assert result["failure"]["logical_tokens"] >= descriptor["prompt_tokens"]
    return record, result


def execute(out, identity):
    plan = verify(out)
    job = next(j for j in plan["jobs"] if j["id"] == identity)
    target = out / "runs" / identity
    if (target / "COMPLETE.json").exists():
        validate_result(out, plan, job)
        return
    if target.exists():
        raise FileExistsError(f"preserving incomplete output: {target}")
    specification = plan["workloads"][job["workload_id"]]
    agents = load_workload(out / specification["path"])
    assert value_hash([asdict(a) for a in agents]) == specification["sha256"]
    config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
    failure = Failure(**job["failure"]) if job["failure"] else None
    profile = GridDurationProfile(out / plan["profile"])
    start, cpu = monotonic(), process_time()
    run_one(
        target,
        config,
        agents,
        job["policy"],
        failure,
        duration_profile=profile,
        retain_detailed_logs=False,
        journal=False,
    )
    wall_elapsed, cpu_elapsed = monotonic() - start, process_time() - cpu
    record = {
        **binding(out, plan, job),
        "wall_seconds": wall_elapsed,
        "process_cpu_seconds": cpu_elapsed,
        "fresh_process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "pid": os.getpid(),
        "artifacts_sha256": {p.name: digest(p) for p in sorted(target.iterdir()) if p.is_file()},
    }
    write_json(target / "COMPLETE.json", record)
    validate_result(out, plan, job)
    print(f"complete {identity} {record['wall_seconds']:.3f}s", flush=True)


def run(out, workers):
    plan = verify(out)
    frozen = out / "source_snapshot" / RELATIVE_SCRIPT

    def child(job):
        with (out / "logs" / f"{job['id']}.log").open("a") as stream:
            subprocess.run(
                [sys.executable, str(frozen), "execute", "--out", str(out), "--job", job["id"]],
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=True,
            )
        return validate_result(out, plan, job)[0]

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(child, job) for job in plan["jobs"]]
        for future in as_completed(futures):
            record = future.result()
            completed += 1
            write_json(
                out / "STATUS.json", {"completed": completed, "total": 12, "latest": record["id"]}
            )
            print(f"{completed}/12 {record['id']} {record['wall_seconds']:.3f}s", flush=True)
    summarize(out)


def write_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)


def summarize(out):
    plan = verify(out)
    raw, paired, checks, results = [], [], [], {}
    for job in plan["jobs"]:
        record, result = validate_result(out, plan, job)
        results[job["id"]] = result
        wct = [r["wct_ns"] / 1e9 for r in result["workflows"].values()]
        raw.append(
            {
                **{k: job[k] for k in ("id", "scenario", "workflows", "seed", "policy", "fault")},
                **{
                    k: record[k]
                    for k in ("wall_seconds", "process_cpu_seconds", "fresh_process_peak_rss_kib")
                },
                "mean_wct_s": mean(wct),
                "p95_wct_s": percentile(wct, 0.95),
                "p99_wct_s": percentile(wct, 0.99),
                "max_wct_s": max(wct),
                **{f"metric_{k}": v for k, v in result["metrics"].items()},
                **{f"peak_{k}": v for k, v in result["peak_bytes"].items()},
            }
        )
        if job["fault"] == "F0":
            continue
        f0 = results[job["f0_id"]]
        assert f0["config_sha256"] == result["config_sha256"]
        assert f0["workload_sha256"] == result["workload_sha256"]
        assert f0["workflows"].keys() == result["workflows"].keys()
        victims = sorted({r["agent"].split("/")[0] for r in result["recoveries"]})
        checks.append(
            {
                "id": job["id"],
                "paired_inputs_and_ids_equal": True,
                "failure": result["failure"],
                "interrupted_agents": sorted({r["agent"] for r in result["recoveries"]}),
            }
        )
        for wf in f0["workflows"]:
            a, b = f0["workflows"][wf]["wct_ns"] / 1e9, result["workflows"][wf]["wct_ns"] / 1e9
            paired.append(
                {
                    "id": job["id"],
                    "workflows": job["workflows"],
                    "policy": job["policy"],
                    "workflow": wf,
                    "target_workflow": wf == job["failure"]["agent"].split("/")[0],
                    "interrupted_workflow": wf in victims,
                    "f0_wct_s": a,
                    "f1_wct_s": b,
                    "delta_wct_s": b - a,
                }
            )
    assert len(raw) == 12 and len(paired) == 336 and len(checks) == 6
    original_comparison = []
    origin = Path(plan["origin"])
    assert digest(origin / "PLAN.json") == plan["origin_plan_sha256"]
    assert digest(origin / "MANIFEST.json") == plan["origin_manifest_sha256"]
    for job in plan["jobs"]:
        old_path = origin / "runs" / job["id"]
        entry = {"id": job["id"], "original_complete": (old_path / "COMPLETE.json").exists()}
        if entry["original_complete"]:
            old_record, old_result = (
                read(old_path / "COMPLETE.json"),
                read(old_path / "summary.json"),
            )
            assert digest(old_path / "summary.json") == old_record["summary_sha256"]
            assert old_result["workload_sha256"] == results[job["id"]]["workload_sha256"]
            old_config = read(old_path / "config.json")
            assert all(job["config"][k] == v for k, v in old_config.items())
            differing = [
                k
                for k in sorted(old_result.keys() | results[job["id"]].keys())
                if old_result.get(k) != results[job["id"]].get(k)
            ]
            entry.update(
                {
                    "original_summary_sha256": old_record["summary_sha256"],
                    "new_summary_sha256": digest(out / "runs" / job["id"] / "summary.json"),
                    "all_summary_fields_equal": not differing,
                    "differing_fields": differing,
                    "original_wall_seconds": old_record["wall_seconds"],
                    "original_process_cpu_seconds": old_record["process_cpu_seconds"],
                    "original_worker_lifetime_peak_rss_kib": old_record[
                        "worker_lifetime_peak_rss_kib"
                    ],
                }
            )
        original_comparison.append(entry)
    write_json(
        out / "ORIGINAL_COMPARISON.json",
        {
            "scope": "individually completed original points; original worker-lifetime RSS includes earlier jobs and is not directly comparable to fresh-process RSS",
            "rows": original_comparison,
        },
    )
    write_csv(out / "resource-results.csv", raw)
    write_csv(out / "paired-workflows.csv", paired)
    write_json(
        out / "AUDIT.json",
        {
            "passed": True,
            "runs": len(raw),
            "paired_workflows": len(paired),
            "pairs": checks,
            "seal_sha256": digest(out / "SEAL.json"),
            "summary_sha256": {
                j["id"]: digest(out / "runs" / j["id"] / "summary.json") for j in plan["jobs"]
            },
            "outputs_sha256": {
                n: digest(out / n) for n in ("resource-results.csv", "paired-workflows.csv")
            },
        },
    )
    (out / "README.md").write_text(
        "# Structural scale performance v2\n\nTwelve same-version, summary-only runs reproduce the frozen history_reuse inputs, configurations and failure identities from structural-campaign-v1 at 8/32/128 workflows, seed 7, DRAM/AegisKV and F0/decode fault. Each job has its own Python process. The original campaign remains intact as a separate runtime version.\n\nresource-results.csv reports simulator wall and CPU time after input loading (including simulation and serialization), plus each fresh process's lifetime peak RSS (including imports and input loading). Concurrent jobs share a host: wall times are descriptive, one run per point, without confidence intervals or hardware-serving throughput claims. Modeled WCT/byte counters remain distinct from measured simulator CPU/RSS.\n\nPLAN/MANIFEST/SEAL pin jobs, source, compressed and uncompressed workloads, metadata, profile, and the external optimization-equivalence record. COMPLETE binds every result to that job and source with all run-artifact hashes. AUDIT verifies 12 completed runs and 336 same-ID workflow pairs, exact outputs, zero residual allocations, no output-length oracle, and the fixed logical decode fault.\n"
    )
    print("audited 12 scale runs / 336 paired workflows", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "execute", "summarize"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--origin", type=Path)
    parser.add_argument("--equivalence", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--job")
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command != "prepare":
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
            if args.job:
                command += ["--job", args.job]
            os.execv(sys.executable, command)
    if args.command == "prepare":
        if not args.origin or not args.equivalence:
            parser.error("prepare requires --origin and --equivalence")
        prepare(out, args.origin.resolve(), args.equivalence.resolve())
    elif args.command == "execute":
        execute(out, args.job)
    elif args.command == "run":
        run(out, args.workers)
    else:
        summarize(out)


if __name__ == "__main__":
    main()
