import json
from pathlib import Path

import pytest

from moonkvsim.common.hash import sha256_json
from moonkvsim.integration.vllm.kv_layout import (
    AttentionLayerSpec,
    build_stage_block_layouts,
    local_num_kv_heads,
)
from moonkvsim.integration.vllm.kv_layout_artifact import (
    LockedLayoutInputs,
    audit_kv_layout_document,
    build_qwen3_kv_layout_document,
    canonical_kv_layout_bytes,
    resolve_pp_layer_partitions,
)


def _locked_inputs() -> LockedLayoutInputs:
    revision = "b" * 40
    vllm_commit = "c" * 40
    return LockedLayoutInputs(
        model_id="Qwen/Qwen3-8B",
        model_revision=revision,
        model_config={
            "architectures": ["Qwen3ForCausalLM"],
            "model_type": "qwen3",
            "hidden_size": 4096,
            "num_hidden_layers": 4,
            "num_attention_heads": 32,
            "num_key_value_heads": 2,
            "head_dim": 128,
            "torch_dtype": "bfloat16",
            "max_position_embeddings": 40960,
            "rope_scaling": None,
            "sliding_window": None,
            "use_sliding_window": False,
        },
        model_weights_bytes=16_381_470_720,
        model_files=(
            {"path": "config.json", "sha256": "1" * 64},
            {"path": "tokenizer.json", "sha256": "2" * 64},
            {"path": "tokenizer_config.json", "sha256": "3" * 64},
        ),
        tokenizer={
            "chat_template_sha256": "4" * 64,
            "tokenizer_class": "Qwen2Tokenizer",
            "model_max_length": 131072,
        },
        proposed_context={
            "status": "proposed_unvalidated",
            "readiness": "BLOCKED",
            "engine": "vllm",
            "vllm_revision": vllm_commit,
            "max_model_len": 131072,
            "model_card_is_experiment_evidence": False,
            "formal_128k_allowed": False,
            "rope_scaling": {
                "rope_type": "yarn",
                "factor": 4.0,
                "original_max_position_embeddings": 32768,
            },
            "static_yarn_short_context_risk": "test risk",
            "physical_validation": {"completed": False, "evidence_path": None},
        },
        model_card={"sha256": "5" * 64},
        vllm_commit=vllm_commit,
        vllm_files=(
            {
                "path": "vllm/v1/kv_cache_interface.py",
                "sha256": "6" * 64,
            },
            {"path": "vllm/config/model.py", "sha256": "7" * 64},
            {"path": "vllm/distributed/utils.py", "sha256": "8" * 64},
        ),
        source_verification={
            "local_model_and_tokenizer_files": "pass",
            "pinned_vllm_git_objects": "pass",
        },
    )


def test_qwen_gqa_page_bytes_and_stage_accounting() -> None:
    layers = [
        AttentionLayerSpec(
            layer_name=f"model.layers.{index}.self_attn",
            layer_index=index,
            pp_stage=index // 2,
            total_num_kv_heads=8,
            head_size=128,
            dtype_bytes=2,
            block_size_tokens=16,
            tensor_parallel_size=4,
            allocator_metadata_bytes_per_block=32,
        )
        for index in range(4)
    ]

    layouts = build_stage_block_layouts(
        layers,
        tensor_parallel_rank=3,
        allocator_alignment_bytes=4096,
    )

    assert len(layouts) == 2
    # 2 layers * K/V * 16 tokens * 2 local KV heads * 128 dim * bf16.
    assert layouts[0].payload_bytes == 32_768
    assert layouts[0].requested_bytes == 32_768
    assert layouts[0].allocator_metadata_bytes == 64
    assert layouts[0].internal_fragmentation_bytes == 4_032
    assert layouts[0].allocated_bytes == 36_864
    assert len(layouts[0].fingerprint) == 64


def test_kv_heads_replicate_when_tp_exceeds_total_heads() -> None:
    assert local_num_kv_heads(2, 8) == 1
    assert local_num_kv_heads(8, 4) == 2
    assert local_num_kv_heads(1, 8) == 1  # MQA replication on every TP rank.


def test_page_padding_is_distinct_from_allocator_fragmentation() -> None:
    layer = AttentionLayerSpec(
        layer_name="layer.0",
        layer_index=0,
        pp_stage=0,
        total_num_kv_heads=1,
        head_size=3,
        dtype_bytes=2,
        block_size_tokens=2,
        tensor_parallel_size=1,
        auxiliary_payload_bytes_per_block=4,
        page_size_padded_bytes=32,
    )
    [layout] = build_stage_block_layouts(
        [layer], tensor_parallel_rank=0, allocator_alignment_bytes=64
    )
    assert layout.payload_bytes == 28
    assert layout.layout_padding_bytes == 4
    assert layout.internal_fragmentation_bytes == 32
    assert layout.allocated_bytes == 64


def test_hybrid_block_sizes_fail_closed_without_explicit_group_layout() -> None:
    base = dict(
        pp_stage=0,
        total_num_kv_heads=8,
        head_size=128,
        dtype_bytes=2,
        tensor_parallel_size=1,
    )
    with pytest.raises(ValueError, match="explicit CacheSpec group"):
        build_stage_block_layouts(
            [
                AttentionLayerSpec(
                    layer_name="a", layer_index=0, block_size_tokens=16, **base
                ),
                AttentionLayerSpec(
                    layer_name="b", layer_index=1, block_size_tokens=32, **base
                ),
            ],
            tensor_parallel_rank=0,
            allocator_alignment_bytes=4096,
        )


