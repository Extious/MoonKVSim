from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from moonkvsim.common.hash import canonical_json_bytes, sha256_json
from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.hbm_block_ledger import (
    HBM_KV_ACTIVE_ACCOUNT,
    HBM_KV_INACTIVE_ACCOUNT,
    HBM_KV_RESERVED_ACCOUNT,
    HBM_RECOVERY_RESERVED_ACCOUNT,
    HbmBlockLedgerBridge,
    HbmStageRankBinding,
    load_hbm_stage_rank_bindings,
)
from moonkvsim.integration.vllm.kv_layout import StageBlockLayout
from moonkvsim.integration.vllm.request import Request, RequestStatus
from moonkvsim.integration.vllm.scheduler import ContinuousBatchScheduler
from moonkvsim.recovery import AtomicGPUHBMFailStop
from moonkvsim.simulation.allocation import AllocationRole, AllocationState
from moonkvsim.simulation.allocation_registry import (
    AllocationRegistry,
    replay_allocation_registry,
)
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import (
    FREE_ACCOUNT,
    UNAVAILABLE_CAPACITY_ACCOUNT,
    CapacityLedger,
    CapacityResourceKind,
)
from moonkvsim.simulation.replay import replay_capacity_transactions


def _layout(*, pp_stage: int, tp_rank: int, allocated_bytes: int) -> StageBlockLayout:
    payload_bytes = allocated_bytes - 12
    return StageBlockLayout(
        pp_stage=pp_stage,
        tensor_parallel_rank=tp_rank,
        block_size_tokens=4,
        layer_names=(f"model.layers.{pp_stage}.self_attn",),
        layer_indices=(pp_stage,),
        tensor_payload_bytes=payload_bytes - 4,
        auxiliary_payload_bytes=4,
        payload_bytes=payload_bytes,
        layout_padding_bytes=4,
        allocator_metadata_bytes=2,
        requested_bytes=payload_bytes + 4,
        internal_fragmentation_bytes=6,
        allocated_bytes=allocated_bytes,
        allocator_alignment_bytes=8,
    )


@dataclass(slots=True)
class _Scenario:
    bridge: HbmBlockLedgerBridge
    ledgers: dict[str, CapacityLedger]
    registry: AllocationRegistry
    journal: EventJournal
    layouts: tuple[StageBlockLayout, ...]


def _scenario(*, physical_block_capacity: int = 3) -> _Scenario:
    layouts = (
        _layout(pp_stage=0, tp_rank=0, allocated_bytes=64),
        _layout(pp_stage=1, tp_rank=0, allocated_bytes=80),
    )
    ledgers = {
        "gpu-pp0-tp0.hbm": CapacityLedger(
            resource_id="gpu-pp0-tp0.hbm",
            resource_kind=CapacityResourceKind.GPU_HBM,
            capacity_bytes=64 * physical_block_capacity + 32,
            initial_accounts={"MODEL_WEIGHTS": 32},
        ),
        "gpu-pp1-tp0.hbm": CapacityLedger(
            resource_id="gpu-pp1-tp0.hbm",
            resource_kind=CapacityResourceKind.GPU_HBM,
            capacity_bytes=80 * physical_block_capacity + 48,
            initial_accounts={"MODEL_WEIGHTS": 48},
        ),
    }
    journal = EventJournal()
    registry = AllocationRegistry(journal=journal)
    bridge = HbmBlockLedgerBridge(
        bridge_id="dp0",
        bindings=(
            HbmStageRankBinding("gpu-pp0-tp0.hbm", layouts[0]),
            HbmStageRankBinding("gpu-pp1-tp0.hbm", layouts[1]),
        ),
        ledgers=ledgers,
        registry=registry,
        journal=journal,
        now_ns=lambda: 7,
    )
    return _Scenario(bridge, ledgers, registry, journal, layouts)


