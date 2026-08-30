"""KV location and replica states shared by the baseline and AegisKV branch."""

from enum import StrEnum


class KVLocation(StrEnum):
    PRIMARY_HBM = "PRIMARY_HBM"
    PEER_HBM = "PEER_HBM"
    STORE_DRAM = "STORE_DRAM"


class ReplicaState(StrEnum):
    ALLOCATED = "ALLOCATED"
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    LOST = "LOST"
    EVICTED = "EVICTED"
    REMOVED = "REMOVED"

    @property
    def visible(self) -> bool:
        return self is ReplicaState.COMMITTED

    @property
    def terminal(self) -> bool:
        return self in {
            ReplicaState.ABORTED,
            ReplicaState.LOST,
            ReplicaState.EVICTED,
            ReplicaState.REMOVED,
        }
