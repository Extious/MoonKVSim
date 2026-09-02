from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import pytest

from moonkvsim.aegiskv.scheduler_step_bridge import (
    AegisSchedulerStepBridge,
    SchedulerExecutionBinding,
    SchedulerStepBridgeFencedError,
    SchedulerStepPreparationError,
    StepDurationEvidenceClass,
    StepDurationProviderEvidence,
)
from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.hbm_block_ledger import (
    HBM_KV_ACTIVE_ACCOUNT,
    HbmBlockLedgerBridge,
    HbmStageRankBinding,
)
from moonkvsim.integration.vllm.kv_layout import StageBlockLayout
from moonkvsim.integration.vllm.request import Request, RequestStatus
from moonkvsim.integration.vllm.scheduler import ContinuousBatchScheduler
from moonkvsim.predictor.schema import ForwardBoundary, PredictionProfile
from moonkvsim.predictor.vllm_adapter import AdaptedSchedulerStep
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _profile() -> PredictionProfile:
    return PredictionProfile(
        provider_name="fixture-whole-step-provider",
        provider_version="test-v1",
        provider_source_revision="1" * 40,
        database_mode="fixture-only-no-performance-database",
        database_sha256=_sha256(b"fixture-database-absent"),
        hardware_profile_id="fixture-a100-shape",
        hardware_profile_fingerprint=_sha256(b"fixture-a100-shape"),
        model_id="Qwen/Qwen3-8B",
        model_revision="b968826d9c46dd6066d109eabc6255188de91218",
        tensor_parallel_size=1,
        pipeline_parallel_size=1,
        forward_boundary=ForwardBoundary(includes_model_collectives=False),
    )