def _scheduler(
    scenario: _Scenario,
    *,
    num_gpu_blocks: int = 4,
    token_budget: int = 32,
    long_prefill_threshold: int = 0,
    enable_prefix_caching: bool = False,
) -> ContinuousBatchScheduler:
    return ContinuousBatchScheduler(
        block_pool=BlockPool(num_gpu_blocks, enable_caching=enable_prefix_caching),
        block_size_tokens=4,
        max_num_scheduled_tokens=token_budget,
        max_num_running_requests=8,
        long_prefill_token_threshold=long_prefill_threshold,
        block_lifecycle_observer=scenario.bridge,
        prefix_hash_seed="0" if enable_prefix_caching else None,
    )


def _request(request_id: str, prompt_tokens: int) -> Request:
    return Request(
        request_id=request_id,
        prompt_tokens=prompt_tokens,
        max_output_tokens=8,
        arrival_ns=0,
    )


def _token_request(request_id: str, token_ids: list[int]) -> Request:
    return Request(
        request_id=request_id,
        prompt_tokens=len(token_ids),
        prompt_token_ids=tuple(token_ids),
        max_output_tokens=8,
        arrival_ns=0,
    )


def test_checked_in_layout_artifact_binds_exact_block_geometry() -> None:
    repository_root = Path(__file__).resolve().parents[4]
    bindings = load_hbm_stage_rank_bindings(
        repository_root / "configs/resolved/qwen3-8b/native-tp1-pp1/kv-layout.json",
        resource_ids={(0, 0): "gpu-physical-0.hbm"},
    )

    assert len(bindings) == 1
    assert bindings[0].key == (0, 0)
    assert bindings[0].resource_id == "gpu-physical-0.hbm"
    assert bindings[0].layout.payload_bytes == 2_359_296
    assert bindings[0].layout.allocated_bytes == 2_359_296


def test_colocated_stage_ranks_share_one_physical_gpu_ledger() -> None:
    layouts = (
        _layout(pp_stage=0, tp_rank=0, allocated_bytes=64),
        _layout(pp_stage=1, tp_rank=0, allocated_bytes=80),
    )
    ledger = CapacityLedger(
        resource_id="shared-gpu.hbm",
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=2 * (64 + 80),
    )
    journal = EventJournal()
    registry = AllocationRegistry(journal=journal)
    bridge = HbmBlockLedgerBridge(
        bridge_id="colocated",
        bindings=(
            HbmStageRankBinding("shared-gpu.hbm", layouts[0]),
            HbmStageRankBinding("shared-gpu.hbm", layouts[1]),
        ),
        ledgers={ledger.resource_id: ledger},
        registry=registry,
        journal=journal,
    )

    assert bridge.num_free_blocks == 2
    bridge.allocate_blocks((1,), request_id="owner", cause="test.colocated")

    assert ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 64 + 80
    allocation_ids = bridge.allocation_ids(1)
    assert len(allocation_ids) == 2
    assert len({registry.get(item).replica_id for item in allocation_ids}) == 2


