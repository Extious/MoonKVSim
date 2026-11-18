from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from moonkvsim.aegiskv import qwen3_8b_acceptance as acceptance


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(acceptance.canonical_json_bytes(value))


def _signed(body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "fingerprint": acceptance.fingerprint(body)}


def _system(seed: int, variant_id: str, *, distinct_orders: bool = True) -> dict[str, Any]:
    workflow_ids = [f"workflow-{index:03d}" for index in range(160)]
    rotation = seed if distinct_orders else 0
    order = workflow_ids[rotation:] + workflow_ids[:rotation]
    offset = 10 if variant_id == "aegiskv_unified" else 0
    return {
        "variant_id": variant_id,
        "payload_sha256": "1" * 64,
        "journal_sha256": f"{seed + 2:064x}",
        "span_details_sha256": f"{seed + 3:064x}",
        "representative_sha256": "4" * 64,
        "workflow_wct_ns": {
            workflow_id: 1_000 + index + offset
            for index, workflow_id in enumerate(workflow_ids)
        },
        "workflow_admission_order": order,
        "workflow_admission_order_sha256": acceptance.fingerprint(order),
        "warmup": {"warmup_end_ns": 100},
        "protection": {
            "transfer_count": 1 if variant_id == "aegiskv_unified" else 0,
            "terminal_state_counts": (
                {"COMMITTED": 1} if variant_id == "aegiskv_unified" else {}
            ),
            "submitted_bytes": 100 if variant_id == "aegiskv_unified" else 0,
            "transferred_bytes": 100 if variant_id == "aegiskv_unified" else 0,
            "aborted_bytes": 0,
            "by_time_phase": {
                "bootstrap_warmup": {
                    "transfer_count": 1 if variant_id == "aegiskv_unified" else 0,
                    "submitted_bytes": 100 if variant_id == "aegiskv_unified" else 0,
                },
                "steady_state": {"transfer_count": 0, "submitted_bytes": 0},
            },
        },
        "algorithm2": {
            "event_count": 1 if variant_id == "aegiskv_unified" else 0,
            "preview_count": 1 if variant_id == "aegiskv_unified" else 0,
            "event_counts_by_kind": (
                {"FORMAL_ALGORITHM2_PREVIEW": 1}
                if variant_id == "aegiskv_unified"
                else {}
            ),
        },
        "algorithm3": {
            "event_count": 1 if variant_id == "aegiskv_unified" else 0,
            "action_counts": (
                {"STABLE_WINDOW": 1} if variant_id == "aegiskv_unified" else {}
            ),
        },
        "raw_artifact": {
            "path": f"raw/seed-{seed}/{variant_id}.json",
            "sha256": "5" * 64,
            "schema": acceptance.EXPECTED_RAW_SCHEMA,
        },
    }


def _aggregate(*, distinct_orders: bool = True, seed_count: int = 5) -> dict[str, Any]:
    cells = []
    for seed in range(seed_count):
        cells.append(
            {
                "seed": seed,
                "systems": {
                    variant: _system(seed, variant, distinct_orders=distinct_orders)
                    for variant in acceptance.SYSTEM_IDS
                },
            }
        )
    return _signed(
        {
            "schema": acceptance.EXPECTED_AGGREGATE_SCHEMA,
            "status": "PASS",
            "protocol": {
                "scenario": "no_failure",
                "workflow_count": 160,
                "record_count": 1304,
                "workflow_filtering": False,
            },
            "provenance": {
                "source_contract": {},
                "config_binding": {},
                "workload_binding": {},
            },
            "cells": cells,
        }
    )


