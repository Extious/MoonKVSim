from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from moonkvsim.simulation.audit import (
    CAPACITY_AUDIT_SCHEMA,
    capacity_snapshot_bytes,
    generate_capacity_audit,
)
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction


def make_ledger(resource_id: str = "gpu-0.hbm") -> CapacityLedger:
    return CapacityLedger(
        resource_id=resource_id,
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=100,
        initial_accounts={"MODEL_WEIGHTS": 20},
    )


def commit_transfer(
    ledger: CapacityLedger,
    journal: EventJournal,
    *,
    event_id: str,
    timestamp_ns: int,
    account_from: str,
    account_to: str,
    delta_bytes: int,
) -> None:
    ResourceTransaction(
        event_id=event_id,
        timestamp_ns=timestamp_ns,
        cause="TEST_CAPACITY_AUDIT",
        allocation_deltas=[
            AllocationDelta(
                resource_id=ledger.resource_id,
                account_from=account_from,
                account_to=account_to,
                delta_bytes=delta_bytes,
                allocation_id=f"allocation-{event_id}",
            )
        ],
    ).commit({ledger.resource_id: ledger}, journal=journal)


def test_success_replays_to_byte_identical_snapshot_and_writes_artifact(tmp_path: Path) -> None:
    initial = make_ledger()
    online = make_ledger()
    journal = EventJournal()
    journal.append(0, "RUN_STARTED", {"event_id": "run-0"})
    commit_transfer(
        online,
        journal,
        event_id="reserve-0",
        timestamp_ns=1,
        account_from="FREE",
        account_to="PENDING_REPLICA",
        delta_bytes=30,
    )
    commit_transfer(
        online,
        journal,
        event_id="release-0",
        timestamp_ns=2,
        account_from="PENDING_REPLICA",
        account_to="FREE",
        delta_bytes=10,
    )

    audit = generate_capacity_audit(
        initial_ledgers={initial.resource_id: initial},
        journal=journal,
        online_final_ledgers={online.resource_id: online},
    )

    assert audit.status == "PASS"
    assert audit.valid
    assert audit.schema == CAPACITY_AUDIT_SCHEMA
    assert audit.checked_journal_record_count == 3
    assert audit.checked_transaction_count == 2
    assert audit.checked_delta_count == 2
    assert audit.final_snapshot_byte_identical
    assert audit.first_failure is None
    assert audit.final_snapshot_sha256 == hashlib.sha256(
        capacity_snapshot_bytes({online.resource_id: online})
    ).hexdigest()
    assert audit.replayed_final_snapshot_sha256 == audit.online_final_snapshot_sha256
    assert initial.accounts == {"MODEL_WEIGHTS": 20, "FREE": 80}

    output = tmp_path / "capacity-audit.json"
    audit.write(output)
    assert output.read_bytes() == audit.to_json_bytes()
    original_bytes = output.read_bytes()
    with pytest.raises(FileExistsError):
        audit.write(output)
    assert output.read_bytes() == original_bytes
    audit.write(output, overwrite=True)
    assert output.read_bytes() == audit.to_json_bytes()
    assert json.loads(output.read_text())["status"] == "PASS"
    assert generate_capacity_audit(
        initial_ledgers={initial.resource_id: initial},
        journal=journal,
        online_final_ledgers={online.resource_id: online},
    ).to_json_bytes() == audit.to_json_bytes()


def test_before_mismatch_reports_first_context_and_minimal_prefix() -> None:
    initial = make_ledger()
    online = make_ledger()
    journal = EventJournal()
    journal.append(0, "RUN_STARTED", {"event_id": "run-0"})
    commit_transfer(
        online,
        journal,
        event_id="reserve-0",
        timestamp_ns=1,
        account_from="FREE",
        account_to="PENDING_REPLICA",
        delta_bytes=10,
    )
    commit_transfer(
        online,
        journal,
        event_id="reserve-1",
        timestamp_ns=2,
        account_from="FREE",
        account_to="PENDING_REPLICA",
        delta_bytes=5,
    )
    failing_delta = journal.records[2].data["allocation_deltas"][0]
    failing_delta["from_before_bytes"] += 1

    audit = generate_capacity_audit(
        initial_ledgers={initial.resource_id: initial},
        journal=journal,
        online_final_ledgers={online.resource_id: online},
    )

    assert audit.status == "FAIL"
    assert not audit.valid
    assert audit.checked_journal_record_count == 2
    assert audit.checked_transaction_count == 1
    assert audit.checked_delta_count == 1
    assert audit.first_failure is not None
    assert audit.first_failure.code == "BEFORE_MISMATCH"
    assert audit.first_failure.journal_sequence == 2
    assert audit.first_failure.event_id == "reserve-1"
    assert audit.first_failure.resource_id == "gpu-0.hbm"
    assert audit.first_failure.accounts is not None
    assert audit.first_failure.accounts["account_from"] == "FREE"
    assert audit.first_failure.accounts["account_to"] == "PENDING_REPLICA"
    assert audit.first_failure.delta_index == 0
    prefix = audit.first_failure.minimal_replay_prefix
    assert prefix.record_count == 3
    assert prefix.inclusive_journal_sequence == 2
    assert prefix.sha256 == hashlib.sha256(journal.to_jsonl_bytes()).hexdigest()


def test_after_arithmetic_mismatch_fails_closed() -> None:
    initial = make_ledger()
    online = make_ledger()
    journal = EventJournal()
    commit_transfer(
        online,
        journal,
        event_id="reserve-0",
        timestamp_ns=1,
        account_from="FREE",
        account_to="PENDING_REPLICA",
        delta_bytes=10,
    )
    journal.records[0].data["allocation_deltas"][0]["to_after_bytes"] += 1

    audit = generate_capacity_audit(
        initial_ledgers={initial.resource_id: initial},
        journal=journal,
        online_final_ledgers={online.resource_id: online},
    )

    assert audit.first_failure is not None
    assert audit.first_failure.code == "AFTER_MISMATCH"
    assert audit.first_failure.journal_sequence == 0
    assert audit.first_failure.event_id == "reserve-0"


def test_invalid_initial_conservation_has_empty_replay_prefix() -> None:
    initial = make_ledger()
    online = make_ledger()
    initial._accounts["FREE"] += 1

    audit = generate_capacity_audit(
        initial_ledgers={initial.resource_id: initial},
        journal=EventJournal(),
        online_final_ledgers={online.resource_id: online},
    )

    assert audit.first_failure is not None
    assert audit.first_failure.code == "INITIAL_LEDGER_CONSERVATION_FAILURE"
    assert audit.first_failure.resource_id == "gpu-0.hbm"
    assert audit.first_failure.journal_sequence is None
    assert audit.first_failure.minimal_replay_prefix.record_count == 0
    assert audit.first_failure.minimal_replay_prefix.sha256 == hashlib.sha256(b"").hexdigest()


def test_final_snapshot_mismatch_reports_full_prefix_and_first_account() -> None:
    initial = make_ledger()
    actual_online = make_ledger()
    stale_online_snapshot = make_ledger()
    journal = EventJournal()
    commit_transfer(
        actual_online,
        journal,
        event_id="reserve-0",
        timestamp_ns=1,
        account_from="FREE",
        account_to="PENDING_REPLICA",
        delta_bytes=10,
    )

    audit = generate_capacity_audit(
        initial_ledgers={initial.resource_id: initial},
        journal=journal,
        online_final_ledgers={stale_online_snapshot.resource_id: stale_online_snapshot},
    )

    assert audit.first_failure is not None
    assert audit.first_failure.code == "FINAL_SNAPSHOT_MISMATCH"
    assert audit.first_failure.event_id == "CAPACITY_AUDIT_FINAL_SNAPSHOT"
    assert audit.first_failure.journal_sequence == 0
    assert audit.first_failure.resource_id == "gpu-0.hbm"
    assert audit.first_failure.accounts is not None
    assert audit.first_failure.accounts["account"] in {"FREE", "PENDING_REPLICA"}
    assert audit.first_failure.minimal_replay_prefix.record_count == 1
    assert audit.checked_transaction_count == 1
    assert audit.replayed_final_snapshot_sha256 != audit.online_final_snapshot_sha256
    assert audit.final_snapshot_sha256 is None


def test_journal_sequence_gap_fails_at_first_record() -> None:
    initial = make_ledger()
    online = make_ledger()
    journal = EventJournal()
    commit_transfer(
        online,
        journal,
        event_id="reserve-0",
        timestamp_ns=1,
        account_from="FREE",
        account_to="PENDING_REPLICA",
        delta_bytes=10,
    )
    journal._records[0] = replace(journal.records[0], journal_sequence=4)

    audit = generate_capacity_audit(
        initial_ledgers={initial.resource_id: initial},
        journal=journal,
        online_final_ledgers={online.resource_id: online},
    )

    assert audit.first_failure is not None
    assert audit.first_failure.code == "JOURNAL_SEQUENCE_MISMATCH"
    assert audit.first_failure.journal_sequence == 4
    assert audit.first_failure.event_id == "reserve-0"
    assert audit.first_failure.minimal_replay_prefix.record_count == 1


def test_unknown_delta_field_fails_schema_closed() -> None:
    initial = make_ledger()
    online = make_ledger()
    journal = EventJournal()
    commit_transfer(
        online,
        journal,
        event_id="reserve-0",
        timestamp_ns=1,
        account_from="FREE",
        account_to="PENDING_REPLICA",
        delta_bytes=10,
    )
    journal.records[0].data["allocation_deltas"][0]["implicit_fallback"] = True

    audit = generate_capacity_audit(
        initial_ledgers={initial.resource_id: initial},
        journal=journal,
        online_final_ledgers={online.resource_id: online},
    )

    assert audit.first_failure is not None
    assert audit.first_failure.code == "SCHEMA_MISMATCH"
    assert "implicit_fallback" in audit.first_failure.message
    assert audit.first_failure.resource_id == "gpu-0.hbm"
    assert audit.first_failure.accounts == {
        "account_from": "FREE",
        "account_to": "PENDING_REPLICA",
    }


def test_journal_failure_precedes_invalid_online_final_snapshot() -> None:
    initial = make_ledger()
    online = make_ledger()
    journal = EventJournal()
    commit_transfer(
        online,
        journal,
        event_id="reserve-0",
        timestamp_ns=1,
        account_from="FREE",
        account_to="PENDING_REPLICA",
        delta_bytes=10,
    )
    journal.records[0].data["allocation_deltas"][0]["from_before_bytes"] += 1
    online._accounts["FREE"] += 1

    audit = generate_capacity_audit(
        initial_ledgers={initial.resource_id: initial},
        journal=journal,
        online_final_ledgers={online.resource_id: online},
    )

    assert audit.first_failure is not None
    assert audit.first_failure.code == "BEFORE_MISMATCH"
    assert audit.first_failure.journal_sequence == 0


def test_invalid_online_snapshot_needs_no_journal_prefix() -> None:
    initial = make_ledger()
    online = make_ledger()
    journal = EventJournal()
    journal.append(0, "RUN_STARTED", {"event_id": "run-0"})
    online._accounts["FREE"] += 1

    audit = generate_capacity_audit(
        initial_ledgers={initial.resource_id: initial},
        journal=journal,
        online_final_ledgers={online.resource_id: online},
    )

    assert audit.first_failure is not None
    assert audit.first_failure.code == "ONLINE_FINAL_LEDGER_CONSERVATION_FAILURE"
    assert audit.first_failure.journal_sequence is None
    assert audit.first_failure.minimal_replay_prefix.record_count == 0


def test_snapshot_is_stable_across_mapping_order() -> None:
    first = make_ledger("gpu-0.hbm")
    second = make_ledger("gpu-1.hbm")

    forward = capacity_snapshot_bytes({first.resource_id: first, second.resource_id: second})
    reverse = capacity_snapshot_bytes({second.resource_id: second, first.resource_id: first})

    assert forward == reverse


def test_multiple_transactions_may_share_a_simulation_event_id() -> None:
    initial = make_ledger()
    online = make_ledger()
    journal = EventJournal()
    commit_transfer(
        online,
        journal,
        event_id="event-0",
        timestamp_ns=1,
        account_from="FREE",
        account_to="PENDING_REPLICA",
        delta_bytes=10,
    )
    commit_transfer(
        online,
        journal,
        event_id="event-0",
        timestamp_ns=1,
        account_from="PENDING_REPLICA",
        account_to="COMMITTED_REPLICA",
        delta_bytes=10,
    )

    audit = generate_capacity_audit(
        initial_ledgers={initial.resource_id: initial},
        journal=journal,
        online_final_ledgers={online.resource_id: online},
    )

    assert audit.valid
    assert audit.checked_transaction_count == 2
