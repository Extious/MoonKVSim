"""Fail-closed AIConfigurator profile-selection and E3 calibration gate.

The source-support audit is not a selected predictor profile.  Formal use needs
an exact database bundle and a held-out, phase/shape-separated residual record.
This module intentionally has no global scalar correction field; unknown keys
are rejected by the loader so a ``global_scale_factor`` cannot be smuggled in.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from moonkvsim.common.hash import canonical_json_bytes, sha256_json
from moonkvsim.predictor.aiconfigurator import (
    AIConfiguratorSupportManifest,
    probe_aiconfigurator,
)
from moonkvsim.predictor.schema import (
    ForwardBoundary,
    PredictionPhase,
    PredictionProfile,
    _require_non_empty,
    _require_positive_int,
    _require_sha256,
)

PROFILE_SELECTION_SCHEMA = "moonkvsim.aiconfigurator-profile-selection.v1"
CALIBRATION_METHOD = "phase_shape_residual_table"
REQUIRED_SHAPE_AXES = ("batch_size", "extend_length", "past_kv_length")
RESIDUAL_REPORT_SCHEMA = "moonkvsim.aiconfigurator-held-out-residual-report.v1"
RESIDUAL_THRESHOLDS_SCHEMA = "moonkvsim.aiconfigurator-residual-thresholds.v1"


class AIConfiguratorE3Error(RuntimeError):
    """Raised when an unresolved or uncalibrated profile is used as E3."""


@dataclass(frozen=True, slots=True)
class E3Diagnostic:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class E3Readiness:
    diagnostics: tuple[E3Diagnostic, ...]

    @property
    def ready(self) -> bool:
        return not self.diagnostics

    def require_ready(self) -> None:
        if self.diagnostics:
            detail = "; ".join(f"{item.code}: {item.message}" for item in self.diagnostics)
            raise AIConfiguratorE3Error(detail)


@dataclass(frozen=True, slots=True)
class SelectedDatabaseFile:
    """One materialized performance database file in a selected bundle."""

    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        _require_non_empty(self.path, "path")
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or path.as_posix() != self.path
        ):
            raise ValueError("artifact path must be a canonical safe relative POSIX path")
        _require_sha256(self.sha256, "sha256")
        _require_positive_int(self.size_bytes, "size_bytes")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


def database_bundle_fingerprint(files: tuple[SelectedDatabaseFile, ...]) -> str:
    """Hash a canonical, path-unique database manifest rather than raw concatenation."""

    ordered = tuple(sorted(files, key=lambda item: item.path))
    if len({item.path for item in ordered}) != len(ordered):
        raise ValueError("selected database paths must be unique")
    return sha256_json([item.to_dict() for item in ordered])


@dataclass(frozen=True, slots=True)
class HeldOutCalibrationRecord:
    """Hash-bound evidence summary for a held-out residual evaluation."""

    report_fingerprint: str
    report_path: str
    report_size_bytes: int
    profile_fingerprint: str
    source_evidence_sha256: str
    source_evidence_path: str
    source_evidence_size_bytes: int
    held_out_split_manifest_sha256: str
    held_out_split_manifest_path: str
    held_out_split_manifest_size_bytes: int
    calibration_method: str
    shape_axes: tuple[str, ...]
    prefill_sample_count: int
    decode_sample_count: int
    prefill_residual_bucket_count: int
    decode_residual_bucket_count: int
    formal_use_allowed: bool

    def __post_init__(self) -> None:
        for field_name in (
            "report_fingerprint",
            "profile_fingerprint",
            "source_evidence_sha256",
            "held_out_split_manifest_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name)
        for field_name in (
            "report_path",
            "source_evidence_path",
            "held_out_split_manifest_path",
        ):
            _require_relative_artifact_path(getattr(self, field_name), field_name)
        for field_name in (
            "report_size_bytes",
            "source_evidence_size_bytes",
            "held_out_split_manifest_size_bytes",
        ):
            _require_positive_int(getattr(self, field_name), field_name)
        if self.calibration_method != CALIBRATION_METHOD:
            raise ValueError(
                f"calibration_method must be {CALIBRATION_METHOD!r}; global scaling is forbidden"
            )
        if self.shape_axes != REQUIRED_SHAPE_AXES:
            raise ValueError(
                "held-out calibration must separate batch_size, extend_length, and "
                "past_kv_length"
            )
        for field_name in (
            "prefill_sample_count",
            "decode_sample_count",
            "prefill_residual_bucket_count",
            "decode_residual_bucket_count",
        ):
            _require_positive_int(getattr(self, field_name), field_name)
        if not isinstance(self.formal_use_allowed, bool):
            raise TypeError("formal_use_allowed must be boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "report_fingerprint": self.report_fingerprint,
            "report_path": self.report_path,
            "report_size_bytes": self.report_size_bytes,
            "profile_fingerprint": self.profile_fingerprint,
            "source_evidence_sha256": self.source_evidence_sha256,
            "source_evidence_path": self.source_evidence_path,
            "source_evidence_size_bytes": self.source_evidence_size_bytes,
            "held_out_split_manifest_sha256": self.held_out_split_manifest_sha256,
            "held_out_split_manifest_path": self.held_out_split_manifest_path,
            "held_out_split_manifest_size_bytes": (
                self.held_out_split_manifest_size_bytes
            ),
            "calibration_method": self.calibration_method,
            "shape_axes": list(self.shape_axes),
            "phase_sample_counts": {
                "prefill": self.prefill_sample_count,
                "decode": self.decode_sample_count,
            },
            "phase_residual_bucket_counts": {
                "prefill": self.prefill_residual_bucket_count,
                "decode": self.decode_residual_bucket_count,
            },
            "formal_use_allowed": self.formal_use_allowed,
        }


@dataclass(frozen=True, slots=True)
class AIConfiguratorProfileSelection:
    """A complete selected profile candidate; readiness remains separately evaluated."""

    profile: PredictionProfile
    support: AIConfiguratorSupportManifest
    target_backend_version: str
    database_backend_version: str
    database_files: tuple[SelectedDatabaseFile, ...]
    calibration: HeldOutCalibrationRecord | None
    formal_use_allowed: bool
    _database_files_materialized: bool = field(
        default=False, repr=False, compare=False
    )
    _calibration_evidence_materialized: bool = field(
        default=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.profile, PredictionProfile):
            raise TypeError("profile must be a PredictionProfile")
        if not isinstance(self.support, AIConfiguratorSupportManifest):
            raise TypeError("support must be an AIConfiguratorSupportManifest")
        _require_non_empty(self.target_backend_version, "target_backend_version")
        _require_non_empty(self.database_backend_version, "database_backend_version")
        if not isinstance(self.database_files, tuple) or any(
            not isinstance(item, SelectedDatabaseFile) for item in self.database_files
        ):
            raise TypeError("database_files must be a tuple of SelectedDatabaseFile values")
        if self.calibration is not None and not isinstance(
            self.calibration, HeldOutCalibrationRecord
        ):
            raise TypeError("calibration must be a HeldOutCalibrationRecord or None")
        if not isinstance(self.formal_use_allowed, bool):
            raise TypeError("formal_use_allowed must be boolean")
        if not isinstance(self._database_files_materialized, bool):
            raise TypeError("_database_files_materialized must be boolean")
        if not isinstance(self._calibration_evidence_materialized, bool):
            raise TypeError("_calibration_evidence_materialized must be boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": PROFILE_SELECTION_SCHEMA,
            "profile": self.profile.to_dict(),
            "support": _support_to_dict(self.support),
            "target_backend_version": self.target_backend_version,
            "database_backend_version": self.database_backend_version,
            "database_files": [
                item.to_dict() for item in sorted(self.database_files, key=lambda item: item.path)
            ],
            "calibration": None if self.calibration is None else self.calibration.to_dict(),
            "formal_use_allowed": self.formal_use_allowed,
        }

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def evaluate_e3_readiness(
    selection: AIConfiguratorProfileSelection | None,
    *,
    installed_version: str | None,
) -> E3Readiness:
    """Evaluate every independent E3 requirement without silently filling defaults."""

    if selection is None:
        return E3Readiness(
            (
                E3Diagnostic(
                    "profile_selection_unresolved",
                    "no AIConfigurator profile/database/calibration selection record exists",
                ),
            )
        )

    diagnostics: list[E3Diagnostic] = []
    availability = probe_aiconfigurator(
        selection.profile,
        support=selection.support,
        installed_version=installed_version,
    )
    diagnostics.extend(E3Diagnostic(item.code, item.message) for item in availability.diagnostics)

    if selection.target_backend_version != selection.database_backend_version:
        diagnostics.append(
            E3Diagnostic(
                "backend_database_version_mismatch",
                "selected performance database was collected for a different backend version",
            )
        )
    if not selection.database_files:
        diagnostics.append(
            E3Diagnostic(
                "database_bundle_missing",
                "the selected profile has no materialized performance database files",
            )
        )
    else:
        actual_bundle = database_bundle_fingerprint(selection.database_files)
        if actual_bundle != selection.profile.database_sha256:
            diagnostics.append(
                E3Diagnostic(
                    "database_bundle_hash_mismatch",
                    "selected database file manifest does not match the profile fingerprint input",
                )
            )
        if not selection._database_files_materialized:
            diagnostics.append(
                E3Diagnostic(
                    "materialized_database_evidence_unverified",
                    "database paths, sizes, and SHA-256 values were not verified from "
                    "regular files relative to the selection record",
                )
            )

    calibration = selection.calibration
    if calibration is None:
        diagnostics.append(
            E3Diagnostic(
                "held_out_calibration_missing",
                "no phase/shape-separated held-out residual record was supplied",
            )
        )
    else:
        if calibration.profile_fingerprint != selection.profile.fingerprint:
            diagnostics.append(
                E3Diagnostic(
                    "calibration_profile_mismatch",
                    "held-out residuals were produced for a different profile",
                )
            )
        if not calibration.formal_use_allowed:
            diagnostics.append(
                E3Diagnostic(
                    "held_out_calibration_preliminary",
                    "held-out residual evidence is not approved for formal use",
                )
            )
        if not selection._calibration_evidence_materialized:
            diagnostics.append(
                E3Diagnostic(
                    "materialized_calibration_evidence_unverified",
                    "residual report, raw source evidence, and held-out split files "
                    "were not verified from their declared sizes and SHA-256 values",
                )
            )
        # Counts and axes are validated by HeldOutCalibrationRecord.  Keeping
        # this explicit guard makes the policy legible if construction changes.
        if calibration.shape_axes != REQUIRED_SHAPE_AXES:
            diagnostics.append(
                E3Diagnostic(
                    "shape_coverage_incomplete",
                    "held-out residuals do not cover all required shape axes",
                )
            )
    if not selection.formal_use_allowed:
        diagnostics.append(
            E3Diagnostic(
                "selection_not_approved",
                "the selected profile record does not allow formal use",
            )
        )
    return E3Readiness(tuple(diagnostics))


def load_aiconfigurator_profile_selection(
    path: Path,
    *,
    installed_version: str | None,
    require_e3: bool = True,
) -> AIConfiguratorProfileSelection:
    """Load a formal selection and verify every referenced artifact before E3.

    Paths in the record are resolved beneath the selection file's directory.
    Directory and leaf symlinks, non-regular files, traversal, size drift, and
    content-hash drift are rejected even when ``require_e3`` is false.  The
    separate support-audit artifact records unsupported/preliminary candidates;
    this loader deliberately accepts only the formal selection schema.
    """

    try:
        raw_bytes = _read_selection_file(path)
    except OSError as error:
        raise AIConfiguratorE3Error(f"profile_selection_file_unavailable: {error}") from error
    try:
        raw = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AIConfiguratorE3Error(f"profile_selection_invalid_json: {error}") from error
    root = _mapping(raw, "$")
    if canonical_json_bytes(root) != raw_bytes:
        raise AIConfiguratorE3Error("profile_selection_not_canonical_json")
    try:
        selection = _selection_from_mapping(root)
    except (KeyError, TypeError, ValueError) as error:
        raise AIConfiguratorE3Error(f"profile_selection_invalid: {error}") from error
    try:
        _verify_materialized_selection_artifacts(path.parent, selection)
    except (OSError, ValueError) as error:
        raise AIConfiguratorE3Error(
            f"profile_selection_artifact_verification_failed: {error}"
        ) from error
    selection = replace(
        selection,
        _database_files_materialized=True,
        _calibration_evidence_materialized=True,
    )
    if require_e3:
        evaluate_e3_readiness(selection, installed_version=installed_version).require_ready()
    return selection


def _selection_from_mapping(root: Mapping[str, object]) -> AIConfiguratorProfileSelection:
    _require_exact_keys(
        root,
        {
            "schema",
            "profile",
            "support",
            "target_backend_version",
            "database_backend_version",
            "database_files",
            "calibration",
            "formal_use_allowed",
        },
        "$",
    )
    if root["schema"] != PROFILE_SELECTION_SCHEMA:
        raise ValueError(f"schema must be {PROFILE_SELECTION_SCHEMA!r}")
    profile = _profile_from_mapping(_mapping(root["profile"], "$.profile"))
    support = _support_from_mapping(_mapping(root["support"], "$.support"))
    database_files = tuple(
        _database_file_from_mapping(_mapping(item, "$.database_files[]"))
        for item in _list(root["database_files"], "$.database_files")
    )
    calibration = _calibration_from_mapping(
        _mapping(root["calibration"], "$.calibration")
    )
    formal_use_allowed = _boolean(
        root["formal_use_allowed"], "$.formal_use_allowed"
    )
    if not calibration.formal_use_allowed or not formal_use_allowed:
        raise ValueError(
            "formal selection loader requires calibration.formal_use_allowed=true "
            "and formal_use_allowed=true; use the support audit for preliminary state"
        )
    return AIConfiguratorProfileSelection(
        profile=profile,
        support=support,
        target_backend_version=_string(
            root["target_backend_version"], "$.target_backend_version"
        ),
        database_backend_version=_string(
            root["database_backend_version"], "$.database_backend_version"
        ),
        database_files=database_files,
        calibration=calibration,
        formal_use_allowed=formal_use_allowed,
    )


def _profile_from_mapping(raw: Mapping[str, object]) -> PredictionProfile:
    _require_exact_keys(
        raw,
        {
            "provider_name",
            "provider_version",
            "provider_source_revision",
            "database_mode",
            "database_sha256",
            "hardware_profile_id",
            "hardware_profile_fingerprint",
            "model_id",
            "model_revision",
            "tensor_parallel_size",
            "pipeline_parallel_size",
            "forward_boundary",
            "fingerprint",
        },
        "$.profile",
    )
    boundary_raw = _mapping(raw["forward_boundary"], "$.profile.forward_boundary")
    _require_exact_keys(
        boundary_raw,
        {
            "scope",
            "included_components",
            "includes_model_collectives",
            "model_collective_scope",
            "excluded_components",
        },
        "$.profile.forward_boundary",
    )
    if boundary_raw["scope"] != "gpu_forward_only":
        raise ValueError("profile forward boundary must be gpu_forward_only")
    boundary = ForwardBoundary(
        includes_model_collectives=_boolean(
            boundary_raw["includes_model_collectives"],
            "$.profile.forward_boundary.includes_model_collectives",
        ),
        model_collective_scope=_optional_string(
            boundary_raw["model_collective_scope"],
            "$.profile.forward_boundary.model_collective_scope",
        ),
    )
    if dict(boundary_raw) != boundary.to_dict():
        raise ValueError("profile forward boundary does not match the fixed contract")
    profile = PredictionProfile(
        provider_name=_string(raw["provider_name"], "$.profile.provider_name"),
        provider_version=_string(raw["provider_version"], "$.profile.provider_version"),
        provider_source_revision=_string(
            raw["provider_source_revision"], "$.profile.provider_source_revision"
        ),
        database_mode=_string(raw["database_mode"], "$.profile.database_mode"),
        database_sha256=_string(raw["database_sha256"], "$.profile.database_sha256"),
        hardware_profile_id=_string(
            raw["hardware_profile_id"], "$.profile.hardware_profile_id"
        ),
        hardware_profile_fingerprint=_string(
            raw["hardware_profile_fingerprint"],
            "$.profile.hardware_profile_fingerprint",
        ),
        model_id=_string(raw["model_id"], "$.profile.model_id"),
        model_revision=_string(raw["model_revision"], "$.profile.model_revision"),
        tensor_parallel_size=_integer(
            raw["tensor_parallel_size"], "$.profile.tensor_parallel_size"
        ),
        pipeline_parallel_size=_integer(
            raw["pipeline_parallel_size"], "$.profile.pipeline_parallel_size"
        ),
        forward_boundary=boundary,
    )
    if raw["fingerprint"] != profile.fingerprint:
        raise ValueError("profile fingerprint mismatch")
    return profile


def _support_from_mapping(raw: Mapping[str, object]) -> AIConfiguratorSupportManifest:
    expected = {
        "provider_version",
        "provider_source_revision",
        "profile_fingerprint",
        "backend_name",
        "database_mode",
        "database_sha256",
        "hardware_profile_id",
        "hardware_profile_fingerprint",
        "model_id",
        "model_revision",
        "tensor_parallel_size",
        "pipeline_parallel_size",
        "supported_phases",
    }
    _require_exact_keys(raw, expected, "$.support")
    return AIConfiguratorSupportManifest(
        provider_version=_string(raw["provider_version"], "$.support.provider_version"),
        provider_source_revision=_string(
            raw["provider_source_revision"], "$.support.provider_source_revision"
        ),
        profile_fingerprint=_string(
            raw["profile_fingerprint"], "$.support.profile_fingerprint"
        ),
        backend_name=_string(raw["backend_name"], "$.support.backend_name"),
        database_mode=_string(raw["database_mode"], "$.support.database_mode"),
        database_sha256=_string(raw["database_sha256"], "$.support.database_sha256"),
        hardware_profile_id=_string(
            raw["hardware_profile_id"], "$.support.hardware_profile_id"
        ),
        hardware_profile_fingerprint=_string(
            raw["hardware_profile_fingerprint"],
            "$.support.hardware_profile_fingerprint",
        ),
        model_id=_string(raw["model_id"], "$.support.model_id"),
        model_revision=_string(raw["model_revision"], "$.support.model_revision"),
        tensor_parallel_size=_integer(
            raw["tensor_parallel_size"], "$.support.tensor_parallel_size"
        ),
        pipeline_parallel_size=_integer(
            raw["pipeline_parallel_size"], "$.support.pipeline_parallel_size"
        ),
        supported_phases=tuple(
            PredictionPhase(_string(item, "$.support.supported_phases[]"))
            for item in _list(raw["supported_phases"], "$.support.supported_phases")
        ),
    )


def _support_to_dict(support: AIConfiguratorSupportManifest) -> dict[str, object]:
    return {
        "provider_version": support.provider_version,
        "provider_source_revision": support.provider_source_revision,
        "profile_fingerprint": support.profile_fingerprint,
        "backend_name": support.backend_name,
        "database_mode": support.database_mode,
        "database_sha256": support.database_sha256,
        "hardware_profile_id": support.hardware_profile_id,
        "hardware_profile_fingerprint": support.hardware_profile_fingerprint,
        "model_id": support.model_id,
        "model_revision": support.model_revision,
        "tensor_parallel_size": support.tensor_parallel_size,
        "pipeline_parallel_size": support.pipeline_parallel_size,
        "supported_phases": [phase.value for phase in support.supported_phases],
    }


def _database_file_from_mapping(raw: Mapping[str, object]) -> SelectedDatabaseFile:
    _require_exact_keys(raw, {"path", "sha256", "size_bytes"}, "$.database_files[]")
    return SelectedDatabaseFile(
        path=_string(raw["path"], "$.database_files[].path"),
        sha256=_string(raw["sha256"], "$.database_files[].sha256"),
        size_bytes=_integer(raw["size_bytes"], "$.database_files[].size_bytes"),
    )


def _calibration_from_mapping(raw: Mapping[str, object]) -> HeldOutCalibrationRecord:
    # Exact-key validation deliberately rejects global_scale_factor and any
    # similarly undeclared correction knob.
    _require_exact_keys(
        raw,
        {
            "report_fingerprint",
            "report_path",
            "report_size_bytes",
            "profile_fingerprint",
            "source_evidence_sha256",
            "source_evidence_path",
            "source_evidence_size_bytes",
            "held_out_split_manifest_sha256",
            "held_out_split_manifest_path",
            "held_out_split_manifest_size_bytes",
            "calibration_method",
            "shape_axes",
            "phase_sample_counts",
            "phase_residual_bucket_counts",
            "formal_use_allowed",
        },
        "$.calibration",
    )
    sample_counts = _mapping(raw["phase_sample_counts"], "$.calibration.phase_sample_counts")
    bucket_counts = _mapping(
        raw["phase_residual_bucket_counts"],
        "$.calibration.phase_residual_bucket_counts",
    )
    phase_keys = {phase.value for phase in PredictionPhase}
    _require_exact_keys(sample_counts, phase_keys, "$.calibration.phase_sample_counts")
    _require_exact_keys(
        bucket_counts,
        phase_keys,
        "$.calibration.phase_residual_bucket_counts",
    )
    return HeldOutCalibrationRecord(
        report_fingerprint=_string(
            raw["report_fingerprint"], "$.calibration.report_fingerprint"
        ),
        report_path=_string(raw["report_path"], "$.calibration.report_path"),
        report_size_bytes=_integer(
            raw["report_size_bytes"], "$.calibration.report_size_bytes"
        ),
        profile_fingerprint=_string(
            raw["profile_fingerprint"], "$.calibration.profile_fingerprint"
        ),
        source_evidence_sha256=_string(
            raw["source_evidence_sha256"], "$.calibration.source_evidence_sha256"
        ),
        source_evidence_path=_string(
            raw["source_evidence_path"], "$.calibration.source_evidence_path"
        ),
        source_evidence_size_bytes=_integer(
            raw["source_evidence_size_bytes"],
            "$.calibration.source_evidence_size_bytes",
        ),
        held_out_split_manifest_sha256=_string(
            raw["held_out_split_manifest_sha256"],
            "$.calibration.held_out_split_manifest_sha256",
        ),
        held_out_split_manifest_path=_string(
            raw["held_out_split_manifest_path"],
            "$.calibration.held_out_split_manifest_path",
        ),
        held_out_split_manifest_size_bytes=_integer(
            raw["held_out_split_manifest_size_bytes"],
            "$.calibration.held_out_split_manifest_size_bytes",
        ),
        calibration_method=_string(
            raw["calibration_method"], "$.calibration.calibration_method"
        ),
        shape_axes=tuple(
            _string(item, "$.calibration.shape_axes[]")
            for item in _list(raw["shape_axes"], "$.calibration.shape_axes")
        ),
        prefill_sample_count=_integer(
            sample_counts[PredictionPhase.PREFILL.value],
            "$.calibration.phase_sample_counts.prefill",
        ),
        decode_sample_count=_integer(
            sample_counts[PredictionPhase.DECODE.value],
            "$.calibration.phase_sample_counts.decode",
        ),
        prefill_residual_bucket_count=_integer(
            bucket_counts[PredictionPhase.PREFILL.value],
            "$.calibration.phase_residual_bucket_counts.prefill",
        ),
        decode_residual_bucket_count=_integer(
            bucket_counts[PredictionPhase.DECODE.value],
            "$.calibration.phase_residual_bucket_counts.decode",
        ),
        formal_use_allowed=_boolean(
            raw["formal_use_allowed"], "$.calibration.formal_use_allowed"
        ),
    )


def _verify_materialized_selection_artifacts(
    selection_directory: Path,
    selection: AIConfiguratorProfileSelection,
) -> None:
    """Hash regular files through no-follow directory descriptors."""

    for item in selection.database_files:
        _verify_relative_regular_file(
            selection_directory,
            path=item.path,
            expected_size=item.size_bytes,
            expected_sha256=item.sha256,
            label="database file",
        )

    calibration = selection.calibration
    if calibration is None:
        raise ValueError("formal selection calibration is missing")
    report_bytes = _verify_relative_regular_file(
        selection_directory,
        path=calibration.report_path,
        expected_size=calibration.report_size_bytes,
        expected_sha256=calibration.report_fingerprint,
        label="held-out residual report",
    )
    for label, artifact_path, expected_size, expected_sha256 in (
        (
            "raw calibration source evidence",
            calibration.source_evidence_path,
            calibration.source_evidence_size_bytes,
            calibration.source_evidence_sha256,
        ),
        (
            "held-out split manifest",
            calibration.held_out_split_manifest_path,
            calibration.held_out_split_manifest_size_bytes,
            calibration.held_out_split_manifest_sha256,
        ),
    ):
        _verify_relative_regular_file(
            selection_directory,
            path=artifact_path,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            label=label,
        )
    _verify_calibration_report_semantics(
        selection_directory,
        selection=selection,
        report_bytes=report_bytes,
    )


def _read_selection_file(path: Path) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("selection path is not a regular file")
        return _read_all(descriptor)
    finally:
        os.close(descriptor)


def _verify_relative_regular_file(
    root: Path,
    *,
    path: str,
    expected_size: int,
    expected_sha256: str,
    label: str,
) -> bytes:
    _require_relative_artifact_path(path, f"{label} path")
    parts = PurePosixPath(path).parts
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
    file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptors: list[int] = []
    try:
        current = os.open(root.resolve(strict=True), directory_flags)
        descriptors.append(current)
        for component in parts[:-1]:
            current = os.open(component, directory_flags, dir_fd=current)
            descriptors.append(current)
        file_descriptor = os.open(parts[-1], file_flags, dir_fd=current)
        descriptors.append(file_descriptor)
        metadata = os.fstat(file_descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{label} {path!r} is not a regular file")
        if metadata.st_size != expected_size:
            raise ValueError(
                f"{label} {path!r} size mismatch: expected {expected_size}, "
                f"observed {metadata.st_size}"
            )
        contents = _read_all(file_descriptor)
        actual_sha256 = hashlib.sha256(contents).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"{label} {path!r} SHA-256 mismatch: expected {expected_sha256}, "
                f"observed {actual_sha256}"
            )
        return contents
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _verify_calibration_report_semantics(
    selection_directory: Path,
    *,
    selection: AIConfiguratorProfileSelection,
    report_bytes: bytes,
) -> None:
    calibration = selection.calibration
    if calibration is None:
        raise ValueError("formal selection calibration is missing")
    report = _canonical_json_object(report_bytes, "held-out residual report")
    _require_exact_keys(
        report,
        {
            "schema",
            "profile_fingerprint",
            "source_evidence_sha256",
            "held_out_split_manifest_sha256",
            "calibration_method",
            "shape_axes",
            "threshold_declaration",
            "phase_results",
            "formal_use_allowed",
        },
        "held-out residual report",
    )
    expected_identity: dict[str, object] = {
        "schema": RESIDUAL_REPORT_SCHEMA,
        "profile_fingerprint": selection.profile.fingerprint,
        "source_evidence_sha256": calibration.source_evidence_sha256,
        "held_out_split_manifest_sha256": (
            calibration.held_out_split_manifest_sha256
        ),
        "calibration_method": CALIBRATION_METHOD,
        "shape_axes": list(REQUIRED_SHAPE_AXES),
        "formal_use_allowed": True,
    }
    for key, expected in expected_identity.items():
        if report[key] != expected:
            raise ValueError(
                f"held-out residual report {key} mismatch: expected {expected!r}"
            )

    declaration = _mapping(
        report["threshold_declaration"],
        "held-out residual report.threshold_declaration",
    )
    _require_exact_keys(
        declaration,
        {"path", "sha256", "size_bytes"},
        "held-out residual report.threshold_declaration",
    )
    declaration_path = _string(
        declaration["path"], "held-out residual report.threshold_declaration.path"
    )
    declaration_sha256 = _string(
        declaration["sha256"],
        "held-out residual report.threshold_declaration.sha256",
    )
    declaration_size = _integer(
        declaration["size_bytes"],
        "held-out residual report.threshold_declaration.size_bytes",
    )
    _require_relative_artifact_path(declaration_path, "threshold declaration path")
    _require_sha256(declaration_sha256, "threshold declaration sha256")
    _require_positive_int(declaration_size, "threshold declaration size_bytes")
    declaration_bytes = _verify_relative_regular_file(
        selection_directory,
        path=declaration_path,
        expected_size=declaration_size,
        expected_sha256=declaration_sha256,
        label="predeclared residual thresholds",
    )
    thresholds = _verify_threshold_declaration(
        declaration_bytes,
        profile_fingerprint=selection.profile.fingerprint,
    )

    phase_results = _mapping(
        report["phase_results"], "held-out residual report.phase_results"
    )
    phase_keys = {phase.value for phase in PredictionPhase}
    _require_exact_keys(
        phase_results, phase_keys, "held-out residual report.phase_results"
    )
    expected_counts = {
        PredictionPhase.PREFILL.value: (
            calibration.prefill_sample_count,
            calibration.prefill_residual_bucket_count,
        ),
        PredictionPhase.DECODE.value: (
            calibration.decode_sample_count,
            calibration.decode_residual_bucket_count,
        ),
    }
    for phase_name in sorted(phase_keys):
        phase_result = _mapping(
            phase_results[phase_name],
            f"held-out residual report.phase_results.{phase_name}",
        )
        _require_exact_keys(
            phase_result,
            {
                "sample_count",
                "residual_bucket_count",
                "mean_absolute_percentage_error",
                "p95_absolute_relative_error",
                "passed",
            },
            f"held-out residual report.phase_results.{phase_name}",
        )
        sample_count = _integer(
            phase_result["sample_count"],
            f"held-out residual report.phase_results.{phase_name}.sample_count",
        )
        bucket_count = _integer(
            phase_result["residual_bucket_count"],
            f"held-out residual report.phase_results.{phase_name}.residual_bucket_count",
        )
        if (sample_count, bucket_count) != expected_counts[phase_name]:
            raise ValueError(
                f"held-out residual report {phase_name} counts do not match selection"
            )
        mape = _nonnegative_finite_number(
            phase_result["mean_absolute_percentage_error"],
            f"held-out residual report.phase_results.{phase_name}."
            "mean_absolute_percentage_error",
        )
        p95 = _nonnegative_finite_number(
            phase_result["p95_absolute_relative_error"],
            f"held-out residual report.phase_results.{phase_name}."
            "p95_absolute_relative_error",
        )
        passed = _boolean(
            phase_result["passed"],
            f"held-out residual report.phase_results.{phase_name}.passed",
        )
        phase_thresholds = thresholds[phase_name]
        recomputed_pass = (
            mape <= phase_thresholds["max_mean_absolute_percentage_error"]
            and p95 <= phase_thresholds["max_p95_absolute_relative_error"]
        )
        if passed != recomputed_pass:
            raise ValueError(
                f"held-out residual report {phase_name} passed flag does not match "
                "the predeclared thresholds"
            )
        if not passed:
            raise ValueError(
                f"held-out residual report {phase_name} fails predeclared thresholds"
            )


def _verify_threshold_declaration(
    contents: bytes,
    *,
    profile_fingerprint: str,
) -> dict[str, dict[str, float]]:
    declaration = _canonical_json_object(contents, "predeclared residual thresholds")
    _require_exact_keys(
        declaration,
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
        "schema": RESIDUAL_THRESHOLDS_SCHEMA,
        "profile_fingerprint": profile_fingerprint,
        "calibration_method": CALIBRATION_METHOD,
        "shape_axes": list(REQUIRED_SHAPE_AXES),
    }
    for key, value in expected.items():
        if declaration[key] != value:
            raise ValueError(
                f"predeclared residual thresholds {key} mismatch: expected {value!r}"
            )
    phase_thresholds = _mapping(
        declaration["phase_thresholds"],
        "predeclared residual thresholds.phase_thresholds",
    )
    phase_keys = {phase.value for phase in PredictionPhase}
    _require_exact_keys(
        phase_thresholds,
        phase_keys,
        "predeclared residual thresholds.phase_thresholds",
    )
    result: dict[str, dict[str, float]] = {}
    for phase_name in sorted(phase_keys):
        raw = _mapping(
            phase_thresholds[phase_name],
            f"predeclared residual thresholds.phase_thresholds.{phase_name}",
        )
        _require_exact_keys(
            raw,
            {
                "max_mean_absolute_percentage_error",
                "max_p95_absolute_relative_error",
            },
            f"predeclared residual thresholds.phase_thresholds.{phase_name}",
        )
        result[phase_name] = {
            key: _nonnegative_finite_number(
                raw[key],
                f"predeclared residual thresholds.phase_thresholds.{phase_name}.{key}",
            )
            for key in (
                "max_mean_absolute_percentage_error",
                "max_p95_absolute_relative_error",
            )
        }
    return result


def _canonical_json_object(contents: bytes, label: str) -> Mapping[str, object]:
    try:
        value = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid UTF-8 JSON: {error}") from error
    result = _mapping(value, label)
    if canonical_json_bytes(result) != contents:
        raise ValueError(f"{label} is not canonical JSON")
    return result


def _read_all(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def _nonnegative_finite_number(value: object, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{location} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{location} must be finite and non-negative")
    return result


def _require_relative_artifact_path(value: object, field_name: str) -> None:
    _require_non_empty(value, field_name)
    assert isinstance(value, str)
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.as_posix() != value
    ):
        raise ValueError(
            f"{field_name} must be a canonical safe relative POSIX path"
        )


def _mapping(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{location} must be an object with string keys")
    return value


def _list(value: object, location: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{location} must be an array")
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise TypeError(f"{location} must be a non-empty string without outer whitespace")
    return value


def _optional_string(value: object, location: str) -> str | None:
    if value is None:
        return None
    return _string(value, location)


def _integer(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{location} must be an integer")
    return value


def _boolean(value: object, location: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{location} must be boolean")
    return value


def _require_exact_keys(
    value: Mapping[str, object], expected: set[str], location: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        _invalid_keys(location, missing=missing, extra=extra)


def _invalid_keys(location: str, *, missing: list[str], extra: list[str]) -> NoReturn:
    raise ValueError(f"{location} keys mismatch; missing={missing}, extra={extra}")


def selection_from_mapping(raw: Mapping[str, Any]) -> AIConfiguratorProfileSelection:
    """Public constructor for already parsed test/tooling documents."""

    return _selection_from_mapping(raw)
