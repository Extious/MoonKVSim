from fractions import Fraction

import pytest

from moonkvsim.aegiskv.recovery_harm import (
    AdmissionHarmDelta,
    RecoveryHarmSnapshot,
    RecoveryTimeBreakdown,
    VictimSetHarmDelta,
    current_design_rental_value,
)
from moonkvsim.aegiskv.types import PolicyPool, SealedChunk, SlackSignal


def _snapshot(
    request_id: str,
    *,
    pool: PolicyPool = PolicyPool.PEER_HBM,
    load: int = 0,
    recompute: int = 0,
    replay: int = 0,
    collective: int = 0,
    slack: int = 0,
    observed_at_ns: int = 5,
    evaluated_at_ns: int = 5,
) -> RecoveryHarmSnapshot:
    return RecoveryHarmSnapshot(
        request_id=request_id,
        pool=pool,
        evaluated_at_ns=evaluated_at_ns,
        slack=SlackSignal(
            slack_at_observation_ns=Fraction(slack, 1),
            observed_at_ns=observed_at_ns,
            version=1,
        ),
        recovery_time=RecoveryTimeBreakdown(
            load_ns=Fraction(load, 1),
            prompt_suffix_recompute_ns=Fraction(recompute, 1),
            silent_replay_ns=Fraction(replay, 1),
            collective_sync_ns=Fraction(collective, 1),
        ),
    )


def test_candidate_gain_uses_remaining_slack_and_complete_recovery_time() -> None:
    before = _snapshot(
        "request-0",
        load=2,
        recompute=10,
        replay=4,
        collective=3,
        slack=12,
        evaluated_at_ns=8,
    )
    after = _snapshot(
        "request-0",
        load=5,
        recompute=2,
        replay=4,
        collective=3,
        slack=12,
        evaluated_at_ns=8,
    )

    # Remaining Slack is 9 ns: J_before=19-9=10 and J_after=14-9=5.
    assert before.slack_at_evaluation_ns == 9
    assert AdmissionHarmDelta(before, after).gain_ns == 5


def test_slack_can_mask_a_candidate_without_creating_negative_gain() -> None:
    before = _snapshot("request-0", recompute=8, slack=20)
    after = _snapshot("request-0", load=3, recompute=2, slack=20)

    delta = AdmissionHarmDelta(before, after)

    assert before.harm_ns == 0
    assert after.harm_ns == 0
    assert delta.gain_ns == 0


def test_joint_victim_loss_is_computed_from_one_state_per_request() -> None:
    before = _snapshot("request-0", recompute=10)
    after_two_suffix_evictions = _snapshot("request-0", recompute=16)

    delta = VictimSetHarmDelta((before,), (after_two_suffix_evictions,))

    # The complete state transition costs 6 ns.  The kernel never adds two
    # independent per-chunk loss estimates that could double-count interactions.
    assert delta.joint_loss_ns == 6


def test_joint_victim_loss_sums_only_after_grouping_by_affected_request() -> None:
    before_a = _snapshot("request-a", recompute=10, slack=3)
    after_a = _snapshot("request-a", recompute=14, slack=3)
    before_b = _snapshot("request-b", recompute=8, slack=20)
    after_b = _snapshot("request-b", recompute=12, slack=20)

    delta = VictimSetHarmDelta((before_a, before_b), (after_a, after_b))

    assert delta.joint_loss_ns == 4


def test_cross_tier_snapshots_cannot_be_compared() -> None:
    before = _snapshot("request-0", pool=PolicyPool.PEER_HBM, recompute=10)
    after = _snapshot("request-0", pool=PolicyPool.STORE_DRAM, recompute=5)

    with pytest.raises(ValueError, match="different policy pools"):
        AdmissionHarmDelta(before, after)


def test_joint_loss_rejects_duplicate_or_mismatched_request_sets() -> None:
    before = _snapshot("request-0", recompute=10)
    after = _snapshot("request-0", recompute=12)

    with pytest.raises(ValueError, match="duplicate request"):
        VictimSetHarmDelta((before, before), (after,))
    with pytest.raises(ValueError, match="request sets must match"):
        VictimSetHarmDelta((before,), (_snapshot("request-1", recompute=12),))


def test_current_design_rental_value_contains_only_recovery_harm_gain() -> None:
    before = _snapshot("request-0", load=2, recompute=10, replay=4, slack=3)
    after = _snapshot("request-0", load=4, recompute=3, replay=4, slack=3)
    candidate = SealedChunk(
        chunk_id="peer:request-0:0",
        request_id="request-0",
        sequence_index=0,
        allocated_bytes=5,
    )

    value = current_design_rental_value(
        candidate=candidate,
        before=before,
        after=after,
        pool_rent=Fraction(2, 1),
        frontier_version=7,
    )

    assert value.workflow_recovery_benefit == AdmissionHarmDelta(before, after).gain_ns
    assert value.hit_utility == 0
    assert value.lru_utility == 0
    assert value.composite_benefit == value.workflow_recovery_benefit
    assert value.rental_key == Fraction(2, 1) + value.composite_benefit / 5
