#!/usr/bin/env python3
"""Pinned Qwen3-8B/vLLM forward-only physical calibration harness.

This runner is intentionally narrow: native 40,960 context, one assigned and
process-isolated Slurm-visible L40S, TP=PP=1, bfloat16, and the pinned 1Cat vLLM
build.  It never edits vLLM.  A runtime monkeypatch lets ``execute_model`` carry
only immutable scheduler metadata to an inner
``GPUModelRunner._model_forward`` wrapper.  The inner wrapper joins that
metadata to the post-``_update_states`` runner state, checks the exact ordered
shape, and times only the model forward with CUDA events.

The produced bundle is raw calibration input, not a calibrated profile.  Every
manifest is therefore fail-closed with ``formal_use_allowed=false``.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Final, Protocol, TextIO, cast

SHAPE_PLAN_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-shape-plan.v1"
SAMPLE_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-sample.v1"
STEP_METADATA_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-step-metadata.v1"
SPLIT_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-held-out-split.v1"
ENVIRONMENT_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-environment.v1"
MANIFEST_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-run-manifest.v1"
FEASIBILITY_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-feasibility.v1"
THRESHOLD_SCHEMA: Final = "moonkvsim.aiconfigurator-residual-thresholds.v1"

EXPECTED_MODEL_ID: Final = "Qwen/Qwen3-8B"
EXPECTED_MODEL_REVISION: Final = "b968826d9c46dd6066d109eabc6255188de91218"
EXPECTED_VLLM_COMMIT: Final = "644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504"
EXPECTED_VLLM_VERSION: Final = "1.2.2+aegiskv.sm89"
EXPECTED_VLLM_DISTRIBUTION: Final = "1cat-vllm"
EXPECTED_AICONFIGURATOR_VERSION: Final = "0.9.0"
EXPECTED_AICONFIGURATOR_COMMIT: Final = "4b9d9dc51e02b5e9d4acc3688f3edf41693834c6"
EXPECTED_TORCH_VERSION: Final = "2.10.0+cu128"
EXPECTED_TORCH_INIT_SHA256: Final = (
    "51c90fe34a7cf869517d1bab4cd114498790e169ec668f1a154c35ec64117a5e"
)
EXPECTED_TORCH_EXTENSION_SHA256: Final = (
    "90fc84350d2de15ca167734eb63b20b3a1a4ea2721d498b66e3e65174c0cff9f"
)
EXPECTED_NVML_DISTRIBUTION_VERSION: Final = "13.610.43"
EXPECTED_PYNVML_SHA256: Final = "d3233c78cd3f17bda97850346eba30fa88f1d6b295cee90fa7ec1c6cbf291e5b"
EXPECTED_RUNTIME_PYTHON: Final = Path(
    "/home/comp/zhanzhao/Mooncake/aegiskv/.venv-vllm-sm89/bin/python"
)
EXPECTED_RUNTIME_PYTHON_SHA256: Final = (
    "339de109f072e52523066d97a2b3372e358a10cc00c6a9df62c28a6618061900"
)
EXPECTED_MODEL_SNAPSHOT: Final = Path(
    "/home/comp/zhanzhao/.cache/huggingface/hub/"
    "models--Qwen--Qwen3-8B/snapshots/"
    f"{EXPECTED_MODEL_REVISION}"
)
EXPECTED_AICONFIGURATOR_REPOSITORY: Final = Path("/home/comp/zhanzhao/aiconfigurator")
EXPECTED_SOURCE_LOCK_SHA256: Final = (
    "d122c926c41071bb1cf6049a3ff9fada836038cee5047881399f946750a9eaf1"
)
EXPECTED_AICONFIGURATOR_SUPPORT_SHA256: Final = (
    "3320c05f3db70f618ccb33299695e228b1ae0e601c281a58246a7b8a72321403"
)
MODEL_RUNNER_RELATIVE: Final = Path("vllm/v1/worker/gpu_model_runner.py")
MODEL_RUNNER_GIT_BLOB: Final = "109ee6e7c836f23282df90937d5b9387b5380cdb"
MODEL_RUNNER_SHA256: Final = "960efef5498b41e59ab9a27e3c75367ad3ea2bb83caf6f8a9799a6f496b35297"
MODEL_RUNNER_SYMBOL: Final = "GPUModelRunner._model_forward"
MEASUREMENT_METHOD: Final = "cuda_events_gpu_model_runner_model_forward"
MAX_MODEL_LEN: Final = 40960
PROMPT_TOKEN_ID: Final = 42
HEX64: Final = re.compile(r"^[0-9a-f]{64}$")
HEX40: Final = re.compile(r"^[0-9a-f]{40}$")

EXIT_INVALID_INPUT: Final = 2
EXIT_SOURCE_DRIFT: Final = 3
EXIT_GPU_MISMATCH: Final = 4
EXIT_SHAPE_MISMATCH: Final = 5
EXIT_TIMING_FAILURE: Final = 6
EXIT_OOM: Final = 7
EXIT_PUBLICATION_FAILURE: Final = 8

_PLAN_KEYS: Final = {
    "attention_backend",
    "block_size",
    "calibration_method",
    "context_mode",
    "dtype",
    "engine",
    "hardware_profile_id",
    "held_out_split_seed",
    "kv_dtype",
    "measured_repeats",
    "model",
    "phases",
    "pipeline_parallel_size",
    "schema",
    "tensor_parallel_size",
    "threshold_declaration",
    "warmup_repeats",
}
_SAMPLE_KEYS: Final = {
    "batch_size",
    "cudagraph_mode",
    "duration_ns",
    "extend_lengths",
    "hardware_profile_fingerprint",
    "measurement_method",
    "model_runner_source_sha256",
    "past_kv_lengths",
    "phase",
    "pipeline_parallel_rank",
    "profile_fingerprint",
    "repeat_index",
    "request_ids_sha256",
    "schema",
    "shape_id",
    "tensor_parallel_rank",
    "warmup",
}


class CalibrationError(RuntimeError):
    """A fail-closed harness failure with a stable process exit code."""

    exit_code = 1


class InvalidInputError(CalibrationError):
    exit_code = EXIT_INVALID_INPUT


class SourceDriftError(CalibrationError):
    exit_code = EXIT_SOURCE_DRIFT


class GPUMismatchError(CalibrationError):
    exit_code = EXIT_GPU_MISMATCH


class ShapeConstructionError(CalibrationError):
    exit_code = EXIT_SHAPE_MISMATCH


class CUDATimingError(CalibrationError):
    exit_code = EXIT_TIMING_FAILURE


class OOMFeasibilityError(CalibrationError):
    exit_code = EXIT_OOM


class PublicationError(CalibrationError):
    exit_code = EXIT_PUBLICATION_FAILURE


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def write_canonical_json(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def _load_json_object(path: Path, label: str, *, canonical: bool) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise InvalidInputError(f"{label} must be a regular non-symlink file: {path}")
    try:
        contents = path.read_bytes()
        value = json.loads(contents)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidInputError(f"cannot load {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise InvalidInputError(f"{label} root must be an object")
    if canonical and canonical_json_bytes(value) != contents:
        raise InvalidInputError(f"{label} must use canonical JSON bytes")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    observed = set(value)
    if observed != expected:
        raise InvalidInputError(
            f"{label} fields differ: missing={sorted(expected - observed)}, "
            f"extra={sorted(observed - expected)}"
        )


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidInputError(f"{label} must be a positive integer")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidInputError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class CalibrationShape:
    phase: str
    extend_lengths: tuple[int, ...]
    past_kv_lengths: tuple[int, ...]

    @property
    def batch_size(self) -> int:
        return len(self.extend_lengths)

    @property
    def shape_id(self) -> str:
        return sha256_bytes(
            canonical_json_bytes(
                {
                    "extend_lengths": list(self.extend_lengths),
                    "past_kv_lengths": list(self.past_kv_lengths),
                    "phase": self.phase,
                }
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "extend_lengths": list(self.extend_lengths),
            "past_kv_lengths": list(self.past_kv_lengths),
            "phase": self.phase,
            "shape_id": self.shape_id,
        }


def _parse_shape(phase: str, value: object, index: int) -> CalibrationShape:
    label = f"phases.{phase}[{index}]"
    if not isinstance(value, dict):
        raise InvalidInputError(f"{label} must be an object")
    _exact_keys(value, {"extend_lengths", "past_kv_lengths"}, label)
    extend_raw = value["extend_lengths"]
    past_raw = value["past_kv_lengths"]
    if not isinstance(extend_raw, list) or not isinstance(past_raw, list):
        raise InvalidInputError(f"{label} vectors must be arrays")
    if not extend_raw or len(extend_raw) != len(past_raw):
        raise InvalidInputError(f"{label} vectors must be non-empty and equally sized")
    extend = tuple(
        _positive_int(item, f"{label}.extend_lengths[{item_index}]")
        for item_index, item in enumerate(extend_raw)
    )
    past = tuple(
        _nonnegative_int(item, f"{label}.past_kv_lengths[{item_index}]")
        for item_index, item in enumerate(past_raw)
    )
    for item_index, (extension, previous) in enumerate(zip(extend, past, strict=True)):
        if previous + extension > MAX_MODEL_LEN:
            raise InvalidInputError(
                f"{label}[{item_index}] exceeds native max_model_len {MAX_MODEL_LEN}"
            )
    if phase == "decode":
        if any(item != 1 for item in extend) or any(item <= 0 for item in past):
            raise InvalidInputError(
                f"{label} pure decode requires extension=1 and positive past KV"
            )
    elif phase == "mixed":
        decode_members = [
            item_extension == 1 and item_past > 0
            for item_extension, item_past in zip(extend, past, strict=True)
        ]
        prefill_members = [item_extension > 1 for item_extension in extend]
        if not any(decode_members) or not any(prefill_members):
            raise InvalidInputError(f"{label} must have an unambiguous decode and prefill member")
        if any(
            not (is_decode or is_prefill)
            for is_decode, is_prefill in zip(decode_members, prefill_members, strict=True)
        ):
            raise InvalidInputError(f"{label} contains an ambiguous mixed member")
    return CalibrationShape(phase, extend, past)


def planned_profile_descriptor(plan: Mapping[str, Any]) -> dict[str, object]:
    """Return the pre-allocation campaign identity bound by thresholds.

    The exact detected GPU identity is recorded separately and never promoted
    by this raw harness.  An offline reducer must bind it into a materialized
    profile before any E3 selection is possible.
    """

    return {
        "attention_backend": plan["attention_backend"],
        "block_size": plan["block_size"],
        "calibration_method": plan["calibration_method"],
        "context_mode": plan["context_mode"],
        "dtype": plan["dtype"],
        "engine": plan["engine"],
        "forward_boundary": {
            "includes_model_collectives": False,
            "model_collective_scope": "none_tp1",
            "scope": "gpu_forward_only",
            "symbol": MODEL_RUNNER_SYMBOL,
        },
        "hardware_profile_id": plan["hardware_profile_id"],
        "kv_dtype": plan["kv_dtype"],
        "model": plan["model"],
        "pipeline_parallel_size": plan["pipeline_parallel_size"],
        "provider": {
            "commit": EXPECTED_AICONFIGURATOR_COMMIT,
            "name": "aiconfigurator",
            "version": EXPECTED_AICONFIGURATOR_VERSION,
        },
        "tensor_parallel_size": plan["tensor_parallel_size"],
    }


def planned_profile_fingerprint(plan: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(planned_profile_descriptor(plan)))


def validate_shape_plan_document(plan: dict[str, Any]) -> tuple[CalibrationShape, ...]:
    _exact_keys(plan, _PLAN_KEYS, "shape plan")
    fixed = {
        "schema": SHAPE_PLAN_SCHEMA,
        "attention_backend": "FLASH_ATTN",
        "block_size": 16,
        "calibration_method": "phase_shape_residual_table",
        "dtype": "bfloat16",
        "kv_dtype": "bfloat16",
        "hardware_profile_id": "l40s-exact-detected-profile",
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
    }
    mismatches = [
        f"{key}: observed={plan.get(key)!r}, expected={expected!r}"
        for key, expected in fixed.items()
        if plan.get(key) != expected
    ]
    if mismatches:
        raise InvalidInputError("shape-plan pin mismatch: " + "; ".join(mismatches))
    if plan["context_mode"] != {"max_model_len": MAX_MODEL_LEN, "rope_scaling": None}:
        raise InvalidInputError("only native max_model_len=40960 with rope_scaling=null is allowed")
    if plan["engine"] != {
        "installed_version": EXPECTED_VLLM_VERSION,
        "source_commit": EXPECTED_VLLM_COMMIT,
    }:
        raise InvalidInputError("shape-plan engine pin mismatch")
    if plan["model"] != {
        "id": EXPECTED_MODEL_ID,
        "revision": EXPECTED_MODEL_REVISION,
    }:
        raise InvalidInputError("shape-plan model pin mismatch")
    _positive_int(plan["measured_repeats"], "measured_repeats")
    if _positive_int(plan["warmup_repeats"], "warmup_repeats") < 5:
        raise InvalidInputError("warmup_repeats must be at least five")
    _nonnegative_int(plan["held_out_split_seed"], "held_out_split_seed")

    phases = plan["phases"]
    if not isinstance(phases, dict):
        raise InvalidInputError("phases must be an object")
    _exact_keys(phases, {"prefill", "decode", "mixed"}, "phases")
    shapes: list[CalibrationShape] = []
    for phase in ("prefill", "decode", "mixed"):
        phase_values = phases[phase]
        if not isinstance(phase_values, list) or not phase_values:
            raise InvalidInputError(f"phases.{phase} must be a non-empty array")
        shapes.extend(_parse_shape(phase, item, index) for index, item in enumerate(phase_values))
    shape_ids = [shape.shape_id for shape in shapes]
    if len(shape_ids) != len(set(shape_ids)):
        raise InvalidInputError("shape plan contains duplicate phase/vector shapes")

    declaration = plan["threshold_declaration"]
    if not isinstance(declaration, dict):
        raise InvalidInputError("threshold_declaration must be an object")
    _exact_keys(declaration, {"path", "sha256", "size_bytes"}, "threshold_declaration")
    threshold_path = declaration["path"]
    if threshold_path != "residual-thresholds.json":
        raise InvalidInputError("threshold_declaration.path must be residual-thresholds.json")
    if not isinstance(declaration["sha256"], str) or not HEX64.fullmatch(declaration["sha256"]):
        raise InvalidInputError("threshold_declaration.sha256 must be lowercase SHA-256")
    _positive_int(declaration["size_bytes"], "threshold_declaration.size_bytes")
    return tuple(shapes)


def load_and_validate_shape_plan(
    path: Path,
) -> tuple[dict[str, Any], tuple[CalibrationShape, ...], dict[str, Any]]:
    plan = _load_json_object(path, "shape plan", canonical=True)
    shapes = validate_shape_plan_document(plan)
    declaration = plan["threshold_declaration"]
    threshold_path = path.parent / declaration["path"]
    thresholds = _load_json_object(
        threshold_path, "predeclared residual thresholds", canonical=True
    )
    if threshold_path.stat().st_size != declaration["size_bytes"]:
        raise InvalidInputError("predeclared residual-threshold size differs from plan")
    if sha256_file(threshold_path) != declaration["sha256"]:
        raise InvalidInputError("predeclared residual-threshold hash differs from plan")
    _exact_keys(
        thresholds,
        {
            "schema",
            "profile_fingerprint",
            "calibration_method",
            "shape_axes",
            "phase_thresholds",
        },
        "predeclared residual thresholds",
    )
    expected = {
        "schema": THRESHOLD_SCHEMA,
        "profile_fingerprint": planned_profile_fingerprint(plan),
        "calibration_method": "phase_shape_residual_table",
        "shape_axes": ["batch_size", "extend_length", "past_kv_length"],
    }
    for key, value in expected.items():
        if thresholds[key] != value:
            raise InvalidInputError(f"predeclared residual thresholds {key} mismatch")
    phase_thresholds = thresholds["phase_thresholds"]
    if not isinstance(phase_thresholds, dict):
        raise InvalidInputError("phase_thresholds must be an object")
    _exact_keys(phase_thresholds, {"prefill", "decode"}, "phase_thresholds")
    for phase in ("prefill", "decode"):
        raw = phase_thresholds[phase]
        if not isinstance(raw, dict):
            raise InvalidInputError(f"phase_thresholds.{phase} must be an object")
        _exact_keys(
            raw,
            {
                "max_mean_absolute_percentage_error",
                "max_p95_absolute_relative_error",
            },
            f"phase_thresholds.{phase}",
        )
        for field, value in raw.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise InvalidInputError(f"phase_thresholds.{phase}.{field} is invalid")
    return plan, shapes, thresholds


def build_held_out_split(shapes: Sequence[CalibrationShape], seed: int) -> dict[str, object]:
    """Freeze a deterministic, phase-stratified shape split before timing."""

    assignments: dict[str, str] = {}
    for phase in ("prefill", "decode"):
        candidates = [shape for shape in shapes if shape.phase == phase]
        if len(candidates) < 2:
            raise InvalidInputError(
                f"at least two {phase} shapes are required for a held-out split"
            )
        ranked = sorted(
            candidates,
            key=lambda shape: sha256_bytes(
                canonical_json_bytes(
                    {"seed": seed, "shape_id": shape.shape_id, "split_phase": phase}
                )
            ),
        )
        assignments[ranked[0].shape_id] = "held_out"
        assignments.update({shape.shape_id: "train" for shape in ranked[1:]})
    for shape in shapes:
        if shape.phase == "mixed":
            assignments[shape.shape_id] = "mixed_observation_only"

    records = [
        {
            "batch_size": shape.batch_size,
            "extend_lengths": list(shape.extend_lengths),
            "past_kv_lengths": list(shape.past_kv_lengths),
            "phase": shape.phase,
            "shape_id": shape.shape_id,
            "split": assignments[shape.shape_id],
        }
        for shape in shapes
    ]
    return {
        "algorithm": "sha256-seeded-phase-stratified-first-held-out-v1",
        "assignments": records,
        "coverage": {
            "batch_sizes": sorted({shape.batch_size for shape in shapes}),
            "extend_lengths": sorted({item for shape in shapes for item in shape.extend_lengths}),
            "past_kv_lengths": sorted({item for shape in shapes for item in shape.past_kv_lengths}),
            "phases": sorted({shape.phase for shape in shapes}),
            "shape_axes": ["batch_size", "extend_length", "past_kv_length"],
        },
        "frozen_before_measurement": True,
        "seed": seed,
        "schema": SPLIT_SCHEMA,
    }


def _verified_file(path: Path, expected_sha256: str, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise SourceDriftError(f"{label} is missing or unsafe: {path}")
    observed = sha256_file(path)
    if observed != expected_sha256:
        raise SourceDriftError(
            f"{label} SHA-256 drift: observed={observed}, expected={expected_sha256}"
        )
    return {
        "path": str(path),
        "resolved_path": str(path.resolve()),
        "sha256": observed,
        "size_bytes": path.stat().st_size,
        "status": "PASS",
    }


def _git_output(repository: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SourceDriftError(f"git verification failed for {repository}: {error}") from error
    return completed.stdout.strip()


def verify_pinned_inputs(source_lock_path: Path, support_path: Path) -> dict[str, object]:
    """Verify source, model, predictor, and interpreter pins before vLLM import."""

    if Path(sys.executable).resolve() != EXPECTED_RUNTIME_PYTHON.resolve():
        raise SourceDriftError(
            f"wrong runtime Python: {sys.executable}; expected {EXPECTED_RUNTIME_PYTHON}"
        )
    runtime_record = _verified_file(
        EXPECTED_RUNTIME_PYTHON.resolve(),
        EXPECTED_RUNTIME_PYTHON_SHA256,
        "pinned runtime interpreter",
    )
    runtime_record["launcher_path"] = str(EXPECTED_RUNTIME_PYTHON)
    runtime_record["launcher_is_symlink"] = EXPECTED_RUNTIME_PYTHON.is_symlink()
    source_record = _verified_file(source_lock_path, EXPECTED_SOURCE_LOCK_SHA256, "source lock")
    support_record = _verified_file(
        support_path,
        EXPECTED_AICONFIGURATOR_SUPPORT_SHA256,
        "AIConfigurator support audit",
    )
    lock = _load_json_object(source_lock_path, "source lock", canonical=False)
    support = _load_json_object(support_path, "AIConfigurator support audit", canonical=True)

    try:
        vllm_lock = lock["repositories"]["vllm"]
        model_lock = lock["model_tokenizer"]
        provider_lock = support["provider"]
    except (KeyError, TypeError) as error:
        raise SourceDriftError(f"pinned evidence lacks required fields: {error}") from error
    checks = {
        "vllm commit": (vllm_lock.get("commit"), EXPECTED_VLLM_COMMIT),
        "vllm version": (
            vllm_lock.get("observed_generated_version"),
            EXPECTED_VLLM_VERSION,
        ),
        "model id": (model_lock.get("model_id"), EXPECTED_MODEL_ID),
        "model revision": (model_lock.get("revision"), EXPECTED_MODEL_REVISION),
        "model snapshot": (model_lock.get("snapshot_path"), str(EXPECTED_MODEL_SNAPSHOT)),
        "AIConfigurator version": (
            provider_lock.get("package_version"),
            EXPECTED_AICONFIGURATOR_VERSION,
        ),
        "AIConfigurator commit": (
            provider_lock.get("source_commit"),
            EXPECTED_AICONFIGURATOR_COMMIT,
        ),
    }
    mismatches = [
        f"{label}: observed={observed!r}, expected={expected!r}"
        for label, (observed, expected) in checks.items()
        if observed != expected
    ]
    if mismatches:
        raise SourceDriftError("source/model pin drift: " + "; ".join(mismatches))

    try:
        distribution = importlib.metadata.distribution(EXPECTED_VLLM_DISTRIBUTION)
        torch_distribution = importlib.metadata.distribution("torch")
        nvml_distribution = importlib.metadata.distribution("nvidia-ml-py")
    except importlib.metadata.PackageNotFoundError as error:
        raise SourceDriftError(f"pinned runtime distribution is missing: {error}") from error
    if distribution.version != EXPECTED_VLLM_VERSION:
        raise SourceDriftError(f"installed vLLM version drift: {distribution.version}")
    torch_version = torch_distribution.version
    if torch_version != EXPECTED_TORCH_VERSION:
        raise SourceDriftError(
            f"installed torch version drift: {torch_version}; expected {EXPECTED_TORCH_VERSION}"
        )
    if nvml_distribution.version != EXPECTED_NVML_DISTRIBUTION_VERSION:
        raise SourceDriftError(
            "installed nvidia-ml-py version drift: "
            f"{nvml_distribution.version}; expected {EXPECTED_NVML_DISTRIBUTION_VERSION}"
        )
    package_root = Path(str(distribution.locate_file("vllm"))).resolve()
    torch_root = Path(str(torch_distribution.locate_file("torch"))).resolve()
    runtime_semantic_files = [
        _verified_file(
            torch_root / "__init__.py",
            EXPECTED_TORCH_INIT_SHA256,
            "installed torch package initializer",
        ),
        _verified_file(
            torch_root / "_C.cpython-312-x86_64-linux-gnu.so",
            EXPECTED_TORCH_EXTENSION_SHA256,
            "installed torch extension loader",
        ),
        _verified_file(
            Path(str(nvml_distribution.locate_file("pynvml.py"))).resolve(),
            EXPECTED_PYNVML_SHA256,
            "installed pynvml runtime",
        ),
    ]
    verified_vllm: list[dict[str, object]] = []
    for item in vllm_lock["files"]:
        relative = Path(item["path"])
        if relative.parts[0] != "vllm" or ".." in relative.parts:
            raise SourceDriftError(f"unsafe vLLM lock path: {relative}")
        verified_vllm.append(
            _verified_file(
                package_root.joinpath(*relative.parts[1:]),
                item["sha256"],
                f"installed vLLM semantic file {relative}",
            )
        )
    model_runner = package_root.joinpath(*MODEL_RUNNER_RELATIVE.parts[1:])
    model_runner_record = _verified_file(
        model_runner, MODEL_RUNNER_SHA256, "installed GPUModelRunner source"
    )
    model_runner_record["git_blob"] = MODEL_RUNNER_GIT_BLOB
    model_runner_record["symbol"] = MODEL_RUNNER_SYMBOL

    if not EXPECTED_MODEL_SNAPSHOT.is_dir():
        raise SourceDriftError(f"pinned model snapshot is missing: {EXPECTED_MODEL_SNAPSHOT}")
    verified_model: list[dict[str, object]] = []
    model_blob_root = EXPECTED_MODEL_SNAPSHOT.parent.parent / "blobs"
    for item in model_lock["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise SourceDriftError(f"unsafe model lock path: {relative}")
        snapshot_file = EXPECTED_MODEL_SNAPSHOT / relative
        if not snapshot_file.is_symlink():
            raise SourceDriftError(
                f"model critical file is not a pinned snapshot symlink: {snapshot_file}"
            )
        resolved_model_file = snapshot_file.resolve(strict=True)
        if model_blob_root.resolve() not in resolved_model_file.parents:
            raise SourceDriftError(
                f"model critical file escapes the cache blob directory: {snapshot_file}"
            )
        model_record = _verified_file(
            resolved_model_file,
            item["sha256"],
            f"model file {relative}",
        )
        model_record["snapshot_symlink"] = str(snapshot_file)
        verified_model.append(model_record)
    weight_index = json.loads(
        (EXPECTED_MODEL_SNAPSHOT / "model.safetensors.index.json").read_text(encoding="utf-8")
    )
    shard_names = sorted(set(weight_index.get("weight_map", {}).values()))
    if not shard_names:
        raise SourceDriftError("model weight index has no shard names")
    verified_weights: list[dict[str, object]] = []
    for shard_name in shard_names:
        if not isinstance(shard_name, str) or Path(shard_name).name != shard_name:
            raise SourceDriftError(f"unsafe model shard name: {shard_name!r}")
        shard = EXPECTED_MODEL_SNAPSHOT / shard_name
        if not shard.is_symlink():
            raise SourceDriftError(f"model shard is not a pinned cache symlink: {shard}")
        resolved = shard.resolve(strict=True)
        if model_blob_root.resolve() not in resolved.parents:
            raise SourceDriftError(f"model shard escapes the cache blob directory: {shard}")
        if not HEX64.fullmatch(resolved.name):
            raise SourceDriftError(f"model shard target is not SHA-256 addressed: {resolved}")
        record = _verified_file(shard.resolve(), resolved.name, f"model shard {shard_name}")
        record["snapshot_symlink"] = str(shard)
        verified_weights.append(record)

    model_config = json.loads((EXPECTED_MODEL_SNAPSHOT / "config.json").read_text(encoding="utf-8"))
    semantic_keys = (
        "model_type",
        "dtype",
        "hidden_size",
        "num_hidden_layers",
        "num_attention_heads",
        "num_key_value_heads",
        "head_dim",
        "max_position_embeddings",
        "rope_theta",
        "rope_scaling",
    )
    declared_model_config = model_lock["model_config"]
    observed_model_semantics = {key: model_config.get(key) for key in semantic_keys}
    observed_model_semantics["dtype"] = model_config.get("dtype", model_config.get("torch_dtype"))
    semantic_mismatches = [
        f"{key}: observed={observed_model_semantics.get(key)!r}, "
        f"expected={declared_model_config.get(key)!r}"
        for key in semantic_keys
        if observed_model_semantics.get(key) != declared_model_config.get(key)
    ]
    if semantic_mismatches:
        raise SourceDriftError("model config semantics drift: " + "; ".join(semantic_mismatches))

    observed_aic_head = _git_output(EXPECTED_AICONFIGURATOR_REPOSITORY, "rev-parse", "HEAD")
    if observed_aic_head != EXPECTED_AICONFIGURATOR_COMMIT:
        raise SourceDriftError(f"AIConfigurator checkout HEAD drift: {observed_aic_head}")
    semantic_lock = provider_lock["semantic_source_lock"]
    verified_aic: list[dict[str, object]] = []
    for relative_text, expected_hash in sorted(semantic_lock["files"].items()):
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise SourceDriftError(f"unsafe AIConfigurator path: {relative}")
        verified_aic.append(
            _verified_file(
                EXPECTED_AICONFIGURATOR_REPOSITORY / relative,
                expected_hash,
                f"AIConfigurator semantic file {relative}",
            )
        )

    return {
        "aiconfigurator": {
            "commit": EXPECTED_AICONFIGURATOR_COMMIT,
            "repository": str(EXPECTED_AICONFIGURATOR_REPOSITORY),
            "semantic_files": verified_aic,
            "version": EXPECTED_AICONFIGURATOR_VERSION,
        },
        "model": {
            "critical_files": verified_model,
            "id": EXPECTED_MODEL_ID,
            "revision": EXPECTED_MODEL_REVISION,
            "snapshot": str(EXPECTED_MODEL_SNAPSHOT),
            "config_semantics": observed_model_semantics,
            "weight_shards": verified_weights,
        },
        "runtime": {
            "interpreter": runtime_record,
            "nvidia_ml_py_version": nvml_distribution.version,
            "python_version": sys.version,
            "semantic_files": runtime_semantic_files,
            "torch_version": torch_version,
            "vllm_distribution": str(distribution.metadata["Name"]),
            "vllm_version": distribution.version,
        },
        "source_lock": source_record,
        "status": "PASS",
        "support_audit": support_record,
        "vllm": {
            "commit": EXPECTED_VLLM_COMMIT,
            "model_runner": model_runner_record,
            "semantic_files": verified_vllm,
        },
    }


def validate_slurm_environment(environment: Mapping[str, str]) -> dict[str, str]:
    job_id = environment.get("SLURM_JOB_ID", "")
    if not job_id.isdigit():
        raise GPUMismatchError("SLURM_JOB_ID must be numeric")
    visible = [item.strip() for item in environment.get("CUDA_VISIBLE_DEVICES", "").split(",")]
    visible = [item for item in visible if item]
    if len(visible) != 1:
        raise GPUMismatchError("exactly one Slurm-visible CUDA device is required")
    partition = environment.get("SLURM_JOB_PARTITION", "")
    if partition != "short":
        raise GPUMismatchError(f"assigned-L40S run requires short, observed {partition!r}")
    if environment.get("MOONKVSIM_ASSIGNED_GPU_ALLOCATION") != "PASS":
        raise GPUMismatchError("wrapper did not verify the assigned L40S GRES binding")
    if environment.get("MOONKVSIM_BATCH_SCRIPT_CAPTURE_STATUS") != "PASS":
        raise SourceDriftError("Slurm-spooled wrapper capture did not pass")
    partition_oversubscribe = environment.get("MOONKVSIM_SLURM_PARTITION_OVERSUBSCRIBE", "")
    if partition_oversubscribe != "FORCE:4":
        raise GPUMismatchError(
            "short partition CPU sharing policy drifted from OverSubscribe=FORCE:4"
        )
    job_oversubscribe = environment.get("MOONKVSIM_SLURM_JOB_OVERSUBSCRIBE", "")
    if not job_oversubscribe:
        raise GPUMismatchError("Slurm job OverSubscribe field was not captured")
    return {
        "assigned_gpu_allocation": "PASS",
        "cpus_per_task": environment.get("SLURM_CPUS_PER_TASK", ""),
        "cuda_visible_devices": visible[0],
        "gres": environment.get("SLURM_JOB_GRES", ""),
        "job_oversubscribe": job_oversubscribe,
        "job_gpus": environment.get("SLURM_JOB_GPUS", ""),
        "job_id": job_id,
        "memory_per_node": environment.get("SLURM_MEM_PER_NODE", ""),
        "node": environment.get("SLURMD_NODENAME", environment.get("HOSTNAME", "")),
        "partition": partition,
        "partition_oversubscribe": partition_oversubscribe,
        "submit_dir": environment.get("SLURM_SUBMIT_DIR", ""),
        "whole_node_exclusive_verified": "false",
    }


def validate_launch_provenance(
    staging_dir: Path, environment: Mapping[str, str]
) -> dict[str, object]:
    resolved_staging = staging_dir.resolve()
    if resolved_staging.parent != Path("/tmp") and Path("/tmp") not in resolved_staging.parents:
        raise SourceDriftError("staging directory must resolve beneath /tmp")
    executing = Path(__file__).resolve()
    if executing.parent != resolved_staging:
        raise SourceDriftError("harness must execute the copy staged under /tmp")
    expected_harness = environment.get("MOONKVSIM_CALIBRATION_SCRIPT_SHA256", "")
    expected_wrapper = environment.get("MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256", "")
    if not HEX64.fullmatch(expected_harness) or not HEX64.fullmatch(expected_wrapper):
        raise SourceDriftError("launch provenance hashes are missing or malformed")
    harness_record = _verified_file(executing, expected_harness, "executing staged harness")
    wrapper_record = _verified_file(
        resolved_staging / "submitted-batch-script.sh",
        expected_wrapper,
        "Slurm-spooled batch wrapper",
    )
    return {
        "executing_harness": harness_record,
        "repository_wrapper_used_as_substitute": False,
        "slurm_spooled_batch_script": wrapper_record,
        "staging_directory": str(resolved_staging),
        "status": "PASS",
    }


def _nvml_call(module: Any, callable_value: Callable[..., Any], *arguments: Any) -> Any:
    try:
        value = callable_value(*arguments)
    except module.NVMLError:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _nvml_processes(module: Any, handle: Any) -> list[dict[str, object]]:
    records: dict[int, dict[str, object]] = {}
    for kind, getter in (
        ("compute", module.nvmlDeviceGetComputeRunningProcesses),
        ("graphics", module.nvmlDeviceGetGraphicsRunningProcesses),
    ):
        try:
            processes = getter(handle)
        except module.NVMLError_NotSupported:
            processes = []
        for process in processes:
            pid = int(process.pid)
            record = records.setdefault(
                pid,
                {
                    "kinds": [],
                    "pid": pid,
                    "used_gpu_memory_bytes": int(getattr(process, "usedGpuMemory", 0)),
                },
            )
            kinds = record["kinds"]
            assert isinstance(kinds, list)
            kinds.append(kind)
            record["name"] = (
                _nvml_call(module, module.nvmlSystemGetProcessName, pid)
                or "process_exited_during_snapshot"
            )
    return [records[pid] for pid in sorted(records)]


def inspect_assigned_gpu(*, allowed_pids: set[int]) -> dict[str, object]:
    """Inspect only CUDA ordinal zero and reject every unrelated process."""

    try:
        import pynvml  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]
    except ImportError as error:
        raise GPUMismatchError(f"GPU inspection dependency unavailable: {error}") from error
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise GPUMismatchError("torch must see exactly one CUDA device")
    properties = torch.cuda.get_device_properties(0)
    if properties.name != "NVIDIA L40S":
        raise GPUMismatchError(f"expected NVIDIA L40S, observed {properties.name!r}")
    if not (47_000_000_000 <= int(properties.total_memory) <= 50_000_000_000):
        raise GPUMismatchError(f"unexpected L40S memory size {int(properties.total_memory)}")
    raw_uuid = str(properties.uuid)
    uuid = raw_uuid if raw_uuid.startswith("GPU-") else f"GPU-{raw_uuid}"
    pynvml.nvmlInit()
    try:
        handle = pynvml.nvmlDeviceGetHandleByUUID(uuid.encode("ascii"))
        observed_uuid = _nvml_call(pynvml, pynvml.nvmlDeviceGetUUID, handle)
        if observed_uuid != uuid:
            raise GPUMismatchError(f"torch/NVML UUID mismatch: torch={uuid}, nvml={observed_uuid}")
        processes = _nvml_processes(pynvml, handle)
        foreign = [record for record in processes if record["pid"] not in allowed_pids]
        if foreign:
            raise GPUMismatchError(f"foreign process present on allocated L40S: {foreign}")
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        pci = pynvml.nvmlDeviceGetPciInfo(handle)
        driver = _nvml_call(pynvml, pynvml.nvmlSystemGetDriverVersion)
        clock = getattr(pynvml, "NVML_CLOCK_GRAPHICS", 0)
        memory_clock = getattr(pynvml, "NVML_CLOCK_MEM", 2)
        profile = {
            "application_graphics_clock_mhz": _nvml_call(
                pynvml, pynvml.nvmlDeviceGetApplicationsClock, handle, clock
            ),
            "application_memory_clock_mhz": _nvml_call(
                pynvml, pynvml.nvmlDeviceGetApplicationsClock, handle, memory_clock
            ),
            "compute_capability": [properties.major, properties.minor],
            "compute_mode": _nvml_call(pynvml, pynvml.nvmlDeviceGetComputeMode, handle),
            "driver_version": str(driver),
            "max_graphics_clock_mhz": _nvml_call(
                pynvml, pynvml.nvmlDeviceGetMaxClockInfo, handle, clock
            ),
            "max_memory_clock_mhz": _nvml_call(
                pynvml, pynvml.nvmlDeviceGetMaxClockInfo, handle, memory_clock
            ),
            "name": properties.name,
            "nvml_total_memory_bytes": int(memory.total),
            "pci_bus_id": (
                pci.busId.decode("ascii") if isinstance(pci.busId, bytes) else str(pci.busId)
            ),
            "persistence_mode": _nvml_call(pynvml, pynvml.nvmlDeviceGetPersistenceMode, handle),
            "power_limit_mw": _nvml_call(pynvml, pynvml.nvmlDeviceGetPowerManagementLimit, handle),
            "torch_cuda_version": torch.version.cuda,
            "torch_version": torch.__version__,
            "total_memory_bytes": int(properties.total_memory),
            "uuid": uuid,
        }
        return {
            "allowed_process_ids": sorted(allowed_pids),
            "cuda_ordinal_inspected": 0,
            "foreign_processes": [],
            "free_memory_bytes": int(memory.free),
            "hardware_profile": profile,
            "hardware_profile_fingerprint": sha256_bytes(canonical_json_bytes(profile)),
            "only_slurm_visible_gpu_inspected": True,
            "processes": processes,
            "status": "PASS",
        }
    finally:
        pynvml.nvmlShutdown()


def capture_nvidia_smi_q(staging_dir: Path, boundary: str, uuid: str) -> dict[str, object]:
    if boundary not in {"pre", "post"}:
        raise ValueError(f"invalid GPU boundary {boundary!r}")
    output = staging_dir / f"nvidia-smi-q.{boundary}.txt"
    try:
        completed = subprocess.run(
            ["nvidia-smi", "-q", "-i", uuid],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GPUMismatchError(f"nvidia-smi -q failed: {error}") from error
    with output.open("xb") as stream:
        stream.write(completed.stdout)
        stream.flush()
        os.fsync(stream.fileno())
    if completed.returncode != 0 or not completed.stdout:
        raise GPUMismatchError(f"nvidia-smi -q returned {completed.returncode} for assigned UUID")
    return {
        "path": output.name,
        "return_code": completed.returncode,
        "sha256": sha256_file(output),
        "size_bytes": output.stat().st_size,
    }


@dataclass(frozen=True, slots=True)
class SchedulerMetadata:
    num_scheduled_tokens: dict[str, int]
    total_num_scheduled_tokens: int


@dataclass(frozen=True, slots=True)
class ObservedSchedulerShape:
    phase: str
    extend_lengths: tuple[int, ...]
    past_kv_lengths: tuple[int, ...]
    prompt_lengths: tuple[int, ...]
    request_ids: tuple[str, ...]
    scheduled_token_budget: int
    model_runner_input_fingerprint: str


def scheduler_metadata_from_output(scheduler_output: object) -> SchedulerMetadata:
    raw = getattr(scheduler_output, "num_scheduled_tokens", None)
    total = getattr(scheduler_output, "total_num_scheduled_tokens", None)
    if not isinstance(raw, dict) or not raw:
        raise ShapeConstructionError("SchedulerOutput has no scheduled-token mapping")
    normalized: dict[str, int] = {}
    for request_id, count in raw.items():
        if not isinstance(request_id, str) or not request_id:
            raise ShapeConstructionError("SchedulerOutput request id is invalid")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ShapeConstructionError("SchedulerOutput scheduled-token count is invalid")
        normalized[request_id] = count
    if isinstance(total, bool) or not isinstance(total, int) or total != sum(normalized.values()):
        raise ShapeConstructionError("SchedulerOutput total token budget is inconsistent")
    return SchedulerMetadata(normalized, total)


def derive_observed_scheduler_shape(
    runner: object, metadata: SchedulerMetadata
) -> ObservedSchedulerShape:
    input_batch = getattr(runner, "input_batch", None)
    if input_batch is None:
        raise ShapeConstructionError("GPUModelRunner has no input_batch")
    request_ids_raw = getattr(input_batch, "req_ids", None)
    computed_raw: Any = getattr(input_batch, "num_computed_tokens_cpu", None)
    prompt_raw: Any = getattr(input_batch, "num_prompt_tokens", None)
    if not isinstance(request_ids_raw, list) or not request_ids_raw:
        raise ShapeConstructionError("GPUModelRunner request IDs are missing")
    request_ids = tuple(request_ids_raw)
    if any(not isinstance(item, str) or not item for item in request_ids):
        raise ShapeConstructionError("GPUModelRunner request IDs are invalid")
    if len(set(request_ids)) != len(request_ids):
        raise ShapeConstructionError("GPUModelRunner request IDs are not unique")
    if set(request_ids) != set(metadata.num_scheduled_tokens):
        raise ShapeConstructionError(
            "SchedulerOutput and GPUModelRunner request IDs do not join one-to-one"
        )
    if computed_raw is None or prompt_raw is None:
        raise ShapeConstructionError("GPUModelRunner counter vectors are missing")
    try:
        past = tuple(int(computed_raw[index]) for index in range(len(request_ids)))
        prompt = tuple(int(prompt_raw[index]) for index in range(len(request_ids)))
    except (IndexError, TypeError, ValueError) as error:
        raise ShapeConstructionError(
            f"GPUModelRunner counter vectors cannot be joined: {error}"
        ) from error
    extend = tuple(metadata.num_scheduled_tokens[item] for item in request_ids)
    if any(item < 0 for item in past) or any(item <= 0 for item in prompt):
        raise ShapeConstructionError("GPUModelRunner pre-step counters are invalid")
    if metadata.total_num_scheduled_tokens != sum(extend):
        raise ShapeConstructionError("ordered extension vector changes scheduled budget")
    member_phases: list[str] = []
    for extension, previous, prompt_length in zip(extend, past, prompt, strict=True):
        if previous < prompt_length:
            member_phases.append("prefill")
        elif extension == 1:
            member_phases.append("decode")
        else:
            raise ShapeConstructionError(
                "a request past prompt completion has extension other than one"
            )
    phase_set = set(member_phases)
    if phase_set == {"prefill"}:
        phase = "prefill"
    elif phase_set == {"decode"}:
        phase = "decode"
    elif phase_set == {"prefill", "decode"}:
        phase = "mixed"
    else:
        raise ShapeConstructionError("scheduler step phase cannot be classified")
    fingerprint_input = {
        "extend_lengths": list(extend),
        "past_kv_lengths": list(past),
        "prompt_lengths": list(prompt),
        "request_ids": list(request_ids),
        "scheduled_token_budget": metadata.total_num_scheduled_tokens,
    }
    return ObservedSchedulerShape(
        phase=phase,
        extend_lengths=extend,
        past_kv_lengths=past,
        prompt_lengths=prompt,
        request_ids=request_ids,
        scheduled_token_budget=metadata.total_num_scheduled_tokens,
        model_runner_input_fingerprint=sha256_bytes(canonical_json_bytes(fingerprint_input)),
    )


@dataclass(frozen=True, slots=True)
class StepExpectation:
    shape: CalibrationShape
    record_sample: bool
    warmup: bool = False
    repeat_index: int = 0
    role: str = "target"


class AppendOnlyJSONL(AbstractContextManager["AppendOnlyJSONL"]):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._stream: TextIO | None = None

    def __enter__(self) -> AppendOnlyJSONL:
        self._stream = self.path.open("x", encoding="utf-8", newline="\n")
        return self

    def append(self, value: Mapping[str, object]) -> None:
        if self._stream is None:
            raise RuntimeError("append-only JSONL is not open")
        self._stream.write(canonical_json_bytes(dict(value)).decode("utf-8"))
        self._stream.flush()
        os.fsync(self._stream.fileno())

    def __exit__(self, *args: object) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None


class ForwardCalibrationController:
    """Single-step controller shared with the in-process pinned model runner."""

    def __init__(
        self,
        *,
        hardware_profile_fingerprint: str,
        profile_fingerprint: str,
    ) -> None:
        if not HEX64.fullmatch(hardware_profile_fingerprint):
            raise ValueError("invalid hardware profile fingerprint")
        if not HEX64.fullmatch(profile_fingerprint):
            raise ValueError("invalid campaign profile fingerprint")
        self.hardware_profile_fingerprint = hardware_profile_fingerprint
        self.profile_fingerprint = profile_fingerprint
        self.expectation: StepExpectation | None = None
        self.completed = False
        self.raw_writer: AppendOnlyJSONL | None = None
        self.metadata_writer: AppendOnlyJSONL | None = None
        self.sample_count = 0
        self.scheduler_step_count = 0
        self.warmup_count = 0

    def bind_metadata_writer(self, metadata_writer: AppendOnlyJSONL) -> None:
        self.metadata_writer = metadata_writer

    def bind_raw_writer(self, raw_writer: AppendOnlyJSONL) -> None:
        self.raw_writer = raw_writer

    def bind_writers(self, raw_writer: AppendOnlyJSONL, metadata_writer: AppendOnlyJSONL) -> None:
        self.bind_raw_writer(raw_writer)
        self.bind_metadata_writer(metadata_writer)

    def begin_step(self, expectation: StepExpectation) -> None:
        if self.expectation is not None:
            raise ShapeConstructionError("previous scheduler expectation was not cleared")
        self.expectation = expectation
        self.completed = False

    def finish_step(self) -> None:
        if self.expectation is None or not self.completed:
            raise ShapeConstructionError("expected scheduler step did not reach _model_forward")
        self.expectation = None
        self.completed = False

    def run_model_forward(
        self,
        runner: object,
        original: Callable[..., Any],
        args: tuple[object, ...],
        kwargs: dict[str, object],
        metadata: SchedulerMetadata,
    ) -> Any:
        expectation = self.expectation
        if expectation is None:
            raise ShapeConstructionError("unexpected scheduler-driven _model_forward call")
        if self.completed:
            raise ShapeConstructionError("one scheduler step invoked _model_forward twice")
        observed = derive_observed_scheduler_shape(runner, metadata)
        expected = expectation.shape
        actual_identity = (
            observed.phase,
            observed.extend_lengths,
            observed.past_kv_lengths,
        )
        expected_identity = (
            expected.phase,
            expected.extend_lengths,
            expected.past_kv_lengths,
        )
        if actual_identity != expected_identity:
            raise ShapeConstructionError(
                "scheduler shape differs from requested ordered vectors: "
                f"observed={actual_identity}, expected={expected_identity}"
            )
        request_ids_sha256 = sha256_bytes(canonical_json_bytes(list(observed.request_ids)))
        metadata_record = {
            "batch_size": len(observed.extend_lengths),
            "cudagraph_mode": "NONE",
            "extend_lengths": list(observed.extend_lengths),
            "measurement_role": expectation.role,
            "model_internal_collective": "none_tp1",
            "model_runner_input_fingerprint": observed.model_runner_input_fingerprint,
            "past_kv_lengths": list(observed.past_kv_lengths),
            "phase": observed.phase,
            "pipeline_parallel_rank": 0,
            "prompt_lengths": list(observed.prompt_lengths),
            "repeat_index": expectation.repeat_index,
            "request_count": len(observed.request_ids),
            "request_ids_sha256": request_ids_sha256,
            "scheduled_token_budget": observed.scheduled_token_budget,
            "schema": STEP_METADATA_SCHEMA,
            "shape_id": expected.shape_id,
            "tensor_parallel_rank": 0,
            "warmup": expectation.warmup,
        }
        if not expectation.record_sample:
            result = original(runner, *args, **kwargs)
            if self.metadata_writer is not None:
                self.metadata_writer.append(metadata_record)
                self.scheduler_step_count += 1
            self.completed = True
            return result
        if self.raw_writer is None or self.metadata_writer is None:
            raise CUDATimingError("measurement writers are not bound")

        try:
            import torch

            if not torch.cuda.is_available():
                raise CUDATimingError("CUDA events are unavailable")
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            result = original(runner, *args, **kwargs)
            end.record()
            end.synchronize()
            elapsed_ms = float(start.elapsed_time(end))
        except CUDATimingError:
            raise
        except BaseException as error:
            if is_cuda_oom(error):
                raise
            raise CUDATimingError(f"CUDA event timing failed: {error}") from error
        duration_ns = round(elapsed_ms * 1_000_000)
        if not math.isfinite(elapsed_ms) or duration_ns <= 0:
            raise CUDATimingError(f"CUDA event returned non-positive duration {elapsed_ms!r} ms")
        sample = {
            "batch_size": len(observed.extend_lengths),
            "cudagraph_mode": "NONE",
            "duration_ns": duration_ns,
            "extend_lengths": list(observed.extend_lengths),
            "hardware_profile_fingerprint": self.hardware_profile_fingerprint,
            "measurement_method": MEASUREMENT_METHOD,
            "model_runner_source_sha256": MODEL_RUNNER_SHA256,
            "past_kv_lengths": list(observed.past_kv_lengths),
            "phase": observed.phase,
            "pipeline_parallel_rank": 0,
            "profile_fingerprint": self.profile_fingerprint,
            "repeat_index": expectation.repeat_index,
            "request_ids_sha256": request_ids_sha256,
            "schema": SAMPLE_SCHEMA,
            "shape_id": expected.shape_id,
            "tensor_parallel_rank": 0,
            "warmup": expectation.warmup,
        }
        if set(sample) != _SAMPLE_KEYS:
            raise AssertionError("raw sample field set drifted")
        self.raw_writer.append(sample)
        self.metadata_writer.append(metadata_record)
        self.scheduler_step_count += 1
        self.sample_count += int(not expectation.warmup)
        self.warmup_count += int(expectation.warmup)
        self.completed = True
        return result


_ACTIVE_CONTROLLER: ForwardCalibrationController | None = None
_INSTRUMENTED = False


def install_pinned_model_runner_instrumentation(
    controller: ForwardCalibrationController,
) -> dict[str, object]:
    """Patch the installed class in memory; never modify the vLLM source tree."""

    global _ACTIVE_CONTROLLER, _INSTRUMENTED
    if _INSTRUMENTED:
        raise SourceDriftError("GPUModelRunner instrumentation was already installed")
    from vllm.v1.worker.gpu_model_runner import (  # type: ignore[import-not-found]
        GPUModelRunner,
    )

    source_path = Path(inspect.getsourcefile(GPUModelRunner) or "").resolve()
    if sha256_file(source_path) != MODEL_RUNNER_SHA256:
        raise SourceDriftError("imported GPUModelRunner source hash changed after import")
    original_execute = GPUModelRunner.execute_model
    original_forward = GPUModelRunner._model_forward

    @wraps(original_execute)
    def execute_model_wrapper(
        runner: object, scheduler_output: object, *args: object, **kwargs: object
    ) -> Any:
        metadata = scheduler_metadata_from_output(scheduler_output)
        if hasattr(runner, "_moonkvsim_scheduler_metadata"):
            raise ShapeConstructionError("nested scheduler metadata handoff")
        runner.__dict__["_moonkvsim_scheduler_metadata"] = metadata
        try:
            return original_execute(runner, scheduler_output, *args, **kwargs)
        finally:
            if hasattr(runner, "_moonkvsim_scheduler_metadata"):
                delattr(runner, "_moonkvsim_scheduler_metadata")

    @wraps(original_forward)
    def model_forward_wrapper(runner: object, *args: object, **kwargs: object) -> Any:
        metadata = getattr(runner, "_moonkvsim_scheduler_metadata", None)
        active = _ACTIVE_CONTROLLER
        # Model-load memory profiling and other direct dummy forwards are not
        # scheduler steps and are deliberately outside raw calibration.
        if metadata is None:
            return original_forward(runner, *args, **kwargs)
        if not isinstance(metadata, SchedulerMetadata) or active is None:
            raise ShapeConstructionError("scheduler metadata reached an inactive timing hook")
        return active.run_model_forward(
            runner,
            original_forward,
            args,
            dict(kwargs),
            metadata,
        )

    GPUModelRunner.execute_model = execute_model_wrapper
    GPUModelRunner._model_forward = model_forward_wrapper
    _ACTIVE_CONTROLLER = controller
    _INSTRUMENTED = True
    return {
        "installation": "in_memory_monkeypatch_only",
        "model_runner_git_blob": MODEL_RUNNER_GIT_BLOB,
        "model_runner_source_sha256": MODEL_RUNNER_SHA256,
        "outer_execute_model_role": "scheduler_metadata_handoff_only",
        "source_tree_modified": False,
        "symbol": MODEL_RUNNER_SYMBOL,
        "timing_boundary": "cuda_events_immediately_inside_model_forward_wrapper",
    }


def is_cuda_oom(error: BaseException) -> bool:
    name = type(error).__name__.lower()
    message = str(error).lower()
    return "outofmemory" in name or "cuda out of memory" in message


def _sampling_params(max_tokens: int) -> object:
    from vllm import SamplingParams  # type: ignore[import-not-found]

    return SamplingParams(
        temperature=0.0,
        max_tokens=max_tokens,
        seed=0,
        ignore_eos=True,
        detokenize=False,
        skip_special_tokens=False,
    )


def _tokens_prompt(length: int) -> object:
    from vllm.inputs import TokensPrompt  # type: ignore[import-not-found]

    return TokensPrompt(prompt_token_ids=[PROMPT_TOKEN_ID] * length)


class CalibrationEngine(Protocol):
    vllm_config: Any
    engine_core: Any

    def add_request(self, request_id: str, prompt: object, params: object) -> object: ...

    def step(self) -> object: ...

    def has_unfinished_requests(self) -> bool: ...


class ShapeDriver:
    def __init__(self, engine: CalibrationEngine, controller: ForwardCalibrationController) -> None:
        self.engine = engine
        self.controller = controller
        self.request_counter = 0

    def _add(self, prompt_length: int, max_tokens: int, label: str) -> None:
        request_id = f"moonkv-{self.request_counter:08d}-{label}"
        self.request_counter += 1
        self.engine.add_request(
            request_id,
            _tokens_prompt(prompt_length),
            _sampling_params(max_tokens),
        )

    def _step(self, expectation: StepExpectation) -> None:
        self.controller.begin_step(expectation)
        self.engine.step()
        self.controller.finish_step()

    def run_shape(
        self,
        shape: CalibrationShape,
        *,
        record_sample: bool,
        warmup: bool = False,
        repeat_index: int = 0,
    ) -> None:
        if self.engine.has_unfinished_requests():
            raise ShapeConstructionError("engine was not empty before a shape trial")
        target = StepExpectation(
            shape,
            record_sample=record_sample,
            warmup=warmup,
            repeat_index=repeat_index,
            role="target" if record_sample else "feasibility_target",
        )
        if shape.phase == "prefill":
            if any(shape.past_kv_lengths):
                raise ShapeConstructionError(
                    "minimal native harness cannot seed nonzero prefill past KV exactly"
                )
            for extension in shape.extend_lengths:
                self._add(extension, 1, "prefill")
            self._step(target)
        elif shape.phase == "decode":
            for previous in shape.past_kv_lengths:
                self._add(previous, 2, "decode")
            setup = CalibrationShape(
                "prefill",
                shape.past_kv_lengths,
                tuple(0 for _ in shape.past_kv_lengths),
            )
            self._step(
                StepExpectation(
                    setup,
                    record_sample=False,
                    warmup=warmup,
                    repeat_index=repeat_index,
                    role=("measurement_setup" if record_sample else "feasibility_setup"),
                )
            )
            self._step(target)
        elif shape.phase == "mixed":
            decode_indices = [
                index
                for index, (extension, previous) in enumerate(
                    zip(shape.extend_lengths, shape.past_kv_lengths, strict=True)
                )
                if extension == 1 and previous > 0
            ]
            prefill_indices = [
                index for index, extension in enumerate(shape.extend_lengths) if extension > 1
            ]
            if decode_indices + prefill_indices != list(range(shape.batch_size)):
                raise ShapeConstructionError(
                    "mixed construction requires ordered decode members before prefill members"
                )
            if any(shape.past_kv_lengths[index] for index in prefill_indices):
                raise ShapeConstructionError(
                    "minimal mixed construction requires zero-past prefill members"
                )
            decode_past = tuple(shape.past_kv_lengths[index] for index in decode_indices)
            for previous in decode_past:
                self._add(previous, 2, "mixed-decode")
            setup = CalibrationShape("prefill", decode_past, tuple(0 for _ in decode_past))
            self._step(
                StepExpectation(
                    setup,
                    record_sample=False,
                    warmup=warmup,
                    repeat_index=repeat_index,
                    role=("measurement_setup" if record_sample else "feasibility_setup"),
                )
            )
            for index in prefill_indices:
                self._add(shape.extend_lengths[index], 1, "mixed-prefill")
            self._step(target)
        else:
            raise ShapeConstructionError(f"unsupported phase {shape.phase!r}")
        if self.engine.has_unfinished_requests():
            raise ShapeConstructionError("shape trial left unfinished requests")


def maximum_scheduler_token_budget(shapes: Sequence[CalibrationShape]) -> int:
    budgets: list[int] = []
    for shape in shapes:
        budgets.append(sum(shape.extend_lengths))
        if shape.phase == "decode":
            budgets.append(sum(shape.past_kv_lengths))
        elif shape.phase == "mixed":
            budgets.append(
                sum(
                    previous
                    for extension, previous in zip(
                        shape.extend_lengths, shape.past_kv_lengths, strict=True
                    )
                    if extension == 1
                )
            )
    return max(budgets)


def create_engine(shapes: Sequence[CalibrationShape]) -> CalibrationEngine:
    from vllm import EngineArgs, LLMEngine

    max_num_seqs = max(shape.batch_size for shape in shapes)
    max_num_batched_tokens = maximum_scheduler_token_budget(shapes)
    arguments = EngineArgs(
        model=str(EXPECTED_MODEL_SNAPSHOT),
        tokenizer=str(EXPECTED_MODEL_SNAPSHOT),
        skip_tokenizer_init=True,
        trust_remote_code=False,
        dtype="bfloat16",
        tensor_parallel_size=1,
        pipeline_parallel_size=1,
        max_model_len=MAX_MODEL_LEN,
        gpu_memory_utilization=0.90,
        enforce_eager=True,
        disable_custom_all_reduce=True,
        block_size=16,
        attention_backend="FLASH_ATTN",
        max_num_seqs=max_num_seqs,
        max_num_batched_tokens=max_num_batched_tokens,
        enable_chunked_prefill=True,
        enable_prefix_caching=False,
        swap_space=0,
        seed=0,
        disable_log_stats=True,
    )
    engine = LLMEngine.from_engine_args(arguments, enable_multiprocessing=False)
    config = engine.vllm_config
    backend = config.attention_config.backend
    backend_name = getattr(backend, "name", str(backend))
    checks = {
        "attention_backend": (backend_name, "FLASH_ATTN"),
        "block_size": (config.cache_config.block_size, 16),
        "dtype": (str(config.model_config.dtype), "torch.bfloat16"),
        "max_model_len": (config.model_config.max_model_len, MAX_MODEL_LEN),
        "pipeline_parallel_size": (config.parallel_config.pipeline_parallel_size, 1),
        "tensor_parallel_size": (config.parallel_config.tensor_parallel_size, 1),
    }
    mismatches = [
        f"{name}: observed={observed!r}, expected={expected!r}"
        for name, (observed, expected) in checks.items()
        if observed != expected
    ]
    if mismatches:
        engine.engine_core.shutdown()
        raise SourceDriftError("resolved vLLM runtime config drift: " + "; ".join(mismatches))
    return cast(CalibrationEngine, engine)


def shutdown_engine(engine: CalibrationEngine | None) -> None:
    if engine is None:
        return
    try:
        engine.engine_core.shutdown()
    finally:
        del engine
        gc.collect()


def _artifact_records(staging_dir: Path, excluded: set[str]) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for path in sorted(staging_dir.iterdir(), key=lambda item: item.name):
        if path.name in excluded:
            continue
        if path.is_symlink() or not path.is_file():
            raise PublicationError(f"unsafe staging entry: {path}")
        records[path.name] = {
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return records


def _write_sha256sums(staging_dir: Path) -> None:
    output = staging_dir / "SHA256SUMS"
    with output.open("xb") as stream:
        for path in sorted(staging_dir.iterdir(), key=lambda item: item.name):
            if path.name == output.name:
                continue
            if path.is_symlink() or not path.is_file():
                raise PublicationError(f"unsafe checksum input: {path}")
            stream.write(f"{sha256_file(path)}  {path.name}\n".encode())
        stream.flush()
        os.fsync(stream.fileno())


def verify_sha256sums(directory: Path) -> None:
    checksum_file = directory / "SHA256SUMS"
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or not HEX64.fullmatch(digest) or Path(name).name != name:
            raise PublicationError(f"invalid SHA256SUMS entry {line!r}")
        path = directory / name
        if path.is_symlink() or not path.is_file() or sha256_file(path) != digest:
            raise PublicationError(f"published checksum mismatch for {name}")


def publish_staging_no_clobber(staging_dir: Path, final_dir: Path) -> None:
    """Copy a flat /tmp staging bundle into a new, fail-marked directory."""

    if final_dir.exists() or final_dir.is_symlink():
        raise PublicationError(f"refusing existing output root: {final_dir}")
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        final_dir.mkdir(mode=0o750)
    except FileExistsError as error:
        raise PublicationError(f"refusing existing output root: {final_dir}") from error
    incomplete = final_dir / "PUBLICATION_INCOMPLETE"
    incomplete.write_text("publication in progress\n", encoding="utf-8")
    try:
        for source in sorted(staging_dir.iterdir(), key=lambda item: item.name):
            if source.is_symlink() or not source.is_file():
                raise PublicationError(f"unsafe staging entry: {source}")
            target = final_dir / source.name
            with source.open("rb") as input_stream, target.open("xb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream, length=8 * 1024 * 1024)
                output_stream.flush()
                os.fsync(output_stream.fileno())
        verify_sha256sums(final_dir)
        completion = {
            "formal_use_allowed": False,
            "no_clobber": True,
            "schema": "moonkvsim.aiconfigurator-forward-publication.v1",
            "sha256sums_sha256": sha256_file(final_dir / "SHA256SUMS"),
            "status": "COMPLETE",
        }
        write_canonical_json(final_dir / "PUBLICATION_COMPLETE.json", completion)
        incomplete.unlink()
        descriptor = os.open(final_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except BaseException as error:
        if isinstance(error, PublicationError):
            raise
        raise PublicationError(f"publication failed: {error}") from error


def _prepare_manifest(
    staging_dir: Path,
    *,
    status: str,
    plan: Mapping[str, Any],
    slurm: Mapping[str, str],
    hardware_profile_fingerprint: str,
    sample_count: int,
    scheduler_step_count: int,
    warmup_count: int,
) -> dict[str, object]:
    artifacts = _artifact_records(staging_dir, {"manifest.json", "SHA256SUMS"})
    return {
        "artifacts": artifacts,
        "evidence_label": {
            "calibrated_profile": False,
            "class": "physical_forward_raw_calibration_input",
            "formal_use_allowed": False,
            "paper_result_allowed": False,
            "reducer_required": True,
        },
        "formal_use_allowed": False,
        "hardware_profile_fingerprint": hardware_profile_fingerprint,
        "instrumentation": {
            "measurement_method": MEASUREMENT_METHOD,
            "model_runner_git_blob": MODEL_RUNNER_GIT_BLOB,
            "model_runner_source_sha256": MODEL_RUNNER_SHA256,
            "outer_execute_model_role": "scheduler_metadata_handoff_only",
            "source_tree_modified": False,
            "symbol": MODEL_RUNNER_SYMBOL,
        },
        "isolation_boundary": {
            "assigned_gpu_gres_verified": slurm["assigned_gpu_allocation"] == "PASS",
            "cuda_visible_device_count": 1,
            "foreign_gpu_processes_rejected_pre_and_post": True,
            "job_oversubscribe": slurm["job_oversubscribe"],
            "partition_oversubscribe": slurm["partition_oversubscribe"],
            "scope": "assigned_slurm_visible_gpu_only",
            "slurm_exclusive_directive_requested": False,
            "whole_node_exclusive_verified": False,
        },
        "model": plan["model"],
        "profile_fingerprint": planned_profile_fingerprint(plan),
        "raw_counts": {
            "measured_samples": sample_count,
            "scheduler_steps": scheduler_step_count,
            "warmup_samples": warmup_count,
        },
        "schema": MANIFEST_SCHEMA,
        "status": status,
    }


def _write_environment(
    staging_dir: Path,
    *,
    source_verification: Mapping[str, object],
    launch_provenance: Mapping[str, object],
    slurm: Mapping[str, str],
    gpu_pre: Mapping[str, object],
    gpu_post: Mapping[str, object],
    nvidia_smi_pre: Mapping[str, object],
    nvidia_smi_post: Mapping[str, object],
    instrumentation: Mapping[str, object],
    started_utc: str,
) -> None:
    environment = {
        "environment_variables": {
            key: os.environ.get(key, "")
            for key in (
                "CUDA_VISIBLE_DEVICES",
                "HF_HUB_OFFLINE",
                "TRANSFORMERS_OFFLINE",
                "VLLM_ATTENTION_BACKEND",
                "VLLM_ENABLE_V1_MULTIPROCESSING",
                "VLLM_USE_V1",
            )
        },
        "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gpu": {"post": gpu_post, "pre": gpu_pre},
        "instrumentation": instrumentation,
        "isolation_boundary": {
            "assigned_gpu_gres_verified": slurm["assigned_gpu_allocation"] == "PASS",
            "foreign_gpu_processes_post": gpu_post["foreign_processes"],
            "foreign_gpu_processes_pre": gpu_pre["foreign_processes"],
            "job_oversubscribe": slurm["job_oversubscribe"],
            "partition_oversubscribe": slurm["partition_oversubscribe"],
            "scope": "assigned_slurm_visible_gpu_only",
            "slurm_exclusive_directive_requested": False,
            "whole_node_exclusive_verified": False,
        },
        "launch_provenance": launch_provenance,
        "nvidia_smi_q": {"post": nvidia_smi_post, "pre": nvidia_smi_pre},
        "schema": ENVIRONMENT_SCHEMA,
        "slurm": slurm,
        "source_verification": source_verification,
        "started_utc": started_utc,
    }
    write_canonical_json(staging_dir / "environment.json", environment)


def _remove_latency_outputs_for_oom(staging_dir: Path) -> None:
    for name in ("raw-forward.jsonl", "step-metadata.jsonl"):
        path = staging_dir / name
        if path.exists() and not path.is_symlink() and path.is_file():
            path.unlink()


def _ensure_new_output_and_staging(output_root: Path, staging_dir: Path) -> None:
    if output_root.exists() or output_root.is_symlink():
        raise PublicationError(f"output root already exists: {output_root}")
    resolved = staging_dir.resolve()
    if Path("/tmp") not in resolved.parents:
        raise PublicationError("staging directory must be beneath /tmp")
    if staging_dir.is_symlink() or not staging_dir.is_dir():
        raise PublicationError("staging directory is missing or unsafe")
    probe = staging_dir / ".writable-probe"
    try:
        with probe.open("xb") as stream:
            stream.write(b"verified-writable\n")
            stream.flush()
            os.fsync(stream.fileno())
        probe.unlink()
    except OSError as error:
        raise PublicationError(f"staging directory is not writable: {error}") from error


def run_harness(args: argparse.Namespace) -> int:
    output_root = args.output_root.resolve()
    staging_dir = args.staging_dir.resolve()
    _ensure_new_output_and_staging(output_root, staging_dir)
    started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    plan, shapes, _thresholds = load_and_validate_shape_plan(args.shape_plan.resolve())
    split = build_held_out_split(shapes, plan["held_out_split_seed"])
    # The split exists before the first CUDA event or residual inspection.
    write_canonical_json(staging_dir / "held-out-split.json", split)

    slurm = validate_slurm_environment(os.environ)
    launch = validate_launch_provenance(staging_dir, os.environ)
    source = verify_pinned_inputs(args.source_lock.resolve(), args.support_audit.resolve())

    pre_gpu = inspect_assigned_gpu(allowed_pids={os.getpid()})
    profile = pre_gpu["hardware_profile"]
    assert isinstance(profile, dict)
    uuid = profile["uuid"]
    assert isinstance(uuid, str)
    with (staging_dir / "assigned-gpu-uuid.txt").open("xb") as stream:
        stream.write((uuid + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    nvidia_pre = capture_nvidia_smi_q(staging_dir, "pre", uuid)
    hardware_fingerprint = pre_gpu["hardware_profile_fingerprint"]
    assert isinstance(hardware_fingerprint, str)

    os.environ["VLLM_ENABLE_V1_MULTIPROCESSING"] = "0"
    os.environ["VLLM_WORKER_MULTIPROC_METHOD"] = "fork"
    os.environ["VLLM_USE_V1"] = "1"
    os.environ["VLLM_ATTENTION_BACKEND"] = "FLASH_ATTN"
    controller = ForwardCalibrationController(
        hardware_profile_fingerprint=hardware_fingerprint,
        profile_fingerprint=planned_profile_fingerprint(plan),
    )
    try:
        instrumentation = install_pinned_model_runner_instrumentation(controller)
    except CalibrationError:
        raise
    except BaseException as error:
        raise SourceDriftError(
            f"pinned GPUModelRunner instrumentation import failed: {error}"
        ) from error
    engine: CalibrationEngine | None = None
    oom_error: BaseException | None = None
    execution_stage = "engine_initialization"
    raw_path = staging_dir / "raw-forward.jsonl"
    metadata_path = staging_dir / "step-metadata.jsonl"
    try:
        with AppendOnlyJSONL(metadata_path) as metadata_writer:
            controller.bind_metadata_writer(metadata_writer)
            engine = create_engine(shapes)
            driver = ShapeDriver(engine, controller)
            # The untimed pass verifies every exact scheduler construction
            # before raw-forward.jsonl or the first CUDA event exists.  Its
            # scheduler counters remain in the non-latency metadata sidecar.
            execution_stage = "exact_shape_feasibility"
            for shape in shapes:
                driver.run_shape(shape, record_sample=False)
            execution_stage = "cuda_event_measurement"
            with AppendOnlyJSONL(raw_path) as raw_writer:
                controller.bind_raw_writer(raw_writer)
                for shape in shapes:
                    for repeat_index in range(plan["warmup_repeats"]):
                        driver.run_shape(
                            shape,
                            record_sample=True,
                            warmup=True,
                            repeat_index=repeat_index,
                        )
                    for repeat_index in range(plan["measured_repeats"]):
                        driver.run_shape(
                            shape,
                            record_sample=True,
                            warmup=False,
                            repeat_index=repeat_index,
                        )
    except BaseException as error:
        if is_cuda_oom(error):
            oom_error = error
        elif isinstance(error, CalibrationError):
            raise
        elif execution_stage == "engine_initialization":
            raise SourceDriftError(f"pinned vLLM engine initialization failed: {error}") from error
        elif execution_stage == "exact_shape_feasibility":
            raise ShapeConstructionError(f"exact shape feasibility failed: {error}") from error
        else:
            raise CUDATimingError(f"forward measurement failed: {error}") from error
    finally:
        shutdown_engine(engine)

    post_gpu = inspect_assigned_gpu(allowed_pids={os.getpid()})
    if post_gpu["hardware_profile_fingerprint"] != hardware_fingerprint:
        raise GPUMismatchError("hardware profile changed between pre/post snapshots")
    nvidia_post = capture_nvidia_smi_q(staging_dir, "post", uuid)
    _write_environment(
        staging_dir,
        source_verification=source,
        launch_provenance=launch,
        slurm=slurm,
        gpu_pre=pre_gpu,
        gpu_post=post_gpu,
        nvidia_smi_pre=nvidia_pre,
        nvidia_smi_post=nvidia_post,
        instrumentation=instrumentation,
        started_utc=started_utc,
    )

    if oom_error is not None:
        _remove_latency_outputs_for_oom(staging_dir)
        feasibility = {
            "error": str(oom_error),
            "error_type": type(oom_error).__name__,
            "formal_use_allowed": False,
            "latency_samples_published": False,
            "outcome": "OOM",
            "schema": FEASIBILITY_SCHEMA,
        }
        write_canonical_json(staging_dir / "feasibility.json", feasibility)
        manifest = _prepare_manifest(
            staging_dir,
            status="OOM_FEASIBILITY_ONLY",
            plan=plan,
            slurm=slurm,
            hardware_profile_fingerprint=hardware_fingerprint,
            sample_count=0,
            scheduler_step_count=0,
            warmup_count=0,
        )
        write_canonical_json(staging_dir / "manifest.json", manifest)
        _write_sha256sums(staging_dir)
        publish_staging_no_clobber(staging_dir, output_root)
        return EXIT_OOM

    expected_measured = len(shapes) * plan["measured_repeats"]
    expected_warmups = len(shapes) * plan["warmup_repeats"]
    if controller.sample_count != expected_measured or controller.warmup_count != expected_warmups:
        raise ShapeConstructionError("raw sample counts differ from the predeclared repeat matrix")
    manifest = _prepare_manifest(
        staging_dir,
        status="RAW_FORWARD_COMPLETE",
        plan=plan,
        slurm=slurm,
        hardware_profile_fingerprint=hardware_fingerprint,
        sample_count=controller.sample_count,
        scheduler_step_count=controller.scheduler_step_count,
        warmup_count=controller.warmup_count,
    )
    write_canonical_json(staging_dir / "manifest.json", manifest)
    _write_sha256sums(staging_dir)
    publish_staging_no_clobber(staging_dir, output_root)
    return 0


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shape-plan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--support-audit", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return run_harness(args)
    except CalibrationError as error:
        print(
            f"MOONKVSIM_AICONFIGURATOR_CALIBRATION_ERROR={type(error).__name__}:{error}",
            file=sys.stderr,
        )
        return error.exit_code
    except BaseException as error:
        traceback.print_exc()
        if is_cuda_oom(error):
            return EXIT_OOM
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
