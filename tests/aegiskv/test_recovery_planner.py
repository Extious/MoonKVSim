from __future__ import annotations

from dataclasses import replace

import pytest

from moonkvsim.aegiskv.recovery_planner import (
    AegisRecoveryPlanner,
    RecoveryBlockRequirement,
    RecoveryCandidate,
    RecoveryPlanningContext,
    RecoveryPlanningError,
    RecoveryShardCandidate,
    RecoverySourceKind,
)
from moonkvsim.common.hash import canonical_json_bytes, sha256_json
from moonkvsim.common.types import KVIdentity


def identity(index: int, *, kv_abi: str = "vllm-v1", token_count: int = 16) -> KVIdentity:
    token_start = index * 16
    return KVIdentity(
        tenant_id="tenant-0",
        model_id="Qwen/Qwen3-8B",
        model_revision="revision",
        kv_dtype="bf16",
        kv_abi=kv_abi,
        kv_layout="tp2-pp1",
        tp_size=2,
        pp_size=1,
        block_size_tokens=16,
        stable_block_hash=f"hash-{index}",
        token_start=token_start,
        token_end=token_start + token_count,
        shard_id="cache-group-0",
        request_id="request-0",
        session_id="session-0",
        workflow_id="workflow-0",
        route_version=0,
        source_gpu_id="node-0.gpu-1",
    )


def context() -> RecoveryPlanningContext:
    return RecoveryPlanningContext(
        request_id="request-0",
        failure_id="failure-0",
        parent_route_version=0,
        recovery_route_version=1,
        source_target_id="engine-dp1",
        destination_target_id="engine-dp0",
        failed_target_ids=("engine-dp1",),
        failed_gpu_ids=("node-0.gpu-1",),
        unavailable_resource_ids=("gpu1.hbm",),
        required_shard_ids=("tp0", "tp1"),
        timestamp_ns=14_641_778_519,
    )


def candidate(
    block: KVIdentity,
    replica_id: str,
    source_kind: RecoverySourceKind,
    *,
    target_id: str | None = None,
    state: str = "COMMITTED",
    visible: bool = True,
    authoritative: bool = True,
    completed_shards: tuple[str, ...] = ("tp0", "tp1"),
    compatibility_key: tuple[str | int, ...] | None = None,
    source_gpu_id: str = "node-0.gpu-0",
    generation: int = 0,
) -> RecoveryCandidate:
    requirement = RecoveryBlockRequirement.from_identity(block)
    resource_kind = "GPU_HBM" if source_kind is RecoverySourceKind.PEER_HBM else "STORE_DRAM"
    target = target_id or (
        "engine-dp0" if source_kind is RecoverySourceKind.PEER_HBM else "store-pool-0"
    )
    resource_prefix = "gpu0.hbm" if source_kind is RecoverySourceKind.PEER_HBM else "store0"
    shards = tuple(
        RecoveryShardCandidate(
            shard_id=shard_id,
            allocation_id=f"{replica_id}-{shard_id}",
            resource_id=f"{resource_prefix}.{shard_id}",
            resource_kind=resource_kind,
            allocation_state="COMMITTED",
            recovery_eligible=True,
            object_id=requirement.object_id,
            replica_id=replica_id,
        )
        for shard_id in ("tp0", "tp1")
    )
    return RecoveryCandidate(
        replica_id=replica_id,
        object_id=requirement.object_id,
        source_kind=source_kind,
        location=source_kind.value,
        state=state,
        visible=visible,
        generation=generation,
        source_route_version=0,
        source_route_authoritative=authoritative,
        compatibility_key=compatibility_key or requirement.compatibility_key,
        resident_target_id=target,
        expected_shard_ids=("tp0", "tp1"),
        completed_shard_ids=completed_shards,
        shards=shards,
        source_lineage_gpu_id=source_gpu_id,
    )


def planner() -> AegisRecoveryPlanner:
    return AegisRecoveryPlanner(
        source_preference=(RecoverySourceKind.PEER_HBM, RecoverySourceKind.STORE_DRAM)
    )


def test_mixed_prefix_stops_at_first_gap_and_recomputes_all_later_blocks() -> None:
    blocks = tuple(identity(index) for index in range(4))
    candidates = {
        blocks[0].object_id: (
            candidate(blocks[0], "peer-0", RecoverySourceKind.PEER_HBM),
            candidate(blocks[0], "store-0", RecoverySourceKind.STORE_DRAM),
        ),
        blocks[1].object_id: (candidate(blocks[1], "store-1", RecoverySourceKind.STORE_DRAM),),
        # block 2 is the gap.  A valid block 3 source must still be ignored.
        blocks[3].object_id: (candidate(blocks[3], "peer-3", RecoverySourceKind.PEER_HBM),),
    }

    plan = planner().plan(blocks, candidates_by_object_id=candidates, context=context())

    assert tuple(block.source_kind for block in plan.blocks) == (
        RecoverySourceKind.PEER_HBM,
        RecoverySourceKind.STORE_DRAM,
        RecoverySourceKind.RECOMPUTE,
        RecoverySourceKind.RECOMPUTE,
    )
    assert plan.missing_suffix_start_block == 2
    assert plan.peer_hbm_tokens == 16
    assert plan.store_dram_tokens == 16
    assert plan.recompute_tokens == 32
    assert plan.restored_tokens == 32
    assert plan.canonical_fields()["capacity_hold_contract"] == {
        "activation_requires_all_shards": True,
        "destination_hold_before_transfer": True,
        "source_pin_before_transfer": True,
    }


