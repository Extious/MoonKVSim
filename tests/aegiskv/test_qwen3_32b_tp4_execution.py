from __future__ import annotations

from pathlib import Path

import pytest

from moonkvsim.aegiskv.qwen3_32b_tp4_config import (
    load_qwen3_32b_tp4_engine_config,
)
from moonkvsim.aegiskv.qwen3_32b_tp4_execution import (
    Algorithm3ControlInput,
    FailureSet,
    PathExecutionControl,
    Qwen3TP4ExecutionDriver,
    ShardTransferStatus,
)
from moonkvsim.aegiskv.tp_recovery import TPCollectiveKind, TPLayoutIdentity
from moonkvsim.aegiskv.types import PathCommitState, PolicyPool

ROOT = Path(__file__).resolve().parents[2]
TOKENS = 16
SHARD_BYTES = TOKENS * 65_536
LOGICAL_BYTES = 4 * SHARD_BYTES


def _driver() -> Qwen3TP4ExecutionDriver:
    return Qwen3TP4ExecutionDriver(load_qwen3_32b_tp4_engine_config(root=ROOT))


def _protected(
    *,
    source_dp_rank: int = 0,
    peer_control: PathExecutionControl | None = None,
    store_control: PathExecutionControl | None = None,
):
    return _driver().protect_logical_chunk(
        logical_chunk_id="request-0:chunk-0",
        source_dp_rank=source_dp_rank,
        token_count=TOKENS,
        route_version=7,
        start_ns=100,
        peer_control=peer_control,
        store_control=store_control,
    )


def test_success_expands_four_rank_transfers_and_commits_each_path() -> None:
    protected = _protected()

    assert protected.logical_chunk_bytes == LOGICAL_BYTES
    assert protected.shard_bytes == SHARD_BYTES
    for path in (protected.peer_hbm, protected.store_dram):
        assert path.state is PathCommitState.COMMITTED
        assert path.transaction.acked_ranks == (0, 1, 2, 3)
        assert len(path.transfers) == 4
        assert all(item.status is ShardTransferStatus.ACKED for item in path.transfers)
        assert path.byte_audit.sum_rank_shard_bytes == LOGICAL_BYTES
        assert path.byte_audit.acknowledged_bytes == LOGICAL_BYTES
        assert path.byte_audit.committed_bytes == LOGICAL_BYTES
        assert path.byte_audit.kv_reduction_bytes == 0
        assert path.byte_audit.valid


def test_partial_ack_remains_pending_and_is_not_recovery_eligible() -> None:
    protected = _protected(peer_control=PathExecutionControl(no_ack_tp_ranks=frozenset({3})))

    assert protected.peer_hbm.state is PathCommitState.PENDING
    assert protected.peer_hbm.transaction.acked_ranks == (0, 1, 2)
    assert protected.peer_hbm.byte_audit.acknowledged_bytes == 3 * SHARD_BYTES
    assert protected.peer_hbm.byte_audit.committed_bytes == 0
    assert protected.store_dram.state is PathCommitState.COMMITTED
    with pytest.raises(ValueError, match="committed all-shard"):
        _driver().recover_logical_chunk(
            protected,
            pool=PolicyPool.PEER_HBM,
            failures=FailureSet(failed_gpu_ids=frozenset({"gpu:node-0:0"})),
            start_ns=1_000,
            directory_install_ns=700,
            model_forward_all_reduce_bytes_per_rank=4096,
        )


def test_one_rank_failure_aborts_only_that_independent_path() -> None:
    protected = _protected(peer_control=PathExecutionControl(failed_tp_ranks=frozenset({2})))

    assert protected.peer_hbm.state is PathCommitState.ABORTED
    assert protected.peer_hbm.transaction.terminal_reason == "SHARD_TRANSFER_FAILED:tp=2"
    assert tuple(item.status for item in protected.peer_hbm.transfers) == (
        ShardTransferStatus.ACKED,
        ShardTransferStatus.ACKED,
        ShardTransferStatus.FAILED,
        ShardTransferStatus.CANCELED,
    )
    assert protected.peer_hbm.byte_audit.committed_bytes == 0
    assert protected.store_dram.state is PathCommitState.COMMITTED
    assert protected.store_dram.byte_audit.committed_bytes == LOGICAL_BYTES


