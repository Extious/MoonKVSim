"""CPU-only Qwen3 CacheSpec/block-byte differential against pinned vLLM.

The checked-in golden is captured by the separately installed, source-locked
vLLM interpreter.  It instantiates only a ``FullAttentionSpec`` Python
metadata object from hash-locked Qwen3-8B dimensions.  This module never
imports vLLM or torch; it validates the capture and compares it with the
native and proposed-YaRN MoonKVSim KV-layout artifacts.

This is E2 metadata evidence.  It does not load model weights, initialize
CUDA, execute a model, observe runtime cache capacity, validate 128K context,
or provide timing/performance evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from moonkvsim.common.hash import canonical_json_bytes, sha256_json
from moonkvsim.integration.vllm.kv_layout_artifact import audit_kv_layout_document

GOLDEN_SCHEMA = "moonkvsim.vllm-qwen-cache-spec-golden.v1"
GOLDEN_EVIDENCE_CLASS = "E2_cpu_metadata_only"
GOLDEN_RELATIVE_PATH = Path(
    "reference/goldens/vllm-v1.2.2-qwen3-8b-cache-spec.json"
)
GENERATOR_RELATIVE_PATH = Path("scripts/generate_vllm_qwen_cache_spec_golden.py")
DIFFERENTIAL_RELATIVE_PATH = Path(
    "python/moonkvsim/integration/vllm/cache_spec_differential.py"
)
SOURCE_LOCK_RELATIVE_PATH = Path("reference/source-lock.json")
LAYOUT_RELATIVE_PATHS = (
    Path("configs/resolved/qwen3-8b/native-tp1-pp1/kv-layout.json"),
    Path("configs/resolved/qwen3-8b/proposed-yarn-128k-tp1-pp1/kv-layout.json"),
)

EXPECTED_VLLM_COMMIT = "644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504"
EXPECTED_VLLM_VERSION = "1.2.2+aegiskv.sm89"
EXPECTED_TORCH_VERSION = "2.10.0+cu128"
EXPECTED_MODEL_ID = "Qwen/Qwen3-8B"
EXPECTED_MODEL_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
EXPECTED_INTERPRETER = Path(
    "/home/comp/zhanzhao/Mooncake/aegiskv/.venv-vllm-sm89/bin/python"
)
EXPECTED_CAPTURE_INTERPRETER = Path(
    "/home/comp/zhanzhao/Mooncake/aegiskv/artifacts/python/"
    "cpython-3.12.13-linux-x86_64-gnu/bin/python3.12"
)
REQUIRED_VLLM_FILES = (
    "vllm/config/model.py",
    "vllm/distributed/utils.py",
    "vllm/v1/kv_cache_interface.py",
)
TRANSITIVE_VLLM_SHA256 = {
    "vllm/utils/torch_utils.py": (
        "af36be9eb2503a7087a66dc42b1ca520baea513f763330a0e955b8d2c005794d"
    )
}
REQUIRED_CLAIM_EXCLUSIONS = (
    "128k_context_validation",
    "cuda",
    "gpu_execution",
    "model_forward",
    "model_weights",
    "performance",
    "physical_validation",
    "runtime_cache_capacity",
    "timing_calibration",
)


class CacheSpecDifferentialError(RuntimeError):
    """Raised when capture provenance or any compared field drifts."""


@dataclass(frozen=True, slots=True)
class CacheSpecDifferentialReport:
    """Summary of an exact Qwen CacheSpec/block-byte comparison."""

    layout_paths: tuple[str, ...]
    per_layer_page_size_bytes: int
    layer_group_block_bytes: int
    golden_fingerprint: str
    evidence_class: str = GOLDEN_EVIDENCE_CLASS

    def to_dict(self) -> dict[str, object]:
        return {
            "layout_paths": list(self.layout_paths),
            "per_layer_page_size_bytes": self.per_layer_page_size_bytes,
            "layer_group_block_bytes": self.layer_group_block_bytes,
            "golden_fingerprint": self.golden_fingerprint,
            "evidence_class": self.evidence_class,
            "claim_exclusions": list(REQUIRED_CLAIM_EXCLUSIONS),
        }


def repository_root() -> Path:
    """Return the checkout root from this installed/editable source file."""

    return Path(__file__).resolve().parents[4]


def canonical_golden_bytes(document: Mapping[str, Any]) -> bytes:
    """Serialize the E2 capture in its byte-canonical representation."""

    return canonical_json_bytes(document) + b"\n"


def load_source_lock(path: Path) -> dict[str, Any]:
    """Load a source-lock object without accepting non-object JSON."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CacheSpecDifferentialError(f"cannot load source lock: {error}") from error
    if not isinstance(value, dict):
        raise CacheSpecDifferentialError("source lock root must be an object")
    return cast(dict[str, Any], value)


