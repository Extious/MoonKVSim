from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from moonkvsim.aegiskv.recovery_adapter import (
    RECOVERY_DESTINATION_HOLD_ACCOUNT,
    AegisRecoveryAdapter,
    DestinationCapacityRequirement,
    RecoveryAuthorityRequirements,
    RecoveryHoldState,
    RecoveryMappingError,
    RouteSourceAuthority,
)
from moonkvsim.aegiskv.recovery_planner import (
    AegisRecoveryPlanner,
    RecoveryBlockRequirement,
    RecoveryPlanningContext,
    RecoveryPlanningError,
    RecoverySourceKind,
)
from moonkvsim.common.status import KVLocation, ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation import (
    AllocationRole,
    AllocationState,
    PhysicalAllocation,
)
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.store.replica import Replica
from tests.aegiskv._integration_support import AegisEnv, build_env


@dataclass(slots=True)
class SourceMaps:
    resource_kinds: dict[str, CapacityResourceKind] = field(default_factory=dict)
    resident_targets: dict[str, str] = field(default_factory=dict)
    route_authorities: dict[str, RouteSourceAuthority] = field(default_factory=dict)


def _identity(index: int) -> KVIdentity:
    token_start = index * 16
    return KVIdentity(
        tenant_id="tenant-recovery",
        model_id="Qwen/Qwen3-8B",
        model_revision="revision",
        kv_dtype="bf16",
        kv_abi="vllm-v1",
        kv_layout="tp1-pp1",
        tp_size=1,
        pp_size=1,
        block_size_tokens=16,
        stable_block_hash=f"recovery-hash-{index}",
        token_start=token_start,
        token_end=token_start + 16,
        shard_id="tp0",
        request_id="recovery-request",
        session_id="recovery-session",
        workflow_id="recovery-workflow",
        route_version=0,
        source_gpu_id="failed-lineage-gpu",
    )


def _context(*, timestamp_ns: int = 0) -> RecoveryPlanningContext:
    return RecoveryPlanningContext(
        request_id="recovery-request",
        failure_id="gpu-failure-0",
        parent_route_version=0,
        recovery_route_version=1,
        source_target_id="failed-engine",
        destination_target_id="healthy-engine",
        failed_target_ids=("failed-engine",),
        failed_gpu_ids=("failed-lineage-gpu",),
        unavailable_resource_ids=("failed-hbm",),
        required_shard_ids=("tp0",),
        timestamp_ns=timestamp_ns,
    )


def _planner() -> AegisRecoveryPlanner:
    return AegisRecoveryPlanner(
        source_preference=(RecoverySourceKind.PEER_HBM, RecoverySourceKind.STORE_DRAM)
    )


def _add_source(
    env: AegisEnv,
    maps: SourceMaps,
    identity: KVIdentity,
    *,
    source_kind: RecoverySourceKind,
    replica_id: str,
    resident_target: str,
    allocation_count: int = 1,
    expected_shard_ids: tuple[str, ...] = ("tp0",),
) -> tuple[str, ...]:
    object_id = env.master.directory.register_object(identity)
    location = (
        KVLocation.PEER_HBM
        if source_kind is RecoverySourceKind.PEER_HBM
        else KVLocation.STORE_DRAM
    )
    resource_kind = (
        CapacityResourceKind.GPU_HBM
        if source_kind is RecoverySourceKind.PEER_HBM
        else CapacityResourceKind.STORE_DRAM
    )
    allocation_ids: list[str] = []
    for index in range(allocation_count):
        allocation_id = f"{replica_id}:allocation:{index}"
        resource_id = f"{replica_id}:resource:{index}"
        env.registry.add(
            PhysicalAllocation(
                allocation_id=allocation_id,
                object_id=object_id,
                replica_id=replica_id,
                resource_id=resource_id,
                owner_account=f"{source_kind.value}_COMMITTED",
                payload_bytes=64,
                requested_bytes=64,
                allocated_bytes=64,
                padding_bytes=0,
                allocator_metadata_bytes=0,
                internal_fragmentation_bytes=0,
                alignment_bytes=64,
                state=AllocationState.COMMITTED,
                created_at_ns=0,
                roles=frozenset({AllocationRole.FAILURE_PROTECTION}),
            ),
            timestamp_ns=0,
            event_id=f"{allocation_id}:add",
        )
        env.registry.set_recovery_eligible(
            allocation_id,
            True,
            timestamp_ns=0,
            event_id=f"{allocation_id}:eligible",
        )
        allocation_ids.append(allocation_id)
        maps.resource_kinds[resource_id] = resource_kind
        maps.resident_targets[resource_id] = resident_target
    env.master.directory.add_replica(
        Replica(
            replica_id=replica_id,
            object_id=object_id,
            location=location,
            allocation_ids=tuple(allocation_ids),
            expected_shard_ids=expected_shard_ids,
            completed_shard_ids=frozenset(expected_shard_ids),
            state=ReplicaState.COMMITTED,
            generation=0,
            route_version=identity.route_version,
            created_at_ns=0,
            published_at_ns=0,
        )
    )
    maps.route_authorities[replica_id] = RouteSourceAuthority(
        route_version=identity.route_version,
        authoritative=True,
        source_lineage_gpu_id=identity.source_gpu_id,
    )
    return tuple(allocation_ids)


