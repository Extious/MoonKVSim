"""Deterministic E2 replay of normalized multi-agent traces on the vanilla baseline.

The runner is deliberately dependency injected: callers construct the source-
aligned schedulers, HBM ledger observers, Store/Master/TransferRuntime graph,
and one explicit :class:`~moonkvsim.predictor.protocols.ForwardPredictor`.
Every component shares the coordinator's ``GlobalDES`` clock.  No recorded API
wall time is used as a simulation delay and no missing predictor value is
invented.

This module is E2 trace-shape evidence only.  A successful replay establishes
deterministic state-machine composition and byte conservation, not calibrated
timing, physical parity, end-to-end validation, or paper-ready results.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Any, Final

from moonkvsim.baseline.runtime import (
    BaselineCoordinator,
    BaselineCoordinatorError,
    BaselineReplicaRuntime,
    ForwardBatchTerminal,
    TaskResourcePlanProvider,
)
from moonkvsim.common.hash import sha256_json
from moonkvsim.common.types import KVIdentity
from moonkvsim.integration.vllm.hbm_block_ledger import HbmBlockLedgerBridge
from moonkvsim.integration.vllm.request import Request, RequestStatus
from moonkvsim.integration.vllm.scheduler import (
    ScheduledRequest,
    SchedulerOutput,
    SchedulingPhase,
)
from moonkvsim.output.capacity import CapacitySummary, derive_capacity_artifacts
from moonkvsim.output.records import (
    FlowRateEventRow,
    ResourceLedgerDeltaRow,
    build_flow_rate_event_rows,
    extract_resource_ledger_delta_rows,
)
from moonkvsim.output.section16 import (
    SECTION_16_ARTIFACTS,
    Section16Projection,
    TraceExecutionProjection,
    build_section_16_projection,
)
from moonkvsim.predictor.protocols import ForwardPredictor
from moonkvsim.predictor.schema import (
    AssumedIntegerMixedPhaseCompositionRule,
    CalibrationEvidenceLabel,
)
from moonkvsim.predictor.vllm_adapter import VLLMSchedulerBatchAdapter
from moonkvsim.recovery.baseline import AttemptStatus, SilentReplayStatus
from moonkvsim.simulation.allocation_registry import replay_allocation_registry
from moonkvsim.simulation.audit import CapacityAudit, generate_capacity_audit
from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import FREE_ACCOUNT, CapacityLedger
from moonkvsim.store.transfer_engine import TransferStatus, TransferTask
from moonkvsim.store.transfer_resources import (
    transfer_flow_queue_wait_ns_by_flow,
    transfer_resource_calendar_replay_byte_identical,
)
from moonkvsim.store.transfer_runtime import transfer_flow_replay_byte_identical
from moonkvsim.workload import (
    CausalReleaseEngine,
    CausalTrace,
    NormalizedSpanMetadata,
    SpanRuntimeStatus,
    normalized_span_metadata_from_record,
)

EVIDENCE_BOUNDARY: Final = "E2_real_trace_shape_vanilla_baseline_uncalibrated"
MAX_MODEL_LEN_TOKENS: Final = 131_072
SOURCE_BLOCK_SIZE_TOKENS: Final = 64
STORE_PAYLOAD_BYTE_BASIS: Final = (
    "stage_rank_payload_bytes_including_auxiliary_excluding_allocator_overhead"
)
_CONTEXT_BUCKETS: Final[tuple[int, ...]] = (8_192, 32_768, 65_536, 98_304, 131_072)


class TraceRunnerError(RuntimeError):
    """The runner cannot preserve the declared input or a runtime invariant."""


class TraceSelectionError(TraceRunnerError):
    """A smoke selection would be ambiguous or causally incomplete."""


class TraceRunStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


class TraceSpanExecutionStatus(StrEnum):
    PENDING = "PENDING"
    REMOTE_PREFIX = "REMOTE_PREFIX"
    INFERENCE_READY = "INFERENCE_READY"
    FORWARD = "FORWARD"
    STORE_SAVE = "STORE_SAVE"
    COMPLETED = "COMPLETED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class TraceSelection:
    """Whole-workflow deterministic selection for smoke or full replay."""

    workflow_ids: tuple[str, ...] | None = None
    max_spans: int | None = None

    def __post_init__(self) -> None:
        if self.workflow_ids is not None:
            if not self.workflow_ids or any(not item for item in self.workflow_ids):
                raise ValueError("workflow_ids must be absent or contain non-empty IDs")
            if tuple(sorted(set(self.workflow_ids))) != self.workflow_ids:
                raise ValueError("workflow_ids must be sorted and unique")
        if self.max_spans is not None and (type(self.max_spans) is not int or self.max_spans <= 0):
            raise ValueError("max_spans must be a positive integer")


@dataclass(frozen=True, slots=True)
class TraceSpanInput:
    """Compact causal metadata plus source-owned hash-block identifiers."""

    metadata: NormalizedSpanMetadata
    source_hash_ids: tuple[int, ...]
    source_hash_ids_sha256: str

    def __post_init__(self) -> None:
        if not self.source_hash_ids or any(
            type(item) is not int or item < 0 for item in self.source_hash_ids
        ):
            raise ValueError("source_hash_ids must contain non-negative integer blocks")
        digest = hashlib.sha256(
            json.dumps(
                list(self.source_hash_ids),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if digest != self.source_hash_ids_sha256:
            raise ValueError("source_hash_ids_sha256 does not match source_hash_ids")
        if self.metadata.prompt_tokens != len(self.source_hash_ids) * SOURCE_BLOCK_SIZE_TOKENS:
            raise ValueError("prompt_tokens do not match the source hash-block count")
        if self.metadata.source_hash_id_scope_raw != "local":
            raise ValueError("only the locked raw local hash-ID scope is accepted")
        if self.metadata.hash_id_scope != "within_workflow_only":
            raise ValueError("source hash IDs must be scoped within one workflow")
        if self.metadata.token_count_mode != "source_hash_blocks_64":
            raise ValueError("trace runner requires source_hash_blocks_64 token counts")
        if self.metadata.prompt_tokens + self.metadata.output_tokens > MAX_MODEL_LEN_TOKENS:
            raise ValueError("131072 guard failed; truncation and padding are forbidden")

    @property
    def span_id(self) -> str:
        return self.metadata.span_id

    @property
    def workflow_id(self) -> str:
        return self.metadata.workflow_id


@dataclass(frozen=True, slots=True)
class TraceRunInput:
    spans: tuple[TraceSpanInput, ...]
    source_path: str
    source_sha256: str
    total_valid_span_count: int
    selected_workflow_ids: tuple[str, ...]
    selection: TraceSelection

    def __post_init__(self) -> None:
        if not self.spans:
            raise ValueError("trace run input must contain at least one selected span")
        if len({item.span_id for item in self.spans}) != len(self.spans):
            raise ValueError("trace run input span IDs must be unique")
        if tuple(sorted(set(self.selected_workflow_ids))) != self.selected_workflow_ids:
            raise ValueError("selected_workflow_ids must be sorted and unique")
        if {item.workflow_id for item in self.spans} != set(self.selected_workflow_ids):
            raise ValueError("selected workflow IDs disagree with selected spans")
        _validate_normalized_parent_prefix_metric(self.spans)
        CausalTrace(tuple(item.metadata for item in self.spans))

    @property
    def trace(self) -> CausalTrace:
        return CausalTrace(tuple(item.metadata for item in self.spans))

    @property
    def by_span_id(self) -> dict[str, TraceSpanInput]:
        return {item.span_id: item for item in self.spans}


@dataclass(frozen=True, slots=True)
class TraceReplicaBinding:
    runtime: BaselineReplicaRuntime
    hbm_bridge: HbmBlockLedgerBridge

    def __post_init__(self) -> None:
        if self.runtime.scheduler.block_lifecycle_observer is not self.hbm_bridge:
            raise ValueError("replica scheduler must use its declared HBM ledger bridge")


@dataclass(frozen=True, slots=True)
class TraceRunnerConfig:
    tenant_id: str
    target_model_id: str
    target_model_revision: str
    kv_dtype: str
    kv_abi: str
    kv_layout: str
    tensor_parallel_size: int
    pipeline_parallel_size: int
    store_payload_bytes_per_source_block: int
    store_payload_byte_basis: str
    preferred_store_segment_ids: tuple[str, ...]
    max_model_len_tokens: int = MAX_MODEL_LEN_TOKENS

    def __post_init__(self) -> None:
        strings = (
            self.tenant_id,
            self.target_model_id,
            self.target_model_revision,
            self.kv_dtype,
            self.kv_abi,
            self.kv_layout,
        )
        if any(not item for item in strings):
            raise ValueError("trace runner target identity fields must be non-empty")
        if self.tensor_parallel_size != 1 or self.pipeline_parallel_size != 1:
            raise ValueError(
                "trace runner currently supports only TP=1 and PP=1; multi-shard "
                "Store identities are not implemented"
            )
        if self.store_payload_bytes_per_source_block <= 0:
            raise ValueError("Store payload bytes per source block must be positive")
        if self.store_payload_byte_basis != STORE_PAYLOAD_BYTE_BASIS:
            raise ValueError(
                "Store payload byte basis must explicitly select the frozen "
                "stage/rank payload contract"
            )
        if not self.preferred_store_segment_ids or any(
            not item for item in self.preferred_store_segment_ids
        ):
            raise ValueError("at least one preferred Store segment is required")
        if len(set(self.preferred_store_segment_ids)) != len(self.preferred_store_segment_ids):
            raise ValueError("preferred Store segment IDs must be unique")
        if self.max_model_len_tokens != MAX_MODEL_LEN_TOKENS:
            raise ValueError("this runner freezes the strict 131072 context guard")


@dataclass(frozen=True, slots=True)
class TraceFailureSpec:
    failure_id: str
    gpu_id: str
    at_ns: int
    detection_delay_ns: int = 0

    def __post_init__(self) -> None:
        if not self.failure_id or not self.gpu_id:
            raise ValueError("failure and GPU IDs must be non-empty")
        if type(self.at_ns) is not int or self.at_ns < 0:
            raise ValueError("failure at_ns must be non-negative")
        if type(self.detection_delay_ns) is not int or self.detection_delay_ns < 0:
            raise ValueError("failure detection delay must be non-negative")


@dataclass(frozen=True, slots=True)
class TraceRunnerGap:
    code: str
    message: str
    span_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "span_ids": list(self.span_ids),
        }


@dataclass(slots=True)
class _SpanExecution:
    trace_span: TraceSpanInput
    request_id: str
    request: Request | None = None
    required_blocks: tuple[KVIdentity, ...] = ()
    target_replica_id: str | None = None
    route_version: int | None = None
    restored_tokens: int = 0
    observed_committed_store_prefix_tokens: int = 0
    pending_get_transfer_ids: set[str] | None = None
    pending_put_transfer_ids: set[str] | None = None
    forward_handle: EventHandle | None = None
    scheduler_step_count: int = 0
    forward_duration_ns: int = 0
    status: TraceSpanExecutionStatus = TraceSpanExecutionStatus.PENDING
    completed_ns: int | None = None


@dataclass(frozen=True, slots=True)
class _ForwardParticipant:
    request_id: str
    scheduled: ScheduledRequest
    produces_output: bool
    output_index: int | None

    def __post_init__(self) -> None:
        if self.request_id != self.scheduled.request_id:
            raise ValueError("forward participant disagrees with its scheduled request")
        if self.produces_output != (self.output_index is not None):
            raise ValueError("forward participant output decision is inconsistent")


@dataclass(frozen=True, slots=True)
class _ComputeLease:
    lease_id: str
    replica_id: str
    handle: EventHandle
    participants: tuple[_ForwardParticipant, ...]
    acquired_ns: int
    release_ns: int

    def __post_init__(self) -> None:
        if not self.lease_id or not self.replica_id or not self.participants:
            raise ValueError("compute lease identity must be complete")
        if self.release_ns <= self.acquired_ns:
            raise ValueError("compute lease must own a positive virtual interval")


@dataclass(frozen=True, slots=True)
class TraceRunResult:
    """Completed E2 result plus the complete canonical section-16 projection."""

    status: TraceRunStatus
    run_input: TraceRunInput
    journal: Any
    gaps: tuple[TraceRunnerGap, ...]
    executions: tuple[_SpanExecution, ...]
    initial_ledgers: Mapping[str, CapacityLedger]
    final_ledgers: Mapping[str, CapacityLedger]
    capacity_audit: CapacityAudit
    resource_rows: tuple[ResourceLedgerDeltaRow, ...]
    flow_rows: tuple[FlowRateEventRow, ...]
    capacity_summary: CapacitySummary | None
    allocation_registry_replay_byte_identical: bool
    transfer_resource_calendar_replay_byte_identical: bool
    flow_rate_state_replay_byte_identical: bool
    predictor_profile_fingerprint: str
    predictor_provider_name: str
    store_payload_bytes_per_source_block: int
    store_payload_byte_basis: str
    virtual_end_ns: int
    mixed_phase_composition_rule: AssumedIntegerMixedPhaseCompositionRule | None
    mixed_phase_composition_count: int
    semantic_source_provenance: Mapping[str, object] | None = None
    failure_protocol_provenance: Mapping[str, object] | None = None
    transfer_resource_protocol_provenance: Mapping[str, object] | None = None

    @property
    def present_section_16_artifacts(self) -> tuple[str, ...]:
        return tuple(sorted(SECTION_16_ARTIFACTS))

    @property
    def missing_section_16_artifacts(self) -> tuple[str, ...]:
        return ()

    def trace_audit_document(self) -> dict[str, object]:
        executions_by_span_id = {
            execution.trace_span.span_id: execution for execution in self.executions
        }
        return {
            "schema": "moonkvsim.trace-runner-trace-audit.v1",
            "status": self.status.value,
            "evidence_boundary": EVIDENCE_BOUNDARY,
            "source_path": self.run_input.source_path,
            "source_sha256": self.run_input.source_sha256,
            "total_valid_span_count": self.run_input.total_valid_span_count,
            "selected_span_count": len(self.run_input.spans),
            "selected_workflow_ids": list(self.run_input.selected_workflow_ids),
            "selection": {
                "workflow_ids": (
                    None
                    if self.run_input.selection.workflow_ids is None
                    else list(self.run_input.selection.workflow_ids)
                ),
                "max_spans": self.run_input.selection.max_spans,
                "whole_workflow_closure": True,
            },
            "guard": {
                "expression": "prompt_tokens + output_tokens <= 131072",
                "truncated_count": 0,
                "padded_count": 0,
            },
            "source_hash_scope": {
                "raw": "local",
                "normalized": "within_workflow_only",
                "cross_workflow_reuse": False,
                "source_block_size_tokens": SOURCE_BLOCK_SIZE_TOKENS,
            },
            "store_payload_contract": {
                "bytes_per_source_block": self.store_payload_bytes_per_source_block,
                "byte_basis": self.store_payload_byte_basis,
                "includes_auxiliary_payload": True,
                "excludes_hbm_layout_padding": True,
                "excludes_hbm_allocator_metadata": True,
                "excludes_hbm_internal_fragmentation": True,
            },
            "spans": [
                {
                    "span_id": item.span_id,
                    "workflow_id": item.workflow_id,
                    "source_hash_ids_sha256": item.source_hash_ids_sha256,
                    "source_hash_block_count": len(item.source_hash_ids),
                    "prompt_tokens": item.metadata.prompt_tokens,
                    "output_tokens": item.metadata.output_tokens,
                    "cached_prefix_tokens": item.metadata.cached_prefix_tokens,
                    "normalized_parent_prefix_tokens": (item.metadata.cached_prefix_tokens),
                    "visible_committed_store_prefix_tokens": (
                        executions_by_span_id[item.span_id].observed_committed_store_prefix_tokens
                    ),
                    "store_lookup_mode": ("full_hash_vector_from_block_zero_first_miss"),
                }
                for item in self.run_input.spans
            ],
        }

    def context_coverage_document(self) -> dict[str, object]:
        bucket_workflows: dict[int, set[str]] = defaultdict(set)
        bucket_counts: dict[int, int] = defaultdict(int)
        for item in self.run_input.spans:
            total = item.metadata.prompt_tokens + item.metadata.output_tokens
            bound = next(bound for bound in _CONTEXT_BUCKETS if total <= bound)
            bucket_counts[bound] += 1
            bucket_workflows[bound].add(item.workflow_id)
        lower = 0
        buckets: list[dict[str, object]] = []
        for bound in _CONTEXT_BUCKETS:
            buckets.append(
                {
                    "lower_exclusive": lower,
                    "upper_inclusive": bound,
                    "request_count": bucket_counts[bound],
                    "workflow_count": len(bucket_workflows[bound]),
                }
            )
            lower = bound
        return {
            "schema": "moonkvsim.trace-runner-context-coverage.v1",
            "evidence_boundary": EVIDENCE_BOUNDARY,
            "context_buckets": buckets,
            "max_total_model_tokens": max(
                item.metadata.prompt_tokens + item.metadata.output_tokens
                for item in self.run_input.spans
            ),
            "truncated_count": 0,
            "padded_count": 0,
        }

    def run_audit_document(self) -> dict[str, object]:
        ledger_replay_byte_identical = (
            self.capacity_audit.valid and self.capacity_audit.final_snapshot_byte_identical
        )
        document: dict[str, object] = {
            "schema": "moonkvsim.trace-run-audit.v1",
            "status": self.status.value,
            "evidence_boundary": EVIDENCE_BOUNDARY,
            "formal_use_allowed": False,
            "predictor": {
                "provider_name": self.predictor_provider_name,
                "profile_fingerprint": self.predictor_profile_fingerprint,
                "calibration_label": "preliminary",
                "calibration_status": "not_calibrated",
                "database_sha256": None,
                "mixed_phase_composition": (
                    None
                    if self.mixed_phase_composition_rule is None
                    else {
                        "configured": True,
                        "used_step_count": self.mixed_phase_composition_count,
                        "rule": self.mixed_phase_composition_rule.to_dict(),
                    }
                ),
            },
            "capacity_audit": self.capacity_audit.to_dict(),
            "ledger_replay_byte_identical": ledger_replay_byte_identical,
            "allocation_registry_replay_byte_identical": (
                self.allocation_registry_replay_byte_identical
            ),
            "transfer_resource_calendar_replay_byte_identical": (
                self.transfer_resource_calendar_replay_byte_identical
            ),
            "flow_rate_state_replay_byte_identical": (
                self.flow_rate_state_replay_byte_identical
            ),
            "journal_replay_byte_identical": (
                ledger_replay_byte_identical
                and self.allocation_registry_replay_byte_identical
                and self.transfer_resource_calendar_replay_byte_identical
                and self.flow_rate_state_replay_byte_identical
            ),
            "gaps": [item.to_dict() for item in self.gaps],
            "semantic_source_provenance": (
                {
                    "available": False,
                    "unchanged_during_run": None,
                    "reason": "runner_invoked_without_e2_harness_snapshot",
                }
                if self.semantic_source_provenance is None
                else dict(self.semantic_source_provenance)
            ),
            "section_16": {
                "present_artifacts": list(self.present_section_16_artifacts),
                "missing_artifacts": list(self.missing_section_16_artifacts),
                "complete": not self.missing_section_16_artifacts,
            },
        }
        if self.failure_protocol_provenance is not None:
            document["failure_protocol"] = dict(self.failure_protocol_provenance)
        if self.transfer_resource_protocol_provenance is not None:
            document["transfer_resource_protocol"] = dict(
                self.transfer_resource_protocol_provenance
            )
        return document

    def summary_document(self) -> dict[str, object]:
        completed = [
            item for item in self.executions if item.status is TraceSpanExecutionStatus.COMPLETED
        ]
        unavailable = [
            item for item in self.executions if item.status is TraceSpanExecutionStatus.UNAVAILABLE
        ]
        return {
            "schema": "moonkvsim.trace-run-summary.v1",
            "status": self.status.value,
            "evidence_boundary": EVIDENCE_BOUNDARY,
            "span_count": len(self.executions),
            "completed_span_count": len(completed),
            "unavailable_span_count": len(unavailable),
            "workflow_count": len(self.run_input.selected_workflow_ids),
            "virtual_end_ns": self.virtual_end_ns,
            "restored_prefix_tokens": sum(item.restored_tokens for item in completed),
            "normalized_parent_prefix_tokens": sum(
                item.trace_span.metadata.cached_prefix_tokens for item in self.executions
            ),
            "visible_committed_store_prefix_tokens": sum(
                item.observed_committed_store_prefix_tokens for item in self.executions
            ),
            "store_lookup_mode": "full_hash_vector_from_block_zero_first_miss",
            "scheduler_step_count": sum(item.scheduler_step_count for item in completed),
            "predicted_forward_ns": sum(item.forward_duration_ns for item in completed),
            "predictor_calibration_status": "not_calibrated",
            "mixed_phase_composition_count": self.mixed_phase_composition_count,
            "gap_codes": [item.code for item in self.gaps],
            "gaps": [item.to_dict() for item in self.gaps],
            "capacity_summary": (
                None if self.capacity_summary is None else self.capacity_summary.to_dict()
            ),
            "section_16_missing_artifacts": list(self.missing_section_16_artifacts),
            "spans": [
                {
                    "span_id": item.trace_span.span_id,
                    "workflow_id": item.trace_span.workflow_id,
                    "request_id": item.request_id,
                    "status": item.status.value,
                    "target_replica_id": item.target_replica_id,
                    "route_version": item.route_version,
                    "restored_tokens": item.restored_tokens,
                    "normalized_parent_prefix_tokens": (
                        item.trace_span.metadata.cached_prefix_tokens
                    ),
                    "visible_committed_store_prefix_tokens": (
                        item.observed_committed_store_prefix_tokens
                    ),
                    "scheduler_step_count": item.scheduler_step_count,
                    "predicted_forward_ns": item.forward_duration_ns,
                    "completed_ns": item.completed_ns,
                }
                for item in self.executions
            ],
        }

    def trace_execution_projections(self) -> tuple[TraceExecutionProjection, ...]:
        """Project only trace/runtime state required by fixed section-16 schemas."""

        return tuple(
            TraceExecutionProjection(
                workflow_id=execution.trace_span.metadata.workflow_id,
                session_id=execution.trace_span.metadata.session_id,
                agent_id=execution.trace_span.metadata.agent_id,
                agent_role=execution.trace_span.metadata.agent_role,
                span_id=execution.trace_span.span_id,
                request_id=execution.request_id,
                status=execution.status.value,
                prompt_tokens=execution.trace_span.metadata.prompt_tokens,
                cached_prefix_tokens=(execution.trace_span.metadata.cached_prefix_tokens),
                output_tokens=execution.trace_span.metadata.output_tokens,
                restored_tokens=execution.restored_tokens,
                scheduler_step_count=execution.scheduler_step_count,
                predicted_forward_ns=execution.forward_duration_ns,
                parent_span_ids=execution.trace_span.metadata.parent_span_ids,
                target_replica_id=execution.target_replica_id,
                route_version=execution.route_version,
                completed_ns=execution.completed_ns,
                recomputed_tokens=(
                    execution.trace_span.metadata.prompt_tokens - execution.restored_tokens
                ),
                source_evidence_class=execution.trace_span.metadata.evidence_class,
                source_hash_ids_sha256=(execution.trace_span.source_hash_ids_sha256),
                truncated=False,
                padded=False,
            )
            for execution in self.executions
        )

    def section_16_projection(self) -> Section16Projection:
        return build_section_16_projection(
            journal=self.journal,
            resource_rows=self.resource_rows,
            flow_rows=self.flow_rows,
            executions=self.trace_execution_projections(),
            runner_documents={
                "trace-audit.json": self.trace_audit_document(),
                "context-coverage.json": self.context_coverage_document(),
                "capacity-audit.json": self.capacity_audit.to_dict(),
                "run-audit.json": self.run_audit_document(),
                "summary.json": self.summary_document(),
            },
        )

    def write_section_16_artifacts(self, directory: Path) -> None:
        """Atomically publish the exact 19-artifact section-16 contract."""

        self.section_16_projection().write(Path(directory))


def load_trace_run_input(
    path: Path,
    *,
    selection: TraceSelection | None = None,
) -> TraceRunInput:
    """Stream, validate, compact, and whole-workflow-select normalized JSONL.

    An explicit ``workflow_ids`` selection is the real-trace smoke path.  The
    loader still parses and validates every source row and hashes every byte,
    but it retains the large source-hash arrays only for selected workflows.
    This keeps provenance and fail-closed validation identical without making
    a one-workflow replay resident-size proportional to the full corpus.
    """

    source = Path(path)
    resolved_selection = selection or TraceSelection()
    explicit_workflow_ids = (
        None if resolved_selection.workflow_ids is None else set(resolved_selection.workflow_ids)
    )
    digest = hashlib.sha256()
    materialized_spans: list[TraceSpanInput] = []
    observed_selected_workflows: set[str] = set()
    total_valid_span_count = 0
    try:
        with source.open("rb") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                digest.update(raw_line)
                if not raw_line.strip():
                    raise TraceSelectionError(
                        f"line {line_number}: blank normalized trace lines are forbidden"
                    )
                try:
                    record = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise TraceSelectionError(
                        f"line {line_number}: invalid normalized JSON: {error}"
                    ) from error
                if not isinstance(record, dict):
                    raise TraceSelectionError(
                        f"line {line_number}: normalized span must be an object"
                    )
                try:
                    metadata = normalized_span_metadata_from_record(record)
                    raw_hash_ids = record.get("source_hash_ids")
                    if not isinstance(raw_hash_ids, list):
                        raise ValueError("source_hash_ids must be an array")
                    source_hash_ids = tuple(
                        _strict_non_negative_int(item, "source_hash_ids entry")
                        for item in raw_hash_ids
                    )
                    hash_digest = record.get("source_hash_ids_sha256")
                    if not isinstance(hash_digest, str):
                        raise ValueError("source_hash_ids_sha256 must be a string")
                    span = TraceSpanInput(metadata, source_hash_ids, hash_digest)
                except (TypeError, ValueError) as error:
                    raise TraceSelectionError(f"line {line_number}: {error}") from error
                total_valid_span_count += 1
                if explicit_workflow_ids is None or span.workflow_id in explicit_workflow_ids:
                    materialized_spans.append(span)
                    observed_selected_workflows.add(span.workflow_id)
    except OSError as error:
        raise TraceSelectionError(f"cannot read normalized trace {source}: {error}") from error
    if total_valid_span_count == 0:
        raise TraceSelectionError("normalized trace contains no spans")

    if explicit_workflow_ids is not None:
        unknown = explicit_workflow_ids - observed_selected_workflows
        if unknown:
            raise TraceSelectionError(f"workflow filter contains unknown IDs: {sorted(unknown)}")
        if (
            resolved_selection.max_spans is not None
            and len(materialized_spans) > resolved_selection.max_spans
        ):
            raise TraceSelectionError(
                "workflow filter plus max_spans would cut a workflow DAG; no partial "
                "workflow selection is allowed"
            )
        selected = tuple(materialized_spans)
    else:
        selected = _select_whole_workflows(materialized_spans, resolved_selection)
    ordered = tuple(sorted(selected, key=lambda item: item.metadata.stable_sort_key))
    selected_workflows = tuple(sorted({item.workflow_id for item in ordered}))
    return TraceRunInput(
        spans=ordered,
        source_path=str(source),
        source_sha256=digest.hexdigest(),
        total_valid_span_count=total_valid_span_count,
        selected_workflow_ids=selected_workflows,
        selection=resolved_selection,
    )


class VanillaBaselineTraceRunner:
    """Compose one normalized trace with independent DP baseline runtimes."""

    def __init__(
        self,
        *,
        coordinator: BaselineCoordinator,
        replicas: Mapping[str, TraceReplicaBinding],
        predictor: ForwardPredictor,
        config: TraceRunnerConfig,
        mixed_phase_composition_rule: (AssumedIntegerMixedPhaseCompositionRule | None) = None,
        transfer_resource_plan_provider: TaskResourcePlanProvider | None = None,
    ) -> None:
        replica_map = dict(replicas)
        if not replica_map or any(
            key != item.runtime.replica_id for key, item in replica_map.items()
        ):
            raise ValueError("replica binding keys must match unique runtime replica IDs")
        if len({item.runtime.dp_rank for item in replica_map.values()}) != len(replica_map):
            raise ValueError("trace runner DP ranks must be unique")
        if coordinator.des is not coordinator.transfer_runtime.des:
            raise ValueError("coordinator and TransferRuntime must share one GlobalDES")
        if not coordinator.hbm_fail_stop_integrated:
            raise ValueError(
                "trace runner requires the complete shared-registry HBM fail-stop topology"
            )
        layout_signature: tuple[tuple[int, int, str], ...] | None = None
        expected_store_payload_bytes: int | None = None
        for item in replica_map.values():
            if item.hbm_bridge.journal is not coordinator.des.journal:
                raise ValueError("HBM bridge and baseline components must share one journal")
            if item.hbm_bridge.registry is not coordinator.master.allocation_registry:
                raise ValueError("Store and every trace HBM bridge must share one registry")
            if SOURCE_BLOCK_SIZE_TOKENS % item.runtime.scheduler.block_size_tokens:
                raise ValueError("source hash blocks must align to scheduler KV blocks")
            signature = tuple(
                (
                    binding.layout.pp_stage,
                    binding.layout.tensor_parallel_rank,
                    binding.layout.fingerprint,
                )
                for binding in item.hbm_bridge.bindings
            )
            if tuple((stage, rank) for stage, rank, _ in signature) != ((0, 0),):
                raise ValueError("TP=1/PP=1 trace replay requires exactly the pp0/tp0 HBM layout")
            if layout_signature is None:
                layout_signature = signature
            elif signature != layout_signature:
                raise ValueError("all DP replicas must use byte-identical HBM block layouts")
            [binding] = item.hbm_bridge.bindings
            source_to_scheduler_ratio = (
                SOURCE_BLOCK_SIZE_TOKENS // item.runtime.scheduler.block_size_tokens
            )
            replica_store_payload_bytes = binding.layout.payload_bytes * source_to_scheduler_ratio
            if expected_store_payload_bytes is None:
                expected_store_payload_bytes = replica_store_payload_bytes
            elif replica_store_payload_bytes != expected_store_payload_bytes:
                raise ValueError("all DP replicas disagree on Store payload bytes")
        if expected_store_payload_bytes is None:
            raise ValueError("trace runner has no resolved HBM payload layout")
        if config.store_payload_bytes_per_source_block != expected_store_payload_bytes:
            raise ValueError(
                "Store payload bytes must equal HBM StageBlockLayout.payload_bytes times "
                "the source-to-scheduler block ratio"
            )
        profile = predictor.profile
        if (
            profile.model_id,
            profile.model_revision,
            profile.tensor_parallel_size,
            profile.pipeline_parallel_size,
        ) != (
            config.target_model_id,
            config.target_model_revision,
            config.tensor_parallel_size,
            config.pipeline_parallel_size,
        ):
            raise ValueError("trace target configuration does not match predictor profile")
        if (
            predictor.evidence.label is not CalibrationEvidenceLabel.PRELIMINARY
            or predictor.evidence.formal_use_allowed
        ):
            raise ValueError("the E2 trace runner requires preliminary non-formal evidence")

        self.coordinator = coordinator
        self.des = coordinator.des
        self.replicas = replica_map
        self.predictor = predictor
        self.config = config
        self.mixed_phase_composition_rule = mixed_phase_composition_rule
        self.transfer_resource_plan_provider = transfer_resource_plan_provider
        if (
            transfer_resource_plan_provider is not None
            and coordinator.transfer_resource_manager is None
        ):
            raise ValueError(
                "trace transfer plan provider requires the coordinator resource manager"
            )
        self.adapter = VLLMSchedulerBatchAdapter()
        self._store_payload_bytes = expected_store_payload_bytes
        self._all_ledgers = _collect_ledgers(coordinator, replica_map)
        allocation_ledgers = coordinator.allocation_ledgers
        for resource_id, ledger in allocation_ledgers.items():
            if self._all_ledgers.get(resource_id) is not ledger:
                raise ValueError(
                    "trace runner ledger graph differs from coordinator failure accounting"
                )
        self._initial_ledgers = {
            resource_id: _clone_ledger(ledger) for resource_id, ledger in self._all_ledgers.items()
        }
        self._started = False
        self._run_input: TraceRunInput | None = None
        self._causal: CausalReleaseEngine | None = None
        self._execution_by_span: dict[str, _SpanExecution] = {}
        self._execution_by_request: dict[str, _SpanExecution] = {}
        self._ready_request_ids: set[str] = set()
        self._pending_step_replica_ids: set[str] = set()
        self._forward_by_replica: dict[str, _ComputeLease] = {}
        self._recovery_fetch_ready_request_ids: set[str] = set()
        self._recovery_replay_request_ids: set[str] = set()
        self._gaps: list[TraceRunnerGap] = []
        self._mixed_phase_composition_count = 0
        self._event_sequence = 0
        self.des.register_handler(
            EventKind.SCHEDULER_STEP_READY,
            self._on_scheduler_step_ready,
        )
        self.des.register_handler(EventKind.PUT_START, self._on_begin_store_save)
        self.des.register_handler(EventKind.RECOVERY_START, self._on_recovery_start)
        self.des.register_invariant(
            "baseline-trace-composed-capacity-rate-refcount",
            self._check_composed_invariant,
        )

    def run(
        self,
        run_input: TraceRunInput,
        *,
        failures: Sequence[TraceFailureSpec] = (),
    ) -> TraceRunResult:
        if self._started:
            raise TraceRunnerError("trace runner instances are single-use")
        if self.des.now_ns != 0 or self.des.pending_count:
            raise TraceRunnerError("trace replay must start from an idle zero GlobalDES clock")
        self._started = True
        self._run_input = run_input
        self._execution_by_span = {
            item.span_id: _SpanExecution(
                trace_span=item,
                request_id=f"trace-request:{item.span_id}",
            )
            for item in run_input.spans
        }
        self._execution_by_request = {
            item.request_id: item for item in self._execution_by_span.values()
        }
        causal = CausalReleaseEngine(
            run_input.trace,
            self.des,
            on_release=self._on_span_release,
        )
        self._causal = causal
        for failure in sorted(failures, key=lambda item: (item.at_ns, item.failure_id)):
            self.coordinator.schedule_gpu_failure(
                failure_id=failure.failure_id,
                gpu_id=failure.gpu_id,
                at_ns=failure.at_ns,
                detection_delay_ns=failure.detection_delay_ns,
            )
            self.des.schedule_at(
                failure.at_ns + failure.detection_delay_ns + 1,
                EventKind.RECOVERY_START,
                event_id=f"trace-runner:recovery:{failure.failure_id}",
                payload={
                    "failure_id": failure.failure_id,
                    "gpu_id": failure.gpu_id,
                },
            )
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_STARTED",
            {
                "evidence_boundary": EVIDENCE_BOUNDARY,
                "span_count": len(run_input.spans),
                "workflow_ids": list(run_input.selected_workflow_ids),
                "predictor_profile_fingerprint": self.predictor.profile.fingerprint,
                "predictor_evidence": self.predictor.evidence.to_dict(),
                "mixed_phase_composition_rule": (
                    None
                    if self.mixed_phase_composition_rule is None
                    else self.mixed_phase_composition_rule.to_dict()
                ),
                "recorded_api_time_used_as_delay": False,
                "store_payload_contract": {
                    "bytes_per_source_block": self._store_payload_bytes,
                    "byte_basis": self.config.store_payload_byte_basis,
                },
            },
        )
        causal.start()
        self.des.run()

        for execution in self._execution_by_span.values():
            snapshot = causal.snapshot(execution.trace_span.span_id)
            if snapshot.status in {SpanRuntimeStatus.UNAVAILABLE, SpanRuntimeStatus.BLOCKED}:
                execution.status = TraceSpanExecutionStatus.UNAVAILABLE
        if self._forward_by_replica:
            raise TraceRunnerError("trace replay ended with an active GPU compute lease")
        self.coordinator.audit(require_quiescent=True)
        for binding in self.replicas.values():
            binding.hbm_bridge.audit()

        capacity_audit = generate_capacity_audit(
            initial_ledgers=self._initial_ledgers,
            journal=self.des.journal,
            online_final_ledgers=self._all_ledgers,
        )
        resource_rows = extract_resource_ledger_delta_rows(
            self.des.journal,
            self._all_ledgers,
        )
        flow_rows = build_flow_rate_event_rows(
            self.coordinator.transfer_runtime.controller.model.intervals,
            queue_wait_ns_by_flow=transfer_flow_queue_wait_ns_by_flow(
                self.des.journal
            ),
        )
        delta_audit, capacity_summary = derive_capacity_artifacts(
            self._initial_ledgers,
            resource_rows,
            expected_final_ledgers=self._all_ledgers,
        )
        if not capacity_audit.valid or not delta_audit.valid:
            raise TraceRunnerError("capacity journal replay/audit failed closed")
        replayed_registry = replay_allocation_registry(self.des.journal)
        registry_replay_byte_identical = (
            replayed_registry.snapshot_bytes()
            == self.coordinator.master.allocation_registry.snapshot_bytes()
        )
        if not registry_replay_byte_identical:
            raise TraceRunnerError("allocation registry journal replay is not byte-identical")
        transfer_resource_replay_byte_identical = (
            self._audit_transfer_resource_calendar_replay()
        )
        flow_rate_replay_byte_identical = transfer_flow_replay_byte_identical(
            self.des.journal,
            self.coordinator.transfer_runtime.controller.model,
        )
        if not flow_rate_replay_byte_identical:
            raise TraceRunnerError(
                "flow rate state/interval journal replay is not byte-identical"
            )
        completed = all(
            item.status is TraceSpanExecutionStatus.COMPLETED
            for item in self._execution_by_span.values()
        )
        status = TraceRunStatus.PASS if completed and not self._gaps else TraceRunStatus.BLOCKED
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_FINISHED",
            {
                "status": status.value,
                "completed_span_count": sum(
                    item.status is TraceSpanExecutionStatus.COMPLETED
                    for item in self._execution_by_span.values()
                ),
                "gap_codes": [item.code for item in self._gaps],
                "mixed_phase_composition_count": (self._mixed_phase_composition_count),
                "capacity_audit": capacity_audit.status,
                "transfer_resource_calendar_replay_byte_identical": (
                    transfer_resource_replay_byte_identical
                ),
                "flow_rate_state_replay_byte_identical": (
                    flow_rate_replay_byte_identical
                ),
                "evidence_boundary": EVIDENCE_BOUNDARY,
            },
        )
        # Re-audit after the terminal record because it is part of the artifact.
        capacity_audit = generate_capacity_audit(
            initial_ledgers=self._initial_ledgers,
            journal=self.des.journal,
            online_final_ledgers=self._all_ledgers,
        )
        return TraceRunResult(
            status=status,
            run_input=run_input,
            journal=self.des.journal,
            gaps=tuple(self._gaps),
            executions=tuple(self._execution_by_span[item.span_id] for item in run_input.spans),
            initial_ledgers=self._initial_ledgers,
            final_ledgers=self._all_ledgers,
            capacity_audit=capacity_audit,
            resource_rows=resource_rows,
            flow_rows=flow_rows,
            capacity_summary=capacity_summary,
            allocation_registry_replay_byte_identical=(registry_replay_byte_identical),
            transfer_resource_calendar_replay_byte_identical=(
                transfer_resource_replay_byte_identical
            ),
            flow_rate_state_replay_byte_identical=(
                flow_rate_replay_byte_identical
            ),
            predictor_profile_fingerprint=self.predictor.profile.fingerprint,
            predictor_provider_name=self.predictor.profile.provider_name,
            store_payload_bytes_per_source_block=self._store_payload_bytes,
            store_payload_byte_basis=self.config.store_payload_byte_basis,
            virtual_end_ns=self.des.now_ns,
            mixed_phase_composition_rule=self.mixed_phase_composition_rule,
            mixed_phase_composition_count=self._mixed_phase_composition_count,
        )

    def _audit_transfer_resource_calendar_replay(self) -> bool:
        """Replay every transfer lease into pristine calendars and compare online state."""

        manager = self.coordinator.transfer_resource_manager
        resource_records_present = any(
            record.record_type.startswith("TRANSFER_RESOURCE_LEASE_")
            for record in self.des.journal.records
        )
        if manager is None:
            if resource_records_present:
                raise TraceRunnerError(
                    "transfer-resource journal records exist without an online manager"
                )
            return True

        identical = transfer_resource_calendar_replay_byte_identical(
            self.des.journal,
            manager,
        )
        if not identical:
            raise TraceRunnerError(
                "transfer resource lease/calendar journal replay is not byte-identical"
            )
        return True

    def _check_composed_invariant(self, des: GlobalDES) -> None:
        if des is not self.des:
            raise TraceRunnerError("composed invariant ran on another GlobalDES")
        self.coordinator.transfer_runtime.audit()
        self.coordinator.master.allocation_registry.audit(self.coordinator.allocation_ledgers)
        manager = self.coordinator.transfer_resource_manager
        if manager is not None:
            manager.audit()
        endpoint_manager = self.coordinator.endpoint_registration_manager
        if endpoint_manager is not None:
            endpoint_manager.audit()
        for replica_id, binding in self.replicas.items():
            binding.runtime.scheduler.audit()
            binding.hbm_bridge.audit()
            lease = self._forward_by_replica.get(replica_id)
            if lease is None:
                continue
            if lease.replica_id != replica_id:
                raise TraceRunnerError("compute lease belongs to another replica")
            for participant in lease.participants:
                execution = self._execution_by_request.get(participant.request_id)
                if (
                    execution is None
                    or execution.status is not TraceSpanExecutionStatus.FORWARD
                    or execution.forward_handle is None
                    or execution.forward_handle.event_id != lease.handle.event_id
                ):
                    raise TraceRunnerError(
                        "compute capacity lease and forward participant diverged"
                    )

    def _on_span_release(
        self,
        metadata: NormalizedSpanMetadata,
        des: GlobalDES,
    ) -> None:
        if des is not self.des:
            raise TraceRunnerError("span released on another GlobalDES instance")
        execution = self._execution_by_span[metadata.span_id]
        if execution.status is not TraceSpanExecutionStatus.PENDING:
            raise TraceRunnerError("span released from a non-pending execution state")
        if metadata.output_tokens <= 0:
            self._block_execution(
                execution,
                code="TRC-BLOCK-OUTPUT-000",
                message=(
                    "the current vLLM Request contract requires a positive output reserve; "
                    "a recorded zero-output span is not padded or fabricated"
                ),
            )
            return
        request = Request(
            request_id=execution.request_id,
            prompt_tokens=metadata.prompt_tokens,
            max_output_tokens=metadata.output_tokens,
            arrival_ns=self.des.now_ns,
            max_model_len_tokens=self.config.max_model_len_tokens,
        )
        required = self._required_blocks(execution, source_gpu_id="unbound-before-route")
        authority = self.coordinator.route_and_admit(request, required_blocks=required)
        execution.request = request
        execution.required_blocks = required
        execution.target_replica_id = authority.target_replica_id
        execution.route_version = authority.route_version
        runtime = self.replicas[authority.target_replica_id].runtime
        current_blocks = tuple(
            replace(
                item,
                route_version=authority.route_version,
                source_gpu_id=runtime.gpu_id,
            )
            for item in required
        )
        visible_prefix: list[KVIdentity] = []
        queried_block_count = 0
        first_miss_block_index: int | None = None
        for block_index, identity in enumerate(current_blocks):
            queried_block_count += 1
            if not self.coordinator.query_store(
                replica_id=authority.target_replica_id,
                identity=identity,
            ):
                first_miss_block_index = block_index
                break
            visible_prefix.append(identity)
        execution.restored_tokens = len(visible_prefix) * SOURCE_BLOCK_SIZE_TOKENS
        execution.observed_committed_store_prefix_tokens = execution.restored_tokens
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_SPAN_ADMITTED",
            {
                "span_id": metadata.span_id,
                "workflow_id": metadata.workflow_id,
                "request_id": execution.request_id,
                "target_replica_id": authority.target_replica_id,
                "route_version": authority.route_version,
                "source_hash_ids": list(execution.trace_span.source_hash_ids),
                "source_hash_ids_sha256": execution.trace_span.source_hash_ids_sha256,
                "hash_id_scope": metadata.hash_id_scope,
                "declared_cached_prefix_tokens": metadata.cached_prefix_tokens,
                "normalized_parent_prefix_tokens": metadata.cached_prefix_tokens,
                "normalized_parent_prefix_role": (
                    "causal_parent_hash_overlap_metric_not_store_lookup_bound"
                ),
                "committed_prefix_lookup": {
                    "mode": "full_hash_vector_from_block_zero_first_miss",
                    "visibility": "committed_published_store_replicas_only",
                    "candidate_block_count": len(current_blocks),
                    "queried_block_count": queried_block_count,
                    "observed_committed_block_count": len(visible_prefix),
                    "first_miss_block_index": first_miss_block_index,
                    "normalized_parent_prefix_used_as_query_limit": False,
                },
                "visible_committed_prefix_tokens": execution.restored_tokens,
                "strict_total_model_tokens": metadata.prompt_tokens + metadata.output_tokens,
            },
        )
        if not visible_prefix:
            execution.status = TraceSpanExecutionStatus.INFERENCE_READY
            self._ready_request_ids.add(execution.request_id)
            self._request_scheduler_step(authority.target_replica_id)
            return

        execution.status = TraceSpanExecutionStatus.REMOTE_PREFIX
        execution.pending_get_transfer_ids = set()
        runtime.scheduler.mark_waiting_for_remote_kv(execution.request_id)
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_REMOTE_PREFIX_WAITING",
            {
                "span_id": execution.trace_span.span_id,
                "request_id": execution.request_id,
                "target_replica_id": authority.target_replica_id,
                "request_status": RequestStatus.WAITING_FOR_REMOTE_KVS.name,
            },
        )
        for block_index, identity in enumerate(visible_prefix):
            operation = self.coordinator.start_store_get(
                execution.request_id,
                identity,
                get_id=(
                    f"trace-get:{metadata.span_id}:route-{authority.route_version}:"
                    f"block-{block_index:06d}"
                ),
                resource_plan_provider=self.transfer_resource_plan_provider,
                terminal_callback=partial(
                    self._on_normal_get_terminal,
                    execution.request_id,
                ),
            )
            [task] = operation.batch.tasks
            execution.pending_get_transfer_ids.add(task.metadata.transfer_id)

    def _on_normal_get_terminal(
        self,
        request_id: str,
        task: TransferTask,
        clock: GlobalDES,
    ) -> None:
        execution = self._execution_by_request[request_id]
        pending = execution.pending_get_transfer_ids
        if clock is not self.des or pending is None or task.metadata.transfer_id not in pending:
            raise TraceRunnerError("normal Store Get callback does not match its span")
        pending.remove(task.metadata.transfer_id)
        if task.status is not TransferStatus.COMPLETED:
            if _is_gpu_failure_abort(task):
                self._record_failure_deferred_transfer(
                    execution,
                    task,
                    phase="NORMAL_PREFIX_GET",
                )
                return
            self._block_execution(
                execution,
                code="TRC-BLOCK-STORE-GET",
                message="a committed-prefix Store Get did not complete successfully",
            )
            return
        if pending:
            return
        if execution.target_replica_id is None:
            raise TraceRunnerError("Store Get completed without a target replica")
        runtime = self.replicas[execution.target_replica_id].runtime
        runtime.scheduler.restore_waiting_request_prefix(
            request_id,
            restored_tokens=execution.restored_tokens,
        )
        execution.status = TraceSpanExecutionStatus.INFERENCE_READY
        self._ready_request_ids.add(request_id)
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_REMOTE_PREFIX_READY",
            {
                "span_id": execution.trace_span.span_id,
                "request_id": request_id,
                "target_replica_id": execution.target_replica_id,
                "restored_tokens": execution.restored_tokens,
            },
        )
        self._request_scheduler_step(execution.target_replica_id)

    def _request_scheduler_step(self, replica_id: str) -> None:
        if replica_id in self._forward_by_replica or replica_id in self._pending_step_replica_ids:
            return
        scheduler = self.replicas[replica_id].runtime.scheduler
        queued_ids = (*scheduler.running_request_ids, *scheduler.waiting_request_ids)
        replay_ids = sorted(
            (
                request_id
                for request_id in self._recovery_replay_request_ids
                if self._execution_by_request[request_id].target_replica_id == replica_id
            ),
            key=lambda request_id: (
                self._execution_by_request[request_id].trace_span.metadata.stable_sort_key
            ),
        )
        if replay_ids and queued_ids == (replay_ids[0],):
            self._schedule_scheduler_step_event(replica_id)
            return

        fetch_ready_ids = sorted(
            (
                request_id
                for request_id in self._recovery_fetch_ready_request_ids
                if self._execution_by_request[request_id].target_replica_id == replica_id
            ),
            key=lambda request_id: (
                self._execution_by_request[request_id].trace_span.metadata.stable_sort_key
            ),
        )
        if not queued_ids and fetch_ready_ids:
            self._prepare_recovery_replay(self._execution_by_request[fetch_ready_ids[0]])
            if fetch_ready_ids[0] in self._recovery_replay_request_ids:
                self._schedule_scheduler_step_event(replica_id)
            return

        ready = [
            request_id
            for request_id in self._ready_request_ids
            if self._execution_by_request[request_id].target_replica_id == replica_id
        ]
        if not ready:
            return
        running_ready = any(
            request_id in self._ready_request_ids for request_id in scheduler.running_request_ids
        )
        if (
            not running_ready
            and len(scheduler.running_request_ids) >= scheduler.max_num_running_requests
        ):
            # A completed remote prefix remains waiting until an ordinary
            # running slot becomes available.  Store-save completion will
            # request another step after releasing the current slot.
            return
        self._schedule_scheduler_step_event(replica_id)

    def _schedule_scheduler_step_event(self, replica_id: str) -> None:
        event_id = self._next_event_id(f"scheduler:{replica_id}")
        self.des.schedule_at(
            self.des.now_ns,
            EventKind.SCHEDULER_STEP_READY,
            event_id=event_id,
            payload={"replica_id": replica_id},
        )
        self._pending_step_replica_ids.add(replica_id)

    def _on_scheduler_step_ready(self, event: ScheduledEvent, des: GlobalDES) -> None:
        if des is not self.des or set(event.payload) != {"replica_id"}:
            raise TraceRunnerError("scheduler-step event payload or clock is invalid")
        replica_id = event.payload["replica_id"]
        if not isinstance(replica_id, str) or replica_id not in self.replicas:
            raise TraceRunnerError("scheduler-step event names an unknown replica")
        if replica_id not in self._pending_step_replica_ids:
            raise TraceRunnerError("scheduler-step event has no pending runner owner")
        self._pending_step_replica_ids.remove(replica_id)
        if replica_id in self._forward_by_replica:
            raise TraceRunnerError("one DP replica cannot overlap two forward steps")
        scheduler = self.replicas[replica_id].runtime.scheduler
        replay_ids = sorted(
            (
                request_id
                for request_id in self._recovery_replay_request_ids
                if self._execution_by_request[request_id].target_replica_id == replica_id
            ),
            key=lambda request_id: (
                self._execution_by_request[request_id].trace_span.metadata.stable_sort_key
            ),
        )
        queued_ids = (*scheduler.running_request_ids, *scheduler.waiting_request_ids)
        if replay_ids and queued_ids == (replay_ids[0],):
            self._start_silent_replay_forward(
                self._execution_by_request[replay_ids[0]],
                replica_id=replica_id,
            )
            return
        ready_by_id = {
            request_id: self._execution_by_request[request_id]
            for request_id in self._ready_request_ids
            if self._execution_by_request[request_id].target_replica_id == replica_id
        }
        if not ready_by_id:
            return
        scheduler_order = (*scheduler.running_request_ids, *scheduler.waiting_request_ids)
        representative_id = next(
            (request_id for request_id in scheduler_order if request_id in ready_by_id),
            None,
        )
        if representative_id is None:
            raise TraceRunnerError("ready trace request is absent from its DP scheduler")
        representative = ready_by_id[representative_id]
        try:
            output = self.coordinator.run_scheduler_step(representative.request_id)
        except BaselineCoordinatorError as error:
            self._block_execution(
                representative,
                code="TRC-BLOCK-SCHEDULER-PROGRESS",
                message=f"scheduler made no safe progress: {error}",
            )
            return
        self._start_predicted_forward(replica_id, output)

    def _start_predicted_forward(self, replica_id: str, output: SchedulerOutput) -> None:
        scheduled_items = _ordered_scheduled_requests(output)
        executions: list[_SpanExecution] = []
        requests: dict[str, Request] = {}
        for item in scheduled_items:
            execution = self._execution_by_request.get(item.request_id)
            if execution is None or execution.request is None:
                raise TraceRunnerError("scheduler emitted a non-trace request")
            if (
                execution.target_replica_id != replica_id
                or item.request_id not in self._ready_request_ids
            ):
                raise TraceRunnerError(
                    "scheduler emitted a request without ready ownership on this replica"
                )
            executions.append(execution)
            requests[item.request_id] = execution.request
        try:
            used_mixed_composition = False
            adapted = self.adapter.adapt(
                output,
                requests=requests,
                profile=self.predictor.profile,
            )
            if len(adapted.phase_batches) == 1:
                prediction = self.predictor.predict(
                    adapted.phase_batches[0].batch,
                    require_formal=False,
                )
                duration_ns = prediction.predicted_forward_duration_ns
                prediction_document = prediction.to_dict()
                composition_document: dict[str, object] = {
                    "mode": "single_phase_provider",
                    "phase": adapted.phase_batches[0].phase.value,
                    "composition_rule": None,
                }
            elif len(adapted.phase_batches) == 2:
                if self.mixed_phase_composition_rule is None:
                    raise ValueError("mixed-phase forward composition has no explicit rule")
                mixed_prediction = self.mixed_phase_composition_rule.compose(
                    tuple(item.batch for item in adapted.phase_batches)
                )
                duration_ns = mixed_prediction.predicted_forward_duration_ns
                prediction_document = mixed_prediction.to_dict()
                composition_document = {
                    "mode": "mixed_phase_joint_composition",
                    "composition_rule": (self.mixed_phase_composition_rule.to_dict()),
                    "calibration_status": "not_calibrated",
                    "formal_use_allowed": False,
                }
                used_mixed_composition = True
            else:
                raise ValueError("forward step has no phase batch")
            participant_items: list[_ForwardParticipant] = []
            for item in scheduled_items:
                request = requests[item.request_id]
                produces_output = _scheduled_request_produces_output(item, request)
                participant_items.append(
                    _ForwardParticipant(
                        request_id=item.request_id,
                        scheduled=item,
                        produces_output=produces_output,
                        output_index=(request.num_output_tokens if produces_output else None),
                    )
                )
            participants = tuple(participant_items)
        except Exception as error:
            for execution in executions:
                self._block_execution(
                    execution,
                    code="TRC-BLOCK-FORWARD-PREDICTOR",
                    message=f"explicit forward predictor could not serve the batch: {error}",
                )
            return
        if used_mixed_composition:
            self._mixed_phase_composition_count += 1
        for execution in executions:
            execution.scheduler_step_count += 1
            execution.forward_duration_ns += duration_ns
            execution.status = TraceSpanExecutionStatus.FORWARD
            self._ready_request_ids.discard(execution.request_id)
        participant_rows = [
            {
                "request_id": item.request_id,
                "span_id": self._execution_by_request[item.request_id].trace_span.span_id,
                "phase": item.scheduled.phase.value,
                "chunked": item.scheduled.chunked,
                "num_scheduled_tokens": item.scheduled.num_scheduled_tokens,
                "num_computed_tokens_before": (item.scheduled.num_computed_tokens_before),
                "num_computed_tokens_after": item.scheduled.num_computed_tokens_after,
                "produces_output": item.produces_output,
                "output_index": item.output_index,
            }
            for item in participants
        ]
        phase_shape_rows = [
            {
                "phase": item.phase.value,
                "request_ids": list(item.request_ids),
                "batch_fingerprint": item.batch.fingerprint,
                "shape": item.batch.shape.to_dict(),
            }
            for item in adapted.phase_batches
        ]
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_FORWARD_PREDICTED",
            {
                "replica_id": replica_id,
                "batch_size": len(participants),
                "participants": participant_rows,
                "phase_shapes": phase_shape_rows,
                "adapter": {
                    "fingerprint": adapted.fingerprint,
                    "scheduler_output_fingerprint": (adapted.scheduler_output_fingerprint),
                    "source_commit": adapted.source_commit,
                    "source_sha256": adapted.source_sha256,
                    "source_symbol": adapted.source_symbol,
                    "evidence_class": adapted.evidence_class,
                },
                "prediction": prediction_document,
                "composition": composition_document,
                "calibration_status": "not_calibrated",
                "formal_use_allowed": False,
                "recorded_api_time_used_as_delay": False,
            },
        )
        completion_ns = self.des.now_ns + duration_ns
        try:
            handle = self.coordinator.schedule_forward_batch_completion(
                tuple(item.request_id for item in participants),
                at_ns=completion_ns,
                produces_outputs={item.request_id: item.produces_output for item in participants},
                output_indices={item.request_id: item.output_index for item in participants},
                terminal_callback=self._on_forward_batch_terminal,
            )
        except Exception as error:
            for execution in executions:
                self._block_execution(
                    execution,
                    code="TRC-BLOCK-FORWARD-BATCH-PREFLIGHT",
                    message=f"forward batch could not be atomically published: {error}",
                )
            return
        lease = _ComputeLease(
            lease_id=f"gpu-compute:{replica_id}:{handle.event_id}",
            replica_id=replica_id,
            handle=handle,
            participants=participants,
            acquired_ns=self.des.now_ns,
            release_ns=completion_ns,
        )
        if replica_id in self._forward_by_replica:
            raise TraceRunnerError("GPU compute capacity=1 was double acquired")
        self._forward_by_replica[replica_id] = lease
        for execution in executions:
            execution.forward_handle = handle
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_GPU_COMPUTE_LEASE_ACQUIRED",
            {
                "lease_id": lease.lease_id,
                "replica_id": replica_id,
                "capacity": 1,
                "request_ids": [item.request_id for item in participants],
                "release_ns": completion_ns,
            },
        )

    def _on_forward_batch_terminal(
        self,
        terminal: ForwardBatchTerminal,
        clock: GlobalDES,
    ) -> None:
        if clock is not self.des:
            raise TraceRunnerError("forward batch completed on another clock")
        lease = self._forward_by_replica.get(terminal.replica_id)
        if lease is None or lease.handle.event_id != terminal.event_id:
            raise TraceRunnerError("forward batch callback has no compute lease")
        expected_ids = tuple(item.request_id for item in lease.participants)
        actual_ids = tuple(item.request_id for item in terminal.participants)
        if actual_ids != expected_ids:
            raise TraceRunnerError("forward batch callback participant order diverged")
        self._release_compute_lease(
            lease,
            outcome="COMPLETED" if terminal.accepted else "FENCED",
        )
        if not terminal.accepted:
            for item in lease.participants:
                self._block_execution(
                    self._execution_by_request[item.request_id],
                    code="TRC-BLOCK-FORWARD-BATCH-FENCED",
                    message=(
                        f"forward batch failed atomic completion preflight: {terminal.fence_reason}"
                    ),
                )
            return

        scheduler = self.replicas[terminal.replica_id].runtime.scheduler
        for item in lease.participants:
            execution = self._execution_by_request[item.request_id]
            request = execution.request
            if request is None or execution.status is not TraceSpanExecutionStatus.FORWARD:
                raise TraceRunnerError("accepted forward participant has invalid state")
            if item.produces_output:
                if request.num_output_tokens >= request.max_output_tokens:
                    raise TraceRunnerError("forward completed after the recorded output reserve")
                scheduler.append_output_tokens(
                    item.request_id,
                    1,
                    terminal=(request.num_output_tokens + 1 == request.max_output_tokens),
                )
            if request.num_output_tokens == request.max_output_tokens:
                execution.status = TraceSpanExecutionStatus.STORE_SAVE
                self.des.schedule_at(
                    self.des.now_ns,
                    EventKind.PUT_START,
                    event_id=self._next_event_id(f"store-save:{item.request_id}"),
                    payload={"request_id": item.request_id},
                )
            else:
                execution.status = TraceSpanExecutionStatus.INFERENCE_READY
                self._ready_request_ids.add(item.request_id)
        self._request_scheduler_step(terminal.replica_id)

    def _start_silent_replay_forward(
        self,
        execution: _SpanExecution,
        *,
        replica_id: str,
    ) -> None:
        """Run one predictor-backed, externally silent recovery model step."""

        if (
            execution.request is None
            or execution.request_id not in self._recovery_replay_request_ids
            or execution.target_replica_id != replica_id
            or execution.route_version is None
        ):
            raise TraceRunnerError("silent replay forward lacks authoritative runner state")
        replay_before = self.coordinator.silent_replay_plan(execution.request_id)
        if replay_before.status is not SilentReplayStatus.REPLAYING:
            raise TraceRunnerError("silent replay forward started outside REPLAYING")
        try:
            output = self.coordinator.run_silent_replay_scheduler_step(execution.request_id)
            scheduled_items = _ordered_scheduled_requests(output)
            if len(scheduled_items) != 1 or scheduled_items[0].request_id != execution.request_id:
                raise TraceRunnerError("silent replay scheduler output is not isolated")
            scheduled = scheduled_items[0]
            adapted = self.adapter.adapt(
                output,
                requests={execution.request_id: execution.request},
                profile=self.predictor.profile,
            )
            if len(adapted.phase_batches) != 1:
                raise TraceRunnerError("isolated silent replay produced a mixed-phase batch")
            phase_batch = adapted.phase_batches[0]
            prediction = self.predictor.predict(
                phase_batch.batch,
                require_formal=False,
            )
            duration_ns = prediction.predicted_forward_duration_ns
            materializes_internal_output = _scheduled_request_produces_output(
                scheduled,
                execution.request,
            )
        except Exception as error:
            raise TraceRunnerError(
                f"recovery silent replay predictor could not serve the step: {error}"
            ) from error

        execution.scheduler_step_count += 1
        execution.forward_duration_ns += duration_ns
        execution.status = TraceSpanExecutionStatus.FORWARD
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_SILENT_REPLAY_FORWARD_PREDICTED",
            {
                "replica_id": replica_id,
                "span_id": execution.trace_span.span_id,
                "request_id": execution.request_id,
                "route_version": execution.route_version,
                "participant": {
                    "phase": scheduled.phase.value,
                    "chunked": scheduled.chunked,
                    "num_scheduled_tokens": scheduled.num_scheduled_tokens,
                    "num_computed_tokens_before": (scheduled.num_computed_tokens_before),
                    "num_computed_tokens_after": scheduled.num_computed_tokens_after,
                    "materializes_internal_output": materializes_internal_output,
                    "externally_emitted": False,
                },
                "phase_shape": {
                    "phase": phase_batch.phase.value,
                    "request_ids": list(phase_batch.request_ids),
                    "batch_fingerprint": phase_batch.batch.fingerprint,
                    "shape": phase_batch.batch.shape.to_dict(),
                },
                "adapter": {
                    "fingerprint": adapted.fingerprint,
                    "scheduler_output_fingerprint": (adapted.scheduler_output_fingerprint),
                    "source_commit": adapted.source_commit,
                    "source_sha256": adapted.source_sha256,
                    "source_symbol": adapted.source_symbol,
                    "evidence_class": adapted.evidence_class,
                },
                "prediction": prediction.to_dict(),
                "silent_replay_before": replay_before.to_dict(),
                "calibration_status": "not_calibrated",
                "formal_use_allowed": False,
                "recorded_api_time_used_as_delay": False,
            },
        )
        completion_ns = self.des.now_ns + duration_ns
        try:
            handle = self.coordinator.schedule_silent_replay_completion(
                execution.request_id,
                at_ns=completion_ns,
                terminal_callback=partial(
                    self._on_silent_replay_terminal,
                    execution.request_id,
                    execution.route_version,
                    replica_id,
                ),
            )
        except Exception as error:
            raise TraceRunnerError(
                f"recovery silent replay completion could not be scheduled: {error}"
            ) from error
        participant = _ForwardParticipant(
            request_id=execution.request_id,
            scheduled=scheduled,
            produces_output=False,
            output_index=None,
        )
        lease = _ComputeLease(
            lease_id=f"gpu-compute:{replica_id}:{handle.event_id}",
            replica_id=replica_id,
            handle=handle,
            participants=(participant,),
            acquired_ns=self.des.now_ns,
            release_ns=completion_ns,
        )
        if replica_id in self._forward_by_replica:
            raise TraceRunnerError("GPU compute capacity=1 was double acquired")
        self._forward_by_replica[replica_id] = lease
        execution.forward_handle = handle
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_GPU_COMPUTE_LEASE_ACQUIRED",
            {
                "lease_id": lease.lease_id,
                "replica_id": replica_id,
                "capacity": 1,
                "request_ids": [execution.request_id],
                "release_ns": completion_ns,
                "purpose": "recovery_silent_replay",
            },
        )

    def _on_silent_replay_terminal(
        self,
        request_id: str,
        route_version: int,
        replica_id: str,
        event: ScheduledEvent,
        clock: GlobalDES,
    ) -> None:
        if clock is not self.des:
            raise TraceRunnerError("silent replay completed on another clock")
        execution = self._execution_by_request[request_id]
        if execution.route_version != route_version or execution.target_replica_id != replica_id:
            raise TraceRunnerError("silent replay callback is stale")
        lease = self._forward_by_replica.get(replica_id)
        if lease is None or lease.handle.event_id != event.event_id:
            raise TraceRunnerError("silent replay callback has no compute lease")
        self._release_compute_lease(lease, outcome="COMPLETED")
        replay_after = self.coordinator.silent_replay_plan(request_id)
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_SILENT_REPLAY_FORWARD_COMPLETED",
            {
                "event_id": event.event_id,
                "span_id": execution.trace_span.span_id,
                "request_id": request_id,
                "route_version": route_version,
                "target_replica_id": replica_id,
                "silent_replay_after": replay_after.to_dict(),
                "externally_emitted": False,
            },
        )
        if replay_after.status is SilentReplayStatus.READY_TO_ACTIVATE:
            self._activate_materialized_recovery(execution)
            return
        if replay_after.status is not SilentReplayStatus.REPLAYING:
            raise TraceRunnerError("silent replay completed into an invalid continuation state")
        execution.status = TraceSpanExecutionStatus.REMOTE_PREFIX
        self._request_scheduler_step(replica_id)

    def _on_begin_store_save(self, event: ScheduledEvent, des: GlobalDES) -> None:
        if des is not self.des or set(event.payload) != {"request_id"}:
            raise TraceRunnerError("Store-save event payload or clock is invalid")
        request_id = event.payload["request_id"]
        if not isinstance(request_id, str) or request_id not in self._execution_by_request:
            raise TraceRunnerError("Store-save event names an unknown request")
        execution = self._execution_by_request[request_id]
        if execution.status is not TraceSpanExecutionStatus.STORE_SAVE:
            raise TraceRunnerError("Store-save event executed from the wrong state")
        if execution.target_replica_id is None or execution.route_version is None:
            raise TraceRunnerError("Store-save request has no current route")
        runtime = self.replicas[execution.target_replica_id].runtime
        current_blocks = tuple(
            replace(
                item,
                route_version=execution.route_version,
                source_gpu_id=runtime.gpu_id,
            )
            for item in execution.required_blocks
        )
        pending: set[str] = set()
        execution.pending_put_transfer_ids = pending
        for block_index, identity in enumerate(current_blocks):
            if self.coordinator.query_store(
                replica_id=execution.target_replica_id,
                identity=identity,
            ):
                continue
            operation = self.coordinator.start_store_put(
                request_id,
                identity,
                put_id=(
                    f"trace-put:{execution.trace_span.span_id}:"
                    f"route-{execution.route_version}:block-{block_index:06d}"
                ),
                payload_bytes=self.config.store_payload_bytes_per_source_block,
                preferred_segment_ids=self.config.preferred_store_segment_ids,
                resource_plan_provider=self.transfer_resource_plan_provider,
                terminal_callback=partial(
                    self._on_store_put_terminal,
                    request_id,
                ),
            )
            [task] = operation.batch.tasks
            pending.add(task.metadata.transfer_id)
        if not pending:
            self._complete_span(execution)

    def _on_store_put_terminal(
        self,
        request_id: str,
        task: TransferTask,
        clock: GlobalDES,
    ) -> None:
        execution = self._execution_by_request[request_id]
        pending = execution.pending_put_transfer_ids
        if clock is not self.des or pending is None or task.metadata.transfer_id not in pending:
            raise TraceRunnerError("Store Put callback does not match its span")
        pending.remove(task.metadata.transfer_id)
        if task.status is not TransferStatus.COMPLETED:
            if _is_gpu_failure_abort(task):
                self._record_failure_deferred_transfer(
                    execution,
                    task,
                    phase="STORE_PUT",
                )
                return
            self._block_execution(
                execution,
                code="TRC-BLOCK-STORE-PUT",
                message="a baseline Store Put did not complete successfully",
            )
            return
        if not pending:
            self._complete_span(execution)

    def _complete_span(self, execution: _SpanExecution) -> None:
        if execution.status is not TraceSpanExecutionStatus.STORE_SAVE:
            raise TraceRunnerError("span completion requires terminal Store-save state")
        self.coordinator.finish_current_request(execution.request_id)
        execution.status = TraceSpanExecutionStatus.COMPLETED
        execution.completed_ns = self.des.now_ns
        causal = self._require_causal()
        causal.mark_completed(execution.trace_span.span_id)
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_SPAN_COMPLETED",
            {
                "span_id": execution.trace_span.span_id,
                "workflow_id": execution.trace_span.workflow_id,
                "request_id": execution.request_id,
                "route_version": execution.route_version,
                "target_replica_id": execution.target_replica_id,
                "restored_tokens": execution.restored_tokens,
                "scheduler_step_count": execution.scheduler_step_count,
                "predicted_forward_ns": execution.forward_duration_ns,
            },
        )
        if execution.target_replica_id is not None:
            self._request_scheduler_step(execution.target_replica_id)

    def _release_compute_lease(
        self,
        lease: _ComputeLease,
        *,
        outcome: str,
    ) -> None:
        current = self._forward_by_replica.get(lease.replica_id)
        if current is not lease:
            raise TraceRunnerError("GPU compute lease release is stale")
        del self._forward_by_replica[lease.replica_id]
        for item in lease.participants:
            execution = self._execution_by_request[item.request_id]
            if (
                execution.forward_handle is None
                or execution.forward_handle.event_id != lease.handle.event_id
            ):
                raise TraceRunnerError("compute lease participant lost its event handle")
            execution.forward_handle = None
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_GPU_COMPUTE_LEASE_RELEASED",
            {
                "lease_id": lease.lease_id,
                "replica_id": lease.replica_id,
                "capacity": 1,
                "request_ids": [item.request_id for item in lease.participants],
                "acquired_ns": lease.acquired_ns,
                "declared_release_ns": lease.release_ns,
                "actual_release_ns": self.des.now_ns,
                "outcome": outcome,
            },
        )

    def _cancel_compute_lease(self, handle: EventHandle, *, reason: str) -> None:
        lease = next(
            (
                item
                for item in self._forward_by_replica.values()
                if item.handle.event_id == handle.event_id
            ),
            None,
        )
        if lease is None:
            return
        self.coordinator.discard_forward_terminal_callback(handle)
        self._release_compute_lease(lease, outcome=f"CANCELED:{reason}")

    def _on_recovery_start(self, event: ScheduledEvent, des: GlobalDES) -> None:
        if des is not self.des or set(event.payload) != {"failure_id", "gpu_id"}:
            raise TraceRunnerError("recovery-start event payload or clock is invalid")
        failure_id = event.payload["failure_id"]
        gpu_id = event.payload["gpu_id"]
        if not isinstance(failure_id, str) or not isinstance(gpu_id, str):
            raise TraceRunnerError("recovery-start IDs must be strings")
        candidates: list[tuple[_SpanExecution, str]] = []
        for execution in self._execution_by_span.values():
            if (
                execution.request is None
                or execution.status
                in {
                    TraceSpanExecutionStatus.COMPLETED,
                    TraceSpanExecutionStatus.UNAVAILABLE,
                }
                or execution.route_version is None
            ):
                continue
            authority = self.coordinator.router.current_authority(execution.request_id)
            if authority.route_version > execution.route_version:
                candidates.append((execution, "REROUTE"))
                continue
            attempt = self.coordinator.failure_controller.attempt(
                execution.request_id,
                execution.route_version,
            )
            if attempt.status is AttemptStatus.RECOVERY_FAILED_NO_TARGET:
                candidates.append((execution, "RECOVERY_FAILED_NO_TARGET"))

        for execution, disposition in sorted(
            candidates,
            key=lambda item: item[0].trace_span.metadata.stable_sort_key,
        ):
            if execution.forward_handle is not None:
                self._cancel_compute_lease(
                    execution.forward_handle,
                    reason=f"GPU_FAILURE:{failure_id}",
                )
            self._ready_request_ids.discard(execution.request_id)
            self._recovery_fetch_ready_request_ids.discard(execution.request_id)
            self._recovery_replay_request_ids.discard(execution.request_id)
            if disposition == "RECOVERY_FAILED_NO_TARGET":
                self._block_execution(
                    execution,
                    code="TRC-BLOCK-RECOVERY-NO-TARGET",
                    message=(
                        f"GPU failure {failure_id} on {gpu_id} left no healthy reroute target"
                    ),
                )
                continue
            authority = self.coordinator.router.current_authority(execution.request_id)
            execution.target_replica_id = authority.target_replica_id
            execution.route_version = authority.route_version
            operations = self.coordinator.start_recovery_fetches(
                execution.request_id,
                resource_plan_provider=self.transfer_resource_plan_provider,
                terminal_callback=partial(
                    self._on_recovery_get_terminal,
                    execution.request_id,
                ),
            )
            pending = {
                task.metadata.transfer_id
                for operation in operations
                for task in operation.batch.tasks
            }
            execution.pending_get_transfer_ids = pending
            execution.status = TraceSpanExecutionStatus.REMOTE_PREFIX
            self.des.journal.append(
                self.des.now_ns,
                "TRACE_RUNNER_RECOVERY_STARTED",
                {
                    "failure_id": failure_id,
                    "gpu_id": gpu_id,
                    "span_id": execution.trace_span.span_id,
                    "request_id": execution.request_id,
                    "route_version": authority.route_version,
                    "target_replica_id": authority.target_replica_id,
                    "transfer_count": len(pending),
                },
            )
            if not pending:
                self._mark_recovery_fetches_ready(execution)

    def _on_recovery_get_terminal(
        self,
        request_id: str,
        task: TransferTask,
        clock: GlobalDES,
    ) -> None:
        execution = self._execution_by_request[request_id]
        pending = execution.pending_get_transfer_ids
        if clock is not self.des or pending is None or task.metadata.transfer_id not in pending:
            raise TraceRunnerError("recovery Store Get callback does not match its span")
        pending.remove(task.metadata.transfer_id)
        if task.status is not TransferStatus.COMPLETED:
            if _is_gpu_failure_abort(task):
                self._record_failure_deferred_transfer(
                    execution,
                    task,
                    phase="RECOVERY_PREFIX_GET",
                )
                return
            self._block_execution(
                execution,
                code="TRC-BLOCK-RECOVERY-GET",
                message="recovery Store Get did not complete successfully",
            )
            return
        if not pending:
            self._mark_recovery_fetches_ready(execution)

    def _record_failure_deferred_transfer(
        self,
        execution: _SpanExecution,
        task: TransferTask,
        *,
        phase: str,
    ) -> None:
        if not _is_gpu_failure_abort(task):
            raise TraceRunnerError("deferred transfer is not a GPU_FAILURE abort")
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_GPU_FAILURE_TRANSFER_DEFERRED",
            {
                "span_id": execution.trace_span.span_id,
                "request_id": execution.request_id,
                "transfer_id": task.metadata.transfer_id,
                "phase": phase,
                "abort_reason": task.abort_reason,
            },
        )

    def _mark_recovery_fetches_ready(self, execution: _SpanExecution) -> None:
        plan = self.coordinator.recovery_plan(execution.request_id)
        execution.restored_tokens = plan.restored_tokens
        self._recovery_fetch_ready_request_ids.add(execution.request_id)
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_RECOVERY_FETCHES_READY",
            {
                "span_id": execution.trace_span.span_id,
                "request_id": execution.request_id,
                "route_version": execution.route_version,
                "target_replica_id": execution.target_replica_id,
                "restored_tokens": plan.restored_tokens,
                "recompute_tokens": plan.recompute_tokens,
                "activation_deferred_until_materialization": True,
            },
        )
        if execution.target_replica_id is None:
            raise TraceRunnerError("recovery fetches completed without a target replica")
        self._request_scheduler_step(execution.target_replica_id)

    def _prepare_recovery_replay(self, execution: _SpanExecution) -> None:
        if execution.request_id not in self._recovery_fetch_ready_request_ids:
            raise TraceRunnerError("recovery preparation lacks completed fetch ownership")
        try:
            recovered = self.coordinator.prepare_recovery(execution.request_id)
        except BaselineCoordinatorError as error:
            self._block_execution(
                execution,
                code="GPU_FAILURE_RECOVERY_PREPARATION_BLOCKED",
                message=str(error),
            )
            return
        execution.request = recovered
        self._recovery_fetch_ready_request_ids.discard(execution.request_id)
        self._recovery_replay_request_ids.add(execution.request_id)
        execution.status = TraceSpanExecutionStatus.REMOTE_PREFIX
        replay = self.coordinator.silent_replay_plan(execution.request_id)
        if replay.status is not SilentReplayStatus.REPLAYING:
            raise TraceRunnerError("prepared recovery did not enter silent replay")
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_RECOVERY_MATERIALIZATION_STARTED",
            {
                "span_id": execution.trace_span.span_id,
                "request_id": execution.request_id,
                "route_version": execution.route_version,
                "target_replica_id": execution.target_replica_id,
                "silent_replay": replay.to_dict(),
                "externally_emitted": False,
            },
        )

    def _activate_materialized_recovery(self, execution: _SpanExecution) -> None:
        replay = self.coordinator.silent_replay_plan(execution.request_id)
        if replay.status is not SilentReplayStatus.READY_TO_ACTIVATE:
            raise TraceRunnerError("recovery activation attempted before replay readiness")
        try:
            recovered = self.coordinator.activate_recovery(execution.request_id)
        except BaselineCoordinatorError as error:
            self._block_execution(
                execution,
                code="GPU_FAILURE_RECOVERY_ACTIVATION_BLOCKED",
                message=str(error),
            )
            return
        execution.request = recovered
        self._recovery_replay_request_ids.discard(execution.request_id)
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_RECOVERY_ACTIVATED",
            {
                "span_id": execution.trace_span.span_id,
                "request_id": execution.request_id,
                "route_version": execution.route_version,
                "target_replica_id": execution.target_replica_id,
                "silent_replay": self.coordinator.silent_replay_plan(
                    execution.request_id
                ).to_dict(),
                "activation_gate": "READY_TO_ACTIVATE_after_modeled_forward_completion",
            },
        )
        if recovered.num_output_tokens == recovered.max_output_tokens:
            execution.status = TraceSpanExecutionStatus.STORE_SAVE
            self.des.schedule_at(
                self.des.now_ns,
                EventKind.PUT_START,
                event_id=self._next_event_id(f"store-save:{execution.request_id}"),
                payload={"request_id": execution.request_id},
            )
            return
        execution.status = TraceSpanExecutionStatus.INFERENCE_READY
        self._ready_request_ids.add(execution.request_id)
        if execution.target_replica_id is None:
            raise TraceRunnerError("recovered request has no target replica")
        self._request_scheduler_step(execution.target_replica_id)

    def _block_execution(
        self,
        execution: _SpanExecution,
        *,
        code: str,
        message: str,
    ) -> None:
        if execution.status is TraceSpanExecutionStatus.UNAVAILABLE:
            return
        self._gaps.append(TraceRunnerGap(code, message, (execution.trace_span.span_id,)))
        self._ready_request_ids.discard(execution.request_id)
        self._recovery_fetch_ready_request_ids.discard(execution.request_id)
        self._recovery_replay_request_ids.discard(execution.request_id)
        request = execution.request
        if request is not None and not request.finished:
            with suppress(BaselineCoordinatorError, ValueError):
                self.coordinator.finish_current_request(
                    execution.request_id,
                    status=RequestStatus.FINISHED_ERROR,
                )
        execution.status = TraceSpanExecutionStatus.UNAVAILABLE
        causal = self._require_causal()
        snapshot = causal.snapshot(execution.trace_span.span_id)
        if snapshot.status is SpanRuntimeStatus.RELEASED:
            causal.mark_unavailable(execution.trace_span.span_id, reason=code)
        self.des.journal.append(
            self.des.now_ns,
            "TRACE_RUNNER_SPAN_UNAVAILABLE",
            {
                "span_id": execution.trace_span.span_id,
                "request_id": execution.request_id,
                "code": code,
                "message": message,
            },
        )

    def _required_blocks(
        self,
        execution: _SpanExecution,
        *,
        source_gpu_id: str,
    ) -> tuple[KVIdentity, ...]:
        metadata = execution.trace_span.metadata
        result: list[KVIdentity] = []
        for block_index, source_hash_id in enumerate(execution.trace_span.source_hash_ids):
            token_start = block_index * SOURCE_BLOCK_SIZE_TOKENS
            stable_block_hash = sha256_json(
                {
                    "schema": "moonkvsim.source-hash-block.v1",
                    "scope": "within_workflow_only",
                    "workflow_id": metadata.workflow_id,
                    "source_hash_id": source_hash_id,
                }
            )
            result.append(
                KVIdentity(
                    tenant_id=self.config.tenant_id,
                    model_id=self.config.target_model_id,
                    model_revision=self.config.target_model_revision,
                    kv_dtype=self.config.kv_dtype,
                    kv_abi=self.config.kv_abi,
                    kv_layout=self.config.kv_layout,
                    tp_size=self.config.tensor_parallel_size,
                    pp_size=self.config.pipeline_parallel_size,
                    block_size_tokens=SOURCE_BLOCK_SIZE_TOKENS,
                    stable_block_hash=stable_block_hash,
                    token_start=token_start,
                    token_end=token_start + SOURCE_BLOCK_SIZE_TOKENS,
                    shard_id="tp0",
                    request_id=execution.request_id,
                    session_id=metadata.session_id,
                    workflow_id=metadata.workflow_id,
                    route_version=0,
                    source_gpu_id=source_gpu_id,
                )
            )
        return tuple(result)

    def _require_causal(self) -> CausalReleaseEngine:
        if self._causal is None:
            raise TraceRunnerError("causal engine is not initialized")
        return self._causal

    def _next_event_id(self, suffix: str) -> str:
        event_id = f"trace-runner:{self._event_sequence:016d}:{suffix}"
        self._event_sequence += 1
        return event_id


def _ordered_scheduled_requests(output: SchedulerOutput) -> tuple[ScheduledRequest, ...]:
    grouped = (
        *output.scheduled_running_reqs,
        *output.scheduled_new_reqs,
        *output.scheduled_resumed_reqs,
    )
    by_id = {item.request_id: item for item in grouped}
    if len(by_id) != len(grouped) or set(by_id) != set(output.scheduled_req_ids):
        raise TraceRunnerError("scheduler output request groups are not one-to-one")
    return tuple(by_id[request_id] for request_id in output.scheduled_req_ids)


def _is_gpu_failure_abort(task: TransferTask) -> bool:
    reason = task.abort_reason
    return reason is not None and any(item.startswith("GPU_FAILURE:") for item in reason.split(";"))


def _scheduled_request_produces_output(
    item: ScheduledRequest,
    request: Request,
) -> bool:
    if request.num_computed_tokens != item.num_computed_tokens_after:
        raise TraceRunnerError("scheduled counters do not match live request state")
    remaining_before = request.num_tokens - item.num_computed_tokens_before
    if remaining_before <= 0:
        raise TraceRunnerError("scheduled request had no materialized work")
    expected_chunked = item.num_scheduled_tokens < remaining_before
    if item.chunked is not expected_chunked:
        raise TraceRunnerError("scheduled chunked flag disagrees with request counters")
    if item.phase is SchedulingPhase.PREFILL:
        if item.num_computed_tokens_before >= request.prompt_tokens:
            raise TraceRunnerError("prefill phase begins beyond the prompt boundary")
        if item.num_computed_tokens_after > request.prompt_tokens:
            raise TraceRunnerError("prefill phase crosses the prompt boundary")
        if item.chunked:
            if item.num_computed_tokens_after >= request.prompt_tokens:
                raise TraceRunnerError("chunked prefill cannot produce a sampled output")
            return False
        if item.num_computed_tokens_after != request.prompt_tokens:
            raise TraceRunnerError("terminal prefill did not compute the full prompt")
        return True
    if item.phase is SchedulingPhase.DECODE:
        if (
            item.num_computed_tokens_before < request.prompt_tokens
            or item.num_scheduled_tokens != 1
            or item.chunked
        ):
            raise TraceRunnerError("decode forward shape is not ordinary one-token decode")
        return True
    raise TraceRunnerError("scheduled request has an unsupported phase")


def _select_whole_workflows(
    spans: Sequence[TraceSpanInput],
    selection: TraceSelection,
) -> tuple[TraceSpanInput, ...]:
    grouped: dict[str, list[TraceSpanInput]] = defaultdict(list)
    for item in spans:
        grouped[item.workflow_id].append(item)
    ordered_workflows = sorted(
        grouped,
        key=lambda workflow_id: (
            min(item.metadata.workflow_line for item in grouped[workflow_id]),
            workflow_id,
        ),
    )
    if selection.workflow_ids is not None:
        unknown = set(selection.workflow_ids) - grouped.keys()
        if unknown:
            raise TraceSelectionError(f"workflow filter contains unknown IDs: {sorted(unknown)}")
        ordered_workflows = [
            workflow_id
            for workflow_id in ordered_workflows
            if workflow_id in set(selection.workflow_ids)
        ]
        selected_count = sum(len(grouped[item]) for item in ordered_workflows)
        if selection.max_spans is not None and selected_count > selection.max_spans:
            raise TraceSelectionError(
                "workflow filter plus max_spans would cut a workflow DAG; no partial "
                "workflow selection is allowed"
            )
    elif selection.max_spans is not None:
        selected_workflows: list[str] = []
        count = 0
        for workflow_id in ordered_workflows:
            workflow_count = len(grouped[workflow_id])
            if count + workflow_count > selection.max_spans:
                break
            selected_workflows.append(workflow_id)
            count += workflow_count
        if not selected_workflows:
            raise TraceSelectionError(
                "max_spans is smaller than the first whole workflow; causal closure "
                "cannot be preserved"
            )
        ordered_workflows = selected_workflows
    selected = tuple(item for workflow_id in ordered_workflows for item in grouped[workflow_id])
    if not selected:
        raise TraceSelectionError("trace selection contains no complete workflow")
    return selected


def _validate_normalized_parent_prefix_metric(spans: Sequence[TraceSpanInput]) -> None:
    """Validate the causal-parent metric without treating it as Store truth.

    Normalization names the longest direct causal-parent hash overlap
    ``cached_prefix_tokens``.  A committed Store can also contain a matching
    prefix from an earlier non-parent span, so this metric is never a runtime
    query bound.  Runtime lookup scans the full current vector from block zero
    and stops at the first Store miss.  This check keeps only structural bounds
    on the normalized metric.
    """

    for item in spans:
        declared = item.metadata.cached_prefix_tokens
        if declared < 0 or declared > item.metadata.prompt_tokens:
            raise ValueError(f"span {item.span_id!r} cached_prefix_tokens is outside its prompt")
        if declared % SOURCE_BLOCK_SIZE_TOKENS:
            raise ValueError(
                f"span {item.span_id!r} cached_prefix_tokens is not source-block aligned"
            )


def _collect_ledgers(
    coordinator: BaselineCoordinator,
    replicas: Mapping[str, TraceReplicaBinding],
) -> dict[str, CapacityLedger]:
    ledgers: dict[str, CapacityLedger] = {}
    sources: list[Mapping[str, CapacityLedger]] = [coordinator.master.ledgers]
    sources.extend(item.hbm_bridge.ledgers for item in replicas.values())
    manager = coordinator.transfer_resource_manager
    if manager is not None:
        sources.append(manager.capacity_ledgers)
    for source in sources:
        for resource_id, ledger in source.items():
            previous = ledgers.get(resource_id)
            if previous is not None and previous is not ledger:
                raise ValueError(f"capacity resource is backed by two ledgers: {resource_id}")
            ledgers[resource_id] = ledger
    if not ledgers:
        raise ValueError("trace runner requires explicit capacity ledgers")
    return dict(sorted(ledgers.items()))


def _clone_ledger(ledger: CapacityLedger) -> CapacityLedger:
    return CapacityLedger(
        resource_id=ledger.resource_id,
        resource_kind=ledger.resource_kind,
        capacity_bytes=ledger.capacity_bytes,
        initial_accounts={
            account: value for account, value in ledger.accounts.items() if account != FREE_ACCOUNT
        },
    )


def _strict_non_negative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value
