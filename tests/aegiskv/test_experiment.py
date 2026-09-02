from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from moonkvsim.aegiskv import experiment as experiment_module
from moonkvsim.aegiskv.experiment import (
    DEFAULT_PARAMETERS,
    CellSpec,
    ModelParameters,
    Scenario,
    SystemId,
    ablation_variants,
    core_variants,
    derive_failure_schedule,
    derive_failure_schedules,
    failure_workload_progress_targets_per_mille,
    qwen3_8b_dp_deployment,
    qwen3_8b_dp_only_contract,
    run_study_cell,
    sensitivity_variants,
    store_node_sensitivity_variants,
    transport_sensitivity_variants,
)
from moonkvsim.aegiskv.experiment_workload import load_experiment_records
from moonkvsim.common.hash import sha256_json
from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.store.transfer_engine import TransferStatus, TransportKind


def _committed_records() -> list[dict[str, object]]:
    root = Path(__file__).resolve().parents[2]
    path = root / "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-shapes.jsonl"
    return load_experiment_records(path)


def _single_exact_token_record() -> dict[str, object]:
    record = dict(_committed_records()[0])
    token_ids = list(range(int(record["prompt_tokens"])))
    token_ids_sha256 = sha256_json(token_ids)
    record.update(
        {
            "messages_or_token_ids": {
                "kind": "token_ids",
                "sha256": token_ids_sha256,
                "value": token_ids,
            },
            "prompt_token_ids_hash": token_ids_sha256,
            "token_count_mode": "qwen3_token_ids",
            "tokenizer_fingerprint": token_ids_sha256,
        }
    )
    return record


def _mock_causal_failure_events(spec: CellSpec) -> list[dict[str, object]]:
    schedule = spec.failure_schedule
    if schedule is None:
        return []
    return [
        {
            "failure_id": event.failure_id,
            "timestamp_ns": event.reference_at_ns,
            "logical_trigger": {"focus_span_id": event.focus_span_id},
            "impacted_active_span_ids": [event.focus_span_id],
            "impacted_queued_span_ids": [],
        }
        for event in schedule.events
    ]


def test_protocol_enumerates_seven_systems_and_declared_variants() -> None:
    assert [item.variant_id for item in core_variants()] == [item.value for item in SystemId]
    assert len(ablation_variants()) == 12
    assert len(sensitivity_variants()) == 21
    assert {item.suite for item in core_variants()} == {"core"}
    assert {item.suite for item in ablation_variants()} == {"ablation"}
    assert {item.suite for item in sensitivity_variants()} == {"sensitivity"}
    transport = transport_sensitivity_variants()
    assert [item.parameters.store_transport for item in transport] == [
        TransportKind.RDMA_GDR,
        TransportKind.RDMA_HOST_STAGED,
        TransportKind.TCP_HOST_STAGED,
    ]
    assert {item.suite for item in transport} == {"transport_sensitivity"}
    store_nodes = store_node_sensitivity_variants()
    assert [item.parameters.store_node_count for item in store_nodes] == [1, 2, 4]
    assert {item.suite for item in store_nodes} == {"store_node_sensitivity"}


def test_failure_count_two_builds_one_ordered_two_event_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    details = (
        {
            "span_id": "span-helper",
            "workflow_id": "workflow-helper",
            "context_bucket": "32k",
            "gpu_id": "gpu-0",
            "compute_start_ns": 0,
            "completed_ns": 50,
        },
        {
            "span_id": "span-a",
            "workflow_id": "workflow-a",
            "context_bucket": "8k",
            "gpu_id": "gpu-0",
            "compute_start_ns": 100,
            "completed_ns": 150,
        },
        {
            "span_id": "span-b",
            "workflow_id": "workflow-b",
            "context_bucket": "8k",
            "gpu_id": "gpu-1",
            "compute_start_ns": 200,
            "completed_ns": 250,
        },
    )
    calls: list[CellSpec] = []

    def oracle(_records: object, spec: CellSpec) -> SimpleNamespace:
        calls.append(spec)
        return SimpleNamespace(
            span_details=details,
            representative={"failure_events": _mock_causal_failure_events(spec)},
        )

    monkeypatch.setattr(experiment_module, "run_study_cell", oracle)

    schedule = derive_failure_schedules(
        (),
        buckets=("8k",),
        seed=7,
        failure_count=2,
        compared_profiles=(core_variants()[0].profile,),
        enforce_all_events_in_bucket=True,
    )["8k"]

    assert len(calls) == 2
    assert calls[0].scenario is Scenario.NO_FAILURE
    assert calls[0].failure_schedule is None
    assert calls[1].scenario is Scenario.GPU_FAILURE
    assert calls[1].failure_schedule is not None
    assert len(calls[1].failure_schedule.events) == 1
    assert {item.focus_span_id for item in schedule.events} == {"span-a", "span-b"}
    assert [item.event_index for item in schedule.events] == [0, 1]
    assert [item.target_workload_progress_per_mille for item in schedule.events] == [
        333,
        667,
    ]
    assert all(item.trigger_progress_per_mille == 600 for item in schedule.events)


def test_failure_count_eight_uses_f0_through_f7_oracles_per_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    details = tuple(
        {
            "span_id": f"span-{index}",
            "workflow_id": f"workflow-{index}",
            "context_bucket": "8k",
            "gpu_id": f"gpu-{index % 2}",
            "compute_start_ns": index * 1_000,
            "completed_ns": index * 1_000 + 100,
        }
        for index in range(10)
    )
    calls: list[CellSpec] = []

    def oracle(_records: object, spec: CellSpec) -> SimpleNamespace:
        calls.append(spec)
        return SimpleNamespace(
            span_details=details,
            representative={"failure_events": _mock_causal_failure_events(spec)},
        )

    monkeypatch.setattr(experiment_module, "run_study_cell", oracle)

    schedule = derive_failure_schedules(
        (),
        buckets=("8k",),
        seed=7,
        failure_count=8,
        compared_profiles=tuple(variant.profile for variant in core_variants()[:2]),
    )["8k"]

    assert len(calls) == 16
    for profile_index in range(2):
        profile_calls = [
            spec
            for spec in calls
            if spec.variant.variant_id == f"profile-{profile_index}"
        ]
        assert len(profile_calls) == 8
        assert profile_calls[0].scenario is Scenario.NO_FAILURE
        assert profile_calls[0].failure_schedule is None
        assert all(
            spec.scenario is Scenario.GPU_FAILURE for spec in profile_calls[1:]
        )
        assert [
            len(spec.failure_schedule.events)
            for spec in profile_calls[1:]
            if spec.failure_schedule is not None
        ] == list(range(1, 8))
    assert len(schedule.events) == 8
    assert len({event.focus_span_id for event in schedule.events}) == 8
    assert [event.reference_at_ns for event in schedule.events] == sorted(
        event.reference_at_ns for event in schedule.events
    )
    assert schedule.selection_scope == (
        "causal_recursive_logical_failures_runtime_resolved_gpu"
    )


@pytest.mark.parametrize(
    ("failure_call", "event_index", "scenario"),
    ((1, 0, "no_failure"), (2, 1, "gpu_failure")),
)
def test_failure_schedule_oracle_error_binds_event_profile_and_preserves_cause(
    monkeypatch: pytest.MonkeyPatch,
    failure_call: int,
    event_index: int,
    scenario: str,
) -> None:
    details = tuple(
        {
            "span_id": f"span-{index}",
            "workflow_id": f"workflow-{index}",
            "context_bucket": "96k",
            "gpu_id": f"gpu-{index}",
            "compute_start_ns": (index + 1) * 100,
            "completed_ns": (index + 1) * 100 + 50,
        }
        for index in range(3)
    )
    calls: list[CellSpec] = []

    def oracle(_records: object, spec: CellSpec) -> SimpleNamespace:
        calls.append(spec)
        if len(calls) == failure_call:
            raise ValueError("foreground scheduler pages cannot fit physical HBM")
        return SimpleNamespace(
            span_details=details,
            representative={"failure_events": _mock_causal_failure_events(spec)},
        )

    monkeypatch.setattr(experiment_module, "run_study_cell", oracle)
    profile = core_variants()[1].profile
    profile_fingerprint = experiment_module._failure_oracle_profile_fingerprint(
        profile
    )

    with pytest.raises(experiment_module.ExperimentError) as captured:
        derive_failure_schedules(
            (),
            buckets=("96k",),
            seed=2,
            workflow_concurrency=32,
            failure_count=2,
            compared_profiles=(profile,),
            enforce_all_events_in_bucket=True,
        )

    message = str(captured.value)
    assert "bucket=96k" in message
    assert "seed=2" in message
    assert "workflow_concurrency=32" in message
    assert f"event_index={event_index}" in message
    assert "profile_index=0" in message
    assert "system_id=vanilla_mooncake_dram" in message
    assert "eviction=lru" in message
    assert f"profile_fingerprint={profile_fingerprint}" in message
    assert f"scenario={scenario}" in message
    assert isinstance(captured.value.__cause__, ValueError)
    assert "foreground scheduler pages" in str(captured.value.__cause__)


def test_failure_schedule_projection_is_pure_logical_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parameters = replace(
        DEFAULT_PARAMETERS,
        failure_detection_ns=0,
        failure_progress_per_mille=600,
        gpu_recovery_time_ns=100,
    )
    reference = experiment_module.FailureSchedule(
        (
            experiment_module.FailureEventSchedule(
                failure_id="failure-0",
                event_index=0,
                bucket="8k",
                seed=7,
                focus_span_id="span-a",
                target_gpu_id="gpu-0",
                reference_at_ns=160,
                target_workload_progress_per_mille=500,
                reference_completed_workflow_count=0,
                reference_workflow_count=1,
                detection_delay_ns=0,
                trigger_progress_per_mille=600,
                gpu_recovery_time_ns=100,
                selection_scope="reference",
            ),
        ),
        selection_scope="reference",
    )
    monkeypatch.setattr(
        experiment_module,
        "run_study_cell",
        lambda *_args, **_kwargs: pytest.fail("projection must not run an oracle"),
    )

    projected = experiment_module.project_failure_schedule_to_profile(
        (),
        reference=reference,
        profile=core_variants()[1].profile,
        parameters=parameters,
        seed=7,
    )

    assert len(projected.events) == 1
    assert projected.events[0].focus_span_id == "span-a"
    assert projected.events[0].target_gpu_id == "gpu-0"
    assert projected.events[0].reference_at_ns == 160
    assert projected.selection_scope == (
        "shared_logical_focus_runtime_resolved_physical_gpu"
    )


def test_failure_projection_rejects_parameter_drift_without_running_oracle() -> None:
    parameters = DEFAULT_PARAMETERS
    reference = experiment_module.FailureSchedule(
        (
            experiment_module.FailureEventSchedule(
                failure_id="failure-0",
                event_index=0,
                bucket="8k",
                seed=7,
                focus_span_id="span-a",
                target_gpu_id="gpu-0",
                reference_at_ns=160,
                target_workload_progress_per_mille=500,
                reference_completed_workflow_count=0,
                reference_workflow_count=1,
                detection_delay_ns=parameters.failure_detection_ns + 1,
                trigger_progress_per_mille=parameters.failure_progress_per_mille,
                gpu_recovery_time_ns=parameters.gpu_recovery_time_ns,
            ),
        )
    )

    with pytest.raises(ValueError, match="parameters diverged"):
        experiment_module.project_failure_schedule_to_profile(
            (),
            reference=reference,
            profile=core_variants()[0].profile,
            parameters=parameters,
            seed=7,
        )


