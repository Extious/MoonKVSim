from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from moonkvsim.aegiskv.experiment_suite import load_frozen_workload
from moonkvsim.aegiskv.odr import (
    ODRDurationModel,
    ODRTraceError,
    normalize_odr_corpus,
    normalize_odr_trace,
    prepare_odr_workload,
)


def _odr_trace() -> dict[str, object]:
    return {
        "trace_id": "deep-research-test-0",
        "events": [
            {
                "event_type": "message",
                "branch_path": [],
                "conversation_id": 0,
                "role": "system",
                "message_index": 0,
                "tokens": 130,
                "system_prompt_id": "odr-supervisor-v1",
            },
            {
                "event_type": "message",
                "branch_path": [],
                "conversation_id": 0,
                "role": "user",
                "message_index": 1,
                "tokens": 20,
            },
            {
                "event_type": "message",
                "branch_path": [],
                "conversation_id": 0,
                "role": "assistant",
                "message_index": 2,
                "prompt_tokens": 130,
                "completion_tokens": 10,
                "llm_duration_ms": 2.0,
            },
            {
                "event_type": "tool_call",
                "branch_path": [],
                "tool_call_id": "fork",
                "tool_name": "spawn_researchers",
                "duration_ms": 3.0,
            },
            {"event_type": "parallel_start", "branch_path": [], "num_branches": 2},
            {
                "event_type": "message",
                "branch_path": [0],
                "conversation_id": 1,
                "role": "system",
                "message_index": 0,
                "tokens": 64,
                "system_prompt_id": "odr-supervisor-v1",
            },
            {
                "event_type": "message",
                "branch_path": [0],
                "conversation_id": 1,
                "role": "assistant",
                "message_index": 1,
                "prompt_tokens": 65,
                "completion_tokens": 5,
            },
            {
                "event_type": "tool_call",
                "branch_path": [0],
                "tool_call_id": "search-0",
                "tool_name": "web_search",
                "duration_ms": 4.0,
            },
            {
                "event_type": "message",
                "branch_path": [0],
                "conversation_id": 1,
                "role": "assistant",
                "message_index": 2,
                "prompt_tokens": 129,
                "completion_tokens": 5,
            },
            {
                "event_type": "message",
                "branch_path": [1],
                "conversation_id": 2,
                "role": "system",
                "message_index": 0,
                "tokens": 64,
                "system_prompt_id": "odr-supervisor-v1",
            },
            {
                "event_type": "message",
                "branch_path": [1],
                "conversation_id": 2,
                "role": "assistant",
                "message_index": 1,
                "prompt_tokens": 64,
                "completion_tokens": 5,
            },
            {"event_type": "parallel_end", "branch_path": []},
            {
                "event_type": "message",
                "branch_path": [],
                "conversation_id": 0,
                "role": "assistant",
                "message_index": 3,
                "prompt_tokens": 257,
                "completion_tokens": 10,
                "llm_duration_ms": 5.0,
            },
        ],
    }


def test_odr_adapter_preserves_fork_join_tool_delays_and_partial_blocks() -> None:
    result = normalize_odr_trace(
        _odr_trace(),
        duration_model=ODRDurationModel(
            prefill_ns_per_token=1_000,
            decode_ns_per_token=10_000,
        ),
    )
    records = list(result.records)

    assert result.assistant_count == 5
    assert result.tool_call_count == 2
    assert result.parallel_region_count == 1
    assert result.max_fan_out == 2
    root, left_first, left_second, right, final = records
    assert root["parent_span_ids"] == []
    assert left_first["parent_span_ids"] == [root["span_id"]]
    assert right["parent_span_ids"] == [root["span_id"]]
    assert left_second["parent_span_ids"] == [left_first["span_id"]]
    assert final["parent_span_ids"] == [left_second["span_id"], right["span_id"]]
    assert left_first["tool_delay_ns"] == 3_000_000
    assert right["tool_delay_ns"] == 3_000_000
    assert left_second["tool_delay_ns"] == 4_000_000
    assert root["source_hash_block_token_counts"] == [64, 64, 2]
    assert left_first["source_hash_block_token_counts"] == [64, 1]
    assert root["source_hash_ids"][0] == left_first["source_hash_ids"][0]
    assert root["source_hash_block_scopes"][:2] == [
        "global_system_template",
        "global_system_template",
    ]
    assert left_first["raw_request_type"].endswith(
        "explicit_uncalibrated_duration_model"
    )
    assert final["raw_request_type"].endswith("observed_llm_duration_ms")


def test_compact_odr_requires_explicit_duration_model() -> None:
    with pytest.raises(ODRTraceError, match="explicit duration model"):
        normalize_odr_trace(_odr_trace())


def test_odr_rejects_whole_task_on_any_context_overflow() -> None:
    trace = deepcopy(_odr_trace())
    trace["events"][6]["prompt_tokens"] = 131_070  # type: ignore[index]
    with pytest.raises(ODRTraceError, match="whole-task model guard"):
        normalize_odr_trace(trace, duration_model=ODRDurationModel(1, 1))


def test_odr_rejects_dangling_tool_delay_at_branch_end() -> None:
    trace = deepcopy(_odr_trace())
    trace["events"].insert(11, {  # type: ignore[union-attr]
        "event_type": "tool_call",
        "branch_path": [1],
        "tool_name": "dangling",
        "duration_ms": 1,
    })
    with pytest.raises(ODRTraceError, match="unattached tool delay"):
        normalize_odr_trace(trace, duration_model=ODRDurationModel(1, 1))


def test_odr_corpus_rejects_duplicate_trace_ids() -> None:
    trace = _odr_trace()
    with pytest.raises(ODRTraceError, match="trace_id values must be unique"):
        normalize_odr_corpus(
            [trace, deepcopy(trace)],
            duration_model=ODRDurationModel(1, 1),
        )


def test_odr_prepare_publishes_manifest_accepted_by_experiment_loader(
    tmp_path: Path,
) -> None:
    final_prompts = (1_000, 10_000, 40_000, 70_000, 100_000)
    traces = []
    for index, final_prompt in enumerate(final_prompts):
        trace = deepcopy(_odr_trace())
        trace["trace_id"] = f"deep-research-test-{index}"
        trace["events"][-1]["prompt_tokens"] = final_prompt  # type: ignore[index]
        traces.append(trace)
    source = tmp_path / "official-odr.json"
    source.write_text(json.dumps(traces), encoding="utf-8")
    output = tmp_path / "odr.jsonl"
    manifest_path = tmp_path / "odr-manifest.json"

    manifest = prepare_odr_workload(
        source=source,
        output_path=output,
        manifest_path=manifest_path,
        source_revision="official-test-revision",
        source_license="Apache-2.0",
        expected_task_count=5,
        minimum_task_count_for_ecdf=1,
        duration_model=ODRDurationModel(1, 8),
    )
    records, binding, loaded_manifest = load_frozen_workload(output, manifest_path)

    assert manifest == loaded_manifest
    assert binding.workload_kind == "odr_complete_tasks"
    assert binding.record_count == len(records) == 25
    assert manifest["selection"]["audit"]["task_count"] == 5
