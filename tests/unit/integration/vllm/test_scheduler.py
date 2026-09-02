from __future__ import annotations

import pytest

from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.request import Request, RequestStatus
from moonkvsim.integration.vllm.scheduler import (
    EVIDENCE_CLASS,
    VLLM_SCHEDULER_SHA256,
    VLLM_SOURCE_COMMIT,
    ContinuousBatchScheduler,
    RecoveryPrefixReservation,
    SchedulerInvariantError,
    SchedulingOrigin,
    SchedulingPhase,
)


def make_scheduler(
    *,
    num_gpu_blocks: int = 20,
    block_size_tokens: int = 4,
    token_budget: int = 16,
    max_running: int = 8,
    long_prefill_threshold: int = 0,
    enable_chunked_prefill: bool = True,
    enable_prefix_caching: bool = False,
) -> ContinuousBatchScheduler:
    return ContinuousBatchScheduler(
        block_pool=BlockPool(num_gpu_blocks, enable_caching=enable_prefix_caching),
        block_size_tokens=block_size_tokens,
        max_num_scheduled_tokens=token_budget,
        max_num_running_requests=max_running,
        long_prefill_token_threshold=long_prefill_threshold,
        enable_chunked_prefill=enable_chunked_prefill,
        prefix_hash_seed="0" if enable_prefix_caching else None,
    )


def make_request(request_id: str, prompt_tokens: int, *, arrival_ns: int = 0) -> Request:
    return Request(
        request_id=request_id,
        prompt_tokens=prompt_tokens,
        max_output_tokens=8,
        arrival_ns=arrival_ns,
    )


def make_token_request(request_id: str, token_ids: list[int]) -> Request:
    return Request(
        request_id=request_id,
        prompt_tokens=len(token_ids),
        prompt_token_ids=tuple(token_ids),
        max_output_tokens=8,
        arrival_ns=0,
    )


def test_recovery_reservation_allows_only_contiguous_exact_allocation_groups() -> None:
    reservation = RecoveryPrefixReservation(
        request_id="rounded",
        restored_tokens=64,
        block_ids=(1, 2, 3, 4),
        destination_allocation_ids=(("source-0",),) * 4,
    )

    assert reservation.physical_allocation_ids == frozenset({"source-0"})
    with pytest.raises(ValueError, match="conflicting groups"):
        RecoveryPrefixReservation(
            request_id="partial-overlap",
            restored_tokens=8,
            block_ids=(1, 2),
            destination_allocation_ids=(
                ("stage-0", "stage-1"),
                ("stage-0", "stage-2"),
            ),
        )
    with pytest.raises(ValueError, match="contiguous blocks"):
        RecoveryPrefixReservation(
            request_id="non-contiguous",
            restored_tokens=12,
            block_ids=(1, 2, 3),
            destination_allocation_ids=(
                ("source-0",),
                ("source-1",),
                ("source-0",),
            ),
        )


def test_running_requests_are_scheduled_before_waiting_requests() -> None:
    scheduler = make_scheduler(token_budget=3, block_size_tokens=1)
    first = make_request("running-a", 1)
    second = make_request("running-b", 1)
    scheduler.add_request(first)
    scheduler.add_request(second)
    scheduler.schedule()
    scheduler.append_output_tokens(first.request_id)
    scheduler.append_output_tokens(second.request_id)
    waiting = make_request("waiting-c", 2, arrival_ns=1)
    scheduler.add_request(waiting)

    output = scheduler.schedule()

    assert output.scheduled_req_ids == ("running-a", "running-b", "waiting-c")
    assert tuple(item.request_id for item in output.scheduled_running_reqs) == (
        "running-a",
        "running-b",
    )
    assert tuple(item.request_id for item in output.scheduled_new_reqs) == ("waiting-c",)
    assert output.total_num_scheduled_tokens == 3
    assert output.evidence_class == EVIDENCE_CLASS == "E1"
    assert output.source_commit == VLLM_SOURCE_COMMIT
    assert output.source_sha256 == VLLM_SCHEDULER_SHA256
    gaps = " ".join(output.fidelity_gaps)
    assert "DDTree" in gaps and "LoRA" in gaps and "multimodal" in gaps


