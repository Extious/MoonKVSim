from __future__ import annotations

import hashlib
from typing import Any, cast

import pytest

from moonkvsim.aegiskv.continuous_batch_des import (
    AegisContinuousBatchDESDriver,
    ContinuousBatchRequestSpec,
    ObservedIdealRequestDuration,
    ObservedIdealTraceDurationProvider,
    ScheduledGPUFailure,
)
from moonkvsim.aegiskv.scheduler_step_bridge import (
    AegisSchedulerStepBridge,
    SchedulerExecutionBinding,
    StepDurationEvidenceClass,
)
from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.hbm_block_ledger import (
    HbmBlockLedgerBridge,
    HbmStageRankBinding,
)
from moonkvsim.integration.vllm.kv_layout import StageBlockLayout
from moonkvsim.integration.vllm.scheduler import ContinuousBatchScheduler
from moonkvsim.predictor.schema import ForwardBoundary, PredictionProfile
from moonkvsim.predictor.vllm_adapter import VLLMSchedulerBatchAdapter
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.event import EventKind
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _profile() -> PredictionProfile:
    return PredictionProfile(
        provider_name="observed-ideal-trace-token-share",
        provider_version="v1-modeled-uncalibrated",
        provider_source_revision="1" * 40,
        database_mode="observed-ideal-request-durations",
        database_sha256=_sha256(b"fixture-observed-ideal-request-durations"),
        hardware_profile_id="fixture-a100-shape",
        hardware_profile_fingerprint=_sha256(b"fixture-a100-shape"),
        model_id="Qwen/Qwen3-8B",
        model_revision="b968826d9c46dd6066d109eabc6255188de91218",
        tensor_parallel_size=1,
        pipeline_parallel_size=1,
        forward_boundary=ForwardBoundary(includes_model_collectives=False),
    )


def _layout() -> StageBlockLayout:
    return StageBlockLayout(
        pp_stage=0,
        tensor_parallel_rank=0,
        block_size_tokens=4,
        layer_names=("model.layers.0.self_attn",),
        layer_indices=(0,),
        tensor_payload_bytes=48,
        auxiliary_payload_bytes=0,
        payload_bytes=48,
        layout_padding_bytes=8,
        allocator_metadata_bytes=4,
        requested_bytes=56,
        internal_fragmentation_bytes=4,
        allocated_bytes=64,
        allocator_alignment_bytes=16,
    )


def _bridge(
    des: GlobalDES,
    *,
    index: int,
    max_running: int = 3,
    token_budget: int = 12,
) -> AegisSchedulerStepBridge:
    profile = _profile()
    resource_id = f"gpu-{index}.hbm"
    registry = AllocationRegistry(journal=des.journal)
    ledger = CapacityLedger(
        resource_id=resource_id,
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=64 * 64,
    )
    hbm = HbmBlockLedgerBridge(
        bridge_id=f"fixture-hbm-dp{index}",
        bindings=(HbmStageRankBinding(resource_id, _layout()),),
        ledgers={resource_id: ledger},
        registry=registry,
        journal=des.journal,
        now_ns=lambda: des.now_ns,
    )
    scheduler = ContinuousBatchScheduler(
        block_pool=BlockPool(65, enable_caching=False),
        block_size_tokens=4,
        max_num_scheduled_tokens=token_budget,
        max_num_running_requests=max_running,
        block_lifecycle_observer=hbm,
    )
    provider = ObservedIdealTraceDurationProvider(
        prediction_profile=profile,
        trace_provenance_sha256=_sha256(b"fixture-ideal-trace-manifest"),
    )
    return AegisSchedulerStepBridge(
        bridge_id=f"aegis-dp{index}",
        execution_binding=SchedulerExecutionBinding(
            target_id=f"dp-{index}",
            gpu_id=f"gpu-{index}",
            failure_domain_id=f"host-{index}/gpu-{index}",
            kv_abi="vllm-v1-ordinary-full-attention",
            kv_layout_id="fixture-qwen3-8b-tp1-pp1",
            kv_layout_sha256=_sha256(b"fixture-qwen3-8b-tp1-pp1"),
        ),
        scheduler=scheduler,
        prediction_profile=profile,
        duration_provider=provider,
        adapter=VLLMSchedulerBatchAdapter(),
    )


