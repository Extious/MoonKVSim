from dataclasses import replace

import pytest

from moonkvsim.store.transfer_engine import (
    BatchTransfer,
    MemoryKind,
    MemoryLocation,
    PathPreference,
    SliceStatus,
    Topology,
    TopologyPath,
    TransferMetadata,
    TransferOpcode,
    TransferStatus,
    TransferTask,
    TransportKind,
)


def locations() -> tuple[MemoryLocation, MemoryLocation]:
    return (
        MemoryLocation(
            resource_id="gpu-0.hbm",
            node_id="node-0",
            numa_node_id="numa-0",
            kind=MemoryKind.GPU_HBM,
            endpoint="rdma://node-0/gpu-0",
            gpu_id="gpu-0",
        ),
        MemoryLocation(
            resource_id="store-0.dram",
            node_id="node-1",
            numa_node_id="numa-1",
            kind=MemoryKind.STORE_DRAM,
            endpoint="rdma://node-1/store-0",
        ),
    )


def direct_path(*, priority: int = 0, path_id: str = "rdma") -> TopologyPath:
    return TopologyPath(
        path_id=path_id,
        source_kind=MemoryKind.GPU_HBM,
        destination_kind=MemoryKind.STORE_DRAM,
        transport=TransportKind.RDMA_GDR,
        rate_resource_ids=("gpu.hbm-read", "pcie", "nic", "fabric", "store.write"),
        concurrency_resource_ids=("gpu.copy", "qp"),
        source_endpoint="rdma://node-0/gpu-0",
        destination_endpoint="rdma://node-1/store-0",
        source_node_id="node-0",
        destination_node_id="node-1",
        source_numa_node_id="numa-0",
        destination_numa_node_id="numa-1",
        source_hca_id="node-0.hca-0",
        destination_hca_id="node-1.hca-0",
        priority=priority,
    )


def metadata(*, total_bytes: int = 131_073) -> TransferMetadata:
    source, destination = locations()
    return TransferMetadata(
        transfer_id="transfer-0",
        object_id="object-0",
        replica_id="replica-0",
        source=source,
        destination=destination,
        opcode=TransferOpcode.WRITE,
        total_bytes=total_bytes,
        cause="BASELINE_STORE_PUT",
        route_version=0,
        ready_ns=10,
        path=direct_path(),
    )


def test_default_64k_slicing_is_contiguous_and_conserves_bytes() -> None:
    task = TransferTask.create(metadata())
    assert [item.length_bytes for item in task.slices] == [65_536, 65_536, 1]
    task.audit()


def test_slice_completion_drives_task_and_batch_status() -> None:
    task = TransferTask.create(metadata(total_bytes=70_000))
    batch = BatchTransfer(batch_id="batch-0")
    batch.add_task(task)
    task.start(timestamp_ns=10)

    for index, item in enumerate(tuple(task.slices)):
        task.update_slice(item.post(timestamp_ns=11 + index))
        posted = task.slices[index]
        task.update_slice(posted.finish(SliceStatus.SUCCESS, timestamp_ns=20 + index))

    assert task.status is TransferStatus.COMPLETED
    assert task.transferred_bytes == 70_000
    assert batch.status is TransferStatus.COMPLETED
    task.audit()


def test_batch_rejects_new_tasks_after_any_existing_task_starts() -> None:
    first = TransferTask.create(metadata(total_bytes=70_000))
    source, destination = locations()
    second = TransferTask.create(
        TransferMetadata(
            transfer_id="transfer-1",
            object_id="object-1",
            replica_id="replica-1",
            source=source,
            destination=destination,
            opcode=TransferOpcode.WRITE,
            total_bytes=1,
            cause="BASELINE_STORE_PUT",
            route_version=0,
            ready_ns=10,
            path=direct_path(),
        )
    )
    batch = BatchTransfer(batch_id="batch-0")
    batch.add_task(first)
    first.start(timestamp_ns=10)

    with pytest.raises(ValueError, match="after a batch starts"):
        batch.add_task(second)


def test_batch_rejects_an_already_started_task() -> None:
    task = TransferTask.create(metadata(total_bytes=1))
    task.start(timestamp_ns=10)

    with pytest.raises(ValueError, match="only waiting tasks"):
        BatchTransfer(batch_id="batch-0").add_task(task)


