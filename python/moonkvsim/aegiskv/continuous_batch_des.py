"""Executable multi-GPU continuous-batching DES for AegisKV experiments.

This module drives :class:`AegisSchedulerStepBridge` with one active forward
per GPU.  It is intentionally separate from the experiment harness: callers
submit request releases and GPU failures, then consume immutable request,
step, and failure records.

The included duration provider consumes per-request durations observed in an
ideal trace, but its token-share and batch-composition rule is a model.  Its
evidence is therefore always ``UNCALIBRATED_MODEL`` and never a physical
measurement.  GPU failure recovery is likewise conservative: lost HBM is not
reused.  An external recovery owner may prove a block-aligned prefix resident
on the selected target; the scheduler adopts only that prefix, recomputes the
remaining prompt suffix, and crosses already committed Router output positions
by silent replay before any new output is committed.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum

from moonkvsim.aegiskv.scheduler_step_bridge import (
    AegisSchedulerStep,
    AegisSchedulerStepBridge,
    GPUFailureFenceSnapshot,
    PendingAdmissionFailureSnapshot,
    ResidentPrimarySnapshot,
    SchedulerStepCompletion,
    StepDurationEvidenceClass,
    StepDurationProviderEvidence,
)
from moonkvsim.common.hash import sha256_json
from moonkvsim.integration.vllm.request import Request
from moonkvsim.predictor.schema import PredictionProfile
from moonkvsim.predictor.vllm_adapter import AdaptedSchedulerStep
from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.simulation.global_des import GlobalDES

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContinuousBatchDESError(RuntimeError):
    """The continuous-batching DES state no longer has one interpretation."""


@dataclass(frozen=True, slots=True)
class ObservedIdealRequestDuration:
    """One request's observed ideal-trace total duration and token extent."""

    request_id: str
    prompt_tokens: int
    max_output_tokens: int
    observed_ideal_duration_ns: int

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id must be non-empty")
        if type(self.prompt_tokens) is not int or self.prompt_tokens <= 0:
            raise ValueError("prompt_tokens must be a positive integer")
        if type(self.max_output_tokens) is not int or self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be a positive integer")
        if (
            type(self.observed_ideal_duration_ns) is not int
            or self.observed_ideal_duration_ns <= 0
        ):
            raise ValueError("observed_ideal_duration_ns must be a positive integer")

    @property
    def scheduler_work_tokens(self) -> int:
        # The terminal prompt forward produces output 1.  Each subsequent
        # output materializes one decode token for a later forward.
        return self.prompt_tokens + self.max_output_tokens - 1

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "prompt_tokens": self.prompt_tokens,
            "max_output_tokens": self.max_output_tokens,
            "observed_ideal_duration_ns": self.observed_ideal_duration_ns,
            "scheduler_work_tokens": self.scheduler_work_tokens,
        }


class ObservedIdealTraceDurationProvider:
    """Uncalibrated token-share duration model over observed ideal traces.

    For participant ``i``, the modeled work share is

    ``ceil(observed_duration_i * scheduled_tokens_i / total_work_tokens_i)``.

    A shared GPU step takes the maximum participant share.  This deterministic
    ideal-parallel rule exposes concurrency to the DES without pretending to
    model real batch-size, phase-mixing, kernel, or interference effects.
    """

    PROVIDER_NAME = "observed-ideal-trace-token-share"
    PROVIDER_VERSION = "v1-modeled-uncalibrated"
    COMPOSITION_RULE = "ceil_per_request_token_share_then_max"

    def __init__(
        self,
        *,
        prediction_profile: PredictionProfile,
        trace_provenance_sha256: str,
    ) -> None:
        if not isinstance(prediction_profile, PredictionProfile):
            raise TypeError("prediction_profile must be a PredictionProfile")
        if _SHA256.fullmatch(trace_provenance_sha256) is None:
            raise ValueError("trace_provenance_sha256 must be a lowercase SHA-256")
        self.prediction_profile = prediction_profile
        self.trace_provenance_sha256 = trace_provenance_sha256
        self._requests: dict[str, ObservedIdealRequestDuration] = {}

    @property
    def evidence(self) -> StepDurationProviderEvidence:
        return StepDurationProviderEvidence(
            provider_name=self.PROVIDER_NAME,
            provider_version=self.PROVIDER_VERSION,
            prediction_profile_fingerprint=self.prediction_profile.fingerprint,
            provenance_sha256=sha256_json(
                {
                    "trace_provenance_sha256": self.trace_provenance_sha256,
                    "composition_rule": self.COMPOSITION_RULE,
                    "provider_version": self.PROVIDER_VERSION,
                }
            ),
            evidence_class=StepDurationEvidenceClass.UNCALIBRATED_MODEL,
            physically_measured=False,
            formal_use_allowed=False,
        )

    def register_request(self, request: ObservedIdealRequestDuration) -> None:
        if not isinstance(request, ObservedIdealRequestDuration):
            raise TypeError("request must be an ObservedIdealRequestDuration")
        existing = self._requests.get(request.request_id)
        if existing is not None and existing != request:
            raise ValueError(f"conflicting ideal-trace duration: {request.request_id}")
        self._requests[request.request_id] = request

    def predict_step_duration_ns(self, step: AdaptedSchedulerStep) -> int:
        if not isinstance(step, AdaptedSchedulerStep) or not step.has_forward:
            raise ValueError("duration provider requires a non-empty scheduler step")
        shares: list[int] = []
        for phase_batch in step.phase_batches:
            for request_id, prediction_request in zip(
                phase_batch.request_ids,
                phase_batch.batch.requests,
                strict=True,
            ):
                try:
                    observed = self._requests[request_id]
                except KeyError as error:
                    raise KeyError(
                        f"missing observed ideal-trace duration: {request_id}"
                    ) from error
                numerator = (
                    observed.observed_ideal_duration_ns
                    * prediction_request.extend_length
                )
                shares.append(
                    max(
                        1,
                        (numerator + observed.scheduler_work_tokens - 1)
                        // observed.scheduler_work_tokens,
                    )
                )
        return max(shares)


