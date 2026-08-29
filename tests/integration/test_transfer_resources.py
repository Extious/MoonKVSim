from __future__ import annotations

from itertools import pairwise

import pytest

from moonkvsim.output.records import build_flow_rate_event_rows
from moonkvsim.simulation.allocation import AllocationState
from moonkvsim.simulation.event import EventKind
from moonkvsim.simulation.flow_des import FlowDESController
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.network import FlowContentionModel
from moonkvsim.simulation.replay import replay_capacity_transactions
from moonkvsim.simulation.resource import ConcurrencyResource, RateResource
from moonkvsim.store.transfer_engine import (
    MemoryKind,
    MemoryLocation,
    TopologyPath,
    TransferMetadata,
    TransferOpcode,
    TransferStatus,
    TransferTask,
    TransportKind,
)
from moonkvsim.store.transfer_resources import (
    EVIDENCE_BOUNDARY,
    ReplayedTransferResourceState,
    StagingAllocationSpec,
    TransferLeaseOutcome,
    TransferLeaseStatus,
    TransferResourceError,
    TransferResourceLeaseManager,
    TransferResourceUnavailable,
    replay_transfer_resource_calendar,
    transfer_flow_queue_wait_ns_by_flow,
    transfer_resource_calendar_replay_byte_identical,
)
from moonkvsim.store.transfer_runtime import (
    TransferRuntime,
    transfer_flow_replay_byte_identical,
)

RATE_IDS = ("gpu.copy-rate", "fabric.rate", "store.write-rate")


def _task(
    transfer_id: str,
    *,
    total_bytes: int,
    transport: TransportKind,
    concurrency_ids: tuple[str, ...] = ("gpu.copy-lane", "endpoint.qp-lane"),
    staging_resource_id: str | None = None,
) -> TransferTask:
    source = MemoryLocation(
        resource_id="node-0.gpu-0.hbm",
        node_id="node-0",
        numa_node_id="numa:node-0:0",
        kind=MemoryKind.GPU_HBM,
        endpoint="rdma://node-0/gpu-0",
        gpu_id="node-0.gpu-0",
    )
    destination = MemoryLocation(
        resource_id="store-0.segment-0",
        node_id="store-0",
        numa_node_id="numa:store-0:0",
        kind=MemoryKind.STORE_DRAM,
        endpoint="rdma://store-0/segment-0",
    )
    path = TopologyPath(
        path_id=f"path:{transfer_id}",
        source_kind=source.kind,
        destination_kind=destination.kind,
        transport=transport,
        rate_resource_ids=RATE_IDS,
        concurrency_resource_ids=concurrency_ids,
        source_endpoint=source.endpoint,
        destination_endpoint=destination.endpoint,
        source_node_id=source.node_id,
        destination_node_id=destination.node_id,
        source_numa_node_id=source.numa_node_id,
        destination_numa_node_id=destination.numa_node_id,
        source_hca_id="node-0.hca-0",
        destination_hca_id="store-0.hca-0",
        source_host_staging_resource_id=staging_resource_id,
    )
    return TransferTask.create(
        TransferMetadata(
            transfer_id=transfer_id,
            object_id=f"object:{transfer_id}",
            replica_id=f"replica:{transfer_id}",
            source=source,
            destination=destination,
            opcode=TransferOpcode.WRITE,
            total_bytes=total_bytes,
            cause="BASELINE_STORE_PUT",
            route_version=0,
            ready_ns=0,
            path=path,
        ),
        slice_size_bytes=total_bytes,
    )


def _host_ledger(capacity_bytes: int = 1_024) -> CapacityLedger:
    return CapacityLedger(
        resource_id="node-0.host-staging",
        resource_kind=CapacityResourceKind.HOST_DRAM,
        capacity_bytes=capacity_bytes,
    )


def _resources() -> dict[str, ConcurrencyResource]:
    return {
        "gpu.copy-lane": ConcurrencyResource(resource_id="gpu.copy-lane", lanes=1),
        "endpoint.qp-lane": ConcurrencyResource(resource_id="endpoint.qp-lane", lanes=1),
    }


def _manager(
    *,
    des: GlobalDES | None = None,
    host_capacity_bytes: int = 1_024,
    resources: dict[str, ConcurrencyResource] | None = None,
) -> tuple[
    GlobalDES,
    CapacityLedger,
    dict[str, ConcurrencyResource],
    TransferResourceLeaseManager,
]:
    resolved_des = des or GlobalDES()
    host = _host_ledger(host_capacity_bytes)
    resolved_resources = resources or _resources()
    manager = TransferResourceLeaseManager(
        des=resolved_des,
        capacity_ledgers={host.resource_id: host},
        concurrency_resources=resolved_resources,
    )
    return resolved_des, host, resolved_resources, manager


