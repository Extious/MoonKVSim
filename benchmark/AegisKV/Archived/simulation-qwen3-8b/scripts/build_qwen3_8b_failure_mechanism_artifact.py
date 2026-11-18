#!/usr/bin/env python3
"""Build a fail-closed Qwen3-8B failure-mechanism artifact.

The input detailed rerun is intentionally separate from the compact paper sweep.
This builder accepts it only when every full-content hash is identical to the
formal F=2, C=16 raw seed cell embedded in the paper-sweep aggregate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

from moonkvsim.common.hash import sha256_json

AGGREGATE_SCHEMA: Final = "moonkvsim.aegiskv.paper_sweeps.v4"
RERUN_SCHEMA: Final = "moonkvsim.aegiskv.qwen3_8b.failure_mechanism_rerun.v1"
ARTIFACT_SCHEMA: Final = "moonkvsim.aegiskv.qwen3_8b.failure_mechanism.v1"
MOONCAKE: Final = "vanilla_mooncake_dram"
AEGISKV: Final = "aegiskv_unified"
SYSTEMS: Final = (MOONCAKE, AEGISKV)
BASE_FAILURE_COUNT: Final = 2
BASE_CONCURRENCY: Final = 16
MODEL_ID: Final = "Qwen/Qwen3-8B"
FORBIDDEN_LABELS: Final = (
    "Projected",
    "Simulation projection",
    "No-measured",
)


class MechanismArtifactError(ValueError):
    """The mechanism input cannot support an exact descriptive artifact."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--detailed-rerun", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MechanismArtifactError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MechanismArtifactError(f"{where} must be an array")
    return value


def _text(value: object, where: str) -> str:
    if type(value) is not str or not value:
        raise MechanismArtifactError(f"{where} must be a non-empty string")
    return value


