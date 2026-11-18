"""Frozen real-trace workload preparation for AegisKV E2 experiments.

The committed artifact intentionally contains only the normalized metadata and
workflow-local source hash-block identifiers already present in the locked
Weka trace.  It never manufactures text, token IDs, parents, or context length.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from moonkvsim.common.hash import sha256_json
from moonkvsim.workload.causal_trace import load_normalized_trace_records

EXPECTED_NORMALIZED_SHA256 = (
    "0a1c37deea32f2c393ba7d8d2d9a7c5629854b874b01ace8953140ad889f6d54"
)
EXPECTED_NORMALIZED_RECORDS = 46_142
SELECTED_WORKFLOW_IDS = (
    "002001296e8a8c38ad9d7cc436d691afc602",
    "0196085d85d2075a50b74cd8795ffbdcea9a",
)


@dataclass(frozen=True, slots=True)
class ContextBucket:
    name: str
    lower_exclusive: int
    upper_inclusive: int

    def contains(self, context_tokens: int) -> bool:
        return self.lower_exclusive < context_tokens <= self.upper_inclusive


CONTEXT_BUCKETS = (
    ContextBucket("8k", 0, 8_192),
    ContextBucket("32k", 8_192, 32_768),
    ContextBucket("64k", 32_768, 65_536),
    ContextBucket("96k", 65_536, 98_304),
    ContextBucket("128k", 98_304, 131_072),
)


class WorkloadPreparationError(ValueError):
    """Raised when the locked source or selected workload fails closed."""


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def context_tokens(record: Mapping[str, Any]) -> int:
    prompt = record.get("prompt_tokens")
    output = record.get("output_tokens")
    total = record.get("total_model_tokens")
    if type(prompt) is not int or type(output) is not int or type(total) is not int:
        raise WorkloadPreparationError("token counts must be integer fields")
    if prompt < 0 or output < 0 or total != prompt + output:
        raise WorkloadPreparationError(
            "total_model_tokens must equal prompt_tokens + output_tokens"
        )
    return total


def bucket_name_for(context_length: int) -> str:
    matches = [bucket.name for bucket in CONTEXT_BUCKETS if bucket.contains(context_length)]
    if len(matches) != 1:
        raise WorkloadPreparationError(
            f"context length {context_length} is outside the frozen bucket partition"
        )
    return matches[0]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_selected_records(source_path: Path) -> tuple[list[dict[str, Any]], int]:
    selected_ids = set(SELECTED_WORKFLOW_IDS)
    selected: list[dict[str, Any]] = []
    source_records = 0
    with source_path.open("r", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                raise WorkloadPreparationError(f"source line {line_number} is blank")
            source_records += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise WorkloadPreparationError(
                    f"source line {line_number} is invalid JSON: {error}"
                ) from error
            if not isinstance(record, dict):
                raise WorkloadPreparationError(f"source line {line_number} is not an object")
            if record.get("workflow_id") in selected_ids:
                selected.append(record)
    return selected, source_records


def _audit_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise WorkloadPreparationError("selected workload is empty")
    # Keep scope failures distinct from the lower-level JSON-schema error so
    # callers receive the evidence-boundary reason that made the row invalid.
    for record in records:
        if record.get("synthetic") is not False or record.get("truncated") is not False:
            raise WorkloadPreparationError("synthetic or truncated records are forbidden")
        if record.get("model_length_guard_passed") is not True:
            raise WorkloadPreparationError("every selected record must pass the 131072 guard")
    # This validates duplicate/missing/cross-workflow parents, release rules and cycles.
    trace = load_normalized_trace_records(records)
    selected_workflows = sorted({span.workflow_id for span in trace.spans})
    if selected_workflows != sorted(SELECTED_WORKFLOW_IDS):
        raise WorkloadPreparationError(
            f"selected workflows differ from the frozen set: {selected_workflows}"
        )

    bucket_counts: Counter[str] = Counter()
    workflow_bucket_counts: dict[str, Counter[str]] = defaultdict(Counter)
    workflow_span_counts: Counter[str] = Counter()
    agent_ids: set[str] = set()
    min_context = 131_073
    max_context = -1
    source_hash_block_count = 0
    inferred_edge_count = 0
    observed_edge_count = 0
    for record in records:
        if record.get("schema") != "moonkvsim.multi_agent_trace.v1":
            raise WorkloadPreparationError("selected record has an unexpected schema")
        if record.get("token_count_mode") != "source_hash_blocks_64":
            raise WorkloadPreparationError("selected records must use source_hash_blocks_64")
        if record.get("hash_id_scope") != "within_workflow_only":
            raise WorkloadPreparationError("source hash identity must remain workflow-local")
        hashes = record.get("source_hash_ids")
        if not isinstance(hashes, list) or not all(type(item) is int for item in hashes):
            raise WorkloadPreparationError("source_hash_ids must be an integer array")
        if len(hashes) != (int(record["prompt_tokens"]) + 63) // 64:
            raise WorkloadPreparationError("source_hash_ids do not cover prompt source blocks")
        length = context_tokens(record)
        if length > 131_072:
            raise WorkloadPreparationError("selected context exceeds the frozen model guard")
        bucket = bucket_name_for(length)
        workflow_id = str(record["workflow_id"])
        bucket_counts[bucket] += 1
        workflow_bucket_counts[workflow_id][bucket] += 1
        workflow_span_counts[workflow_id] += 1
        agent_ids.add(str(record["agent_id"]))
        min_context = min(min_context, length)
        max_context = max(max_context, length)
        source_hash_block_count += len(hashes)
        for edge in record["parent_edges"]:
            if edge["origin"] == "observed":
                observed_edge_count += 1
            elif edge["origin"] == "inferred":
                inferred_edge_count += 1

    expected_bucket_names = [bucket.name for bucket in CONTEXT_BUCKETS]
    missing_buckets = [name for name in expected_bucket_names if bucket_counts[name] == 0]
    if missing_buckets:
        raise WorkloadPreparationError(f"selected workload misses buckets: {missing_buckets}")

    return {
        "status": "pass",
        "closed_causal_dag": True,
        "workflow_count": len(selected_workflows),
        "workflow_ids": selected_workflows,
        "span_count": len(records),
        "workflow_span_counts": {
            workflow_id: workflow_span_counts[workflow_id]
            for workflow_id in selected_workflows
        },
        "agent_count": len(agent_ids),
        "context_tokens": {"min": min_context, "max": max_context},
        "context_bucket_counts": {
            bucket.name: bucket_counts[bucket.name] for bucket in CONTEXT_BUCKETS
        },
        "workflow_counts_by_bucket": {
            bucket.name: sum(
                workflow_bucket_counts[workflow_id][bucket.name] > 0
                for workflow_id in selected_workflows
            )
            for bucket in CONTEXT_BUCKETS
        },
        "parent_edges": {
            "observed": observed_edge_count,
            "inferred": inferred_edge_count,
            "missing": 0,
        },
        "source_hash_block_count": source_hash_block_count,
        "synthetic_count": 0,
        "truncated_count": 0,
        "padding_count": 0,
        "overflow_count": 0,
    }


def prepare_experiment_workload(
    *,
    source_path: Path,
    output_path: Path,
    manifest_path: Path,
    expected_source_sha256: str = EXPECTED_NORMALIZED_SHA256,
    expected_source_records: int = EXPECTED_NORMALIZED_RECORDS,
) -> dict[str, Any]:
    """Select, audit and publish the frozen two-workflow experiment input."""

    if not source_path.is_file():
        raise WorkloadPreparationError(f"normalized source does not exist: {source_path}")
    source_sha256 = _sha256_file(source_path)
    if source_sha256 != expected_source_sha256:
        raise WorkloadPreparationError(
            f"normalized source sha256 mismatch: {source_sha256} != {expected_source_sha256}"
        )
    records, source_record_count = _load_selected_records(source_path)
    if source_record_count != expected_source_records:
        raise WorkloadPreparationError(
            f"normalized source record count mismatch: {source_record_count} "
            f"!= {expected_source_records}"
        )
    audit = _audit_records(records)

    output_bytes = b"".join(canonical_json_bytes(record) for record in records)
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output_bytes)

    manifest: dict[str, Any] = {
        "schema": "moonkvsim.aegiskv.experiment_workload_manifest.v1",
        "status": "pass",
        "evidence": {
            "class": "E2",
            "scope": "modeled/preliminary",
            "calibration": "not_calibrated",
            "physical_execution": False,
            "paper_ready": False,
        },
        "source": {
            "dataset": "semianalysisai/cc-traces-weka-062126",
            "repository_revision": "23f152f6f0f9399a85901b89a6458def0ef16729",
            "license": "Apache-2.0",
            "normalized_sha256": source_sha256,
            "normalized_record_count": source_record_count,
            "normalizer_version": "moonkvsim.weka.v1.1",
            "token_count_mode": "source_hash_blocks_64",
            "target_tokenizer_equivalence": False,
            "content_availability": "source_hash_ids_only",
            "collection_interval": "not_disclosed_by_reviewed_public_sources",
        },
        "selection": {
            "kind": "complete_workflows_frozen_by_id",
            "workflow_ids": list(SELECTED_WORKFLOW_IDS),
            "guard": "prompt_tokens + output_tokens <= 131072",
            "no_span_slicing": True,
            "no_cross_workflow_concatenation": True,
            "no_truncation": True,
            "no_padding": True,
            "no_synthesis": True,
            "audit": audit,
        },
        "artifact": {
            "path": output_path.as_posix(),
            "sha256": output_sha256,
            "size_bytes": len(output_bytes),
            "record_count": len(records),
            "canonical_serialization": "utf8-jsonl-sort-keys-no-whitespace",
            "semantic_fingerprint": sha256_json(
                {
                    "source_sha256": source_sha256,
                    "workflow_ids": list(SELECTED_WORKFLOW_IDS),
                    "span_ids": [record["span_id"] for record in records],
                }
            ),
        },
        "formal_blockers": [
            "source trace collection interval is not disclosed",
            "source hash blocks are not target-tokenizer-equivalent token IDs",
            "no physical timing calibration was requested or performed",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    return manifest


def load_experiment_records(path: Path) -> list[dict[str, Any]]:
    """Load and re-audit a committed experiment workload artifact."""

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                raise WorkloadPreparationError(f"workload line {line_number} is blank")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise WorkloadPreparationError(f"workload line {line_number} is not an object")
            records.append(value)
    _audit_records(records)
    return records


def bucket_records(
    records: Iterable[Mapping[str, Any]], bucket_name: str
) -> tuple[Mapping[str, Any], ...]:
    if bucket_name not in {bucket.name for bucket in CONTEXT_BUCKETS}:
        raise WorkloadPreparationError(f"unknown context bucket: {bucket_name}")
    return tuple(
        record
        for record in records
        if bucket_name_for(context_tokens(record)) == bucket_name
    )
