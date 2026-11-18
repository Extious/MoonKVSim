from __future__ import annotations

import pickle
from copy import deepcopy
from fractions import Fraction

import pytest

from moonkvsim.aegiskv.formal_algorithm_audit import (
    CONTINUOUS_SCHEDULER_AUDIT_SCHEMA,
    FORMAL_ALGORITHM_AUDIT_SCHEMA,
    FormalAlgorithmAuditError,
    audit_continuous_scheduler_evidence,
    audit_formal_algorithm_run,
    audit_lru_ablation_run,
)
from moonkvsim.aegiskv.recovery_harm import (
    AdmissionHarmDelta,
    RecoveryHarmSnapshot,
    RecoveryTimeBreakdown,
    VictimSetHarmDelta,
    current_design_rental_value,
)
from moonkvsim.aegiskv.slack_landlord import SlackLandlord
from moonkvsim.aegiskv.types import (
    PolicyPool,
    SealedChunk,
    SlackSignal,
    fraction_from_json,
    fraction_to_json,
)


def _snapshot(
    request_id: str,
    pool: PolicyPool,
    harm_ns: int,
) -> RecoveryHarmSnapshot:
    return RecoveryHarmSnapshot(
        request_id=request_id,
        pool=pool,
        evaluated_at_ns=0,
        slack=SlackSignal(
            slack_at_observation_ns=Fraction(0, 1),
            observed_at_ns=0,
            version=1,
        ),
        recovery_time=RecoveryTimeBreakdown(
            load_ns=Fraction(harm_ns, 1),
            prompt_suffix_recompute_ns=Fraction(0, 1),
            silent_replay_ns=Fraction(0, 1),
        ),
    )


def _gain(
    request_id: str,
    pool: PolicyPool,
    before_ns: int,
    after_ns: int,
) -> AdmissionHarmDelta:
    return AdmissionHarmDelta(
        before=_snapshot(request_id, pool, before_ns),
        after=_snapshot(request_id, pool, after_ns),
    )


def _value(
    request_id: str,
    pool: PolicyPool,
    *,
    chunk_id: str,
    sequence_index: int,
    allocated_bytes: int,
    before_ns: int,
    after_ns: int,
    rent: Fraction = Fraction(0, 1),
):
    gain = _gain(request_id, pool, before_ns, after_ns)
    return current_design_rental_value(
        candidate=SealedChunk(
            chunk_id=chunk_id,
            request_id=request_id,
            sequence_index=sequence_index,
            allocated_bytes=allocated_bytes,
        ),
        before=gain.before,
        after=gain.after,
        pool_rent=rent,
        frontier_version=1,
    )


def _preview_events() -> list[dict[str, object]]:
    peer = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=10)
    victim = _value(
        "victim",
        PolicyPool.PEER_HBM,
        chunk_id="PEER_HBM:gpu0:victim:0:content-key",
        sequence_index=0,
        allocated_bytes=10,
        before_ns=1,
        after_ns=0,
    )
    peer.register_committed(victim)
    candidate_gain = _gain("peer-candidate", PolicyPool.PEER_HBM, 20, 0)
    candidate = _value(
        "peer-candidate",
        PolicyPool.PEER_HBM,
        chunk_id="peer-candidate-0",
        sequence_index=0,
        allocated_bytes=10,
        before_ns=20,
        after_ns=0,
    )
    preview = peer.preview(
        candidate,
        latest_values={victim.candidate.chunk_id: victim},
        candidate_gain_evidence=candidate_gain,
        joint_loss_provider=lambda _victims: VictimSetHarmDelta(
            before_by_request=(_snapshot("victim", PolicyPool.PEER_HBM, 0),),
            after_by_request=(_snapshot("victim", PolicyPool.PEER_HBM, 1),),
        ),
    )

    store = SlackLandlord(pool=PolicyPool.STORE_DRAM, capacity_bytes=20)
    store_gain = _gain("store-candidate", PolicyPool.STORE_DRAM, 10, 0)
    store_candidate = _value(
        "store-candidate",
        PolicyPool.STORE_DRAM,
        chunk_id="store-candidate-0",
        sequence_index=0,
        allocated_bytes=10,
        before_ns=10,
        after_ns=0,
    )
    store_preview = store.preview(
        store_candidate,
        latest_values={},
        candidate_gain_evidence=store_gain,
        joint_loss_provider=lambda _victims: pytest.fail("no Store victim expected"),
    )
    peer_preview_json = preview.to_canonical_json()
    peer_preview_json["landlord_applied"] = True
    peer_preview_json["excluded_victim_reasons"] = {}
    store_preview_json = store_preview.to_canonical_json()
    store_preview_json["landlord_applied"] = True
    store_preview_json["excluded_victim_reasons"] = {}
    return [
        {
            "event": "FORMAL_ALGORITHM2_PREVIEW",
            "path": "PEER_HBM",
            "pool_id": "PEER_HBM:gpu0",
            "span_id": "peer-candidate",
            "timestamp_ns": 1,
            "candidate_token_start": 0,
            "candidate_token_count": 64,
            "candidate_global_system_template": True,
            "engine_policy_chunk_tokens": 1_024,
            "preview": peer_preview_json,
        },
        {
            "event": "FORMAL_ALGORITHM2_PREVIEW",
            "path": "STORE_DRAM",
            "pool_id": "STORE_DRAM:segment0",
            "span_id": "store-candidate",
            "timestamp_ns": 2,
            "candidate_token_start": 64,
            "candidate_token_count": 1_024,
            "candidate_global_system_template": False,
            "engine_policy_chunk_tokens": 1_024,
            "preview": store_preview_json,
        },
    ]


