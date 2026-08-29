from __future__ import annotations

from dataclasses import replace

import pytest

from moonkvsim.common.status import KVLocation, ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.recovery import (
    AtomicGPUHBMFailStop,
    AttemptStatus,
    BaselineGPUFailureController,
    BaselineRecoveryPlanner,
    EngineTarget,
    GPUHealth,
    PhysicalGPU,
    RecoveryInvariantError,
    RerouteDecision,
    SilentReplayStatus,
)
from moonkvsim.simulation.allocation import AllocationState, PhysicalAllocation
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.event import EventKind
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import (
    UNAVAILABLE_CAPACITY_ACCOUNT,
    CapacityLedger,
    CapacityResourceKind,
)
from moonkvsim.simulation.replay import replay_capacity_transactions
from moonkvsim.store.metadata_store import GlobalKVDirectory
from moonkvsim.store.replica import Replica


def identity(
    index: int,
    *,
    request_id: str = "request-0",
    route_version: int = 0,
    source_gpu_id: str = "gpu-0",
) -> KVIdentity:
    token_start = index * 16
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
        stable_block_hash=f"hash-{index}",
        token_start=token_start,
        token_end=token_start + 16,
        shard_id="cache-group-0",
        request_id=request_id,
        session_id="session-0",
        workflow_id="workflow-0",
        route_version=route_version,
        source_gpu_id=source_gpu_id,
    )


def add_replica(
    directory: GlobalKVDirectory,
    registry: AllocationRegistry,
    kv: KVIdentity,
    *,
    replica_id: str,
    allocation_id: str,
    resource_id: str,
    location: KVLocation,
    committed: bool,
) -> Replica:
    object_id = directory.register_object(kv)
    allocation_state = AllocationState.COMMITTED if committed else AllocationState.PENDING
    allocation = PhysicalAllocation(
        allocation_id=allocation_id,
        object_id=object_id,
        replica_id=replica_id,
        resource_id=resource_id,
        owner_account="COMMITTED_REPLICA" if committed else "PENDING_REPLICA",
        payload_bytes=64,
        requested_bytes=64,
        allocated_bytes=64,
        padding_bytes=0,
        allocator_metadata_bytes=0,
        internal_fragmentation_bytes=0,
        alignment_bytes=1,
        state=allocation_state,
        created_at_ns=0,
    )
    registry.add(allocation, timestamp_ns=0, event_id=f"add:{allocation_id}")
    replica = Replica(
        replica_id=replica_id,
        object_id=object_id,
        location=location,
        allocation_ids=(allocation_id,),
        expected_shard_ids=("tp0",),
        completed_shard_ids=frozenset(("tp0",)) if committed else frozenset(),
        state=ReplicaState.COMMITTED if committed else ReplicaState.PENDING,
        generation=0,
        route_version=kv.route_version,
        created_at_ns=0,
        published_at_ns=0 if committed else None,
    )
    directory.add_replica(replica)
    return replica


def make_controller(
    des: GlobalDES,
    directory: GlobalKVDirectory,
    registry: AllocationRegistry,
    *,
    output_sink: list[object] | None = None,
) -> BaselineGPUFailureController:
    sink = None if output_sink is None else output_sink.append
    return BaselineGPUFailureController(
        des=des,
        directory=directory,
        allocation_registry=registry,
        gpus=(
            PhysicalGPU("gpu-0", "node-0", ("gpu-0.hbm",)),
            PhysicalGPU("gpu-1", "node-1", ("gpu-1.hbm",)),
        ),
        targets=(
            EngineTarget("engine-dp0", 0, ("gpu-0",), "qwen3-tp1-pp1"),
            EngineTarget("engine-dp1", 1, ("gpu-1",), "qwen3-tp1-pp1"),
        ),
        output_sink=sink,
    )


