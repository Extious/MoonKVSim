"""Deterministic projection of canonical E2 state into the section-16 matrix.

This module is deliberately independent of the baseline runner and harness.  It
accepts only four already-canonical sources:

* the append-only :class:`~moonkvsim.simulation.journal.EventJournal`;
* byte-ledger delta rows;
* fluid-flow interval rows; and
* an explicit, output-only description of each trace execution.

Every other row is a projection.  Missing timing evidence remains null and is
accompanied by applicability/completeness/evidence fields; observed API wall
time is neither accepted nor used as simulated time.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import importlib
import json
import math
import os
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, Final, cast

from moonkvsim.output.artifacts import (
    ParquetUnavailableError,
    event_journal_jsonl_bytes,
)
from moonkvsim.output.records import (
    FlowRateEventRow,
    OutputContractError,
    ResourceLedgerDeltaRow,
    canonical_flow_rate_event_rows,
    canonical_resource_ledger_delta_rows,
    validate_flow_rate_sequence,
)
from moonkvsim.simulation.journal import EventJournal, JournalRecord
from moonkvsim.simulation.ledger import CapacityLedger

SECTION_16_SCHEMA_VERSION: Final = "moonkvsim.output.section-16-e2-projection.v1"
MAX_MODEL_LEN_TOKENS: Final = 131_072
CONTEXT_BUCKET_UPPER_BOUNDS: Final[tuple[int, ...]] = (
    8_192,
    32_768,
    65_536,
    98_304,
    131_072,
)

SECTION_16_ARTIFACTS: Final[tuple[str, ...]] = (
    "event-journal.jsonl",
    "trace-audit.json",
    "context-coverage.json",
    "workflow-metrics.parquet",
    "request-metrics.parquet",
    "batch-events.parquet",
    "kv-residency-events.parquet",
    "kv-transfer-events.parquet",
    "physical-allocation-events.parquet",
    "resource-ledger-deltas.parquet",
    "resource-ledger-snapshots.parquet",
    "flow-rate-events.parquet",
    "resource-utilization.parquet",
    "store-directory-snapshots.parquet",
    "failure-events.parquet",
    "recovery-events.parquet",
    "capacity-audit.json",
    "run-audit.json",
    "summary.json",
)

SECTION_16_PARQUET_ARTIFACTS: Final[tuple[str, ...]] = tuple(
    name for name in SECTION_16_ARTIFACTS if name.endswith(".parquet")
)

_JSON_DOCUMENT_ARTIFACTS: Final[tuple[str, ...]] = (
    "trace-audit.json",
    "context-coverage.json",
    "capacity-audit.json",
    "run-audit.json",
    "summary.json",
)

_EVENT_TABLE_ARTIFACTS: Final[tuple[str, ...]] = (
    "batch-events.parquet",
    "kv-residency-events.parquet",
    "kv-transfer-events.parquet",
    "physical-allocation-events.parquet",
    "store-directory-snapshots.parquet",
    "failure-events.parquet",
    "recovery-events.parquet",
)


@dataclass(frozen=True, slots=True)
class ParquetColumn:
    """One dependency-independent fixed Parquet column declaration."""

    name: str
    type_name: str
    nullable: bool


_EVENT_COLUMNS: Final[tuple[ParquetColumn, ...]] = (
    ParquetColumn("timestamp_ns", "int64", False),
    ParquetColumn("stable_sequence", "int64", False),
    ParquetColumn("record_type", "string", False),
    ParquetColumn("data_json", "string", False),
)

_REQUEST_METRIC_COLUMNS: Final[tuple[ParquetColumn, ...]] = (
    ParquetColumn("workflow_id", "string", False),
    ParquetColumn("session_id", "string", False),
    ParquetColumn("agent_id", "string", False),
    ParquetColumn("agent_role", "string", False),
    ParquetColumn("span_id", "string", False),
    ParquetColumn("request_id", "string", False),
    ParquetColumn("parent_span_ids", "list_string", False),
    ParquetColumn("status", "string", False),
    ParquetColumn("target_replica_id", "string", True),
    ParquetColumn("route_version", "int64", True),
    ParquetColumn("arrival_ns", "int64", True),
    ParquetColumn("first_output_ns", "int64", True),
    ParquetColumn("last_output_ns", "int64", True),
    ParquetColumn("completion_ns", "int64", True),
    ParquetColumn("prompt_tokens", "int64", False),
    ParquetColumn("cached_prefix_tokens", "int64", False),
    ParquetColumn("output_tokens", "int64", False),
    ParquetColumn("emitted_output_count", "int64", False),
    ParquetColumn("total_context_tokens", "int64", False),
    ParquetColumn("context_bucket_upper", "int64", False),
    ParquetColumn("restored_tokens", "int64", False),
    ParquetColumn("recomputed_tokens", "int64", True),
    ParquetColumn("scheduler_step_count", "int64", False),
    ParquetColumn("predicted_forward_ns", "int64", False),
    ParquetColumn("ttft_ns", "int64", True),
    ParquetColumn("tpot_ns", "float64", True),
    ParquetColumn("e2e_ns", "int64", True),
    ParquetColumn("ttft_applicable", "bool", False),
    ParquetColumn("ttft_complete", "bool", False),
    ParquetColumn("ttft_evidence", "string", False),
    ParquetColumn("tpot_applicable", "bool", False),
    ParquetColumn("tpot_complete", "bool", False),
    ParquetColumn("tpot_evidence", "string", False),
    ParquetColumn("e2e_complete", "bool", False),
    ParquetColumn("e2e_evidence", "string", False),
    ParquetColumn("timing_complete", "bool", False),
    ParquetColumn("missing_evidence", "list_string", False),
    ParquetColumn("timing_basis", "string", False),
    ParquetColumn("source_evidence_class", "string", False),
    ParquetColumn("observed_api_time_used_as_simulated_time", "bool", False),
)

_WORKFLOW_METRIC_COLUMNS: Final[tuple[ParquetColumn, ...]] = (
    ParquetColumn("workflow_id", "string", False),
    ParquetColumn("status", "string", False),
    ParquetColumn("request_count", "int64", False),
    ParquetColumn("completed_request_count", "int64", False),
    ParquetColumn("arrival_ns", "int64", True),
    ParquetColumn("first_output_ns", "int64", True),
    ParquetColumn("last_output_ns", "int64", True),
    ParquetColumn("completion_ns", "int64", True),
    ParquetColumn("prompt_tokens", "int64", False),
    ParquetColumn("cached_prefix_tokens", "int64", False),
    ParquetColumn("output_tokens", "int64", False),
    ParquetColumn("emitted_output_count", "int64", False),
    ParquetColumn("restored_tokens", "int64", False),
    ParquetColumn("recomputed_tokens", "int64", True),
    ParquetColumn("scheduler_step_count", "int64", False),
    ParquetColumn("predicted_forward_ns", "int64", False),
    ParquetColumn("ttft_ns", "int64", True),
    ParquetColumn("tpot_ns", "float64", True),
    ParquetColumn("wct_ns", "int64", True),
    ParquetColumn("ttft_applicable", "bool", False),
    ParquetColumn("ttft_complete", "bool", False),
    ParquetColumn("ttft_evidence", "string", False),
    ParquetColumn("tpot_applicable", "bool", False),
    ParquetColumn("tpot_complete", "bool", False),
    ParquetColumn("tpot_evidence", "string", False),
    ParquetColumn("wct_complete", "bool", False),
    ParquetColumn("wct_evidence", "string", False),
    ParquetColumn("timing_complete", "bool", False),
    ParquetColumn("missing_evidence", "list_string", False),
    ParquetColumn("timing_basis", "string", False),
    ParquetColumn("observed_api_time_used_as_simulated_time", "bool", False),
)

_RESOURCE_DELTA_COLUMNS: Final[tuple[ParquetColumn, ...]] = (
    ParquetColumn("timestamp_ns", "int64", False),
    ParquetColumn("stable_sequence", "int64", False),
    ParquetColumn("delta_sequence", "int64", False),
    ParquetColumn("event_id", "string", False),
    ParquetColumn("cause", "string", False),
    ParquetColumn("resource_id", "string", False),
    ParquetColumn("resource_kind", "string", False),
    ParquetColumn("allocation_id", "string", False),
    ParquetColumn("object_id", "string", True),
    ParquetColumn("replica_id", "string", True),
    ParquetColumn("transfer_id", "string", True),
    ParquetColumn("account_from", "string", False),
    ParquetColumn("account_to", "string", False),
    ParquetColumn("requested_bytes", "int64", False),
    ParquetColumn("allocated_bytes", "int64", False),
    ParquetColumn("delta_bytes", "int64", False),
    ParquetColumn("before_bytes", "int64", False),
    ParquetColumn("after_bytes", "int64", False),
    ParquetColumn("from_before_bytes", "int64", False),
    ParquetColumn("from_after_bytes", "int64", False),
    ParquetColumn("to_before_bytes", "int64", False),
    ParquetColumn("to_after_bytes", "int64", False),
    ParquetColumn("capacity_bytes", "int64", False),
)

_RESOURCE_SNAPSHOT_COLUMNS: Final[tuple[ParquetColumn, ...]] = (
    ParquetColumn("timestamp_ns", "int64", False),
    ParquetColumn("stable_sequence", "int64", True),
    ParquetColumn("delta_sequence", "int64", True),
    ParquetColumn("boundary_index", "int64", False),
    ParquetColumn("event_id", "string", True),
    ParquetColumn("cause", "string", True),
    ParquetColumn("boundary_phase", "string", False),
    ParquetColumn("resource_id", "string", False),
    ParquetColumn("resource_kind", "string", False),
    ParquetColumn("account", "string", False),
    ParquetColumn("account_bytes", "int64", False),
    ParquetColumn("capacity_bytes", "int64", False),
    ParquetColumn("known_account_bytes", "int64", False),
    ParquetColumn("unknown_account_bytes", "int64", False),
    ParquetColumn("snapshot_complete", "bool", False),
    ParquetColumn("source_record_type", "string", False),
)

_FLOW_COLUMNS: Final[tuple[ParquetColumn, ...]] = (
    ParquetColumn("start_ns", "int64", False),
    ParquetColumn("end_ns", "int64", False),
    ParquetColumn("stable_sequence", "int64", False),
    ParquetColumn("flow_id", "string", False),
    ParquetColumn("transfer_id", "string", False),
    ParquetColumn("slice_id", "string", False),
    ParquetColumn("cause", "string", False),
    ParquetColumn("path_resource_ids", "list_string", False),
    ParquetColumn("payload_bytes", "int64", False),
    ParquetColumn("remaining_bytes", "float64", False),
    ParquetColumn("remaining_bytes_at_end", "float64", False),
    ParquetColumn("transferred_bytes", "float64", False),
    ParquetColumn("allocated_rate_Bps", "float64", False),
    ParquetColumn("queue_wait_ns", "int64", False),
    ParquetColumn("service_ns", "int64", False),
)

_RESOURCE_UTILIZATION_COLUMNS: Final[tuple[ParquetColumn, ...]] = (
    ParquetColumn("timestamp_ns", "int64", False),
    ParquetColumn("end_ns", "int64", True),
    ParquetColumn("stable_sequence", "int64", True),
    ParquetColumn("delta_sequence", "int64", True),
    ParquetColumn("resource_id", "string", False),
    ParquetColumn("resource_kind", "string", False),
    ParquetColumn("metric_kind", "string", False),
    ParquetColumn("account", "string", True),
    ParquetColumn("cause", "string", True),
    ParquetColumn("flow_id", "string", True),
    ParquetColumn("transfer_id", "string", True),
    ParquetColumn("path_hop_index", "int64", True),
    ParquetColumn("path_hop_count", "int64", True),
    ParquetColumn("account_bytes", "int64", True),
    ParquetColumn("capacity_bytes", "int64", True),
    ParquetColumn("allocated_rate_Bps", "float64", True),
    ParquetColumn("capacity_rate_Bps", "float64", True),
    ParquetColumn("utilization", "float64", True),
    ParquetColumn("transferred_bytes", "float64", True),
    ParquetColumn("byte_nanoseconds", "float64", True),
    ParquetColumn("evidence_complete", "bool", False),
    ParquetColumn("evidence", "string", False),
)

PARQUET_SCHEMAS: Final[Mapping[str, tuple[ParquetColumn, ...]]] = MappingProxyType(
    {
        "workflow-metrics.parquet": _WORKFLOW_METRIC_COLUMNS,
        "request-metrics.parquet": _REQUEST_METRIC_COLUMNS,
        "batch-events.parquet": _EVENT_COLUMNS,
        "kv-residency-events.parquet": _EVENT_COLUMNS,
        "kv-transfer-events.parquet": _EVENT_COLUMNS,
        "physical-allocation-events.parquet": _EVENT_COLUMNS,
        "resource-ledger-deltas.parquet": _RESOURCE_DELTA_COLUMNS,
        "resource-ledger-snapshots.parquet": _RESOURCE_SNAPSHOT_COLUMNS,
        "flow-rate-events.parquet": _FLOW_COLUMNS,
        "resource-utilization.parquet": _RESOURCE_UTILIZATION_COLUMNS,
        "store-directory-snapshots.parquet": _EVENT_COLUMNS,
        "failure-events.parquet": _EVENT_COLUMNS,
        "recovery-events.parquet": _EVENT_COLUMNS,
    }
)

if tuple(PARQUET_SCHEMAS) != SECTION_16_PARQUET_ARTIFACTS:
    raise RuntimeError("section-16 Parquet schema order drifted from the artifact contract")


@dataclass(frozen=True, slots=True)
class TraceExecutionProjection:
    """Explicit trace state permitted as a source for request/workflow metrics.

    Source-observed submit/finish/API durations are intentionally absent.  The
    only times accepted here are terminal simulated times; arrival, output, and
    normal completion boundaries are preferentially reconstructed from the
    canonical journal and cross-checked against ``completed_ns`` when present.
    """

    workflow_id: str
    session_id: str
    agent_id: str
    agent_role: str
    span_id: str
    request_id: str
    status: str
    prompt_tokens: int
    cached_prefix_tokens: int
    output_tokens: int
    restored_tokens: int
    scheduler_step_count: int
    predicted_forward_ns: int
    parent_span_ids: tuple[str, ...] = ()
    target_replica_id: str | None = None
    route_version: int | None = None
    completed_ns: int | None = None
    recomputed_tokens: int | None = None
    source_evidence_class: str = "E2"
    source_hash_ids_sha256: str | None = None
    truncated: bool | None = None
    padded: bool | None = None

    def __post_init__(self) -> None:
        string_fields: tuple[tuple[str, object], ...] = (
            ("workflow_id", self.workflow_id),
            ("session_id", self.session_id),
            ("agent_id", self.agent_id),
            ("agent_role", self.agent_role),
            ("span_id", self.span_id),
            ("request_id", self.request_id),
            ("status", self.status),
            ("source_evidence_class", self.source_evidence_class),
        )
        for name, value in string_fields:
            _require_nonempty_string(name, value)
        canonical_parents = tuple(sorted(set(self.parent_span_ids)))
        if any(not isinstance(item, str) or not item for item in canonical_parents):
            raise OutputContractError("parent_span_ids must contain non-empty strings")
        object.__setattr__(self, "parent_span_ids", canonical_parents)
        integer_fields: tuple[tuple[str, object], ...] = (
            ("prompt_tokens", self.prompt_tokens),
            ("cached_prefix_tokens", self.cached_prefix_tokens),
            ("output_tokens", self.output_tokens),
            ("restored_tokens", self.restored_tokens),
            ("scheduler_step_count", self.scheduler_step_count),
            ("predicted_forward_ns", self.predicted_forward_ns),
        )
        for name, value in integer_fields:
            _require_nonnegative_int(name, value)
        if self.cached_prefix_tokens > self.prompt_tokens:
            raise OutputContractError("cached_prefix_tokens cannot exceed prompt_tokens")
        if self.restored_tokens > self.prompt_tokens:
            raise OutputContractError("restored_tokens cannot exceed prompt_tokens")
        if self.prompt_tokens + self.output_tokens > MAX_MODEL_LEN_TOKENS:
            raise OutputContractError("trace execution exceeds the strict 131072-token guard")
        optional_integer_fields: tuple[tuple[str, object], ...] = (
            ("route_version", self.route_version),
            ("completed_ns", self.completed_ns),
            ("recomputed_tokens", self.recomputed_tokens),
        )
        for name, value in optional_integer_fields:
            if value is not None:
                _require_nonnegative_int(name, value)
        if self.target_replica_id is not None:
            _require_nonempty_string("target_replica_id", self.target_replica_id)
        if self.source_hash_ids_sha256 is not None and not _is_sha256(self.source_hash_ids_sha256):
            raise OutputContractError("source_hash_ids_sha256 must be lowercase SHA-256")
        optional_bool_fields: tuple[tuple[str, object], ...] = (
            ("truncated", self.truncated),
            ("padded", self.padded),
        )
        for name, value in optional_bool_fields:
            if value is not None and type(value) is not bool:
                raise OutputContractError(f"{name} must be bool or null")


@dataclass(frozen=True, slots=True)
class _ProjectedTable:
    name: str
    row_json: tuple[str, ...]

    def rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(cast(dict[str, Any], json.loads(item)) for item in self.row_json)


@dataclass(frozen=True, slots=True)
class Section16Projection:
    """Frozen in-memory 19-artifact projection, independent of ``pyarrow``."""

    journal_jsonl: bytes
    _tables: tuple[_ProjectedTable, ...]
    _json_payloads: tuple[tuple[str, bytes], ...]

    @property
    def artifact_names(self) -> tuple[str, ...]:
        return SECTION_16_ARTIFACTS

    def table_rows(self, name: str) -> tuple[dict[str, Any], ...]:
        for table in self._tables:
            if table.name == name:
                return table.rows()
        raise KeyError(name)

    def document(self, name: str) -> dict[str, Any]:
        for artifact_name, payload in self._json_payloads:
            if artifact_name == name:
                return cast(dict[str, Any], json.loads(payload))
        raise KeyError(name)

    def non_parquet_bytes(self, name: str) -> bytes:
        if name == "event-journal.jsonl":
            return self.journal_jsonl
        for artifact_name, payload in self._json_payloads:
            if artifact_name == name:
                return payload
        raise KeyError(name)

    def write(self, directory: Path) -> None:
        write_section_16_artifacts(self, directory)


@dataclass(frozen=True, slots=True)
class _RequestTimeline:
    arrival_ns: int | None
    arrival_evidence: str
    outputs: tuple[tuple[int, int, int], ...]
    journal_completion_ns: int | None


def parquet_schema_columns(name: str) -> tuple[ParquetColumn, ...]:
    """Return the fixed schema without importing the optional Parquet stack."""

    try:
        return PARQUET_SCHEMAS[name]
    except KeyError as error:
        raise KeyError(f"not a section-16 Parquet artifact: {name}") from error


def classify_journal_record(record: JournalRecord) -> tuple[str, ...]:
    """Return deterministic event-table views for one canonical journal record."""

    if not isinstance(record, JournalRecord):
        raise OutputContractError("event classification requires a JournalRecord")
    record_type = record.record_type
    categories: set[str] = set()

    if record_type in _BATCH_RECORD_TYPES or record_type.startswith(
        "TRACE_RUNNER_GPU_COMPUTE_LEASE_"
    ):
        categories.add("batch-events.parquet")
    if record_type.startswith("VLLM_HBM_") or record_type in _KV_RESIDENCY_RECORD_TYPES:
        categories.add("kv-residency-events.parquet")
    if record_type.startswith(_KV_TRANSFER_PREFIXES) or record_type in {
        "TRACE_RUNNER_GPU_FAILURE_TRANSFER_DEFERRED",
    }:
        categories.add("kv-transfer-events.parquet")
    if record_type.startswith("ALLOCATION_") or record_type == "RESOURCE_TRANSACTION":
        categories.add("physical-allocation-events.parquet")
    if record_type.startswith(("MASTER_", "STORE_CLIENT_")):
        categories.add("store-directory-snapshots.parquet")
    if _is_failure_record_type(record_type):
        categories.add("failure-events.parquet")
    if _is_recovery_record_type(record_type):
        categories.add("recovery-events.parquet")

    if record_type == "EVENT_EXECUTING":
        kind = record.data.get("kind")
        if not isinstance(kind, str) or not kind:
            raise OutputContractError("EVENT_EXECUTING is missing its kind")
        categories.update(_EXECUTED_KIND_TABLES.get(kind, ()))

    return tuple(name for name in _EVENT_TABLE_ARTIFACTS if name in categories)


def project_event_rows(
    journal: EventJournal,
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Project typed event views while retaining the complete canonical payload."""

    event_journal_jsonl_bytes(journal)
    projected: dict[str, list[dict[str, Any]]] = {name: [] for name in _EVENT_TABLE_ARTIFACTS}
    for record in journal.records:
        row = {
            "timestamp_ns": record.timestamp_ns,
            "stable_sequence": record.journal_sequence,
            "record_type": record.record_type,
            "data_json": _canonical_json_text(record.data),
        }
        for table_name in classify_journal_record(record):
            projected[table_name].append(row)
    return {name: tuple(projected[name]) for name in _EVENT_TABLE_ARTIFACTS}


def derive_request_metric_rows(
    journal: EventJournal,
    executions: Sequence[TraceExecutionProjection],
) -> tuple[dict[str, Any], ...]:
    """Derive request timing solely from simulated journal boundaries."""

    event_journal_jsonl_bytes(journal)
    ordered = _canonical_executions(executions)
    timelines = _request_timelines(journal, ordered)
    result: list[dict[str, Any]] = []
    for execution in ordered:
        timeline = timelines[execution.request_id]
        output_count = len(timeline.outputs)
        output_timestamps = tuple(item[1] for item in timeline.outputs)
        first_output_ns = min(output_timestamps) if output_timestamps else None
        last_output_ns = max(output_timestamps) if output_timestamps else None
        completion_ns = timeline.journal_completion_ns
        if execution.completed_ns is not None:
            if completion_ns is not None and completion_ns != execution.completed_ns:
                raise OutputContractError(
                    f"execution completion disagrees with journal for {execution.request_id}"
                )
            completion_ns = execution.completed_ns

        _validate_timeline_order(
            execution.request_id,
            timeline.arrival_ns,
            output_timestamps,
            completion_ns,
        )
        exact_output_sequence = _has_exact_output_sequence(
            timeline.outputs,
            execution.output_tokens,
        )
        missing: list[str] = []

        ttft_applicable = execution.output_tokens > 0
        if not ttft_applicable:
            ttft_ns = None
            ttft_complete = True
            ttft_evidence = "not_applicable_zero_output_tokens"
        elif timeline.arrival_ns is not None and first_output_ns is not None:
            ttft_ns = first_output_ns - timeline.arrival_ns
            ttft_complete = True
            ttft_evidence = "simulated_event_journal"
        else:
            ttft_ns = None
            ttft_complete = False
            ttft_evidence = "missing_simulated_arrival_or_first_output_boundary"
            missing.append("ttft_simulated_boundaries")

        tpot_applicable = execution.output_tokens >= 2
        if not tpot_applicable:
            tpot_ns = None
            tpot_complete = True
            tpot_evidence = "not_applicable_fewer_than_two_output_tokens"
        elif exact_output_sequence and first_output_ns is not None and last_output_ns is not None:
            tpot_ns = (last_output_ns - first_output_ns) / (execution.output_tokens - 1)
            tpot_complete = True
            tpot_evidence = "simulated_output_event_boundaries"
        else:
            tpot_ns = None
            tpot_complete = False
            tpot_evidence = "missing_complete_simulated_output_event_sequence"
            missing.append("tpot_complete_output_sequence")

        if timeline.arrival_ns is not None and completion_ns is not None:
            e2e_ns = completion_ns - timeline.arrival_ns
            e2e_complete = True
            e2e_evidence = "simulated_event_journal"
        else:
            e2e_ns = None
            e2e_complete = False
            e2e_evidence = "missing_simulated_arrival_or_completion_boundary"
            missing.append("e2e_simulated_boundaries")

        result.append(
            {
                "workflow_id": execution.workflow_id,
                "session_id": execution.session_id,
                "agent_id": execution.agent_id,
                "agent_role": execution.agent_role,
                "span_id": execution.span_id,
                "request_id": execution.request_id,
                "parent_span_ids": list(execution.parent_span_ids),
                "status": execution.status,
                "target_replica_id": execution.target_replica_id,
                "route_version": execution.route_version,
                "arrival_ns": timeline.arrival_ns,
                "first_output_ns": first_output_ns,
                "last_output_ns": last_output_ns,
                "completion_ns": completion_ns,
                "prompt_tokens": execution.prompt_tokens,
                "cached_prefix_tokens": execution.cached_prefix_tokens,
                "output_tokens": execution.output_tokens,
                "emitted_output_count": output_count,
                "total_context_tokens": execution.prompt_tokens + execution.output_tokens,
                "context_bucket_upper": _context_bucket(
                    execution.prompt_tokens + execution.output_tokens
                ),
                "restored_tokens": execution.restored_tokens,
                "recomputed_tokens": execution.recomputed_tokens,
                "scheduler_step_count": execution.scheduler_step_count,
                "predicted_forward_ns": execution.predicted_forward_ns,
                "ttft_ns": ttft_ns,
                "tpot_ns": tpot_ns,
                "e2e_ns": e2e_ns,
                "ttft_applicable": ttft_applicable,
                "ttft_complete": ttft_complete,
                "ttft_evidence": ttft_evidence,
                "tpot_applicable": tpot_applicable,
                "tpot_complete": tpot_complete,
                "tpot_evidence": tpot_evidence,
                "e2e_complete": e2e_complete,
                "e2e_evidence": e2e_evidence,
                "timing_complete": ttft_complete and tpot_complete and e2e_complete,
                "missing_evidence": sorted(missing),
                "timing_basis": ("canonical_simulated_event_boundaries;observed_api_time_excluded"),
                "source_evidence_class": execution.source_evidence_class,
                "observed_api_time_used_as_simulated_time": False,
            }
        )
    return tuple(result)


