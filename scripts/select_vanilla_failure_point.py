#!/usr/bin/env python3
"""Select and materialize one deterministic vanilla E2 GPU failure point.

The selector intentionally reuses ``compare_section16_runs.inspect_run`` for the
complete 19-artifact validation contract.  It then reopens the journal and JSON
documents, requires their SHA-256 identities to match that inspection, and
derives one failure point without consulting normalized cached-prefix hints.
"""

from __future__ import annotations

import argparse
import bisect
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Final

from compare_section16_runs import ComparisonError, inspect_run

from moonkvsim.baseline.e2_harness import (
    E2HarnessError,
    load_harness_config,
    resolve_failure_specs,
)
from moonkvsim.common.hash import canonical_json_bytes
from moonkvsim.output.section16 import SECTION_16_ARTIFACTS

SELECTION_SCHEMA: Final = "moonkvsim.vanilla-failure-point-selection.v1"
ALGORITHM_ID: Final = "widest-isolated-reused-store-prefix-post-output-forward.v1"
EVIDENCE_BOUNDARY: Final = "E2_real_trace_shape_vanilla_baseline_uncalibrated"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_NORMAL_GET_CAUSE = "BASELINE_E2_SHARED_STORE_PREFIX_REUSE"
_SOURCE_BLOCK_SIZE_TOKENS = 64


class SelectionError(RuntimeError):
    """The input bundle or requested materialization is invalid."""


class NoSelectionError(RuntimeError):
    """The bundle is valid but contains no fully gated failure point."""