def _lifecycle(
    *,
    capacity_before: int,
    capacity_after: int,
    rent: Fraction,
    released_entry: dict[str, object] | None = None,
) -> dict[str, object]:
    released = [] if released_entry is None else [released_entry]
    released_bytes = 0 if released_entry is None else int(released_entry["actual_allocated_bytes"])
    rent_after = (
        rent if released_entry is None else max(rent, fraction_from_json(released_entry["H"]))
    )
    return {
        "aborted_pending": [],
        "aborted_pending_bytes": 0,
        "action": "CAPACITY_CHANGE",
        "available_after": True,
        "available_before": True,
        "capacity_bytes_after": capacity_after,
        "capacity_bytes_before": capacity_before,
        "cause": (
            "AEGIS_AIMD_MULTIPLICATIVE_DECREASE"
            if capacity_after < capacity_before
            else "AEGIS_AIMD_ADDITIVE_INCREASE"
        ),
        "epoch": 1,
        "pool": "PEER_HBM",
        "refresh_checks": [],
        "released_bytes": released_bytes,
        "released_entries": released,
        "rent_after": fraction_to_json(rent_after),
        "rent_before": fraction_to_json(rent),
    }


def _aimd_event(
    *,
    timestamp_ns: int,
    action: str,
    pressure: bool,
    previous_alpha: str,
    next_alpha: str,
    previous_stable: int,
    next_stable: int,
    current_bytes: int,
    quota_bytes: int,
    lifecycle: dict[str, object],
) -> dict[str, object]:
    reclaim = max(0, current_bytes - quota_bytes)
    return {
        "action": action,
        "admission_blocked": reclaim > 0,
        "bytes_to_reclaim": reclaim,
        "current_protection_bytes": current_bytes,
        "foreground_pressure": pressure,
        "formal_algorithm2_capacity_lifecycle": lifecycle,
        "next_state": {
            "last_update_ns": timestamp_ns,
            "peer_hbm_capacity_bytes": 100,
            "protection_fraction": next_alpha,
            "stable_windows": next_stable,
            "target_id": "gpu0",
        },
        "parameters": {
            "additive_increase": "0.1",
            "maximum_fraction": "0.8",
            "minimum_fraction": "0.1",
            "multiplicative_decrease": "0.5",
            "stable_window_count": 2,
        },
        "previous_state": {
            "last_update_ns": None if timestamp_ns == 10 else timestamp_ns - 10,
            "peer_hbm_capacity_bytes": 100,
            "protection_fraction": previous_alpha,
            "stable_windows": previous_stable,
            "target_id": "gpu0",
        },
        "quota_bytes": quota_bytes,
        "timestamp_ns": timestamp_ns,
        "update_basis": "FIXED_GLOBAL_DES_CONTROL_WINDOW",
    }


def _resident(
    *, request_ids: list[str], block_ids: list[int], active_bytes: int
) -> dict[str, object]:
    return {
        "resident_primary_request_count": len(request_ids),
        "resident_primary_block_count": len(block_ids),
        "resident_primary_bytes": active_bytes,
        "request_ids": request_ids,
        "unique_block_ids": block_ids,
        "bytes_by_hbm_resource": {"hbm:gpu0": active_bytes},
    }


def _hbm_state(timestamp_ns: int, active_bytes: int) -> dict[str, object]:
    return {
        "timestamp_ns": timestamp_ns,
        "resource_id": "hbm:gpu0",
        "capacity_bytes": 100,
        "accounts": {
            "ACTIVE_PRIMARY_KV": active_bytes,
            "FOREGROUND_STORE_RESTORE_RESERVED": 0,
            "FREE": 100 - active_bytes,
        },
        "cause": "TEST",
    }


