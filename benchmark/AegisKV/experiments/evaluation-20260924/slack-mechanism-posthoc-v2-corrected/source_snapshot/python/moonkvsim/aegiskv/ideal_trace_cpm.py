"""Ideal-trace Critical Path Method (CPM) slack for AegisKV Algorithm 1.

This module intentionally removes predictor error from the modeled experiment:
each trace span supplies its already-known agent invocation time through
``recorded_api_time_ns``.  The durations are propagated over the frozen causal
DAG with an exact forward/backward CPM pass.  No observed absolute finish time,
failure location, cache outcome, or future simulator event is consulted.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from moonkvsim.workload.causal_trace import NormalizedSpanMetadata


class IdealTraceCPMError(ValueError):
    """Raised when ideal-trace CPM cannot be evaluated on the supplied DAG."""


@dataclass(frozen=True, slots=True)
class IdealTraceCPMTiming:
    """Exact CPM timing for one agent invocation in workflow-relative ns."""

    workflow_id: str
    span_id: str
    agent_id: str
    duration_ns: int
    earliest_start_ns: int
    earliest_finish_ns: int
    latest_start_ns: int
    latest_finish_ns: int
    slack_ns: int
    critical: bool


@dataclass(frozen=True, slots=True)
class IdealTraceCPMResult:
    """Machine-auditable Algorithm 1 output for all workflows in one trace."""

    timings: dict[str, IdealTraceCPMTiming]
    workflow_makespan_ns: dict[str, int]
    algorithm: str = "ideal_trace_exact_dag_cpm_v1"
    duration_source: str = "trace.recorded_api_time_ns"
    forward_pass: str = "ES=max(parent.EF)+recorded_tool_delay; EF=ES+duration"
    backward_pass: str = "LF=min(child.LS-recorded_tool_delay); LS=LF-duration"

    def timing(self, span_id: str) -> IdealTraceCPMTiming:
        try:
            return self.timings[span_id]
        except KeyError as error:
            raise IdealTraceCPMError(f"unknown CPM span_id {span_id!r}") from error

    def provenance(self) -> dict[str, object]:
        critical_count = sum(item.critical for item in self.timings.values())
        return {
            "algorithm": self.algorithm,
            "duration_source": self.duration_source,
            "predictor_used": False,
            "prediction_error_modeled": False,
            "absolute_observed_finish_used": False,
            "failure_location_used": False,
            "forward_pass": self.forward_pass,
            "backward_pass": self.backward_pass,
            "slack_definition": "max(0,LS-ES)",
            "span_count": len(self.timings),
            "workflow_count": len(self.workflow_makespan_ns),
            "critical_span_count": critical_count,
        }


def compute_ideal_trace_cpm(
    spans: Iterable[NormalizedSpanMetadata],
) -> IdealTraceCPMResult:
    """Compute exact per-span slack from known trace durations.

    ``tool_delay_ns`` belongs to the child release rule and is therefore added
    once after the latest parent, rather than once per incoming edge.
    """

    grouped: dict[str, list[NormalizedSpanMetadata]] = defaultdict(list)
    seen: set[str] = set()
    for span in spans:
        if span.span_id in seen:
            raise IdealTraceCPMError(f"duplicate span_id {span.span_id!r}")
        seen.add(span.span_id)
        if span.recorded_api_time_ns <= 0:
            raise IdealTraceCPMError(
                f"span {span.span_id!r} has non-positive ideal duration"
            )
        grouped[span.workflow_id].append(span)
    if not grouped:
        raise IdealTraceCPMError("ideal-trace CPM requires at least one span")

    timings: dict[str, IdealTraceCPMTiming] = {}
    makespans: dict[str, int] = {}
    for workflow_id, workflow_spans in sorted(grouped.items()):
        by_id = {span.span_id: span for span in workflow_spans}
        children: dict[str, list[str]] = defaultdict(list)
        indegree = {span.span_id: len(span.parent_span_ids) for span in workflow_spans}
        for span in workflow_spans:
            for parent_id in span.parent_span_ids:
                parent = by_id.get(parent_id)
                if parent is None:
                    raise IdealTraceCPMError(
                        f"workflow {workflow_id!r} span {span.span_id!r} has "
                        f"missing or cross-workflow parent {parent_id!r}"
                    )
                children[parent_id].append(span.span_id)

        ready = deque(sorted(span_id for span_id, degree in indegree.items() if degree == 0))
        topological: list[str] = []
        while ready:
            span_id = ready.popleft()
            topological.append(span_id)
            for child_id in sorted(children[span_id]):
                indegree[child_id] -= 1
                if indegree[child_id] == 0:
                    ready.append(child_id)
        if len(topological) != len(workflow_spans):
            raise IdealTraceCPMError(f"workflow {workflow_id!r} contains a cycle")

        earliest_start: dict[str, int] = {}
        earliest_finish: dict[str, int] = {}
        for span_id in topological:
            span = by_id[span_id]
            parent_finish = max(
                (earliest_finish[parent_id] for parent_id in span.parent_span_ids),
                default=0,
            )
            start_ns = parent_finish + (span.tool_delay_ns if span.parent_span_ids else 0)
            earliest_start[span_id] = start_ns
            earliest_finish[span_id] = start_ns + span.recorded_api_time_ns

        makespan_ns = max(earliest_finish.values())
        makespans[workflow_id] = makespan_ns
        latest_start: dict[str, int] = {}
        latest_finish: dict[str, int] = {}
        for span_id in reversed(topological):
            span = by_id[span_id]
            child_ids = children[span_id]
            finish_ns = min(
                (
                    latest_start[child_id] - by_id[child_id].tool_delay_ns
                    for child_id in child_ids
                ),
                default=makespan_ns,
            )
            start_ns = finish_ns - span.recorded_api_time_ns
            if start_ns < earliest_start[span_id]:
                raise IdealTraceCPMError(
                    f"workflow {workflow_id!r} produced negative CPM slack for {span_id!r}"
                )
            latest_finish[span_id] = finish_ns
            latest_start[span_id] = start_ns

        for span_id in topological:
            span = by_id[span_id]
            slack_ns = latest_start[span_id] - earliest_start[span_id]
            timings[span_id] = IdealTraceCPMTiming(
                workflow_id=workflow_id,
                span_id=span_id,
                agent_id=span.agent_id,
                duration_ns=span.recorded_api_time_ns,
                earliest_start_ns=earliest_start[span_id],
                earliest_finish_ns=earliest_finish[span_id],
                latest_start_ns=latest_start[span_id],
                latest_finish_ns=latest_finish[span_id],
                slack_ns=slack_ns,
                critical=slack_ns == 0,
            )

    return IdealTraceCPMResult(timings=timings, workflow_makespan_ns=makespans)


def compute_residual_ideal_trace_cpm(
    spans: Iterable[NormalizedSpanMetadata],
    remaining_duration_ns: Mapping[str, int],
) -> IdealTraceCPMResult:
    """Exact CPM slack on the residual DAG of not-yet-complete agent nodes.

    ``remaining_duration_ns`` is the predicted remaining weight ``ŵ_v``.  Completed
    spans are omitted, so their children become residual start nodes.  Active
    remaining time is caller-supplied; this function does not read observed finish
    times, failure locations, or future simulator events.  Start-node ``ES`` is 0
    on the residual clock, matching Algorithm 1 ``UpdateSlack``.
    """

    remaining = dict(remaining_duration_ns)
    if not remaining:
        raise IdealTraceCPMError("residual CPM requires at least one remaining span")
    by_id = {span.span_id: span for span in spans}
    missing = sorted(span_id for span_id in remaining if span_id not in by_id)
    if missing:
        raise IdealTraceCPMError(f"residual duration for unknown span {missing[0]!r}")
    for span_id, duration_ns in remaining.items():
        if type(duration_ns) is not int or duration_ns < 0:
            raise IdealTraceCPMError(
                f"span {span_id!r} has invalid residual duration {duration_ns!r}"
            )

    grouped: dict[str, list[NormalizedSpanMetadata]] = defaultdict(list)
    for span_id in remaining:
        grouped[by_id[span_id].workflow_id].append(by_id[span_id])

    timings: dict[str, IdealTraceCPMTiming] = {}
    makespans: dict[str, int] = {}
    for workflow_id, workflow_spans in sorted(grouped.items()):
        residual_ids = {span.span_id for span in workflow_spans}
        residual_parents: dict[str, tuple[str, ...]] = {}
        children: dict[str, list[str]] = defaultdict(list)
        for span in workflow_spans:
            parents = tuple(
                parent_id
                for parent_id in span.parent_span_ids
                if parent_id in residual_ids
            )
            residual_parents[span.span_id] = parents
            for parent_id in parents:
                children[parent_id].append(span.span_id)

        indegree = {
            span.span_id: len(residual_parents[span.span_id]) for span in workflow_spans
        }
        ready = deque(sorted(span_id for span_id, degree in indegree.items() if degree == 0))
        topological: list[str] = []
        while ready:
            span_id = ready.popleft()
            topological.append(span_id)
            for child_id in sorted(children[span_id]):
                indegree[child_id] -= 1
                if indegree[child_id] == 0:
                    ready.append(child_id)
        if len(topological) != len(workflow_spans):
            raise IdealTraceCPMError(f"workflow {workflow_id!r} residual DAG contains a cycle")

        earliest_start: dict[str, int] = {}
        earliest_finish: dict[str, int] = {}
        for span_id in topological:
            span = by_id[span_id]
            parents = residual_parents[span_id]
            if not parents:
                start_ns = 0
            else:
                start_ns = max(
                    earliest_finish[parent_id] for parent_id in parents
                ) + span.tool_delay_ns
            earliest_start[span_id] = start_ns
            earliest_finish[span_id] = start_ns + remaining[span_id]

        makespan_ns = max(earliest_finish.values())
        makespans[workflow_id] = makespan_ns
        latest_start: dict[str, int] = {}
        latest_finish: dict[str, int] = {}
        for span_id in reversed(topological):
            span = by_id[span_id]
            child_ids = children[span_id]
            if not child_ids:
                finish_ns = makespan_ns
            else:
                finish_ns = min(
                    latest_start[child_id] - by_id[child_id].tool_delay_ns
                    for child_id in child_ids
                )
            start_ns = finish_ns - remaining[span_id]
            slack_ns = max(0, start_ns - earliest_start[span_id])
            latest_finish[span_id] = earliest_start[span_id] + remaining[span_id] + slack_ns
            latest_start[span_id] = earliest_start[span_id] + slack_ns
            timings[span_id] = IdealTraceCPMTiming(
                workflow_id=workflow_id,
                span_id=span_id,
                agent_id=span.agent_id,
                duration_ns=remaining[span_id],
                earliest_start_ns=earliest_start[span_id],
                earliest_finish_ns=earliest_finish[span_id],
                latest_start_ns=latest_start[span_id],
                latest_finish_ns=latest_finish[span_id],
                slack_ns=slack_ns,
                critical=slack_ns == 0,
            )

    return IdealTraceCPMResult(
        timings=timings,
        workflow_makespan_ns=makespans,
        algorithm="residual_ideal_trace_exact_dag_cpm_v1",
        duration_source="causal_remaining_predicted_agent_time",
        forward_pass="residual start ES=0; else ES=max(parent.EF)+tool_delay",
        backward_pass="residual C_t=max(end EF); LS=C_t-ŵ or min(succ.LS)-ŵ",
    )
