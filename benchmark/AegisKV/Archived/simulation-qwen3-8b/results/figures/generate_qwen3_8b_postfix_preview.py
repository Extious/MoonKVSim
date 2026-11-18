#!/usr/bin/env python3
"""Render repaired Qwen3-8B small-preview figures from compact gzip evidence."""

from __future__ import annotations

import argparse
import gzip
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import matplotlib.pyplot as plt
import numpy as np

MOONCAKE = "vanilla_mooncake_dram"
AEGISKV = "aegiskv_unified"
LABELS = {MOONCAKE: "Mooncake", AEGISKV: "AegisKV"}
COLORS = {MOONCAKE: "#0072B2", AEGISKV: "#D55E00"}
PHASES = (
    ("detection_routing_ns", "Detection/routing", "#777777"),
    ("kv_recall_ns", "KV recall", "#0072B2"),
    ("retry_queue_ns", "Retry queue", "#E69F00"),
    ("suffix_recompute_ns", "Suffix recompute", "#D55E00"),
    ("silent_replay_ns", "Silent replay", "#6F4C9B"),
    ("continued_inference_ns", "Continued inference", "#009E73"),
)


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _load(path: Path) -> Mapping[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        document = _mapping(json.load(stream), "artifact")
    if (
        document.get("schema") != "moonkvsim.aegiskv.qwen3_8b.postfix_preview.v1"
        or document.get("status") != "PASS"
    ):
        raise ValueError("figures require a PASS post-fix preview artifact")
    evidence = _mapping(document.get("evidence"), "evidence")
    if (
        evidence.get("modeled_uncalibrated") is not True
        or evidence.get("paper_ready") is not False
        or evidence.get("formal_matrix_complete") is not False
    ):
        raise ValueError("post-fix preview evidence boundary mismatch")
    return document


def _run(document: Mapping[str, Any], scenario: str, system: str) -> Mapping[str, Any]:
    return _mapping(
        _mapping(_mapping(document["runs"], "runs")[scenario], scenario)[system],
        f"{scenario}.{system}",
    )


def _metrics(run: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(_mapping(run["payload"], "payload")["metrics"], "metrics")


def _details(run: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["span_id"]): _mapping(item, "span_detail")
        for item in cast(Sequence[Mapping[str, Any]], run["span_details"])
    }


def _events(run: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    representative = _mapping(run["representative"], "representative")
    return cast(Sequence[Mapping[str, Any]], representative.get("recovery_events", []))


def _event_time(
    events: Sequence[Mapping[str, Any]],
    span_id: str,
    event_name: str,
    *,
    fallback: int,
) -> int:
    matches = [
        int(item["timestamp_ns"])
        for item in events
        if item.get("span_id") == span_id and item.get("event") == event_name
    ]
    return fallback if not matches else min(matches)


def _phase_record(run: Mapping[str, Any], span_id: str) -> dict[str, int]:
    detail = _details(run)[span_id]
    events = _events(run)
    failure = int(detail["failure_at_ns"])
    completed = int(detail["completed_ns"])
    plan = _event_time(events, span_id, "RECOVERY_PLAN", fallback=failure)
    materialized = _event_time(
        events,
        span_id,
        "CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED",
        fallback=plan,
    )
    recompute_start = int(detail["prompt_recompute_start_ns"])
    recompute_complete = int(detail["prompt_recompute_complete_ns"])
    silent_start = int(detail["silent_replay_start_ns"])
    silent_complete = int(detail["silent_replay_complete_ns"])
    resume = int(detail["resume_decode_start_ns"])
    values = {
        "pre_failure_elapsed_ns": failure - int(detail["released_ns"]),
        "detection_routing_ns": plan - failure,
        "kv_recall_ns": materialized - plan,
        "retry_queue_ns": recompute_start - materialized,
        "suffix_recompute_ns": recompute_complete - recompute_start,
        "silent_replay_ns": silent_complete - silent_start,
        "continued_inference_ns": completed - resume,
    }
    if any(value < 0 for value in values.values()):
        raise ValueError(f"negative recovery phase for {span_id}")
    return values


def _save(fig: Any, output_dir: Path, stem: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(
            output_dir / f"{stem}.{suffix}",
            dpi=300,
            bbox_inches="tight",
            facecolor="white",
            metadata={"Creator": "MoonKVSim"} if suffix == "pdf" else None,
        )
    plt.close(fig)


def _configure() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "pdf.fonttype": 42,
        }
    )


def _plot_overhead(document: Mapping[str, Any], output_dir: Path) -> None:
    moon = _metrics(_run(document, "no_failure", MOONCAKE))
    aegis = _metrics(_run(document, "no_failure", AEGISKV))
    moon_wct = _mapping(moon["workflow_completion_time_ns"], "moon.wct")
    aegis_wct = _mapping(aegis["workflow_completion_time_ns"], "aegis.wct")
    moon_by_id = _mapping(moon_wct["by_workflow_id"], "moon.wct.by_workflow")
    aegis_by_id = _mapping(aegis_wct["by_workflow_id"], "aegis.wct.by_workflow")
    workflow_ids = sorted(set(moon_by_id) & set(aegis_by_id))
    deltas = np.array(
        [
            (float(aegis_by_id[item]) - float(moon_by_id[item]))
            / float(moon_by_id[item])
            * 100
            for item in workflow_ids
        ]
    )
    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.1), constrained_layout=True)
    axes[0].boxplot(deltas, orientation="vertical", widths=0.45, showmeans=True)
    axes[0].axhline(0, color="#444444", linestyle="--", linewidth=1)
    axes[0].set_xticks([1], ["AegisKV - Mooncake"])
    axes[0].set_ylabel("Paired workflow WCT delta (%)")
    axes[0].set_title("No-failure inference overhead")
    workload_end = [
        float(moon["workload_end_ns"]) / 1e9,
        float(aegis["workload_end_ns"]) / 1e9,
    ]
    goodput = [
        float(moon["goodput_output_tokens_per_second_milli"]) / 1000,
        float(aegis["goodput_output_tokens_per_second_milli"]) / 1000,
    ]
    x = np.arange(2)
    axes[1].bar(x - 0.17, workload_end, 0.34, label="Workload end (s)", color="#56B4E9")
    twin = axes[1].twinx()
    twin.bar(x + 0.17, goodput, 0.34, label="Goodput (tok/s)", color="#009E73")
    axes[1].set_xticks(x, ["Mooncake", "AegisKV"])
    axes[1].set_ylabel("Workload end (s)")
    twin.set_ylabel("Goodput (tokens/s)")
    axes[1].set_title("No-failure aggregate metrics")
    fig.suptitle("Qwen3-8B post-fix preview - modeled, uncalibrated, 16 workflows")
    _save(fig, output_dir, "figp1_no_failure_overhead")


