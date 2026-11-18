#!/usr/bin/env python3
"""Final-column plots of causal native-selector coverage, never recovery timing."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path

import fitz
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/native-topk"
OUT = SOURCE / "figures"
WIDTH = 3.33465
FONT_SIZE = 10.3
MODELS = ("NOSA-8B", "NSA-8B", "MiniCPM4.1-8B")
KS = (4, 16, 64)
STYLES = {
    "decay_hysteresis": dict(label="Current", color="#285d88", marker="o", ls="-", ms=4.0),
    "recency": dict(label="Recency", color="#ac572b", marker="s", ls="--", ms=4.3),
    "future_oracle": dict(label="Oracle", color="#444444", marker="D", ls=":", ms=6.7),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def setup_style():
    path = subprocess.check_output(["kpsewhich", "LinLibertine_R.otf"], text=True).strip()
    font_manager.fontManager.addfont(path)
    family = font_manager.FontProperties(fname=path).get_name()
    plt.rcParams.update(
        {
            "font.family": family,
            "font.size": FONT_SIZE,
            "axes.labelsize": FONT_SIZE,
            "axes.titlesize": FONT_SIZE,
            "xtick.labelsize": FONT_SIZE,
            "ytick.labelsize": FONT_SIZE,
            "legend.fontsize": FONT_SIZE,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.65,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "xtick.major.size": 2.6,
            "ytick.major.size": 2.6,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "savefig.dpi": 300,
        }
    )
    return path, family


def select(summary, model, k, method):
    matches = [
        row
        for row in summary
        if row["model"] == model
        and int(row["K"]) == k
        and row["method"] == method
        and int(row["first_L_layers"]) == 4
    ]
    assert len(matches) == 1
    return matches[0]


def numbers(row, metric):
    return tuple(100 * float(row[f"{metric}_{suffix}"]) for suffix in ("mean", "min", "max"))


def check_document_aggregation(summary, documents):
    for row in summary:
        if int(row["first_L_layers"]) != 4:
            continue
        group = [
            item
            for item in documents
            if (item["model"], item["K"], item["method"], item["first_L_layers"])
            == (row["model"], row["K"], row["method"], row["first_L_layers"])
        ]
        assert len(group) == 3 and len({item["book_id"] for item in group}) == 3
        for metric in ("demand_weighted_coverage", "event_weighted_coverage"):
            values = [float(item[metric]) for item in group]
            for suffix, expected in (
                ("mean", np.mean(values)),
                ("min", min(values)),
                ("max", max(values)),
            ):
                assert abs(float(row[f"{metric}_{suffix}"]) - expected) < 1e-12


def save(fig, name):
    for extension in ("pdf", "png", "svg"):
        fig.savefig(OUT / f"{name}.{extension}", facecolor="white")
    plt.close(fig)
    pdf = fitz.open(OUT / f"{name}.pdf")
    page = pdf[0]
    assert abs(page.rect.width / 72 - WIDTH) < 1e-5
    font_sizes = [
        span["size"]
        for block in page.get_text("dict")["blocks"]
        if "lines" in block
        for line in block["lines"]
        for span in line["spans"]
        if span["text"].strip()
    ]
    assert font_sizes and min(font_sizes) >= 10.0
    for dpi in (96, 144):
        for suffix, colorspace in (("color", fitz.csRGB), ("grayscale", fitz.csGRAY)):
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), colorspace=colorspace)
            pix.save(OUT / f"{name}-{dpi}dpi-{suffix}.png")
    return {
        "name": name,
        "page_width_inches": page.rect.width / 72,
        "page_height_inches": page.rect.height / 72,
        "placed_width_inches": WIDTH,
        "minimum_placed_font_pt": min(font_sizes),
        "pdf_sha256": sha(OUT / f"{name}.pdf"),
        "png_sha256": sha(OUT / f"{name}.png"),
        "font_names": sorted({item[3] for item in page.get_fonts()}),
    }


def coverage(summary, figure_data):
    fig, axes = plt.subplots(3, 1, figsize=(WIDTH, 3.3), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.167, right=0.969, bottom=0.15, top=0.85, hspace=0.64)
    # Open oracle diamonds surround coincident current markers; values are not jittered.
    handles = []
    for method in STYLES:
        style = STYLES[method]
        handles.append(
            Line2D(
                [],
                [],
                color=style["color"],
                marker=style["marker"],
                ls=style["ls"],
                markersize=style["ms"],
                markerfacecolor=style["color"] if method == "decay_hysteresis" else "white",
                linewidth=1.1,
                label=style["label"],
            )
        )
    fig.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.545, 0.985),
        frameon=False,
        ncol=3,
        handlelength=1.6,
        handletextpad=0.4,
        columnspacing=0.85,
    )
    for ax, model in zip(axes, MODELS, strict=True):
        for method in ("future_oracle", "recency", "decay_hysteresis"):
            style = STYLES[method]
            points = [
                numbers(select(summary, model, k, method), "demand_weighted_coverage") for k in KS
            ]
            values, low, high = np.asarray(points).T
            ax.errorbar(
                range(3),
                values,
                yerr=[values - low, high - values],
                color=style["color"],
                marker=style["marker"],
                linestyle=style["ls"],
                markersize=style["ms"],
                linewidth=1.1,
                elinewidth=0.7,
                capsize=2.0,
                markerfacecolor=style["color"] if method == "decay_hysteresis" else "white",
                markeredgewidth=0.9,
                zorder=4 if method == "decay_hysteresis" else 3,
            )
            for k, point in zip(KS, points, strict=True):
                figure_data.append(
                    dict(
                        figure="native-topk-coverage",
                        model=model,
                        K=k,
                        method=method,
                        metric="distinct_demand",
                        mean_percent=point[0],
                        min_percent=point[1],
                        max_percent=point[2],
                    )
                )
        current = select(summary, model, 64, "decay_hysteresis")
        recent = select(summary, model, 64, "recency")
        delta = 100 * (
            float(current["demand_weighted_coverage_mean"])
            - float(recent["demand_weighted_coverage_mean"])
        )
        delta_text = f"Δ {delta:+.2f} pp".replace("-", "\u2212")
        ax.set_title(model, loc="left", pad=3.5)
        ax.text(1.0, 1.055, delta_text, ha="right", va="bottom", transform=ax.transAxes)
        ax.set_ylim(-2, 40)
        ax.set_yticks((0, 20, 40))
        ax.set_xlim(-0.12, 2.13)
        ax.grid(axis="y", color="#dddddd", linewidth=0.45)
        ax.set_axisbelow(True)
    axes[-1].set_xticks(range(3), [str(k) for k in KS])
    axes[-1].set_xlabel("K (blocks per layer)", labelpad=4)
    fig.text(
        0.026, 0.505, "Distinct future-history coverage (%)", rotation=90, va="center", ha="left"
    )
    return save(fig, "native-topk-coverage")


def denominator(summary, figure_data):
    fig, ax = plt.subplots(figsize=(WIDTH, 2.5))
    fig.subplots_adjust(left=0.17, right=0.978, bottom=0.245, top=0.825)
    specs = (
        ("demand_weighted_coverage", "Distinct blocks", "#285d88", "", -0.175),
        ("event_weighted_coverage", "Query-block events", "#dddddd", "///", 0.175),
    )
    for metric, label, color, hatch, shift in specs:
        points = [
            numbers(select(summary, model, 64, "decay_hysteresis"), metric) for model in MODELS
        ]
        values, low, high = np.asarray(points).T
        ax.bar(
            np.arange(3) + shift,
            values,
            width=0.3,
            yerr=[values - low, high - values],
            color=color,
            edgecolor="#303030",
            linewidth=0.6,
            hatch=hatch,
            label=label,
            error_kw={"elinewidth": 0.8, "capsize": 2.1, "capthick": 0.8},
            zorder=3,
        )
        for index, (model, point) in enumerate(zip(MODELS, points, strict=True)):
            ax.text(index + shift, point[2] + 1.2, f"{point[0]:.1f}", ha="center", va="bottom")
            figure_data.append(
                dict(
                    figure="native-topk-denominator",
                    model=model,
                    K=64,
                    method="decay_hysteresis",
                    metric=metric,
                    mean_percent=point[0],
                    min_percent=point[1],
                    max_percent=point[2],
                )
            )
    ax.set_ylim(0, 72)
    ax.set_yticks((0, 20, 40, 60))
    ax.set_xticks(range(3), ("NOSA\n8B", "NSA\n8B", "MiniCPM\n4.1-8B"))
    ax.set_ylabel("Coverage (%)", labelpad=4)
    ax.grid(axis="y", color="#dddddd", linewidth=0.45)
    ax.set_axisbelow(True)
    fig.legend(
        loc="upper center",
        bbox_to_anchor=(0.555, 1.015),
        frameon=False,
        ncol=1,
        handlelength=1.35,
        labelspacing=0.25,
        handletextpad=0.5,
    )
    return save(fig, "native-topk-denominator")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    font_path, family = setup_style()
    summary, documents = read_csv(SOURCE / "summary.csv"), read_csv(SOURCE / "document-results.csv")
    audit = json.loads((SOURCE / "AUDIT.json").read_text())
    for name in ("summary.csv", "document-results.csv"):
        assert sha(SOURCE / name) == audit["result_sha256"][name]
    check_document_aggregation(summary, documents)
    figure_data = []
    exports = [coverage(summary, figure_data), denominator(summary, figure_data)]
    with (OUT / "figure-data.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(figure_data[0]))
        writer.writeheader()
        writer.writerows(figure_data)
    metadata = dict(
        source_hashes={
            name: sha(SOURCE / name)
            for name in ("summary.csv", "document-results.csv", "PROTOCOL.json", "AUDIT.json")
        },
        script_sha256=sha(Path(__file__)),
        font_path=font_path,
        font_family=family,
        requested_font_pt=FONT_SIZE,
        exports=exports,
        statistics=(
            "For each document sum covered/demand over first4 layers and two checkpoints; "
            "mean/min/max over3 documents per model"
        ),
        independent_documents_per_model=3,
        error_bars="document min/max, not confidence intervals",
        changes_to_values="none; no jitter, smoothing, truncation or excluded negative values",
        evidence="native selector replay; logical demand coverage, not recovery timing",
        actual_visual_review="pending separate review of exported color/grayscale files",
    )
    (OUT / "EXPORT_METADATA.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(exports, indent=2))


if __name__ == "__main__":
    main()
