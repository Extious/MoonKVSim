"""AegisKV DRAM policy pool on the ordinary global Mooncake Store."""

from __future__ import annotations

from dataclasses import dataclass

from moonkvsim.aegiskv.kv_directory import AegisKVDirectory
from moonkvsim.aegiskv.types import PathCommitState
from moonkvsim.common.status import KVLocation, ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation import AllocationRole, AllocationState
from moonkvsim.store.master import MasterService, PutTicket
from moonkvsim.store.replica import Replica
from moonkvsim.store.segment import SegmentStatus


@dataclass(frozen=True, slots=True)
class StoreDRAMAllocationQuote:
    segment_id: str
    payload_bytes: int
    allocated_bytes: int
    allocator_metadata_bytes: int
    internal_fragmentation_bytes: int
    alignment_bytes: int


@dataclass(slots=True)
class StoreDRAMTicket:
    operation_id: str
    identity: KVIdentity
    put_ticket: PutTicket
    segment_id: str
    created_at_ns: int
    state: PathCommitState = PathCommitState.PENDING

    @property
    def object_id(self) -> str:
        return self.put_ticket.object_id

    @property
    def replica_id(self) -> str:
        if len(self.put_ticket.replica_ids) != 1:
            raise RuntimeError("AegisKV Store ticket must contain exactly one replica")
        return self.put_ticket.replica_ids[0]

    @property
    def allocation_id(self) -> str:
        if len(self.put_ticket.allocation_ids) != 1:
            raise RuntimeError("AegisKV Store ticket must contain exactly one allocation")
        return self.put_ticket.allocation_ids[0]


