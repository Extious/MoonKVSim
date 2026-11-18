"""Tensor-free Mooncake-style StoreClient lifecycle orchestration.

The client coordinates Master metadata with source-aligned transfer objects.
It never advances time, computes bandwidth, posts a slice implicitly, or marks
bytes successful without an explicit data-plane callback.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from moonkvsim.common.status import ReplicaState
from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.allocation import AllocationState
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.store.master import MasterService, PutTicket
from moonkvsim.store.replica import Replica
from moonkvsim.store.transfer_engine import (
    DEFAULT_SLICE_SIZE_BYTES,
    BatchTransfer,
    MemoryKind,
    MemoryLocation,
    Slice,
    SliceStatus,
    Topology,
    TopologyPath,
    TransferMetadata,
    TransferOpcode,
    TransferStatus,
    TransferTask,
)


class StoreClientError(RuntimeError):
    """Raised when a client operation violates metadata/data-plane ordering."""


class PutOperationState(StrEnum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


class GetOperationState(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(slots=True)
class PutOperation:
    put_id: str
    identity: KVIdentity
    ticket: PutTicket
    batch: BatchTransfer
    payload_bytes: int
    cause: str
    state: PutOperationState = PutOperationState.PENDING
    committed_replicas: tuple[Replica, ...] = ()
    abort_reason: str | None = None


@dataclass(slots=True)
class GetOperation:
    get_id: str
    identity: KVIdentity
    replica: Replica
    batch: BatchTransfer
    payload_bytes: int
    cause: str
    source_allocation_ids: tuple[str, ...]
    destination_allocation_ids: tuple[str, ...] = ()
    state: GetOperationState = GetOperationState.PENDING
    failure_reason: str | None = None
    source_pins_released: bool = False


class StoreClient:
    """Control-plane client that binds Master allocations to TransferTasks."""

    def __init__(
        self,
        *,
        client_id: str,
        master: MasterService,
        topology: Topology,
        local_gpu: MemoryLocation,
        registered_at_ns: int,
        slice_size_bytes: int = DEFAULT_SLICE_SIZE_BYTES,
    ) -> None:
        if not client_id:
            raise ValueError("client_id must be non-empty")
        if local_gpu.kind is not MemoryKind.GPU_HBM:
            raise ValueError("StoreClient local_gpu must be GPU_HBM")
        if registered_at_ns < 0 or slice_size_bytes <= 0:
            raise ValueError("registered time and slice size must be valid")
        self.client_id = client_id
        self.master = master
        self.topology = topology
        self.local_gpu = local_gpu
        self.slice_size_bytes = slice_size_bytes
        self.journal: EventJournal = master.journal
        self._puts: dict[str, PutOperation] = {}
        self._gets: dict[str, GetOperation] = {}
        self._batches: dict[str, BatchTransfer] = {}
        self._tasks: dict[str, TransferTask] = {}
        self._transfer_owner: dict[str, tuple[str, str]] = {}
        self.master.register_client(client_id, timestamp_ns=registered_at_ns)

    def put_start(
        self,
        identity: KVIdentity,
        *,
        put_id: str,
        payload_bytes: int,
        replica_count: int,
        ready_ns: int,
        cause: str = "BASELINE_STORE_PUT",
        preferred_segment_ids: tuple[str, ...] = (),
        excluded_segment_ids: tuple[str, ...] = (),
    ) -> PutOperation:
        """Allocate PENDING replicas, then create one write task per allocation."""

        if put_id in self._puts:
            raise ValueError(f"duplicate client put_id: {put_id}")
        if self.local_gpu.gpu_id != identity.source_gpu_id:
            raise ValueError("put source identity does not match this client's local GPU")
        ticket = self.master.put_start(
            identity,
            put_id=put_id,
            payload_bytes=payload_bytes,
            replica_count=replica_count,
            timestamp_ns=ready_ns,
            preferred_segment_ids=preferred_segment_ids,
            excluded_segment_ids=excluded_segment_ids,
        )
        batch = BatchTransfer(batch_id=f"put:{put_id}")
        try:
            for replica_id, allocation_id in zip(
                ticket.replica_ids, ticket.allocation_ids, strict=True
            ):
                allocation = self.master.allocation_registry.get(allocation_id)
                if allocation.payload_bytes != payload_bytes:
                    raise StoreClientError("Master allocation payload differs from PutStart")
                destination = self._store_location(allocation.resource_id)
                path = self._select_path(self.local_gpu, destination)
                task = TransferTask.create(
                    TransferMetadata(
                        transfer_id=f"{put_id}:write:{replica_id}",
                        object_id=ticket.object_id,
                        replica_id=replica_id,
                        source=self.local_gpu,
                        destination=destination,
                        opcode=TransferOpcode.WRITE,
                        total_bytes=payload_bytes,
                        cause=cause,
                        route_version=identity.route_version,
                        ready_ns=ready_ns,
                        path=path,
                    ),
                    slice_size_bytes=self.slice_size_bytes,
                )
                task.audit()
                batch.add_task(task)
        except Exception as error:
            try:
                self.master.abort_put(
                    ticket.put_id,
                    timestamp_ns=ready_ns,
                    reason="CLIENT_TASK_BUILD_FAILED",
                )
            except Exception as rollback_error:
                raise StoreClientError(
                    f"PutStart task construction failed and rollback failed: {rollback_error}"
                ) from error
            raise
        if not batch.tasks:
            # Master currently guarantees at least one best-effort placement.
            self.master.abort_put(
                ticket.put_id,
                timestamp_ns=ready_ns,
                reason="CLIENT_EMPTY_BATCH",
            )
            raise StoreClientError("PutStart produced no transfer tasks")
        operation = PutOperation(
            put_id=put_id,
            identity=identity,
            ticket=ticket,
            batch=batch,
            payload_bytes=payload_bytes,
            cause=cause,
        )
        self._puts[put_id] = operation
        self._register_batch(batch, owner_kind="put", owner_id=put_id)
        self.journal.append(
            ready_ns,
            "STORE_CLIENT_PUT_STARTED",
            {
                "client_id": self.client_id,
                "put_id": put_id,
                "object_id": ticket.object_id,
                "replica_ids": list(ticket.replica_ids),
                "transfer_ids": [task.metadata.transfer_id for task in batch.tasks],
                "payload_bytes_per_replica": payload_bytes,
                "required_transfer_bytes": payload_bytes * len(batch.tasks),
                "cause": cause,
                "route_version": identity.route_version,
                "evidence_boundary": "toy_E1_E2_store_lifecycle_not_bandwidth_measurement",
            },
        )
        return operation

    def get_replica_list(self, identity: KVIdentity) -> tuple[Replica, ...]:
        replicas = self.master.get_replica_list(identity)
        if any(
            replica.state is not ReplicaState.COMMITTED or replica.published_at_ns is None
            for replica in replicas
        ):
            raise StoreClientError("Master returned a non-committed or unpublished replica")
        return replicas

    def get_start(
        self,
        identity: KVIdentity,
        *,
        get_id: str,
        ready_ns: int,
        cause: str = "BASELINE_STORE_GET",
        required_replica_id: str | None = None,
        required_allocation_ids: tuple[str, ...] | None = None,
        required_source_resource_id: str | None = None,
        required_destination_allocation_ids: tuple[str, ...] | None = None,
    ) -> GetOperation:
        """Select a visible committed replica and create one Store-to-GPU read task."""

        if not get_id or get_id in self._gets:
            raise ValueError("get_id must be non-empty and unique per client")
        if required_replica_id is not None and not required_replica_id:
            raise ValueError("required_replica_id must be absent or non-empty")
        if required_allocation_ids is not None and (
            not required_allocation_ids
            or len(set(required_allocation_ids)) != len(required_allocation_ids)
        ):
            raise ValueError("required_allocation_ids must be absent or non-empty and unique")
        if required_source_resource_id is not None and not required_source_resource_id:
            raise ValueError("required_source_resource_id must be absent or non-empty")
        if required_destination_allocation_ids is not None and (
            not required_destination_allocation_ids
            or len(set(required_destination_allocation_ids))
            != len(required_destination_allocation_ids)
        ):
            raise ValueError(
                "required_destination_allocation_ids must be absent or non-empty and unique"
            )
        if (required_allocation_ids is not None or required_source_resource_id is not None) and (
            required_replica_id is None
        ):
            raise ValueError("strict allocation/source binding requires required_replica_id")
        if required_destination_allocation_ids is not None:
            for allocation_id in required_destination_allocation_ids:
                try:
                    destination_allocation = self.master.allocation_registry.get(allocation_id)
                except KeyError as error:
                    raise StoreClientError("REQUIRED_DESTINATION_ALLOCATION_UNAVAILABLE") from error
                if (
                    destination_allocation.state is not AllocationState.RESERVED
                    or destination_allocation.resource_id != self.local_gpu.resource_id
                ):
                    raise StoreClientError(
                        "REQUIRED_DESTINATION_ALLOCATION_NOT_RESERVED_ON_LOCAL_GPU"
                    )
        replicas = self.get_replica_list(identity)
        if not replicas:
            raise StoreClientError("NO_COMMITTED_REPLICA")
        if required_replica_id is not None:
            replicas = tuple(
                replica for replica in replicas if replica.replica_id == required_replica_id
            )
            if len(replicas) != 1:
                raise StoreClientError("REQUIRED_COMMITTED_REPLICA_UNAVAILABLE")
            [required_replica] = replicas
            if (
                required_allocation_ids is not None
                and required_replica.allocation_ids != required_allocation_ids
            ):
                raise StoreClientError("REQUIRED_REPLICA_ALLOCATION_MISMATCH")

        candidates: list[tuple[int, str, str, Replica, MemoryLocation, TopologyPath, int]] = []
        for replica in replicas:
            if len(replica.allocation_ids) != 1:
                raise StoreClientError("baseline Store replica must have one allocation")
            allocation = self.master.allocation_registry.get(replica.allocation_ids[0])
            if allocation.state is not AllocationState.COMMITTED:
                raise StoreClientError("visible Store replica does not have a committed allocation")
            if (
                required_source_resource_id is not None
                and allocation.resource_id != required_source_resource_id
            ):
                raise StoreClientError("REQUIRED_REPLICA_SOURCE_RESOURCE_MISMATCH")
            source = self._store_location(allocation.resource_id)
            try:
                path = self._select_path(source, self.local_gpu)
            except ValueError:
                continue
            candidates.append(
                (
                    path.priority,
                    path.path_id,
                    replica.replica_id,
                    replica,
                    source,
                    path,
                    allocation.payload_bytes,
                )
            )
        if not candidates:
            if required_replica_id is not None:
                raise StoreClientError("REQUIRED_COMMITTED_REPLICA_UNREACHABLE")
            raise StoreClientError("NO_REACHABLE_COMMITTED_REPLICA")
        _, _, _, replica, source, path, payload_bytes = min(candidates, key=lambda item: item[:3])
        task = TransferTask.create(
            TransferMetadata(
                transfer_id=f"{get_id}:read:{replica.replica_id}",
                object_id=replica.object_id,
                replica_id=replica.replica_id,
                source=source,
                destination=self.local_gpu,
                opcode=TransferOpcode.READ,
                total_bytes=payload_bytes,
                cause=cause,
                route_version=identity.route_version,
                ready_ns=ready_ns,
                path=path,
                destination_allocation_ids=(
                    ()
                    if required_destination_allocation_ids is None
                    else required_destination_allocation_ids
                ),
            ),
            slice_size_bytes=self.slice_size_bytes,
        )
        task.audit()
        batch = BatchTransfer(batch_id=f"get:{self.client_id}:{get_id}")
        batch.add_task(task)
        operation = GetOperation(
            get_id=get_id,
            identity=identity,
            replica=replica,
            batch=batch,
            payload_bytes=payload_bytes,
            cause=cause,
            source_allocation_ids=replica.allocation_ids,
            destination_allocation_ids=(
                ()
                if required_destination_allocation_ids is None
                else required_destination_allocation_ids
            ),
        )
        pinned: list[str] = []
        try:
            for allocation_id in operation.source_allocation_ids:
                self.master.allocation_registry.pin_source(
                    allocation_id,
                    timestamp_ns=ready_ns,
                    event_id=f"{get_id}:store-get-source-pin:{allocation_id}",
                )
                pinned.append(allocation_id)
            self.master.record_committed_access(identity, timestamp_ns=ready_ns)
            self._gets[get_id] = operation
            self._register_batch(batch, owner_kind="get", owner_id=get_id)
            self.journal.append(
                ready_ns,
                "STORE_CLIENT_GET_STARTED",
                {
                    "client_id": self.client_id,
                    "get_id": get_id,
                    "object_id": replica.object_id,
                    "replica_id": replica.replica_id,
                    "transfer_id": task.metadata.transfer_id,
                    "payload_bytes": payload_bytes,
                    "cause": cause,
                    "route_version": identity.route_version,
                    "path_id": path.path_id,
                    "source_allocation_ids": list(operation.source_allocation_ids),
                    "source_pins_held_until_terminal": True,
                    "required_replica_id": required_replica_id,
                    "required_allocation_ids": (
                        None if required_allocation_ids is None else list(required_allocation_ids)
                    ),
                    "required_source_resource_id": required_source_resource_id,
                    "required_destination_allocation_ids": (
                        None
                        if required_destination_allocation_ids is None
                        else list(required_destination_allocation_ids)
                    ),
                    "evidence_boundary": "toy_E1_E2_store_lifecycle_not_bandwidth_measurement",
                },
            )
        except Exception:
            self._discard_registered_get(operation)
            for allocation_id in reversed(pinned):
                self.master.allocation_registry.unpin_source(
                    allocation_id,
                    timestamp_ns=ready_ns,
                    event_id=f"{get_id}:store-get-source-pin-rollback:{allocation_id}",
                )
            raise
        return operation

    def start_batch(self, batch_id: str, *, timestamp_ns: int) -> None:
        """Mark tasks ready for an external data-plane scheduler; move no bytes."""

        batch = self._batch(batch_id)
        if any(task.status is not TransferStatus.WAITING for task in batch.tasks):
            raise StoreClientError("batch may start only while every task is WAITING")
        if any(timestamp_ns < task.metadata.ready_ns for task in batch.tasks):
            raise StoreClientError("batch cannot start before every task ready_ns")
        for task in batch.tasks:
            task.start(timestamp_ns=timestamp_ns)
        self.journal.append(
            timestamp_ns,
            "STORE_CLIENT_BATCH_STARTED",
            {
                "client_id": self.client_id,
                "batch_id": batch_id,
                "transfer_ids": [task.metadata.transfer_id for task in batch.tasks],
            },
        )

    def post_slice(self, transfer_id: str, slice_id: str, *, timestamp_ns: int) -> Slice:
        task = self._task(transfer_id)
        if task.status is not TransferStatus.PENDING or task.start_ns is None:
            raise StoreClientError("slice may post only after its task starts")
        if timestamp_ns < task.start_ns:
            raise StoreClientError("slice post cannot precede task start")
        current = self._slice(task, slice_id)
        updated = current.post(timestamp_ns=timestamp_ns)
        task.update_slice(updated)
        self.journal.append(
            timestamp_ns,
            "STORE_CLIENT_SLICE_POSTED",
            {
                "client_id": self.client_id,
                "transfer_id": transfer_id,
                "slice_id": slice_id,
                "offset_bytes": updated.offset_bytes,
                "length_bytes": updated.length_bytes,
            },
        )
        return updated

    def finish_slice(
        self,
        transfer_id: str,
        slice_id: str,
        status: SliceStatus,
        *,
        timestamp_ns: int,
        abort_reason: str | None = None,
    ) -> Slice:
        """Apply an explicit data-plane result and reconcile its owning operation."""

        if not status.terminal:
            raise ValueError("finish_slice requires a terminal SliceStatus")
        task = self._task(transfer_id)
        current = self._slice(task, slice_id)
        updated = current.finish(
            status,
            timestamp_ns=timestamp_ns,
            abort_reason=abort_reason,
        )
        task.update_slice(updated)
        task.audit()
        self.journal.append(
            timestamp_ns,
            "STORE_CLIENT_SLICE_TERMINAL",
            {
                "client_id": self.client_id,
                "transfer_id": transfer_id,
                "slice_id": slice_id,
                "status": status.value,
                "length_bytes": updated.length_bytes,
                "abort_reason": abort_reason,
            },
        )
        owner_kind, owner_id = self._transfer_owner[transfer_id]
        if status is not SliceStatus.SUCCESS:
            reason = abort_reason or status.value
            if owner_kind == "put":
                self.abort_put(owner_id, timestamp_ns=timestamp_ns, reason=reason)
            else:
                self._fail_get(owner_id, timestamp_ns=timestamp_ns, reason=reason)
        else:
            batch = (
                self._puts[owner_id].batch if owner_kind == "put" else self._gets[owner_id].batch
            )
            if batch.status is TransferStatus.COMPLETED:
                if owner_kind == "put":
                    self.put_end(owner_id, timestamp_ns=timestamp_ns)
                else:
                    self.get_end(owner_id, timestamp_ns=timestamp_ns)
        return updated

    def reconcile_transfer_terminal(
        self,
        transfer_id: str,
        *,
        timestamp_ns: int,
    ) -> None:
        """Reconcile a task completed by an external data-plane runtime.

        ``TransferRuntime`` and a real Transfer Engine own task/slice state.
        ``StoreClient`` owns the surrounding Put/Get control-plane operation.
        This boundary observes the shared terminal task without replaying any
        lifecycle transition, then commits or aborts the owning operation once.
        """

        task = self._task(transfer_id)
        if not task.status.terminal:
            raise StoreClientError("only a terminal transfer can be reconciled")
        task.audit()
        owner_kind, owner_id = self._transfer_owner[transfer_id]
        batch = self._puts[owner_id].batch if owner_kind == "put" else self._gets[owner_id].batch
        if task.status is not TransferStatus.COMPLETED and any(
            sibling is not task and not sibling.status.terminal for sibling in batch.tasks
        ):
            raise StoreClientError(
                "failed transfer reconciliation requires every sibling runtime task to be terminal"
            )
        if owner_kind == "put":
            put_operation = self._put(owner_id)
            if put_operation.state is not PutOperationState.PENDING:
                raise StoreClientError("put transfer was already reconciled")
            if task.status is TransferStatus.COMPLETED:
                if put_operation.batch.status is TransferStatus.COMPLETED:
                    self.put_end(owner_id, timestamp_ns=timestamp_ns)
            else:
                self.abort_put(
                    owner_id,
                    timestamp_ns=timestamp_ns,
                    reason=task.abort_reason or task.status.value,
                )
        else:
            get_operation = self._get(owner_id)
            if get_operation.state is not GetOperationState.PENDING:
                raise StoreClientError("get transfer was already reconciled")
            if task.status is TransferStatus.COMPLETED:
                if get_operation.batch.status is TransferStatus.COMPLETED:
                    self.get_end(owner_id, timestamp_ns=timestamp_ns)
            else:
                self._fail_get(
                    owner_id,
                    timestamp_ns=timestamp_ns,
                    reason=task.abort_reason or task.status.value,
                )
        self.journal.append(
            timestamp_ns,
            "STORE_CLIENT_TRANSFER_RECONCILED",
            {
                "client_id": self.client_id,
                "transfer_id": transfer_id,
                "transfer_status": task.status.value,
                "owner_kind": owner_kind,
                "owner_id": owner_id,
            },
        )

    def put_end(self, put_id: str, *, timestamp_ns: int) -> tuple[Replica, ...]:
        operation = self._put(put_id)
        if operation.state is PutOperationState.COMMITTED:
            return operation.committed_replicas
        if operation.state is PutOperationState.ABORTED:
            raise StoreClientError("aborted put cannot end")
        self._audit_successful_batch(operation.batch, operation.payload_bytes)
        committed = self.master.put_end(
            operation.ticket.put_id,
            successful_replica_ids=operation.ticket.replica_ids,
            timestamp_ns=timestamp_ns,
        )
        if len(committed) != len(operation.ticket.replica_ids):
            raise StoreClientError("PutEnd did not publish every required replica")
        operation.state = PutOperationState.COMMITTED
        operation.committed_replicas = committed
        self.journal.append(
            timestamp_ns,
            "STORE_CLIENT_PUT_COMMITTED",
            {
                "client_id": self.client_id,
                "put_id": put_id,
                "replica_ids": [replica.replica_id for replica in committed],
                "transferred_bytes": operation.batch.transferred_bytes,
            },
        )
        return committed

    def abort_put(self, put_id: str, *, timestamp_ns: int, reason: str) -> None:
        operation = self._put(put_id)
        if operation.state is not PutOperationState.PENDING:
            raise StoreClientError("only a pending put may abort")
        self._cancel_nonterminal_tasks(operation.batch, timestamp_ns=timestamp_ns, reason=reason)
        self.master.abort_put(put_id, timestamp_ns=timestamp_ns, reason=reason)
        operation.state = PutOperationState.ABORTED
        operation.abort_reason = reason
        self.journal.append(
            timestamp_ns,
            "STORE_CLIENT_PUT_ABORTED",
            {
                "client_id": self.client_id,
                "put_id": put_id,
                "reason": reason,
                "successful_bytes_before_abort": operation.batch.transferred_bytes,
            },
        )

    def get_end(self, get_id: str, *, timestamp_ns: int) -> GetOperation:
        operation = self._get(get_id)
        if operation.state is GetOperationState.COMPLETED:
            return operation
        if operation.state is GetOperationState.FAILED:
            raise StoreClientError("failed get cannot end")
        self._audit_successful_batch(operation.batch, operation.payload_bytes)
        self._release_get_source_pins(operation, timestamp_ns=timestamp_ns)
        operation.state = GetOperationState.COMPLETED
        self.journal.append(
            timestamp_ns,
            "STORE_CLIENT_GET_COMPLETED",
            {
                "client_id": self.client_id,
                "get_id": get_id,
                "replica_id": operation.replica.replica_id,
                "transferred_bytes": operation.batch.transferred_bytes,
            },
        )
        return operation

    def remove(
        self,
        identity: KVIdentity,
        *,
        timestamp_ns: int,
        cause: str = "BASELINE_STORE_REMOVE",
    ) -> int:
        if not cause:
            raise ValueError("remove cause must be non-empty")
        removed = self.master.remove(identity, timestamp_ns=timestamp_ns)
        self.journal.append(
            timestamp_ns,
            "STORE_CLIENT_REMOVE_COMPLETED",
            {
                "client_id": self.client_id,
                "object_id": identity.object_id,
                "removed_replica_count": removed,
                "cause": cause,
                "route_version": identity.route_version,
            },
        )
        return removed

    def _select_path(self, source: MemoryLocation, destination: MemoryLocation) -> TopologyPath:
        return self.topology.select_path(source, destination, retry_count=0)

    def _store_location(self, segment_id: str) -> MemoryLocation:
        try:
            segment = self.master.segments[segment_id]
        except KeyError as error:
            raise StoreClientError(
                f"Master allocation uses unknown segment {segment_id!r}"
            ) from error
        return MemoryLocation(
            resource_id=segment.segment_id,
            node_id=segment.node_id,
            numa_node_id=segment.numa_node_id,
            kind=MemoryKind.STORE_DRAM,
            endpoint=segment.transport_endpoint,
        )

    def _register_batch(self, batch: BatchTransfer, *, owner_kind: str, owner_id: str) -> None:
        if batch.batch_id in self._batches:
            raise StoreClientError(f"duplicate batch ID {batch.batch_id!r}")
        self._batches[batch.batch_id] = batch
        for task in batch.tasks:
            transfer_id = task.metadata.transfer_id
            if transfer_id in self._tasks:
                raise StoreClientError(f"duplicate transfer ID {transfer_id!r}")
            self._tasks[transfer_id] = task
            self._transfer_owner[transfer_id] = (owner_kind, owner_id)

    def _audit_successful_batch(self, batch: BatchTransfer, payload_bytes: int) -> None:
        if batch.status is not TransferStatus.COMPLETED:
            raise StoreClientError("operation cannot publish before every transfer completes")
        for task in batch.tasks:
            task.audit()
            if task.metadata.total_bytes != payload_bytes:
                raise StoreClientError("task payload differs from operation payload")
            if any(item.status is not SliceStatus.SUCCESS for item in task.slices):
                raise StoreClientError("operation requires every slice to succeed")
        expected_bytes = payload_bytes * len(batch.tasks)
        if batch.transferred_bytes != expected_bytes:
            raise StoreClientError("batch transferred bytes do not conserve payload replicas")

    def _cancel_nonterminal_tasks(
        self, batch: BatchTransfer, *, timestamp_ns: int, reason: str
    ) -> None:
        for task in batch.tasks:
            if not task.status.terminal:
                task.cancel_remaining(timestamp_ns=timestamp_ns, reason=reason)
            task.audit()

    def _fail_get(self, get_id: str, *, timestamp_ns: int, reason: str) -> None:
        operation = self._get(get_id)
        if operation.state is not GetOperationState.PENDING:
            raise StoreClientError("only a pending get may fail")
        self._cancel_nonterminal_tasks(operation.batch, timestamp_ns=timestamp_ns, reason=reason)
        self._release_get_source_pins(operation, timestamp_ns=timestamp_ns)
        operation.state = GetOperationState.FAILED
        operation.failure_reason = reason
        self.journal.append(
            timestamp_ns,
            "STORE_CLIENT_GET_FAILED",
            {
                "client_id": self.client_id,
                "get_id": get_id,
                "reason": reason,
                "successful_bytes_before_failure": operation.batch.transferred_bytes,
            },
        )

    def _release_get_source_pins(
        self,
        operation: GetOperation,
        *,
        timestamp_ns: int,
    ) -> None:
        if operation.source_pins_released:
            raise StoreClientError("Store GET source pins were already released")
        for allocation_id in operation.source_allocation_ids:
            self.master.allocation_registry.unpin_source(
                allocation_id,
                timestamp_ns=timestamp_ns,
                event_id=f"{operation.get_id}:store-get-source-unpin:{allocation_id}",
            )
        operation.source_pins_released = True

    def _discard_registered_get(self, operation: GetOperation) -> None:
        self._gets.pop(operation.get_id, None)
        self._batches.pop(operation.batch.batch_id, None)
        for task in operation.batch.tasks:
            self._tasks.pop(task.metadata.transfer_id, None)
            self._transfer_owner.pop(task.metadata.transfer_id, None)

    def _batch(self, batch_id: str) -> BatchTransfer:
        try:
            return self._batches[batch_id]
        except KeyError as error:
            raise StoreClientError(f"unknown batch ID {batch_id!r}") from error

    def _task(self, transfer_id: str) -> TransferTask:
        try:
            return self._tasks[transfer_id]
        except KeyError as error:
            raise StoreClientError(f"unknown transfer ID {transfer_id!r}") from error

    @staticmethod
    def _slice(task: TransferTask, slice_id: str) -> Slice:
        for item in task.slices:
            if item.slice_id == slice_id:
                return item
        raise StoreClientError(f"unknown slice ID {slice_id!r}")

    def _put(self, put_id: str) -> PutOperation:
        try:
            return self._puts[put_id]
        except KeyError as error:
            raise StoreClientError(f"unknown put ID {put_id!r}") from error

    def _get(self, get_id: str) -> GetOperation:
        try:
            return self._gets[get_id]
        except KeyError as error:
            raise StoreClientError(f"unknown get ID {get_id!r}") from error
