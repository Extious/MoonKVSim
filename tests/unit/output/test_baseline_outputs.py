from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from moonkvsim.output import (
    OutputContractError,
    ParquetUnavailableError,
    ResourceLedgerDeltaRow,
    build_flow_rate_event_rows,
    derive_capacity_artifacts,
    event_journal_jsonl_bytes,
    extract_resource_ledger_delta_rows,
    flow_rate_events_jsonl_bytes,
    resource_ledger_deltas_jsonl_bytes,
    write_event_journal_jsonl,
    write_resource_ledger_deltas_parquet,
)
from moonkvsim.simulation.allocation import AllocationState, PhysicalAllocation
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.network import ActiveFlow, FlowContentionModel
from moonkvsim.simulation.resource import RateResource
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction


def ledger() -> CapacityLedger:
    return CapacityLedger(
        resource_id="gpu-0.hbm",
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=100,
    )


def resource_rows_fixture() -> tuple[
    CapacityLedger,
    CapacityLedger,
    EventJournal,
    tuple[ResourceLedgerDeltaRow, ...],
]:
    initial = ledger()
    online = ledger()
    journal = EventJournal()
    allocation = PhysicalAllocation(
        allocation_id="allocation-0",
        object_id="object-0",
        replica_id="replica-0",
        resource_id=online.resource_id,
        owner_account="PENDING",
        payload_bytes=70,
        requested_bytes=70,
        allocated_bytes=80,
        padding_bytes=0,
        allocator_metadata_bytes=2,
        internal_fragmentation_bytes=8,
        alignment_bytes=16,
        state=AllocationState.PENDING,
        created_at_ns=5,
    )
    ResourceTransaction(
        event_id="reserve",
        timestamp_ns=5,
        cause="INFERENCE_PRIMARY_KV",
        allocation_deltas=[
            AllocationDelta(
                resource_id=online.resource_id,
                account_from="FREE",
                account_to="PENDING",
                delta_bytes=80,
                allocation_id=allocation.allocation_id,
                object_id=allocation.object_id,
                replica_id=allocation.replica_id,
            )
        ],
    ).commit({online.resource_id: online}, journal=journal)
    # Geometry may be journaled after the reservation. Extraction deliberately
    # scans the full canonical journal instead of guessing delta=requested.
    AllocationRegistry(journal=journal).add(
        allocation,
        timestamp_ns=5,
        event_id="allocation-added",
    )
    ResourceTransaction(
        event_id="release",
        timestamp_ns=5,
        cause="EVICTION",
        allocation_deltas=[
            AllocationDelta(
                resource_id=online.resource_id,
                account_from="PENDING",
                account_to="FREE",
                delta_bytes=80,
                allocation_id=allocation.allocation_id,
                object_id=allocation.object_id,
                replica_id=allocation.replica_id,
            )
        ],
    ).commit({online.resource_id: online}, journal=journal)
    rows = extract_resource_ledger_delta_rows(
        journal,
        {online.resource_id: online},
    )
    return initial, online, journal, rows


def test_event_journal_jsonl_is_canonical_and_byte_identical(tmp_path: Path) -> None:
    first = EventJournal()
    first.append(0, "RUN_STARTED", {"z": [2, 1], "a": "值"})
    second = EventJournal()
    second.append(0, "RUN_STARTED", {"a": "值", "z": [2, 1]})

    assert event_journal_jsonl_bytes(first) == event_journal_jsonl_bytes(second)
    decoded = json.loads(event_journal_jsonl_bytes(first))
    assert decoded["journal_sequence"] == 0
    assert decoded["data"] == {"a": "值", "z": [2, 1]}

    output = tmp_path / "event-journal.jsonl"
    write_event_journal_jsonl(first, output)
    assert output.read_bytes() == event_journal_jsonl_bytes(first)
    original_bytes = output.read_bytes()
    with pytest.raises(FileExistsError):
        write_event_journal_jsonl(second, output)
    assert output.read_bytes() == original_bytes
    write_event_journal_jsonl(second, output, overwrite=True)
    assert output.read_bytes() == event_journal_jsonl_bytes(second)
    with pytest.raises(FileExistsError):
        first.write(output)
    first.write(output, overwrite=True)
    assert output.read_bytes() == first.to_jsonl_bytes()
    with pytest.raises(OutputContractError, match=r"\.jsonl"):
        write_event_journal_jsonl(first, tmp_path / "not-parquet.parquet")


def test_resource_delta_rows_are_typed_sorted_and_do_not_invent_geometry() -> None:
    _initial, online, _journal, untyped_rows = resource_rows_fixture()
    rows = tuple(untyped_rows)

    assert [row.event_id for row in rows] == ["reserve", "release"]
    assert rows[0].requested_bytes == 70
    assert rows[0].allocated_bytes == rows[0].delta_bytes == 80
    assert rows[0].before_bytes == rows[0].to_before_bytes == 0
    assert rows[0].after_bytes == rows[0].to_after_bytes == 80
    assert resource_ledger_deltas_jsonl_bytes(rows[::-1]) == (
        resource_ledger_deltas_jsonl_bytes(rows)
    )

    journal_without_geometry = EventJournal()
    ResourceTransaction(
        event_id="unknown-shape",
        timestamp_ns=0,
        cause="TEST",
        allocation_deltas=[AllocationDelta("gpu-0.hbm", "FREE", "PENDING", 1, "missing")],
    ).commit({online.resource_id: ledger()}, journal=journal_without_geometry)
    with pytest.raises(OutputContractError, match="missing requested/allocated geometry"):
        extract_resource_ledger_delta_rows(
            journal_without_geometry,
            {online.resource_id: online},
        )

    with pytest.raises(OutputContractError, match="complete physical allocation"):
        replace(rows[0], delta_bytes=79)