def _mixed_run() -> tuple[dict[str, Any], bytes]:
    des = GlobalDES()
    bridge = _bridge(des, index=0, max_running=3, token_budget=8)
    driver = AegisContinuousBatchDESDriver(des=des, bridges=(bridge,))
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="decode-first",
            release_ns=0,
            prompt_tokens=4,
            max_output_tokens=2,
            observed_ideal_duration_ns=500,
        )
    )
    # First prefill consumes ceil(500 * 4 / 5) = 400 ns.  The release at
    # exactly 400 ns is admitted before the newly requested next step.
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="late-prefill",
            release_ns=400,
            prompt_tokens=4,
            max_output_tokens=2,
            observed_ideal_duration_ns=500,
        )
    )
    return cast(dict[str, Any], driver.run().to_dict()), des.journal.to_jsonl_bytes()


def test_driver_does_not_claim_causal_release_request_arrival_event() -> None:
    des = GlobalDES()
    des.register_handler(EventKind.REQUEST_ARRIVAL, lambda _event, _des: None)

    driver = AegisContinuousBatchDESDriver(
        des=des,
        bridges=(_bridge(des, index=0),),
        register_failure_handler=False,
    )
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="coexists-with-causal-release",
            release_ns=0,
            prompt_tokens=4,
            max_output_tokens=1,
            observed_ideal_duration_ns=100,
        )
    )

    assert driver.run().requests[0]["completion_ns"] is not None


def test_mixed_prefill_decode_and_multiple_resident_requests_execute_one_step() -> None:
    result, _journal = _mixed_run()

    assert result["calibration_boundary"] == (
        "MODELED_UNCALIBRATED_NOT_PHYSICAL_BATCH_LATENCY_EVIDENCE"
    )
    evidence = result["duration_evidence"]
    assert isinstance(evidence, list)
    assert evidence[0]["evidence_class"] == StepDurationEvidenceClass.UNCALIBRATED_MODEL
    assert evidence[0]["physically_measured"] is False
    assert evidence[0]["formal_use_allowed"] is False
    steps = result["steps"]
    assert isinstance(steps, list)
    mixed = [step for step in steps if step["is_mixed_phase"]]
    assert len(mixed) == 1
    [mixed_step] = mixed
    assert mixed_step["start_ns"] == 400
    assert mixed_step["planned_end_ns"] == 800
    assert {item["request_id"] for item in mixed_step["participants"]} == {
        "decode-first",
        "late-prefill",
    }
    assert {item["phase"] for item in mixed_step["participants"]} == {
        "PREFILL",
        "DECODE",
    }
    assert mixed_step["resident_after_schedule"]["resident_primary_request_count"] == 2
    # decode-first owns prompt+decode blocks while late-prefill owns its prompt.
    assert mixed_step["resident_after_schedule"]["resident_primary_block_count"] == 3
    assert mixed_step["resident_after_schedule"]["resident_primary_bytes"] == 192
    requests = {item["spec"]["request_id"]: item for item in result["requests"]}
    assert requests["decode-first"]["completion_ns"] == 800
    assert requests["late-prefill"]["completion_ns"] == 900


def test_target_load_snapshot_counts_route_bound_pending_tokens() -> None:
    des = GlobalDES()
    bridge = _bridge(des, index=0)
    driver = AegisContinuousBatchDESDriver(des=des, bridges=(bridge,))
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="pending-a",
            release_ns=100,
            prompt_tokens=8,
            max_output_tokens=3,
            observed_ideal_duration_ns=500,
            initial_target_id="dp-0",
        )
    )
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="pending-b",
            release_ns=200,
            prompt_tokens=4,
            max_output_tokens=2,
            observed_ideal_duration_ns=300,
            initial_target_id="dp-0",
        )
    )

    snapshot = driver.target_load_snapshot("dp-0")

    assert snapshot["resident_request_count"] == 0
    assert snapshot["pending_admission_count"] == 2
    assert snapshot["queued_tokens"] == (8 + 3 - 1) + (4 + 2 - 1)
    assert snapshot["estimated_available_ns"] == 600


