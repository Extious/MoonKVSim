from __future__ import annotations

import json
from dataclasses import replace

import pytest

from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.request import Request
from moonkvsim.integration.vllm.scheduler import ContinuousBatchScheduler, SchedulingPhase
from moonkvsim.predictor import (
    AICONFIGURATOR_PINNED_COMMIT,
    AICONFIGURATOR_PINNED_VERSION,
    AIConfiguratorForwardProvider,
    AIConfiguratorSupportManifest,
    AIConfiguratorUnavailableError,
    ForwardBoundary,
    PredictionBatch,
    PredictionPhase,
    PredictionProfile,
    PredictionRequest,
    VLLMBatchAdapterError,
    VLLMSchedulerBatchAdapter,
    probe_aiconfigurator,
)


def _profile() -> PredictionProfile:
    return PredictionProfile(
        provider_name="aiconfigurator",
        provider_version=AICONFIGURATOR_PINNED_VERSION,
        provider_source_revision=AICONFIGURATOR_PINNED_COMMIT,
        database_mode="unit-test-explicit-vllm",
        database_sha256="1" * 64,
        hardware_profile_id="unit-test-target-gpu",
        hardware_profile_fingerprint="2" * 64,
        model_id="unit-test/Qwen3",
        model_revision="unit-test-qwen3-revision",
        tensor_parallel_size=2,
        pipeline_parallel_size=1,
        forward_boundary=ForwardBoundary(
            includes_model_collectives=True,
            model_collective_scope="unit-test TP collective boundary",
        ),
    )


def _scheduler(*, token_budget: int = 8, threshold: int = 0) -> ContinuousBatchScheduler:
    return ContinuousBatchScheduler(
        block_pool=BlockPool(32, enable_caching=False),
        block_size_tokens=4,
        max_num_scheduled_tokens=token_budget,
        max_num_running_requests=8,
        long_prefill_token_threshold=threshold,
    )


def _request(request_id: str, prompt_tokens: int) -> Request:
    return Request(
        request_id=request_id,
        prompt_tokens=prompt_tokens,
        max_output_tokens=8,
        arrival_ns=0,
    )


def test_adapter_preserves_chunk_shape_and_one_token_prefill_phase() -> None:
    scheduler = _scheduler(token_budget=1, threshold=1)
    request = _request("one-token-prefill", 2)
    scheduler.add_request(request)

    output = scheduler.schedule()
    adapted = VLLMSchedulerBatchAdapter().adapt(
        output,
        requests={request.request_id: request},
        profile=_profile(),
    )

    prefill = adapted.batch_for_phase(PredictionPhase.PREFILL)
    assert prefill is not None
    assert prefill.request_ids == (request.request_id,)
    assert prefill.batch.shape.extend_lengths == (1,)
    assert prefill.batch.shape.past_kv_lengths == (0,)
    assert adapted.batch_for_phase(PredictionPhase.DECODE) is None
    assert adapted.has_forward
    assert not adapted.is_mixed_phase


def test_adapter_splits_mixed_continuous_batch_without_importing_kv_io() -> None:
    scheduler = _scheduler(token_budget=4)
    decode = _request("decode", 1)
    scheduler.add_request(decode)
    scheduler.schedule()
    scheduler.append_output_tokens(decode.request_id)
    prefill = _request("prefill", 3)
    scheduler.add_request(prefill)

    output = scheduler.schedule()
    adapted = VLLMSchedulerBatchAdapter().adapt(
        output,
        requests={decode.request_id: decode, prefill.request_id: prefill},
        profile=_profile(),
    )

    prefill_batch = adapted.batch_for_phase(PredictionPhase.PREFILL)
    decode_batch = adapted.batch_for_phase(PredictionPhase.DECODE)
    assert prefill_batch is not None and decode_batch is not None
    assert prefill_batch.request_ids == (prefill.request_id,)
    assert prefill_batch.batch.shape.extend_lengths == (3,)
    assert prefill_batch.batch.shape.past_kv_lengths == (0,)
    assert decode_batch.request_ids == (decode.request_id,)
    assert decode_batch.batch.shape.extend_lengths == (1,)
    assert decode_batch.batch.shape.past_kv_lengths == (1,)
    assert adapted.scheduled_request_ids == (decode.request_id, prefill.request_id)
    assert adapted.is_mixed_phase

    serialized = json.loads(adapted.to_json_bytes())
    assert serialized["boundary"] == "gpu_forward_shape_only"
    encoded = adapted.to_json_bytes()
    assert b"block_ids" not in encoded
    assert b"connector" not in encoded
    assert b"kv_d2d" not in encoded
    assert b"io_duration" not in encoded
    assert b"global_scale" not in encoded


