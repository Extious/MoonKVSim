from __future__ import annotations

import copy

import pytest

from moonkvsim.aegiskv.audit import (
    AegisAuditError,
    AegisAuditEvent,
    AegisE2AuditReport,
    load_aegis_e2_audit,
    validate_aegis_e2_audit,
)
from moonkvsim.common.hash import sha256_json


def events() -> tuple[AegisAuditEvent, ...]:
    return (
        AegisAuditEvent.from_payload(
            event_id="failure-0",
            event_type="GPU_FAILURE",
            timestamp_ns=100,
            priority=0,
            stable_sequence=5,
            data={"gpu_id": "node-0.gpu-1"},
        ),
        AegisAuditEvent.from_payload(
            event_id="fence-0",
            event_type="ROUTE_FENCE",
            timestamp_ns=100,
            priority=10,
            stable_sequence=3,
            data={"request_id": "request-0", "route_version": 0},
        ),
        AegisAuditEvent.from_payload(
            event_id="recovery-plan-0",
            event_type="AEGIS_RECOVERY_PLANNED",
            timestamp_ns=120,
            priority=50,
            stable_sequence=6,
            data={"source_kinds": ["PEER_HBM", "STORE_DRAM", "RECOMPUTE"]},
        ),
    )


def report() -> AegisE2AuditReport:
    return AegisE2AuditReport.build(
        events(),
        source_fingerprints={
            "patent_contract": "a" * 64,
            "source_tree": "b" * 64,
        },
    )


def test_audit_is_canonical_and_explicitly_capped_at_modeled_e2() -> None:
    audit = report()
    document = load_aegis_e2_audit(audit.to_json_bytes())

    assert document == audit.to_dict()
    assert document["evidence_boundary"] == {
        "calibration_status": "not_calibrated",
        "evidence_class": "E2",
        "execution_scope": "pure_GlobalDES",
        "formal_claim_allowed": False,
        "performance_claim_allowed": False,
        "physical_component_executed": False,
        "result_status": "modeled/preliminary",
        "slurm_used": False,
    }
    assert document["patent_review"] == {
        "contract_status": "machine_transcribed_pending_manual_review",
        "manual_review": "pending",
    }
    assert document["event_count"] == 3
    assert document["event_type_counts"] == {
        "AEGIS_RECOVERY_PLANNED": 1,
        "GPU_FAILURE": 1,
        "ROUTE_FENCE": 1,
    }


def test_same_timestamp_uses_priority_then_stable_sequence() -> None:
    valid = events()
    assert valid[0].stable_sequence > valid[1].stable_sequence
    assert valid[0].priority < valid[1].priority
    assert report().to_dict()["clock"] == {
        "first_timestamp_ns": 100,
        "global_virtual_clock": True,
        "last_timestamp_ns": 120,
        "ordering_key": ["timestamp_ns", "priority", "stable_sequence"],
        "time_unit": "ns",
    }
    with pytest.raises(AegisAuditError, match="global DES key"):
        AegisE2AuditReport.build(
            tuple(reversed(valid)),
            source_fingerprints={"source_tree": "b" * 64},
        )


def test_audit_rejects_evidence_promotion_and_pending_review_overclaim() -> None:
    document = copy.deepcopy(report().to_dict())
    evidence = document["evidence_boundary"]
    assert isinstance(evidence, dict)
    evidence["calibration_status"] = "calibrated"
    review = document["patent_review"]
    assert isinstance(review, dict)
    review["manual_review"] = "complete"
    document["fingerprint"] = sha256_json(
        {key: value for key, value in document.items() if key != "fingerprint"}
    )

    errors = validate_aegis_e2_audit(document)

    assert any("modeled/not_calibrated" in error for error in errors)
    assert any("explicitly pending" in error for error in errors)


def test_event_or_report_fingerprint_tampering_fails_closed() -> None:
    document = copy.deepcopy(report().to_dict())
    raw_events = document["events"]
    assert isinstance(raw_events, list)
    first = raw_events[0]
    assert isinstance(first, dict)
    data = first["data"]
    assert isinstance(data, dict)
    data["gpu_id"] = "forged"

    errors = validate_aegis_e2_audit(document)

    assert "audit event fingerprint mismatch" in errors
    assert "audit report fingerprint mismatch" in errors


def test_loader_rejects_noncanonical_json() -> None:
    noncanonical = b'{"status": "PASS"}\n'

    with pytest.raises(AegisAuditError, match="canonical"):
        load_aegis_e2_audit(noncanonical)