def test_peer_shards_preserve_tp_rank_and_cross_node_mapping() -> None:
    protected = _protected(source_dp_rank=7)

    for record in protected.peer_hbm.transfers:
        assert record.source_node_id == "node-7"
        assert record.destination_node_id == "node-0"
        assert record.source_resource_id == f"gpu:node-7:{record.tp_rank}"
        assert record.destination_resource_id.startswith(f"peer-hbm:gpu:node-0:{record.tp_rank}:")
        assert "fabric:node-7->node-0:rdma-gdr" in record.rate_resource_ids


def test_layout_incompatibility_fails_closed_before_recovery() -> None:
    protected = _protected()
    incompatible = TPLayoutIdentity(
        model_revision=protected.layout.model_revision,
        kv_abi=protected.layout.kv_abi,
        layout_id="different-layout",
        tensor_parallel_size=4,
        pipeline_parallel_size=1,
    )

    with pytest.raises(ValueError, match="route/layout"):
        _driver().recover_logical_chunk(
            protected,
            pool=PolicyPool.PEER_HBM,
            failures=FailureSet(failed_gpu_ids=frozenset({"gpu:node-0:2"})),
            start_ns=1_000,
            directory_install_ns=700,
            model_forward_all_reduce_bytes_per_rank=4096,
            requested_layout=incompatible,
        )


def test_peer_recovery_uses_max_rank_activation_then_barrier_and_directory() -> None:
    driver = _driver()
    protected = driver.protect_logical_chunk(
        logical_chunk_id="request-0:chunk-0",
        source_dp_rank=0,
        token_count=TOKENS,
        route_version=7,
    )
    recovery = driver.recover_logical_chunk(
        protected,
        pool=PolicyPool.PEER_HBM,
        failures=FailureSet(failed_gpu_ids=frozenset({"gpu:node-0:2"})),
        start_ns=1_000,
        directory_install_ns=700,
        model_forward_all_reduce_bytes_per_rank=4096,
        peer_activation_ns_by_rank=(10, 40, 20, 30),
    )

    assert tuple(item.complete_ns for item in recovery.rank_costs) == (
        1_010,
        1_040,
        1_020,
        1_030,
    )
    assert recovery.barrier.start_ns == 1_040
    assert recovery.barrier.duration_ns == 50_000
    assert recovery.barrier.payload_bytes == 0
    assert recovery.directory_install.start_ns == 51_040
    assert recovery.directory_install.duration_ns == 700
    assert recovery.directory_install.resource_id == "directory:node-1:generation-install"
    assert recovery.kv_recovery_complete_ns == 51_740
    assert recovery.kv_recovery_latency_ns == 50_740
    assert tuple(item.kind for item in recovery.plan.collectives) == (
        TPCollectiveKind.ACTIVATION_BARRIER,
        TPCollectiveKind.MODEL_ALL_REDUCE,
    )


def test_model_forward_all_reduce_is_separate_and_never_reduces_kv() -> None:
    driver = _driver()
    protected = driver.protect_logical_chunk(
        logical_chunk_id="request-0:chunk-0",
        source_dp_rank=0,
        token_count=TOKENS,
        route_version=7,
    )
    recovery = driver.recover_logical_chunk(
        protected,
        pool=PolicyPool.PEER_HBM,
        failures=FailureSet(failed_node_ids=frozenset({"node-0"})),
        start_ns=2_000,
        directory_install_ns=500,
        model_forward_all_reduce_bytes_per_rank=8192,
    )

    collective = recovery.model_forward_all_reduce
    assert collective.start_ns == recovery.kv_recovery_complete_ns
    assert collective.complete_ns > collective.start_ns
    assert collective.payload_bytes_per_rank == 8192
    assert collective.total_collective_bytes == 4 * 8192
    assert collective.operates_on_kv is False
    assert collective.included_in_kv_recovery_latency is False
    assert recovery.plan.kv_shards_are_reduced is False
    assert recovery.byte_audit.kv_reduction_bytes == 0
    assert recovery.byte_audit.model_collective_bytes_excluded == 4 * 8192