def test_adapter_is_byte_deterministic_for_identical_scheduler_steps() -> None:
    def run_once() -> bytes:
        scheduler = _scheduler(token_budget=4, threshold=2)
        first = _request("a", 5)
        second = _request("b", 2)
        scheduler.add_request(first)
        scheduler.add_request(second)
        output = scheduler.schedule()
        return VLLMSchedulerBatchAdapter().adapt(
            output,
            requests={first.request_id: first, second.request_id: second},
            profile=_profile(),
        ).to_json_bytes()

    assert run_once() == run_once()


def test_adapter_uses_restored_prefix_as_prefill_past_kv_shape() -> None:
    scheduler = _scheduler(token_budget=8)
    request = _request("restored", 6)
    scheduler.restore_request_prefix(request, restored_tokens=4)

    output = scheduler.schedule()
    adapted = VLLMSchedulerBatchAdapter().adapt(
        output,
        requests={request.request_id: request},
        profile=_profile(),
    )

    prefill = adapted.batch_for_phase(PredictionPhase.PREFILL)
    assert prefill is not None
    assert prefill.batch.shape.extend_lengths == (2,)
    assert prefill.batch.shape.past_kv_lengths == (4,)


def test_adapter_rejects_multi_token_decode_outside_ordinary_path() -> None:
    scheduler = _scheduler(token_budget=8)
    request = _request("multi-decode", 1)
    scheduler.add_request(request)
    scheduler.schedule()
    scheduler.append_output_tokens(request.request_id, count=2)
    output = scheduler.schedule()
    scheduled = output.scheduled_running_reqs[0]
    corrupt = replace(
        scheduled,
        num_scheduled_tokens=2,
        num_computed_tokens_after=scheduled.num_computed_tokens_before + 2,
    )
    output = replace(
        output,
        scheduled_running_reqs=(corrupt,),
        num_scheduled_tokens={request.request_id: 2},
        total_num_scheduled_tokens=2,
        token_budget_remaining=6,
    )
    request.num_computed_tokens = corrupt.num_computed_tokens_after

    with pytest.raises(VLLMBatchAdapterError, match="one token per decode"):
        VLLMSchedulerBatchAdapter().adapt(
            output,
            requests={request.request_id: request},
            profile=_profile(),
        )


def test_adapter_rejects_stale_request_state_and_corrupt_source_phase() -> None:
    scheduler = _scheduler(token_budget=2, threshold=2)
    request = _request("stale", 4)
    scheduler.add_request(request)
    output = scheduler.schedule()
    scheduler.schedule()

    with pytest.raises(VLLMBatchAdapterError, match="stale or from another step"):
        VLLMSchedulerBatchAdapter().adapt(
            output,
            requests={request.request_id: request},
            profile=_profile(),
        )

    scheduler = _scheduler(token_budget=2)
    request = _request("wrong-phase", 2)
    scheduler.add_request(request)
    output = scheduler.schedule()
    item = output.scheduled_new_reqs[0]
    object.__setattr__(item, "phase", SchedulingPhase.DECODE)
    with pytest.raises(VLLMBatchAdapterError, match="source phase disagrees"):
        VLLMSchedulerBatchAdapter().adapt(
            output,
            requests={request.request_id: request},
            profile=_profile(),
        )


def test_adapter_rejects_missing_request_and_nonconserving_output() -> None:
    scheduler = _scheduler(token_budget=2)
    request = _request("missing", 2)
    scheduler.add_request(request)
    output = scheduler.schedule()

    with pytest.raises(VLLMBatchAdapterError, match="missing corresponding"):
        VLLMSchedulerBatchAdapter().adapt(output, requests={}, profile=_profile())

    corrupt = replace(output, total_num_scheduled_tokens=99)
    with pytest.raises(VLLMBatchAdapterError, match="does not conserve"):
        VLLMSchedulerBatchAdapter().adapt(
            corrupt,
            requests={request.request_id: request},
            profile=_profile(),
        )

    corrupt_item = replace(output.scheduled_new_reqs[0], num_scheduled_tokens=1)
    inconsistent = replace(output, scheduled_new_reqs=(corrupt_item,))
    with pytest.raises(VLLMBatchAdapterError, match="item count disagrees"):
        VLLMSchedulerBatchAdapter().adapt(
            inconsistent,
            requests={request.request_id: request},
            profile=_profile(),
        )


