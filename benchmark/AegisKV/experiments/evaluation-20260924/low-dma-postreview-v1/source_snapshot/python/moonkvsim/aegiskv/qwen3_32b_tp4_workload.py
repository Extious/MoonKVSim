"""Derive the frozen Qwen3-32B TP4 workload from exact Qwen3 token IDs.

The pinned Qwen3-8B and Qwen3-32B revisions have byte-identical tokenizer
artifacts.  This module therefore ports token IDs, hashes, record order, and
workflow topology verbatim, while replacing model identity and recomputing the
isolated request duration with the Qwen3-32B TP4 analytical provider.

The resulting timing remains modeled and uncalibrated.  Contexts above the
model's native 40,960-token limit depend on the proposed, runtime-unvalidated
YaRN 131,072-token configuration; no input is truncated or padded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from moonkvsim.aegiskv.qwen3_32b_tp4_duration import (
    CONTEXT_EXTENSION_PROVENANCE,
    ISOLATED_REQUEST_SCHEDULING_RULE,
    MAX_CONTEXT_TOKENS,
    MODEL_ID,
    MODEL_REVISION,
    NATIVE_MAX_CONTEXT_TOKENS,
    Qwen3TP4SchedulerStepDurationProvider,
    build_qwen3_32b_tp4_prediction_profile,
)
from moonkvsim.common.hash import sha256_json

SCHEMA: Final = "moonkvsim.aegiskv.qwen3_32b_tp4_workload_derivation.v1"
SOURCE_MODEL_ID: Final = "Qwen/Qwen3-8B"
SOURCE_MODEL_REVISION: Final = "b968826d9c46dd6066d109eabc6255188de91218"
TOKENIZER_EQUIVALENCE_SCHEMA: Final = "moonkvsim.aegiskv.tokenizer_equivalence.v1"
MANIFEST_SCHEMA: Final = "moonkvsim.aegiskv.experiment_workload_manifest.v1"
MAX_NUM_SCHEDULED_TOKENS: Final = 4_096
EXPECTED_RECORD_COUNT: Final = 1_304
EXPECTED_WORKFLOW_COUNT: Final = 160

DEFAULT_SOURCE_WORKLOAD: Final = Path(
    "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl"
)
DEFAULT_SOURCE_MANIFEST: Final = Path(
    "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160-manifest.json"
)
DEFAULT_EQUIVALENCE: Final = Path(
    "benchmark/AegisKV/experiments/workloads/qwen3-8b-32b-tokenizer-equivalence.json"
)
DEFAULT_OUTPUT: Final = Path(
    "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-32b-tp4-160.jsonl"
)
DEFAULT_OUTPUT_MANIFEST: Final = Path(
    "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-32b-tp4-160-manifest.json"
)
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_RECORD_CHANGES: Final = frozenset(
    {
        "model_id",
        "model_revision",
        "observed_finish_ns",
        "recorded_api_time_ns",
    }
)


class Qwen3TP4WorkloadError(ValueError):
    """The Qwen3-32B workload derivation failed closed."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise Qwen3TP4WorkloadError(f"cannot hash {path}: {error}") from error
    return digest.hexdigest()


