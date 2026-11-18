from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from moonkvsim.aegiskv.qwen3_32b_tp4_config import (
    load_qwen3_32b_tp4_engine_config,
)
from moonkvsim.aegiskv.qwen3_32b_tp4_des import (
    EVIDENCE_CLASS,
    MODEL_WEIGHTS_ACCOUNT,
    RUNTIME_FIXED_ACCOUNT,
    Qwen3TP4GroupDES,
    RecoveryPhase,
)
from moonkvsim.aegiskv.qwen3_32b_tp4_execution import PathExecutionControl
from moonkvsim.aegiskv.types import PathCommitState, PolicyPool
from moonkvsim.simulation.event import EventKind
from moonkvsim.simulation.ledger import UNAVAILABLE_CAPACITY_ACCOUNT

ROOT = Path(__file__).resolve().parents[2]
TOKENS = 16
SHARD_BYTES = TOKENS * 65_536
LOGICAL_BYTES = 4 * SHARD_BYTES


def _des() -> Qwen3TP4GroupDES:
    return Qwen3TP4GroupDES(
        load_qwen3_32b_tp4_engine_config(root=ROOT),
    )


def _protected(des: Qwen3TP4GroupDES, *, source_dp_rank: int = 0):
    run = des.protect_logical_chunk(
        logical_chunk_id="request-0:chunk-0",
        source_dp_rank=source_dp_rank,
        token_count=TOKENS,
        route_version=7,
    )
    des.run()
    return run


def _fence_source(des: Qwen3TP4GroupDES, *, dp_rank: int = 0) -> None:
    des.schedule_rank_failure(
        failure_id=f"failure-dp{dp_rank}",
        dp_rank=dp_rank,
        tp_rank=2,
        at_ns=des.des.now_ns + 1,
    )
    des.run()


def test_builds_eight_tp4_groups_thirty_two_hbm_ledgers_and_rate_resources() -> None:
    des = _des()

    assert des.evidence_class == EVIDENCE_CLASS == "modeled_uncalibrated"
    assert len(des.groups) == 8
    assert all(tuple(rank.tp_rank for rank in group.ranks) == (0, 1, 2, 3) for group in des.groups)
    assert len(des.hbm_ledgers) == 32
    assert all(
        ledger.capacity_bytes == des.config.cluster.physical_hbm_bytes_per_gpu
        for ledger in des.hbm_ledgers.values()
    )
    rank_capacity = des.config.capacity.rank_hbm
    for ledger in des.hbm_ledgers.values():
        assert ledger.bytes_in(MODEL_WEIGHTS_ACCOUNT) == (
            rank_capacity.model_weights_bytes_per_rank
        )
        assert ledger.bytes_in(RUNTIME_FIXED_ACCOUNT) == (
            rank_capacity.runtime_fixed_bytes_per_rank
        )
        assert ledger.bytes_in("FREE") == rank_capacity.kv_capable_hbm_bytes_per_rank
    assert des.store_ledger.resource_id == "store-0:segment-0"
    assert des.store_ledger.capacity_bytes == (des.config.capacity.store_dram.total_capacity_bytes)
    assert "fabric:node-0->node-1:rdma-gdr" in des.rate_resources
    assert "store:store-dram-service:write" in des.rate_resources
    assert "node:node-0:nvlink" in des.rate_resources
    assert des.capacity_audit().valid


def test_constructor_rejects_store_capacity_that_drifts_from_unique_config_segment() -> None:
    config = load_qwen3_32b_tp4_engine_config(root=ROOT)

    with pytest.raises(ValueError, match=r"exactly match config\.capacity\.store_dram"):
        Qwen3TP4GroupDES(
            config,
            store_dram_capacity_bytes=config.capacity.store_dram.total_capacity_bytes - 1,
        )