def _support(profile: PredictionProfile) -> AIConfiguratorSupportManifest:
    return AIConfiguratorSupportManifest(
        provider_version=profile.provider_version,
        provider_source_revision=profile.provider_source_revision,
        profile_fingerprint=profile.fingerprint,
        backend_name="vllm",
        database_mode=profile.database_mode,
        database_sha256=profile.database_sha256,
        hardware_profile_id=profile.hardware_profile_id,
        hardware_profile_fingerprint=profile.hardware_profile_fingerprint,
        model_id=profile.model_id,
        model_revision=profile.model_revision,
        tensor_parallel_size=profile.tensor_parallel_size,
        pipeline_parallel_size=profile.pipeline_parallel_size,
        supported_phases=(PredictionPhase.PREFILL, PredictionPhase.DECODE),
    )


class _PhaseBackend:
    def __init__(self) -> None:
        self.prefill_calls: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
        self.decode_calls: list[tuple[int, ...]] = []

    def predict_prefill_forward_ms(
        self,
        *,
        extend_lengths: tuple[int, ...],
        past_kv_lengths: tuple[int, ...],
    ) -> float:
        self.prefill_calls.append((extend_lengths, past_kv_lengths))
        return 1.25

    def predict_decode_forward_ms(
        self,
        *,
        past_kv_lengths: tuple[int, ...],
    ) -> float:
        self.decode_calls.append(past_kv_lengths)
        return 0.5


def test_aiconfigurator_probe_fails_closed_without_package_and_support() -> None:
    availability = probe_aiconfigurator(
        _profile(),
        support=None,
        installed_version=None,
    )

    assert not availability.available
    assert {item.code for item in availability.diagnostics} == {
        "package_unavailable",
        "support_manifest_unavailable",
    }
    with pytest.raises(AIConfiguratorUnavailableError, match="package_unavailable"):
        availability.require_available()


def test_explicit_aiconfigurator_provider_forwards_exact_phase_shapes_only() -> None:
    profile = _profile()
    backend = _PhaseBackend()
    provider = AIConfiguratorForwardProvider(
        profile=profile,
        support=_support(profile),
        backend=backend,
        installed_version=AICONFIGURATOR_PINNED_VERSION,
    )
    prefill = PredictionBatch.for_profile(
        requests=(
            # A one-token prefill remains explicitly prefill.
            PredictionRequest(extend_length=1, past_kv_length=7),
        ),
        phase=PredictionPhase.PREFILL,
        profile=profile,
    )
    decode = PredictionBatch.for_profile(
        requests=(
            PredictionRequest(extend_length=1, past_kv_length=8),
        ),
        phase=PredictionPhase.DECODE,
        profile=profile,
    )

    assert provider.predict_forward_duration_ns(prefill) == 1_250_000
    assert provider.predict_forward_duration_ns(decode) == 500_000
    assert backend.prefill_calls == [((1,), (7,))]
    assert backend.decode_calls == [(8,)]


def test_aiconfigurator_provider_rejects_profile_or_phase_coverage_mismatch() -> None:
    profile = _profile()
    incomplete = replace(
        _support(profile),
        supported_phases=(PredictionPhase.PREFILL,),
    )
    with pytest.raises(AIConfiguratorUnavailableError, match="phase_coverage_incomplete"):
        AIConfiguratorForwardProvider(
            profile=profile,
            support=incomplete,
            backend=_PhaseBackend(),
            installed_version=AICONFIGURATOR_PINNED_VERSION,
        )

    wrong_hardware = replace(_support(profile), hardware_profile_id="different-gpu")
    with pytest.raises(AIConfiguratorUnavailableError, match="hardware_profile_id"):
        AIConfiguratorForwardProvider(
            profile=profile,
            support=wrong_hardware,
            backend=_PhaseBackend(),
            installed_version=AICONFIGURATOR_PINNED_VERSION,
        )
