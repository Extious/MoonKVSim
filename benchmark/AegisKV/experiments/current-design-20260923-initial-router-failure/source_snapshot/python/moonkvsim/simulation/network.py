"""Topology-path flow contention on the shared global virtual timeline."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Final

from moonkvsim.simulation.resource import RateResource

_EPSILON_BYTES: Final = 1e-7
_EPSILON_RATE: Final = 1e-9
_NANOSECONDS_PER_SECOND: Final = 1_000_000_000


@dataclass(slots=True)
class ActiveFlow:
    flow_id: str
    transfer_id: str
    slice_id: str
    cause: str
    path_resource_ids: tuple[str, ...]
    payload_bytes: int
    remaining_bytes: float
    weight: float = 1.0
    allocated_rate_bytes_per_second: float = 0.0

    def __post_init__(self) -> None:
        if not self.flow_id or not self.transfer_id or not self.slice_id or not self.cause:
            raise ValueError("flow identifiers and cause must be non-empty")
        if not self.path_resource_ids or len(set(self.path_resource_ids)) != len(
            self.path_resource_ids
        ):
            raise ValueError("flow path must contain unique resources")
        if self.payload_bytes <= 0:
            raise ValueError("payload_bytes must be positive")
        if self.remaining_bytes != float(self.payload_bytes):
            raise ValueError("new flow remaining_bytes must equal payload_bytes")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("flow weight must be finite and positive")
        if (
            not math.isfinite(self.remaining_bytes)
            or not math.isfinite(self.allocated_rate_bytes_per_second)
            or self.allocated_rate_bytes_per_second < 0
        ):
            raise ValueError("flow byte/rate state must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class FlowRateInterval:
    start_ns: int
    end_ns: int
    flow_id: str
    transfer_id: str
    slice_id: str
    cause: str
    path_resource_ids: tuple[str, ...]
    payload_bytes: int
    remaining_bytes_at_start: float
    allocated_rate_bytes_per_second: float
    transferred_bytes: float
    remaining_bytes_at_end: float


@dataclass(frozen=True, slots=True)
class CanceledFlow:
    flow_id: str
    transferred_bytes: float
    aborted_bytes: float
    canceled_at_ns: int
    reason: str


class FlowContentionModel:
    """Weighted max-min fair fluid flows across arbitrary shared paths.

    Callers pass the DES `now_ns` to every mutation. The model therefore has no
    independently advancing clock; `last_update_ns` is only a consistency guard.
    """

    def __init__(self, resources: list[RateResource], *, initial_now_ns: int = 0) -> None:
        if initial_now_ns < 0:
            raise ValueError("initial_now_ns must be non-negative")
        if not resources:
            raise ValueError("at least one rate resource is required")
        self.resources = {resource.resource_id: resource for resource in resources}
        if len(self.resources) != len(resources):
            raise ValueError("rate resource ids must be unique")
        self.last_update_ns = initial_now_ns
        self.flows: dict[str, ActiveFlow] = {}
        self.intervals: list[FlowRateInterval] = []

    def add_flow(self, flow: ActiveFlow, *, now_ns: int) -> None:
        if flow.flow_id in self.flows:
            raise ValueError(f"duplicate flow_id: {flow.flow_id}")
        unknown = set(flow.path_resource_ids) - self.resources.keys()
        if unknown:
            raise KeyError(f"flow path contains unknown resources: {sorted(unknown)}")
        self.advance_to(now_ns)
        previous_rates = {
            flow_id: active.allocated_rate_bytes_per_second
            for flow_id, active in self.flows.items()
        }
        self.flows[flow.flow_id] = flow
        try:
            self._recompute_rates()
        except Exception:
            del self.flows[flow.flow_id]
            flow.allocated_rate_bytes_per_second = 0.0
            for flow_id, allocated_rate in previous_rates.items():
                self.flows[flow_id].allocated_rate_bytes_per_second = allocated_rate
            raise

    def cancel_flow(self, flow_id: str, *, now_ns: int, reason: str) -> CanceledFlow:
        if not reason:
            raise ValueError("cancel reason must be non-empty")
        self.advance_to(now_ns)
        flow = self.flows.pop(flow_id)
        canceled = CanceledFlow(
            flow_id=flow.flow_id,
            transferred_bytes=flow.payload_bytes - flow.remaining_bytes,
            aborted_bytes=flow.remaining_bytes,
            canceled_at_ns=now_ns,
            reason=reason,
        )
        self._recompute_rates()
        return canceled

    def complete_flows(self, *, now_ns: int) -> tuple[ActiveFlow, ...]:
        self.advance_to(now_ns)
        completed_ids = sorted(
            flow_id
            for flow_id, flow in self.flows.items()
            if flow.remaining_bytes <= _EPSILON_BYTES
        )
        completed = tuple(self.flows.pop(flow_id) for flow_id in completed_ids)
        if completed:
            self._recompute_rates()
        return completed

    def advance_to(self, now_ns: int) -> None:
        if now_ns < self.last_update_ns:
            raise ValueError("flow model cannot move backwards")
        if now_ns == self.last_update_ns:
            return
        elapsed_ns = now_ns - self.last_update_ns
        for flow in sorted(self.flows.values(), key=lambda item: item.flow_id):
            remaining_bytes_at_start = flow.remaining_bytes
            transferred = _service_bytes(
                flow.allocated_rate_bytes_per_second,
                elapsed_ns,
            )
            # Completion timestamps are integer nanoseconds. `next_completion_ns`
            # rounds up, so advancing to that event may overshoot the exact
            # fluid completion by less than one nanosecond of service.
            rounding_allowance = (
                flow.allocated_rate_bytes_per_second / _NANOSECONDS_PER_SECOND
            ) + _EPSILON_BYTES
            if transferred > flow.remaining_bytes + rounding_allowance:
                raise RuntimeError(
                    f"flow {flow.flow_id} completed before requested advance; "
                    "DES completion event was not processed"
                )
            transferred = min(transferred, flow.remaining_bytes)
            flow.remaining_bytes = max(0.0, flow.remaining_bytes - transferred)
            self.intervals.append(
                FlowRateInterval(
                    start_ns=self.last_update_ns,
                    end_ns=now_ns,
                    flow_id=flow.flow_id,
                    transfer_id=flow.transfer_id,
                    slice_id=flow.slice_id,
                    cause=flow.cause,
                    path_resource_ids=flow.path_resource_ids,
                    payload_bytes=flow.payload_bytes,
                    remaining_bytes_at_start=remaining_bytes_at_start,
                    allocated_rate_bytes_per_second=flow.allocated_rate_bytes_per_second,
                    transferred_bytes=transferred,
                    remaining_bytes_at_end=flow.remaining_bytes,
                )
            )
        self.last_update_ns = now_ns

    def next_completion_ns(self) -> int | None:
        if not self.flows:
            return None
        completion_times: list[int] = []
        for flow in self.flows.values():
            rate = flow.allocated_rate_bytes_per_second
            if not math.isfinite(rate) or rate <= 0.0:
                raise RuntimeError(f"active flow {flow.flow_id} has no allocated rate")
            duration_ns = _ceil_service_duration_ns(flow.remaining_bytes, rate)
            completion_times.append(self.last_update_ns + max(1, duration_ns))
        return min(completion_times)

    def rates(self) -> dict[str, float]:
        return {
            flow_id: flow.allocated_rate_bytes_per_second
            for flow_id, flow in sorted(self.flows.items())
        }

    def snapshot_bytes(self) -> bytes:
        """Serialize resources, active flows, and every completed rate interval."""

        value = {
            "last_update_ns": self.last_update_ns,
            "resources": [
                {
                    "resource_id": resource_id,
                    "capacity_bytes_per_second": resource.capacity_bytes_per_second,
                }
                for resource_id, resource in sorted(self.resources.items())
            ],
            "active_flows": [
                {
                    "flow_id": flow.flow_id,
                    "transfer_id": flow.transfer_id,
                    "slice_id": flow.slice_id,
                    "cause": flow.cause,
                    "path_resource_ids": list(flow.path_resource_ids),
                    "payload_bytes": flow.payload_bytes,
                    "remaining_bytes": flow.remaining_bytes,
                    "weight": flow.weight,
                    "allocated_rate_bytes_per_second": (
                        flow.allocated_rate_bytes_per_second
                    ),
                }
                for _, flow in sorted(self.flows.items())
            ],
            "intervals": [
                {
                    "start_ns": item.start_ns,
                    "end_ns": item.end_ns,
                    "flow_id": item.flow_id,
                    "transfer_id": item.transfer_id,
                    "slice_id": item.slice_id,
                    "cause": item.cause,
                    "path_resource_ids": list(item.path_resource_ids),
                    "payload_bytes": item.payload_bytes,
                    "remaining_bytes_at_start": item.remaining_bytes_at_start,
                    "allocated_rate_bytes_per_second": (
                        item.allocated_rate_bytes_per_second
                    ),
                    "transferred_bytes": item.transferred_bytes,
                    "remaining_bytes_at_end": item.remaining_bytes_at_end,
                }
                for item in self.intervals
            ],
        }
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()

    def _recompute_rates(self) -> None:
        for flow in self.flows.values():
            flow.allocated_rate_bytes_per_second = 0.0
        unsatisfied = set(self.flows)
        residual = {
            resource_id: resource.capacity_bytes_per_second
            for resource_id, resource in self.resources.items()
        }

        while unsatisfied:
            increments: list[tuple[float, str]] = []
            for resource_id, capacity in residual.items():
                users = [
                    self.flows[flow_id]
                    for flow_id in unsatisfied
                    if resource_id in self.flows[flow_id].path_resource_ids
                ]
                if users:
                    increments.append((capacity / sum(flow.weight for flow in users), resource_id))
            if not increments:
                raise RuntimeError("active flow is disconnected from every rate resource")
            increment, bottleneck = min(increments, key=lambda item: (item[0], item[1]))
            if increment < -_EPSILON_RATE:
                raise RuntimeError("negative residual rate capacity")
            increment = max(0.0, increment)

            for flow_id in unsatisfied:
                flow = self.flows[flow_id]
                flow.allocated_rate_bytes_per_second += increment * flow.weight
            for resource_id in residual:
                weight_sum = sum(
                    self.flows[flow_id].weight
                    for flow_id in unsatisfied
                    if resource_id in self.flows[flow_id].path_resource_ids
                )
                residual[resource_id] = max(0.0, residual[resource_id] - increment * weight_sum)

            saturated = {
                resource_id
                for resource_id, remaining in residual.items()
                if remaining <= _EPSILON_RATE
            }
            # The selected bottleneck is mathematically saturated even when
            # floating-point division/multiplication leaves a few ulps of
            # positive residual.  Previously, an already-saturated resource
            # from an earlier round could keep this set non-empty and prevent
            # the current bottleneck from being added.  If the remaining flows
            # did not use that earlier resource, the allocator then falsely
            # reported that it made no progress.
            saturated.add(bottleneck)
            newly_satisfied = {
                flow_id
                for flow_id in unsatisfied
                if saturated.intersection(self.flows[flow_id].path_resource_ids)
            }
            if not newly_satisfied:
                raise RuntimeError("max-min allocation made no progress")
            unsatisfied -= newly_satisfied

        self._clamp_rate_roundoff()
        self._assert_rate_invariants()

    def _clamp_rate_roundoff(self) -> None:
        """Remove only IEEE-754 accumulation overage before the strict audit.

        A fair share such as ``25_000_000_000 / 39`` is not exactly
        representable.  Re-adding 39 stored shares can therefore exceed the
        capacity by a few ulps even though the mathematical allocation equals
        it.  Bound that numerical envelope from the number of additions, trim
        the deterministic largest share by the observed overage, and leave any
        larger violation for the fail-closed invariant.
        """

        for resource_id, resource in sorted(self.resources.items()):
            users = sorted(
                (
                    flow
                    for flow in self.flows.values()
                    if resource_id in flow.path_resource_ids
                ),
                key=lambda item: item.flow_id,
            )
            if not users:
                continue
            allocated = math.fsum(
                flow.allocated_rate_bytes_per_second for flow in users
            )
            overage = allocated - resource.capacity_bytes_per_second
            if overage <= 0:
                continue
            roundoff_envelope = math.ulp(resource.capacity_bytes_per_second) * (
                len(users) + 1
            )
            if overage > max(_EPSILON_RATE, roundoff_envelope):
                raise RuntimeError(f"rate capacity exceeded on {resource_id}")
            correction_target = max(
                users,
                key=lambda item: (item.allocated_rate_bytes_per_second, item.flow_id),
            )
            corrected_rate = correction_target.allocated_rate_bytes_per_second - overage
            if corrected_rate < 0:
                raise RuntimeError(f"rate capacity exceeded on {resource_id}")
            correction_target.allocated_rate_bytes_per_second = math.nextafter(
                corrected_rate,
                0.0,
            )

    def _assert_rate_invariants(self) -> None:
        if any(
            not math.isfinite(flow.weight)
            or not math.isfinite(flow.remaining_bytes)
            or not math.isfinite(flow.allocated_rate_bytes_per_second)
            or flow.weight <= 0
            or flow.remaining_bytes < 0
            or flow.remaining_bytes > flow.payload_bytes + _EPSILON_BYTES
            or flow.allocated_rate_bytes_per_second < 0
            for flow in self.flows.values()
        ):
            raise RuntimeError("active flow has invalid numeric state")
        for resource_id, resource in self.resources.items():
            allocated = math.fsum(
                flow.allocated_rate_bytes_per_second
                for flow in self.flows.values()
                if resource_id in flow.path_resource_ids
            )
            if allocated > resource.capacity_bytes_per_second + _EPSILON_RATE:
                raise RuntimeError(f"rate capacity exceeded on {resource_id}")


def _service_bytes(rate_bytes_per_second: float, elapsed_ns: int) -> float:
    """Multiply a finite float rate by integer nanoseconds without overflow."""

    numerator, denominator = rate_bytes_per_second.as_integer_ratio()
    return (numerator * elapsed_ns) / (
        denominator * _NANOSECONDS_PER_SECOND
    )


def _ceil_service_duration_ns(remaining_bytes: float, rate_bytes_per_second: float) -> int:
    """Return the exact integer-nanosecond ceiling for two stored floats."""

    remaining_numerator, remaining_denominator = remaining_bytes.as_integer_ratio()
    rate_numerator, rate_denominator = rate_bytes_per_second.as_integer_ratio()
    numerator = (
        remaining_numerator
        * rate_denominator
        * _NANOSECONDS_PER_SECOND
    )
    denominator = remaining_denominator * rate_numerator
    return -(-numerator // denominator)
