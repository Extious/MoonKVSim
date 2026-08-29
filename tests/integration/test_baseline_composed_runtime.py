from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from moonkvsim.baseline.runtime import (
    EVIDENCE_BOUNDARY,
    BaselineCoordinator,
    BaselineCoordinatorError,
    BaselineReplicaRuntime,
    ForwardBatchTerminal,
    TransferTaskResourcePlan,
    _compact_scheduler_output,
)
from moonkvsim.common.hash import canonical_json_bytes, sha256_json
from moonkvsim.common.types import KVIdentity
from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.hbm_block_ledger import (
    HBM_RECOVERY_RESERVED_ACCOUNT,
    HbmBlockLedgerBridge,
    HbmStageRankBinding,
)
from moonkvsim.integration.vllm.kv_layout import StageBlockLayout
from moonkvsim.integration.vllm.request import Request, RequestStatus
from moonkvsim.integration.vllm.router import DPRouter, RoutePolicy
from moonkvsim.integration.vllm.scheduler import (
    ContinuousBatchScheduler,
    ScheduledRequest,
    SchedulerOutput,
    SchedulingOrigin,
    SchedulingPhase,
)
from moonkvsim.recovery.baseline import (
    AttemptStatus,
    EngineTarget,
    PhysicalGPU,
    SilentReplayPlan,
    SilentReplayStatus,
)
from moonkvsim.simulation.allocation import AllocationState
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.audit import generate_capacity_audit
from moonkvsim.simulation.flow_des import FlowDESController
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.network import FlowContentionModel
from moonkvsim.simulation.replay import replay_capacity_transactions
from moonkvsim.simulation.resource import ConcurrencyResource, RateResource
from moonkvsim.store.allocation_strategy import RandomAllocationStrategy
from moonkvsim.store.client import GetOperationState, PutOperationState, StoreClient
from moonkvsim.store.master import STORE_COMMITTED_ACCOUNT, MasterService
from moonkvsim.store.segment import Segment
from moonkvsim.store.transfer_engine import (
    MemoryKind,
    MemoryLocation,
    Topology,
    TopologyPath,
    TransferStatus,
    TransferTask,
    TransportKind,
)
from moonkvsim.store.transfer_resources import (
    StagingAllocationSpec,
    TransferLeaseOutcome,
    TransferLeaseStatus,
    TransferResourceError,
    TransferResourceLeaseManager,
    replay_transfer_resource_calendar,
)
from moonkvsim.store.transfer_runtime import TransferRuntime


@dataclass(slots=True)
class _Harness:
    des: GlobalDES
    coordinator: BaselineCoordinator
    master: MasterService
    initial_ledgers: dict[str, CapacityLedger]
    scheduler0: ContinuousBatchScheduler
    scheduler1: ContinuousBatchScheduler
    schedulers: tuple[ContinuousBatchScheduler, ...]
    transfer_resource_manager: TransferResourceLeaseManager | None = None
    host_staging_ledger: CapacityLedger | None = None
    concurrency_resources: dict[str, ConcurrencyResource] | None = None
    hbm_ledgers: dict[str, CapacityLedger] | None = None


def _gpu(gpu_id: str, node_id: str) -> MemoryLocation:
    return MemoryLocation(
        resource_id=f"{gpu_id}.hbm",
        node_id=node_id,
        numa_node_id=f"numa:{node_id}:0",
        kind=MemoryKind.GPU_HBM,
        endpoint=f"rdma://{node_id}/{gpu_id}",
        gpu_id=gpu_id,
    )


def _path(
    path_id: str,
    source: MemoryLocation,
    destination: MemoryLocation,
    rate_resource_ids: tuple[str, ...],
    *,
    concurrency_resource_ids: tuple[str, ...] = (),
    transport: TransportKind = TransportKind.RDMA_GDR,
    source_host_staging_resource_id: str | None = None,
    destination_host_staging_resource_id: str | None = None,
) -> TopologyPath:
    return TopologyPath(
        path_id=path_id,
        source_kind=source.kind,
        destination_kind=destination.kind,
        transport=transport,
        rate_resource_ids=rate_resource_ids,
        concurrency_resource_ids=concurrency_resource_ids,
        source_endpoint=source.endpoint,
        destination_endpoint=destination.endpoint,
        source_node_id=source.node_id,
        destination_node_id=destination.node_id,
        source_numa_node_id=source.numa_node_id,
        destination_numa_node_id=destination.numa_node_id,
        source_hca_id=f"{source.node_id}.hca-0",
        destination_hca_id=f"{destination.node_id}.hca-0",
        source_host_staging_resource_id=source_host_staging_resource_id,
        destination_host_staging_resource_id=destination_host_staging_resource_id,
    )


def _hbm_layout() -> StageBlockLayout:
    return StageBlockLayout(
        pp_stage=0,
        tensor_parallel_rank=0,
        block_size_tokens=16,
        layer_names=("fixture.layer.0.self_attn",),
        layer_indices=(0,),
        tensor_payload_bytes=100,
        auxiliary_payload_bytes=4,
        payload_bytes=104,
        layout_padding_bytes=8,
        allocator_metadata_bytes=4,
        requested_bytes=112,
        internal_fragmentation_bytes=12,
        allocated_bytes=128,
        allocator_alignment_bytes=16,
    )


def _scheduler(
    observer: HbmBlockLedgerBridge | None = None,
) -> ContinuousBatchScheduler:
    return ContinuousBatchScheduler(
        block_pool=BlockPool(16, enable_caching=False),
        block_size_tokens=16,
        max_num_scheduled_tokens=32,
        max_num_running_requests=4,
        block_lifecycle_observer=observer,
    )


