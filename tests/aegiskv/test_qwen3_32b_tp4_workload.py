from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from moonkvsim.aegiskv.qwen3_32b_tp4_config import default_qwen3_32b_tp4_config_path
from moonkvsim.aegiskv.qwen3_32b_tp4_duration import (
    MODEL_ID,
    MODEL_REVISION,
    Qwen3TP4SchedulerStepDurationProvider,
    build_qwen3_32b_tp4_prediction_profile,
)
from moonkvsim.aegiskv.qwen3_32b_tp4_runner import (
    DEFAULT_MANIFEST_RELATIVE_PATH,
    DEFAULT_WORKLOAD_RELATIVE_PATH,
    Qwen3TP4RunnerBlocked,
    run_qwen3_32b_tp4_contract,
)
from moonkvsim.aegiskv.qwen3_32b_tp4_workload import (
    DEFAULT_EQUIVALENCE,
    DEFAULT_OUTPUT,
    DEFAULT_OUTPUT_MANIFEST,
    DEFAULT_SOURCE_MANIFEST,
    DEFAULT_SOURCE_WORKLOAD,
    MAX_CONTEXT_TOKENS,
    SOURCE_MODEL_ID,
    SOURCE_MODEL_REVISION,
    Qwen3TP4WorkloadError,
    derive_qwen3_32b_tp4_workload,
)
from moonkvsim.common.hash import sha256_json

ROOT = Path(__file__).resolve().parents[2]
PROVIDER_SOURCE_REVISION = "2bee56bd54a0f5e3070159f53b60a73273bccf44"
PROVIDER_SOURCE_REVISION_STATUS = (
    "repository_base_commit_plus_exact_dirty_worktree_provider_source_sha256"
)
PROVIDER_SOURCE_PATH = Path("python/moonkvsim/aegiskv/qwen3_32b_tp4_duration.py")


def _canonical_json_line(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _record(
    *,
    span_id: str,
    parent_span_ids: list[str],
    prompt_tokens: int,
    output_tokens: int,
) -> dict[str, Any]:
    token_ids = list(range(prompt_tokens))
    token_hash = sha256_json(token_ids)
    duration_ns = prompt_tokens * 100_000 + output_tokens * 5_000_000
    return {
        "schema": "moonkvsim.multi_agent_trace.v1",
        "workflow_id": "workflow-0",
        "span_id": span_id,
        "parent_span_ids": parent_span_ids,
        "observed_submit_ns": 0,
        "observed_finish_ns": duration_ns,
        "recorded_api_time_ns": duration_ns,
        "messages_or_token_ids": {
            "kind": "token_ids",
            "sha256": token_hash,
            "value": token_ids,
        },
        "prompt_token_ids_hash": token_hash,
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "total_model_tokens": prompt_tokens + output_tokens,
        "tool_delay_ns": 0,
        "model_id": SOURCE_MODEL_ID,
        "model_revision": SOURCE_MODEL_REVISION,
        "token_count_mode": "qwen3_token_ids",
        "tokenizer_fingerprint": "f" * 64,
        "truncated": False,
        "model_length_guard_passed": True,
    }


def _write_fixture(
    tmp_path: Path,
    *,
    records: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path, Path, Path]:
    source = tmp_path / "source.jsonl"
    source_manifest = tmp_path / "source-manifest.json"
    equivalence = tmp_path / "equivalence.json"
    provider_source = tmp_path / "provider.py"
    rows = records or [
        _record(span_id="root", parent_span_ids=[], prompt_tokens=8, output_tokens=2),
        _record(span_id="final", parent_span_ids=["root"], prompt_tokens=10, output_tokens=1),
    ]
    source_bytes = b"".join(_canonical_json_line(row) for row in rows)
    source.write_bytes(source_bytes)
    artifact = {
        "path": source.as_posix(),
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "record_count": len(rows),
        "semantic_fingerprint": sha256_json(rows),
    }
    manifest: dict[str, Any] = {
        "schema": "moonkvsim.aegiskv.experiment_workload_manifest.v1",
        "status": "pass",
        "source": {"dataset": "fixture"},
        "normalizer": {
            "model_id": SOURCE_MODEL_ID,
            "model_revision": SOURCE_MODEL_REVISION,
            "tokenizer_fingerprint": "f" * 64,
            "topology": "fixture_dag",
            "prompt_source": "fixture_token_ids",
        },
        "selection": {
            "selected_workflow_ids": ["workflow-0"],
            "no_span_slicing": True,
            "no_truncation": True,
            "no_padding": True,
            "no_synthesis": True,
        },
        "artifact": artifact,
    }
    manifest["fingerprint"] = sha256_json(manifest)
    source_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    equivalence.write_text(
        json.dumps(
            {
                "schema": "moonkvsim.aegiskv.tokenizer_equivalence.v1",
                "status": "PASS",
                "comparison": "byte_identical_files_at_pinned_model_revisions",
                "models": [
                    {"model_id": SOURCE_MODEL_ID, "revision": SOURCE_MODEL_REVISION},
                    {"model_id": MODEL_ID, "revision": MODEL_REVISION},
                ],
                "files": {
                    "merges.txt": "1" * 64,
                    "tokenizer.json": "2" * 64,
                    "tokenizer_config.json": "3" * 64,
                    "vocab.json": "4" * 64,
                },
                "evidence_boundary": (
                    "token_ids_are_portable_between_these_revisions_only;_service_times_are_not"
                ),
            }
        ),
        encoding="utf-8",
    )
    provider_source.write_text("# exact fixture provider source\n", encoding="utf-8")
    return source, source_manifest, equivalence, provider_source


def _derive_fixture(
    tmp_path: Path,
    *,
    records: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    source, source_manifest, equivalence, provider_source = _write_fixture(
        tmp_path, records=records
    )
    output = tmp_path / "derived.jsonl"
    output_manifest = tmp_path / "derived-manifest.json"
    manifest = derive_qwen3_32b_tp4_workload(
        source_workload_path=source,
        source_manifest_path=source_manifest,
        equivalence_path=equivalence,
        output_path=output,
        output_manifest_path=output_manifest,
        provider_source_revision="1" * 40,
        provider_source_revision_status="fixture_exact_source",
        provider_source_path=provider_source,
        enforce_formal_shape=False,
    )
    source_rows = [json.loads(line) for line in source.read_text().splitlines()]
    derived_rows = [json.loads(line) for line in output.read_text().splitlines()]
    return manifest, source_rows, derived_rows


def test_derivation_preserves_exact_tokens_hashes_dag_and_only_changes_allowed_fields(
    tmp_path: Path,
) -> None:
    manifest, source_rows, derived_rows = _derive_fixture(tmp_path)
    provider = Qwen3TP4SchedulerStepDurationProvider(
        prediction_profile=build_qwen3_32b_tp4_prediction_profile(provider_source_revision="1" * 40)
    )

    assert len(derived_rows) == len(source_rows) == 2
    for source, derived in zip(source_rows, derived_rows, strict=True):
        changed = {
            key for key in source.keys() | derived.keys() if source.get(key) != derived.get(key)
        }
        assert changed <= {
            "model_id",
            "model_revision",
            "observed_finish_ns",
            "recorded_api_time_ns",
        }
        assert derived["model_id"] == MODEL_ID
        assert derived["model_revision"] == MODEL_REVISION
        assert derived["messages_or_token_ids"] == source["messages_or_token_ids"]
        assert derived["prompt_token_ids_hash"] == source["prompt_token_ids_hash"]
        assert derived["workflow_id"] == source["workflow_id"]
        assert derived["span_id"] == source["span_id"]
        assert derived["parent_span_ids"] == source["parent_span_ids"]
        expected_duration = provider.predict_isolated_request_duration_ns(
            prompt_tokens=source["prompt_tokens"], output_tokens=source["output_tokens"]
        )
        assert derived["recorded_api_time_ns"] == expected_duration
        assert derived["observed_finish_ns"] == (derived["observed_submit_ns"] + expected_duration)

    derivation = manifest["derivation"]
    assert derivation["exact_prompt_token_ids_preserved"] is True
    assert derivation["workflow_dag_preserved"] is True
    assert derivation["no_truncation"] is True
    assert manifest["evidence"]["timing_and_bandwidth"] == "modeled_uncalibrated"
    assert manifest["evidence"]["physical_execution"] is False
    assert manifest["evidence"]["formal_use_allowed"] is False
    assert manifest["fingerprint"] == sha256_json(
        {key: value for key, value in manifest.items() if key != "fingerprint"}
    )


def test_context_audit_separates_native_and_proposed_yarn_without_shape_changes(
    tmp_path: Path,
) -> None:
    native = _record(span_id="root", parent_span_ids=[], prompt_tokens=10, output_tokens=1)
    yarn = _record(
        span_id="final",
        parent_span_ids=["root"],
        prompt_tokens=40_960,
        output_tokens=1,
    )
    manifest, source_rows, derived_rows = _derive_fixture(tmp_path, records=[native, yarn])
    audit = manifest["normalizer"]["context"]

    assert audit["native_max_context_tokens"] == 40_960
    assert audit["simulated_max_context_tokens"] == 131_072
    assert audit["native_context_record_count"] == 1
    assert audit["proposed_yarn_record_count"] == 1
    assert audit["native_context_workflow_count"] == 0
    assert audit["proposed_yarn_workflow_count"] == 1
    assert audit["runtime_context_extension_validated"] is False
    assert [row["total_model_tokens"] for row in derived_rows] == [
        row["total_model_tokens"] for row in source_rows
    ]
    assert all(row["truncated"] is False for row in derived_rows)


def test_derivation_rejects_context_beyond_proposed_yarn_limit(tmp_path: Path) -> None:
    oversized = _record(
        span_id="root",
        parent_span_ids=[],
        prompt_tokens=MAX_CONTEXT_TOKENS,
        output_tokens=1,
    )
    source, source_manifest, equivalence, provider_source = _write_fixture(
        tmp_path, records=[oversized]
    )

    with pytest.raises(Qwen3TP4WorkloadError, match="exceeds the proposed"):
        derive_qwen3_32b_tp4_workload(
            source_workload_path=source,
            source_manifest_path=source_manifest,
            equivalence_path=equivalence,
            output_path=tmp_path / "output.jsonl",
            output_manifest_path=tmp_path / "output-manifest.json",
            provider_source_revision="1" * 40,
            provider_source_revision_status="fixture_exact_source",
            provider_source_path=provider_source,
            enforce_formal_shape=False,
        )


def test_derivation_rejects_tokenizer_equivalence_and_source_artifact_drift(
    tmp_path: Path,
) -> None:
    source, source_manifest, equivalence, provider_source = _write_fixture(tmp_path)
    evidence = json.loads(equivalence.read_text())
    evidence["status"] = "FAIL"
    equivalence.write_text(json.dumps(evidence), encoding="utf-8")
    kwargs = {
        "source_workload_path": source,
        "source_manifest_path": source_manifest,
        "equivalence_path": equivalence,
        "output_path": tmp_path / "output.jsonl",
        "output_manifest_path": tmp_path / "output-manifest.json",
        "provider_source_revision": "1" * 40,
        "provider_source_revision_status": "fixture_exact_source",
        "provider_source_path": provider_source,
        "enforce_formal_shape": False,
    }
    with pytest.raises(Qwen3TP4WorkloadError, match="not passing"):
        derive_qwen3_32b_tp4_workload(**kwargs)

    _, _, clean_equivalence, _ = _write_fixture(tmp_path)
    kwargs["equivalence_path"] = clean_equivalence
    source.write_bytes(source.read_bytes() + b"\n")
    with pytest.raises(Qwen3TP4WorkloadError, match="SHA-256 differs"):
        derive_qwen3_32b_tp4_workload(**kwargs)


def test_checked_in_formal_workload_is_byte_reproducible(tmp_path: Path) -> None:
    output = tmp_path / DEFAULT_OUTPUT.name
    output_manifest = tmp_path / DEFAULT_OUTPUT_MANIFEST.name
    manifest = derive_qwen3_32b_tp4_workload(
        source_workload_path=DEFAULT_SOURCE_WORKLOAD,
        source_manifest_path=DEFAULT_SOURCE_MANIFEST,
        equivalence_path=DEFAULT_EQUIVALENCE,
        output_path=output,
        output_manifest_path=output_manifest,
        provider_source_revision=PROVIDER_SOURCE_REVISION,
        provider_source_revision_status=PROVIDER_SOURCE_REVISION_STATUS,
        provider_source_path=PROVIDER_SOURCE_PATH,
        artifact_declared_path=DEFAULT_OUTPUT.as_posix(),
    )

    assert output.read_bytes() == (ROOT / DEFAULT_OUTPUT).read_bytes()
    assert output_manifest.read_bytes() == (ROOT / DEFAULT_OUTPUT_MANIFEST).read_bytes()
    audit = manifest["normalizer"]["context"]
    assert manifest["artifact"]["record_count"] == 1_304
    assert len(manifest["selection"]["selected_workflow_ids"]) == 160
    assert audit["max_observed_context_tokens"] == 86_214
    assert audit["native_context_record_count"] == 1_099
    assert audit["proposed_yarn_record_count"] == 205
    assert audit["native_context_workflow_count"] == 74
    assert audit["proposed_yarn_workflow_count"] == 86


def test_qwen3_32b_runner_defaults_bind_derived_workload_before_schedule_gate() -> None:
    assert DEFAULT_WORKLOAD_RELATIVE_PATH == DEFAULT_OUTPUT
    assert DEFAULT_MANIFEST_RELATIVE_PATH == DEFAULT_OUTPUT_MANIFEST

    with pytest.raises(Qwen3TP4RunnerBlocked) as raised:
        run_qwen3_32b_tp4_contract(
            engine_config_path=default_qwen3_32b_tp4_config_path(ROOT),
            workload_path=ROOT / DEFAULT_WORKLOAD_RELATIVE_PATH,
            manifest_path=ROOT / DEFAULT_MANIFEST_RELATIVE_PATH,
            schedule_path=None,
        )

    codes = {row["code"] for row in raised.value.report["missing_gates"]}
    assert codes == {
        "QWEN3_32B_EXECUTION_SCHEDULE_MISSING",
        "QWEN3_32B_WORKFLOW_RELEASE_COMPLETION_TIMES_MISSING",
    }
