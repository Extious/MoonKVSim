"""Baseline transfer capacity and concurrency leases.

The fluid-flow controller accounts rate sharing, while this module accounts
the resources that cannot be inferred from a byte-rate path:

* temporary Host DRAM staging allocations for explicitly host-staged paths;
* one deterministic lane on every copy/QP concurrency resource named by the
  selected :class:`~moonkvsim.store.transfer_engine.TopologyPath`.

All durations and overlap assumptions remain uncalibrated E2 toy inputs.  A
lease is acquired before a :class:`TransferTask` or any flow is mutated.  The
``start_task`` wrapper is the fail-closed bridge to ``TransferRuntime``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Final

from moonkvsim.simulation.allocation import AllocationState, PhysicalAllocation
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import (
    FREE_ACCOUNT,
    AccountTransfer,
    CapacityLedger,
    CapacityResourceKind,
)
from moonkvsim.simulation.resource import ConcurrencyResource, Reservation
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction
from moonkvsim.store.transfer_engine import (
    TransferStatus,
    TransferTask,
    TransportKind,
)
from moonkvsim.store.transfer_runtime import TaskTerminalHandler, TransferRuntime

EVIDENCE_BOUNDARY: Final = "toy_E2_uncalibrated_transfer_resource_semantics"
HOST_STAGING_ACCOUNT_PREFIX: Final = "HOST_STAGING"

_HOST_STAGED_TRANSPORTS: Final = {
    TransportKind.RDMA_HOST_STAGED,
    TransportKind.TCP_HOST_STAGED,
}


class TransferResourceError(RuntimeError):
    """Base error for fail-closed transfer resource operations."""


class TransferResourceUnavailable(TransferResourceError):
    """Raised when a requested capacity or concurrency lease cannot be made."""


class TransferLeaseStatus(StrEnum):
    ACQUIRED = "ACQUIRED"
    STARTED = "STARTED"
    RELEASED = "RELEASED"


class TransferLeaseOutcome(StrEnum):
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    GPU_FAILURE = "GPU_FAILURE"


@dataclass(frozen=True, slots=True)
class StagingAllocationSpec:
    """Fully explained geometry for one temporary Host DRAM allocation."""

    allocation_id: str
    resource_id: str
    payload_bytes: int
    requested_bytes: int
    allocated_bytes: int
    padding_bytes: int
    allocator_metadata_bytes: int
    internal_fragmentation_bytes: int
    alignment_bytes: int

    def __post_init__(self) -> None:
        if not self.allocation_id or not self.resource_id:
            raise ValueError("staging allocation and resource IDs must be non-empty")
        byte_fields = (
            self.payload_bytes,
            self.requested_bytes,
            self.allocated_bytes,
            self.padding_bytes,
            self.allocator_metadata_bytes,
            self.internal_fragmentation_bytes,
        )
        if any(value < 0 for value in byte_fields):
            raise ValueError("staging allocation byte fields must be non-negative")
        if self.payload_bytes <= 0 or self.alignment_bytes <= 0:
            raise ValueError("staging payload and alignment must be positive")
        if self.requested_bytes != self.payload_bytes + self.padding_bytes:
            raise ValueError("requested staging bytes must equal payload plus padding")
        if self.allocated_bytes != (
            self.requested_bytes
            + self.allocator_metadata_bytes
            + self.internal_fragmentation_bytes
        ):
            raise ValueError("allocated staging bytes must be fully explained")
        if self.allocated_bytes % self.alignment_bytes:
            raise ValueError("allocated staging bytes must respect alignment")


@dataclass(frozen=True, slots=True)
class StagingAllocationBinding:
    """A physical staging allocation plus its transfer provenance."""

    allocation: PhysicalAllocation
    transfer_id: str
    slice_ids: tuple[str, ...]
    cause: str


@dataclass(frozen=True, slots=True)
class TransferResourceLease:
    lease_id: str
    transfer_id: str
    object_id: str
    replica_id: str
    slice_ids: tuple[str, ...]
    cause: str
    path_id: str
    transport: TransportKind
    acquired_ns: int
    start_ns: int
    end_ns: int
    duration_ns: int
    staging_allocations: tuple[StagingAllocationBinding, ...]
    concurrency_reservations: tuple[Reservation, ...]
    status: TransferLeaseStatus = TransferLeaseStatus.ACQUIRED
    started_ns: int | None = None
    released_ns: int | None = None
    outcome: TransferLeaseOutcome | None = None
    release_reason: str | None = None

    def __post_init__(self) -> None:
        identifiers = (
            self.lease_id,
            self.transfer_id,
            self.object_id,
            self.replica_id,
            self.cause,
            self.path_id,
        )
        if any(not value for value in identifiers) or not self.slice_ids:
            raise ValueError("lease identifiers, cause, and slice IDs must be non-empty")
        if self.acquired_ns < 0 or self.duration_ns <= 0:
            raise ValueError("lease time and duration are invalid")
        if self.start_ns < self.acquired_ns or self.end_ns != self.start_ns + self.duration_ns:
            raise ValueError("lease calendar interval is inconsistent")
        if not isinstance(self.transport, TransportKind):
            raise TypeError("lease transport must be a TransportKind")
        if not isinstance(self.status, TransferLeaseStatus):
            raise TypeError("lease status must be a TransferLeaseStatus")
        if len(set(self.slice_ids)) != len(self.slice_ids):
            raise ValueError("lease slice IDs must be unique")
        released = self.status is TransferLeaseStatus.RELEASED
        if released:
            if (
                self.released_ns is None
                or not isinstance(self.outcome, TransferLeaseOutcome)
                or not isinstance(self.release_reason, str)
            ):
                raise ValueError("released lease requires time, outcome, and reason")
            if not self.release_reason:
                raise ValueError("released lease reason must be non-empty")
            if not self.acquired_ns <= self.released_ns <= self.end_ns:
                raise ValueError("lease release time is outside its reserved interval")
        elif (
            self.released_ns is not None
            or self.outcome is not None
            or self.release_reason is not None
        ):
            raise ValueError("only released leases have release metadata")
        if self.status is TransferLeaseStatus.STARTED and self.started_ns != self.start_ns:
            raise ValueError("started lease must begin at its reserved start")
        if self.status is TransferLeaseStatus.ACQUIRED and self.started_ns is not None:
            raise ValueError("acquired lease cannot already have started_ns")
        if released and self.started_ns is not None and self.started_ns != self.start_ns:
            raise ValueError("released started lease has an invalid start time")


@dataclass(frozen=True, slots=True)
class ReplayedTransferResourceState:
    """Canonical result of deterministic lease/calendar journal replay."""

    active_lease_ids: tuple[str, ...]
    started_lease_ids: tuple[str, ...]
    released_lease_ids: tuple[str, ...]
    staging_allocation_states: tuple[tuple[str, AllocationState], ...]
    calendar_reservations: tuple[
        tuple[str, int, tuple[Reservation, ...]], ...
    ] = ()
    lease_snapshots: tuple[tuple[str, str], ...] = ()

    def snapshot_bytes(self) -> bytes:
        """Serialize the complete replayable state for byte-exact comparison."""

        value = {
            "active_lease_ids": list(self.active_lease_ids),
            "started_lease_ids": list(self.started_lease_ids),
            "released_lease_ids": list(self.released_lease_ids),
            "staging_allocation_states": [
                [allocation_id, state.value]
                for allocation_id, state in self.staging_allocation_states
            ],
            "calendar_reservations": [
                {
                    "resource_id": resource_id,
                    "lanes": lanes,
                    "reservations": [
                        {
                            "reservation_id": item.reservation_id,
                            "resource_id": item.resource_id,
                            "lane": item.lane,
                            "start_ns": item.start_ns,
                            "end_ns": item.end_ns,
                            "cause": item.cause,
                        }
                        for item in reservations
                    ],
                }
                for resource_id, lanes, reservations in self.calendar_reservations
            ],
            "lease_snapshots": [
                {
                    "lease_id": lease_id,
                    "snapshot": json.loads(snapshot_json),
                }
                for lease_id, snapshot_json in self.lease_snapshots
            ],
        }
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()


class TransferResourceLeaseManager:
    """Atomically lease baseline Host staging and copy/QP calendars."""

    def __init__(
        self,
        *,
        des: GlobalDES,
        capacity_ledgers: Mapping[str, CapacityLedger],
        concurrency_resources: Mapping[str, ConcurrencyResource],
    ) -> None:
        self.des = des
        self.capacity_ledgers = dict(capacity_ledgers)
        self.concurrency_resources = dict(concurrency_resources)
        if any(key != ledger.resource_id for key, ledger in self.capacity_ledgers.items()):
            raise ValueError("capacity ledger mapping keys must match resource IDs")
        if any(
            key != resource.resource_id
            for key, resource in self.concurrency_resources.items()
        ):
            raise ValueError("concurrency resource mapping keys must match resource IDs")
        self._leases: dict[str, TransferResourceLease] = {}
        self._lease_by_transfer: dict[str, str] = {}
        self._allocation_ids: set[str] = set()

    @property
    def active_lease_ids(self) -> tuple[str, ...]:
        return tuple(
            lease_id
            for lease_id, lease in sorted(self._leases.items())
            if lease.status is not TransferLeaseStatus.RELEASED
        )

    def lease(self, lease_id: str) -> TransferResourceLease:
        try:
            return self._leases[lease_id]
        except KeyError as error:
            raise KeyError(f"unknown transfer resource lease: {lease_id}") from error

    def snapshot(self) -> ReplayedTransferResourceState:
        """Return the online state in the same canonical form as journal replay."""

        leases = tuple(sorted(self._leases.items()))
        return ReplayedTransferResourceState(
            active_lease_ids=tuple(
                lease_id
                for lease_id, lease in leases
                if lease.status is not TransferLeaseStatus.RELEASED
            ),
            started_lease_ids=tuple(
                lease_id
                for lease_id, lease in leases
                if lease.status is TransferLeaseStatus.STARTED
            ),
            released_lease_ids=tuple(
                lease_id
                for lease_id, lease in leases
                if lease.status is TransferLeaseStatus.RELEASED
            ),
            staging_allocation_states=tuple(
                sorted(
                    (
                        binding.allocation.allocation_id,
                        binding.allocation.state,
                    )
                    for _, lease in leases
                    for binding in lease.staging_allocations
                )
            ),
            calendar_reservations=tuple(
                (
                    resource_id,
                    resource.lanes,
                    resource.reservations(),
                )
                for resource_id, resource in sorted(
                    self.concurrency_resources.items()
                )
            ),
            lease_snapshots=tuple(
                (lease_id, _canonical_json_text(_lease_snapshot_data(lease)))
                for lease_id, lease in leases
            ),
        )

    def acquire(
        self,
        task: TransferTask,
        *,
        lease_id: str,
        duration_ns: int,
        staging_specs: Mapping[str, StagingAllocationSpec] | None = None,
        latest_start_ns: int | None = None,
    ) -> TransferResourceLease:
        """Reserve the whole path before mutating ``task`` or creating flows.

        ``duration_ns`` is an explicit uncalibrated E2 calendar input.  A caller
        may pass ``latest_start_ns`` to fail rather than queue past a deadline.
        Host staging is conservatively charged from acquisition through release,
        including time waiting for a concurrency lane.
        """

        self._preflight_identity(task, lease_id=lease_id, duration_ns=duration_ns)
        specs = dict(staging_specs or {})
        path = task.metadata.path
        expected_staging = self._staging_resource_ids(task)
        if path.transport in _HOST_STAGED_TRANSPORTS:
            if set(specs) != set(expected_staging):
                raise TransferResourceError(
                    "host-staged path requires one explicit spec for every staging resource"
                )
        elif specs:
            raise TransferResourceError("direct/GDR path cannot reserve Host staging")

        allocations = self._build_staging_allocations(
            task,
            expected_resource_ids=expected_staging,
            specs=specs,
        )
        deltas = [
            AllocationDelta(
                resource_id=binding.allocation.resource_id,
                account_from=FREE_ACCOUNT,
                account_to=binding.allocation.owner_account,
                delta_bytes=binding.allocation.allocated_bytes,
                allocation_id=binding.allocation.allocation_id,
                object_id=binding.allocation.object_id,
                replica_id=binding.allocation.replica_id,
                transfer_id=binding.transfer_id,
            )
            for binding in allocations
        ]
        self._preview_capacity(deltas)

        concurrency_ids = path.concurrency_resource_ids
        unknown = set(concurrency_ids) - self.concurrency_resources.keys()
        if unknown:
            raise TransferResourceUnavailable(
                f"unknown concurrency resources: {sorted(unknown)}"
            )
        ready_ns = max(self.des.now_ns, task.metadata.ready_ns)
        start_ns, planned_lanes = self._common_start(
            concurrency_ids,
            ready_ns=ready_ns,
            duration_ns=duration_ns,
            latest_start_ns=latest_start_ns,
        )

        planned_reservations: list[Reservation] = []
        try:
            for resource_id, lane in planned_lanes:
                reservation_id = self._reservation_id(lease_id, resource_id)
                resource = self.concurrency_resources[resource_id]
                reservation = resource.reserve(
                    ready_ns=start_ns,
                    duration_ns=duration_ns,
                    reservation_id=reservation_id,
                    cause=task.metadata.cause,
                )
                if reservation.lane != lane or reservation.start_ns != start_ns:
                    raise TransferResourceError(
                        "concurrency calendar changed after atomic preflight"
                    )
                planned_reservations.append(reservation)

            if deltas:
                ResourceTransaction(
                    event_id=f"{lease_id}:staging-acquire",
                    timestamp_ns=self.des.now_ns,
                    cause=task.metadata.cause,
                    allocation_deltas=deltas,
                ).commit(self.capacity_ledgers, journal=self.des.journal)
        except Exception:
            for reservation in reversed(planned_reservations):
                self.concurrency_resources[reservation.resource_id].cancel(
                    reservation.reservation_id
                )
            raise

        lease = TransferResourceLease(
            lease_id=lease_id,
            transfer_id=task.metadata.transfer_id,
            object_id=task.metadata.object_id,
            replica_id=task.metadata.replica_id,
            slice_ids=tuple(item.slice_id for item in task.slices),
            cause=task.metadata.cause,
            path_id=path.path_id,
            transport=path.transport,
            acquired_ns=self.des.now_ns,
            start_ns=start_ns,
            end_ns=start_ns + duration_ns,
            duration_ns=duration_ns,
            staging_allocations=allocations,
            concurrency_reservations=tuple(planned_reservations),
        )
        self._leases[lease_id] = lease
        self._lease_by_transfer[lease.transfer_id] = lease_id
        self._allocation_ids.update(
            item.allocation.allocation_id for item in lease.staging_allocations
        )
        self.des.journal.append(
            self.des.now_ns,
            "TRANSFER_RESOURCE_LEASE_ACQUIRED",
            self._acquired_data(lease),
        )
        self.audit()
        return lease

    def start_task(
        self,
        runtime: TransferRuntime,
        task: TransferTask,
        *,
        lease_id: str,
        on_terminal: TaskTerminalHandler | None = None,
    ) -> None:
        """Start a runtime task only when its complete resource lease is ready."""

        lease = self.lease(lease_id)
        if runtime.des is not self.des:
            raise TransferResourceError("runtime and resource lease use different DES clocks")
        if lease.status is not TransferLeaseStatus.ACQUIRED:
            raise TransferResourceError("only an acquired lease may start a task")
        if lease.transfer_id != task.metadata.transfer_id:
            raise TransferResourceError("lease belongs to a different transfer")
        if lease.path_id != task.metadata.path.path_id:
            raise TransferResourceError("lease path differs from transfer path")
        if self.des.now_ns != lease.start_ns:
            raise TransferResourceUnavailable(
                "task must start at its exact reserved calendar timestamp"
            )
        self._assert_no_live_lane_overlap(lease)
        self._audit_live_lease(lease)

        def terminal_handler(terminal_task: TransferTask, des: GlobalDES) -> None:
            if des is not self.des:
                raise TransferResourceError("terminal callback used a different DES")
            outcome, reason = self._terminal_outcome(terminal_task)
            self.release(lease_id, outcome=outcome, reason=reason)
            if on_terminal is not None:
                on_terminal(terminal_task, des)

        runtime.start_task(task, on_terminal=terminal_handler)
        started = replace(
            lease,
            status=TransferLeaseStatus.STARTED,
            started_ns=self.des.now_ns,
        )
        self._leases[lease_id] = started
        self.des.journal.append(
            self.des.now_ns,
            "TRANSFER_RESOURCE_LEASE_STARTED",
            {
                "lease_id": lease_id,
                "transfer_id": lease.transfer_id,
                "start_ns": self.des.now_ns,
                "cause": lease.cause,
                "evidence_boundary": EVIDENCE_BOUNDARY,
            },
        )
        self.audit()

    def release(
        self,
        lease_id: str,
        *,
        outcome: TransferLeaseOutcome,
        reason: str,
    ) -> TransferResourceLease:
        """Release every staging byte and lane exactly once."""

        if not isinstance(outcome, TransferLeaseOutcome):
            raise TypeError("release outcome must be a TransferLeaseOutcome")
        if not isinstance(reason, str) or not reason:
            raise ValueError("release reason must be non-empty")
        lease = self.lease(lease_id)
        if lease.status is TransferLeaseStatus.RELEASED:
            raise TransferResourceError("transfer resource lease was already released")
        if self.des.now_ns > lease.end_ns:
            raise TransferResourceError(
                "transfer exceeded its reserved concurrency interval; "
                "the duration model must be corrected before this run is valid"
            )
        self._audit_live_lease(lease)

        deltas = [
            AllocationDelta(
                resource_id=binding.allocation.resource_id,
                account_from=binding.allocation.owner_account,
                account_to=FREE_ACCOUNT,
                delta_bytes=binding.allocation.allocated_bytes,
                allocation_id=binding.allocation.allocation_id,
                object_id=binding.allocation.object_id,
                replica_id=binding.allocation.replica_id,
                transfer_id=binding.transfer_id,
            )
            for binding in lease.staging_allocations
        ]
        self._preview_capacity(deltas)
        if deltas:
            ResourceTransaction(
                event_id=f"{lease_id}:staging-release",
                timestamp_ns=self.des.now_ns,
                cause=reason,
                allocation_deltas=deltas,
            ).commit(self.capacity_ledgers, journal=self.des.journal)

        for reservation in lease.concurrency_reservations:
            canceled = self.concurrency_resources[reservation.resource_id].cancel(
                reservation.reservation_id
            )
            if canceled != reservation:
                raise TransferResourceError("concurrency reservation disappeared before release")

        released_allocations = tuple(
            replace(
                binding,
                allocation=binding.allocation.transition(
                    AllocationState.RELEASED,
                    timestamp_ns=self.des.now_ns,
                ),
            )
            for binding in lease.staging_allocations
        )
        released = replace(
            lease,
            staging_allocations=released_allocations,
            status=TransferLeaseStatus.RELEASED,
            released_ns=self.des.now_ns,
            outcome=outcome,
            release_reason=reason,
        )
        self._leases[lease_id] = released
        self.des.journal.append(
            self.des.now_ns,
            "TRANSFER_RESOURCE_LEASE_RELEASED",
            {
                "lease_id": lease_id,
                "transfer_id": lease.transfer_id,
                "released_ns": self.des.now_ns,
                "outcome": outcome.value,
                "reason": reason,
                "overran_reserved_end": False,
                "staging_allocation_ids": [
                    item.allocation.allocation_id for item in released_allocations
                ],
                "concurrency_reservation_ids": [
                    item.reservation_id for item in lease.concurrency_reservations
                ],
                "evidence_boundary": EVIDENCE_BOUNDARY,
            },
        )
        self.audit()
        return released

    def audit(self) -> None:
        """Check one charge/reservation per live lease and no live lane overlap."""

        seen_allocations: set[str] = set()
        seen_reservations: set[str] = set()
        live_lanes: dict[tuple[str, int], str] = {}
        for lease_id, lease in sorted(self._leases.items()):
            for binding in lease.staging_allocations:
                allocation = binding.allocation
                if allocation.allocation_id in seen_allocations:
                    raise TransferResourceError("staging allocation is charged by two leases")
                seen_allocations.add(allocation.allocation_id)
                charged = self.capacity_ledgers[allocation.resource_id].bytes_in(
                    allocation.owner_account
                )
                if lease.status is TransferLeaseStatus.RELEASED:
                    if allocation.state is not AllocationState.RELEASED or charged != 0:
                        raise TransferResourceError("released staging allocation remains charged")
                elif allocation.state is not AllocationState.RESERVED or charged != (
                    allocation.allocated_bytes
                ):
                    raise TransferResourceError("live staging allocation charge diverged")

            if lease.status is TransferLeaseStatus.RELEASED:
                continue
            self._audit_live_lease(lease)
            for reservation in lease.concurrency_reservations:
                if reservation.reservation_id in seen_reservations:
                    raise TransferResourceError("concurrency reservation belongs to two leases")
                seen_reservations.add(reservation.reservation_id)
                if lease.status is TransferLeaseStatus.STARTED:
                    key = (reservation.resource_id, reservation.lane)
                    other = live_lanes.get(key)
                    if other is not None:
                        raise TransferResourceError(
                            f"started leases overlap on live lane: {other}, {lease_id}"
                        )
                    live_lanes[key] = lease_id

    def _preflight_identity(
        self,
        task: TransferTask,
        *,
        lease_id: str,
        duration_ns: int,
    ) -> None:
        if not lease_id or duration_ns <= 0:
            raise ValueError("lease_id and positive duration_ns are required")
        if lease_id in self._leases:
            raise TransferResourceError(f"duplicate lease_id: {lease_id}")
        transfer_id = task.metadata.transfer_id
        if transfer_id in self._lease_by_transfer:
            raise TransferResourceError(f"transfer already has a resource lease: {transfer_id}")
        if task.status is not TransferStatus.WAITING:
            raise TransferResourceError("resource lease requires a WAITING transfer task")
        try:
            task.audit()
        except RuntimeError as error:
            raise TransferResourceError("transfer task failed byte-layout audit") from error
        last_timestamp_ns = self.des.journal.last_timestamp_ns
        if last_timestamp_ns is not None and last_timestamp_ns > self.des.now_ns:
            raise TransferResourceError("journal is ahead of the shared DES clock")

    def _build_staging_allocations(
        self,
        task: TransferTask,
        *,
        expected_resource_ids: tuple[str, ...],
        specs: Mapping[str, StagingAllocationSpec],
    ) -> tuple[StagingAllocationBinding, ...]:
        bindings: list[StagingAllocationBinding] = []
        slice_ids = tuple(item.slice_id for item in task.slices)
        for resource_id in expected_resource_ids:
            spec = specs[resource_id]
            if spec.resource_id != resource_id:
                raise TransferResourceError("staging spec key and resource_id differ")
            if spec.payload_bytes != task.metadata.total_bytes:
                raise TransferResourceError(
                    "staging payload must explicitly cover the complete transfer"
                )
            if spec.allocation_id in self._allocation_ids:
                raise TransferResourceError(
                    f"duplicate staging allocation_id: {spec.allocation_id}"
                )
            ledger = self.capacity_ledgers.get(resource_id)
            if ledger is None:
                raise TransferResourceUnavailable(
                    f"unknown Host staging capacity resource: {resource_id}"
                )
            if ledger.resource_kind is not CapacityResourceKind.HOST_DRAM:
                raise TransferResourceError("staging allocation must use a HOST_DRAM ledger")
            owner_account = self._staging_account(spec.allocation_id)
            if ledger.bytes_in(owner_account):
                raise TransferResourceError("staging owner account is already charged")
            allocation = PhysicalAllocation(
                allocation_id=spec.allocation_id,
                object_id=task.metadata.object_id,
                replica_id=task.metadata.replica_id,
                resource_id=resource_id,
                owner_account=owner_account,
                payload_bytes=spec.payload_bytes,
                requested_bytes=spec.requested_bytes,
                allocated_bytes=spec.allocated_bytes,
                padding_bytes=spec.padding_bytes,
                allocator_metadata_bytes=spec.allocator_metadata_bytes,
                internal_fragmentation_bytes=spec.internal_fragmentation_bytes,
                alignment_bytes=spec.alignment_bytes,
                state=AllocationState.RESERVED,
                created_at_ns=self.des.now_ns,
            )
            bindings.append(
                StagingAllocationBinding(
                    allocation=allocation,
                    transfer_id=task.metadata.transfer_id,
                    slice_ids=slice_ids,
                    cause=task.metadata.cause,
                )
            )
        allocation_ids = [item.allocation.allocation_id for item in bindings]
        if len(set(allocation_ids)) != len(allocation_ids):
            raise TransferResourceError("staging allocation IDs must be unique")
        return tuple(bindings)

    def _preview_capacity(self, deltas: list[AllocationDelta]) -> None:
        grouped: dict[str, list[AccountTransfer]] = defaultdict(list)
        for delta in deltas:
            ledger = self.capacity_ledgers.get(delta.resource_id)
            if ledger is None:
                raise TransferResourceUnavailable(
                    f"unknown capacity resource: {delta.resource_id}"
                )
            grouped[delta.resource_id].append(delta.as_transfer())
        try:
            for resource_id, transfers in grouped.items():
                self.capacity_ledgers[resource_id].preview(transfers)
        except ValueError as error:
            raise TransferResourceUnavailable("insufficient Host staging capacity") from error

    def _common_start(
        self,
        resource_ids: tuple[str, ...],
        *,
        ready_ns: int,
        duration_ns: int,
        latest_start_ns: int | None,
    ) -> tuple[int, tuple[tuple[str, int], ...]]:
        if latest_start_ns is not None and latest_start_ns < ready_ns:
            raise TransferResourceUnavailable("concurrency deadline precedes ready time")
        if not resource_ids:
            return ready_ns, ()
        candidate = ready_ns
        while True:
            fits = [
                (
                    resource_id,
                    *self._first_fit(
                        self.concurrency_resources[resource_id],
                        candidate,
                        duration_ns,
                    ),
                )
                for resource_id in resource_ids
            ]
            next_candidate = max(start_ns for _, start_ns, _ in fits)
            if latest_start_ns is not None and next_candidate > latest_start_ns:
                raise TransferResourceUnavailable(
                    "no common concurrency slot before latest_start_ns"
                )
            if all(start_ns == candidate for _, start_ns, _ in fits):
                return candidate, tuple(
                    (resource_id, lane) for resource_id, _, lane in fits
                )
            candidate = next_candidate

    @staticmethod
    def _first_fit(
        resource: ConcurrencyResource,
        ready_ns: int,
        duration_ns: int,
    ) -> tuple[int, int]:
        candidates: list[tuple[int, int]] = []
        for lane in range(resource.lanes):
            candidate = ready_ns
            for reservation in resource.reservations_on_lane(lane):
                if candidate + duration_ns <= reservation.start_ns:
                    break
                if candidate < reservation.end_ns:
                    candidate = reservation.end_ns
            candidates.append((candidate, lane))
        return min(candidates)

    def _assert_no_live_lane_overlap(self, candidate: TransferResourceLease) -> None:
        candidate_lanes = {
            (reservation.resource_id, reservation.lane)
            for reservation in candidate.concurrency_reservations
        }
        for lease_id, lease in self._leases.items():
            if lease_id == candidate.lease_id or lease.status is not TransferLeaseStatus.STARTED:
                continue
            occupied = {
                (reservation.resource_id, reservation.lane)
                for reservation in lease.concurrency_reservations
            }
            if candidate_lanes.intersection(occupied):
                raise TransferResourceUnavailable(
                    "an earlier transfer still occupies a reserved concurrency lane"
                )

    def _audit_live_lease(self, lease: TransferResourceLease) -> None:
        for binding in lease.staging_allocations:
            allocation = binding.allocation
            ledger = self.capacity_ledgers.get(allocation.resource_id)
            if ledger is None or ledger.bytes_in(allocation.owner_account) != (
                allocation.allocated_bytes
            ):
                raise TransferResourceError("staging ledger charge is missing or altered")
        for expected in lease.concurrency_reservations:
            resource = self.concurrency_resources.get(expected.resource_id)
            if resource is None:
                raise TransferResourceError("leased concurrency resource disappeared")
            actual = resource.reservation(expected.reservation_id)
            if actual != expected:
                raise TransferResourceError("leased concurrency reservation diverged")

    @staticmethod
    def _staging_resource_ids(task: TransferTask) -> tuple[str, ...]:
        path = task.metadata.path
        ordered = (
            path.source_host_staging_resource_id,
            path.destination_host_staging_resource_id,
        )
        return tuple(dict.fromkeys(item for item in ordered if item is not None))

    @staticmethod
    def _terminal_outcome(
        task: TransferTask,
    ) -> tuple[TransferLeaseOutcome, str]:
        if task.status is TransferStatus.COMPLETED:
            return TransferLeaseOutcome.COMPLETED, "TRANSFER_COMPLETED"
        reason = task.abort_reason or f"TRANSFER_{task.status.value}"
        if "GPU_FAILURE" in reason.upper():
            return TransferLeaseOutcome.GPU_FAILURE, reason
        return TransferLeaseOutcome.ABORTED, reason

    @staticmethod
    def _staging_account(allocation_id: str) -> str:
        return f"{HOST_STAGING_ACCOUNT_PREFIX}:{allocation_id}"

    @staticmethod
    def _reservation_id(lease_id: str, resource_id: str) -> str:
        return f"{lease_id}:concurrency:{resource_id}"

    @staticmethod
    def _acquired_data(lease: TransferResourceLease) -> dict[str, Any]:
        return {
            "lease_id": lease.lease_id,
            "transfer_id": lease.transfer_id,
            "object_id": lease.object_id,
            "replica_id": lease.replica_id,
            "slice_ids": list(lease.slice_ids),
            "cause": lease.cause,
            "path_id": lease.path_id,
            "transport": lease.transport.value,
            "acquired_ns": lease.acquired_ns,
            "start_ns": lease.start_ns,
            "end_ns": lease.end_ns,
            "duration_ns": lease.duration_ns,
            "staging_allocations": [
                {
                    "allocation_id": binding.allocation.allocation_id,
                    "resource_id": binding.allocation.resource_id,
                    "owner_account": binding.allocation.owner_account,
                    "transfer_id": binding.transfer_id,
                    "slice_ids": list(binding.slice_ids),
                    "cause": binding.cause,
                    "payload_bytes": binding.allocation.payload_bytes,
                    "requested_bytes": binding.allocation.requested_bytes,
                    "allocated_bytes": binding.allocation.allocated_bytes,
                    "padding_bytes": binding.allocation.padding_bytes,
                    "allocator_metadata_bytes": (
                        binding.allocation.allocator_metadata_bytes
                    ),
                    "internal_fragmentation_bytes": (
                        binding.allocation.internal_fragmentation_bytes
                    ),
                    "alignment_bytes": binding.allocation.alignment_bytes,
                    "state": binding.allocation.state.value,
                }
                for binding in lease.staging_allocations
            ],
            "concurrency_reservations": [
                {
                    "reservation_id": item.reservation_id,
                    "resource_id": item.resource_id,
                    "lane": item.lane,
                    "start_ns": item.start_ns,
                    "end_ns": item.end_ns,
                    "cause": item.cause,
                }
                for item in lease.concurrency_reservations
            ],
            "evidence_boundary": EVIDENCE_BOUNDARY,
            "fidelity_gaps": [
                "transfer_duration_and_overlap_are_uncalibrated",
                "queued_staging_is_conservatively_charged_from_acquisition",
            ],
        }


def transfer_flow_queue_wait_ns_by_flow(journal: EventJournal) -> dict[str, int]:
    """Map actual runtime flow IDs to their journaled calendar queue wait.

    A lease may be released before a task starts, so only runtime flow-start
    records receive an output value.  Transfers without a resource lease are
    intentionally absent and therefore retain the output layer's zero default.
    """

    calendar_by_slice: dict[tuple[str, str], tuple[int, int]] = {}
    for record in journal.records:
        if record.record_type != "TRANSFER_RESOURCE_LEASE_ACQUIRED":
            continue
        data = record.data
        transfer_id = _required_string(data, "transfer_id")
        acquired_ns = _required_integer(data, "acquired_ns")
        start_ns = _required_integer(data, "start_ns")
        if acquired_ns != record.timestamp_ns or start_ns < acquired_ns:
            raise TransferResourceError("lease queue-wait interval is inconsistent")
        wait_ns = start_ns - acquired_ns
        for slice_id in _required_unique_string_list(data, "slice_ids"):
            key = (transfer_id, slice_id)
            if key in calendar_by_slice:
                raise TransferResourceError("one transfer slice has two resource leases")
            calendar_by_slice[key] = (start_ns, wait_ns)

    waits: dict[str, int] = {}
    started_slices: set[tuple[str, str]] = set()
    for record in journal.records:
        if record.record_type != "TRANSFER_RUNTIME_SLICE_FLOW_STARTED":
            continue
        data = record.data
        key = (
            _required_string(data, "transfer_id"),
            _required_string(data, "slice_id"),
        )
        calendar = calendar_by_slice.get(key)
        if calendar is None:
            continue
        start_ns, wait_ns = calendar
        if record.timestamp_ns != start_ns:
            raise TransferResourceError(
                "runtime flow start differs from its reserved calendar start"
            )
        if key in started_slices:
            raise TransferResourceError("one leased transfer slice started two flows")
        started_slices.add(key)
        flow_id = _required_string(data, "flow_id")
        if flow_id in waits:
            raise TransferResourceError("one runtime flow has two queue-wait records")
        waits[flow_id] = wait_ns
    return dict(sorted(waits.items()))


def _lease_snapshot_data(lease: TransferResourceLease) -> dict[str, Any]:
    return {
        "lease_id": lease.lease_id,
        "transfer_id": lease.transfer_id,
        "object_id": lease.object_id,
        "replica_id": lease.replica_id,
        "slice_ids": list(lease.slice_ids),
        "cause": lease.cause,
        "path_id": lease.path_id,
        "transport": lease.transport.value,
        "acquired_ns": lease.acquired_ns,
        "start_ns": lease.start_ns,
        "end_ns": lease.end_ns,
        "duration_ns": lease.duration_ns,
        "status": lease.status.value,
        "started_ns": lease.started_ns,
        "released_ns": lease.released_ns,
        "outcome": None if lease.outcome is None else lease.outcome.value,
        "release_reason": lease.release_reason,
        "staging_allocations": [
            {
                "allocation_id": binding.allocation.allocation_id,
                "resource_id": binding.allocation.resource_id,
                "owner_account": binding.allocation.owner_account,
                "transfer_id": binding.transfer_id,
                "slice_ids": list(binding.slice_ids),
                "cause": binding.cause,
                "payload_bytes": binding.allocation.payload_bytes,
                "requested_bytes": binding.allocation.requested_bytes,
                "allocated_bytes": binding.allocation.allocated_bytes,
                "padding_bytes": binding.allocation.padding_bytes,
                "allocator_metadata_bytes": binding.allocation.allocator_metadata_bytes,
                "internal_fragmentation_bytes": (
                    binding.allocation.internal_fragmentation_bytes
                ),
                "alignment_bytes": binding.allocation.alignment_bytes,
                "state": binding.allocation.state.value,
                "created_at_ns": binding.allocation.created_at_ns,
                "released_at_ns": binding.allocation.released_at_ns,
            }
            for binding in lease.staging_allocations
        ],
        "concurrency_reservations": [
            _reservation_data(item) for item in lease.concurrency_reservations
        ],
    }


def _reservation_data(reservation: Reservation) -> dict[str, Any]:
    return {
        "reservation_id": reservation.reservation_id,
        "resource_id": reservation.resource_id,
        "lane": reservation.lane,
        "start_ns": reservation.start_ns,
        "end_ns": reservation.end_ns,
        "cause": reservation.cause,
    }


def _canonical_json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def replay_transfer_resource_calendar(
    journal: EventJournal,
    concurrency_resources: Mapping[str, ConcurrencyResource],
) -> ReplayedTransferResourceState:
    """Rebuild active copy/QP calendars and staging lifecycle from the journal."""

    resources = dict(concurrency_resources)
    if any(key != resource.resource_id for key, resource in resources.items()):
        raise TransferResourceError("replay resource keys must match resource IDs")
    if any(resource.reservations() for resource in resources.values()):
        raise TransferResourceError("calendar replay requires pristine resources")

    statuses: dict[str, TransferLeaseStatus] = {}
    reservations_by_lease: dict[str, tuple[Reservation, ...]] = {}
    allocations_by_lease: dict[str, tuple[str, ...]] = {}
    allocation_states: dict[str, AllocationState] = {}
    lease_documents: dict[str, dict[str, Any]] = {}

    for record in journal.records:
        data = record.data
        if record.record_type == "TRANSFER_RESOURCE_LEASE_ACQUIRED":
            lease_id = _required_string(data, "lease_id")
            if lease_id in statuses:
                raise TransferResourceError("duplicate lease acquisition in replay")
            transfer_id = _required_string(data, "transfer_id")
            object_id = _required_string(data, "object_id")
            replica_id = _required_string(data, "replica_id")
            cause = _required_string(data, "cause")
            path_id = _required_string(data, "path_id")
            try:
                transport = TransportKind(_required_string(data, "transport"))
            except ValueError as error:
                raise TransferResourceError("unknown replayed transfer transport") from error
            acquired_ns = _required_integer(data, "acquired_ns")
            start_ns = _required_integer(data, "start_ns")
            end_ns = _required_integer(data, "end_ns")
            duration_ns = _required_integer(data, "duration_ns")
            if (
                acquired_ns != record.timestamp_ns
                or acquired_ns < 0
                or duration_ns <= 0
                or start_ns < acquired_ns
                or end_ns != start_ns + duration_ns
            ):
                raise TransferResourceError("replayed lease calendar interval is inconsistent")
            lease_slice_ids = _required_unique_string_list(data, "slice_ids")
            raw_reservations = _required_list(data, "concurrency_reservations")
            replayed: list[Reservation] = []
            reservation_documents: list[dict[str, Any]] = []
            reservation_resource_ids: set[str] = set()
            for raw in raw_reservations:
                item = _required_mapping(raw, "concurrency reservation")
                resource_id = _required_string(item, "resource_id")
                if resource_id in reservation_resource_ids:
                    raise TransferResourceError(
                        "replayed lease reserves one concurrency resource twice"
                    )
                reservation_resource_ids.add(resource_id)
                resource = resources.get(resource_id)
                if resource is None:
                    raise TransferResourceError(
                        f"unknown concurrency replay resource: {resource_id}"
                    )
                reservation_start_ns = _required_integer(item, "start_ns")
                reservation_end_ns = _required_integer(item, "end_ns")
                reservation_id = _required_string(item, "reservation_id")
                reservation_cause = _required_string(item, "cause")
                if (
                    reservation_start_ns != start_ns
                    or reservation_end_ns != end_ns
                    or reservation_id
                    != TransferResourceLeaseManager._reservation_id(
                        lease_id,
                        resource_id,
                    )
                ):
                    raise TransferResourceError(
                        "replayed concurrency reservation differs from its lease interval"
                    )
                reservation = resource.reserve(
                    ready_ns=reservation_start_ns,
                    duration_ns=reservation_end_ns - reservation_start_ns,
                    reservation_id=reservation_id,
                    cause=reservation_cause,
                )
                if (
                    reservation.lane != _required_integer(item, "lane")
                    or reservation.start_ns != reservation_start_ns
                    or reservation.end_ns != reservation_end_ns
                    or reservation.cause != cause
                ):
                    raise TransferResourceError("replayed concurrency reservation diverged")
                replayed.append(reservation)
                reservation_documents.append(_reservation_data(reservation))
            reservations_by_lease[lease_id] = tuple(replayed)

            raw_allocations = _required_list(data, "staging_allocations")
            allocation_ids: list[str] = []
            allocation_documents: list[dict[str, Any]] = []
            for raw in raw_allocations:
                item = _required_mapping(raw, "staging allocation")
                allocation_id = _required_string(item, "allocation_id")
                if allocation_id in allocation_states:
                    raise TransferResourceError("duplicate staging allocation in replay")
                if _required_string(item, "transfer_id") != transfer_id:
                    raise TransferResourceError("staging allocation transfer provenance differs")
                if _required_string(item, "cause") != cause:
                    raise TransferResourceError("staging allocation cause differs")
                if _required_unique_string_list(item, "slice_ids") != lease_slice_ids:
                    raise TransferResourceError("staging allocation slice provenance differs")
                if _required_string(item, "state") != AllocationState.RESERVED.value:
                    raise TransferResourceError("new staging allocation is not RESERVED")
                _validate_replayed_geometry(item)
                resource_id = _required_string(item, "resource_id")
                owner_account = _required_string(item, "owner_account")
                if owner_account != TransferResourceLeaseManager._staging_account(
                    allocation_id
                ):
                    raise TransferResourceError("staging owner account differs in replay")
                allocation_states[allocation_id] = AllocationState.RESERVED
                allocation_ids.append(allocation_id)
                allocation_documents.append(
                    {
                        "allocation_id": allocation_id,
                        "resource_id": resource_id,
                        "owner_account": owner_account,
                        "transfer_id": transfer_id,
                        "slice_ids": list(lease_slice_ids),
                        "cause": cause,
                        "payload_bytes": _required_integer(item, "payload_bytes"),
                        "requested_bytes": _required_integer(item, "requested_bytes"),
                        "allocated_bytes": _required_integer(item, "allocated_bytes"),
                        "padding_bytes": _required_integer(item, "padding_bytes"),
                        "allocator_metadata_bytes": _required_integer(
                            item,
                            "allocator_metadata_bytes",
                        ),
                        "internal_fragmentation_bytes": _required_integer(
                            item,
                            "internal_fragmentation_bytes",
                        ),
                        "alignment_bytes": _required_integer(item, "alignment_bytes"),
                        "state": AllocationState.RESERVED.value,
                        "created_at_ns": acquired_ns,
                        "released_at_ns": None,
                    }
                )
            allocations_by_lease[lease_id] = tuple(allocation_ids)
            statuses[lease_id] = TransferLeaseStatus.ACQUIRED
            lease_documents[lease_id] = {
                "lease_id": lease_id,
                "transfer_id": transfer_id,
                "object_id": object_id,
                "replica_id": replica_id,
                "slice_ids": list(lease_slice_ids),
                "cause": cause,
                "path_id": path_id,
                "transport": transport.value,
                "acquired_ns": acquired_ns,
                "start_ns": start_ns,
                "end_ns": end_ns,
                "duration_ns": duration_ns,
                "status": TransferLeaseStatus.ACQUIRED.value,
                "started_ns": None,
                "released_ns": None,
                "outcome": None,
                "release_reason": None,
                "staging_allocations": allocation_documents,
                "concurrency_reservations": reservation_documents,
            }

        elif record.record_type == "TRANSFER_RESOURCE_LEASE_STARTED":
            lease_id = _required_string(data, "lease_id")
            if statuses.get(lease_id) is not TransferLeaseStatus.ACQUIRED:
                raise TransferResourceError("replay start requires an acquired lease")
            document = lease_documents[lease_id]
            started_ns = _required_integer(data, "start_ns")
            if (
                record.timestamp_ns != started_ns
                or started_ns != document["start_ns"]
                or _required_string(data, "transfer_id") != document["transfer_id"]
                or _required_string(data, "cause") != document["cause"]
            ):
                raise TransferResourceError("replayed lease start metadata differs")
            statuses[lease_id] = TransferLeaseStatus.STARTED
            document["status"] = TransferLeaseStatus.STARTED.value
            document["started_ns"] = started_ns

        elif record.record_type == "TRANSFER_RESOURCE_LEASE_RELEASED":
            lease_id = _required_string(data, "lease_id")
            if statuses.get(lease_id) not in {
                TransferLeaseStatus.ACQUIRED,
                TransferLeaseStatus.STARTED,
            }:
                raise TransferResourceError("replay release requires one live lease")
            document = lease_documents[lease_id]
            released_ns = _required_integer(data, "released_ns")
            if (
                record.timestamp_ns != released_ns
                or not document["acquired_ns"] <= released_ns <= document["end_ns"]
                or _required_string(data, "transfer_id") != document["transfer_id"]
                or _required_boolean(data, "overran_reserved_end")
            ):
                raise TransferResourceError("replayed lease release metadata differs")
            try:
                outcome = TransferLeaseOutcome(_required_string(data, "outcome"))
            except ValueError as error:
                raise TransferResourceError("unknown replayed lease outcome") from error
            reason = _required_string(data, "reason")
            expected_reservation_ids = tuple(
                item.reservation_id for item in reservations_by_lease[lease_id]
            )
            recorded_reservation_ids = _required_unique_string_list(
                data,
                "concurrency_reservation_ids",
            )
            if recorded_reservation_ids != expected_reservation_ids:
                raise TransferResourceError("released reservation IDs differ in replay")
            for reservation in reservations_by_lease[lease_id]:
                canceled = resources[reservation.resource_id].cancel(
                    reservation.reservation_id
                )
                if canceled != reservation:
                    raise TransferResourceError("replay could not release reservation")
            recorded_allocation_ids = _required_unique_string_list(
                data,
                "staging_allocation_ids",
            )
            if recorded_allocation_ids != allocations_by_lease[lease_id]:
                raise TransferResourceError("released allocation IDs differ in replay")
            for allocation_index, allocation_id in enumerate(
                allocations_by_lease[lease_id]
            ):
                if allocation_states[allocation_id] is not AllocationState.RESERVED:
                    raise TransferResourceError("staging allocation was already released")
                allocation_states[allocation_id] = AllocationState.RELEASED
                allocation_document = document["staging_allocations"][allocation_index]
                allocation_document["state"] = AllocationState.RELEASED.value
                allocation_document["released_at_ns"] = released_ns
            statuses[lease_id] = TransferLeaseStatus.RELEASED
            document["status"] = TransferLeaseStatus.RELEASED.value
            document["released_ns"] = released_ns
            document["outcome"] = outcome.value
            document["release_reason"] = reason

    return ReplayedTransferResourceState(
        active_lease_ids=tuple(
            lease_id
            for lease_id, status in sorted(statuses.items())
            if status is not TransferLeaseStatus.RELEASED
        ),
        started_lease_ids=tuple(
            lease_id
            for lease_id, status in sorted(statuses.items())
            if status is TransferLeaseStatus.STARTED
        ),
        released_lease_ids=tuple(
            lease_id
            for lease_id, status in sorted(statuses.items())
            if status is TransferLeaseStatus.RELEASED
        ),
        staging_allocation_states=tuple(sorted(allocation_states.items())),
        calendar_reservations=tuple(
            (resource_id, resource.lanes, resource.reservations())
            for resource_id, resource in sorted(resources.items())
        ),
        lease_snapshots=tuple(
            (lease_id, _canonical_json_text(document))
            for lease_id, document in sorted(lease_documents.items())
        ),
    )


def transfer_resource_calendar_replay_byte_identical(
    journal: EventJournal,
    manager: TransferResourceLeaseManager,
) -> bool:
    """Compare a pristine journal replay with the complete online lease state."""

    pristine = {
        resource_id: ConcurrencyResource(
            resource_id=resource_id,
            lanes=resource.lanes,
        )
        for resource_id, resource in manager.concurrency_resources.items()
    }
    replayed = replay_transfer_resource_calendar(journal, pristine)
    return replayed.snapshot_bytes() == manager.snapshot().snapshot_bytes()


def _validate_replayed_geometry(data: Mapping[str, Any]) -> None:
    payload = _required_integer(data, "payload_bytes")
    requested = _required_integer(data, "requested_bytes")
    allocated = _required_integer(data, "allocated_bytes")
    padding = _required_integer(data, "padding_bytes")
    metadata = _required_integer(data, "allocator_metadata_bytes")
    fragmentation = _required_integer(data, "internal_fragmentation_bytes")
    alignment = _required_integer(data, "alignment_bytes")
    if (
        payload <= 0
        or alignment <= 0
        or any(
            value < 0
            for value in (
                requested,
                allocated,
                padding,
                metadata,
                fragmentation,
            )
        )
        or requested != payload + padding
        or allocated != requested + metadata + fragmentation
        or allocated % alignment
    ):
        raise TransferResourceError("replayed staging geometry is inconsistent")


def _required_mapping(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TransferResourceError(f"{description} must be an object")
    return value


def _required_list(data: Mapping[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise TransferResourceError(f"{key} must be a list")
    return value


def _required_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise TransferResourceError(f"{key} must be a non-empty string")
    return value


def _required_integer(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TransferResourceError(f"{key} must be an integer")
    return value


def _required_string_list(data: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = _required_list(data, key)
    if not all(isinstance(value, str) and value for value in values):
        raise TransferResourceError(f"{key} must contain non-empty strings")
    return tuple(values)


def _required_unique_string_list(
    data: Mapping[str, Any],
    key: str,
) -> tuple[str, ...]:
    values = _required_string_list(data, key)
    if len(values) != len(set(values)):
        raise TransferResourceError(f"{key} must contain unique strings")
    return values


def _required_boolean(data: Mapping[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise TransferResourceError(f"{key} must be a boolean")
    return value
