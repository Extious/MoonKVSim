"""Engine-neutral, tensor-free schemas for GPU-forward prediction.

These values deliberately contain no scheduler, connector, Store, transfer, or
failure-recovery latency.  Such work belongs to independent MoonKVSim resources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from moonkvsim.common.hash import canonical_json_bytes, sha256_json

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require_non_empty(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be non-empty and have no outer whitespace")


def _require_sha256(value: object, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256")


def _require_positive_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


class PredictionPhase(StrEnum):
    """A phase-specific forward prediction boundary."""

    PREFILL = "prefill"
    DECODE = "decode"


class CalibrationEvidenceLabel(StrEnum):
    """Evidence class attached to a forward prediction."""

    PRELIMINARY = "preliminary"
    CALIBRATED = "calibrated"


class ExternalLatencyComponent(StrEnum):
    """Latency components that are never accepted from a forward provider."""

    SCHEDULER_CPU = "scheduler_cpu"
    CONNECTOR_METADATA = "connector_metadata"
    MASTER_RPC = "master_rpc"
    KV_D2D = "kv_d2d"
    KV_H2D = "kv_h2d"
    KV_D2H = "kv_d2h"
    RDMA = "rdma"
    TCP = "tcp"
    STORE_DRAM = "store_dram"
    FAILURE_DETECTION = "failure_detection"
    REROUTE = "reroute"
    RECOVERY_REPLAY = "recovery_replay"


@dataclass(frozen=True, slots=True)
class PredictionRequest:
    """One request's token shape during a single scheduler step."""

    extend_length: int
    past_kv_length: int

    def __post_init__(self) -> None:
        _require_positive_int(self.extend_length, "extend_length")
        _require_non_negative_int(self.past_kv_length, "past_kv_length")

    @property
    def resulting_context_length(self) -> int:
        return self.past_kv_length + self.extend_length

    def to_dict(self) -> dict[str, int]:
        return {
            "extend_length": self.extend_length,
            "past_kv_length": self.past_kv_length,
            "resulting_context_length": self.resulting_context_length,
        }


@dataclass(frozen=True, slots=True)
class PredictionBatchShape:
    """Exact request vectors plus aggregate coordinates used for residual buckets."""

    extend_lengths: tuple[int, ...]
    past_kv_lengths: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.extend_lengths, tuple) or not isinstance(
            self.past_kv_lengths, tuple
        ):
            raise TypeError("batch shape vectors must be tuples")
        if not self.extend_lengths or len(self.extend_lengths) != len(self.past_kv_lengths):
            raise ValueError("batch shape vectors must be non-empty and equally sized")
        for value in self.extend_lengths:
            _require_positive_int(value, "extend_lengths entry")
        for value in self.past_kv_lengths:
            _require_non_negative_int(value, "past_kv_lengths entry")

    @property
    def batch_size(self) -> int:
        return len(self.extend_lengths)

    @property
    def total_extend_length(self) -> int:
        return sum(self.extend_lengths)

    @property
    def max_extend_length(self) -> int:
        return max(self.extend_lengths)

    @property
    def max_past_kv_length(self) -> int:
        return max(self.past_kv_lengths)

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_size": self.batch_size,
            "extend_lengths": list(self.extend_lengths),
            "past_kv_lengths": list(self.past_kv_lengths),
            "total_extend_length": self.total_extend_length,
            "max_extend_length": self.max_extend_length,
            "max_past_kv_length": self.max_past_kv_length,
        }