def _authority(
    identities: tuple[KVIdentity, ...],
    maps: SourceMaps,
) -> RecoveryAuthorityRequirements:
    identities_by_object_id = {identity.object_id: identity for identity in identities}
    return RecoveryAuthorityRequirements(
        identities_by_object_id=identities_by_object_id,
        requirements_by_object_id={
            object_id: RecoveryBlockRequirement.from_identity(identity)
            for object_id, identity in identities_by_object_id.items()
        },
        resource_kind_by_resource_id=maps.resource_kinds,
        resident_target_by_resource_id=maps.resident_targets,
        route_authority_by_replica_id=maps.route_authorities,
    )


def test_exact_tp1_peer_and_store_candidates_come_from_single_shared_truth() -> None:
    env = build_env()
    maps = SourceMaps()
    block = _identity(0)
    _add_source(
        env,
        maps,
        block,
        source_kind=RecoverySourceKind.PEER_HBM,
        replica_id="peer-0",
        resident_target="healthy-peer-engine",
    )
    _add_source(
        env,
        maps,
        block,
        source_kind=RecoverySourceKind.STORE_DRAM,
        replica_id="store-0",
        resident_target="global-store",
    )
    adapter = AegisRecoveryAdapter(directory=env.directory)

    candidates = adapter.build_candidates(_authority((block,), maps))[block.object_id]

    assert adapter.directory is env.directory
    assert env.directory.directory is env.master.directory
    assert env.directory.allocation_registry is env.registry
    assert {candidate.source_kind for candidate in candidates} == {
        RecoverySourceKind.PEER_HBM,
        RecoverySourceKind.STORE_DRAM,
    }
    assert all(candidate.expected_shard_ids == ("tp0",) for candidate in candidates)
    assert all(len(candidate.shards) == 1 for candidate in candidates)
    assert all(candidate.shards[0].recovery_eligible for candidate in candidates)


def test_failed_residence_is_distinct_from_failed_source_lineage_and_store_is_isolated() -> None:
    env = build_env()
    maps = SourceMaps()
    block = _identity(0)
    _add_source(
        env,
        maps,
        block,
        source_kind=RecoverySourceKind.PEER_HBM,
        replica_id="peer-failed-residence",
        resident_target="failed-engine",
    )
    _add_source(
        env,
        maps,
        block,
        source_kind=RecoverySourceKind.STORE_DRAM,
        replica_id="store-healthy-residence",
        resident_target="global-store",
    )
    adapter = AegisRecoveryAdapter(directory=env.directory)
    candidates = adapter.build_candidates(_authority((block,), maps))

    plan = _planner().plan((block,), candidates_by_object_id=candidates, context=_context())

    assert plan.blocks[0].source_kind is RecoverySourceKind.STORE_DRAM
    assert plan.blocks[0].resident_target_id == "global-store"
    assert plan.blocks[0].source_lineage_gpu_id == "failed-lineage-gpu"