def _registry(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    return _signed({"schema": acceptance.REGISTRY_SCHEMA, "attempts": attempts})


def _direct_classifier(
    aggregate_fingerprint: str,
    *,
    classification: str = "DIRECT_RECOVERY_BENEFIT_CONCORDANT",
    causal_check_status: str = "PASS",
    effect_direction_gate_applied: bool = False,
    all_cells_retained: bool = True,
) -> dict[str, Any]:
    focus_span_id = "workflow-000:span-000"
    matched_evidence = {
        "focus_span_id": focus_span_id,
        "target_gpu_id": "gpu-3",
        "target_workload_progress_per_mille": 600,
        "outage_duration_ns": 120_000_000_000,
        "realized_outcomes_by_system": {
            system_id: {
                "injection_timestamp_ns": 42_000 + index,
                "active_span_ids": [focus_span_id],
                "queued_span_ids": ["workflow-001:span-000"],
                "reroute_only_queued_span_ids": [],
            }
            for index, system_id in enumerate(acceptance.SYSTEM_IDS)
        },
    }
    checks = [
        {"check": "INPUT_STATUS_PASS", "status": "PASS", "evidence": "PASS"},
        {
            "check": "INPUT_SELF_FINGERPRINT",
            "status": "PASS",
            "evidence": aggregate_fingerprint,
        },
        {"check": "PAPER_CAUSAL_MODE", "status": "PASS", "evidence": True},
        {
            "check": "EXACTLY_ONE_FOCUS_SPAN",
            "status": "PASS",
            "evidence": focus_span_id,
        },
        {
            "check": "MATCHED_SINGLE_FAILURE_SCHEDULE",
            "status": causal_check_status,
            "evidence": "6" * 64,
        },
        {"check": "FROZEN_PHYSICAL_TARGET", "status": "PASS", "evidence": "gpu-3"},
        {
            "check": "NO_FROZEN_POST_TREATMENT_IMPACT_CONTRACT",
            "status": "PASS",
            "evidence": None,
        },
        {
            "check": "PROFILE_IMPACT_CONTRACTS_ABSENT_OR_NULL",
            "status": "PASS",
            "evidence": None,
        },
        {
            "check": "MATCHED_INTERVENTION_AND_REALIZED_OUTCOMES",
            "status": "PASS",
            "evidence": matched_evidence,
        },
        {
            "check": "PROMPT_TOKEN_CONSERVATION",
            "status": "PASS",
            "evidence": True,
        },
        {
            "check": "REQUIRED_TIMESTAMPS_PRESENT",
            "status": "PASS",
            "evidence": True,
        },
    ]
    deltas_by_class = {
        "DIRECT_RECOVERY_BENEFIT_CONCORDANT": {
            "recompute_tokens": -10,
            "prefix_materialization_latency_ns": -30,
            "recovery_ready_latency_ns": -20,
            "failure_to_completion_latency_ns": -15,
        },
        "DIRECT_RECOVERY_MIXED": {
            "recompute_tokens": -10,
            "prefix_materialization_latency_ns": 30,
            "recovery_ready_latency_ns": 20,
            "failure_to_completion_latency_ns": 15,
        },
        "SOURCE_SUBSTITUTION_OR_NULL_DIRECT_MECHANISM": {
            "recompute_tokens": 0,
            "prefix_materialization_latency_ns": 30,
            "recovery_ready_latency_ns": 0,
            "failure_to_completion_latency_ns": 0,
        },
        "ADVERSE_DIRECT_MECHANISM": {
            "recompute_tokens": 10,
            "prefix_materialization_latency_ns": 30,
            "recovery_ready_latency_ns": 20,
            "failure_to_completion_latency_ns": 15,
        },
    }
    deltas = deltas_by_class[classification]
    return _signed(
        {
            "schema": acceptance.EXPECTED_DIRECT_CLASSIFIER_SCHEMA,
            "status": "PASS",
            "input_artifact_fingerprint": aggregate_fingerprint,
            "focus_span_id": focus_span_id,
            "systems": {},
            "validation": {
                "status": "PASS",
                "fail_closed": True,
                "checks": checks,
                "input_body_sha256": aggregate_fingerprint,
            },
            "paired_deltas_aegiskv_minus_mooncake": deltas,
            "delta_signs": {},
            "direct_mechanism_exercised": classification
            in {
                "DIRECT_RECOVERY_BENEFIT_CONCORDANT",
                "DIRECT_RECOVERY_MIXED",
            },
            "classification": classification,
            "propagation_label": "TEST_PROPAGATION",
            "classification_axes": [
                "recompute_tokens",
                "recovery_ready_latency_ns",
            ],
            "diagnostic_only_axes": [
                "prefix_materialization_latency_ns",
                "failure_to_completion_latency_ns",
            ],
            "effect_direction_gate_applied": effect_direction_gate_applied,
            "all_cells_retained": all_cells_retained,
            "retention_rule": "ALL_VALID_CELLS_RETAINED_INCLUDING_NULL_AND_ADVERSE",
        }
    )


def _patch_generic_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(acceptance, "_validate_aggregate_schema", lambda *_: None)
    monkeypatch.setattr(
        acceptance,
        "_verify_source_and_config",
        lambda *_: {
            "source_contract_fingerprint": "a" * 64,
            "source_file_count": 1,
            "config_binding_fingerprint": "b" * 64,
            "config_file_count": 3,
        },
    )
    monkeypatch.setattr(
        acceptance,
        "_load_workload",
        lambda *_: {
            "workflow_count": 160,
            "span_count": 1304,
            "workflow_ids_sha256": "c" * 64,
            "span_ids_sha256": "d" * 64,
            "exact_token_ids_sha256": "e" * 64,
            "manifest_fingerprint": "f" * 64,
            "workflow_filtering": False,
        },
    )

    def fake_raw(
        _aggregate_path: Path,
        system: dict[str, Any],
        *,
        run_public_audits: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        aegis = system["variant_id"] == "aegiskv_unified"
        raw = {
            "payload": {
                "metrics": {
                    "failure_impact": {
                        "failure_event_count": 0,
                        "active_requests": 0,
                        "queued_requests": 0,
                        "failed_gpu_count": 0,
                    },
                    "policy_effects": {
                        "formal_algorithm2_event_count": 1 if aegis else 0,
                        "aimd_decision_count": 1 if aegis else 0,
                        "aimd_action_counts": {"STABLE_WINDOW": 1} if aegis else {},
                        "hbm_pressure_observation_count": 1 if aegis else 0,
                        "cache_aware_route_evaluations": 1,
                        "cache_aware_route_changes": 1,
                    },
                }
            },
            "representative": {
                "transfers": (
                    [
                        {
                            "cause": "AEGIS_PEER_HBM_PROTECTION",
                            "status": "COMMITTED",
                            "bytes": 100,
                            "transferred_bytes": 100,
                            "aborted_bytes": 0,
                            "ready_ns": 50,
                        }
                    ]
                    if aegis
                    else []
                ),
                "formal_algorithm2_events": (
                    [
                        {
                            "event": "FORMAL_ALGORITHM2_PREVIEW",
                            "timestamp_ns": 50,
                        }
                    ]
                    if aegis
                    else []
                ),
                "aimd_events": (
                    [{"action": "STABLE_WINDOW", "timestamp_ns": 150}]
                    if aegis
                    else []
                ),
                "hbm_pressure_observations": (
                    [{"reason": "PRIMARY_HEADROOM_SHORTFALL"}] if aegis else []
                ),
                "route_events": [
                    {
                        "cache_aware": True,
                        "selected_gpu_id": "gpu-1",
                        "hashed_gpu_id": "gpu-0",
                        "preferred_gpu_id": "gpu-2",
                    }
                ],
                "scheduler_preemption_events": (
                    [
                        {
                            "preempted_request_ids": ["victim"],
                            "preemption_details": [
                                {
                                    "reason": "KV_BLOCK_PRESSURE",
                                    "victim_request_id": "victim",
                                    "victim_num_computed_tokens_before_preemption": 12,
                                    "victim_prompt_tokens": 10,
                                    "victim_output_tokens_before_preemption": 2,
                                    "victim_phase_before_preemption": "DECODE",
                                }
                            ],
                        }
                    ]
                    if aegis
                    else []
                ),
            },
        }
        reports = {"continuous_scheduler": {"status": "PASS"}} if run_public_audits else {}
        return reports, raw

    monkeypatch.setattr(acceptance, "_verify_raw", fake_raw)


def _build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    distinct_orders: bool = True,
    scenario: str = "NO_FAILURE",
    classification: str = "DIRECT_RECOVERY_BENEFIT_CONCORDANT",
    failure_seed_count: int = 5,
    classifier_mutation: Any = None,
    include_classifier: bool = True,
) -> dict[str, Any]:
    _patch_generic_passes(monkeypatch)
    artifact_path = tmp_path / "artifact.json"
    aggregate = _aggregate(
        distinct_orders=distinct_orders,
        seed_count=failure_seed_count if scenario != "NO_FAILURE" else 5,
    )
    _write(artifact_path, aggregate)
    classifier_path = tmp_path / "direct-classifier.json"
    classifier = _direct_classifier(
        aggregate["fingerprint"],
        classification=classification,
    )
    if classifier_mutation is not None:
        classifier = classifier_mutation(classifier)
    if include_classifier:
        _write(classifier_path, classifier)
    attempt: dict[str, Any] = {
        "attempt_id": "attempt-0",
        "disposition": "COMPLETED",
        "scenario": {"kind": scenario},
        "artifact_path": artifact_path.relative_to(tmp_path).as_posix(),
    }
    if scenario != "NO_FAILURE" and include_classifier:
        attempt["direct_classifier"] = {
            "path": classifier_path.relative_to(tmp_path).as_posix(),
            "sha256": acceptance.sha256_file(classifier_path),
            "fingerprint": classifier.get("fingerprint"),
        }
    registry_path = tmp_path / "registry.json"
    _write(
        registry_path,
        _registry(
            [attempt]
        ),
    )
    return acceptance.build_manifest(tmp_path, registry_path)


def test_valid_synthetic_no_failure_reconstructs_all_statistics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _build(tmp_path, monkeypatch)
    attempt = document["attempts"][0]

    assert attempt["terminal_class"] == "VALID"
    assert attempt["allowed_panel_ids"] == list(acceptance.AUTHORIZED_FIGURE_2_PANELS)
    assert [gate["gate"] for gate in attempt["gates"]] == list(range(1, 9))
    assert attempt["gates"][3]["status"] == "NOT_APPLICABLE"
    assert attempt["gates"][3]["evidence"]["verified_failure_event_count"] == 0
    assert attempt["statistics"]["workflow_pair_count"] == 800
    assert attempt["statistics"]["distinct_admission_order_count"] == 5
    assert attempt["statistics"]["student_t_95_eligible"] is True
    assert all(
        item["winner_tie_loser"]
        == {"aegiskv_winner_count": 0, "tie_count": 0, "aegiskv_loser_count": 160}
        for item in attempt["statistics"]["per_seed"]
    )
    assert all(item["mooncake_p95"]["rank"] == 152 for item in attempt["statistics"]["per_seed"])
    declaration = attempt["statistics"]["attribution_declaration"]
    assert declaration == {
        "attribution_kind": "DIAGNOSTIC_NON_ADDITIVE",
        "wct_sum_explanation_claimed": False,
        "modeled_uncalibrated": True,
        "physical_execution": False,
    }
    attribution = attempt["statistics"]["no_failure_attribution"]
    assert len(attribution) == 10
    aegis = next(
        item
        for item in attribution
        if item["algorithm2"]["event_count"] == 1
    )
    assert aegis["protection"]["by_tier_and_time_phase"]["peer_hbm"][
        "bootstrap_warmup"
    ]["submitted_bytes"] == 100
    assert aegis["routing"]["selected_vs_hashed_change_count"] == 1
    assert aegis["scheduler_preemptions"]["victim_computed_tokens_total"] == 12


def _attribution_fixture(
    variant_id: str = "aegiskv_unified",
) -> tuple[dict[str, Any], dict[str, Any]]:
    system = _system(0, variant_id)
    aegis = variant_id == "aegiskv_unified"
    raw = {
        "payload": {
            "metrics": {
                "policy_effects": {
                    "formal_algorithm2_event_count": 1 if aegis else 0,
                    "aimd_decision_count": 1 if aegis else 0,
                    "aimd_action_counts": {"STABLE_WINDOW": 1} if aegis else {},
                    "hbm_pressure_observation_count": 1 if aegis else 0,
                    "cache_aware_route_evaluations": 1,
                    "cache_aware_route_changes": 1,
                }
            }
        },
        "representative": {
            "transfers": (
                [{
                    "cause": "AEGIS_PEER_HBM_PROTECTION",
                    "status": "COMMITTED",
                    "bytes": 100,
                    "transferred_bytes": 100,
                    "aborted_bytes": 0,
                    "ready_ns": 50,
                }]
                if aegis else []
            ),
            "formal_algorithm2_events": (
                [{"event": "FORMAL_ALGORITHM2_PREVIEW", "timestamp_ns": 50}]
                if aegis else []
            ),
            "aimd_events": (
                [{"action": "STABLE_WINDOW", "timestamp_ns": 150}]
                if aegis else []
            ),
            "hbm_pressure_observations": (
                [{"reason": "PRIMARY_HEADROOM_SHORTFALL"}] if aegis else []
            ),
            "route_events": [{
                "cache_aware": True,
                "selected_gpu_id": "gpu-1",
                "hashed_gpu_id": "gpu-0",
                "preferred_gpu_id": "gpu-2",
            }],
            "scheduler_preemption_events": (
                [{
                    "preempted_request_ids": ["victim"],
                    "preemption_details": [{
                        "reason": "KV_BLOCK_PRESSURE",
                        "victim_request_id": "victim",
                        "victim_num_computed_tokens_before_preemption": 12,
                        "victim_prompt_tokens": 10,
                        "victim_output_tokens_before_preemption": 2,
                        "victim_phase_before_preemption": "DECODE",
                    }],
                }]
                if aegis else []
            ),
        },
    }
    return system, raw


@pytest.mark.parametrize(
    ("mutation", "detail"),
    [
        (
            lambda system, raw: system["protection"].update({"submitted_bytes": 99}),
            "protection compact aggregate mismatch",
        ),
        (
            lambda system, raw: system["algorithm2"].update({"event_count": 2}),
            "Algorithm 2 compact/policy summary mismatch",
        ),
        (
            lambda system, raw: raw["payload"]["metrics"]["policy_effects"].update(
                {"aimd_decision_count": 2}
            ),
            "Algorithm 3 compact/policy summary mismatch",
        ),
        (
            lambda system, raw: raw["payload"]["metrics"]["policy_effects"].update(
                {"cache_aware_route_changes": 0}
            ),
            "route evaluation/change policy counter mismatch",
        ),
        (
            lambda system, raw: raw["representative"]["scheduler_preemption_events"][0][
                "preemption_details"
            ][0].update({"victim_output_tokens_before_preemption": 3}),
            "computed-token identity mismatch",
        ),
    ],
)
def test_no_failure_attribution_mismatches_fail_closed(
    mutation: Any,
    detail: str,
) -> None:
    system, raw = _attribution_fixture()
    mutation(system, raw)
    with pytest.raises(acceptance.AcceptanceError, match=detail):
        acceptance._reconstruct_no_failure_attribution(system, raw)


def test_mooncake_rejects_formal_events() -> None:
    system, raw = _attribution_fixture("vanilla_mooncake_dram")
    raw["representative"]["formal_algorithm2_events"] = [
        {"event": "FORMAL_ALGORITHM2_PREVIEW", "timestamp_ns": 50}
    ]
    system["algorithm2"] = {
        "event_count": 1,
        "preview_count": 1,
        "event_counts_by_kind": {"FORMAL_ALGORITHM2_PREVIEW": 1},
    }
    raw["payload"]["metrics"]["policy_effects"]["formal_algorithm2_event_count"] = 1
    with pytest.raises(acceptance.AcceptanceError, match="Mooncake emitted formal"):
        acceptance._reconstruct_no_failure_attribution(system, raw)


@pytest.mark.parametrize(
    ("disposition", "terminal"),
    [("MISSING", "FAILED"), ("FAILED", "FAILED"), ("INFEASIBLE", "INFEASIBLE")],
)
def test_noncompleted_dispositions_are_registered(
    tmp_path: Path,
    disposition: str,
    terminal: str,
) -> None:
    registry_path = tmp_path / "registry.json"
    _write(
        registry_path,
        _registry(
            [
                {
                    "attempt_id": disposition.lower(),
                    "disposition": disposition,
                    "scenario": {"kind": "NO_FAILURE"},
                    "reason_codes": ["TEST_REASON"],
                }
            ]
        ),
    )

    attempt = acceptance.build_manifest(tmp_path, registry_path)["attempts"][0]

    assert attempt["terminal_class"] == terminal
    assert attempt["gates"][0]["status"] == "FAIL"
    assert all(gate["status"] == "NOT_APPLICABLE" for gate in attempt["gates"][1:7])
    assert attempt["gates"][7]["status"] == "PASS"
    assert attempt["allowed_panel_ids"] == []


def test_deterministic_repeats_fail_gate_7_and_block_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = _build(tmp_path, monkeypatch, distinct_orders=False)["attempts"][0]

    assert attempt["gates"][6]["status"] == "FAIL"
    assert attempt["gates"][6]["reason_codes"] == [
        "PAIRED_STATISTICS_OR_INDEPENDENCE_FAILED"
    ]
    assert attempt["statistics"]["deterministic_repeats"] is True
    assert attempt["statistics"]["student_t_95_eligible"] is False
    assert attempt["terminal_class"] == "FAILED"


@pytest.mark.parametrize(
    ("classification", "terminal"),
    [
        ("DIRECT_RECOVERY_BENEFIT_CONCORDANT", "VALID"),
        ("DIRECT_RECOVERY_MIXED", "MIXED_DIRECT"),
        ("SOURCE_SUBSTITUTION_OR_NULL_DIRECT_MECHANISM", "NULL_DIRECT"),
        ("ADVERSE_DIRECT_MECHANISM", "ADVERSE_DIRECT"),
    ],
)
def test_failure_classifier_preserves_all_four_classes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    classification: str,
    terminal: str,
) -> None:
    attempt = _build(
        tmp_path,
        monkeypatch,
        scenario="PRIMARY_FAILURE",
        classification=classification,
    )["attempts"][0]

    assert attempt["gates"][3]["status"] == "PASS"
    assert attempt["gates"][5]["status"] == "PASS"
    assert attempt["gates"][5]["evidence"]["classification"] == classification
    assert attempt["gates"][6]["status"] == "PASS"
    assert attempt["terminal_class"] == terminal
    assert attempt["accepted_for_numerical_aggregates"] is True
    assert attempt["direct_classifier"]["output"]["classification"] == classification
    assert attempt["allowed_panel_ids"] == [
        *acceptance.AUTHORIZED_FAILURE_DIRECT_PANELS,
        *acceptance.AUTHORIZED_FAILURE_AGGREGATE_PANELS,
    ]


