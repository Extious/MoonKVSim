#!/usr/bin/env python3
"""Capture/check a pinned-vLLM Qwen3 CacheSpec golden without CUDA or weights.

The capture reads only the hash-locked Qwen ``config.json`` and constructs one
real pinned-vLLM ``FullAttentionSpec`` Python object for TP1/PP1, BF16, and a
16-token block.  ``CUDA_VISIBLE_DEVICES`` is cleared before torch/vLLM import,
and the capture fails if torch reports CUDA initialization before or after the
metadata calculation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import sysconfig
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REPOSITORY_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from moonkvsim.integration.vllm.cache_spec_differential import (  # noqa: E402
    DIFFERENTIAL_RELATIVE_PATH,
    EXPECTED_INTERPRETER,
    EXPECTED_MODEL_ID,
    EXPECTED_MODEL_REVISION,
    EXPECTED_TORCH_VERSION,
    EXPECTED_VLLM_COMMIT,
    EXPECTED_VLLM_VERSION,
    GENERATOR_RELATIVE_PATH,
    GOLDEN_EVIDENCE_CLASS,
    GOLDEN_RELATIVE_PATH,
    GOLDEN_SCHEMA,
    REQUIRED_CLAIM_EXCLUSIONS,
    REQUIRED_VLLM_FILES,
    SOURCE_LOCK_RELATIVE_PATH,
    TRANSITIVE_VLLM_SHA256,
    CacheSpecDifferentialError,
    build_bound_source_subset,
    canonical_golden_bytes,
    load_source_lock,
)


class CaptureError(RuntimeError):
    """Raised on any environment, source, or metadata drift."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=REPOSITORY_ROOT,
    )
    parser.add_argument("--output", type=Path, default=GOLDEN_RELATIVE_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless the output is byte-identical to a fresh CPU capture",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing output when capturing (never implied by default)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        document = capture(root)
        expected = canonical_golden_bytes(document)
        if args.check:
            if args.overwrite:
                raise CaptureError("--check and --overwrite are mutually exclusive")
            try:
                actual = output.read_bytes()
            except OSError as error:
                raise CaptureError(f"cannot read golden for --check: {error}") from error
            if actual != expected:
                raise CaptureError(f"{output} is not byte-identical to a fresh capture")
            status = "checked"
        else:
            if output.exists() and not args.overwrite:
                raise CaptureError(f"refusing to overwrite existing golden: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(expected)
            status = "generated"
    except (
        CacheSpecDifferentialError,
        CaptureError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "evidence_class": GOLDEN_EVIDENCE_CLASS,
                "output": str(output),
                "sha256": hashlib.sha256(expected).hexdigest(),
                "status": status,
            },
            sort_keys=True,
        )
    )
    return 0


