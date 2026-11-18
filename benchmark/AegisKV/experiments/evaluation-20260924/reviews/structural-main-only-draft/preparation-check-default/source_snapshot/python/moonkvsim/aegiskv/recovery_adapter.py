"""Single-directory recovery mapping and GlobalDES capacity-hold adapter.

This module normalizes committed recovery sources from the sole AegisKV/Master directory
and allocation registry.  It supports only the exact TP=1 mapping currently represented by
one replica shard and one physical allocation; it never guesses a many-to-many association
with ``zip``.  The path state machine pins sources and charges destination holds, but moves
no bytes and creates no replica, allocation, or second metadata directory.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from moonkvsim.aegiskv.kv_directory import AegisKVDirectory
from moonkvsim.aegiskv.recovery_planner import (
    AegisRecoveryPlanner,
    HeterogeneousRecoveryPlan,
    RecoveryBlockRequirement,
    RecoveryCandidate,
    RecoveryPlanningContext,
    RecoveryPlanningError,
    RecoveryShardCandidate,
    RecoverySourceKind,
)
from moonkvsim.common.status import KVLocation
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation import AllocationRole, AllocationState
from moonkvsim.simulation.ledger import (
    FREE_ACCOUNT,
    AccountTransfer,
    CapacityLedger,
    CapacityResourceKind,
)
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction

RECOVERY_DESTINATION_HOLD_ACCOUNT = "AEGIS_RECOVERY_DESTINATION_HOLD"


class RecoveryMappingError(RecoveryPlanningError):
    """The sole directory cannot prove one exact physical source binding."""


class RecoveryHoldState(StrEnum):
    PREPARED = "PREPARED"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


@dataclass(frozen=True, slots=True)
class RouteSourceAuthority:
    """Caller-owned route authority, separate from physical residence and lineage."""

    route_version: int
    authoritative: bool
    source_lineage_gpu_id: str

    def __post_init__(self) -> None:
        if type(self.route_version) is not int or self.route_version < 0:
            raise TypeError("route_version must be a non-negative integer")
        if type(self.authoritative) is not bool:
            raise TypeError("authoritative must be a boolean")
        if type(self.source_lineage_gpu_id) is not str or not self.source_lineage_gpu_id:
            raise ValueError("source_lineage_gpu_id must be non-empty")


@dataclass(frozen=True, slots=True)
class RecoveryAuthorityRequirements:
    """Explicit caller maps required to interpret directory and resource truth."""

    identities_by_object_id: Mapping[str, KVIdentity]
    requirements_by_object_id: Mapping[str, RecoveryBlockRequirement]
    resource_kind_by_resource_id: Mapping[str, CapacityResourceKind]
    resident_target_by_resource_id: Mapping[str, str]
    route_authority_by_replica_id: Mapping[str, RouteSourceAuthority]

    def __post_init__(self) -> None:
        if set(self.identities_by_object_id) != set(self.requirements_by_object_id):
            raise RecoveryMappingError("identity and requirement object maps must have exact keys")
        if not self.identities_by_object_id:
            raise RecoveryMappingError("recovery authority requirements must not be empty")
        for object_id, identity in self.identities_by_object_id.items():
            if not object_id or type(identity) is not KVIdentity:
                raise RecoveryMappingError("identity map contains an invalid entry")
            if identity.object_id != object_id:
                raise RecoveryMappingError("identity map key does not equal its content object_id")
            requirement = self.requirements_by_object_id[object_id]
            if type(requirement) is not RecoveryBlockRequirement:
                raise RecoveryMappingError("requirement map must contain exact requirements")
            if requirement != RecoveryBlockRequirement.from_identity(identity):
                raise RecoveryMappingError("requirement map diverges from its exact KV identity")
            if identity.tp_size != 1:
                raise RecoveryMappingError("recovery adapter currently supports exact TP=1 only")
        if any(
            type(kind) is not CapacityResourceKind
            for kind in self.resource_kind_by_resource_id.values()
        ):
            raise RecoveryMappingError("resource-kind map must use exact CapacityResourceKind")
        if any(
            type(target) is not str or not target
            for target in self.resident_target_by_resource_id.values()
        ):
            raise RecoveryMappingError("resident-target map contains an invalid target")
        if any(
            type(authority) is not RouteSourceAuthority
            for authority in self.route_authority_by_replica_id.values()
        ):
            raise RecoveryMappingError("route-authority map contains an invalid authority")


@dataclass(frozen=True, slots=True)
class DestinationCapacityRequirement:
    """One source-tier path's explicit destination charge and terminal account."""

    path_kind: RecoverySourceKind
    destination_resource_id: str
    destination_resource_kind: CapacityResourceKind
    destination_target_id: str
    allocated_bytes: int
    committed_account: str

    def __post_init__(self) -> None:
        if type(self.path_kind) is not RecoverySourceKind:
            raise TypeError("path_kind must be an exact RecoverySourceKind")
        if self.path_kind not in {
            RecoverySourceKind.PEER_HBM,
            RecoverySourceKind.STORE_DRAM,
        }:
            raise ValueError("destination hold path must be Peer-HBM or Store-DRAM")
        if not self.destination_resource_id or not self.destination_target_id:
            raise ValueError("destination resource and target must be non-empty")
        if type(self.destination_resource_kind) is not CapacityResourceKind:
            raise TypeError("destination_resource_kind must be exact")
        if type(self.allocated_bytes) is not int or self.allocated_bytes <= 0:
            raise ValueError("destination allocated_bytes must be a positive integer")
        if not self.committed_account or self.committed_account in {
            FREE_ACCOUNT,
            RECOVERY_DESTINATION_HOLD_ACCOUNT,
        }:
            raise ValueError("destination committed account is invalid")