@dataclass(slots=True)
class _FixtureDurationProvider:
    profile: PredictionProfile
    fail: bool = False
    calls: list[AdaptedSchedulerStep] = field(default_factory=list)

    @property
    def evidence(self) -> StepDurationProviderEvidence:
        return StepDurationProviderEvidence(
            provider_name="fixture-whole-step-provider",
            provider_version="test-v1",
            prediction_profile_fingerprint=self.profile.fingerprint,
            provenance_sha256=_sha256(b"fixture-duration-provider-code-and-inputs"),
            evidence_class=StepDurationEvidenceClass.FIXTURE_ONLY,
            physically_measured=False,
            formal_use_allowed=False,
        )

    def predict_step_duration_ns(self, step: AdaptedSchedulerStep) -> int:
        self.calls.append(step)
        if self.fail:
            raise RuntimeError("fixture provider failure")
        # This value is deliberately fixture-only.  Tests inspect shape
        # propagation, not timing accuracy.
        return 1_000 + sum(
            phase_batch.batch.shape.total_extend_length
            for phase_batch in step.phase_batches
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


@dataclass(slots=True)
class _Scenario:
    bridge: AegisSchedulerStepBridge
    provider: _FixtureDurationProvider
    hbm: HbmBlockLedgerBridge
    ledger: CapacityLedger


def _scenario(
    *,
    max_running: int = 3,
    token_budget: int = 8,
    provider_fails: bool = False,
) -> _Scenario:
    profile = _profile()
    journal = EventJournal()
    registry = AllocationRegistry(journal=journal)
    ledger = CapacityLedger(
        resource_id="gpu-0.hbm",
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=64 * 16,
    )
    hbm = HbmBlockLedgerBridge(
        bridge_id="fixture-hbm-dp0",
        bindings=(HbmStageRankBinding("gpu-0.hbm", _layout()),),
        ledgers={"gpu-0.hbm": ledger},
        registry=registry,
        journal=journal,
        now_ns=lambda: 7,
    )
    scheduler = ContinuousBatchScheduler(
        block_pool=BlockPool(17, enable_caching=False),
        block_size_tokens=4,
        max_num_scheduled_tokens=token_budget,
        max_num_running_requests=max_running,
        block_lifecycle_observer=hbm,
    )
    provider = _FixtureDurationProvider(profile, fail=provider_fails)
    bridge = AegisSchedulerStepBridge(
        bridge_id="aegis-dp0",
        execution_binding=SchedulerExecutionBinding(
            target_id="dp-0",
            gpu_id="gpu-0",
            failure_domain_id="host-0/gpu-0",
            kv_abi="vllm-v1-ordinary-full-attention",
            kv_layout_id="fixture-qwen3-8b-tp1-pp1",
            kv_layout_sha256=_sha256(b"fixture-qwen3-8b-tp1-pp1"),
        ),
        scheduler=scheduler,
        prediction_profile=profile,
        duration_provider=provider,
    )
    return _Scenario(bridge, provider, hbm, ledger)


def _request(request_id: str, *, output_tokens: int = 2) -> Request:
    return Request(
        request_id=request_id,
        prompt_tokens=4,
        max_output_tokens=output_tokens,
        arrival_ns=0,
    )


def test_shared_forward_exports_participants_shapes_duration_and_residency() -> None:
    scenario = _scenario(max_running=2, token_budget=8)
    scenario.bridge.admit_request(_request("r0"))
    scenario.bridge.admit_request(_request("r1"))

    step = scenario.bridge.start_step()

    assert [item.request_id for item in step.participants] == ["r0", "r1"]
    assert {item.phase.value for item in step.participants} == {"PREFILL"}
    assert all(item.produces_output and item.output_index == 0 for item in step.participants)
    assert len(step.phase_shapes) == 1
    [shape] = step.phase_shapes
    assert shape.phase.value == "prefill"
    assert shape.request_ids == ("r0", "r1")
    assert shape.shape.batch_size == 2
    assert shape.shape.total_extend_length == 8
    assert step.duration is not None
    assert step.duration.duration_ns == 1_008
    assert step.duration.evidence.evidence_class is StepDurationEvidenceClass.FIXTURE_ONLY
    assert step.duration.evidence.physically_measured is False
    assert step.duration.evidence.formal_use_allowed is False
    assert step.residency_before.resident_primary_bytes == 0
    assert step.residency_after_schedule.resident_primary_request_count == 2
    assert step.residency_after_schedule.resident_primary_bytes == 128
    assert scenario.ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 128

    completion = scenario.bridge.complete_step(step.step_id)

    assert completion.output_positions == (("r0", 1), ("r1", 1))
    assert completion.terminal_output_request_ids == ()
    assert completion.residency_after_completion.resident_primary_bytes == 128
    assert len(scenario.provider.calls) == 1


def test_restored_prefix_waits_for_ordinary_page_admission() -> None:
    scenario = _scenario(max_running=2, token_budget=48)
    occupying = Request(
        request_id="occupying",
        prompt_tokens=48,
        max_output_tokens=2,
        arrival_ns=0,
    )
    scenario.bridge.admit_request(occupying)
    first = scenario.bridge.start_step()
    scenario.bridge.complete_step(first.step_id)

    restored = Request(
        request_id="restored",
        prompt_tokens=32,
        max_output_tokens=1,
        arrival_ns=0,
    )
    scenario.bridge.admit_restored_request(restored, restored_tokens=32)

    assert restored.status is RequestStatus.WAITING_FOR_REMOTE_KVS
    assert scenario.bridge.scheduler.request_block_ids("restored") == ()
    assert scenario.bridge.scheduler.running_request_ids == ("occupying",)
    assert scenario.bridge.scheduler.waiting_request_ids == ("restored",)

    # The next step continues the older resident request.  The restored
    # request remains capacity-safe instead of forcing an all-prefix failure.
    second = scenario.bridge.start_step()
    assert [item.request_id for item in second.participants] == ["occupying"]


def test_mixed_prefill_decode_step_keeps_one_shape_per_phase() -> None:
    scenario = _scenario(max_running=3, token_budget=8)
    scenario.bridge.admit_request(_request("decode"))
    first = scenario.bridge.start_step()
    scenario.bridge.complete_step(first.step_id)
    scenario.bridge.admit_request(_request("prefill"))

    mixed = scenario.bridge.start_step()

    assert mixed.is_mixed_phase
    assert [shape.phase.value for shape in mixed.phase_shapes] == ["prefill", "decode"]
    shapes = {shape.phase.value: shape for shape in mixed.phase_shapes}
    assert shapes["prefill"].request_ids == ("prefill",)
    assert shapes["prefill"].shape.total_extend_length == 4
    assert shapes["decode"].request_ids == ("decode",)
    assert shapes["decode"].shape.total_extend_length == 1
    participants = {item.request_id: item for item in mixed.participants}
    assert participants["decode"].phase.value == "DECODE"
    assert participants["prefill"].phase.value == "PREFILL"
    assert all(item.produces_output for item in participants.values())

    completion = scenario.bridge.complete_step(mixed.step_id)

    assert completion.terminal_output_request_ids == ("decode",)
    assert dict(completion.output_positions) == {"decode": 2, "prefill": 1}
    after_decode_retire = scenario.bridge.retire_request("decode")
    assert after_decode_retire.request_ids == ("prefill",)
    assert after_decode_retire.resident_primary_bytes == 64


def test_gpu_failure_fence_preserves_rollback_and_pre_loss_residency() -> None:
    scenario = _scenario(max_running=2, token_budget=8)
    for request_id in ("active-0", "active-1", "waiting"):
        scenario.bridge.admit_request(_request(request_id))
    step = scenario.bridge.start_step()

    snapshot = scenario.bridge.fence_for_gpu_failure(
        observed_at_ns=123,
        reason="GPU_FAILURE:gpu-0",
    )

    assert snapshot.active_step_id == step.step_id
    assert snapshot.execution_binding.target_id == "dp-0"
    assert snapshot.execution_binding.failure_domain_id == "host-0/gpu-0"
    assert snapshot.prediction_profile.model_id == "Qwen/Qwen3-8B"
    assert snapshot.running_request_ids == ("active-0", "active-1")
    assert snapshot.waiting_request_ids == ("waiting",)
    assert snapshot.residency_before_physical_loss.resident_primary_bytes == 128
    assert snapshot.physical_hbm_failure_applied is False
    by_id = {item.request_id: item for item in snapshot.requests}
    for request_id in ("active-0", "active-1"):
        item = by_id[request_id]
        assert item.observed_num_computed_tokens == 4
        assert item.last_completed_model_tokens == 0
        assert item.requeue_num_computed_tokens is None
        assert item.recovery_prefix_selection_required
        assert item.committed_output_tokens == 0
        assert item.in_flight_step_id == step.step_id
        assert item.in_flight_would_produce_output
        assert len(item.lost_resident_block_ids) == 1
    waiting = by_id["waiting"]
    assert waiting.queue_kind == "WAITING"
    assert waiting.observed_num_computed_tokens == 0
    assert waiting.last_completed_model_tokens == 0
    assert waiting.requeue_num_computed_tokens == 0
    assert waiting.recovery_prefix_selection_required is False
    assert waiting.in_flight_step_id is None
    # A control-plane fence does not fake the separately-owned physical fail-stop.
    assert scenario.ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 128
    with pytest.raises(SchedulerStepBridgeFencedError):
        scenario.bridge.complete_step(step.step_id)
    with pytest.raises(SchedulerStepBridgeFencedError):
        scenario.bridge.start_step()
    with pytest.raises(SchedulerStepBridgeFencedError):
        scenario.bridge.admit_request(_request("stale-admission"))


def test_duration_evidence_cannot_label_uncalibrated_input_as_measured_or_formal() -> None:
    profile_fingerprint = _sha256(b"profile")
    provenance = _sha256(b"provenance")
    with pytest.raises(ValueError, match="physically_measured"):
        StepDurationProviderEvidence(
            provider_name="bad",
            provider_version="v1",
            prediction_profile_fingerprint=profile_fingerprint,
            provenance_sha256=provenance,
            evidence_class=StepDurationEvidenceClass.UNCALIBRATED_MODEL,
            physically_measured=True,
            formal_use_allowed=False,
        )
    with pytest.raises(ValueError, match="formal use"):
        StepDurationProviderEvidence(
            provider_name="bad",
            provider_version="v1",
            prediction_profile_fingerprint=profile_fingerprint,
            provenance_sha256=provenance,
            evidence_class=StepDurationEvidenceClass.UNCALIBRATED_MODEL,
            physically_measured=False,
            formal_use_allowed=True,
        )


def test_provider_failure_fences_mutated_step_and_leaves_failure_snapshot_available() -> None:
    scenario = _scenario(provider_fails=True)
    scenario.bridge.admit_request(_request("r0"))

    with pytest.raises(SchedulerStepPreparationError, match="bridge fenced"):
        scenario.bridge.start_step()

    assert scenario.bridge.fenced
    snapshot = scenario.bridge.failure_state_snapshot(
        observed_at_ns=9,
        reason="STEP_PREPARATION_FAILURE_HANDOFF",
    )
    assert snapshot.active_step_id == "aegis-dp0:scheduler-step:00000001"
    [request] = snapshot.requests
    assert request.observed_num_computed_tokens == 4
    assert request.last_completed_model_tokens == 0
    assert request.requeue_num_computed_tokens is None
    assert request.recovery_prefix_selection_required
    assert request.in_flight_would_produce_output
    with pytest.raises(SchedulerStepBridgeFencedError):
        scenario.bridge.start_step()