class StoreDRAMPool:
    """Independent DRAM admission using Master PutStart/PutEnd and Store DRAM.

    Every pressure attempt supplies an explicit victim frontier, including an
    empty one.  Therefore the baseline Master's LRU is never a hidden fallback
    for AegisKV.
    """

    def __init__(self, *, directory: AegisKVDirectory) -> None:
        self.directory = directory
        self.master: MasterService = directory.master
        self.registry = directory.allocation_registry
        self._tickets: dict[str, StoreDRAMTicket] = {}

    def quote(self, *, segment_id: str, payload_bytes: int) -> StoreDRAMAllocationQuote:
        try:
            segment = self.master.segments[segment_id]
        except KeyError as error:
            raise KeyError(f"unknown global Store DRAM segment: {segment_id}") from error
        if segment.status is not SegmentStatus.OK:
            raise ValueError("Store DRAM quote requires an allocation-accepting segment")
        if payload_bytes <= 0:
            raise ValueError("payload_bytes must be positive")
        charged_before_rounding = payload_bytes + segment.allocator_metadata_bytes
        allocated_bytes = _round_up(
            charged_before_rounding,
            segment.allocation_alignment_bytes,
        )
        return StoreDRAMAllocationQuote(
            segment_id=segment_id,
            payload_bytes=payload_bytes,
            allocated_bytes=allocated_bytes,
            allocator_metadata_bytes=segment.allocator_metadata_bytes,
            internal_fragmentation_bytes=allocated_bytes - charged_before_rounding,
            alignment_bytes=segment.allocation_alignment_bytes,
        )

    def reserve(
        self,
        identity: KVIdentity,
        *,
        operation_id: str,
        quote: StoreDRAMAllocationQuote,
        victim_allocation_ids: tuple[str, ...] = (),
        timestamp_ns: int,
    ) -> StoreDRAMTicket:
        if not operation_id or operation_id in self._tickets:
            raise ValueError("operation_id must be non-empty and unique")
        if quote != self.quote(segment_id=quote.segment_id, payload_bytes=quote.payload_bytes):
            raise ValueError("Store DRAM allocation quote is stale or foreign")
        victim_object_ids = self._explicit_victim_objects(victim_allocation_ids)
        excluded = tuple(sorted(set(self.master.segments) - {quote.segment_id}))
        put_ticket = self.master.put_start(
            identity,
            put_id=f"{operation_id}:store-put",
            payload_bytes=quote.payload_bytes,
            replica_count=1,
            timestamp_ns=timestamp_ns,
            preferred_segment_ids=(quote.segment_id,),
            excluded_segment_ids=excluded,
            capacity_pressure_candidate_object_ids=victim_object_ids,
            transaction_cause_prefix="AEGIS_STORE_DRAM",
        )
        if len(put_ticket.allocation_ids) != 1:
            self.master.abort_put(
                put_ticket.put_id,
                timestamp_ns=timestamp_ns,
                reason="AEGIS_NON_SINGLETON_STORE_RESERVATION",
            )
            raise RuntimeError("AegisKV Store reservation must allocate one final extent")
        allocation = self.registry.get(put_ticket.allocation_ids[0])
        if (
            allocation.resource_id != quote.segment_id
            or allocation.allocated_bytes != quote.allocated_bytes
        ):
            self.master.abort_put(
                put_ticket.put_id,
                timestamp_ns=timestamp_ns,
                reason="AEGIS_STORE_QUOTE_DIVERGED",
            )
            raise RuntimeError("Master allocation diverged from the Store DRAM quote")
        try:
            self.directory.add_roles(
                allocation.allocation_id,
                (AllocationRole.CACHE_REUSE, AllocationRole.FAILURE_PROTECTION),
                timestamp_ns=timestamp_ns,
                event_id_prefix=f"{operation_id}:store",
            )
        except Exception:
            self.master.abort_put(
                put_ticket.put_id,
                timestamp_ns=timestamp_ns,
                reason="AEGIS_ROLE_BIND_FAILED",
            )
            raise
        ticket = StoreDRAMTicket(
            operation_id=operation_id,
            identity=identity,
            put_ticket=put_ticket,
            segment_id=quote.segment_id,
            created_at_ns=timestamp_ns,
        )
        self._tickets[operation_id] = ticket
        return ticket

    def commit(self, ticket: StoreDRAMTicket, *, timestamp_ns: int) -> Replica:
        self._require_pending(ticket)
        committed = self.master.put_end(
            ticket.put_ticket.put_id,
            successful_replica_ids=ticket.put_ticket.replica_ids,
            timestamp_ns=timestamp_ns,
        )
        if len(committed) != 1:
            raise RuntimeError("AegisKV Store commit did not publish exactly one replica")
        self.registry.set_recovery_eligible(
            ticket.allocation_id,
            True,
            timestamp_ns=timestamp_ns,
            event_id=f"{ticket.operation_id}:store-recovery-eligible",
        )
        ticket.state = PathCommitState.COMMITTED
        return committed[0]

    def abort(
        self,
        ticket: StoreDRAMTicket,
        *,
        timestamp_ns: int,
        reason: str,
    ) -> None:
        self._require_pending(ticket)
        self.master.abort_put(
            ticket.put_ticket.put_id,
            timestamp_ns=timestamp_ns,
            reason=f"AEGIS_STORE_PATH:{reason}",
        )
        self.directory.remove_all_roles(
            ticket.allocation_id,
            timestamp_ns=timestamp_ns,
            event_id_prefix=f"{ticket.operation_id}:store-abort",
        )
        ticket.state = PathCommitState.ABORTED

    def audit(self) -> None:
        self.directory.assert_shared_truth()
        self.registry.audit_resources(self.master.ledgers)
        for ticket in self._tickets.values():
            allocation = self.registry.get(ticket.allocation_id)
            replica = self.master.directory.get_replica(ticket.replica_id)
            if allocation.resource_id != ticket.segment_id:
                raise RuntimeError("Store DRAM ticket changed physical segment")
            if replica.location is not KVLocation.STORE_DRAM:
                raise RuntimeError("Store DRAM ticket points to a non-Store replica")
            live_or_historical = {
                PathCommitState.PENDING: {
                    (AllocationState.PENDING, ReplicaState.PENDING),
                },
                PathCommitState.COMMITTED: {
                    (AllocationState.COMMITTED, ReplicaState.COMMITTED),
                    (AllocationState.RELEASED, ReplicaState.EVICTED),
                    (AllocationState.RELEASED, ReplicaState.REMOVED),
                },
                PathCommitState.ABORTED: {
                    (AllocationState.RELEASED, ReplicaState.ABORTED),
                },
            }[ticket.state]
            if (allocation.state, replica.state) not in live_or_historical:
                raise RuntimeError("Store DRAM lifecycle diverged from shared truth")

    def _explicit_victim_objects(
        self,
        victim_allocation_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(set(victim_allocation_ids)) != len(victim_allocation_ids):
            raise ValueError("victim allocation IDs must be unique")
        ordered_objects: list[str] = []
        selected = frozenset(victim_allocation_ids)
        for allocation_id in victim_allocation_ids:
            allocation = self.registry.get(allocation_id)
            replica = self.master.directory.get_replica_for_allocation(allocation_id)
            overlay = self.registry.overlay(allocation_id)
            if (
                allocation.resource_id not in self.master.ledgers
                or allocation.state is not AllocationState.COMMITTED
                or replica.location is not KVLocation.STORE_DRAM
                or replica.state is not ReplicaState.COMMITTED
                or not replica.visible
                or overlay.source_pin_count != 0
            ):
                raise ValueError(f"unsafe explicit Store DRAM victim: {allocation_id}")
            if replica.object_id in ordered_objects:
                continue
            visible_store_allocations = {
                item
                for candidate in self.master.directory.replicas_for_object(replica.object_id)
                if candidate.location is KVLocation.STORE_DRAM and candidate.visible
                for item in candidate.allocation_ids
            }
            if not visible_store_allocations.issubset(selected):
                raise ValueError(
                    "explicit Store victim plan must name every visible allocation of an object"
                )
            ordered_objects.append(replica.object_id)
        return tuple(ordered_objects)

    def _require_pending(self, ticket: StoreDRAMTicket) -> None:
        if self._tickets.get(ticket.operation_id) is not ticket:
            raise ValueError("foreign Store DRAM ticket")
        if ticket.state is not PathCommitState.PENDING:
            raise ValueError("Store DRAM ticket is already terminal")


def _round_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment
