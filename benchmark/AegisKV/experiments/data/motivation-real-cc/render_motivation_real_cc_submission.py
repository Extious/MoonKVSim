#!/usr/bin/env python3
"""Re-layout the historical Real CC Motivation Figure 1 for submission.

This renderer consumes only the already-frozen workflow-level CSV, the frozen
five-target counterfactual CSV, and the native Draw.io workflow export.  It
does not open a raw trace, instantiate AIConfigurator, import SGLSim, or run an
experiment.  The statistical and evidence semantics are unchanged; only the
paper-specific typography and two-row layout are new.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import fitz
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FixedLocator


PAPER_DIR = Path(__file__).resolve().parents[1]
AEGISKV_DIR = PAPER_DIR.parent
REPO_DIR = AEGISKV_DIR.parent

DEFAULT_GAP_CSV = AEGISKV_DIR / "figures" / "data" / "real-cc-workflow-parallel-gap.csv"
DEFAULT_FAILURE_CSV = AEGISKV_DIR / "figures" / "data" / "real-cc-example-failure-position.csv"
DEFAULT_WORKFLOW_PDF = AEGISKV_DIR / "figures" / "real-cc-workflow-8ab0a089.pdf"
DEFAULT_WORKFLOW_DRAWIO = AEGISKV_DIR / "figures" / "real-cc-workflow-8ab0a089.drawio"
DEFAULT_OUTPUT_PDF = PAPER_DIR / "figures" / "motivation-real-cc-three-panel-submission.pdf"
DEFAULT_OUTPUT_PNG = PAPER_DIR / "figures" / "motivation-real-cc-three-panel-submission.png"
DEFAULT_MANIFEST = PAPER_DIR / "figures" / "motivation-real-cc-three-panel-submission.manifest.json"
DEFAULT_TMP_DIR = PAPER_DIR / "tmp" / "pdfs" / "motivation-real-cc-three-panel-submission"

EXPECTED = {
    "gap_csv_sha256": "c78a84bf55713b3c112a8f38ee5330c2fc27e3f1e9437b87770a45b154d5cbb6",
    "failure_csv_sha256": "96aaf85f4c9f3ed5b19c78548125d70d6fdabdf3bd01602ad189df546c9de7f2",
    "workflow_pdf_sha256": "b5b5668f3dc3ab065e6eb7aa5ecc8187c2f0472eed279b87436d313bc225fa6f",
    "workflow_drawio_sha256": "d244fc068c025d85b7830232a52672ae0499444da06e1a62f542a424d8925699",
    "trace_sha256": "29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276",
    "workflow_id": "8ab0a0892b0035b681a85c71d603caeb9e0f",
    "gap_workflows": 124,
    "median_gap_s": 140.611,
    "p90_gap_s": 1570.290,
    "failure_targets": 5,
    "failure_time_s": 349.5,
    "delta_wct_s": [0.0, 17.152499, 0.0, 35.903174, 21.376957],
}

FINAL_WIDTH_PT = 7.0 * 72.0
FINAL_HEIGHT_PT = 4.15 * 72.0
TOP_PANEL_WIDTH_PT = 3.40 * 72.0
TOP_PANEL_HEIGHT_PT = 2.25 * 72.0
BOTTOM_WORKFLOW_WIDTH_PT = 4.35 * 72.0
BOTTOM_TITLE_HEIGHT_PT = 18.0
MIN_FONT_PT = 9.95


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(REPO_DIR.resolve()))


def require_sha(path: Path, expected: str) -> None:
    actual = sha256(path)
    if actual != expected:
        raise RuntimeError(f"unexpected SHA for {path}: {actual}")


def load_gap_rows(path: Path) -> tuple[list[dict[str, str]], np.ndarray]:
    require_sha(path, EXPECTED["gap_csv_sha256"])
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != EXPECTED["gap_workflows"]:
        raise RuntimeError(f"workflow count drifted: {len(rows)}")
    if len({row["workflow_id"] for row in rows}) != len(rows):
        raise RuntimeError("workflow-level gap samples are not unique")
    if {row["trace_sha256"] for row in rows} != {EXPECTED["trace_sha256"]}:
        raise RuntimeError("gap samples do not bind the frozen trace SHA")
    if {row["selection_rule"] for row in rows} != {
        "max_within_fanout_duration_gap_per_workflow"
    }:
        raise RuntimeError("workflow-level gap selection rule drifted")
    if {row["parallel_definition"] for row in rows} != {"max_start_lt_min_end"}:
        raise RuntimeError("strict-overlap definition drifted")
    values = np.asarray([float(row["max_duration_gap_s"]) for row in rows])
    if round(float(np.quantile(values, 0.50)), 3) != EXPECTED["median_gap_s"]:
        raise RuntimeError("median workflow gap drifted")
    if round(float(np.quantile(values, 0.90)), 3) != EXPECTED["p90_gap_s"]:
        raise RuntimeError("p90 workflow gap drifted")
    return rows, values


def load_failure_rows(path: Path) -> list[dict[str, str]]:
    require_sha(path, EXPECTED["failure_csv_sha256"])
    with path.open(newline="", encoding="utf-8") as stream:
        rows = sorted(csv.DictReader(stream), key=lambda row: int(row["branch_index"]))
    if len(rows) != EXPECTED["failure_targets"]:
        raise RuntimeError(f"failure-target count drifted: {len(rows)}")
    if {row["workflow_id"] for row in rows} != {EXPECTED["workflow_id"]}:
        raise RuntimeError("failure-target workflow changed")
    if {row["trace_sha256"] for row in rows} != {EXPECTED["trace_sha256"]}:
        raise RuntimeError("failure rows do not bind the frozen materialized trace")
    if {row["raw_trace_sha256"] for row in rows} != {EXPECTED["trace_sha256"]}:
        raise RuntimeError("failure rows do not bind the frozen raw trace")
    if {row["counterfactual"] for row in rows} != {
        "aiconfigurator_full_prefix_recompute_at_tf"
    }:
        raise RuntimeError("counterfactual contract drifted")
    if {row["predictor_evidence"] for row in rows} != {
        "configuration_prediction_not_physical_pp_run"
    }:
        raise RuntimeError("counterfactual evidence boundary drifted")
    if {float(row["failure_time_s"]) for row in rows} != {
        EXPECTED["failure_time_s"]
    }:
        raise RuntimeError("failure time drifted")
    observed = [float(row["delta_wct_s"]) for row in rows]
    if observed != EXPECTED["delta_wct_s"]:
        raise RuntimeError(f"failure-position values drifted: {observed}")
    return rows


def plot_style() -> dict[str, object]:
    return {
        "font.family": "DejaVu Sans",
        "font.size": 10.0,
        "axes.labelsize": 10.0,
        "axes.titlesize": 10.5,
        "xtick.labelsize": 10.0,
        "ytick.labelsize": 10.0,
        "axes.linewidth": 0.8,
        "lines.linewidth": 1.7,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }


def render_gap_panel(values: np.ndarray, output: Path) -> None:
    ordered = np.sort(values)
    ecdf = np.arange(1, len(ordered) + 1, dtype=float) / len(ordered)
    median = float(np.quantile(values, 0.50))
    p90 = float(np.quantile(values, 0.90))
    with plt.rc_context(plot_style()):
        fig, ax = plt.subplots(figsize=(3.40, 2.25))
        ax.step(ordered, ecdf, where="post", color="#111111")
        marker_indices = np.unique(np.linspace(0, len(ordered) - 1, 12, dtype=int))
        ax.plot(
            ordered[marker_indices],
            ecdf[marker_indices],
            linestyle="none",
            marker="o",
            markersize=3.8,
            markerfacecolor="white",
            markeredgecolor="#111111",
            markeredgewidth=0.8,
        )
        ax.vlines(median, 0.0, 0.5, colors="#555555", linestyles="--", linewidth=1.1)
        ax.vlines(p90, 0.0, 0.9, colors="#777777", linestyles=":", linewidth=1.25)
        ax.scatter(
            [median, p90],
            [0.5, 0.9],
            s=24,
            facecolors="white",
            edgecolors="#111111",
            linewidths=1.0,
            zorder=4,
        )
        ax.annotate(
            "median\n140.611 s",
            xy=(median, 0.5),
            xytext=(7, -36),
            textcoords="offset points",
            ha="left",
            va="bottom",
            fontsize=10.0,
        )
        ax.annotate(
            "p90\n1570.290 s",
            xy=(p90, 0.9),
            xytext=(-7, -39),
            textcoords="offset points",
            ha="right",
            va="bottom",
            fontsize=10.0,
        )
        ax.text(
            0.035,
            0.945,
            "Real CC/Weka\nn=124 workflows",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10.0,
        )
        ax.set_xscale("log")
        ax.set_xlim(0.3, 2.0e4)
        ax.set_ylim(0.0, 1.02)
        ax.xaxis.set_major_locator(FixedLocator([1, 10, 100, 1000, 10000]))
        ax.set_xticklabels(["1", "10", "100", "1k", "10k"])
        ax.yaxis.set_major_locator(FixedLocator([0.0, 0.25, 0.5, 0.75, 1.0]))
        ax.set_yticklabels(["0", ".25", ".50", ".75", "1"])
        ax.set_xlabel("Max. fan-out duration gap (s)", labelpad=2)
        ax.set_ylabel("Workflow ECDF", labelpad=2)
        ax.set_title("(a) Parallel-runtime gap", loc="left", fontweight="bold", pad=6)
        ax.grid(True, which="major", color="#D0D0D0", linewidth=0.55)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        fig.subplots_adjust(left=0.19, right=0.985, top=0.86, bottom=0.24)
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, format="pdf", metadata={"CreationDate": None})
        plt.close(fig)


def render_failure_panel(rows: list[dict[str, str]], output: Path) -> None:
    values = np.asarray([float(row["delta_wct_s"]) for row in rows])
    positions = np.arange(len(rows))
    labels = [f"A{index + 1}" for index in range(len(rows))]
    with plt.rc_context(plot_style()):
        fig, ax = plt.subplots(figsize=(3.40, 2.25))
        bars = ax.barh(
            positions,
            values,
            height=0.56,
            color=["white" if value == 0 else "#777777" for value in values],
            edgecolor="#111111",
            linewidth=0.9,
        )
        for bar, value in zip(bars, values):
            if value > 0:
                bar.set_hatch("////")
            ax.text(
                value + 0.9 if value > 0 else 0.8,
                bar.get_y() + bar.get_height() / 2,
                f"{value:.1f}",
                ha="left",
                va="center",
                fontsize=10.0,
            )
        ax.set_yticks(positions, labels)
        ax.invert_yaxis()
        ax.set_xlim(0.0, 45.5)
        ax.xaxis.set_major_locator(FixedLocator([0, 10, 20, 30, 40]))
        ax.set_xlabel("Exposed fan-in delay (s)", labelpad=2)
        ax.set_title(
            "(c) Failure-position sensitivity",
            loc="left",
            fontweight="bold",
            pad=6,
        )
        ax.text(
            0.98,
            0.96,
            "Trace + model\ncounterfactual\n(AIConfigurator)\nat 349.5 s",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=10.0,
        )
        ax.grid(True, axis="x", color="#D0D0D0", linewidth=0.55)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        fig.subplots_adjust(left=0.15, right=0.985, top=0.86, bottom=0.24)
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, format="pdf", metadata={"CreationDate": None})
        plt.close(fig)


def compose(
    gap_pdf: Path,
    failure_pdf: Path,
    workflow_pdf: Path,
    output_pdf: Path,
) -> None:
    gap = fitz.open(gap_pdf)
    failure = fitz.open(failure_pdf)
    workflow = fitz.open(workflow_pdf)
    if any(document.page_count != 1 for document in (gap, failure, workflow)):
        raise RuntimeError("all frozen/layout components must be single-page PDFs")

    document = fitz.open()
    page = document.new_page(width=FINAL_WIDTH_PT, height=FINAL_HEIGHT_PT)
    page.show_pdf_page(
        fitz.Rect(0.0, 0.0, TOP_PANEL_WIDTH_PT, TOP_PANEL_HEIGHT_PT), gap, 0
    )
    page.show_pdf_page(
        fitz.Rect(
            FINAL_WIDTH_PT - TOP_PANEL_WIDTH_PT,
            0.0,
            FINAL_WIDTH_PT,
            TOP_PANEL_HEIGHT_PT,
        ),
        failure,
        0,
    )

    title_top = TOP_PANEL_HEIGHT_PT
    title_rect = fitz.Rect(0.0, title_top, FINAL_WIDTH_PT, title_top + BOTTOM_TITLE_HEIGHT_PT)
    inserted = page.insert_textbox(
        title_rect,
        "(b) Real CC workflow example (trace reconstruction)",
        fontname="Helvetica-Bold",
        fontsize=10.5,
        color=(0.07, 0.07, 0.07),
        align=fitz.TEXT_ALIGN_CENTER,
    )
    if inserted < 0:
        raise RuntimeError("bottom-panel title did not fit")

    workflow_source_rect = workflow[0].rect
    workflow_height_pt = (
        BOTTOM_WORKFLOW_WIDTH_PT * workflow_source_rect.height / workflow_source_rect.width
    )
    workflow_left = (FINAL_WIDTH_PT - BOTTOM_WORKFLOW_WIDTH_PT) / 2.0
    workflow_top = title_top + BOTTOM_TITLE_HEIGHT_PT
    workflow_rect = fitz.Rect(
        workflow_left,
        workflow_top,
        workflow_left + BOTTOM_WORKFLOW_WIDTH_PT,
        workflow_top + workflow_height_pt,
    )
    if workflow_rect.y1 > FINAL_HEIGHT_PT:
        raise RuntimeError(f"workflow panel exceeds final page: {workflow_rect}")
    page.show_pdf_page(workflow_rect, workflow, 0, keep_proportion=True)
    document.set_metadata(
        {
            "title": "Real CC workflow parallelism and failure-position sensitivity",
            "author": "Anonymous",
            "subject": "Paper-specific re-layout of frozen Motivation Figure 1",
        }
    )
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_pdf, garbage=4, deflate=True, clean=True)
    document.close()
    gap.close()
    failure.close()
    workflow.close()


def audit_pdf(path: Path) -> dict[str, object]:
    document = fitz.open(path)
    if document.page_count != 1:
        raise RuntimeError(f"expected one figure page, got {document.page_count}")
    page = document[0]
    if abs(page.rect.width - FINAL_WIDTH_PT) > 0.05:
        raise RuntimeError(f"figure is not 7 inches wide: {page.rect.width} pt")
    if abs(page.rect.height - FINAL_HEIGHT_PT) > 0.05:
        raise RuntimeError(f"unexpected figure height: {page.rect.height} pt")
    spans: list[dict[str, object]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans.extend(
                span for span in line.get("spans", []) if str(span.get("text", "")).strip()
            )
    if not spans:
        raise RuntimeError("final figure contains no extractable text")
    minimum = min(spans, key=lambda span: float(span["size"]))
    if float(minimum["size"]) < MIN_FONT_PT:
        raise RuntimeError(
            f"font below 10 pt: {minimum['size']:.3f} in {minimum['text']!r}"
        )
    for span in spans:
        if not page.rect.contains(fitz.Rect(span["bbox"])):
            raise RuntimeError(f"text outside MediaBox: {span['text']!r}")
    images = page.get_images(full=True)
    if images:
        raise RuntimeError(f"final submission figure is not all-vector: {len(images)} images")
    text = page.get_text()
    required = (
        "(a) Parallel-runtime gap",
        "(b) Real CC workflow example",
        "(c) Failure-position sensitivity",
        "n=124 workflows",
        "140.611 s",
        "1570.290 s",
        "Trace + model",
        "AIConfigurator",
        "A1 110.3 s",
        "A5 107.1 s",
    )
    missing = [phrase for phrase in required if phrase not in text]
    if missing:
        raise RuntimeError(f"expected final labels missing: {missing}")
    result = {
        "page_count": 1,
        "width_in": round(page.rect.width / 72.0, 6),
        "height_in": round(page.rect.height / 72.0, 6),
        "minimum_extracted_font_pt": round(float(minimum["size"]), 6),
        "minimum_font_text": str(minimum["text"]),
        "text_spans": len(spans),
        "embedded_raster_images": len(images),
        "text_inside_media_box": True,
        "vector_only": True,
    }
    document.close()
    return result


def render_png(pdf_path: Path, png_path: Path) -> tuple[int, int]:
    document = fitz.open(pdf_path)
    pixmap = document[0].get_pixmap(
        matrix=fitz.Matrix(300 / 72.0, 300 / 72.0), alpha=False
    )
    png_path.parent.mkdir(parents=True, exist_ok=True)
    pixmap.save(png_path)
    dimensions = (pixmap.width, pixmap.height)
    document.close()
    return dimensions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gap-csv", type=Path, default=DEFAULT_GAP_CSV)
    parser.add_argument("--failure-csv", type=Path, default=DEFAULT_FAILURE_CSV)
    parser.add_argument("--workflow-pdf", type=Path, default=DEFAULT_WORKFLOW_PDF)
    parser.add_argument("--workflow-drawio", type=Path, default=DEFAULT_WORKFLOW_DRAWIO)
    parser.add_argument("--output-pdf", type=Path, default=DEFAULT_OUTPUT_PDF)
    parser.add_argument("--output-png", type=Path, default=DEFAULT_OUTPUT_PNG)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--tmp-dir", type=Path, default=DEFAULT_TMP_DIR)
    args = parser.parse_args()

    _, gap_values = load_gap_rows(args.gap_csv)
    failure_rows = load_failure_rows(args.failure_csv)
    require_sha(args.workflow_pdf, EXPECTED["workflow_pdf_sha256"])
    require_sha(args.workflow_drawio, EXPECTED["workflow_drawio_sha256"])

    args.tmp_dir.mkdir(parents=True, exist_ok=True)
    gap_panel = args.tmp_dir / "panel-a-gap.pdf"
    failure_panel = args.tmp_dir / "panel-c-failure.pdf"
    render_gap_panel(gap_values, gap_panel)
    render_failure_panel(failure_rows, failure_panel)
    compose(gap_panel, failure_panel, args.workflow_pdf, args.output_pdf)
    pdf_audit = audit_pdf(args.output_pdf)
    png_dimensions = render_png(args.output_pdf, args.output_png)

    manifest = {
        "schema": "aegiskv_historical_motivation_submission_layout_v1",
        "operation": "paper_only_relayout_of_frozen_historical_figure_1",
        "raw_trace_accessed": False,
        "predictor_executed": False,
        "sglsim_executed": False,
        "new_experiment": False,
        "evidence_boundary": {
            "panel_a": "Real CC trace observation; one maximum strict-parallel fan-out duration gap per workflow",
            "panel_b": "Real CC trace reconstruction from top-level order and timestamps because the trace has no parent ID",
            "panel_c": "frozen trace-plus-AIConfigurator counterfactual, not a Claude, physical PP, failure-to-ready, or paired failure measurement",
        },
        "inputs": {
            "gap_csv": relative(args.gap_csv),
            "gap_csv_sha256": sha256(args.gap_csv),
            "failure_csv": relative(args.failure_csv),
            "failure_csv_sha256": sha256(args.failure_csv),
            "workflow_pdf": relative(args.workflow_pdf),
            "workflow_pdf_sha256": sha256(args.workflow_pdf),
            "workflow_drawio": relative(args.workflow_drawio),
            "workflow_drawio_sha256": sha256(args.workflow_drawio),
            "embedded_raw_trace_sha256": EXPECTED["trace_sha256"],
        },
        "statistics": {
            "workflows": EXPECTED["gap_workflows"],
            "median_workflow_max_gap_s": EXPECTED["median_gap_s"],
            "p90_workflow_max_gap_s": EXPECTED["p90_gap_s"],
            "example_workflow_id": EXPECTED["workflow_id"],
            "example_failure_time_s": EXPECTED["failure_time_s"],
            "failure_target_delta_wct_s": EXPECTED["delta_wct_s"],
        },
        "renderer": {
            "path": relative(Path(__file__)),
            "sha256": sha256(Path(__file__)),
        },
        "outputs": {
            "pdf": relative(args.output_pdf),
            "pdf_sha256": sha256(args.output_pdf),
            "png": relative(args.output_png),
            "png_sha256": sha256(args.output_png),
            "png_width_px": png_dimensions[0],
            "png_height_px": png_dimensions[1],
        },
        "pdf_audit": pdf_audit,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
