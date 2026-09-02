from __future__ import annotations

from collections.abc import Callable

import pytest

from moonkvsim.aegiskv.experiment_hbm_authority import ExperimentHBMAuthority
from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.request import Request, RequestStatus
from moonkvsim.integration.vllm.scheduler import ContinuousBatchScheduler
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import (
    FREE_ACCOUNT,
    UNAVAILABLE_CAPACITY_ACCOUNT,
    AccountTransfer,
    CapacityLedger,
    CapacityResourceKind,
)

ACTIVE = "ACTIVE_PRIMARY_KV"
INACTIVE = "INACTIVE_REUSABLE_KV"
RECOVERY = "RECOVERY_DEST_RESERVED"
FOREGROUND_STORE = "FOREGROUND_STORE_RESTORE_RESERVED"
CHUNK_BYTES = 9_437_184


def _authority(
    *,
    chunks: int = 4,
    inactive_chunks: int = 0,
    journal: EventJournal | None = None,
    now_ns: Callable[[], int] = lambda: 0,
    reclaim_free_bytes: Callable[[int], bool] | None = None,
) -> tuple[ExperimentHBMAuthority, CapacityLedger]:
    ledger = CapacityLedger(
        resource_id="hbm:gpu-0",
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=chunks * CHUNK_BYTES,
        initial_accounts={
            ACTIVE: 0,
            INACTIVE: inactive_chunks * CHUNK_BYTES,
            RECOVERY: 0,
            FOREGROUND_STORE: 0,
            UNAVAILABLE_CAPACITY_ACCOUNT: 0,
        },
    )
    authority = ExperimentHBMAuthority(
        authority_id="gpu-0-primary",
        ledger=ledger,
        journal=EventJournal() if journal is None else journal,
        now_ns=now_ns,
        logical_block_tokens=16,
        source_chunk_tokens=64,
        source_chunk_bytes=CHUNK_BYTES,
        active_account=ACTIVE,
        inactive_account=INACTIVE,
        recovery_reserved_account=RECOVERY,
        reclaim_free_bytes=reclaim_free_bytes,
    )
    return authority, ledger


def test_four_logical_pages_share_one_rounded_source_allocation() -> None:
    authority, ledger = _authority()

    authority.allocate_blocks((1, 2, 3, 4), request_id="r0", cause="prefill")

    assert ledger.bytes_in(ACTIVE) == CHUNK_BYTES
    assert authority.active_physical_bytes == CHUNK_BYTES
    assert authority.active_block_ids == (1, 2, 3, 4)
    authority.audit_scheduler_blocks(
        {1: 1, 2: 1, 3: 1, 4: 1},
        {},
        set(),
    )

    authority.allocate_blocks((5,), request_id="r0", cause="tail")

    # The fifth 16-token logical page starts another 64-token physical source
    # chunk.  The unused 48-token tail remains charged, by construction.
    assert ledger.bytes_in(ACTIVE) == 2 * CHUNK_BYTES
    authority.release_blocks((5, 4, 3, 2, 1), request_id="r0", cause="terminal")
    assert ledger.bytes_in(ACTIVE) == 0
    assert ledger.bytes_in(FREE_ACCOUNT) == 4 * CHUNK_BYTES


def test_partial_source_tail_is_available_only_to_its_own_request() -> None:
    authority, _ledger = _authority(chunks=2)

    authority.allocate_blocks((1,), request_id="owner", cause="prefill")

    assert authority.num_free_blocks == 4
    assert authority.num_free_blocks_for_request("owner") == 7
    assert authority.num_free_blocks_for_request("other") == 4