@dataclass(frozen=True, slots=True)
class ForwardBoundary:
    """Manifest the only optional non-compute work allowed in a forward profile.

    Model-internal collectives may be included when the physical profile says so.
    Mooncake KV I/O and all control-plane work remain excluded unconditionally.
    """

    includes_model_collectives: bool
    model_collective_scope: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.includes_model_collectives, bool):
            raise TypeError("includes_model_collectives must be boolean")
        if self.includes_model_collectives:
            if self.model_collective_scope is None:
                raise ValueError("model_collective_scope is required when collectives are included")
            _require_non_empty(self.model_collective_scope, "model_collective_scope")
        elif self.model_collective_scope is not None:
            raise ValueError("model_collective_scope must be absent when collectives are excluded")

    @property
    def excluded_components(self) -> tuple[ExternalLatencyComponent, ...]:
        return tuple(ExternalLatencyComponent)

    def to_dict(self) -> dict[str, object]:
        included = ["model_forward"]
        if self.includes_model_collectives:
            included.append("profile_declared_model_collectives")
        return {
            "scope": "gpu_forward_only",
            "included_components": included,
            "includes_model_collectives": self.includes_model_collectives,
            "model_collective_scope": self.model_collective_scope,
            "excluded_components": [item.value for item in self.excluded_components],
        }


