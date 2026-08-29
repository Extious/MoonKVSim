from __future__ import annotations

from dataclasses import replace

import pytest

from moonkvsim.simulation.event import EventKind
from moonkvsim.simulation.flow_des import FlowDESController
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.network import FlowContentionModel
from moonkvsim.simulation.resource import RateResource
from moonkvsim.store.transfer_engine import (
    MemoryKind,
    MemoryLocation,
    SliceStatus,
    TopologyPath,
    TransferMetadata,
    TransferOpcode,
    TransferStatus,
    TransferTask,
    TransportKind,
)
from moonkvsim.store.transfer_runtime import (
    EVIDENCE_BOUNDARY,
    TransferRuntime,
    TransferRuntimeError,
    replay_transfer_flow_state,
    transfer_flow_replay_byte_identical,
)


def _location(resource_id: str, *, gpu: bool) -> MemoryLocation:
    node_id = resource_id.split(".", maxsplit=1)[0]
    return MemoryLocation(
        resource_id=resource_id,
        node_id=node_id,
        numa_node_id=f"numa:{node_id}:0",
        kind=MemoryKind.GPU_HBM if gpu else MemoryKind.STORE_DRAM,
        endpoint=f"rdma://{resource_id}",
        gpu_id=f"{node_id}.gpu-0" if gpu else None,
    )


def _task(
    transfer_id: str,
    *,
    total_bytes: int,
    slice_size_bytes: int,
    path_resource_ids: tuple[str, ...] = ("source", "link", "destination"),
    ready_ns: int = 0,
) -> TransferTask:
    source = _location(f"{transfer_id}.hbm", gpu=True)
    destination = _location(f"{transfer_id}.store", gpu=False)
    path = TopologyPath(
        path_id=f"path:{transfer_id}",
        source_kind=MemoryKind.GPU_HBM,
        destination_kind=MemoryKind.STORE_DRAM,
        transport=TransportKind.RDMA_GDR,
        rate_resource_ids=path_resource_ids,
        concurrency_resource_ids=(f"copy:{transfer_id}",),
        source_endpoint=source.endpoint,
        destination_endpoint=destination.endpoint,
        source_node_id=source.node_id,
        destination_node_id=destination.node_id,
        source_numa_node_id=source.numa_node_id,
        destination_numa_node_id=destination.numa_node_id,
        source_hca_id=f"{source.node_id}.hca-0",
        destination_hca_id=f"{destination.node_id}.hca-0",
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
            ready_ns=ready_ns,
            path=path,
        ),
        slice_size_bytes=slice_size_bytes,
    )


def _runtime(
    capacities: dict[str, float] | None = None,
) -> tuple[GlobalDES, FlowContentionModel, TransferRuntime]:
    configured = capacities or {
        "source": 1_000_000_000.0,
        "link": 1_000_000_000.0,
        "destination": 1_000_000_000.0,
    }
    des = GlobalDES()
    model = FlowContentionModel(
        [RateResource(resource_id, capacity) for resource_id, capacity in configured.items()]
    )
    runtime = TransferRuntime(controller=FlowDESController(des=des, model=model))
    return des, model, runtime


def _active_flow_ids(runtime: TransferRuntime) -> tuple[str, ...]:
    return runtime.active_flow_ids


def _active_transfer_ids(runtime: TransferRuntime) -> tuple[str, ...]:
    return runtime.active_transfer_ids


