from dataclasses import replace

import pytest

from moonkvsim.common.status import ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.store.allocation_strategy import RandomAllocationStrategy
from moonkvsim.store.master import (
    STORE_COMMITTED_ACCOUNT,
    STORE_PENDING_ACCOUNT,
    MasterService,
    PutState,
)
from moonkvsim.store.segment import Segment


def identity() -> KVIdentity:
    return KVIdentity(
        tenant_id="tenant-0",
        model_id="Qwen/Qwen3-8B",
        model_revision="revision",
        kv_dtype="bf16",
        kv_abi="vllm-v1",
        kv_layout="tp1-pp1",
        tp_size=1,
        pp_size=1,
        block_size_tokens=16,
        stable_block_hash="hash-0",
        token_start=0,
        token_end=16,
        shard_id="tp0",
        request_id="request-0",
        session_id="session-0",
        workflow_id="workflow-0",
        route_version=0,
        source_gpu_id="node-0.gpu-0",
    )


def master(*, capacities: tuple[int, ...] = (1024, 1024)) -> MasterService:
    service = MasterService(allocation_strategy=RandomAllocationStrategy(seed=3))
    for index, capacity in enumerate(capacities):
        resource_id = f"store-{index}"
        service.mount_segment(
            Segment(
                segment_id=resource_id,
                name=resource_id,
                node_id=f"node-{index}",
                numa_node_id=f"numa:node-{index}:0",
                transport_endpoint=f"tcp://store-{index}",
                capacity_bytes=capacity,
                allocation_alignment_bytes=64,
                allocator_metadata_bytes=8,
            ),
            CapacityLedger(
                resource_id=resource_id,
                resource_kind=CapacityResourceKind.STORE_DRAM,
                capacity_bytes=capacity,
            ),
            timestamp_ns=0,
        )
    return service


def test_master_can_share_an_explicit_registry_and_its_journal() -> None:
    journal = EventJournal()
    registry = AllocationRegistry(journal=journal)

    service = MasterService(
        allocation_strategy=RandomAllocationStrategy(seed=3),
        allocation_registry=registry,
    )

    assert service.journal is journal
    assert service.allocation_registry is registry


def test_master_rejects_registry_from_another_or_missing_journal() -> None:
    with pytest.raises(ValueError, match="must share one EventJournal"):
        MasterService(
            allocation_strategy=RandomAllocationStrategy(seed=3),
            journal=EventJournal(),
            allocation_registry=AllocationRegistry(journal=EventJournal()),
        )
    with pytest.raises(ValueError, match="must expose its EventJournal"):
        MasterService(
            allocation_strategy=RandomAllocationStrategy(seed=3),
            allocation_registry=AllocationRegistry(),
        )


def test_put_pending_is_invisible_then_committed_is_cross_dp_visible() -> None:
    service = master()
    source = identity()
    ticket = service.put_start(
        source,
        put_id="put-0",
        payload_bytes=100,
        replica_count=1,
        timestamp_ns=1,
    )
    assert service.get_replica_list(source) == ()
    allocation = service.allocation_registry.get(ticket.allocation_ids[0])
    ledger = service.ledgers[allocation.resource_id]
    assert ledger.bytes_in(STORE_PENDING_ACCOUNT) == 128

    [committed] = service.put_end(
        ticket.put_id,
        successful_replica_ids=ticket.replica_ids,
        timestamp_ns=2,
    )
    rerouted = replace(source, request_id="request-1", route_version=1)
    assert service.get_replica_list(rerouted) == (committed,)
    assert ledger.bytes_in(STORE_PENDING_ACCOUNT) == 0
    assert ledger.bytes_in(STORE_COMMITTED_ACCOUNT) == 128
    service.allocation_registry.audit(service.ledgers)


def test_best_effort_replica_allocation_uses_distinct_available_segments() -> None:
    service = master(capacities=(1024, 64, 1024))
    ticket = service.put_start(
        identity(),
        put_id="put-best-effort",
        payload_bytes=100,
        replica_count=3,
        timestamp_ns=1,
    )

    assert len(ticket.replica_ids) == 2
    resource_ids = {
        service.allocation_registry.get(allocation_id).resource_id
        for allocation_id in ticket.allocation_ids
    }
    assert len(resource_ids) == 2


def test_abort_releases_pending_capacity_and_extent() -> None:
    service = master(capacities=(1024,))
    ticket = service.put_start(
        identity(),
        put_id="put-abort",
        payload_bytes=100,
        replica_count=1,
        timestamp_ns=1,
    )
    service.abort_put(ticket.put_id, timestamp_ns=2, reason="TRANSFER_FAILED")

    assert ticket.state is PutState.ABORTED
    assert service.segments["store-0"].used_bytes == 0
    assert service.ledgers["store-0"].bytes_in(STORE_PENDING_ACCOUNT) == 0
    assert service.get_replica_list(identity()) == ()


