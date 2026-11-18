"""DRAM-only Mooncake-style segment and explicit extent allocator.

The baseline intentionally has no disk/NVMe replica type. This allocator is
the geometry source for requested/allocated/fragmentation bytes; capacity
charging remains the responsibility of the atomic resource transaction layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SegmentStatus(StrEnum):
    UNDEFINED = "UNDEFINED"
    OK = "OK"
    DRAINING = "DRAINING"
    DRAINED = "DRAINED"
    GRACEFULLY_UNMOUNTING = "GRACEFULLY_UNMOUNTING"
    UNMOUNTING = "UNMOUNTING"

    @property
    def accepts_allocations(self) -> bool:
        return self is SegmentStatus.OK

    @property
    def readable(self) -> bool:
        return self in {
            SegmentStatus.OK,
            SegmentStatus.DRAINING,
            SegmentStatus.GRACEFULLY_UNMOUNTING,
        }


@dataclass(frozen=True, slots=True)
class Buffer:
    buffer_id: str
    segment_id: str
    offset_bytes: int
    requested_bytes: int
    allocated_bytes: int
    allocator_metadata_bytes: int
    internal_fragmentation_bytes: int
    alignment_bytes: int

    def __post_init__(self) -> None:
        if not self.buffer_id or not self.segment_id:
            raise ValueError("buffer and segment IDs must be non-empty")
        if self.offset_bytes < 0 or self.requested_bytes <= 0:
            raise ValueError("buffer offset must be non-negative and request positive")
        if self.allocated_bytes <= 0 or self.alignment_bytes <= 0:
            raise ValueError("allocated bytes and alignment must be positive")
        if self.allocator_metadata_bytes < 0 or self.internal_fragmentation_bytes < 0:
            raise ValueError("metadata and fragmentation bytes must be non-negative")
        if self.allocated_bytes != (
            self.requested_bytes + self.allocator_metadata_bytes + self.internal_fragmentation_bytes
        ):
            raise ValueError("allocated extent must be fully explained")
        if self.offset_bytes % self.alignment_bytes != 0:
            raise ValueError("buffer offset is not aligned")

    @property
    def end_offset_bytes(self) -> int:
        return self.offset_bytes + self.allocated_bytes


class Segment:
    """Mounted memory segment with deterministic aligned first-fit allocation."""

    def __init__(
        self,
        *,
        segment_id: str,
        name: str,
        node_id: str,
        numa_node_id: str,
        transport_endpoint: str,
        capacity_bytes: int,
        allocation_alignment_bytes: int,
        allocator_metadata_bytes: int = 0,
    ) -> None:
        identifiers = (segment_id, name, node_id, numa_node_id, transport_endpoint)
        if any(not value for value in identifiers):
            raise ValueError("segment identifiers and endpoint must be non-empty")
        if capacity_bytes <= 0 or allocation_alignment_bytes <= 0:
            raise ValueError("segment capacity and alignment must be positive")
        if allocator_metadata_bytes < 0:
            raise ValueError("allocator metadata bytes must be non-negative")
        self.segment_id = segment_id
        self.name = name
        self.node_id = node_id
        self.numa_node_id = numa_node_id
        self.transport_endpoint = transport_endpoint
        self.capacity_bytes = capacity_bytes
        self.allocation_alignment_bytes = allocation_alignment_bytes
        self.allocator_metadata_bytes = allocator_metadata_bytes
        self.status = SegmentStatus.UNDEFINED
        self._buffers: dict[str, Buffer] = {}

    @property
    def buffers(self) -> tuple[Buffer, ...]:
        return tuple(sorted(self._buffers.values(), key=lambda item: item.offset_bytes))

    @property
    def used_bytes(self) -> int:
        return sum(buffer.allocated_bytes for buffer in self._buffers.values())

    @property
    def free_bytes(self) -> int:
        return self.capacity_bytes - self.used_bytes

    @property
    def largest_free_region_bytes(self) -> int:
        return max((end - start for start, end in self._free_regions()), default=0)

    def mount(self) -> None:
        if self.status is not SegmentStatus.UNDEFINED:
            raise ValueError("only an undefined segment may be mounted")
        self.status = SegmentStatus.OK

    def begin_drain(self) -> None:
        if self.status is not SegmentStatus.OK:
            raise ValueError("only an OK segment may begin draining")
        self.status = SegmentStatus.DRAINING

    def finish_drain(self) -> None:
        if self.status is not SegmentStatus.DRAINING or self._buffers:
            raise ValueError("drain may finish only after every buffer is released")
        self.status = SegmentStatus.DRAINED

    def allocate(self, *, buffer_id: str, requested_bytes: int) -> Buffer | None:
        if not self.status.accepts_allocations:
            return None
        if not buffer_id or buffer_id in self._buffers:
            raise ValueError("buffer_id must be non-empty and unique")
        if requested_bytes <= 0:
            raise ValueError("requested_bytes must be positive")
        charged_before_rounding = requested_bytes + self.allocator_metadata_bytes
        allocated_bytes = _round_up(charged_before_rounding, self.allocation_alignment_bytes)
        for start, end in self._free_regions():
            offset = _round_up(start, self.allocation_alignment_bytes)
            if offset + allocated_bytes > end:
                continue
            buffer = Buffer(
                buffer_id=buffer_id,
                segment_id=self.segment_id,
                offset_bytes=offset,
                requested_bytes=requested_bytes,
                allocated_bytes=allocated_bytes,
                allocator_metadata_bytes=self.allocator_metadata_bytes,
                internal_fragmentation_bytes=(
                    allocated_bytes - requested_bytes - self.allocator_metadata_bytes
                ),
                alignment_bytes=self.allocation_alignment_bytes,
            )
            self._buffers[buffer_id] = buffer
            self.audit()
            return buffer
        return None

    def deallocate(self, buffer_id: str) -> Buffer:
        try:
            buffer = self._buffers.pop(buffer_id)
        except KeyError as error:
            raise KeyError(f"unknown segment buffer: {buffer_id}") from error
        self.audit()
        return buffer

    def restore_deallocated(self, buffer: Buffer) -> None:
        """Restore one exact extent while rolling back a Master transaction.

        This is intentionally not a general allocator entry point: callers may
        restore only a previously materialized immutable ``Buffer`` on the same
        segment.  The overlap/capacity audit runs before the method returns.
        """

        if buffer.segment_id != self.segment_id:
            raise ValueError("cannot restore a buffer on a different segment")
        if buffer.buffer_id in self._buffers:
            raise ValueError(f"duplicate restored buffer: {buffer.buffer_id}")
        self._buffers[buffer.buffer_id] = buffer
        try:
            self.audit()
        except Exception:
            del self._buffers[buffer.buffer_id]
            raise

    def utilization(self) -> float:
        return self.used_bytes / self.capacity_bytes

    def above_high_watermark(self, high_watermark: float) -> bool:
        if not 0.0 < high_watermark <= 1.0:
            raise ValueError("high watermark must be in (0, 1]")
        return self.utilization() >= high_watermark

    def audit(self) -> None:
        previous_end = 0
        used = 0
        for buffer in self.buffers:
            if buffer.segment_id != self.segment_id:
                raise RuntimeError("foreign buffer in segment")
            if buffer.offset_bytes < previous_end:
                raise RuntimeError("segment extents overlap")
            if buffer.end_offset_bytes > self.capacity_bytes:
                raise RuntimeError("segment extent exceeds capacity")
            previous_end = buffer.end_offset_bytes
            used += buffer.allocated_bytes
        if used > self.capacity_bytes or used != self.used_bytes:
            raise RuntimeError("segment byte conservation failed")

    def _free_regions(self) -> tuple[tuple[int, int], ...]:
        regions: list[tuple[int, int]] = []
        cursor = 0
        for buffer in self.buffers:
            if cursor < buffer.offset_bytes:
                regions.append((cursor, buffer.offset_bytes))
            cursor = buffer.end_offset_bytes
        if cursor < self.capacity_bytes:
            regions.append((cursor, self.capacity_bytes))
        return tuple(regions)


def _round_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment
