"""Fail-closed NVIDIA Open Deep Research trace normalization.

The adapter follows TensorRT-LLM's public ``ExecutionTrace`` semantics: a
``parallel_start`` is a barrier after the parent branch, child ``branch_path``
queues execute independently, and ``parallel_end`` joins every child before
the parent continues.  Only assistant messages become model-request spans;
tool durations are preserved as causal release delays.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from moonkvsim.aegiskv.experiment import (
    QWEN3_8B_MODEL_ID,
    QWEN3_8B_MODEL_REVISION,
)
from moonkvsim.aegiskv.experiment_workload import CONTEXT_BUCKETS, bucket_name_for
from moonkvsim.common.hash import sha256_json
from moonkvsim.workload.causal_trace import load_normalized_trace_records

ODR_NORMALIZER_SCHEMA: Final = "moonkvsim.aegiskv.odr_normalizer.v1"
SOURCE_BLOCK_TOKENS: Final = 64


class ODRTraceError(ValueError):
    """An ODR task cannot be replayed without changing its observed shape."""


@dataclass(frozen=True, slots=True)
class ODRDurationModel:
    """Explicit uncalibrated timing fallback for compact ODR traces."""

    prefill_ns_per_token: int
    decode_ns_per_token: int

    def __post_init__(self) -> None:
        if (
            type(self.prefill_ns_per_token) is not int
            or self.prefill_ns_per_token <= 0
            or type(self.decode_ns_per_token) is not int
            or self.decode_ns_per_token <= 0
        ):
            raise ValueError("ODR duration rates must be positive integer ns/token")

    def duration_ns(self, prompt_tokens: int, completion_tokens: int) -> int:
        return max(
            1,
            prompt_tokens * self.prefill_ns_per_token
            + completion_tokens * self.decode_ns_per_token,
        )

    def to_dict(self) -> dict[str, int | str]:
        return {
            "kind": "explicit_uncalibrated_linear_token_model",
            "prefill_ns_per_token": self.prefill_ns_per_token,
            "decode_ns_per_token": self.decode_ns_per_token,
        }


@dataclass(frozen=True, slots=True)
class ODRNormalizationResult:
    trace_id: str
    records: tuple[dict[str, Any], ...]
    assistant_count: int
    tool_call_count: int
    parallel_region_count: int
    max_fan_out: int
    duration_sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ParallelFrame:
    parent_path: tuple[int, ...]
    child_paths: tuple[tuple[int, ...], ...]


def normalize_odr_trace(
    document: Mapping[str, Any],
    *,
    workflow_line: int = 1,
    duration_model: ODRDurationModel | None = None,
    max_model_len_tokens: int = 131_072,
    require_parallel: bool = True,
) -> ODRNormalizationResult:
    """Convert one complete ODR ``ExecutionTrace`` into a closed causal DAG."""

    if type(workflow_line) is not int or workflow_line <= 0:
        raise ODRTraceError("workflow_line must be a positive integer")
    if type(max_model_len_tokens) is not int or max_model_len_tokens <= 0:
        raise ODRTraceError("max_model_len_tokens must be a positive integer")
    trace_id = _non_empty_string(document.get("trace_id"), "trace_id")
    raw_events = document.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise ODRTraceError(f"trace {trace_id!r} has no events")
    if not all(isinstance(event, Mapping) for event in raw_events):
        raise ODRTraceError(f"trace {trace_id!r} events must all be objects")

    records: list[dict[str, Any]] = []
    open_branches: set[tuple[int, ...]] = {()}
    suspended_branches: set[tuple[int, ...]] = set()
    frames: list[_ParallelFrame] = []
    last_span_by_branch: dict[tuple[int, ...], str] = {}
    first_parents_by_branch: dict[tuple[int, ...], tuple[str, ...]] = {}
    pending_join_by_branch: dict[tuple[int, ...], tuple[str, ...]] = {}
    pending_tool_delay_ns: defaultdict[tuple[int, ...], int] = defaultdict(int)
    pending_tool_names: defaultdict[tuple[int, ...], list[str]] = defaultdict(list)
    tool_count_by_branch: defaultdict[tuple[int, ...], int] = defaultdict(int)
    system_by_conversation: dict[tuple[tuple[int, ...], int], tuple[str, int]] = {}
    seen_message_indices: set[tuple[tuple[int, ...], int, int]] = set()
    duration_sources: set[str] = set()
    parallel_region_count = 0
    max_fan_out = 0
    tool_call_count = 0

    for event_index, event in enumerate(raw_events):
        event_type = _non_empty_string(
            event.get("event_type"), f"events[{event_index}].event_type"
        )
        branch_path = _branch_path(event.get("branch_path", []), event_index)

        if event_type == "parallel_start":
            _require_routable_branch(
                branch_path,
                open_branches,
                suspended_branches,
                event_index,
            )
            raw_fan_out = event.get("num_branches")
            if type(raw_fan_out) is not int or raw_fan_out <= 0:
                raise ODRTraceError(
                    f"events[{event_index}].num_branches must be a positive integer"
                )
            fork_parents = pending_join_by_branch.pop(branch_path, None)
            if fork_parents is None:
                last_parent = last_span_by_branch.get(branch_path)
                if last_parent is None:
                    raise ODRTraceError(
                        f"events[{event_index}] parallel_start has no completed parent request"
                    )
                fork_parents = (last_parent,)
            fork_delay_ns = pending_tool_delay_ns.pop(branch_path, 0)
            fork_tool_names = pending_tool_names.pop(branch_path, [])
            children = tuple((*branch_path, index) for index in range(raw_fan_out))
            if any(child in open_branches for child in children):
                raise ODRTraceError(f"events[{event_index}] reuses an open child branch")
            for child in children:
                open_branches.add(child)
                first_parents_by_branch[child] = fork_parents
                if fork_delay_ns:
                    pending_tool_delay_ns[child] += fork_delay_ns
                    pending_tool_names[child].extend(fork_tool_names)
            suspended_branches.add(branch_path)
            frames.append(_ParallelFrame(branch_path, children))
            parallel_region_count += 1
            max_fan_out = max(max_fan_out, raw_fan_out)
            continue

        if event_type == "parallel_end":
            if not frames:
                raise ODRTraceError(f"events[{event_index}] parallel_end has no open region")
            frame = frames.pop()
            if branch_path != frame.parent_path:
                raise ODRTraceError(
                    f"events[{event_index}] parallel_end path does not match the open parent"
                )
            endpoints: list[str] = []
            for child in frame.child_paths:
                if pending_tool_delay_ns.get(child, 0):
                    raise ODRTraceError(
                        f"events[{event_index}] child {list(child)} ends with an "
                        "unattached tool delay"
                    )
                child_endpoints = pending_join_by_branch.pop(child, None)
                if child_endpoints is None:
                    child_last = last_span_by_branch.get(child)
                    if child_last is None:
                        raise ODRTraceError(
                            f"events[{event_index}] child {list(child)} has no assistant request"
                        )
                    child_endpoints = (child_last,)
                endpoints.extend(child_endpoints)
                open_branches.remove(child)
                suspended_branches.discard(child)
                first_parents_by_branch.pop(child, None)
            pending_join_by_branch[frame.parent_path] = tuple(dict.fromkeys(endpoints))
            suspended_branches.remove(frame.parent_path)
            continue

        _require_routable_branch(
            branch_path,
            open_branches,
            suspended_branches,
            event_index,
        )
        if event_type == "drop_kv_cache":
            raise ODRTraceError(
                f"events[{event_index}] drop_kv_cache is not supported by the AegisKV "
                "workload schema"
            )
        if event_type == "tool_call":
            duration_ms = _non_negative_number(
                event.get("duration_ms", 0), f"events[{event_index}].duration_ms"
            )
            duration_ns = math.ceil(duration_ms * 1_000_000)
            pending_tool_delay_ns[branch_path] += duration_ns
            tool_name = event.get("tool_name")
            if tool_name is not None:
                pending_tool_names[branch_path].append(
                    _non_empty_string(tool_name, f"events[{event_index}].tool_name")
                )
            tool_count_by_branch[branch_path] += 1
            tool_call_count += 1
            continue
        if event_type != "message":
            raise ODRTraceError(f"events[{event_index}] has unsupported type {event_type!r}")

        role = _non_empty_string(event.get("role"), f"events[{event_index}].role")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ODRTraceError(f"events[{event_index}].role is unsupported: {role!r}")
        conversation_id = _non_negative_int(
            event.get("conversation_id"), f"events[{event_index}].conversation_id"
        )
        message_index = _non_negative_int(
            event.get("message_index"), f"events[{event_index}].message_index"
        )
        message_key = (branch_path, conversation_id, message_index)
        if message_key in seen_message_indices:
            raise ODRTraceError(f"events[{event_index}] duplicates a conversation message index")
        seen_message_indices.add(message_key)

        if role == "system":
            system_tokens = _non_negative_int(
                event.get("tokens", 0), f"events[{event_index}].tokens"
            )
            system_prompt_id = event.get("system_prompt_id")
            if system_prompt_id is not None:
                system_by_conversation[(branch_path, conversation_id)] = (
                    _non_empty_string(
                        system_prompt_id,
                        f"events[{event_index}].system_prompt_id",
                    ),
                    system_tokens,
                )
        if role != "assistant":
            continue

        prompt_tokens = _non_negative_int(
            event.get("prompt_tokens"), f"events[{event_index}].prompt_tokens"
        )
        completion_tokens = _positive_int(
            event.get("completion_tokens"),
            f"events[{event_index}].completion_tokens",
        )
        total_tokens = prompt_tokens + completion_tokens
        if total_tokens > max_model_len_tokens:
            raise ODRTraceError(
                f"trace {trace_id!r} exceeds the whole-task model guard at "
                f"events[{event_index}]: {total_tokens} > {max_model_len_tokens}"
            )
        duration_ns, duration_source = _duration_for_event(
            event,
            event_index=event_index,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_model=duration_model,
        )
        duration_sources.add(duration_source)

        parents = pending_join_by_branch.pop(branch_path, None)
        if parents is None:
            last_span = last_span_by_branch.get(branch_path)
            if last_span is not None:
                parents = (last_span,)
            else:
                parents = first_parents_by_branch.pop(branch_path, ())
        parents = tuple(dict.fromkeys(parents))
        span_id = f"odr:{trace_id}:event-{event_index}"
        source_hashes, block_counts, block_scopes = _source_shape(
            trace_id=trace_id,
            branch_path=branch_path,
            conversation_id=conversation_id,
            prompt_tokens=prompt_tokens,
            system=system_by_conversation.get((branch_path, conversation_id)),
        )
        tool_delay_ns = pending_tool_delay_ns.pop(branch_path, 0)
        tool_names = pending_tool_names.pop(branch_path, [])
        parent_edges = [
            {
                "parent_span_id": parent_id,
                "origin": "observed",
                "confidence": 1.0,
                "inference_rule": None,
            }
            for parent_id in parents
        ]
        is_root = not parents
        global_blocks = any(scope == "global_system_template" for scope in block_scopes)
        record: dict[str, Any] = {
            "schema": "moonkvsim.multi_agent_trace.v1",
            "workflow_id": trace_id,
            "session_id": trace_id,
            "agent_id": _agent_id(branch_path),
            "agent_role": "main" if not branch_path else "subagent",
            "span_id": span_id,
            "parent_span_ids": list(parents),
            "parent_edges": parent_edges,
            "parent_edge_origin": "none" if is_root else "observed",
            "parent_edge_confidence": None if is_root else 1.0,
            "observed_submit_ns": 0,
            "observed_finish_ns": duration_ns,
            "recorded_api_time_ns": duration_ns,
            "messages_or_token_ids": None,
            "prompt_token_ids_hash": None,
            "source_hash_ids": source_hashes,
            "source_hash_block_token_counts": block_counts,
            "source_hash_block_scopes": block_scopes,
            "source_hash_ids_sha256": sha256_json(source_hashes),
            "prompt_tokens": prompt_tokens,
            "cached_prefix_tokens": 0,
            "output_tokens": completion_tokens,
            "total_model_tokens": total_tokens,
            "tool_name": ",".join(dict.fromkeys(tool_names)) or None,
            "tool_delay_ns": tool_delay_ns,
            "dependency_release_rule": (
                "observed_root_arrival"
                if is_root
                else "parent_completion_plus_recorded_delay"
            ),
            "retry_of_span_id": None,
            "model_id": QWEN3_8B_MODEL_ID,
            "model_revision": QWEN3_8B_MODEL_REVISION,
            "token_count_mode": "source_hash_blocks_64",
            "tokenizer_fingerprint": "not_available_source_hash_blocks_64",
            "source_block_size_tokens": SOURCE_BLOCK_TOKENS,
            "source_hash_id_scope_raw": "mixed" if global_blocks else "local",
            "hash_id_scope": (
                "global_system_template_and_within_workflow"
                if global_blocks
                else "within_workflow_only"
            ),
            "evidence_class": "real_trace_shape_replay",
            "synthetic": False,
            "truncated": False,
            "model_length_guard_passed": True,
            "source_position": {
                "workflow_line": workflow_line,
                "top_level_index": event_index,
                "inner_index": None,
            },
            "raw_request_type": f"odr_assistant_generation:{duration_source}",
            "subagent_group": (
                None
                if not branch_path
                else {
                    "group_id": f"odr:{trace_id}:branch:{_branch_label(branch_path)}",
                    "subagent_type": "odr_parallel_branch",
                    "status": "observed_complete",
                    "duration_ns": 0,
                    "tool_use_count": tool_count_by_branch[branch_path],
                }
            ),
        }
        records.append(record)
        last_span_by_branch[branch_path] = span_id

    if frames:
        raise ODRTraceError(f"trace {trace_id!r} has unclosed parallel regions")
    dangling_tools = {
        path: delay for path, delay in pending_tool_delay_ns.items() if delay > 0
    }
    if dangling_tools:
        raise ODRTraceError(f"trace {trace_id!r} ends with unattached tool delays")
    if require_parallel and parallel_region_count == 0:
        raise ODRTraceError(f"trace {trace_id!r} has no explicit fan-out/fan-in region")
    terminal = pending_join_by_branch.get(())
    if terminal is not None and len(terminal) != 1:
        raise ODRTraceError(
            f"trace {trace_id!r} has no unique final root request after fan-in"
        )
    if not records or () not in last_span_by_branch:
        raise ODRTraceError(f"trace {trace_id!r} has no root assistant request")
    if _sink_span_ids(records) != {last_span_by_branch[()]}:
        raise ODRTraceError(f"trace {trace_id!r} does not end in one root-branch sink")

    # Reuse the repository schema and full-DAG validator at the adapter boundary.
    load_normalized_trace_records(records)
    return ODRNormalizationResult(
        trace_id=trace_id,
        records=tuple(records),
        assistant_count=len(records),
        tool_call_count=tool_call_count,
        parallel_region_count=parallel_region_count,
        max_fan_out=max_fan_out,
        duration_sources=tuple(sorted(duration_sources)),
    )


def normalize_odr_corpus(
    documents: Sequence[Mapping[str, Any]],
    *,
    duration_model: ODRDurationModel | None = None,
    max_model_len_tokens: int = 131_072,
) -> tuple[ODRNormalizationResult, ...]:
    """Normalize a corpus while rejecting duplicate task identities."""

    if not documents:
        raise ODRTraceError("ODR corpus is empty")
    results = tuple(
        normalize_odr_trace(
            document,
            workflow_line=index,
            duration_model=duration_model,
            max_model_len_tokens=max_model_len_tokens,
        )
        for index, document in enumerate(documents, start=1)
    )
    trace_ids = [result.trace_id for result in results]
    if len(set(trace_ids)) != len(trace_ids):
        raise ODRTraceError("ODR corpus trace_id values must be unique")
    return results


def load_odr_documents(
    source: Path,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, str], ...]]:
    """Load one official trace file, a JSON array, or a directory of trace files."""

    resolved = source.resolve()
    if resolved.is_dir():
        paths = tuple(sorted(resolved.rglob("*.json")))
        if not paths:
            raise ODRTraceError(f"ODR source directory has no JSON files: {resolved}")
    elif resolved.is_file():
        paths = (resolved,)
    else:
        raise ODRTraceError(f"ODR source does not exist: {resolved}")
    documents: list[dict[str, Any]] = []
    provenance: list[dict[str, str]] = []
    for path in paths:
        try:
            raw = path.read_bytes()
            value = json.loads(raw)
        except (OSError, json.JSONDecodeError) as error:
            raise ODRTraceError(f"cannot load ODR source {path}: {error}") from error
        items = value if isinstance(value, list) else [value]
        if not all(isinstance(item, dict) for item in items):
            raise ODRTraceError(f"ODR source {path} must contain trace objects")
        documents.extend(items)
        provenance.append(
            {
                "path": path.as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return tuple(documents), tuple(provenance)


def prepare_odr_workload(
    *,
    source: Path,
    output_path: Path,
    manifest_path: Path,
    source_revision: str,
    source_license: str,
    expected_task_count: int = 100,
    minimum_task_count_for_ecdf: int = 30,
    duration_model: ODRDurationModel | None = None,
    max_model_len_tokens: int = 131_072,
) -> dict[str, Any]:
    """Freeze an official ODR corpus without mutating ``requests.json``."""

    if not source_revision or not source_license:
        raise ODRTraceError("source revision and license must be recorded")
    if type(expected_task_count) is not int or expected_task_count <= 0:
        raise ODRTraceError("expected_task_count must be a positive integer")
    if type(minimum_task_count_for_ecdf) is not int or minimum_task_count_for_ecdf <= 0:
        raise ODRTraceError("minimum_task_count_for_ecdf must be a positive integer")
    declared_output_path = output_path.as_posix()
    output = output_path.resolve()
    manifest_file = manifest_path.resolve()
    if output.exists() or manifest_file.exists():
        raise ODRTraceError("ODR frozen output and manifest must not already exist")

    documents, source_files = load_odr_documents(source)
    if len(documents) != expected_task_count:
        raise ODRTraceError(
            f"official ODR corpus must contain {expected_task_count} tasks, "
            f"found {len(documents)}"
        )
    results = normalize_odr_corpus(
        documents,
        duration_model=duration_model,
        max_model_len_tokens=max_model_len_tokens,
    )
    if len(results) < minimum_task_count_for_ecdf:
        raise ODRTraceError("ODR corpus is too small for the configured task-level ECDF")
    records = tuple(record for result in results for record in result.records)
    jsonl = b"".join(
        (
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        for record in records
    )
    bucket_counts = {bucket.name: 0 for bucket in CONTEXT_BUCKETS}
    for record in records:
        bucket_counts[bucket_name_for(int(record["total_model_tokens"]))] += 1
    missing_buckets = sorted(name for name, count in bucket_counts.items() if count == 0)
    if missing_buckets:
        raise ODRTraceError(
            "ODR corpus cannot drive the current context-stratified suite; missing buckets: "
            f"{missing_buckets}"
        )

    artifact_sha256 = hashlib.sha256(jsonl).hexdigest()
    semantic_fingerprint = sha256_json(records)
    manifest: dict[str, Any] = {
        "schema": "moonkvsim.aegiskv.experiment_workload_manifest.v1",
        "status": "pass",
        "evidence": {
            "class": "E2",
            "scope": "modeled/preliminary",
            "calibration": "not_calibrated",
            "physical_execution": False,
            "paper_ready": False,
        },
        "source": {
            "dataset": "NVIDIA TensorRT-LLM Open Deep Research",
            "revision": source_revision,
            "license": source_license,
            "files": list(source_files),
            "expected_task_count": expected_task_count,
        },
        "normalizer": {
            "schema": ODR_NORMALIZER_SCHEMA,
            "topology": "explicit_parallel_start_end",
            "duration_model": None if duration_model is None else duration_model.to_dict(),
            "compact_trace_requires_explicit_duration_model": True,
        },
        "artifact": {
            "path": declared_output_path,
            "sha256": artifact_sha256,
            "record_count": len(records),
            "semantic_fingerprint": semantic_fingerprint,
        },
        "selection": {
            "kind": "complete_odr_tasks_after_whole_task_guard",
            "selected_workflow_ids": [result.trace_id for result in results],
            "no_span_slicing": True,
            "no_cross_workflow_concatenation": True,
            "no_truncation": True,
            "no_padding": True,
            "no_synthesis": True,
            "audit": {
                "task_count": len(results),
                "record_count": len(records),
                "context_bucket_counts": bucket_counts,
                "parallel_region_count": sum(
                    result.parallel_region_count for result in results
                ),
                "max_fan_out": max(result.max_fan_out for result in results),
                "duration_sources": sorted(
                    {source for result in results for source in result.duration_sources}
                ),
                "max_model_len_tokens": max_model_len_tokens,
            },
        },
    }
    manifest["fingerprint"] = sha256_json(manifest)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    output_tmp = output.with_name(f".{output.name}.tmp")
    manifest_tmp = manifest_file.with_name(f".{manifest_file.name}.tmp")
    try:
        output_tmp.write_bytes(jsonl)
        manifest_tmp.write_bytes(manifest_bytes)
        os.replace(output_tmp, output)
        os.replace(manifest_tmp, manifest_file)
    except OSError as error:
        output_tmp.unlink(missing_ok=True)
        manifest_tmp.unlink(missing_ok=True)
        raise ODRTraceError(f"cannot publish ODR frozen workload: {error}") from error
    return manifest


def load_frozen_odr_records(
    path: Path,
    *,
    expected_workflow_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Load and re-audit a frozen ODR JSONL artifact without Weka assumptions."""

    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise ODRTraceError(f"ODR workload line {line_number} is blank")
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ODRTraceError(
                        f"ODR workload line {line_number} is not an object"
                    )
                if value.get("synthetic") is not False or value.get("truncated") is not False:
                    raise ODRTraceError("ODR workload contains synthetic or truncated records")
                if value.get("model_length_guard_passed") is not True:
                    raise ODRTraceError("ODR workload contains a record outside the model guard")
                records.append(value)
    except (OSError, json.JSONDecodeError) as error:
        raise ODRTraceError(f"cannot load frozen ODR workload {path}: {error}") from error
    trace = load_normalized_trace_records(records)
    actual_workflows = sorted({span.workflow_id for span in trace.spans})
    expected = actual_workflows if expected_workflow_ids is None else sorted(expected_workflow_ids)
    if actual_workflows != expected:
        raise ODRTraceError("frozen ODR workflow IDs differ from the manifest selection")
    records_by_workflow: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        records_by_workflow[str(record["workflow_id"])].append(record)
    for workflow_id, workflow_records in records_by_workflow.items():
        roots = [record for record in workflow_records if not record["parent_span_ids"]]
        if len(roots) != 1:
            raise ODRTraceError(f"ODR workflow {workflow_id!r} must have exactly one root")
        if len(_sink_span_ids(workflow_records)) != 1:
            raise ODRTraceError(f"ODR workflow {workflow_id!r} must have exactly one sink")
    return records


def _duration_for_event(
    event: Mapping[str, Any],
    *,
    event_index: int,
    prompt_tokens: int,
    completion_tokens: int,
    duration_model: ODRDurationModel | None,
) -> tuple[int, str]:
    duration_ms = event.get("llm_duration_ms")
    if duration_ms is not None:
        milliseconds = _non_negative_number(
            duration_ms, f"events[{event_index}].llm_duration_ms"
        )
        if milliseconds <= 0:
            raise ODRTraceError(f"events[{event_index}].llm_duration_ms must be positive")
        return max(1, math.ceil(milliseconds * 1_000_000)), "observed_llm_duration_ms"
    if duration_model is None:
        raise ODRTraceError(
            f"events[{event_index}] is a compact ODR assistant event without "
            "llm_duration_ms; an explicit duration model is required"
        )
    return (
        duration_model.duration_ns(prompt_tokens, completion_tokens),
        "explicit_uncalibrated_duration_model",
    )


def _source_shape(
    *,
    trace_id: str,
    branch_path: tuple[int, ...],
    conversation_id: int,
    prompt_tokens: int,
    system: tuple[str, int] | None,
) -> tuple[list[int], list[int], list[str]]:
    block_count = (prompt_tokens + SOURCE_BLOCK_TOKENS - 1) // SOURCE_BLOCK_TOKENS
    counts = [SOURCE_BLOCK_TOKENS] * block_count
    if counts and prompt_tokens % SOURCE_BLOCK_TOKENS:
        counts[-1] = prompt_tokens % SOURCE_BLOCK_TOKENS
    hashes: list[int] = []
    scopes: list[str] = []
    system_prompt_id, system_tokens = system or ("", 0)
    for block_index in range(block_count):
        is_global_system_block = (
            bool(system_prompt_id)
            and (block_index + 1) * SOURCE_BLOCK_TOKENS <= system_tokens
        )
        if is_global_system_block:
            identity = f"odr-system:{system_prompt_id}:block-{block_index}"
            scopes.append("global_system_template")
        else:
            identity = (
                f"odr-workflow:{trace_id}:branch:{_branch_label(branch_path)}:"
                f"conversation:{conversation_id}:block-{block_index}"
            )
            scopes.append("within_workflow")
        hashes.append(int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big"))
    return hashes, counts, scopes


def _sink_span_ids(records: Sequence[Mapping[str, Any]]) -> set[str]:
    span_ids = {str(record["span_id"]) for record in records}
    parent_ids = {
        str(parent_id)
        for record in records
        for parent_id in record["parent_span_ids"]
    }
    return span_ids - parent_ids


def _require_routable_branch(
    branch_path: tuple[int, ...],
    open_branches: set[tuple[int, ...]],
    suspended_branches: set[tuple[int, ...]],
    event_index: int,
) -> None:
    if branch_path not in open_branches:
        raise ODRTraceError(f"events[{event_index}] targets an unopened branch")
    if branch_path in suspended_branches:
        raise ODRTraceError(f"events[{event_index}] targets a parent suspended at fan-out")


def _branch_path(value: object, event_index: int) -> tuple[int, ...]:
    if not isinstance(value, list) or not all(type(item) is int and item >= 0 for item in value):
        raise ODRTraceError(f"events[{event_index}].branch_path must be non-negative integers")
    return tuple(value)


def _agent_id(branch_path: tuple[int, ...]) -> str:
    return "odr-root" if not branch_path else f"odr-branch:{_branch_label(branch_path)}"


def _branch_label(branch_path: tuple[int, ...]) -> str:
    return "root" if not branch_path else ".".join(str(item) for item in branch_path)


def _non_empty_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise ODRTraceError(f"{location} must be a non-empty string")
    return value


def _non_negative_int(value: object, location: str) -> int:
    if type(value) is not int or value < 0:
        raise ODRTraceError(f"{location} must be a non-negative integer")
    return value


def _positive_int(value: object, location: str) -> int:
    result = _non_negative_int(value, location)
    if result == 0:
        raise ODRTraceError(f"{location} must be positive")
    return result


def _non_negative_number(value: object, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ODRTraceError(f"{location} must be a non-negative finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ODRTraceError(f"{location} must be a non-negative finite number")
    return result