@dataclass(frozen=True, slots=True)
class ContinuousBatchRequestSpec:
    request_id: str
    release_ns: int
    prompt_tokens: int
    max_output_tokens: int
    observed_ideal_duration_ns: int
    initial_target_id: str | None = None
    priority: int = 0
    max_model_len_tokens: int = 131_072
    prompt_token_ids: tuple[int, ...] | None = None
    initial_restored_tokens: int = 0
    route_bound_before_admission: bool = False

    def __post_init__(self) -> None:
        ObservedIdealRequestDuration(
            request_id=self.request_id,
            prompt_tokens=self.prompt_tokens,
            max_output_tokens=self.max_output_tokens,
            observed_ideal_duration_ns=self.observed_ideal_duration_ns,
        )
        if type(self.release_ns) is not int or self.release_ns < 0:
            raise ValueError("release_ns must be a non-negative integer")
        if self.prompt_tokens + self.max_output_tokens > self.max_model_len_tokens:
            raise ValueError("request exceeds max_model_len_tokens")
        if self.prompt_token_ids is not None and len(self.prompt_token_ids) != (
            self.prompt_tokens
        ):
            raise ValueError("prompt_token_ids length must equal prompt_tokens")
        if (
            type(self.initial_restored_tokens) is not int
            or self.initial_restored_tokens < 0
            or self.initial_restored_tokens > self.prompt_tokens
        ):
            raise ValueError("initial_restored_tokens must be within the prompt")
        if type(self.route_bound_before_admission) is not bool:
            raise TypeError("route_bound_before_admission must be bool")

    @property
    def observed_duration(self) -> ObservedIdealRequestDuration:
        return ObservedIdealRequestDuration(
            request_id=self.request_id,
            prompt_tokens=self.prompt_tokens,
            max_output_tokens=self.max_output_tokens,
            observed_ideal_duration_ns=self.observed_ideal_duration_ns,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "release_ns": self.release_ns,
            "prompt_tokens": self.prompt_tokens,
            "max_output_tokens": self.max_output_tokens,
            "observed_ideal_duration_ns": self.observed_ideal_duration_ns,
            "initial_target_id": self.initial_target_id,
            "priority": self.priority,
            "max_model_len_tokens": self.max_model_len_tokens,
            "prompt_token_ids": (
                None if self.prompt_token_ids is None else list(self.prompt_token_ids)
            ),
            "initial_restored_tokens": self.initial_restored_tokens,
            "route_bound_before_admission": self.route_bound_before_admission,
        }


@dataclass(frozen=True, slots=True)
class ScheduledGPUFailure:
    failure_id: str
    target_id: str
    timestamp_ns: int
    reason: str = "GPU_FAILURE"

    def __post_init__(self) -> None:
        if not self.failure_id or not self.target_id or not self.reason:
            raise ValueError("failure identity must be non-empty")
        if type(self.timestamp_ns) is not int or self.timestamp_ns < 0:
            raise ValueError("failure timestamp must be a non-negative integer")


class ForwardStepStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FENCED = "FENCED"


@dataclass(slots=True)
class _ForwardStepRecord:
    target_id: str
    gpu_id: str
    start_ns: int
    planned_end_ns: int
    step: AegisSchedulerStep
    completion_event_id: str
    status: ForwardStepStatus = ForwardStepStatus.ACTIVE
    effective_end_ns: int | None = None
    completion: SchedulerStepCompletion | None = None
    residency_after_retire: ResidentPrimarySnapshot | None = None
    fenced_by_failure_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "target_id": self.target_id,
            "gpu_id": self.gpu_id,
            "start_ns": self.start_ns,
            "planned_end_ns": self.planned_end_ns,
            "effective_end_ns": self.effective_end_ns,
            "status": self.status.value,
            "completion_event_id": self.completion_event_id,
            "fenced_by_failure_id": self.fenced_by_failure_id,
            "participants": [item.to_dict() for item in self.step.participants],
            "phase_shapes": [item.to_dict() for item in self.step.phase_shapes],
            "duration": None if self.step.duration is None else self.step.duration.to_dict(),
            "resident_before": self.step.residency_before.to_dict(),
            "resident_after_schedule": self.step.residency_after_schedule.to_dict(),
            "completion": None if self.completion is None else self.completion.to_dict(),
            "resident_after_retire": (
                None
                if self.residency_after_retire is None
                else self.residency_after_retire.to_dict()
            ),
            "step_id": self.step.step_id,
            "is_mixed_phase": self.step.is_mixed_phase,
        }


@dataclass(slots=True)
class _RequestRuntime:
    spec: ContinuousBatchRequestSpec
    route_version: int = 0
    target_id: str | None = None
    completion_ns: int | None = None
    router_committed_output_tokens: int = 0
    silent_replay_target: int = 0
    route_history: list[tuple[int, int, str, str]] = field(default_factory=list)
    admission_handle: EventHandle | None = None
    pending_target_id: str | None = None
    pending_ready_ns: int | None = None
    pending_restored_tokens: int = 0
    pending_cause: str | None = None

    @property
    def complete(self) -> bool:
        return self.completion_ns is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "spec": self.spec.to_dict(),
            "route_version": self.route_version,
            "target_id": self.target_id,
            "completion_ns": self.completion_ns,
            "wct_ns": (
                None
                if self.completion_ns is None
                else self.completion_ns - self.spec.release_ns
            ),
            "router_committed_output_tokens": self.router_committed_output_tokens,
            "silent_replay_target": self.silent_replay_target,
            "route_history": [
                {
                    "timestamp_ns": timestamp_ns,
                    "route_version": route_version,
                    "target_id": target_id,
                    "cause": cause,
                }
                for timestamp_ns, route_version, target_id, cause in self.route_history
            ],
        }


