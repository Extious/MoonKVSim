"""Patent-final exact rental-value computation for AegisKV."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from moonkvsim.aegiskv.types import (
    PolicyPool,
    RentalSignals,
    RentalWeights,
    SealedChunk,
    SignalVersions,
    fraction_to_json,
    require_fraction,
    require_nonnegative_int,
)


@dataclass(frozen=True, slots=True)
class RentalValueInputs:
    candidate: SealedChunk
    pool: PolicyPool
    signals: RentalSignals
    recovery_time_before: Fraction
    recovery_time_after: Fraction
    weights: RentalWeights
    pool_rent: Fraction
    now_ns: int

    def __post_init__(self) -> None:
        if type(self.candidate) is not SealedChunk:
            raise TypeError("candidate must be an exact SealedChunk")
        if type(self.pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        if type(self.signals) is not RentalSignals:
            raise TypeError("signals must be exact RentalSignals")
        if type(self.weights) is not RentalWeights:
            raise TypeError("weights must be exact RentalWeights")
        require_fraction(self.recovery_time_before, "recovery_time_before")
        require_fraction(self.recovery_time_after, "recovery_time_after")
        require_fraction(self.pool_rent, "pool_rent")
        require_nonnegative_int(self.now_ns, "now_ns")
        if self.now_ns < self.signals.last_access_ns:
            raise ValueError("now_ns cannot precede the latest access signal")


@dataclass(frozen=True, slots=True)
class RentalValue:
    """Every named patent quantity, retained as an exact rational."""

    candidate: SealedChunk
    pool: PolicyPool
    evaluated_at_ns: int
    signal_versions: SignalVersions
    slack_at_evaluation: Fraction
    recovery_time_before: Fraction
    recovery_time_after: Fraction
    j_before: Fraction
    j_after: Fraction
    workflow_recovery_benefit: Fraction
    hit_probability: Fraction
    reuse_saving: Fraction
    hit_utility: Fraction
    lru_utility: Fraction
    weights: RentalWeights
    composite_benefit: Fraction
    unit_byte_priority: Fraction
    pool_rent: Fraction
    rental_key: Fraction

    def __post_init__(self) -> None:
        if type(self.candidate) is not SealedChunk:
            raise TypeError("candidate must be an exact SealedChunk")
        if type(self.pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        if type(self.signal_versions) is not SignalVersions:
            raise TypeError("signal_versions must be exact SignalVersions")
        if type(self.weights) is not RentalWeights:
            raise TypeError("weights must be exact RentalWeights")
        require_nonnegative_int(self.evaluated_at_ns, "evaluated_at_ns")
        for name, value in (
            ("slack_at_evaluation", self.slack_at_evaluation),
            ("recovery_time_before", self.recovery_time_before),
            ("recovery_time_after", self.recovery_time_after),
            ("j_before", self.j_before),
            ("j_after", self.j_after),
            ("workflow_recovery_benefit", self.workflow_recovery_benefit),
            ("hit_probability", self.hit_probability),
            ("reuse_saving", self.reuse_saving),
            ("hit_utility", self.hit_utility),
            ("lru_utility", self.lru_utility),
            ("composite_benefit", self.composite_benefit),
            ("unit_byte_priority", self.unit_byte_priority),
            ("pool_rent", self.pool_rent),
            ("rental_key", self.rental_key),
        ):
            require_fraction(value, name)
        zero = Fraction(0, 1)
        if self.j_before != max(self.recovery_time_before - self.slack_at_evaluation, zero):
            raise ValueError("J_before does not match max(T_before - s_i(t), 0)")
        if self.j_after != max(self.recovery_time_after - self.slack_at_evaluation, zero):
            raise ValueError("J_after does not match max(T_after - s_i(t), 0)")
        if self.workflow_recovery_benefit != max(self.j_before - self.j_after, zero):
            raise ValueError("W does not match max(J_before - J_after, 0)")
        if self.hit_probability > 1:
            raise ValueError("hit_probability must not exceed one")
        if self.hit_utility != self.hit_probability * self.reuse_saving:
            raise ValueError("Uhit must equal hit probability times reuse saving")
        expected_benefit = (
            self.weights.lambda_w * self.workflow_recovery_benefit
            + self.weights.lambda_h * self.hit_utility
            + self.weights.lambda_l * self.lru_utility
        )
        if self.composite_benefit != expected_benefit:
            raise ValueError("G does not match the weighted W/Uhit/Ulru sum")
        if self.unit_byte_priority != self.composite_benefit / self.actual_allocated_bytes:
            raise ValueError("P must divide G by actual allocated bytes")
        if self.rental_key != self.pool_rent + self.unit_byte_priority:
            raise ValueError("H must equal pool rent plus P")

    @property
    def actual_allocated_bytes(self) -> int:
        return self.candidate.allocated_bytes

    def is_stale_against(self, latest: RentalValue) -> bool:
        self._require_same_identity(latest)
        return (
            self.signal_versions != latest.signal_versions
            or self.evaluated_at_ns != latest.evaluated_at_ns
            or self.pool_rent != latest.pool_rent
        )

    def _require_same_identity(self, other: RentalValue) -> None:
        if self.candidate != other.candidate or self.pool is not other.pool:
            raise ValueError("rental values describe different pool candidates")

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "G": fraction_to_json(self.composite_benefit),
            "H": fraction_to_json(self.rental_key),
            "J_after": fraction_to_json(self.j_after),
            "J_before": fraction_to_json(self.j_before),
            "P": fraction_to_json(self.unit_byte_priority),
            "Uhit": fraction_to_json(self.hit_utility),
            "Ulru": fraction_to_json(self.lru_utility),
            "W": fraction_to_json(self.workflow_recovery_benefit),
            "actual_allocated_bytes": self.actual_allocated_bytes,
            "candidate": self.candidate.to_canonical_json(),
            "evaluated_at_ns": self.evaluated_at_ns,
            "hit_probability": fraction_to_json(self.hit_probability),
            "pool": self.pool.value,
            "pool_rent": fraction_to_json(self.pool_rent),
            "recovery_time_after": fraction_to_json(self.recovery_time_after),
            "recovery_time_before": fraction_to_json(self.recovery_time_before),
            "reuse_saving": fraction_to_json(self.reuse_saving),
            "s_i_t": fraction_to_json(self.slack_at_evaluation),
            "signal_versions": self.signal_versions.to_canonical_json(),
            "weights": self.weights.to_canonical_json(),
        }


def compute_rental_value(inputs: RentalValueInputs) -> RentalValue:
    """Evaluate the patent-final J/W/Uhit/Ulru/G/P/H equations exactly."""

    slack = inputs.signals.slack.value_at(inputs.now_ns)
    zero = Fraction(0, 1)
    j_before = max(inputs.recovery_time_before - slack, zero)
    j_after = max(inputs.recovery_time_after - slack, zero)
    workflow_recovery_benefit = max(j_before - j_after, zero)
    hit_utility = inputs.signals.hit_probability * inputs.signals.reuse_saving
    lru_utility = inputs.signals.lru_utility
    composite_benefit = (
        inputs.weights.lambda_w * workflow_recovery_benefit
        + inputs.weights.lambda_h * hit_utility
        + inputs.weights.lambda_l * lru_utility
    )
    unit_byte_priority = composite_benefit / inputs.candidate.allocated_bytes
    rental_key = inputs.pool_rent + unit_byte_priority
    return RentalValue(
        candidate=inputs.candidate,
        pool=inputs.pool,
        evaluated_at_ns=inputs.now_ns,
        signal_versions=inputs.signals.versions,
        slack_at_evaluation=slack,
        recovery_time_before=inputs.recovery_time_before,
        recovery_time_after=inputs.recovery_time_after,
        j_before=j_before,
        j_after=j_after,
        workflow_recovery_benefit=workflow_recovery_benefit,
        hit_probability=inputs.signals.hit_probability,
        reuse_saving=inputs.signals.reuse_saving,
        hit_utility=hit_utility,
        lru_utility=lru_utility,
        weights=inputs.weights,
        composite_benefit=composite_benefit,
        unit_byte_priority=unit_byte_priority,
        pool_rent=inputs.pool_rent,
        rental_key=rental_key,
    )


# Concise public spelling used by policy callers.
calculate_rental_value = compute_rental_value
