#!/usr/bin/env python3
"""Show every primary fault target, with matching identities across policies."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np
from matplotlib.ticker import MaxNLocator
from plot_profile_campaign import (
    COLORS,
    LABELS,
    LOADS,
    MARKERS,
    MODELS,
    POLICIES,
    export,
    plt,
    save_json,
    setup,
    sha,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    root = parser.parse_args().campaign.resolve()
    source = root / "endpoints"
    provenance = json.loads((source / "PROVENANCE.json").read_text())
    assert provenance["status"] == "PASS" and provenance["fault_rows"] == 150
    for name, expected in provenance["output_sha256"].items():
        assert sha(source / name) == expected
    with (source / "per-identity.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    index = {
        (r["model"], float(r["nominal_load"]), r["policy"], int(r["fault_index"])): r for r in rows
    }
    assert len(index) == 150
    out = source / "figures"
    out.mkdir(exist_ok=True)
    setup()
    fig, axes = plt.subplots(2, 3, figsize=(178 / 25.4, 105 / 25.4), sharey="row")
    fig.subplots_adjust(left=0.10, right=0.995, bottom=0.155, top=0.87, wspace=0.12, hspace=0.22)
    for row, model in enumerate(MODELS):
        all_values = [
            int(index[model, load, policy, i]["target_delta_wct_ns"]) / 1e9
            for load in LOADS
            for policy in POLICIES
            for i in range(5)
        ]
        low, high = min(0, min(all_values)), max(all_values)
        ticks = MaxNLocator(nbins=4, integer=True, steps=[1, 2, 5, 10]).tick_values(low, high)
        span = ticks[-1] - ticks[0]
        for column, load in enumerate(LOADS):
            ax = axes[row, column]
            for p, policy in enumerate(POLICIES):
                values = [
                    int(index[model, load, policy, i]["target_delta_wct_ns"]) / 1e9
                    for i in range(5)
                ]
                ax.plot(
                    np.arange(5) + (p - 2) * 0.13,
                    values,
                    color=COLORS[p],
                    marker=MARKERS[p],
                    linestyle="none",
                    markersize=4.0,
                    markerfacecolor="none",
                    markeredgewidth=0.9,
                    label=LABELS[p],
                )
            labels = [
                ("S" if index[model, load, "none", i]["target_dag_position"] == "sink" else "N")
                + str(i + 1)
                for i in range(5)
            ]
            ax.set_xticks(range(5), labels)
            ax.set_xlim(-0.55, 4.55)
            ax.set_yticks(ticks)
            ax.set_ylim(ticks[0] - 0.04 * span, ticks[-1] + 0.04 * span)
            ax.axhline(0, color="#555555", linewidth=0.6, zorder=0)
            ax.grid(axis="y", alpha=0.18)
            if row == 0:
                ax.set_title(rf"Nominal $\rho={load:g}$", pad=5)
            if column == 0:
                ax.set_ylabel(f"{model}\nTarget ΔWCT (s)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.54, 1.005),
        ncol=5,
        frameon=False,
        columnspacing=1.0,
        handletextpad=0.35,
        handlelength=1.0,
    )
    fig.text(0.54, 0.04, "Fixed fault identity: S = sink, N = non-sink", ha="center")
    export(fig, out, "primary-target-wct")
    save_json(
        out / "PROVENANCE.json",
        dict(
            input_provenance_sha256=sha(source / "PROVENANCE.json"),
            data_sha256=sha(source / "per-identity.csv"),
            plot_sha256=sha(Path(__file__)),
            style_source_sha256=sha(Path(__file__).with_name("plot_profile_campaign.py")),
            runtime_versions=provenance["runtime_versions"],
            canvas_mm=[178, 105],
            marker_rows=150,
            y_unit="target-workflow failure minus own-policy healthy WCT, seconds",
            x_unit="same five fixed identities, explicitly classified from the saved DAG",
            intervals="none; no repeated trials or population confidence interval",
            y_scales="shared within each model row; inspect limits across model rows",
            output_sha256={p.name: sha(p) for p in out.glob("primary-target-wct.*")},
        ),
    )


if __name__ == "__main__":
    main()