def test_scheduler_allocate_and_free_charge_exact_stage_rank_layouts() -> None:
    scenario = _scenario()
    scheduler = _scheduler(scenario)
    request = _request("request-a", 8)
    scheduler.add_request(request)

    scheduled = scheduler.schedule().scheduled_new_reqs[0]

    assert scheduled.new_block_ids == (1, 2)
    assert scenario.bridge.active_block_ids == (1, 2)
    for ledger, layout in zip(scenario.ledgers.values(), scenario.layouts, strict=True):
        assert ledger.bytes_in(HBM_KV_RESERVED_ACCOUNT) == 0
        assert ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 2 * layout.allocated_bytes
    allocation = scenario.registry.get(scenario.bridge.allocation_ids(1)[0])
    layout = scenario.layouts[0]
    assert allocation.state is AllocationState.COMMITTED
    assert allocation.payload_bytes == layout.payload_bytes
    assert allocation.padding_bytes == layout.layout_padding_bytes
    assert allocation.allocator_metadata_bytes == layout.allocator_metadata_bytes
    assert allocation.internal_fragmentation_bytes == layout.internal_fragmentation_bytes
    assert allocation.allocated_bytes == layout.allocated_bytes
    assert allocation.roles == {AllocationRole.ACTIVE_PRIMARY}

    scheduler.finish_request(request.request_id, RequestStatus.FINISHED_STOPPED)

    assert scenario.bridge.active_block_ids == ()
    for ledger in scenario.ledgers.values():
        assert ledger.bytes_in(HBM_KV_RESERVED_ACCOUNT) == 0
        assert ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 0
    transaction_causes = [
        record.data["cause"]
        for record in scenario.journal.records
        if record.record_type == "RESOURCE_TRANSACTION"
    ]
    assert transaction_causes == [
        "vllm.schedule:prefill:new:reserve",
        "vllm.schedule:prefill:new:activate",
        "vllm.finish:finished_stopped:release",
    ]
    activated = next(
        record
        for record in scenario.journal.records
        if record.record_type == "VLLM_HBM_BLOCKS_ACTIVATED"
    )
    released = next(
        record
        for record in scenario.journal.records
        if record.record_type == "VLLM_HBM_BLOCKS_RELEASED"
    )
    assert released.data["request_id"] == request.request_id
    assert released.data["block_count"] == 2
    assert set(released.data["block_ids"]) == {1, 2}
    activated_by_id = {block["block_id"]: block for block in activated.data["blocks"]}
    released_full_records = [activated_by_id[block_id] for block_id in released.data["block_ids"]]
    assert released.data["blocks_sha256"] == sha256_json(released_full_records)
    assert "blocks" not in released.data


def test_prefix_cache_residency_moves_active_inactive_without_alias_double_charge() -> None:
    scenario = _scenario(physical_block_capacity=4)
    scheduler = _scheduler(
        scenario,
        num_gpu_blocks=5,
        enable_prefix_caching=True,
    )
    owner = _token_request("owner", list(range(1, 9)))
    scheduler.add_request(owner)
    scheduler.schedule()
    scheduler.finish_request(owner.request_id, RequestStatus.FINISHED_STOPPED)

    assert scenario.bridge.inactive_block_ids == (1, 2)
    for ledger, layout in zip(scenario.ledgers.values(), scenario.layouts, strict=True):
        assert ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 0
        assert ledger.bytes_in(HBM_KV_INACTIVE_ACCOUNT) == 2 * layout.allocated_bytes

    follower = _token_request("follower", list(range(1, 9)))
    scheduler.add_request(follower)
    [hit] = scheduler.schedule().scheduled_new_reqs

    assert hit.local_cache_hit_block_ids == (1,)
    assert scheduler.block_pool.blocks[1].ref_count == 1
    assert scenario.bridge.inactive_block_ids == (2,)
    for ledger, layout in zip(scenario.ledgers.values(), scenario.layouts, strict=True):
        # One hit page plus one newly allocated suffix page are active. The hit
        # reference itself never creates a third active physical charge.
        assert ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 2 * layout.allocated_bytes
        assert ledger.bytes_in(HBM_KV_INACTIVE_ACCOUNT) == layout.allocated_bytes

    scheduler.finish_request(follower.request_id, RequestStatus.FINISHED_STOPPED)
    assert scenario.bridge.inactive_block_ids == (1, 2, 3)
    replacement = _token_request("replacement", list(range(90, 98)))
    scheduler.add_request(replacement)
    scheduler.schedule()
    assert any(
        record.record_type == "VLLM_HBM_INACTIVE_BLOCKS_EVICTED"
        for record in scenario.journal.records
    )

    pristine = _scenario(physical_block_capacity=4)
    replay_capacity_transactions(scenario.journal, pristine.ledgers)
    replayed_registry = replay_allocation_registry(scenario.journal)
    assert {resource_id: ledger.accounts for resource_id, ledger in pristine.ledgers.items()} == {
        resource_id: ledger.accounts for resource_id, ledger in scenario.ledgers.items()
    }
    assert replayed_registry.snapshot_bytes() == scenario.registry.snapshot_bytes()


