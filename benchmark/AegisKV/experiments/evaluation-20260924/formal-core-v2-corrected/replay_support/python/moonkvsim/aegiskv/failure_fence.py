"""Prepared AegisKV GPU failure fence for the pure GlobalDES layer.

This module computes one immutable, canonical mutation plan.  The existing
``AtomicGPUHBMFailStop`` remains responsible for ledger mutation; an adapter can
consume this plan only after its physical preflight succeeds.  Keeping planning
pure makes failed-target Peer-HBM invalidation and Store-DRAM isolation auditable
before any state changes occur.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from moonkvsim.common.hash import canonical_json_bytes, sha256_json

PEER_HBM = "PEER_HBM"
STORE_DRAM = "STORE_DRAM"


def _value(value: object) -> str:
    raw = getattr(value, "value", value)
    if not isinstance(raw, str):
        raise TypeError("enum-compatible values must resolve to strings")
    return raw


def _require_canonical_ids(values: tuple[str, ...], label: str) -> None:
    if any(not value for value in values):
        raise ValueError(f"{label} must be non-empty strings")
    if tuple(sorted(set(values))) != values:
        raise ValueError(f"{label} must be sorted and unique")


class FenceRouteStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RECOVERING = "RECOVERING"
    FINISHED = "FINISHED"
    FENCED = "FENCED"
    RECOVERY_FAILED_NO_TARGET = "RECOVERY_FAILED_NO_TARGET"


class OperationDependency(StrEnum):
    """Why an in-flight operation must be canceled on a GPU failure."""

    EXECUTOR_ROUTE = "EXECUTOR_ROUTE"
    PHYSICAL_RESOURCES = "PHYSICAL_RESOURCES"
    INDEPENDENT_POOL_PATH = "INDEPENDENT_POOL_PATH"


@dataclass(frozen=True, slots=True)
class GPUFailureContext:
    failure_id: str
    gpu_id: str
    failed_target_ids: tuple[str, ...]
    failed_hbm_resource_ids: tuple[str, ...]
    timestamp_ns: int

    def __post_init__(self) -> None:
        if not self.failure_id or not self.gpu_id:
            raise ValueError("failure_id and gpu_id must be non-empty")
        _require_canonical_ids(self.failed_target_ids, "failed_target_ids")
        _require_canonical_ids(self.failed_hbm_resource_ids, "failed_hbm_resource_ids")
        if self.timestamp_ns < 0:
            raise ValueError("timestamp_ns must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "failed_hbm_resource_ids": list(self.failed_hbm_resource_ids),
            "failed_target_ids": list(self.failed_target_ids),
            "failure_id": self.failure_id,
            "failure_type": "GPU_FAILURE",
            "gpu_id": self.gpu_id,
            "timestamp_ns": self.timestamp_ns,
        }


@dataclass(frozen=True, slots=True)
class FailureRoute:
    request_id: str
    route_version: int
    target_id: str
    status: FenceRouteStatus
    authoritative: bool

    def __post_init__(self) -> None:
        if not self.request_id or not self.target_id:
            raise ValueError("route identifiers must be non-empty")
        if self.route_version < 0:
            raise ValueError("route_version must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "authoritative": self.authoritative,
            "request_id": self.request_id,
            "route_version": self.route_version,
            "status": self.status.value,
            "target_id": self.target_id,
        }


@dataclass(frozen=True, slots=True)
class ReplicaResidentShard:
    shard_id: str
    allocation_id: str
    resource_id: str

    def __post_init__(self) -> None:
        if not self.shard_id or not self.allocation_id or not self.resource_id:
            raise ValueError("resident shard identifiers must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {
            "allocation_id": self.allocation_id,
            "resource_id": self.resource_id,
            "shard_id": self.shard_id,
        }


@dataclass(frozen=True, slots=True)
class FailureReplica:
    replica_id: str
    location: str
    resident_target_id: str
    expected_shard_ids: tuple[str, ...]
    shards: tuple[ReplicaResidentShard, ...]
    source_lineage_gpu_id: str | None = None

    def __post_init__(self) -> None:
        if not self.replica_id or not self.resident_target_id:
            raise ValueError("replica_id and resident_target_id must be non-empty")
        if _value(self.location) not in {PEER_HBM, STORE_DRAM}:
            raise ValueError("failure fence accepts only Peer-HBM or Store-DRAM replicas")
        _require_canonical_ids(self.expected_shard_ids, "expected_shard_ids")
        shard_ids = tuple(sorted(shard.shard_id for shard in self.shards))
        if shard_ids != self.expected_shard_ids:
            raise ValueError("replica shards must exactly bind every expected shard")
        allocation_ids = tuple(shard.allocation_id for shard in self.shards)
        if len(set(allocation_ids)) != len(allocation_ids):
            raise ValueError("one allocation cannot bind multiple replica shards")
        if self.source_lineage_gpu_id is not None and not self.source_lineage_gpu_id:
            raise ValueError("source_lineage_gpu_id cannot be empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "expected_shard_ids": list(self.expected_shard_ids),
            "location": _value(self.location),
            "replica_id": self.replica_id,
            "resident_target_id": self.resident_target_id,
            "shards": [shard.to_dict() for shard in self.shards],
            "source_lineage_gpu_id": self.source_lineage_gpu_id,
        }


@dataclass(frozen=True, slots=True)
class FailureOperation:
    operation_id: str
    dependency: OperationDependency
    resource_ids: tuple[str, ...]
    request_id: str | None = None
    route_version: int | None = None
    pool: str | None = None

    def __post_init__(self) -> None:
        if not self.operation_id:
            raise ValueError("operation_id must be non-empty")
        _require_canonical_ids(self.resource_ids, "operation resource_ids")
        if (self.request_id is None) != (self.route_version is None):
            raise ValueError("operation request_id and route_version must be supplied together")
        if self.request_id == "":
            raise ValueError("operation request_id cannot be empty")
        if self.route_version is not None and self.route_version < 0:
            raise ValueError("operation route_version must be non-negative")
        if self.pool is not None and _value(self.pool) not in {PEER_HBM, STORE_DRAM}:
            raise ValueError("operation pool must be Peer-HBM or Store-DRAM")

    @property
    def route_key(self) -> tuple[str, int] | None:
        if self.request_id is None or self.route_version is None:
            return None
        return (self.request_id, self.route_version)

    def to_dict(self) -> dict[str, object]:
        return {
            "dependency": self.dependency.value,
            "operation_id": self.operation_id,
            "pool": None if self.pool is None else _value(self.pool),
            "request_id": self.request_id,
            "resource_ids": list(self.resource_ids),
            "route_version": self.route_version,
        }


@dataclass(frozen=True, slots=True)
class FailureFencePlan:
    context: GPUFailureContext
    fenced_routes: tuple[FailureRoute, ...]
    invalidated_peer_replica_ids: tuple[str, ...]
    recovery_eligibility_revoked_allocation_ids: tuple[str, ...]
    physically_lost_allocation_ids: tuple[str, ...]
    stranded_healthy_allocation_ids: tuple[str, ...]
    preserved_peer_replica_ids: tuple[str, ...]
    preserved_store_replica_ids: tuple[str, ...]
    canceled_operation_ids: tuple[str, ...]
    preserved_operation_ids: tuple[str, ...]

    def canonical_fields(self) -> dict[str, object]:
        return {
            "canceled_operation_ids": list(self.canceled_operation_ids),
            "context": self.context.to_dict(),
            "eligibility_basis": "RESIDENT_TARGET_AND_PHYSICAL_RESOURCE_NOT_SOURCE_LINEAGE",
            "fenced_routes": [route.to_dict() for route in self.fenced_routes],
            "invalidated_peer_replica_ids": list(self.invalidated_peer_replica_ids),
            "physically_lost_allocation_ids": list(self.physically_lost_allocation_ids),
            "preserved_operation_ids": list(self.preserved_operation_ids),
            "preserved_peer_replica_ids": list(self.preserved_peer_replica_ids),
            "preserved_store_replica_ids": list(self.preserved_store_replica_ids),
            "recovery_eligibility_revoked_allocation_ids": list(
                self.recovery_eligibility_revoked_allocation_ids
            ),
            "stranded_healthy_allocation_ids": list(self.stranded_healthy_allocation_ids),
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        return {**self.canonical_fields(), "fingerprint": self.fingerprint}

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict()) + b"\n"


class AegisFailureFence:
    """Build a fail-closed, no-side-effect failure mutation plan."""

    def plan(
        self,
        context: GPUFailureContext,
        *,
        routes: tuple[FailureRoute, ...],
        replicas: tuple[FailureReplica, ...],
        operations: tuple[FailureOperation, ...],
    ) -> FailureFencePlan:
        route_keys = tuple((route.request_id, route.route_version) for route in routes)
        if len(set(route_keys)) != len(route_keys):
            raise ValueError("failure routes must be unique")
        replica_ids = tuple(replica.replica_id for replica in replicas)
        if len(set(replica_ids)) != len(replica_ids):
            raise ValueError("failure replicas must be unique")
        operation_ids = tuple(operation.operation_id for operation in operations)
        if len(set(operation_ids)) != len(operation_ids):
            raise ValueError("failure operations must be unique")

        failed_targets = frozenset(context.failed_target_ids)
        failed_resources = frozenset(context.failed_hbm_resource_ids)
        fenced_routes = tuple(
            sorted(
                (
                    route
                    for route in routes
                    if route.authoritative
                    and route.target_id in failed_targets
                    and route.status in {FenceRouteStatus.ACTIVE, FenceRouteStatus.RECOVERING}
                ),
                key=lambda route: (route.request_id, route.route_version),
            )
        )
        fenced_keys = frozenset((route.request_id, route.route_version) for route in fenced_routes)

        invalidated_peer: set[str] = set()
        revoked_allocations: set[str] = set()
        lost_allocations: set[str] = set()
        stranded_allocations: set[str] = set()
        preserved_peer: set[str] = set()
        preserved_store: set[str] = set()
        for replica in replicas:
            location = _value(replica.location)
            resources = frozenset(shard.resource_id for shard in replica.shards)
            if location == STORE_DRAM:
                if resources & failed_resources:
                    raise ValueError("Store-DRAM replica cannot occupy a failed GPU-HBM resource")
                preserved_store.add(replica.replica_id)
                continue
            invalidated = replica.resident_target_id in failed_targets or bool(
                resources & failed_resources
            )
            if not invalidated:
                preserved_peer.add(replica.replica_id)
                continue
            invalidated_peer.add(replica.replica_id)
            for shard in replica.shards:
                revoked_allocations.add(shard.allocation_id)
                if shard.resource_id in failed_resources:
                    lost_allocations.add(shard.allocation_id)
                else:
                    stranded_allocations.add(shard.allocation_id)

        canceled_operations: set[str] = set()
        preserved_operations: set[str] = set()
        for operation in operations:
            resource_failure = bool(failed_resources & frozenset(operation.resource_ids))
            route_failure = (
                operation.dependency is OperationDependency.EXECUTOR_ROUTE
                and operation.route_key in fenced_keys
            )
            if (
                operation.pool is not None
                and _value(operation.pool) == STORE_DRAM
                and resource_failure
            ):
                raise ValueError("Store-DRAM operation cannot depend on failed GPU-HBM resources")
            if resource_failure or route_failure:
                canceled_operations.add(operation.operation_id)
            else:
                preserved_operations.add(operation.operation_id)

        return FailureFencePlan(
            context=context,
            fenced_routes=fenced_routes,
            invalidated_peer_replica_ids=tuple(sorted(invalidated_peer)),
            recovery_eligibility_revoked_allocation_ids=tuple(sorted(revoked_allocations)),
            physically_lost_allocation_ids=tuple(sorted(lost_allocations)),
            stranded_healthy_allocation_ids=tuple(sorted(stranded_allocations)),
            preserved_peer_replica_ids=tuple(sorted(preserved_peer)),
            preserved_store_replica_ids=tuple(sorted(preserved_store)),
            canceled_operation_ids=tuple(sorted(canceled_operations)),
            preserved_operation_ids=tuple(sorted(preserved_operations)),
        )