def derive_workflow_metric_rows(
    request_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Aggregate request rows without inventing cross-request TPOT semantics."""

    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in request_rows:
        workflow_id = _mapping_string(row, "workflow_id")
        grouped[workflow_id].append(row)

    result: list[dict[str, Any]] = []
    for workflow_id, rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda item: _mapping_string(item, "request_id"))
        arrivals = _present_ints(ordered, "arrival_ns")
        first_outputs = _present_ints(ordered, "first_output_ns")
        last_outputs = _present_ints(ordered, "last_output_ns")
        completions = _present_ints(ordered, "completion_ns")
        request_count = len(ordered)
        completed_count = sum(_mapping_string(row, "status") == "COMPLETED" for row in ordered)
        output_tokens = sum(_mapping_int(row, "output_tokens") for row in ordered)
        emitted_outputs = sum(_mapping_int(row, "emitted_output_count") for row in ordered)
        arrival_ns = min(arrivals) if arrivals else None
        first_output_ns = min(first_outputs) if first_outputs else None
        last_output_ns = max(last_outputs) if last_outputs else None
        completion_ns = max(completions) if completions else None
        missing: list[str] = []

        ttft_applicable = output_tokens > 0
        if not ttft_applicable:
            ttft_ns = None
            ttft_complete = True
            ttft_evidence = "not_applicable_zero_output_tokens"
        elif arrival_ns is not None and first_output_ns is not None:
            ttft_ns = first_output_ns - arrival_ns
            ttft_complete = True
            ttft_evidence = "simulated_event_journal"
        else:
            ttft_ns = None
            ttft_complete = False
            ttft_evidence = "missing_simulated_workflow_arrival_or_first_output"
            missing.append("workflow_ttft_simulated_boundaries")

        tpot_applicable = request_count == 1 and output_tokens >= 2
        if request_count > 1:
            tpot_ns = None
            tpot_complete = True
            tpot_evidence = "not_applicable_across_multiple_request_output_streams"
        elif not tpot_applicable:
            tpot_ns = None
            tpot_complete = True
            tpot_evidence = "not_applicable_fewer_than_two_output_tokens"
        elif request_count == 1 and bool(ordered[0].get("tpot_complete")):
            raw_tpot = ordered[0].get("tpot_ns")
            if not isinstance(raw_tpot, (int, float)) or isinstance(raw_tpot, bool):
                raise OutputContractError("complete request TPOT must be numeric")
            tpot_ns = float(raw_tpot)
            tpot_complete = True
            tpot_evidence = "single_request_simulated_output_event_boundaries"
        else:
            tpot_ns = None
            tpot_complete = False
            tpot_evidence = "missing_complete_single_request_output_event_sequence"
            missing.append("workflow_tpot_complete_output_sequence")

        all_arrivals = len(arrivals) == request_count
        all_completions = len(completions) == request_count
        if (
            all_arrivals
            and all_completions
            and arrival_ns is not None
            and completion_ns is not None
        ):
            wct_ns = completion_ns - arrival_ns
            wct_complete = True
            wct_evidence = "simulated_request_boundaries"
        else:
            wct_ns = None
            wct_complete = False
            wct_evidence = "missing_complete_simulated_request_boundaries"
            missing.append("workflow_wct_complete_request_boundaries")

        recomputed_values = [row.get("recomputed_tokens") for row in ordered]
        recomputed_tokens = (
            sum(cast(int, value) for value in recomputed_values)
            if all(type(value) is int for value in recomputed_values)
            else None
        )
        result.append(
            {
                "workflow_id": workflow_id,
                "status": "COMPLETED" if completed_count == request_count else "INCOMPLETE",
                "request_count": request_count,
                "completed_request_count": completed_count,
                "arrival_ns": arrival_ns,
                "first_output_ns": first_output_ns,
                "last_output_ns": last_output_ns,
                "completion_ns": completion_ns,
                "prompt_tokens": sum(_mapping_int(row, "prompt_tokens") for row in ordered),
                "cached_prefix_tokens": sum(
                    _mapping_int(row, "cached_prefix_tokens") for row in ordered
                ),
                "output_tokens": output_tokens,
                "emitted_output_count": emitted_outputs,
                "restored_tokens": sum(_mapping_int(row, "restored_tokens") for row in ordered),
                "recomputed_tokens": recomputed_tokens,
                "scheduler_step_count": sum(
                    _mapping_int(row, "scheduler_step_count") for row in ordered
                ),
                "predicted_forward_ns": sum(
                    _mapping_int(row, "predicted_forward_ns") for row in ordered
                ),
                "ttft_ns": ttft_ns,
                "tpot_ns": tpot_ns,
                "wct_ns": wct_ns,
                "ttft_applicable": ttft_applicable,
                "ttft_complete": ttft_complete,
                "ttft_evidence": ttft_evidence,
                "tpot_applicable": tpot_applicable,
                "tpot_complete": tpot_complete,
                "tpot_evidence": tpot_evidence,
                "wct_complete": wct_complete,
                "wct_evidence": wct_evidence,
                "timing_complete": ttft_complete and tpot_complete and wct_complete,
                "missing_evidence": sorted(missing),
                "timing_basis": ("canonical_simulated_event_boundaries;observed_api_time_excluded"),
                "observed_api_time_used_as_simulated_time": False,
            }
        )
    return tuple(result)


def derive_resource_snapshot_rows(
    resource_rows: Sequence[ResourceLedgerDeltaRow],
    *,
    initial_ledgers: Mapping[str, CapacityLedger] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Replay declared initial accounts and retain every delta boundary.

    A runner can supply its pristine ledgers to name accounts that never appear
    in a delta. Generic callers may omit them; that fallback remains explicitly
    partial instead of inventing account names.
    """

    ordered = canonical_resource_ledger_delta_rows(resource_rows)
    by_resource: dict[str, list[ResourceLedgerDeltaRow]] = defaultdict(list)
    for row in ordered:
        by_resource[row.resource_id].append(row)

    declared_ledgers = dict(initial_ledgers or {})
    for resource_id, ledger in declared_ledgers.items():
        if resource_id != ledger.resource_id:
            raise OutputContractError(
                f"initial ledger key disagrees with resource ID: {resource_id}"
            )

    snapshots: list[dict[str, Any]] = []
    for resource_id in sorted(set(by_resource) | set(declared_ledgers)):
        rows = by_resource.get(resource_id, [])
        declared = declared_ledgers.get(resource_id)
        if declared is not None:
            capacity_bytes = declared.capacity_bytes
            resource_kind = declared.resource_kind.value
            initial = dict(declared.accounts)
            initial_timestamp_ns = 0
            initial_phase = "INITIAL_DECLARED"
            initial_source = "initial-capacity-ledger"
        else:
            first = rows[0]
            capacity_bytes = first.capacity_bytes
            resource_kind = first.resource_kind.value
            initial = {}
            for row in rows:
                initial.setdefault(row.account_from, row.from_before_bytes)
                initial.setdefault(row.account_to, row.to_before_bytes)
            initial_timestamp_ns = first.timestamp_ns
            initial_phase = "INITIAL_RECONSTRUCTED"
            initial_source = "resource-ledger-deltas"
        for row in rows:
            if row.capacity_bytes != capacity_bytes or row.resource_kind.value != resource_kind:
                raise OutputContractError(
                    f"resource metadata changes during replay for {resource_id}"
                )
        known_initial = sum(initial.values())
        if known_initial > capacity_bytes:
            raise OutputContractError(f"known initial accounts exceed capacity for {resource_id}")
        state = dict(initial)
        _append_snapshot_boundary(
            snapshots,
            timestamp_ns=initial_timestamp_ns,
            stable_sequence=None,
            delta_sequence=None,
            boundary_index=0,
            event_id=None,
            cause=None,
            boundary_phase=initial_phase,
            resource_id=resource_id,
            resource_kind=resource_kind,
            state=state,
            capacity_bytes=capacity_bytes,
            source_record_type=initial_source,
        )
        for boundary_index, row in enumerate(rows, start=1):
            if (
                state.get(row.account_from, 0) != row.from_before_bytes
                or state.get(row.account_to, 0) != row.to_before_bytes
            ):
                raise OutputContractError(
                    f"delta replay before-state mismatch for {resource_id} at "
                    f"({row.stable_sequence},{row.delta_sequence})"
                )
            state[row.account_from] = row.from_after_bytes
            state[row.account_to] = row.to_after_bytes
            if any(value < 0 for value in state.values()) or sum(state.values()) > capacity_bytes:
                raise OutputContractError(
                    f"delta replay violates known-account capacity for {resource_id}"
                )
            _append_snapshot_boundary(
                snapshots,
                timestamp_ns=row.timestamp_ns,
                stable_sequence=row.stable_sequence,
                delta_sequence=row.delta_sequence,
                boundary_index=boundary_index,
                event_id=row.event_id,
                cause=row.cause,
                boundary_phase="AFTER_DELTA",
                resource_id=resource_id,
                resource_kind=resource_kind,
                state=state,
                capacity_bytes=capacity_bytes,
                source_record_type="RESOURCE_TRANSACTION",
            )
    return tuple(
        sorted(
            snapshots,
            key=lambda row: (
                cast(int, row["timestamp_ns"]),
                -1 if row["stable_sequence"] is None else cast(int, row["stable_sequence"]),
                -1 if row["delta_sequence"] is None else cast(int, row["delta_sequence"]),
                cast(str, row["resource_id"]),
                cast(str, row["account"]),
            ),
        )
    )


def derive_resource_utilization_rows(
    snapshot_rows: Sequence[Mapping[str, Any]],
    flow_rows: Sequence[FlowRateEventRow],
    *,
    run_end_ns: int | None,
) -> tuple[dict[str, Any], ...]:
    """Project capacity shares and explode every flow across its path resources."""

    if run_end_ns is not None:
        _require_nonnegative_int("run_end_ns", run_end_ns)
    boundaries: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in snapshot_rows:
        resource_id = _mapping_string(row, "resource_id")
        boundary_index = _mapping_int(row, "boundary_index")
        boundaries[(resource_id, boundary_index)].append(row)

    result: list[dict[str, Any]] = []
    by_resource: dict[str, list[tuple[int, list[Mapping[str, Any]]]]] = defaultdict(list)
    for (resource_id, boundary_index), rows in boundaries.items():
        by_resource[resource_id].append((boundary_index, rows))
    for resource_id, indexed_boundaries in sorted(by_resource.items()):
        ordered_boundaries = sorted(indexed_boundaries)
        for position, (_boundary_index, rows) in enumerate(ordered_boundaries):
            rows = sorted(rows, key=lambda item: _mapping_string(item, "account"))
            timestamp_ns = _mapping_int(rows[0], "timestamp_ns")
            if position + 1 < len(ordered_boundaries):
                next_rows = ordered_boundaries[position + 1][1]
                end_ns: int | None = _mapping_int(next_rows[0], "timestamp_ns")
            else:
                end_ns = (
                    run_end_ns if run_end_ns is not None and run_end_ns >= timestamp_ns else None
                )
            for row in rows:
                account_bytes = _mapping_int(row, "account_bytes")
                capacity_bytes = _mapping_int(row, "capacity_bytes")
                complete = _mapping_bool(row, "snapshot_complete")
                duration_ns = None if end_ns is None else end_ns - timestamp_ns
                result.append(
                    {
                        "timestamp_ns": timestamp_ns,
                        "end_ns": end_ns,
                        "stable_sequence": _mapping_optional_int(row, "stable_sequence"),
                        "delta_sequence": _mapping_optional_int(row, "delta_sequence"),
                        "resource_id": resource_id,
                        "resource_kind": _mapping_string(row, "resource_kind"),
                        "metric_kind": "CAPACITY_ACCOUNT",
                        "account": _mapping_string(row, "account"),
                        "cause": _mapping_optional_string(row, "cause"),
                        "flow_id": None,
                        "transfer_id": None,
                        "path_hop_index": None,
                        "path_hop_count": None,
                        "account_bytes": account_bytes,
                        "capacity_bytes": capacity_bytes,
                        "allocated_rate_Bps": None,
                        "capacity_rate_Bps": None,
                        "utilization": account_bytes / capacity_bytes,
                        "transferred_bytes": None,
                        "byte_nanoseconds": (
                            None if duration_ns is None else float(account_bytes * duration_ns)
                        ),
                        "evidence_complete": complete,
                        "evidence": (
                            "delta_replay_complete_snapshot"
                            if complete
                            else "delta_replay_partial_known_accounts"
                        ),
                    }
                )

    ordered_flows = canonical_flow_rate_event_rows(flow_rows)
    validate_flow_rate_sequence(ordered_flows)
    for flow in ordered_flows:
        hop_count = len(flow.path_resource_ids)
        for hop_index, resource_id in enumerate(flow.path_resource_ids):
            result.append(
                {
                    "timestamp_ns": flow.start_ns,
                    "end_ns": flow.end_ns,
                    "stable_sequence": flow.stable_sequence,
                    "delta_sequence": None,
                    "resource_id": resource_id,
                    "resource_kind": "RATE",
                    "metric_kind": "FLOW_RATE",
                    "account": None,
                    "cause": flow.cause,
                    "flow_id": flow.flow_id,
                    "transfer_id": flow.transfer_id,
                    "path_hop_index": hop_index,
                    "path_hop_count": hop_count,
                    "account_bytes": None,
                    "capacity_bytes": None,
                    "allocated_rate_Bps": flow.allocated_rate_Bps,
                    "capacity_rate_Bps": None,
                    "utilization": None,
                    "transferred_bytes": flow.transferred_bytes,
                    "byte_nanoseconds": None,
                    "evidence_complete": False,
                    "evidence": "rate_capacity_not_present_in_flow_rows",
                }
            )
    return tuple(sorted(result, key=_utilization_sort_key))


def build_section_16_projection(
    *,
    journal: EventJournal,
    resource_rows: Sequence[ResourceLedgerDeltaRow] = (),
    flow_rows: Sequence[FlowRateEventRow] = (),
    executions: Sequence[TraceExecutionProjection] = (),
    initial_ledgers: Mapping[str, CapacityLedger] | None = None,
    runner_documents: Mapping[str, Mapping[str, Any]] | None = None,
) -> Section16Projection:
    """Build all 19 artifacts without importing ``pyarrow`` or runner code.

    ``runner_documents`` preserves runner-owned provenance and audits under a
    ``trace_runner`` namespace.  Selected compatibility fields are also copied
    to the top level when they do not replace projection-owned truth.  This
    avoids discarding source selection, predictor, gap, and replay evidence
    while keeping this module independent of the baseline implementation.
    """

    journal_bytes = event_journal_jsonl_bytes(journal)
    ordered_resources = canonical_resource_ledger_delta_rows(resource_rows)
    ordered_flows = canonical_flow_rate_event_rows(flow_rows)
    validate_flow_rate_sequence(ordered_flows)
    ordered_executions = _canonical_executions(executions)
    event_tables = project_event_rows(journal)
    request_rows = derive_request_metric_rows(journal, ordered_executions)
    workflow_rows = derive_workflow_metric_rows(request_rows)
    snapshot_rows = derive_resource_snapshot_rows(
        ordered_resources,
        initial_ledgers=initial_ledgers,
    )
    run_end_ns = journal.records[-1].timestamp_ns if journal.records else None
    utilization_rows = derive_resource_utilization_rows(
        snapshot_rows,
        ordered_flows,
        run_end_ns=run_end_ns,
    )

    raw_tables: dict[str, Sequence[Mapping[str, Any]]] = {
        "workflow-metrics.parquet": workflow_rows,
        "request-metrics.parquet": request_rows,
        **event_tables,
        "resource-ledger-deltas.parquet": tuple(row.to_dict() for row in ordered_resources),
        "resource-ledger-snapshots.parquet": snapshot_rows,
        "flow-rate-events.parquet": tuple(row.to_dict() for row in ordered_flows),
        "resource-utilization.parquet": utilization_rows,
    }
    tables = tuple(_freeze_table(name, raw_tables[name]) for name in SECTION_16_PARQUET_ARTIFACTS)
    row_counts = {table.name: len(table.row_json) for table in tables}

    trace_audit = _trace_audit_document(journal, ordered_executions)
    context_coverage = _context_coverage_document(ordered_executions)
    capacity_audit = _capacity_audit_document(
        ordered_resources,
        ordered_flows,
        snapshot_rows,
    )
    run_audit = _run_audit_document(
        ordered_executions,
        request_rows,
        workflow_rows,
        row_counts,
        capacity_audit,
    )
    summary = _summary_document(
        ordered_executions,
        request_rows,
        workflow_rows,
        snapshot_rows,
        row_counts,
    )
    documents = {
        "trace-audit.json": trace_audit,
        "context-coverage.json": context_coverage,
        "capacity-audit.json": capacity_audit,
        "run-audit.json": run_audit,
        "summary.json": summary,
    }
    _merge_runner_documents(documents, runner_documents)
    payloads = tuple(
        (name, _canonical_json_bytes(documents[name])) for name in _JSON_DOCUMENT_ARTIFACTS
    )
    return Section16Projection(journal_bytes, tables, payloads)


def _merge_runner_documents(
    documents: Mapping[str, dict[str, Any]],
    runner_documents: Mapping[str, Mapping[str, Any]] | None,
) -> None:
    if runner_documents is None:
        return
    allowed = frozenset(_JSON_DOCUMENT_ARTIFACTS)
    unexpected = set(runner_documents) - allowed
    if unexpected:
        raise OutputContractError(
            f"runner document context contains unexpected artifacts: {sorted(unexpected)}"
        )
    for name, raw_context in runner_documents.items():
        if not isinstance(raw_context, Mapping):
            raise OutputContractError(f"runner document context for {name} must be a mapping")
        context = cast(dict[str, Any], json.loads(_canonical_json_bytes(raw_context)))
        documents[name]["trace_runner"] = context
        runner_status = context.get("status")
        if name in {
            "trace-audit.json",
            "run-audit.json",
            "summary.json",
        } and isinstance(runner_status, str):
            documents[name]["projection_status"] = documents[name]["status"]
            documents[name]["status"] = runner_status
        evidence_boundary = context.get("evidence_boundary")
        if isinstance(evidence_boundary, str):
            documents[name]["evidence_boundary"] = evidence_boundary

    trace_context = runner_documents.get("trace-audit.json")
    if trace_context is not None:
        for key in (
            "source_path",
            "source_sha256",
            "total_valid_span_count",
            "selected_span_count",
            "selected_workflow_ids",
            "selection",
            "guard",
            "source_hash_scope",
            "store_payload_contract",
            "spans",
        ):
            if key in trace_context:
                documents["trace-audit.json"][key] = cast(
                    Any,
                    json.loads(_canonical_json_bytes(trace_context[key])),
                )

    run_context = runner_documents.get("run-audit.json")
    if run_context is not None:
        for key in (
            "predictor",
            "gaps",
            "ledger_replay_byte_identical",
            "allocation_registry_replay_byte_identical",
            "transfer_resource_calendar_replay_byte_identical",
            "flow_rate_state_replay_byte_identical",
            "journal_replay_byte_identical",
            "semantic_source_provenance",
            "failure_protocol",
            "transfer_resource_protocol",
        ):
            if key in run_context:
                documents["run-audit.json"][key] = cast(
                    Any,
                    json.loads(_canonical_json_bytes(run_context[key])),
                )
        if "capacity_audit" in run_context:
            documents["run-audit.json"]["trace_runner_capacity_audit"] = cast(
                Any,
                json.loads(_canonical_json_bytes(run_context["capacity_audit"])),
            )

    capacity_context = runner_documents.get("capacity-audit.json")
    if capacity_context is not None:
        documents["capacity-audit.json"]["trace_runner_capacity_audit"] = cast(
            Any,
            json.loads(_canonical_json_bytes(capacity_context)),
        )


def write_section_16_artifacts(
    projection: Section16Projection,
    directory: Path,
) -> None:
    """Publish the exact 19-file set with strict no-clobber semantics."""

    if not isinstance(projection, Section16Projection):
        raise TypeError("projection must be a Section16Projection")
    destination = Path(directory)
    if os.path.lexists(destination):
        raise FileExistsError(
            errno.EEXIST,
            "refusing to overwrite an existing section-16 artifact directory",
            destination,
        )
    parent = destination.parent
    if not parent.is_dir():
        raise FileNotFoundError(f"section-16 output parent does not exist: {parent}")
    pyarrow, parquet = _load_pyarrow()
    staging = Path(
        tempfile.mkdtemp(
            dir=parent,
            prefix=f".{destination.name}.section16-staging-",
        )
    )
    published = False
    try:
        table_by_name = {table.name: table for table in projection._tables}
        for name in SECTION_16_ARTIFACTS:
            path = staging / name
            if name.endswith(".parquet"):
                _write_parquet_table(
                    table_by_name[name],
                    path,
                    pyarrow=pyarrow,
                    parquet=parquet,
                )
            else:
                _write_exclusive(path, projection.non_parquet_bytes(name))
        actual = tuple(sorted(path.name for path in staging.iterdir()))
        if actual != tuple(sorted(SECTION_16_ARTIFACTS)):
            raise RuntimeError("staged section-16 artifact set is incomplete")
        _atomic_rename_no_replace(staging, destination)
        published = True
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)


_BATCH_RECORD_TYPES: Final[frozenset[str]] = frozenset(
    {
        "BASELINE_SCHEDULER_STEP",
        "TRACE_RUNNER_FORWARD_PREDICTED",
        "BASELINE_FORWARD_BATCH_SCHEDULED",
        "BASELINE_FORWARD_BATCH_COMPLETED",
        "BASELINE_FORWARD_BATCH_FENCED",
        "BASELINE_FORWARD_BATCH_REGISTRATION_ROLLBACK",
    }
)
_KV_RESIDENCY_RECORD_TYPES: Final[frozenset[str]] = frozenset(
    {
        "TRACE_RUNNER_REMOTE_PREFIX_WAITING",
        "TRACE_RUNNER_REMOTE_PREFIX_READY",
    }
)
_KV_TRANSFER_PREFIXES: Final[tuple[str, ...]] = (
    "TRANSFER_RUNTIME_",
    "TRANSFER_RESOURCE_",
    "TRANSFER_ENDPOINT_",
    "BASELINE_TRANSFER_",
    "STORE_CLIENT_SLICE_",
    "STORE_CLIENT_TRANSFER_",
)
_FAILURE_TOKENS: Final[tuple[str, ...]] = (
    "FAILURE",
    "FAILED",
    "FAIL_STOP",
    "FENCED",
)
_RECOVERY_TOKENS: Final[tuple[str, ...]] = (
    "RECOVERY",
    "REROUT",
    "REPAIR",
    "SILENT_REPLAY",
)

