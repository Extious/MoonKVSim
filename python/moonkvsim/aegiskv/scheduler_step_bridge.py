"""AegisKV-facing scheduler-step execution boundary.

The experiment harness historically booked one whole request on one exclusive
GPU lane.  This module deliberately exposes a different, reusable boundary:
one source-locked vLLM scheduler step may contain several requests, while the
GPU still executes only one forward step at a time.

The bridge owns no clock, Router authority, KV-protection policy, transfer, or
physical failure operation.  Its GPU-failure fence is a control-plane fence
that returns enough immutable state for an external failure owner to perform
physical HBM loss and route-versioned requeue/recovery.  In particular, it
never relabels a Peer-HBM backup or treats an uncommitted copy as recoverable.

Forward duration is supplied by an explicit whole-step provider.  Every
provider carries a profile binding and evidence classification, so an
uncalibrated formula cannot be serialized as a physical measurement.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from moonkvsim.aegiskv.experiment_hbm_authority import ExperimentHBMAuthority
from moonkvsim.integration.vllm.hbm_block_ledger import (
    HBM_KV_ACTIVE_ACCOUNT,
    HbmBlockLedgerBridge,
)
from moonkvsim.integration.vllm.request import Request, RequestStatus
from moonkvsim.integration.vllm.scheduler import (
    VLLM_SCHEDULE_SYMBOL,
    VLLM_SCHEDULER_SHA256,
    VLLM_SOURCE_COMMIT,
    ContinuousBatchScheduler,
    ScheduledRequest,
    SchedulerOutput,
    SchedulingPhase,
)
from moonkvsim.predictor.schema import PredictionBatchShape, PredictionPhase, PredictionProfile
from moonkvsim.predictor.vllm_adapter import AdaptedSchedulerStep, VLLMSchedulerBatchAdapter

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SchedulerStepBridgeError(RuntimeError):
    """Base error for the Aegis scheduler-step bridge."""


class SchedulerStepBridgeFencedError(SchedulerStepBridgeError):
    """A stale caller attempted to mutate a GPU after its control-plane fence."""


class SchedulerStepPreparationError(SchedulerStepBridgeError):
    """A scheduled mutation could not be bound to a valid duration record."""


class StepDurationEvidenceClass(StrEnum):
    """Evidence boundary attached to one whole scheduler-step duration source."""

    PHYSICAL_MEASUREMENT = "PHYSICAL_MEASUREMENT"
    CALIBRATED_MODEL = "CALIBRATED_MODEL"
    UNCALIBRATED_MODEL = "UNCALIBRATED_MODEL"
    FIXTURE_ONLY = "FIXTURE_ONLY"


@dataclass(frozen=True, slots=True)
class StepDurationProviderEvidence:
    """Profile-bound provenance for one scheduler-step duration provider."""

    provider_name: str
    provider_version: str
    prediction_profile_fingerprint: str
    provenance_sha256: str
    evidence_class: StepDurationEvidenceClass
    physically_measured: bool
    formal_use_allowed: bool

    def __post_init__(self) -> None:
        if not self.provider_name or not self.provider_version:
            raise ValueError("duration provider name and version must be non-empty")
        if _SHA256.fullmatch(self.prediction_profile_fingerprint) is None:
            raise ValueError("duration evidence requires a prediction-profile SHA-256")
        if _SHA256.fullmatch(self.provenance_sha256) is None:
            raise ValueError("duration evidence requires a provenance SHA-256")
        if not isinstance(self.evidence_class, StepDurationEvidenceClass):
            raise TypeError("duration evidence_class has an invalid type")
        if not isinstance(self.physically_measured, bool) or not isinstance(
            self.formal_use_allowed, bool
        ):
            raise TypeError("duration evidence flags must be booleans")
        measured = self.evidence_class is StepDurationEvidenceClass.PHYSICAL_MEASUREMENT
        if self.physically_measured != measured:
            raise ValueError(
                "physically_measured is true exactly for PHYSICAL_MEASUREMENT evidence"
            )
        if self.evidence_class in {
            StepDurationEvidenceClass.UNCALIBRATED_MODEL,
            StepDurationEvidenceClass.FIXTURE_ONLY,
        } and self.formal_use_allowed:
            raise ValueError("uncalibrated or fixture duration evidence cannot allow formal use")

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "prediction_profile_fingerprint": self.prediction_profile_fingerprint,
            "provenance_sha256": self.provenance_sha256,
            "evidence_class": self.evidence_class.value,
            "physically_measured": self.physically_measured,
            "formal_use_allowed": self.formal_use_allowed,
        }


@runtime_checkable
class SchedulerStepDurationProvider(Protocol):
    """Predict one complete (possibly mixed-phase) GPU scheduler step."""

    @property
    def evidence(self) -> StepDurationProviderEvidence: ...

    def predict_step_duration_ns(self, step: AdaptedSchedulerStep) -> int: ...


@dataclass(frozen=True, slots=True)
class SchedulerStepDuration:
    duration_ns: int
    evidence: StepDurationProviderEvidence

    def __post_init__(self) -> None:
        if type(self.duration_ns) is not int or self.duration_ns <= 0:
            raise ValueError("scheduler-step duration must be a positive integer nanosecond value")
        if not isinstance(self.evidence, StepDurationProviderEvidence):
            raise TypeError("scheduler-step duration requires typed provider evidence")

    def to_dict(self) -> dict[str, object]:
        return {"duration_ns": self.duration_ns, "evidence": self.evidence.to_dict()}


@dataclass(frozen=True, slots=True)
class SchedulerExecutionBinding:
    """Router-supplied compatibility identity for one DP scheduler target."""

    target_id: str
    gpu_id: str
    failure_domain_id: str
    kv_abi: str
    kv_layout_id: str
    kv_layout_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "target_id",
            "gpu_id",
            "failure_domain_id",
            "kv_abi",
            "kv_layout_id",
        ):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must be non-empty")
        if _SHA256.fullmatch(self.kv_layout_sha256) is None:
            raise ValueError("kv_layout_sha256 must be a SHA-256")

    def to_dict(self) -> dict[str, object]:
        return {
            "target_id": self.target_id,
            "gpu_id": self.gpu_id,
            "failure_domain_id": self.failure_domain_id,
            "kv_abi": self.kv_abi,
            "kv_layout_id": self.kv_layout_id,
            "kv_layout_sha256": self.kv_layout_sha256,
        }


@dataclass(frozen=True, slots=True)
class SchedulerStepPhaseShape:
    phase: PredictionPhase
    request_ids: tuple[str, ...]
    batch_fingerprint: str
    shape: PredictionBatchShape

    def __post_init__(self) -> None:
        if not self.request_ids or len(set(self.request_ids)) != len(self.request_ids):
            raise ValueError("phase shape requires unique request IDs")
        if _SHA256.fullmatch(self.batch_fingerprint) is None:
            raise ValueError("phase shape requires a batch SHA-256")
        if not isinstance(self.shape, PredictionBatchShape):
            raise TypeError("phase shape requires a PredictionBatchShape")

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "request_ids": list(self.request_ids),
            "batch_fingerprint": self.batch_fingerprint,
            "shape": self.shape.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SchedulerStepParticipant:
    request_id: str
    route_version: int
    phase: SchedulingPhase
    origin: str
    num_scheduled_tokens: int
    num_computed_tokens_before: int
    num_computed_tokens_after: int
    new_block_ids: tuple[int, ...]
    resident_block_ids: tuple[int, ...]
    local_cache_hit_tokens: int
    produces_output: bool
    output_index: int | None
    recompute: bool
    chunked: bool

    def __post_init__(self) -> None:
        if not self.request_id or self.route_version < 0:
            raise ValueError("participant request identity is invalid")
        if self.num_scheduled_tokens <= 0:
            raise ValueError("participant must schedule positive tokens")
        if self.num_computed_tokens_after <= self.num_computed_tokens_before:
            raise ValueError("participant computed-token counters did not advance")
        if self.produces_output != (self.output_index is not None):
            raise ValueError("participant output flag and index disagree")

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "route_version": self.route_version,
            "phase": self.phase.value,
            "origin": self.origin,
            "num_scheduled_tokens": self.num_scheduled_tokens,
            "num_computed_tokens_before": self.num_computed_tokens_before,
            "num_computed_tokens_after": self.num_computed_tokens_after,
            "new_block_ids": list(self.new_block_ids),
            "resident_block_ids": list(self.resident_block_ids),
            "local_cache_hit_tokens": self.local_cache_hit_tokens,
            "produces_output": self.produces_output,
            "output_index": self.output_index,
            "recompute": self.recompute,
            "chunked": self.chunked,
        }


@dataclass(frozen=True, slots=True)
class ResidentPrimarySnapshot:
    request_ids: tuple[str, ...]
    unique_block_ids: tuple[int, ...]
    resident_primary_bytes: int
    bytes_by_hbm_resource: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if len(set(self.request_ids)) != len(self.request_ids):
            raise ValueError("resident request IDs must be unique")
        if tuple(sorted(set(self.unique_block_ids))) != self.unique_block_ids:
            raise ValueError("resident block IDs must be sorted and unique")
        if self.resident_primary_bytes < 0:
            raise ValueError("resident primary bytes must be non-negative")
        if self.resident_primary_bytes != sum(value for _, value in self.bytes_by_hbm_resource):
            raise ValueError("per-resource active bytes do not conserve resident primary bytes")

    @property
    def resident_primary_request_count(self) -> int:
        return len(self.request_ids)

    @property
    def resident_primary_block_count(self) -> int:
        return len(self.unique_block_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "resident_primary_request_count": self.resident_primary_request_count,
            "resident_primary_block_count": self.resident_primary_block_count,
            "resident_primary_bytes": self.resident_primary_bytes,
            "request_ids": list(self.request_ids),
            "unique_block_ids": list(self.unique_block_ids),
            "bytes_by_hbm_resource": {
                resource_id: value for resource_id, value in self.bytes_by_hbm_resource
            },
        }


@dataclass(frozen=True, slots=True)
class AegisSchedulerStep:
    step_id: str
    participants: tuple[SchedulerStepParticipant, ...]
    phase_shapes: tuple[SchedulerStepPhaseShape, ...]
    preempted_request_ids: tuple[str, ...]
    preemption_details: tuple[dict[str, object], ...]
    scheduler_output_fingerprint: str
    duration: SchedulerStepDuration | None
    residency_before: ResidentPrimarySnapshot
    residency_after_schedule: ResidentPrimarySnapshot

    def __post_init__(self) -> None:
        participant_ids = tuple(item.request_id for item in self.participants)
        if len(set(participant_ids)) != len(participant_ids):
            raise ValueError("scheduler-step participants must be unique")
        shaped_ids = {
            request_id
            for phase_shape in self.phase_shapes
            for request_id in phase_shape.request_ids
        }
        if shaped_ids != set(participant_ids):
            raise ValueError("phase shapes must cover scheduler-step participants exactly")
        if bool(self.participants) != (self.duration is not None):
            raise ValueError("only a forward scheduler step has a duration")
        if _SHA256.fullmatch(self.scheduler_output_fingerprint) is None:
            raise ValueError("scheduler output fingerprint must be a SHA-256")

    @property
    def has_forward(self) -> bool:
        return bool(self.participants)

    @property
    def is_mixed_phase(self) -> bool:
        return len(self.phase_shapes) > 1

    def to_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "has_forward": self.has_forward,
            "is_mixed_phase": self.is_mixed_phase,
            "participants": [item.to_dict() for item in self.participants],
            "phase_shapes": [item.to_dict() for item in self.phase_shapes],
            "preempted_request_ids": list(self.preempted_request_ids),
            "preemption_details": [dict(item) for item in self.preemption_details],
            "scheduler_output_fingerprint": self.scheduler_output_fingerprint,
            "duration": None if self.duration is None else self.duration.to_dict(),
            "residency_before": self.residency_before.to_dict(),
            "residency_after_schedule": self.residency_after_schedule.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SchedulerStepCompletion:
    step_id: str
    output_positions: tuple[tuple[str, int], ...]
    terminal_output_request_ids: tuple[str, ...]
    residency_after_completion: ResidentPrimarySnapshot

    def to_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "output_positions": dict(self.output_positions),
            "terminal_output_request_ids": list(self.terminal_output_request_ids),
            "residency_after_completion": self.residency_after_completion.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class FailureRequeueRequestSnapshot:
    request_id: str
    route_version: int
    scheduler_status: RequestStatus
    queue_kind: str
    queue_position: int
    prompt_tokens: int
    max_output_tokens: int
    arrival_ns: int
    priority: int
    max_model_len_tokens: int
    prompt_token_ids: tuple[int, ...] | None
    observed_num_computed_tokens: int
    last_completed_model_tokens: int
    requeue_num_computed_tokens: int | None
    recovery_prefix_selection_required: bool
    committed_output_tokens: int
    num_preemptions: int
    lost_resident_block_ids: tuple[int, ...]
    in_flight_step_id: str | None
    in_flight_phase: SchedulingPhase | None
    in_flight_num_scheduled_tokens: int
    in_flight_would_produce_output: bool

    def __post_init__(self) -> None:
        if self.queue_kind not in {"RUNNING", "WAITING"} or self.queue_position < 0:
            raise ValueError("failure snapshot queue identity is invalid")
        if not 0 <= self.last_completed_model_tokens <= self.observed_num_computed_tokens:
            raise ValueError("failure snapshot completed-token counters are invalid")
        if self.requeue_num_computed_tokens is not None and (
            self.requeue_num_computed_tokens < 0
            or self.requeue_num_computed_tokens > self.last_completed_model_tokens
        ):
            raise ValueError("failure snapshot requeue counters are invalid")
        if not isinstance(self.recovery_prefix_selection_required, bool):
            raise TypeError("recovery-prefix selection flag must be boolean")
        if self.recovery_prefix_selection_required != (
            self.requeue_num_computed_tokens is None
        ):
            raise ValueError(
                "unresolved requeue progress must exactly match recovery-prefix selection"
            )
        if self.committed_output_tokens < 0:
            raise ValueError("committed output position must be non-negative")
        if (self.in_flight_step_id is None) != (self.in_flight_phase is None):
            raise ValueError("in-flight step identity and phase must be present together")
        if self.in_flight_step_id is None and (
            self.in_flight_num_scheduled_tokens != 0 or self.in_flight_would_produce_output
        ):
            raise ValueError("non-participant failure state cannot describe in-flight work")

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "route_version": self.route_version,
            "scheduler_status": self.scheduler_status.name,
            "queue_kind": self.queue_kind,
            "queue_position": self.queue_position,
            "prompt_tokens": self.prompt_tokens,
            "max_output_tokens": self.max_output_tokens,
            "arrival_ns": self.arrival_ns,
            "priority": self.priority,
            "max_model_len_tokens": self.max_model_len_tokens,
            "prompt_token_ids": (
                None if self.prompt_token_ids is None else list(self.prompt_token_ids)
            ),
            "observed_num_computed_tokens": self.observed_num_computed_tokens,
            "last_completed_model_tokens": self.last_completed_model_tokens,
            "requeue_num_computed_tokens": self.requeue_num_computed_tokens,
            "recovery_prefix_selection_required": (
                self.recovery_prefix_selection_required
            ),
            "committed_output_tokens": self.committed_output_tokens,
            "num_preemptions": self.num_preemptions,
            "lost_resident_block_ids": list(self.lost_resident_block_ids),
            "in_flight_step_id": self.in_flight_step_id,
            "in_flight_phase": (
                None if self.in_flight_phase is None else self.in_flight_phase.value
            ),
            "in_flight_num_scheduled_tokens": self.in_flight_num_scheduled_tokens,
            "in_flight_would_produce_output": self.in_flight_would_produce_output,
        }


@dataclass(frozen=True, slots=True)
class PendingAdmissionFailureSnapshot:
    """Route-bound admission canceled before it entered the scheduler."""

    request_id: str
    event_id: str
    cause: str
    route_version: int
    target_id: str
    ready_ns: int
    restored_tokens: int
    router_committed_output_tokens: int
    silent_replay_target: int

    def __post_init__(self) -> None:
        if not self.request_id or not self.event_id or not self.cause or not self.target_id:
            raise ValueError("pending admission failure identity is invalid")
        if self.route_version < 0 or self.ready_ns < 0 or self.restored_tokens < 0:
            raise ValueError("pending admission failure counters are invalid")
        if (
            self.router_committed_output_tokens < 0
            or self.silent_replay_target < 0
        ):
            raise ValueError("pending admission output counters are invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "event_id": self.event_id,
            "cause": self.cause,
            "route_version": self.route_version,
            "target_id": self.target_id,
            "ready_ns": self.ready_ns,
            "restored_tokens": self.restored_tokens,
            "router_committed_output_tokens": self.router_committed_output_tokens,
            "silent_replay_target": self.silent_replay_target,
        }


@dataclass(frozen=True, slots=True)
class GPUFailureFenceSnapshot:
    bridge_id: str
    execution_binding: SchedulerExecutionBinding
    prediction_profile: PredictionProfile
    observed_at_ns: int
    reason: str
    active_step_id: str | None
    residency_before_physical_loss: ResidentPrimarySnapshot
    running_request_ids: tuple[str, ...]
    waiting_request_ids: tuple[str, ...]
    requests: tuple[FailureRequeueRequestSnapshot, ...]
    pending_admissions: tuple[PendingAdmissionFailureSnapshot, ...] = ()
    physical_hbm_failure_applied: bool = False

    def __post_init__(self) -> None:
        if not self.bridge_id or self.observed_at_ns < 0 or not self.reason:
            raise ValueError("GPU failure fence identity is invalid")
        if not isinstance(self.execution_binding, SchedulerExecutionBinding):
            raise TypeError("GPU failure fence requires an execution binding")
        if not isinstance(self.prediction_profile, PredictionProfile):
            raise TypeError("GPU failure fence requires a prediction profile")
        if self.physical_hbm_failure_applied:
            raise ValueError("the scheduler bridge cannot claim physical HBM failure execution")
        ordered_ids = self.running_request_ids + self.waiting_request_ids
        if tuple(item.request_id for item in self.requests) != ordered_ids:
            raise ValueError("failure requeue snapshots must preserve scheduler queue order")
        if len(set(self.pending_admission_request_ids)) != len(self.pending_admissions):
            raise ValueError("pending failure-fenced admissions must be unique")
        if set(self.pending_admission_request_ids) & set(ordered_ids):
            raise ValueError("pending admissions cannot also be scheduler residents")

    @property
    def pending_admission_request_ids(self) -> tuple[str, ...]:
        return tuple(item.request_id for item in self.pending_admissions)

    def to_dict(self) -> dict[str, object]:
        return {
            "bridge_id": self.bridge_id,
            "execution_binding": self.execution_binding.to_dict(),
            "prediction_profile": self.prediction_profile.to_dict(),
            "scheduler_source": {
                "commit": VLLM_SOURCE_COMMIT,
                "sha256": VLLM_SCHEDULER_SHA256,
                "symbol": VLLM_SCHEDULE_SYMBOL,
            },
            "observed_at_ns": self.observed_at_ns,
            "reason": self.reason,
            "active_step_id": self.active_step_id,
            "residency_before_physical_loss": self.residency_before_physical_loss.to_dict(),
            "running_request_ids": list(self.running_request_ids),
            "waiting_request_ids": list(self.waiting_request_ids),
            "requests": [item.to_dict() for item in self.requests],
            "pending_admission_request_ids": list(
                self.pending_admission_request_ids
            ),
            "pending_admissions": [item.to_dict() for item in self.pending_admissions],
            "physical_hbm_failure_applied": self.physical_hbm_failure_applied,
            "boundary": (
                "CONTROL_PLANE_FENCE_ONLY_EXTERNAL_OWNER_MUST_APPLY_PHYSICAL_HBM_LOSS_"
                "AND_ROUTE_VERSIONED_REQUEUE"
            ),
        }


class AegisSchedulerStepBridge:
    """Compose scheduler, shape adapter, duration provider, and HBM residency."""

    def __init__(
        self,
        *,
        bridge_id: str,
        execution_binding: SchedulerExecutionBinding,
        scheduler: ContinuousBatchScheduler,
        prediction_profile: PredictionProfile,
        duration_provider: SchedulerStepDurationProvider,
        adapter: VLLMSchedulerBatchAdapter | None = None,
    ) -> None:
        if not bridge_id:
            raise ValueError("bridge_id must be non-empty")
        if not isinstance(execution_binding, SchedulerExecutionBinding):
            raise TypeError("execution_binding must be a SchedulerExecutionBinding")
        if not isinstance(scheduler, ContinuousBatchScheduler):
            raise TypeError("scheduler must be a ContinuousBatchScheduler")
        if scheduler.running_request_ids or scheduler.waiting_request_ids:
            raise ValueError("scheduler-step bridge requires an initially empty scheduler")
        observer = scheduler.block_lifecycle_observer
        if not isinstance(observer, (HbmBlockLedgerBridge, ExperimentHBMAuthority)):
            raise TypeError(
                "scheduler-step bridge requires a physical HBM ownership observer"
            )
        if not isinstance(prediction_profile, PredictionProfile):
            raise TypeError("prediction_profile must be a PredictionProfile")
        if not isinstance(duration_provider, SchedulerStepDurationProvider):
            raise TypeError("duration_provider does not satisfy SchedulerStepDurationProvider")
        if duration_provider.evidence.prediction_profile_fingerprint != (
            prediction_profile.fingerprint
        ):
            raise ValueError("duration provider evidence belongs to another prediction profile")
        self.bridge_id = bridge_id
        self.execution_binding = execution_binding
        self.scheduler = scheduler
        self.prediction_profile = prediction_profile
        self.duration_provider = duration_provider
        self.adapter = adapter or VLLMSchedulerBatchAdapter()
        self.hbm_observer = observer
        self._requests: dict[str, Request] = {}
        self._step_sequence = 0
        self._active_step: AegisSchedulerStep | None = None
        self._in_flight_step_id: str | None = None
        self._in_flight_participants: tuple[SchedulerStepParticipant, ...] = ()
        self._fenced = False
        self._fence_reason: str | None = None
        if self.scheduler.eager_audit:
            self.scheduler.audit()

    @property
    def fenced(self) -> bool:
        return self._fenced

    @property
    def active_step(self) -> AegisSchedulerStep | None:
        return self._active_step

    def request_progress_snapshot(self) -> tuple[tuple[str, int, int], ...]:
        """Return scheduler-visible progress in stable queue order."""

        ordered_ids = (
            self.scheduler.running_request_ids + self.scheduler.waiting_request_ids
        )
        return tuple(
            (
                request_id,
                self._requests[request_id].num_computed_tokens,
                self._requests[request_id].num_tokens,
            )
            for request_id in ordered_ids
        )

    def continue_step_sequence_after(
        self, predecessor: AegisSchedulerStepBridge
    ) -> None:
        """Continue one physical target's step namespace after repair.

        A repaired GPU receives a fresh scheduler and bridge, but the emitted
        scheduler-step IDs belong to the complete driver run.  Preserve the
        predecessor's high-water mark so a repair cannot restart that target's
        IDs at one.
        """

        if not isinstance(predecessor, AegisSchedulerStepBridge):
            raise TypeError("step-sequence predecessor must be a scheduler bridge")
        if self.bridge_id != predecessor.bridge_id or (
            self.execution_binding != predecessor.execution_binding
        ):
            raise SchedulerStepBridgeError(
                "step-sequence continuation requires the same bridge identity"
            )
        if not predecessor.fenced:
            raise SchedulerStepBridgeError(
                "step-sequence predecessor must be failure-fenced"
            )
        if (
            self._step_sequence != 0
            or self._requests
            or self._active_step is not None
            or self._in_flight_step_id is not None
            or self.scheduler.running_request_ids
            or self.scheduler.waiting_request_ids
        ):
            raise SchedulerStepBridgeError(
                "step-sequence continuation requires a fresh empty bridge"
            )
        self._step_sequence = predecessor._step_sequence

    def admit_request(self, request: Request) -> None:
        self._require_mutable()
        if self._active_step is not None:
            # Queue admission while a physical forward is active is safe: the
            # request cannot enter that already-frozen participant set.
            pass
        self.scheduler.add_request(request)
        try:
            self._register_request(request)
        except Exception:
            self.scheduler.rollback_unstarted_request(request.request_id)
            raise

    def prioritize_waiting_recovery(self, request_id: str) -> None:
        """Give one externally requeued failure owner bounded admission priority."""

        self._require_mutable()
        if request_id not in self._requests:
            raise KeyError(f"unknown bridge request: {request_id}")
        self.scheduler.prioritize_waiting_recovery(request_id)

    def admit_restored_request(self, request: Request, *, restored_tokens: int) -> None:
        """Queue a proven remote prefix behind ordinary scheduler admission.

        A restored prefix may already own physical HBM (or have completed its
        Store load) while the scheduler's finite logical page IDs are still
        referenced by currently running requests.  Directly forcing the whole
        prefix into ``RUNNING`` therefore creates a false two-layer capacity
        failure.  Mirror the connector path instead: retain FCFS order, publish
        the completed remote prefix, and let ``schedule()`` allocate logical
        pages only when both the block pool and physical authority can admit
        them.  With free capacity this is observationally equivalent to direct
        admission in the immediately following scheduler step.
        """

        self._require_mutable()
        self.scheduler.add_request(request)
        try:
            self.scheduler.mark_waiting_for_remote_kv(request.request_id)
            self.scheduler.restore_waiting_request_prefix(
                request.request_id,
                restored_tokens=restored_tokens,
            )
        except Exception:
            self.scheduler.rollback_unstarted_request(request.request_id)
            raise
        try:
            self._register_request(request)
        except Exception:
            self.scheduler.rollback_unstarted_request(request.request_id)
            raise

    def rollback_unstarted_admission(self, request_id: str) -> None:
        """Undo one bridge admission which has not entered a forward step."""

        self._require_mutable()
        if request_id not in self._requests:
            raise KeyError(f"unknown bridge request: {request_id}")
        self.scheduler.rollback_unstarted_request(request_id)
        del self._requests[request_id]

    def resident_primary_snapshot(self, *, audit: bool = True) -> ResidentPrimarySnapshot:
        if audit and self.scheduler.eager_audit:
            self.scheduler.audit()
        request_ids = self.scheduler.running_request_ids
        if set(request_ids) != set(self.hbm_observer.active_request_ids):
            raise SchedulerStepBridgeError(
                "scheduler resident requests and physical ACTIVE ownership diverged"
            )
        block_ids = tuple(
            sorted(
                {
                    block_id
                    for request_id in request_ids
                    for block_id in self.scheduler.request_block_ids(request_id)
                }
            )
        )
        bytes_by_resource = tuple(
            (
                resource_id,
                ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT),
            )
            for resource_id, ledger in sorted(self.hbm_observer.ledgers.items())
        )
        return ResidentPrimarySnapshot(
            request_ids=request_ids,
            unique_block_ids=block_ids,
            resident_primary_bytes=sum(value for _, value in bytes_by_resource),
            bytes_by_hbm_resource=bytes_by_resource,
        )

    def start_step(self) -> AegisSchedulerStep:
        """Mutate one scheduler step and bind any forward to explicit duration evidence."""

        self._require_mutable()
        if self._active_step is not None or self._in_flight_step_id is not None:
            raise SchedulerStepBridgeError("one GPU cannot overlap two scheduler steps")
        residency_before = self.resident_primary_snapshot()
        self._step_sequence += 1
        step_id = f"{self.bridge_id}:scheduler-step:{self._step_sequence:08d}"
        output = self.scheduler.schedule()
        adapted = self.adapter.adapt(
            output,
            requests=self._requests,
            profile=self.prediction_profile,
        )
        participants = self._participants(output)
        self._in_flight_step_id = step_id if participants else None
        self._in_flight_participants = participants
        phase_shapes = tuple(
            SchedulerStepPhaseShape(
                phase=phase_batch.phase,
                request_ids=phase_batch.request_ids,
                batch_fingerprint=phase_batch.batch.fingerprint,
                shape=phase_batch.batch.shape,
            )
            for phase_batch in adapted.phase_batches
        )
        duration: SchedulerStepDuration | None = None
        if participants:
            try:
                duration_ns = self.duration_provider.predict_step_duration_ns(adapted)
                duration = SchedulerStepDuration(
                    duration_ns=duration_ns,
                    evidence=self.duration_provider.evidence,
                )
            except Exception as error:
                self._fenced = True
                self._fence_reason = f"STEP_DURATION_PREPARATION_FAILED:{type(error).__name__}"
                raise SchedulerStepPreparationError(
                    "duration provider failed after the scheduler mutation; bridge fenced"
                ) from error
        plan = AegisSchedulerStep(
            step_id=step_id,
            participants=participants,
            phase_shapes=phase_shapes,
            preempted_request_ids=output.preempted_req_ids,
            preemption_details=output.preemption_details,
            scheduler_output_fingerprint=adapted.scheduler_output_fingerprint,
            duration=duration,
            residency_before=residency_before,
            residency_after_schedule=self.resident_primary_snapshot(audit=False),
        )
        if plan.has_forward:
            self._active_step = plan
        else:
            self._in_flight_participants = ()
        return plan

    def complete_step(self, step_id: str) -> SchedulerStepCompletion:
        """Commit sampled outputs; terminal KV remains resident until explicit retirement."""

        self._require_mutable()
        plan = self._active_step
        if plan is None or plan.step_id != step_id:
            raise SchedulerStepBridgeError("completion does not own the active scheduler step")
        output_positions: list[tuple[str, int]] = []
        terminal_ids: list[str] = []
        for participant in plan.participants:
            request = self._requests[participant.request_id]
            if participant.produces_output:
                terminal = request.num_output_tokens + 1 == request.max_output_tokens
                self.scheduler.append_output_tokens(
                    participant.request_id,
                    1,
                    terminal=terminal,
                    audit=False,
                )
                if terminal:
                    terminal_ids.append(participant.request_id)
            output_positions.append((participant.request_id, request.num_output_tokens))
        if self.scheduler.eager_audit:
            self.scheduler.audit()
        self._active_step = None
        self._in_flight_step_id = None
        self._in_flight_participants = ()
        return SchedulerStepCompletion(
            step_id=step_id,
            output_positions=tuple(output_positions),
            terminal_output_request_ids=tuple(terminal_ids),
            residency_after_completion=self.resident_primary_snapshot(audit=False),
        )

    def retire_request(
        self,
        request_id: str,
        *,
        status: RequestStatus = RequestStatus.FINISHED_STOPPED,
    ) -> ResidentPrimarySnapshot:
        """Release primary HBM after output/protection completion policy permits cleanup."""

        self._require_mutable()
        if self._active_step is not None:
            raise SchedulerStepBridgeError("cannot retire a request during a GPU forward step")
        if request_id not in self._requests:
            raise KeyError(f"unknown bridge request: {request_id}")
        self.scheduler.finish_request(request_id, status)
        del self._requests[request_id]
        return self.resident_primary_snapshot()

    def failure_state_snapshot(
        self,
        *,
        observed_at_ns: int,
        reason: str,
    ) -> GPUFailureFenceSnapshot:
        """Return immutable pre-loss state without claiming physical HBM failure."""

        if type(observed_at_ns) is not int or observed_at_ns < 0 or not reason:
            raise ValueError("failure observation requires a non-negative time and reason")
        running = self.scheduler.running_request_ids
        waiting = self.scheduler.waiting_request_ids
        participant_by_id = {
            item.request_id: item for item in self._in_flight_participants
        }
        snapshots: list[FailureRequeueRequestSnapshot] = []
        for queue_kind, request_ids in (("RUNNING", running), ("WAITING", waiting)):
            for position, request_id in enumerate(request_ids):
                request = self._requests[request_id]
                participant = participant_by_id.get(request_id)
                lost_block_ids = self.scheduler.request_block_ids(request_id)
                last_completed_tokens = (
                    request.num_computed_tokens
                    if participant is None
                    else participant.num_computed_tokens_before
                )
                recovery_selection_required = bool(
                    lost_block_ids or request.num_output_tokens > 0
                )
                snapshots.append(
                    FailureRequeueRequestSnapshot(
                        request_id=request_id,
                        route_version=request.route_version,
                        scheduler_status=request.status,
                        queue_kind=queue_kind,
                        queue_position=position,
                        prompt_tokens=request.prompt_tokens,
                        max_output_tokens=request.max_output_tokens,
                        arrival_ns=request.arrival_ns,
                        priority=request.priority,
                        max_model_len_tokens=request.max_model_len_tokens,
                        prompt_token_ids=request.prompt_token_ids,
                        observed_num_computed_tokens=request.num_computed_tokens,
                        last_completed_model_tokens=last_completed_tokens,
                        requeue_num_computed_tokens=(
                            None if recovery_selection_required else 0
                        ),
                        recovery_prefix_selection_required=recovery_selection_required,
                        committed_output_tokens=request.num_output_tokens,
                        num_preemptions=request.num_preemptions,
                        lost_resident_block_ids=lost_block_ids,
                        in_flight_step_id=(
                            None if participant is None else self._in_flight_step_id
                        ),
                        in_flight_phase=None if participant is None else participant.phase,
                        in_flight_num_scheduled_tokens=(
                            0 if participant is None else participant.num_scheduled_tokens
                        ),
                        in_flight_would_produce_output=(
                            False if participant is None else participant.produces_output
                        ),
                    )
                )
        return GPUFailureFenceSnapshot(
            bridge_id=self.bridge_id,
            execution_binding=self.execution_binding,
            prediction_profile=self.prediction_profile,
            observed_at_ns=observed_at_ns,
            reason=reason,
            active_step_id=self._in_flight_step_id,
            residency_before_physical_loss=self.resident_primary_snapshot(),
            running_request_ids=running,
            waiting_request_ids=waiting,
            requests=tuple(snapshots),
        )

    def fence_for_gpu_failure(
        self,
        *,
        observed_at_ns: int,
        reason: str,
    ) -> GPUFailureFenceSnapshot:
        """Fence stale step completion and return the external recovery handoff."""

        if self._fenced:
            raise SchedulerStepBridgeFencedError(
                f"scheduler bridge is already fenced: {self._fence_reason}"
            )
        snapshot = self.failure_state_snapshot(
            observed_at_ns=observed_at_ns,
            reason=reason,
        )
        self._fenced = True
        self._fence_reason = reason
        return snapshot

    def _register_request(self, request: Request) -> None:
        if request.request_id in self._requests:
            raise SchedulerStepBridgeError("bridge request registry duplicated an admission")
        self._requests[request.request_id] = request

    def _require_mutable(self) -> None:
        if self._fenced:
            raise SchedulerStepBridgeFencedError(
                f"scheduler bridge is fenced: {self._fence_reason}"
            )

    def _participants(
        self, output: SchedulerOutput
    ) -> tuple[SchedulerStepParticipant, ...]:
        grouped = (
            output.scheduled_running_reqs
            + output.scheduled_new_reqs
            + output.scheduled_resumed_reqs
        )
        by_id: Mapping[str, ScheduledRequest] = {item.request_id: item for item in grouped}
        if len(by_id) != len(grouped) or set(by_id) != set(output.scheduled_req_ids):
            raise SchedulerStepBridgeError("scheduler output groups are not one-to-one")
        participants: list[SchedulerStepParticipant] = []
        for request_id in output.scheduled_req_ids:
            scheduled = by_id[request_id]
            request = self._requests[request_id]
            produces_output = _scheduled_request_produces_output(scheduled, request)
            participants.append(
                SchedulerStepParticipant(
                    request_id=request_id,
                    route_version=request.route_version,
                    phase=scheduled.phase,
                    origin=scheduled.origin.value,
                    num_scheduled_tokens=scheduled.num_scheduled_tokens,
                    num_computed_tokens_before=scheduled.num_computed_tokens_before,
                    num_computed_tokens_after=scheduled.num_computed_tokens_after,
                    new_block_ids=scheduled.new_block_ids,
                    resident_block_ids=scheduled.block_ids,
                    local_cache_hit_tokens=scheduled.local_cache_hit_tokens,
                    produces_output=produces_output,
                    output_index=request.num_output_tokens if produces_output else None,
                    recompute=scheduled.recompute,
                    chunked=scheduled.chunked,
                )
            )
        return tuple(participants)


def _scheduled_request_produces_output(item: ScheduledRequest, request: Request) -> bool:
    """Validate ordinary decoder-only output materialization for one participant."""

    if request.num_computed_tokens != item.num_computed_tokens_after:
        raise SchedulerStepBridgeError("scheduled counters do not match live request state")
    remaining_before = request.num_tokens - item.num_computed_tokens_before
    if remaining_before <= 0:
        raise SchedulerStepBridgeError("scheduled request had no materialized work")
    if item.chunked != (item.num_scheduled_tokens < remaining_before):
        raise SchedulerStepBridgeError("scheduled chunked flag disagrees with request counters")
    if item.phase is SchedulingPhase.PREFILL:
        if item.num_computed_tokens_before >= request.prompt_tokens:
            raise SchedulerStepBridgeError("prefill begins beyond the prompt boundary")
        if item.num_computed_tokens_after > request.prompt_tokens:
            raise SchedulerStepBridgeError("prefill crosses the prompt boundary")
        if item.chunked:
            if item.num_computed_tokens_after >= request.prompt_tokens:
                raise SchedulerStepBridgeError("chunked prefill cannot sample output")
            return False
        if item.num_computed_tokens_after != request.prompt_tokens:
            raise SchedulerStepBridgeError("terminal prefill did not compute the prompt")
        return True
    if item.phase is SchedulingPhase.DECODE:
        if (
            item.num_computed_tokens_before < request.prompt_tokens
            or item.num_scheduled_tokens != 1
            or item.chunked
        ):
            raise SchedulerStepBridgeError("decode is not ordinary one-token decode")
        return True
    raise SchedulerStepBridgeError("unsupported scheduler phase")


__all__ = [
    "AegisSchedulerStep",
    "AegisSchedulerStepBridge",
    "FailureRequeueRequestSnapshot",
    "GPUFailureFenceSnapshot",
    "PendingAdmissionFailureSnapshot",
    "ResidentPrimarySnapshot",
    "SchedulerExecutionBinding",
    "SchedulerStepBridgeError",
    "SchedulerStepBridgeFencedError",
    "SchedulerStepCompletion",
    "SchedulerStepDuration",
    "SchedulerStepDurationProvider",
    "SchedulerStepParticipant",
    "SchedulerStepPhaseShape",
    "SchedulerStepPreparationError",
    "StepDurationEvidenceClass",
    "StepDurationProviderEvidence",
]
