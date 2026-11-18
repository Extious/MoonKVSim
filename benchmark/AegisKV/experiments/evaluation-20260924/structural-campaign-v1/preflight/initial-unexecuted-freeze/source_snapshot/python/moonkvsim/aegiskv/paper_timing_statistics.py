"""Paired policy comparisons under predeclared alternative batching assumptions."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any

from moonkvsim.aegiskv.experiment_statistics import confidence_summary
from moonkvsim.aegiskv.paper_randomization import (
    paired_admission_fingerprint,
    require_distinct_admissions,
)
from moonkvsim.common.hash import sha256_json

TIMING_MODELS = {
    0: ("full", "store_only"),
    500: ("aegiskv_serial_500", "store_only_serial_500"),
    1000: ("aegiskv_serial_1000", "store_only_serial_1000"),
}


def build_timing_statistics(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if sorted(cell["seed"] for cell in cells) != list(range(5)):
        raise ValueError("timing robustness requires exactly five seeds 0 through 4")
    expected_arms = {arm for pair in TIMING_MODELS.values() for arm in pair}
    fingerprints = []
    rows = []
    for cell in sorted(cells, key=lambda value: value["seed"]):
        runs = cell["runs"]
        if set(runs) != {"no_failure", "gpu_failure"} or any(
            set(arms) != expected_arms for arms in runs.values()
        ):
            raise ValueError("timing robustness has missing or extra arms/scenarios")
        all_runs = {f"{scenario}:{arm}": run
                    for scenario, arms in runs.items() for arm, run in arms.items()}
        ids = set(runs["no_failure"]["full"]["wct_ns"])
        if len(ids) != 160 or any(set(run["wct_ns"]) != ids for run in all_runs.values()):
            raise ValueError("timing robustness requires the same 160 workflow IDs")
        fingerprints.append(paired_admission_fingerprint(
            all_runs, seed=cell["seed"], workflow_ids=ids,
        ))
        focus = cell["focus_workflow_id"]
        if focus not in ids:
            raise ValueError("timing robustness focus workflow is absent")
        for beta, (aegis, control) in TIMING_MODELS.items():
            a0, a1 = runs["no_failure"][aegis], runs["gpu_failure"][aegis]
            b0, b1 = runs["no_failure"][control], runs["gpu_failure"][control]
            for run, expected_failure in ((a0, 0), (b0, 0), (a1, 1), (b1, 1)):
                if run["failure_event_count"] != expected_failure:
                    raise ValueError("timing robustness did not execute declared failures")
                if expected_failure:
                    tokens = run["focus_tokens"]
                    if tokens["prompt"] <= 0 or any(value < 0 for value in tokens.values()):
                        raise ValueError("invalid focus recovery token counts")
                    if sum(tokens[k] for k in ("normal", "peer", "store", "recompute")) != (
                        tokens["prompt"]
                    ):
                        raise ValueError("focus recovery does not conserve prompt tokens")
            delta_f0 = {i: a0["wct_ns"][i] - b0["wct_ns"][i] for i in ids}
            delta_f1 = {i: a1["wct_ns"][i] - b1["wct_ns"][i] for i in ids}
            did = {i: delta_f1[i] - delta_f0[i] for i in ids}
            denominator = b0["wct_ns"][focus]
            if denominator <= 0:
                raise ValueError("focus F0 control WCT must be positive")
            rows.append({
                "seed": cell["seed"], "batch_serialization_per_mille": beta,
                "focus_workflow_id": focus,
                "focus_did_ns": did[focus],
                "focus_did_relative_ppb": round(Fraction(did[focus]*10**9, denominator)),
                "whole_mean_did_ns": round(Fraction(sum(did.values()), 160)),
                "whole_f1_mean_delta_ns": round(Fraction(sum(delta_f1.values()), 160)),
                "whole_f0_mean_delta_ns": round(Fraction(sum(delta_f0.values()), 160)),
                "focus_recompute_delta_tokens": (
                    a1["focus_tokens"]["recompute"] - b1["focus_tokens"]["recompute"]
                ),
                "f1_additional_protection_bytes": (
                    a1["protection_transferred_bytes"] - b1["protection_transferred_bytes"]
                ),
            })
    require_distinct_admissions(fingerprints)
    metrics = ("focus_did_ns", "focus_did_relative_ppb", "whole_mean_did_ns",
               "whole_f1_mean_delta_ns", "whole_f0_mean_delta_ns",
               "focus_recompute_delta_tokens", "f1_additional_protection_bytes")
    body = {
        "schema": "moonkvsim.aegiskv.paper-timing-statistics.v1", "status": "PASS",
        "seed_rows": rows,
        "models": {str(beta): {
            metric: confidence_summary([
                row[metric] for row in rows if row["batch_serialization_per_mille"] == beta
            ]) for metric in metrics
        } for beta in TIMING_MODELS},
        "admission_order_sha256_by_seed": fingerprints,
        "sign": "AegisKV minus Store-only; negative completion-time effects favor AegisKV",
        "sampling_unit": "paired_admission_seed_on_one_fixed_workload",
        "physical_execution": False, "effect_direction_gate_applied": False,
    }
    return {**body, "fingerprint": sha256_json(body)}