@dataclass(frozen=True, slots=True)
class PreparedRecoveryPath:
    operation_id: str
    path_kind: RecoverySourceKind
    source_allocation_ids: tuple[str, ...]
    destination: DestinationCapacityRequirement
    hold_account: str
    prepared_at_ns: int
    state: RecoveryHoldState = RecoveryHoldState.PREPARED
    terminal_at_ns: int | None = None

    def __post_init__(self) -> None:
        if not self.operation_id:
            raise ValueError("operation_id must be non-empty")
        if type(self.path_kind) is not RecoverySourceKind:
            raise TypeError("path_kind must be an exact RecoverySourceKind")
        if type(self.state) is not RecoveryHoldState:
            raise TypeError("state must be an exact RecoveryHoldState")
        if not self.source_allocation_ids:
            raise ValueError("prepared materialized path requires source allocations")
        if tuple(sorted(set(self.source_allocation_ids))) != self.source_allocation_ids:
            raise ValueError("source allocation IDs must be sorted and unique")
        _require_timestamp(self.prepared_at_ns)
        if self.terminal_at_ns is not None:
            _require_timestamp(self.terminal_at_ns)
        if self.path_kind is not self.destination.path_kind:
            raise ValueError("prepared path and destination path kinds differ")
        if not self.hold_account.startswith(f"{RECOVERY_DESTINATION_HOLD_ACCOUNT}:"):
            raise ValueError("prepared path hold account is not operation-scoped")
        if self.state is RecoveryHoldState.PREPARED and self.terminal_at_ns is not None:
            raise ValueError("PREPARED path cannot have a terminal timestamp")
        if self.state is not RecoveryHoldState.PREPARED and (
            self.terminal_at_ns is None or self.terminal_at_ns < self.prepared_at_ns
        ):
            raise ValueError("terminal path requires a monotonic terminal timestamp")

    def to_canonical_dict(self) -> dict[str, object]:
        return {
            "allocated_bytes": self.destination.allocated_bytes,
            "committed_account": self.destination.committed_account,
            "destination_resource_id": self.destination.destination_resource_id,
            "destination_resource_kind": self.destination.destination_resource_kind.value,
            "destination_target_id": self.destination.destination_target_id,
            "hold_account": self.hold_account,
            "operation_id": self.operation_id,
            "path_kind": self.path_kind.value,
            "prepared_at_ns": self.prepared_at_ns,
            "source_allocation_ids": list(self.source_allocation_ids),
            "state": self.state.value,
            "terminal_at_ns": self.terminal_at_ns,
        }