def test_single_seed_failure_is_direct_evidence_without_aggregate_panels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = _build(
        tmp_path,
        monkeypatch,
        scenario="PRIMARY_FAILURE",
        failure_seed_count=1,
    )["attempts"][0]

    assert attempt["terminal_class"] == "VALID"
    assert attempt["gates"][6]["status"] == "PASS"
    assert attempt["statistics"]["student_t_95_eligible"] is False
    assert attempt["statistics"]["direct_mechanism_evidence_accepted"] is True
    assert attempt["statistics"]["aggregate_mean_p95_panels_authorized"] is False
    assert attempt["allowed_panel_ids"] == list(
        acceptance.AUTHORIZED_FAILURE_DIRECT_PANELS
    )


def test_missing_classifier_fails_causal_gate_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = _build(
        tmp_path,
        monkeypatch,
        scenario="PRIMARY_FAILURE",
        include_classifier=False,
    )["attempts"][0]

    assert attempt["gates"][3]["status"] == "FAIL"
    assert attempt["gates"][3]["reason_codes"] == ["FAILURE_CAUSAL_CONTRACT_FAILED"]
    assert "direct_classifier must be an object" in attempt["gates"][3]["evidence"]["detail"]
    assert attempt["terminal_class"] == "FAILED"


def test_tampered_classifier_file_hash_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_generic_passes(monkeypatch)
    artifact = _aggregate()
    artifact_path = tmp_path / "artifact.json"
    _write(artifact_path, artifact)
    classifier_path = tmp_path / "classifier.json"
    classifier = _direct_classifier(artifact["fingerprint"])
    _write(classifier_path, classifier)
    registry_path = tmp_path / "registry.json"
    _write(
        registry_path,
        _registry(
            [
                {
                    "attempt_id": "attempt-0",
                    "disposition": "COMPLETED",
                    "scenario": {"kind": "PRIMARY_FAILURE"},
                    "artifact_path": "artifact.json",
                    "direct_classifier": {
                        "path": "classifier.json",
                        "sha256": acceptance.sha256_file(classifier_path),
                        "fingerprint": classifier["fingerprint"],
                    },
                }
            ]
        ),
    )
    classifier["classification"] = "ADVERSE_DIRECT_MECHANISM"
    _write(classifier_path, classifier)

    attempt = acceptance.build_manifest(tmp_path, registry_path)["attempts"][0]

    assert attempt["gates"][3]["status"] == "FAIL"
    assert "file SHA-256 mismatch" in attempt["gates"][3]["evidence"]["detail"]


