#!/usr/bin/env python3
"""Render sealed native raw-KV component differences; no DES or native execution."""
# ruff: noqa: RUF001 -- mathematical minus and range dash are intentional figure glyphs.

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import fitz
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent / "native-transfer-paper-summary-v1"
SOURCE_SEAL = "e700b25df99a37c956221178a4b57c5451b450c982b507f64bf890194ac1eaa7"
WIDTH, HEIGHT, FONT = 178 / 25.4, 3.05, 10.3
MODELS = ("NOSA-8B", "NSA-8B", "MiniCPM4.1-8B")
COMPUTE_US = (0, 25.6, 256, 2560)
STYLES = {
    "dram": dict(label="DRAM − Current", color="#3b78a4", marker="^", offset=-0.18),
    "recency": dict(label="Recency − Current", color="#ac572b", marker="s", offset=0.0),
    "oracle": dict(label="Oracle − Current", color="#444444", marker="D", offset=0.18),
}
NAME = "native-transfer-differences"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def inputs():
    assert sha(SOURCE / "SEAL.json") == SOURCE_SEAL
    seal = json.loads((SOURCE / "SEAL.json").read_text())
    for relative, record in seal["files"].items():
        assert sha(SOURCE / relative) == record["sha256"], relative
    (OUT / "inputs").mkdir(exist_ok=True)
    names = ("paper-32GBps-summary.csv", "document-checkpoint-means.csv", "SEAL.json")
    for name in names:
        target = OUT / "inputs" / name
        if target.exists():
            assert target.read_bytes() == (SOURCE / name).read_bytes()
        else:
            shutil.copy2(SOURCE / name, target)
    summary = read_csv(OUT / "inputs/paper-32GBps-summary.csv")
    documents = read_csv(OUT / "inputs/document-checkpoint-means.csv")
    data = []
    assert len(summary) == 12
    for model in MODELS:
        for category, compute in enumerate(COMPUTE_US):
            group = [
                r
                for r in documents
                if (r["model"], int(r["bandwidth_GBps"]), float(r["layer_compute_us"]))
                == (model, 32, compute)
            ]
            assert len(group) == 3
            assert {r["book_id"] for r in group} == {"10146", "10321", "10356"}
            source_row = next(
                r for r in summary if (r["model"], float(r["layer_compute_us"])) == (model, compute)
            )
            for comparator, style in STYLES.items():
                field = comparator + "_minus_current"
                values = [Fraction(int(r[field + "_checkpoint_sum_ns"]), 2000) for r in group]
                expected = dict(mean=sum(values) / 3, min=min(values), max=max(values))
                for stat, value in expected.items():
                    assert abs(float(source_row[field + "_" + stat + "_us"]) - float(value)) < 1e-10
                data.append(
                    dict(
                        model=model,
                        bandwidth_GBps=32,
                        layer_compute_us=compute,
                        comparator=comparator,
                        difference="comparator_minus_Current",
                        mean_us=float(expected["mean"]),
                        min_us=float(expected["min"]),
                        max_us=float(expected["max"]),
                        documents=3,
                        checkpoints_per_document=2,
                        six_checkpoint_sum_ns=source_row[field + "_six_checkpoint_sum_ns"],
                        category=category,
                        display_x=category + style["offset"],
                    )
                )
    assert len(data) == 36
    with (OUT / "figure-data.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)
    return data, {name: sha(SOURCE / name) for name in names}


def setup():
    path = subprocess.check_output(["kpsewhich", "LinLibertine_R.otf"], text=True).strip()
    font_manager.fontManager.addfont(path)
    family = font_manager.FontProperties(fname=path).get_name()
    plt.rcParams.update(
        {
            "font.family": family,
            "font.size": FONT,
            "axes.labelsize": FONT,
            "axes.titlesize": FONT,
            "xtick.labelsize": FONT,
            "ytick.labelsize": FONT,
            "legend.fontsize": FONT,
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


def main():
    data, source_hashes = inputs()
    font, family = setup()
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, HEIGHT), sharey=True)
    fig.subplots_adjust(left=0.103, right=0.984, bottom=0.28, top=0.735, wspace=0.25)
    for panel, (ax, model) in enumerate(zip(axes, MODELS, strict=True)):
        ax.axhline(0, color="#888888", linewidth=0.7, zorder=1)
        for comparator, style in STYLES.items():
            group = [r for r in data if r["model"] == model and r["comparator"] == comparator]
            assert len(group) == 4
            y = [r["mean_us"] for r in group]
            error = [
                [r["mean_us"] - r["min_us"] for r in group],
                [r["max_us"] - r["mean_us"] for r in group],
            ]
            ax.errorbar(
                [r["display_x"] for r in group],
                y,
                yerr=error,
                fmt=style["marker"],
                linestyle="none",
                color=style["color"],
                markerfacecolor="white",
                markersize=5.2,
                markeredgewidth=1.0,
                elinewidth=1.0,
                capsize=2.5,
                capthick=0.9,
                zorder=3,
            )
        ax.set_title(f"({chr(ord('a') + panel)}) {model}", loc="left", pad=7)
        ax.set_xlim(-0.5, 3.5)
        ax.set_xticks(range(4), [f"{v:g}" for v in COMPUTE_US])
        ax.set_ylim(-280, 450)
        ax.set_yticks((-200, 0, 200, 400))
        ax.grid(axis="y", color="#e4e4e4", linewidth=0.5)
        ax.set_axisbelow(True)
    handles = [
        Line2D(
            [],
            [],
            label=s["label"],
            color=s["color"],
            marker=s["marker"],
            linestyle="none",
            markersize=5.2,
            markerfacecolor="white",
            markeredgewidth=1.0,
        )
        for s in STYLES.values()
    ]
    fig.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.535, 0.98),
        ncol=3,
        frameon=False,
        handlelength=1.2,
        handletextpad=0.35,
        columnspacing=1.3,
    )
    fig.text(0.54, 0.845, "32 GB/s; K = 16, L = 4", ha="center")
    fig.text(0.018, 0.51, "Raw-KV time difference (µs)", rotation=90, va="center")
    fig.text(0.54, 0.145, "Assumed per-layer compute (µs; categorical)", ha="center")
    fig.text(0.54, 0.04, "Positive: Current faster; ranges: 3-document min–max", ha="center")
    for suffix in ("pdf", "svg", "png"):
        fig.savefig(OUT / f"{NAME}.{suffix}", facecolor="white")
    plt.close(fig)
    with fitz.open(OUT / f"{NAME}.pdf") as doc:
        page = doc[0]
        assert abs(page.rect.width / 72 - WIDTH) < 1e-5
        spans = [
            span
            for block in page.get_text("dict")["blocks"]
            if "lines" in block
            for line in block["lines"]
            for span in line["spans"]
            if span["text"].strip()
        ]
        assert min(s["size"] for s in spans) >= FONT
        outside = [s["text"] for s in spans if not page.rect.contains(fitz.Rect(s["bbox"]))]
        assert not outside
        for dpi in (96, 144):
            for label, color in (("color", fitz.csRGB), ("grayscale", fitz.csGRAY)):
                page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), colorspace=color).save(
                    OUT / f"{NAME}-{dpi}dpi-{label}.png"
                )
        write_json(
            "EXPORT_METADATA.json",
            {
                "script_sha256": sha(Path(__file__)),
                "source_hashes": source_hashes,
                "source_summary_seal_sha256": SOURCE_SEAL,
                "figure_data_sha256": sha(OUT / "figure-data.csv"),
                "width_mm": page.rect.width / 72 * 25.4,
                "height_mm": page.rect.height / 72 * 25.4,
                "requested_font_pt": FONT,
                "minimum_font_pt": min(s["size"] for s in spans),
                "font_path": font,
                "font_family": family,
                "outside_text": outside,
                "plotted_points": len(data),
                "documents_per_cell": 3,
                "checkpoints_averaged_within_document": [32000, 32256],
                "bandwidth_GBps": 32,
                "x_axis": "categorical, no connecting lines",
                "y_axis": "shared linear [-280,450] microseconds; comparator minus Current",
                "range": "min/max of three within-document checkpoint means; not CI",
                "new_DES_runs": 0,
                "actual_visual_review": "pending",
            },
        )


if __name__ == "__main__":
    main()