def _object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SelectionError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if type(value) is not list:
        raise SelectionError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SelectionError(f"{label} must be a non-empty string")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise SelectionError(f"{label} must be a non-negative integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise SelectionError(f"{label} must be a boolean")
    return value


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_bound_json(path: Path, expected_sha256: str) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SelectionError(f"bound JSON must be a regular non-symlink file: {path}")
    raw = path.read_bytes()
    if _sha256_bytes(raw) != expected_sha256:
        raise SelectionError(f"bound JSON SHA-256 changed after bundle inspection: {path}")
    try:
        value = json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SelectionError(f"cannot parse bound JSON {path}: {error}") from error
    document = _object(value, str(path))
    if raw != canonical_json_bytes(document) + b"\n":
        raise SelectionError(f"bound JSON is not canonical with one final newline: {path}")
    return document


def _read_bound_journal(path: Path, expected_sha256: str) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise SelectionError(f"journal must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    records: list[dict[str, Any]] = []
    previous_timestamp = 0
    with path.open("rb") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            digest.update(raw_line)
            if not raw_line.endswith(b"\n") or raw_line == b"\n":
                raise SelectionError(f"journal line {line_number} is empty or lacks final newline")
            payload = raw_line[:-1]
            try:
                value = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                raise SelectionError(f"cannot parse journal line {line_number}: {error}") from error
            record = dict(_object(value, f"journal line {line_number}"))
            if set(record) != {"timestamp_ns", "journal_sequence", "record_type", "data"}:
                raise SelectionError(f"journal line {line_number} has non-canonical keys")
            if canonical_json_bytes(record) != payload:
                raise SelectionError(f"journal line {line_number} is not canonical JSON")
            timestamp = _integer(record["timestamp_ns"], f"journal line {line_number}.timestamp_ns")
            sequence = _integer(
                record["journal_sequence"], f"journal line {line_number}.journal_sequence"
            )
            if sequence != len(records):
                raise SelectionError("journal_sequence must be contiguous from zero")
            if timestamp < previous_timestamp:
                raise SelectionError("journal timestamps must be monotonic")
            _string(record["record_type"], f"journal line {line_number}.record_type")
            _object(record["data"], f"journal line {line_number}.data")
            records.append(record)
            previous_timestamp = timestamp
    if digest.hexdigest() != expected_sha256:
        raise SelectionError("journal SHA-256 changed after bundle inspection")
    return records


def _unique_put(target: dict[str, Any], key: str, value: Any, label: str) -> None:
    if key in target:
        raise SelectionError(f"duplicate {label}: {key}")
    target[key] = value


def _allocation_state_at(
    allocation_events: Mapping[str, list[tuple[int, int, str, Mapping[str, Any]]]],
    allocation_id: str,
    at_ns: int,
) -> dict[str, Any] | None:
    state: dict[str, Any] | None = None
    for timestamp, _sequence, record_type, data in allocation_events.get(allocation_id, []):
        if timestamp >= at_ns:
            break
        if record_type == "ALLOCATION_ADDED":
            allocation = _object(data.get("allocation"), "ALLOCATION_ADDED.allocation")
            state = {
                "allocation_id": allocation_id,
                "object_id": _string(allocation.get("object_id"), "allocation.object_id"),
                "replica_id": _string(allocation.get("replica_id"), "allocation.replica_id"),
                "resource_id": _string(allocation.get("resource_id"), "allocation.resource_id"),
                "state": _string(allocation.get("state"), "allocation.state"),
                "state_record_type": "ALLOCATION_ADDED",
                "state_timestamp_ns": timestamp,
                "state_journal_sequence": _sequence,
                "source_pin_count": 0,
            }
        elif state is None:
            raise SelectionError(f"allocation event precedes ALLOCATION_ADDED: {allocation_id}")
        elif record_type == "ALLOCATION_TRANSITION":
            state["state"] = _string(data.get("state"), "ALLOCATION_TRANSITION.state")
            state["state_record_type"] = record_type
            state["state_timestamp_ns"] = timestamp
            state["state_journal_sequence"] = _sequence
        elif record_type == "ALLOCATION_RECOVERY_ELIGIBILITY":
            # Parse the value strictly, but do not use it as a Store-source gate.
            # BaselineRecoveryPlanner._usable_store_replica deliberately ignores
            # this overlay flag; it is false for normal Store allocations.
            _boolean(data.get("eligible"), "ALLOCATION_RECOVERY_ELIGIBILITY.eligible")
        elif record_type == "ALLOCATION_SOURCE_PINNED":
            state["source_pin_count"] += 1
        elif record_type == "ALLOCATION_SOURCE_UNPINNED":
            state["source_pin_count"] -= 1
            if state["source_pin_count"] < 0:
                raise SelectionError(f"negative source pin count: {allocation_id}")
    if state is not None:
        state["terminal_transition_absent_before_failure"] = state["state"] not in {
            "LOST",
            "RELEASED",
        }
    return state


def _directory_state_at(
    put_started_by_replica: Mapping[str, Mapping[str, Any]],
    put_committed: Mapping[str, Mapping[str, Any]],
    *,
    replica_id: str,
    object_id: str,
    at_ns: int,
) -> dict[str, Any] | None:
    """Replay the journaled Store publication proof for one directory replica.

    The directory itself is in-memory and has no separate mutation record.  The
    client commit record is emitted only after ``Master.put_end`` completed all
    expected shards, transitioned the replica to COMMITTED, and published it.
    The candidate additionally requires a later successful real GET, which can
    start only from a visible committed directory replica.  A removal/eviction
    is rejected independently by the point-in-time allocation replay because
    those paths transition the backing allocation to RELEASED.  The recovery
    eligibility overlay is intentionally irrelevant, matching the planner.
    """

    started = put_started_by_replica.get(replica_id)
    if started is None or started.get("object_id") != object_id:
        return None
    put_id = _string(started.get("put_id"), "STORE_CLIENT_PUT_STARTED.put_id")
    committed = put_committed.get(put_id)
    if committed is None or replica_id not in _array(
        committed.get("replica_ids"), "STORE_CLIENT_PUT_COMMITTED.replica_ids"
    ):
        return None
    committed_at = _integer(committed.get("timestamp_ns"), "Store commit timestamp")
    if committed_at >= at_ns:
        return None
    return {
        "replica_id": replica_id,
        "object_id": object_id,
        "location": "STORE_DRAM",
        "state": "COMMITTED",
        "visible": True,
        "expected_shards_complete": True,
        "publication_record_type": "STORE_CLIENT_PUT_COMMITTED",
        "put_id": put_id,
        "published_at_ns": committed_at,
        "publication_journal_sequence": _integer(
            committed.get("journal_sequence"), "Store commit journal sequence"
        ),
    }


def _subtract_intervals(
    segments: list[tuple[int, int]], exclusions: Iterable[tuple[int, int]]
) -> list[tuple[int, int]]:
    result = segments
    for excluded_start, excluded_end in sorted(exclusions):
        updated: list[tuple[int, int]] = []
        for start, end in result:
            if excluded_end < start or excluded_start > end:
                updated.append((start, end))
                continue
            if start < excluded_start:
                updated.append((start, excluded_start - 1))
            if excluded_end < end:
                updated.append((excluded_end + 1, end))
        result = updated
    return result


def _subtract_points(
    segments: list[tuple[int, int]], sorted_points: Sequence[int]
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for start, end in segments:
        cursor = start
        left = bisect.bisect_left(sorted_points, start)
        right = bisect.bisect_right(sorted_points, end)
        for point in sorted_points[left:right]:
            if cursor <= point - 1:
                result.append((cursor, point - 1))
            cursor = point + 1
        if cursor <= end:
            result.append((cursor, end))
    return result


def select_failure_point(
    records: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the canonical selection fields derived only from one no-failure journal."""

    admissions: dict[str, dict[str, Any]] = {}
    ready: dict[str, dict[str, Any]] = {}
    get_started: dict[str, dict[str, Any]] = {}
    get_completed: dict[str, dict[str, Any]] = {}
    outputs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    forwards: list[dict[str, Any]] = []
    leases: dict[str, dict[str, Any]] = {}
    lease_releases: dict[str, dict[str, Any]] = {}
    forward_completions: dict[str, dict[str, Any]] = {}
    completions: dict[str, int] = {}
    put_started_by_replica: dict[str, dict[str, Any]] = {}
    put_committed: dict[str, dict[str, Any]] = {}
    allocation_events: dict[str, list[tuple[int, int, str, Mapping[str, Any]]]] = defaultdict(list)
    occupied: set[int] = set()

    allocation_types = {
        "ALLOCATION_ADDED",
        "ALLOCATION_TRANSITION",
        "ALLOCATION_RECOVERY_ELIGIBILITY",
        "ALLOCATION_SOURCE_PINNED",
        "ALLOCATION_SOURCE_UNPINNED",
    }
    for expected_sequence, raw_record in enumerate(records):
        record = _object(raw_record, f"record {expected_sequence}")
        timestamp = _integer(record.get("timestamp_ns"), "record.timestamp_ns")
        sequence = _integer(record.get("journal_sequence"), "record.journal_sequence")
        if sequence != expected_sequence:
            raise SelectionError("selection records must retain contiguous journal order")
        record_type = _string(record.get("record_type"), "record.record_type")
        data = _object(record.get("data"), f"{record_type}.data")
        occupied.add(timestamp)
        if record_type == "EVENT_SCHEDULED":
            occupied.add(_integer(data.get("scheduled_timestamp_ns"), "scheduled_timestamp_ns"))
        elif record_type == "TRACE_RUNNER_SPAN_ADMITTED":
            request_id = _string(data.get("request_id"), "admission.request_id")
            _unique_put(
                admissions,
                request_id,
                {"timestamp_ns": timestamp, "journal_sequence": sequence, **dict(data)},
                "request admission",
            )
        elif record_type == "TRACE_RUNNER_REMOTE_PREFIX_READY":
            request_id = _string(data.get("request_id"), "prefix-ready.request_id")
            _unique_put(
                ready,
                request_id,
                {"timestamp_ns": timestamp, "journal_sequence": sequence, **dict(data)},
                "prefix-ready record",
            )
        elif record_type == "STORE_CLIENT_GET_STARTED":
            get_id = _string(data.get("get_id"), "get-started.get_id")
            _unique_put(
                get_started,
                get_id,
                {"timestamp_ns": timestamp, "journal_sequence": sequence, **dict(data)},
                "Store GET start",
            )
        elif record_type == "STORE_CLIENT_GET_COMPLETED":
            get_id = _string(data.get("get_id"), "get-completed.get_id")
            _unique_put(
                get_completed,
                get_id,
                {"timestamp_ns": timestamp, "journal_sequence": sequence, **dict(data)},
                "Store GET completion",
            )
        elif record_type == "STORE_CLIENT_PUT_STARTED":
            put_id = _string(data.get("put_id"), "put-started.put_id")
            started = {"timestamp_ns": timestamp, "journal_sequence": sequence, **dict(data)}
            for item in _array(data.get("replica_ids"), "put-started.replica_ids"):
                replica_id = _string(item, "put-started.replica_ids[]")
                _unique_put(
                    put_started_by_replica,
                    replica_id,
                    started,
                    "Store replica publication start",
                )
            if not data.get("replica_ids"):
                raise SelectionError(f"Store PUT has no replica: {put_id}")
        elif record_type == "STORE_CLIENT_PUT_COMMITTED":
            put_id = _string(data.get("put_id"), "put-committed.put_id")
            committed_replica_ids = [
                _string(item, "put-committed.replica_ids[]")
                for item in _array(data.get("replica_ids"), "put-committed.replica_ids")
            ]
            if not committed_replica_ids or len(set(committed_replica_ids)) != len(
                committed_replica_ids
            ):
                raise SelectionError(f"Store PUT commit has no replicas or duplicates: {put_id}")
            _unique_put(
                put_committed,
                put_id,
                {"timestamp_ns": timestamp, "journal_sequence": sequence, **dict(data)},
                "Store PUT commit",
            )
        elif record_type == "BASELINE_OUTPUT_ACTIVATED":
            request_id = _string(data.get("request_id"), "output.request_id")
            outputs[request_id].append(
                {"timestamp_ns": timestamp, "journal_sequence": sequence, **dict(data)}
            )
        elif record_type == "BASELINE_FORWARD_BATCH_SCHEDULED":
            forwards.append({"timestamp_ns": timestamp, "journal_sequence": sequence, **dict(data)})
        elif record_type == "TRACE_RUNNER_GPU_COMPUTE_LEASE_ACQUIRED":
            lease_id = _string(data.get("lease_id"), "lease-acquired.lease_id")
            _unique_put(
                leases,
                lease_id,
                {"timestamp_ns": timestamp, "journal_sequence": sequence, **dict(data)},
                "compute lease",
            )
        elif record_type == "TRACE_RUNNER_GPU_COMPUTE_LEASE_RELEASED":
            lease_id = _string(data.get("lease_id"), "lease-released.lease_id")
            _unique_put(
                lease_releases,
                lease_id,
                {"timestamp_ns": timestamp, "journal_sequence": sequence, **dict(data)},
                "compute lease release",
            )
        elif record_type == "BASELINE_FORWARD_BATCH_COMPLETED":
            event_id = _string(data.get("event_id"), "forward-completed.event_id")
            _unique_put(
                forward_completions,
                event_id,
                {"timestamp_ns": timestamp, "journal_sequence": sequence, **dict(data)},
                "forward completion",
            )
        elif record_type == "TRACE_RUNNER_SPAN_COMPLETED":
            request_id = _string(data.get("request_id"), "span-completed.request_id")
            if request_id in completions:
                raise SelectionError(f"duplicate span completion: {request_id}")
            completions[request_id] = timestamp

        if record_type in allocation_types:
            if record_type == "ALLOCATION_ADDED":
                allocation = _object(data.get("allocation"), "ALLOCATION_ADDED.allocation")
                allocation_id = _string(allocation.get("allocation_id"), "allocation_id")
            else:
                allocation_id = _string(data.get("allocation_id"), f"{record_type}.allocation_id")
            allocation_events[allocation_id].append((timestamp, sequence, record_type, data))

    gpu_items = _array(_object(config.get("deployment"), "deployment").get("gpus"), "gpus")
    by_replica: dict[str, Mapping[str, Any]] = {}
    for raw_gpu in gpu_items:
        gpu = _object(raw_gpu, "deployment.gpus[]")
        replica_id = _string(gpu.get("replica_id"), "gpu.replica_id")
        if replica_id in by_replica:
            raise SelectionError(f"duplicate configured replica: {replica_id}")
        by_replica[replica_id] = gpu
    if len(by_replica) < 2:
        raise NoSelectionError("failure replay requires at least one alternate DP replica")
    store_resource_id = _string(
        _object(config.get("store"), "store").get("segment_id"), "store.segment_id"
    )

    forbidden_points = sorted(occupied | {item - 1 for item in occupied if item > 0})
    ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for forward in forwards:
        event_id = _string(forward.get("event_id"), "forward.event_id")
        replica_id = _string(forward.get("replica_id"), "forward.replica_id")
        completion_ns = _integer(forward.get("completion_ns"), "forward.completion_ns")
        start_ns = _integer(forward.get("timestamp_ns"), "forward.timestamp_ns")
        participants = _array(forward.get("participants"), "forward.participants")
        lease_id = f"gpu-compute:{replica_id}:{event_id}"
        lease = leases.get(lease_id)
        release = lease_releases.get(lease_id)
        terminal = forward_completions.get(event_id)
        if lease is None or release is None or terminal is None or "purpose" in lease:
            continue
        participant_request_ids = [
            _string(_object(item, "participant").get("request_id"), "participant.request_id")
            for item in participants
        ]
        if (
            lease.get("replica_id") != replica_id
            or lease.get("capacity") != 1
            or lease.get("request_ids") != participant_request_ids
            or lease.get("release_ns") != completion_ns
            or terminal.get("accepted") is not True
            or terminal.get("fence_reason") is not None
            or release.get("outcome") != "COMPLETED"
            or release.get("actual_release_ns") != completion_ns
            or release.get("declared_release_ns") != completion_ns
        ):
            continue

        for raw_participant in participants:
            participant = _object(raw_participant, "forward participant")
            if participant.get("produces_output") is not True:
                continue
            request_id = _string(participant.get("request_id"), "participant.request_id")
            admission = admissions.get(request_id)
            prefix_ready = ready.get(request_id)
            if admission is None or prefix_ready is None:
                continue
            route_version = _integer(participant.get("route_version"), "participant.route_version")
            if (
                participant.get("target_id") != replica_id
                or admission.get("target_replica_id") != replica_id
                or admission.get("route_version") != route_version
            ):
                continue
            lookup = _object(admission.get("committed_prefix_lookup"), "committed_prefix_lookup")
            block_count = _integer(
                lookup.get("observed_committed_block_count"), "observed_committed_block_count"
            )
            visible_tokens = _integer(
                admission.get("visible_committed_prefix_tokens"), "visible_committed_prefix_tokens"
            )
            if (
                block_count == 0
                or visible_tokens != block_count * _SOURCE_BLOCK_SIZE_TOKENS
                or lookup.get("mode") != "full_hash_vector_from_block_zero_first_miss"
                or lookup.get("normalized_parent_prefix_used_as_query_limit") is not False
                or prefix_ready.get("restored_tokens") != visible_tokens
                or prefix_ready.get("target_replica_id") != replica_id
            ):
                continue

            span_id = _string(admission.get("span_id"), "admission.span_id")
            expected_get_ids = [
                f"trace-get:{span_id}:route-{route_version}:block-{index:06d}"
                for index in range(block_count)
            ]
            source_bindings: list[dict[str, Any]] = []
            source_allocation_ids: list[str] = []
            valid_gets = True
            for get_id in expected_get_ids:
                get_start = get_started.get(get_id)
                get_completion = get_completed.get(get_id)
                if (
                    get_start is None
                    or get_completion is None
                    or get_start.get("cause") != _NORMAL_GET_CAUSE
                    or get_start.get("route_version") != route_version
                    or get_start.get("source_pins_held_until_terminal") is not True
                    or get_completion.get("replica_id") != get_start.get("replica_id")
                    or get_completion.get("transferred_bytes") != get_start.get("payload_bytes")
                    or (get_start["timestamp_ns"], get_start["journal_sequence"])
                    >= (prefix_ready["timestamp_ns"], prefix_ready["journal_sequence"])
                    or (get_completion["timestamp_ns"], get_completion["journal_sequence"])
                    > (prefix_ready["timestamp_ns"], prefix_ready["journal_sequence"])
                ):
                    valid_gets = False
                    break
                allocation_ids = _array(
                    get_start.get("source_allocation_ids"), "source_allocation_ids"
                )
                if not allocation_ids:
                    valid_gets = False
                    break
                normalized_ids = [
                    _string(item, "source_allocation_ids[]") for item in allocation_ids
                ]
                source_allocation_ids.extend(normalized_ids)
                source_bindings.append(
                    {
                        "get_id": get_id,
                        "object_id": _string(get_start.get("object_id"), "GET.object_id"),
                        "store_replica_id": _string(get_start.get("replica_id"), "GET.replica_id"),
                        "source_allocation_ids": normalized_ids,
                        "started_at_ns": get_start["timestamp_ns"],
                        "started_journal_sequence": get_start["journal_sequence"],
                        "completed_at_ns": get_completion["timestamp_ns"],
                        "completed_journal_sequence": get_completion["journal_sequence"],
                        "visibility_proof": (
                            "successful_real_get_from_visible_committed_store_replica"
                        ),
                    }
                )
            if not valid_gets or len(set(source_allocation_ids)) != len(source_allocation_ids):
                continue

            request_outputs = sorted(
                outputs.get(request_id, []),
                key=lambda item: (item["timestamp_ns"], item["journal_sequence"]),
            )
            prior_outputs = [
                item
                for item in request_outputs
                if item.get("route_version") == route_version
                and (item["timestamp_ns"], item["journal_sequence"])
                < (start_ns, forward["journal_sequence"])
            ]
            if not prior_outputs:
                continue
            indices = [
                _integer(item.get("output_index"), "output.output_index") for item in prior_outputs
            ]
            if indices != list(range(len(indices))):
                continue
            last_output = prior_outputs[-1]
            if participant.get("output_index") != indices[-1] + 1:
                continue

            low = max(start_ns, _integer(last_output["timestamp_ns"], "last-output timestamp"))
            high = completion_ns - 2
            if low + 1 > high:
                continue
            segments = [(low + 1, high)]
            other_live_intervals: list[tuple[int, int]] = []
            for other_request, other_admission in admissions.items():
                if (
                    other_request == request_id
                    or other_admission.get("target_replica_id") != replica_id
                ):
                    continue
                other_completion = completions.get(other_request)
                if other_completion is None:
                    raise SelectionError(f"PASS journal lacks completion for {other_request}")
                other_live_intervals.append(
                    (
                        _integer(other_admission["timestamp_ns"], "other admission") + 1,
                        other_completion - 1,
                    )
                )
            segments = _subtract_intervals(segments, other_live_intervals)
            segments = _subtract_points(segments, forbidden_points)

            for segment_start, segment_end in segments:
                at_ns = segment_start + (segment_end - segment_start) // 2
                allocation_rows: list[dict[str, Any]] = []
                directory_rows: dict[str, dict[str, Any]] = {}
                allocation_valid = True
                binding_by_id = {
                    allocation_id: binding
                    for binding in source_bindings
                    for allocation_id in binding["source_allocation_ids"]
                }
                for allocation_id in source_allocation_ids:
                    state = _allocation_state_at(allocation_events, allocation_id, at_ns)
                    binding = binding_by_id[allocation_id]
                    directory_state = _directory_state_at(
                        put_started_by_replica,
                        put_committed,
                        replica_id=binding["store_replica_id"],
                        object_id=binding["object_id"],
                        at_ns=at_ns,
                    )
                    if (
                        state is None
                        or state["state"] != "COMMITTED"
                        or state["terminal_transition_absent_before_failure"] is not True
                        or state["source_pin_count"] != 0
                        or state["resource_id"] != store_resource_id
                        or state["object_id"] != binding["object_id"]
                        or state["replica_id"] != binding["store_replica_id"]
                        or directory_state is None
                        or (
                            directory_state["published_at_ns"],
                            directory_state["publication_journal_sequence"],
                        )
                        >= (binding["started_at_ns"], binding["started_journal_sequence"])
                    ):
                        allocation_valid = False
                        break
                    allocation_rows.append(dict(state))
                    directory_rows[directory_state["replica_id"]] = directory_state
                if not allocation_valid:
                    continue
                selected_gpu = by_replica.get(replica_id)
                if selected_gpu is None:
                    raise SelectionError(f"forward references unknown replica {replica_id}")
                selected_gpu_id = _string(selected_gpu.get("gpu_id"), "gpu.gpu_id")
                if not any(
                    other_replica_id != replica_id
                    and _string(other_gpu.get("gpu_id"), "gpu.gpu_id") != selected_gpu_id
                    for other_replica_id, other_gpu in by_replica.items()
                ):
                    continue
                target = {
                    "replica_id": replica_id,
                    "gpu_id": selected_gpu_id,
                    "hbm_resource_id": _string(
                        selected_gpu.get("hbm_resource_id"), "gpu.hbm_resource_id"
                    ),
                }
                width = segment_end - segment_start + 1
                margin = min(at_ns - low, completion_ns - at_ns)
                selection = {
                    "span_id": span_id,
                    "request_id": request_id,
                    "route_version": route_version,
                    "store_prefix": {
                        "block_count": block_count,
                        "tokens": visible_tokens,
                        "get_ids": expected_get_ids,
                        "source_bindings": source_bindings,
                        "source_allocation_ids": sorted(source_allocation_ids),
                        "allocation_state_at_failure": sorted(
                            allocation_rows, key=lambda item: item["allocation_id"]
                        ),
                        "directory_state_at_failure": sorted(
                            directory_rows.values(), key=lambda item: item["replica_id"]
                        ),
                    },
                    "last_activated_output": {
                        "output_index": indices[-1],
                        "timestamp_ns": last_output["timestamp_ns"],
                        "journal_sequence": last_output["journal_sequence"],
                    },
                    "forward": {
                        "event_id": event_id,
                        "lease_id": lease_id,
                        "replica_id": replica_id,
                        "start_ns": start_ns,
                        "completion_ns": completion_ns,
                        "output_index": participant["output_index"],
                    },
                    "eligible_window": {
                        "start_ns_inclusive": segment_start,
                        "end_ns_inclusive": segment_end,
                        "integer_count": width,
                    },
                    "at_ns": at_ns,
                    "target": target,
                    "affected_live_request_ids": [request_id],
                }
                rank = (
                    -width,
                    -margin,
                    span_id,
                    request_id,
                    route_version,
                    replica_id,
                    event_id,
                    segment_start,
                )
                ranked.append((rank, selection))

    if not ranked:
        raise NoSelectionError("no isolated reused-prefix post-output forward window exists")
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def _failure_document(selection: Mapping[str, Any]) -> dict[str, Any]:
    at_ns = _integer(selection.get("at_ns"), "selection.at_ns")
    raw_target = _object(selection.get("target"), "selection.target")
    if set(raw_target) != {"replica_id", "gpu_id", "hbm_resource_id"}:
        raise SelectionError("selection target must contain the exact failure target tuple")
    target = {
        "replica_id": _string(raw_target.get("replica_id"), "target.replica_id"),
        "gpu_id": _string(raw_target.get("gpu_id"), "target.gpu_id"),
        "hbm_resource_id": _string(raw_target.get("hbm_resource_id"), "target.hbm_resource_id"),
    }
    return {
        "enabled": True,
        "mode": "fixed_virtual_time_gpu_fail_stop",
        "parameter_source": "assumed",
        "calibration_status": "not_calibrated",
        "formal_use_allowed": False,
        "random_selection": False,
        "implicit_fallback": False,
        "events": [
            {
                "failure_id": "weka-reused-prefix-post-output-failure-0",
                "type": "GPU_FAILURE",
                "at_ns": at_ns,
                "detection_delay_ns": 0,
                "target": target,
                "repair_after_ns": None,
                "semantics": "fail_stop_hbm_lost",
            }
        ],
    }


def _selection_fingerprint(document: Mapping[str, Any]) -> str:
    fields = dict(document)
    fields.pop("selection_fingerprint", None)
    return hashlib.sha256(canonical_json_bytes(fields)).hexdigest()


def _normalized_repository_path(value: object, label: str) -> str:
    path = _string(value, label)
    pure_path = PurePosixPath(path)
    if (
        pure_path.is_absolute()
        or pure_path.as_posix() != path
        or any(part in {"", ".", ".."} for part in pure_path.parts)
        or "\\" in path
    ):
        raise SelectionError(f"{label} must be normalized repository-relative POSIX")
    return path


def _regular_non_symlink_file(repository_root: Path, relative_path: str, label: str) -> Path:
    target = repository_root
    for part in PurePosixPath(relative_path).parts:
        target /= part
        if target.is_symlink():
            raise SelectionError(f"{label} must not be a symlink: {relative_path}")
    try:
        mode = target.stat().st_mode
    except OSError as error:
        raise SelectionError(f"{label} is unavailable: {relative_path}: {error}") from error
    if not stat.S_ISREG(mode):
        raise SelectionError(f"{label} must be a regular file: {relative_path}")
    return target


def _semantic_source_manifest(sources: Mapping[str, Any]) -> dict[str, Any]:
    raw_files = _array(sources.get("files"), "semantic source files")
    files: list[dict[str, Any]] = []
    observed_paths: set[str] = set()
    for index, raw_item in enumerate(raw_files):
        item = _object(raw_item, f"semantic source file {index}")
        if set(item) != {"path", "scope", "roles", "size_bytes", "sha256"}:
            raise SelectionError(f"semantic source file {index} has non-canonical fields")
        if item.get("scope") != "repository":
            raise SelectionError(f"semantic source file {index} is not repository-scoped")
        path = _normalized_repository_path(item.get("path"), f"semantic source file {index}.path")
        if path in observed_paths:
            raise SelectionError(f"duplicate semantic source path: {path}")
        observed_paths.add(path)
        raw_roles = _array(item.get("roles"), "roles")
        roles = [_string(role, "semantic source role") for role in raw_roles]
        if not roles or roles != sorted(set(roles)):
            raise SelectionError(f"semantic source roles are not sorted and unique: {path}")
        size_bytes = _integer(item.get("size_bytes"), f"semantic source size {path}")
        sha256 = _string(item.get("sha256"), f"semantic source SHA {path}")
        if _SHA256_RE.fullmatch(sha256) is None:
            raise SelectionError(f"semantic source SHA is invalid: {path}")
        files.append(
            {
                "path": path,
                "scope": "repository",
                "roles": roles,
                "size_bytes": size_bytes,
                "sha256": sha256,
            }
        )
    if not files or [item["path"] for item in files] != sorted(observed_paths):
        raise SelectionError("semantic source files must be non-empty and path-sorted")
    if sources.get("file_count") != len(files):
        raise SelectionError("semantic source file count is inconsistent")
    aggregate = hashlib.sha256(canonical_json_bytes(files)).hexdigest()
    if sources.get("aggregate_sha256") != aggregate:
        raise SelectionError("semantic source aggregate SHA-256 is inconsistent")
    return {"files": files, "file_count": len(files), "aggregate_sha256": aggregate}


def _selection_tool_provenance(repository_root: Path) -> dict[str, Any]:
    if _git_output(repository_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise SelectionError("selection requires a clean current Git worktree")
    script = Path(__file__).resolve()
    try:
        relative = script.relative_to(repository_root.resolve()).as_posix()
    except ValueError as error:
        raise SelectionError("selector script is outside the repository") from error
    relative = _normalized_repository_path(relative, "selector script path")
    script = _regular_non_symlink_file(repository_root, relative, "selector script")
    _git_output(repository_root, "ls-files", "--error-unmatch", "--", relative)
    raw = script.read_bytes()
    head = _git_output(repository_root, "rev-parse", "HEAD").decode().strip()
    tree = _git_output(repository_root, "rev-parse", "HEAD^{tree}").decode().strip()
    if _GIT_OBJECT_RE.fullmatch(head) is None or _GIT_OBJECT_RE.fullmatch(tree) is None:
        raise SelectionError("selection tool Git HEAD/tree is not a complete object ID")
    return {
        "git_head_commit": head,
        "git_head_tree": tree,
        "script_path": relative,
        "script_size_bytes": len(raw),
        "script_sha256": _sha256_bytes(raw),
    }


def select_bundle(
    run_dir: Path,
    base_config_path: Path,
    expected_head: str,
) -> dict[str, Any]:
    if _GIT_OBJECT_RE.fullmatch(expected_head) is None:
        raise SelectionError("--expected-head must be a complete lowercase Git object ID")
    try:
        inspection = inspect_run(run_dir)
    except ComparisonError as error:
        raise SelectionError(str(error)) from error
    hashes = _object(inspection.get("artifact_sha256"), "artifact SHA manifest")
    if set(hashes) != set(SECTION_16_ARTIFACTS):
        raise SelectionError("artifact SHA manifest does not cover the exact Section16 set")
    normalized_hashes = {
        name: _string(hashes[name], f"artifact hash {name}") for name in sorted(hashes)
    }
    run_audit = _read_bound_json(run_dir / "run-audit.json", normalized_hashes["run-audit.json"])
    trace_audit = _read_bound_json(
        run_dir / "trace-audit.json", normalized_hashes["trace-audit.json"]
    )
    provenance = _object(run_audit.get("semantic_source_provenance"), "source provenance")
    snapshot = _object(provenance.get("start_snapshot"), "start snapshot")
    git = _object(snapshot.get("git"), "start snapshot git")
    if git.get("head_commit") != expected_head:
        raise SelectionError("recorded Git HEAD differs from --expected-head")
    if (
        git.get("head_state") != "resolved"
        or git.get("worktree_clean") is not True
        or git.get("porcelain_entry_count") != 0
        or snapshot.get("source_frozen") is not True
        or snapshot.get("source_freeze_blockers") != []
        or provenance.get("unchanged_during_run") is not True
    ):
        raise SelectionError("diagnostic does not bind one unchanged clean frozen source")
    section = _object(run_audit.get("section_16"), "run-audit.section_16")
    rows = _object(section.get("parquet_row_counts"), "parquet row counts")
    if rows.get("failure-events.parquet") != 0 or rows.get("recovery-events.parquet") != 0:
        raise SelectionError("selector accepts only a no-failure diagnostic")

    sources = _object(snapshot.get("semantic_sources"), "semantic sources")
    semantic_source_manifest = _semantic_source_manifest(sources)
    config_entries = [
        _object(item, "semantic source file")
        for item in _array(sources.get("files"), "semantic source files")
        if "selected-harness-config"
        in _array(_object(item, "semantic source file").get("roles"), "semantic source roles")
    ]
    if len(config_entries) != 1:
        raise SelectionError("semantic manifest must name exactly one selected harness config")
    config_entry = config_entries[0]
    repository_root = Path(_string(snapshot.get("repository_root"), "repository_root"))
    if repository_root.resolve() != Path(__file__).resolve().parents[1]:
        raise SelectionError("diagnostic repository root differs from the selector repository")
    selection_tool = _selection_tool_provenance(repository_root)
    recorded_relative = _string(config_entry.get("path"), "selected config path")
    expected_config_path = (repository_root / recorded_relative).resolve()
    if base_config_path.resolve() != expected_config_path:
        raise SelectionError("--base-config differs from the recorded selected harness config")
    raw_config = base_config_path.read_bytes()
    config_sha256 = _sha256_bytes(raw_config)
    if config_sha256 != config_entry.get("sha256") or len(raw_config) != config_entry.get(
        "size_bytes"
    ):
        raise SelectionError("base config bytes differ from the frozen semantic manifest")
    config = load_harness_config(base_config_path)
    if config.failure_enabled:
        raise SelectionError("selection requires the recorded no-failure base config")
    if trace_audit.get("source_sha256") != config.trace_sha256:
        raise SelectionError("trace audit and base config trace SHA differ")
    if trace_audit.get("selected_workflow_ids") != list(config.workflow_ids):
        raise SelectionError("trace audit and base config workflow selection differ")

    records = _read_bound_journal(
        run_dir / "event-journal.jsonl", normalized_hashes["event-journal.jsonl"]
    )
    if trace_audit.get("journal_record_count") != len(records):
        raise SelectionError("trace audit journal count differs from bound journal")
    selection = select_failure_point(records, config.document)
    failure = _failure_document(selection)
    document: dict[str, Any] = {
        "schema": SELECTION_SCHEMA,
        "status": "PASS",
        "formal_use_allowed": False,
        "evidence_boundary": EVIDENCE_BOUNDARY,
        "algorithm": {
            "id": ALGORITHM_ID,
            "failure_detection_delay_ns": 0,
            "collision_policy": "at_ns_and_at_ns_plus_one_absent_from_journal_and_schedule",
            "tie_break": (
                "widest_integer_window_then_largest_boundary_margin_then_"
                "span_request_route_replica_event_start"
            ),
            "store_source_gate": (
                "prior_successful_visible_store_get_plus_point_in_time_committed_"
                "allocation_zero_source_pins_and_no_terminal_transition"
            ),
            "source_resource_gate": (
                "exact_no_failure_bundle_and_committed_store_allocation_on_configured_segment"
            ),
            "recovery_eligibility_overlay_used": False,
        },
        "input": {
            "artifact_sha256": normalized_hashes,
            "artifact_aggregate_sha256": hashlib.sha256(
                canonical_json_bytes(normalized_hashes)
            ).hexdigest(),
            "journal_sha256": normalized_hashes["event-journal.jsonl"],
            "journal_record_count": len(records),
            "semantic_source_fingerprint": inspection["semantic_source_fingerprint"],
            "semantic_sources": semantic_source_manifest,
            "git_head_commit": expected_head,
            "git_head_tree": git.get("head_tree"),
            "base_config_path": recorded_relative,
            "base_config_sha256": config_sha256,
            "trace_sha256": config.trace_sha256,
            "selected_workflow_ids": list(config.workflow_ids),
        },
        "selection_tool": selection_tool,
        "selection": selection,
        "materialization": {
            "json_pointer_replaced": "/failure",
            "failure": failure,
            "hardware_profile_fingerprint": config.document["predictor"][
                "hardware_profile_fingerprint"
            ],
        },
    }
    document["selection_fingerprint"] = _selection_fingerprint(document)
    return document


def _load_selection_evidence(path: Path) -> Mapping[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SelectionError(f"invalid selection evidence: {error}") from error
    document = _object(value, "selection evidence")
    if raw != canonical_json_bytes(document) + b"\n":
        raise SelectionError("selection evidence must be canonical JSON with one final newline")
    if document.get("schema") != SELECTION_SCHEMA or document.get("status") != "PASS":
        raise SelectionError("selection evidence schema/status differs")
    if document.get("selection_fingerprint") != _selection_fingerprint(document):
        raise SelectionError("selection evidence fingerprint is inconsistent")
    return document


def _git_output(repository_root: Path, *args: str) -> bytes:
    process = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if process.returncode:
        raise SelectionError(process.stderr.decode(errors="replace").strip())
    return process.stdout


def _require_clean_semantic_sources(
    repository_root: Path,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if _git_output(repository_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise SelectionError("materialization requires a clean current Git worktree")
    inputs = _object(evidence.get("input"), "input")
    tool = _object(evidence.get("selection_tool"), "selection_tool")
    if set(tool) != {
        "git_head_commit",
        "git_head_tree",
        "script_path",
        "script_size_bytes",
        "script_sha256",
    }:
        raise SelectionError("selection_tool has non-canonical fields")
    tool_head = _string(tool.get("git_head_commit"), "selection_tool.git_head_commit")
    tool_tree = _string(tool.get("git_head_tree"), "selection_tool.git_head_tree")
    if _GIT_OBJECT_RE.fullmatch(tool_head) is None or _GIT_OBJECT_RE.fullmatch(tool_tree) is None:
        raise SelectionError("selection tool Git HEAD/tree is not a complete object ID")
    current_head = _git_output(repository_root, "rev-parse", "HEAD").decode().strip()
    current_tree = _git_output(repository_root, "rev-parse", "HEAD^{tree}").decode().strip()
    if current_head != tool_head or current_tree != tool_tree:
        raise SelectionError("current Git HEAD/tree differs from the selection tool provenance")
    script_path = _normalized_repository_path(tool.get("script_path"), "selection_tool.script_path")
    expected_script_path = Path(__file__).resolve()
    current_script_path = _regular_non_symlink_file(
        repository_root, script_path, "selection tool script"
    )
    if current_script_path.resolve() != expected_script_path:
        raise SelectionError("selection tool script path differs from the executing selector")
    _git_output(repository_root, "ls-files", "--error-unmatch", "--", script_path)
    raw_script = current_script_path.read_bytes()
    tool_size = _integer(tool.get("script_size_bytes"), "selection_tool.script_size_bytes")
    tool_sha = _string(tool.get("script_sha256"), "selection_tool.script_sha256")
    if _SHA256_RE.fullmatch(tool_sha) is None:
        raise SelectionError("selection tool script SHA-256 is invalid")
    if len(raw_script) != tool_size or _sha256_bytes(raw_script) != tool_sha:
        raise SelectionError("selection tool script bytes differ from selection provenance")

    manifest = _semantic_source_manifest(
        _object(inputs.get("semantic_sources"), "input.semantic_sources")
    )
    for item in manifest["files"]:
        semantic_path = _regular_non_symlink_file(
            repository_root, item["path"], "diagnostic semantic source"
        )
        raw = semantic_path.read_bytes()
        if len(raw) != item["size_bytes"] or _sha256_bytes(raw) != item["sha256"]:
            raise SelectionError(f"diagnostic semantic source bytes drifted: {item['path']}")
    run_audit_sha = _object(inputs.get("artifact_sha256"), "hashes").get("run-audit.json")
    if not isinstance(run_audit_sha, str) or _SHA256_RE.fullmatch(run_audit_sha) is None:
        raise SelectionError("selection evidence lacks a valid run-audit hash")
    return {
        "git_head_commit": current_head,
        "git_head_tree": current_tree,
        "script_path": script_path,
        "script_size_bytes": len(raw_script),
        "script_sha256": _sha256_bytes(raw_script),
    }


def materialize_config(
    evidence: Mapping[str, Any],
    base_config_path: Path,
    output_path: Path,
    *,
    current_tool: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    inputs = _object(evidence.get("input"), "selection input")
    repository_root = Path(__file__).resolve().parents[1]
    recorded_base_path = repository_root / _string(
        inputs.get("base_config_path"), "selection input.base_config_path"
    )
    if base_config_path.resolve() != recorded_base_path.resolve():
        raise SelectionError("materialization base config path differs from selection evidence")
    raw_base = base_config_path.read_bytes()
    if _sha256_bytes(raw_base) != inputs.get("base_config_sha256"):
        raise SelectionError("base config SHA differs from selection evidence")
    base = load_harness_config(base_config_path)
    if base.failure_enabled:
        raise SelectionError("materialization base config already enables failure")
    materialization = _object(evidence.get("materialization"), "materialization")
    if materialization.get("json_pointer_replaced") != "/failure":
        raise SelectionError("materialization may replace only /failure")
    selection = _object(evidence.get("selection"), "selection")
    expected_failure = _failure_document(selection)
    if materialization.get("failure") != expected_failure:
        raise SelectionError("materialized failure differs from the canonical selected failure")
    base_hardware_fingerprint = base.document["predictor"]["hardware_profile_fingerprint"]
    if materialization.get("hardware_profile_fingerprint") != base_hardware_fingerprint:
        raise SelectionError("materialization hardware fingerprint differs from the base config")
    document = dict(copy.deepcopy(base.document))
    document["failure"] = copy.deepcopy(expected_failure)
    base_without_failure = dict(base.document)
    output_without_failure = dict(document)
    del base_without_failure["failure"]
    del output_without_failure["failure"]
    if output_without_failure != base_without_failure:
        raise SelectionError("materialization changed a field outside /failure")
    raw_output = canonical_json_bytes(document) + b"\n"
    output = output_path.resolve()
    parent = output.parent
    if output_path.exists() or output_path.is_symlink():
        raise SelectionError(f"materialized config target already exists: {output_path}")
    parent.mkdir(parents=False, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{output.name}.", suffix=".tmp", dir=parent, delete=False
        ) as stream:
            temporary_name = stream.name
            stream.write(raw_output)
            stream.flush()
            os.fsync(stream.fileno())
        temporary = Path(temporary_name)
        candidate = load_harness_config(temporary)
        specs = resolve_failure_specs(candidate)
        if len(specs) != 1:
            raise SelectionError("materialized config did not resolve exactly one failure")
        try:
            os.link(temporary, output)
        except FileExistsError as error:
            raise SelectionError(f"materialized config target already exists: {output}") from error
        loaded = load_harness_config(output)
        resolved = resolve_failure_specs(loaded)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    result = {
        "schema": "moonkvsim.vanilla-failure-config-materialization.v1",
        "status": "PASS",
        "output_path": str(output),
        "output_sha256": _sha256_bytes(raw_output),
        "selection_fingerprint": evidence["selection_fingerprint"],
        "failure_id": resolved[0].failure_id,
        "at_ns": resolved[0].at_ns,
        "gpu_id": resolved[0].gpu_id,
        "changed_json_pointers": ["/failure"],
    }
    if current_tool is not None:
        result["selection_tool"] = dict(current_tool)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    select = subparsers.add_parser("select")
    select.add_argument("--run-dir", required=True, type=Path)
    select.add_argument("--expected-head", required=True)
    select.add_argument("--base-config", required=True, type=Path)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--selection-evidence", required=True, type=Path)
    materialize.add_argument("--base-config", required=True, type=Path)
    materialize.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "select":
            result = select_bundle(args.run_dir, args.base_config, args.expected_head)
        else:
            evidence = _load_selection_evidence(args.selection_evidence)
            repository_root = Path(__file__).resolve().parents[1]
            current_tool = _require_clean_semantic_sources(repository_root, evidence)
            result = materialize_config(
                evidence, args.base_config, args.output, current_tool=current_tool
            )
    except NoSelectionError as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        return 3
    except (OSError, ValueError, SelectionError, E2HarnessError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, sort_keys=True))
        return 2
    sys.stdout.buffer.write(canonical_json_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
