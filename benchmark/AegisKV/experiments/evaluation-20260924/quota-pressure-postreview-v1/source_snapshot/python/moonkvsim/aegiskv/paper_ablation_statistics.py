"""Paired seed-level estimands for a fixed logical F1 ablation experiment."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from moonkvsim.aegiskv.experiment_statistics import confidence_summary
from moonkvsim.aegiskv.paper_randomization import (
    paired_admission_fingerprint,
    require_distinct_admissions,
)
from moonkvsim.common.hash import sha256_json

ARMS = ("full", "no_slack", "lru_eviction", "no_aimd")


def _mean(values: Sequence[int]) -> int:
    # Round only after pairing; ns rounding error is below one nanosecond.
    from fractions import Fraction

    return round(Fraction(sum(values), len(values)))


def build_ablation_statistics(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if sorted(cell["seed"] for cell in cells) != list(range(5)):
        raise ValueError("ablation requires exactly five seeds 0 through 4")
    fingerprints = []
    rows: list[dict[str, Any]] = []
    for cell in sorted(cells, key=lambda value: value["seed"]):
        runs = cell["runs"]
        if set(runs) != {"no_failure", "gpu_failure"}:
            raise ValueError("ablation requires matched F0 and F1 scenarios")
        if any(set(value) != set(ARMS) for value in runs.values()):
            raise ValueError("ablation has missing or extra arms")
        all_runs = {
            f"{scenario}:{arm}": run
            for scenario, arm_runs in runs.items()
            for arm, run in arm_runs.items()
        }
        ids = set(runs["no_failure"]["full"]["wct_ns"])
        if len(ids) != 160 or any(set(run["wct_ns"]) != ids for run in all_runs.values()):
            raise ValueError("ablation workflow population must be the same 160 IDs")
        fingerprints.append(
            paired_admission_fingerprint(
                all_runs,
                seed=cell["seed"],
                workflow_ids=ids,
            )
        )
        focus = cell["focus_workflow_id"]
        if focus not in ids:
            raise ValueError("failure focus workflow is absent")
        full_f0 = runs["no_failure"]["full"]["wct_ns"]
        full_f1 = runs["gpu_failure"]["full"]["wct_ns"]
        for arm in ARMS:
            f0, f1 = runs["no_failure"][arm], runs["gpu_failure"][arm]
            if f0["failure_event_count"] != 0 or f1["failure_event_count"] != 1:
                raise ValueError("ablation did not execute its declared failures")
            token = f1["focus_tokens"]
            if token["prompt"] <= 0 or any(value < 0 for value in token.values()):
                raise ValueError("invalid focus token counts")
            if (
                sum(token[key] for key in ("normal", "peer", "store", "recompute"))
                != token["prompt"]
            ):
                raise ValueError("focus recovery token denominator does not conserve prompt")
            penalty = {key: f1["wct_ns"][key] - f0["wct_ns"][key] for key in ids}
            did = {key: penalty[key] - (full_f1[key] - full_f0[key]) for key in ids}
            rows.append(
                {
                    "seed": cell["seed"],
                    "arm": arm,
                    "focus_penalty_ns": penalty[focus],
                    "focus_did_ns": did[focus],
                    "whole_mean_did_ns": _mean(list(did.values())),
                    "whole_f1_mean_delta_ns": _mean(
                        [f1["wct_ns"][key] - full_f1[key] for key in ids]
                    ),
                    "f0_mean_delta_ns": _mean([f0["wct_ns"][key] - full_f0[key] for key in ids]),
                    "restored_fraction_ppb": round(
                        (token["normal"] + token["peer"] + token["store"])
                        * 1_000_000_000
                        / token["prompt"]
                    ),
                    "focus_tokens": token,
                    "f1_protection_transferred_bytes": f1["protection_transferred_bytes"],
                    "f0_protection_transferred_bytes": f0["protection_transferred_bytes"],
                    "counterexamples": sorted(
                        ({"workflow_id": key, "did_ns": value} for key, value in did.items()),
                        key=lambda item: (-item["did_ns"], item["workflow_id"]),
                    )[:5],
                }
            )
    require_distinct_admissions(fingerprints)
    metric_names = (
        "focus_penalty_ns",
        "focus_did_ns",
        "whole_mean_did_ns",
        "whole_f1_mean_delta_ns",
        "f0_mean_delta_ns",
        "restored_fraction_ppb",
        "f1_protection_transferred_bytes",
        "f0_protection_transferred_bytes",
    )
    body = {
        "schema": "moonkvsim.aegiskv.paper-ablation-statistics.v1",
        "status": "PASS",
        "sampling": {
            "unit": "paired_workflow_admission_seed",
            "seed_count": 5,
            "order_sha256": fingerprints,
            "workflow_count_per_run": 160,
            "effect_direction_gate_applied": False,
            "focus_did": "(arm_F1-arm_F0)-(full_F1-full_F0), same focus workflow",
            "intervention": "same logical span and request progress; natural per-arm GPU",
            "restored_fraction_denominator": (
                "focus prompt tokens; tiers are disjoint selected intervals"
            ),
            "interval_scope": "admission-order variability on this fixed derived workload",
        },
        "seed_rows": rows,
        "arms": {
            arm: {
                name: confidence_summary([row[name] for row in rows if row["arm"] == arm])
                for name in metric_names
            }
            for arm in ARMS
        },
    }
    return {**body, "fingerprint": sha256_json(body)}