def test_large_hbm_release_record_has_bounded_compact_payload() -> None:
    scenario = _scenario(physical_block_capacity=128)
    block_ids = tuple(range(1, 129))
    scenario.bridge.allocate_blocks(
        block_ids,
        request_id="large-release",
        cause="test.large-release.allocate",
    )
    activated = next(
        record
        for record in scenario.journal.records
        if record.record_type == "VLLM_HBM_BLOCKS_ACTIVATED"
    )

    scenario.bridge.release_blocks(
        block_ids,
        request_id="large-release",
        cause="test.large-release.free",
    )

    released = next(
        record
        for record in scenario.journal.records
        if record.record_type == "VLLM_HBM_BLOCKS_RELEASED"
    )
    assert released.data["block_count"] == 128
    assert released.data["block_ids"] == list(block_ids)
    assert released.data["blocks_sha256"] == sha256_json(activated.data["blocks"])
    assert len(canonical_json_bytes(released.data)) < 1_500
    assert len(canonical_json_bytes(released.data)) * 20 < len(canonical_json_bytes(activated.data))


def test_chunked_prefill_and_decode_only_charge_new_full_layout_blocks() -> None:
    scenario = _scenario(physical_block_capacity=4)
    scheduler = _scheduler(
        scenario,
        num_gpu_blocks=5,
        token_budget=8,
        long_prefill_threshold=2,
    )
    request = _request("chunk-decode", 8)
    scheduler.add_request(request)

    first = scheduler.schedule().scheduled_new_reqs[0]
    second = scheduler.schedule().scheduled_running_reqs[0]
    third = scheduler.schedule().scheduled_running_reqs[0]
    fourth = scheduler.schedule().scheduled_running_reqs[0]
    scheduler.append_output_tokens(request.request_id)
    decode = scheduler.schedule().scheduled_running_reqs[0]

    assert first.new_block_ids == (1,)
    assert second.new_block_ids == ()
    assert third.new_block_ids == (2,)
    assert fourth.new_block_ids == ()
    assert decode.new_block_ids == (3,)
    assert scenario.bridge.active_block_ids == (1, 2, 3)
    reserve_transactions = [
        record
        for record in scenario.journal.records
        if record.record_type == "RESOURCE_TRANSACTION"
        and str(record.data["cause"]).endswith(":reserve")
    ]
    assert len(reserve_transactions) == 3


def test_recompute_preemption_frees_then_rebuilds_unique_allocations() -> None:
    scenario = _scenario()
    scheduler = _scheduler(scenario, token_budget=12)
    head = _request("head", 4)
    tail = _request("tail", 8)
    scheduler.add_request(head)
    scheduler.add_request(tail)
    scheduler.schedule()
    old_tail_allocations = {
        *scenario.bridge.allocation_ids(2),
        *scenario.bridge.allocation_ids(3),
    }

    scheduler.append_output_tokens(head.request_id)
    pressured = scheduler.schedule()

    assert pressured.preempted_req_ids == ("tail",)
    assert tail.status is RequestStatus.PREEMPTED
    assert scenario.bridge.active_block_ids == (1, 3)
    scheduler.finish_request(head.request_id, RequestStatus.FINISHED_STOPPED)
    resumed = scheduler.schedule().scheduled_resumed_reqs[0]
    new_tail_allocations = {
        *scenario.bridge.allocation_ids(2),
        *scenario.bridge.allocation_ids(3),
    }

    assert resumed.recompute
    assert old_tail_allocations.isdisjoint(new_tail_allocations)
    assert all(
        scenario.registry.get(allocation_id).state is AllocationState.RELEASED
        for allocation_id in old_tail_allocations
    )
    causes = [
        str(record.data["cause"])
        for record in scenario.journal.records
        if record.record_type == "RESOURCE_TRANSACTION"
    ]
    assert "vllm.preempt:recompute:release" in causes
    assert "vllm.schedule:prefill:resumed:reserve" in causes


