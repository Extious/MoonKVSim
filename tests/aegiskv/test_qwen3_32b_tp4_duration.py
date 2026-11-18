from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from moonkvsim.aegiskv.qwen3_32b_tp4_config import (
    MODELED_MODEL_SAFETENSORS_TOTAL_BYTES,
    load_qwen3_32b_tp4_engine_config,
)
from moonkvsim.aegiskv.qwen3_32b_tp4_duration import (
    ALLOWED_CLAIM,
    DATABASE_MODE,
    MAX_CONTEXT_TOKENS,
    MODEL_ID,
    MODEL_REVISION,
    MODEL_SAFETENSORS_TOTAL_BYTES,
    NATIVE_MAX_CONTEXT_TOKENS,
    PROVIDER_NAME,
    PROVIDER_VERSION,
    TIMING_AND_BANDWIDTH,
    Qwen3TP4AnalyticalParameters,
    Qwen3TP4SchedulerStepDurationProvider,
    build_qwen3_32b_tp4_prediction_profile,
)
from moonkvsim.aegiskv.scheduler_step_bridge import (
    SchedulerStepDurationProvider,
    StepDurationEvidenceClass,
)
from moonkvsim.common.hash import sha256_json
from moonkvsim.predictor.schema import PredictionBatch, PredictionPhase, PredictionRequest
from moonkvsim.predictor.vllm_adapter import AdaptedPhaseBatch, AdaptedSchedulerStep

ROOT = Path(__file__).resolve().parents[2]


def _profile(source_revision: str = "1" * 40):
    return build_qwen3_32b_tp4_prediction_profile(provider_source_revision=source_revision)


def _phase(
    *,
    profile=None,
    phase: PredictionPhase,
    request_ids: tuple[str, ...],
    extend_lengths: tuple[int, ...],
    past_kv_lengths: tuple[int, ...],
) -> AdaptedPhaseBatch:
    resolved_profile = profile or _profile()
    return AdaptedPhaseBatch(
        request_ids=request_ids,
        batch=PredictionBatch.for_profile(
            requests=tuple(
                PredictionRequest(extend_length=extend, past_kv_length=past)
                for extend, past in zip(extend_lengths, past_kv_lengths, strict=True)
            ),
            phase=phase,
            profile=resolved_profile,
        ),
    )


def _step(*phases: AdaptedPhaseBatch) -> AdaptedSchedulerStep:
    return AdaptedSchedulerStep(
        scheduled_request_ids=tuple(
            request_id for phase in phases for request_id in phase.request_ids
        ),
        phase_batches=phases,
        scheduler_output_fingerprint=sha256_json(
            {"phase_batch_fingerprints": [phase.batch.fingerprint for phase in phases]}
        ),
    )


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def test_exact_qwen3_32b_tp4_architecture_and_analytical_sources_are_fingerprinted() -> None:
    parameters = Qwen3TP4AnalyticalParameters()

    assert parameters.hidden_size == 5_120
    assert parameters.intermediate_size == 25_600
    assert parameters.num_hidden_layers == 64
    assert parameters.num_attention_heads == 64
    assert parameters.num_kv_heads == 8
    assert parameters.head_dim == 128
    assert parameters.query_hidden_size == 8_192
    assert parameters.kv_hidden_size == 1_024
    assert parameters.native_max_context_tokens == NATIVE_MAX_CONTEXT_TOKENS == 40_960
    assert parameters.max_context_tokens == MAX_CONTEXT_TOKENS == 131_072
    assert parameters.tensor_parallel_size == 4
    assert parameters.pipeline_parallel_size == 1
    assert parameters.dense_bf16_flops_per_second_per_gpu == 312_000_000_000_000
    assert parameters.hbm_bandwidth_bytes_per_second_per_gpu == 2_039_000_000_000
    assert parameters.model_safetensors_total_bytes == MODEL_SAFETENSORS_TOTAL_BYTES
    assert parameters.model_weights_bytes_per_rank == 16_381_061_632
    assert parameters.analytical_main_matrix_weight_bytes_per_rank == 15_991_767_040
    assert parameters.non_main_matrix_weight_bytes_per_rank == 389_294_592
    assert parameters.shared_weight_bytes_per_rank == 16_381_061_632
    assert len(parameters.model_fingerprint) == 64
    assert len(parameters.hardware_fingerprint) == 64
    assert len(parameters.database_sha256) == 64

    profile = _profile()
    assert profile.model_id == MODEL_ID
    assert profile.model_revision == MODEL_REVISION
    assert profile.tensor_parallel_size == 4
    assert profile.pipeline_parallel_size == 1
    assert profile.database_mode == DATABASE_MODE
    assert "proposed-yarn-128k-runtime-validation-pending" in profile.database_mode
    assert profile.database_sha256 == parameters.database_sha256
    assert profile.hardware_profile_fingerprint == parameters.hardware_fingerprint
    assert profile.forward_boundary.includes_model_collectives