def _failure_run() -> tuple[dict[str, Any], bytes]:
    des = GlobalDES()
    bridges = (_bridge(des, index=0), _bridge(des, index=1))
    driver = AegisContinuousBatchDESDriver(des=des, bridges=bridges)
    for request_id in ("r0", "r1", "r2"):
        driver.submit(
            ContinuousBatchRequestSpec(
                request_id=request_id,
                release_ns=0,
                prompt_tokens=4,
                max_output_tokens=1,
                observed_ideal_duration_ns=100,
                initial_target_id="dp-0",
            )
        )
    # FAILURE priority precedes FORWARD_COMPLETE at the same timestamp.  This
    # makes the canceled old completion a direct stale-step-fence test.
    driver.inject_gpu_failure(
        ScheduledGPUFailure(
            failure_id="failure-0",
            target_id="dp-0",
            timestamp_ns=100,
        )
    )
    return cast(dict[str, Any], driver.run().to_dict()), des.journal.to_jsonl_bytes()


def test_failure_fences_multi_request_forward_and_requeues_without_lost_hbm_reuse() -> None:
    result, journal = _failure_run()

    steps = result["steps"]
    assert isinstance(steps, list)
    old = [step for step in steps if step["target_id"] == "dp-0"]
    assert len(old) == 1
    [fenced] = old
    assert fenced["status"] == "FENCED"
    assert fenced["effective_end_ns"] == 100
    assert len(fenced["participants"]) == 3
    assert fenced["completion"] is None
    recovered = [step for step in steps if step["target_id"] == "dp-1"]
    assert len(recovered) == 1
    assert recovered[0]["status"] == "COMPLETED"
    assert recovered[0]["start_ns"] == 100
    assert recovered[0]["effective_end_ns"] == 200

    [failure] = result["failures"]
    snapshot = failure["snapshot"]
    assert snapshot["running_request_ids"] == ["r0", "r1", "r2"]
    assert snapshot["active_step_id"] == fenced["step_id"]
    assert snapshot["physical_hbm_failure_applied"] is False
    assert failure["recovery_mode"] == (
        "EXTERNAL_PREFIX_SELECTION_THEN_PROMPT_SUFFIX_RECOMPUTE_AND_SILENT_REPLAY_NO_LOST_HBM_REUSE"
    )
    assert failure["requeue_targets"] == {"r0": "dp-1", "r1": "dp-1", "r2": "dp-1"}
    requests = result["requests"]
    assert all(item["route_version"] == 1 for item in requests)
    assert all(item["completion_ns"] == 200 for item in requests)
    assert all(item["router_committed_output_tokens"] == 1 for item in requests)
    assert b'"record_type":"EVENT_CANCELED"' in journal


def test_driver_and_journal_are_byte_deterministic() -> None:
    first_result, first_journal = _failure_run()
    second_result, second_journal = _failure_run()

    assert first_result == second_result
    assert first_journal == second_journal
    assert first_result["journal_sha256"] == hashlib.sha256(first_journal).hexdigest()