def test_slices_map_to_exact_resource_path_and_conserve_bytes() -> None:
    des, model, runtime = _runtime()
    task = _task("transfer-a", total_bytes=10, slice_size_bytes=4)

    runtime.start_task(task)

    assert [item.status for item in task.slices] == [
        SliceStatus.POSTED,
        SliceStatus.POSTED,
        SliceStatus.POSTED,
    ]
    flows = sorted(model.flows.values(), key=lambda item: item.slice_id)
    assert [item.payload_bytes for item in flows] == [4, 4, 2]
    assert {item.path_resource_ids for item in flows} == {task.metadata.path.rate_resource_ids}
    assert sum(item.payload_bytes for item in flows) == task.metadata.total_bytes
    assert task.start_ns == 0
    started_slice_ids = [
        record.data["slice_id"]
        for record in des.journal.records
        if record.record_type == "TRANSFER_RUNTIME_SLICE_FLOW_STARTED"
    ]
    assert started_slice_ids == [item.slice_id for item in task.slices]
    runtime.audit()

    des.run()

    assert task.status is TransferStatus.COMPLETED
    assert task.transferred_bytes == task.metadata.total_bytes == 10
    assert all(item.status is SliceStatus.SUCCESS for item in task.slices)
    assert runtime.active_flow_ids == ()
    assert model.flows == {}
    assert sum(item.transferred_bytes for item in model.intervals) == pytest.approx(10.0)
    replayed = replay_transfer_flow_state(des.journal, model.resources)
    assert replayed.snapshot_bytes() == model.snapshot_bytes()
    assert transfer_flow_replay_byte_identical(des.journal, model)
    task.audit()


def test_start_fails_closed_before_mutation_for_unknown_path_or_bad_bytes() -> None:
    des, model, runtime = _runtime()
    unknown_path = _task(
        "unknown-path",
        total_bytes=8,
        slice_size_bytes=8,
        path_resource_ids=("source", "missing-link", "destination"),
    )

    with pytest.raises(TransferRuntimeError, match="unknown rate resources"):
        runtime.start_task(unknown_path)

    assert unknown_path.status is TransferStatus.WAITING
    assert model.flows == {}
    assert des.journal.records == ()

    bad_bytes = _task("bad-bytes", total_bytes=8, slice_size_bytes=4)
    bad_bytes.slices[1] = replace(bad_bytes.slices[1], offset_bytes=5)
    with pytest.raises(TransferRuntimeError, match="byte-layout audit"):
        runtime.start_task(bad_bytes)
    assert bad_bytes.status is TransferStatus.WAITING
    assert model.flows == {}


def test_add_flow_failure_atomically_cancels_partially_started_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    des, model, runtime = _runtime()
    task = _task("atomic-start", total_bytes=10, slice_size_bytes=4)
    original_recompute = model._recompute_rates
    injected = False
    terminal: list[TransferStatus] = []

    def fail_second_add() -> None:
        nonlocal injected
        if len(model.flows) == 2 and not injected:
            injected = True
            raise RuntimeError("injected add_flow failure")
        original_recompute()

    monkeypatch.setattr(model, "_recompute_rates", fail_second_add)
    with pytest.raises(RuntimeError, match="injected add_flow failure"):
        runtime.start_task(
            task,
            on_terminal=lambda item, _des: terminal.append(item.status),
        )

    assert injected
    assert task.status is TransferStatus.CANCELED
    assert all(item.status is SliceStatus.CANCELED for item in task.slices)
    assert terminal == [TransferStatus.CANCELED]
    assert runtime.active_flow_ids == ()
    assert runtime.active_transfer_ids == ()
    assert model.flows == {}
    assert runtime.controller._completion_handlers == {}
    assert des.pending_count == 0
    assert des.journal.records[-1].record_type == "TRANSFER_RUNTIME_TASK_ABORTED"
    runtime.audit()