def test_logical_hash_aliases_and_refcounts_never_charge_capacity_twice() -> None:
    scenario = _scenario()
    scenario.bridge.allocate_blocks((1,), request_id="owner", cause="test.allocate")
    before_accounts = {
        resource_id: ledger.accounts for resource_id, ledger in scenario.ledgers.items()
    }

    scenario.bridge.retain_alias(1, alias_id="alias-a", logical_hash="hash-1")
    scenario.bridge.retain_alias(1, alias_id="alias-b", logical_hash="hash-1")

    assert {
        resource_id: ledger.accounts for resource_id, ledger in scenario.ledgers.items()
    } == before_accounts
    for allocation_id in scenario.bridge.allocation_ids(1):
        assert scenario.registry.overlay(allocation_id).source_pin_count == 2
        assert AllocationRole.CACHE_REUSE in scenario.registry.get(allocation_id).roles
    with pytest.raises(ValueError, match="two logical hashes"):
        scenario.bridge.retain_alias(1, alias_id="bad-hash", logical_hash="hash-2")
    with pytest.raises(ValueError, match="retains alias references"):
        scenario.bridge.release_blocks((1,), request_id="owner", cause="test.free")

    scenario.bridge.release_alias(1, alias_id="alias-a")
    scenario.bridge.release_alias(1, alias_id="alias-b")
    scenario.bridge.release_blocks((1,), request_id="owner", cause="test.free")

    assert scenario.bridge.active_block_ids == ()
    assert all(ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 0 for ledger in scenario.ledgers.values())


def test_null_block_has_no_physical_allocation_and_oom_is_atomic() -> None:
    scenario = _scenario(physical_block_capacity=1)
    before_accounts = {
        resource_id: ledger.accounts for resource_id, ledger in scenario.ledgers.items()
    }
    before_registry = scenario.registry.snapshot_bytes()
    scenario.bridge.allocate_blocks((0,), request_id="null", cause="test.null")
    assert scenario.journal.records == ()

    with pytest.raises(ValueError, match="cannot transfer"):
        scenario.bridge.allocate_blocks((1, 2), request_id="oom", cause="test.oom")

    assert scenario.bridge.active_block_ids == ()
    assert scenario.registry.snapshot_bytes() == before_registry
    assert scenario.journal.records == ()
    assert {
        resource_id: ledger.accounts for resource_id, ledger in scenario.ledgers.items()
    } == before_accounts


def test_scheduler_capacity_shortage_does_not_mutate_waiting_request() -> None:
    scenario = _scenario(physical_block_capacity=1)
    scheduler = _scheduler(scenario, num_gpu_blocks=3)
    request = _request("too-large", 8)
    scheduler.add_request(request)

    output = scheduler.schedule()

    assert output.scheduled_req_ids == ()
    assert scheduler.waiting_request_ids == ("too-large",)
    assert scheduler.running_request_ids == ()
    assert request.status is RequestStatus.WAITING
    assert request.num_computed_tokens == 0
    assert scheduler.request_block_ids(request.request_id) == ()
    assert scenario.bridge.active_block_ids == ()
    assert scenario.journal.records == ()


def test_capacity_and_allocation_journal_replay_matches_online_bytes() -> None:
    def run_once() -> _Scenario:
        result = _scenario()
        scheduler = _scheduler(result)
        request = _request("replay", 4)
        scheduler.add_request(request)
        scheduler.schedule()
        result.bridge.retain_alias(1, alias_id="reuse", logical_hash="hash-replay")
        result.bridge.release_alias(1, alias_id="reuse")
        scheduler.finish_request(request.request_id, RequestStatus.FINISHED_STOPPED)
        return result

    online = run_once()
    repeated = run_once()
    assert repeated.journal.to_jsonl_bytes() == online.journal.to_jsonl_bytes()

    pristine = _scenario()
    replay_capacity_transactions(online.journal, pristine.ledgers)
    replayed_registry = replay_allocation_registry(online.journal)

    assert {resource_id: ledger.accounts for resource_id, ledger in pristine.ledgers.items()} == {
        resource_id: ledger.accounts for resource_id, ledger in online.ledgers.items()
    }
    assert replayed_registry.snapshot_bytes() == online.registry.snapshot_bytes()


