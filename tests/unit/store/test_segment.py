import pytest

from moonkvsim.store.allocation_strategy import RandomAllocationStrategy
from moonkvsim.store.segment import Segment, SegmentStatus


def segment(segment_id: str, *, capacity: int = 1024) -> Segment:
    item = Segment(
        segment_id=segment_id,
        name=segment_id,
        node_id=f"node-{segment_id}",
        numa_node_id=f"numa:node-{segment_id}:0",
        transport_endpoint=f"tcp://{segment_id}",
        capacity_bytes=capacity,
        allocation_alignment_bytes=64,
        allocator_metadata_bytes=8,
    )
    item.mount()
    return item


def test_segment_tracks_requested_metadata_fragmentation_and_extent_reuse() -> None:
    item = segment("s0")
    first = item.allocate(buffer_id="a", requested_bytes=100)
    second = item.allocate(buffer_id="b", requested_bytes=60)
    assert first is not None and second is not None

    assert first.offset_bytes == 0
    assert first.allocated_bytes == 128
    assert first.internal_fragmentation_bytes == 20
    assert second.offset_bytes == 128
    assert item.used_bytes == 256

    item.deallocate("a")
    replacement = item.allocate(buffer_id="c", requested_bytes=40)
    assert replacement is not None
    assert replacement.offset_bytes == 0
    item.audit()


def test_draining_segment_is_readable_but_rejects_new_allocation() -> None:
    item = segment("s0")
    item.begin_drain()
    assert item.status is SegmentStatus.DRAINING
    assert item.status.readable
    assert item.allocate(buffer_id="late", requested_bytes=1) is None
    item.finish_drain()
    assert item.status is SegmentStatus.DRAINED


def test_finish_drain_requires_every_extent_to_be_released() -> None:
    item = segment("s0")
    assert item.allocate(buffer_id="live", requested_bytes=1) is not None
    item.begin_drain()
    with pytest.raises(ValueError, match="every buffer"):
        item.finish_drain()


def test_seeded_strategy_places_best_effort_replicas_on_distinct_segments() -> None:
    segments = [segment("s0"), segment("s1"), segment("s2", capacity=64)]
    strategy = RandomAllocationStrategy(seed=17)
    placements = strategy.allocate(
        segments,
        slice_id="slice-0",
        slice_length_bytes=100,
        replica_count=3,
        preferred_segment_ids=["s1"],
    )

    assert placements[0].segment_id == "s1"
    assert len(placements) == 2
    assert len({placement.segment_id for placement in placements}) == 2


def test_segment_fails_closed_on_duplicate_buffer_and_invalid_watermark() -> None:
    item = segment("s0")
    assert item.allocate(buffer_id="a", requested_bytes=1) is not None
    with pytest.raises(ValueError, match="unique"):
        item.allocate(buffer_id="a", requested_bytes=1)
    with pytest.raises(ValueError, match="watermark"):
        item.above_high_watermark(0)