def _runtime(des: GlobalDES, *, rate_bytes_per_second: float = 1_000_000_000.0) -> TransferRuntime:
    model = FlowContentionModel(
        [
            RateResource(
                resource_id=resource_id,
                capacity_bytes_per_second=rate_bytes_per_second,
            )
            for resource_id in RATE_IDS
        ]
    )
    return TransferRuntime(controller=FlowDESController(des=des, model=model))


def _staging_spec(
    transfer_id: str,
    *,
    payload_bytes: int,
    allocated_bytes: int,
    alignment_bytes: int = 8,
) -> StagingAllocationSpec:
    return StagingAllocationSpec(
        allocation_id=f"staging:{transfer_id}",
        resource_id="node-0.host-staging",
        payload_bytes=payload_bytes,
        requested_bytes=payload_bytes,
        allocated_bytes=allocated_bytes,
        padding_bytes=0,
        allocator_metadata_bytes=0,
        internal_fragmentation_bytes=allocated_bytes - payload_bytes,
        alignment_bytes=alignment_bytes,
    )


def test_tcp_staging_is_explicit_and_gdr_never_charges_host_dram() -> None:
    des, host, _calendars, manager = _manager()
    runtime = _runtime(des)
    tcp = _task(
        "tcp",
        total_bytes=10,
        transport=TransportKind.TCP_HOST_STAGED,
        staging_resource_id=host.resource_id,
    )
    spec = _staging_spec("tcp", payload_bytes=10, allocated_bytes=16)

    lease = manager.acquire(
        tcp,
        lease_id="lease:tcp",
        duration_ns=10,
        staging_specs={host.resource_id: spec},
    )

    assert tcp.status.value == TransferStatus.WAITING.value
    assert host.bytes_in("HOST_STAGING:staging:tcp") == 16
    binding = lease.staging_allocations[0]
    assert binding.transfer_id == "tcp"
    assert binding.slice_ids == ("tcp:slice-000000",)
    assert binding.cause == "BASELINE_STORE_PUT"
    assert binding.allocation.requested_bytes == 10
    assert binding.allocation.allocated_bytes == 16
    assert binding.allocation.internal_fragmentation_bytes == 6
    assert binding.allocation.alignment_bytes == 8

    manager.start_task(runtime, tcp, lease_id=lease.lease_id)
    des.run()

    released = manager.lease(lease.lease_id)
    assert tcp.status is TransferStatus.COMPLETED
    assert released.status is TransferLeaseStatus.RELEASED
    assert released.outcome is TransferLeaseOutcome.COMPLETED
    assert released.staging_allocations[0].allocation.state is AllocationState.RELEASED
    assert host.bytes_in("FREE") == host.capacity_bytes

    gdr = _task("gdr", total_bytes=8, transport=TransportKind.RDMA_GDR)
    gdr_lease = manager.acquire(gdr, lease_id="lease:gdr", duration_ns=8)
    assert gdr_lease.staging_allocations == ()
    assert host.bytes_in("FREE") == host.capacity_bytes
    assert not any(account.startswith("HOST_STAGING:staging:gdr") for account in host.accounts)

    with pytest.raises(TransferResourceError, match="cannot reserve Host staging"):
        manager.acquire(
            _task("bad-gdr", total_bytes=8, transport=TransportKind.RDMA_GDR),
            lease_id="lease:bad-gdr",
            duration_ns=8,
            staging_specs={
                host.resource_id: _staging_spec("bad-gdr", payload_bytes=8, allocated_bytes=8)
            },
        )


