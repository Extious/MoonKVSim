"""Fail-closed capacity-ledger audit generated from the canonical journal."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from moonkvsim.simulation.journal import EventJournal, JournalRecord
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind

CAPACITY_AUDIT_SCHEMA = "moonkvsim.capacity-audit.v1"
CAPACITY_SNAPSHOT_SCHEMA = "moonkvsim.capacity-ledger-snapshot.v1"
RESOURCE_TRANSACTION = "RESOURCE_TRANSACTION"

_TRANSACTION_KEYS = {"event_id", "cause", "allocation_deltas"}
_DELTA_KEYS = {
    "resource_id",
    "allocation_id",
    "object_id",
    "replica_id",
    "transfer_id",
    "account_from",
    "account_to",
    "delta_bytes",
    "from_before_bytes",
    "from_after_bytes",
    "to_before_bytes",
    "to_after_bytes",
    "capacity_bytes",
}


@dataclass(frozen=True, slots=True)
class MinimalReplayPrefix:
    """Smallest inclusive journal prefix that reproduces the first failure."""

    record_count: int
    inclusive_journal_sequence: int | None
    sha256: str


@dataclass(frozen=True, slots=True)
class CapacityAuditFailure:
    """Context for exactly the first fail-closed audit error."""

    code: str
    message: str
    journal_sequence: int | None
    event_id: str | None
    resource_id: str | None
    accounts: dict[str, Any] | None
    delta_index: int | None
    minimal_replay_prefix: MinimalReplayPrefix

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return value


@dataclass(frozen=True, slots=True)
class CapacityAudit:
    """Machine-readable contents of ``capacity-audit.json``."""

    schema: str
    status: str
    valid: bool
    checked_journal_record_count: int
    checked_transaction_count: int
    checked_delta_count: int
    initial_snapshot_sha256: str | None
    online_final_snapshot_sha256: str | None
    replayed_final_snapshot_sha256: str | None
    final_snapshot_sha256: str | None
    final_snapshot_byte_identical: bool
    first_failure: CapacityAuditFailure | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "valid": self.valid,
            "checked_journal_record_count": self.checked_journal_record_count,
            "checked_transaction_count": self.checked_transaction_count,
            "checked_delta_count": self.checked_delta_count,
            "initial_snapshot_sha256": self.initial_snapshot_sha256,
            "online_final_snapshot_sha256": self.online_final_snapshot_sha256,
            "replayed_final_snapshot_sha256": self.replayed_final_snapshot_sha256,
            "final_snapshot_sha256": self.final_snapshot_sha256,
            "final_snapshot_byte_identical": self.final_snapshot_byte_identical,
            "first_failure": None if self.first_failure is None else self.first_failure.to_dict(),
        }

    def to_json_bytes(self) -> bytes:
        return (
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()

    def write(self, path: Path, *, overwrite: bool = False) -> None:
        """Write without implicit directories or silent evidence replacement."""

        mode = "wb" if overwrite else "xb"
        with path.open(mode) as stream:
            stream.write(self.to_json_bytes())


@dataclass(slots=True)
class _LedgerState:
    resource_id: str
    resource_kind: str
    capacity_bytes: int
    accounts: dict[str, int]

    def copy(self) -> _LedgerState:
        return _LedgerState(
            resource_id=self.resource_id,
            resource_kind=self.resource_kind,
            capacity_bytes=self.capacity_bytes,
            accounts=dict(self.accounts),
        )


class _AuditIssue(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        resource_id: str | None = None,
        accounts: dict[str, Any] | None = None,
        delta_index: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.resource_id = resource_id
        self.accounts = accounts
        self.delta_index = delta_index


def capacity_snapshot_bytes(ledgers: Mapping[str, CapacityLedger]) -> bytes:
    """Return a canonical byte-exact snapshot after validating every ledger."""

    states = _capture_ledgers(ledgers, label="snapshot")
    return _snapshot_bytes(states)


def generate_capacity_audit(
    *,
    initial_ledgers: Mapping[str, CapacityLedger],
    journal: EventJournal,
    online_final_ledgers: Mapping[str, CapacityLedger],
) -> CapacityAudit:
    """Replay capacity transactions and compare with the online final ledger snapshot.

    The input ledgers are never mutated. Journal structure, transaction fields,
    per-delta before/after arithmetic, per-resource conservation, and the final canonical
    snapshot are all assertions. The returned failure is always the first observed one.
    """

    records = journal.records
    try:
        initial = _capture_ledgers(initial_ledgers, label="initial")
        initial_bytes = _snapshot_bytes(initial)
    except _AuditIssue as issue:
        return _failure_audit(
            issue,
            records=records,
            failure_record_index=None,
            event_id=None,
            journal_sequence=None,
            checked_journal_records=0,
            checked_transactions=0,
            checked_deltas=0,
            initial_sha256=None,
            online_sha256=None,
            replayed_sha256=None,
        )

    initial_sha256 = _sha256(initial_bytes)
    replayed = {resource_id: state.copy() for resource_id, state in initial.items()}
    checked_journal_records = 0
    checked_transactions = 0
    checked_deltas = 0
    previous_timestamp_ns = 0

    for record_index, record in enumerate(records):
        event_id = _record_event_id(record)
        try:
            _validate_record_envelope(record, record_index, previous_timestamp_ns)
            previous_timestamp_ns = record.timestamp_ns
            if record.record_type == RESOURCE_TRANSACTION:
                delta_count = _replay_transaction(
                    record,
                    replayed,
                )
                checked_transactions += 1
                checked_deltas += delta_count
            checked_journal_records += 1
        except _AuditIssue as issue:
            return _failure_audit(
                issue,
                records=records,
                failure_record_index=record_index,
                event_id=event_id,
                journal_sequence=_safe_sequence(record),
                checked_journal_records=checked_journal_records,
                checked_transactions=checked_transactions,
                checked_deltas=checked_deltas,
                initial_sha256=initial_sha256,
                online_sha256=None,
                replayed_sha256=None,
            )

    replayed_bytes = _snapshot_bytes(replayed)
    replayed_sha256 = _sha256(replayed_bytes)
    try:
        online_final = _capture_ledgers(online_final_ledgers, label="online_final")
        online_bytes = _snapshot_bytes(online_final)
    except _AuditIssue as issue:
        return _failure_audit(
            issue,
            records=records,
            failure_record_index=None,
            event_id="CAPACITY_AUDIT_ONLINE_FINAL_SNAPSHOT",
            journal_sequence=None,
            checked_journal_records=checked_journal_records,
            checked_transactions=checked_transactions,
            checked_deltas=checked_deltas,
            initial_sha256=initial_sha256,
            online_sha256=None,
            replayed_sha256=replayed_sha256,
        )

    online_sha256 = _sha256(online_bytes)
    if replayed_bytes != online_bytes:
        resource_id, accounts = _first_snapshot_difference(replayed, online_final)
        final_issue = _AuditIssue(
            "FINAL_SNAPSHOT_MISMATCH",
            "replayed final snapshot is not byte-identical to the online final snapshot",
            resource_id=resource_id,
            accounts=accounts,
        )
        return _failure_audit(
            final_issue,
            records=records,
            failure_record_index=len(records) - 1 if records else None,
            event_id="CAPACITY_AUDIT_FINAL_SNAPSHOT",
            journal_sequence=records[-1].journal_sequence if records else None,
            checked_journal_records=checked_journal_records,
            checked_transactions=checked_transactions,
            checked_deltas=checked_deltas,
            initial_sha256=initial_sha256,
            online_sha256=online_sha256,
            replayed_sha256=replayed_sha256,
        )

    return CapacityAudit(
        schema=CAPACITY_AUDIT_SCHEMA,
        status="PASS",
        valid=True,
        checked_journal_record_count=checked_journal_records,
        checked_transaction_count=checked_transactions,
        checked_delta_count=checked_deltas,
        initial_snapshot_sha256=initial_sha256,
        online_final_snapshot_sha256=online_sha256,
        replayed_final_snapshot_sha256=replayed_sha256,
        final_snapshot_sha256=replayed_sha256,
        final_snapshot_byte_identical=True,
        first_failure=None,
    )


def _capture_ledgers(
    ledgers: Mapping[str, CapacityLedger], *, label: str
) -> dict[str, _LedgerState]:
    if not isinstance(ledgers, Mapping):
        raise _AuditIssue("INVALID_LEDGER_SET", f"{label} ledgers must be a mapping")
    mapping_keys = list(ledgers)
    for mapping_key in mapping_keys:
        if not isinstance(mapping_key, str) or not mapping_key:
            raise _AuditIssue("INVALID_RESOURCE_ID", f"{label} resource key must be non-empty")
    states: dict[str, _LedgerState] = {}
    for mapping_key in sorted(mapping_keys):
        ledger = ledgers[mapping_key]
        if not isinstance(ledger, CapacityLedger):
            raise _AuditIssue(
                "INVALID_LEDGER_TYPE",
                f"{label} resource {mapping_key} is not a CapacityLedger",
                resource_id=mapping_key,
            )
        if not isinstance(ledger.resource_id, str) or not ledger.resource_id:
            raise _AuditIssue(
                "INVALID_RESOURCE_ID",
                f"{label} ledger.resource_id must be non-empty",
                resource_id=mapping_key,
            )
        if mapping_key != ledger.resource_id:
            raise _AuditIssue(
                "RESOURCE_KEY_MISMATCH",
                f"{label} mapping key does not match ledger.resource_id",
                resource_id=mapping_key,
            )
        if not isinstance(ledger.resource_kind, CapacityResourceKind):
            raise _AuditIssue(
                "INVALID_RESOURCE_KIND",
                f"{label} resource_kind is not a CapacityResourceKind",
                resource_id=mapping_key,
            )
        accounts = dict(ledger.accounts)
        _validate_accounts(
            accounts,
            capacity_bytes=ledger.capacity_bytes,
            resource_id=ledger.resource_id,
            code_prefix=f"{label.upper()}_LEDGER",
        )
        states[mapping_key] = _LedgerState(
            resource_id=ledger.resource_id,
            resource_kind=ledger.resource_kind.value,
            capacity_bytes=ledger.capacity_bytes,
            accounts=accounts,
        )
    return states


def _validate_accounts(
    accounts: Mapping[str, Any],
    *,
    capacity_bytes: int,
    resource_id: str,
    code_prefix: str,
) -> None:
    if type(capacity_bytes) is not int or capacity_bytes <= 0:
        raise _AuditIssue(
            f"{code_prefix}_INVALID_CAPACITY",
            "capacity_bytes must be a positive integer",
            resource_id=resource_id,
            accounts={"capacity_bytes": capacity_bytes},
        )
    for account, value in accounts.items():
        if not isinstance(account, str) or not account:
            raise _AuditIssue(
                f"{code_prefix}_INVALID_ACCOUNT",
                "account names must be non-empty strings",
                resource_id=resource_id,
                accounts={"account": account, "value": value},
            )
        if type(value) is not int or value < 0:
            raise _AuditIssue(
                f"{code_prefix}_INVALID_ACCOUNT_BYTES",
                "account bytes must be non-negative integers",
                resource_id=resource_id,
                accounts={"account": account, "value": value},
            )
    total = sum(accounts.values())
    if total != capacity_bytes:
        raise _AuditIssue(
            f"{code_prefix}_CONSERVATION_FAILURE",
            f"account total {total} does not equal capacity {capacity_bytes}",
            resource_id=resource_id,
            accounts={"capacity_bytes": capacity_bytes, "total_bytes": total, **accounts},
        )


def _validate_record_envelope(
    record: JournalRecord, expected_sequence: int, previous_timestamp_ns: int
) -> None:
    if type(record.journal_sequence) is not int or record.journal_sequence != expected_sequence:
        raise _AuditIssue(
            "JOURNAL_SEQUENCE_MISMATCH",
            f"expected journal_sequence {expected_sequence}, got {record.journal_sequence!r}",
        )
    if type(record.timestamp_ns) is not int or record.timestamp_ns < 0:
        raise _AuditIssue("INVALID_JOURNAL_TIMESTAMP", "timestamp_ns must be non-negative int")
    if record.timestamp_ns < previous_timestamp_ns:
        raise _AuditIssue(
            "JOURNAL_TIME_REGRESSION",
            f"timestamp {record.timestamp_ns} precedes {previous_timestamp_ns}",
        )
    if not isinstance(record.record_type, str) or not record.record_type:
        raise _AuditIssue("INVALID_RECORD_TYPE", "record_type must be a non-empty string")
    if not isinstance(record.data, Mapping):
        raise _AuditIssue("INVALID_RECORD_DATA", "journal record data must be a mapping")


def _replay_transaction(
    record: JournalRecord,
    states: dict[str, _LedgerState],
) -> int:
    data = record.data
    _require_exact_keys(
        data,
        _TRANSACTION_KEYS,
        "resource transaction",
    )
    _required_string(data, "event_id", "INVALID_EVENT_ID")
    _required_string(data, "cause", "INVALID_CAUSE")
    raw_deltas = data.get("allocation_deltas")
    if not isinstance(raw_deltas, list) or not raw_deltas:
        raise _AuditIssue(
            "INVALID_ALLOCATION_DELTAS",
            "allocation_deltas must be a non-empty list",
        )

    proposed = {resource_id: state.copy() for resource_id, state in states.items()}
    for delta_index, raw_delta in enumerate(raw_deltas):
        try:
            _apply_delta(raw_delta, proposed)
        except _AuditIssue as issue:
            _attach_delta_context(issue, raw_delta)
            if issue.delta_index is None:
                issue.delta_index = delta_index
            raise
    states.clear()
    states.update(proposed)
    return len(raw_deltas)


def _apply_delta(raw_delta: Any, states: dict[str, _LedgerState]) -> None:
    if not isinstance(raw_delta, Mapping):
        raise _AuditIssue("INVALID_DELTA", "allocation delta must be a mapping")
    raw_resource_id = raw_delta.get("resource_id")
    raw_account_from = raw_delta.get("account_from")
    raw_account_to = raw_delta.get("account_to")
    schema_accounts = {
        "account_from": raw_account_from,
        "account_to": raw_account_to,
    }
    _require_exact_keys(
        raw_delta,
        _DELTA_KEYS,
        "allocation delta",
        resource_id=raw_resource_id if isinstance(raw_resource_id, str) else None,
        accounts=schema_accounts,
    )
    resource_id = _required_string(raw_delta, "resource_id", "INVALID_RESOURCE_ID")
    state = states.get(resource_id)
    if state is None:
        raise _AuditIssue(
            "UNKNOWN_RESOURCE",
            f"journal references unknown capacity resource {resource_id!r}",
            resource_id=resource_id,
        )
    _required_string(raw_delta, "allocation_id", "INVALID_ALLOCATION_ID")
    for optional_id in ("object_id", "replica_id", "transfer_id"):
        value = raw_delta.get(optional_id)
        if value is not None and (not isinstance(value, str) or not value):
            raise _AuditIssue(
                "INVALID_OPTIONAL_ID",
                f"{optional_id} must be null or a non-empty string",
                resource_id=resource_id,
            )
    account_from = _required_string(raw_delta, "account_from", "INVALID_ACCOUNT")
    account_to = _required_string(raw_delta, "account_to", "INVALID_ACCOUNT")
    if account_from == account_to:
        raise _AuditIssue(
            "IDENTICAL_ACCOUNTS",
            "account_from and account_to must differ",
            resource_id=resource_id,
            accounts={"account_from": account_from, "account_to": account_to},
        )
    delta_bytes = _required_int(raw_delta, "delta_bytes", positive=True)
    capacity_bytes = _required_int(raw_delta, "capacity_bytes", positive=True)
    recorded_from_before = _required_int(raw_delta, "from_before_bytes", non_negative=True)
    recorded_from_after = _required_int(raw_delta, "from_after_bytes", non_negative=True)
    recorded_to_before = _required_int(raw_delta, "to_before_bytes", non_negative=True)
    recorded_to_after = _required_int(raw_delta, "to_after_bytes", non_negative=True)
    actual_from_before = state.accounts.get(account_from, 0)
    actual_to_before = state.accounts.get(account_to, 0)
    context: dict[str, Any] = {
        "account_from": account_from,
        "account_to": account_to,
        "delta_bytes": delta_bytes,
        "recorded_from_before_bytes": recorded_from_before,
        "recorded_from_after_bytes": recorded_from_after,
        "recorded_to_before_bytes": recorded_to_before,
        "recorded_to_after_bytes": recorded_to_after,
        "replay_from_before_bytes": actual_from_before,
        "replay_to_before_bytes": actual_to_before,
    }
    if capacity_bytes != state.capacity_bytes:
        raise _AuditIssue(
            "CAPACITY_MISMATCH",
            f"recorded capacity {capacity_bytes} differs from {state.capacity_bytes}",
            resource_id=resource_id,
            accounts=context,
        )
    if actual_from_before != recorded_from_before or actual_to_before != recorded_to_before:
        raise _AuditIssue(
            "BEFORE_MISMATCH",
            "recorded before values do not match replay state",
            resource_id=resource_id,
            accounts=context,
        )
    computed_from_after = actual_from_before - delta_bytes
    computed_to_after = actual_to_before + delta_bytes
    context["computed_from_after_bytes"] = computed_from_after
    context["computed_to_after_bytes"] = computed_to_after
    if computed_from_after < 0:
        raise _AuditIssue(
            "NEGATIVE_ACCOUNT",
            "delta would make account_from negative",
            resource_id=resource_id,
            accounts=context,
        )
    if (
        computed_from_after != recorded_from_after
        or computed_to_after != recorded_to_after
    ):
        raise _AuditIssue(
            "AFTER_MISMATCH",
            "recorded after values do not equal before plus/minus delta",
            resource_id=resource_id,
            accounts=context,
        )
    state.accounts[account_from] = computed_from_after
    state.accounts[account_to] = computed_to_after
    _validate_accounts(
        state.accounts,
        capacity_bytes=state.capacity_bytes,
        resource_id=resource_id,
        code_prefix="TRANSACTION",
    )


def _require_exact_keys(
    data: Mapping[str, Any],
    expected: set[str],
    location: str,
    *,
    resource_id: str | None = None,
    accounts: dict[str, Any] | None = None,
) -> None:
    actual = set(data)
    missing = sorted(expected - actual)
    unknown = sorted(repr(key) for key in actual - expected)
    if missing or unknown:
        raise _AuditIssue(
            "SCHEMA_MISMATCH",
            f"{location} fields differ: missing={missing}, unknown={unknown}",
            resource_id=resource_id,
            accounts=accounts,
        )


def _required_string(data: Mapping[str, Any], key: str, code: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise _AuditIssue(code, f"{key} must be a non-empty string")
    return value


def _attach_delta_context(issue: _AuditIssue, raw_delta: Any) -> None:
    if not isinstance(raw_delta, Mapping):
        return
    resource_id = raw_delta.get("resource_id")
    if issue.resource_id is None and isinstance(resource_id, str):
        issue.resource_id = resource_id
    if issue.accounts is not None:
        return
    account_fields = (
        "account_from",
        "account_to",
        "delta_bytes",
        "from_before_bytes",
        "from_after_bytes",
        "to_before_bytes",
        "to_after_bytes",
    )
    issue.accounts = {
        field: raw_delta[field]
        for field in account_fields
        if field in raw_delta
    }


def _required_int(
    data: Mapping[str, Any],
    key: str,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> int:
    value = data.get(key)
    if type(value) is not int:
        raise _AuditIssue("INVALID_INTEGER", f"{key} must be an integer")
    if positive and value <= 0:
        raise _AuditIssue("INVALID_INTEGER", f"{key} must be positive")
    if non_negative and value < 0:
        raise _AuditIssue("INVALID_INTEGER", f"{key} must be non-negative")
    return value


def _snapshot_bytes(states: Mapping[str, _LedgerState]) -> bytes:
    payload = {
        "schema": CAPACITY_SNAPSHOT_SCHEMA,
        "resources": [
            {
                "resource_id": state.resource_id,
                "resource_kind": state.resource_kind,
                "capacity_bytes": state.capacity_bytes,
                "accounts": dict(sorted(state.accounts.items())),
            }
            for _, state in sorted(states.items())
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _journal_prefix_bytes(records: Sequence[JournalRecord], record_count: int) -> bytes:
    lines = [
        json.dumps(
            asdict(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for record in records[:record_count]
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode()


def _minimal_prefix(
    records: Sequence[JournalRecord], failure_record_index: int | None
) -> MinimalReplayPrefix:
    record_count = 0 if failure_record_index is None else failure_record_index + 1
    prefix = _journal_prefix_bytes(records, record_count)
    sequence = None
    if record_count:
        sequence = _safe_sequence(records[record_count - 1])
    return MinimalReplayPrefix(
        record_count=record_count,
        inclusive_journal_sequence=sequence,
        sha256=_sha256(prefix),
    )


def _failure_audit(
    issue: _AuditIssue,
    *,
    records: Sequence[JournalRecord],
    failure_record_index: int | None,
    event_id: str | None,
    journal_sequence: int | None,
    checked_journal_records: int,
    checked_transactions: int,
    checked_deltas: int,
    initial_sha256: str | None,
    online_sha256: str | None,
    replayed_sha256: str | None,
) -> CapacityAudit:
    failure = CapacityAuditFailure(
        code=issue.code,
        message=str(issue),
        journal_sequence=journal_sequence,
        event_id=event_id,
        resource_id=issue.resource_id,
        accounts=issue.accounts,
        delta_index=issue.delta_index,
        minimal_replay_prefix=_minimal_prefix(records, failure_record_index),
    )
    return CapacityAudit(
        schema=CAPACITY_AUDIT_SCHEMA,
        status="FAIL",
        valid=False,
        checked_journal_record_count=checked_journal_records,
        checked_transaction_count=checked_transactions,
        checked_delta_count=checked_deltas,
        initial_snapshot_sha256=initial_sha256,
        online_final_snapshot_sha256=online_sha256,
        replayed_final_snapshot_sha256=replayed_sha256,
        final_snapshot_sha256=None,
        final_snapshot_byte_identical=False,
        first_failure=failure,
    )


def _first_snapshot_difference(
    replayed: Mapping[str, _LedgerState], online: Mapping[str, _LedgerState]
) -> tuple[str | None, dict[str, Any]]:
    for resource_id in sorted(set(replayed) | set(online)):
        replayed_state = replayed.get(resource_id)
        online_state = online.get(resource_id)
        if replayed_state is None or online_state is None:
            return resource_id, {
                "replayed_present": replayed_state is not None,
                "online_present": online_state is not None,
            }
        if (
            replayed_state.resource_kind != online_state.resource_kind
            or replayed_state.capacity_bytes != online_state.capacity_bytes
        ):
            return resource_id, {
                "replayed_resource_kind": replayed_state.resource_kind,
                "online_resource_kind": online_state.resource_kind,
                "replayed_capacity_bytes": replayed_state.capacity_bytes,
                "online_capacity_bytes": online_state.capacity_bytes,
            }
        for account in sorted(set(replayed_state.accounts) | set(online_state.accounts)):
            replayed_bytes = replayed_state.accounts.get(account, 0)
            online_bytes = online_state.accounts.get(account, 0)
            if replayed_bytes != online_bytes:
                return resource_id, {
                    "account": account,
                    "replayed_bytes": replayed_bytes,
                    "online_bytes": online_bytes,
                    "replayed_accounts": dict(sorted(replayed_state.accounts.items())),
                    "online_accounts": dict(sorted(online_state.accounts.items())),
                }
    return None, {"reason": "canonical bytes differ without a decoded state difference"}


def _record_event_id(record: JournalRecord) -> str | None:
    if isinstance(record.data, Mapping):
        value = record.data.get("event_id")
        if isinstance(value, str):
            return value
    return None


def _safe_sequence(record: JournalRecord) -> int | None:
    return record.journal_sequence if type(record.journal_sequence) is int else None


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