_EXECUTED_KIND_TABLES: Final[Mapping[str, tuple[str, ...]]] = {
    "SCHEDULER_STEP_READY": ("batch-events.parquet",),
    "FORWARD_START": ("batch-events.parquet",),
    "FORWARD_COMPLETE": ("batch-events.parquet",),
    "KV_BLOCK_ALLOCATE": ("kv-residency-events.parquet",),
    "KV_BLOCK_FREE": ("kv-residency-events.parquet",),
    "STAGING_ACQUIRE": ("kv-transfer-events.parquet",),
    "STAGING_RELEASE": ("kv-transfer-events.parquet",),
    "ENDPOINT_REGISTRATION_START": ("kv-transfer-events.parquet",),
    "ENDPOINT_REGISTRATION_COMPLETE": ("kv-transfer-events.parquet",),
    "ENDPOINT_READY": ("kv-transfer-events.parquet",),
    "TRANSFER_START": ("kv-transfer-events.parquet",),
    "TRANSFER_SLICE_START": ("kv-transfer-events.parquet",),
    "FLOW_RATE_UPDATE": ("kv-transfer-events.parquet",),
    "TRANSFER_SLICE_COMPLETE": ("kv-transfer-events.parquet",),
    "TRANSFER_COMPLETE": ("kv-transfer-events.parquet",),
    "STORE_QUERY": ("store-directory-snapshots.parquet",),
    "PUT_START": ("store-directory-snapshots.parquet",),
    "PUT_ALLOCATED": ("store-directory-snapshots.parquet",),
    "PUT_COMMIT": ("store-directory-snapshots.parquet",),
    "GET_START": ("store-directory-snapshots.parquet",),
    "GET_COMPLETE": ("store-directory-snapshots.parquet",),
    "EVICTION_START": ("store-directory-snapshots.parquet",),
    "EVICTION_COMPLETE": ("store-directory-snapshots.parquet",),
    "DIRECTORY_PUBLISH": ("store-directory-snapshots.parquet",),
    "FAILURE_INJECT": ("failure-events.parquet",),
    "FAILURE_DETECT": ("failure-events.parquet",),
    "ROUTE_FENCE": ("failure-events.parquet",),
    "REROUTE": ("recovery-events.parquet",),
    "RECOVERY_START": ("recovery-events.parquet",),
    "RECOVERY_COMPLETE": ("recovery-events.parquet",),
    "SILENT_REPLAY_COMPLETE": ("recovery-events.parquet",),
    "REPAIR_COMPLETE": ("recovery-events.parquet",),
}