def test_two_transfers_share_link_and_controller_reorders_completions() -> None:
    capacities = {
        "source-a": 1_000.0,
        "source-b": 1_000.0,
        "shared-link": 100.0,
        "destination-a": 1_000.0,
        "destination-b": 1_000.0,
    }
    des, model, runtime = _runtime(capacities)
    long_task = _task(
        "long",
        total_bytes=100,
        slice_size_bytes=100,
        path_resource_ids=("source-a", "shared-link", "destination-a"),
    )
    short_task = _task(
        "short",
        total_bytes=50,
        slice_size_bytes=50,
        path_resource_ids=("source-b", "shared-link", "destination-b"),
    )

    runtime.start_task(long_task)
    runtime.start_task(short_task)
    des.run()

    assert short_task.end_ns == 1_000_000_000
    assert long_task.end_ns == 1_500_000_000
    assert short_task.status is long_task.status is TransferStatus.COMPLETED
    assert sum(item.transferred_bytes for item in model.intervals) == pytest.approx(150.0)
    canceled = [
        record
        for record in des.journal.records
        if record.record_type == "EVENT_CANCELED"
        and record.data["reason"] == "FLOW_RATE_RECOMPUTED"
    ]
    assert canceled


def test_same_time_gpu_failure_beats_slice_completion() -> None:
    des, model, runtime = _runtime()
    task = _task("failure-race", total_bytes=10, slice_size_bytes=10)
    runtime.start_task(task)

    def fail(_event: object, _des: GlobalDES) -> None:
        runtime.abort_task("failure-race", reason="GPU_FAILURE:gpu-0")

    des.register_handler(EventKind.FAILURE_INJECT, fail)
    des.schedule_at(10, EventKind.FAILURE_INJECT, event_id="failure:gpu-0")
    des.run()

    assert task.status is TransferStatus.CANCELED
    assert task.transferred_bytes == 0
    assert task.slices[0].status is SliceStatus.CANCELED
    assert task.slices[0].terminal_ns == 10
    assert runtime.active_flow_ids == ()
    assert model.flows == {}
    executed_kinds = [
        record.data["kind"]
        for record in des.journal.records
        if record.record_type == "EVENT_EXECUTING"
    ]
    assert executed_kinds == [EventKind.FAILURE_INJECT.value]
    assert not any(
        record.record_type == "TRANSFER_RUNTIME_SLICE_FLOW_COMPLETED"
        for record in des.journal.records
    )


def test_abort_cancels_every_flow_and_releases_runtime_mappings() -> None:
    des, model, runtime = _runtime()
    task = _task("operator-abort", total_bytes=25, slice_size_bytes=10)
    runtime.start_task(task)

    assert len(_active_flow_ids(runtime)) == 3
    assert _active_transfer_ids(runtime) == ("operator-abort",)
    des.run(until_ns=20)
    assert task.slices[2].status is SliceStatus.SUCCESS
    assert len(_active_flow_ids(runtime)) == 2
    runtime.abort_task("operator-abort", reason="OPERATOR_ABORT")

    assert task.status is TransferStatus.CANCELED
    assert [item.status for item in task.slices] == [
        SliceStatus.CANCELED,
        SliceStatus.CANCELED,
        SliceStatus.SUCCESS,
    ]
    assert task.transferred_bytes == 5
    assert _active_flow_ids(runtime) == ()
    assert _active_transfer_ids(runtime) == ()
    assert model.flows == {}
    runtime.audit()


def test_transfer_runtime_journal_is_byte_deterministic_and_marks_evidence_gap() -> None:
    def run_once() -> bytes:
        des, _model, runtime = _runtime()
        runtime.start_task(_task("deterministic", total_bytes=9, slice_size_bytes=4))
        des.run()
        return des.journal.to_jsonl_bytes()

    first = run_once()
    second = run_once()

    assert first == second
    assert EVIDENCE_BOUNDARY.encode() in first
    assert b"host_staging_capacity_transactions_are_external_to_transfer_runtime" in first


def test_flow_rate_replay_gate_detects_online_interval_tamper() -> None:
    des, model, runtime = _runtime()
    runtime.start_task(_task("rate-tamper", total_bytes=9, slice_size_bytes=4))
    des.run()

    assert transfer_flow_replay_byte_identical(des.journal, model)
    model.intervals[0] = replace(
        model.intervals[0],
        transferred_bytes=model.intervals[0].transferred_bytes + 0.5,
    )
    assert not transfer_flow_replay_byte_identical(des.journal, model)