def test_failure_fences_route_bound_future_admission_and_preserves_ready_time() -> None:
    des = GlobalDES()
    driver = AegisContinuousBatchDESDriver(
        des=des,
        bridges=(_bridge(des, index=0), _bridge(des, index=1)),
    )
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="route-bound",
            release_ns=100,
            prompt_tokens=4,
            max_output_tokens=1,
            observed_ideal_duration_ns=100,
            initial_target_id="dp-0",
            route_bound_before_admission=True,
        )
    )
    driver.inject_gpu_failure(
        ScheduledGPUFailure(
            failure_id="failure-before-ready",
            target_id="dp-0",
            timestamp_ns=50,
        )
    )

    result = driver.run()

    [failure] = result.failures
    assert failure["snapshot"]["pending_admission_request_ids"] == ["route-bound"]
    [pending] = failure["snapshot"]["pending_admissions"]
    assert pending["cause"] == "INITIAL_RELEASE"
    assert pending["ready_ns"] == 100
    [request] = result.requests
    assert request["route_version"] == 1
    assert request["route_history"] == [
        {
            "timestamp_ns": 100,
            "route_version": 1,
            "target_id": "dp-1",
            "cause": "GPU_FAILURE_REQUEUE:failure-before-ready",
        }
    ]


def test_unbound_future_arrival_keeps_route_zero_and_selects_healthy_gpu() -> None:
    des = GlobalDES()
    driver = AegisContinuousBatchDESDriver(
        des=des,
        bridges=(_bridge(des, index=0), _bridge(des, index=1)),
    )
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="unbound",
            release_ns=100,
            prompt_tokens=4,
            max_output_tokens=1,
            observed_ideal_duration_ns=100,
        )
    )
    driver.inject_gpu_failure(
        ScheduledGPUFailure(
            failure_id="failure-before-arrival",
            target_id="dp-0",
            timestamp_ns=50,
        )
    )

    result = driver.run()

    assert result.failures[0]["snapshot"]["pending_admissions"] == []
    [request] = result.requests
    assert request["route_version"] == 0
    assert request["route_history"][0]["target_id"] == "dp-1"


def test_external_failure_hands_off_route_bound_pending_admission() -> None:
    des = GlobalDES()
    driver = AegisContinuousBatchDESDriver(
        des=des,
        bridges=(_bridge(des, index=0), _bridge(des, index=1)),
        register_failure_handler=False,
    )
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="external-pending",
            release_ns=100,
            prompt_tokens=4,
            max_output_tokens=1,
            observed_ideal_duration_ns=100,
            initial_target_id="dp-0",
            route_bound_before_admission=True,
        )
    )
    handoff: list[dict[str, object]] = []

    def fence(_event: Any, _des: GlobalDES) -> None:
        snapshot = driver.fence_for_external_gpu_failure(
            failure_id="external-failure",
            target_id="dp-0",
            reason="fixture",
        )
        handoff.extend(item.to_dict() for item in snapshot.pending_admissions)
        driver.resume_external_request(
            request_id="external-pending",
            target_id="dp-1",
            route_version=1,
            ready_ns=100,
        )

    des.register_handler(EventKind.FAILURE_INJECT, fence)
    des.schedule_at(50, EventKind.FAILURE_INJECT)

    result = driver.run()

    assert handoff == [
        {
            "request_id": "external-pending",
            "event_id": "event-0000000000000000",
            "cause": "INITIAL_RELEASE",
            "route_version": 0,
            "target_id": "dp-0",
            "ready_ns": 100,
            "restored_tokens": 0,
            "router_committed_output_tokens": 0,
            "silent_replay_target": 0,
        }
    ]
    [request] = result.requests
    assert request["route_version"] == 1
    assert request["route_history"][0]["target_id"] == "dp-1"


