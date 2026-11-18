"""Group-level GlobalDES skeleton for the strict Qwen3-32B DP8/TP4 contract.

This module gives the pure TP4 state machines a physical, byte-exact execution
surface.  It deliberately remains ``modeled_uncalibrated``: every bandwidth and
setup cost is taken directly from :class:`Qwen3TP4EngineConfig`, and no observed
or desired trend is used to alter a duration.

Peer-HBM and Store-DRAM protection are independent source-owned transactions.
Each path reserves physical capacity as PENDING, records four rank-local ACKs,
and commits capacity only after the TP transaction has all four ACKs.  A rank
failure fences its complete DP/TP4 group.  Recovery is ordered as four distinct
rank shards, a readiness barrier, a directory-generation install, and a later
first-forward model collective.  The collective never reduces KV bytes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Final

from moonkvsim.aegiskv.hbm_quota_aimd import (
    AIMDDecision,
    AIMDParameters,
    AIMDTargetState,
    HBMQuotaAIMD,
)
from moonkvsim.aegiskv.qwen3_32b_tp4_config import (
    Qwen3TP4EngineConfig,
    RankPlacement,
)
from moonkvsim.aegiskv.qwen3_32b_tp4_execution import PathExecutionControl
from moonkvsim.aegiskv.tp_recovery import (
    TPChunkPathTransaction,
    TPLayoutIdentity,
    TPRecoveryPlan,
    TPShardPlacement,
)
from moonkvsim.aegiskv.types import PathCommitState, PolicyPool, require_nonnegative_int
from moonkvsim.simulation.event import EventHandle, EventKind, EventPriority, ScheduledEvent
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import (
    FREE_ACCOUNT,
    UNAVAILABLE_CAPACITY_ACCOUNT,
    CapacityLedger,
    CapacityResourceKind,
)
from moonkvsim.simulation.resource import RateResource
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction

EVIDENCE_CLASS: Final = "modeled_uncalibrated"
STORE_LEDGER_ID: Final = "store-0:segment-0"
MODEL_WEIGHTS_ACCOUNT: Final = "MODEL_WEIGHTS"
RUNTIME_FIXED_ACCOUNT: Final = "RUNTIME_FIXED"
_NS_PER_SECOND: Final = 1_000_000_000


class RecoveryPhase(StrEnum):
    SCHEDULED = "SCHEDULED"
    SHARDS_READY = "SHARDS_READY"
    BARRIER_COMPLETE = "BARRIER_COMPLETE"
    DIRECTORY_INSTALLED = "DIRECTORY_INSTALLED"
    FORWARD_COMPLETE = "FORWARD_COMPLETE"
    ABORTED = "ABORTED"


@dataclass(frozen=True, slots=True)
class TP4Group:
    dp_rank: int
    ranks: tuple[RankPlacement, ...]

    def __post_init__(self) -> None:
        require_nonnegative_int(self.dp_rank, "dp_rank")
        if len(self.ranks) != 4 or tuple(rank.tp_rank for rank in self.ranks) != tuple(range(4)):
            raise ValueError("a Qwen3-32B TP4 group requires ordered TP ranks 0..3")
        if any(rank.dp_rank != self.dp_rank for rank in self.ranks):
            raise ValueError("TP4 group contains a rank from another DP group")


@dataclass(frozen=True, slots=True)
class TP4LogicalChunk:
    logical_chunk_id: str
    source_dp_rank: int
    token_count: int
    route_version: int
    shard_bytes: int
    logical_chunk_bytes: int
    primary_accounts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProtectionByteAudit:
    pool: PolicyPool
    logical_chunk_bytes: int
    sum_rank_shard_bytes: int
    source_read_bytes: int
    destination_write_bytes: int
    acknowledged_bytes: int
    committed_bytes: int
    kv_reduction_bytes: int
    valid: bool


@dataclass(slots=True)
class ProtectionPathRun:
    path_id: str
    chunk: TP4LogicalChunk
    pool: PolicyPool
    transaction: TPChunkPathTransaction
    source_dp_rank: int
    target_dp_rank: int | None
    ledger_resource_ids: tuple[str, ...]
    pending_accounts: tuple[str, ...]
    committed_accounts: tuple[str, ...]
    rate_resource_ids_by_rank: tuple[tuple[str, ...], ...]
    control: PathExecutionControl
    scheduled_start_ns: int
    admitted: bool = False
    capacity_committed: bool = False
    transferred_bytes_by_rank: dict[int, int] = field(default_factory=dict)
    completion_handles: dict[int, EventHandle] = field(default_factory=dict)

    @property
    def state(self) -> PathCommitState:
        return self.transaction.state

    @property
    def byte_audit(self) -> ProtectionByteAudit:
        transferred = sum(self.transferred_bytes_by_rank.values())
        acknowledged = len(self.transaction.acked_ranks) * self.chunk.shard_bytes
        committed = self.chunk.logical_chunk_bytes if self.capacity_committed else 0
        valid = (
            4 * self.chunk.shard_bytes == self.chunk.logical_chunk_bytes
            and transferred <= self.chunk.logical_chunk_bytes
            and acknowledged <= transferred
            and (
                (
                    self.capacity_committed
                    and self.state is PathCommitState.COMMITTED
                    and acknowledged == self.chunk.logical_chunk_bytes
                    and committed == self.chunk.logical_chunk_bytes
                )
                or (not self.capacity_committed and committed == 0)
            )
        )
        return ProtectionByteAudit(
            pool=self.pool,
            logical_chunk_bytes=self.chunk.logical_chunk_bytes,
            sum_rank_shard_bytes=4 * self.chunk.shard_bytes,
            source_read_bytes=transferred,
            destination_write_bytes=transferred,
            acknowledged_bytes=acknowledged,
            committed_bytes=committed,
            kv_reduction_bytes=0,
            valid=valid,
        )


@dataclass(frozen=True, slots=True)
class TP4ProtectionRun:
    protection_id: str
    chunk: TP4LogicalChunk
    peer_hbm: ProtectionPathRun
    store_dram: ProtectionPathRun

    def path(self, pool: PolicyPool) -> ProtectionPathRun:
        if pool is PolicyPool.PEER_HBM:
            return self.peer_hbm
        if pool is PolicyPool.STORE_DRAM:
            return self.store_dram
        raise TypeError("pool must be an exact PolicyPool")


@dataclass(frozen=True, slots=True)
class RecoveryByteAudit:
    pool: PolicyPool
    logical_chunk_bytes: int
    sum_rank_restored_kv_bytes: int
    source_read_bytes: int
    destination_write_bytes: int
    activated_bytes: int
    kv_reduction_bytes: int
    model_collective_bytes_excluded: int
    valid: bool


@dataclass(slots=True)
class TP4RecoveryRun:
    recovery_id: str
    protection: TP4ProtectionRun
    path: ProtectionPathRun
    pool: PolicyPool
    destination_dp_rank: int
    plan: TPRecoveryPlan
    scheduled_start_ns: int
    directory_install_ns: int
    first_forward_bytes_per_rank: int
    destination_ledger_ids: tuple[str, ...]
    pending_accounts: tuple[str, ...]
    recovered_accounts: tuple[str, ...]
    rate_resource_ids_by_rank: tuple[tuple[str, ...], ...]
    peer_activation_ns_by_rank: tuple[int, ...]
    phase: RecoveryPhase = RecoveryPhase.SCHEDULED
    ready_ranks: set[int] = field(default_factory=set)
    rank_ready_ns: dict[int, int] = field(default_factory=dict)
    event_handles: list[EventHandle] = field(default_factory=list)
    capacity_reserved: bool = False
    capacity_committed: bool = False
    shard_ready_ns: int | None = None
    barrier_complete_ns: int | None = None
    directory_installed_ns: int | None = None
    forward_start_ns: int | None = None
    forward_complete_ns: int | None = None
    byte_audit: RecoveryByteAudit | None = None
    terminal_reason: str | None = None

    @property
    def kv_recovery_complete_ns(self) -> int | None:
        return self.directory_installed_ns


@dataclass(frozen=True, slots=True)
class CapacityConservationAudit:
    hbm_ledger_count: int
    store_ledger_count: int
    physical_capacity_bytes: int
    account_bytes: int
    fixed_hbm_capacity_bytes: int
    fixed_hbm_account_bytes: int
    kv_capable_hbm_capacity_bytes: int
    kv_capable_hbm_account_bytes: int
    valid: bool


@dataclass(frozen=True, slots=True)
class PeerHBMPressureSnapshot:
    """Physical Peer-HBM inputs exposed to, but not controlled by, Algorithm 3."""

    quota_bytes_per_rank: int
    quota_upper_bound_bytes_per_rank: int
    pending_bytes_by_rank: tuple[tuple[str, int], ...]
    committed_bytes_by_rank: tuple[tuple[str, int], ...]
    usage_bytes_by_rank: tuple[tuple[str, int], ...]
    pressure_per_mille_by_rank: tuple[tuple[str, int], ...]
    maximum_usage_bytes: int
    maximum_pressure_per_mille: int


@dataclass(frozen=True, slots=True)
class Algorithm3AuditRecord:
    """One target-local controller transition and its physical DES inputs."""

    target_dp_rank: int
    reason: str
    resident_primary_bytes_per_rank: tuple[int, ...]
    free_reclaimable_bytes_per_rank: tuple[int, ...]
    peer_usage_bytes_per_rank: tuple[int, ...]
    quota_enforced: bool
    decision: AIMDDecision

    def to_dict(self) -> dict[str, object]:
        return {
            "target_dp_rank": self.target_dp_rank,
            "reason": self.reason,
            "resident_primary_bytes_per_rank": list(self.resident_primary_bytes_per_rank),
            "free_reclaimable_bytes_per_rank": list(self.free_reclaimable_bytes_per_rank),
            "peer_usage_bytes_per_rank": list(self.peer_usage_bytes_per_rank),
            "quota_enforced": self.quota_enforced,
            "decision": self.decision.to_dict(),
        }


class Qwen3TP4GroupDES:
    """Sweep-drivable DP8/TP4 resource skeleton on one GlobalDES clock."""

    def __init__(
        self,
        config: Qwen3TP4EngineConfig,
        *,
        store_dram_capacity_bytes: int | None = None,
        des: GlobalDES | None = None,
    ) -> None:
        if type(config) is not Qwen3TP4EngineConfig:
            raise TypeError("config must be an exact Qwen3TP4EngineConfig")
        self._validate_contract(config)
        configured_store_capacity = config.capacity.store_dram.total_capacity_bytes
        if store_dram_capacity_bytes is not None:
            if type(store_dram_capacity_bytes) is not int:
                raise TypeError("store_dram_capacity_bytes must be an integer when supplied")
            if store_dram_capacity_bytes != configured_store_capacity:
                raise ValueError(
                    "store_dram_capacity_bytes must exactly match config.capacity.store_dram"
                )
        self.config = config
        self.des = des or GlobalDES()
        if type(self.des) is not GlobalDES:
            raise TypeError("des must be an exact GlobalDES")
        self.layout = TPLayoutIdentity(
            model_revision=config.model.revision,
            kv_abi="qwen3-bfloat16-kv-v1",
            layout_id="qwen3-32b-tp4-pp1",
            tensor_parallel_size=4,
            pipeline_parallel_size=1,
        )
        placements = {(rank.dp_rank, rank.tp_rank): rank for rank in config.rank_placements}
        self.groups = tuple(
            TP4Group(
                dp_rank=dp_rank,
                ranks=tuple(placements[(dp_rank, tp_rank)] for tp_rank in range(4)),
            )
            for dp_rank in range(8)
        )
        rank_capacity = config.capacity.rank_hbm
        fixed_accounts = {
            MODEL_WEIGHTS_ACCOUNT: rank_capacity.model_weights_bytes_per_rank,
            RUNTIME_FIXED_ACCOUNT: rank_capacity.runtime_fixed_bytes_per_rank,
        }
        self.hbm_ledgers = {
            self._hbm_ledger_id(rank): CapacityLedger(
                resource_id=self._hbm_ledger_id(rank),
                resource_kind=CapacityResourceKind.GPU_HBM,
                capacity_bytes=rank_capacity.physical_hbm_bytes_per_rank,
                initial_accounts=fixed_accounts,
            )
            for rank in config.rank_placements
        }
        store_segment = config.capacity.store_dram.segments[0]
        if store_segment.segment_id != STORE_LEDGER_ID:
            raise ValueError("Qwen3TP4GroupDES requires the configured unique Store segment")
        self.store_ledger = CapacityLedger(
            resource_id=store_segment.segment_id,
            resource_kind=CapacityResourceKind.STORE_DRAM,
            capacity_bytes=store_segment.capacity_bytes,
        )
        self.capacity_ledgers: dict[str, CapacityLedger] = {
            **self.hbm_ledgers,
            self.store_ledger.resource_id: self.store_ledger,
        }
        self.rate_resources = self._build_rate_resources()
        parameters = config.algorithm3
        self.algorithm3_controller = HBMQuotaAIMD(
            AIMDParameters(
                minimum_fraction=Decimal(parameters.minimum_fraction),
                maximum_fraction=Decimal(parameters.maximum_fraction),
                multiplicative_decrease=Decimal(parameters.multiplicative_decrease),
                additive_increase=Decimal(parameters.additive_increase),
                stable_window_count=parameters.stable_window_count,
            )
        )
        self.algorithm3_states = {
            target_dp_rank: AIMDTargetState(
                target_id=f"dp-{target_dp_rank}",
                peer_hbm_capacity_bytes=rank_capacity.kv_capable_hbm_bytes_per_rank,
                protection_fraction=Decimal(parameters.initial_fraction),
            )
            for target_dp_rank in range(config.parallelism.data_parallel_size)
        }
        self.peer_hbm_quota_bytes_by_target = {
            target_dp_rank: rank_capacity.peer_hbm_dynamic_quota_upper_bound_bytes_per_rank
            for target_dp_rank in range(config.parallelism.data_parallel_size)
        }
        self.algorithm3_audit: list[Algorithm3AuditRecord] = []
        self.algorithm3_fenced_targets: set[int] = set()
        self.protections: dict[str, TP4ProtectionRun] = {}
        self.recoveries: dict[str, TP4RecoveryRun] = {}
        self.fenced_dp_ranks: set[int] = set()
        self._next_protection = 0
        self._next_recovery = 0
        self._next_event = 0
        self._register_handlers()
        self.des.register_invariant("qwen3_32b_tp4_capacity", self._check_capacity_invariant)

    @property
    def evidence_class(self) -> str:
        return EVIDENCE_CLASS

    def protect_logical_chunk(
        self,
        *,
        logical_chunk_id: str,
        source_dp_rank: int,
        token_count: int,
        route_version: int,
        start_ns: int | None = None,
        peer_control: PathExecutionControl | None = None,
        store_control: PathExecutionControl | None = None,
    ) -> TP4ProtectionRun:
        """Admit primary shards now and schedule two independent protection paths."""

        if type(logical_chunk_id) is not str or not logical_chunk_id:
            raise ValueError("logical_chunk_id must be a non-empty string")
        self._validate_dp_rank(source_dp_rank)
        if type(token_count) is not int or token_count <= 0:
            raise ValueError("token_count must be a positive integer")
        if token_count > self.config.model.max_context_tokens:
            raise ValueError("token_count exceeds the configured Qwen3-32B context limit")
        require_nonnegative_int(route_version, "route_version")
        resolved_start = self.des.now_ns if start_ns is None else start_ns
        require_nonnegative_int(resolved_start, "start_ns")
        if resolved_start < self.des.now_ns:
            raise ValueError("start_ns cannot precede the GlobalDES clock")
        if any(run.chunk.logical_chunk_id == logical_chunk_id for run in self.protections.values()):
            raise ValueError(f"duplicate logical_chunk_id: {logical_chunk_id}")
        peer = peer_control or PathExecutionControl()
        store = store_control or PathExecutionControl()
        self._validate_control(peer)
        self._validate_control(store)

        shard_bytes = token_count * self.config.model.kv_bytes_per_token_per_tp_rank
        logical_bytes = token_count * self.config.model.kv_bytes_per_token_total
        primary_accounts = tuple(
            f"PRIMARY:{logical_chunk_id}:dp{source_dp_rank}:tp{tp_rank}" for tp_rank in range(4)
        )
        chunk = TP4LogicalChunk(
            logical_chunk_id=logical_chunk_id,
            source_dp_rank=source_dp_rank,
            token_count=token_count,
            route_version=route_version,
            shard_bytes=shard_bytes,
            logical_chunk_bytes=logical_bytes,
            primary_accounts=primary_accounts,
        )
        self._admit_primary(chunk)
        protection_id = f"protection-{self._next_protection:08d}"
        self._next_protection += 1
        peer_path = self._make_path(
            protection_id=protection_id,
            chunk=chunk,
            pool=PolicyPool.PEER_HBM,
            control=peer,
            start_ns=resolved_start,
        )
        store_path = self._make_path(
            protection_id=protection_id,
            chunk=chunk,
            pool=PolicyPool.STORE_DRAM,
            control=store,
            start_ns=resolved_start,
        )
        run = TP4ProtectionRun(
            protection_id=protection_id,
            chunk=chunk,
            peer_hbm=peer_path,
            store_dram=store_path,
        )
        self.protections[protection_id] = run
        for path in (peer_path, store_path):
            self.des.schedule_at(
                resolved_start,
                EventKind.PUT_START,
                event_id=self._event_id(f"{path.path_id}:start"),
                payload={"component": "qwen3_32b_tp4_des", "path_id": path.path_id},
            )
        return run

    def schedule_rank_failure(
        self,
        *,
        failure_id: str,
        dp_rank: int,
        tp_rank: int,
        at_ns: int,
    ) -> EventHandle:
        """Schedule one rank failure whose fence always covers the complete TP4 group."""

        if type(failure_id) is not str or not failure_id:
            raise ValueError("failure_id must be a non-empty string")
        self._validate_dp_rank(dp_rank)
        require_nonnegative_int(tp_rank, "tp_rank")
        if tp_rank >= 4:
            raise ValueError("tp_rank is outside the configured TP4 group")
        require_nonnegative_int(at_ns, "at_ns")
        return self.des.schedule_at(
            at_ns,
            EventKind.FAILURE_INJECT,
            event_id=self._event_id(f"failure:{failure_id}"),
            payload={
                "component": "qwen3_32b_tp4_des",
                "failure_id": failure_id,
                "dp_rank": dp_rank,
                "failed_tp_rank": tp_rank,
            },
        )

    def recover_logical_chunk(
        self,
        protection: TP4ProtectionRun,
        *,
        pool: PolicyPool,
        start_ns: int,
        directory_install_ns: int,
        first_forward_bytes_per_rank: int,
        destination_dp_rank: int | None = None,
        peer_activation_ns_by_rank: tuple[int, ...] | None = None,
    ) -> TP4RecoveryRun:
        """Schedule shard recovery after the failed source group has been fenced."""

        if type(protection) is not TP4ProtectionRun:
            raise TypeError("protection must be an exact TP4ProtectionRun")
        if protection.protection_id not in self.protections:
            raise ValueError("protection does not belong to this DES")
        if type(pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        require_nonnegative_int(start_ns, "start_ns")
        require_nonnegative_int(directory_install_ns, "directory_install_ns")
        if type(first_forward_bytes_per_rank) is not int or first_forward_bytes_per_rank <= 0:
            raise ValueError("first_forward_bytes_per_rank must be positive")
        resolved_activation = peer_activation_ns_by_rank or (0, 0, 0, 0)
        if type(resolved_activation) is not tuple or len(resolved_activation) != 4:
            raise ValueError("Peer-HBM activation requires one duration per TP4 rank")
        for value in resolved_activation:
            require_nonnegative_int(value, "peer_activation_ns_by_rank item")
        if pool is PolicyPool.STORE_DRAM and any(resolved_activation):
            raise ValueError("Store-DRAM recovery cannot consume Peer-HBM activation costs")
        if start_ns < self.des.now_ns:
            raise ValueError("recovery start_ns cannot precede the GlobalDES clock")
        source_dp = protection.chunk.source_dp_rank
        if source_dp not in self.fenced_dp_ranks:
            raise ValueError("recovery requires the source TP4 group to be fenced")
        path = protection.path(pool)
        if path.state is not PathCommitState.COMMITTED or not path.capacity_committed:
            raise ValueError("recovery requires a committed all-shard capacity path")
        destination_dp = self._select_recovery_destination(
            path=path,
            requested=destination_dp_rank,
        )
        destination_ranks = self.groups[destination_dp].ranks
        destination_gpu_ids = tuple(rank.resource_id for rank in destination_ranks)
        nvlink_id = f"node:{destination_ranks[0].node_id}:nvlink"
        plan = path.transaction.build_recovery_plan(
            route_version=protection.chunk.route_version,
            layout=self.layout,
            destination_gpu_ids=destination_gpu_ids,
            nvlink_rate_resource_id=nvlink_id,
            model_all_reduce_bytes_per_rank=first_forward_bytes_per_rank,
        )
        recovery_id = f"recovery-{self._next_recovery:08d}"
        self._next_recovery += 1
        destination_ledger_ids = tuple(self._hbm_ledger_id(rank) for rank in destination_ranks)
        pending_accounts = tuple(f"PENDING_RECOVERY:{recovery_id}:tp{rank}" for rank in range(4))
        recovered_accounts = tuple(f"PRIMARY_RECOVERED:{recovery_id}:tp{rank}" for rank in range(4))
        rate_paths = tuple(
            self._recovery_rate_path(pool, path, destination_ranks[rank], rank) for rank in range(4)
        )
        recovery = TP4RecoveryRun(
            recovery_id=recovery_id,
            protection=protection,
            path=path,
            pool=pool,
            destination_dp_rank=destination_dp,
            plan=plan,
            scheduled_start_ns=start_ns,
            directory_install_ns=directory_install_ns,
            first_forward_bytes_per_rank=first_forward_bytes_per_rank,
            destination_ledger_ids=destination_ledger_ids,
            pending_accounts=pending_accounts,
            recovered_accounts=recovered_accounts,
            rate_resource_ids_by_rank=rate_paths,
            peer_activation_ns_by_rank=resolved_activation,
        )
        self.recoveries[recovery_id] = recovery
        handle = self.des.schedule_at(
            start_ns,
            EventKind.RECOVERY_START,
            event_id=self._event_id(f"{recovery_id}:start"),
            payload={"component": "qwen3_32b_tp4_des", "recovery_id": recovery_id},
        )
        recovery.event_handles.append(handle)
        return recovery

    def run(self, *, until_ns: int | None = None) -> int:
        return self.des.run(until_ns=until_ns)

    def schedule_algorithm3_control(
        self,
        *,
        target_dp_rank: int,
        at_ns: int,
        foreground_pressure: bool,
        reason: str,
    ) -> EventHandle:
        """Schedule one real target-local AIMD transition on the GlobalDES clock."""

        self._validate_dp_rank(target_dp_rank)
        require_nonnegative_int(at_ns, "at_ns")
        if type(foreground_pressure) is not bool:
            raise TypeError("foreground_pressure must be a bool")
        if type(reason) is not str or not reason:
            raise ValueError("reason must be a non-empty string")
        if foreground_pressure and reason == "STABLE_WINDOW":
            raise ValueError("a pressure signal requires a physical pressure reason")
        if not foreground_pressure and reason != "STABLE_WINDOW":
            raise ValueError("a stable control window must use reason=STABLE_WINDOW")
        return self.des.schedule_at(
            at_ns,
            EventKind.CONTROL_WINDOW,
            priority=(EventPriority.FENCE if foreground_pressure else EventPriority.NORMAL),
            event_id=self._event_id(f"algorithm3:dp{target_dp_rank}"),
            payload={
                "component": "qwen3_32b_tp4_des",
                "target_dp_rank": target_dp_rank,
                "foreground_pressure": foreground_pressure,
                "reason": reason,
            },
        )

    @property
    def peer_hbm_quota_bytes_per_rank(self) -> int:
        """Return the most restrictive target quota for legacy aggregate audits."""

        return min(self.peer_hbm_quota_bytes_by_target.values())

    def peer_hbm_pressure(self) -> PeerHBMPressureSnapshot:
        pending = {resource_id: 0 for resource_id in self.hbm_ledgers}
        committed = {resource_id: 0 for resource_id in self.hbm_ledgers}
        for protection in self.protections.values():
            path = protection.peer_hbm
            for rank, resource_id in enumerate(path.ledger_resource_ids):
                ledger = self.hbm_ledgers[resource_id]
                pending[resource_id] += ledger.bytes_in(path.pending_accounts[rank])
                committed[resource_id] += ledger.bytes_in(path.committed_accounts[rank])
        usage = {
            resource_id: pending[resource_id] + committed[resource_id]
            for resource_id in self.hbm_ledgers
        }
        pressure = {
            resource_id: (
                0
                if byte_count == 0
                else (
                    byte_count * 1000
                    + self.peer_hbm_quota_bytes_by_target[self._dp_rank_for_hbm(resource_id)]
                    - 1
                )
                // self.peer_hbm_quota_bytes_by_target[self._dp_rank_for_hbm(resource_id)]
            )
            for resource_id, byte_count in usage.items()
        }
        return PeerHBMPressureSnapshot(
            quota_bytes_per_rank=self.peer_hbm_quota_bytes_per_rank,
            quota_upper_bound_bytes_per_rank=(
                self.config.capacity.rank_hbm.peer_hbm_dynamic_quota_upper_bound_bytes_per_rank
            ),
            pending_bytes_by_rank=tuple(sorted(pending.items())),
            committed_bytes_by_rank=tuple(sorted(committed.items())),
            usage_bytes_by_rank=tuple(sorted(usage.items())),
            pressure_per_mille_by_rank=tuple(sorted(pressure.items())),
            maximum_usage_bytes=max(usage.values(), default=0),
            maximum_pressure_per_mille=max(pressure.values(), default=0),
        )

    def capacity_audit(self) -> CapacityConservationAudit:
        physical = sum(ledger.capacity_bytes for ledger in self.capacity_ledgers.values())
        accounts = sum(sum(ledger.accounts.values()) for ledger in self.capacity_ledgers.values())
        fixed_capacity_per_rank = (
            self.config.capacity.rank_hbm.model_weights_bytes_per_rank
            + self.config.capacity.rank_hbm.runtime_fixed_bytes_per_rank
        )
        fixed_capacity = len(self.hbm_ledgers) * fixed_capacity_per_rank
        fixed_accounts = sum(
            ledger.bytes_in(MODEL_WEIGHTS_ACCOUNT) + ledger.bytes_in(RUNTIME_FIXED_ACCOUNT)
            for ledger in self.hbm_ledgers.values()
        )
        kv_capacity = (
            len(self.hbm_ledgers) * self.config.capacity.rank_hbm.kv_capable_hbm_bytes_per_rank
        )
        kv_accounts = sum(
            sum(
                byte_count
                for account, byte_count in ledger.accounts.items()
                if account not in {MODEL_WEIGHTS_ACCOUNT, RUNTIME_FIXED_ACCOUNT}
            )
            for ledger in self.hbm_ledgers.values()
        )
        return CapacityConservationAudit(
            hbm_ledger_count=len(self.hbm_ledgers),
            store_ledger_count=1,
            physical_capacity_bytes=physical,
            account_bytes=accounts,
            fixed_hbm_capacity_bytes=fixed_capacity,
            fixed_hbm_account_bytes=fixed_accounts,
            kv_capable_hbm_capacity_bytes=kv_capacity,
            kv_capable_hbm_account_bytes=kv_accounts,
            valid=(
                len(self.hbm_ledgers) == 32
                and accounts == physical
                and fixed_accounts == fixed_capacity
                and kv_accounts == kv_capacity
            ),
        )

    def sweep_snapshot(self) -> dict[str, object]:
        """Return a JSON-safe result surface for a later parameter-sweep runner."""

        audit = self.capacity_audit()
        peer_pressure = self.peer_hbm_pressure()
        return {
            "schema": "moonkvsim.aegiskv.qwen3_32b_tp4_des.v1",
            "evidence_class": EVIDENCE_CLASS,
            "calibrated": False,
            "physical_measurement_completed": False,
            "now_ns": self.des.now_ns,
            "topology": {"dp_groups": 8, "tp_ranks_per_group": 4, "hbm_ledgers": 32},
            "fenced_dp_ranks": sorted(self.fenced_dp_ranks),
            "protection_paths": [
                {
                    "path_id": path.path_id,
                    "pool": path.pool.value,
                    "state": path.state.value,
                    "capacity_committed": path.capacity_committed,
                    "acked_ranks": list(path.transaction.acked_ranks),
                    "byte_conservation_valid": path.byte_audit.valid,
                }
                for run in self.protections.values()
                for path in (run.peer_hbm, run.store_dram)
            ],
            "recoveries": [
                {
                    "recovery_id": item.recovery_id,
                    "pool": item.pool.value,
                    "destination_dp_rank": item.destination_dp_rank,
                    "phase": item.phase.value,
                    "ready_ranks": sorted(item.ready_ranks),
                    "rank_ready_ns": dict(sorted(item.rank_ready_ns.items())),
                    "byte_conservation_valid": (
                        item.byte_audit.valid if item.byte_audit is not None else False
                    ),
                }
                for item in self.recoveries.values()
            ],
            "capacity": {
                "physical_capacity_bytes": audit.physical_capacity_bytes,
                "account_bytes": audit.account_bytes,
                "fixed_hbm_capacity_bytes": audit.fixed_hbm_capacity_bytes,
                "fixed_hbm_account_bytes": audit.fixed_hbm_account_bytes,
                "kv_capable_hbm_capacity_bytes": audit.kv_capable_hbm_capacity_bytes,
                "kv_capable_hbm_account_bytes": audit.kv_capable_hbm_account_bytes,
                "valid": audit.valid,
            },
            "peer_hbm_quota": {
                "controller_integration": "per_dp_rank_global_des_aimd",
                "quota_bytes_per_rank": peer_pressure.quota_bytes_per_rank,
                "quota_bytes_per_rank_by_target": dict(
                    sorted(self.peer_hbm_quota_bytes_by_target.items())
                ),
                "quota_upper_bound_bytes_per_rank": (
                    peer_pressure.quota_upper_bound_bytes_per_rank
                ),
                "pending_bytes_by_rank": dict(peer_pressure.pending_bytes_by_rank),
                "committed_bytes_by_rank": dict(peer_pressure.committed_bytes_by_rank),
                "usage_bytes_by_rank": dict(peer_pressure.usage_bytes_by_rank),
                "pressure_per_mille_by_rank": dict(peer_pressure.pressure_per_mille_by_rank),
                "maximum_usage_bytes": peer_pressure.maximum_usage_bytes,
                "maximum_pressure_per_mille": peer_pressure.maximum_pressure_per_mille,
                "audit": [item.to_dict() for item in self.algorithm3_audit],
            },
        }

    def _register_handlers(self) -> None:
        handlers = {
            EventKind.PUT_START: self._on_put_start,
            EventKind.TRANSFER_COMPLETE: self._on_transfer_complete,
            EventKind.PUT_COMMIT: self._on_put_commit,
            EventKind.FAILURE_INJECT: self._on_failure_inject,
            EventKind.ROUTE_FENCE: self._on_route_fence,
            EventKind.CONTROL_WINDOW: self._on_algorithm3_control,
            EventKind.RECOVERY_START: self._on_recovery_start,
            EventKind.GET_COMPLETE: self._on_recovery_shard_complete,
            EventKind.RECOVERY_COMPLETE: self._on_barrier_complete,
            EventKind.DIRECTORY_PUBLISH: self._on_directory_publish,
            EventKind.FORWARD_START: self._on_forward_start,
            EventKind.FORWARD_COMPLETE: self._on_forward_complete,
        }
        for kind, handler in handlers.items():
            self.des.register_handler(kind, handler)

    def _on_algorithm3_control(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        target_dp_rank = int(event.payload["target_dp_rank"])
        if target_dp_rank in self.algorithm3_fenced_targets:
            self.des.journal.append(
                self.des.now_ns,
                "ALGORITHM3_CONTROL_SKIPPED_FENCED",
                {"target_dp_rank": target_dp_rank},
            )
            return
        foreground_pressure = bool(event.payload["foreground_pressure"])
        reason = str(event.payload["reason"])
        state = self.algorithm3_states[target_dp_rank]
        if (
            not foreground_pressure
            and state.last_update_ns is not None
            and self.des.now_ns - state.last_update_ns != self.config.algorithm3.control_window_ns
        ):
            raise ValueError("stable Algorithm 3 updates must use the fixed control window")
        usage = self._peer_usage_for_target(target_dp_rank)
        resident_primary, free_reclaimable = self._target_physical_hbm_snapshot(target_dp_rank)
        decision = self.algorithm3_controller.update(
            state,
            foreground_pressure=foreground_pressure,
            current_protection_bytes=max(usage, default=0),
            timestamp_ns=self.des.now_ns,
        )
        if decision.bytes_to_reclaim:
            raise ValueError(
                "Algorithm 3 quota contraction requires Peer-HBM reclaim before publication"
            )
        self.algorithm3_states[target_dp_rank] = decision.next_state
        self.peer_hbm_quota_bytes_by_target[target_dp_rank] = decision.quota_bytes
        quota_enforced = all(value <= decision.quota_bytes for value in usage)
        if not quota_enforced:
            raise RuntimeError("Algorithm 3 published a quota below physical Peer-HBM usage")
        audit = Algorithm3AuditRecord(
            target_dp_rank=target_dp_rank,
            reason=reason,
            resident_primary_bytes_per_rank=resident_primary,
            free_reclaimable_bytes_per_rank=free_reclaimable,
            peer_usage_bytes_per_rank=usage,
            quota_enforced=quota_enforced,
            decision=decision,
        )
        self.algorithm3_audit.append(audit)
        self.des.journal.append(
            self.des.now_ns,
            "ALGORITHM3_AIMD_DECISION",
            audit.to_dict(),
        )

    def _admit_primary(self, chunk: TP4LogicalChunk) -> None:
        deltas = [
            AllocationDelta(
                resource_id=self._hbm_ledger_id(self.groups[chunk.source_dp_rank].ranks[rank]),
                account_from=FREE_ACCOUNT,
                account_to=chunk.primary_accounts[rank],
                delta_bytes=chunk.shard_bytes,
                allocation_id=f"{chunk.logical_chunk_id}:primary:tp{rank}",
                object_id=chunk.logical_chunk_id,
            )
            for rank in range(4)
        ]
        ResourceTransaction(
            event_id=self._event_id(f"{chunk.logical_chunk_id}:primary-admit"),
            timestamp_ns=self.des.now_ns,
            cause="QWEN3_TP4_PRIMARY_ADMIT",
            allocation_deltas=deltas,
        ).commit(self.capacity_ledgers, journal=self.des.journal)

    def _make_path(
        self,
        *,
        protection_id: str,
        chunk: TP4LogicalChunk,
        pool: PolicyPool,
        control: PathExecutionControl,
        start_ns: int,
    ) -> ProtectionPathRun:
        target_dp = (
            self.config.placement.peer_target_dp_by_source_dp[chunk.source_dp_rank]
            if pool is PolicyPool.PEER_HBM
            else None
        )
        path_id = f"{protection_id}:{pool.value}"
        shards: list[TPShardPlacement] = []
        ledger_ids: list[str] = []
        rate_paths: list[tuple[str, ...]] = []
        for tp_rank in range(4):
            source = self.groups[chunk.source_dp_rank].ranks[tp_rank]
            if pool is PolicyPool.PEER_HBM:
                assert target_dp is not None
                target = self.groups[target_dp].ranks[tp_rank]
                protection_resource_id = (
                    f"peer-hbm:{target.resource_id}:owner-dp{chunk.source_dp_rank}"
                )
                ledger_ids.append(self._hbm_ledger_id(target))
                rate_paths.append(
                    (
                        f"copy:{source.resource_id}:d2d",
                        f"fabric:{source.node_id}->{target.node_id}:rdma-gdr",
                        f"copy:{target.resource_id}:d2d",
                    )
                )
            else:
                protection_resource_id = f"store-dram:{chunk.logical_chunk_id}:tp{tp_rank}"
                ledger_ids.append(STORE_LEDGER_ID)
                rate_paths.append(
                    (
                        f"copy:{source.resource_id}:d2h",
                        f"fabric:{source.node_id}->store-dram-service:mooncake-rdma",
                        "store:store-dram-service:write",
                    )
                )
            shards.append(
                TPShardPlacement(
                    tp_rank=tp_rank,
                    source_gpu_id=source.resource_id,
                    protection_resource_id=protection_resource_id,
                    allocated_bytes=chunk.shard_bytes,
                )
            )
        transaction = TPChunkPathTransaction(
            transaction_id=path_id,
            logical_chunk_id=chunk.logical_chunk_id,
            pool=pool,
            route_version=chunk.route_version,
            layout=self.layout,
            shards=tuple(shards),
        )
        return ProtectionPathRun(
            path_id=path_id,
            chunk=chunk,
            pool=pool,
            transaction=transaction,
            source_dp_rank=chunk.source_dp_rank,
            target_dp_rank=target_dp,
            ledger_resource_ids=tuple(ledger_ids),
            pending_accounts=tuple(f"PENDING:{path_id}:tp{rank}" for rank in range(4)),
            committed_accounts=tuple(f"COMMITTED:{path_id}:tp{rank}" for rank in range(4)),
            rate_resource_ids_by_rank=tuple(rate_paths),
            control=control,
            scheduled_start_ns=start_ns,
        )

    def _on_put_start(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        path = self._path_by_id(str(event.payload["path_id"]))
        if path.state is not PathCommitState.PENDING:
            return
        if path.source_dp_rank in self.fenced_dp_ranks or (
            path.target_dp_rank is not None and path.target_dp_rank in self.fenced_dp_ranks
        ):
            self._abort_path(path, reason="TP_GROUP_FENCED")
            return
        if path.pool is PolicyPool.PEER_HBM and not self._peer_quota_allows(path):
            target_dp_rank = path.target_dp_rank
            if target_dp_rank is None:
                raise RuntimeError("Peer-HBM rejection omitted its target DP rank")
            path.transaction.abort(reason="PEER_HBM_DYNAMIC_QUOTA_EXCEEDED")
            self.des.journal.append(
                self.des.now_ns,
                "TP_PATH_ADMISSION_REJECTED",
                {
                    "path_id": path.path_id,
                    "quota_bytes_per_rank": self.peer_hbm_quota_bytes_by_target[target_dp_rank],
                    "target_dp_rank": target_dp_rank,
                    "reason": "PEER_HBM_DYNAMIC_QUOTA_EXCEEDED",
                },
            )
            return
        deltas = [
            AllocationDelta(
                resource_id=path.ledger_resource_ids[rank],
                account_from=FREE_ACCOUNT,
                account_to=path.pending_accounts[rank],
                delta_bytes=path.chunk.shard_bytes,
                allocation_id=f"{path.path_id}:reserve:tp{rank}",
                object_id=path.chunk.logical_chunk_id,
                replica_id=path.path_id,
                transfer_id=f"{path.path_id}:tp{rank}",
            )
            for rank in range(4)
        ]
        try:
            ResourceTransaction(
                event_id=event.event_id,
                timestamp_ns=self.des.now_ns,
                cause=f"QWEN3_TP4_{path.pool.value}_RESERVE",
                allocation_deltas=deltas,
            ).commit(self.capacity_ledgers, journal=self.des.journal)
        except ValueError as error:
            path.transaction.abort(reason="CAPACITY_ADMISSION_FAILED")
            self.des.journal.append(
                self.des.now_ns,
                "TP_PATH_ADMISSION_REJECTED",
                {"path_id": path.path_id, "reason": str(error)},
            )
            return
        path.admitted = True
        cost = (
            self.config.modeled_costs.cross_node_peer_hbm
            if path.pool is PolicyPool.PEER_HBM
            else self.config.modeled_costs.store_dram
        )
        for tp_rank in range(4):
            duration_ns = self._duration_ns(
                byte_count=path.chunk.shard_bytes,
                resource_ids=path.rate_resource_ids_by_rank[tp_rank],
                setup_ns=cost.setup_ns,
            )
            outcome = "ACK"
            if tp_rank in path.control.failed_tp_ranks:
                outcome = "FAILED"
            elif tp_rank in path.control.no_ack_tp_ranks:
                outcome = "NO_ACK"
            handle = self.des.schedule_at(
                self.des.now_ns + duration_ns,
                EventKind.TRANSFER_COMPLETE,
                event_id=self._event_id(f"{path.path_id}:tp{tp_rank}:complete"),
                payload={
                    "component": "qwen3_32b_tp4_des",
                    "path_id": path.path_id,
                    "tp_rank": tp_rank,
                    "outcome": outcome,
                    "shard_bytes": path.chunk.shard_bytes,
                    "rate_resource_ids": list(path.rate_resource_ids_by_rank[tp_rank]),
                },
            )
            path.completion_handles[tp_rank] = handle
        self.des.journal.append(
            self.des.now_ns,
            "TP_PATH_RATE_RESOURCES_BOUND",
            {
                "path_id": path.path_id,
                "rank_paths": [list(item) for item in path.rate_resource_ids_by_rank],
            },
        )

    def _on_transfer_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        path = self._path_by_id(str(event.payload["path_id"]))
        if path.state is not PathCommitState.PENDING:
            return
        tp_rank = int(event.payload["tp_rank"])
        outcome = str(event.payload["outcome"])
        if outcome == "FAILED":
            self._abort_path(path, reason=f"SHARD_TRANSFER_FAILED:tp={tp_rank}")
            return
        path.transferred_bytes_by_rank[tp_rank] = path.chunk.shard_bytes
        if outcome == "NO_ACK":
            self.des.journal.append(
                self.des.now_ns,
                "TP_SHARD_NO_ACK",
                {"path_id": path.path_id, "tp_rank": tp_rank},
            )
            return
        just_committed = path.transaction.acknowledge_shard(
            tp_rank,
            timestamp_ns=self.des.now_ns,
            route_version=path.chunk.route_version,
            layout=self.layout,
        )
        self.des.journal.append(
            self.des.now_ns,
            "TP_SHARD_ACK",
            {"path_id": path.path_id, "tp_rank": tp_rank},
        )
        if just_committed:
            self.des.schedule_at(
                self.des.now_ns,
                EventKind.PUT_COMMIT,
                event_id=self._event_id(f"{path.path_id}:commit"),
                payload={"component": "qwen3_32b_tp4_des", "path_id": path.path_id},
            )

    def _on_put_commit(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        path = self._path_by_id(str(event.payload["path_id"]))
        if path.state is not PathCommitState.COMMITTED or path.capacity_committed:
            return
        deltas = [
            AllocationDelta(
                resource_id=path.ledger_resource_ids[rank],
                account_from=path.pending_accounts[rank],
                account_to=path.committed_accounts[rank],
                delta_bytes=path.chunk.shard_bytes,
                allocation_id=f"{path.path_id}:commit:tp{rank}",
                object_id=path.chunk.logical_chunk_id,
                replica_id=path.path_id,
                transfer_id=f"{path.path_id}:tp{rank}",
            )
            for rank in range(4)
        ]
        ResourceTransaction(
            event_id=event.event_id,
            timestamp_ns=self.des.now_ns,
            cause=f"QWEN3_TP4_{path.pool.value}_COMMIT_ALL_ACK",
            allocation_deltas=deltas,
        ).commit(self.capacity_ledgers, journal=self.des.journal)
        path.capacity_committed = True
        self.des.journal.append(
            self.des.now_ns,
            "TP_PATH_COMMITTED",
            {"acked_ranks": list(path.transaction.acked_ranks), "path_id": path.path_id},
        )

    def _on_failure_inject(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        self.des.schedule_at(
            self.des.now_ns,
            EventKind.ROUTE_FENCE,
            event_id=self._event_id(f"{event.payload['failure_id']}:group-fence"),
            payload=dict(event.payload),
        )

    def _on_route_fence(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        dp_rank = int(event.payload["dp_rank"])
        if dp_rank in self.fenced_dp_ranks:
            return
        self.algorithm3_fenced_targets.add(dp_rank)
        for run in self.protections.values():
            for path in (run.peer_hbm, run.store_dram):
                if path.state is PathCommitState.PENDING and (
                    path.source_dp_rank == dp_rank or path.target_dp_rank == dp_rank
                ):
                    self._abort_path(path, reason=f"TP_GROUP_FENCED:dp={dp_rank}")
        for recovery in self.recoveries.values():
            if (
                recovery.phase not in {RecoveryPhase.FORWARD_COMPLETE, RecoveryPhase.ABORTED}
                and recovery.destination_dp_rank == dp_rank
            ):
                self._abort_recovery(recovery, reason=f"TP_GROUP_FENCED:dp={dp_rank}")
        self.fenced_dp_ranks.add(dp_rank)
        deltas: list[AllocationDelta] = []
        for rank in self.groups[dp_rank].ranks:
            ledger = self.hbm_ledgers[self._hbm_ledger_id(rank)]
            for account, byte_count in ledger.accounts.items():
                if (
                    account
                    in {
                        MODEL_WEIGHTS_ACCOUNT,
                        RUNTIME_FIXED_ACCOUNT,
                        UNAVAILABLE_CAPACITY_ACCOUNT,
                    }
                    or byte_count == 0
                ):
                    continue
                deltas.append(
                    AllocationDelta(
                        resource_id=ledger.resource_id,
                        account_from=account,
                        account_to=UNAVAILABLE_CAPACITY_ACCOUNT,
                        delta_bytes=byte_count,
                        allocation_id=f"fence:dp{dp_rank}:{rank.tp_rank}:{account}",
                    )
                )
        ResourceTransaction(
            event_id=event.event_id,
            timestamp_ns=self.des.now_ns,
            cause="QWEN3_TP4_WHOLE_GROUP_FENCE",
            allocation_deltas=deltas,
        ).commit(self.capacity_ledgers, journal=self.des.journal)
        self.des.journal.append(
            self.des.now_ns,
            "TP_GROUP_FENCED",
            {
                "dp_rank": dp_rank,
                "failed_tp_rank": int(event.payload["failed_tp_rank"]),
                "rank_resource_ids": [rank.resource_id for rank in self.groups[dp_rank].ranks],
            },
        )
        self.des.journal.append(
            self.des.now_ns,
            "ALGORITHM3_TARGET_FENCED",
            {
                "target_dp_rank": dp_rank,
                "last_update_ns": self.algorithm3_states[dp_rank].last_update_ns,
                "quota_bytes_per_rank": self.peer_hbm_quota_bytes_by_target[dp_rank],
            },
        )

    def _on_recovery_start(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        recovery = self.recoveries[str(event.payload["recovery_id"])]
        if recovery.destination_dp_rank in self.fenced_dp_ranks:
            self._abort_recovery(recovery, reason="DESTINATION_TP_GROUP_FENCED")
            return
        if recovery.pool is PolicyPool.STORE_DRAM:
            deltas = [
                AllocationDelta(
                    resource_id=recovery.destination_ledger_ids[rank],
                    account_from=FREE_ACCOUNT,
                    account_to=recovery.pending_accounts[rank],
                    delta_bytes=recovery.protection.chunk.shard_bytes,
                    allocation_id=f"{recovery.recovery_id}:reserve:tp{rank}",
                    object_id=recovery.protection.chunk.logical_chunk_id,
                )
                for rank in range(4)
            ]
            try:
                ResourceTransaction(
                    event_id=event.event_id,
                    timestamp_ns=self.des.now_ns,
                    cause="QWEN3_TP4_STORE_RECOVERY_RESERVE",
                    allocation_deltas=deltas,
                ).commit(self.capacity_ledgers, journal=self.des.journal)
            except ValueError as error:
                self._abort_recovery(recovery, reason=f"CAPACITY_ADMISSION_FAILED:{error}")
                return
            recovery.capacity_reserved = True
        for tp_rank in range(4):
            if recovery.pool is PolicyPool.PEER_HBM:
                duration_ns = recovery.peer_activation_ns_by_rank[tp_rank]
                transfer_bytes = 0
                activated_bytes = recovery.protection.chunk.shard_bytes
            else:
                duration_ns = self._duration_ns(
                    byte_count=recovery.protection.chunk.shard_bytes,
                    resource_ids=recovery.rate_resource_ids_by_rank[tp_rank],
                    setup_ns=self.config.modeled_costs.store_dram.setup_ns,
                )
                transfer_bytes = recovery.protection.chunk.shard_bytes
                activated_bytes = 0
            handle = self.des.schedule_at(
                self.des.now_ns + duration_ns,
                EventKind.GET_COMPLETE,
                event_id=self._event_id(f"{recovery.recovery_id}:tp{tp_rank}:ready"),
                payload={
                    "component": "qwen3_32b_tp4_des",
                    "recovery_id": recovery.recovery_id,
                    "tp_rank": tp_rank,
                    "transfer_bytes": transfer_bytes,
                    "activated_bytes": activated_bytes,
                    "rate_resource_ids": list(recovery.rate_resource_ids_by_rank[tp_rank]),
                },
            )
            recovery.event_handles.append(handle)

    def _on_recovery_shard_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        recovery = self.recoveries[str(event.payload["recovery_id"])]
        if recovery.phase is not RecoveryPhase.SCHEDULED:
            return
        tp_rank = int(event.payload["tp_rank"])
        if tp_rank in recovery.ready_ranks:
            raise RuntimeError("one recovery TP rank completed more than once")
        recovery.ready_ranks.add(tp_rank)
        recovery.rank_ready_ns[tp_rank] = self.des.now_ns
        if len(recovery.ready_ranks) != 4:
            return
        recovery.phase = RecoveryPhase.SHARDS_READY
        recovery.shard_ready_ns = self.des.now_ns
        handle = self.des.schedule_at(
            self.des.now_ns + self.config.modeled_costs.tp_collective_sync.fixed_overhead_ns,
            EventKind.RECOVERY_COMPLETE,
            event_id=self._event_id(f"{recovery.recovery_id}:barrier-complete"),
            payload={
                "component": "qwen3_32b_tp4_des",
                "phase": "TP_READINESS_BARRIER_COMPLETE",
                "recovery_id": recovery.recovery_id,
                "payload_bytes": 0,
                "rate_resource_id": recovery.plan.collectives[0].rate_resource_id,
            },
        )
        recovery.event_handles.append(handle)

    def _on_barrier_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        recovery = self.recoveries[str(event.payload["recovery_id"])]
        if recovery.phase is not RecoveryPhase.SHARDS_READY:
            return
        if recovery.pool is PolicyPool.STORE_DRAM:
            deltas = [
                AllocationDelta(
                    resource_id=recovery.destination_ledger_ids[rank],
                    account_from=recovery.pending_accounts[rank],
                    account_to=recovery.recovered_accounts[rank],
                    delta_bytes=recovery.protection.chunk.shard_bytes,
                    allocation_id=f"{recovery.recovery_id}:commit:tp{rank}",
                    object_id=recovery.protection.chunk.logical_chunk_id,
                )
                for rank in range(4)
            ]
            ResourceTransaction(
                event_id=event.event_id,
                timestamp_ns=self.des.now_ns,
                cause="QWEN3_TP4_RECOVERY_COMMIT_AFTER_BARRIER",
                allocation_deltas=deltas,
            ).commit(self.capacity_ledgers, journal=self.des.journal)
            recovery.capacity_reserved = False
            recovery.capacity_committed = True
        recovery.phase = RecoveryPhase.BARRIER_COMPLETE
        recovery.barrier_complete_ns = self.des.now_ns
        handle = self.des.schedule_at(
            self.des.now_ns + recovery.directory_install_ns,
            EventKind.DIRECTORY_PUBLISH,
            event_id=self._event_id(f"{recovery.recovery_id}:directory-install"),
            payload={
                "component": "qwen3_32b_tp4_des",
                "phase": "DIRECTORY_GENERATION_INSTALL",
                "recovery_id": recovery.recovery_id,
            },
        )
        recovery.event_handles.append(handle)

    def _on_directory_publish(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        recovery = self.recoveries[str(event.payload["recovery_id"])]
        if recovery.phase is not RecoveryPhase.BARRIER_COMPLETE:
            return
        recovery.phase = RecoveryPhase.DIRECTORY_INSTALLED
        recovery.directory_installed_ns = self.des.now_ns
        handle = self.des.schedule_at(
            self.des.now_ns,
            EventKind.FORWARD_START,
            event_id=self._event_id(f"{recovery.recovery_id}:first-forward-start"),
            payload={
                "component": "qwen3_32b_tp4_des",
                "phase": "FIRST_FORWARD_MODEL_COLLECTIVE",
                "recovery_id": recovery.recovery_id,
            },
        )
        recovery.event_handles.append(handle)

    def _on_forward_start(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        recovery = self.recoveries[str(event.payload["recovery_id"])]
        if recovery.phase is not RecoveryPhase.DIRECTORY_INSTALLED:
            return
        recovery.forward_start_ns = self.des.now_ns
        resource_id = recovery.plan.collectives[-1].rate_resource_id
        duration_ns = self._duration_ns(
            byte_count=recovery.first_forward_bytes_per_rank,
            resource_ids=(resource_id,),
            setup_ns=self.config.modeled_costs.intra_node_nvlink.setup_ns,
        )
        handle = self.des.schedule_at(
            self.des.now_ns + duration_ns,
            EventKind.FORWARD_COMPLETE,
            event_id=self._event_id(f"{recovery.recovery_id}:first-forward-complete"),
            payload={
                "component": "qwen3_32b_tp4_des",
                "operates_on_kv": False,
                "payload_bytes_per_rank": recovery.first_forward_bytes_per_rank,
                "rate_resource_id": resource_id,
                "recovery_id": recovery.recovery_id,
            },
        )
        recovery.event_handles.append(handle)

    def _on_forward_complete(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        recovery = self.recoveries[str(event.payload["recovery_id"])]
        recovery.phase = RecoveryPhase.FORWARD_COMPLETE
        recovery.forward_complete_ns = self.des.now_ns
        logical_bytes = recovery.protection.chunk.logical_chunk_bytes
        is_store = recovery.pool is PolicyPool.STORE_DRAM
        recovery.byte_audit = RecoveryByteAudit(
            pool=recovery.pool,
            logical_chunk_bytes=logical_bytes,
            sum_rank_restored_kv_bytes=4 * recovery.protection.chunk.shard_bytes,
            source_read_bytes=logical_bytes if is_store else 0,
            destination_write_bytes=logical_bytes if is_store else 0,
            activated_bytes=0 if is_store else logical_bytes,
            kv_reduction_bytes=0,
            model_collective_bytes_excluded=4 * recovery.first_forward_bytes_per_rank,
            valid=(
                4 * recovery.protection.chunk.shard_bytes == logical_bytes
                and (
                    (is_store and recovery.capacity_committed)
                    or (not is_store and recovery.path.capacity_committed)
                )
            ),
        )

    def _abort_path(self, path: ProtectionPathRun, *, reason: str) -> None:
        if path.state is not PathCommitState.PENDING:
            return
        path.transaction.abort(reason=reason)
        for handle in path.completion_handles.values():
            self.des.cancel(handle, reason=reason)
        if path.admitted:
            deltas = [
                AllocationDelta(
                    resource_id=path.ledger_resource_ids[rank],
                    account_from=path.pending_accounts[rank],
                    account_to=FREE_ACCOUNT,
                    delta_bytes=path.chunk.shard_bytes,
                    allocation_id=f"{path.path_id}:abort:tp{rank}",
                    object_id=path.chunk.logical_chunk_id,
                )
                for rank in range(4)
            ]
            ResourceTransaction(
                event_id=self._event_id(f"{path.path_id}:abort"),
                timestamp_ns=self.des.now_ns,
                cause="QWEN3_TP4_PATH_ABORT_RELEASE",
                allocation_deltas=deltas,
            ).commit(self.capacity_ledgers, journal=self.des.journal)
            path.admitted = False
        self.des.journal.append(
            self.des.now_ns,
            "TP_PATH_ABORTED",
            {"path_id": path.path_id, "reason": reason},
        )

    def _abort_recovery(self, recovery: TP4RecoveryRun, *, reason: str) -> None:
        for handle in recovery.event_handles:
            self.des.cancel(handle, reason=reason)
        if recovery.capacity_reserved:
            deltas = [
                AllocationDelta(
                    resource_id=recovery.destination_ledger_ids[rank],
                    account_from=recovery.pending_accounts[rank],
                    account_to=FREE_ACCOUNT,
                    delta_bytes=recovery.protection.chunk.shard_bytes,
                    allocation_id=f"{recovery.recovery_id}:abort:tp{rank}",
                )
                for rank in range(4)
            ]
            ResourceTransaction(
                event_id=self._event_id(f"{recovery.recovery_id}:abort"),
                timestamp_ns=self.des.now_ns,
                cause="QWEN3_TP4_RECOVERY_ABORT_RELEASE",
                allocation_deltas=deltas,
            ).commit(self.capacity_ledgers, journal=self.des.journal)
            recovery.capacity_reserved = False
        recovery.phase = RecoveryPhase.ABORTED
        recovery.terminal_reason = reason

    def _select_recovery_destination(
        self,
        *,
        path: ProtectionPathRun,
        requested: int | None,
    ) -> int:
        if path.pool is PolicyPool.PEER_HBM:
            assert path.target_dp_rank is not None
            if requested is not None and requested != path.target_dp_rank:
                raise ValueError("Peer-HBM recovery must activate its mapped TP4 group")
            candidate = path.target_dp_rank
        elif requested is not None:
            self._validate_dp_rank(requested)
            candidate = requested
        else:
            candidates = ((path.source_dp_rank + offset) % 8 for offset in range(1, 9))
            candidate = next(
                (item for item in candidates if item not in self.fenced_dp_ranks),
                -1,
            )
        if candidate < 0 or candidate in self.fenced_dp_ranks:
            raise ValueError("no healthy complete TP4 destination group is available")
        return candidate

    def _recovery_rate_path(
        self,
        pool: PolicyPool,
        path: ProtectionPathRun,
        destination: RankPlacement,
        tp_rank: int,
    ) -> tuple[str, ...]:
        if pool is PolicyPool.PEER_HBM:
            return (f"node:{destination.node_id}:nvlink",)
        return (
            "store:store-dram-service:read",
            f"fabric:store-dram-service->{destination.node_id}:mooncake-rdma",
            f"copy:{destination.resource_id}:h2d",
        )

    def _build_rate_resources(self) -> dict[str, RateResource]:
        resources: dict[str, RateResource] = {}

        def add(resource_id: str, capacity: int) -> None:
            current = resources.get(resource_id)
            if current is not None:
                if current.capacity_bytes_per_second != float(capacity):
                    raise ValueError(f"conflicting modeled rate for {resource_id}")
                return
            resources[resource_id] = RateResource(
                resource_id=resource_id,
                capacity_bytes_per_second=float(capacity),
            )

        peer = self.config.modeled_costs.cross_node_peer_hbm.effective_bandwidth_bytes_per_second
        store = self.config.modeled_costs.store_dram.effective_bandwidth_bytes_per_second
        nvlink = self.config.modeled_costs.intra_node_nvlink.effective_bandwidth_bytes_per_second
        for group in self.groups:
            target_dp = self.config.placement.peer_target_dp_by_source_dp[group.dp_rank]
            target_node = self.groups[target_dp].ranks[0].node_id
            source_node = group.ranks[0].node_id
            add(f"fabric:{source_node}->{target_node}:rdma-gdr", peer)
            add(f"fabric:{source_node}->store-dram-service:mooncake-rdma", store)
            add(f"fabric:store-dram-service->{source_node}:mooncake-rdma", store)
            add(f"node:{source_node}:nvlink", nvlink)
            for rank in group.ranks:
                add(f"copy:{rank.resource_id}:d2d", peer)
                add(f"copy:{rank.resource_id}:d2h", store)
                add(f"copy:{rank.resource_id}:h2d", store)
        add("store:store-dram-service:write", store)
        add("store:store-dram-service:read", store)
        return resources

    def _duration_ns(
        self,
        *,
        byte_count: int,
        resource_ids: tuple[str, ...],
        setup_ns: int,
    ) -> int:
        require_nonnegative_int(byte_count, "byte_count")
        require_nonnegative_int(setup_ns, "setup_ns")
        rates = [
            self.rate_resources[resource_id].capacity_bytes_per_second
            for resource_id in resource_ids
        ]
        bandwidth = int(min(rates))
        return setup_ns + (byte_count * _NS_PER_SECOND + bandwidth - 1) // bandwidth

    def _path_by_id(self, path_id: str) -> ProtectionPathRun:
        for run in self.protections.values():
            for path in (run.peer_hbm, run.store_dram):
                if path.path_id == path_id:
                    return path
        raise KeyError(f"unknown protection path: {path_id}")

    def _peer_quota_allows(self, path: ProtectionPathRun) -> bool:
        if path.target_dp_rank is None:
            raise RuntimeError("Peer-HBM quota admission requires a target DP rank")
        pressure = dict(self.peer_hbm_pressure().usage_bytes_by_rank)
        quota = self.peer_hbm_quota_bytes_by_target[path.target_dp_rank]
        return all(
            pressure[resource_id] + path.chunk.shard_bytes <= quota
            for resource_id in path.ledger_resource_ids
        )

    def _peer_usage_for_target(self, target_dp_rank: int) -> tuple[int, ...]:
        pressure = dict(self.peer_hbm_pressure().usage_bytes_by_rank)
        return tuple(
            pressure[self._hbm_ledger_id(rank)] for rank in self.groups[target_dp_rank].ranks
        )

    def _target_physical_hbm_snapshot(
        self, target_dp_rank: int
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        resident: list[int] = []
        free_reclaimable: list[int] = []
        peer_usage = self._peer_usage_for_target(target_dp_rank)
        for tp_rank, rank in enumerate(self.groups[target_dp_rank].ranks):
            ledger = self.hbm_ledgers[self._hbm_ledger_id(rank)]
            primary = sum(
                byte_count
                for account, byte_count in ledger.accounts.items()
                if account.startswith("PRIMARY:") or account.startswith("PRIMARY_RECOVERED:")
            )
            resident.append(primary)
            free_reclaimable.append(ledger.bytes_in(FREE_ACCOUNT) + peer_usage[tp_rank])
        return tuple(resident), tuple(free_reclaimable)

    @staticmethod
    def _dp_rank_for_hbm(resource_id: str) -> int:
        prefix = "hbm:gpu:node-"
        if not resource_id.startswith(prefix):
            raise ValueError(f"unexpected Qwen3 TP4 HBM resource id: {resource_id}")
        return int(resource_id[len(prefix) :].split(":", maxsplit=1)[0])

    def _check_capacity_invariant(self, _des: GlobalDES) -> None:
        rank_capacity = self.config.capacity.rank_hbm
        for resource_id, ledger in self.capacity_ledgers.items():
            if any(value < 0 for value in ledger.accounts.values()):
                raise RuntimeError(f"negative capacity account on {resource_id}")
            if sum(ledger.accounts.values()) != ledger.capacity_bytes:
                raise RuntimeError(f"capacity is not conserved on {resource_id}")
        for resource_id, ledger in self.hbm_ledgers.items():
            if ledger.bytes_in(MODEL_WEIGHTS_ACCOUNT) != rank_capacity.model_weights_bytes_per_rank:
                raise RuntimeError(f"model-weight capacity drift on {resource_id}")
            if ledger.bytes_in(RUNTIME_FIXED_ACCOUNT) != rank_capacity.runtime_fixed_bytes_per_rank:
                raise RuntimeError(f"runtime-fixed capacity drift on {resource_id}")
            kv_accounts = sum(
                byte_count
                for account, byte_count in ledger.accounts.items()
                if account not in {MODEL_WEIGHTS_ACCOUNT, RUNTIME_FIXED_ACCOUNT}
            )
            if kv_accounts != rank_capacity.kv_capable_hbm_bytes_per_rank:
                raise RuntimeError(f"KV-capable HBM capacity drift on {resource_id}")
        for target_dp_rank, quota in self.peer_hbm_quota_bytes_by_target.items():
            if max(self._peer_usage_for_target(target_dp_rank), default=0) > quota:
                raise RuntimeError(
                    f"Peer-HBM usage exceeds the installed quota for dp={target_dp_rank}"
                )

    def _event_id(self, suffix: str) -> str:
        value = f"qwen3-tp4-{self._next_event:012d}:{suffix}"
        self._next_event += 1
        return value

    def _validate_dp_rank(self, dp_rank: int) -> None:
        require_nonnegative_int(dp_rank, "dp_rank")
        if dp_rank >= 8:
            raise ValueError("dp_rank is outside the configured DP8 topology")

    @staticmethod
    def _validate_control(control: PathExecutionControl) -> None:
        if type(control) is not PathExecutionControl:
            raise TypeError("path controls must be exact PathExecutionControl values")
        if any(rank >= 4 for rank in control.no_ack_tp_ranks | control.failed_tp_ranks):
            raise ValueError("path control rank is outside TP4")

    @staticmethod
    def _hbm_ledger_id(rank: RankPlacement) -> str:
        return f"hbm:{rank.resource_id}"

    @staticmethod
    def _validate_contract(config: Qwen3TP4EngineConfig) -> None:
        parallelism = config.parallelism
        if (
            parallelism.data_parallel_size != 8
            or parallelism.tensor_parallel_size != 4
            or parallelism.pipeline_parallel_size != 1
            or parallelism.world_size != 32
            or config.cluster.gpu_count != 32
        ):
            raise ValueError(
                "Qwen3TP4GroupDES requires the strict DP8/TP4/PP1 world-size-32 config"
            )
        rank_capacity = config.capacity.rank_hbm
        if (
            config.capacity.status != EVIDENCE_CLASS
            or rank_capacity.physical_hbm_bytes_per_rank
            != config.cluster.physical_hbm_bytes_per_gpu
            or rank_capacity.model_weights_bytes_per_rank
            + rank_capacity.runtime_fixed_bytes_per_rank
            + rank_capacity.kv_capable_hbm_bytes_per_rank
            != rank_capacity.physical_hbm_bytes_per_rank
        ):
            raise ValueError("rank HBM fixed/KV-capable capacity contract drift")
        if (
            rank_capacity.peer_hbm_dynamic_quota_upper_bound_numerator != 1
            or rank_capacity.peer_hbm_dynamic_quota_upper_bound_denominator != 2
            or rank_capacity.peer_hbm_dynamic_quota_upper_bound_bytes_per_rank * 2
            != rank_capacity.kv_capable_hbm_bytes_per_rank
        ):
            raise ValueError("Peer-HBM dynamic quota upper bound must equal one-half")
        store = config.capacity.store_dram
        if (
            store.store_node_count != 1
            or len(store.segments) != 1
            or store.segments[0].segment_id != STORE_LEDGER_ID
            or store.segments[0].capacity_bytes != store.total_capacity_bytes
        ):
            raise ValueError("Store DRAM must be the one configured physical segment")
        if (
            config.evidence.timing_and_bandwidth != EVIDENCE_CLASS
            or config.evidence.capacity != EVIDENCE_CLASS
            or config.evidence.calibrated
            or config.evidence.physical_measurement_completed
        ):
            raise ValueError("Qwen3TP4GroupDES must remain modeled_uncalibrated")


__all__ = [
    "EVIDENCE_CLASS",
    "MODEL_WEIGHTS_ACCOUNT",
    "RUNTIME_FIXED_ACCOUNT",
    "STORE_LEDGER_ID",
    "Algorithm3AuditRecord",
    "CapacityConservationAudit",
    "PeerHBMPressureSnapshot",
    "ProtectionByteAudit",
    "ProtectionPathRun",
    "Qwen3TP4GroupDES",
    "RecoveryByteAudit",
    "RecoveryPhase",
    "TP4Group",
    "TP4LogicalChunk",
    "TP4ProtectionRun",
    "TP4RecoveryRun",
]
