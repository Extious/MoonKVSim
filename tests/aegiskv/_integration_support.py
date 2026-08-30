from __future__ import annotations

from dataclasses import dataclass

from moonkvsim.aegiskv.controller import (
    AdmissionDecision,
    AdmissionPolicy,
    AegisKVController,
    AllocationQuote,
    IndependentAdmission,
    ProductionChunk,
)
from moonkvsim.aegiskv.kv_directory import AegisKVDirectory
from moonkvsim.aegiskv.peer_hbm_pool import PeerHBMPool
from moonkvsim.aegiskv.store_dram_pool import StoreDRAMPool
from moonkvsim.aegiskv.types import AdmissionOutcome, PolicyPool, SealedChunk
from moonkvsim.common.status import KVLocation, ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation import (
    AllocationRole,
    AllocationState,
    PhysicalAllocation,
)
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.flow_des import FlowDESController
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.network import FlowContentionModel
from moonkvsim.simulation.resource import RateResource
from moonkvsim.store.allocation_strategy import RandomAllocationStrategy
from moonkvsim.store.master import MasterService
from moonkvsim.store.replica import Replica
from moonkvsim.store.segment import Segment
from moonkvsim.store.transfer_engine import (
    MemoryKind,
    MemoryLocation,
    TopologyPath,
    TransferMetadata,
    TransferOpcode,
    TransferTask,
    TransportKind,
)
from moonkvsim.store.transfer_runtime import TransferRuntime

SOURCE_RESOURCE_ID = "hbm-source"
PEER_RESOURCE_ID = "hbm-peer"
STORE_SEGMENT_ID = "store-target"
SOURCE_ALLOCATION_ID = "source-primary-allocation"
SOURCE_REPLICA_ID = "source-primary-replica"


class FixedPolicy(AdmissionPolicy):
    def __init__(
        self,
        outcomes: dict[PolicyPool, AdmissionOutcome],
        *,
        victims: dict[PolicyPool, tuple[str, ...]] | None = None,
    ) -> None:
        self.outcomes = outcomes
        self.victims = victims or {}
        self.calls: list[tuple[PolicyPool, SealedChunk, AllocationQuote, int]] = []

    def preview(
        self,
        pool: PolicyPool,
        candidate: SealedChunk,
        allocation_quote: AllocationQuote,
        now_ns: int,
    ) -> AdmissionDecision:
        self.calls.append((pool, candidate, allocation_quote, now_ns))
        return AdmissionDecision(
            outcome=self.outcomes[pool],
            plan_id=f"plan:{pool.value}:{candidate.chunk_id}",
            victim_allocation_ids=self.victims.get(pool, ()),
            reason="fixed-test-policy",
        )


@dataclass(slots=True)
class AegisEnv:
    identity: KVIdentity
    journal: EventJournal
    registry: AllocationRegistry
    master: MasterService
    directory: AegisKVDirectory
    source_ledger: CapacityLedger
    peer_ledger: CapacityLedger
    peer_pool: PeerHBMPool
    store_pool: StoreDRAMPool
    des: GlobalDES
    runtime: TransferRuntime

    @property
    def production(self) -> ProductionChunk:
        return ProductionChunk(
            chunk_id="chunk-0",
            identity=self.identity,
            sequence_index=0,
            payload_bytes=100,
            source_allocation_id=SOURCE_ALLOCATION_ID,
        )

    def controller(self, policy: AdmissionPolicy) -> AegisKVController:
        return AegisKVController(
            directory=self.directory,
            peer_pool=self.peer_pool,
            store_pool=self.store_pool,
            policy=policy,
        )


def identity(*, stable_block_hash: str = "hash-0", request_id: str = "request-0") -> KVIdentity:
    return KVIdentity(
        tenant_id="tenant-0",
        model_id="Qwen/Qwen3-8B",
        model_revision="revision",
        kv_dtype="bf16",
        kv_abi="vllm-v1",
        kv_layout="tp1-pp1",
        tp_size=1,
        pp_size=1,
        block_size_tokens=16,
        stable_block_hash=stable_block_hash,
        token_start=0,
        token_end=16,
        shard_id="tp0",
        request_id=request_id,
        session_id="session-0",
        workflow_id="workflow-0",
        route_version=0,
        source_gpu_id="gpu-source",
    )