def test_long_prefill_threshold_produces_deterministic_chunks() -> None:
    scheduler = make_scheduler(token_budget=8, long_prefill_threshold=4)
    request = make_request("long-prefill", 10)
    scheduler.add_request(request)

    first = scheduler.schedule()
    second = scheduler.schedule()
    third = scheduler.schedule()

    assert first.num_scheduled_tokens == {"long-prefill": 4}
    assert second.num_scheduled_tokens == {"long-prefill": 4}
    assert third.num_scheduled_tokens == {"long-prefill": 2}
    assert first.scheduled_new_reqs[0].chunked
    assert second.scheduled_running_reqs[0].chunked
    assert not third.scheduled_running_reqs[0].chunked
    assert request.num_computed_tokens == 10


def test_decode_allocates_a_new_block_only_when_crossing_boundary() -> None:
    scheduler = make_scheduler(block_size_tokens=4)
    request = make_request("decode", 4)
    scheduler.add_request(request)

    prefill = scheduler.schedule().scheduled_new_reqs[0]
    scheduler.append_output_tokens(request.request_id)
    decode = scheduler.schedule().scheduled_running_reqs[0]

    assert prefill.phase is SchedulingPhase.PREFILL
    assert prefill.new_block_ids == (1,)
    assert decode.phase is SchedulingPhase.DECODE
    assert decode.num_scheduled_tokens == 1
    assert decode.new_block_ids == (2,)
    assert decode.block_ids == (1, 2)


def test_kv_shortage_preempts_tail_and_resumes_with_recompute() -> None:
    scheduler = make_scheduler(num_gpu_blocks=4, token_budget=12)
    head = make_request("head", 4)
    tail = make_request("tail", 8)
    scheduler.add_request(head)
    scheduler.add_request(tail)
    scheduler.schedule()
    assert scheduler.block_pool.num_free_blocks == 0

    scheduler.append_output_tokens(head.request_id)
    pressured = scheduler.schedule()

    assert pressured.preempted_req_ids == ("tail",)
    assert pressured.scheduled_req_ids == ("head",)
    assert tail.status is RequestStatus.PREEMPTED
    assert tail.num_computed_tokens == 0
    assert tail.num_preemptions == 1
    assert scheduler.request_block_ids("tail") == ()
    assert scheduler.waiting_request_ids == ("tail",)

    scheduler.finish_request("head", RequestStatus.FINISHED_STOPPED)
    resumed = scheduler.schedule().scheduled_resumed_reqs[0]

    assert resumed.request_id == "tail"
    assert resumed.origin is SchedulingOrigin.RESUMED
    assert resumed.recompute
    assert resumed.num_computed_tokens_before == 0
    assert resumed.num_computed_tokens_after == 8


def test_ready_remote_prefix_owner_precedes_newly_preempted_recompute() -> None:
    scheduler = make_scheduler(num_gpu_blocks=4, block_size_tokens=4, token_budget=8)
    running = make_request("running", 12)
    restored = make_request("restored", 8)
    scheduler.add_request(running)
    scheduler.schedule()
    scheduler.add_request(restored)
    scheduler.mark_waiting_for_remote_kv(restored.request_id)
    scheduler.restore_waiting_request_prefix(restored.request_id, restored_tokens=8)

    scheduler.append_output_tokens(running.request_id)
    pressured = scheduler.schedule()

    assert pressured.preempted_req_ids == (running.request_id,)
    assert scheduler.waiting_request_ids == (restored.request_id, running.request_id)

    admitted = scheduler.schedule()

    assert admitted.scheduled_req_ids[0] == restored.request_id
    assert restored.status is RequestStatus.RUNNING
    assert restored.num_computed_tokens == restored.prompt_tokens
    assert running.status is RequestStatus.PREEMPTED


def test_failure_recovery_priority_preempts_one_running_slot_then_admits() -> None:
    scheduler = make_scheduler(
        num_gpu_blocks=10,
        block_size_tokens=4,
        token_budget=16,
        max_running=2,
    )
    head = make_request("head", 8)
    tail = make_request("tail", 8)
    recovery = make_request("recovery", 4)
    scheduler.add_request(head)
    scheduler.add_request(tail)
    scheduler.schedule()
    scheduler.add_request(recovery)
    scheduler.prioritize_waiting_recovery(recovery.request_id)

    pressured = scheduler.schedule()

    assert pressured.preempted_req_ids == (tail.request_id,)
    assert scheduler.waiting_request_ids == (recovery.request_id, tail.request_id)

    admitted = scheduler.schedule()

    assert admitted.scheduled_req_ids[0] == recovery.request_id
    assert recovery.status is RequestStatus.RUNNING
    assert tail.status is RequestStatus.PREEMPTED


