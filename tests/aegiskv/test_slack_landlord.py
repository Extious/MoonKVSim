from __future__ import annotations

from fractions import Fraction

import pytest

from moonkvsim.aegiskv.lazy_refresh import RefreshTrigger, RentalEntry
from moonkvsim.aegiskv.recovery_harm import (
    AdmissionHarmDelta,
    RecoveryHarmSnapshot,
    RecoveryTimeBreakdown,
    VictimSetHarmDelta,
    current_design_rental_value,
)
from moonkvsim.aegiskv.rental_value import (
    RentalValue,
    RentalValueInputs,
    compute_rental_value,
)
from moonkvsim.aegiskv.slack_landlord import (
    EXACT_JOINT_LOSS_INTERPRETATION,
    EXACT_JOINT_LOSS_REVIEW_STATUS,
    JOINT_LOSS_INTERPRETATION,
    JOINT_LOSS_REVIEW_STATUS,
    PoolLifecycleAction,
    SlackLandlord,
    StalePreviewError,
)
from moonkvsim.aegiskv.types import (
    AdmissionOutcome,
    PathCommitState,
    PolicyPool,
    RentalSignals,
    RentalWeights,
    SealedChunk,
    SignalVersions,
    SlackSignal,
)


def _inputs(
    chunk_id: str,
    request_id: str,
    sequence_index: int,
    allocated_bytes: int,
    benefit: Fraction,
    *,
    pool: PolicyPool = PolicyPool.PEER_HBM,
    rent: Fraction = Fraction(0, 1),
    now_ns: int = 10,
    version: int = 1,
) -> RentalValueInputs:
    return RentalValueInputs(
        candidate=SealedChunk(
            chunk_id=chunk_id,
            request_id=request_id,
            sequence_index=sequence_index,
            allocated_bytes=allocated_bytes,
        ),
        pool=pool,
        signals=RentalSignals(
            slack=SlackSignal(Fraction(0, 1), observed_at_ns=0, version=version),
            hit_probability=Fraction(0, 1),
            reuse_saving=Fraction(0, 1),
            lru_utility=Fraction(0, 1),
            last_access_ns=0,
            versions=SignalVersions(version, version, version, version),
        ),
        recovery_time_before=benefit,
        recovery_time_after=Fraction(0, 1),
        weights=RentalWeights(Fraction(1, 1), Fraction(0, 1), Fraction(0, 1)),
        pool_rent=rent,
        now_ns=now_ns,
    )


def _value(
    chunk_id: str,
    request_id: str,
    sequence_index: int,
    allocated_bytes: int,
    benefit: Fraction,
    *,
    pool: PolicyPool = PolicyPool.PEER_HBM,
    rent: Fraction = Fraction(0, 1),
    now_ns: int = 10,
    version: int = 1,
) -> RentalValue:
    return compute_rental_value(
        _inputs(
            chunk_id,
            request_id,
            sequence_index,
            allocated_bytes,
            benefit,
            pool=pool,
            rent=rent,
            now_ns=now_ns,
            version=version,
        )
    )


def _harm_snapshot(
    request_id: str,
    total_ns: int,
    *,
    pool: PolicyPool = PolicyPool.PEER_HBM,
    now_ns: int = 10,
) -> RecoveryHarmSnapshot:
    return RecoveryHarmSnapshot(
        request_id=request_id,
        pool=pool,
        evaluated_at_ns=now_ns,
        slack=SlackSignal(Fraction(0, 1), observed_at_ns=0, version=1),
        recovery_time=RecoveryTimeBreakdown(
            load_ns=Fraction(0, 1),
            prompt_suffix_recompute_ns=Fraction(total_ns, 1),
            silent_replay_ns=Fraction(0, 1),
        ),
    )


def _exact_value(
    chunk_id: str,
    request_id: str,
    sequence_index: int,
    allocated_bytes: int,
    before_ns: int,
    after_ns: int,
    *,
    rent: Fraction = Fraction(0, 1),
) -> tuple[RentalValue, AdmissionHarmDelta]:
    candidate = SealedChunk(
        chunk_id=chunk_id,
        request_id=request_id,
        sequence_index=sequence_index,
        allocated_bytes=allocated_bytes,
    )
    delta = AdmissionHarmDelta(
        before=_harm_snapshot(request_id, before_ns),
        after=_harm_snapshot(request_id, after_ns),
    )
    return (
        current_design_rental_value(
            candidate=candidate,
            before=delta.before,
            after=delta.after,
            pool_rent=rent,
            frontier_version=1,
        ),
        delta,
    )


def test_two_level_index_contains_only_contiguous_request_tails() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=20)
    a0 = _value("a:0", "a", 0, 4, Fraction(4, 1))
    a1 = _value("a:1", "a", 1, 4, Fraction(8, 1))
    b0 = _value("b:0", "b", 0, 4, Fraction(12, 1))

    landlord.register_committed(a0)
    assert list(landlord.heap_chunk_ids) == ["a:0"]
    landlord.register_committed(a1)
    landlord.register_committed(b0)

    assert list(landlord.heap_chunk_ids) == ["a:1", "b:0"]
    assert [entry.chunk_id for entry in landlord.committed_entries("a")] == ["a:0", "a:1"]
    with pytest.raises(ValueError, match="contiguous"):
        landlord.register_committed(_value("a:3", "a", 3, 1, Fraction(1, 1)))


def test_pool_rents_are_independent_and_pending_never_enters_heap() -> None:
    hbm = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=5)
    dram = SlackLandlord(pool=PolicyPool.STORE_DRAM, capacity_bytes=5)
    victim = _value("old", "old-request", 0, 5, Fraction(5, 1))
    hbm.register_committed(victim)
    candidate = _value("new", "new-request", 0, 5, Fraction(10, 1))

    preview = hbm.preview(candidate, latest_values={"old": victim})
    pending = hbm.apply(preview)

    assert pending is not None
    assert pending.state is PathCommitState.PENDING
    assert hbm.rent == Fraction(1, 1)
    assert dram.rent == Fraction(0, 1)
    assert list(hbm.pending_chunk_ids) == ["new"]
    assert "new" not in hbm.heap_chunk_ids

    aborted = hbm.abort_pending("new")
    assert aborted.state is PathCommitState.ABORTED
    assert not hbm.pending_chunk_ids
    assert hbm.free_bytes == 5


def test_multiple_pending_chunks_extend_one_request_and_commit_in_sequence() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=15)
    r0 = _value("r:0", "r", 0, 5, Fraction(3, 1))
    landlord.register_committed(r0)

    r1 = _value("r:1", "r", 1, 5, Fraction(6, 1))
    r1_pending = landlord.apply(landlord.preview(r1, latest_values={}))
    assert r1_pending is not None
    r2 = _value("r:2", "r", 2, 5, Fraction(9, 1))
    r2_pending = landlord.apply(landlord.preview(r2, latest_values={}))
    assert r2_pending is not None

    assert landlord.pending_chunk_ids == ("r:1", "r:2")
    assert landlord.heap_chunk_ids == ()
    with pytest.raises(ValueError, match="earliest PENDING sequence"):
        landlord.complete_pending_value("r:2", latest_value=r2)

    first = landlord.complete_pending_value("r:1", latest_value=r1)
    assert first.state is PathCommitState.COMMITTED
    assert [entry.chunk_id for entry in landlord.committed_entries("r")] == [
        "r:0",
        "r:1",
    ]
    assert landlord.heap_chunk_ids == ()

    second = landlord.complete_pending_value("r:2", latest_value=r2)
    assert second.state is PathCommitState.COMMITTED
    assert [entry.chunk_id for entry in landlord.committed_entries("r")] == [
        "r:0",
        "r:1",
        "r:2",
    ]
    assert list(landlord.heap_chunk_ids) == ["r:2"]


def test_pending_successor_protects_committed_tail_from_eviction() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=15)
    protected = _value("a:0", "a", 0, 5, Fraction(1, 1))
    evictable = _value("b:0", "b", 0, 5, Fraction(4, 1))
    landlord.register_committed(protected)
    landlord.register_committed(evictable)
    pending = _value("a:1", "a", 1, 5, Fraction(2, 1))
    assert landlord.apply(landlord.preview(pending, latest_values={})) is not None

    assert landlord.heap_chunk_ids == ("b:0",)
    candidate = _value("c:0", "c", 0, 5, Fraction(10, 1))
    preview = landlord.preview(candidate, latest_values={"b:0": evictable})

    assert preview.outcome is AdmissionOutcome.ADMIT
    assert [entry.chunk_id for entry in preview.selected_victims] == ["b:0"]


def test_abort_pending_allows_only_latest_suffix_tail_and_preserves_frontier() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=15)
    for sequence_index in range(3):
        value = _value(
            f"r:{sequence_index}",
            "r",
            sequence_index,
            5,
            Fraction(sequence_index + 1, 1),
        )
        assert landlord.apply(landlord.preview(value, latest_values={})) is not None

    with pytest.raises(ValueError, match="latest PENDING suffix tail"):
        landlord.abort_pending("r:1")

    resolution = landlord.abort_pending("r:2")
    assert resolution.state is PathCommitState.ABORTED
    replacement = _value("r:2-retry", "r", 2, 5, Fraction(4, 1))
    assert landlord.apply(landlord.preview(replacement, latest_values={})) is not None
    assert landlord.pending_chunk_ids == ("r:0", "r:1", "r:2-retry")

    landlord.abort_pending("r:2-retry")
    landlord.abort_pending("r:1")
    landlord.abort_pending("r:0")
    assert not list(landlord.pending_chunk_ids)
    assert landlord.free_bytes == landlord.capacity_bytes


def test_preview_is_temporary_and_uses_only_top_or_newly_exposed_refresh() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=10)
    a0 = _value("a:0", "a", 0, 4, Fraction(4, 1))
    a1 = _value("a:1", "a", 1, 4, Fraction(8, 1))
    b0 = _value("b:0", "b", 0, 2, Fraction(2, 1))
    for value in (a0, a1, b0):
        landlord.register_committed(value)
    candidate = _value("c:0", "c", 0, 8, Fraction(80, 1))
    latest_a0 = _value(
        "a:0",
        "a",
        0,
        4,
        Fraction(6, 1),
        now_ns=12,
        version=2,
    )
    before = landlord.to_canonical_json()

    preview = landlord.preview(
        candidate,
        latest_values={"a:0": latest_a0, "a:1": a1, "b:0": b0},
    )

    assert landlord.to_canonical_json() == before
    assert preview.outcome is AdmissionOutcome.ADMIT
    assert [entry.chunk_id for entry in preview.selected_victims] == ["b:0", "a:1", "a:0"]
    assert preview.joint_loss == Fraction(16, 1)
    assert preview.joint_loss_interpretation == JOINT_LOSS_INTERPRETATION
    assert preview.interpretation_review_status == JOINT_LOSS_REVIEW_STATUS
    assert preview.manual_review_confirmed is False
    assert any(
        check.trigger is RefreshTrigger.NEWLY_EXPOSED
        and check.after.chunk_id == "a:0"
        and check.refreshed
        for check in preview.refresh_checks
    )
    assert {check.trigger for check in preview.refresh_checks} <= {
        RefreshTrigger.HEAP_TOP,
        RefreshTrigger.NEWLY_EXPOSED,
    }

    pending = landlord.apply(preview)
    assert pending is not None
    assert landlord.rent == Fraction(2, 1)
    assert list(landlord.pending_chunk_ids) == ["c:0"]
    assert not landlord.heap_chunk_ids

    completion_inputs = _inputs(
        "c:0",
        "c",
        0,
        8,
        Fraction(72, 1),
        rent=landlord.rent,
        now_ns=20,
        version=3,
    )
    resolution = landlord.complete_pending("c:0", latest_inputs=completion_inputs)
    assert resolution.state is PathCommitState.COMMITTED
    assert not landlord.pending_chunk_ids
    assert list(landlord.heap_chunk_ids) == ["c:0"]
    assert landlord.committed_entries("c")[0].value.composite_benefit == Fraction(72, 1)
    assert landlord.committed_entries("c")[0].value.rental_key == Fraction(11, 1)


def test_candidate_request_is_skipped_as_a_whole() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=5)
    own_tail = _value("r:0", "r", 0, 5, Fraction(5, 1))
    landlord.register_committed(own_tail)
    candidate = _value("r:1", "r", 1, 5, Fraction(10, 1))

    preview = landlord.preview(candidate, latest_values={})

    assert preview.outcome is AdmissionOutcome.BYPASS
    assert preview.selected_victims == ()
    assert preview.refresh_checks == ()
    assert landlord.committed_entries("r")[0].chunk_id == "r:0"


def test_apply_persists_a_newly_exposed_survivors_latest_signal_value() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=10)
    a0 = _value("a:0", "a", 0, 5, Fraction(5, 1))
    a1 = _value("a:1", "a", 1, 5, Fraction(5, 1))
    landlord.register_committed(a0)
    landlord.register_committed(a1)
    latest_a0 = _value(
        "a:0",
        "a",
        0,
        5,
        Fraction(10, 1),
        now_ns=12,
        version=2,
    )
    candidate = _value("c:0", "c", 0, 5, Fraction(20, 1))

    preview = landlord.preview(
        candidate,
        latest_values={"a:0": latest_a0, "a:1": a1},
    )
    pending = landlord.apply(preview)

    assert pending is not None
    assert [entry.chunk_id for entry in landlord.committed_entries("a")] == ["a:0"]
    assert landlord.committed_entries("a")[0].value.composite_benefit == Fraction(10, 1)
    assert any(
        check.trigger is RefreshTrigger.NEWLY_EXPOSED and check.refreshed
        for check in preview.refresh_checks
    )


def test_strict_h_and_joint_loss_boundaries_and_zero_gain_bypass() -> None:
    equal_h = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=5)
    victim_h1 = _value("h-victim", "v", 0, 5, Fraction(5, 1))
    candidate_h1 = _value("h-candidate", "x", 0, 5, Fraction(5, 1))
    equal_h.register_committed(victim_h1)
    h_preview = equal_h.preview(candidate_h1, latest_values={"h-victim": victim_h1})
    assert h_preview.outcome is AdmissionOutcome.BYPASS
    assert h_preview.bypass_reason == "VICTIM_KEY_NOT_STRICTLY_BELOW_THRESHOLD"

    equal_g = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=10)
    victim_g10 = _value("g-victim", "v", 0, 10, Fraction(10, 1))
    candidate_g10 = _value("g-candidate", "x", 0, 5, Fraction(10, 1))
    equal_g.register_committed(victim_g10)
    g_preview = equal_g.preview(candidate_g10, latest_values={"g-victim": victim_g10})
    assert g_preview.selected_victims[0].chunk_id == "g-victim"
    assert g_preview.joint_loss == candidate_g10.composite_benefit
    assert g_preview.outcome is AdmissionOutcome.BYPASS
    assert g_preview.bypass_reason == "CANDIDATE_G_NOT_STRICTLY_ABOVE_JOINT_LOSS"

    idle = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=5)
    zero = _value("zero", "z", 0, 5, Fraction(0, 1))
    zero_preview = idle.preview(zero, latest_values={})
    assert zero_preview.outcome is AdmissionOutcome.BYPASS
    assert zero_preview.joint_loss == Fraction(0, 1)