def _artifacts() -> tuple[dict[str, object], dict[str, object]]:
    formal_events = _preview_events()
    quota_victim = _value(
        "quota-request",
        PolicyPool.PEER_HBM,
        chunk_id="quota-request-1",
        sequence_index=1,
        allocated_bytes=20,
        before_ns=1,
        after_ns=0,
    ).to_canonical_json()
    md = _lifecycle(
        capacity_before=50,
        capacity_after=25,
        rent=Fraction(1, 10),
        released_entry=quota_victim,
    )
    hold = _lifecycle(
        capacity_before=25,
        capacity_after=25,
        rent=Fraction(1, 10),
    )
    increase = _lifecycle(
        capacity_before=25,
        capacity_after=35,
        rent=Fraction(1, 10),
    )
    representative: dict[str, object] = {
        "aimd_events": [
            _aimd_event(
                timestamp_ns=10,
                action="MULTIPLICATIVE_DECREASE",
                pressure=True,
                previous_alpha="0.5",
                next_alpha="0.25",
                previous_stable=0,
                next_stable=0,
                current_bytes=40,
                quota_bytes=25,
                lifecycle=md,
            ),
            _aimd_event(
                timestamp_ns=20,
                action="STABLE_WINDOW",
                pressure=False,
                previous_alpha="0.25",
                next_alpha="0.25",
                previous_stable=0,
                next_stable=1,
                current_bytes=20,
                quota_bytes=25,
                lifecycle=hold,
            ),
            _aimd_event(
                timestamp_ns=30,
                action="ADDITIVE_INCREASE",
                pressure=False,
                previous_alpha="0.25",
                next_alpha="0.35",
                previous_stable=1,
                next_stable=0,
                current_bytes=20,
                quota_bytes=35,
                lifecycle=increase,
            ),
        ],
        "failure_events": [{"event": "FAILURE_INJECT", "target_gpu_id": "gpu0"}],
        "formal_algorithm2_events": formal_events,
        "algorithm1_cpm": {
            "scheduler-request": {
                "workflow_id": "workflow-0",
            }
        },
        "hbm_pressure_observations": [
            {"timestamp_ns": 10, "target_gpu_id": "gpu0", "reason": "HEADROOM"}
        ],
        "peer_hbm_timelines": {
            "gpu0": [
                {
                    "timestamp_ns": 0,
                    "occupied_bytes": 40,
                    "committed_bytes": 40,
                    "pending_bytes": 0,
                    "capacity_bytes": 50,
                    "unavailable_bytes": 0,
                    "cause": "INITIAL",
                },
                {
                    "timestamp_ns": 10,
                    "occupied_bytes": 20,
                    "committed_bytes": 20,
                    "pending_bytes": 0,
                    "capacity_bytes": 25,
                    "unavailable_bytes": 0,
                    "cause": "AEGIS_AIMD_MULTIPLICATIVE_DECREASE:FORMAL_RECLAIM",
                },
                {
                    "timestamp_ns": 30,
                    "occupied_bytes": 20,
                    "committed_bytes": 20,
                    "pending_bytes": 0,
                    "capacity_bytes": 35,
                    "unavailable_bytes": 0,
                    "cause": "AEGIS_AIMD_ADDITIVE_INCREASE",
                },
            ]
        },
        "recovery_events": [
            {
                "event": "RECOVERY_PLAN",
                "protection_sources_committed_only": True,
                "in_flight_protection_estimate_used": False,
            }
        ],
        "recovery_source_events": [{"event": "PEER_HBM_LOCAL_ADOPTION"}],
        "store_dram_timelines": {
            "segment0": [
                {
                    "timestamp_ns": 0,
                    "occupied_bytes": 0,
                    "committed_bytes": 0,
                    "pending_bytes": 0,
                    "capacity_bytes": 20,
                    "unavailable_bytes": 0,
                    "cause": "INITIAL",
                },
                {
                    "timestamp_ns": 2,
                    "occupied_bytes": 10,
                    "committed_bytes": 10,
                    "pending_bytes": 0,
                    "capacity_bytes": 20,
                    "unavailable_bytes": 0,
                    "cause": "STORE_DRAM_COMMIT",
                },
            ]
        },
        "gpu_hbm_timelines": {
            "gpu0": [
                _hbm_state(0, 0),
                _hbm_state(0, 64),
                _hbm_state(20, 64),
                _hbm_state(20, 0),
            ]
        },
        "continuous_batch_scheduler": {
            "finished_at_ns": 20,
            "requests": [
                {
                    "spec": {
                        "request_id": "scheduler-request",
                        "release_ns": 0,
                        "max_output_tokens": 1,
                    },
                    "completion_ns": 20,
                    "wct_ns": 20,
                    "route_history": [
                        {
                            "timestamp_ns": 0,
                            "route_version": 0,
                            "target_id": "gpu0",
                            "cause": "INITIAL_ADMIT",
                        }
                    ],
                }
            ],
            "steps": [
                {
                    "step_id": "scheduler-step-0",
                    "gpu_id": "gpu0",
                    "status": "COMPLETED",
                    "start_ns": 0,
                    "planned_end_ns": 20,
                    "effective_end_ns": 20,
                    "participants": [{"request_id": "scheduler-request"}],
                    "duration": {"duration_ns": 20},
                    "resident_before": _resident(
                        request_ids=[], block_ids=[], active_bytes=0
                    ),
                    "resident_after_schedule": _resident(
                        request_ids=["scheduler-request"],
                        block_ids=[1],
                        active_bytes=64,
                    ),
                    "completion": {
                        "step_id": "scheduler-step-0",
                        "output_positions": {"scheduler-request": 1},
                        "terminal_output_request_ids": ["scheduler-request"],
                        "residency_after_completion": _resident(
                            request_ids=["scheduler-request"],
                            block_ids=[1],
                            active_bytes=64,
                        ),
                    },
                    "resident_after_retire": _resident(
                        request_ids=[], block_ids=[], active_bytes=0
                    ),
                }
            ],
            "failures": [],
            "journal_sha256": "0" * 64,
            "duration_evidence": [
                {
                    "evidence_class": "UNCALIBRATED_MODEL",
                    "physically_measured": False,
                    "formal_use_allowed": False,
                }
            ],
            "calibration_boundary": ("MODELED_UNCALIBRATED_NOT_PHYSICAL_BATCH_LATENCY_EVIDENCE"),
        },
    }
    payload: dict[str, object] = {
        "schema": "moonkvsim.aegiskv.study_run_payload.v1",
        "status": "PASS",
        "resource_model": {
            "gpu_hbm_account_stack": [
                "ACTIVE_PRIMARY_KV",
                "FOREGROUND_STORE_RESTORE_RESERVED",
                "FREE",
            ],
        },
        "workload": {
            "span_count": 1,
            "workflow_count": 1,
        },
        "output_audit": {
            "expected_output_tokens": 1,
            "external_output_tokens": 1,
            "duplicate_or_missing_tokens": 0,
        },
        "metrics": {
            "workload_end_ns": 20,
            "request_latency_ns": {
                "mean": 20,
                "p95": 20,
            },
            "workflow_completion_time_ns": {
                "mean": 20,
                "p95": 20,
                "max": 20,
                "by_workflow_id": {"workflow-0": 20},
            },
            "resource_cost": {
                "gpu_hbm_account_stack_by_gpu": {
                    "gpu0": {
                        "resource_id": "hbm:gpu0",
                        "capacity_bytes": 100,
                        "final_accounts": {
                            "ACTIVE_PRIMARY_KV": 0,
                            "FOREGROUND_STORE_RESTORE_RESERVED": 0,
                            "FREE": 100,
                        },
                        "peak_account_bytes": {
                            "ACTIVE_PRIMARY_KV": 64,
                            "FOREGROUND_STORE_RESTORE_RESERVED": 0,
                            "FREE": 100,
                        },
                        "event_boundary_snapshot_count": 4,
                        "valid": True,
                    }
                },
                "source_pin_count_final": 0,
                "gpu_hbm_foreground_store_reserve_final_bytes": 0,
            },
            "policy_effects": {
                "landlord_runtime": "FORMAL_SLACK_LANDLORD_CURRENT_DESIGN",
                "formal_suffix_frontier_modeled": True,
                "formal_joint_gain_loss_gate_modeled": True,
                "formal_joint_loss_interpretation": (
                    "RECOMPUTE_ONCE_PER_AFFECTED_REQUEST_FROM_TENTATIVE_VICTIM_SET"
                ),
                "formal_algorithm2_event_count": len(formal_events),
                "aimd_enabled": True,
                "aimd_update_basis": "FIXED_GLOBAL_DES_CONTROL_WINDOW",
                "aimd_quota_lifecycle_uses_formal_safe_tails": True,
                "compute_scheduler_model": "VLLM_CONTINUOUS_BATCH_SCHEDULER_STEP",
                "continuous_batch_residency_modeled": True,
            },
            "pool_audit": {
                "normal_hbm": {
                    "valid": True,
                    "pinned_entry_count_final": 0,
                    "pinned_reference_count_final": 0,
                },
                "peer_hbm": {
                    "valid": True,
                    "per_gpu": {
                        "gpu0": {
                            "valid": True,
                            "final_bytes": 20,
                            "quota_bytes": 35,
                            "physical_capacity_bytes": 100,
                        }
                    },
                },
                "store_dram": {
                    "valid": True,
                    "pinned_entry_count_final": 0,
                    "pinned_reference_count_final": 0,
                    "per_segment": {
                        "segment0": {
                            "valid": True,
                            "final_bytes": 10,
                            "capacity_bytes": 20,
                        }
                    },
                },
                "pending_destination_bytes_final": 0,
                "unattributed_reserve_bytes": 0,
            },
        },
    }
    return payload, representative


