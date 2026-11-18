"""Adapter/provider protocols and the fail-closed forward-only facade."""

from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from moonkvsim.predictor.schema import (
    CalibrationEvidence,
    ForwardPrediction,
    PredictionBatch,
    PredictionPhase,
    PredictionProfile,
)

SourceBatchT = TypeVar("SourceBatchT", contravariant=True)


@runtime_checkable
class PredictionBatchAdapter(Protocol[SourceBatchT]):
    """Convert an engine-owned scheduled batch into the neutral schema."""

    def adapt(
        self,
        source_batch: SourceBatchT,
        *,
        phase: PredictionPhase,
        profile: PredictionProfile,
    ) -> PredictionBatch: ...


@runtime_checkable
class ForwardDurationProvider(Protocol):
    """Return only GPU-forward nanoseconds for an already-normalized batch."""

    @property
    def provider_name(self) -> str: ...

    def predict_forward_duration_ns(self, batch: PredictionBatch) -> int: ...


class ForwardPredictor:
    """Validate profile identity and keep provider output forward-only."""

    def __init__(
        self,
        *,
        profile: PredictionProfile,
        evidence: CalibrationEvidence,
        provider: ForwardDurationProvider,
    ) -> None:
        if evidence.profile_fingerprint != profile.fingerprint:
            raise ValueError("calibration evidence belongs to a different profile")
        if provider.provider_name != profile.provider_name:
            raise ValueError("provider_name does not match the profile manifest")
        self._profile = profile
        self._evidence = evidence
        self._provider = provider

    @property
    def profile(self) -> PredictionProfile:
        return self._profile

    @property
    def evidence(self) -> CalibrationEvidence:
        return self._evidence

    def predict(
        self,
        batch: PredictionBatch,
        *,
        require_formal: bool = False,
    ) -> ForwardPrediction:
        self._validate_batch_identity(batch)
        if require_formal:
            self._evidence.require_formal_use()
        duration_ns = self._provider.predict_forward_duration_ns(batch)
        if isinstance(duration_ns, bool) or not isinstance(duration_ns, int):
            raise TypeError("forward provider must return one integer duration in nanoseconds")
        return ForwardPrediction(
            predicted_forward_duration_ns=duration_ns,
            phase=batch.phase,
            batch_fingerprint=batch.fingerprint,
            profile_fingerprint=self._profile.fingerprint,
            evidence=self._evidence,
        )

    def _validate_batch_identity(self, batch: PredictionBatch) -> None:
        expected = (
            self._profile.model_id,
            self._profile.model_revision,
            self._profile.tensor_parallel_size,
            self._profile.pipeline_parallel_size,
            self._profile.hardware_profile_id,
            self._profile.hardware_profile_fingerprint,
            self._profile.fingerprint,
        )
        actual = (
            batch.model_id,
            batch.model_revision,
            batch.tensor_parallel_size,
            batch.pipeline_parallel_size,
            batch.hardware_profile_id,
            batch.hardware_profile_fingerprint,
            batch.profile_fingerprint,
        )
        if actual != expected:
            raise ValueError("prediction batch does not match the resolved profile")