def test_failure_cancels_remaining_slices_without_counting_aborted_bytes() -> None:
    task = TransferTask.create(metadata(total_bytes=70_000))
    task.start(timestamp_ns=10)
    first = task.slices[0].post(timestamp_ns=11)
    task.update_slice(first.finish(SliceStatus.SUCCESS, timestamp_ns=12))
    task.cancel_remaining(timestamp_ns=13, reason="GPU_FAILURE")

    assert task.status is TransferStatus.CANCELED
    assert task.transferred_bytes == 65_536
    assert task.slices[1].abort_reason == "GPU_FAILURE"
    task.audit()


def test_topology_selects_deterministic_priority_and_honors_disable() -> None:
    preferred = direct_path(priority=0, path_id="preferred")
    fallback = direct_path(priority=1, path_id="fallback")
    topology = Topology([fallback, preferred])
    source, destination = locations()

    assert topology.select_path(source, destination) is preferred
    topology.disable_path("preferred")
    assert topology.select_path(source, destination) is fallback


def test_topology_preserves_preferred_available_retry_and_hca_disable_semantics() -> None:
    preferred = direct_path(priority=5, path_id="preferred")
    available_first = replace(
        direct_path(priority=0, path_id="available-a"),
        preference=PathPreference.AVAILABLE,
    )
    available_second = replace(
        direct_path(priority=1, path_id="available-b"),
        preference=PathPreference.AVAILABLE,
    )
    topology = Topology([available_second, preferred, available_first])
    source, destination = locations()

    assert topology.select_path(source, destination, retry_count=0) is preferred
    assert topology.select_path(source, destination, retry_count=1) is preferred
    assert topology.select_path(source, destination, retry_count=2) is available_first
    assert topology.select_path(source, destination, retry_count=3) is available_second
    assert topology.select_path(source, destination, retry_count=4) is preferred
    topology.disable_path("preferred")
    assert topology.select_path(source, destination, retry_count=0) is available_first
    topology.enable_path("preferred")
    topology.disable_hca("node-0.hca-0")
    with pytest.raises(ValueError, match="no exact compatible enabled"):
        topology.select_path(source, destination)


@pytest.mark.parametrize(
    "transport",
    [TransportKind.LOCAL_COPY, TransportKind.PCIE, TransportKind.NVLINK],
)
def test_topology_rejects_wrong_endpoint_and_cross_node_local_paths(
    transport: TransportKind,
) -> None:
    source, destination = locations()
    wrong_endpoint = MemoryLocation(
        resource_id=destination.resource_id,
        node_id=destination.node_id,
        numa_node_id=destination.numa_node_id,
        kind=destination.kind,
        endpoint="rdma://node-1/wrong",
    )
    with pytest.raises(ValueError, match="no exact compatible enabled"):
        Topology([direct_path()]).select_path(source, wrong_endpoint)
    with pytest.raises(ValueError, match="cannot cross nodes"):
        TopologyPath(
            path_id="invalid-local",
            source_kind=source.kind,
            destination_kind=destination.kind,
            transport=transport,
            rate_resource_ids=("local-copy",),
            concurrency_resource_ids=(),
            source_endpoint=source.endpoint,
            destination_endpoint=destination.endpoint,
            source_node_id=source.node_id,
            destination_node_id=destination.node_id,
            source_numa_node_id=source.numa_node_id,
            destination_numa_node_id=destination.numa_node_id,
            source_hca_id=None,
            destination_hca_id=None,
        )


def test_host_staged_path_requires_explicit_staging_capacity_resource() -> None:
    with pytest.raises(ValueError, match="staging resource"):
        TopologyPath(
            path_id="tcp",
            source_kind=MemoryKind.GPU_HBM,
            destination_kind=MemoryKind.STORE_DRAM,
            transport=TransportKind.TCP_HOST_STAGED,
            rate_resource_ids=("pcie", "nic"),
            concurrency_resource_ids=("copy",),
            source_endpoint="rdma://node-0/gpu-0",
            destination_endpoint="rdma://node-1/store-0",
            source_node_id="node-0",
            destination_node_id="node-1",
            source_numa_node_id="numa-0",
            destination_numa_node_id="numa-1",
            source_hca_id="node-0.hca-0",
            destination_hca_id="node-1.hca-0",
        )