def test_failed_residence_is_excluded_but_failed_source_lineage_is_not() -> None:
    block = identity(0)
    failed_residence = candidate(
        block,
        "peer-a-failed-residence",
        RecoverySourceKind.PEER_HBM,
        target_id="engine-dp1",
    )
    healthy_residence_failed_lineage = candidate(
        block,
        "peer-b-healthy-residence",
        RecoverySourceKind.PEER_HBM,
        target_id="engine-dp0",
        source_gpu_id="node-0.gpu-1",
    )

    plan = planner().plan(
        (block,),
        candidates_by_object_id={
            block.object_id: (failed_residence, healthy_residence_failed_lineage)
        },
        context=context(),
    )

    assert plan.blocks[0].replica_id == "peer-b-healthy-residence"
    assert plan.blocks[0].source_lineage_gpu_id == "node-0.gpu-1"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda item: replace(item, state="PENDING"),
        lambda item: replace(item, visible=False),
        lambda item: replace(item, source_route_authoritative=False),
        lambda item: replace(item, completed_shard_ids=("tp0",)),
        lambda item: replace(item, compatibility_key=(*item.compatibility_key[:-1], "wrong")),
        lambda item: replace(
            item,
            shards=(replace(item.shards[0], resource_kind="STORE_DRAM"), item.shards[1]),
        ),
    ],
)
def test_pending_route_shard_or_abi_layout_mismatch_recomputes_fail_closed(mutator: object) -> None:
    block = identity(0)
    base = candidate(block, "peer-0", RecoverySourceKind.PEER_HBM)
    changed = mutator(base)  # type: ignore[operator]

    plan = planner().plan(
        (block,),
        candidates_by_object_id={block.object_id: (changed,)},
        context=context(),
    )

    assert plan.missing_suffix_start_block == 0
    assert plan.blocks[0].source_kind is RecoverySourceKind.RECOMPUTE


def test_required_blocks_with_different_abi_fail_before_selection() -> None:
    first = identity(0)
    incompatible = identity(1, kv_abi="another-abi")

    with pytest.raises(RecoveryPlanningError, match="ABI/layout"):
        planner().plan(
            (first, incompatible),
            candidates_by_object_id={},
            context=context(),
        )


def test_candidate_cannot_relabel_peer_hbm_as_store_dram() -> None:
    block = identity(0)
    peer = candidate(block, "peer-0", RecoverySourceKind.PEER_HBM)

    with pytest.raises(RecoveryPlanningError, match="authoritative directory location"):
        replace(
            peer,
            source_kind=RecoverySourceKind.STORE_DRAM,
            # Retaining the raw directory location makes the attempted relabel
            # fail before failed-target filtering can be bypassed.
            location="PEER_HBM",
        )


def test_partial_block_starts_recompute_suffix() -> None:
    partial = identity(0, token_count=8)
    next_block = replace(identity(1), token_start=8, token_end=24)
    requirements = (
        RecoveryBlockRequirement.from_identity(partial),
        RecoveryBlockRequirement.from_identity(next_block),
    )

    plan = planner().plan(
        requirements,
        candidates_by_object_id={},
        context=context(),
    )

    assert plan.missing_suffix_start_block == 0
    assert all(block.source_kind is RecoverySourceKind.RECOMPUTE for block in plan.blocks)


def test_revalidation_ignores_new_better_candidate_but_rejects_changed_selection() -> None:
    block = identity(0)
    store = candidate(block, "store-0", RecoverySourceKind.STORE_DRAM)
    selected = {block.object_id: (store,)}
    recovery_planner = planner()
    plan = recovery_planner.plan((block,), candidates_by_object_id=selected, context=context())
    newly_available_peer = candidate(block, "peer-0", RecoverySourceKind.PEER_HBM)

    recovery_planner.validate_selected_sources(
        plan,
        candidates_by_object_id={block.object_id: (newly_available_peer, store)},
        context=context(),
    )
    with pytest.raises(RecoveryPlanningError, match="changed or disappeared"):
        recovery_planner.validate_selected_sources(
            plan,
            candidates_by_object_id={
                block.object_id: (replace(store, generation=1), newly_available_peer)
            },
            context=context(),
        )


def test_plan_json_and_fingerprint_are_canonical() -> None:
    block = identity(0)
    source = candidate(block, "peer-0", RecoverySourceKind.PEER_HBM)
    plan = planner().plan(
        (block,),
        candidates_by_object_id={block.object_id: (source,)},
        context=context(),
    )

    document = plan.to_dict()
    canonical = {key: value for key, value in document.items() if key != "fingerprint"}
    assert document["fingerprint"] == sha256_json(canonical)
    assert plan.to_json_bytes() == canonical_json_bytes(document) + b"\n"