@dataclass(frozen=True, slots=True)
class PredictionProfile:
    """Resolved provider/database/model/hardware identity, never a default profile."""

    provider_name: str
    provider_version: str
    provider_source_revision: str
    database_mode: str
    database_sha256: str
    hardware_profile_id: str
    hardware_profile_fingerprint: str
    model_id: str
    model_revision: str
    tensor_parallel_size: int
    pipeline_parallel_size: int
    forward_boundary: ForwardBoundary

    def __post_init__(self) -> None:
        for field_name in (
            "provider_name",
            "provider_version",
            "database_mode",
            "hardware_profile_id",
            "model_id",
            "model_revision",
        ):
            _require_non_empty(getattr(self, field_name), field_name)
        if (
            not isinstance(self.provider_source_revision, str)
            or _SHA1.fullmatch(self.provider_source_revision) is None
        ):
            raise ValueError("provider_source_revision must be a lowercase Git commit")
        _require_sha256(self.database_sha256, "database_sha256")
        _require_sha256(
            self.hardware_profile_fingerprint,
            "hardware_profile_fingerprint",
        )
        _require_positive_int(self.tensor_parallel_size, "tensor_parallel_size")
        _require_positive_int(self.pipeline_parallel_size, "pipeline_parallel_size")
        if not isinstance(self.forward_boundary, ForwardBoundary):
            raise TypeError("forward_boundary must be a ForwardBoundary")

    def canonical_fields(self) -> dict[str, object]:
        return {
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "provider_source_revision": self.provider_source_revision,
            "database_mode": self.database_mode,
            "database_sha256": self.database_sha256,
            "hardware_profile_id": self.hardware_profile_id,
            "hardware_profile_fingerprint": self.hardware_profile_fingerprint,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "tensor_parallel_size": self.tensor_parallel_size,
            "pipeline_parallel_size": self.pipeline_parallel_size,
            "forward_boundary": self.forward_boundary.to_dict(),
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


@dataclass(frozen=True, slots=True)
class PredictionBatch:
    """Complete engine-neutral input for one phase-specific forward prediction."""

    requests: tuple[PredictionRequest, ...]
    phase: PredictionPhase
    model_id: str
    model_revision: str
    tensor_parallel_size: int
    pipeline_parallel_size: int
    hardware_profile_id: str
    hardware_profile_fingerprint: str
    profile_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.requests, tuple) or any(
            not isinstance(request, PredictionRequest) for request in self.requests
        ):
            raise TypeError("requests must be a tuple of PredictionRequest values")
        if not self.requests:
            raise ValueError("prediction batch must contain at least one request")
        if not isinstance(self.phase, PredictionPhase):
            raise TypeError("phase must be a PredictionPhase")
        if self.phase is PredictionPhase.DECODE and any(
            request.extend_length != 1 for request in self.requests
        ):
            raise ValueError("decode requests must extend by exactly one token")
        # Do not infer prefill versus decode from extension length alone.  A
        # one-token prompt, or the final one-token chunk of a chunked prefill,
        # is still prefill.  The engine adapter derives phase from the request's
        # pre-step computed-token position relative to its prompt boundary.
        for field_name in (
            "model_id",
            "model_revision",
            "hardware_profile_id",
        ):
            _require_non_empty(getattr(self, field_name), field_name)
        _require_positive_int(self.tensor_parallel_size, "tensor_parallel_size")
        _require_positive_int(self.pipeline_parallel_size, "pipeline_parallel_size")
        _require_sha256(
            self.hardware_profile_fingerprint,
            "hardware_profile_fingerprint",
        )
        _require_sha256(self.profile_fingerprint, "profile_fingerprint")

    @classmethod
    def for_profile(
        cls,
        *,
        requests: tuple[PredictionRequest, ...],
        phase: PredictionPhase,
        profile: PredictionProfile,
    ) -> PredictionBatch:
        return cls(
            requests=requests,
            phase=phase,
            model_id=profile.model_id,
            model_revision=profile.model_revision,
            tensor_parallel_size=profile.tensor_parallel_size,
            pipeline_parallel_size=profile.pipeline_parallel_size,
            hardware_profile_id=profile.hardware_profile_id,
            hardware_profile_fingerprint=profile.hardware_profile_fingerprint,
            profile_fingerprint=profile.fingerprint,
        )

    @property
    def shape(self) -> PredictionBatchShape:
        return PredictionBatchShape(
            extend_lengths=tuple(item.extend_length for item in self.requests),
            past_kv_lengths=tuple(item.past_kv_length for item in self.requests),
        )

    def canonical_fields(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "requests": [item.to_dict() for item in self.requests],
            "shape": self.shape.to_dict(),
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "tensor_parallel_size": self.tensor_parallel_size,
            "pipeline_parallel_size": self.pipeline_parallel_size,
            "hardware_profile_id": self.hardware_profile_id,
            "hardware_profile_fingerprint": self.hardware_profile_fingerprint,
            "profile_fingerprint": self.profile_fingerprint,
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


class PredictorEvidenceError(RuntimeError):
    """Raised when preliminary evidence is requested for formal use."""


@dataclass(frozen=True, slots=True)
class CalibrationEvidence:
    """Fail-closed evidence metadata attached to every prediction."""

    profile_fingerprint: str
    label: CalibrationEvidenceLabel
    formal_use_allowed: bool
    calibration_report_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _require_sha256(self.profile_fingerprint, "profile_fingerprint")
        if not isinstance(self.label, CalibrationEvidenceLabel):
            raise TypeError("label must be a CalibrationEvidenceLabel")
        if not isinstance(self.formal_use_allowed, bool):
            raise TypeError("formal_use_allowed must be boolean")
        if self.calibration_report_fingerprint is not None:
            _require_sha256(
                self.calibration_report_fingerprint,
                "calibration_report_fingerprint",
            )
        if self.label is CalibrationEvidenceLabel.PRELIMINARY:
            if self.formal_use_allowed:
                raise ValueError("preliminary predictor evidence cannot allow formal use")
        elif self.calibration_report_fingerprint is None:
            raise ValueError("calibrated evidence requires a calibration report fingerprint")
        if self.formal_use_allowed and self.label is not CalibrationEvidenceLabel.CALIBRATED:
            raise ValueError("formal use requires calibrated evidence")

    @classmethod
    def preliminary(cls, profile_fingerprint: str) -> CalibrationEvidence:
        return cls(
            profile_fingerprint=profile_fingerprint,
            label=CalibrationEvidenceLabel.PRELIMINARY,
            formal_use_allowed=False,
        )

    def require_formal_use(self) -> None:
        if not self.formal_use_allowed:
            raise PredictorEvidenceError(
                "predictor evidence is preliminary or otherwise not approved for formal use"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_fingerprint": self.profile_fingerprint,
            "label": self.label.value,
            "formal_use_allowed": self.formal_use_allowed,
            "calibration_report_fingerprint": self.calibration_report_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class ForwardPrediction:
    """A scalar GPU-forward duration with provenance and no I/O latency fields."""

    predicted_forward_duration_ns: int
    phase: PredictionPhase
    batch_fingerprint: str
    profile_fingerprint: str
    evidence: CalibrationEvidence

    def __post_init__(self) -> None:
        _require_positive_int(
            self.predicted_forward_duration_ns,
            "predicted_forward_duration_ns",
        )
        if not isinstance(self.phase, PredictionPhase):
            raise TypeError("phase must be a PredictionPhase")
        _require_sha256(self.batch_fingerprint, "batch_fingerprint")
        _require_sha256(self.profile_fingerprint, "profile_fingerprint")
        if not isinstance(self.evidence, CalibrationEvidence):
            raise TypeError("evidence must be CalibrationEvidence")
        if self.evidence.profile_fingerprint != self.profile_fingerprint:
            raise ValueError("prediction evidence belongs to a different profile")

    def to_dict(self) -> dict[str, object]:
        return {
            "boundary": "gpu_forward_only",
            "predicted_forward_duration_ns": self.predicted_forward_duration_ns,
            "phase": self.phase.value,
            "batch_fingerprint": self.batch_fingerprint,
            "profile_fingerprint": self.profile_fingerprint,
            "evidence": self.evidence.to_dict(),
        }

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class AssumedIntegerMixedPhaseCompositionRule:
    """Explicit preliminary-only joint formula for a mixed scheduler step.

    This rule is intentionally narrower than a general forward provider.  It is
    an E2 control-flow assumption for a step containing both prefill and decode
    requests: the base is charged once, request overhead covers both phase
    batches, and the remaining terms retain their phase-specific coordinates.
    It is never calibrated and can never be promoted to formal use.
    """

    parameter_fingerprint: str
    base_ns: int
    batch_request_overhead_ns: int
    prefill_ns_per_scheduled_token: int
    decode_ns_per_request: int
    decode_ns_per_past_token: int
    rule_name: str = "joint_assumed_integer_formula"
    rule_version: str = "v1"

    def __post_init__(self) -> None:
        _require_sha256(self.parameter_fingerprint, "parameter_fingerprint")
        for field_name in (
            "base_ns",
            "batch_request_overhead_ns",
            "prefill_ns_per_scheduled_token",
            "decode_ns_per_request",
            "decode_ns_per_past_token",
        ):
            _require_positive_int(getattr(self, field_name), field_name)
        _require_non_empty(self.rule_name, "rule_name")
        _require_non_empty(self.rule_version, "rule_version")

    def canonical_fields(self) -> dict[str, object]:
        return {
            "schema": "moonkvsim.mixed-phase-composition-rule.v1",
            "rule_name": self.rule_name,
            "rule_version": self.rule_version,
            "parameter_source": "assumed",
            "parameter_fingerprint": self.parameter_fingerprint,
            "calibration_status": "not_calibrated",
            "evidence_label": CalibrationEvidenceLabel.PRELIMINARY.value,
            "formal_use_allowed": False,
            "semantics": {
                "base_application": "once_per_joint_scheduler_step",
                "request_overhead_scope": "all_prefill_and_decode_requests",
                "prefill_term": "scheduled_prefill_tokens",
                "decode_request_term": "decode_request_count",
                "decode_past_term": "sum_decode_past_kv_lengths",
                "phase_provider_predictions_summed": False,
            },
            "coefficients_ns": {
                "base_ns": self.base_ns,
                "batch_request_overhead_ns": self.batch_request_overhead_ns,
                "prefill_ns_per_scheduled_token": (self.prefill_ns_per_scheduled_token),
                "decode_ns_per_request": self.decode_ns_per_request,
                "decode_ns_per_past_token": self.decode_ns_per_past_token,
            },
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        value = self.canonical_fields()
        value["fingerprint"] = self.fingerprint
        return value

    def compose(
        self,
        phase_batches: tuple[PredictionBatch, ...],
    ) -> MixedPhaseForwardPrediction:
        """Compose exactly one prefill batch and one decode batch."""

        if not isinstance(phase_batches, tuple) or any(
            not isinstance(batch, PredictionBatch) for batch in phase_batches
        ):
            raise TypeError("phase_batches must be a tuple of PredictionBatch values")
        phases = tuple(batch.phase for batch in phase_batches)
        if phases != (PredictionPhase.PREFILL, PredictionPhase.DECODE):
            raise ValueError("mixed composition requires exactly prefill then decode phase batches")
        profile_fingerprints = {batch.profile_fingerprint for batch in phase_batches}
        if len(profile_fingerprints) != 1:
            raise ValueError("mixed phase batches must share one predictor profile")
        prefill_batch, decode_batch = phase_batches
        prefill_shape = prefill_batch.shape
        decode_shape = decode_batch.shape
        request_count = prefill_shape.batch_size + decode_shape.batch_size
        duration_ns = (
            self.base_ns
            + self.batch_request_overhead_ns * request_count
            + self.prefill_ns_per_scheduled_token * prefill_shape.total_extend_length
            + self.decode_ns_per_request * decode_shape.batch_size
            + self.decode_ns_per_past_token * sum(decode_shape.past_kv_lengths)
        )
        return MixedPhaseForwardPrediction(
            predicted_forward_duration_ns=duration_ns,
            phase_batches=phase_batches,
            profile_fingerprint=next(iter(profile_fingerprints)),
            composition_rule=self,
        )


@dataclass(frozen=True, slots=True)
class MixedPhaseForwardPrediction:
    """One preliminary joint duration with exact phase-shape provenance."""

    predicted_forward_duration_ns: int
    phase_batches: tuple[PredictionBatch, ...]
    profile_fingerprint: str
    composition_rule: AssumedIntegerMixedPhaseCompositionRule

    def __post_init__(self) -> None:
        _require_positive_int(
            self.predicted_forward_duration_ns,
            "predicted_forward_duration_ns",
        )
        if not isinstance(self.phase_batches, tuple) or any(
            not isinstance(batch, PredictionBatch) for batch in self.phase_batches
        ):
            raise TypeError("phase_batches must be a tuple of PredictionBatch values")
        if tuple(batch.phase for batch in self.phase_batches) != (
            PredictionPhase.PREFILL,
            PredictionPhase.DECODE,
        ):
            raise ValueError("mixed prediction must preserve canonical phase order")
        _require_sha256(self.profile_fingerprint, "profile_fingerprint")
        if any(
            batch.profile_fingerprint != self.profile_fingerprint for batch in self.phase_batches
        ):
            raise ValueError("mixed prediction batches belong to another profile")
        if not isinstance(
            self.composition_rule,
            AssumedIntegerMixedPhaseCompositionRule,
        ):
            raise TypeError("composition_rule must be an AssumedIntegerMixedPhaseCompositionRule")

    def to_dict(self) -> dict[str, object]:
        return {
            "boundary": "gpu_forward_only",
            "prediction_mode": "mixed_phase_joint_composition",
            "predicted_forward_duration_ns": self.predicted_forward_duration_ns,
            "profile_fingerprint": self.profile_fingerprint,
            "phase_shapes": [
                {
                    "phase": batch.phase.value,
                    "batch_fingerprint": batch.fingerprint,
                    "shape": batch.shape.to_dict(),
                }
                for batch in self.phase_batches
            ],
            "composition_rule": self.composition_rule.to_dict(),
            "calibration_status": "not_calibrated",
            "evidence_label": CalibrationEvidenceLabel.PRELIMINARY.value,
            "formal_use_allowed": False,
        }

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())
