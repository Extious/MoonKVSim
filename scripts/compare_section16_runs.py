#!/usr/bin/env python3
"""Fail-closed validation and comparison of two Section 16 run directories.

The comparison proves that two *distinct directories* contain valid frozen
PASS bundles whose 19 artifacts are byte-identical. Filesystem inspection
cannot prove that the directories came from independent executions (rather
than, for example, an ordinary byte-for-byte copy), so the PASS report states
that limitation explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

from moonkvsim.common.hash import canonical_json_bytes
from moonkvsim.output.section16 import (
    MAX_MODEL_LEN_TOKENS,
    PARQUET_SCHEMAS,
    SECTION_16_ARTIFACTS,
    SECTION_16_PARQUET_ARTIFACTS,
    SECTION_16_SCHEMA_VERSION,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40,64}$")
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_SEMANTIC_SNAPSHOT_SCHEMA = "moonkvsim.semantic-source-snapshot.v1"
_SEMANTIC_PROVENANCE_SCHEMA = "moonkvsim.semantic-source-run-provenance.v1"
_PARQUET_METADATA = {
    b"moonkvsim.output_contract": SECTION_16_SCHEMA_VERSION.encode(),
    b"moonkvsim.truth_source": b"canonical-projection-only",
}
_SELECTION_POLICY_KEYS = frozenset(
    {
        "python",
        "cli",
        "schemas",
        "config",
        "layout",
        "dependencies",
        "bytecode_and_caches_included",
    }
)
_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
_DIRECTORY_FLAGS = _OPEN_FLAGS | getattr(os, "O_DIRECTORY", 0)


class ComparisonError(RuntimeError):
    """A run directory cannot satisfy the deterministic replay contract."""


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ComparisonError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if type(value) is not list:
        raise ComparisonError(f"{label} must be an array")
    return value


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ComparisonError(f"{label} must be a non-empty string")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ComparisonError(f"{label} must be a non-negative integer")
    return value


def _sha256_value(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ComparisonError(f"{label} must be a lowercase SHA-256")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str] | frozenset[str],
    label: str,
) -> None:
    observed = set(value)
    if observed != set(expected):
        raise ComparisonError(
            f"{label} keys differ: missing={sorted(set(expected) - observed)}, "
            f"extra={sorted(observed - set(expected))}"
        )


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def _parse_json_bytes(raw: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ComparisonError(f"cannot parse {label}: {error}") from error
    document = _mapping(value, label)
    try:
        canonical = canonical_json_bytes(document) + b"\n"
    except (TypeError, ValueError) as error:
        raise ComparisonError(f"cannot canonicalize {label}: {error}") from error
    if raw != canonical:
        raise ComparisonError(f"{label} is not canonical JSON with one final newline")
    return document


def _stat_signature(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _open_regular_at(directory_fd: int, name: str, run_label: str) -> tuple[int, os.stat_result]:
    if not name or "/" in name or name in {".", ".."}:
        raise ComparisonError(f"invalid artifact basename: {name!r}")
    try:
        descriptor = os.open(name, _OPEN_FLAGS, dir_fd=directory_fd)
    except OSError as error:
        raise ComparisonError(
            f"cannot securely open regular non-symlink artifact {run_label}/{name}: {error}"
        ) from error
    try:
        initial = os.fstat(descriptor)
        if not stat.S_ISREG(initial.st_mode):
            raise ComparisonError(
                f"artifact must be a regular non-symlink file: {run_label}/{name}"
            )
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, initial


def _read_all(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _sha256_fd(descriptor: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def _assert_fd_unchanged(
    descriptor: int,
    initial: os.stat_result,
    label: str,
) -> None:
    if _stat_signature(os.fstat(descriptor)) != _stat_signature(initial):
        raise ComparisonError(f"{label} changed while it was being validated")


def _load_pyarrow() -> tuple[ModuleType, ModuleType]:
    try:
        pyarrow = importlib.import_module("pyarrow")
        parquet = importlib.import_module("pyarrow.parquet")
    except ModuleNotFoundError as error:
        raise ComparisonError("validating genuine Section 16 Parquet requires pyarrow") from error
    return pyarrow, parquet


def _expected_arrow_type(pyarrow: ModuleType, type_name: str) -> object:
    factories = {
        "int64": pyarrow.int64,
        "float64": pyarrow.float64,
        "string": pyarrow.string,
        "bool": pyarrow.bool_,
        "list_string": lambda: pyarrow.list_(pyarrow.string()),
    }
    try:
        return factories[type_name]()
    except KeyError as error:
        raise ComparisonError(f"unsupported fixed Parquet type {type_name!r}") from error


def _inspect_parquet_fd(
    descriptor: int,
    initial: os.stat_result,
    name: str,
    label: str,
    *,
    pyarrow: ModuleType,
    parquet: ModuleType,
) -> tuple[str, int, dict[str, object]]:
    digest = _sha256_fd(descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)
    duplicate = os.dup(descriptor)
    declared_rows = -1
    resource_ids: set[str] = set()
    try:
        with os.fdopen(duplicate, "rb", closefd=True) as stream:
            duplicate = -1
            try:
                parquet_file = parquet.ParquetFile(stream)
                schema = parquet_file.schema_arrow
                metadata = schema.metadata or {}
                required_metadata = {
                    **_PARQUET_METADATA,
                    b"moonkvsim.artifact": name.encode(),
                }
                for key, expected_value in required_metadata.items():
                    if metadata.get(key) != expected_value:
                        raise ComparisonError(
                            f"{label} has invalid Parquet metadata {key.decode()}"
                        )
                expected_columns = PARQUET_SCHEMAS[name]
                if len(schema) != len(expected_columns):
                    raise ComparisonError(f"{label} has the wrong Parquet field count")
                for index, expected in enumerate(expected_columns):
                    field = schema.field(index)
                    if field.name != expected.name:
                        raise ComparisonError(
                            f"{label} field {index} name differs: "
                            f"expected={expected.name}, observed={field.name}"
                        )
                    expected_type = _expected_arrow_type(pyarrow, expected.type_name)
                    if field.type != expected_type:
                        raise ComparisonError(
                            f"{label} field {expected.name} type differs: "
                            f"expected={expected_type}, observed={field.type}"
                        )
                    if field.nullable is not expected.nullable:
                        raise ComparisonError(f"{label} field {expected.name} nullability differs")
                file_metadata = parquet_file.metadata
                if file_metadata is None:
                    raise ComparisonError(f"{label} has no Parquet file metadata")
                declared_rows = file_metadata.num_rows
                observed_rows = 0
                for batch in parquet_file.iter_batches(batch_size=65_536):
                    observed_rows += batch.num_rows
                    for index, expected in enumerate(expected_columns):
                        if not expected.nullable and batch.column(index).null_count:
                            raise ComparisonError(
                                f"{label} contains nulls in non-nullable {expected.name}"
                            )
                    _validate_parquet_content(
                        name,
                        batch,
                        label,
                        resource_ids=resource_ids,
                    )
                if observed_rows != declared_rows:
                    raise ComparisonError(
                        f"{label} Parquet row count is unreadable or inconsistent: "
                        f"metadata={declared_rows}, decoded={observed_rows}"
                    )
            except ComparisonError:
                raise
            except Exception as error:
                raise ComparisonError(
                    f"cannot validate genuine Parquet {label}: {error}"
                ) from error
    finally:
        if duplicate >= 0:
            os.close(duplicate)
    _assert_fd_unchanged(descriptor, initial, label)
    return digest, declared_rows, {"resource_ids": sorted(resource_ids)}


def _validate_parquet_content(
    name: str,
    batch: Any,
    label: str,
    *,
    resource_ids: set[str],
) -> None:
    """Validate completeness claims against decoded rows, not JSON summaries."""

    def values(column: str) -> list[Any]:
        index = batch.schema.get_field_index(column)
        if index < 0:
            raise ComparisonError(f"{label} omits required content column {column}")
        return list(batch.column(index).to_pylist())

    if name == "resource-ledger-snapshots.parquet":
        observed_ids = values("resource_id")
        complete = values("snapshot_complete")
        unknown = values("unknown_account_bytes")
        known = values("known_account_bytes")
        capacity = values("capacity_bytes")
        for row_index, resource_id in enumerate(observed_ids):
            if not isinstance(resource_id, str) or not resource_id:
                raise ComparisonError(f"{label} row {row_index} has an invalid resource_id")
            resource_ids.add(resource_id)
            if complete[row_index] is not True or unknown[row_index] != 0:
                raise ComparisonError(
                    f"{label} row {row_index} contains an incomplete capacity snapshot"
                )
            if known[row_index] != capacity[row_index]:
                raise ComparisonError(
                    f"{label} row {row_index} complete snapshot does not cover capacity"
                )
    elif name == "request-metrics.parquet":
        timing_complete = values("timing_complete")
        ttft_complete = values("ttft_complete")
        tpot_complete = values("tpot_complete")
        e2e_complete = values("e2e_complete")
        missing_evidence = values("missing_evidence")
        observed_api_time = values("observed_api_time_used_as_simulated_time")
        for row_index in range(batch.num_rows):
            if (
                timing_complete[row_index] is not True
                or ttft_complete[row_index] is not True
                or tpot_complete[row_index] is not True
                or e2e_complete[row_index] is not True
                or missing_evidence[row_index] != []
            ):
                raise ComparisonError(
                    f"{label} row {row_index} contains incomplete request timing"
                )
            if observed_api_time[row_index] is not False:
                raise ComparisonError(
                    f"{label} row {row_index} uses observed API time as simulated time"
                )
    elif name == "workflow-metrics.parquet":
        timing_complete = values("timing_complete")
        ttft_complete = values("ttft_complete")
        tpot_complete = values("tpot_complete")
        wct_complete = values("wct_complete")
        missing_evidence = values("missing_evidence")
        observed_api_time = values("observed_api_time_used_as_simulated_time")
        for row_index in range(batch.num_rows):
            if (
                timing_complete[row_index] is not True
                or ttft_complete[row_index] is not True
                or tpot_complete[row_index] is not True
                or wct_complete[row_index] is not True
                or missing_evidence[row_index] != []
            ):
                raise ComparisonError(
                    f"{label} row {row_index} contains incomplete workflow timing"
                )
            if observed_api_time[row_index] is not False:
                raise ComparisonError(
                    f"{label} row {row_index} uses observed API time as simulated time"
                )


def _inspect_journal_fd(
    descriptor: int,
    initial: os.stat_result,
    label: str,
) -> tuple[str, int]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    duplicate = os.dup(descriptor)
    digest = hashlib.sha256()
    count = 0
    previous_timestamp = 0
    try:
        with os.fdopen(duplicate, "rb", closefd=True) as stream:
            duplicate = -1
            for raw_line in stream:
                digest.update(raw_line)
                if not raw_line.endswith(b"\n") or raw_line == b"\n":
                    raise ComparisonError(
                        f"{label} must contain non-empty canonical JSON lines with final newlines"
                    )
                payload = raw_line[:-1]
                try:
                    value = json.loads(
                        payload.decode("utf-8"), parse_constant=_reject_json_constant
                    )
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                    raise ComparisonError(
                        f"cannot parse {label} line {count + 1}: {error}"
                    ) from error
                record = _mapping(value, f"{label} line {count + 1}")
                if canonical_json_bytes(record) != payload:
                    raise ComparisonError(f"{label} line {count + 1} is not canonical JSON")
                _require_exact_keys(
                    record,
                    {"timestamp_ns", "journal_sequence", "record_type", "data"},
                    f"{label} line {count + 1}",
                )
                timestamp = _nonnegative_int(
                    record.get("timestamp_ns"), f"{label} line {count + 1}.timestamp_ns"
                )
                sequence = _nonnegative_int(
                    record.get("journal_sequence"),
                    f"{label} line {count + 1}.journal_sequence",
                )
                if sequence != count:
                    raise ComparisonError(f"{label} journal_sequence is not contiguous from zero")
                if timestamp < previous_timestamp:
                    raise ComparisonError(f"{label} timestamps are not monotonic")
                _nonempty_string(record.get("record_type"), f"{label} line {count + 1}.record_type")
                _mapping(record.get("data"), f"{label} line {count + 1}.data")
                previous_timestamp = timestamp
                count += 1
    finally:
        if duplicate >= 0:
            os.close(duplicate)
    _assert_fd_unchanged(descriptor, initial, label)
    return digest.hexdigest(), count


def _validate_semantic_source_snapshot(snapshot_value: object, label: str) -> str:
    snapshot = _mapping(snapshot_value, label)
    _require_exact_keys(
        snapshot,
        {
            "schema",
            "repository_root",
            "git",
            "semantic_sources",
            "source_frozen",
            "source_freeze_blockers",
            "source_frozen_reason",
            "fingerprint",
        },
        label,
    )
    if snapshot.get("schema") != _SEMANTIC_SNAPSHOT_SCHEMA:
        raise ComparisonError(f"{label} has the wrong schema")
    repository_root = _nonempty_string(snapshot.get("repository_root"), f"{label}.repository_root")
    root_path = PurePosixPath(repository_root)
    if (
        not root_path.is_absolute()
        or root_path.as_posix() != repository_root
        or ".." in root_path.parts
    ):
        raise ComparisonError(f"{label}.repository_root must be a normalized absolute path")

    git = _mapping(snapshot.get("git"), f"{label}.git")
    _require_exact_keys(
        git,
        {
            "branch",
            "head_state",
            "head_commit",
            "head_tree",
            "porcelain_sha256",
            "porcelain_entry_count",
            "worktree_clean",
        },
        f"{label}.git",
    )
    branch = git.get("branch")
    if branch is not None and (not isinstance(branch, str) or not branch):
        raise ComparisonError(f"{label}.git.branch must be a non-empty string or null")
    if git.get("head_state") != "resolved":
        raise ComparisonError(f"{label} does not have a resolved Git HEAD")
    for key in ("head_commit", "head_tree"):
        value = git.get(key)
        if not isinstance(value, str) or _GIT_OBJECT_RE.fullmatch(value) is None:
            raise ComparisonError(f"{label}.git.{key} must be a resolved Git object ID")
    if git.get("porcelain_sha256") != _EMPTY_SHA256:
        raise ComparisonError(f"{label} Git porcelain is not the hash of empty output")
    porcelain_count = _nonnegative_int(
        git.get("porcelain_entry_count"), f"{label}.git.porcelain_entry_count"
    )
    if porcelain_count != 0 or git.get("worktree_clean") is not True:
        raise ComparisonError(f"{label} does not describe a clean Git worktree")

    sources = _mapping(snapshot.get("semantic_sources"), f"{label}.semantic_sources")
    _require_exact_keys(
        sources,
        {
            "selection_policy",
            "files",
            "file_count",
            "repository_file_count",
            "tracked_repository_file_count",
            "aggregate_sha256",
        },
        f"{label}.semantic_sources",
    )
    selection = _mapping(
        sources.get("selection_policy"), f"{label}.semantic_sources.selection_policy"
    )
    _require_exact_keys(
        selection, _SELECTION_POLICY_KEYS, f"{label}.semantic_sources.selection_policy"
    )
    for key in _SELECTION_POLICY_KEYS - {"bytecode_and_caches_included"}:
        _nonempty_string(selection.get(key), f"{label}.semantic_sources.selection_policy.{key}")
    if selection.get("bytecode_and_caches_included") is not False:
        raise ComparisonError(f"{label} must exclude bytecode and caches")

    files = _list(sources.get("files"), f"{label}.semantic_sources.files")
    if not files:
        raise ComparisonError(f"{label}.semantic_sources.files must not be empty")
    normalized_files: list[Mapping[str, Any]] = []
    observed_paths: set[str] = set()
    for index, raw_file in enumerate(files):
        file_label = f"{label}.semantic_sources.files[{index}]"
        item = _mapping(raw_file, file_label)
        _require_exact_keys(
            item,
            {"path", "scope", "roles", "size_bytes", "sha256"},
            file_label,
        )
        if item.get("scope") != "repository":
            raise ComparisonError(f"{file_label}.scope must be repository")
        path = _nonempty_string(item.get("path"), f"{file_label}.path")
        pure_path = PurePosixPath(path)
        if (
            pure_path.is_absolute()
            or pure_path.as_posix() != path
            or any(part in {"", ".", ".."} for part in pure_path.parts)
            or "\\" in path
        ):
            raise ComparisonError(f"{file_label}.path must be normalized repository-relative POSIX")
        if path in observed_paths:
            raise ComparisonError(f"{label} contains duplicate semantic path {path}")
        observed_paths.add(path)
        roles = _list(item.get("roles"), f"{file_label}.roles")
        if not roles or any(not isinstance(role, str) or not role for role in roles):
            raise ComparisonError(f"{file_label}.roles must contain non-empty strings")
        if roles != sorted(set(roles)):
            raise ComparisonError(f"{file_label}.roles must be sorted and unique")
        _nonnegative_int(item.get("size_bytes"), f"{file_label}.size_bytes")
        _sha256_value(item.get("sha256"), f"{file_label}.sha256")
        normalized_files.append(item)
    if [item["path"] for item in normalized_files] != sorted(observed_paths):
        raise ComparisonError(f"{label}.semantic_sources.files must be path-sorted")
    file_count = len(files)
    for key in ("file_count", "repository_file_count", "tracked_repository_file_count"):
        declared_count = _nonnegative_int(sources.get(key), f"{label}.semantic_sources.{key}")
        if declared_count != file_count:
            raise ComparisonError(f"{label}.semantic_sources.{key} must equal {file_count}")
    aggregate = hashlib.sha256(canonical_json_bytes(files)).hexdigest()
    if sources.get("aggregate_sha256") != aggregate:
        raise ComparisonError(f"{label} semantic-source aggregate SHA-256 is inconsistent")

    if snapshot.get("source_frozen") is not True:
        raise ComparisonError(f"{label} semantic source is not frozen")
    if snapshot.get("source_freeze_blockers") != []:
        raise ComparisonError(f"{label} semantic source has freeze blockers")
    if snapshot.get("source_frozen_reason") != "clean_head_and_all_semantic_sources_git_tracked":
        raise ComparisonError(f"{label} source-frozen reason is inconsistent")

    fingerprint = _sha256_value(snapshot.get("fingerprint"), f"{label}.fingerprint")
    canonical_fields = dict(snapshot)
    del canonical_fields["fingerprint"]
    recomputed = hashlib.sha256(canonical_json_bytes(canonical_fields)).hexdigest()
    if fingerprint != recomputed:
        raise ComparisonError(f"{label} semantic-source fingerprint is inconsistent")
    return fingerprint


def _source_fingerprint(run_audit: Mapping[str, Any], label: str) -> str:
    provenance = _mapping(
        run_audit.get("semantic_source_provenance"),
        f"{label}.semantic_source_provenance",
    )
    _require_exact_keys(
        provenance,
        {
            "schema",
            "unchanged_during_run",
            "formal_use_allowed",
            "evidence_boundary",
            "start_snapshot",
            "end_snapshot_fingerprint",
            "comparison",
        },
        f"{label}.semantic_source_provenance",
    )
    if provenance.get("schema") != _SEMANTIC_PROVENANCE_SCHEMA:
        raise ComparisonError(f"{label} semantic-source provenance has the wrong schema")
    if provenance.get("unchanged_during_run") is not True:
        raise ComparisonError(f"{label} did not preserve its semantic source during replay")
    if provenance.get("formal_use_allowed") is not False:
        raise ComparisonError(f"{label} semantic-source provenance overclaims formal use")
    _nonempty_string(
        provenance.get("evidence_boundary"),
        f"{label}.semantic_source_provenance.evidence_boundary",
    )
    if provenance.get("comparison") != "byte_identical_canonical_snapshot":
        raise ComparisonError(f"{label} semantic-source comparison contract differs")
    fingerprint = _validate_semantic_source_snapshot(
        provenance.get("start_snapshot"),
        f"{label}.semantic_source_provenance.start_snapshot",
    )
    if provenance.get("end_snapshot_fingerprint") != fingerprint:
        raise ComparisonError(f"{label} start/end semantic-source fingerprints differ")
    return fingerprint


def _expected_schema_fingerprints() -> dict[str, str]:
    return {
        name: hashlib.sha256(
            canonical_json_bytes(
                [
                    {
                        "name": column.name,
                        "type": column.type_name,
                        "nullable": column.nullable,
                    }
                    for column in PARQUET_SCHEMAS[name]
                ]
            )
            + b"\n"
        ).hexdigest()
        for name in SECTION_16_PARQUET_ARTIFACTS
    }


def _row_count_mapping(value: object, label: str) -> dict[str, int]:
    mapping = _mapping(value, label)
    if set(mapping) != set(SECTION_16_PARQUET_ARTIFACTS):
        raise ComparisonError(f"{label} does not declare exactly the 13 Parquet artifacts")
    return {
        name: _nonnegative_int(mapping.get(name), f"{label}.{name}")
        for name in SECTION_16_PARQUET_ARTIFACTS
    }


def _validate_json_contracts(
    documents: Mapping[str, Mapping[str, Any]],
    parquet_rows: Mapping[str, int],
    parquet_facts: Mapping[str, Mapping[str, object]],
    journal_count: int,
    run_label: str,
) -> str:
    for name in (
        "trace-audit.json",
        "context-coverage.json",
        "capacity-audit.json",
        "run-audit.json",
        "summary.json",
    ):
        document = documents[name]
        if document.get("schema") != SECTION_16_SCHEMA_VERSION:
            raise ComparisonError(f"{run_label}/{name} has the wrong schema")
        if document.get("artifact") != name:
            raise ComparisonError(f"{run_label}/{name} has the wrong artifact identity")

    trace_audit = documents["trace-audit.json"]
    context = documents["context-coverage.json"]
    capacity = documents["capacity-audit.json"]
    run_audit = documents["run-audit.json"]
    summary = documents["summary.json"]
    for name, document in (
        ("trace-audit.json", trace_audit),
        ("capacity-audit.json", capacity),
        ("run-audit.json", run_audit),
        ("summary.json", summary),
    ):
        if document.get("status") != "PASS":
            raise ComparisonError(f"{run_label}/{name} is not a PASS document")
        projection_status = document.get("projection_status")
        if projection_status is not None and projection_status != "PASS":
            raise ComparisonError(f"{run_label}/{name} projection status is not PASS")

    request_count = parquet_rows["request-metrics.parquet"]
    workflow_count = parquet_rows["workflow-metrics.parquet"]
    trace_journal_count = _nonnegative_int(
        trace_audit.get("journal_record_count"),
        f"{run_label}/trace-audit.json.journal_record_count",
    )
    trace_execution_count = _nonnegative_int(
        trace_audit.get("execution_count"),
        f"{run_label}/trace-audit.json.execution_count",
    )
    trace_workflow_count = _nonnegative_int(
        trace_audit.get("workflow_count"),
        f"{run_label}/trace-audit.json.workflow_count",
    )
    if trace_journal_count != journal_count:
        raise ComparisonError(f"{run_label}/trace-audit.json journal count differs")
    if trace_execution_count != request_count:
        raise ComparisonError(f"{run_label}/trace-audit.json execution count differs")
    if trace_workflow_count != workflow_count:
        raise ComparisonError(f"{run_label}/trace-audit.json workflow count differs")
    if (
        trace_audit.get("evidence_class") != "E2"
        or trace_audit.get("formal_use_allowed") is not False
    ):
        raise ComparisonError(f"{run_label}/trace-audit.json evidence boundary differs")
    if trace_audit.get("recorded_api_time_used_as_simulated_time") is not False:
        raise ComparisonError(f"{run_label}/trace-audit.json uses recorded API time")

    context_request_count = _nonnegative_int(
        context.get("request_count"), f"{run_label}/context-coverage.json.request_count"
    )
    context_workflow_count = _nonnegative_int(
        context.get("workflow_count"), f"{run_label}/context-coverage.json.workflow_count"
    )
    if context_request_count != request_count or context_workflow_count != workflow_count:
        raise ComparisonError(f"{run_label}/context-coverage.json counts differ")
    if context.get("coverage_complete") is not True:
        raise ComparisonError(f"{run_label}/context-coverage.json is incomplete")
    strict_max = _nonnegative_int(
        context.get("strict_max_model_len_tokens"),
        f"{run_label}/context-coverage.json.strict_max_model_len_tokens",
    )
    if strict_max != MAX_MODEL_LEN_TOKENS:
        raise ComparisonError(f"{run_label}/context-coverage.json has the wrong context guard")
    if context.get("recorded_api_time_used_as_simulated_time") is not False:
        raise ComparisonError(f"{run_label}/context-coverage.json uses recorded API time")
    buckets = _list(
        context.get("context_buckets"), f"{run_label}/context-coverage.json.context_buckets"
    )
    bucket_requests = 0
    previous_upper = 0
    for index, raw_bucket in enumerate(buckets):
        bucket = _mapping(raw_bucket, f"{run_label}/context-coverage.json.context_buckets[{index}]")
        _require_exact_keys(
            bucket,
            {"lower_exclusive", "upper_inclusive", "request_count", "workflow_count"},
            f"{run_label}/context-coverage.json.context_buckets[{index}]",
        )
        lower = _nonnegative_int(bucket.get("lower_exclusive"), "context bucket lower")
        if lower != previous_upper:
            raise ComparisonError(f"{run_label}/context-coverage.json buckets are not contiguous")
        upper = _nonnegative_int(bucket.get("upper_inclusive"), "context bucket upper")
        if upper <= previous_upper:
            raise ComparisonError(f"{run_label}/context-coverage.json buckets do not increase")
        bucket_requests += _nonnegative_int(bucket.get("request_count"), "context request count")
        _nonnegative_int(bucket.get("workflow_count"), "context workflow count")
        previous_upper = upper
    if bucket_requests != request_count or previous_upper != MAX_MODEL_LEN_TOKENS:
        raise ComparisonError(f"{run_label}/context-coverage.json bucket totals differ")

    if capacity.get("valid") is not True:
        raise ComparisonError(f"{run_label}/capacity-audit.json is invalid")
    if capacity.get("resource_delta_replay_valid") is not True:
        raise ComparisonError(f"{run_label}/capacity-audit.json delta replay is invalid")
    if capacity.get("flow_byte_conservation_valid") is not True:
        raise ComparisonError(f"{run_label}/capacity-audit.json flow conservation is invalid")
    if capacity.get("snapshot_state_complete") is not True:
        raise ComparisonError(f"{run_label}/capacity-audit.json snapshot state is incomplete")
    incomplete_resource_ids = _list(
        capacity.get("incomplete_resource_ids"),
        f"{run_label}/capacity-audit.json.incomplete_resource_ids",
    )
    if incomplete_resource_ids:
        raise ComparisonError(
            f"{run_label}/capacity-audit.json declares incomplete resource IDs"
        )
    capacity_delta_count = _nonnegative_int(
        capacity.get("resource_delta_count"),
        f"{run_label}/capacity-audit.json.resource_delta_count",
    )
    capacity_flow_count = _nonnegative_int(
        capacity.get("flow_interval_count"),
        f"{run_label}/capacity-audit.json.flow_interval_count",
    )
    if capacity_delta_count != parquet_rows["resource-ledger-deltas.parquet"]:
        raise ComparisonError(f"{run_label}/capacity-audit.json resource-delta count differs")
    if capacity_flow_count != parquet_rows["flow-rate-events.parquet"]:
        raise ComparisonError(f"{run_label}/capacity-audit.json flow count differs")
    capacity_resource_count = _nonnegative_int(
        capacity.get("resource_count"),
        f"{run_label}/capacity-audit.json.resource_count",
    )
    snapshot_facts = _mapping(
        parquet_facts.get("resource-ledger-snapshots.parquet"),
        f"{run_label}/resource-ledger-snapshots.parquet facts",
    )
    snapshot_resource_ids = _list(
        snapshot_facts.get("resource_ids"),
        f"{run_label}/resource-ledger-snapshots.parquet resource IDs",
    )
    if capacity_resource_count != len(snapshot_resource_ids):
        raise ComparisonError(f"{run_label}/capacity-audit.json resource count differs")

    section = _mapping(run_audit.get("section_16"), f"{run_label}/run-audit.json.section_16")
    artifact_count = _nonnegative_int(
        section.get("artifact_count"), f"{run_label}/run-audit.json.section_16.artifact_count"
    )
    if artifact_count != len(SECTION_16_ARTIFACTS):
        raise ComparisonError(f"{run_label}/run-audit.json artifact count differs")
    if section.get("expected_artifacts") != list(SECTION_16_ARTIFACTS):
        raise ComparisonError(f"{run_label}/run-audit.json expected artifact set differs")
    if section.get("complete_file_set") is not True:
        raise ComparisonError(f"{run_label}/run-audit.json file set is incomplete")
    schema_fingerprints = _mapping(
        section.get("fixed_parquet_schemas"),
        f"{run_label}/run-audit.json.section_16.fixed_parquet_schemas",
    )
    if dict(schema_fingerprints) != _expected_schema_fingerprints():
        raise ComparisonError(f"{run_label}/run-audit.json fixed schema fingerprints differ")
    run_rows = _row_count_mapping(
        section.get("parquet_row_counts"),
        f"{run_label}/run-audit.json.section_16.parquet_row_counts",
    )
    if run_rows != dict(parquet_rows):
        raise ComparisonError(f"{run_label}/run-audit.json Parquet row counts differ")
    if run_audit.get("execution_status") != "PASS":
        raise ComparisonError(f"{run_label}/run-audit.json execution status is not PASS")
    if run_audit.get("evidence_class") != "E2" or run_audit.get("formal_use_allowed") is not False:
        raise ComparisonError(f"{run_label}/run-audit.json evidence boundary differs")
    for field in (
        "ledger_replay_byte_identical",
        "allocation_registry_replay_byte_identical",
        "journal_replay_byte_identical",
    ):
        if run_audit.get(field) is not True:
            raise ComparisonError(f"{run_label}/run-audit.json does not prove {field}")
    run_capacity = _mapping(run_audit.get("capacity"), f"{run_label}/run-audit.json.capacity")
    for key in (
        "schema",
        "artifact",
        "status",
        "valid",
        "truth_sources",
        "resource_delta_replay_valid",
        "flow_byte_conservation_valid",
        "resource_delta_count",
        "flow_interval_count",
        "resource_count",
        "event_boundary_snapshots_preserved",
        "snapshot_state_complete",
        "incomplete_resource_ids",
        "snapshot_completeness_evidence",
    ):
        if run_capacity.get(key) != capacity.get(key):
            raise ComparisonError(f"{run_label} run/capacity audit field {key} differs")
    timing = _mapping(run_audit.get("timing_metrics"), f"{run_label}/run-audit.json.timing_metrics")
    timing_request_count = _nonnegative_int(
        timing.get("request_count"), f"{run_label}/run-audit.json.timing_metrics.request_count"
    )
    timing_workflow_count = _nonnegative_int(
        timing.get("workflow_count"),
        f"{run_label}/run-audit.json.timing_metrics.workflow_count",
    )
    if timing_request_count != request_count or timing_workflow_count != workflow_count:
        raise ComparisonError(f"{run_label}/run-audit.json timing counts differ")
    request_complete = _nonnegative_int(
        timing.get("request_complete_count"), "request complete count"
    )
    workflow_complete = _nonnegative_int(
        timing.get("workflow_complete_count"), "workflow complete count"
    )
    if request_complete != request_count:
        raise ComparisonError(f"{run_label}/run-audit.json request timing is incomplete")
    if workflow_complete != workflow_count:
        raise ComparisonError(f"{run_label}/run-audit.json workflow timing is incomplete")
    if (
        timing.get("missing_values_are_null") is not True
        or timing.get("completeness_and_evidence_flags_present") is not True
    ):
        raise ComparisonError(f"{run_label}/run-audit.json timing evidence contract differs")
    if timing.get("observed_api_time_used_as_simulated_time") is not False:
        raise ComparisonError(f"{run_label}/run-audit.json uses observed API time")

    summary_rows = _row_count_mapping(
        summary.get("parquet_row_counts"),
        f"{run_label}/summary.json.parquet_row_counts",
    )
    if summary_rows != dict(parquet_rows):
        raise ComparisonError(f"{run_label}/summary.json Parquet row counts differ")
    summary_request_count = _nonnegative_int(
        summary.get("request_count"), f"{run_label}/summary.json.request_count"
    )
    summary_workflow_count = _nonnegative_int(
        summary.get("workflow_count"), f"{run_label}/summary.json.workflow_count"
    )
    if summary_request_count != request_count or summary_workflow_count != workflow_count:
        raise ComparisonError(f"{run_label}/summary.json request/workflow counts differ")
    completed_request_count = _nonnegative_int(
        summary.get("completed_request_count"),
        f"{run_label}/summary.json.completed_request_count",
    )
    if completed_request_count != request_count:
        raise ComparisonError(f"{run_label}/summary.json completed request count differs")
    summary_request_complete = _nonnegative_int(
        summary.get("request_timing_complete_count"),
        f"{run_label}/summary.json.request_timing_complete_count",
    )
    if summary_request_complete != request_complete:
        raise ComparisonError(f"{run_label}/summary.json request timing count differs")
    if summary_request_complete != summary_request_count:
        raise ComparisonError(f"{run_label}/summary.json request timing is incomplete")
    summary_workflow_complete = _nonnegative_int(
        summary.get("workflow_timing_complete_count"),
        f"{run_label}/summary.json.workflow_timing_complete_count",
    )
    if summary_workflow_complete != workflow_complete:
        raise ComparisonError(f"{run_label}/summary.json workflow timing count differs")
    if summary_workflow_complete != summary_workflow_count:
        raise ComparisonError(f"{run_label}/summary.json workflow timing is incomplete")
    if summary.get("evidence_class") != "E2" or summary.get("formal_use_allowed") is not False:
        raise ComparisonError(f"{run_label}/summary.json evidence boundary differs")
    if summary.get("observed_api_time_used_as_simulated_time") is not False:
        raise ComparisonError(f"{run_label}/summary.json uses observed API time")

    return _source_fingerprint(run_audit, f"{run_label}/run-audit.json")


def inspect_run(path: Path) -> dict[str, object]:
    """Validate one complete PASS run and return its content identities."""

    run = Path(path)
    if run.is_symlink():
        raise ComparisonError(f"run path must be a regular non-symlink directory: {run}")
    try:
        resolved = run.resolve(strict=True)
        directory_fd = os.open(run, _DIRECTORY_FLAGS)
    except (OSError, RuntimeError) as error:
        raise ComparisonError(
            f"run path must be a regular non-symlink directory: {run}: {error}"
        ) from error
    try:
        directory_stat = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise ComparisonError(f"run path is not a directory: {run}")
        expected = set(SECTION_16_ARTIFACTS)
        try:
            observed = set(os.listdir(directory_fd))
        except OSError as error:
            raise ComparisonError(f"cannot enumerate run directory {run}: {error}") from error
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        if missing or extra:
            raise ComparisonError(f"{run} artifact set differs: missing={missing}, extra={extra}")

        pyarrow, parquet = _load_pyarrow()
        identities: dict[str, str] = {}
        parquet_rows: dict[str, int] = {}
        parquet_facts: dict[str, Mapping[str, object]] = {}
        documents: dict[str, Mapping[str, Any]] = {}
        journal_count: int | None = None
        for name in sorted(expected):
            artifact_label = f"{run}/{name}"
            descriptor, initial = _open_regular_at(directory_fd, name, str(run))
            try:
                if name in SECTION_16_PARQUET_ARTIFACTS:
                    digest, row_count, facts = _inspect_parquet_fd(
                        descriptor,
                        initial,
                        name,
                        artifact_label,
                        pyarrow=pyarrow,
                        parquet=parquet,
                    )
                    identities[name] = digest
                    parquet_rows[name] = row_count
                    parquet_facts[name] = facts
                elif name == "event-journal.jsonl":
                    digest, journal_count = _inspect_journal_fd(
                        descriptor,
                        initial,
                        artifact_label,
                    )
                    identities[name] = digest
                else:
                    raw = _read_all(descriptor)
                    identities[name] = hashlib.sha256(raw).hexdigest()
                    documents[name] = _parse_json_bytes(raw, artifact_label)
                    _assert_fd_unchanged(descriptor, initial, artifact_label)
            finally:
                os.close(descriptor)
        if journal_count is None:
            raise ComparisonError(f"{run} has no validated event journal")
        source_fingerprint = _validate_json_contracts(
            documents,
            parquet_rows,
            parquet_facts,
            journal_count,
            str(run),
        )
        if _stat_signature(os.fstat(directory_fd)) != _stat_signature(directory_stat):
            raise ComparisonError(f"run directory changed while being validated: {run}")
        return {
            "artifact_sha256": identities,
            "semantic_source_fingerprint": source_fingerprint,
            "status": "PASS",
            "resolved_path": str(resolved),
            "directory_identity": (directory_stat.st_dev, directory_stat.st_ino),
        }
    finally:
        os.close(directory_fd)


def compare_runs(first: Path, second: Path) -> dict[str, object]:
    """Require distinct directories containing valid byte-identical PASS bundles."""

    first_path = Path(first)
    second_path = Path(second)
    try:
        first_resolved = first_path.resolve(strict=True)
        second_resolved = second_path.resolve(strict=True)
    except OSError as error:
        raise ComparisonError(f"cannot resolve both run directories: {error}") from error
    if first_resolved == second_resolved:
        raise ComparisonError("the two run arguments resolve to the same directory")
    try:
        if os.path.samefile(first_path, second_path):
            raise ComparisonError("the two run arguments refer to the same directory inode")
    except ComparisonError:
        raise
    except OSError as error:
        raise ComparisonError(f"cannot compare run-directory identities: {error}") from error

    first_result = inspect_run(first_path)
    second_result = inspect_run(second_path)
    if first_result["resolved_path"] == second_result["resolved_path"]:
        raise ComparisonError("the validated run directories have the same resolved path")
    if first_result["directory_identity"] == second_result["directory_identity"]:
        raise ComparisonError("the validated run directories have the same device/inode")
    first_source = first_result["semantic_source_fingerprint"]
    second_source = second_result["semantic_source_fingerprint"]
    if first_source != second_source:
        raise ComparisonError(
            f"semantic-source fingerprints differ: first={first_source}, second={second_source}"
        )
    first_hashes = _mapping(first_result["artifact_sha256"], "first artifact hashes")
    second_hashes = _mapping(second_result["artifact_sha256"], "second artifact hashes")
    mismatches = [
        name for name in sorted(first_hashes) if first_hashes[name] != second_hashes[name]
    ]
    if mismatches:
        raise ComparisonError(f"Section 16 artifacts are not byte-identical: {mismatches}")
    aggregate = hashlib.sha256(
        canonical_json_bytes({name: first_hashes[name] for name in sorted(first_hashes)})
    ).hexdigest()
    return {
        "schema": "moonkvsim.section16-double-replay-comparison.v1",
        "status": "PASS",
        "acceptance": (
            "two_distinct_directories_contain_valid_frozen_PASS_bundles_"
            "with_all_19_artifacts_byte_identical"
        ),
        "independent_execution_proven": False,
        "limitation": (
            "directory_and_content_validation_cannot_prove_that_one_bundle_"
            "was_not_copied_from_the_other"
        ),
        "artifact_count": len(first_hashes),
        "artifact_sha256": dict(first_hashes),
        "aggregate_sha256": aggregate,
        "semantic_source_fingerprint": first_source,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = compare_runs(args.first, args.second)
    except ComparisonError as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, sort_keys=True))
        return 1
    sys.stdout.buffer.write(canonical_json_bytes(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
