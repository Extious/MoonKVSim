"""Logical replica lifecycle; physical bytes live in allocation ledgers.

Baseline mappings are `ALLOCATED -> Mooncake INITIALIZED`, `PENDING ->
PROCESSING`, and `COMMITTED -> COMPLETE`. Extra terminal distinctions preserve
the plan's failure/eviction audit reason without changing visibility semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from moonkvsim.common.status import KVLocation, ReplicaState


@dataclass(frozen=True, slots=True)
class Replica:
    replica_id: str
    object_id: str
    location: KVLocation
    allocation_ids: tuple[str, ...]
    expected_shard_ids: tuple[str, ...]
    completed_shard_ids: frozenset[str]
    state: ReplicaState
    generation: int
    route_version: int
    created_at_ns: int
    published_at_ns: int | None = None

    def __post_init__(self) -> None:
        if not self.replica_id or not self.object_id:
            raise ValueError("replica_id and object_id must be non-empty")
        if not self.allocation_ids or len(set(self.allocation_ids)) != len(self.allocation_ids):
            raise ValueError("replica requires unique physical allocation ids")
        if not self.expected_shard_ids or len(set(self.expected_shard_ids)) != len(
            self.expected_shard_ids
        ):
            raise ValueError("replica requires unique expected shard ids")
        if not self.completed_shard_ids.issubset(self.expected_shard_ids):
            raise ValueError("completed shards must be expected")
        if self.generation < 0 or self.route_version < 0 or self.created_at_ns < 0:
            raise ValueError("generation, route version, and created time must be non-negative")
        if self.published_at_ns is not None:
            if self.state is not ReplicaState.COMMITTED:
                raise ValueError("only committed replicas may be published")
            if self.published_at_ns < self.created_at_ns:
                raise ValueError("published time cannot precede creation")

    @property
    def visible(self) -> bool:
        return self.state.visible and self.published_at_ns is not None

    def start_pending(self) -> Replica:
        if self.state is not ReplicaState.ALLOCATED:
            raise ValueError("only allocated replicas may become pending")
        return replace(self, state=ReplicaState.PENDING)

    def complete_shard(self, shard_id: str) -> Replica:
        if self.state is not ReplicaState.PENDING:
            raise ValueError("shards may complete only while a replica is pending")
        if shard_id not in self.expected_shard_ids:
            raise ValueError(f"unexpected shard: {shard_id}")
        if shard_id in self.completed_shard_ids:
            raise ValueError(f"shard already completed: {shard_id}")
        return replace(self, completed_shard_ids=self.completed_shard_ids | {shard_id})

    def commit(self) -> Replica:
        if self.state is not ReplicaState.PENDING:
            raise ValueError("only pending replicas may commit")
        if self.completed_shard_ids != frozenset(self.expected_shard_ids):
            raise ValueError("all expected shards must complete before commit")
        return replace(self, state=ReplicaState.COMMITTED)

    def publish(self, *, timestamp_ns: int) -> Replica:
        if self.state is not ReplicaState.COMMITTED:
            raise ValueError("only committed replicas may be published")
        if self.published_at_ns is not None:
            raise ValueError("replica is already published")
        return replace(self, published_at_ns=timestamp_ns)

    def revoke_visibility(self) -> Replica:
        if self.published_at_ns is None:
            return self
        return replace(self, published_at_ns=None)

    def terminate(self, state: ReplicaState) -> Replica:
        if state not in {
            ReplicaState.ABORTED,
            ReplicaState.LOST,
            ReplicaState.EVICTED,
            ReplicaState.REMOVED,
        }:
            raise ValueError(f"not a terminal replica state: {state}")
        allowed = {
            ReplicaState.ALLOCATED: {ReplicaState.ABORTED, ReplicaState.REMOVED},
            ReplicaState.PENDING: {ReplicaState.ABORTED, ReplicaState.LOST},
            ReplicaState.COMMITTED: {
                ReplicaState.LOST,
                ReplicaState.EVICTED,
                ReplicaState.REMOVED,
            },
            ReplicaState.ABORTED: {ReplicaState.REMOVED},
            ReplicaState.LOST: {ReplicaState.REMOVED},
            ReplicaState.EVICTED: {ReplicaState.REMOVED},
            ReplicaState.REMOVED: set(),
        }
        if state not in allowed[self.state]:
            raise ValueError(f"invalid replica transition: {self.state} -> {state}")
        return replace(self, state=state, published_at_ns=None)