def test_each_path_waits_for_all_four_acks_before_capacity_commit() -> None:
    des = _des()
    protection = des.protect_logical_chunk(
        logical_chunk_id="partial-ack",
        source_dp_rank=0,
        token_count=TOKENS,
        route_version=1,
        peer_control=PathExecutionControl(no_ack_tp_ranks=frozenset({3})),
    )

    des.run()

    peer = protection.peer_hbm
    assert peer.state is PathCommitState.PENDING
    assert peer.transaction.acked_ranks == (0, 1, 2)
    assert not peer.capacity_committed
    assert peer.byte_audit.acknowledged_bytes == 3 * SHARD_BYTES
    assert peer.byte_audit.committed_bytes == 0
    assert (
        sum(
            des.capacity_ledgers[ledger_id].bytes_in(account)
            for ledger_id, account in zip(
                peer.ledger_resource_ids,
                peer.pending_accounts,
                strict=True,
            )
        )
        == LOGICAL_BYTES
    )
    assert protection.store_dram.state is PathCommitState.COMMITTED
    assert protection.store_dram.capacity_committed


def test_peer_and_store_transactions_fail_independently() -> None:
    des = _des()
    protection = des.protect_logical_chunk(
        logical_chunk_id="independent-paths",
        source_dp_rank=0,
        token_count=TOKENS,
        route_version=1,
        peer_control=PathExecutionControl(failed_tp_ranks=frozenset({2})),
    )

    des.run()

    assert protection.peer_hbm.state is PathCommitState.ABORTED
    assert not protection.peer_hbm.capacity_committed
    assert protection.peer_hbm.transaction.terminal_reason == "SHARD_TRANSFER_FAILED:tp=2"
    assert protection.store_dram.state is PathCommitState.COMMITTED
    assert protection.store_dram.capacity_committed
    assert protection.store_dram.byte_audit.valid
    assert des.store_ledger.bytes_in(protection.store_dram.committed_accounts[0]) == SHARD_BYTES
    assert des.capacity_audit().valid


def test_peer_quota_counts_pending_plus_committed_and_rejects_only_peer_path() -> None:
    des = _des()
    des.schedule_algorithm3_control(
        target_dp_rank=1,
        at_ns=0,
        foreground_pressure=True,
        reason="PRIMARY_ALLOCATION_SHORTFALL",
    )
    max_tokens = des.config.model.max_context_tokens
    committed = des.protect_logical_chunk(
        logical_chunk_id="quota-committed",
        source_dp_rank=0,
        token_count=max_tokens,
        route_version=1,
    )
    des.run()

    pressure = des.peer_hbm_pressure()
    assert committed.peer_hbm.capacity_committed
    assert pressure.maximum_usage_bytes == max_tokens * 65_536
    assert des.algorithm3_audit[0].decision.action.value == "MULTIPLICATIVE_DECREASE"
    assert des.algorithm3_audit[0].quota_enforced is True

    rejected = des.protect_logical_chunk(
        logical_chunk_id="quota-rejected",
        source_dp_rank=0,
        token_count=max_tokens,
        route_version=2,
    )
    des.run()
    assert rejected.peer_hbm.state is PathCommitState.ABORTED
    assert rejected.peer_hbm.transaction.terminal_reason == ("PEER_HBM_DYNAMIC_QUOTA_EXCEEDED")
    assert rejected.store_dram.state is PathCommitState.COMMITTED
    assert des.capacity_audit().valid


def test_algorithm3_is_target_local_and_stable_windows_additively_increase() -> None:
    des = _des()
    des.schedule_algorithm3_control(
        target_dp_rank=1,
        at_ns=1,
        foreground_pressure=True,
        reason="PEER_RESERVATION_FAILURE",
    )
    for index in range(1, 5):
        des.schedule_algorithm3_control(
            target_dp_rank=1,
            at_ns=1 + index * des.config.algorithm3.control_window_ns,
            foreground_pressure=False,
            reason="STABLE_WINDOW",
        )

    des.run()

    assert [item.decision.action.value for item in des.algorithm3_audit] == [
        "MULTIPLICATIVE_DECREASE",
        "STABLE_WINDOW",
        "STABLE_WINDOW",
        "STABLE_WINDOW",
        "ADDITIVE_INCREASE",
    ]
    assert des.algorithm3_states[1].protection_fraction == Decimal("0.30")
    assert des.algorithm3_states[2].protection_fraction == Decimal("0.50")
    assert des.peer_hbm_quota_bytes_by_target[1] < des.peer_hbm_quota_bytes_by_target[2]
    assert all(item.quota_enforced for item in des.algorithm3_audit)


