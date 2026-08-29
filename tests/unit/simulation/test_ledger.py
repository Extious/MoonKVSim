import pytest

from moonkvsim.simulation.allocation import AllocationRole, AllocationState, PhysicalAllocation
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.replay import replay_capacity_transactions
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction


def make_ledger(resource_id: str = "gpu-0.hbm") -> CapacityLedger:
    return CapacityLedger(
        resource_id=resource_id,
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=100,
        initial_accounts={"MODEL_WEIGHTS": 20},
    )


def test_transaction_conserves_capacity_and_is_auditable() -> None:
    ledger = make_ledger()
    journal = EventJournal()
    transaction = ResourceTransaction(
        event_id="e0",
        timestamp_ns=10,
        cause="INFERENCE_PRIMARY_KV",
        allocation_deltas=[
            AllocationDelta(
                resource_id=ledger.resource_id,
                account_from="FREE",
                account_to="ACTIVE_PRIMARY_KV",
                delta_bytes=30,
                allocation_id="alloc-0",
            )
        ],
    )

    transaction.commit({ledger.resource_id: ledger}, journal=journal)

    assert ledger.bytes_in("FREE") == 50
    assert ledger.bytes_in("ACTIVE_PRIMARY_KV") == 30
    assert sum(ledger.accounts.values()) == ledger.capacity_bytes
    assert b'"record_type":"RESOURCE_TRANSACTION"' in journal.to_jsonl_bytes()


def test_multi_ledger_transaction_is_atomic_on_failure() -> None:
    first = make_ledger("gpu-0.hbm")
    second = make_ledger("gpu-1.hbm")
    before_first = first.accounts
    before_second = second.accounts
    transaction = ResourceTransaction(
        event_id="e0",
        timestamp_ns=0,
        cause="RECOVERY",
        allocation_deltas=[
            AllocationDelta("gpu-0.hbm", "FREE", "RECOVERY_DEST_RESERVED", 10, "a0"),
            AllocationDelta("gpu-1.hbm", "FREE", "RECOVERY_DEST_RESERVED", 90, "a1"),
        ],
    )

    with pytest.raises(ValueError, match="cannot transfer"):
        transaction.commit({"gpu-0.hbm": first, "gpu-1.hbm": second})

    assert first.accounts == before_first
    assert second.accounts == before_second


def test_logical_roles_do_not_change_physical_bytes() -> None:
    allocation = PhysicalAllocation(
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
        created_at_ns=1,
    )

    dual_role = allocation.with_role(AllocationRole.ACTIVE_PRIMARY).with_role(
        AllocationRole.CACHE_REUSE
    )

    assert dual_role.allocated_bytes == allocation.allocated_bytes
    assert dual_role.roles == {
        AllocationRole.ACTIVE_PRIMARY,
        AllocationRole.CACHE_REUSE,
    }


def test_journal_replay_reconstructs_online_ledger() -> None:
    online = make_ledger()
    replayed = make_ledger()
    journal = EventJournal()
    transaction = ResourceTransaction(
        event_id="reserve-0",
        timestamp_ns=2,
        cause="MOONCAKE_PUT",
        allocation_deltas=[
            AllocationDelta(
                resource_id=online.resource_id,
                account_from="FREE",
                account_to="PENDING_REPLICA",
                delta_bytes=25,
                allocation_id="alloc-0",
            )
        ],
    )
    transaction.commit({online.resource_id: online}, journal=journal)

    replay_capacity_transactions(journal, {replayed.resource_id: replayed})

    assert replayed.accounts == online.accounts
