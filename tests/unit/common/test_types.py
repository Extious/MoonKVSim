from dataclasses import replace

import pytest

from moonkvsim.common.status import KVLocation, ReplicaState
from moonkvsim.common.types import KVIdentity


def identity() -> KVIdentity:
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
        stable_block_hash="abc123",
        token_start=0,
        token_end=16,
        shard_id="tp0.pp0",
        request_id="request-0",
        session_id="session-0",
        workflow_id="workflow-0",
        route_version=0,
        source_gpu_id="node-0.gpu-0",
    )


def test_content_hash_is_cross_route_stable_but_lineage_is_not() -> None:
    first = identity()
    second = identity()
    rerouted = replace(second, route_version=1, source_gpu_id="node-0.gpu-1")

    assert first.object_id == second.object_id
    assert first.object_id == rerouted.object_id
    assert first.lineage_record_id != rerouted.lineage_record_id
    assert len(first.object_id) == 67


def test_invalid_token_interval_fails_closed() -> None:
    fields = identity().canonical_fields()
    fields["token_end"] = 17
    with pytest.raises(ValueError, match="one declared block"):
        KVIdentity(**fields)


def test_main_location_enum_has_no_peer_or_persistent_tier() -> None:
    assert {location.value for location in KVLocation} == {"PRIMARY_HBM", "STORE_DRAM"}
    assert ReplicaState.PENDING.visible is False
    assert ReplicaState.COMMITTED.visible is True
