"""Typed rate and concurrency resources sharing the global nanosecond timeline."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True, slots=True)
class Reservation:
    reservation_id: str
    resource_id: str
    lane: int
    start_ns: int
    end_ns: int
    cause: str


class ConcurrencyResource:
    """Deterministic multi-lane interval calendar with cancellation."""

    def __init__(self, *, resource_id: str, lanes: int) -> None:
        if not resource_id:
            raise ValueError("resource_id must be non-empty")
        if lanes <= 0:
            raise ValueError("lanes must be positive")
        self.resource_id = resource_id
        self.lanes = lanes
        self._intervals: list[list[Reservation]] = [[] for _ in range(lanes)]
        self._by_id: dict[str, Reservation] = {}

    def reserve(
        self,
        *,
        ready_ns: int,
        duration_ns: int,
        reservation_id: str,
        cause: str,
    ) -> Reservation:
        if ready_ns < 0 or duration_ns <= 0:
            raise ValueError("ready_ns must be non-negative and duration_ns positive")
        if not reservation_id or not cause:
            raise ValueError("reservation_id and cause must be non-empty")
        if reservation_id in self._by_id:
            raise ValueError(f"duplicate reservation_id: {reservation_id}")

        candidates = [
            (self._first_fit(lane, ready_ns, duration_ns), lane) for lane in range(self.lanes)
        ]
        start_ns, lane = min(candidates)
        reservation = Reservation(
            reservation_id=reservation_id,
            resource_id=self.resource_id,
            lane=lane,
            start_ns=start_ns,
            end_ns=start_ns + duration_ns,
            cause=cause,
        )
        intervals = self._intervals[lane]
        intervals.append(reservation)
        intervals.sort(key=lambda item: (item.start_ns, item.end_ns, item.reservation_id))
        self._by_id[reservation_id] = reservation
        self._assert_no_overlap(lane)
        return reservation

    def cancel(self, reservation_id: str) -> Reservation | None:
        reservation = self._by_id.pop(reservation_id, None)
        if reservation is None:
            return None
        self._intervals[reservation.lane].remove(reservation)
        self._assert_no_overlap(reservation.lane)
        return reservation

    def reservations(self) -> tuple[Reservation, ...]:
        return tuple(
            sorted(
                self._by_id.values(),
                key=lambda item: (item.start_ns, item.lane, item.reservation_id),
            )
        )

    def _first_fit(self, lane: int, ready_ns: int, duration_ns: int) -> int:
        candidate = ready_ns
        for interval in self._intervals[lane]:
            if candidate + duration_ns <= interval.start_ns:
                break
            if candidate < interval.end_ns:
                candidate = interval.end_ns
        return candidate

    def _assert_no_overlap(self, lane: int) -> None:
        intervals = self._intervals[lane]
        for previous, current in pairwise(intervals):
            if previous.end_ns > current.start_ns:
                raise RuntimeError(f"overlapping reservations on {self.resource_id} lane {lane}")


@dataclass(frozen=True, slots=True)
class RateResource:
    resource_id: str
    capacity_bytes_per_second: float

    def __post_init__(self) -> None:
        if not self.resource_id:
            raise ValueError("resource_id must be non-empty")
        if (
            not math.isfinite(self.capacity_bytes_per_second)
            or self.capacity_bytes_per_second <= 0
        ):
            raise ValueError("capacity_bytes_per_second must be finite and positive")

    def equal_fair_share(self, active_flow_ids: set[str]) -> dict[str, float]:
        if not active_flow_ids:
            return {}
        share = self.capacity_bytes_per_second / len(active_flow_ids)
        return {flow_id: share for flow_id in sorted(active_flow_ids)}
