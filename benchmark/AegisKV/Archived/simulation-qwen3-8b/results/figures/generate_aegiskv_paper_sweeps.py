#!/usr/bin/env python3
"""Render Qwen3-8B paper figures from strict multi-seed aggregates only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

import matplotlib.pyplot as plt
import numpy as np

from moonkvsim.aegiskv.paper_sweep_statistics import (
    MINIMUM_SEED_COUNT,
    STATISTICS_SCHEMA,
)
from moonkvsim.aegiskv.qwen3_8b_acceptance import load_json_strict
from moonkvsim.common.hash import sha256_json

SCHEMA: Final = "moonkvsim.aegiskv.paper_sweeps.v4"
MOONCAKE: Final = "vanilla_mooncake_dram"
AEGISKV: Final = "aegiskv_unified"
FAILURE_COUNTS: Final = (1, 2, 4, 8)
WORKFLOW_CONCURRENCIES: Final = (8, 16, 24, 32)
BASE_FAILURE_COUNT: Final = 2
BASE_WORKFLOW_CONCURRENCY: Final = 16
EXPECTED_CELL_IDENTITIES: Final = frozenset(
    {
        *((failure_count, BASE_WORKFLOW_CONCURRENCY) for failure_count in FAILURE_COUNTS),
        *((BASE_FAILURE_COUNT, concurrency) for concurrency in WORKFLOW_CONCURRENCIES),
    }
)
BLUE: Final = "#0072B2"
ORANGE: Final = "#D55E00"
GREEN: Final = "#009E73"
RED: Final = "#CC3311"
PURPLE: Final = "#6F4C9B"
GREY: Final = "#666666"

EXPECTED_FIGURE_STEMS: Final = (
    "fig1a_base_whole_workload_wct_cdf",
    "fig1b_base_failure_focus_wct_cdf",
    "fig2_base_aimd_observed_trace",
    "fig3a_base_failure_kv_selected_ci",
    "fig3b_base_failure_kv_available_ci",
    "fig4_failure_scale_absolute_mean_wct_ci",
    "fig4_failure_scale_affected_workflow_count_ci",
    "fig4_failure_scale_alpha_ci",
    "fig4_failure_scale_focus_mean_gain_ci",
    "fig4_failure_scale_focus_p95_gain_ci",
    "fig4_failure_scale_impacted_union_mean_gain_ci",
    "fig4_failure_scale_pressure_rate_ci",
    "fig4_failure_scale_selected_kv_ci",
    "fig4_failure_scale_whole_mean_gain_ci",
    "fig5_concurrency_scale_absolute_mean_wct_ci",
    "fig5_concurrency_scale_affected_workflow_count_ci",
    "fig5_concurrency_scale_alpha_ci",
    "fig5_concurrency_scale_focus_mean_gain_ci",
    "fig5_concurrency_scale_focus_p95_gain_ci",
    "fig5_concurrency_scale_impacted_union_mean_gain_ci",
    "fig5_concurrency_scale_pressure_rate_ci",
    "fig5_concurrency_scale_selected_kv_ci",
    "fig5_concurrency_scale_whole_mean_gain_ci",
)

_SUMMARY_COMPATIBILITY_PATHS: Final[dict[tuple[str, ...], tuple[tuple[str, ...], ...]]] = {
    ("wct_gain", "failure_focus_mean"): (
        ("wct_gain", "logical_focus_mean"),
        ("wct_gain", "failure_affected_mean"),
    ),
    ("wct_gain", "failure_focus_p95"): (("wct_gain", "failure_affected_p95"),),
    ("wct_gain", "descriptive_variant_local_impacted_union_mean"): (
        ("wct_gain", "failure_affected_mean"),
    ),
    ("wct_gain", "descriptive_variant_local_impacted_union_p95"): (
        ("wct_gain", "failure_affected_p95"),
    ),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--acceptance-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pdf-output-dir", type=Path, required=True)
    return parser


def _object(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be an object")
    return value


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{where} must be an array")
    return value


def _integer(value: object, where: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{where} must be a {qualifier} integer")
    return value


def _validate_document(document: Mapping[str, Any]) -> None:
    if document.get("schema") != SCHEMA or document.get("status") != "PASS":
        raise ValueError("figures require a PASS multi-seed paper-sweep v4 artifact")
    fingerprint = document.get("fingerprint")
    unsigned = dict(document)
    unsigned.pop("fingerprint", None)
    if fingerprint != sha256_json(unsigned):
        raise ValueError("paper-sweep artifact fingerprint mismatch")
    protocol = _object(document.get("protocol"), "protocol")
    seeds = _array(protocol.get("seeds"), "protocol.seeds")
    normalized_seeds = [_integer(seed, "protocol.seeds[]") for seed in seeds]
    normalized_failure_counts = [
        _integer(value, "protocol.failure_counts[]", positive=True)
        for value in _array(protocol.get("failure_counts"), "protocol.failure_counts")
    ]
    normalized_concurrencies = [
        _integer(value, "protocol.workflow_concurrencies[]", positive=True)
        for value in _array(
            protocol.get("workflow_concurrencies"),
            "protocol.workflow_concurrencies",
        )
    ]
    if (
        normalized_seeds != list(range(MINIMUM_SEED_COUNT))
        or protocol.get("seed_count") != MINIMUM_SEED_COUNT
    ):
        raise ValueError("figures require the exact independent seed vector 0,1,2,3,4")
    if (
        _integer(
            protocol.get("base_failure_count"),
            "protocol.base_failure_count",
            positive=True,
        )
        != BASE_FAILURE_COUNT
        or _integer(
            protocol.get("base_workflow_concurrency"),
            "protocol.base_workflow_concurrency",
            positive=True,
        )
        != BASE_WORKFLOW_CONCURRENCY
        or normalized_failure_counts != list(FAILURE_COUNTS)
        or normalized_concurrencies != list(WORKFLOW_CONCURRENCIES)
    ):
        raise ValueError("paper-sweep protocol does not match the required F/C figure grid")
    coverage = _object(protocol.get("context_coverage"), "protocol.context_coverage")
    if coverage.get("observed_128k_coverage") is not False:
        raise ValueError("current figure protocol must not claim observed 128K coverage")
    evidence = _object(document.get("evidence"), "evidence")
    if evidence.get("paper_ready") is not False:
        raise ValueError("modeled uncalibrated artifact cannot claim paper readiness")
    provenance = _object(document.get("provenance"), "provenance")
    workload = _object(provenance.get("workload"), "provenance.workload")
    workload_fingerprint = workload.get("fingerprint")
    cells = _array(document.get("cells"), "cells")
    identities: set[tuple[int, int]] = set()
    for index, raw_cell in enumerate(cells):
        cell = _object(raw_cell, f"cells[{index}]")
        identity = (
            _integer(cell.get("failure_count"), f"cells[{index}].failure_count", positive=True),
            _integer(
                cell.get("workflow_concurrency"),
                f"cells[{index}].workflow_concurrency",
                positive=True,
            ),
        )
        if identity in identities:
            raise ValueError(f"duplicate aggregate cell {identity}")
        identities.add(identity)
        statistics = _object(cell.get("statistics"), f"cells[{index}].statistics")
        if statistics.get("schema") != STATISTICS_SCHEMA:
            raise ValueError(f"aggregate cell {identity} statistics schema mismatch")
        statistics_fingerprint = statistics.get("fingerprint")
        unsigned_statistics = dict(statistics)
        unsigned_statistics.pop("fingerprint", None)
        if statistics_fingerprint != sha256_json(unsigned_statistics):
            raise ValueError(f"aggregate cell {identity} fingerprint mismatch")
        if statistics.get("status") != "PASS":
            raise ValueError(f"aggregate cell {identity} failed a paper gate")
        statistics_identity = _object(
            statistics.get("cell_identity"),
            f"cells[{index}].statistics.cell_identity",
        )
        embedded_identity = (
            _integer(
                statistics_identity.get("failure_count"),
                f"cells[{index}].statistics.cell_identity.failure_count",
                positive=True,
            ),
            _integer(
                statistics_identity.get("workflow_concurrency"),
                f"cells[{index}].statistics.cell_identity.workflow_concurrency",
                positive=True,
            ),
        )
        if embedded_identity != identity:
            raise ValueError(
                f"aggregate cell {identity} does not match statistics identity {embedded_identity}"
            )
        sampling = _object(statistics.get("sampling_contract"), "statistics.sampling_contract")
        if (
            sampling.get("seeds") != normalized_seeds
            or sampling.get("seed_count") != len(normalized_seeds)
            or sampling.get("smoothing_performed") is not False
        ):
            raise ValueError(f"aggregate cell {identity} seed/smoothing contract mismatch")
        statistics_provenance = _object(statistics.get("provenance"), "statistics.provenance")
        if (
            statistics_provenance.get("trend_generation_performed") is not False
            or statistics_provenance.get("observed_values_only") is not True
        ):
            raise ValueError(f"aggregate cell {identity} contains shaped/non-observed data")
        if statistics.get("workload_fingerprint") != workload_fingerprint:
            raise ValueError(f"aggregate cell {identity} workload fingerprint mismatch")
    if identities != EXPECTED_CELL_IDENTITIES:
        missing = sorted(EXPECTED_CELL_IDENTITIES - identities)
        extra = sorted(identities - EXPECTED_CELL_IDENTITIES)
        raise ValueError(f"paper-sweep aggregate grid mismatch: missing={missing}, extra={extra}")


def _validate_acceptance(
    document: Mapping[str, Any],
    *,
    results_path: Path,
    acceptance_path: Path,
) -> list[str]:
    manifest = _object(load_json_strict(acceptance_path), "acceptance manifest")
    if (
        manifest.get("schema")
        != "moonkvsim.aegiskv.qwen3-8b-acceptance-manifest.v1"
        or manifest.get("status") != "PASS"
    ):
        raise ValueError("figures require a PASS unified acceptance manifest")
    unsigned_manifest = dict(manifest)
    claimed_manifest_fingerprint = unsigned_manifest.pop("fingerprint", None)
    if claimed_manifest_fingerprint != sha256_json(unsigned_manifest):
        raise ValueError("acceptance manifest fingerprint mismatch")
    matches: list[Mapping[str, Any]] = []
    for value in _array(manifest.get("attempts"), "acceptance attempts"):
        attempt = _object(value, "acceptance attempt")
        scenario = _object(attempt.get("scenario"), "acceptance attempt scenario")
        artifact = attempt.get("artifact")
        if (
            scenario.get("kind") == "SENSITIVITY_SWEEP"
            and isinstance(artifact, Mapping)
            and artifact.get("fingerprint") == document.get("fingerprint")
        ):
            matches.append(attempt)
    if len(matches) != 1:
        raise ValueError("expected exactly one accepted sensitivity-sweep attempt")
    attempt = matches[0]
    artifact = _object(attempt.get("artifact"), "acceptance attempt artifact")
    if (
        artifact.get("sha256") != _sha256_file(results_path)
        or attempt.get("terminal_class") != "VALID"
        or attempt.get("accepted_for_numerical_aggregates") is not True
    ):
        raise ValueError("sensitivity-sweep artifact is not accepted for figures")
    gates = _array(attempt.get("gates"), "acceptance attempt gates")
    if len(gates) != 8 or [gate.get("gate") for gate in gates] != list(range(1, 9)):
        raise ValueError("sensitivity-sweep acceptance gates are incomplete")
    if any(gate.get("status") not in {"PASS", "NOT_APPLICABLE"} for gate in gates):
        raise ValueError("sensitivity-sweep acceptance contains a failed gate")
    gate8 = _object(gates[7], "acceptance Gate 8")
    gate8_allowed = list(
        _array(
            _object(gate8.get("evidence"), "acceptance Gate 8 evidence").get(
                "allowed_panel_ids"
            ),
            "acceptance Gate 8 allowed panels",
        )
    )
    attempt_allowed = list(
        _array(attempt.get("allowed_panel_ids"), "acceptance allowed panels")
    )
    if gate8_allowed != attempt_allowed:
        raise ValueError("sensitivity-sweep panel authorization is inconsistent")
    if set(attempt_allowed) != {f"FIGURE_5_{letter}" for letter in "ABCDEF"}:
        raise ValueError("acceptance does not authorize the complete Figure 5 panel set")
    return attempt_allowed


def _validate_output_directories(output_dir: Path, pdf_output_dir: Path) -> None:
    if output_dir.resolve() == pdf_output_dir.resolve():
        raise ValueError("output-dir and pdf-output-dir must be distinct")
    for label, path in (("output-dir", output_dir), ("pdf-output-dir", pdf_output_dir)):
        if path.exists() and not path.is_dir():
            raise ValueError(f"{label} must be a directory")
        if path.exists() and next(path.iterdir(), None) is not None:
            raise ValueError(f"{label} must not exist or must be empty: {path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_figure_manifest(output_dir: Path, pdf_output_dir: Path) -> tuple[Path, int]:
    png_by_stem = {path.stem: path for path in output_dir.glob("*.png")}
    pdf_by_stem = {path.stem: path for path in output_dir.glob("*.pdf")}
    pdf_copy_by_stem = {path.stem: path for path in pdf_output_dir.glob("*.pdf")}
    actual_stems = set(png_by_stem)
    expected_stems = set(EXPECTED_FIGURE_STEMS)
    if (
        actual_stems != expected_stems
        or set(pdf_by_stem) != expected_stems
        or set(pdf_copy_by_stem) != expected_stems
    ):
        raise ValueError(
            "generated figure set mismatch: "
            f"expected={sorted(expected_stems)}, png={sorted(png_by_stem)}, "
            f"pdf={sorted(pdf_by_stem)}, pdf_copy={sorted(pdf_copy_by_stem)}"
        )
    figures: list[dict[str, object]] = []
    for stem in sorted(actual_stems):
        png = png_by_stem[stem]
        pdf = pdf_by_stem[stem]
        pdf_copy = pdf_copy_by_stem[stem]
        pdf_sha256 = _sha256_file(pdf)
        pdf_copy_sha256 = _sha256_file(pdf_copy)
        if pdf_sha256 != pdf_copy_sha256:
            raise ValueError(f"PDF copy hash mismatch for {stem}")
        figures.append(
            {
                "stem": stem,
                "png_filename": png.name,
                "png_sha256": _sha256_file(png),
                "pdf_filename": pdf.name,
                "pdf_sha256": pdf_sha256,
                "pdf_output_filename": pdf_copy.name,
                "pdf_output_sha256": pdf_copy_sha256,
            }
        )
    figure_count = len(figures)
    if figure_count != len(EXPECTED_FIGURE_STEMS):
        raise ValueError(f"expected {len(EXPECTED_FIGURE_STEMS)} figures, generated {figure_count}")
    manifest_path = output_dir / "FIGURE_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "moonkvsim.aegiskv.figure_manifest.v1",
                "figure_count": figure_count,
                "figures": figures,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path, figure_count


def _cell(document: Mapping[str, Any], failure_count: int, concurrency: int) -> Mapping[str, Any]:
    matches = [
        _object(item, "cell")
        for item in _array(document["cells"], "cells")
        if item["failure_count"] == failure_count and item["workflow_concurrency"] == concurrency
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one aggregate cell for F={failure_count}, C={concurrency}")
    return matches[0]


def _statistics(cell: Mapping[str, Any]) -> Mapping[str, Any]:
    return _object(cell.get("statistics"), "cell.statistics")


def _summary(cell: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    requested = tuple(path)
    candidates = (requested, *_SUMMARY_COMPATIBILITY_PATHS.get(requested, ()))
    for candidate in candidates:
        current: object = _statistics(cell)
        found = True
        for key in candidate:
            mapping = _object(current, ".".join(candidate))
            if key not in mapping:
                found = False
                break
            current = mapping[key]
        if found:
            return _object(current, ".".join(candidate))
    raise ValueError(f"aggregate summary is missing canonical/compatible path {requested}")


def _summary_point(summary: Mapping[str, Any]) -> tuple[float, float, float]:
    scale = int(summary["integer_scale"])
    estimate = _object(summary.get("estimate"), "summary.estimate")
    mean = float(_object(estimate.get("mean"), "summary.mean")["rounded_half_even"])
    ci = _object(estimate.get("ci95"), "summary.ci95")
    if ci.get("status") != "ESTIMATED":
        raise ValueError("multi-seed figure requires an estimated two-sided 95% CI")
    return mean / scale, float(ci["lower_floor"]) / scale, float(ci["upper_ceiling"]) / scale


def _configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10.5,
            "axes.labelsize": 11,
            "axes.titlesize": 11.5,
            "legend.fontsize": 9.5,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.alpha": 0.25,
            "lines.linewidth": 2.0,
            "figure.dpi": 140,
            "savefig.transparent": False,
        }
    )


def _save(fig: Any, stem: str, output_dir: Path, pdf_output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_output_dir.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "svg", "pdf"):
        path = output_dir / f"{stem}.{extension}"
        fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
        if extension == "pdf":
            shutil.copy2(path, pdf_output_dir / path.name)
    plt.close(fig)


def _ecdf(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ordered = np.sort(values)
    return ordered, np.arange(1, len(ordered) + 1, dtype=float) / len(ordered)


def _pooled_wct(cell: Mapping[str, Any], subset: str, system: str) -> np.ndarray:
    observations = _object(_statistics(cell).get("ecdf_observations"), "ecdf_observations")
    subset_candidates = (subset, "failure_affected") if subset == "failure_focus" else (subset,)
    selected_subset = next(
        (candidate for candidate in subset_candidates if candidate in observations),
        None,
    )
    if selected_subset is None:
        raise ValueError(f"aggregate ECDF is missing canonical/compatible subset {subset}")
    rows = _array(
        _object(observations[selected_subset], selected_subset).get("per_seed"),
        f"{selected_subset}.per_seed",
    )
    values = [
        int(value)
        for raw_row in rows
        for value in _object(_object(raw_row, "ecdf row").get("wct_ns"), "wct_ns")[system]
    ]
    if not values:
        raise ValueError(f"aggregate {subset} ECDF has no observations")
    return np.asarray(values, dtype=float) / 1e9


def _plot_cdf(
    base: Mapping[str, Any],
    *,
    subset: str,
    gain_path: str,
    stem: str,
    x_label: str,
    y_label: str,
    output_dir: Path,
    pdf_output_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(6.8, 4.25), constrained_layout=True)
    for system, label, color, linestyle in (
        (MOONCAKE, "Mooncake", BLUE, "--"),
        (AEGISKV, "AegisKV", ORANGE, "-"),
    ):
        x, y = _ecdf(_pooled_wct(base, subset, system))
        ax.step(x, y, where="post", color=color, linestyle=linestyle, label=label)
    mean, lower, upper = _summary_point(_summary(base, "wct_gain", gain_path))
    seed_count = int(_statistics(base)["sampling_contract"]["seed_count"])
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_xlim(left=0)
    ax.set_ylim(0, 1.02)
    ax.legend(loc="lower right", frameon=False)
    ax.text(
        0.02,
        0.96,
        (
            f"{seed_count} seeds, observed only\n"
            f"Gain: {mean:+.2f}% [95% CI {lower:+.2f}, {upper:+.2f}]"
        ),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9.5,
    )
    _save(fig, stem, output_dir, pdf_output_dir)


def _fraction_value(value: Mapping[str, Any]) -> float:
    return float(value["numerator"]) / float(value["denominator"])


def _plot_aimd_trace(base: Mapping[str, Any], out: Path, pdf_out: Path) -> tuple[int, str]:
    traces = _array(_statistics(base)["aimd"]["observed_trace_by_seed"], "aimd traces")
    first = _object(traces[0], "aimd trace")
    seed = int(first["seed"])
    events = [_object(item, "aimd event") for item in _array(first["events"], "events")]
    pressure_counts = Counter(
        str(event["target_id"]) for event in events if bool(event["foreground_pressure"])
    )
    event_counts = Counter(str(event["target_id"]) for event in events)
    if not event_counts:
        raise ValueError("aggregate contains no AIMD trace events")
    rank = min(event_counts, key=lambda item: (-pressure_counts[item], -event_counts[item], item))
    selected = [event for event in events if event["target_id"] == rank]
    time_seconds = np.asarray([int(event["timestamp_ns"]) for event in selected]) / 1e9
    time_seconds -= time_seconds[0]
    active = np.asarray([int(event["active_request_count"]) for event in selected])
    resident = np.asarray([int(event["pressure_resident_primary_count"]) for event in selected])
    alpha = np.asarray(
        [_fraction_value(_object(event["protection_fraction"], "alpha")) for event in selected]
    )
    pressure = np.asarray([bool(event["foreground_pressure"]) for event in selected])
    fig, left = plt.subplots(figsize=(7.2, 4.3), constrained_layout=True)
    right = left.twinx()
    left.plot(time_seconds, active, color=BLUE, label="Queued + active")
    left.step(time_seconds, resident, where="post", color=PURPLE, linestyle="--", label="Primary")
    right.step(time_seconds, alpha, where="post", color=ORANGE, label="Alpha")
    if pressure.any():
        right.scatter(
            time_seconds[pressure],
            alpha[pressure],
            marker="v",
            s=34,
            color=RED,
            edgecolors="white",
            linewidths=0.5,
            label="Pressure",
        )
    left.set_xlabel("Virtual time since first control event (s)")
    left.set_ylabel("Requests on selected DP rank", color=BLUE)
    right.set_ylabel("Peer-HBM quota fraction, alpha", color=ORANGE)
    right.spines["right"].set_visible(True)
    right.set_ylim(-0.01, 0.52)
    handles = [*left.get_lines(), *right.get_lines(), *right.collections]
    fig.legend(
        handles,
        [str(item.get_label()) for item in handles],
        loc="lower center",
        bbox_to_anchor=(0.55, 1.01),
        ncols=4,
        frameon=False,
    )
    left.set_title(f"Observed seed {seed}, selected rank {rank}", loc="left", pad=8)
    _save(fig, "fig2_base_aimd_observed_trace", out, pdf_out)
    return seed, rank


def _plot_base_tiers(base: Mapping[str, Any], *, available: bool, out: Path, pdf_out: Path) -> None:
    key = "tier_available_kv_tokens" if available else "tier_selected_kv_tokens"
    tiers = ("normal_hbm_local", "peer_hbm", "store_dram")
    labels = ("Normal HBM", "Peer HBM", "Store DRAM")
    colors = (PURPLE, GREEN, BLUE)
    x = np.arange(2)
    width = 0.24
    fig, ax = plt.subplots(figsize=(6.8, 4.2), constrained_layout=True)
    source = _object(_statistics(base).get(key), key)
    for offset, tier, label, color in zip((-width, 0.0, width), tiers, labels, colors, strict=True):
        points = [
            _summary_point(_object(_object(source[system], system)[tier], tier))
            for system in (MOONCAKE, AEGISKV)
        ]
        means = np.asarray([point[0] for point in points])
        errors = np.asarray(
            ([point[0] - point[1] for point in points], [point[2] - point[0] for point in points])
        )
        ax.bar(x + offset, means, width, yerr=errors, capsize=3, label=label, color=color)
    ax.set_xticks(x, ("Mooncake", "AegisKV"))
    ax.set_ylabel("KV tokens (multi-seed mean and 95% CI)")
    ax.set_yscale("symlog", linthresh=128)
    ax.legend(frameon=False, ncols=3, loc="lower center", bbox_to_anchor=(0.5, 1.02))
    stem = (
        "fig3b_base_failure_kv_available_ci" if available else "fig3a_base_failure_kv_selected_ci"
    )
    _save(fig, stem, out, pdf_out)


def _plot_ci_series(
    cells: Sequence[Mapping[str, Any]],
    *,
    x_values: Sequence[int],
    summary_path: tuple[str, ...],
    x_label: str,
    y_label: str,
    stem: str,
    color: str,
    out: Path,
    pdf_out: Path,
    zero_line: bool = False,
) -> None:
    points = [_summary_point(_summary(cell, *summary_path)) for cell in cells]
    means = np.asarray([point[0] for point in points])
    lower = np.asarray([point[1] for point in points])
    upper = np.asarray([point[2] for point in points])
    positions = np.arange(len(x_values))
    fig, ax = plt.subplots(figsize=(6.8, 4.2), constrained_layout=True)
    if zero_line:
        ax.axhline(0, color=GREY, linewidth=1, linestyle="--")
    ax.errorbar(
        positions,
        means,
        yerr=np.vstack((means - lower, upper - means)),
        marker="o",
        capsize=4,
        color=color,
    )
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_xticks(positions, [str(value) for value in x_values])
    for position, value in zip(positions, means, strict=True):
        ax.annotate(
            f"{value:+.2f}",
            (position, value),
            xytext=(0, 7),
            textcoords="offset points",
            ha="center",
            fontsize=8.5,
        )
    _save(fig, stem, out, pdf_out)


def _plot_alpha_scale(
    cells: Sequence[Mapping[str, Any]],
    *,
    x_values: Sequence[int],
    x_label: str,
    stem: str,
    out: Path,
    pdf_out: Path,
) -> None:
    mean_points = [_summary_point(_summary(cell, "aimd", "time_weighted_mean")) for cell in cells]
    range_min = [_summary_point(_summary(cell, "aimd", "range_min"))[0] for cell in cells]
    range_max = [_summary_point(_summary(cell, "aimd", "range_max"))[0] for cell in cells]
    means = np.asarray([point[0] for point in mean_points])
    lower = np.asarray([point[1] for point in mean_points])
    upper = np.asarray([point[2] for point in mean_points])
    positions = np.arange(len(x_values))
    fig, ax = plt.subplots(figsize=(6.8, 4.2), constrained_layout=True)
    ax.fill_between(positions, range_min, range_max, color=BLUE, alpha=0.14, label="Observed range")
    ax.errorbar(
        positions,
        means,
        yerr=np.vstack((means - lower, upper - means)),
        marker="o",
        capsize=4,
        color=BLUE,
        label="Time-weighted mean, 95% CI",
    )
    ax.set_xlabel(x_label)
    ax.set_ylabel("Peer-HBM quota fraction, alpha")
    ax.set_xticks(positions, [str(value) for value in x_values])
    ax.set_ylim(-0.01, 0.52)
    ax.legend(frameon=False)
    _save(fig, stem, out, pdf_out)


def _plot_impacted_workflow_count_scale(
    cells: Sequence[Mapping[str, Any]],
    *,
    x_values: Sequence[int],
    x_label: str,
    stem: str,
    out: Path,
    pdf_out: Path,
) -> None:
    positions = np.arange(len(x_values))
    fig, ax = plt.subplots(figsize=(6.8, 4.2), constrained_layout=True)
    for key, label, color, marker, linestyle in (
        ("union", "Aligned union", RED, "o", "-"),
        (MOONCAKE, "Mooncake", BLUE, "s", "--"),
        (AEGISKV, "AegisKV", ORANGE, "D", "-"),
        ("logical_focus", "Scheduled focus", GREY, "^", ":"),
    ):
        points = [
            _summary_point(_summary(cell, "failure_impacted_workflow_count", key)) for cell in cells
        ]
        means = np.asarray([point[0] for point in points])
        lower = np.asarray([point[1] for point in points])
        upper = np.asarray([point[2] for point in points])
        ax.errorbar(
            positions,
            means,
            yerr=np.vstack((means - lower, upper - means)),
            marker=marker,
            capsize=4,
            color=color,
            linestyle=linestyle,
            label=label,
        )
    ax.set_xlabel(x_label)
    ax.set_ylabel("Failure-impacted workflows")
    ax.set_xticks(positions, [str(value) for value in x_values])
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, ncols=2)
    _save(fig, stem, out, pdf_out)


def _plot_absolute_wct(
    cells: Sequence[Mapping[str, Any]],
    *,
    x_values: Sequence[int],
    x_label: str,
    stem: str,
    out: Path,
    pdf_out: Path,
) -> None:
    positions = np.arange(len(x_values))
    fig, ax = plt.subplots(figsize=(6.8, 4.2), constrained_layout=True)
    for system, label, color, linestyle in (
        (MOONCAKE, "Mooncake", BLUE, "--"),
        (AEGISKV, "AegisKV", ORANGE, "-"),
    ):
        points = [
            _summary_point(_summary(cell, "absolute_mean_wct_ns", "whole", system))
            for cell in cells
        ]
        means = np.asarray([point[0] for point in points]) / 1e9
        lower = np.asarray([point[1] for point in points]) / 1e9
        upper = np.asarray([point[2] for point in points]) / 1e9
        ax.errorbar(
            positions,
            means,
            yerr=np.vstack((means - lower, upper - means)),
            marker="o",
            capsize=4,
            color=color,
            linestyle=linestyle,
            label=label,
        )
    ax.set_xlabel(x_label)
    ax.set_ylabel("Whole-workload mean WCT (s)")
    ax.set_xticks(positions, [str(value) for value in x_values])
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False)
    _save(fig, stem, out, pdf_out)


def _plot_selected_kv_scale(
    cells: Sequence[Mapping[str, Any]],
    *,
    x_values: Sequence[int],
    x_label: str,
    stem: str,
    out: Path,
    pdf_out: Path,
) -> None:
    positions = np.arange(len(x_values))
    fig, ax = plt.subplots(figsize=(6.8, 4.2), constrained_layout=True)
    for tier, label, color, marker in (
        ("normal_hbm_local", "Normal HBM", PURPLE, "s"),
        ("peer_hbm", "Peer HBM", GREEN, "D"),
        ("store_dram", "Store DRAM", BLUE, "o"),
    ):
        points = [
            _summary_point(_summary(cell, "tier_selected_kv_tokens", AEGISKV, tier))
            for cell in cells
        ]
        means = np.asarray([point[0] for point in points]) / 1_000
        lower = np.asarray([point[1] for point in points]) / 1_000
        upper = np.asarray([point[2] for point in points]) / 1_000
        ax.errorbar(
            positions,
            means,
            yerr=np.vstack((means - lower, upper - means)),
            marker=marker,
            capsize=4,
            color=color,
            label=label,
        )
    ax.set_xlabel(x_label)
    ax.set_ylabel("AegisKV selected KV (K tokens)")
    ax.set_xticks(positions, [str(value) for value in x_values])
    ax.set_yscale("symlog", linthresh=0.128)
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, ncols=3)
    _save(fig, stem, out, pdf_out)


def _plot_scale(
    cells: Sequence[Mapping[str, Any]],
    *,
    x_values: Sequence[int],
    x_label: str,
    stem_prefix: str,
    out: Path,
    pdf_out: Path,
) -> None:
    gain_metrics = (
        ("whole_mean", "Whole-workload mean WCT gain (%)", "whole_mean_gain"),
        ("failure_focus_mean", "Failure-focus mean WCT gain (%)", "focus_mean_gain"),
        (
            "descriptive_variant_local_impacted_union_mean",
            "Variant-local impacted-union mean WCT gain (%)",
            "impacted_union_mean_gain",
        ),
        ("failure_focus_p95", "Failure-focus P95 WCT gain (%)", "focus_p95_gain"),
    )
    for metric, y_label, suffix in gain_metrics:
        _plot_ci_series(
            cells,
            x_values=x_values,
            summary_path=("wct_gain", metric),
            x_label=x_label,
            y_label=y_label,
            stem=f"{stem_prefix}_{suffix}_ci",
            color=ORANGE if metric == "whole_mean" else RED,
            out=out,
            pdf_out=pdf_out,
            zero_line=True,
        )
    _plot_alpha_scale(
        cells,
        x_values=x_values,
        x_label=x_label,
        stem=f"{stem_prefix}_alpha_ci",
        out=out,
        pdf_out=pdf_out,
    )
    _plot_ci_series(
        cells,
        x_values=x_values,
        summary_path=("aimd", "pressure_event_rate"),
        x_label=x_label,
        y_label="Pressure events (%)",
        stem=f"{stem_prefix}_pressure_rate_ci",
        color=RED,
        out=out,
        pdf_out=pdf_out,
    )
    _plot_selected_kv_scale(
        cells,
        x_values=x_values,
        x_label=x_label,
        stem=f"{stem_prefix}_selected_kv_ci",
        out=out,
        pdf_out=pdf_out,
    )
    _plot_impacted_workflow_count_scale(
        cells,
        x_values=x_values,
        x_label=x_label,
        stem=f"{stem_prefix}_affected_workflow_count_ci",
        out=out,
        pdf_out=pdf_out,
    )
    _plot_absolute_wct(
        cells,
        x_values=x_values,
        x_label=x_label,
        stem=f"{stem_prefix}_absolute_mean_wct_ci",
        out=out,
        pdf_out=pdf_out,
    )


def _write_data(document: Mapping[str, Any], output_dir: Path, trace_seed: int, rank: str) -> None:
    rows: list[dict[str, object]] = []
    for raw_cell in _array(document["cells"], "cells"):
        cell = _object(raw_cell, "cell")
        row: dict[str, object] = {
            "failure_count": cell["failure_count"],
            "workflow_concurrency": cell["workflow_concurrency"],
        }
        for key, path in (
            ("whole_mean_gain_percent", ("wct_gain", "whole_mean")),
            ("failure_focus_mean_gain_percent", ("wct_gain", "failure_focus_mean")),
            (
                "descriptive_impacted_union_mean_gain_percent",
                ("wct_gain", "descriptive_variant_local_impacted_union_mean"),
            ),
            ("failure_focus_p95_gain_percent", ("wct_gain", "failure_focus_p95")),
            ("alpha_time_weighted_mean", ("aimd", "time_weighted_mean")),
            ("pressure_rate_percent", ("aimd", "pressure_event_rate")),
            (
                "affected_workflow_count_union",
                ("failure_impacted_workflow_count", "union"),
            ),
            (
                "affected_workflow_count_mooncake",
                ("failure_impacted_workflow_count", MOONCAKE),
            ),
            (
                "affected_workflow_count_aegiskv",
                ("failure_impacted_workflow_count", AEGISKV),
            ),
            (
                "scheduled_failure_focus_count",
                ("failure_impacted_workflow_count", "logical_focus"),
            ),
        ):
            mean, lower, upper = _summary_point(_summary(cell, *path))
            row[key] = mean
            row[f"{key}_ci95_lower"] = lower
            row[f"{key}_ci95_upper"] = upper
        rows.append(row)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "figure-data.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "CAPTIONS.md").write_text(
        "\n".join(
            (
                "# Figure captions",
                "",
                "All figures report modeled, uncalibrated Qwen3-8B DP=8 GlobalDES runs.",
                "Every point and CI uses at least five independent seeds; no smoothing,",
                "monotonic fitting, interpolation, or trend shaping is applied.",
                (
                    "Whole-workload and pre-frozen failure-focus ECDFs are separate pooled "
                    "workflow-seed observation views."
                ),
                (
                    f"The AIMD panel shows the unmodified observed trace for seed "
                    f"{trace_seed}, {rank}."
                ),
                "The frozen workload has no observed 128K context (maximum: 86,214 tokens);",
                "the selected highest non-empty failure-focus bucket is 96k.",
                (
                    "Scale metrics are split into independent figures with two-sided "
                    "95% Student-t CIs."
                ),
                "Normal-HBM local reuse, Peer-HBM restore, and Store restore are distinct sources.",
                (
                    "Failure-impacted workflow counts report each variant and their aligned union; "
                    "these are descriptive diagnostics, while the scheduled focus is the primary "
                    "failure-local cohort."
                ),
                "",
            )
        ),
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    document = cast(dict[str, Any], json.loads(args.results.read_text(encoding="utf-8")))
    _validate_document(document)
    allowed_panels = _validate_acceptance(
        document,
        results_path=args.results,
        acceptance_path=args.acceptance_manifest,
    )
    _validate_output_directories(args.output_dir, args.pdf_output_dir)
    _configure_style()
    base = _cell(document, BASE_FAILURE_COUNT, BASE_WORKFLOW_CONCURRENCY)
    _plot_cdf(
        base,
        subset="whole_workload",
        gain_path="whole_mean",
        stem="fig1a_base_whole_workload_wct_cdf",
        x_label="Workflow completion time (s)",
        y_label="Cumulative fraction of workflow-seed observations",
        output_dir=args.output_dir,
        pdf_output_dir=args.pdf_output_dir,
    )
    _plot_cdf(
        base,
        subset="failure_focus",
        gain_path="failure_focus_p95",
        stem="fig1b_base_failure_focus_wct_cdf",
        x_label="Failure-focus workflow completion time (s)",
        y_label="Cumulative fraction of focus workflow-seed observations",
        output_dir=args.output_dir,
        pdf_output_dir=args.pdf_output_dir,
    )
    trace_seed, selected_rank = _plot_aimd_trace(base, args.output_dir, args.pdf_output_dir)
    _plot_base_tiers(base, available=False, out=args.output_dir, pdf_out=args.pdf_output_dir)
    _plot_base_tiers(base, available=True, out=args.output_dir, pdf_out=args.pdf_output_dir)
    failure_values = FAILURE_COUNTS
    _plot_scale(
        [_cell(document, value, BASE_WORKFLOW_CONCURRENCY) for value in failure_values],
        x_values=failure_values,
        x_label="Failures per workload run",
        stem_prefix="fig4_failure_scale",
        out=args.output_dir,
        pdf_out=args.pdf_output_dir,
    )
    concurrency_values = WORKFLOW_CONCURRENCIES
    _plot_scale(
        [_cell(document, BASE_FAILURE_COUNT, value) for value in concurrency_values],
        x_values=concurrency_values,
        x_label="Workflow concurrency",
        stem_prefix="fig5_concurrency_scale",
        out=args.output_dir,
        pdf_out=args.pdf_output_dir,
    )
    _write_data(document, args.output_dir, trace_seed, selected_rank)
    figure_manifest_path, figure_count = _write_figure_manifest(
        args.output_dir, args.pdf_output_dir
    )
    generator_path = Path(__file__).resolve()
    (args.output_dir / "SOURCE_PROVENANCE.json").write_text(
        json.dumps(
            {
                "schema": "moonkvsim.aegiskv.figure_provenance.v4",
                "results_path": args.results.resolve().as_posix(),
                "results_sha256": hashlib.sha256(args.results.read_bytes()).hexdigest(),
                "results_fingerprint": document["fingerprint"],
                "acceptance_manifest_path": args.acceptance_manifest.resolve().as_posix(),
                "acceptance_manifest_sha256": _sha256_file(args.acceptance_manifest),
                "allowed_panel_ids": allowed_panels,
                "generator_path": generator_path.as_posix(),
                "generator_sha256": hashlib.sha256(generator_path.read_bytes()).hexdigest(),
                "figure_manifest_filename": figure_manifest_path.name,
                "figure_manifest_sha256": _sha256_file(figure_manifest_path),
                "figure_count": figure_count,
                "aggregate_only": True,
                "smoothing_performed": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps({"status": "PASS", "figure_count": figure_count, "selected_rank": selected_rank})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
