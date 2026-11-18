"""Stable KV identity shared by engine, Store, and router models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from moonkvsim.common.hash import sha256_json


@dataclass(frozen=True, slots=True)
class KVIdentity:
    tenant_id: str
    model_id: str
    model_revision: str
    kv_dtype: str
    kv_abi: str
    kv_layout: str
    tp_size: int
    pp_size: int
    block_size_tokens: int
    stable_block_hash: str
    token_start: int
    token_end: int
    shard_id: str
    request_id: str
    session_id: str
    workflow_id: str
    route_version: int
    source_gpu_id: str

    def __post_init__(self) -> None:
        string_fields = (
            self.tenant_id,
            self.model_id,
            self.model_revision,
            self.kv_dtype,
            self.kv_abi,
            self.kv_layout,
            self.stable_block_hash,
            self.shard_id,
            self.request_id,
            self.session_id,
            self.workflow_id,
            self.source_gpu_id,
        )
        if any(not value for value in string_fields):
            raise ValueError("KV identity string fields must be non-empty")
        if self.tp_size <= 0 or self.pp_size <= 0:
            raise ValueError("TP and PP sizes must be positive")
        if self.block_size_tokens <= 0:
            raise ValueError("block_size_tokens must be positive")
        if self.token_start < 0 or self.token_end <= self.token_start:
            raise ValueError("token interval must be non-empty and non-negative")
        if self.token_end - self.token_start > self.block_size_tokens:
            raise ValueError("token interval cannot exceed one declared block")
        if self.route_version < 0:
            raise ValueError("route_version must be non-negative")

    def canonical_fields(self) -> dict[str, Any]:
        return asdict(self)

    def content_fields(self) -> dict[str, Any]:
        """Fields that define a cross-DP compatible KV block."""

        return {
            "tenant_id": self.tenant_id,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "kv_dtype": self.kv_dtype,
            "kv_abi": self.kv_abi,
            "kv_layout": self.kv_layout,
            "tp_size": self.tp_size,
            "pp_size": self.pp_size,
            "block_size_tokens": self.block_size_tokens,
            "stable_block_hash": self.stable_block_hash,
            "token_start": self.token_start,
            "token_end": self.token_end,
            "shard_id": self.shard_id,
        }

    @property
    def object_id(self) -> str:
        return f"kv-{sha256_json(self.content_fields())}"

    @property
    def lineage_record_id(self) -> str:
        return f"kv-record-{sha256_json(self.canonical_fields())}"

    @property
    def compatibility_key(self) -> tuple[str | int, ...]:
        return (
            self.tenant_id,
            self.model_id,
            self.model_revision,
            self.kv_dtype,
            self.kv_abi,
            self.kv_layout,
            self.tp_size,
            self.pp_size,
            self.block_size_tokens,
            self.shard_id,
        )