def test_duration_context_and_weight_bytes_match_the_strict_engine_contract() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)
    parameters = Qwen3TP4AnalyticalParameters()

    assert parameters.native_max_context_tokens == config.model.native_max_context_tokens
    assert parameters.max_context_tokens == config.model.max_context_tokens
    assert parameters.model_safetensors_total_bytes == (MODELED_MODEL_SAFETENSORS_TOTAL_BYTES)
    assert parameters.model_weights_bytes_per_rank == (
        config.capacity.rank_hbm.model_weights_bytes_per_rank
    )


def test_provider_exports_complete_modeled_uncalibrated_provenance_and_evidence() -> None:
    provider = Qwen3TP4SchedulerStepDurationProvider(prediction_profile=_profile())

    assert isinstance(provider, SchedulerStepDurationProvider)
    evidence = provider.evidence
    assert evidence.provider_name == PROVIDER_NAME
    assert evidence.provider_version == PROVIDER_VERSION
    assert evidence.evidence_class is StepDurationEvidenceClass.UNCALIBRATED_MODEL
    assert evidence.physically_measured is False
    assert evidence.formal_use_allowed is False
    assert evidence.provenance_sha256 == provider.provenance_fingerprint
    provenance = provider.provenance
    assert provenance["timing_and_bandwidth"] == TIMING_AND_BANDWIDTH
    assert provenance["calibrated"] is False
    assert provenance["physical_measurement_completed"] is False
    assert provenance["formal_use_allowed"] is False
    assert provenance["allowed_claim"] == ALLOWED_CLAIM
    model = provenance["model"]
    assert isinstance(model, dict)
    assert model["native_max_context_tokens"] == 40_960
    assert model["max_context_tokens"] == 131_072
    assert model["context_extension_provenance"] == (
        "proposed_yarn_128k_modeled_not_runtime_validated"
    )
    assert model["kv_layout_status"] == ("proposed_yarn_128k_modeled_runtime_validation_pending")
    assert model["model_safetensors_total_bytes"] == 65_524_246_528
    assert model["model_weights_bytes_per_rank"] == 16_381_061_632
    assert provenance["fingerprint"] == sha256_json(
        {key: value for key, value in provenance.items() if key != "fingerprint"}
    )
    serialized = json.dumps(provenance, sort_keys=True)
    assert "observed_ideal_duration" not in serialized
    assert "Qwen3-8B" not in serialized
    assert "no_empirical_scale_or_shape_factor" in serialized
    assert provider.prediction_profile.fingerprint in serialized