def _integer(value: object, where: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise MechanismArtifactError(f"{where} must be an integer >= {minimum}")
    return value


def _optional_integer(value: object, where: str) -> int | None:
    if value is None:
        return None
    return _integer(value, where)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_fingerprint(document: Mapping[str, Any], where: str) -> str:
    fingerprint = _text(document.get("fingerprint"), f"{where}.fingerprint")
    unsigned = dict(document)
    unsigned.pop("fingerprint", None)
    if fingerprint != sha256_json(unsigned):
        raise MechanismArtifactError(f"{where} fingerprint mismatch")
    return fingerprint


def _load_json(path: Path, where: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MechanismArtifactError(f"cannot read {where}: {error}") from error
    return dict(_mapping(value, where))


def _load_workload(path: Path) -> tuple[dict[str, Mapping[str, Any]], int]:
    records: dict[str, Mapping[str, Any]] = {}
    workflow_ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise MechanismArtifactError(f"cannot read workload: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise MechanismArtifactError(f"workload line {line_number} is blank")
        try:
            record = _mapping(json.loads(line), f"workload line {line_number}")
        except json.JSONDecodeError as error:
            raise MechanismArtifactError(
                f"workload line {line_number} is invalid JSON: {error}"
            ) from error
        span_id = _text(record.get("span_id"), f"workload line {line_number}.span_id")
        workflow_id = _text(record.get("workflow_id"), f"workload line {line_number}.workflow_id")
        _integer(record.get("prompt_tokens"), f"workload line {line_number}.prompt_tokens")
        _integer(record.get("output_tokens"), f"workload line {line_number}.output_tokens")
        if span_id in records:
            raise MechanismArtifactError(f"duplicate workload span_id {span_id}")
        records[span_id] = record
        workflow_ids.add(workflow_id)
    if not records:
        raise MechanismArtifactError("workload is empty")
    if len(workflow_ids) != 160:
        raise MechanismArtifactError("mechanism workload must contain exactly 160 workflows")
    return records, len(workflow_ids)


def _base_seed_cell(aggregate: Mapping[str, Any], seed: int) -> Mapping[str, Any]:
    matches = [
        _mapping(raw, "aggregate.raw_seed_cells[]")
        for raw in _array(aggregate.get("raw_seed_cells"), "aggregate.raw_seed_cells")
        if isinstance(raw, Mapping)
        and raw.get("failure_count") == BASE_FAILURE_COUNT
        and raw.get("workflow_concurrency") == BASE_CONCURRENCY
        and raw.get("seed") == seed
    ]
    if len(matches) != 1:
        raise MechanismArtifactError(
            f"expected exactly one formal F=2,C=16 raw cell for seed {seed}"
        )
    return matches[0]


def _validate_aggregate(aggregate: Mapping[str, Any]) -> str:
    if aggregate.get("schema") != AGGREGATE_SCHEMA or aggregate.get("status") != "PASS":
        raise MechanismArtifactError("aggregate must be a PASS paper-sweeps v4 artifact")
    fingerprint = _validate_fingerprint(aggregate, "aggregate")
    protocol = _mapping(aggregate.get("protocol"), "aggregate.protocol")
    if (
        protocol.get("base_failure_count") != BASE_FAILURE_COUNT
        or protocol.get("base_workflow_concurrency") != BASE_CONCURRENCY
        or protocol.get("workflow_count") != 160
        or protocol.get("model") != MODEL_ID
        or protocol.get("dp") != 8
    ):
        raise MechanismArtifactError("aggregate base Qwen3-8B DP=8 protocol mismatch")
    evidence = _mapping(aggregate.get("evidence"), "aggregate.evidence")
    if evidence.get("physical_execution") is not False or evidence.get("paper_ready") is not False:
        raise MechanismArtifactError("mechanism figures require modeled uncalibrated evidence")
    return fingerprint


def _validate_rerun_protocol(
    rerun: Mapping[str, Any],
    *,
    aggregate_fingerprint: str,
) -> int:
    if rerun.get("schema") != RERUN_SCHEMA or rerun.get("status") != "PASS":
        raise MechanismArtifactError("detailed rerun schema/status mismatch")
    _validate_fingerprint(rerun, "detailed_rerun")
    protocol = _mapping(rerun.get("protocol"), "detailed_rerun.protocol")
    if (
        protocol.get("model") != MODEL_ID
        or protocol.get("dp") != 8
        or protocol.get("failure_count") != BASE_FAILURE_COUNT
        or protocol.get("workflow_concurrency") != BASE_CONCURRENCY
        or protocol.get("scenario") != "gpu_failure"
        or protocol.get("repetition") != "A"
        or protocol.get("modeled_uncalibrated") is not True
    ):
        raise MechanismArtifactError("detailed rerun protocol is not base F=2,C=16")
    seed = _integer(protocol.get("seed"), "detailed_rerun.protocol.seed")
    aggregate_binding = _mapping(rerun.get("formal_aggregate"), "detailed_rerun.formal_aggregate")
    if (
        aggregate_binding.get("schema") != AGGREGATE_SCHEMA
        or aggregate_binding.get("fingerprint") != aggregate_fingerprint
    ):
        raise MechanismArtifactError("detailed rerun is not bound to the supplied aggregate")
    return seed


def _by_span(rows: object, where: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(_array(rows, where)):
        row = _mapping(raw, f"{where}[{index}]")
        span_id = _text(row.get("span_id"), f"{where}[{index}].span_id")
        if span_id in result:
            raise MechanismArtifactError(f"{where} has duplicate span_id {span_id}")
        result[span_id] = row
    return result


def _event_for_span(
    rows: object,
    *,
    span_id: str,
    event_name: str,
    where: str,
    required: bool = True,
) -> Mapping[str, Any] | None:
    matches = [
        row
        for row in (_mapping(raw, f"{where}[]") for raw in _array(rows, where))
        if row.get("span_id") == span_id and row.get("event") == event_name
    ]
    if len(matches) > 1 or (required and len(matches) != 1):
        raise MechanismArtifactError(
            f"{where} expected {'one' if required else 'at most one'} "
            f"{event_name} for {span_id}, found {len(matches)}"
        )
    return matches[0] if matches else None


def _failure_event_for_span(representative: Mapping[str, Any], span_id: str) -> Mapping[str, Any]:
    matches = []
    for raw in _array(representative.get("failure_events"), "representative.failure_events"):
        event = _mapping(raw, "representative.failure_events[]")
        trigger = _mapping(event.get("logical_trigger"), "failure.logical_trigger")
        if trigger.get("focus_span_id") == span_id:
            matches.append(event)
    if len(matches) != 1:
        raise MechanismArtifactError(
            f"expected one logical focus failure event for {span_id}, found {len(matches)}"
        )
    return matches[0]


def _merge_interval_length(intervals: Sequence[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(intervals)
    total = 0
    start, end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def _pre_failure_progress(
    representative: Mapping[str, Any],
    *,
    span_id: str,
    failure_event: Mapping[str, Any],
) -> dict[str, Any]:
    failure_ns = _integer(failure_event.get("timestamp_ns"), "failure.timestamp_ns")
    scheduler = _mapping(
        representative.get("continuous_batch_scheduler"),
        "representative.continuous_batch_scheduler",
    )
    intervals: list[tuple[int, int]] = []
    first_start: int | None = None
    for step_index, raw_step in enumerate(
        _array(scheduler.get("steps"), "continuous_batch_scheduler.steps")
    ):
        step = _mapping(raw_step, f"continuous_batch_scheduler.steps[{step_index}]")
        participants = [
            _mapping(raw, "step.participants[]")
            for raw in _array(step.get("participants"), "step.participants")
        ]
        if not any(
            participant.get("request_id") == span_id and participant.get("route_version") == 0
            for participant in participants
        ):
            continue
        start = _integer(step.get("start_ns"), "step.start_ns")
        effective_end = _optional_integer(step.get("effective_end_ns"), "step.effective_end_ns")
        if effective_end is None:
            raise MechanismArtifactError("focus scheduler step lacks effective_end_ns")
        if effective_end < start:
            raise MechanismArtifactError("focus scheduler step has negative duration")
        if start < failure_ns:
            first_start = start if first_start is None else min(first_start, start)
            intervals.append((start, min(failure_ns, effective_end)))
    if first_start is None:
        raise MechanismArtifactError(f"no route-0 compute step precedes failure for {span_id}")

    trigger = _mapping(failure_event.get("logical_trigger"), "failure.logical_trigger")
    evidence = _mapping(
        trigger.get("continuous_progress_evidence"),
        "failure.logical_trigger.continuous_progress_evidence",
    )
    if (
        evidence.get("kind") != "CONTINUOUS_SCHEDULER_TOKEN_PROGRESS"
        or evidence.get("route_version") != 0
        or evidence.get("resolved_at_ns") != failure_ns
    ):
        raise MechanismArtifactError("focus failure lacks route-0 token progress evidence")
    step_start = _integer(evidence.get("step_start_ns"), "progress.step_start_ns")
    step_end = _integer(evidence.get("step_end_ns"), "progress.step_end_ns")
    before = _integer(
        evidence.get("num_computed_tokens_before"), "progress.num_computed_tokens_before"
    )
    after = _integer(
        evidence.get("num_computed_tokens_after"), "progress.num_computed_tokens_after"
    )
    if not (step_start <= failure_ns <= step_end) or after <= before or step_end <= step_start:
        raise MechanismArtifactError("focus failure progress interpolation bounds are invalid")
    computed_floor = before + (after - before) * (failure_ns - step_start) // (
        step_end - step_start
    )
    total_tokens = _integer(
        evidence.get("total_request_tokens"), "progress.total_request_tokens", minimum=1
    )
    if computed_floor > total_tokens:
        raise MechanismArtifactError("computed token progress exceeds request tokens")

    failures = [
        _mapping(raw, "continuous_batch_scheduler.failures[]")
        for raw in _array(scheduler.get("failures"), "continuous_batch_scheduler.failures")
        if isinstance(raw, Mapping) and raw.get("timestamp_ns") == failure_ns
    ]
    matching_failures = [
        item
        for item in failures
        if span_id
        in _mapping(
            item.get("router_committed_outputs_before_requeue"),
            "driver_failure.router_committed_outputs_before_requeue",
        )
    ]
    if len(matching_failures) != 1:
        raise MechanismArtifactError("driver failure snapshot is missing focus output progress")
    committed_outputs = _integer(
        _mapping(
            matching_failures[0].get("router_committed_outputs_before_requeue"),
            "driver_failure.router_committed_outputs_before_requeue",
        ).get(span_id),
        "driver_failure.committed_output_tokens",
    )
    return {
        "initial_compute_start_ns": first_start,
        "pre_failure_elapsed_ns": failure_ns - first_start,
        "pre_failure_compute_active_ns": _merge_interval_length(intervals),
        "computed_tokens_at_failure_floor": computed_floor,
        "total_request_tokens": total_tokens,
        "committed_output_tokens_at_failure": committed_outputs,
        "progress_interpolation": {
            "rounding": "floor",
            "step_start_ns": step_start,
            "step_end_ns": step_end,
            "num_computed_tokens_before": before,
            "num_computed_tokens_after": after,
            "failure_at_ns": failure_ns,
        },
    }


def _recovery_transfers(
    representative: Mapping[str, Any],
    *,
    span_id: str,
    materialized_ns: int,
) -> list[dict[str, Any]]:
    result = []
    for index, raw in enumerate(
        _array(representative.get("transfers"), "representative.transfers")
    ):
        transfer = _mapping(raw, f"representative.transfers[{index}]")
        if transfer.get("span_id") != span_id:
            continue
        cause = transfer.get("cause")
        if cause not in {"AEGIS_RECOVERY_PEER_HBM", "AEGIS_RECOVERY_STORE_DRAM"}:
            continue
        ready = _integer(transfer.get("ready_ns"), "recovery_transfer.ready_ns")
        start = _integer(transfer.get("start_ns"), "recovery_transfer.start_ns")
        end = _integer(transfer.get("end_ns"), "recovery_transfer.end_ns")
        terminal = _integer(transfer.get("terminal_ns"), "recovery_transfer.terminal_ns")
        transferred = _integer(
            transfer.get("transferred_bytes"), "recovery_transfer.transferred_bytes"
        )
        total_bytes = _integer(transfer.get("bytes"), "recovery_transfer.bytes", minimum=1)
        if (
            transfer.get("status") != "COMMITTED"
            or transfer.get("aborted_bytes") != 0
            or transferred != total_bytes
            or not (ready <= start <= end == terminal <= materialized_ns)
        ):
            raise MechanismArtifactError("recovery transfer is not a committed causal interval")
        result.append(
            {
                "transfer_id": _text(transfer.get("transfer_id"), "recovery_transfer.transfer_id"),
                "source": "peer_hbm" if cause == "AEGIS_RECOVERY_PEER_HBM" else "store_dram",
                "ready_ns": ready,
                "start_ns": start,
                "end_ns": end,
                "bytes": total_bytes,
            }
        )
    return sorted(result, key=lambda item: (item["start_ns"], item["source"], item["transfer_id"]))


def _phase_record(
    *,
    system_id: str,
    span_id: str,
    detail: Mapping[str, Any],
    representative: Mapping[str, Any],
    workload_record: Mapping[str, Any],
) -> dict[str, Any]:
    workflow_id = _text(detail.get("workflow_id"), f"{system_id}.{span_id}.workflow_id")
    if workflow_id != workload_record.get("workflow_id"):
        raise MechanismArtifactError(f"{system_id}.{span_id} workflow identity mismatch")
    prompt_tokens = _integer(
        workload_record.get("prompt_tokens"), f"workload.{span_id}.prompt_tokens"
    )
    output_tokens = _integer(
        workload_record.get("output_tokens"), f"workload.{span_id}.output_tokens"
    )
    if detail.get("output_tokens") != output_tokens:
        raise MechanismArtifactError(f"{system_id}.{span_id} output token mismatch")

    failure_event = _failure_event_for_span(representative, span_id)
    failure_ns = _integer(detail.get("failure_at_ns"), f"{system_id}.{span_id}.failure_at_ns")
    if failure_event.get("timestamp_ns") != failure_ns:
        raise MechanismArtifactError(f"{system_id}.{span_id} failure timestamp mismatch")
    completed_ns = _integer(detail.get("completed_ns"), f"{system_id}.{span_id}.completed_ns")
    released_ns = _integer(detail.get("released_ns"), f"{system_id}.{span_id}.released_ns")
    prompt_start = _integer(
        detail.get("prompt_recompute_start_ns"), f"{system_id}.{span_id}.prompt_recompute_start_ns"
    )
    prompt_complete = _integer(
        detail.get("prompt_recompute_complete_ns"),
        f"{system_id}.{span_id}.prompt_recompute_complete_ns",
    )
    silent_start = _integer(
        detail.get("silent_replay_start_ns"), f"{system_id}.{span_id}.silent_replay_start_ns"
    )
    silent_complete = _integer(
        detail.get("silent_replay_complete_ns"),
        f"{system_id}.{span_id}.silent_replay_complete_ns",
    )
    recovery_ready = _integer(
        detail.get("recovery_ready_ns"), f"{system_id}.{span_id}.recovery_ready_ns"
    )
    resume_start = _integer(
        detail.get("resume_decode_start_ns"), f"{system_id}.{span_id}.resume_decode_start_ns"
    )
    if not (
        released_ns
        <= failure_ns
        <= prompt_start
        <= prompt_complete
        <= silent_start
        <= silent_complete
        == recovery_ready
        <= resume_start
        <= completed_ns
    ):
        raise MechanismArtifactError(f"{system_id}.{span_id} recovery phase order is invalid")
    progress = _pre_failure_progress(
        representative,
        span_id=span_id,
        failure_event=failure_event,
    )

    recovery_events = representative.get("recovery_events")
    plan = _event_for_span(
        recovery_events,
        span_id=span_id,
        event_name="RECOVERY_PLAN",
        where="representative.recovery_events",
    )
    assert plan is not None
    plan_ns = _integer(plan.get("timestamp_ns"), "recovery_plan.timestamp_ns")
    materialized = _event_for_span(
        recovery_events,
        span_id=span_id,
        event_name="CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED",
        where="representative.recovery_events",
    )
    assert materialized is not None
    materialized_ns = _integer(materialized.get("timestamp_ns"), "materialized.timestamp_ns")
    start_event = _event_for_span(
        recovery_events,
        span_id=span_id,
        event_name="PROMPT_SUFFIX_RECOMPUTE_START",
        where="representative.recovery_events",
    )
    complete_event = _event_for_span(
        recovery_events,
        span_id=span_id,
        event_name="PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
        where="representative.recovery_events",
    )
    silent_start_event = _event_for_span(
        recovery_events,
        span_id=span_id,
        event_name="SILENT_REPLAY_START",
        where="representative.recovery_events",
        required=False,
    )
    silent_complete_event = _event_for_span(
        recovery_events,
        span_id=span_id,
        event_name="SILENT_REPLAY_COMPLETE",
        where="representative.recovery_events",
    )
    assert start_event and complete_event and silent_complete_event
    committed_output_tokens = _integer(
        progress["committed_output_tokens_at_failure"],
        "pre_failure.committed_output_tokens_at_failure",
    )
    if committed_output_tokens > 0 and silent_start_event is None:
        raise MechanismArtifactError(
            f"{system_id}.{span_id} lacks the non-empty silent replay start event"
        )
    if committed_output_tokens == 0 and silent_start != silent_complete:
        raise MechanismArtifactError(
            f"{system_id}.{span_id} assigns latency to an empty silent replay"
        )
    expected_event_times = [
        (start_event, prompt_start),
        (complete_event, prompt_complete),
        (silent_complete_event, silent_complete),
    ]
    if silent_start_event is not None:
        expected_event_times.append((silent_start_event, silent_start))
    if any(event.get("timestamp_ns") != timestamp for event, timestamp in expected_event_times):
        raise MechanismArtifactError(f"{system_id}.{span_id} recovery event/detail mismatch")

    primary_tokens = _integer(
        detail.get("recovery_normal_hbm_local_tokens"),
        f"{system_id}.{span_id}.recovery_normal_hbm_local_tokens",
    )
    peer_tokens = _integer(
        detail.get("restored_peer_tokens"), f"{system_id}.{span_id}.restored_peer_tokens"
    )
    peer_local_tokens = _integer(
        detail.get("restored_peer_local_tokens"),
        f"{system_id}.{span_id}.restored_peer_local_tokens",
    )
    peer_d2d_tokens = _integer(
        detail.get("restored_peer_d2d_tokens"),
        f"{system_id}.{span_id}.restored_peer_d2d_tokens",
    )
    store_tokens = _integer(
        detail.get("restored_store_tokens"), f"{system_id}.{span_id}.restored_store_tokens"
    )
    recompute_tokens = _integer(
        detail.get("recompute_tokens"), f"{system_id}.{span_id}.recompute_tokens"
    )
    if (
        primary_tokens + peer_tokens + store_tokens + recompute_tokens != prompt_tokens
        or peer_local_tokens + peer_d2d_tokens != peer_tokens
    ):
        raise MechanismArtifactError(f"{system_id}.{span_id} recovery token conservation failed")
    source_tokens = _mapping(plan.get("source_tokens"), "recovery_plan.source_tokens")
    if source_tokens != {
        "NORMAL_HBM_LOCAL": primary_tokens,
        "PEER_HBM": peer_tokens,
        "STORE_DRAM": store_tokens,
        "RECOMPUTE": recompute_tokens,
    }:
        raise MechanismArtifactError(f"{system_id}.{span_id} plan/detail source tokens diverged")

    transfers = _recovery_transfers(
        representative, span_id=span_id, materialized_ns=materialized_ns
    )
    peer_transfers = [item for item in transfers if item["source"] == "peer_hbm"]
    store_transfers = [item for item in transfers if item["source"] == "store_dram"]
    if bool(peer_transfers) != (peer_d2d_tokens > 0):
        raise MechanismArtifactError(f"{system_id}.{span_id} Peer-HBM transfer evidence mismatch")
    if bool(store_transfers) != (store_tokens > 0):
        raise MechanismArtifactError(f"{system_id}.{span_id} Store transfer evidence mismatch")

    source_events = representative.get("recovery_source_events")
    normal_local = _event_for_span(
        source_events,
        span_id=span_id,
        event_name="NORMAL_HBM_LOCAL_ADOPTION",
        where="representative.recovery_source_events",
        required=primary_tokens > 0,
    )
    peer_local = _event_for_span(
        source_events,
        span_id=span_id,
        event_name="PEER_HBM_LOCAL_ACTIVATION",
        where="representative.recovery_source_events",
        required=peer_local_tokens > 0,
    )
    if primary_tokens == 0 and normal_local is not None:
        raise MechanismArtifactError(f"{system_id}.{span_id} has zero-token normal-HBM adoption")
    if peer_local_tokens == 0 and peer_local is not None:
        raise MechanismArtifactError(f"{system_id}.{span_id} has zero-token local Peer adoption")

    route_ready_ns = (
        min(_integer(item["ready_ns"], "transfer.ready_ns") for item in transfers)
        if transfers
        else materialized_ns
    )
    if not (failure_ns <= plan_ns <= route_ready_ns <= materialized_ns <= prompt_start):
        raise MechanismArtifactError(f"{system_id}.{span_id} detection/restore order is invalid")
    phases = {
        "detection_ns": plan_ns - failure_ns,
        "reroute_setup_ns": route_ready_ns - plan_ns,
        "kv_recall_critical_path_ns": materialized_ns - route_ready_ns,
        "retry_compute_queue_ns": prompt_start - materialized_ns,
        "prompt_recompute_ns": prompt_complete - prompt_start,
        "silent_replay_queue_ns": silent_start - prompt_complete,
        "silent_replay_ns": silent_complete - silent_start,
        "activation_resume_gap_ns": resume_start - silent_complete,
        "resumed_inference_ns": completed_ns - resume_start,
    }
    failure_to_completion = completed_ns - failure_ns
    if sum(phases.values()) != failure_to_completion:
        raise MechanismArtifactError(
            f"{system_id}.{span_id} exclusive phases do not conserve latency"
        )
    combined_retry = (
        phases["detection_ns"]
        + phases["reroute_setup_ns"]
        + phases["retry_compute_queue_ns"]
        + phases["silent_replay_queue_ns"]
        + phases["activation_resume_gap_ns"]
    )
    return {
        "system_id": system_id,
        "span_id": span_id,
        "workflow_id": workflow_id,
        "route_version": _integer(
            detail.get("route_version"), f"{system_id}.{span_id}.route_version", minimum=1
        ),
        "prompt_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "released_ns": released_ns,
        "failure_at_ns": failure_ns,
        "recovery_plan_ns": plan_ns,
        "route_ready_ns": route_ready_ns,
        "prefix_materialized_ns": materialized_ns,
        "prompt_recompute_start_ns": prompt_start,
        "prompt_recompute_complete_ns": prompt_complete,
        "silent_replay_start_ns": silent_start,
        "silent_replay_complete_ns": silent_complete,
        "recovery_ready_ns": recovery_ready,
        "resume_inference_start_ns": resume_start,
        "completed_ns": completed_ns,
        "failure_to_completion_ns": failure_to_completion,
        "pre_failure": progress,
        "exclusive_latency_phases_ns": phases,
        "detection_routing_retry_ns": combined_retry,
        "recovery_tokens": {
            "normal_hbm_local": primary_tokens,
            "peer_hbm": peer_tokens,
            "peer_hbm_local_zero_copy": peer_local_tokens,
            "peer_hbm_d2d": peer_d2d_tokens,
            "store_dram": store_tokens,
            "prompt_recompute": recompute_tokens,
            "total_prompt": prompt_tokens,
        },
        "source_transfer_intervals": transfers,
        "source_windows_are_parallel_non_additive": True,
        "local_adoptions": [
            *(
                [
                    {
                        "source": "normal_hbm_local",
                        "timestamp_ns": _integer(
                            normal_local.get("timestamp_ns"), "normal_local.timestamp_ns"
                        ),
                        "tokens": primary_tokens,
                        "transferred_bytes": 0,
                    }
                ]
                if normal_local is not None
                else []
            ),
            *(
                [
                    {
                        "source": "peer_hbm_local_zero_copy",
                        "timestamp_ns": _integer(
                            peer_local.get("timestamp_ns"), "peer_local.timestamp_ns"
                        ),
                        "tokens": peer_local_tokens,
                        "transferred_bytes": 0,
                    }
                ]
                if peer_local is not None
                else []
            ),
        ],
    }


def build_mechanism_artifact(
    *,
    aggregate_path: Path,
    detailed_rerun_path: Path,
    workload_path: Path,
) -> dict[str, Any]:
    aggregate = _load_json(aggregate_path, "aggregate")
    aggregate_fingerprint = _validate_aggregate(aggregate)
    rerun = _load_json(detailed_rerun_path, "detailed_rerun")
    seed = _validate_rerun_protocol(
        rerun,
        aggregate_fingerprint=aggregate_fingerprint,
    )
    base_cell = _base_seed_cell(aggregate, seed)
    records, workflow_count = _load_workload(workload_path)
    aggregate_workload = _mapping(
        _mapping(aggregate.get("provenance"), "aggregate.provenance").get("workload"),
        "aggregate.provenance.workload",
    )
    workload_sha256 = _sha256_file(workload_path)
    rerun_workload = _mapping(rerun.get("workload"), "detailed_rerun.workload")
    if (
        workload_sha256 != aggregate_workload.get("sha256")
        or workload_sha256 != rerun_workload.get("sha256")
        or len(records) != aggregate_workload.get("record_count")
        or len(records) != rerun_workload.get("record_count")
        or base_cell.get("workload_fingerprint") != aggregate_workload.get("semantic_fingerprint")
        or rerun_workload.get("semantic_fingerprint")
        != aggregate_workload.get("semantic_fingerprint")
    ):
        raise MechanismArtifactError("workload content/semantic binding mismatch")

    focus_by_system = _mapping(
        base_cell.get("failure_focus_span_ids_by_system"),
        "base_cell.failure_focus_span_ids_by_system",
    )
    focus_ids = focus_by_system.get(MOONCAKE)
    if (
        not isinstance(focus_ids, list)
        or len(focus_ids) != BASE_FAILURE_COUNT
        or len(set(focus_ids)) != BASE_FAILURE_COUNT
        or focus_by_system.get(AEGISKV) != focus_ids
    ):
        raise MechanismArtifactError("formal base cell has unaligned focus IDs")
    if any(span_id not in records for span_id in focus_ids):
        raise MechanismArtifactError("formal focus span is absent from the frozen workload")

    aggregate_systems = _mapping(base_cell.get("systems"), "base_cell.systems")
    rerun_systems = _mapping(rerun.get("systems"), "detailed_rerun.systems")
    if set(rerun_systems) != set(SYSTEMS):
        raise MechanismArtifactError("detailed rerun must contain exactly Mooncake and AegisKV")
    observations: list[dict[str, Any]] = []
    content_bindings: dict[str, Any] = {}
    for system_id in SYSTEMS:
        compact = _mapping(aggregate_systems.get(system_id), f"base_cell.systems.{system_id}")
        detailed = _mapping(rerun_systems.get(system_id), f"detailed_rerun.systems.{system_id}")
        compact_run = _mapping(compact.get("run"), f"compact.{system_id}.run")
        payload = _mapping(detailed.get("payload"), f"detailed.{system_id}.payload")
        span_details_value = _array(
            detailed.get("span_details"), f"detailed.{system_id}.span_details"
        )
        representative = _mapping(
            detailed.get("representative"), f"detailed.{system_id}.representative"
        )
        if (
            detailed.get("variant_id") != system_id
            or detailed.get("variant_fingerprint") != compact.get("variant_fingerprint")
            or payload.get("variant_fingerprint") != compact.get("variant_fingerprint")
            or detailed.get("failure_schedule") != compact.get("failure_schedule")
            or payload.get("failure_schedule") != compact.get("failure_schedule")
            or detailed.get("failure_schedule_fingerprint")
            != compact.get("failure_schedule_fingerprint")
            or payload.get("scenario") != "gpu_failure"
        ):
            raise MechanismArtifactError(f"{system_id} variant/schedule binding mismatch")
        content_hashes = {
            "payload_sha256": sha256_json(payload),
            "span_details_sha256": sha256_json(span_details_value),
            "representative_sha256": sha256_json(representative),
        }
        for field, computed in content_hashes.items():
            if detailed.get(field) != computed or compact_run.get(field) != computed:
                raise MechanismArtifactError(
                    f"{system_id} {field} does not match the formal aggregate"
                )
        journal_sha256 = _text(
            detailed.get("journal_sha256"), f"detailed.{system_id}.journal_sha256"
        )
        if compact_run.get("journal_sha256") != journal_sha256:
            raise MechanismArtifactError(f"{system_id} journal hash mismatch")
        workload_payload = _mapping(payload.get("workload"), f"payload.{system_id}.workload")
        if workload_payload.get("workflow_count") != workflow_count:
            raise MechanismArtifactError(f"{system_id} payload workflow count mismatch")
        details = _by_span(span_details_value, f"detailed.{system_id}.span_details")
        if set(focus_ids) - set(details):
            raise MechanismArtifactError(f"{system_id} is missing formal focus span details")
        for span_id in focus_ids:
            observations.append(
                _phase_record(
                    system_id=system_id,
                    span_id=span_id,
                    detail=details[span_id],
                    representative=representative,
                    workload_record=records[span_id],
                )
            )
        content_bindings[system_id] = {
            **content_hashes,
            "journal_sha256": journal_sha256,
            "variant_fingerprint": detailed["variant_fingerprint"],
            "failure_schedule_fingerprint": detailed["failure_schedule_fingerprint"],
            "aggregate_run_content_binding": _mapping(
                _mapping(
                    base_cell.get("run_content_bindings"),
                    "base_cell.run_content_bindings",
                ).get(system_id),
                f"base_cell.run_content_bindings.{system_id}",
            ),
        }

    observations.sort(
        key=lambda item: (focus_ids.index(item["span_id"]), SYSTEMS.index(item["system_id"]))
    )
    body: dict[str, Any] = {
        "schema": ARTIFACT_SCHEMA,
        "status": "PASS",
        "protocol": {
            "model": MODEL_ID,
            "dp": 8,
            "failure_count": BASE_FAILURE_COUNT,
            "workflow_concurrency": BASE_CONCURRENCY,
            "seed": seed,
            "repetition": "A",
            "focus_span_ids": list(focus_ids),
            "focus_observation_count": len(observations),
        },
        "evidence": {
            "class": "E2",
            "physical_execution": False,
            "calibrated": False,
            "paper_ready": False,
            "observed_values_only": True,
            "trend_generation_performed": False,
            "source_windows_parallel_non_additive": True,
            "exclusive_latency_phases_conserve_failure_to_completion": True,
        },
        "source_bindings": {
            "aggregate_path": aggregate_path.resolve().as_posix(),
            "aggregate_sha256": _sha256_file(aggregate_path),
            "aggregate_fingerprint": aggregate_fingerprint,
            "detailed_rerun_path": detailed_rerun_path.resolve().as_posix(),
            "detailed_rerun_sha256": _sha256_file(detailed_rerun_path),
            "detailed_rerun_fingerprint": rerun["fingerprint"],
            "workload_path": workload_path.resolve().as_posix(),
            "workload_sha256": workload_sha256,
            "workload_semantic_fingerprint": aggregate_workload["semantic_fingerprint"],
            "systems": content_bindings,
        },
        "phase_definitions": {
            "pre_failure_elapsed": "initial route-0 scheduler-step start to failure fence",
            "pre_failure_compute_active": "union of route-0 step intervals before the fence",
            "detection": "failure fence to RECOVERY_PLAN",
            "reroute_setup": "RECOVERY_PLAN to first recovery-flow ready time",
            "kv_recall_critical_path": "flow-ready to restored-prefix materialization",
            "retry_compute_queue": "prefix materialization to prompt recompute start",
            "prompt_recompute": "missing prompt suffix recomputation",
            "silent_replay": "already emitted output replay with zero external emission",
            "resumed_inference": "resume point to request completion",
            "peer_store_intervals": "source-specific parallel windows; never summed as latency",
        },
        "observations": observations,
        "forbidden_figure_labels": list(FORBIDDEN_LABELS),
    }
    return {**body, "fingerprint": sha256_json(body)}


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise MechanismArtifactError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifact = build_mechanism_artifact(
        aggregate_path=args.aggregate,
        detailed_rerun_path=args.detailed_rerun,
        workload_path=args.workload,
    )
    _write_json_atomic(args.output, artifact)
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": args.output.resolve().as_posix(),
                "fingerprint": artifact["fingerprint"],
                "observation_count": len(artifact["observations"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
