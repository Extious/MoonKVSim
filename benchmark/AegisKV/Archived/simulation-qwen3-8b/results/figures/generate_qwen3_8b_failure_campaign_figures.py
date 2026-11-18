#!/usr/bin/env python3
"""Render paper failure panels only from an accepted Qwen3-8B campaign."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

import matplotlib.pyplot as plt
import numpy as np

from moonkvsim.aegiskv.qwen3_8b_acceptance import (
    canonical_json_bytes,
    fingerprint,
    load_json_strict,
    write_json_atomic,
)
from moonkvsim.aegiskv.qwen3_8b_failure_campaign import (
    SYSTEM_IDS,
    validate_campaign,
)

MOONCAKE, AEGISKV = SYSTEM_IDS
PANEL_STEMS: Final = {
    "FIGURE_3_A": "figure_3a_absolute_wct_by_cohort",
    "FIGURE_3_B": "figure_3b_wct_ecdfs",
    "FIGURE_3_C": "figure_3c_mean_wct_effect",
    "FIGURE_3_D": "figure_3d_p95_wct_effect",
    "FIGURE_4_B": "figure_4b_direct_recovery_composition",
    "FIGURE_4_C": "figure_4c_recompute_recovery_ready",
    "FIGURE_4_D": "figure_4d_selector_prediction_realization",
}
BLUE: Final = "#0072B2"
ORANGE: Final = "#D55E00"
GREEN: Final = "#009E73"
GREY: Final = "#777777"
RED: Final = "#CC3311"
PURPLE: Final = "#6F4C9B"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--acceptance-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--panels",
        nargs="*",
        default=None,
        help="Optional panel IDs; every requested ID must be authorized",
    )
    return parser


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be an array")
    return value


def _configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
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


def _load_acceptance(
    path: Path,
    *,
    campaign_path: Path,
    campaign: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any], list[str]]:
    manifest = _mapping(load_json_strict(path), "acceptance manifest")
    body = {key: value for key, value in manifest.items() if key != "fingerprint"}
    if fingerprint(body) != manifest.get("fingerprint"):
        raise ValueError("acceptance manifest fingerprint mismatch")
    if (
        manifest.get("schema")
        != "moonkvsim.aegiskv.qwen3-8b-acceptance-manifest.v1"
        or manifest.get("status") != "PASS"
    ):
        raise ValueError("figures require one PASS unified acceptance manifest")
    matches = []
    campaign_sha256 = hashlib.sha256(campaign_path.read_bytes()).hexdigest()
    for raw_attempt in _array(manifest.get("attempts"), "acceptance.attempts"):
        attempt = _mapping(raw_attempt, "acceptance.attempts[]")
        reference = attempt.get("artifact")
        if not isinstance(reference, Mapping):
            continue
        if (
            reference.get("sha256") == campaign_sha256
            and reference.get("fingerprint") == campaign.get("fingerprint")
        ):
            matches.append(attempt)
    if len(matches) != 1:
        raise ValueError(
            "acceptance manifest must bind exactly one campaign SHA256+fingerprint"
        )
    attempt = matches[0]
    if (
        _mapping(attempt.get("scenario"), "acceptance scenario").get("kind")
        != "FAILURE_CAMPAIGN"
        or attempt.get("terminal_class") != "VALID"
        or attempt.get("accepted_for_numerical_aggregates") is not True
    ):
        raise ValueError("acceptance attempt is not a VALID failure campaign")
    gates = [
        _mapping(raw_gate, "acceptance.gates[]")
        for raw_gate in _array(attempt.get("gates"), "acceptance.gates")
    ]
    if [gate.get("gate") for gate in gates] != list(range(1, 9)) or any(
        gate.get("status") not in {"PASS", "NOT_APPLICABLE"} for gate in gates
    ):
        raise ValueError("acceptance manifest contains a failed or incomplete gate")
    gate8 = gates[7]
    allowed = list(
        _array(
            _mapping(gate8.get("evidence"), "acceptance Gate 8 evidence").get(
                "allowed_panel_ids"
            ),
            "acceptance Gate 8 allowed_panel_ids",
        )
    )
    attempt_allowed = list(
        _array(attempt.get("allowed_panel_ids"), "acceptance allowed_panel_ids")
    )
    if allowed != attempt_allowed or "FIGURE_4_A" in allowed:
        raise ValueError("acceptance Gate 8 panel authorization is inconsistent")
    return manifest, attempt, allowed


def _seed_rows(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        _mapping(item, "campaign.seeds[]")
        for item in _array(document.get("seeds"), "campaign.seeds")
    ]


def _save(fig: Any, output_dir: Path, stem: str) -> list[dict[str, str]]:
    outputs: list[dict[str, str]] = []
    for suffix in ("png", "svg", "pdf"):
        path = output_dir / f"{stem}.{suffix}"
        metadata = (
            {"Software": "MoonKVSim"}
            if suffix == "png"
            else {"Creator": "MoonKVSim", "CreationDate": None, "ModDate": None}
            if suffix == "pdf"
            else None
        )
        fig.savefig(
            path,
            dpi=300,
            bbox_inches="tight",
            facecolor="white",
            metadata=metadata,
        )
        outputs.append(
            {
                "format": suffix.upper(),
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    plt.close(fig)
    return outputs


def _span_workflow_id(span_id: str, workflow_ids: set[str]) -> str:
    matches = [
        workflow_id
        for workflow_id in workflow_ids
        if span_id == workflow_id
        or span_id.startswith(f"{workflow_id}:")
        or f":{workflow_id}:" in f":{span_id}:"
    ]
    if len(matches) != 1:
        raise ValueError(
            f"span {span_id!r} does not map to exactly one workflow identity"
        )
    return matches[0]


def _cohort_ids(row: Mapping[str, Any]) -> dict[str, set[str]]:
    all_ids = set(
        _mapping(row["workflow_wct_ns"], "workflow_wct_ns")[MOONCAKE]
    )
    focus = _span_workflow_id(
        str(row["causal_contract"]["focus_span_id"]), all_ids
    )
    outcomes = _mapping(
        _mapping(row["causal_contract"], "causal_contract")[
            "realized_outcomes_by_system"
        ],
        "realized_outcomes_by_system",
    )
    impacted = {focus}
    for system_id in SYSTEM_IDS:
        outcome = _mapping(outcomes[system_id], f"outcome.{system_id}")
        for field in ("active_span_ids", "queued_span_ids"):
            impacted.update(
                _span_workflow_id(str(span_id), all_ids)
                for span_id in _array(outcome[field], f"{system_id}.{field}")
            )
    return {
        "whole": all_ids,
        "focus": {focus},
        "impacted_union": impacted,
        "non_focus": all_ids - {focus},
    }


def _plot_3a(document: Mapping[str, Any]) -> Any:
    rows = _seed_rows(document)
    cohorts = ("whole", "focus", "impacted_union", "non_focus")
    labels = ("Whole", "Focus", "Impacted union", "Non-focus")
    x: Any = np.arange(len(cohorts), dtype=float)
    width = 0.36
    fig, ax = plt.subplots(figsize=(8.2, 4.7), constrained_layout=True)
    for offset, system_id, label, color in (
        (-width / 2, MOONCAKE, "Mooncake", BLUE),
        (width / 2, AEGISKV, "AegisKV", ORANGE),
    ):
        means = []
        for cohort in cohorts:
            seed_means = []
            for row in rows:
                ids = _cohort_ids(row)[cohort]
                wct = _mapping(
                    _mapping(row["workflow_wct_ns"], "workflow_wct_ns")[system_id],
                    system_id,
                )
                seed_means.append(
                    sum(float(wct[workflow_id]) for workflow_id in ids)
                    / len(ids)
                    / 1e9
                )
            means.append(float(np.mean(seed_means)))
        ax.bar(x + offset, means, width, label=label, color=color)
        for row in rows:
            values = []
            for cohort in cohorts:
                ids = _cohort_ids(row)[cohort]
                wct = _mapping(
                    _mapping(row["workflow_wct_ns"], "workflow_wct_ns")[system_id],
                    system_id,
                )
                values.append(
                    sum(float(wct[workflow_id]) for workflow_id in ids)
                    / len(ids)
                    / 1e9
                )
            ax.scatter(x + offset, values, color="black", s=10, alpha=0.35)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Absolute mean workflow WCT (s)")
    ax.set_title("Absolute failure WCT by predeclared and descriptive cohorts")
    ax.legend(frameon=False)
    return fig


def _ecdf(values: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    ordered = np.sort(np.asarray(values, dtype=float))
    return ordered, np.arange(1, len(ordered) + 1) / len(ordered)


def _plot_3b(document: Mapping[str, Any]) -> Any:
    rows = _seed_rows(document)
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.2), constrained_layout=True)
    for ax, cohort, title in zip(
        axes, ("whole", "focus"), ("Whole workload", "Focus workflow"), strict=True
    ):
        for system_id, label, color in (
            (MOONCAKE, "Mooncake", BLUE),
            (AEGISKV, "AegisKV", ORANGE),
        ):
            values = []
            for row in rows:
                ids = _cohort_ids(row)[cohort]
                wct = _mapping(
                    _mapping(row["workflow_wct_ns"], "workflow_wct_ns")[system_id],
                    system_id,
                )
                values.extend(float(wct[item]) / 1e9 for item in ids)
            x, y = _ecdf(values)
            ax.step(x, y, where="post", label=label, color=color)
        ax.set_title(title)
        ax.set_xlabel("Workflow WCT (s)")
        ax.set_ylabel("Descriptive ECDF")
    axes[0].legend(frameon=False)
    return fig


def _plot_3c(document: Mapping[str, Any]) -> Any:
    rows = _seed_rows(document)
    values = [
        float(
            _mapping(row["seed_level_estimands_ns"], "estimands")[
                "focus_failure_penalty_did"
            ]
        )
        / 1e9
        for row in rows
    ]
    intervals = _mapping(
        _mapping(document["inference"], "inference")["student_t_95"],
        "student_t_95",
    )
    interval = _mapping(
        intervals["focus_failure_penalty_did"],
        "interval.focus_failure_penalty_did",
    )
    if interval.get("eligible") is not True:
        raise ValueError(
            "focus failure-penalty DiD lacks authorized seed-level Student-t interval"
        )
    mean = float(interval["mean"]) / 1e9
    fig, ax = plt.subplots(figsize=(7.2, 4.3), constrained_layout=True)
    x = np.arange(len(rows), dtype=float)
    ax.scatter(x, values, color=ORANGE, label="paired seed effect")
    ax.errorbar(
        [len(rows)],
        [mean],
        yerr=[
            [mean - float(interval["low"]) / 1e9],
            [float(interval["high"]) / 1e9 - mean],
        ],
        fmt="D",
        color="black",
        capsize=5,
        linewidth=2,
        label="mean ± t 95% CI",
    )
    ax.axhline(0, color=GREY, linewidth=1.2)
    ax.set_xticks([*x, len(rows)], [*[f"seed {row['seed']}" for row in rows], "mean"])
    ax.set_ylabel("Focus failure-penalty DiD (s)")
    ax.set_title("Pre-registered focus-workflow failure effect")
    ax.legend(frameon=False)
    return fig


def _plot_3d(document: Mapping[str, Any]) -> Any:
    rows = _seed_rows(document)
    values = [
        float(
            _mapping(row["seed_level_estimands_ns"], "estimands")[
                "whole_mean_failure_penalty_did"
            ]
        )
        / 1e9
        for row in rows
    ]
    interval = _mapping(
        _mapping(
            _mapping(document["inference"], "inference")["student_t_95"],
            "student_t_95",
        )["whole_mean_failure_penalty_did"],
        "interval.whole_mean_failure_penalty_did",
    )
    mean = float(interval["mean"]) / 1e9
    fig, ax = plt.subplots(figsize=(7.8, 4.5), constrained_layout=True)
    x = np.arange(len(rows), dtype=float)
    ax.scatter(x, values, color=PURPLE)
    for index, row in enumerate(rows):
        ax.annotate(
            f"n={row['workflow_count']}",
            (x[index], values[index]),
            fontsize=6,
        )
    ax.errorbar(
        [len(rows)],
        [mean],
        yerr=[
            [mean - float(interval["low"]) / 1e9],
            [float(interval["high"]) / 1e9 - mean],
        ],
        fmt="D",
        color="black",
        capsize=5,
    )
    ax.axhline(0, color=GREY, linewidth=1.2)
    ax.set_xticks([*x, len(rows)], [*[f"seed {row['seed']}" for row in rows], "mean"])
    ax.set_ylabel("Whole-workload mean failure-penalty DiD (s)")
    ax.set_title("Secondary total-workload failure effect")
    return fig


def _plot_4b(document: Mapping[str, Any]) -> Any:
    rows = _seed_rows(document)
    sources = (
        ("NORMAL_HBM_LOCAL", "Normal HBM", PURPLE),
        ("PEER_HBM", "Peer HBM", GREEN),
        ("STORE_DRAM", "Store DRAM", BLUE),
        ("RECOMPUTE", "Recompute", ORANGE),
    )
    labels = [
        f"s{row['seed']} {system}"
        for row in rows
        for system in ("Mooncake", "AegisKV")
    ]
    fig, ax = plt.subplots(figsize=(10.4, 4.8), constrained_layout=True)
    bottom = np.zeros(len(labels))
    for source, label, color in sources:
        values = []
        for row in rows:
            systems = _mapping(
                _mapping(row["direct_evidence"], "direct")["systems"], "systems"
            )
            for system_id in SYSTEM_IDS:
                tokens = _mapping(
                    _mapping(systems[system_id], system_id)["source_tokens"],
                    "source_tokens",
                )
                prompt = float(_mapping(systems[system_id], system_id)["prompt_tokens"])
                values.append(float(tokens[source]) / prompt)
        array = np.asarray(values)
        ax.bar(labels, array, bottom=bottom, color=color, label=label)
        bottom += array
    ax.set_ylim(0, 1)
    ax.set_ylabel("Focus prompt-token fraction")
    ax.set_title("Direct recovery composition for every seed and system")
    ax.tick_params(axis="x", rotation=45)
    ax.legend(frameon=False, ncol=4)
    return fig


def _plot_4c(document: Mapping[str, Any]) -> Any:
    rows = _seed_rows(document)
    fig, ax = plt.subplots(figsize=(7.6, 4.6), constrained_layout=True)
    for row in rows:
        deltas = _mapping(
            _mapping(row["direct_evidence"], "direct")[
                "paired_deltas_aegiskv_minus_mooncake"
            ],
            "direct deltas",
        )
        x = float(deltas["recompute_tokens"])
        y = float(deltas["recovery_ready_latency_ns"]) / 1e9
        direct_class = str(row["direct_class"])
        color = (
            GREEN
            if direct_class == "DIRECT_RECOVERY_BENEFIT_CONCORDANT"
            else ORANGE
            if direct_class == "DIRECT_RECOVERY_MIXED"
            else GREY
            if direct_class == "SOURCE_SUBSTITUTION_OR_NULL_DIRECT_MECHANISM"
            else RED
        )
        ax.scatter(x, y, s=70, color=color)
        ax.annotate(f"seed {row['seed']}\n{direct_class}", (x, y), fontsize=7)
    ax.axhline(0, color=GREY, linewidth=1)
    ax.axvline(0, color=GREY, linewidth=1)
    ax.set_xlabel("AegisKV - Mooncake recompute tokens")
    ax.set_ylabel("AegisKV - Mooncake recovery-ready (s)")
    ax.set_title("Direct-path classes retain null, mixed, and adverse seeds")
    return fig


def _plot_4d(document: Mapping[str, Any]) -> Any:
    rows = _seed_rows(document)
    labels: list[str] = []
    predicted: list[float] = []
    realized: list[float] = []
    changed: list[bool] = []
    for row in rows:
        selectors = _mapping(row["recovery_selector_evidence"], "selector evidence")
        aegis = _mapping(selectors[AEGISKV], "Aegis selector")
        deltas = _mapping(
            aegis["selected_vs_control_deltas_ns"], "selected_vs_control_deltas"
        )
        labels.append(f"seed {row['seed']}")
        predicted.append(float(deltas["scheduler_completion"]) / 1e9)
        direct = _mapping(
            _mapping(row["direct_evidence"], "direct")[
                "paired_deltas_aegiskv_minus_mooncake"
            ],
            "direct deltas",
        )
        realized.append(float(direct["failure_to_completion_latency_ns"]) / 1e9)
        changed.append(aegis.get("selection_changed") is True)
    x: Any = np.arange(len(rows), dtype=float)
    width = 0.36
    fig, ax = plt.subplots(figsize=(7.8, 4.5), constrained_layout=True)
    ax.bar(
        x - width / 2,
        predicted,
        width,
        color=BLUE,
        label="selected-control predicted",
    )
    ax.bar(
        x + width / 2,
        realized,
        width,
        color=[ORANGE if item else GREY for item in changed],
        label="AegisKV-Mooncake realized completion",
    )
    ax.axhline(0, color=GREY, linewidth=1)
    ax.set_xticks(x, labels)
    ax.set_ylabel("Delta (s)")
    ax.set_title("Selector prediction and realized downstream timing")
    ax.legend(frameon=False)
    return fig


PLOTTERS: Final[dict[str, Callable[[Mapping[str, Any]], Any]]] = {
    "FIGURE_3_A": _plot_3a,
    "FIGURE_3_B": _plot_3b,
    "FIGURE_3_C": _plot_3c,
    "FIGURE_3_D": _plot_3d,
    "FIGURE_4_B": _plot_4b,
    "FIGURE_4_C": _plot_4c,
    "FIGURE_4_D": _plot_4d,
}


def generate(
    document: Mapping[str, Any],
    *,
    campaign_path: Path,
    acceptance_manifest_path: Path,
    output_dir: Path,
    requested_panels: Sequence[str] | None = None,
) -> dict[str, Any]:
    validate_campaign(document)
    acceptance_manifest, accepted_attempt, manifest_allowed = _load_acceptance(
        acceptance_manifest_path,
        campaign_path=campaign_path,
        campaign=document,
    )
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError("output directory must not exist or must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    campaign_allowed = list(
        _mapping(document["acceptance"], "acceptance")["allowed_panel_ids"]
    )
    allowed = [
        panel
        for panel in manifest_allowed
        if panel in campaign_allowed and panel in PLOTTERS
    ]
    requested = allowed if requested_panels is None else list(requested_panels)
    if len(requested) != len(set(requested)):
        raise ValueError("requested panel IDs must be unique")
    unauthorized = [panel for panel in requested if panel not in allowed]
    if unauthorized:
        raise ValueError(f"unauthorized panel request: {', '.join(unauthorized)}")
    unsupported = [panel for panel in requested if panel not in PLOTTERS]
    if unsupported:
        raise ValueError(f"unsupported panel request: {', '.join(unsupported)}")
    _configure_style()
    figures = []
    for panel in requested:
        stem = PANEL_STEMS[panel]
        outputs = _save(PLOTTERS[panel](document), output_dir, stem)
        figures.append({"panel_id": panel, "stem": stem, "outputs": outputs})
    generator = Path(__file__).resolve()
    body: dict[str, Any] = {
        "schema": "moonkvsim.aegiskv.qwen3_8b.failure_campaign_figures.v1",
        "status": "PASS",
        "campaign": {
            "path": campaign_path.resolve().as_posix(),
            "sha256": hashlib.sha256(campaign_path.read_bytes()).hexdigest(),
            "fingerprint": document["fingerprint"],
        },
        "generator": {
            "path": generator.as_posix(),
            "sha256": hashlib.sha256(generator.read_bytes()).hexdigest(),
        },
        "acceptance_manifest": {
            "path": acceptance_manifest_path.resolve().as_posix(),
            "sha256": hashlib.sha256(
                acceptance_manifest_path.read_bytes()
            ).hexdigest(),
            "fingerprint": acceptance_manifest["fingerprint"],
            "attempt_id": accepted_attempt["attempt_id"],
            "attempt_fingerprint": accepted_attempt["fingerprint"],
        },
        "requested_panel_ids": requested,
        "authorized_panel_ids": allowed,
        "omitted_panel_ids": _mapping(document["acceptance"], "acceptance").get(
            "omitted_panel_ids"
        ),
        "figure_count": len(figures),
        "figures": figures,
        "inference": document["inference"],
        "effect_direction_filter_applied": False,
        "modeled_uncalibrated": True,
        "physical_execution": False,
        "paper_ready": False,
    }
    manifest = {**body, "fingerprint": fingerprint(body)}
    write_json_atomic(output_dir / "FIGURE_MANIFEST.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    document = _mapping(load_json_strict(args.campaign.resolve()), "campaign")
    manifest = generate(
        document,
        campaign_path=args.campaign.resolve(),
        acceptance_manifest_path=args.acceptance_manifest.resolve(),
        output_dir=args.output_dir.resolve(),
        requested_panels=args.panels,
    )
    result = {"status": "PASS", "figure_count": manifest["figure_count"]}
    print(canonical_json_bytes(result).decode().strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