def test_algorithm3_stable_updates_reject_non_fixed_window_spacing() -> None:
    des = _des()
    des.schedule_algorithm3_control(
        target_dp_rank=1,
        at_ns=1,
        foreground_pressure=True,
        reason="RECLAIM_STALL",
    )
    des.schedule_algorithm3_control(
        target_dp_rank=1,
        at_ns=2,
        foreground_pressure=False,
        reason="STABLE_WINDOW",
    )

    with pytest.raises(ValueError, match="fixed control window"):
        des.run()


def test_algorithm3_contraction_fails_closed_without_physical_reclaim() -> None:
    des = _des()
    des.protect_logical_chunk(
        logical_chunk_id="occupied-before-contraction",
        source_dp_rank=0,
        token_count=des.config.model.max_context_tokens,
        route_version=1,
    )
    des.run()
    first_pressure_ns = des.des.now_ns + 1
    des.schedule_algorithm3_control(
        target_dp_rank=1,
        at_ns=first_pressure_ns,
        foreground_pressure=True,
        reason="PRIMARY_ALLOCATION_SHORTFALL",
    )
    des.schedule_algorithm3_control(
        target_dp_rank=1,
        at_ns=first_pressure_ns + 1,
        foreground_pressure=True,
        reason="RECLAIM_STALL",
    )

    with pytest.raises(ValueError, match="requires Peer-HBM reclaim"):
        des.run()

    assert len(des.algorithm3_audit) == 1
    assert des.algorithm3_audit[0].quota_enforced is True


def test_group_failure_fences_target_local_algorithm3_state() -> None:
    des = _des()
    des.schedule_algorithm3_control(
        target_dp_rank=1,
        at_ns=1,
        foreground_pressure=True,
        reason="RECLAIM_STALL",
    )
    des.schedule_rank_failure(
        failure_id="target-failure",
        dp_rank=1,
        tp_rank=0,
        at_ns=2,
    )
    des.schedule_algorithm3_control(
        target_dp_rank=1,
        at_ns=100_001,
        foreground_pressure=False,
        reason="STABLE_WINDOW",
    )

    des.run()

    assert 1 in des.algorithm3_fenced_targets
    assert len(des.algorithm3_audit) == 1
    assert des.algorithm3_states[1].protection_fraction == Decimal("0.250")
    assert any(
        row.record_type == "ALGORITHM3_CONTROL_SKIPPED_FENCED" for row in des.des.journal.records
    )


def test_primary_hbm_admission_fails_atomically_at_kv_capable_capacity() -> None:
    des = _des()
    max_tokens = des.config.model.max_context_tokens
    shard_bytes = max_tokens * des.config.model.kv_bytes_per_token_per_tp_rank
    source_ledgers = [des.hbm_ledgers[f"hbm:{rank.resource_id}"] for rank in des.groups[0].ranks]
    admitted = des.config.capacity.rank_hbm.kv_capable_hbm_bytes_per_rank // shard_bytes
    for index in range(admitted):
        des.protect_logical_chunk(
            logical_chunk_id=f"capacity-{index}",
            source_dp_rank=0,
            token_count=max_tokens,
            route_version=index,
            start_ns=index + 1,
        )
    before = tuple(ledger.accounts for ledger in source_ledgers)

    with pytest.raises(ValueError, match="cannot transfer"):
        des.protect_logical_chunk(
            logical_chunk_id="capacity-rejected",
            source_dp_rank=0,
            token_count=max_tokens,
            route_version=admitted,
            start_ns=admitted + 1,
        )

    assert tuple(ledger.accounts for ledger in source_ledgers) == before
    assert des.capacity_audit().valid


