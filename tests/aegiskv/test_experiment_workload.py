from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from moonkvsim.aegiskv.experiment_workload import (
    CONTEXT_BUCKETS,
    WorkloadPreparationError,
    _audit_records,
    bucket_name_for,
    canonical_json_bytes,
    context_tokens,
)


def _record(*, span_id: str, prompt: int, output: int) -> dict[str, object]:
    if prompt % 64:
        raise ValueError("test prompt must be a whole source hash block")
    workflow = "002001296e8a8c38ad9d7cc436d691afc602"
    hashes = list(range((prompt + 63) // 64))
    return {
        "schema": "moonkvsim.multi_agent_trace.v1",
        "workflow_id": workflow,
        "session_id": workflow,
        "agent_id": "main",
        "agent_role": "main",
        "span_id": span_id,
        "parent_edges": [],
        "parent_span_ids": [],
        "parent_edge_origin": "none",
        "parent_edge_confidence": None,
        "observed_submit_ns": 0,
        "observed_finish_ns": 1,
        "recorded_api_time_ns": 1,
        "tool_delay_ns": 0,
        "dependency_release_rule": "observed_root_arrival",
        "prompt_tokens": prompt,
        "cached_prefix_tokens": 0,
        "output_tokens": output,
        "total_model_tokens": prompt + output,
        "model_id": "model",
        "model_revision": None,
        "evidence_class": "real_trace_shape_replay",
        "token_count_mode": "source_hash_blocks_64",
        "tokenizer_fingerprint": "not_available_source_hash_blocks_64",
        "source_block_size_tokens": 64,
        "source_hash_id_scope_raw": "local",
        "hash_id_scope": "within_workflow_only",
        "source_hash_ids": hashes,
        "source_hash_ids_sha256": hashlib.sha256(
            json.dumps(hashes, separators=(",", ":")).encode()
        ).hexdigest(),
        "source_position": {
            "workflow_line": 1,
            "top_level_index": 0,
            "inner_index": None,
        },
        "messages_or_token_ids": None,
        "prompt_token_ids_hash": None,
        "raw_request_type": "s",
        "retry_of_span_id": None,
        "subagent_group": None,
        "tool_name": None,
        "model_length_guard_passed": True,
        "synthetic": False,
        "truncated": False,
    }


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [(1, "8k"), (8192, "8k"), (8193, "32k"), (32768, "32k"),
     (32769, "64k"), (65537, "96k"), (98305, "128k"), (131072, "128k")],
)
def test_bucket_partition(tokens: int, expected: str) -> None:
    assert bucket_name_for(tokens) == expected


def test_context_tokens_rejects_inconsistent_total() -> None:
    record = _record(span_id="span", prompt=128, output=2)
    record["total_model_tokens"] = 129
    with pytest.raises(WorkloadPreparationError, match="must equal"):
        context_tokens(record)


def test_canonical_serialization_is_byte_stable() -> None:
    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}\n'


def test_audit_requires_all_five_buckets_and_both_frozen_workflows() -> None:
    records: list[dict[str, object]] = []
    token_counts = [100, 9_000, 40_000, 70_000, 100_000]
    for workflow_index, workflow in enumerate(
        (
            "002001296e8a8c38ad9d7cc436d691afc602",
            "0196085d85d2075a50b74cd8795ffbdcea9a",
        )
    ):
        for index, tokens in enumerate(token_counts):
            prompt = (tokens // 64) * 64
            record = _record(
                span_id=f"span-{workflow_index}-{index}",
                prompt=prompt,
                output=tokens - prompt,
            )
            record["workflow_id"] = workflow
            record["session_id"] = workflow
            record["source_position"] = {
                "workflow_line": workflow_index + 1,
                "top_level_index": index,
                "inner_index": None,
            }
            records.append(record)
    audit = _audit_records(records)
    assert audit["status"] == "pass"
    assert list(audit["context_bucket_counts"]) == [bucket.name for bucket in CONTEXT_BUCKETS]
    assert audit["context_bucket_counts"] == {
        "8k": 2,
        "32k": 2,
        "64k": 2,
        "96k": 2,
        "128k": 2,
    }


def test_audit_rejects_truncation() -> None:
    record = _record(span_id="span", prompt=128, output=1)
    record["truncated"] = True
    with pytest.raises(WorkloadPreparationError, match="forbidden"):
        _audit_records([record])


def test_committed_workload_and_manifest_match_if_present() -> None:
    root = Path(__file__).resolve().parents[2]
    workload = root / "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-shapes.jsonl"
    manifest_path = (
        root / "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-manifest.json"
    )
    if not workload.exists() or not manifest_path.exists():
        pytest.skip("generated frozen workload is not present")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(workload.read_bytes()).hexdigest() == manifest["artifact"]["sha256"]
    assert manifest["selection"]["audit"]["closed_causal_dag"] is True
    assert manifest["selection"]["audit"]["span_count"] == 117