def build_env(*, peer_capacity: int = 512, store_capacity: int = 512) -> AegisEnv:
    journal = EventJournal()
    registry = AllocationRegistry(journal=journal)
    master = MasterService(
        allocation_strategy=RandomAllocationStrategy(seed=7),
        allocation_registry=registry,
    )
    master.mount_segment(
        Segment(
            segment_id=STORE_SEGMENT_ID,
            name=STORE_SEGMENT_ID,
            node_id="node-store",
            numa_node_id="numa:node-store:0",
            transport_endpoint="rdma://store-target",
            capacity_bytes=store_capacity,
            allocation_alignment_bytes=64,
        ),
        CapacityLedger(
            resource_id=STORE_SEGMENT_ID,
            resource_kind=CapacityResourceKind.STORE_DRAM,
            capacity_bytes=store_capacity,
        ),
        timestamp_ns=0,
    )
    source_ledger = CapacityLedger(
        resource_id=SOURCE_RESOURCE_ID,
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=512,
        initial_accounts={"ACTIVE_PRIMARY": 256},
    )
    peer_ledger = CapacityLedger(
        resource_id=PEER_RESOURCE_ID,
        resource_kind=CapacityResourceKind.GPU_HBM,
        capacity_bytes=peer_capacity,
    )
    kv = identity()
    object_id = master.directory.register_object(kv)
    registry.add(
        PhysicalAllocation(
            allocation_id=SOURCE_ALLOCATION_ID,
            object_id=object_id,
            replica_id=SOURCE_REPLICA_ID,
            resource_id=SOURCE_RESOURCE_ID,
            owner_account="ACTIVE_PRIMARY",
            payload_bytes=100,
            requested_bytes=100,
            allocated_bytes=256,
            padding_bytes=0,
            allocator_metadata_bytes=0,
            internal_fragmentation_bytes=156,
            alignment_bytes=256,
            state=AllocationState.COMMITTED,
            created_at_ns=0,
            roles=frozenset({AllocationRole.ACTIVE_PRIMARY}),
        ),
        timestamp_ns=0,
        event_id="source-primary-add",
    )
    master.directory.add_replica(
        Replica(
            replica_id=SOURCE_REPLICA_ID,
            object_id=object_id,
            location=KVLocation.PRIMARY_HBM,
            allocation_ids=(SOURCE_ALLOCATION_ID,),
            expected_shard_ids=(kv.shard_id,),
            completed_shard_ids=frozenset({kv.shard_id}),
            state=ReplicaState.COMMITTED,
            generation=0,
            route_version=kv.route_version,
            created_at_ns=0,
            published_at_ns=0,
        )
    )
    directory = AegisKVDirectory(master)
    peer_pool = PeerHBMPool(
        directory=directory,
        ledgers={PEER_RESOURCE_ID: peer_ledger},
        gpu_id_by_resource={PEER_RESOURCE_ID: "gpu-peer"},
        allocation_alignment_bytes=256,
    )
    store_pool = StoreDRAMPool(directory=directory)
    des = GlobalDES(journal=journal)
    flow_model = FlowContentionModel(
        [
            RateResource("source-copy", 1_000_000_000.0),
            RateResource("peer-link", 1_000_000_000.0),
            RateResource("peer-write", 1_000_000_000.0),
            RateResource("store-link", 1_000_000_000.0),
            RateResource("store-write", 1_000_000_000.0),
        ]
    )
    runtime = TransferRuntime(controller=FlowDESController(des=des, model=flow_model))
    return AegisEnv(
        identity=kv,
        journal=journal,
        registry=registry,
        master=master,
        directory=directory,
        source_ledger=source_ledger,
        peer_ledger=peer_ledger,
        peer_pool=peer_pool,
        store_pool=store_pool,
        des=des,
        runtime=runtime,
    )


def reserve(
    env: AegisEnv,
    *,
    operation_id: str,
    peer: AdmissionOutcome,
    store: AdmissionOutcome,
) -> IndependentAdmission:
    policy = FixedPolicy(
        {
            PolicyPool.PEER_HBM: peer,
            PolicyPool.STORE_DRAM: store,
        }
    )
    return env.controller(policy).reserve_independently(
        env.production,
        operation_id=operation_id,
        peer_resource_id=PEER_RESOURCE_ID,
        store_segment_id=STORE_SEGMENT_ID,
        timestamp_ns=env.des.now_ns,
    )


def transfer_task(
    env: AegisEnv,
    admission: IndependentAdmission,
    *,
    pool: PolicyPool,
    transfer_id: str,
    source: MemoryLocation | None = None,
) -> TransferTask:
    source_location = source or MemoryLocation(
        resource_id=SOURCE_RESOURCE_ID,
        node_id="node-source",
        numa_node_id="numa:node-source:0",
        kind=MemoryKind.GPU_HBM,
        endpoint="rdma://hbm-source",
        gpu_id="gpu-source",
    )
    if pool is PolicyPool.PEER_HBM:
        ticket = admission.peer.peer_ticket
        if ticket is None:
            raise ValueError("test admission has no peer ticket")
        destination = MemoryLocation(
            resource_id=PEER_RESOURCE_ID,
            node_id="node-peer",
            numa_node_id="numa:node-peer:0",
            kind=MemoryKind.GPU_HBM,
            endpoint="rdma://hbm-peer",
            gpu_id="gpu-peer",
        )
        path_resources = ("source-copy", "peer-link", "peer-write")
        cause = "AEGIS_PEER_HBM_PROPAGATION"
        replica_id = ticket.replica_id
    else:
        ticket_store = admission.store.store_ticket
        if ticket_store is None:
            raise ValueError("test admission has no Store ticket")
        destination = MemoryLocation(
            resource_id=STORE_SEGMENT_ID,
            node_id="node-store",
            numa_node_id="numa:node-store:0",
            kind=MemoryKind.STORE_DRAM,
            endpoint="rdma://store-target",
        )
        path_resources = ("source-copy", "store-link", "store-write")
        cause = "AEGIS_STORE_DRAM_PROPAGATION"
        replica_id = ticket_store.replica_id
    path = TopologyPath(
        path_id=f"path:{transfer_id}",
        source_kind=MemoryKind.GPU_HBM,
        destination_kind=destination.kind,
        transport=TransportKind.RDMA_GDR,
        rate_resource_ids=path_resources,
        concurrency_resource_ids=(f"copy:{transfer_id}",),
        source_endpoint=source_location.endpoint,
        destination_endpoint=destination.endpoint,
        source_node_id=source_location.node_id,
        destination_node_id=destination.node_id,
        source_numa_node_id=source_location.numa_node_id,
        destination_numa_node_id=destination.numa_node_id,
        source_hca_id="source-hca",
        destination_hca_id=f"{destination.node_id}-hca",
    )
    return TransferTask.create(
        TransferMetadata(
            transfer_id=transfer_id,
            object_id=env.identity.object_id,
            replica_id=replica_id,
            source=source_location,
            destination=destination,
            opcode=TransferOpcode.WRITE,
            total_bytes=env.production.payload_bytes,
            cause=cause,
            route_version=env.identity.route_version,
            ready_ns=env.des.now_ns,
            path=path,
        ),
        slice_size_bytes=64,
    )
