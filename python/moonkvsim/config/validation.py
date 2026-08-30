"""Draft-2020-12 schema validation with MoonKVSim semantic guards.

JSON Schema closes every declared object against unknown fields.  The semantic
checks in this module cover relationships that are awkward or impossible to
express in JSON Schema, such as token sums, edge consistency, and the complete
absence of persistent-storage vocabulary from a deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import Any, Final

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError, ValidationError  # type: ignore[import-untyped]

SchemaInstance = Mapping[str, Any]

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
_SCHEMA_DIRECTORY: Final = _REPOSITORY_ROOT / "schemas"
_SCHEMA_FILES: Final[dict[str, str]] = {
    "requests": "requests.schema.json",
    "failure": "failure.schema.json",
    "deployment": "deployment.schema.json",
    "multi-agent-trace": "multi-agent-trace.schema.json",
    "predictor-held-out-residual-report": (
        "predictor-held-out-residual-report.schema.json"
    ),
    "predictor-profile-selection": "predictor-profile-selection.schema.json",
    "predictor-residual-thresholds": "predictor-residual-thresholds.schema.json",
    "run-manifest": "run-manifest.schema.json",
}
_SCHEMA_IDS: Final[dict[str, str]] = {
    "moonkvsim.requests.v1": "requests",
    "moonkvsim.failure.v1": "failure",
    "moonkvsim.deployment.v1": "deployment",
    "moonkvsim.multi_agent_trace.v1": "multi-agent-trace",
    "moonkvsim.aiconfigurator-held-out-residual-report.v1": (
        "predictor-held-out-residual-report"
    ),
    "moonkvsim.aiconfigurator-profile-selection.v1": "predictor-profile-selection",
    "moonkvsim.aiconfigurator-residual-thresholds.v1": (
        "predictor-residual-thresholds"
    ),
    "moonkvsim.run_manifest.v1": "run-manifest",
}
_FORBIDDEN_DEPLOYMENT_TERMS: Final = (
    "SSD",
    "NVME",
    "LOCALDISK",
    "STORESSD",
    "PERSISTENCE",
)
_SOURCE_HASH_IDS_ELISION_SCHEMA_SHA256: Final = (
    "65af89d4b8475ab72c26eee1158369541f5cfb028aac28fc98e4f8acf7438cee"
)


class SchemaValidationError(ValueError):
    """Raised when a document fails structural or semantic validation."""

    def __init__(self, schema_name: str, messages: Sequence[str]) -> None:
        self.schema_name = schema_name
        self.messages = tuple(messages)
        detail = "; ".join(self.messages)
        super().__init__(f"{schema_name} validation failed: {detail}")


def _canonical_schema_name(schema_name: str) -> str:
    candidate = schema_name.removesuffix(".schema.json")
    candidate = _SCHEMA_IDS.get(candidate, candidate)
    if candidate not in _SCHEMA_FILES:
        choices = ", ".join(sorted(_SCHEMA_FILES))
        raise ValueError(f"unknown schema {schema_name!r}; expected one of: {choices}")
    return candidate


@cache
def load_schema(schema_name: str) -> dict[str, Any]:
    """Load and meta-validate one repository-owned JSON Schema."""

    canonical_name = _canonical_schema_name(schema_name)
    path = _SCHEMA_DIRECTORY / _SCHEMA_FILES[canonical_name]
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot load schema {path}: {error}") from error
    if not isinstance(document, dict):
        raise RuntimeError(f"schema {path} is not a JSON object")
    try:
        Draft202012Validator.check_schema(document)
    except SchemaError as error:
        raise RuntimeError(f"invalid draft-2020-12 schema {path}: {error.message}") from error
    return document


@cache
def _format_checker() -> FormatChecker:
    """Return the one read-only format checker shared by cached validators."""

    return FormatChecker()


@cache
def _validator_for_canonical_schema(canonical_name: str) -> Draft202012Validator:
    """Build one reusable validator for a canonical repository schema name."""

    return Draft202012Validator(
        load_schema(canonical_name),
        format_checker=_format_checker(),
    )


def _schema_validator(schema_name: str) -> Draft202012Validator:
    return _validator_for_canonical_schema(_canonical_schema_name(schema_name))


def _source_hash_ids_schema_supports_elision(schema: Mapping[str, Any]) -> bool:
    """Enable elision only for the fully reviewed multi-agent schema."""

    if type(schema) is not dict:
        return False
    try:
        canonical = json.dumps(
            schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return False
    return hashlib.sha256(canonical).hexdigest() == (
        _SOURCE_HASH_IDS_ELISION_SCHEMA_SHA256
    )


@cache
def _source_hash_ids_elision_enabled() -> bool:
    """Cache the process-local full-schema drift gate."""

    return _source_hash_ids_schema_supports_elision(load_schema("multi-agent-trace"))


def _schema_validation_instance(
    instance: SchemaInstance,
    canonical_name: str,
) -> SchemaInstance:
    """Elide already-proven valid source-hash items from schema traversal only."""

    if canonical_name != "multi-agent-trace" or type(instance) is not dict:
        return instance
    if not _source_hash_ids_elision_enabled():
        return instance
    hash_ids = instance.get("source_hash_ids")
    if (
        type(hash_ids) is not list
        or not hash_ids
        or not all(type(item) is int and item >= 0 for item in hash_ids)
    ):
        return instance
    validation_instance = instance.copy()
    validation_instance["source_hash_ids"] = []
    return validation_instance


def _json_path(error: ValidationError) -> str:
    if not error.absolute_path:
        return "$"
    parts = [str(part) for part in error.absolute_path]
    return "$." + ".".join(parts)


def _schema_errors(instance: SchemaInstance, schema_name: str) -> list[str]:
    canonical_name = _canonical_schema_name(schema_name)
    validator = _schema_validator(canonical_name)
    validation_instance = _schema_validation_instance(instance, canonical_name)
    errors = sorted(
        validator.iter_errors(validation_instance),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
    )
    return [f"{_json_path(error)}: {error.message}" for error in errors]


def _normalized_storage_term(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _find_forbidden_storage_terms(value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            normalized_key = _normalized_storage_term(key_text)
            if any(term in normalized_key for term in _FORBIDDEN_DEPLOYMENT_TERMS):
                errors.append(f"{path}.{key_text}: forbidden persistent-storage field")
            errors.extend(_find_forbidden_storage_terms(child, f"{path}.{key_text}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_find_forbidden_storage_terms(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        normalized_value = _normalized_storage_term(value)
        if any(term in normalized_value for term in _FORBIDDEN_DEPLOYMENT_TERMS):
            errors.append(f"{path}: forbidden persistent-storage value {value!r}")
    return errors


def _multi_agent_span_errors(instance: SchemaInstance) -> list[str]:
    errors: list[str] = []
    prompt_tokens = instance.get("prompt_tokens")
    output_tokens = instance.get("output_tokens")
    total_tokens = instance.get("total_model_tokens")
    block_size = instance.get("source_block_size_tokens")
    hash_ids = instance.get("source_hash_ids")
    if (
        isinstance(prompt_tokens, int)
        and isinstance(output_tokens, int)
        and isinstance(total_tokens, int)
        and prompt_tokens + output_tokens != total_tokens
    ):
        errors.append("$.total_model_tokens: must equal prompt_tokens + output_tokens")
    if (
        isinstance(prompt_tokens, int)
        and isinstance(block_size, int)
        and isinstance(hash_ids, list)
        and len(hash_ids) * block_size != prompt_tokens
    ):
        errors.append(
            "$.prompt_tokens: must equal len(source_hash_ids) * source_block_size_tokens"
        )
    cached_tokens = instance.get("cached_prefix_tokens")
    if isinstance(cached_tokens, int) and isinstance(prompt_tokens, int):
        if cached_tokens > prompt_tokens:
            errors.append("$.cached_prefix_tokens: cannot exceed prompt_tokens")
        if isinstance(block_size, int) and cached_tokens % block_size != 0:
            errors.append("$.cached_prefix_tokens: must align to source_block_size_tokens")

    submit_ns = instance.get("observed_submit_ns")
    finish_ns = instance.get("observed_finish_ns")
    api_ns = instance.get("recorded_api_time_ns")
    if (
        isinstance(submit_ns, int)
        and isinstance(finish_ns, int)
        and isinstance(api_ns, int)
        and finish_ns != submit_ns + api_ns
    ):
        errors.append(
            "$.observed_finish_ns: must equal observed_submit_ns + recorded_api_time_ns"
        )

    parent_ids = instance.get("parent_span_ids")
    parent_edges = instance.get("parent_edges")
    origin = instance.get("parent_edge_origin")
    confidence = instance.get("parent_edge_confidence")
    if isinstance(parent_ids, list) and isinstance(parent_edges, list):
        edge_ids = [
            edge.get("parent_span_id")
            for edge in parent_edges
            if isinstance(edge, Mapping)
        ]
        if parent_ids != edge_ids:
            errors.append("$.parent_edges: parent_span_ids must exactly match edge order")
        if not parent_ids:
            if origin != "none" or confidence is not None:
                errors.append(
                    "$.parent_edge_origin: root spans require origin=none and confidence=null"
                )
        else:
            origins = {
                edge.get("origin") for edge in parent_edges if isinstance(edge, Mapping)
            }
            expected_origin = next(iter(origins)) if len(origins) == 1 else "mixed"
            if origin != expected_origin:
                errors.append(
                    f"$.parent_edge_origin: expected {expected_origin!r} from parent_edges"
                )
            edge_confidences = [
                edge.get("confidence") for edge in parent_edges if isinstance(edge, Mapping)
            ]
            numeric_confidences = [
                value for value in edge_confidences if isinstance(value, (int, float))
            ]
            if numeric_confidences and confidence != min(numeric_confidences):
                errors.append(
                    "$.parent_edge_confidence: must be the minimum parent-edge confidence"
                )

    role = instance.get("agent_role")
    group = instance.get("subagent_group")
    if role == "subagent" and group is None:
        errors.append("$.subagent_group: required for subagent spans")
    if role == "main" and group is not None:
        errors.append("$.subagent_group: must be null or absent for main spans")
    return errors


def _failure_errors(instance: SchemaInstance) -> list[str]:
    events = instance.get("events")
    if not isinstance(events, list):
        return []
    failure_ids = [event.get("failure_id") for event in events if isinstance(event, Mapping)]
    if len(failure_ids) != len(set(failure_ids)):
        return ["$.events: failure_id values must be unique"]
    return []


def _run_manifest_errors(instance: SchemaInstance) -> list[str]:
    errors: list[str] = []
    virtual_time = instance.get("virtual_time")
    if isinstance(virtual_time, Mapping):
        start_ns = virtual_time.get("start_ns")
        end_ns = virtual_time.get("end_ns")
        if isinstance(start_ns, int) and isinstance(end_ns, int) and end_ns < start_ns:
            errors.append("$.virtual_time.end_ns: cannot precede start_ns")
    completeness = instance.get("result_completeness")
    if isinstance(completeness, Mapping):
        status = completeness.get("status")
        missing = completeness.get("missing_artifacts")
        if status == "complete" and missing:
            errors.append("$.result_completeness: complete status requires no missing artifacts")
        if status == "incomplete" and isinstance(missing, list) and not missing:
            errors.append(
                "$.result_completeness: incomplete status requires at least one "
                "missing artifact"
            )
    return errors


def _semantic_errors(instance: SchemaInstance, schema_name: str) -> list[str]:
    if schema_name == "deployment":
        return _find_forbidden_storage_terms(instance)
    if schema_name == "multi-agent-trace":
        return _multi_agent_span_errors(instance)
    if schema_name == "failure":
        return _failure_errors(instance)
    if schema_name == "run-manifest":
        return _run_manifest_errors(instance)
    return []


def validate_instance(instance: SchemaInstance, schema_name: str) -> None:
    """Validate a mapping and raise one deterministic aggregate error on failure."""

    canonical_name = _canonical_schema_name(schema_name)
    errors = _schema_errors(instance, canonical_name)
    if not errors:
        errors.extend(_semantic_errors(instance, canonical_name))
    if errors:
        raise SchemaValidationError(canonical_name, errors)


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SchemaValidationError("json", [f"{path}: {error}"]) from error
    if not isinstance(document, dict):
        raise SchemaValidationError("json", [f"{path}: top-level value must be an object"])
    return document


def validate_file(path: str | Path, schema_name: str | None = None) -> dict[str, Any]:
    """Read and validate a JSON file, inferring its schema from ``schema`` when omitted."""

    resolved_path = Path(path)
    document = _load_json_object(resolved_path)
    requested_schema = schema_name
    if requested_schema is None:
        discriminator = document.get("schema")
        if not isinstance(discriminator, str):
            raise SchemaValidationError("unknown", ["$.schema: missing string discriminator"])
        requested_schema = discriminator
    validate_instance(document, requested_schema)
    return document


def validate_requests_config(instance: SchemaInstance) -> None:
    validate_instance(instance, "requests")


def validate_failure_config(instance: SchemaInstance) -> None:
    validate_instance(instance, "failure")


def validate_deployment_config(instance: SchemaInstance) -> None:
    validate_instance(instance, "deployment")


def validate_trace_span(instance: SchemaInstance) -> None:
    validate_instance(instance, "multi-agent-trace")


def validate_run_manifest(instance: SchemaInstance) -> None:
    validate_instance(instance, "run-manifest")


def validate_jsonl_trace(path: str | Path) -> dict[str, int]:
    """Stream-validate trace records, then check parent scope, missing IDs, and cycles."""

    resolved_path = Path(path)
    workflow_by_span: dict[str, str] = {}
    parents_by_span: dict[str, tuple[str, ...]] = {}
    children: dict[str, list[str]] = defaultdict(list)
    record_count = 0
    try:
        with resolved_path.open("r", encoding="utf-8", newline="") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise SchemaValidationError(
                        "multi-agent-trace", [f"line {line_number}: blank lines are forbidden"]
                    )
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise SchemaValidationError(
                        "multi-agent-trace", [f"line {line_number}: {error}"]
                    ) from error
                if not isinstance(record, dict):
                    raise SchemaValidationError(
                        "multi-agent-trace", [f"line {line_number}: record must be an object"]
                    )
                try:
                    validate_trace_span(record)
                except SchemaValidationError as error:
                    messages = [f"line {line_number}: {message}" for message in error.messages]
                    raise SchemaValidationError("multi-agent-trace", messages) from error
                span_id = str(record["span_id"])
                if span_id in workflow_by_span:
                    raise SchemaValidationError(
                        "multi-agent-trace", [f"line {line_number}: duplicate span_id {span_id!r}"]
                    )
                workflow_by_span[span_id] = str(record["workflow_id"])
                parent_ids = tuple(str(parent_id) for parent_id in record["parent_span_ids"])
                parents_by_span[span_id] = parent_ids
                for parent_id in parent_ids:
                    children[parent_id].append(span_id)
                record_count += 1
    except OSError as error:
        raise SchemaValidationError("multi-agent-trace", [f"{resolved_path}: {error}"]) from error

    relationship_errors: list[str] = []
    for span_id, parent_ids in parents_by_span.items():
        for parent_id in parent_ids:
            if parent_id not in workflow_by_span:
                relationship_errors.append(f"span {span_id!r}: missing parent {parent_id!r}")
            elif workflow_by_span[parent_id] != workflow_by_span[span_id]:
                relationship_errors.append(
                    f"span {span_id!r}: parent {parent_id!r} crosses workflow"
                )
    if relationship_errors:
        raise SchemaValidationError("multi-agent-trace", sorted(relationship_errors))

    indegree = {span_id: len(parent_ids) for span_id, parent_ids in parents_by_span.items()}
    ready = deque(sorted(span_id for span_id, degree in indegree.items() if degree == 0))
    visited = 0
    while ready:
        parent_id = ready.popleft()
        visited += 1
        for child_id in sorted(children[parent_id]):
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(child_id)
    if visited != record_count:
        cyclic = sorted(span_id for span_id, degree in indegree.items() if degree > 0)
        raise SchemaValidationError(
            "multi-agent-trace", [f"cycle detected among spans: {', '.join(cyclic[:10])}"]
        )
    return {"record_count": record_count, "workflow_count": len(set(workflow_by_span.values()))}


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="JSON config/manifest or normalized JSONL trace")
    parser.add_argument("--schema", choices=sorted(_SCHEMA_FILES))
    parser.add_argument(
        "--jsonl-trace",
        action="store_true",
        help="stream and cross-record validate a multi-agent JSONL trace",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        if args.jsonl_trace:
            summary = validate_jsonl_trace(args.path)
            print(json.dumps(summary, sort_keys=True))
        else:
            document = validate_file(args.path, args.schema)
            print(json.dumps({"schema": document["schema"], "status": "pass"}, sort_keys=True))
    except (SchemaValidationError, ValueError) as error:
        print(str(error))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
