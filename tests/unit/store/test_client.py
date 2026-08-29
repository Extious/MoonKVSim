from __future__ import annotations

from dataclasses import replace

import pytest

from moonkvsim.common.types import KVIdentity
from moonkvsim.recovery.baseline import BaselineRecoveryPlanner
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.store.allocation_strategy import RandomAllocationStrategy
from moonkvsim.store.client import (
    GetOperationState,
    PutOperationState,
    StoreClient,
    StoreClientError,
)
from moonkvsim.store.master import (
    STORE_COMMITTED_ACCOUNT,
    STORE_PENDING_ACCOUNT,
    MasterService,
)
from moonkvsim.store.segment import Segment
from moonkvsim.store.transfer_engine import (
    BatchTransfer,
    MemoryKind,
    MemoryLocation,
    SliceStatus,
    Topology,
    TopologyPath,
    TransferOpcode,
    TransferStatus,
    TransferTask,
    TransportKind,
)


def _identity() -> KVIdentity:
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


def _gpu(node_id: str, gpu_index: int) -> MemoryLocation:
    gpu_id = f"{node_id}.gpu-{gpu_index}"
    return MemoryLocation(
        resource_id=f"{gpu_id}.hbm",
        node_id=node_id,
        numa_node_id=f"numa:{node_id}:0",
        kind=MemoryKind.GPU_HBM,
        endpoint=f"rdma://{gpu_id}",
        gpu_id=gpu_id,
    )


def _path(
    path_id: str,
    source: MemoryLocation,
    destination: MemoryLocation,
    *,
    priority: int,
) -> TopologyPath:
    local = source.node_id == destination.node_id
    return TopologyPath(
        path_id=path_id,
        source_kind=source.kind,
        destination_kind=destination.kind,
        transport=TransportKind.LOCAL_COPY if local else TransportKind.RDMA_GDR,
        rate_resource_ids=(f"{path_id}.read", f"{path_id}.link", f"{path_id}.write"),
        concurrency_resource_ids=(f"{path_id}.queue",),
        source_endpoint=source.endpoint,
        destination_endpoint=destination.endpoint,
        source_node_id=source.node_id,
        destination_node_id=destination.node_id,
        source_numa_node_id=source.numa_node_id,
        destination_numa_node_id=destination.numa_node_id,
        source_hca_id=None if local else f"{source.node_id}.hca-0",
        destination_hca_id=None if local else f"{destination.node_id}.hca-0",
        priority=priority,
    )


def _topology() -> Topology:
    dp0 = _gpu("node-0", 0)
    dp1 = _gpu("node-1", 0)
    local_store = MemoryLocation(
        resource_id="store-local",
        node_id="node-0",
        numa_node_id="numa:node-0:0",
        kind=MemoryKind.STORE_DRAM,
        endpoint="tcp://store-local",
    )
    remote_store = MemoryLocation(
        resource_id="store-remote",
        node_id="node-2",
        numa_node_id="numa:node-2:0",
        kind=MemoryKind.STORE_DRAM,
        endpoint="tcp://store-remote",
    )
    return Topology(
        [
            _path("put-local", dp0, local_store, priority=0),
            _path("put-remote", dp0, remote_store, priority=10),
            _path("get-local", local_store, dp0, priority=0),
            _path("get-remote", local_store, dp1, priority=10),
            _path("put-dp1-local-store", dp1, local_store, priority=10),
            _path("put-dp1-remote-store", dp1, remote_store, priority=10),
            _path("get-remote-store-dp0", remote_store, dp0, priority=10),
            _path("get-remote-store-dp1", remote_store, dp1, priority=10),
        ]
    )


def _master() -> MasterService:
    master = MasterService(allocation_strategy=RandomAllocationStrategy(seed=7))
    for segment_id, node_id in (("store-local", "node-0"), ("store-remote", "node-2")):
        master.mount_segment(
            Segment(
                segment_id=segment_id,
                name=segment_id,
                node_id=node_id,
                numa_node_id=f"numa:{node_id}:0",
                transport_endpoint=f"tcp://{segment_id}",
                capacity_bytes=1024,
                allocation_alignment_bytes=64,
                allocator_metadata_bytes=8,
            ),
            CapacityLedger(
                resource_id=segment_id,
                resource_kind=CapacityResourceKind.STORE_DRAM,
                capacity_bytes=1024,
            ),
            timestamp_ns=0,
        )
    return master


def _clients() -> tuple[MasterService, StoreClient, StoreClient]:
    master = _master()
    topology = _topology()
    dp0 = StoreClient(
        client_id="dp0",
        master=master,
        topology=topology,
        local_gpu=_gpu("node-0", 0),
        registered_at_ns=0,
        slice_size_bytes=64,
    )
    dp1 = StoreClient(
        client_id="dp1",
        master=master,
        topology=topology,
        local_gpu=_gpu("node-1", 0),
        registered_at_ns=0,
        slice_size_bytes=64,
    )
    return master, dp0, dp1


def _complete_task(
    client: StoreClient,
    task: TransferTask,
    *,
    start_ns: int,
) -> int:
    timestamp_ns = start_ns
    for item in tuple(task.slices):
        timestamp_ns += 1
        client.post_slice(
            task.metadata.transfer_id,
            item.slice_id,
            timestamp_ns=timestamp_ns,
        )
        timestamp_ns += 1
        client.finish_slice(
            task.metadata.transfer_id,
            item.slice_id,
            SliceStatus.SUCCESS,
            timestamp_ns=timestamp_ns,
        )
    return timestamp_ns


def _complete_batch(client: StoreClient, batch: BatchTransfer, *, start_ns: int) -> int:
    client.start_batch(batch.batch_id, timestamp_ns=start_ns)
    timestamp_ns = start_ns
    for task in batch.tasks:
        timestamp_ns = _complete_task(client, task, start_ns=timestamp_ns)
    return timestamp_ns


def test_dp0_pending_put_becomes_visible_then_dp1_loads_committed_replica() -> None:
    master, dp0, dp1 = _clients()
    identity = _identity()
    put = dp0.put_start(
        identity,
        put_id="put-0",
        payload_bytes=100,
        replica_count=1,
        ready_ns=1,
        cause="DP0_SOURCE_STORE_PUT",
        preferred_segment_ids=("store-local",),
    )

    assert put.state is PutOperationState.PENDING
    assert put.batch.status is TransferStatus.WAITING
    assert put.batch.transferred_bytes == 0
    assert dp1.get_replica_list(identity) == ()
    with pytest.raises(StoreClientError, match="NO_COMMITTED_REPLICA"):
        dp1.get_start(identity, get_id="too-early", ready_ns=2)
    allocation = master.allocation_registry.get(put.ticket.allocation_ids[0])
    assert allocation.payload_bytes == 100
    assert allocation.allocated_bytes == 128
    assert master.ledgers["store-local"].bytes_in(STORE_PENDING_ACCOUNT) == 128

    [write_task] = put.batch.tasks
    assert write_task.metadata.opcode is TransferOpcode.WRITE
    assert write_task.metadata.total_bytes == 100
    assert write_task.metadata.path.path_id == "put-local"
    assert write_task.metadata.cause == "DP0_SOURCE_STORE_PUT"
    assert write_task.metadata.route_version == 0
    end_ns = _complete_batch(dp0, put.batch, start_ns=3)

    assert put.state is PutOperationState.COMMITTED
    assert put.batch.transferred_bytes == 100
    assert master.ledgers["store-local"].bytes_in(STORE_PENDING_ACCOUNT) == 0
    assert master.ledgers["store-local"].bytes_in(STORE_COMMITTED_ACCOUNT) == 128
    assert len(dp1.get_replica_list(identity)) == 1

    dp1_identity = replace(
        identity,
        request_id="request-dp1",
        route_version=1,
        source_gpu_id="node-1.gpu-0",
    )
    get = dp1.get_start(
        dp1_identity,
        get_id="get-0",
        ready_ns=end_ns + 1,
        cause="DP1_CROSS_DP_LOAD",
    )
    [read_task] = get.batch.tasks
    assert read_task.metadata.opcode is TransferOpcode.READ
    assert read_task.metadata.source.resource_id == "store-local"
    assert read_task.metadata.destination.gpu_id == "node-1.gpu-0"
    assert read_task.metadata.path.path_id == "get-remote"
    assert read_task.metadata.total_bytes == 100
    assert read_task.metadata.cause == "DP1_CROSS_DP_LOAD"
    assert read_task.metadata.route_version == 1
    _complete_batch(dp1, get.batch, start_ns=end_ns + 2)

    assert get.state is GetOperationState.COMPLETED
    assert get.batch.transferred_bytes == 100
    master.allocation_registry.audit(master.ledgers)


def test_all_replica_slices_must_succeed_before_atomic_publication() -> None:
    master, dp0, dp1 = _clients()
    identity = _identity()
    put = dp0.put_start(
        identity,
        put_id="put-two",
        payload_bytes=100,
        replica_count=2,
        ready_ns=1,
        preferred_segment_ids=("store-local", "store-remote"),
    )
    assert len(put.batch.tasks) == 2
    assert {task.metadata.path.path_id for task in put.batch.tasks} == {
        "put-local",
        "put-remote",
    }
    dp0.start_batch(put.batch.batch_id, timestamp_ns=2)

    timestamp_ns = _complete_task(dp0, put.batch.tasks[0], start_ns=2)
    assert put.state is PutOperationState.PENDING
    assert dp1.get_replica_list(identity) == ()
    assert (
        master.ledgers[put.batch.tasks[0].metadata.destination.resource_id].bytes_in(
            STORE_PENDING_ACCOUNT
        )
        == 128
    )

    _complete_task(dp0, put.batch.tasks[1], start_ns=timestamp_ns)
    assert put.state is PutOperationState.COMMITTED
    assert put.batch.transferred_bytes == 200
    assert len(dp1.get_replica_list(identity)) == 2
    assert (
        sum(ledger.bytes_in(STORE_COMMITTED_ACCOUNT) for ledger in master.ledgers.values()) == 256
    )
    master.allocation_registry.audit(master.ledgers)


def test_strict_get_uses_planned_replica_when_path_priority_prefers_another() -> None:
    master, dp0, _ = _clients()
    identity = _identity()
    put = dp0.put_start(
        identity,
        put_id="put-strict-get",
        payload_bytes=100,
        replica_count=2,
        ready_ns=1,
        # replica-0 is remote while replica-1 is local to dp0.  The ordinary
        # GET selector therefore prefers replica-1 even though the recovery
        # planner deterministically binds replica-0.
        preferred_segment_ids=("store-remote", "store-local"),
    )
    end_ns = _complete_batch(dp0, put.batch, start_ns=2)

    plan = BaselineRecoveryPlanner(
        master.directory,
        master.allocation_registry,
    ).plan((identity,))
    [planned] = plan.store_prefix
    assert planned.replica_id == "put-strict-get:replica-0"
    assert planned.resource_ids == ("store-remote",)

    unbound = dp0.get_start(
        identity,
        get_id="get-unbound",
        ready_ns=end_ns + 1,
    )
    [unbound_task] = unbound.batch.tasks
    assert unbound.replica.replica_id == "put-strict-get:replica-1"
    assert unbound_task.metadata.source.resource_id == "store-local"
    assert unbound_task.metadata.path.path_id == "get-local"
    unbound_end_ns = _complete_batch(dp0, unbound.batch, start_ns=end_ns + 2)

    strict = dp0.get_start(
        identity,
        get_id="get-strict",
        ready_ns=unbound_end_ns + 1,
        required_replica_id=planned.replica_id,
        required_allocation_ids=planned.allocation_ids,
        required_source_resource_id=planned.resource_ids[0],
    )
    [strict_task] = strict.batch.tasks
    assert strict.replica.replica_id == planned.replica_id
    assert strict.replica.allocation_ids == planned.allocation_ids
    assert strict_task.metadata.source.resource_id == "store-remote"
    assert strict_task.metadata.path.path_id == "get-remote-store-dp0"
    strict_end_ns = _complete_batch(
        dp0,
        strict.batch,
        start_ns=unbound_end_ns + 2,
    )

    with pytest.raises(
        StoreClientError,
        match="REQUIRED_COMMITTED_REPLICA_UNAVAILABLE",
    ):
        dp0.get_start(
            identity,
            get_id="get-missing-strict-replica",
            ready_ns=strict_end_ns + 1,
            required_replica_id="missing-replica",
        )
    master.allocation_registry.audit(master.ledgers)


def test_failed_slice_aborts_put_and_releases_pending_allocation() -> None:
    master, dp0, dp1 = _clients()
    identity = _identity()
    put = dp0.put_start(
        identity,
        put_id="put-fail",
        payload_bytes=100,
        replica_count=1,
        ready_ns=1,
        preferred_segment_ids=("store-local",),
    )
    dp0.start_batch(put.batch.batch_id, timestamp_ns=2)
    [task] = put.batch.tasks
    first = task.slices[0]
    dp0.post_slice(task.metadata.transfer_id, first.slice_id, timestamp_ns=3)
    dp0.finish_slice(
        task.metadata.transfer_id,
        first.slice_id,
        SliceStatus.FAILED,
        timestamp_ns=4,
        abort_reason="TOY_TRANSFER_FAILED",
    )

    assert put.state is PutOperationState.ABORTED
    assert put.abort_reason == "TOY_TRANSFER_FAILED"
    assert task.status is TransferStatus.CANCELED
    assert all(item.status.terminal for item in task.slices)
    assert dp1.get_replica_list(identity) == ()
    assert master.ledgers["store-local"].bytes_in(STORE_PENDING_ACCOUNT) == 0
    assert master.segments["store-local"].used_bytes == 0
    master.allocation_registry.audit(master.ledgers)


def test_remove_revokes_committed_visibility_and_releases_store_bytes() -> None:
    master, dp0, dp1 = _clients()
    identity = _identity()
    put = dp0.put_start(
        identity,
        put_id="put-remove",
        payload_bytes=100,
        replica_count=1,
        ready_ns=1,
        preferred_segment_ids=("store-local",),
    )
    end_ns = _complete_batch(dp0, put.batch, start_ns=2)
    assert len(dp1.get_replica_list(identity)) == 1

    assert dp1.remove(identity, timestamp_ns=end_ns + 1) == 1
    assert dp1.remove(identity, timestamp_ns=end_ns + 2) == 0
    assert dp1.get_replica_list(identity) == ()
    assert master.ledgers["store-local"].bytes_in(STORE_COMMITTED_ACCOUNT) == 0
    assert master.segments["store-local"].used_bytes == 0
    master.allocation_registry.audit(master.ledgers)


def test_get_failure_does_not_remove_the_committed_source_replica() -> None:
    master, dp0, dp1 = _clients()
    identity = _identity()
    put = dp0.put_start(
        identity,
        put_id="put-for-get-failure",
        payload_bytes=100,
        replica_count=1,
        ready_ns=1,
        preferred_segment_ids=("store-local",),
    )
    end_ns = _complete_batch(dp0, put.batch, start_ns=2)
    get = dp1.get_start(identity, get_id="get-fail", ready_ns=end_ns + 1)
    dp1.start_batch(get.batch.batch_id, timestamp_ns=end_ns + 2)
    [task] = get.batch.tasks
    first = task.slices[0]
    dp1.post_slice(task.metadata.transfer_id, first.slice_id, timestamp_ns=end_ns + 3)
    dp1.finish_slice(
        task.metadata.transfer_id,
        first.slice_id,
        SliceStatus.TIMEOUT,
        timestamp_ns=end_ns + 4,
        abort_reason="TOY_TIMEOUT",
    )

    assert get.state is GetOperationState.FAILED
    assert len(dp1.get_replica_list(identity)) == 1
    assert master.ledgers["store-local"].bytes_in(STORE_COMMITTED_ACCOUNT) == 128
    master.allocation_registry.audit(master.ledgers)