class AegisRecoveryAdapter:
    """Read and transact against the unique directory/registry and caller ledgers."""

    def __init__(self, *, directory: AegisKVDirectory) -> None:
        if type(directory) is not AegisKVDirectory:
            raise TypeError("directory must be the exact AegisKVDirectory facade")
        directory.assert_shared_truth()
        self._directory = directory
        self._paths: dict[tuple[str, RecoverySourceKind], PreparedRecoveryPath] = {}

    @property
    def directory(self) -> AegisKVDirectory:
        """Return the same facade; no metadata map is copied or re-owned."""

        return self._directory

    def build_candidates(
        self,
        authority: RecoveryAuthorityRequirements,
    ) -> dict[str, tuple[RecoveryCandidate, ...]]:
        """Normalize current committed recovery replicas with exact TP=1 bindings."""

        if type(authority) is not RecoveryAuthorityRequirements:
            raise TypeError("authority must be exact RecoveryAuthorityRequirements")
        self._directory.assert_shared_truth()
        result: dict[str, tuple[RecoveryCandidate, ...]] = {}
        for object_id in sorted(authority.identities_by_object_id):
            identity = authority.identities_by_object_id[object_id]
            requirement = authority.requirements_by_object_id[object_id]
            replicas = self._directory.recovery_replicas(
                identity,
                locations=(KVLocation.PEER_HBM, KVLocation.STORE_DRAM),
            )
            candidates = tuple(
                self._candidate_from_replica(replica, identity, requirement, authority)
                for replica in replicas
            )
            result[object_id] = tuple(sorted(candidates, key=lambda item: item.replica_id))
        return result

    def revalidate_plan(
        self,
        planner: AegisRecoveryPlanner,
        plan: HeterogeneousRecoveryPlan,
        *,
        context: RecoveryPlanningContext,
        authority: RecoveryAuthorityRequirements,
    ) -> dict[str, tuple[RecoveryCandidate, ...]]:
        """Refresh from sole truth and revalidate the original selections in place."""

        candidates = self.build_candidates(authority)
        planner.validate_selected_sources(
            plan,
            candidates_by_object_id=candidates,
            context=context,
        )
        return candidates

    def prepare(
        self,
        operation_id: str,
        plan: HeterogeneousRecoveryPlan,
        *,
        path_kind: RecoverySourceKind,
        destination: DestinationCapacityRequirement,
        planner: AegisRecoveryPlanner,
        context: RecoveryPlanningContext,
        authority: RecoveryAuthorityRequirements,
        ledgers: Mapping[str, CapacityLedger],
        timestamp_ns: int,
    ) -> PreparedRecoveryPath:
        """Revalidate, pin selected sources, and hold exact destination capacity."""

        _require_timestamp(timestamp_ns)
        if not operation_id:
            raise ValueError("operation_id must be non-empty")
        if type(path_kind) is not RecoverySourceKind or path_kind not in {
            RecoverySourceKind.PEER_HBM,
            RecoverySourceKind.STORE_DRAM,
        }:
            raise ValueError("only materialized Peer/Store paths require holds")
        if destination.path_kind is not path_kind:
            raise ValueError("destination requirement belongs to another source path")
        if destination.destination_target_id != context.destination_target_id:
            raise ValueError("destination hold target differs from recovery route destination")
        if timestamp_ns < context.timestamp_ns:
            raise ValueError("prepare cannot precede the recovery planning timestamp")
        key = (operation_id, path_kind)
        if key in self._paths:
            raise ValueError("recovery path operation ID must be unique per source tier")

        self.revalidate_plan(planner, plan, context=context, authority=authority)
        source_allocation_ids = tuple(
            sorted(
                shard.allocation_id
                for block in plan.blocks
                if block.source_kind is path_kind
                for shard in block.shards
            )
        )
        if not source_allocation_ids:
            raise ValueError("plan has no selected sources for the requested path")
        if len(set(source_allocation_ids)) != len(source_allocation_ids):
            raise RecoveryMappingError("one path selected a source allocation more than once")

        try:
            ledger = ledgers[destination.destination_resource_id]
        except KeyError as error:
            raise KeyError("destination capacity ledger is missing") from error
        if ledger.resource_kind is not destination.destination_resource_kind:
            raise ValueError("destination ledger resource kind differs from explicit requirement")
        hold_account = self._hold_account(operation_id, path_kind)
        ledger.preview(
            [
                AccountTransfer(
                    account_from=FREE_ACCOUNT,
                    account_to=hold_account,
                    delta_bytes=destination.allocated_bytes,
                )
            ]
        )
        self._validate_sources_for_pin(source_allocation_ids)
        self._validate_journal_timestamp(timestamp_ns)

        pinned: list[str] = []
        try:
            for allocation_id in source_allocation_ids:
                self._directory.allocation_registry.pin_source(
                    allocation_id,
                    timestamp_ns=timestamp_ns,
                    event_id=f"{operation_id}:{path_kind.value}:source-pin:{allocation_id}",
                )
                pinned.append(allocation_id)
            ResourceTransaction(
                event_id=f"{operation_id}:{path_kind.value}:destination-hold",
                timestamp_ns=timestamp_ns,
                cause=f"AEGIS_RECOVERY_{path_kind.value}_DESTINATION_HOLD",
                allocation_deltas=[
                    AllocationDelta(
                        resource_id=destination.destination_resource_id,
                        account_from=FREE_ACCOUNT,
                        account_to=hold_account,
                        delta_bytes=destination.allocated_bytes,
                        allocation_id=self._hold_allocation_id(operation_id, path_kind),
                    )
                ],
            ).commit(ledgers, journal=self._directory.master.journal)
        except Exception:
            self._unpin_many(
                tuple(reversed(pinned)),
                operation_id=operation_id,
                path_kind=path_kind,
                timestamp_ns=timestamp_ns,
                phase="prepare-rollback",
            )
            raise

        prepared = PreparedRecoveryPath(
            operation_id=operation_id,
            path_kind=path_kind,
            source_allocation_ids=source_allocation_ids,
            destination=destination,
            hold_account=hold_account,
            prepared_at_ns=timestamp_ns,
        )
        self._paths[key] = prepared
        return prepared

    def commit(
        self,
        operation_id: str,
        path_kind: RecoverySourceKind,
        *,
        ledgers: Mapping[str, CapacityLedger],
        timestamp_ns: int,
    ) -> PreparedRecoveryPath:
        """Commit one held destination account after caller-reported transfer success."""

        path = self._require_prepared(operation_id, path_kind, timestamp_ns)
        self._validate_terminal_preconditions(path, ledgers)
        ResourceTransaction(
            event_id=f"{operation_id}:{path_kind.value}:destination-hold-commit",
            timestamp_ns=timestamp_ns,
            cause=f"AEGIS_RECOVERY_{path_kind.value}_DESTINATION_HOLD_COMMIT",
            allocation_deltas=[
                AllocationDelta(
                    resource_id=path.destination.destination_resource_id,
                    account_from=path.hold_account,
                    account_to=path.destination.committed_account,
                    delta_bytes=path.destination.allocated_bytes,
                    allocation_id=self._hold_allocation_id(operation_id, path_kind),
                )
            ],
        ).commit(ledgers, journal=self._directory.master.journal)
        self._unpin_many(
            path.source_allocation_ids,
            operation_id=operation_id,
            path_kind=path_kind,
            timestamp_ns=timestamp_ns,
            phase="commit",
        )
        terminal = replace(
            path,
            state=RecoveryHoldState.COMMITTED,
            terminal_at_ns=timestamp_ns,
        )
        self._paths[(operation_id, path_kind)] = terminal
        return terminal

    def abort(
        self,
        operation_id: str,
        path_kind: RecoverySourceKind,
        *,
        ledgers: Mapping[str, CapacityLedger],
        timestamp_ns: int,
    ) -> PreparedRecoveryPath:
        """Release one path's destination hold and source pins without cross-tier effects."""

        path = self._require_prepared(operation_id, path_kind, timestamp_ns)
        self._validate_terminal_preconditions(path, ledgers)
        ResourceTransaction(
            event_id=f"{operation_id}:{path_kind.value}:destination-hold-abort",
            timestamp_ns=timestamp_ns,
            cause=f"AEGIS_RECOVERY_{path_kind.value}_DESTINATION_HOLD_ABORT",
            allocation_deltas=[
                AllocationDelta(
                    resource_id=path.destination.destination_resource_id,
                    account_from=path.hold_account,
                    account_to=FREE_ACCOUNT,
                    delta_bytes=path.destination.allocated_bytes,
                    allocation_id=self._hold_allocation_id(operation_id, path_kind),
                )
            ],
        ).commit(ledgers, journal=self._directory.master.journal)
        self._unpin_many(
            path.source_allocation_ids,
            operation_id=operation_id,
            path_kind=path_kind,
            timestamp_ns=timestamp_ns,
            phase="abort",
        )
        terminal = replace(
            path,
            state=RecoveryHoldState.ABORTED,
            terminal_at_ns=timestamp_ns,
        )
        self._paths[(operation_id, path_kind)] = terminal
        return terminal

    def path(self, operation_id: str, path_kind: RecoverySourceKind) -> PreparedRecoveryPath:
        try:
            return self._paths[(operation_id, path_kind)]
        except KeyError as error:
            raise KeyError("unknown recovery path operation") from error

    def _candidate_from_replica(
        self,
        replica: object,
        identity: KVIdentity,
        requirement: RecoveryBlockRequirement,
        authority: RecoveryAuthorityRequirements,
    ) -> RecoveryCandidate:
        # Replica is intentionally duck-typed only at this private boundary; every field is
        # then checked before constructing the strict planner value.
        replica_id = _string_attr(replica, "replica_id")
        object_id = _string_attr(replica, "object_id")
        allocation_ids = _tuple_attr(replica, "allocation_ids")
        expected_shard_ids = _tuple_attr(replica, "expected_shard_ids")
        completed_raw = getattr(replica, "completed_shard_ids", None)
        if not isinstance(completed_raw, frozenset) or not all(
            isinstance(item, str) for item in completed_raw
        ):
            raise RecoveryMappingError("replica completed shard set is invalid")
        completed_shard_ids = tuple(sorted(completed_raw))
        exact_shards = (identity.shard_id,)
        if (
            identity.tp_size != 1
            or expected_shard_ids != exact_shards
            or completed_shard_ids != exact_shards
            or len(allocation_ids) != 1
        ):
            raise RecoveryMappingError(
                "TP=1 recovery requires exactly one named shard and one allocation; "
                "ambiguous multi-shard/allocation mapping is forbidden"
            )
        allocation_id = allocation_ids[0]
        allocation = self._directory.allocation_registry.get(allocation_id)
        overlay = self._directory.allocation_registry.overlay(allocation_id)
        if (
            allocation.object_id != object_id
            or allocation.object_id != requirement.object_id
            or allocation.replica_id != replica_id
            or allocation.state is not AllocationState.COMMITTED
            or AllocationRole.FAILURE_PROTECTION not in allocation.roles
            or not overlay.recovery_eligible
        ):
            raise RecoveryMappingError("directory and recovery allocation truth diverged")
        location = getattr(replica, "location", None)
        if location is KVLocation.PEER_HBM:
            source_kind = RecoverySourceKind.PEER_HBM
            expected_resource_kind = CapacityResourceKind.GPU_HBM
        elif location is KVLocation.STORE_DRAM:
            source_kind = RecoverySourceKind.STORE_DRAM
            expected_resource_kind = CapacityResourceKind.STORE_DRAM
        else:
            raise RecoveryMappingError("only Peer-HBM and Store-DRAM are recovery sources")
        resource_kind = _required_mapping(
            authority.resource_kind_by_resource_id,
            allocation.resource_id,
            "resource kind",
        )
        if resource_kind is not expected_resource_kind:
            raise RecoveryMappingError("directory location and caller resource kind diverge")
        resident_target = _required_mapping(
            authority.resident_target_by_resource_id,
            allocation.resource_id,
            "resident target",
        )
        route_authority = _required_mapping(
            authority.route_authority_by_replica_id,
            replica_id,
            "route authority",
        )
        if type(route_authority) is not RouteSourceAuthority:
            raise RecoveryMappingError("route authority has the wrong type")
        replica_route_version = _int_attr(replica, "route_version")
        if route_authority.route_version != replica_route_version:
            raise RecoveryMappingError("route authority version differs from directory replica")
        generation = _int_attr(replica, "generation")
        state = _enum_string_attr(replica, "state")
        visible = getattr(replica, "visible", None)
        if type(visible) is not bool:
            raise RecoveryMappingError("replica visibility must be a boolean")
        return RecoveryCandidate(
            replica_id=replica_id,
            object_id=object_id,
            source_kind=source_kind,
            location=source_kind.value,
            state=state,
            visible=visible,
            generation=generation,
            source_route_version=route_authority.route_version,
            source_route_authoritative=route_authority.authoritative,
            compatibility_key=requirement.compatibility_key,
            resident_target_id=str(resident_target),
            expected_shard_ids=exact_shards,
            completed_shard_ids=exact_shards,
            shards=(
                RecoveryShardCandidate(
                    shard_id=identity.shard_id,
                    allocation_id=allocation.allocation_id,
                    resource_id=allocation.resource_id,
                    resource_kind=resource_kind.value,
                    allocation_state=allocation.state.value,
                    recovery_eligible=overlay.recovery_eligible,
                    object_id=allocation.object_id,
                    replica_id=allocation.replica_id,
                ),
            ),
            # A failed production GPU may remain valid lineage; residence is separately
            # represented by resident_target_id and filtered by the planner context.
            source_lineage_gpu_id=route_authority.source_lineage_gpu_id,
        )

    def _validate_sources_for_pin(self, allocation_ids: Sequence[str]) -> None:
        for allocation_id in allocation_ids:
            allocation = self._directory.allocation_registry.get(allocation_id)
            overlay = self._directory.allocation_registry.overlay(allocation_id)
            if allocation.state is not AllocationState.COMMITTED or not overlay.recovery_eligible:
                raise RecoveryMappingError("source changed before capacity-hold preparation")

    def _require_prepared(
        self,
        operation_id: str,
        path_kind: RecoverySourceKind,
        timestamp_ns: int,
    ) -> PreparedRecoveryPath:
        _require_timestamp(timestamp_ns)
        if type(path_kind) is not RecoverySourceKind:
            raise TypeError("path_kind must be an exact RecoverySourceKind")
        path = self.path(operation_id, path_kind)
        if path.state is not RecoveryHoldState.PREPARED:
            raise ValueError("recovery path is already terminal")
        if timestamp_ns < path.prepared_at_ns:
            raise ValueError("terminal callback cannot precede prepare")
        self._validate_journal_timestamp(timestamp_ns)
        return path

    def _validate_terminal_preconditions(
        self,
        path: PreparedRecoveryPath,
        ledgers: Mapping[str, CapacityLedger],
    ) -> None:
        try:
            ledger = ledgers[path.destination.destination_resource_id]
        except KeyError as error:
            raise KeyError("destination capacity ledger is missing") from error
        if ledger.resource_kind is not path.destination.destination_resource_kind:
            raise ValueError("terminal destination ledger kind changed")
        if ledger.bytes_in(path.hold_account) != path.destination.allocated_bytes:
            raise ValueError("destination capacity hold is missing or undercharged")
        if any(
            self._directory.allocation_registry.overlay(allocation_id).source_pin_count <= 0
            for allocation_id in path.source_allocation_ids
        ):
            raise ValueError("recovery source pin is missing")

    def _unpin_many(
        self,
        allocation_ids: Sequence[str],
        *,
        operation_id: str,
        path_kind: RecoverySourceKind,
        timestamp_ns: int,
        phase: str,
    ) -> None:
        for allocation_id in allocation_ids:
            self._directory.allocation_registry.unpin_source(
                allocation_id,
                timestamp_ns=timestamp_ns,
                event_id=(
                    f"{operation_id}:{path_kind.value}:source-unpin:{phase}:{allocation_id}"
                ),
            )

    def _validate_journal_timestamp(self, timestamp_ns: int) -> None:
        records = self._directory.master.journal.records
        if records and timestamp_ns < records[-1].timestamp_ns:
            raise ValueError("recovery operation would move GlobalDES journal time backwards")

    @staticmethod
    def _hold_allocation_id(operation_id: str, path_kind: RecoverySourceKind) -> str:
        return f"recovery-hold:{operation_id}:{path_kind.value}"

    @staticmethod
    def _hold_account(operation_id: str, path_kind: RecoverySourceKind) -> str:
        return f"{RECOVERY_DESTINATION_HOLD_ACCOUNT}:{operation_id}:{path_kind.value}"