def _is_failure_record_type(record_type: str) -> bool:
    return any(token in record_type for token in _FAILURE_TOKENS)


def _is_recovery_record_type(record_type: str) -> bool:
    return any(token in record_type for token in _RECOVERY_TOKENS)


def _canonical_executions(
    executions: Sequence[TraceExecutionProjection],
) -> tuple[TraceExecutionProjection, ...]:
    for execution in executions:
        if not isinstance(execution, TraceExecutionProjection):
            raise OutputContractError("executions must contain TraceExecutionProjection values")
    ordered = tuple(
        sorted(
            executions,
            key=lambda item: (item.workflow_id, item.span_id, item.request_id),
        )
    )
    if len({item.span_id for item in ordered}) != len(ordered):
        raise OutputContractError("trace execution span IDs must be unique")
    if len({item.request_id for item in ordered}) != len(ordered):
        raise OutputContractError("trace execution request IDs must be unique")
    by_span = {item.span_id: item for item in ordered}
    for item in ordered:
        for parent_id in item.parent_span_ids:
            parent = by_span.get(parent_id)
            if parent is None:
                raise OutputContractError(
                    f"execution {item.span_id} has unknown parent {parent_id}"
                )
            if parent.workflow_id != item.workflow_id:
                raise OutputContractError(f"execution {item.span_id} has a cross-workflow parent")
    return ordered


def _request_timelines(
    journal: EventJournal,
    executions: Sequence[TraceExecutionProjection],
) -> dict[str, _RequestTimeline]:
    by_request = {item.request_id: item for item in executions}
    admitted: dict[str, tuple[int, str]] = {}
    baseline_admitted: dict[str, tuple[int, str]] = {}
    released: dict[str, tuple[int, str]] = {}
    completions: dict[str, int] = {}
    outputs: dict[str, list[tuple[int, int, int]]] = defaultdict(list)

    for record in journal.records:
        data = record.data
        if record.record_type == "TRACE_RUNNER_SPAN_ADMITTED":
            request_id = _mapping_string(data, "request_id")
            span_id = _mapping_string(data, "span_id")
            if request_id in by_request and by_request[request_id].span_id != span_id:
                raise OutputContractError("span admission disagrees with explicit execution")
            _put_unique_boundary(
                admitted,
                request_id,
                (record.timestamp_ns, "TRACE_RUNNER_SPAN_ADMITTED"),
            )
        elif record.record_type == "BASELINE_REQUEST_ADMITTED":
            request_id = _mapping_string(data, "request_id")
            _put_unique_boundary(
                baseline_admitted,
                request_id,
                (record.timestamp_ns, "BASELINE_REQUEST_ADMITTED"),
            )
        elif record.record_type == "WORKLOAD_SPAN_RELEASED":
            span_id = _mapping_string(data, "span_id")
            _put_unique_boundary(
                released,
                span_id,
                (record.timestamp_ns, "WORKLOAD_SPAN_RELEASED"),
            )
        elif record.record_type == "BASELINE_OUTPUT_ACTIVATED":
            request_id = _mapping_string(data, "request_id")
            output_index = _mapping_int(data, "output_index")
            outputs[request_id].append((output_index, record.timestamp_ns, record.journal_sequence))
        elif record.record_type == "TRACE_RUNNER_SPAN_COMPLETED":
            request_id = _mapping_string(data, "request_id")
            previous = completions.get(request_id)
            if previous is not None and previous != record.timestamp_ns:
                raise OutputContractError(f"multiple completion boundaries for {request_id}")
            completions[request_id] = record.timestamp_ns

    result: dict[str, _RequestTimeline] = {}
    for request_id, execution in by_request.items():
        arrival = admitted.get(request_id)
        if arrival is None:
            arrival = baseline_admitted.get(request_id)
        if arrival is None:
            arrival = released.get(execution.span_id)
        ordered_outputs = tuple(
            sorted(outputs.get(request_id, ()), key=lambda item: (item[0], item[2]))
        )
        if len({item[0] for item in ordered_outputs}) != len(ordered_outputs):
            raise OutputContractError(f"duplicate activated output index for {request_id}")
        result[request_id] = _RequestTimeline(
            arrival_ns=None if arrival is None else arrival[0],
            arrival_evidence="missing" if arrival is None else arrival[1],
            outputs=ordered_outputs,
            journal_completion_ns=completions.get(request_id),
        )
    return result


def _put_unique_boundary(
    boundaries: dict[str, tuple[int, str]],
    key: str,
    value: tuple[int, str],
) -> None:
    previous = boundaries.get(key)
    if previous is not None and previous != value:
        raise OutputContractError(f"multiple inconsistent boundaries for {key}")
    boundaries[key] = value


