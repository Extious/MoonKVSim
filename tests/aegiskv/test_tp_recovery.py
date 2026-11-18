import pytest

from moonkvsim.aegiskv.tp_recovery import (
    TPChunkPathTransaction,
    TPCollectiveKind,
    TPLayoutIdentity,
    TPShardPlacement,
)
from moonkvsim.aegiskv.types import PathCommitState, PolicyPool


def _layout() -> TPLayoutIdentity:
    return TPLayoutIdentity(
        model_revision="qwen3-32b-revision",
        kv_abi="vllm-bf16-tp4",
        layout_id="qwen3-32b-tp4",
        tensor_parallel_size=4,
    )


def _transaction() -> TPChunkPathTransaction:
    return TPChunkPathTransaction(
        transaction_id="tx-0",
        logical_chunk_id="request-0:chunk-0",
        pool=PolicyPool.PEER_HBM,
        route_version=3,
        layout=_layout(),
        shards=tuple(
            TPShardPlacement(
                tp_rank=rank,
                source_gpu_id=f"source-gpu-{rank}",
                protection_resource_id=f"standby-gpu-{rank}.hbm",
                allocated_bytes=1024,
            )
            for rank in range(4)
        ),
    )


def test_logical_chunk_commits_only_after_every_tp_shard_ack() -> None:
    transaction = _transaction()

    for rank in range(3):
        assert not transaction.acknowledge_shard(
            rank,
            timestamp_ns=10 + rank,
            route_version=3,
            layout=_layout(),
        )
        assert transaction.state is PathCommitState.PENDING

    assert transaction.acknowledge_shard(
        3,
        timestamp_ns=20,
        route_version=3,
        layout=_layout(),
    )
    assert transaction.state is PathCommitState.COMMITTED
    assert transaction.acked_ranks == (0, 1, 2, 3)
    assert transaction.committed_at_ns == 20


def test_route_or_layout_mismatch_aborts_the_whole_path() -> None:
    transaction = _transaction()

    assert not transaction.acknowledge_shard(
        0,
        timestamp_ns=10,
        route_version=4,
        layout=_layout(),
    )

    assert transaction.state is PathCommitState.ABORTED
    assert transaction.terminal_reason == "ROUTE_OR_LAYOUT_MISMATCH"


def test_partial_shard_path_is_not_recovery_eligible() -> None:
    transaction = _transaction()
    transaction.acknowledge_shard(
        0,
        timestamp_ns=10,
        route_version=3,
        layout=_layout(),
    )

    with pytest.raises(ValueError, match="all-shard"):
        transaction.build_recovery_plan(
            route_version=3,
            layout=_layout(),
            destination_gpu_ids=tuple(f"target-gpu-{rank}" for rank in range(4)),
            nvlink_rate_resource_id="node-0.nvlink",
            model_all_reduce_bytes_per_rank=4096,
        )


def test_recovery_keeps_rank_shards_distinct_and_models_collectives() -> None:
    transaction = _transaction()
    for rank in range(4):
        transaction.acknowledge_shard(
            rank,
            timestamp_ns=10 + rank,
            route_version=3,
            layout=_layout(),
        )

    plan = transaction.build_recovery_plan(
        route_version=3,
        layout=_layout(),
        destination_gpu_ids=tuple(f"target-gpu-{rank}" for rank in range(4)),
        nvlink_rate_resource_id="target-node.nvlink",
        model_all_reduce_bytes_per_rank=4096,
    )

    assert plan.rank_sources == tuple(
        (rank, f"standby-gpu-{rank}.hbm") for rank in range(4)
    )
    assert plan.rank_destinations == tuple(
        (rank, f"target-gpu-{rank}") for rank in range(4)
    )
    assert not plan.kv_shards_are_reduced
    assert tuple(item.kind for item in plan.collectives) == (
        TPCollectiveKind.ACTIVATION_BARRIER,
        TPCollectiveKind.MODEL_ALL_REDUCE,
    )


def test_transaction_requires_exactly_one_shard_per_tp_rank() -> None:
    with pytest.raises(ValueError, match="every TP rank"):
        TPChunkPathTransaction(
            transaction_id="tx-0",
            logical_chunk_id="request-0:chunk-0",
            pool=PolicyPool.STORE_DRAM,
            route_version=0,
            layout=_layout(),
            shards=tuple(
                TPShardPlacement(
                    tp_rank=rank,
                    source_gpu_id=f"source-gpu-{rank}",
                    protection_resource_id=f"store-shard-{rank}",
                    allocated_bytes=1024,
                )
                for rank in range(3)
            ),
        )