def test_exact_joint_loss_recomputes_victim_set_once_per_request() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=10)
    r0, _ = _exact_value("r:0", "r", 0, 5, 4, 2)
    r1, _ = _exact_value("r:1", "r", 1, 5, 4, 2)
    landlord.register_committed(r0)
    landlord.register_committed(r1)
    candidate, candidate_gain = _exact_value("c:0", "c", 0, 10, 9, 1)

    def exact_joint_loss(victims: tuple[RentalEntry, ...]) -> VictimSetHarmDelta:
        assert [item.chunk_id for item in victims] == ["r:1", "r:0"]
        return VictimSetHarmDelta(
            before_by_request=(_harm_snapshot("r", 0),),
            after_by_request=(_harm_snapshot("r", 9),),
        )

    preview = landlord.preview(
        candidate,
        latest_values={"r:0": r0, "r:1": r1},
        candidate_gain_evidence=candidate_gain,
        joint_loss_provider=exact_joint_loss,
    )

    assert preview.joint_loss == Fraction(9, 1)
    assert sum(item.value.composite_benefit for item in preview.selected_victims) == Fraction(4, 1)
    assert preview.outcome is AdmissionOutcome.BYPASS
    assert preview.bypass_reason == "CANDIDATE_G_NOT_STRICTLY_ABOVE_JOINT_LOSS"
    assert preview.joint_loss_interpretation == EXACT_JOINT_LOSS_INTERPRETATION
    assert preview.interpretation_review_status == EXACT_JOINT_LOSS_REVIEW_STATUS
    assert preview.joint_loss_evidence is not None


def test_exact_joint_loss_includes_requests_sharing_a_physical_victim() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=5)
    victim, _ = _exact_value("shared:0", "owner", 0, 5, 4, 2)
    landlord.register_committed(victim)
    candidate, candidate_gain = _exact_value("candidate:0", "candidate", 0, 5, 12, 1)

    def shared_joint_loss(victims: tuple[RentalEntry, ...]) -> VictimSetHarmDelta:
        assert [item.chunk_id for item in victims] == ["shared:0"]
        return VictimSetHarmDelta(
            before_by_request=(
                _harm_snapshot("owner", 0),
                _harm_snapshot("alias", 0),
            ),
            after_by_request=(
                _harm_snapshot("owner", 3),
                _harm_snapshot("alias", 5),
            ),
        )

    preview = landlord.preview(
        candidate,
        latest_values={"shared:0": victim},
        candidate_gain_evidence=candidate_gain,
        joint_loss_provider=shared_joint_loss,
    )

    assert preview.outcome is AdmissionOutcome.ADMIT
    assert preview.joint_loss == Fraction(8, 1)
    assert preview.joint_loss_evidence is not None
    assert {
        item.request_id for item in preview.joint_loss_evidence.before_by_request
    } == {"owner", "alias"}


def test_alias_dependent_physical_victim_is_excluded_for_candidate_request() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=5)
    victim, _ = _exact_value("shared:0", "owner", 0, 5, 4, 2)
    landlord.register_committed(victim)
    candidate, candidate_gain = _exact_value("candidate:0", "alias", 0, 5, 12, 1)

    preview = landlord.preview(
        candidate,
        latest_values={"shared:0": victim},
        candidate_gain_evidence=candidate_gain,
        joint_loss_provider=lambda _victims: pytest.fail(
            "an alias-dependent victim must never enter the tentative set"
        ),
        excluded_victim_chunk_ids=frozenset({"shared:0"}),
    )

    assert preview.outcome is AdmissionOutcome.BYPASS
    assert preview.bypass_reason == "INSUFFICIENT_CAPACITY_OR_NO_LEGAL_VICTIM"
    assert preview.selected_victims == ()
    assert preview.excluded_victim_chunk_ids == ("shared:0",)


def test_apply_rejects_preview_after_any_epoch_change() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=10)
    victim = _value("victim", "v", 0, 5, Fraction(5, 1))
    landlord.register_committed(victim)
    candidate = _value("candidate", "c", 0, 10, Fraction(20, 1))
    preview = landlord.preview(candidate, latest_values={"victim": victim})
    assert preview.outcome is AdmissionOutcome.ADMIT

    landlord.register_committed(_value("concurrent", "q", 0, 5, Fraction(15, 1)))

    with pytest.raises(StalePreviewError, match="epoch"):
        landlord.apply(preview)


