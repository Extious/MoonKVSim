from __future__ import annotations

from dataclasses import replace

import pytest

from moonkvsim.common.status import ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation_registry import replay_allocation_registry
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.replay import replay_capacity_transactions
from moonkvsim.store.allocation_strategy import RandomAllocationStrategy
from moonkvsim.store.client import GetOperationState, StoreClient
from moonkvsim.store.master import (
    STORE_COMMITTED_ACCOUNT,
    STORE_PENDING_ACCOUNT,
    MasterService,
)
from moonkvsim.store.segment import Segment
from moonkvsim.store.transfer_engine import (
    MemoryKind,
    MemoryLocation,
    SliceStatus,
    Topology,
    TopologyPath,
    TransportKind,
)


def _identity(block_hash: str, *, request_id: str) -> KVIdentity:
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
        stable_block_hash=block_hash,
        token_start=0,
        token_end=16,
        shard_id="tp0",
        request_id=request_id,
        session_id=f"session-{request_id}",
        workflow_id=f"workflow-{request_id}",
        route_version=0,
        source_gpu_id="node-0.gpu-0",
    )


def _master(capacity_bytes: int) -> MasterService:
    service = MasterService(allocation_strategy=RandomAllocationStrategy(seed=13))
    service.mount_segment(
        Segment(
            segment_id="store-0",
            name="store-0",
            node_id="node-0",
            numa_node_id="numa:node-0:0",
            transport_endpoint="tcp://store-0",
            capacity_bytes=capacity_bytes,
            allocation_alignment_bytes=64,
            allocator_metadata_bytes=8,
        ),
        CapacityLedger(
            resource_id="store-0",
            resource_kind=CapacityResourceKind.STORE_DRAM,
            capacity_bytes=capacity_bytes,
        ),
        timestamp_ns=0,
    )
    return service


def _commit(
    service: MasterService,
    identity: KVIdentity,
    *,
    put_id: str,
    start_ns: int,
) -> tuple[str, str]:
    ticket = service.put_start(
        identity,
        put_id=put_id,
        payload_bytes=100,
        replica_count=1,
        timestamp_ns=start_ns,
    )
    service.put_end(
        ticket.put_id,
        successful_replica_ids=ticket.replica_ids,
        timestamp_ns=start_ns + 1,
    )
    return ticket.replica_ids[0], ticket.allocation_ids[0]


def _topology() -> Topology:
    return Topology(
        [
            TopologyPath(
                path_id="put-local",
                source_kind=MemoryKind.GPU_HBM,
                destination_kind=MemoryKind.STORE_DRAM,
                transport=TransportKind.LOCAL_COPY,
                rate_resource_ids=("gpu-read", "store-write"),
                concurrency_resource_ids=("copy-lane",),
                source_endpoint="node-0",
                destination_endpoint="tcp://store-0",
                source_node_id="node-0",
                destination_node_id="node-0",
                source_numa_node_id="numa:node-0:0",
                destination_numa_node_id="numa:node-0:0",
                source_hca_id=None,
                destination_hca_id=None,
                priority=0,
            ),
            TopologyPath(
                path_id="get-local",
                source_kind=MemoryKind.STORE_DRAM,
                destination_kind=MemoryKind.GPU_HBM,
                transport=TransportKind.LOCAL_COPY,
                rate_resource_ids=("store-read", "gpu-write"),
                concurrency_resource_ids=("copy-lane",),
                source_endpoint="tcp://store-0",
                destination_endpoint="node-0",
                source_node_id="node-0",
                destination_node_id="node-0",
                source_numa_node_id="numa:node-0:0",
                destination_numa_node_id="numa:node-0:0",
                source_hca_id=None,
                destination_hca_id=None,
                priority=0,
            ),
        ]
    )


def _client(service: MasterService) -> StoreClient:
    return StoreClient(
        client_id="dp-0",
        master=service,
        topology=_topology(),
        local_gpu=MemoryLocation(
            resource_id="node-0.gpu-0.hbm",
            node_id="node-0",
            numa_node_id="numa:node-0:0",
            kind=MemoryKind.GPU_HBM,
            endpoint="node-0",
            gpu_id="node-0.gpu-0",
        ),
        registered_at_ns=0,
        slice_size_bytes=64,
    )


def _complete_client_put(client: StoreClient, identity: KVIdentity) -> tuple[str, str]:
    operation = client.put_start(
        identity,
        put_id="put-source",
        payload_bytes=100,
        replica_count=1,
        ready_ns=1,
    )
    client.start_batch(operation.batch.batch_id, timestamp_ns=2)
    timestamp_ns = 2
    for item in tuple(operation.batch.tasks[0].slices):
        timestamp_ns += 1
        client.post_slice(
            operation.batch.tasks[0].metadata.transfer_id,
            item.slice_id,
            timestamp_ns=timestamp_ns,
        )
        timestamp_ns += 1
        client.finish_slice(
            operation.batch.tasks[0].metadata.transfer_id,
            item.slice_id,
            SliceStatus.SUCCESS,
            timestamp_ns=timestamp_ns,
        )
    return operation.ticket.replica_ids[0], operation.ticket.allocation_ids[0]


def test_lru_capacity_pressure_eviction_and_journal_replay_are_exact() -> None:
    service = _master(256)
    first = _identity("hash-a", request_id="a")
    second = _identity("hash-b", request_id="b")
    third = _identity("hash-c", request_id="c")
    first_replica, _ = _commit(service, first, put_id="put-a", start_ns=1)
    second_replica, _ = _commit(service, second, put_id="put-b", start_ns=3)

    # A real access makes A MRU, so B is the deterministic capacity victim.
    service.record_committed_access(first, timestamp_ns=5)
    third_ticket = service.put_start(
        third,
        put_id="put-c",
        payload_bytes=100,
        replica_count=1,
        timestamp_ns=6,
    )

    assert service.directory.get_replica(first_replica).state is ReplicaState.COMMITTED
    assert service.directory.get_replica(second_replica).state is ReplicaState.EVICTED
    assert service.get_replica_list(first)
    assert service.get_replica_list(second) == ()
    assert service.get_replica_list(third) == ()
    assert service.ledgers["store-0"].bytes_in(STORE_COMMITTED_ACCOUNT) == 128
    assert service.ledgers["store-0"].bytes_in(STORE_PENDING_ACCOUNT) == 128

    service.put_end(
        third_ticket.put_id,
        successful_replica_ids=third_ticket.replica_ids,
        timestamp_ns=7,
    )
    service.allocation_registry.audit(service.ledgers)

    [pressure] = [
        record
        for record in service.journal.records
        if record.record_type == "MASTER_STORE_CAPACITY_PRESSURE"
    ]
    assert pressure.data["outcome"] == "EVICTED_AND_RESERVED"
    assert pressure.data["inspected_object_ids_lru_first"] == [second.object_id]
    assert pressure.data["candidate_victim_replica_ids"] == [second_replica]
    assert "asynchronous_lease_aware_batch_eviction" in pressure.data["fidelity_gap"]

    replayed_ledger = CapacityLedger(
        resource_id="store-0",
        resource_kind=CapacityResourceKind.STORE_DRAM,
        capacity_bytes=256,
    )
    replay_capacity_transactions(service.journal, {"store-0": replayed_ledger})
    replayed_registry = replay_allocation_registry(service.journal)
    assert replayed_ledger.accounts == service.ledgers["store-0"].accounts
    assert replayed_registry.snapshot_bytes() == service.allocation_registry.snapshot_bytes()
    replayed_registry.audit({"store-0": replayed_ledger})


def test_live_get_alias_refcounts_block_eviction_until_every_terminal_path() -> None:
    service = _master(128)
    client = _client(service)
    source = _identity("hash-source", request_id="source")
    source_replica_id, source_allocation_id = _complete_client_put(client, source)
    next_timestamp = service.journal.records[-1].timestamp_ns + 1

    first_alias = replace(
        source,
        request_id="alias-a",
        session_id="session-alias-a",
        workflow_id="workflow-alias-a",
        route_version=1,
    )
    second_alias = replace(
        source,
        request_id="alias-b",
        session_id="session-alias-b",
        workflow_id="workflow-alias-b",
        route_version=2,
    )
    get_a = client.get_start(first_alias, get_id="get-alias-a", ready_ns=next_timestamp)
    get_b = client.get_start(second_alias, get_id="get-alias-b", ready_ns=next_timestamp + 1)
    client.start_batch(get_a.batch.batch_id, timestamp_ns=next_timestamp + 2)
    client.start_batch(get_b.batch.batch_id, timestamp_ns=next_timestamp + 2)
    assert service.allocation_registry.overlay(source_allocation_id).source_pin_count == 2

    with pytest.raises(RuntimeError, match="OBJECT_BUSY"):
        service.remove(source, timestamp_ns=next_timestamp + 3)
    blocked_identity = _identity("hash-blocked", request_id="blocked")
    with pytest.raises(RuntimeError, match="NO_AVAILABLE_HANDLE"):
        service.put_start(
            blocked_identity,
            put_id="put-blocked-by-live-aliases",
            payload_bytes=100,
            replica_count=1,
            timestamp_ns=next_timestamp + 3,
        )
    assert service.directory.get_replica(source_replica_id).state is ReplicaState.COMMITTED
    [blocked_pressure] = [
        record
        for record in service.journal.records
        if record.record_type == "MASTER_STORE_CAPACITY_PRESSURE"
    ]
    assert blocked_pressure.data["outcome"] == "NO_AVAILABLE_HANDLE"
    assert blocked_pressure.data["skipped_object_ids"] == [source.object_id]
    assert blocked_pressure.data["candidate_victim_replica_ids"] == []

    timestamp_ns = next_timestamp + 3
    for item in tuple(get_a.batch.tasks[0].slices):
        timestamp_ns += 1
        client.post_slice(
            get_a.batch.tasks[0].metadata.transfer_id,
            item.slice_id,
            timestamp_ns=timestamp_ns,
        )
        timestamp_ns += 1
        client.finish_slice(
            get_a.batch.tasks[0].metadata.transfer_id,
            item.slice_id,
            SliceStatus.SUCCESS,
            timestamp_ns=timestamp_ns,
        )
    assert get_a.state is GetOperationState.COMPLETED
    assert service.allocation_registry.overlay(source_allocation_id).source_pin_count == 1

    timestamp_ns += 1
    first_slice = get_b.batch.tasks[0].slices[0]
    client.post_slice(
        get_b.batch.tasks[0].metadata.transfer_id,
        first_slice.slice_id,
        timestamp_ns=timestamp_ns,
    )
    timestamp_ns += 1
    client.finish_slice(
        get_b.batch.tasks[0].metadata.transfer_id,
        first_slice.slice_id,
        SliceStatus.TIMEOUT,
        timestamp_ns=timestamp_ns,
        abort_reason="INJECTED_GET_FAILURE",
    )
    assert get_b.state is GetOperationState.FAILED
    assert service.allocation_registry.overlay(source_allocation_id).source_pin_count == 0

    replacement = _identity("hash-replacement", request_id="replacement")
    replacement_put = client.put_start(
        replacement,
        put_id="put-after-aliases-terminal",
        payload_bytes=100,
        replica_count=1,
        ready_ns=timestamp_ns + 1,
    )
    assert replacement_put.ticket.allocation_ids
    assert service.directory.get_replica(source_replica_id).state is ReplicaState.EVICTED
    assert service.get_replica_list(source) == ()
    assert service.ledgers["store-0"].bytes_in(STORE_PENDING_ACCOUNT) == 128
    assert service.ledgers["store-0"].bytes_in(STORE_COMMITTED_ACCOUNT) == 0
    service.allocation_registry.audit(service.ledgers)

    replayed_ledger = CapacityLedger(
        resource_id="store-0",
        resource_kind=CapacityResourceKind.STORE_DRAM,
        capacity_bytes=128,
    )
    replay_capacity_transactions(service.journal, {"store-0": replayed_ledger})
    replayed_registry = replay_allocation_registry(service.journal)
    assert replayed_ledger.accounts == service.ledgers["store-0"].accounts
    assert replayed_registry.snapshot_bytes() == service.allocation_registry.snapshot_bytes()
    replayed_registry.audit({"store-0": replayed_ledger})
