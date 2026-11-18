#!/usr/bin/env python3
"""Render exact Qwen3-8B failure-mechanism figures from a bound artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from moonkvsim.common.hash import sha256_json

SCHEMA: Final = "moonkvsim.aegiskv.qwen3_8b.failure_mechanism.v1"
MOONCAKE: Final = "vanilla_mooncake_dram"
AEGISKV: Final = "aegiskv_unified"
SYSTEM_LABELS: Final = {MOONCAKE: "Mooncake", AEGISKV: "AegisKV"}
EXPECTED_STEMS: Final = (
    "figm1_failure_request_phase_decomposition",
    "figm2_recovery_source_timeline",
    "figm3_recovery_token_progress",
    "figm4_latency_phase_distribution",
)
FORBIDDEN_TEXT: Final = (
    "Projected",
    "Simulation projection",
    "No-measured",
)

BLUE: Final = "#0072B2"
ORANGE: Final = "#D55E00"
GREEN: Final = "#009E73"
YELLOW: Final = "#E69F00"
PURPLE: Final = "#6F4C9B"
GREY: Final = "#777777"
LIGHT_GREY: Final = "#B8B8B8"
RED: Final = "#CC3311"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pdf-output-dir", type=Path, required=True)
    return parser


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{where} must be an array")
    return value


def _integer(value: object, where: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{where} must be an integer >= {minimum}")
    return value


def _validate_document(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if document.get("schema") != SCHEMA or document.get("status") != "PASS":
        raise ValueError("figures require a PASS Qwen3-8B failure-mechanism artifact")
    fingerprint = document.get("fingerprint")
    unsigned = dict(document)
    unsigned.pop("fingerprint", None)
    if fingerprint != sha256_json(unsigned):
        raise ValueError("failure-mechanism artifact fingerprint mismatch")
    protocol = _mapping(document.get("protocol"), "protocol")
    if (
        protocol.get("model") != "Qwen/Qwen3-8B"
        or protocol.get("dp") != 8
        or protocol.get("failure_count") != 2
        or protocol.get("workflow_concurrency") != 16
        or protocol.get("repetition") != "A"
        or protocol.get("focus_observation_count") != 4
    ):
        raise ValueError("mechanism artifact protocol mismatch")
    focus_ids = _array(protocol.get("focus_span_ids"), "protocol.focus_span_ids")
    if len(focus_ids) != 2 or len(set(focus_ids)) != 2:
        raise ValueError("mechanism artifact must bind two unique focus spans")
    evidence = _mapping(document.get("evidence"), "evidence")
    if (
        evidence.get("physical_execution") is not False
        or evidence.get("calibrated") is not False
        or evidence.get("paper_ready") is not False
        or evidence.get("observed_values_only") is not True
        or evidence.get("trend_generation_performed") is not False
        or evidence.get("source_windows_parallel_non_additive") is not True
        or evidence.get("exclusive_latency_phases_conserve_failure_to_completion") is not True
    ):
        raise ValueError("mechanism artifact evidence boundary mismatch")
    observations = [
        _mapping(raw, f"observations[{index}]")
        for index, raw in enumerate(_array(document.get("observations"), "observations"))
    ]
    identities = {(item.get("system_id"), item.get("span_id")) for item in observations}
    expected = {(system, span_id) for system in SYSTEM_LABELS for span_id in focus_ids}
    if identities != expected or len(observations) != len(expected):
        raise ValueError("mechanism observations do not form the matched 2x2 focus grid")
    required_phases = {
        "detection_ns",
        "reroute_setup_ns",
        "kv_recall_critical_path_ns",
        "retry_compute_queue_ns",
        "prompt_recompute_ns",
        "silent_replay_queue_ns",
        "silent_replay_ns",
        "activation_resume_gap_ns",
        "resumed_inference_ns",
    }
    for index, observation in enumerate(observations):
        where = f"observations[{index}]"
        phases = _mapping(observation.get("exclusive_latency_phases_ns"), f"{where}.phases")
        if set(phases) != required_phases:
            raise ValueError(f"{where} exclusive phase set mismatch")
        phase_values = [_integer(phases[name], f"{where}.phases.{name}") for name in phases]
        failure_latency = _integer(
            observation.get("failure_to_completion_ns"), f"{where}.failure_to_completion_ns"
        )
        if sum(phase_values) != failure_latency or failure_latency <= 0:
            raise ValueError(f"{where} latency phases do not conserve")
        pre = _mapping(observation.get("pre_failure"), f"{where}.pre_failure")
        elapsed = _integer(pre.get("pre_failure_elapsed_ns"), f"{where}.pre_failure_elapsed_ns")
        active = _integer(
            pre.get("pre_failure_compute_active_ns"), f"{where}.pre_failure_compute_active_ns"
        )
        if active > elapsed:
            raise ValueError(f"{where} pre-failure active compute exceeds elapsed time")
        tokens = _mapping(observation.get("recovery_tokens"), f"{where}.recovery_tokens")
        token_total = sum(
            _integer(tokens.get(name), f"{where}.recovery_tokens.{name}")
            for name in ("normal_hbm_local", "peer_hbm", "store_dram", "prompt_recompute")
        )
        if token_total != _integer(
            tokens.get("total_prompt"), f"{where}.recovery_tokens.total_prompt", minimum=1
        ):
            raise ValueError(f"{where} recovery tokens do not conserve prompt length")
        if observation.get("source_windows_are_parallel_non_additive") is not True:
            raise ValueError(f"{where} does not preserve parallel source-window semantics")
        for interval_index, raw_interval in enumerate(
            _array(observation.get("source_transfer_intervals"), f"{where}.source_intervals")
        ):
            interval = _mapping(raw_interval, f"{where}.source_intervals[{interval_index}]")
            if interval.get("source") not in {"peer_hbm", "store_dram"}:
                raise ValueError(f"{where} has an unknown recovery source")
            ready = _integer(interval.get("ready_ns"), f"{where}.source.ready_ns")
            start = _integer(interval.get("start_ns"), f"{where}.source.start_ns")
            end = _integer(interval.get("end_ns"), f"{where}.source.end_ns")
            if not ready <= start <= end:
                raise ValueError(f"{where} source interval order is invalid")
    if list(document.get("forbidden_figure_labels", [])) != list(FORBIDDEN_TEXT):
        raise ValueError("artifact forbidden-label contract mismatch")
    return observations


def _validate_output_dirs(output_dir: Path, pdf_output_dir: Path) -> None:
    if output_dir.resolve() == pdf_output_dir.resolve():
        raise ValueError("output-dir and pdf-output-dir must be distinct")
    for label, path in (("output-dir", output_dir), ("pdf-output-dir", pdf_output_dir)):
        if path.exists() and not path.is_dir():
            raise ValueError(f"{label} must be a directory")
        if path.exists() and next(path.iterdir(), None) is not None:
            raise ValueError(f"{label} must not exist or must be empty: {path}")


def _configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10.5,
            "axes.labelsize": 11,
            "axes.titlesize": 12,
            "legend.fontsize": 9.5,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "figure.dpi": 150,
            "savefig.transparent": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def _ordered(
    observations: Sequence[Mapping[str, Any]], focus_ids: Sequence[Any]
) -> list[Mapping[str, Any]]:
    index = {str(span_id): position for position, span_id in enumerate(focus_ids)}
    return sorted(
        observations,
        key=lambda item: (index[str(item["span_id"])], 0 if item["system_id"] == MOONCAKE else 1),
    )


def _row_label(observation: Mapping[str, Any], focus_index: Mapping[str, int]) -> str:
    system = SYSTEM_LABELS[str(observation["system_id"])]
    failure_number = focus_index[str(observation["span_id"])] + 1
    return f"{system} - failure {failure_number}"


def _ns_to_s(value: int | float) -> float:
    return float(value) / 1_000_000_000


def _save(fig: Any, stem: str, output_dir: Path, pdf_output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / f"{stem}.png"
    pdf_path = output_dir / f"{stem}.pdf"
    fig.savefig(
        png_path,
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Software": "MoonKVSim"},
    )
    fig.savefig(
        pdf_path,
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
        metadata={"Creator": "MoonKVSim", "CreationDate": None, "ModDate": None},
    )
    shutil.copy2(pdf_path, pdf_output_dir / pdf_path.name)
    plt.close(fig)


def _plot_phase_decomposition(
    observations: Sequence[Mapping[str, Any]],
    focus_ids: Sequence[Any],
    output_dir: Path,
    pdf_output_dir: Path,
) -> None:
    rows = _ordered(observations, focus_ids)
    focus_index = {str(span_id): index for index, span_id in enumerate(focus_ids)}
    y = np.arange(len(rows), dtype=float)
    fig, ax = plt.subplots(figsize=(8.2, 4.45), constrained_layout=True)
    categories = (
        ("detection_routing_retry_ns", "Detection, routing, retry queue", GREY),
        ("kv_recall_critical_path_ns", "KV recall critical path", BLUE),
        ("prompt_recompute_ns", "Prompt recompute", ORANGE),
        ("silent_replay_ns", "Silent replay", PURPLE),
        ("resumed_inference_ns", "Resumed inference", GREEN),
    )
    pre_elapsed = np.asarray(
        [
            -_ns_to_s(
                _integer(
                    _mapping(item["pre_failure"], "pre_failure")["pre_failure_elapsed_ns"],
                    "pre_failure_elapsed_ns",
                )
            )
            for item in rows
        ]
    )
    ax.barh(
        y,
        -pre_elapsed,
        left=pre_elapsed,
        height=0.62,
        color=LIGHT_GREY,
        edgecolor="white",
        hatch="///",
        label="Pre-failure elapsed",
    )
    for row_index, item in enumerate(rows):
        pre = _mapping(item["pre_failure"], "pre_failure")
        active_s = _ns_to_s(
            _integer(pre["pre_failure_compute_active_ns"], "pre_failure_compute_active_ns")
        )
        computed = _integer(
            pre["computed_tokens_at_failure_floor"],
            "computed_tokens_at_failure_floor",
        )
        total = _integer(pre["total_request_tokens"], "total_request_tokens", minimum=1)
        ax.text(
            pre_elapsed[row_index] / 2,
            row_index,
            f"active {active_s:.2f} s; progress floor {computed:,}/{total:,} tok",
            ha="center",
            va="center",
            fontsize=9.2,
            color="#222222",
        )
    left = np.zeros(len(rows), dtype=float)
    for field, label, color in categories:
        if field == "detection_routing_retry_ns":
            values = np.asarray([_ns_to_s(_integer(item[field], field)) for item in rows])
        else:
            values = np.asarray(
                [
                    _ns_to_s(
                        _integer(
                            _mapping(item["exclusive_latency_phases_ns"], "phases")[field],
                            field,
                        )
                    )
                    for item in rows
                ]
            )
        ax.barh(y, values, left=left, height=0.62, color=color, edgecolor="white", label=label)
        left += values
    ax.axvline(0, color="#222222", linewidth=1.3)
    ax.set_yticks(y, [_row_label(item, focus_index) for item in rows])
    ax.invert_yaxis()
    ax.set_xlabel("Time relative to failure (s)")
    ax.set_title("Failure-focus request execution and recovery phases")
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.17),
        ncol=3,
        frameon=False,
    )
    _save(fig, EXPECTED_STEMS[0], output_dir, pdf_output_dir)


def _plot_source_timeline(
    observations: Sequence[Mapping[str, Any]],
    focus_ids: Sequence[Any],
    output_dir: Path,
    pdf_output_dir: Path,
) -> None:
    rows = _ordered(observations, focus_ids)
    focus_index = {str(span_id): index for index, span_id in enumerate(focus_ids)}
    fig, ax = plt.subplots(figsize=(8.2, 4.55), constrained_layout=True)
    y = np.arange(len(rows), dtype=float)
    for row_index, observation in enumerate(rows):
        failure_ns = _integer(observation["failure_at_ns"], "failure_at_ns")
        materialized_ns = _integer(observation["prefix_materialized_ns"], "materialized_ns")
        for raw_interval in _array(observation["source_transfer_intervals"], "source intervals"):
            interval = _mapping(raw_interval, "source interval")
            start = _ns_to_s(_integer(interval["start_ns"], "start_ns") - failure_ns)
            end = _ns_to_s(_integer(interval["end_ns"], "end_ns") - failure_ns)
            source = str(interval["source"])
            color = BLUE if source == "peer_hbm" else YELLOW
            offset = -0.12 if source == "peer_hbm" else 0.12
            ax.plot(
                [start, end],
                [row_index + offset] * 2,
                color=color,
                linewidth=6,
                solid_capstyle="butt",
            )
        for raw_adoption in _array(observation["local_adoptions"], "local adoptions"):
            adoption = _mapping(raw_adoption, "local adoption")
            timestamp = _ns_to_s(
                _integer(adoption["timestamp_ns"], "adoption timestamp") - failure_ns
            )
            source = str(adoption["source"])
            if source == "peer_hbm_local_zero_copy":
                ax.scatter(
                    timestamp,
                    row_index - 0.12,
                    marker="D",
                    s=55,
                    color=GREEN,
                    edgecolor="white",
                    linewidth=0.7,
                    zorder=4,
                )
            else:
                ax.scatter(
                    timestamp,
                    row_index + 0.12,
                    marker="o",
                    s=58,
                    color=PURPLE,
                    edgecolor="white",
                    linewidth=0.7,
                    zorder=4,
                )
        prompt_start = _ns_to_s(
            _integer(observation["prompt_recompute_start_ns"], "prompt_start") - failure_ns
        )
        prompt_end = _ns_to_s(
            _integer(observation["prompt_recompute_complete_ns"], "prompt_end") - failure_ns
        )
        ax.plot(
            [prompt_start, prompt_end],
            [row_index] * 2,
            color=ORANGE,
            linewidth=3,
            alpha=0.8,
            solid_capstyle="butt",
        )
        materialized = _ns_to_s(materialized_ns - failure_ns)
        ax.scatter(
            materialized, row_index, marker="|", s=140, color="#222222", linewidth=1.5, zorder=5
        )
    ax.axvline(0, color="#222222", linewidth=1.2, linestyle="--")
    ax.set_yticks(y, [_row_label(item, focus_index) for item in rows])
    ax.invert_yaxis()
    ax.set_xlabel("Time since failure (s)")
    ax.set_title("Recovery source service windows and prefix materialization")
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    handles = [
        Line2D([0], [0], color=BLUE, linewidth=6, label="Peer-HBM D2D"),
        Line2D([0], [0], color=YELLOW, linewidth=6, label="Store DRAM H2D"),
        Line2D(
            [0],
            [0],
            marker="D",
            color="none",
            markerfacecolor=GREEN,
            markeredgecolor="white",
            markersize=8,
            label="Peer-HBM local reuse",
        ),
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor=PURPLE,
            markeredgecolor="white",
            markersize=8,
            label="Normal-HBM local reuse",
        ),
        Line2D([0], [0], color=ORANGE, linewidth=3, label="Prompt recompute"),
        Line2D(
            [0],
            [0],
            marker="|",
            color="#222222",
            markersize=12,
            linewidth=0,
            label="Prefix materialized",
        ),
    ]
    ax.legend(
        handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3, frameon=False
    )
    _save(fig, EXPECTED_STEMS[1], output_dir, pdf_output_dir)


def _plot_token_progress(
    observations: Sequence[Mapping[str, Any]],
    focus_ids: Sequence[Any],
    output_dir: Path,
    pdf_output_dir: Path,
) -> None:
    rows = _ordered(observations, focus_ids)
    focus_index = {str(span_id): index for index, span_id in enumerate(focus_ids)}
    y = np.arange(len(rows), dtype=float)
    fig, ax = plt.subplots(figsize=(7.8, 4.4), constrained_layout=True)
    sources = (
        ("normal_hbm_local", "Normal HBM reuse", PURPLE),
        ("peer_hbm", "Peer-HBM reuse", GREEN),
        ("store_dram", "Store DRAM reuse", BLUE),
        ("prompt_recompute", "Prompt recompute", ORANGE),
    )
    left = np.zeros(len(rows), dtype=float)
    for field, label, color in sources:
        values = np.asarray(
            [
                float(_integer(_mapping(item["recovery_tokens"], "tokens")[field], field))
                for item in rows
            ]
        )
        ax.barh(y, values, left=left, height=0.62, color=color, edgecolor="white", label=label)
        left += values
    for row_index, total in enumerate(left):
        ax.text(total, row_index, f"  {int(total):,}", va="center", ha="left", fontsize=9.5)
    ax.set_yticks(y, [_row_label(item, focus_index) for item in rows])
    ax.invert_yaxis()
    ax.set_xlabel("Prompt KV tokens after failure")
    ax.set_title("Recovery KV reuse versus prompt recomputation")
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.margins(x=0.12)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, frameon=False)
    _save(fig, EXPECTED_STEMS[2], output_dir, pdf_output_dir)


def _plot_phase_distribution(
    observations: Sequence[Mapping[str, Any]],
    output_dir: Path,
    pdf_output_dir: Path,
) -> None:
    categories = (
        ("detection_routing_retry_ns", "Detect + route\n+ retry queue"),
        ("kv_recall_critical_path_ns", "KV recall\ncritical path"),
        ("prompt_recompute_ns", "Prompt\nrecompute"),
        ("silent_replay_ns", "Silent\nreplay"),
        ("resumed_inference_ns", "Resumed\ninference"),
    )
    fig, ax = plt.subplots(figsize=(7.8, 4.35), constrained_layout=True)
    x = np.arange(len(categories), dtype=float)
    for system_id, color, marker, offset in (
        (MOONCAKE, ORANGE, "o", -0.14),
        (AEGISKV, BLUE, "D", 0.14),
    ):
        system_rows = [item for item in observations if item["system_id"] == system_id]
        if len(system_rows) != 2:
            raise ValueError(f"{system_id} latency distribution lacks two focus observations")
        medians = []
        for category_index, (field, _label) in enumerate(categories):
            values = []
            for item in system_rows:
                source = (
                    item
                    if field == "detection_routing_retry_ns"
                    else _mapping(item["exclusive_latency_phases_ns"], "phases")
                )
                values.append(_ns_to_s(_integer(source[field], field)))
            position = x[category_index] + offset
            point_offsets = (-0.025, 0.025)
            ax.scatter(
                [position + value for value in point_offsets],
                values,
                color=color,
                marker=marker,
                s=48,
                edgecolor="white",
                linewidth=0.7,
                zorder=4,
            )
            low, high = min(values), max(values)
            median = float(np.median(np.asarray(values)))
            medians.append(median)
            ax.vlines(position, low, high, color=color, linewidth=2, alpha=0.8)
            ax.hlines(median, position - 0.07, position + 0.07, color=color, linewidth=3)
        ax.plot(x + offset, medians, color=color, linewidth=1.2, alpha=0.45)
    ax.set_xticks(x, [label for _field, label in categories])
    ax.set_ylabel("Latency per failure-focus request (s)")
    ax.set_title("Failure recovery phase latency across exact focus requests")
    ax.grid(axis="y")
    ax.grid(axis="x", visible=False)
    ax.legend(
        handles=[
            Line2D(
                [0],
                [0],
                marker="o",
                color=ORANGE,
                markerfacecolor=ORANGE,
                linewidth=1.5,
                label="Mooncake",
            ),
            Line2D(
                [0],
                [0],
                marker="D",
                color=BLUE,
                markerfacecolor=BLUE,
                linewidth=1.5,
                label="AegisKV",
            ),
            Patch(facecolor="#FFFFFF", edgecolor="none", label="bar = range; dash = median"),
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=3,
        frameon=False,
    )
    _save(fig, EXPECTED_STEMS[3], output_dir, pdf_output_dir)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(
    *,
    artifact_path: Path,
    document: Mapping[str, Any],
    output_dir: Path,
    pdf_output_dir: Path,
) -> Path:
    figures = []
    for stem in EXPECTED_STEMS:
        png = output_dir / f"{stem}.png"
        pdf = output_dir / f"{stem}.pdf"
        pdf_copy = pdf_output_dir / f"{stem}.pdf"
        if not (png.is_file() and pdf.is_file() and pdf_copy.is_file()):
            raise ValueError(f"missing generated figure artifact for {stem}")
        if _sha256_file(pdf) != _sha256_file(pdf_copy):
            raise ValueError(f"PDF copy hash mismatch for {stem}")
        figures.append(
            {
                "stem": stem,
                "png": {"file": png.name, "sha256": _sha256_file(png)},
                "pdf": {"file": pdf.name, "sha256": _sha256_file(pdf)},
                "pdf_copy": {"file": pdf_copy.name, "sha256": _sha256_file(pdf_copy)},
            }
        )
    generator_path = Path(__file__).resolve()
    body: dict[str, Any] = {
        "schema": "moonkvsim.aegiskv.qwen3_8b.failure_mechanism_figures.v1",
        "status": "PASS",
        "figure_count": len(figures),
        "artifact": {
            "path": artifact_path.resolve().as_posix(),
            "sha256": _sha256_file(artifact_path),
            "fingerprint": document["fingerprint"],
        },
        "generator": {
            "path": generator_path.as_posix(),
            "sha256": _sha256_file(generator_path),
        },
        "evidence": {
            "physical_execution": False,
            "calibrated": False,
            "paper_ready": False,
            "observed_values_only": True,
            "trend_generation_performed": False,
            "source_windows_parallel_non_additive": True,
        },
        "forbidden_label_scan": {
            "strings": list(FORBIDDEN_TEXT),
            "status": "PASS",
        },
        "figures": figures,
    }
    manifest = {**body, "fingerprint": sha256_json(body)}
    path = output_dir / "FIGURE_MANIFEST.json"
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def _scan_forbidden(output_dir: Path) -> None:
    source_text = Path(__file__).read_text(encoding="utf-8")
    # The constants are allowed in the validator, but no rendered title/label may use them.
    for forbidden in FORBIDDEN_TEXT:
        rendered_occurrences = source_text.count(f'"{forbidden}"')
        if rendered_occurrences != 1:
            raise ValueError(f"forbidden figure text appears outside its validator: {forbidden}")
    for path in output_dir.glob("*.pdf"):
        if any(forbidden.lower() in path.name.lower() for forbidden in FORBIDDEN_TEXT):
            raise ValueError(f"forbidden figure text appears in filename: {path.name}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    document = cast(dict[str, Any], json.loads(args.artifact.read_text(encoding="utf-8")))
    observations = _validate_document(document)
    _validate_output_dirs(args.output_dir, args.pdf_output_dir)
    _configure_style()
    focus_ids = list(
        _array(_mapping(document["protocol"], "protocol")["focus_span_ids"], "focus ids")
    )
    _plot_phase_decomposition(observations, focus_ids, args.output_dir, args.pdf_output_dir)
    _plot_source_timeline(observations, focus_ids, args.output_dir, args.pdf_output_dir)
    _plot_token_progress(observations, focus_ids, args.output_dir, args.pdf_output_dir)
    _plot_phase_distribution(observations, args.output_dir, args.pdf_output_dir)
    _scan_forbidden(args.output_dir)
    manifest = _write_manifest(
        artifact_path=args.artifact,
        document=document,
        output_dir=args.output_dir,
        pdf_output_dir=args.pdf_output_dir,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "figure_count": len(EXPECTED_STEMS),
                "manifest": manifest.resolve().as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