def test_explicit_release_accepts_only_exact_suffix_and_preserves_rent_history() -> None:
    landlord = SlackLandlord(
        pool=PolicyPool.PEER_HBM,
        capacity_bytes=15,
        initial_rent=Fraction(2, 1),
    )
    a0 = _value("a:0", "a", 0, 5, Fraction(5, 1), rent=landlord.rent)
    a1 = _value("a:1", "a", 1, 5, Fraction(10, 1), rent=landlord.rent)
    a2 = _value("a:2", "a", 2, 5, Fraction(15, 1), rent=landlord.rent)
    for value in (a0, a1, a2):
        landlord.register_committed(value)

    with pytest.raises(ValueError, match="exactly match"):
        landlord.release_committed_suffix(
            "a",
            ("a:1",),
            cause="UNSAFE_NON_TAIL_RELEASE",
        )

    resolution = landlord.release_committed_suffix(
        "a",
        ("a:1", "a:2"),
        cause="REQUEST_LIFECYCLE_RELEASE",
    )

    assert resolution.action is PoolLifecycleAction.EXPLICIT_SUFFIX_RELEASE
    assert resolution.released_bytes == 10
    assert resolution.rent_before == resolution.rent_after == Fraction(2, 1)
    assert [entry.chunk_id for entry in landlord.committed_entries("a")] == ["a:0"]
    assert landlord.heap_chunk_ids == ("a:0",)
    assert resolution.to_canonical_json()["cause"] == "REQUEST_LIFECYCLE_RELEASE"
    with pytest.raises(ValueError, match="already known"):
        landlord.register_committed(a1)


def test_capacity_contraction_evicts_only_successively_exposed_minimum_tails() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=15)
    a0 = _value("a:0", "a", 0, 5, Fraction(20, 1))
    a1 = _value("a:1", "a", 1, 5, Fraction(5, 1))
    b0 = _value("b:0", "b", 0, 5, Fraction(10, 1))
    for value in (a0, a1, b0):
        landlord.register_committed(value)

    preview = landlord.preview_capacity_change(
        5,
        latest_values={"a:0": a0, "a:1": a1, "b:0": b0},
    )

    assert [entry.chunk_id for entry in preview.selected_victims] == ["a:1", "b:0"]
    assert any(
        check.trigger is RefreshTrigger.NEWLY_EXPOSED and check.after.chunk_id == "a:0"
        for check in preview.refresh_checks
    )
    resolution = landlord.apply_capacity_change(preview, cause="AIMD_QUOTA_CONTRACTION")

    assert resolution.action is PoolLifecycleAction.CAPACITY_CHANGE
    assert landlord.capacity_bytes == landlord.committed_bytes == 5
    assert [entry.chunk_id for entry in landlord.committed_entries("a")] == ["a:0"]
    assert landlord.committed_entries("b") == ()
    assert landlord.rent == Fraction(2, 1)
    # The hidden predecessor retained its historical H=4.  Advancing rent did
    # not reconstruct it as current-rent + full original credit.
    assert landlord.committed_entries("a")[0].value.rental_key == Fraction(4, 1)

    expanded = landlord.change_capacity(
        15,
        latest_values={},
        cause="AIMD_QUOTA_INCREASE",
    )
    assert expanded.released_entries == ()
    assert landlord.capacity_bytes == 15
    assert landlord.rent == Fraction(2, 1)


def test_capacity_contraction_fails_closed_below_pending_bytes_and_on_stale_plan() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=10)
    candidate = _value("pending", "p", 0, 5, Fraction(5, 1))
    pending_preview = landlord.preview(candidate, latest_values={})
    pending = landlord.apply(pending_preview)
    assert pending is not None

    with pytest.raises(ValueError, match="below PENDING bytes"):
        landlord.preview_capacity_change(4, latest_values={})

    landlord.abort_pending("pending")
    resident = _value("resident", "r", 0, 5, Fraction(5, 1))
    landlord.register_committed(resident)
    capacity_preview = landlord.preview_capacity_change(
        5,
        latest_values={"resident": resident},
    )
    landlord.register_committed(_value("other", "q", 0, 5, Fraction(10, 1)))
    with pytest.raises(StalePreviewError, match="epoch"):
        landlord.apply_capacity_change(capacity_preview, cause="STALE_AIMD_PLAN")


