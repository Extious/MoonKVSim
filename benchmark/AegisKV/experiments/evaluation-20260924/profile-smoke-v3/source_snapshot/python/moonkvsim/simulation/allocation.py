"""Physical allocation records, separate from logical KV roles."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class AllocationState(StrEnum):
    RESERVED = "RESERVED"
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    LOST = "LOST"
    RELEASED = "RELEASED"


class AllocationRole(StrEnum):
    ACTIVE_PRIMARY = "ACTIVE_PRIMARY"
    CACHE_REUSE = "CACHE_REUSE"
    FAILURE_PROTECTION = "FAILURE_PROTECTION"


@dataclass(frozen=True, slots=True)
class PhysicalAllocation:
    allocation_id: str
    object_id: str
    replica_id: str
    resource_id: str
    owner_account: str
    payload_bytes: int
    requested_bytes: int
    allocated_bytes: int
    padding_bytes: int
    allocator_metadata_bytes: int
    internal_fragmentation_bytes: int
    alignment_bytes: int
    state: AllocationState
    created_at_ns: int
    released_at_ns: int | None = None
    roles: frozenset[AllocationRole] = frozenset()

    def __post_init__(self) -> None:
        identifiers = (
            self.allocation_id,
            self.object_id,
            self.replica_id,
            self.resource_id,
            self.owner_account,
        )
        if any(not value for value in identifiers):
            raise ValueError("allocation identifiers and owner_account must be non-empty")
        byte_fields = (
            self.payload_bytes,
            self.requested_bytes,
            self.allocated_bytes,
            self.padding_bytes,
            self.allocator_metadata_bytes,
            self.internal_fragmentation_bytes,
        )
        if any(value < 0 for value in byte_fields):
            raise ValueError("allocation byte counts must be non-negative")
        if self.alignment_bytes <= 0:
            raise ValueError("alignment_bytes must be positive")
        if self.requested_bytes != self.payload_bytes + self.padding_bytes:
            raise ValueError("requested_bytes must equal payload_bytes + padding_bytes")
        explained_allocated = (
            self.requested_bytes
            + self.allocator_metadata_bytes
            + self.internal_fragmentation_bytes
        )
        if self.allocated_bytes != explained_allocated:
            raise ValueError("allocated_bytes must be fully explained")
        if self.created_at_ns < 0:
            raise ValueError("created_at_ns must be non-negative")
        if self.released_at_ns is not None and self.released_at_ns < self.created_at_ns:
            raise ValueError("released_at_ns cannot precede created_at_ns")
        if self.state is AllocationState.RELEASED and self.released_at_ns is None:
            raise ValueError("released allocation requires released_at_ns")
        if self.state is not AllocationState.RELEASED and self.released_at_ns is not None:
            raise ValueError("only released allocations may have released_at_ns")

    def with_role(self, role: AllocationRole) -> PhysicalAllocation:
        return replace(self, roles=self.roles | {role})

    def without_role(self, role: AllocationRole) -> PhysicalAllocation:
        return replace(self, roles=self.roles - {role})

    def reaccount(self, owner_account: str) -> PhysicalAllocation:
        if not owner_account:
            raise ValueError("owner_account must be non-empty")
        if self.state in {AllocationState.LOST, AllocationState.RELEASED}:
            raise ValueError("terminal allocation cannot change owner account")
        return replace(self, owner_account=owner_account)

    def transition(self, state: AllocationState, *, timestamp_ns: int) -> PhysicalAllocation:
        if self.state in {AllocationState.LOST, AllocationState.RELEASED}:
            raise ValueError(f"terminal allocation cannot transition from {self.state}")
        allowed = {
            AllocationState.RESERVED: {
                AllocationState.PENDING,
                AllocationState.LOST,
                AllocationState.RELEASED,
            },
            AllocationState.PENDING: {
                AllocationState.COMMITTED,
                AllocationState.LOST,
                AllocationState.RELEASED,
            },
            AllocationState.COMMITTED: {AllocationState.LOST, AllocationState.RELEASED},
        }
        if state not in allowed[self.state]:
            raise ValueError(f"invalid allocation transition: {self.state} -> {state}")
        released_at_ns = timestamp_ns if state is AllocationState.RELEASED else None
        return replace(self, state=state, released_at_ns=released_at_ns)
