#!/usr/bin/env python3
"""Figure 6: cost/effect associations, ablations, and the five lowest effects."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from simulation_paper_plotting import accepted_attempt, estimate, export, style

AEGIS = "aegiskv_unified"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sweep-acceptance", type=Path, required=True)
    parser.add_argument("--ablation-acceptance", type=Path, required=True)
    parser.add_argument("--output-stem", type=Path, required=True)
    args = parser.parse_args()
    sweep = accepted_attempt(args.sweep_acceptance, {"FIGURE_6_A", "FIGURE_6_B", "FIGURE_6_D"})
    ablation = accepted_attempt(args.ablation_acceptance, {"FIGURE_6_C"})
    costs, abl = sweep["statistics"]["cost_effect"], ablation["statistics"]
    style()
    fig = plt.figure(figsize=(7, 6.4), layout="constrained")
    grid = fig.add_gridspec(4, 2, height_ratios=[1.2, .22, .95, 1.1])
    axes = [fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1]),
            fig.add_subplot(grid[2, :]), fig.add_subplot(grid[3, :])]
    markers = ["o", "s", "^", "v", "D", "P", "X"]
    legend_axis = fig.add_subplot(grid[1, :])
    legend_axis.set_axis_off()
    legend_axis.legend(
        [Line2D([], [], marker=marker, linestyle="none", color="0.3",
                markerfacecolor="white", markersize=5) for marker in markers],
        [f"F={point['failure_count']}, C={point['workflow_concurrency']}"
         for point in costs["points"]],
        loc="center", ncol=4, frameon=False, handlelength=1, columnspacing=1,
    )
    for ax, xfield, xscale, yfield, title, xlabel, ylabel in (
        (axes[0], "protection_transferred_bytes", 1024**3, "focus_mean_gain_percent",
         "(a) Protection cost and completion", "AegisKV protection (GiB/run)",
         "Focus mean WCT gain (%)"),
        (axes[1], "restored_prompt_percent", 10**6, "focus_p95_gain_percent",
         "(b) Restored prefix and completion", "AegisKV restored prompt (%)",
         "Focus P95 WCT gain (%)"),
    ):
        for marker, point in zip(markers, costs["points"], strict=True):
            x, xl, xh = estimate(point[xfield][AEGIS]["estimate"], xscale)
            y, yl, yh = estimate(point[yfield]["estimate"], 10**6)
            ax.errorbar(x, y, xerr=[[x-xl], [xh-x]], yerr=[[y-yl], [yh-y]],
                        marker=marker, color="0.3", markerfacecolor="white",
                        markersize=5, capsize=2, linewidth=.8)
        ax.axhline(0, color="0.4", linestyle="--", linewidth=.8)
        ax.set(xlabel=xlabel, ylabel=ylabel)
        ax.set_title(title, loc="left")
        ax.grid(alpha=.2)
        ax.margins(x=.22, y=.22)
    ax = axes[2]
    arms = ("full", "no_slack", "lru_eviction", "no_aimd")
    for x, arm in enumerate(arms):
        values = [row["focus_did_ns"]/10**9 for row in abl["seed_rows"] if row["arm"] == arm]
        ax.scatter(x+np.linspace(-.16, .16, 5), values, s=22,
                   facecolors="none", edgecolors="0.3")
        mean, low, high = estimate(abl["arms"][arm]["focus_did_ns"], 10**9)
        ax.errorbar(x+.25, mean, yerr=[[mean-low], [high-mean]], fmt="s", color="black",
                    markersize=4, capsize=3)
    ax.axhline(0, color="0.4", linestyle="--", linewidth=.8)
    ax.set_xticks(range(4), ["Full", "No slack", "LRU eviction", "No AIMD"])
    ax.set_title("(c) Ablation: change in focus failure penalty", loc="left")
    ax.set_ylabel("Additional penalty (s)")
    ax.set_xlim(-.5, 3.6)
    ax.grid(axis="y", alpha=.2)
    ax = axes[3]
    ax.set_axis_off()
    ax.set_title("(d) Five lowest paired workflow effects", loc="left", pad=10)
    rows = []
    for row in costs["five_lowest_paired_effects"]:
        exact = row["gain_percent_exact"]
        completion = row["wct_ns"]
        rows.append([str(row["seed"]), f"{row['failure_count']}/{row['workflow_concurrency']}",
                     row["workflow_id"],
                     f"{completion['vanilla_mooncake_dram']/1e9:.2f} / "
                     f"{completion[AEGIS]/1e9:.2f}",
                     f"{exact['numerator']/exact['denominator']:.2f}%"])
    table = ax.table(cellText=rows,
                     colLabels=["Seed", "F/C", "Workflow ID", "Store / Aegis\nWCT (s)", "WCT gain"],
                     bbox=[0, 0, 1, .88], cellLoc="center",
                     colWidths=[.07, .07, .29, .37, .20])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.65)
    for (row, _col), cell in table.get_celld().items():
        cell.set_linewidth(.4)
        cell.set_edgecolor("0.7")
        if row == 0:
            cell.set_facecolor("0.9")
            cell.set_height(cell.get_height() * 1.7)
    export(fig, args.output_stem, generator=Path(__file__),
           inputs=[args.sweep_acceptance, args.ablation_acceptance], data={
               "cost_effect": costs, "ablation": abl,
               "panel_ab_labels": ("shared F/C marker legend; five-seed mean and "
                                   "95% intervals on both axes"),
               "panel_ab_sign": "positive means lower AegisKV WCT in failure runs",
               "panel_c_sign": "(ablation F1 - ablation F0) - (full F1 - full F0)",
               "table_identity_note": ("full workflow IDs and paired completion times; "
                                       "focus request IDs and raw hashes are in this sidecar"),
               "smoothing": False,
           })


if __name__ == "__main__":
    main()