def _add_formal_alias(
    payload: dict[str, object],
    representative: dict[str, object],
    *,
    span_id: str,
    physical_key: str,
) -> None:
    representative["formal_algorithm2_events"].insert(
        0,
        {
            "event": "FORMAL_CONTENT_ALIAS_COMMITTED",
            "span_id": span_id,
            "path": "PEER_HBM",
            "pool_id": "PEER_HBM:gpu0",
            "global_sequence_index": 0,
            "physical_chunk_key": physical_key,
            "allocated_bytes": 0,
            "transferred_bytes": 0,
            "timestamp_ns": 0,
        },
    )
    payload["metrics"]["policy_effects"]["formal_algorithm2_event_count"] += 1


def _add_late_peer_preview(payload: dict[str, object], representative: dict[str, object]) -> None:
    landlord = SlackLandlord(
        pool=PolicyPool.PEER_HBM,
        capacity_bytes=10,
        initial_rent=Fraction(1, 10),
    )
    victim = _value(
        "late-victim",
        PolicyPool.PEER_HBM,
        chunk_id="PEER_HBM:gpu0:late-victim:0:late-key",
        sequence_index=0,
        allocated_bytes=10,
        before_ns=1,
        after_ns=0,
        rent=Fraction(1, 10),
    )
    landlord.register_committed(victim)
    gain = _gain("late-candidate", PolicyPool.PEER_HBM, 20, 0)
    candidate = _value(
        "late-candidate",
        PolicyPool.PEER_HBM,
        chunk_id="PEER_HBM:gpu0:late-candidate:0:late-candidate-key",
        sequence_index=0,
        allocated_bytes=10,
        before_ns=20,
        after_ns=0,
        rent=Fraction(1, 10),
    )
    preview = landlord.preview(
        candidate,
        latest_values={victim.candidate.chunk_id: victim},
        candidate_gain_evidence=gain,
        joint_loss_provider=lambda _victims: VictimSetHarmDelta(
            before_by_request=(_snapshot("late-victim", PolicyPool.PEER_HBM, 0),),
            after_by_request=(_snapshot("late-victim", PolicyPool.PEER_HBM, 1),),
        ),
    )
    preview_json = preview.to_canonical_json()
    preview_json["excluded_victim_reasons"] = {}
    representative["formal_algorithm2_events"].append(
        {
            "event": "FORMAL_ALGORITHM2_PREVIEW",
            "path": "PEER_HBM",
            "pool_id": "PEER_HBM:gpu0",
            "span_id": "late-candidate",
            "timestamp_ns": 40,
            "candidate_token_start": 64,
            "candidate_token_count": 1_024,
            "candidate_global_system_template": False,
            "engine_policy_chunk_tokens": 1_024,
            "preview": preview_json,
        }
    )
    payload["metrics"]["policy_effects"]["formal_algorithm2_event_count"] += 1