@dataclass(frozen=True, slots=True)
class DriverFailureRecord:
    failure_id: str
    target_id: str
    timestamp_ns: int
    snapshot: GPUFailureFenceSnapshot
    requeue_targets: tuple[tuple[str, str], ...]
    router_committed_outputs_before_requeue: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "failure_id": self.failure_id,
            "target_id": self.target_id,
            "timestamp_ns": self.timestamp_ns,
            "snapshot": self.snapshot.to_dict(),
            "requeue_targets": dict(self.requeue_targets),
            "router_committed_outputs_before_requeue": dict(
                self.router_committed_outputs_before_requeue
            ),
            "recovery_mode": (
                "EXTERNAL_PREFIX_SELECTION_THEN_PROMPT_SUFFIX_RECOMPUTE_"
                "AND_SILENT_REPLAY_NO_LOST_HBM_REUSE"
            ),
        }


@dataclass(frozen=True, slots=True)
class ContinuousBatchDESResult:
    finished_at_ns: int
    requests: tuple[dict[str, object], ...]
    steps: tuple[dict[str, object], ...]
    failures: tuple[dict[str, object], ...]
    journal_sha256: str
    duration_evidence: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "finished_at_ns": self.finished_at_ns,
            "requests": list(self.requests),
            "steps": list(self.steps),
            "failures": list(self.failures),
            "journal_sha256": self.journal_sha256,
            "duration_evidence": list(self.duration_evidence),
            "calibration_boundary": (
                "MODELED_UNCALIBRATED_NOT_PHYSICAL_BATCH_LATENCY_EVIDENCE"
            ),
        }


@dataclass(slots=True)
class _TargetRuntime:
    bridge: AegisSchedulerStepBridge
    provider: ObservedIdealTraceDurationProvider
    failed: bool = False
    step_ready_pending: bool = False
    active_record: _ForwardStepRecord | None = None
    completion_handle: EventHandle | None = None


