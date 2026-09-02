from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from moonkvsim.aegiskv.ideal_trace_cpm import (
    compute_ideal_trace_cpm,
    compute_residual_ideal_trace_cpm,
)
from moonkvsim.workload.causal_trace import load_normalized_trace_records


def _span(
    span_id: str,
    duration_ns: int,
    *,
    parents: Iterable[str] = (),
    tool_delay_ns: int = 0,
    order: int = 0,
) -> dict[str, Any]:
    parent_ids = list(parents)
    return {
        "schema": "moonkvsim.multi_agent_trace.v1",
        "workflow_id": "wf",
        "session_id": "wf",
        "agent_id": f"agent:{span_id}",
        "agent_role": "main",
        "span_id": span_id,
        "parent_span_ids": parent_ids,
        "parent_edges": [
            {
                "parent_span_id": parent_id,
                "origin": "observed",
                "confidence": 1.0,
                "inference_rule": None,
            }
            for parent_id in parent_ids
        ],
        "parent_edge_origin": "observed" if parent_ids else "none",
        "parent_edge_confidence": 1.0 if parent_ids else None,
        "observed_submit_ns": 0,
        "observed_finish_ns": duration_ns,
        "recorded_api_time_ns": duration_ns,
        "messages_or_token_ids": None,
        "prompt_token_ids_hash": None,
        "source_hash_ids": [order],
        "source_hash_ids_sha256": "0" * 64,
        "prompt_tokens": 64,
        "cached_prefix_tokens": 0,
        "output_tokens": 1,
        "total_model_tokens": 65,
        "tool_name": None,
        "tool_delay_ns": tool_delay_ns,
        "dependency_release_rule": (
            "parent_completion_plus_recorded_delay"
            if parent_ids
            else "observed_root_arrival"
        ),
        "retry_of_span_id": None,
        "model_id": "ideal-trace-test",
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
            "top_level_index": order,
            "inner_index": None,
        },
        "raw_request_type": "n",
        "subagent_group": None,
    }


def test_exact_cpm_uses_known_durations_and_marks_short_branch_slack() -> None:
    trace = load_normalized_trace_records(
        [
            _span("root", 10, order=0),
            _span("long", 20, parents=("root",), order=1),
            _span("short", 5, parents=("root",), order=2),
            _span("join", 3, parents=("long", "short"), tool_delay_ns=2, order=3),
        ]
    )

    result = compute_ideal_trace_cpm(trace.spans)

    assert result.workflow_makespan_ns == {"wf": 35}
    assert result.timing("root").slack_ns == 0
    assert result.timing("long").slack_ns == 0
    assert result.timing("short").slack_ns == 15
    assert result.timing("join").slack_ns == 0
    assert result.provenance()["duration_source"] == "trace.recorded_api_time_ns"
    assert result.provenance()["absolute_observed_finish_used"] is False


def test_absolute_observed_finish_does_not_affect_cpm() -> None:
    records = [_span("root", 10), _span("child", 4, parents=("root",), order=1)]
    records[0]["observed_submit_ns"] = 999_989
    records[0]["observed_finish_ns"] = 999_999
    records[1]["observed_submit_ns"] = 1
    records[1]["observed_finish_ns"] = 5
    trace = load_normalized_trace_records(records)

    result = compute_ideal_trace_cpm(trace.spans)

    assert result.workflow_makespan_ns == {"wf": 14}
    assert all(item.slack_ns == 0 for item in result.timings.values())


def test_residual_cpm_matches_full_dag_when_nothing_has_finished() -> None:
    trace = load_normalized_trace_records(
        [
            _span("root", 10, order=0),
            _span("long", 20, parents=("root",), order=1),
            _span("short", 5, parents=("root",), order=2),
            _span("join", 3, parents=("long", "short"), tool_delay_ns=2, order=3),
        ]
    )
    remaining = {
        span.span_id: span.recorded_api_time_ns for span in trace.spans
    }

    residual = compute_residual_ideal_trace_cpm(trace.spans, remaining)

    assert residual.timing("root").slack_ns == 0
    assert residual.timing("long").slack_ns == 0
    assert residual.timing("short").slack_ns == 15
    assert residual.timing("join").slack_ns == 0
    assert residual.provenance()["algorithm"] == "residual_ideal_trace_exact_dag_cpm_v1"


def test_residual_cpm_drops_slack_after_sibling_returns() -> None:
    trace = load_normalized_trace_records(
        [
            _span("root", 10, order=0),
            _span("long", 20, parents=("root",), order=1),
            _span("short", 5, parents=("root",), order=2),
            _span("join", 3, parents=("long", "short"), tool_delay_ns=2, order=3),
        ]
    )

    residual = compute_residual_ideal_trace_cpm(
        trace.spans,
        {"long": 20, "join": 3},
    )

    assert residual.timing("long").slack_ns == 0
    assert residual.timing("join").slack_ns == 0
    assert "short" not in residual.timings
    assert residual.workflow_makespan_ns == {"wf": 25}


def test_residual_cpm_uses_remaining_active_weight() -> None:
    trace = load_normalized_trace_records(
        [
            _span("long", 20, order=0),
            _span("short", 5, order=1),
        ]
    )

    residual = compute_residual_ideal_trace_cpm(
        trace.spans,
        {"long": 2, "short": 5},
    )

    assert residual.timing("long").slack_ns == 3
    assert residual.timing("short").slack_ns == 0
    assert residual.timing("long").critical is False
    assert residual.timing("short").critical is True