def _harness(
    *,
    concurrency_resource_ids: tuple[str, ...] = (),
    transport: TransportKind = TransportKind.RDMA_GDR,
    host_staging_resource_id: str | None = None,
    configure_transfer_resources: bool = False,
    wire_hbm_failure: bool = True,
    replica_count: int = 2,
    swap_scheduler_hbm_observers: bool = False,
) -> _Harness:
    if replica_count < 2:
        raise ValueError("baseline test harness requires at least two replicas")
    des = GlobalDES()
    registry = AllocationRegistry(journal=des.journal)
    master = MasterService(
        allocation_strategy=RandomAllocationStrategy(seed=11),
        journal=des.journal,
        allocation_registry=registry,
    )
    master.mount_segment(
        Segment(
            segment_id="shared-store-0",
            name="shared-store-0",
            node_id="store-node",
            numa_node_id="numa:store-node:0",
            transport_endpoint="rdma://shared-store-0",
            capacity_bytes=4096,
            allocation_alignment_bytes=64,
            allocator_metadata_bytes=0,
        ),
        CapacityLedger(
            resource_id="shared-store-0",
            resource_kind=CapacityResourceKind.STORE_DRAM,
            capacity_bytes=4096,
        ),
        timestamp_ns=0,
    )
    initial_ledgers: dict[str, CapacityLedger] = {
        "shared-store-0": CapacityLedger(
            resource_id="shared-store-0",
            resource_kind=CapacityResourceKind.STORE_DRAM,
            capacity_bytes=4096,
        )
    }
    gpu_locations = tuple(_gpu(f"gpu-{rank}", f"node-{rank}") for rank in range(replica_count))
    store_location = MemoryLocation(
        resource_id="shared-store-0",
        node_id="store-node",
        numa_node_id="numa:store-node:0",
        kind=MemoryKind.STORE_DRAM,
        endpoint="rdma://shared-store-0",
    )
    topology = Topology(
        [
            path
            for rank, gpu_location in enumerate(gpu_locations)
            for path in (
                _path(
                    f"direct-put:dp-{rank}",
                    gpu_location,
                    store_location,
                    ("gpu-read", "shared-fabric", "store-write"),
                    concurrency_resource_ids=concurrency_resource_ids,
                    transport=transport,
                    source_host_staging_resource_id=host_staging_resource_id,
                ),
                _path(
                    f"direct-get:dp-{rank}",
                    store_location,
                    gpu_location,
                    ("store-read", "shared-fabric", "gpu-write"),
                    concurrency_resource_ids=concurrency_resource_ids,
                    transport=transport,
                    destination_host_staging_resource_id=host_staging_resource_id,
                ),
            )
        ]
    )
    clients = tuple(
        StoreClient(
            client_id=f"client-dp{rank}",
            master=master,
            topology=topology,
            local_gpu=gpu_locations[rank],
            registered_at_ns=0,
            slice_size_bytes=64,
        )
        for rank in range(replica_count)
    )
    model = FlowContentionModel(
        [
            RateResource("gpu-read", 1_000_000_000.0),
            RateResource("shared-fabric", 500_000_000.0),
            RateResource("store-write", 1_000_000_000.0),
            RateResource("store-read", 1_000_000_000.0),
            RateResource("gpu-write", 1_000_000_000.0),
        ]
    )
    transfer_runtime = TransferRuntime(controller=FlowDESController(des=des, model=model))
    host_staging_ledger = None
    concurrency_resources: dict[str, ConcurrencyResource] = {}
    transfer_resource_manager = None
    if configure_transfer_resources:
        if host_staging_resource_id is not None:
            host_staging_ledger = CapacityLedger(
                resource_id=host_staging_resource_id,
                resource_kind=CapacityResourceKind.HOST_DRAM,
                capacity_bytes=4096,
            )
        concurrency_resources = {
            resource_id: ConcurrencyResource(resource_id=resource_id, lanes=1)
            for resource_id in concurrency_resource_ids
        }
        transfer_resource_manager = TransferResourceLeaseManager(
            des=des,
            capacity_ledgers=(
                {}
                if host_staging_ledger is None
                else {host_staging_ledger.resource_id: host_staging_ledger}
            ),
            concurrency_resources=concurrency_resources,
        )
    hbm_ledgers = {
        f"gpu-{rank}.hbm": CapacityLedger(
            resource_id=f"gpu-{rank}.hbm",
            resource_kind=CapacityResourceKind.GPU_HBM,
            capacity_bytes=4096,
        )
        for rank in range(replica_count)
    }
    hbm_observers = tuple(
        HbmBlockLedgerBridge(
            bridge_id=f"composed:dp-{rank}:hbm",
            bindings=(
                HbmStageRankBinding(
                    f"gpu-{rank}.hbm",
                    _hbm_layout(),
                ),
            ),
            ledgers={f"gpu-{rank}.hbm": hbm_ledgers[f"gpu-{rank}.hbm"]},
            registry=registry,
            journal=des.journal,
            now_ns=lambda: des.now_ns,
        )
        for rank in range(replica_count)
    )
    for resource_id, ledger in hbm_ledgers.items():
        initial_ledgers[resource_id] = CapacityLedger(
            resource_id=resource_id,
            resource_kind=CapacityResourceKind.GPU_HBM,
            capacity_bytes=ledger.capacity_bytes,
        )
    scheduler_observers = (
        tuple(reversed(hbm_observers)) if swap_scheduler_hbm_observers else hbm_observers
    )
    schedulers = tuple(_scheduler(scheduler_observers[rank]) for rank in range(replica_count))
    replicas = tuple(
        BaselineReplicaRuntime(
            f"dp-{rank}",
            rank,
            f"scheduler-{rank}",
            f"gpu-{rank}",
            schedulers[rank],
            clients[rank],
        )
        for rank in range(replica_count)
    )
    coordinator = BaselineCoordinator(
        des=des,
        router=DPRouter(router_id="external-router", policy=RoutePolicy.LEAST_LOADED),
        replicas=replicas,
        master=master,
        transfer_runtime=transfer_runtime,
        transfer_resource_manager=transfer_resource_manager,
        gpus=tuple(
            PhysicalGPU(
                f"gpu-{rank}",
                f"node-{rank}",
                (f"gpu-{rank}.hbm",),
            )
            for rank in range(replica_count)
        ),
        targets=tuple(
            EngineTarget(
                f"dp-{rank}",
                rank,
                (f"gpu-{rank}",),
                "qwen3-tp1-pp1",
            )
            for rank in range(replica_count)
        ),
        hbm_ledgers=hbm_ledgers if wire_hbm_failure else None,
        hbm_failure_observers=hbm_observers if wire_hbm_failure else (),
    )
    return _Harness(
        des=des,
        coordinator=coordinator,
        master=master,
        initial_ledgers=initial_ledgers,
        scheduler0=schedulers[0],
        scheduler1=schedulers[1],
        schedulers=schedulers,
        transfer_resource_manager=transfer_resource_manager,
        host_staging_ledger=host_staging_ledger,
        concurrency_resources=concurrency_resources,
        hbm_ledgers=hbm_ledgers,
    )


def test_gpu_failure_rejects_an_unwired_hbm_topology_before_scheduling() -> None:
    harness = _harness(wire_hbm_failure=False)

    with pytest.raises(BaselineCoordinatorError, match="shared-registry HBM"):
        harness.coordinator.schedule_gpu_failure(
            failure_id="must-fail-closed",
            gpu_id="gpu-0",
            at_ns=0,
        )

    assert harness.des.pending_count == 0


def test_gpu_failure_rejects_scheduler_hbm_observers_swapped_between_targets() -> None:
    with pytest.raises(ValueError, match="engine target failure domain"):
        _harness(swap_scheduler_hbm_observers=True)


def _identity(block_index: int) -> KVIdentity:
    token_start = block_index * 16
    return KVIdentity(
        tenant_id="tenant-0",
        model_id="Qwen/Qwen3-8B",
        model_revision="toy-revision",
        kv_dtype="bf16",
        kv_abi="vllm-v1",
        kv_layout="toy-tp1-pp1",
        tp_size=1,
        pp_size=1,
        block_size_tokens=16,
        stable_block_hash=f"causal-hash-{block_index}",
        token_start=token_start,
        token_end=token_start + 16,
        shard_id="tp0",
        request_id="request-0",
        session_id="session-0",
        workflow_id="workflow-0",
        route_version=0,
        source_gpu_id="gpu-0",
    )


def _materialize_recovery_prompt(
    harness: _Harness,
    request_id: str,
) -> tuple[SchedulerOutput, ...]:
    """Run only internal recovery forwards until atomic activation is legal."""

    outputs: list[SchedulerOutput] = []
    for _ in range(128):
        replay = harness.coordinator.silent_replay_plan(request_id)
        if replay.status is SilentReplayStatus.READY_TO_ACTIVATE:
            return tuple(outputs)
        assert replay.status is SilentReplayStatus.REPLAYING
        outputs.append(harness.coordinator.run_silent_replay_scheduler_step(request_id))
        harness.coordinator.schedule_silent_replay_completion(
            request_id,
            at_ns=harness.des.now_ns + 1,
        )
        harness.des.run()
    raise AssertionError("recovery prompt materialization did not converge")