def build_bound_source_subset(source_lock: Mapping[str, Any]) -> dict[str, Any]:
    """Select every source-lock field that gives this observation meaning."""

    repositories = _require_mapping(source_lock.get("repositories"), "repositories")
    vllm = _require_mapping(repositories.get("vllm"), "repositories.vllm")
    files = {
        _require_string(_require_mapping(item, "vLLM file").get("path"), "file.path"):
        _require_string(_require_mapping(item, "vLLM file").get("sha256"), "file.sha256")
        for item in _require_sequence(vllm.get("files"), "repositories.vllm.files")
    }
    missing = sorted(set(REQUIRED_VLLM_FILES).difference(files))
    if missing:
        raise CacheSpecDifferentialError(
            f"source lock omits required CacheSpec files: {missing}"
        )
    generated_files = _require_sequence(
        vllm.get("generated_files"), "repositories.vllm.generated_files"
    )
    version_sha = next(
        (
            _require_string(
                _require_mapping(item, "generated vLLM file").get("sha256"),
                "generated vLLM file sha256",
            )
            for item in generated_files
            if _require_mapping(item, "generated vLLM file").get("path")
            == "vllm/_version.py"
        ),
        None,
    )
    if version_sha is None:
        raise CacheSpecDifferentialError("source lock omits vllm/_version.py")

    model = _require_mapping(source_lock.get("model_tokenizer"), "model_tokenizer")
    model_files = {
        _require_string(_require_mapping(item, "model file").get("path"), "model path"):
        _require_string(_require_mapping(item, "model file").get("sha256"), "model sha256")
        for item in _require_sequence(model.get("files"), "model_tokenizer.files")
    }
    config_sha = model_files.get("config.json")
    if config_sha is None:
        raise CacheSpecDifferentialError("source lock omits Qwen config.json")
    locked_config = _require_mapping(
        model.get("model_config"), "model_tokenizer.model_config"
    )
    config_fields = {
        key: locked_config.get(key)
        for key in (
            "dtype",
            "head_dim",
            "hidden_size",
            "max_position_embeddings",
            "model_type",
            "num_attention_heads",
            "num_hidden_layers",
            "num_key_value_heads",
            "rope_scaling",
        )
    }
    return {
        "vllm": {
            "commit": vllm.get("commit"),
            "observed_generated_version": vllm.get("observed_generated_version"),
            "generated_version_file_sha256": version_sha,
            "semantic_file_sha256": {
                path: files[path] for path in REQUIRED_VLLM_FILES
            },
        },
        "model": {
            "id": model.get("model_id"),
            "revision": model.get("revision"),
            "config_sha256": config_sha,
            "config_fields": config_fields,
        },
    }


