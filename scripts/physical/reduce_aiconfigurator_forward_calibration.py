#!/usr/bin/env python3
"""Reduce one audited forward-only physical bundle without weakening its split.

The physical harness publishes CUDA-event observations and an immutable split;
it does not publish a calibrated profile.  This offline reducer verifies the
entire source bundle, builds a train-only phase/shape database, evaluates only
the held-out prefill/decode shapes, and keeps mixed measurements observation
only.  Invalid provenance is rejected.  Failed thresholds or ``--fixture-mode``
produce a preliminary candidate and never a formal profile selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import stat
import sys
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Final, NoReturn

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from moonkvsim.common.hash import canonical_json_bytes, sha256_json
from moonkvsim.predictor.aiconfigurator import (
    AICONFIGURATOR_PINNED_COMMIT,
    AICONFIGURATOR_PINNED_VERSION,
    AIConfiguratorSupportManifest,
)
from moonkvsim.predictor.calibration import (
    CalibrationObservation,
    CalibrationReport,
    ShapeBucketSpec,
    build_calibration_report,
)
from moonkvsim.predictor.e3_gate import (
    CALIBRATION_METHOD,
    REQUIRED_SHAPE_AXES,
    AIConfiguratorProfileSelection,
    HeldOutCalibrationRecord,
    SelectedDatabaseFile,
    database_bundle_fingerprint,
    load_aiconfigurator_profile_selection,
)
from moonkvsim.predictor.schema import (
    CalibrationEvidenceLabel,
    ForwardBoundary,
    PredictionBatch,
    PredictionPhase,
    PredictionProfile,
    PredictionRequest,
)

SOURCE_PLAN_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-shape-plan.v1"
SOURCE_SAMPLE_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-sample.v1"
SOURCE_STEP_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-step-metadata.v1"
SOURCE_SPLIT_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-held-out-split.v1"
SOURCE_ENVIRONMENT_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-environment.v1"
SOURCE_MANIFEST_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-run-manifest.v1"
SOURCE_PUBLICATION_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-publication.v1"
THRESHOLD_SCHEMA: Final = "moonkvsim.aiconfigurator-residual-thresholds.v1"
REDUCER_CONFIG_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-reducer-config.v1"
DATABASE_SCHEMA: Final = "moonkvsim.aiconfigurator-phase-shape-database.v1"
REDUCTION_REPORT_SCHEMA: Final = "moonkvsim.aiconfigurator-forward-reduction-report.v1"
SOURCE_MANIFEST_OUTPUT_SCHEMA: Final = (
    "moonkvsim.aiconfigurator-forward-reduction-source-manifest.v1"
)
MIXED_OBSERVATIONS_SCHEMA: Final = "moonkvsim.aiconfigurator-mixed-observations.v1"
PROFILE_CANDIDATE_SCHEMA: Final = "moonkvsim.aiconfigurator-profile-candidate.v1"
REDUCTION_PUBLICATION_SCHEMA: Final = "moonkvsim.aiconfigurator-reduction-publication.v1"

DATABASE_RELATIVE_PATH: Final = "database/phase-shape-forward-database.json"
RAW_COPY_PATH: Final = "calibration/raw-forward.jsonl"
METADATA_COPY_PATH: Final = "calibration/step-metadata.jsonl"
SPLIT_COPY_PATH: Final = "calibration/held-out-split.json"
ORIGINAL_THRESHOLDS_COPY_PATH: Final = "calibration/residual-thresholds.predeclared.json"
BOUND_THRESHOLDS_PATH: Final = "calibration/residual-thresholds.selected-profile.json"
DETAIL_REPORT_PATH: Final = "calibration/shape-residual-detail.json"
PREDICTION_AUDIT_PATH: Final = "calibration/held-out-prediction-audit.json"
FORMAL_REPORT_PATH: Final = "calibration/held-out-residual-report.json"
MIXED_PATH: Final = "calibration/mixed-observations.json"
PHYSICAL_MANIFEST_COPY_PATH: Final = "source/physical-run-manifest.json"
ENVIRONMENT_COPY_PATH: Final = "source/environment.json"
SOURCE_CHECKSUM_COPY_PATH: Final = "source/physical-SHA256SUMS"
REDUCER_CONFIG_COPY_PATH: Final = "source/reducer-config.json"

HEX64: Final = "0123456789abcdef"

PLAN_KEYS: Final = {
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
RAW_KEYS: Final = {
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
METADATA_KEYS: Final = {
    "batch_size",
    "cudagraph_mode",
    "extend_lengths",
    "measurement_role",
    "model_internal_collective",
    "model_runner_input_fingerprint",
    "past_kv_lengths",
    "phase",
    "pipeline_parallel_rank",
    "prompt_lengths",
    "repeat_index",
    "request_count",
    "request_ids_sha256",
    "scheduled_token_budget",
    "schema",
    "shape_id",
    "tensor_parallel_rank",
    "warmup",
}


class ReductionError(RuntimeError):
    """Fail-closed reducer error."""


@dataclass(frozen=True, slots=True)
class Shape:
    phase: str
    extend_lengths: tuple[int, ...]
    past_kv_lengths: tuple[int, ...]

    @property
    def batch_size(self) -> int:
        return len(self.extend_lengths)

    @property
    def shape_id(self) -> str:
        return _sha256_bytes(
            _source_canonical_json_bytes(
                {
                    "extend_lengths": list(self.extend_lengths),
                    "past_kv_lengths": list(self.past_kv_lengths),
                    "phase": self.phase,
                }
            )
        )

    @property
    def coordinates(self) -> tuple[int, int, int]:
        return (self.batch_size, max(self.extend_lengths), max(self.past_kv_lengths))

    def to_vectors(self) -> dict[str, object]:
        return {
            "batch_size": self.batch_size,
            "extend_lengths": list(self.extend_lengths),
            "past_kv_lengths": list(self.past_kv_lengths),
            "phase": self.phase,
            "shape_id": self.shape_id,
        }


@dataclass(frozen=True, slots=True)
class ExpectedStep:
    shape: Shape
    role: str
    warmup: bool
    repeat_index: int
    has_raw_sample: bool


@dataclass(frozen=True, slots=True)
class VerifiedSourceBundle:
    root: Path
    plan: Mapping[str, Any]
    shapes: tuple[Shape, ...]
    split: Mapping[str, Any]
    thresholds: Mapping[str, Any]
    manifest: Mapping[str, Any]
    environment: Mapping[str, Any]
    raw_samples: tuple[Mapping[str, Any], ...]
    metadata_steps: tuple[Mapping[str, Any], ...]
    assignments: Mapping[str, str]
    hardware_profile_fingerprint: str
    campaign_profile_fingerprint: str
    source_bundle_fingerprint: str
    source_artifacts: Mapping[str, Mapping[str, object]]
    source_artifact_bytes: Mapping[str, bytes]
    source_checksum_bytes: bytes
    source_publication: Mapping[str, Any]
    source_publication_bytes: bytes


@dataclass(frozen=True, slots=True)
class PhaseEvaluation:
    phase: str
    train_shape_count: int
    held_out_shape_count: int
    held_out_sample_count: int
    residual_bucket_count: int
    mean_absolute_percentage_error: float
    p95_absolute_relative_error: float
    max_mape: float
    max_p95: float
    passed: bool

    def to_reduction_dict(self) -> dict[str, object]:
        return {
            "train_shape_count": self.train_shape_count,
            "held_out_shape_count": self.held_out_shape_count,
            "held_out_sample_count": self.held_out_sample_count,
            "residual_bucket_count": self.residual_bucket_count,
            "mean_absolute_percentage_error": self.mean_absolute_percentage_error,
            "p95_absolute_relative_error": self.p95_absolute_relative_error,
            "thresholds": {
                "max_mean_absolute_percentage_error": self.max_mape,
                "max_p95_absolute_relative_error": self.max_p95,
            },
            "passed": self.passed,
        }

    def to_formal_dict(self) -> dict[str, object]:
        return {
            "sample_count": self.held_out_sample_count,
            "residual_bucket_count": self.residual_bucket_count,
            "mean_absolute_percentage_error": self.mean_absolute_percentage_error,
            "p95_absolute_relative_error": self.p95_absolute_relative_error,
            "passed": self.passed,
        }


def _fail(message: str) -> NoReturn:
    raise ReductionError(message)


def _source_canonical_json_bytes(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"  # type: ignore[arg-type]


def _json_equal(observed: object, expected: object) -> bool:
    """Compare JSON values without Python's bool/int equality coercion."""

    return _source_canonical_json_bytes(observed) == _source_canonical_json_bytes(expected)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_regular_file_bytes(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        _fail(f"{label} cannot be opened as a no-follow file: {path}: {error}")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            _fail(f"{label} is not a regular file: {path}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 8 * 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_regular_file_at(directory_descriptor: int, name: str, label: str) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError as error:
        _fail(f"{label} cannot be opened as a no-follow file: {error}")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            _fail(f"{label} is not a regular file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 8 * 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in HEX64 for character in value)
    )


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    observed = set(value)
    if observed != expected:
        _fail(
            f"{label} fields differ: missing={sorted(expected - observed)}, "
            f"extra={sorted(observed - expected)}"
        )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _fail(f"{label} must be an object with string keys")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        _fail(f"{label} must be a non-empty string without outer whitespace")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(f"{label} must be an integer >= {minimum}")
    return value


def _number(value: object, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        _fail(f"{label} must be finite and >= {minimum}")
    return result


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{label} must be boolean")
    return value


def _safe_regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        _fail(f"{label} must be a regular non-symlink file: {path}")
    mode = path.stat(follow_symlinks=False).st_mode
    if not stat.S_ISREG(mode):
        _fail(f"{label} is not a regular file: {path}")


def _load_source_json_bytes(contents: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{label} is invalid UTF-8 JSON: {error}")
    result = _mapping(value, label)
    if _source_canonical_json_bytes(result) != contents:
        _fail(f"{label} is not canonical source JSON with one trailing newline")
    return result


def _load_source_json(path: Path, label: str) -> Mapping[str, Any]:
    return _load_source_json_bytes(_read_regular_file_bytes(path, label), label)


def _load_config(path: Path) -> Mapping[str, Any]:
    config = _load_source_json(path, "reducer config")
    _validate_json_schema(
        config,
        Path(__file__).resolve().parents[2]
        / "schemas/aiconfigurator-forward-reducer-config.schema.json",
        "reducer config",
    )
    _exact_keys(
        config,
        {
            "absolute_error_percentile_method",
            "calibration_method",
            "database_mode",
            "formal_requirements",
            "held_out_predictor",
            "mixed_policy",
            "residual_convention",
            "schema",
            "shape_axes",
            "train_estimator",
        },
        "reducer config",
    )
    expected = {
        "schema": REDUCER_CONFIG_SCHEMA,
        "calibration_method": CALIBRATION_METHOD,
        "database_mode": "MOONKVSIM_PHASE_SHAPE_PHYSICAL_V1",
        "shape_axes": list(REQUIRED_SHAPE_AXES),
        "train_estimator": "integer_median_half_up",
        "mixed_policy": "observation_only_never_fit_or_decompose",
        "residual_convention": "predicted_minus_observed_ns",
        "absolute_error_percentile_method": "nearest_rank",
        "held_out_predictor": {
            "axis_normalization": "phase_plan_axis_range_with_unit_floor",
            "distance": "normalized_l1",
            "tie_breaker": "shape_id_lexicographic",
        },
        "formal_requirements": {
            "exact_hardware_profile_binding": True,
            "held_out_thresholds_pass": True,
            "phase_coverage": ["prefill", "decode"],
            "source_bundle_complete": True,
            "train_held_out_disjoint": True,
        },
    }
    for key, value in expected.items():
        if config[key] != value:
            _fail(f"reducer config {key} differs from the frozen v1 method")
    return config


def _parse_checksum_bytes(contents: bytes) -> tuple[tuple[str, str], ...]:
    try:
        lines = contents.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        _fail(f"source SHA256SUMS is not UTF-8: {error}")
    if not lines or contents != ("\n".join(lines) + "\n").encode():
        _fail("source SHA256SUMS must be non-empty with exactly one trailing newline")
    records: list[tuple[str, str]] = []
    for index, line in enumerate(lines, start=1):
        digest, separator, name = line.partition("  ")
        if not separator or not _is_sha256(digest) or Path(name).name != name:
            _fail(f"invalid source SHA256SUMS line {index}: {line!r}")
        records.append((name, digest))
    names = [name for name, _ in records]
    if names != sorted(names) or len(names) != len(set(names)):
        _fail("source SHA256SUMS names must be unique and sorted")
    return tuple(records)


def _verify_source_publication(
    root: Path,
) -> tuple[
    Mapping[str, Any],
    dict[str, dict[str, object]],
    dict[str, bytes],
    bytes,
    bytes,
]:
    if root.is_symlink() or not root.is_dir():
        _fail(f"source bundle must be a regular non-symlink directory: {root}")
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
    try:
        directory_descriptor = os.open(root, directory_flags)
    except OSError as error:
        _fail(f"source bundle cannot be opened as a no-follow directory: {root}: {error}")
    try:
        actual_names = set(os.listdir(directory_descriptor))
        if "PUBLICATION_INCOMPLETE" in actual_names:
            _fail("source bundle still has PUBLICATION_INCOMPLETE")
        publication_bytes = _read_regular_file_at(
            directory_descriptor,
            "PUBLICATION_COMPLETE.json",
            "source publication",
        )
        publication = _load_source_json_bytes(publication_bytes, "source publication")
        _exact_keys(
            publication,
            {"formal_use_allowed", "no_clobber", "schema", "sha256sums_sha256", "status"},
            "source publication",
        )
        expected_publication = {
            "formal_use_allowed": False,
            "no_clobber": True,
            "schema": SOURCE_PUBLICATION_SCHEMA,
            "sha256sums_sha256": publication["sha256sums_sha256"],
            "status": "COMPLETE",
        }
        if not _json_equal(publication, expected_publication):
            _fail("source publication completion fields are not the fail-closed harness contract")
        if not _is_sha256(publication["sha256sums_sha256"]):
            _fail("source publication SHA256SUMS hash is malformed")
        checksum_bytes = _read_regular_file_at(
            directory_descriptor,
            "SHA256SUMS",
            "source SHA256SUMS",
        )
        if _sha256_bytes(checksum_bytes) != publication["sha256sums_sha256"]:
            _fail("source publication SHA256SUMS hash mismatch")
        checksum_records = _parse_checksum_bytes(checksum_bytes)
        artifacts: dict[str, dict[str, object]] = {}
        artifact_bytes: dict[str, bytes] = {}
        for name, digest in checksum_records:
            contents = _read_regular_file_at(
                directory_descriptor,
                name,
                f"source artifact {name}",
            )
            observed = _sha256_bytes(contents)
            if observed != digest:
                _fail(f"source artifact SHA-256 mismatch for {name}")
            artifacts[name] = {
                "path": name,
                "sha256": observed,
                "size_bytes": len(contents),
            }
            artifact_bytes[name] = contents
        expected_names = set(artifacts) | {"SHA256SUMS", "PUBLICATION_COMPLETE.json"}
        if actual_names != expected_names:
            _fail(
                "source bundle flat artifact set differs from SHA256SUMS: "
                f"missing={sorted(expected_names - actual_names)}, "
                f"extra={sorted(actual_names - expected_names)}"
            )
        return publication, artifacts, artifact_bytes, checksum_bytes, publication_bytes
    finally:
        os.close(directory_descriptor)


def _parse_shape(phase: str, raw: object, label: str) -> Shape:
    shape = _mapping(raw, label)
    _exact_keys(shape, {"extend_lengths", "past_kv_lengths"}, label)
    extend = tuple(
        _integer(value, f"{label}.extend_lengths[]", minimum=1)
        for value in _list(shape["extend_lengths"], f"{label}.extend_lengths")
    )
    past = tuple(
        _integer(value, f"{label}.past_kv_lengths[]")
        for value in _list(shape["past_kv_lengths"], f"{label}.past_kv_lengths")
    )
    if not extend or len(extend) != len(past):
        _fail(f"{label} vectors must be non-empty and equally sized")
    if any(extension + previous > 40960 for extension, previous in zip(extend, past, strict=True)):
        _fail(f"{label} exceeds the native max_model_len 40960")
    if phase == "prefill":
        if any(past):
            _fail(f"{label} prefill shape must have zero past KV")
    elif phase == "decode":
        if any(value != 1 for value in extend) or any(value <= 0 for value in past):
            _fail(f"{label} decode shape must use extend=1 and positive past KV")
    elif phase == "mixed":
        members = tuple(zip(extend, past, strict=True))
        decode_count = sum(extension == 1 and previous > 0 for extension, previous in members)
        prefill_count = sum(extension > 1 and previous == 0 for extension, previous in members)
        if decode_count == 0 or prefill_count == 0 or decode_count + prefill_count != len(members):
            _fail(f"{label} mixed shape must contain unambiguous decode and prefill members")
        if members[:decode_count] != tuple(item for item in members if item[0] == 1):
            _fail(f"{label} mixed decode members must precede prefill members")
    else:
        _fail(f"{label} has unsupported phase {phase!r}")
    return Shape(phase, extend, past)


def _planned_profile_fingerprint(plan: Mapping[str, Any]) -> str:
    descriptor = {
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
            "symbol": "GPUModelRunner._model_forward",
        },
        "hardware_profile_id": plan["hardware_profile_id"],
        "kv_dtype": plan["kv_dtype"],
        "model": plan["model"],
        "pipeline_parallel_size": plan["pipeline_parallel_size"],
        "provider": {
            "commit": AICONFIGURATOR_PINNED_COMMIT,
            "name": "aiconfigurator",
            "version": AICONFIGURATOR_PINNED_VERSION,
        },
        "tensor_parallel_size": plan["tensor_parallel_size"],
    }
    return _sha256_bytes(_source_canonical_json_bytes(descriptor))


def _load_and_validate_plan(
    root: Path,
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> tuple[Mapping[str, Any], tuple[Shape, ...]]:
    plan = (
        _load_source_json(root / "shape-plan.json", "shape plan")
        if artifact_bytes is None
        else _load_source_json_bytes(artifact_bytes["shape-plan.json"], "shape plan")
    )
    _exact_keys(plan, PLAN_KEYS, "shape plan")
    fixed = {
        "schema": SOURCE_PLAN_SCHEMA,
        "calibration_method": CALIBRATION_METHOD,
        "hardware_profile_id": "l40s-exact-detected-profile",
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "dtype": "bfloat16",
        "kv_dtype": "bfloat16",
        "attention_backend": "FLASH_ATTN",
        "block_size": 16,
    }
    for key, expected in fixed.items():
        if not _json_equal(plan[key], expected):
            _fail(f"shape plan {key} differs from the implemented physical contract")
    _integer(plan["warmup_repeats"], "shape plan warmup_repeats", minimum=5)
    _integer(plan["measured_repeats"], "shape plan measured_repeats", minimum=1)
    _integer(plan["held_out_split_seed"], "shape plan held_out_split_seed")
    context = _mapping(plan["context_mode"], "shape plan context_mode")
    _exact_keys(context, {"max_model_len", "rope_scaling"}, "shape plan context_mode")
    if (
        _integer(context["max_model_len"], "shape plan context_mode.max_model_len", minimum=1)
        != 40960
        or context["rope_scaling"] is not None
    ):
        _fail("reducer supports only the native 40960 context physical campaign")
    engine = _mapping(plan["engine"], "shape plan engine")
    _exact_keys(engine, {"installed_version", "source_commit"}, "shape plan engine")
    _string(engine["installed_version"], "shape plan engine installed_version")
    source_commit = engine["source_commit"]
    if (
        not isinstance(source_commit, str)
        or len(source_commit) != 40
        or any(character not in HEX64 for character in source_commit)
    ):
        _fail("shape plan engine source_commit must be a lowercase 40-character Git commit")
    model = _mapping(plan["model"], "shape plan model")
    _exact_keys(model, {"id", "revision"}, "shape plan model")
    _string(model["id"], "shape plan model id")
    _string(model["revision"], "shape plan model revision")

    phases = _mapping(plan["phases"], "shape plan phases")
    _exact_keys(phases, {"prefill", "decode", "mixed"}, "shape plan phases")
    shapes: list[Shape] = []
    for phase in ("prefill", "decode", "mixed"):
        records = _list(phases[phase], f"shape plan phases.{phase}")
        if not records:
            _fail(f"shape plan phases.{phase} must be non-empty")
        shapes.extend(
            _parse_shape(phase, raw, f"shape plan phases.{phase}[{index}]")
            for index, raw in enumerate(records)
        )
    if len({shape.shape_id for shape in shapes}) != len(shapes):
        _fail("shape plan contains duplicate phase/vector shapes")
    return plan, tuple(shapes)


def _load_and_validate_thresholds(
    root: Path,
    plan: Mapping[str, Any],
    campaign_fingerprint: str,
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> Mapping[str, Any]:
    declaration = _mapping(plan["threshold_declaration"], "shape plan threshold_declaration")
    _exact_keys(declaration, {"path", "sha256", "size_bytes"}, "threshold declaration")
    if _string(declaration["path"], "threshold declaration path") != "residual-thresholds.json":
        _fail("threshold declaration path must be residual-thresholds.json")
    if not _is_sha256(declaration["sha256"]):
        _fail("threshold declaration sha256 must be lowercase SHA-256")
    declared_size = _integer(
        declaration["size_bytes"], "threshold declaration size_bytes", minimum=1
    )
    threshold_path = root / "residual-thresholds.json"
    threshold_bytes = (
        _read_regular_file_bytes(threshold_path, "predeclared thresholds")
        if artifact_bytes is None
        else artifact_bytes["residual-thresholds.json"]
    )
    thresholds = _load_source_json_bytes(threshold_bytes, "predeclared thresholds")
    if len(threshold_bytes) != declared_size:
        _fail("predeclared threshold size differs from the shape plan")
    if _sha256_bytes(threshold_bytes) != declaration["sha256"]:
        _fail("predeclared threshold hash differs from the shape plan")
    _exact_keys(
        thresholds,
        {"schema", "profile_fingerprint", "calibration_method", "shape_axes", "phase_thresholds"},
        "predeclared thresholds",
    )
    expected = {
        "schema": THRESHOLD_SCHEMA,
        "profile_fingerprint": campaign_fingerprint,
        "calibration_method": CALIBRATION_METHOD,
        "shape_axes": list(REQUIRED_SHAPE_AXES),
    }
    for key, value in expected.items():
        if not _json_equal(thresholds[key], value):
            _fail(f"predeclared thresholds {key} does not bind the source campaign")
    phase_thresholds = _mapping(thresholds["phase_thresholds"], "phase thresholds")
    _exact_keys(phase_thresholds, {"prefill", "decode"}, "phase thresholds")
    for phase in ("prefill", "decode"):
        values = _mapping(phase_thresholds[phase], f"phase thresholds {phase}")
        _exact_keys(
            values,
            {"max_mean_absolute_percentage_error", "max_p95_absolute_relative_error"},
            f"phase thresholds {phase}",
        )
        for key, value in values.items():
            _number(value, f"phase thresholds {phase}.{key}")
    return thresholds


def _expected_split(shapes: tuple[Shape, ...], seed: int) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for phase in ("prefill", "decode"):
        candidates = [shape for shape in shapes if shape.phase == phase]
        if len(candidates) < 2:
            _fail(f"at least two {phase} shapes are required for a held-out split")
        ranked = sorted(
            candidates,
            key=lambda shape: _sha256_bytes(
                _source_canonical_json_bytes(
                    {"seed": seed, "shape_id": shape.shape_id, "split_phase": phase}
                )
            ),
        )
        assignments[ranked[0].shape_id] = "held_out"
        assignments.update({shape.shape_id: "train" for shape in ranked[1:]})
    assignments.update(
        {shape.shape_id: "mixed_observation_only" for shape in shapes if shape.phase == "mixed"}
    )
    return assignments


def _load_and_validate_split(
    root: Path,
    shapes: tuple[Shape, ...],
    seed: int,
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> tuple[Mapping[str, Any], Mapping[str, str]]:
    split = (
        _load_source_json(root / "held-out-split.json", "held-out split")
        if artifact_bytes is None
        else _load_source_json_bytes(artifact_bytes["held-out-split.json"], "held-out split")
    )
    _exact_keys(
        split,
        {"algorithm", "assignments", "coverage", "frozen_before_measurement", "seed", "schema"},
        "held-out split",
    )
    if (
        not _json_equal(split["schema"], SOURCE_SPLIT_SCHEMA)
        or not _json_equal(split["algorithm"], "sha256-seeded-phase-stratified-first-held-out-v1")
        or not _json_equal(split["seed"], seed)
        or split["frozen_before_measurement"] is not True
    ):
        _fail("held-out split identity/freeze fields differ from the harness contract")
    records = _list(split["assignments"], "held-out split assignments")
    if len(records) != len(shapes):
        _fail("held-out split assignment count differs from the shape plan")
    expected_assignments = _expected_split(shapes, seed)
    observed_assignments: dict[str, str] = {}
    for index, (raw, shape) in enumerate(zip(records, shapes, strict=True)):
        record = _mapping(raw, f"held-out split assignment {index}")
        _exact_keys(
            record,
            {"batch_size", "extend_lengths", "past_kv_lengths", "phase", "shape_id", "split"},
            f"held-out split assignment {index}",
        )
        expected_vectors = shape.to_vectors()
        expected_vectors["split"] = expected_assignments[shape.shape_id]
        if not _json_equal(record, expected_vectors):
            _fail(f"held-out split assignment {index} differs from plan/order/algorithm")
        observed_assignments[shape.shape_id] = _string(record["split"], "split assignment")
    train = {
        shape_id for shape_id, split_name in observed_assignments.items() if split_name == "train"
    }
    held = {
        shape_id
        for shape_id, split_name in observed_assignments.items()
        if split_name == "held_out"
    }
    if train & held:
        _fail("train and held-out shape IDs overlap")
    coverage = _mapping(split["coverage"], "held-out split coverage")
    _exact_keys(
        coverage,
        {"batch_sizes", "extend_lengths", "past_kv_lengths", "phases", "shape_axes"},
        "held-out split coverage",
    )
    expected_coverage = {
        "batch_sizes": sorted({shape.batch_size for shape in shapes}),
        "extend_lengths": sorted({value for shape in shapes for value in shape.extend_lengths}),
        "past_kv_lengths": sorted({value for shape in shapes for value in shape.past_kv_lengths}),
        "phases": sorted({shape.phase for shape in shapes}),
        "shape_axes": list(REQUIRED_SHAPE_AXES),
    }
    if not _json_equal(coverage, expected_coverage):
        _fail("held-out split coverage does not match the exact shape plan")
    return split, observed_assignments


def _setup_shape(shape: Shape) -> Shape | None:
    if shape.phase == "decode":
        return Shape("prefill", shape.past_kv_lengths, tuple(0 for _ in shape.past_kv_lengths))
    if shape.phase == "mixed":
        decode_past = tuple(
            previous
            for extension, previous in zip(shape.extend_lengths, shape.past_kv_lengths, strict=True)
            if extension == 1
        )
        return Shape("prefill", decode_past, tuple(0 for _ in decode_past))
    return None


def _expected_steps(
    shapes: tuple[Shape, ...], warmups: int, measured: int
) -> tuple[ExpectedStep, ...]:
    result: list[ExpectedStep] = []

    def append_trial(shape: Shape, role_prefix: str, warmup: bool, repeat: int) -> None:
        setup = _setup_shape(shape)
        if setup is not None:
            result.append(
                ExpectedStep(
                    setup,
                    f"{role_prefix}_setup",
                    warmup,
                    repeat,
                    False,
                )
            )
        result.append(
            ExpectedStep(
                shape,
                f"{role_prefix}_target" if role_prefix == "feasibility" else "target",
                warmup,
                repeat,
                role_prefix != "feasibility",
            )
        )

    for shape in shapes:
        append_trial(shape, "feasibility", False, 0)
    for shape in shapes:
        for repeat in range(warmups):
            append_trial(shape, "measurement", True, repeat)
        for repeat in range(measured):
            append_trial(shape, "measurement", False, repeat)
    return tuple(result)


def _load_jsonl_bytes(contents: bytes, label: str) -> tuple[Mapping[str, Any], ...]:
    if not contents or not contents.endswith(b"\n"):
        _fail(f"{label} must be non-empty and newline terminated")
    records: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(contents.splitlines(keepends=True), start=1):
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            _fail(f"{label} line {line_number} is invalid JSON: {error}")
        record = _mapping(value, f"{label} line {line_number}")
        if _source_canonical_json_bytes(record) != line:
            _fail(f"{label} line {line_number} is not canonical JSONL")
        records.append(record)
    return tuple(records)


def _load_jsonl(path: Path, label: str) -> tuple[Mapping[str, Any], ...]:
    return _load_jsonl_bytes(_read_regular_file_bytes(path, label), label)


def _validate_metadata_record(
    record: Mapping[str, Any], expected: ExpectedStep, index: int
) -> None:
    label = f"step-metadata record {index}"
    _exact_keys(record, METADATA_KEYS, label)
    shape = expected.shape
    expected_basic: dict[str, object] = {
        "schema": SOURCE_STEP_SCHEMA,
        "shape_id": shape.shape_id,
        "phase": shape.phase,
        "batch_size": shape.batch_size,
        "extend_lengths": list(shape.extend_lengths),
        "past_kv_lengths": list(shape.past_kv_lengths),
        "measurement_role": expected.role,
        "warmup": expected.warmup,
        "repeat_index": expected.repeat_index,
        "request_count": shape.batch_size,
        "scheduled_token_budget": sum(shape.extend_lengths),
        "cudagraph_mode": "NONE",
        "model_internal_collective": "none_tp1",
        "pipeline_parallel_rank": 0,
        "tensor_parallel_rank": 0,
    }
    for key, value in expected_basic.items():
        if not _json_equal(record[key], value):
            _fail(f"{label} {key} differs from exact expected execution order")
    prompts = tuple(
        _integer(value, f"{label}.prompt_lengths[]", minimum=1)
        for value in _list(record["prompt_lengths"], f"{label}.prompt_lengths")
    )
    if len(prompts) != shape.batch_size:
        _fail(f"{label} prompt_lengths count differs from batch size")
    expected_prompts = tuple(
        previous if previous > 0 else extension
        for extension, previous in zip(shape.extend_lengths, shape.past_kv_lengths, strict=True)
    )
    if prompts != expected_prompts:
        _fail(f"{label} prompt counters do not match the requested shape")
    for key in ("request_ids_sha256", "model_runner_input_fingerprint"):
        if not _is_sha256(record[key]):
            _fail(f"{label} {key} must be lowercase SHA-256")


def _validate_raw_record(
    record: Mapping[str, Any], expected: ExpectedStep, metadata: Mapping[str, Any], index: int
) -> None:
    label = f"raw-forward record {index}"
    _exact_keys(record, RAW_KEYS, label)
    shape = expected.shape
    expected_basic: dict[str, object] = {
        "schema": SOURCE_SAMPLE_SCHEMA,
        "shape_id": shape.shape_id,
        "phase": shape.phase,
        "batch_size": shape.batch_size,
        "extend_lengths": list(shape.extend_lengths),
        "past_kv_lengths": list(shape.past_kv_lengths),
        "warmup": expected.warmup,
        "repeat_index": expected.repeat_index,
        "cudagraph_mode": "NONE",
        "measurement_method": "cuda_events_gpu_model_runner_model_forward",
        "pipeline_parallel_rank": 0,
        "tensor_parallel_rank": 0,
        "request_ids_sha256": metadata["request_ids_sha256"],
    }
    for key, value in expected_basic.items():
        if not _json_equal(record[key], value):
            _fail(f"{label} {key} does not join its exact target metadata record")
    _integer(record["duration_ns"], f"{label}.duration_ns", minimum=1)
    for key in (
        "hardware_profile_fingerprint",
        "profile_fingerprint",
        "model_runner_source_sha256",
    ):
        if not _is_sha256(record[key]):
            _fail(f"{label} {key} must be lowercase SHA-256")


def _validate_measurement_streams(
    root: Path,
    plan: Mapping[str, Any],
    shapes: tuple[Shape, ...],
    campaign_fingerprint: str,
    hardware_fingerprint: str,
    manifest: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    if artifact_bytes is None:
        metadata = _load_jsonl(root / "step-metadata.jsonl", "step-metadata.jsonl")
        raw = _load_jsonl(root / "raw-forward.jsonl", "raw-forward.jsonl")
    else:
        metadata = _load_jsonl_bytes(artifact_bytes["step-metadata.jsonl"], "step-metadata.jsonl")
        raw = _load_jsonl_bytes(artifact_bytes["raw-forward.jsonl"], "raw-forward.jsonl")
    warmups = _integer(plan["warmup_repeats"], "warmup repeats", minimum=1)
    measured = _integer(plan["measured_repeats"], "measured repeats", minimum=1)
    expected = _expected_steps(shapes, warmups, measured)
    if len(metadata) != len(expected):
        _fail(
            f"step-metadata record count differs from exact schedule: "
            f"observed={len(metadata)}, expected={len(expected)}"
        )
    expected_raw_steps = tuple(step for step in expected if step.has_raw_sample)
    if len(raw) != len(expected_raw_steps):
        _fail(
            f"raw-forward record count differs from exact schedule: "
            f"observed={len(raw)}, expected={len(expected_raw_steps)}"
        )
    raw_index = 0
    for metadata_index, (record, expected_step) in enumerate(zip(metadata, expected, strict=True)):
        _validate_metadata_record(record, expected_step, metadata_index)
        if expected_step.has_raw_sample:
            _validate_raw_record(raw[raw_index], expected_step, record, raw_index)
            raw_index += 1
    if any(record["profile_fingerprint"] != campaign_fingerprint for record in raw):
        _fail("raw-forward profile fingerprint differs from the source campaign")
    if any(record["hardware_profile_fingerprint"] != hardware_fingerprint for record in raw):
        _fail("raw-forward hardware fingerprint differs from the manifest/environment")
    raw_counts = _mapping(manifest["raw_counts"], "source manifest raw_counts")
    _exact_keys(
        raw_counts,
        {"measured_samples", "scheduler_steps", "warmup_samples"},
        "source manifest raw_counts",
    )
    for key in ("measured_samples", "scheduler_steps", "warmup_samples"):
        _integer(raw_counts[key], f"source manifest raw_counts.{key}")
    expected_measured = len(shapes) * measured
    expected_warmups = len(shapes) * warmups
    if not _json_equal(
        raw_counts,
        {
            "measured_samples": expected_measured,
            "scheduler_steps": len(expected),
            "warmup_samples": expected_warmups,
        },
    ):
        _fail("source manifest raw counts differ from the exact record matrix")
    return raw, metadata


def _load_and_validate_environment(
    root: Path,
    plan: Mapping[str, Any],
    hardware_fingerprint: str,
    manifest: Mapping[str, Any],
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> Mapping[str, Any]:
    environment = (
        _load_source_json(root / "environment.json", "source environment")
        if artifact_bytes is None
        else _load_source_json_bytes(artifact_bytes["environment.json"], "source environment")
    )
    _exact_keys(
        environment,
        {
            "environment_variables",
            "finished_utc",
            "gpu",
            "instrumentation",
            "isolation_boundary",
            "launch_provenance",
            "nvidia_smi_q",
            "schema",
            "slurm",
            "source_verification",
            "started_utc",
        },
        "source environment",
    )
    if environment["schema"] != SOURCE_ENVIRONMENT_SCHEMA:
        _fail("source environment schema mismatch")
    gpu = _mapping(environment["gpu"], "source environment gpu")
    _exact_keys(gpu, {"pre", "post"}, "source environment gpu")
    profiles: list[Mapping[str, Any]] = []
    for boundary in ("pre", "post"):
        snapshot = _mapping(gpu[boundary], f"source environment gpu.{boundary}")
        if snapshot.get("status") != "PASS":
            _fail(f"source environment gpu.{boundary} did not pass")
        if snapshot.get("foreign_processes") != []:
            _fail(f"source environment gpu.{boundary} contains foreign GPU processes")
        if snapshot.get("hardware_profile_fingerprint") != hardware_fingerprint:
            _fail(f"source environment gpu.{boundary} fingerprint mismatch")
        profile = _mapping(
            snapshot.get("hardware_profile"), f"source environment gpu.{boundary}.hardware_profile"
        )
        if _sha256_bytes(_source_canonical_json_bytes(profile)) != hardware_fingerprint:
            _fail(f"source environment gpu.{boundary} hardware profile hash mismatch")
        if profile.get("name") != "NVIDIA L40S" or not _json_equal(
            profile.get("compute_capability"), [8, 9]
        ):
            _fail(f"source environment gpu.{boundary} is not the exact L40S profile")
        if not isinstance(profile.get("uuid"), str) or not profile["uuid"].startswith("GPU-"):
            _fail(f"source environment gpu.{boundary} GPU UUID is invalid")
        profiles.append(profile)
    if not _json_equal(profiles[0], profiles[1]):
        _fail("source environment hardware profile changed across measurement")
    isolation = _mapping(environment["isolation_boundary"], "source isolation boundary")
    if (
        isolation.get("assigned_gpu_gres_verified") is not True
        or isolation.get("foreign_gpu_processes_pre") != []
        or isolation.get("foreign_gpu_processes_post") != []
        or isolation.get("scope") != "assigned_slurm_visible_gpu_only"
    ):
        _fail("source environment assigned-GPU isolation boundary did not pass")
    manifest_isolation = _mapping(
        manifest["isolation_boundary"], "source manifest isolation boundary"
    )
    if (
        manifest_isolation.get("assigned_gpu_gres_verified") is not True
        or not _json_equal(manifest_isolation.get("cuda_visible_device_count"), 1)
        or manifest_isolation.get("foreign_gpu_processes_rejected_pre_and_post") is not True
        or manifest_isolation.get("scope") != "assigned_slurm_visible_gpu_only"
        or manifest_isolation.get("whole_node_exclusive_verified") is not False
    ):
        _fail("source manifest assigned-GPU isolation boundary did not pass")
    manifest_instrumentation = _mapping(
        manifest["instrumentation"], "source manifest instrumentation"
    )
    environment_instrumentation = _mapping(
        environment["instrumentation"], "source environment instrumentation"
    )
    instrumentation_contract = {
        "measurement_method": "cuda_events_gpu_model_runner_model_forward",
        "outer_execute_model_role": "scheduler_metadata_handoff_only",
        "source_tree_modified": False,
        "symbol": "GPUModelRunner._model_forward",
    }
    for key, value in instrumentation_contract.items():
        if not _json_equal(manifest_instrumentation.get(key), value):
            _fail(f"source manifest instrumentation {key} differs from the timing contract")
    for key in (
        "model_runner_git_blob",
        "model_runner_source_sha256",
        "outer_execute_model_role",
        "source_tree_modified",
        "symbol",
    ):
        if environment_instrumentation.get(key) != manifest_instrumentation.get(key):
            _fail(f"source environment/manifest instrumentation {key} mismatch")
    if environment_instrumentation.get("timing_boundary") != (
        "cuda_events_immediately_inside_model_forward_wrapper"
    ):
        _fail("source environment timing boundary differs from the inner forward hook")
    slurm = _mapping(environment["slurm"], "source environment slurm")
    if slurm.get("partition") != "short" or slurm.get("assigned_gpu_allocation") != "PASS":
        _fail("source environment Slurm L40S allocation was not verified")
    source = _mapping(environment["source_verification"], "source verification")
    if source.get("status") != "PASS":
        _fail("source/model/runtime verification did not pass")
    aic = _mapping(source.get("aiconfigurator"), "source verification aiconfigurator")
    if (
        aic.get("version") != AICONFIGURATOR_PINNED_VERSION
        or aic.get("commit") != AICONFIGURATOR_PINNED_COMMIT
    ):
        _fail("source verification AIConfigurator pin mismatch")
    engine = _mapping(plan["engine"], "shape plan engine")
    runtime = _mapping(source.get("runtime"), "source verification runtime")
    vllm = _mapping(source.get("vllm"), "source verification vllm")
    if (
        runtime.get("vllm_version") != engine["installed_version"]
        or vllm.get("commit") != engine["source_commit"]
    ):
        _fail("source verification vLLM runtime/commit differs from shape plan")
    model_plan = _mapping(plan["model"], "shape plan model")
    model = _mapping(source.get("model"), "source verification model")
    if model.get("id") != model_plan["id"] or model.get("revision") != model_plan["revision"]:
        _fail("source verification model identity differs from shape plan")
    return environment


def _load_and_validate_manifest(
    root: Path,
    artifacts: Mapping[str, Mapping[str, object]],
    plan: Mapping[str, Any],
    campaign_fingerprint: str,
    artifact_bytes: Mapping[str, bytes] | None = None,
) -> tuple[Mapping[str, Any], str]:
    manifest = (
        _load_source_json(root / "manifest.json", "source manifest")
        if artifact_bytes is None
        else _load_source_json_bytes(artifact_bytes["manifest.json"], "source manifest")
    )
    _exact_keys(
        manifest,
        {
            "artifacts",
            "evidence_label",
            "formal_use_allowed",
            "hardware_profile_fingerprint",
            "instrumentation",
            "isolation_boundary",
            "model",
            "profile_fingerprint",
            "raw_counts",
            "schema",
            "status",
        },
        "source manifest",
    )
    if (
        manifest["schema"] != SOURCE_MANIFEST_SCHEMA
        or manifest["status"] != "RAW_FORWARD_COMPLETE"
        or manifest["formal_use_allowed"] is not False
        or manifest["profile_fingerprint"] != campaign_fingerprint
        or not _json_equal(manifest["model"], plan["model"])
    ):
        _fail("source manifest does not describe a complete fail-closed raw forward bundle")
    hardware_fingerprint = manifest["hardware_profile_fingerprint"]
    if not _is_sha256(hardware_fingerprint):
        _fail("source manifest hardware profile fingerprint is malformed")
    evidence = _mapping(manifest["evidence_label"], "source manifest evidence_label")
    if not _json_equal(
        evidence,
        {
            "calibrated_profile": False,
            "class": "physical_forward_raw_calibration_input",
            "formal_use_allowed": False,
            "paper_result_allowed": False,
            "reducer_required": True,
        },
    ):
        _fail("source manifest evidence label is not raw physical calibration input")
    manifest_artifacts = _mapping(manifest["artifacts"], "source manifest artifacts")
    expected_artifact_names = set(artifacts) - {"manifest.json"}
    if set(manifest_artifacts) != expected_artifact_names:
        _fail("source manifest artifact inventory differs from SHA256SUMS")
    for name in sorted(expected_artifact_names):
        record = _mapping(manifest_artifacts[name], f"source manifest artifact {name}")
        _exact_keys(record, {"sha256", "size_bytes"}, f"source manifest artifact {name}")
        expected = artifacts[name]
        if not _is_sha256(record["sha256"]):
            _fail(f"source manifest artifact SHA-256 is malformed for {name}")
        _integer(record["size_bytes"], f"source manifest artifact {name}.size_bytes")
        expected_record = {
            "sha256": expected["sha256"],
            "size_bytes": expected["size_bytes"],
        }
        if not _json_equal(record, expected_record):
            _fail(f"source manifest artifact metadata mismatch for {name}")
    required = {
        "shape-plan.json",
        "residual-thresholds.json",
        "held-out-split.json",
        "raw-forward.jsonl",
        "step-metadata.jsonl",
        "environment.json",
    }
    if not required.issubset(manifest_artifacts):
        missing = sorted(required - set(manifest_artifacts))
        _fail(f"source manifest misses required reducer inputs: {missing}")
    return manifest, str(hardware_fingerprint)


def verify_source_bundle(root: Path) -> VerifiedSourceBundle:
    publication, artifacts, artifact_bytes, checksum_bytes, publication_bytes = (
        _verify_source_publication(root)
    )
    plan, shapes = _load_and_validate_plan(root, artifact_bytes)
    campaign_fingerprint = _planned_profile_fingerprint(plan)
    thresholds = _load_and_validate_thresholds(root, plan, campaign_fingerprint, artifact_bytes)
    split, assignments = _load_and_validate_split(
        root,
        shapes,
        _integer(plan["held_out_split_seed"], "held_out split seed"),
        artifact_bytes,
    )
    manifest, hardware_fingerprint = _load_and_validate_manifest(
        root, artifacts, plan, campaign_fingerprint, artifact_bytes
    )
    environment = _load_and_validate_environment(
        root, plan, hardware_fingerprint, manifest, artifact_bytes
    )
    raw, metadata = _validate_measurement_streams(
        root,
        plan,
        shapes,
        campaign_fingerprint,
        hardware_fingerprint,
        manifest,
        artifact_bytes,
    )
    instrumentation = _mapping(manifest["instrumentation"], "source instrumentation")
    if any(
        record["model_runner_source_sha256"] != instrumentation["model_runner_source_sha256"]
        for record in raw
    ):
        _fail("raw-forward model-runner source hash differs from instrumentation")
    fingerprint_rows = [
        {"path": name, "sha256": record["sha256"], "size_bytes": record["size_bytes"]}
        for name, record in sorted(artifacts.items())
    ]
    fingerprint_rows.extend(
        (
            {
                "path": "SHA256SUMS",
                "sha256": _sha256_bytes(checksum_bytes),
                "size_bytes": len(checksum_bytes),
            },
            {
                "path": "PUBLICATION_COMPLETE.json",
                "sha256": _sha256_bytes(publication_bytes),
                "size_bytes": len(publication_bytes),
            },
        )
    )
    return VerifiedSourceBundle(
        root=root,
        plan=plan,
        shapes=shapes,
        split=split,
        thresholds=thresholds,
        manifest=manifest,
        environment=environment,
        raw_samples=raw,
        metadata_steps=metadata,
        assignments=assignments,
        hardware_profile_fingerprint=hardware_fingerprint,
        campaign_profile_fingerprint=campaign_fingerprint,
        source_bundle_fingerprint=sha256_json(fingerprint_rows),
        source_artifacts=artifacts,
        source_artifact_bytes=artifact_bytes,
        source_checksum_bytes=checksum_bytes,
        source_publication=publication,
        source_publication_bytes=publication_bytes,
    )


def _integer_median_half_up(values: Sequence[int]) -> int:
    if not values:
        _fail("integer median requires at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle] + 1) // 2


def _measured_samples_by_shape(
    source: VerifiedSourceBundle,
) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in source.raw_samples:
        if record["warmup"] is False:
            grouped[str(record["shape_id"])].append(record)
    result = {shape_id: tuple(records) for shape_id, records in grouped.items()}
    measured = _integer(source.plan["measured_repeats"], "measured repeats", minimum=1)
    for shape in source.shapes:
        records = result.get(shape.shape_id, ())
        if len(records) != measured:
            _fail(f"shape {shape.shape_id} measured-repeat coverage is incomplete")
        if [record["repeat_index"] for record in records] != list(range(measured)):
            _fail(f"shape {shape.shape_id} measured-repeat order is not canonical")
    return result


def _database_document(
    source: VerifiedSourceBundle,
    config: Mapping[str, Any],
    samples: Mapping[str, tuple[Mapping[str, Any], ...]],
) -> Mapping[str, Any]:
    entries: list[dict[str, object]] = []
    for shape in source.shapes:
        if source.assignments[shape.shape_id] != "train":
            continue
        if shape.phase not in {"prefill", "decode"}:
            _fail("mixed observation entered the training database")
        durations = tuple(int(record["duration_ns"]) for record in samples[shape.shape_id])
        entries.append(
            {
                "batch_size": shape.batch_size,
                "estimated_forward_duration_ns": _integer_median_half_up(durations),
                "estimator": config["train_estimator"],
                "extend_lengths": list(shape.extend_lengths),
                "past_kv_lengths": list(shape.past_kv_lengths),
                "phase": shape.phase,
                "sample_count": len(durations),
                "shape_id": shape.shape_id,
                "split": "train",
            }
        )
    entries.sort(key=lambda item: (str(item["phase"]), str(item["shape_id"])))
    if {entry["phase"] for entry in entries} != {"prefill", "decode"}:
        _fail("train database lacks independent prefill/decode coverage")
    plan_engine = _mapping(source.plan["engine"], "shape plan engine")
    return {
        "backend": "vllm",
        "backend_version": plan_engine["installed_version"],
        "campaign_profile_fingerprint": source.campaign_profile_fingerprint,
        "database_mode": config["database_mode"],
        "entries": entries,
        "estimator": config["train_estimator"],
        "formal_use_allowed": False,
        "forward_boundary": "gpu_model_runner._model_forward_cuda_events",
        "hardware_profile_fingerprint": source.hardware_profile_fingerprint,
        "hardware_profile_id": source.plan["hardware_profile_id"],
        "held_out_predictor": config["held_out_predictor"],
        "mixed_observations_included": False,
        "model": source.plan["model"],
        "parallelism": {
            "pipeline_parallel_size": source.plan["pipeline_parallel_size"],
            "tensor_parallel_size": source.plan["tensor_parallel_size"],
        },
        "schema": DATABASE_SCHEMA,
        "shape_axes": list(REQUIRED_SHAPE_AXES),
    }


def _shape_from_database_entry(entry: Mapping[str, Any]) -> Shape:
    return Shape(
        str(entry["phase"]),
        tuple(int(value) for value in entry["extend_lengths"]),
        tuple(int(value) for value in entry["past_kv_lengths"]),
    )


def _axis_ranges(shapes: Sequence[Shape]) -> tuple[int, int, int]:
    coordinates = [shape.coordinates for shape in shapes]
    ranges = tuple(max(1, max(values) - min(values)) for values in zip(*coordinates, strict=True))
    if len(ranges) != 3:
        _fail("shape coordinate dimensionality differs from the three-axis contract")
    return ranges[0], ranges[1], ranges[2]


def _nearest_train_entry(
    target: Shape,
    entries: Sequence[Mapping[str, Any]],
    all_phase_shapes: Sequence[Shape],
) -> Mapping[str, Any]:
    candidates = [entry for entry in entries if entry["phase"] == target.phase]
    if not candidates:
        _fail(f"no train database candidates for held-out {target.phase}")
    ranges = _axis_ranges(all_phase_shapes)
    target_coordinates = target.coordinates

    def key(entry: Mapping[str, Any]) -> tuple[Fraction, str]:
        coordinates = _shape_from_database_entry(entry).coordinates
        distance = sum(
            (
                Fraction(abs(actual - expected), scale)
                for actual, expected, scale in zip(
                    coordinates, target_coordinates, ranges, strict=True
                )
            ),
            start=Fraction(0),
        )
        return distance, str(entry["shape_id"])

    return min(candidates, key=key)


def _prediction_batch(profile: PredictionProfile, shape: Shape) -> PredictionBatch:
    if shape.phase not in {"prefill", "decode"}:
        _fail("mixed shape cannot be converted to a phase PredictionBatch")
    return PredictionBatch.for_profile(
        requests=tuple(
            PredictionRequest(extend_length=extension, past_kv_length=previous)
            for extension, previous in zip(shape.extend_lengths, shape.past_kv_lengths, strict=True)
        ),
        phase=PredictionPhase(shape.phase),
        profile=profile,
    )


def _profile_and_support(
    source: VerifiedSourceBundle, config: Mapping[str, Any], database_file: SelectedDatabaseFile
) -> tuple[PredictionProfile, AIConfiguratorSupportManifest]:
    profile = PredictionProfile(
        provider_name="aiconfigurator",
        provider_version=AICONFIGURATOR_PINNED_VERSION,
        provider_source_revision=AICONFIGURATOR_PINNED_COMMIT,
        database_mode=str(config["database_mode"]),
        database_sha256=database_bundle_fingerprint((database_file,)),
        hardware_profile_id=str(source.plan["hardware_profile_id"]),
        hardware_profile_fingerprint=source.hardware_profile_fingerprint,
        model_id=str(_mapping(source.plan["model"], "shape plan model")["id"]),
        model_revision=str(_mapping(source.plan["model"], "shape plan model")["revision"]),
        tensor_parallel_size=int(source.plan["tensor_parallel_size"]),
        pipeline_parallel_size=int(source.plan["pipeline_parallel_size"]),
        forward_boundary=ForwardBoundary(includes_model_collectives=False),
    )
    support = AIConfiguratorSupportManifest(
        provider_version=profile.provider_version,
        provider_source_revision=profile.provider_source_revision,
        profile_fingerprint=profile.fingerprint,
        backend_name="vllm",
        database_mode=profile.database_mode,
        database_sha256=profile.database_sha256,
        hardware_profile_id=profile.hardware_profile_id,
        hardware_profile_fingerprint=profile.hardware_profile_fingerprint,
        model_id=profile.model_id,
        model_revision=profile.model_revision,
        tensor_parallel_size=profile.tensor_parallel_size,
        pipeline_parallel_size=profile.pipeline_parallel_size,
        supported_phases=(PredictionPhase.PREFILL, PredictionPhase.DECODE),
    )
    return profile, support


def _relative_metrics(predicted: Sequence[int], observed: Sequence[int]) -> tuple[float, float]:
    if not predicted or len(predicted) != len(observed):
        _fail("held-out relative metrics require equal non-empty vectors")
    errors = sorted(
        abs(prediction - actual) / actual
        for prediction, actual in zip(predicted, observed, strict=True)
    )
    rank = max(0, math.ceil(0.95 * len(errors)) - 1)
    return math.fsum(errors) / len(errors), errors[rank]


def _phase_residual_bucket_spec(shapes: Sequence[Shape]) -> ShapeBucketSpec:
    phase_shapes = tuple(shape for shape in shapes if shape.phase in {"prefill", "decode"})
    if {shape.phase for shape in phase_shapes} != {"prefill", "decode"}:
        _fail("residual bucket axes require independent prefill/decode shapes")
    return ShapeBucketSpec(
        batch_size_upper_bounds=tuple(sorted({shape.batch_size for shape in phase_shapes})),
        extend_length_upper_bounds=tuple(
            sorted({max(shape.extend_lengths) for shape in phase_shapes})
        ),
        past_kv_length_upper_bounds=tuple(
            sorted({max(1, max(shape.past_kv_lengths)) for shape in phase_shapes})
        ),
    )


def _build_residuals(
    source: VerifiedSourceBundle,
    profile: PredictionProfile,
    database: Mapping[str, Any],
    samples: Mapping[str, tuple[Mapping[str, Any], ...]],
    *,
    preliminary: bool,
) -> tuple[CalibrationReport, Mapping[str, PhaseEvaluation], Mapping[str, Any]]:
    entries = tuple(_mapping(item, "database entry") for item in database["entries"])
    observations: list[CalibrationObservation] = []
    evaluations: dict[str, PhaseEvaluation] = {}
    thresholds = _mapping(source.thresholds["phase_thresholds"], "phase thresholds")
    predictions_by_sample: dict[str, dict[str, object]] = {}
    for phase in ("prefill", "decode"):
        phase_shapes = [shape for shape in source.shapes if shape.phase == phase]
        held_shapes = [
            shape for shape in phase_shapes if source.assignments[shape.shape_id] == "held_out"
        ]
        train_shapes = [
            shape for shape in phase_shapes if source.assignments[shape.shape_id] == "train"
        ]
        if not held_shapes or not train_shapes:
            _fail(f"{phase} train/held-out coverage is incomplete")
        phase_predicted: list[int] = []
        phase_observed: list[int] = []
        for shape in held_shapes:
            nearest = _nearest_train_entry(shape, entries, phase_shapes)
            predicted_ns = int(nearest["estimated_forward_duration_ns"])
            for record in samples[shape.shape_id]:
                repeat_index = int(record["repeat_index"])
                sample_id = f"{phase}:{shape.shape_id}:{repeat_index:06d}"
                observed_ns = int(record["duration_ns"])
                observations.append(
                    CalibrationObservation(
                        sample_id=sample_id,
                        batch=_prediction_batch(profile, shape),
                        raw_prediction_ns=predicted_ns,
                        calibrated_prediction_ns=predicted_ns,
                        observed_forward_duration_ns=observed_ns,
                    )
                )
                predictions_by_sample[sample_id] = {
                    "held_out_shape_id": shape.shape_id,
                    "prediction_source_shape_id": nearest["shape_id"],
                    "predicted_forward_duration_ns": predicted_ns,
                    "observed_forward_duration_ns": observed_ns,
                }
                phase_predicted.append(predicted_ns)
                phase_observed.append(observed_ns)
        mape, p95 = _relative_metrics(phase_predicted, phase_observed)
        phase_threshold = _mapping(thresholds[phase], f"phase threshold {phase}")
        max_mape = float(phase_threshold["max_mean_absolute_percentage_error"])
        max_p95 = float(phase_threshold["max_p95_absolute_relative_error"])
        evaluations[phase] = PhaseEvaluation(
            phase=phase,
            train_shape_count=len(train_shapes),
            held_out_shape_count=len(held_shapes),
            held_out_sample_count=len(phase_observed),
            residual_bucket_count=len(held_shapes),
            mean_absolute_percentage_error=mape,
            p95_absolute_relative_error=p95,
            max_mape=max_mape,
            max_p95=max_p95,
            passed=mape <= max_mape and p95 <= max_p95,
        )
    bucket_spec = _phase_residual_bucket_spec(source.shapes)
    formal = not preliminary and all(item.passed for item in evaluations.values())
    detail = build_calibration_report(
        profile_fingerprint=profile.fingerprint,
        observations=observations,
        bucket_spec=bucket_spec,
        calibration_method=CALIBRATION_METHOD,
        source_evidence_sha256=_sha256_file(source.root / "raw-forward.jsonl"),
        evidence_label=(
            CalibrationEvidenceLabel.CALIBRATED if formal else CalibrationEvidenceLabel.PRELIMINARY
        ),
        formal_use_allowed=formal,
    )
    prediction_audit = {
        "algorithm": "phase_plan_normalized_l1_nearest_train_shape_v1",
        "mixed_used": False,
        "records": [
            {"sample_id": sample_id, **record}
            for sample_id, record in sorted(predictions_by_sample.items())
        ],
        "train_and_held_out_duration_leakage": False,
    }
    return detail, evaluations, prediction_audit


def _mixed_document(
    source: VerifiedSourceBundle,
    samples: Mapping[str, tuple[Mapping[str, Any], ...]],
) -> Mapping[str, Any]:
    observations: list[dict[str, object]] = []
    for shape in source.shapes:
        if shape.phase != "mixed":
            continue
        if source.assignments[shape.shape_id] != "mixed_observation_only":
            _fail("mixed shape assignment is not observation-only")
        durations = tuple(int(record["duration_ns"]) for record in samples[shape.shape_id])
        observations.append(
            {
                "batch_size": shape.batch_size,
                "duration_ns_integer_median_half_up": _integer_median_half_up(durations),
                "extend_lengths": list(shape.extend_lengths),
                "past_kv_lengths": list(shape.past_kv_lengths),
                "sample_count": len(durations),
                "shape_id": shape.shape_id,
            }
        )
    observations.sort(key=lambda item: str(item["shape_id"]))
    return {
        "decomposed_into_prefill_decode": False,
        "formal_use_allowed": False,
        "observations": observations,
        "schema": MIXED_OBSERVATIONS_SCHEMA,
        "used_for_phase_database_fit": False,
        "used_for_phase_residuals": False,
    }


def _artifact(path: Path, relative: str) -> dict[str, object]:
    return {
        "path": relative,
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _write_bytes(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(contents)
        stream.flush()
        os.fsync(stream.fileno())


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_bytes(path, canonical_json_bytes(value))


def _write_verified_snapshot(
    target: Path,
    contents: bytes,
    expected: Mapping[str, object],
    label: str,
) -> None:
    if len(contents) != expected["size_bytes"] or _sha256_bytes(contents) != expected["sha256"]:
        _fail(f"{label} snapshot differs from its initially verified source artifact")
    _write_bytes(target, contents)


def _validate_json_schema(document: Mapping[str, Any], schema_path: Path, label: str) -> None:
    try:
        schema = json.loads(schema_path.read_bytes())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(document)
    except Exception as error:
        _fail(f"{label} failed JSON Schema validation: {error}")


def _support_to_dict(support: AIConfiguratorSupportManifest) -> dict[str, object]:
    return {
        "backend_name": support.backend_name,
        "database_mode": support.database_mode,
        "database_sha256": support.database_sha256,
        "hardware_profile_fingerprint": support.hardware_profile_fingerprint,
        "hardware_profile_id": support.hardware_profile_id,
        "model_id": support.model_id,
        "model_revision": support.model_revision,
        "pipeline_parallel_size": support.pipeline_parallel_size,
        "profile_fingerprint": support.profile_fingerprint,
        "provider_source_revision": support.provider_source_revision,
        "provider_version": support.provider_version,
        "supported_phases": [phase.value for phase in support.supported_phases],
        "tensor_parallel_size": support.tensor_parallel_size,
    }


def _source_manifest_document(
    source: VerifiedSourceBundle,
    reducer_config_sha256: str,
    reducer_script_sha256: str,
) -> Mapping[str, Any]:
    artifacts = [
        {
            "path": name,
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
        }
        for name, record in sorted(source.source_artifacts.items())
    ]
    artifacts.extend(
        (
            {
                "path": "SHA256SUMS",
                "sha256": _sha256_bytes(source.source_checksum_bytes),
                "size_bytes": len(source.source_checksum_bytes),
            },
            {
                "path": "PUBLICATION_COMPLETE.json",
                "sha256": _sha256_bytes(source.source_publication_bytes),
                "size_bytes": len(source.source_publication_bytes),
            },
        )
    )
    return {
        "campaign_profile_fingerprint": source.campaign_profile_fingerprint,
        "hardware_profile_fingerprint": source.hardware_profile_fingerprint,
        "reducer": {
            "config_sha256": reducer_config_sha256,
            "script_sha256": reducer_script_sha256,
        },
        "schema": SOURCE_MANIFEST_OUTPUT_SCHEMA,
        "source_artifacts": artifacts,
        "source_bundle": str(source.root),
        "source_bundle_fingerprint": source.source_bundle_fingerprint,
        "verification": {
            "hashes": "PASS",
            "hardware_profile_binding": "PASS",
            "raw_metadata_join": "PASS",
            "schema_and_order": "PASS",
            "split_disjoint": "PASS",
        },
    }


def _output_sha256sums(stage: Path) -> None:
    paths = sorted(
        (path for path in stage.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(stage).as_posix(),
    )
    lines = [
        f"{_sha256_file(path)}  {path.relative_to(stage).as_posix()}"
        for path in paths
        if path.name != "SHA256SUMS"
    ]
    _write_bytes(stage / "SHA256SUMS", ("\n".join(lines) + "\n").encode())


def _verify_output_sha256sums(stage: Path) -> None:
    checksum = stage / "SHA256SUMS"
    lines = checksum.read_text(encoding="utf-8").splitlines()
    names: list[str] = []
    for line in lines:
        digest, separator, name = line.partition("  ")
        if not separator or not _is_sha256(digest):
            _fail(f"invalid reducer SHA256SUMS line {line!r}")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
            _fail(f"unsafe reducer SHA256SUMS path {name!r}")
        path = stage / relative
        _safe_regular_file(path, f"reducer output {name}")
        if _sha256_file(path) != digest:
            _fail(f"reducer output SHA-256 mismatch for {name}")
        names.append(name)
    expected = sorted(
        path.relative_to(stage).as_posix()
        for path in stage.rglob("*")
        if path.is_file()
        and path.name not in {"SHA256SUMS", "PUBLICATION_INCOMPLETE", "PUBLICATION_COMPLETE.json"}
    )
    if names != expected:
        _fail("reducer SHA256SUMS inventory is incomplete or noncanonical")


def _publish_no_clobber(stage: Path, output_root: Path, *, formal: bool) -> None:
    if output_root.exists() or output_root.is_symlink():
        _fail(f"refusing existing reducer output root: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_root.mkdir(mode=0o750)
    except FileExistsError:
        _fail(f"refusing concurrently created reducer output root: {output_root}")
    incomplete = output_root / "PUBLICATION_INCOMPLETE"
    try:
        _write_bytes(incomplete, b"publication in progress\n")
    except FileExistsError:
        _fail(f"refusing concurrently populated reducer output root: {output_root}")
    try:
        for directory in sorted(
            (path for path in stage.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
        ):
            (output_root / directory.relative_to(stage)).mkdir(exist_ok=False)
        for source in sorted(
            (path for path in stage.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(stage).as_posix(),
        ):
            target = output_root / source.relative_to(stage)
            with source.open("rb") as input_stream, target.open("xb") as output_stream:
                shutil.copyfileobj(input_stream, output_stream, length=8 * 1024 * 1024)
                output_stream.flush()
                os.fsync(output_stream.fileno())
        _verify_output_sha256sums(output_root)
        completion = {
            "formal_use_allowed": formal,
            "no_clobber": True,
            "schema": REDUCTION_PUBLICATION_SCHEMA,
            "sha256sums_sha256": _sha256_file(output_root / "SHA256SUMS"),
            "status": "COMPLETE",
        }
        _write_json(output_root / "PUBLICATION_COMPLETE.json", completion)
        incomplete.unlink()
        descriptor = os.open(output_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except BaseException:
        raise


def _materialize(
    source: VerifiedSourceBundle,
    config: Mapping[str, Any],
    output_root: Path,
    *,
    fixture_mode: bool,
    project_root: Path,
    reducer_script_sha256: str,
) -> bool:
    output_parent = output_root.parent.resolve()
    output_parent.mkdir(parents=True, exist_ok=True)
    output_root = output_parent / output_root.name
    stage_path = Path(tempfile.mkdtemp(prefix=".moonkvsim-aic-reduce-", dir=output_parent))
    try:
        reducer_config_bytes = _source_canonical_json_bytes(config)
        reducer_config_sha256 = _sha256_bytes(reducer_config_bytes)
        samples = _measured_samples_by_shape(source)
        database = _database_document(source, config, samples)
        database_path = stage_path / DATABASE_RELATIVE_PATH
        _write_json(database_path, database)
        _validate_json_schema(
            database,
            project_root / "schemas/aiconfigurator-phase-shape-database.schema.json",
            "materialized phase-shape database",
        )
        database_file = SelectedDatabaseFile(
            path=DATABASE_RELATIVE_PATH,
            sha256=_sha256_file(database_path),
            size_bytes=database_path.stat().st_size,
        )
        profile, support = _profile_and_support(source, config, database_file)

        detail_preliminary, initial_evaluations, prediction_audit = _build_residuals(
            source,
            profile,
            database,
            samples,
            preliminary=fixture_mode,
        )
        thresholds_pass = all(item.passed for item in initial_evaluations.values())
        formal = thresholds_pass and not fixture_mode
        if formal:
            detail, evaluations, prediction_audit = _build_residuals(
                source,
                profile,
                database,
                samples,
                preliminary=False,
            )
        else:
            detail, evaluations = detail_preliminary, initial_evaluations

        mixed = _mixed_document(source, samples)
        mixed_path = stage_path / MIXED_PATH
        _write_json(mixed_path, mixed)
        detail_document = detail.to_dict()
        detail_path = stage_path / DETAIL_REPORT_PATH
        _write_json(detail_path, detail_document)
        prediction_audit_path = stage_path / PREDICTION_AUDIT_PATH
        _write_json(prediction_audit_path, prediction_audit)

        for source_name, relative in (
            ("raw-forward.jsonl", RAW_COPY_PATH),
            ("step-metadata.jsonl", METADATA_COPY_PATH),
            ("held-out-split.json", SPLIT_COPY_PATH),
            ("residual-thresholds.json", ORIGINAL_THRESHOLDS_COPY_PATH),
            ("manifest.json", PHYSICAL_MANIFEST_COPY_PATH),
            ("environment.json", ENVIRONMENT_COPY_PATH),
        ):
            _write_verified_snapshot(
                stage_path / relative,
                source.source_artifact_bytes[source_name],
                source.source_artifacts[source_name],
                f"source artifact {source_name}",
            )
        _write_bytes(stage_path / SOURCE_CHECKSUM_COPY_PATH, source.source_checksum_bytes)
        _write_bytes(stage_path / REDUCER_CONFIG_COPY_PATH, reducer_config_bytes)

        original_phase_thresholds = source.thresholds["phase_thresholds"]
        bound_thresholds = {
            "calibration_method": CALIBRATION_METHOD,
            "phase_thresholds": original_phase_thresholds,
            "profile_fingerprint": profile.fingerprint,
            "schema": THRESHOLD_SCHEMA,
            "shape_axes": list(REQUIRED_SHAPE_AXES),
        }
        bound_threshold_path = stage_path / BOUND_THRESHOLDS_PATH
        _write_json(bound_threshold_path, bound_thresholds)
        _validate_json_schema(
            bound_thresholds,
            project_root / "schemas/predictor-residual-thresholds.schema.json",
            "selected-profile thresholds",
        )

        source_manifest = _source_manifest_document(
            source, reducer_config_sha256, reducer_script_sha256
        )
        _write_json(stage_path / "source-manifest.json", source_manifest)

        train_ids = sorted(
            shape_id for shape_id, value in source.assignments.items() if value == "train"
        )
        held_ids = sorted(
            shape_id for shape_id, value in source.assignments.items() if value == "held_out"
        )
        mixed_ids = sorted(
            shape_id
            for shape_id, value in source.assignments.items()
            if value == "mixed_observation_only"
        )
        diagnostics: list[dict[str, str]] = []
        if fixture_mode:
            diagnostics.append(
                {
                    "code": "fixture_mode_forbids_formal_use",
                    "message": "fixture validation is E1/E2 reducer evidence only",
                }
            )
        for phase, evaluation in sorted(evaluations.items()):
            if not evaluation.passed:
                diagnostics.append(
                    {
                        "code": f"{phase}_held_out_threshold_failed",
                        "message": (f"{phase} held-out MAPE/p95 exceeds the predeclared threshold"),
                    }
                )
        candidate = {
            "calibration": {
                "detail_report": _artifact(detail_path, DETAIL_REPORT_PATH),
                "formal_residual_report": FORMAL_REPORT_PATH if formal else None,
                "held_out_split": _artifact(stage_path / SPLIT_COPY_PATH, SPLIT_COPY_PATH),
                "prediction_audit": _artifact(prediction_audit_path, PREDICTION_AUDIT_PATH),
                "raw_source": _artifact(stage_path / RAW_COPY_PATH, RAW_COPY_PATH),
                "thresholds": _artifact(bound_threshold_path, BOUND_THRESHOLDS_PATH),
            },
            "database_files": [database_file.to_dict()],
            "diagnostics": diagnostics,
            "formal_use_allowed": formal,
            "profile": profile.to_dict(),
            "schema": PROFILE_CANDIDATE_SCHEMA,
            "support": _support_to_dict(support),
        }
        _write_json(stage_path / "profile-candidate.json", candidate)

        formal_report_path = stage_path / FORMAL_REPORT_PATH
        if formal:
            formal_report = {
                "calibration_method": CALIBRATION_METHOD,
                "formal_use_allowed": True,
                "held_out_split_manifest_sha256": _sha256_file(stage_path / SPLIT_COPY_PATH),
                "phase_results": {
                    phase: evaluations[phase].to_formal_dict() for phase in ("prefill", "decode")
                },
                "profile_fingerprint": profile.fingerprint,
                "schema": "moonkvsim.aiconfigurator-held-out-residual-report.v1",
                "shape_axes": list(REQUIRED_SHAPE_AXES),
                "source_evidence_sha256": _sha256_file(stage_path / RAW_COPY_PATH),
                "threshold_declaration": _artifact(bound_threshold_path, BOUND_THRESHOLDS_PATH),
            }
            _write_json(formal_report_path, formal_report)
            _validate_json_schema(
                formal_report,
                project_root / "schemas/predictor-held-out-residual-report.schema.json",
                "formal held-out residual report",
            )
            calibration = HeldOutCalibrationRecord(
                report_fingerprint=_sha256_file(formal_report_path),
                report_path=FORMAL_REPORT_PATH,
                report_size_bytes=formal_report_path.stat().st_size,
                profile_fingerprint=profile.fingerprint,
                source_evidence_sha256=_sha256_file(stage_path / RAW_COPY_PATH),
                source_evidence_path=RAW_COPY_PATH,
                source_evidence_size_bytes=(stage_path / RAW_COPY_PATH).stat().st_size,
                held_out_split_manifest_sha256=_sha256_file(stage_path / SPLIT_COPY_PATH),
                held_out_split_manifest_path=SPLIT_COPY_PATH,
                held_out_split_manifest_size_bytes=(stage_path / SPLIT_COPY_PATH).stat().st_size,
                calibration_method=CALIBRATION_METHOD,
                shape_axes=REQUIRED_SHAPE_AXES,
                prefill_sample_count=evaluations["prefill"].held_out_sample_count,
                decode_sample_count=evaluations["decode"].held_out_sample_count,
                prefill_residual_bucket_count=evaluations["prefill"].residual_bucket_count,
                decode_residual_bucket_count=evaluations["decode"].residual_bucket_count,
                formal_use_allowed=True,
            )
            engine = _mapping(source.plan["engine"], "shape plan engine")
            selection = AIConfiguratorProfileSelection(
                profile=profile,
                support=support,
                target_backend_version=str(engine["installed_version"]),
                database_backend_version=str(engine["installed_version"]),
                database_files=(database_file,),
                calibration=calibration,
                formal_use_allowed=True,
            )
            selection_path = stage_path / "profile-selection.json"
            _write_bytes(selection_path, selection.to_json_bytes())
            _validate_json_schema(
                selection.to_dict(),
                project_root / "schemas/predictor-profile-selection.schema.json",
                "formal profile selection",
            )
            load_aiconfigurator_profile_selection(
                selection_path,
                installed_version=AICONFIGURATOR_PINNED_VERSION,
                require_e3=True,
            )

        original_threshold_path = stage_path / ORIGINAL_THRESHOLDS_COPY_PATH
        reduction_report = {
            "database": _artifact(database_path, DATABASE_RELATIVE_PATH),
            "diagnostics": diagnostics,
            "evidence_class": (
                "E3_physical_forward_calibration"
                if formal
                else (
                    "E1_E2_reducer_fixture_only"
                    if fixture_mode
                    else "physical_forward_calibration_preliminary"
                )
            ),
            "fixture_mode": fixture_mode,
            "formal_use_allowed": formal,
            "hardware_profile_fingerprint": source.hardware_profile_fingerprint,
            "mixed_observations": {
                "artifact": _artifact(mixed_path, MIXED_PATH),
                "decomposed_into_phases": False,
                "used_for_phase_fit": False,
            },
            "phase_results": {
                phase: evaluations[phase].to_reduction_dict() for phase in ("prefill", "decode")
            },
            "profile_fingerprint": profile.fingerprint,
            "schema": REDUCTION_REPORT_SCHEMA,
            "source_bundle_fingerprint": source.source_bundle_fingerprint,
            "source_campaign_profile_fingerprint": source.campaign_profile_fingerprint,
            "split_audit": {
                "disjoint": not bool(set(train_ids) & set(held_ids)),
                "held_out_shape_ids": held_ids,
                "mixed_shape_ids": mixed_ids,
                "train_shape_ids": train_ids,
            },
            "status": "FORMAL_SELECTION_READY" if formal else "PRELIMINARY_ONLY",
            "threshold_rebinding": {
                "numeric_values_unchanged": (
                    bound_thresholds["phase_thresholds"] == source.thresholds["phase_thresholds"]
                ),
                "original_campaign_thresholds": _artifact(
                    original_threshold_path, ORIGINAL_THRESHOLDS_COPY_PATH
                ),
                "selected_profile_thresholds": _artifact(
                    bound_threshold_path, BOUND_THRESHOLDS_PATH
                ),
            },
        }
        _write_json(stage_path / "reduction-report.json", reduction_report)
        _validate_json_schema(
            reduction_report,
            project_root / "schemas/aiconfigurator-forward-reduction-report.schema.json",
            "reduction report",
        )
        (
            final_publication,
            final_source_artifacts,
            _final_source_bytes,
            final_checksum_bytes,
            final_publication_bytes,
        ) = _verify_source_publication(source.root)
        if (
            not _json_equal(final_publication, source.source_publication)
            or final_source_artifacts != source.source_artifacts
            or final_checksum_bytes != source.source_checksum_bytes
            or final_publication_bytes != source.source_publication_bytes
        ):
            _fail("source bundle changed while the reducer was materializing outputs")
        _output_sha256sums(stage_path)
        _verify_output_sha256sums(stage_path)
        _publish_no_clobber(stage_path, output_root, formal=formal)
        return formal
    finally:
        if stage_path.exists() and stage_path.is_dir() and stage_path.parent == output_parent:
            shutil.rmtree(stage_path)


def reduce_bundle(
    *,
    input_bundle: Path,
    output_root: Path,
    reducer_config: Path,
    fixture_mode: bool,
) -> bool:
    """Validate and reduce one bundle; return whether a formal selection was emitted."""

    output_path = output_root.absolute()
    input_path = input_bundle.absolute()
    reducer_config_path = reducer_config.absolute()
    if output_path.exists() or output_path.is_symlink():
        _fail(f"refusing existing reducer output root: {output_path}")
    config = _load_config(reducer_config_path)
    source = verify_source_bundle(input_path)
    project_root = Path(__file__).resolve().parents[2]
    reducer_script_sha256 = _sha256_bytes(
        _read_regular_file_bytes(Path(__file__).absolute(), "reducer script")
    )
    return _materialize(
        source,
        config,
        output_path,
        fixture_mode=fixture_mode,
        project_root=project_root,
        reducer_script_sha256=reducer_script_sha256,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bundle", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--reducer-config", type=Path, required=True)
    parser.add_argument(
        "--fixture-mode",
        action="store_true",
        help="exercise the reducer but force preliminary E1/E2-only output",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        formal = reduce_bundle(
            input_bundle=args.input_bundle,
            output_root=args.output_root,
            reducer_config=args.reducer_config,
            fixture_mode=args.fixture_mode,
        )
    except (OSError, ReductionError) as error:
        print(f"MOONKVSIM_AIC_REDUCER_ERROR={error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "formal_use_allowed": formal,
                "output_root": str(args.output_root.resolve()),
                "status": "FORMAL_SELECTION_READY" if formal else "PRELIMINARY_ONLY",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
