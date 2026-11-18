"""Shape-aware residual records for forward-predictor calibration evidence."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from moonkvsim.common.hash import canonical_json_bytes, sha256_json
from moonkvsim.predictor.schema import (
    CalibrationEvidence,
    CalibrationEvidenceLabel,
    PredictionBatch,
    PredictionPhase,
    _require_non_empty,
    _require_non_negative_int,
    _require_positive_int,
    _require_sha256,
)

CALIBRATION_REPORT_SCHEMA = "moonkvsim.predictor-calibration.v1"


def _validate_edges(edges: tuple[int, ...], field_name: str) -> None:
    if not isinstance(edges, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if not edges:
        raise ValueError(f"{field_name} must contain at least one upper bound")
    for value in edges:
        _require_positive_int(value, f"{field_name} entry")
    if tuple(sorted(set(edges))) != edges:
        raise ValueError(f"{field_name} must be strictly increasing")


def _bucket_upper_bound(value: int, edges: tuple[int, ...]) -> int | None:
    return next((edge for edge in edges if value <= edge), None)


def _bound_sort_key(value: int | None) -> tuple[bool, int]:
    return (value is None, 0 if value is None else value)


@dataclass(frozen=True, slots=True)
class ShapeBucketSpec:
    """Explicit, non-performance scaling coordinates for residual grouping."""

    batch_size_upper_bounds: tuple[int, ...]
    extend_length_upper_bounds: tuple[int, ...]
    past_kv_length_upper_bounds: tuple[int, ...]

    def __post_init__(self) -> None:
        _validate_edges(self.batch_size_upper_bounds, "batch_size_upper_bounds")
        _validate_edges(self.extend_length_upper_bounds, "extend_length_upper_bounds")
        _validate_edges(self.past_kv_length_upper_bounds, "past_kv_length_upper_bounds")

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_size_upper_bounds": list(self.batch_size_upper_bounds),
            "extend_length_upper_bounds": list(self.extend_length_upper_bounds),
            "past_kv_length_upper_bounds": list(self.past_kv_length_upper_bounds),
            "overflow_bucket": True,
        }


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    """One measured forward with raw and shape-calibrated predictions."""

    sample_id: str
    batch: PredictionBatch
    raw_prediction_ns: int
    calibrated_prediction_ns: int
    observed_forward_duration_ns: int

    def __post_init__(self) -> None:
        _require_non_empty(self.sample_id, "sample_id")
        if not isinstance(self.batch, PredictionBatch):
            raise TypeError("batch must be a PredictionBatch")
        _require_positive_int(self.raw_prediction_ns, "raw_prediction_ns")
        _require_positive_int(
            self.calibrated_prediction_ns,
            "calibrated_prediction_ns",
        )
        _require_positive_int(
            self.observed_forward_duration_ns,
            "observed_forward_duration_ns",
        )

    @property
    def raw_residual_ns(self) -> int:
        """Signed residual using the declared predicted-minus-observed convention."""

        return self.raw_prediction_ns - self.observed_forward_duration_ns

    @property
    def calibrated_residual_ns(self) -> int:
        return self.calibrated_prediction_ns - self.observed_forward_duration_ns

    def to_dict(self) -> dict[str, object]:
        return {
            "sample_id": self.sample_id,
            "profile_fingerprint": self.batch.profile_fingerprint,
            "batch_fingerprint": self.batch.fingerprint,
            "phase": self.batch.phase.value,
            "shape": self.batch.shape.to_dict(),
            "raw_prediction_ns": self.raw_prediction_ns,
            "calibrated_prediction_ns": self.calibrated_prediction_ns,
            "observed_forward_duration_ns": self.observed_forward_duration_ns,
            "raw_residual_ns": self.raw_residual_ns,
            "calibrated_residual_ns": self.calibrated_residual_ns,
        }


@dataclass(frozen=True, slots=True)
class ResidualStatistics:
    """Deterministic integer-residual summary for one shape bucket."""

    sample_count: int
    signed_error_sum_ns: int
    mean_signed_error_ns: float
    mean_absolute_error_ns: float
    p50_absolute_error_ns: int
    p95_absolute_error_ns: int
    max_absolute_error_ns: int

    def __post_init__(self) -> None:
        _require_positive_int(self.sample_count, "sample_count")
        if isinstance(self.signed_error_sum_ns, bool) or not isinstance(
            self.signed_error_sum_ns, int
        ):
            raise ValueError("signed_error_sum_ns must be an integer")
        if not math.isfinite(self.mean_signed_error_ns):
            raise ValueError("mean_signed_error_ns must be finite")
        if (
            not math.isfinite(self.mean_absolute_error_ns)
            or self.mean_absolute_error_ns < 0
        ):
            raise ValueError("mean_absolute_error_ns must be finite and non-negative")
        _require_non_negative_int(
            self.p50_absolute_error_ns,
            "p50_absolute_error_ns",
        )
        _require_non_negative_int(
            self.p95_absolute_error_ns,
            "p95_absolute_error_ns",
        )
        _require_non_negative_int(
            self.max_absolute_error_ns,
            "max_absolute_error_ns",
        )
        if not (
            self.p50_absolute_error_ns
            <= self.p95_absolute_error_ns
            <= self.max_absolute_error_ns
        ):
            raise ValueError("absolute-error percentiles must be monotonic")

    @classmethod
    def from_residuals(cls, residuals: tuple[int, ...]) -> ResidualStatistics:
        if not residuals:
            raise ValueError("residual statistics require at least one sample")
        absolute = tuple(sorted(abs(value) for value in residuals))
        count = len(residuals)

        def nearest_rank(percentile: float) -> int:
            return absolute[max(0, math.ceil(percentile * count) - 1)]

        signed_sum = sum(residuals)
        absolute_sum = sum(absolute)
        return cls(
            sample_count=count,
            signed_error_sum_ns=signed_sum,
            mean_signed_error_ns=signed_sum / count,
            mean_absolute_error_ns=absolute_sum / count,
            p50_absolute_error_ns=nearest_rank(0.50),
            p95_absolute_error_ns=nearest_rank(0.95),
            max_absolute_error_ns=absolute[-1],
        )

    def to_dict(self) -> dict[str, int | float]:
        return {
            "sample_count": self.sample_count,
            "signed_error_sum_ns": self.signed_error_sum_ns,
            "mean_signed_error_ns": self.mean_signed_error_ns,
            "mean_absolute_error_ns": self.mean_absolute_error_ns,
            "p50_absolute_error_ns": self.p50_absolute_error_ns,
            "p95_absolute_error_ns": self.p95_absolute_error_ns,
            "max_absolute_error_ns": self.max_absolute_error_ns,
        }


@dataclass(frozen=True, slots=True)
class ResidualBucket:
    phase: PredictionPhase
    batch_size_upper_bound: int | None
    extend_length_upper_bound: int | None
    past_kv_length_upper_bound: int | None
    raw: ResidualStatistics
    calibrated: ResidualStatistics

    def __post_init__(self) -> None:
        if not isinstance(self.phase, PredictionPhase):
            raise TypeError("phase must be a PredictionPhase")
        for field_name in (
            "batch_size_upper_bound",
            "extend_length_upper_bound",
            "past_kv_length_upper_bound",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_positive_int(value, field_name)
        if not isinstance(self.raw, ResidualStatistics) or not isinstance(
            self.calibrated, ResidualStatistics
        ):
            raise TypeError("raw and calibrated values must be ResidualStatistics")
        if self.raw.sample_count != self.calibrated.sample_count:
            raise ValueError("raw and calibrated residual counts must match")

    def sort_key(self) -> tuple[object, ...]:
        return (
            self.phase.value,
            _bound_sort_key(self.batch_size_upper_bound),
            _bound_sort_key(self.extend_length_upper_bound),
            _bound_sort_key(self.past_kv_length_upper_bound),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "batch_size_upper_bound": self.batch_size_upper_bound,
            "extend_length_upper_bound": self.extend_length_upper_bound,
            "past_kv_length_upper_bound": self.past_kv_length_upper_bound,
            "raw": self.raw.to_dict(),
            "calibrated": self.calibrated.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """Stable report; its label records evidence level rather than upgrading it."""

    profile_fingerprint: str
    calibration_method: str
    source_evidence_sha256: str | None
    evidence_label: CalibrationEvidenceLabel
    formal_use_allowed: bool
    bucket_spec: ShapeBucketSpec
    observations: tuple[CalibrationObservation, ...]
    residual_buckets: tuple[ResidualBucket, ...]

    def __post_init__(self) -> None:
        _require_sha256(self.profile_fingerprint, "profile_fingerprint")
        _require_non_empty(self.calibration_method, "calibration_method")
        if not isinstance(self.evidence_label, CalibrationEvidenceLabel):
            raise TypeError("evidence_label must be a CalibrationEvidenceLabel")
        if not isinstance(self.formal_use_allowed, bool):
            raise TypeError("formal_use_allowed must be boolean")
        if not isinstance(self.bucket_spec, ShapeBucketSpec):
            raise TypeError("bucket_spec must be a ShapeBucketSpec")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, CalibrationObservation) for item in self.observations
        ):
            raise TypeError("observations must be a tuple of CalibrationObservation values")
        if not isinstance(self.residual_buckets, tuple) or any(
            not isinstance(item, ResidualBucket) for item in self.residual_buckets
        ):
            raise TypeError("residual_buckets must be a tuple of ResidualBucket values")
        if self.source_evidence_sha256 is not None:
            _require_sha256(self.source_evidence_sha256, "source_evidence_sha256")
        if not self.observations or not self.residual_buckets:
            raise ValueError("calibration report must contain observations and buckets")
        if self.observations != tuple(sorted(self.observations, key=lambda item: item.sample_id)):
            raise ValueError("calibration observations must be sorted by sample_id")
        if len({item.sample_id for item in self.observations}) != len(self.observations):
            raise ValueError("calibration sample_id values must be unique")
        if self.residual_buckets != tuple(
            sorted(self.residual_buckets, key=lambda item: item.sort_key())
        ):
            raise ValueError("residual buckets must use canonical ordering")
        if any(
            item.batch.profile_fingerprint != self.profile_fingerprint
            for item in self.observations
        ):
            raise ValueError("all observations must use the report profile")
        if sum(item.raw.sample_count for item in self.residual_buckets) != len(
            self.observations
        ):
            raise ValueError("residual bucket counts must cover every observation exactly once")
        if self.evidence_label is CalibrationEvidenceLabel.PRELIMINARY:
            if self.formal_use_allowed:
                raise ValueError("preliminary residuals cannot allow formal use")
        elif self.source_evidence_sha256 is None:
            raise ValueError("calibrated reports require source evidence SHA-256")
        if self.formal_use_allowed and not self.coverage_complete:
            raise ValueError("formal calibration requires both prefill and decode evidence")

    @property
    def coverage_complete(self) -> bool:
        phases = {item.batch.phase for item in self.observations}
        return phases == set(PredictionPhase)

    def canonical_fields(self) -> dict[str, object]:
        phase_counts = {
            phase.value: sum(item.batch.phase is phase for item in self.observations)
            for phase in PredictionPhase
        }
        return {
            "schema": CALIBRATION_REPORT_SCHEMA,
            "profile_fingerprint": self.profile_fingerprint,
            "calibration_method": self.calibration_method,
            "source_evidence_sha256": self.source_evidence_sha256,
            "evidence_label": self.evidence_label.value,
            "formal_use_allowed": self.formal_use_allowed,
            "coverage_complete": self.coverage_complete,
            "phase_sample_counts": phase_counts,
            "residual_convention": "predicted_minus_observed_ns",
            "absolute_error_percentile_method": "nearest_rank",
            "bucket_spec": self.bucket_spec.to_dict(),
            "observations": [item.to_dict() for item in self.observations],
            "residual_buckets": [item.to_dict() for item in self.residual_buckets],
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        value = self.canonical_fields()
        value["fingerprint"] = self.fingerprint
        return value

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_evidence(self) -> CalibrationEvidence:
        return CalibrationEvidence(
            profile_fingerprint=self.profile_fingerprint,
            label=self.evidence_label,
            formal_use_allowed=self.formal_use_allowed,
            calibration_report_fingerprint=self.fingerprint,
        )


def build_calibration_report(
    *,
    profile_fingerprint: str,
    observations: Iterable[CalibrationObservation],
    bucket_spec: ShapeBucketSpec,
    calibration_method: str,
    source_evidence_sha256: str | None = None,
    evidence_label: CalibrationEvidenceLabel = CalibrationEvidenceLabel.PRELIMINARY,
    formal_use_allowed: bool = False,
) -> CalibrationReport:
    """Group residuals by phase, batch size, extension length, and past-KV length."""

    ordered = tuple(sorted(observations, key=lambda item: item.sample_id))
    if len({item.sample_id for item in ordered}) != len(ordered):
        raise ValueError("calibration sample_id values must be unique")

    key_to_samples: dict[
        tuple[PredictionPhase, int | None, int | None, int | None],
        list[CalibrationObservation],
    ] = defaultdict(list)
    for item in ordered:
        shape = item.batch.shape
        key = (
            item.batch.phase,
            _bucket_upper_bound(shape.batch_size, bucket_spec.batch_size_upper_bounds),
            _bucket_upper_bound(
                shape.max_extend_length,
                bucket_spec.extend_length_upper_bounds,
            ),
            _bucket_upper_bound(
                shape.max_past_kv_length,
                bucket_spec.past_kv_length_upper_bounds,
            ),
        )
        key_to_samples[key].append(item)

    buckets: list[ResidualBucket] = []
    for key, samples in key_to_samples.items():
        phase, batch_upper, extend_upper, past_upper = key
        buckets.append(
            ResidualBucket(
                phase=phase,
                batch_size_upper_bound=batch_upper,
                extend_length_upper_bound=extend_upper,
                past_kv_length_upper_bound=past_upper,
                raw=ResidualStatistics.from_residuals(
                    tuple(item.raw_residual_ns for item in samples)
                ),
                calibrated=ResidualStatistics.from_residuals(
                    tuple(item.calibrated_residual_ns for item in samples)
                ),
            )
        )

    return CalibrationReport(
        profile_fingerprint=profile_fingerprint,
        calibration_method=calibration_method,
        source_evidence_sha256=source_evidence_sha256,
        evidence_label=evidence_label,
        formal_use_allowed=formal_use_allowed,
        bucket_spec=bucket_spec,
        observations=ordered,
        residual_buckets=tuple(sorted(buckets, key=lambda item: item.sort_key())),
    )