def test_recovery_destination_reservation_commits_without_reallocation_or_double_charge() -> None:
    scenario = _scenario(physical_block_capacity=2)
    scheduler = _scheduler(scenario, num_gpu_blocks=3)

    reservation = scheduler.reserve_recovery_prefix(
        "recovery",
        restored_tokens=8,
    )

    assert reservation.block_ids == (1, 2)
    assert scheduler.block_pool.num_free_blocks == 0
    assert scenario.bridge.active_block_ids == ()
    for ledger, layout in zip(scenario.ledgers.values(), scenario.layouts, strict=True):
        assert ledger.bytes_in(HBM_RECOVERY_RESERVED_ACCOUNT) == (2 * layout.allocated_bytes)
        assert ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 0
    for allocation_ids in reservation.destination_allocation_ids:
        for allocation_id in allocation_ids:
            allocation = scenario.registry.get(allocation_id)
            assert allocation.state is AllocationState.RESERVED
            assert allocation.owner_account == HBM_RECOVERY_RESERVED_ACCOUNT

    journal_before_capacity_retry = scenario.journal.to_jsonl_bytes()
    with pytest.raises(ValueError, match="insufficient scheduler/HBM capacity"):
        scheduler.reserve_recovery_prefix("capacity-retry", restored_tokens=4)
    assert scenario.journal.to_jsonl_bytes() == journal_before_capacity_retry

    recovered = _request("recovery", 12)
    scheduler.commit_recovery_prefix(recovered, reservation)

    assert recovered.status is RequestStatus.RUNNING
    assert recovered.num_computed_tokens == 8
    assert scheduler.request_block_ids(recovered.request_id) == reservation.block_ids
    assert scenario.bridge.active_block_ids == reservation.block_ids
    for ledger, layout in zip(scenario.ledgers.values(), scenario.layouts, strict=True):
        assert ledger.bytes_in(HBM_RECOVERY_RESERVED_ACCOUNT) == 0
        assert ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 2 * layout.allocated_bytes
    for allocation_ids in reservation.destination_allocation_ids:
        for allocation_id in allocation_ids:
            allocation = scenario.registry.get(allocation_id)
            assert allocation.state is AllocationState.COMMITTED
            assert allocation.owner_account == HBM_KV_ACTIVE_ACCOUNT
            assert allocation.roles == {AllocationRole.ACTIVE_PRIMARY}

    scheduler.finish_request(recovered.request_id, RequestStatus.FINISHED_STOPPED)
    pristine = _scenario(physical_block_capacity=2)
    replay_capacity_transactions(scenario.journal, pristine.ledgers)
    replayed_registry = replay_allocation_registry(scenario.journal)
    assert {resource_id: ledger.accounts for resource_id, ledger in pristine.ledgers.items()} == {
        resource_id: ledger.accounts for resource_id, ledger in scenario.ledgers.items()
    }
    assert replayed_registry.snapshot_bytes() == scenario.registry.snapshot_bytes()


