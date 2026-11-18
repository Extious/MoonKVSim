from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from moonkvsim.common.hash import sha256_json


def _module() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "benchmark"
        / "AegisKV"
        / "experiments"
        / "scripts"
        / "classify_qwen3_8b_direct_recovery.py"
    )
    spec = importlib.util.spec_from_file_location("direct_recovery_classifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _refingerprint(document: dict[str, Any]) -> None:
    document.pop("fingerprint", None)
    document["fingerprint"] = sha256_json(document)


def _document(
    *,
    mooncake_recompute: int,
    aegiskv_recompute: int,
    mooncake_ready_ns: int = 100,
    aegiskv_ready_ns: int = 100,
    mooncake_completed_ns: int = 200,
    aegiskv_completed_ns: int = 200,
    mooncake_materialized_ns: int = 90,
    aegiskv_materialized_ns: int = 90,
    mooncake_injection_ns: int = 80,
    aegiskv_injection_ns: int = 80,
    aegiskv_extra_victim: bool = False,
) -> dict[str, Any]:
    focus = "workflow:focus"
    event = {
        "failure_id": "failure-0",
        "event_index": 0,
        "type": "GPU_FAILURE",
        "bucket": "96k",
        "seed": 0,
        "focus_span_id": focus,
        "target_gpu_id": "gpu-3",
        "target_gpu_id_semantics": "FROZEN_PHYSICAL_FAILURE_TARGET",
        "impact_contract": None,
        "profile_impact_contracts": None,
        "workload_position": {
            "kind": "COMPLETED_WORKFLOW_FRACTION_NEAREST_COMMON_ROUTE_SPAN",
            "target_progress_per_mille": 600,
            "reference_completed_workflow_count": 10,
            "reference_workflow_count": 160,
        },
        "trigger": {
            "kind": "FOCUS_SPAN_COMPUTE_PROGRESS",
            "progress_per_mille": 500,
        },
        "reference_at_ns": 70,
        "reference_at_ns_semantics": "fixture",
        "detection_delay_ns": 1,
        "selection_scope": "fixture",
        "repair_after_ns": 1_000,
        "parameter_source": "fixture",
    }
    schedule = {
        "type": "GPU_FAILURE",
        "failure_count": 1,
        "selection_scope": "fixture",
        "events": [event],
    }

    def run(
        recompute: int,
        peer: int,
        ready_ns: int,
        completed_ns: int,
        materialized_ns: int,
        injection_ns: int,
        extra_victim: bool,
    ) -> dict[str, Any]:
        normal = 10
        store = 100 - recompute - peer - normal
        return {
            "failure_schedule": schedule,
            "failure_schedule_fingerprint": sha256_json(schedule),
            "span_details": [
                {
                    "span_id": focus,
                    "prompt_tokens": 100,
                    "completed_ns": completed_ns,
                    "restored_peer_local_tokens": peer // 2,
                    "restored_peer_d2d_tokens": peer - peer // 2,
                }
            ],
            "representative": {
                "failure_events": [
                    {
                        "timestamp_ns": injection_ns,
                        "event": "FAILURE_INJECT",
                        "target_gpu_id": "gpu-3",
                        "impacted_active_span_ids": [focus],
                        "impacted_queued_span_ids": sorted(
                            [
                                "workflow:queued",
                                *(["workflow:aegis-extra"] if extra_victim else []),
                            ]
                        ),
                        "reroute_only_queued_span_ids": sorted(
                            [
                                "workflow:queued",
                                *(["workflow:aegis-extra"] if extra_victim else []),
                            ]
                        ),
                        "logical_trigger": {
                            "focus_span_id": focus,
                            "progress_per_mille": 500,
                            "resolved_target_gpu_id": "gpu-3",
                            "continuous_progress_evidence": {
                                "prompt_tokens": 100,
                            },
                        },
                    }
                ],
                "recovery_events": [
                    {
                        "event": "RECOVERY_PLAN",
                        "span_id": focus,
                        "prompt_tokens": 100,
                        "effective_prefix_tokens": 100 - recompute,
                        "source_tokens": {
                            "NORMAL_HBM_LOCAL": normal,
                            "RECOMPUTE": recompute,
                            "PEER_HBM": peer,
                            "STORE_DRAM": store,
                        },
                    },
                    {
                        "event": "CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED",
                        "span_id": focus,
                        "timestamp_ns": materialized_ns,
                    },
                    {
                        "event": "PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
                        "span_id": focus,
                        "timestamp_ns": ready_ns,
                    },
                ],
            },
        }

    document = {
        "status": "PASS",
        "protocol": {
            "paper_causal_mode": True,
            "focus_span_ids": [focus],
        },
        "runs": {
            "gpu_failure": {
                "vanilla_mooncake_dram": run(
                    mooncake_recompute,
                    0,
                    mooncake_ready_ns,
                    mooncake_completed_ns,
                    mooncake_materialized_ns,
                    mooncake_injection_ns,
                    False,
                ),
                "aegiskv_unified": run(
                    aegiskv_recompute,
                    min(40, 90 - aegiskv_recompute),
                    aegiskv_ready_ns,
                    aegiskv_completed_ns,
                    aegiskv_materialized_ns,
                    aegiskv_injection_ns,
                    aegiskv_extra_victim,
                ),
            }
        },
    }
    _refingerprint(document)
    return document


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        (
            _document(
                mooncake_recompute=50,
                aegiskv_recompute=30,
                aegiskv_ready_ns=90,
            ),
            "DIRECT_RECOVERY_BENEFIT_CONCORDANT",
        ),
        (
            _document(
                mooncake_recompute=50,
                aegiskv_recompute=30,
                aegiskv_ready_ns=110,
            ),
            "DIRECT_RECOVERY_MIXED",
        ),
        (
            _document(mooncake_recompute=50, aegiskv_recompute=50),
            "SOURCE_SUBSTITUTION_OR_NULL_DIRECT_MECHANISM",
        ),
        (
            _document(
                mooncake_recompute=50,
                aegiskv_recompute=60,
                aegiskv_ready_ns=110,
            ),
            "ADVERSE_DIRECT_MECHANISM",
        ),
    ],
)
def test_classifier_emits_all_four_direct_classes(
    document: dict[str, Any],
    expected: str,
) -> None:
    result = _module().classify(document)

    assert result["classification"] == expected
    assert result["schema"].endswith(".v2")
    assert result["effect_direction_gate_applied"] is False
    assert result["all_cells_retained"] is True


def test_completion_diagnostic_does_not_change_direct_class() -> None:
    earlier = _module().classify(
        _document(
            mooncake_recompute=50,
            aegiskv_recompute=30,
            aegiskv_ready_ns=90,
            aegiskv_completed_ns=150,
        )
    )
    later = _module().classify(
        _document(
            mooncake_recompute=50,
            aegiskv_recompute=30,
            aegiskv_ready_ns=90,
            aegiskv_completed_ns=250,
        )
    )

    assert earlier["classification"] == later["classification"]
    assert earlier["propagation_label"] == (
        "PROPAGATED_TO_FAILED_REQUEST_COMPLETION"
    )
    assert later["propagation_label"] == "REVERSED_BY_FAILED_REQUEST_COMPLETION"


def test_classifier_compares_failure_relative_durations() -> None:
    result = _module().classify(
        _document(
            mooncake_recompute=50,
            aegiskv_recompute=50,
            mooncake_injection_ns=80,
            aegiskv_injection_ns=100,
            mooncake_materialized_ns=90,
            aegiskv_materialized_ns=115,
            mooncake_ready_ns=100,
            aegiskv_ready_ns=125,
            mooncake_completed_ns=200,
            aegiskv_completed_ns=225,
        )
    )

    assert result["classification"] == "ADVERSE_DIRECT_MECHANISM"
    assert result["paired_deltas_aegiskv_minus_mooncake"][
        "recovery_ready_latency_ns"
    ] == 5
    assert result["paired_deltas_aegiskv_minus_mooncake"][
        "failure_to_completion_latency_ns"
    ] == 5


def test_classifier_rejects_input_fingerprint_tamper() -> None:
    document = _document(mooncake_recompute=50, aegiskv_recompute=30)
    document["protocol"]["focus_span_ids"] = ["tampered"]

    with pytest.raises(ValueError, match="self-fingerprint mismatch"):
        _module().classify(document)


def test_classifier_rejects_frozen_impact_contract() -> None:
    document = _document(mooncake_recompute=50, aegiskv_recompute=30)
    for run in document["runs"]["gpu_failure"].values():
        run["failure_schedule"]["events"][0]["impact_contract"] = {
            "kind": "EXACT_NATURAL_PRE_FENCE_REQUEST_PARTITION",
            "active_span_ids": ["workflow:focus"],
            "queued_span_ids": [],
            "reroute_only_queued_span_ids": [],
        }
        run["failure_schedule_fingerprint"] = sha256_json(run["failure_schedule"])
    _refingerprint(document)

    with pytest.raises(ValueError, match="rejects frozen post-treatment"):
        _module().classify(document)


def test_classifier_rejects_profile_specific_contract() -> None:
    document = _document(mooncake_recompute=50, aegiskv_recompute=30)
    for run in document["runs"]["gpu_failure"].values():
        run["failure_schedule"]["events"][0]["profile_impact_contracts"] = {
            "profile": {
                "kind": "EXACT_NATURAL_PRE_FENCE_REQUEST_PARTITION",
                "active_span_ids": ["workflow:focus"],
                "queued_span_ids": [],
                "reroute_only_queued_span_ids": [],
            }
        }
        run["failure_schedule_fingerprint"] = sha256_json(run["failure_schedule"])
    _refingerprint(document)

    with pytest.raises(ValueError, match="rejects frozen post-treatment"):
        _module().classify(document)


def test_classifier_rejects_token_nonconservation() -> None:
    document = _document(mooncake_recompute=50, aegiskv_recompute=30)
    plan = document["runs"]["gpu_failure"]["aegiskv_unified"]["representative"][
        "recovery_events"
    ][0]
    plan["source_tokens"]["STORE_DRAM"] += 1
    _refingerprint(document)

    with pytest.raises(ValueError, match="do not conserve prompt"):
        _module().classify(document)


def test_classifier_uses_failure_trigger_prompt_tokens_when_plan_omits_them() -> None:
    document = _document(mooncake_recompute=50, aegiskv_recompute=30)
    for run in document["runs"]["gpu_failure"].values():
        plan = run["representative"]["recovery_events"][0]
        plan.pop("prompt_tokens")
        run["span_details"][0].pop("prompt_tokens")
    _refingerprint(document)

    result = _module().classify(document)

    checks = {
        item["check"]: item["evidence"]
        for item in result["validation"]["checks"]
    }
    assert checks["PROMPT_TOKEN_CONSERVATION"]["vanilla_mooncake_dram"][
        "prompt_tokens"
    ] == 100


def test_classifier_accepts_different_realized_times_and_collateral_victims() -> None:
    result = _module().classify(
        _document(
            mooncake_recompute=50,
            aegiskv_recompute=30,
            mooncake_injection_ns=80,
            aegiskv_injection_ns=95,
            aegiskv_materialized_ns=105,
            aegiskv_ready_ns=115,
            aegiskv_extra_victim=True,
        )
    )

    checks = {
        item["check"]: item["evidence"]
        for item in result["validation"]["checks"]
    }
    outcomes = checks["MATCHED_INTERVENTION_AND_REALIZED_OUTCOMES"][
        "realized_outcomes_by_system"
    ]
    assert outcomes["vanilla_mooncake_dram"]["injection_timestamp_ns"] == 80
    assert outcomes["aegiskv_unified"]["injection_timestamp_ns"] == 95
    assert outcomes["vanilla_mooncake_dram"]["queued_span_ids"] != outcomes[
        "aegiskv_unified"
    ]["queued_span_ids"]


def test_output_has_valid_self_fingerprint() -> None:
    result = _module().classify(
        _document(mooncake_recompute=50, aegiskv_recompute=30)
    )
    unsigned = dict(result)
    fingerprint = unsigned.pop("fingerprint")

    assert fingerprint == sha256_json(unsigned)
    assert result["validation"]["status"] == "PASS"


def test_cli_writer_rejects_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "classification.json"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(ValueError, match="refusing to overwrite"):
        _module()._write_atomic(output, {"value": 1})


def test_cli_writer_writes_complete_json_atomically(tmp_path: Path) -> None:
    output = tmp_path / "classification.json"

    _module()._write_atomic(output, {"value": 1})

    assert json.loads(output.read_text(encoding="utf-8")) == {"value": 1}