def test_mixed_peer_store_gap_becomes_one_continuous_recompute_suffix() -> None:
    env = build_env()
    maps = SourceMaps()
    blocks = tuple(_identity(index) for index in range(4))
    _add_source(
        env,
        maps,
        blocks[0],
        source_kind=RecoverySourceKind.PEER_HBM,
        replica_id="peer-block-0",
        resident_target="healthy-peer-engine",
    )
    _add_source(
        env,
        maps,
        blocks[1],
        source_kind=RecoverySourceKind.STORE_DRAM,
        replica_id="store-block-1",
        resident_target="global-store",
    )
    # Block 2 is intentionally missing.  Block 3 must still be recomputed.
    _add_source(
        env,
        maps,
        blocks[3],
        source_kind=RecoverySourceKind.PEER_HBM,
        replica_id="peer-block-3",
        resident_target="healthy-peer-engine",
    )
    adapter = AegisRecoveryAdapter(directory=env.directory)
    candidates = adapter.build_candidates(_authority(blocks, maps))

    plan = _planner().plan(blocks, candidates_by_object_id=candidates, context=_context())

    assert tuple(block.source_kind for block in plan.blocks) == (
        RecoverySourceKind.PEER_HBM,
        RecoverySourceKind.STORE_DRAM,
        RecoverySourceKind.RECOMPUTE,
        RecoverySourceKind.RECOMPUTE,
    )
    assert plan.missing_suffix_start_block == 2


def test_revalidation_reads_fresh_eligibility_and_rejects_disappeared_selection() -> None:
    env = build_env()
    maps = SourceMaps()
    block = _identity(0)
    (allocation_id,) = _add_source(
        env,
        maps,
        block,
        source_kind=RecoverySourceKind.PEER_HBM,
        replica_id="peer-revalidate",
        resident_target="healthy-peer-engine",
    )
    adapter = AegisRecoveryAdapter(directory=env.directory)
    authority = _authority((block,), maps)
    planner = _planner()
    context = _context()
    plan = planner.plan(
        (block,),
        candidates_by_object_id=adapter.build_candidates(authority),
        context=context,
    )
    env.registry.set_recovery_eligible(
        allocation_id,
        False,
        timestamp_ns=1,
        event_id="revalidation-revoke",
    )

    with pytest.raises(RecoveryPlanningError, match="changed or disappeared"):
        adapter.revalidate_plan(planner, plan, context=context, authority=authority)


def test_ambiguous_multi_allocation_replica_fails_closed_without_zip_guessing() -> None:
    env = build_env()
    maps = SourceMaps()
    block = _identity(0)
    _add_source(
        env,
        maps,
        block,
        source_kind=RecoverySourceKind.PEER_HBM,
        replica_id="peer-ambiguous",
        resident_target="healthy-peer-engine",
        allocation_count=2,
    )
    adapter = AegisRecoveryAdapter(directory=env.directory)

    with pytest.raises(RecoveryMappingError, match="ambiguous multi-shard/allocation"):
        adapter.build_candidates(_authority((block,), maps))


def _two_path_plan() -> tuple[
    AegisEnv,
    SourceMaps,
    tuple[KVIdentity, KVIdentity],
    AegisRecoveryAdapter,
    RecoveryAuthorityRequirements,
    AegisRecoveryPlanner,
    RecoveryPlanningContext,
]:
    env = build_env()
    maps = SourceMaps()
    blocks = (_identity(0), _identity(1))
    _add_source(
        env,
        maps,
        blocks[0],
        source_kind=RecoverySourceKind.PEER_HBM,
        replica_id="peer-hold",
        resident_target="healthy-peer-engine",
    )
    _add_source(
        env,
        maps,
        blocks[1],
        source_kind=RecoverySourceKind.STORE_DRAM,
        replica_id="store-hold",
        resident_target="global-store",
    )
    adapter = AegisRecoveryAdapter(directory=env.directory)
    authority = _authority(blocks, maps)
    planner = _planner()
    context = _context()
    return env, maps, blocks, adapter, authority, planner, context