def test_c32_tail_fragments_do_not_over_admit_the_thirty_third_request() -> None:
    authority, ledger = _authority(chunks=32)
    scheduler = ContinuousBatchScheduler(
        block_pool=BlockPool(32 * 4 + 1, enable_caching=False),
        block_size_tokens=16,
        max_num_scheduled_tokens=33 * 16,
        max_num_running_requests=64,
        block_lifecycle_observer=authority,
    )
    for index in range(33):
        scheduler.add_request(
            Request(
                request_id=f"request-{index:02d}",
                prompt_tokens=16,
                max_output_tokens=1,
                arrival_ns=0,
            )
        )

    output = scheduler.schedule()

    assert len(output.scheduled_new_reqs) == 32
    assert output.total_num_scheduled_tokens == 32 * 16
    assert scheduler.waiting_request_ids == ("request-32",)
    assert len(authority.active_request_ids) == 32
    assert authority.num_free_blocks == 0
    assert authority.num_free_blocks_for_request("request-32") == 0
    assert ledger.bytes_in(ACTIVE) == 32 * CHUNK_BYTES
    assert ledger.bytes_in(FREE_ACCOUNT) == 0
    scheduler.audit()


def test_reclaimable_external_hbm_is_reclaimed_before_recompute_preemption() -> None:
    peer = "PEER_PROTECTION"
    holder: dict[str, CapacityLedger] = {}
    reclaim_requests: list[int] = []

    def reclaim(required_bytes: int) -> bool:
        reclaim_requests.append(required_bytes)
        ledger = holder["ledger"]
        additional_bytes = required_bytes - ledger.bytes_in(FREE_ACCOUNT)
        if additional_bytes <= 0:
            return True
        if ledger.bytes_in(peer) < additional_bytes:
            return False
        ledger._replace_accounts(
            ledger.preview(
                [
                    AccountTransfer(
                        account_from=peer,
                        account_to=FREE_ACCOUNT,
                        delta_bytes=additional_bytes,
                    )
                ]
            )
        )
        return True

    authority, ledger = _authority(chunks=3, reclaim_free_bytes=reclaim)
    holder["ledger"] = ledger
    ledger._replace_accounts(
        ledger.preview(
            [
                AccountTransfer(
                    account_from=FREE_ACCOUNT,
                    account_to=peer,
                    delta_bytes=CHUNK_BYTES,
                )
            ]
        )
    )
    scheduler = ContinuousBatchScheduler(
        block_pool=BlockPool(13, enable_caching=False),
        block_size_tokens=16,
        max_num_scheduled_tokens=128,
        max_num_running_requests=4,
        block_lifecycle_observer=authority,
    )
    head = Request(
        request_id="head",
        prompt_tokens=64,
        max_output_tokens=2,
        arrival_ns=0,
    )
    tail = Request(
        request_id="tail",
        prompt_tokens=64,
        max_output_tokens=2,
        arrival_ns=0,
    )
    scheduler.add_request(head)
    scheduler.add_request(tail)
    scheduler.schedule()
    scheduler.append_output_tokens(head.request_id)

    pressured = scheduler.schedule()

    assert pressured.preempted_req_ids == ()
    assert tail.status is RequestStatus.RUNNING
    assert tail.num_computed_tokens == tail.prompt_tokens
    assert reclaim_requests == [CHUNK_BYTES]
    assert ledger.bytes_in(peer) == 0
    assert ledger.bytes_in(ACTIVE) == 3 * CHUNK_BYTES
    assert ledger.bytes_in(FREE_ACCOUNT) == 0
    scheduler.audit()


def test_reclaim_callback_receives_absolute_free_byte_target() -> None:
    peer = "PEER_PROTECTION"
    holder: dict[str, CapacityLedger] = {}
    reclaim_requests: list[int] = []

    def reclaim(required_free_bytes: int) -> bool:
        reclaim_requests.append(required_free_bytes)
        ledger = holder["ledger"]
        additional_bytes = required_free_bytes - ledger.bytes_in(FREE_ACCOUNT)
        if additional_bytes <= 0:
            return True
        if ledger.bytes_in(peer) < additional_bytes:
            return False
        ledger._replace_accounts(
            ledger.preview(
                [
                    AccountTransfer(
                        account_from=peer,
                        account_to=FREE_ACCOUNT,
                        delta_bytes=additional_bytes,
                    )
                ]
            )
        )
        return True

    authority, ledger = _authority(chunks=4, reclaim_free_bytes=reclaim)
    holder["ledger"] = ledger
    ledger._replace_accounts(
        ledger.preview(
            [
                AccountTransfer(
                    account_from=FREE_ACCOUNT,
                    account_to=peer,
                    delta_bytes=2 * CHUNK_BYTES,
                )
            ]
        )
    )

    assert ledger.bytes_in(FREE_ACCOUNT) == 2 * CHUNK_BYTES
    assert authority.try_reclaim_blocks("request", 12)
    assert reclaim_requests == [3 * CHUNK_BYTES]
    assert ledger.bytes_in(FREE_ACCOUNT) == 3 * CHUNK_BYTES