def test_failed_recovery_destination_abort_releases_only_healthy_shards_and_replays() -> None:
    scenario = _scenario(physical_block_capacity=2)
    scheduler = _scheduler(scenario, num_gpu_blocks=3)
    reservation = scheduler.reserve_recovery_prefix(
        "failed-recovery",
        restored_tokens=4,
    )
    failed_allocation, healthy_allocation = reservation.destination_allocation_ids[0]
    AtomicGPUHBMFailStop(
        ledgers=scenario.ledgers,
        registry=scenario.registry,
        journal=scenario.journal,
        observers=(scenario.bridge,),
    ).fail_gpu_hbm(
        gpu_id="gpu-pp0-tp0",
        resource_ids=("gpu-pp0-tp0.hbm",),
        failure_id="recovery-destination-failure",
        timestamp_ns=7,
    )

    scheduler.abort_recovery_prefix(
        "failed-recovery",
        cause="test.recovery-destination-failure",
    )

    assert scheduler.block_pool.num_free_blocks == 2
    assert scenario.bridge.active_block_ids == ()
    assert scenario.registry.get(failed_allocation).state is AllocationState.LOST
    assert scenario.registry.get(failed_allocation).owner_account == (UNAVAILABLE_CAPACITY_ACCOUNT)
    assert scenario.registry.get(healthy_allocation).state is AllocationState.RELEASED
    assert scenario.ledgers["gpu-pp1-tp0.hbm"].bytes_in(HBM_RECOVERY_RESERVED_ACCOUNT) == 0

    pristine = _scenario(physical_block_capacity=2)
    replay_capacity_transactions(scenario.journal, pristine.ledgers)
    replayed_registry = replay_allocation_registry(scenario.journal)
    assert {resource_id: ledger.accounts for resource_id, ledger in pristine.ledgers.items()} == {
        resource_id: ledger.accounts for resource_id, ledger in scenario.ledgers.items()
    }
    assert replayed_registry.snapshot_bytes() == scenario.registry.snapshot_bytes()


def test_multi_gpu_block_degrades_and_later_release_preserves_failed_capacity() -> None:
    scenario = _scenario()
    scheduler = _scheduler(scenario)
    request = _request("failed-request", 4)
    scheduler.add_request(request)
    scheduler.schedule()
    scenario.bridge.retain_alias(1, alias_id="reuse", logical_hash="hash-failure")
    failed_resource = "gpu-pp0-tp0.hbm"
    healthy_resource = "gpu-pp1-tp0.hbm"
    failed_allocation, healthy_allocation = scenario.bridge.allocation_ids(1)
    handler = AtomicGPUHBMFailStop(
        ledgers=scenario.ledgers,
        registry=scenario.registry,
        journal=scenario.journal,
        observers=(scenario.bridge,),
    )

    handler.fail_gpu_hbm(
        gpu_id="gpu-pp0-tp0",
        resource_ids=(failed_resource,),
        failure_id="failure-0",
        timestamp_ns=7,
    )

    failed_ledger = scenario.ledgers[failed_resource]
    healthy_ledger = scenario.ledgers[healthy_resource]
    assert failed_ledger.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT) == (failed_ledger.capacity_bytes)
    assert failed_ledger.bytes_in(FREE_ACCOUNT) == 0
    assert scenario.registry.get(failed_allocation).state is AllocationState.LOST
    assert scenario.registry.get(failed_allocation).roles == frozenset()
    assert scenario.registry.overlay(failed_allocation).source_pin_count == 0
    assert scenario.registry.get(healthy_allocation).state is AllocationState.COMMITTED
    assert scenario.registry.overlay(healthy_allocation).source_pin_count == 0
    assert scenario.registry.get(healthy_allocation).roles == {AllocationRole.ACTIVE_PRIMARY}
    assert healthy_ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 80
    assert scenario.bridge.num_free_blocks == 0

    scheduler.finish_request(request.request_id, RequestStatus.FINISHED_STOPPED)

    assert scenario.bridge.active_block_ids == ()
    assert failed_ledger.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT) == (failed_ledger.capacity_bytes)
    assert failed_ledger.bytes_in(FREE_ACCOUNT) == 0
    assert scenario.registry.get(failed_allocation).state is AllocationState.LOST
    assert scenario.registry.get(healthy_allocation).state is AllocationState.RELEASED
    assert healthy_ledger.bytes_in(HBM_KV_ACTIVE_ACCOUNT) == 0


