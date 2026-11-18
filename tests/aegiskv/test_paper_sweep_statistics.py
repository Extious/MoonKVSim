from __future__ import annotations

from copy import deepcopy
from itertools import permutations
from typing import Any, cast

import pytest

from moonkvsim.aegiskv.paper_sweep_statistics import (
    AEGISKV,
    MOONCAKE,
    PaperSweepStatisticsError,
    build_paper_sweep_statistics,
)
from moonkvsim.common.hash import sha256_json


def _aimd_events() -> list[dict[str, Any]]:
    return [
        {
            "timestamp_ns": 10,
            "foreground_pressure": True,
            "active_request_count": 4,
            "pressure_resident_primary_count": 3,
            "previous_state": {"target_id": "gpu-0", "protection_fraction": "0.2"},
            "next_state": {"target_id": "gpu-0", "protection_fraction": "0.1"},
        },
        {
            "timestamp_ns": 20,
            "foreground_pressure": False,
            "active_request_count": 2,
            "pressure_resident_primary_count": 1,
            "previous_state": {"target_id": "gpu-0", "protection_fraction": "0.1"},
            "next_state": {"target_id": "gpu-0", "protection_fraction": "0.15"},
        },
    ]


def _focus(*, peer_tokens: int, store_tokens: int) -> list[dict[str, Any]]:
    return [
        {
            "span_id": "span-focus",
            "workflow_id": "workflow-0",
            "recovery_normal_hbm_local_tokens": 1,
            "restored_peer_tokens": peer_tokens,
            "restored_store_tokens": store_tokens,
            "available_normal_hbm_tokens_at_failure": 1,
            "available_peer_tokens_at_failure": peer_tokens,
            "available_store_tokens_at_failure": max(store_tokens, 5),
        }
    ]


def _run(
    wct: dict[str, int],
    *,
    affected_workflow: str,
    aegiskv: bool,
    seed: int,
) -> dict[str, Any]:
    order = list(list(permutations(sorted(wct)))[seed])
    return {
        "workflow_admission": {
            "order_policy": "observed_submit_then_seeded_sha256_workflow_permutation",
            "seed": seed,
            "realized_workflow_order": order,
            "realized_workflow_order_sha256": sha256_json(order),
        },
        "randomization": {"workflow_admission_seed": seed, "peer_binding_seed": 0},
        "metrics": {
            "workflow_completion_time_ns": {"by_workflow_id": wct},
            "workload_end_ns": 30,
        },
        "failure_impacted_spans": [
            {"span_id": f"impacted-{affected_workflow}", "workflow_id": affected_workflow}
        ],
        "failure_focus_spans": _focus(
            peer_tokens=20 + seed if aegiskv else 0,
            store_tokens=5 if aegiskv else 25 + seed,
        ),
        "aimd_events": _aimd_events() if aegiskv else [],
    }


def _cell(seed: int) -> dict[str, Any]:
    mooncake_wct = {
        "workflow-0": 100 + seed,
        "workflow-1": 200 + seed,
        "workflow-2": 300 + seed,
        "workflow-3": 400 + seed,
    }
    aegiskv_wct = {
        "workflow-0": 80 + seed,
        "workflow-1": 200 + seed,
        "workflow-2": 300 + seed,
        "workflow-3": 400 + seed,
    }
    return {
        "cell_id": "failure-2:concurrency-16",
        "failure_count": 2,
        "workflow_concurrency": 16,
        "seed": seed,
        "workload_fingerprint": "frozen-workload-fixture",
        "failure_focus_span_ids_by_system": {
            MOONCAKE: ["span-focus"],
            AEGISKV: ["span-focus"],
        },
        "systems": {
            MOONCAKE: {
                "run": _run(
                    mooncake_wct,
                    affected_workflow="workflow-0",
                    aegiskv=False,
                    seed=seed,
                )
            },
            AEGISKV: {
                "run": _run(
                    aegiskv_wct,
                    affected_workflow="workflow-1",
                    aegiskv=True,
                    seed=seed,
                )
            },
        },
    }


def _cells() -> list[dict[str, Any]]:
    return [_cell(seed) for seed in range(5)]


def _summary_metric(document: dict[str, Any], *path: str) -> dict[str, Any]:
    value: Any = document
    for key in path:
        value = value[key]
    return cast(dict[str, Any], value)