def test_prefill_cost_uses_exact_tokens_context_model_layers_memory_and_tp4_collectives() -> None:
    profile = _profile()
    provider = Qwen3TP4SchedulerStepDurationProvider(prediction_profile=profile)
    step = _step(
        _phase(
            profile=profile,
            phase=PredictionPhase.PREFILL,
            request_ids=("prefill",),
            extend_lengths=(4,),
            past_kv_lengths=(2,),
        )
    )

    result = provider.predict_step(step)
    [phase] = result.phases
    parameters = provider.parameters
    expected_attention_pairs = 4 * 2 + 4 * 5 // 2
    expected_matmul_flops = _ceil_div(
        2 * parameters.num_hidden_layers * 4 * parameters.transformer_matrix_parameters_per_layer,
        4,
    )
    expected_attention_flops = _ceil_div(
        4
        * parameters.num_hidden_layers
        * expected_attention_pairs
        * parameters.num_attention_heads
        * parameters.head_dim,
        4,
    )

    assert phase.phase is PredictionPhase.PREFILL
    assert phase.total_extend_tokens == 4
    assert phase.attention_pairs == expected_attention_pairs == 18
    assert phase.transformer_matmul_flops_per_rank == expected_matmul_flops
    assert phase.attention_flops_per_rank == expected_attention_flops
    assert phase.kv_read_bytes_per_rank == 64 * 18 * 2 * 256 * 2
    assert phase.kv_write_bytes_per_rank == 64 * 4 * 2 * 256 * 2
    assert result.shared_weight_bytes_per_rank == 16_381_061_632
    assert result.shared_weight_bytes_per_rank == parameters.model_weights_bytes_per_rank
    assert result.shared_weight_bytes_per_rank > (
        parameters.analytical_main_matrix_weight_bytes_per_rank
    )
    assert result.total_hbm_bytes_per_rank == (
        parameters.shared_weight_bytes_per_rank + phase.dynamic_hbm_bytes_per_rank
    )
    assert result.compute_ns == _ceil_div(
        result.total_compute_flops_per_rank * 1_000_000_000,
        parameters.dense_bf16_flops_per_second_per_gpu,
    )
    assert result.hbm_ns == _ceil_div(
        result.total_hbm_bytes_per_rank * 1_000_000_000,
        parameters.hbm_bandwidth_bytes_per_second_per_gpu,
    )
    assert result.roofline_ns == max(result.compute_ns, result.hbm_ns)
    assert result.collective_payload_bytes_per_rank == 4 * 5_120 * 2
    assert result.ring_collective_bytes_per_rank_per_all_reduce == 61_440
    assert result.collective_count == 64 * 2
    assert result.duration_ns == result.roofline_ns + result.collective_ns
    assert provider.predict_step_duration_ns(step) == result.duration_ns


def test_decode_attention_cost_uses_each_request_past_kv_length() -> None:
    profile = _profile()
    provider = Qwen3TP4SchedulerStepDurationProvider(prediction_profile=profile)
    short = _step(
        _phase(
            profile=profile,
            phase=PredictionPhase.DECODE,
            request_ids=("decode",),
            extend_lengths=(1,),
            past_kv_lengths=(127,),
        )
    )
    long = _step(
        _phase(
            profile=profile,
            phase=PredictionPhase.DECODE,
            request_ids=("decode",),
            extend_lengths=(1,),
            past_kv_lengths=(4_095,),
        )
    )

    short_result = provider.predict_step(short)
    long_result = provider.predict_step(long)
    assert short_result.phases[0].attention_pairs == 128
    assert long_result.phases[0].attention_pairs == 4_096
    assert long_result.phases[0].attention_flops_per_rank > (
        short_result.phases[0].attention_flops_per_rank
    )
    assert long_result.phases[0].kv_read_bytes_per_rank > (
        short_result.phases[0].kv_read_bytes_per_rank
    )
    assert long_result.duration_ns > short_result.duration_ns


def test_mixed_phase_step_composes_raw_costs_without_duplicate_weight_scan() -> None:
    profile = _profile()
    provider = Qwen3TP4SchedulerStepDurationProvider(prediction_profile=profile)
    prefill = _phase(
        profile=profile,
        phase=PredictionPhase.PREFILL,
        request_ids=("p0", "p1"),
        extend_lengths=(3, 2),
        past_kv_lengths=(0, 5),
    )
    decode = _phase(
        profile=profile,
        phase=PredictionPhase.DECODE,
        request_ids=("d0", "d1"),
        extend_lengths=(1, 1),
        past_kv_lengths=(10, 20),
    )

    result = provider.predict_step(_step(prefill, decode))

    assert tuple(phase.phase for phase in result.phases) == (
        PredictionPhase.PREFILL,
        PredictionPhase.DECODE,
    )
    assert result.phases[0].attention_pairs == 19
    assert result.phases[1].attention_pairs == 32
    assert result.collective_payload_bytes_per_rank == 7 * 5_120 * 2
    assert result.shared_weight_bytes_per_rank == provider.parameters.shared_weight_bytes_per_rank
    assert result.total_hbm_bytes_per_rank == (
        provider.parameters.shared_weight_bytes_per_rank
        + sum(phase.dynamic_hbm_bytes_per_rank for phase in result.phases)
    )
    assert result.total_compute_flops_per_rank == sum(
        phase.total_compute_flops_per_rank for phase in result.phases
    )


def test_prediction_and_all_fingerprints_are_process_independent() -> None:
    profile = _profile()
    provider = Qwen3TP4SchedulerStepDurationProvider(prediction_profile=profile)
    step = _step(
        _phase(
            profile=profile,
            phase=PredictionPhase.DECODE,
            request_ids=("r0", "r1"),
            extend_lengths=(1, 1),
            past_kv_lengths=(100, 200),
        )
    )

    first = provider.predict_step(step)
    second = provider.predict_step(step)
    assert first == second
    assert first.fingerprint == second.fingerprint
    assert first.to_dict()["fingerprint"] == first.fingerprint
    assert first.provenance_fingerprint == provider.evidence.provenance_sha256
    assert all(phase.to_dict()["fingerprint"] == phase.fingerprint for phase in first.phases)

    other_provider = Qwen3TP4SchedulerStepDurationProvider(prediction_profile=_profile("2" * 40))
    other_step = _step(
        _phase(
            profile=other_provider.prediction_profile,
            phase=PredictionPhase.DECODE,
            request_ids=("r0", "r1"),
            extend_lengths=(1, 1),
            past_kv_lengths=(100, 200),
        )
    )
    other = other_provider.predict_step(other_step)
    assert other.duration_ns == first.duration_ns
    assert other.provenance_fingerprint != first.provenance_fingerprint
    assert other.fingerprint != first.fingerprint


def test_isolated_duration_chunks_86214_prompt_tokens_without_truncation() -> None:
    provider = Qwen3TP4SchedulerStepDurationProvider(prediction_profile=_profile())

    result = provider.predict_isolated_request(
        prompt_tokens=86_214,
        output_tokens=3,
        max_num_scheduled_tokens=4_096,
    )

    assert result.covered_prompt_tokens == result.prompt_tokens == 86_214
    assert result.prefill_step_count == 22
    assert result.decode_step_count == 2
    assert len(result.steps) == 24
    prefill_steps = result.steps[: result.prefill_step_count]
    decode_steps = result.steps[result.prefill_step_count :]
    assert sum(step.phases[0].total_extend_tokens for step in prefill_steps) == 86_214
    assert [step.phases[0].total_extend_tokens for step in prefill_steps[:-1]] == [4_096] * 21
    assert prefill_steps[-1].phases[0].total_extend_tokens == 198
    assert prefill_steps[-1].phases[0].attention_pairs == 198 * 86_016 + 198 * 199 // 2
    assert [step.phases[0].phase for step in decode_steps] == [
        PredictionPhase.DECODE,
        PredictionPhase.DECODE,
    ]
    assert [step.phases[0].attention_pairs for step in decode_steps] == [86_215, 86_216]
    assert result.duration_ns == sum(step.duration_ns for step in result.steps)
    assert (
        provider.predict_isolated_request_duration_ns(
            prompt_tokens=86_214,
            output_tokens=3,
            max_num_scheduled_tokens=4_096,
        )
        == result.duration_ns
    )
    assert result.provenance_fingerprint == provider.provenance_fingerprint
    assert result.to_dict()["fingerprint"] == result.fingerprint