def test_reclaim_retries_when_conservative_binding_hides_first_release() -> None:
    holder: dict[str, CapacityLedger] = {}
    reclaim_requests: list[int] = []

    def reclaim(required_free_bytes: int) -> bool:
        reclaim_requests.append(required_free_bytes)
        ledger = holder["ledger"]
        additional_bytes = required_free_bytes - ledger.bytes_in(FREE_ACCOUNT)
        if additional_bytes <= 0:
            return True
        ledger._replace_accounts(
            ledger.preview(
                [
                    AccountTransfer(
                        account_from=INACTIVE,
                        account_to=FREE_ACCOUNT,
                        delta_bytes=additional_bytes,
                    )
                ]
            )
        )
        return True

    authority, ledger = _authority(
        chunks=4,
        inactive_chunks=2,
        reclaim_free_bytes=reclaim,
    )
    holder["ledger"] = ledger
    authority.bind_inactive_prefix(
        request_id="pinned",
        restored_tokens=64,
        activate=lambda _count: CHUNK_BYTES,
    )

    assert authority.num_free_blocks_for_request("other") == 12
    assert authority.try_reclaim_blocks("other", 16)
    assert reclaim_requests == [3 * CHUNK_BYTES, 4 * CHUNK_BYTES]
    assert ledger.bytes_in(FREE_ACCOUNT) == 4 * CHUNK_BYTES
    assert authority.num_free_blocks_for_request("other") == 16


def test_inactive_prefix_is_zero_copy_reclassified_before_pool_mutation() -> None:
    authority, ledger = _authority(inactive_chunks=2)
    activated: list[int] = []

    def activate(source_chunk_count: int) -> int:
        activated.append(source_chunk_count)
        return source_chunk_count * CHUNK_BYTES

    authority.bind_inactive_prefix(
        request_id="reuse",
        restored_tokens=80,
        activate=activate,
    )
    authority.allocate_blocks(
        (1, 2, 3, 4, 5),
        request_id="reuse",
        cause="zero-copy-prefix",
    )

    assert activated == [2]
    assert ledger.bytes_in(INACTIVE) == 0
    assert ledger.bytes_in(ACTIVE) == 2 * CHUNK_BYTES
    assert ledger.bytes_in(FREE_ACCOUNT) == 2 * CHUNK_BYTES


def test_bound_inactive_prefix_is_private_not_globally_fungible() -> None:
    authority, ledger = _authority(chunks=2, inactive_chunks=2)
    authority.bind_inactive_prefix(
        request_id="owner",
        restored_tokens=128,
        activate=lambda count: count * CHUNK_BYTES,
    )

    assert ledger.bytes_in(FREE_ACCOUNT) == 0
    assert authority.num_free_blocks == 0
    assert authority.num_free_blocks_for_request("owner") == 8
    assert authority.num_free_blocks_for_request("other") == 0


def test_resident_binding_rollback_preserves_reserved_bytes_for_rebind() -> None:
    authority, ledger = _authority(chunks=2)
    ledger._replace_accounts(
        ledger.preview(
            [
                AccountTransfer(
                    account_from=FREE_ACCOUNT,
                    account_to=RECOVERY,
                    delta_bytes=CHUNK_BYTES,
                )
            ]
        )
    )
    authority.observe_external_recovery_reservation(
        request_id="recover",
        reserved_bytes=CHUNK_BYTES,
    )
    authority.bind_resident_interval(
        request_id="recover",
        start_token=0,
        token_count=64,
        account=RECOVERY,
        activate=lambda count: count * CHUNK_BYTES,
    )

    assert authority.unbind_resident_intervals("recover") == CHUNK_BYTES
    assert ledger.bytes_in(RECOVERY) == CHUNK_BYTES
    authority.bind_resident_interval(
        request_id="recover",
        start_token=0,
        token_count=64,
        account=RECOVERY,
        activate=lambda count: count * CHUNK_BYTES,
    )
    authority.allocate_blocks(
        (1, 2, 3, 4),
        request_id="recover",
        cause="rebound",
    )
    assert ledger.bytes_in(RECOVERY) == 0
    assert ledger.bytes_in(ACTIVE) == CHUNK_BYTES