def _has_exact_output_sequence(
    outputs: Sequence[tuple[int, int, int]],
    expected_count: int,
) -> bool:
    return [item[0] for item in outputs] == list(range(expected_count))


def _validate_timeline_order(
    request_id: str,
    arrival_ns: int | None,
    output_timestamps: Sequence[int],
    completion_ns: int | None,
) -> None:
    if arrival_ns is not None and any(item < arrival_ns for item in output_timestamps):
        raise OutputContractError(f"output precedes arrival for {request_id}")
    if completion_ns is not None:
        if arrival_ns is not None and completion_ns < arrival_ns:
            raise OutputContractError(f"completion precedes arrival for {request_id}")
        if any(item > completion_ns for item in output_timestamps):
            raise OutputContractError(f"output follows completion for {request_id}")


def _append_snapshot_boundary(
    target: list[dict[str, Any]],
    *,
    timestamp_ns: int,
    stable_sequence: int | None,
    delta_sequence: int | None,
    boundary_index: int,
    event_id: str | None,
    cause: str | None,
    boundary_phase: str,
    resource_id: str,
    resource_kind: str,
    state: Mapping[str, int],
    capacity_bytes: int,
    source_record_type: str,
) -> None:
    known = sum(state.values())
    unknown = capacity_bytes - known
    complete = unknown == 0
    for account, account_bytes in sorted(state.items()):
        target.append(
            {
                "timestamp_ns": timestamp_ns,
                "stable_sequence": stable_sequence,
                "delta_sequence": delta_sequence,
                "boundary_index": boundary_index,
                "event_id": event_id,
                "cause": cause,
                "boundary_phase": boundary_phase,
                "resource_id": resource_id,
                "resource_kind": resource_kind,
                "account": account,
                "account_bytes": account_bytes,
                "capacity_bytes": capacity_bytes,
                "known_account_bytes": known,
                "unknown_account_bytes": unknown,
                "snapshot_complete": complete,
                "source_record_type": source_record_type,
            }
        )


def _utilization_sort_key(row: Mapping[str, Any]) -> tuple[object, ...]:
    return (
        cast(int, row["timestamp_ns"]),
        -1 if row["stable_sequence"] is None else cast(int, row["stable_sequence"]),
        -1 if row["delta_sequence"] is None else cast(int, row["delta_sequence"]),
        cast(str, row["resource_id"]),
        cast(str, row["metric_kind"]),
        "" if row["account"] is None else cast(str, row["account"]),
        "" if row["flow_id"] is None else cast(str, row["flow_id"]),
        -1 if row["path_hop_index"] is None else cast(int, row["path_hop_index"]),
    )


def _trace_audit_document(
    journal: EventJournal,
    executions: Sequence[TraceExecutionProjection],
) -> dict[str, Any]:
    status = _execution_status(executions)
    hashes_complete = all(item.source_hash_ids_sha256 is not None for item in executions)
    integrity_complete = all(
        item.truncated is not None and item.padded is not None for item in executions
    )
    return {
        "schema": SECTION_16_SCHEMA_VERSION,
        "artifact": "trace-audit.json",
        "status": status,
        "evidence_class": "E2",
        "formal_use_allowed": False,
        "truth_sources": ["canonical-event-journal", "explicit-trace-executions"],
        "journal_record_count": len(journal.records),
        "execution_count": len(executions),
        "workflow_count": len({item.workflow_id for item in executions}),
        "lineage_complete": all(
            item.workflow_id and item.session_id and item.agent_id and item.span_id
            for item in executions
        ),
        "source_hash_evidence_complete": hashes_complete,
        "integrity_evidence_complete": integrity_complete,
        "truncated_count": (
            sum(item.truncated is True for item in executions) if integrity_complete else None
        ),
        "padded_count": (
            sum(item.padded is True for item in executions) if integrity_complete else None
        ),
        "strict_max_model_len_tokens": MAX_MODEL_LEN_TOKENS,
        "recorded_api_time_used_as_simulated_time": False,
        "missing_evidence": sorted(
            [
                *("source_hash_ids_sha256" for _ in [0] if not hashes_complete),
                *("truncation_and_padding_flags" for _ in [0] if not integrity_complete),
            ]
        ),
    }


def _context_coverage_document(
    executions: Sequence[TraceExecutionProjection],
) -> dict[str, Any]:
    bucket_requests: dict[int, int] = defaultdict(int)
    bucket_workflows: dict[int, set[str]] = defaultdict(set)
    totals: list[int] = []
    for item in executions:
        total = item.prompt_tokens + item.output_tokens
        upper = _context_bucket(total)
        totals.append(total)
        bucket_requests[upper] += 1
        bucket_workflows[upper].add(item.workflow_id)
    lower = 0
    buckets: list[dict[str, Any]] = []
    for upper in CONTEXT_BUCKET_UPPER_BOUNDS:
        buckets.append(
            {
                "lower_exclusive": lower,
                "upper_inclusive": upper,
                "request_count": bucket_requests[upper],
                "workflow_count": len(bucket_workflows[upper]),
            }
        )
        lower = upper
    return {
        "schema": SECTION_16_SCHEMA_VERSION,
        "artifact": "context-coverage.json",
        "source": "explicit-trace-executions",
        "context_buckets": buckets,
        "request_count": len(executions),
        "workflow_count": len({item.workflow_id for item in executions}),
        "max_total_model_tokens": max(totals) if totals else None,
        "strict_max_model_len_tokens": MAX_MODEL_LEN_TOKENS,
        "coverage_complete": True,
        "recorded_api_time_used_as_simulated_time": False,
    }