def test_logical_failure_resolves_route_at_compute_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _single_exact_token_record()
    variant = core_variants()[-1]
    parameters = variant.parameters
    event = experiment_module.FailureEventSchedule(
        failure_id="failure-runtime-route",
        event_index=0,
        bucket="8k",
        seed=0,
        focus_span_id=str(record["span_id"]),
        target_gpu_id="gpu-0",
        reference_at_ns=100,
        target_workload_progress_per_mille=500,
        reference_completed_workflow_count=0,
        reference_workflow_count=1,
        detection_delay_ns=parameters.failure_detection_ns,
        trigger_progress_per_mille=parameters.failure_progress_per_mille,
        gpu_recovery_time_ns=parameters.gpu_recovery_time_ns,
    )
    runtime = experiment_module._StudyRuntime(
        records=[record],
        variant=variant,
        context_bucket="8k",
        seed=0,
        failure_schedule=experiment_module.FailureSchedule((event,)),
        workflow_concurrency=1,
    )
    execution = runtime.executions[event.focus_span_id]
    execution.gpu_id = "gpu-3"
    execution.status = experiment_module._ExecutionStatus.RUNNING
    captured: dict[str, object] = {}

    def capture(
        timestamp_ns: int,
        kind: EventKind,
        *,
        event_id: str,
        payload: dict[str, object],
    ) -> EventHandle:
        captured.update(
            timestamp_ns=timestamp_ns,
            kind=kind,
            event_id=event_id,
            payload=payload,
        )
        return EventHandle(event_id)

    monkeypatch.setattr(runtime.des, "schedule_at", capture)

    runtime._schedule_logical_failure_trigger(
        execution,
        gpu_id="gpu-3",
        compute_start_ns=100,
        compute_end_ns=1_100,
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["reference_target_gpu_id"] == "gpu-0"
    assert payload["target_gpu_id"] == "gpu-3"
    assert payload["resolved_target_gpu_id"] == "gpu-3"
    assert payload["focus_span_id"] == event.focus_span_id


def test_continuous_failure_uses_exact_scheduler_token_crossing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _single_exact_token_record()
    variant = core_variants()[-1]
    parameters = variant.parameters
    event = experiment_module.FailureEventSchedule(
        failure_id="continuous-token-crossing",
        event_index=0,
        bucket="8k",
        seed=0,
        focus_span_id=str(record["span_id"]),
        target_gpu_id="gpu-0",
        reference_at_ns=100,
        target_workload_progress_per_mille=500,
        reference_completed_workflow_count=0,
        reference_workflow_count=1,
        detection_delay_ns=parameters.failure_detection_ns,
        trigger_progress_per_mille=parameters.failure_progress_per_mille,
        gpu_recovery_time_ns=parameters.gpu_recovery_time_ns,
    )
    runtime = experiment_module._StudyRuntime(
        records=[record],
        variant=variant,
        context_bucket="8k",
        seed=0,
        failure_schedule=experiment_module.FailureSchedule((event,)),
        workflow_concurrency=1,
    )
    execution = runtime.executions[event.focus_span_id]
    execution.gpu_id = "gpu-3"
    execution.status = experiment_module._ExecutionStatus.RUNNING
    total_tokens = execution.metadata.prompt_tokens + execution.metadata.output_tokens
    threshold_numerator = total_tokens * event.trigger_progress_per_mille
    threshold_floor = threshold_numerator // 1_000
    before = threshold_floor - 10
    after = threshold_floor + 10
    step = experiment_module._ContinuousFailureStep(
        span_id=execution.metadata.span_id,
        route_version=execution.route_version,
        gpu_id="gpu-3",
        scheduler_step_id="step-token-crossing",
        start_ns=100,
        end_ns=1_100,
        num_computed_tokens_before=before,
        num_computed_tokens_after=after,
    )
    runtime.des.now_ns = step.start_ns
    captured: dict[str, object] = {}

    def capture(
        timestamp_ns: int,
        kind: EventKind,
        *,
        event_id: str,
        payload: dict[str, object],
    ) -> EventHandle:
        captured.update(
            timestamp_ns=timestamp_ns,
            kind=kind,
            event_id=event_id,
            payload=payload,
        )
        return EventHandle(event_id)

    monkeypatch.setattr(runtime.des, "schedule_at", capture)

    runtime._schedule_continuous_logical_failure_trigger(
        execution,
        step=step,
    )

    interpolation_numerator = threshold_numerator - before * 1_000
    interpolation_denominator = (after - before) * 1_000
    expected_offset = (
        (step.end_ns - step.start_ns)
        * interpolation_numerator
        // interpolation_denominator
    )
    assert captured["timestamp_ns"] == step.start_ns + expected_offset
    payload = captured["payload"]
    assert isinstance(payload, dict)
    evidence = payload["continuous_progress_evidence"]
    assert isinstance(evidence, dict)
    assert evidence["kind"] == "CONTINUOUS_SCHEDULER_TOKEN_PROGRESS"
    assert evidence["scheduler_step_id"] == step.scheduler_step_id
    assert evidence["num_computed_tokens_before"] == before
    assert evidence["num_computed_tokens_after"] == after
    assert evidence["threshold_numerator"] == threshold_numerator
    assert evidence["threshold_denominator"] == 1_000
    assert evidence["interpolation_numerator"] == interpolation_numerator
    assert evidence["interpolation_denominator"] == interpolation_denominator
    assert evidence["resolution_mode"] == "FIRST_TOKEN_THRESHOLD_CROSSING"


def test_continuous_ordered_failure_defers_to_still_active_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _single_exact_token_record()
    variant = core_variants()[-1]
    parameters = variant.parameters
    base_event = experiment_module.FailureEventSchedule(
        failure_id="continuous-ordered-future",
        event_index=0,
        bucket="8k",
        seed=0,
        focus_span_id=str(record["span_id"]),
        target_gpu_id="gpu-0",
        reference_at_ns=100,
        target_workload_progress_per_mille=500,
        reference_completed_workflow_count=0,
        reference_workflow_count=1,
        detection_delay_ns=parameters.failure_detection_ns,
        trigger_progress_per_mille=parameters.failure_progress_per_mille,
        gpu_recovery_time_ns=parameters.gpu_recovery_time_ns,
    )
    runtime = experiment_module._StudyRuntime(
        records=[record],
        variant=variant,
        context_bucket="8k",
        seed=0,
        failure_schedule=experiment_module.FailureSchedule((base_event,)),
        workflow_concurrency=1,
    )
    prior = replace(
        base_event,
        failure_id="continuous-ordered-prior",
        event_index=0,
        focus_span_id="prior-focus",
        target_workload_progress_per_mille=250,
    )
    future = replace(base_event, event_index=1)
    runtime.failure_schedule = experiment_module.FailureSchedule((prior, future))
    runtime._failure_schedule_by_id = {future.failure_id: future}
    runtime._failure_schedule_by_focus_span = {future.focus_span_id: future}
    execution = runtime.executions[future.focus_span_id]
    execution.gpu_id = "gpu-3"
    execution.status = experiment_module._ExecutionStatus.RUNNING
    total_tokens = execution.metadata.prompt_tokens + execution.metadata.output_tokens
    threshold_floor = (
        total_tokens * future.trigger_progress_per_mille // 1_000
    )
    step = experiment_module._ContinuousFailureStep(
        span_id=execution.metadata.span_id,
        route_version=execution.route_version,
        gpu_id="gpu-3",
        scheduler_step_id="step-ordered-crossing",
        start_ns=100,
        end_ns=1_100,
        num_computed_tokens_before=threshold_floor - 10,
        num_computed_tokens_after=threshold_floor + 10,
    )
    runtime._continuous_failure_active_steps[execution.metadata.span_id] = step
    runtime.des.now_ns = step.start_ns
    captured: dict[str, object] = {}

    def capture(
        timestamp_ns: int,
        kind: EventKind,
        *,
        event_id: str,
        payload: dict[str, object],
    ) -> EventHandle:
        captured.update(
            timestamp_ns=timestamp_ns,
            kind=kind,
            event_id=event_id,
            payload=payload,
        )
        return EventHandle(event_id)

    monkeypatch.setattr(runtime.des, "schedule_at", capture)

    runtime._schedule_continuous_logical_failure_trigger(execution, step=step)

    assert not captured
    assert future.failure_id in runtime._continuous_failure_crossing_evidence
    runtime._failure_event_executed.add(prior.failure_id)
    runtime.des.now_ns = 800
    runtime._schedule_ready_future_failure_triggers()

    assert captured["timestamp_ns"] == 800
    payload = captured["payload"]
    assert isinstance(payload, dict)
    evidence = payload["continuous_progress_evidence"]
    assert isinstance(evidence, dict)
    assert evidence["resolution_mode"] == "ORDERED_DEFERRED_ACTIVE_STEP"
    first_crossing = evidence["first_crossing_evidence"]
    assert isinstance(first_crossing, dict)
    assert first_crossing["scheduler_step_id"] == step.scheduler_step_id
    assert evidence["resolved_at_ns"] <= step.end_ns


def test_failure_cell_rejects_schedule_identity_or_parameter_mismatch() -> None:
    variant = core_variants()[-1]
    parameters = variant.parameters
    event = experiment_module.FailureEventSchedule(
        failure_id="failure-0",
        event_index=0,
        bucket="8k",
        seed=7,
        focus_span_id="span-a",
        target_gpu_id="gpu-0",
        reference_at_ns=100,
        target_workload_progress_per_mille=500,
        reference_completed_workflow_count=0,
        reference_workflow_count=1,
        detection_delay_ns=parameters.failure_detection_ns,
        trigger_progress_per_mille=parameters.failure_progress_per_mille,
        gpu_recovery_time_ns=parameters.gpu_recovery_time_ns,
    )

    def build(candidate: experiment_module.FailureEventSchedule, **overrides: object) -> None:
        CellSpec(
            variant=variant,
            context_bucket=str(overrides.get("context_bucket", "8k")),
            scenario=Scenario.GPU_FAILURE,
            seed=int(overrides.get("seed", 7)),
            repetition="A",
            failure_schedule=experiment_module.FailureSchedule((candidate,)),
        )

    build(event)
    with pytest.raises(ValueError, match="seed must match"):
        build(event, seed=8)
    with pytest.raises(ValueError, match="bucket must match"):
        build(event, context_bucket="32k")
    with pytest.raises(ValueError, match="detection delay"):
        build(replace(event, detection_delay_ns=parameters.failure_detection_ns + 1))
    with pytest.raises(ValueError, match="trigger progress"):
        build(
            replace(
                event,
                trigger_progress_per_mille=parameters.failure_progress_per_mille + 1,
            )
        )
    with pytest.raises(ValueError, match="recovery time"):
        build(replace(event, gpu_recovery_time_ns=parameters.gpu_recovery_time_ns + 1))


def test_paper_failure_counts_are_evenly_spaced_in_one_workload() -> None:
    assert failure_workload_progress_targets_per_mille(1) == (500,)
    assert failure_workload_progress_targets_per_mille(2) == (333, 667)
    assert failure_workload_progress_targets_per_mille(4) == (200, 400, 600, 800)
    assert failure_workload_progress_targets_per_mille(8) == (
        111,
        222,
        333,
        444,
        556,
        667,
        778,
        889,
    )


def test_positive_fraction_rounds_a_single_unit_up() -> None:
    assert experiment_module._fraction_count(1, Fraction(3, 4)) == 1
    assert experiment_module._fraction_count(1, Fraction(9, 10)) == 1
    assert experiment_module._fraction_count(0, Fraction(9, 10)) == 0
    assert experiment_module._fraction_count(8, Fraction(3, 4)) == 6


def test_policy_chunks_do_not_mix_global_and_workflow_scopes() -> None:
    record = {
        "workflow_id": "workflow-a",
        "source_hash_ids": list(range(20)),
        "source_hash_block_token_counts": [64] * 20,
        "source_hash_block_scopes": [
            "global_system_template",
            *(["within_workflow"] * 19),
        ],
    }

    chunks = experiment_module._chunks_for_record(record, ModelParameters())
    peer_record = dict(record, workflow_id="workflow-b")
    peer_chunks = experiment_module._chunks_for_record(peer_record, ModelParameters())

    assert [chunk.token_count for chunk in chunks] == [64, 1_024, 192]
    assert [chunk.token_start for chunk in chunks] == [0, 64, 1_088]
    assert chunks[0].key == peer_chunks[0].key
    assert chunks[0].global_system_template is True
    assert all(chunk.global_system_template is False for chunk in chunks[1:])
    assert chunks[1].key != peer_chunks[1].key
    assert chunks[2].key != peer_chunks[2].key

    assert experiment_module._fraction_prefix_chunk_count(
        chunks, Fraction(3, 4)
    ) == 2
    assert experiment_module._fraction_prefix_chunk_count(
        chunks, Fraction(9, 10)
    ) == 3


def test_partial_source_block_is_charged_as_one_complete_physical_allocation() -> None:
    record = {
        "workflow_id": "workflow-tail",
        "source_hash_ids": [1, 2],
        "source_hash_block_token_counts": [64, 16],
        "source_hash_block_scopes": ["within_workflow", "within_workflow"],
    }

    [chunk] = experiment_module._chunks_for_record(record, ModelParameters())

    assert chunk.token_count == 80
    assert chunk.bytes == 2 * experiment_module.KV_BYTES_PER_SOURCE_BLOCK


def test_page_aligned_tail_adopts_complete_source_allocations_without_pin_leak() -> None:
    block_bytes = 64
    chunks = (
        experiment_module._Chunk(
            key="full",
            workflow_id="workflow-tail",
            token_start=0,
            token_count=1_024,
            bytes=16 * block_bytes,
        ),
        experiment_module._Chunk(
            key="tail",
            workflow_id="workflow-tail",
            token_start=1_024,
            token_count=85,
            bytes=2 * block_bytes,
        ),
    )
    pool = experiment_module._ModeledPool(
        pool_id="tail",
        capacity_bytes=18 * block_bytes,
        eviction=experiment_module.EvictionKind.LRU,
        seed=0,
    )
    for chunk in chunks:
        assert pool.insert(chunk, score=Fraction(1), now_ns=0, cause="TEST")
    adopted_tokens = experiment_module._source_chunk_page_aligned_prefix(
        chunks,
        1_109,
        logical_page_tokens=16,
    )

    assert adopted_tokens == 1_104
    assert experiment_module._source_chunk_page_aligned_prefix(
        chunks,
        adopted_tokens,
        logical_page_tokens=16,
    ) == adopted_tokens
    pool.pin_interval(
        chunks,
        start_token=0,
        token_count=adopted_tokens,
        pin_id="request-tail",
    )
    assert pool.activate_prefix(
        chunks,
        token_count=adopted_tokens,
        now_ns=1,
        cause="TEST_ACTIVATE",
        pin_id="request-tail",
    ) == 18 * block_bytes
    assert pool.pinned_entry_count == 0


def test_protection_batches_preserve_independent_policy_chunk_admission() -> None:
    assert experiment_module._protection_batch_ranges(100, 75) == tuple(
        (index, index + 1) for index in range(75)
    )
    assert experiment_module._protection_batch_ranges(100, 90) == tuple(
        (index, index + 1) for index in range(90)
    )
    assert experiment_module._protection_batch_ranges(1, 1) == ((0, 1),)
    assert experiment_module._protection_batch_ranges(
        100,
        75,
        global_prefix_chunk_count=1,
    ) == tuple((index, index + 1) for index in range(75))
    assert experiment_module._protection_transfer_batch_ranges(18) == (
        (0, 8),
        (8, 16),
        (16, 18),
    )
    assert experiment_module._protection_transfer_batch_ranges(
        18,
        global_prefix_candidate_count=1,
    ) == ((0, 1), (1, 9), (9, 17), (17, 18))


def test_formal_policy_previews_stay_independent_while_transfers_batch() -> None:
    records = _committed_records()[:2]
    result = run_study_cell(
        records,
        CellSpec(
            variant=core_variants()[-1],
            context_bucket="64k",
            scenario=Scenario.NO_FAILURE,
            seed=3,
            repetition="A",
        ),
    )
    previews = [
        item
        for item in result.representative["formal_algorithm2_events"]
        if item["event"] == "FORMAL_ALGORITHM2_PREVIEW"
    ]
    protection_transfers = [
        item
        for item in result.representative["transfers"]
        if item["cause"]
        in {"AEGIS_PEER_HBM_PROTECTION", "AEGIS_STORE_DRAM_PROTECTION"}
    ]
    admitted_previews = [
        item for item in previews if item["preview"]["outcome"] == "ADMIT"
    ]

    assert previews
    assert all(
        0 < item["candidate_token_count"] <= item["engine_policy_chunk_tokens"]
        for item in previews
    )
    assert sum(
        item["policy_candidate_count"] for item in protection_transfers
    ) == len(admitted_previews)
    assert any(
        item["policy_candidate_count"] == experiment_module.FLOW_SLICE_POLICY_CHUNKS
        for item in protection_transfers
    )
    assert len(protection_transfers) < len(admitted_previews)


def test_pool_reinserted_key_invalidates_old_heap_identity() -> None:
    chunk = experiment_module._Chunk(
        key="shared-prefix",
        workflow_id="workflow-a",
        token_start=0,
        token_count=64,
        bytes=64,
    )
    pool = experiment_module._ModeledPool(
        pool_id="test",
        capacity_bytes=64,
        eviction=experiment_module.EvictionKind.LRU,
        seed=0,
    )
    assert pool.insert(chunk, score=Fraction(1), now_ns=0, cause="TEST")
    assert pool.activate_prefix(
        (chunk,),
        token_count=64,
        now_ns=1,
        cause="TEST_ACTIVATE",
    ) == 64
    assert pool.insert(chunk, score=Fraction(2), now_ns=2, cause="TEST_REINSERT")

    assert pool.evict_at_least(64, now_ns=3, cause="TEST_EVICT") == 64
    assert pool.occupied_bytes == 0
    assert not pool.entries


def test_inactive_hbm_source_pin_is_visible_to_shared_readers_and_survives_reclaim() -> None:
    chunks = tuple(
        experiment_module._Chunk(
            key=f"prefix-{index}",
            workflow_id="workflow-a",
            token_start=index * 64,
            token_count=64,
            bytes=64,
        )
        for index in range(2)
    )
    pool = experiment_module._ModeledPool(
        pool_id="normal-hbm",
        capacity_bytes=128,
        eviction=experiment_module.EvictionKind.LRU,
        seed=0,
    )
    for chunk in chunks:
        assert pool.insert(chunk, score=Fraction(1), now_ns=0, cause="TEST")
    pool.pin_interval(
        chunks,
        start_token=0,
        token_count=64,
        pin_id="request-a",
    )
    pool.pin_interval(
        chunks,
        start_token=0,
        token_count=64,
        pin_id="request-b",
    )

    assert pool.peek_prefix_tokens(chunks) == 128
    assert pool.pinned_entry_count == 1
    assert pool.pinned_reference_count == 2
    assert pool.evictable_bytes == 64
    assert pool.evict_at_least(64, now_ns=1, cause="TEST_RECLAIM") == 64
    assert set(pool.entries) == {"prefix-0"}
    with pytest.raises(
        experiment_module.ExperimentError,
        match="source pin diverged",
    ):
        pool.activate_prefix(
            chunks,
            token_count=64,
            now_ns=2,
            cause="WRONG_OWNER",
            pin_id="request-b",
        )

    assert pool.release_pin("request-b") == 64
    assert pool.activate_prefix(
        chunks,
        token_count=64,
        now_ns=2,
        cause="OWNED_ACTIVATION",
        pin_id="request-a",
    ) == 64
    assert pool.occupied_bytes == 0


def test_pool_distinguishes_alias_noop_from_admission_rejection() -> None:
    chunk = experiment_module._Chunk(
        key="shared-prefix",
        workflow_id="workflow-a",
        token_start=0,
        token_count=64,
        bytes=64,
    )
    pool = experiment_module._ModeledPool(
        pool_id="test",
        capacity_bytes=64,
        eviction=experiment_module.EvictionKind.LRU,
        seed=0,
    )
    assert pool.insert(chunk, score=Fraction(1), now_ns=0, cause="TEST")

    assert (
        pool.reserve(
            "alias",
            (chunk,),
            (Fraction(2),),
            now_ns=1,
            cause="TEST_ALIAS",
        )
        is None
    )
    assert pool.last_reserve_outcome == "ALIAS_ONLY"


def test_pool_rebases_each_batch_candidate_on_current_rent() -> None:
    def chunk(key: str) -> experiment_module._Chunk:
        return experiment_module._Chunk(
            key=key,
            workflow_id="workflow-a",
            token_start=0,
            token_count=1,
            bytes=1,
        )

    pool = experiment_module._ModeledPool(
        pool_id="test",
        capacity_bytes=2,
        eviction=experiment_module.EvictionKind.SLACK_LANDLORD_VALUE,
        seed=0,
    )
    assert pool.insert(chunk("victim-a"), score=Fraction(5), now_ns=0, cause="TEST")
    assert pool.insert(
        chunk("victim-b"), score=Fraction(11, 2), now_ns=0, cause="TEST"
    )

    reservation = pool.reserve(
        "batch",
        (chunk("candidate-a"), chunk("candidate-b")),
        (Fraction(10), Fraction(1)),
        now_ns=1,
        cause="TEST_BATCH",
    )

    assert reservation is not None
    assert len(reservation.chunks) == 2
    assert reservation.scores == (Fraction(10), Fraction(6))
    assert pool.rent == Fraction(11, 2)


def test_remaining_ideal_slack_decays_from_published_residual_observation() -> None:
    runtime = object.__new__(experiment_module._StudyRuntime)
    runtime.algorithm1_cpm = SimpleNamespace(
        timing=lambda _span_id: SimpleNamespace(slack_ns=10_000)
    )
    runtime._published_slack = {
        "span-a": experiment_module.SlackSignal(
            slack_at_observation_ns=Fraction(100),
            observed_at_ns=2_000,
            version=3,
        )
    }
    execution = experiment_module._SpanExecution(
        metadata=SimpleNamespace(span_id="span-a"),
        record={},
        chunks=(),
        released_ns=1_000,
    )

    assert runtime._remaining_ideal_slack_ns(execution, at_ns=2_040) == 60
    assert runtime._remaining_ideal_slack_ns(execution, at_ns=2_100) == 0
    assert runtime._remaining_ideal_slack_ns(execution, at_ns=2_500) == 0


def test_remaining_ideal_slack_falls_back_to_initial_cpm_without_publication() -> None:
    runtime = object.__new__(experiment_module._StudyRuntime)
    runtime.algorithm1_cpm = SimpleNamespace(
        timing=lambda _span_id: SimpleNamespace(slack_ns=100)
    )
    runtime._published_slack = {}
    execution = experiment_module._SpanExecution(
        metadata=SimpleNamespace(span_id="span-a"),
        record={},
        chunks=(),
        released_ns=1_000,
    )

    assert runtime._remaining_ideal_slack_ns(execution, at_ns=1_040) == 60
    assert runtime._remaining_ideal_slack_ns(execution, at_ns=1_100) == 0


def test_update_residual_slack_republishes_when_sibling_completes() -> None:
    base = dict(_committed_records()[0])
    long_id = f"{base['span_id']}:long"
    short_id = f"{base['span_id']}:short"
    workflow_id = str(base["workflow_id"])
    long_record = dict(base)
    short_record = dict(base)
    long_record["span_id"] = long_id
    short_record["span_id"] = short_id
    short_hashes = list(short_record["source_hash_ids"])
    short_record["source_hash_ids"] = [int(item) + 1_000_003 for item in short_hashes]
    runtime = experiment_module._StudyRuntime(
        records=[long_record, short_record],
        variant=core_variants()[-1],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    long_ex = runtime.executions[long_id]
    short_ex = runtime.executions[short_id]
    long_ex.released_ns = 0
    long_ex.compute_start_ns = 0
    long_ex.planned_complete_ns = 20_000
    short_ex.released_ns = 0
    short_ex.compute_start_ns = 0
    short_ex.planned_complete_ns = 5_000
    runtime.des.now_ns = 0
    runtime._update_residual_slack(
        workflow_id,
        reason="REQUEST_RELEASE",
        trigger_span_id=long_id,
    )
    assert int(runtime._published_slack[long_id].slack_at_observation_ns) == 0
    assert int(runtime._published_slack[short_id].slack_at_observation_ns) == 15_000

    short_ex.completed_ns = 5_000
    runtime.des.now_ns = 5_000
    runtime._update_residual_slack(
        workflow_id,
        reason="REQUEST_COMPLETE",
        trigger_span_id=short_id,
    )
    assert int(runtime._published_slack[long_id].slack_at_observation_ns) == 0
    assert runtime._published_slack[long_id].observed_at_ns == 5_000
    assert runtime._published_slack[long_id].version == 2
    assert runtime._published_slack[short_id].version == 1


def test_formal_recovery_snapshot_uses_published_residual_slack() -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records()[:1],
        variant=core_variants()[-1],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    execution = next(iter(runtime.executions.values()))
    span_id = execution.metadata.span_id
    execution.released_ns = 0
    initial_slack = runtime.algorithm1_cpm.timing(span_id).slack_ns
    runtime._published_slack[span_id] = experiment_module.SlackSignal(
        slack_at_observation_ns=Fraction(0, 1),
        observed_at_ns=0,
        version=4,
    )
    snapshot = runtime._formal_recovery_snapshot(
        span_id=span_id,
        path="STORE_DRAM",
        pool=experiment_module.PolicyPool.STORE_DRAM,
    )
    assert snapshot.slack.slack_at_observation_ns == 0
    assert snapshot.slack.observed_at_ns == 0
    assert snapshot.slack.version == 4
    if initial_slack > 0:
        assert snapshot.slack.slack_at_observation_ns != Fraction(initial_slack, 1)


def test_formal_joint_loss_excludes_completed_victim_requests() -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records()[:1],
        variant=core_variants()[-1],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    execution = next(iter(runtime.executions.values()))
    span_id = execution.metadata.span_id
    execution.released_ns = 0
    execution.completed_ns = 1
    runtime.des.now_ns = 2

    metadata = experiment_module._FormalChunkMetadata(
        chunk_id="completed-victim-chunk",
        span_id=span_id,
        path="PEER_HBM",
        pool_id="PEER_HBM:gpu-0",
        physical_chunk=runtime._protection_chunks(
            execution,
            path="PEER_HBM",
        )[0],
        global_sequence_index=0,
        pool_sequence_index=0,
    )
    runtime._formal_chunk_metadata[metadata.chunk_id] = metadata
    value, _gain = runtime._formal_candidate_value(
        metadata,
        landlord=runtime.formal_landlords[metadata.pool_id],
        resident=False,
    )
    loss = runtime._formal_joint_loss(
        (experiment_module.RentalEntry(value),),
        path="PEER_HBM",
        pool=experiment_module.PolicyPool.PEER_HBM,
    )

    assert len(loss.before_by_request) == 1
    assert len(loss.after_by_request) == 1
    assert loss.before_by_request[0].request_id == span_id
    assert loss.after_by_request[0].request_id == span_id
    assert loss.before_by_request[0].harm_ns == 0
    assert loss.after_by_request[0].harm_ns == 0
    assert loss.joint_loss_ns == 0


def test_recovery_source_intervals_are_disjoint_and_conservative() -> None:
    assert experiment_module._recovery_source_intervals(
        10_000,
        normal_prefix_tokens=2_000,
        peer_prefix_tokens=6_000,
        store_prefix_tokens=8_000,
    ) == (2_000, 4_000, 2_000, 2_000)
    assert experiment_module._recovery_source_intervals(
        10_000,
        normal_prefix_tokens=7_000,
        peer_prefix_tokens=5_000,
        store_prefix_tokens=6_000,
    ) == (7_000, 0, 0, 3_000)


def test_formal_store_lookup_uses_committed_protection_content_keys() -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records(),
        variant=core_variants()[-1],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    execution = sorted(
        (item for item in runtime.executions.values() if len(item.chunks) > 2),
        key=lambda item: item.metadata.prompt_tokens,
    )[0]
    protection_chunks = runtime._protection_chunks(
        execution,
        path="STORE_DRAM",
    )
    committed = protection_chunks[:2]
    assert committed[1].global_system_template is False
    for chunk in committed:
        pool = runtime.store_pools[runtime._store_segment_for_chunk(chunk)]
        assert pool.insert(
            chunk,
            score=Fraction(1),
            now_ns=0,
            cause="TEST_FORMAL_STORE_PRIVATE_PREFIX",
        )

    assert runtime._store_lookup_prefix_tokens(
        execution.chunks,
        now_ns=0,
        mutate_signals=False,
    ) == 0
    expected_tokens = sum(chunk.token_count for chunk in committed)
    assert runtime._store_lookup_prefix_tokens(
        protection_chunks,
        now_ns=0,
        mutate_signals=False,
    ) == expected_tokens

    runtime._route_gpu(
        execution.metadata.span_id,
        route_version=0,
        required_hbm_bytes=0,
    )
    route = runtime.route_events[-1]
    assert route["selected_cache_source"] == "STORE_DRAM"
    assert route["selected_effective_prefix_tokens"] == expected_tokens


def test_exact_token_continuous_failure_recovery_preserves_hbm_and_silent_replay() -> None:
    record = _single_exact_token_record()
    variant = replace(
        core_variants()[-1],
        parameters=replace(
            core_variants()[-1].parameters,
            failure_detection_ns=1_000_000,
            failure_progress_per_mille=990,
            gpu_recovery_time_ns=100_000_000,
        ),
    )
    no_failure = run_study_cell(
        [record],
        CellSpec(
            variant=variant,
            context_bucket="8k",
            scenario=Scenario.NO_FAILURE,
            seed=0,
            repetition="A",
            workflow_concurrency=1,
        ),
    )
    reference = no_failure.span_details[0]
    reference_gpu = str(reference["gpu_id"])
    provenance_gpu = "gpu-0" if reference_gpu != "gpu-0" else "gpu-1"
    schedule = experiment_module.FailureSchedule(
        (
            experiment_module.FailureEventSchedule(
                failure_id="continuous-e2e-failure-0",
                event_index=0,
                bucket="8k",
                seed=0,
                focus_span_id=str(record["span_id"]),
                target_gpu_id=provenance_gpu,
                reference_at_ns=int(reference["completed_ns"]) * 990 // 1_000,
                target_workload_progress_per_mille=500,
                reference_completed_workflow_count=0,
                reference_workflow_count=1,
                detection_delay_ns=1_000_000,
                trigger_progress_per_mille=990,
                gpu_recovery_time_ns=100_000_000,
                selection_scope="exact_token_continuous_e2e_test",
            ),
        ),
        selection_scope="exact_token_continuous_e2e_test",
    )
    result = run_study_cell(
        [record],
        CellSpec(
            variant=variant,
            context_bucket="8k",
            scenario=Scenario.GPU_FAILURE,
            seed=0,
            repetition="A",
            failure_schedule=schedule,
            workflow_concurrency=1,
        ),
    )

    detail = result.span_details[0]
    assert detail["route_version"] == 1
    assert detail["restored_peer_tokens"] == record["prompt_tokens"]
    assert detail["recompute_tokens"] == 0
    assert detail["external_output_emissions"] == record["output_tokens"]
    ordered = tuple(
        int(detail[name])
        for name in (
            "failure_at_ns",
            "prompt_recompute_start_ns",
            "prompt_recompute_complete_ns",
            "silent_replay_start_ns",
            "silent_replay_complete_ns",
            "recovery_ready_ns",
            "resume_decode_start_ns",
        )
    )
    assert ordered == tuple(sorted(ordered))
    replay = [
        event
        for event in result.representative["recovery_events"]
        if event["event"] == "SILENT_REPLAY_COMPLETE"
    ]
    assert len(replay) == 1
    assert replay[0]["replayed_output_tokens"] > 0
    assert replay[0]["externally_emitted_tokens"] == 0

    failed_gpu = str(reference["gpu_id"])
    causes = [
        point["cause"]
        for point in result.representative["gpu_hbm_timelines"][failed_gpu]
    ]
    assert causes.count("GPU_FAILURE_ALL_HBM_UNAVAILABLE") == 1
    assert causes.count("GPU_REPAIR_HBM_EMPTY_REUSABLE") == 1
    hbm = result.payload["metrics"]["resource_cost"][
        "gpu_hbm_account_stack_by_gpu"
    ]
    assert all(item["valid"] for item in hbm.values())
    policy = result.payload["metrics"]["policy_effects"]
    assert policy["compute_scheduler_model"] == (
        "VLLM_CONTINUOUS_BATCH_SCHEDULER_STEP"
    )
    assert policy["continuous_batch_residency_modeled"] is True
    assert policy["continuous_batch_duration_evidence"] == (
        "OBSERVED_IDEAL_TRACE_TOKEN_SHARE_UNCALIBRATED_MODEL"
    )
    scheduler_evidence = result.representative["continuous_batch_scheduler"]
    assert scheduler_evidence is not None
    assert scheduler_evidence["steps"]
    assert scheduler_evidence["failures"]
    [failure] = result.representative["failure_events"]
    assert failure["reference_target_gpu_id"] == provenance_gpu
    assert failure["target_gpu_id"] == reference_gpu
    assert failure["logical_trigger"]["resolved_target_gpu_id"] == reference_gpu
    trigger_evidence = failure["logical_trigger"]["continuous_progress_evidence"]
    assert trigger_evidence["kind"] == "CONTINUOUS_SCHEDULER_TOKEN_PROGRESS"
    assert trigger_evidence["num_computed_tokens_before"] * 1_000 < (
        trigger_evidence["threshold_numerator"]
    )
    assert trigger_evidence["threshold_numerator"] <= (
        trigger_evidence["num_computed_tokens_after"] * 1_000
    )
    assert trigger_evidence["step_start_ns"] <= failure["timestamp_ns"]
    assert failure["timestamp_ns"] <= trigger_evidence["step_end_ns"]


def test_continuous_sync_preserves_external_recovery_reserve_owner() -> None:
    runtime = experiment_module._StudyRuntime(
        records=[_single_exact_token_record()],
        variant=core_variants()[-1],
        context_bucket="8k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=1,
    )
    execution = next(iter(runtime.executions.values()))
    target_gpu = "gpu-2"
    reserved_bytes = experiment_module.KV_BYTES_PER_SOURCE_BLOCK
    runtime._commit_hbm_moves(
        target_gpu,
        [
            (
                experiment_module.FREE_ACCOUNT,
                experiment_module.HBM_RECOVERY_RESERVED_ACCOUNT,
                reserved_bytes,
            )
        ],
        cause="TEST_EXTERNAL_RECOVERY_RESERVE",
    )
    runtime.continuous_hbm_authorities[
        target_gpu
    ].observe_external_recovery_reservation(
        request_id=execution.metadata.span_id,
        reserved_bytes=reserved_bytes,
    )
    execution.gpu_id = target_gpu
    execution.status = experiment_module._ExecutionStatus.RECOVERING
    execution.hbm_recovery_reserved_bytes = reserved_bytes
    execution.hbm_allocation_gpu_id = target_gpu

    runtime._sync_continuous_execution_hbm(target_gpu)
    runtime._check_invariants(runtime.des)

    assert execution.hbm_allocated_bytes == 0
    assert execution.hbm_recovery_reserved_bytes == reserved_bytes
    assert execution.hbm_allocation_gpu_id == target_gpu


def test_recovery_inbound_borrows_full_reserved_destination_without_double_charge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records(),
        variant=core_variants()[1],
        context_bucket="8k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=1,
    )
    execution = next(iter(runtime.executions.values()))
    target_gpu = "gpu-0"
    transfer_id = "test-recovery-reserved-destination"
    transfer_bytes = 2 * experiment_module.KV_BYTES_PER_SOURCE_BLOCK
    task = runtime._make_transfer_task(
        transfer_id=transfer_id,
        span_id=execution.metadata.span_id,
        source_id=runtime.store_segment_ids[0],
        target_id=target_gpu,
        cause="AEGIS_RECOVERY_STORE_DRAM",
        route_version=1,
        ready_ns=0,
        total_bytes=transfer_bytes,
    )
    staging_bytes = max(item.length_bytes for item in task.slices)
    initial_handle = runtime.des.schedule_at(
        0,
        EventKind.RECOVERY_START,
        event_id="initial-recovery-start",
        payload={"transfer_id": transfer_id},
    )
    runtime.pending_recovery_transfers[transfer_id] = (
        experiment_module._PendingRecoveryTransfer(
            transfer_id=transfer_id,
            span_id=execution.metadata.span_id,
            source="STORE_DRAM",
            source_gpu_id=runtime.store_segment_ids[0],
            target_gpu_id=target_gpu,
            task=task,
            handle=initial_handle,
            bytes=transfer_bytes,
            staging_bytes=staging_bytes,
        )
    )
    runtime.recovery_transfer_ids_by_span[execution.metadata.span_id] = {
        transfer_id
    }
    runtime._record_transfer(
        experiment_module._transfer_record(
            transfer_id=transfer_id,
            path="STORE_H2D",
            cause="AEGIS_RECOVERY_STORE_DRAM",
            start_ns=0,
            end_ns=1,
            bytes=transfer_bytes,
            source_gpu_id=runtime.store_segment_ids[0],
            target_gpu_id=target_gpu,
            ready_ns=0,
            status="PENDING",
            span_id=execution.metadata.span_id,
            flow_slice_count=len(task.slices),
        )
    )
    runtime._bind_transfer_task_metadata(task)

    ledger = runtime.hbm_ledgers[target_gpu]
    recovery_reserved_bytes = transfer_bytes
    runtime._commit_hbm_moves(
        target_gpu,
        [
            (
                experiment_module.FREE_ACCOUNT,
                experiment_module.HBM_RECOVERY_RESERVED_ACCOUNT,
                recovery_reserved_bytes,
            )
        ],
        cause="TEST_RECOVERY_DESTINATION_RESERVE",
    )
    active_primary_bytes = ledger.bytes_in(experiment_module.FREE_ACCOUNT)
    runtime._commit_hbm_moves(
        target_gpu,
        [
            (
                experiment_module.FREE_ACCOUNT,
                experiment_module.HBM_ACTIVE_PRIMARY_ACCOUNT,
                active_primary_bytes,
            )
        ],
        cause="TEST_ACTIVE_PRIMARY_PRESSURE",
    )
    execution.route_version = 1
    execution.gpu_id = target_gpu
    execution.status = experiment_module._ExecutionStatus.RECOVERING
    execution.hbm_allocation_gpu_id = target_gpu
    execution.hbm_allocated_bytes = active_primary_bytes
    execution.hbm_recovery_reserved_bytes = recovery_reserved_bytes
    before_accounts = dict(ledger.accounts)
    before_timeline_length = len(runtime.hbm_timelines[target_gpu])
    materialized: list[tuple[str, int]] = []

    def capture_materialized(
        recovered: experiment_module._SpanExecution, *, at_ns: int
    ) -> None:
        materialized.append((recovered.metadata.span_id, at_ns))

    monkeypatch.setattr(
        runtime,
        "_schedule_recovery_materialized",
        capture_materialized,
    )

    runtime.des.run()

    assert task.status is TransferStatus.COMPLETED
    assert transfer_id not in runtime.pending_recovery_transfers
    assert execution.metadata.span_id not in runtime.recovery_transfer_ids_by_span
    assert len(materialized) == 1
    assert materialized[0][0] == execution.metadata.span_id
    assert execution.hbm_staging_bytes == 0
    assert ledger.bytes_in(experiment_module.HBM_TRANSFER_STAGING_ACCOUNT) == 0
    assert ledger.bytes_in(
        experiment_module.HBM_RECOVERY_RESERVED_ACCOUNT
    ) == recovery_reserved_bytes
    assert ledger.bytes_in(experiment_module.HBM_ACTIVE_PRIMARY_ACCOUNT) == (
        active_primary_bytes
    )
    assert ledger.bytes_in(experiment_module.FREE_ACCOUNT) == 0
    assert dict(ledger.accounts) == before_accounts
    assert len(runtime.hbm_timelines[target_gpu]) == before_timeline_length
    assert sum(ledger.accounts.values()) == ledger.capacity_bytes
    [destination_write] = [
        event
        for event in runtime.recovery_events
        if event["event"] == "RECOVERY_RESERVED_DESTINATION_WRITE_START"
    ]
    assert destination_write["borrowed_destination_window_bytes"] == staging_bytes
    assert destination_write["additional_hbm_charge_bytes"] == 0


def _install_recovery_transfer_group(
    runtime: experiment_module._StudyRuntime,
    execution: experiment_module._SpanExecution,
    *,
    target_gpu: str,
    start_ns: int,
) -> tuple[experiment_module._PendingRecoveryTransfer, ...]:
    transfer_bytes = 2 * experiment_module.KV_BYTES_PER_SOURCE_BLOCK
    specs = (
        ("STORE_DRAM", runtime.store_segment_ids[0], "STORE_H2D"),
        ("PEER_HBM", "gpu-1", "D2D_P2P"),
    )
    pending_group: list[experiment_module._PendingRecoveryTransfer] = []
    for index, (source, source_id, path) in enumerate(specs):
        transfer_id = f"test-recovery-group-{index}"
        task = runtime._make_transfer_task(
            transfer_id=transfer_id,
            span_id=execution.metadata.span_id,
            source_id=source_id,
            target_id=target_gpu,
            cause=f"AEGIS_RECOVERY_{source}",
            route_version=1,
            ready_ns=start_ns,
            total_bytes=transfer_bytes,
        )
        handle = runtime.des.schedule_at(
            start_ns,
            EventKind.RECOVERY_START,
            event_id=f"start:{transfer_id}",
            payload={"transfer_id": transfer_id},
        )
        pending = experiment_module._PendingRecoveryTransfer(
            transfer_id=transfer_id,
            span_id=execution.metadata.span_id,
            source=source,
            source_gpu_id=source_id,
            target_gpu_id=target_gpu,
            task=task,
            handle=handle,
            bytes=transfer_bytes,
            staging_bytes=max(item.length_bytes for item in task.slices),
        )
        runtime.pending_recovery_transfers[transfer_id] = pending
        runtime._record_transfer(
            experiment_module._transfer_record(
                transfer_id=transfer_id,
                path=path,
                cause=f"AEGIS_RECOVERY_{source}",
                start_ns=start_ns,
                end_ns=start_ns + 1,
                bytes=transfer_bytes,
                source_gpu_id=source_id,
                target_gpu_id=target_gpu,
                ready_ns=start_ns,
                status="PENDING",
                span_id=execution.metadata.span_id,
                flow_slice_count=len(task.slices),
            )
        )
        runtime._bind_transfer_task_metadata(task)
        pending_group.append(pending)
    runtime.recovery_transfer_ids_by_span[execution.metadata.span_id] = {
        pending.transfer_id for pending in pending_group
    }
    recovery_reserved_bytes = sum(pending.bytes for pending in pending_group)
    runtime._commit_hbm_moves(
        target_gpu,
        [
            (
                experiment_module.FREE_ACCOUNT,
                experiment_module.HBM_RECOVERY_RESERVED_ACCOUNT,
                recovery_reserved_bytes,
            )
        ],
        cause="TEST_RECOVERY_GROUP_DESTINATION_RESERVE",
    )
    execution.route_version = 1
    execution.gpu_id = target_gpu
    execution.status = experiment_module._ExecutionStatus.RECOVERING
    execution.hbm_allocation_gpu_id = target_gpu
    execution.hbm_recovery_reserved_bytes = recovery_reserved_bytes
    runtime.continuous_hbm_authorities[
        target_gpu
    ].observe_external_recovery_reservation(
        request_id=execution.metadata.span_id,
        reserved_bytes=recovery_reserved_bytes,
    )
    return tuple(pending_group)


def _inject_failure_with_one_active_focus(
    runtime: experiment_module._StudyRuntime,
    *,
    focus: experiment_module._SpanExecution,
    target_gpu: str,
    failure_id: str,
) -> None:
    schedule = experiment_module.FailureEventSchedule(
        failure_id=failure_id,
        event_index=0,
        bucket="8k",
        seed=0,
        focus_span_id=focus.metadata.span_id,
        target_gpu_id=target_gpu,
        reference_at_ns=runtime.des.now_ns,
        target_workload_progress_per_mille=500,
        reference_completed_workflow_count=0,
        reference_workflow_count=1,
        detection_delay_ns=1_000_000_000_000,
        trigger_progress_per_mille=500,
        gpu_recovery_time_ns=2_000_000_000_000,
        selection_scope="continuous_failure_regression",
    )
    runtime.failure_schedule = experiment_module.FailureSchedule(
        (schedule,),
        selection_scope="continuous_failure_regression",
    )
    runtime._failure_schedule_by_id = {failure_id: schedule}
    runtime._failure_schedule_by_focus_span = {
        focus.metadata.span_id: schedule,
    }
    focus.gpu_id = target_gpu
    focus.status = experiment_module._ExecutionStatus.RUNNING

    def fence(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            requests=(
                SimpleNamespace(
                    request_id=focus.metadata.span_id,
                    queue_kind="RUNNING",
                    committed_output_tokens=0,
                ),
            ),
            pending_admissions=(),
        )

    runtime.continuous_batch_driver = SimpleNamespace(
        fence_for_external_gpu_failure=fence,
    )
    event = ScheduledEvent(
        timestamp_ns=runtime.des.now_ns,
        priority=0,
        stable_sequence=0,
        kind=EventKind.FAILURE_INJECT,
        event_id=f"inject:{failure_id}",
        payload={
            "failure_id": failure_id,
            "target_gpu_id": target_gpu,
            "reference_target_gpu_id": target_gpu,
            "resolved_target_gpu_id": target_gpu,
            "resolved_at_ns": runtime.des.now_ns,
            "resolved_compute_start_ns": runtime.des.now_ns,
            "resolved_compute_end_ns": runtime.des.now_ns + 1,
            "continuous_progress_evidence": {"test": True},
        },
    )
    runtime._on_failure_inject(event, runtime.des)


def test_continuous_protection_failure_retries_new_route_until_commit() -> None:
    runtime = experiment_module._StudyRuntime(
        records=[_single_exact_token_record()],
        variant=core_variants()[2],
        context_bucket="8k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=1,
    )
    execution = next(iter(runtime.executions.values()))
    failed_source = "gpu-0"
    execution.released_ns = runtime.des.now_ns
    execution.base_duration_ns = max(1, execution.metadata.recorded_api_time_ns)
    execution.gpu_id = failed_source
    execution.status = experiment_module._ExecutionStatus.RUNNING
    runtime._schedule_continuous_sealed_protection_puts(
        execution,
        source_gpu_id=failed_source,
        computed_prompt_tokens=execution.metadata.prompt_tokens,
    )
    route_zero_keys = set(execution.continuous_protection_batch_states)
    assert route_zero_keys
    assert {key[0] for key in route_zero_keys} == {0}

    runtime.des.run(until_ns=runtime.des.now_ns)
    route_zero_pending = tuple(runtime.pending_puts.values())
    assert route_zero_pending
    assert all(item.task.status is TransferStatus.WAITING for item in route_zero_pending)

    _inject_failure_with_one_active_focus(
        runtime,
        focus=execution,
        target_gpu=failed_source,
        failure_id="protection-before-commit",
    )

    assert not runtime.pending_puts
    assert all(
        runtime._transfer_by_id[item.transfer_id]["status"] == "ABORTED"
        for item in route_zero_pending
    )
    assert not route_zero_keys.intersection(
        execution.continuous_protection_batch_states
    )

    rerouted_source = "gpu-2"
    execution.route_version = 1
    execution.gpu_id = rerouted_source
    execution.status = experiment_module._ExecutionStatus.RUNNING
    runtime._schedule_continuous_sealed_protection_puts(
        execution,
        source_gpu_id=rerouted_source,
        computed_prompt_tokens=execution.metadata.prompt_tokens,
    )
    route_one_keys = {
        key for key in execution.continuous_protection_batch_states if key[0] == 1
    }
    assert route_one_keys
    runtime.des.run(until_ns=runtime.des.now_ns)
    route_one_pending = tuple(runtime.pending_puts.values())
    assert route_one_pending
    assert all(item.task.metadata.route_version == 1 for item in route_one_pending)

    runtime.des.run(until_ns=100_000_000_000)

    assert all(item.task.status is TransferStatus.COMPLETED for item in route_one_pending)
    assert all(
        execution.continuous_protection_batch_states[key].committed
        and not execution.continuous_protection_batch_states[key].failed
        and execution.continuous_protection_batch_states[key].outstanding_parts == 0
        for key in route_one_keys
    )
    transfer_count_after_commit = len(runtime.transfers)
    runtime._schedule_continuous_sealed_protection_puts(
        execution,
        source_gpu_id=rerouted_source,
        computed_prompt_tokens=execution.metadata.prompt_tokens,
    )
    assert not runtime.pending_put_starts
    assert len(runtime.transfers) == transfer_count_after_commit


@pytest.mark.parametrize("stage", ("WAITING", "PENDING"))
def test_subsequent_gpu_failure_fences_entire_recovery_group_and_recomputes(
    stage: str,
) -> None:
    runtime = experiment_module._StudyRuntime(
        records=[_single_exact_token_record()],
        variant=core_variants()[-1],
        context_bucket="8k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=1,
    )
    execution = next(iter(runtime.executions.values()))
    target_gpu = "gpu-0"
    start_ns = 100 if stage == "WAITING" else 0
    pending_group = _install_recovery_transfer_group(
        runtime,
        execution,
        target_gpu=target_gpu,
        start_ns=start_ns,
    )
    if stage == "PENDING":
        runtime.des.run(until_ns=0)
    expected_status = (
        TransferStatus.WAITING if stage == "WAITING" else TransferStatus.PENDING
    )
    assert {item.task.status for item in pending_group} == {expected_status}

    focus_id = f"{execution.metadata.span_id}:active-focus"
    focus = replace(
        execution,
        metadata=replace(execution.metadata, span_id=focus_id),
        chunks=(),
        status=experiment_module._ExecutionStatus.RUNNING,
        route_version=0,
        gpu_id=target_gpu,
        hbm_allocated_bytes=0,
        hbm_allocation_gpu_id=None,
        hbm_recovery_reserved_bytes=0,
        continuous_protection_batch_states={},
    )
    runtime.executions[focus_id] = focus
    _inject_failure_with_one_active_focus(
        runtime,
        focus=focus,
        target_gpu=target_gpu,
        failure_id=f"recovery-{stage.lower()}-second-failure",
    )

    assert not runtime.pending_recovery_transfers
    assert execution.metadata.span_id not in runtime.recovery_transfer_ids_by_span
    assert {item.task.status for item in pending_group} == {TransferStatus.CANCELED}
    assert not runtime.active_source_pins
    assert not runtime.active_host_staging
    assert all(
        runtime._transfer_by_id[item.transfer_id]["status"] == "ABORTED"
        for item in pending_group
    )
    [aborted_plan] = [
        item
        for item in runtime.recovery_events
        if item["event"] == "RECOVERY_PLAN_ABORTED_BY_GPU_FAILURE"
    ]
    assert set(aborted_plan["transfer_ids"]) == {
        item.transfer_id for item in pending_group
    }

    resumed: dict[str, object] = {}
    runtime.continuous_batch_driver = SimpleNamespace(
        resume_external_request=lambda **kwargs: resumed.update(kwargs),
        target_load_snapshot=lambda _gpu_id: {
            "queued_tokens": 0,
            "estimated_available_ns": runtime.des.now_ns,
            "resident_request_count": 0,
            "pending_admission_count": 0,
            "active_forward_remaining_ns": 0,
        },
    )
    detect = ScheduledEvent(
        timestamp_ns=runtime.des.now_ns,
        priority=0,
        stable_sequence=1,
        kind=EventKind.FAILURE_DETECT,
        event_id=f"detect-recovery-{stage.lower()}",
        payload={
            "active_span_ids": [],
            "queued_span_ids": [execution.metadata.span_id],
        },
    )
    runtime._on_failure_detect(detect, runtime.des)

    assert execution.route_version == 2
    assert execution.gpu_id != target_gpu
    assert execution.recompute_tokens == execution.metadata.prompt_tokens
    assert resumed["request_id"] == execution.metadata.span_id
    assert resumed["route_version"] == 2
    recovery_write_count = sum(
        item["event"] == "RECOVERY_RESERVED_DESTINATION_WRITE_START"
        for item in runtime.recovery_events
    )
    runtime.des.run(until_ns=100_000_000_000)
    assert sum(
        item["event"] == "RECOVERY_RESERVED_DESTINATION_WRITE_START"
        for item in runtime.recovery_events
    ) == recovery_write_count
    assert {item.task.status for item in pending_group} == {TransferStatus.CANCELED}


def test_scheduler_waiting_failure_is_reroute_only_not_failure_recompute() -> None:
    runtime = experiment_module._StudyRuntime(
        records=[_single_exact_token_record()],
        variant=core_variants()[-1],
        context_bucket="8k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=1,
    )
    execution = next(iter(runtime.executions.values()))
    target_gpu = "gpu-0"
    execution.gpu_id = target_gpu
    execution.status = experiment_module._ExecutionStatus.FENCED

    resumed: dict[str, object] = {}
    runtime.continuous_batch_driver = SimpleNamespace(
        resume_external_request=lambda **kwargs: resumed.update(kwargs),
        target_load_snapshot=lambda _gpu_id: {
            "queued_tokens": 0,
            "estimated_available_ns": runtime.des.now_ns,
            "resident_request_count": 0,
            "pending_admission_count": 0,
            "active_forward_remaining_ns": 0,
        },
    )
    detect = ScheduledEvent(
        timestamp_ns=runtime.des.now_ns,
        priority=0,
        stable_sequence=1,
        kind=EventKind.FAILURE_DETECT,
        event_id="detect-scheduler-waiting",
        payload={
            "active_span_ids": [],
            "queued_span_ids": [execution.metadata.span_id],
            "reroute_only_queued_span_ids": [execution.metadata.span_id],
        },
    )
    runtime._on_failure_detect(detect, runtime.des)

    assert execution.route_version == 1
    assert execution.recompute_tokens == 0
    assert resumed["request_id"] == execution.metadata.span_id
    assert resumed["route_version"] == 1
    assert resumed["restored_tokens"] == 0


def test_continuous_recovery_uses_fenced_output_snapshot_without_compute_start() -> None:
    runtime = experiment_module._StudyRuntime(
        records=[_single_exact_token_record()],
        variant=core_variants()[0],
        context_bucket="8k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=1,
    )
    execution = next(iter(runtime.executions.values()))
    execution.route_version = 1
    execution.failure_at_ns = 10
    execution.compute_start_ns = None
    execution.committed_output_tokens_at_failure = 0
    execution.recovery_ready_ns = 6
    execution.prompt_recompute_start_ns = 1
    execution.prompt_recompute_complete_ns = 2
    execution.silent_replay_start_ns = 3
    execution.silent_replay_complete_ns = 4
    execution.resume_decode_start_ns = 5

    runtime._plan_recovery(execution)

    assert execution.committed_output_tokens_at_failure == 0
    assert execution.route_version == 2
    assert execution.status is experiment_module._ExecutionStatus.RECOVERING
    assert execution.recovery_ready_ns is None
    assert execution.prompt_recompute_start_ns is None
    assert execution.prompt_recompute_complete_ns is None
    assert execution.silent_replay_start_ns is None
    assert execution.silent_replay_complete_ns is None
    assert execution.resume_decode_start_ns is None


def test_continuous_queued_second_failure_accounts_full_prompt_recompute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = experiment_module._StudyRuntime(
        records=[_single_exact_token_record()],
        variant=core_variants()[0],
        context_bucket="8k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=1,
    )
    execution = next(iter(runtime.executions.values()))
    prompt_tokens = execution.metadata.prompt_tokens
    execution.route_version = 1
    execution.failure_at_ns = 10
    execution.status = experiment_module._ExecutionStatus.FENCED
    execution.recovery_normal_hbm_local_tokens = 64
    execution.restored_peer_tokens = 64
    execution.restored_peer_local_tokens = 64
    execution.restored_store_tokens = 64
    execution.recompute_tokens = prompt_tokens - 192
    execution.recovery_ready_ns = 6
    execution.prompt_recompute_start_ns = 1
    execution.prompt_recompute_complete_ns = 2
    execution.silent_replay_start_ns = 3
    execution.silent_replay_complete_ns = 4
    execution.resume_decode_start_ns = 5
    resumed: dict[str, object] = {}

    def capture_resume(**kwargs: object) -> None:
        resumed.update(kwargs)

    monkeypatch.setattr(
        runtime,
        "continuous_batch_driver",
        SimpleNamespace(
            resume_external_request=capture_resume,
            target_load_snapshot=lambda _gpu_id: {
                "queued_tokens": 0,
                "estimated_available_ns": runtime.des.now_ns,
                "resident_request_count": 0,
                "pending_admission_count": 0,
                "active_forward_remaining_ns": 0,
            },
        ),
    )
    event = ScheduledEvent(
        timestamp_ns=runtime.des.now_ns,
        priority=0,
        stable_sequence=0,
        kind=EventKind.FAILURE_DETECT,
        event_id="detect:second-failure",
        payload={
            "active_span_ids": [],
            "queued_span_ids": [execution.metadata.span_id],
        },
    )

    runtime._on_failure_detect(event, runtime.des)

    assert execution.route_version == 2
    assert execution.status is experiment_module._ExecutionStatus.RECOVERING
    assert execution.recovery_normal_hbm_local_tokens == 0
    assert execution.restored_peer_tokens == 0
    assert execution.restored_peer_local_tokens == 0
    assert execution.restored_peer_d2d_tokens == 0
    assert execution.restored_store_tokens == 0
    assert execution.recompute_tokens == prompt_tokens
    assert execution.recovery_ready_ns is None
    assert execution.prompt_recompute_start_ns is None
    assert execution.prompt_recompute_complete_ns is None
    assert execution.silent_replay_start_ns is None
    assert execution.silent_replay_complete_ns is None
    assert execution.resume_decode_start_ns is None
    assert resumed == {
        "request_id": execution.metadata.span_id,
        "target_id": execution.gpu_id,
        "route_version": 2,
        "ready_ns": runtime.des.now_ns + runtime.parameters.reroute_ns,
        "restored_tokens": 0,
    }


def test_recovery_adopts_target_local_inactive_normal_hbm_without_transfer() -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records(),
        variant=core_variants()[1],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    execution = sorted(
        (item for item in runtime.executions.values() if len(item.chunks) > 1),
        key=lambda item: item.metadata.prompt_tokens,
    )[0]
    target_gpu = "gpu-1"
    cached_chunk = execution.chunks[0]
    assert runtime.primary_pools[target_gpu].insert(
        cached_chunk,
        score=Fraction(1),
        now_ns=0,
        cause="TEST_NORMAL_HBM_CACHE",
    )
    runtime._sync_primary_hbm_ledger(target_gpu, cause="TEST_NORMAL_HBM_CACHE")
    inactive_before = runtime.hbm_ledgers[target_gpu].bytes_in(
        experiment_module.HBM_INACTIVE_REUSABLE_ACCOUNT
    )
    execution.compute_start_ns = 0
    execution.scheduled_duration_ns = 100
    execution.base_duration_ns = 100
    execution.failure_at_ns = 0
    execution.status = experiment_module._ExecutionStatus.FENCED

    runtime._plan_recovery(execution)

    assert execution.gpu_id == target_gpu
    assert execution.recovery_normal_hbm_local_tokens == cached_chunk.token_count
    assert execution.restored_peer_tokens == 0
    assert execution.restored_store_tokens == 0
    assert execution.recompute_tokens == (
        execution.metadata.prompt_tokens - cached_chunk.token_count
    )
    assert runtime.hbm_ledgers[target_gpu].bytes_in(
        experiment_module.HBM_INACTIVE_REUSABLE_ACCOUNT
    ) == inactive_before - cached_chunk.bytes
    adoption = runtime.recovery_source_events
    assert len(adoption) == 1
    assert adoption[0]["event"] == "NORMAL_HBM_LOCAL_ADOPTION"
    assert adoption[0]["transferred_bytes"] == 0
    assert adoption[0]["protection_evidence"] is False
    assert all(
        transfer["cause"] != "RECOVERY_NORMAL_HBM_LOCAL_ADOPTION"
        for transfer in runtime.transfers
    )


def test_recovery_prefers_route_bound_peer_when_it_is_not_more_loaded() -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records(),
        # This test seeds physical pools directly, so use the static Peer-HBM
        # profile rather than bypassing the formal Landlord's ownership index.
        variant=core_variants()[2],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    execution = sorted(
        (item for item in runtime.executions.values() if len(item.chunks) >= 4),
        key=lambda item: item.metadata.prompt_tokens,
    )[0]
    designated = "gpu-2"
    unrelated = "gpu-3"
    execution.designated_peer_gpu_id = designated
    protection_chunks = runtime._protection_chunks(execution, path="PEER_HBM")
    assert runtime.peer_pools[designated].insert(
        protection_chunks[0],
        score=Fraction(1),
        now_ns=0,
        cause="TEST_DESIGNATED_PEER",
    )
    assert runtime.peer_pools[unrelated].insert(
        protection_chunks[0],
        score=Fraction(1),
        now_ns=0,
        cause="TEST_UNRELATED_PEER",
    )
    runtime._sync_peer_hbm_ledger(designated, cause="TEST_DESIGNATED_PEER")
    runtime._sync_peer_hbm_ledger(unrelated, cause="TEST_UNRELATED_PEER")
    execution.compute_start_ns = 0
    execution.scheduled_duration_ns = 100
    execution.base_duration_ns = 100
    execution.failure_at_ns = 0
    execution.status = experiment_module._ExecutionStatus.FENCED

    runtime._plan_recovery(execution)

    assert execution.gpu_id == designated
    assert execution.restored_peer_tokens == execution.chunks[0].token_count
    assert execution.restored_peer_local_tokens == execution.restored_peer_tokens
    assert execution.restored_peer_d2d_tokens == 0
    recovery_route = runtime.route_events[-1]
    assert recovery_route["preferred_gpu_id"] == designated
    assert recovery_route["selection_objective"] == (
        "minimum_estimated_completion_ns_with_remote_peer_d2d"
    )


def test_peer_target_prefers_free_quota_and_remains_route_bound() -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records(),
        variant=core_variants()[-1],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    execution = next(iter(runtime.executions.values()))
    source = "gpu-0"
    candidates = [gpu_id for gpu_id in runtime.gpu_ids if gpu_id != source]
    preferred, congested = candidates[:2]
    preferred_pool = runtime.peer_pools[preferred]
    congested_pool = runtime.peer_pools[congested]
    congested_pool.capacity_bytes = 0

    selected = runtime._peer_target(
        source_gpu_id=source,
        span_id=execution.metadata.span_id,
    )

    assert selected != congested
    execution.designated_peer_gpu_id = selected
    preferred_pool.capacity_bytes = 0
    assert runtime._peer_target(
        source_gpu_id=source,
        span_id=execution.metadata.span_id,
    ) == selected


def test_algorithm2_bypass_parks_suffix_instead_of_permanently_blocking() -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records()[:1],
        variant=core_variants()[-1],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    execution = next(iter(runtime.executions.values()))
    span_id = execution.metadata.span_id
    path = "PEER_HBM"
    key = (span_id, path)
    batch_key = (0, path, 1, "gpu-1")
    dummy = experiment_module._PendingPutStart(
        plan_id="park-test",
        span_id=span_id,
        path=path,
        source_gpu_id="gpu-0",
        target_gpu_id="gpu-1",
        target_store_id=None,
        chunks=execution.chunks[:1],
        handle=EventHandle("park-test"),
        produced_ns=0,
        continuous_batch_key=batch_key,
    )
    execution.continuous_protection_batch_states[batch_key] = (
        experiment_module._ContinuousProtectionBatchState()
    )
    runtime._formal_active_request_paths.add(key)
    runtime._formal_waiting_put_starts[key] = [dummy]

    runtime._formal_finish_request_path(
        span_id,
        path,
        block=False,
        park_suffix=True,
    )

    assert key not in runtime._formal_blocked_request_paths
    assert key not in runtime._formal_active_request_paths
    assert runtime._formal_waiting_put_starts[key] == [dummy]
    assert batch_key in execution.continuous_protection_batch_states
    assert execution.continuous_protection_batch_states[batch_key].outstanding_parts == 1
    assert any(
        item["event"] == "FORMAL_PREFIX_PARKED_FOR_RETRY"
        for item in runtime.formal_policy_events
    )


def test_algorithm2_failure_block_still_drops_queued_suffix() -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records()[:1],
        variant=core_variants()[-1],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    execution = next(iter(runtime.executions.values()))
    span_id = execution.metadata.span_id
    path = "STORE_DRAM"
    key = (span_id, path)
    batch_key = (0, path, 1, "store-0:segment-0")
    dummy = experiment_module._PendingPutStart(
        plan_id="block-test",
        span_id=span_id,
        path=path,
        source_gpu_id="gpu-0",
        target_gpu_id=None,
        target_store_id="store-0:segment-0",
        chunks=execution.chunks[:1],
        handle=EventHandle("block-test"),
        produced_ns=0,
        continuous_batch_key=batch_key,
    )
    execution.continuous_protection_batch_states[batch_key] = (
        experiment_module._ContinuousProtectionBatchState()
    )
    runtime._formal_waiting_put_starts[key] = [dummy]

    runtime._formal_finish_request_path(span_id, path, block=True)

    assert key in runtime._formal_blocked_request_paths
    assert key not in runtime._formal_waiting_put_starts
    assert batch_key not in execution.continuous_protection_batch_states


def test_recovery_uses_d2d_peer_when_designated_gpu_is_more_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records(),
        variant=core_variants()[2],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    execution = sorted(
        (item for item in runtime.executions.values() if len(item.chunks) >= 4),
        key=lambda item: item.metadata.prompt_tokens,
    )[0]
    designated = "gpu-2"
    execution.designated_peer_gpu_id = designated
    protection_chunks = runtime._protection_chunks(execution, path="PEER_HBM")
    assert runtime.peer_pools[designated].insert(
        protection_chunks[0],
        score=Fraction(1),
        now_ns=0,
        cause="TEST_DESIGNATED_PEER",
    )
    runtime._sync_peer_hbm_ledger(designated, cause="TEST_DESIGNATED_PEER")
    execution.compute_start_ns = 0
    execution.scheduled_duration_ns = 100
    execution.base_duration_ns = 100
    execution.failure_at_ns = 0
    execution.status = experiment_module._ExecutionStatus.FENCED
    runtime.compute[designated].reserve(
        ready_ns=0,
        duration_ns=10**12,
        reservation_id="test-busy-designated-peer",
        cause="TEST_DESIGNATED_PEER_QUEUE",
    )
    if runtime.continuous_batch_driver is not None:
        monkeypatch.setattr(
            runtime.continuous_batch_driver,
            "target_load_snapshot",
            lambda gpu_id: {
                "queued_tokens": 10_000_000 if gpu_id == designated else 0,
                "estimated_available_ns": (
                    runtime.des.now_ns + (10**12 if gpu_id == designated else 0)
                ),
                "resident_request_count": 8 if gpu_id == designated else 0,
                "pending_admission_count": 0,
                "active_forward_remaining_ns": (
                    10**12 if gpu_id == designated else 0
                ),
            },
        )

    runtime._plan_recovery(execution)

    assert execution.gpu_id != designated
    assert execution.restored_peer_tokens == protection_chunks[0].token_count
    assert execution.restored_peer_d2d_tokens == execution.restored_peer_tokens
    assert execution.restored_peer_local_tokens == 0
    recovery_route = runtime.route_events[-1]
    selected = recovery_route["candidates"][execution.gpu_id]
    assert recovery_route["selection_objective"] == (
        "minimum_estimated_completion_ns_with_remote_peer_d2d"
    )
    assert selected["remote_peer_d2d_prefix_tokens"] == (
        protection_chunks[0].token_count
    )
    assert selected["peer_d2d_ns"] > 0
    assert selected["effective_prefix_tokens"] >= protection_chunks[0].token_count


def test_aimd_pressure_uses_safe_primary_headroom_before_peer_reclaim() -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records(),
        variant=core_variants()[-1],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    gpu_id = "gpu-0"
    ledger = runtime.hbm_ledgers[gpu_id]
    safe_headroom = ledger.bytes_in(experiment_module.FREE_ACCOUNT) + ledger.bytes_in(
        experiment_module.HBM_INACTIVE_REUSABLE_ACCOUNT
    )

    assert not runtime._latch_aimd_foreground_pressure(
        gpu_id,
        safe_headroom,
        reason="PRIMARY_HEADROOM_SHORTFALL",
    )
    assert runtime._latch_aimd_foreground_pressure(
        gpu_id,
        safe_headroom + 1,
        reason="PRIMARY_HEADROOM_SHORTFALL",
    )
    assert runtime._aimd_pending_pressure[gpu_id] is False
    assert runtime._aimd_pending_shortfall_bytes[gpu_id] == 0
    assert runtime.aimd_events[-1]["action"] == "MULTIPLICATIVE_DECREASE"
    assert runtime.aimd_events[-1]["update_basis"] == "IMMEDIATE_PRESSURE_EVENT"
    assert runtime.aimd_events[-1]["foreground_shortfall_bytes"] == 1
    assert runtime.aimd_events[-1]["pressure_reasons"] == [
        "PRIMARY_HEADROOM_SHORTFALL"
    ]
    assert runtime.aimd_events[-1]["timestamp_ns"] == runtime.des.now_ns
    assert runtime.hbm_pressure_observations[-1]["headroom_shortfall_bytes"] == 1


def test_compute_rebook_priority_uses_remaining_slack_before_normal() -> None:
    make_spec = experiment_module._ComputeSpec
    kind = experiment_module._ComputeKind
    urgent = make_spec(
        span_id="urgent",
        route_version=1,
        gpu_id="gpu-0",
        kind=kind.RECOVERY_PROMPT,
        ready_ns=100,
        duration_ns=10,
        recovery_due_ns=90,
        prior_start_ns=100,
        prior_end_ns=110,
        prior_reservation_id="new:urgent",
    )
    loose = make_spec(
        span_id="loose",
        route_version=1,
        gpu_id="gpu-0",
        kind=kind.RECOVERY_SILENT,
        ready_ns=100,
        duration_ns=10,
        recovery_due_ns=300,
        prior_start_ns=100,
        prior_end_ns=110,
        prior_reservation_id="new:loose",
    )
    normal = make_spec(
        span_id="normal",
        route_version=0,
        gpu_id="gpu-0",
        kind=kind.NORMAL,
        ready_ns=0,
        duration_ns=10,
        recovery_due_ns=None,
        prior_start_ns=100,
        prior_end_ns=110,
        prior_reservation_id="old:normal",
    )

    ordered = sorted(
        (normal, loose, urgent),
        key=lambda spec: experiment_module._compute_rebook_priority_key(
            spec, now_ns=100
        ),
    )

    assert [spec.span_id for spec in ordered] == ["urgent", "loose", "normal"]
    assert experiment_module._compute_rebook_priority_key(
        urgent, now_ns=100
    )[1] == 0
    assert experiment_module._compute_rebook_priority_key(
        loose, now_ns=100
    )[1] == 200


def test_recovery_compute_rebooks_only_unstarted_normal_and_all_handles() -> None:
    runtime = experiment_module._StudyRuntime(
        records=_committed_records(),
        variant=core_variants()[-1],
        context_bucket="64k",
        seed=0,
        failure_schedule=None,
        workflow_concurrency=None,
    )
    executions = sorted(
        runtime.executions.values(),
        key=lambda item: item.metadata.prompt_tokens,
    )[:3]
    active, queued, recovering = executions
    runtime._schedule_compute(active, gpu_id="gpu-0", ready_ns=0, duration_ns=100)
    runtime._schedule_compute(queued, gpu_id="gpu-0", ready_ns=0, duration_ns=100)
    runtime.des.run(until_ns=0)
    active_booking = runtime._compute_bookings_by_span[active.metadata.span_id]
    old_active_interval = (
        active_booking.reservation_id,
        active_booking.start_ns,
        active_booking.end_ns,
    )
    queued_booking = runtime._compute_bookings_by_span[queued.metadata.span_id]
    old_queued_reservation_id = queued_booking.reservation_id
    old_queued_start_handle = queued_booking.start_handle
    old_queued_completion_handle = queued_booking.completion_handle
    old_plan_ids = {
        plan_id
        for plan_id, plan in runtime.pending_put_starts.items()
        if plan.span_id == queued.metadata.span_id
    }

    recovering.released_ns = runtime.des.now_ns
    recovering.failure_at_ns = runtime.des.now_ns
    recovering.status = experiment_module._ExecutionStatus.RECOVERING
    recovering.gpu_id = "gpu-0"
    recovery_booking = runtime._book_ready_recovery_compute(
        recovering,
        gpu_id="gpu-0",
        kind=experiment_module._ComputeKind.RECOVERY_PROMPT,
        duration_ns=10,
    )

    new_active = runtime._compute_bookings_by_span[active.metadata.span_id]
    new_queued = runtime._compute_bookings_by_span[queued.metadata.span_id]
    assert (
        new_active.reservation_id,
        new_active.start_ns,
        new_active.end_ns,
    ) == old_active_interval
    assert new_active.started is True
    assert recovery_booking.start_ns == new_active.end_ns
    assert new_queued.start_ns == recovery_booking.end_ns
    assert new_queued.reservation_id != old_queued_reservation_id
    assert runtime.compute["gpu-0"].reservation(old_queued_reservation_id) is None
    assert runtime.des.cancel(
        old_queued_start_handle, reason="TEST_ALREADY_REBOOKED"
    ) is False
    assert runtime.des.cancel(
        old_queued_completion_handle, reason="TEST_ALREADY_REBOOKED"
    ) is False
    new_plan_ids = {
        plan_id
        for plan_id, plan in runtime.pending_put_starts.items()
        if plan.span_id == queued.metadata.span_id
    }
    assert old_plan_ids
    assert new_plan_ids
    assert old_plan_ids.isdisjoint(new_plan_ids)
    audit = runtime.compute_rebook_events[-1]
    assert audit["rebooked_normal_count"] == 1
    assert [item["kind"] for item in audit["ordered_bookings"]] == [
        "RECOVERY_PROMPT",
        "NORMAL",
    ]
    assert audit["started_compute_preempted"] is False
    assert audit["transfer_priority_changed"] is False


def test_peer_prefix_activation_reclassifies_without_eviction() -> None:
    chunks = tuple(
        experiment_module._Chunk(
            key=f"chunk-{index}",
            workflow_id="wf",
            token_start=index * 1_024,
            token_count=1_024,
            bytes=4_096,
        )
        for index in range(2)
    )
    pool = experiment_module._ModeledPool(
        pool_id="PEER_HBM:gpu-0",
        capacity_bytes=8_192,
        eviction=experiment_module.EvictionKind.SLACK_LANDLORD_VALUE,
        seed=0,
    )
    for chunk in chunks:
        assert pool.insert(
            chunk,
            score=Fraction(1),
            now_ns=0,
            cause="TEST_INSERT",
        )

    activated = pool.activate_prefix(
        chunks,
        token_count=1_024,
        now_ns=1,
        cause="TEST_LOCAL_ACTIVATION",
    )

    assert activated == 4_096
    assert pool.occupied_bytes == 4_096
    assert set(pool.entries) == {"chunk-1"}
    assert pool.evicted_chunks == 0
    assert pool.timeline[-1]["cause"] == "TEST_LOCAL_ACTIVATION"


@pytest.mark.parametrize(
    ("failure_count", "targets"),
    (
        (1, (500,)),
        (3, (250, 500, 750)),
        (4, (200, 400, 600, 800)),
    ),
)
def test_variant_local_schedule_executes_configured_failure_count(
    failure_count: int,
    targets: tuple[int, ...],
) -> None:
    records = _committed_records()
    variant = core_variants()[-1]
    schedule = derive_failure_schedule(
        records,
        bucket="64k",
        seed=20260830,
        failure_count=failure_count,
        compared_profiles=(variant.profile,),
    )
    result = run_study_cell(
        records,
        CellSpec(
            variant=variant,
            context_bucket="64k",
            scenario=Scenario.GPU_FAILURE,
            seed=20260830,
            repetition="A",
            failure_schedule=schedule,
        ),
    )

    assert tuple(
        event.target_workload_progress_per_mille for event in schedule.events
    ) == targets
    assert result.payload["metrics"]["failure_impact"]["failure_event_count"] == (
        failure_count
    )
    assert result.payload["metrics"]["gpu_capacity_recovery"]["completed_count"] == (
        failure_count
    )
    assert all(
        event["logical_trigger"]["focus_span_id"] in event["impacted_active_span_ids"]
        for event in result.representative["failure_events"]
    )


def test_qwen3_8b_dp_only_scope_is_fixed_and_machine_auditable() -> None:
    contract = qwen3_8b_dp_only_contract()
    deployment = ModelParameters(dp_count=8).to_dict()["model_deployment"]

    assert contract["model"] == {
        "id": "Qwen/Qwen3-8B",
        "revision": "b968826d9c46dd6066d109eabc6255188de91218",
        "config_sha256": (
            "f7c4eadfbbf522470667b797a3c89be2524832d2d599797248dc304fff447c30"
        ),
        "other_models_allowed": False,
    }
    assert contract["parallelism"] == {
        "data_parallel_size": 8,
        "allowed_data_parallel_sizes": [8],
        "data_parallel_sensitivity_allowed": False,
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "tensor_parallel_sensitivity_allowed": False,
        "pipeline_parallel_sensitivity_allowed": False,
    }
    assert contract["hardware"] == {
        "gpu_sku": "NVIDIA-A100-40GB",
        "gpu_count": 8,
        "node_count": 1,
        "topology": "single_node",
        "physical_hbm_bytes_per_gpu": 40 * 1024**3,
        "evidence": "modeled_not_physically_calibrated",
    }
    assert deployment == qwen3_8b_dp_deployment(8)
    assert deployment["parallelism"]["data_parallel_size"] == 8
    with pytest.raises(ValueError, match="dp_count"):
        ModelParameters(dp_count=16)
    with pytest.raises(ValueError, match="A100-40GB"):
        ModelParameters(physical_hbm_bytes_per_gpu=80 * 1024**3)


def test_store_transport_paths_charge_host_staging_only_when_explicit() -> None:
    records = _committed_records()
    for transport in (
        TransportKind.PCIE,
        TransportKind.RDMA_GDR,
        TransportKind.RDMA_HOST_STAGED,
        TransportKind.TCP_HOST_STAGED,
    ):
        parameters = ModelParameters(store_transport=transport)
        result = run_study_cell(
            records,
            CellSpec(
                variant=core_variants(parameters)[3],
                context_bucket="8k",
                scenario=Scenario.NO_FAILURE,
                seed=9,
                repetition="A",
            ),
        )
        store_transfers = [
            item
            for item in result.representative["transfers"]
            if item["cause"].startswith("AEGIS_STORE_DRAM_")
        ]
        assert store_transfers
        assert {item["transport"] for item in store_transfers} == {transport.value}
        resource_cost = result.payload["metrics"]["resource_cost"]
        assert resource_cost["source_pin_acquire_count"] >= len(store_transfers)
        assert resource_cost["source_pin_count_final"] == 0
        host_stacks = resource_cost["host_dram_staging_by_gpu"]
        assert all(item["valid"] for item in host_stacks.values())
        assert all(
            item["final_accounts"]["TRANSFER_STAGING"] == 0
            for item in host_stacks.values()
        )
        if transport in {TransportKind.PCIE, TransportKind.RDMA_GDR}:
            assert resource_cost["host_dram_staging_peak_bytes"] == 0
            assert resource_cost["host_staging_acquire_count"] == 0
            assert all(
                item["source_host_staging_resource_id"] is None
                and item["destination_host_staging_resource_id"] is None
                for item in store_transfers
            )
            if transport is TransportKind.PCIE:
                assert all(
                    "peer-fabric-rate" in item["rate_resource_ids"]
                    for item in store_transfers
                )
        else:
            assert resource_cost["host_dram_staging_peak_bytes"] > 0
            assert resource_cost["host_staging_acquire_count"] == len(store_transfers)
            assert all(
                item["source_host_staging_resource_id"] is not None
                for item in store_transfers
            )
            expected_fabric = (
                "store-tcp-fabric-rate"
                if transport is TransportKind.TCP_HOST_STAGED
                else "store-fabric-rate"
            )
            assert all(
                expected_fabric in item["rate_resource_ids"]
                for item in store_transfers
            )


def test_four_store_nodes_partition_capacity_and_restore_from_multiple_segments() -> None:
    records = _committed_records()
    parameters = ModelParameters(
        store_node_count=4,
        store_transport=TransportKind.RDMA_GDR,
        failure_progress_per_mille=600,
    )
    variant = core_variants(parameters)[-1]
    schedule = derive_failure_schedule(
        records,
        bucket="32k",
        seed=0,
        parameters=parameters,
    )
    first = run_study_cell(
        records,
        CellSpec(
            variant=variant,
            context_bucket="32k",
            scenario=Scenario.GPU_FAILURE,
            seed=0,
            repetition="A",
            failure_schedule=schedule,
        ),
    )
    second = run_study_cell(
        records,
        CellSpec(
            variant=variant,
            context_bucket="32k",
            scenario=Scenario.GPU_FAILURE,
            seed=0,
            repetition="B",
            failure_schedule=schedule,
        ),
    )
    assert first.payload_sha256 == second.payload_sha256
    assert first.journal_sha256 == second.journal_sha256
    resource_model = first.payload["resource_model"]
    assert resource_model["store_node_count"] == 4
    assert resource_model["store_dram_segments"] == [
        f"store-{index}:segment-0" for index in range(4)
    ]
    store_segments = first.payload["metrics"]["resource_cost"][
        "store_dram_by_segment"
    ]
    assert len(store_segments) == 4
    assert sum(item["capacity_bytes"] for item in store_segments.values()) == (
        parameters.store_budget_bytes
    )
    assert all(item["valid"] for item in store_segments.values())
    assert set(first.representative["store_dram_timelines"]) == set(store_segments)
    recovery = [
        item
        for item in first.representative["transfers"]
        if item["cause"] == "AEGIS_RECOVERY_STORE_DRAM"
    ]
    assert recovery
    assert {item["source"] for item in recovery} <= set(store_segments)
    assert len({item["source"] for item in recovery}) >= 2
    for item in recovery:
        node_id = item["source"].split(":", 1)[0]
        assert f"{node_id}.dram-rate" in item["rate_resource_ids"]
        assert f"{node_id}.fabric-rate" in item["rate_resource_ids"]
    assert first.payload["metrics"]["pool_audit"][
        "pending_destination_bytes_final"
    ] == 0


def test_sensitivity_catalog_binds_fabric_and_reroute_parameters() -> None:
    variants = {item.variant_id: item for item in sensitivity_variants()}

    assert str(variants["peer_hbm_alpha_percent=0"].parameters.peer_hbm_alpha) == "0"
    assert str(variants["peer_hbm_alpha_percent=20"].parameters.peer_hbm_alpha) == "0.2"
    assert str(variants["peer_hbm_alpha_percent=50"].parameters.peer_hbm_alpha) == "0.5"
    assert (
        variants["peer_fabric_bandwidth_gbps=50"]
        .parameters.peer_bandwidth_bytes_per_second
        == 50_000_000_000
    )
    assert all(item.parameters.failure_detection_ns == 0 for item in variants.values())
    assert variants["reroute_delay_ms=0"].parameters.reroute_ns == 0


def test_peer_hbm_quota_uses_alpha_times_kv_capacity_without_profile_rescaling() -> None:
    parameters = ModelParameters()
    result = run_study_cell(
        _committed_records(),
        CellSpec(
            variant=core_variants(parameters)[2],
            context_bucket="8k",
            scenario=Scenario.NO_FAILURE,
            seed=3,
            repetition="A",
        ),
    )
    per_gpu = result.payload["metrics"]["pool_audit"]["peer_hbm"]["per_gpu"]
    assert per_gpu
    assert {
        item["quota_bytes"] for item in per_gpu.values()
    } == {parameters.peer_hbm_quota_bytes_per_gpu}
    assert {
        item["physical_capacity_bytes"] for item in per_gpu.values()
    } == {parameters.kv_capacity_bytes_per_gpu}


def test_failure_cell_is_fresh_run_byte_identical_and_scope_limited() -> None:
    records = _committed_records()
    schedule = derive_failure_schedule(records, bucket="64k", seed=20260830)
    variant = core_variants()[-1]
    first = run_study_cell(
        records,
        CellSpec(
            variant=variant,
            context_bucket="64k",
            scenario=Scenario.GPU_FAILURE,
            seed=20260830,
            repetition="A",
            failure_schedule=schedule,
        ),
    )
    second = run_study_cell(
        records,
        CellSpec(
            variant=variant,
            context_bucket="64k",
            scenario=Scenario.GPU_FAILURE,
            seed=20260830,
            repetition="B",
            failure_schedule=schedule,
        ),
    )
    assert first.payload_sha256 == second.payload_sha256
    assert first.journal_sha256 == second.journal_sha256
    assert first.payload == second.payload
    assert first.payload["global_clock"] == {
        "kind": "single_global_virtual_clock",
        "time_unit": "ns",
        "wall_clock_or_sleep_used": False,
        "event_order": "timestamp_priority_stable_sequence",
    }
    assert first.payload["evidence"] == {
        "class": "E2",
        "scope": "modeled/preliminary",
        "calibration": "not_calibrated",
        "physical_execution": False,
        "physical_timing_claim_allowed": False,
        "formal_use_allowed": False,
        "paper_ready": False,
    }
    assert first.payload["metrics"]["failure_impact"]["active_requests"] >= 1
    assert first.payload["metrics"]["gpu_capacity_recovery"] == {
        "fixed_time_ns": 120_000_000_000,
        "scheduled_count": 2,
        "completed_count": 2,
    }
    assert first.payload["output_audit"]["duplicate_or_missing_tokens"] == 0
    assert first.payload["output_audit"]["stale_route_output_count"] == 0
    assert set(first.payload["metrics"]["restored_tokens"]) == {
        "peer_hbm",
        "store_dram",
        "total",
    }
    assert all(value == 0 for value in first.payload["forbidden_semantics"].values())
    assert first.payload["metrics"]["pool_audit"]["unattributed_reserve_bytes"] == 0
    assert first.payload["metrics"]["pool_audit"]["pending_destination_bytes_final"] == 0
    resource_model = first.payload["resource_model"]
    assert resource_model["communication_backend"] == "flow_contention"
    assert resource_model["fairness"] == "weighted_max_min_work_conserving"
    assert resource_model["flow_clock"] == "shared_global_des_now_ns"
    assert resource_model["foreground_store_restore_model"] == (
        "destination_reserved_store_to_gpu_flow_with_shared_contention"
    )
    resource_cost = first.payload["metrics"]["resource_cost"]
    assert resource_cost["transfer_byte_conservation_valid"] is True
    assert resource_cost["transfer_state_counts"].get("PENDING", 0) == 0
    assert resource_cost["gpu_hbm_recovery_reserve_peak_bytes"] > 0
    hbm_stacks = resource_cost["gpu_hbm_account_stack_by_gpu"]
    assert all(item["valid"] for item in hbm_stacks.values())
    for item in hbm_stacks.values():
        final = item["final_accounts"]
        assert sum(final.values()) == item["capacity_bytes"]
        assert final["ACTIVE_PRIMARY_KV"] == 0
        assert final["RECOVERY_DEST_RESERVED"] == 0
        assert final["TRANSFER_STAGING"] == 0
        assert final["UNATTRIBUTED_RESERVE"] == 0
    assert len(first.representative["failure_events"]) == 2
    compute_rebooks = first.representative["compute_rebook_events"]
    assert compute_rebooks
    for rebook in compute_rebooks:
        assert rebook["ready_recovery_order"] == (
            "IDEAL_CPM_REMAINING_SLACK_DUE_TIME"
        )
        assert rebook["scheduler_extension"] == (
            "RECOVERY_OVER_UNSTARTED_NORMAL_COMPUTE"
        )
        assert rebook["started_compute_preempted"] is False
        assert rebook["transfer_priority_changed"] is False
        ordered = rebook["ordered_bookings"]
        classes = [entry["priority_key"][0] for entry in ordered]
        assert classes == sorted(classes)
        for entry in ordered:
            if entry["old_start_ns"] is not None:
                assert entry["old_start_ns"] >= rebook["timestamp_ns"]
    for failure_event in first.representative["failure_events"]:
        assert failure_event["repair_after_ns"] == 120_000_000_000
        assert failure_event["repair_completed_at_ns"] == (
            failure_event["timestamp_ns"] + failure_event["repair_after_ns"]
        )
        failed_gpu_id = failure_event["target_gpu_id"]
        failed_gpu_timeline = first.representative["gpu_hbm_timelines"][failed_gpu_id]
        assert any(
            point["accounts"]["UNAVAILABLE_CAPACITY"]
            == resource_model["gpu_hbm_capacity_bytes_per_gpu"]
            for point in failed_gpu_timeline
        )
        repaired_accounts = hbm_stacks[failed_gpu_id]["final_accounts"]
        assert repaired_accounts["UNAVAILABLE_CAPACITY"] == 0
        assert (
            repaired_accounts["MODEL_WEIGHTS"]
            == DEFAULT_PARAMETERS.model_weights_bytes_per_gpu
        )
        assert (
            repaired_accounts["RUNTIME_FIXED"]
            == DEFAULT_PARAMETERS.runtime_fixed_bytes_per_gpu
        )
    assert first.payload["metrics"]["policy_effects"]["protection_path_bypasses"]
    failed_pools = [
        value
        for value in resource_cost["peer_hbm_by_gpu"].values()
        if value["failed_unavailable"]
    ]
    assert failed_pools == []
    for failure_event in first.representative["failure_events"]:
        repaired_pool = resource_cost["peer_hbm_by_gpu"][failure_event["target_gpu_id"]]
        assert repaired_pool["failed_unavailable"] is False
        assert repaired_pool["unavailable_bytes"] == 0
    assert all(item["status"] != "PENDING" for item in first.representative["transfers"])
    assert any(
        item["pending_peak_bytes"] > 0
        for item in resource_cost["peer_hbm_by_gpu"].values()
    )
    assert (
        resource_cost["store_dram_by_segment"]["store-0:segment-0"][
            "pending_peak_bytes"
        ]
        > 0
    )
    for transfer in first.representative["transfers"]:
        assert transfer["bytes"] == (
            transfer["transferred_bytes"] + transfer["aborted_bytes"]
        )
    assert any(
        transfer["flow_slice_count"] > 1
        for transfer in first.representative["transfers"]
    )
    remote_recovery = [
        transfer
        for transfer in first.representative["transfers"]
        if transfer["communication_backend"] == "flow_contention"
        and transfer["cause"].startswith("AEGIS_RECOVERY_")
    ]
    if remote_recovery:
        # Recovery DMA writes directly into the already charged
        # RECOVERY_RESERVED destination.  Charging an additional GPU staging
        # buffer here would double-count HBM; host-staged transports account
        # their scratch space in Host DRAM instead.
        assert resource_cost["gpu_hbm_staging_peak_bytes"] == 0
        destination_writes = [
            item
            for item in first.representative["recovery_events"]
            if item["event"] == "RECOVERY_RESERVED_DESTINATION_WRITE_START"
        ]
        assert destination_writes
        assert all(
            item["additional_hbm_charge_bytes"] == 0
            for item in destination_writes
        )

    rate_capacities = resource_model["rate_resources"]
    rates_by_interval_resource: dict[tuple[int, int, str], list[float]] = {}
    for interval in first.representative["flow_rate_intervals"]:
        for resource_id in interval["path_resource_ids"]:
            key = (interval["start_ns"], interval["end_ns"], resource_id)
            rates_by_interval_resource.setdefault(key, []).append(
                interval["allocated_rate_bytes_per_second"]
            )
    shared = [
        (key, rates)
        for key, rates in rates_by_interval_resource.items()
        if len(rates) > 1
    ]
    assert shared
    for (_, _, resource_id), rates in rates_by_interval_resource.items():
        assert sum(rates) <= rate_capacities[resource_id] + 1e-5
    assert any(
        abs(sum(rates) - rate_capacities[key[2]]) <= 1e-5
        for key, rates in shared
    )

    recovered = [
        item
        for item in first.span_details
        if item["recovery_ready_ns"] is not None
    ]
    assert recovered
    for item in recovered:
        assert (
            item["failure_at_ns"]
            <= item["prompt_recompute_start_ns"]
            <= item["prompt_recompute_complete_ns"]
            <= item["silent_replay_start_ns"]
            <= item["silent_replay_complete_ns"]
            == item["recovery_ready_ns"]
            <= item["resume_decode_start_ns"]
            <= item["completed_ns"]
        )
    events_by_span: dict[str, list[str]] = {}
    for event in first.representative["recovery_events"]:
        events_by_span.setdefault(str(event["span_id"]), []).append(str(event["event"]))
    for item in recovered:
        events = events_by_span[str(item["span_id"])]
        assert events[0] == "RECOVERY_PLAN"
        assert events[-5:] == [
            "PROMPT_SUFFIX_RECOMPUTE_START",
            "PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
            "SILENT_REPLAY_START",
            "SILENT_REPLAY_COMPLETE",
            "RECOVERY_ATOMIC_ACTIVATION",
        ]
        assert all(
            event == "RECOVERY_RESERVED_DESTINATION_WRITE_START"
            for event in events[1:-5]
        )


def test_no_failure_recompute_has_no_protection_or_failure() -> None:
    records = _committed_records()
    result = run_study_cell(
        records,
        CellSpec(
            variant=core_variants()[0],
            context_bucket="8k",
            scenario=Scenario.NO_FAILURE,
            seed=7,
            repetition="A",
        ),
    )
    metrics = result.payload["metrics"]
    assert result.payload["failure_schedule"] is None
    assert metrics["failure_impact"] == {
        "failure_event_count": 0,
        "active_requests": 0,
        "queued_requests": 0,
        "failed_gpu_count": 0,
    }
    assert metrics["resource_cost"]["peer_hbm_peak_bytes"] == 0
    assert metrics["resource_cost"]["store_dram_peak_bytes"] == 0
    assert result.payload["output_audit"]["duplicate_or_missing_tokens"] == 0


def test_dp8_128k_uses_same_logical_failure_trigger_across_core_systems() -> None:
    records = _committed_records()
    parameters = ModelParameters(dp_count=8)
    for seed in (0, 7):
        schedule = derive_failure_schedule(
            records,
            bucket="128k",
            seed=seed,
            parameters=parameters,
        )
        resolved_times: set[int] = set()
        for variant in core_variants(parameters):
            result = run_study_cell(
                records,
                CellSpec(
                    variant=variant,
                    context_bucket="128k",
                    scenario=Scenario.GPU_FAILURE,
                    seed=seed,
                    repetition="A",
                    failure_schedule=schedule,
                ),
            )
            failures = result.representative["failure_events"]
            assert len(failures) == 2
            for planned, failure in zip(schedule.events, failures, strict=True):
                trigger = failure["logical_trigger"]
                assert trigger["focus_span_id"] == planned.focus_span_id
                assert trigger["progress_per_mille"] == parameters.failure_progress_per_mille
                assert planned.focus_span_id in failure["impacted_active_span_ids"]
                resolved_times.add(int(trigger["resolved_at_ns"]))
        # Absolute time remains an outcome rather than a matching key. Fair
        # normal-HBM cache visibility can make it identical across systems;
        # matching is only on the frozen logical span/progress trigger.
        assert resolved_times


def test_failure_aborts_only_unserved_transfer_suffix_and_conserves_bytes() -> None:
    records = _committed_records()
    parameters = ModelParameters(
        peer_bandwidth_bytes_per_second=10_000_000,
        store_bandwidth_bytes_per_second=10_000_000,
        failure_progress_per_mille=500,
    )
    schedule = derive_failure_schedule(
        records,
        bucket="64k",
        seed=2,
        parameters=parameters,
    )
    result = run_study_cell(
        records,
        CellSpec(
            variant=core_variants(parameters)[-1],
            context_bucket="64k",
            scenario=Scenario.GPU_FAILURE,
            seed=2,
            repetition="A",
            failure_schedule=schedule,
        ),
    )
    aborted = [
        transfer
        for transfer in result.representative["transfers"]
        if transfer["status"] == "ABORTED"
    ]
    assert aborted
    assert sum(item["aborted_bytes"] for item in aborted) > 0
    for transfer in aborted:
        assert transfer["terminal_ns"] <= transfer["planned_end_ns"]
        assert transfer["bytes"] == (
            transfer["transferred_bytes"] + transfer["aborted_bytes"]
        )
        for interval in transfer["resource_intervals"]:
            assert interval["start_ns"] <= interval["actual_end_ns"]
            assert interval["actual_end_ns"] <= interval["planned_end_ns"]
    resource_cost = result.payload["metrics"]["resource_cost"]
    assert resource_cost["transfer_state_counts"]["ABORTED"] == len(aborted)
    assert resource_cost["transfer_byte_conservation_valid"] is True


def test_cache_aware_routing_combines_continuous_prefix_and_dp_queue_cost() -> None:
    records = _committed_records()
    enabled = run_study_cell(
        records,
        CellSpec(
            variant=core_variants()[-1],
            context_bucket="64k",
            scenario=Scenario.NO_FAILURE,
            seed=0,
            repetition="A",
        ),
    )
    changed = [
        event
        for event in enabled.representative["route_events"]
        if event["selected_gpu_id"] != event["hashed_gpu_id"]
    ]
    assert changed
    aimd_actions = enabled.payload["metrics"]["policy_effects"]["aimd_action_counts"]
    assert sum(aimd_actions.values()) == enabled.payload["metrics"]["policy_effects"][
        "aimd_decision_count"
    ]
    assert sum(aimd_actions.values()) > 0
    pressure_events = [
        event
        for event in enabled.representative["aimd_events"]
        if event["foreground_pressure"]
    ]
    assert all(event["foreground_shortfall_bytes"] > 0 for event in pressure_events)
    assert all(event["pressure_active_request_count"] > 0 for event in pressure_events)
    assert all(
        event["update_basis"]
        == (
            "IMMEDIATE_PRESSURE_EVENT"
            if event["foreground_pressure"]
            else "FIXED_GLOBAL_DES_CONTROL_WINDOW"
        )
        for event in enabled.representative["aimd_events"]
    )
    for event in changed:
        assert event["router_owner"] == "external_router"
        assert event["index_owner"] == "mooncake_conductor"
        selected = event["candidates"][event["selected_gpu_id"]]
        assert (
            selected["continuous_queued_tokens"],
            selected["estimated_completion_ns"],
        ) == min(
            (
                candidate["continuous_queued_tokens"],
                candidate["estimated_completion_ns"],
            )
            for candidate in event["candidates"].values()
        )
        assert selected["effective_prefix_tokens"] == max(
            selected["local_hbm_union_prefix_tokens"],
            selected["store_prefix_tokens"],
        )
        assert selected["local_hbm_union_prefix_tokens"] == (
            selected["normal_hbm_contribution_tokens"]
            + selected["peer_backup_contribution_tokens"]
        )
        if selected["cache_source"] == "PEER_HBM":
            assert selected["store_restore_bytes"] == 0
            assert selected["store_restore_ns"] == 0
    assert any(
        candidate["normal_hbm_prefix_tokens"] > 0
        for event in enabled.representative["route_events"]
        for candidate in event["candidates"].values()
    )
    assert any(
        candidate["peer_backup_prefix_tokens"] > 0
        for event in enabled.representative["route_events"]
        for candidate in event["candidates"].values()
    )
    load_over_cache = [
        event
        for event in enabled.representative["route_events"]
        if event["candidates"][event["selected_gpu_id"]]["effective_prefix_tokens"]
        < max(
            candidate["effective_prefix_tokens"]
            for candidate in event["candidates"].values()
        )
    ]
    assert load_over_cache

    disabled_variant = next(
        item for item in ablation_variants() if item.variant_id == "no_cache_aware_routing"
    )
    disabled = run_study_cell(
        records,
        CellSpec(
            variant=disabled_variant,
            context_bucket="64k",
            scenario=Scenario.NO_FAILURE,
            seed=0,
            repetition="A",
        ),
    )
    assert all(
        event["selected_gpu_id"] == event["hashed_gpu_id"]
        for event in disabled.representative["route_events"]
    )

    mooncake = run_study_cell(
        records,
        CellSpec(
            variant=core_variants()[1],
            context_bucket="64k",
            scenario=Scenario.NO_FAILURE,
            seed=0,
            repetition="A",
        ),
    )
    assert mooncake.payload["metrics"]["cache_reuse_tokens"]["normal_hbm"] > 0
    assert any(
        candidate["normal_hbm_prefix_tokens"] > 0
        for event in mooncake.representative["route_events"]
        for candidate in event["candidates"].values()
    )
    assert all(
        candidate["peer_backup_prefix_tokens"] == 0
        for event in mooncake.representative["route_events"]
        for candidate in event["candidates"].values()
    )


def test_two_manager_ablation_keeps_visibility_but_separates_value_bids() -> None:
    records = _committed_records()
    results = {}
    for variant_id in ("full", "two_managers"):
        variant = next(
            item for item in ablation_variants() if item.variant_id == variant_id
        )
        results[variant_id] = run_study_cell(
            records,
            CellSpec(
                variant=variant,
                context_bucket="64k",
                scenario=Scenario.NO_FAILURE,
                seed=0,
                repetition="A",
            ),
        )
    full_effects = results["full"].payload["metrics"]["policy_effects"]
    split_effects = results["two_managers"].payload["metrics"]["policy_effects"]
    assert full_effects["manager_mode"] == (
        "CURRENT_DESIGN_TIER_LOCAL_RECOVERY_HARM_ONLY"
    )
    assert (
        split_effects["manager_mode"]
        == "TWO_INDEPENDENT_VALUE_BIDS_SHARED_DIRECTORY"
    )
    assert all(split_effects["committed_reuse_visibility"].values())
    assert sum(results["two_managers"].payload["metrics"]["cache_reuse_tokens"].values()) > 0
    assert (
        results["full"].payload["variant_fingerprint"]
        != results["two_managers"].payload["variant_fingerprint"]
    )
