"""Deterministic execution driver for the strict Qwen3-32B DP8/TP4 contract.

This module expands one logical KV chunk into four rank-local transfers and
drives :mod:`moonkvsim.aegiskv.tp_recovery` transactions.  Its isolated pure
integer helpers remain available for unit contracts; the formal Qwen3-32B
runner uses ``execute_des_failure_recovery`` so those transactions execute on
the Qwen3-32B GlobalDES resource surface.

KV recovery ends after rank-local load/activation, a readiness barrier, and a
directory-generation install.  A later model-forward all-reduce is recorded as
separate work and is excluded from KV byte conservation and recovery latency.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from moonkvsim.aegiskv.qwen3_32b_tp4_config import Qwen3TP4EngineConfig
from moonkvsim.aegiskv.tp_recovery import (
    TPChunkPathTransaction,
    TPCollectiveKind,
    TPLayoutIdentity,
    TPRecoveryPlan,
    TPShardPlacement,
)
from moonkvsim.aegiskv.types import PathCommitState, PolicyPool, require_nonnegative_int

_NS_PER_SECOND: Final = 1_000_000_000
_STORE_NODE_ID: Final = "store-dram-service"


class ShardTransferStatus(StrEnum):
    ACKED = "ACKED"
    NO_ACK = "NO_ACK"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


@dataclass(frozen=True, slots=True)
class FailureSet:
    """Unavailable inference resources for GPU- and node-failure recovery."""

    failed_gpu_ids: frozenset[str] = frozenset()
    failed_node_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for name, values in (
            ("failed_gpu_ids", self.failed_gpu_ids),
            ("failed_node_ids", self.failed_node_ids),
        ):
            if type(values) is not frozenset:
                raise TypeError(f"{name} must be an exact frozenset")
            if any(type(value) is not str or not value for value in values):
                raise ValueError(f"{name} must contain only non-empty strings")

    def rank_is_failed(self, *, node_id: str, gpu_id: str) -> bool:
        return node_id in self.failed_node_ids or gpu_id in self.failed_gpu_ids


@dataclass(frozen=True, slots=True)
class PathExecutionControl:
    """Testable transfer outcomes; omitted ranks remain unacknowledged PENDING."""

    no_ack_tp_ranks: frozenset[int] = frozenset()
    failed_tp_ranks: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        for name, values in (
            ("no_ack_tp_ranks", self.no_ack_tp_ranks),
            ("failed_tp_ranks", self.failed_tp_ranks),
        ):
            if type(values) is not frozenset:
                raise TypeError(f"{name} must be an exact frozenset")
            for value in values:
                require_nonnegative_int(value, f"{name} item")
        if self.no_ack_tp_ranks & self.failed_tp_ranks:
            raise ValueError("one TP rank cannot be both failed and no-ACK")


@dataclass(frozen=True, slots=True)
class ShardTransferRecord:
    pool: PolicyPool
    tp_rank: int
    source_node_id: str
    destination_node_id: str
    source_resource_id: str
    destination_resource_id: str
    rate_resource_ids: tuple[str, ...]
    shard_bytes: int
    transferred_bytes: int
    start_ns: int
    complete_ns: int | None
    status: ShardTransferStatus

    def __post_init__(self) -> None:
        if type(self.pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        require_nonnegative_int(self.tp_rank, "tp_rank")
        for name, value in (
            ("source_node_id", self.source_node_id),
            ("destination_node_id", self.destination_node_id),
            ("source_resource_id", self.source_resource_id),
            ("destination_resource_id", self.destination_resource_id),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.rate_resource_ids) is not tuple or not self.rate_resource_ids:
            raise ValueError("rate_resource_ids must be a non-empty tuple")
        if len(set(self.rate_resource_ids)) != len(self.rate_resource_ids):
            raise ValueError("rate_resource_ids must be unique")
        if type(self.shard_bytes) is not int or self.shard_bytes <= 0:
            raise ValueError("shard_bytes must be positive")
        require_nonnegative_int(self.transferred_bytes, "transferred_bytes")
        if self.transferred_bytes > self.shard_bytes:
            raise ValueError("transferred_bytes cannot exceed shard_bytes")
        require_nonnegative_int(self.start_ns, "start_ns")
        if self.complete_ns is not None:
            require_nonnegative_int(self.complete_ns, "complete_ns")
            if self.complete_ns < self.start_ns:
                raise ValueError("complete_ns cannot precede start_ns")
        if type(self.status) is not ShardTransferStatus:
            raise TypeError("status must be an exact ShardTransferStatus")
        if self.status is ShardTransferStatus.CANCELED and self.complete_ns is not None:
            raise ValueError("a canceled transfer cannot have a completion time")


@dataclass(frozen=True, slots=True)
class PathByteConservationAudit:
    pool: PolicyPool
    logical_chunk_bytes: int
    sum_rank_shard_bytes: int
    source_read_bytes: int
    destination_write_bytes: int
    acknowledged_bytes: int
    committed_bytes: int
    kv_reduction_bytes: int
    valid: bool


@dataclass(frozen=True, slots=True)
class RankResourceAudit:
    phase: str
    pool: PolicyPool
    tp_rank: int
    node_id: str
    gpu_resource_id: str
    resource_ids: tuple[str, ...]
    kv_bytes: int
    transfer_bytes: int
    activated_bytes: int
    model_collective_bytes: int


@dataclass(frozen=True, slots=True)
class NodeResourceAudit:
    node_id: str
    resource_ids: tuple[str, ...]
    kv_source_read_bytes: int
    kv_destination_write_bytes: int
    kv_activated_bytes: int
    model_collective_bytes: int


@dataclass(slots=True)
class _MutableNodeAudit:
    resource_ids: set[str] = field(default_factory=set)
    kv_source_read_bytes: int = 0
    kv_destination_write_bytes: int = 0
    kv_activated_bytes: int = 0
    model_collective_bytes: int = 0


@dataclass(slots=True)
class PathProtectionExecution:
    transaction: TPChunkPathTransaction
    transfers: tuple[ShardTransferRecord, ...]
    byte_audit: PathByteConservationAudit

    @property
    def state(self) -> PathCommitState:
        return self.transaction.state


@dataclass(slots=True)
class ProtectedLogicalChunk:
    logical_chunk_id: str
    source_dp_rank: int
    token_count: int
    logical_chunk_bytes: int
    shard_bytes: int
    route_version: int
    layout: TPLayoutIdentity
    peer_hbm: PathProtectionExecution
    store_dram: PathProtectionExecution
    rank_resources: tuple[RankResourceAudit, ...]
    node_resources: tuple[NodeResourceAudit, ...]
    fingerprint: str

    def path(self, pool: PolicyPool) -> PathProtectionExecution:
        if pool is PolicyPool.PEER_HBM:
            return self.peer_hbm
        if pool is PolicyPool.STORE_DRAM:
            return self.store_dram
        raise TypeError("pool must be an exact PolicyPool")


@dataclass(frozen=True, slots=True)
class RankRecoveryCost:
    tp_rank: int
    source_node_id: str
    destination_node_id: str
    source_resource_id: str
    destination_gpu_id: str
    source_resource_ids: tuple[str, ...]
    destination_resource_ids: tuple[str, ...]
    restored_kv_bytes: int
    transfer_bytes: int
    activation_bytes: int
    start_ns: int
    complete_ns: int

    @property
    def duration_ns(self) -> int:
        return self.complete_ns - self.start_ns


@dataclass(frozen=True, slots=True)
class BarrierCost:
    participant_gpu_ids: tuple[str, ...]
    resource_id: str
    start_ns: int
    complete_ns: int
    payload_bytes: int

    @property
    def duration_ns(self) -> int:
        return self.complete_ns - self.start_ns


@dataclass(frozen=True, slots=True)
class DirectoryInstallCost:
    resource_id: str
    start_ns: int
    complete_ns: int

    @property
    def duration_ns(self) -> int:
        return self.complete_ns - self.start_ns


@dataclass(frozen=True, slots=True)
class ModelForwardAllReduceCost:
    participant_gpu_ids: tuple[str, ...]
    resource_id: str
    payload_bytes_per_rank: int
    total_collective_bytes: int
    start_ns: int
    complete_ns: int
    operates_on_kv: bool
    included_in_kv_recovery_latency: bool

    @property
    def duration_ns(self) -> int:
        return self.complete_ns - self.start_ns


@dataclass(frozen=True, slots=True)
class DESEventExecution:
    timestamp_ns: int
    event_id: str
    kind: str


@dataclass(frozen=True, slots=True)
class Algorithm3ControlInput:
    target_dp_rank: int
    timestamp_ns: int
    foreground_pressure: bool
    reason: str

    def __post_init__(self) -> None:
        require_nonnegative_int(self.target_dp_rank, "target_dp_rank")
        require_nonnegative_int(self.timestamp_ns, "timestamp_ns")
        if type(self.foreground_pressure) is not bool:
            raise TypeError("foreground_pressure must be a bool")
        if type(self.reason) is not str or not self.reason:
            raise ValueError("reason must be a non-empty string")


@dataclass(frozen=True, slots=True)
class Algorithm3ExecutionAudit:
    target_dp_rank: int
    timestamp_ns: int
    action: str
    reason: str
    previous_fraction: str
    next_fraction: str
    previous_stable_windows: int
    next_stable_windows: int
    quota_bytes_per_rank: int
    peer_usage_bytes_per_rank: tuple[int, ...]
    resident_primary_bytes_per_rank: tuple[int, ...]
    free_reclaimable_bytes_per_rank: tuple[int, ...]
    quota_enforced: bool
    decision_fingerprint: str


@dataclass(frozen=True, slots=True)
class DESExecutionEvidence:
    evidence_class: str
    journal_sha256: str
    journal_record_count: int
    event_trace: tuple[DESEventExecution, ...]
    fenced_dp_ranks: tuple[int, ...]
    failure_fence_event_count: int
    protection_path_states: tuple[tuple[str, str, tuple[int, ...], bool], ...]
    recovery_phase: str
    four_shard_recovery_executed: bool
    capacity_conservation_valid: bool
    algorithm2_four_shard_transaction_surface_executed: bool
    algorithm3_peer_quota_surface_enforced: bool
    algorithm3_controller_integration: str
    algorithm3_audit: tuple[Algorithm3ExecutionAudit, ...]


@dataclass(frozen=True, slots=True)
class RecoveryByteConservationAudit:
    pool: PolicyPool
    logical_chunk_bytes: int
    sum_rank_restored_kv_bytes: int
    source_read_bytes: int
    destination_write_bytes: int
    activated_bytes: int
    kv_reduction_bytes: int
    model_collective_bytes_excluded: int
    valid: bool


@dataclass(frozen=True, slots=True)
class RecoveryExecution:
    logical_chunk_id: str
    pool: PolicyPool
    destination_dp_rank: int
    failures: FailureSet
    plan: TPRecoveryPlan
    rank_costs: tuple[RankRecoveryCost, ...]
    barrier: BarrierCost
    directory_install: DirectoryInstallCost
    kv_recovery_start_ns: int
    kv_recovery_complete_ns: int
    model_forward_all_reduce: ModelForwardAllReduceCost
    rank_resources: tuple[RankResourceAudit, ...]
    node_resources: tuple[NodeResourceAudit, ...]
    byte_audit: RecoveryByteConservationAudit
    fingerprint: str
    des_evidence: DESExecutionEvidence | None = None

    @property
    def kv_recovery_latency_ns(self) -> int:
        return self.kv_recovery_complete_ns - self.kv_recovery_start_ns


def _duration_ns(*, byte_count: int, bandwidth_bytes_per_second: int, setup_ns: int) -> int:
    require_nonnegative_int(byte_count, "byte_count")
    if type(bandwidth_bytes_per_second) is not int or bandwidth_bytes_per_second <= 0:
        raise ValueError("bandwidth_bytes_per_second must be positive")
    require_nonnegative_int(setup_ns, "setup_ns")
    payload_ns = (
        byte_count * _NS_PER_SECOND + bandwidth_bytes_per_second - 1
    ) // bandwidth_bytes_per_second
    return setup_ns + payload_ns


def _canonical_fingerprint(document: dict[str, object]) -> str:
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _node_audits(rank_audits: tuple[RankResourceAudit, ...]) -> tuple[NodeResourceAudit, ...]:
    rows: dict[str, _MutableNodeAudit] = {}
    for item in rank_audits:
        row = rows.setdefault(item.node_id, _MutableNodeAudit())
        row.resource_ids.update(item.resource_ids)
        if item.phase.endswith("_SOURCE"):
            row.kv_source_read_bytes += item.transfer_bytes
        if item.phase.endswith("_DESTINATION"):
            row.kv_destination_write_bytes += item.transfer_bytes
        row.kv_activated_bytes += item.activated_bytes
        row.model_collective_bytes += item.model_collective_bytes
    return tuple(
        NodeResourceAudit(
            node_id=node_id,
            resource_ids=tuple(sorted(row.resource_ids)),
            kv_source_read_bytes=row.kv_source_read_bytes,
            kv_destination_write_bytes=row.kv_destination_write_bytes,
            kv_activated_bytes=row.kv_activated_bytes,
            model_collective_bytes=row.model_collective_bytes,
        )
        for node_id, row in sorted(rows.items())
    )


class Qwen3TP4ExecutionDriver:
    """Pure integer cost driver over the strict DP8/TP4 configuration."""

    def __init__(self, config: Qwen3TP4EngineConfig) -> None:
        if type(config) is not Qwen3TP4EngineConfig:
            raise TypeError("config must be an exact Qwen3TP4EngineConfig")
        self.config = config
        self.layout = TPLayoutIdentity(
            model_revision=config.model.revision,
            kv_abi="qwen3-bfloat16-kv-v1",
            layout_id="qwen3-32b-tp4-pp1",
            tensor_parallel_size=config.parallelism.tensor_parallel_size,
            pipeline_parallel_size=config.parallelism.pipeline_parallel_size,
        )
        self._ranks = {(rank.dp_rank, rank.tp_rank): rank for rank in config.rank_placements}

    def protect_logical_chunk(
        self,
        *,
        logical_chunk_id: str,
        source_dp_rank: int,
        token_count: int,
        route_version: int,
        start_ns: int = 0,
        peer_control: PathExecutionControl | None = None,
        store_control: PathExecutionControl | None = None,
    ) -> ProtectedLogicalChunk:
        if type(logical_chunk_id) is not str or not logical_chunk_id:
            raise ValueError("logical_chunk_id must be a non-empty string")
        self._validate_dp_rank(source_dp_rank)
        if type(token_count) is not int or token_count <= 0:
            raise ValueError("token_count must be a positive integer")
        require_nonnegative_int(route_version, "route_version")
        require_nonnegative_int(start_ns, "start_ns")
        resolved_peer_control = peer_control or PathExecutionControl()
        resolved_store_control = store_control or PathExecutionControl()
        self._validate_control(resolved_peer_control)
        self._validate_control(resolved_store_control)

        shard_bytes = token_count * self.config.model.kv_bytes_per_token_per_tp_rank
        logical_bytes = token_count * self.config.model.kv_bytes_per_token_total
        peer = self._execute_path(
            logical_chunk_id=logical_chunk_id,
            source_dp_rank=source_dp_rank,
            shard_bytes=shard_bytes,
            logical_bytes=logical_bytes,
            route_version=route_version,
            start_ns=start_ns,
            pool=PolicyPool.PEER_HBM,
            control=resolved_peer_control,
        )
        store = self._execute_path(
            logical_chunk_id=logical_chunk_id,
            source_dp_rank=source_dp_rank,
            shard_bytes=shard_bytes,
            logical_bytes=logical_bytes,
            route_version=route_version,
            start_ns=start_ns,
            pool=PolicyPool.STORE_DRAM,
            control=resolved_store_control,
        )
        rank_resources = self._protection_rank_audits(peer, store)
        fingerprint = _canonical_fingerprint(
            {
                "logical_chunk_id": logical_chunk_id,
                "logical_chunk_bytes": logical_bytes,
                "peer": self._path_fingerprint_document(peer),
                "route_version": route_version,
                "source_dp_rank": source_dp_rank,
                "store": self._path_fingerprint_document(store),
                "token_count": token_count,
            }
        )
        return ProtectedLogicalChunk(
            logical_chunk_id=logical_chunk_id,
            source_dp_rank=source_dp_rank,
            token_count=token_count,
            logical_chunk_bytes=logical_bytes,
            shard_bytes=shard_bytes,
            route_version=route_version,
            layout=self.layout,
            peer_hbm=peer,
            store_dram=store,
            rank_resources=rank_resources,
            node_resources=_node_audits(rank_resources),
            fingerprint=fingerprint,
        )

    def recover_logical_chunk(
        self,
        protected: ProtectedLogicalChunk,
        *,
        pool: PolicyPool,
        failures: FailureSet,
        start_ns: int,
        directory_install_ns: int,
        model_forward_all_reduce_bytes_per_rank: int,
        destination_dp_rank: int | None = None,
        requested_layout: TPLayoutIdentity | None = None,
        peer_activation_ns_by_rank: tuple[int, ...] | None = None,
    ) -> RecoveryExecution:
        if type(protected) is not ProtectedLogicalChunk:
            raise TypeError("protected must be an exact ProtectedLogicalChunk")
        if type(pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        if type(failures) is not FailureSet:
            raise TypeError("failures must be an exact FailureSet")
        require_nonnegative_int(start_ns, "start_ns")
        require_nonnegative_int(directory_install_ns, "directory_install_ns")
        if (
            type(model_forward_all_reduce_bytes_per_rank) is not int
            or model_forward_all_reduce_bytes_per_rank <= 0
        ):
            raise ValueError("model forward all-reduce bytes/rank must be positive")
        self._validate_failure_ids(failures)

        path = protected.path(pool)
        if path.state is not PathCommitState.COMMITTED:
            raise ValueError("recovery requires a committed all-shard protection path")
        if protected.layout != self.layout:
            raise ValueError("protected chunk layout is incompatible with this driver")
        layout = requested_layout or protected.layout
        if type(layout) is not TPLayoutIdentity:
            raise TypeError("requested_layout must be an exact TPLayoutIdentity")

        destination_dp = self._recovery_destination_dp(
            protected=protected,
            pool=pool,
            failures=failures,
            destination_dp_rank=destination_dp_rank,
        )
        destination_ranks = tuple(
            self._ranks[(destination_dp, tp_rank)]
            for tp_rank in range(self.config.parallelism.tensor_parallel_size)
        )
        destination_gpu_ids = tuple(rank.resource_id for rank in destination_ranks)
        nvlink_resource = f"node:{destination_ranks[0].node_id}:nvlink"
        plan = path.transaction.build_recovery_plan(
            route_version=protected.route_version,
            layout=layout,
            destination_gpu_ids=destination_gpu_ids,
            nvlink_rate_resource_id=nvlink_resource,
            model_all_reduce_bytes_per_rank=model_forward_all_reduce_bytes_per_rank,
        )
        if tuple(item.kind for item in plan.collectives) != (
            TPCollectiveKind.ACTIVATION_BARRIER,
            TPCollectiveKind.MODEL_ALL_REDUCE,
        ):
            raise ValueError("TP recovery plan collective ordering drift")

        activation_costs = self._peer_activation_costs(peer_activation_ns_by_rank)
        rank_costs = self._rank_recovery_costs(
            protected=protected,
            pool=pool,
            destination_dp_rank=destination_dp,
            start_ns=start_ns,
            activation_ns_by_rank=activation_costs,
        )
        max_rank_complete_ns = max(item.complete_ns for item in rank_costs)
        barrier_overhead = self.config.modeled_costs.tp_collective_sync.fixed_overhead_ns
        barrier = BarrierCost(
            participant_gpu_ids=destination_gpu_ids,
            resource_id=nvlink_resource,
            start_ns=max_rank_complete_ns,
            complete_ns=max_rank_complete_ns + barrier_overhead,
            payload_bytes=0,
        )
        directory = DirectoryInstallCost(
            resource_id=f"directory:{destination_ranks[0].node_id}:generation-install",
            start_ns=barrier.complete_ns,
            complete_ns=barrier.complete_ns + directory_install_ns,
        )
        forward_link = self.config.modeled_costs.intra_node_nvlink
        forward_duration = _duration_ns(
            byte_count=model_forward_all_reduce_bytes_per_rank,
            bandwidth_bytes_per_second=forward_link.effective_bandwidth_bytes_per_second,
            setup_ns=forward_link.setup_ns,
        )
        model_collective = ModelForwardAllReduceCost(
            participant_gpu_ids=destination_gpu_ids,
            resource_id=nvlink_resource,
            payload_bytes_per_rank=model_forward_all_reduce_bytes_per_rank,
            total_collective_bytes=(
                model_forward_all_reduce_bytes_per_rank
                * self.config.parallelism.tensor_parallel_size
            ),
            start_ns=directory.complete_ns,
            complete_ns=directory.complete_ns + forward_duration,
            operates_on_kv=False,
            included_in_kv_recovery_latency=False,
        )
        rank_resources = self._recovery_rank_audits(
            pool=pool,
            rank_costs=rank_costs,
            barrier=barrier,
            directory=directory,
            model_collective=model_collective,
        )
        byte_audit = self._recovery_byte_audit(
            protected=protected,
            pool=pool,
            rank_costs=rank_costs,
            model_collective=model_collective,
        )
        fingerprint = _canonical_fingerprint(
            {
                "barrier": [barrier.start_ns, barrier.complete_ns],
                "byte_audit_valid": byte_audit.valid,
                "destination_dp_rank": destination_dp,
                "directory": [directory.start_ns, directory.complete_ns],
                "failures": {
                    "gpus": sorted(failures.failed_gpu_ids),
                    "nodes": sorted(failures.failed_node_ids),
                },
                "forward": [
                    model_collective.payload_bytes_per_rank,
                    model_collective.start_ns,
                    model_collective.complete_ns,
                ],
                "logical_chunk_id": protected.logical_chunk_id,
                "pool": pool.value,
                "rank_costs": [
                    [
                        item.tp_rank,
                        item.source_resource_id,
                        item.destination_gpu_id,
                        list(item.source_resource_ids),
                        list(item.destination_resource_ids),
                        item.restored_kv_bytes,
                        item.transfer_bytes,
                        item.activation_bytes,
                        item.complete_ns,
                    ]
                    for item in rank_costs
                ],
                "start_ns": start_ns,
            }
        )
        return RecoveryExecution(
            logical_chunk_id=protected.logical_chunk_id,
            pool=pool,
            destination_dp_rank=destination_dp,
            failures=failures,
            plan=plan,
            rank_costs=rank_costs,
            barrier=barrier,
            directory_install=directory,
            kv_recovery_start_ns=start_ns,
            kv_recovery_complete_ns=directory.complete_ns,
            model_forward_all_reduce=model_collective,
            rank_resources=rank_resources,
            node_resources=_node_audits(rank_resources),
            byte_audit=byte_audit,
            fingerprint=fingerprint,
        )

    def execute_des_failure_recovery(
        self,
        *,
        logical_chunk_id: str,
        source_dp_rank: int,
        token_count: int,
        route_version: int,
        protection_start_ns: int,
        failure_id: str,
        failure_at_ns: int,
        failures: FailureSet,
        pool: PolicyPool,
        recovery_start_ns: int,
        directory_install_ns: int,
        model_forward_all_reduce_bytes_per_rank: int,
        destination_dp_rank: int | None = None,
        peer_activation_ns_by_rank: tuple[int, ...] | None = None,
        peer_control: PathExecutionControl | None = None,
        store_control: PathExecutionControl | None = None,
        algorithm3_control_events: tuple[Algorithm3ControlInput, ...] = (),
    ) -> RecoveryExecution:
        """Execute one complete protection/fence/recovery scenario on GlobalDES.

        The older ``protect_logical_chunk`` and ``recover_logical_chunk`` methods
        remain pure integer helpers for isolated contract tests.  Formal runner
        results use this method so the four protection shards, group fence, four
        recovery shards, barrier, directory publication, and following model
        collective all cross the event journal and physical capacity ledgers.
        """

        # Local import avoids the deliberate DES -> PathExecutionControl import
        # while preserving the public execution-module API.
        from moonkvsim.aegiskv.qwen3_32b_tp4_des import (
            EVIDENCE_CLASS,
            Qwen3TP4GroupDES,
            RecoveryPhase,
        )

        if type(logical_chunk_id) is not str or not logical_chunk_id:
            raise ValueError("logical_chunk_id must be a non-empty string")
        if type(failure_id) is not str or not failure_id:
            raise ValueError("failure_id must be a non-empty string")
        self._validate_dp_rank(source_dp_rank)
        if type(token_count) is not int or token_count <= 0:
            raise ValueError("token_count must be a positive integer")
        require_nonnegative_int(route_version, "route_version")
        require_nonnegative_int(protection_start_ns, "protection_start_ns")
        require_nonnegative_int(failure_at_ns, "failure_at_ns")
        require_nonnegative_int(recovery_start_ns, "recovery_start_ns")
        if protection_start_ns > failure_at_ns or recovery_start_ns < failure_at_ns:
            raise ValueError("protection/failure/recovery timestamps are not ordered")
        if type(failures) is not FailureSet:
            raise TypeError("failures must be an exact FailureSet")
        if type(pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        self._validate_failure_ids(failures)
        activation = self._peer_activation_costs(peer_activation_ns_by_rank)
        if pool is PolicyPool.STORE_DRAM and any(activation):
            raise ValueError("Store recovery cannot consume Peer-HBM activation costs")
        if type(algorithm3_control_events) is not tuple:
            raise TypeError("algorithm3_control_events must be an exact tuple")
        if not algorithm3_control_events:
            raise ValueError("formal DES execution requires Algorithm 3 control events")
        if any(type(item) is not Algorithm3ControlInput for item in algorithm3_control_events):
            raise TypeError("Algorithm 3 control events must be exact values")

        failed_dp_ranks: list[int] = []
        failed_tp_rank_by_dp: dict[int, int] = {}
        for dp_rank in range(self.config.parallelism.data_parallel_size):
            ranks = tuple(
                self._ranks[(dp_rank, tp_rank)]
                for tp_rank in range(self.config.parallelism.tensor_parallel_size)
            )
            failed_ranks = [
                rank.tp_rank
                for rank in ranks
                if failures.rank_is_failed(
                    node_id=rank.node_id,
                    gpu_id=rank.resource_id,
                )
            ]
            if failed_ranks:
                failed_dp_ranks.append(dp_rank)
                failed_tp_rank_by_dp[dp_rank] = min(failed_ranks)
        if source_dp_rank not in failed_dp_ranks:
            raise ValueError("failure set does not fence the source TP4 group")

        des = Qwen3TP4GroupDES(self.config)
        protection = des.protect_logical_chunk(
            logical_chunk_id=logical_chunk_id,
            source_dp_rank=source_dp_rank,
            token_count=token_count,
            route_version=route_version,
            start_ns=protection_start_ns,
            peer_control=peer_control,
            store_control=store_control,
        )
        for control_event in algorithm3_control_events:
            if control_event.target_dp_rank >= self.config.parallelism.data_parallel_size:
                raise ValueError("Algorithm 3 target is outside the DP8 topology")
            if not protection_start_ns <= control_event.timestamp_ns < failure_at_ns:
                raise ValueError("Algorithm 3 event must execute after release and before failure")
            des.schedule_algorithm3_control(
                target_dp_rank=control_event.target_dp_rank,
                at_ns=control_event.timestamp_ns,
                foreground_pressure=control_event.foreground_pressure,
                reason=control_event.reason,
            )
        for dp_rank in failed_dp_ranks:
            des.schedule_rank_failure(
                failure_id=f"{failure_id}:dp{dp_rank}",
                dp_rank=dp_rank,
                tp_rank=failed_tp_rank_by_dp[dp_rank],
                at_ns=failure_at_ns,
            )
        des.run(until_ns=failure_at_ns)
        if source_dp_rank not in des.fenced_dp_ranks:
            raise RuntimeError("source TP4 failure did not execute its group fence")
        selected_path = protection.path(pool)
        if (
            selected_path.state is not PathCommitState.COMMITTED
            or not selected_path.capacity_committed
        ):
            raise ValueError("selected protection path was not committed before failure")

        recovery = des.recover_logical_chunk(
            protection,
            pool=pool,
            start_ns=recovery_start_ns,
            directory_install_ns=directory_install_ns,
            first_forward_bytes_per_rank=model_forward_all_reduce_bytes_per_rank,
            destination_dp_rank=destination_dp_rank,
            peer_activation_ns_by_rank=(activation if pool is PolicyPool.PEER_HBM else None),
        )
        des.run()
        if recovery.phase is not RecoveryPhase.FORWARD_COMPLETE:
            raise RuntimeError(
                f"DES recovery did not reach FORWARD_COMPLETE: {recovery.phase.value}"
            )
        if recovery.byte_audit is None or not recovery.byte_audit.valid:
            raise RuntimeError("DES recovery failed KV byte conservation")
        if set(recovery.rank_ready_ns) != set(range(4)):
            raise RuntimeError("DES recovery did not execute all four rank shards")
        if (
            recovery.shard_ready_ns is None
            or recovery.barrier_complete_ns is None
            or recovery.directory_installed_ns is None
            or recovery.forward_start_ns is None
            or recovery.forward_complete_ns is None
        ):
            raise RuntimeError("DES recovery omitted a required TP4 phase timestamp")

        destination_ranks = tuple(
            self._ranks[(recovery.destination_dp_rank, tp_rank)]
            for tp_rank in range(self.config.parallelism.tensor_parallel_size)
        )
        rank_costs: list[RankRecoveryCost] = []
        for tp_rank, source_resource_id in recovery.plan.rank_sources:
            destination = destination_ranks[tp_rank]
            source_resource_ids: tuple[str, ...]
            destination_resource_ids: tuple[str, ...]
            if pool is PolicyPool.PEER_HBM:
                source_node_id = destination.node_id
                source_resource_ids = (
                    source_resource_id,
                    f"hbm:{destination.resource_id}",
                )
                destination_resource_ids = (
                    destination.resource_id,
                    f"hbm:{destination.resource_id}",
                )
                transfer_bytes = 0
                activation_bytes = protection.chunk.shard_bytes
            else:
                source_node_id = _STORE_NODE_ID
                source_resource_ids = (
                    source_resource_id,
                    f"store:{_STORE_NODE_ID}:read",
                    f"fabric:{_STORE_NODE_ID}->{destination.node_id}:mooncake-rdma",
                )
                destination_resource_ids = (
                    f"fabric:{_STORE_NODE_ID}->{destination.node_id}:mooncake-rdma",
                    f"copy:{destination.resource_id}:h2d",
                    destination.resource_id,
                )
                transfer_bytes = protection.chunk.shard_bytes
                activation_bytes = 0
            rank_costs.append(
                RankRecoveryCost(
                    tp_rank=tp_rank,
                    source_node_id=source_node_id,
                    destination_node_id=destination.node_id,
                    source_resource_id=source_resource_id,
                    destination_gpu_id=destination.resource_id,
                    source_resource_ids=source_resource_ids,
                    destination_resource_ids=destination_resource_ids,
                    restored_kv_bytes=protection.chunk.shard_bytes,
                    transfer_bytes=transfer_bytes,
                    activation_bytes=activation_bytes,
                    start_ns=recovery_start_ns,
                    complete_ns=recovery.rank_ready_ns[tp_rank],
                )
            )
        rank_cost_tuple = tuple(rank_costs)
        barrier = BarrierCost(
            participant_gpu_ids=tuple(rank.resource_id for rank in destination_ranks),
            resource_id=recovery.plan.collectives[0].rate_resource_id,
            start_ns=recovery.shard_ready_ns,
            complete_ns=recovery.barrier_complete_ns,
            payload_bytes=0,
        )
        directory = DirectoryInstallCost(
            resource_id=(f"directory:{destination_ranks[0].node_id}:generation-install"),
            start_ns=recovery.barrier_complete_ns,
            complete_ns=recovery.directory_installed_ns,
        )
        model_collective = ModelForwardAllReduceCost(
            participant_gpu_ids=tuple(rank.resource_id for rank in destination_ranks),
            resource_id=recovery.plan.collectives[-1].rate_resource_id,
            payload_bytes_per_rank=model_forward_all_reduce_bytes_per_rank,
            total_collective_bytes=(
                model_forward_all_reduce_bytes_per_rank
                * self.config.parallelism.tensor_parallel_size
            ),
            start_ns=recovery.forward_start_ns,
            complete_ns=recovery.forward_complete_ns,
            operates_on_kv=False,
            included_in_kv_recovery_latency=False,
        )
        rank_resources = self._recovery_rank_audits(
            pool=pool,
            rank_costs=rank_cost_tuple,
            barrier=barrier,
            directory=directory,
            model_collective=model_collective,
        )
        byte_audit = RecoveryByteConservationAudit(
            pool=pool,
            logical_chunk_bytes=recovery.byte_audit.logical_chunk_bytes,
            sum_rank_restored_kv_bytes=(recovery.byte_audit.sum_rank_restored_kv_bytes),
            source_read_bytes=recovery.byte_audit.source_read_bytes,
            destination_write_bytes=recovery.byte_audit.destination_write_bytes,
            activated_bytes=recovery.byte_audit.activated_bytes,
            kv_reduction_bytes=recovery.byte_audit.kv_reduction_bytes,
            model_collective_bytes_excluded=(recovery.byte_audit.model_collective_bytes_excluded),
            valid=recovery.byte_audit.valid,
        )

        event_trace = tuple(
            DESEventExecution(
                timestamp_ns=record.timestamp_ns,
                event_id=str(record.data["event_id"]),
                kind=str(record.data["kind"]),
            )
            for record in des.des.journal.records
            if record.record_type == "EVENT_EXECUTING"
        )
        recovery_events = tuple(
            item.kind for item in event_trace if recovery.recovery_id in item.event_id
        )
        expected_recovery_events = (
            "RECOVERY_START",
            "GET_COMPLETE",
            "GET_COMPLETE",
            "GET_COMPLETE",
            "GET_COMPLETE",
            "RECOVERY_COMPLETE",
            "DIRECTORY_PUBLISH",
            "FORWARD_START",
            "FORWARD_COMPLETE",
        )
        if recovery_events != expected_recovery_events:
            raise RuntimeError(f"DES TP4 recovery event ordering drift: {recovery_events}")
        capacity = des.capacity_audit()
        pressure = des.peer_hbm_pressure()
        algorithm3_audit = tuple(
            Algorithm3ExecutionAudit(
                target_dp_rank=item.target_dp_rank,
                timestamp_ns=item.decision.timestamp_ns,
                action=item.decision.action.value,
                reason=item.reason,
                previous_fraction=str(item.decision.previous_state.protection_fraction),
                next_fraction=str(item.decision.next_state.protection_fraction),
                previous_stable_windows=item.decision.previous_state.stable_windows,
                next_stable_windows=item.decision.next_state.stable_windows,
                quota_bytes_per_rank=item.decision.quota_bytes,
                peer_usage_bytes_per_rank=item.peer_usage_bytes_per_rank,
                resident_primary_bytes_per_rank=item.resident_primary_bytes_per_rank,
                free_reclaimable_bytes_per_rank=item.free_reclaimable_bytes_per_rank,
                quota_enforced=item.quota_enforced,
                decision_fingerprint=item.decision.fingerprint,
            )
            for item in des.algorithm3_audit
        )
        if len(algorithm3_audit) != len(algorithm3_control_events):
            raise RuntimeError("Algorithm 3 control event/audit cardinality drift")
        journal_bytes = des.des.journal.to_jsonl_bytes()
        des_evidence = DESExecutionEvidence(
            evidence_class=EVIDENCE_CLASS,
            journal_sha256=hashlib.sha256(journal_bytes).hexdigest(),
            journal_record_count=len(des.des.journal.records),
            event_trace=event_trace,
            fenced_dp_ranks=tuple(sorted(des.fenced_dp_ranks)),
            failure_fence_event_count=sum(item.kind == "ROUTE_FENCE" for item in event_trace),
            protection_path_states=tuple(
                (
                    path.pool.value,
                    path.state.value,
                    path.transaction.acked_ranks,
                    path.capacity_committed,
                )
                for path in (protection.peer_hbm, protection.store_dram)
            ),
            recovery_phase=recovery.phase.value,
            four_shard_recovery_executed=(
                len(recovery.rank_ready_ns) == 4 and recovery_events.count("GET_COMPLETE") == 4
            ),
            capacity_conservation_valid=capacity.valid,
            algorithm2_four_shard_transaction_surface_executed=True,
            algorithm3_peer_quota_surface_enforced=(
                all(item.quota_enforced for item in algorithm3_audit)
                and pressure.maximum_pressure_per_mille <= 1000
            ),
            algorithm3_controller_integration="per_dp_rank_global_des_aimd",
            algorithm3_audit=algorithm3_audit,
        )
        fingerprint = _canonical_fingerprint(
            {
                "des_journal_sha256": des_evidence.journal_sha256,
                "failure_id": failure_id,
                "fenced_dp_ranks": list(des_evidence.fenced_dp_ranks),
                "logical_chunk_id": logical_chunk_id,
                "recovery_id": recovery.recovery_id,
                "recovery_phase": recovery.phase.value,
            }
        )
        return RecoveryExecution(
            logical_chunk_id=logical_chunk_id,
            pool=pool,
            destination_dp_rank=recovery.destination_dp_rank,
            failures=failures,
            plan=recovery.plan,
            rank_costs=rank_cost_tuple,
            barrier=barrier,
            directory_install=directory,
            kv_recovery_start_ns=recovery_start_ns,
            kv_recovery_complete_ns=recovery.directory_installed_ns,
            model_forward_all_reduce=model_collective,
            rank_resources=rank_resources,
            node_resources=_node_audits(rank_resources),
            byte_audit=byte_audit,
            fingerprint=fingerprint,
            des_evidence=des_evidence,
        )

    def _execute_path(
        self,
        *,
        logical_chunk_id: str,
        source_dp_rank: int,
        shard_bytes: int,
        logical_bytes: int,
        route_version: int,
        start_ns: int,
        pool: PolicyPool,
        control: PathExecutionControl,
    ) -> PathProtectionExecution:
        placements = self._path_placements(
            logical_chunk_id=logical_chunk_id,
            source_dp_rank=source_dp_rank,
            shard_bytes=shard_bytes,
            pool=pool,
        )
        transaction = TPChunkPathTransaction(
            transaction_id=f"{logical_chunk_id}:{pool.value}",
            logical_chunk_id=logical_chunk_id,
            pool=pool,
            route_version=route_version,
            layout=self.layout,
            shards=tuple(item[0] for item in placements),
        )
        cost = (
            self.config.modeled_costs.cross_node_peer_hbm
            if pool is PolicyPool.PEER_HBM
            else self.config.modeled_costs.store_dram
        )
        duration = _duration_ns(
            byte_count=shard_bytes,
            bandwidth_bytes_per_second=cost.effective_bandwidth_bytes_per_second,
            setup_ns=cost.setup_ns,
        )
        records: list[ShardTransferRecord] = []
        aborted = False
        for shard, source_node, destination_node, rate_resources in placements:
            if aborted:
                records.append(
                    ShardTransferRecord(
                        pool=pool,
                        tp_rank=shard.tp_rank,
                        source_node_id=source_node,
                        destination_node_id=destination_node,
                        source_resource_id=shard.source_gpu_id,
                        destination_resource_id=shard.protection_resource_id,
                        rate_resource_ids=rate_resources,
                        shard_bytes=shard_bytes,
                        transferred_bytes=0,
                        start_ns=start_ns,
                        complete_ns=None,
                        status=ShardTransferStatus.CANCELED,
                    )
                )
                continue
            complete_ns = start_ns + duration
            if shard.tp_rank in control.failed_tp_ranks:
                transaction.abort(reason=f"SHARD_TRANSFER_FAILED:tp={shard.tp_rank}")
                aborted = True
                status = ShardTransferStatus.FAILED
                transferred_bytes = 0
            elif shard.tp_rank in control.no_ack_tp_ranks:
                status = ShardTransferStatus.NO_ACK
                transferred_bytes = shard_bytes
            else:
                transaction.acknowledge_shard(
                    shard.tp_rank,
                    timestamp_ns=complete_ns,
                    route_version=route_version,
                    layout=self.layout,
                )
                status = ShardTransferStatus.ACKED
                transferred_bytes = shard_bytes
            records.append(
                ShardTransferRecord(
                    pool=pool,
                    tp_rank=shard.tp_rank,
                    source_node_id=source_node,
                    destination_node_id=destination_node,
                    source_resource_id=shard.source_gpu_id,
                    destination_resource_id=shard.protection_resource_id,
                    rate_resource_ids=rate_resources,
                    shard_bytes=shard_bytes,
                    transferred_bytes=transferred_bytes,
                    start_ns=start_ns,
                    complete_ns=complete_ns,
                    status=status,
                )
            )
        transfers = tuple(records)
        transferred = sum(item.transferred_bytes for item in transfers)
        acked = sum(
            item.shard_bytes for item in transfers if item.status is ShardTransferStatus.ACKED
        )
        committed = logical_bytes if transaction.state is PathCommitState.COMMITTED else 0
        audit = PathByteConservationAudit(
            pool=pool,
            logical_chunk_bytes=logical_bytes,
            sum_rank_shard_bytes=sum(item.allocated_bytes for item in transaction.shards),
            source_read_bytes=transferred,
            destination_write_bytes=transferred,
            acknowledged_bytes=acked,
            committed_bytes=committed,
            kv_reduction_bytes=0,
            valid=(
                sum(item.allocated_bytes for item in transaction.shards) == logical_bytes
                and transferred == sum(item.transferred_bytes for item in transfers)
                and (
                    (
                        transaction.state is PathCommitState.COMMITTED
                        and acked == logical_bytes
                        and committed == logical_bytes
                    )
                    or (transaction.state is not PathCommitState.COMMITTED and committed == 0)
                )
            ),
        )
        return PathProtectionExecution(
            transaction=transaction,
            transfers=transfers,
            byte_audit=audit,
        )

    def _path_placements(
        self,
        *,
        logical_chunk_id: str,
        source_dp_rank: int,
        shard_bytes: int,
        pool: PolicyPool,
    ) -> tuple[tuple[TPShardPlacement, str, str, tuple[str, ...]], ...]:
        result: list[tuple[TPShardPlacement, str, str, tuple[str, ...]]] = []
        target_dp = self.config.placement.peer_target_dp_by_source_dp[source_dp_rank]
        for tp_rank in range(self.config.parallelism.tensor_parallel_size):
            source = self._ranks[(source_dp_rank, tp_rank)]
            if pool is PolicyPool.PEER_HBM:
                target = self._ranks[(target_dp, tp_rank)]
                destination_node = target.node_id
                protection_resource = f"peer-hbm:{target.resource_id}:owner-dp{source_dp_rank}"
                rate_resources = (
                    f"copy:{source.resource_id}:d2d",
                    f"fabric:{source.node_id}->{target.node_id}:rdma-gdr",
                    f"copy:{target.resource_id}:d2d",
                )
            else:
                destination_node = _STORE_NODE_ID
                protection_resource = f"store-dram:{logical_chunk_id}:tp{tp_rank}"
                rate_resources = (
                    f"copy:{source.resource_id}:d2h",
                    f"fabric:{source.node_id}->{_STORE_NODE_ID}:mooncake-rdma",
                    f"store:{_STORE_NODE_ID}:write",
                )
            result.append(
                (
                    TPShardPlacement(
                        tp_rank=tp_rank,
                        source_gpu_id=source.resource_id,
                        protection_resource_id=protection_resource,
                        allocated_bytes=shard_bytes,
                    ),
                    source.node_id,
                    destination_node,
                    rate_resources,
                )
            )
        return tuple(result)

    def _protection_rank_audits(
        self,
        peer: PathProtectionExecution,
        store: PathProtectionExecution,
    ) -> tuple[RankResourceAudit, ...]:
        audits: list[RankResourceAudit] = []
        for execution in (peer, store):
            for item in execution.transfers:
                audits.extend(
                    (
                        RankResourceAudit(
                            phase="PROTECT_SOURCE",
                            pool=item.pool,
                            tp_rank=item.tp_rank,
                            node_id=item.source_node_id,
                            gpu_resource_id=item.source_resource_id,
                            resource_ids=(
                                item.source_resource_id,
                                item.rate_resource_ids[0],
                                item.rate_resource_ids[1],
                            ),
                            kv_bytes=item.shard_bytes,
                            transfer_bytes=item.transferred_bytes,
                            activated_bytes=0,
                            model_collective_bytes=0,
                        ),
                        RankResourceAudit(
                            phase="PROTECT_DESTINATION",
                            pool=item.pool,
                            tp_rank=item.tp_rank,
                            node_id=item.destination_node_id,
                            gpu_resource_id=item.destination_resource_id,
                            resource_ids=(
                                item.destination_resource_id,
                                item.rate_resource_ids[1],
                                item.rate_resource_ids[2],
                            ),
                            kv_bytes=item.shard_bytes,
                            transfer_bytes=item.transferred_bytes,
                            activated_bytes=0,
                            model_collective_bytes=0,
                        ),
                    )
                )
        return tuple(audits)

    def _recovery_destination_dp(
        self,
        *,
        protected: ProtectedLogicalChunk,
        pool: PolicyPool,
        failures: FailureSet,
        destination_dp_rank: int | None,
    ) -> int:
        if pool is PolicyPool.PEER_HBM:
            expected = self.config.placement.peer_target_dp_by_source_dp[protected.source_dp_rank]
            if destination_dp_rank is not None and destination_dp_rank != expected:
                raise ValueError("Peer-HBM recovery must use its mapped target DP rank")
            candidate = expected
            if not self._dp_is_healthy(candidate, failures):
                raise ValueError("mapped Peer-HBM TP group is unavailable")
            return candidate
        if destination_dp_rank is not None:
            self._validate_dp_rank(destination_dp_rank)
            if not self._dp_is_healthy(destination_dp_rank, failures):
                raise ValueError("requested Store recovery TP group is unavailable")
            return destination_dp_rank
        for offset in range(1, self.config.parallelism.data_parallel_size + 1):
            candidate = (
                protected.source_dp_rank + offset
            ) % self.config.parallelism.data_parallel_size
            if self._dp_is_healthy(candidate, failures):
                return candidate
        raise ValueError("no healthy complete TP group is available for Store recovery")

    def _dp_is_healthy(self, dp_rank: int, failures: FailureSet) -> bool:
        return all(
            not failures.rank_is_failed(
                node_id=self._ranks[(dp_rank, tp_rank)].node_id,
                gpu_id=self._ranks[(dp_rank, tp_rank)].resource_id,
            )
            for tp_rank in range(self.config.parallelism.tensor_parallel_size)
        )

    def _rank_recovery_costs(
        self,
        *,
        protected: ProtectedLogicalChunk,
        pool: PolicyPool,
        destination_dp_rank: int,
        start_ns: int,
        activation_ns_by_rank: tuple[int, ...],
    ) -> tuple[RankRecoveryCost, ...]:
        path = protected.path(pool)
        costs: list[RankRecoveryCost] = []
        store_link = self.config.modeled_costs.store_dram
        for shard in path.transaction.shards:
            destination = self._ranks[(destination_dp_rank, shard.tp_rank)]
            if pool is PolicyPool.PEER_HBM:
                source_node = destination.node_id
                transfer_bytes = 0
                activation_bytes = shard.allocated_bytes
                duration = activation_ns_by_rank[shard.tp_rank]
                source_resources: tuple[str, ...] = (
                    shard.protection_resource_id,
                    f"hbm:{destination.resource_id}",
                )
                destination_resources: tuple[str, ...] = (
                    destination.resource_id,
                    f"hbm:{destination.resource_id}",
                )
            else:
                source_node = _STORE_NODE_ID
                transfer_bytes = shard.allocated_bytes
                activation_bytes = 0
                duration = _duration_ns(
                    byte_count=shard.allocated_bytes,
                    bandwidth_bytes_per_second=(store_link.effective_bandwidth_bytes_per_second),
                    setup_ns=store_link.setup_ns,
                )
                source_resources = (
                    shard.protection_resource_id,
                    f"store:{_STORE_NODE_ID}:read",
                    f"fabric:{_STORE_NODE_ID}->{destination.node_id}:mooncake-rdma",
                )
                destination_resources = (
                    f"fabric:{_STORE_NODE_ID}->{destination.node_id}:mooncake-rdma",
                    f"copy:{destination.resource_id}:h2d",
                    destination.resource_id,
                )
            costs.append(
                RankRecoveryCost(
                    tp_rank=shard.tp_rank,
                    source_node_id=source_node,
                    destination_node_id=destination.node_id,
                    source_resource_id=shard.protection_resource_id,
                    destination_gpu_id=destination.resource_id,
                    source_resource_ids=source_resources,
                    destination_resource_ids=destination_resources,
                    restored_kv_bytes=shard.allocated_bytes,
                    transfer_bytes=transfer_bytes,
                    activation_bytes=activation_bytes,
                    start_ns=start_ns,
                    complete_ns=start_ns + duration,
                )
            )
        return tuple(costs)

    def _recovery_rank_audits(
        self,
        *,
        pool: PolicyPool,
        rank_costs: tuple[RankRecoveryCost, ...],
        barrier: BarrierCost,
        directory: DirectoryInstallCost,
        model_collective: ModelForwardAllReduceCost,
    ) -> tuple[RankResourceAudit, ...]:
        audits: list[RankResourceAudit] = []
        for item in rank_costs:
            audits.append(
                RankResourceAudit(
                    phase="RECOVER_SOURCE",
                    pool=pool,
                    tp_rank=item.tp_rank,
                    node_id=item.source_node_id,
                    gpu_resource_id=item.source_resource_id,
                    resource_ids=item.source_resource_ids,
                    kv_bytes=item.restored_kv_bytes,
                    transfer_bytes=item.transfer_bytes,
                    activated_bytes=0,
                    model_collective_bytes=0,
                )
            )
            audits.append(
                RankResourceAudit(
                    phase="RECOVER_DESTINATION",
                    pool=pool,
                    tp_rank=item.tp_rank,
                    node_id=item.destination_node_id,
                    gpu_resource_id=item.destination_gpu_id,
                    resource_ids=(
                        *item.destination_resource_ids,
                        barrier.resource_id,
                        directory.resource_id,
                    ),
                    kv_bytes=item.restored_kv_bytes,
                    transfer_bytes=item.transfer_bytes,
                    activated_bytes=item.activation_bytes,
                    model_collective_bytes=0,
                )
            )
            audits.append(
                RankResourceAudit(
                    phase="MODEL_FORWARD_COLLECTIVE",
                    pool=pool,
                    tp_rank=item.tp_rank,
                    node_id=item.destination_node_id,
                    gpu_resource_id=item.destination_gpu_id,
                    resource_ids=(
                        item.destination_gpu_id,
                        model_collective.resource_id,
                    ),
                    kv_bytes=0,
                    transfer_bytes=0,
                    activated_bytes=0,
                    model_collective_bytes=(model_collective.payload_bytes_per_rank),
                )
            )
        return tuple(audits)

    def _recovery_byte_audit(
        self,
        *,
        protected: ProtectedLogicalChunk,
        pool: PolicyPool,
        rank_costs: tuple[RankRecoveryCost, ...],
        model_collective: ModelForwardAllReduceCost,
    ) -> RecoveryByteConservationAudit:
        restored = sum(item.restored_kv_bytes for item in rank_costs)
        transferred = sum(item.transfer_bytes for item in rank_costs)
        activated = sum(item.activation_bytes for item in rank_costs)
        source_read = transferred
        destination_write = transferred
        return RecoveryByteConservationAudit(
            pool=pool,
            logical_chunk_bytes=protected.logical_chunk_bytes,
            sum_rank_restored_kv_bytes=restored,
            source_read_bytes=source_read,
            destination_write_bytes=destination_write,
            activated_bytes=activated,
            kv_reduction_bytes=0,
            model_collective_bytes_excluded=model_collective.total_collective_bytes,
            valid=(
                restored == protected.logical_chunk_bytes
                and source_read == destination_write
                and (transferred == restored or activated == restored)
            ),
        )

    def _peer_activation_costs(
        self,
        value: tuple[int, ...] | None,
    ) -> tuple[int, ...]:
        result = value or (0,) * self.config.parallelism.tensor_parallel_size
        if type(result) is not tuple:
            raise TypeError("peer_activation_ns_by_rank must be an exact tuple")
        if len(result) != self.config.parallelism.tensor_parallel_size:
            raise ValueError("peer activation costs require one value per TP rank")
        for item in result:
            require_nonnegative_int(item, "peer activation cost")
        return result

    def _validate_control(self, control: PathExecutionControl) -> None:
        if type(control) is not PathExecutionControl:
            raise TypeError("path controls must be exact PathExecutionControl values")
        ranks = control.no_ack_tp_ranks | control.failed_tp_ranks
        if any(rank >= self.config.parallelism.tensor_parallel_size for rank in ranks):
            raise ValueError("path control TP rank is outside the configured layout")

    def _validate_dp_rank(self, dp_rank: int) -> None:
        require_nonnegative_int(dp_rank, "dp_rank")
        if dp_rank >= self.config.parallelism.data_parallel_size:
            raise ValueError("DP rank is outside the configured layout")

    def _validate_failure_ids(self, failures: FailureSet) -> None:
        valid_gpus = {rank.resource_id for rank in self.config.rank_placements}
        valid_nodes = {rank.node_id for rank in self.config.rank_placements}
        unknown_gpus = failures.failed_gpu_ids - valid_gpus
        unknown_nodes = failures.failed_node_ids - valid_nodes
        if unknown_gpus or unknown_nodes:
            raise ValueError(
                "failure set contains unknown resources: "
                f"gpus={sorted(unknown_gpus)}, nodes={sorted(unknown_nodes)}"
            )

    @staticmethod
    def _path_fingerprint_document(path: PathProtectionExecution) -> dict[str, object]:
        return {
            "acked_ranks": list(path.transaction.acked_ranks),
            "byte_audit": {
                "acknowledged": path.byte_audit.acknowledged_bytes,
                "committed": path.byte_audit.committed_bytes,
                "valid": path.byte_audit.valid,
            },
            "state": path.state.value,
            "terminal_reason": path.transaction.terminal_reason,
            "transfers": [
                {
                    "complete_ns": item.complete_ns,
                    "destination": item.destination_resource_id,
                    "rank": item.tp_rank,
                    "rate_resources": list(item.rate_resource_ids),
                    "source": item.source_resource_id,
                    "status": item.status.value,
                    "transferred_bytes": item.transferred_bytes,
                }
                for item in path.transfers
            ],
        }


__all__ = [
    "Algorithm3ControlInput",
    "Algorithm3ExecutionAudit",
    "BarrierCost",
    "DESEventExecution",
    "DESExecutionEvidence",
    "DirectoryInstallCost",
    "FailureSet",
    "ModelForwardAllReduceCost",
    "NodeResourceAudit",
    "PathByteConservationAudit",
    "PathExecutionControl",
    "PathProtectionExecution",
    "ProtectedLogicalChunk",
    "Qwen3TP4ExecutionDriver",
    "RankRecoveryCost",
    "RankResourceAudit",
    "RecoveryByteConservationAudit",
    "RecoveryExecution",
    "ShardTransferRecord",
    "ShardTransferStatus",
]
