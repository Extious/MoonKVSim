from dataclasses import replace

import pytest

from moonkvsim.aegiskv.guarded_aimd import AIMDObservation, GuardedAIMD


def observation(n, **kwargs):
    return AIMDObservation(
        n,
        n * 50,
        **{
            "memory_cap_bytes": 800,
            "physical_backup_bytes": 0,
            "reclaim_bytes": 0,
            "warning": False,
            "valid": True,
            "demand": True,
            "adjustment_complete": True,
            **kwargs,
        },
    )


def governor():
    return GuardedAIMD(
        denominator_bytes=1000,
        policy_cap_bytes=800,
        additive_bytes=100,
        stable_windows=2,
        window_ns=50,
    )


def test_stable_growth_multiplicative_warning_and_memory_clip():
    c = governor()
    assert c.observe(observation(0)).quota_bytes == 0
    assert c.observe(observation(1)).quota_bytes == 100
    assert c.observe(observation(2)).quota_bytes == 100
    assert c.observe(observation(3)).quota_bytes == 200
    r = c.observe(observation(4, warning=True, physical_backup_bytes=180))
    assert (r.quota_bytes, r.reclaim_needed_bytes, r.pause_copy) == (100, 80, True)
    assert c.observe(observation(5, memory_cap_bytes=40)).quota_bytes == 40
    assert c.stable == 0


def test_missing_feedback_and_outstanding_release_prevent_growth():
    c = governor()
    c.observe(observation(0))
    c.observe(observation(1))
    c.observe(observation(2))
    r = c.observe(observation(3, physical_backup_bytes=100, reclaim_bytes=40))
    assert r.quota_bytes == 100 and r.pause_copy
    r = c.observe(observation(4, valid=False))
    assert r.quota_bytes == 0 and r.reason == "invalid-feedback"
    assert c.observe(observation(6)).quota_bytes == 0


def test_sequence_retry_and_allocation_clip_do_not_create_stable_samples():
    c = governor()
    first = observation(0)
    assert c.observe(first) == c.observe(first)
    assert c.stable == 1
    with pytest.raises(ValueError):
        c.observe(replace(first, demand=False))
    c.observe(observation(1))
    assert c.clip_for_foreground(30) == 30 and c.stable == 0
    assert c.clip_for_foreground(800) == 30
    assert c.observe(observation(2)).quota_bytes == 30
