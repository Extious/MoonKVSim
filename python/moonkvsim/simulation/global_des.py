"""Single-clock deterministic discrete-event kernel."""

from __future__ import annotations

import heapq
import json
from collections.abc import Callable, Mapping
from typing import Any

from moonkvsim.common.hash import sha256_json
from moonkvsim.simulation.event import (
    EventHandle,
    EventKind,
    ScheduledEvent,
    default_priority,
)
from moonkvsim.simulation.journal import EventJournal

EventHandler = Callable[[ScheduledEvent, "GlobalDES"], None]
InvariantCheck = Callable[["GlobalDES"], None]


class GlobalDES:
    """All components share this monotonic nanosecond clock and event heap."""

    def __init__(self, *, journal: EventJournal | None = None) -> None:
        self.now_ns = 0
        self._next_sequence = 0
        self._heap: list[ScheduledEvent] = []
        self._canceled: set[str] = set()
        self._terminal: set[str] = set()
        self._known_event_ids: set[str] = set()
        self._handlers: dict[EventKind, EventHandler] = {}
        self._invariants: list[tuple[str, InvariantCheck]] = []
        self.journal = journal if journal is not None else EventJournal()

    @property
    def pending_count(self) -> int:
        return sum(event.event_id not in self._canceled for event in self._heap)

    def register_handler(self, kind: EventKind, handler: EventHandler) -> None:
        if kind in self._handlers:
            raise ValueError(f"handler already registered for {kind}")
        self._handlers[kind] = handler

    def register_invariant(self, name: str, check: InvariantCheck) -> None:
        if not name:
            raise ValueError("invariant name must be non-empty")
        if any(existing_name == name for existing_name, _ in self._invariants):
            raise ValueError(f"invariant already registered: {name}")
        self._invariants.append((name, check))

    def schedule_at(
        self,
        timestamp_ns: int,
        kind: EventKind,
        *,
        payload: Mapping[str, Any] | None = None,
        priority: int | None = None,
        event_id: str | None = None,
    ) -> EventHandle:
        if timestamp_ns < self.now_ns:
            raise ValueError(
                f"cannot schedule event in the past: now={self.now_ns}, event={timestamp_ns}"
            )
        sequence = self._next_sequence
        resolved_event_id = event_id if event_id is not None else f"event-{sequence:016d}"
        if resolved_event_id in self._known_event_ids:
            raise ValueError(f"duplicate event_id: {resolved_event_id}")
        canonical_payload = json.loads(
            json.dumps(
                dict(payload or {}),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        if not isinstance(canonical_payload, dict):
            raise TypeError("event payload must serialize as a JSON object")
        event = ScheduledEvent(
            timestamp_ns=timestamp_ns,
            priority=int(default_priority(kind) if priority is None else priority),
            stable_sequence=sequence,
            kind=kind,
            event_id=resolved_event_id,
            payload=canonical_payload,
        )
        self._next_sequence += 1
        self._known_event_ids.add(resolved_event_id)
        heapq.heappush(self._heap, event)
        self.journal.append(
            self.now_ns,
            "EVENT_SCHEDULED",
            {
                "event_id": event.event_id,
                "kind": event.kind.value,
                "scheduled_timestamp_ns": event.timestamp_ns,
                "priority": event.priority,
                "stable_sequence": event.stable_sequence,
                "payload": event.payload,
            },
        )
        return EventHandle(event_id=resolved_event_id)

    def schedule_after(
        self,
        delay_ns: int,
        kind: EventKind,
        *,
        payload: Mapping[str, Any] | None = None,
        priority: int | None = None,
        event_id: str | None = None,
    ) -> EventHandle:
        if delay_ns < 0:
            raise ValueError("delay_ns must be non-negative")
        return self.schedule_at(
            self.now_ns + delay_ns,
            kind,
            payload=payload,
            priority=priority,
            event_id=event_id,
        )

    def cancel(self, handle: EventHandle, *, reason: str) -> bool:
        if not reason:
            raise ValueError("cancellation reason must be non-empty")
        if (
            handle.event_id not in self._known_event_ids
            or handle.event_id in self._canceled
            or handle.event_id in self._terminal
        ):
            return False
        self._canceled.add(handle.event_id)
        self.journal.append(
            self.now_ns,
            "EVENT_CANCELED",
            {"event_id": handle.event_id, "reason": reason},
        )
        return True

    def run(self, *, until_ns: int | None = None) -> int:
        if until_ns is not None and until_ns < self.now_ns:
            raise ValueError("until_ns cannot be earlier than now_ns")
        executed = 0
        while self._heap:
            event = heapq.heappop(self._heap)
            if until_ns is not None and event.timestamp_ns > until_ns:
                heapq.heappush(self._heap, event)
                self.now_ns = until_ns
                break
            if event.event_id in self._canceled:
                self._terminal.add(event.event_id)
                continue
            if event.timestamp_ns < self.now_ns:
                raise RuntimeError("event heap attempted to move virtual time backwards")
            self.now_ns = event.timestamp_ns
            self.journal.append(
                self.now_ns,
                "EVENT_EXECUTING",
                {
                    "event_id": event.event_id,
                    "kind": event.kind.value,
                    "priority": event.priority,
                    "stable_sequence": event.stable_sequence,
                    # EVENT_SCHEDULED is the canonical owner of the complete
                    # payload.  Keep only an integrity link here so a replay
                    # can join on event_id, verify the payload, and avoid
                    # serializing large scheduler/transfer payloads twice.
                    "payload_sha256": sha256_json(event.payload),
                },
            )
            handler = self._handlers.get(event.kind)
            if handler is not None:
                handler(event, self)
            for name, check in self._invariants:
                check(self)
                self.journal.append(
                    self.now_ns,
                    "INVARIANT_CHECKED",
                    {"event_id": event.event_id, "name": name},
                )
            self._terminal.add(event.event_id)
            executed += 1
        else:
            if until_ns is not None:
                self.now_ns = until_ns
        return executed
