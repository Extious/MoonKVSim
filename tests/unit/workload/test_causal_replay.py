from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from moonkvsim.simulation.event import EventKind, ScheduledEvent
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.workload import (
    CausalReleaseEngine,
    CausalTraceValidationError,
    SpanRuntimeStatus,
    load_normalized_trace_jsonl,
    load_normalized_trace_records,
)

EdgeSpec = tuple[str, str, float, str | None]


def _hash_ids_sha256(hash_ids: list[int]) -> str:
    payload = json.dumps(hash_ids, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _span(
    span_id: str,
    *,
    parents: Iterable[EdgeSpec] = (),
    workflow_id: str = "wf",
    observed_submit_ns: int = 0,
    tool_delay_ns: int = 0,
    top_level_index: int = 0,
) -> dict[str, Any]:
    edge_specs = tuple(parents)
    edges = [
        {
            "parent_span_id": parent_id,
            "origin": origin,
            "confidence": confidence,
            "inference_rule": inference_rule,
        }
        for parent_id, origin, confidence, inference_rule in edge_specs
    ]
    origins = {origin for _, origin, _, _ in edge_specs}
    if not edges:
        parent_origin = "none"
        parent_confidence = None
        dependency_rule = "observed_root_arrival"
    else:
        parent_origin = next(iter(origins)) if len(origins) == 1 else "mixed"
        parent_confidence = min(confidence for _, _, confidence, _ in edge_specs)
        dependency_rule = "parent_completion_plus_recorded_delay"
    hash_ids = [0]
    return {
        "schema": "moonkvsim.multi_agent_trace.v1",
        "workflow_id": workflow_id,
        "session_id": workflow_id,
        "agent_id": "main",
        "agent_role": "main",
        "span_id": span_id,
        "parent_span_ids": [parent_id for parent_id, _, _, _ in edge_specs],
        "parent_edges": edges,
        "parent_edge_origin": parent_origin,
        "parent_edge_confidence": parent_confidence,
        "observed_submit_ns": observed_submit_ns,
        "observed_finish_ns": observed_submit_ns + 1,
        "recorded_api_time_ns": 1,
        "messages_or_token_ids": None,
        "prompt_token_ids_hash": None,
        "source_hash_ids": hash_ids,
        "source_hash_ids_sha256": _hash_ids_sha256(hash_ids),
        "prompt_tokens": 64,
        "cached_prefix_tokens": 0,
        "output_tokens": 1,
        "total_model_tokens": 65,
        "tool_name": None,
        "tool_delay_ns": tool_delay_ns,
        "dependency_release_rule": dependency_rule,
        "retry_of_span_id": None,
        "model_id": "claude-toy",
        "model_revision": None,
        "token_count_mode": "source_hash_blocks_64",
        "tokenizer_fingerprint": "not_available_source_hash_blocks_64",
        "source_block_size_tokens": 64,
        "source_hash_id_scope_raw": "local",
        "hash_id_scope": "within_workflow_only",
        "evidence_class": "real_trace_shape_replay",
        "synthetic": False,
        "truncated": False,
        "model_length_guard_passed": True,
        "source_position": {
            "workflow_line": 1,
            "top_level_index": top_level_index,
            "inner_index": None,
        },
        "raw_request_type": "n",
        "subagent_group": None,
    }


def _run_to_completion(
    records: list[dict[str, Any]],
    durations_ns: dict[str, int],
    *,
    workflow_concurrency: int | None = None,
) -> tuple[CausalReleaseEngine, GlobalDES]:
    trace = load_normalized_trace_records(records)
    des = GlobalDES()
    holder: dict[str, CausalReleaseEngine] = {}

    def complete(event: ScheduledEvent, _des: GlobalDES) -> None:
        span_id = event.payload["span_id"]
        assert isinstance(span_id, str)
        holder["engine"].mark_completed(span_id)

    def on_release(span: object, state: GlobalDES) -> None:
        span_id = span.span_id  # type: ignore[attr-defined]
        state.schedule_after(
            durations_ns[span_id],
            EventKind.REQUEST_COMPLETE,
            payload={"span_id": span_id},
            event_id=f"toy-complete:{span_id}",
        )

    des.register_handler(EventKind.REQUEST_COMPLETE, complete)
    engine = CausalReleaseEngine(
        trace,
        des,
        on_release=on_release,
        workflow_concurrency=workflow_concurrency,
    )
    holder["engine"] = engine
    engine.start()
    des.run()
    return engine, des


def test_fan_out_fan_in_waits_for_all_parents_and_tool_delay() -> None:
    root = _span("root", top_level_index=0)
    left = _span(
        "left",
        parents=[("root", "inferred", 0.8, "timeline")],
        observed_submit_ns=1,
        top_level_index=1,
    )
    right = _span(
        "right",
        parents=[("root", "inferred", 0.7, "timeline")],
        observed_submit_ns=1,
        top_level_index=2,
    )
    join = _span(
        "join",
        parents=[
            ("left", "observed", 1.0, None),
            ("right", "inferred", 0.6, "group_end_before_submit"),
        ],
        observed_submit_ns=2,
        tool_delay_ns=4,
        top_level_index=3,
    )
    engine, des = _run_to_completion(
        [join, right, root, left],
        {"root": 10, "left": 7, "right": 3, "join": 1},
    )

    assert engine.release_order == ("root", "left", "right", "join")
    assert engine.snapshot("root").released_ns == 0
    assert engine.snapshot("left").released_ns == 10
    assert engine.snapshot("right").released_ns == 10
    assert engine.snapshot("right").completed_ns == 13
    assert engine.snapshot("left").completed_ns == 17
    assert engine.snapshot("join").released_ns == 21
    assert engine.snapshot("join").status is SpanRuntimeStatus.COMPLETED
    assert des.now_ns == 22

    join_schedule = next(
        record
        for record in des.journal.records
        if record.record_type == "EVENT_SCHEDULED"
        and record.data["event_id"] == "workload-release:join"
    )
    payload = join_schedule.data["payload"]
    assert payload["parent_edge_origin"] == "mixed"
    assert payload["parent_edge_confidence"] == 0.6
    assert payload["parent_edges"] == [
        {
            "confidence": 1.0,
            "inference_rule": None,
            "origin": "observed",
            "parent_span_id": "left",
        },
        {
            "confidence": 0.6,
            "inference_rule": "group_end_before_submit",
            "origin": "inferred",
            "parent_span_id": "right",
        },
    ]


def test_same_timestamp_release_order_uses_source_metadata_not_input_order() -> None:
    root = _span("root", top_level_index=0)
    first = _span(
        "first",
        parents=[("root", "inferred", 0.5, "timeline")],
        observed_submit_ns=1,
        top_level_index=1,
    )
    second = _span(
        "second",
        parents=[("root", "inferred", 0.5, "timeline")],
        observed_submit_ns=1,
        top_level_index=2,
    )
    engine, _ = _run_to_completion([second, first, root], {"root": 5, "first": 0, "second": 0})
    assert engine.release_order == ("root", "first", "second")
    assert engine.snapshot("first").released_ns == 5
    assert engine.snapshot("second").released_ns == 5


def test_workflow_concurrency_is_closed_loop_and_releases_slot_on_completion() -> None:
    records = [
        _span("root-2", workflow_id="wf-2", top_level_index=0),
        _span("root-0", workflow_id="wf-0", top_level_index=0),
        _span("root-1", workflow_id="wf-1", top_level_index=0),
    ]
    engine, des = _run_to_completion(
        records,
        {"root-0": 5, "root-1": 10, "root-2": 1},
        workflow_concurrency=2,
    )

    assert engine.release_order == ("root-0", "root-1", "root-2")
    assert engine.snapshot("root-0").released_ns == 0
    assert engine.snapshot("root-1").released_ns == 0
    assert engine.snapshot("root-2").released_ns == 5
    admissions = [
        record
        for record in des.journal.records
        if record.record_type == "WORKLOAD_WORKFLOW_ADMITTED"
    ]
    assert [record.data["workflow_id"] for record in admissions] == ["wf-0", "wf-1", "wf-2"]
    assert max(int(record.data["active_workflows"]) for record in admissions) == 2
    assert admissions[-1].data["queue_wait_ns"] == 5


@pytest.mark.parametrize("kind", ["missing", "cross_workflow", "cycle"])
def test_loader_rejects_invalid_dag(kind: str) -> None:
    root = _span("root", top_level_index=0)
    if kind == "missing":
        records = [
            root,
            _span(
                "child",
                parents=[("absent", "inferred", 0.5, "timeline")],
                top_level_index=1,
            ),
        ]
        match = "missing parent"
    elif kind == "cross_workflow":
        records = [
            root,
            _span(
                "child",
                parents=[("root", "observed", 1.0, None)],
                workflow_id="other",
                top_level_index=1,
            ),
        ]
        match = "cross-workflow parent"
    else:
        records = [
            _span(
                "left",
                parents=[("right", "observed", 1.0, None)],
                top_level_index=0,
            ),
            _span(
                "right",
                parents=[("left", "observed", 1.0, None)],
                top_level_index=1,
            ),
        ]
        match = "cycle detected"
    with pytest.raises(CausalTraceValidationError, match=match):
        load_normalized_trace_records(records)


def test_streaming_loader_discards_content_and_hash_arrays(tmp_path: Path) -> None:
    path = tmp_path / "normalized.jsonl"
    record = _span("root")
    path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")

    trace = load_normalized_trace_jsonl(path)
    metadata = trace.spans[0]
    assert metadata.span_id == "root"
    assert not hasattr(metadata, "source_hash_ids")
    assert not hasattr(metadata, "messages_or_token_ids")


def test_same_records_produce_byte_identical_workload_journal() -> None:
    records = [
        _span("root", top_level_index=0),
        _span(
            "child",
            parents=[("root", "inferred", 0.75, "timeline")],
            tool_delay_ns=2,
            top_level_index=1,
        ),
    ]

    def run_once(input_records: list[dict[str, Any]]) -> bytes:
        _, des = _run_to_completion(input_records, {"root": 3, "child": 1})
        return des.journal.to_jsonl_bytes()

    assert run_once(records) == run_once(list(reversed(records)))


def test_unavailable_parent_blocks_descendants_without_release() -> None:
    trace = load_normalized_trace_records(
        [
            _span("root", top_level_index=0),
            _span(
                "child",
                parents=[("root", "inferred", 0.5, "timeline")],
                tool_delay_ns=10,
                top_level_index=1,
            ),
            _span(
                "grandchild",
                parents=[("child", "inferred", 0.5, "timeline")],
                top_level_index=2,
            ),
        ]
    )
    des = GlobalDES()
    engine = CausalReleaseEngine(trace, des)
    engine.start()
    des.run(until_ns=0)

    engine.mark_unavailable("root", reason="toy_parent_failed")
    des.run()

    assert engine.release_order == ("root",)
    assert engine.snapshot("root").status is SpanRuntimeStatus.UNAVAILABLE
    assert engine.snapshot("child").status is SpanRuntimeStatus.BLOCKED
    assert engine.snapshot("grandchild").status is SpanRuntimeStatus.BLOCKED
    assert engine.snapshot("child").released_ns is None
    assert engine.snapshot("grandchild").released_ns is None
    assert des.pending_count == 0