def test_five_seed_statistics_emit_all_requested_paired_metrics() -> None:
    result = build_paper_sweep_statistics(list(reversed(_cells())))

    assert result["status"] == "PASS"
    assert result["cell_identity"] == {"failure_count": 2, "workflow_concurrency": 16}
    contract = cast(dict[str, Any], result["sampling_contract"])
    assert contract["seeds"] == [0, 1, 2, 3, 4]
    assert contract["seed_count"] == 5
    assert contract["interval_method"] == "two_sided_student_t_95_conservative_table"
    assert contract["smoothing_performed"] is False

    whole = _summary_metric(result, "wct_gain", "whole_mean")
    focus = _summary_metric(result, "wct_gain", "failure_focus_mean")
    p95 = _summary_metric(result, "wct_gain", "failure_focus_p95")
    impacted_union = _summary_metric(
        result, "wct_gain", "descriptive_variant_local_impacted_union_mean"
    )
    impacted_union_p95 = _summary_metric(
        result, "wct_gain", "descriptive_variant_local_impacted_union_p95"
    )
    assert whole["per_seed"][0]["exact"] == {"numerator": 2, "denominator": 1}
    assert whole["per_seed"][0]["rounded_value"] == 2_000_000
    assert focus["per_seed"][0]["exact"] == {"numerator": 20, "denominator": 1}
    assert p95["per_seed"][0]["exact"] == {"numerator": 20, "denominator": 1}
    assert impacted_union["per_seed"][0]["exact"] == {
        "numerator": 20,
        "denominator": 3,
    }
    assert impacted_union_p95["per_seed"][0]["exact"] == {
        "numerator": 0,
        "denominator": 1,
    }
    for metric in (whole, focus, p95, impacted_union, impacted_union_p95):
        assert metric["estimate"]["sample_count"] == 5
        assert metric["estimate"]["ci95"]["status"] == "ESTIMATED"
        assert metric["smoothing_performed"] is False
    assert result["wct_gain"]["failure_affected_mean"] == focus
    assert result["wct_gain"]["logical_focus_mean"] == focus
    assert result["wct_gain"]["failure_affected_p95"] == p95

    unaffected = cast(dict[str, Any], result["unaffected_workflow_match"])
    assert unaffected["all_seeds_pass"] is True
    assert unaffected["variant_local_impacted_membership_used"] is False
    assert all(row["pass"] for row in unaffected["per_seed_gate"])
    gates = cast(dict[str, Any], result["paper_gates"])
    base_gate = cast(dict[str, Any], gates["base_failure_focus_p95_gain"])
    assert base_gate["applies"] is True
    assert base_gate["point_estimate_positive"] is True
    assert base_gate["ci95_lower_positive"] is True
    assert base_gate["pass"] is True
    assert gates["all_applicable_pass"] is True
    impact = cast(dict[str, Any], result["failure_impacted_workflow_count"])
    assert impact[MOONCAKE]["per_seed"][0]["rounded_value"] == 1
    assert impact[AEGISKV]["per_seed"][0]["rounded_value"] == 1
    assert impact["union"]["per_seed"][0]["rounded_value"] == 2
    assert impact["logical_focus"]["per_seed"][0]["rounded_value"] == 1
    alpha = cast(dict[str, Any], result["aimd"])
    assert alpha["time_weighted_mean"]["per_seed"][0]["exact"] == {
        "numerator": 3,
        "denominator": 20,
    }
    assert alpha["time_weighted_mean"]["per_seed"][0]["rounded_value"] == 150_000
    assert alpha["range_min"]["per_seed"][0]["rounded_value"] == 100_000
    assert alpha["range_max"]["per_seed"][0]["rounded_value"] == 200_000
    assert alpha["pressure_event_rate"]["per_seed"][0]["rounded_value"] == 50_000_000
    tiers_by_system = cast(dict[str, Any], result["tier_selected_kv_tokens"])
    tiers = tiers_by_system[AEGISKV]
    assert tiers["normal_hbm_local"]["per_seed"][0]["rounded_value"] == 1
    assert tiers["peer_hbm"]["per_seed"][0]["rounded_value"] == 20
    assert tiers["store_dram"]["per_seed"][0]["rounded_value"] == 5
    assert "total" not in tiers
    assert "cross-tier total omitted" in result["tier_selected_aggregation_rule"]
    available = cast(dict[str, Any], result["tier_available_kv_tokens"])[AEGISKV]
    assert available["peer_hbm"]["per_seed"][0]["rounded_value"] == 20
    ecdf = cast(dict[str, Any], result["ecdf_observations"])
    assert len(ecdf["whole_workload"]["per_seed"][0]["wct_ns"][MOONCAKE]) == 4
    assert len(ecdf["failure_focus"]["per_seed"][0]["wct_ns"][AEGISKV]) == 1
    assert ecdf["failure_affected"] == ecdf["failure_focus"]
    assert (
        len(ecdf["variant_local_impacted_union"]["per_seed"][0]["wct_ns"][AEGISKV])
        == 2
    )
    alignment = result["alignment_audit"][0]
    assert alignment["primary_failure_local_selection"] == (
        "pre_frozen_logical_failure_focus_workflow_ids"
    )
    assert alignment["descriptive_impacted_selection"] == (
        "union_of_variant_local_impacted_workflow_ids"
    )
    traces = alpha["observed_trace_by_seed"]
    assert traces[0]["events"][0]["active_request_count"] == 4
    assert result["fingerprint"]


