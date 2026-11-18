#!/usr/bin/env python3
"""Render submission figures from frozen legacy AegisKV WCT artifacts.

This script performs paper-only analysis and plotting.  It never launches
SGLSim, a serving runtime, CUDA, or a scheduler job.  The inputs predate the
current source-owned independent-tier design and therefore must remain
explicitly labelled as legacy evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


PAPER_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path(
    "/home/comp/zhanzhao/sglsim/AegisKV/Archived/"
    "2026-08-06-pre-kvcache-centric"
)
PRESENTATION = ARCHIVE / "presentations/presentation"
POLICY_CSV = (
    PRESENTATION
    / "figures/data/measured/fig_backup_policy_comparison_paired_wct.csv"
)
PROJECTION_CSV = (
    PRESENTATION
    / "figures/data/projected/"
    "fig_weka_subagent_policy_wct_cdf_projected_128k_dp64.csv"
)
PROJECTION_ASSUMPTIONS = PROJECTION_CSV.with_suffix(".assumptions.json")
HEAVY_DIR = (
    ARCHIVE
    / "experiments/demo/results/"
    "fast_logical_pp_20w_16k_c8_c16_heavyfail_v1"
)
HEAVY_FILES = {
    (8, "aegiskv"): HEAVY_DIR / "c8-heavyfail-aegiskv-v2.json",
    (8, "no_backup"): HEAVY_DIR / "c8-heavyfail-no_backup-v2.json",
    (16, "aegiskv"): HEAVY_DIR / "c16-heavyfail-aegiskv-v2.json",
    (16, "no_backup"): HEAVY_DIR / "c16-heavyfail-no_backup-v2.json",
}

FIGURE_DIR = PAPER_ROOT / "figures"
MANIFEST = FIGURE_DIR / "legacy-wct-submission.manifest.json"

COLORS = {
    "no_backup": "#666666",
    "host_only": "#0072B2",
    "gpu_replica": "#E69F00",
    "aegiskv": "#009E73",
}
LABELS = {
    "no_backup": "No backup",
    "host_only": "HostBackup",
    "gpu_replica": "GPUReplica",
    "aegiskv": "Legacy AegisKV",
}
LINESTYLES = {
    "no_backup": ":",
    "host_only": "-",
    "gpu_replica": "--",
    "aegiskv": "-.",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_package() -> int:
    if not MANIFEST.is_file():
        raise SystemExit(f"missing legacy WCT manifest: {MANIFEST}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema") != "aegiskv_legacy_wct_paper_relayout_v1":
        raise SystemExit("unexpected legacy WCT manifest schema")
    for key in (
        "new_experiment",
        "sglsim_executed",
        "physical_runtime_executed",
        "current_design_validation",
    ):
        if manifest.get(key) is not False:
            raise SystemExit(f"legacy WCT evidence boundary changed: {key}")

    checked = 0
    source_status = []
    for item in manifest.get("sources", []):
        path = Path(item["path"])
        if not path.is_file():
            status = "missing"
        elif sha256(path) != item["sha256"]:
            status = "hash_mismatch"
        else:
            status = "verified"
        source_status.append({"path": str(path), "status": status})
    for item in manifest.get("outputs", {}).values():
        for kind in ("pdf", "png"):
            path = PAPER_ROOT / item[kind]
            if not path.is_file() or sha256(path) != item[f"{kind}_sha256"]:
                raise SystemExit(f"legacy WCT output hash mismatch: {path}")
            checked += 1
    if checked != 6:
        raise SystemExit(f"unexpected legacy WCT output cardinality: {checked}")
    print(
        json.dumps(
            {
                "status": "PASS",
                "operation": "verify_legacy_wct_package",
                "checked_local_outputs": checked,
                "external_sources": source_status,
                "regeneration_ready": all(
                    item["status"] == "verified" for item in source_status
                ),
                "manifest": str(MANIFEST),
            },
            indent=2,
        )
    )
    return 0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def ecdf(values: list[float]) -> tuple[np.ndarray, np.ndarray]:
    xs = np.sort(np.asarray(values, dtype=float))
    ys = np.arange(1, len(xs) + 1, dtype=float) / len(xs)
    return xs, ys


def percentile(values: list[float], q: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=float), q))


def setup_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 10.5,
            "axes.labelsize": 10,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "figure.dpi": 300,
        }
    )


def save(fig: plt.Figure, stem: str) -> dict[str, object]:
    pdf = FIGURE_DIR / f"{stem}.pdf"
    png = FIGURE_DIR / f"{stem}.png"
    fig.savefig(pdf, bbox_inches="tight", pad_inches=0.04)
    fig.savefig(png, dpi=300, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    return {
        "pdf": str(pdf.relative_to(PAPER_ROOT)),
        "pdf_sha256": sha256(pdf),
        "png": str(png.relative_to(PAPER_ROOT)),
        "png_sha256": sha256(png),
    }


def policy_figure() -> tuple[dict[str, object], dict[str, object]]:
    rows = read_csv(POLICY_CSV)
    policies = ("host_only", "gpu_replica", "aegiskv")
    by_policy = {
        policy: [row for row in rows if row["policy"] == policy]
        for policy in policies
    }
    baseline = [float(row["no_backup_wct_s"]) for row in by_policy["aegiskv"]]
    samples = {"no_backup": baseline}
    deltas: dict[str, list[float]] = {}
    for policy in policies:
        samples[policy] = [float(row["policy_wct_s"]) for row in by_policy[policy]]
        deltas[policy] = [float(row["delta_s"]) for row in by_policy[policy]]

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.05), gridspec_kw={"wspace": 0.30})
    ax = axes[0]
    for policy in ("no_backup", *policies):
        xs, ys = ecdf(samples[policy])
        ax.step(
            xs,
            ys,
            where="post",
            color=COLORS[policy],
            linestyle=LINESTYLES[policy],
            linewidth=2.0,
            label=LABELS[policy],
        )
    ax.set_title("(a) Workflow completion time")
    ax.set_xlabel("WCT (s)")
    ax.set_ylabel("Empirical CDF")
    ax.set_ylim(0, 1.02)
    ax.grid(True, color="#dddddd", linewidth=0.6)
    ax.legend(frameon=False, loc="lower right")

    ax = axes[1]
    positions = np.arange(1, 4)
    box = ax.boxplot(
        [deltas[p] for p in policies],
        positions=positions,
        widths=0.55,
        patch_artist=True,
        showfliers=False,
        medianprops={"color": "#222222", "linewidth": 1.5},
    )
    for patch, policy in zip(box["boxes"], policies):
        patch.set_facecolor(COLORS[policy])
        patch.set_alpha(0.30)
        patch.set_edgecolor(COLORS[policy])
    for index, policy in enumerate(policies, start=1):
        values = deltas[policy]
        jitter = np.linspace(-0.14, 0.14, len(values))
        ax.scatter(
            index + jitter,
            values,
            s=13,
            color=COLORS[policy],
            alpha=0.85,
            zorder=3,
        )
        mean = float(np.mean(values))
        wins = sum(value < 0 for value in values)
        ax.text(
            index,
            44,
            f"mean {mean:+.1f}s\n{wins}/24 wins",
            ha="center",
            va="top",
            fontsize=10,
        )
    ax.axhline(0, color="#222222", linewidth=1.0)
    ax.set_ylim(-42, 47)
    ax.set_xticks(positions, ["Host", "Peer GPU", "AegisKV"])
    ax.set_ylabel("Policy - No backup WCT (s)")
    ax.set_title("(b) Paired workflow delta")
    ax.grid(axis="y", color="#dddddd", linewidth=0.6)

    fig.suptitle(
        "Legacy DP8 prototype: 24 workflows, three soft failures, fixed alpha=0.30",
        fontsize=10.5,
        fontweight="bold",
        y=1.01,
    )
    fig.subplots_adjust(top=0.82, bottom=0.18, left=0.09, right=0.99)
    output = save(fig, "legacy-wct-policy-comparison")
    metrics = {
        policy: {
            "workflow_count": len(samples[policy]),
            "mean_wct_s": float(np.mean(samples[policy])),
            "p50_wct_s": percentile(samples[policy], 0.50),
            "p90_wct_s": percentile(samples[policy], 0.90),
            "p99_wct_s": percentile(samples[policy], 0.99),
            **(
                {}
                if policy == "no_backup"
                else {
                    "paired_mean_delta_s": float(np.mean(deltas[policy])),
                    "paired_wins": sum(value < 0 for value in deltas[policy]),
                }
            ),
        }
        for policy in ("no_backup", *policies)
    }
    return output, metrics


def projection_figure() -> tuple[dict[str, object], dict[str, object]]:
    rows = read_csv(PROJECTION_CSV)
    summaries = {
        row["policy_suffix"]: row
        for row in rows
        if row["workflow_id"] == "__summary__"
    }
    samples = {
        policy: [
            float(row["projected_wct_s"])
            for row in rows
            if row["policy_suffix"] == policy
            and row["workflow_id"] != "__summary__"
        ]
        for policy in ("aegiskv", "no_backup")
    }

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.85), gridspec_kw={"wspace": 0.32})
    ax = axes[0]
    for policy in ("aegiskv", "no_backup"):
        xs, ys = ecdf(samples[policy])
        ax.plot(xs, ys, color=COLORS[policy], linewidth=2.1, label=LABELS[policy])
    ax.set_title("(a) Projected WCT")
    ax.set_xlabel("Projected WCT (s)")
    ax.set_ylabel("CDF")
    ax.set_ylim(0, 1.02)
    ax.grid(True, color="#dddddd", linewidth=0.6)
    ax.legend(frameon=False, loc="lower right")

    ax = axes[1]
    keys = (
        ("l1_reuse_tokens", "Legacy L1 reuse", "#0072B2"),
        ("l2_reuse_tokens", "Legacy L2 reuse", "#56B4E9"),
        ("recompute_tokens", "Recompute", "#777777"),
    )
    positions = np.arange(2)
    bottoms = np.zeros(2)
    for key, label, color in keys:
        values = []
        for policy in ("aegiskv", "no_backup"):
            count = float(summaries[policy][key])
            total = float(summaries[policy]["retry_tokens_total"])
            values.append(100.0 * count / total)
        ax.bar(positions, values, bottom=bottoms, color=color, width=0.58, label=label)
        for position, bottom, value in zip(positions, bottoms, values):
            if value >= 12:
                ax.text(
                    position,
                    bottom + value / 2,
                    f"{value:.1f}%",
                    color="white",
                    fontweight="bold",
                    ha="center",
                    va="center",
                    fontsize=10,
                )
        bottoms += np.asarray(values)
    ax.set_title("(b) Retry-token source")
    ax.set_ylabel("Fraction (%)")
    ax.set_xticks(positions, ["AegisKV", "No backup"])
    ax.set_ylim(0, 112)
    ax.grid(axis="y", color="#dddddd", linewidth=0.6)
    ax.legend(frameon=False, loc="upper center", ncol=1)

    fig.suptitle(
        "Legacy model projection: Qwen3-8B, DP64, <=128K context, 160 workflows",
        fontsize=10.5,
        fontweight="bold",
        y=1.01,
    )
    fig.subplots_adjust(top=0.80, bottom=0.20, left=0.09, right=0.99)
    output = save(fig, "legacy-wct-dp64-projection")
    metrics = {
        policy: {
            key: (
                int(value)
                if key
                in {
                    "workflow_count",
                    "retry_count",
                    "l1_reuse_tokens",
                    "l2_reuse_tokens",
                    "recompute_tokens",
                    "retry_tokens_total",
                }
                else float(value)
            )
            for key, value in summaries[policy].items()
            if key
            in {
                "workflow_count",
                "mean_wct_s",
                "p50_wct_s",
                "p90_wct_s",
                "p99_wct_s",
                "max_wct_s",
                "retry_count",
                "l1_reuse_tokens",
                "l2_reuse_tokens",
                "recompute_tokens",
                "retry_tokens_total",
            }
        }
        for policy in ("aegiskv", "no_backup")
    }
    return output, metrics


def load_heavy(path: Path) -> tuple[list[float], dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = [float(row["wct_s"]) for row in payload["workflows"]]
    metadata = {
        "workflow_count": len(values),
        "workflow_concurrency": int(payload["workflow_concurrency"]),
        "failure_count_injected": int(payload["failure_count_injected"]),
        "simulation_time_mode": payload["simulation_time_mode"],
        "evidence_tier": payload["evidence_tier"],
    }
    return values, metadata


def heavy_figure() -> tuple[dict[str, object], dict[str, object]]:
    samples: dict[tuple[int, str], list[float]] = {}
    metadata: dict[str, object] = {}
    for key, path in HEAVY_FILES.items():
        values, item = load_heavy(path)
        samples[key] = values
        metadata[f"c{key[0]}_{key[1]}"] = item

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.65), gridspec_kw={"wspace": 0.28})
    metrics: dict[str, object] = {}
    for ax, concurrency in zip(axes, (8, 16)):
        for policy in ("aegiskv", "no_backup"):
            xs, ys = ecdf(samples[(concurrency, policy)])
            ax.step(
                xs,
                ys,
                where="post",
                color=COLORS[policy],
                linewidth=2.0,
                label=LABELS[policy],
            )
        mean_a = float(np.mean(samples[(concurrency, "aegiskv")]))
        mean_n = float(np.mean(samples[(concurrency, "no_backup")]))
        reduction = 100.0 * (mean_n - mean_a) / mean_n
        metrics[f"c{concurrency}"] = {
            "workflow_count": len(samples[(concurrency, "aegiskv")]),
            "aegiskv_mean_wct_s": mean_a,
            "no_backup_mean_wct_s": mean_n,
            "mean_wct_reduction_percent": reduction,
        }
        ax.text(
            0.04,
            0.80,
            f"mean reduction {reduction:.1f}%",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10,
            fontweight="bold",
        )
        ax.set_title(f"Offered concurrency {concurrency}")
        ax.set_xlabel("WCT (s)")
        ax.set_ylim(0, 1.02)
        ax.grid(True, color="#dddddd", linewidth=0.6)
    axes[0].set_ylabel("Empirical CDF")
    axes[0].legend(frameon=False, loc="lower right")
    fig.suptitle(
        "Legacy heavy-failure logical-PP stress smoke: Qwen3-32B, 20 workflows",
        fontsize=10.5,
        fontweight="bold",
        y=1.01,
    )
    fig.subplots_adjust(top=0.78, bottom=0.21, left=0.09, right=0.99)
    output = save(fig, "legacy-wct-heavyfail-stress")
    metrics["source_metadata"] = metadata
    return output, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-package", action="store_true")
    args = parser.parse_args()
    if args.verify_package:
        return verify_package()

    setup_style()
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    policy_output, policy_metrics = policy_figure()
    projection_output, projection_metrics = projection_figure()
    heavy_output, heavy_metrics = heavy_figure()
    source_paths = [
        POLICY_CSV,
        PROJECTION_CSV,
        PROJECTION_ASSUMPTIONS,
        *HEAVY_FILES.values(),
    ]
    manifest = {
        "schema": "aegiskv_legacy_wct_paper_relayout_v1",
        "operation": "paper_only_analysis_and_relayout_of_frozen_legacy_results",
        "new_experiment": False,
        "sglsim_executed": False,
        "physical_runtime_executed": False,
        "current_design_validation": False,
        "evidence_boundary": (
            "All inputs predate the current source-owned independent-tier design. "
            "The DP8 comparison is a single-seed/single-trial fixed-alpha legacy "
            "prototype result; the DP64 panel is a model projection; the heavy-fail "
            "panels are logical-PP stress smoke results."
        ),
        "sources": [
            {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}
            for path in source_paths
        ],
        "outputs": {
            "policy_comparison": policy_output,
            "dp64_projection": projection_output,
            "heavyfail_stress": heavy_output,
        },
        "metrics": {
            "policy_comparison": policy_metrics,
            "dp64_projection": projection_metrics,
            "heavyfail_stress": heavy_metrics,
        },
    }
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "PASS", "manifest": str(MANIFEST)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