def test_same_time_failure_cancels_completion_and_fences_output() -> None:
    des = GlobalDES()
    directory = GlobalKVDirectory()
    registry = AllocationRegistry()
    completed: list[str] = []
    des.register_handler(
        EventKind.FORWARD_COMPLETE,
        lambda event, _: completed.append(event.event_id),
    )
    des.register_handler(
        EventKind.TRANSFER_COMPLETE,
        lambda event, _: completed.append(event.event_id),
    )
    controller = make_controller(des, directory, registry)
    controller.begin_request(
        request_id="request-0",
        target_id="engine-dp0",
        required_blocks=(),
    )
    forward = des.schedule_at(10, EventKind.FORWARD_COMPLETE, event_id="forward-complete")
    transfer = des.schedule_at(
        10,
        EventKind.TRANSFER_COMPLETE,
        event_id="transfer-complete",
    )
    des.schedule_at(
        10,
        EventKind.REQUEST_COMPLETE,
        event_id="old-route-output",
        payload={"request_id": "request-0", "route_version": 0, "output_index": 0},
    )
    controller.register_forward(
        forward,
        request_id="request-0",
        route_version=0,
        gpu_id="gpu-0",
    )
    controller.register_transfer(
        transfer,
        request_id="request-0",
        route_version=0,
        source_gpu_id="gpu-0",
        destination_gpu_id=None,
    )
    controller.schedule_gpu_failure(
        failure_id="failure-0",
        gpu_id="gpu-0",
        at_ns=10,
        detection_delay_ns=1,
    )

    des.run(until_ns=10)

    assert completed == []
    assert controller.emitted_outputs == ()
    assert controller.gpu_health("gpu-0") is GPUHealth.FAILED
    assert not controller.target_is_healthy("engine-dp0")
    assert controller.attempt("request-0", 0).status is AttemptStatus.FENCED
    executed_kinds = [
        record.data["kind"]
        for record in des.journal.records
        if record.record_type == "EVENT_EXECUTING"
    ]
    assert executed_kinds == [
        EventKind.FAILURE_INJECT.value,
        EventKind.ROUTE_FENCE.value,
        EventKind.REQUEST_COMPLETE.value,
    ]


def test_same_time_failure_atomically_loses_complete_physical_hbm() -> None:
    des = GlobalDES()
    directory = GlobalKVDirectory()
    registry = AllocationRegistry(journal=des.journal)
    kv = identity(0)
    add_replica(
        directory,
        registry,
        kv,
        replica_id="gpu-replica",
        allocation_id="gpu-allocation",
        resource_id="gpu-0.hbm",
        location=KVLocation.PRIMARY_HBM,
        committed=True,
    )
    ledger = CapacityLedger(
        resource_id="gpu-0.hbm",
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=128,
        initial_accounts={"COMMITTED_REPLICA": 64, "MODEL_WEIGHTS": 32},
    )
    handler = AtomicGPUHBMFailStop(
        ledgers={ledger.resource_id: ledger},
        registry=registry,
        journal=des.journal,
    )
    controller = BaselineGPUFailureController(
        des=des,
        directory=directory,
        allocation_registry=registry,
        gpus=(PhysicalGPU("gpu-0", "node-0", ("gpu-0.hbm",)),),
        targets=(EngineTarget("engine-dp0", 0, ("gpu-0",), "compatible"),),
        hbm_failure_handler=handler,
    )
    controller.track_gpu_allocation("gpu-0", "gpu-allocation")
    controller.begin_request(request_id="request-0", target_id="engine-dp0", required_blocks=(kv,))
    completed: list[str] = []
    des.register_handler(
        EventKind.FORWARD_COMPLETE,
        lambda event, _: completed.append(event.event_id),
    )
    completion = des.schedule_at(10, EventKind.FORWARD_COMPLETE, event_id="same-time-forward")
    controller.register_forward(
        completion,
        request_id="request-0",
        route_version=0,
        gpu_id="gpu-0",
    )
    controller.schedule_gpu_failure(
        failure_id="failure-atomic",
        gpu_id="gpu-0",
        at_ns=10,
        detection_delay_ns=1,
    )

    des.run(until_ns=10)

    assert completed == []
    assert ledger.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT) == ledger.capacity_bytes
    assert registry.get("gpu-allocation").state is AllocationState.LOST
    registry.audit({ledger.resource_id: ledger})

    replay_ledger = CapacityLedger(
        resource_id="gpu-0.hbm",
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=128,
        initial_accounts={"COMMITTED_REPLICA": 64, "MODEL_WEIGHTS": 32},
    )
    replay_capacity_transactions(des.journal, {replay_ledger.resource_id: replay_ledger})
    assert replay_ledger.accounts == ledger.accounts
    assert controller.attempt("request-0", 0).status is AttemptStatus.FENCED


