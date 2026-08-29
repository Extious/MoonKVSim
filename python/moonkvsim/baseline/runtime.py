"""One-clock composition of the tensor-free vanilla MoonKVSim baseline.

The coordinator connects existing source-aligned state machines; it does not
replace them with aggregate delays.  Two DP ranks retain independent vLLM
schedulers, one external :class:`DPRouter` owns route selection, Store metadata
remains owned by :class:`MasterService`, and every byte moves as
``TransferTask`` slices through ``FlowDESController``.

This module demonstrates E2 toy semantics only.  Durations and payload sizes
are synthetic, no tensors execute, and no physical performance claim follows.
Host-staged and concurrency-limited paths require a caller-supplied per-task
resource plan.  The plan reserves only staging capacity and calendar lanes;
actual bytes still move as FlowDES slices on the one ``GlobalDES`` clock.
When configured, endpoint registration/lookup first consumes its own named
worker resource and completes through independent DES events; it is never
folded into a forward duration or a transfer-flow aggregate.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

from moonkvsim.common.hash import sha256_json
from moonkvsim.common.types import KVIdentity
from moonkvsim.integration.vllm.hbm_block_ledger import (
    HBM_RECOVERY_RESERVED_ACCOUNT,
)
from moonkvsim.integration.vllm.request import Request, RequestStatus
from moonkvsim.integration.vllm.router import (
    DPReplicaSnapshot,
    DPRouter,
    NoHealthyReplicaError,
    RouteAuthority,
    RoutePolicy,
    RouterError,
)
from moonkvsim.integration.vllm.scheduler import (
    ContinuousBatchScheduler,
    RecoveryPrefixReservation,
    ScheduledRequest,
    SchedulerOutput,
    SchedulingPhase,
)
from moonkvsim.recovery.baseline import (
    ActivatedOutput,
    AtomicGPUHBMFailStop,
    AttemptStatus,
    BaselineGPUFailureController,
    EngineTarget,
    GPUHBMFailureObserver,
    PhysicalGPU,
    RecoveryInvariantError,
    RecoveryPlan,
    RerouteDecision,
    RouteAttempt,
    SilentReplayPlan,
    SilentReplayStatus,
)
from moonkvsim.simulation.allocation import AllocationState
from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.store.client import (
    GetOperation,
    GetOperationState,
    PutOperation,
    PutOperationState,
    StoreClient,
)
from moonkvsim.store.endpoint import EndpointRegistrationManager
from moonkvsim.store.master import MasterService
from moonkvsim.store.replica import Replica
from moonkvsim.store.transfer_engine import (
    TransferStatus,
    TransferTask,
    TransportKind,
)
from moonkvsim.store.transfer_resources import (
    StagingAllocationSpec,
    TransferLeaseOutcome,
    TransferLeaseStatus,
    TransferResourceLeaseManager,
)
from moonkvsim.store.transfer_runtime import TransferRuntime

EVIDENCE_BOUNDARY: Final = "E2_toy_composed_baseline_semantics_only"
FIDELITY_GAPS: Final[tuple[str, ...]] = (
    "physical_timing_and_tensor_execution_are_not_measured",
    "transfer_duration_and_staged_copy_overlap_are_uncalibrated",
    "external_vllm_and_mooncake_differential_traces_remain_open",
    "physical_endpoint_registration_and_qp_handshake_are_not_executed",
)

SnapshotProvider = Callable[[int], Iterable[DPReplicaSnapshot]]
TransferTerminalCallback = Callable[[TransferTask, GlobalDES], None]
ForwardTerminalCallback = Callable[[ScheduledEvent, GlobalDES], None]


@dataclass(frozen=True, slots=True)
class ForwardBatchParticipant:
    """One route-versioned participant in a physical forward batch."""

    request_id: str
    route_version: int
    target_id: str
    produces_output: bool
    output_index: int | None

    def __post_init__(self) -> None:
        if not self.request_id or not self.target_id:
            raise ValueError("forward-batch request and target IDs must be non-empty")
        if type(self.route_version) is not int or self.route_version < 0:
            raise ValueError("forward-batch route_version must be non-negative")
        if type(self.produces_output) is not bool:
            raise TypeError("forward-batch produces_output must be boolean")
        if self.output_index is not None and (
            type(self.output_index) is not int or self.output_index < 0
        ):
            raise ValueError("forward-batch output_index must be absent or non-negative")
        if self.produces_output != (self.output_index is not None):
            raise ValueError(
                "forward-batch output_index must be present exactly when output is produced"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "route_version": self.route_version,
            "target_id": self.target_id,
            "produces_output": self.produces_output,
            "output_index": self.output_index,
        }


@dataclass(frozen=True, slots=True)
class ForwardBatchTerminal:
    """Atomic completion decision delivered once for a whole physical batch."""

    event_id: str
    replica_id: str
    participants: tuple[ForwardBatchParticipant, ...]
    accepted: bool
    fence_reason: str | None

    def __post_init__(self) -> None:
        if not self.event_id or not self.replica_id or not self.participants:
            raise ValueError("forward-batch terminal identity must be complete")
        if self.accepted != (self.fence_reason is None):
            raise ValueError("forward-batch acceptance and fence reason disagree")

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "replica_id": self.replica_id,
            "participants": [item.to_dict() for item in self.participants],
            "accepted": self.accepted,
            "fence_reason": self.fence_reason,
        }


ForwardBatchTerminalCallback = Callable[[ForwardBatchTerminal, GlobalDES], None]


class BaselineCoordinatorError(RuntimeError):
    """Raised when component state cannot be composed without ambiguity."""


@dataclass(frozen=True, slots=True)
class TransferTaskResourcePlan:
    """Explicit lease inputs for exactly one Store transfer task.

    ``duration_ns`` is a fail-closed calendar bound, not an aggregate transfer
    delay.  FlowDES continues to determine completion from the task's slices and
    rate-resource path.  ``latest_start_ns`` is the last admissible lease start;
    every Host staging allocation is supplied with fully explained geometry.
    """

    duration_ns: int
    staging_specs: tuple[StagingAllocationSpec, ...] = ()
    latest_start_ns: int | None = None

    def __post_init__(self) -> None:
        if type(self.duration_ns) is not int or self.duration_ns <= 0:
            raise ValueError("resource-plan duration_ns must be a positive integer")
        if self.latest_start_ns is not None and (
            type(self.latest_start_ns) is not int or self.latest_start_ns < 0
        ):
            raise ValueError("resource-plan latest_start_ns must be non-negative")
        if not isinstance(self.staging_specs, tuple) or any(
            not isinstance(spec, StagingAllocationSpec) for spec in self.staging_specs
        ):
            raise TypeError("resource-plan staging_specs must be a tuple of specs")
        resource_ids = [spec.resource_id for spec in self.staging_specs]
        if len(set(resource_ids)) != len(resource_ids):
            raise ValueError("resource-plan staging resource IDs must be unique")

    def staging_specs_by_resource(self) -> dict[str, StagingAllocationSpec]:
        return {spec.resource_id: spec for spec in self.staging_specs}


TaskResourcePlanProvider = Callable[[TransferTask], TransferTaskResourcePlan | None]


@dataclass(frozen=True, slots=True)
class BaselineReplicaRuntime:
    """Independent scheduler and Store client for one external DP target."""

    replica_id: str
    dp_rank: int
    scheduler_id: str
    gpu_id: str
    scheduler: ContinuousBatchScheduler
    store_client: StoreClient

    def __post_init__(self) -> None:
        if not self.replica_id or not self.scheduler_id or not self.gpu_id:
            raise ValueError("replica, scheduler, and GPU IDs must be non-empty")
        if self.dp_rank < 0:
            raise ValueError("dp_rank must be non-negative")
        if self.store_client.local_gpu.gpu_id != self.gpu_id:
            raise ValueError("Store client GPU must match the DP runtime GPU")


@dataclass(slots=True)
class _TransferLaunch:
    client: StoreClient
    task: TransferTask
    request_id: str
    resource_plan: TransferTaskResourcePlan | None
    terminal_callback: TransferTerminalCallback | None = None
    operation_handle: EventHandle | None = None
    endpoint_preparation_id: str | None = None
    lease_id: str | None = None
    start_handle: EventHandle | None = None
    started: bool = False
    failure_canceling: bool = False
    reconciled: bool = False


@dataclass(slots=True)
class _SilentReplayForward:
    """One scheduler mutation awaiting a physical replay-forward terminal."""

    request_id: str
    route_version: int
    scheduled: ScheduledRequest
    handle: EventHandle | None = None


class DPRouterAuthorityAdapter:
    """Make ``DPRouter`` the sole route selector used by failure recovery."""

    def __init__(
        self,
        *,
        router: DPRouter,
        snapshot_provider: SnapshotProvider,
    ) -> None:
        if router.policy is RoutePolicy.CACHE_AWARE:
            raise ValueError("the baseline recovery adapter has no implicit Store cache signals")
        self.router = router
        self.snapshot_provider = snapshot_provider

    def is_authoritative(
        self,
        *,
        request_id: str,
        route_version: int,
        target_id: str,
    ) -> bool:
        try:
            self.router.require_route(
                request_id,
                route_version=route_version,
                target_replica_id=target_id,
            )
        except RouterError:
            return False
        return True

    def reroute(
        self,
        *,
        current: RouteAttempt,
        compatible_targets: tuple[EngineTarget, ...],
        healthy_target_ids: frozenset[str],
        now_ns: int,
    ) -> RerouteDecision | None:
        target_ids = {target.target_id for target in compatible_targets}
        supplied = tuple(self.snapshot_provider(now_ns))
        snapshot_by_id = {snapshot.replica_id: snapshot for snapshot in supplied}
        if len(snapshot_by_id) != len(supplied):
            raise BaselineCoordinatorError("DP snapshot replica IDs are not unique")
        missing = target_ids - snapshot_by_id.keys()
        if missing:
            raise BaselineCoordinatorError(
                f"route authority is missing compatible DP snapshots: {sorted(missing)}"
            )
        replicas = tuple(
            replace(
                snapshot_by_id[target.target_id],
                healthy=target.target_id in healthy_target_ids,
                observed_at_ns=now_ns,
            )
            for target in compatible_targets
        )
        latest = self.router.current_authority(current.request_id)
        if (
            latest.route_version != current.route_version
            or latest.target_replica_id != current.target_id
        ):
            raise BaselineCoordinatorError(
                "failure controller route mirror diverged from DPRouter authority"
            )
        failed = tuple(sorted(target_ids - healthy_target_ids))
        try:
            authority = self.router.reroute(
                latest,
                replicas=replicas,
                failed_replica_ids=failed,
            )
        except NoHealthyReplicaError:
            return None
        return RerouteDecision(
            target_id=authority.target_replica_id,
            route_version=authority.route_version,
            authority_fingerprint=authority.fingerprint,
        )


class BaselineCoordinator:
    """Compose router, independent schedulers, Store, flow DES, and recovery."""

    def __init__(
        self,
        *,
        des: GlobalDES,
        router: DPRouter,
        replicas: Iterable[BaselineReplicaRuntime],
        master: MasterService,
        transfer_runtime: TransferRuntime,
        transfer_resource_manager: TransferResourceLeaseManager | None = None,
        endpoint_registration_manager: EndpointRegistrationManager | None = None,
        gpus: Iterable[PhysicalGPU],
        targets: Iterable[EngineTarget],
        hbm_ledgers: Mapping[str, CapacityLedger] | None = None,
        hbm_failure_observers: Iterable[GPUHBMFailureObserver] = (),
        output_sink: Callable[[ActivatedOutput], None] | None = None,
    ) -> None:
        replica_items = tuple(replicas)
        gpu_items = tuple(gpus)
        target_items = tuple(targets)
        self.des = des
        self.router = router
        self.master = master
        self.transfer_runtime = transfer_runtime
        self.transfer_resource_manager = transfer_resource_manager
        self.endpoint_registration_manager = endpoint_registration_manager
        self._replicas = {item.replica_id: item for item in replica_items}
        self._targets = {item.target_id: item for item in target_items}
        if not replica_items or len(self._replicas) != len(replica_items):
            raise ValueError("DP replica IDs must be non-empty and unique")
        if len({item.dp_rank for item in replica_items}) != len(replica_items):
            raise ValueError("DP ranks must be unique")
        if len({item.scheduler_id for item in replica_items}) != len(replica_items):
            raise ValueError("scheduler IDs must be unique")
        if set(self._targets) != set(self._replicas):
            raise ValueError("engine target IDs must exactly match DP replica IDs")
        for replica in replica_items:
            target = self._targets[replica.replica_id]
            if target.dp_rank != replica.dp_rank or replica.gpu_id not in target.gpu_ids:
                raise ValueError("DP runtime and engine target topology diverge")
            if replica.store_client.master is not master:
                raise ValueError("every Store client must share the one Master")
        if master.journal is not des.journal:
            raise ValueError("Master and GlobalDES must share one journal")
        if transfer_runtime.des is not des:
            raise ValueError("TransferRuntime and coordinator must share one GlobalDES")
        if transfer_resource_manager is not None and transfer_resource_manager.des is not des:
            raise ValueError("transfer resource manager and coordinator must share one GlobalDES")
        if (
            endpoint_registration_manager is not None
            and endpoint_registration_manager.des is not des
        ):
            raise ValueError(
                "endpoint registration manager and coordinator must share one GlobalDES"
            )

        hbm_ledger_map = dict(hbm_ledgers or {})
        hbm_observer_items = tuple(hbm_failure_observers)
        self._hbm_failure_handler = self._build_hbm_failure_handler(
            gpu_items=gpu_items,
            replica_items=replica_items,
            hbm_ledgers=hbm_ledger_map,
            observers=hbm_observer_items,
        )
        self._allocation_ledgers = dict(master.ledgers)
        for resource_id, ledger in hbm_ledger_map.items():
            if resource_id in self._allocation_ledgers:
                raise ValueError(f"Store and HBM ledgers reuse one resource ID: {resource_id}")
            self._allocation_ledgers[resource_id] = ledger
        master.allocation_registry.audit(self._allocation_ledgers)

        self.route_authority = DPRouterAuthorityAdapter(
            router=router,
            snapshot_provider=self._snapshot_replicas,
        )
        self.failure_controller = BaselineGPUFailureController(
            des=des,
            directory=master.directory,
            allocation_registry=master.allocation_registry,
            gpus=gpu_items,
            targets=target_items,
            output_sink=output_sink,
            recovery_failure_sink=self._on_recovery_failed_no_target,
            recovery_fence_sink=self._on_recovery_route_fenced,
            route_authority=self.route_authority,
            hbm_failure_handler=self._hbm_failure_handler,
        )
        self._requests: dict[tuple[str, int], Request] = {}
        self._authorities: dict[tuple[str, int], RouteAuthority] = {}
        self._recovery_gets: dict[tuple[str, int], tuple[GetOperation, ...]] = {}
        self._recovery_fetch_sequences: dict[tuple[str, int], int] = {}
        self._recovery_reservations: dict[tuple[str, int], RecoveryPrefixReservation] = {}
        self._aborting_recovery_fetches: set[tuple[str, int]] = set()
        self._prepared_recoveries: set[tuple[str, int]] = set()
        self._silent_replay_forwards: dict[tuple[str, int], _SilentReplayForward] = {}
        self._silent_replay_sequence = 0
        self._started_tasks: dict[str, TransferTask] = {}
        self._transfer_launches: dict[str, _TransferLaunch] = {}
        self._forward_terminal_callbacks: dict[str, ForwardTerminalCallback] = {}
        self._forward_batch_terminal_callbacks: dict[str, ForwardBatchTerminalCallback] = {}
        self._forward_batch_sequence = 0
        des.register_handler(EventKind.TRANSFER_START, self._on_transfer_start)
        des.register_handler(EventKind.FORWARD_COMPLETE, self._on_forward_complete)
        self._append(
            "BASELINE_COORDINATOR_CREATED",
            {
                "router_id": router.router_id,
                "replica_ids": sorted(self._replicas),
                "hbm_fail_stop_integrated": self.hbm_fail_stop_integrated,
                "hbm_resource_ids": sorted(hbm_ledger_map),
                "endpoint_registration_integrated": endpoint_registration_manager is not None,
                "evidence_boundary": EVIDENCE_BOUNDARY,
                "fidelity_gaps": list(FIDELITY_GAPS),
            },
        )

    @property
    def hbm_fail_stop_integrated(self) -> bool:
        return self._hbm_failure_handler is not None

    @property
    def allocation_ledgers(self) -> dict[str, CapacityLedger]:
        """Return the exact Store/HBM ledger graph covered by the shared registry."""

        return dict(self._allocation_ledgers)

    def _build_hbm_failure_handler(
        self,
        *,
        gpu_items: tuple[PhysicalGPU, ...],
        replica_items: tuple[BaselineReplicaRuntime, ...],
        hbm_ledgers: Mapping[str, CapacityLedger],
        observers: tuple[GPUHBMFailureObserver, ...],
    ) -> AtomicGPUHBMFailStop | None:
        if not hbm_ledgers and not observers:
            return None
        if not hbm_ledgers or not observers:
            raise ValueError("HBM fail-stop requires both physical ledgers and logical observers")

        expected_resource_ids = {
            resource_id for gpu in gpu_items for resource_id in gpu.hbm_resource_ids
        }
        if set(hbm_ledgers) != expected_resource_ids:
            raise ValueError("PhysicalGPU HBM resources must exactly match fail-stop ledgers")
        for resource_id, ledger in hbm_ledgers.items():
            if ledger.resource_id != resource_id:
                raise ValueError("HBM ledger mapping key differs from its resource ID")
            if ledger.resource_kind is not CapacityResourceKind.GPU_HBM:
                raise ValueError(f"failure ledger is not GPU HBM: {resource_id}")

        scheduler_observers = tuple(
            runtime.scheduler.block_lifecycle_observer for runtime in replica_items
        )
        if any(observer is None for observer in scheduler_observers):
            raise ValueError("every failure-bearing scheduler requires an HBM lifecycle observer")
        if len({id(observer) for observer in scheduler_observers}) != len(scheduler_observers):
            raise ValueError("one HBM observer cannot own two baseline schedulers")
        if {id(observer) for observer in scheduler_observers} != {
            id(observer) for observer in observers
        }:
            raise ValueError(
                "HBM failure observers must exactly match scheduler lifecycle observers"
            )

        gpu_by_id = {gpu.gpu_id: gpu for gpu in gpu_items}
        observer_by_id = {id(observer): observer for observer in observers}
        for runtime in replica_items:
            scheduler_observer = runtime.scheduler.block_lifecycle_observer
            if scheduler_observer is None:
                raise ValueError(
                    "every failure-bearing scheduler requires an HBM lifecycle observer"
                )
            observer = observer_by_id[id(scheduler_observer)]
            target = self._targets[runtime.replica_id]
            unknown_gpu_ids = set(target.gpu_ids) - gpu_by_id.keys()
            if unknown_gpu_ids:
                raise ValueError(
                    f"engine target references unknown GPUs: {sorted(unknown_gpu_ids)}"
                )
            target_resource_ids = {
                resource_id
                for gpu_id in target.gpu_ids
                for resource_id in gpu_by_id[gpu_id].hbm_resource_ids
            }
            if set(observer.hbm_resource_ids) != target_resource_ids:
                raise ValueError(
                    "scheduler HBM observer does not match its engine target failure domain: "
                    f"target={runtime.replica_id}"
                )

        observed_resource_ids: set[str] = set()
        registry = self.master.allocation_registry
        for observer in observers:
            if observer.registry is not registry:
                raise ValueError("Store and every HBM observer must share one registry")
            if observer.journal is not self.des.journal:
                raise ValueError("HBM observer and coordinator must share one journal")
            resource_ids = set(observer.hbm_resource_ids)
            if not resource_ids:
                raise ValueError("HBM failure observer has an empty failure domain")
            duplicate = observed_resource_ids & resource_ids
            if duplicate:
                raise ValueError(
                    f"HBM resources have multiple logical observers: {sorted(duplicate)}"
                )
            if set(observer.ledgers) != resource_ids:
                raise ValueError("HBM observer ledger set differs from its failure resource set")
            for resource_id in resource_ids:
                if observer.ledgers[resource_id] is not hbm_ledgers.get(resource_id):
                    raise ValueError("HBM observer and coordinator must share each ledger object")
            observed_resource_ids.update(resource_ids)
        if observed_resource_ids != expected_resource_ids:
            raise ValueError(
                "HBM observers must cover every PhysicalGPU failure resource exactly once"
            )

        combined_ledgers = dict(self.master.ledgers)
        for resource_id, ledger in hbm_ledgers.items():
            if resource_id in combined_ledgers:
                raise ValueError(f"Store and HBM ledgers reuse one resource ID: {resource_id}")
            combined_ledgers[resource_id] = ledger
        return AtomicGPUHBMFailStop(
            ledgers=combined_ledgers,
            registry=registry,
            journal=self.des.journal,
            observers=observers,
        )

    def route_and_admit(
        self,
        request: Request,
        *,
        required_blocks: Sequence[KVIdentity],
    ) -> RouteAuthority:
        """Route once, mirror authority into recovery, and admit one scheduler."""

        if request.route_version != 0:
            raise ValueError("initial request route_version must be zero")
        if request.arrival_ns != self.des.now_ns:
            raise ValueError("request arrival must equal the GlobalDES clock")
        if any(key[0] == request.request_id for key in self._requests):
            raise ValueError("request_id is already known to the coordinator")
        validated_blocks = self.failure_controller.planner.validate_required_blocks(required_blocks)
        authority = self.router.route(
            request_id=request.request_id,
            replicas=self._snapshot_replicas(self.des.now_ns),
        )
        runtime = self._replicas[authority.target_replica_id]
        self.failure_controller.begin_request(
            request_id=request.request_id,
            target_id=authority.target_replica_id,
            required_blocks=validated_blocks,
            route_version=authority.route_version,
        )
        runtime.scheduler.add_request(request)
        key = (request.request_id, authority.route_version)
        self._requests[key] = request
        self._authorities[key] = authority
        self._append(
            "BASELINE_REQUEST_ADMITTED",
            {
                "request_id": request.request_id,
                "route_version": authority.route_version,
                "target_id": authority.target_replica_id,
                "scheduler_id": authority.target_scheduler_id,
                "authority_fingerprint": authority.fingerprint,
            },
        )
        return authority

    def run_scheduler_step(self, request_id: str) -> SchedulerOutput:
        authority = self.router.current_authority(request_id)
        self.router.require_authority(authority)
        attempt = self.failure_controller.attempt(request_id, authority.route_version)
        if attempt.status is not AttemptStatus.ACTIVE:
            raise BaselineCoordinatorError("scheduler step requires an active route")
        runtime = self._replicas[authority.target_replica_id]
        output = runtime.scheduler.schedule()
        if request_id not in output.scheduled_req_ids:
            raise BaselineCoordinatorError(
                "the requested route made no progress in its scheduler step"
            )
        self._append(
            "BASELINE_SCHEDULER_STEP",
            {
                "request_id": request_id,
                "route_version": authority.route_version,
                "target_id": authority.target_replica_id,
                "scheduler_id": authority.target_scheduler_id,
                **_compact_scheduler_output(output),
            },
        )
        return output

    def start_store_put(
        self,
        request_id: str,
        identity: KVIdentity,
        *,
        put_id: str,
        payload_bytes: int,
        preferred_segment_ids: tuple[str, ...] = (),
        resource_plan: TransferTaskResourcePlan | None = None,
        resource_plan_provider: TaskResourcePlanProvider | None = None,
        terminal_callback: TransferTerminalCallback | None = None,
    ) -> PutOperation:
        if resource_plan is not None and resource_plan_provider is not None:
            raise ValueError("resource_plan and resource_plan_provider are mutually exclusive")
        authority = self.router.current_authority(request_id)
        self.router.require_authority(authority)
        runtime = self._replicas[authority.target_replica_id]
        if (
            identity.request_id != request_id
            or identity.route_version != authority.route_version
            or identity.source_gpu_id != runtime.gpu_id
        ):
            raise BaselineCoordinatorError("Store Put identity is stale or on the wrong GPU")
        operation = runtime.store_client.put_start(
            identity,
            put_id=put_id,
            payload_bytes=payload_bytes,
            replica_count=1,
            ready_ns=self.des.now_ns,
            cause="BASELINE_E2_DP_TO_SHARED_STORE",
            preferred_segment_ids=preferred_segment_ids,
        )
        try:
            [task] = operation.batch.tasks
            resolved_resource_plan = (
                resource_plan if resource_plan_provider is None else resource_plan_provider(task)
            )
            self._schedule_transfer(
                runtime.store_client,
                task,
                request_id=request_id,
                resource_plan=resolved_resource_plan,
                terminal_callback=terminal_callback,
            )
        except Exception:
            if operation.state is PutOperationState.PENDING:
                runtime.store_client.abort_put(
                    put_id,
                    timestamp_ns=self.des.now_ns,
                    reason="BASELINE_COORDINATOR_TRANSFER_PREFLIGHT_FAILED",
                )
            raise
        return operation

    def start_store_get(
        self,
        request_id: str,
        identity: KVIdentity,
        *,
        get_id: str,
        resource_plan: TransferTaskResourcePlan | None = None,
        resource_plan_provider: TaskResourcePlanProvider | None = None,
        terminal_callback: TransferTerminalCallback | None = None,
    ) -> GetOperation:
        """Start one ordinary committed-Store prefix fetch for the current route.

        This is the normal-path counterpart of the recovery fetch helper.  It
        retains the same metadata-before-data ordering and routes the resulting
        task through the coordinator-owned FlowDES/resource-lease bridge.
        Callers remain responsible for waiting for the terminal callback before
        materializing the restored scheduler prefix.
        """

        if resource_plan is not None and resource_plan_provider is not None:
            raise ValueError("resource_plan and resource_plan_provider are mutually exclusive")
        authority = self.router.current_authority(request_id)
        self.router.require_authority(authority)
        runtime = self._replicas[authority.target_replica_id]
        if (
            identity.request_id != request_id
            or identity.route_version != authority.route_version
            or identity.source_gpu_id != runtime.gpu_id
        ):
            raise BaselineCoordinatorError("Store Get identity is stale or on the wrong GPU")
        operation = runtime.store_client.get_start(
            identity,
            get_id=get_id,
            ready_ns=self.des.now_ns,
            cause="BASELINE_E2_SHARED_STORE_PREFIX_REUSE",
        )
        try:
            [task] = operation.batch.tasks
            resolved_resource_plan = (
                resource_plan if resource_plan_provider is None else resource_plan_provider(task)
            )
            self._schedule_transfer(
                runtime.store_client,
                task,
                request_id=request_id,
                resource_plan=resolved_resource_plan,
                terminal_callback=terminal_callback,
            )
        except Exception:
            if operation.state is GetOperationState.PENDING:
                for task in operation.batch.tasks:
                    if not task.status.terminal:
                        task.cancel_remaining(
                            timestamp_ns=self.des.now_ns,
                            reason="BASELINE_COORDINATOR_GET_PREFLIGHT_FAILED",
                        )
                        runtime.store_client.reconcile_transfer_terminal(
                            task.metadata.transfer_id,
                            timestamp_ns=self.des.now_ns,
                        )
            raise
        return operation

    def query_store(
        self,
        *,
        replica_id: str,
        identity: KVIdentity,
    ) -> tuple[Replica, ...]:
        return self._replicas[replica_id].store_client.get_replica_list(identity)

    def schedule_gpu_failure(
        self,
        *,
        failure_id: str,
        gpu_id: str,
        at_ns: int,
        detection_delay_ns: int = 0,
    ) -> EventHandle:
        if not self.hbm_fail_stop_integrated:
            raise BaselineCoordinatorError(
                "GPU_FAILURE requires the complete shared-registry HBM fail-stop topology"
            )
        return self.failure_controller.schedule_gpu_failure(
            failure_id=failure_id,
            gpu_id=gpu_id,
            at_ns=at_ns,
            detection_delay_ns=detection_delay_ns,
        )

    def abort_transfer(self, transfer_id: str, *, reason: str) -> None:
        """Abort one queued or active Store transfer and reconcile it once."""

        if not reason:
            raise ValueError("transfer abort reason must be non-empty")
        try:
            launch = self._transfer_launches[transfer_id]
        except KeyError as error:
            raise KeyError(f"unknown baseline transfer: {transfer_id}") from error
        self._abort_launch(
            launch,
            reason=reason,
            outcome=TransferLeaseOutcome.ABORTED,
        )

    def schedule_forward_completion(
        self,
        request_id: str,
        *,
        at_ns: int,
        output_index: int | None,
        produces_output: bool = True,
        terminal_callback: ForwardTerminalCallback | None = None,
    ) -> EventHandle:
        if type(produces_output) is not bool:
            raise TypeError("produces_output must be boolean")
        if produces_output != (output_index is not None):
            raise ValueError("output_index must be present exactly when forward produces output")
        authority = self.router.current_authority(request_id)
        self.router.require_authority(authority)
        runtime = self._replicas[authority.target_replica_id]
        handle = self.des.schedule_at(
            at_ns,
            EventKind.FORWARD_COMPLETE,
            event_id=(
                f"baseline-forward:{request_id}:route-{authority.route_version}:"
                f"output-{output_index}"
            ),
            payload={
                "request_id": request_id,
                "route_version": authority.route_version,
                "produces_output": produces_output,
                "output_index": output_index,
            },
        )
        self.failure_controller.register_forward(
            handle,
            request_id=request_id,
            route_version=authority.route_version,
            gpu_id=runtime.gpu_id,
        )
        if terminal_callback is not None:
            self._forward_terminal_callbacks[handle.event_id] = terminal_callback
        return handle

    def schedule_forward_batch_completion(
        self,
        request_ids: Sequence[str],
        *,
        at_ns: int,
        produces_outputs: Mapping[str, bool],
        output_indices: Mapping[str, int | None],
        terminal_callback: ForwardBatchTerminalCallback | None = None,
    ) -> EventHandle:
        """Schedule one physical completion for a same-target request batch.

        Every route is preflighted before the event is published and again at
        completion.  A completion-time mismatch fences the entire batch before
        any output activation is scheduled, and the callback receives one
        atomic accepted/fenced result.
        """

        ordered_ids = tuple(request_ids)
        if not ordered_ids or any(not item for item in ordered_ids):
            raise ValueError("forward batch requires non-empty request IDs")
        if len(set(ordered_ids)) != len(ordered_ids):
            raise ValueError("forward batch request IDs must be unique")
        if set(output_indices) != set(ordered_ids) or set(produces_outputs) != set(ordered_ids):
            raise ValueError("forward batch output decisions must exactly cover requests")
        if type(at_ns) is not int or at_ns < self.des.now_ns:
            raise ValueError("forward batch completion cannot precede GlobalDES now")

        participants: list[ForwardBatchParticipant] = []
        for request_id in ordered_ids:
            authority = self.router.current_authority(request_id)
            participants.append(
                ForwardBatchParticipant(
                    request_id=request_id,
                    route_version=authority.route_version,
                    target_id=authority.target_replica_id,
                    produces_output=produces_outputs[request_id],
                    output_index=output_indices[request_id],
                )
            )
        participant_tuple = tuple(participants)
        replica_ids = {item.target_id for item in participant_tuple}
        if len(replica_ids) != 1:
            raise BaselineCoordinatorError("one physical forward batch cannot cross DP replicas")
        replica_id = next(iter(replica_ids))
        fence_reason = self._forward_batch_fence_reason(
            replica_id,
            participant_tuple,
        )
        if fence_reason is not None:
            raise BaselineCoordinatorError(
                f"forward batch failed atomic schedule preflight: {fence_reason}"
            )

        sequence = self._forward_batch_sequence
        self._forward_batch_sequence += 1
        handle = self.des.schedule_at(
            at_ns,
            EventKind.FORWARD_COMPLETE,
            event_id=f"baseline-forward-batch:{replica_id}:{sequence:016d}",
            payload={
                "replica_id": replica_id,
                "batch": [item.to_dict() for item in participant_tuple],
            },
        )
        runtime = self._replicas[replica_id]
        representative = participant_tuple[0]
        try:
            self.failure_controller.register_forward(
                handle,
                request_id=representative.request_id,
                route_version=representative.route_version,
                gpu_id=runtime.gpu_id,
            )
        except Exception:
            self.des.cancel(handle, reason="BASELINE_FORWARD_BATCH_REGISTRATION_ROLLBACK")
            raise
        if terminal_callback is not None:
            self._forward_batch_terminal_callbacks[handle.event_id] = terminal_callback
        self._append(
            "BASELINE_FORWARD_BATCH_SCHEDULED",
            {
                "event_id": handle.event_id,
                "replica_id": replica_id,
                "completion_ns": at_ns,
                "compute_capacity": 1,
                "participants": [item.to_dict() for item in participant_tuple],
            },
        )
        return handle

    def discard_forward_terminal_callback(self, handle: EventHandle) -> bool:
        """Forget a callback for a forward event canceled by another owner."""

        single = self._forward_terminal_callbacks.pop(handle.event_id, None)
        batch = self._forward_batch_terminal_callbacks.pop(handle.event_id, None)
        return single is not None or batch is not None

    def recovery_plan(self, request_id: str) -> RecoveryPlan:
        version = self.failure_controller.current_route_version(request_id)
        return self.failure_controller.recovery_plan(request_id, version)

    def silent_replay_plan(self, request_id: str) -> SilentReplayPlan:
        version = self.failure_controller.current_route_version(request_id)
        return self.failure_controller.silent_replay_plan(request_id, version)

    def start_recovery_fetches(
        self,
        request_id: str,
        *,
        resource_plan_provider: TaskResourcePlanProvider | None = None,
        terminal_callback: TransferTerminalCallback | None = None,
    ) -> tuple[GetOperation, ...]:
        """Reserve the target block table/HBM, then issue bound Store GETs."""

        authority = self.router.current_authority(request_id)
        self.router.require_authority(authority)
        key = (request_id, authority.route_version)
        if key in self._recovery_gets:
            raise BaselineCoordinatorError("recovery fetches already started")
        attempt = self.failure_controller.attempt(request_id, authority.route_version)
        if attempt.status is not AttemptStatus.RECOVERING:
            raise BaselineCoordinatorError("Store recovery requires a recovering route")
        runtime = self._replicas[authority.target_replica_id]
        fetch_sequence = self._recovery_fetch_sequences.get(key, 0)
        self._recovery_fetch_sequences[key] = fetch_sequence + 1
        plan = self.failure_controller.recovery_plan(
            request_id,
            authority.route_version,
        )
        for block in plan.store_prefix:
            if len(block.allocation_ids) != 1 or len(block.resource_ids) != 1:
                raise BaselineCoordinatorError(
                    "baseline recovery requires one planned Store allocation per block"
                )
            allocation = self.master.allocation_registry.get(block.allocation_ids[0])
            if allocation.resource_id != block.resource_ids[0]:
                raise BaselineCoordinatorError(
                    "planned Store allocation moved to another resource before fetch"
                )

        operations: list[GetOperation] = []
        fetch_bindings: list[dict[str, object]] = []
        destination_bindings: list[tuple[str, ...]] = []
        reservation: RecoveryPrefixReservation | None = None
        publish_terminal_callbacks = False
        try:
            if plan.restored_tokens:
                reservation = runtime.scheduler.reserve_recovery_prefix(
                    request_id,
                    restored_tokens=plan.restored_tokens,
                )
                destination_cursor = 0
                for block in plan.store_prefix:
                    token_count = block.identity.token_end - block.identity.token_start
                    if (
                        block.identity.token_start
                        != destination_cursor * runtime.scheduler.block_size_tokens
                        or token_count <= 0
                        or token_count % runtime.scheduler.block_size_tokens
                    ):
                        raise BaselineCoordinatorError(
                            "Store recovery block cannot map to whole target scheduler blocks"
                        )
                    logical_block_count = token_count // runtime.scheduler.block_size_tokens
                    logical_destinations = reservation.destination_allocation_ids[
                        destination_cursor : destination_cursor + logical_block_count
                    ]
                    if len(logical_destinations) != logical_block_count:
                        raise BaselineCoordinatorError(
                            "recovery reservation does not cover a full Store prefix block"
                        )
                    if any(len(allocation_ids) != 1 for allocation_ids in logical_destinations):
                        raise BaselineCoordinatorError(
                            "E2 baseline Store GET requires one target HBM allocation "
                            "per scheduler block"
                        )
                    destination_ids = tuple(
                        allocation_id
                        for allocation_ids in logical_destinations
                        for allocation_id in allocation_ids
                    )
                    destination_bindings.append(destination_ids)
                    destination_cursor += logical_block_count
                if destination_cursor != len(reservation.destination_allocation_ids):
                    raise BaselineCoordinatorError(
                        "recovery reservation has target blocks outside the Store prefix"
                    )
                for destination_ids in destination_bindings:
                    if any(
                        allocation.state is not AllocationState.RESERVED
                        or allocation.owner_account != HBM_RECOVERY_RESERVED_ACCOUNT
                        or allocation.resource_id != runtime.store_client.local_gpu.resource_id
                        for allocation in (
                            self.master.allocation_registry.get(allocation_id)
                            for allocation_id in destination_ids
                        )
                    ):
                        raise BaselineCoordinatorError(
                            "recovery destination is not RESERVED on the routed target GPU"
                        )
                self._recovery_reservations[key] = reservation
            for index, block in enumerate(plan.store_prefix):
                if reservation is None:
                    raise BaselineCoordinatorError("Store recovery block has no target reservation")
                destination_ids = destination_bindings[index]
                identity = replace(
                    block.identity,
                    request_id=request_id,
                    route_version=authority.route_version,
                    source_gpu_id=runtime.gpu_id,
                )
                operation = runtime.store_client.get_start(
                    identity,
                    get_id=(
                        f"recovery:{request_id}:route-{authority.route_version}:"
                        f"attempt-{fetch_sequence:04d}:block-{index:06d}"
                    ),
                    ready_ns=self.des.now_ns,
                    cause="BASELINE_E2_COMMITTED_STORE_PREFIX_RESTORE",
                    required_replica_id=block.replica_id,
                    required_allocation_ids=block.allocation_ids,
                    required_source_resource_id=block.resource_ids[0],
                    required_destination_allocation_ids=destination_ids,
                )
                operations.append(operation)
                [task] = operation.batch.tasks
                if (
                    operation.replica.replica_id != block.replica_id
                    or operation.replica.allocation_ids != block.allocation_ids
                    or task.metadata.replica_id != block.replica_id
                    or task.metadata.source.resource_id != block.resource_ids[0]
                    or operation.destination_allocation_ids != destination_ids
                    or task.metadata.destination_allocation_ids != destination_ids
                ):
                    raise BaselineCoordinatorError(
                        "Store recovery fetch diverged from its immutable plan binding"
                    )
                fetch_bindings.append(
                    {
                        "block_index": index,
                        "object_id": block.identity.object_id,
                        "replica_id": block.replica_id,
                        "allocation_ids": list(block.allocation_ids),
                        "source_resource_id": block.resource_ids[0],
                        "destination_allocation_ids": list(destination_ids),
                        "path_id": task.metadata.path.path_id,
                        "transport": task.metadata.path.transport.value,
                    }
                )
            task_plans = tuple(
                (
                    task,
                    None if resource_plan_provider is None else resource_plan_provider(task),
                )
                for operation in operations
                for task in operation.batch.tasks
            )
            for task, resource_plan in task_plans:
                self._preflight_task(task, resource_plan=resource_plan)
            result = tuple(operations)
            self._recovery_gets[key] = result

            def on_recovery_terminal(
                task: TransferTask,
                clock: GlobalDES,
            ) -> None:
                self._on_recovery_transfer_terminal(key, task, clock)
                if publish_terminal_callbacks and terminal_callback is not None:
                    terminal_callback(task, clock)

            for task, resource_plan in task_plans:
                self._schedule_transfer(
                    runtime.store_client,
                    task,
                    request_id=request_id,
                    resource_plan=resource_plan,
                    terminal_callback=on_recovery_terminal,
                    preflight=False,
                )
            publish_terminal_callbacks = True
        except Exception:
            for operation in operations:
                for task in operation.batch.tasks:
                    if task.metadata.transfer_id in self._transfer_launches:
                        launch = self._transfer_launches[task.metadata.transfer_id]
                        if not task.status.terminal:
                            self._abort_launch(
                                launch,
                                reason="BASELINE_RECOVERY_FETCH_START_FAILED",
                                outcome=TransferLeaseOutcome.ABORTED,
                            )
                    elif not task.status.terminal:
                        task.cancel_remaining(
                            timestamp_ns=self.des.now_ns,
                            reason="BASELINE_RECOVERY_FETCH_START_FAILED",
                        )
                        runtime.store_client.reconcile_transfer_terminal(
                            task.metadata.transfer_id,
                            timestamp_ns=self.des.now_ns,
                        )
            self._recovery_gets.pop(key, None)
            self._abort_recovery_reservation(
                key,
                cause="BASELINE_RECOVERY_FETCH_START_FAILED",
            )
            raise
        result = tuple(operations)
        self._recovery_gets[key] = result
        self._append(
            "BASELINE_RECOVERY_FETCHES_STARTED",
            {
                "request_id": request_id,
                "route_version": authority.route_version,
                "fetch_sequence": fetch_sequence,
                "target_id": authority.target_replica_id,
                "get_ids": [operation.get_id for operation in result],
                "fetch_bindings": fetch_bindings,
                "restored_tokens": plan.restored_tokens,
                "recompute_tokens": plan.recompute_tokens,
                "destination_reserved_before_get": reservation is not None,
                "reservation_block_ids": (
                    [] if reservation is None else list(reservation.block_ids)
                ),
            },
        )
        return result

    def prepare_recovery(self, request_id: str) -> Request:
        """Materialize Store/prompt recovery without activating external output.

        The recovered request starts with zero output tokens.  Previously
        committed output positions are reconstructed only by successful
        :meth:`schedule_silent_replay_completion` events.  Generated but not
        externally committed output positions from the failed route are
        deliberately discarded.
        """

        authority = self.router.current_authority(request_id)
        self.router.require_authority(authority)
        key = (request_id, authority.route_version)
        if key in self._prepared_recoveries:
            raise BaselineCoordinatorError("recovery scheduler state was already prepared")
        attempt = self.failure_controller.attempt(request_id, authority.route_version)
        if attempt.status is not AttemptStatus.RECOVERING:
            raise BaselineCoordinatorError("only a recovering route can be prepared")
        operations = self._recovery_gets.get(key)
        if operations is None:
            raise BaselineCoordinatorError("recovery Store fetch phase was not started")
        if any(operation.state is not GetOperationState.COMPLETED for operation in operations):
            raise BaselineCoordinatorError("recovery Store fetches are not complete")
        if attempt.parent_route_version is None:
            raise BaselineCoordinatorError("recovering route has no fenced parent")
        source_key = self._materialized_recovery_parent_key(
            request_id,
            attempt.parent_route_version,
        )
        previous = self._requests[source_key]
        replay = self.failure_controller.silent_replay_plan(
            request_id,
            authority.route_version,
        )
        discarded_partial_replay = 0
        if previous.num_output_tokens < replay.committed_next_output_index:
            try:
                source_replay = self.failure_controller.silent_replay_plan(
                    request_id,
                    source_key[1],
                )
            except KeyError as error:
                raise BaselineCoordinatorError(
                    "initial materialized request is behind the committed output checkpoint"
                ) from error
            if (
                source_replay.status is not SilentReplayStatus.FENCED
                or previous.num_output_tokens != source_replay.replayed_output_count
            ):
                raise BaselineCoordinatorError(
                    "materialized request disagrees with fenced silent replay progress"
                )
            discarded_partial_replay = previous.num_output_tokens
        if replay.committed_next_output_index > previous.max_output_tokens:
            raise BaselineCoordinatorError(
                "committed output checkpoint exceeds the request output guard"
            )
        recovery_plan = self.failure_controller.recovery_plan(
            request_id,
            authority.route_version,
        )
        restored = recovery_plan.restored_tokens
        recovered = Request(
            request_id=previous.request_id,
            prompt_tokens=previous.prompt_tokens,
            max_output_tokens=previous.max_output_tokens,
            arrival_ns=self.des.now_ns,
            priority=previous.priority,
            route_version=authority.route_version,
            max_model_len_tokens=previous.max_model_len_tokens,
        )
        scheduler = self._replicas[authority.target_replica_id].scheduler
        if restored > recovered.prompt_tokens:
            raise BaselineCoordinatorError("restored Store prefix exceeds the prompt")
        if restored and restored % scheduler.block_size_tokens != 0:
            raise BaselineCoordinatorError(
                "restored Store prefix is not aligned to the target scheduler block size"
            )
        if restored == recovered.prompt_tokens == 1:
            raise BaselineCoordinatorError(
                "a one-token full prefix cannot leave the required sampling token"
            )

        reservation = self._recovery_reservations.get(key)
        if restored:
            if reservation is None or reservation.restored_tokens != restored:
                raise BaselineCoordinatorError(
                    "completed Store recovery has no matching target reservation"
                )
            scheduler.validate_recovery_prefix_commit(recovered, reservation)
        elif reservation is not None:
            raise BaselineCoordinatorError(
                "recompute-only recovery unexpectedly owns a target reservation"
            )
        previous_target = self.failure_controller.attempt(
            request_id,
            source_key[1],
        ).target_id
        target_admitted = False
        replay_started = False
        try:
            if not restored:
                scheduler.add_request(recovered)
                target_admitted = True
            started_replay = self.failure_controller.start_silent_replay(
                request_id,
                authority.route_version,
            )
            replay_started = True
            if not previous.finished:
                self._replicas[previous_target].scheduler.finish_request(
                    request_id,
                    RequestStatus.FINISHED_ABORTED,
                )
        except Exception as error:
            replay_rollback_error: Exception | None = None
            replay_state = self.failure_controller.silent_replay_plan(
                request_id,
                authority.route_version,
            )
            replay_mutated = replay_started or replay_state.status is SilentReplayStatus.REPLAYING
            if replay_mutated:
                try:
                    self.failure_controller.rollback_silent_replay_start(
                        request_id,
                        authority.route_version,
                    )
                except Exception as rollback_error:
                    replay_rollback_error = rollback_error
            if target_admitted:
                scheduler.rollback_unstarted_request(request_id)
            self._append(
                "BASELINE_RECOVERY_PREPARATION_ROLLED_BACK",
                {
                    "request_id": request_id,
                    "route_version": authority.route_version,
                    "target_id": authority.target_replica_id,
                    "phase": (
                        "SOURCE_SCHEDULER_RELEASE" if replay_started else "SILENT_REPLAY_START"
                    ),
                    "error_type": type(error).__name__,
                    "old_request_preserved": not previous.finished,
                    "silent_replay_rollback_error_type": (
                        None
                        if replay_rollback_error is None
                        else type(replay_rollback_error).__name__
                    ),
                },
            )
            if replay_rollback_error is not None:
                raise BaselineCoordinatorError(
                    "recovery preparation and silent replay rollback both failed"
                ) from error
            raise

        if restored:
            if reservation is None:
                raise BaselineCoordinatorError("recovery reservation disappeared before commit")
            try:
                scheduler.commit_recovery_prefix(recovered, reservation)
            except Exception as error:
                commit_replay_rollback_error: Exception | None = None
                try:
                    self.failure_controller.rollback_silent_replay_start(
                        request_id,
                        authority.route_version,
                    )
                except Exception as rollback_error:
                    commit_replay_rollback_error = rollback_error
                self._append(
                    "BASELINE_RECOVERY_PREPARATION_ROLLED_BACK",
                    {
                        "request_id": request_id,
                        "route_version": authority.route_version,
                        "target_id": authority.target_replica_id,
                        "phase": "TARGET_RESERVATION_COMMIT",
                        "error_type": type(error).__name__,
                        "old_request_preserved": False,
                        "silent_replay_rollback_error_type": (
                            None
                            if commit_replay_rollback_error is None
                            else type(commit_replay_rollback_error).__name__
                        ),
                    },
                )
                if commit_replay_rollback_error is not None:
                    raise BaselineCoordinatorError(
                        "recovery commit and silent replay rollback both failed"
                    ) from error
                raise
            del self._recovery_reservations[key]
            target_admitted = True

        self._requests[key] = recovered
        self._authorities[key] = authority
        self._prepared_recoveries.add(key)
        if not target_admitted:
            # This is unreachable for a valid recovery and guards future edits
            # from publishing coordinator ownership without scheduler ownership.
            self._prepared_recoveries.discard(key)
            self._authorities.pop(key, None)
            self._requests.pop(key, None)
            try:
                self.failure_controller.rollback_silent_replay_start(
                    request_id,
                    authority.route_version,
                )
            except Exception as rollback_error:
                raise BaselineCoordinatorError(
                    "target admission vanished and replay rollback failed"
                ) from rollback_error
            raise BaselineCoordinatorError("target recovery request was not admitted")
        self._append(
            "BASELINE_RECOVERY_SCHEDULER_PREPARED",
            {
                "request_id": request_id,
                "route_version": authority.route_version,
                "target_id": authority.target_replica_id,
                "materialized_parent_route_version": source_key[1],
                "restored_tokens": restored,
                "recompute_tokens": recovered.prompt_tokens - restored,
                "committed_next_output_index": (replay.committed_next_output_index),
                "discarded_uncommitted_output_count": (
                    max(
                        previous.num_output_tokens - replay.committed_next_output_index,
                        0,
                    )
                ),
                "discarded_partial_silent_replay_output_count": (discarded_partial_replay),
                "restored_block_ids": list(scheduler.request_block_ids(request_id)),
                "running_admission_deferred": False,
                "recovery_destination_committed": bool(restored),
                "request_status": recovered.status.name,
                "silent_replay": started_replay.to_dict(),
            },
        )
        return recovered

    def run_silent_replay_scheduler_step(self, request_id: str) -> SchedulerOutput:
        """Schedule one isolated prompt-recompute/output-replay model step."""

        authority = self.router.current_authority(request_id)
        self.router.require_authority(authority)
        key = (request_id, authority.route_version)
        if key not in self._prepared_recoveries:
            raise BaselineCoordinatorError("silent replay requires prepared recovery state")
        if key in self._silent_replay_forwards:
            raise BaselineCoordinatorError("a silent replay forward is already pending")
        attempt = self.failure_controller.attempt(request_id, authority.route_version)
        replay = self.failure_controller.silent_replay_plan(
            request_id,
            authority.route_version,
        )
        if attempt.status is not AttemptStatus.RECOVERING:
            raise BaselineCoordinatorError("silent replay requires a recovering route")
        if replay.status is not SilentReplayStatus.REPLAYING:
            raise BaselineCoordinatorError("silent replay has no remaining output position")
        scheduler = self._replicas[authority.target_replica_id].scheduler
        queued_ids = (*scheduler.running_request_ids, *scheduler.waiting_request_ids)
        if queued_ids != (request_id,):
            raise BaselineCoordinatorError("E2 silent replay requires isolated scheduler ownership")
        output = scheduler.schedule()
        if output.scheduled_req_ids != (request_id,):
            raise BaselineCoordinatorError(
                "silent replay scheduler made no isolated request progress"
            )
        scheduled = _scheduled_request(output, request_id)
        self._silent_replay_forwards[key] = _SilentReplayForward(
            request_id=request_id,
            route_version=authority.route_version,
            scheduled=scheduled,
        )
        self._append(
            "BASELINE_SILENT_REPLAY_SCHEDULER_STEP",
            {
                "request_id": request_id,
                "route_version": authority.route_version,
                "target_id": authority.target_replica_id,
                "scheduled": scheduled.to_dict(),
                "silent_replay": replay.to_dict(),
            },
        )
        return output

    def schedule_silent_replay_completion(
        self,
        request_id: str,
        *,
        at_ns: int,
        terminal_callback: ForwardTerminalCallback | None = None,
    ) -> EventHandle:
        """Publish one internal replay forward; it can never emit externally.

        The optional callback runs only after scheduler counters and the
        ``SilentReplayPlan`` have been advanced, so a recovery driver can use
        the plan status as the sole continuation/activation predicate.
        """

        authority = self.router.current_authority(request_id)
        self.router.require_authority(authority)
        key = (request_id, authority.route_version)
        try:
            pending = self._silent_replay_forwards[key]
        except KeyError as error:
            raise BaselineCoordinatorError(
                "silent replay completion has no scheduled model step"
            ) from error
        if pending.handle is not None:
            raise BaselineCoordinatorError("silent replay completion was already scheduled")
        if type(at_ns) is not int or at_ns < self.des.now_ns:
            raise ValueError("silent replay completion cannot precede GlobalDES now")
        attempt = self.failure_controller.attempt(request_id, authority.route_version)
        replay = self.failure_controller.silent_replay_plan(
            request_id,
            authority.route_version,
        )
        if (
            attempt.status is not AttemptStatus.RECOVERING
            or replay.status is not SilentReplayStatus.REPLAYING
        ):
            raise BaselineCoordinatorError("silent replay route is no longer executable")

        sequence = self._silent_replay_sequence
        self._silent_replay_sequence += 1
        event_id = (
            f"baseline-silent-replay:{request_id}:route-{authority.route_version}:"
            f"step-{sequence:016d}"
        )
        handle = self.des.schedule_at(
            at_ns,
            EventKind.FORWARD_COMPLETE,
            event_id=event_id,
            payload={
                "request_id": request_id,
                "route_version": authority.route_version,
                "produces_output": False,
                "output_index": None,
            },
        )
        runtime = self._replicas[authority.target_replica_id]
        try:
            self.failure_controller.register_forward(
                handle,
                request_id=request_id,
                route_version=authority.route_version,
                gpu_id=runtime.gpu_id,
                cancel_handler=lambda reason: self._cancel_silent_replay_forward(
                    key,
                    handle,
                    reason=reason,
                ),
            )
        except Exception:
            self.des.cancel(
                handle,
                reason="BASELINE_SILENT_REPLAY_REGISTRATION_ROLLBACK",
            )
            raise
        pending.handle = handle

        def on_silent_replay_terminal(
            event: ScheduledEvent,
            clock: GlobalDES,
        ) -> None:
            self._on_silent_replay_forward_complete(
                key,
                event,
                clock,
            )
            if terminal_callback is not None:
                terminal_callback(event, clock)

        self._forward_terminal_callbacks[event_id] = on_silent_replay_terminal
        self._append(
            "BASELINE_SILENT_REPLAY_FORWARD_SCHEDULED",
            {
                "event_id": event_id,
                "request_id": request_id,
                "route_version": authority.route_version,
                "target_id": authority.target_replica_id,
                "completion_ns": at_ns,
                "externally_emitted": False,
                "scheduled": pending.scheduled.to_dict(),
            },
        )
        return handle

    def activate_recovery(self, request_id: str) -> Request:
        authority = self.router.current_authority(request_id)
        self.router.require_authority(authority)
        key = (request_id, authority.route_version)
        recovered = (
            self._requests[key]
            if key in self._prepared_recoveries
            else self.prepare_recovery(request_id)
        )
        if key in self._silent_replay_forwards:
            raise BaselineCoordinatorError(
                "cannot activate recovery with a pending silent replay forward"
            )
        try:
            self.failure_controller.activate_recovery(
                request_id,
                authority.route_version,
            )
        except (RecoveryInvariantError, ValueError) as error:
            raise BaselineCoordinatorError(str(error)) from error
        self._prepared_recoveries.discard(key)
        self._append(
            "BASELINE_RECOVERY_SCHEDULER_ACTIVATED",
            {
                "request_id": request_id,
                "route_version": authority.route_version,
                "target_id": authority.target_replica_id,
                "request_status": recovered.status.name,
                "silent_replay": self.failure_controller.silent_replay_plan(
                    request_id,
                    authority.route_version,
                ).to_dict(),
            },
        )
        return recovered

    def _materialized_recovery_parent_key(
        self,
        request_id: str,
        parent_route_version: int,
    ) -> tuple[str, int]:
        """Find the nearest ancestor route that owns scheduler request state."""

        route_version = parent_route_version
        visited: set[int] = set()
        while route_version not in visited:
            visited.add(route_version)
            key = (request_id, route_version)
            if key in self._requests:
                pending = self._silent_replay_forwards.get(key)
                if pending is not None:
                    if pending.handle is not None:
                        raise BaselineCoordinatorError(
                            "fenced replay retained a scheduled forward callback"
                        )
                    del self._silent_replay_forwards[key]
                    self._append(
                        "BASELINE_SILENT_REPLAY_UNPUBLISHED_STEP_DISCARDED",
                        {
                            "request_id": request_id,
                            "route_version": route_version,
                            "reason": "PARENT_ROUTE_FENCED_BEFORE_FORWARD_PUBLICATION",
                            "scheduled": pending.scheduled.to_dict(),
                        },
                    )
                return key
            attempt = self.failure_controller.attempt(request_id, route_version)
            if attempt.parent_route_version is None:
                break
            route_version = attempt.parent_route_version
        raise BaselineCoordinatorError("recovering route has no materialized scheduler ancestor")

    def _cancel_silent_replay_forward(
        self,
        key: tuple[str, int],
        handle: EventHandle,
        *,
        reason: str,
    ) -> None:
        pending = self._silent_replay_forwards.get(key)
        if pending is None or pending.handle is None or pending.handle.event_id != handle.event_id:
            raise BaselineCoordinatorError(
                "silent replay cancellation has no matching pending forward"
            )
        del self._silent_replay_forwards[key]
        callback = self._forward_terminal_callbacks.pop(handle.event_id, None)
        if callback is None:
            raise BaselineCoordinatorError("silent replay cancellation lost its terminal callback")
        self._append(
            "BASELINE_SILENT_REPLAY_FORWARD_CANCELED",
            {
                "event_id": handle.event_id,
                "request_id": key[0],
                "route_version": key[1],
                "reason": reason,
                "externally_emitted": False,
                "scheduled": pending.scheduled.to_dict(),
            },
        )

    def _on_recovery_transfer_terminal(
        self,
        key: tuple[str, int],
        task: TransferTask,
        clock: GlobalDES,
    ) -> None:
        """Abort the whole destination hold when any bound Store GET fails."""

        if clock is not self.des:
            raise BaselineCoordinatorError("recovery transfer completed on another clock")
        operations = self._recovery_gets.get(key)
        if operations is None or not any(
            task is candidate for operation in operations for candidate in operation.batch.tasks
        ):
            raise BaselineCoordinatorError(
                "recovery transfer terminal callback lost its fetch binding"
            )
        if task.status is TransferStatus.COMPLETED:
            return
        if not task.status.terminal:
            raise BaselineCoordinatorError(
                "recovery transfer terminal callback received an active task"
            )
        # The failure controller cancels every affected operation synchronously
        # before it schedules ROUTE_FENCE.  Let that loop finish so a sibling is
        # never canceled twice; the fence sink below then releases the hold.
        if (task.abort_reason or "").startswith("GPU_FAILURE:"):
            return
        self._abort_recovery_fetch_group(
            key,
            reason=task.abort_reason or f"RECOVERY_TRANSFER_{task.status.value}",
        )

    def _abort_recovery_fetch_group(
        self,
        key: tuple[str, int],
        *,
        reason: str,
    ) -> None:
        """Make every GET terminal before returning its destination capacity."""

        if not reason:
            raise ValueError("recovery fetch abort reason must be non-empty")
        if key in self._aborting_recovery_fetches:
            return
        self._aborting_recovery_fetches.add(key)
        try:
            operations = self._recovery_gets.get(key, ())
            target_id = self.failure_controller.attempt(key[0], key[1]).target_id
            client = self._replicas[target_id].store_client
            for operation in operations:
                for task in operation.batch.tasks:
                    if task.status.terminal:
                        continue
                    launch = self._transfer_launches.get(task.metadata.transfer_id)
                    if launch is not None:
                        self._abort_launch(
                            launch,
                            reason=reason,
                            outcome=TransferLeaseOutcome.ABORTED,
                        )
                    else:
                        task.cancel_remaining(
                            timestamp_ns=self.des.now_ns,
                            reason=reason,
                        )
                        client.reconcile_transfer_terminal(
                            task.metadata.transfer_id,
                            timestamp_ns=self.des.now_ns,
                        )
            if any(
                not task.status.terminal
                for operation in operations
                for task in operation.batch.tasks
            ):
                raise BaselineCoordinatorError(
                    "recovery destination cannot release before every GET is terminal"
                )
            self._abort_recovery_reservation(key, cause=reason)
        finally:
            self._aborting_recovery_fetches.discard(key)

    def _abort_recovery_reservation(
        self,
        key: tuple[str, int],
        *,
        cause: str,
    ) -> bool:
        """Release one coordinator/scheduler recovery hold exactly once."""

        reservation = self._recovery_reservations.get(key)
        if reservation is None:
            return False
        if not cause:
            raise ValueError("recovery reservation abort cause must be non-empty")
        attempt = self.failure_controller.attempt(key[0], key[1])
        scheduler = self._replicas[attempt.target_id].scheduler
        try:
            scheduler_reservation = scheduler.recovery_prefix_reservation(key[0])
        except KeyError as error:
            raise BaselineCoordinatorError(
                "coordinator recovery reservation is absent from its scheduler"
            ) from error
        if scheduler_reservation != reservation:
            raise BaselineCoordinatorError(
                "coordinator and scheduler recovery reservations diverged"
            )
        scheduler.abort_recovery_prefix(key[0], cause=cause)
        del self._recovery_reservations[key]
        self._append(
            "BASELINE_RECOVERY_DESTINATION_ABORTED",
            {
                "request_id": key[0],
                "route_version": key[1],
                "target_id": attempt.target_id,
                "cause": cause,
                "block_ids": list(reservation.block_ids),
                "destination_allocation_ids": [
                    list(allocation_ids)
                    for allocation_ids in reservation.destination_allocation_ids
                ],
            },
        )
        return True

    def _on_recovery_route_fenced(
        self,
        request_id: str,
        route_version: int,
        reason: str,
    ) -> None:
        """Fence cleanup for an uncommitted recovery destination."""

        key = (request_id, route_version)
        if key not in self._recovery_reservations:
            return
        self._abort_recovery_fetch_group(key, reason=reason)

    def _on_recovery_failed_no_target(
        self,
        request_id: str,
        route_version: int,
        reason: str,
    ) -> None:
        """Release logical scheduler ownership after terminal recovery failure."""

        source_key = self._materialized_recovery_parent_key(
            request_id,
            route_version,
        )
        request = self._requests[source_key]
        source_target = self.failure_controller.attempt(
            request_id,
            source_key[1],
        ).target_id
        if not request.finished:
            self._replicas[source_target].scheduler.finish_request(
                request_id,
                RequestStatus.FINISHED_ERROR,
            )
        self._prepared_recoveries.discard(source_key)
        self._append(
            "BASELINE_RECOVERY_TERMINAL_REQUEST_ABORTED",
            {
                "request_id": request_id,
                "failed_route_version": route_version,
                "materialized_route_version": source_key[1],
                "target_id": source_target,
                "reason": reason,
                "request_status": request.status.name,
            },
        )

    def _on_silent_replay_forward_complete(
        self,
        key: tuple[str, int],
        event: ScheduledEvent,
        clock: GlobalDES,
    ) -> None:
        if clock is not self.des:
            raise BaselineCoordinatorError("silent replay completed on another clock")
        pending = self._silent_replay_forwards.get(key)
        if pending is None or pending.handle is None or pending.handle.event_id != event.event_id:
            raise BaselineCoordinatorError(
                "silent replay completion has no matching scheduled forward"
            )
        del self._silent_replay_forwards[key]
        request = self._requests[key]
        scheduler = self._replicas[
            self.failure_controller.attempt(key[0], key[1]).target_id
        ].scheduler
        produces_output = _scheduled_request_produces_output(
            pending.scheduled,
            request,
        )
        replay_before = self.failure_controller.silent_replay_plan(key[0], key[1])
        if replay_before.status is not SilentReplayStatus.REPLAYING:
            raise BaselineCoordinatorError(
                "silent replay forward completed after its route stopped replaying"
            )
        replay_after = replay_before
        replayed_output_index: int | None = None
        cached_new_output_index: int | None = None
        if produces_output:
            terminal = request.num_output_tokens + 1 == request.max_output_tokens
            scheduler.append_output_tokens(
                key[0],
                1,
                terminal=terminal,
            )
            if replay_before.remaining_output_count > 0:
                replayed_output_index = replay_before.replayed_output_count
                replay_after = self.failure_controller.record_silent_replay_output(
                    key[0],
                    key[1],
                    replayed_output_index=replayed_output_index,
                )
            else:
                cached_new_output_index = 0
                try:
                    replay_after = self.failure_controller.record_prompt_materialized_output(
                        key[0],
                        key[1],
                        output_index=cached_new_output_index,
                    )
                except (RecoveryInvariantError, ValueError) as error:
                    raise BaselineCoordinatorError(
                        "silent replay computed beyond its materialization contract"
                    ) from error
        self._append(
            "BASELINE_SILENT_REPLAY_FORWARD_COMPLETED",
            {
                "event_id": event.event_id,
                "request_id": key[0],
                "route_version": key[1],
                "scheduled": pending.scheduled.to_dict(),
                "produced_replayed_output": replayed_output_index is not None,
                "replayed_output_index": replayed_output_index,
                "cached_new_output_index": cached_new_output_index,
                "externally_emitted": False,
                "request_num_computed_tokens": request.num_computed_tokens,
                "request_num_output_tokens": request.num_output_tokens,
                "silent_replay": replay_after.to_dict(),
            },
        )

    def finish_current_request(
        self,
        request_id: str,
        *,
        status: RequestStatus = RequestStatus.FINISHED_STOPPED,
    ) -> None:
        authority = self.router.current_authority(request_id)
        self.router.require_authority(authority)
        self._replicas[authority.target_replica_id].scheduler.finish_request(
            request_id,
            status,
        )
        self._append(
            "BASELINE_REQUEST_FINISHED",
            {
                "request_id": request_id,
                "route_version": authority.route_version,
                "target_id": authority.target_replica_id,
                "status": status.name,
            },
        )

    def audit(self, *, require_quiescent: bool = True) -> None:
        """Check scheduler, Store ledger, runtime-flow, and byte invariants."""

        self.transfer_runtime.audit()
        self.master.allocation_registry.audit(self._allocation_ledgers)
        if self.transfer_resource_manager is not None:
            self.transfer_resource_manager.audit()
        if self.endpoint_registration_manager is not None:
            self.endpoint_registration_manager.audit(require_quiescent=require_quiescent)
        for runtime in self._replicas.values():
            runtime.scheduler.audit()
        for key, reservation in self._recovery_reservations.items():
            attempt = self.failure_controller.attempt(key[0], key[1])
            scheduler = self._replicas[attempt.target_id].scheduler
            try:
                scheduler_reservation = scheduler.recovery_prefix_reservation(key[0])
            except KeyError as error:
                raise BaselineCoordinatorError(
                    "coordinator recovery reservation is absent from its scheduler"
                ) from error
            if scheduler_reservation != reservation:
                raise BaselineCoordinatorError(
                    "coordinator and scheduler recovery reservations diverged"
                )
            operations = self._recovery_gets.get(key)
            if operations is None:
                raise BaselineCoordinatorError(
                    "recovery reservation has no immutable Store GET binding"
                )
            if any(
                task.status.terminal and task.status is not TransferStatus.COMPLETED
                for operation in operations
                for task in operation.batch.tasks
            ):
                raise BaselineCoordinatorError("failed recovery GET retained destination capacity")
            if key in self._prepared_recoveries:
                raise BaselineCoordinatorError(
                    "prepared recovery retained an uncommitted destination hold"
                )
        if require_quiescent and self._silent_replay_forwards:
            raise BaselineCoordinatorError("quiescent audit found a pending silent replay forward")
        model = self.transfer_runtime.controller.model
        if require_quiescent and (model.flows or self.transfer_runtime.active_flow_ids):
            raise BaselineCoordinatorError("quiescent audit found active transfer flows")
        if (
            require_quiescent
            and self.transfer_resource_manager is not None
            and self.transfer_resource_manager.active_lease_ids
        ):
            raise BaselineCoordinatorError("quiescent audit found active transfer resource leases")
        if require_quiescent and any(
            not launch.task.status.terminal or not launch.reconciled
            for launch in self._transfer_launches.values()
        ):
            raise BaselineCoordinatorError("quiescent audit found an unreconciled transfer launch")
        interval_bytes_by_transfer: dict[str, float] = {}
        for interval in model.intervals:
            interval_bytes_by_transfer[interval.transfer_id] = (
                interval_bytes_by_transfer.get(interval.transfer_id, 0.0)
                + interval.transferred_bytes
            )
        unknown_interval_transfers = interval_bytes_by_transfer.keys() - self._started_tasks.keys()
        if require_quiescent and unknown_interval_transfers:
            raise BaselineCoordinatorError(
                "flow intervals reference transfers outside the baseline coordinator"
            )
        for transfer_id, task in self._started_tasks.items():
            task.audit()
            if require_quiescent and not task.status.terminal:
                raise BaselineCoordinatorError(
                    "quiescent E2 scenario contains a nonterminal transfer"
                )
            modeled_bytes = interval_bytes_by_transfer.get(transfer_id, 0.0)
            if (
                modeled_bytes < task.transferred_bytes - 1e-6
                or modeled_bytes > task.metadata.total_bytes + 1e-6
            ):
                raise BaselineCoordinatorError(
                    "flow intervals violate terminal transfer byte bounds"
                )
            if task.status is TransferStatus.COMPLETED and not math.isclose(
                modeled_bytes,
                float(task.metadata.total_bytes),
                rel_tol=0.0,
                abs_tol=1e-6,
            ):
                raise BaselineCoordinatorError(
                    "flow intervals do not conserve completed transfer bytes"
                )
        previous_timestamp = 0
        for record in self.des.journal.records:
            if record.timestamp_ns < previous_timestamp:
                raise BaselineCoordinatorError("journal time moved backwards")
            previous_timestamp = record.timestamp_ns

    def _snapshot_replicas(self, now_ns: int) -> tuple[DPReplicaSnapshot, ...]:
        return tuple(
            DPReplicaSnapshot(
                replica_id=runtime.replica_id,
                dp_rank=runtime.dp_rank,
                scheduler_id=runtime.scheduler_id,
                healthy=self.failure_controller.target_is_healthy(runtime.replica_id),
                waiting_requests=len(runtime.scheduler.waiting_request_ids),
                running_requests=len(runtime.scheduler.running_request_ids),
                queued_tokens=runtime.scheduler.queued_tokens,
                observed_at_ns=now_ns,
            )
            for runtime in sorted(
                self._replicas.values(),
                key=lambda item: (item.dp_rank, item.replica_id),
            )
        )

    def _schedule_transfer(
        self,
        client: StoreClient,
        task: TransferTask,
        *,
        request_id: str,
        resource_plan: TransferTaskResourcePlan | None,
        terminal_callback: TransferTerminalCallback | None = None,
        preflight: bool = True,
    ) -> None:
        if preflight:
            self._preflight_task(task, resource_plan=resource_plan)

        transfer_id = task.metadata.transfer_id
        launch = _TransferLaunch(
            client=client,
            task=task,
            request_id=request_id,
            resource_plan=resource_plan,
            terminal_callback=terminal_callback,
        )
        self._transfer_launches[transfer_id] = launch
        registered = False
        try:
            endpoint_manager = self.endpoint_registration_manager
            if endpoint_manager is None:
                self._schedule_data_plane_start(launch)
                launch.operation_handle = launch.start_handle
            else:
                preparation_id = f"baseline-endpoint-preparation:{transfer_id}"

                def on_endpoint_ready(
                    prepared_task: TransferTask,
                    clock: GlobalDES,
                    transfer_id: str = transfer_id,
                ) -> None:
                    self._on_endpoint_ready(transfer_id, prepared_task, clock)

                launch.endpoint_preparation_id = preparation_id
                launch.operation_handle = endpoint_manager.prepare(
                    task,
                    preparation_id=preparation_id,
                    on_ready=on_endpoint_ready,
                )

            if launch.operation_handle is None:
                raise BaselineCoordinatorError("transfer has no failure operation handle")

            def cancel_on_gpu_failure(
                reason: str,
                transfer_id: str = transfer_id,
            ) -> None:
                self._abort_for_gpu_failure(transfer_id, reason=reason)

            self.failure_controller.register_transfer(
                launch.operation_handle,
                request_id=request_id,
                route_version=task.metadata.route_version,
                source_gpu_id=task.metadata.source.gpu_id,
                destination_gpu_id=task.metadata.destination.gpu_id,
                cancel_handler=cancel_on_gpu_failure,
            )
            registered = True
        except Exception:
            self._transfer_launches.pop(transfer_id, None)
            if registered and launch.operation_handle is not None:
                self.failure_controller.complete_operation(launch.operation_handle)
            if launch.endpoint_preparation_id is not None:
                endpoint_manager = self.endpoint_registration_manager
                if endpoint_manager is not None:
                    endpoint_manager.cancel_preparation(
                        launch.endpoint_preparation_id,
                        reason="BASELINE_TRANSFER_SCHEDULING_ROLLBACK",
                    )
            if launch.start_handle is not None:
                self.des.cancel(
                    launch.start_handle,
                    reason="BASELINE_TRANSFER_SCHEDULING_ROLLBACK",
                )
            if launch.lease_id is not None:
                manager = self.transfer_resource_manager
                if manager is None:
                    raise BaselineCoordinatorError(
                        "resource manager disappeared during transfer scheduling"
                    ) from None
                lease = manager.lease(launch.lease_id)
                if lease.status is not TransferLeaseStatus.RELEASED:
                    manager.release(
                        launch.lease_id,
                        outcome=TransferLeaseOutcome.ABORTED,
                        reason="BASELINE_TRANSFER_SCHEDULING_ROLLBACK",
                    )
            raise

        self._append(
            "BASELINE_TRANSFER_ENDPOINT_PREPARATION_SCHEDULED",
            {
                "operation_event_id": launch.operation_handle.event_id,
                "endpoint_preparation_id": launch.endpoint_preparation_id,
                "transfer_id": transfer_id,
                "request_id": request_id,
                "route_version": task.metadata.route_version,
                "endpoint_registration_integrated": (
                    self.endpoint_registration_manager is not None
                ),
            },
        )

    def _on_endpoint_ready(
        self,
        transfer_id: str,
        task: TransferTask,
        clock: GlobalDES,
    ) -> None:
        try:
            launch = self._transfer_launches[transfer_id]
        except KeyError as error:
            raise BaselineCoordinatorError(
                "endpoint-ready callback references an unknown launch"
            ) from error
        if clock is not self.des or launch.task is not task:
            raise BaselineCoordinatorError("endpoint-ready callback binding diverged")
        if task.status is not TransferStatus.WAITING or launch.start_handle is not None:
            raise BaselineCoordinatorError("endpoint-ready transfer is not queued exactly once")
        launch.endpoint_preparation_id = None
        try:
            self._schedule_data_plane_start(launch)
        except Exception:
            if not task.status.terminal:
                task.cancel_remaining(
                    timestamp_ns=self.des.now_ns,
                    reason="BASELINE_TRANSFER_DATA_PLANE_SCHEDULING_FAILED",
                )
                self._reconcile_transfer_terminal(task, clock=self.des)
            raise

    def _schedule_data_plane_start(self, launch: _TransferLaunch) -> None:
        task = launch.task
        transfer_id = task.metadata.transfer_id
        if launch.start_handle is not None or launch.lease_id is not None:
            raise BaselineCoordinatorError("transfer data-plane start was scheduled twice")
        start_ns = max(self.des.now_ns, task.metadata.ready_ns)
        resource_plan = launch.resource_plan
        if resource_plan is not None:
            manager = self.transfer_resource_manager
            if manager is None:
                raise BaselineCoordinatorError(
                    "a resource plan requires the coordinator transfer resource manager"
                )
            lease_id = f"baseline-transfer-lease:{transfer_id}"
            lease = manager.acquire(
                task,
                lease_id=lease_id,
                duration_ns=resource_plan.duration_ns,
                staging_specs=resource_plan.staging_specs_by_resource(),
                latest_start_ns=resource_plan.latest_start_ns,
            )
            launch.lease_id = lease_id
            start_ns = lease.start_ns
        try:
            launch.start_handle = self.des.schedule_at(
                start_ns,
                EventKind.TRANSFER_START,
                event_id=f"baseline-transfer-start:{transfer_id}",
                payload={"lease_id": launch.lease_id, "transfer_id": transfer_id},
            )
        except Exception:
            if launch.lease_id is not None:
                manager = self.transfer_resource_manager
                if manager is None:
                    raise BaselineCoordinatorError(
                        "resource manager disappeared during start scheduling"
                    ) from None
                manager.release(
                    launch.lease_id,
                    outcome=TransferLeaseOutcome.ABORTED,
                    reason="BASELINE_TRANSFER_START_SCHEDULING_ROLLBACK",
                )
                launch.lease_id = None
            raise
        self._append(
            "BASELINE_TRANSFER_START_SCHEDULED",
            {
                "event_id": launch.start_handle.event_id,
                "lease_id": launch.lease_id,
                "transfer_id": transfer_id,
                "request_id": launch.request_id,
                "route_version": task.metadata.route_version,
                "scheduled_start_ns": start_ns,
                "resource_plan_supplied": resource_plan is not None,
                "duration_ns": (None if resource_plan is None else resource_plan.duration_ns),
                "latest_start_ns": (
                    None if resource_plan is None else resource_plan.latest_start_ns
                ),
                "scheduled_after_endpoint_ready": (self.endpoint_registration_manager is not None),
            },
        )

    def _preflight_task(
        self,
        task: TransferTask,
        *,
        resource_plan: TransferTaskResourcePlan | None,
    ) -> None:
        if task.status is not TransferStatus.WAITING:
            raise BaselineCoordinatorError("only a waiting transfer may enter FlowDES")
        if resource_plan is not None and not isinstance(resource_plan, TransferTaskResourcePlan):
            raise TypeError("resource plan must be a TransferTaskResourcePlan")
        try:
            task.audit()
        except RuntimeError as error:
            raise BaselineCoordinatorError("transfer task byte layout is invalid") from error
        path = task.metadata.path
        needs_resource_plan = path.transport in {
            TransportKind.RDMA_HOST_STAGED,
            TransportKind.TCP_HOST_STAGED,
        } or (
            path.source_host_staging_resource_id is not None
            or path.destination_host_staging_resource_id is not None
            or bool(path.concurrency_resource_ids)
        )
        if needs_resource_plan and resource_plan is None:
            raise BaselineCoordinatorError(
                "host-staged path or concurrency resources require an explicit "
                "per-task resource plan"
            )
        if resource_plan is not None and self.transfer_resource_manager is None:
            raise BaselineCoordinatorError(
                "resource-planned transfer requires a transfer resource manager"
            )
        unknown = (
            set(path.rate_resource_ids) - self.transfer_runtime.controller.model.resources.keys()
        )
        if unknown:
            raise BaselineCoordinatorError(
                f"transfer path names unknown flow resources: {sorted(unknown)}"
            )
        if task.metadata.transfer_id in self._transfer_launches:
            raise BaselineCoordinatorError("transfer ID was already scheduled")

    def _on_transfer_start(self, event: ScheduledEvent, des: GlobalDES) -> None:
        if set(event.payload) != {"lease_id", "transfer_id"}:
            raise BaselineCoordinatorError("TRANSFER_START payload is not exact")
        transfer_id = event.payload["transfer_id"]
        lease_id = event.payload["lease_id"]
        if not isinstance(transfer_id, str) or not transfer_id:
            raise BaselineCoordinatorError("TRANSFER_START transfer_id is invalid")
        if lease_id is not None and (not isinstance(lease_id, str) or not lease_id):
            raise BaselineCoordinatorError("TRANSFER_START lease_id is invalid")
        try:
            launch = self._transfer_launches[transfer_id]
        except KeyError as error:
            raise BaselineCoordinatorError("TRANSFER_START references an unknown task") from error
        if (
            des is not self.des
            or launch.start_handle is None
            or event.event_id != launch.start_handle.event_id
        ):
            raise BaselineCoordinatorError("transfer start executed outside its launch binding")
        if lease_id != launch.lease_id or des.now_ns != event.timestamp_ns:
            raise BaselineCoordinatorError("transfer start lease or clock diverged")

        def reconcile(terminal: TransferTask, clock: GlobalDES) -> None:
            self._reconcile_transfer_terminal(terminal, clock=clock)

        self._started_tasks[transfer_id] = launch.task
        try:
            if lease_id is None:
                self.transfer_runtime.start_task(launch.task, on_terminal=reconcile)
            else:
                manager = self.transfer_resource_manager
                if manager is None:
                    raise BaselineCoordinatorError(
                        "leased transfer lost its transfer resource manager"
                    )
                manager.start_task(
                    self.transfer_runtime,
                    launch.task,
                    lease_id=lease_id,
                    on_terminal=reconcile,
                )
        except Exception:
            if not launch.task.status.terminal:
                self._abort_launch(
                    launch,
                    reason="BASELINE_TRANSFER_START_FAILED",
                    outcome=TransferLeaseOutcome.ABORTED,
                )
            raise
        launch.started = True
        self._append(
            "BASELINE_TRANSFER_STARTED",
            {
                "event_id": event.event_id,
                "lease_id": lease_id,
                "transfer_id": transfer_id,
                "request_id": launch.request_id,
                "route_version": launch.task.metadata.route_version,
                "start_ns": des.now_ns,
            },
        )

    def _abort_for_gpu_failure(self, transfer_id: str, *, reason: str) -> None:
        try:
            launch = self._transfer_launches[transfer_id]
        except KeyError as error:
            raise BaselineCoordinatorError(
                "GPU failure references an unknown transfer launch"
            ) from error
        launch.failure_canceling = True
        self._abort_launch(
            launch,
            reason=reason,
            outcome=TransferLeaseOutcome.GPU_FAILURE,
        )
        if self.endpoint_registration_manager is not None:
            self.endpoint_registration_manager.teardown_path(
                launch.task.metadata.path,
                reason=reason,
            )

    def _abort_launch(
        self,
        launch: _TransferLaunch,
        *,
        reason: str,
        outcome: TransferLeaseOutcome,
    ) -> None:
        task = launch.task
        if task.status.terminal:
            raise BaselineCoordinatorError("terminal transfer cannot be aborted twice")
        if task.status is TransferStatus.PENDING:
            self.transfer_runtime.abort_task(task.metadata.transfer_id, reason=reason)
        elif task.status is TransferStatus.WAITING:
            canceled = False
            if launch.endpoint_preparation_id is not None:
                endpoint_manager = self.endpoint_registration_manager
                if endpoint_manager is None:
                    raise BaselineCoordinatorError("queued endpoint preparation lost its manager")
                canceled = endpoint_manager.cancel_preparation(
                    launch.endpoint_preparation_id,
                    reason=reason,
                )
                launch.endpoint_preparation_id = None
            if launch.start_handle is not None:
                canceled = self.des.cancel(launch.start_handle, reason=reason) or canceled
            if not canceled and not launch.failure_canceling:
                raise BaselineCoordinatorError(
                    "queued endpoint/start event could not be canceled exactly once"
                )
            if launch.lease_id is not None:
                manager = self.transfer_resource_manager
                if manager is None:
                    raise BaselineCoordinatorError(
                        "queued leased transfer lost its resource manager"
                    )
                manager.release(launch.lease_id, outcome=outcome, reason=reason)
            task.cancel_remaining(timestamp_ns=self.des.now_ns, reason=reason)
            self._reconcile_transfer_terminal(task, clock=self.des)
        else:
            raise BaselineCoordinatorError("transfer has an unsupported active status")
        self._append(
            "BASELINE_TRANSFER_ABORTED",
            {
                "transfer_id": task.metadata.transfer_id,
                "request_id": launch.request_id,
                "route_version": task.metadata.route_version,
                "reason": reason,
                "outcome": outcome.value,
                "started": launch.started,
            },
        )

    def _reconcile_transfer_terminal(
        self,
        task: TransferTask,
        *,
        clock: GlobalDES,
    ) -> None:
        if clock is not self.des:
            raise BaselineCoordinatorError("transfer terminal callback used another DES")
        try:
            launch = self._transfer_launches[task.metadata.transfer_id]
        except KeyError as error:
            raise BaselineCoordinatorError(
                "terminal transfer has no baseline launch binding"
            ) from error
        if launch.task is not task or not task.status.terminal:
            raise BaselineCoordinatorError("terminal transfer binding is inconsistent")
        if launch.reconciled:
            raise BaselineCoordinatorError("Store transfer was reconciled more than once")
        launch.client.reconcile_transfer_terminal(
            task.metadata.transfer_id,
            timestamp_ns=clock.now_ns,
        )
        launch.reconciled = True
        if not launch.failure_canceling:
            if launch.operation_handle is None:
                raise BaselineCoordinatorError("terminal transfer lost its operation handle")
            self.failure_controller.complete_operation(launch.operation_handle)
        self._append(
            "BASELINE_TRANSFER_TERMINAL_RECONCILED",
            {
                "transfer_id": task.metadata.transfer_id,
                "request_id": launch.request_id,
                "route_version": task.metadata.route_version,
                "status": task.status.value,
                "terminal_ns": task.end_ns,
            },
        )
        if launch.terminal_callback is not None:
            launch.terminal_callback(task, clock)

    def _on_forward_complete(self, event: ScheduledEvent, des: GlobalDES) -> None:
        if set(event.payload) == {"batch", "replica_id"}:
            self._on_forward_batch_complete(event, des)
            return
        expected = {
            "request_id",
            "route_version",
            "produces_output",
            "output_index",
        }
        if set(event.payload) != expected:
            raise BaselineCoordinatorError("FORWARD_COMPLETE payload is not exact")
        request_id = event.payload["request_id"]
        route_version = event.payload["route_version"]
        produces_output = event.payload["produces_output"]
        output_index = event.payload["output_index"]
        if (
            not isinstance(request_id, str)
            or type(route_version) is not int
            or type(produces_output) is not bool
            or (output_index is not None and type(output_index) is not int)
            or produces_output != (output_index is not None)
        ):
            raise BaselineCoordinatorError("FORWARD_COMPLETE payload types are invalid")
        self.failure_controller.complete_operation(EventHandle(event.event_id))
        if produces_output:
            des.schedule_at(
                des.now_ns,
                EventKind.REQUEST_COMPLETE,
                event_id=f"{event.event_id}:activate-output",
                payload={
                    "request_id": request_id,
                    "route_version": route_version,
                    "output_index": output_index,
                },
            )
        callback = self._forward_terminal_callbacks.pop(event.event_id, None)
        if callback is not None:
            callback(event, des)

    def _on_forward_batch_complete(
        self,
        event: ScheduledEvent,
        des: GlobalDES,
    ) -> None:
        replica_id = event.payload["replica_id"]
        raw_batch = event.payload["batch"]
        if not isinstance(replica_id, str) or replica_id not in self._replicas:
            raise BaselineCoordinatorError("forward batch names an unknown replica")
        if not isinstance(raw_batch, list) or not raw_batch:
            raise BaselineCoordinatorError("forward batch payload must be a non-empty list")
        participants: list[ForwardBatchParticipant] = []
        for raw_item in raw_batch:
            if not isinstance(raw_item, dict) or set(raw_item) != {
                "request_id",
                "route_version",
                "target_id",
                "produces_output",
                "output_index",
            }:
                raise BaselineCoordinatorError("forward batch participant payload is not exact")
            try:
                participants.append(
                    ForwardBatchParticipant(
                        request_id=raw_item["request_id"],
                        route_version=raw_item["route_version"],
                        target_id=raw_item["target_id"],
                        produces_output=raw_item["produces_output"],
                        output_index=raw_item["output_index"],
                    )
                )
            except (TypeError, ValueError) as error:
                raise BaselineCoordinatorError(
                    f"forward batch participant is invalid: {error}"
                ) from error
        participant_tuple = tuple(participants)
        if len({item.request_id for item in participant_tuple}) != len(participant_tuple):
            raise BaselineCoordinatorError("forward batch request IDs are not unique")

        fence_reason = self._forward_batch_fence_reason(
            replica_id,
            participant_tuple,
        )
        self.failure_controller.complete_operation(EventHandle(event.event_id))
        accepted = fence_reason is None
        if accepted:
            for item in participant_tuple:
                if not item.produces_output:
                    continue
                if item.output_index is None:
                    raise BaselineCoordinatorError(
                        "accepted output participant has no output index"
                    )
                des.schedule_at(
                    des.now_ns,
                    EventKind.REQUEST_COMPLETE,
                    event_id=(
                        f"{event.event_id}:activate-output:{item.request_id}:{item.output_index}"
                    ),
                    payload={
                        "request_id": item.request_id,
                        "route_version": item.route_version,
                        "output_index": item.output_index,
                    },
                )
        terminal = ForwardBatchTerminal(
            event_id=event.event_id,
            replica_id=replica_id,
            participants=participant_tuple,
            accepted=accepted,
            fence_reason=fence_reason,
        )
        self._append(
            ("BASELINE_FORWARD_BATCH_COMPLETED" if accepted else "BASELINE_FORWARD_BATCH_FENCED"),
            terminal.to_dict(),
        )
        callback = self._forward_batch_terminal_callbacks.pop(event.event_id, None)
        if callback is not None:
            callback(terminal, des)

    def _forward_batch_fence_reason(
        self,
        replica_id: str,
        participants: tuple[ForwardBatchParticipant, ...],
    ) -> str | None:
        if replica_id not in self._replicas:
            return "UNKNOWN_REPLICA"
        for item in participants:
            if item.target_id != replica_id:
                return f"CROSS_REPLICA:{item.request_id}"
            try:
                authority = self.router.require_route(
                    item.request_id,
                    route_version=item.route_version,
                    target_replica_id=replica_id,
                )
                attempt = self.failure_controller.attempt(
                    item.request_id,
                    item.route_version,
                )
                request = self._requests[(item.request_id, item.route_version)]
            except (KeyError, RouterError, ValueError):
                return f"STALE_ROUTE:{item.request_id}@{item.route_version}"
            if authority.target_replica_id != replica_id:
                return f"TARGET_MISMATCH:{item.request_id}@{item.route_version}"
            if attempt.status is not AttemptStatus.ACTIVE:
                return f"INACTIVE_ROUTE:{item.request_id}@{item.route_version}"
            if request.finished:
                return f"FINISHED_REQUEST:{item.request_id}@{item.route_version}"
        if not self.failure_controller.target_is_healthy(replica_id):
            return f"UNHEALTHY_TARGET:{replica_id}"
        return None

    def _append(self, record_type: str, data: dict[str, object]) -> None:
        self.des.journal.append(self.des.now_ns, record_type, data)


def _scheduled_request(output: SchedulerOutput, request_id: str) -> ScheduledRequest:
    matches = tuple(
        item
        for item in (
            *output.scheduled_running_reqs,
            *output.scheduled_new_reqs,
            *output.scheduled_resumed_reqs,
        )
        if item.request_id == request_id
    )
    if len(matches) != 1:
        raise BaselineCoordinatorError(
            "scheduler output must contain exactly one silent replay request"
        )
    return matches[0]


def _compact_scheduler_output(output: SchedulerOutput) -> dict[str, object]:
    """Retain scheduler semantics without repeating unbounded block-ID arrays.

    Allocation and ledger mutation records remain the reconstructable source of
    physical state.  The ordered summaries retain scheduler control semantics;
    hashes bind every omitted block list and the complete source-shaped output.
    """

    scheduled_items = (
        *output.scheduled_running_reqs,
        *output.scheduled_new_reqs,
        *output.scheduled_resumed_reqs,
    )
    scheduled_by_id = {item.request_id: item for item in scheduled_items}
    if len(scheduled_by_id) != len(scheduled_items) or set(scheduled_by_id) != set(
        output.scheduled_req_ids
    ):
        raise BaselineCoordinatorError(
            "scheduler output IDs diverge from its scheduled request records"
        )
    participants: list[dict[str, object]] = []
    for request_id in output.scheduled_req_ids:
        item = scheduled_by_id[request_id]
        participants.append(
            {
                "request_id": item.request_id,
                "origin": item.origin.value,
                "phase": item.phase.value,
                "num_scheduled_tokens": item.num_scheduled_tokens,
                "num_computed_tokens_before": item.num_computed_tokens_before,
                "num_computed_tokens_after": item.num_computed_tokens_after,
                "new_block_count": len(item.new_block_ids),
                "new_block_ids_sha256": sha256_json(item.new_block_ids),
                "block_count": len(item.block_ids),
                "block_ids_sha256": sha256_json(item.block_ids),
                "recompute": item.recompute,
                "chunked": item.chunked,
            }
        )
    return {
        "scheduled_requests": participants,
        "total_num_scheduled_tokens": output.total_num_scheduled_tokens,
        "token_budget_remaining": output.token_budget_remaining,
        "preempted_req_ids": list(output.preempted_req_ids),
        "scheduler_output_sha256": sha256_json(output.to_dict()),
        "scheduler_source_sha256": output.source_sha256,
        "evidence_class": output.evidence_class,
    }


def _scheduled_request_produces_output(
    item: ScheduledRequest,
    request: Request,
) -> bool:
    """Validate an E2 scheduler result and identify a sampled replay output."""

    if request.num_computed_tokens != item.num_computed_tokens_after:
        raise BaselineCoordinatorError(
            "silent replay scheduled counters diverge from the live request"
        )
    remaining_before = request.num_tokens - item.num_computed_tokens_before
    if remaining_before <= 0:
        raise BaselineCoordinatorError("silent replay scheduled no materialized work")
    expected_chunked = item.num_scheduled_tokens < remaining_before
    if item.chunked is not expected_chunked:
        raise BaselineCoordinatorError("silent replay chunked flag is inconsistent")
    if item.phase is SchedulingPhase.PREFILL:
        if item.num_computed_tokens_before >= request.prompt_tokens:
            raise BaselineCoordinatorError("silent replay prefill starts past the prompt")
        if item.num_computed_tokens_after > request.prompt_tokens:
            raise BaselineCoordinatorError("silent replay prefill crosses the prompt boundary")
        if item.chunked:
            if item.num_computed_tokens_after >= request.prompt_tokens:
                raise BaselineCoordinatorError(
                    "chunked silent replay prefill cannot sample an output"
                )
            return False
        if item.num_computed_tokens_after != request.prompt_tokens:
            raise BaselineCoordinatorError(
                "terminal silent replay prefill did not complete the prompt"
            )
        return True
    if item.phase is SchedulingPhase.DECODE:
        if (
            item.num_computed_tokens_before < request.prompt_tokens
            or item.num_scheduled_tokens != 1
            or item.chunked
        ):
            raise BaselineCoordinatorError("silent replay decode is not an ordinary one-token step")
        return True
    raise BaselineCoordinatorError("silent replay scheduler phase is unsupported")
