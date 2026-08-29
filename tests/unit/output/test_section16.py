from __future__ import annotations

import hashlib
import importlib
import importlib.util
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import moonkvsim.output.section16 as section16_module
from moonkvsim.output.artifacts import ParquetUnavailableError
from moonkvsim.output.records import (
    FlowRateEventRow,
    OutputContractError,
    ResourceLedgerDeltaRow,
)
from moonkvsim.output.section16 import (
    PARQUET_SCHEMAS,
    SECTION_16_ARTIFACTS,
    SECTION_16_PARQUET_ARTIFACTS,
    TraceExecutionProjection,
    build_section_16_projection,
    derive_request_metric_rows,
    derive_resource_snapshot_rows,
    derive_resource_utilization_rows,
    derive_workflow_metric_rows,
    parquet_schema_columns,
    project_event_rows,
)
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import CapacityResourceKind

HAS_PYARROW = importlib.util.find_spec("pyarrow") is not None


def _resource_rows() -> tuple[ResourceLedgerDeltaRow, ResourceLedgerDeltaRow]:
    reserve = ResourceLedgerDeltaRow(
        timestamp_ns=10,
        stable_sequence=4,
        delta_sequence=0,
        event_id="reserve",
        cause="TEST",
        resource_id="gpu-0.hbm",
        resource_kind=CapacityResourceKind.GPU_HBM,
        allocation_id="allocation-0",
        object_id="object-0",
        replica_id="replica-0",
        transfer_id=None,
        account_from="FREE",
        account_to="PENDING",
        requested_bytes=20,
        allocated_bytes=20,
        delta_bytes=20,
        before_bytes=0,
        after_bytes=20,
        from_before_bytes=100,
        from_after_bytes=80,
        to_before_bytes=0,
        to_after_bytes=20,
        capacity_bytes=100,
    )
    release = ResourceLedgerDeltaRow(
        timestamp_ns=10,
        stable_sequence=5,
        delta_sequence=0,
        event_id="release",
        cause="TEST",
        resource_id="gpu-0.hbm",
        resource_kind=CapacityResourceKind.GPU_HBM,
        allocation_id="allocation-0",
        object_id="object-0",
        replica_id="replica-0",
        transfer_id=None,
        account_from="PENDING",
        account_to="FREE",
        requested_bytes=20,
        allocated_bytes=20,
        delta_bytes=20,
        before_bytes=80,
        after_bytes=100,
        from_before_bytes=20,
        from_after_bytes=0,
        to_before_bytes=80,
        to_after_bytes=100,
        capacity_bytes=100,
    )
    return reserve, release


def _flow_row() -> FlowRateEventRow:
    return FlowRateEventRow(
        start_ns=0,
        end_ns=1_000_000_000,
        stable_sequence=0,
        flow_id="flow-0",
        transfer_id="transfer-0",
        slice_id="slice-0",
        cause="MOONCAKE_PUT",
        path_resource_ids=("gpu-read", "fabric", "store-write"),
        payload_bytes=100,
        remaining_bytes=100.0,
        remaining_bytes_at_end=0.0,
        transferred_bytes=100.0,
        allocated_rate_Bps=100.0,
        queue_wait_ns=0,
        service_ns=1_000_000_000,
    )


def _execution(*, completed_ns: int | None = 40) -> TraceExecutionProjection:
    return TraceExecutionProjection(
        workflow_id="workflow-0",
        session_id="session-0",
        agent_id="agent-0",
        agent_role="main",
        span_id="span-0",
        request_id="request-0",
        status="COMPLETED",
        prompt_tokens=1_000,
        cached_prefix_tokens=128,
        output_tokens=3,
        restored_tokens=128,
        scheduler_step_count=3,
        predicted_forward_ns=30,
        completed_ns=completed_ns,
        recomputed_tokens=None,
        source_hash_ids_sha256="a" * 64,
        truncated=False,
        padded=False,
    )


