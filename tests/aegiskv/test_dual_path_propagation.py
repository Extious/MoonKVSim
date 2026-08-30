from __future__ import annotations

from moonkvsim.aegiskv.kv_directory import ResidencyOutcome
from moonkvsim.aegiskv.propagation import (
    DualPathPropagator,
    PropagationPathState,
)
from moonkvsim.aegiskv.types import AdmissionOutcome, PathCommitState, PolicyPool
from moonkvsim.store.transfer_engine import MemoryKind, MemoryLocation, TransferStatus
from tests.aegiskv._integration_support import (
    SOURCE_ALLOCATION_ID,
    SOURCE_RESOURCE_ID,
    build_env,
    reserve,
    transfer_task,
)


def test_dual_paths_start_from_same_production_buffer_and_commit_independently() -> None:
    env = build_env()
    admission = reserve(
        env,
        operation_id="dual",
        peer=AdmissionOutcome.ADMIT,
        store=AdmissionOutcome.ADMIT,
    )
    peer_task = transfer_task(
        env,
        admission,
        pool=PolicyPool.PEER_HBM,
        transfer_id="dual-peer-transfer",
    )
    store_task = transfer_task(
        env,
        admission,
        pool=PolicyPool.STORE_DRAM,
        transfer_id="dual-store-transfer",
    )
    propagator = DualPathPropagator(
        runtime=env.runtime,
        peer_pool=env.peer_pool,
        store_pool=env.store_pool,
    )

    started = propagator.start(
        admission,
        peer_task=peer_task,
        store_task=store_task,
    )

    assert started.peer.state is started.store.state is PropagationPathState.STARTED
    assert peer_task.metadata.source == store_task.metadata.source
    assert peer_task.metadata.source.resource_id == SOURCE_RESOURCE_ID
    assert env.registry.overlay(SOURCE_ALLOCATION_ID).source_pin_count == 2
    assert set(env.runtime.active_transfer_ids) == {
        "dual-peer-transfer",
        "dual-store-transfer",
    }

    env.des.run()

    peer_ticket = admission.peer.peer_ticket
    store_ticket = admission.store.store_ticket
    assert peer_ticket is not None and store_ticket is not None
    assert peer_task.status is store_task.status is TransferStatus.COMPLETED
    assert peer_ticket.state is store_ticket.state is PathCommitState.COMMITTED
    assert env.registry.overlay(SOURCE_ALLOCATION_ID).source_pin_count == 0
    assert propagator.committed_outcome(admission) is ResidencyOutcome.HBM_AND_DRAM
    transaction_causes = {
        record.data["cause"]
        for record in env.journal.records
        if record.record_type == "RESOURCE_TRANSACTION"
    }
    assert {
        "AEGIS_PEER_HBM_RESERVE",
        "AEGIS_PEER_HBM_COMMIT",
        "AEGIS_STORE_DRAM_START",
        "AEGIS_STORE_DRAM_END",
    }.issubset(transaction_causes)
    propagator.audit()


def test_aborting_peer_transfer_never_aborts_store_path() -> None:
    env = build_env()
    admission = reserve(
        env,
        operation_id="abort-one",
        peer=AdmissionOutcome.ADMIT,
        store=AdmissionOutcome.ADMIT,
    )
    peer_task = transfer_task(
        env,
        admission,
        pool=PolicyPool.PEER_HBM,
        transfer_id="abort-peer-transfer",
    )
    store_task = transfer_task(
        env,
        admission,
        pool=PolicyPool.STORE_DRAM,
        transfer_id="surviving-store-transfer",
    )
    propagator = DualPathPropagator(
        runtime=env.runtime,
        peer_pool=env.peer_pool,
        store_pool=env.store_pool,
    )
    propagator.start(admission, peer_task=peer_task, store_task=store_task)

    env.runtime.abort_task("abort-peer-transfer", reason="INJECTED_PEER_PATH_FAILURE")

    peer_ticket = admission.peer.peer_ticket
    store_ticket = admission.store.store_ticket
    assert peer_ticket is not None and store_ticket is not None
    assert peer_ticket.state is PathCommitState.ABORTED
    assert store_ticket.state is PathCommitState.PENDING
    assert env.runtime.active_transfer_ids == ("surviving-store-transfer",)
    assert env.registry.overlay(SOURCE_ALLOCATION_ID).source_pin_count == 1

    env.des.run()

    assert store_task.status is TransferStatus.COMPLETED
    assert store_ticket.state is PathCommitState.COMMITTED
    assert propagator.committed_outcome(admission) is ResidencyOutcome.DRAM_ONLY
    assert env.registry.overlay(SOURCE_ALLOCATION_ID).source_pin_count == 0


def test_store_path_rejects_peer_target_as_relay_while_peer_path_continues() -> None:
    env = build_env()
    admission = reserve(
        env,
        operation_id="no-relay",
        peer=AdmissionOutcome.ADMIT,
        store=AdmissionOutcome.ADMIT,
    )
    peer_task = transfer_task(
        env,
        admission,
        pool=PolicyPool.PEER_HBM,
        transfer_id="no-relay-peer",
    )
    peer_as_source = MemoryLocation(
        resource_id="hbm-peer",
        node_id="node-peer",
        numa_node_id="numa:node-peer:0",
        kind=MemoryKind.GPU_HBM,
        endpoint="rdma://hbm-peer",
        gpu_id="gpu-peer",
    )
    relayed_store_task = transfer_task(
        env,
        admission,
        pool=PolicyPool.STORE_DRAM,
        transfer_id="forbidden-relay-store",
        source=peer_as_source,
    )
    propagator = DualPathPropagator(
        runtime=env.runtime,
        peer_pool=env.peer_pool,
        store_pool=env.store_pool,
    )

    started = propagator.start(
        admission,
        peer_task=peer_task,
        store_task=relayed_store_task,
    )

    assert started.peer.state is PropagationPathState.STARTED
    assert started.store.state is PropagationPathState.START_FAILED
    assert started.store.error is not None and "production allocation" in started.store.error
    store_ticket = admission.store.store_ticket
    assert store_ticket is not None and store_ticket.state is PathCommitState.ABORTED
    assert env.runtime.active_transfer_ids == ("no-relay-peer",)

    env.des.run()

    peer_ticket = admission.peer.peer_ticket
    assert peer_ticket is not None and peer_ticket.state is PathCommitState.COMMITTED
    assert propagator.committed_outcome(admission) is ResidencyOutcome.HBM_ONLY
