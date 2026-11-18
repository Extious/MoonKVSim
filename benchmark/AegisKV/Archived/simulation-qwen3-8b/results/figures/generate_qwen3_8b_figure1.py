#!/usr/bin/env python3
"""Render Qwen3-8B Figure 1 from accepted workload/intervention evidence."""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import matplotlib.pyplot as plt
import numpy as np

from moonkvsim.aegiskv.qwen3_8b_acceptance import (
    fingerprint,
    load_json_strict,
    write_json_atomic,
)

SCHEMA = "moonkvsim.aegiskv.qwen3_8b.figure1_evidence.v1"
PANEL_STEMS = {
    "FIGURE_1_A": "figure_1a_prompt_token_ecdf",
    "FIGURE_1_B": "figure_1b_spans_per_workflow",
    "FIGURE_1_C": "figure_1c_context_and_focus_population",
    "FIGURE_1_D": "figure_1d_intervention_audit",
}
MOONCAKE = "vanilla_mooncake_dram"
AEGISKV = "aegiskv_unified"
BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
PURPLE = "#6F4C9B"
GREY = "#777777"


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be an array")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Mapping[str, Any]:
    document = _mapping(load_json_strict(path), "Figure 1 evidence")
    claimed = document.get("fingerprint")
    body = {key: value for key, value in document.items() if key != "fingerprint"}
    if fingerprint(body) != claimed:
        raise ValueError("Figure 1 evidence self-fingerprint mismatch")
    if document.get("schema") != SCHEMA or document.get("status") != "PASS":
        raise ValueError("unsupported Figure 1 evidence")
    workload = _mapping(document.get("workload"), "workload")
    if (
        workload.get("record_count") != 1_304
        or workload.get("exact_token_ids_verified") is not True
        or workload.get("workflow_filtering") is not False
        or workload.get("workflow_count") != 160
    ):
        raise ValueError("Figure 1 workload contract mismatch")
    buckets = _mapping(workload.get("context_bucket_counts"), "context buckets")
    if buckets.get("128k") != 0 or sum(int(value) for value in buckets.values()) != 1_304:
        raise ValueError("Figure 1 context population mismatch")
    intervention = _mapping(document.get("intervention_audit"), "intervention audit")
    if len(_array(intervention.get("seed_contracts"), "seed contracts")) != 5:
        raise ValueError("Figure 1 intervention audit requires five seeds")
    return document


def _style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "figure.dpi": 150,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def _plot_1a(document: Mapping[str, Any]) -> Any:
    prompts = np.sort(
        np.asarray(_array(_mapping(document["workload"], "workload")["prompt_tokens"], "prompts"))
    )
    y = np.arange(1, len(prompts) + 1) / len(prompts)
    fig, ax = plt.subplots(figsize=(6.8, 4.4), constrained_layout=True)
    ax.step(prompts, y, where="post", color=BLUE, linewidth=2)
    ax.set_xscale("log", base=2)
    ax.set_xlabel("Prompt tokens (log₂ scale)")
    ax.set_ylabel("Request ECDF")
    ax.set_title("Frozen request prompt-size distribution")
    return fig


def _plot_1b(document: Mapping[str, Any]) -> Any:
    counts = list(
        _mapping(
            _mapping(document["workload"], "workload")["workflow_span_counts"],
            "workflow span counts",
        ).values()
    )
    values, frequencies = np.unique(np.asarray(counts, dtype=int), return_counts=True)
    fig, ax = plt.subplots(figsize=(6.8, 4.4), constrained_layout=True)
    ax.bar(values, frequencies, color=GREEN)
    ax.set_xlabel("Requests/spans per workflow")
    ax.set_ylabel("Workflow count")
    ax.set_title("Frozen workflow-structure distribution")
    return fig


def _plot_1c(document: Mapping[str, Any]) -> Any:
    workload = _mapping(document["workload"], "workload")
    buckets = _mapping(workload["context_bucket_counts"], "context buckets")
    labels = ("8k", "32k", "64k", "96k", "128k")
    values = [int(buckets[label]) for label in labels]
    focus_buckets = Counter(
        str(row["focus_bucket"])
        for row in _array(
            _mapping(document["intervention_audit"], "intervention audit")[
                "seed_contracts"
            ],
            "seed contracts",
        )
    )
    focus = [focus_buckets[label] for label in labels]
    x = np.arange(len(labels), dtype=float)
    fig, ax = plt.subplots(figsize=(7.4, 4.5), constrained_layout=True)
    ax.bar(x - 0.18, values, 0.36, color=BLUE, label="all requests")
    ax.bar(x + 0.18, focus, 0.36, color=ORANGE, label="failure focus (5 seeds)")
    ax.set_xticks(x, labels)
    ax.set_ylabel("Request count")
    ax.set_title("Context populations and pre-registered failure focus")
    ax.legend(frameon=False)
    ax.annotate("128k population = 0", (x[-1], 0), xytext=(-45, 30), textcoords="offset points")
    return fig


