"""Peer-HBM final-space reservations on physical GPU HBM ledgers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from moonkvsim.aegiskv.kv_directory import AegisKVDirectory
from moonkvsim.aegiskv.types import PathCommitState
from moonkvsim.common.status import KVLocation, ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation import (
    AllocationRole,
    AllocationState,
    PhysicalAllocation,
)
from moonkvsim.simulation.ledger import AccountTransfer, CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction
from moonkvsim.store.replica import Replica

PEER_PENDING_ACCOUNT = "AEGIS_PEER_PENDING"
PEER_COMMITTED_ACCOUNT = "AEGIS_PEER_COMMITTED"


@dataclass(frozen=True, slots=True)
class PeerHBMAllocationQuote:
    resource_id: str
    payload_bytes: int
    requested_bytes: int
    allocated_bytes: int
    allocator_metadata_bytes: int
    internal_fragmentation_bytes: int
    alignment_bytes: int


@dataclass(slots=True)
class PeerHBMTicket:
    operation_id: str
    identity: KVIdentity
    object_id: str
    replica_id: str
    allocation_id: str
    resource_id: str
    created_at_ns: int
    state: PathCommitState = PathCommitState.PENDING


class PeerHBMPool:
    """One policy pool backed by per-GPU physical HBM resources.

    The pool owns reservation mechanics only.  Victims must come from an
    explicit admission plan; there is deliberately no hidden LRU fallback.
    """

    def __init__(
        self,
        *,
        directory: AegisKVDirectory,
        ledgers: Mapping[str, CapacityLedger],
        gpu_id_by_resource: Mapping[str, str],
        allocation_alignment_bytes: int = 256,
        allocator_metadata_bytes: int = 0,
    ) -> None:
        if allocation_alignment_bytes <= 0 or allocator_metadata_bytes < 0:
            raise ValueError("HBM allocator alignment/metadata are invalid")
        if set(ledgers) != set(gpu_id_by_resource):
            raise ValueError("every Peer-HBM ledger requires one physical gpu_id")
        if not ledgers:
            raise ValueError("Peer-HBM pool requires at least one HBM ledger")
        if any(
            ledger.resource_id != resource_id
            or ledger.resource_kind is not CapacityResourceKind.GPU_HBM
            for resource_id, ledger in ledgers.items()
        ):
            raise ValueError("Peer-HBM pool accepts only matching GPU_HBM ledgers")
        if len(set(gpu_id_by_resource.values())) != len(gpu_id_by_resource):
            raise ValueError("Peer-HBM resources must map to distinct physical GPUs")
        self.directory = directory
        self.registry = directory.allocation_registry
        self.journal = directory.master.journal
        self.ledgers = dict(ledgers)
        self.gpu_id_by_resource = dict(gpu_id_by_resource)
        self.allocation_alignment_bytes = allocation_alignment_bytes
        self.allocator_metadata_bytes = allocator_metadata_bytes
        self._tickets: dict[str, PeerHBMTicket] = {}

    def quote(self, *, resource_id: str, payload_bytes: int) -> PeerHBMAllocationQuote:
        if resource_id not in self.ledgers:
            raise KeyError(f"unknown Peer-HBM resource: {resource_id}")
        if payload_bytes <= 0:
            raise ValueError("payload_bytes must be positive")
        charged_before_rounding = payload_bytes + self.allocator_metadata_bytes
        allocated_bytes = _round_up(
            charged_before_rounding,
            self.allocation_alignment_bytes,
        )
        return PeerHBMAllocationQuote(
            resource_id=resource_id,
            payload_bytes=payload_bytes,
            requested_bytes=payload_bytes,
            allocated_bytes=allocated_bytes,
            allocator_metadata_bytes=self.allocator_metadata_bytes,
            internal_fragmentation_bytes=allocated_bytes - charged_before_rounding,
            alignment_bytes=self.allocation_alignment_bytes,
        )

    def reserve(
        self,
        identity: KVIdentity,
        *,
        operation_id: str,
        quote: PeerHBMAllocationQuote,
        victim_allocation_ids: tuple[str, ...] = (),
        timestamp_ns: int,
    ) -> PeerHBMTicket:
        if not operation_id or operation_id in self._tickets:
            raise ValueError("operation_id must be non-empty and unique")
        if quote != self.quote(
            resource_id=quote.resource_id,
            payload_bytes=quote.payload_bytes,
        ):
            raise ValueError("Peer-HBM allocation quote is stale or foreign")
        if quote.payload_bytes <= 0:
            raise ValueError("Peer-HBM payload must be positive")
        if self.gpu_id_by_resource[quote.resource_id] == identity.source_gpu_id:
            raise ValueError("Peer-HBM target must differ from the production GPU")
        if len(set(victim_allocation_ids)) != len(victim_allocation_ids):
            raise ValueError("victim allocation IDs must be unique")
        self._check_timestamp(timestamp_ns)

        object_id = self.directory.directory.register_object(identity)
        allocation_id = f"{operation_id}:peer-allocation"
        replica_id = f"{operation_id}:peer-replica"
        victims = tuple(self._validate_victim(item) for item in victim_allocation_ids)
        deltas = [
            AllocationDelta(
                resource_id=allocation.resource_id,
                account_from=PEER_COMMITTED_ACCOUNT,
                account_to="FREE",
                delta_bytes=allocation.allocated_bytes,
                allocation_id=allocation.allocation_id,
                object_id=allocation.object_id,
                replica_id=allocation.replica_id,
            )
            for allocation, _replica in victims
        ]
        deltas.append(
            AllocationDelta(
                resource_id=quote.resource_id,
                account_from="FREE",
                account_to=PEER_PENDING_ACCOUNT,
                delta_bytes=quote.allocated_bytes,
                allocation_id=allocation_id,
                object_id=object_id,
                replica_id=replica_id,
            )
        )
        self._preflight(deltas)

        revoked: list[str] = []
        for allocation, _replica in victims:
            if self.registry.overlay(allocation.allocation_id).recovery_eligible:
                self.registry.set_recovery_eligible(
                    allocation.allocation_id,
                    False,
                    timestamp_ns=timestamp_ns,
                    event_id=f"{operation_id}:victim-recovery-revoke:{allocation.allocation_id}",
                )
                revoked.append(allocation.allocation_id)
        try:
            ResourceTransaction(
                event_id=(
                    f"{operation_id}:peer-evict-reserve"
                    if victims
                    else f"{operation_id}:peer-reserve"
                ),
                timestamp_ns=timestamp_ns,
                cause=(
                    "AEGIS_PEER_HBM_EVICT_RESERVE"
                    if victims
                    else "AEGIS_PEER_HBM_RESERVE"
                ),
                allocation_deltas=deltas,
            ).commit(self.ledgers, journal=self.journal)
        except Exception:
            for victim_id in revoked:
                self.registry.set_recovery_eligible(
                    victim_id,
                    True,
                    timestamp_ns=timestamp_ns,
                    event_id=f"{operation_id}:victim-recovery-rollback:{victim_id}",
                )
            raise

        for allocation, replica in victims:
            self.directory.remove_all_roles(
                allocation.allocation_id,
                timestamp_ns=timestamp_ns,
                event_id_prefix=f"{operation_id}:victim:{allocation.allocation_id}",
            )
            self.registry.transition(
                allocation.allocation_id,
                AllocationState.RELEASED,
                timestamp_ns=timestamp_ns,
                event_id=f"{operation_id}:victim-release:{allocation.allocation_id}",
            )
            self.directory.directory.update_replica(replica.terminate(ReplicaState.EVICTED))

        physical = PhysicalAllocation(
            allocation_id=allocation_id,
            object_id=object_id,
            replica_id=replica_id,
            resource_id=quote.resource_id,
            owner_account=PEER_PENDING_ACCOUNT,
            payload_bytes=quote.payload_bytes,
            requested_bytes=quote.requested_bytes,
            allocated_bytes=quote.allocated_bytes,
            padding_bytes=quote.requested_bytes - quote.payload_bytes,
            allocator_metadata_bytes=quote.allocator_metadata_bytes,
            internal_fragmentation_bytes=quote.internal_fragmentation_bytes,
            alignment_bytes=quote.alignment_bytes,
            state=AllocationState.PENDING,
            created_at_ns=timestamp_ns,
            roles=frozenset(
                {AllocationRole.CACHE_REUSE, AllocationRole.FAILURE_PROTECTION}
            ),
        )
        self.registry.add(
            physical,
            timestamp_ns=timestamp_ns,
            event_id=f"{operation_id}:peer-allocation-add",
        )
        replica = Replica(
            replica_id=replica_id,
            object_id=object_id,
            location=KVLocation.PEER_HBM,
            allocation_ids=(allocation_id,),
            expected_shard_ids=(identity.shard_id,),
            completed_shard_ids=frozenset(),
            state=ReplicaState.ALLOCATED,
            generation=0,
            route_version=identity.route_version,
            created_at_ns=timestamp_ns,
        ).start_pending()
        self.directory.directory.add_replica(replica)
        ticket = PeerHBMTicket(
            operation_id=operation_id,
            identity=identity,
            object_id=object_id,
            replica_id=replica_id,
            allocation_id=allocation_id,
            resource_id=quote.resource_id,
            created_at_ns=timestamp_ns,
        )
        self._tickets[operation_id] = ticket
        return ticket

    def commit(self, ticket: PeerHBMTicket, *, timestamp_ns: int) -> Replica:
        self._require_pending(ticket)
        allocation = self.registry.get(ticket.allocation_id)
        ResourceTransaction(
            event_id=f"{ticket.operation_id}:peer-commit",
            timestamp_ns=timestamp_ns,
            cause="AEGIS_PEER_HBM_COMMIT",
            allocation_deltas=[
                AllocationDelta(
                    resource_id=ticket.resource_id,
                    account_from=PEER_PENDING_ACCOUNT,
                    account_to=PEER_COMMITTED_ACCOUNT,
                    delta_bytes=allocation.allocated_bytes,
                    allocation_id=ticket.allocation_id,
                    object_id=ticket.object_id,
                    replica_id=ticket.replica_id,
                )
            ],
        ).commit(self.ledgers, journal=self.journal)
        self.registry.reaccount(
            ticket.allocation_id,
            PEER_COMMITTED_ACCOUNT,
            timestamp_ns=timestamp_ns,
            event_id=f"{ticket.operation_id}:peer-reaccount",
        )
        self.registry.transition(
            ticket.allocation_id,
            AllocationState.COMMITTED,
            timestamp_ns=timestamp_ns,
            event_id=f"{ticket.operation_id}:peer-allocation-commit",
        )
        pending = self.directory.directory.get_replica(ticket.replica_id)
        published = (
            pending.complete_shard(ticket.identity.shard_id)
            .commit()
            .publish(timestamp_ns=timestamp_ns)
        )
        self.directory.directory.update_replica(published)
        self.registry.set_recovery_eligible(
            ticket.allocation_id,
            True,
            timestamp_ns=timestamp_ns,
            event_id=f"{ticket.operation_id}:peer-recovery-eligible",
        )
        ticket.state = PathCommitState.COMMITTED
        return published

    def abort(
        self,
        ticket: PeerHBMTicket,
        *,
        timestamp_ns: int,
        reason: str,
    ) -> None:
        self._require_pending(ticket)
        if not reason:
            raise ValueError("abort reason must be non-empty")
        allocation = self.registry.get(ticket.allocation_id)
        ResourceTransaction(
            event_id=f"{ticket.operation_id}:peer-abort",
            timestamp_ns=timestamp_ns,
            cause=f"AEGIS_PEER_HBM_ABORT:{reason}",
            allocation_deltas=[
                AllocationDelta(
                    resource_id=ticket.resource_id,
                    account_from=PEER_PENDING_ACCOUNT,
                    account_to="FREE",
                    delta_bytes=allocation.allocated_bytes,
                    allocation_id=ticket.allocation_id,
                    object_id=ticket.object_id,
                    replica_id=ticket.replica_id,
                )
            ],
        ).commit(self.ledgers, journal=self.journal)
        self.directory.remove_all_roles(
            ticket.allocation_id,
            timestamp_ns=timestamp_ns,
            event_id_prefix=f"{ticket.operation_id}:peer-abort",
        )
        self.registry.transition(
            ticket.allocation_id,
            AllocationState.RELEASED,
            timestamp_ns=timestamp_ns,
            event_id=f"{ticket.operation_id}:peer-allocation-abort",
        )
        replica = self.directory.directory.get_replica(ticket.replica_id)
        self.directory.directory.update_replica(replica.terminate(ReplicaState.ABORTED))
        ticket.state = PathCommitState.ABORTED

    def audit(self) -> None:
        self.directory.assert_shared_truth()
        self.registry.audit_resources(self.ledgers)
        for ticket in self._tickets.values():
            allocation = self.registry.get(ticket.allocation_id)
            replica = self.directory.directory.get_replica(ticket.replica_id)
            if allocation.resource_id != ticket.resource_id:
                raise RuntimeError("Peer-HBM ticket changed physical resource")
            if replica.location is not KVLocation.PEER_HBM:
                raise RuntimeError("Peer-HBM ticket points to a non-peer replica")
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
                raise RuntimeError("Peer-HBM ticket lifecycle diverged from shared truth")

    def _validate_victim(self, allocation_id: str) -> tuple[PhysicalAllocation, Replica]:
        allocation = self.registry.get(allocation_id)
        replica = self.directory.directory.get_replica_for_allocation(allocation_id)
        overlay = self.registry.overlay(allocation_id)
        if (
            allocation.resource_id not in self.ledgers
            or allocation.owner_account != PEER_COMMITTED_ACCOUNT
            or allocation.state is not AllocationState.COMMITTED
            or replica.location is not KVLocation.PEER_HBM
            or replica.state is not ReplicaState.COMMITTED
            or not replica.visible
            or replica.allocation_ids != (allocation_id,)
            or overlay.source_pin_count != 0
        ):
            raise ValueError(f"unsafe explicit Peer-HBM victim: {allocation_id}")
        return allocation, replica

    def _preflight(self, deltas: list[AllocationDelta]) -> None:
        grouped: dict[str, list[AccountTransfer]] = defaultdict(list)
        for delta in deltas:
            if delta.resource_id not in self.ledgers:
                raise KeyError(f"unknown Peer-HBM ledger: {delta.resource_id}")
            grouped[delta.resource_id].append(delta.as_transfer())
        for resource_id, transfers in grouped.items():
            self.ledgers[resource_id].preview(transfers)

    def _check_timestamp(self, timestamp_ns: int) -> None:
        if timestamp_ns < 0:
            raise ValueError("timestamp_ns must be non-negative")
        last_timestamp_ns = self.journal.last_timestamp_ns
        if last_timestamp_ns is not None and timestamp_ns < last_timestamp_ns:
            raise ValueError("Peer-HBM operation would move the journal backwards")

    def _require_pending(self, ticket: PeerHBMTicket) -> None:
        if self._tickets.get(ticket.operation_id) is not ticket:
            raise ValueError("foreign Peer-HBM ticket")
        if ticket.state is not PathCommitState.PENDING:
            raise ValueError("Peer-HBM ticket is already terminal")


def _round_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment
