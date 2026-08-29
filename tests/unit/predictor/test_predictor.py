from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import pytest

from moonkvsim.predictor import (
    AssumedIntegerMixedPhaseCompositionRule,
    CalibrationEvidence,
    CalibrationEvidenceLabel,
    CalibrationObservation,
    ExternalLatencyComponent,
    ForwardBoundary,
    ForwardDurationProvider,
    ForwardPredictor,
    PredictionBatch,
    PredictionBatchAdapter,
    PredictionPhase,
    PredictionProfile,
    PredictionRequest,
    PredictorEvidenceError,
    ShapeBucketSpec,
    build_calibration_report,
)

AI_CONFIGURATOR_COMMIT = "4b9d9dc51e02b5e9d4acc3688f3edf41693834c6"


def fixture_profile() -> PredictionProfile:
    """Return an explicitly test-only profile, never a production fallback."""

    return PredictionProfile(
        provider_name="aiconfigurator",
        provider_version="0.9.0",
        provider_source_revision=AI_CONFIGURATOR_COMMIT,
        database_mode="unit-test-fixture",
        database_sha256="1" * 64,
        hardware_profile_id="unit-test-gpu-profile",
        hardware_profile_fingerprint="2" * 64,
        model_id="unit-test/model",
        model_revision="unit-test-revision",
        tensor_parallel_size=4,
        pipeline_parallel_size=2,
        forward_boundary=ForwardBoundary(
            includes_model_collectives=True,
            model_collective_scope="unit-test profile includes TP collectives",
        ),
    )


def fixture_batch(
    profile: PredictionProfile,
    *,
    phase: PredictionPhase,
    lengths: tuple[tuple[int, int], ...],
) -> PredictionBatch:
    return PredictionBatch.for_profile(
        requests=tuple(
            PredictionRequest(extend_length=extend, past_kv_length=past) for extend, past in lengths
        ),
        phase=phase,
        profile=profile,
    )


class ConstantForwardProvider:
    provider_name = "aiconfigurator"

    def __init__(self, duration_ns: int) -> None:
        self.duration_ns = duration_ns

    def predict_forward_duration_ns(self, batch: PredictionBatch) -> int:
        assert batch.requests
        return self.duration_ns


class TupleBatchAdapter:
    def adapt(
        self,
        source_batch: tuple[tuple[int, int], ...],
        *,
        phase: PredictionPhase,
        profile: PredictionProfile,
    ) -> PredictionBatch:
        return fixture_batch(profile, phase=phase, lengths=source_batch)


class StructuredIOProvider:
    provider_name = "aiconfigurator"

    def predict_forward_duration_ns(self, batch: PredictionBatch) -> object:
        return {
            "forward_duration_ns": 10,
            "io_duration_ns": 20,
            "batch": batch.fingerprint,
        }


def test_profile_and_batch_fingerprints_are_stable_and_shape_sensitive() -> None:
    profile = fixture_profile()
    identical = fixture_profile()
    changed_hardware = replace(profile, hardware_profile_fingerprint="3" * 64)

    assert profile.fingerprint == identical.fingerprint
    assert profile.to_json_bytes() == identical.to_json_bytes()
    assert profile.fingerprint != changed_hardware.fingerprint

    first = fixture_batch(
        profile,
        phase=PredictionPhase.PREFILL,
        lengths=((128, 0), (16, 64)),
    )
    second = fixture_batch(
        profile,
        phase=PredictionPhase.PREFILL,
        lengths=((128, 0), (16, 64)),
    )
    changed_shape = fixture_batch(
        profile,
        phase=PredictionPhase.PREFILL,
        lengths=((128, 0), (17, 64)),
    )

    assert first.fingerprint == second.fingerprint
    assert first.to_json_bytes() == second.to_json_bytes()
    assert first.fingerprint != changed_shape.fingerprint
    assert first.shape.batch_size == 2
    assert first.shape.total_extend_length == 144
    assert first.shape.max_past_kv_length == 64