def test_resource_delta_rows_use_explicit_transfer_staging_geometry() -> None:
    host = CapacityLedger(
        resource_id="host-staging",
        resource_kind=CapacityResourceKind.HOST_DRAM,
        capacity_bytes=256,
    )
    journal = EventJournal()
    journal.append(
        0,
        "TRANSFER_RESOURCE_LEASE_ACQUIRED",
        {
            "staging_allocations": [
                {
                    "allocation_id": "staging-0",
                    "requested_bytes": 70,
                    "allocated_bytes": 80,
                }
            ]
        },
    )
    ResourceTransaction(
        event_id="staging-acquire",
        timestamp_ns=0,
        cause="TCP_HOST_STAGED",
        allocation_deltas=[
            AllocationDelta(
                host.resource_id,
                "FREE",
                "HOST_STAGING:staging-0",
                80,
                "staging-0",
            )
        ],
    ).commit({host.resource_id: host}, journal=journal)

    [row] = extract_resource_ledger_delta_rows(journal, {host.resource_id: host})

    assert row.requested_bytes == 70
    assert row.allocated_bytes == row.delta_bytes == 80


def test_capacity_summary_preserves_zero_duration_event_boundary_peak(
    tmp_path: Path,
) -> None:
    initial, online, _journal, untyped_rows = resource_rows_fixture()
    rows = tuple(untyped_rows)

    audit, summary = derive_capacity_artifacts(
        {initial.resource_id: initial},
        rows,
        expected_final_ledgers={online.resource_id: online},
    )

    assert audit.valid
    assert audit.checked_delta_count == 2
    assert audit.byte_conservation_at_every_event_boundary
    assert audit.expected_final_snapshot_byte_identical
    assert summary is not None
    pending = next(
        account for account in summary.resources[0].accounts if account.account == "PENDING"
    )
    # Both deltas happen at t=5. Any periodic start/end sample can see zero,
    # while event-boundary replay must retain the transient 80-byte peak.
    assert pending.initial_bytes == pending.final_bytes == 0
    assert pending.peak_bytes == 80
    assert pending.peak_timestamp_ns == 5
    assert pending.peak_stable_sequence == rows[0].stable_sequence
    assert summary.event_boundary_peaks_preserved
    assert summary.to_json_bytes() == summary.to_json_bytes()
    summary_path = tmp_path / "summary.json"
    summary.write(summary_path)
    original_bytes = summary_path.read_bytes()
    with pytest.raises(FileExistsError):
        summary.write(summary_path)
    assert summary_path.read_bytes() == original_bytes
    summary.write(summary_path, overwrite=True)
    assert summary_path.read_bytes() == summary.to_json_bytes()


def test_capacity_audit_fails_closed_before_summary_on_replay_mismatch() -> None:
    initial, _online, _journal, untyped_rows = resource_rows_fixture()
    rows = tuple(untyped_rows)
    bad_first = replace(
        rows[0],
        from_before_bytes=90,
        from_after_bytes=10,
    )

    audit, summary = derive_capacity_artifacts(
        {initial.resource_id: initial},
        (bad_first, rows[1]),
    )

    assert not audit.valid
    assert audit.status == "FAIL"
    assert audit.first_failure is not None
    assert audit.first_failure.code == "BEFORE_MISMATCH"
    assert summary is None


def test_flow_rows_preserve_rate_boundaries_and_conserve_payload_bytes() -> None:
    model = FlowContentionModel([RateResource("nic", 100.0)])
    first = ActiveFlow(
        flow_id="a",
        transfer_id="transfer-a",
        slice_id="slice-a",
        cause="MOONCAKE_PUT",
        path_resource_ids=("nic",),
        payload_bytes=100,
        remaining_bytes=100.0,
    )
    second = ActiveFlow(
        flow_id="b",
        transfer_id="transfer-b",
        slice_id="slice-b",
        cause="MOONCAKE_PUT",
        path_resource_ids=("nic",),
        payload_bytes=50,
        remaining_bytes=50.0,
    )
    model.add_flow(first, now_ns=0)
    model.add_flow(second, now_ns=500_000_000)
    model.complete_flows(now_ns=1_500_000_000)

    rows = build_flow_rate_event_rows(
        model.intervals,
        queue_wait_ns_by_flow={"a": 7, "b": 11},
    )

    a_rows = [row for row in rows if row.flow_id == "a"]
    assert [row.allocated_rate_Bps for row in a_rows] == [100.0, 50.0]
    assert [row.queue_wait_ns for row in a_rows] == [7, 0]
    assert sum(row.transferred_bytes for row in a_rows) == pytest.approx(100.0)
    assert a_rows[-1].remaining_bytes_at_end == 0
    assert flow_rate_events_jsonl_bytes(rows[::-1]) == flow_rate_events_jsonl_bytes(rows)


def test_parquet_path_fails_closed_without_pyarrow(tmp_path: Path) -> None:
    if importlib.util.find_spec("pyarrow") is not None:
        pytest.skip("this gate specifically covers the dependency-absent path")
    _initial, _online, _journal, untyped_rows = resource_rows_fixture()
    output = tmp_path / "resource-ledger-deltas.parquet"

    with pytest.raises(ParquetUnavailableError, match="optional 'trace' dependency"):
        write_resource_ledger_deltas_parquet(tuple(untyped_rows), output)

    assert not output.exists()