def _capacity_audit_document(
    resource_rows: Sequence[ResourceLedgerDeltaRow],
    flow_rows: Sequence[FlowRateEventRow],
    snapshot_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    resource_ids = sorted(
        {row.resource_id for row in resource_rows}
        | {_mapping_string(row, "resource_id") for row in snapshot_rows}
    )
    incomplete = sorted(
        {
            _mapping_string(row, "resource_id")
            for row in snapshot_rows
            if not _mapping_bool(row, "snapshot_complete")
        }
    )
    has_declared_initial_state = any(
        _mapping_string(row, "source_record_type") == "initial-capacity-ledger"
        for row in snapshot_rows
    )
    truth_sources = ["flow-rate-events", "resource-ledger-deltas"]
    if has_declared_initial_state:
        truth_sources.append("initial-capacity-ledgers")
    if incomplete:
        snapshot_completeness_evidence = (
            "untouched_initial_accounts_not_named_by_available_truth_sources"
        )
    elif has_declared_initial_state:
        snapshot_completeness_evidence = "initial_capacity_ledgers_plus_delta_replay"
    else:
        snapshot_completeness_evidence = "all_capacity_accounts_observed_in_deltas"
    return {
        "schema": SECTION_16_SCHEMA_VERSION,
        "artifact": "capacity-audit.json",
        "status": "PASS",
        "valid": True,
        "truth_sources": sorted(truth_sources),
        "resource_delta_replay_valid": True,
        "flow_byte_conservation_valid": True,
        "resource_delta_count": len(resource_rows),
        "flow_interval_count": len(flow_rows),
        "resource_count": len(resource_ids),
        "event_boundary_snapshots_preserved": True,
        "snapshot_state_complete": not incomplete,
        "incomplete_resource_ids": incomplete,
        "snapshot_completeness_evidence": snapshot_completeness_evidence,
    }


def _run_audit_document(
    executions: Sequence[TraceExecutionProjection],
    request_rows: Sequence[Mapping[str, Any]],
    workflow_rows: Sequence[Mapping[str, Any]],
    row_counts: Mapping[str, int],
    capacity_audit: Mapping[str, Any],
) -> dict[str, Any]:
    request_timing_complete = sum(_mapping_bool(row, "timing_complete") for row in request_rows)
    workflow_timing_complete = sum(_mapping_bool(row, "timing_complete") for row in workflow_rows)
    capacity_truth_sources = capacity_audit.get("truth_sources")
    if type(capacity_truth_sources) is not list or any(
        not isinstance(item, str) or not item for item in capacity_truth_sources
    ):
        raise OutputContractError("capacity audit truth_sources must be an array of strings")
    truth_sources = [
        "canonical-event-journal",
        "resource-ledger-deltas",
        "flow-rate-events",
        "explicit-trace-executions",
    ]
    if "initial-capacity-ledgers" in capacity_truth_sources:
        truth_sources.insert(2, "initial-capacity-ledgers")
    schemas = {
        name: hashlib.sha256(
            _canonical_json_bytes(
                [
                    {
                        "name": column.name,
                        "type": column.type_name,
                        "nullable": column.nullable,
                    }
                    for column in PARQUET_SCHEMAS[name]
                ]
            )
        ).hexdigest()
        for name in SECTION_16_PARQUET_ARTIFACTS
    }
    return {
        "schema": SECTION_16_SCHEMA_VERSION,
        "artifact": "run-audit.json",
        "status": "PASS" if bool(capacity_audit["valid"]) else "FAIL",
        "execution_status": _execution_status(executions),
        "evidence_class": "E2",
        "formal_use_allowed": False,
        "derived_only": True,
        "truth_sources": truth_sources,
        "section_16": {
            "artifact_count": len(SECTION_16_ARTIFACTS),
            "expected_artifacts": list(SECTION_16_ARTIFACTS),
            "complete_file_set": True,
            "fixed_parquet_schemas": schemas,
            "parquet_row_counts": dict(sorted(row_counts.items())),
        },
        "capacity": dict(capacity_audit),
        "timing_metrics": {
            "request_count": len(request_rows),
            "request_complete_count": request_timing_complete,
            "workflow_count": len(workflow_rows),
            "workflow_complete_count": workflow_timing_complete,
            "missing_values_are_null": True,
            "completeness_and_evidence_flags_present": True,
            "observed_api_time_used_as_simulated_time": False,
        },
    }


def _summary_document(
    executions: Sequence[TraceExecutionProjection],
    request_rows: Sequence[Mapping[str, Any]],
    workflow_rows: Sequence[Mapping[str, Any]],
    snapshot_rows: Sequence[Mapping[str, Any]],
    row_counts: Mapping[str, int],
) -> dict[str, Any]:
    peaks: dict[tuple[str, str], tuple[int, int, int | None, int | None]] = {}
    for row in snapshot_rows:
        key = (_mapping_string(row, "resource_id"), _mapping_string(row, "account"))
        value = _mapping_int(row, "account_bytes")
        candidate = (
            value,
            _mapping_int(row, "timestamp_ns"),
            _mapping_optional_int(row, "stable_sequence"),
            _mapping_optional_int(row, "delta_sequence"),
        )
        previous = peaks.get(key)
        if previous is None or candidate[0] > previous[0]:
            peaks[key] = candidate
    return {
        "schema": SECTION_16_SCHEMA_VERSION,
        "artifact": "summary.json",
        "status": _execution_status(executions),
        "evidence_class": "E2",
        "formal_use_allowed": False,
        "request_count": len(request_rows),
        "workflow_count": len(workflow_rows),
        "completed_request_count": sum(
            _mapping_string(row, "status") == "COMPLETED" for row in request_rows
        ),
        "prompt_tokens": sum(_mapping_int(row, "prompt_tokens") for row in request_rows),
        "output_tokens": sum(_mapping_int(row, "output_tokens") for row in request_rows),
        "restored_tokens": sum(_mapping_int(row, "restored_tokens") for row in request_rows),
        "scheduler_step_count": sum(
            _mapping_int(row, "scheduler_step_count") for row in request_rows
        ),
        "predicted_forward_ns": sum(
            _mapping_int(row, "predicted_forward_ns") for row in request_rows
        ),
        "request_timing_complete_count": sum(
            _mapping_bool(row, "timing_complete") for row in request_rows
        ),
        "workflow_timing_complete_count": sum(
            _mapping_bool(row, "timing_complete") for row in workflow_rows
        ),
        "resource_account_peaks": [
            {
                "resource_id": resource_id,
                "account": account,
                "peak_bytes": peak[0],
                "timestamp_ns": peak[1],
                "stable_sequence": peak[2],
                "delta_sequence": peak[3],
            }
            for (resource_id, account), peak in sorted(peaks.items())
        ],
        "parquet_row_counts": dict(sorted(row_counts.items())),
        "observed_api_time_used_as_simulated_time": False,
    }


def _execution_status(executions: Sequence[TraceExecutionProjection]) -> str:
    if not executions:
        return "EMPTY"
    return "PASS" if all(item.status == "COMPLETED" for item in executions) else "INCOMPLETE"


def _freeze_table(
    name: str,
    rows: Sequence[Mapping[str, Any]],
) -> _ProjectedTable:
    columns = PARQUET_SCHEMAS[name]
    expected_names = tuple(column.name for column in columns)
    encoded: list[str] = []
    for index, row in enumerate(rows):
        if tuple(row) != expected_names and set(row) != set(expected_names):
            missing = sorted(set(expected_names) - set(row))
            unexpected = sorted(set(row) - set(expected_names))
            raise OutputContractError(
                f"{name} row {index} violates fixed schema: "
                f"missing={missing}, unexpected={unexpected}"
            )
        canonical = {column.name: row[column.name] for column in columns}
        for column in columns:
            _validate_column_value(name, index, column, canonical[column.name])
        encoded.append(_canonical_json_text(canonical))
    return _ProjectedTable(name, tuple(encoded))


def _validate_column_value(
    table_name: str,
    row_index: int,
    column: ParquetColumn,
    value: object,
) -> None:
    if value is None:
        if not column.nullable:
            raise OutputContractError(
                f"{table_name} row {row_index} has null non-nullable {column.name}"
            )
        return
    valid = False
    if column.type_name == "int64":
        valid = type(value) is int and -(2**63) <= value < 2**63
    elif column.type_name == "float64":
        valid = (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    elif column.type_name == "string":
        valid = isinstance(value, str)
    elif column.type_name == "bool":
        valid = type(value) is bool
    elif column.type_name == "list_string":
        valid = isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value)
    else:
        raise RuntimeError(f"unsupported fixed Parquet type: {column.type_name}")
    if not valid:
        raise OutputContractError(
            f"{table_name} row {row_index} has invalid {column.type_name} value for {column.name}"
        )


def _load_pyarrow() -> tuple[ModuleType, ModuleType]:
    try:
        pyarrow = importlib.import_module("pyarrow")
        parquet = importlib.import_module("pyarrow.parquet")
    except ModuleNotFoundError as error:
        raise ParquetUnavailableError(
            "the complete section-16 matrix requires the optional 'trace' "
            "dependency (pyarrow); no artifact directory was created"
        ) from error
    return pyarrow, parquet


def _write_parquet_table(
    projected: _ProjectedTable,
    path: Path,
    *,
    pyarrow: ModuleType,
    parquet: ModuleType,
) -> None:
    type_factories = {
        "int64": pyarrow.int64,
        "float64": pyarrow.float64,
        "string": pyarrow.string,
        "bool": pyarrow.bool_,
        "list_string": lambda: pyarrow.list_(pyarrow.string()),
    }
    columns = PARQUET_SCHEMAS[projected.name]
    schema = pyarrow.schema(
        [
            pyarrow.field(
                column.name,
                type_factories[column.type_name](),
                nullable=column.nullable,
            )
            for column in columns
        ],
        metadata={
            b"moonkvsim.output_contract": SECTION_16_SCHEMA_VERSION.encode(),
            b"moonkvsim.artifact": projected.name.encode(),
            b"moonkvsim.truth_source": b"canonical-projection-only",
        },
    )
    table = pyarrow.Table.from_pylist(list(projected.rows()), schema=schema)
    parquet.write_table(
        table,
        path,
        compression="NONE",
        use_dictionary=False,
        write_statistics=False,
        data_page_version="2.0",
        version="2.6",
        store_schema=True,
    )


def _atomic_rename_no_replace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as error:
        raise RuntimeError(
            "atomic no-clobber section-16 publication requires Linux renameat2"
        ) from error
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(
            error_number,
            "refusing to overwrite an existing section-16 artifact directory",
            destination,
        )
    unsupported = {errno.EINVAL, errno.ENOSYS}
    if hasattr(errno, "EOPNOTSUPP"):
        unsupported.add(errno.EOPNOTSUPP)
    if error_number in unsupported:
        _link_directory_no_replace(source, destination)
        return
    raise OSError(error_number, os.strerror(error_number), destination)


def _link_directory_no_replace(source: Path, destination: Path) -> None:
    """No-clobber fallback for filesystems lacking ``RENAME_NOREPLACE``.

    The destination directory itself is exclusively reserved first, and every
    regular artifact is then hard-linked from the same-filesystem staging
    directory.  A failed publication is rolled back; an existing destination
    is never modified.
    """

    destination.mkdir()
    try:
        for source_path in sorted(source.iterdir(), key=lambda item: item.name):
            if not source_path.is_file() or source_path.is_symlink():
                raise RuntimeError("section-16 staging contains a non-regular artifact")
            os.link(source_path, destination / source_path.name)
    except Exception:
        shutil.rmtree(destination)
        raise
    shutil.rmtree(source)


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)


def _context_bucket(total_tokens: int) -> int:
    for upper in CONTEXT_BUCKET_UPPER_BOUNDS:
        if total_tokens <= upper:
            return upper
    raise OutputContractError("total context tokens exceed the strict 131072-token guard")


def _present_ints(rows: Sequence[Mapping[str, Any]], key: str) -> list[int]:
    result: list[int] = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        if type(value) is not int:
            raise OutputContractError(f"{key} must be an integer or null")
        result.append(value)
    return result


def _mapping_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise OutputContractError(f"{key} must be a non-empty string")
    return value


def _mapping_optional_string(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and (not isinstance(value, str) or not value):
        raise OutputContractError(f"{key} must be a non-empty string or null")
    return value


def _mapping_int(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if type(value) is not int:
        raise OutputContractError(f"{key} must be an integer")
    return value


def _mapping_optional_int(data: Mapping[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is not None and type(value) is not int:
        raise OutputContractError(f"{key} must be an integer or null")
    return value


def _mapping_bool(data: Mapping[str, Any], key: str) -> bool:
    value = data.get(key)
    if type(value) is not bool:
        raise OutputContractError(f"{key} must be a bool")
    return value


def _require_nonempty_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise OutputContractError(f"{name} must be a non-empty string")


def _require_nonnegative_int(name: str, value: object) -> None:
    if type(value) is not int or value < 0:
        raise OutputContractError(f"{name} must be a non-negative integer")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _canonical_json_text(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise OutputContractError("projection value is not canonical JSON") from error


def _canonical_json_bytes(value: object) -> bytes:
    return (_canonical_json_text(value) + "\n").encode()
