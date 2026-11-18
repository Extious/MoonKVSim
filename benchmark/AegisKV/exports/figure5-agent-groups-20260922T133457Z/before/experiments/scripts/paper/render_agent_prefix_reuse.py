#!/usr/bin/env python3
"""Render same-model prefix coverage, with non-additive same/other-Agent bars."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "experiments/data/agent-prefix-reuse"
OUT = ROOT / "exports/agent-prefix-reuse"
FIGURE = ROOT / "paper/figures/agent-prefix-reuse.pdf"
INPUT = DATA / "same-model-reuse-scope.csv"


def main():
    global OUT, FIGURE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,help='Stage exports without publishing paper assets')
    args=parser.parse_args()
    if args.output_dir is not None:
        OUT=args.output_dir.resolve()
        FIGURE=OUT/'agent-prefix-reuse.pdf'
    OUT.mkdir(parents=True, exist_ok=True)
    rows = {r["request_class"]: r for r in csv.DictReader(INPUT.open())}
    groups = ["all", "main_later", "subagent_first", "subagent_later"]
    labels = ["All\nrequests", "Main\nfollow-up", "Subagent\nfirst", "Subagent\nfollow-up"]
    fields = ["same_agent_tokens", "raw_cross_overlap_tokens"]
    values = [[100 * int(rows[g][f]) / int(rows[g]["input_tokens"]) for g in groups] for f in fields]
    for row in rows.values():
        assert sum(int(row[f]) for f in ["same_agent_tokens", "cross_agent_only_tokens", "new_tokens"]) == int(row["input_tokens"])
        for field, percent in [("same_agent_tokens", "same_agent_share_pct"), ("raw_cross_overlap_tokens", "raw_cross_overlap_share_pct")]:
            assert abs(100 * int(row[field]) / int(row["input_tokens"]) - float(row[percent])) < 0.000001
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10.5,
        "axes.labelsize": 10.5, "xtick.labelsize": 10.05, "ytick.labelsize": 10.5,
        "pdf.fonttype": 42, "ps.fonttype": 42, "hatch.linewidth": 0.5,
    })
    fig, ax = plt.subplots(figsize=(84.65 / 25.4, 2.85))
    fig.subplots_adjust(left=0.285, right=0.95, bottom=0.205, top=0.80)
    positions = np.arange(len(groups)) * 1.14
    colors = ["#28609A", "#E4A64A"]
    legend = ["Same-agent history", "Other agents"]
    for series, (series_values, color, label) in enumerate(zip(values, colors, legend)):
        y = positions + (-0.23 if series == 0 else 0.23)
        ax.barh(y, series_values, height=0.42, color=color, edgecolor="#273645",
                linewidth=0.4, hatch=None if series == 0 else "///", label=label, zorder=3)
        for yi, value in zip(y, series_values):
            inside = value >= 90
            if value == 0:
                ax.plot(0, yi, marker="|", color="#273645", markersize=5, zorder=4, clip_on=False)
            ax.text(value - 2 if inside else value + 1.8, yi,
                    "0" if value == 0 else f"{value:.1f}",
                    va="center", ha="right" if inside else "left",
                    fontsize=10.05, color="white" if inside else "#202830", zorder=5)
    ax.set_yticks(positions, labels)
    ax.set_ylim(positions[-1] + 0.51, -0.51)
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Input-prefix coverage (%)", labelpad=5)
    ax.tick_params(axis="y", length=0, pad=6)
    ax.tick_params(axis="x", length=3, pad=3)
    ax.grid(axis="x", color="#DBDFE3", linewidth=0.55, zorder=0)
    for name in ["top", "right", "left"]:
        ax.spines[name].set_visible(False)
    ax.spines["bottom"].set_linewidth(0.6)
    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 0.985), ncol=1,
               frameon=False, fontsize=10.5, handlelength=1.7,
               labelspacing=0.35, borderaxespad=0)
    fig.savefig(FIGURE)
    fig.savefig(OUT / "agent-prefix-reuse.png", dpi=240)
    fig.savefig(OUT / "agent-prefix-reuse.svg")
    plt.close(fig)
    manifest = {
        "input": str(INPUT.relative_to(ROOT)),
        "input_sha256": hashlib.sha256(INPUT.read_bytes()).hexdigest(),
        "plot_type": "paired horizontal bars; series overlap and must not be added",
        "groups": groups,
        "series": dict(zip(legend, values)),
        "width_mm": 84.65,
        "nominal_min_font_pt": 10.05,
        "omitted_detail": "Main first requests have zero in both series; retained in All requests and CSV.",
        "pdf": str(FIGURE.relative_to(ROOT)),
        "pdf_sha256": hashlib.sha256(FIGURE.read_bytes()).hexdigest(),
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
