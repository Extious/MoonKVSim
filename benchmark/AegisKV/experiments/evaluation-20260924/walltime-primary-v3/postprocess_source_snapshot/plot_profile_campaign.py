#!/usr/bin/env python3
"""Plot only a complete, independently audited primary campaign.

Intervals show the range of five predeclared failure scenarios, never a CI.
Every figure retains its numeric table and source hashes. No paper is edited.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

POLICIES = ("none", "all_dram", "dram", "static_hbm", "aegiskv")
LABELS = ("Restart", "All-DRAM", "DRAM", "Static-HBM", "AegisKV")
COLORS = ("#777777", "#b88a24", "#3b78a4", "#9270a9", "#b7474b")
MARKERS = ("x", "^", "s", "D", "o")
MODELS = ("Qwen3-8B", "Qwen3-32B")
LOADS = (0.3, 0.65, 0.9)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def setup():
    font = subprocess.check_output(["kpsewhich", "LinLibertine_R.otf"], text=True).strip()
    font_manager.fontManager.addfont(font)
    family = font_manager.FontProperties(fname=font).get_name()
    plt.rcParams.update(
        {
            "font.family": family,
            "font.size": 10.3,
            "axes.labelsize": 10.3,
            "xtick.labelsize": 10.3,
            "ytick.labelsize": 10.3,
            "legend.fontsize": 10.3,
            "axes.titlesize": 10.3,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.65,
            "lines.linewidth": 1.15,
            "svg.fonttype": "none",
            "savefig.facecolor": "white",
        }
    )


def export(fig, out, name):
    for extension in ("pdf", "png", "svg"):
        fig.savefig(out / f"{name}.{extension}", dpi=300)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    args = parser.parse_args()
    root = args.campaign
    audit = json.loads((root / "AUDIT.json").read_text())
    if audit.get("status") != "PASS":
        raise ValueError("figures require an independently audited complete campaign")
    with (root / "run-metrics.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 180:
        raise ValueError("primary plot expects the frozen 180-run matrix")
    index = {row["run_id"]: row for row in rows}
    out = root / "figures"
    out.mkdir(exist_ok=True)
    setup()
    data = []

    def group(model, load, policy):
        result = [index[f"{model}-load{load}-{policy}-F1-{i}"] for i in range(5)]
        assert all(row["run_integrity_verified"] == "True" for row in result)
        return result

    # Workflow-level failure effect, preserving negative scheduling effects.
    fig, axes = plt.subplots(1, 2, figsize=(178 / 25.4, 78 / 25.4), sharey=True)
    fig.subplots_adjust(left=0.10, right=0.99, bottom=0.21, top=0.85, wspace=0.12)
    for column, model in enumerate(MODELS):
        ax = axes[column]
        for p, policy in enumerate(POLICIES):
            values = [
                [float(r["delta_wct_mean_s"]) for r in group(model, load, policy)] for load in LOADS
            ]
            centers = [mean(v) for v in values]
            x = np.arange(3) + (p - 2) * 0.13
            ax.errorbar(
                x,
                centers,
                yerr=[
                    [m - min(v) for m, v in zip(centers, values, strict=True)],
                    [max(v) - m for m, v in zip(centers, values, strict=True)],
                ],
                color=COLORS[p],
                marker=MARKERS[p],
                linestyle="none",
                markersize=4.4,
                capsize=2,
                elinewidth=0.8,
                label=LABELS[p],
            )
            for load, value in zip(LOADS, values, strict=True):
                for scenario, number in enumerate(value):
                    data.append(
                        dict(
                            figure="core-workflow-delay",
                            model=model,
                            load=load,
                            policy=policy,
                            fault_index=scenario,
                            unit="s",
                            metric="mean_workflow_F1_minus_own_F0",
                            value=number,
                            source_run=f"{model}-load{load}-{policy}-F1-{scenario}",
                        )
                    )
        ax.axhline(0, color="#333333", linewidth=0.7, zorder=0)
        ax.set_xticks(range(3), [str(x) for x in LOADS])
        ax.set_xlabel(f"({chr(97 + column)}) {model}; nominal load")
        ax.set_xlim(-0.5, 2.5)
        ax.grid(axis="y", alpha=0.18)
    axes[0].set_ylabel("Mean workflow delay (s)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.52, 1.01),
        ncol=5,
        frameon=False,
        columnspacing=1.1,
        handletextpad=0.35,
    )
    export(fig, out, "core-workflow-delay")

    # Same-ID paired DRAM minus AegisKV: isolates incremental HBM placement.
    fig, axes = plt.subplots(1, 2, figsize=(178 / 25.4, 62 / 25.4), sharey=True)
    fig.subplots_adjust(left=0.10, right=0.99, bottom=0.28, top=0.94, wspace=0.12)
    for column, model in enumerate(MODELS):
        ax = axes[column]
        for i, load in enumerate(LOADS):
            dram, aegis = group(model, load, "dram"), group(model, load, "aegiskv")
            values = [
                1000 * (float(d["fault_workflow_wct_s"]) - float(a["fault_workflow_wct_s"]))
                for d, a in zip(dram, aegis, strict=True)
            ]
            ax.scatter(
                i + np.linspace(-0.10, 0.10, 5),
                values,
                s=23,
                marker="o",
                facecolors="none",
                edgecolors=COLORS[4],
                linewidths=0.9,
            )
            ax.plot([i - 0.15, i + 0.15], [mean(values)] * 2, color="#222222", linewidth=1.3)
            for scenario, value in enumerate(values):
                data.append(
                    dict(
                        figure="core-hbm-increment",
                        model=model,
                        load=load,
                        policy="dram-minus-aegiskv",
                        fault_index=scenario,
                        unit="ms",
                        metric="target_workflow_paired_WCT_benefit",
                        value=value,
                        source_run=f"{model}-load{load}-{{dram,aegiskv}}-F1-{scenario}",
                    )
                )
        ax.axhline(0, color="#333333", linewidth=0.7, zorder=0)
        ax.set_xticks(range(3), [str(x) for x in LOADS])
        ax.set_xlabel(f"({chr(97 + column)}) {model}; nominal load")
        ax.set_xlim(-0.4, 2.4)
        ax.grid(axis="y", alpha=0.18)
    axes[0].set_ylabel("HBM WCT benefit (ms)")
    export(fig, out, "core-hbm-increment")

    # Values remain descriptive; do not treat the six condition means as trials.
    headline = []
    for model in MODELS:
        for load in LOADS:
            cell = dict(model=model, nominal_load=load, policies={})
            for policy in POLICIES:
                runs = group(model, load, policy)
                healthy = index[f"{model}-load{load}-{policy}-F0"]
                cell["policies"][policy] = dict(
                    healthy_mean_wct_s=float(healthy["wct_mean_s"]),
                    failure_mean_wct_s=mean(float(r["wct_mean_s"]) for r in runs),
                    failure_mean_delta_wct_s=mean(float(r["delta_wct_mean_s"]) for r in runs),
                    target_mean_wct_s=mean(float(r["fault_workflow_wct_s"]) for r in runs),
                    target_mean_delta_wct_s=mean(float(r["fault_workflow_delta_s"]) for r in runs),
                    recovery_service_mean_s=mean(float(r["recovery_service_mean_s"]) for r in runs),
                    recovery_queue_mean_s=mean(float(r["recovery_queue_mean_s"]) for r in runs),
                    healthy_checkpoint_bytes=float(healthy["traffic_checkpoint_bytes"]),
                    healthy_hot_bytes=float(healthy["traffic_hot_bytes"]),
                )
            headline.append(cell)
    save_json(out / "RESULTS.json", headline)
    with (out / "figure-data.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)
    save_json(
        out / "PROVENANCE.json",
        dict(
            source_sha256={
                str(p.resolve()): sha(p)
                for p in [root / "AUDIT.json", root / "run-metrics.csv", Path(__file__)]
            },
            final_width_mm=178,
            font_pt=10.3,
            numeric_points=len(data),
            interval="min-max of five fixed failure identities; not confidence intervals",
            render_review="pending actual exported-image and manuscript inspection",
            outputs_sha256={
                p.name: sha(p)
                for p in out.iterdir()
                if p.suffix in {".pdf", ".png", ".svg", ".csv"}
            },
        ),
    )


if __name__ == "__main__":
    main()
