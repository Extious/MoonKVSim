#!/usr/bin/env python3
"""Render complete Figure 1 from a VALID primary campaign and frozen workload."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from build_qwen3_8b_figure1_evidence import build
from matplotlib.ticker import ScalarFormatter
from simulation_paper_plotting import accepted_attempt, export, style


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--output-stem", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    attempt = accepted_attempt(args.acceptance, {"FIGURE_3_A"})
    source = root / attempt["gates"][1]["evidence"]["source_root"]
    workload = source / "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl"
    manifest = workload.with_name(workload.stem + "-manifest.json")
    campaign_path = root / attempt["artifact"]["path"]
    evidence = build(workload_path=workload, workload_manifest_path=manifest,
                     campaign_path=campaign_path, acceptance_path=args.acceptance)
    campaign = json.loads(campaign_path.read_text())
    interventions = evidence["intervention_audit"]["seed_contracts"]
    for row, seed in zip(interventions, campaign["seeds"], strict=True):
        row["request_progress_per_mille"] = (
            seed["failure_schedule"]["events"][0]["trigger"]["progress_per_mille"])
    population = evidence["workload"]
    style()
    fig = plt.figure(figsize=(7, 5.4), layout="constrained")
    grid = fig.add_gridspec(3, 2, height_ratios=[1, 1.1, .95])
    for ax, values, xlabel, title in (
        (fig.add_subplot(grid[0, 0]), sorted(population["prompt_tokens"]),
         "Prompt tokens (log scale)", "(a) All 1,304 model calls"),
        (fig.add_subplot(grid[0, 1]), sorted(population["workflow_span_counts"].values()),
         "Model calls per workflow", "(b) All 160 complete workflows"),
    ):
        ax.step(np.r_[values[0], values],
                np.r_[0, np.arange(1, len(values) + 1) / len(values)],
                where="post", color="0.15", linewidth=1.4)
        ax.set(xlabel=xlabel, ylabel="Empirical CDF", ylim=(0, 1.04))
        ax.set_title(title, loc="left")
        ax.set_yticks([0, .5, 1])
        ax.grid(axis="y", color="0.88", linewidth=.5)
        if "Prompt" in xlabel:
            ax.set_xscale("log")
            ax.xaxis.set_major_formatter(ScalarFormatter())
    ax = fig.add_subplot(grid[1, :])
    buckets = ["8k", "32k", "64k", "96k", "128k"]
    focuses = Counter(row["focus_bucket"] for row in interventions)
    positions = np.arange(5)
    for offset, counts, total, shade, hatch, label in (
        (-.18, population["context_bucket_counts"], 1304, "0.75", None, "All calls (n=1,304)"),
        (.18, focuses, 5, "0.3", "//", "Failure focuses (n=5)"),
    ):
        heights = [100 * counts[bucket] / total for bucket in buckets]
        ax.bar(positions + offset, heights, .34, color=shade, hatch=hatch,
               edgecolor="0.25", linewidth=.5, label=label)
        for x, height, bucket in zip(positions + offset, heights, buckets, strict=True):
            ax.text(x, height + 2, str(counts[bucket]), ha="center", va="bottom")
    ax.set_title("(c) Context coverage and selected failure focuses", loc="left")
    ax.set(ylabel="Within-population fraction (%)", ylim=(0, 117))
    ax.set_xticks(positions, ["≤8K", "8-32K", "32-64K", "64-96K", "96-128K"])
    ax.set_xlabel("Prompt + output context bucket; labels above bars are counts")
    ax.legend(frameon=False, loc="upper left", ncol=1)
    ax.grid(axis="y", color="0.88", linewidth=.5)
    ax.set_axisbelow(True)
    ax = fig.add_subplot(grid[2, :])
    ax.axis("off")
    ax.set_title("(d) Planned and realized intervention (Store-only / AegisKV)", loc="left")
    table_rows = []
    short_identities = {}
    for row in interventions:
        _, workflow_id, request_id = row["focus_span_id"].split(":")
        short = f"{workflow_id[:8]}/{request_id[:8]}"
        if short in short_identities and short_identities[short] != row["focus_span_id"]:
            raise ValueError("displayed focus identities collide")
        short_identities[short] = row["focus_span_id"]
        control, aegis = [row["systems"][key] for key in
                          ("vanilla_mooncake_dram", "aegiskv_unified")]
        table_rows.append([
            str(row["seed"]), workflow_id[:8], request_id[:8],
            f"{row['request_progress_per_mille'] / 10:g}%",
            row["physical_failure_target"].removeprefix("gpu-"),
            f"{control['injection_timestamp_ns'] / 1e9:.3f} / "
            f"{aegis['injection_timestamp_ns'] / 1e9:.3f}",
            f"{control['active_victim_count']},{control['queued_victim_count']} / "
            f"{aegis['active_victim_count']},{aegis['queued_victim_count']}",
        ])
    table = ax.table(cellText=table_rows,
                     colLabels=["Seed", "Workflow\nID", "Request\nID", "Request\nprogress", "GPU",
                                "Injection time (s)", "Victims\n(active, queued)"],
                     colWidths=[.065, .14, .14, .115, .055, .25, .235],
                     cellLoc="center", bbox=[0, 0, 1, .94])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    for (row, _), cell in table.get_celld().items():
        cell.set_linewidth(.35)
        cell.set_edgecolor("0.8")
        if row == 0:
            cell.set_facecolor("0.91")
            cell.set_height(cell.get_height() * 1.5)
    export(fig, args.output_stem, generator=Path(__file__),
           inputs=[args.acceptance, workload, manifest, campaign_path],
           data={"evidence": evidence, "display_identity_map": short_identities,
                 "interval": "none; finite-population descriptive panels",
                 "victims_and_timestamps": "post-treatment outcomes; not forced equal",
                 "request_progress_is_not_workload_proposal_position": True})


if __name__ == "__main__":
    main()
