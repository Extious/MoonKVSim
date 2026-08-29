from __future__ import annotations

import pytest

from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.resource import ConcurrencyResource
from moonkvsim.store.endpoint import (
    EndpointRegistrationError,
    EndpointRegistrationManager,
    EndpointRegistrationProfile,
    EndpointState,
)
from moonkvsim.store.transfer_engine import (
    MemoryKind,
    MemoryLocation,
    TopologyPath,
    TransferMetadata,
    TransferOpcode,
    TransferTask,
    TransportKind,
)


def _task(transfer_id: str) -> TransferTask:
    source = MemoryLocation(
        resource_id="gpu-0.hbm",
        node_id="compute-0",
        numa_node_id="numa-0",
        kind=MemoryKind.GPU_HBM,
        endpoint="rdma://compute-0/gpu-0",
        gpu_id="gpu-0",
    )
    destination = MemoryLocation(
        resource_id="store-dram-0",
        node_id="store-0",
        numa_node_id="numa-0",
        kind=MemoryKind.STORE_DRAM,
        endpoint="rdma://store-0/store-dram-0",
    )
    path = TopologyPath(
        path_id="gpu-0-to-store-0",
        source_kind=source.kind,
        destination_kind=destination.kind,
        transport=TransportKind.RDMA_GDR,
        rate_resource_ids=("gpu-read", "fabric", "store-write"),
        concurrency_resource_ids=(),
        source_endpoint=source.endpoint,
        destination_endpoint=destination.endpoint,
        source_node_id=source.node_id,
        destination_node_id=destination.node_id,
        source_numa_node_id=source.numa_node_id,
        destination_numa_node_id=destination.numa_node_id,
        source_hca_id="mlx5-compute-0-0",
        destination_hca_id="mlx5-store-0-0",
    )
    return TransferTask.create(
        TransferMetadata(
            transfer_id=transfer_id,
            object_id=f"object:{transfer_id}",
            replica_id=f"replica:{transfer_id}",
            source=source,
            destination=destination,
            opcode=TransferOpcode.WRITE,
            total_bytes=64,
            cause="BASELINE_STORE_PUT",
            route_version=0,
            ready_ns=0,
            path=path,
        ),
        slice_size_bytes=64,
    )


def _manager() -> tuple[GlobalDES, EndpointRegistrationManager]:
    des = GlobalDES()
    manager = EndpointRegistrationManager(
        des=des,
        registration_worker=ConcurrencyResource(
            resource_id="endpoint-registration-worker",
            lanes=1,
        ),
        profile=EndpointRegistrationProfile(
            worker_resource_id="endpoint-registration-worker",
            cold_latency_ns=10,
            warm_lookup_ns=2,
        ),
    )
    return des, manager


def test_cold_registration_and_warm_lookup_are_independent_des_events() -> None:
    des, manager = _manager()
    cold = _task("cold")
    ready: list[tuple[str, int]] = []
    manager.prepare(
        cold,
        preparation_id="prepare:cold",
        on_ready=lambda task, clock: ready.append((task.metadata.transfer_id, clock.now_ns)),
    )

    assert manager.state_for_path(cold.metadata.path) is EndpointState.REGISTERING
    assert len(manager.registration_worker.reservations()) == 1
    des.run()

    assert ready == [("cold", 10)]
    assert manager.state_for_path(cold.metadata.path) is EndpointState.WARM
    assert manager.registration_worker.reservations() == ()
    warm = _task("warm")
    manager.prepare(
        warm,
        preparation_id="prepare:warm",
        on_ready=lambda task, clock: ready.append((task.metadata.transfer_id, clock.now_ns)),
    )
    des.run()

    assert ready == [("cold", 10), ("warm", 12)]
    executed_kinds = [
        record.data["kind"]
        for record in des.journal.records
        if record.record_type == "EVENT_EXECUTING"
    ]
    assert executed_kinds == [
        "ENDPOINT_REGISTRATION_START",
        "ENDPOINT_REGISTRATION_COMPLETE",
        "ENDPOINT_READY",
        "ENDPOINT_READY",
    ]
    assert "FORWARD_COMPLETE" not in executed_kinds
    manager.audit(require_quiescent=True)


def test_concurrent_cold_waiters_join_one_registration_worker_reservation() -> None:
    des, manager = _manager()
    first = _task("first")
    second = _task("second")
    ready: list[str] = []
    manager.prepare(
        first,
        preparation_id="prepare:first",
        on_ready=lambda task, _clock: ready.append(task.metadata.transfer_id),
    )
    manager.prepare(
        second,
        preparation_id="prepare:second",
        on_ready=lambda task, _clock: ready.append(task.metadata.transfer_id),
    )

    assert len(manager.active_registration_ids) == 1
    assert len(manager.registration_worker.reservations()) == 1
    des.run()

    assert ready == ["first", "second"]
    queued = [
        record
        for record in des.journal.records
        if record.record_type == "TRANSFER_ENDPOINT_REGISTRATION_QUEUED"
    ]
    assert len(queued) == 1
    manager.audit(require_quiescent=True)


def test_canceled_cold_registration_releases_worker_and_can_retry_new_generation() -> None:
    des, manager = _manager()
    task = _task("cancel-retry")
    manager.prepare(
        task,
        preparation_id="prepare:cancel",
        on_ready=lambda _task, _clock: pytest.fail("canceled waiter became ready"),
    )
    assert manager.cancel_preparation("prepare:cancel", reason="GPU_FAILURE:test")
    assert manager.registration_worker.reservations() == ()
    assert manager.state_for_path(task.metadata.path) is EndpointState.COLD
    manager.audit(require_quiescent=True)

    ready: list[int] = []
    manager.prepare(
        task,
        preparation_id="prepare:retry",
        on_ready=lambda _task, clock: ready.append(clock.now_ns),
    )
    des.run()

    assert ready == [10]
    registration_ids = [
        record.data["registration_id"]
        for record in des.journal.records
        if record.record_type == "TRANSFER_ENDPOINT_REGISTRATION_QUEUED"
    ]
    assert registration_ids[0] != registration_ids[1]
    manager.audit(require_quiescent=True)


def test_failure_teardown_cancels_waiters_releases_worker_and_can_disable_key() -> None:
    _des, manager = _manager()
    task = _task("teardown")
    manager.prepare(
        task,
        preparation_id="prepare:teardown",
        on_ready=lambda _task, _clock: pytest.fail("torn-down waiter became ready"),
    )
    manager.teardown_path(task.metadata.path, reason="GPU_FAILURE:test", disable=True)

    assert manager.active_preparation_ids == ()
    assert manager.active_registration_ids == ()
    assert manager.registration_worker.reservations() == ()
    assert manager.state_for_path(task.metadata.path) is EndpointState.DISABLED
    with pytest.raises(EndpointRegistrationError, match="disabled"):
        manager.prepare(
            task,
            preparation_id="prepare:disabled",
            on_ready=lambda _task, _clock: None,
        )
    manager.audit(require_quiescent=True)
