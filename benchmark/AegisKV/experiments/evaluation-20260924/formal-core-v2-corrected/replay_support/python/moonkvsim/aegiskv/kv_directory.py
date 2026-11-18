"""AegisKV view over the one Mooncake directory and allocation registry.

This module deliberately owns no replica or allocation map.  It is a typed
facade over ``MasterService.directory`` and ``MasterService.allocation_registry``
so cache reuse and failure protection cannot diverge into two truth sources.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from moonkvsim.common.status import KVLocation
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation import AllocationRole, AllocationState
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.store.master import MasterService
from moonkvsim.store.metadata_store import GlobalKVDirectory
from moonkvsim.store.replica import Replica


class ResidencyOutcome(StrEnum):
    HBM_ONLY = "HBM_ONLY"
    DRAM_ONLY = "DRAM_ONLY"
    HBM_AND_DRAM = "HBM_AND_DRAM"
    BYPASS = "BYPASS"


class AegisKVDirectory:
    """Location- and role-aware queries over the Master's sole truth source."""

    def __init__(self, master: MasterService) -> None:
        self.master = master
        self.directory: GlobalKVDirectory = master.directory
        self.allocation_registry: AllocationRegistry = master.allocation_registry

    def replicas(
        self,
        identity: KVIdentity,
        *,
        locations: Iterable[KVLocation] | None = None,
    ) -> tuple[Replica, ...]:
        selected = None if locations is None else frozenset(locations)
        return self.directory.query(identity, locations=selected)

    def recovery_replicas(
        self,
        identity: KVIdentity,
        *,
        locations: Iterable[KVLocation] | None = None,
    ) -> tuple[Replica, ...]:
        """Return only committed, published, physically eligible protection copies."""

        return tuple(
            replica
            for replica in self.replicas(identity, locations=locations)
            if all(
                self._allocation_is_recovery_eligible(allocation_id)
                for allocation_id in replica.allocation_ids
            )
        )

    def reuse_replicas(
        self,
        identity: KVIdentity,
        *,
        locations: Iterable[KVLocation] | None = None,
    ) -> tuple[Replica, ...]:
        return tuple(
            replica
            for replica in self.replicas(identity, locations=locations)
            if all(
                AllocationRole.CACHE_REUSE
                in self.allocation_registry.get(allocation_id).roles
                for allocation_id in replica.allocation_ids
            )
        )

    def residency_outcome(self, identity: KVIdentity) -> ResidencyOutcome:
        peer = bool(self.recovery_replicas(identity, locations=(KVLocation.PEER_HBM,)))
        store = bool(self.recovery_replicas(identity, locations=(KVLocation.STORE_DRAM,)))
        if peer and store:
            return ResidencyOutcome.HBM_AND_DRAM
        if peer:
            return ResidencyOutcome.HBM_ONLY
        if store:
            return ResidencyOutcome.DRAM_ONLY
        return ResidencyOutcome.BYPASS

    def add_roles(
        self,
        allocation_id: str,
        roles: Iterable[AllocationRole],
        *,
        timestamp_ns: int,
        event_id_prefix: str,
    ) -> None:
        """Add logical overlays without changing the physical capacity charge."""

        if not event_id_prefix:
            raise ValueError("event_id_prefix must be non-empty")
        for role in sorted(frozenset(roles), key=lambda item: item.value):
            allocation = self.allocation_registry.get(allocation_id)
            if role in allocation.roles:
                continue
            self.allocation_registry.add_role(
                allocation_id,
                role,
                timestamp_ns=timestamp_ns,
                event_id=f"{event_id_prefix}:role:{role.value}",
            )

    def remove_all_roles(
        self,
        allocation_id: str,
        *,
        timestamp_ns: int,
        event_id_prefix: str,
    ) -> None:
        for role in sorted(
            self.allocation_registry.get(allocation_id).roles,
            key=lambda item: item.value,
        ):
            self.allocation_registry.remove_role(
                allocation_id,
                role,
                timestamp_ns=timestamp_ns,
                event_id=f"{event_id_prefix}:remove-role:{role.value}",
            )

    def object_id_for_allocation(self, allocation_id: str) -> str:
        replica = self.directory.get_replica_for_allocation(allocation_id)
        allocation = self.allocation_registry.get(allocation_id)
        if replica.object_id != allocation.object_id:
            raise RuntimeError("directory and allocation registry object IDs diverged")
        return replica.object_id

    def assert_shared_truth(self) -> None:
        if self.master.directory is not self.directory:
            raise RuntimeError("AegisKV directory detached from the Master directory")
        if self.master.allocation_registry is not self.allocation_registry:
            raise RuntimeError("AegisKV registry detached from the Master registry")

    def _allocation_is_recovery_eligible(self, allocation_id: str) -> bool:
        allocation = self.allocation_registry.get(allocation_id)
        overlay = self.allocation_registry.overlay(allocation_id)
        return (
            allocation.state is AllocationState.COMMITTED
            and AllocationRole.FAILURE_PROTECTION in allocation.roles
            and overlay.recovery_eligible
        )
