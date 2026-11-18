#!/usr/bin/env python3
"""Render paper Figure 2 from one accepted five-seed overhead artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import matplotlib.pyplot as plt
import numpy as np

from moonkvsim.common.hash import sha256_json

SCHEMA = "moonkvsim.aegiskv.no-failure-overhead.v1"
MOONCAKE = "vanilla_mooncake_dram"
AEGISKV = "aegiskv_unified"
STEMS = (
    "fig2a_no_failure_wct_by_seed",
    "fig2b_no_failure_system_overhead",
    "fig2c_no_failure_protection_traffic",
    "fig2d_no_failure_cost_effect",
)
PANEL_IDS = (
    "FIGURE_2_A",
    "FIGURE_2_B",
    "FIGURE_2_C",
    "FIGURE_2_D",
)
T_CRITICAL_95_DF4 = 2.7764451051977987


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{where} must be an array")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Mapping[str, Any]:
    document = _mapping(json.loads(path.read_text(encoding="utf-8")), "artifact")
    if document.get("schema") != SCHEMA or document.get("status") != "PASS":
        raise ValueError("figures require one PASS no-failure overhead artifact")
    unsigned = dict(document)
    fingerprint = unsigned.pop("fingerprint", None)
    if fingerprint != sha256_json(unsigned):
        raise ValueError("artifact fingerprint mismatch")
    evidence = _mapping(document.get("evidence"), "evidence")
    if (
        evidence.get("physical_execution") is not False
        or evidence.get("paper_ready") is not False
        or evidence.get("effect_direction_gate_applied") is not False
    ):
        raise ValueError("artifact evidence boundary mismatch")
    protocol = _mapping(document.get("protocol"), "protocol")
    if (
        protocol.get("workflow_count") != 160
        or protocol.get("record_count") != 1304
        or protocol.get("seeds") != [0, 1, 2, 3, 4]
        or protocol.get("peer_binding_seed") != 0
        or protocol.get("scenario") != "no_failure"
    ):
        raise ValueError("artifact protocol mismatch")
    randomization = _mapping(
        protocol.get("workflow_admission_randomization"),
        "protocol.workflow_admission_randomization",
    )
    if (
        randomization.get("policy")
        != "observed_submit_then_seeded_sha256_workflow_permutation"
        or randomization.get("seed_source") != "paired_experiment_seed"
        or randomization.get("paired_systems_share_exact_permutation") is not True
        or randomization.get("peer_placement_held_fixed") is not True
    ):
        raise ValueError("artifact lacks the independent paired admission protocol")
    audit = _mapping(document.get("audit"), "audit")
    checks = _mapping(audit.get("checks"), "audit.checks")
    if (
        audit.get("status") != "PASS"
        or checks.get("seed_changes_realized_workflow_admission_order") is not True
        or checks.get("paired_systems_share_workflow_admission_order") is not True
    ):
        raise ValueError("artifact audit did not pass")
    hashes = []
    for cell in _cells(document):
        systems = _mapping(cell.get("systems"), "cell.systems")
        moon = _mapping(systems.get(MOONCAKE), "cell.systems.mooncake")
        aegis = _mapping(systems.get(AEGISKV), "cell.systems.aegiskv")
        moon_hash = moon.get("workflow_admission_order_sha256")
        if moon_hash != aegis.get("workflow_admission_order_sha256"):
            raise ValueError("paired systems have divergent admission-order hashes")
        hashes.append(moon_hash)
    if len(set(hashes)) != 5:
        raise ValueError("artifact contains deterministic repeats, not five independent seeds")
    return document


def _load_acceptance(
    path: Path,
    *,
    artifact_path: Path,
    artifact: Mapping[str, Any],
) -> Mapping[str, Any]:
    document = _mapping(
        json.loads(path.read_text(encoding="utf-8")),
        "acceptance manifest",
    )
    unsigned = dict(document)
    fingerprint = unsigned.pop("fingerprint", None)
    if fingerprint != sha256_json(unsigned):
        raise ValueError("acceptance manifest fingerprint mismatch")
    if (
        document.get("schema")
        != "moonkvsim.aegiskv.qwen3-8b-acceptance-manifest.v1"
        or document.get("status") != "PASS"
    ):
        raise ValueError("figures require one PASS acceptance manifest")
    matches = []
    for raw_attempt in _array(document.get("attempts"), "acceptance.attempts"):
        attempt = _mapping(raw_attempt, "acceptance.attempts[]")
        reference = attempt.get("artifact")
        if not isinstance(reference, Mapping):
            continue
        if (
            reference.get("fingerprint") == artifact.get("fingerprint")
            and reference.get("sha256") == _sha256(artifact_path)
        ):
            matches.append(attempt)
    if len(matches) != 1:
        raise ValueError("acceptance manifest must bind exactly one input artifact")
    attempt = matches[0]
    if (
        attempt.get("terminal_class") != "VALID"
        or attempt.get("accepted_for_numerical_aggregates") is not True
        or set(_array(attempt.get("allowed_panel_ids"), "allowed_panel_ids"))
        != set(PANEL_IDS)
    ):
        raise ValueError("acceptance manifest does not authorize every Figure 2 panel")
    gates = [
        _mapping(raw_gate, "acceptance.gates[]")
        for raw_gate in _array(attempt.get("gates"), "acceptance.gates")
    ]
    if [gate.get("gate") for gate in gates] != list(range(1, 9)) or any(
        gate.get("status") not in {"PASS", "NOT_APPLICABLE"} for gate in gates
    ):
        raise ValueError("acceptance manifest contains a failed or incomplete gate")
    return document


def _seed_rows(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = [
        _mapping(item, "paired[]")
        for item in _array(document.get("paired"), "paired")
    ]
    if [row.get("seed") for row in rows] != [0, 1, 2, 3, 4]:
        raise ValueError("paired rows must contain ordered seeds 0..4")
    return rows


def _cells(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = [
        _mapping(item, "cells[]")
        for item in _array(document.get("cells"), "cells")
    ]
    if [row.get("seed") for row in rows] != [0, 1, 2, 3, 4]:
        raise ValueError("cells must contain ordered seeds 0..4")
    return rows


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


def _save(fig: Any, output_dir: Path, stem: str) -> None:
    for suffix in ("png", "svg", "pdf"):
        fig.savefig(
            output_dir / f"{stem}.{suffix}",
            dpi=300,
            bbox_inches="tight",
            facecolor="white",
            metadata={"Creator": "MoonKVSim"} if suffix == "pdf" else None,
        )
    plt.close(fig)


def _mean_delta_s(row: Mapping[str, Any], cohort: str | None = None) -> float:
    distribution = _mapping(
        row["wct_delta_ns"]
        if cohort is None
        else _mapping(row["wct_delta_ns_by_cohort"], "cohorts")[cohort],
        "wct distribution",
    )
    return float(distribution["mean"]) / 1e9


def _student_t_95(values: Sequence[float]) -> tuple[float, float, float]:
    if len(values) != 5:
        raise ValueError("Student-t protocol requires exactly five seed values")
    mean = statistics.mean(values)
    half_width = T_CRITICAL_95_DF4 * statistics.stdev(values) / math.sqrt(len(values))
    return mean, mean - half_width, mean + half_width


def _plot_wct(rows: Sequence[Mapping[str, Any]], output_dir: Path) -> None:
    seeds = np.arange(5)
    fig, ax = plt.subplots(figsize=(7.4, 4.3), constrained_layout=True)
    for label, cohort, marker in (
        ("All workflows", None, "o"),
        ("Bootstrap cohort", "bootstrap_initial_admission", "s"),
        ("Steady-state cohort", "steady_state", "^"),
    ):
        values = [_mean_delta_s(row, cohort) for row in rows]
        ax.plot(seeds, values, marker=marker, linewidth=1.6, label=label)
        mean, low, high = _student_t_95(values)
        ax.errorbar(
            [4.35],
            [mean],
            yerr=[[mean - low], [high - mean]],
            marker=marker,
            capsize=4,
            color=ax.lines[-1].get_color(),
        )
    ax.axhline(0, color="black", linewidth=1, linestyle="--")
    ax.set_xticks([*seeds, 4.35], [*map(str, seeds), "mean\n95% CI"])
    ax.set_xlabel("Shared experiment seed")
    ax.set_ylabel("Mean paired workflow WCT delta (s)")
    ax.set_title("No-failure WCT effect by independent seed")
    ax.legend(frameon=False)
    _save(fig, output_dir, STEMS[0])


def _plot_system(rows: Sequence[Mapping[str, Any]], output_dir: Path) -> None:
    makespan = [
        float(_mapping(row["makespan"], "makespan")["aegiskv_overhead_ppm_floor"])
        / 10_000
        for row in rows
    ]
    goodput = [
        float(_mapping(row["goodput"], "goodput")["aegiskv_delta_ppm_floor"])
        / 10_000
        for row in rows
    ]
    x = np.arange(5)
    fig, ax = plt.subplots(figsize=(7.4, 4.3), constrained_layout=True)
    ax.plot(x, makespan, marker="o", label="Makespan overhead")
    ax.plot(x, goodput, marker="s", label="Goodput change")
    for values, marker, line in (
        (makespan, "o", ax.lines[-2]),
        (goodput, "s", ax.lines[-1]),
    ):
        mean, low, high = _student_t_95(values)
        ax.errorbar(
            [4.35],
            [mean],
            yerr=[[mean - low], [high - mean]],
            marker=marker,
            capsize=4,
            color=line.get_color(),
        )
    ax.axhline(0, color="black", linewidth=1, linestyle="--")
    ax.set_xticks([*x, 4.35], [*map(str, x), "mean\n95% CI"])
    ax.set_xlabel("Shared experiment seed")
    ax.set_ylabel("AegisKV relative change (%)")
    ax.set_title("No-failure makespan and goodput")
    ax.legend(frameon=False)
    _save(fig, output_dir, STEMS[1])


def _plot_traffic(cells: Sequence[Mapping[str, Any]], output_dir: Path) -> None:
    submitted: dict[str, dict[str, list[float]]] = {
        system: {"bootstrap_warmup": [], "steady_state": []}
        for system in (MOONCAKE, AEGISKV)
    }
    aborted: dict[str, list[float]] = {MOONCAKE: [], AEGISKV: []}
    for cell in cells:
        systems = _mapping(cell["systems"], "systems")
        for system in submitted:
            protection = _mapping(
                _mapping(systems[system], system)["protection"],
                "protection",
            )
            phases = _mapping(protection["by_time_phase"], "protection.by_time_phase")
            for phase in submitted[system]:
                submitted[system][phase].append(
                    float(_mapping(phases[phase], phase)["submitted_bytes"]) / 1024**3
                )
            aborted[system].append(float(protection["aborted_bytes"]) / 1024**3)
    x = np.arange(5)
    fig, ax = plt.subplots(figsize=(7.4, 4.3), constrained_layout=True)
    width = 0.36
    for system, offset, label in (
        (MOONCAKE, -width / 2, "Mooncake Store-only"),
        (AEGISKV, width / 2, "AegisKV Peer + Store"),
    ):
        bootstrap = submitted[system]["bootstrap_warmup"]
        steady = submitted[system]["steady_state"]
        bars = ax.bar(x + offset, bootstrap, width, label=f"{label}: bootstrap")
        ax.bar(
            x + offset,
            steady,
            width,
            bottom=bootstrap,
            label=f"{label}: steady",
            alpha=0.55,
            color=bars.patches[0].get_facecolor(),
        )
        ax.scatter(
            x + offset,
            aborted[system],
            marker="x",
            label=f"{label}: aborted total",
        )
    ax.set_xticks(x)
    ax.set_xlabel("Shared experiment seed")
    ax.set_ylabel("Protection traffic (GiB/run)")
    ax.set_title("No-failure submitted traffic by phase and total aborted bytes")
    ax.legend(frameon=False, fontsize=8, ncol=2)
    _save(fig, output_dir, STEMS[2])


def _plot_cost_effect(
    rows: Sequence[Mapping[str, Any]],
    cells: Sequence[Mapping[str, Any]],
    output_dir: Path,
) -> None:
    traffic_delta: list[float] = []
    wct_delta = [_mean_delta_s(row, "steady_state") for row in rows]
    for cell in cells:
        systems = _mapping(cell["systems"], "systems")
        moon = _mapping(_mapping(systems[MOONCAKE], MOONCAKE)["protection"], "moon")
        aegis = _mapping(_mapping(systems[AEGISKV], AEGISKV)["protection"], "aegis")
        traffic_delta.append(
            (float(aegis["submitted_bytes"]) - float(moon["submitted_bytes"]))
            / 1024**3
        )
    fig, ax = plt.subplots(figsize=(7.1, 4.5), constrained_layout=True)
    ax.axhline(0, color="black", linewidth=1, linestyle="--")
    for seed, (x, y) in enumerate(zip(traffic_delta, wct_delta, strict=True)):
        ax.scatter(x, y, s=55)
        ax.annotate(f"seed {seed}", (x, y), xytext=(5, 5), textcoords="offset points")
    ax.set_xlabel("Incremental AegisKV protection traffic (GiB/run)")
    ax.set_ylabel("Steady-state mean paired workflow WCT delta (s)")
    ax.set_title("Incremental protection cost versus steady-state WCT effect")
    _save(fig, output_dir, STEMS[3])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--acceptance-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists() and next(args.output_dir.iterdir(), None) is not None:
        raise ValueError("output directory must be absent or empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    document = _load(args.artifact)
    acceptance = _load_acceptance(
        args.acceptance_manifest,
        artifact_path=args.artifact,
        artifact=document,
    )
    rows = _seed_rows(document)
    cells = _cells(document)
    _configure()
    _plot_wct(rows, args.output_dir)
    _plot_system(rows, args.output_dir)
    _plot_traffic(cells, args.output_dir)
    _plot_cost_effect(rows, cells, args.output_dir)
    figures = []
    for stem in STEMS:
        files = {}
        for suffix in ("png", "svg", "pdf"):
            path = args.output_dir / f"{stem}.{suffix}"
            if not path.is_file():
                raise ValueError(f"missing generated {suffix} for {stem}")
            files[suffix] = {"file": path.name, "sha256": _sha256(path)}
        figures.append({"stem": stem, "files": files})
    body = {
        "schema": "moonkvsim.aegiskv.qwen3_8b.no_failure_figures.v1",
        "status": "PASS",
        "artifact": {
            "file": args.artifact.resolve().as_posix(),
            "sha256": _sha256(args.artifact),
            "fingerprint": document["fingerprint"],
        },
        "acceptance_manifest": {
            "file": args.acceptance_manifest.resolve().as_posix(),
            "sha256": _sha256(args.acceptance_manifest),
            "fingerprint": acceptance["fingerprint"],
            "authorized_panel_ids": list(PANEL_IDS),
        },
        "generator_sha256": _sha256(Path(__file__).resolve()),
        "figure_count": len(figures),
        "figures": figures,
        "statistics": {
            "independent_unit": "shared_experiment_seed",
            "seed_count": 5,
            "interval": "two_sided_student_t_95_percent_df4",
            "t_critical": T_CRITICAL_95_DF4,
            "seed_randomization_verified_from_distinct_realized_admission_order_hashes": True,
            "workflow_values_are_descriptive_not_independent_replicates": True,
            "all_seed_points_rendered": True,
            "smoothing_performed": False,
            "effect_direction_gate_applied": False,
        },
        "evidence": {
            "modeled_uncalibrated": True,
            "physical_execution": False,
            "paper_ready": False,
        },
    }
    manifest = {**body, "fingerprint": sha256_json(body)}
    manifest_path = args.output_dir / "FIGURE_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "manifest": str(manifest_path.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