def test_committed_store_prefix_is_recoverable_across_dp_routes() -> None:
    directory = GlobalKVDirectory()
    registry = AllocationRegistry()
    source_blocks = (identity(0), identity(1))
    for index, kv in enumerate(source_blocks):
        add_replica(
            directory,
            registry,
            kv,
            replica_id=f"store-replica-{index}",
            allocation_id=f"store-allocation-{index}",
            resource_id="store-0.segment-0",
            location=KVLocation.STORE_DRAM,
            committed=True,
        )
    rerouted_blocks = tuple(
        replace(
            kv,
            request_id="request-1",
            route_version=1,
            source_gpu_id="gpu-1",
        )
        for kv in source_blocks
    )

    plan = BaselineRecoveryPlanner(directory, registry).plan(
        rerouted_blocks,
        unavailable_resource_ids=("gpu-0.hbm",),
    )

    assert tuple(item.replica_id for item in plan.store_prefix) == (
        "store-replica-0",
        "store-replica-1",
    )
    assert plan.restored_tokens == 32
    assert plan.recompute_tokens == 0
    assert plan.missing_suffix_start_block == 2


def test_pending_replica_breaks_prefix_and_suffix_is_explicit_recompute() -> None:
    directory = GlobalKVDirectory()
    registry = AllocationRegistry()
    blocks = (identity(0), identity(1), identity(2))
    add_replica(
        directory,
        registry,
        blocks[0],
        replica_id="committed-first",
        allocation_id="allocation-first",
        resource_id="store-0.segment-0",
        location=KVLocation.STORE_DRAM,
        committed=True,
    )
    add_replica(
        directory,
        registry,
        blocks[1],
        replica_id="pending-middle",
        allocation_id="allocation-middle",
        resource_id="store-0.segment-0",
        location=KVLocation.STORE_DRAM,
        committed=False,
    )
    add_replica(
        directory,
        registry,
        blocks[2],
        replica_id="committed-tail",
        allocation_id="allocation-tail",
        resource_id="store-0.segment-0",
        location=KVLocation.STORE_DRAM,
        committed=True,
    )

    plan = BaselineRecoveryPlanner(directory, registry).plan(blocks)

    assert tuple(item.replica_id for item in plan.store_prefix) == ("committed-first",)
    assert plan.restored_tokens == 16
    assert plan.recompute_tokens == 32
    assert plan.missing_suffix_start_block == 1


def test_recovery_blocks_must_begin_at_token_zero() -> None:
    planner = BaselineRecoveryPlanner(GlobalKVDirectory(), AllocationRegistry())

    with pytest.raises(ValueError, match="start at token zero"):
        planner.plan((identity(1),))


def test_partial_committed_store_block_is_an_explicit_recompute_suffix() -> None:
    directory = GlobalKVDirectory()
    registry = AllocationRegistry()
    partial = replace(identity(0), token_end=8)
    add_replica(
        directory,
        registry,
        partial,
        replica_id="partial-store-replica",
        allocation_id="partial-store-allocation",
        resource_id="store-0.segment-0",
        location=KVLocation.STORE_DRAM,
        committed=True,
    )

    plan = BaselineRecoveryPlanner(directory, registry).plan((partial,))

    assert plan.store_prefix == ()
    assert plan.restored_tokens == 0
    assert plan.recompute_tokens == 8
    assert plan.missing_suffix_start_block == 0


def test_incomplete_committed_replica_is_not_a_recovery_source() -> None:
    directory = GlobalKVDirectory()
    registry = AllocationRegistry()
    kv = identity(0)
    replica = add_replica(
        directory,
        registry,
        kv,
        replica_id="incomplete-replica",
        allocation_id="incomplete-allocation",
        resource_id="store-0.segment-0",
        location=KVLocation.STORE_DRAM,
        committed=True,
    )
    directory.update_replica(replace(replica, completed_shard_ids=frozenset()))

    plan = BaselineRecoveryPlanner(directory, registry).plan((kv,))

    assert plan.store_prefix == ()
    assert plan.recompute_tokens == 16


