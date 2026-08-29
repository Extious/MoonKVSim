"""Strongly typed rows for the section 16 baseline resource outputs."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.network import FlowRateInterval


class OutputContractError(ValueError):
    """An input cannot be represented without violating the output contract."""


@dataclass(frozen=True, slots=True)
class AllocationByteShape:
    """Allocator geometry needed to avoid inventing requested/allocated bytes."""

    requested_bytes: int
    allocated_bytes: int

    def __post_init__(self) -> None:
        _require_int("requested_bytes", self.requested_bytes, positive=True)
        _require_int("allocated_bytes", self.allocated_bytes, positive=True)
        if self.requested_bytes > self.allocated_bytes:
            raise OutputContractError("requested_bytes cannot exceed allocated_bytes")


@dataclass(frozen=True, slots=True)
class ResourceLedgerDeltaRow:
    """One physical allocation account transfer at a canonical event boundary.

    ``before_bytes`` and ``after_bytes`` are the destination-account values
    required by plan section 16.3.  The explicit source and destination pairs
    retain enough information for byte-exact replay and conservation checks.
    """

    timestamp_ns: int
    stable_sequence: int
    delta_sequence: int
    event_id: str
    cause: str
    resource_id: str
    resource_kind: CapacityResourceKind
    allocation_id: str
    object_id: str | None
    replica_id: str | None
    transfer_id: str | None
    account_from: str
    account_to: str
    requested_bytes: int
    allocated_bytes: int
    delta_bytes: int
    before_bytes: int
    after_bytes: int
    from_before_bytes: int
    from_after_bytes: int
    to_before_bytes: int
    to_after_bytes: int
    capacity_bytes: int

    def __post_init__(self) -> None:
        for name, integer_value in (
            ("timestamp_ns", self.timestamp_ns),
            ("stable_sequence", self.stable_sequence),
            ("delta_sequence", self.delta_sequence),
        ):
            _require_int(name, integer_value, non_negative=True)
        for name, string_value in (
            ("event_id", self.event_id),
            ("cause", self.cause),
            ("resource_id", self.resource_id),
            ("allocation_id", self.allocation_id),
            ("account_from", self.account_from),
            ("account_to", self.account_to),
        ):
            _require_string(name, string_value)
        if not isinstance(self.resource_kind, CapacityResourceKind):
            raise OutputContractError("resource_kind must be a CapacityResourceKind")
        for name, optional_string in (
            ("object_id", self.object_id),
            ("replica_id", self.replica_id),
            ("transfer_id", self.transfer_id),
        ):
            if optional_string is not None:
                _require_string(name, optional_string)
        if self.account_from == self.account_to:
            raise OutputContractError("account_from and account_to must differ")
        for name, positive_integer in (
            ("requested_bytes", self.requested_bytes),
            ("allocated_bytes", self.allocated_bytes),
            ("delta_bytes", self.delta_bytes),
            ("capacity_bytes", self.capacity_bytes),
        ):
            _require_int(name, positive_integer, positive=True)
        for name, non_negative_integer in (
            ("before_bytes", self.before_bytes),
            ("after_bytes", self.after_bytes),
            ("from_before_bytes", self.from_before_bytes),
            ("from_after_bytes", self.from_after_bytes),
            ("to_before_bytes", self.to_before_bytes),
            ("to_after_bytes", self.to_after_bytes),
        ):
            _require_int(name, non_negative_integer, non_negative=True)
        if self.requested_bytes > self.allocated_bytes:
            raise OutputContractError("requested_bytes cannot exceed allocated_bytes")
        if self.delta_bytes != self.allocated_bytes:
            raise OutputContractError("capacity delta must move the complete physical allocation")
        if self.from_before_bytes - self.delta_bytes != self.from_after_bytes:
            raise OutputContractError("source account does not conserve delta_bytes")
        if self.to_before_bytes + self.delta_bytes != self.to_after_bytes:
            raise OutputContractError("destination account does not conserve delta_bytes")
        if (self.before_bytes, self.after_bytes) != (
            self.to_before_bytes,
            self.to_after_bytes,
        ):
            raise OutputContractError(
                "before_bytes/after_bytes must mirror destination account boundaries"
            )
        if (
            max(
                self.from_before_bytes,
                self.from_after_bytes,
                self.to_before_bytes,
                self.to_after_bytes,
            )
            > self.capacity_bytes
        ):
            raise OutputContractError("account bytes cannot exceed physical capacity")

    @property
    def sort_key(self) -> tuple[int, int, int, str, str]:
        return (
            self.timestamp_ns,
            self.stable_sequence,
            self.delta_sequence,
            self.resource_id,
            self.allocation_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_ns": self.timestamp_ns,
            "stable_sequence": self.stable_sequence,
            "delta_sequence": self.delta_sequence,
            "event_id": self.event_id,
            "cause": self.cause,
            "resource_id": self.resource_id,
            "resource_kind": self.resource_kind.value,
            "allocation_id": self.allocation_id,
            "object_id": self.object_id,
            "replica_id": self.replica_id,
            "transfer_id": self.transfer_id,
            "account_from": self.account_from,
            "account_to": self.account_to,
            "requested_bytes": self.requested_bytes,
            "allocated_bytes": self.allocated_bytes,
            "delta_bytes": self.delta_bytes,
            "before_bytes": self.before_bytes,
            "after_bytes": self.after_bytes,
            "from_before_bytes": self.from_before_bytes,
            "from_after_bytes": self.from_after_bytes,
            "to_before_bytes": self.to_before_bytes,
            "to_after_bytes": self.to_after_bytes,
            "capacity_bytes": self.capacity_bytes,
        }


@dataclass(frozen=True, slots=True)
class FlowRateEventRow:
    """One non-empty fluid-service interval between contention boundaries."""

    start_ns: int
    end_ns: int
    stable_sequence: int
    flow_id: str
    transfer_id: str
    slice_id: str
    cause: str
    path_resource_ids: tuple[str, ...]
    payload_bytes: int
    remaining_bytes: float
    remaining_bytes_at_end: float
    transferred_bytes: float
    allocated_rate_Bps: float
    queue_wait_ns: int
    service_ns: int

    def __post_init__(self) -> None:
        _require_int("start_ns", self.start_ns, non_negative=True)
        _require_int("end_ns", self.end_ns, non_negative=True)
        _require_int("stable_sequence", self.stable_sequence, non_negative=True)
        if self.end_ns <= self.start_ns:
            raise OutputContractError("flow interval must be non-empty")
        for name, string_value in (
            ("flow_id", self.flow_id),
            ("transfer_id", self.transfer_id),
            ("slice_id", self.slice_id),
            ("cause", self.cause),
        ):
            _require_string(name, string_value)
        if not self.path_resource_ids or len(set(self.path_resource_ids)) != len(
            self.path_resource_ids
        ):
            raise OutputContractError("path_resource_ids must be non-empty and unique")
        for resource_id in self.path_resource_ids:
            _require_string("path_resource_id", resource_id)
        _require_int("payload_bytes", self.payload_bytes, positive=True)
        _require_int("queue_wait_ns", self.queue_wait_ns, non_negative=True)
        _require_int("service_ns", self.service_ns, positive=True)
        if self.service_ns != self.end_ns - self.start_ns:
            raise OutputContractError("service_ns must equal end_ns - start_ns")
        for name, numeric_value in (
            ("remaining_bytes", self.remaining_bytes),
            ("remaining_bytes_at_end", self.remaining_bytes_at_end),
            ("transferred_bytes", self.transferred_bytes),
            ("allocated_rate_Bps", self.allocated_rate_Bps),
        ):
            _require_finite(name, numeric_value, non_negative=True)
        if self.allocated_rate_Bps <= 0:
            raise OutputContractError("allocated_rate_Bps must be positive")
        if self.remaining_bytes > self.payload_bytes:
            raise OutputContractError("remaining_bytes cannot exceed payload_bytes")
        allowance = self.allocated_rate_Bps / 1_000_000_000 + 1e-7
        if not math.isclose(
            self.remaining_bytes - self.transferred_bytes,
            self.remaining_bytes_at_end,
            rel_tol=1e-12,
            abs_tol=allowance,
        ):
            raise OutputContractError("flow interval does not conserve remaining bytes")
        ideal_transferred = self.allocated_rate_Bps * self.service_ns / 1_000_000_000
        if not math.isclose(
            self.transferred_bytes,
            min(ideal_transferred, self.remaining_bytes),
            rel_tol=1e-12,
            abs_tol=allowance,
        ):
            raise OutputContractError("transferred bytes disagree with rate and service time")

    @property
    def sort_key(self) -> tuple[int, int, str, str, int]:
        return (
            self.start_ns,
            self.end_ns,
            self.flow_id,
            self.slice_id,
            self.stable_sequence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
            "stable_sequence": self.stable_sequence,
            "flow_id": self.flow_id,
            "transfer_id": self.transfer_id,
            "slice_id": self.slice_id,
            "cause": self.cause,
            "path_resource_ids": list(self.path_resource_ids),
            "payload_bytes": self.payload_bytes,
            "remaining_bytes": self.remaining_bytes,
            "remaining_bytes_at_end": self.remaining_bytes_at_end,
            "transferred_bytes": self.transferred_bytes,
            "allocated_rate_Bps": self.allocated_rate_Bps,
            "queue_wait_ns": self.queue_wait_ns,
            "service_ns": self.service_ns,
        }


def extract_resource_ledger_delta_rows(
    journal: EventJournal,
    resources: Mapping[str, CapacityLedger],
    *,
    allocation_shapes: Mapping[str, AllocationByteShape] | None = None,
) -> tuple[ResourceLedgerDeltaRow, ...]:
    """Extract canonical rows without guessing unavailable allocation geometry."""

    shapes = _allocation_shapes_from_journal(journal)
    for allocation_id, shape in (allocation_shapes or {}).items():
        _require_string("allocation_id", allocation_id)
        if not isinstance(shape, AllocationByteShape):
            raise OutputContractError("allocation_shapes values must be AllocationByteShape")
        previous = shapes.get(allocation_id)
        if previous is not None and previous != shape:
            raise OutputContractError(f"conflicting geometry for allocation {allocation_id}")
        shapes[allocation_id] = shape

    rows: list[ResourceLedgerDeltaRow] = []
    for record in journal.records:
        if record.record_type != "RESOURCE_TRANSACTION":
            continue
        event_id = _mapping_string(record.data, "event_id")
        cause = _mapping_string(record.data, "cause")
        raw_deltas = record.data.get("allocation_deltas")
        if not isinstance(raw_deltas, list) or not raw_deltas:
            raise OutputContractError("allocation_deltas must be a non-empty list")
        for delta_sequence, raw_delta in enumerate(raw_deltas):
            if not isinstance(raw_delta, Mapping):
                raise OutputContractError("allocation delta must be an object")
            resource_id = _mapping_string(raw_delta, "resource_id")
            try:
                resource = resources[resource_id]
            except KeyError as error:
                raise OutputContractError(f"unknown resource {resource_id}") from error
            if not isinstance(resource, CapacityLedger):
                raise OutputContractError(f"resource {resource_id} is not a CapacityLedger")
            if resource.resource_id != resource_id:
                raise OutputContractError(f"resource key mismatch for {resource_id}")
            allocation_id = _mapping_string(raw_delta, "allocation_id")
            try:
                shape = shapes[allocation_id]
            except KeyError as error:
                raise OutputContractError(
                    f"missing requested/allocated geometry for allocation {allocation_id}"
                ) from error
            to_before = _mapping_int(raw_delta, "to_before_bytes", non_negative=True)
            to_after = _mapping_int(raw_delta, "to_after_bytes", non_negative=True)
            rows.append(
                ResourceLedgerDeltaRow(
                    timestamp_ns=record.timestamp_ns,
                    stable_sequence=record.journal_sequence,
                    delta_sequence=delta_sequence,
                    event_id=event_id,
                    cause=cause,
                    resource_id=resource_id,
                    resource_kind=resource.resource_kind,
                    allocation_id=allocation_id,
                    object_id=_mapping_optional_string(raw_delta, "object_id"),
                    replica_id=_mapping_optional_string(raw_delta, "replica_id"),
                    transfer_id=_mapping_optional_string(raw_delta, "transfer_id"),
                    account_from=_mapping_string(raw_delta, "account_from"),
                    account_to=_mapping_string(raw_delta, "account_to"),
                    requested_bytes=shape.requested_bytes,
                    allocated_bytes=shape.allocated_bytes,
                    delta_bytes=_mapping_int(raw_delta, "delta_bytes", positive=True),
                    before_bytes=to_before,
                    after_bytes=to_after,
                    from_before_bytes=_mapping_int(
                        raw_delta, "from_before_bytes", non_negative=True
                    ),
                    from_after_bytes=_mapping_int(raw_delta, "from_after_bytes", non_negative=True),
                    to_before_bytes=to_before,
                    to_after_bytes=to_after,
                    capacity_bytes=_mapping_int(raw_delta, "capacity_bytes", positive=True),
                )
            )
    return canonical_resource_ledger_delta_rows(rows)


def canonical_resource_ledger_delta_rows(
    rows: Sequence[ResourceLedgerDeltaRow],
) -> tuple[ResourceLedgerDeltaRow, ...]:
    for row in rows:
        if not isinstance(row, ResourceLedgerDeltaRow):
            raise OutputContractError("resource ledger rows must be ResourceLedgerDeltaRow")
    ordered = tuple(sorted(rows, key=lambda item: item.sort_key))
    keys = [(row.stable_sequence, row.delta_sequence) for row in ordered]
    if len(keys) != len(set(keys)):
        raise OutputContractError("duplicate journal/delta sequence in resource rows")
    return ordered


def build_flow_rate_event_rows(
    intervals: Sequence[FlowRateInterval],
    *,
    queue_wait_ns_by_flow: Mapping[str, int] | None = None,
) -> tuple[FlowRateEventRow, ...]:
    """Convert flow-model intervals; queue wait is charged only to the first interval."""

    queue_wait = dict(queue_wait_ns_by_flow or {})
    for flow_id, value in queue_wait.items():
        _require_string("flow_id", flow_id)
        _require_int("queue_wait_ns", value, non_negative=True)
    ordered = sorted(
        intervals,
        key=lambda item: (
            item.start_ns,
            item.end_ns,
            item.flow_id,
            item.slice_id,
            item.transfer_id,
        ),
    )
    seen: set[str] = set()
    rows: list[FlowRateEventRow] = []
    for stable_sequence, interval in enumerate(ordered):
        first_interval = interval.flow_id not in seen
        seen.add(interval.flow_id)
        rows.append(
            FlowRateEventRow(
                start_ns=interval.start_ns,
                end_ns=interval.end_ns,
                stable_sequence=stable_sequence,
                flow_id=interval.flow_id,
                transfer_id=interval.transfer_id,
                slice_id=interval.slice_id,
                cause=interval.cause,
                path_resource_ids=interval.path_resource_ids,
                payload_bytes=interval.payload_bytes,
                remaining_bytes=interval.remaining_bytes_at_start,
                remaining_bytes_at_end=interval.remaining_bytes_at_end,
                transferred_bytes=interval.transferred_bytes,
                allocated_rate_Bps=interval.allocated_rate_bytes_per_second,
                queue_wait_ns=queue_wait.get(interval.flow_id, 0) if first_interval else 0,
                service_ns=interval.end_ns - interval.start_ns,
            )
        )
    result = canonical_flow_rate_event_rows(rows)
    validate_flow_rate_sequence(result)
    return result


def canonical_flow_rate_event_rows(
    rows: Sequence[FlowRateEventRow],
) -> tuple[FlowRateEventRow, ...]:
    for row in rows:
        if not isinstance(row, FlowRateEventRow):
            raise OutputContractError("flow rows must be FlowRateEventRow")
    ordered = tuple(sorted(rows, key=lambda item: item.sort_key))
    sequences = [row.stable_sequence for row in ordered]
    if len(sequences) != len(set(sequences)):
        raise OutputContractError("flow stable_sequence values must be unique")
    return ordered


def validate_flow_rate_sequence(rows: Sequence[FlowRateEventRow]) -> None:
    """Validate interval continuity and byte conservation independently per flow."""

    grouped: dict[str, list[FlowRateEventRow]] = defaultdict(list)
    for row in canonical_flow_rate_event_rows(rows):
        grouped[row.flow_id].append(row)
    for flow_id, flow_rows in sorted(grouped.items()):
        ordered = sorted(flow_rows, key=lambda item: (item.start_ns, item.end_ns))
        first = ordered[0]
        payload_bytes = first.payload_bytes
        if not math.isclose(first.remaining_bytes, payload_bytes, abs_tol=1e-7):
            raise OutputContractError(f"flow {flow_id} does not begin with its payload")
        previous = first
        for row in ordered[1:]:
            if row.payload_bytes != payload_bytes:
                raise OutputContractError(f"flow {flow_id} changes payload_bytes")
            if (
                row.transfer_id,
                row.slice_id,
                row.cause,
                row.path_resource_ids,
            ) != (
                first.transfer_id,
                first.slice_id,
                first.cause,
                first.path_resource_ids,
            ):
                raise OutputContractError(f"flow {flow_id} changes immutable metadata")
            if row.start_ns != previous.end_ns:
                raise OutputContractError(f"flow {flow_id} intervals are not contiguous")
            allowance = row.allocated_rate_Bps / 1_000_000_000 + 1e-7
            if not math.isclose(
                row.remaining_bytes,
                previous.remaining_bytes_at_end,
                rel_tol=1e-12,
                abs_tol=allowance,
            ):
                raise OutputContractError(f"flow {flow_id} remaining bytes are discontinuous")
            if row.queue_wait_ns != 0:
                raise OutputContractError(
                    f"flow {flow_id} repeats queue wait after its first interval"
                )
            previous = row
        transferred = sum(row.transferred_bytes for row in ordered)
        allowance = max(row.allocated_rate_Bps for row in ordered) / 1_000_000_000 + 1e-7
        if not math.isclose(
            transferred + ordered[-1].remaining_bytes_at_end,
            payload_bytes,
            rel_tol=1e-12,
            abs_tol=allowance,
        ):
            raise OutputContractError(f"flow {flow_id} does not conserve payload bytes")


def _allocation_shapes_from_journal(
    journal: EventJournal,
) -> dict[str, AllocationByteShape]:
    shapes: dict[str, AllocationByteShape] = {}
    for record in journal.records:
        if record.record_type == "TRANSFER_RESOURCE_LEASE_ACQUIRED":
            raw_allocations = record.data.get("staging_allocations")
            if not isinstance(raw_allocations, list):
                raise OutputContractError(
                    "TRANSFER_RESOURCE_LEASE_ACQUIRED staging_allocations must be a list"
                )
            for raw in raw_allocations:
                if not isinstance(raw, Mapping):
                    raise OutputContractError("staging allocation must be an object")
                allocation_id = _mapping_string(raw, "allocation_id")
                shape = AllocationByteShape(
                    requested_bytes=_mapping_int(raw, "requested_bytes", positive=True),
                    allocated_bytes=_mapping_int(raw, "allocated_bytes", positive=True),
                )
                previous = shapes.get(allocation_id)
                if previous is not None and previous != shape:
                    raise OutputContractError(f"conflicting journal geometry for {allocation_id}")
                shapes[allocation_id] = shape
            continue
        if record.record_type == "ALLOCATION_BYTE_SHAPE_DECLARED":
            allocation_id = _mapping_string(record.data, "allocation_id")
            shape = AllocationByteShape(
                requested_bytes=_mapping_int(
                    record.data,
                    "requested_bytes",
                    positive=True,
                ),
                allocated_bytes=_mapping_int(
                    record.data,
                    "allocated_bytes",
                    positive=True,
                ),
            )
        elif record.record_type == "ALLOCATION_ADDED":
            raw = record.data.get("allocation")
            if not isinstance(raw, Mapping):
                raise OutputContractError("ALLOCATION_ADDED must contain an allocation object")
            allocation_id = _mapping_string(raw, "allocation_id")
            shape = AllocationByteShape(
                requested_bytes=_mapping_int(raw, "requested_bytes", positive=True),
                allocated_bytes=_mapping_int(raw, "allocated_bytes", positive=True),
            )
        else:
            continue
        previous = shapes.get(allocation_id)
        if previous is not None and previous != shape:
            raise OutputContractError(f"conflicting journal geometry for {allocation_id}")
        shapes[allocation_id] = shape
    return shapes


def _mapping_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise OutputContractError(f"{key} must be a non-empty string")
    return value


def _mapping_optional_string(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None:
        _require_string(key, value)
    return value


def _mapping_int(
    data: Mapping[str, Any],
    key: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> int:
    value = data.get(key)
    if type(value) is not int:
        raise OutputContractError(f"{key} must be an integer")
    if positive and value <= 0:
        raise OutputContractError(f"{key} must be positive")
    if non_negative and value < 0:
        raise OutputContractError(f"{key} must be non-negative")
    return value


def _require_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise OutputContractError(f"{name} must be a non-empty string")


def _require_int(
    name: str,
    value: object,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> None:
    if type(value) is not int:
        raise OutputContractError(f"{name} must be an integer")
    if positive and value <= 0:
        raise OutputContractError(f"{name} must be positive")
    if non_negative and value < 0:
        raise OutputContractError(f"{name} must be non-negative")


def _require_finite(
    name: str,
    value: object,
    *,
    non_negative: bool = False,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OutputContractError(f"{name} must be numeric")
    if not math.isfinite(value):
        raise OutputContractError(f"{name} must be finite")
    if non_negative and value < 0:
        raise OutputContractError(f"{name} must be non-negative")
