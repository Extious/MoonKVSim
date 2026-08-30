from __future__ import annotations

from fractions import Fraction
from typing import cast

import pytest

from moonkvsim.aegiskv.rental_value import RentalValueInputs, compute_rental_value
from moonkvsim.aegiskv.types import (
    PolicyPool,
    RentalSignals,
    RentalWeights,
    SealedChunk,
    SignalVersions,
    SlackSignal,
    fraction_from_json,
    fraction_to_json,
)


def test_canonical_fraction_json_is_reduced_and_loader_rejects_aliases() -> None:
    assert fraction_to_json(Fraction(2, 4)) == {"numerator": 1, "denominator": 2}
    assert fraction_from_json({"numerator": -3, "denominator": 7}) == Fraction(-3, 7)

    with pytest.raises(ValueError, match="canonical"):
        fraction_from_json({"numerator": 2, "denominator": 4})
    with pytest.raises(ValueError, match="exactly"):
        fraction_from_json({"numerator": 1, "denominator": 2, "float": 0.5})
    with pytest.raises(TypeError, match="Fraction"):
        fraction_to_json(cast(Fraction, 0.5))


def test_slack_decreases_on_explicit_virtual_time_and_clamps_at_zero() -> None:
    slack = SlackSignal(
        slack_at_observation_ns=Fraction(9, 2),
        observed_at_ns=10,
        version=3,
    )

    assert slack.value_at(12) == Fraction(5, 2)
    assert slack.value_at(100) == Fraction(0, 1)
    with pytest.raises(ValueError, match="precede"):
        slack.value_at(9)


def test_patent_rental_equations_remain_exact_and_use_actual_allocated_bytes() -> None:
    candidate = SealedChunk(
        chunk_id="request-7:0",
        request_id="request-7",
        sequence_index=0,
        allocated_bytes=7,
    )
    versions = SignalVersions(slack=2, hit=5, lru=7, frontier=11)
    value = compute_rental_value(
        RentalValueInputs(
            candidate=candidate,
            pool=PolicyPool.PEER_HBM,
            signals=RentalSignals(
                slack=SlackSignal(Fraction(10, 1), observed_at_ns=100, version=2),
                hit_probability=Fraction(1, 3),
                reuse_saving=Fraction(9, 2),
                lru_utility=Fraction(2, 5),
                last_access_ns=99,
                versions=versions,
            ),
            recovery_time_before=Fraction(14, 1),
            recovery_time_after=Fraction(8, 1),
            weights=RentalWeights(
                lambda_w=Fraction(2, 1),
                lambda_h=Fraction(3, 1),
                lambda_l=Fraction(5, 2),
            ),
            pool_rent=Fraction(1, 3),
            now_ns=104,
        )
    )

    assert value.slack_at_evaluation == Fraction(6, 1)
    assert value.j_before == Fraction(8, 1)
    assert value.j_after == Fraction(2, 1)
    assert value.workflow_recovery_benefit == Fraction(6, 1)
    assert value.hit_utility == Fraction(3, 2)
    assert value.lru_utility == Fraction(2, 5)
    assert value.composite_benefit == Fraction(35, 2)
    assert value.actual_allocated_bytes == 7
    assert value.unit_byte_priority == Fraction(5, 2)
    assert value.rental_key == Fraction(17, 6)

    document = value.to_canonical_json()
    assert document["G"] == {"numerator": 35, "denominator": 2}
    assert document["P"] == {"numerator": 5, "denominator": 2}
    assert document["H"] == {"numerator": 17, "denominator": 6}
    assert document["actual_allocated_bytes"] == 7


def test_float_and_nonpositive_allocator_charge_fail_closed() -> None:
    with pytest.raises(TypeError, match="Fraction"):
        SlackSignal(cast(Fraction, 1.0), observed_at_ns=0, version=0)
    with pytest.raises(ValueError, match="positive"):
        SealedChunk("c", "r", sequence_index=0, allocated_bytes=0)