def test_capacity_and_concurrency_deadline_fail_before_task_or_calendar_mutation() -> None:
    _des, host, calendars, manager = _manager(host_capacity_bytes=8)
    tcp = _task(
        "too-large",
        total_bytes=10,
        transport=TransportKind.TCP_HOST_STAGED,
        staging_resource_id=host.resource_id,
    )
    before_accounts = host.accounts

    with pytest.raises(TransferResourceUnavailable, match="insufficient Host staging"):
        manager.acquire(
            tcp,
            lease_id="lease:too-large",
            duration_ns=10,
            staging_specs={
                host.resource_id: _staging_spec("too-large", payload_bytes=10, allocated_bytes=16)
            },
        )

    assert tcp.status is TransferStatus.WAITING
    assert host.accounts == before_accounts
    assert all(resource.reservations() == () for resource in calendars.values())
    assert manager.active_lease_ids == ()

    occupied = calendars["gpu.copy-lane"].reserve(
        ready_ns=0,
        duration_ns=20,
        reservation_id="external:copy",
        cause="EXTERNAL_BASELINE_COPY",
    )
    gdr = _task(
        "deadline",
        total_bytes=8,
        transport=TransportKind.RDMA_GDR,
        concurrency_ids=("gpu.copy-lane",),
    )
    with pytest.raises(TransferResourceUnavailable, match="latest_start_ns"):
        manager.acquire(
            gdr,
            lease_id="lease:deadline",
            duration_ns=5,
            latest_start_ns=0,
        )

    assert gdr.status is TransferStatus.WAITING
    assert calendars["gpu.copy-lane"].reservations() == (occupied,)
    assert host.accounts == before_accounts


def test_concurrency_resources_queue_at_one_common_non_overlapping_slot() -> None:
    des, _host, calendars, manager = _manager()
    runtime = _runtime(des)
    first = _task("first", total_bytes=10, transport=TransportKind.RDMA_GDR)
    second = _task("second", total_bytes=5, transport=TransportKind.RDMA_GDR)

    first_lease = manager.acquire(first, lease_id="lease:first", duration_ns=10)
    second_lease = manager.acquire(second, lease_id="lease:second", duration_ns=5)

    assert (first_lease.start_ns, first_lease.end_ns) == (0, 10)
    assert (second_lease.start_ns, second_lease.end_ns) == (10, 15)
    for resource in calendars.values():
        reservations = resource.reservations()
        assert [(item.start_ns, item.end_ns) for item in reservations] == [(0, 10), (10, 15)]
        assert all(left.end_ns <= right.start_ns for left, right in pairwise(reservations))

    with pytest.raises(TransferResourceUnavailable, match="exact reserved"):
        manager.start_task(runtime, second, lease_id=second_lease.lease_id)
    assert second.status.value == TransferStatus.WAITING.value

    manager.start_task(runtime, first, lease_id=first_lease.lease_id)
    des.run(until_ns=10)
    assert first.status is TransferStatus.COMPLETED
    assert manager.lease(first_lease.lease_id).status is TransferLeaseStatus.RELEASED

    manager.start_task(runtime, second, lease_id=second_lease.lease_id)
    des.run()
    assert second.status is TransferStatus.COMPLETED
    assert manager.active_lease_ids == ()
    assert all(resource.reservations() == () for resource in calendars.values())

    waits = transfer_flow_queue_wait_ns_by_flow(des.journal)
    assert waits == {
        "transfer-flow:first:slice-000000": 0,
        "transfer-flow:second:slice-000000": 10,
    }
    rows = build_flow_rate_event_rows(
        runtime.controller.model.intervals,
        queue_wait_ns_by_flow=waits,
    )
    assert next(
        row for row in rows if row.flow_id == "transfer-flow:first:slice-000000"
    ).queue_wait_ns == 0
    assert next(
        row for row in rows if row.flow_id == "transfer-flow:second:slice-000000"
    ).queue_wait_ns == 10


def test_two_calendar_lanes_finish_simultaneously_and_release_both_leases() -> None:
    calendars = {
        resource_id: ConcurrencyResource(resource_id=resource_id, lanes=2)
        for resource_id in ("gpu.copy-lane", "endpoint.qp-lane")
    }
    des, _host, calendars, manager = _manager(resources=calendars)
    runtime = _runtime(des)
    first = _task("same-time-a", total_bytes=10, transport=TransportKind.RDMA_GDR)
    second = _task("same-time-b", total_bytes=10, transport=TransportKind.RDMA_GDR)
    first_lease = manager.acquire(first, lease_id="lease:same-time-a", duration_ns=20)
    second_lease = manager.acquire(second, lease_id="lease:same-time-b", duration_ns=20)

    assert first_lease.start_ns == second_lease.start_ns == 0
    assert {
        item.lane
        for lease in (first_lease, second_lease)
        for item in lease.concurrency_reservations
        if item.resource_id == "gpu.copy-lane"
    } == {0, 1}
    manager.start_task(runtime, first, lease_id=first_lease.lease_id)
    manager.start_task(runtime, second, lease_id=second_lease.lease_id)
    des.run()

    assert first.end_ns == second.end_ns == 20
    assert first.status is second.status is TransferStatus.COMPLETED
    assert manager.active_lease_ids == ()
    assert all(resource.reservations() == () for resource in calendars.values())
    assert transfer_resource_calendar_replay_byte_identical(des.journal, manager)
    assert transfer_flow_replay_byte_identical(
        des.journal,
        runtime.controller.model,
    )