def test_classifier_input_fingerprint_mismatch_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mismatch(classifier: dict[str, Any]) -> dict[str, Any]:
        body = dict(classifier)
        body.pop("fingerprint")
        body["input_artifact_fingerprint"] = "9" * 64
        return _signed(body)

    attempt = _build(
        tmp_path,
        monkeypatch,
        scenario="PRIMARY_FAILURE",
        classifier_mutation=mismatch,
    )["attempts"][0]

    assert attempt["gates"][3]["status"] == "FAIL"
    assert "input fingerprint mismatch" in attempt["gates"][3]["evidence"]["detail"]


def test_classifier_causal_check_failure_fails_gate_4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_causal_check(classifier: dict[str, Any]) -> dict[str, Any]:
        body = dict(classifier)
        body.pop("fingerprint")
        validation = dict(body["validation"])
        validation["checks"] = [
            {
                **check,
                "status": (
                    "FAIL"
                    if check["check"] == "MATCHED_SINGLE_FAILURE_SCHEDULE"
                    else check["status"]
                ),
            }
            for check in validation["checks"]
        ]
        body["validation"] = validation
        return _signed(body)

    attempt = _build(
        tmp_path,
        monkeypatch,
        scenario="PRIMARY_FAILURE",
        classifier_mutation=fail_causal_check,
    )["attempts"][0]

    assert attempt["gates"][3]["status"] == "FAIL"
    assert "did not PASS" in attempt["gates"][3]["evidence"]["detail"]


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("effect_direction_gate_applied", True, "effect-direction filter"),
        ("all_cells_retained", False, "retain all valid cells"),
    ],
)
def test_classifier_rejects_filtering_or_cell_dropping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: bool,
    detail: str,
) -> None:
    def mutate(classifier: dict[str, Any]) -> dict[str, Any]:
        body = dict(classifier)
        body.pop("fingerprint")
        body[field] = value
        return _signed(body)

    attempt = _build(
        tmp_path,
        monkeypatch,
        scenario="RECOVERY_SELECTOR",
        classifier_mutation=mutate,
    )["attempts"][0]

    assert attempt["gates"][3]["status"] == "PASS"
    assert attempt["gates"][5]["status"] == "FAIL"
    assert attempt["gates"][5]["reason_codes"] == ["DIRECT_CLASSIFICATION_FAILED"]
    assert detail in attempt["gates"][5]["evidence"]["detail"]


