"""Streaming metadata loader for normalized multi-agent trace spans."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, cast

from moonkvsim.config import SchemaValidationError, validate_trace_span


class CausalTraceValidationError(ValueError):
    """Raised when normalized records do not form a closed causal DAG."""


class EdgeOrigin(StrEnum):
    OBSERVED = "observed"
    INFERRED = "inferred"


@dataclass(frozen=True, slots=True)
class ParentEdgeMetadata:
    parent_span_id: str
    origin: EdgeOrigin
    confidence: float
    inference_rule: str | None


@dataclass(frozen=True, slots=True)
class NormalizedSpanMetadata:
    """Replay metadata only; source text, token IDs, and hash blocks are discarded."""

    workflow_id: str
    session_id: str
    agent_id: str
    agent_role: str
    span_id: str
    parent_edges: tuple[ParentEdgeMetadata, ...]
    parent_edge_origin: str
    parent_edge_confidence: float | None
    observed_submit_ns: int
    observed_finish_ns: int
    recorded_api_time_ns: int
    tool_delay_ns: int
    dependency_release_rule: str
    prompt_tokens: int
    cached_prefix_tokens: int
    output_tokens: int
    model_id: str
    evidence_class: str
    token_count_mode: str
    source_hash_id_scope_raw: str
    hash_id_scope: str
    workflow_line: int
    top_level_index: int
    inner_index: int | None

    @property
    def parent_span_ids(self) -> tuple[str, ...]:
        return tuple(edge.parent_span_id for edge in self.parent_edges)

    @property
    def stable_sort_key(self) -> tuple[int, str, int, int, int, str]:
        inner_index = -1 if self.inner_index is None else self.inner_index
        return (
            self.observed_submit_ns,
            self.workflow_id,
            self.workflow_line,
            self.top_level_index,
            inner_index,
            self.span_id,
        )


@dataclass(frozen=True, slots=True)
class CausalTrace:
    spans: tuple[NormalizedSpanMetadata, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.spans, key=lambda span: span.stable_sort_key))
        object.__setattr__(self, "spans", ordered)
        validate_causal_trace(ordered)

    @property
    def by_span_id(self) -> dict[str, NormalizedSpanMetadata]:
        return {span.span_id: span for span in self.spans}


def _metadata_from_record(record: Mapping[str, Any]) -> NormalizedSpanMetadata:
    try:
        validate_trace_span(record)
    except SchemaValidationError as error:
        raise CausalTraceValidationError(str(error)) from error

    raw_edges = cast(list[dict[str, Any]], record["parent_edges"])
    edges = tuple(
        ParentEdgeMetadata(
            parent_span_id=cast(str, edge["parent_span_id"]),
            origin=EdgeOrigin(cast(str, edge["origin"])),
            confidence=float(edge["confidence"]),
            inference_rule=cast(str | None, edge["inference_rule"]),
        )
        for edge in raw_edges
    )
    for edge in edges:
        if edge.origin is EdgeOrigin.INFERRED and not edge.inference_rule:
            raise CausalTraceValidationError(
                f"span {record['span_id']!r}: inferred edge {edge.parent_span_id!r} "
                "requires a non-empty inference_rule"
            )
        if edge.origin is EdgeOrigin.OBSERVED and edge.inference_rule is not None:
            raise CausalTraceValidationError(
                f"span {record['span_id']!r}: observed edge {edge.parent_span_id!r} "
                "must not carry an inference_rule"
            )
    source_position = cast(dict[str, Any], record["source_position"])
    return NormalizedSpanMetadata(
        workflow_id=cast(str, record["workflow_id"]),
        session_id=cast(str, record["session_id"]),
        agent_id=cast(str, record["agent_id"]),
        agent_role=cast(str, record["agent_role"]),
        span_id=cast(str, record["span_id"]),
        parent_edges=edges,
        parent_edge_origin=cast(str, record["parent_edge_origin"]),
        parent_edge_confidence=cast(float | None, record["parent_edge_confidence"]),
        observed_submit_ns=cast(int, record["observed_submit_ns"]),
        observed_finish_ns=cast(int, record["observed_finish_ns"]),
        recorded_api_time_ns=cast(int, record["recorded_api_time_ns"]),
        tool_delay_ns=cast(int, record["tool_delay_ns"]),
        dependency_release_rule=cast(str, record["dependency_release_rule"]),
        prompt_tokens=cast(int, record["prompt_tokens"]),
        cached_prefix_tokens=cast(int, record["cached_prefix_tokens"]),
        output_tokens=cast(int, record["output_tokens"]),
        model_id=cast(str, record["model_id"]),
        evidence_class=cast(str, record["evidence_class"]),
        token_count_mode=cast(str, record["token_count_mode"]),
        source_hash_id_scope_raw=cast(str, record["source_hash_id_scope_raw"]),
        hash_id_scope=cast(str, record["hash_id_scope"]),
        workflow_line=cast(int, source_position["workflow_line"]),
        top_level_index=cast(int, source_position["top_level_index"]),
        inner_index=cast(int | None, source_position["inner_index"]),
    )


def normalized_span_metadata_from_record(
    record: Mapping[str, Any],
) -> NormalizedSpanMetadata:
    """Validate one record and retain only causal/shape metadata.

    Runners that require source-owned block identifiers can keep those arrays
    in a separate, explicitly scoped structure without weakening the compact
    causal loader's no-content-retention contract.
    """

    return _metadata_from_record(record)


def iter_normalized_span_metadata(path: str | Path) -> Iterator[NormalizedSpanMetadata]:
    """Yield validated metadata one JSONL record at a time without retaining content arrays."""

    resolved_path = Path(path)
    try:
        with resolved_path.open("r", encoding="utf-8", newline="") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise CausalTraceValidationError(
                        f"line {line_number}: blank normalized trace lines are forbidden"
                    )
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise CausalTraceValidationError(
                        f"line {line_number}: invalid JSON: {error}"
                    ) from error
                if not isinstance(record, dict):
                    raise CausalTraceValidationError(
                        f"line {line_number}: normalized span must be an object"
                    )
                try:
                    yield _metadata_from_record(record)
                except CausalTraceValidationError as error:
                    raise CausalTraceValidationError(f"line {line_number}: {error}") from error
    except OSError as error:
        raise CausalTraceValidationError(
            f"cannot read normalized trace {resolved_path}: {error}"
        ) from error


def load_normalized_trace_jsonl(path: str | Path) -> CausalTrace:
    """Stream records into compact metadata, then close and validate the full DAG."""

    return CausalTrace(tuple(iter_normalized_span_metadata(path)))


def load_normalized_trace_records(records: Iterable[Mapping[str, Any]]) -> CausalTrace:
    """Load in-memory records; intended for tests and small programmatic workloads."""

    spans: list[NormalizedSpanMetadata] = []
    for index, record in enumerate(records):
        try:
            spans.append(_metadata_from_record(record))
        except CausalTraceValidationError as error:
            raise CausalTraceValidationError(f"record {index}: {error}") from error
    return CausalTrace(tuple(spans))


def validate_causal_trace(spans: Iterable[NormalizedSpanMetadata]) -> None:
    """Fail closed on duplicate, missing, cross-workflow, malformed, or cyclic edges."""

    span_list = tuple(spans)
    if not span_list:
        raise CausalTraceValidationError("causal trace must contain at least one span")
    by_id: dict[str, NormalizedSpanMetadata] = {}
    for span in span_list:
        if span.span_id in by_id:
            raise CausalTraceValidationError(f"duplicate span_id {span.span_id!r}")
        by_id[span.span_id] = span

    children: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {}
    for span in span_list:
        parent_ids = span.parent_span_ids
        if not parent_ids:
            if span.dependency_release_rule != "observed_root_arrival":
                raise CausalTraceValidationError(
                    f"root span {span.span_id!r} must use observed_root_arrival"
                )
        elif span.dependency_release_rule != "parent_completion_plus_recorded_delay":
            raise CausalTraceValidationError(
                f"child span {span.span_id!r} must use "
                "parent_completion_plus_recorded_delay"
            )
        indegree[span.span_id] = len(parent_ids)
        for parent_id in parent_ids:
            parent = by_id.get(parent_id)
            if parent is None:
                raise CausalTraceValidationError(
                    f"span {span.span_id!r} has missing parent {parent_id!r}"
                )
            if parent.workflow_id != span.workflow_id:
                raise CausalTraceValidationError(
                    f"span {span.span_id!r} has cross-workflow parent {parent_id!r}"
                )
            children[parent_id].append(span.span_id)

    ready = deque(sorted(span_id for span_id, degree in indegree.items() if degree == 0))
    visited = 0
    while ready:
        parent_id = ready.popleft()
        visited += 1
        for child_id in sorted(children[parent_id]):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(child_id)
    if visited != len(span_list):
        cyclic = sorted(span_id for span_id, degree in indegree.items() if degree > 0)
        raise CausalTraceValidationError(
            f"cycle detected among spans: {', '.join(cyclic[:10])}"
        )
