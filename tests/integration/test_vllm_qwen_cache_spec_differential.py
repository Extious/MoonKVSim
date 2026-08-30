from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from moonkvsim.common.hash import sha256_json
from moonkvsim.integration.vllm.cache_spec_differential import (
    EXPECTED_INTERPRETER,
    GENERATOR_RELATIVE_PATH,
    GOLDEN_EVIDENCE_CLASS,
    LAYOUT_RELATIVE_PATHS,
    CacheSpecDifferentialError,
    compare_qwen_layouts_to_vllm_golden,
    load_vllm_qwen_cache_spec_golden,
    repository_root,
)


def test_golden_verification_does_not_require_capture_venv_symlink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_resolve = Path.resolve

    def resolve_without_capture_venv(path: Path, strict: bool = False) -> Path:
        if path == EXPECTED_INTERPRETER:
            return path.absolute()
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_without_capture_venv)

    load_vllm_qwen_cache_spec_golden()


def test_pinned_vllm_qwen_cache_spec_bytes_match_both_layouts() -> None:
    golden = load_vllm_qwen_cache_spec_golden()

    report = compare_qwen_layouts_to_vllm_golden(golden)

    assert report.evidence_class == GOLDEN_EVIDENCE_CLASS
    assert report.layout_paths == tuple(path.as_posix() for path in LAYOUT_RELATIVE_PATHS)
    assert report.per_layer_page_size_bytes == 65_536
    assert report.layer_group_block_bytes == 2_359_296
    assert len(report.golden_fingerprint) == 64
    assert golden["vllm_observation"] == {
        "cache_spec": {
            "block_size": 16,
            "class": "FullAttentionSpec",
            "dtype": "torch.bfloat16",
            "head_size": 128,
            "head_size_v": 128,
            "kv_quant_mode": "NONE",
            "num_kv_heads": 8,
            "page_size_bytes": 65_536,
            "page_size_padded": None,
            "real_page_size_bytes": 65_536,
        },
        "layer_group_block_bytes": 2_359_296,
        "model_metadata": {
            "architecture": "Qwen3ForCausalLM",
            "dtype": "bfloat16",
            "head_size": 128,
            "local_num_kv_heads": 8,
            "model_type": "qwen3",
            "num_hidden_layers": 36,
            "total_num_kv_heads": 8,
        },
    }
    assert golden["provenance"]["execution"] == {
        "cuda_visible_devices": "",
        "device_execution": "cpu_metadata_only_no_cuda",
        "model_config_runtime_constructed": False,
        "model_forward_executed": False,
        "model_weights_loaded": False,
        "tokenizer_initialized": False,
        "torch_cuda_initialized_after": False,
        "torch_cuda_initialized_before": False,
    }


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (
            ("vllm_observation", "cache_spec", "page_size_bytes"),
            65_535,
            "cache_spec",
        ),
        (
            ("provenance", "execution", "model_weights_loaded"),
            True,
            "execution",
        ),
        (
            (
                "provenance",
                "bound_source_lock_subset",
                "vllm",
                "semantic_file_sha256",
                "vllm/v1/kv_cache_interface.py",
            ),
            "0" * 64,
            "bound_source_lock_subset",
        ),
    ],
)
def test_golden_fails_closed_on_semantic_source_or_execution_drift(
    path: tuple[str, ...], value: object, message: str
) -> None:
    golden = copy.deepcopy(load_vllm_qwen_cache_spec_golden())
    cursor = golden
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value

    with pytest.raises(CacheSpecDifferentialError, match=message):
        compare_qwen_layouts_to_vllm_golden(golden)


def test_differential_rejects_a_self_consistent_but_wrong_layout(tmp_path: Path) -> None:
    root = repository_root()
    native = json.loads((root / LAYOUT_RELATIVE_PATHS[0]).read_text(encoding="utf-8"))
    entry = native["stage_rank_layouts"][0]
    entry["cache_spec"]["local_num_kv_heads"] = 7
    entry_payload = dict(entry)
    entry_payload.pop("fingerprint")
    entry["fingerprint"] = sha256_json(entry_payload)
    layout_payload = dict(native)
    layout_payload.pop("fingerprint")
    native["fingerprint"] = sha256_json(layout_payload)
    changed_native = tmp_path / "native.json"
    changed_native.write_text(json.dumps(native), encoding="utf-8")

    with pytest.raises(CacheSpecDifferentialError, match=r"layout\.cache_spec drift"):
        compare_qwen_layouts_to_vllm_golden(
            layout_paths=(changed_native, root / LAYOUT_RELATIVE_PATHS[1])
        )


def test_loader_rejects_noncanonical_golden_bytes(tmp_path: Path) -> None:
    golden = load_vllm_qwen_cache_spec_golden()
    noncanonical = tmp_path / "golden.json"
    noncanonical.write_text(json.dumps(golden, indent=2), encoding="utf-8")

    with pytest.raises(CacheSpecDifferentialError, match="not canonical JSON"):
        load_vllm_qwen_cache_spec_golden(noncanonical)


def test_generator_refuses_project_interpreter_before_vllm_import() -> None:
    root = repository_root()
    completed = subprocess.run(
        [sys.executable, str(root / GENERATOR_RELATIVE_PATH), "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "wrong interpreter" in completed.stderr
