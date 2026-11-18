"""Capacity audit and event-boundary summary derived only from delta rows."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from moonkvsim.output.records import (
    ResourceLedgerDeltaRow,
    canonical_resource_ledger_delta_rows,
)
from moonkvsim.simulation.ledger import CapacityLedger

CAPACITY_DELTA_AUDIT_SCHEMA = "moonkvsim.output.capacity-delta-audit.v1"
CAPACITY_SUMMARY_SCHEMA = "moonkvsim.output.capacity-summary.v1"


@dataclass(frozen=True, slots=True)
class CapacityDeltaFailure:
    code: str
    message: str
    resource_id: str | None
    stable_sequence: int | None
    delta_sequence: int | None


@dataclass(frozen=True, slots=True)
class CapacityDeltaAudit:
    schema: str
    valid: bool
    status: str
    checked_delta_count: int
    resource_count: int
    byte_conservation_at_every_event_boundary: bool
    final_snapshot_sha256: str | None
    expected_final_snapshot_byte_identical: bool | None
    first_failure: CapacityDeltaFailure | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_dict())

    def write(self, path: Path, *, overwrite: bool = False) -> None:
        _write_bytes(path, self.to_json_bytes(), overwrite=overwrite)


@dataclass(frozen=True, slots=True)
class AccountCapacitySummary:
    account: str
    initial_bytes: int
    final_bytes: int
    peak_bytes: int
    peak_timestamp_ns: int
    peak_stable_sequence: int
    peak_delta_sequence: int


@dataclass(frozen=True, slots=True)
class ResourceCapacitySummary:
    resource_id: str
    resource_kind: str
    capacity_bytes: int
    accounts: tuple[AccountCapacitySummary, ...]


@dataclass(frozen=True, slots=True)
class CapacitySummary:
    schema: str
    source: str
    event_boundary_peaks_preserved: bool
    resource_count: int
    start_timestamp_ns: int
    end_timestamp_ns: int
    resources: tuple[ResourceCapacitySummary, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_dict())

    def write(self, path: Path, *, overwrite: bool = False) -> None:
        _write_bytes(path, self.to_json_bytes(), overwrite=overwrite)


@dataclass(slots=True)
class _ResourceState:
    resource_id: str
    resource_kind: str
    capacity_bytes: int
    accounts: dict[str, int]


@dataclass(frozen=True, slots=True)
class _Peak:
    value: int
    timestamp_ns: int
    stable_sequence: int
    delta_sequence: int


def derive_capacity_artifacts(
    initial_ledgers: Mapping[str, CapacityLedger],
    rows: Sequence[ResourceLedgerDeltaRow],
    *,
    expected_final_ledgers: Mapping[str, CapacityLedger] | None = None,
) -> tuple[CapacityDeltaAudit, CapacitySummary | None]:
    """Replay canonical deltas and return no summary when any audit gate fails."""

    ordered = canonical_resource_ledger_delta_rows(rows)
    try:
        states = _capture_ledgers(initial_ledgers)
    except ValueError as error:
        return _failure("INVALID_INITIAL_LEDGER", str(error), len(initial_ledgers)), None

    start_timestamp_ns = ordered[0].timestamp_ns if ordered else 0
    end_timestamp_ns = ordered[-1].timestamp_ns if ordered else start_timestamp_ns
    initial_accounts = {
        resource_id: dict(state.accounts) for resource_id, state in states.items()
    }
    peaks: dict[tuple[str, str], _Peak] = {}
    for resource_id, initial_state in states.items():
        for account, value in initial_state.accounts.items():
            peaks[(resource_id, account)] = _Peak(
                value=value,
                timestamp_ns=start_timestamp_ns,
                stable_sequence=-1,
                delta_sequence=-1,
            )

    checked = 0
    for row in ordered:
        current_state = states.get(row.resource_id)
        if current_state is None:
            return (
                _failure(
                    "UNKNOWN_RESOURCE",
                    f"delta references unknown resource {row.resource_id}",
                    len(states),
                    row=row,
                    checked=checked,
                ),
                None,
            )
        if current_state.resource_kind != row.resource_kind.value:
            return (
                _failure(
                    "RESOURCE_KIND_MISMATCH",
                    f"resource kind mismatch for {row.resource_id}",
                    len(states),
                    row=row,
                    checked=checked,
                ),
                None,
            )
        if current_state.capacity_bytes != row.capacity_bytes:
            return (
                _failure(
                    "CAPACITY_MISMATCH",
                    f"capacity mismatch for {row.resource_id}",
                    len(states),
                    row=row,
                    checked=checked,
                ),
                None,
            )
        actual_from = current_state.accounts.get(row.account_from, 0)
        actual_to = current_state.accounts.get(row.account_to, 0)
        if (actual_from, actual_to) != (
            row.from_before_bytes,
            row.to_before_bytes,
        ):
            return (
                _failure(
                    "BEFORE_MISMATCH",
                    f"recorded before values do not match replay for {row.resource_id}",
                    len(states),
                    row=row,
                    checked=checked,
                ),
                None,
            )
        current_state.accounts[row.account_from] = row.from_after_bytes
        current_state.accounts[row.account_to] = row.to_after_bytes
        if any(value < 0 for value in current_state.accounts.values()):
            return (
                _failure(
                    "NEGATIVE_ACCOUNT",
                    f"negative account after delta on {row.resource_id}",
                    len(states),
                    row=row,
                    checked=checked,
                ),
                None,
            )
        if sum(current_state.accounts.values()) != current_state.capacity_bytes:
            return (
                _failure(
                    "BYTE_CONSERVATION_FAILURE",
                    f"accounts do not sum to capacity on {row.resource_id}",
                    len(states),
                    row=row,
                    checked=checked,
                ),
                None,
            )
        checked += 1
        for account in (row.account_from, row.account_to):
            key = (row.resource_id, account)
            value = current_state.accounts[account]
            previous = peaks.get(key)
            if previous is None or value > previous.value:
                peaks[key] = _Peak(
                    value=value,
                    timestamp_ns=row.timestamp_ns,
                    stable_sequence=row.stable_sequence,
                    delta_sequence=row.delta_sequence,
                )

    final_snapshot = _snapshot_bytes(states)
    final_sha256 = hashlib.sha256(final_snapshot).hexdigest()
    expected_matches: bool | None = None
    if expected_final_ledgers is not None:
        try:
            expected = _capture_ledgers(expected_final_ledgers)
        except ValueError as error:
            return (
                _failure(
                    "INVALID_EXPECTED_FINAL_LEDGER",
                    str(error),
                    len(states),
                    checked=checked,
                ),
                None,
            )
        expected_matches = _snapshot_bytes(expected) == final_snapshot
        if not expected_matches:
            return (
                _failure(
                    "FINAL_SNAPSHOT_MISMATCH",
                    "delta-derived final snapshot is not byte-identical to expected final",
                    len(states),
                    checked=checked,
                ),
                None,
            )

    resources: list[ResourceCapacitySummary] = []
    for resource_id, state in sorted(states.items()):
        accounts: list[AccountCapacitySummary] = []
        all_accounts = sorted(set(initial_accounts[resource_id]) | set(state.accounts))
        for account in all_accounts:
            peak = peaks.get(
                (resource_id, account),
                _Peak(0, start_timestamp_ns, -1, -1),
            )
            accounts.append(
                AccountCapacitySummary(
                    account=account,
                    initial_bytes=initial_accounts[resource_id].get(account, 0),
                    final_bytes=state.accounts.get(account, 0),
                    peak_bytes=peak.value,
                    peak_timestamp_ns=peak.timestamp_ns,
                    peak_stable_sequence=peak.stable_sequence,
                    peak_delta_sequence=peak.delta_sequence,
                )
            )
        resources.append(
            ResourceCapacitySummary(
                resource_id=resource_id,
                resource_kind=state.resource_kind,
                capacity_bytes=state.capacity_bytes,
                accounts=tuple(accounts),
            )
        )

    audit = CapacityDeltaAudit(
        schema=CAPACITY_DELTA_AUDIT_SCHEMA,
        valid=True,
        status="PASS",
        checked_delta_count=checked,
        resource_count=len(states),
        byte_conservation_at_every_event_boundary=True,
        final_snapshot_sha256=final_sha256,
        expected_final_snapshot_byte_identical=expected_matches,
        first_failure=None,
    )
    summary = CapacitySummary(
        schema=CAPACITY_SUMMARY_SCHEMA,
        source="resource-ledger-deltas",
        event_boundary_peaks_preserved=True,
        resource_count=len(states),
        start_timestamp_ns=start_timestamp_ns,
        end_timestamp_ns=end_timestamp_ns,
        resources=tuple(resources),
    )
    return audit, summary


def _capture_ledgers(ledgers: Mapping[str, CapacityLedger]) -> dict[str, _ResourceState]:
    states: dict[str, _ResourceState] = {}
    for resource_id in sorted(ledgers):
        ledger = ledgers[resource_id]
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError("resource keys must be non-empty strings")
        if not isinstance(ledger, CapacityLedger):
            raise ValueError(f"resource {resource_id} is not a CapacityLedger")
        if ledger.resource_id != resource_id:
            raise ValueError(f"resource key mismatch for {resource_id}")
        accounts = dict(ledger.accounts)
        if any(type(value) is not int or value < 0 for value in accounts.values()):
            raise ValueError(f"resource {resource_id} has invalid account bytes")
        if sum(accounts.values()) != ledger.capacity_bytes:
            raise ValueError(f"resource {resource_id} does not conserve capacity")
        states[resource_id] = _ResourceState(
            resource_id=resource_id,
            resource_kind=ledger.resource_kind.value,
            capacity_bytes=ledger.capacity_bytes,
            accounts=accounts,
        )
    return states


def _snapshot_bytes(states: Mapping[str, _ResourceState]) -> bytes:
    value = {
        resource_id: {
            "resource_id": state.resource_id,
            "resource_kind": state.resource_kind,
            "capacity_bytes": state.capacity_bytes,
            "accounts": dict(sorted(state.accounts.items())),
        }
        for resource_id, state in sorted(states.items())
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _failure(
    code: str,
    message: str,
    resource_count: int,
    *,
    row: ResourceLedgerDeltaRow | None = None,
    checked: int = 0,
) -> CapacityDeltaAudit:
    return CapacityDeltaAudit(
        schema=CAPACITY_DELTA_AUDIT_SCHEMA,
        valid=False,
        status="FAIL",
        checked_delta_count=checked,
        resource_count=resource_count,
        byte_conservation_at_every_event_boundary=False,
        final_snapshot_sha256=None,
        expected_final_snapshot_byte_identical=None,
        first_failure=CapacityDeltaFailure(
            code=code,
            message=message,
            resource_id=None if row is None else row.resource_id,
            stable_sequence=None if row is None else row.stable_sequence,
            delta_sequence=None if row is None else row.delta_sequence,
        ),
    )


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode()


def _write_bytes(path: Path, payload: bytes, *, overwrite: bool) -> None:
    mode = "wb" if overwrite else "xb"
    with path.open(mode) as stream:
        stream.write(payload)
