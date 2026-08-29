"""Vanilla Mooncake-style Master metadata and DRAM allocation protocol."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from moonkvsim.common.status import KVLocation, ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation import AllocationState, PhysicalAllocation
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import FREE_ACCOUNT, CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction
from moonkvsim.store.allocation_strategy import RandomAllocationStrategy, ReplicaPlacement
from moonkvsim.store.eviction import LRUEvictionStrategy
from moonkvsim.store.metadata_store import GlobalKVDirectory
from moonkvsim.store.replica import Replica
from moonkvsim.store.segment import Buffer, Segment

STORE_PENDING_ACCOUNT = "PENDING_REPLICA"
STORE_COMMITTED_ACCOUNT = "COMMITTED_REPLICA"
CAPACITY_PRESSURE_EVICTION_FIDELITY_GAP = (
    "pinned_f161118_put_start_returns_NO_AVAILABLE_HANDLE_and_only_signals_an_"
    "asynchronous_lease_aware_batch_eviction_thread;_MoonKVSim_runs_one_"
    "deterministic_LRU_pressure_pass_and_retry_inside_the_same_DES_control_event"
)


class PutState(StrEnum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


@dataclass(slots=True)
class PutTicket:
    put_id: str
    object_id: str
    identity: KVIdentity
    replica_ids: tuple[str, ...]
    allocation_ids: tuple[str, ...]
    created_at_ns: int
    state: PutState = PutState.PENDING


@dataclass(frozen=True, slots=True)
class _PlacementRecord:
    segment_id: str
    buffer: Buffer
    replica_id: str


@dataclass(frozen=True, slots=True)
class _EvictionVictim:
    replica: Replica
    allocations: tuple[PhysicalAllocation, ...]
    placements: tuple[_PlacementRecord, ...]


@dataclass(frozen=True, slots=True)
class _CapacityPressureAttempt:
    placements: tuple[_PlacementRecord, ...]
    victims: tuple[_EvictionVictim, ...]
    inspected_object_ids: tuple[str, ...]
    skipped_object_ids: tuple[str, ...]


class MasterService:
    """Metadata plane for PutStart/PutEnd/GetReplicaList/Remove.

    The Master selects and charges Store DRAM extents but never schedules or
    accounts a byte-transfer path. StoreClient/TransferEngine own that plane.
    """

    def __init__(
        self,
        *,
        allocation_strategy: RandomAllocationStrategy,
        journal: EventJournal | None = None,
        allocation_registry: AllocationRegistry | None = None,
        eviction_strategy: LRUEvictionStrategy | None = None,
    ) -> None:
        if journal is None:
            if allocation_registry is None:
                journal = EventJournal()
            elif allocation_registry.journal is None:
                raise ValueError("an injected allocation registry must expose its EventJournal")
            else:
                journal = allocation_registry.journal
        if allocation_registry is not None and allocation_registry.journal is not journal:
            raise ValueError("Master and injected allocation registry must share one EventJournal")
        self.journal = journal
        self.directory = GlobalKVDirectory()
        self.allocation_registry = (
            allocation_registry
            if allocation_registry is not None
            else AllocationRegistry(journal=self.journal)
        )
        self.allocation_strategy = allocation_strategy
        self.eviction_strategy = (
            eviction_strategy if eviction_strategy is not None else LRUEvictionStrategy()
        )
        self.segments: dict[str, Segment] = {}
        self.ledgers: dict[str, CapacityLedger] = {}
        self.clients: set[str] = set()
        self._tickets: dict[str, PutTicket] = {}
        self._placements: dict[str, _PlacementRecord] = {}

    def register_client(self, client_id: str, *, timestamp_ns: int) -> None:
        if not client_id or client_id in self.clients:
            raise ValueError("client_id must be non-empty and unique")
        self.clients.add(client_id)
        self.journal.append(
            timestamp_ns,
            "MASTER_CLIENT_REGISTERED",
            {"client_id": client_id},
        )

    def mount_segment(
        self,
        segment: Segment,
        ledger: CapacityLedger,
        *,
        timestamp_ns: int,
    ) -> None:
        if segment.segment_id in self.segments:
            raise ValueError(f"duplicate segment: {segment.segment_id}")
        if ledger.resource_id != segment.segment_id:
            raise ValueError("segment and ledger resource IDs must match")
        if ledger.resource_kind is not CapacityResourceKind.STORE_DRAM:
            raise ValueError("Store segment requires a STORE_DRAM ledger")
        if ledger.capacity_bytes != segment.capacity_bytes:
            raise ValueError("segment and ledger capacities must match")
        segment.mount()
        self.segments[segment.segment_id] = segment
        self.ledgers[ledger.resource_id] = ledger
        self.journal.append(
            timestamp_ns,
            "MASTER_SEGMENT_MOUNTED",
            {
                "segment_id": segment.segment_id,
                "capacity_bytes": segment.capacity_bytes,
            },
        )

    def put_start(
        self,
        identity: KVIdentity,
        *,
        put_id: str,
        payload_bytes: int,
        replica_count: int,
        timestamp_ns: int,
        preferred_segment_ids: tuple[str, ...] = (),
        excluded_segment_ids: tuple[str, ...] = (),
    ) -> PutTicket:
        if not put_id or put_id in self._tickets:
            raise ValueError("put_id must be non-empty and unique")
        if payload_bytes <= 0 or replica_count <= 0:
            raise ValueError("payload bytes and replica count must be positive")
        object_id = self.directory.register_object(identity)
        allocation_checkpoint = self.allocation_strategy.checkpoint()
        try:
            placements = self.allocation_strategy.allocate(
                self.segments.values(),
                slice_id=put_id,
                slice_length_bytes=payload_bytes,
                replica_count=replica_count,
                preferred_segment_ids=preferred_segment_ids,
                excluded_segment_ids=excluded_segment_ids,
            )
            if placements:
                attempt = _CapacityPressureAttempt(
                    placements=self._placement_records(put_id, placements),
                    victims=(),
                    inspected_object_ids=(),
                    skipped_object_ids=(),
                )
            else:
                attempt = self._allocate_after_capacity_pressure(
                    put_id=put_id,
                    payload_bytes=payload_bytes,
                    replica_count=replica_count,
                    preferred_segment_ids=preferred_segment_ids,
                    excluded_segment_ids=excluded_segment_ids,
                )
        except Exception:
            self.allocation_strategy.restore(allocation_checkpoint)
            raise
        if not attempt.placements:
            self.allocation_strategy.restore(allocation_checkpoint)
            self._append_capacity_pressure_result(
                put_id=put_id,
                timestamp_ns=timestamp_ns,
                attempt=attempt,
                outcome="NO_AVAILABLE_HANDLE",
            )
            raise RuntimeError("NO_AVAILABLE_HANDLE: no Store DRAM replica allocated")

        records = attempt.placements
        eviction_deltas = [
            AllocationDelta(
                resource_id=allocation.resource_id,
                account_from=STORE_COMMITTED_ACCOUNT,
                account_to=FREE_ACCOUNT,
                delta_bytes=allocation.allocated_bytes,
                allocation_id=allocation.allocation_id,
                object_id=allocation.object_id,
                replica_id=allocation.replica_id,
            )
            for victim in attempt.victims
            for allocation in victim.allocations
        ]
        transaction = ResourceTransaction(
            event_id=(f"{put_id}:evict-reserve" if attempt.victims else f"{put_id}:reserve"),
            timestamp_ns=timestamp_ns,
            cause=(
                "MOONCAKE_PUT_START_CAPACITY_PRESSURE_REPLACEMENT"
                if attempt.victims
                else "MOONCAKE_PUT_START"
            ),
            allocation_deltas=[
                *eviction_deltas,
                *[
                    AllocationDelta(
                        resource_id=record.segment_id,
                        account_from=FREE_ACCOUNT,
                        account_to=STORE_PENDING_ACCOUNT,
                        delta_bytes=record.buffer.allocated_bytes,
                        allocation_id=record.buffer.buffer_id,
                        object_id=object_id,
                        replica_id=record.replica_id,
                    )
                    for record in records
                ],
            ],
        )
        try:
            transaction.commit(self.ledgers, journal=self.journal)
        except Exception:
            self._rollback_capacity_pressure_geometry(records, attempt.victims)
            self.allocation_strategy.restore(allocation_checkpoint)
            if attempt.victims:
                self._append_capacity_pressure_result(
                    put_id=put_id,
                    timestamp_ns=timestamp_ns,
                    attempt=attempt,
                    outcome="TRANSACTION_ROLLED_BACK",
                )
            raise

        self._commit_eviction_victims(
            attempt.victims,
            put_id=put_id,
            timestamp_ns=timestamp_ns,
        )

        for record in records:
            physical = PhysicalAllocation(
                allocation_id=record.buffer.buffer_id,
                object_id=object_id,
                replica_id=record.replica_id,
                resource_id=record.segment_id,
                owner_account=STORE_PENDING_ACCOUNT,
                payload_bytes=payload_bytes,
                requested_bytes=payload_bytes,
                allocated_bytes=record.buffer.allocated_bytes,
                padding_bytes=0,
                allocator_metadata_bytes=record.buffer.allocator_metadata_bytes,
                internal_fragmentation_bytes=record.buffer.internal_fragmentation_bytes,
                alignment_bytes=record.buffer.alignment_bytes,
                state=AllocationState.PENDING,
                created_at_ns=timestamp_ns,
            )
            self.allocation_registry.add(
                physical,
                timestamp_ns=timestamp_ns,
                event_id=f"{put_id}:allocation-add:{record.replica_id}",
            )
            replica = Replica(
                replica_id=record.replica_id,
                object_id=object_id,
                location=KVLocation.STORE_DRAM,
                allocation_ids=(record.buffer.buffer_id,),
                expected_shard_ids=(identity.shard_id,),
                completed_shard_ids=frozenset(),
                state=ReplicaState.ALLOCATED,
                generation=0,
                route_version=identity.route_version,
                created_at_ns=timestamp_ns,
            ).start_pending()
            self.directory.add_replica(replica)
            self._placements[record.buffer.buffer_id] = record

        ticket = PutTicket(
            put_id=put_id,
            object_id=object_id,
            identity=identity,
            replica_ids=tuple(record.replica_id for record in records),
            allocation_ids=tuple(record.buffer.buffer_id for record in records),
            created_at_ns=timestamp_ns,
        )
        self._tickets[put_id] = ticket
        if attempt.victims:
            self._append_capacity_pressure_result(
                put_id=put_id,
                timestamp_ns=timestamp_ns,
                attempt=attempt,
                outcome="EVICTED_AND_RESERVED",
            )
        return ticket

    def put_end(
        self,
        put_id: str,
        *,
        successful_replica_ids: tuple[str, ...],
        timestamp_ns: int,
    ) -> tuple[Replica, ...]:
        ticket = self._require_pending_ticket(put_id)
        successful = set(successful_replica_ids)
        if not successful or successful - set(ticket.replica_ids):
            raise ValueError("successful replicas must be a non-empty subset of the ticket")
        replicas = [self.directory.get_replica(replica_id) for replica_id in ticket.replica_ids]
        if any(replica.state is not ReplicaState.PENDING for replica in replicas):
            raise RuntimeError("PutEnd requires every ticket replica to remain pending")

        deltas: list[AllocationDelta] = []
        for replica in replicas:
            allocation = self.allocation_registry.get(replica.allocation_ids[0])
            target = STORE_COMMITTED_ACCOUNT if replica.replica_id in successful else FREE_ACCOUNT
            deltas.append(
                AllocationDelta(
                    resource_id=allocation.resource_id,
                    account_from=STORE_PENDING_ACCOUNT,
                    account_to=target,
                    delta_bytes=allocation.allocated_bytes,
                    allocation_id=allocation.allocation_id,
                    object_id=allocation.object_id,
                    replica_id=allocation.replica_id,
                )
            )
        ResourceTransaction(
            event_id=f"{put_id}:finalize",
            timestamp_ns=timestamp_ns,
            cause="MOONCAKE_PUT_END",
            allocation_deltas=deltas,
        ).commit(self.ledgers, journal=self.journal)

        committed: list[Replica] = []
        for replica in replicas:
            allocation_id = replica.allocation_ids[0]
            if replica.replica_id in successful:
                allocation = self.allocation_registry.get(allocation_id)
                self.allocation_registry.reaccount(
                    allocation_id,
                    STORE_COMMITTED_ACCOUNT,
                    timestamp_ns=timestamp_ns,
                    event_id=f"{put_id}:allocation-reaccount:{replica.replica_id}",
                )
                self.allocation_registry.transition(
                    allocation_id,
                    AllocationState.COMMITTED,
                    timestamp_ns=timestamp_ns,
                    event_id=f"{put_id}:allocation-commit:{replica.replica_id}",
                )
                published = (
                    replica.complete_shard(ticket.identity.shard_id)
                    .commit()
                    .publish(timestamp_ns=timestamp_ns)
                )
                self.directory.update_replica(published)
                committed.append(published)
                if allocation.allocated_bytes <= 0:
                    raise RuntimeError("committed allocation has no physical bytes")
            else:
                self.allocation_registry.transition(
                    allocation_id,
                    AllocationState.RELEASED,
                    timestamp_ns=timestamp_ns,
                    event_id=f"{put_id}:allocation-abort:{replica.replica_id}",
                )
                self.directory.update_replica(replica.terminate(ReplicaState.ABORTED))
                placement = self._placements[allocation_id]
                self.segments[placement.segment_id].deallocate(allocation_id)
        ticket.state = PutState.COMMITTED
        self.eviction_strategy.add_key(ticket.object_id)
        self.journal.append(
            timestamp_ns,
            "MASTER_EVICTION_KEY_ADDED",
            {
                "object_id": ticket.object_id,
                "put_id": put_id,
                "policy": "deterministic_lru_capacity_pressure_replacement",
            },
        )
        return tuple(committed)

    def abort_put(self, put_id: str, *, timestamp_ns: int, reason: str) -> None:
        if not reason:
            raise ValueError("abort reason must be non-empty")
        ticket = self._require_pending_ticket(put_id)
        deltas: list[AllocationDelta] = []
        for allocation_id in ticket.allocation_ids:
            allocation = self.allocation_registry.get(allocation_id)
            deltas.append(
                AllocationDelta(
                    resource_id=allocation.resource_id,
                    account_from=STORE_PENDING_ACCOUNT,
                    account_to=FREE_ACCOUNT,
                    delta_bytes=allocation.allocated_bytes,
                    allocation_id=allocation_id,
                    object_id=allocation.object_id,
                    replica_id=allocation.replica_id,
                )
            )
        ResourceTransaction(
            event_id=f"{put_id}:abort",
            timestamp_ns=timestamp_ns,
            cause=f"MOONCAKE_PUT_ABORT:{reason}",
            allocation_deltas=deltas,
        ).commit(self.ledgers, journal=self.journal)
        for replica_id, allocation_id in zip(
            ticket.replica_ids, ticket.allocation_ids, strict=True
        ):
            replica = self.directory.get_replica(replica_id)
            self.directory.update_replica(replica.terminate(ReplicaState.ABORTED))
            self.allocation_registry.transition(
                allocation_id,
                AllocationState.RELEASED,
                timestamp_ns=timestamp_ns,
                event_id=f"{put_id}:allocation-abort:{replica_id}",
            )
            placement = self._placements[allocation_id]
            self.segments[placement.segment_id].deallocate(allocation_id)
        ticket.state = PutState.ABORTED

    def get_replica_list(self, identity: KVIdentity) -> tuple[Replica, ...]:
        return self.directory.query(identity)

    def record_committed_access(self, identity: KVIdentity, *, timestamp_ns: int) -> None:
        """Move a visible object to the MRU frontier after a real GET starts."""

        if not self.directory.query(identity):
            raise ValueError("only a visible committed Store object may be touched")
        self.eviction_strategy.update_key(identity.object_id)
        self.journal.append(
            timestamp_ns,
            "MASTER_EVICTION_KEY_TOUCHED",
            {
                "object_id": identity.object_id,
                "policy": "deterministic_lru_capacity_pressure_replacement",
            },
        )

    def remove(self, identity: KVIdentity, *, timestamp_ns: int) -> int:
        replicas = self.directory.query(identity)
        if not replicas:
            return 0
        deltas: list[AllocationDelta] = []
        for replica in replicas:
            for allocation_id in replica.allocation_ids:
                allocation = self.allocation_registry.get(allocation_id)
                if allocation.state is not AllocationState.COMMITTED:
                    raise RuntimeError("visible replica allocation is not committed")
                if self.allocation_registry.overlay(allocation_id).source_pin_count:
                    raise RuntimeError(
                        "OBJECT_BUSY: committed Store allocation has a live source pin"
                    )
                deltas.append(
                    AllocationDelta(
                        resource_id=allocation.resource_id,
                        account_from=STORE_COMMITTED_ACCOUNT,
                        account_to=FREE_ACCOUNT,
                        delta_bytes=allocation.allocated_bytes,
                        allocation_id=allocation_id,
                        object_id=allocation.object_id,
                        replica_id=allocation.replica_id,
                    )
                )
        ResourceTransaction(
            event_id=f"remove:{identity.object_id}:{timestamp_ns}",
            timestamp_ns=timestamp_ns,
            cause="MOONCAKE_REMOVE",
            allocation_deltas=deltas,
        ).commit(self.ledgers, journal=self.journal)
        for replica in replicas:
            for allocation_id in replica.allocation_ids:
                overlay = self.allocation_registry.overlay(allocation_id)
                if overlay.recovery_eligible:
                    self.allocation_registry.set_recovery_eligible(
                        allocation_id,
                        False,
                        timestamp_ns=timestamp_ns,
                        event_id=f"remove:{replica.replica_id}:revoke-recovery:{allocation_id}",
                    )
                for role in sorted(
                    self.allocation_registry.get(allocation_id).roles,
                    key=lambda item: item.value,
                ):
                    self.allocation_registry.remove_role(
                        allocation_id,
                        role,
                        timestamp_ns=timestamp_ns,
                        event_id=(
                            f"remove:{replica.replica_id}:remove-role:{allocation_id}:{role.value}"
                        ),
                    )
                self.allocation_registry.transition(
                    allocation_id,
                    AllocationState.RELEASED,
                    timestamp_ns=timestamp_ns,
                    event_id=f"remove:{replica.replica_id}:{allocation_id}",
                )
                placement = self._placements[allocation_id]
                self.segments[placement.segment_id].deallocate(allocation_id)
            self.directory.update_replica(replica.terminate(ReplicaState.REMOVED))
        self.eviction_strategy.remove_key(identity.object_id)
        return len(replicas)

    @staticmethod
    def _placement_records(
        put_id: str,
        placements: tuple[ReplicaPlacement, ...],
    ) -> tuple[_PlacementRecord, ...]:
        return tuple(
            _PlacementRecord(
                segment_id=placement.segment_id,
                buffer=placement.buffer,
                replica_id=f"{put_id}:replica-{placement.replica_index}",
            )
            for placement in placements
        )

    def _allocate_after_capacity_pressure(
        self,
        *,
        put_id: str,
        payload_bytes: int,
        replica_count: int,
        preferred_segment_ids: tuple[str, ...],
        excluded_segment_ids: tuple[str, ...],
    ) -> _CapacityPressureAttempt:
        """Tentatively free legal LRU victims, then retry best-effort placement.

        The pinned service performs this work asynchronously and does not retry
        the failing PutStart.  MoonKVSim keeps the replacement synchronous so
        one DES event has an atomic before/after state.  The journal exposes
        that fidelity boundary on every pressure attempt.
        """

        allowed_segments = frozenset(
            segment_id
            for segment_id, segment in self.segments.items()
            if segment.status.accepts_allocations and segment_id not in excluded_segment_ids
        )
        victims: list[_EvictionVictim] = []
        inspected: list[str] = []
        skipped: list[str] = []
        try:
            for object_id in self.eviction_strategy.keys_lru_to_mru:
                inspected.append(object_id)
                candidate_victims = self._evictable_victims(
                    object_id,
                    allowed_segment_ids=allowed_segments,
                )
                if not candidate_victims:
                    skipped.append(object_id)
                    continue
                for victim in candidate_victims:
                    for placement in victim.placements:
                        removed = self.segments[placement.segment_id].deallocate(
                            placement.buffer.buffer_id
                        )
                        if removed != placement.buffer:
                            raise RuntimeError("eviction removed unexpected segment geometry")
                victims.extend(candidate_victims)
                placements = self.allocation_strategy.allocate(
                    self.segments.values(),
                    slice_id=put_id,
                    slice_length_bytes=payload_bytes,
                    replica_count=replica_count,
                    preferred_segment_ids=preferred_segment_ids,
                    excluded_segment_ids=excluded_segment_ids,
                )
                if placements:
                    return _CapacityPressureAttempt(
                        placements=self._placement_records(put_id, placements),
                        victims=tuple(victims),
                        inspected_object_ids=tuple(inspected),
                        skipped_object_ids=tuple(skipped),
                    )
        except Exception:
            self._rollback_capacity_pressure_geometry((), tuple(victims))
            raise

        self._rollback_capacity_pressure_geometry((), tuple(victims))
        return _CapacityPressureAttempt(
            placements=(),
            victims=tuple(victims),
            inspected_object_ids=tuple(inspected),
            skipped_object_ids=tuple(skipped),
        )

    def _evictable_victims(
        self,
        object_id: str,
        *,
        allowed_segment_ids: frozenset[str],
    ) -> tuple[_EvictionVictim, ...]:
        replicas = self.directory.replicas_for_object(object_id)
        if any(
            replica.state in {ReplicaState.ALLOCATED, ReplicaState.PENDING} for replica in replicas
        ):
            return ()

        victims: list[_EvictionVictim] = []
        for replica in replicas:
            if replica.state is not ReplicaState.COMMITTED or not replica.visible:
                continue
            allocations: list[PhysicalAllocation] = []
            placements: list[_PlacementRecord] = []
            eligible = True
            for allocation_id in replica.allocation_ids:
                allocation = self.allocation_registry.get(allocation_id)
                overlay = self.allocation_registry.overlay(allocation_id)
                placement = self._placements.get(allocation_id)
                if (
                    allocation.state is not AllocationState.COMMITTED
                    or allocation.owner_account != STORE_COMMITTED_ACCOUNT
                    or allocation.resource_id not in allowed_segment_ids
                    or overlay.source_pin_count != 0
                    or placement is None
                    or placement.segment_id != allocation.resource_id
                ):
                    eligible = False
                    break
                live_buffers = {
                    buffer.buffer_id for buffer in self.segments[allocation.resource_id].buffers
                }
                if allocation_id not in live_buffers:
                    raise RuntimeError("committed Store allocation has no segment extent")
                allocations.append(allocation)
                placements.append(placement)
            if eligible:
                victims.append(
                    _EvictionVictim(
                        replica=replica,
                        allocations=tuple(allocations),
                        placements=tuple(placements),
                    )
                )
        return tuple(victims)

    def _rollback_capacity_pressure_geometry(
        self,
        new_records: tuple[_PlacementRecord, ...],
        victims: tuple[_EvictionVictim, ...],
    ) -> None:
        for record in reversed(new_records):
            live_ids = {buffer.buffer_id for buffer in self.segments[record.segment_id].buffers}
            if record.buffer.buffer_id in live_ids:
                self.segments[record.segment_id].deallocate(record.buffer.buffer_id)
        victim_placements = sorted(
            (placement for victim in victims for placement in victim.placements),
            key=lambda item: (
                item.segment_id,
                item.buffer.offset_bytes,
                item.buffer.buffer_id,
            ),
        )
        for placement in victim_placements:
            live_ids = {buffer.buffer_id for buffer in self.segments[placement.segment_id].buffers}
            if placement.buffer.buffer_id not in live_ids:
                self.segments[placement.segment_id].restore_deallocated(placement.buffer)

    def _commit_eviction_victims(
        self,
        victims: tuple[_EvictionVictim, ...],
        *,
        put_id: str,
        timestamp_ns: int,
    ) -> None:
        affected_object_ids: set[str] = set()
        for victim in victims:
            for allocation in victim.allocations:
                allocation_id = allocation.allocation_id
                overlay = self.allocation_registry.overlay(allocation_id)
                if overlay.source_pin_count:
                    raise RuntimeError("eviction victim gained a source pin before commit")
                if overlay.recovery_eligible:
                    self.allocation_registry.set_recovery_eligible(
                        allocation_id,
                        False,
                        timestamp_ns=timestamp_ns,
                        event_id=f"{put_id}:eviction-revoke-recovery:{allocation_id}",
                    )
                for role in sorted(
                    self.allocation_registry.get(allocation_id).roles,
                    key=lambda item: item.value,
                ):
                    self.allocation_registry.remove_role(
                        allocation_id,
                        role,
                        timestamp_ns=timestamp_ns,
                        event_id=f"{put_id}:eviction-remove-role:{allocation_id}:{role.value}",
                    )
                self.allocation_registry.transition(
                    allocation_id,
                    AllocationState.RELEASED,
                    timestamp_ns=timestamp_ns,
                    event_id=f"{put_id}:eviction-release:{allocation_id}",
                )
            self.directory.update_replica(victim.replica.terminate(ReplicaState.EVICTED))
            affected_object_ids.add(victim.replica.object_id)
        for object_id in sorted(affected_object_ids):
            if not any(
                replica.visible for replica in self.directory.replicas_for_object(object_id)
            ):
                self.eviction_strategy.remove_key(object_id)

    def _append_capacity_pressure_result(
        self,
        *,
        put_id: str,
        timestamp_ns: int,
        attempt: _CapacityPressureAttempt,
        outcome: str,
    ) -> None:
        self.journal.append(
            timestamp_ns,
            "MASTER_STORE_CAPACITY_PRESSURE",
            {
                "put_id": put_id,
                "outcome": outcome,
                "policy": "deterministic_lru_capacity_pressure_replacement",
                "inspected_object_ids_lru_first": list(attempt.inspected_object_ids),
                "skipped_object_ids": list(attempt.skipped_object_ids),
                "candidate_victim_object_ids": sorted(
                    {victim.replica.object_id for victim in attempt.victims}
                ),
                "candidate_victim_replica_ids": sorted(
                    victim.replica.replica_id for victim in attempt.victims
                ),
                "candidate_victim_allocation_ids": sorted(
                    allocation.allocation_id
                    for victim in attempt.victims
                    for allocation in victim.allocations
                ),
                "candidate_allocated_bytes": sum(
                    allocation.allocated_bytes
                    for victim in attempt.victims
                    for allocation in victim.allocations
                ),
                "committed_freed_allocated_bytes": (
                    sum(
                        allocation.allocated_bytes
                        for victim in attempt.victims
                        for allocation in victim.allocations
                    )
                    if outcome == "EVICTED_AND_RESERVED"
                    else 0
                ),
                "reserved_allocation_ids": [
                    record.buffer.buffer_id for record in attempt.placements
                ],
                "fidelity_gap": CAPACITY_PRESSURE_EVICTION_FIDELITY_GAP,
                "evidence_boundary": "E2_toy_store_capacity_pressure_semantics_only",
            },
        )

    def _require_pending_ticket(self, put_id: str) -> PutTicket:
        try:
            ticket = self._tickets[put_id]
        except KeyError as error:
            raise KeyError(f"unknown put ticket: {put_id}") from error
        if ticket.state is not PutState.PENDING:
            raise ValueError("put ticket is already terminal")
        return ticket
