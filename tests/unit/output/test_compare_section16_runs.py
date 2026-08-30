from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from moonkvsim.common.hash import canonical_json_bytes
from moonkvsim.output.section16 import (
    SECTION_16_ARTIFACTS,
    TraceExecutionProjection,
    build_section_16_projection,
)
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts/compare_section16_runs.py"
    spec = importlib.util.spec_from_file_location("compare_section16_runs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT = _load_script()


def _frozen_snapshot(seed: str = "a") -> dict[str, Any]:
    files = [
        {
            "path": "pyproject.toml",
            "scope": "repository",
            "roles": ["dependency-contract"],
            "size_bytes": 123,
            "sha256": seed * 64,
        },
        {
            "path": "python/moonkvsim/runtime.py",
            "scope": "repository",
            "roles": ["python/moonkvsim-source"],
            "size_bytes": 456,
            "sha256": seed * 64,
        },
    ]
    canonical = {
        "schema": "moonkvsim.semantic-source-snapshot.v1",
        "repository_root": "/repo/MoonKVSim",
        "git": {
            "branch": "main",
            "head_state": "resolved",
            "head_commit": seed * 40,
            "head_tree": seed * 40,
            "porcelain_sha256": hashlib.sha256(b"").hexdigest(),
            "porcelain_entry_count": 0,
            "worktree_clean": True,
        },
        "semantic_sources": {
            "selection_policy": {
                "python": "all Python sources",
                "cli": "selected CLI",
                "schemas": "all schemas",
                "config": "selected config",
                "layout": "selected layout",
                "dependencies": "locked dependencies",
                "bytecode_and_caches_included": False,
            },
            "files": files,
            "file_count": len(files),
            "repository_file_count": len(files),
            "tracked_repository_file_count": len(files),
            "aggregate_sha256": hashlib.sha256(canonical_json_bytes(files)).hexdigest(),
        },
        "source_frozen": True,
        "source_freeze_blockers": [],
        "source_frozen_reason": "clean_head_and_all_semantic_sources_git_tracked",
    }
    return {
        **canonical,
        "fingerprint": hashlib.sha256(canonical_json_bytes(canonical)).hexdigest(),
    }


def _source_provenance(seed: str = "a") -> dict[str, Any]:
    snapshot = _frozen_snapshot(seed)
    return {
        "schema": "moonkvsim.semantic-source-run-provenance.v1",
        "unchanged_during_run": True,
        "formal_use_allowed": False,
        "evidence_boundary": "E2 deterministic simulation; nonformal",
        "start_snapshot": snapshot,
        "end_snapshot_fingerprint": snapshot["fingerprint"],
        "comparison": "byte_identical_canonical_snapshot",
    }


def _write_run(path: Path, *, seed: str = "a", status: str = "PASS") -> str:
    journal = EventJournal()
    journal.append(
        10,
        "TRACE_RUNNER_SPAN_ADMITTED",
        {"request_id": "request-0", "span_id": "span-0"},
    )
    journal.append(
        20,
        "BASELINE_OUTPUT_ACTIVATED",
        {"output_index": 0, "request_id": "request-0"},
    )
    journal.append(30, "TRACE_RUNNER_SPAN_COMPLETED", {"request_id": "request-0"})
    execution = TraceExecutionProjection(
        workflow_id="workflow-0",
        session_id="session-0",
        agent_id="agent-0",
        agent_role="assistant",
        span_id="span-0",
        request_id="request-0",
        status="COMPLETED",
        prompt_tokens=8,
        cached_prefix_tokens=0,
        output_tokens=1,
        restored_tokens=0,
        scheduler_step_count=1,
        predicted_forward_ns=10,
        target_replica_id="replica-0",
        route_version=1,
        completed_ns=30,
        recomputed_tokens=8,
        source_hash_ids_sha256="c" * 64,
        truncated=False,
        padded=False,
    )
    provenance = _source_provenance(seed)
    projection = build_section_16_projection(
        journal=journal,
        executions=(execution,),
        initial_ledgers={
            "gpu-0.hbm": CapacityLedger(
                resource_id="gpu-0.hbm",
                resource_kind=CapacityResourceKind.GPU_HBM,
                capacity_bytes=1024,
            )
        },
        runner_documents={
            "trace-audit.json": {"status": status},
            "run-audit.json": {
                "status": status,
                "ledger_replay_byte_identical": True,
                "allocation_registry_replay_byte_identical": True,
                "transfer_resource_calendar_replay_byte_identical": True,
                "flow_rate_state_replay_byte_identical": True,
                "journal_replay_byte_identical": True,
                "semantic_source_provenance": provenance,
            },
            "summary.json": {"status": status},
        },
    )
    projection.write(path)
    return str(provenance["start_snapshot"]["fingerprint"])


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _refresh_snapshot_fingerprint(run: Path) -> None:
    path = run / "run-audit.json"
    audit = _read_json(path)
    provenance = audit["semantic_source_provenance"]
    snapshot = provenance["start_snapshot"]
    canonical = dict(snapshot)
    del canonical["fingerprint"]
    fingerprint = hashlib.sha256(canonical_json_bytes(canonical)).hexdigest()
    snapshot["fingerprint"] = fingerprint
    provenance["end_snapshot_fingerprint"] = fingerprint
    _write_json(path, audit)


def _rewrite_empty_parquet(path: Path, defect: str) -> None:
    table = pq.read_table(path)
    assert table.num_rows == 0
    fields = list(table.schema)
    metadata = dict(table.schema.metadata or {})
    arrays = [table.column(index) for index in range(table.num_columns)]
    first = fields[0]
    if defect == "field_name":
        fields[0] = pa.field("wrong_name", first.type, nullable=first.nullable)
    elif defect == "field_type":
        fields[0] = pa.field(first.name, pa.string(), nullable=first.nullable)
        arrays[0] = pa.chunked_array([], type=pa.string())
    elif defect == "nullability":
        fields[0] = pa.field(first.name, first.type, nullable=not first.nullable)
    elif defect == "metadata":
        metadata.pop(b"moonkvsim.truth_source")
    else:
        raise AssertionError(defect)
    schema = pa.schema(fields, metadata=metadata)
    pq.write_table(
        pa.Table.from_arrays(arrays, schema=schema),
        path,
        compression="NONE",
        use_dictionary=False,
        write_statistics=False,
    )


def _rewrite_first_parquet_value(path: Path, column: str, value: object) -> None:
    table = pq.read_table(path)
    assert table.num_rows > 0
    index = table.schema.get_field_index(column)
    assert index >= 0
    values = table.column(index).to_pylist()
    values[0] = value
    replacement = pa.chunked_array([pa.array(values, type=table.schema.field(index).type)])
    changed = table.set_column(index, table.schema.field(index), replacement)
    pq.write_table(
        changed,
        path,
        compression="NONE",
        use_dictionary=False,
        write_statistics=False,
    )


def test_compare_accepts_genuine_distinct_frozen_byte_identical_pass_runs(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    fingerprint = _write_run(first)
    _write_run(second)

    report = SCRIPT.compare_runs(first, second)

    assert report["status"] == "PASS"
    assert report["artifact_count"] == 19
    assert report["semantic_source_fingerprint"] == fingerprint
    assert report["independent_execution_proven"] is False
    assert "copied" in report["limitation"]
    assert "independent" not in report["acceptance"]
    for name in SECTION_16_ARTIFACTS:
        assert (first / name).is_file()
    assert pq.read_metadata(first / "request-metrics.parquet").num_rows == 1


def test_compare_rejects_same_resolved_directory(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_run(run)

    with pytest.raises(SCRIPT.ComparisonError, match="same directory"):
        SCRIPT.compare_runs(run, run / ".." / "run")


@pytest.mark.parametrize("defect", ["missing", "extra", "mismatch", "blocked", "source"])
def test_compare_rejects_incomplete_or_nonmatching_runs(tmp_path: Path, defect: str) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_run(first)
    _write_run(
        second,
        seed="b" if defect == "source" else "a",
        status="BLOCKED" if defect == "blocked" else "PASS",
    )
    if defect == "missing":
        (second / SECTION_16_ARTIFACTS[0]).unlink()
    elif defect == "extra":
        (second / "extra").write_bytes(b"not allowed")
    elif defect == "mismatch":
        summary = _read_json(second / "summary.json")
        summary["copy_note"] = "byte drift"
        _write_json(second / "summary.json", summary)

    with pytest.raises(SCRIPT.ComparisonError):
        SCRIPT.compare_runs(first, second)


def test_compare_rejects_symlink_artifact(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_run(first)
    _write_run(second)
    target = tmp_path / "outside"
    target.write_bytes(b"outside")
    artifact = second / SECTION_16_ARTIFACTS[0]
    artifact.unlink()
    artifact.symlink_to(target)

    with pytest.raises(SCRIPT.ComparisonError, match="non-symlink"):
        SCRIPT.compare_runs(first, second)


def test_compare_rejects_internally_contradictory_snapshot_even_with_refreshed_fingerprint(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_run(first)
    _write_run(second)
    audit = _read_json(second / "run-audit.json")
    sources = audit["semantic_source_provenance"]["start_snapshot"]["semantic_sources"]
    sources["repository_file_count"] += 1
    _write_json(second / "run-audit.json", audit)
    _refresh_snapshot_fingerprint(second)

    with pytest.raises(SCRIPT.ComparisonError, match="repository_file_count"):
        SCRIPT.compare_runs(first, second)


def test_compare_rejects_forged_semantic_fingerprint(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_run(first)
    _write_run(second)
    audit = _read_json(second / "run-audit.json")
    provenance = audit["semantic_source_provenance"]
    provenance["start_snapshot"]["fingerprint"] = "f" * 64
    provenance["end_snapshot_fingerprint"] = "f" * 64
    _write_json(second / "run-audit.json", audit)

    with pytest.raises(SCRIPT.ComparisonError, match="fingerprint is inconsistent"):
        SCRIPT.compare_runs(first, second)


def test_compare_rejects_plain_text_disguised_as_parquet(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_run(first)
    _write_run(second)
    (second / "batch-events.parquet").write_bytes(b"not parquet")

    with pytest.raises(SCRIPT.ComparisonError, match="genuine Parquet"):
        SCRIPT.compare_runs(first, second)


@pytest.mark.parametrize("defect", ["field_name", "field_type", "nullability", "metadata"])
def test_compare_rejects_parquet_schema_or_metadata_drift(
    tmp_path: Path,
    defect: str,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_run(first)
    _write_run(second)
    _rewrite_empty_parquet(second / "batch-events.parquet", defect)

    with pytest.raises(SCRIPT.ComparisonError):
        SCRIPT.compare_runs(first, second)


def test_compare_rejects_declared_parquet_row_count_drift(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_run(first)
    _write_run(second)
    summary = _read_json(second / "summary.json")
    summary["parquet_row_counts"]["batch-events.parquet"] += 1
    _write_json(second / "summary.json", summary)

    with pytest.raises(SCRIPT.ComparisonError, match="row counts differ"):
        SCRIPT.compare_runs(first, second)


@pytest.mark.parametrize(
    ("snapshot_state_complete", "incomplete_resource_ids", "message"),
    [
        (False, [], "snapshot state is incomplete"),
        (True, ["gpu-0.hbm"], "declares incomplete resource IDs"),
    ],
)
def test_inspect_rejects_incomplete_capacity_snapshot(
    tmp_path: Path,
    snapshot_state_complete: bool,
    incomplete_resource_ids: list[str],
    message: str,
) -> None:
    run = tmp_path / "run"
    _write_run(run)
    capacity = _read_json(run / "capacity-audit.json")
    capacity["snapshot_state_complete"] = snapshot_state_complete
    capacity["incomplete_resource_ids"] = incomplete_resource_ids
    _write_json(run / "capacity-audit.json", capacity)

    with pytest.raises(SCRIPT.ComparisonError, match=message):
        SCRIPT.inspect_run(run)


def test_inspect_rejects_incomplete_workflow_timing(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_run(run)
    run_audit = _read_json(run / "run-audit.json")
    run_audit["timing_metrics"]["workflow_complete_count"] = 0
    _write_json(run / "run-audit.json", run_audit)
    summary = _read_json(run / "summary.json")
    summary["workflow_timing_complete_count"] = 0
    _write_json(run / "summary.json", summary)

    with pytest.raises(SCRIPT.ComparisonError, match="workflow timing is incomplete"):
        SCRIPT.inspect_run(run)


@pytest.mark.parametrize(
    ("artifact", "column", "value", "message"),
    [
        (
            "resource-ledger-snapshots.parquet",
            "snapshot_complete",
            False,
            "incomplete capacity snapshot",
        ),
        (
            "resource-ledger-snapshots.parquet",
            "unknown_account_bytes",
            1,
            "incomplete capacity snapshot",
        ),
        (
            "request-metrics.parquet",
            "timing_complete",
            False,
            "incomplete request timing",
        ),
        (
            "workflow-metrics.parquet",
            "timing_complete",
            False,
            "incomplete workflow timing",
        ),
    ],
)
def test_inspect_rejects_incomplete_parquet_rows_even_when_json_claims_pass(
    tmp_path: Path,
    artifact: str,
    column: str,
    value: object,
    message: str,
) -> None:
    run = tmp_path / "run"
    _write_run(run)
    _rewrite_first_parquet_value(run / artifact, column, value)

    with pytest.raises(SCRIPT.ComparisonError, match=message):
        SCRIPT.inspect_run(run)


def test_inspect_cross_checks_capacity_resource_count_with_snapshot_rows(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    _write_run(run)
    capacity = _read_json(run / "capacity-audit.json")
    capacity["resource_count"] += 1
    _write_json(run / "capacity-audit.json", capacity)
    run_audit = _read_json(run / "run-audit.json")
    run_audit["capacity"]["resource_count"] += 1
    _write_json(run / "run-audit.json", run_audit)

    with pytest.raises(SCRIPT.ComparisonError, match="resource count differs"):
        SCRIPT.inspect_run(run)


def test_inspect_rejects_incomplete_request_timing_json_claim(tmp_path: Path) -> None:
    run = tmp_path / "run"
    _write_run(run)
    run_audit = _read_json(run / "run-audit.json")
    run_audit["timing_metrics"]["request_complete_count"] = 0
    _write_json(run / "run-audit.json", run_audit)
    summary = _read_json(run / "summary.json")
    summary["request_timing_complete_count"] = 0
    _write_json(run / "summary.json", summary)

    with pytest.raises(SCRIPT.ComparisonError, match="request timing is incomplete"):
        SCRIPT.inspect_run(run)


def test_compare_rejects_noncanonical_or_unparseable_journal(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_run(first)
    _write_run(second)
    (second / "event-journal.jsonl").write_bytes(b"plain text\n")

    with pytest.raises(SCRIPT.ComparisonError, match="cannot parse"):
        SCRIPT.compare_runs(first, second)


def test_compare_rejects_json_schema_and_artifact_identity_drift(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_run(first)
    _write_run(second)
    trace_audit = _read_json(second / "trace-audit.json")
    trace_audit["artifact"] = "summary.json"
    _write_json(second / "trace-audit.json", trace_audit)

    with pytest.raises(SCRIPT.ComparisonError, match="artifact identity"):
        SCRIPT.compare_runs(first, second)
