"""Shared acceptance and final-size export for the simulation manuscript."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

from moonkvsim.aegiskv.paper_artifacts import file_sha256
from moonkvsim.aegiskv.qwen3_8b_acceptance import load_json_strict, validate_manifest
from moonkvsim.common.hash import sha256_json


def accepted_attempt(manifest: Path, panels: set[str]) -> dict[str, Any]:
    document = load_json_strict(manifest)
    root = Path(__file__).resolve().parents[4]
    validate_manifest(document, root / "schemas/aegiskv-qwen3-8b-acceptance-manifest.schema.json")
    entries = [entry for entry in document["attempts"]
               if entry["terminal_class"] == "VALID"
               and entry["accepted_for_numerical_aggregates"] is True
               and panels <= set(entry["allowed_panel_ids"])]
    if len(entries) != 1:
        raise ValueError(f"expected exactly one VALID accepted attempt for {sorted(panels)}")
    entry = entries[0]
    artifact = root / entry["artifact"]["path"]
    if file_sha256(artifact) != entry["artifact"]["sha256"]:
        raise ValueError("accepted aggregate artifact changed after verification")
    return entry


def style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 10,
        "axes.labelsize": 10, "xtick.labelsize": 10, "ytick.labelsize": 10,
        "legend.fontsize": 10, "pdf.fonttype": 42, "svg.fonttype": "none",
        "axes.spines.top": False, "axes.spines.right": False,
    })


def estimate(summary: dict, scale: float = 1) -> tuple[float, float, float]:
    if summary["sample_count"] != 5 or summary["ci95"]["degrees_of_freedom"] != 4:
        raise ValueError("figure requires five seed estimates and a df=4 interval")
    mean = summary["mean"]["numerator"] / summary["mean"]["denominator"] / scale
    return mean, summary["ci95"]["lower_floor"] / scale, (
        summary["ci95"]["upper_ceiling"] / scale
    )


def export(fig, stem: Path, *, generator: Path, inputs: list[Path], data: dict) -> None:
    stem.parent.mkdir(parents=True, exist_ok=True)
    fig.canvas.draw()
    outputs = {}
    for suffix in ("pdf", "svg", "png"):
        path = stem.with_suffix("." + suffix)
        fig.savefig(path, dpi=200, facecolor="white")
        outputs[suffix] = file_sha256(path)
    plt.close(fig)
    body = {
        "schema": "moonkvsim.simulation-paper-figure.v1", "chart_data": data,
        "generator_sha256": file_sha256(generator),
        "helper_sha256": file_sha256(Path(__file__)),
        "input_sha256": {str(p.resolve()): file_sha256(p) for p in inputs},
        "output_sha256": outputs, "minimum_font_pt": 10,
        "interval": data.get("interval", "two-sided Student t, five paired admission seeds, df=4"),
        "physical_execution": False, "modeled_uncalibrated": True,
        "submission_ready": False,
    }
    stem.with_suffix(".json").write_text(json.dumps(
        {**body, "fingerprint": sha256_json(body)}, indent=2,
    ) + "\n")
    print(stem)
