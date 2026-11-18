#!/usr/bin/env python3
"""Final-width, descriptive sensitivity figures for one fixed failure identity."""

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
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/sensitivity-campaign-v1"
OUT = SOURCE / "figures"
WIDTH, FONT = 178 / 25.4, 10.3
STYLES = {
    "none": dict(label="Restart", color="#777777", marker="x", ls=":", ms=5.3),
    "dram": dict(label="DRAM", color="#3b78a4", marker="s", ls="--", ms=6.0),
    "aegiskv": dict(label="AegisKV", color="#b7474b", marker="o", ls="-", ms=3.5),
}
RESOURCES = (
    ("h2d_GBps", "(a) H2D bandwidth", "Bandwidth (GB/s)", "log", 1),
    ("dram_GiB_per_host", "(b) Peer DRAM capacity", "DRAM per host (GiB)", "log", 1),
    ("hbm_cap_MiB_per_rank", "(c) Peer HBM cap", "HBM cap per rank (MiB)", "symlog32", 1),
)
CONTROLS = (
    ("online_prediction_multiplier", "(a) Prediction scale", "Prediction multiplier", "linear", 1),
    ("prediction_latency_ms_at_TTL100ms", "(b) TTL = 100 ms", "Prediction latency (ms)", "log", 1),
    ("compute_dma_slowdown", "(c) DMA/compute coupling", "Modeled slowdown (%)", "linear", 100),
    ("failure_detection_ms", "(d) Failure detection", "Detection delay (ms)", "log", 1),
    ("tolerance_seconds", "(e) Protection tolerance", "Tolerance (ms)", "symlog10", 1000),
    ("checkpoint_tokens", "(f) Checkpoint interval", "Z (tokens)", "log", 1),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def setup():
    font_path = subprocess.check_output(["kpsewhich", "LinLibertine_R.otf"], text=True).strip()
    font_manager.fontManager.addfont(font_path)
    family = font_manager.FontProperties(fname=font_path).get_name()
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
            "xtick.major.size": 3,
            "ytick.major.size": 3,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "savefig.dpi": 300,
        }
    )
    return font_path, family


def verify_inputs():
    audit = json.loads((SOURCE / "AUDIT.json").read_text())
    assert audit["complete"] and audit["verified_runs"] == 126
    for name, digest in audit["outputs_sha256"].items():
        assert sha(SOURCE / name) == digest
    plan = json.loads((SOURCE / "PLAN.json").read_text())
    paired = read_csv(SOURCE / "paired-workflows.csv")
    targets = [r for r in paired if r["target_workflow"] == "True"]
    assert len(paired) == 252 and len(targets) == 63
    by_id = {r["id"]: r for r in targets}
    for job in plan["jobs"]:
        if job["fault"] != "F1":
            continue
        normal = json.loads((SOURCE / "runs" / job["f0_id"] / "summary.json").read_text())
        failed = json.loads((SOURCE / "runs" / job["id"] / "summary.json").read_text())
        workflow = job["failure"]["agent"].split("/")[0]
        expected = (
            failed["workflows"][workflow]["wct_ns"] - normal["workflows"][workflow]["wct_ns"]
        ) / 1e9
        assert float(by_id[job["id"]]["delta_wct_s"]) == expected
    return plan, targets, paired


def save(fig, name):
    for extension in ("pdf", "png", "svg"):
        fig.savefig(OUT / f"{name}.{extension}", facecolor="white")
    plt.close(fig)
    with fitz.open(OUT / f"{name}.pdf") as document:
        page = document[0]
        assert abs(page.rect.width / 72 - WIDTH) < 1e-5
        spans = [
            s
            for b in page.get_text("dict")["blocks"]
            if "lines" in b
            for line in b["lines"]
            for s in line["spans"]
            if s["text"].strip()
        ]
        assert min(s["size"] for s in spans) >= 10
        for dpi in (96, 144):
            for suffix, color in (("color", fitz.csRGB), ("grayscale", fitz.csGRAY)):
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), colorspace=color)
                pix.save(OUT / f"{name}-{dpi}dpi-{suffix}.png")
        return dict(
            name=name,
            width_inches=page.rect.width / 72,
            height_inches=page.rect.height / 72,
            insertion_width_mm=178,
            minimum_placed_font_pt=min(s["size"] for s in spans),
            pdf_sha256=sha(OUT / f"{name}.pdf"),
            png_sha256=sha(OUT / f"{name}.png"),
            embedded_fonts=sorted({item[3] for item in page.get_fonts()}),
        )


