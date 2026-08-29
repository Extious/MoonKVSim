"""Streaming, deterministic normalization for the pinned Weka trace format."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any, BinaryIO, Final

from moonkvsim.config import validate_trace_span

MAX_MODEL_LENGTH: Final = 131_072
SOURCE_BLOCK_SIZE: Final = 64
NEAR_128K_LOWER: Final = 126_976
NORMALIZER_VERSION: Final = "moonkvsim.weka.v1.1"
EVIDENCE_CLASS: Final = "real_trace_shape_replay"
TOKEN_COUNT_MODE: Final = "source_hash_blocks_64"
HASH_ID_SCOPE: Final = "within_workflow_only"
RAW_HASH_ID_SCOPE: Final = "local"

_TOP_LEVEL_FIELDS: Final = {"id", "models", "block_size", "hash_id_scope", "requests"}
_REQUEST_FIELDS: Final = {
    "api_time",
    "hash_ids",
    "in",
    "model",
    "out",
    "t",
    "think_time",
    "ttft",
    "type",
}
_SUBAGENT_FIELDS: Final = {
    "agent_id",
    "duration_ms",
    "models",
    "requests",
    "status",
    "subagent_type",
    "t",
    "tool_use_count",
    "total_tokens",
    "type",
}
_BUCKET_BOUNDS: Final = (
    (0, 8_192),
    (8_192, 32_768),
    (32_768, 65_536),
    (65_536, 98_304),
    (98_304, 131_072),
)


class WekaTraceError(ValueError):
    """Raised when raw Weka data violates its pinned, fail-closed contract."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _seconds_to_ns(value: int | float) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WekaTraceError(f"time value must be numeric, got {value!r}")
    if not math.isfinite(value) or value < 0:
        raise WekaTraceError(f"time value must be finite and non-negative, got {value!r}")
    return int((Decimal(str(value)) * Decimal(1_000_000_000)).to_integral_value(ROUND_HALF_UP))


def _milliseconds_to_ns(value: int | float) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WekaTraceError(f"duration_ms must be numeric, got {value!r}")
    if not math.isfinite(value) or value < 0:
        raise WekaTraceError(f"duration_ms must be finite and non-negative, got {value!r}")
    return int((Decimal(str(value)) * Decimal(1_000_000)).to_integral_value(ROUND_HALF_UP))


def _require_fields(
    record: Mapping[str, Any], allowed: set[str], required: set[str], where: str
) -> None:
    unknown = sorted(set(record) - allowed)
    missing = sorted(required - set(record))
    if unknown:
        raise WekaTraceError(f"{where}: unknown fields: {', '.join(unknown)}")
    if missing:
        raise WekaTraceError(f"{where}: missing fields: {', '.join(missing)}")