def capture(root: Path) -> dict[str, Any]:
    """Capture one source-verified, GPU-invisible FullAttentionSpec object."""

    if Path(sys.executable).resolve() != EXPECTED_INTERPRETER.resolve():
        raise CaptureError(
            f"wrong interpreter; run with {EXPECTED_INTERPRETER}, got {sys.executable}"
        )
    source_lock_path = root / SOURCE_LOCK_RELATIVE_PATH
    source_lock = load_source_lock(source_lock_path)
    bound_subset = build_bound_source_subset(source_lock)
    _audit_expected_lock_identity(bound_subset)

    installed_root = Path(sysconfig.get_paths()["purelib"]).resolve()
    installed_vllm_root = _inside(installed_root, Path("vllm"))
    if not installed_vllm_root.is_dir():
        raise CaptureError(f"installed vLLM package is missing: {installed_vllm_root}")
    bound_vllm = _mapping(bound_subset.get("vllm"), "bound vLLM")
    locked_hashes = _mapping(
        bound_vllm.get("semantic_file_sha256"), "semantic_file_sha256"
    )
    installed_hashes: dict[str, str] = {}
    for relative_text in REQUIRED_VLLM_FILES:
        expected_sha = _string(locked_hashes.get(relative_text), relative_text)
        actual_sha = _sha256_file(_inside(installed_root, Path(relative_text)))
        if actual_sha != expected_sha:
            raise CaptureError(
                f"installed vLLM semantic file hash drift: {relative_text}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
        installed_hashes[relative_text] = actual_sha
    transitive_hashes: dict[str, str] = {}
    for relative_text, expected_sha in TRANSITIVE_VLLM_SHA256.items():
        actual_sha = _sha256_file(_inside(installed_root, Path(relative_text)))
        if actual_sha != expected_sha:
            raise CaptureError(
                f"installed vLLM transitive file hash drift: {relative_text}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
        transitive_hashes[relative_text] = actual_sha
    version_sha = _sha256_file(_inside(installed_root, Path("vllm/_version.py")))
    if version_sha != bound_vllm.get("generated_version_file_sha256"):
        raise CaptureError("installed vLLM generated version-file hash drift")

    model_lock = _mapping(source_lock.get("model_tokenizer"), "model_tokenizer")
    snapshot_path = Path(_string(model_lock.get("snapshot_path"), "snapshot_path")).resolve()
    if snapshot_path.name != EXPECTED_MODEL_REVISION or not snapshot_path.is_dir():
        raise CaptureError("locked Qwen snapshot path/revision is unavailable")
    config_path = snapshot_path / "config.json"
    bound_model = _mapping(bound_subset.get("model"), "bound model")
    if _sha256_file(config_path) != bound_model.get("config_sha256"):
        raise CaptureError("locked Qwen config.json hash drift")
    config = _load_json_object(config_path)
    model_metadata = _qwen_model_metadata(config, bound_model=bound_model)

    # This must happen before the first torch/vLLM import.  Refuse any caller
    # that pre-imported either package, because its device environment cannot
    # then be proven to have been GPU-invisible for the whole capture.
    if "torch" in sys.modules or "vllm" in sys.modules:
        raise CaptureError("torch/vLLM was imported before GPU visibility was disabled")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    import torch  # type: ignore[import-not-found]
    import vllm  # type: ignore[import-not-found]
    from vllm.utils import torch_utils  # type: ignore[import-not-found]
    from vllm.v1 import kv_cache_interface  # type: ignore[import-not-found]

    if vllm.__version__ != EXPECTED_VLLM_VERSION:
        raise CaptureError(
            f"installed vLLM version drift: {vllm.__version__} != {EXPECTED_VLLM_VERSION}"
        )
    if torch.__version__ != EXPECTED_TORCH_VERSION:
        raise CaptureError(
            f"installed torch version drift: {torch.__version__} != {EXPECTED_TORCH_VERSION}"
        )
    module_file = getattr(kv_cache_interface, "__file__", None)
    if not isinstance(module_file, str):
        raise CaptureError("imported vLLM CacheSpec module has no source path")
    expected_module_path = _inside(
        installed_root, Path("vllm/v1/kv_cache_interface.py")
    )
    if Path(module_file).resolve() != expected_module_path:
        raise CaptureError("vLLM CacheSpec module imported outside verified installation")
    torch_utils_file = getattr(torch_utils, "__file__", None)
    expected_torch_utils_path = _inside(
        installed_root, Path("vllm/utils/torch_utils.py")
    )
    if not isinstance(torch_utils_file, str) or Path(torch_utils_file).resolve() != (
        expected_torch_utils_path
    ):
        raise CaptureError("vLLM torch-utils module imported outside verified installation")

    cuda_initialized_before = torch.cuda.is_initialized()
    if cuda_initialized_before:
        raise CaptureError("CUDA was initialized before CacheSpec construction")
    spec = kv_cache_interface.FullAttentionSpec(
        block_size=16,
        num_kv_heads=cast(int, model_metadata["local_num_kv_heads"]),
        head_size=cast(int, model_metadata["head_size"]),
        dtype=torch.bfloat16,
    )
    cuda_initialized_after = torch.cuda.is_initialized()
    if cuda_initialized_after:
        raise CaptureError("CUDA was initialized by metadata-only CacheSpec construction")

    generator_path = root / GENERATOR_RELATIVE_PATH
    differential_path = root / DIFFERENTIAL_RELATIVE_PATH
    cache_spec = {
        "class": type(spec).__name__,
        "block_size": spec.block_size,
        "num_kv_heads": spec.num_kv_heads,
        "head_size": spec.head_size,
        "head_size_v": spec.head_size_v,
        "dtype": str(spec.dtype),
        "kv_quant_mode": spec.kv_quant_mode.name,
        "page_size_padded": spec.page_size_padded,
        "real_page_size_bytes": spec.real_page_size_bytes,
        "page_size_bytes": spec.page_size_bytes,
    }
    layer_count = cast(int, model_metadata["num_hidden_layers"])
    return {
        "schema": GOLDEN_SCHEMA,
        "evidence_class": GOLDEN_EVIDENCE_CLASS,
        "claim_exclusions": list(REQUIRED_CLAIM_EXCLUSIONS),
        "provenance": {
            "interpreter": str(Path(sys.executable).resolve()),
            "python_version": platform.python_version(),
            "vllm_version": vllm.__version__,
            "vllm_source_commit": EXPECTED_VLLM_COMMIT,
            "torch_version": torch.__version__,
            "installed_vllm_root": str(installed_vllm_root),
            "installed_vllm_file_sha256": installed_hashes,
            "installed_vllm_transitive_sha256": transitive_hashes,
            "installed_vllm_version_file_sha256": version_sha,
            "imported_module_paths": {
                "vllm.v1.kv_cache_interface": str(expected_module_path),
                "vllm.utils.torch_utils": str(expected_torch_utils_path),
            },
            "generator": {
                "path": GENERATOR_RELATIVE_PATH.as_posix(),
                "sha256": _sha256_file(generator_path),
            },
            "differential": {
                "path": DIFFERENTIAL_RELATIVE_PATH.as_posix(),
                "sha256": _sha256_file(differential_path),
            },
            "bound_source_lock_subset": bound_subset,
            "bound_source_lock_subset_sha256": _sha256_json(bound_subset),
            "model": {
                "snapshot_path": str(snapshot_path),
                "config_path": str(config_path),
                "input_method": (
                    "hash_locked_qwen_config_json_to_pinned_FullAttentionSpec_constructor"
                ),
            },
            "execution": {
                "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
                "torch_cuda_initialized_before": cuda_initialized_before,
                "torch_cuda_initialized_after": cuda_initialized_after,
                "device_execution": "cpu_metadata_only_no_cuda",
                "model_config_runtime_constructed": False,
                "model_forward_executed": False,
                "model_weights_loaded": False,
                "tokenizer_initialized": False,
            },
        },
        "target": {
            "model_id": EXPECTED_MODEL_ID,
            "model_revision": EXPECTED_MODEL_REVISION,
            "config_sha256": bound_model["config_sha256"],
            "tensor_parallel_size": 1,
            "pipeline_parallel_size": 1,
            "block_size_tokens": 16,
            "kv_dtype": "bfloat16",
            "dtype_bytes": 2,
        },
        "vllm_observation": {
            "model_metadata": model_metadata,
            "cache_spec": cache_spec,
            "layer_group_block_bytes": spec.page_size_bytes * layer_count,
        },
    }


def _audit_expected_lock_identity(bound_subset: Mapping[str, Any]) -> None:
    vllm = _mapping(bound_subset.get("vllm"), "bound vLLM")
    if vllm.get("commit") != EXPECTED_VLLM_COMMIT:
        raise CaptureError("source-lock vLLM commit drift")
    if vllm.get("observed_generated_version") != EXPECTED_VLLM_VERSION:
        raise CaptureError("source-lock vLLM generated version drift")
    model = _mapping(bound_subset.get("model"), "bound model")
    if model.get("id") != EXPECTED_MODEL_ID:
        raise CaptureError("source-lock model ID drift")
    if model.get("revision") != EXPECTED_MODEL_REVISION:
        raise CaptureError("source-lock model revision drift")


def _qwen_model_metadata(
    config: Mapping[str, Any], *, bound_model: Mapping[str, Any]
) -> dict[str, object]:
    locked = _mapping(bound_model.get("config_fields"), "config_fields")
    expected = {
        "model_type": locked.get("model_type"),
        "hidden_size": locked.get("hidden_size"),
        "num_hidden_layers": locked.get("num_hidden_layers"),
        "num_attention_heads": locked.get("num_attention_heads"),
        "num_key_value_heads": locked.get("num_key_value_heads"),
        "head_dim": locked.get("head_dim"),
        "torch_dtype": locked.get("dtype"),
        "max_position_embeddings": locked.get("max_position_embeddings"),
        "rope_scaling": locked.get("rope_scaling"),
    }
    actual = {key: config.get(key) for key in expected}
    if actual != expected:
        raise CaptureError(f"Qwen config fields drift: expected {expected}, got {actual}")
    architectures = config.get("architectures")
    if architectures != ["Qwen3ForCausalLM"]:
        raise CaptureError("Qwen architecture drift")
    total_kv_heads = _positive_integer(config.get("num_key_value_heads"), "KV heads")
    head_size = _positive_integer(config.get("head_dim"), "head_dim")
    layer_count = _positive_integer(config.get("num_hidden_layers"), "layers")
    return {
        "architecture": "Qwen3ForCausalLM",
        "model_type": "qwen3",
        "num_hidden_layers": layer_count,
        "total_num_kv_heads": total_kv_heads,
        # The target is TP1, so no head sharding or replication is needed.
        "local_num_kv_heads": total_kv_heads,
        "head_size": head_size,
        "dtype": "bfloat16",
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CaptureError(f"JSON root must be an object: {path}")
    return cast(dict[str, Any], value)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CaptureError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CaptureError(f"{label} must be a non-empty string")
    return value


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CaptureError(f"{label} must be a positive integer")
    return value


def _inside(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise CaptureError(f"path escapes verified root: {relative}")
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise CaptureError(f"path escapes verified root: {relative}")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(raw).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