def test_formal_algorithm_gate_accepts_exact_trace() -> None:
    payload, representative = _artifacts()

    report = audit_formal_algorithm_run(payload, representative).to_dict()

    assert report["status"] == "PASS"
    assert report["schema"] == FORMAL_ALGORITHM_AUDIT_SCHEMA
    assert report["formal_algorithm2_preview_count"] == 2
    assert report["formal_algorithm2_admitted_preview_count"] == 2
    assert report["aimd_decision_count"] == 3
    assert report["continuous_scheduler"] == {
        "duration_provider_count": 1,
        "request_count": 1,
        "step_count": 1,
    }
    assert report["evidence_boundary"]["paper_performance_claim_allowed_by_this_gate"] is False


def test_explicit_no_aimd_ablation_audits_landlord_without_claiming_algorithm3() -> None:
    payload, representative = _artifacts()
    payload["metrics"]["policy_effects"]["aimd_enabled"] = False
    representative["aimd_events"] = []
    report = audit_formal_algorithm_run(
        payload, representative, expected_aimd_enabled=False
    ).to_dict()
    assert report["aimd_enabled"] is False
    assert report["aimd_decision_count"] == 0
    assert report["formal_algorithm2_preview_count"] == 2
    with pytest.raises(FormalAlgorithmAuditError, match="aimd_enabled"):
        audit_formal_algorithm_run(payload, representative)


def test_disabled_aimd_ablation_rejects_observed_control_decisions() -> None:
    payload, representative = _artifacts()
    payload["metrics"]["policy_effects"]["aimd_enabled"] = False
    with pytest.raises(FormalAlgorithmAuditError, match="disabled Algorithm 3"):
        audit_formal_algorithm_run(payload, representative, expected_aimd_enabled=False)


def test_lru_ablation_preserves_aimd_audit_without_fabricated_landlord() -> None:
    payload, representative = _artifacts()
    payload["metrics"]["policy_effects"].update({
        "landlord_runtime": "MODELED_POOL_BASELINE_POLICY",
        "formal_suffix_frontier_modeled": False,
        "formal_joint_gain_loss_gate_modeled": False,
        "formal_algorithm2_event_count": 1,
        "slack_signal_enabled": True,
    })
    representative["formal_algorithm2_events"] = [{
        "event": "FOREGROUND_KV_RECLAIM_PEER_RESULT", "formal_policy_enabled": False,
    }]
    for event in representative["aimd_events"]:
        event.pop("formal_algorithm2_capacity_lifecycle")
    report = audit_lru_ablation_run(payload, representative)
    assert report["algorithm2"] == "NOT_APPLICABLE_REPLACED_WITH_LRU"
    assert report["aimd_decision_count"] == 3
    representative["formal_algorithm2_events"][0]["formal_policy_enabled"] = True
    with pytest.raises(FormalAlgorithmAuditError, match="must not emit"):
        audit_lru_ablation_run(payload, representative)
    representative["formal_algorithm2_events"][0]["formal_policy_enabled"] = False
    representative["aimd_events"][0]["quota_bytes"] += 1
    with pytest.raises(FormalAlgorithmAuditError, match="floor"):
        audit_lru_ablation_run(payload, representative)


def test_formal_audit_error_preserves_messages_across_process_boundary() -> None:
    error = FormalAlgorithmAuditError(["first violation", "second violation"])
    restored = pickle.loads(pickle.dumps(error))
    assert restored.errors == error.errors
    assert str(restored) == str(error)


def test_formal_algorithm_gate_reconstructs_foreground_store_restore() -> None:
    payload, representative = _artifacts()
    representative["foreground_store_events"] = [
        {
            "timestamp_ns": 1,
            "event": "FOREGROUND_STORE_GET_START",
            "span_id": "scheduler-request",
            "transfer_id": "store-get-0",
        },
        {
            "timestamp_ns": 2,
            "event": "FOREGROUND_STORE_GET_SEGMENT_COMPLETE",
            "span_id": "scheduler-request",
            "transfer_id": "store-get-0",
        },
        {
            "timestamp_ns": 2,
            "event": "FOREGROUND_STORE_RESTORE_COMPLETE",
            "span_id": "scheduler-request",
            "segment_transfer_count": 1,
            "destination_account": "FOREGROUND_STORE_RESTORE_RESERVED",
        },
        {
            "timestamp_ns": 3,
            "event": "FOREGROUND_STORE_RESTORE_ADOPTED",
            "span_id": "scheduler-request",
            "adopted_bytes": 64,
        },
    ]

    report = audit_formal_algorithm_run(payload, representative).to_dict()

    assert report["checks"]["foreground_store_restore_transaction_lifecycle"] is True


def test_formal_algorithm_gate_rejects_incomplete_foreground_store_restore() -> None:
    payload, representative = _artifacts()
    representative["foreground_store_events"] = [
        {
            "timestamp_ns": 1,
            "event": "FOREGROUND_STORE_GET_START",
            "span_id": "scheduler-request",
            "transfer_id": "store-get-0",
        },
        {
            "timestamp_ns": 2,
            "event": "FOREGROUND_STORE_GET_SEGMENT_COMPLETE",
            "span_id": "scheduler-request",
            "transfer_id": "store-get-0",
        },
        {
            "timestamp_ns": 2,
            "event": "FOREGROUND_STORE_RESTORE_COMPLETE",
            "span_id": "scheduler-request",
            "segment_transfer_count": 1,
            "destination_account": "FOREGROUND_STORE_RESTORE_RESERVED",
        },
    ]

    with pytest.raises(
        FormalAlgorithmAuditError,
        match="lacks ADOPTED or ABORTED terminal event",
    ):
        audit_formal_algorithm_run(payload, representative)