def _required_mapping(mapping: Mapping[str, object], key: str, label: str) -> object:
    try:
        return mapping[key]
    except KeyError as error:
        raise RecoveryMappingError(f"missing explicit {label} for {key}") from error


def _string_attr(value: object, name: str) -> str:
    result = getattr(value, name, None)
    if type(result) is not str or not result:
        raise RecoveryMappingError(f"replica {name} must be a non-empty string")
    return result


def _int_attr(value: object, name: str) -> int:
    result = getattr(value, name, None)
    if type(result) is not int or result < 0:
        raise RecoveryMappingError(f"replica {name} must be a non-negative integer")
    return result


def _enum_string_attr(value: object, name: str) -> str:
    result = getattr(value, name, None)
    raw = getattr(result, "value", result)
    if type(raw) is not str or not raw:
        raise RecoveryMappingError(f"replica {name} must resolve to a non-empty string")
    return raw


def _tuple_attr(value: object, name: str) -> tuple[str, ...]:
    result = getattr(value, name, None)
    if not isinstance(result, tuple) or not all(type(item) is str and item for item in result):
        raise RecoveryMappingError(f"replica {name} must be a string tuple")
    return result


def _require_timestamp(timestamp_ns: int) -> None:
    if type(timestamp_ns) is not int or timestamp_ns < 0:
        raise TypeError("timestamp_ns must be a non-negative integer")