def test_one_rank_failure_fences_all_four_ranks_and_preserves_capacity() -> None:
    des = _des()
    _protected(des)
    _fence_source(des)

    assert des.fenced_dp_ranks == {0}
    for rank in des.groups[0].ranks:
        ledger = des.hbm_ledgers[f"hbm:{rank.resource_id}"]
        assert ledger.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT) == (
            des.config.capacity.rank_hbm.kv_capable_hbm_bytes_per_rank
        )
        assert ledger.bytes_in(MODEL_WEIGHTS_ACCOUNT) == (
            des.config.capacity.rank_hbm.model_weights_bytes_per_rank
        )
        assert ledger.bytes_in(RUNTIME_FIXED_ACCOUNT) == (
            des.config.capacity.rank_hbm.runtime_fixed_bytes_per_rank
        )
        assert sum(ledger.accounts.values()) == ledger.capacity_bytes
    fence_record = next(
        record for record in des.des.journal.records if record.record_type == "TP_GROUP_FENCED"
    )
    assert fence_record.data["rank_resource_ids"] == [
        "gpu:node-0:0",
        "gpu:node-0:1",
        "gpu:node-0:2",
        "gpu:node-0:3",
    ]
    assert des.capacity_audit().valid


def test_failure_priority_fences_group_before_same_time_transfer_completion() -> None:
    des = _des()
    protection = des.protect_logical_chunk(
        logical_chunk_id="same-time-failure",
        source_dp_rank=0,
        token_count=TOKENS,
        route_version=1,
    )
    peer_cost = des.config.modeled_costs.cross_node_peer_hbm
    peer_complete_ns = (
        peer_cost.setup_ns
        + (SHARD_BYTES * 1_000_000_000 + peer_cost.effective_bandwidth_bytes_per_second - 1)
        // peer_cost.effective_bandwidth_bytes_per_second
    )
    des.schedule_rank_failure(
        failure_id="same-time",
        dp_rank=0,
        tp_rank=1,
        at_ns=peer_complete_ns,
    )

    des.run()

    assert protection.peer_hbm.state is PathCommitState.ABORTED
    assert protection.store_dram.state is PathCommitState.ABORTED
    assert protection.peer_hbm.transaction.acked_ranks == ()
    assert protection.store_dram.transaction.acked_ranks == ()
    assert des.capacity_audit().valid


def test_peer_recovery_orders_four_shards_barrier_directory_then_forward() -> None:
    des = _des()
    protection = _protected(des)
    _fence_source(des)
    recovery = des.recover_logical_chunk(
        protection,
        pool=PolicyPool.PEER_HBM,
        start_ns=des.des.now_ns,
        directory_install_ns=700,
        first_forward_bytes_per_rank=4096,
    )

    des.run()

    assert recovery.destination_dp_rank == 1
    assert recovery.phase is RecoveryPhase.FORWARD_COMPLETE
    assert recovery.ready_ranks == {0, 1, 2, 3}
    assert recovery.shard_ready_ns is not None
    assert recovery.barrier_complete_ns == (
        recovery.shard_ready_ns + des.config.modeled_costs.tp_collective_sync.fixed_overhead_ns
    )
    assert recovery.directory_installed_ns == recovery.barrier_complete_ns + 700
    assert recovery.forward_start_ns == recovery.directory_installed_ns
    assert recovery.forward_complete_ns is not None
    assert recovery.forward_complete_ns > recovery.forward_start_ns
    assert recovery.byte_audit is not None
    assert recovery.byte_audit.activated_bytes == LOGICAL_BYTES
    assert recovery.byte_audit.source_read_bytes == 0
    assert recovery.byte_audit.kv_reduction_bytes == 0
    assert recovery.byte_audit.model_collective_bytes_excluded == 4 * 4096
    assert recovery.byte_audit.valid

    scheduled = {
        record.data["event_id"]: record.data
        for record in des.des.journal.records
        if record.record_type == "EVENT_SCHEDULED"
    }
    recovery_kinds = [
        EventKind(scheduled[record.data["event_id"]]["kind"])
        for record in des.des.journal.records
        if record.record_type == "EVENT_EXECUTING"
        and scheduled[record.data["event_id"]]["payload"].get("recovery_id") == recovery.recovery_id
    ]
    assert recovery_kinds == [
        EventKind.RECOVERY_START,
        EventKind.GET_COMPLETE,
        EventKind.GET_COMPLETE,
        EventKind.GET_COMPLETE,
        EventKind.GET_COMPLETE,
        EventKind.RECOVERY_COMPLETE,
        EventKind.DIRECTORY_PUBLISH,
        EventKind.FORWARD_START,
        EventKind.FORWARD_COMPLETE,
    ]
    assert des.capacity_audit().valid


def test_peer_recovery_executes_distinct_parallel_rank_activation_times() -> None:
    des = _des()
    protection = _protected(des)
    _fence_source(des)
    start_ns = des.des.now_ns
    recovery = des.recover_logical_chunk(
        protection,
        pool=PolicyPool.PEER_HBM,
        start_ns=start_ns,
        directory_install_ns=700,
        first_forward_bytes_per_rank=4096,
        peer_activation_ns_by_rank=(10, 40, 20, 30),
    )

    des.run()

    assert recovery.rank_ready_ns == {
        0: start_ns + 10,
        1: start_ns + 40,
        2: start_ns + 20,
        3: start_ns + 30,
    }
    assert recovery.shard_ready_ns == start_ns + 40
    assert recovery.phase is RecoveryPhase.FORWARD_COMPLETE


def test_store_recovery_allocates_four_destination_shards_and_keeps_store_copy() -> None:
    des = _des()
    protection = _protected(des)
    _fence_source(des)
    recovery = des.recover_logical_chunk(
        protection,
        pool=PolicyPool.STORE_DRAM,
        destination_dp_rank=2,
        start_ns=des.des.now_ns,
        directory_install_ns=900,
        first_forward_bytes_per_rank=8192,
    )

    des.run()

    assert recovery.phase is RecoveryPhase.FORWARD_COMPLETE
    assert recovery.capacity_committed
    assert recovery.byte_audit is not None
    assert recovery.byte_audit.source_read_bytes == LOGICAL_BYTES
    assert recovery.byte_audit.destination_write_bytes == LOGICAL_BYTES
    assert recovery.byte_audit.activated_bytes == 0
    assert recovery.byte_audit.valid
    for rank in range(4):
        destination = des.capacity_ledgers[recovery.destination_ledger_ids[rank]]
        assert destination.bytes_in(recovery.recovered_accounts[rank]) == SHARD_BYTES
        assert (
            des.store_ledger.bytes_in(protection.store_dram.committed_accounts[rank]) == SHARD_BYTES
        )
    assert des.capacity_audit().valid


def test_sweep_snapshot_stays_modeled_uncalibrated_and_reports_conservation() -> None:
    des = _des()
    protection = _protected(des)

    snapshot = des.sweep_snapshot()

    assert snapshot["evidence_class"] == "modeled_uncalibrated"
    assert snapshot["calibrated"] is False
    assert snapshot["physical_measurement_completed"] is False
    assert snapshot["topology"] == {
        "dp_groups": 8,
        "tp_ranks_per_group": 4,
        "hbm_ledgers": 32,
    }
    assert snapshot["capacity"]["valid"] is True  # type: ignore[index]
    quota = snapshot["peer_hbm_quota"]
    assert quota["controller_integration"] == "per_dp_rank_global_des_aimd"  # type: ignore[index]
    assert quota["quota_bytes_per_rank"] == (  # type: ignore[index]
        des.config.capacity.rank_hbm.peer_hbm_dynamic_quota_upper_bound_bytes_per_rank
    )
    assert quota["maximum_usage_bytes"] == SHARD_BYTES  # type: ignore[index]
    assert quota["maximum_pressure_per_mille"] > 0  # type: ignore[index]
    assert protection.peer_hbm.byte_audit.valid
    assert protection.store_dram.byte_audit.valid
