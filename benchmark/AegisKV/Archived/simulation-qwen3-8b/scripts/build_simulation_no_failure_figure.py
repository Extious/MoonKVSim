#!/usr/bin/env python3
"""Compose accepted Figure 2 panels at their final manuscript size."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from simulation_paper_plotting import accepted_attempt

from moonkvsim.aegiskv.paper_artifacts import file_sha256
from moonkvsim.common.hash import sha256_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--acceptance-manifest", type=Path, required=True)
    parser.add_argument("--output-stem", type=Path, required=True)
    args = parser.parse_args()
    helper = Path(__file__).resolve().parents[1] / (
        "results/figures/generate_qwen3_8b_no_failure_overhead.py"
    )
    spec = importlib.util.spec_from_file_location("figure2_contract", helper)
    assert spec is not None and spec.loader is not None
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    artifact = contract._load(args.artifact)
    accepted_attempt(args.acceptance_manifest, set(contract.PANEL_IDS))
    contract._load_acceptance(args.acceptance_manifest,
                             artifact_path=args.artifact, artifact=artifact)
    rows = contract._seed_rows(artifact)
    cells = contract._cells(artifact)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 10,
        "axes.labelsize": 10, "xtick.labelsize": 10, "ytick.labelsize": 10,
        "legend.fontsize": 10, "pdf.fonttype": 42, "svg.fonttype": "none",
        "axes.spines.top": False, "axes.spines.right": False,
    })
    fig = plt.figure(figsize=(7, 5.7), layout="constrained")
    grid = fig.add_gridspec(3, 2, height_ratios=[1, 1, 1])
    axes = [fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1]),
            fig.add_subplot(grid[1, :]), fig.add_subplot(grid[2, :])]
    chart: dict[str, object] = {"seed_ids": list(range(5)), "panels": {}}
    panels = chart["panels"]
    assert isinstance(panels, dict)

    def paired_points(ax, values, labels):
        stats = []
        for index, sample in enumerate(values):
            mean, low, high = contract._student_t_95(sample)
            ax.scatter(index + np.linspace(-.16, .16, 5), sample,
                       marker="o", s=22, facecolors="none", edgecolors="0.35")
            ax.errorbar(index + .26, mean, yerr=[[mean-low], [high-mean]],
                        color="black", fmt="s", markersize=4, capsize=3)
            stats.append({"label": labels[index], "seed_values": sample,
                          "mean": mean, "ci95": [low, high]})
        ax.axhline(0, color="0.35", linestyle="--", linewidth=.8)
        ax.set_xticks(range(len(labels)), labels)
        ax.set_xlim(-.5, len(labels)-.45)
        ax.grid(axis="y", alpha=.2)
        return stats

    ax = axes[0]
    panels["FIGURE_2_A"] = paired_points(ax, [
        [contract._mean_delta_s(row, cohort) for row in rows]
        for cohort in (None, "bootstrap_initial_admission", "steady_state")
    ], ["All", "Initial", "Later"])
    ax.set_title("(a) Paired completion-time effect", loc="left")
    ax.set_ylabel("WCT difference (s)")
    ax.set_xlabel("Workflow admission cohort")

    ax = axes[1]
    panels["FIGURE_2_B"] = paired_points(ax, [
        [float(row[field][metric])/10_000 for row in rows]
        for field, metric in (("makespan", "aegiskv_overhead_ppm_floor"),
                              ("goodput", "aegiskv_delta_ppm_floor"))
    ], ["Makespan", "Goodput"])
    ax.set_title("(b) Whole-run effect", loc="left")
    ax.set_ylabel("Relative change (%)")
    ax.set_xlabel("AegisKV relative to Store-only")

    ax = axes[2]
    traffic = {}
    x = np.arange(5)
    tier_rows, raw_hashes = _protection_tiers(args.artifact.parent, cells)
    width = .25
    for index, (key, label, shade) in enumerate((
        (f"{contract.MOONCAKE}:Store", "Store-only: Store", "0.8"),
        (f"{contract.AEGISKV}:Peer", "AegisKV: Peer", "0.45"),
        (f"{contract.AEGISKV}:Store", "AegisKV: Store", "0.15"),
    )):
        offset = (index - 1) * width
        submitted = [row[key]["submitted_bytes"]/1024**3 for row in tier_rows]
        warmup = [row[key]["warmup_bytes"]/1024**3 for row in tier_rows]
        aborted = [row[key]["aborted_bytes"]/1024**3 for row in tier_rows]
        warmup_aborted = [row[key]["warmup_aborted_bytes"]/1024**3 for row in tier_rows]
        transferred = [row[key]["transferred_bytes"]/1024**3 for row in tier_rows]
        ax.bar(x+offset, submitted, width=width, color=shade, label=label)
        ax.bar(x+offset, warmup, width=width, color="none", edgecolor="black",
               linewidth=.5, hatch="////")
        ax.scatter(x+offset, aborted, marker="x", s=15, color="black")
        for xpos, volume in zip(x+offset, aborted, strict=True):
            if volume > 0:
                ax.annotate(f"{volume:.2f}", (xpos, volume), xytext=(0, 8),
                            textcoords="offset points", ha="center", va="bottom",
                            bbox={"facecolor": "white", "edgecolor": "none", "pad": .7})
        traffic[key] = {"submitted_gib": submitted, "warmup_gib": warmup,
                        "aborted_gib": aborted, "warmup_aborted_gib": warmup_aborted,
                        "later_aborted_gib": [a-w for a, w in zip(
                            aborted, warmup_aborted, strict=True)],
                        "transferred_gib": transferred}
    panels["FIGURE_2_C"] = traffic
    ax.set_title("(c) Protection bytes per run", loc="left")
    ax.set_ylabel("Protection traffic (GiB)")
    ax.set_xlabel("Shared admission seed")
    ax.set_xticks(x)
    ax.set_ylim(0, max(max(row["submitted_gib"]) for row in traffic.values()) * 1.38)
    ax.legend(frameon=False, loc="upper left", ncol=3,
              columnspacing=.7, handlelength=1.1)

    ax = axes[3]
    delta_traffic = [
        (cell["systems"][contract.AEGISKV]["protection"]["submitted_bytes"]
         - cell["systems"][contract.MOONCAKE]["protection"]["submitted_bytes"])
        / 1024**3 / (cell["systems"][contract.MOONCAKE]["makespan_ns"] / 1e9)
        for cell in cells
    ]
    delta_wct = [contract._mean_delta_s(row, "steady_state") for row in rows]
    ax.scatter(delta_traffic, delta_wct, s=22, color="black")
    for seed, (xv, yv) in enumerate(zip(delta_traffic, delta_wct, strict=True)):
        ax.annotate(str(seed), (xv, yv), xytext=(4, 4), textcoords="offset points")
    ax.axhline(0, linestyle="--", color="0.35", linewidth=.8)
    ax.set_title("(d) Later-cohort cost and effect", loc="left")
    ax.set_xlabel("Incremental protection rate (GiB/s; Store-only makespan denominator)")
    ax.set_ylabel("WCT difference (s)")
    ax.margins(x=.2, y=.2)
    ax.grid(alpha=.2)
    panels["FIGURE_2_D"] = {"incremental_protection_rate_gib_s": delta_traffic,
                            "later_cohort_wct_difference_s": delta_wct,
                            "regression_or_causal_cost_claim": False}
    args.output_stem.parent.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for suffix in ("pdf", "svg", "png"):
        path = args.output_stem.with_suffix("." + suffix)
        fig.savefig(path, dpi=200, facecolor="white")
        outputs[suffix] = file_sha256(path)
    plt.close(fig)
    body = {"schema": "moonkvsim.simulation-paper-figure2.v1", "chart_data": chart,
            "artifact_sha256": file_sha256(args.artifact),
            "acceptance_sha256": file_sha256(args.acceptance_manifest),
            "generator_sha256": file_sha256(Path(__file__)),
            "contract_helper_sha256": file_sha256(helper), "output_sha256": outputs,
            "raw_artifact_sha256": raw_hashes,
            "effect_sign": "AegisKV minus Store-only; lower WCT is better",
            "interval": "two-sided Student t, df=4; five admission-seed estimates",
            "traffic_marks": ("hatching: warmup; crosses: aborted submitted bytes; "
                              "nonzero aborted GiB explicitly labeled"),
            "physical_execution": False, "submission_ready": False}
    args.output_stem.with_suffix(".json").write_text(
        json.dumps({**body, "fingerprint": sha256_json(body)}, indent=2)+"\n")
    print(args.output_stem)


def _protection_tiers(directory: Path, cells) -> tuple[list[dict], dict[str, str]]:
    """Reconstruct disjoint traffic causes and the declared transfer-ready phases."""
    rows, hashes = [], {}
    for cell in cells:
        row = {}
        for system_id, system in cell["systems"].items():
            binding = system["raw_artifact"]
            path = (directory / binding["path"]).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError("raw traffic evidence escapes artifact directory")
            if file_sha256(path) != binding["sha256"]:
                raise ValueError("raw traffic evidence changed")
            hashes[str(path)] = binding["sha256"]
            raw = json.loads(path.read_text())
            totals = {name: 0 for name in ("submitted_bytes", "aborted_bytes", "transferred_bytes")}
            warmup_total = 0
            for tier in ("Peer", "Store"):
                row[f"{system_id}:{tier}"] = {
                    **totals, "warmup_bytes": 0, "warmup_aborted_bytes": 0}
            for transfer in raw["representative"]["transfers"]:
                cause = transfer["cause"]
                if cause not in system["protection"]["protection_causes"]:
                    continue
                if transfer["status"] not in {"COMMITTED", "ABORTED"}:
                    raise ValueError("nonterminal protection transfer")
                tier = "Peer" if "PEER_HBM" in cause else "Store"
                bucket = row[f"{system_id}:{tier}"]
                for field, raw_field in (("submitted_bytes", "bytes"),
                                         ("aborted_bytes", "aborted_bytes"),
                                         ("transferred_bytes", "transferred_bytes")):
                    value = transfer[raw_field]
                    if type(value) is not int or value < 0:
                        raise ValueError("invalid protection byte count")
                    bucket[field] += value
                    totals[field] += value
                if transfer["ready_ns"] < system["warmup"]["warmup_end_ns"]:
                    bucket["warmup_bytes"] += transfer["bytes"]
                    bucket["warmup_aborted_bytes"] += transfer["aborted_bytes"]
                    warmup_total += transfer["bytes"]
            if any(value != system["protection"][key] for key, value in totals.items()):
                raise ValueError("tier traffic does not reconstruct accepted total")
            if warmup_total != system["protection"]["by_time_phase"]["bootstrap_warmup"][
                "submitted_bytes"
            ]:
                raise ValueError("tier warmup does not reconstruct accepted phase")
            del raw
        rows.append(row)
    return rows, hashes


if __name__ == "__main__":
    main()
