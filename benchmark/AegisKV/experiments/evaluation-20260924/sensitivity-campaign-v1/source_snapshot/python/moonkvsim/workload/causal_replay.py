"""Deterministic parent-completion release engine on the shared GlobalDES clock."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.workload.causal_trace import (
    CausalTrace,
    NormalizedSpanMetadata,
    validate_causal_trace,
)

ReleaseCallback = Callable[[NormalizedSpanMetadata, GlobalDES], None]


class CausalReplayError(RuntimeError):
    """Raised when replay state or events violate the frozen causal contract."""


class SpanRuntimeStatus(StrEnum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class SpanRuntimeSnapshot:
    span_id: str
    status: SpanRuntimeStatus
    scheduled_release_ns: int | None
    released_ns: int | None
    completed_ns: int | None
    terminal_reason: str | None


@dataclass(slots=True)
class _MutableSpanState:
    status: SpanRuntimeStatus = SpanRuntimeStatus.PENDING
    release_handle: EventHandle | None = None
    scheduled_release_ns: int | None = None
    released_ns: int | None = None
    completed_ns: int | None = None
    terminal_reason: str | None = None


class CausalReleaseEngine:
    """Release roots by observed time and children after all parents plus tool delay."""

    _PAYLOAD_ENGINE = "moonkvsim.causal_release.v1"

    def __init__(
        self,
        trace: CausalTrace,
        des: GlobalDES,
        *,
        on_release: ReleaseCallback | None = None,
        workflow_concurrency: int | None = None,
        workflow_admission_seed: int | None = None,
    ) -> None:
        # Validate again at the runtime boundary even when the loader already did so.
        validate_causal_trace(trace.spans)
        self.trace = trace
        self.des = des
        self._on_release = on_release
        if workflow_concurrency is not None and (
            type(workflow_concurrency) is not int or workflow_concurrency <= 0
        ):
            raise CausalReplayError("workflow_concurrency must be a positive integer or null")
        if workflow_admission_seed is not None and (
            type(workflow_admission_seed) is not int or workflow_admission_seed < 0
        ):
            raise CausalReplayError(
                "workflow_admission_seed must be a non-negative integer or null"
            )
        if workflow_concurrency is None and workflow_admission_seed is not None:
            raise CausalReplayError(
                "workflow_admission_seed requires closed-loop workflow concurrency"
            )
        self.workflow_concurrency = workflow_concurrency
        self.workflow_admission_seed = workflow_admission_seed
        self._by_id = trace.by_span_id
        self._states = {span.span_id: _MutableSpanState() for span in trace.spans}
        workflows: dict[str, list[NormalizedSpanMetadata]] = defaultdict(list)
        children: dict[str, list[NormalizedSpanMetadata]] = defaultdict(list)
        for span in trace.spans:
            workflows[span.workflow_id].append(span)
            for parent_id in span.parent_span_ids:
                children[parent_id].append(span)
        self._workflows = {
            workflow_id: tuple(sorted(spans, key=lambda span: span.stable_sort_key))
            for workflow_id, spans in workflows.items()
        }
        self._workflow_roots = {
            workflow_id: tuple(span for span in spans if not span.parent_span_ids)
            for workflow_id, spans in self._workflows.items()
        }
        self._children = {
            parent_id: tuple(sorted(spans, key=lambda span: span.stable_sort_key))
            for parent_id, spans in children.items()
        }
        self._started = False
        self._release_order: list[str] = []
        self._eligible_workflow_ids: list[str] = []
        self._active_workflow_ids: set[str] = set()
        self._admitted_workflow_ids: set[str] = set()
        self._workflow_admission_order: list[str] = []
        try:
            self.des.register_handler(EventKind.REQUEST_ARRIVAL, self._handle_release_event)
        except ValueError as error:
            raise CausalReplayError(
                "causal release engine requires exclusive REQUEST_ARRIVAL handler ownership"
            ) from error

    @property
    def release_order(self) -> tuple[str, ...]:
        return tuple(self._release_order)

    @property
    def workflow_admission_order(self) -> tuple[str, ...]:
        return tuple(self._workflow_admission_order)

    def snapshot(self, span_id: str) -> SpanRuntimeSnapshot:
        state = self._state(span_id)
        return SpanRuntimeSnapshot(
            span_id=span_id,
            status=state.status,
            scheduled_release_ns=state.scheduled_release_ns,
            released_ns=state.released_ns,
            completed_ns=state.completed_ns,
            terminal_reason=state.terminal_reason,
        )

    def start(self) -> None:
        if self._started:
            raise CausalReplayError("causal replay has already started")
        roots = sorted(
            (span for span in self.trace.spans if not span.parent_span_ids),
            key=lambda span: span.stable_sort_key,
        )
        if not roots:
            raise CausalReplayError("validated causal trace unexpectedly has no roots")
        past_roots = [span for span in roots if span.observed_submit_ns < self.des.now_ns]
        if past_roots:
            raise CausalReplayError(
                f"root {past_roots[0].span_id!r} arrives before GlobalDES.now_ns={self.des.now_ns}"
            )
        self._started = True
        self.des.journal.append(
            self.des.now_ns,
            "WORKLOAD_CAUSAL_REPLAY_STARTED",
            {
                "engine": self._PAYLOAD_ENGINE,
                "span_count": len(self.trace.spans),
                "root_count": len(roots),
                "workflow_count": len(self._workflows),
                "workflow_concurrency": self.workflow_concurrency,
                "workflow_admission_seed": self.workflow_admission_seed,
                "workflow_admission_order": (
                    "observed_submit_then_source_metadata"
                    if self.workflow_admission_seed is None
                    else "observed_submit_then_seeded_sha256_workflow_permutation"
                ),
                "admission_mode": (
                    "observed_open_loop"
                    if self.workflow_concurrency is None
                    else "closed_loop_workflow_concurrency"
                ),
                "evidence_boundary": "toy_E1_E2_causal_semantics_not_trace_experiment",
            },
        )
        if self.workflow_concurrency is None:
            for root in roots:
                self._schedule_release(root, root.observed_submit_ns, "observed_root_arrival")
            return
        for workflow_id, workflow_roots in sorted(
            self._workflow_roots.items(),
            key=lambda item: self._workflow_admission_key(item[0]),
        ):
            first_submit_ns = min(root.observed_submit_ns for root in workflow_roots)
            self.des.schedule_at(
                first_submit_ns,
                EventKind.REQUEST_ARRIVAL,
                payload={
                    "workload_engine": self._PAYLOAD_ENGINE,
                    "event_type": "WORKFLOW_ELIGIBLE",
                    "workflow_id": workflow_id,
                },
                event_id=f"workload-eligible:{workflow_id}",
            )

    def mark_completed(self, span_id: str) -> None:
        self._require_started()
        state = self._state(span_id)
        if state.status is not SpanRuntimeStatus.RELEASED:
            raise CausalReplayError(
                f"span {span_id!r} cannot complete from state {state.status.value}"
            )
        state.status = SpanRuntimeStatus.COMPLETED
        state.completed_ns = self.des.now_ns
        self.des.journal.append(
            self.des.now_ns,
            "WORKLOAD_SPAN_COMPLETED",
            {"span_id": span_id, "workflow_id": self._by_id[span_id].workflow_id},
        )
        for child in self._children.get(span_id, ()):
            self._evaluate_child(child)
        self._maybe_finish_workflow(self._by_id[span_id].workflow_id)

    def mark_unavailable(self, span_id: str, *, reason: str) -> None:
        self._require_started()
        if not reason:
            raise CausalReplayError("unavailable reason must be non-empty")
        state = self._state(span_id)
        if state.status not in {
            SpanRuntimeStatus.PENDING,
            SpanRuntimeStatus.SCHEDULED,
            SpanRuntimeStatus.RELEASED,
        }:
            raise CausalReplayError(
                f"span {span_id!r} cannot become unavailable from state {state.status.value}"
            )
        if state.release_handle is not None and state.status is SpanRuntimeStatus.SCHEDULED:
            self.des.cancel(state.release_handle, reason=f"WORKLOAD_PARENT_UNAVAILABLE:{reason}")
        state.status = SpanRuntimeStatus.UNAVAILABLE
        state.terminal_reason = reason
        self.des.journal.append(
            self.des.now_ns,
            "WORKLOAD_SPAN_UNAVAILABLE",
            {"span_id": span_id, "reason": reason},
        )
        self._block_descendants(span_id, unavailable_parent_id=span_id)
        self._maybe_finish_workflow(self._by_id[span_id].workflow_id)

    def _state(self, span_id: str) -> _MutableSpanState:
        try:
            return self._states[span_id]
        except KeyError as error:
            raise CausalReplayError(f"unknown span_id {span_id!r}") from error

    def _require_started(self) -> None:
        if not self._started:
            raise CausalReplayError("causal replay has not started")

    def _schedule_release(
        self, span: NormalizedSpanMetadata, timestamp_ns: int, release_basis: str
    ) -> None:
        state = self._state(span.span_id)
        if state.status is not SpanRuntimeStatus.PENDING:
            raise CausalReplayError(
                f"span {span.span_id!r} cannot be scheduled from state {state.status.value}"
            )
        if timestamp_ns < self.des.now_ns:
            raise CausalReplayError(
                f"span {span.span_id!r} release {timestamp_ns} precedes GlobalDES.now_ns"
            )
        payload = {
            "workload_engine": self._PAYLOAD_ENGINE,
            "event_type": "SPAN_RELEASE",
            "workflow_id": span.workflow_id,
            "session_id": span.session_id,
            "agent_id": span.agent_id,
            "span_id": span.span_id,
            "parent_span_ids": list(span.parent_span_ids),
            "parent_edges": [
                {
                    "parent_span_id": edge.parent_span_id,
                    "origin": edge.origin.value,
                    "confidence": edge.confidence,
                    "inference_rule": edge.inference_rule,
                }
                for edge in span.parent_edges
            ],
            "parent_edge_origin": span.parent_edge_origin,
            "parent_edge_confidence": span.parent_edge_confidence,
            "tool_delay_ns": span.tool_delay_ns,
            "dependency_release_rule": span.dependency_release_rule,
            "release_basis": release_basis,
        }
        handle = self.des.schedule_at(
            timestamp_ns,
            EventKind.REQUEST_ARRIVAL,
            payload=payload,
            event_id=f"workload-release:{span.span_id}",
        )
        state.status = SpanRuntimeStatus.SCHEDULED
        state.release_handle = handle
        state.scheduled_release_ns = timestamp_ns
        self.des.journal.append(
            self.des.now_ns,
            "WORKLOAD_SPAN_RELEASE_SCHEDULED",
            {
                "span_id": span.span_id,
                "release_at_ns": timestamp_ns,
                "release_basis": release_basis,
            },
        )

    def _handle_release_event(self, event: ScheduledEvent, state_des: GlobalDES) -> None:
        if state_des is not self.des:
            raise CausalReplayError("release event executed on a different GlobalDES instance")
        if event.payload.get("workload_engine") != self._PAYLOAD_ENGINE:
            raise CausalReplayError("foreign REQUEST_ARRIVAL event reached causal release engine")
        if event.payload.get("event_type") == "WORKFLOW_ELIGIBLE":
            self._handle_workflow_eligible(event)
            return
        if event.payload.get("event_type") not in {None, "SPAN_RELEASE"}:
            raise CausalReplayError("causal release event has an unknown event_type")
        span_id = event.payload.get("span_id")
        if not isinstance(span_id, str) or span_id not in self._by_id:
            raise CausalReplayError("release event has an unknown or missing span_id")
        runtime = self._state(span_id)
        if runtime.status is not SpanRuntimeStatus.SCHEDULED:
            raise CausalReplayError(
                f"span {span_id!r} release event executed from state {runtime.status.value}"
            )
        if runtime.release_handle is None or runtime.release_handle.event_id != event.event_id:
            raise CausalReplayError(f"span {span_id!r} release handle does not match event")
        if runtime.scheduled_release_ns != self.des.now_ns:
            raise CausalReplayError(f"span {span_id!r} release timestamp does not match GlobalDES")
        runtime.status = SpanRuntimeStatus.RELEASED
        runtime.released_ns = self.des.now_ns
        self._release_order.append(span_id)
        self.des.journal.append(
            self.des.now_ns,
            "WORKLOAD_SPAN_RELEASED",
            {
                "span_id": span_id,
                "workflow_id": self._by_id[span_id].workflow_id,
                "parent_span_ids": list(self._by_id[span_id].parent_span_ids),
            },
        )
        if self._on_release is not None:
            self._on_release(self._by_id[span_id], self.des)

    def _handle_workflow_eligible(self, event: ScheduledEvent) -> None:
        if self.workflow_concurrency is None:
            raise CausalReplayError("workflow eligibility event reached open-loop replay")
        workflow_id = event.payload.get("workflow_id")
        if not isinstance(workflow_id, str) or workflow_id not in self._workflows:
            raise CausalReplayError("workflow eligibility event has an unknown workflow_id")
        if workflow_id in self._admitted_workflow_ids or workflow_id in self._eligible_workflow_ids:
            raise CausalReplayError(f"workflow {workflow_id!r} became eligible twice")
        self._eligible_workflow_ids.append(workflow_id)
        self._eligible_workflow_ids.sort(key=self._workflow_admission_key)
        self.des.journal.append(
            self.des.now_ns,
            "WORKLOAD_WORKFLOW_ELIGIBLE",
            {"workflow_id": workflow_id, "queued_workflows": len(self._eligible_workflow_ids)},
        )
        self._admit_eligible_workflows()

    def _workflow_admission_key(self, workflow_id: str) -> tuple[object, ...]:
        roots = self._workflow_roots[workflow_id]
        observed_submit_ns = min(root.observed_submit_ns for root in roots)
        if self.workflow_admission_seed is None:
            return (observed_submit_ns, roots[0].stable_sort_key)
        digest = hashlib.sha256(
            f"workflow-admission:{self.workflow_admission_seed}:{workflow_id}".encode()
        ).digest()
        return (
            observed_submit_ns,
            int.from_bytes(digest[:8], "big"),
            roots[0].stable_sort_key,
        )

    def _admit_eligible_workflows(self) -> None:
        if self.workflow_concurrency is None:
            return
        while (
            self._eligible_workflow_ids
            and len(self._active_workflow_ids) < self.workflow_concurrency
        ):
            workflow_id = self._eligible_workflow_ids.pop(0)
            roots = self._workflow_roots[workflow_id]
            original_start_ns = min(root.observed_submit_ns for root in roots)
            admitted_ns = self.des.now_ns
            self._active_workflow_ids.add(workflow_id)
            self._admitted_workflow_ids.add(workflow_id)
            self._workflow_admission_order.append(workflow_id)
            self.des.journal.append(
                admitted_ns,
                "WORKLOAD_WORKFLOW_ADMITTED",
                {
                    "workflow_id": workflow_id,
                    "workflow_concurrency": self.workflow_concurrency,
                    "active_workflows": len(self._active_workflow_ids),
                    "queued_workflows": len(self._eligible_workflow_ids),
                    "eligibility_ns": original_start_ns,
                    "queue_wait_ns": admitted_ns - original_start_ns,
                },
            )
            for root in roots:
                root_offset_ns = root.observed_submit_ns - original_start_ns
                self._schedule_release(
                    root,
                    admitted_ns + root_offset_ns,
                    "workflow_admission_plus_observed_root_offset",
                )

    def _maybe_finish_workflow(self, workflow_id: str) -> None:
        if self.workflow_concurrency is None or workflow_id not in self._active_workflow_ids:
            return
        terminal = {
            SpanRuntimeStatus.COMPLETED,
            SpanRuntimeStatus.UNAVAILABLE,
            SpanRuntimeStatus.BLOCKED,
        }
        if not all(
            self._state(span.span_id).status in terminal
            for span in self._workflows[workflow_id]
        ):
            return
        self._active_workflow_ids.remove(workflow_id)
        self.des.journal.append(
            self.des.now_ns,
            "WORKLOAD_WORKFLOW_COMPLETED",
            {
                "workflow_id": workflow_id,
                "active_workflows": len(self._active_workflow_ids),
                "queued_workflows": len(self._eligible_workflow_ids),
            },
        )
        self._admit_eligible_workflows()

    def _evaluate_child(self, child: NormalizedSpanMetadata) -> None:
        child_state = self._state(child.span_id)
        if child_state.status is not SpanRuntimeStatus.PENDING:
            return
        parent_states = [self._state(parent_id) for parent_id in child.parent_span_ids]
        unavailable_index = next(
            (
                index
                for index, state in enumerate(parent_states)
                if state.status in {SpanRuntimeStatus.UNAVAILABLE, SpanRuntimeStatus.BLOCKED}
            ),
            None,
        )
        if unavailable_index is not None:
            self._block_span(child, unavailable_parent_id=child.parent_span_ids[unavailable_index])
            return
        if not all(state.status is SpanRuntimeStatus.COMPLETED for state in parent_states):
            return
        completion_times = [state.completed_ns for state in parent_states]
        if any(timestamp is None for timestamp in completion_times):
            raise CausalReplayError(
                f"child {child.span_id!r} has completed parent without timestamp"
            )
        last_parent_completion_ns = max(
            timestamp for timestamp in completion_times if timestamp is not None
        )
        release_ns = last_parent_completion_ns + child.tool_delay_ns
        self._schedule_release(
            child,
            release_ns,
            "all_parent_completions_plus_recorded_tool_delay",
        )

    def _block_descendants(self, parent_id: str, *, unavailable_parent_id: str) -> None:
        for child in self._children.get(parent_id, ()):
            child_state = self._state(child.span_id)
            if child_state.status in {SpanRuntimeStatus.PENDING, SpanRuntimeStatus.SCHEDULED}:
                self._block_span(child, unavailable_parent_id=unavailable_parent_id)

    def _block_span(
        self, span: NormalizedSpanMetadata, *, unavailable_parent_id: str
    ) -> None:
        state = self._state(span.span_id)
        if state.status not in {SpanRuntimeStatus.PENDING, SpanRuntimeStatus.SCHEDULED}:
            return
        if state.release_handle is not None and state.status is SpanRuntimeStatus.SCHEDULED:
            self.des.cancel(
                state.release_handle,
                reason=f"WORKLOAD_PARENT_UNAVAILABLE:{unavailable_parent_id}",
            )
        state.status = SpanRuntimeStatus.BLOCKED
        state.terminal_reason = f"parent_unavailable:{unavailable_parent_id}"
        self.des.journal.append(
            self.des.now_ns,
            "WORKLOAD_SPAN_BLOCKED",
            {
                "span_id": span.span_id,
                "unavailable_parent_id": unavailable_parent_id,
            },
        )
        self._block_descendants(
            span.span_id,
            unavailable_parent_id=unavailable_parent_id,
        )
