from __future__ import annotations

from fractions import Fraction

import pytest

from moonkvsim.aegiskv.lazy_refresh import RefreshTrigger
from moonkvsim.aegiskv.rental_value import (
    RentalValue,
    RentalValueInputs,
    compute_rental_value,
)
from moonkvsim.aegiskv.slack_landlord import (
    JOINT_LOSS_INTERPRETATION,
    JOINT_LOSS_REVIEW_STATUS,
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
    assert {
        check.trigger for check in preview.refresh_checks
    } <= {RefreshTrigger.HEAP_TOP, RefreshTrigger.NEWLY_EXPOSED}

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
