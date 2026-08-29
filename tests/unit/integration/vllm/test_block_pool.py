import pytest

from moonkvsim.integration.vllm.block_hash import (
    BlockHashWitness,
    hash_full_block_witnesses,
    hash_full_blocks,
    initial_none_hash,
)
from moonkvsim.integration.vllm.block_pool import BlockPool


def test_block_hash_is_parent_chained_and_ignores_partial_tail() -> None:
    token_ids = list(range(10))
    first = hash_full_blocks(token_ids, block_size=4)
    second = hash_full_blocks(token_ids, block_size=4)
    changed = hash_full_blocks([99, *token_ids[1:]], block_size=4)

    assert first == second
    assert len(first) == 2
    assert first[0] != changed[0]
    assert first[1] != changed[1]
    assert initial_none_hash("0") == (
        "1973e23848344dc43a988a9b478663803cfffe1243480253f9a3cf004b14aa7c"
    )
    assert first == (
        "46117ba77ad894de70dbb722c54f081d9c22d67a118e1776b7acef72235a141f",
        "138b5b26bb0e76617b5e0ed41ce28645aecd5ac545c6f92bbf3cdd3ec41834be",
    )


def test_cached_free_block_can_be_touched_without_reallocation() -> None:
    pool = BlockPool(4, enable_caching=True)
    [block] = pool.allocate(1)
    [witness] = hash_full_block_witnesses([1, 2, 3, 4], block_size=4, python_hash_seed="0")
    pool.cache(
        block.block_id,
        block_hash=witness.digest,
        group_id=0,
        witness=witness,
    )
    pool.free([block.block_id])

    assert pool.free_block_ids == (2, 3, 1)
    hit = pool.get_cached(witness.digest, group_id=0, witness=witness)
    assert hit is block

    pool.touch([block.block_id])
    assert block.ref_count == 1
    assert pool.free_block_ids == (2, 3)
    pool.audit()


def test_lru_allocation_evicts_cached_metadata_but_not_capacity_twice() -> None:
    pool = BlockPool(3, enable_caching=True)
    first, second = pool.allocate(2)
    first_witness, second_witness = hash_full_block_witnesses(
        list(range(8)), block_size=4, python_hash_seed="0"
    )
    pool.cache(
        first.block_id,
        block_hash=first_witness.digest,
        group_id=0,
        witness=first_witness,
    )
    pool.cache(
        second.block_id,
        block_hash=second_witness.digest,
        group_id=0,
        witness=second_witness,
    )
    pool.free([second.block_id, first.block_id])

    [reused] = pool.allocate(1)
    assert reused is second
    assert (
        pool.get_cached(
            second_witness.digest,
            group_id=0,
            witness=second_witness,
        )
        is None
    )
    assert (
        pool.get_cached(
            first_witness.digest,
            group_id=0,
            witness=first_witness,
        )
        is first
    )
    pool.audit()


def test_cache_digest_collision_guard_rejects_a_different_preimage() -> None:
    pool = BlockPool(3, enable_caching=True)
    [block] = pool.allocate(1)
    [witness] = hash_full_block_witnesses([1, 2, 3, 4], block_size=4, python_hash_seed="0")
    pool.cache(
        block.block_id,
        block_hash=witness.digest,
        group_id=0,
        witness=witness,
    )
    forged = BlockHashWitness(
        digest=witness.digest,
        parent_digest=witness.parent_digest,
        token_ids=(9, 9, 9, 9),
    )

    with pytest.raises(ValueError, match="collision witness"):
        pool.get_cached(witness.digest, group_id=0, witness=forged)


def test_pool_rejects_overallocation_and_double_free() -> None:
    pool = BlockPool(2, enable_caching=False)
    [block] = pool.allocate(1)
    with pytest.raises(ValueError, match="free pool"):
        pool.allocate(1)
    pool.free([block.block_id])
    with pytest.raises(ValueError, match="unreferenced"):
        pool.free([block.block_id])