def test_failed_gpu_replica_is_lost_but_store_and_network_state_survive() -> None:
    des = GlobalDES()
    directory = GlobalKVDirectory()
    registry = AllocationRegistry(journal=des.journal)
    kv = identity(0)
    primary = add_replica(
        directory,
        registry,
        kv,
        replica_id="a-primary-replica",
        allocation_id="gpu-allocation",
        resource_id="gpu-0.hbm",
        location=KVLocation.PRIMARY_HBM,
        committed=True,
    )
    store = add_replica(
        directory,
        registry,
        kv,
        replica_id="z-store-replica",
        allocation_id="store-allocation",
        resource_id="store-0.segment-0",
        location=KVLocation.STORE_DRAM,
        committed=True,
    )
    network_state = {"fabric-0": {"capacity_bps": 100, "healthy": True}}
    network_before = {key: dict(value) for key, value in network_state.items()}
    controller = make_controller(des, directory, registry)
    controller.track_gpu_allocation("gpu-0", "gpu-allocation")
    controller.begin_request(
        request_id="request-0",
        target_id="engine-dp0",
        required_blocks=(kv,),
    )
    controller.schedule_gpu_failure(
        failure_id="failure-0",
        gpu_id="gpu-0",
        at_ns=1,
        detection_delay_ns=0,
    )

    des.run()

    assert registry.get("gpu-allocation").state is AllocationState.LOST
    assert registry.get("store-allocation").state is AllocationState.COMMITTED
    assert directory.get_replica(primary.replica_id).state is ReplicaState.LOST
    assert directory.query(kv) == (store,)
    assert network_state == network_before
    assert controller.recovery_plan("request-0", 1).store_prefix[0].replica_id == (
        "z-store-replica"
    )


def test_reroute_activation_allows_exactly_one_output_and_fences_stale_route() -> None:
    des = GlobalDES()
    directory = GlobalKVDirectory()
    registry = AllocationRegistry()
    delivered: list[object] = []
    controller = make_controller(des, directory, registry, output_sink=delivered)
    controller.begin_request(
        request_id="request-0",
        target_id="engine-dp0",
        required_blocks=(),
    )
    controller.schedule_gpu_failure(
        failure_id="failure-0",
        gpu_id="gpu-0",
        at_ns=1,
        detection_delay_ns=0,
    )
    des.run()
    assert controller.current_route_version("request-0") == 1
    assert controller.attempt("request-0", 1).status is AttemptStatus.RECOVERING

    assert not controller.try_emit_output(request_id="request-0", route_version=0, output_index=0)
    assert not controller.try_emit_output(request_id="request-0", route_version=1, output_index=0)
    with pytest.raises(RecoveryInvariantError, match="prompt materialization"):
        controller.activate_recovery("request-0", 1)
    assert controller.start_silent_replay("request-0", 1).status is (SilentReplayStatus.REPLAYING)
    ready = controller.record_prompt_materialized_output(
        "request-0",
        1,
        output_index=0,
    )
    assert ready.status is SilentReplayStatus.READY_TO_ACTIVATE
    assert delivered == []
    controller.activate_recovery("request-0", 1)
    assert not controller.try_emit_output(request_id="request-0", route_version=1, output_index=0)

    assert len(delivered) == 1
    assert controller.emitted_outputs == tuple(delivered)
    assert controller.emitted_outputs[0].route_version == 1


