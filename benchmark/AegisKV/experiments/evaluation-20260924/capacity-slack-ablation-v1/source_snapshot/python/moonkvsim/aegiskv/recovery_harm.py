"""Exact tier-local fail-now recovery harm for AegisKV Algorithm 2.

This module deliberately contains no placement or eviction policy.  It evaluates the
current design's ``J=[T-s]^+`` quantity, one candidate's ``A`` reduction, and one victim
set's joint ``D`` increase on the GlobalDES clock.  A caller must supply complete
before/after recovery-time snapshots; in particular, victim loss is not reconstructed by
summing per-chunk credits.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Final

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
    fraction_to_json,
    require_fraction,
    require_nonnegative_int,
)

_ZERO: Final = Fraction(0, 1)


@dataclass(frozen=True, slots=True)
class RecoveryTimeBreakdown:
    """Complete fail-now recovery time for one tier-local continuous prefix.

    ``collective_sync_ns`` is zero for TP=1.  For tensor-parallel recovery it represents
    communication/synchronization required after every rank has restored its own KV
    shard; it must not be used to invent a mathematical reduction of KV contents.
    """

    load_ns: Fraction
    prompt_suffix_recompute_ns: Fraction
    silent_replay_ns: Fraction
    collective_sync_ns: Fraction = _ZERO

    def __post_init__(self) -> None:
        for name, value in (
            ("load_ns", self.load_ns),
            ("prompt_suffix_recompute_ns", self.prompt_suffix_recompute_ns),
            ("silent_replay_ns", self.silent_replay_ns),
            ("collective_sync_ns", self.collective_sync_ns),
        ):
            require_fraction(value, name)

    @property
    def total_ns(self) -> Fraction:
        return (
            self.load_ns
            + self.prompt_suffix_recompute_ns
            + self.silent_replay_ns
            + self.collective_sync_ns
        )

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "collective_sync_ns": fraction_to_json(self.collective_sync_ns),
            "load_ns": fraction_to_json(self.load_ns),
            "prompt_suffix_recompute_ns": fraction_to_json(
                self.prompt_suffix_recompute_ns
            ),
            "silent_replay_ns": fraction_to_json(self.silent_replay_ns),
            "total_ns": fraction_to_json(self.total_ns),
        }


@dataclass(frozen=True, slots=True)
class RecoveryHarmSnapshot:
    """One request's tier-local recovery harm at an exact DES timestamp."""

    request_id: str
    pool: PolicyPool
    evaluated_at_ns: int
    slack: SlackSignal
    recovery_time: RecoveryTimeBreakdown

    def __post_init__(self) -> None:
        if type(self.request_id) is not str or not self.request_id:
            raise ValueError("request_id must be a non-empty string")
        if type(self.pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        require_nonnegative_int(self.evaluated_at_ns, "evaluated_at_ns")
        if type(self.slack) is not SlackSignal:
            raise TypeError("slack must be an exact SlackSignal")
        if type(self.recovery_time) is not RecoveryTimeBreakdown:
            raise TypeError("recovery_time must be an exact RecoveryTimeBreakdown")
        if self.evaluated_at_ns < self.slack.observed_at_ns:
            raise ValueError("recovery harm cannot predate its Slack observation")

    @property
    def slack_at_evaluation_ns(self) -> Fraction:
        return self.slack.value_at(self.evaluated_at_ns)

    @property
    def harm_ns(self) -> Fraction:
        return max(self.recovery_time.total_ns - self.slack_at_evaluation_ns, _ZERO)

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "evaluated_at_ns": self.evaluated_at_ns,
            "harm_J_ns": fraction_to_json(self.harm_ns),
            "pool": self.pool.value,
            "recovery_time": self.recovery_time.to_canonical_json(),
            "request_id": self.request_id,
            "slack": self.slack.to_canonical_json(now_ns=self.evaluated_at_ns),
        }


@dataclass(frozen=True, slots=True)
class AdmissionHarmDelta:
    """Algorithm 2 candidate gain ``A=[J_before-J_after]^+``."""

    before: RecoveryHarmSnapshot
    after: RecoveryHarmSnapshot

    def __post_init__(self) -> None:
        _require_comparable(self.before, self.after)

    @property
    def gain_ns(self) -> Fraction:
        return max(self.before.harm_ns - self.after.harm_ns, _ZERO)

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "after": self.after.to_canonical_json(),
            "before": self.before.to_canonical_json(),
            "gain_A_ns": fraction_to_json(self.gain_ns),
        }