def test_put_start_rolls_back_geometry_if_capacity_ledger_disagrees() -> None:
    service = master(capacities=(1024,))
    service.ledgers["store-0"]._replace_accounts({"FREE": 64, "EXTERNAL_RESERVE": 960})
    with pytest.raises(ValueError, match="cannot transfer"):
        service.put_start(
            identity(),
            put_id="put-no-ledger-capacity",
            payload_bytes=100,
            replica_count=1,
            timestamp_ns=1,
        )
    assert service.segments["store-0"].used_bytes == 0


def test_remove_revokes_visibility_and_releases_committed_capacity() -> None:
    service = master(capacities=(1024,))
    kv = identity()
    ticket = service.put_start(
        kv,
        put_id="put-remove",
        payload_bytes=100,
        replica_count=1,
        timestamp_ns=1,
    )
    service.put_end(
        ticket.put_id,
        successful_replica_ids=ticket.replica_ids,
        timestamp_ns=2,
    )

    assert service.remove(kv, timestamp_ns=3) == 1
    assert service.remove(kv, timestamp_ns=4) == 0
    assert service.get_replica_list(kv) == ()
    assert service.segments["store-0"].used_bytes == 0
    assert service.ledgers["store-0"].bytes_in(STORE_COMMITTED_ACCOUNT) == 0
    service.allocation_registry.audit(service.ledgers)


def test_capacity_pressure_never_reuses_a_pending_extent() -> None:
    service = master(capacities=(128,))
    first = service.put_start(
        identity(),
        put_id="put-pending",
        payload_bytes=100,
        replica_count=1,
        timestamp_ns=1,
    )
    second_identity = replace(
        identity(),
        stable_block_hash="hash-1",
        request_id="request-1",
    )

    with pytest.raises(RuntimeError, match="NO_AVAILABLE_HANDLE"):
        service.put_start(
            second_identity,
            put_id="put-blocked-by-pending",
            payload_bytes=100,
            replica_count=1,
            timestamp_ns=2,
        )

    pending = service.directory.get_replica(first.replica_ids[0])
    assert pending.state is ReplicaState.PENDING
    assert service.segments["store-0"].buffers[0].buffer_id == first.allocation_ids[0]
    assert service.ledgers["store-0"].bytes_in(STORE_PENDING_ACCOUNT) == 128
    assert service.ledgers["store-0"].bytes_in(STORE_COMMITTED_ACCOUNT) == 0
    service.allocation_registry.audit(service.ledgers)


def test_failed_eviction_reserve_transaction_restores_victim_geometry() -> None:
    service = master(capacities=(128,))
    source = identity()
    first = service.put_start(
        source,
        put_id="put-victim",
        payload_bytes=100,
        replica_count=1,
        timestamp_ns=1,
    )
    service.put_end(
        first.put_id,
        successful_replica_ids=first.replica_ids,
        timestamp_ns=2,
    )
    allocation_snapshot = service.allocation_registry.snapshot_bytes()
    buffer_snapshot = service.segments["store-0"].buffers
    random_snapshot = service.allocation_strategy.checkpoint()

    # Deliberately inject a ledger/geometry disagreement.  The combined
    # victim-release/new-reserve transaction must fail in preview and restore
    # the exact old extent without publishing an eviction.
    service.ledgers["store-0"]._replace_accounts({"EXTERNAL_RESERVE": 128})
    ledger_snapshot = service.ledgers["store-0"].accounts
    second_identity = replace(
        source,
        stable_block_hash="hash-rollback",
        request_id="request-rollback",
    )
    with pytest.raises(ValueError, match=r"COMMITTED_REPLICA.*cannot transfer"):
        service.put_start(
            second_identity,
            put_id="put-rollback",
            payload_bytes=100,
            replica_count=1,
            timestamp_ns=3,
        )

    assert service.segments["store-0"].buffers == buffer_snapshot
    assert service.ledgers["store-0"].accounts == ledger_snapshot
    assert service.directory.get_replica(first.replica_ids[0]).state is ReplicaState.COMMITTED
    assert service.get_replica_list(source)
    assert service.allocation_registry.snapshot_bytes() == allocation_snapshot
    assert service.allocation_strategy.checkpoint() == random_snapshot
    assert service.eviction_strategy.keys_mru_to_lru == (source.object_id,)
    [pressure] = [
        record
        for record in service.journal.records
        if record.record_type == "MASTER_STORE_CAPACITY_PRESSURE"
    ]
    assert pressure.data["outcome"] == "TRANSACTION_ROLLED_BACK"
    assert pressure.data["candidate_victim_object_ids"] == [source.object_id]
    assert pressure.data["committed_freed_allocated_bytes"] == 0
