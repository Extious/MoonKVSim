#!/usr/bin/env python3
"""Figure 5: all six predeclared sensitivity rows, with five paired seeds."""
from __future__ import annotations

import argparse
import json
from fractions import Fraction
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from simulation_paper_plotting import accepted_attempt, estimate, export, style

from moonkvsim.aegiskv.paper_artifacts import file_sha256
from moonkvsim.aegiskv.paper_sweep_statistics import _summarize
from moonkvsim.aegiskv.qwen3_8b_acceptance import load_json_strict

STORE, AEGIS = "vanilla_mooncake_dram", "aegiskv_unified"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance-manifest", type=Path, required=True)
    parser.add_argument("--output-stem", type=Path, required=True)
    args = parser.parse_args()
    attempt = accepted_attempt(args.acceptance_manifest,
                               {f"FIGURE_5_{letter}" for letter in "ABCDEF"})
    root = Path(__file__).resolve().parents[4]
    artifact_path = root / attempt["artifact"]["path"]
    artifact = load_json_strict(artifact_path)
    source = root / attempt["gates"][1]["evidence"].get("source_root", ".")
    binding = artifact["provenance"]["workload"]
    workload = source / binding["declared_path"]
    if file_sha256(workload) != binding["sha256"]:
        raise ValueError("sensitivity figure workload changed")
    prompts = {}
    with workload.open() as stream:
        for line in stream:
            r = json.loads(line)
            prompts[r["span_id"]] = r["prompt_tokens"]
    points = {(c["failure_count"], c["workflow_concurrency"]): c["statistics"]
              for c in artifact["cells"]}
    fractions = {}
    for identity in points:
        cells = [c for c in artifact["raw_seed_cells"]
                 if (c["failure_count"], c["workflow_concurrency"]) == identity]
        series = {}
        for system, tier in ((AEGIS, "peer"), (AEGIS, "store"), (STORE, "store")):
            values = []
            for cell in cells:
                focus = cell["systems"][system]["run"]["failure_focus_spans"]
                denominator = sum(prompts[r["span_id"]] for r in focus)
                numerator = sum(r[f"restored_{tier}_tokens"] for r in focus)
                if not 0 <= numerator <= denominator:
                    raise ValueError("selected tier fraction is outside its frozen denominator")
                values.append((cell["seed"], Fraction(numerator * 100, denominator)))
            series[f"{system}:{tier}"] = _summarize(values, unit="percent", scale=10**6)
        fractions[identity] = series
    style()
    fig, axes = plt.subplots(6, 2, figsize=(7, 7.3), sharex="col", layout="constrained")
    panel_data = {}
    for col, identities, xs, title in (
        (0, [(f, 16) for f in (1, 2, 4, 8)], [1, 2, 4, 8], "Failure count; C=16"),
        (1, [(2, c) for c in (8, 16, 24, 32)], [8, 16, 24, 32], "Concurrency; F=2"),
    ):
        selected = [points[i] for i in identities]
        row_series = [
            [("Store-only", "o", "0.6", [s["absolute_mean_wct_ns"]["failure_focus"][STORE]
                                           for s in selected], 10**9),
             ("AegisKV", "x", "0.1", [s["absolute_mean_wct_ns"]["failure_focus"][AEGIS]
                                        for s in selected], 10**9)],
            [("Gain", "o", "0.1", [s["wct_gain"]["failure_focus_mean"] for s in selected], 10**6)],
            [("Gain", "o", "0.1", [s["wct_gain"]["failure_focus_p95"] for s in selected], 10**6)],
            [(label, marker, shade,
              [s["failure_impacted_workflow_count"][key] for s in selected], 1)
             for key, label, marker, shade in (("logical_focus", "Focus", "D", "0.1"),
                                              (STORE, "Store victims", "o", "0.6"),
                                              (AEGIS, "Aegis victims", "x", "0.1"))],
            [("Quota", "o", "0.6", [s["aimd"]["time_weighted_mean"] for s in selected], 10**4),
             ("Pressure", "x", "0.1", [s["aimd"]["pressure_event_rate"] for s in selected], 10**6)],
            [(label, marker, shade, [fractions[i][f"{system}:{tier}"] for i in identities], 10**6)
             for system, tier, label, marker, shade in (
                 (AEGIS, "peer", "Aegis Peer", "o", "0.1"),
                 (AEGIS, "store", "Aegis Store", "x", "0.1"),
                 (STORE, "store", "Store-only", "^", "0.6"))],
        ]
        for row, series in enumerate(row_series):
            ax = axes[row, col]
            for label, marker, shade, summaries, scale in series:
                triples = [estimate(s["estimate"], scale) for s in summaries]
                means, lows, highs = np.array(triples).T
                ax.errorbar(xs, means, yerr=[means-lows, highs-means], fmt=marker+"-",
                            color=shade, markersize=3.5, capsize=2, linewidth=.8, label=label)
                for x, summary in zip(xs, summaries, strict=True):
                    values = [v["rounded_value"]/scale for v in summary["per_seed"]]
                    ax.scatter(x+np.linspace(-.025, .025, 5)*(max(xs)-min(xs)), values,
                               color=shade, marker=marker, s=8, alpha=.35)
            if row in (1, 2):
                ax.axhline(0, color="0.6", linestyle="--", linewidth=.6)
            ax.grid(axis="y", alpha=.2)
            ax.set_xticks(xs)
            ax.tick_params(axis="x", labelbottom=row == 5)
            ax.margins(x=.13, y=.2)
            ax.locator_params(axis="y", nbins=3)
            if col == 0:
                ax.set_ylabel(("(a) Mean WCT\n(s)", "(b) Mean gain\n(%)",
                               "(c) P95 gain\n(%)", "(d) Workflow\ncount",
                               "(e) Quota /\npressure (%)", "(f) Selected\nprompt (%)")[row])
            if col == 1 and row in (0, 3, 4):
                ax.legend(frameon=False, loc="best", ncol=1, handlelength=1,
                          borderpad=.1, labelspacing=.1, handletextpad=.4)
        axes[0, col].set_title(title)
        axes[5, col].set_xlabel("GPU failures per run" if col == 0 else "Workflow concurrency")
        panel_data[str(col)] = {"identities": identities, "statistics": selected,
                               "selected_tier_fractions": [fractions[i] for i in identities]}
    handles, labels = axes[5, 1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=3, frameon=False,
               handlelength=1, columnspacing=1.2)
    export(fig, args.output_stem, generator=Path(__file__),
           inputs=[args.acceptance_manifest, artifact_path, workload], data={
               "columns": panel_data, "gain_sign": "positive means lower AegisKV WCT",
               "comparison": "policy contrast in failure runs; no F0 subtraction",
               "selected_tier_denominator": "sum of frozen prompt tokens over logical failure foci",
               "focus_p95": ("nearest rank; equals the maximum "
                             "when the focus cohort has under 20 tasks"),
               "repeated_base_point": "F2,C16 is the same paired cell in both columns",
               "lines": "connect only observed seed means; no smoothing or monotonic fit",
           })


if __name__ == "__main__":
    main()