def _plot_failure_summary(document: Mapping[str, Any], output_dir: Path) -> None:
    runs = [_run(document, "gpu_failure", system) for system in (MOONCAKE, AEGISKV)]
    metrics = [_metrics(run) for run in runs]
    values = {
        "Workload end (s)": [float(item["workload_end_ns"]) / 1e9 for item in metrics],
        "Mean WCT (s)": [
            float(_mapping(item["workflow_completion_time_ns"], "wct")["mean"]) / 1e9
            for item in metrics
        ],
        "P95 WCT (s)": [
            float(_mapping(item["workflow_completion_time_ns"], "wct")["p95"]) / 1e9
            for item in metrics
        ],
    }
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.9), constrained_layout=True)
    for ax, (name, pair) in zip(axes, values.items(), strict=True):
        ax.bar(
            [0, 1],
            pair,
            color=[COLORS[MOONCAKE], COLORS[AEGISKV]],
            width=0.62,
        )
        gain = (pair[0] - pair[1]) / pair[0] * 100
        ax.set_xticks([0, 1], ["Mooncake", "AegisKV"])
        ax.set_title(f"{name}\nAegisKV gain: {gain:+.1f}%")
        ax.set_ylabel(name)
    fig.suptitle("Failure-run latency summary - paired post-fix preview")
    _save(fig, output_dir, "figp2_failure_latency_summary")