def test_capacity_reclaim_keeps_a_recovery_read_pin_and_its_prefix() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=15)
    entries = (
        _value("a:0", "a", 0, 5, Fraction(1)),
        _value("a:1", "a", 1, 5, Fraction(1)),
        _value("b:0", "b", 0, 5, Fraction(10)),
    )
    for value in entries:
        landlord.register_committed(value)
    preview = landlord.preview_capacity_change(
        10, latest_values={v.candidate.chunk_id: v for v in entries},
        excluded_chunk_ids=frozenset({"a:1"}),
    )
    assert [v.chunk_id for v in preview.selected_victims] == ["b:0"]
    landlord.apply_capacity_change(preview, cause="PRIMARY_CAPACITY_RECLAIM")
    assert [v.chunk_id for v in landlord.committed_entries("a")] == ["a:0", "a:1"]


def test_failure_domain_invalidation_clears_committed_and_pending_without_rent_refund() -> None:
    landlord = SlackLandlord(pool=PolicyPool.PEER_HBM, capacity_bytes=10)
    victim = _value("victim", "v", 0, 10, Fraction(10, 1))
    landlord.register_committed(victim)
    replacement = _value("replacement", "r", 0, 10, Fraction(20, 1))
    replacement_preview = landlord.preview(
        replacement,
        latest_values={"victim": victim},
    )
    assert landlord.apply(replacement_preview) is not None
    landlord.complete_pending(
        "replacement",
        latest_inputs=_inputs(
            "replacement",
            "r",
            0,
            10,
            Fraction(20, 1),
            rent=landlord.rent,
            now_ns=20,
            version=2,
        ),
    )
    landlord.change_capacity(15, latest_values={}, cause="PRE_FAILURE_EXPANSION")
    pending_candidate = _value(
        "pending-after-rent",
        "p",
        0,
        5,
        Fraction(5, 1),
        rent=landlord.rent,
        now_ns=20,
        version=2,
    )
    pending_preview = landlord.preview(pending_candidate, latest_values={})
    assert landlord.apply(pending_preview) is not None
    rent_before_failure = landlord.rent

    invalidated = landlord.invalidate_failure_domain(cause="GPU_FAILURE:gpu-3")

    assert invalidated.action is PoolLifecycleAction.FAILURE_DOMAIN_INVALIDATE
    assert [entry.chunk_id for entry in invalidated.released_entries] == ["replacement"]
    assert [item.chunk_id for item in invalidated.aborted_pending] == ["pending-after-rent"]
    assert landlord.available is False
    assert landlord.free_bytes == 0
    assert landlord.committed_bytes == landlord.pending_bytes == 0
    assert landlord.rent == rent_before_failure
    unavailable_candidate = _value(
        "while-failed",
        "failed-request",
        0,
        5,
        Fraction(100, 1),
        rent=landlord.rent,
        now_ns=20,
        version=2,
    )
    bypass = landlord.preview(unavailable_candidate, latest_values={})
    assert bypass.outcome is AdmissionOutcome.BYPASS
    assert bypass.bypass_reason == "FAILURE_DOMAIN_UNAVAILABLE"

    restored = landlord.restore_failure_domain(
        cause="GPU_REPAIR:gpu-3",
        capacity_bytes=10,
    )
    assert restored.action is PoolLifecycleAction.FAILURE_DOMAIN_RESTORE
    assert landlord.available is True
    assert landlord.capacity_bytes == 10
    assert landlord.rent == rent_before_failure
    with pytest.raises(ValueError, match="already known"):
        landlord.register_committed(
            _value(
                "replacement",
                "r",
                0,
                10,
                Fraction(20, 1),
                rent=landlord.rent,
                now_ns=20,
                version=2,
            )
        )