def load_vllm_qwen_cache_spec_golden(
    path: Path | None = None,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Load and fail-closed audit the checked-in CPU metadata capture."""

    resolved_root = (root or repository_root()).resolve()
    resolved_path = (path or resolved_root / GOLDEN_RELATIVE_PATH).resolve()
    try:
        raw = resolved_path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CacheSpecDifferentialError(f"cannot load CacheSpec golden: {error}") from error
    if not isinstance(value, dict):
        raise CacheSpecDifferentialError("CacheSpec golden root must be an object")
    document = cast(dict[str, Any], value)
    if raw != canonical_golden_bytes(document):
        raise CacheSpecDifferentialError("CacheSpec golden is not canonical JSON")
    _audit_golden_document(document, root=resolved_root)
    return document


def compare_qwen_layouts_to_vllm_golden(
    golden: Mapping[str, Any] | None = None,
    *,
    root: Path | None = None,
    layout_paths: Sequence[Path] = LAYOUT_RELATIVE_PATHS,
) -> CacheSpecDifferentialReport:
    """Compare MoonKVSim Qwen layouts with the captured vLLM CacheSpec bytes."""

    resolved_root = (root or repository_root()).resolve()
    document = (
        dict(golden)
        if golden is not None
        else load_vllm_qwen_cache_spec_golden(root=resolved_root)
    )
    _audit_golden_document(document, root=resolved_root)
    target = _require_mapping(document.get("target"), "target")
    observation = _require_mapping(
        document.get("vllm_observation"), "vllm_observation"
    )
    cache_spec = _require_mapping(observation.get("cache_spec"), "cache_spec")
    model = _require_mapping(observation.get("model_metadata"), "model_metadata")

    per_layer_bytes = _require_integer(
        cache_spec.get("page_size_bytes"), "cache_spec.page_size_bytes"
    )
    layer_count = _require_integer(model.get("num_hidden_layers"), "num_hidden_layers")
    expected_group_bytes = per_layer_bytes * layer_count
    if observation.get("layer_group_block_bytes") != expected_group_bytes:
        raise CacheSpecDifferentialError(
            "vLLM layer-group bytes do not equal per-layer page bytes times layer count"
        )

    if len(layout_paths) != 2 or layout_paths[0] == layout_paths[1]:
        raise CacheSpecDifferentialError(
            "target differential requires two distinct native/YaRN layouts"
        )
    compared: list[str] = []
    context_modes: list[str] = []
    for relative in layout_paths:
        layout_path = relative if relative.is_absolute() else resolved_root / relative
        layout = _load_json_object(layout_path, label=f"KV layout {relative}")
        try:
            audit_kv_layout_document(layout)
        except ValueError as error:
            raise CacheSpecDifferentialError(
                f"KV layout audit failed for {relative}: {error}"
            ) from error
        _compare_layout(
            layout,
            target=target,
            model_observation=model,
            cache_spec_observation=cache_spec,
            expected_group_bytes=expected_group_bytes,
        )
        compared.append(relative.as_posix())
        context = _require_mapping(layout.get("context"), "layout.context")
        context_modes.append(_require_string(context.get("mode"), "layout.context.mode"))
    if context_modes != ["native_model_config", "proposed_yarn_128k"]:
        raise CacheSpecDifferentialError(
            "target differential requires native then proposed-YaRN layout contexts"
        )

    return CacheSpecDifferentialReport(
        layout_paths=tuple(compared),
        per_layer_page_size_bytes=per_layer_bytes,
        layer_group_block_bytes=expected_group_bytes,
        golden_fingerprint=sha256_json(document),
    )


def _compare_layout(
    layout: Mapping[str, Any],
    *,
    target: Mapping[str, Any],
    model_observation: Mapping[str, Any],
    cache_spec_observation: Mapping[str, Any],
    expected_group_bytes: int,
) -> None:
    model = _require_mapping(layout.get("model"), "layout.model")
    parallelism = _require_mapping(layout.get("parallelism"), "layout.parallelism")
    entries = _require_sequence(layout.get("stage_rank_layouts"), "stage_rank_layouts")
    if len(entries) != 1:
        raise CacheSpecDifferentialError("target differential requires exactly one TP1/PP1 entry")
    entry = _require_mapping(entries[0], "stage_rank_layouts[0]")
    cache_spec = _require_mapping(entry.get("cache_spec"), "layout.cache_spec")
    block = _require_mapping(entry.get("block"), "layout.block")

    expected_model = {
        "id": target.get("model_id"),
        "revision": target.get("model_revision"),
        "config_sha256": target.get("config_sha256"),
        "architecture": model_observation.get("architecture"),
        "model_type": model_observation.get("model_type"),
        "num_hidden_layers": model_observation.get("num_hidden_layers"),
        "total_num_kv_heads": model_observation.get("total_num_kv_heads"),
        "head_size": model_observation.get("head_size"),
    }
    actual_model = {key: model.get(key) for key in expected_model}
    _require_exact(actual_model, expected_model, "layout.model")
    _require_exact(
        {
            "tensor_parallel_size": parallelism.get("tensor_parallel_size"),
            "pipeline_parallel_size": parallelism.get("pipeline_parallel_size"),
        },
        {
            "tensor_parallel_size": target.get("tensor_parallel_size"),
            "pipeline_parallel_size": target.get("pipeline_parallel_size"),
        },
        "layout.parallelism",
    )

    expected_cache_spec = {
        "kind": "full_attention",
        "block_size_tokens": cache_spec_observation.get("block_size"),
        "total_num_kv_heads": model_observation.get("total_num_kv_heads"),
        "local_num_kv_heads": cache_spec_observation.get("num_kv_heads"),
        "head_size_k": cache_spec_observation.get("head_size"),
        "head_size_v": cache_spec_observation.get("head_size_v"),
        "kv_dtype": target.get("kv_dtype"),
        "dtype_bytes": target.get("dtype_bytes"),
        "kv_quant_mode": "none",
        "page_size_padded_bytes_per_layer": cache_spec_observation.get(
            "page_size_padded"
        ),
        "auxiliary_payload_bytes_per_layer_block": 0,
    }
    actual_cache_spec = {key: cache_spec.get(key) for key in expected_cache_spec}
    _require_exact(actual_cache_spec, expected_cache_spec, "layout.cache_spec")
    _require_exact(
        {
            "layer_count": entry.get("layer_count"),
            "block_size_tokens": block.get("block_size_tokens"),
            "tensor_payload_bytes": block.get("tensor_payload_bytes"),
            "auxiliary_payload_bytes": block.get("auxiliary_payload_bytes"),
            "payload_bytes": block.get("payload_bytes"),
            "layout_padding_bytes": block.get("layout_padding_bytes"),
            "requested_bytes": block.get("requested_bytes"),
        },
        {
            "layer_count": model_observation.get("num_hidden_layers"),
            "block_size_tokens": cache_spec_observation.get("block_size"),
            "tensor_payload_bytes": expected_group_bytes,
            "auxiliary_payload_bytes": 0,
            "payload_bytes": expected_group_bytes,
            "layout_padding_bytes": 0,
            "requested_bytes": expected_group_bytes,
        },
        "layout.block",
    )


def _audit_golden_document(document: Mapping[str, Any], *, root: Path) -> None:
    if document.get("schema") != GOLDEN_SCHEMA:
        raise CacheSpecDifferentialError("unexpected CacheSpec golden schema")
    if document.get("evidence_class") != GOLDEN_EVIDENCE_CLASS:
        raise CacheSpecDifferentialError("CacheSpec golden must remain E2 CPU metadata only")
    exclusions = _require_sequence(document.get("claim_exclusions"), "claim_exclusions")
    if tuple(exclusions) != REQUIRED_CLAIM_EXCLUSIONS:
        raise CacheSpecDifferentialError("CacheSpec golden claim exclusions drifted")

    provenance = _require_mapping(document.get("provenance"), "provenance")
    # Validate the immutable identity recorded at capture time.  Resolving the
    # launcher path here would make verification depend on whether that local
    # venv symlink happens to exist on the machine reading the golden.
    if provenance.get("interpreter") != str(EXPECTED_CAPTURE_INTERPRETER):
        raise CacheSpecDifferentialError("CacheSpec interpreter provenance drift")
    if provenance.get("vllm_version") != EXPECTED_VLLM_VERSION:
        raise CacheSpecDifferentialError("CacheSpec vLLM version drift")
    if provenance.get("vllm_source_commit") != EXPECTED_VLLM_COMMIT:
        raise CacheSpecDifferentialError("CacheSpec vLLM commit drift")
    if provenance.get("torch_version") != EXPECTED_TORCH_VERSION:
        raise CacheSpecDifferentialError("CacheSpec torch version drift")
    execution = _require_mapping(provenance.get("execution"), "provenance.execution")
    expected_execution = {
        "cuda_visible_devices": "",
        "torch_cuda_initialized_before": False,
        "torch_cuda_initialized_after": False,
        "device_execution": "cpu_metadata_only_no_cuda",
        "model_config_runtime_constructed": False,
        "model_forward_executed": False,
        "model_weights_loaded": False,
        "tokenizer_initialized": False,
    }
    _require_exact(dict(execution), expected_execution, "provenance.execution")

    _audit_bound_file(
        _require_mapping(provenance.get("generator"), "provenance.generator"),
        expected_relative=GENERATOR_RELATIVE_PATH,
        root=root,
    )
    _audit_bound_file(
        _require_mapping(provenance.get("differential"), "provenance.differential"),
        expected_relative=DIFFERENTIAL_RELATIVE_PATH,
        root=root,
    )
    source_lock = load_source_lock(root / SOURCE_LOCK_RELATIVE_PATH)
    current_subset = build_bound_source_subset(source_lock)
    bound_source = _require_mapping(
        provenance.get("bound_source_lock_subset"), "bound_source_lock_subset"
    )
    _require_exact(dict(bound_source), current_subset, "bound_source_lock_subset")
    if provenance.get("bound_source_lock_subset_sha256") != sha256_json(current_subset):
        raise CacheSpecDifferentialError("bound source-lock subset fingerprint drift")

    installed_hashes = _require_mapping(
        provenance.get("installed_vllm_file_sha256"), "installed_vllm_file_sha256"
    )
    locked_vllm = _require_mapping(current_subset.get("vllm"), "bound vLLM")
    expected_hashes = _require_mapping(
        locked_vllm.get("semantic_file_sha256"), "semantic_file_sha256"
    )
    _require_exact(dict(installed_hashes), dict(expected_hashes), "installed vLLM hashes")
    transitive_hashes = _require_mapping(
        provenance.get("installed_vllm_transitive_sha256"),
        "installed_vllm_transitive_sha256",
    )
    _require_exact(
        dict(transitive_hashes),
        TRANSITIVE_VLLM_SHA256,
        "installed vLLM transitive hashes",
    )
    if provenance.get("installed_vllm_version_file_sha256") != locked_vllm.get(
        "generated_version_file_sha256"
    ):
        raise CacheSpecDifferentialError("installed vLLM version-file hash drift")
    installed_root = _require_string(
        provenance.get("installed_vllm_root"), "installed_vllm_root"
    )
    if not installed_root.endswith("/lib/python3.12/site-packages/vllm"):
        raise CacheSpecDifferentialError("installed vLLM root provenance drift")
    imported_paths = _require_mapping(
        provenance.get("imported_module_paths"), "imported_module_paths"
    )
    package_root = Path(installed_root)
    _require_exact(
        dict(imported_paths),
        {
            "vllm.v1.kv_cache_interface": str(package_root / "v1/kv_cache_interface.py"),
            "vllm.utils.torch_utils": str(package_root / "utils/torch_utils.py"),
        },
        "imported_module_paths",
    )

    model_provenance = _require_mapping(provenance.get("model"), "provenance.model")
    source_model = _require_mapping(source_lock.get("model_tokenizer"), "model_tokenizer")
    snapshot_path = source_model.get("snapshot_path")
    expected_model_provenance = {
        "snapshot_path": snapshot_path,
        "config_path": (
            str(Path(snapshot_path) / "config.json")
            if isinstance(snapshot_path, str)
            else None
        ),
        "input_method": (
            "hash_locked_qwen_config_json_to_pinned_FullAttentionSpec_constructor"
        ),
    }
    _require_exact(
        dict(model_provenance), expected_model_provenance, "provenance.model"
    )

    target = _require_mapping(document.get("target"), "target")
    bound_model = _require_mapping(current_subset.get("model"), "bound model")
    expected_target = {
        "model_id": EXPECTED_MODEL_ID,
        "model_revision": EXPECTED_MODEL_REVISION,
        "config_sha256": bound_model.get("config_sha256"),
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "block_size_tokens": 16,
        "kv_dtype": "bfloat16",
        "dtype_bytes": 2,
    }
    _require_exact(dict(target), expected_target, "target")
    _audit_observation(document, bound_model=bound_model)


def _audit_observation(
    document: Mapping[str, Any], *, bound_model: Mapping[str, Any]
) -> None:
    observation = _require_mapping(
        document.get("vllm_observation"), "vllm_observation"
    )
    model = _require_mapping(observation.get("model_metadata"), "model_metadata")
    locked_fields = _require_mapping(bound_model.get("config_fields"), "config_fields")
    expected_model = {
        "architecture": "Qwen3ForCausalLM",
        "model_type": locked_fields.get("model_type"),
        "num_hidden_layers": locked_fields.get("num_hidden_layers"),
        "total_num_kv_heads": locked_fields.get("num_key_value_heads"),
        "local_num_kv_heads": locked_fields.get("num_key_value_heads"),
        "head_size": locked_fields.get("head_dim"),
        "dtype": locked_fields.get("dtype"),
    }
    _require_exact(dict(model), expected_model, "vllm_observation.model_metadata")
    spec = _require_mapping(observation.get("cache_spec"), "cache_spec")
    expected_spec = {
        "class": "FullAttentionSpec",
        "block_size": 16,
        "num_kv_heads": expected_model["local_num_kv_heads"],
        "head_size": expected_model["head_size"],
        "head_size_v": expected_model["head_size"],
        "dtype": "torch.bfloat16",
        "kv_quant_mode": "NONE",
        "page_size_padded": None,
        "real_page_size_bytes": 65_536,
        "page_size_bytes": 65_536,
    }
    _require_exact(dict(spec), expected_spec, "vllm_observation.cache_spec")
    block_size = _require_integer(spec.get("block_size"), "cache_spec.block_size")
    num_heads = _require_integer(spec.get("num_kv_heads"), "cache_spec.num_kv_heads")
    head_size = _require_integer(spec.get("head_size"), "cache_spec.head_size")
    expected_page = 2 * block_size * num_heads * head_size * 2
    if spec.get("real_page_size_bytes") != expected_page:
        raise CacheSpecDifferentialError("CacheSpec real page bytes drift")
    if spec.get("page_size_bytes") != expected_page:
        raise CacheSpecDifferentialError("CacheSpec page bytes drift")
    layer_count = _require_integer(model.get("num_hidden_layers"), "num_hidden_layers")
    if observation.get("layer_group_block_bytes") != expected_page * layer_count:
        raise CacheSpecDifferentialError("CacheSpec layer-group bytes drift")


def _audit_bound_file(
    record: Mapping[str, Any], *, expected_relative: Path, root: Path
) -> None:
    if record.get("path") != expected_relative.as_posix():
        raise CacheSpecDifferentialError(f"bound file path drift: {expected_relative}")
    expected_sha = _require_string(record.get("sha256"), "bound file sha256")
    actual_sha = hashlib.sha256((root / expected_relative).read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise CacheSpecDifferentialError(f"bound file hash drift: {expected_relative}")


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CacheSpecDifferentialError(f"cannot load {label}: {error}") from error
    if not isinstance(value, dict):
        raise CacheSpecDifferentialError(f"{label} root must be an object")
    return cast(dict[str, Any], value)


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CacheSpecDifferentialError(f"{label} must be an object")
    return cast(Mapping[str, Any], value)


def _require_sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CacheSpecDifferentialError(f"{label} must be an array")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CacheSpecDifferentialError(f"{label} must be a non-empty string")
    return value


def _require_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CacheSpecDifferentialError(f"{label} must be a positive integer")
    return value


def _require_exact(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise CacheSpecDifferentialError(
            f"{label} drift: expected {expected!r}, got {actual!r}"
        )