def test_isolated_duration_honors_output_semantics_and_128k_boundary() -> None:
    provider = Qwen3TP4SchedulerStepDurationProvider(prediction_profile=_profile())

    one_output = provider.predict_isolated_request(
        prompt_tokens=40_961,
        output_tokens=1,
    )
    assert one_output.covered_prompt_tokens == 40_961
    assert one_output.decode_step_count == 0
    assert all(step.phases[0].phase is PredictionPhase.PREFILL for step in one_output.steps)

    boundary = provider.predict_isolated_request(
        prompt_tokens=131_071,
        output_tokens=1,
    )
    assert boundary.covered_prompt_tokens == 131_071
    assert boundary.steps[-1].phases[0].total_extend_tokens == 4_095

    with pytest.raises(ValueError, match="131072-token context"):
        provider.predict_isolated_request_duration_ns(
            prompt_tokens=131_071,
            output_tokens=2,
        )
    with pytest.raises(ValueError, match="prompt_tokens"):
        provider.predict_isolated_request_duration_ns(prompt_tokens=0, output_tokens=1)
    with pytest.raises(ValueError, match="output_tokens"):
        provider.predict_isolated_request_duration_ns(prompt_tokens=1, output_tokens=0)
    with pytest.raises(ValueError, match="max_num_scheduled_tokens"):
        provider.predict_isolated_request_duration_ns(
            prompt_tokens=1,
            output_tokens=1,
            max_num_scheduled_tokens=0,
        )


def test_provider_fails_closed_on_empty_wrong_profile_batch_or_context() -> None:
    profile = _profile()
    provider = Qwen3TP4SchedulerStepDurationProvider(prediction_profile=profile)
    empty = AdaptedSchedulerStep(
        scheduled_request_ids=(),
        phase_batches=(),
        scheduler_output_fingerprint="0" * 64,
    )
    with pytest.raises(ValueError, match="non-empty"):
        provider.predict_step(empty)

    wrong_model_profile = replace(profile, model_id="Qwen/Qwen3-8B")
    with pytest.raises(ValueError, match="model_id"):
        Qwen3TP4SchedulerStepDurationProvider(prediction_profile=wrong_model_profile)

    wrong_tp_profile = replace(profile, tensor_parallel_size=2)
    with pytest.raises(ValueError, match="tensor_parallel_size"):
        Qwen3TP4SchedulerStepDurationProvider(prediction_profile=wrong_tp_profile)

    other_profile = _profile("2" * 40)
    mismatched_step = _step(
        _phase(
            profile=other_profile,
            phase=PredictionPhase.DECODE,
            request_ids=("mismatch",),
            extend_lengths=(1,),
            past_kv_lengths=(10,),
        )
    )
    with pytest.raises(ValueError, match="profile_fingerprint"):
        provider.predict_step(mismatched_step)

    extended_context = _step(
        _phase(
            profile=profile,
            phase=PredictionPhase.PREFILL,
            request_ids=("beyond-native",),
            extend_lengths=(2,),
            past_kv_lengths=(40_959,),
        )
    )
    assert provider.predict_step(extended_context).duration_ns > 0

    over_context = _step(
        _phase(
            profile=profile,
            phase=PredictionPhase.PREFILL,
            request_ids=("too-long",),
            extend_lengths=(2,),
            past_kv_lengths=(131_071,),
        )
    )
    with pytest.raises(ValueError, match="131072-token context"):
        provider.predict_step(over_context)


def test_qwen3_32b_model_dimensions_and_tp4_collective_count_cannot_drift() -> None:
    with pytest.raises(ValueError, match="hidden_size=5120"):
        replace(Qwen3TP4AnalyticalParameters(), hidden_size=4_096)
    with pytest.raises(ValueError, match="tensor_parallel_size=4"):
        replace(Qwen3TP4AnalyticalParameters(), tensor_parallel_size=8)
    with pytest.raises(ValueError, match="model_all_reduces_per_layer=2"):
        replace(Qwen3TP4AnalyticalParameters(), model_all_reduces_per_layer=1)
    with pytest.raises(ValueError, match="native_max_context_tokens=40960"):
        replace(Qwen3TP4AnalyticalParameters(), native_max_context_tokens=131_072)
    with pytest.raises(ValueError, match="max_context_tokens=131072"):
        replace(Qwen3TP4AnalyticalParameters(), max_context_tokens=40_960)
    with pytest.raises(ValueError, match="model_safetensors_total_bytes=65524246528"):
        replace(
            Qwen3TP4AnalyticalParameters(),
            model_safetensors_total_bytes=65_524_246_527,
        )