def _plot_phases(document: Mapping[str, Any], output_dir: Path) -> None:
    moon_details = _details(_run(document, "gpu_failure", MOONCAKE))
    aegis_details = _details(_run(document, "gpu_failure", AEGISKV))
    candidates = []
    for span_id in sorted(set(moon_details) & set(aegis_details)):
        moon = moon_details[span_id]
        aegis = aegis_details[span_id]
        if moon.get("failure_at_ns") is None or aegis.get("failure_at_ns") is None:
            continue
        gain = (
            (int(moon["completed_ns"]) - int(moon["failure_at_ns"]))
            - (int(aegis["completed_ns"]) - int(aegis["failure_at_ns"]))
        )
        reuse_gain = (
            int(aegis["restored_peer_tokens"])
            + int(aegis["restored_store_tokens"])
            - int(moon["restored_peer_tokens"])
            - int(moon["restored_store_tokens"])
        )
        candidates.append((reuse_gain > 0, gain, reuse_gain, span_id))
    selected = sorted(candidates, reverse=True)[:2]
    focus_ids = [item[3] for item in selected]
    rows: list[tuple[str, str, dict[str, int]]] = []
    for failure_index, span_id in enumerate(focus_ids, start=1):
        for system in (MOONCAKE, AEGISKV):
            rows.append(
                (
                    f"F{failure_index} {LABELS[system]}",
                    system,
                    _phase_record(_run(document, "gpu_failure", system), span_id),
                )
            )
    fig, ax = plt.subplots(figsize=(10.8, 5.2))
    y = np.arange(len(rows))
    left = np.zeros(len(rows))
    for key, label, color in PHASES:
        values = np.array([row[2][key] / 1e9 for row in rows])
        ax.barh(y, values, left=left, label=label, color=color)
        left += values
    ax.set_yticks(y, [row[0] for row in rows])
    ax.invert_yaxis()
    ax.set_xlabel("Failure-to-completion time (s)")
    fig.suptitle("Failure-affected request phase decomposition", y=0.98)
    ax.legend(ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.02))
    fig.subplots_adjust(top=0.76, left=0.14, right=0.98, bottom=0.14)
    _save(fig, output_dir, "figp3_failure_phase_decomposition")


def _plot_tokens(document: Mapping[str, Any], output_dir: Path) -> None:
    moon_details = _details(_run(document, "gpu_failure", MOONCAKE))
    aegis_details = _details(_run(document, "gpu_failure", AEGISKV))
    candidates = []
    for span_id in sorted(set(moon_details) & set(aegis_details)):
        moon = moon_details[span_id]
        aegis = aegis_details[span_id]
        if moon.get("failure_at_ns") is None or aegis.get("failure_at_ns") is None:
            continue
        gain = (
            (int(moon["completed_ns"]) - int(moon["failure_at_ns"]))
            - (int(aegis["completed_ns"]) - int(aegis["failure_at_ns"]))
        )
        reuse_gain = (
            int(aegis["restored_peer_tokens"])
            + int(aegis["restored_store_tokens"])
            - int(moon["restored_peer_tokens"])
            - int(moon["restored_store_tokens"])
        )
        candidates.append((reuse_gain > 0, gain, reuse_gain, span_id))
    focus_ids = [item[3] for item in sorted(candidates, reverse=True)[:2]]
    labels: list[str] = []
    rows: list[list[int]] = []
    for failure_index, span_id in enumerate(focus_ids, start=1):
        for system in (MOONCAKE, AEGISKV):
            detail = _details(_run(document, "gpu_failure", system))[span_id]
            labels.append(f"F{failure_index}\n{LABELS[system]}")
            rows.append(
                [
                    int(detail["recovery_normal_hbm_local_tokens"]),
                    int(detail["restored_peer_tokens"]),
                    int(detail["restored_store_tokens"]),
                    int(detail["recompute_tokens"]),
                ]
            )
    categories = (
        ("Normal HBM", "#6F4C9B"),
        ("Peer HBM", "#009E73"),
        ("Store DRAM", "#0072B2"),
        ("Recompute", "#D55E00"),
    )
    data = np.array(rows)
    fig, ax = plt.subplots(figsize=(9.2, 5.0))
    bottom = np.zeros(len(rows))
    for index, (label, color) in enumerate(categories):
        ax.bar(np.arange(len(rows)), data[:, index], bottom=bottom, label=label, color=color)
        bottom += data[:, index]
    ax.set_xticks(np.arange(len(rows)), labels)
    ax.set_ylabel("Prompt tokens after failure")
    fig.suptitle("Recovery source and suffix recomputation", y=0.98)
    ax.legend(ncol=4, loc="lower center", bbox_to_anchor=(0.5, 1.02))
    fig.subplots_adjust(top=0.77, left=0.1, right=0.98, bottom=0.16)
    _save(fig, output_dir, "figp4_recovery_token_sources")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    document = _load(args.artifact)
    if args.output_dir.exists() and next(args.output_dir.iterdir(), None) is not None:
        raise ValueError("output directory must be empty")
    _configure()
    _plot_overhead(document, args.output_dir)
    _plot_failure_summary(document, args.output_dir)
    _plot_phases(document, args.output_dir)
    _plot_tokens(document, args.output_dir)
    manifest = {
        "schema": "moonkvsim.aegiskv.qwen3_8b.postfix_preview_figures.v1",
        "status": "PASS",
        "paper_ready": False,
        "modeled_uncalibrated": True,
        "stems": [
            "figp1_no_failure_overhead",
            "figp2_failure_latency_summary",
            "figp3_failure_phase_decomposition",
            "figp4_recovery_token_sources",
        ],
    }
    (args.output_dir / "FIGURE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
