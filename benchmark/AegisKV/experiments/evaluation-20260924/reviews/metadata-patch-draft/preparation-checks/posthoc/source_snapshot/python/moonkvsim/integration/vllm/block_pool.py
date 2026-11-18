"""Tensor-free mirror of pinned vLLM block-pool ownership semantics."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from moonkvsim.integration.vllm.block_hash import BlockHashWitness


@dataclass(slots=True)
class KVCacheBlock:
    block_id: int
    ref_count: int = 0
    block_hash: str | None = None
    group_id: int | None = None
    hash_witness: BlockHashWitness | None = None
    is_null: bool = False

    @property
    def cache_key(self) -> tuple[str, int] | None:
        if self.block_hash is None or self.group_id is None:
            return None
        return (self.block_hash, self.group_id)


class BlockPool:
    """Keep one null block plus an LRU-ordered free/eviction queue."""

    def __init__(self, num_gpu_blocks: int, *, enable_caching: bool) -> None:
        if num_gpu_blocks <= 1:
            raise ValueError("num_gpu_blocks must leave room beyond the null block")
        self.enable_caching = enable_caching
        self.blocks = [KVCacheBlock(block_id=index) for index in range(num_gpu_blocks)]
        self.blocks[0].is_null = True
        self._free_queue: deque[int] = deque(range(1, num_gpu_blocks))
        self._free_members = set(self._free_queue)
        self._cached: dict[tuple[str, int], list[int]] = {}

    @property
    def null_block(self) -> KVCacheBlock:
        return self.blocks[0]

    @property
    def num_free_blocks(self) -> int:
        return len(self._free_queue)

    @property
    def free_block_ids(self) -> tuple[int, ...]:
        return tuple(self._free_queue)

    def peek_allocatable_block_ids(self, count: int) -> tuple[int, ...]:
        """Return the next stable block IDs without changing pool ownership.

        Lifecycle observers use this preview to reserve physical HBM before the
        scheduler mutates either the block pool or request state.  ``allocate``
        remains the sole owner-changing operation.
        """

        if count < 0:
            raise ValueError("allocation preview count must be non-negative")
        if count > self.num_free_blocks:
            raise ValueError(f"cannot preview {count} blocks from the free pool")
        if count == 0:
            return ()
        return tuple(list(self._free_queue)[:count])

    def _remove_free_member(self, block_id: int) -> None:
        if block_id in self._free_members:
            self._free_queue.remove(block_id)
            self._free_members.remove(block_id)

    def _drop_cached_key(self, block: KVCacheBlock) -> None:
        cache_key = block.cache_key
        if cache_key is None:
            return
        block_ids = self._cached[cache_key]
        block_ids.remove(block.block_id)
        if not block_ids:
            del self._cached[cache_key]
        block.block_hash = None
        block.group_id = None
        block.hash_witness = None

    def allocate(self, count: int) -> tuple[KVCacheBlock, ...]:
        if count <= 0:
            raise ValueError("allocation count must be positive")
        if count > self.num_free_blocks:
            raise ValueError(f"cannot allocate {count} blocks from the free pool")
        allocated: list[KVCacheBlock] = []
        for _ in range(count):
            block_id = self._free_queue.popleft()
            self._free_members.remove(block_id)
            block = self.blocks[block_id]
            if block.ref_count != 0:
                raise RuntimeError("free queue contains a referenced block")
            if self.enable_caching:
                self._drop_cached_key(block)
            block.ref_count = 1
            allocated.append(block)
        return tuple(allocated)

    def cache(
        self,
        block_id: int,
        *,
        block_hash: str,
        group_id: int,
        witness: BlockHashWitness,
    ) -> None:
        block = self._checked_block(block_id)
        if not self.enable_caching:
            raise ValueError("prefix caching is disabled")
        if not block_hash or group_id < 0:
            raise ValueError("cache hash must be non-empty and group ID non-negative")
        if block.is_null or block.block_hash is not None or block.ref_count <= 0:
            raise ValueError("only an uncached, referenced, non-null block may be cached")
        if witness.digest != block_hash:
            raise ValueError("cache witness digest disagrees with block_hash")
        self.validate_hash_witness(block_hash, group_id=group_id, witness=witness)
        block.block_hash = block_hash
        block.group_id = group_id
        block.hash_witness = witness
        self._cached.setdefault((block_hash, group_id), []).append(block_id)

    def get_cached(
        self,
        block_hash: str,
        *,
        group_id: int,
        witness: BlockHashWitness,
    ) -> KVCacheBlock | None:
        self.validate_hash_witness(block_hash, group_id=group_id, witness=witness)
        block_ids = self._cached.get((block_hash, group_id))
        if not block_ids:
            return None
        return self.blocks[block_ids[0]]

    def validate_hash_witness(
        self,
        block_hash: str,
        *,
        group_id: int,
        witness: BlockHashWitness,
    ) -> None:
        """Reject one digest/group key with two different preimages."""

        if witness.digest != block_hash:
            raise ValueError("cache witness digest disagrees with block_hash")
        for block_id in self._cached.get((block_hash, group_id), ()):
            cached_witness = self.blocks[block_id].hash_witness
            if cached_witness != witness:
                raise ValueError("prefix-cache digest collision witness mismatch")

    @property
    def cached_block_ids(self) -> tuple[int, ...]:
        return tuple(block.block_id for block in self.blocks[1:] if block.cache_key is not None)

    def cached_hashes(self) -> dict[int, str]:
        return {
            block.block_id: block.block_hash
            for block in self.blocks[1:]
            if block.block_hash is not None
        }

    def touch(self, block_ids: Iterable[int]) -> None:
        for block_id in block_ids:
            block = self._checked_block(block_id)
            if block.is_null:
                block.ref_count += 1
                continue
            if block.ref_count == 0:
                self._remove_free_member(block_id)
            block.ref_count += 1

    def free(self, block_ids_in_eviction_order: Iterable[int]) -> None:
        """Release references and append newly free blocks in caller LRU order."""

        released: list[int] = []
        for block_id in block_ids_in_eviction_order:
            block = self._checked_block(block_id)
            if block.is_null:
                continue
            if block.ref_count <= 0:
                raise ValueError("cannot free an unreferenced block")
            block.ref_count -= 1
            if block.ref_count == 0:
                released.append(block_id)
        for block_id in released:
            if block_id in self._free_members:
                raise RuntimeError("block is already present in the free queue")
            self._free_queue.append(block_id)
            self._free_members.add(block_id)

    def evict(self, block_id: int) -> None:
        block = self._checked_block(block_id)
        self._drop_cached_key(block)

    def audit(self) -> None:
        if self.blocks[0] is not self.null_block or not self.null_block.is_null:
            raise RuntimeError("null block invariant failed")
        if len(self._free_members) != len(self._free_queue):
            raise RuntimeError("free queue contains duplicates")
        if set(self._free_queue) != self._free_members:
            raise RuntimeError("free queue membership drift")
        for block in self.blocks[1:]:
            if (block.ref_count == 0) != (block.block_id in self._free_members):
                raise RuntimeError("reference/free-queue invariant failed")
            if (block.block_hash is None) != (block.group_id is None):
                raise RuntimeError("partial cache key")
            if (block.block_hash is None) != (block.hash_witness is None):
                raise RuntimeError("partial cache witness")
            if block.hash_witness is not None and block.hash_witness.digest != block.block_hash:
                raise RuntimeError("cache witness digest drift")
            if block.cache_key is not None and block.block_id not in self._cached.get(
                block.cache_key, []
            ):
                raise RuntimeError("cache map is missing a block")
        for cache_key, block_ids in self._cached.items():
            if len(set(block_ids)) != len(block_ids):
                raise RuntimeError("cache map contains duplicate block IDs")
            for block_id in block_ids:
                if self.blocks[block_id].cache_key != cache_key:
                    raise RuntimeError("cache map key mismatch")
            witnesses = {self.blocks[block_id].hash_witness for block_id in block_ids}
            if len(witnesses) != 1:
                raise RuntimeError("one cache key contains conflicting collision witnesses")

    def _checked_block(self, block_id: int) -> KVCacheBlock:
        if block_id < 0 or block_id >= len(self.blocks):
            raise ValueError(f"unknown block ID: {block_id}")
        return self.blocks[block_id]