def test_non_exact_seed_cell_count_fails_closed() -> None:
    with pytest.raises(PaperSweepStatisticsError, match="exactly five"):
        build_paper_sweep_statistics(_cells()[:4])
    with pytest.raises(PaperSweepStatisticsError, match="exactly five"):
        build_paper_sweep_statistics([*_cells(), _cell(5)])


def test_non_frozen_seed_vector_fails_closed() -> None:
    cells = _cells()
    cells[-1]["seed"] = 5

    with pytest.raises(PaperSweepStatisticsError, match="exact seed vector"):
        build_paper_sweep_statistics(cells)


def test_duplicate_seed_cell_fails_closed() -> None:
    cells = _cells()
    cells[-1]["seed"] = 0

    with pytest.raises(PaperSweepStatisticsError, match="duplicate seed"):
        build_paper_sweep_statistics(cells)


def test_system_workflow_mismatch_fails_closed() -> None:
    cells = _cells()
    del cells[2]["systems"][AEGISKV]["run"]["metrics"]["workflow_completion_time_ns"][
        "by_workflow_id"
    ]["workflow-3"]

    with pytest.raises(PaperSweepStatisticsError, match="workflow WCT sets are not aligned"):
        build_paper_sweep_statistics(cells)


def test_logical_focus_mismatch_fails_closed() -> None:
    cells = _cells()
    cells[1]["systems"][AEGISKV]["run"]["failure_focus_spans"][0]["span_id"] = "other"

    with pytest.raises(PaperSweepStatisticsError, match="logical focus span sets"):
        build_paper_sweep_statistics(cells)


def test_focus_span_to_workflow_mismatch_fails_closed() -> None:
    cells = _cells()
    cells[3]["systems"][AEGISKV]["run"]["failure_focus_spans"][0]["workflow_id"] = "workflow-1"

    with pytest.raises(PaperSweepStatisticsError, match="maps to different workflows"):
        build_paper_sweep_statistics(cells)


def test_non_focus_gap_diagnostic_does_not_hide_or_reject_observations() -> None:
    cells = _cells()
    for cell in cells:
        wct = cell["systems"][AEGISKV]["run"]["metrics"]["workflow_completion_time_ns"][
            "by_workflow_id"
        ]
        wct["workflow-2"] += 30
        wct["workflow-3"] += 40

    result = build_paper_sweep_statistics(cells)

    assert result["status"] == "PASS"
    assert "NON_FOCUS_MEAN_GAP_EXCEEDS_1_PERCENT" in result[
        "unmet_result_expectations"
    ]
    assert result["paper_gates"]["blocks_artifact_generation"] is False
    unaffected = cast(dict[str, Any], result["unaffected_workflow_match"])
    assert unaffected["all_seeds_pass"] is False
    assert not any(row["pass"] for row in unaffected["per_seed_gate"])
    assert unaffected["metric"]["per_seed"]


def test_variant_local_impacted_union_cannot_remove_a_workflow_from_non_focus_gate() -> None:
    cells = _cells()
    for cell in cells:
        wct = cell["systems"][AEGISKV]["run"]["metrics"][
            "workflow_completion_time_ns"
        ]["by_workflow_id"]
        wct["workflow-1"] += 30

    result = build_paper_sweep_statistics(cells)

    assert result["status"] == "PASS"
    assert "NON_FOCUS_MEAN_GAP_EXCEEDS_1_PERCENT" in result[
        "unmet_result_expectations"
    ]
    non_focus = cast(dict[str, Any], result["non_focus_workflow_match"])
    assert non_focus["variant_local_impacted_membership_used"] is False
    assert non_focus["all_seeds_pass"] is False


def test_base_negative_failure_focus_p95_gain_is_reported_not_rejected() -> None:
    cells = _cells()
    for cell in cells:
        moon_wct = cell["systems"][MOONCAKE]["run"]["metrics"][
            "workflow_completion_time_ns"
        ]["by_workflow_id"]
        aegis_wct = cell["systems"][AEGISKV]["run"]["metrics"][
            "workflow_completion_time_ns"
        ]["by_workflow_id"]
        aegis_wct["workflow-0"] = moon_wct["workflow-0"] + 20

    result = build_paper_sweep_statistics(cells)

    assert result["status"] == "PASS"
    assert result["failed_paper_gates"] == []
    assert result["unmet_result_expectations"] == [
        "BASE_FAILURE_FOCUS_P95_NOT_POSITIVE_SIGNIFICANT_AT_95_PERCENT"
    ]
    gate = result["paper_gates"]["base_failure_focus_p95_gain"]
    assert gate["point_estimate_positive"] is False
    assert gate["ci95_lower_positive"] is False
    assert gate["blocks_artifact_generation"] is False
    assert gate["pass"] is False


