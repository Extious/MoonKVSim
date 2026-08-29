import pytest

from moonkvsim.simulation.allocation import AllocationRole, AllocationState, PhysicalAllocation
from moonkvsim.simulation.allocation_registry import (
    AllocationRegistry,
    replay_allocation_registry,
)
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import (
    UNAVAILABLE_CAPACITY_ACCOUNT,
    CapacityLedger,
    CapacityResourceKind,
)


def allocation() -> PhysicalAllocation:
    return PhysicalAllocation(
        allocation_id="alloc-0",
        object_id="object-0",
        replica_id="replica-0",
        resource_id="store-0.segment-0",
        owner_account="COMMITTED_REPLICA",
        payload_bytes=90,
        requested_bytes=96,
        allocated_bytes=100,
        padding_bytes=6,
        allocator_metadata_bytes=1,
        internal_fragmentation_bytes=3,
        alignment_bytes=4,
        state=AllocationState.COMMITTED,
        created_at_ns=0,
    )


def test_roles_pins_and_eligibility_replay_byte_identically() -> None:
    journal = EventJournal()
    registry = AllocationRegistry(journal=journal)
    registry.add(allocation(), timestamp_ns=0, event_id="add")
    registry.add_role("alloc-0", AllocationRole.CACHE_REUSE, timestamp_ns=1, event_id="reuse")
    registry.add_role("alloc-0", AllocationRole.ACTIVE_PRIMARY, timestamp_ns=1, event_id="primary")
    registry.pin_source("alloc-0", timestamp_ns=2, event_id="pin")
    registry.unpin_source("alloc-0", timestamp_ns=3, event_id="unpin")
    registry.set_recovery_eligible("alloc-0", True, timestamp_ns=4, event_id="eligible")
    registry.reaccount(
        "alloc-0",
        "COMMITTED_REPLICA_RECLASSIFIED",
        timestamp_ns=5,
        event_id="reaccount",
    )

    replayed = replay_allocation_registry(journal)

    assert replayed.snapshot_bytes() == registry.snapshot_bytes()


def test_terminal_transition_requires_overlay_cleanup() -> None:
    registry = AllocationRegistry()
    registry.add(allocation(), timestamp_ns=0, event_id="add")
    registry.pin_source("alloc-0", timestamp_ns=1, event_id="pin")

    with pytest.raises(ValueError, match="zero source pins"):
        registry.transition("alloc-0", AllocationState.LOST, timestamp_ns=2, event_id="failure")


def test_registry_audit_detects_capacity_undercharge() -> None:
    registry = AllocationRegistry()
    registry.add(allocation(), timestamp_ns=0, event_id="add")
    ledger = CapacityLedger(
        resource_id="store-0.segment-0",
        resource_kind=CapacityResourceKind.STORE_DRAM,
        capacity_bytes=100,
    )

    with pytest.raises(RuntimeError, match="tracked allocations disagree"):
        registry.audit({ledger.resource_id: ledger})


def test_registry_audit_detects_capacity_overcharge() -> None:
    registry = AllocationRegistry()
    registry.add(allocation(), timestamp_ns=0, event_id="add")
    ledger = CapacityLedger(
        resource_id="store-0.segment-0",
        resource_kind=CapacityResourceKind.STORE_DRAM,
        capacity_bytes=200,
        initial_accounts={"COMMITTED_REPLICA": 101},
    )

    with pytest.raises(RuntimeError, match="tracked=100, charged=101"):
        registry.audit({ledger.resource_id: ledger})


def test_registry_audit_retains_old_account_key_after_reaccount() -> None:
    registry = AllocationRegistry()
    registry.add(allocation(), timestamp_ns=0, event_id="add")
    registry.reaccount("alloc-0", "RECLASSIFIED", timestamp_ns=1, event_id="reaccount")
    ledger = CapacityLedger(
        resource_id="store-0.segment-0",
        resource_kind=CapacityResourceKind.STORE_DRAM,
        capacity_bytes=201,
        initial_accounts={"COMMITTED_REPLICA": 1, "RECLASSIFIED": 100},
    )

    with pytest.raises(RuntimeError, match="COMMITTED_REPLICA"):
        registry.audit({ledger.resource_id: ledger})


def test_unavailable_residual_is_exact_and_replays_byte_identically() -> None:
    journal = EventJournal()
    registry = AllocationRegistry(journal=journal)
    registry.add(allocation(), timestamp_ns=0, event_id="add")
    registry.reaccount(
        "alloc-0",
        UNAVAILABLE_CAPACITY_ACCOUNT,
        timestamp_ns=1,
        event_id="unavailable",
    )
    registry.transition(
        "alloc-0", AllocationState.LOST, timestamp_ns=1, event_id="lost"
    )
    registry.set_unavailable_residual(
        "store-0.segment-0", 50, timestamp_ns=1, event_id="residual"
    )
    ledger = CapacityLedger(
        resource_id="store-0.segment-0",
        resource_kind=CapacityResourceKind.STORE_DRAM,
        capacity_bytes=150,
        initial_accounts={UNAVAILABLE_CAPACITY_ACCOUNT: 150},
    )

    registry.audit({ledger.resource_id: ledger})
    replayed = replay_allocation_registry(journal)
    assert replayed.snapshot_bytes() == registry.snapshot_bytes()

    wrong = CapacityLedger(
        resource_id="store-0.segment-0",
        resource_kind=CapacityResourceKind.STORE_DRAM,
        capacity_bytes=151,
        initial_accounts={UNAVAILABLE_CAPACITY_ACCOUNT: 151},
    )
    with pytest.raises(RuntimeError, match="tracked=150, charged=151"):
        registry.audit({wrong.resource_id: wrong})