def draw(specifications, name, plan, targets, figure_data):
    rows = 1 if len(specifications) == 3 else 2
    y_upper = 3 if rows == 1 else 30
    fig, axes = plt.subplots(
        rows, 3, figsize=(WIDTH, 2.6 if rows == 1 else 4.65), sharey=True, squeeze=False
    )
    fig.subplots_adjust(
        left=0.087,
        right=0.983,
        bottom=0.255 if rows == 1 else 0.14,
        top=0.735 if rows == 1 else 0.85,
        wspace=0.34,
        hspace=0.83,
    )
    handles = [
        Line2D(
            [],
            [],
            label=s["label"],
            color=s["color"],
            marker=s["marker"],
            linestyle=s["ls"],
            markersize=s["ms"],
            linewidth=1.1,
            markerfacecolor=s["color"] if p == "aegiskv" else "white",
        )
        for p, s in STYLES.items()
    ]
    fig.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.55, 0.99),
        ncol=3,
        frameon=False,
        handlelength=2.0,
        handletextpad=0.45,
        columnspacing=1.2,
    )
    for ax, (factor, title, xlabel, scale, multiple) in zip(axes.flat, specifications, strict=True):
        aliases = [r for r in plan["protocol"]["factor_aliases"] if r["factor"] == factor]
        x = [float(r["value"]) * multiple for r in aliases]
        for policy, style in STYLES.items():
            y = []
            for alias, value in zip(aliases, x, strict=True):
                matches = [
                    r
                    for r in targets
                    if r["condition"] == alias["condition"] and r["policy"] == policy
                ]
                assert len(matches) == 1
                penalty = float(matches[0]["delta_wct_s"])
                assert 0.01 < penalty < y_upper, "Do not discard points outside the log axis"
                y.append(penalty)
                figure_data.append(
                    dict(
                        figure=name,
                        factor=factor,
                        configured_value=alias["value"],
                        displayed_x=value,
                        condition=alias["condition"],
                        policy=policy,
                        target_workflow=matches[0]["workflow"],
                        target_delta_wct_seconds=penalty,
                        fixed_fault_identities=1,
                    )
                )
            ax.plot(
                x,
                y,
                color=style["color"],
                marker=style["marker"],
                ls=style["ls"],
                markersize=style["ms"],
                linewidth=1.1,
                markeredgewidth=0.9,
                markerfacecolor=style["color"] if policy == "aegiskv" else "white",
            )
        if scale == "log":
            ax.set_xscale("log", base=2)
        elif scale.startswith("symlog"):
            ax.set_xscale("symlog", base=2, linthresh=int(scale.removeprefix("symlog")))
        ax.set_xticks(x, [f"{v:g}" for v in x])
        ax.minorticks_off()
        ax.set_yscale("log")
        ax.set_ylim(0.01, y_upper)
        ax.set_yticks((0.01, 0.1, 1) if rows == 1 else (0.01, 0.1, 1, 10))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
        ax.set_title(title, loc="left", pad=6)
        ax.set_xlabel(xlabel, labelpad=4)
        ax.grid(axis="y", color="#dddddd", linewidth=0.5)
        ax.set_axisbelow(True)
    fig.text(
        0.012,
        0.51,
        "Target workflow penalty (s)",
        rotation=90,
        va="center",
        ha="left",
        fontsize=FONT,
    )
    return save(fig, name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    font, family = setup()
    plan, targets, paired = verify_inputs()
    data = []
    exports = [
        draw(RESOURCES, "sensitivity-resources", plan, targets, data),
        draw(CONTROLS, "sensitivity-controls", plan, targets, data),
    ]
    assert len(data) == 84
    with (OUT / "figure-data.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)
    metadata = dict(
        script_sha256=sha(__file__),
        font_path=font,
        font_family=family,
        requested_font_pt=FONT,
        source_hashes={
            name: sha(SOURCE / name)
            for name in (
                "PLAN.json",
                "PROTOCOL.json",
                "AUDIT.json",
                "paired-workflows.csv",
                "raw-runs.csv",
                "binding-diagnostics.csv",
            )
        },
        exports=exports,
        independent_fault_identities=1,
        underlying_workflows=4,
        plotted_points=84,
        statistic="single target-workflow F1 minus its condition/policy own F0; no error bars",
        axes=(
            "log y, shared within each figure: resources [0.01,3], controls [0.01,30]; "
            "log/symlog x positions preserve tested numerical values"
        ),
        omitted_observations="other workflow outcomes remain in paired CSV; no source filtering",
        negative_collateral_delta_count=sum(float(r["delta_wct_s"]) < 0 for r in paired),
        shared_center="one observed central condition reused by explicit factor aliases",
        protocol_coupling="Z64 changes modeled prefill chunks and checkpoint/decay cadence",
        actual_visual_review="pending actual exported PNG and PDF-render review",
    )
    (OUT / "EXPORT_METADATA.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(exports, indent=2))


if __name__ == "__main__":
    main()