def _require_int(value: Any, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WekaTraceError(f"{where}: expected integer >= {minimum}, got {value!r}")
    return value


def _require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise WekaTraceError(f"{where}: expected a non-empty string, got {value!r}")
    return value


def _stable_span_id(workflow_id: str, top_level_index: int, inner_index: int | None) -> str:
    if inner_index is None:
        return f"weka:{workflow_id}:main:{top_level_index:06d}"
    return f"weka:{workflow_id}:subagent:{top_level_index:06d}:{inner_index:06d}"


def _source_hash_ids_sha256(hash_ids: Sequence[int]) -> str:
    return hashlib.sha256(_canonical_json_bytes(hash_ids)).hexdigest()


@dataclass(frozen=True)
class _GroupMetadata:
    group_id: str
    agent_id: str
    subagent_type: str
    status: str
    duration_ns: int
    tool_use_count: int | None
    start_ns: int
    end_ns: int


@dataclass
class _Candidate:
    workflow_id: str
    workflow_line: int
    top_level_index: int
    inner_index: int | None
    role: str
    agent_id: str
    model_id: str
    raw_request_type: str
    prompt_tokens: int
    output_tokens: int
    hash_ids: list[int]
    submit_ns: int
    api_time_ns: int
    tool_delay_ns: int
    group: _GroupMetadata | None
    parents: list[tuple[_Candidate, float, str]] = field(default_factory=list)

    @property
    def span_id(self) -> str:
        return _stable_span_id(self.workflow_id, self.top_level_index, self.inner_index)

    @property
    def finish_ns(self) -> int:
        return self.submit_ns + self.api_time_ns

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    @property
    def source_order(self) -> tuple[int, int]:
        inner = -1 if self.inner_index is None else self.inner_index
        return (self.top_level_index, inner)


@dataclass
class _CoverageAccumulator:
    workflow_ids: set[str] = field(default_factory=set)
    raw_hash_id_scopes: set[str] = field(default_factory=set)
    strict_workflow_ids: set[str] = field(default_factory=set)
    models: set[str] = field(default_factory=set)
    total_requests: int = 0
    main_requests: int = 0
    subagent_requests: int = 0
    input_only_pass: int = 0
    strict_pass: int = 0
    strict_overflow: int = 0
    output_reserve_reject: int = 0
    input_only_max_prompt_tokens: int | None = None
    strict_max_prompt_tokens: int | None = None
    bucket_request_counts: list[int] = field(default_factory=lambda: [0] * len(_BUCKET_BOUNDS))
    bucket_workflow_ids: list[set[str]] = field(
        default_factory=lambda: [set() for _ in _BUCKET_BOUNDS]
    )
    near_input_only_count: int = 0
    near_input_only_workflow_ids: set[str] = field(default_factory=set)
    near_input_only_main: int = 0
    near_input_only_subagent: int = 0
    near_strict_count: int = 0
    near_strict_workflow_ids: set[str] = field(default_factory=set)
    near_strict_main: int = 0
    near_strict_subagent: int = 0
    near_strict_sample_ids: list[str] = field(default_factory=list)

    def add_workflow(self, workflow_id: str, raw_hash_id_scope: str) -> None:
        if workflow_id in self.workflow_ids:
            raise WekaTraceError(f"duplicate workflow id {workflow_id!r}")
        self.workflow_ids.add(workflow_id)
        self.raw_hash_id_scopes.add(raw_hash_id_scope)

    def add_request(self, candidate: _Candidate) -> bool:
        self.total_requests += 1
        if candidate.role == "main":
            self.main_requests += 1
        else:
            self.subagent_requests += 1
        self.models.add(candidate.model_id)

        input_only_passes = candidate.prompt_tokens <= MAX_MODEL_LENGTH
        strict_passes = candidate.total_tokens <= MAX_MODEL_LENGTH
        if input_only_passes:
            self.input_only_pass += 1
            current = self.input_only_max_prompt_tokens
            self.input_only_max_prompt_tokens = (
                candidate.prompt_tokens
                if current is None
                else max(current, candidate.prompt_tokens)
            )
        if strict_passes:
            self.strict_pass += 1
            self.strict_workflow_ids.add(candidate.workflow_id)
            current = self.strict_max_prompt_tokens
            self.strict_max_prompt_tokens = (
                candidate.prompt_tokens
                if current is None
                else max(current, candidate.prompt_tokens)
            )
            for index, (lower, upper) in enumerate(_BUCKET_BOUNDS):
                if lower < candidate.prompt_tokens <= upper:
                    self.bucket_request_counts[index] += 1
                    self.bucket_workflow_ids[index].add(candidate.workflow_id)
                    break
        else:
            self.strict_overflow += 1
            if input_only_passes:
                self.output_reserve_reject += 1

        is_near_128k = NEAR_128K_LOWER <= candidate.prompt_tokens <= MAX_MODEL_LENGTH
        if is_near_128k and input_only_passes:
            self.near_input_only_count += 1
            self.near_input_only_workflow_ids.add(candidate.workflow_id)
            if candidate.role == "main":
                self.near_input_only_main += 1
            else:
                self.near_input_only_subagent += 1
        if is_near_128k and strict_passes:
            self.near_strict_count += 1
            self.near_strict_workflow_ids.add(candidate.workflow_id)
            self.near_strict_sample_ids.append(candidate.span_id)
            if candidate.role == "main":
                self.near_strict_main += 1
            else:
                self.near_strict_subagent += 1
        return strict_passes

    def to_document(self, raw_sha256: str) -> dict[str, Any]:
        buckets = []
        for index, (lower, upper) in enumerate(_BUCKET_BOUNDS):
            buckets.append(
                {
                    "lower_exclusive": lower,
                    "upper_inclusive": upper,
                    "request_count": self.bucket_request_counts[index],
                    "workflow_count": len(self.bucket_workflow_ids[index]),
                }
            )
        return {
            "schema": "moonkvsim.trace_audit.v1",
            "normalizer_version": NORMALIZER_VERSION,
            "raw_sha256": raw_sha256,
            "guard": {
                "expression": "prompt_tokens + output_tokens <= 131072",
                "max_model_len_tokens": MAX_MODEL_LENGTH,
                "output_reserve": "actual_recorded_output_tokens",
                "overflow_action": "exclude_without_truncation",
            },
            "evidence": {
                "evidence_class": EVIDENCE_CLASS,
                "token_count_mode": TOKEN_COUNT_MODE,
                "source_block_size_tokens": SOURCE_BLOCK_SIZE,
                "source_hash_id_scope_raw_values": sorted(self.raw_hash_id_scopes),
                "hash_id_scope": HASH_ID_SCOPE,
                "hash_id_scope_mapping": {
                    "raw": RAW_HASH_ID_SCOPE,
                    "normalized": HASH_ID_SCOPE,
                    "semantics": "hash identities are comparable only within one workflow row",
                },
                "target_tokenizer_equivalence": False,
                "parent_edge_origin": "inferred",
            },
            "raw": {
                "workflow_count": len(self.workflow_ids),
                "request_count": self.total_requests,
                "main_request_count": self.main_requests,
                "subagent_request_count": self.subagent_requests,
                "models": sorted(self.models),
            },
            "legacy_input_only_guard": {
                "expression": "prompt_tokens <= 131072",
                "pass_count": self.input_only_pass,
                "max_prompt_tokens": self.input_only_max_prompt_tokens,
            },
            "strict_guard": {
                "pass_count": self.strict_pass,
                "workflow_count": len(self.strict_workflow_ids),
                "overflow_count": self.strict_overflow,
                "input_pass_but_output_reserve_fail_count": self.output_reserve_reject,
                "max_prompt_tokens": self.strict_max_prompt_tokens,
                "truncated_count": 0,
                "synthetic": False,
            },
            "context_buckets": buckets,
            "near_128k": {
                "definition": "126976 <= prompt_tokens <= 131072",
                "legacy_input_only": {
                    "request_count": self.near_input_only_count,
                    "workflow_count": len(self.near_input_only_workflow_ids),
                    "main_request_count": self.near_input_only_main,
                    "subagent_request_count": self.near_input_only_subagent,
                },
                "strict_with_output_reserve": {
                    "request_count": self.near_strict_count,
                    "workflow_count": len(self.near_strict_workflow_ids),
                    "main_request_count": self.near_strict_main,
                    "subagent_request_count": self.near_strict_subagent,
                    "sample_ids": sorted(self.near_strict_sample_ids),
                },
            },
        }


def _parse_request(
    request: Mapping[str, Any],
    *,
    workflow_id: str,
    workflow_line: int,
    top_level_index: int,
    inner_index: int | None,
    role: str,
    agent_id: str,
    group: _GroupMetadata | None,
) -> _Candidate:
    where = f"workflow line {workflow_line}, request {top_level_index}"
    if inner_index is not None:
        where += f", inner request {inner_index}"
    _require_fields(
        request,
        _REQUEST_FIELDS,
        {"api_time", "hash_ids", "in", "model", "out", "t", "type"},
        where,
    )
    prompt_tokens = _require_int(request["in"], f"{where}.in")
    output_tokens = _require_int(request["out"], f"{where}.out")
    model_id = _require_string(request["model"], f"{where}.model")
    raw_request_type = _require_string(request["type"], f"{where}.type")
    raw_hash_ids = request["hash_ids"]
    if not isinstance(raw_hash_ids, list):
        raise WekaTraceError(f"{where}.hash_ids: expected an array")
    hash_ids = [
        _require_int(hash_id, f"{where}.hash_ids[{index}]")
        for index, hash_id in enumerate(raw_hash_ids)
    ]
    if len(hash_ids) * SOURCE_BLOCK_SIZE != prompt_tokens:
        raise WekaTraceError(
            f"{where}: in={prompt_tokens} does not equal len(hash_ids)*{SOURCE_BLOCK_SIZE}"
        )
    submit_ns = _seconds_to_ns(request["t"])
    api_time_ns = _seconds_to_ns(request["api_time"])
    tool_delay_ns = _seconds_to_ns(request.get("think_time", 0))
    return _Candidate(
        workflow_id=workflow_id,
        workflow_line=workflow_line,
        top_level_index=top_level_index,
        inner_index=inner_index,
        role=role,
        agent_id=agent_id,
        model_id=model_id,
        raw_request_type=raw_request_type,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        hash_ids=hash_ids,
        submit_ns=submit_ns,
        api_time_ns=api_time_ns,
        tool_delay_ns=tool_delay_ns,
        group=group,
    )


def _parse_subagent_group(
    raw_group: Mapping[str, Any],
    *,
    workflow_id: str,
    workflow_line: int,
    top_level_index: int,
) -> tuple[_GroupMetadata, list[_Candidate]]:
    where = f"workflow line {workflow_line}, subagent group {top_level_index}"
    _require_fields(
        raw_group,
        _SUBAGENT_FIELDS,
        {
            "agent_id",
            "duration_ms",
            "models",
            "requests",
            "status",
            "subagent_type",
            "t",
            "tool_use_count",
            "total_tokens",
            "type",
        },
        where,
    )
    if raw_group["type"] != "subagent":
        raise WekaTraceError(f"{where}.type: expected 'subagent', got {raw_group['type']!r}")
    agent_id = _require_string(raw_group["agent_id"], f"{where}.agent_id")
    subagent_type = _require_string(raw_group["subagent_type"], f"{where}.subagent_type")
    status = _require_string(raw_group["status"], f"{where}.status")
    start_ns = _seconds_to_ns(raw_group["t"])
    duration_ns = _milliseconds_to_ns(raw_group["duration_ms"])
    tool_use_count = raw_group["tool_use_count"]
    if tool_use_count is not None:
        tool_use_count = _require_int(tool_use_count, f"{where}.tool_use_count")
    _require_int(raw_group["total_tokens"], f"{where}.total_tokens")
    if not isinstance(raw_group["models"], list) or not all(
        isinstance(model, str) and model for model in raw_group["models"]
    ):
        raise WekaTraceError(f"{where}.models: expected an array of non-empty strings")
    group = _GroupMetadata(
        group_id=f"weka:{workflow_id}:subagent-group:{top_level_index:06d}",
        agent_id=agent_id,
        subagent_type=subagent_type,
        status=status,
        duration_ns=duration_ns,
        tool_use_count=tool_use_count,
        start_ns=start_ns,
        end_ns=start_ns + duration_ns,
    )
    raw_requests = raw_group["requests"]
    if not isinstance(raw_requests, list) or not raw_requests:
        raise WekaTraceError(f"{where}.requests: expected a non-empty array")
    requests: list[_Candidate] = []
    for inner_index, raw_request in enumerate(raw_requests):
        if not isinstance(raw_request, Mapping):
            raise WekaTraceError(f"{where}.requests[{inner_index}]: expected an object")
        requests.append(
            _parse_request(
                raw_request,
                workflow_id=workflow_id,
                workflow_line=workflow_line,
                top_level_index=top_level_index,
                inner_index=inner_index,
                role="subagent",
                agent_id=agent_id,
                group=group,
            )
        )
    return group, requests


def _add_parent(
    child: _Candidate, parent: _Candidate, confidence: float, inference_rule: str
) -> None:
    if child.span_id == parent.span_id:
        raise WekaTraceError(f"span {child.span_id!r} cannot be its own parent")
    if all(existing.span_id != parent.span_id for existing, _, _ in child.parents):
        child.parents.append((parent, confidence, inference_rule))


def _infer_edges(candidates: list[_Candidate]) -> None:
    mains = sorted(
        (candidate for candidate in candidates if candidate.role == "main"),
        key=lambda candidate: (candidate.submit_ns, candidate.source_order),
    )
    groups: dict[str, list[_Candidate]] = {}
    for candidate in candidates:
        if candidate.group is not None:
            groups.setdefault(candidate.group.group_id, []).append(candidate)
    for group_candidates in groups.values():
        group_candidates.sort(key=lambda candidate: (candidate.submit_ns, candidate.source_order))

    for index, main in enumerate(mains):
        previous_main = mains[index - 1] if index else None
        if previous_main is not None:
            _add_parent(main, previous_main, 0.75, "previous_selected_main_by_observed_time")
        lower_bound = -1 if previous_main is None else previous_main.submit_ns
        completed_groups: list[_Candidate] = []
        for group_candidates in groups.values():
            first = group_candidates[0]
            last = group_candidates[-1]
            group = first.group
            assert group is not None
            if lower_bound < group.start_ns < main.submit_ns and group.end_ns <= main.submit_ns:
                completed_groups.append(last)
        for last in sorted(
            completed_groups, key=lambda candidate: (candidate.finish_ns, candidate.source_order)
        ):
            _add_parent(main, last, 0.50, "subagent_group_end_before_main_submit")

    for group_candidates in groups.values():
        first = group_candidates[0]
        launching_mains = [main for main in mains if main.submit_ns <= first.submit_ns]
        if launching_mains:
            parent = launching_mains[-1]
            _add_parent(first, parent, 0.50, "latest_selected_main_before_subagent_start")
        for previous, current in pairwise(group_candidates):
            _add_parent(current, previous, 0.90, "previous_selected_request_in_subagent_group")


def _longest_parent_prefix_tokens(candidate: _Candidate) -> int:
    max_blocks = 0
    for parent, _, _ in candidate.parents:
        blocks = 0
        for current_hash, parent_hash in zip(candidate.hash_ids, parent.hash_ids, strict=False):
            if current_hash != parent_hash:
                break
            blocks += 1
        max_blocks = max(max_blocks, blocks)
    return max_blocks * SOURCE_BLOCK_SIZE


def _normalized_record(candidate: _Candidate) -> dict[str, Any]:
    sorted_parents = sorted(
        candidate.parents,
        key=lambda item: (item[0].submit_ns, item[0].source_order, item[0].span_id),
    )
    parent_edges = [
        {
            "parent_span_id": parent.span_id,
            "origin": "inferred",
            "confidence": confidence,
            "inference_rule": rule,
        }
        for parent, confidence, rule in sorted_parents
    ]
    if parent_edges:
        parent_origin = "inferred"
        parent_confidence: float | None = min(edge["confidence"] for edge in parent_edges)
        release_rule = "parent_completion_plus_recorded_delay"
    else:
        parent_origin = "none"
        parent_confidence = None
        release_rule = "observed_root_arrival"
    group_document: dict[str, Any] | None = None
    if candidate.group is not None:
        group_document = {
            "group_id": candidate.group.group_id,
            "subagent_type": candidate.group.subagent_type,
            "status": candidate.group.status,
            "duration_ns": candidate.group.duration_ns,
            "tool_use_count": candidate.group.tool_use_count,
        }
    record = {
        "schema": "moonkvsim.multi_agent_trace.v1",
        "workflow_id": candidate.workflow_id,
        "session_id": candidate.workflow_id,
        "agent_id": candidate.agent_id,
        "agent_role": candidate.role,
        "span_id": candidate.span_id,
        "parent_span_ids": [edge["parent_span_id"] for edge in parent_edges],
        "parent_edges": parent_edges,
        "parent_edge_origin": parent_origin,
        "parent_edge_confidence": parent_confidence,
        "observed_submit_ns": candidate.submit_ns,
        "observed_finish_ns": candidate.finish_ns,
        "recorded_api_time_ns": candidate.api_time_ns,
        "messages_or_token_ids": None,
        "prompt_token_ids_hash": None,
        "source_hash_ids": candidate.hash_ids,
        "source_hash_ids_sha256": _source_hash_ids_sha256(candidate.hash_ids),
        "prompt_tokens": candidate.prompt_tokens,
        "cached_prefix_tokens": _longest_parent_prefix_tokens(candidate),
        "output_tokens": candidate.output_tokens,
        "total_model_tokens": candidate.total_tokens,
        "tool_name": None,
        "tool_delay_ns": candidate.tool_delay_ns,
        "dependency_release_rule": release_rule,
        "retry_of_span_id": None,
        "model_id": candidate.model_id,
        "model_revision": None,
        "token_count_mode": TOKEN_COUNT_MODE,
        "tokenizer_fingerprint": "not_available_source_hash_blocks_64",
        "source_block_size_tokens": SOURCE_BLOCK_SIZE,
        "source_hash_id_scope_raw": RAW_HASH_ID_SCOPE,
        "hash_id_scope": HASH_ID_SCOPE,
        "evidence_class": EVIDENCE_CLASS,
        "synthetic": False,
        "truncated": False,
        "model_length_guard_passed": True,
        "source_position": {
            "workflow_line": candidate.workflow_line,
            "top_level_index": candidate.top_level_index,
            "inner_index": candidate.inner_index,
        },
        "raw_request_type": candidate.raw_request_type,
        "subagent_group": group_document,
    }
    validate_trace_span(record)
    return record


def _normalize_workflow(
    raw_workflow: Mapping[str, Any], workflow_line: int, coverage: _CoverageAccumulator
) -> list[dict[str, Any]]:
    where = f"workflow line {workflow_line}"
    _require_fields(
        raw_workflow,
        _TOP_LEVEL_FIELDS,
        {"id", "models", "block_size", "hash_id_scope", "requests"},
        where,
    )
    workflow_id = _require_string(raw_workflow["id"], f"{where}.id")
    if raw_workflow["block_size"] != SOURCE_BLOCK_SIZE:
        raise WekaTraceError(
            f"{where}.block_size: expected {SOURCE_BLOCK_SIZE}, got {raw_workflow['block_size']!r}"
        )
    raw_hash_id_scope = _require_string(
        raw_workflow["hash_id_scope"], f"{where}.hash_id_scope"
    )
    if raw_hash_id_scope != RAW_HASH_ID_SCOPE:
        raise WekaTraceError(
            f"{where}.hash_id_scope: expected locked raw value {RAW_HASH_ID_SCOPE!r}, "
            f"got {raw_hash_id_scope!r}"
        )
    coverage.add_workflow(workflow_id, raw_hash_id_scope)
    models = raw_workflow["models"]
    if not isinstance(models, list) or not all(
        isinstance(model, str) and model for model in models
    ):
        raise WekaTraceError(f"{where}.models: expected an array of non-empty strings")
    raw_requests = raw_workflow["requests"]
    if not isinstance(raw_requests, list):
        raise WekaTraceError(f"{where}.requests: expected an array")

    selected: list[_Candidate] = []
    for top_level_index, raw_item in enumerate(raw_requests):
        if not isinstance(raw_item, Mapping):
            raise WekaTraceError(f"{where}.requests[{top_level_index}]: expected an object")
        if raw_item.get("type") == "subagent" or "requests" in raw_item:
            _, group_candidates = _parse_subagent_group(
                raw_item,
                workflow_id=workflow_id,
                workflow_line=workflow_line,
                top_level_index=top_level_index,
            )
            for candidate in group_candidates:
                if coverage.add_request(candidate):
                    selected.append(candidate)
        else:
            candidate = _parse_request(
                raw_item,
                workflow_id=workflow_id,
                workflow_line=workflow_line,
                top_level_index=top_level_index,
                inner_index=None,
                role="main",
                agent_id="main",
                group=None,
            )
            if coverage.add_request(candidate):
                selected.append(candidate)

    _infer_edges(selected)
    selected.sort(
        key=lambda candidate: (candidate.submit_ns, candidate.source_order, candidate.span_id)
    )
    return [_normalized_record(candidate) for candidate in selected]


def _iter_raw_workflows(
    stream: BinaryIO, raw_hasher: Any
) -> Iterator[tuple[int, Mapping[str, Any]]]:
    for line_number, raw_line in enumerate(stream, start=1):
        raw_hasher.update(raw_line)
        if not raw_line.strip():
            raise WekaTraceError(f"line {line_number}: blank lines are forbidden")
        try:
            workflow = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WekaTraceError(f"line {line_number}: invalid UTF-8 JSON: {error}") from error
        if not isinstance(workflow, Mapping):
            raise WekaTraceError(f"line {line_number}: workflow must be an object")
        yield line_number, workflow


def _verify_raw_hash(actual: str, expected: str | None) -> None:
    if expected is not None and actual.lower() != expected.lower():
        raise WekaTraceError(
            f"raw SHA256 mismatch: expected {expected.lower()}, got {actual.lower()}"
        )


def _normalizer_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def audit_weka_trace(
    input_path: str | Path, *, expected_raw_sha256: str | None = None
) -> dict[str, Any]:
    """Read the raw file once without writing and return its strict 128K audit."""

    path = Path(input_path)
    raw_hasher = hashlib.sha256()
    coverage = _CoverageAccumulator()
    try:
        with path.open("rb") as stream:
            for line_number, workflow in _iter_raw_workflows(stream, raw_hasher):
                _normalize_workflow(workflow, line_number, coverage)
    except OSError as error:
        raise WekaTraceError(f"cannot read raw trace {path}: {error}") from error
    raw_sha256 = raw_hasher.hexdigest()
    _verify_raw_hash(raw_sha256, expected_raw_sha256)
    document = coverage.to_document(raw_sha256)
    document["normalizer_source_sha256"] = _normalizer_source_sha256()
    document["mode"] = "read_only_audit"
    return document


def _write_json_atomic(path: Path, document: Mapping[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {path}; pass overwrite=True explicitly")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical_json_bytes(document))
            stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def normalize_weka_trace(
    input_path: str | Path,
    output_path: str | Path,
    *,
    expected_raw_sha256: str | None = None,
    manifest_path: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Normalize to canonical JSONL without truncation, padding, or resampling."""

    source = Path(input_path)
    destination = Path(output_path)
    if source.resolve() == destination.resolve():
        raise WekaTraceError("input and output paths must differ; the raw trace is read-only")
    if destination.exists() and not overwrite:
        raise FileExistsError(
            f"refusing to overwrite {destination}; pass overwrite=True explicitly"
        )
    if manifest_path is not None and Path(manifest_path).resolve() == source.resolve():
        raise WekaTraceError("manifest path cannot overwrite the raw trace")

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temporary_path = Path(temporary_name)
    raw_hasher = hashlib.sha256()
    normalized_hasher = hashlib.sha256()
    coverage = _CoverageAccumulator()
    normalized_count = 0
    try:
        with source.open("rb") as raw_stream, os.fdopen(descriptor, "wb") as output_stream:
            for line_number, workflow in _iter_raw_workflows(raw_stream, raw_hasher):
                for record in _normalize_workflow(workflow, line_number, coverage):
                    serialized = _canonical_json_bytes(record) + b"\n"
                    output_stream.write(serialized)
                    normalized_hasher.update(serialized)
                    normalized_count += 1
            output_stream.flush()
            os.fsync(output_stream.fileno())
        raw_sha256 = raw_hasher.hexdigest()
        _verify_raw_hash(raw_sha256, expected_raw_sha256)
        os.replace(temporary_path, destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise

    manifest = coverage.to_document(raw_sha256)
    manifest.update(
        {
            "mode": "normalized",
            "normalizer_source_sha256": _normalizer_source_sha256(),
            "normalized": {
                "path": str(destination),
                "sha256": normalized_hasher.hexdigest(),
                "record_count": normalized_count,
                "ordering": "workflow_line,observed_submit_ns,source_position,span_id",
                "serialization": "utf8-canonical-jsonl-sort-keys",
            },
        }
    )
    if manifest_path is not None:
        _write_json_atomic(Path(manifest_path), manifest, overwrite=overwrite)
    return manifest