def _plot_1d(document: Mapping[str, Any]) -> Any:
    rows = _array(
        _mapping(document["intervention_audit"], "intervention audit")[
            "seed_contracts"
        ],
        "seed contracts",
    )
    x = np.arange(len(rows), dtype=float)
    moon_times = []
    aegis_times = []
    moon_victims = []
    aegis_victims = []
    for row in rows:
        systems = _mapping(_mapping(row, "seed contract")["systems"], "systems")
        moon = _mapping(systems[MOONCAKE], "Mooncake outcome")
        aegis = _mapping(systems[AEGISKV], "AegisKV outcome")
        moon_times.append(float(moon["injection_timestamp_ns"]) / 1e9)
        aegis_times.append(float(aegis["injection_timestamp_ns"]) / 1e9)
        moon_victims.append(int(moon["active_victim_count"]) + int(moon["queued_victim_count"]))
        aegis_victims.append(int(aegis["active_victim_count"]) + int(aegis["queued_victim_count"]))
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.4), constrained_layout=True)
    axes[0].plot(x, moon_times, "o-", color=BLUE, label="Mooncake")
    axes[0].plot(x, aegis_times, "o-", color=ORANGE, label="AegisKV")
    axes[0].set_xticks(x, [f"seed {row['seed']}" for row in rows])
    axes[0].set_ylabel("First-crossing injection time (s)")
    axes[0].set_title("Realized injection time")
    axes[0].legend(frameon=False)
    width = 0.36
    axes[1].bar(x - width / 2, moon_victims, width, color=BLUE, label="Mooncake")
    axes[1].bar(x + width / 2, aegis_victims, width, color=ORANGE, label="AegisKV")
    axes[1].set_xticks(x, [f"seed {row['seed']}" for row in rows])
    axes[1].set_ylabel("Active + queued victims")
    axes[1].set_title("Post-treatment victim exposure")
    axes[1].legend(frameon=False)
    return fig


PLOTTERS = {
    "FIGURE_1_A": _plot_1a,
    "FIGURE_1_B": _plot_1b,
    "FIGURE_1_C": _plot_1c,
    "FIGURE_1_D": _plot_1d,
}


def _save(fig: Any, output_dir: Path, stem: str) -> list[dict[str, str]]:
    outputs = []
    for suffix in ("png", "svg", "pdf"):
        path = output_dir / f"{stem}.{suffix}"
        metadata = (
            {"Software": "MoonKVSim"}
            if suffix == "png"
            else {"Creator": "MoonKVSim", "CreationDate": None, "ModDate": None}
            if suffix == "pdf"
            else None
        )
        fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white", metadata=metadata)
        outputs.append({"format": suffix.upper(), "file": path.name, "sha256": _sha256(path)})
    plt.close(fig)
    return outputs


def generate(
    document: Mapping[str, Any],
    *,
    evidence_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    _style()
    output_dir.mkdir(parents=True, exist_ok=False)
    figures = []
    for panel_id, stem in PANEL_STEMS.items():
        figures.append(
            {
                "panel_id": panel_id,
                "stem": stem,
                "outputs": _save(PLOTTERS[panel_id](document), output_dir, stem),
            }
        )
    source = Path(__file__).resolve()
    scientific = _mapping(document["scientific_contract"], "scientific contract")
    body = {
        "schema": "moonkvsim.aegiskv.qwen3_8b.figure1_figures.v1",
        "status": "PASS",
        "figure_count": len(figures),
        "figures": figures,
        "evidence": {
            "path": evidence_path.resolve().as_posix(),
            "sha256": _sha256(evidence_path),
            "fingerprint": document["fingerprint"],
        },
        "generator": {"path": source.as_posix(), "sha256": _sha256(source)},
        "hypothesis": scientific["hypothesis"],
        "population": {"requests": 1_304, "workflows": 160, "failure_seeds": 5},
        "independent_unit": scientific["independent_unit"],
        "held_constants": [
            "Qwen3-8B DP=8 TP=1 PP=1",
            "complete frozen workload without filtering",
            "paired focus request/progress/physical target/outage within seed",
        ],
        "post_treatment_outcomes": [
            "injection timestamp",
            "active victim partition",
            "queued victim partition",
            "reroute-only victim partition",
        ],
        "modeled_uncalibrated": True,
        "physical_execution": False,
        "paper_ready": False,
    }
    manifest = {**body, "fingerprint": fingerprint(body)}
    write_json_atomic(output_dir / "FIGURE_MANIFEST.json", manifest)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    document = _load(args.evidence.resolve())
    manifest = generate(
        document,
        evidence_path=args.evidence.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    print(fingerprint({"status": manifest["status"], "figure_count": manifest["figure_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
