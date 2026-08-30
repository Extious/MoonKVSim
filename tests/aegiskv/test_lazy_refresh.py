from __future__ import annotations

from fractions import Fraction
from typing import cast

import pytest

from moonkvsim.aegiskv.lazy_refresh import (
    RefreshTrigger,
    RentalEntry,
    refresh_if_stale,
)
from moonkvsim.aegiskv.rental_value import (
    RentalValue,
    RentalValueInputs,
    compute_rental_value,
)
from moonkvsim.aegiskv.types import (
    PolicyPool,
    RentalSignals,
    RentalWeights,
    SealedChunk,
    SignalVersions,
    SlackSignal,
)


def _value(*, now_ns: int, version: int, benefit: Fraction = Fraction(3, 1)) -> RentalValue:
    candidate = SealedChunk("r:0", "r", sequence_index=0, allocated_bytes=3)
    return compute_rental_value(
        RentalValueInputs(
            candidate=candidate,
            pool=PolicyPool.PEER_HBM,
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
            pool_rent=Fraction(0, 1),
            now_ns=now_ns,
        )
    )


@pytest.mark.parametrize(
    "trigger",
    [RefreshTrigger.HEAP_TOP, RefreshTrigger.NEWLY_EXPOSED],
)
def test_only_authorized_boundaries_refresh_an_immutable_entry(trigger: RefreshTrigger) -> None:
    stored = RentalEntry(_value(now_ns=10, version=1))
    latest = _value(now_ns=12, version=2, benefit=Fraction(6, 1))

    result = refresh_if_stale(stored, latest, trigger=trigger)

    assert result.refreshed is True
    assert result.before is stored
    assert result.after.value is latest
    assert stored.value.composite_benefit == Fraction(3, 1)
    assert result.to_canonical_json()["trigger"] == trigger.value


def test_unchanged_latest_value_is_checked_without_replacement() -> None:
    stored = RentalEntry(_value(now_ns=10, version=1))

    result = refresh_if_stale(stored, stored.value, trigger=RefreshTrigger.HEAP_TOP)

    assert result.refreshed is False
    assert result.after is stored


def test_refresh_rejects_unlisted_trigger_and_latest_signal_regression() -> None:
    stored = RentalEntry(_value(now_ns=10, version=2))
    with pytest.raises(TypeError, match="HEAP_TOP or NEWLY_EXPOSED"):
        refresh_if_stale(
            stored,
            _value(now_ns=11, version=3),
            trigger=cast(RefreshTrigger, "BACKGROUND_SCAN"),
        )
    with pytest.raises(ValueError, match="regress"):
        refresh_if_stale(
            stored,
            _value(now_ns=11, version=1),
            trigger=RefreshTrigger.HEAP_TOP,
        )
