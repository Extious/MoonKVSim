#!/usr/bin/env python3
"""Paper-facing replacement numbers from corrected auxiliary summaries only."""
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

from audit_o1_dma_evidence import Evidence, campaign, dma_rows, encoded, write_csv


def read_csv(path):
    return list(csv.DictReader(path.open()))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    args = parser.parse_args()
    base = args.base.resolve()
    sens = base / "sensitivity-campaign-v2-corrected"
    cap = base / "capacity-slack-ablation-v2-corrected"
    evidence = Evidence()
    plan, manifest, runs = campaign(evidence, sens)
    primary_path = base / "reviews/o1-dma-corrected-v2-audit/AUDIT.json"
    primary = None
    if primary_path.exists():
        primary = evidence.read(primary_path)
        assert primary["status"] == "PASS"
        assert primary["primary_runs_verified"] == 180
        assert primary["sensitivity_runs_verified"] == 126
        assert primary["design_versions"]["sensitivity"] == manifest["design_version"]
    dma, dma_workflows = dma_rows(plan, runs)
    target = plan["protocol"]["failure"]["agent"].split("/")[0]

    def condition(factor, value):
        return next(
            a["condition"]
            for a in plan["protocol"]["factor_aliases"]
            if a["factor"] == factor and a["value"] == value
        )

    def penalty(identity, policy):
        f0 = runs[f"{identity}-{policy}-F0"][1]
        f1 = runs[f"{identity}-{policy}-F1"][1]
        return (f1["workflows"][target]["wct_ns"] - f0["workflows"][target]["wct_ns"]) / 1e9

    bandwidth = []
    for speed in (8, 16, 32, 64):
        identity = condition("h2d_GBps", speed)
        d, a = (penalty(identity, policy) for policy in ("dram", "aegiskv"))
        bandwidth.append(
            dict(
                h2d_GBps=speed,
                dram_penalty_ms=d * 1000,
                aegiskv_penalty_ms=a * 1000,
                hbm_increment_ms=(d - a) * 1000,
            )
        )
    center = {policy: penalty("center", policy) for policy in ("none", "dram", "aegiskv")}
    cost = read_csv(cap / "variant-cost-results.csv")
    capacity = []
    for budget in (2, 4, 8, 256):
        selected = {
            r["variant"]: r for r in cost if int(r["capacity_GiB"]) == budget and r["phase"] == "F0"
        }
        current, zero = (
            float(selected[v]["modeled_backup_transfer_bytes"])
            for v in ("aegiskv", "aegiskv_no_slack")
        )
        capacity.append(
            dict(
                capacity_GiB=budget,
                current_backup_GiB=current / 2**30,
                zero_slack_backup_GiB=zero / 2**30,
                reduction_pct=100 * (1 - current / zero),
            )
        )
    cap_audit = evidence.read(cap / "INDEPENDENT_VARIANT_AUDIT.json")
    binding = read_csv(sens / "binding-diagnostics.csv")
    noncross = []
    for factor in (
        "online_prediction_multiplier",
        "prediction_latency_ms_at_TTL100ms",
        "tolerance_seconds",
    ):
        for policy in ("none", "dram", "aegiskv"):
            values = [
                (a["value"], penalty(a["condition"], policy))
                for a in plan["protocol"]["factor_aliases"]
                if a["factor"] == factor
            ]
            noncross.append(
                dict(
                    factor=factor,
                    policy=policy,
                    values=values,
                    max_minus_min_s=max(y for _, y in values) - min(y for _, y in values),
                )
            )
    small_dram = [
        r
        for r in binding
        if r["policy"] in ("dram", "aegiskv")
        and r["fault"] == "F1"
        and r["condition"] in {condition("dram_GiB_per_host", v) for v in (0.25, 1)}
    ]
    stale = [
        r
        for r in binding
        if r["fault"] == "F0"
        and r["condition"]
        in {condition("prediction_latency_ms_at_TTL100ms", v) for v in (0.1, 200)}
    ]
    checkpoint = [
        {
            "Z": z,
            **{
                p: penalty(condition("checkpoint_tokens", z), p)
                for p in ("none", "dram", "aegiskv")
            },
        }
        for z in (64, 256, 1024)
    ]
    paired = read_csv(sens / "paired-workflows.csv")
    for directory, names in (
        (
            sens,
            [
                "AUDIT.json",
                "PLAN.json",
                "MANIFEST.json",
                "paired-workflows.csv",
                "binding-diagnostics.csv",
            ],
        ),
        (cap, ["AUDIT.json", "INDEPENDENT_VARIANT_AUDIT.json", "variant-cost-results.csv"]),
    ):
        for name in names:
            evidence.bytes(directory / name)
    report = dict(
        design_version=manifest["design_version"],
        complete_auxiliary_conditions=168,
        bandwidth=bandwidth,
        center_target_penalty_s=center,
        capacity_traffic=capacity,
        capacity_all_workflow_records_equal=cap_audit[
            "all_workflow_completions_equal_current_vs_zero_for_F0_F1_at_all_capacities"
        ],
        dma=dma,
        non_boundary_crossing_controls=noncross,
        small_dram_binding=small_dram,
        stale_reply_diagnostics=stale,
        checkpoint_penalty_s=checkpoint,
        negative_paired_workflow_deltas=sum(float(r["delta_wct_s"]) < 0 for r in paired),
        primary_o1_audit=(
            {"status": "PASS", "path": str(primary_path), "sha256": sha(primary_path)}
            if primary else
            "pending full corrected primary 180/AUDIT PASS; these numbers use auxiliary groups only"
        ),
        input_sha256=evidence.hashes,
        script_sha256=sha(Path(__file__)),
        dma_formula="H=policyF0-noneF0; D=(noneF1-noneF0)-(policyF1-policyF0); expected advantage=pD-H, only for this binary fixed-scenario mixture",
    )
    out = base / "reviews"
    write_csv(out / "DMA_CORRECTED_V2_SCENARIOS.csv", dma)
    write_csv(out / "DMA_CORRECTED_V2_WORKFLOWS.csv", dma_workflows)
    (out / "PAPER_NUMBERS_V2.json").write_bytes(encoded(report))
    lines = [
        "# Corrected auxiliary numbers for the Evaluation draft",
        "",
        "All numbers below come from the 126 + 32 corrected conditions; old runs remain historical versions. They are not added repetitions. Timing is AIC-informed and uncalibrated. No paper source was edited.",
        "",
        f"Source: `{manifest['design_version']}`. Detailed bindings and raw precision: `PAPER_NUMBERS_V2.json`.",
        "",
        "## H2D and center",
        "",
        "| H2D GB/s | DRAM target penalty (ms) | AegisKV target penalty (ms) | DRAM - AegisKV (ms) |",
        "|---:|---:|---:|---:|",
    ]
    for r in bandwidth:
        lines.append(
            f"| {r['h2d_GBps']} | {r['dram_penalty_ms']:.6f} | {r['aegiskv_penalty_ms']:.6f} | {r['hbm_increment_ms']:.6f} |"
        )
    lines += [
        "",
        f"Center target penalties: Restart {center['none']:.9f} s; DRAM {center['dram']:.9f} s; AegisKV {center['aegiskv']:.9f} s. HBM adds {(center['dram'] - center['aegiskv']) * 1000:.6f} ms.",
        "",
        "## Capacity / zero Slack",
        "",
        f"All Current-versus-zero-Slack workflow records equal across four capacities and F0/F1: **{report['capacity_all_workflow_records_equal']}**. This is 32 paired workflow records, not 32 independent samples. Zero Slack affects both DRAM exposure and HBM gain, so this is not O1-only.",
        "",
        "| DRAM GiB/host | Current healthy backup GiB | Zero-Slack healthy backup GiB | Reduction |",
        "|---:|---:|---:|---:|",
    ]
    for r in capacity:
        lines.append(
            f"| {r['capacity_GiB']} | {r['current_backup_GiB']:.9f} | {r['zero_slack_backup_GiB']:.9f} | {r['reduction_pct']:.6f}% |"
        )
    lines += [
        "",
        "Backup includes completed checkpoint + hot-placement + canceled-transferred bytes. In the 0.25/1 GiB sensitivity cases, target checkpoint remains zero; peak host occupancy remains about 98.45%, and both backup policies have Restart penalty 1.802310283 s. HBM cap 0/32 MiB does not improve the target over DRAM. These finite tests do not establish a universal threshold.",
        "",
        "## DMA healthy cost and matched-objective break-even",
        "",
        "| Slowdown | Policy | Healthy mean WCT s | Mean increase | Target healthy extra s | Target incremental fault advantage s | Target p* | Cohort p* |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in dma:
        if r["metric"] != "four_workflow_sum_wct" or r["dma_slowdown"] == 0:
            continue
        t = next(
            t
            for t in dma
            if t["condition"] == r["condition"]
            and t["policy"] == r["policy"]
            and t["metric"] == "target_workflow_wct"
        )
        lines.append(
            f"| {r['dma_slowdown']} | {r['policy']} | {r['policy_healthy_mean_wct_s']:.9f} | {r['healthy_wct_increase_pct']:.6f}% | {t['healthy_extra_s']:.9f} | {t['incremental_fault_advantage_s']:.9f} | {t['hypothetical_break_even_probability']:.9f} | {r['hypothetical_break_even_probability']:.9f} |"
        )
    lines += [
        "",
        "Restart healthy mean is 8.398206670 s; maximum 19.354031920 s. DRAM/AegisKV maximum is 19.968400114 s at 0.05 and 20.582768102 s at 0.1. The target-only and four-workflow-sum objectives have separate H and D. Under the hypothetical mixture of F0 and this exact F1, advantage is pD-H; cohort p*>1 has no feasible break-even in [0,1]. These are not measured failure rates, nor extrapolations to other or multiple faults. A smaller F1-F0 under slowdown does not mean faster absolute service.",
        "",
        "## Controls that do not cross the target decision boundary",
        "",
    ]
    for factor in (
        "online_prediction_multiplier",
        "prediction_latency_ms_at_TTL100ms",
        "tolerance_seconds",
    ):
        rows = [r for r in noncross if r["factor"] == factor]
        lines.append(
            f"- `{factor}`: maximum target-penalty spread across tested levels is {max(r['max_minus_min_s'] for r in rows):.9f} s for every policy; this is a finite null, not predictor accuracy or staleness robustness."
        )
    lines += [
        "- TTL pair: all 52 replies at 200 ms exceed the 100 ms TTL; zero at 0.1 ms. Accepted publication is not valid-for-Slack evidence. No exact timeout count is claimed.",
        "- Detection levels remain 1/10/100 ms. Their exposure and other controls are retained in the complete raw tables.",
        "",
        "| Z tokens | Restart penalty s | DRAM penalty s | AegisKV penalty s |",
        "|---:|---:|---:|---:|",
    ]
    for r in checkpoint:
        lines.append(f"| {r['Z']} | {r['none']:.9f} | {r['dram']:.9f} | {r['aegiskv']:.9f} |")
    lines += [
        "",
        f"Z=64 also forces at-most-64-token forward chunks, while Z=1024 keeps the 256-token compute chunk. This is a coupled compute/checkpoint intervention. All {report['negative_paired_workflow_deltas']} negative paired collateral outcomes remain in the CSV; one length-selected fixed fault is the independent intervention, not a failure population.",
        "",
        "The new 10-point post-hoc audit is separate: tight DAG ΔWCT 23.974643 ms, zero 134.793723 ms (difference 110.819080 ms); 4 GiB remains null. See POSTHOC_SLACK_V2_INDEPENDENT_REVIEW.md for the fault-entry/budget chain and observer checks.",
        "",
        (
            "The full corrected primary O1/DMA audit now passes all 180 primary and 126 sensitivity runs. "
            "See [primary O1 numbers and historical comparison](o1-dma-corrected-v2-audit/PAPER_O1_NUMBERS_V2.md) "
            "for the exact fallback denominators, both traffic definitions, and version changes. "
            "The auxiliary numbers above are unchanged by this finalization."
            if primary else
            "Full corrected primary O1/fallback numbers are deliberately pending the 180-point primary audit. Do not replace them with historical v1 numbers."
        ),
        "",
    ]
    (out / "PAPER_NUMBERS_V2.md").write_text("\n".join(lines))
    print("wrote PAPER_NUMBERS_V2.md/json and corrected DMA raw tables")


if __name__ == "__main__":
    main()
