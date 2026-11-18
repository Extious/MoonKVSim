#!/usr/bin/env python3
"""Figure 7: retain every paired seed under alternative batching assumptions."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from simulation_paper_plotting import accepted_attempt, estimate, export, style


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance-manifest", type=Path, required=True)
    parser.add_argument("--output-stem", type=Path, required=True)
    args = parser.parse_args()
    attempt = accepted_attempt(args.acceptance_manifest, {"FIGURE_7_A", "FIGURE_7_B"})
    stats = attempt["statistics"]
    style()
    fig, axes = plt.subplots(1, 2, figsize=(7, 2.7), layout="constrained")
    for ax, metric, title, ylabel, divisor in (
        (axes[0], "focus_did_relative_ppb", "(a) Failure-focus workflow",
         "Focus penalty difference (%)", 10**7),
        (axes[1], "whole_mean_did_ns", "(b) Whole workload",
         "Mean penalty difference (s)", 10**9),
    ):
        for x, beta in enumerate((0, 500, 1000)):
            values = [row[metric]/divisor for row in stats["seed_rows"]
                      if row["batch_serialization_per_mille"] == beta]
            ax.scatter(x+np.linspace(-.16, .16, 5), values, s=22,
                       facecolors="none", edgecolors="0.3")
            mean, low, high = estimate(stats["models"][str(beta)][metric], divisor)
            ax.errorbar(x+.25, mean, yerr=[[mean-low], [high-mean]], fmt="s",
                        color="black", markersize=4, capsize=3)
        ax.axhline(0, linestyle="--", color="0.4", linewidth=.8)
        ax.set_xticks([0, 1, 2], ["0 (max)", "0.5", "1 (sum)"])
        ax.set_xlabel(r"Batch serialization weight $\beta$")
        ax.set_ylabel(ylabel)
        ax.set_title(title, loc="left")
        ax.grid(axis="y", alpha=.2)
        ax.set_xlim(-.5, 2.6)
    export(fig, args.output_stem, generator=Path(__file__),
           inputs=[args.acceptance_manifest], data={
               "statistics": stats, "accepted_attempt_fingerprint": attempt["fingerprint"],
               "sign": ("(Aegis F1 - Aegis F0) - (Store-only F1 - Store-only F0); "
                        "negative favors Aegis"),
               "focus_normalization": "per-seed Store-only F0 focus WCT",
               "model_interpretation": "alternative assumptions, not calibrated hardware bounds",
               "smoothing": False,
           })


if __name__ == "__main__":
    main()