def test_committed_output_checkpoint_requires_continuous_silent_replay() -> None:
    des = GlobalDES()
    delivered: list[object] = []
    controller = make_controller(
        des,
        GlobalKVDirectory(),
        AllocationRegistry(),
        output_sink=delivered,
    )
    controller.begin_request(
        request_id="request-0",
        target_id="engine-dp0",
        required_blocks=(),
    )
    assert controller.try_emit_output(request_id="request-0", route_version=0, output_index=0)
    assert controller.try_emit_output(request_id="request-0", route_version=0, output_index=1)
    controller.schedule_gpu_failure(
        failure_id="failure-0",
        gpu_id="gpu-0",
        at_ns=1,
        detection_delay_ns=0,
    )
    des.run()

    plan = controller.silent_replay_plan("request-0", 1)
    assert plan.status is SilentReplayStatus.PLANNED
    assert plan.committed_next_output_index == 2
    assert not controller.try_emit_output(request_id="request-0", route_version=0, output_index=2)
    with pytest.raises(RecoveryInvariantError, match="silent replay must reach"):
        controller.activate_recovery("request-0", 1)

    assert controller.start_silent_replay("request-0", 1).status is (SilentReplayStatus.REPLAYING)
    with pytest.raises(RecoveryInvariantError, match="duplicate or discontinuous"):
        controller.record_silent_replay_output(
            "request-0",
            1,
            replayed_output_index=1,
        )
    controller.record_silent_replay_output(
        "request-0",
        1,
        replayed_output_index=0,
    )
    with pytest.raises(RecoveryInvariantError, match="silent replay must reach"):
        controller.activate_recovery("request-0", 1)
    ready = controller.record_silent_replay_output(
        "request-0",
        1,
        replayed_output_index=1,
    )
    assert ready.status is SilentReplayStatus.READY_TO_ACTIVATE
    controller.activate_recovery("request-0", 1)

    assert not controller.try_emit_output(request_id="request-0", route_version=1, output_index=1)
    assert controller.try_emit_output(request_id="request-0", route_version=1, output_index=2)
    assert [(item.route_version, item.output_index) for item in delivered] == [
        (0, 0),
        (0, 1),
        (1, 2),
    ]


def test_pre_mid_and_post_silent_replay_failures_fence_every_old_route() -> None:
    des = GlobalDES()
    controller = BaselineGPUFailureController(
        des=des,
        directory=GlobalKVDirectory(),
        allocation_registry=AllocationRegistry(),
        gpus=tuple(
            PhysicalGPU(f"gpu-{index}", f"node-{index}", (f"gpu-{index}.hbm",))
            for index in range(4)
        ),
        targets=tuple(
            EngineTarget(
                f"engine-dp{index}",
                index,
                (f"gpu-{index}",),
                "compatible",
            )
            for index in range(4)
        ),
    )
    controller.begin_request(
        request_id="request-0",
        target_id="engine-dp0",
        required_blocks=(),
    )
    assert controller.try_emit_output(request_id="request-0", route_version=0, output_index=0)
    assert controller.try_emit_output(request_id="request-0", route_version=0, output_index=1)

    # Route 1 fails before replay starts.
    controller.schedule_gpu_failure(
        failure_id="pre-replay",
        gpu_id="gpu-0",
        at_ns=1,
        detection_delay_ns=0,
    )
    des.run()
    assert controller.silent_replay_plan("request-0", 1).status is (SilentReplayStatus.PLANNED)
    controller.schedule_gpu_failure(
        failure_id="before-start",
        gpu_id="gpu-1",
        at_ns=2,
        detection_delay_ns=0,
    )
    des.run()
    assert controller.silent_replay_plan("request-0", 1).status is (SilentReplayStatus.FENCED)

    # Route 2 fails after partial replay progress.
    controller.start_silent_replay("request-0", 2)
    controller.record_silent_replay_output(
        "request-0",
        2,
        replayed_output_index=0,
    )
    controller.schedule_gpu_failure(
        failure_id="mid-replay",
        gpu_id="gpu-2",
        at_ns=3,
        detection_delay_ns=0,
    )
    des.run()
    assert controller.silent_replay_plan("request-0", 2).status is (SilentReplayStatus.FENCED)

    # Route 3 reaches the checkpoint, then fails before atomic activation.
    controller.start_silent_replay("request-0", 3)
    controller.record_silent_replay_output(
        "request-0",
        3,
        replayed_output_index=0,
    )
    controller.record_silent_replay_output(
        "request-0",
        3,
        replayed_output_index=1,
    )
    assert controller.silent_replay_plan("request-0", 3).status is (
        SilentReplayStatus.READY_TO_ACTIVATE
    )
    controller.schedule_gpu_failure(
        failure_id="post-replay-pre-activation",
        gpu_id="gpu-3",
        at_ns=4,
        detection_delay_ns=0,
    )
    des.run()
    assert controller.silent_replay_plan("request-0", 3).status is (SilentReplayStatus.FENCED)
    assert controller.next_output_index("request-0") == 2
    assert [(item.route_version, item.output_index) for item in controller.emitted_outputs] == [
        (0, 0),
        (0, 1),
    ]