def test_gpu_failure_releases_all_staging_and_lanes_once() -> None:
    des, host, calendars, manager = _manager()
    runtime = _runtime(des)
    task = _task(
        "failure",
        total_bytes=100,
        transport=TransportKind.TCP_HOST_STAGED,
        staging_resource_id=host.resource_id,
    )
    lease = manager.acquire(
        task,
        lease_id="lease:failure",
        duration_ns=100,
        staging_specs={
            host.resource_id: _staging_spec("failure", payload_bytes=100, allocated_bytes=104)
        },
    )
    manager.start_task(runtime, task, lease_id=lease.lease_id)

    def fail(_event: object, _des: GlobalDES) -> None:
        runtime.abort_task("failure", reason="GPU_FAILURE:node-0.gpu-0")

    des.register_handler(EventKind.FAILURE_INJECT, fail)
    des.schedule_at(50, EventKind.FAILURE_INJECT, event_id="failure:node-0.gpu-0")
    des.run()

    released = manager.lease(lease.lease_id)
    assert task.status is TransferStatus.CANCELED
    assert released.status is TransferLeaseStatus.RELEASED
    assert released.outcome is TransferLeaseOutcome.GPU_FAILURE
    assert released.release_reason == "GPU_FAILURE:node-0.gpu-0"
    assert host.bytes_in("FREE") == host.capacity_bytes
    assert all(resource.reservations() == () for resource in calendars.values())
    with pytest.raises(TransferResourceError, match="already released"):
        manager.release(
            lease.lease_id,
            outcome=TransferLeaseOutcome.GPU_FAILURE,
            reason="GPU_FAILURE:duplicate",
        )


def test_transfer_duration_overrun_fails_closed_without_reusing_the_lane() -> None:
    des, host, calendars, manager = _manager()
    runtime = _runtime(des, rate_bytes_per_second=1_000_000_000.0)
    task = _task("overrun", total_bytes=100, transport=TransportKind.RDMA_GDR)
    lease = manager.acquire(task, lease_id="lease:overrun", duration_ns=10)
    manager.start_task(runtime, task, lease_id=lease.lease_id)

    with pytest.raises(TransferResourceError, match="exceeded its reserved"):
        des.run()

    assert task.status is TransferStatus.COMPLETED
    assert manager.lease(lease.lease_id).status is TransferLeaseStatus.STARTED
    assert all(resource.reservations() for resource in calendars.values())
    assert host.bytes_in("FREE") == host.capacity_bytes


def test_resource_journal_is_byte_identical_and_rebuilds_ledgers_and_calendars() -> None:
    def run_once() -> tuple[
        bytes,
        CapacityLedger,
        dict[str, ConcurrencyResource],
        ReplayedTransferResourceState,
    ]:
        des, host, calendars, manager = _manager()
        tcp = _task(
            "replay-tcp",
            total_bytes=8,
            transport=TransportKind.TCP_HOST_STAGED,
            staging_resource_id=host.resource_id,
        )
        gdr = _task("replay-gdr", total_bytes=5, transport=TransportKind.RDMA_GDR)
        tcp_lease = manager.acquire(
            tcp,
            lease_id="lease:replay-tcp",
            duration_ns=10,
            staging_specs={
                host.resource_id: _staging_spec("replay-tcp", payload_bytes=8, allocated_bytes=8)
            },
        )
        manager.acquire(gdr, lease_id="lease:replay-gdr", duration_ns=5)
        manager.release(
            tcp_lease.lease_id,
            outcome=TransferLeaseOutcome.ABORTED,
            reason="TEST_ABORT",
        )

        replayed_host = _host_ledger()
        replay_capacity_transactions(des.journal, {replayed_host.resource_id: replayed_host})
        replayed_calendars = _resources()
        replayed_state = replay_transfer_resource_calendar(des.journal, replayed_calendars)
        assert transfer_resource_calendar_replay_byte_identical(
            des.journal,
            manager,
        )
        assert replayed_state.snapshot_bytes() == manager.snapshot().snapshot_bytes()
        assert replayed_host.accounts == host.accounts
        assert {
            resource_id: resource.reservations()
            for resource_id, resource in replayed_calendars.items()
        } == {resource_id: resource.reservations() for resource_id, resource in calendars.items()}
        return des.journal.to_jsonl_bytes(), host, calendars, replayed_state

    first, _host, _calendars, replayed = run_once()
    second, _host_again, _calendars_again, replayed_again = run_once()

    assert first == second
    assert replayed == replayed_again
    assert replayed.active_lease_ids == ("lease:replay-gdr",)
    assert replayed.released_lease_ids == ("lease:replay-tcp",)
    assert replayed.staging_allocation_states == (("staging:replay-tcp", AllocationState.RELEASED),)
    assert EVIDENCE_BOUNDARY.encode() in first
    assert b"transfer_duration_and_overlap_are_uncalibrated" in first