def test_cross_system_scheduler_gate_accepts_joined_request_and_hbm_evidence() -> None:
    payload, representative = _artifacts()

    report = audit_continuous_scheduler_evidence(payload, representative).to_dict()

    assert report["schema"] == CONTINUOUS_SCHEDULER_AUDIT_SCHEMA
    assert report["status"] == "PASS"
    assert report["request_count"] == 1
    assert report["terminal_request_count"] == 1
    assert report["hbm_resource_ids"] == ["hbm:gpu0"]
    assert report["evidence_boundary"] == {
        "calibrated_physical_performance": False,
        "claim_scope": "continuous_scheduler_trace_structure_only",
        "paper_performance_claim_allowed_by_this_gate": False,
        "physical_execution": False,
    }


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("participant", "unknown request"),
        ("terminal", "non-participant request"),
    ],
)
def test_scheduler_gate_rejects_orphan_step_request_ids(
    field: str,
    message: str,
) -> None:
    payload, representative = _artifacts()
    [step] = representative["continuous_batch_scheduler"]["steps"]
    if field == "participant":
        step["participants"][0]["request_id"] = "not-a-request"
    else:
        step["completion"]["terminal_output_request_ids"] = ["not-a-request"]

    with pytest.raises(FormalAlgorithmAuditError, match=message):
        audit_continuous_scheduler_evidence(payload, representative)


def test_scheduler_gate_rejects_duplicate_terminal_completion() -> None:
    payload, representative = _artifacts()
    [step] = representative["continuous_batch_scheduler"]["steps"]
    step["completion"]["terminal_output_request_ids"] = [
        "scheduler-request",
        "scheduler-request",
    ]

    with pytest.raises(FormalAlgorithmAuditError, match="more than once"):
        audit_continuous_scheduler_evidence(payload, representative)


@pytest.mark.parametrize("target", ["request", "payload"])
def test_scheduler_gate_rejects_request_or_payload_wct_tampering(target: str) -> None:
    payload, representative = _artifacts()
    if target == "request":
        [request] = representative["continuous_batch_scheduler"]["requests"]
        request["wct_ns"] = 19
    else:
        payload["metrics"]["workflow_completion_time_ns"]["by_workflow_id"][
            "workflow-0"
        ] = 19

    with pytest.raises(FormalAlgorithmAuditError, match="reconstruct"):
        audit_continuous_scheduler_evidence(payload, representative)


@pytest.mark.parametrize("target", ["snapshot", "payload_summary"])
def test_scheduler_gate_rejects_hbm_authority_or_account_tampering(target: str) -> None:
    payload, representative = _artifacts()
    if target == "snapshot":
        [step] = representative["continuous_batch_scheduler"]["steps"]
        snapshot = step["resident_after_schedule"]
        snapshot["resident_primary_bytes"] = 32
        snapshot["bytes_by_hbm_resource"]["hbm:gpu0"] = 32
    else:
        payload["metrics"]["resource_cost"]["gpu_hbm_account_stack_by_gpu"]["gpu0"][
            "final_accounts"
        ]["ACTIVE_PRIMARY_KV"] = 1

    with pytest.raises(FormalAlgorithmAuditError, match=r"HBM|account|reconstruct"):
        audit_continuous_scheduler_evidence(payload, representative)


def test_rent_chronology_merges_earlier_aimd_with_later_preview() -> None:
    payload, representative = _artifacts()
    _add_late_peer_preview(payload, representative)

    report = audit_formal_algorithm_run(payload, representative)

    assert report.preview_count == 3


def test_rent_chronology_rejects_real_cross_list_refund() -> None:
    payload, representative = _artifacts()
    lifecycle = representative["aimd_events"][0]["formal_algorithm2_capacity_lifecycle"]
    lifecycle["rent_before"] = {"numerator": 0, "denominator": 1}

    with pytest.raises(FormalAlgorithmAuditError, match="merged DES chronology"):
        audit_formal_algorithm_run(payload, representative)


def test_rent_chronology_ignores_unapplied_admission_proposed_rent() -> None:
    payload, representative = _artifacts()
    peer_event = representative["formal_algorithm2_events"][1]
    preview = peer_event["preview"]
    preview["landlord_applied"] = False

    report = audit_formal_algorithm_run(payload, representative)

    assert report.preview_count == 2


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("gain_A_ns", "candidate G/A is not exact"),
        ("joint_loss_D_ns", "joint loss D is not the exact"),
    ],
)
def test_formal_algorithm_gate_rejects_tampered_exact_harm(
    field: str,
    message: str,
) -> None:
    payload, representative = _artifacts()
    preview = representative["formal_algorithm2_events"][0]["preview"]
    if field == "gain_A_ns":
        preview["candidate_gain_evidence"][field] = {"numerator": 19, "denominator": 1}
    else:
        preview["joint_loss_evidence"][field] = {"numerator": 2, "denominator": 1}

    with pytest.raises(FormalAlgorithmAuditError, match=message):
        audit_formal_algorithm_run(payload, representative)


def test_victim_set_d_includes_content_alias_harm() -> None:
    payload, representative = _artifacts()
    _add_formal_alias(
        payload,
        representative,
        span_id="alias-request",
        physical_key="content-key",
    )
    preview = representative["formal_algorithm2_events"][1]["preview"]
    preview["joint_loss_evidence"]["before_by_request"].append(
        _snapshot("alias-request", PolicyPool.PEER_HBM, 0).to_canonical_json()
    )
    preview["joint_loss_evidence"]["after_by_request"].append(
        _snapshot("alias-request", PolicyPool.PEER_HBM, 2).to_canonical_json()
    )
    exact_d = {"numerator": 3, "denominator": 1}
    preview["joint_loss_evidence"]["joint_loss_D_ns"] = exact_d
    preview["joint_loss_D_Y"] = exact_d

    audit_formal_algorithm_run(payload, representative)