def test_default_and_explicit_pp_partitions_match_pinned_rules() -> None:
    assert resolve_pp_layer_partitions(36, 2) == (18, 18)
    assert resolve_pp_layer_partitions(37, 4) == (9, 9, 10, 9)
    assert resolve_pp_layer_partitions(36, 2, (17, 19)) == (17, 19)
    with pytest.raises(ValueError, match="cover every hidden layer"):
        resolve_pp_layer_partitions(36, 2, (18, 17))


def test_layout_artifact_is_repeatable_and_accounts_each_stage_rank() -> None:
    inputs = _locked_inputs()
    first = build_qwen3_kv_layout_document(
        inputs,
        context_mode="native",
        tp_size=2,
        pp_size=2,
        block_size_tokens=16,
        allocator_alignment_bytes=256,
    )
    second = build_qwen3_kv_layout_document(
        inputs,
        context_mode="native",
        tp_size=2,
        pp_size=2,
        block_size_tokens=16,
        allocator_alignment_bytes=256,
    )

    assert first == second
    assert canonical_kv_layout_bytes(first) == canonical_kv_layout_bytes(second)
    assert first["model"]["weights_bytes"] == 16_381_470_720
    assert len(first["stage_rank_layouts"]) == 4
    entry = first["stage_rank_layouts"][0]
    assert entry["cache_spec"]["local_num_kv_heads"] == 1
    assert entry["block"]["tensor_payload_bytes"] == 16_384
    assert entry["block"]["auxiliary_payload_bytes"] == 0
    assert entry["block"]["allocator_metadata_bytes"] == 0
    assert entry["block"]["internal_fragmentation_bytes"] == 0
    assert entry["capacity"]["required_block_count_per_layer_group"] == 2560
    assert entry["capacity"]["allocated_bytes"] == 41_943_040
    assert entry["capacity"]["runtime_gpu_cache_capacity_bytes"] is None
    audit_kv_layout_document(first)


def test_native_and_proposed_128k_contexts_cannot_be_conflated() -> None:
    inputs = _locked_inputs()
    common = {
        "tp_size": 1,
        "pp_size": 1,
        "block_size_tokens": 16,
        "allocator_alignment_bytes": 256,
    }
    native = build_qwen3_kv_layout_document(inputs, context_mode="native", **common)
    proposed = build_qwen3_kv_layout_document(
        inputs,
        context_mode="proposed-yarn-128k",
        **common,
    )

    assert native["context"]["max_model_len_tokens"] == 40960
    assert native["context"]["configuration_status"] == "locked_native"
    assert native["context"]["rope_scaling"] is None
    assert proposed["context"]["max_model_len_tokens"] == 131072
    assert proposed["context"]["configuration_status"] == "proposed_unvalidated"
    assert proposed["context"]["rope_scaling"]["rope_type"] == "yarn"
    assert proposed["evidence"]["formal_use_allowed"] is False
    assert proposed["fingerprint"] != native["fingerprint"]


def test_model_hybrid_or_group_layout_fails_closed() -> None:
    inputs = _locked_inputs()
    model_config = dict(inputs.model_config)
    model_config["layer_types"] = ["full_attention", "sliding_attention"]
    hybrid = LockedLayoutInputs(
        model_id=inputs.model_id,
        model_revision=inputs.model_revision,
        model_config=model_config,
        model_weights_bytes=inputs.model_weights_bytes,
        model_files=inputs.model_files,
        tokenizer=inputs.tokenizer,
        proposed_context=inputs.proposed_context,
        model_card=inputs.model_card,
        vllm_commit=inputs.vllm_commit,
        vllm_files=inputs.vllm_files,
        source_verification=inputs.source_verification,
    )
    with pytest.raises(ValueError, match="explicit runtime CacheSpec group"):
        build_qwen3_kv_layout_document(
            hybrid,
            context_mode="native",
            tp_size=1,
            pp_size=1,
            block_size_tokens=16,
            allocator_alignment_bytes=256,
        )


def test_audit_rejects_promoted_runtime_or_physical_claims() -> None:
    document = build_qwen3_kv_layout_document(
        _locked_inputs(),
        context_mode="native",
        tp_size=1,
        pp_size=1,
        block_size_tokens=16,
        allocator_alignment_bytes=256,
    )
    document["evidence"]["cuda_physical_validation"] = "pass"
    payload = dict(document)
    payload.pop("fingerprint")
    document["fingerprint"] = sha256_json(payload)
    with pytest.raises(ValueError, match="cuda_physical_validation"):
        audit_kv_layout_document(document)


@pytest.mark.parametrize(
    "relative_path",
    [
        "configs/resolved/qwen3-8b/native-tp1-pp1/kv-layout.json",
        "configs/resolved/qwen3-8b/proposed-yarn-128k-tp1-pp1/kv-layout.json",
    ],
)
def test_checked_in_qwen_layout_artifact_passes_e1_audit(
    relative_path: str,
) -> None:
    repository_root = Path(__file__).resolve().parents[4]
    document = json.loads((repository_root / relative_path).read_text(encoding="utf-8"))
    audit_kv_layout_document(document)
