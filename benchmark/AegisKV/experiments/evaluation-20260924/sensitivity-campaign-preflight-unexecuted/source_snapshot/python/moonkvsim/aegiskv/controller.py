"""Independent Peer-HBM and Store-DRAM admission orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from moonkvsim.aegiskv.kv_directory import AegisKVDirectory, ResidencyOutcome
from moonkvsim.aegiskv.peer_hbm_pool import PeerHBMPool, PeerHBMTicket
from moonkvsim.aegiskv.store_dram_pool import StoreDRAMPool, StoreDRAMTicket
from moonkvsim.aegiskv.types import AdmissionOutcome, PolicyPool, SealedChunk
from moonkvsim.common.status import KVLocation, ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation import AllocationRole, AllocationState


@dataclass(frozen=True, slots=True)
class ProductionChunk:
    """A sealed source-production chunk before either policy-pool decision."""

    chunk_id: str
    identity: KVIdentity
    sequence_index: int
    payload_bytes: int
    source_allocation_id: str

    def __post_init__(self) -> None:
        if not self.chunk_id or not self.source_allocation_id:
            raise ValueError("chunk/source allocation IDs must be non-empty")
        if self.sequence_index < 0 or self.payload_bytes <= 0:
            raise ValueError("sequence index and payload bytes are invalid")

    def policy_candidate(self, *, allocated_bytes: int) -> SealedChunk:
        return SealedChunk(
            chunk_id=self.chunk_id,
            request_id=self.identity.request_id,
            sequence_index=self.sequence_index,
            allocated_bytes=allocated_bytes,
        )


@dataclass(frozen=True, slots=True)
class AllocationQuote:
    pool: PolicyPool
    resource_id: str
    payload_bytes: int
    allocated_bytes: int
    allocator_metadata_bytes: int
    internal_fragmentation_bytes: int
    alignment_bytes: int

    def __post_init__(self) -> None:
        if not self.resource_id:
            raise ValueError("allocation quote resource_id must be non-empty")
        if self.payload_bytes <= 0 or self.allocated_bytes < self.payload_bytes:
            raise ValueError("allocation quote byte counts are invalid")
        if self.allocator_metadata_bytes < 0 or self.internal_fragmentation_bytes < 0:
            raise ValueError("allocation quote overheads must be non-negative")
        if self.alignment_bytes <= 0:
            raise ValueError("allocation quote alignment must be positive")
        if self.allocated_bytes != (
            self.payload_bytes
            + self.allocator_metadata_bytes
            + self.internal_fragmentation_bytes
        ):
            raise ValueError("allocation quote must fully explain allocated bytes")


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    outcome: AdmissionOutcome
    plan_id: str
    victim_allocation_ids: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.plan_id or not self.reason:
            raise ValueError("admission plan_id and reason must be non-empty")
        if len(set(self.victim_allocation_ids)) != len(self.victim_allocation_ids):
            raise ValueError("admission victims must be unique")
        if self.outcome is AdmissionOutcome.BYPASS and self.victim_allocation_ids:
            raise ValueError("a bypass plan cannot evict physical allocations")

    @property
    def admitted(self) -> bool:
        return self.outcome is AdmissionOutcome.ADMIT


class AdmissionPolicy(Protocol):
    """Small adapter boundary implemented by SlackLandlord policy owners."""

    def preview(
        self,
        pool: PolicyPool,
        candidate: SealedChunk,
        allocation_quote: AllocationQuote,
        now_ns: int,
    ) -> AdmissionDecision: ...


@dataclass(frozen=True, slots=True)
class PathAdmission:
    pool: PolicyPool
    decision: AdmissionDecision
    peer_ticket: PeerHBMTicket | None = None
    store_ticket: StoreDRAMTicket | None = None
    error: str | None = None

    @property
    def reserved(self) -> bool:
        return self.peer_ticket is not None or self.store_ticket is not None


@dataclass(frozen=True, slots=True)
class IndependentAdmission:
    operation_id: str
    production: ProductionChunk
    peer: PathAdmission
    store: PathAdmission

    @property
    def reserved_outcome(self) -> ResidencyOutcome:
        if self.peer.reserved and self.store.reserved:
            return ResidencyOutcome.HBM_AND_DRAM
        if self.peer.reserved:
            return ResidencyOutcome.HBM_ONLY
        if self.store.reserved:
            return ResidencyOutcome.DRAM_ONLY
        return ResidencyOutcome.BYPASS


class AegisKVController:
    """Evaluate and reserve both policy pools without cross-tier preconditions."""

    def __init__(
        self,
        *,
        directory: AegisKVDirectory,
        peer_pool: PeerHBMPool,
        store_pool: StoreDRAMPool,
        policy: AdmissionPolicy,
    ) -> None:
        if peer_pool.directory is not directory or store_pool.directory is not directory:
            raise ValueError("controller pools must share one AegisKV/Master directory")
        self.directory = directory
        self.peer_pool = peer_pool
        self.store_pool = store_pool
        self.policy = policy

    def reserve_independently(
        self,
        production: ProductionChunk,
        *,
        operation_id: str,
        peer_resource_id: str,
        store_segment_id: str,
        timestamp_ns: int,
    ) -> IndependentAdmission:
        if not operation_id:
            raise ValueError("operation_id must be non-empty")
        source = self.directory.allocation_registry.get(production.source_allocation_id)
        source_replica = self.directory.directory.get_replica_for_allocation(
            production.source_allocation_id
        )
        if (
            source.object_id != production.identity.object_id
            or source.state is not AllocationState.COMMITTED
            or AllocationRole.ACTIVE_PRIMARY not in source.roles
            or source_replica.location is not KVLocation.PRIMARY_HBM
            or source_replica.state is not ReplicaState.COMMITTED
            or not source_replica.visible
        ):
            raise ValueError(
                "production allocation must be the visible committed primary for the sealed KV"
            )

        peer = self._reserve_peer(
            production,
            operation_id=operation_id,
            resource_id=peer_resource_id,
            timestamp_ns=timestamp_ns,
        )
        store = self._reserve_store(
            production,
            operation_id=operation_id,
            segment_id=store_segment_id,
            timestamp_ns=timestamp_ns,
        )
        result = IndependentAdmission(
            operation_id=operation_id,
            production=production,
            peer=peer,
            store=store,
        )
        self.directory.master.journal.append(
            timestamp_ns,
            "AEGIS_INDEPENDENT_ADMISSION",
            {
                "operation_id": operation_id,
                "object_id": production.identity.object_id,
                "peer_decision": peer.decision.outcome.value,
                "peer_reserved": peer.reserved,
                "peer_error": peer.error,
                "store_decision": store.decision.outcome.value,
                "store_reserved": store.reserved,
                "store_error": store.error,
                "reserved_outcome": result.reserved_outcome.value,
                "cause": "AEGIS_SOURCE_OWNED_INDEPENDENT_ADMISSION",
            },
        )
        return result

    def _reserve_peer(
        self,
        production: ProductionChunk,
        *,
        operation_id: str,
        resource_id: str,
        timestamp_ns: int,
    ) -> PathAdmission:
        raw_quote = self.peer_pool.quote(
            resource_id=resource_id,
            payload_bytes=production.payload_bytes,
        )
        quote = AllocationQuote(
            pool=PolicyPool.PEER_HBM,
            resource_id=raw_quote.resource_id,
            payload_bytes=raw_quote.payload_bytes,
            allocated_bytes=raw_quote.allocated_bytes,
            allocator_metadata_bytes=raw_quote.allocator_metadata_bytes,
            internal_fragmentation_bytes=raw_quote.internal_fragmentation_bytes,
            alignment_bytes=raw_quote.alignment_bytes,
        )
        candidate = production.policy_candidate(allocated_bytes=quote.allocated_bytes)
        decision = self.policy.preview(
            PolicyPool.PEER_HBM,
            candidate,
            quote,
            timestamp_ns,
        )
        if not decision.admitted:
            return PathAdmission(pool=PolicyPool.PEER_HBM, decision=decision)
        try:
            ticket = self.peer_pool.reserve(
                production.identity,
                operation_id=f"{operation_id}:peer",
                quote=raw_quote,
                victim_allocation_ids=decision.victim_allocation_ids,
                timestamp_ns=timestamp_ns,
            )
        except (KeyError, RuntimeError, ValueError) as error:
            return PathAdmission(
                pool=PolicyPool.PEER_HBM,
                decision=decision,
                error=f"{type(error).__name__}:{error}",
            )
        return PathAdmission(
            pool=PolicyPool.PEER_HBM,
            decision=decision,
            peer_ticket=ticket,
        )

    def _reserve_store(
        self,
        production: ProductionChunk,
        *,
        operation_id: str,
        segment_id: str,
        timestamp_ns: int,
    ) -> PathAdmission:
        raw_quote = self.store_pool.quote(
            segment_id=segment_id,
            payload_bytes=production.payload_bytes,
        )
        quote = AllocationQuote(
            pool=PolicyPool.STORE_DRAM,
            resource_id=raw_quote.segment_id,
            payload_bytes=raw_quote.payload_bytes,
            allocated_bytes=raw_quote.allocated_bytes,
            allocator_metadata_bytes=raw_quote.allocator_metadata_bytes,
            internal_fragmentation_bytes=raw_quote.internal_fragmentation_bytes,
            alignment_bytes=raw_quote.alignment_bytes,
        )
        candidate = production.policy_candidate(allocated_bytes=quote.allocated_bytes)
        decision = self.policy.preview(
            PolicyPool.STORE_DRAM,
            candidate,
            quote,
            timestamp_ns,
        )
        if not decision.admitted:
            return PathAdmission(pool=PolicyPool.STORE_DRAM, decision=decision)
        try:
            ticket = self.store_pool.reserve(
                production.identity,
                operation_id=f"{operation_id}:store",
                quote=raw_quote,
                victim_allocation_ids=decision.victim_allocation_ids,
                timestamp_ns=timestamp_ns,
            )
        except (KeyError, RuntimeError, ValueError) as error:
            return PathAdmission(
                pool=PolicyPool.STORE_DRAM,
                decision=decision,
                error=f"{type(error).__name__}:{error}",
            )
        return PathAdmission(
            pool=PolicyPool.STORE_DRAM,
            decision=decision,
            store_ticket=ticket,
        )