def _timed_journal() -> EventJournal:
    journal = EventJournal()
    journal.append(
        0,
        "TRACE_RUNNER_STARTED",
        {
            "recorded_api_time_ns": 999_999_999_999,
            "recorded_api_time_used_as_delay": False,
        },
    )
    journal.append(
        0,
        "TRACE_RUNNER_SPAN_ADMITTED",
        {"workflow_id": "workflow-0", "span_id": "span-0", "request_id": "request-0"},
    )
    for timestamp_ns, output_index in ((10, 0), (20, 1), (30, 2)):
        journal.append(
            timestamp_ns,
            "BASELINE_OUTPUT_ACTIVATED",
            {"request_id": "request-0", "output_index": output_index},
        )
    journal.append(
        40,
        "TRACE_RUNNER_SPAN_COMPLETED",
        {"workflow_id": "workflow-0", "span_id": "span-0", "request_id": "request-0"},
    )
    return journal


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir()) if path.is_file()}


def test_request_and_workflow_metrics_use_only_simulated_boundaries() -> None:
    request_rows = derive_request_metric_rows(_timed_journal(), (_execution(),))

    [request] = request_rows
    assert request["ttft_ns"] == 10
    assert request["tpot_ns"] == 10.0
    assert request["e2e_ns"] == 40
    assert request["timing_complete"] is True
    assert request["observed_api_time_used_as_simulated_time"] is False
    [workflow] = derive_workflow_metric_rows(request_rows)
    assert workflow["ttft_ns"] == 10
    assert workflow["tpot_ns"] == 10.0
    assert workflow["wct_ns"] == 40
    assert workflow["timing_complete"] is True


def test_missing_ttft_and_tpot_are_null_with_explicit_evidence_flags() -> None:
    journal = EventJournal()
    journal.append(
        0,
        "TRACE_RUNNER_STARTED",
        {"recorded_api_time_ns": 1, "recorded_api_time_used_as_delay": False},
    )
    journal.append(
        2,
        "TRACE_RUNNER_SPAN_ADMITTED",
        {"workflow_id": "workflow-0", "span_id": "span-0", "request_id": "request-0"},
    )
    journal.append(
        40,
        "TRACE_RUNNER_SPAN_COMPLETED",
        {"workflow_id": "workflow-0", "span_id": "span-0", "request_id": "request-0"},
    )
    request_rows = derive_request_metric_rows(
        journal,
        (_execution(completed_ns=40),),
    )

    [request] = request_rows
    assert request["ttft_ns"] is None
    assert request["tpot_ns"] is None
    assert request["ttft_complete"] is False
    assert request["tpot_complete"] is False
    assert request["e2e_ns"] == 38
    assert request["missing_evidence"] == [
        "tpot_complete_output_sequence",
        "ttft_simulated_boundaries",
    ]
    assert request["observed_api_time_used_as_simulated_time"] is False
    [workflow] = derive_workflow_metric_rows(request_rows)
    assert workflow["ttft_ns"] is None
    assert workflow["tpot_ns"] is None
    assert workflow["timing_complete"] is False


def test_event_classification_retains_canonical_record_identity_and_json() -> None:
    journal = EventJournal()
    records: tuple[tuple[str, dict[str, Any]], ...] = (
        ("BASELINE_FORWARD_BATCH_SCHEDULED", {"z": 2, "a": 1}),
        ("VLLM_HBM_BLOCKS_ACTIVATED", {"blocks": []}),
        ("TRANSFER_RUNTIME_TASK_STARTED", {"transfer_id": "transfer-0"}),
        ("ALLOCATION_ADDED", {"allocation": {"allocation_id": "allocation-0"}}),
        ("STORE_CLIENT_PUT_COMMITTED", {"put_id": "put-0"}),
        ("BASELINE_GPU_FAILURE_DETECTED", {"failure_id": "failure-0"}),
        ("VLLM_HBM_RESOURCES_FAILED", {"failure_id": "failure-0"}),
        ("TRACE_RUNNER_RECOVERY_STARTED", {"failure_id": "failure-0"}),
    )
    for sequence, (record_type, data) in enumerate(records):
        journal.append(sequence, record_type, data)
    journal.append(
        len(records),
        "EVENT_EXECUTING",
        {
            "event_id": "inject",
            "kind": "FAILURE_INJECT",
            "payload": {"failure_id": "failure-1"},
            "priority": 0,
            "stable_sequence": 9,
        },
    )

    tables = project_event_rows(journal)

    assert [row["record_type"] for row in tables["batch-events.parquet"]] == [
        "BASELINE_FORWARD_BATCH_SCHEDULED"
    ]
    assert tables["batch-events.parquet"][0]["data_json"] == '{"a":1,"z":2}'
    assert [row["stable_sequence"] for row in tables["kv-residency-events.parquet"]] == [1, 6]
    assert [row["stable_sequence"] for row in tables["kv-transfer-events.parquet"]] == [2]
    assert [row["stable_sequence"] for row in tables["physical-allocation-events.parquet"]] == [3]
    assert [row["stable_sequence"] for row in tables["store-directory-snapshots.parquet"]] == [4]
    assert [row["stable_sequence"] for row in tables["failure-events.parquet"]] == [
        5,
        6,
        8,
    ]
    assert [row["stable_sequence"] for row in tables["recovery-events.parquet"]] == [7]