def test_local_prefix_hit_recomputes_final_full_prompt_block_and_shares_refcount() -> None:
    scheduler = make_scheduler(enable_prefix_caching=True, num_gpu_blocks=5)
    owner = make_token_request("owner", list(range(1, 9)))
    scheduler.add_request(owner)
    scheduler.schedule()
    scheduler.finish_request(owner.request_id, RequestStatus.FINISHED_STOPPED)

    follower = make_token_request("follower", list(range(1, 9)))
    scheduler.add_request(follower)
    [hit] = scheduler.schedule().scheduled_new_reqs

    assert hit.local_cache_hit_tokens == 4
    assert hit.local_cache_hit_block_ids == (1,)
    assert hit.num_scheduled_tokens == 4
    assert hit.num_computed_tokens_before == 4
    assert hit.num_computed_tokens_after == 8
    assert hit.block_ids == (1, 3)

    sharer = make_token_request("sharer", [1, 2, 3, 4, 99])
    scheduler.add_request(sharer)
    [shared] = scheduler.schedule().scheduled_new_reqs
    assert shared.local_cache_hit_block_ids == (1,)
    assert scheduler.block_pool.blocks[1].ref_count == 2

    scheduler.finish_request(follower.request_id, RequestStatus.FINISHED_STOPPED)
    assert scheduler.block_pool.blocks[1].ref_count == 1
    scheduler.finish_request(sharer.request_id, RequestStatus.FINISHED_STOPPED)
    assert scheduler.block_pool.blocks[1].ref_count == 0
    assert 1 in scheduler.block_pool.free_block_ids


def test_prefix_cache_preemption_keeps_first_block_and_evicts_tail_first() -> None:
    scheduler = make_scheduler(
        enable_prefix_caching=True,
        num_gpu_blocks=4,
        token_budget=12,
    )
    head = make_token_request("head", [20, 21, 22, 23])
    tail = make_token_request("tail", list(range(1, 9)))
    scheduler.add_request(head)
    scheduler.add_request(tail)
    scheduler.schedule()
    scheduler.append_output_tokens(head.request_id)

    pressured = scheduler.schedule()

    assert pressured.preempted_req_ids == (tail.request_id,)
    assert scheduler.block_pool.blocks[2].block_hash is not None
    assert scheduler.block_pool.blocks[3].block_hash is None
    scheduler.finish_request(head.request_id, RequestStatus.FINISHED_STOPPED)

    [resumed] = scheduler.schedule().scheduled_resumed_reqs
    assert resumed.recompute
    assert resumed.local_cache_hit_tokens == 4
    assert resumed.local_cache_hit_block_ids == (2,)
    assert resumed.num_scheduled_tokens == 4


def test_global_budget_is_shared_across_waiting_requests() -> None:
    scheduler = make_scheduler(block_size_tokens=1, token_budget=5)
    for request_id, prompt_tokens in (("a", 4), ("b", 4), ("c", 1)):
        scheduler.add_request(make_request(request_id, prompt_tokens))

    output = scheduler.schedule()

    assert output.num_scheduled_tokens == {"a": 4, "b": 1}
    assert output.total_num_scheduled_tokens == 5
    assert output.token_budget_remaining == 0
    assert scheduler.running_request_ids == ("a", "b")
    assert scheduler.waiting_request_ids == ("c",)


def test_waiting_request_stays_queued_when_blocks_are_unavailable() -> None:
    scheduler = make_scheduler(num_gpu_blocks=2, token_budget=8)
    first = make_request("first", 4)
    blocked = make_request("blocked", 4)
    scheduler.add_request(first)
    scheduler.add_request(blocked)

    output = scheduler.schedule()

    assert output.scheduled_req_ids == ("first",)
    assert scheduler.running_request_ids == ("first",)
    assert scheduler.waiting_request_ids == ("blocked",)


def test_identical_inputs_produce_byte_identical_scheduler_outputs() -> None:
    def run_once() -> tuple[bytes, bytes]:
        scheduler = make_scheduler(token_budget=5, long_prefill_threshold=3)
        scheduler.add_request(make_request("a", 7))
        scheduler.add_request(make_request("b", 2))
        first = scheduler.schedule().to_json_bytes()
        second = scheduler.schedule().to_json_bytes()
        return first, second

    assert run_once() == run_once()


