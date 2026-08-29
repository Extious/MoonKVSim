from dataclasses import replace

import pytest

from moonkvsim.common.status import KVLocation, ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.store.metadata_store import GlobalKVDirectory
from moonkvsim.store.replica import Replica


def identity(*, block_hash: str = "hash-0", token_start: int = 0) -> KVIdentity:
    return KVIdentity(
        tenant_id="tenant-0",
        model_id="Qwen/Qwen3-8B",
        model_revision="revision",
        kv_dtype="bf16",
        kv_abi="vllm-v1",
        kv_layout="tp2-pp1",
        tp_size=2,
        pp_size=1,
        block_size_tokens=16,
        stable_block_hash=block_hash,
        token_start=token_start,
        token_end=token_start + 16,
        shard_id="cache-group-0",
        request_id="request-0",
        session_id="session-0",
        workflow_id="workflow-0",
        route_version=0,
        source_gpu_id="node-0.gpu-0",
    )


def replica(object_id: str) -> Replica:
    return Replica(
        replica_id="replica-0",
        object_id=object_id,
        location=KVLocation.STORE_DRAM,
        allocation_ids=("alloc-tp0", "alloc-tp1"),
        expected_shard_ids=("tp0", "tp1"),
        completed_shard_ids=frozenset(),
        state=ReplicaState.ALLOCATED,
        generation=0,
        route_version=0,
        created_at_ns=0,
    )


def test_pending_is_invisible_and_publish_requires_all_shards() -> None:
    directory = GlobalKVDirectory()
    kv = identity()
    object_id = directory.register_object(kv)
    pending = replica(object_id).start_pending().complete_shard("tp0")
    directory.add_replica(pending)

    assert directory.query(kv) == ()
    with pytest.raises(ValueError, match="all expected shards"):
        pending.commit()

    committed = pending.complete_shard("tp1").commit()
    directory.update_replica(committed)
    assert directory.query(kv) == ()

    published = committed.publish(timestamp_ns=10)
    directory.update_replica(published)
    assert directory.query(kv) == (published,)


def test_cross_route_lookup_uses_content_identity() -> None:
    directory = GlobalKVDirectory()
    source = identity()
    object_id = directory.register_object(source)
    committed = (
        replica(object_id)
        .start_pending()
        .complete_shard("tp0")
        .complete_shard("tp1")
        .commit()
        .publish(timestamp_ns=1)
    )
    directory.add_replica(committed)
    rerouted = replace(
        source,
        request_id="request-1",
        route_version=1,
        source_gpu_id="node-1.gpu-0",
    )

    assert directory.register_object(rerouted) == object_id
    assert directory.query(rerouted) == (committed,)


def test_continuous_prefix_stops_at_first_miss() -> None:
    directory = GlobalKVDirectory()
    first = identity(block_hash="hash-0", token_start=0)
    second = identity(block_hash="hash-1", token_start=16)
    third = identity(block_hash="hash-2", token_start=32)
    first_id = directory.register_object(first)
    first_replica = (
        replica(first_id)
        .start_pending()
        .complete_shard("tp0")
        .complete_shard("tp1")
        .commit()
        .publish(timestamp_ns=1)
    )
    directory.add_replica(first_replica)
    directory.register_object(third)

    prefix = directory.query_committed_prefix([first, second, third])

    assert tuple(item[0] for item in prefix) == (first,)


def test_one_physical_allocation_cannot_back_two_replicas() -> None:
    directory = GlobalKVDirectory()
    kv = identity()
    object_id = directory.register_object(kv)
    first = replica(object_id)
    directory.add_replica(first)

    with pytest.raises(ValueError, match="cannot back multiple replicas"):
        directory.add_replica(replace(first, replica_id="replica-1"))
