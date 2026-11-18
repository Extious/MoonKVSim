"""Logical overlays and refcounts for physically charged allocations."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, cast

from moonkvsim.simulation.allocation import (
    AllocationRole,
    AllocationState,
    PhysicalAllocation,
)
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import UNAVAILABLE_CAPACITY_ACCOUNT, CapacityLedger


@dataclass(frozen=True, slots=True)
class AllocationOverlay:
    source_pin_count: int = 0
    recovery_eligible: bool = False


class AllocationRegistry:
    """Tracks overlays without applying a second capacity charge."""

    def __init__(self, *, journal: EventJournal | None = None) -> None:
        self._allocations: dict[str, PhysicalAllocation] = {}
        self._overlays: dict[str, AllocationOverlay] = {}
        # Capacity accounts become registry-managed the first time an allocation
        # is charged to them.  Keeping the historical keys lets ``audit`` detect
        # both undercharges and leaked bytes after reaccount/release.
        self._managed_account_keys: set[tuple[str, str]] = set()
        # Bytes such as model weights, runtime reserve, and FREE are not
        # represented by PhysicalAllocation records.  On a fail-stopped GPU
        # those bytes are nevertheless moved into UNAVAILABLE_CAPACITY.  This
        # map records that exact non-allocation residual without weakening the
        # equality audit for any registry-managed account.
        self._unavailable_residual_bytes: dict[str, int] = {}
        self.journal = journal

    def allocations_on_resources(
        self, resource_ids: Iterable[str]
    ) -> tuple[PhysicalAllocation, ...]:
        """Return all known allocations on the selected physical resources."""

        selected = frozenset(resource_ids)
        return tuple(
            allocation
            for _, allocation in sorted(self._allocations.items())
            if allocation.resource_id in selected
        )

    def has_unavailable_residual(self, resource_id: str) -> bool:
        return resource_id in self._unavailable_residual_bytes

    def set_unavailable_residual(
        self,
        resource_id: str,
        residual_bytes: int,
        *,
        timestamp_ns: int,
        event_id: str,
    ) -> None:
        """Bind non-allocation bytes on one failed resource to its ledger.

        This is deliberately a one-shot GPU-failure operation.  It cannot be
        used as a general account offset and therefore preserves strict exact
        equality for every ordinary managed account.
        """

        if not resource_id or residual_bytes < 0:
            raise ValueError(
                "resource_id must be non-empty and residual_bytes non-negative"
            )
        if resource_id in self._unavailable_residual_bytes:
            raise ValueError(f"unavailable residual already set: {resource_id}")
        self._unavailable_residual_bytes[resource_id] = residual_bytes
        self._managed_account_keys.add((resource_id, UNAVAILABLE_CAPACITY_ACCOUNT))
        self._append(
            timestamp_ns,
            "ALLOCATION_UNAVAILABLE_RESIDUAL_SET",
            {
                "event_id": event_id,
                "resource_id": resource_id,
                "residual_bytes": residual_bytes,
            },
        )

    def add(self, allocation: PhysicalAllocation, *, timestamp_ns: int, event_id: str) -> None:
        if allocation.allocation_id in self._allocations:
            raise ValueError(f"duplicate allocation_id: {allocation.allocation_id}")
        if allocation.state is AllocationState.RELEASED:
            raise ValueError("cannot add an already released allocation")
        self._allocations[allocation.allocation_id] = allocation
        self._overlays[allocation.allocation_id] = AllocationOverlay()
        self._managed_account_keys.add((allocation.resource_id, allocation.owner_account))
        self._append(
            timestamp_ns,
            "ALLOCATION_ADDED",
            {"event_id": event_id, "allocation": self._allocation_data(allocation)},
        )

    def get(self, allocation_id: str) -> PhysicalAllocation:
        return self._allocations[allocation_id]

    def overlay(self, allocation_id: str) -> AllocationOverlay:
        return self._overlays[allocation_id]

    def transition(
        self,
        allocation_id: str,
        state: AllocationState,
        *,
        timestamp_ns: int,
        event_id: str,
    ) -> None:
        allocation = self.get(allocation_id)
        overlay = self.overlay(allocation_id)
        if state in {AllocationState.LOST, AllocationState.RELEASED} and overlay.source_pin_count:
            raise ValueError("allocation must have zero source pins before terminal transition")
        if state is AllocationState.RELEASED and overlay.recovery_eligible:
            raise ValueError("recovery eligibility must be revoked before release")
        self._allocations[allocation_id] = allocation.transition(state, timestamp_ns=timestamp_ns)
        self._append(
            timestamp_ns,
            "ALLOCATION_TRANSITION",
            {"event_id": event_id, "allocation_id": allocation_id, "state": state.value},
        )

    def add_role(
        self,
        allocation_id: str,
        role: AllocationRole,
        *,
        timestamp_ns: int,
        event_id: str,
    ) -> None:
        allocation = self.get(allocation_id)
        if allocation.state in {AllocationState.LOST, AllocationState.RELEASED}:
            raise ValueError("terminal allocation cannot gain a role")
        self._allocations[allocation_id] = allocation.with_role(role)
        self._append(
            timestamp_ns,
            "ALLOCATION_ROLE_ADDED",
            {"event_id": event_id, "allocation_id": allocation_id, "role": role.value},
        )

    def remove_role(
        self,
        allocation_id: str,
        role: AllocationRole,
        *,
        timestamp_ns: int,
        event_id: str,
    ) -> None:
        allocation = self.get(allocation_id)
        if role not in allocation.roles:
            raise ValueError(f"allocation does not have role {role}")
        self._allocations[allocation_id] = allocation.without_role(role)
        self._append(
            timestamp_ns,
            "ALLOCATION_ROLE_REMOVED",
            {"event_id": event_id, "allocation_id": allocation_id, "role": role.value},
        )

    def reaccount(
        self,
        allocation_id: str,
        owner_account: str,
        *,
        timestamp_ns: int,
        event_id: str,
    ) -> None:
        allocation = self.get(allocation_id)
        previous_account = allocation.owner_account
        self._allocations[allocation_id] = allocation.reaccount(owner_account)
        self._managed_account_keys.add((allocation.resource_id, previous_account))
        self._managed_account_keys.add((allocation.resource_id, owner_account))
        self._append(
            timestamp_ns,
            "ALLOCATION_REACCOUNTED",
            {
                "event_id": event_id,
                "allocation_id": allocation_id,
                "account_from": previous_account,
                "account_to": owner_account,
            },
        )

    def pin_source(self, allocation_id: str, *, timestamp_ns: int, event_id: str) -> None:
        allocation = self.get(allocation_id)
        if allocation.state in {AllocationState.LOST, AllocationState.RELEASED}:
            raise ValueError("cannot pin a terminal allocation")
        overlay = self.overlay(allocation_id)
        self._overlays[allocation_id] = AllocationOverlay(
            source_pin_count=overlay.source_pin_count + 1,
            recovery_eligible=overlay.recovery_eligible,
        )
        self._append(
            timestamp_ns,
            "ALLOCATION_SOURCE_PINNED",
            {"event_id": event_id, "allocation_id": allocation_id},
        )

    def unpin_source(self, allocation_id: str, *, timestamp_ns: int, event_id: str) -> None:
        overlay = self.overlay(allocation_id)
        if overlay.source_pin_count == 0:
            raise ValueError("source pin count cannot become negative")
        self._overlays[allocation_id] = AllocationOverlay(
            source_pin_count=overlay.source_pin_count - 1,
            recovery_eligible=overlay.recovery_eligible,
        )
        self._append(
            timestamp_ns,
            "ALLOCATION_SOURCE_UNPINNED",
            {"event_id": event_id, "allocation_id": allocation_id},
        )

    def set_recovery_eligible(
        self,
        allocation_id: str,
        eligible: bool,
        *,
        timestamp_ns: int,
        event_id: str,
    ) -> None:
        allocation = self.get(allocation_id)
        if eligible and allocation.state is not AllocationState.COMMITTED:
            raise ValueError("only committed allocations may be recovery eligible")
        overlay = self.overlay(allocation_id)
        self._overlays[allocation_id] = AllocationOverlay(
            source_pin_count=overlay.source_pin_count,
            recovery_eligible=eligible,
        )
        self._append(
            timestamp_ns,
            "ALLOCATION_RECOVERY_ELIGIBILITY",
            {
                "event_id": event_id,
                "allocation_id": allocation_id,
                "eligible": eligible,
            },
        )

    def audit(self, ledgers: dict[str, CapacityLedger]) -> None:
        self._audit(ledgers, require_all_resources=True)

    def audit_resources(self, ledgers: dict[str, CapacityLedger]) -> None:
        """Strictly audit the supplied resource subset of a shared registry."""

        self._audit(ledgers, require_all_resources=False)

    def _audit(
        self,
        ledgers: dict[str, CapacityLedger],
        *,
        require_all_resources: bool,
    ) -> None:
        tracked: dict[tuple[str, str], int] = {}
        for allocation_id, allocation in self._allocations.items():
            overlay = self._overlays[allocation_id]
            if overlay.source_pin_count < 0:
                raise RuntimeError(f"negative source refcount: {allocation_id}")
            if overlay.recovery_eligible and allocation.state is not AllocationState.COMMITTED:
                raise RuntimeError(f"ineligible allocation exposed for recovery: {allocation_id}")
            if allocation.state is AllocationState.RELEASED:
                continue
            if allocation.resource_id not in ledgers:
                if require_all_resources:
                    raise RuntimeError(
                        f"allocation references unknown resource: {allocation_id}"
                    )
                continue
            key = (allocation.resource_id, allocation.owner_account)
            tracked[key] = tracked.get(key, 0) + allocation.allocated_bytes
        for resource_id, account in sorted(self._managed_account_keys):
            if resource_id not in ledgers:
                if require_all_resources:
                    raise RuntimeError(
                        f"managed account references unknown resource: {resource_id}:{account}"
                    )
                continue
            tracked_bytes = tracked.get((resource_id, account), 0)
            if account == UNAVAILABLE_CAPACITY_ACCOUNT:
                tracked_bytes += self._unavailable_residual_bytes.get(resource_id, 0)
            charged_bytes = ledgers[resource_id].bytes_in(account)
            if tracked_bytes != charged_bytes:
                raise RuntimeError(
                    f"tracked allocations disagree with {resource_id}:{account}: "
                    f"tracked={tracked_bytes}, charged={charged_bytes}"
                )

    def snapshot_bytes(self) -> bytes:
        snapshot = {
            "allocations": {
                allocation_id: {
                    "allocation": self._allocation_data(allocation),
                    "overlay": {
                        "source_pin_count": self._overlays[allocation_id].source_pin_count,
                        "recovery_eligible": self._overlays[allocation_id].recovery_eligible,
                    },
                }
                for allocation_id, allocation in sorted(self._allocations.items())
            },
            "managed_account_keys": [
                [resource_id, account]
                for resource_id, account in sorted(self._managed_account_keys)
            ],
            "unavailable_residual_bytes": dict(
                sorted(self._unavailable_residual_bytes.items())
            ),
        }
        return json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()

    def _append(self, timestamp_ns: int, record_type: str, data: dict[str, Any]) -> None:
        if self.journal is not None:
            self.journal.append(timestamp_ns, record_type, data)

    @staticmethod
    def _allocation_data(allocation: PhysicalAllocation) -> dict[str, Any]:
        return {
            "allocation_id": allocation.allocation_id,
            "object_id": allocation.object_id,
            "replica_id": allocation.replica_id,
            "resource_id": allocation.resource_id,
            "owner_account": allocation.owner_account,
            "payload_bytes": allocation.payload_bytes,
            "requested_bytes": allocation.requested_bytes,
            "allocated_bytes": allocation.allocated_bytes,
            "padding_bytes": allocation.padding_bytes,
            "allocator_metadata_bytes": allocation.allocator_metadata_bytes,
            "internal_fragmentation_bytes": allocation.internal_fragmentation_bytes,
            "alignment_bytes": allocation.alignment_bytes,
            "state": allocation.state.value,
            "created_at_ns": allocation.created_at_ns,
            "released_at_ns": allocation.released_at_ns,
            "roles": sorted(role.value for role in allocation.roles),
        }


def replay_allocation_registry(journal: EventJournal) -> AllocationRegistry:
    registry = AllocationRegistry()
    registry_record_types = {
        "ALLOCATION_ADDED",
        "ALLOCATION_TRANSITION",
        "ALLOCATION_ROLE_ADDED",
        "ALLOCATION_ROLE_REMOVED",
        "ALLOCATION_REACCOUNTED",
        "ALLOCATION_SOURCE_PINNED",
        "ALLOCATION_SOURCE_UNPINNED",
        "ALLOCATION_RECOVERY_ELIGIBILITY",
        "ALLOCATION_UNAVAILABLE_RESIDUAL_SET",
    }
    for record in journal.records:
        if record.record_type not in registry_record_types:
            continue
        data = record.data
        event_id = _string(data, "event_id")
        if record.record_type == "ALLOCATION_ADDED":
            raw = data.get("allocation")
            if not isinstance(raw, dict):
                raise ValueError("ALLOCATION_ADDED is missing allocation")
            values = cast(dict[str, Any], raw)
            roles = values.get("roles")
            if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
                raise ValueError("allocation roles must be a string list")
            allocation = PhysicalAllocation(
                allocation_id=_string(values, "allocation_id"),
                object_id=_string(values, "object_id"),
                replica_id=_string(values, "replica_id"),
                resource_id=_string(values, "resource_id"),
                owner_account=_string(values, "owner_account"),
                payload_bytes=_integer(values, "payload_bytes"),
                requested_bytes=_integer(values, "requested_bytes"),
                allocated_bytes=_integer(values, "allocated_bytes"),
                padding_bytes=_integer(values, "padding_bytes"),
                allocator_metadata_bytes=_integer(values, "allocator_metadata_bytes"),
                internal_fragmentation_bytes=_integer(values, "internal_fragmentation_bytes"),
                alignment_bytes=_integer(values, "alignment_bytes"),
                state=AllocationState(_string(values, "state")),
                created_at_ns=_integer(values, "created_at_ns"),
                released_at_ns=None,
                roles=frozenset(AllocationRole(role) for role in roles),
            )
            registry.add(allocation, timestamp_ns=record.timestamp_ns, event_id=event_id)
        elif record.record_type == "ALLOCATION_TRANSITION":
            registry.transition(
                _string(data, "allocation_id"),
                AllocationState(_string(data, "state")),
                timestamp_ns=record.timestamp_ns,
                event_id=event_id,
            )
        elif record.record_type == "ALLOCATION_ROLE_ADDED":
            registry.add_role(
                _string(data, "allocation_id"),
                AllocationRole(_string(data, "role")),
                timestamp_ns=record.timestamp_ns,
                event_id=event_id,
            )
        elif record.record_type == "ALLOCATION_ROLE_REMOVED":
            registry.remove_role(
                _string(data, "allocation_id"),
                AllocationRole(_string(data, "role")),
                timestamp_ns=record.timestamp_ns,
                event_id=event_id,
            )
        elif record.record_type == "ALLOCATION_REACCOUNTED":
            allocation_id = _string(data, "allocation_id")
            if registry.get(allocation_id).owner_account != _string(data, "account_from"):
                raise ValueError("allocation reaccount source does not match replay state")
            registry.reaccount(
                allocation_id,
                _string(data, "account_to"),
                timestamp_ns=record.timestamp_ns,
                event_id=event_id,
            )
        elif record.record_type == "ALLOCATION_SOURCE_PINNED":
            registry.pin_source(
                _string(data, "allocation_id"),
                timestamp_ns=record.timestamp_ns,
                event_id=event_id,
            )
        elif record.record_type == "ALLOCATION_SOURCE_UNPINNED":
            registry.unpin_source(
                _string(data, "allocation_id"),
                timestamp_ns=record.timestamp_ns,
                event_id=event_id,
            )
        elif record.record_type == "ALLOCATION_RECOVERY_ELIGIBILITY":
            eligible = data.get("eligible")
            if not isinstance(eligible, bool):
                raise ValueError("eligible must be a bool")
            registry.set_recovery_eligible(
                _string(data, "allocation_id"),
                eligible,
                timestamp_ns=record.timestamp_ns,
                event_id=event_id,
            )
        elif record.record_type == "ALLOCATION_UNAVAILABLE_RESIDUAL_SET":
            registry.set_unavailable_residual(
                _string(data, "resource_id"),
                _integer(data, "residual_bytes"),
                timestamp_ns=record.timestamp_ns,
                event_id=event_id,
            )
    return registry


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _integer(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value
