from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from moonkvsim.config import SchemaValidationError, validate_jsonl_trace
from traces.scripts._weka import WekaTraceError, audit_weka_trace, normalize_weka_trace

FIXTURE = Path(__file__).parent / "fixtures" / "weka-toy.jsonl"
REAL_SHAPE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "weka-real-shape-line1-minimal.jsonl"
)


def _raw_workflow(workflow_id: str, requests: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": workflow_id,
        "models": ["claude-toy"],
        "block_size": 64,
        "hash_id_scope": "local",
        "requests": requests,
    }


def _request(prompt_tokens: int, output_tokens: int, *, timestamp: float) -> dict[str, Any]:
    return {
        "t": timestamp,
        "model": "claude-toy",
        "in": prompt_tokens,
        "out": output_tokens,
        "hash_ids": list(range(prompt_tokens // 64)),
        "api_time": 0.1,
        "type": "n",
    }


def _write_raw(path: Path, workflows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(workflow, separators=(",", ":")) + "\n" for workflow in workflows),
        encoding="utf-8",
    )


def test_read_only_audit_uses_full_model_length_guard() -> None:
    before = (FIXTURE.stat().st_ino, FIXTURE.stat().st_size, FIXTURE.stat().st_mtime_ns)
    audit = audit_weka_trace(FIXTURE)
    after = (FIXTURE.stat().st_ino, FIXTURE.stat().st_size, FIXTURE.stat().st_mtime_ns)

    assert before == after
    assert audit["raw"]["workflow_count"] == 2
    assert audit["raw"]["request_count"] == 6
    assert audit["legacy_input_only_guard"]["pass_count"] == 6
    assert audit["strict_guard"]["pass_count"] == 5
    assert audit["strict_guard"]["overflow_count"] == 1
    assert audit["strict_guard"]["input_pass_but_output_reserve_fail_count"] == 1
    assert audit["strict_guard"]["truncated_count"] == 0
    assert audit["context_buckets"][0]["request_count"] == 5
    assert audit["evidence"]["source_hash_id_scope_raw_values"] == ["local"]
    assert audit["evidence"]["hash_id_scope_mapping"] == {
        "raw": "local",
        "normalized": "within_workflow_only",
        "semantics": "hash identities are comparable only within one workflow row",
    }


def test_boundary_guard_reserves_actual_output_tokens(tmp_path: Path) -> None:
    raw = tmp_path / "boundary.jsonl"
    workflows = [
        _raw_workflow(
            "wf-boundary",
            [
                _request(126976, 96, timestamp=0.0),
                _request(131072, 0, timestamp=1.0),
                _request(131072, 1, timestamp=2.0),
            ],
        )
    ]
    _write_raw(raw, workflows)

    audit = audit_weka_trace(raw)
    near = audit["near_128k"]
    assert near["legacy_input_only"]["request_count"] == 3
    assert near["strict_with_output_reserve"]["request_count"] == 2
    assert audit["strict_guard"]["input_pass_but_output_reserve_fail_count"] == 1


def test_normalization_is_byte_deterministic_and_schema_valid(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first_manifest = normalize_weka_trace(FIXTURE, first)
    second_manifest = normalize_weka_trace(FIXTURE, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_manifest["normalized"]["sha256"] == second_manifest["normalized"]["sha256"]
    assert first_manifest["normalized"]["record_count"] == 5
    assert validate_jsonl_trace(first) == {"record_count": 5, "workflow_count": 2}

    records = [json.loads(line) for line in first.read_text(encoding="utf-8").splitlines()]
    assert all(record["prompt_tokens"] + record["output_tokens"] <= 131072 for record in records)
    assert all(record["truncated"] is False for record in records)
    assert all(record["evidence_class"] == "real_trace_shape_replay" for record in records)
    assert all(record["source_hash_id_scope_raw"] == "local" for record in records)
    assert all(record["hash_id_scope"] == "within_workflow_only" for record in records)
    subagent_first = next(
        record
        for record in records
        if record["span_id"].endswith("000001:000000")
    )
    assert subagent_first["parent_edge_origin"] == "inferred"
    assert subagent_first["cached_prefix_tokens"] == 128


def test_expected_raw_hash_is_checked(tmp_path: Path) -> None:
    expected = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert audit_weka_trace(FIXTURE, expected_raw_sha256=expected)["raw_sha256"] == expected
    with pytest.raises(WekaTraceError, match="SHA256 mismatch"):
        audit_weka_trace(FIXTURE, expected_raw_sha256="0" * 64)


def test_raw_contract_rejects_unknown_fields(tmp_path: Path) -> None:
    raw = tmp_path / "unknown.jsonl"
    workflow = _raw_workflow("wf-unknown", [_request(64, 1, timestamp=0.0)])
    workflow["requests"][0]["silently_ignored"] = True
    _write_raw(raw, [workflow])
    with pytest.raises(WekaTraceError, match="unknown fields"):
        audit_weka_trace(raw)


def test_locked_raw_scope_fails_closed_instead_of_accepting_old_alias(tmp_path: Path) -> None:
    raw = tmp_path / "wrong-scope.jsonl"
    workflow = _raw_workflow("wf-wrong-scope", [_request(64, 1, timestamp=0.0)])
    workflow["hash_id_scope"] = "trace"
    _write_raw(raw, [workflow])
    with pytest.raises(WekaTraceError, match="expected locked raw value 'local'"):
        audit_weka_trace(raw)


def test_minimal_fixture_preserves_locked_real_line_shape(tmp_path: Path) -> None:
    audit = audit_weka_trace(REAL_SHAPE_FIXTURE)
    assert audit["raw"]["workflow_count"] == 1
    assert audit["raw"]["request_count"] == 1
    assert audit["evidence"]["source_hash_id_scope_raw_values"] == ["local"]

    normalized = tmp_path / "real-shape.jsonl"
    normalize_weka_trace(REAL_SHAPE_FIXTURE, normalized)
    record = json.loads(normalized.read_text(encoding="utf-8"))
    assert record["workflow_id"] == "002001296e8a8c38ad9d7cc436d691afc602"
    assert record["raw_request_type"] == "s"
    assert record["prompt_tokens"] == 640
    assert record["source_hash_id_scope_raw"] == "local"
    assert record["hash_id_scope"] == "within_workflow_only"


def test_normalizer_never_overwrites_raw_input() -> None:
    with pytest.raises(WekaTraceError, match="input and output paths must differ"):
        normalize_weka_trace(FIXTURE, FIXTURE, overwrite=True)


def test_cross_record_validator_rejects_missing_parent(tmp_path: Path) -> None:
    normalized = tmp_path / "normalized.jsonl"
    normalize_weka_trace(FIXTURE, normalized)
    records = normalized.read_text(encoding="utf-8").splitlines()
    record = json.loads(records[0])
    record["parent_span_ids"] = ["missing"]
    record["parent_edges"] = [
        {
            "parent_span_id": "missing",
            "origin": "inferred",
            "confidence": 0.5,
            "inference_rule": "toy",
        }
    ]
    record["parent_edge_origin"] = "inferred"
    record["parent_edge_confidence"] = 0.5
    record["dependency_release_rule"] = "parent_completion_plus_recorded_delay"
    records[0] = json.dumps(record, separators=(",", ":"), sort_keys=True)
    normalized.write_text("\n".join(records) + "\n", encoding="utf-8")
    with pytest.raises(SchemaValidationError, match="missing parent"):
        validate_jsonl_trace(normalized)


def test_checked_in_manifest_distinguishes_legacy_and_strict_near_128k_counts() -> None:
    manifest_path = Path(__file__).resolve().parents[3] / "traces" / "TRACE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot = manifest["preaudit_snapshot"]
    assert snapshot["legacy_plan_input_only_guard"]["near_128k_request_count"] == 1164
    assert snapshot["strict_model_length_guard"]["near_128k_request_count"] == 936
    assert snapshot["strict_model_length_guard"]["expression"] == "in + out <= 131072"
    assert manifest["normalizer"]["source_hash_id_scope_raw"] == "local"
    assert manifest["normalizer"]["hash_id_scope_mapping"]["normalized"] == (
        "within_workflow_only"
    )
    normalized = manifest["artifacts"]["normalized_trace"]
    assert normalized["status"] == "generated_external_not_committed"
    assert normalized["path"] is None
    assert normalized["sha256"] == (
        "0a1c37deea32f2c393ba7d8d2d9a7c5629854b874b01ace8953140ad889f6d54"
    )
    assert normalized["record_count"] == 46142
    assert manifest["raw"]["repository_revision"] == (
        "23f152f6f0f9399a85901b89a6458def0ef16729"
    )
    collection_interval = manifest["raw"]["collection_interval"]
    assert collection_interval["status"] == (
        "not_disclosed_by_reviewed_public_sources"
    )
    assert collection_interval["value"] is None
    assert len(collection_interval["sources"]) == 2
    assert "build date" in collection_interval["evidence_boundary"]
    assert manifest["formal_gate"]["status"] == "incomplete"


def test_full_read_only_audit_freezes_strict_near_128k_ids() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "traces" / "TRACE_MANIFEST.json").read_text())
    artifact = manifest["artifacts"]["strict_near_128k_sample_ids"]
    report_path = root / artifact["path"]
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    sample_ids = report["near_128k"]["strict_with_output_reserve"]["sample_ids"]

    assert artifact["status"] == "generated_and_frozen"
    assert len(sample_ids) == artifact["count"] == 936
    assert len(set(sample_ids)) == 936
    assert sample_ids == sorted(sample_ids)
    assert hashlib.sha256(report_bytes).hexdigest() == artifact["report_sha256"]
    assert report["raw_sha256"] == manifest["raw"]["sha256"]
    assert report["strict_guard"]["truncated_count"] == 0
    assert report["strict_guard"]["synthetic"] is False


def test_full_normalization_determinism_audit_is_hash_locked() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "traces" / "TRACE_MANIFEST.json").read_text())
    normalized = manifest["artifacts"]["normalized_trace"]
    audit_path = root / normalized["determinism_audit_path"]
    audit_bytes = audit_path.read_bytes()
    audit = json.loads(audit_bytes)

    assert hashlib.sha256(audit_bytes).hexdigest() == normalized[
        "determinism_audit_sha256"
    ]
    assert audit["comparison"]["normalized_byte_identical"] is True
    assert audit["comparison"]["semantic_manifests_identical"] is True
    assert audit["schema_and_dag_validation"] == {
        "command": "moonkv-sim validate NORMALIZED.jsonl --jsonl-trace",
        "status": "pass",
        "record_count": 46142,
        "workflow_count": 392,
    }
    assert audit["causal_loader_validation"]["status"] == "pass"
    assert audit["causal_loader_validation"]["edge_count"] == 46907
    assert audit["evidence_boundary"].startswith("Real source-block trace shape")
