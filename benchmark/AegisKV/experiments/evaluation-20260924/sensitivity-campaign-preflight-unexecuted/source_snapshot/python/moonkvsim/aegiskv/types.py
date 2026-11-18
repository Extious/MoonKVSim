"""Exact, tensor-free value types for the AegisKV policy kernel.

The policy layer is evaluated only on the :class:`~moonkvsim.simulation.global_des.GlobalDES`
virtual clock.  Durations and utilities are represented by :class:`fractions.Fraction`; this
module deliberately provides no float or wall-clock conversion path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from typing import TypedDict


class CanonicalFractionJSON(TypedDict):
    """Canonical JSON representation of one exact rational number."""

    numerator: int
    denominator: int


def fraction_to_json(value: Fraction) -> CanonicalFractionJSON:
    """Return the unique reduced numerator/positive-denominator representation."""

    if type(value) is not Fraction:
        raise TypeError("exact values must be fractions.Fraction instances")
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
    }


def fraction_from_json(value: Mapping[str, object]) -> Fraction:
    """Load a canonical fraction and fail closed on aliases or unreduced input."""

    if set(value) != {"numerator", "denominator"}:
        raise ValueError("fraction JSON must contain exactly numerator and denominator")
    numerator = value["numerator"]
    denominator = value["denominator"]
    if type(numerator) is not int or type(denominator) is not int:
        raise TypeError("fraction numerator and denominator must be integers")
    if denominator <= 0:
        raise ValueError("fraction denominator must be positive")
    result = Fraction(numerator, denominator)
    if result.numerator != numerator or result.denominator != denominator:
        raise ValueError("fraction JSON must already be reduced and canonical")
    return result


def require_fraction(value: Fraction, name: str, *, nonnegative: bool = True) -> None:
    """Validate an internal exact value without accepting an implicit numeric coercion."""

    if type(value) is not Fraction:
        raise TypeError(f"{name} must be fractions.Fraction")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be non-negative")


def require_nonnegative_int(value: int, name: str) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


class PolicyPool(StrEnum):
    PEER_HBM = "PEER_HBM"
    STORE_DRAM = "STORE_DRAM"


class AdmissionOutcome(StrEnum):
    ADMIT = "ADMIT"
    BYPASS = "BYPASS"


class PathCommitState(StrEnum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


@dataclass(frozen=True, slots=True)
class SealedChunk:
    """One indivisible, already-sealed logical chunk considered by one pool.

    ``allocated_bytes`` is the actual allocator charge.  Payload or requested bytes are
    intentionally absent so a caller cannot accidentally use them as the rental divisor.
    ``sequence_index`` is request-local and makes the safely releasable suffix explicit.
    """

    chunk_id: str
    request_id: str
    sequence_index: int
    allocated_bytes: int

    def __post_init__(self) -> None:
        if type(self.chunk_id) is not str or type(self.request_id) is not str:
            raise TypeError("chunk_id and request_id must be strings")
        if not self.chunk_id or not self.request_id:
            raise ValueError("chunk_id and request_id must be non-empty")
        require_nonnegative_int(self.sequence_index, "sequence_index")
        if type(self.allocated_bytes) is not int:
            raise TypeError("allocated_bytes must be an integer")
        if self.allocated_bytes <= 0:
            raise ValueError("allocated_bytes must be positive")

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "actual_allocated_bytes": self.allocated_bytes,
            "chunk_id": self.chunk_id,
            "request_id": self.request_id,
            "sequence_index": self.sequence_index,
        }


@dataclass(frozen=True, slots=True)
class SlackSignal:
    """A versioned Slack observation that decreases only on virtual time.

    Slack is a non-negative allowance.  Between observations the kernel subtracts elapsed
    GlobalDES nanoseconds and clamps at zero; it never reads a wall clock.
    """

    slack_at_observation_ns: Fraction
    observed_at_ns: int
    version: int

    def __post_init__(self) -> None:
        require_fraction(self.slack_at_observation_ns, "slack_at_observation_ns")
        require_nonnegative_int(self.observed_at_ns, "observed_at_ns")
        require_nonnegative_int(self.version, "version")

    def value_at(self, now_ns: int) -> Fraction:
        require_nonnegative_int(now_ns, "now_ns")
        if now_ns < self.observed_at_ns:
            raise ValueError("now_ns cannot precede the Slack observation")
        elapsed = Fraction(now_ns - self.observed_at_ns, 1)
        return max(self.slack_at_observation_ns - elapsed, Fraction(0, 1))

    def to_canonical_json(self, *, now_ns: int) -> dict[str, object]:
        return {
            "observed_at_ns": self.observed_at_ns,
            "s_i_t": fraction_to_json(self.value_at(now_ns)),
            "slack_at_observation_ns": fraction_to_json(self.slack_at_observation_ns),
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class SignalVersions:
    slack: int
    hit: int
    lru: int
    frontier: int

    def __post_init__(self) -> None:
        require_nonnegative_int(self.slack, "slack version")
        require_nonnegative_int(self.hit, "hit version")
        require_nonnegative_int(self.lru, "LRU version")
        require_nonnegative_int(self.frontier, "frontier version")

    def to_canonical_json(self) -> dict[str, int]:
        return {
            "frontier": self.frontier,
            "hit": self.hit,
            "lru": self.lru,
            "slack": self.slack,
        }

    def is_at_least(self, older: SignalVersions) -> bool:
        """Return whether every independently owned version is non-regressing."""

        return (
            self.slack >= older.slack
            and self.hit >= older.hit
            and self.lru >= older.lru
            and self.frontier >= older.frontier
        )


@dataclass(frozen=True, slots=True)
class RentalSignals:
    """Latest exact inputs supplied by the workflow/cache signal owners.

    The patent requires ``Ulru = psi(t - tlast)`` but does not freeze a particular ``psi``.
    Consequently ``lru_utility`` is the exact output of the configured monotone function,
    rather than an undocumented decay curve invented by this kernel.
    """

    slack: SlackSignal
    hit_probability: Fraction
    reuse_saving: Fraction
    lru_utility: Fraction
    last_access_ns: int
    versions: SignalVersions

    def __post_init__(self) -> None:
        if type(self.slack) is not SlackSignal:
            raise TypeError("slack must be an exact SlackSignal")
        if type(self.versions) is not SignalVersions:
            raise TypeError("versions must be exact SignalVersions")
        require_fraction(self.hit_probability, "hit_probability")
        require_fraction(self.reuse_saving, "reuse_saving")
        require_fraction(self.lru_utility, "lru_utility")
        if self.hit_probability > 1:
            raise ValueError("hit_probability must not exceed one")
        require_nonnegative_int(self.last_access_ns, "last_access_ns")
        if self.versions.slack != self.slack.version:
            raise ValueError("Slack signal and aggregate signal versions diverge")

    def to_canonical_json(self, *, now_ns: int) -> dict[str, object]:
        if now_ns < self.last_access_ns:
            raise ValueError("now_ns cannot precede last_access_ns")
        return {
            "hit_probability": fraction_to_json(self.hit_probability),
            "last_access_ns": self.last_access_ns,
            "lru_elapsed_ns": now_ns - self.last_access_ns,
            "lru_utility": fraction_to_json(self.lru_utility),
            "reuse_saving": fraction_to_json(self.reuse_saving),
            "slack": self.slack.to_canonical_json(now_ns=now_ns),
            "versions": self.versions.to_canonical_json(),
        }


@dataclass(frozen=True, slots=True)
class RentalWeights:
    lambda_w: Fraction
    lambda_h: Fraction
    lambda_l: Fraction

    def __post_init__(self) -> None:
        require_fraction(self.lambda_w, "lambda_w")
        require_fraction(self.lambda_h, "lambda_h")
        require_fraction(self.lambda_l, "lambda_l")
        if self.lambda_w <= 0:
            raise ValueError("lambda_w must be strictly positive")

    def to_canonical_json(self) -> dict[str, CanonicalFractionJSON]:
        return {
            "lambda_h": fraction_to_json(self.lambda_h),
            "lambda_l": fraction_to_json(self.lambda_l),
            "lambda_w": fraction_to_json(self.lambda_w),
        }


# A descriptive alias for callers that use the policy-candidate terminology.
ChunkCandidate = SealedChunk
