"""Fail-closed contract runner for modeled Qwen3-32B DP8/TP4 results.

The default frozen workload preserves the Qwen3-8B input's exact token IDs and
workflow DAG but carries Qwen3-32B TP4 analytical isolated-request durations.
Those durations are modeled and uncalibrated, and they are not an execution
schedule.  A complete result is emitted only when a caller supplies an exact
external schedule whose workload/config fingerprints and workflow set match.

Recovery costs are not copied from that schedule.  Each selected logical chunk
is protected, fenced, and recovered through the GlobalDES-backed execution
surface of :class:`Qwen3TP4ExecutionDriver`, preserving four rank-local KV
shards, the TP readiness barrier, directory install, and the separate subsequent
model-forward all-reduce.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from moonkvsim.aegiskv.qwen3_32b_tp4_config import (
    Qwen3TP4EngineConfig,
    default_qwen3_32b_tp4_config_path,
    load_qwen3_32b_tp4_engine_config,
    repository_root,
)
from moonkvsim.aegiskv.qwen3_32b_tp4_execution import (
    Algorithm3ControlInput,
    FailureSet,
    PathExecutionControl,
    Qwen3TP4ExecutionDriver,
    RecoveryExecution,
)
from moonkvsim.aegiskv.types import PolicyPool

SCHEDULE_SCHEMA: Final = "moonkvsim.aegiskv.qwen3_32b_tp4_schedule.v1"
RESULT_SCHEMA: Final = "moonkvsim.aegiskv.qwen3_32b_tp4_run.v1"
GATE_SCHEMA: Final = "moonkvsim.aegiskv.qwen3_32b_tp4_runner_gate.v1"
EVIDENCE_CLASS: Final = "modeled_uncalibrated"
DEFAULT_WORKLOAD_RELATIVE_PATH: Final = Path(
    "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-32b-tp4-160.jsonl"
)
DEFAULT_MANIFEST_RELATIVE_PATH: Final = Path(
    "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-32b-tp4-160-manifest.json"
)


class Qwen3TP4RunnerError(ValueError):
    """A runner input violated the strict evidence contract."""


class Qwen3TP4RunnerBlocked(Qwen3TP4RunnerError):
    """The inputs are valid artifacts but lack evidence needed to compute WCT."""

    def __init__(self, report: dict[str, object]) -> None:
        super().__init__("Qwen3-32B TP4 run is BLOCKED by missing evidence gates")
        self.report = report


@dataclass(frozen=True, slots=True)
class WorkloadIdentity:
    artifact_sha256: str
    manifest_sha256: str
    manifest_fingerprint: str
    model_id: str
    model_revision: str
    record_count: int
    workflow_ids: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise Qwen3TP4RunnerError(f"cannot read {path}: {error}") from error
    return digest.hexdigest()


def _load_json(path: Path, *, kind: str) -> dict[str, Any]:
    if path.is_symlink():
        raise Qwen3TP4RunnerError(f"{kind} symlinks are forbidden: {path}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise Qwen3TP4RunnerError(f"duplicate key in {kind} {path}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except Qwen3TP4RunnerError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Qwen3TP4RunnerError(f"cannot load {kind} {path}: {error}") from error
    if not isinstance(value, dict):
        raise Qwen3TP4RunnerError(f"{kind} {path} must contain one JSON object")
    return value


def _exact_keys(
    value: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str] | frozenset[str] = frozenset(),
    where: str,
) -> None:
    missing = required - set(value)
    extra = set(value) - required - optional
    if missing or extra:
        raise Qwen3TP4RunnerError(
            f"{where} keys drift: missing={sorted(missing)}, extra={sorted(extra)}"
        )


def _string(value: object, where: str) -> str:
    if type(value) is not str or not value:
        raise Qwen3TP4RunnerError(f"{where} must be a non-empty string")
    return value


def _integer(value: object, where: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        qualifier = "positive" if positive else "non-negative"
        raise Qwen3TP4RunnerError(f"{where} must be a {qualifier} integer")
    return value


def _boolean(value: object, where: str) -> bool:
    if type(value) is not bool:
        raise Qwen3TP4RunnerError(f"{where} must be a boolean")
    return value


def _object(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Qwen3TP4RunnerError(f"{where} must be an object")
    return value


def _array(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise Qwen3TP4RunnerError(f"{where} must be an array")
    return value


def _string_array(value: object, where: str) -> tuple[str, ...]:
    rows = _array(value, where)
    result = tuple(_string(item, f"{where}[]") for item in rows)
    if len(set(result)) != len(result):
        raise Qwen3TP4RunnerError(f"{where} must not contain duplicates")
    return result


def _load_workload(workload_path: Path, manifest_path: Path) -> WorkloadIdentity:
    if workload_path.is_symlink() or manifest_path.is_symlink():
        raise Qwen3TP4RunnerError("workload and manifest symlinks are forbidden")
    manifest = _load_json(manifest_path, kind="workload manifest")
    if manifest.get("schema") != "moonkvsim.aegiskv.experiment_workload_manifest.v1":
        raise Qwen3TP4RunnerError("unsupported workload manifest schema")
    artifact = _object(manifest.get("artifact"), "manifest.artifact")
    normalizer = _object(manifest.get("normalizer"), "manifest.normalizer")
    selection = _object(manifest.get("selection"), "manifest.selection")
    expected_sha = _string(artifact.get("sha256"), "manifest.artifact.sha256")
    actual_sha = _sha256(workload_path)
    if actual_sha != expected_sha:
        raise Qwen3TP4RunnerError("workload SHA256 does not match manifest.artifact.sha256")

    workflow_ids: set[str] = set()
    span_ids: set[str] = set()
    model_ids: set[str] = set()
    revisions: set[str] = set()
    record_count = 0
    try:
        lines = workload_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise Qwen3TP4RunnerError(f"cannot load workload {workload_path}: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line:
            raise Qwen3TP4RunnerError(f"blank workload record at line {line_number}")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise Qwen3TP4RunnerError(
                f"invalid workload JSON at line {line_number}: {error}"
            ) from error
        if not isinstance(row, dict):
            raise Qwen3TP4RunnerError(f"workload line {line_number} is not an object")
        workflow_ids.add(_string(row.get("workflow_id"), f"workload[{line_number}].workflow_id"))
        span_id = _string(row.get("span_id"), f"workload[{line_number}].span_id")
        if span_id in span_ids:
            raise Qwen3TP4RunnerError(f"duplicate workload span_id: {span_id}")
        span_ids.add(span_id)
        model_ids.add(_string(row.get("model_id"), f"workload[{line_number}].model_id"))
        revisions.add(_string(row.get("model_revision"), f"workload[{line_number}].model_revision"))
        record_count += 1

    if not record_count or len(model_ids) != 1 or len(revisions) != 1:
        raise Qwen3TP4RunnerError("workload must have records with one model id and revision")
    if record_count != _integer(artifact.get("record_count"), "manifest.artifact.record_count"):
        raise Qwen3TP4RunnerError("workload record count does not match manifest")
    selected = set(
        _string_array(selection.get("selected_workflow_ids"), "manifest.selected_workflow_ids")
    )
    if selected != workflow_ids:
        raise Qwen3TP4RunnerError("manifest selected workflow set does not match workload")
    model_id = next(iter(model_ids))
    revision = next(iter(revisions))
    if normalizer.get("model_id") != model_id or normalizer.get("model_revision") != revision:
        raise Qwen3TP4RunnerError("manifest normalizer model identity does not match workload")
    fingerprint = _string(manifest.get("fingerprint"), "manifest.fingerprint")
    return WorkloadIdentity(
        artifact_sha256=actual_sha,
        manifest_sha256=_sha256(manifest_path),
        manifest_fingerprint=fingerprint,
        model_id=model_id,
        model_revision=revision,
        record_count=record_count,
        workflow_ids=tuple(sorted(workflow_ids)),
    )


def _blocked_report(
    *,
    config: Qwen3TP4EngineConfig,
    config_sha256: str,
    workload: WorkloadIdentity,
    workload_path: Path,
    manifest_path: Path,
    schedule_path: Path | None,
) -> dict[str, object] | None:
    gates: list[dict[str, str]] = []
    if workload.model_id != config.model.model_id:
        gates.append(
            {
                "code": "WORKLOAD_MODEL_ID_MISMATCH",
                "detail": f"workload={workload.model_id}, required={config.model.model_id}",
            }
        )
    if workload.model_revision != config.model.revision:
        gates.append(
            {
                "code": "WORKLOAD_MODEL_REVISION_MISMATCH",
                "detail": (f"workload={workload.model_revision}, required={config.model.revision}"),
            }
        )
    if schedule_path is None:
        gates.extend(
            (
                {
                    "code": "QWEN3_32B_EXECUTION_SCHEDULE_MISSING",
                    "detail": "an exact external Qwen3-32B schedule was not supplied",
                },
                {
                    "code": "QWEN3_32B_WORKFLOW_RELEASE_COMPLETION_TIMES_MISSING",
                    "detail": "WCT cannot be synthesized from Qwen3-8B token timing metadata",
                },
            )
        )
    if not gates:
        return None
    return {
        "schema": GATE_SCHEMA,
        "status": "BLOCKED",
        "evidence_class": EVIDENCE_CLASS,
        "result_rows_written": 0,
        "wct_emitted": False,
        "trend_generation_performed": False,
        "missing_gates": gates,
        "engine": {
            "model_id": config.model.model_id,
            "model_revision": config.model.revision,
            "config_sha256": config_sha256,
        },
        "workload": {
            "path": str(workload_path.resolve()),
            "manifest_path": str(manifest_path.resolve()),
            "artifact_sha256": workload.artifact_sha256,
            "model_id": workload.model_id,
            "model_revision": workload.model_revision,
            "record_count": workload.record_count,
            "workflow_count": len(workload.workflow_ids),
        },
    }


def _canonical_hash(document: Mapping[str, object]) -> str:
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _percentile(values: Sequence[int], quantile: float) -> int:
    if not values:
        raise Qwen3TP4RunnerError("cannot aggregate an empty metric")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _metric(values: Sequence[int]) -> dict[str, int | float]:
    if not values:
        return {"count": 0, "mean": 0, "p95": 0, "max": 0}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "p95": _percentile(values, 0.95),
        "max": max(values),
    }


def _validate_evidence(schedule: Mapping[str, object]) -> None:
    evidence = _object(schedule.get("evidence"), "schedule.evidence")
    _exact_keys(
        evidence,
        required={
            "timing_and_bandwidth",
            "calibrated",
            "physical_measurement_completed",
            "wct_source",
            "trend_generation",
        },
        where="schedule.evidence",
    )
    if (
        evidence.get("timing_and_bandwidth") != EVIDENCE_CLASS
        or _boolean(evidence.get("calibrated"), "schedule.evidence.calibrated")
        or _boolean(
            evidence.get("physical_measurement_completed"),
            "schedule.evidence.physical_measurement_completed",
        )
        or evidence.get("wct_source") != "explicit_external_schedule"
        or _boolean(evidence.get("trend_generation"), "schedule.evidence.trend_generation")
    ):
        raise Qwen3TP4RunnerError("schedule must remain modeled_uncalibrated and unsmoothed")


def _path_control(available: bool) -> PathExecutionControl:
    if available:
        return PathExecutionControl()
    return PathExecutionControl(failed_tp_ranks=frozenset({0}))


def _recovery_json(
    *,
    failure_id: str,
    failure_at_ns: int,
    workflow_id: str,
    token_count: int,
    peer_available: bool,
    store_available: bool,
    recovery: RecoveryExecution,
) -> dict[str, object]:
    des_evidence = recovery.des_evidence
    if des_evidence is None:
        raise Qwen3TP4RunnerError("formal Qwen3-32B recovery bypassed GlobalDES")
    return {
        "failure_id": failure_id,
        "failure_at_ns": failure_at_ns,
        "workflow_id": workflow_id,
        "logical_chunk_id": recovery.logical_chunk_id,
        "selected_pool": recovery.pool.value,
        "available_reuse_tokens": {
            "peer_hbm": token_count if peer_available else 0,
            "store_dram": token_count if store_available else 0,
        },
        "selected_reuse_tokens": {
            "peer_hbm": token_count if recovery.pool is PolicyPool.PEER_HBM else 0,
            "store_dram": token_count if recovery.pool is PolicyPool.STORE_DRAM else 0,
        },
        "recovery_latency_ns": recovery.kv_recovery_latency_ns,
        "kv_recovery_start_ns": recovery.kv_recovery_start_ns,
        "kv_recovery_complete_ns": recovery.kv_recovery_complete_ns,
        "destination_dp_rank": recovery.destination_dp_rank,
        "rank_costs": [
            {
                "tp_rank": row.tp_rank,
                "source_node_id": row.source_node_id,
                "destination_node_id": row.destination_node_id,
                "source_resource_id": row.source_resource_id,
                "destination_gpu_id": row.destination_gpu_id,
                "restored_kv_bytes": row.restored_kv_bytes,
                "transfer_bytes": row.transfer_bytes,
                "activation_bytes": row.activation_bytes,
                "start_ns": row.start_ns,
                "complete_ns": row.complete_ns,
            }
            for row in recovery.rank_costs
        ],
        "tp_readiness_barrier": {
            "participant_gpu_ids": list(recovery.barrier.participant_gpu_ids),
            "resource_id": recovery.barrier.resource_id,
            "payload_bytes": recovery.barrier.payload_bytes,
            "start_ns": recovery.barrier.start_ns,
            "complete_ns": recovery.barrier.complete_ns,
        },
        "directory_generation_install": {
            "resource_id": recovery.directory_install.resource_id,
            "start_ns": recovery.directory_install.start_ns,
            "complete_ns": recovery.directory_install.complete_ns,
        },
        "model_forward_all_reduce": {
            "participant_gpu_ids": list(recovery.model_forward_all_reduce.participant_gpu_ids),
            "resource_id": recovery.model_forward_all_reduce.resource_id,
            "payload_bytes_per_rank": (recovery.model_forward_all_reduce.payload_bytes_per_rank),
            "total_collective_bytes": recovery.model_forward_all_reduce.total_collective_bytes,
            "start_ns": recovery.model_forward_all_reduce.start_ns,
            "complete_ns": recovery.model_forward_all_reduce.complete_ns,
            "operates_on_kv": recovery.model_forward_all_reduce.operates_on_kv,
            "included_in_kv_recovery_latency": (
                recovery.model_forward_all_reduce.included_in_kv_recovery_latency
            ),
        },
        "rank_resource_audit": [
            {
                "phase": row.phase,
                "pool": row.pool.value,
                "tp_rank": row.tp_rank,
                "node_id": row.node_id,
                "gpu_resource_id": row.gpu_resource_id,
                "resource_ids": list(row.resource_ids),
                "kv_bytes": row.kv_bytes,
                "transfer_bytes": row.transfer_bytes,
                "activated_bytes": row.activated_bytes,
                "model_collective_bytes": row.model_collective_bytes,
            }
            for row in recovery.rank_resources
        ],
        "node_resource_audit": [
            {
                "node_id": row.node_id,
                "resource_ids": list(row.resource_ids),
                "kv_source_read_bytes": row.kv_source_read_bytes,
                "kv_destination_write_bytes": row.kv_destination_write_bytes,
                "kv_activated_bytes": row.kv_activated_bytes,
                "model_collective_bytes": row.model_collective_bytes,
            }
            for row in recovery.node_resources
        ],
        "byte_conservation": {
            "logical_chunk_bytes": recovery.byte_audit.logical_chunk_bytes,
            "sum_rank_restored_kv_bytes": recovery.byte_audit.sum_rank_restored_kv_bytes,
            "source_read_bytes": recovery.byte_audit.source_read_bytes,
            "destination_write_bytes": recovery.byte_audit.destination_write_bytes,
            "activated_bytes": recovery.byte_audit.activated_bytes,
            "kv_reduction_bytes": recovery.byte_audit.kv_reduction_bytes,
            "model_collective_bytes_excluded": (
                recovery.byte_audit.model_collective_bytes_excluded
            ),
            "valid": recovery.byte_audit.valid,
        },
        "des_execution": {
            "backend": "GlobalDES",
            "evidence_class": des_evidence.evidence_class,
            "journal_sha256": des_evidence.journal_sha256,
            "journal_record_count": des_evidence.journal_record_count,
            "fenced_dp_ranks": list(des_evidence.fenced_dp_ranks),
            "failure_fence_event_count": des_evidence.failure_fence_event_count,
            "protection_path_states": [
                {
                    "pool": pool,
                    "state": state,
                    "acked_ranks": list(acked_ranks),
                    "capacity_committed": capacity_committed,
                }
                for pool, state, acked_ranks, capacity_committed in (
                    des_evidence.protection_path_states
                )
            ],
            "recovery_phase": des_evidence.recovery_phase,
            "four_shard_recovery_executed": (des_evidence.four_shard_recovery_executed),
            "capacity_conservation_valid": (des_evidence.capacity_conservation_valid),
            "algorithm2_four_shard_transaction_surface_executed": (
                des_evidence.algorithm2_four_shard_transaction_surface_executed
            ),
            "algorithm3_peer_quota_surface_enforced": (
                des_evidence.algorithm3_peer_quota_surface_enforced
            ),
            "algorithm3_controller_integration": (des_evidence.algorithm3_controller_integration),
            "algorithm3_audit": [
                {
                    "target_dp_rank": row.target_dp_rank,
                    "timestamp_ns": row.timestamp_ns,
                    "action": row.action,
                    "reason": row.reason,
                    "previous_fraction": row.previous_fraction,
                    "next_fraction": row.next_fraction,
                    "previous_stable_windows": row.previous_stable_windows,
                    "next_stable_windows": row.next_stable_windows,
                    "quota_bytes_per_rank": row.quota_bytes_per_rank,
                    "peer_usage_bytes_per_rank": list(row.peer_usage_bytes_per_rank),
                    "resident_primary_bytes_per_rank": list(row.resident_primary_bytes_per_rank),
                    "free_reclaimable_bytes_per_rank": list(row.free_reclaimable_bytes_per_rank),
                    "quota_enforced": row.quota_enforced,
                    "decision_fingerprint": row.decision_fingerprint,
                }
                for row in des_evidence.algorithm3_audit
            ],
            "event_trace": [
                {
                    "timestamp_ns": event.timestamp_ns,
                    "event_id": event.event_id,
                    "kind": event.kind,
                }
                for event in des_evidence.event_trace
            ],
        },
        "execution_fingerprint": recovery.fingerprint,
    }


def _parse_cell(schedule: Mapping[str, object], workflow_count: int) -> dict[str, object]:
    cell = _object(schedule.get("cell_identity"), "schedule.cell_identity")
    _exact_keys(
        cell,
        required={"cell_id", "failure_count", "workflow_concurrency", "seed"},
        where="schedule.cell_identity",
    )
    workflow_concurrency = _integer(
        cell.get("workflow_concurrency"),
        "schedule.cell_identity.workflow_concurrency",
        positive=True,
    )
    result: dict[str, object] = {
        "cell_id": _string(cell.get("cell_id"), "schedule.cell_identity.cell_id"),
        "failure_count": _integer(
            cell.get("failure_count"), "schedule.cell_identity.failure_count"
        ),
        "workflow_concurrency": workflow_concurrency,
        "seed": _integer(cell.get("seed"), "schedule.cell_identity.seed"),
    }
    if workflow_concurrency > workflow_count:
        raise Qwen3TP4RunnerError("workflow_concurrency exceeds workflow count")
    return result


def _parse_timings(
    schedule: Mapping[str, object], workload: WorkloadIdentity
) -> dict[str, tuple[int, int]]:
    rows = _array(schedule.get("workflow_timings"), "schedule.workflow_timings")
    result: dict[str, tuple[int, int]] = {}
    for index, raw in enumerate(rows):
        row = _object(raw, f"schedule.workflow_timings[{index}]")
        _exact_keys(
            row,
            required={"workflow_id", "released_ns", "completed_ns"},
            where=f"schedule.workflow_timings[{index}]",
        )
        workflow_id = _string(row.get("workflow_id"), f"workflow_timings[{index}].workflow_id")
        released = _integer(row.get("released_ns"), f"workflow_timings[{index}].released_ns")
        completed = _integer(row.get("completed_ns"), f"workflow_timings[{index}].completed_ns")
        if completed < released:
            raise Qwen3TP4RunnerError(f"workflow {workflow_id} completes before release")
        if workflow_id in result:
            raise Qwen3TP4RunnerError(f"duplicate workflow timing: {workflow_id}")
        result[workflow_id] = (released, completed)
    if set(result) != set(workload.workflow_ids):
        raise Qwen3TP4RunnerError("schedule workflow timing set does not exactly match workload")
    return result


def _parse_failures(
    schedule: Mapping[str, object],
    *,
    config: Qwen3TP4EngineConfig,
    cell: Mapping[str, object],
    timings: Mapping[str, tuple[int, int]],
) -> tuple[list[dict[str, object]], list[dict[str, str]], set[str]]:
    driver = Qwen3TP4ExecutionDriver(config)
    rows = _array(schedule.get("failures"), "schedule.failures")
    if len(rows) != cell["failure_count"]:
        raise Qwen3TP4RunnerError("failure_count does not equal schedule.failures length")
    failure_ids: set[str] = set()
    affected_pairs: list[dict[str, str]] = []
    affected_workflows: set[str] = set()
    audits: list[dict[str, object]] = []
    logical_chunk_ids: set[str] = set()
    for failure_index, raw_failure in enumerate(rows):
        where = f"schedule.failures[{failure_index}]"
        failure = _object(raw_failure, where)
        _exact_keys(
            failure,
            required={
                "failure_id",
                "occurred_ns",
                "failed_gpu_ids",
                "failed_node_ids",
                "affected_workflow_ids",
                "recoveries",
            },
            where=where,
        )
        failure_id = _string(failure.get("failure_id"), f"{where}.failure_id")
        if failure_id in failure_ids:
            raise Qwen3TP4RunnerError(f"duplicate failure_id: {failure_id}")
        failure_ids.add(failure_id)
        occurred_ns = _integer(failure.get("occurred_ns"), f"{where}.occurred_ns")
        failed_gpus = _string_array(failure.get("failed_gpu_ids"), f"{where}.failed_gpu_ids")
        failed_nodes = _string_array(failure.get("failed_node_ids"), f"{where}.failed_node_ids")
        if not failed_gpus and not failed_nodes:
            raise Qwen3TP4RunnerError(f"{where} must identify at least one failed resource")
        failures = FailureSet(
            failed_gpu_ids=frozenset(failed_gpus),
            failed_node_ids=frozenset(failed_nodes),
        )
        affected = _string_array(
            failure.get("affected_workflow_ids"), f"{where}.affected_workflow_ids"
        )
        if not affected:
            raise Qwen3TP4RunnerError(f"{where}.affected_workflow_ids cannot be empty")
        for workflow_id in affected:
            if workflow_id not in timings:
                raise Qwen3TP4RunnerError(f"unknown affected workflow: {workflow_id}")
            affected_workflows.add(workflow_id)
            affected_pairs.append({"failure_id": failure_id, "workflow_id": workflow_id})

        recovery_rows = _array(failure.get("recoveries"), f"{where}.recoveries")
        for recovery_index, raw_recovery in enumerate(recovery_rows):
            recovery_where = f"{where}.recoveries[{recovery_index}]"
            item = _object(raw_recovery, recovery_where)
            _exact_keys(
                item,
                required={
                    "workflow_id",
                    "logical_chunk_id",
                    "source_dp_rank",
                    "token_count",
                    "route_version",
                    "protection_start_ns",
                    "peer_hbm_available",
                    "store_dram_available",
                    "selected_pool",
                    "recovery_start_ns",
                    "directory_install_ns",
                    "model_forward_all_reduce_bytes_per_rank",
                    "algorithm3_control_events",
                },
                optional={"destination_dp_rank", "peer_activation_ns_by_rank"},
                where=recovery_where,
            )
            workflow_id = _string(item.get("workflow_id"), f"{recovery_where}.workflow_id")
            if workflow_id not in affected:
                raise Qwen3TP4RunnerError(
                    f"{recovery_where}.workflow_id is not affected by {failure_id}"
                )
            logical_chunk_id = _string(
                item.get("logical_chunk_id"), f"{recovery_where}.logical_chunk_id"
            )
            if logical_chunk_id in logical_chunk_ids:
                raise Qwen3TP4RunnerError(f"duplicate logical_chunk_id: {logical_chunk_id}")
            logical_chunk_ids.add(logical_chunk_id)
            token_count = _integer(
                item.get("token_count"), f"{recovery_where}.token_count", positive=True
            )
            source_dp = _integer(item.get("source_dp_rank"), f"{recovery_where}.source_dp_rank")
            route_version = _integer(item.get("route_version"), f"{recovery_where}.route_version")
            protection_start = _integer(
                item.get("protection_start_ns"), f"{recovery_where}.protection_start_ns"
            )
            recovery_start = _integer(
                item.get("recovery_start_ns"), f"{recovery_where}.recovery_start_ns"
            )
            if protection_start > occurred_ns or recovery_start < occurred_ns:
                raise Qwen3TP4RunnerError(
                    f"{recovery_where} protection/recovery does not bracket failure time"
                )
            released_ns, completed_ns = timings[workflow_id]
            if protection_start < released_ns or recovery_start > completed_ns:
                raise Qwen3TP4RunnerError(
                    f"{recovery_where} lies outside explicit workflow lifetime"
                )
            peer_available = _boolean(
                item.get("peer_hbm_available"), f"{recovery_where}.peer_hbm_available"
            )
            store_available = _boolean(
                item.get("store_dram_available"), f"{recovery_where}.store_dram_available"
            )
            pool_text = _string(item.get("selected_pool"), f"{recovery_where}.selected_pool")
            try:
                pool = PolicyPool(pool_text)
            except ValueError as error:
                raise Qwen3TP4RunnerError(
                    f"{recovery_where}.selected_pool must be PEER_HBM or STORE_DRAM"
                ) from error
            if (pool is PolicyPool.PEER_HBM and not peer_available) or (
                pool is PolicyPool.STORE_DRAM and not store_available
            ):
                raise Qwen3TP4RunnerError(f"{recovery_where} selects an unavailable path")
            activation_raw = item.get("peer_activation_ns_by_rank")
            activation: tuple[int, ...] | None = None
            if activation_raw is not None:
                activation_values = _array(
                    activation_raw, f"{recovery_where}.peer_activation_ns_by_rank"
                )
                activation = tuple(
                    _integer(value, f"{recovery_where}.peer_activation_ns_by_rank[]")
                    for value in activation_values
                )
            destination_raw = item.get("destination_dp_rank")
            destination = (
                None
                if destination_raw is None
                else _integer(destination_raw, f"{recovery_where}.destination_dp_rank")
            )
            control_rows = _array(
                item.get("algorithm3_control_events"),
                f"{recovery_where}.algorithm3_control_events",
            )
            if not control_rows:
                raise Qwen3TP4RunnerError(
                    f"{recovery_where}.algorithm3_control_events cannot be empty"
                )
            control_events: list[Algorithm3ControlInput] = []
            for control_index, raw_control in enumerate(control_rows):
                control_where = f"{recovery_where}.algorithm3_control_events[{control_index}]"
                control = _object(raw_control, control_where)
                _exact_keys(
                    control,
                    required={
                        "target_dp_rank",
                        "timestamp_ns",
                        "foreground_pressure",
                        "reason",
                    },
                    where=control_where,
                )
                control_events.append(
                    Algorithm3ControlInput(
                        target_dp_rank=_integer(
                            control.get("target_dp_rank"),
                            f"{control_where}.target_dp_rank",
                        ),
                        timestamp_ns=_integer(
                            control.get("timestamp_ns"),
                            f"{control_where}.timestamp_ns",
                        ),
                        foreground_pressure=_boolean(
                            control.get("foreground_pressure"),
                            f"{control_where}.foreground_pressure",
                        ),
                        reason=_string(control.get("reason"), f"{control_where}.reason"),
                    )
                )
            try:
                recovery = driver.execute_des_failure_recovery(
                    logical_chunk_id=logical_chunk_id,
                    source_dp_rank=source_dp,
                    token_count=token_count,
                    route_version=route_version,
                    protection_start_ns=protection_start,
                    failure_id=failure_id,
                    failure_at_ns=occurred_ns,
                    failures=failures,
                    pool=pool,
                    recovery_start_ns=recovery_start,
                    directory_install_ns=_integer(
                        item.get("directory_install_ns"),
                        f"{recovery_where}.directory_install_ns",
                    ),
                    model_forward_all_reduce_bytes_per_rank=_integer(
                        item.get("model_forward_all_reduce_bytes_per_rank"),
                        f"{recovery_where}.model_forward_all_reduce_bytes_per_rank",
                        positive=True,
                    ),
                    destination_dp_rank=destination,
                    peer_activation_ns_by_rank=activation,
                    peer_control=_path_control(peer_available),
                    store_control=_path_control(store_available),
                    algorithm3_control_events=tuple(control_events),
                )
            except (RuntimeError, ValueError) as error:
                raise Qwen3TP4RunnerError(
                    f"{recovery_where} DES execution failed: {error}"
                ) from error
            if recovery.model_forward_all_reduce.complete_ns > completed_ns:
                raise Qwen3TP4RunnerError(
                    f"{recovery_where} completes after explicit workflow completion"
                )
            if not recovery.byte_audit.valid:
                raise Qwen3TP4RunnerError(f"{recovery_where} failed byte conservation")
            audits.append(
                _recovery_json(
                    failure_id=failure_id,
                    failure_at_ns=occurred_ns,
                    workflow_id=workflow_id,
                    token_count=token_count,
                    peer_available=peer_available,
                    store_available=store_available,
                    recovery=recovery,
                )
            )
    return audits, affected_pairs, affected_workflows


def run_qwen3_32b_tp4_contract(
    *,
    engine_config_path: Path,
    workload_path: Path,
    manifest_path: Path,
    schedule_path: Path | None,
) -> dict[str, object]:
    """Run an exact schedule or raise ``Qwen3TP4RunnerBlocked`` without WCT."""

    config = load_qwen3_32b_tp4_engine_config(engine_config_path)
    config_sha = _sha256(engine_config_path)
    workload = _load_workload(workload_path, manifest_path)
    blocked = _blocked_report(
        config=config,
        config_sha256=config_sha,
        workload=workload,
        workload_path=workload_path,
        manifest_path=manifest_path,
        schedule_path=schedule_path,
    )
    if blocked is not None:
        raise Qwen3TP4RunnerBlocked(blocked)
    assert schedule_path is not None
    schedule = _load_json(schedule_path, kind="execution schedule")
    _exact_keys(
        schedule,
        required={
            "schema",
            "evidence",
            "engine",
            "workload",
            "cell_identity",
            "workflow_timings",
            "failures",
        },
        where="schedule",
    )
    if schedule.get("schema") != SCHEDULE_SCHEMA:
        raise Qwen3TP4RunnerError("unsupported execution schedule schema")
    _validate_evidence(schedule)
    engine = _object(schedule.get("engine"), "schedule.engine")
    _exact_keys(
        engine,
        required={"model_id", "model_revision", "config_sha256"},
        where="schedule.engine",
    )
    if engine != {
        "model_id": config.model.model_id,
        "model_revision": config.model.revision,
        "config_sha256": config_sha,
    }:
        raise Qwen3TP4RunnerError("schedule engine identity/fingerprint mismatch")
    schedule_workload = _object(schedule.get("workload"), "schedule.workload")
    _exact_keys(
        schedule_workload,
        required={"artifact_sha256", "manifest_fingerprint"},
        where="schedule.workload",
    )
    if schedule_workload != {
        "artifact_sha256": workload.artifact_sha256,
        "manifest_fingerprint": workload.manifest_fingerprint,
    }:
        raise Qwen3TP4RunnerError("schedule workload identity/fingerprint mismatch")

    cell = _parse_cell(schedule, len(workload.workflow_ids))
    timings = _parse_timings(schedule, workload)
    audits, affected_pairs, affected_workflows = _parse_failures(
        schedule,
        config=config,
        cell=cell,
        timings=timings,
    )
    wct_by_workflow = {
        workflow_id: completed - released
        for workflow_id, (released, completed) in sorted(timings.items())
    }
    workflow_reuse: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "peer_hbm_available": 0,
            "store_dram_available": 0,
            "peer_hbm_selected": 0,
            "store_dram_selected": 0,
            "recovery_latency_ns": 0,
        }
    )
    for audit in audits:
        workflow_id = str(audit["workflow_id"])
        available = _object(audit["available_reuse_tokens"], "internal.available")
        selected = _object(audit["selected_reuse_tokens"], "internal.selected")
        workflow_reuse[workflow_id]["peer_hbm_available"] += int(available["peer_hbm"])
        workflow_reuse[workflow_id]["store_dram_available"] += int(available["store_dram"])
        workflow_reuse[workflow_id]["peer_hbm_selected"] += int(selected["peer_hbm"])
        workflow_reuse[workflow_id]["store_dram_selected"] += int(selected["store_dram"])
        workflow_reuse[workflow_id]["recovery_latency_ns"] += _integer(
            audit["recovery_latency_ns"], "internal.recovery_latency_ns"
        )
    workflow_results: list[dict[str, object]] = []
    for workflow_id in sorted(timings):
        released, completed = timings[workflow_id]
        reuse = workflow_reuse[workflow_id]
        workflow_results.append(
            {
                "workflow_id": workflow_id,
                "released_ns": released,
                "completed_ns": completed,
                "wct_ns": wct_by_workflow[workflow_id],
                "failure_affected": workflow_id in affected_workflows,
                "peer_hbm_available_reuse_tokens": reuse["peer_hbm_available"],
                "store_dram_available_reuse_tokens": reuse["store_dram_available"],
                "peer_hbm_selected_reuse_tokens": reuse["peer_hbm_selected"],
                "store_dram_selected_reuse_tokens": reuse["store_dram_selected"],
                "recovery_latency_ns": reuse["recovery_latency_ns"],
            }
        )
    recovery_latencies = [
        _integer(audit["recovery_latency_ns"], "internal.recovery_latency_ns") for audit in audits
    ]
    reuse_totals = {
        key: sum(row[key] for row in workflow_reuse.values())
        for key in (
            "peer_hbm_available",
            "store_dram_available",
            "peer_hbm_selected",
            "store_dram_selected",
        )
    }
    failure_focus_spans: list[dict[str, object]] = []
    for audit in audits:
        available = _object(audit["available_reuse_tokens"], "internal.available")
        selected = _object(audit["selected_reuse_tokens"], "internal.selected")
        failure_focus_spans.append(
            {
                "failure_id": audit["failure_id"],
                "failure_at_ns": audit["failure_at_ns"],
                "span_id": audit["logical_chunk_id"],
                "workflow_id": audit["workflow_id"],
                "available_normal_hbm_tokens_at_failure": 0,
                "available_peer_tokens_at_failure": available["peer_hbm"],
                "available_store_tokens_at_failure": available["store_dram"],
                "recovery_normal_hbm_local_tokens": 0,
                "restored_peer_tokens": selected["peer_hbm"],
                "restored_peer_local_tokens": 0,
                "restored_peer_d2d_tokens": selected["peer_hbm"],
                "restored_store_tokens": selected["store_dram"],
                "recovery_ready_ns": audit["kv_recovery_complete_ns"],
            }
        )
    impacted_spans: list[dict[str, object]] = []
    for affected in affected_pairs:
        matching = [
            audit
            for audit in audits
            if audit["failure_id"] == affected["failure_id"]
            and audit["workflow_id"] == affected["workflow_id"]
        ]
        impacted_spans.append(
            {
                **affected,
                "failure_affected": True,
                "recovery_event_count": len(matching),
                "peer_hbm_available_reuse_tokens": sum(
                    _integer(
                        _object(row["available_reuse_tokens"], "internal.available")["peer_hbm"],
                        "internal.available.peer_hbm",
                    )
                    for row in matching
                ),
                "store_dram_available_reuse_tokens": sum(
                    _integer(
                        _object(row["available_reuse_tokens"], "internal.available")["store_dram"],
                        "internal.available.store_dram",
                    )
                    for row in matching
                ),
                "peer_hbm_selected_reuse_tokens": sum(
                    _integer(
                        _object(row["selected_reuse_tokens"], "internal.selected")["peer_hbm"],
                        "internal.selected.peer_hbm",
                    )
                    for row in matching
                ),
                "store_dram_selected_reuse_tokens": sum(
                    _integer(
                        _object(row["selected_reuse_tokens"], "internal.selected")["store_dram"],
                        "internal.selected.store_dram",
                    )
                    for row in matching
                ),
            }
        )
    result: dict[str, object] = {
        "schema": RESULT_SCHEMA,
        "status": "complete",
        "evidence_class": EVIDENCE_CLASS,
        "execution_backend": "GlobalDES",
        "des_execution_complete": all(
            _object(audit["des_execution"], "internal.des_execution").get("recovery_phase")
            == "FORWARD_COMPLETE"
            for audit in audits
        ),
        "algorithm2_four_shard_transaction_surface_executed": bool(audits),
        "algorithm3_peer_quota_surface_enforced": bool(audits)
        and all(
            _boolean(
                _object(audit["des_execution"], "internal.des_execution").get(
                    "algorithm3_peer_quota_surface_enforced"
                ),
                "internal.algorithm3_peer_quota_surface_enforced",
            )
            for audit in audits
        ),
        "algorithm3_controller_integration": (
            "per_dp_rank_global_des_aimd"
            if audits
            and all(
                _object(audit["des_execution"], "internal.des_execution").get(
                    "algorithm3_controller_integration"
                )
                == "per_dp_rank_global_des_aimd"
                for audit in audits
            )
            else "not_executed"
        ),
        "paper_ready": False,
        "calibrated": False,
        "physical_measurement_completed": False,
        "trend_generation_performed": False,
        "failure_count": cell["failure_count"],
        "workflow_concurrency": cell["workflow_concurrency"],
        "cell_id": cell["cell_id"],
        "seed": cell["seed"],
        "cell_identity": cell,
        "engine": {
            "model_id": config.model.model_id,
            "model_revision": config.model.revision,
            "data_parallel_size": config.parallelism.data_parallel_size,
            "tensor_parallel_size": config.parallelism.tensor_parallel_size,
            "config_sha256": config_sha,
        },
        "workload": {
            "artifact_sha256": workload.artifact_sha256,
            "manifest_sha256": workload.manifest_sha256,
            "manifest_fingerprint": workload.manifest_fingerprint,
            "record_count": workload.record_count,
            "workflow_count": len(workload.workflow_ids),
        },
        "metrics": {
            "workflow_completion_time_ns": {
                **_metric(list(wct_by_workflow.values())),
                "by_workflow_id": wct_by_workflow,
            },
            "recovery_latency_ns": _metric(recovery_latencies),
            "cache_reuse_tokens": {
                "normal_hbm": 0,
                "peer_hbm": reuse_totals["peer_hbm_selected"],
                "store_dram": reuse_totals["store_dram_selected"],
                "peer_hbm_available": reuse_totals["peer_hbm_available"],
                "store_dram_available": reuse_totals["store_dram_available"],
                "peer_hbm_selected": reuse_totals["peer_hbm_selected"],
                "store_dram_selected": reuse_totals["store_dram_selected"],
            },
            "restored_tokens": {
                "peer_hbm": reuse_totals["peer_hbm_selected"],
                "store_dram": reuse_totals["store_dram_selected"],
                "total": (reuse_totals["peer_hbm_selected"] + reuse_totals["store_dram_selected"]),
            },
            "failure_impact": {
                "failure_event_count": cell["failure_count"],
                "affected_workflow_count": len(affected_workflows),
            },
        },
        "workflow_results": workflow_results,
        "failure_focus_spans": sorted(
            failure_focus_spans,
            key=lambda row: (str(row["failure_id"]), str(row["span_id"])),
        ),
        "failure_impacted_spans": sorted(
            impacted_spans,
            key=lambda row: (str(row["failure_id"]), str(row["workflow_id"])),
        ),
        "recovery_audit": audits,
    }
    result["fingerprint"] = _canonical_hash(result)
    return result


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    if path.is_symlink():
        raise Qwen3TP4RunnerError(f"output symlinks are forbidden: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    path.write_text(payload + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    root = repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--engine-config",
        type=Path,
        default=default_qwen3_32b_tp4_config_path(root),
    )
    parser.add_argument("--workload", type=Path, default=root / DEFAULT_WORKLOAD_RELATIVE_PATH)
    parser.add_argument("--manifest", type=Path, default=root / DEFAULT_MANIFEST_RELATIVE_PATH)
    parser.add_argument("--execution-schedule", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_qwen3_32b_tp4_contract(
            engine_config_path=args.engine_config,
            workload_path=args.workload,
            manifest_path=args.manifest,
            schedule_path=args.execution_schedule,
        )
    except Qwen3TP4RunnerBlocked as error:
        _write_json(args.output, error.report)
        print("BLOCKED: missing exact Qwen3-32B execution evidence", file=sys.stderr)
        return 2
    except Qwen3TP4RunnerError as error:
        report: dict[str, object] = {
            "schema": GATE_SCHEMA,
            "status": "ERROR",
            "evidence_class": EVIDENCE_CLASS,
            "result_rows_written": 0,
            "wct_emitted": False,
            "trend_generation_performed": False,
            "error": str(error),
        }
        _write_json(args.output, report)
        print(f"ERROR: {error}", file=sys.stderr)
        return 3
    _write_json(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_MANIFEST_RELATIVE_PATH",
    "DEFAULT_WORKLOAD_RELATIVE_PATH",
    "EVIDENCE_CLASS",
    "GATE_SCHEMA",
    "RESULT_SCHEMA",
    "SCHEDULE_SCHEMA",
    "Qwen3TP4RunnerBlocked",
    "Qwen3TP4RunnerError",
    "WorkloadIdentity",
    "main",
    "run_qwen3_32b_tp4_contract",
]
