"""Vanilla Mooncake baseline GPU fail-stop, fencing, and Store recovery.

The baseline has exactly one failure kind (``GPU_FAILURE``) and exactly one
recovery source (committed ``STORE_DRAM`` continuous prefix).  Peer HBM and all
AegisKV admission/value policies are intentionally absent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any, Protocol

from moonkvsim.common.status import KVLocation, ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation import AllocationState
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import (
    UNAVAILABLE_CAPACITY_ACCOUNT,
    CapacityLedger,
    CapacityResourceKind,
)
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction
from moonkvsim.store.metadata_store import GlobalKVDirectory
from moonkvsim.store.replica import Replica


class FailureType(StrEnum):
    GPU_FAILURE = "GPU_FAILURE"


class GPUHealth(StrEnum):
    HEALTHY = "HEALTHY"
    FAILED = "FAILED"


class AttemptStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FENCED = "FENCED"
    RECOVERING = "RECOVERING"
    RECOVERY_FAILED_NO_TARGET = "RECOVERY_FAILED_NO_TARGET"
    FINISHED = "FINISHED"


class SilentReplayStatus(StrEnum):
    """Fail-closed output-position replay states for one rerouted attempt."""

    PLANNED = "PLANNED"
    REPLAYING = "REPLAYING"
    READY_TO_ACTIVATE = "READY_TO_ACTIVATE"
    ACTIVATED = "ACTIVATED"
    FENCED = "FENCED"


class OperationKind(StrEnum):
    FORWARD = "FORWARD"
    TRANSFER = "TRANSFER"


class RecoveryInvariantError(RuntimeError):
    """Raised when recovery state has no safe deterministic interpretation."""


class GPUHBMFailureObserver(Protocol):
    """A logical owner that must degrade records after physical HBM loss."""

    @property
    def hbm_resource_ids(self) -> frozenset[str]: ...

    @property
    def registry(self) -> AllocationRegistry: ...

    @property
    def journal(self) -> EventJournal: ...

    @property
    def ledgers(self) -> Mapping[str, CapacityLedger]: ...

    def validate_hbm_failure(self, resource_ids: frozenset[str]) -> None: ...

    def on_hbm_resources_failed(
        self,
        resource_ids: frozenset[str],
        *,
        gpu_id: str,
        failure_id: str,
        timestamp_ns: int,
    ) -> None: ...


class GPUHBMFailureHandler(Protocol):
    """Physical fail-stop API consumed by ``BaselineGPUFailureController``."""

    def fail_gpu_hbm(
        self,
        *,
        gpu_id: str,
        resource_ids: tuple[str, ...],
        failure_id: str,
        timestamp_ns: int,
    ) -> None: ...


class AtomicGPUHBMFailStop:
    """Move complete GPU HBM resources to unavailable capacity exactly once.

    All resource accounts are transferred in one multi-ledger transaction.
    Allocation overlays/roles are then revoked, allocations are reaccounted to
    the unavailable account, and their state becomes LOST.  Non-allocation
    bytes remain explicitly bound through the registry's unavailable residual.
    """

    def __init__(
        self,
        *,
        ledgers: Mapping[str, CapacityLedger],
        registry: AllocationRegistry,
        journal: EventJournal,
        observers: Iterable[GPUHBMFailureObserver] = (),
    ) -> None:
        if registry.journal is not journal:
            raise ValueError("HBM fail-stop registry and handler must share one journal")
        self.ledgers = dict(ledgers)
        self.registry = registry
        self.journal = journal
        self.observers = tuple(observers)

    def fail_gpu_hbm(
        self,
        *,
        gpu_id: str,
        resource_ids: tuple[str, ...],
        failure_id: str,
        timestamp_ns: int,
    ) -> None:
        if not gpu_id or not failure_id or timestamp_ns < 0:
            raise ValueError("gpu_id/failure_id and non-negative timestamp are required")
        if not resource_ids or len(resource_ids) != len(set(resource_ids)):
            raise ValueError("HBM failure resources must be non-empty and unique")
        selected = frozenset(resource_ids)
        for observer in self.observers:
            observer.validate_hbm_failure(selected)

        selected_ledgers: dict[str, CapacityLedger] = {}
        for resource_id in sorted(selected):
            ledger = self.ledgers.get(resource_id)
            if ledger is None:
                raise KeyError(f"unknown GPU HBM resource: {resource_id}")
            if ledger.resource_kind is not CapacityResourceKind.GPU_HBM:
                raise ValueError(f"failure resource is not GPU HBM: {resource_id}")
            if ledger.bytes_in(UNAVAILABLE_CAPACITY_ACCOUNT):
                raise ValueError(f"GPU HBM resource is already degraded: {resource_id}")
            if self.registry.has_unavailable_residual(resource_id):
                raise ValueError(f"GPU HBM unavailable residual is already recorded: {resource_id}")
            selected_ledgers[resource_id] = ledger

        # This validates exact ordinary managed-account equality before any
        # ledger mutation.  The handler must receive every registry resource,
        # not a selectively incomplete capacity view.
        self.registry.audit(self.ledgers)
        allocations = tuple(
            allocation
            for allocation in self.registry.allocations_on_resources(selected)
            if allocation.state is not AllocationState.RELEASED
        )
        if any(allocation.state is AllocationState.LOST for allocation in allocations):
            raise ValueError("healthy HBM resource already contains a LOST allocation")
        tracked_by_resource: dict[str, int] = {item: 0 for item in selected}
        tracked_by_account: dict[tuple[str, str], int] = {}
        for allocation in allocations:
            tracked_by_resource[allocation.resource_id] += allocation.allocated_bytes
            key = (allocation.resource_id, allocation.owner_account)
            tracked_by_account[key] = tracked_by_account.get(key, 0) + allocation.allocated_bytes
        residual_by_resource = {
            resource_id: ledger.capacity_bytes - tracked_by_resource[resource_id]
            for resource_id, ledger in selected_ledgers.items()
        }
        if any(value < 0 for value in residual_by_resource.values()):
            raise RecoveryInvariantError("tracked HBM allocations exceed physical capacity")

        deltas = [
            AllocationDelta(
                resource_id=allocation.resource_id,
                account_from=allocation.owner_account,
                account_to=UNAVAILABLE_CAPACITY_ACCOUNT,
                delta_bytes=allocation.allocated_bytes,
                allocation_id=allocation.allocation_id,
                object_id=allocation.object_id,
                replica_id=allocation.replica_id,
            )
            for allocation in allocations
        ]
        for resource_id, ledger in sorted(selected_ledgers.items()):
            for account, account_bytes in sorted(ledger.accounts.items()):
                if account == UNAVAILABLE_CAPACITY_ACCOUNT or account_bytes == 0:
                    continue
                residual_bytes = account_bytes - tracked_by_account.get(
                    (resource_id, account),
                    0,
                )
                if residual_bytes < 0:
                    raise RecoveryInvariantError(
                        "tracked HBM allocations exceed their charged account"
                    )
                if residual_bytes == 0:
                    continue
                residual_id = f"gpu-failure:{failure_id}:{resource_id}:residual:{account}"
                self.journal.append(
                    timestamp_ns,
                    "ALLOCATION_BYTE_SHAPE_DECLARED",
                    {
                        "event_id": f"{residual_id}:shape",
                        "allocation_id": residual_id,
                        "requested_bytes": residual_bytes,
                        "allocated_bytes": residual_bytes,
                        "shape_kind": "NON_ALLOCATION_ACCOUNT_RESIDUAL",
                        "resource_id": resource_id,
                        "account": account,
                    },
                )
                deltas.append(
                    AllocationDelta(
                        resource_id=resource_id,
                        account_from=account,
                        account_to=UNAVAILABLE_CAPACITY_ACCOUNT,
                        delta_bytes=residual_bytes,
                        allocation_id=residual_id,
                    )
                )
        ResourceTransaction(
            event_id=f"gpu-failure:{failure_id}:hbm-unavailable",
            timestamp_ns=timestamp_ns,
            cause=f"GPU_FAILURE:{failure_id}:HBM_FAIL_STOP",
            allocation_deltas=deltas,
        ).commit(self.ledgers, journal=self.journal)

        for allocation in allocations:
            allocation_id = allocation.allocation_id
            operation = f"gpu-failure:{failure_id}:{allocation_id}"
            overlay = self.registry.overlay(allocation_id)
            for pin_index in range(overlay.source_pin_count):
                self.registry.unpin_source(
                    allocation_id,
                    timestamp_ns=timestamp_ns,
                    event_id=f"{operation}:unpin:{pin_index}",
                )
            if self.registry.overlay(allocation_id).recovery_eligible:
                self.registry.set_recovery_eligible(
                    allocation_id,
                    False,
                    timestamp_ns=timestamp_ns,
                    event_id=f"{operation}:ineligible",
                )
            for role in sorted(allocation.roles, key=lambda item: item.value):
                self.registry.remove_role(
                    allocation_id,
                    role,
                    timestamp_ns=timestamp_ns,
                    event_id=f"{operation}:remove-role:{role.value}",
                )
            self.registry.reaccount(
                allocation_id,
                UNAVAILABLE_CAPACITY_ACCOUNT,
                timestamp_ns=timestamp_ns,
                event_id=f"{operation}:reaccount",
            )
            self.registry.transition(
                allocation_id,
                AllocationState.LOST,
                timestamp_ns=timestamp_ns,
                event_id=f"{operation}:lost",
            )

        for resource_id, residual_bytes in sorted(residual_by_resource.items()):
            self.registry.set_unavailable_residual(
                resource_id,
                residual_bytes,
                timestamp_ns=timestamp_ns,
                event_id=f"gpu-failure:{failure_id}:{resource_id}:residual",
            )
        self.registry.audit(self.ledgers)
        for observer in self.observers:
            observer.on_hbm_resources_failed(
                selected,
                gpu_id=gpu_id,
                failure_id=failure_id,
                timestamp_ns=timestamp_ns,
            )


@dataclass(frozen=True, slots=True)
class PhysicalGPU:
    gpu_id: str
    node_id: str
    hbm_resource_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.gpu_id or not self.node_id or not self.hbm_resource_ids:
            raise ValueError("GPU identity, node, and HBM resources must be non-empty")
        if any(not value for value in self.hbm_resource_ids):
            raise ValueError("HBM resource IDs must be non-empty")
        if len(set(self.hbm_resource_ids)) != len(self.hbm_resource_ids):
            raise ValueError("HBM resource IDs must be unique per GPU")


@dataclass(frozen=True, slots=True)
class EngineTarget:
    target_id: str
    dp_rank: int
    gpu_ids: tuple[str, ...]
    compatibility_key: str

    def __post_init__(self) -> None:
        if not self.target_id or not self.compatibility_key or not self.gpu_ids:
            raise ValueError("engine target identity, compatibility, and GPUs are required")
        if self.dp_rank < 0:
            raise ValueError("dp_rank must be non-negative")
        if any(not gpu_id for gpu_id in self.gpu_ids):
            raise ValueError("target GPU IDs must be non-empty")
        if len(set(self.gpu_ids)) != len(self.gpu_ids):
            raise ValueError("target GPU IDs must be unique")


@dataclass(frozen=True, slots=True)
class StorePrefixBlock:
    identity: KVIdentity
    replica_id: str
    allocation_ids: tuple[str, ...]
    resource_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.replica_id or not self.allocation_ids:
            raise ValueError("Store prefix binding must name a replica and allocations")
        if len(self.resource_ids) != len(self.allocation_ids) or any(
            not resource_id for resource_id in self.resource_ids
        ):
            raise ValueError("Store prefix resources must exactly cover allocations")

    @property
    def token_count(self) -> int:
        return self.identity.token_end - self.identity.token_start


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """Committed Store prefix plus an explicit recompute suffix."""

    required_block_count: int
    store_prefix: tuple[StorePrefixBlock, ...]
    restored_tokens: int
    recompute_tokens: int
    missing_suffix_start_block: int
    source: str = "VANILLA_STORE_DRAM"

    def __post_init__(self) -> None:
        if self.required_block_count < 0:
            raise ValueError("required_block_count must be non-negative")
        if self.missing_suffix_start_block != len(self.store_prefix):
            raise ValueError("missing suffix must begin after the continuous Store prefix")
        if self.required_block_count < len(self.store_prefix):
            raise ValueError("Store prefix cannot exceed required blocks")
        if self.restored_tokens < 0 or self.recompute_tokens < 0:
            raise ValueError("recovery token counts must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "required_block_count": self.required_block_count,
            "store_prefix": [
                {
                    "object_id": item.identity.object_id,
                    "token_start": item.identity.token_start,
                    "token_end": item.identity.token_end,
                    "replica_id": item.replica_id,
                    "allocation_ids": list(item.allocation_ids),
                    "resource_ids": list(item.resource_ids),
                }
                for item in self.store_prefix
            ],
            "restored_tokens": self.restored_tokens,
            "recompute_tokens": self.recompute_tokens,
            "missing_suffix_start_block": self.missing_suffix_start_block,
        }


class BaselineRecoveryPlanner:
    """Query the single directory for a committed continuous Store prefix."""

    def __init__(
        self,
        directory: GlobalKVDirectory,
        allocation_registry: AllocationRegistry,
    ) -> None:
        self.directory = directory
        self.allocation_registry = allocation_registry

    @staticmethod
    def validate_required_blocks(
        required_blocks: Sequence[KVIdentity],
    ) -> tuple[KVIdentity, ...]:
        """Return one validated token-zero continuous recovery sequence."""

        identities = tuple(required_blocks)
        _validate_required_blocks(identities)
        return identities

    def plan(
        self,
        required_blocks: Sequence[KVIdentity],
        *,
        unavailable_resource_ids: Iterable[str] = (),
    ) -> RecoveryPlan:
        identities = self.validate_required_blocks(required_blocks)
        unavailable = frozenset(unavailable_resource_ids)
        prefix: list[StorePrefixBlock] = []

        visible_prefix = self.directory.query_committed_prefix(list(identities))
        for identity, visible_replicas in visible_prefix:
            # The E2 scheduler adapter owns whole physical KV blocks and does
            # not model slot-level restoration.  A partial final source block
            # is therefore an explicit recompute suffix even when Store has a
            # committed object for it; treating it as restored would publish a
            # computed-token position for bytes the scheduler cannot map.
            if (
                identity.token_start % identity.block_size_tokens != 0
                or identity.token_end - identity.token_start != identity.block_size_tokens
            ):
                break
            eligible = tuple(
                replica
                for replica in visible_replicas
                if self._usable_store_replica(replica, unavailable)
            )
            if not eligible:
                break
            replica = eligible[0]
            prefix.append(
                StorePrefixBlock(
                    identity=identity,
                    replica_id=replica.replica_id,
                    allocation_ids=replica.allocation_ids,
                    resource_ids=tuple(
                        self.allocation_registry.get(allocation_id).resource_id
                        for allocation_id in replica.allocation_ids
                    ),
                )
            )

        restored_tokens = sum(item.token_count for item in prefix)
        recompute_tokens = sum(
            identity.token_end - identity.token_start for identity in identities[len(prefix) :]
        )
        return RecoveryPlan(
            required_block_count=len(identities),
            store_prefix=tuple(prefix),
            restored_tokens=restored_tokens,
            recompute_tokens=recompute_tokens,
            missing_suffix_start_block=len(prefix),
        )

    def _usable_store_replica(
        self,
        replica: Replica,
        unavailable_resource_ids: frozenset[str],
    ) -> bool:
        if (
            replica.location is not KVLocation.STORE_DRAM
            or replica.state is not ReplicaState.COMMITTED
            or not replica.visible
            or replica.completed_shard_ids != frozenset(replica.expected_shard_ids)
        ):
            return False
        for allocation_id in replica.allocation_ids:
            try:
                allocation = self.allocation_registry.get(allocation_id)
            except KeyError:
                return False
            if (
                allocation.replica_id != replica.replica_id
                or allocation.object_id != replica.object_id
                or allocation.state is not AllocationState.COMMITTED
                or allocation.resource_id in unavailable_resource_ids
            ):
                return False
        return True


@dataclass(frozen=True, slots=True)
class RouteAttempt:
    request_id: str
    route_version: int
    target_id: str
    status: AttemptStatus
    parent_route_version: int | None = None
    failure_id: str | None = None


@dataclass(frozen=True, slots=True)
class RerouteDecision:
    """A target/version published by the configured route authority."""

    target_id: str
    route_version: int
    authority_fingerprint: str | None = None


class BaselineRouteAuthority(Protocol):
    """Optional single source of truth for external DP route selection."""

    def is_authoritative(
        self,
        *,
        request_id: str,
        route_version: int,
        target_id: str,
    ) -> bool: ...

    def reroute(
        self,
        *,
        current: RouteAttempt,
        compatible_targets: tuple[EngineTarget, ...],
        healthy_target_ids: frozenset[str],
        now_ns: int,
    ) -> RerouteDecision | None: ...


@dataclass(frozen=True, slots=True)
class ActivatedOutput:
    request_id: str
    route_version: int
    output_index: int


@dataclass(frozen=True, slots=True)
class SilentReplayPlan:
    """Committed output-position checkpoint for one recovery route.

    MoonKVSim's E2 baseline is tensor-free and therefore never invents token
    IDs or token contents.  ``replayed_output_count`` may advance only after a
    successful modeled forward completion.  The immutable committed checkpoint
    is also the first externally publishable output index after activation.
    """

    request_id: str
    route_version: int
    committed_next_output_index: int
    replayed_output_count: int
    status: SilentReplayStatus
    prompt_materialized: bool = False
    cached_new_output_index: int | None = None
    cached_new_output_published: bool = False
    content_contract: str = "POSITION_ONLY_TENSOR_FREE_NO_TOKEN_CONTENT"

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("silent replay request_id must be non-empty")
        if type(self.route_version) is not int or self.route_version <= 0:
            raise ValueError("silent replay route_version must be positive")
        if (
            type(self.committed_next_output_index) is not int
            or self.committed_next_output_index < 0
        ):
            raise ValueError("committed output checkpoint must be non-negative")
        if (
            type(self.replayed_output_count) is not int
            or self.replayed_output_count < 0
            or self.replayed_output_count > self.committed_next_output_index
        ):
            raise ValueError("silent replay progress exceeds its committed checkpoint")
        if (
            self.status
            in {
                SilentReplayStatus.READY_TO_ACTIVATE,
                SilentReplayStatus.ACTIVATED,
            }
            and self.replayed_output_count != self.committed_next_output_index
        ):
            raise ValueError("ready/activated replay must reach the committed checkpoint")
        if (
            type(self.prompt_materialized) is not bool
            or type(self.cached_new_output_published) is not bool
        ):
            raise TypeError("silent replay materialization flags must be boolean")
        if self.replayed_output_count and not self.prompt_materialized:
            raise ValueError("replayed output requires prompt materialization")
        if (
            self.status
            in {
                SilentReplayStatus.READY_TO_ACTIVATE,
                SilentReplayStatus.ACTIVATED,
            }
            and not self.prompt_materialized
        ):
            raise ValueError("ready/activated recovery requires prompt materialization")
        if self.cached_new_output_index is not None and (
            type(self.cached_new_output_index) is not int
            or self.cached_new_output_index != self.committed_next_output_index
            or self.committed_next_output_index != 0
            or self.replayed_output_count != 0
            or not self.prompt_materialized
        ):
            raise ValueError("cached new output must be position zero after prompt materialization")
        if self.cached_new_output_published and (
            self.cached_new_output_index is None
            or self.status not in {SilentReplayStatus.ACTIVATED, SilentReplayStatus.FENCED}
        ):
            raise ValueError("only activated recovery may publish its cached new output")
        if self.status is SilentReplayStatus.PLANNED and (
            self.replayed_output_count != 0
            or self.prompt_materialized
            or self.cached_new_output_index is not None
            or self.cached_new_output_published
        ):
            raise ValueError("planned silent replay cannot contain materialized progress")

    @property
    def remaining_output_count(self) -> int:
        return self.committed_next_output_index - self.replayed_output_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "route_version": self.route_version,
            "committed_next_output_index": self.committed_next_output_index,
            "replayed_output_count": self.replayed_output_count,
            "remaining_output_count": self.remaining_output_count,
            "status": self.status.value,
            "prompt_materialized": self.prompt_materialized,
            "cached_new_output_index": self.cached_new_output_index,
            "cached_new_output_published": self.cached_new_output_published,
            "content_contract": self.content_contract,
        }


@dataclass(frozen=True, slots=True)
class _InFlightOperation:
    handle: EventHandle
    kind: OperationKind
    request_id: str
    route_version: int
    gpu_ids: frozenset[str]
    cancel_handler: Callable[[str], None] | None = None


class BaselineGPUFailureController:
    """Fail-stop GPU controller with deterministic fence/reroute activation."""

    def __init__(
        self,
        *,
        des: GlobalDES,
        directory: GlobalKVDirectory,
        allocation_registry: AllocationRegistry,
        gpus: Iterable[PhysicalGPU],
        targets: Iterable[EngineTarget],
        output_sink: Callable[[ActivatedOutput], None] | None = None,
        recovery_failure_sink: Callable[[str, int, str], None] | None = None,
        recovery_fence_sink: Callable[[str, int, str], None] | None = None,
        route_authority: BaselineRouteAuthority | None = None,
        hbm_failure_handler: GPUHBMFailureHandler | None = None,
    ) -> None:
        gpu_items = tuple(gpus)
        target_items = tuple(targets)
        self.des = des
        self.directory = directory
        self.allocation_registry = allocation_registry
        self.planner = BaselineRecoveryPlanner(directory, allocation_registry)
        self._gpus = {gpu.gpu_id: gpu for gpu in gpu_items}
        self._targets = {target.target_id: target for target in target_items}
        if not self._gpus or len(self._gpus) != len(gpu_items):
            raise ValueError("physical GPU IDs must be non-empty and unique")
        if not self._targets or len(self._targets) != len(target_items):
            raise ValueError("engine target IDs must be non-empty and unique")
        resource_owner: dict[str, str] = {}
        for gpu in gpu_items:
            for resource_id in gpu.hbm_resource_ids:
                if resource_id in resource_owner:
                    raise ValueError("one HBM resource cannot belong to multiple GPUs")
                resource_owner[resource_id] = gpu.gpu_id
        for target in target_items:
            unknown = set(target.gpu_ids) - set(self._gpus)
            if unknown:
                raise ValueError(f"target references unknown GPUs: {sorted(unknown)}")

        self._gpu_health = {gpu.gpu_id: GPUHealth.HEALTHY for gpu in gpu_items}
        self._attempts: dict[tuple[str, int], RouteAttempt] = {}
        self._current_route_versions: dict[str, int] = {}
        self._active_output_routes: dict[str, int] = {}
        self._required_blocks: dict[str, tuple[KVIdentity, ...]] = {}
        self._next_output_indices: dict[str, int] = {}
        self._emitted_outputs: list[ActivatedOutput] = []
        self._in_flight: dict[str, _InFlightOperation] = {}
        self._gpu_allocation_ids: dict[str, set[str]] = {gpu.gpu_id: set() for gpu in gpu_items}
        self._allocation_gpu_ids: dict[str, str] = {}
        self._failure_routes: dict[str, tuple[tuple[str, int], ...]] = {}
        self._recovery_plans: dict[tuple[str, int], RecoveryPlan] = {}
        self._silent_replay_plans: dict[tuple[str, int], SilentReplayPlan] = {}
        self._output_sink = output_sink
        self._recovery_failure_sink = recovery_failure_sink
        self._recovery_fence_sink = recovery_fence_sink
        self._route_authority = route_authority
        self._hbm_failure_handler = hbm_failure_handler

        self.des.register_handler(EventKind.FAILURE_INJECT, self._on_failure_inject)
        self.des.register_handler(EventKind.ROUTE_FENCE, self._on_route_fence)
        self.des.register_handler(EventKind.FAILURE_DETECT, self._on_failure_detect)
        self.des.register_handler(EventKind.REROUTE, self._on_reroute)
        self.des.register_handler(EventKind.REQUEST_COMPLETE, self._on_request_output)

    @property
    def emitted_outputs(self) -> tuple[ActivatedOutput, ...]:
        return tuple(self._emitted_outputs)

    @property
    def uses_external_route_authority(self) -> bool:
        return self._route_authority is not None

    def gpu_health(self, gpu_id: str) -> GPUHealth:
        self._require_gpu(gpu_id)
        return self._gpu_health[gpu_id]

    def target_is_healthy(self, target_id: str) -> bool:
        target = self._require_target(target_id)
        return all(self._gpu_health[gpu_id] is GPUHealth.HEALTHY for gpu_id in target.gpu_ids)

    def attempt(self, request_id: str, route_version: int) -> RouteAttempt:
        try:
            return self._attempts[(request_id, route_version)]
        except KeyError as error:
            raise KeyError(f"unknown route attempt: {request_id}@{route_version}") from error

    def current_route_version(self, request_id: str) -> int:
        try:
            return self._current_route_versions[request_id]
        except KeyError as error:
            raise KeyError(f"unknown request: {request_id}") from error

    def recovery_plan(self, request_id: str, route_version: int) -> RecoveryPlan:
        try:
            return self._recovery_plans[(request_id, route_version)]
        except KeyError as error:
            raise KeyError(f"route has no recovery plan: {request_id}@{route_version}") from error

    def silent_replay_plan(
        self,
        request_id: str,
        route_version: int,
    ) -> SilentReplayPlan:
        try:
            return self._silent_replay_plans[(request_id, route_version)]
        except KeyError as error:
            raise KeyError(
                f"route has no silent replay plan: {request_id}@{route_version}"
            ) from error

    def next_output_index(self, request_id: str) -> int:
        try:
            return self._next_output_indices[request_id]
        except KeyError as error:
            raise KeyError(f"unknown request: {request_id}") from error

    def begin_request(
        self,
        *,
        request_id: str,
        target_id: str,
        required_blocks: Sequence[KVIdentity],
        route_version: int = 0,
        next_output_index: int = 0,
    ) -> RouteAttempt:
        if not request_id or request_id in self._current_route_versions:
            raise ValueError("request_id must be non-empty and unique")
        if type(route_version) is not int or route_version != 0:
            raise ValueError("a baseline request must begin at route_version 0")
        if type(next_output_index) is not int or next_output_index < 0:
            raise ValueError("next_output_index must be a non-negative integer")
        target = self._require_target(target_id)
        if not self.target_is_healthy(target.target_id):
            raise ValueError("initial route target must be healthy")
        if not self._route_is_authoritative(request_id, route_version, target_id):
            raise RecoveryInvariantError(
                "initial route is not authoritative at the external router"
            )
        identities = self.planner.validate_required_blocks(required_blocks)
        attempt = RouteAttempt(
            request_id=request_id,
            route_version=route_version,
            target_id=target_id,
            status=AttemptStatus.ACTIVE,
        )
        self._attempts[(request_id, route_version)] = attempt
        self._current_route_versions[request_id] = route_version
        self._active_output_routes[request_id] = route_version
        self._required_blocks[request_id] = identities
        self._next_output_indices[request_id] = next_output_index
        self._append(
            "BASELINE_ROUTE_STARTED",
            {
                "request_id": request_id,
                "route_version": route_version,
                "target_id": target_id,
                "route_authority": (
                    "external" if self._route_authority is not None else "internal"
                ),
            },
        )
        return attempt

    def track_gpu_allocation(self, gpu_id: str, allocation_id: str) -> None:
        gpu = self._require_gpu(gpu_id)
        if self._gpu_health[gpu_id] is not GPUHealth.HEALTHY:
            raise ValueError("cannot register an allocation on a failed GPU")
        if allocation_id in self._allocation_gpu_ids:
            raise ValueError(f"allocation already belongs to a GPU: {allocation_id}")
        allocation = self.allocation_registry.get(allocation_id)
        if allocation.resource_id not in gpu.hbm_resource_ids:
            raise ValueError("allocation resource is not HBM owned by the physical GPU")
        self._gpu_allocation_ids[gpu_id].add(allocation_id)
        self._allocation_gpu_ids[allocation_id] = gpu_id

    def register_forward(
        self,
        handle: EventHandle,
        *,
        request_id: str,
        route_version: int,
        gpu_id: str,
        cancel_handler: Callable[[str], None] | None = None,
    ) -> None:
        self._register_operation(
            handle,
            kind=OperationKind.FORWARD,
            request_id=request_id,
            route_version=route_version,
            gpu_ids=frozenset((gpu_id,)),
            cancel_handler=cancel_handler,
        )

    def register_transfer(
        self,
        handle: EventHandle,
        *,
        request_id: str,
        route_version: int,
        source_gpu_id: str | None,
        destination_gpu_id: str | None,
        cancel_handler: Callable[[str], None] | None = None,
    ) -> None:
        gpu_ids = frozenset(
            gpu_id for gpu_id in (source_gpu_id, destination_gpu_id) if gpu_id is not None
        )
        if not gpu_ids:
            raise ValueError("a tracked failure-sensitive transfer must touch a GPU")
        self._register_operation(
            handle,
            kind=OperationKind.TRANSFER,
            request_id=request_id,
            route_version=route_version,
            gpu_ids=gpu_ids,
            cancel_handler=cancel_handler,
        )

    def complete_operation(self, handle: EventHandle) -> None:
        if self._in_flight.pop(handle.event_id, None) is None:
            raise KeyError(f"unknown in-flight operation: {handle.event_id}")

    def finish_request(
        self,
        request_id: str,
        route_version: int,
        *,
        terminal_status: str,
    ) -> RouteAttempt:
        """Retire one authoritative route from future failure recovery.

        Scheduler completion and failure-controller route lifetime are separate
        state machines.  The coordinator must close both: otherwise a later GPU
        failure would treat an already-finished request as an affected active
        route and create a spurious reroute/recovery plan.
        """

        if not terminal_status:
            raise ValueError("terminal_status must be non-empty")
        key = (request_id, route_version)
        attempt = self.attempt(request_id, route_version)
        if self._current_route_versions.get(request_id) != route_version:
            raise RecoveryInvariantError("cannot finish a stale route version")
        if attempt.status is not AttemptStatus.ACTIVE:
            raise ValueError("only an active authoritative route may finish")
        if self._active_output_routes.get(request_id) != route_version:
            raise RecoveryInvariantError("finished route is not the active output route")

        finished = replace(attempt, status=AttemptStatus.FINISHED)
        self._attempts[key] = finished
        del self._active_output_routes[request_id]
        self._append(
            "BASELINE_ROUTE_FINISHED",
            {
                "request_id": request_id,
                "route_version": route_version,
                "target_id": attempt.target_id,
                "terminal_status": terminal_status,
                "committed_next_output_index": self._next_output_indices[request_id],
            },
        )
        return finished

    def schedule_gpu_failure(
        self,
        *,
        failure_id: str,
        gpu_id: str,
        at_ns: int,
        detection_delay_ns: int,
        failure_type: str = FailureType.GPU_FAILURE.value,
    ) -> EventHandle:
        if not failure_id:
            raise ValueError("failure_id must be non-empty")
        if failure_type != FailureType.GPU_FAILURE.value:
            raise ValueError("baseline runtime accepts only GPU_FAILURE")
        self._require_gpu(gpu_id)
        if type(at_ns) is not int or at_ns < 0:
            raise ValueError("at_ns must be a non-negative integer")
        if type(detection_delay_ns) is not int or detection_delay_ns < 0:
            raise ValueError("detection_delay_ns must be a non-negative integer")
        return self.des.schedule_at(
            at_ns,
            EventKind.FAILURE_INJECT,
            event_id=f"gpu-failure:{failure_id}:inject",
            payload={
                "failure_id": failure_id,
                "type": failure_type,
                "gpu_id": gpu_id,
                "detection_delay_ns": detection_delay_ns,
            },
        )

    def activate_recovery(self, request_id: str, route_version: int) -> RouteAttempt:
        key = (request_id, route_version)
        attempt = self.attempt(request_id, route_version)
        if attempt.status is not AttemptStatus.RECOVERING:
            raise ValueError("only a recovering route may be atomically activated")
        if self._current_route_versions.get(request_id) != route_version:
            raise RecoveryInvariantError("cannot activate a stale route version")
        if not self.target_is_healthy(attempt.target_id):
            raise RecoveryInvariantError("cannot activate recovery on an unhealthy target")
        if not self._route_is_authoritative(
            request_id,
            route_version,
            attempt.target_id,
        ):
            raise RecoveryInvariantError(
                "cannot activate a route rejected by the external authority"
            )
        expected_plan = self.planner.plan(
            self._required_blocks[request_id],
            unavailable_resource_ids=self._failed_hbm_resource_ids(),
        )
        if expected_plan != self._recovery_plans[key]:
            raise RecoveryInvariantError("recovery source changed before atomic activation")
        replay = self.silent_replay_plan(request_id, route_version)
        if replay.status is not SilentReplayStatus.READY_TO_ACTIVATE:
            raise RecoveryInvariantError(
                "prompt materialization and silent replay must reach the committed "
                "output position before activation"
            )
        cached_output_index = replay.cached_new_output_index
        if cached_output_index is not None and (
            replay.cached_new_output_published
            or self._next_output_indices[request_id] != cached_output_index
        ):
            raise RecoveryInvariantError(
                "cached recovery output does not match the next publishable position"
            )
        activated = replace(attempt, status=AttemptStatus.ACTIVE)
        self._attempts[key] = activated
        activated_replay = replace(
            replay,
            status=SilentReplayStatus.ACTIVATED,
            cached_new_output_published=cached_output_index is not None,
        )
        self._silent_replay_plans[key] = activated_replay
        self._active_output_routes[request_id] = route_version
        self._append(
            "BASELINE_RECOVERY_ACTIVATED",
            {
                "request_id": request_id,
                "route_version": route_version,
                "target_id": attempt.target_id,
                "recovery_plan": expected_plan.to_dict(),
                "silent_replay": activated_replay.to_dict(),
            },
        )
        if cached_output_index is not None:
            output = ActivatedOutput(request_id, route_version, cached_output_index)
            self._emitted_outputs.append(output)
            self._next_output_indices[request_id] = cached_output_index + 1
            self._append("BASELINE_OUTPUT_ACTIVATED", asdict(output))
            self._append(
                "BASELINE_RECOVERY_CACHED_OUTPUT_PUBLISHED",
                {
                    **asdict(output),
                    "externally_emitted": True,
                    "content_contract": activated_replay.content_contract,
                },
            )
            if self._output_sink is not None:
                self._output_sink(output)
        return activated

    def start_silent_replay(
        self,
        request_id: str,
        route_version: int,
    ) -> SilentReplayPlan:
        key = (request_id, route_version)
        attempt = self.attempt(request_id, route_version)
        replay = self.silent_replay_plan(request_id, route_version)
        if attempt.status is not AttemptStatus.RECOVERING:
            raise ValueError("silent replay requires a recovering route")
        if self._current_route_versions.get(request_id) != route_version:
            raise RecoveryInvariantError("cannot start silent replay on a stale route")
        if not self.target_is_healthy(attempt.target_id):
            raise RecoveryInvariantError("cannot start silent replay on an unhealthy target")
        if not self._route_is_authoritative(
            request_id,
            route_version,
            attempt.target_id,
        ):
            raise RecoveryInvariantError("silent replay route is not authoritative")
        if replay.status is not SilentReplayStatus.PLANNED:
            raise ValueError("silent replay was already started")
        started = replace(replay, status=SilentReplayStatus.REPLAYING)
        self._silent_replay_plans[key] = started
        self._append("BASELINE_SILENT_REPLAY_STARTED", started.to_dict())
        return started

    def rollback_silent_replay_start(
        self,
        request_id: str,
        route_version: int,
    ) -> SilentReplayPlan:
        """Undo replay start when recovery preparation fails before any forward.

        This rollback is intentionally unavailable after replay progress or
        route activation.  It exists only so a composed coordinator can retry a
        multi-step preparation after the source scheduler has already released
        its failed request.
        """

        key = (request_id, route_version)
        attempt = self.attempt(request_id, route_version)
        replay = self.silent_replay_plan(request_id, route_version)
        if attempt.status is not AttemptStatus.RECOVERING:
            raise ValueError("silent replay start rollback requires a recovering route")
        if self._current_route_versions.get(request_id) != route_version:
            raise RecoveryInvariantError("cannot roll back silent replay on a stale route")
        if (
            replay.replayed_output_count != 0
            or replay.prompt_materialized
            or replay.cached_new_output_index is not None
        ):
            raise RecoveryInvariantError(
                "cannot roll back silent replay after materialized progress"
            )
        if replay.status is SilentReplayStatus.PLANNED:
            return replay
        if replay.status is not SilentReplayStatus.REPLAYING:
            raise RecoveryInvariantError("cannot roll back activated or fenced silent replay")
        rolled_back = replace(replay, status=SilentReplayStatus.PLANNED)
        self._silent_replay_plans[key] = rolled_back
        self._append("BASELINE_SILENT_REPLAY_START_ROLLED_BACK", rolled_back.to_dict())
        return rolled_back

    def record_silent_replay_output(
        self,
        request_id: str,
        route_version: int,
        *,
        replayed_output_index: int,
    ) -> SilentReplayPlan:
        key = (request_id, route_version)
        attempt = self.attempt(request_id, route_version)
        replay = self.silent_replay_plan(request_id, route_version)
        if attempt.status is not AttemptStatus.RECOVERING:
            raise ValueError("silent replay output requires a recovering route")
        if self._current_route_versions.get(request_id) != route_version:
            raise RecoveryInvariantError("cannot advance silent replay on a stale route")
        if not self.target_is_healthy(attempt.target_id):
            raise RecoveryInvariantError("cannot advance silent replay on an unhealthy target")
        if not self._route_is_authoritative(
            request_id,
            route_version,
            attempt.target_id,
        ):
            raise RecoveryInvariantError("silent replay route is not authoritative")
        if replay.status is not SilentReplayStatus.REPLAYING:
            raise ValueError("silent replay output arrived outside REPLAYING")
        if replayed_output_index != replay.replayed_output_count:
            raise RecoveryInvariantError(
                "silent replay output position is duplicate or discontinuous"
            )
        if replay.remaining_output_count <= 0:
            raise RecoveryInvariantError(
                "silent replay output exceeds the committed output checkpoint"
            )
        advanced_count = replay.replayed_output_count + 1
        status = (
            SilentReplayStatus.READY_TO_ACTIVATE
            if advanced_count == replay.committed_next_output_index
            else SilentReplayStatus.REPLAYING
        )
        advanced = replace(
            replay,
            replayed_output_count=advanced_count,
            status=status,
            prompt_materialized=True,
        )
        self._silent_replay_plans[key] = advanced
        self._append(
            "BASELINE_SILENT_REPLAY_OUTPUT_COMPUTED",
            {
                **advanced.to_dict(),
                "replayed_output_index": replayed_output_index,
                "externally_emitted": False,
            },
        )
        if status is SilentReplayStatus.READY_TO_ACTIVATE:
            self._append("BASELINE_SILENT_REPLAY_READY", advanced.to_dict())
        return advanced

    def record_prompt_materialized_output(
        self,
        request_id: str,
        route_version: int,
        *,
        output_index: int,
    ) -> SilentReplayPlan:
        """Cache output zero after checkpoint-zero prompt materialization."""

        key = (request_id, route_version)
        attempt = self.attempt(request_id, route_version)
        replay = self.silent_replay_plan(request_id, route_version)
        if attempt.status is not AttemptStatus.RECOVERING:
            raise ValueError("prompt materialization requires a recovering route")
        if self._current_route_versions.get(request_id) != route_version:
            raise RecoveryInvariantError("cannot materialize prompt on a stale route")
        if not self.target_is_healthy(attempt.target_id):
            raise RecoveryInvariantError("cannot materialize prompt on an unhealthy target")
        if not self._route_is_authoritative(
            request_id,
            route_version,
            attempt.target_id,
        ):
            raise RecoveryInvariantError("prompt materialization route is not authoritative")
        if replay.status is not SilentReplayStatus.REPLAYING:
            raise ValueError("prompt materialization output arrived outside REPLAYING")
        if (
            replay.committed_next_output_index != 0
            or replay.replayed_output_count != 0
            or replay.prompt_materialized
            or replay.cached_new_output_index is not None
            or output_index != 0
        ):
            raise RecoveryInvariantError(
                "checkpoint-zero prompt materialization must cache output position zero once"
            )
        ready = replace(
            replay,
            prompt_materialized=True,
            cached_new_output_index=output_index,
            status=SilentReplayStatus.READY_TO_ACTIVATE,
        )
        self._silent_replay_plans[key] = ready
        self._append(
            "BASELINE_RECOVERY_PROMPT_MATERIALIZED",
            {
                **ready.to_dict(),
                "output_index": output_index,
                "externally_emitted": False,
            },
        )
        self._append("BASELINE_SILENT_REPLAY_READY", ready.to_dict())
        return ready

    def try_emit_output(
        self,
        *,
        request_id: str,
        route_version: int,
        output_index: int,
    ) -> bool:
        if type(route_version) is not int or route_version < 0:
            raise ValueError("route_version must be a non-negative integer")
        if type(output_index) is not int or output_index < 0:
            raise ValueError("output_index must be a non-negative integer")
        attempt = self._attempts.get((request_id, route_version))
        active_route = self._active_output_routes.get(request_id)
        if (
            attempt is None
            or attempt.status is not AttemptStatus.ACTIVE
            or active_route != route_version
            or not self.target_is_healthy(attempt.target_id)
            or not self._route_is_authoritative(
                request_id,
                route_version,
                "" if attempt is None else attempt.target_id,
            )
        ):
            self._append(
                "BASELINE_OUTPUT_FENCED",
                {
                    "request_id": request_id,
                    "route_version": route_version,
                    "output_index": output_index,
                },
            )
            return False

        expected_index = self._next_output_indices[request_id]
        if output_index < expected_index:
            self._append(
                "BASELINE_DUPLICATE_OUTPUT_SUPPRESSED",
                {
                    "request_id": request_id,
                    "route_version": route_version,
                    "output_index": output_index,
                    "expected_output_index": expected_index,
                },
            )
            return False
        if output_index > expected_index:
            raise RecoveryInvariantError(
                f"output index gap: expected {expected_index}, got {output_index}"
            )

        output = ActivatedOutput(request_id, route_version, output_index)
        self._emitted_outputs.append(output)
        self._next_output_indices[request_id] = expected_index + 1
        self._append("BASELINE_OUTPUT_ACTIVATED", asdict(output))
        if self._output_sink is not None:
            self._output_sink(output)
        return True

    def _register_operation(
        self,
        handle: EventHandle,
        *,
        kind: OperationKind,
        request_id: str,
        route_version: int,
        gpu_ids: frozenset[str],
        cancel_handler: Callable[[str], None] | None,
    ) -> None:
        if not handle.event_id or handle.event_id in self._in_flight:
            raise ValueError("operation EventHandle must be non-empty and unique")
        attempt = self.attempt(request_id, route_version)
        if attempt.status not in {AttemptStatus.ACTIVE, AttemptStatus.RECOVERING}:
            raise ValueError("operation cannot be attached to a fenced route")
        target_gpu_ids = frozenset(self._targets[attempt.target_id].gpu_ids)
        if kind is OperationKind.FORWARD and (
            len(gpu_ids) != 1 or not gpu_ids.issubset(target_gpu_ids)
        ):
            raise ValueError("forward must execute on a GPU in its route target")
        if kind is OperationKind.TRANSFER and not gpu_ids.intersection(target_gpu_ids):
            raise ValueError("transfer must touch a GPU in its route target")
        unknown = set(gpu_ids) - set(self._gpus)
        if unknown:
            raise ValueError(f"operation references unknown GPUs: {sorted(unknown)}")
        if any(self._gpu_health[gpu_id] is GPUHealth.FAILED for gpu_id in gpu_ids):
            raise ValueError("operation cannot use a failed GPU")
        self._in_flight[handle.event_id] = _InFlightOperation(
            handle=handle,
            kind=kind,
            request_id=request_id,
            route_version=route_version,
            gpu_ids=gpu_ids,
            cancel_handler=cancel_handler,
        )

    def _on_failure_inject(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        data = _exact_payload(
            event.payload,
            {"failure_id", "type", "gpu_id", "detection_delay_ns"},
            "FAILURE_INJECT",
        )
        failure_id = _string(data, "failure_id")
        if _string(data, "type") != FailureType.GPU_FAILURE.value:
            raise RecoveryInvariantError("runtime failure type is not GPU_FAILURE")
        gpu_id = _string(data, "gpu_id")
        detection_delay_ns = _integer(data, "detection_delay_ns")
        if detection_delay_ns < 0:
            raise RecoveryInvariantError("detection delay cannot be negative")
        self._require_gpu(gpu_id)
        if self._gpu_health[gpu_id] is GPUHealth.FAILED:
            raise RecoveryInvariantError(f"GPU already failed: {gpu_id}")

        self._gpu_health[gpu_id] = GPUHealth.FAILED
        if self._hbm_failure_handler is not None:
            gpu = self._gpus[gpu_id]
            self._hbm_failure_handler.fail_gpu_hbm(
                gpu_id=gpu_id,
                resource_ids=gpu.hbm_resource_ids,
                failure_id=failure_id,
                timestamp_ns=self.des.now_ns,
            )
        self._lose_gpu_allocations(gpu_id, failure_id)
        affected_routes = tuple(
            sorted(
                (
                    key
                    for key, attempt in self._attempts.items()
                    if attempt.status in {AttemptStatus.ACTIVE, AttemptStatus.RECOVERING}
                    and gpu_id in self._targets[attempt.target_id].gpu_ids
                ),
                key=lambda item: (item[0], item[1]),
            )
        )
        self._failure_routes[failure_id] = affected_routes
        affected_route_set = set(affected_routes)
        for operation_id in sorted(tuple(self._in_flight)):
            operation = self._in_flight[operation_id]
            if (
                gpu_id not in operation.gpu_ids
                and (operation.request_id, operation.route_version) not in affected_route_set
            ):
                continue
            canceled = self.des.cancel(
                operation.handle,
                reason=f"GPU_FAILURE:{failure_id}",
            )
            if operation.cancel_handler is not None:
                operation.cancel_handler(f"GPU_FAILURE:{failure_id}")
            self._append(
                "BASELINE_GPU_OPERATION_CANCELED",
                {
                    "failure_id": failure_id,
                    "gpu_id": gpu_id,
                    "operation_event_id": operation.handle.event_id,
                    "operation_kind": operation.kind.value,
                    "request_id": operation.request_id,
                    "route_version": operation.route_version,
                    "canceled": canceled,
                    "cancel_handler_invoked": operation.cancel_handler is not None,
                },
            )
            self._in_flight.pop(operation_id, None)

        self._append(
            "BASELINE_GPU_FAIL_STOPPED",
            {
                "failure_id": failure_id,
                "gpu_id": gpu_id,
                "affected_routes": [
                    {"request_id": request_id, "route_version": route_version}
                    for request_id, route_version in affected_routes
                ],
            },
        )
        for request_id, route_version in affected_routes:
            self.des.schedule_at(
                self.des.now_ns,
                EventKind.ROUTE_FENCE,
                event_id=(f"gpu-failure:{failure_id}:fence:{request_id}:route-{route_version}"),
                payload={
                    "failure_id": failure_id,
                    "request_id": request_id,
                    "route_version": route_version,
                },
            )
        self.des.schedule_at(
            self.des.now_ns + detection_delay_ns,
            EventKind.FAILURE_DETECT,
            event_id=f"gpu-failure:{failure_id}:detect",
            payload={"failure_id": failure_id, "gpu_id": gpu_id},
        )

    def _on_route_fence(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        data = _exact_payload(
            event.payload,
            {"failure_id", "request_id", "route_version"},
            "ROUTE_FENCE",
        )
        failure_id = _string(data, "failure_id")
        request_id = _string(data, "request_id")
        route_version = _integer(data, "route_version")
        key = (request_id, route_version)
        attempt = self._attempts.get(key)
        if attempt is None:
            raise RecoveryInvariantError("fence references an unknown route")
        if attempt.status in {
            AttemptStatus.FENCED,
            AttemptStatus.RECOVERY_FAILED_NO_TARGET,
        }:
            return
        self._attempts[key] = replace(
            attempt,
            status=AttemptStatus.FENCED,
            failure_id=failure_id,
        )
        if self._active_output_routes.get(request_id) == route_version:
            del self._active_output_routes[request_id]
        replay = self._silent_replay_plans.get(key)
        if replay is not None and replay.status is not SilentReplayStatus.FENCED:
            fenced_replay = replace(replay, status=SilentReplayStatus.FENCED)
            self._silent_replay_plans[key] = fenced_replay
            self._append(
                "BASELINE_SILENT_REPLAY_FENCED",
                {
                    **fenced_replay.to_dict(),
                    "failure_id": failure_id,
                    "previous_status": replay.status.value,
                },
            )
        if self._recovery_fence_sink is not None:
            self._recovery_fence_sink(
                request_id,
                route_version,
                f"GPU_FAILURE:{failure_id}:ROUTE_FENCED",
            )
        self._append(
            "BASELINE_ROUTE_FENCED",
            {
                "failure_id": failure_id,
                "request_id": request_id,
                "route_version": route_version,
                "target_id": attempt.target_id,
            },
        )

    def _on_failure_detect(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        data = _exact_payload(
            event.payload,
            {"failure_id", "gpu_id"},
            "FAILURE_DETECT",
        )
        failure_id = _string(data, "failure_id")
        gpu_id = _string(data, "gpu_id")
        if self._gpu_health.get(gpu_id) is not GPUHealth.FAILED:
            raise RecoveryInvariantError("failure detection requires a failed physical GPU")
        affected_routes = self._failure_routes.get(failure_id)
        if affected_routes is None:
            raise RecoveryInvariantError("failure detection has no injection record")
        self._append(
            "BASELINE_GPU_FAILURE_DETECTED",
            {"failure_id": failure_id, "gpu_id": gpu_id},
        )
        for request_id, route_version in affected_routes:
            attempt = self._attempts[(request_id, route_version)]
            if (
                attempt.status is not AttemptStatus.FENCED
                or self._current_route_versions[request_id] != route_version
            ):
                continue
            self.des.schedule_at(
                self.des.now_ns,
                EventKind.REROUTE,
                event_id=(f"gpu-failure:{failure_id}:reroute:{request_id}:route-{route_version}"),
                payload={
                    "failure_id": failure_id,
                    "request_id": request_id,
                    "old_route_version": route_version,
                },
            )

    def _on_reroute(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        data = _exact_payload(
            event.payload,
            {"failure_id", "request_id", "old_route_version"},
            "REROUTE",
        )
        failure_id = _string(data, "failure_id")
        request_id = _string(data, "request_id")
        old_route_version = _integer(data, "old_route_version")
        old_key = (request_id, old_route_version)
        old_attempt = self._attempts.get(old_key)
        if old_attempt is None:
            raise RecoveryInvariantError("reroute references an unknown route")
        if (
            old_attempt.status is not AttemptStatus.FENCED
            or self._current_route_versions.get(request_id) != old_route_version
        ):
            self._append(
                "BASELINE_STALE_REROUTE_IGNORED",
                {
                    "failure_id": failure_id,
                    "request_id": request_id,
                    "old_route_version": old_route_version,
                },
            )
            return

        decision = self._select_reroute_target(old_attempt)
        if decision is None:
            self._attempts[old_key] = replace(
                old_attempt,
                status=AttemptStatus.RECOVERY_FAILED_NO_TARGET,
            )
            self._append(
                "BASELINE_RECOVERY_FAILED_NO_TARGET",
                {
                    "failure_id": failure_id,
                    "request_id": request_id,
                    "route_version": old_route_version,
                },
            )
            if self._recovery_failure_sink is not None:
                self._recovery_failure_sink(
                    request_id,
                    old_route_version,
                    "RECOVERY_FAILED_NO_TARGET",
                )
            return

        target = self._require_target(decision.target_id)
        new_route_version = decision.route_version
        if new_route_version != old_route_version + 1:
            raise RecoveryInvariantError(
                "route authority must publish exactly the next route version"
            )
        new_key = (request_id, new_route_version)
        if new_key in self._attempts:
            raise RecoveryInvariantError("reroute would reuse a route version")
        plan = self.planner.plan(
            self._required_blocks[request_id],
            unavailable_resource_ids=self._failed_hbm_resource_ids(),
        )
        rerouted = RouteAttempt(
            request_id=request_id,
            route_version=new_route_version,
            target_id=target.target_id,
            status=AttemptStatus.RECOVERING,
            parent_route_version=old_route_version,
            failure_id=failure_id,
        )
        self._attempts[new_key] = rerouted
        self._current_route_versions[request_id] = new_route_version
        self._recovery_plans[new_key] = plan
        replay = SilentReplayPlan(
            request_id=request_id,
            route_version=new_route_version,
            committed_next_output_index=self._next_output_indices[request_id],
            replayed_output_count=0,
            status=SilentReplayStatus.PLANNED,
        )
        self._silent_replay_plans[new_key] = replay
        self._append(
            "BASELINE_REROUTED",
            {
                "failure_id": failure_id,
                "request_id": request_id,
                "old_route_version": old_route_version,
                "new_route_version": new_route_version,
                "target_id": target.target_id,
                "target_dp_rank": target.dp_rank,
                "route_authority": (
                    "external" if self._route_authority is not None else "internal"
                ),
                "authority_fingerprint": decision.authority_fingerprint,
                "recovery_plan": plan.to_dict(),
                "silent_replay": replay.to_dict(),
            },
        )
        self._append("BASELINE_SILENT_REPLAY_PLANNED", replay.to_dict())

    def _on_request_output(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        data = _exact_payload(
            event.payload,
            {"request_id", "route_version", "output_index"},
            "REQUEST_COMPLETE",
        )
        self.try_emit_output(
            request_id=_string(data, "request_id"),
            route_version=_integer(data, "route_version"),
            output_index=_integer(data, "output_index"),
        )

    def _lose_gpu_allocations(self, gpu_id: str, failure_id: str) -> None:
        for allocation_id in sorted(self._gpu_allocation_ids[gpu_id]):
            allocation = self.allocation_registry.get(allocation_id)
            overlay = self.allocation_registry.overlay(allocation_id)
            for pin_index in range(overlay.source_pin_count):
                self.allocation_registry.unpin_source(
                    allocation_id,
                    timestamp_ns=self.des.now_ns,
                    event_id=f"{failure_id}:unpin:{allocation_id}:{pin_index}",
                )
            if self.allocation_registry.overlay(allocation_id).recovery_eligible:
                self.allocation_registry.set_recovery_eligible(
                    allocation_id,
                    False,
                    timestamp_ns=self.des.now_ns,
                    event_id=f"{failure_id}:ineligible:{allocation_id}",
                )
            for role in sorted(allocation.roles, key=lambda item: item.value):
                self.allocation_registry.remove_role(
                    allocation_id,
                    role,
                    timestamp_ns=self.des.now_ns,
                    event_id=f"{failure_id}:remove-role:{allocation_id}:{role.value}",
                )
            if allocation.state not in {AllocationState.LOST, AllocationState.RELEASED}:
                self.allocation_registry.transition(
                    allocation_id,
                    AllocationState.LOST,
                    timestamp_ns=self.des.now_ns,
                    event_id=f"{failure_id}:lost:{allocation_id}",
                )
            try:
                replica = self.directory.get_replica(allocation.replica_id)
            except KeyError:
                continue
            if replica.state.terminal:
                continue
            terminal_state = (
                ReplicaState.ABORTED
                if replica.state is ReplicaState.ALLOCATED
                else ReplicaState.LOST
            )
            self.directory.update_replica(replica.terminate(terminal_state))

    def _select_reroute_target(
        self,
        old_attempt: RouteAttempt,
    ) -> RerouteDecision | None:
        old_target = self._require_target(old_attempt.target_id)
        compatible_targets = tuple(
            sorted(
                (
                    target
                    for target in self._targets.values()
                    if target.compatibility_key == old_target.compatibility_key
                ),
                key=lambda item: (item.dp_rank, item.target_id),
            )
        )
        healthy_target_ids = frozenset(
            target.target_id
            for target in compatible_targets
            if target.target_id != old_target.target_id and self.target_is_healthy(target.target_id)
        )
        if self._route_authority is not None:
            decision = self._route_authority.reroute(
                current=old_attempt,
                compatible_targets=compatible_targets,
                healthy_target_ids=healthy_target_ids,
                now_ns=self.des.now_ns,
            )
            if decision is None:
                return None
            if decision.target_id not in healthy_target_ids:
                raise RecoveryInvariantError(
                    "external route authority selected an unhealthy or incompatible target"
                )
            return decision

        candidates = [
            target for target in compatible_targets if target.target_id in healthy_target_ids
        ]
        selected = min(
            candidates,
            key=lambda item: (item.dp_rank, item.target_id),
            default=None,
        )
        if selected is None:
            return None
        return RerouteDecision(
            target_id=selected.target_id,
            route_version=old_attempt.route_version + 1,
        )

    def _route_is_authoritative(
        self,
        request_id: str,
        route_version: int,
        target_id: str,
    ) -> bool:
        if self._route_authority is None:
            return True
        if not target_id:
            return False
        return self._route_authority.is_authoritative(
            request_id=request_id,
            route_version=route_version,
            target_id=target_id,
        )

    def _failed_hbm_resource_ids(self) -> frozenset[str]:
        return frozenset(
            resource_id
            for gpu_id, health in self._gpu_health.items()
            if health is GPUHealth.FAILED
            for resource_id in self._gpus[gpu_id].hbm_resource_ids
        )

    def _require_gpu(self, gpu_id: str) -> PhysicalGPU:
        try:
            return self._gpus[gpu_id]
        except KeyError as error:
            raise KeyError(f"unknown physical GPU: {gpu_id}") from error

    def _require_target(self, target_id: str) -> EngineTarget:
        try:
            return self._targets[target_id]
        except KeyError as error:
            raise KeyError(f"unknown engine target: {target_id}") from error

    def _append(self, record_type: str, data: dict[str, Any]) -> None:
        self.des.journal.append(self.des.now_ns, record_type, data)


def _validate_required_blocks(identities: tuple[KVIdentity, ...]) -> None:
    if not identities:
        return
    if identities[0].token_start != 0:
        raise ValueError("recovery blocks must start at token zero")
    compatibility_key = identities[0].compatibility_key
    previous_end = 0
    for identity in identities:
        if identity.compatibility_key != compatibility_key:
            raise ValueError("recovery blocks must have one compatible KV layout and shard")
        if identity.token_start != previous_end:
            raise ValueError("recovery blocks must form one continuous token interval")
        previous_end = identity.token_end


def _exact_payload(
    payload: Mapping[str, Any], expected_keys: set[str], event_name: str
) -> Mapping[str, Any]:
    actual_keys = set(payload)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(repr(key) for key in actual_keys - expected_keys)
        raise RecoveryInvariantError(
            f"{event_name} payload mismatch: missing={missing}, unknown={unknown}"
        )
    return payload


def _string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise RecoveryInvariantError(f"{key} must be a non-empty string")
    return value


def _integer(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if type(value) is not int:
        raise RecoveryInvariantError(f"{key} must be an integer")
    return value