def test_transfer_resource_replay_gate_detects_online_calendar_tamper() -> None:
    des, _host, calendars, manager = _manager()
    task = _task("calendar-tamper", total_bytes=5, transport=TransportKind.RDMA_GDR)
    lease = manager.acquire(task, lease_id="lease:calendar-tamper", duration_ns=5)

    assert transfer_resource_calendar_replay_byte_identical(des.journal, manager)
    reservation = lease.concurrency_reservations[0]
    assert calendars[reservation.resource_id].cancel(reservation.reservation_id) == reservation
    assert not transfer_resource_calendar_replay_byte_identical(des.journal, manager)


def test_invalid_release_metadata_fails_before_any_state_mutation() -> None:
    des, host, calendars, manager = _manager()
    task = _task("bad-release", total_bytes=5, transport=TransportKind.RDMA_GDR)
    lease = manager.acquire(task, lease_id="lease:bad-release", duration_ns=5)
    before_manager = manager.snapshot().snapshot_bytes()
    before_journal = des.journal.to_jsonl_bytes()
    before_accounts = host.accounts
    before_calendars = {
        resource_id: resource.reservations()
        for resource_id, resource in calendars.items()
    }

    with pytest.raises(TypeError, match="TransferLeaseOutcome"):
        manager.release(
            lease.lease_id,
            outcome="COMPLETED",  # type: ignore[arg-type]
            reason="INVALID_ENUM",
        )

    assert manager.snapshot().snapshot_bytes() == before_manager
    assert des.journal.to_jsonl_bytes() == before_journal
    assert host.accounts == before_accounts
    assert {
        resource_id: resource.reservations()
        for resource_id, resource in calendars.items()
    } == before_calendars


def test_empty_resource_manager_has_a_byte_identical_replay_gate() -> None:
    des = GlobalDES()
    manager = TransferResourceLeaseManager(
        des=des,
        capacity_ledgers={},
        concurrency_resources={},
    )
    task = _task(
        "empty-manager",
        total_bytes=5,
        transport=TransportKind.RDMA_GDR,
        concurrency_ids=(),
    )
    lease = manager.acquire(task, lease_id="lease:empty-manager", duration_ns=5)
    manager.release(
        lease.lease_id,
        outcome=TransferLeaseOutcome.ABORTED,
        reason="TEST_ABORT_BEFORE_START",
    )

    assert manager.snapshot().calendar_reservations == ()
    assert transfer_resource_calendar_replay_byte_identical(des.journal, manager)


def test_resource_replay_detects_release_outcome_and_duplicate_id_tamper() -> None:
    des, _host, _calendars, manager = _manager()
    task = _task("release-tamper", total_bytes=5, transport=TransportKind.RDMA_GDR)
    lease = manager.acquire(task, lease_id="lease:release-tamper", duration_ns=5)
    manager.release(
        lease.lease_id,
        outcome=TransferLeaseOutcome.ABORTED,
        reason="EXPECTED_ABORT",
    )
    release_record = next(
        record
        for record in des.journal.records
        if record.record_type == "TRANSFER_RESOURCE_LEASE_RELEASED"
    )

    release_record.data["outcome"] = TransferLeaseOutcome.COMPLETED.value
    assert not transfer_resource_calendar_replay_byte_identical(des.journal, manager)

    release_record.data["outcome"] = TransferLeaseOutcome.ABORTED.value
    reservation_ids = release_record.data["concurrency_reservation_ids"]
    assert isinstance(reservation_ids, list) and reservation_ids
    reservation_ids.append(reservation_ids[0])
    with pytest.raises(TransferResourceError, match="unique strings"):
        replay_transfer_resource_calendar(des.journal, _resources())
