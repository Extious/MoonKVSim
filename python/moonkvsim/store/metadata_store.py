"""The baseline global KV directory and its visibility index."""

from __future__ import annotations

from dataclasses import dataclass, field

from moonkvsim.common.status import KVLocation
from moonkvsim.common.types import KVIdentity
from moonkvsim.store.replica import Replica


@dataclass(slots=True)
class DirectoryObject:
    identity: KVIdentity
    lineage_record_ids: set[str] = field(default_factory=set)
    replicas: dict[str, Replica] = field(default_factory=dict)


class GlobalKVDirectory:
    """A metadata plane only; this class never moves or charges KV bytes."""

    def __init__(self) -> None:
        self._objects: dict[str, DirectoryObject] = {}
        self._replica_to_object: dict[str, str] = {}
        self._allocation_to_replica: dict[str, str] = {}

    def register_object(self, identity: KVIdentity) -> str:
        object_id = identity.object_id
        existing = self._objects.get(object_id)
        if existing is None:
            existing = DirectoryObject(identity=identity)
            self._objects[object_id] = existing
        elif existing.identity.content_fields() != identity.content_fields():
            raise RuntimeError("content hash collision with different KV identity")
        existing.lineage_record_ids.add(identity.lineage_record_id)
        return object_id

    def add_replica(self, replica: Replica) -> None:
        if replica.object_id not in self._objects:
            raise KeyError(f"unknown KV object: {replica.object_id}")
        if replica.replica_id in self._replica_to_object:
            raise ValueError(f"duplicate replica_id: {replica.replica_id}")
        duplicate_allocations = set(replica.allocation_ids).intersection(
            self._allocation_to_replica
        )
        if duplicate_allocations:
            raise ValueError(
                "physical allocations cannot back multiple replicas: "
                f"{sorted(duplicate_allocations)}"
            )
        self._objects[replica.object_id].replicas[replica.replica_id] = replica
        self._replica_to_object[replica.replica_id] = replica.object_id
        for allocation_id in replica.allocation_ids:
            self._allocation_to_replica[allocation_id] = replica.replica_id

    def update_replica(self, replica: Replica) -> None:
        object_id = self._replica_to_object.get(replica.replica_id)
        if object_id is None:
            raise KeyError(f"unknown replica: {replica.replica_id}")
        if object_id != replica.object_id:
            raise ValueError("replica cannot change object ownership")
        previous = self._objects[object_id].replicas[replica.replica_id]
        if previous.allocation_ids != replica.allocation_ids:
            raise ValueError("replica cannot change physical allocation ids")
        self._objects[object_id].replicas[replica.replica_id] = replica

    def get_replica(self, replica_id: str) -> Replica:
        object_id = self._replica_to_object[replica_id]
        return self._objects[object_id].replicas[replica_id]

    def get_replica_for_allocation(self, allocation_id: str) -> Replica:
        """Resolve one physical allocation through the sole replica index."""

        try:
            replica_id = self._allocation_to_replica[allocation_id]
        except KeyError as error:
            raise KeyError(f"unknown replica allocation: {allocation_id}") from error
        return self.get_replica(replica_id)

    def replicas_for_object(self, object_id: str) -> tuple[Replica, ...]:
        entry = self._objects.get(object_id)
        if entry is None:
            return ()
        return tuple(sorted(entry.replicas.values(), key=lambda item: item.replica_id))

    def query(
        self,
        identity: KVIdentity,
        *,
        locations: frozenset[KVLocation] | None = None,
    ) -> tuple[Replica, ...]:
        entry = self._objects.get(identity.object_id)
        if entry is None or entry.identity.compatibility_key != identity.compatibility_key:
            return ()
        return tuple(
            sorted(
                (
                    replica
                    for replica in entry.replicas.values()
                    if replica.visible
                    and (locations is None or replica.location in locations)
                ),
                key=lambda replica: replica.replica_id,
            )
        )

    def query_committed_prefix(
        self, identities: list[KVIdentity]
    ) -> tuple[tuple[KVIdentity, tuple[Replica, ...]], ...]:
        prefix: list[tuple[KVIdentity, tuple[Replica, ...]]] = []
        for identity in identities:
            replicas = self.query(identity)
            if not replicas:
                break
            prefix.append((identity, replicas))
        return tuple(prefix)
