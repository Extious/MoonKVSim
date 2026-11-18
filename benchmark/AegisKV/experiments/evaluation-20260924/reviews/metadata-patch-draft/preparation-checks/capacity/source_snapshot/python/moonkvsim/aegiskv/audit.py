"""Canonical E2 audit envelope for the pure-GlobalDES AegisKV layer."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from moonkvsim.common.hash import canonical_json_bytes, sha256_json

AUDIT_SCHEMA = "moonkvsim.aegiskv.globaldes-audit.v1"
EVIDENCE_BOUNDARY: dict[str, object] = {
    "calibration_status": "not_calibrated",
    "evidence_class": "E2",
    "execution_scope": "pure_GlobalDES",
    "formal_claim_allowed": False,
    "performance_claim_allowed": False,
    "physical_component_executed": False,
    "result_status": "modeled/preliminary",
    "slurm_used": False,
}
PATENT_REVIEW_BOUNDARY: dict[str, object] = {
    "contract_status": "machine_transcribed_pending_manual_review",
    "manual_review": "pending",
}
CLAIM_EXCLUSIONS = (
    "formal_correctness_proof",
    "hardware_latency_calibration",
    "physical_runtime_validation",
    "performance_result",
)


class AegisAuditError(ValueError):
    """An Aegis E2 audit document violates its fail-closed envelope."""


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class AegisAuditEvent:
    event_id: str
    event_type: str
    timestamp_ns: int
    priority: int
    stable_sequence: int
    data_json: str

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_type:
            raise AegisAuditError("audit event identifiers must be non-empty")
        if self.timestamp_ns < 0 or self.priority < 0 or self.stable_sequence < 0:
            raise AegisAuditError("audit event DES key must be non-negative")
        try:
            payload = json.loads(self.data_json)
        except json.JSONDecodeError as error:
            raise AegisAuditError("audit event data_json is invalid") from error
        if not isinstance(payload, dict):
            raise AegisAuditError("audit event payload must be a JSON object")
        if canonical_json_bytes(payload).decode() != self.data_json:
            raise AegisAuditError("audit event data_json must be canonical JSON")

    @classmethod
    def from_payload(
        cls,
        *,
        event_id: str,
        event_type: str,
        timestamp_ns: int,
        priority: int,
        stable_sequence: int,
        data: Mapping[str, object],
    ) -> AegisAuditEvent:
        return cls(
            event_id=event_id,
            event_type=event_type,
            timestamp_ns=timestamp_ns,
            priority=priority,
            stable_sequence=stable_sequence,
            data_json=canonical_json_bytes(data).decode(),
        )

    @property
    def des_key(self) -> tuple[int, int, int]:
        return (self.timestamp_ns, self.priority, self.stable_sequence)

    def canonical_fields(self) -> dict[str, object]:
        payload = cast(dict[str, object], json.loads(self.data_json))
        return {
            "data": payload,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "priority": self.priority,
            "stable_sequence": self.stable_sequence,
            "timestamp_ns": self.timestamp_ns,
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        return {**self.canonical_fields(), "fingerprint": self.fingerprint}


@dataclass(frozen=True, slots=True)
class AegisE2AuditReport:
    events: tuple[AegisAuditEvent, ...]
    source_fingerprints: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.events:
            raise AegisAuditError("Aegis audit requires at least one event")
        event_ids = tuple(event.event_id for event in self.events)
        if len(set(event_ids)) != len(event_ids):
            raise AegisAuditError("Aegis audit event ids must be unique")
        des_keys = tuple(event.des_key for event in self.events)
        if len(set(des_keys)) != len(des_keys):
            raise AegisAuditError("Aegis audit DES keys must be unique")
        if tuple(sorted(des_keys)) != des_keys:
            raise AegisAuditError("Aegis audit events must follow the global DES key")
        names = tuple(name for name, _ in self.source_fingerprints)
        if tuple(sorted(set(names))) != names or any(not name for name in names):
            raise AegisAuditError("source fingerprint names must be sorted and unique")
        if any(not _is_sha256(value) for _, value in self.source_fingerprints):
            raise AegisAuditError("source fingerprints must be lowercase SHA-256 values")

    @classmethod
    def build(
        cls,
        events: Sequence[AegisAuditEvent],
        *,
        source_fingerprints: Mapping[str, str],
    ) -> AegisE2AuditReport:
        return cls(
            events=tuple(events),
            source_fingerprints=tuple(sorted(source_fingerprints.items())),
        )

    def canonical_fields(self) -> dict[str, object]:
        type_counts = Counter(event.event_type for event in self.events)
        return {
            "claim_exclusions": list(CLAIM_EXCLUSIONS),
            "clock": {
                "first_timestamp_ns": self.events[0].timestamp_ns,
                "global_virtual_clock": True,
                "last_timestamp_ns": self.events[-1].timestamp_ns,
                "ordering_key": ["timestamp_ns", "priority", "stable_sequence"],
                "time_unit": "ns",
            },
            "event_count": len(self.events),
            "event_type_counts": dict(sorted(type_counts.items())),
            "events": [event.to_dict() for event in self.events],
            "evidence_boundary": dict(EVIDENCE_BOUNDARY),
            "patent_review": dict(PATENT_REVIEW_BOUNDARY),
            "schema": AUDIT_SCHEMA,
            "source_fingerprints": dict(self.source_fingerprints),
            "status": "PASS",
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        return {**self.canonical_fields(), "fingerprint": self.fingerprint}

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict()) + b"\n"


def validate_aegis_e2_audit(document: Mapping[str, object]) -> tuple[str, ...]:
    """Return all structural errors without accepting a weaker evidence boundary."""

    errors: list[str] = []
    expected_keys = {
        "claim_exclusions",
        "clock",
        "event_count",
        "event_type_counts",
        "events",
        "evidence_boundary",
        "fingerprint",
        "patent_review",
        "schema",
        "source_fingerprints",
        "status",
    }
    if set(document) != expected_keys:
        errors.append("audit document keys do not match the v1 schema")
    if document.get("schema") != AUDIT_SCHEMA:
        errors.append("audit schema is not the Aegis GlobalDES v1 schema")
    if document.get("status") != "PASS":
        errors.append("audit status must be PASS")
    if document.get("evidence_boundary") != EVIDENCE_BOUNDARY:
        errors.append("audit evidence boundary must remain E2 modeled/not_calibrated")
    if document.get("patent_review") != PATENT_REVIEW_BOUNDARY:
        errors.append("manual patent review must remain explicitly pending")
    if document.get("claim_exclusions") != list(CLAIM_EXCLUSIONS):
        errors.append("audit claim exclusions changed")

    events = document.get("events")
    event_count = document.get("event_count")
    type_counts: Counter[str] = Counter()
    previous_key: tuple[int, int, int] | None = None
    event_ids: set[str] = set()
    des_keys: set[tuple[int, int, int]] = set()
    if not isinstance(events, list) or not events:
        errors.append("audit events must be a non-empty list")
    else:
        if event_count != len(events):
            errors.append("audit event_count does not match events")
        for raw_event in events:
            if not isinstance(raw_event, dict):
                errors.append("audit event is not an object")
                continue
            event = cast(dict[str, object], raw_event)
            expected_event_keys = {
                "data",
                "event_id",
                "event_type",
                "fingerprint",
                "priority",
                "stable_sequence",
                "timestamp_ns",
            }
            if set(event) != expected_event_keys:
                errors.append("audit event keys do not match the v1 schema")
                continue
            event_id = event.get("event_id")
            event_type = event.get("event_type")
            timestamp_ns = event.get("timestamp_ns")
            priority = event.get("priority")
            stable_sequence = event.get("stable_sequence")
            if not isinstance(event_id, str) or not event_id or event_id in event_ids:
                errors.append("audit event id is empty or duplicated")
            else:
                event_ids.add(event_id)
            if not isinstance(event_type, str) or not event_type:
                errors.append("audit event type is invalid")
            else:
                type_counts[event_type] += 1
            if not all(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0
                for value in (timestamp_ns, priority, stable_sequence)
            ):
                errors.append("audit event DES key is invalid")
            else:
                key = cast(tuple[int, int, int], (timestamp_ns, priority, stable_sequence))
                if key in des_keys or (previous_key is not None and key < previous_key):
                    errors.append("audit event DES ordering is duplicated or decreasing")
                des_keys.add(key)
                previous_key = key
            canonical_event = {key: value for key, value in event.items() if key != "fingerprint"}
            if event.get("fingerprint") != sha256_json(canonical_event):
                errors.append("audit event fingerprint mismatch")
        if document.get("event_type_counts") != dict(sorted(type_counts.items())):
            errors.append("audit event_type_counts do not match events")

    source_fingerprints = document.get("source_fingerprints")
    if not isinstance(source_fingerprints, dict) or not source_fingerprints:
        errors.append("source_fingerprints must be a non-empty object")
    elif any(
        not isinstance(name, str) or not name or not _is_sha256(value)
        for name, value in source_fingerprints.items()
    ):
        errors.append("source_fingerprints contain invalid names or hashes")

    clock = document.get("clock")
    expected_clock_keys = {
        "first_timestamp_ns",
        "global_virtual_clock",
        "last_timestamp_ns",
        "ordering_key",
        "time_unit",
    }
    if not isinstance(clock, dict) or set(clock) != expected_clock_keys:
        errors.append("audit clock is malformed")
    elif events and isinstance(events, list):
        first = events[0] if events else None
        last = events[-1] if events else None
        if (
            clock.get("global_virtual_clock") is not True
            or clock.get("time_unit") != "ns"
            or clock.get("ordering_key") != ["timestamp_ns", "priority", "stable_sequence"]
            or not isinstance(first, dict)
            or not isinstance(last, dict)
            or clock.get("first_timestamp_ns") != first.get("timestamp_ns")
            or clock.get("last_timestamp_ns") != last.get("timestamp_ns")
        ):
            errors.append("audit clock does not bind the event DES range")

    canonical_report = {key: value for key, value in document.items() if key != "fingerprint"}
    if document.get("fingerprint") != sha256_json(canonical_report):
        errors.append("audit report fingerprint mismatch")
    return tuple(errors)


def load_aegis_e2_audit(contents: bytes) -> dict[str, object]:
    """Load canonical newline-terminated JSON and fail on any audit error."""

    try:
        raw = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AegisAuditError("Aegis audit is not valid UTF-8 JSON") from error
    if not isinstance(raw, dict):
        raise AegisAuditError("Aegis audit root must be an object")
    document = cast(dict[str, object], raw)
    if canonical_json_bytes(document) + b"\n" != contents:
        raise AegisAuditError("Aegis audit must be canonical newline-terminated JSON")
    errors = validate_aegis_e2_audit(document)
    if errors:
        raise AegisAuditError("; ".join(errors))
    return document
