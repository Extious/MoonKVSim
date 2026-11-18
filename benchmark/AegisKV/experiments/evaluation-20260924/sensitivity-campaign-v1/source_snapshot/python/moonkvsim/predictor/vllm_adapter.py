"""Pinned-vLLM scheduler-step to engine-neutral prediction batches.

The adapter consumes the tensor-free ``ContinuousBatchScheduler`` output and
the corresponding post-schedule request states.  It emits separate prefill and
decode batches while preserving source scheduling order within each phase.
It never carries block IDs, connector metadata, or KV-transfer work into the
GPU-forward prediction schema.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from moonkvsim.common.hash import canonical_json_bytes, sha256_json
from moonkvsim.integration.vllm.request import Request, RequestStatus
from moonkvsim.integration.vllm.scheduler import (
    VLLM_SCHEDULE_SYMBOL,
    VLLM_SCHEDULER_SHA256,
    VLLM_SOURCE_COMMIT,
    ScheduledRequest,
    SchedulerOutput,
    SchedulingOrigin,
    SchedulingPhase,
)
from moonkvsim.predictor.schema import (
    PredictionBatch,
    PredictionPhase,
    PredictionProfile,
    PredictionRequest,
)


class VLLMBatchAdapterError(RuntimeError):
    """Raised when one scheduler output has no unambiguous prediction shape."""


@dataclass(frozen=True, slots=True)
class AdaptedPhaseBatch:
    """One phase-specific neutral batch plus source request correlation IDs."""

    request_ids: tuple[str, ...]
    batch: PredictionBatch

    def __post_init__(self) -> None:
        if not self.request_ids or len(self.request_ids) != len(self.batch.requests):
            raise ValueError("request_ids must align one-to-one with the prediction batch")
        if len(set(self.request_ids)) != len(self.request_ids):
            raise ValueError("request_ids must be unique within a phase batch")
        if any(not request_id for request_id in self.request_ids):
            raise ValueError("request_ids must be non-empty")

    @property
    def phase(self) -> PredictionPhase:
        return self.batch.phase

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "request_ids": list(self.request_ids),
            "batch": self.batch.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AdaptedSchedulerStep:
    """Canonical phase split for one scheduler output.

    A mixed continuous-batching step has two entries.  This object does not
    define a rule for summing or otherwise composing their predicted latency.
    A caller must supply a separate fingerprinted composition rule; absence of
    that rule remains fail-closed.
    """

    scheduled_request_ids: tuple[str, ...]
    phase_batches: tuple[AdaptedPhaseBatch, ...]
    scheduler_output_fingerprint: str
    source_commit: str = VLLM_SOURCE_COMMIT
    source_sha256: str = VLLM_SCHEDULER_SHA256
    source_symbol: str = VLLM_SCHEDULE_SYMBOL
    evidence_class: str = "E1/E2-toy-adapter-semantics"

    def __post_init__(self) -> None:
        if len(set(self.scheduled_request_ids)) != len(self.scheduled_request_ids):
            raise ValueError("scheduled_request_ids must be unique")
        phases = tuple(item.phase for item in self.phase_batches)
        canonical_phases = tuple(phase for phase in PredictionPhase if phase in set(phases))
        if phases != canonical_phases:
            raise ValueError("phase batches must be unique and in canonical phase order")
        grouped_ids = {
            request_id
            for phase_batch in self.phase_batches
            for request_id in phase_batch.request_ids
        }
        if grouped_ids != set(self.scheduled_request_ids):
            raise ValueError("phase batches must cover scheduled request IDs exactly once")
        if sum(len(item.request_ids) for item in self.phase_batches) != len(
            self.scheduled_request_ids
        ):
            raise ValueError("each scheduled request ID must appear in exactly one phase batch")
        if not self.scheduler_output_fingerprint or len(self.scheduler_output_fingerprint) != 64:
            raise ValueError("scheduler_output_fingerprint must be a SHA-256")
        if (self.scheduled_request_ids and not self.phase_batches) or (
            self.phase_batches and not self.scheduled_request_ids
        ):
            raise ValueError("empty scheduler steps cannot contain phase batches")

    @property
    def has_forward(self) -> bool:
        return bool(self.phase_batches)

    @property
    def is_mixed_phase(self) -> bool:
        return len(self.phase_batches) > 1

    def batch_for_phase(self, phase: PredictionPhase) -> AdaptedPhaseBatch | None:
        return next((item for item in self.phase_batches if item.phase is phase), None)

    def canonical_fields(self) -> dict[str, object]:
        return {
            "boundary": "gpu_forward_shape_only",
            "scheduled_request_ids": list(self.scheduled_request_ids),
            "phase_batches": [item.to_dict() for item in self.phase_batches],
            "scheduler_output_fingerprint": self.scheduler_output_fingerprint,
            "source_commit": self.source_commit,
            "source_sha256": self.source_sha256,
            "source_symbol": self.source_symbol,
            "evidence_class": self.evidence_class,
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


class VLLMSchedulerBatchAdapter:
    """Adapt one source-locked ordinary decoder-only scheduler step."""

    def adapt(
        self,
        scheduler_output: SchedulerOutput,
        *,
        requests: Mapping[str, Request],
        profile: PredictionProfile,
    ) -> AdaptedSchedulerStep:
        if not isinstance(scheduler_output, SchedulerOutput):
            raise TypeError("scheduler_output must be a MoonKVSim SchedulerOutput")
        if not isinstance(profile, PredictionProfile):
            raise TypeError("profile must be a PredictionProfile")
        self._validate_source_identity(scheduler_output)
        scheduled = self._ordered_scheduled_requests(scheduler_output)

        request_ids_by_phase: dict[PredictionPhase, list[str]] = {
            phase: [] for phase in PredictionPhase
        }
        requests_by_phase: dict[PredictionPhase, list[PredictionRequest]] = {
            phase: [] for phase in PredictionPhase
        }
        for item in scheduled:
            request = requests.get(item.request_id)
            if request is None:
                raise VLLMBatchAdapterError(
                    f"missing corresponding request state: {item.request_id}"
                )
            phase = self._validate_and_classify(item, request)
            request_ids_by_phase[phase].append(item.request_id)
            requests_by_phase[phase].append(
                PredictionRequest(
                    extend_length=item.num_scheduled_tokens,
                    past_kv_length=item.num_computed_tokens_before,
                )
            )

        phase_batches = tuple(
            AdaptedPhaseBatch(
                request_ids=tuple(request_ids_by_phase[phase]),
                batch=PredictionBatch.for_profile(
                    requests=tuple(requests_by_phase[phase]),
                    phase=phase,
                    profile=profile,
                ),
            )
            for phase in PredictionPhase
            if requests_by_phase[phase]
        )
        return AdaptedSchedulerStep(
            scheduled_request_ids=scheduler_output.scheduled_req_ids,
            phase_batches=phase_batches,
            scheduler_output_fingerprint=sha256_json(scheduler_output.to_dict()),
        )

    @staticmethod
    def _validate_source_identity(output: SchedulerOutput) -> None:
        actual = (output.source_commit, output.source_sha256, output.source_symbol)
        expected = (VLLM_SOURCE_COMMIT, VLLM_SCHEDULER_SHA256, VLLM_SCHEDULE_SYMBOL)
        if actual != expected:
            raise VLLMBatchAdapterError(
                "scheduler output does not match the pinned vLLM source identity"
            )

    @staticmethod
    def _ordered_scheduled_requests(output: SchedulerOutput) -> tuple[ScheduledRequest, ...]:
        if not isinstance(output.num_scheduled_tokens, dict):
            raise VLLMBatchAdapterError("num_scheduled_tokens must be an ordered dictionary")
        if any(
            not isinstance(request_id, str)
            or not request_id
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
            for request_id, count in output.num_scheduled_tokens.items()
        ):
            raise VLLMBatchAdapterError(
                "num_scheduled_tokens requires non-empty IDs and positive integer counts"
            )
        if output.total_num_scheduled_tokens != sum(output.num_scheduled_tokens.values()):
            raise VLLMBatchAdapterError("total_num_scheduled_tokens does not conserve")
        if (
            isinstance(output.token_budget_remaining, bool)
            or not isinstance(output.token_budget_remaining, int)
            or output.token_budget_remaining < 0
        ):
            raise VLLMBatchAdapterError("token_budget_remaining must be non-negative")

        groups = (
            (output.scheduled_new_reqs, SchedulingOrigin.NEW),
            (output.scheduled_resumed_reqs, SchedulingOrigin.RESUMED),
            (output.scheduled_running_reqs, SchedulingOrigin.RUNNING),
        )
        by_id: dict[str, ScheduledRequest] = {}
        for group, expected_origin in groups:
            for item in group:
                if not isinstance(item, ScheduledRequest):
                    raise VLLMBatchAdapterError("scheduled groups contain an invalid item")
                if item.origin is not expected_origin:
                    raise VLLMBatchAdapterError(
                        f"scheduled group disagrees with origin: {item.request_id}"
                    )
                if item.request_id in by_id:
                    raise VLLMBatchAdapterError(
                        f"scheduled request appears in multiple groups: {item.request_id}"
                    )
                by_id[item.request_id] = item
        if set(by_id) != set(output.num_scheduled_tokens):
            raise VLLMBatchAdapterError(
                "scheduled groups and num_scheduled_tokens have different request IDs"
            )
        if any(
            item.num_scheduled_tokens != output.num_scheduled_tokens[request_id]
            for request_id, item in by_id.items()
        ):
            raise VLLMBatchAdapterError("scheduled item count disagrees with num_scheduled_tokens")
        return tuple(by_id[request_id] for request_id in output.num_scheduled_tokens)

    @staticmethod
    def _validate_and_classify(
        item: ScheduledRequest,
        request: Request,
    ) -> PredictionPhase:
        if not isinstance(request, Request) or request.request_id != item.request_id:
            raise VLLMBatchAdapterError(
                f"corresponding request identity mismatch: {item.request_id}"
            )
        if request.status is not RequestStatus.RUNNING:
            raise VLLMBatchAdapterError(f"scheduled request is not RUNNING: {item.request_id}")
        counters = (
            item.num_scheduled_tokens,
            item.num_computed_tokens_before,
            item.num_computed_tokens_after,
            request.prompt_tokens,
            request.num_computed_tokens,
            request.num_tokens,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counters
        ):
            raise VLLMBatchAdapterError("scheduler/request counters must be non-negative integers")
        if item.num_scheduled_tokens <= 0:
            raise VLLMBatchAdapterError("scheduled token count must be positive")
        if (
            item.num_computed_tokens_after
            != item.num_computed_tokens_before + item.num_scheduled_tokens
        ):
            raise VLLMBatchAdapterError("scheduled request counters do not conserve")
        if request.num_computed_tokens != item.num_computed_tokens_after:
            raise VLLMBatchAdapterError(
                f"request state is stale or from another step: {item.request_id}"
            )
        if request.num_computed_tokens > request.num_tokens:
            raise VLLMBatchAdapterError("computed tokens exceed materialized request tokens")

        if item.num_computed_tokens_before < request.prompt_tokens:
            phase = PredictionPhase.PREFILL
            if item.num_computed_tokens_after > request.prompt_tokens:
                raise VLLMBatchAdapterError(
                    "one scheduled request crosses the prefill/decode boundary"
                )
            expected_source_phase = SchedulingPhase.PREFILL
        else:
            phase = PredictionPhase.DECODE
            expected_source_phase = SchedulingPhase.DECODE
            if item.num_scheduled_tokens != 1:
                raise VLLMBatchAdapterError(
                    "ordinary decoder-only adaptation requires one token per decode request"
                )
        if item.phase is not expected_source_phase:
            raise VLLMBatchAdapterError(
                f"source phase disagrees with request counters: {item.request_id}"
            )
        return phase
