"""Generate source-locked, fail-closed Qwen3 KV layout artifacts.

This module derives ordinary full-attention page bytes from the pinned vLLM
``AttentionSpec`` rule.  It deliberately does not import vLLM or torch: a live
vLLM ``CacheSpec``/CUDA observation is a later differential/physical gate, not
something an E1 static generator may claim.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from moonkvsim.common.hash import sha256_json
from moonkvsim.integration.vllm.kv_layout import (
    AttentionLayerSpec,
    StageBlockLayout,
    build_stage_block_layouts,
    local_num_kv_heads,
)

ContextMode = Literal["native", "proposed-yarn-128k"]

_SCHEMA = "moonkvsim.kv_layout.v1"
_QWEN_MODEL_ID = "Qwen/Qwen3-8B"
_QWEN_ARCHITECTURE = "Qwen3ForCausalLM"
_REQUIRED_VLLM_SOURCES = (
    "vllm/v1/kv_cache_interface.py",
    "vllm/config/model.py",
    "vllm/distributed/utils.py",
)
_DTYPE_BYTES = {
    "bfloat16": 2,
    "float16": 2,
    "float32": 4,
}


@dataclass(frozen=True, slots=True)
class LockedLayoutInputs:
    """Verified source inputs without machine-specific paths in the artifact."""

    model_id: str
    model_revision: str
    model_config: Mapping[str, Any]
    model_weights_bytes: int
    model_files: tuple[Mapping[str, str], ...]
    tokenizer: Mapping[str, Any]
    proposed_context: Mapping[str, Any]
    model_card: Mapping[str, Any]
    vllm_commit: str
    vllm_files: tuple[Mapping[str, str], ...]
    source_verification: Mapping[str, str]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{location}: expected object")
    return value


def _sequence(value: object, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{location}: expected array")
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{location}: expected non-empty string")
    return value


def _integer(value: object, location: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{location}: expected integer")
    return value


def _git_object_bytes(repository: Path, commit: str, source_path: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), "show", f"{commit}:{source_path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise ValueError(f"cannot read pinned Git object {source_path}: {detail}")
    return result.stdout


def _locked_file_entries(raw: object, location: str) -> tuple[Mapping[str, str], ...]:
    entries: list[Mapping[str, str]] = []
    for index, item in enumerate(_sequence(raw, location)):
        entry = _mapping(item, f"{location}[{index}]")
        path = _string(entry.get("path"), f"{location}[{index}].path")
        sha256 = _string(entry.get("sha256"), f"{location}[{index}].sha256")
        normalized = {"path": path, "sha256": sha256}
        git_blob = entry.get("git_blob")
        if git_blob is not None:
            normalized["git_blob"] = _string(
                git_blob, f"{location}[{index}].git_blob"
            )
        entries.append(normalized)
    return tuple(sorted(entries, key=lambda item: item["path"]))


def load_locked_qwen3_layout_inputs(source_lock_path: Path) -> LockedLayoutInputs:
    """Read and live-verify the model/tokenizer and pinned vLLM Git objects."""

    try:
        source_lock = json.loads(source_lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read source lock {source_lock_path}: {error}") from error
    root = _mapping(source_lock, "$")
    if root.get("schema") != "moonkvsim.source-lock.v1":
        raise ValueError("$.schema: expected moonkvsim.source-lock.v1")

    model = _mapping(root.get("model_tokenizer"), "$.model_tokenizer")
    model_id = _string(model.get("model_id"), "$.model_tokenizer.model_id")
    if model_id != _QWEN_MODEL_ID:
        raise ValueError(f"only {_QWEN_MODEL_ID} is supported by this generator")
    revision = _string(model.get("revision"), "$.model_tokenizer.revision")
    snapshot_path = Path(
        _string(model.get("snapshot_path"), "$.model_tokenizer.snapshot_path")
    )
    model_files = _locked_file_entries(
        model.get("files"), "$.model_tokenizer.files"
    )
    for entry in model_files:
        actual_sha256 = _sha256_file(snapshot_path / entry["path"])
        if actual_sha256 != entry["sha256"]:
            raise ValueError(
                f"model file hash mismatch for {entry['path']}: "
                f"expected {entry['sha256']}, got {actual_sha256}"
            )

    config_path = snapshot_path / "config.json"
    weight_index_path = snapshot_path / "model.safetensors.index.json"
    tokenizer_config_path = snapshot_path / "tokenizer_config.json"
    try:
        actual_config = _mapping(
            json.loads(config_path.read_text(encoding="utf-8")), "config.json"
        )
        weight_index = _mapping(
            json.loads(weight_index_path.read_text(encoding="utf-8")),
            "model.safetensors.index.json",
        )
        actual_tokenizer_config = _mapping(
            json.loads(tokenizer_config_path.read_text(encoding="utf-8")),
            "tokenizer_config.json",
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot parse locked model metadata: {error}") from error
    weight_index_metadata = _mapping(
        weight_index.get("metadata"),
        "model.safetensors.index.json.metadata",
    )
    model_weights_bytes = _integer(
        weight_index_metadata.get("total_size"),
        "model.safetensors.index.json.metadata.total_size",
    )
    if model_weights_bytes <= 0:
        raise ValueError(
            "model.safetensors.index.json.metadata.total_size must be positive"
        )

    locked_config = _mapping(model.get("model_config"), "$.model_tokenizer.model_config")
    config_field_mapping = {
        "model_type": "model_type",
        "dtype": "torch_dtype",
        "hidden_size": "hidden_size",
        "num_hidden_layers": "num_hidden_layers",
        "num_attention_heads": "num_attention_heads",
        "num_key_value_heads": "num_key_value_heads",
        "head_dim": "head_dim",
        "max_position_embeddings": "max_position_embeddings",
        "rope_theta": "rope_theta",
        "rope_scaling": "rope_scaling",
    }
    for locked_name, actual_name in config_field_mapping.items():
        if locked_config.get(locked_name) != actual_config.get(actual_name):
            raise ValueError(
                f"locked model_config.{locked_name} disagrees with config.json."
                f"{actual_name}"
            )

    tokenizer = _mapping(model.get("tokenizer"), "$.model_tokenizer.tokenizer")
    for key in ("tokenizer_class", "model_max_length"):
        if tokenizer.get(key) != actual_tokenizer_config.get(key):
            raise ValueError(f"locked tokenizer.{key} disagrees with tokenizer_config.json")
    chat_template = _string(
        actual_tokenizer_config.get("chat_template"),
        "tokenizer_config.json.chat_template",
    )
    if _sha256_bytes(chat_template.encode()) != tokenizer.get("chat_template_sha256"):
        raise ValueError("locked chat-template fingerprint disagrees with tokenizer config")

    repositories = _mapping(root.get("repositories"), "$.repositories")
    vllm = _mapping(repositories.get("vllm"), "$.repositories.vllm")
    repository = Path(_string(vllm.get("repository"), "$.repositories.vllm.repository"))
    commit = _string(vllm.get("commit"), "$.repositories.vllm.commit")
    all_vllm_files = _locked_file_entries(vllm.get("files"), "$.repositories.vllm.files")
    files_by_path = {entry["path"]: entry for entry in all_vllm_files}
    verified_vllm_files: list[Mapping[str, str]] = []
    for source_path in _REQUIRED_VLLM_SOURCES:
        vllm_entry = files_by_path.get(source_path)
        if vllm_entry is None:
            raise ValueError(f"source lock is missing required vLLM file {source_path}")
        source_bytes = _git_object_bytes(repository, commit, source_path)
        actual_sha256 = _sha256_bytes(source_bytes)
        if actual_sha256 != vllm_entry["sha256"]:
            raise ValueError(
                f"vLLM Git-object hash mismatch for {source_path}: "
                f"expected {vllm_entry['sha256']}, got {actual_sha256}"
            )
        verified_vllm_files.append(vllm_entry)

    return LockedLayoutInputs(
        model_id=model_id,
        model_revision=revision,
        model_config=actual_config,
        model_weights_bytes=model_weights_bytes,
        model_files=model_files,
        tokenizer=dict(tokenizer),
        proposed_context=dict(
            _mapping(model.get("context_128k"), "$.model_tokenizer.context_128k")
        ),
        model_card=dict(
            _mapping(model.get("official_model_card"), "$.model_tokenizer.official_model_card")
        ),
        vllm_commit=commit,
        vllm_files=tuple(verified_vllm_files),
        source_verification={
            "local_model_and_tokenizer_files": "pass",
            "pinned_vllm_git_objects": "pass",
        },
    )


def resolve_pp_layer_partitions(
    num_hidden_layers: int,
    pp_size: int,
    explicit_partition: Sequence[int] | None = None,
) -> tuple[int, ...]:
    """Mirror pinned vLLM ``get_pp_indices`` and validate its resolved result."""

    if num_hidden_layers <= 0 or pp_size <= 0:
        raise ValueError("num_hidden_layers and pp_size must be positive")
    if pp_size > num_hidden_layers:
        raise ValueError("PP size cannot exceed the number of hidden layers")
    if explicit_partition is not None:
        partitions = tuple(explicit_partition)
        if len(partitions) != pp_size:
            raise ValueError("explicit PP partition length must equal pp_size")
        if any(value <= 0 for value in partitions):
            raise ValueError("explicit PP partition entries must be positive")
        if sum(partitions) != num_hidden_layers:
            raise ValueError("explicit PP partition must cover every hidden layer")
        return partitions

    layers_per_partition = num_hidden_layers // pp_size
    default_partitions = [layers_per_partition for _ in range(pp_size)]
    remaining_layers = num_hidden_layers % pp_size
    if remaining_layers:
        for index in range(2, remaining_layers + 2):
            default_partitions[-index] += 1
    return tuple(default_partitions)


def _model_dimensions(model_config: Mapping[str, Any], tp_size: int) -> dict[str, Any]:
    if model_config.get("model_type") != "qwen3":
        raise ValueError("only a qwen3 model config is supported")
    architectures = model_config.get("architectures")
    if not isinstance(architectures, list) or _QWEN_ARCHITECTURE not in architectures:
        raise ValueError(f"model config must declare {_QWEN_ARCHITECTURE}")
    if model_config.get("sliding_window") is not None or model_config.get(
        "use_sliding_window", False
    ):
        raise ValueError(
            "sliding/hybrid attention requires an explicit runtime CacheSpec group layout"
        )
    for key in ("layer_types", "layers_block_type", "attention_types"):
        if key in model_config:
            raise ValueError(
                f"{key} requires an explicit runtime CacheSpec group layout"
            )

    num_hidden_layers = _integer(
        model_config.get("num_hidden_layers"), "config.num_hidden_layers"
    )
    total_attention_heads = _integer(
        model_config.get("num_attention_heads"), "config.num_attention_heads"
    )
    total_kv_heads = _integer(
        model_config.get("num_key_value_heads"), "config.num_key_value_heads"
    )
    hidden_size = _integer(model_config.get("hidden_size"), "config.hidden_size")
    if total_attention_heads <= 0 or total_attention_heads % tp_size != 0:
        raise ValueError("attention heads must divide evenly across TP ranks")
    head_size_value = model_config.get("head_dim")
    if head_size_value is None:
        if hidden_size % total_attention_heads != 0:
            raise ValueError("cannot derive an integral attention head size")
        head_size = hidden_size // total_attention_heads
    else:
        head_size = _integer(head_size_value, "config.head_dim")
    if head_size <= 0 or total_kv_heads <= 0 or num_hidden_layers <= 0:
        raise ValueError("model attention dimensions must be positive")

    dtype = _string(
        model_config.get("torch_dtype", model_config.get("dtype")),
        "config.torch_dtype",
    )
    dtype_bytes = _DTYPE_BYTES.get(dtype)
    if dtype_bytes is None:
        raise ValueError(
            f"KV dtype {dtype!r} needs an explicit runtime CacheSpec layout"
        )
    return {
        "num_hidden_layers": num_hidden_layers,
        "total_attention_heads": total_attention_heads,
        "total_kv_heads": total_kv_heads,
        "local_kv_heads": local_num_kv_heads(total_kv_heads, tp_size),
        "hidden_size": hidden_size,
        "head_size": head_size,
        "kv_dtype": dtype,
        "dtype_bytes": dtype_bytes,
    }


def _context_document(inputs: LockedLayoutInputs, mode: ContextMode) -> dict[str, Any]:
    native_max = _integer(
        inputs.model_config.get("max_position_embeddings"),
        "config.max_position_embeddings",
    )
    native_rope = inputs.model_config.get("rope_scaling")
    if native_rope is not None:
        raise ValueError("locked native config must keep rope_scaling=null")
    if mode == "native":
        return {
            "mode": "native_model_config",
            "configuration_status": "locked_native",
            "max_model_len_tokens": native_max,
            "rope_scaling": None,
            "source": "config.json:max_position_embeddings",
            "formal_context_validation": "not_run",
        }
    if mode != "proposed-yarn-128k":
        raise ValueError(f"unsupported context mode: {mode}")

    proposed = inputs.proposed_context
    required = {
        "status": "proposed_unvalidated",
        "readiness": "BLOCKED",
        "engine": "vllm",
        "vllm_revision": inputs.vllm_commit,
        "max_model_len": 131072,
        "model_card_is_experiment_evidence": False,
        "formal_128k_allowed": False,
    }
    for key, expected in required.items():
        if proposed.get(key) != expected:
            raise ValueError(f"proposed context {key} must remain {expected!r}")
    rope_scaling = _mapping(proposed.get("rope_scaling"), "context_128k.rope_scaling")
    expected_rope = {
        "rope_type": "yarn",
        "factor": 4.0,
        "original_max_position_embeddings": 32768,
    }
    if rope_scaling != expected_rope:
        raise ValueError("proposed 128K YaRN settings disagree with the source lock")
    physical = _mapping(
        proposed.get("physical_validation"), "context_128k.physical_validation"
    )
    if physical.get("completed") is not False or physical.get("evidence_path") is not None:
        raise ValueError("proposed 128K context cannot be promoted without physical evidence")
    return {
        "mode": "proposed_yarn_128k",
        "configuration_status": "proposed_unvalidated",
        "max_model_len_tokens": 131072,
        "rope_scaling": dict(rope_scaling),
        "source": "fixed_revision_model_card_configuration_guidance",
        "model_card_sha256": inputs.model_card.get("sha256"),
        "static_yarn_short_context_risk": proposed.get(
            "static_yarn_short_context_risk"
        ),
        "formal_context_validation": "blocked_pending_long_and_short_context_physical_runs",
    }


def _capacity_document(
    layout: StageBlockLayout,
    max_model_len_tokens: int,
) -> dict[str, Any]:
    block_count = (max_model_len_tokens + layout.block_size_tokens - 1) // (
        layout.block_size_tokens
    )
    physical_token_slots = block_count * layout.block_size_tokens
    return {
        "basis": "single_sequence_max_model_len_footprint",
        "max_model_len_tokens": max_model_len_tokens,
        "required_block_count_per_layer_group": block_count,
        "physical_token_slots": physical_token_slots,
        "last_block_unused_token_slots": physical_token_slots - max_model_len_tokens,
        "tensor_payload_bytes": block_count * layout.tensor_payload_bytes,
        "auxiliary_payload_bytes": block_count * layout.auxiliary_payload_bytes,
        "layout_padding_bytes": block_count * layout.layout_padding_bytes,
        "allocator_metadata_bytes": block_count * layout.allocator_metadata_bytes,
        "internal_fragmentation_bytes": (
            block_count * layout.internal_fragmentation_bytes
        ),
        "allocated_bytes": block_count * layout.allocated_bytes,
        "runtime_gpu_cache_capacity_blocks": None,
        "runtime_gpu_cache_capacity_bytes": None,
        "runtime_capacity_status": "not_observed_requires_pinned_vllm_runtime",
    }


def _fingerprinted(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    return {**payload, "fingerprint": sha256_json(payload)}


def build_qwen3_kv_layout_document(
    inputs: LockedLayoutInputs,
    *,
    context_mode: ContextMode,
    tp_size: int,
    pp_size: int,
    block_size_tokens: int,
    allocator_alignment_bytes: int,
    allocator_metadata_bytes_per_layer_block: int = 0,
    pp_layer_partition: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Build a deterministic E1 artifact for one explicit TP/PP placement."""

    if tp_size <= 0 or pp_size <= 0 or block_size_tokens <= 0:
        raise ValueError("TP, PP, and block size must be positive")
    if allocator_alignment_bytes <= 0:
        raise ValueError("allocator alignment must be positive")
    if allocator_metadata_bytes_per_layer_block < 0:
        raise ValueError("allocator metadata bytes must be non-negative")

    dimensions = _model_dimensions(inputs.model_config, tp_size)
    num_hidden_layers = int(dimensions["num_hidden_layers"])
    partitions = resolve_pp_layer_partitions(
        num_hidden_layers, pp_size, pp_layer_partition
    )
    context = _context_document(inputs, context_mode)
    max_model_len_tokens = int(context["max_model_len_tokens"])

    stage_for_layer: list[int] = []
    for pp_stage, layer_count in enumerate(partitions):
        stage_for_layer.extend([pp_stage] * layer_count)
    layers = tuple(
        AttentionLayerSpec(
            layer_name=f"model.layers.{layer_index}.self_attn",
            layer_index=layer_index,
            pp_stage=stage_for_layer[layer_index],
            total_num_kv_heads=int(dimensions["total_kv_heads"]),
            head_size=int(dimensions["head_size"]),
            dtype_bytes=int(dimensions["dtype_bytes"]),
            block_size_tokens=block_size_tokens,
            tensor_parallel_size=tp_size,
            allocator_metadata_bytes_per_block=(
                allocator_metadata_bytes_per_layer_block
            ),
        )
        for layer_index in range(num_hidden_layers)
    )

    stage_rank_layouts: list[dict[str, Any]] = []
    for tp_rank in range(tp_size):
        layouts = build_stage_block_layouts(
            layers,
            tensor_parallel_rank=tp_rank,
            allocator_alignment_bytes=allocator_alignment_bytes,
        )
        for layout in layouts:
            entry = {
                "pp_stage": layout.pp_stage,
                "tensor_parallel_rank": tp_rank,
                "global_rank_within_dp": layout.pp_stage * tp_size + tp_rank,
                "layer_start_inclusive": layout.layer_indices[0],
                "layer_end_exclusive": layout.layer_indices[-1] + 1,
                "layer_count": len(layout.layer_indices),
                "layer_indices": list(layout.layer_indices),
                "layer_names": list(layout.layer_names),
                "cache_spec": {
                    "kind": "full_attention",
                    "cache_group_id": 0,
                    "block_size_tokens": block_size_tokens,
                    "total_num_kv_heads": dimensions["total_kv_heads"],
                    "local_num_kv_heads": dimensions["local_kv_heads"],
                    "head_size_k": dimensions["head_size"],
                    "head_size_v": dimensions["head_size"],
                    "kv_dtype": dimensions["kv_dtype"],
                    "dtype_bytes": dimensions["dtype_bytes"],
                    "kv_quant_mode": "none",
                    "page_size_padded_bytes_per_layer": None,
                    "auxiliary_payload_bytes_per_layer_block": 0,
                },
                "block": layout.to_dict(),
                "capacity": _capacity_document(layout, max_model_len_tokens),
            }
            stage_rank_layouts.append(_fingerprinted(entry))
    stage_rank_layouts.sort(
        key=lambda entry: (
            int(entry["pp_stage"]),
            int(entry["tensor_parallel_rank"]),
        )
    )

    model_file_hashes = {entry["path"]: entry["sha256"] for entry in inputs.model_files}
    tokenizer_fingerprint_fields = {
        "revision": inputs.model_revision,
        "tokenizer_json_sha256": model_file_hashes["tokenizer.json"],
        "tokenizer_config_sha256": model_file_hashes["tokenizer_config.json"],
        "chat_template_sha256": inputs.tokenizer["chat_template_sha256"],
    }
    document: dict[str, Any] = {
        "schema": _SCHEMA,
        "model": {
            "id": inputs.model_id,
            "revision": inputs.model_revision,
            "weights_bytes": inputs.model_weights_bytes,
            "config_sha256": model_file_hashes["config.json"],
            "tokenizer_json_sha256": model_file_hashes["tokenizer.json"],
            "tokenizer_config_sha256": model_file_hashes["tokenizer_config.json"],
            "chat_template_sha256": inputs.tokenizer["chat_template_sha256"],
            "tokenizer_fingerprint": sha256_json(tokenizer_fingerprint_fields),
            "tokenizer_class": inputs.tokenizer["tokenizer_class"],
            "tokenizer_model_max_length": inputs.tokenizer["model_max_length"],
            "model_type": inputs.model_config["model_type"],
            "architecture": _QWEN_ARCHITECTURE,
            "hidden_size": dimensions["hidden_size"],
            "num_hidden_layers": dimensions["num_hidden_layers"],
            "num_attention_heads": dimensions["total_attention_heads"],
            "total_num_kv_heads": dimensions["total_kv_heads"],
            "head_size": dimensions["head_size"],
            "native_max_position_embeddings": inputs.model_config[
                "max_position_embeddings"
            ],
            "native_rope_scaling": inputs.model_config["rope_scaling"],
        },
        "context": context,
        "parallelism": {
            "tensor_parallel_size": tp_size,
            "pipeline_parallel_size": pp_size,
            "rank_layout_order": "DP_x_PP_x_TP",
            "dp_replication": "layout_repeats_identically_for_each_dp_rank",
            "pp_layer_partition": list(partitions),
            "pp_partition_source": (
                "explicit_VLLM_PP_LAYER_PARTITION_equivalent"
                if pp_layer_partition is not None
                else "pinned_vllm_get_pp_indices_default"
            ),
        },
        "allocator": {
            "alignment_bytes": allocator_alignment_bytes,
            "metadata_bytes_per_layer_block": (
                allocator_metadata_bytes_per_layer_block
            ),
            "input_source": "explicit_generator_arguments",
            "runtime_allocator_differential_validation": "not_run",
        },
        "cache_groups": [
            {
                "cache_group_id": 0,
                "kind": "uniform_full_attention",
                "layer_indices": list(range(num_hidden_layers)),
                "runtime_cache_spec_observed": False,
            }
        ],
        "stage_rank_layouts": stage_rank_layouts,
        "sources": {
            "model_files": [dict(entry) for entry in inputs.model_files],
            "vllm": {
                "commit": inputs.vllm_commit,
                "files": [dict(entry) for entry in inputs.vllm_files],
                "semantic_rules": [
                    "AttentionSpec.real_page_size_bytes",
                    "FullAttentionSpec.real_page_size_bytes",
                    "ModelConfig.get_num_kv_heads",
                    "get_pp_indices",
                ],
            },
            "source_verification": dict(inputs.source_verification),
        },
        "evidence": {
            "class": "E1",
            "configuration_status": context["configuration_status"],
            "static_source_derivation": "pass",
            "runtime_vllm_cache_spec_observed": False,
            "vllm_cache_spec_block_byte_differential": "not_run",
            "cuda_physical_validation": "not_run",
            "formal_use_allowed": False,
        },
    }
    return _fingerprinted(document)


