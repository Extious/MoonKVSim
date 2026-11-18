#!/usr/bin/env python3
"""Compose Figures 3 and 4 from one fully accepted five-seed primary campaign."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from simulation_paper_plotting import accepted_attempt, export, style

from moonkvsim.aegiskv.paper_artifacts import file_sha256
from moonkvsim.aegiskv.qwen3_8b_acceptance import load_json_strict

STORE = "vanilla_mooncake_dram"
AEGIS = "aegiskv_unified"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    attempt = accepted_attempt(args.acceptance_manifest, {
        "FIGURE_3_A", "FIGURE_3_B", "FIGURE_3_C", "FIGURE_3_D",
        "FIGURE_4_B", "FIGURE_4_C", "FIGURE_4_D",
    })
    root = Path(__file__).resolve().parents[4]
    artifact_path = root / attempt["artifact"]["path"]
    campaign = load_json_strict(artifact_path)
    source_root = root / attempt["gates"][1]["evidence"].get("source_root", ".")
    workload_binding = campaign["binding"]["workload_binding"]
    workload_path = source_root / workload_binding["declared_path"]
    if file_sha256(workload_path) != workload_binding["sha256"]:
        raise ValueError("primary figure frozen workload binding changed")
    workflow_by_span = {}
    with workload_path.open() as stream:
        for line in stream:
            record = json.loads(line)
            workflow_by_span[record["span_id"]] = record["workflow_id"]
    rows = campaign["seeds"]
    if [r["seed"] for r in rows] != list(range(5)):
        raise ValueError("primary figure requires five ordered seeds")
    style()
    fig = plt.figure(figsize=(7, 5.8), layout="constrained")
    grid = fig.add_gridspec(3, 2, height_ratios=[.8, 1, 1])
    absolute_ax = fig.add_subplot(grid[0, :])
    ecdf_axes = [fig.add_subplot(grid[1, 0]), fig.add_subplot(grid[1, 1])]
    effect_axes = [fig.add_subplot(grid[2, 0]), fig.add_subplot(grid[2, 1])]
    ax = absolute_ax
    for offset, system, label, shade in ((-.18, STORE, "Store-only", "0.75"),
                                         (.18, AEGIS, "AegisKV", "0.25")):
        samples = [[], [], [], []]
        for row in rows:
            wct = row["workflow_wct_ns"][system]
            focus = workflow_by_span[row["causal_contract"]["focus_span_id"]]
            impacted = {focus}
            for outcome in row["causal_contract"]["realized_outcomes_by_system"].values():
                for field in ("active_span_ids", "queued_span_ids"):
                    impacted.update(workflow_by_span[span] for span in outcome[field])
            for i, ids in enumerate((set(wct), {focus}, impacted, set(wct) - {focus})):
                samples[i].append(sum(wct[k] for k in ids)/len(ids)/10**9)
        ax.bar(np.arange(4)+offset, [np.mean(v) for v in samples], width=.36,
               color=shade, label=label)
        for i, values in enumerate(samples):
            ax.scatter(i+offset+np.linspace(-.08, .08, 5), values, s=12,
                       color="black", marker=".")
    ax.set_xticks(range(4), ["All", "Focus", "Impacted union", "Non-focus"])
    ax.set_ylabel("Mean WCT (s)")
    ax.set_title("(a) Absolute completion time", loc="left")
    ax.legend(frameon=False, ncol=2, handlelength=1, columnspacing=.6)
    ax.margins(y=.2)
    for ax, focus_only, title in zip(ecdf_axes, (False, True),
                                      ("(b) All task-runs", "(b) Focus task-runs"), strict=True):
        for system, label, shade, dash in ((STORE, "Store-only", "0.6", "--"),
                                           (AEGIS, "AegisKV", "0.1", "-")):
            values = []
            for row in rows:
                wct = row["workflow_wct_ns"][system]
                ids = ({workflow_by_span[row["causal_contract"]["focus_span_id"]]}
                       if focus_only else set(wct))
                values.extend(wct[k]/10**9 for k in ids)
            values.sort()
            ax.step(np.r_[values[0], values],
                    np.r_[0, np.arange(1, len(values)+1)/len(values)], where="post",
                    color=shade, linestyle=dash, label=label)
        ax.set(xlabel="WCT in failure runs (s)", ylabel="Descriptive ECDF")
        ax.set_title(title, loc="left")
        ax.set_ylim(0, 1.02)
        ax.legend(frameon=False)
    for ax, metric, title, ylabel in (
        (effect_axes[0], "focus_failure_penalty_did", "(c) Failure-focus workflow",
         "Penalty difference (s)"),
        (effect_axes[1], "whole_mean_failure_penalty_did", "(d) Whole workload",
         "Mean penalty difference (s)"),
    ):
        values = [r["seed_level_estimands_ns"][metric]/10**9 for r in rows]
        interval = campaign["inference"]["student_t_95"][metric]
        if interval["eligible"] is not True:
            raise ValueError("primary figure interval is not eligible")
        mean, low, high = (interval[k]/10**9 for k in ("mean", "low", "high"))
        ax.scatter(range(5), values, s=24, facecolors="none", edgecolors="0.2")
        ax.errorbar(5.3, mean, yerr=[[mean-low], [high-mean]], fmt="s", color="black",
                    capsize=4, markersize=4)
        ax.axhline(0, color="0.4", linestyle="--", linewidth=.8)
        ax.set_xticks([0, 1, 2, 3, 4, 5.3], ["0", "1", "2", "3", "4", "Mean"])
        ax.set(xlabel="Shared admission seed", ylabel=ylabel)
        ax.set_title(title, loc="left")
        ax.grid(axis="y", alpha=.2)
        ax.set_xlim(-.5, 6)
    export(fig, args.output_dir / "failure-effects", generator=Path(__file__),
           inputs=[args.acceptance_manifest, artifact_path, workload_path], data={
               "campaign_fingerprint": campaign["fingerprint"],
               "seed_rows": rows, "inference": campaign["inference"],
               "cohorts": ("all 160 workflows, focus, descriptive post-treatment impacted union, "
                           "and the 159-workflow non-focus complement"),
               "ecdf_population": ("800 task-runs per policy; "
                                   "160 distinct tasks repeated over five seeds"),
               "effect": "(Aegis F1 - Aegis F0) - (Store-only F1 - Store-only F0)",
               "sign": "negative failure-penalty differences favor AegisKV",
           })

    fig = plt.figure(figsize=(7, 4.6), layout="constrained")
    grid = fig.add_gridspec(2, 2, height_ratios=[1, 1.1])
    axes = [fig.add_subplot(grid[0, :]), fig.add_subplot(grid[1, 0]),
            fig.add_subplot(grid[1, 1])]
    x = np.arange(10)
    bottom = np.zeros(10)
    recovery = {(r["seed"], r["system"]): r["focus_recovery"][0]
                for r in attempt["gates"][4]["evidence"]["complete_raw_reconstruction"]
                if r["scenario"] == "gpu_failure"}
    for source, label, shade, hatch in (
        ("normal", "Normal HBM", "0.95", "..."),
        ("peer_local", "Peer local", "0.85", "///"),
        ("peer_d2d", "Peer D2D", "0.65", "xxx"),
        ("store", "Store DRAM", "0.4", ""),
        ("recompute", "Recompute", "0.1", ""),
    ):
        values = [recovery[r["seed"], s]["tokens"][source]
                  / recovery[r["seed"], s]["prompt_tokens"]
                  for r in rows for s in (STORE, AEGIS)]
        axes[0].bar(x, values, bottom=bottom, color=shade, hatch=hatch,
                    edgecolor="black", linewidth=.4, label=label)
        bottom += np.asarray(values)
    if not np.allclose(bottom, 1, rtol=0, atol=1e-12):
        raise ValueError("selected recovery token fractions do not sum to one")
    axes[0].set_xticks(x, [f"{r['seed']} {label}" for r in rows for label in ("S", "A")])
    axes[0].set(xlabel="Seed and policy: S = Store-only, A = AegisKV",
                ylabel="Focus prompt fraction", ylim=(0, 1.02))
    axes[0].set_title("(a) Selected recovery sources", loc="left")
    axes[0].legend(frameon=False, ncol=5, loc="lower left", bbox_to_anchor=(0, 1.1),
                    handlelength=1, columnspacing=.7)
    ax = axes[1]
    for r in rows:
        pair = [r["direct_evidence"]["systems"][s] for s in (STORE, AEGIS)]
        xv = [d["source_tokens"]["RECOMPUTE"] / d["prompt_tokens"] * 100 for d in pair]
        yv = [d["recovery_ready_latency_ns"] / 10**9 for d in pair]
        ax.plot(xv, yv, color="0.7", linewidth=.7)
        for i, marker in enumerate(("o", "x")):
            ax.scatter(xv[i], yv[i], marker=marker, color="black", s=22)
        offset = {0: (-13, 6), 4: (5, -8)}.get(r["seed"], (5, 5))
        ax.annotate(str(r["seed"]), (xv[1], yv[1]), xytext=offset,
                    textcoords="offset points")
    ax.set(xlabel="Recomputed prompt (%)", ylabel="Recovery readiness (s)")
    ax.set_title("(b) Recompute and recovery", loc="left")
    ax.margins(x=.25, y=.25)
    ax = axes[2]
    for r in rows:
        pair = [r["direct_evidence"]["systems"][s] for s in (STORE, AEGIS)]
        xv = [d["recovery_ready_latency_ns"] / 10**9 for d in pair]
        yv = [d["failure_to_completion_latency_ns"] / 10**9 for d in pair]
        ax.plot(xv, yv, color="0.7", linewidth=.7)
        for i, (marker, label) in enumerate((("o", "Store-only"), ("x", "AegisKV"))):
            ax.scatter(xv[i], yv[i], marker=marker, color="black", s=22,
                        label=label if r["seed"] == 0 else None)
        offset = {0: (5, -12), 1: (-10, 6), 2: (-8, -12)}.get(r["seed"], (5, 5))
        ax.annotate(str(r["seed"]), (xv[1], yv[1]), xytext=offset,
                    textcoords="offset points")
    ax.set(xlabel="Recovery-ready latency (s)", ylabel="Request completion (s)")
    ax.set_title("(c) Recovery and completion", loc="left")
    ax.legend(frameon=False, loc="best", handlelength=1)
    ax.margins(y=.3)
    export(fig, args.output_dir / "recovery-mechanism", generator=Path(__file__),
           inputs=[args.acceptance_manifest, artifact_path], data={
               "campaign_fingerprint": campaign["fingerprint"], "seed_rows": rows,
               "source_intervals": ("disjoint selected prompt intervals; "
                                    "available copies may overlap"),
               "focus_recovery_transport": list(recovery.values()),
               "scatter_labels": "seed IDs; lines connect matched system observations",
               "latencies": "each run uses its own actual injection as time zero",
               "direct_class_counts": campaign["direct_class_counts"],
               "exclusive_latency_phase_decomposition": False,
           })


if __name__ == "__main__":
    main()
