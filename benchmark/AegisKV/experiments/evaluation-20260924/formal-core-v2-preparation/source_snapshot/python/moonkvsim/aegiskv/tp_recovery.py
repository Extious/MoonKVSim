"""Tensor-parallel shard commit and recovery contracts for AegisKV.

KV cache is sharded by the model's parallel layout.  Each rank restores its own bytes;
collectives synchronize activation and execute the model, but never mathematically reduce
KV shards into one tensor.  This module is a pure state machine and schedules no time by
itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from moonkvsim.aegiskv.types import PathCommitState, PolicyPool, require_nonnegative_int


class TPCollectiveKind(StrEnum):
    ACTIVATION_BARRIER = "ACTIVATION_BARRIER"
    MODEL_ALL_REDUCE = "MODEL_ALL_REDUCE"


@dataclass(frozen=True, slots=True)
class TPLayoutIdentity:
    model_revision: str
    kv_abi: str
    layout_id: str
    tensor_parallel_size: int
    pipeline_parallel_size: int = 1

    def __post_init__(self) -> None:
        for name, value in (
            ("model_revision", self.model_revision),
            ("kv_abi", self.kv_abi),
            ("layout_id", self.layout_id),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.tensor_parallel_size) is not int or self.tensor_parallel_size <= 0:
            raise ValueError("tensor_parallel_size must be a positive integer")
        if type(self.pipeline_parallel_size) is not int or self.pipeline_parallel_size <= 0:
            raise ValueError("pipeline_parallel_size must be a positive integer")


@dataclass(frozen=True, slots=True)
class TPShardPlacement:
    tp_rank: int
    source_gpu_id: str
    protection_resource_id: str
    allocated_bytes: int

    def __post_init__(self) -> None:
        require_nonnegative_int(self.tp_rank, "tp_rank")
        if type(self.source_gpu_id) is not str or not self.source_gpu_id:
            raise ValueError("source_gpu_id must be a non-empty string")
        if type(self.protection_resource_id) is not str or not self.protection_resource_id:
            raise ValueError("protection_resource_id must be a non-empty string")
        if type(self.allocated_bytes) is not int or self.allocated_bytes <= 0:
            raise ValueError("allocated_bytes must be a positive integer")


@dataclass(frozen=True, slots=True)
class TPCollectiveWork:
    kind: TPCollectiveKind
    participant_gpu_ids: tuple[str, ...]
    payload_bytes_per_rank: int
    rate_resource_id: str

    def __post_init__(self) -> None:
        if type(self.kind) is not TPCollectiveKind:
            raise TypeError("kind must be an exact TPCollectiveKind")
        if type(self.participant_gpu_ids) is not tuple or not self.participant_gpu_ids:
            raise ValueError("participant_gpu_ids must be a non-empty tuple")
        if len(set(self.participant_gpu_ids)) != len(self.participant_gpu_ids):
            raise ValueError("collective participants must be unique")
        if type(self.payload_bytes_per_rank) is not int or self.payload_bytes_per_rank < 0:
            raise ValueError("payload_bytes_per_rank must be a non-negative integer")
        if type(self.rate_resource_id) is not str or not self.rate_resource_id:
            raise ValueError("rate_resource_id must be a non-empty string")


@dataclass(frozen=True, slots=True)
class TPRecoveryPlan:
    logical_chunk_id: str
    pool: PolicyPool
    route_version: int
    rank_sources: tuple[tuple[int, str], ...]
    rank_destinations: tuple[tuple[int, str], ...]
    collectives: tuple[TPCollectiveWork, ...]
    kv_shards_are_reduced: bool = False

    def __post_init__(self) -> None:
        if not self.logical_chunk_id:
            raise ValueError("logical_chunk_id must be non-empty")
        if type(self.pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        require_nonnegative_int(self.route_version, "route_version")
        if self.kv_shards_are_reduced:
            raise ValueError("tensor-parallel KV shards must never be mathematically reduced")
        source_ranks = tuple(rank for rank, _resource in self.rank_sources)
        destination_ranks = tuple(rank for rank, _gpu in self.rank_destinations)
        if source_ranks != destination_ranks:
            raise ValueError("recovery source and destination TP ranks must match")
        if source_ranks != tuple(range(len(source_ranks))):
            raise ValueError("recovery plan requires contiguous TP ranks from zero")
        if (
            not self.collectives
            or self.collectives[0].kind is not TPCollectiveKind.ACTIVATION_BARRIER
        ):
            raise ValueError("recovery plan must begin with an activation barrier")


@dataclass(slots=True)
class TPChunkPathTransaction:
    transaction_id: str
    logical_chunk_id: str
    pool: PolicyPool
    route_version: int
    layout: TPLayoutIdentity
    shards: tuple[TPShardPlacement, ...]
    state: PathCommitState = PathCommitState.PENDING
    terminal_reason: str | None = None
    _acked_ranks: set[int] = field(default_factory=set, init=False, repr=False)
    _ack_ns_by_rank: dict[int, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.transaction_id or not self.logical_chunk_id:
            raise ValueError("transaction_id and logical_chunk_id must be non-empty")
        if type(self.pool) is not PolicyPool:
            raise TypeError("pool must be an exact PolicyPool")
        require_nonnegative_int(self.route_version, "route_version")
        if type(self.layout) is not TPLayoutIdentity:
            raise TypeError("layout must be an exact TPLayoutIdentity")
        if type(self.shards) is not tuple:
            raise TypeError("shards must be an exact tuple")
        ranks = tuple(shard.tp_rank for shard in self.shards)
        expected = tuple(range(self.layout.tensor_parallel_size))
        if ranks != expected:
            raise ValueError("transaction must contain one ordered shard for every TP rank")
        if len({shard.source_gpu_id for shard in self.shards}) != len(self.shards):
            raise ValueError("source TP ranks must use distinct GPUs")
        if len({shard.protection_resource_id for shard in self.shards}) != len(self.shards):
            raise ValueError("protection TP shards must use distinct resources")
        if self.state is not PathCommitState.PENDING or self.terminal_reason is not None:
            raise ValueError("a new transaction must be non-terminal PENDING")

    @property
    def acked_ranks(self) -> tuple[int, ...]:
        return tuple(sorted(self._acked_ranks))

    @property
    def committed_at_ns(self) -> int | None:
        if self.state is not PathCommitState.COMMITTED:
            return None
        return max(self._ack_ns_by_rank.values())

    @property
    def allocated_bytes(self) -> int:
        return sum(shard.allocated_bytes for shard in self.shards)

    def acknowledge_shard(
        self,
        tp_rank: int,
        *,
        timestamp_ns: int,
        route_version: int,
        layout: TPLayoutIdentity,
    ) -> bool:
        """Record one shard ACK and return whether the logical path just committed."""

        self._require_pending()
        require_nonnegative_int(tp_rank, "tp_rank")
        require_nonnegative_int(timestamp_ns, "timestamp_ns")
        if route_version != self.route_version or layout != self.layout:
            self.abort(reason="ROUTE_OR_LAYOUT_MISMATCH")
            return False
        if tp_rank >= self.layout.tensor_parallel_size:
            raise ValueError("ACK TP rank is outside the transaction layout")
        if tp_rank in self._acked_ranks:
            raise ValueError("duplicate TP shard ACK")
        self._acked_ranks.add(tp_rank)
        self._ack_ns_by_rank[tp_rank] = timestamp_ns
        if len(self._acked_ranks) == self.layout.tensor_parallel_size:
            self.state = PathCommitState.COMMITTED
            return True
        return False

    def abort(self, *, reason: str) -> None:
        self._require_pending()
        if type(reason) is not str or not reason:
            raise ValueError("abort reason must be non-empty")
        self.state = PathCommitState.ABORTED
        self.terminal_reason = reason

    def build_recovery_plan(
        self,
        *,
        route_version: int,
        layout: TPLayoutIdentity,
        destination_gpu_ids: tuple[str, ...],
        nvlink_rate_resource_id: str,
        model_all_reduce_bytes_per_rank: int,
    ) -> TPRecoveryPlan:
        if self.state is not PathCommitState.COMMITTED:
            raise ValueError("only a committed all-shard path is recovery eligible")
        if route_version != self.route_version or layout != self.layout:
            raise ValueError("recovery route/layout does not match the committed path")
        if type(destination_gpu_ids) is not tuple:
            raise TypeError("destination_gpu_ids must be an exact tuple")
        if len(destination_gpu_ids) != self.layout.tensor_parallel_size:
            raise ValueError("recovery requires one destination GPU per TP rank")
        if len(set(destination_gpu_ids)) != len(destination_gpu_ids):
            raise ValueError("recovery destination TP GPUs must be unique")
        collectives = [
            TPCollectiveWork(
                kind=TPCollectiveKind.ACTIVATION_BARRIER,
                participant_gpu_ids=destination_gpu_ids,
                payload_bytes_per_rank=0,
                rate_resource_id=nvlink_rate_resource_id,
            )
        ]
        if self.layout.tensor_parallel_size > 1:
            collectives.append(
                TPCollectiveWork(
                    kind=TPCollectiveKind.MODEL_ALL_REDUCE,
                    participant_gpu_ids=destination_gpu_ids,
                    payload_bytes_per_rank=model_all_reduce_bytes_per_rank,
                    rate_resource_id=nvlink_rate_resource_id,
                )
            )
        return TPRecoveryPlan(
            logical_chunk_id=self.logical_chunk_id,
            pool=self.pool,
            route_version=self.route_version,
            rank_sources=tuple(
                (shard.tp_rank, shard.protection_resource_id) for shard in self.shards
            ),
            rank_destinations=tuple(enumerate(destination_gpu_ids)),
            collectives=tuple(collectives),
        )

    def _require_pending(self) -> None:
        if self.state is not PathCommitState.PENDING:
            raise ValueError("TP shard transaction is already terminal")