def test_peer_store_holds_commit_abort_independently_without_pin_or_capacity_leak() -> None:
    env, _, blocks, adapter, authority, planner, context = _two_path_plan()
    plan = planner.plan(
        blocks,
        candidates_by_object_id=adapter.build_candidates(authority),
        context=context,
    )
    destination = CapacityLedger(
        resource_id="destination-hbm",
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=1_000,
    )
    ledgers = {destination.resource_id: destination}
    des = GlobalDES(journal=env.journal)
    des.run(until_ns=1)
    peer_path = adapter.prepare(
        "recovery-op",
        plan,
        path_kind=RecoverySourceKind.PEER_HBM,
        destination=DestinationCapacityRequirement(
            path_kind=RecoverySourceKind.PEER_HBM,
            destination_resource_id=destination.resource_id,
            destination_resource_kind=CapacityResourceKind.GPU_HBM,
            destination_target_id=context.destination_target_id,
            allocated_bytes=100,
            committed_account="RECOVERY_PEER_COMMITTED",
        ),
        planner=planner,
        context=context,
        authority=authority,
        ledgers=ledgers,
        timestamp_ns=des.now_ns,
    )
    store_path = adapter.prepare(
        "recovery-op",
        plan,
        path_kind=RecoverySourceKind.STORE_DRAM,
        destination=DestinationCapacityRequirement(
            path_kind=RecoverySourceKind.STORE_DRAM,
            destination_resource_id=destination.resource_id,
            destination_resource_kind=CapacityResourceKind.GPU_HBM,
            destination_target_id=context.destination_target_id,
            allocated_bytes=200,
            committed_account="RECOVERY_STORE_COMMITTED",
        ),
        planner=planner,
        context=context,
        authority=authority,
        ledgers=ledgers,
        timestamp_ns=des.now_ns,
    )
    peer_allocation = peer_path.source_allocation_ids[0]
    store_allocation = store_path.source_allocation_ids[0]
    assert destination.bytes_in(peer_path.hold_account) == 100
    assert destination.bytes_in(store_path.hold_account) == 200
    assert env.registry.overlay(peer_allocation).source_pin_count == 1
    assert env.registry.overlay(store_allocation).source_pin_count == 1

    des.run(until_ns=2)
    store_path = adapter.abort(
        "recovery-op",
        RecoverySourceKind.STORE_DRAM,
        ledgers=ledgers,
        timestamp_ns=des.now_ns,
    )
    assert store_path.state is RecoveryHoldState.ABORTED
    assert env.registry.overlay(store_allocation).source_pin_count == 0
    assert env.registry.overlay(peer_allocation).source_pin_count == 1
    assert destination.bytes_in(store_path.hold_account) == 0
    assert destination.bytes_in(peer_path.hold_account) == 100

    peer_path = adapter.commit(
        "recovery-op",
        RecoverySourceKind.PEER_HBM,
        ledgers=ledgers,
        timestamp_ns=des.now_ns,
    )
    assert peer_path.state is RecoveryHoldState.COMMITTED
    assert env.registry.overlay(peer_allocation).source_pin_count == 0
    assert destination.bytes_in(peer_path.hold_account) == 0
    assert destination.bytes_in("RECOVERY_PEER_COMMITTED") == 100
    assert destination.bytes_in("RECOVERY_STORE_COMMITTED") == 0


def test_failed_destination_hold_preflight_does_not_leak_source_pin_or_capacity() -> None:
    env, _, blocks, adapter, authority, planner, context = _two_path_plan()
    plan = planner.plan(
        blocks,
        candidates_by_object_id=adapter.build_candidates(authority),
        context=context,
    )
    destination = CapacityLedger(
        resource_id="small-destination-hbm",
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=64,
    )
    peer_source = plan.blocks[0].shards[0].allocation_id

    with pytest.raises(ValueError, match="cannot transfer"):
        adapter.prepare(
            "capacity-failure",
            plan,
            path_kind=RecoverySourceKind.PEER_HBM,
            destination=DestinationCapacityRequirement(
                path_kind=RecoverySourceKind.PEER_HBM,
                destination_resource_id=destination.resource_id,
                destination_resource_kind=CapacityResourceKind.GPU_HBM,
                destination_target_id=context.destination_target_id,
                allocated_bytes=128,
                committed_account="RECOVERY_COMMITTED",
            ),
            planner=planner,
            context=context,
            authority=authority,
            ledgers={destination.resource_id: destination},
            timestamp_ns=1,
        )

    assert env.registry.overlay(peer_source).source_pin_count == 0
    assert sum(
        value
        for account, value in destination.accounts.items()
        if account.startswith(RECOVERY_DESTINATION_HOLD_ACCOUNT)
    ) == 0
    assert destination.bytes_in("FREE") == destination.capacity_bytes
    with pytest.raises(KeyError, match="unknown recovery path"):
        adapter.path("capacity-failure", RecoverySourceKind.PEER_HBM)