def _resource_plan(
    task: TransferTask,
    *,
    duration_ns: int,
    latest_start_ns: int | None = None,
) -> TransferTaskResourcePlan:
    path = task.metadata.path
    staging_resource_ids = tuple(
        dict.fromkeys(
            resource_id
            for resource_id in (
                path.source_host_staging_resource_id,
                path.destination_host_staging_resource_id,
            )
            if resource_id is not None
        )
    )
    allocated_bytes = ((task.metadata.total_bytes + 7) // 8) * 8
    return TransferTaskResourcePlan(
        duration_ns=duration_ns,
        latest_start_ns=latest_start_ns,
        staging_specs=tuple(
            StagingAllocationSpec(
                allocation_id=(f"baseline-staging:{task.metadata.transfer_id}:{resource_id}"),
                resource_id=resource_id,
                payload_bytes=task.metadata.total_bytes,
                requested_bytes=task.metadata.total_bytes,
                allocated_bytes=allocated_bytes,
                padding_bytes=0,
                allocator_metadata_bytes=0,
                internal_fragmentation_bytes=(allocated_bytes - task.metadata.total_bytes),
                alignment_bytes=8,
            )
            for resource_id in staging_resource_ids
        ),
    )


def _single_staging_plan(
    *,
    allocation_id: str,
    resource_id: str,
    payload_bytes: int,
    duration_ns: int,
    latest_start_ns: int | None = None,
) -> TransferTaskResourcePlan:
    allocated_bytes = ((payload_bytes + 7) // 8) * 8
    return TransferTaskResourcePlan(
        duration_ns=duration_ns,
        latest_start_ns=latest_start_ns,
        staging_specs=(
            StagingAllocationSpec(
                allocation_id=allocation_id,
                resource_id=resource_id,
                payload_bytes=payload_bytes,
                requested_bytes=payload_bytes,
                allocated_bytes=allocated_bytes,
                padding_bytes=0,
                allocator_metadata_bytes=0,
                internal_fragmentation_bytes=allocated_bytes - payload_bytes,
                alignment_bytes=8,
            ),
        ),
    )


def test_nonzero_recovery_prefix_fails_before_router_or_scheduler_mutation() -> None:
    harness = _harness()
    coordinator = harness.coordinator
    request = Request("request-0", 16, 1, harness.des.now_ns)

    with pytest.raises(ValueError, match="start at token zero"):
        coordinator.route_and_admit(
            request,
            required_blocks=(_identity(1),),
        )

    authority = coordinator.route_and_admit(
        request,
        required_blocks=(_identity(0),),
    )
    assert authority.route_version == 0
    assert authority.target_replica_id == "dp-0"
    coordinator.finish_current_request(request.request_id)
    coordinator.audit()


def test_partial_store_prefix_recomputes_without_leaking_target_scheduler_state() -> None:
    harness = _harness()
    coordinator = harness.coordinator
    partial = replace(_identity(0), token_end=8)
    request = Request("request-0", 8, 1, harness.des.now_ns)
    coordinator.route_and_admit(request, required_blocks=(partial,))
    coordinator.run_scheduler_step(request.request_id)
    put = coordinator.start_store_put(
        request.request_id,
        partial,
        put_id="partial-prefix",
        payload_bytes=64,
        preferred_segment_ids=("shared-store-0",),
    )
    harness.des.run()
    assert put.state is PutOperationState.COMMITTED

    coordinator.schedule_gpu_failure(
        failure_id="partial-prefix-failure",
        gpu_id="gpu-0",
        at_ns=harness.des.now_ns,
    )
    harness.des.run()
    plan = coordinator.recovery_plan(request.request_id)
    assert plan.store_prefix == ()
    assert plan.restored_tokens == 0
    assert plan.recompute_tokens == 8
    assert coordinator.start_recovery_fetches(request.request_id) == ()

    recovered = coordinator.prepare_recovery(request.request_id)
    assert recovered.status is RequestStatus.WAITING
    with pytest.raises(BaselineCoordinatorError, match="prompt materialization"):
        coordinator.activate_recovery(request.request_id)
    [recompute] = _materialize_recovery_prompt(harness, request.request_id)
    [item] = recompute.scheduled_new_reqs
    assert item.num_computed_tokens_before == 0
    assert item.num_computed_tokens_after == 8
    ready = coordinator.silent_replay_plan(request.request_id)
    assert ready.prompt_materialized
    assert ready.cached_new_output_index == 0
    assert coordinator.failure_controller.emitted_outputs == ()
    coordinator.activate_recovery(request.request_id)
    assert [output.output_index for output in coordinator.failure_controller.emitted_outputs] == [0]
    assert not coordinator.failure_controller.try_emit_output(
        request_id=request.request_id,
        route_version=1,
        output_index=0,
    )
    coordinator.finish_current_request(request.request_id)
    coordinator.audit()


def test_prepare_recovery_reservation_commit_failure_is_retryable_without_reallocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness()
    coordinator = harness.coordinator
    block = _identity(0)
    source = Request("request-0", 16, 1, harness.des.now_ns)
    coordinator.route_and_admit(source, required_blocks=(block,))
    coordinator.run_scheduler_step(source.request_id)
    put = coordinator.start_store_put(
        source.request_id,
        block,
        put_id="retryable-prefix",
        payload_bytes=64,
        preferred_segment_ids=("shared-store-0",),
    )
    harness.des.run()
    assert put.state is PutOperationState.COMMITTED
    coordinator.schedule_gpu_failure(
        failure_id="retryable-prepare-failure",
        gpu_id="gpu-0",
        at_ns=harness.des.now_ns,
    )
    harness.des.run()
    [recovery_get] = coordinator.start_recovery_fetches(source.request_id)
    harness.des.run()
    assert recovery_get.state is GetOperationState.COMPLETED

    target_scheduler = harness.scheduler1
    reservation = target_scheduler.recovery_prefix_reservation(source.request_id)
    commit = target_scheduler.commit_recovery_prefix
    call_count = 0

    def fail_once_before_commit(
        recovered: Request,
        current_reservation: object,
    ) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("injected target reservation commit failure")
        assert current_reservation == reservation
        commit(recovered, reservation)

    monkeypatch.setattr(
        target_scheduler,
        "commit_recovery_prefix",
        fail_once_before_commit,
    )
    with pytest.raises(RuntimeError, match="injected target reservation commit failure"):
        coordinator.prepare_recovery(source.request_id)

    assert source.status is RequestStatus.FINISHED_ABORTED
    assert target_scheduler.waiting_request_ids == ()
    assert target_scheduler.running_request_ids == ()
    assert target_scheduler.recovery_prefix_reservation(source.request_id) == reservation
    assert target_scheduler.block_pool.num_free_blocks == 14
    assert target_scheduler.block_pool.blocks[reservation.block_ids[0]].ref_count == 1
    assert (source.request_id, 1) not in coordinator._requests
    assert (source.request_id, 1) not in coordinator._authorities
    assert (source.request_id, 1) not in coordinator._prepared_recoveries
    assert coordinator.silent_replay_plan(source.request_id).status is (SilentReplayStatus.PLANNED)

    recovered = coordinator.prepare_recovery(source.request_id)
    assert call_count == 2
    assert source.status is RequestStatus.FINISHED_ABORTED
    assert recovered.status is RequestStatus.RUNNING
    assert recovered.num_computed_tokens == 15
    assert target_scheduler.request_block_ids(source.request_id) == reservation.block_ids
    [materialization] = _materialize_recovery_prompt(harness, source.request_id)
    [last_prompt_token] = materialization.scheduled_running_reqs
    assert last_prompt_token.num_computed_tokens_before == 15
    assert last_prompt_token.num_computed_tokens_after == 16
    coordinator.activate_recovery(source.request_id)
    coordinator.finish_current_request(source.request_id)
    coordinator.audit()
    assert any(
        record.record_type == "BASELINE_RECOVERY_PREPARATION_ROLLED_BACK"
        and record.data["phase"] == "TARGET_RESERVATION_COMMIT"
        for record in harness.des.journal.records
    )


def test_prepare_recovery_is_retryable_after_source_release_and_replay_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness()
    coordinator = harness.coordinator
    block = _identity(0)
    source = Request("request-0", 16, 1, harness.des.now_ns)
    coordinator.route_and_admit(source, required_blocks=(block,))
    coordinator.run_scheduler_step(source.request_id)
    put = coordinator.start_store_put(
        source.request_id,
        block,
        put_id="retryable-after-source-release",
        payload_bytes=64,
        preferred_segment_ids=("shared-store-0",),
    )
    harness.des.run()
    assert put.state is PutOperationState.COMMITTED
    coordinator.schedule_gpu_failure(
        failure_id="replay-start-prepare-failure",
        gpu_id="gpu-0",
        at_ns=harness.des.now_ns,
    )
    harness.des.run()
    [recovery_get] = coordinator.start_recovery_fetches(source.request_id)
    harness.des.run()
    assert recovery_get.state is GetOperationState.COMPLETED

    controller = coordinator.failure_controller
    start_replay = controller.start_silent_replay
    call_count = 0

    def fail_once_after_replay_start(
        request_id: str,
        route_version: int,
    ) -> SilentReplayPlan:
        nonlocal call_count
        call_count += 1
        started = start_replay(request_id, route_version)
        if call_count == 1:
            raise RuntimeError("injected post-replay-start failure")
        return started

    monkeypatch.setattr(
        controller,
        "start_silent_replay",
        fail_once_after_replay_start,
    )
    with pytest.raises(RuntimeError, match="injected post-replay-start failure"):
        coordinator.prepare_recovery(source.request_id)

    key = (source.request_id, 1)
    reservation = harness.scheduler1.recovery_prefix_reservation(source.request_id)
    assert source.status is RequestStatus.RUNNING
    assert harness.scheduler1.waiting_request_ids == ()
    assert harness.scheduler1.running_request_ids == ()
    assert harness.scheduler1.block_pool.num_free_blocks == 14
    assert harness.scheduler1.block_pool.blocks[reservation.block_ids[0]].ref_count == 1
    assert key not in coordinator._requests
    assert key not in coordinator._authorities
    assert key not in coordinator._prepared_recoveries
    assert coordinator.silent_replay_plan(source.request_id).status is (SilentReplayStatus.PLANNED)

    recovered = coordinator.prepare_recovery(source.request_id)
    assert call_count == 2
    assert source.status is RequestStatus.FINISHED_ABORTED
    assert recovered.status is RequestStatus.RUNNING
    assert recovered.num_computed_tokens == 15
    _materialize_recovery_prompt(harness, source.request_id)
    coordinator.activate_recovery(source.request_id)
    coordinator.finish_current_request(source.request_id)
    coordinator.audit()
    assert any(
        record.record_type == "BASELINE_RECOVERY_PREPARATION_ROLLED_BACK"
        and record.data["phase"] == "SILENT_REPLAY_START"
        and record.data["old_request_preserved"] is True
        and record.data["silent_replay_rollback_error_type"] is None
        for record in harness.des.journal.records
    )
    assert any(
        record.record_type == "BASELINE_SILENT_REPLAY_START_ROLLED_BACK"
        for record in harness.des.journal.records
    )


def test_recovery_capacity_failure_precedes_store_get_and_retry_reuses_no_state() -> None:
    harness = _harness()
    coordinator = harness.coordinator
    block = _identity(0)
    source = Request("request-0", 16, 1, harness.des.now_ns)
    coordinator.route_and_admit(source, required_blocks=(block,))
    coordinator.run_scheduler_step(source.request_id)
    put = coordinator.start_store_put(
        source.request_id,
        block,
        put_id="capacity-prefix",
        payload_bytes=64,
        preferred_segment_ids=("shared-store-0",),
    )
    harness.des.run()
    assert put.state is PutOperationState.COMMITTED
    coordinator.schedule_gpu_failure(
        failure_id="capacity-source-failure",
        gpu_id="gpu-0",
        at_ns=harness.des.now_ns,
    )
    harness.des.run()

    target_scheduler = harness.scheduler1
    capacity_owner = Request("capacity-owner", 240, 1, harness.des.now_ns)
    target_scheduler.add_request(capacity_owner)
    while capacity_owner.num_computed_tokens < capacity_owner.prompt_tokens:
        assert target_scheduler.schedule().scheduled_req_ids == (capacity_owner.request_id,)
    assert target_scheduler.block_pool.num_free_blocks == 0
    get_record_count = sum(
        record.record_type == "STORE_CLIENT_GET_STARTED" for record in harness.des.journal.records
    )

    with pytest.raises(ValueError, match="insufficient scheduler/HBM capacity"):
        coordinator.start_recovery_fetches(source.request_id)

    assert (
        sum(
            record.record_type == "STORE_CLIENT_GET_STARTED"
            for record in harness.des.journal.records
        )
        == get_record_count
    )
    assert (source.request_id, 1) not in coordinator._recovery_gets
    assert (source.request_id, 1) not in coordinator._recovery_reservations
    with pytest.raises(KeyError, match="no recovery prefix reservation"):
        target_scheduler.recovery_prefix_reservation(source.request_id)

    target_scheduler.finish_request(
        capacity_owner.request_id,
        RequestStatus.FINISHED_STOPPED,
    )
    rejected_tasks: list[TransferTask] = []

    def reject_transfer_plan(task: TransferTask) -> TransferTaskResourcePlan:
        rejected_tasks.append(task)
        raise RuntimeError("injected recovery transfer preflight failure")

    with pytest.raises(RuntimeError, match="injected recovery transfer preflight failure"):
        coordinator.start_recovery_fetches(
            source.request_id,
            resource_plan_provider=reject_transfer_plan,
        )
    [rejected_task] = rejected_tasks
    [rejected_destination_id] = rejected_task.metadata.destination_allocation_ids
    assert rejected_task.status is TransferStatus.CANCELED
    assert harness.master.allocation_registry.get(rejected_destination_id).state is (
        AllocationState.RELEASED
    )
    assert target_scheduler.block_pool.num_free_blocks == 15
    assert (source.request_id, 1) not in coordinator._recovery_gets
    assert (source.request_id, 1) not in coordinator._recovery_reservations

    [recovery_get] = coordinator.start_recovery_fetches(source.request_id)
    assert ":attempt-0002:" in recovery_get.get_id
    assert recovery_get.destination_allocation_ids != (rejected_destination_id,)
    harness.des.run()
    assert recovery_get.state is GetOperationState.COMPLETED
    coordinator.prepare_recovery(source.request_id)
    _materialize_recovery_prompt(harness, source.request_id)
    coordinator.activate_recovery(source.request_id)
    coordinator.finish_current_request(source.request_id)
    coordinator.audit()


def test_target_gpu_failure_aborts_bound_recovery_destination_and_next_route_retries() -> None:
    harness = _harness(replica_count=3)
    coordinator = harness.coordinator
    block = _identity(0)
    source = Request("request-0", 16, 1, harness.des.now_ns)
    coordinator.route_and_admit(source, required_blocks=(block,))
    coordinator.run_scheduler_step(source.request_id)
    put = coordinator.start_store_put(
        source.request_id,
        block,
        put_id="target-failure-prefix",
        payload_bytes=64,
        preferred_segment_ids=("shared-store-0",),
    )
    harness.des.run()
    assert put.state is PutOperationState.COMMITTED
    coordinator.schedule_gpu_failure(
        failure_id="initial-source-failure",
        gpu_id="gpu-0",
        at_ns=harness.des.now_ns,
    )
    harness.des.run()
    assert coordinator.router.current_authority(source.request_id).target_replica_id == "dp-1"

    [failed_get] = coordinator.start_recovery_fetches(source.request_id)
    failed_reservation = harness.scheduler1.recovery_prefix_reservation(source.request_id)
    failed_destination_id = failed_reservation.destination_allocation_ids[0][0]
    assert failed_get.destination_allocation_ids == (failed_destination_id,)
    assert harness.master.allocation_registry.get(failed_destination_id).state is (
        AllocationState.RESERVED
    )
    coordinator.schedule_gpu_failure(
        failure_id="recovery-target-failure",
        gpu_id="gpu-1",
        at_ns=harness.des.now_ns,
    )
    harness.des.run()

    assert failed_get.state is GetOperationState.FAILED
    assert coordinator.router.current_authority(source.request_id).route_version == 2
    assert coordinator.router.current_authority(source.request_id).target_replica_id == "dp-2"
    assert harness.scheduler1.block_pool.num_free_blocks == 15
    with pytest.raises(KeyError, match="no recovery prefix reservation"):
        harness.scheduler1.recovery_prefix_reservation(source.request_id)
    assert harness.master.allocation_registry.get(failed_destination_id).state is (
        AllocationState.LOST
    )
    assert harness.hbm_ledgers is not None
    assert harness.hbm_ledgers["gpu-1.hbm"].bytes_in(HBM_RECOVERY_RESERVED_ACCOUNT) == 0

    [retry_get] = coordinator.start_recovery_fetches(source.request_id)
    harness.des.run()
    assert retry_get.state is GetOperationState.COMPLETED
    coordinator.prepare_recovery(source.request_id)
    _materialize_recovery_prompt(harness, source.request_id)
    coordinator.activate_recovery(source.request_id)
    coordinator.finish_current_request(source.request_id)
    coordinator.audit()


def _run_once() -> tuple[bytes, dict[str, object]]:
    harness = _harness()
    des = harness.des
    coordinator = harness.coordinator
    blocks = (_identity(0), _identity(1))
    request = Request(
        request_id="request-0",
        prompt_tokens=32,
        max_output_tokens=1,
        arrival_ns=des.now_ns,
    )

    initial = coordinator.route_and_admit(request, required_blocks=blocks)
    assert initial.target_replica_id == "dp-0"
    first_step = coordinator.run_scheduler_step(request.request_id)
    assert first_step.num_scheduled_tokens == {"request-0": 32}
    assert harness.scheduler0 is not harness.scheduler1
    assert harness.scheduler0.request_block_ids("request-0") == (1, 2)
    assert harness.scheduler1.running_request_ids == ()

    put = coordinator.start_store_put(
        request.request_id,
        blocks[0],
        put_id="put-prefix-block-0",
        payload_bytes=100,
        preferred_segment_ids=("shared-store-0",),
    )
    assert put.state is PutOperationState.PENDING
    assert coordinator.query_store(replica_id="dp-1", identity=blocks[0]) == ()
    des.run()
    assert put.state is PutOperationState.COMMITTED
    assert len(coordinator.query_store(replica_id="dp-1", identity=blocks[0])) == 1

    failure_at = des.now_ns + 10
    coordinator.schedule_forward_completion(
        request.request_id,
        at_ns=failure_at,
        output_index=0,
    )
    coordinator.schedule_gpu_failure(
        failure_id="failure-gpu-0",
        gpu_id="gpu-0",
        at_ns=failure_at,
        detection_delay_ns=0,
    )
    des.run()

    current = coordinator.router.current_authority(request.request_id)
    assert current.route_version == 1
    assert current.target_replica_id == "dp-1"
    assert not coordinator.router.is_authoritative(initial)
    assert coordinator.failure_controller.emitted_outputs == ()
    assert not coordinator.failure_controller.try_emit_output(
        request_id=request.request_id,
        route_version=0,
        output_index=0,
    )
    failure_records = [
        record
        for record in des.journal.records
        if record.record_type
        in {
            "BASELINE_GPU_FAIL_STOPPED",
            "BASELINE_ROUTE_FENCED",
            "BASELINE_GPU_FAILURE_DETECTED",
            "BASELINE_REROUTED",
        }
    ]
    assert {record.timestamp_ns for record in failure_records} == {failure_at}
    plan = coordinator.recovery_plan(request.request_id)
    assert [block.identity.object_id for block in plan.store_prefix] == [blocks[0].object_id]
    assert plan.restored_tokens == 16
    assert plan.recompute_tokens == 16
    assert plan.missing_suffix_start_block == 1

    [recovery_get] = coordinator.start_recovery_fetches(request.request_id)
    assert recovery_get.state is GetOperationState.PENDING
    [planned_block] = plan.store_prefix
    [recovery_task] = recovery_get.batch.tasks
    reservation = harness.scheduler1.recovery_prefix_reservation(request.request_id)
    [destination_ids] = reservation.destination_allocation_ids
    assert recovery_get.replica.replica_id == planned_block.replica_id
    assert recovery_get.replica.allocation_ids == planned_block.allocation_ids
    assert recovery_task.metadata.source.resource_id == planned_block.resource_ids[0]
    assert recovery_get.destination_allocation_ids == destination_ids
    assert recovery_task.metadata.destination_allocation_ids == destination_ids
    assert harness.master.allocation_registry.get(destination_ids[0]).state is (
        AllocationState.RESERVED
    )
    assert harness.scheduler1.block_pool.num_free_blocks == 14
    assert harness.hbm_ledgers is not None
    assert harness.hbm_ledgers["gpu-1.hbm"].bytes_in(HBM_RECOVERY_RESERVED_ACCOUNT) == 128
    des.run()
    assert recovery_get.state is GetOperationState.COMPLETED
    recovered = coordinator.prepare_recovery(request.request_id)
    assert recovered.route_version == 1
    assert recovered.status is RequestStatus.RUNNING
    assert recovered.num_computed_tokens == 16
    assert harness.scheduler0.request_block_ids("request-0") == ()
    assert harness.scheduler1.request_block_ids("request-0") == reservation.block_ids
    assert harness.hbm_ledgers["gpu-1.hbm"].bytes_in(HBM_RECOVERY_RESERVED_ACCOUNT) == 0
    with pytest.raises(BaselineCoordinatorError, match="prompt materialization"):
        coordinator.activate_recovery(request.request_id)
    [second_step] = _materialize_recovery_prompt(harness, request.request_id)
    [suffix] = second_step.scheduled_running_reqs
    assert suffix.num_computed_tokens_before == 16
    assert suffix.num_computed_tokens_after == 32
    assert suffix.num_scheduled_tokens == plan.recompute_tokens
    assert coordinator.failure_controller.emitted_outputs == ()
    coordinator.activate_recovery(request.request_id)
    assert [output.route_version for output in coordinator.failure_controller.emitted_outputs] == [
        1
    ]
    coordinator.finish_current_request(request.request_id)
    coordinator.audit()

    audit = generate_capacity_audit(
        initial_ledgers=harness.initial_ledgers,
        journal=des.journal,
        online_final_ledgers=coordinator.allocation_ledgers,
    )
    assert audit.valid and audit.final_snapshot_byte_identical
    assert harness.master.ledgers["shared-store-0"].bytes_in(STORE_COMMITTED_ACCOUNT) == 128
    flow_bytes = sum(
        interval.transferred_bytes
        for interval in coordinator.transfer_runtime.controller.model.intervals
    )
    assert flow_bytes == pytest.approx(200.0)
    summary = {
        "initial_target": initial.target_replica_id,
        "rerouted_target": current.target_replica_id,
        "restored_tokens": plan.restored_tokens,
        "recompute_tokens": plan.recompute_tokens,
        "flow_bytes": flow_bytes,
        "capacity_audit": audit.status,
    }
    return des.journal.to_jsonl_bytes(), summary


def test_composed_two_dp_store_failure_recovery_is_byte_deterministic() -> None:
    first_journal, first_summary = _run_once()
    second_journal, second_summary = _run_once()

    assert first_summary == second_summary
    assert first_journal == second_journal
    assert EVIDENCE_BOUNDARY.encode() in first_journal
    assert b"BASELINE_GPU_OPERATION_CANCELED" in first_journal
    assert b"BASELINE_OUTPUT_FENCED" in first_journal
    assert b"STORE_CLIENT_PUT_COMMITTED" in first_journal
    assert b"STORE_CLIENT_GET_COMPLETED" in first_journal


def test_forward_batch_completion_atomically_fences_all_outputs() -> None:
    harness = _harness()
    coordinator = harness.coordinator
    requests = (
        Request("request-0", 16, 1, harness.des.now_ns),
        Request("spacer-on-dp-1", 16, 1, harness.des.now_ns),
        Request("request-2", 16, 1, harness.des.now_ns),
    )
    authorities = tuple(
        coordinator.route_and_admit(request, required_blocks=()) for request in requests
    )
    assert tuple(item.target_replica_id for item in authorities) == (
        "dp-0",
        "dp-1",
        "dp-0",
    )
    scheduled = coordinator.run_scheduler_step("request-0")
    assert scheduled.scheduled_req_ids == ("request-0", "request-2")
    scheduler_record = next(
        record
        for record in harness.des.journal.records
        if record.record_type == "BASELINE_SCHEDULER_STEP"
    )
    scheduler_data = scheduler_record.data
    assert "scheduled" not in scheduler_data
    assert scheduler_data["scheduler_output_sha256"] == sha256_json(scheduled.to_dict())
    assert scheduler_data["scheduler_source_sha256"] == scheduled.source_sha256
    assert [
        participant["request_id"] for participant in scheduler_data["scheduled_requests"]
    ] == list(scheduled.scheduled_req_ids)
    for participant, item in zip(
        scheduler_data["scheduled_requests"],
        (*scheduled.scheduled_new_reqs,),
        strict=True,
    ):
        assert participant["block_count"] == len(item.block_ids)
        assert participant["block_ids_sha256"] == sha256_json(item.block_ids)
        assert participant["new_block_count"] == len(item.new_block_ids)
        assert participant["new_block_ids_sha256"] == sha256_json(item.new_block_ids)
    assert len(canonical_json_bytes(scheduler_data)) < 2_000
    terminals: list[ForwardBatchTerminal] = []
    coordinator.schedule_forward_batch_completion(
        ("request-0", "request-2"),
        at_ns=harness.des.now_ns + 10,
        produces_outputs={"request-0": True, "request-2": True},
        output_indices={"request-0": 0, "request-2": 0},
        terminal_callback=lambda terminal, _clock: terminals.append(terminal),
    )

    coordinator.finish_current_request(
        "request-2",
        status=RequestStatus.FINISHED_ABORTED,
    )
    harness.des.run()

    [terminal] = terminals
    assert not terminal.accepted
    assert terminal.fence_reason == "FINISHED_REQUEST:request-2@0"
    assert coordinator.failure_controller.emitted_outputs == ()
    assert not any(
        record.record_type == "BASELINE_OUTPUT_ACTIVATED" for record in harness.des.journal.records
    )
    assert any(
        record.record_type == "BASELINE_FORWARD_BATCH_FENCED"
        for record in harness.des.journal.records
    )
    coordinator.finish_current_request("request-0")
    coordinator.finish_current_request("spacer-on-dp-1")
    coordinator.audit()


def test_compact_scheduler_record_size_is_independent_of_block_id_array_length() -> None:
    block_ids = tuple(range(1, 10_001))
    scheduled = ScheduledRequest(
        request_id="large-scheduler-record",
        origin=SchedulingOrigin.NEW,
        phase=SchedulingPhase.PREFILL,
        num_scheduled_tokens=len(block_ids) * 16,
        num_computed_tokens_before=0,
        num_computed_tokens_after=len(block_ids) * 16,
        new_block_ids=block_ids,
        block_ids=block_ids,
        recompute=False,
        chunked=False,
    )
    output = SchedulerOutput(
        scheduled_new_reqs=(scheduled,),
        scheduled_resumed_reqs=(),
        scheduled_running_reqs=(),
        num_scheduled_tokens={scheduled.request_id: scheduled.num_scheduled_tokens},
        total_num_scheduled_tokens=scheduled.num_scheduled_tokens,
        token_budget_remaining=0,
        preempted_req_ids=(),
    )

    compact = _compact_scheduler_output(output)

    [participant] = compact["scheduled_requests"]
    assert participant["block_count"] == len(block_ids)
    assert participant["block_ids_sha256"] == sha256_json(block_ids)
    assert participant["new_block_count"] == len(block_ids)
    assert participant["new_block_ids_sha256"] == sha256_json(block_ids)
    assert compact["scheduler_output_sha256"] == sha256_json(output.to_dict())
    assert len(canonical_json_bytes(compact)) < 1_500
    assert len(canonical_json_bytes(compact)) * 50 < len(canonical_json_bytes(output.to_dict()))


def test_committed_output_is_silently_replayed_without_duplicate_delivery() -> None:
    harness = _harness()
    coordinator = harness.coordinator
    blocks = (_identity(0), _identity(1))
    request = Request("request-0", 32, 3, harness.des.now_ns)
    authority = coordinator.route_and_admit(request, required_blocks=blocks)
    coordinator.run_scheduler_step(request.request_id)
    put = coordinator.start_store_put(
        request.request_id,
        blocks[0],
        put_id="committed-prefix-before-output-failure",
        payload_bytes=100,
        preferred_segment_ids=("shared-store-0",),
    )
    harness.des.run()
    assert put.state is PutOperationState.COMMITTED

    coordinator.schedule_forward_completion(
        request.request_id,
        at_ns=harness.des.now_ns + 1,
        output_index=0,
        terminal_callback=(
            lambda _event, _clock: harness.scheduler0.append_output_tokens(request.request_id)
        ),
    )
    harness.des.run()
    assert request.num_output_tokens == 1
    assert [item.output_index for item in coordinator.failure_controller.emitted_outputs] == [0]

    coordinator.schedule_gpu_failure(
        failure_id="failure-after-output",
        gpu_id="gpu-0",
        at_ns=harness.des.now_ns,
    )
    harness.des.run()
    assert authority.target_replica_id == "dp-0"
    assert coordinator.router.current_authority(request.request_id).target_replica_id == "dp-1"
    [recovery_get] = coordinator.start_recovery_fetches(request.request_id)
    harness.des.run()
    assert recovery_get.state is GetOperationState.COMPLETED

    recovered = coordinator.prepare_recovery(request.request_id)
    plan = coordinator.silent_replay_plan(request.request_id)
    assert plan.committed_next_output_index == 1
    assert plan.replayed_output_count == 0
    assert recovered.num_output_tokens == 0
    assert recovered.num_computed_tokens == 16
    assert not coordinator.failure_controller.try_emit_output(
        request_id=request.request_id,
        route_version=1,
        output_index=1,
    )
    with pytest.raises(BaselineCoordinatorError, match="silent replay must reach"):
        coordinator.activate_recovery(request.request_id)

    replay_step = coordinator.run_silent_replay_scheduler_step(request.request_id)
    [recomputed_suffix] = replay_step.scheduled_running_reqs
    assert recomputed_suffix.num_computed_tokens_before == 16
    assert recomputed_suffix.num_computed_tokens_after == 32
    coordinator.schedule_silent_replay_completion(
        request.request_id,
        at_ns=harness.des.now_ns + 1,
    )
    harness.des.run()
    assert recovered.num_output_tokens == 1
    assert coordinator.silent_replay_plan(request.request_id).replayed_output_count == 1
    assert [item.output_index for item in coordinator.failure_controller.emitted_outputs] == [0]

    coordinator.activate_recovery(request.request_id)
    assert not coordinator.failure_controller.try_emit_output(
        request_id=request.request_id,
        route_version=1,
        output_index=0,
    )
    decode = coordinator.run_scheduler_step(request.request_id)
    [decode_item] = decode.scheduled_running_reqs
    assert decode_item.num_computed_tokens_before == 32
    assert decode_item.num_computed_tokens_after == 33
    coordinator.schedule_forward_completion(
        request.request_id,
        at_ns=harness.des.now_ns + 1,
        output_index=1,
        terminal_callback=(
            lambda _event, _clock: harness.scheduler1.append_output_tokens(request.request_id)
        ),
    )
    harness.des.run()

    assert [
        (item.route_version, item.output_index)
        for item in coordinator.failure_controller.emitted_outputs
    ] == [(0, 0), (1, 1)]
    assert (
        sum(
            record.record_type == "BASELINE_SILENT_REPLAY_OUTPUT_COMPUTED"
            for record in harness.des.journal.records
        )
        == 1
    )
    assert not any(
        record.record_type == "BASELINE_OUTPUT_ACTIVATED"
        and record.data["route_version"] == 1
        and record.data["output_index"] == 0
        for record in harness.des.journal.records
    )

    coordinator.finish_current_request(request.request_id)
    coordinator.audit()


def test_pre_mid_post_replay_failures_release_refcounts_without_resurrecting_hbm() -> None:
    harness = _harness(replica_count=4)
    coordinator = harness.coordinator
    request = Request("request-0", 16, 3, harness.des.now_ns)
    coordinator.route_and_admit(request, required_blocks=())
    coordinator.run_scheduler_step(request.request_id)

    for output_index in range(2):
        if output_index:
            coordinator.run_scheduler_step(request.request_id)
        scheduler = harness.schedulers[0]
        coordinator.schedule_forward_completion(
            request.request_id,
            at_ns=harness.des.now_ns + 1,
            output_index=output_index,
            terminal_callback=(
                lambda _event, _clock, scheduler=scheduler: scheduler.append_output_tokens(
                    request.request_id
                )
            ),
        )
        harness.des.run()
    assert request.num_output_tokens == 2
    assert [item.output_index for item in coordinator.failure_controller.emitted_outputs] == [
        0,
        1,
    ]

    # The first recovery target fails before any replay scheduler step.
    coordinator.schedule_gpu_failure(
        failure_id="source-failure",
        gpu_id="gpu-0",
        at_ns=harness.des.now_ns + 1,
    )
    harness.des.run()
    assert coordinator.start_recovery_fetches(request.request_id) == ()
    route1 = coordinator.prepare_recovery(request.request_id)
    assert route1.route_version == 1
    coordinator.schedule_gpu_failure(
        failure_id="pre-replay-failure",
        gpu_id="gpu-1",
        at_ns=harness.des.now_ns + 1,
    )
    harness.des.run()
    assert (
        coordinator.failure_controller.silent_replay_plan(
            request.request_id,
            1,
        ).status
        is SilentReplayStatus.FENCED
    )

    # Preparing route 2 aborts the fenced route-1 scheduler state.  Route 2
    # then fails while its first replay forward is physically in flight.
    assert coordinator.start_recovery_fetches(request.request_id) == ()
    route2 = coordinator.prepare_recovery(request.request_id)
    assert route2.route_version == 2
    assert harness.schedulers[1].running_request_ids == ()
    assert harness.schedulers[1].waiting_request_ids == ()
    coordinator.run_silent_replay_scheduler_step(request.request_id)
    coordinator.schedule_silent_replay_completion(
        request.request_id,
        at_ns=harness.des.now_ns + 10,
    )
    coordinator.schedule_gpu_failure(
        failure_id="mid-replay-failure",
        gpu_id="gpu-2",
        at_ns=harness.des.now_ns + 5,
    )
    harness.des.run()
    assert (
        coordinator.failure_controller.silent_replay_plan(
            request.request_id,
            2,
        ).status
        is SilentReplayStatus.FENCED
    )
    assert any(
        record.record_type == "BASELINE_SILENT_REPLAY_FORWARD_CANCELED"
        for record in harness.des.journal.records
    )

    # Route 3 preparation releases all lost logical blocks from route 2.  It
    # reaches READY_TO_ACTIVATE, then fails before output activation.
    assert coordinator.start_recovery_fetches(request.request_id) == ()
    route3 = coordinator.prepare_recovery(request.request_id)
    assert route3.route_version == 3
    for old_scheduler in harness.schedulers[:3]:
        assert old_scheduler.running_request_ids == ()
        assert old_scheduler.waiting_request_ids == ()
        assert old_scheduler.block_pool.num_free_blocks == 15
        assert all(block.ref_count == 0 for block in old_scheduler.block_pool.blocks[1:])

    for _ in range(2):
        coordinator.run_silent_replay_scheduler_step(request.request_id)
        coordinator.schedule_silent_replay_completion(
            request.request_id,
            at_ns=harness.des.now_ns + 1,
        )
        harness.des.run()
    assert coordinator.silent_replay_plan(request.request_id).status is (
        SilentReplayStatus.READY_TO_ACTIVATE
    )
    assert [item.output_index for item in coordinator.failure_controller.emitted_outputs] == [
        0,
        1,
    ]

    coordinator.schedule_gpu_failure(
        failure_id="post-replay-pre-activation-failure",
        gpu_id="gpu-3",
        at_ns=harness.des.now_ns + 1,
    )
    harness.des.run()
    assert (
        coordinator.failure_controller.attempt(
            request.request_id,
            3,
        ).status
        is AttemptStatus.RECOVERY_FAILED_NO_TARGET
    )
    assert route3.status is RequestStatus.FINISHED_ERROR
    assert harness.schedulers[3].running_request_ids == ()
    assert harness.schedulers[3].waiting_request_ids == ()
    assert harness.schedulers[3].block_pool.num_free_blocks == 15
    assert all(block.ref_count == 0 for block in harness.schedulers[3].block_pool.blocks[1:])

    assert harness.hbm_ledgers is not None
    assert all(
        ledger.bytes_in("UNAVAILABLE_CAPACITY") == ledger.capacity_bytes
        for ledger in harness.hbm_ledgers.values()
    )
    coordinator.audit()
    audit = generate_capacity_audit(
        initial_ledgers=harness.initial_ledgers,
        journal=harness.des.journal,
        online_final_ledgers=coordinator.allocation_ledgers,
    )
    assert audit.valid and audit.final_snapshot_byte_identical


def test_unmodeled_concurrency_path_fails_closed_and_releases_pending_store_bytes() -> None:
    harness = _harness(concurrency_resource_ids=("unmodeled-copy-lane",))
    block = _identity(0)
    harness.coordinator.route_and_admit(
        Request("request-0", 16, 1, harness.des.now_ns),
        required_blocks=(block,),
    )
    harness.coordinator.run_scheduler_step("request-0")

    with pytest.raises(BaselineCoordinatorError, match="concurrency resources"):
        harness.coordinator.start_store_put(
            "request-0",
            block,
            put_id="must-abort",
            payload_bytes=64,
            preferred_segment_ids=("shared-store-0",),
        )

    assert harness.master.ledgers["shared-store-0"].bytes_in("PENDING_REPLICA") == 0
    assert harness.master.segments["shared-store-0"].used_bytes == 0
    assert harness.coordinator.query_store(replica_id="dp-1", identity=block) == ()
    harness.master.allocation_registry.audit(harness.coordinator.allocation_ledgers)


def test_new_request_cannot_route_to_a_failed_less_loaded_dp() -> None:
    harness = _harness()
    coordinator = harness.coordinator
    coordinator.route_and_admit(
        Request("request-0", 16, 1, harness.des.now_ns),
        required_blocks=(),
    )
    coordinator.schedule_gpu_failure(
        failure_id="failure-gpu-0",
        gpu_id="gpu-0",
        at_ns=harness.des.now_ns,
    )
    harness.des.run()

    # Make the healthy DP look busier.  Health must dominate load in the
    # external router snapshot; otherwise route() would mutate authority to the
    # failed DP before the recovery controller rejected it.
    for index in range(3):
        harness.scheduler1.add_request(Request(f"background-{index}", 16, 1, harness.des.now_ns))
    authority = coordinator.route_and_admit(
        Request("request-after-failure", 16, 1, harness.des.now_ns),
        required_blocks=(),
    )
    assert authority.target_replica_id == "dp-1"


def test_tcp_staging_and_queued_lane_compose_with_dp_store_put_get_and_replay() -> None:
    host_resource_id = "node.host-staging"
    lane_resource_id = "endpoint.tcp-lane"
    harness = _harness(
        concurrency_resource_ids=(lane_resource_id,),
        transport=TransportKind.TCP_HOST_STAGED,
        host_staging_resource_id=host_resource_id,
        configure_transfer_resources=True,
    )
    manager = harness.transfer_resource_manager
    host = harness.host_staging_ledger
    calendars = harness.concurrency_resources
    assert manager is not None and host is not None and calendars is not None

    blocks = (_identity(0), _identity(1))
    harness.coordinator.route_and_admit(
        Request("request-0", 32, 1, harness.des.now_ns),
        required_blocks=blocks,
    )
    harness.coordinator.run_scheduler_step("request-0")
    first = harness.coordinator.start_store_put(
        "request-0",
        blocks[0],
        put_id="staged-put-0",
        payload_bytes=64,
        preferred_segment_ids=("shared-store-0",),
        resource_plan=_single_staging_plan(
            allocation_id="staging:put-0",
            resource_id=host_resource_id,
            payload_bytes=64,
            duration_ns=200,
            latest_start_ns=0,
        ),
    )
    second = harness.coordinator.start_store_put(
        "request-0",
        blocks[1],
        put_id="staged-put-1",
        payload_bytes=64,
        preferred_segment_ids=("shared-store-0",),
        resource_plan=_single_staging_plan(
            allocation_id="staging:put-1",
            resource_id=host_resource_id,
            payload_bytes=64,
            duration_ns=200,
            latest_start_ns=200,
        ),
    )
    first_transfer_id = first.batch.tasks[0].metadata.transfer_id
    second_transfer_id = second.batch.tasks[0].metadata.transfer_id
    first_lease = manager.lease(f"baseline-transfer-lease:{first_transfer_id}")
    second_lease = manager.lease(f"baseline-transfer-lease:{second_transfer_id}")
    assert (first_lease.start_ns, first_lease.end_ns) == (0, 200)
    assert (second_lease.start_ns, second_lease.end_ns) == (200, 400)
    assert first.batch.tasks[0].status is second.batch.tasks[0].status
    assert first.batch.tasks[0].status.value == "WAITING"

    harness.des.run()

    assert first.state is second.state is PutOperationState.COMMITTED
    assert first.batch.tasks[0].start_ns == 0
    assert second.batch.tasks[0].start_ns == 200
    assert host.bytes_in("FREE") == host.capacity_bytes
    assert calendars[lane_resource_id].reservations() == ()

    harness.coordinator.schedule_gpu_failure(
        failure_id="reroute-after-staged-puts",
        gpu_id="gpu-0",
        at_ns=harness.des.now_ns + 1,
    )
    harness.des.run()
    assert harness.coordinator.router.current_authority("request-0").target_replica_id == "dp-1"

    recovery_gets = harness.coordinator.start_recovery_fetches(
        "request-0",
        resource_plan_provider=lambda task: _resource_plan(
            task,
            duration_ns=200,
            latest_start_ns=harness.des.now_ns + 200,
        ),
    )
    assert len(recovery_gets) == 2
    harness.des.run()
    assert all(item.state is GetOperationState.COMPLETED for item in recovery_gets)
    harness.coordinator.prepare_recovery("request-0")
    _materialize_recovery_prompt(harness, "request-0")
    harness.coordinator.activate_recovery("request-0")
    harness.coordinator.finish_current_request("request-0")
    harness.coordinator.audit()

    replayed_store = CapacityLedger(
        resource_id="shared-store-0",
        resource_kind=CapacityResourceKind.STORE_DRAM,
        capacity_bytes=4096,
    )
    replayed_host = CapacityLedger(
        resource_id=host_resource_id,
        resource_kind=CapacityResourceKind.HOST_DRAM,
        capacity_bytes=host.capacity_bytes,
    )
    assert harness.hbm_ledgers is not None
    replayed_hbm = {
        resource_id: CapacityLedger(
            resource_id=resource_id,
            resource_kind=CapacityResourceKind.GPU_HBM,
            capacity_bytes=ledger.capacity_bytes,
        )
        for resource_id, ledger in harness.hbm_ledgers.items()
    }
    replay_capacity_transactions(
        harness.des.journal,
        {
            replayed_store.resource_id: replayed_store,
            replayed_host.resource_id: replayed_host,
            **replayed_hbm,
        },
    )
    assert replayed_store.accounts == harness.master.ledgers["shared-store-0"].accounts
    assert replayed_host.accounts == host.accounts
    assert all(
        replayed_hbm[resource_id].accounts == ledger.accounts
        for resource_id, ledger in harness.hbm_ledgers.items()
    )

    replayed_calendars = {
        lane_resource_id: ConcurrencyResource(resource_id=lane_resource_id, lanes=1)
    }
    replayed_state = replay_transfer_resource_calendar(
        harness.des.journal,
        replayed_calendars,
    )
    assert replayed_state.active_lease_ids == ()
    assert len(replayed_state.released_lease_ids) == 4
    assert replayed_calendars[lane_resource_id].reservations() == ()
    records = harness.des.journal.records
    assert sum(record.record_type == "STORE_CLIENT_TRANSFER_RECONCILED" for record in records) == 4
    assert sum(record.record_type == "TRANSFER_RESOURCE_LEASE_RELEASED" for record in records) == 4


def test_gpu_failure_aborts_active_staged_put_and_releases_resources_once() -> None:
    host_resource_id = "node.host-staging"
    lane_resource_id = "endpoint.tcp-lane"
    harness = _harness(
        concurrency_resource_ids=(lane_resource_id,),
        transport=TransportKind.TCP_HOST_STAGED,
        host_staging_resource_id=host_resource_id,
        configure_transfer_resources=True,
    )
    manager = harness.transfer_resource_manager
    host = harness.host_staging_ledger
    calendars = harness.concurrency_resources
    assert manager is not None and host is not None and calendars is not None
    block = _identity(0)
    harness.coordinator.route_and_admit(
        Request("request-0", 16, 1, harness.des.now_ns),
        required_blocks=(block,),
    )
    operation = harness.coordinator.start_store_put(
        "request-0",
        block,
        put_id="failure-staged-put",
        payload_bytes=100,
        preferred_segment_ids=("shared-store-0",),
        resource_plan=_single_staging_plan(
            allocation_id="staging:failure-put",
            resource_id=host_resource_id,
            payload_bytes=100,
            duration_ns=500,
        ),
    )
    task = operation.batch.tasks[0]
    lease_id = f"baseline-transfer-lease:{task.metadata.transfer_id}"
    harness.coordinator.schedule_gpu_failure(
        failure_id="failure-during-staged-put",
        gpu_id="gpu-0",
        at_ns=50,
    )

    harness.des.run()

    released = manager.lease(lease_id)
    assert task.status.value == "CANCELED"
    assert operation.state is PutOperationState.ABORTED
    assert released.status is TransferLeaseStatus.RELEASED
    assert released.outcome is TransferLeaseOutcome.GPU_FAILURE
    assert released.release_reason == "GPU_FAILURE:failure-during-staged-put"
    assert host.bytes_in("FREE") == host.capacity_bytes
    assert calendars[lane_resource_id].reservations() == ()
    records = harness.des.journal.records
    assert (
        sum(
            record.record_type == "TRANSFER_RESOURCE_LEASE_RELEASED"
            and record.data["lease_id"] == lease_id
            for record in records
        )
        == 1
    )
    assert (
        sum(
            record.record_type == "STORE_CLIENT_TRANSFER_RECONCILED"
            and record.data["transfer_id"] == task.metadata.transfer_id
            for record in records
        )
        == 1
    )
    harness.coordinator.audit()


def test_operator_abort_releases_active_lease_and_reconciles_once() -> None:
    host_resource_id = "node.host-staging"
    lane_resource_id = "endpoint.tcp-lane"
    harness = _harness(
        concurrency_resource_ids=(lane_resource_id,),
        transport=TransportKind.TCP_HOST_STAGED,
        host_staging_resource_id=host_resource_id,
        configure_transfer_resources=True,
    )
    manager = harness.transfer_resource_manager
    assert manager is not None
    block = _identity(0)
    harness.coordinator.route_and_admit(
        Request("request-0", 16, 1, harness.des.now_ns),
        required_blocks=(block,),
    )
    operation = harness.coordinator.start_store_put(
        "request-0",
        block,
        put_id="operator-abort-put",
        payload_bytes=100,
        preferred_segment_ids=("shared-store-0",),
        resource_plan=_single_staging_plan(
            allocation_id="staging:operator-abort",
            resource_id=host_resource_id,
            payload_bytes=100,
            duration_ns=500,
        ),
    )
    task = operation.batch.tasks[0]
    lease_id = f"baseline-transfer-lease:{task.metadata.transfer_id}"
    harness.des.run(until_ns=50)
    assert task.status.value == "PENDING"

    harness.coordinator.abort_transfer(
        task.metadata.transfer_id,
        reason="OPERATOR_ABORT",
    )

    lease = manager.lease(lease_id)
    assert operation.state is PutOperationState.ABORTED
    assert lease.status is TransferLeaseStatus.RELEASED
    assert lease.outcome is TransferLeaseOutcome.ABORTED
    records = harness.des.journal.records
    assert (
        sum(
            record.record_type == "TRANSFER_RESOURCE_LEASE_RELEASED"
            and record.data["lease_id"] == lease_id
            for record in records
        )
        == 1
    )
    assert (
        sum(
            record.record_type == "STORE_CLIENT_TRANSFER_RECONCILED"
            and record.data["transfer_id"] == task.metadata.transfer_id
            for record in records
        )
        == 1
    )
    with pytest.raises(BaselineCoordinatorError, match="cannot be aborted twice"):
        harness.coordinator.abort_transfer(
            task.metadata.transfer_id,
            reason="DUPLICATE_ABORT",
        )
    harness.coordinator.audit()


def test_resource_path_without_per_task_plan_fails_before_lease_or_flow() -> None:
    host_resource_id = "node.host-staging"
    lane_resource_id = "endpoint.tcp-lane"
    harness = _harness(
        concurrency_resource_ids=(lane_resource_id,),
        transport=TransportKind.TCP_HOST_STAGED,
        host_staging_resource_id=host_resource_id,
        configure_transfer_resources=True,
    )
    manager = harness.transfer_resource_manager
    host = harness.host_staging_ledger
    calendars = harness.concurrency_resources
    assert manager is not None and host is not None and calendars is not None
    block = _identity(0)
    harness.coordinator.route_and_admit(
        Request("request-0", 16, 1, harness.des.now_ns),
        required_blocks=(block,),
    )

    with pytest.raises(BaselineCoordinatorError, match="per-task resource plan"):
        harness.coordinator.start_store_put(
            "request-0",
            block,
            put_id="missing-resource-plan",
            payload_bytes=64,
            preferred_segment_ids=("shared-store-0",),
        )

    assert manager.active_lease_ids == ()
    assert host.bytes_in("FREE") == host.capacity_bytes
    assert calendars[lane_resource_id].reservations() == ()
    assert harness.coordinator.transfer_runtime.active_flow_ids == ()
    assert harness.master.ledgers["shared-store-0"].bytes_in("PENDING_REPLICA") == 0


def test_normal_put_get_resource_plan_provider_receives_constructed_task() -> None:
    lane_resource_id = "endpoint.provider-lane"
    harness = _harness(
        concurrency_resource_ids=(lane_resource_id,),
        configure_transfer_resources=True,
    )
    manager = harness.transfer_resource_manager
    assert manager is not None
    block = _identity(0)
    harness.coordinator.route_and_admit(
        Request("request-0", 16, 1, harness.des.now_ns),
        required_blocks=(block,),
    )
    seen: list[TransferTask] = []

    def provider(task: TransferTask) -> TransferTaskResourcePlan:
        seen.append(task)
        return _resource_plan(task, duration_ns=200)

    put = harness.coordinator.start_store_put(
        "request-0",
        block,
        put_id="provider-put",
        payload_bytes=64,
        preferred_segment_ids=("shared-store-0",),
        resource_plan_provider=provider,
    )
    [put_task] = put.batch.tasks
    assert seen == [put_task]
    harness.des.run()
    assert put.state is PutOperationState.COMMITTED

    get = harness.coordinator.start_store_get(
        "request-0",
        block,
        get_id="provider-get",
        resource_plan_provider=provider,
    )
    [get_task] = get.batch.tasks
    assert seen == [put_task, get_task]
    harness.des.run()
    assert get.state is GetOperationState.COMPLETED
    assert manager.active_lease_ids == ()
    assert all(
        manager.lease(f"baseline-transfer-lease:{task.metadata.transfer_id}").transfer_id
        == task.metadata.transfer_id
        for task in seen
    )


def test_normal_resource_plan_provider_is_exclusive_and_rolls_back_on_error() -> None:
    lane_resource_id = "endpoint.provider-lane"
    harness = _harness(
        concurrency_resource_ids=(lane_resource_id,),
        configure_transfer_resources=True,
    )
    manager = harness.transfer_resource_manager
    assert manager is not None
    block = _identity(0)
    harness.coordinator.route_and_admit(
        Request("request-0", 16, 1, harness.des.now_ns),
        required_blocks=(block,),
    )
    explicit = TransferTaskResourcePlan(duration_ns=200)
    put_record_count = sum(
        record.record_type == "STORE_CLIENT_PUT_STARTED" for record in harness.des.journal.records
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        harness.coordinator.start_store_put(
            "request-0",
            block,
            put_id="exclusive-provider-put",
            payload_bytes=64,
            preferred_segment_ids=("shared-store-0",),
            resource_plan=explicit,
            resource_plan_provider=lambda task: _resource_plan(task, duration_ns=200),
        )
    assert (
        sum(
            record.record_type == "STORE_CLIENT_PUT_STARTED"
            for record in harness.des.journal.records
        )
        == put_record_count
    )

    seen: list[TransferTask] = []

    def reject(task: TransferTask) -> TransferTaskResourcePlan:
        seen.append(task)
        raise RuntimeError("provider rejected constructed task")

    with pytest.raises(RuntimeError, match="provider rejected"):
        harness.coordinator.start_store_put(
            "request-0",
            block,
            put_id="rejected-provider-put",
            payload_bytes=64,
            preferred_segment_ids=("shared-store-0",),
            resource_plan_provider=reject,
        )
    [rejected_task] = seen
    assert rejected_task.status is TransferStatus.CANCELED
    assert manager.active_lease_ids == ()
    assert harness.concurrency_resources[lane_resource_id].reservations() == ()
    assert harness.coordinator.transfer_runtime.active_flow_ids == ()
    assert harness.master.ledgers["shared-store-0"].bytes_in("PENDING_REPLICA") == 0


def test_composed_resource_duration_overrun_keeps_run_invalid() -> None:
    host_resource_id = "node.host-staging"
    lane_resource_id = "endpoint.tcp-lane"
    harness = _harness(
        concurrency_resource_ids=(lane_resource_id,),
        transport=TransportKind.TCP_HOST_STAGED,
        host_staging_resource_id=host_resource_id,
        configure_transfer_resources=True,
    )
    manager = harness.transfer_resource_manager
    assert manager is not None
    block = _identity(0)
    harness.coordinator.route_and_admit(
        Request("request-0", 16, 1, harness.des.now_ns),
        required_blocks=(block,),
    )
    operation = harness.coordinator.start_store_put(
        "request-0",
        block,
        put_id="duration-overrun",
        payload_bytes=100,
        preferred_segment_ids=("shared-store-0",),
        resource_plan=_single_staging_plan(
            allocation_id="staging:duration-overrun",
            resource_id=host_resource_id,
            payload_bytes=100,
            duration_ns=10,
        ),
    )
    task = operation.batch.tasks[0]

    with pytest.raises(TransferResourceError, match="exceeded its reserved"):
        harness.des.run()

    lease = manager.lease(f"baseline-transfer-lease:{task.metadata.transfer_id}")
    assert task.status.value == "COMPLETED"
    assert operation.state is PutOperationState.PENDING
    assert lease.status is TransferLeaseStatus.STARTED
