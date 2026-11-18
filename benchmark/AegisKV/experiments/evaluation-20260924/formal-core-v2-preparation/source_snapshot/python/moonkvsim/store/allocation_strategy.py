"""Mooncake-style best-effort, cross-segment DRAM replica allocation."""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import dataclass

from moonkvsim.store.segment import Buffer, Segment


@dataclass(frozen=True, slots=True)
class ReplicaPlacement:
    replica_index: int
    segment_id: str
    buffer: Buffer


class RandomAllocationStrategy:
    """Prefer named segments, then use a seeded permutation of the remainder.

    Like pinned Mooncake, allocation is best effort and each replica for one
    slice lands on a different segment.
    """

    def __init__(self, *, seed: int) -> None:
        self._random = random.Random(seed)

    def checkpoint(self) -> object:
        """Capture permutation state so a failed allocation transaction can roll back."""

        return self._random.getstate()

    def restore(self, checkpoint: object) -> None:
        """Restore a checkpoint returned by :meth:`checkpoint`."""

        self._random.setstate(checkpoint)  # type: ignore[arg-type]

    def allocate(
        self,
        segments: Iterable[Segment],
        *,
        slice_id: str,
        slice_length_bytes: int,
        replica_count: int,
        preferred_segment_ids: Iterable[str] = (),
        excluded_segment_ids: Iterable[str] = (),
    ) -> tuple[ReplicaPlacement, ...]:
        if not slice_id or slice_length_bytes <= 0 or replica_count <= 0:
            raise ValueError("slice ID, length, and replica count must be valid")
        segment_by_id = {segment.segment_id: segment for segment in segments}
        if not segment_by_id:
            return ()
        excluded = set(excluded_segment_ids)
        preferred: list[str] = []
        for segment_id in preferred_segment_ids:
            if (
                segment_id in segment_by_id
                and segment_id not in excluded
                and segment_id not in preferred
            ):
                preferred.append(segment_id)
        remaining = sorted(set(segment_by_id) - excluded - set(preferred))
        self._random.shuffle(remaining)
        candidates = [*preferred, *remaining]

        placements: list[ReplicaPlacement] = []
        for segment_id in candidates:
            if len(placements) == replica_count:
                break
            segment = segment_by_id[segment_id]
            replica_index = len(placements)
            buffer_id = f"{slice_id}:replica-{replica_index}"
            buffer = segment.allocate(
                buffer_id=buffer_id,
                requested_bytes=slice_length_bytes,
            )
            if buffer is not None:
                placements.append(
                    ReplicaPlacement(
                        replica_index=replica_index,
                        segment_id=segment_id,
                        buffer=buffer,
                    )
                )
        return tuple(placements)
