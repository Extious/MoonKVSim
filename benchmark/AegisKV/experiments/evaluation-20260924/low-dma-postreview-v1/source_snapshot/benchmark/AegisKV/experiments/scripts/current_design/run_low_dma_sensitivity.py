#!/usr/bin/env python3
"""Post-review, prespecified low-DMA coefficients on the unchanged four-WF replay.

This extends the frozen service-proxy sensitivity; it does not use the newer
wall-time predictor, calibrate hardware, or add independent fault samples.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import asdict, replace
from pathlib import Path

import run_sensitivity_campaign as shared

from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile, profile_manifest_fields

ROOT = Path(__file__).resolve().parents[5]
RELATIVE_SCRIPT = Path(__file__).resolve().relative_to(ROOT)
BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
LEVELS = (0.002, 0.005, 0.01, 0.02)


def prepare(out, source):
    parent = shared.verify(source)
    out.mkdir(parents=True, exist_ok=False)
    for directory in ("profiles", "workloads"):
        (out / directory).mkdir()
    for name in ("PRIORS.json", parent["profile"], parent["workload"]["path"]):
        shutil.copy2(source / name, out / name)
        assert shared.digest(source / name) == shared.digest(out / name)
    original = parent["protocol"]
    base = shared.Config(**{**original["baseline_config"], "hosts": tuple(original["baseline_config"]["hosts"])})
    jobs, aliases = [], []
    for value in LEVELS:
        condition = f"dma-{value:g}"
        config = asdict(replace(base, compute_dma_slowdown=value))
        aliases.append(dict(factor="compute_dma_slowdown", value=value, condition=condition, local_control=False))
        for policy in shared.POLICIES:
            for fault in ("F0", "F1"):
                jobs.append(dict(
                    id=f"{condition}-{policy}-{fault}", condition=condition,
                    policy=policy, config=config, prediction_multiplier=1.0,
                    fault=fault, f0_id=f"{condition}-{policy}-F0",
                    failure=original["failure"] if fault == "F1" else None,
                    detailed_logs=True,
                ))
    assert len(jobs) == 24
    protocol = {key: original[key] for key in (
        "models", "workflows", "agents", "repeats_per_workflow", "workflow_selection",
        "faults", "failure", "failure_descriptor", "nominal_load", "arrival_interval_ns",
        "priors", "statistics", "binding_audit",
    )}
    protocol.update(
        schema="aegiskv.post-review-low-dma.v1", status="frozen_before_execution",
        planned_runs=len(jobs), levels=list(LEVELS), factor_aliases=aliases,
        baseline_config=asdict(base), parent_campaign=str(source),
        parent_plan_sha256=shared.digest(source / "PLAN.json"),
        parent_manifest_sha256=shared.digest(source / "MANIFEST.json"),
        selection="Four coefficients fixed before any new execution; response to final external review, not original prespecification",
        unchanged="Exact workload, arrivals, same-ID 80% fault, profile, service proxy, priors, guard, L, K and runtime",
        evidence_limits=[
            "Uncalibrated multiplicative compute-delay intervention, not measured copy interference",
            "One fault and four dependent workflows, no population confidence intervals",
            "Original service-proxy predictor; not results for the new Agent-walltime predictor",
            "No monotonic interpolation or unique break-even threshold assumed under FCFS ordering changes",
            "F1 minus F0 and absolute policy-vs-Restart endpoints reported separately",
        ],
    )
    shared.write_json(out / "PROTOCOL.json", protocol)
    shared.write_json(out / "PLAN.json", dict(jobs=jobs, protocol=protocol, workload=parent["workload"], profile=parent["profile"]))
    manifest = shared.manifest(out)
    for path in [*sorted((ROOT / "python/moonkvsim").rglob("*.py")), Path(__file__).resolve(), Path(shared.__file__).resolve()]:
        relative = path.relative_to(ROOT)
        saved = out / "source_snapshot" / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
        manifest["source_sha256"][str(relative)] = shared.digest(saved)
    manifest.update(
        original_root=str(ROOT), source_execution="snapshotted Python modules",
        profile_sha256=shared.digest(out / parent["profile"]), workload=parent["workload"],
        priors_sha256=shared.digest(out / "PRIORS.json"), physical_execution=False,
        control_sha256={name: shared.digest(out / name) for name in ("PLAN.json", "PROTOCOL.json", "PRIORS.json")},
    )
    manifest.update(profile_manifest_fields(GridDurationProfile(out / parent["profile"]), [job["config"] for job in jobs]))
    shared.write_json(out / "MANIFEST.json", manifest)
    print(f"Frozen {len(jobs)} additional conditions", flush=True)


def report(out):
    shared.summarize(out)
    plan = shared.verify(out)
    source = Path(plan["protocol"]["parent_campaign"])
    assert shared.digest(source / "PLAN.json") == plan["protocol"]["parent_plan_sha256"]
    assert shared.digest(source / "MANIFEST.json") == plan["protocol"]["parent_manifest_sha256"]
    parent = shared.verify(source)
    parent_aliases = {a["condition"]: a["value"] for a in parent["protocol"]["factor_aliases"] if a["factor"] == "compute_dma_slowdown"}
    results, hashes = {}, {}
    for campaign, design, selected in ((source, parent, set(parent_aliases)), (out, plan, {j["condition"] for j in plan["jobs"]})):
        for job in design["jobs"]:
            if job["condition"] not in selected:
                continue
            _, summary = shared.verify_complete(campaign, job, design)
            results[job["config"]["compute_dma_slowdown"], job["policy"], job["fault"]] = summary
            file = campaign / "runs" / job["id"] / "summary.json"
            hashes[str(file)] = shared.digest(file)
    rows = []
    target = plan["protocol"]["failure"]["agent"].split("/")[0]
    for coefficient in sorted({k[0] for k in results}):
        for policy in shared.POLICIES:
            f0, f1 = (results[coefficient, policy, f] for f in ("F0", "F1"))
            n0, n1 = (results[coefficient, "none", f] for f in ("F0", "F1"))
            for endpoint in ("target", "cohort_sum"):
                def value(result):
                    return result["workflows"][target]["wct_ns"] if endpoint == "target" else sum(w["wct_ns"] for w in result["workflows"].values())
                healthy_cost = value(f0) - value(n0)
                # pD-H compares the SAME endpoint in a Bernoulli mixture of
                # these exact F0/F1 scenarios. It is not an empirical fault rate.
                fault_increment_saved = (value(n1) - value(n0)) - (value(f1) - value(f0))
                rows.append(dict(
                    coefficient=coefficient, policy=policy, endpoint=endpoint,
                    f0_wct_s=value(f0) / 1e9, f1_wct_s=value(f1) / 1e9,
                    healthy_cost_vs_restart_s=healthy_cost / 1e9,
                    absolute_f1_gain_vs_restart_s=(value(n1) - value(f1)) / 1e9,
                    fault_increment_saved_s=fault_increment_saved / 1e9,
                    formal_break_even_probability=(healthy_cost / fault_increment_saved if fault_increment_saved > 0 else None),
                    beneficial_probability_exists=(min(healthy_cost, healthy_cost - fault_increment_saved) < 0),
                ))
    shared.write_csv(out / "combined-dma-endpoints.csv", rows)
    shared.write_json(out / "COMBINED_PROVENANCE.json", dict(
        source_summary_sha256=hashes, additional_runs=24, referenced_existing_runs=18,
        independent_fault_identities=1, output_sha256=shared.digest(out / "combined-dma-endpoints.csv"),
        no_interpolation=True, status="PASS",
    ))
    text = ["# Low-DMA sensitivity (post-review)", "", "24 new runs plus 18 referenced prior runs; one unchanged fault, four dependent workflows. Original service proxy and uncalibrated DMA model. These are parameter points, not independent repetitions.", "", "Positive F1 gain means earlier than Restart on the same endpoint. A break-even probability above 1 cannot compensate healthy cost in this two-scenario mixture. No continuous threshold is inferred.", "", "| coefficient | policy | target F1 gain (s) | cohort-sum F1 gain (s) | cohort healthy cost (s) | cohort formal p |", "|---:|---|---:|---:|---:|---:|"]
    for row in rows:
        if row["policy"] == "none" or row["endpoint"] != "cohort_sum":
            continue
        paired = next(r for r in rows if r["coefficient"] == row["coefficient"] and r["policy"] == row["policy"] and r["endpoint"] == "target")
        p = row["formal_break_even_probability"]
        text.append(f"| {row['coefficient']:g} | {row['policy']} | {paired['absolute_f1_gain_vs_restart_s']:.9f} | {row['absolute_f1_gain_vs_restart_s']:.9f} | {row['healthy_cost_vs_restart_s']:.9f} | {p if p is not None else 'undefined'} |")
    (out / "RESULTS.md").write_text("\n".join(text) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "report"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=BASE / "sensitivity-campaign-v2-corrected")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command != "prepare":
        frozen = out / "source_snapshot" / RELATIVE_SCRIPT
        if frozen.resolve() != Path(__file__).resolve():
            os.execv(sys.executable, [sys.executable, str(frozen), args.command, "--out", str(out), "--workers", str(args.workers)])
    if args.command == "prepare":
        prepare(out, args.source.resolve())
    elif args.command == "run":
        shared.run(out, args.workers, None)
        report(out)
    else:
        report(out)


if __name__ == "__main__":
    main()
