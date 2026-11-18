"""Deterministic endpoint registration on the shared GlobalDES clock.

The pinned Mooncake topology code exposes preferred/available HCA selection and
endpoint-backed transports, but real registration/connect/QP timing depends on
the physical runtime.  This module therefore models only an explicit,
uncalibrated Vanilla baseline contract: one pooled endpoint key becomes warm
after consuming a named registration-worker lane, and every cold or cached
lookup completes through its own GlobalDES event.  It never advances a second
clock and never folds endpoint delay into model forward time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from moonkvsim.common.hash import sha256_json
from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.resource import ConcurrencyResource, Reservation
from moonkvsim.store.transfer_engine import TopologyPath, TransferStatus, TransferTask

EVIDENCE_BOUNDARY: Final = "E2_uncalibrated_vanilla_endpoint_registration_semantics"
FIDELITY_GAPS: Final[tuple[str, ...]] = (
    "real_memory_region_registration_and_qp_handshake_are_not_executed",
    "registration_and_cached_lookup_latencies_are_assumed_not_calibrated",
    "physical_endpoint_pool_eviction_and_transport_internal_reconnect_are_not_modeled",
)

EndpointReadyHandler = Callable[[TransferTask, GlobalDES], None]


class EndpointRegistrationError(RuntimeError):
    """Endpoint preparation cannot preserve its lifecycle invariants."""


class EndpointState(StrEnum):
    COLD = "COLD"
    REGISTERING = "REGISTERING"
    WARM = "WARM"
    DISABLED = "DISABLED"


class EndpointPreparationMode(StrEnum):
    COLD = "COLD"
    JOINED_COLD = "JOINED_COLD"
    WARM = "WARM"


@dataclass(frozen=True, slots=True)
class EndpointRegistrationProfile:
    """Explicit assumed timing/resource inputs for a pooled endpoint context."""

    worker_resource_id: str
    cold_latency_ns: int
    warm_lookup_ns: int
    endpoint_pooling: bool = True

    def __post_init__(self) -> None:
        if not self.worker_resource_id:
            raise ValueError("endpoint registration worker ID must be non-empty")
        if type(self.cold_latency_ns) is not int or self.cold_latency_ns <= 0:
            raise ValueError("cold endpoint registration latency must be positive")
        if type(self.warm_lookup_ns) is not int or self.warm_lookup_ns < 0:
            raise ValueError("warm endpoint lookup latency must be non-negative")
        if self.endpoint_pooling is not True:
            raise ValueError("the Vanilla endpoint runtime requires explicit pooling")


@dataclass(frozen=True, slots=True)
class EndpointKey:
    """A fully resolved directional endpoint/HCA transport identity."""

    transport: str
    source_endpoint: str
    destination_endpoint: str
    source_node_id: str
    destination_node_id: str
    source_numa_node_id: str
    destination_numa_node_id: str
    source_hca_id: str | None
    destination_hca_id: str | None

    @classmethod
    def from_path(cls, path: TopologyPath) -> EndpointKey:
        return cls(
            transport=path.transport.value,
            source_endpoint=path.source_endpoint,
            destination_endpoint=path.destination_endpoint,
            source_node_id=path.source_node_id,
            destination_node_id=path.destination_node_id,
            source_numa_node_id=path.source_numa_node_id,
            destination_numa_node_id=path.destination_numa_node_id,
            source_hca_id=path.source_hca_id,
            destination_hca_id=path.destination_hca_id,
        )

    @property
    def endpoint_id(self) -> str:
        return f"endpoint-{sha256_json(self.to_dict())[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "transport": self.transport,
            "source_endpoint": self.source_endpoint,
            "destination_endpoint": self.destination_endpoint,
            "source_node_id": self.source_node_id,
            "destination_node_id": self.destination_node_id,
            "source_numa_node_id": self.source_numa_node_id,
            "destination_numa_node_id": self.destination_numa_node_id,
            "source_hca_id": self.source_hca_id,
            "destination_hca_id": self.destination_hca_id,
        }


@dataclass(slots=True)
class _PoolEntry:
    key: EndpointKey
    state: EndpointState = EndpointState.COLD
    generation: int = 0
    registration_id: str | None = None
    warm_since_ns: int | None = None


@dataclass(slots=True)
class _Registration:
    registration_id: str
    key: EndpointKey
    generation: int
    reservation: Reservation
    start_handle: EventHandle
    completion_handle: EventHandle
    waiter_ids: set[str] = field(default_factory=set)
    started: bool = False


@dataclass(slots=True)
class _Preparation:
    preparation_id: str
    task: TransferTask
    key: EndpointKey
    generation: int
    mode: EndpointPreparationMode
    requested_ns: int
    ready_ns: int
    registration_id: str | None
    ready_handle: EventHandle
    on_ready: EndpointReadyHandler


class EndpointRegistrationManager:
    """Prepare pooled endpoint keys through independent DES resource events."""

    def __init__(
        self,
        *,
        des: GlobalDES,
        registration_worker: ConcurrencyResource,
        profile: EndpointRegistrationProfile,
    ) -> None:
        if registration_worker.resource_id != profile.worker_resource_id:
            raise ValueError("endpoint profile and worker resource IDs differ")
        self.des = des
        self.registration_worker = registration_worker
        self.profile = profile
        self._pool: dict[EndpointKey, _PoolEntry] = {}
        self._registrations: dict[str, _Registration] = {}
        self._preparations: dict[str, _Preparation] = {}
        self._known_preparation_ids: set[str] = set()
        self._known_registration_ids: set[str] = set()
        des.register_handler(
            EventKind.ENDPOINT_REGISTRATION_START,
            self._on_registration_start,
        )
        des.register_handler(
            EventKind.ENDPOINT_REGISTRATION_COMPLETE,
            self._on_registration_complete,
        )
        des.register_handler(EventKind.ENDPOINT_READY, self._on_endpoint_ready)

    @property
    def active_preparation_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._preparations))

    @property
    def active_registration_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    @property
    def warm_endpoint_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                entry.key.endpoint_id
                for entry in self._pool.values()
                if entry.state is EndpointState.WARM
            )
        )

    def state_for_path(self, path: TopologyPath) -> EndpointState:
        return self._entry(EndpointKey.from_path(path)).state

    def prepare(
        self,
        task: TransferTask,
        *,
        preparation_id: str,
        on_ready: EndpointReadyHandler,
    ) -> EventHandle:
        """Schedule one cold/joined/warm endpoint-ready event for ``task``."""

        if not preparation_id or preparation_id in self._known_preparation_ids:
            raise ValueError("endpoint preparation ID must be non-empty and globally unique")
        if task.status is not TransferStatus.WAITING:
            raise EndpointRegistrationError("endpoint preparation requires a WAITING transfer")
        if self.des.now_ns < task.metadata.ready_ns:
            raise EndpointRegistrationError("endpoint preparation cannot precede task ready_ns")
        task.audit()
        key = EndpointKey.from_path(task.metadata.path)
        entry = self._entry(key)
        if entry.state is EndpointState.DISABLED:
            raise EndpointRegistrationError("endpoint key is disabled")

        registration_id: str | None
        if entry.state is EndpointState.WARM:
            mode = EndpointPreparationMode.WARM
            ready_ns = self.des.now_ns + self.profile.warm_lookup_ns
            registration_id = None
        elif entry.state is EndpointState.REGISTERING:
            if entry.registration_id is None:
                raise EndpointRegistrationError("registering endpoint has no registration ID")
            registration = self._registrations[entry.registration_id]
            mode = EndpointPreparationMode.JOINED_COLD
            ready_ns = registration.reservation.end_ns
            registration_id = registration.registration_id
        else:
            registration = self._begin_registration(entry, preparation_id=preparation_id)
            mode = EndpointPreparationMode.COLD
            ready_ns = registration.reservation.end_ns
            registration_id = registration.registration_id

        ready_handle = self.des.schedule_at(
            ready_ns,
            EventKind.ENDPOINT_READY,
            event_id=f"endpoint-ready:{preparation_id}",
            payload={"preparation_id": preparation_id},
        )
        preparation = _Preparation(
            preparation_id=preparation_id,
            task=task,
            key=key,
            generation=entry.generation,
            mode=mode,
            requested_ns=self.des.now_ns,
            ready_ns=ready_ns,
            registration_id=registration_id,
            ready_handle=ready_handle,
            on_ready=on_ready,
        )
        self._preparations[preparation_id] = preparation
        self._known_preparation_ids.add(preparation_id)
        if registration_id is not None:
            self._registrations[registration_id].waiter_ids.add(preparation_id)
        self._append(
            "TRANSFER_ENDPOINT_PREPARATION_REQUESTED",
            {
                "preparation_id": preparation_id,
                "transfer_id": task.metadata.transfer_id,
                "path_id": task.metadata.path.path_id,
                "endpoint_id": key.endpoint_id,
                "endpoint_key": key.to_dict(),
                "generation": entry.generation,
                "mode": mode.value,
                "requested_ns": self.des.now_ns,
                "ready_ns": ready_ns,
                "registration_id": registration_id,
                "worker_resource_id": self.profile.worker_resource_id,
                "evidence_boundary": EVIDENCE_BOUNDARY,
                "fidelity_gaps": list(FIDELITY_GAPS),
            },
        )
        self.audit()
        return ready_handle

    def cancel_preparation(self, preparation_id: str, *, reason: str) -> bool:
        """Cancel one waiter and release a now-unused cold registration."""

        if not reason:
            raise ValueError("endpoint preparation cancel reason must be non-empty")
        preparation = self._preparations.pop(preparation_id, None)
        if preparation is None:
            return False
        self.des.cancel(preparation.ready_handle, reason=reason)
        if preparation.registration_id is not None:
            registration = self._registrations.get(preparation.registration_id)
            if registration is not None:
                registration.waiter_ids.discard(preparation_id)
                if not registration.waiter_ids:
                    self._cancel_registration(registration, reason=reason)
        self._append(
            "TRANSFER_ENDPOINT_PREPARATION_CANCELED",
            {
                "preparation_id": preparation_id,
                "transfer_id": preparation.task.metadata.transfer_id,
                "endpoint_id": preparation.key.endpoint_id,
                "mode": preparation.mode.value,
                "reason": reason,
            },
        )
        self.audit()
        return True

    def teardown_path(
        self,
        path: TopologyPath,
        *,
        reason: str,
        disable: bool = False,
    ) -> None:
        """Cancel pending preparations and invalidate one pooled endpoint key."""

        if not reason:
            raise ValueError("endpoint teardown reason must be non-empty")
        key = EndpointKey.from_path(path)
        entry = self._entry(key)
        canceled_ids = [
            preparation_id
            for preparation_id, preparation in sorted(self._preparations.items())
            if preparation.key == key
        ]
        for preparation_id in canceled_ids:
            self.cancel_preparation(preparation_id, reason=reason)
        previous_state = entry.state
        if entry.registration_id is not None:
            registration = self._registrations.get(entry.registration_id)
            if registration is not None:
                self._cancel_registration(registration, reason=reason)
        entry.generation += 1
        entry.registration_id = None
        entry.warm_since_ns = None
        entry.state = EndpointState.DISABLED if disable else EndpointState.COLD
        self._append(
            "TRANSFER_ENDPOINT_TORN_DOWN",
            {
                "endpoint_id": key.endpoint_id,
                "endpoint_key": key.to_dict(),
                "previous_state": previous_state.value,
                "new_state": entry.state.value,
                "generation": entry.generation,
                "reason": reason,
                "canceled_preparation_ids": canceled_ids,
            },
        )
        self.audit()

    def audit(self, *, require_quiescent: bool = False) -> None:
        """Check pool/registration/waiter/calendar ownership exactly."""

        reservation_ids = {
            registration.reservation.reservation_id for registration in self._registrations.values()
        }
        calendar_ids = {
            reservation.reservation_id for reservation in self.registration_worker.reservations()
        }
        if reservation_ids != calendar_ids:
            raise EndpointRegistrationError(
                "endpoint registrations and worker reservations diverged"
            )
        for key, entry in self._pool.items():
            if entry.key != key:
                raise EndpointRegistrationError("endpoint pool key diverged")
            registering = entry.state is EndpointState.REGISTERING
            if registering != (entry.registration_id is not None):
                raise EndpointRegistrationError(
                    "endpoint registration state and registration ID diverged"
                )
            if entry.registration_id is not None:
                registration = self._registrations.get(entry.registration_id)
                if registration is None or registration.key != key:
                    raise EndpointRegistrationError(
                        "endpoint pool references a missing registration"
                    )
            if (entry.state is EndpointState.WARM) != (entry.warm_since_ns is not None):
                raise EndpointRegistrationError("only warm endpoints have warm_since_ns")
        for registration_id, registration in self._registrations.items():
            if registration.registration_id != registration_id:
                raise EndpointRegistrationError("registration mapping key diverged")
            registration_entry = self._pool.get(registration.key)
            if (
                registration_entry is None
                or registration_entry.state is not EndpointState.REGISTERING
                or registration_entry.registration_id != registration_id
                or registration_entry.generation != registration.generation
                or not registration.waiter_ids
            ):
                raise EndpointRegistrationError("live registration has no exact pool owner")
            for preparation_id in registration.waiter_ids:
                preparation = self._preparations.get(preparation_id)
                if (
                    preparation is None
                    or preparation.registration_id != registration_id
                    or preparation.key != registration.key
                ):
                    raise EndpointRegistrationError(
                        "registration waiter has no exact preparation owner"
                    )
        for preparation_id, preparation in self._preparations.items():
            if preparation.preparation_id != preparation_id:
                raise EndpointRegistrationError("preparation mapping key diverged")
            if preparation.task.status is not TransferStatus.WAITING:
                raise EndpointRegistrationError(
                    "pending endpoint preparation owns a non-WAITING transfer"
                )
            if preparation.registration_id is not None:
                registration = self._registrations.get(preparation.registration_id)
                completed_registration = (
                    registration is None
                    and self._pool[preparation.key].state is EndpointState.WARM
                    and self._pool[preparation.key].generation == preparation.generation
                    and self._pool[preparation.key].warm_since_ns == preparation.ready_ns
                )
                if not completed_registration and (
                    registration is None or preparation_id not in registration.waiter_ids
                ):
                    raise EndpointRegistrationError(
                        "cold endpoint preparation lost its registration waiter"
                    )
        if require_quiescent and (self._registrations or self._preparations):
            raise EndpointRegistrationError(
                "quiescent endpoint audit found live registration/preparation state"
            )

    def _begin_registration(
        self,
        entry: _PoolEntry,
        *,
        preparation_id: str,
    ) -> _Registration:
        if entry.state is not EndpointState.COLD or entry.registration_id is not None:
            raise EndpointRegistrationError("cold registration requires an idle endpoint")
        registration_id = (
            f"endpoint-registration:{entry.key.endpoint_id}:generation-{entry.generation}"
        )
        if registration_id in self._known_registration_ids:
            raise EndpointRegistrationError("endpoint registration ID was reused")
        reservation = self.registration_worker.reserve(
            ready_ns=self.des.now_ns,
            duration_ns=self.profile.cold_latency_ns,
            reservation_id=f"{registration_id}:worker",
            cause="BASELINE_ENDPOINT_COLD_REGISTRATION",
        )
        start_handle: EventHandle | None = None
        completion_handle: EventHandle | None = None
        try:
            start_handle = self.des.schedule_at(
                reservation.start_ns,
                EventKind.ENDPOINT_REGISTRATION_START,
                event_id=f"{registration_id}:start",
                payload={"registration_id": registration_id},
            )
            completion_handle = self.des.schedule_at(
                reservation.end_ns,
                EventKind.ENDPOINT_REGISTRATION_COMPLETE,
                event_id=f"{registration_id}:complete",
                payload={"registration_id": registration_id},
            )
        except Exception:
            if start_handle is not None:
                self.des.cancel(start_handle, reason="ENDPOINT_REGISTRATION_SCHEDULE_ROLLBACK")
            if completion_handle is not None:
                self.des.cancel(
                    completion_handle,
                    reason="ENDPOINT_REGISTRATION_SCHEDULE_ROLLBACK",
                )
            self.registration_worker.cancel(reservation.reservation_id)
            raise
        registration = _Registration(
            registration_id=registration_id,
            key=entry.key,
            generation=entry.generation,
            reservation=reservation,
            start_handle=start_handle,
            completion_handle=completion_handle,
        )
        self._registrations[registration_id] = registration
        self._known_registration_ids.add(registration_id)
        entry.state = EndpointState.REGISTERING
        entry.registration_id = registration_id
        self._append(
            "TRANSFER_ENDPOINT_REGISTRATION_QUEUED",
            {
                "registration_id": registration_id,
                "owner_preparation_id": preparation_id,
                "endpoint_id": entry.key.endpoint_id,
                "generation": entry.generation,
                "worker_resource_id": reservation.resource_id,
                "worker_reservation_id": reservation.reservation_id,
                "worker_lane": reservation.lane,
                "queued_ns": self.des.now_ns,
                "start_ns": reservation.start_ns,
                "end_ns": reservation.end_ns,
                "cold_latency_ns": self.profile.cold_latency_ns,
            },
        )
        return registration

    def _cancel_registration(self, registration: _Registration, *, reason: str) -> None:
        self.des.cancel(registration.start_handle, reason=reason)
        self.des.cancel(registration.completion_handle, reason=reason)
        canceled = self.registration_worker.cancel(registration.reservation.reservation_id)
        if canceled != registration.reservation:
            raise EndpointRegistrationError("endpoint registration worker reservation disappeared")
        self._registrations.pop(registration.registration_id, None)
        entry = self._pool[registration.key]
        if entry.registration_id == registration.registration_id:
            entry.registration_id = None
            entry.warm_since_ns = None
            entry.generation += 1
            if entry.state is not EndpointState.DISABLED:
                entry.state = EndpointState.COLD
        self._append(
            "TRANSFER_ENDPOINT_REGISTRATION_CANCELED",
            {
                "registration_id": registration.registration_id,
                "endpoint_id": registration.key.endpoint_id,
                "generation": registration.generation,
                "reason": reason,
                "started": registration.started,
            },
        )

    def _on_registration_start(self, event: ScheduledEvent, des: GlobalDES) -> None:
        registration = self._registration_from_event(event, des)
        if registration.started:
            raise EndpointRegistrationError("endpoint registration started twice")
        if des.now_ns != registration.reservation.start_ns:
            raise EndpointRegistrationError("endpoint registration start time diverged")
        registration.started = True
        self._append(
            "TRANSFER_ENDPOINT_REGISTRATION_STARTED",
            {
                "registration_id": registration.registration_id,
                "endpoint_id": registration.key.endpoint_id,
                "generation": registration.generation,
                "worker_resource_id": registration.reservation.resource_id,
                "worker_reservation_id": registration.reservation.reservation_id,
                "worker_lane": registration.reservation.lane,
                "queue_wait_ns": (
                    registration.reservation.start_ns
                    - min(self._preparations[item].requested_ns for item in registration.waiter_ids)
                ),
            },
        )

    def _on_registration_complete(self, event: ScheduledEvent, des: GlobalDES) -> None:
        registration = self._registration_from_event(event, des)
        if not registration.started:
            raise EndpointRegistrationError("endpoint registration completed before start")
        if des.now_ns != registration.reservation.end_ns:
            raise EndpointRegistrationError("endpoint registration completion time diverged")
        entry = self._pool[registration.key]
        if (
            entry.state is not EndpointState.REGISTERING
            or entry.registration_id != registration.registration_id
            or entry.generation != registration.generation
            or not registration.waiter_ids
        ):
            raise EndpointRegistrationError("endpoint registration lost its pool generation")
        canceled = self.registration_worker.cancel(registration.reservation.reservation_id)
        if canceled != registration.reservation:
            raise EndpointRegistrationError(
                "completed endpoint registration lost its worker reservation"
            )
        entry.state = EndpointState.WARM
        entry.registration_id = None
        entry.warm_since_ns = des.now_ns
        del self._registrations[registration.registration_id]
        self._append(
            "TRANSFER_ENDPOINT_REGISTRATION_COMPLETED",
            {
                "registration_id": registration.registration_id,
                "endpoint_id": registration.key.endpoint_id,
                "generation": registration.generation,
                "worker_resource_id": registration.reservation.resource_id,
                "worker_reservation_id": registration.reservation.reservation_id,
                "worker_lane": registration.reservation.lane,
                "start_ns": registration.reservation.start_ns,
                "end_ns": registration.reservation.end_ns,
                "service_ns": self.profile.cold_latency_ns,
                "waiter_ids": sorted(registration.waiter_ids),
            },
        )
        self.audit()

    def _on_endpoint_ready(self, event: ScheduledEvent, des: GlobalDES) -> None:
        if des is not self.des or set(event.payload) != {"preparation_id"}:
            raise EndpointRegistrationError("ENDPOINT_READY payload or clock is invalid")
        preparation_id = event.payload["preparation_id"]
        if not isinstance(preparation_id, str) or not preparation_id:
            raise EndpointRegistrationError("ENDPOINT_READY preparation ID is invalid")
        try:
            preparation = self._preparations.pop(preparation_id)
        except KeyError as error:
            raise EndpointRegistrationError(
                "ENDPOINT_READY references an unknown preparation"
            ) from error
        entry = self._pool[preparation.key]
        if (
            entry.state is not EndpointState.WARM
            or entry.generation != preparation.generation
            or des.now_ns != preparation.ready_ns
        ):
            raise EndpointRegistrationError("endpoint became ready on a stale/cold generation")
        # The group is removed at its completion event; no live waiter set
        # remains to mutate here.
        if (
            preparation.registration_id is not None
            and preparation.registration_id in self._registrations
        ):
            raise EndpointRegistrationError("endpoint waiter ran before registration completion")
        self._append(
            "TRANSFER_ENDPOINT_READY",
            {
                "preparation_id": preparation.preparation_id,
                "transfer_id": preparation.task.metadata.transfer_id,
                "path_id": preparation.task.metadata.path.path_id,
                "endpoint_id": preparation.key.endpoint_id,
                "endpoint_key": preparation.key.to_dict(),
                "generation": preparation.generation,
                "mode": preparation.mode.value,
                "requested_ns": preparation.requested_ns,
                "ready_ns": preparation.ready_ns,
                "latency_ns": preparation.ready_ns - preparation.requested_ns,
                "registration_id": preparation.registration_id,
                "aggregated_into_gpu_forward": False,
            },
        )
        preparation.on_ready(preparation.task, des)
        self.audit()

    def _registration_from_event(
        self,
        event: ScheduledEvent,
        des: GlobalDES,
    ) -> _Registration:
        if des is not self.des or set(event.payload) != {"registration_id"}:
            raise EndpointRegistrationError("endpoint registration event payload/clock is invalid")
        registration_id = event.payload["registration_id"]
        if not isinstance(registration_id, str) or not registration_id:
            raise EndpointRegistrationError("endpoint registration ID is invalid")
        try:
            return self._registrations[registration_id]
        except KeyError as error:
            raise EndpointRegistrationError(
                "endpoint registration event references unknown state"
            ) from error

    def _entry(self, key: EndpointKey) -> _PoolEntry:
        return self._pool.setdefault(key, _PoolEntry(key=key))

    def _append(self, record_type: str, data: dict[str, object]) -> None:
        self.des.journal.append(self.des.now_ns, record_type, data)
