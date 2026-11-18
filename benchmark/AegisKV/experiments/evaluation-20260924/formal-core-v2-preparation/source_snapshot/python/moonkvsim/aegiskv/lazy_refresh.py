"""Fail-closed lazy refresh primitives for SlackLandlord heap entries.

Refresh is deliberately not a general cache-update API.  The policy algorithm may
refresh a stale value only while it is the temporary heap top or immediately after
it becomes the newly exposed predecessor of a selected request-local tail.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from moonkvsim.aegiskv.rental_value import RentalValue


class RefreshTrigger(StrEnum):
    """The two, and only two, patent-authorized lazy-refresh sites."""

    HEAP_TOP = "HEAP_TOP"
    NEWLY_EXPOSED = "NEWLY_EXPOSED"


@dataclass(frozen=True, slots=True)
class RentalEntry:
    """One committed chunk and its last materialized rental value."""

    value: RentalValue

    def __post_init__(self) -> None:
        if type(self.value) is not RentalValue:
            raise TypeError("value must be an exact RentalValue")

    @property
    def chunk_id(self) -> str:
        return self.value.candidate.chunk_id

    @property
    def request_id(self) -> str:
        return self.value.candidate.request_id

    @property
    def sequence_index(self) -> int:
        return self.value.candidate.sequence_index

    @property
    def allocated_bytes(self) -> int:
        return self.value.actual_allocated_bytes

    def to_canonical_json(self) -> dict[str, object]:
        return self.value.to_canonical_json()


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """Auditable result of one authorized refresh check."""

    before: RentalEntry
    after: RentalEntry
    trigger: RefreshTrigger
    refreshed: bool

    def __post_init__(self) -> None:
        if type(self.before) is not RentalEntry or type(self.after) is not RentalEntry:
            raise TypeError("refresh endpoints must be exact RentalEntry values")
        if type(self.trigger) is not RefreshTrigger:
            raise TypeError("trigger must be an exact RefreshTrigger")
        if type(self.refreshed) is not bool:
            raise TypeError("refreshed must be a boolean")
        self.before.value._require_same_identity(self.after.value)
        if self.refreshed != (self.before.value != self.after.value):
            raise ValueError("refreshed must describe whether the stored value changed")

    def to_canonical_json(self) -> dict[str, object]:
        return {
            "after": self.after.to_canonical_json(),
            "before": self.before.to_canonical_json(),
            "refreshed": self.refreshed,
            "trigger": self.trigger.value,
        }


def refresh_if_stale(
    stored: RentalEntry,
    latest: RentalValue,
    *,
    trigger: RefreshTrigger,
) -> RefreshResult:
    """Return a refreshed immutable entry at an authorized algorithmic boundary.

    ``latest`` is computed by the signal owner.  This module never reads clocks or
    reconstructs signals, and it rejects time regression even if version numbers differ.
    """

    if type(trigger) is not RefreshTrigger:
        raise TypeError("trigger must be HEAP_TOP or NEWLY_EXPOSED")
    stored.value._require_same_identity(latest)
    if latest.evaluated_at_ns < stored.value.evaluated_at_ns:
        raise ValueError("latest rental value cannot move virtual time backwards")
    if not latest.signal_versions.is_at_least(stored.value.signal_versions):
        raise ValueError("latest rental value cannot regress any signal version")
    if not stored.value.is_stale_against(latest):
        return RefreshResult(
            before=stored,
            after=stored,
            trigger=trigger,
            refreshed=False,
        )
    after = RentalEntry(latest)
    return RefreshResult(
        before=stored,
        after=after,
        trigger=trigger,
        refreshed=True,
    )