class AegisContinuousBatchDESDriver:
    """Release, schedule, complete, retire, fence, and requeue across GPUs."""

    def __init__(
        self,
        *,
        des: GlobalDES,
        bridges: tuple[AegisSchedulerStepBridge, ...],
        register_failure_handler: bool = True,
        on_step_started: Callable[[str, AegisSchedulerStep, int, int], None]
        | None = None,
        on_step_completed: Callable[
            [str, AegisSchedulerStep, SchedulerStepCompletion, int, ResidentPrimarySnapshot],
            None,
        ]
        | None = None,
        on_before_admit: Callable[
            [str, ContinuousBatchRequestSpec, int, str, int], None
        ]
        | None = None,
        on_after_admit: Callable[
            [str, ContinuousBatchRequestSpec, int, str, int], None
        ]
        | None = None,
        on_admit_abort: Callable[
            [str, ContinuousBatchRequestSpec, int, str, int], None
        ]
        | None = None,
        on_maintenance_step: Callable[[str, AegisSchedulerStep], None]
        | None = None,
    ) -> None:
        if not isinstance(des, GlobalDES):
            raise TypeError("des must be a GlobalDES")
        if not bridges:
            raise ValueError("at least one scheduler-step bridge is required")
        self.des = des
        self._targets: dict[str, _TargetRuntime] = {}
        bridge_ids: set[str] = set()
        for bridge in bridges:
            target_id = bridge.execution_binding.target_id
            if target_id in self._targets:
                raise ValueError(f"duplicate target_id: {target_id}")
            if bridge.bridge_id in bridge_ids:
                raise ValueError(f"duplicate bridge_id: {bridge.bridge_id}")
            provider = bridge.duration_provider
            if not isinstance(provider, ObservedIdealTraceDurationProvider):
                raise TypeError(
                    "driver bridges require ObservedIdealTraceDurationProvider"
                )
            if bridge.fenced or bridge.scheduler.running_request_ids or (
                bridge.scheduler.waiting_request_ids
            ):
                raise ValueError("driver requires empty, unfenced bridges")
            self._targets[target_id] = _TargetRuntime(bridge, provider)
            bridge_ids.add(bridge.bridge_id)
        self._requests: dict[str, _RequestRuntime] = {}
        self._steps: list[_ForwardStepRecord] = []
        self._issued_step_ids: set[str] = set()
        self._failures: list[DriverFailureRecord] = []
        self._started = False
        self._finished = False
        self._register_failure_handler = register_failure_handler
        self._on_step_started_callback = on_step_started
        self._on_step_completed_callback = on_step_completed
        self._on_before_admit_callback = on_before_admit
        self._on_after_admit_callback = on_after_admit
        self._on_admit_abort_callback = on_admit_abort
        self._on_maintenance_step_callback = on_maintenance_step
        des.register_handler(
            EventKind.CONTINUOUS_BATCH_ADMIT,
            self._on_request_arrival,
        )
        des.register_handler(EventKind.SCHEDULER_STEP_READY, self._on_step_ready)
        des.register_handler(EventKind.FORWARD_COMPLETE, self._on_forward_complete)
        if register_failure_handler:
            des.register_handler(EventKind.FAILURE_INJECT, self._on_failure)
        des.register_invariant("aegis-continuous-batch-des", self._check_invariants)

    def submit(self, spec: ContinuousBatchRequestSpec) -> EventHandle:
        self.register_suspended(spec)
        runtime = self._requests[spec.request_id]
        return self._schedule_admission(
            runtime,
            ready_ns=spec.release_ns,
            target_id=spec.initial_target_id,
            cause="INITIAL_RELEASE",
            restored_tokens=spec.initial_restored_tokens,
        )

    def register_suspended(self, spec: ContinuousBatchRequestSpec) -> None:
        """Register original release/WCT evidence without scheduling admission.

        A foreground Store GET owns the request between workload release and
        route-0 scheduler admission.  Registering that suspended interval keeps
        WCT anchored to the real release and lets an external GPU failure resume
        the same runtime rather than fabricating a second request.
        """

        if self._started:
            raise ContinuousBatchDESError("cannot submit after DES execution starts")
        if spec.request_id in self._requests:
            raise ValueError(f"duplicate request_id: {spec.request_id}")
        if spec.initial_target_id is not None and spec.initial_target_id not in self._targets:
            raise ValueError(f"unknown initial target: {spec.initial_target_id}")
        runtime = _RequestRuntime(spec=spec)
        self._requests[spec.request_id] = runtime
        for target in self._targets.values():
            target.provider.register_request(spec.observed_duration)

    def schedule_registered_initial_admission(
        self,
        *,
        request_id: str,
        target_id: str,
        ready_ns: int | None = None,
        restored_tokens: int = 0,
    ) -> EventHandle:
        """Schedule route-0 admission after an external initial GET completes."""

        runtime = self._requests.get(request_id)
        if runtime is None or runtime.complete:
            raise ContinuousBatchDESError(
                "initial admission requires a registered incomplete request"
            )
        if (
            runtime.route_version != 0
            or runtime.target_id is not None
            or runtime.admission_handle is not None
            or runtime.route_history
        ):
            raise ContinuousBatchDESError(
                "registered initial admission requires a pristine suspended runtime"
            )
        resolved_ready_ns = self.des.now_ns if ready_ns is None else ready_ns
        return self._schedule_admission(
            runtime,
            ready_ns=resolved_ready_ns,
            target_id=target_id,
            cause="INITIAL_STORE_RESTORE_COMPLETE",
            restored_tokens=restored_tokens,
        )

    def unregister_pristine_suspended(self, request_id: str) -> None:
        """Rollback setup that failed before any admission or route history."""

        runtime = self._requests.get(request_id)
        if runtime is None:
            return
        if (
            runtime.complete
            or runtime.route_version != 0
            or runtime.target_id is not None
            or runtime.admission_handle is not None
            or runtime.route_history
            or runtime.router_committed_output_tokens
        ):
            raise ContinuousBatchDESError(
                "only a pristine suspended runtime can be unregistered"
            )
        del self._requests[request_id]

    def inject_gpu_failure(self, failure: ScheduledGPUFailure) -> EventHandle:
        if not self._register_failure_handler:
            raise ContinuousBatchDESError(
                "external failure owner must call fence_for_external_gpu_failure"
            )
        if self._started:
            raise ContinuousBatchDESError("cannot inject failures after execution starts")
        if failure.target_id not in self._targets:
            raise ValueError(f"unknown failure target: {failure.target_id}")
        return self.des.schedule_at(
            failure.timestamp_ns,
            EventKind.FAILURE_INJECT,
            payload={
                "failure_id": failure.failure_id,
                "target_id": failure.target_id,
                "reason": failure.reason,
            },
            event_id=f"failure:{failure.failure_id}",
        )

    def fence_for_external_gpu_failure(
        self,
        *,
        failure_id: str,
        target_id: str,
        reason: str,
    ) -> GPUFailureFenceSnapshot:
        """Fence one target when the enclosing runtime owns FAILURE_INJECT.

        This cancels the active scheduler-step completion and freezes every
        resident/waiting request, but deliberately does not route or mutate the
        physical HBM ledger.  The enclosing failure handler owns those actions
        and may later call :meth:`resume_external_request` after detection.
        """

        if self._register_failure_handler:
            raise ContinuousBatchDESError("driver owns failure events in this mode")
        snapshot, _requeues = self._fence_target(
            failure_id=failure_id,
            target_id=target_id,
            reason=reason,
            requeue=False,
        )
        return snapshot

    def resume_external_request(
        self,
        *,
        request_id: str,
        target_id: str,
        route_version: int,
        ready_ns: int | None = None,
        restored_tokens: int = 0,
    ) -> None:
        """Admit a fresh full-recompute attempt after an external route fence."""

        runtime = self._requests.get(request_id)
        if runtime is None or runtime.complete:
            raise ContinuousBatchDESError("external resume requires an incomplete request")
        if runtime.target_id is not None:
            raise ContinuousBatchDESError("external resume requires a suspended request")
        if runtime.admission_handle is not None:
            raise ContinuousBatchDESError("external resume already owns a pending admission")
        if route_version <= runtime.route_version:
            raise ContinuousBatchDESError("external resume route version did not advance")
        if (
            type(restored_tokens) is not int
            or restored_tokens < 0
            or restored_tokens > runtime.spec.prompt_tokens
        ):
            raise ContinuousBatchDESError(
                "external restored prefix must be bounded by the request prompt"
            )
        runtime.route_version = route_version
        runtime.silent_replay_target = runtime.router_committed_output_tokens
        resolved_ready_ns = self.des.now_ns if ready_ns is None else ready_ns
        if resolved_ready_ns < self.des.now_ns:
            raise ContinuousBatchDESError("external resume cannot be scheduled in the past")
        if resolved_ready_ns > self.des.now_ns:
            self._schedule_admission(
                runtime,
                ready_ns=resolved_ready_ns,
                target_id=target_id,
                cause="EXTERNAL_FAILURE_OWNER_REQUEUE",
                restored_tokens=restored_tokens,
            )
            return
        self._admit_attempt(
            runtime,
            target_id=target_id,
            cause="EXTERNAL_FAILURE_OWNER_REQUEUE",
            restored_tokens=restored_tokens,
        )

    def _schedule_admission(
        self,
        runtime: _RequestRuntime,
        *,
        ready_ns: int,
        target_id: str | None,
        cause: str,
        restored_tokens: int,
    ) -> EventHandle:
        if runtime.complete or runtime.target_id is not None:
            raise ContinuousBatchDESError("pending admission requires a suspended request")
        if runtime.admission_handle is not None:
            raise ContinuousBatchDESError("request already owns a pending admission event")
        if target_id is not None and target_id not in self._targets:
            raise ContinuousBatchDESError("pending admission targets an unknown GPU")
        if ready_ns < self.des.now_ns:
            raise ContinuousBatchDESError("pending admission cannot precede the DES clock")
        handle = self.des.schedule_at(
            ready_ns,
            EventKind.CONTINUOUS_BATCH_ADMIT,
            payload={
                "request_id": runtime.spec.request_id,
                "route_version": runtime.route_version,
                "target_id": target_id,
                "cause": cause,
                "restored_tokens": restored_tokens,
            },
        )
        runtime.admission_handle = handle
        runtime.pending_target_id = target_id
        runtime.pending_ready_ns = ready_ns
        runtime.pending_restored_tokens = restored_tokens
        runtime.pending_cause = cause
        return handle

    def replace_repaired_target(self, bridge: AegisSchedulerStepBridge) -> None:
        """Install one new empty bridge after an external physical GPU repair."""

        target_id = bridge.execution_binding.target_id
        target = self._targets.get(target_id)
        if target is None or not target.failed or not target.bridge.fenced:
            raise ContinuousBatchDESError("target replacement requires a fenced failed bridge")
        provider = bridge.duration_provider
        if not isinstance(provider, ObservedIdealTraceDurationProvider):
            raise TypeError("replacement bridge has an incompatible duration provider")
        if bridge.fenced or bridge.scheduler.running_request_ids or (
            bridge.scheduler.waiting_request_ids
        ):
            raise ContinuousBatchDESError("replacement bridge must be empty and mutable")
        bridge.continue_step_sequence_after(target.bridge)
        for runtime in self._requests.values():
            provider.register_request(runtime.spec.observed_duration)
        self._targets[target_id] = _TargetRuntime(bridge, provider)

    def target_load_snapshot(self, target_id: str) -> dict[str, int]:
        """Estimate route-visible target backlog from live scheduler progress.

        The estimate follows the same observed-duration token-share model as
        forward steps.  Resident requests batch ideally, so their remaining
        horizon is the maximum share rather than a serial sum.  Route-bound
        future admissions extend that horizon by their ready time and full
        modeled duration.
        """

        try:
            target = self._targets[target_id]
        except KeyError as error:
            raise ContinuousBatchDESError(f"unknown target: {target_id}") from error
        if target.failed:
            raise ContinuousBatchDESError("failed target has no routable load snapshot")
        active_ready_ns = (
            self.des.now_ns
            if target.active_record is None
            else target.active_record.planned_end_ns
        )
        remaining_shares: list[int] = []
        for request_id, computed_tokens, total_tokens in (
            target.bridge.request_progress_snapshot()
        ):
            runtime = self._requests[request_id]
            remaining_tokens = max(0, total_tokens - computed_tokens)
            remaining_shares.append(
                (
                    runtime.spec.observed_ideal_duration_ns * remaining_tokens
                    + runtime.spec.observed_duration.scheduler_work_tokens
                    - 1
                )
                // runtime.spec.observed_duration.scheduler_work_tokens
            )
        estimated_available_ns = active_ready_ns + max(remaining_shares, default=0)
        pending_count = 0
        pending_tokens = 0
        for runtime in self._requests.values():
            if (
                runtime.admission_handle is None
                or runtime.pending_target_id != target_id
                or runtime.pending_ready_ns is None
            ):
                continue
            pending_count += 1
            pending_tokens += runtime.spec.observed_duration.scheduler_work_tokens
            estimated_available_ns = max(
                estimated_available_ns,
                runtime.pending_ready_ns
                + runtime.spec.observed_ideal_duration_ns,
            )
        progress = target.bridge.request_progress_snapshot()
        return {
            "queued_tokens": target.bridge.scheduler.queued_tokens + pending_tokens,
            "resident_request_count": len(progress),
            "pending_admission_count": pending_count,
            "active_forward_remaining_ns": max(
                0,
                active_ready_ns - self.des.now_ns,
            ),
            "estimated_available_ns": max(
                self.des.now_ns,
                estimated_available_ns,
            ),
        }

    def run(self, *, until_ns: int | None = None) -> ContinuousBatchDESResult:
        if self._finished:
            raise ContinuousBatchDESError("driver is single-use")
        self._started = True
        self.des.run(until_ns=until_ns)
        if self.des.pending_count:
            raise ContinuousBatchDESError("bounded run ended with pending driver events")
        incomplete = sorted(
            request_id for request_id, runtime in self._requests.items() if not runtime.complete
        )
        if incomplete:
            raise ContinuousBatchDESError(f"requests did not complete: {incomplete}")
        self._finished = True
        return ContinuousBatchDESResult(
            finished_at_ns=self.des.now_ns,
            requests=tuple(
                self._requests[request_id].to_dict()
                for request_id in sorted(self._requests)
            ),
            steps=tuple(record.to_dict() for record in self._steps),
            failures=tuple(record.to_dict() for record in self._failures),
            journal_sha256=hashlib.sha256(self.des.journal.to_jsonl_bytes()).hexdigest(),
            duration_evidence=tuple(
                self._targets[target_id].provider.evidence.to_dict()
                for target_id in sorted(self._targets)
            ),
        )

    def _on_request_arrival(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        request_id = str(event.payload["request_id"])
        runtime = self._requests[request_id]
        if runtime.admission_handle != EventHandle(event.event_id):
            raise ContinuousBatchDESError("stale admission event crossed its route fence")
        if int(event.payload["route_version"]) != runtime.route_version:
            raise ContinuousBatchDESError("pending admission route version is stale")
        target_id = runtime.pending_target_id
        cause = runtime.pending_cause
        restored_tokens = runtime.pending_restored_tokens
        if cause is None or runtime.pending_ready_ns != self.des.now_ns:
            raise ContinuousBatchDESError("pending admission metadata diverged")
        runtime.admission_handle = None
        runtime.pending_target_id = None
        runtime.pending_ready_ns = None
        runtime.pending_restored_tokens = 0
        runtime.pending_cause = None
        if target_id is None:
            target_id = self._select_target()
        elif self._targets[target_id].failed:
            raise ContinuousBatchDESError(
                "explicit pending admission reached a failed GPU without a fence"
            )
        self._admit_attempt(
            runtime,
            target_id=target_id,
            cause=cause,
            restored_tokens=restored_tokens,
        )

    def _admit_attempt(
        self,
        runtime: _RequestRuntime,
        *,
        target_id: str,
        cause: str,
        restored_tokens: int = 0,
    ) -> None:
        if runtime.complete or runtime.target_id is not None:
            raise ContinuousBatchDESError("admission requires one suspended request")
        if runtime.admission_handle is not None:
            raise ContinuousBatchDESError("direct admission crossed a pending event owner")
        target = self._targets[target_id]
        if target.failed:
            raise ContinuousBatchDESError("cannot admit onto a failed GPU")
        spec = runtime.spec
        request = Request(
            request_id=spec.request_id,
            prompt_tokens=spec.prompt_tokens,
            max_output_tokens=spec.max_output_tokens,
            arrival_ns=self.des.now_ns,
            priority=spec.priority,
            route_version=runtime.route_version,
            max_model_len_tokens=spec.max_model_len_tokens,
            prompt_token_ids=spec.prompt_token_ids,
        )
        bridge_admitted = False
        try:
            if self._on_before_admit_callback is not None:
                self._on_before_admit_callback(
                    target_id,
                    spec,
                    runtime.route_version,
                    cause,
                    restored_tokens,
                )
            if restored_tokens:
                target.bridge.admit_restored_request(
                    request,
                    restored_tokens=restored_tokens,
                )
            else:
                target.bridge.admit_request(request)
            bridge_admitted = True
            if restored_tokens and cause.startswith(
                ("GPU_FAILURE_REQUEUE:", "EXTERNAL_FAILURE_OWNER_REQUEUE")
            ):
                target.bridge.prioritize_waiting_recovery(request.request_id)
            if self._on_after_admit_callback is not None:
                self._on_after_admit_callback(
                    target_id,
                    spec,
                    runtime.route_version,
                    cause,
                    restored_tokens,
                )
        except Exception:
            if bridge_admitted:
                target.bridge.rollback_unstarted_admission(spec.request_id)
            if self._on_admit_abort_callback is not None:
                self._on_admit_abort_callback(
                    target_id,
                    spec,
                    runtime.route_version,
                    cause,
                    restored_tokens,
                )
            raise
        runtime.target_id = target_id
        runtime.route_history.append(
            (self.des.now_ns, runtime.route_version, target_id, cause)
        )
        self.des.journal.append(
            self.des.now_ns,
            "AegisRequestAdmitted",
            {
                "request_id": spec.request_id,
                "target_id": target_id,
                "route_version": runtime.route_version,
                "cause": cause,
                "silent_replay_target": runtime.silent_replay_target,
            },
        )
        self._request_step(target_id)

    def _request_step(self, target_id: str) -> None:
        target = self._targets[target_id]
        has_work = bool(
            target.bridge.scheduler.running_request_ids
            or target.bridge.scheduler.waiting_request_ids
        )
        if (
            target.failed
            or not has_work
            or target.active_record is not None
            or target.step_ready_pending
        ):
            return
        target.step_ready_pending = True
        self.des.schedule_at(
            self.des.now_ns,
            EventKind.SCHEDULER_STEP_READY,
            payload={"target_id": target_id},
        )

    def _on_step_ready(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        target_id = str(event.payload["target_id"])
        target = self._targets[target_id]
        target.step_ready_pending = False
        if target.failed:
            return
        if target.active_record is not None:
            raise ContinuousBatchDESError("GPU attempted to overlap scheduler steps")
        step = target.bridge.start_step()
        if step.step_id in self._issued_step_ids:
            raise ContinuousBatchDESError("duplicate scheduler step ID in one driver run")
        self._issued_step_ids.add(step.step_id)
        if not step.has_forward:
            if step.preempted_request_ids:
                if self._on_maintenance_step_callback is not None:
                    self._on_maintenance_step_callback(target_id, step)
                self.des.journal.append(
                    self.des.now_ns,
                    "AegisSchedulerMaintenanceStep",
                    {"target_id": target_id, "step": step.to_dict()},
                )
                self._request_step(target_id)
                return
            if target.bridge.scheduler.running_request_ids or (
                target.bridge.scheduler.waiting_request_ids
            ):
                raise ContinuousBatchDESError("scheduler made no progress with queued work")
            return
        assert step.duration is not None
        planned_end_ns = self.des.now_ns + step.duration.duration_ns
        handle = self.des.schedule_at(
            planned_end_ns,
            EventKind.FORWARD_COMPLETE,
            payload={"target_id": target_id, "step_id": step.step_id},
        )
        record = _ForwardStepRecord(
            target_id=target_id,
            gpu_id=target.bridge.execution_binding.gpu_id,
            start_ns=self.des.now_ns,
            planned_end_ns=planned_end_ns,
            step=step,
            completion_event_id=handle.event_id,
        )
        target.active_record = record
        target.completion_handle = handle
        self._steps.append(record)
        self.des.journal.append(
            self.des.now_ns,
            "AegisForwardStepStarted",
            record.to_dict(),
        )
        if self._on_step_started_callback is not None:
            self._on_step_started_callback(
                target_id,
                step,
                self.des.now_ns,
                planned_end_ns,
            )

    def _on_forward_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        target_id = str(event.payload["target_id"])
        target = self._targets[target_id]
        record = target.active_record
        if (
            target.failed
            or record is None
            or record.step.step_id != event.payload["step_id"]
            or record.completion_event_id != event.event_id
        ):
            raise ContinuousBatchDESError("stale scheduler-step completion crossed its fence")
        completion = target.bridge.complete_step(record.step.step_id)
        position_by_id = dict(completion.output_positions)
        participant_by_id = {
            participant.request_id: participant
            for participant in record.step.participants
        }
        for request_id, participant in participant_by_id.items():
            if not participant.produces_output:
                continue
            runtime = self._requests[request_id]
            local_position = position_by_id[request_id]
            if local_position > runtime.silent_replay_target:
                if local_position != runtime.router_committed_output_tokens + 1:
                    raise ContinuousBatchDESError("Router output position is not contiguous")
                runtime.router_committed_output_tokens += 1
        after_retire = completion.residency_after_completion
        for request_id in completion.terminal_output_request_ids:
            runtime = self._requests[request_id]
            if runtime.router_committed_output_tokens != runtime.spec.max_output_tokens:
                raise ContinuousBatchDESError("terminal request ended inside silent replay")
            after_retire = target.bridge.retire_request(request_id)
            runtime.completion_ns = self.des.now_ns
        record.status = ForwardStepStatus.COMPLETED
        record.effective_end_ns = self.des.now_ns
        record.completion = completion
        record.residency_after_retire = after_retire
        target.active_record = None
        target.completion_handle = None
        if self._on_step_completed_callback is not None:
            self._on_step_completed_callback(
                target_id,
                record.step,
                completion,
                self.des.now_ns,
                after_retire,
            )
        self.des.journal.append(
            self.des.now_ns,
            "AegisForwardStepCompleted",
            record.to_dict(),
        )
        self._request_step(target_id)

    def _on_failure(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        failure_id = str(event.payload["failure_id"])
        target_id = str(event.payload["target_id"])
        self._fence_target(
            failure_id=failure_id,
            target_id=target_id,
            reason=str(event.payload["reason"]),
            requeue=True,
        )

    def _fence_target(
        self,
        *,
        failure_id: str,
        target_id: str,
        reason: str,
        requeue: bool,
    ) -> tuple[GPUFailureFenceSnapshot, tuple[tuple[str, str], ...]]:
        target = self._targets[target_id]
        if target.failed:
            raise ContinuousBatchDESError(f"target already failed: {target_id}")
        reason = f"{reason}:{target.bridge.execution_binding.gpu_id}"
        snapshot = target.bridge.fence_for_gpu_failure(
            observed_at_ns=self.des.now_ns,
            reason=reason,
        )
        pending: list[PendingAdmissionFailureSnapshot] = []
        pending_ready: dict[str, int] = {}
        for request_id, runtime in sorted(self._requests.items()):
            if (
                runtime.complete
                or runtime.target_id is not None
                or runtime.admission_handle is None
                or runtime.pending_target_id != target_id
            ):
                continue
            if (
                runtime.pending_cause == "INITIAL_RELEASE"
                and not runtime.spec.route_bound_before_admission
            ):
                # A standalone future arrival has not entered the routing
                # domain yet.  Drop only its preferred target and let the
                # unchanged route-version-zero event select a healthy GPU.
                runtime.pending_target_id = None
                continue
            if runtime.pending_ready_ns is None or not self.des.cancel(
                runtime.admission_handle,
                reason=f"GPU_FAILURE_PENDING_ADMISSION_FENCE:{failure_id}",
            ):
                raise ContinuousBatchDESError(
                    "pending admission event was not cancellable"
                )
            if runtime.pending_cause is None:
                raise ContinuousBatchDESError("pending admission lost its cause")
            pending.append(
                PendingAdmissionFailureSnapshot(
                    request_id=request_id,
                    event_id=runtime.admission_handle.event_id,
                    cause=runtime.pending_cause,
                    route_version=runtime.route_version,
                    target_id=target_id,
                    ready_ns=runtime.pending_ready_ns,
                    restored_tokens=runtime.pending_restored_tokens,
                    router_committed_output_tokens=(
                        runtime.router_committed_output_tokens
                    ),
                    silent_replay_target=runtime.silent_replay_target,
                )
            )
            pending_ready[request_id] = runtime.pending_ready_ns
            runtime.admission_handle = None
            runtime.pending_target_id = None
            runtime.pending_ready_ns = None
            runtime.pending_restored_tokens = 0
            runtime.pending_cause = None
        snapshot = replace(
            snapshot,
            pending_admissions=tuple(pending),
        )
        pending_ids = list(snapshot.pending_admission_request_ids)
        active_record = target.active_record
        if active_record is not None:
            if target.completion_handle is None or not self.des.cancel(
                target.completion_handle,
                reason=f"GPU_FAILURE_FENCE:{failure_id}",
            ):
                raise ContinuousBatchDESError("active forward completion was not cancellable")
            active_record.status = ForwardStepStatus.FENCED
            active_record.effective_end_ns = self.des.now_ns
            active_record.fenced_by_failure_id = failure_id
        target.failed = True
        target.active_record = None
        target.completion_handle = None
        target.step_ready_pending = False

        committed = tuple(
            (item.request_id, self._requests[item.request_id].router_committed_output_tokens)
            for item in snapshot.requests
        ) + tuple(
            (request_id, self._requests[request_id].router_committed_output_tokens)
            for request_id in pending_ids
        )
        requeues: list[tuple[str, str]] = []
        for item in snapshot.requests:
            runtime = self._requests[item.request_id]
            if runtime.complete:
                raise ContinuousBatchDESError("failure snapshot contains completed request")
            runtime.silent_replay_target = runtime.router_committed_output_tokens
            runtime.target_id = None
            if not requeue:
                continue
            runtime.route_version += 1
            reroute_target = self._select_target()
            self._admit_attempt(
                runtime,
                target_id=reroute_target,
                cause=f"GPU_FAILURE_REQUEUE:{failure_id}",
                restored_tokens=0,
            )
            requeues.append((item.request_id, reroute_target))
        for request_id in pending_ids:
            runtime = self._requests[request_id]
            runtime.silent_replay_target = runtime.router_committed_output_tokens
            if not requeue:
                continue
            runtime.route_version += 1
            reroute_target = self._select_target()
            ready_ns = max(self.des.now_ns, pending_ready[request_id])
            if ready_ns > self.des.now_ns:
                self._schedule_admission(
                    runtime,
                    ready_ns=ready_ns,
                    target_id=reroute_target,
                    cause=f"GPU_FAILURE_REQUEUE:{failure_id}",
                    restored_tokens=0,
                )
            else:
                self._admit_attempt(
                    runtime,
                    target_id=reroute_target,
                    cause=f"GPU_FAILURE_REQUEUE:{failure_id}",
                    restored_tokens=0,
                )
            requeues.append((request_id, reroute_target))
        failure_record = DriverFailureRecord(
            failure_id=failure_id,
            target_id=target_id,
            timestamp_ns=self.des.now_ns,
            snapshot=snapshot,
            requeue_targets=tuple(requeues),
            router_committed_outputs_before_requeue=committed,
        )
        self._failures.append(failure_record)
        self.des.journal.append(
            self.des.now_ns,
            "AegisGPUFailureFencedAndRequeued",
            failure_record.to_dict(),
        )
        return snapshot, tuple(requeues)

    def _select_target(self) -> str:
        healthy = [
            (target_id, target)
            for target_id, target in self._targets.items()
            if not target.failed
        ]
        if not healthy:
            raise ContinuousBatchDESError("no healthy GPU target is available")
        return min(
            healthy,
            key=lambda item: (
                item[1].bridge.scheduler.queued_tokens,
                item[1].bridge.resident_primary_snapshot().resident_primary_bytes,
                len(item[1].bridge.scheduler.running_request_ids)
                + len(item[1].bridge.scheduler.waiting_request_ids),
                item[0],
            ),
        )[0]

    def _check_invariants(self, _des: GlobalDES) -> None:
        for target_id, target in self._targets.items():
            active_record = target.active_record
            active = active_record is not None
            if active != (target.completion_handle is not None):
                raise ContinuousBatchDESError(
                    f"target active step/completion ownership disagrees: {target_id}"
                )
            if target.failed and (active or not target.bridge.fenced):
                raise ContinuousBatchDESError(
                    f"failed target retained mutable execution: {target_id}"
                )
            if active_record is not None and (
                active_record.status is not ForwardStepStatus.ACTIVE
            ):
                raise ContinuousBatchDESError("active target owns a terminal step record")
        for request_id, runtime in self._requests.items():
            has_pending = runtime.admission_handle is not None
            if has_pending != (
                runtime.pending_ready_ns is not None
                and runtime.pending_cause is not None
            ):
                raise ContinuousBatchDESError(
                    f"request pending-admission ownership disagrees: {request_id}"
                )
            if has_pending and runtime.target_id is not None:
                raise ContinuousBatchDESError(
                    f"admitted request retained a pending admission: {request_id}"
                )
            if runtime.complete:
                if runtime.router_committed_output_tokens != runtime.spec.max_output_tokens:
                    raise ContinuousBatchDESError(
                        f"completed request output count disagrees: {request_id}"
                    )
            elif runtime.target_id is not None and self._targets[runtime.target_id].failed:
                raise ContinuousBatchDESError(
                    f"live request remains assigned to failed target: {request_id}"
                )


__all__ = [
    "AegisContinuousBatchDESDriver",
    "ContinuousBatchDESError",
    "ContinuousBatchDESResult",
    "ContinuousBatchRequestSpec",
    "DriverFailureRecord",
    "ForwardStepStatus",
    "ObservedIdealRequestDuration",
    "ObservedIdealTraceDurationProvider",
    "ScheduledGPUFailure",
]