def test_foreground_store_reservation_is_private_and_atomically_adopted() -> None:
    authority, ledger = _authority(chunks=2)
    ledger._replace_accounts(
        ledger.preview(
            [
                AccountTransfer(
                    account_from=FREE_ACCOUNT,
                    account_to=FOREGROUND_STORE,
                    delta_bytes=CHUNK_BYTES,
                )
            ]
        )
    )
    activated: list[int] = []
    authority.bind_resident_interval(
        request_id="store-hit",
        start_token=64,
        token_count=64,
        account=FOREGROUND_STORE,
        activate=lambda count: activated.append(count) or count * CHUNK_BYTES,
    )

    assert authority.num_free_blocks == 4
    assert authority.num_free_blocks_for_request("store-hit") == 8
    assert authority.num_free_blocks_for_request("other") == 4

    authority.allocate_blocks(
        (1, 2, 3, 4, 5, 6, 7, 8),
        request_id="store-hit",
        cause="foreground-store-adoption",
    )

    assert activated == [1]
    assert ledger.bytes_in(FOREGROUND_STORE) == 0
    assert ledger.bytes_in(ACTIVE) == 2 * CHUNK_BYTES
    assert ledger.bytes_in(FREE_ACCOUNT) == 0


def test_inactive_binding_rollback_restores_global_fungibility_without_moving_bytes() -> None:
    authority, ledger = _authority(chunks=2, inactive_chunks=2)
    activated: list[int] = []
    authority.bind_inactive_prefix(
        request_id="inactive-owner",
        restored_tokens=128,
        activate=lambda count: activated.append(count) or count * CHUNK_BYTES,
    )
    before = ledger.accounts

    assert authority.num_free_blocks == 0
    assert authority.num_free_blocks_for_request("inactive-owner") == 8
    assert authority.unbind_resident_intervals("inactive-owner") == 2 * CHUNK_BYTES

    assert authority.num_free_blocks == 8
    assert authority.num_free_blocks_for_request("inactive-owner") == 8
    assert authority.num_free_blocks_for_request("other") == 8
    assert ledger.accounts == before
    assert activated == []
    assert authority.unbind_resident_intervals("inactive-owner") == 0
    authority.audit()


def test_failed_transaction_does_not_publish_logical_ownership() -> None:
    authority, ledger = _authority(chunks=1)
    before = ledger.accounts

    with pytest.raises(ValueError, match="cannot fit physical HBM"):
        authority.allocate_blocks(
            (1, 2, 3, 4, 5),
            request_id="too-large",
            cause="prefill",
        )

    assert ledger.accounts == before
    assert authority.active_block_ids == ()
    assert authority.active_request_ids == ()


def test_transaction_preflight_rejects_before_resident_pool_mutation() -> None:
    journal = EventJournal()
    journal.append(10, "FUTURE_EVENT", {})
    authority, ledger = _authority(
        inactive_chunks=1,
        journal=journal,
        now_ns=lambda: 0,
    )
    activated: list[int] = []
    authority.bind_inactive_prefix(
        request_id="reuse",
        restored_tokens=64,
        activate=lambda count: activated.append(count) or count * CHUNK_BYTES,
    )
    before = ledger.accounts

    with pytest.raises(ValueError, match="journal backwards"):
        authority.allocate_blocks(
            (1, 2, 3, 4),
            request_id="reuse",
            cause="rejected-before-pool-mutation",
        )

    assert activated == []
    assert ledger.accounts == before
    assert authority.active_block_ids == ()


