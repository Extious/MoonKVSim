"""Mooncake-named transfer objects on the simulator resource graph.

This module models BatchTransfer/TransferTask/Slice lifecycle and topology
selection.  It deliberately contains no wall clock or aggregate-delay shortcut;
the DES flow controller consumes each slice and its explicit resource path.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

DEFAULT_SLICE_SIZE_BYTES = 65_536


class MemoryKind(StrEnum):
    GPU_HBM = "GPU_HBM"
    HOST_DRAM = "HOST_DRAM"
    STORE_DRAM = "STORE_DRAM"


class TransferOpcode(StrEnum):
    READ = "READ"
    WRITE = "WRITE"


class TransportKind(StrEnum):
    LOCAL_COPY = "LOCAL_COPY"
    NVLINK = "NVLINK"
    RDMA_GDR = "RDMA_GDR"
    RDMA_HOST_STAGED = "RDMA_HOST_STAGED"
    TCP_HOST_STAGED = "TCP_HOST_STAGED"


class PathPreference(StrEnum):
    """Pinned-Topology candidate class, ordered before explicit priority.

    Mooncake's ``Topology`` selects from ``preferred_hca`` at retry zero when
    that set is non-empty, and falls back to ``avail_hca`` only when it is
    empty.  MoonKVSim keeps that class boundary while replacing the upstream
    random/round-robin choice inside a class with a stable explicit order.
    """

    PREFERRED = "PREFERRED"
    AVAILABLE = "AVAILABLE"


class TransferStatus(StrEnum):
    WAITING = "WAITING"
    PENDING = "PENDING"
    CANCELED = "CANCELED"
    COMPLETED = "COMPLETED"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"

    @property
    def terminal(self) -> bool:
        return self in {
            TransferStatus.CANCELED,
            TransferStatus.COMPLETED,
            TransferStatus.TIMEOUT,
            TransferStatus.FAILED,
        }


class SliceStatus(StrEnum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"
    CANCELED = "CANCELED"

    @property
    def terminal(self) -> bool:
        return self in {
            SliceStatus.SUCCESS,
            SliceStatus.TIMEOUT,
            SliceStatus.FAILED,
            SliceStatus.CANCELED,
        }


@dataclass(frozen=True, slots=True)
class MemoryLocation:
    resource_id: str
    node_id: str
    numa_node_id: str
    kind: MemoryKind
    endpoint: str
    gpu_id: str | None = None

    def __post_init__(self) -> None:
        if not self.resource_id or not self.node_id or not self.numa_node_id or not self.endpoint:
            raise ValueError("memory location identifiers must be non-empty")
        if (self.kind is MemoryKind.GPU_HBM) != (self.gpu_id is not None):
            raise ValueError("only GPU HBM locations require a gpu_id")


@dataclass(frozen=True, slots=True)
class TopologyPath:
    path_id: str
    source_kind: MemoryKind
    destination_kind: MemoryKind
    transport: TransportKind
    rate_resource_ids: tuple[str, ...]
    concurrency_resource_ids: tuple[str, ...]
    source_endpoint: str
    destination_endpoint: str
    source_node_id: str
    destination_node_id: str
    source_numa_node_id: str
    destination_numa_node_id: str
    source_hca_id: str | None
    destination_hca_id: str | None
    preference: PathPreference = PathPreference.PREFERRED
    source_host_staging_resource_id: str | None = None
    destination_host_staging_resource_id: str | None = None
    priority: int = 0

    def __post_init__(self) -> None:
        identifiers = (
            self.path_id,
            self.source_endpoint,
            self.destination_endpoint,
            self.source_node_id,
            self.destination_node_id,
            self.source_numa_node_id,
            self.destination_numa_node_id,
        )
        if any(not value for value in identifiers) or not self.rate_resource_ids:
            raise ValueError("path, endpoint, node, NUMA, and rate IDs must be non-empty")
        if not isinstance(self.preference, PathPreference):
            raise TypeError("path preference must be a PathPreference")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("path priority must be a non-negative integer")
        if len(set(self.rate_resource_ids)) != len(self.rate_resource_ids):
            raise ValueError("rate resources on a path must be unique")
        if len(set(self.concurrency_resource_ids)) != len(self.concurrency_resource_ids):
            raise ValueError("concurrency resources on a path must be unique")
        staged = self.transport in {
            TransportKind.RDMA_HOST_STAGED,
            TransportKind.TCP_HOST_STAGED,
        }
        if staged and not (
            self.source_host_staging_resource_id or self.destination_host_staging_resource_id
        ):
            raise ValueError("host-staged transport requires an explicit staging resource")
        if not staged and (
            self.source_host_staging_resource_id or self.destination_host_staging_resource_id
        ):
            raise ValueError("direct transport cannot silently reserve host staging")
        local_transport = self.transport in {
            TransportKind.LOCAL_COPY,
            TransportKind.NVLINK,
        }
        if local_transport:
            if self.source_node_id != self.destination_node_id:
                raise ValueError("LOCAL_COPY/NVLINK paths cannot cross nodes")
            if self.source_hca_id is not None or self.destination_hca_id is not None:
                raise ValueError("LOCAL_COPY/NVLINK paths cannot bind network HCAs")
        elif not self.source_hca_id or not self.destination_hca_id:
            raise ValueError("network paths require explicit source and destination HCAs")
        if self.transport is TransportKind.NVLINK and (
            self.source_kind is not MemoryKind.GPU_HBM
            or self.destination_kind is not MemoryKind.GPU_HBM
        ):
            raise ValueError("NVLINK is valid only between GPU HBM locations")

    def matches(self, source: MemoryLocation, destination: MemoryLocation) -> bool:
        """Return whether both locations exactly satisfy this resolved path."""

        return (
            self.source_kind is source.kind
            and self.destination_kind is destination.kind
            and self.source_endpoint == source.endpoint
            and self.destination_endpoint == destination.endpoint
            and self.source_node_id == source.node_id
            and self.destination_node_id == destination.node_id
            and self.source_numa_node_id == source.numa_node_id
            and self.destination_numa_node_id == destination.numa_node_id
        )


class Topology:
    """Resolved, deterministic analogue of pinned Mooncake ``Topology``.

    Retry zero selects the stable first preferred path, falling back to the
    stable first available path only when no preferred path is eligible.
    Positive retries enumerate the complete preferred-then-available list with
    the pinned ``(retry_count - 1) % N`` rule.  This intentionally does not
    claim parity with upstream random or thread-local round-robin initial
    choice, real device discovery, or physical distance measurement.
    """

    def __init__(self, paths: list[TopologyPath]) -> None:
        if not paths:
            raise ValueError("topology requires at least one path")
        self._paths = {path.path_id: path for path in paths}
        if len(self._paths) != len(paths):
            raise ValueError("topology path IDs must be unique")
        self._disabled: set[str] = set()
        self._disabled_hcas: set[str] = set()
        self.audit()

    @property
    def paths(self) -> tuple[TopologyPath, ...]:
        return tuple(sorted(self._paths.values(), key=self._sort_key))

    def disable_path(self, path_id: str) -> None:
        if path_id not in self._paths:
            raise KeyError(path_id)
        self._disabled.add(path_id)

    def enable_path(self, path_id: str) -> None:
        if path_id not in self._paths:
            raise KeyError(path_id)
        self._disabled.discard(path_id)

    def disable_hca(self, hca_id: str) -> None:
        """Remove one HCA from future selection without renumbering paths."""

        if not hca_id:
            raise ValueError("hca_id must be non-empty")
        known = {
            hca
            for path in self._paths.values()
            for hca in (path.source_hca_id, path.destination_hca_id)
            if hca is not None
        }
        if hca_id not in known:
            raise KeyError(hca_id)
        self._disabled_hcas.add(hca_id)

    def select_path(
        self,
        source: MemoryLocation,
        destination: MemoryLocation,
        *,
        transport_hint: TransportKind | None = None,
        retry_count: int = 0,
    ) -> TopologyPath:
        if type(retry_count) is not int or retry_count < 0:
            raise ValueError("retry_count must be a non-negative integer")
        candidates = [
            path
            for path in self._paths.values()
            if path.path_id not in self._disabled
            and path.matches(source, destination)
            and (transport_hint is None or path.transport is transport_hint)
            and path.source_hca_id not in self._disabled_hcas
            and path.destination_hca_id not in self._disabled_hcas
        ]
        if not candidates:
            raise ValueError("no exact compatible enabled topology path")
        preferred = sorted(
            (path for path in candidates if path.preference is PathPreference.PREFERRED),
            key=self._sort_key,
        )
        available = sorted(
            (path for path in candidates if path.preference is PathPreference.AVAILABLE),
            key=self._sort_key,
        )
        if retry_count == 0:
            selected_class = preferred if preferred else available
            return selected_class[0]
        ordered = (*preferred, *available)
        return ordered[(retry_count - 1) % len(ordered)]

    def audit(self) -> None:
        """Fail closed on unresolved or internally inconsistent path state."""

        if self._disabled - set(self._paths):
            raise RuntimeError("disabled topology state references an unknown path")
        known_hcas = {
            hca
            for path in self._paths.values()
            for hca in (path.source_hca_id, path.destination_hca_id)
            if hca is not None
        }
        if not self._disabled_hcas.issubset(known_hcas):
            raise RuntimeError("disabled topology state references an unknown HCA")

    @staticmethod
    def _sort_key(path: TopologyPath) -> tuple[int, str]:
        return (path.priority, path.path_id)


@dataclass(frozen=True, slots=True)
class TransferMetadata:
    transfer_id: str
    object_id: str
    replica_id: str
    source: MemoryLocation
    destination: MemoryLocation
    opcode: TransferOpcode
    total_bytes: int
    cause: str
    route_version: int
    ready_ns: int
    path: TopologyPath
    destination_allocation_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identifiers = (self.transfer_id, self.object_id, self.replica_id, self.cause)
        if any(not value for value in identifiers):
            raise ValueError("transfer identifiers and cause must be non-empty")
        if self.total_bytes <= 0:
            raise ValueError("transfer size must be positive")
        if self.route_version < 0 or self.ready_ns < 0:
            raise ValueError("route version and ready time must be non-negative")
        if self.path.source_kind is not self.source.kind:
            raise ValueError("path source kind does not match metadata")
        if self.path.destination_kind is not self.destination.kind:
            raise ValueError("path destination kind does not match metadata")
        if not self.path.matches(self.source, self.destination):
            raise ValueError("path endpoint/node/NUMA binding does not match metadata")
        if len(set(self.destination_allocation_ids)) != len(self.destination_allocation_ids) or any(
            not item for item in self.destination_allocation_ids
        ):
            raise ValueError("destination allocation IDs must be unique and non-empty")
        if self.destination_allocation_ids and (
            self.opcode is not TransferOpcode.READ
            or self.destination.kind is not MemoryKind.GPU_HBM
        ):
            raise ValueError("only a Store READ into GPU HBM may bind destination allocations")


@dataclass(frozen=True, slots=True)
class Slice:
    slice_id: str
    transfer_id: str
    offset_bytes: int
    length_bytes: int
    status: SliceStatus = SliceStatus.PENDING
    posted_ns: int | None = None
    terminal_ns: int | None = None
    abort_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.slice_id or not self.transfer_id:
            raise ValueError("slice identifiers must be non-empty")
        if self.offset_bytes < 0 or self.length_bytes <= 0:
            raise ValueError("slice offset and length are invalid")
        if self.status is SliceStatus.PENDING and (
            self.posted_ns is not None or self.terminal_ns is not None
        ):
            raise ValueError("pending slice cannot have lifecycle timestamps")
        if self.status is SliceStatus.POSTED and (
            self.posted_ns is None or self.terminal_ns is not None
        ):
            raise ValueError("posted slice requires only posted_ns")
        if self.status.terminal and (self.posted_ns is None or self.terminal_ns is None):
            raise ValueError("terminal slice requires posted and terminal timestamps")
        if self.terminal_ns is not None and self.terminal_ns < (self.posted_ns or 0):
            raise ValueError("slice terminal time cannot precede posting")
        failed = self.status in {
            SliceStatus.FAILED,
            SliceStatus.TIMEOUT,
            SliceStatus.CANCELED,
        }
        if failed != (self.abort_reason is not None):
            raise ValueError("only unsuccessful terminal slices require an abort reason")

    def post(self, *, timestamp_ns: int) -> Slice:
        if self.status is not SliceStatus.PENDING:
            raise ValueError("only pending slices may be posted")
        return replace(self, status=SliceStatus.POSTED, posted_ns=timestamp_ns)

    def finish(
        self,
        status: SliceStatus,
        *,
        timestamp_ns: int,
        abort_reason: str | None = None,
    ) -> Slice:
        if self.status is not SliceStatus.POSTED or not status.terminal:
            raise ValueError("only a posted slice may enter a terminal state")
        return replace(
            self,
            status=status,
            terminal_ns=timestamp_ns,
            abort_reason=abort_reason,
        )


@dataclass(slots=True)
class TransferTask:
    metadata: TransferMetadata
    slices: list[Slice]
    status: TransferStatus = TransferStatus.WAITING
    start_ns: int | None = None
    end_ns: int | None = None
    abort_reason: str | None = None

    @classmethod
    def create(
        cls,
        metadata: TransferMetadata,
        *,
        slice_size_bytes: int = DEFAULT_SLICE_SIZE_BYTES,
    ) -> TransferTask:
        if slice_size_bytes <= 0:
            raise ValueError("slice size must be positive")
        slices: list[Slice] = []
        offset = 0
        while offset < metadata.total_bytes:
            length = min(slice_size_bytes, metadata.total_bytes - offset)
            slices.append(
                Slice(
                    slice_id=f"{metadata.transfer_id}:slice-{len(slices):06d}",
                    transfer_id=metadata.transfer_id,
                    offset_bytes=offset,
                    length_bytes=length,
                )
            )
            offset += length
        return cls(metadata=metadata, slices=slices)

    @property
    def transferred_bytes(self) -> int:
        return sum(item.length_bytes for item in self.slices if item.status is SliceStatus.SUCCESS)

    def start(self, *, timestamp_ns: int) -> None:
        if self.status is not TransferStatus.WAITING:
            raise ValueError("only a waiting task may start")
        if timestamp_ns < self.metadata.ready_ns:
            raise ValueError("transfer cannot start before ready_ns")
        self.status = TransferStatus.PENDING
        self.start_ns = timestamp_ns

    def update_slice(self, updated: Slice) -> None:
        if updated.transfer_id != self.metadata.transfer_id:
            raise ValueError("slice belongs to another transfer")
        for index, current in enumerate(self.slices):
            if current.slice_id == updated.slice_id:
                if current.status.terminal:
                    raise ValueError("terminal slice cannot be updated")
                self.slices[index] = updated
                self._refresh_terminal_state()
                return
        raise KeyError(updated.slice_id)

    def cancel_remaining(self, *, timestamp_ns: int, reason: str) -> None:
        if not reason or self.status.terminal:
            raise ValueError("active task and non-empty cancellation reason required")
        for index, item in enumerate(self.slices):
            if item.status is SliceStatus.PENDING:
                item = item.post(timestamp_ns=timestamp_ns)
            if item.status is SliceStatus.POSTED:
                self.slices[index] = item.finish(
                    SliceStatus.CANCELED,
                    timestamp_ns=timestamp_ns,
                    abort_reason=reason,
                )
        self.status = TransferStatus.CANCELED
        self.end_ns = timestamp_ns
        self.abort_reason = reason

    def _refresh_terminal_state(self) -> None:
        if not all(item.status.terminal for item in self.slices):
            return
        terminal_times = [item.terminal_ns for item in self.slices]
        if any(value is None for value in terminal_times):
            raise RuntimeError("terminal slice is missing terminal_ns")
        self.end_ns = max(value for value in terminal_times if value is not None)
        if all(item.status is SliceStatus.SUCCESS for item in self.slices):
            self.status = TransferStatus.COMPLETED
            return
        if any(item.status is SliceStatus.TIMEOUT for item in self.slices):
            self.status = TransferStatus.TIMEOUT
        elif any(item.status is SliceStatus.FAILED for item in self.slices):
            self.status = TransferStatus.FAILED
        else:
            self.status = TransferStatus.CANCELED
        reasons = sorted({item.abort_reason for item in self.slices if item.abort_reason})
        self.abort_reason = ";".join(reasons)

    def audit(self) -> None:
        cursor = 0
        for item in self.slices:
            if item.offset_bytes != cursor:
                raise RuntimeError("transfer slices are not contiguous")
            cursor += item.length_bytes
        if cursor != self.metadata.total_bytes:
            raise RuntimeError("transfer slices do not conserve bytes")
        if self.transferred_bytes > self.metadata.total_bytes:
            raise RuntimeError("transferred bytes exceed request")
        if self.status is TransferStatus.COMPLETED and (
            self.transferred_bytes != self.metadata.total_bytes
        ):
            raise RuntimeError("completed task has missing bytes")


@dataclass(slots=True)
class BatchTransfer:
    batch_id: str
    tasks: list[TransferTask] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.batch_id:
            raise ValueError("batch_id must be non-empty")

    @property
    def status(self) -> TransferStatus:
        if not self.tasks or any(task.status is TransferStatus.WAITING for task in self.tasks):
            return TransferStatus.WAITING
        if any(task.status is TransferStatus.PENDING for task in self.tasks):
            return TransferStatus.PENDING
        if all(task.status is TransferStatus.COMPLETED for task in self.tasks):
            return TransferStatus.COMPLETED
        if any(task.status is TransferStatus.TIMEOUT for task in self.tasks):
            return TransferStatus.TIMEOUT
        if any(task.status is TransferStatus.FAILED for task in self.tasks):
            return TransferStatus.FAILED
        return TransferStatus.CANCELED

    @property
    def transferred_bytes(self) -> int:
        return sum(task.transferred_bytes for task in self.tasks)

    def add_task(self, task: TransferTask) -> None:
        if task.status is not TransferStatus.WAITING:
            raise ValueError("only waiting tasks can be added to a batch")
        if any(item.status is not TransferStatus.WAITING for item in self.tasks):
            raise ValueError("tasks cannot be added after a batch starts")
        if any(item.metadata.transfer_id == task.metadata.transfer_id for item in self.tasks):
            raise ValueError("duplicate transfer ID in batch")
        self.tasks.append(task)