def test_base_positive_point_with_ci_crossing_zero_is_reported_not_rejected() -> None:
    cells = _cells()
    for index, cell in enumerate(cells):
        moon_wct = cell["systems"][MOONCAKE]["run"]["metrics"][
            "workflow_completion_time_ns"
        ]["by_workflow_id"]
        aegis_wct = cell["systems"][AEGISKV]["run"]["metrics"][
            "workflow_completion_time_ns"
        ]["by_workflow_id"]
        aegis_wct["workflow-0"] = 50 if index == 0 else moon_wct["workflow-0"]

    result = build_paper_sweep_statistics(cells)

    assert result["status"] == "PASS"
    assert result["failed_paper_gates"] == []
    gate = result["paper_gates"]["base_failure_focus_p95_gain"]
    assert gate["point_estimate_positive"] is True
    assert gate["ci95_lower_positive"] is False
    assert gate["result_interpretation"] == (
        "POSITIVE_POINT_ESTIMATE_CI_CROSSES_ZERO"
    )
    assert gate["pass"] is False


def test_non_base_cell_does_not_enforce_failure_focus_gain_trend() -> None:
    cells = _cells()
    for cell in cells:
        cell["failure_count"] = 1
        moon_wct = cell["systems"][MOONCAKE]["run"]["metrics"][
            "workflow_completion_time_ns"
        ]["by_workflow_id"]
        aegis_wct = cell["systems"][AEGISKV]["run"]["metrics"][
            "workflow_completion_time_ns"
        ]["by_workflow_id"]
        aegis_wct["workflow-0"] = moon_wct["workflow-0"] + 20

    result = build_paper_sweep_statistics(cells)

    assert result["status"] == "PASS"
    gate = result["paper_gates"]["base_failure_focus_p95_gain"]
    assert gate["applies"] is False
    assert gate["status"] == "NOT_APPLICABLE"
    assert gate["pass"] is None


def test_fingerprint_is_canonical_under_input_cell_order() -> None:
    cells = _cells()
    reordered = list(reversed(deepcopy(cells)))

    first = build_paper_sweep_statistics(cells)
    second = build_paper_sweep_statistics(reordered)

    assert first == second
    assert first["fingerprint"] == second["fingerprint"]


def test_discontinuous_aimd_state_fails_closed() -> None:
    cells = _cells()
    cells[0]["systems"][AEGISKV]["run"]["aimd_events"][1]["previous_state"][
        "protection_fraction"
    ] = "0.3"

    with pytest.raises(PaperSweepStatisticsError, match="AIMD state is discontinuous"):
        build_paper_sweep_statistics(cells)


def test_zero_mooncake_normal_hbm_reuse_remains_a_valid_observation() -> None:
    cells = _cells()
    for cell in cells:
        cell["systems"][MOONCAKE]["run"]["failure_focus_spans"][0][
            "recovery_normal_hbm_local_tokens"
        ] = 0

    result = build_paper_sweep_statistics(cells)
    assert result["status"] == "PASS"


def test_relabelled_identical_admission_orders_are_not_independent_seeds() -> None:
    cells = _cells()
    reference = cells[0]["systems"][MOONCAKE]["run"]["workflow_admission"]
    for cell in cells:
        for system in (MOONCAKE, AEGISKV):
            admission = cell["systems"][system]["run"]["workflow_admission"]
            admission["realized_workflow_order"] = reference["realized_workflow_order"]
            admission["realized_workflow_order_sha256"] = reference[
                "realized_workflow_order_sha256"
            ]
    with pytest.raises(PaperSweepStatisticsError, match="distinct realized admission"):
        build_paper_sweep_statistics(cells)


def test_pair_with_different_valid_permutations_is_rejected() -> None:
    cells = _cells()
    admission = cells[0]["systems"][AEGISKV]["run"]["workflow_admission"]
    order = list(reversed(admission["realized_workflow_order"]))
    admission["realized_workflow_order"] = order
    admission["realized_workflow_order_sha256"] = sha256_json(order)
    with pytest.raises(PaperSweepStatisticsError, match="different workflow admission"):
        build_paper_sweep_statistics(cells)


def test_admission_hash_tampering_is_rejected() -> None:
    cells = _cells()
    cells[0]["systems"][AEGISKV]["run"]["workflow_admission"][
        "realized_workflow_order_sha256"
    ] = "0" * 64
    with pytest.raises(PaperSweepStatisticsError, match="fingerprint mismatch"):
        build_paper_sweep_statistics(cells)
