from __future__ import annotations

from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.request import Request
from moonkvsim.integration.vllm.scheduler import ContinuousBatchScheduler
from moonkvsim.predictor import (
    AICONFIGURATOR_PINNED_COMMIT,
    AICONFIGURATOR_PINNED_VERSION,
    ForwardBoundary,
    PredictionPhase,
    PredictionProfile,
    VLLMSchedulerBatchAdapter,
)


def _profile() -> PredictionProfile:
    return PredictionProfile(
        provider_name="aiconfigurator",
        provider_version=AICONFIGURATOR_PINNED_VERSION,
        provider_source_revision=AICONFIGURATOR_PINNED_COMMIT,
        database_mode="e2-toy-shape-only",
        database_sha256="a" * 64,
        hardware_profile_id="e2-toy-unavailable-hardware",
        hardware_profile_fingerprint="b" * 64,
        model_id="Qwen/Qwen3-8B",
        model_revision="e2-toy-not-a-calibration",
        tensor_parallel_size=1,
        pipeline_parallel_size=1,
        forward_boundary=ForwardBoundary(includes_model_collectives=False),
    )


def _run_adapter_sequence() -> tuple[bytes, bytes, bytes]:
    scheduler = ContinuousBatchScheduler(
        block_pool=BlockPool(64, enable_caching=False),
        block_size_tokens=4,
        max_num_scheduled_tokens=4,
        max_num_running_requests=8,
        long_prefill_token_threshold=3,
    )
    first = Request("first", prompt_tokens=5, max_output_tokens=2, arrival_ns=0)
    second = Request("second", prompt_tokens=5, max_output_tokens=2, arrival_ns=0)
    scheduler.add_request(first)
    scheduler.add_request(second)
    adapter = VLLMSchedulerBatchAdapter()
    profile = _profile()

    step1 = scheduler.schedule()
    adapted1 = adapter.adapt(
        step1,
        requests={first.request_id: first, second.request_id: second},
        profile=profile,
    )
    step2 = scheduler.schedule()
    adapted2 = adapter.adapt(
        step2,
        requests={first.request_id: first, second.request_id: second},
        profile=profile,
    )
    scheduler.append_output_tokens(first.request_id)
    step3 = scheduler.schedule()
    adapted3 = adapter.adapt(
        step3,
        requests={first.request_id: first, second.request_id: second},
        profile=profile,
    )

    prefill1 = adapted1.batch_for_phase(PredictionPhase.PREFILL)
    prefill2 = adapted2.batch_for_phase(PredictionPhase.PREFILL)
    prefill3 = adapted3.batch_for_phase(PredictionPhase.PREFILL)
    decode3 = adapted3.batch_for_phase(PredictionPhase.DECODE)
    assert prefill1 is not None and prefill1.batch.shape.extend_lengths == (3, 1)
    assert prefill1.batch.shape.past_kv_lengths == (0, 0)
    assert prefill2 is not None and prefill2.batch.shape.extend_lengths == (2, 2)
    assert prefill2.batch.shape.past_kv_lengths == (3, 1)
    assert prefill3 is not None and prefill3.batch.shape.extend_lengths == (2,)
    assert prefill3.batch.shape.past_kv_lengths == (3,)
    assert decode3 is not None and decode3.batch.shape.extend_lengths == (1,)
    assert decode3.batch.shape.past_kv_lengths == (5,)
    assert adapted3.is_mixed_phase
    return adapted1.to_json_bytes(), adapted2.to_json_bytes(), adapted3.to_json_bytes()


def test_scheduler_to_prediction_batches_are_deterministic_across_toy_replays() -> None:
    assert _run_adapter_sequence() == _run_adapter_sequence()