def test_registry_duplicate_keys_and_nonfinite_numbers_are_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema":"moonkvsim.aegiskv.qwen3-8b-acceptance-registry.v1",'
        '"attempts":[],"attempts":[],"fingerprint":"' + "0" * 64 + '"}',
        encoding="utf-8",
    )
    with pytest.raises(acceptance.AcceptanceError, match="duplicate JSON key"):
        acceptance.load_registry(tmp_path, duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(acceptance.AcceptanceError, match="non-finite"):
        acceptance.load_json_strict(nonfinite)


def test_path_escape_and_symlink_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(acceptance.AcceptanceError, match="normalized repository-relative"):
        acceptance.repository_path(tmp_path, "../outside.json", "test")

    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(acceptance.AcceptanceError, match="symlink"):
        acceptance.repository_path(tmp_path, "link.json", "test")


def test_raw_component_and_file_hash_tampering_are_rejected(tmp_path: Path) -> None:
    aggregate_dir = tmp_path / "result"
    raw_path = aggregate_dir / "raw/seed-0/vanilla_mooncake_dram.json"
    payload = {"status": "PASS"}
    raw: dict[str, Any] = {
        "schema": acceptance.EXPECTED_RAW_SCHEMA,
        "status": "PASS",
        "component_sha256": {
            "payload": acceptance.fingerprint(payload),
            "journal": "2" * 64,
            "span_details": acceptance.fingerprint([]),
            "representative": acceptance.fingerprint({}),
            "continuous_scheduler_audit": acceptance.fingerprint({"status": "PASS"}),
            "formal_algorithm_audit": None,
        },
        "payload": payload,
        "span_details": [],
        "representative": {},
        "continuous_scheduler_audit": {"status": "PASS"},
        "formal_algorithm_audit": None,
    }
    _write(raw_path, raw)
    system: dict[str, Any] = {
        "variant_id": "vanilla_mooncake_dram",
        "payload_sha256": raw["component_sha256"]["payload"],
        "span_details_sha256": raw["component_sha256"]["span_details"],
        "representative_sha256": raw["component_sha256"]["representative"],
        "raw_artifact": {
            "path": "raw/seed-0/vanilla_mooncake_dram.json",
            "sha256": acceptance.sha256_file(raw_path),
        },
    }
    acceptance._verify_raw(aggregate_dir / "aggregate.json", system, run_public_audits=False)

    system["raw_artifact"]["sha256"] = "0" * 64
    with pytest.raises(acceptance.AcceptanceError, match="referenced raw artifact"):
        acceptance._verify_raw(aggregate_dir / "aggregate.json", system, run_public_audits=False)
    system["raw_artifact"]["sha256"] = acceptance.sha256_file(raw_path)

    raw["component_sha256"]["payload"] = "0" * 64
    _write(raw_path, raw)
    system["raw_artifact"]["sha256"] = acceptance.sha256_file(raw_path)
    with pytest.raises(acceptance.AcceptanceError, match="raw component hash mismatch"):
        acceptance._verify_raw(aggregate_dir / "aggregate.json", system, run_public_audits=False)


def test_fingerprint_is_deterministic_and_tamper_evident(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _build(tmp_path, monkeypatch)
    second = acceptance.build_manifest(tmp_path, tmp_path / "registry.json")
    assert first == second

    tampered = json.loads(json.dumps(first))
    tampered["attempts"][0]["terminal_class"] = "FAILED"
    schema = Path(__file__).resolve().parents[2] / (
        "schemas/aegiskv-qwen3-8b-acceptance-manifest.schema.json"
    )
    with pytest.raises(acceptance.AcceptanceError, match="self-fingerprint mismatch"):
        acceptance.validate_manifest(tampered, schema)


def test_schema_rejects_unknown_panel_and_wrong_gate_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _build(tmp_path, monkeypatch)
    schema = Path(__file__).resolve().parents[2] / (
        "schemas/aegiskv-qwen3-8b-acceptance-manifest.schema.json"
    )
    acceptance.validate_manifest(document, schema)

    unknown = json.loads(json.dumps(document))
    unknown["attempts"][0]["allowed_panel_ids"].append("FIGURE_999_A")
    with pytest.raises(acceptance.AcceptanceError, match="schema validation"):
        acceptance.validate_manifest(unknown, schema)

    reordered = json.loads(json.dumps(document))
    reordered["attempts"][0]["gates"][0], reordered["attempts"][0]["gates"][1] = (
        reordered["attempts"][0]["gates"][1],
        reordered["attempts"][0]["gates"][0],
    )
    with pytest.raises(acceptance.AcceptanceError, match="schema validation"):
        acceptance.validate_manifest(reordered, schema)