def _load_json_object(path: Path, *, kind: str) -> dict[str, Any]:
    if path.is_symlink():
        raise Qwen3TP4WorkloadError(f"{kind} symlinks are forbidden: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Qwen3TP4WorkloadError(f"cannot load {kind} {path}: {error}") from error
    if not isinstance(value, dict):
        raise Qwen3TP4WorkloadError(f"{kind} must be a JSON object")
    return value


def _require_int(value: object, where: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Qwen3TP4WorkloadError(f"{where} must be an integer")
    if positive and value <= 0:
        raise Qwen3TP4WorkloadError(f"{where} must be positive")
    if not positive and value < 0:
        raise Qwen3TP4WorkloadError(f"{where} must be non-negative")
    return value


def _require_string(value: object, where: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise Qwen3TP4WorkloadError(f"{where} must be a non-empty string")
    return value


def _require_sha256(value: object, where: str) -> str:
    result = _require_string(value, where)
    if _SHA256.fullmatch(result) is None:
        raise Qwen3TP4WorkloadError(f"{where} must be a lowercase SHA-256")
    return result


def _load_source_manifest(
    path: Path,
    *,
    source_workload_path: Path,
    enforce_formal_shape: bool,
) -> dict[str, Any]:
    manifest = _load_json_object(path, kind="source workload manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "pass":
        raise Qwen3TP4WorkloadError("source workload manifest must be a passing v1 manifest")
    expected_fingerprint = _require_sha256(
        manifest.get("fingerprint"), "source manifest fingerprint"
    )
    fingerprint_fields = {key: value for key, value in manifest.items() if key != "fingerprint"}
    if sha256_json(fingerprint_fields) != expected_fingerprint:
        raise Qwen3TP4WorkloadError("source workload manifest fingerprint drifted")

    artifact = manifest.get("artifact")
    selection = manifest.get("selection")
    normalizer = manifest.get("normalizer")
    if not all(isinstance(item, dict) for item in (artifact, selection, normalizer)):
        raise Qwen3TP4WorkloadError("source manifest lacks artifact, selection, or normalizer")
    assert isinstance(artifact, dict)
    assert isinstance(selection, dict)
    assert isinstance(normalizer, dict)
    expected_artifact_sha = _require_sha256(
        artifact.get("sha256"), "source manifest artifact SHA-256"
    )
    if _sha256_file(source_workload_path) != expected_artifact_sha:
        raise Qwen3TP4WorkloadError("source workload SHA-256 differs from its manifest")
    if (
        normalizer.get("model_id") != SOURCE_MODEL_ID
        or normalizer.get("model_revision") != SOURCE_MODEL_REVISION
    ):
        raise Qwen3TP4WorkloadError("source manifest does not bind the pinned Qwen3-8B model")
    for guard in ("no_span_slicing", "no_truncation", "no_padding", "no_synthesis"):
        if selection.get(guard) is not True:
            raise Qwen3TP4WorkloadError(f"source manifest selection.{guard} must be true")
    selected = selection.get("selected_workflow_ids")
    if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
        raise Qwen3TP4WorkloadError("source selected_workflow_ids must be strings")
    if len(set(selected)) != len(selected):
        raise Qwen3TP4WorkloadError("source selected_workflow_ids contain duplicates")
    record_count = _require_int(artifact.get("record_count"), "source artifact record_count")
    if enforce_formal_shape and (
        record_count != EXPECTED_RECORD_COUNT or len(selected) != EXPECTED_WORKFLOW_COUNT
    ):
        raise Qwen3TP4WorkloadError(
            "source workload is not the frozen 1304-record/160-workflow set"
        )
    return manifest


def _load_equivalence(path: Path) -> tuple[dict[str, Any], str]:
    equivalence = _load_json_object(path, kind="tokenizer equivalence evidence")
    if equivalence.get("schema") != TOKENIZER_EQUIVALENCE_SCHEMA:
        raise Qwen3TP4WorkloadError("unsupported tokenizer equivalence schema")
    if equivalence.get("status") != "PASS":
        raise Qwen3TP4WorkloadError("tokenizer equivalence evidence is not passing")
    if equivalence.get("comparison") != "byte_identical_files_at_pinned_model_revisions":
        raise Qwen3TP4WorkloadError("tokenizer equivalence is not byte-identical-file evidence")
    if equivalence.get("evidence_boundary") != (
        "token_ids_are_portable_between_these_revisions_only;_service_times_are_not"
    ):
        raise Qwen3TP4WorkloadError("tokenizer equivalence evidence boundary drifted")
    models = equivalence.get("models")
    if not isinstance(models, list):
        raise Qwen3TP4WorkloadError("tokenizer equivalence models must be an array")
    actual_models = {
        (item.get("model_id"), item.get("revision")) for item in models if isinstance(item, dict)
    }
    expected_models = {
        (SOURCE_MODEL_ID, SOURCE_MODEL_REVISION),
        (MODEL_ID, MODEL_REVISION),
    }
    if actual_models != expected_models or len(models) != 2:
        raise Qwen3TP4WorkloadError("tokenizer equivalence does not bind the two pinned models")
    files = equivalence.get("files")
    if not isinstance(files, dict) or set(files) != {
        "merges.txt",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
    }:
        raise Qwen3TP4WorkloadError("tokenizer equivalence file set drifted")
    for name, digest in files.items():
        _require_sha256(digest, f"tokenizer equivalence files.{name}")
    return equivalence, _sha256_file(path)


def _load_source_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise Qwen3TP4WorkloadError(f"source workload line {line_number} is blank")
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise Qwen3TP4WorkloadError(
                        f"source workload line {line_number} is not an object"
                    )
                records.append(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Qwen3TP4WorkloadError(f"cannot load source workload {path}: {error}") from error
    if not records:
        raise Qwen3TP4WorkloadError("source workload is empty")
    return records


def _validate_record(
    record: Mapping[str, Any],
    *,
    line_number: int,
) -> tuple[str, str, tuple[str, ...], int, int]:
    where = f"source workload line {line_number}"
    if record.get("schema") != "moonkvsim.multi_agent_trace.v1":
        raise Qwen3TP4WorkloadError(f"{where} has an unsupported trace schema")
    if (
        record.get("model_id") != SOURCE_MODEL_ID
        or record.get("model_revision") != SOURCE_MODEL_REVISION
    ):
        raise Qwen3TP4WorkloadError(f"{where} does not bind the pinned Qwen3-8B model")
    if record.get("token_count_mode") != "qwen3_token_ids":
        raise Qwen3TP4WorkloadError(f"{where} is not exact Qwen3-token-ID evidence")
    if record.get("truncated") is not False or record.get("model_length_guard_passed") is not True:
        raise Qwen3TP4WorkloadError(f"{where} is truncated or failed its model-length guard")
    if _require_int(record.get("tool_delay_ns"), f"{where}.tool_delay_ns") != 0:
        raise Qwen3TP4WorkloadError(f"{where} has nonzero tool delay outside the duration model")
    workflow_id = _require_string(record.get("workflow_id"), f"{where}.workflow_id")
    span_id = _require_string(record.get("span_id"), f"{where}.span_id")
    parent_ids_value = record.get("parent_span_ids")
    if not isinstance(parent_ids_value, list) or not all(
        isinstance(item, str) for item in parent_ids_value
    ):
        raise Qwen3TP4WorkloadError(f"{where}.parent_span_ids must contain strings")
    parent_ids = tuple(parent_ids_value)
    if len(set(parent_ids)) != len(parent_ids):
        raise Qwen3TP4WorkloadError(f"{where}.parent_span_ids contains duplicates")

    prompt_tokens = _require_int(
        record.get("prompt_tokens"), f"{where}.prompt_tokens", positive=True
    )
    output_tokens = _require_int(
        record.get("output_tokens"), f"{where}.output_tokens", positive=True
    )
    total_tokens = _require_int(record.get("total_model_tokens"), f"{where}.total_model_tokens")
    if total_tokens != prompt_tokens + output_tokens:
        raise Qwen3TP4WorkloadError(f"{where} total_model_tokens is inconsistent")
    if total_tokens > MAX_CONTEXT_TOKENS:
        raise Qwen3TP4WorkloadError(f"{where} exceeds the proposed 131072-token context")

    content = record.get("messages_or_token_ids")
    if not isinstance(content, dict) or content.get("kind") != "token_ids":
        raise Qwen3TP4WorkloadError(f"{where} lacks frozen token IDs")
    token_ids = content.get("value")
    if not isinstance(token_ids, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) for item in token_ids
    ):
        raise Qwen3TP4WorkloadError(f"{where} token IDs are malformed")
    if len(token_ids) != prompt_tokens:
        raise Qwen3TP4WorkloadError(f"{where} prompt token count differs from exact IDs")
    token_hash = sha256_json(token_ids)
    if token_hash != content.get("sha256") or token_hash != record.get("prompt_token_ids_hash"):
        raise Qwen3TP4WorkloadError(f"{where} prompt token hash drifted")
    submit_ns = _require_int(record.get("observed_submit_ns"), f"{where}.observed_submit_ns")
    old_duration = _require_int(
        record.get("recorded_api_time_ns"), f"{where}.recorded_api_time_ns", positive=True
    )
    if record.get("observed_finish_ns") != submit_ns + old_duration:
        raise Qwen3TP4WorkloadError(f"{where} source finish/duration fields are inconsistent")
    return workflow_id, span_id, parent_ids, prompt_tokens, output_tokens


def _validate_dag(
    records: Sequence[Mapping[str, Any]],
    *,
    selected_workflow_ids: Sequence[str],
) -> None:
    span_workflow: dict[str, str] = {}
    parents_by_span: dict[str, tuple[str, ...]] = {}
    workflows: set[str] = set()
    for line_number, record in enumerate(records, start=1):
        workflow_id, span_id, parent_ids, _, _ = _validate_record(record, line_number=line_number)
        if span_id in span_workflow:
            raise Qwen3TP4WorkloadError(f"duplicate source span_id: {span_id}")
        span_workflow[span_id] = workflow_id
        parents_by_span[span_id] = parent_ids
        workflows.add(workflow_id)
    if workflows != set(selected_workflow_ids):
        raise Qwen3TP4WorkloadError("source record workflows differ from manifest selection")

    children: defaultdict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {span_id: 0 for span_id in span_workflow}
    for span_id, parent_ids in parents_by_span.items():
        for parent_id in parent_ids:
            if parent_id not in span_workflow:
                raise Qwen3TP4WorkloadError(f"span {span_id} references missing parent {parent_id}")
            if span_workflow[parent_id] != span_workflow[span_id]:
                raise Qwen3TP4WorkloadError(f"span {span_id} has a cross-workflow parent")
            children[parent_id].append(span_id)
            indegree[span_id] += 1
    ready = deque(sorted(span_id for span_id, degree in indegree.items() if degree == 0))
    visited = 0
    while ready:
        span_id = ready.popleft()
        visited += 1
        for child in children[span_id]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(records):
        raise Qwen3TP4WorkloadError("source workload DAG contains a cycle")


def _canonical_json_line(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def _context_audit(records: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    workflow_max: dict[str, int] = {}
    native_records = 0
    max_tokens = 0
    for record in records:
        workflow_id = str(record["workflow_id"])
        total_tokens = int(record["total_model_tokens"])
        max_tokens = max(max_tokens, total_tokens)
        workflow_max[workflow_id] = max(workflow_max.get(workflow_id, 0), total_tokens)
        if total_tokens <= NATIVE_MAX_CONTEXT_TOKENS:
            native_records += 1
    native_workflows = sum(
        maximum <= NATIVE_MAX_CONTEXT_TOKENS for maximum in workflow_max.values()
    )
    return {
        "native_max_context_tokens": NATIVE_MAX_CONTEXT_TOKENS,
        "simulated_max_context_tokens": MAX_CONTEXT_TOKENS,
        "context_extension_provenance": CONTEXT_EXTENSION_PROVENANCE,
        "runtime_context_extension_validated": False,
        "max_observed_context_tokens": max_tokens,
        "record_count": len(records),
        "workflow_count": len(workflow_max),
        "native_context_record_count": native_records,
        "proposed_yarn_record_count": len(records) - native_records,
        "native_context_workflow_count": native_workflows,
        "proposed_yarn_workflow_count": len(workflow_max) - native_workflows,
        "no_truncation": True,
        "no_padding": True,
    }


def derive_qwen3_32b_tp4_workload(
    *,
    source_workload_path: Path,
    source_manifest_path: Path,
    equivalence_path: Path,
    output_path: Path,
    output_manifest_path: Path,
    provider_source_revision: str,
    provider_source_revision_status: str,
    provider_source_path: Path,
    artifact_declared_path: str | None = None,
    enforce_formal_shape: bool = True,
) -> dict[str, Any]:
    """Publish a deterministic Qwen3-32B workload and manifest atomically."""

    if _SHA1.fullmatch(provider_source_revision) is None:
        raise Qwen3TP4WorkloadError("provider_source_revision must be a lowercase Git commit")
    _require_string(provider_source_revision_status, "provider_source_revision_status")
    resolved_inputs = {
        source_workload_path.resolve(),
        source_manifest_path.resolve(),
        equivalence_path.resolve(),
        provider_source_path.resolve(),
    }
    if (
        output_path.resolve() in resolved_inputs
        or output_manifest_path.resolve() in resolved_inputs
    ):
        raise Qwen3TP4WorkloadError("output paths must not overwrite derivation inputs")
    if output_path.resolve() == output_manifest_path.resolve():
        raise Qwen3TP4WorkloadError("workload and manifest outputs must differ")
    if output_path.is_symlink() or output_manifest_path.is_symlink():
        raise Qwen3TP4WorkloadError("output symlinks are forbidden")

    source_manifest = _load_source_manifest(
        source_manifest_path,
        source_workload_path=source_workload_path,
        enforce_formal_shape=enforce_formal_shape,
    )
    equivalence, equivalence_sha256 = _load_equivalence(equivalence_path)
    source_records = _load_source_records(source_workload_path)
    source_artifact = source_manifest["artifact"]
    source_selection = source_manifest["selection"]
    assert isinstance(source_artifact, dict)
    assert isinstance(source_selection, dict)
    if len(source_records) != source_artifact["record_count"]:
        raise Qwen3TP4WorkloadError("source workload record count differs from manifest")
    selected_workflow_ids = source_selection["selected_workflow_ids"]
    assert isinstance(selected_workflow_ids, list)
    _validate_dag(source_records, selected_workflow_ids=selected_workflow_ids)

    profile = build_qwen3_32b_tp4_prediction_profile(
        provider_source_revision=provider_source_revision
    )
    provider = Qwen3TP4SchedulerStepDurationProvider(prediction_profile=profile)
    derived_records: list[dict[str, Any]] = []
    duration_ns_values: list[int] = []
    for line_number, source in enumerate(source_records, start=1):
        _, _, _, prompt_tokens, output_tokens = _validate_record(source, line_number=line_number)
        duration_ns = provider.predict_isolated_request_duration_ns(
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            max_num_scheduled_tokens=MAX_NUM_SCHEDULED_TOKENS,
        )
        derived = dict(source)
        derived["model_id"] = MODEL_ID
        derived["model_revision"] = MODEL_REVISION
        derived["recorded_api_time_ns"] = duration_ns
        derived["observed_finish_ns"] = int(source["observed_submit_ns"]) + duration_ns
        changed = {
            key for key in source.keys() | derived.keys() if source.get(key) != derived.get(key)
        }
        if not changed.issubset(_ALLOWED_RECORD_CHANGES):
            raise AssertionError(f"unexpected derived record mutations: {sorted(changed)}")
        derived_records.append(derived)
        duration_ns_values.append(duration_ns)

    source_topology = [
        (record["workflow_id"], record["span_id"], record["parent_span_ids"])
        for record in source_records
    ]
    derived_topology = [
        (record["workflow_id"], record["span_id"], record["parent_span_ids"])
        for record in derived_records
    ]
    if source_topology != derived_topology:
        raise AssertionError("derived workflow topology or record order changed")
    context_audit = _context_audit(derived_records)
    if enforce_formal_shape and (
        context_audit["record_count"] != EXPECTED_RECORD_COUNT
        or context_audit["workflow_count"] != EXPECTED_WORKFLOW_COUNT
    ):
        raise Qwen3TP4WorkloadError("derived workload lost its formal 1304/160 shape")

    artifact_bytes = b"".join(_canonical_json_line(record) for record in derived_records)
    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    source_manifest_sha256 = _sha256_file(source_manifest_path)
    source_workload_sha256 = _sha256_file(source_workload_path)
    provider_source_sha256 = _sha256_file(provider_source_path)
    source_normalizer = source_manifest.get("normalizer")
    assert isinstance(source_normalizer, dict)
    source_selection_copy = json.loads(json.dumps(source_selection))
    assert isinstance(source_selection_copy, dict)
    source_selection_copy["qwen3_32b_context_audit"] = context_audit
    source_selection_copy["no_truncation"] = True
    source_selection_copy["no_padding"] = True

    declared_path = artifact_declared_path or output_path.as_posix()
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "status": "pass",
        "evidence": {
            "class": "E2",
            "scope": "modeled/preliminary",
            "calibration": "not_calibrated",
            "timing_and_bandwidth": "modeled_uncalibrated",
            "physical_execution": False,
            "formal_use_allowed": False,
            "paper_ready": False,
        },
        "derivation": {
            "schema": SCHEMA,
            "rule": (
                "preserve_exact_token_ids_hashes_record_order_and_workflow_dag;"
                "replace_model_identity_and_isolated_request_duration_only"
            ),
            "source_workload": {
                "path": source_workload_path.as_posix(),
                "sha256": source_workload_sha256,
                "record_count": len(source_records),
                "semantic_fingerprint": source_artifact["semantic_fingerprint"],
            },
            "source_manifest": {
                "path": source_manifest_path.as_posix(),
                "sha256": source_manifest_sha256,
                "fingerprint": source_manifest["fingerprint"],
            },
            "tokenizer_equivalence": {
                "path": equivalence_path.as_posix(),
                "sha256": equivalence_sha256,
                "comparison": equivalence["comparison"],
                "files": equivalence["files"],
                "evidence_boundary": equivalence["evidence_boundary"],
            },
            "allowed_record_changes": sorted(_ALLOWED_RECORD_CHANGES),
            "exact_prompt_token_ids_preserved": True,
            "exact_prompt_hashes_preserved": True,
            "workflow_dag_preserved": True,
            "record_order_preserved": True,
            "no_truncation": True,
            "no_padding": True,
        },
        "source": source_manifest.get("source"),
        "normalizer": {
            "version": SCHEMA,
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "tokenizer_fingerprint": source_normalizer.get("tokenizer_fingerprint"),
            "tokenizer_equivalence_sha256": equivalence_sha256,
            "topology": source_normalizer.get("topology"),
            "prompt_source": source_normalizer.get("prompt_source"),
            "tool_delay_ns": 0,
            "duration_model": {
                "kind": "qwen3_32b_tp4_analytical_roofline_isolated_request",
                "timing_and_bandwidth": "modeled_uncalibrated",
                "physically_calibrated": False,
                "physical_measurement_completed": False,
                "formal_use_allowed": False,
                "isolated_request_scheduling_rule": ISOLATED_REQUEST_SCHEDULING_RULE,
                "max_num_scheduled_tokens": MAX_NUM_SCHEDULED_TOKENS,
                "provider_provenance": provider.provenance,
                "provider_source_revision": provider_source_revision,
                "provider_source_revision_status": provider_source_revision_status,
                "provider_source_path": provider_source_path.as_posix(),
                "provider_source_sha256": provider_source_sha256,
            },
            "context": context_audit,
        },
        "evidence_snapshot": source_manifest.get("evidence_snapshot"),
        "selection": source_selection_copy,
        "duration_audit": {
            "record_count": len(duration_ns_values),
            "minimum_ns": min(duration_ns_values),
            "maximum_ns": max(duration_ns_values),
            "sum_ns": sum(duration_ns_values),
            "duration_vector_sha256": sha256_json(duration_ns_values),
            "source_duration_vector_sha256": sha256_json(
                [int(record["recorded_api_time_ns"]) for record in source_records]
            ),
        },
        "artifact": {
            "path": declared_path,
            "sha256": artifact_sha256,
            "record_count": len(derived_records),
            "semantic_fingerprint": sha256_json(derived_records),
        },
    }
    manifest["fingerprint"] = sha256_json(manifest)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output_path.with_name(f".{output_path.name}.tmp")
    temporary_manifest = output_manifest_path.with_name(f".{output_manifest_path.name}.tmp")
    try:
        temporary_output.write_bytes(artifact_bytes)
        temporary_manifest.write_bytes(manifest_bytes)
        os.replace(temporary_output, output_path)
        os.replace(temporary_manifest, output_manifest_path)
    except OSError as error:
        temporary_output.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
        raise Qwen3TP4WorkloadError(f"cannot publish Qwen3-32B workload: {error}") from error
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-workload", type=Path, default=DEFAULT_SOURCE_WORKLOAD)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--equivalence", type=Path, default=DEFAULT_EQUIVALENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output-manifest", type=Path, default=DEFAULT_OUTPUT_MANIFEST)
    parser.add_argument("--provider-source-revision", required=True)
    parser.add_argument("--provider-source-revision-status", required=True)
    parser.add_argument(
        "--provider-source-path",
        type=Path,
        default=Path("python/moonkvsim/aegiskv/qwen3_32b_tp4_duration.py"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    manifest = derive_qwen3_32b_tp4_workload(
        source_workload_path=args.source_workload,
        source_manifest_path=args.source_manifest,
        equivalence_path=args.equivalence,
        output_path=args.output,
        output_manifest_path=args.output_manifest,
        provider_source_revision=args.provider_source_revision,
        provider_source_revision_status=args.provider_source_revision_status,
        provider_source_path=args.provider_source_path,
        artifact_declared_path=args.output.as_posix(),
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
