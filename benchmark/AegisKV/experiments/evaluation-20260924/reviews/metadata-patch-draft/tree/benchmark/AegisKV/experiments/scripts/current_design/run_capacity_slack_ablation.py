#!/usr/bin/env python3
"""Four fixed DRAM capacities x four policy variants x paired F0/F1.

Reuses the completed/pinned sensitivity workload without refitting or selecting
workflows again. no_slack remains policy=aegiskv with Config.slack_mode=zero.
"""

from __future__ import annotations

import argparse
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
VARIANTS = (
    ("dram", "dram", "dag"),
    ("all_dram", "all_dram", "dag"),
    ("aegiskv", "aegiskv", "dag"),
    ("aegiskv_no_slack", "aegiskv", "zero"),
)


def prepare(out, source):
    out.mkdir(parents=True, exist_ok=False)
    parent = shared.verify(source)
    for directory in ("profiles", "workloads"):
        (out / directory).mkdir()
    for name in ("PRIORS.json", parent["profile"], parent["workload"]["path"]):
        shutil.copy2(source / name, out / name)
        assert shared.digest(source / name) == shared.digest(out / name)
    original = parent["protocol"]
    base = shared.Config(
        **{
            **original["baseline_config"],
            "hosts": tuple(original["baseline_config"]["hosts"]),
        }
    )
    assert base.slack_mode == "dag"
    jobs, aliases = [], []
    for capacity in (2, 4, 8, 256):
        condition = f"dram-{capacity}GiB"
        aliases.append(
            dict(
                factor="dram_GiB_per_host", value=capacity, condition=condition, local_control=False
            )
        )
        for variant, policy, slack_mode in VARIANTS:
            config = replace(base, dram_bytes_per_host=capacity * 1024**3, slack_mode=slack_mode)
            f0 = f"{condition}-{variant}-F0"
            for fault in ("F0", "F1"):
                jobs.append(
                    dict(
                        id=f"{condition}-{variant}-{fault}",
                        condition=condition,
                        variant=variant,
                        policy=policy,
                        config=asdict(config),
                        prediction_multiplier=1.0,
                        fault=fault,
                        f0_id=f0,
                        failure=original["failure"] if fault == "F1" else None,
                        detailed_logs=False,
                    )
                )
    assert len(jobs) == 32 and len({job["id"] for job in jobs}) == 32
    protocol = {
        key: original[key]
        for key in (
            "models",
            "workflows",
            "agents",
            "repeats_per_workflow",
            "workflow_selection",
            "faults",
            "failure",
            "failure_descriptor",
            "nominal_load",
            "arrival_interval_ns",
            "priors",
            "statistics",
            "binding_audit",
        )
    }
    protocol.update(
        schema="aegiskv.capacity-slack-ablation.v1",
        status="frozen_before_execution",
        planned_runs=32,
        capacities_GiB_per_host=[2, 4, 8, 256],
        factor_aliases=aliases,
        variants=[dict(variant=v, policy=p, slack_mode=s) for v, p, s in VARIANTS],
        selection="capacities bracket ~2.4GB target checkpoint and concurrent footprints",
        parent_campaign=str(source),
        parent_plan_sha256=shared.digest(source / "PLAN.json"),
        parent_manifest_sha256=shared.digest(source / "MANIFEST.json"),
        baseline_config=asdict(base),
        unchanged="exact workload, arrivals, failure, profile, training priors, guard, L and K",
        no_slack="policy=aegiskv; Config.slack_mode=zero; Tracker async events remain active",
        all_dram="separate full-selection baseline, not a no-Slack ablation",
        evidence_limits=[
            "one fixed fault and four dependent workflows; no population confidence interval",
            "modeled finite-capacity intervention; not evidence of real predictor accuracy",
            "capacities use fixed checkpoint/concurrency sizes, not observed policy gains",
            "coarse counters and peaks; no complete master-budget denial count",
        ],
    )
    shared.write_json(out / "PROTOCOL.json", protocol)
    shared.write_json(
        out / "PLAN.json",
        dict(jobs=jobs, protocol=protocol, workload=parent["workload"], profile=parent["profile"]),
    )
    source_manifest = shared.manifest(out)
    paths = [
        *sorted((ROOT / "python/moonkvsim").rglob("*.py")),
        Path(__file__).resolve(),
        Path(shared.__file__).resolve(),
    ]
    for path in paths:
        relative = path.relative_to(ROOT)
        target = out / "source_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        source_manifest["source_sha256"][str(relative)] = shared.digest(target)
    source_manifest.update(
        original_root=str(ROOT),
        source_execution="snapshotted Python modules",
        profile_sha256=shared.digest(out / parent["profile"]),
        workload=parent["workload"],
        priors_sha256=shared.digest(out / "PRIORS.json"),
        physical_execution=False,
        control_sha256={
            name: shared.digest(out / name)
            for name in ("PLAN.json", "PROTOCOL.json", "PRIORS.json")
        },
    )
    source_manifest.update(
        profile_manifest_fields(
            GridDurationProfile(out / parent["profile"]), [job["config"] for job in jobs]
        )
    )
    shared.write_json(out / "MANIFEST.json", source_manifest)
    (out / "README.md").write_text(
        "# Finite-capacity Slack ablation\n\n"
        "32 frozen runs: DRAM per host 2/4/8/256 GiB, four policy variants and paired F0/F1. "
        "The source sensitivity campaign's four full workflows, 52 Agents, profile, priors, "
        "arrivals and same-ID 80%-progress fault are copied byte-for-byte. "
        "No L/K/guard retuning.\n\n"
        "Variants: dram; all_dram; aegiskv; aegiskv_no_slack. The last still reports "
        "summary.policy=aegiskv, with the auditable Config.slack_mode=zero. Tracker predictions "
        "and asynchronous events remain active; Slack used by protection decisions is zero. "
        "All-DRAM is a separate selection baseline and must not be relabeled no-Slack.\n\n"
        "Capacities bracket the fixed target checkpoint size (~2.4 GB) and concurrent footprints; "
        "they are not chosen by observed benefit. This is one fixed fault intervention with four "
        "dependent workflows, not random-failure sampling or real prediction-accuracy evidence. "
        "Raw metrics, paired workflow deltas, negatives and binding diagnostics are retained. "
        "There is no complete master budget denial counter or independent per-flow audit for "
        "these summary-only runs. PLAN/PROTOCOL/PRIORS and sources are snapshotted and sealed.\n"
    )
    print(f"frozen 32 runs at {out}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "summarize"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=BASE / "sensitivity-campaign-v1")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--limit", type=int)
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
            if args.limit is not None:
                command += ["--limit", str(args.limit)]
            os.execv(sys.executable, command)
    if args.command == "prepare":
        prepare(out, args.source.resolve())
    elif args.command == "run":
        shared.run(out, args.workers, args.limit)
    else:
        shared.summarize(out)


if __name__ == "__main__":
    main()