def test_victim_set_d_matches_alias_with_formal_attempt_suffix() -> None:
    payload, representative = _artifacts()
    _add_formal_alias(
        payload,
        representative,
        span_id="alias-request",
        physical_key="content-key",
    )
    preview = representative["formal_algorithm2_events"][1]["preview"]
    preview["selected_victims"][0]["candidate"]["chunk_id"] = (
        "PEER_HBM:gpu0:victim:0:content-key:attempt:peer-put:candidate-0"
    )
    preview["joint_loss_evidence"]["before_by_request"].append(
        _snapshot("alias-request", PolicyPool.PEER_HBM, 0).to_canonical_json()
    )
    preview["joint_loss_evidence"]["after_by_request"].append(
        _snapshot("alias-request", PolicyPool.PEER_HBM, 2).to_canonical_json()
    )
    exact_d = {"numerator": 3, "denominator": 1}
    preview["joint_loss_evidence"]["joint_loss_D_ns"] = exact_d
    preview["joint_loss_D_Y"] = exact_d

    audit_formal_algorithm_run(payload, representative)


def test_victim_set_d_rejects_omitted_content_alias_harm() -> None:
    payload, representative = _artifacts()
    _add_formal_alias(
        payload,
        representative,
        span_id="alias-request",
        physical_key="content-key",
    )

    with pytest.raises(FormalAlgorithmAuditError, match="affected content aliases"):
        audit_formal_algorithm_run(payload, representative)


def test_candidate_alias_dependency_requires_physical_victim_exclusion() -> None:
    payload, representative = _artifacts()
    _add_formal_alias(
        payload,
        representative,
        span_id="peer-candidate",
        physical_key="dependency-key",
    )
    preview = representative["formal_algorithm2_events"][1]["preview"]
    preview["excluded_victim_chunk_ids"] = ["PEER_HBM:gpu0:dependency-owner:0:dependency-key"]
    preview["excluded_victim_reasons"] = {
        "PEER_HBM:gpu0:dependency-owner:0:dependency-key": [
            "CANDIDATE_PHYSICAL_ALIAS"
        ]
    }

    audit_formal_algorithm_run(payload, representative)

    preview["excluded_victim_chunk_ids"] = []
    preview["excluded_victim_reasons"] = {}
    with pytest.raises(FormalAlgorithmAuditError, match="alias dependency is absent"):
        audit_formal_algorithm_run(payload, representative)


def test_candidate_alias_dependency_accepts_formal_attempt_suffix() -> None:
    payload, representative = _artifacts()
    _add_formal_alias(
        payload,
        representative,
        span_id="peer-candidate",
        physical_key="dependency-key",
    )
    preview = representative["formal_algorithm2_events"][1]["preview"]
    chunk_id = (
        "PEER_HBM:gpu0:dependency-owner:0:dependency-key:"
        "attempt:peer-put:candidate-0"
    )
    preview["excluded_victim_chunk_ids"] = [chunk_id]
    preview["excluded_victim_reasons"] = {
        chunk_id: ["CANDIDATE_PHYSICAL_ALIAS"]
    }

    audit_formal_algorithm_run(payload, representative)