def canonical_kv_layout_bytes(document: Mapping[str, Any]) -> bytes:
    """Serialize an artifact deterministically for byte-for-byte audits."""

    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def audit_kv_layout_document(document: Mapping[str, Any]) -> None:
    """Audit fingerprints and the mandatory E1 evidence boundary."""

    if document.get("schema") != _SCHEMA:
        raise ValueError(f"schema must be {_SCHEMA}")
    fingerprint = document.get("fingerprint")
    payload = dict(document)
    payload.pop("fingerprint", None)
    if fingerprint != sha256_json(payload):
        raise ValueError("top-level KV layout fingerprint mismatch")
    model = _mapping(document.get("model"), "$.model")
    if _integer(model.get("weights_bytes"), "$.model.weights_bytes") <= 0:
        raise ValueError("$.model.weights_bytes must be positive")
    evidence = _mapping(document.get("evidence"), "$.evidence")
    expected_boundary = {
        "class": "E1",
        "runtime_vllm_cache_spec_observed": False,
        "vllm_cache_spec_block_byte_differential": "not_run",
        "cuda_physical_validation": "not_run",
        "formal_use_allowed": False,
    }
    for key, expected in expected_boundary.items():
        if evidence.get(key) != expected:
            raise ValueError(f"evidence.{key} must remain {expected!r}")
    for index, raw_entry in enumerate(
        _sequence(document.get("stage_rank_layouts"), "$.stage_rank_layouts")
    ):
        entry = _mapping(raw_entry, f"$.stage_rank_layouts[{index}]")
        entry_fingerprint = entry.get("fingerprint")
        entry_payload = dict(entry)
        entry_payload.pop("fingerprint", None)
        if entry_fingerprint != sha256_json(entry_payload):
            raise ValueError(f"stage/rank layout {index} fingerprint mismatch")
        capacity = _mapping(entry.get("capacity"), f"$.stage_rank_layouts[{index}].capacity")
        if capacity.get("runtime_gpu_cache_capacity_blocks") is not None:
            raise ValueError("E1 artifact cannot claim runtime GPU cache capacity")
        if capacity.get("runtime_gpu_cache_capacity_bytes") is not None:
            raise ValueError("E1 artifact cannot claim runtime GPU cache bytes")