def test_endpoint_registration_records_project_to_kv_transfer_events() -> None:
    journal = EventJournal()
    journal.append(
        10,
        "TRANSFER_ENDPOINT_READY",
        {"transfer_id": "transfer-0", "aggregated_into_gpu_forward": False},
    )
    journal.append(
        10,
        "EVENT_EXECUTING",
        {
            "event_id": "endpoint-registration:complete",
            "kind": "ENDPOINT_REGISTRATION_COMPLETE",
            "priority": 20,
            "stable_sequence": 1,
            "payload_sha256": "0" * 64,
        },
    )

    rows = project_event_rows(journal)["kv-transfer-events.parquet"]

    assert [row["record_type"] for row in rows] == [
        "TRANSFER_ENDPOINT_READY",
        "EVENT_EXECUTING",
    ]


def test_delta_replay_keeps_initial_and_same_timestamp_transient_boundaries() -> None:
    reserve, release = _resource_rows()

    snapshots = derive_resource_snapshot_rows((release, reserve))

    pending = [row for row in snapshots if row["account"] == "PENDING"]
    assert [row["boundary_index"] for row in pending] == [0, 1, 2]
    assert [row["account_bytes"] for row in pending] == [0, 20, 0]
    assert [row["timestamp_ns"] for row in pending] == [10, 10, 10]
    assert all(row["snapshot_complete"] is True for row in snapshots)
    utilization = derive_resource_utilization_rows(
        snapshots,
        (),
        run_end_ns=10,
    )
    pending_utilization = [
        row
        for row in utilization
        if row["metric_kind"] == "CAPACITY_ACCOUNT" and row["account"] == "PENDING"
    ]
    assert [row["utilization"] for row in pending_utilization] == [0.0, 0.2, 0.0]
    assert len(pending_utilization) == 3

    inconsistent_release = replace(
        release,
        requested_bytes=19,
        allocated_bytes=19,
        delta_bytes=19,
        before_bytes=80,
        after_bytes=99,
        from_before_bytes=19,
        from_after_bytes=0,
        to_before_bytes=80,
        to_after_bytes=99,
    )
    with pytest.raises(OutputContractError, match="before-state mismatch"):
        derive_resource_snapshot_rows((reserve, inconsistent_release))


def test_flow_path_is_exploded_once_per_hop_and_preserves_bytes() -> None:
    flow = _flow_row()

    rows = derive_resource_utilization_rows((), (flow,), run_end_ns=flow.end_ns)

    assert len(rows) == len(flow.path_resource_ids) == 3
    assert [row["resource_id"] for row in rows] == sorted(flow.path_resource_ids)
    assert {row["path_hop_count"] for row in rows} == {3}
    assert sum(row["transferred_bytes"] for row in rows) == pytest.approx(
        flow.transferred_bytes * len(flow.path_resource_ids)
    )
    assert all(row["capacity_rate_Bps"] is None for row in rows)
    assert all(row["utilization"] is None for row in rows)
    assert all(row["evidence_complete"] is False for row in rows)


def test_empty_projection_declares_all_fixed_schemas_without_pyarrow() -> None:
    projection = build_section_16_projection(journal=EventJournal())

    assert projection.artifact_names == SECTION_16_ARTIFACTS
    assert len(projection.artifact_names) == 19
    assert tuple(PARQUET_SCHEMAS) == SECTION_16_PARQUET_ARTIFACTS
    for name in SECTION_16_PARQUET_ARTIFACTS:
        assert projection.table_rows(name) == ()
        columns = parquet_schema_columns(name)
        assert columns
        assert len({column.name for column in columns}) == len(columns)
    assert projection.document("summary.json")["status"] == "EMPTY"
    assert projection.document("run-audit.json")["section_16"]["complete_file_set"] is True