def test_before_admit_exception_calls_abort_without_publishing_route() -> None:
    des = GlobalDES()
    bridge = _bridge(des, index=0)
    aborts: list[tuple[str, str, int, str, int]] = []

    def reject_before(
        _target_id: str,
        _spec: ContinuousBatchRequestSpec,
        _route_version: int,
        _cause: str,
        _restored_tokens: int,
    ) -> None:
        raise RuntimeError("fixture before-admit rejection")

    driver = AegisContinuousBatchDESDriver(
        des=des,
        bridges=(bridge,),
        on_before_admit=reject_before,
        on_admit_abort=lambda target_id, spec, route_version, cause, restored: aborts.append(
            (target_id, spec.request_id, route_version, cause, restored)
        ),
    )
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="before-abort",
            release_ns=0,
            prompt_tokens=4,
            max_output_tokens=1,
            observed_ideal_duration_ns=100,
            initial_target_id="dp-0",
            initial_restored_tokens=4,
        )
    )

    with pytest.raises(RuntimeError, match="before-admit rejection"):
        driver.run()

    runtime = driver._requests["before-abort"]
    assert runtime.target_id is None
    assert runtime.route_history == []
    assert bridge.scheduler.running_request_ids == ()
    assert bridge.scheduler.waiting_request_ids == ()
    assert aborts == [("dp-0", "before-abort", 0, "INITIAL_RELEASE", 4)]
    assert all(record.record_type != "AegisRequestAdmitted" for record in des.journal.records)


def test_after_admit_exception_rolls_back_bridge_before_abort_callback() -> None:
    des = GlobalDES()
    bridge = _bridge(des, index=0)
    abort_observations: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def reject_after(
        _target_id: str,
        _spec: ContinuousBatchRequestSpec,
        _route_version: int,
        _cause: str,
        _restored_tokens: int,
    ) -> None:
        assert bridge.scheduler.waiting_request_ids == ("after-abort",)
        raise RuntimeError("fixture after-admit rejection")

    def observe_abort(
        _target_id: str,
        _spec: ContinuousBatchRequestSpec,
        _route_version: int,
        _cause: str,
        _restored_tokens: int,
    ) -> None:
        abort_observations.append(
            (
                bridge.scheduler.running_request_ids,
                bridge.scheduler.waiting_request_ids,
            )
        )

    driver = AegisContinuousBatchDESDriver(
        des=des,
        bridges=(bridge,),
        on_after_admit=reject_after,
        on_admit_abort=observe_abort,
    )
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="after-abort",
            release_ns=0,
            prompt_tokens=4,
            max_output_tokens=1,
            observed_ideal_duration_ns=100,
            initial_target_id="dp-0",
            initial_restored_tokens=4,
        )
    )

    with pytest.raises(RuntimeError, match="after-admit rejection"):
        driver.run()

    runtime = driver._requests["after-abort"]
    assert runtime.target_id is None
    assert runtime.route_history == []
    assert abort_observations == [((), ())]
    assert bridge.scheduler.running_request_ids == ()
    assert bridge.scheduler.waiting_request_ids == ()
    assert all(record.record_type != "AegisRequestAdmitted" for record in des.journal.records)


def test_second_failure_fences_future_external_resume_without_stale_revival() -> None:
    des = GlobalDES()
    driver = AegisContinuousBatchDESDriver(
        des=des,
        bridges=tuple(_bridge(des, index=index) for index in range(3)),
        register_failure_handler=False,
    )
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="twice-fenced",
            release_ns=0,
            prompt_tokens=4,
            max_output_tokens=1,
            observed_ideal_duration_ns=100,
            initial_target_id="dp-0",
        )
    )
    snapshots: list[dict[str, object]] = []

    def fence(event: Any, _des: GlobalDES) -> None:
        failure_id = str(event.payload["failure_id"])
        target_id = str(event.payload["target_id"])
        snapshot = driver.fence_for_external_gpu_failure(
            failure_id=failure_id,
            target_id=target_id,
            reason="fixture repeated pending-admission fence",
        )
        snapshots.append(snapshot.to_dict())
        route_version = 1 if failure_id == "failure-0" else 2
        resume_target = "dp-1" if failure_id == "failure-0" else "dp-2"
        driver.resume_external_request(
            request_id="twice-fenced",
            target_id=resume_target,
            route_version=route_version,
            ready_ns=100,
            restored_tokens=4,
        )

    des.register_handler(EventKind.FAILURE_INJECT, fence)
    des.schedule_at(
        1,
        EventKind.FAILURE_INJECT,
        payload={"failure_id": "failure-0", "target_id": "dp-0"},
    )
    des.schedule_at(
        50,
        EventKind.FAILURE_INJECT,
        payload={"failure_id": "failure-1", "target_id": "dp-1"},
    )

    result = driver.run()

    assert snapshots[0]["pending_admission_request_ids"] == []
    assert snapshots[1]["pending_admission_request_ids"] == ["twice-fenced"]
    [pending] = cast(list[dict[str, object]], snapshots[1]["pending_admissions"])
    assert pending["route_version"] == 1
    assert pending["target_id"] == "dp-1"
    assert pending["ready_ns"] == 100
    assert pending["restored_tokens"] == 4
    [request] = result.requests
    assert request["route_version"] == 2
    assert request["route_history"] == [
        {
            "timestamp_ns": 0,
            "route_version": 0,
            "target_id": "dp-0",
            "cause": "INITIAL_RELEASE",
        },
        {
            "timestamp_ns": 100,
            "route_version": 2,
            "target_id": "dp-2",
            "cause": "EXTERNAL_FAILURE_OWNER_REQUEUE",
        },
    ]
    assert all(
        not (step["target_id"] == "dp-1" and step["start_ns"] >= 100) for step in result.steps
    )