def test_non_gpu_failure_is_rejected_before_event_scheduling() -> None:
    des = GlobalDES()
    controller = make_controller(des, GlobalKVDirectory(), AllocationRegistry())

    with pytest.raises(ValueError, match="only GPU_FAILURE"):
        controller.schedule_gpu_failure(
            failure_id="bad",
            failure_type="NIC_FAILURE",
            gpu_id="gpu-0",
            at_ns=1,
            detection_delay_ns=0,
        )

    assert des.pending_count == 0


def test_external_route_authority_is_the_only_reroute_selector() -> None:
    class Authority:
        def __init__(self) -> None:
            self.current = ("request-0", 0, "engine-dp0")
            self.reroute_calls = 0

        def is_authoritative(
            self,
            *,
            request_id: str,
            route_version: int,
            target_id: str,
        ) -> bool:
            return self.current == (request_id, route_version, target_id)

        def reroute(
            self,
            *,
            current: object,
            compatible_targets: tuple[EngineTarget, ...],
            healthy_target_ids: frozenset[str],
            now_ns: int,
        ) -> RerouteDecision:
            del current, now_ns
            assert {target.target_id for target in compatible_targets} == {
                "engine-dp0",
                "engine-dp1",
                "engine-dp2",
            }
            assert healthy_target_ids == frozenset(("engine-dp1", "engine-dp2"))
            self.reroute_calls += 1
            self.current = ("request-0", 1, "engine-dp2")
            return RerouteDecision(
                target_id="engine-dp2",
                route_version=1,
                authority_fingerprint="f" * 64,
            )

    des = GlobalDES()
    authority = Authority()
    controller = BaselineGPUFailureController(
        des=des,
        directory=GlobalKVDirectory(),
        allocation_registry=AllocationRegistry(),
        gpus=(
            PhysicalGPU("gpu-0", "node-0", ("gpu-0.hbm",)),
            PhysicalGPU("gpu-1", "node-1", ("gpu-1.hbm",)),
            PhysicalGPU("gpu-2", "node-2", ("gpu-2.hbm",)),
        ),
        targets=(
            EngineTarget("engine-dp0", 0, ("gpu-0",), "compatible"),
            EngineTarget("engine-dp1", 1, ("gpu-1",), "compatible"),
            EngineTarget("engine-dp2", 2, ("gpu-2",), "compatible"),
        ),
        route_authority=authority,
    )
    controller.begin_request(
        request_id="request-0",
        target_id="engine-dp0",
        required_blocks=(),
    )
    controller.schedule_gpu_failure(
        failure_id="failure-0",
        gpu_id="gpu-0",
        at_ns=1,
        detection_delay_ns=0,
    )

    des.run()

    assert authority.reroute_calls == 1
    assert controller.attempt("request-0", 1).target_id == "engine-dp2"
    assert controller.attempt("request-0", 1).status is AttemptStatus.RECOVERING


def test_identical_failure_runs_have_byte_identical_journals() -> None:
    def run_once() -> bytes:
        des = GlobalDES()
        controller = make_controller(des, GlobalKVDirectory(), AllocationRegistry())
        controller.begin_request(
            request_id="request-0",
            target_id="engine-dp0",
            required_blocks=(),
        )
        controller.schedule_gpu_failure(
            failure_id="failure-0",
            gpu_id="gpu-0",
            at_ns=5,
            detection_delay_ns=0,
        )
        des.run()
        controller.start_silent_replay("request-0", 1)
        controller.record_prompt_materialized_output(
            "request-0",
            1,
            output_index=0,
        )
        controller.activate_recovery("request-0", 1)
        des.schedule_at(
            6,
            EventKind.REQUEST_COMPLETE,
            event_id="rerouted-output",
            payload={"request_id": "request-0", "route_version": 1, "output_index": 1},
        )
        des.run()
        return des.journal.to_jsonl_bytes()

    assert run_once() == run_once()