def test_non_alias_victim_exclusion_requires_explicit_reason() -> None:
    payload, representative = _artifacts()
    preview = representative["formal_algorithm2_events"][1]["preview"]
    chunk_id = "PEER_HBM:gpu0:pending-owner:0:pending-key"
    preview["excluded_victim_chunk_ids"] = [chunk_id]
    preview["excluded_victim_reasons"] = {
        chunk_id: ["PENDING_SUCCESSOR_CONTIGUITY"]
    }

    audit_formal_algorithm_run(payload, representative)

    preview["excluded_victim_reasons"] = {
        chunk_id: ["CANDIDATE_PHYSICAL_ALIAS"]
    }
    with pytest.raises(
        FormalAlgorithmAuditError,
        match="not a recorded candidate alias dependency",
    ):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_same_request_victim_and_nonsuffix() -> None:
    payload, representative = _artifacts()
    preview = representative["formal_algorithm2_events"][0]["preview"]
    victim = preview["selected_victims"][0]
    victim["candidate"]["request_id"] = "peer-candidate"

    with pytest.raises(FormalAlgorithmAuditError, match="same-request victim exclusion"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_non_strict_h_boundary() -> None:
    payload, representative = _artifacts()
    preview = representative["formal_algorithm2_events"][0]["preview"]
    preview["threshold_Theta"] = preview["selected_victims"][0]["H"]

    with pytest.raises(FormalAlgorithmAuditError, match="strict H_y < Theta"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_non_strict_a_d_boundary() -> None:
    payload, representative = _artifacts()
    preview = representative["formal_algorithm2_events"][1]["preview"]
    zero = {"numerator": 0, "denominator": 1}
    before = preview["candidate_gain_evidence"]["before"]
    before["harm_J_ns"] = zero
    before["recovery_time"]["load_ns"] = zero
    before["recovery_time"]["total_ns"] = zero
    preview["candidate_gain_evidence"]["gain_A_ns"] = zero
    for name in ("G", "W", "P", "H"):
        preview["candidate_value"][name] = zero
    preview["threshold_Theta"] = zero

    with pytest.raises(FormalAlgorithmAuditError, match="strict A > D"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_pending_recovery_visibility() -> None:
    payload, representative = _artifacts()
    representative["recovery_source_events"][0]["state"] = "PENDING"

    with pytest.raises(FormalAlgorithmAuditError, match="PENDING object appeared"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_early_additive_increase() -> None:
    payload, representative = _artifacts()
    event = representative["aimd_events"][1]
    event["action"] = "ADDITIVE_INCREASE"
    event["next_state"]["protection_fraction"] = "0.35"
    event["next_state"]["stable_windows"] = 0
    event["quota_bytes"] = 35
    event["formal_algorithm2_capacity_lifecycle"]["capacity_bytes_after"] = 35

    with pytest.raises(FormalAlgorithmAuditError, match="K-window AI"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_pressure_after_windowed_md() -> None:
    payload, representative = _artifacts()
    representative["hbm_pressure_observations"][0]["timestamp_ns"] = 11

    with pytest.raises(FormalAlgorithmAuditError, match="control-window MD"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_accepts_terminal_pending_pressure() -> None:
    payload, representative = _artifacts()
    representative["hbm_pressure_observations"].append(
        {"timestamp_ns": 31, "target_gpu_id": "gpu0", "reason": "HEADROOM"}
    )
    representative["aimd_terminal_state"] = {
        "gpu0": {
            "control_window_canceled_at_workload_completion": True,
            "pending_pressure": True,
            "pending_shortfall_bytes": 1,
            "pending_pressure_active_requests": 1,
            "pending_pressure_reasons": ["HEADROOM"],
        }
    }

    audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_unlatched_terminal_pressure() -> None:
    payload, representative = _artifacts()
    representative["hbm_pressure_observations"].append(
        {"timestamp_ns": 31, "target_gpu_id": "gpu0", "reason": "HEADROOM"}
    )
    representative["aimd_terminal_state"] = {
        "gpu0": {
            "control_window_canceled_at_workload_completion": True,
            "pending_pressure": False,
            "pending_shortfall_bytes": 0,
            "pending_pressure_active_requests": 0,
            "pending_pressure_reasons": [],
        }
    }

    with pytest.raises(FormalAlgorithmAuditError, match="control-window MD"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_noncontiguous_quota_tail() -> None:
    payload, representative = _artifacts()
    lifecycle = representative["aimd_events"][0]["formal_algorithm2_capacity_lifecycle"]
    extra = deepcopy(lifecycle["released_entries"][0])
    extra["candidate"]["chunk_id"] = "quota-request-3"
    extra["candidate"]["sequence_index"] = 3
    lifecycle["released_entries"].append(extra)
    lifecycle["released_bytes"] += extra["actual_allocated_bytes"]

    with pytest.raises(FormalAlgorithmAuditError, match="not safe suffix tails"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_projected_or_smoothed_artifacts() -> None:
    payload, representative = _artifacts()
    payload["figure_source"] = "smoothed_projection"

    with pytest.raises(FormalAlgorithmAuditError, match="projected/smoothed"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_allows_internal_schedule_projection_name() -> None:
    payload, representative = _artifacts()
    representative["failure_schedule"] = {
        "transform_function": "project_failure_schedule_to_profile"
    }

    audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_physical_byte_nonconservation() -> None:
    payload, representative = _artifacts()
    representative["peer_hbm_timelines"]["gpu0"][1]["occupied_bytes"] = 21

    with pytest.raises(FormalAlgorithmAuditError, match="committed plus pending"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_coalesced_policy_candidate() -> None:
    payload, representative = _artifacts()
    event = representative["formal_algorithm2_events"][1]
    event["candidate_token_count"] = 2_048

    with pytest.raises(FormalAlgorithmAuditError, match="policy-chunk granularity"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_rejects_capability_label_without_scheduler_trace() -> None:
    payload, representative = _artifacts()
    representative["continuous_batch_scheduler"] = None

    with pytest.raises(FormalAlgorithmAuditError, match="continuous_batch_scheduler"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_is_fail_closed_without_formal_previews() -> None:
    payload, representative = _artifacts()
    representative["formal_algorithm2_events"] = []
    payload["metrics"]["policy_effects"]["formal_algorithm2_event_count"] = 0

    with pytest.raises(FormalAlgorithmAuditError, match="requires at least one"):
        audit_formal_algorithm_run(payload, representative)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("continuous_batch_residency_modeled", False),
        ("compute_scheduler_model", "ONE_NONPREEMPTIVE_REQUEST_LANE_PER_GPU"),
    ],
)
def test_paper_gate_blocks_noncontinuous_request_lane(
    field: str,
    value: object,
) -> None:
    payload, representative = _artifacts()
    payload["metrics"]["policy_effects"][field] = value

    with pytest.raises(FormalAlgorithmAuditError, match=field):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_does_not_accept_missing_store_landlord() -> None:
    payload, representative = _artifacts()
    representative["formal_algorithm2_events"] = [representative["formal_algorithm2_events"][0]]
    payload["metrics"]["policy_effects"]["formal_algorithm2_event_count"] = 1

    with pytest.raises(FormalAlgorithmAuditError, match="Store-DRAM landlord"):
        audit_formal_algorithm_run(payload, representative)


def test_formal_algorithm_gate_does_not_mutate_input_artifacts() -> None:
    payload, representative = _artifacts()
    expected_payload = deepcopy(payload)
    expected_representative = deepcopy(representative)

    audit_formal_algorithm_run(payload, representative)

    assert payload == expected_payload
    assert representative == expected_representative