def test_external_recovery_prefix_reclassifies_reserved_chunks_once() -> None:
    authority, ledger = _authority(chunks=3)
    ledger._replace_accounts(
        ledger.preview(
            [
                AccountTransfer(
                    account_from=FREE_ACCOUNT,
                    account_to=RECOVERY,
                    delta_bytes=2 * CHUNK_BYTES,
                )
            ]
        )
    )
    authority.observe_external_recovery_reservation(
        request_id="recover",
        reserved_bytes=2 * CHUNK_BYTES,
    )
    authority.trim_external_recovery_reservation(
        request_id="recover",
        retained_bytes=CHUNK_BYTES,
        cause="release-recompute-suffix",
    )
    authority.bind_resident_interval(
        request_id="recover",
        start_token=0,
        token_count=64,
        account=RECOVERY,
        activate=lambda count: count * CHUNK_BYTES,
    )
    assert authority.num_free_blocks_for_request("recover") == 12
    authority.allocate_blocks(
        (1, 2, 3, 4),
        request_id="recover",
        cause="resume-restored-prefix",
    )

    assert ledger.bytes_in(RECOVERY) == 0
    assert ledger.bytes_in(ACTIVE) == CHUNK_BYTES
    assert ledger.bytes_in(FREE_ACCOUNT) == 2 * CHUNK_BYTES
    authority.audit_scheduler_blocks(
        {1: 1, 2: 1, 3: 1, 4: 1},
        {},
        set(),
    )


@pytest.mark.parametrize("restored_tokens", (32, 64))
def test_native_recovery_commit_allows_rounded_allocation_sharing(
    restored_tokens: int,
) -> None:
    authority, ledger = _authority(chunks=1)
    scheduler = ContinuousBatchScheduler(
        block_pool=BlockPool(5, enable_caching=False),
        block_size_tokens=16,
        max_num_scheduled_tokens=64,
        max_num_running_requests=4,
        block_lifecycle_observer=authority,
    )

    reservation = scheduler.reserve_recovery_prefix(
        "recover",
        restored_tokens=restored_tokens,
    )

    assert len(reservation.block_ids) == restored_tokens // 16
    assert len(reservation.physical_allocation_ids) == 1
    assert len(set(reservation.destination_allocation_ids)) == 1
    assert ledger.bytes_in(RECOVERY) == CHUNK_BYTES
    request = Request(
        request_id="recover",
        prompt_tokens=restored_tokens + 16,
        max_output_tokens=1,
        arrival_ns=0,
    )
    scheduler.commit_recovery_prefix(request, reservation)

    assert scheduler.request_block_ids("recover") == reservation.block_ids
    assert ledger.bytes_in(RECOVERY) == 0
    assert ledger.bytes_in(ACTIVE) == CHUNK_BYTES
    scheduler.finish_request("recover", RequestStatus.FINISHED_STOPPED)
    assert ledger.bytes_in(ACTIVE) == 0
    assert ledger.bytes_in(FREE_ACCOUNT) == CHUNK_BYTES


@pytest.mark.parametrize("restored_tokens", (32, 64))
def test_native_recovery_abort_releases_one_rounded_allocation(
    restored_tokens: int,
) -> None:
    authority, ledger = _authority(chunks=1)
    scheduler = ContinuousBatchScheduler(
        block_pool=BlockPool(5, enable_caching=False),
        block_size_tokens=16,
        max_num_scheduled_tokens=64,
        max_num_running_requests=4,
        block_lifecycle_observer=authority,
    )
    reservation = scheduler.reserve_recovery_prefix(
        "recover",
        restored_tokens=restored_tokens,
    )

    scheduler.abort_recovery_prefix("recover", cause="test.abort-rounded-recovery")

    assert ledger.bytes_in(RECOVERY) == 0
    assert ledger.bytes_in(FREE_ACCOUNT) == CHUNK_BYTES
    assert scheduler.block_pool.num_free_blocks == 4
    assert set(reservation.block_ids) <= set(scheduler.block_pool.free_block_ids)
    scheduler.audit()