def test_store_recovery_supports_node_failure_and_selects_complete_healthy_tp_group() -> None:
    driver = _driver()
    protected = driver.protect_logical_chunk(
        logical_chunk_id="request-0:chunk-0",
        source_dp_rank=0,
        token_count=TOKENS,
        route_version=7,
    )
    recovery = driver.recover_logical_chunk(
        protected,
        pool=PolicyPool.STORE_DRAM,
        failures=FailureSet(
            failed_gpu_ids=frozenset({"gpu:node-1:3"}),
            failed_node_ids=frozenset({"node-0"}),
        ),
        start_ns=5_000,
        directory_install_ns=900,
        model_forward_all_reduce_bytes_per_rank=4096,
    )

    assert recovery.destination_dp_rank == 2
    assert {item.destination_node_id for item in recovery.rank_costs} == {"node-2"}
    assert all(item.source_node_id == "store-dram-service" for item in recovery.rank_costs)
    assert sum(item.transfer_bytes for item in recovery.rank_costs) == LOGICAL_BYTES
    assert sum(item.activation_bytes for item in recovery.rank_costs) == 0
    assert recovery.byte_audit.source_read_bytes == LOGICAL_BYTES
    assert recovery.byte_audit.destination_write_bytes == LOGICAL_BYTES
    assert recovery.byte_audit.valid


def test_peer_recovery_rejects_failed_target_tp_group() -> None:
    protected = _protected()

    with pytest.raises(ValueError, match="Peer-HBM TP group is unavailable"):
        _driver().recover_logical_chunk(
            protected,
            pool=PolicyPool.PEER_HBM,
            failures=FailureSet(
                failed_gpu_ids=frozenset({"gpu:node-1:1"}),
                failed_node_ids=frozenset({"node-0"}),
            ),
            start_ns=1_000,
            directory_install_ns=700,
            model_forward_all_reduce_bytes_per_rank=4096,
        )


def test_rank_node_resources_and_byte_conservation_are_explicit() -> None:
    protected = _protected()

    assert len(protected.rank_resources) == 16
    node_by_id = {item.node_id: item for item in protected.node_resources}
    assert node_by_id["node-0"].kv_source_read_bytes == 2 * LOGICAL_BYTES
    assert node_by_id["node-1"].kv_destination_write_bytes == LOGICAL_BYTES
    assert node_by_id["store-dram-service"].kv_destination_write_bytes == LOGICAL_BYTES
    assert "copy:gpu:node-1:0:d2d" not in node_by_id["node-0"].resource_ids
    assert "copy:gpu:node-0:0:d2d" not in node_by_id["node-1"].resource_ids
    assert "copy:gpu:node-0:0:d2h" not in node_by_id["store-dram-service"].resource_ids
    assert protected.peer_hbm.byte_audit.source_read_bytes == LOGICAL_BYTES
    assert protected.peer_hbm.byte_audit.destination_write_bytes == LOGICAL_BYTES
    assert protected.store_dram.byte_audit.source_read_bytes == LOGICAL_BYTES
    assert protected.store_dram.byte_audit.destination_write_bytes == LOGICAL_BYTES

    recovery = _driver().recover_logical_chunk(
        protected,
        pool=PolicyPool.PEER_HBM,
        failures=FailureSet(failed_node_ids=frozenset({"node-0"})),
        start_ns=1_000,
        directory_install_ns=700,
        model_forward_all_reduce_bytes_per_rank=4096,
    )
    assert len(recovery.rank_resources) == 12
    recovery_nodes = {item.node_id: item for item in recovery.node_resources}
    assert recovery_nodes["node-1"].kv_activated_bytes == LOGICAL_BYTES
    assert recovery_nodes["node-1"].model_collective_bytes == 4 * 4096
    assert "directory:node-1:generation-install" in recovery_nodes["node-1"].resource_ids
    assert recovery.byte_audit.sum_rank_restored_kv_bytes == LOGICAL_BYTES
    assert recovery.byte_audit.valid