def test_full_recompute_failure_requeue_does_not_gain_recovery_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    des = GlobalDES()
    bridge = _bridge(des, index=0)
    driver = AegisContinuousBatchDESDriver(
        des=des,
        bridges=(bridge,),
        register_failure_handler=False,
    )
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="full-recompute",
            release_ns=0,
            prompt_tokens=8,
            max_output_tokens=2,
            observed_ideal_duration_ns=100,
            initial_target_id="dp-0",
        )
    )
    des.run(until_ns=0)
    snapshot = driver.fence_for_external_gpu_failure(
        failure_id="failure-0",
        target_id="dp-0",
        reason="fixture GPU failure",
    )
    assert tuple(item.request_id for item in snapshot.requests) == ("full-recompute",)
    replacement = _bridge(des, index=0)
    driver.replace_repaired_target(replacement)
    prioritized: list[str] = []
    monkeypatch.setattr(
        replacement,
        "prioritize_waiting_recovery",
        lambda request_id: prioritized.append(request_id),
    )

    driver.resume_external_request(
        request_id="full-recompute",
        target_id="dp-0",
        route_version=1,
        restored_tokens=0,
    )

    assert prioritized == []


def test_repaired_bridges_keep_step_ids_unique_across_gpus_and_failures() -> None:
    des = GlobalDES()
    driver = AegisContinuousBatchDESDriver(
        des=des,
        bridges=(_bridge(des, index=0), _bridge(des, index=1)),
        register_failure_handler=False,
    )
    for index in range(2):
        driver.submit(
            ContinuousBatchRequestSpec(
                request_id=f"r{index}",
                release_ns=0,
                prompt_tokens=4,
                max_output_tokens=4,
                observed_ideal_duration_ns=700,
                initial_target_id=f"dp-{index}",
            )
        )

    fenced_requests: dict[str, tuple[str, ...]] = {}

    def fence(event: Any, _des: GlobalDES) -> None:
        failure_id = str(event.payload["failure_id"])
        snapshot = driver.fence_for_external_gpu_failure(
            failure_id=failure_id,
            target_id="dp-0",
            reason="fixture GPU failure",
        )
        fenced_requests[failure_id] = tuple(item.request_id for item in snapshot.requests)

    def repair(event: Any, _des: GlobalDES) -> None:
        failure_id = str(event.payload["failure_id"])
        route_version = int(event.payload["route_version"])
        driver.replace_repaired_target(_bridge(des, index=0))
        for request_id in fenced_requests[failure_id]:
            driver.resume_external_request(
                request_id=request_id,
                target_id="dp-0",
                route_version=route_version,
            )

    des.register_handler(EventKind.FAILURE_INJECT, fence)
    des.register_handler(EventKind.REPAIR_COMPLETE, repair)
    for failure_id, failure_ns, repair_ns, route_version in (
        ("failure-0", 200, 250, 1),
        ("failure-1", 700, 710, 2),
    ):
        des.schedule_at(
            failure_ns,
            EventKind.FAILURE_INJECT,
            payload={"failure_id": failure_id},
        )
        des.schedule_at(
            repair_ns,
            EventKind.REPAIR_COMPLETE,
            payload={
                "failure_id": failure_id,
                "route_version": route_version,
            },
        )

    result = driver.run()
    step_ids = [str(step["step_id"]) for step in result.steps]

    assert len(step_ids) == len(set(step_ids))
    dp0_sequences = [
        int(step_id.rsplit(":", 1)[1]) for step_id in step_ids if step_id.startswith("aegis-dp0:")
    ]
    assert dp0_sequences == list(range(1, len(dp0_sequences) + 1))
    assert {str(step["target_id"]) for step in result.steps} == {"dp-0", "dp-1"}
    assert [str(failure["failure_id"]) for failure in result.failures] == [
        "failure-0",
        "failure-1",
    ]