def test_external_recovery_backing_cannot_be_mortgaged_twice() -> None:
    authority, ledger = _authority(chunks=1)
    ledger._replace_accounts(
        ledger.preview(
            [
                AccountTransfer(
                    account_from=FREE_ACCOUNT,
                    account_to=RECOVERY,
                    delta_bytes=CHUNK_BYTES,
                )
            ]
        )
    )
    authority.observe_external_recovery_reservation(
        request_id="first",
        reserved_bytes=CHUNK_BYTES,
    )
    activated: list[int] = []
    authority.bind_resident_interval(
        request_id="first",
        start_token=0,
        token_count=64,
        account=RECOVERY,
        activate=lambda count: activated.append(count) or count * CHUNK_BYTES,
    )
    before = ledger.accounts

    with pytest.raises(ValueError, match="exceeds its per-request reservation"):
        authority.bind_resident_interval(
            request_id="first",
            start_token=64,
            token_count=64,
            account=RECOVERY,
            activate=lambda count: count * CHUNK_BYTES,
        )
    with pytest.raises(ValueError, match="unowned RESERVED bytes"):
        authority.observe_external_recovery_reservation(
            request_id="second",
            reserved_bytes=CHUNK_BYTES,
        )
    with pytest.raises(ValueError, match="lacks a per-request external reservation"):
        authority.bind_resident_interval(
            request_id="second",
            start_token=0,
            token_count=64,
            account=RECOVERY,
            activate=lambda count: count * CHUNK_BYTES,
        )

    assert ledger.accounts == before
    assert activated == []
    assert authority.num_free_blocks_for_request("first") == 4
    assert authority.num_free_blocks_for_request("second") == 0
    authority.allocate_blocks(
        (1, 2, 3, 4),
        request_id="first",
        cause="consume-unique-recovery-backing",
    )
    assert activated == [1]
    assert ledger.bytes_in(RECOVERY) == 0
    assert ledger.bytes_in(ACTIVE) == CHUNK_BYTES


def test_cross_request_recovery_allocation_collision_rolls_back_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, ledger = _authority(chunks=2)
    scheduler = ContinuousBatchScheduler(
        block_pool=BlockPool(9, enable_caching=False),
        block_size_tokens=16,
        max_num_scheduled_tokens=64,
        max_num_running_requests=4,
        block_lifecycle_observer=authority,
    )
    original_reserve = ExperimentHBMAuthority.reserve_recovery_blocks
    first_destination: tuple[tuple[str, ...], ...] | None = None

    def reserve_with_collision(
        self: ExperimentHBMAuthority,
        block_ids: tuple[int, ...],
        *,
        request_id: str,
        cause: str,
    ) -> tuple[tuple[str, ...], ...]:
        nonlocal first_destination
        destination = original_reserve(
            self,
            block_ids,
            request_id=request_id,
            cause=cause,
        )
        if first_destination is None:
            first_destination = destination
            return destination
        return first_destination

    monkeypatch.setattr(
        ExperimentHBMAuthority,
        "reserve_recovery_blocks",
        reserve_with_collision,
    )
    first = scheduler.reserve_recovery_prefix("first", restored_tokens=16)
    before_second = ledger.accounts

    with pytest.raises(ValueError, match="shared across requests"):
        scheduler.reserve_recovery_prefix("second", restored_tokens=16)

    assert ledger.accounts == before_second
    assert ledger.bytes_in(RECOVERY) == CHUNK_BYTES
    assert scheduler.recovery_prefix_reservation("first") == first
    with pytest.raises(KeyError, match="second"):
        scheduler.recovery_prefix_reservation("second")
    assert scheduler.block_pool.num_free_blocks == 7
    scheduler.audit()


def test_external_failure_clears_logical_state_without_second_release() -> None:
    authority, ledger = _authority(chunks=2)
    authority.allocate_blocks((1,), request_id="r0", cause="prefill")
    accounts = ledger.preview(
        [
            AccountTransfer(
                account_from=account,
                account_to=UNAVAILABLE_CAPACITY_ACCOUNT,
                delta_bytes=value,
            )
            for account, value in ledger.accounts.items()
            if account != UNAVAILABLE_CAPACITY_ACCOUNT and value > 0
        ]
    )
    ledger._replace_accounts(accounts)

    authority.observe_external_failure()

    assert authority.failed is True
    assert authority.active_block_ids == ()
    assert ledger.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT) == ledger.capacity_bytes
