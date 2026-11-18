"""Fail-closed, deterministic publication of one run's evidence bundle.

The publisher derives only configuration hashes.  Code, predictor, trace,
model/tokenizer, coverage, validation, and calibration claims are explicit
caller inputs and remain subject to their own evidence gates.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final, cast

from moonkvsim.common.hash import sha256_json
from moonkvsim.config import ResolvedConfigBundle, validate_run_manifest

_MANIFEST_NAME: Final = "manifest.json"
_RESOLVED_CONFIG_NAME: Final = "resolved-config.json"
_CHECKSUMS_NAME: Final = "SHA256SUMS"
_CORE_ARTIFACTS: Final = frozenset({_MANIFEST_NAME, _RESOLVED_CONFIG_NAME, _CHECKSUMS_NAME})
_SECTION_16_ARTIFACTS: Final = frozenset(
    {
        "event-journal.jsonl",
        "trace-audit.json",
        "context-coverage.json",
        "workflow-metrics.parquet",
        "request-metrics.parquet",
        "batch-events.parquet",
        "kv-residency-events.parquet",
        "kv-transfer-events.parquet",
        "physical-allocation-events.parquet",
        "resource-ledger-deltas.parquet",
        "resource-ledger-snapshots.parquet",
        "flow-rate-events.parquet",
        "resource-utilization.parquet",
        "store-directory-snapshots.parquet",
        "failure-events.parquet",
        "recovery-events.parquet",
        "capacity-audit.json",
        "run-audit.json",
        "summary.json",
    }
)
_REQUIRED_RUN_ARTIFACTS: Final = _CORE_ARTIFACTS | _SECTION_16_ARTIFACTS
_AT_FDCWD: Final = -100
_RENAME_NOREPLACE: Final = 1

ArtifactWriter = Callable[[Path], None]


class RunArtifactBundleError(ValueError):
    """A run bundle is incomplete, inconsistent, or unsafe to publish."""


@dataclass(frozen=True, slots=True)
class RunManifestInputs:
    """All non-configuration manifest claims, with deliberately no defaults."""

    run_id: str
    code: Mapping[str, Any]
    source_lock_sha256: str
    predictor_database_sha256: str | None
    trace: Mapping[str, Any]
    target_model: Mapping[str, Any]
    coverage: Mapping[str, Any]
    integrity: Mapping[str, Any]
    seed: int
    virtual_time: Mapping[str, Any]
    validation: Mapping[str, Any]
    result_completeness: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class PublishedRunArtifactBundle:
    """Verified identity of a published run directory."""

    directory: Path
    checksums: tuple[tuple[str, str], ...]

    def sha256_for(self, artifact_name: str) -> str:
        for name, digest in self.checksums:
            if name == artifact_name:
                return digest
        raise KeyError(artifact_name)


def build_run_manifest(
    config_bundle: ResolvedConfigBundle,
    inputs: RunManifestInputs,
) -> dict[str, Any]:
    """Build and validate a manifest without inventing provenance claims."""

    _validate_resolved_config_bundle_hashes(config_bundle)
    completeness = _json_object("result_completeness", inputs.result_completeness)
    for field in ("expected_artifacts", "present_artifacts", "missing_artifacts"):
        value = completeness.get(field)
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            completeness[field] = sorted(value)

    manifest: dict[str, Any] = {
        "schema": "moonkvsim.run_manifest.v1",
        "run_id": inputs.run_id,
        "config_hashes": {
            "requests": config_bundle.requests_sha256,
            "failure": config_bundle.failure_sha256,
            "deployment": config_bundle.deployment_sha256,
            "resolved_config": config_bundle.sha256,
        },
        "code": _json_object("code", inputs.code),
        "source_lock_sha256": inputs.source_lock_sha256,
        "predictor_database_sha256": inputs.predictor_database_sha256,
        "trace": _json_object("trace", inputs.trace),
        "target_model": _json_object("target_model", inputs.target_model),
        "coverage": _json_object("coverage", inputs.coverage),
        "integrity": _json_object("integrity", inputs.integrity),
        "seed": inputs.seed,
        "virtual_time": _json_object("virtual_time", inputs.virtual_time),
        "validation": _json_object("validation", inputs.validation),
        "result_completeness": completeness,
    }
    validate_run_manifest(manifest)
    errors = _manifest_binding_errors(manifest, config_bundle)
    errors.extend(_completeness_errors(manifest))
    if errors:
        raise RunArtifactBundleError("run manifest integrity failed: " + "; ".join(errors))
    return manifest


def publish_run_artifact_bundle(
    run_directory: Path,
    *,
    config_bundle: ResolvedConfigBundle,
    manifest_inputs: RunManifestInputs,
    artifact_writer: ArtifactWriter | None = None,
) -> PublishedRunArtifactBundle:
    """Stage, verify, and atomically publish a never-clobbered run directory.

    ``artifact_writer`` receives an empty private staging directory and may use
    the canonical output writers to add section-16 artifacts.  It must not
    create the three publisher-owned core artifacts.  The manifest's
    ``present_artifacts`` list must exactly name everything it creates plus the
    core artifacts.
    """

    destination = Path(run_directory)
    if destination.name in {"", ".", ".."}:
        raise RunArtifactBundleError("run directory must name one concrete directory")
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.is_dir() or parent.is_symlink():
        raise RunArtifactBundleError("run directory parent must be a real directory")
    if os.path.lexists(destination):
        raise FileExistsError(
            errno.EEXIST,
            "refusing to overwrite existing run artifact bundle",
            destination,
        )

    staging = Path(
        tempfile.mkdtemp(
            dir=parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
    )
    published = False
    try:
        if artifact_writer is not None:
            artifact_writer(staging)
        writer_files = set(_scan_regular_files(staging))
        reserved = sorted(writer_files & _CORE_ARTIFACTS)
        if reserved:
            raise RunArtifactBundleError(
                "artifact writer created publisher-owned files: " + ", ".join(reserved)
            )

        manifest = build_run_manifest(config_bundle, manifest_inputs)
        declared_present = set(
            cast(list[str], manifest["result_completeness"]["present_artifacts"])
        )
        expected_writer_files = declared_present - _CORE_ARTIFACTS
        if writer_files != expected_writer_files:
            raise RunArtifactBundleError(
                _set_mismatch_message(
                    "artifact writer output does not match present_artifacts",
                    expected_writer_files,
                    writer_files,
                )
            )

        config_bundle.write(staging / _RESOLVED_CONFIG_NAME)
        _write_exclusive(staging / _MANIFEST_NAME, _canonical_json_bytes(manifest))
        checksums = _calculate_checksums(staging)
        _write_exclusive(staging / _CHECKSUMS_NAME, _checksum_file_bytes(checksums))

        verified = verify_run_artifact_bundle(staging, config_bundle=config_bundle)
        _fsync_tree(staging)
        _atomic_rename_no_replace(staging, destination)
        published = True
        _fsync_directory(parent)
        return PublishedRunArtifactBundle(destination, verified.checksums)
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)


def verify_run_artifact_bundle(
    run_directory: Path,
    *,
    config_bundle: ResolvedConfigBundle,
) -> PublishedRunArtifactBundle:
    """Re-hash and cross-check every declared artifact in a run directory."""

    directory = Path(run_directory)
    if directory.is_symlink() or not directory.is_dir():
        raise RunArtifactBundleError("run artifact bundle must be a real directory")
    actual_files = set(_scan_regular_files(directory))
    missing_core = sorted(_CORE_ARTIFACTS - actual_files)
    if missing_core:
        raise RunArtifactBundleError(
            "run artifact bundle is missing core files: " + ", ".join(missing_core)
        )

    manifest = _load_canonical_json_object(directory / _MANIFEST_NAME)
    validate_run_manifest(manifest)
    _validate_resolved_config_bundle_hashes(config_bundle)
    if _read_regular_file(directory / _RESOLVED_CONFIG_NAME) != config_bundle.to_json_bytes():
        raise RunArtifactBundleError(
            "resolved-config.json is not byte-identical to the supplied resolved bundle"
        )

    errors = _manifest_binding_errors(manifest, config_bundle)
    errors.extend(_completeness_errors(manifest))
    declared_present = set(cast(list[str], manifest["result_completeness"]["present_artifacts"]))
    if declared_present != actual_files:
        errors.append(
            _set_mismatch_message(
                "present_artifacts does not match directory files",
                declared_present,
                actual_files,
            )
        )

    recorded = _read_checksum_file(directory / _CHECKSUMS_NAME)
    recorded_names = {name for name, _digest in recorded}
    checksum_expected = actual_files - {_CHECKSUMS_NAME}
    if recorded_names != checksum_expected:
        errors.append(
            _set_mismatch_message(
                "SHA256SUMS entries do not match bundle files",
                checksum_expected,
                recorded_names,
            )
        )
    for name, expected_digest in recorded:
        actual_digest = _sha256_file(directory / name)
        if actual_digest != expected_digest:
            errors.append(
                f"SHA256 mismatch for {name}: expected {expected_digest}, got {actual_digest}"
            )
    if errors:
        raise RunArtifactBundleError(
            "run artifact bundle verification failed: " + "; ".join(errors)
        )
    return PublishedRunArtifactBundle(directory, recorded)


def _validate_resolved_config_bundle_hashes(bundle: ResolvedConfigBundle) -> None:
    hashes = (
        ("requests", bundle.requests, bundle.requests_sha256),
        ("failure", bundle.failure, bundle.failure_sha256),
        ("deployment", bundle.deployment, bundle.deployment_sha256),
    )
    errors = [
        f"resolved configuration {name} hash does not match its document"
        for name, document, expected in hashes
        if sha256_json(document) != expected
    ]
    if errors:
        raise RunArtifactBundleError("; ".join(errors))


def _manifest_binding_errors(
    manifest: Mapping[str, Any], bundle: ResolvedConfigBundle
) -> list[str]:
    errors: list[str] = []
    expected_config_hashes = {
        "requests": bundle.requests_sha256,
        "failure": bundle.failure_sha256,
        "deployment": bundle.deployment_sha256,
        "resolved_config": bundle.sha256,
    }
    if manifest.get("config_hashes") != expected_config_hashes:
        errors.append("config_hashes do not match the supplied resolved configuration")

    code = cast(Mapping[str, Any], manifest["code"])
    if set(code) != {"commit", "dirty", "dirty_patch_sha256"}:
        errors.append("code must explicitly provide commit, dirty, and dirty_patch_sha256")
    elif code["dirty"] is True and code["dirty_patch_sha256"] is None:
        errors.append("dirty code requires an explicit dirty_patch_sha256")
    elif code["dirty"] is False and code["dirty_patch_sha256"] is not None:
        errors.append("clean code must set dirty_patch_sha256 to null")

    requests = bundle.requests
    deployment = bundle.deployment
    workload = _nested_mapping(requests, "workload", errors)
    request_provenance = _nested_mapping(workload, "provenance", errors)
    token_count = _nested_mapping(requests, "trace_token_count", errors)
    request_model = _nested_mapping(requests, "target_model_tokenizer", errors)
    context = _nested_mapping(requests, "context", errors)
    deployment_model = _nested_mapping(deployment, "model", errors)
    deployment_predictor = _nested_mapping(deployment, "predictor", errors)
    trace = cast(Mapping[str, Any], manifest["trace"])
    trace_provenance = cast(Mapping[str, Any], trace["provenance"])
    target_model = cast(Mapping[str, Any], manifest["target_model"])

    comparisons = (
        ("seed", manifest["seed"], requests.get("seed")),
        ("trace.dataset", trace["dataset"], workload.get("dataset")),
        (
            "trace.workload_trace_sha256",
            trace["workload_trace_sha256"],
            workload.get("trace_sha256"),
        ),
        (
            "trace.provenance.license",
            trace_provenance["license"],
            request_provenance.get("license"),
        ),
        (
            "trace.provenance.access_level",
            trace_provenance["access_level"],
            request_provenance.get("access_level"),
        ),
        (
            "trace.provenance.collection_interval",
            trace_provenance["collection_interval"],
            request_provenance.get("collection_interval"),
        ),
        (
            "trace.provenance.content_availability",
            trace_provenance["content_availability"],
            request_provenance.get("content_availability"),
        ),
        (
            "trace.provenance.token_count_mode",
            trace_provenance["token_count_mode"],
            token_count.get("mode"),
        ),
        ("target_model.model_id", target_model["model_id"], request_model.get("model_id")),
        (
            "target_model.model_revision",
            target_model["model_revision"],
            request_model.get("revision"),
        ),
        (
            "target_model.model_config_sha256",
            target_model["model_config_sha256"],
            deployment_model.get("config_sha256"),
        ),
        (
            "target_model.tokenizer_config_sha256",
            target_model["tokenizer_config_sha256"],
            request_model.get("tokenizer_config_sha256"),
        ),
        (
            "target_model.chat_template_sha256",
            target_model["chat_template_sha256"],
            request_model.get("chat_template_sha256"),
        ),
        (
            "predictor_database_sha256",
            manifest["predictor_database_sha256"],
            deployment_predictor.get("database_sha256"),
        ),
    )
    for label, actual, expected in comparisons:
        if actual != expected:
            errors.append(f"{label} does not match resolved configuration")

    coverage = cast(Mapping[str, Any], manifest["coverage"])
    bucket_upper_bounds = [
        bucket["upper_inclusive"]
        for bucket in cast(Sequence[Mapping[str, Any]], coverage["context_buckets"])
    ]
    if bucket_upper_bounds != context.get("required_observed_context_buckets"):
        errors.append("coverage.context_buckets do not match required observed buckets")

    validation = cast(Mapping[str, Any], manifest["validation"])
    if validation["evidence_class"] in {"E3", "E4", "E5"}:
        if validation["calibration_status"] != "pass":
            errors.append("E3+ evidence requires explicit calibration_status=pass")
        if manifest["predictor_database_sha256"] is None:
            errors.append("E3+ evidence requires a concrete predictor database SHA-256")
    if validation["evidence_class"] == "E5":
        collection_interval = trace_provenance.get("collection_interval")
        if not isinstance(collection_interval, str) or not collection_interval:
            errors.append("E5 evidence requires a non-empty trace collection interval")
        if code.get("dirty") is not False:
            errors.append("E5 evidence requires a clean code commit")
        completeness = cast(Mapping[str, Any], manifest["result_completeness"])
        if completeness.get("status") != "complete":
            errors.append("E5 evidence requires a complete result artifact matrix")
        buckets = cast(Sequence[Mapping[str, Any]], coverage["context_buckets"])
        if any(
            bucket.get("request_count", 0) <= 0
            or bucket.get("workflow_count", 0) <= 0
            for bucket in buckets
        ):
            errors.append(
                "E5 evidence requires observed requests/workflows in every context bucket"
            )
        if coverage.get("sample_count") != sum(
            cast(int, bucket["request_count"]) for bucket in buckets
        ):
            errors.append("E5 evidence requires sample_count to equal context-bucket requests")
        network = deployment.get("network")
        registration = (
            network.get("registration") if isinstance(network, Mapping) else None
        )
        if not isinstance(registration, Mapping) or registration.get("mode") != "calibrated":
            errors.append("E5 evidence requires calibrated registration timing")
        nonformal_sources = _find_nonformal_parameter_sources(deployment)
        if nonformal_sources:
            errors.append(
                "E5 evidence forbids assumed/sensitivity-only deployment parameters: "
                + ", ".join(nonformal_sources)
            )
    return errors


def _find_nonformal_parameter_sources(
    value: object,
    *,
    path: str = "deployment",
) -> list[str]:
    """Locate explicit parameter sources that cannot enter formal E5 cells."""

    result: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == "source" and child in {"assumed", "sensitivity_only"}:
                result.append(child_path)
            result.extend(_find_nonformal_parameter_sources(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(
                _find_nonformal_parameter_sources(child, path=f"{path}[{index}]")
            )
    return result


def _completeness_errors(manifest: Mapping[str, Any]) -> list[str]:
    completeness = cast(Mapping[str, Any], manifest["result_completeness"])
    status = cast(str, completeness["status"])
    expected = cast(list[str], completeness["expected_artifacts"])
    present = cast(list[str], completeness["present_artifacts"])
    missing = cast(list[str], completeness["missing_artifacts"])
    errors: list[str] = []
    for label, names in (
        ("expected_artifacts", expected),
        ("present_artifacts", present),
        ("missing_artifacts", missing),
    ):
        if names != sorted(names):
            errors.append(f"{label} must be sorted")
        for name in names:
            try:
                _validate_artifact_name(name)
            except RunArtifactBundleError as error:
                errors.append(f"{label}: {error}")
    expected_set = set(expected)
    present_set = set(present)
    missing_set = set(missing)
    if present_set & missing_set:
        errors.append("present_artifacts and missing_artifacts must be disjoint")
    if expected_set != present_set | missing_set:
        errors.append("expected_artifacts must equal present_artifacts plus missing_artifacts")
    if not present_set >= _CORE_ARTIFACTS:
        errors.append("all three core artifact names must be present")
    omitted_required = sorted(_REQUIRED_RUN_ARTIFACTS - expected_set)
    if omitted_required:
        errors.append(
            "expected_artifacts omits mandatory section-16 artifacts: "
            + ", ".join(omitted_required)
        )
    if status == "complete" and missing_set:
        errors.append("result status complete requires missing_artifacts to be empty")
    if status == "incomplete" and not missing_set:
        errors.append("result status incomplete requires at least one missing artifact")
    return errors


def _nested_mapping(parent: Mapping[str, Any], key: str, errors: list[str]) -> Mapping[str, Any]:
    value = parent.get(key)
    if isinstance(value, Mapping):
        return value
    errors.append(f"resolved configuration is missing object {key}")
    return {}


def _json_object(label: str, value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        cloned = json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as error:
        raise RunArtifactBundleError(f"{label} must be finite JSON") from error
    if not isinstance(cloned, dict):
        raise RunArtifactBundleError(f"{label} must be a JSON object")
    return cast(dict[str, Any], cloned)


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as error:
        raise RunArtifactBundleError("manifest must be finite JSON") from error
    return encoded + b"\n"


def _load_canonical_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = _read_regular_file(path)
        value = json.loads(payload)
    except (OSError, json.JSONDecodeError) as error:
        raise RunArtifactBundleError(f"cannot read JSON artifact {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise RunArtifactBundleError(f"{path.name} must contain one JSON object")
    result = cast(dict[str, Any], value)
    if payload != _canonical_json_bytes(result):
        raise RunArtifactBundleError(f"{path.name} is not canonical JSON with one final newline")
    return result


def _validate_artifact_name(name: str) -> None:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or path.as_posix() != name
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in name
        or "\n" in name
        or "\r" in name
    ):
        raise RunArtifactBundleError(f"invalid canonical relative artifact name {name!r}")


def _scan_regular_files(directory: Path) -> tuple[str, ...]:
    names: list[str] = []
    directory_names: list[str] = []
    for root_text, directories, files in os.walk(directory, followlinks=False):
        root = Path(root_text)
        for child_name in directories:
            child = root / child_name
            mode = child.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise RunArtifactBundleError(f"non-directory artifact path is forbidden: {child}")
            relative_name = child.relative_to(directory).as_posix()
            _validate_artifact_name(relative_name)
            directory_names.append(relative_name)
        for child_name in files:
            child = root / child_name
            mode = child.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise RunArtifactBundleError(f"non-regular artifact is forbidden: {child}")
            name = child.relative_to(directory).as_posix()
            _validate_artifact_name(name)
            names.append(name)
    names.sort()
    required_directories: set[str] = set()
    for name in names:
        parent = PurePosixPath(name).parent
        while parent != PurePosixPath("."):
            required_directories.add(parent.as_posix())
            parent = parent.parent
    undeclared_empty_directories = sorted(set(directory_names) - required_directories)
    if undeclared_empty_directories:
        raise RunArtifactBundleError(
            "empty artifact directories are forbidden: " + ", ".join(undeclared_empty_directories)
        )
    return tuple(names)


def _write_exclusive(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = _open_regular_file_no_follow(path)
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    except OSError as error:
        raise RunArtifactBundleError(f"cannot hash artifact {path}: {error}") from error
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _calculate_checksums(directory: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (name, _sha256_file(directory / name))
        for name in _scan_regular_files(directory)
        if name != _CHECKSUMS_NAME
    )


def _checksum_file_bytes(checksums: Sequence[tuple[str, str]]) -> bytes:
    return "".join(f"{digest}  {name}\n" for name, digest in checksums).encode()


def _read_checksum_file(path: Path) -> tuple[tuple[str, str], ...]:
    try:
        payload = _read_regular_file(path)
    except OSError as error:
        raise RunArtifactBundleError(f"cannot read SHA256SUMS: {error}") from error
    if not payload or not payload.endswith(b"\n"):
        raise RunArtifactBundleError("SHA256SUMS must be non-empty and end with one newline")
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise RunArtifactBundleError("SHA256SUMS must be UTF-8") from error
    result: list[tuple[str, str]] = []
    for line_number, line in enumerate(lines, start=1):
        digest, separator, name = line.partition("  ")
        if (
            separator != "  "
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise RunArtifactBundleError(
                f"SHA256SUMS line {line_number} is not strict sha256sum format"
            )
        _validate_artifact_name(name)
        if name == _CHECKSUMS_NAME:
            raise RunArtifactBundleError("SHA256SUMS must not contain a self-hash")
        result.append((name, digest))
    names = [name for name, _digest in result]
    if names != sorted(names) or len(names) != len(set(names)):
        raise RunArtifactBundleError("SHA256SUMS names must be unique and sorted")
    if payload != _checksum_file_bytes(result):
        raise RunArtifactBundleError("SHA256SUMS is not canonically encoded")
    return tuple(result)


def _set_mismatch_message(label: str, expected: set[str], actual: set[str]) -> str:
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    return f"{label}: missing={missing}, unexpected={unexpected}"


def _read_regular_file(path: Path) -> bytes:
    descriptor = _open_regular_file_no_follow(path)
    chunks: list[bytes] = []
    try:
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
    except OSError as error:
        raise RunArtifactBundleError(f"cannot read regular artifact {path}: {error}") from error
    finally:
        os.close(descriptor)
    return b"".join(chunks)


def _open_regular_file_no_follow(path: Path) -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise RunArtifactBundleError("symlink-safe artifact verification requires O_NOFOLLOW")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RunArtifactBundleError(
            f"cannot open regular artifact without following symlinks {path}: {error}"
        ) from error
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise RunArtifactBundleError(f"artifact is not a regular file: {path}")
    return descriptor


def _fsync_tree(directory: Path) -> None:
    for name in _scan_regular_files(directory):
        descriptor = _open_regular_file_no_follow(directory / name)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    directories = [directory]
    directories.extend(path for path in directory.rglob("*") if path.is_dir())
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        _fsync_directory(path)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_rename_no_replace(source: Path, destination: Path) -> None:
    """Use Linux renameat2 and fail closed if no atomic no-replace exists."""

    error_number = _renameat2_no_replace_errno(source, destination)
    if error_number == 0:
        return
    if error_number == errno.EEXIST:
        raise FileExistsError(
            error_number,
            "refusing to overwrite existing run artifact bundle",
            destination,
        )
    unsupported = {errno.EINVAL, errno.ENOSYS}
    if hasattr(errno, "EOPNOTSUPP"):
        unsupported.add(errno.EOPNOTSUPP)
    if error_number in unsupported:
        raise RunArtifactBundleError(
            "filesystem does not support atomic no-clobber directory publication "
            f"with renameat2(RENAME_NOREPLACE): errno={error_number}"
        )
    raise OSError(error_number, os.strerror(error_number), destination)


def _renameat2_no_replace_errno(source: Path, destination: Path) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as error:
        raise RunArtifactBundleError(
            "atomic no-clobber publication requires Linux renameat2"
        ) from error
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return 0
    return ctypes.get_errno()