def test_fully_lost_block_release_keeps_reconstructable_logical_ids() -> None:
    scenario = _scenario()
    scenario.bridge.allocate_blocks(
        (1,),
        request_id="fully-lost",
        cause="test.fully-lost.allocate",
    )
    AtomicGPUHBMFailStop(
        ledgers=scenario.ledgers,
        registry=scenario.registry,
        journal=scenario.journal,
        observers=(scenario.bridge,),
    ).fail_gpu_hbm(
        gpu_id="synthetic-whole-failure-domain",
        resource_ids=tuple(scenario.ledgers),
        failure_id="failure-all-shards",
        timestamp_ns=7,
    )
    transaction_count_before_release = sum(
        record.record_type == "RESOURCE_TRANSACTION" for record in scenario.journal.records
    )

    scenario.bridge.release_blocks(
        (1,),
        request_id="fully-lost",
        cause="test.fully-lost.free",
    )

    assert scenario.bridge.active_block_ids == ()
    assert transaction_count_before_release == sum(
        record.record_type == "RESOURCE_TRANSACTION" for record in scenario.journal.records
    )
    released = next(
        record
        for record in scenario.journal.records
        if record.record_type == "VLLM_HBM_BLOCKS_RELEASED"
    )
    assert released.data["request_id"] == "fully-lost"
    assert released.data["block_count"] == 1
    assert released.data["block_ids"] == [1]
    assert isinstance(released.data["blocks_sha256"], str)


def test_hbm_failure_journal_capacity_and_registry_replay_byte_identically() -> None:
    def run_once() -> _Scenario:
        scenario = _scenario()
        scenario.bridge.allocate_blocks((1,), request_id="replay", cause="test.allocate")
        scenario.bridge.retain_alias(1, alias_id="reuse", logical_hash="hash-replay")
        AtomicGPUHBMFailStop(
            ledgers=scenario.ledgers,
            registry=scenario.registry,
            journal=scenario.journal,
            observers=(scenario.bridge,),
        ).fail_gpu_hbm(
            gpu_id="gpu-pp0-tp0",
            resource_ids=("gpu-pp0-tp0.hbm",),
            failure_id="failure-replay",
            timestamp_ns=7,
        )
        scenario.bridge.release_blocks((1,), request_id="replay", cause="vllm.failure-cleanup")
        return scenario

    online = run_once()
    repeated = run_once()
    assert repeated.journal.to_jsonl_bytes() == online.journal.to_jsonl_bytes()

    pristine = _scenario()
    replay_capacity_transactions(online.journal, pristine.ledgers)
    replayed_registry = replay_allocation_registry(online.journal)
    assert {resource_id: ledger.accounts for resource_id, ledger in pristine.ledgers.items()} == {
        resource_id: ledger.accounts for resource_id, ledger in online.ledgers.items()
    }
    assert replayed_registry.snapshot_bytes() == online.registry.snapshot_bytes()


def test_one_physical_gpu_failure_can_atomically_lose_multiple_hbm_resources() -> None:
    scenario = _scenario()
    scenario.bridge.allocate_blocks((1,), request_id="all-lost", cause="test.allocate")
    resource_ids = tuple(scenario.ledgers)
    allocation_ids = scenario.bridge.allocation_ids(1)
    handler = AtomicGPUHBMFailStop(
        ledgers=scenario.ledgers,
        registry=scenario.registry,
        journal=scenario.journal,
        observers=(scenario.bridge,),
    )

    handler.fail_gpu_hbm(
        gpu_id="colocated-physical-gpu",
        resource_ids=resource_ids,
        failure_id="failure-all-resources",
        timestamp_ns=7,
    )
    transactions_before_release = sum(
        record.record_type == "RESOURCE_TRANSACTION" for record in scenario.journal.records
    )
    scenario.bridge.release_blocks((1,), request_id="all-lost", cause="vllm.failure-cleanup")

    assert all(
        ledger.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT) == ledger.capacity_bytes
        for ledger in scenario.ledgers.values()
    )
    assert all(
        scenario.registry.get(allocation_id).state is AllocationState.LOST
        for allocation_id in allocation_ids
    )
    assert scenario.bridge.active_block_ids == ()
    assert (
        sum(record.record_type == "RESOURCE_TRANSACTION" for record in scenario.journal.records)
        == transactions_before_release
    )
