"""Pinned-vLLM-compatible prefix-block hashing for the ordinary SHA-256 path.

Pinned vLLM hashes ``(parent_hash, tuple(token_ids), extra_keys)`` after
``pickle.dumps(..., protocol=pickle.HIGHEST_PROTOCOL)``. The first parent is
itself the SHA-256/pickle hash of an explicit ``PYTHONHASHSEED`` string. The
simulator requires that seed instead of silently using vLLM's random fallback,
because a replay artifact must be reproducible across processes.
"""

from __future__ import annotations

import hashlib
import pickle
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


def pinned_sha256(value: object) -> bytes:
    """Mirror ``vllm.utils.hashing.sha256`` byte-for-byte."""

    return hashlib.sha256(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)).digest()


def initial_none_hash(python_hash_seed: str) -> str:
    """Return pinned vLLM's deterministic first-parent hash as lowercase hex."""

    if not python_hash_seed:
        raise ValueError("python_hash_seed must be a non-empty explicit string")
    return pinned_sha256(python_hash_seed).hex()


@dataclass(frozen=True, slots=True)
class BlockHashWitness:
    """Preimage witness used to fail closed on an injected digest collision."""

    digest: str
    parent_digest: str
    token_ids: tuple[int, ...]
    extra_keys: tuple[Any, ...] | None = None

    def __post_init__(self) -> None:
        _validate_digest(self.digest, "digest")
        _validate_digest(self.parent_digest, "parent_digest")
        if not self.token_ids:
            raise ValueError("a block hash witness requires at least one token")
        if any(type(token_id) is not int or token_id < 0 for token_id in self.token_ids):
            raise ValueError("token IDs must be non-negative integers")


def hash_block_tokens(
    parent_block_hash: str | None,
    curr_block_token_ids: Sequence[int],
    *,
    extra_keys: Sequence[Any] | None = None,
    python_hash_seed: str | None = None,
) -> str:
    """Hash one full block with the pinned SHA-256/pickle parent chain.

    ``python_hash_seed`` is required only for the first block. Later calls
    consume the explicit parent digest and cannot accidentally re-seed a chain.
    """

    return hash_block_witness(
        parent_block_hash,
        curr_block_token_ids,
        extra_keys=extra_keys,
        python_hash_seed=python_hash_seed,
    ).digest


def hash_block_witness(
    parent_block_hash: str | None,
    curr_block_token_ids: Sequence[int],
    *,
    extra_keys: Sequence[Any] | None = None,
    python_hash_seed: str | None = None,
) -> BlockHashWitness:
    """Return both the pinned digest and its collision-checking preimage."""

    tokens = tuple(curr_block_token_ids)
    if not tokens:
        raise ValueError("a block hash requires at least one token")
    if any(type(token_id) is not int or token_id < 0 for token_id in tokens):
        raise ValueError("token IDs must be non-negative integers")
    if parent_block_hash is None:
        if python_hash_seed is None:
            raise ValueError("the first block requires an explicit python_hash_seed")
        parent = initial_none_hash(python_hash_seed)
    else:
        _validate_digest(parent_block_hash, "parent_block_hash")
        parent = parent_block_hash
    normalized_extra = tuple(extra_keys) if extra_keys is not None else None
    digest = pinned_sha256((bytes.fromhex(parent), tokens, normalized_extra)).hex()
    return BlockHashWitness(
        digest=digest,
        parent_digest=parent,
        token_ids=tokens,
        extra_keys=normalized_extra,
    )


def hash_full_block_witnesses(
    token_ids: Sequence[int],
    *,
    block_size: int,
    python_hash_seed: str,
    parent_block_hash: str | None = None,
    per_block_extra_keys: Iterable[Sequence[Any] | None] | None = None,
) -> tuple[BlockHashWitness, ...]:
    """Hash complete blocks only and retain every causal-chain witness."""

    if type(block_size) is not int or block_size <= 0:
        raise ValueError("block_size must be positive")
    full_block_count = len(token_ids) // block_size
    extra = (
        list(per_block_extra_keys)
        if per_block_extra_keys is not None
        else [None] * full_block_count
    )
    if len(extra) != full_block_count:
        raise ValueError("extra-key count must equal the number of full blocks")

    witnesses: list[BlockHashWitness] = []
    parent = parent_block_hash
    for block_index in range(full_block_count):
        start = block_index * block_size
        witness = hash_block_witness(
            parent,
            token_ids[start : start + block_size],
            extra_keys=extra[block_index],
            python_hash_seed=python_hash_seed if parent is None else None,
        )
        witnesses.append(witness)
        parent = witness.digest
    return tuple(witnesses)


def hash_full_blocks(
    token_ids: Sequence[int],
    *,
    block_size: int,
    python_hash_seed: str = "0",
    parent_block_hash: str | None = None,
    per_block_extra_keys: Iterable[Sequence[Any] | None] | None = None,
) -> tuple[str, ...]:
    """Return pinned digests for complete blocks, ignoring a partial tail."""

    return tuple(
        witness.digest
        for witness in hash_full_block_witnesses(
            token_ids,
            block_size=block_size,
            python_hash_seed=python_hash_seed,
            parent_block_hash=parent_block_hash,
            per_block_extra_keys=per_block_extra_keys,
        )
    )


def _validate_digest(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
