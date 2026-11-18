"""Byte-exact, tensor-free representation of pinned vLLM KV cache specs.

The ordinary attention formula mirrors ``AttentionSpec.real_page_size_bytes``
from the source-locked vLLM tree.  Special layouts (MLA, hybrid groups,
quantized auxiliary tensors, and shared tensors) must be supplied as explicit
per-layer measurements instead of being guessed through this module.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from moonkvsim.common.hash import sha256_json


def round_up(value: int, alignment: int) -> int:
    """Round ``value`` up without accepting invalid allocator parameters."""

    if value < 0:
        raise ValueError("value must be non-negative")
    if alignment <= 0:
        raise ValueError("alignment must be positive")
    return ((value + alignment - 1) // alignment) * alignment


def local_num_kv_heads(total_num_kv_heads: int, tensor_parallel_size: int) -> int:
    """Mirror pinned ``ModelConfig.get_num_kv_heads`` replication semantics."""

    if total_num_kv_heads <= 0 or tensor_parallel_size <= 0:
        raise ValueError("KV heads and tensor-parallel size must be positive")
    return max(1, total_num_kv_heads // tensor_parallel_size)


@dataclass(frozen=True, slots=True)
class AttentionLayerSpec:
    """Resolved ordinary MHA/GQA layer spec for one physical TP rank."""

    layer_name: str
    pp_stage: int
    total_num_kv_heads: int
    head_size: int
    dtype_bytes: int
    block_size_tokens: int
    tensor_parallel_size: int
    auxiliary_payload_bytes_per_block: int = 0
    page_size_padded_bytes: int | None = None
    allocator_metadata_bytes_per_block: int = 0
    layer_index: int | None = None

    def __post_init__(self) -> None:
        if not self.layer_name:
            raise ValueError("layer_name must be non-empty")
        positive = (
            self.total_num_kv_heads,
            self.head_size,
            self.dtype_bytes,
            self.block_size_tokens,
            self.tensor_parallel_size,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("attention dimensions and block size must be positive")
        if self.pp_stage < 0:
            raise ValueError("pp_stage must be non-negative")
        if self.layer_index is not None and self.layer_index < 0:
            raise ValueError("layer_index must be non-negative when supplied")
        if self.auxiliary_payload_bytes_per_block < 0:
            raise ValueError("auxiliary payload bytes must be non-negative")
        if self.allocator_metadata_bytes_per_block < 0:
            raise ValueError("allocator metadata bytes must be non-negative")
        if (
            self.page_size_padded_bytes is not None
            and self.page_size_padded_bytes < self.real_page_size_bytes
        ):
            raise ValueError("padded page size cannot be smaller than real page size")

    @property
    def local_num_kv_heads(self) -> int:
        return local_num_kv_heads(self.total_num_kv_heads, self.tensor_parallel_size)

    @property
    def tensor_payload_bytes(self) -> int:
        # K and V are separate tensors, hence the leading factor of two.
        return (
            2
            * self.block_size_tokens
            * self.local_num_kv_heads
            * self.head_size
            * self.dtype_bytes
        )

    @property
    def real_page_size_bytes(self) -> int:
        return self.tensor_payload_bytes + self.auxiliary_payload_bytes_per_block

    @property
    def page_size_bytes(self) -> int:
        return self.page_size_padded_bytes or self.real_page_size_bytes

    @property
    def layout_padding_bytes(self) -> int:
        return self.page_size_bytes - self.real_page_size_bytes


@dataclass(frozen=True, slots=True)
class StageBlockLayout:
    """One vLLM logical block's physical bytes on one PP-stage/TP-rank GPU."""

    pp_stage: int
    tensor_parallel_rank: int
    block_size_tokens: int
    layer_names: tuple[str, ...]
    layer_indices: tuple[int, ...]
    tensor_payload_bytes: int
    auxiliary_payload_bytes: int
    payload_bytes: int
    layout_padding_bytes: int
    allocator_metadata_bytes: int
    requested_bytes: int
    internal_fragmentation_bytes: int
    allocated_bytes: int
    allocator_alignment_bytes: int

    def __post_init__(self) -> None:
        if self.pp_stage < 0 or self.tensor_parallel_rank < 0:
            raise ValueError("stage and rank must be non-negative")
        if self.block_size_tokens <= 0 or self.allocator_alignment_bytes <= 0:
            raise ValueError("block size and allocator alignment must be positive")
        if not self.layer_names:
            raise ValueError("a stage layout must contain at least one layer")
        if len(self.layer_indices) != len(self.layer_names):
            raise ValueError("layer indices and names must have the same length")
        if tuple(sorted(self.layer_indices)) != self.layer_indices:
            raise ValueError("layer indices must be sorted")
        if len(set(self.layer_indices)) != len(self.layer_indices):
            raise ValueError("layer indices must be unique")
        counts = (
            self.tensor_payload_bytes,
            self.auxiliary_payload_bytes,
            self.payload_bytes,
            self.layout_padding_bytes,
            self.allocator_metadata_bytes,
            self.requested_bytes,
            self.internal_fragmentation_bytes,
            self.allocated_bytes,
        )
        if any(value < 0 for value in counts):
            raise ValueError("layout byte counts must be non-negative")
        if self.payload_bytes != (
            self.tensor_payload_bytes + self.auxiliary_payload_bytes
        ):
            raise ValueError("payload bytes must equal tensor plus auxiliary payload")
        if self.requested_bytes != self.payload_bytes + self.layout_padding_bytes:
            raise ValueError("requested bytes must equal payload plus layout padding")
        if self.allocated_bytes != (
            self.requested_bytes
            + self.allocator_metadata_bytes
            + self.internal_fragmentation_bytes
        ):
            raise ValueError("allocated bytes must be fully explained")

    @property
    def fingerprint(self) -> str:
        return sha256_json(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fingerprint"] = self.fingerprint
        return data


def build_stage_block_layouts(
    layers: Iterable[AttentionLayerSpec],
    *,
    tensor_parallel_rank: int,
    allocator_alignment_bytes: int,
) -> tuple[StageBlockLayout, ...]:
    """Resolve one layout per PP stage and fail on ambiguous mixed block sizes."""

    if tensor_parallel_rank < 0:
        raise ValueError("tensor_parallel_rank must be non-negative")
    if allocator_alignment_bytes <= 0:
        raise ValueError("allocator_alignment_bytes must be positive")

    layer_list = list(layers)
    if not layer_list:
        raise ValueError("at least one layer is required")
    supplied_indices = [item.layer_index for item in layer_list]
    if all(index is None for index in supplied_indices):
        ordered_names = sorted(item.layer_name for item in layer_list)
        resolved_index_by_name = {
            layer_name: index for index, layer_name in enumerate(ordered_names)
        }
    elif any(index is None for index in supplied_indices):
        raise ValueError("layer_index must be supplied for either every layer or none")
    else:
        resolved_index_by_name = {}
        for item in layer_list:
            if item.layer_index is None:  # Narrowed above; retained for type safety.
                raise AssertionError("unreachable missing layer index")
            resolved_index_by_name[item.layer_name] = item.layer_index

    by_stage: dict[int, list[AttentionLayerSpec]] = {}
    seen_names: set[str] = set()
    seen_indices: set[int] = set()
    for layer in layer_list:
        if tensor_parallel_rank >= layer.tensor_parallel_size:
            raise ValueError("tensor_parallel_rank is outside the layer TP group")
        resolved_index = resolved_index_by_name[layer.layer_name]
        if layer.layer_name in seen_names:
            raise ValueError(f"duplicate layer name: {layer.layer_name}")
        if resolved_index in seen_indices:
            raise ValueError(f"duplicate layer index: {resolved_index}")
        seen_names.add(layer.layer_name)
        seen_indices.add(resolved_index)
        by_stage.setdefault(layer.pp_stage, []).append(layer)

    layouts: list[StageBlockLayout] = []
    for pp_stage in sorted(by_stage):
        stage_layers = sorted(
            by_stage[pp_stage],
            key=lambda item: (resolved_index_by_name[item.layer_name], item.layer_name),
        )
        block_sizes = {item.block_size_tokens for item in stage_layers}
        if len(block_sizes) != 1:
            raise ValueError(
                "hybrid block sizes require an explicit CacheSpec group layout"
            )
        tensor_payload = sum(item.tensor_payload_bytes for item in stage_layers)
        auxiliary_payload = sum(
            item.auxiliary_payload_bytes_per_block for item in stage_layers
        )
        payload = tensor_payload + auxiliary_payload
        padding = sum(item.layout_padding_bytes for item in stage_layers)
        metadata = sum(item.allocator_metadata_bytes_per_block for item in stage_layers)
        requested = payload + padding
        allocated = round_up(requested + metadata, allocator_alignment_bytes)
        fragmentation = allocated - requested - metadata
        layouts.append(
            StageBlockLayout(
                pp_stage=pp_stage,
                tensor_parallel_rank=tensor_parallel_rank,
                block_size_tokens=block_sizes.pop(),
                layer_names=tuple(item.layer_name for item in stage_layers),
                layer_indices=tuple(
                    resolved_index_by_name[item.layer_name] for item in stage_layers
                ),
                tensor_payload_bytes=tensor_payload,
                auxiliary_payload_bytes=auxiliary_payload,
                payload_bytes=payload,
                layout_padding_bytes=padding,
                allocator_metadata_bytes=metadata,
                requested_bytes=requested,
                internal_fragmentation_bytes=fragmentation,
                allocated_bytes=allocated,
                allocator_alignment_bytes=allocator_alignment_bytes,
            )
        )
    return tuple(layouts)