@dataclass(frozen=True, slots=True)
class VictimSetHarmDelta:
    """Algorithm 2 joint loss ``D`` for a complete tentative victim set.

    There is exactly one before and one after snapshot per affected request.  This makes
    interactions among multiple removed suffix chunks explicit and prevents callers from
    approximating the joint loss as a sum of stale per-chunk values.
    """

    before_by_request: tuple[RecoveryHarmSnapshot, ...]
    after_by_request: tuple[RecoveryHarmSnapshot, ...]

    def __post_init__(self) -> None:
        before = _index_snapshots(self.before_by_request, name="before_by_request")
        after = _index_snapshots(self.after_by_request, name="after_by_request")
        if before.keys() != after.keys():
            raise ValueError("joint loss before/after request sets must match")
        for request_id in before:
            _require_comparable(before[request_id], after[request_id])

    @property
    def joint_loss_ns(self) -> Fraction:
        before = _index_snapshots(self.before_by_request, name="before_by_request")
        after = _index_snapshots(self.after_by_request, name="after_by_request")
        return sum(
            (
                max(after[request_id].harm_ns - before[request_id].harm_ns, _ZERO)
                for request_id in sorted(before)
            ),
            start=_ZERO,
        )

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "after_by_request": [
                snapshot.to_canonical_json()
                for snapshot in sorted(
                    self.after_by_request,
                    key=lambda item: item.request_id,
                )
            ],
            "before_by_request": [
                snapshot.to_canonical_json()
                for snapshot in sorted(
                    self.before_by_request,
                    key=lambda item: item.request_id,
                )
            ],
            "joint_loss_D_ns": fraction_to_json(self.joint_loss_ns),
        }


def current_design_rental_value(
    *,
    candidate: SealedChunk,
    before: RecoveryHarmSnapshot,
    after: RecoveryHarmSnapshot,
    pool_rent: Fraction,
    frontier_version: int,
) -> RentalValue:
    """Build a formal-kernel value whose benefit is exactly Algorithm 2 ``A``.

    ``RentalValue`` predates the current recovery-only design and retains compatibility
    fields for hit/LRU utilities.  This fail-closed adapter sets those terms and weights to
    zero, so ``composite_benefit`` is exactly the tier-local recovery-harm reduction.  New
    experiment wiring must use this adapter rather than constructing weighted composite
    values directly.
    """

    if type(candidate) is not SealedChunk:
        raise TypeError("candidate must be an exact SealedChunk")
    _require_comparable(before, after)
    if candidate.request_id != before.request_id:
        raise ValueError("candidate and recovery snapshots belong to different requests")
    require_fraction(pool_rent, "pool_rent")
    require_nonnegative_int(frontier_version, "frontier_version")
    versions = SignalVersions(
        slack=before.slack.version,
        hit=0,
        lru=0,
        frontier=frontier_version,
    )
    return compute_rental_value(
        RentalValueInputs(
            candidate=candidate,
            pool=before.pool,
            signals=RentalSignals(
                slack=before.slack,
                hit_probability=_ZERO,
                reuse_saving=_ZERO,
                lru_utility=_ZERO,
                last_access_ns=before.evaluated_at_ns,
                versions=versions,
            ),
            recovery_time_before=before.recovery_time.total_ns,
            recovery_time_after=after.recovery_time.total_ns,
            weights=RentalWeights(
                lambda_w=Fraction(1, 1),
                lambda_h=_ZERO,
                lambda_l=_ZERO,
            ),
            pool_rent=pool_rent,
            now_ns=before.evaluated_at_ns,
        )
    )


def _require_comparable(
    before: RecoveryHarmSnapshot,
    after: RecoveryHarmSnapshot,
) -> None:
    if type(before) is not RecoveryHarmSnapshot or type(after) is not RecoveryHarmSnapshot:
        raise TypeError("recovery harm comparisons require exact snapshots")
    if before.request_id != after.request_id:
        raise ValueError("recovery harm snapshots belong to different requests")
    if before.pool is not after.pool:
        raise ValueError("recovery harm snapshots belong to different policy pools")
    if before.evaluated_at_ns != after.evaluated_at_ns:
        raise ValueError("recovery harm snapshots must use one DES timestamp")
    if before.slack != after.slack:
        raise ValueError("recovery harm snapshots must use one Slack observation")


def _index_snapshots(
    snapshots: tuple[RecoveryHarmSnapshot, ...],
    *,
    name: str,
) -> dict[str, RecoveryHarmSnapshot]:
    if type(snapshots) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    result: dict[str, RecoveryHarmSnapshot] = {}
    for snapshot in snapshots:
        if type(snapshot) is not RecoveryHarmSnapshot:
            raise TypeError(f"{name} must contain exact RecoveryHarmSnapshot values")
        if snapshot.request_id in result:
            raise ValueError(f"{name} contains a duplicate request")
        result[snapshot.request_id] = snapshot
    if not result:
        raise ValueError(f"{name} must contain at least one affected request")
    return result