def test_phase_and_request_shape_validation_fail_closed() -> None:
    profile = fixture_profile()

    with pytest.raises(ValueError, match="positive integer"):
        PredictionRequest(extend_length=0, past_kv_length=0)
    with pytest.raises(ValueError, match="positive integer"):
        PredictionRequest(extend_length=1.5, past_kv_length=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative integer"):
        PredictionRequest(extend_length=1, past_kv_length=-1)
    with pytest.raises(ValueError, match="exactly one token"):
        fixture_batch(
            profile,
            phase=PredictionPhase.DECODE,
            lengths=((2, 128),),
        )
    one_token_prefill = fixture_batch(
        profile,
        phase=PredictionPhase.PREFILL,
        lengths=((1, 128), (1, 256)),
    )
    assert one_token_prefill.phase is PredictionPhase.PREFILL
    with pytest.raises(ValueError, match="at least one request"):
        PredictionBatch.for_profile(
            requests=(),
            phase=PredictionPhase.DECODE,
            profile=profile,
        )


def test_forward_output_contains_only_forward_duration_and_external_io_is_excluded() -> None:
    profile = fixture_profile()
    batch = fixture_batch(
        profile,
        phase=PredictionPhase.DECODE,
        lengths=((1, 512), (1, 1024)),
    )
    evidence = CalibrationEvidence.preliminary(profile.fingerprint)
    predictor = ForwardPredictor(
        profile=profile,
        evidence=evidence,
        provider=ConstantForwardProvider(123_456),
    )

    result = predictor.predict(batch)
    serialized = json.loads(result.to_json_bytes())

    assert result.predicted_forward_duration_ns == 123_456
    assert serialized["boundary"] == "gpu_forward_only"
    assert set(serialized) == {
        "batch_fingerprint",
        "boundary",
        "evidence",
        "phase",
        "predicted_forward_duration_ns",
        "profile_fingerprint",
    }
    assert ExternalLatencyComponent.RDMA in profile.forward_boundary.excluded_components
    assert ExternalLatencyComponent.KV_D2H in profile.forward_boundary.excluded_components
    assert ExternalLatencyComponent.STORE_DRAM in profile.forward_boundary.excluded_components
    assert "io_duration_ns" not in serialized
    assert b"global_scale" not in profile.to_json_bytes()


def test_adapter_provider_protocols_and_scalar_boundary_are_runtime_checkable() -> None:
    profile = fixture_profile()
    adapter = TupleBatchAdapter()
    provider = ConstantForwardProvider(10)

    assert isinstance(adapter, PredictionBatchAdapter)
    assert isinstance(provider, ForwardDurationProvider)
    batch = adapter.adapt(
        ((1, 64),),
        phase=PredictionPhase.DECODE,
        profile=profile,
    )
    predictor = ForwardPredictor(
        profile=profile,
        evidence=CalibrationEvidence.preliminary(profile.fingerprint),
        provider=cast(ForwardDurationProvider, StructuredIOProvider()),
    )

    with pytest.raises(TypeError, match="one integer duration"):
        predictor.predict(batch)


def test_uncalibrated_predictions_are_preliminary_and_rejected_for_formal_use() -> None:
    profile = fixture_profile()
    evidence = CalibrationEvidence.preliminary(profile.fingerprint)
    predictor = ForwardPredictor(
        profile=profile,
        evidence=evidence,
        provider=ConstantForwardProvider(50),
    )
    batch = fixture_batch(
        profile,
        phase=PredictionPhase.DECODE,
        lengths=((1, 128),),
    )

    preliminary = predictor.predict(batch)

    assert preliminary.evidence.label is CalibrationEvidenceLabel.PRELIMINARY
    assert preliminary.evidence.formal_use_allowed is False
    with pytest.raises(PredictorEvidenceError, match="not approved for formal use"):
        predictor.predict(batch, require_formal=True)
    with pytest.raises(ValueError, match="cannot allow formal use"):
        CalibrationEvidence(
            profile_fingerprint=profile.fingerprint,
            label=CalibrationEvidenceLabel.PRELIMINARY,
            formal_use_allowed=True,
        )


def test_joint_mixed_phase_formula_is_explicit_fingerprinted_and_preliminary() -> None:
    profile = fixture_profile()
    prefill = fixture_batch(
        profile,
        phase=PredictionPhase.PREFILL,
        lengths=((32, 0), (16, 64)),
    )
    decode = fixture_batch(
        profile,
        phase=PredictionPhase.DECODE,
        lengths=((1, 128), (1, 256)),
    )
    rule = AssumedIntegerMixedPhaseCompositionRule(
        parameter_fingerprint="3" * 64,
        base_ns=10,
        batch_request_overhead_ns=2,
        prefill_ns_per_scheduled_token=3,
        decode_ns_per_request=5,
        decode_ns_per_past_token=1,
    )

    prediction = rule.compose((prefill, decode))
    document = json.loads(prediction.to_json_bytes())

    assert prediction.predicted_forward_duration_ns == (10 + 2 * 4 + 3 * 48 + 5 * 2 + 128 + 256)
    assert document["composition_rule"]["fingerprint"] == rule.fingerprint
    assert document["composition_rule"]["semantics"]["base_application"] == (
        "once_per_joint_scheduler_step"
    )
    assert document["composition_rule"]["semantics"]["phase_provider_predictions_summed"] is False
    assert document["calibration_status"] == "not_calibrated"
    assert document["formal_use_allowed"] is False
    with pytest.raises(ValueError, match="prefill then decode"):
        rule.compose((decode, prefill))


def test_predictor_rejects_batch_from_a_different_profile() -> None:
    profile = fixture_profile()
    other_profile = replace(profile, model_revision="other-revision")
    predictor = ForwardPredictor(
        profile=profile,
        evidence=CalibrationEvidence.preliminary(profile.fingerprint),
        provider=ConstantForwardProvider(100),
    )
    other_batch = fixture_batch(
        other_profile,
        phase=PredictionPhase.DECODE,
        lengths=((1, 32),),
    )

    with pytest.raises(ValueError, match="does not match"):
        predictor.predict(other_batch)


def test_shape_aware_residual_buckets_and_json_are_deterministic() -> None:
    profile = fixture_profile()
    prefill_a = fixture_batch(
        profile,
        phase=PredictionPhase.PREFILL,
        lengths=((128, 0),),
    )
    prefill_b = fixture_batch(
        profile,
        phase=PredictionPhase.PREFILL,
        lengths=((96, 32),),
    )
    decode = fixture_batch(
        profile,
        phase=PredictionPhase.DECODE,
        lengths=((1, 512), (1, 700)),
    )
    observations = (
        CalibrationObservation(
            sample_id="prefill-b",
            batch=prefill_b,
            raw_prediction_ns=90,
            calibrated_prediction_ns=95,
            observed_forward_duration_ns=100,
        ),
        CalibrationObservation(
            sample_id="decode-a",
            batch=decode,
            raw_prediction_ns=220,
            calibrated_prediction_ns=210,
            observed_forward_duration_ns=200,
        ),
        CalibrationObservation(
            sample_id="prefill-a",
            batch=prefill_a,
            raw_prediction_ns=110,
            calibrated_prediction_ns=105,
            observed_forward_duration_ns=100,
        ),
    )
    bucket_spec = ShapeBucketSpec(
        batch_size_upper_bounds=(1, 4),
        extend_length_upper_bounds=(1, 128, 512),
        past_kv_length_upper_bounds=(64, 1024),
    )

    report = build_calibration_report(
        profile_fingerprint=profile.fingerprint,
        observations=observations,
        bucket_spec=bucket_spec,
        calibration_method="unit-test-shape-aware-residual-fixture",
    )
    reversed_report = build_calibration_report(
        profile_fingerprint=profile.fingerprint,
        observations=reversed(observations),
        bucket_spec=bucket_spec,
        calibration_method="unit-test-shape-aware-residual-fixture",
    )

    assert report.to_json_bytes() == reversed_report.to_json_bytes()
    assert report.fingerprint == reversed_report.fingerprint
    assert report.coverage_complete
    assert report.evidence_label is CalibrationEvidenceLabel.PRELIMINARY
    assert report.formal_use_allowed is False
    assert [item.sample_id for item in report.observations] == [
        "decode-a",
        "prefill-a",
        "prefill-b",
    ]
    assert len(report.residual_buckets) == 2
    prefill_bucket = next(
        item for item in report.residual_buckets if item.phase is PredictionPhase.PREFILL
    )
    assert prefill_bucket.raw.sample_count == 2
    assert prefill_bucket.raw.mean_signed_error_ns == 0
    assert prefill_bucket.raw.mean_absolute_error_ns == 10
    assert prefill_bucket.calibrated.mean_absolute_error_ns == 5
    evidence = report.to_evidence()
    assert evidence.label is CalibrationEvidenceLabel.PRELIMINARY
    assert evidence.formal_use_allowed is False
    assert evidence.calibration_report_fingerprint == report.fingerprint


def test_calibrated_label_requires_hash_locked_source_evidence() -> None:
    profile = fixture_profile()
    observation = CalibrationObservation(
        sample_id="prefill-a",
        batch=fixture_batch(
            profile,
            phase=PredictionPhase.PREFILL,
            lengths=((8, 0),),
        ),
        raw_prediction_ns=10,
        calibrated_prediction_ns=10,
        observed_forward_duration_ns=10,
    )

    with pytest.raises(ValueError, match="source evidence"):
        build_calibration_report(
            profile_fingerprint=profile.fingerprint,
            observations=(observation,),
            bucket_spec=ShapeBucketSpec(
                batch_size_upper_bounds=(1,),
                extend_length_upper_bounds=(8,),
                past_kv_length_upper_bounds=(1,),
            ),
            calibration_method="unit-test-shape-aware-residual-fixture",
            evidence_label=CalibrationEvidenceLabel.CALIBRATED,
        )
