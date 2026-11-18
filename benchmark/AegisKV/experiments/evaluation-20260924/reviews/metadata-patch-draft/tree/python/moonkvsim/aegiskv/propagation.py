"""Source-owned dual-path propagation on one GlobalDES/TransferRuntime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from moonkvsim.aegiskv.controller import IndependentAdmission
from moonkvsim.aegiskv.kv_directory import ResidencyOutcome
from moonkvsim.aegiskv.peer_hbm_pool import PeerHBMPool, PeerHBMTicket
from moonkvsim.aegiskv.store_dram_pool import StoreDRAMPool, StoreDRAMTicket
from moonkvsim.aegiskv.types import PathCommitState, PolicyPool
from moonkvsim.simulation.allocation import AllocationState
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.store.transfer_engine import (
    MemoryKind,
    TransferOpcode,
    TransferStatus,
    TransferTask,
)
from moonkvsim.store.transfer_runtime import TransferRuntime


class PropagationPathState(StrEnum):
    BYPASSED = "BYPASSED"
    STARTED = "STARTED"
    START_FAILED = "START_FAILED"


@dataclass(frozen=True, slots=True)
class PropagationPathStart:
    pool: PolicyPool
    state: PropagationPathState
    transfer_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DualPropagationStart:
    peer: PropagationPathStart
    store: PropagationPathStart


@dataclass(frozen=True, slots=True)
class _ActivePath:
    pool: PolicyPool
    source_allocation_id: str
    peer_ticket: PeerHBMTicket | None = None
    store_ticket: StoreDRAMTicket | None = None


class DualPathPropagator:
    """Start direct source->peer and source->Store writes independently."""

    def __init__(
        self,
        *,
        runtime: TransferRuntime,
        peer_pool: PeerHBMPool,
        store_pool: StoreDRAMPool,
    ) -> None:
        if peer_pool.directory is not store_pool.directory:
            raise ValueError("propagation pools must share the sole AegisKV directory")
        if runtime.des.journal is not peer_pool.journal:
            raise ValueError("AegisKV propagation and physical pools must share one DES journal")
        self.runtime = runtime
        self.des = runtime.des
        self.peer_pool = peer_pool
        self.store_pool = store_pool
        self.directory = peer_pool.directory
        self.registry = self.directory.allocation_registry
        self._active: dict[str, _ActivePath] = {}

    def start(
        self,
        admission: IndependentAdmission,
        *,
        peer_task: TransferTask | None,
        store_task: TransferTask | None,
    ) -> DualPropagationStart:
        peer = self._start_peer(admission, peer_task)
        store = self._start_store(admission, store_task)
        return DualPropagationStart(peer=peer, store=store)

    def committed_outcome(self, admission: IndependentAdmission) -> ResidencyOutcome:
        return self.directory.residency_outcome(admission.production.identity)

    def audit(self) -> None:
        self.runtime.audit()
        self.peer_pool.audit()
        self.store_pool.audit()
        for transfer_id, binding in self._active.items():
            if transfer_id not in self.runtime.active_transfer_ids:
                raise RuntimeError("active Aegis propagation has no TransferRuntime flow")
            if self.registry.overlay(binding.source_allocation_id).source_pin_count <= 0:
                raise RuntimeError("active Aegis propagation lost its source pin")

    def _start_peer(
        self,
        admission: IndependentAdmission,
        task: TransferTask | None,
    ) -> PropagationPathStart:
        ticket = admission.peer.peer_ticket
        if ticket is None:
            return PropagationPathStart(
                pool=PolicyPool.PEER_HBM,
                state=PropagationPathState.BYPASSED,
                error=admission.peer.error,
            )
        if task is None:
            self.peer_pool.abort(
                ticket,
                timestamp_ns=self.des.now_ns,
                reason="MISSING_PEER_TRANSFER_TASK",
            )
            return PropagationPathStart(
                pool=PolicyPool.PEER_HBM,
                state=PropagationPathState.START_FAILED,
                error="missing Peer-HBM transfer task",
            )
        try:
            self._validate_task(admission, task, pool=PolicyPool.PEER_HBM)
            self._pin_and_start(
                task,
                _ActivePath(
                    pool=PolicyPool.PEER_HBM,
                    source_allocation_id=admission.production.source_allocation_id,
                    peer_ticket=ticket,
                ),
            )
        except (KeyError, RuntimeError, ValueError) as error:
            self._abort_after_start_failure(
                task,
                source_allocation_id=admission.production.source_allocation_id,
                peer_ticket=ticket,
                store_ticket=None,
                reason=f"PEER_START_FAILED:{type(error).__name__}",
            )
            return PropagationPathStart(
                pool=PolicyPool.PEER_HBM,
                state=PropagationPathState.START_FAILED,
                transfer_id=task.metadata.transfer_id,
                error=f"{type(error).__name__}:{error}",
            )
        return PropagationPathStart(
            pool=PolicyPool.PEER_HBM,
            state=PropagationPathState.STARTED,
            transfer_id=task.metadata.transfer_id,
        )

    def _start_store(
        self,
        admission: IndependentAdmission,
        task: TransferTask | None,
    ) -> PropagationPathStart:
        ticket = admission.store.store_ticket
        if ticket is None:
            return PropagationPathStart(
                pool=PolicyPool.STORE_DRAM,
                state=PropagationPathState.BYPASSED,
                error=admission.store.error,
            )
        if task is None:
            self.store_pool.abort(
                ticket,
                timestamp_ns=self.des.now_ns,
                reason="MISSING_STORE_TRANSFER_TASK",
            )
            return PropagationPathStart(
                pool=PolicyPool.STORE_DRAM,
                state=PropagationPathState.START_FAILED,
                error="missing Store DRAM transfer task",
            )
        try:
            self._validate_task(admission, task, pool=PolicyPool.STORE_DRAM)
            self._pin_and_start(
                task,
                _ActivePath(
                    pool=PolicyPool.STORE_DRAM,
                    source_allocation_id=admission.production.source_allocation_id,
                    store_ticket=ticket,
                ),
            )
        except (KeyError, RuntimeError, ValueError) as error:
            self._abort_after_start_failure(
                task,
                source_allocation_id=admission.production.source_allocation_id,
                peer_ticket=None,
                store_ticket=ticket,
                reason=f"STORE_START_FAILED:{type(error).__name__}",
            )
            return PropagationPathStart(
                pool=PolicyPool.STORE_DRAM,
                state=PropagationPathState.START_FAILED,
                transfer_id=task.metadata.transfer_id,
                error=f"{type(error).__name__}:{error}",
            )
        return PropagationPathStart(
            pool=PolicyPool.STORE_DRAM,
            state=PropagationPathState.STARTED,
            transfer_id=task.metadata.transfer_id,
        )

    def _validate_task(
        self,
        admission: IndependentAdmission,
        task: TransferTask,
        *,
        pool: PolicyPool,
    ) -> None:
        production = admission.production
        metadata = task.metadata
        source_allocation = self.registry.get(production.source_allocation_id)
        if source_allocation.state not in {
            AllocationState.RESERVED,
            AllocationState.PENDING,
            AllocationState.COMMITTED,
        }:
            raise ValueError("source production allocation is terminal")
        if (
            metadata.object_id != production.identity.object_id
            or metadata.total_bytes != production.payload_bytes
            or metadata.route_version != production.identity.route_version
            or metadata.opcode is not TransferOpcode.WRITE
            or metadata.source.kind is not MemoryKind.GPU_HBM
            or metadata.source.resource_id != source_allocation.resource_id
            or metadata.source.gpu_id != production.identity.source_gpu_id
        ):
            raise ValueError("transfer does not originate at the sealed production allocation")
        if metadata.transfer_id in self._active:
            raise ValueError("duplicate active Aegis transfer_id")

        if pool is PolicyPool.PEER_HBM:
            peer_ticket = admission.peer.peer_ticket
            if peer_ticket is None:
                raise RuntimeError("Peer-HBM transfer has no pending reservation")
            if (
                metadata.replica_id != peer_ticket.replica_id
                or metadata.destination.kind is not MemoryKind.GPU_HBM
                or metadata.destination.resource_id != peer_ticket.resource_id
                or metadata.destination.gpu_id
                != self.peer_pool.gpu_id_by_resource[peer_ticket.resource_id]
                or metadata.cause != "AEGIS_PEER_HBM_PROPAGATION"
            ):
                raise ValueError("Peer-HBM task does not target its final reservation")
        else:
            store_ticket = admission.store.store_ticket
            if store_ticket is None:
                raise RuntimeError("Store transfer has no pending reservation")
            segment = self.store_pool.master.segments[store_ticket.segment_id]
            if (
                metadata.replica_id != store_ticket.replica_id
                or metadata.destination.kind is not MemoryKind.STORE_DRAM
                or metadata.destination.resource_id != store_ticket.segment_id
                or metadata.destination.node_id != segment.node_id
                or metadata.destination.numa_node_id != segment.numa_node_id
                or metadata.destination.endpoint != segment.transport_endpoint
                or metadata.cause != "AEGIS_STORE_DRAM_PROPAGATION"
            ):
                raise ValueError("Store task does not target its final Master allocation")
    def _pin_and_start(self, task: TransferTask, binding: _ActivePath) -> None:
        transfer_id = task.metadata.transfer_id
        self.registry.pin_source(
            binding.source_allocation_id,
            timestamp_ns=self.des.now_ns,
            event_id=f"{transfer_id}:aegis-source-pin",
        )
        self._active[transfer_id] = binding
        self.runtime.start_task(task, on_terminal=self._terminal_handler)

    def _terminal_handler(self, task: TransferTask, _des: GlobalDES) -> None:
        transfer_id = task.metadata.transfer_id
        try:
            binding = self._active.pop(transfer_id)
        except KeyError as error:
            raise RuntimeError("terminal Aegis transfer has no active path binding") from error
        try:
            if task.status is TransferStatus.COMPLETED:
                if binding.peer_ticket is not None:
                    self.peer_pool.commit(binding.peer_ticket, timestamp_ns=self.des.now_ns)
                elif binding.store_ticket is not None:
                    self.store_pool.commit(binding.store_ticket, timestamp_ns=self.des.now_ns)
                else:
                    raise RuntimeError("Aegis transfer binding has no destination ticket")
            else:
                reason = task.abort_reason or task.status.value
                if binding.peer_ticket is not None:
                    self.peer_pool.abort(
                        binding.peer_ticket,
                        timestamp_ns=self.des.now_ns,
                        reason=reason,
                    )
                elif binding.store_ticket is not None:
                    self.store_pool.abort(
                        binding.store_ticket,
                        timestamp_ns=self.des.now_ns,
                        reason=reason,
                    )
        finally:
            self.registry.unpin_source(
                binding.source_allocation_id,
                timestamp_ns=self.des.now_ns,
                event_id=f"{transfer_id}:aegis-source-unpin",
            )
        self.directory.master.journal.append(
            self.des.now_ns,
            "AEGIS_PROPAGATION_PATH_TERMINAL",
            {
                "transfer_id": transfer_id,
                "pool": binding.pool.value,
                "transfer_state": task.status.value,
                "cause": "AEGIS_SOURCE_OWNED_PROPAGATION_TERMINAL",
            },
        )

    def _abort_after_start_failure(
        self,
        task: TransferTask,
        *,
        source_allocation_id: str,
        peer_ticket: PeerHBMTicket | None,
        store_ticket: StoreDRAMTicket | None,
        reason: str,
    ) -> None:
        transfer_id = task.metadata.transfer_id
        binding = self._active.pop(transfer_id, None)
        if binding is not None:
            self.registry.unpin_source(
                source_allocation_id,
                timestamp_ns=self.des.now_ns,
                event_id=f"{transfer_id}:aegis-source-unpin-start-failed",
            )
        if peer_ticket is not None and peer_ticket.state is PathCommitState.PENDING:
            self.peer_pool.abort(
                peer_ticket,
                timestamp_ns=self.des.now_ns,
                reason=reason,
            )
        if store_ticket is not None and store_ticket.state is PathCommitState.PENDING:
            self.store_pool.abort(
                store_ticket,
                timestamp_ns=self.des.now_ns,
                reason=reason,
            )
