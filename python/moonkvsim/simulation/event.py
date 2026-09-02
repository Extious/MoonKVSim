"""Typed events and their frozen global tie-breaking policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class EventKind(StrEnum):
    REQUEST_ARRIVAL = "REQUEST_ARRIVAL"
    CONTINUOUS_BATCH_ADMIT = "CONTINUOUS_BATCH_ADMIT"
    ROUTE_REQUEST = "ROUTE_REQUEST"
    SCHEDULER_STEP_READY = "SCHEDULER_STEP_READY"
    FORWARD_START = "FORWARD_START"
    FORWARD_COMPLETE = "FORWARD_COMPLETE"
    KV_BLOCK_ALLOCATE = "KV_BLOCK_ALLOCATE"
    KV_BLOCK_FREE = "KV_BLOCK_FREE"
    CONTROL_WINDOW = "CONTROL_WINDOW"
    RESOURCE_RESERVE = "RESOURCE_RESERVE"
    RESOURCE_RELEASE = "RESOURCE_RELEASE"
    STAGING_ACQUIRE = "STAGING_ACQUIRE"
    STAGING_RELEASE = "STAGING_RELEASE"
    ENDPOINT_REGISTRATION_START = "ENDPOINT_REGISTRATION_START"
    ENDPOINT_REGISTRATION_COMPLETE = "ENDPOINT_REGISTRATION_COMPLETE"
    ENDPOINT_READY = "ENDPOINT_READY"
    STORE_QUERY = "STORE_QUERY"
    PUT_START = "PUT_START"
    PUT_ALLOCATED = "PUT_ALLOCATED"
    TRANSFER_START = "TRANSFER_START"
    TRANSFER_SLICE_START = "TRANSFER_SLICE_START"
    FLOW_RATE_UPDATE = "FLOW_RATE_UPDATE"
    TRANSFER_SLICE_COMPLETE = "TRANSFER_SLICE_COMPLETE"
    TRANSFER_COMPLETE = "TRANSFER_COMPLETE"
    PUT_COMMIT = "PUT_COMMIT"
    GET_START = "GET_START"
    GET_COMPLETE = "GET_COMPLETE"
    EVICTION_START = "EVICTION_START"
    EVICTION_COMPLETE = "EVICTION_COMPLETE"
    DIRECTORY_PUBLISH = "DIRECTORY_PUBLISH"
    FAILURE_INJECT = "FAILURE_INJECT"
    FAILURE_DETECT = "FAILURE_DETECT"
    ROUTE_FENCE = "ROUTE_FENCE"
    REROUTE = "REROUTE"
    RECOVERY_START = "RECOVERY_START"
    RECOVERY_COMPLETE = "RECOVERY_COMPLETE"
    RECOVERY_RECOMPUTE_COMPLETE = "RECOVERY_RECOMPUTE_COMPLETE"
    SILENT_REPLAY_COMPLETE = "SILENT_REPLAY_COMPLETE"
    REQUEST_COMPLETE = "REQUEST_COMPLETE"
    REPAIR_COMPLETE = "REPAIR_COMPLETE"


class EventPriority(IntEnum):
    """Lower values execute first at the same virtual timestamp."""

    FAILURE = 0
    FENCE = 10
    COMPLETION = 20
    COMMIT = 30
    OUTPUT = 40
    NORMAL = 50


_COMPLETION_KINDS = {
    EventKind.FORWARD_COMPLETE,
    EventKind.RESOURCE_RELEASE,
    EventKind.STAGING_RELEASE,
    EventKind.ENDPOINT_REGISTRATION_COMPLETE,
    EventKind.ENDPOINT_READY,
    EventKind.TRANSFER_SLICE_COMPLETE,
    EventKind.TRANSFER_COMPLETE,
    EventKind.GET_COMPLETE,
    EventKind.EVICTION_COMPLETE,
    EventKind.RECOVERY_COMPLETE,
    EventKind.RECOVERY_RECOMPUTE_COMPLETE,
    EventKind.SILENT_REPLAY_COMPLETE,
    EventKind.REPAIR_COMPLETE,
}


def default_priority(kind: EventKind) -> EventPriority:
    if kind is EventKind.FAILURE_INJECT:
        return EventPriority.FAILURE
    if kind in {EventKind.FAILURE_DETECT, EventKind.ROUTE_FENCE}:
        return EventPriority.FENCE
    if kind in _COMPLETION_KINDS:
        return EventPriority.COMPLETION
    if kind in {EventKind.PUT_COMMIT, EventKind.DIRECTORY_PUBLISH}:
        return EventPriority.COMMIT
    if kind is EventKind.REQUEST_COMPLETE:
        return EventPriority.OUTPUT
    return EventPriority.NORMAL


@dataclass(frozen=True, slots=True)
class EventHandle:
    event_id: str


@dataclass(frozen=True, order=True, slots=True)
class ScheduledEvent:
    """An immutable event ordered only by the DES key."""

    timestamp_ns: int
    priority: int
    stable_sequence: int
    kind: EventKind = field(compare=False)
    event_id: str = field(compare=False)
    payload: dict[str, Any] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        if self.timestamp_ns < 0:
            raise ValueError("timestamp_ns must be non-negative")
        if self.stable_sequence < 0:
            raise ValueError("stable_sequence must be non-negative")