def test_execution_and_audit_fingerprints_are_deterministic() -> None:
    first_driver = _driver()
    second_driver = _driver()
    first = first_driver.protect_logical_chunk(
        logical_chunk_id="deterministic:chunk",
        source_dp_rank=3,
        token_count=32,
        route_version=11,
        start_ns=99,
    )
    second = second_driver.protect_logical_chunk(
        logical_chunk_id="deterministic:chunk",
        source_dp_rank=3,
        token_count=32,
        route_version=11,
        start_ns=99,
    )

    assert first.fingerprint == second.fingerprint
    assert first.rank_resources == second.rank_resources
    assert first.node_resources == second.node_resources

    failure = FailureSet(failed_node_ids=frozenset({"node-3"}))
    first_recovery = first_driver.recover_logical_chunk(
        first,
        pool=PolicyPool.PEER_HBM,
        failures=failure,
        start_ns=1_234,
        directory_install_ns=567,
        model_forward_all_reduce_bytes_per_rank=8192,
    )
    second_recovery = second_driver.recover_logical_chunk(
        second,
        pool=PolicyPool.PEER_HBM,
        failures=failure,
        start_ns=1_234,
        directory_install_ns=567,
        model_forward_all_reduce_bytes_per_rank=8192,
    )
    assert first_recovery.fingerprint == second_recovery.fingerprint
    assert first_recovery.rank_costs == second_recovery.rank_costs
    assert first_recovery.byte_audit == second_recovery.byte_audit


def test_des_backed_execution_runs_protection_fence_recovery_and_forward() -> None:
    recovery = _driver().execute_des_failure_recovery(
        logical_chunk_id="des-backed:chunk",
        source_dp_rank=0,
        token_count=32,
        route_version=1,
        protection_start_ns=0,
        failure_id="failure-0",
        failure_at_ns=450_000,
        failures=FailureSet(failed_node_ids=frozenset({"node-0"})),
        pool=PolicyPool.PEER_HBM,
        recovery_start_ns=450_000,
        directory_install_ns=700,
        model_forward_all_reduce_bytes_per_rank=4096,
        peer_activation_ns_by_rank=(10, 40, 20, 30),
        algorithm3_control_events=(
            Algorithm3ControlInput(
                target_dp_rank=1,
                timestamp_ns=1,
                foreground_pressure=True,
                reason="PRIMARY_ALLOCATION_SHORTFALL",
            ),
            *tuple(
                Algorithm3ControlInput(
                    target_dp_rank=1,
                    timestamp_ns=1 + 100_000 * index,
                    foreground_pressure=False,
                    reason="STABLE_WINDOW",
                )
                for index in range(1, 5)
            ),
        ),
    )

    evidence = recovery.des_evidence
    assert evidence is not None
    assert evidence.evidence_class == "modeled_uncalibrated"
    assert evidence.fenced_dp_ranks == (0,)
    assert evidence.failure_fence_event_count == 1
    assert evidence.recovery_phase == "FORWARD_COMPLETE"
    assert evidence.four_shard_recovery_executed is True
    assert evidence.capacity_conservation_valid is True
    assert evidence.algorithm2_four_shard_transaction_surface_executed is True
    assert evidence.algorithm3_peer_quota_surface_enforced is True
    assert evidence.algorithm3_controller_integration == "per_dp_rank_global_des_aimd"
    assert [row.action for row in evidence.algorithm3_audit] == [
        "MULTIPLICATIVE_DECREASE",
        "STABLE_WINDOW",
        "STABLE_WINDOW",
        "STABLE_WINDOW",
        "ADDITIVE_INCREASE",
    ]
    assert all(row.quota_enforced for row in evidence.algorithm3_audit)
    recovery_kinds = [
        event.kind for event in evidence.event_trace if "recovery-00000000" in event.event_id
    ]
    assert recovery_kinds == [
        "RECOVERY_START",
        "GET_COMPLETE",
        "GET_COMPLETE",
        "GET_COMPLETE",
        "GET_COMPLETE",
        "RECOVERY_COMPLETE",
        "DIRECTORY_PUBLISH",
        "FORWARD_START",
        "FORWARD_COMPLETE",
    ]
    assert tuple(row.complete_ns for row in recovery.rank_costs) == (
        450_010,
        450_040,
        450_020,
        450_030,
    )