def test_restored_prefix_materializes_owned_blocks_and_only_schedules_suffix() -> None:
    scheduler = make_scheduler(block_size_tokens=4, token_budget=16)
    request = make_request("restored", 12)

    scheduler.restore_request_prefix(request, restored_tokens=8)

    assert request.status is RequestStatus.RUNNING
    assert request.num_computed_tokens == 8
    assert scheduler.request_block_ids(request.request_id) == (1, 2)
    assert scheduler.queued_tokens == 4

    [scheduled] = scheduler.schedule().scheduled_running_reqs
    assert scheduled.num_computed_tokens_before == 8
    assert scheduled.num_computed_tokens_after == 12
    assert scheduled.new_block_ids == (3,)
    assert scheduler.queued_tokens == 0


def test_restored_prefix_rejects_partial_block_or_unproven_counter_state() -> None:
    scheduler = make_scheduler(block_size_tokens=4)

    with pytest.raises(ValueError, match="whole KV blocks"):
        scheduler.restore_request_prefix(
            make_request("partial", 8),
            restored_tokens=6,
        )

    request = make_request("already-computed", 8)
    request.num_computed_tokens = 4
    with pytest.raises(ValueError, match="fresh request counters"):
        scheduler.restore_request_prefix(request, restored_tokens=4)


def test_remote_prefix_wait_skips_head_and_defers_promotion_until_slot_is_free() -> None:
    scheduler = make_scheduler(
        block_size_tokens=4,
        token_budget=16,
        max_running=1,
    )
    remote = make_request("remote", 8)
    ready = make_request("ready-behind-remote", 4)
    scheduler.add_request(remote)
    scheduler.mark_waiting_for_remote_kv(remote.request_id)
    scheduler.add_request(ready)

    first = scheduler.schedule()

    assert first.scheduled_req_ids == (ready.request_id,)
    assert remote.status is RequestStatus.WAITING_FOR_REMOTE_KVS
    assert scheduler.waiting_request_ids == (remote.request_id,)
    assert scheduler.running_request_ids == (ready.request_id,)

    scheduler.restore_waiting_request_prefix(remote.request_id, restored_tokens=8)
    assert remote.status is RequestStatus.WAITING_FOR_REMOTE_KVS
    assert remote.num_computed_tokens == 0
    assert scheduler.request_block_ids(remote.request_id) == ()

    slot_full = scheduler.schedule()
    assert slot_full.scheduled_req_ids == ()
    assert remote.status is RequestStatus.WAITING_FOR_REMOTE_KVS
    assert scheduler.running_request_ids == (ready.request_id,)

    scheduler.finish_request(ready.request_id, RequestStatus.FINISHED_STOPPED)
    admitted = scheduler.schedule()
    [remote_prefill] = admitted.scheduled_new_reqs

    assert remote_prefill.request_id == remote.request_id
    assert remote_prefill.phase is SchedulingPhase.PREFILL
    assert remote_prefill.num_computed_tokens_before == 7
    assert remote_prefill.num_computed_tokens_after == 8
    assert remote_prefill.num_scheduled_tokens == 1
    assert len(remote_prefill.new_block_ids) == 2
    assert remote.status is RequestStatus.RUNNING
    assert scheduler.running_request_ids == (remote.request_id,)


def test_unsupported_or_ambiguous_state_fails_closed() -> None:
    with pytest.raises(ValueError, match="prefix_hash_seed"):
        ContinuousBatchScheduler(
            block_pool=BlockPool(4, enable_caching=True),
            block_size_tokens=4,
            max_num_scheduled_tokens=8,
            max_num_running_requests=2,
        )

    caching = make_scheduler(enable_prefix_caching=True)
    with pytest.raises(ValueError, match="exact prompt_token_ids"):
        caching.add_request(make_request("count-only", 4))

    scheduler = make_scheduler()
    remote = make_request("remote", 4)
    remote.wait_for_remote_kv()
    with pytest.raises(ValueError, match="fresh WAITING"):
        scheduler.add_request(remote)

    request = make_request("corrupt", 4)
    scheduler.add_request(request)
    request.num_computed_tokens = 5
    with pytest.raises(SchedulerInvariantError, match="computed tokens"):
        scheduler.schedule()