def test_failure_after_committed_output_silently_replays_before_new_output() -> None:
    des = GlobalDES()
    bridges = (_bridge(des, index=0), _bridge(des, index=1))
    driver = AegisContinuousBatchDESDriver(des=des, bridges=bridges)
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="replay",
            release_ns=0,
            prompt_tokens=4,
            max_output_tokens=2,
            observed_ideal_duration_ns=500,
            initial_target_id="dp-0",
        )
    )
    # Prefill commits output position 1 at 400 ns.  Failure fences the decode
    # forward one ns later, so the replacement must silently cross position 1.
    driver.inject_gpu_failure(
        ScheduledGPUFailure(
            failure_id="failure-after-output",
            target_id="dp-0",
            timestamp_ns=401,
        )
    )

    result = cast(dict[str, Any], driver.run().to_dict())

    [failure] = result["failures"]
    assert failure["router_committed_outputs_before_requeue"] == {"replay": 1}
    [request] = result["requests"]
    assert request["silent_replay_target"] == 1
    assert request["router_committed_output_tokens"] == 2
    assert request["completion_ns"] == 901
    recovery_steps = [step for step in result["steps"] if step["target_id"] == "dp-1"]
    assert [step["effective_end_ns"] for step in recovery_steps] == [801, 901]


def test_observed_duration_provider_uses_explicit_uncalibrated_evidence() -> None:
    profile = _profile()
    provider = ObservedIdealTraceDurationProvider(
        prediction_profile=profile,
        trace_provenance_sha256=_sha256(b"trace-manifest"),
    )
    provider.register_request(
        ObservedIdealRequestDuration(
            request_id="r0",
            prompt_tokens=4,
            max_output_tokens=2,
            observed_ideal_duration_ns=500,
        )
    )

    assert provider.evidence.evidence_class is StepDurationEvidenceClass.UNCALIBRATED_MODEL
    assert provider.evidence.physically_measured is False
    assert provider.evidence.formal_use_allowed is False


def test_initial_restored_prefix_crosses_explicit_pre_admit_boundary() -> None:
    des = GlobalDES()
    bridge = _bridge(des, index=0)
    admissions: list[tuple[str, str, int, str, int]] = []
    driver = AegisContinuousBatchDESDriver(
        des=des,
        bridges=(bridge,),
        on_before_admit=lambda target_id, spec, route_version, cause, restored: admissions.append(
            (target_id, spec.request_id, route_version, cause, restored)
        ),
    )
    driver.submit(
        ContinuousBatchRequestSpec(
            request_id="restored",
            release_ns=0,
            prompt_tokens=8,
            max_output_tokens=1,
            observed_ideal_duration_ns=100,
            initial_restored_tokens=4,
        )
    )

    result = driver.run()

    assert admissions == [("dp-0", "restored", 0, "INITIAL_RELEASE", 4)]
    assert result.requests[0]["completion_ns"] == 50