def test_runner_documents_are_namespaced_and_preserve_required_audit_fields() -> None:
    source_provenance = {
        "schema": "moonkvsim.semantic-source-run-provenance.v1",
        "unchanged_during_run": True,
    }
    projection = build_section_16_projection(
        journal=EventJournal(),
        runner_documents={
            "trace-audit.json": {
                "source_path": "/tmp/normalized.jsonl",
                "source_sha256": "a" * 64,
                "selection": {"workflow_ids": ["workflow-0"]},
            },
            "run-audit.json": {
                "predictor": {
                    "calibration_status": "not_calibrated",
                    "formal_use_allowed": False,
                },
                "gaps": [{"code": "GAP-E2"}],
                "capacity_audit": {"valid": True},
                "semantic_source_provenance": source_provenance,
                "failure_protocol": {"mode": "fixed_virtual_time_gpu_fail_stop"},
                "transfer_resource_protocol": {"transport": "RDMA_GDR"},
            },
        },
    )

    trace_audit = projection.document("trace-audit.json")
    assert trace_audit["source_sha256"] == "a" * 64
    assert trace_audit["trace_runner"]["selection"]["workflow_ids"] == ["workflow-0"]
    run_audit = projection.document("run-audit.json")
    assert run_audit["predictor"]["calibration_status"] == "not_calibrated"
    assert run_audit["gaps"] == [{"code": "GAP-E2"}]
    assert run_audit["trace_runner_capacity_audit"] == {"valid": True}
    assert run_audit["semantic_source_provenance"] == source_provenance
    assert run_audit["failure_protocol"] == {"mode": "fixed_virtual_time_gpu_fail_stop"}
    assert run_audit["transfer_resource_protocol"] == {"transport": "RDMA_GDR"}


@pytest.mark.skipif(not HAS_PYARROW, reason="real Parquet byte gate requires trace extra")
def test_complete_matrix_is_byte_deterministic_empty_schema_stable_and_no_clobber(
    tmp_path: Path,
) -> None:
    parquet: Any = importlib.import_module("pyarrow.parquet")

    first_projection = build_section_16_projection(
        journal=_timed_journal(),
        resource_rows=_resource_rows(),
        flow_rows=(_flow_row(),),
        executions=(_execution(),),
    )
    second_projection = build_section_16_projection(
        journal=_timed_journal(),
        resource_rows=tuple(reversed(_resource_rows())),
        flow_rows=(_flow_row(),),
        executions=(_execution(),),
    )
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_projection.write(first)
    second_projection.write(second)

    first_bytes = _snapshot(first)
    assert first_bytes == _snapshot(second)
    assert set(first_bytes) == set(SECTION_16_ARTIFACTS)
    for name in SECTION_16_PARQUET_ARTIFACTS:
        assert first_bytes[name][:4] == b"PAR1"
        schema = parquet.read_schema(first / name)
        assert schema.names == [column.name for column in PARQUET_SCHEMAS[name]]
        assert schema.metadata is not None
        assert schema.metadata[b"moonkvsim.artifact"] == name.encode()

    empty = tmp_path / "empty"
    build_section_16_projection(journal=EventJournal()).write(empty)
    for name in SECTION_16_PARQUET_ARTIFACTS:
        table = parquet.read_table(empty / name)
        assert table.num_rows == 0
        assert table.schema.names == [column.name for column in PARQUET_SCHEMAS[name]]

    original_hashes = {
        name: hashlib.sha256(payload).hexdigest() for name, payload in first_bytes.items()
    }
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        first_projection.write(first)
    assert {
        name: hashlib.sha256(payload).hexdigest() for name, payload in _snapshot(first).items()
    } == original_hashes


def test_pyarrow_absence_fails_before_creating_any_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = build_section_16_projection(journal=EventJournal())

    def missing_pyarrow() -> Any:
        raise ParquetUnavailableError(
            "the complete section-16 matrix requires pyarrow; no artifact directory was created"
        )

    monkeypatch.setattr(section16_module, "_load_pyarrow", missing_pyarrow)
    output = tmp_path / "not-created"

    with pytest.raises(ParquetUnavailableError, match="no artifact directory was created"):
        projection.write(output)

    assert not output.exists()
    assert not list(tmp_path.glob(".not-created.section16-staging-*"))
