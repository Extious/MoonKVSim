#!/usr/bin/env python3
"""Run the Qwen3-8B C=16 no-failure backup-overhead diagnostic.

This runner is intentionally separate from the failure paper sweep.  It executes
the frozen 160-workflow workload with the same continuous-batching simulator for
Mooncake and AegisKV, but injects no failure.  The output is descriptive evidence:
no effect direction or "negligible overhead" threshold is enforced.

Every run remains modeled, uncalibrated E2 evidence.  Full payloads, span details,
Algorithm 2/3 events, transfer ledgers, and flow-rate intervals are retained in one
raw JSON artifact per system and seed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Final, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from moonkvsim.aegiskv.experiment import (
    CellSpec,
    ExperimentError,
    ExperimentVariant,
    Scenario,
    StudyRunResult,
    core_variants,
    run_study_cell,
)
from moonkvsim.aegiskv.experiment_config import (
    default_config_dir,
    load_experiment_configs,
    matrix_seeds,
    model_parameters_from_configs,
    repository_root,
    workflow_concurrency,
    workload_paths,
)
from moonkvsim.aegiskv.experiment_suite import load_frozen_workload
from moonkvsim.aegiskv.formal_algorithm_audit import (
    FormalAlgorithmAuditError,
    audit_continuous_scheduler_evidence,
    audit_formal_algorithm_run,
)
from moonkvsim.common.hash import sha256_json
from moonkvsim.workload.causal_trace import load_normalized_trace_records

SCHEMA: Final = "moonkvsim.aegiskv.no-failure-overhead.v1"
RAW_SCHEMA: Final = "moonkvsim.aegiskv.no-failure-overhead.raw-run.v1"
FAILURE_SCHEMA: Final = "moonkvsim.aegiskv.no-failure-overhead.failure.v1"
DEFAULT_SEEDS: Final = (0, 1, 2, 3, 4)
BASE_CONCURRENCY: Final = 16
EXPECTED_WORKFLOW_COUNT: Final = 160
EXPECTED_RECORD_COUNT: Final = 1_304
VARIANT_IDS: Final = ("vanilla_mooncake_dram", "aegiskv_unified")
AEGISKV_VARIANT_ID: Final = "aegiskv_unified"
MOONCAKE_VARIANT_ID: Final = "vanilla_mooncake_dram"
OUTPUT_FILENAME: Final = "no-failure-overhead.json"
SCHEMA_RELATIVE_PATH: Final = "benchmark/AegisKV/experiments/schemas/aegiskv-no-failure-overhead.schema.json"
PROTECTION_CAUSES: Final = (
    "AEGIS_PEER_HBM_PROTECTION",
    "AEGIS_STORE_DRAM_PROTECTION",
)

_WORKER_RECORDS: Sequence[Mapping[str, Any]] | None = None
_WORKER_VARIANTS: tuple[ExperimentVariant, ExperimentVariant] | None = None
_WORKER_CONTEXT_BUCKET: str | None = None
_WORKER_SOURCE_CONTRACT_FINGERPRINT: str | None = None
_WORKER_WORKLOAD_BINDING: dict[str, Any] | None = None
_WORKER_CONFIG_BINDING_FINGERPRINT: str | None = None
_WORKER_ROOT: Path | None = None


class NoFailureOverheadError(ExperimentError):
    """The no-failure diagnostic failed an exact-input or output invariant."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
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


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("wb") as stream:
        stream.write(_canonical_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _source_paths(root: Path) -> tuple[Path, ...]:
    """Bind the complete Python implementation plus this protocol and lockfiles."""

    candidates = [
        path
        for path in (root / "python/moonkvsim").rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    candidates.extend(
        (
            root / "benchmark/AegisKV/Archived/simulation-qwen3-8b/scripts/run_aegiskv_no_failure_overhead.py",
            root / SCHEMA_RELATIVE_PATH,
            root / "pyproject.toml",
            root / "uv.lock",
        )
    )
    paths = tuple(sorted(set(path.resolve() for path in candidates)))
    if not paths or any(not path.is_file() or path.is_symlink() for path in paths):
        raise NoFailureOverheadError("source contract contains a missing file or symlink")
    return paths


def _source_contract(root: Path) -> dict[str, Any]:
    bindings = {
        path.relative_to(root).as_posix(): _sha256_file(path) for path in _source_paths(root)
    }
    body = {
        "binding_kind": "complete_python_tree_plus_protocol_schema_and_lockfiles",
        "files": bindings,
    }
    return {**body, "fingerprint": sha256_json(body)}


def _config_binding(config_dir: Path) -> dict[str, Any]:
    bindings = {
        name: _sha256_file(config_dir / name)
        for name in ("requests.json", "failure.json", "engine.json")
    }
    return {"files": bindings, "fingerprint": sha256_json(bindings)}


def _git_commit(root: Path) -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = completed.stdout.strip()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise NoFailureOverheadError("Git HEAD is not a lowercase 40-hex commit")
    return commit


def _highest_nonempty_context_bucket(manifest: Mapping[str, Any]) -> str:
    selection = manifest.get("selection")
    audit = selection.get("audit") if isinstance(selection, Mapping) else None
    counts = audit.get("context_bucket_counts") if isinstance(audit, Mapping) else None
    if not isinstance(counts, Mapping):
        raise NoFailureOverheadError("workload manifest lacks context bucket counts")
    ordered = ("8k", "32k", "64k", "96k", "128k")
    nonempty = [
        bucket
        for bucket in ordered
        if type(counts.get(bucket)) is int and cast(int, counts[bucket]) > 0
    ]
    if not nonempty:
        raise NoFailureOverheadError("frozen workload has no non-empty context bucket")
    return nonempty[-1]


def _workflow_order(
    records: Sequence[Mapping[str, Any]],
    *,
    admission_seed: int | None = None,
) -> tuple[str, ...]:
    trace = load_normalized_trace_records(records)
    workflow_roots: dict[str, list[Any]] = {}
    for span in trace.spans:
        if not span.parent_span_ids:
            workflow_roots.setdefault(span.workflow_id, []).append(span)
    if not workflow_roots:
        raise NoFailureOverheadError("frozen workload has no workflow roots")
    ordered = [
        workflow_id
        for workflow_id, _roots in sorted(
            workflow_roots.items(),
            key=lambda item: (
                min(root.observed_submit_ns for root in item[1]),
                (
                    b""
                    if admission_seed is None
                    else hashlib.sha256(
                        f"workflow-admission:{admission_seed}:{item[0]}".encode()
                    ).digest()[:8]
                ),
                min(root.stable_sort_key for root in item[1]),
            ),
        )
    ]
    if len(ordered) != EXPECTED_WORKFLOW_COUNT:
        raise NoFailureOverheadError(
            f"expected {EXPECTED_WORKFLOW_COUNT} workflows, observed {len(ordered)}"
        )
    return tuple(ordered)


def _require_exact_token_records(records: Sequence[Mapping[str, Any]]) -> None:
    for index, record in enumerate(records):
        content = record.get("messages_or_token_ids")
        if (
            not isinstance(content, Mapping)
            or content.get("kind") != "token_ids"
            or not isinstance(content.get("value"), list)
            or not content["value"]
            or any(type(token_id) is not int for token_id in content["value"])
        ):
            raise NoFailureOverheadError(
                f"frozen workload record {index} lacks exact token IDs"
            )


def _select_variants(parameters: object) -> tuple[ExperimentVariant, ExperimentVariant]:
    variants = {
        item.variant_id: item
        for item in core_variants(cast(Any, parameters))
        if item.variant_id in VARIANT_IDS
    }
    if set(variants) != set(VARIANT_IDS):
        raise NoFailureOverheadError("core catalog lacks the exact Mooncake/AegisKV pair")
    return cast(
        tuple[ExperimentVariant, ExperimentVariant],
        tuple(variants[variant_id] for variant_id in VARIANT_IDS),
    )


def _initialize_worker(
    root_text: str,
    config_dir_text: str,
    expected_source_fingerprint: str,
    expected_workload_fingerprint: str,
    expected_config_fingerprint: str,
) -> None:
    global _WORKER_CONFIG_BINDING_FINGERPRINT
    global _WORKER_CONTEXT_BUCKET
    global _WORKER_RECORDS
    global _WORKER_ROOT
    global _WORKER_SOURCE_CONTRACT_FINGERPRINT
    global _WORKER_VARIANTS
    global _WORKER_WORKLOAD_BINDING

    root = Path(root_text).resolve()
    config_dir = Path(config_dir_text).resolve()
    source_contract = _source_contract(root)
    if source_contract["fingerprint"] != expected_source_fingerprint:
        raise NoFailureOverheadError("worker observed source-contract drift")
    config_binding = _config_binding(config_dir)
    if config_binding["fingerprint"] != expected_config_fingerprint:
        raise NoFailureOverheadError("worker observed config drift")
    configs = load_experiment_configs(config_dir, root=root)
    workload_path, manifest_path = workload_paths(configs.requests, root=root)
    records, workload_binding, manifest = load_frozen_workload(
        workload_path,
        manifest_path,
        retain_exact_token_ids=True,
    )
    if workload_binding.fingerprint != expected_workload_fingerprint:
        raise NoFailureOverheadError("worker observed frozen-workload drift")
    _require_exact_token_records(records)
    _WORKER_RECORDS = records
    _WORKER_VARIANTS = _select_variants(model_parameters_from_configs(configs))
    _WORKER_CONTEXT_BUCKET = _highest_nonempty_context_bucket(manifest)
    _WORKER_SOURCE_CONTRACT_FINGERPRINT = expected_source_fingerprint
    _WORKER_WORKLOAD_BINDING = workload_binding.to_dict()
    _WORKER_CONFIG_BINDING_FINGERPRINT = expected_config_fingerprint
    _WORKER_ROOT = root


def _integer(value: object, path: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise NoFailureOverheadError(f"{path} must be an integer >= {minimum}")
    return value


def _positive_number(value: object, path: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise NoFailureOverheadError(f"{path} must be a finite number > 0")
    return float(value)


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NoFailureOverheadError(f"{path} must be an object")
    return cast(Mapping[str, Any], value)


def _sequence(value: object, path: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise NoFailureOverheadError(f"{path} must be an array")
    return cast(Sequence[Any], value)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _warmup_definition(
    details: Sequence[Mapping[str, Any]],
    bootstrap_workflow_ids: Sequence[str],
) -> dict[str, Any]:
    first_release: dict[str, int] = {}
    first_compute: dict[str, int] = {}
    for index, detail in enumerate(details):
        workflow_id = detail.get("workflow_id")
        if not isinstance(workflow_id, str):
            raise NoFailureOverheadError(f"span_details[{index}].workflow_id is invalid")
        released_ns = _integer(detail.get("released_ns"), f"span_details[{index}].released_ns")
        compute_start_ns = _integer(
            detail.get("compute_start_ns"),
            f"span_details[{index}].compute_start_ns",
        )
        first_release[workflow_id] = min(first_release.get(workflow_id, released_ns), released_ns)
        first_compute[workflow_id] = min(
            first_compute.get(workflow_id, compute_start_ns), compute_start_ns
        )
    bootstrap = tuple(bootstrap_workflow_ids)
    if len(bootstrap) != BASE_CONCURRENCY or any(
        workflow_id not in first_compute for workflow_id in bootstrap
    ):
        raise NoFailureOverheadError("bootstrap cohort is incomplete in span details")
    warmup_end_ns = max(first_compute[workflow_id] for workflow_id in bootstrap)
    return {
        "bootstrap_workflow_ids": list(bootstrap),
        "bootstrap_workflow_count": len(bootstrap),
        "steady_state_workflow_count": len(first_compute) - len(bootstrap),
        "warmup_start_ns": min(first_release.values()),
        "warmup_end_ns": warmup_end_ns,
        "definition": (
            "bootstrap cohort is the first C=16 workflows in causal admission order; "
            "warmup ends when every bootstrap workflow has started its first compute"
        ),
        "warmup_exclusion_applied_to_primary_metrics": False,
    }


def _protection_summary(
    payload: Mapping[str, Any],
    representative: Mapping[str, Any],
    details: Sequence[Mapping[str, Any]],
    warmup: Mapping[str, Any],
) -> dict[str, Any]:
    metrics = _mapping(payload.get("metrics"), "payload.metrics")
    resource = _mapping(metrics.get("resource_cost"), "payload.metrics.resource_cost")
    if resource.get("transfer_byte_conservation_valid") is not True:
        raise NoFailureOverheadError("transfer byte accounting did not conserve")
    transfers = _sequence(representative.get("transfers"), "representative.transfers")
    flow_intervals = _sequence(
        representative.get("flow_rate_intervals"),
        "representative.flow_rate_intervals",
    )
    rate_resources = _mapping(
        _mapping(payload.get("resource_model"), "payload.resource_model").get("rate_resources"),
        "payload.resource_model.rate_resources",
    )
    span_to_workflow = {str(detail["span_id"]): str(detail["workflow_id"]) for detail in details}
    bootstrap_ids = set(cast(Sequence[str], warmup["bootstrap_workflow_ids"]))
    warmup_end_ns = _integer(warmup.get("warmup_end_ns"), "warmup.warmup_end_ns")
    by_phase = Counter[str]()
    bytes_by_phase = Counter[str]()
    by_cohort = Counter[str]()
    bytes_by_cohort = Counter[str]()
    terminal_state_counts = Counter[str]()
    transfer_rows: list[Mapping[str, Any]] = []
    for index, raw_transfer in enumerate(transfers):
        transfer = _mapping(raw_transfer, f"representative.transfers[{index}]")
        if transfer.get("cause") not in PROTECTION_CAUSES:
            continue
        status = transfer.get("status")
        if status not in {"COMMITTED", "ABORTED"}:
            raise NoFailureOverheadError("protection transfer is not terminal")
        ready_ns = _integer(transfer.get("ready_ns"), f"transfer[{index}].ready_ns")
        size = _integer(transfer.get("bytes"), f"transfer[{index}].bytes")
        phase = "bootstrap_warmup" if ready_ns < warmup_end_ns else "steady_state"
        by_phase[phase] += 1
        bytes_by_phase[phase] += size
        span_id = transfer.get("span_id")
        workflow_id = span_to_workflow.get(str(span_id))
        if workflow_id is None:
            raise NoFailureOverheadError("protection transfer lacks a known span owner")
        cohort = "bootstrap_initial_admission" if workflow_id in bootstrap_ids else "steady_state"
        by_cohort[cohort] += 1
        bytes_by_cohort[cohort] += size
        terminal_state_counts[str(status)] += 1
        transfer_rows.append(transfer)

    cause_maps = {
        name: _mapping(resource.get(name), f"payload.metrics.resource_cost.{name}")
        for name in (
            "submitted_bytes_by_cause",
            "cause_bytes",
            "aborted_bytes_by_cause",
            "queue_wait_ns_by_cause",
            "service_time_ns_by_cause",
            "copy_engine_busy_ns",
            "fabric_busy_ns",
        )
    }

    def cause_total(name: str) -> int:
        values = cause_maps[name]
        return sum(_integer(values.get(cause, 0), f"{name}.{cause}") for cause in PROTECTION_CAUSES)

    record_submitted = sum(_integer(item.get("bytes"), "transfer.bytes") for item in transfer_rows)
    record_transferred = sum(
        _integer(item.get("transferred_bytes"), "transfer.transferred_bytes")
        for item in transfer_rows
    )
    record_aborted = sum(
        _integer(item.get("aborted_bytes"), "transfer.aborted_bytes") for item in transfer_rows
    )
    record_queue_wait = sum(
        _integer(item.get("start_ns"), "transfer.start_ns")
        - _integer(item.get("ready_ns"), "transfer.ready_ns")
        for item in transfer_rows
    )
    record_service = sum(
        _integer(item.get("end_ns"), "transfer.end_ns")
        - _integer(item.get("start_ns"), "transfer.start_ns")
        for item in transfer_rows
    )
    expected = {
        "submitted_bytes_by_cause": record_submitted,
        "cause_bytes": record_transferred,
        "aborted_bytes_by_cause": record_aborted,
        "queue_wait_ns_by_cause": record_queue_wait,
        "service_time_ns_by_cause": record_service,
    }
    for name, observed in expected.items():
        if cause_total(name) != observed:
            raise NoFailureOverheadError(f"protection transfer aggregate drifted: {name}")

    contended_interval_count = 0
    contended_interval_ns_sum = 0
    protection_interval_count = 0
    allocated_rates: list[float] = []
    for index, raw_interval in enumerate(flow_intervals):
        interval = _mapping(raw_interval, f"representative.flow_rate_intervals[{index}]")
        if interval.get("cause") not in PROTECTION_CAUSES:
            continue
        protection_interval_count += 1
        start_ns = _integer(interval.get("start_ns"), f"flow[{index}].start_ns")
        end_ns = _integer(interval.get("end_ns"), f"flow[{index}].end_ns")
        if end_ns < start_ns:
            raise NoFailureOverheadError("protection flow interval runs backward")
        allocated = _positive_number(
            interval.get("allocated_rate_bytes_per_second"),
            f"flow[{index}].allocated_rate_bytes_per_second",
        )
        resource_ids = _sequence(
            interval.get("path_resource_ids"), f"flow[{index}].path_resource_ids"
        )
        if not resource_ids or any(not isinstance(item, str) for item in resource_ids):
            raise NoFailureOverheadError("protection flow lacks rate resources")
        isolated_ceiling = min(
            _positive_number(
                rate_resources.get(str(resource_id)),
                f"rate_resources.{resource_id}",
            )
            for resource_id in resource_ids
        )
        if allocated > isolated_ceiling:
            raise NoFailureOverheadError("flow allocation exceeds an isolated bottleneck")
        allocated_rates.append(allocated)
        if allocated < isolated_ceiling:
            contended_interval_count += 1
            contended_interval_ns_sum += end_ns - start_ns

    return {
        "protection_causes": list(PROTECTION_CAUSES),
        "transfer_count": len(transfer_rows),
        "terminal_state_counts": dict(sorted(terminal_state_counts.items())),
        "submitted_bytes": record_submitted,
        "transferred_bytes": record_transferred,
        "aborted_bytes": record_aborted,
        "queue_wait_ns_sum": record_queue_wait,
        "service_time_ns_sum": record_service,
        "copy_engine_busy_ns_sum": cause_total("copy_engine_busy_ns"),
        "fabric_busy_ns_sum": cause_total("fabric_busy_ns"),
        "by_time_phase": {
            phase: {
                "transfer_count": by_phase[phase],
                "submitted_bytes": bytes_by_phase[phase],
            }
            for phase in ("bootstrap_warmup", "steady_state")
        },
        "by_workflow_cohort": {
            cohort: {
                "transfer_count": by_cohort[cohort],
                "submitted_bytes": bytes_by_cohort[cohort],
            }
            for cohort in ("bootstrap_initial_admission", "steady_state")
        },
        "bandwidth_competition": {
            "definition": "allocated_rate_below_minimum_path_resource_capacity",
            "protection_flow_interval_count": protection_interval_count,
            "contended_flow_interval_count": contended_interval_count,
            "contended_flow_interval_ns_sum": contended_interval_ns_sum,
            "minimum_allocated_rate_bytes_per_second": (
                0 if not allocated_rates else min(allocated_rates)
            ),
            "maximum_allocated_rate_bytes_per_second": (
                0 if not allocated_rates else max(allocated_rates)
            ),
            "interval_time_sum_is_not_wall_clock_union": True,
        },
    }


def _validate_and_summarize_run(
    result: StudyRunResult,
    *,
    variant: ExperimentVariant,
    seed: int,
    bootstrap_workflow_ids: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = result.payload
    representative = result.representative
    if result.payload_sha256 != sha256_json(payload) or not _is_sha256(result.journal_sha256):
        raise NoFailureOverheadError("run result hashes are malformed")
    if payload.get("status") != "PASS" or payload.get("scenario") != Scenario.NO_FAILURE.value:
        raise NoFailureOverheadError("no-failure run status or scenario drifted")
    if payload.get("variant_fingerprint") != variant.fingerprint:
        raise NoFailureOverheadError("variant fingerprint drifted")
    admission = _mapping(payload.get("workflow_admission"), "payload.workflow_admission")
    if (
        admission.get("mode") != "closed_loop_workflow_concurrency"
        or admission.get("workflow_concurrency") != BASE_CONCURRENCY
    ):
        raise NoFailureOverheadError("run did not use closed-loop C=16 admission")
    workload = _mapping(payload.get("workload"), "payload.workload")
    if (
        workload.get("workflow_count") != EXPECTED_WORKFLOW_COUNT
        or workload.get("span_count") != EXPECTED_RECORD_COUNT
        or workload.get("no_truncation_or_padding") is not True
    ):
        raise NoFailureOverheadError("run workload shape drifted")
    metrics = _mapping(payload.get("metrics"), "payload.metrics")
    impact = _mapping(metrics.get("failure_impact"), "payload.metrics.failure_impact")
    if any(
        _integer(impact.get(name), f"failure_impact.{name}") != 0
        for name in (
            "failure_event_count",
            "active_requests",
            "queued_requests",
            "failed_gpu_count",
        )
    ):
        raise NoFailureOverheadError("failure activity occurred in the no-failure diagnostic")
    recovery = _mapping(metrics.get("recovery_latency_ns"), "metrics.recovery_latency_ns")
    if _integer(recovery.get("count"), "recovery_latency_ns.count") != 0:
        raise NoFailureOverheadError("recovery activity occurred in a no-failure run")
    output_audit = _mapping(payload.get("output_audit"), "payload.output_audit")
    if (
        output_audit.get("duplicate_or_missing_tokens") != 0
        or output_audit.get("stale_route_output_count") != 0
    ):
        raise NoFailureOverheadError("output-token audit failed")
    forbidden = _mapping(payload.get("forbidden_semantics"), "payload.forbidden_semantics")
    if any(value != 0 for value in forbidden.values()):
        raise NoFailureOverheadError("forbidden semantics occurred")
    pool_audit = _mapping(metrics.get("pool_audit"), "payload.metrics.pool_audit")
    for pool in ("normal_hbm", "peer_hbm", "store_dram"):
        if _mapping(pool_audit.get(pool), f"pool_audit.{pool}").get("valid") is not True:
            raise NoFailureOverheadError(f"{pool} capacity audit failed")
    if pool_audit.get("pending_destination_bytes_final") != 0:
        raise NoFailureOverheadError("run ended with pending destination bytes")
    resource_cost = _mapping(
        metrics.get("resource_cost"), "payload.metrics.resource_cost"
    )
    if _integer(
        resource_cost.get("source_pin_count_final"),
        "resource_cost.source_pin_count_final",
    ) != 0:
        raise NoFailureOverheadError("run ended with active transfer source pins")
    if _integer(
        resource_cost.get("gpu_hbm_foreground_store_reserve_final_bytes"),
        "resource_cost.gpu_hbm_foreground_store_reserve_final_bytes",
    ) != 0:
        raise NoFailureOverheadError(
            "run ended with foreground Store destination reservations"
        )
    for pool in ("normal_hbm", "store_dram"):
        pool_summary = _mapping(pool_audit.get(pool), f"pool_audit.{pool}")
        for field in ("pinned_entry_count_final", "pinned_reference_count_final"):
            if _integer(pool_summary.get(field), f"pool_audit.{pool}.{field}") != 0:
                raise NoFailureOverheadError(
                    f"{pool} ended with pinned physical KV entries"
                )

    try:
        continuous_report = audit_continuous_scheduler_evidence(payload, representative).to_dict()
    except FormalAlgorithmAuditError as error:
        raise NoFailureOverheadError(f"continuous scheduler audit failed: {error}") from error
    policy = _mapping(metrics.get("policy_effects"), "payload.metrics.policy_effects")
    formal_events = _sequence(
        representative.get("formal_algorithm2_events"),
        "representative.formal_algorithm2_events",
    )
    aimd_events = _sequence(representative.get("aimd_events"), "representative.aimd_events")
    formal_report: dict[str, object] | None
    if variant.variant_id == AEGISKV_VARIANT_ID:
        try:
            formal_report = audit_formal_algorithm_run(payload, representative).to_dict()
        except FormalAlgorithmAuditError as error:
            raise NoFailureOverheadError(f"formal Algorithm 2/3 audit failed: {error}") from error
        if not formal_events or not aimd_events:
            raise NoFailureOverheadError("AegisKV no-failure run lacks Algorithm 2/3 events")
        if policy.get("formal_algorithm2_event_count") != len(formal_events) or policy.get(
            "aimd_decision_count"
        ) != len(aimd_events):
            raise NoFailureOverheadError("Algorithm 2/3 event counts drifted")
    else:
        formal_report = None
        if formal_events or aimd_events or policy.get("formal_algorithm2_event_count") != 0:
            raise NoFailureOverheadError("Mooncake unexpectedly emitted Algorithm 2/3 events")

    details = tuple(_mapping(item, "span_details[]") for item in result.span_details)
    if len(details) != EXPECTED_RECORD_COUNT:
        raise NoFailureOverheadError("span detail count drifted")
    warmup = _warmup_definition(details, bootstrap_workflow_ids)
    protection = _protection_summary(payload, representative, details, warmup)
    wct_metrics = _mapping(
        metrics.get("workflow_completion_time_ns"),
        "payload.metrics.workflow_completion_time_ns",
    )
    raw_wct = _mapping(
        wct_metrics.get("by_workflow_id"),
        "workflow_completion_time_ns.by_workflow_id",
    )
    wct = {
        str(workflow_id): _integer(value, f"workflow_wct.{workflow_id}", minimum=1)
        for workflow_id, value in raw_wct.items()
    }
    if len(wct) != EXPECTED_WORKFLOW_COUNT:
        raise NoFailureOverheadError("workflow WCT map is incomplete")
    admission = _mapping(payload.get("workflow_admission"), "payload.workflow_admission")
    realized_order = tuple(
        str(item)
        for item in _sequence(
            admission.get("realized_workflow_order"),
            "payload.workflow_admission.realized_workflow_order",
        )
    )
    if (
        len(realized_order) != EXPECTED_WORKFLOW_COUNT
        or len(set(realized_order)) != EXPECTED_WORKFLOW_COUNT
        or set(realized_order) != set(wct)
        or realized_order[:BASE_CONCURRENCY] != tuple(bootstrap_workflow_ids)
        or admission.get("seed") != seed
        or admission.get("order_policy")
        != "observed_submit_then_seeded_sha256_workflow_permutation"
        or admission.get("realized_workflow_order_sha256") != sha256_json(realized_order)
    ):
        raise NoFailureOverheadError(
            "realized workflow admission order violates the seeded protocol"
        )
    earliest_release = min(
        _integer(item.get("released_ns"), "span.released_ns") for item in details
    )
    workload_end_ns = _integer(metrics.get("workload_end_ns"), "metrics.workload_end_ns")
    makespan_ns = workload_end_ns - earliest_release
    if makespan_ns <= 0:
        raise NoFailureOverheadError("workload makespan must be positive")
    goodput = _integer(
        metrics.get("goodput_output_tokens_per_second_milli"),
        "metrics.goodput_output_tokens_per_second_milli",
        minimum=1,
    )
    warmup_end_ns = _integer(warmup.get("warmup_end_ns"), "warmup.warmup_end_ns")
    algorithm2_kind_counts = Counter(str(item.get("event")) for item in formal_events)
    action_counts = Counter(str(item.get("action")) for item in aimd_events)

    def event_phase_counts(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        counts = Counter(
            "bootstrap_warmup"
            if _integer(item.get("timestamp_ns"), "algorithm_event.timestamp_ns") < warmup_end_ns
            else "steady_state"
            for item in events
        )
        return {phase: counts[phase] for phase in ("bootstrap_warmup", "steady_state")}

    compact = {
        "variant_id": variant.variant_id,
        "variant_fingerprint": variant.fingerprint,
        "payload_sha256": result.payload_sha256,
        "journal_sha256": result.journal_sha256,
        "span_details_sha256": sha256_json(result.span_details),
        "representative_sha256": sha256_json(representative),
        "workflow_wct_ns": dict(sorted(wct.items())),
        "workflow_admission_order": list(realized_order),
        "workflow_admission_order_sha256": sha256_json(realized_order),
        "makespan_ns": makespan_ns,
        "goodput_output_tokens_per_second_milli": goodput,
        "warmup": warmup,
        "protection": protection,
        "algorithm2": {
            "event_count": len(formal_events),
            "preview_count": sum(
                item.get("event") == "FORMAL_ALGORITHM2_PREVIEW" for item in formal_events
            ),
            "event_counts_by_kind": dict(sorted(algorithm2_kind_counts.items())),
            "by_time_phase": event_phase_counts(formal_events),
        },
        "algorithm3": {
            "event_count": len(aimd_events),
            "action_counts": dict(sorted(action_counts.items())),
            "by_time_phase": event_phase_counts(aimd_events),
        },
    }
    raw_document = {
        "schema": RAW_SCHEMA,
        "status": "PASS",
        "evidence": payload.get("evidence"),
        "task": {
            "scenario": Scenario.NO_FAILURE.value,
            "workflow_concurrency": BASE_CONCURRENCY,
            "seed": seed,
            "variant_id": variant.variant_id,
        },
        "variant": variant.to_dict(),
        "component_sha256": {
            "payload": result.payload_sha256,
            "journal": result.journal_sha256,
            "span_details": compact["span_details_sha256"],
            "representative": compact["representative_sha256"],
            "continuous_scheduler_audit": sha256_json(continuous_report),
            "formal_algorithm_audit": (
                None if formal_report is None else sha256_json(formal_report)
            ),
        },
        "continuous_scheduler_audit": continuous_report,
        "formal_algorithm_audit": formal_report,
        "warmup": warmup,
        "payload": payload,
        "span_details": list(result.span_details),
        "representative": representative,
    }
    return compact, raw_document


def _execute_worker_seed(seed: int, raw_root_text: str) -> dict[str, Any]:
    if (
        _WORKER_RECORDS is None
        or _WORKER_VARIANTS is None
        or _WORKER_CONTEXT_BUCKET is None
        or _WORKER_SOURCE_CONTRACT_FINGERPRINT is None
        or _WORKER_WORKLOAD_BINDING is None
        or _WORKER_CONFIG_BINDING_FINGERPRINT is None
        or _WORKER_ROOT is None
    ):
        raise NoFailureOverheadError("worker was not initialized")
    if seed not in DEFAULT_SEEDS:
        raise NoFailureOverheadError("worker received a non-protocol seed")
    systems: dict[str, Any] = {}
    raw_root = Path(raw_root_text)
    bootstrap_workflow_ids = _workflow_order(
        _WORKER_RECORDS,
        admission_seed=seed,
    )[:BASE_CONCURRENCY]
    for variant in _WORKER_VARIANTS:
        started = time.monotonic()
        print(
            f"[overhead] seed={seed} variant={variant.variant_id} START",
            file=sys.stderr,
            flush=True,
        )
        spec = CellSpec(
            variant=variant,
            context_bucket=_WORKER_CONTEXT_BUCKET,
            scenario=Scenario.NO_FAILURE,
            seed=seed,
            repetition="A",
            failure_schedule=None,
            workflow_concurrency=BASE_CONCURRENCY,
            workflow_admission_seed=seed,
            peer_binding_seed=0,
        )
        result = run_study_cell(_WORKER_RECORDS, spec)
        print(
            f"[overhead] seed={seed} variant={variant.variant_id} "
            f"SIM_DONE wall_s={time.monotonic() - started:.1f}",
            file=sys.stderr,
            flush=True,
        )
        unvalidated_relative_path = (
            Path("unvalidated")
            / f"seed-{seed}"
            / f"{variant.variant_id}.json"
        )
        unvalidated_path = raw_root.parent / unvalidated_relative_path
        _write_json_atomic(
            unvalidated_path,
            {
                "schema": "moonkvsim.aegiskv.no_failure_overhead.unvalidated_run.v1",
                "status": "UNVALIDATED",
                "paper_ready": False,
                "seed": seed,
                "variant_id": variant.variant_id,
                "variant_fingerprint": variant.fingerprint,
                "payload_sha256": result.payload_sha256,
                "journal_sha256": result.journal_sha256,
                "span_details_sha256": sha256_json(result.span_details),
                "representative_sha256": sha256_json(result.representative),
                "payload": result.payload,
                "span_details": list(result.span_details),
                "representative": result.representative,
            },
        )
        compact, raw_document = _validate_and_summarize_run(
            result,
            variant=variant,
            seed=seed,
            bootstrap_workflow_ids=bootstrap_workflow_ids,
        )
        raw_document["provenance"] = {
            "source_contract_fingerprint": _WORKER_SOURCE_CONTRACT_FINGERPRINT,
            "config_binding_fingerprint": _WORKER_CONFIG_BINDING_FINGERPRINT,
            "workload_binding": _WORKER_WORKLOAD_BINDING,
            "input_fingerprint": sha256_json(
                {
                    "source_contract_fingerprint": _WORKER_SOURCE_CONTRACT_FINGERPRINT,
                    "config_binding_fingerprint": _WORKER_CONFIG_BINDING_FINGERPRINT,
                    "workload_binding": _WORKER_WORKLOAD_BINDING,
                    "variant_fingerprint": variant.fingerprint,
                    "peer_binding_seed": 0,
                    "scenario": Scenario.NO_FAILURE.value,
                    "workflow_concurrency": BASE_CONCURRENCY,
                    "workflow_admission_seed": seed,
                    "seed": seed,
                }
            ),
        }
        relative_path = Path("raw") / f"seed-{seed}" / f"{variant.variant_id}.json"
        raw_path = raw_root.parent / relative_path
        _write_json_atomic(raw_path, raw_document)
        unvalidated_path.unlink()
        compact["raw_artifact"] = {
            "path": relative_path.as_posix(),
            "sha256": _sha256_file(raw_path),
            "schema": RAW_SCHEMA,
        }
        systems[variant.variant_id] = compact
        print(
            f"[overhead] seed={seed} variant={variant.variant_id} "
            f"DONE wall_s={time.monotonic() - started:.1f}",
            file=sys.stderr,
            flush=True,
        )
    if _source_contract(_WORKER_ROOT)["fingerprint"] != _WORKER_SOURCE_CONTRACT_FINGERPRINT:
        raise NoFailureOverheadError("source contract changed while worker executed")
    return {"seed": seed, "systems": systems}


def _nearest_rank(values: Sequence[int], percentile: int) -> int:
    if not values:
        raise NoFailureOverheadError("cannot summarize an empty sequence")
    ordered = sorted(values)
    rank = max(1, (percentile * len(ordered) + 99) // 100)
    return ordered[rank - 1]


def _distribution(values: Sequence[int]) -> dict[str, int]:
    if not values:
        raise NoFailureOverheadError("cannot summarize an empty distribution")
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) // 2
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p05": _nearest_rank(ordered, 5),
        "median": median,
        "mean": sum(ordered) // len(ordered),
        "p95": _nearest_rank(ordered, 95),
        "max": ordered[-1],
    }


def _ratio_ppm(delta: int, baseline: int) -> int:
    if baseline <= 0:
        raise NoFailureOverheadError("ratio baseline must be positive")
    return delta * 1_000_000 // baseline


def _build_paired_seed(cell: Mapping[str, Any]) -> dict[str, Any]:
    seed = _integer(cell.get("seed"), "cell.seed")
    systems = _mapping(cell.get("systems"), "cell.systems")
    if set(systems) != set(VARIANT_IDS):
        raise NoFailureOverheadError("paired cell lacks one of the exact two systems")
    moon = _mapping(systems[MOONCAKE_VARIANT_ID], "cell.systems.mooncake")
    aegis = _mapping(systems[AEGISKV_VARIANT_ID], "cell.systems.aegiskv")
    moon_wct = _mapping(moon.get("workflow_wct_ns"), "moon.workflow_wct_ns")
    aegis_wct = _mapping(aegis.get("workflow_wct_ns"), "aegis.workflow_wct_ns")
    moon_order = tuple(
        str(item)
        for item in _sequence(
            moon.get("workflow_admission_order"),
            "moon.workflow_admission_order",
        )
    )
    aegis_order = tuple(
        str(item)
        for item in _sequence(
            aegis.get("workflow_admission_order"),
            "aegis.workflow_admission_order",
        )
    )
    if (
        moon_order != aegis_order
        or len(moon_order) != EXPECTED_WORKFLOW_COUNT
        or moon.get("workflow_admission_order_sha256") != sha256_json(moon_order)
        or aegis.get("workflow_admission_order_sha256") != sha256_json(aegis_order)
    ):
        raise NoFailureOverheadError(
            "paired systems do not share the exact realized workflow admission order"
        )
    if set(moon_wct) != set(aegis_wct) or len(moon_wct) != EXPECTED_WORKFLOW_COUNT:
        raise NoFailureOverheadError("paired systems do not share exactly 160 workflow IDs")
    moon_warmup = _mapping(moon.get("warmup"), "moon.warmup")
    aegis_warmup = _mapping(aegis.get("warmup"), "aegis.warmup")
    moon_bootstrap = set(_sequence(moon_warmup.get("bootstrap_workflow_ids"), "moon.bootstrap"))
    aegis_bootstrap = set(_sequence(aegis_warmup.get("bootstrap_workflow_ids"), "aegis.bootstrap"))
    if moon_bootstrap != aegis_bootstrap or len(moon_bootstrap) != BASE_CONCURRENCY:
        raise NoFailureOverheadError("paired bootstrap cohorts diverged")
    rows: list[dict[str, Any]] = []
    deltas: list[int] = []
    bootstrap_deltas: list[int] = []
    steady_deltas: list[int] = []
    for workflow_id in sorted(moon_wct):
        baseline = _integer(moon_wct[workflow_id], f"moon.wct.{workflow_id}", minimum=1)
        candidate = _integer(aegis_wct[workflow_id], f"aegis.wct.{workflow_id}", minimum=1)
        delta = candidate - baseline
        cohort = "bootstrap_initial_admission" if workflow_id in moon_bootstrap else "steady_state"
        rows.append(
            {
                "workflow_id": workflow_id,
                "cohort": cohort,
                "mooncake_wct_ns": baseline,
                "aegiskv_wct_ns": candidate,
                "aegiskv_minus_mooncake_ns": delta,
                "aegiskv_overhead_ppm_floor": _ratio_ppm(delta, baseline),
                "aegiskv_over_mooncake_ratio": {
                    "numerator": candidate,
                    "denominator": baseline,
                },
            }
        )
        deltas.append(delta)
        (bootstrap_deltas if cohort == "bootstrap_initial_admission" else steady_deltas).append(
            delta
        )
    moon_makespan = _integer(moon.get("makespan_ns"), "moon.makespan_ns", minimum=1)
    aegis_makespan = _integer(aegis.get("makespan_ns"), "aegis.makespan_ns", minimum=1)
    moon_goodput = _integer(
        moon.get("goodput_output_tokens_per_second_milli"), "moon.goodput", minimum=1
    )
    aegis_goodput = _integer(
        aegis.get("goodput_output_tokens_per_second_milli"), "aegis.goodput", minimum=1
    )
    return {
        "seed": seed,
        "workflow_pairs": rows,
        "wct_delta_ns": _distribution(deltas),
        "wct_delta_ns_by_cohort": {
            "bootstrap_initial_admission": _distribution(bootstrap_deltas),
            "steady_state": _distribution(steady_deltas),
        },
        "makespan": {
            "mooncake_ns": moon_makespan,
            "aegiskv_ns": aegis_makespan,
            "aegiskv_minus_mooncake_ns": aegis_makespan - moon_makespan,
            "aegiskv_overhead_ppm_floor": _ratio_ppm(aegis_makespan - moon_makespan, moon_makespan),
        },
        "goodput": {
            "mooncake_output_tokens_per_second_milli": moon_goodput,
            "aegiskv_output_tokens_per_second_milli": aegis_goodput,
            "aegiskv_minus_mooncake_output_tokens_per_second_milli": (aegis_goodput - moon_goodput),
            "aegiskv_delta_ppm_floor": _ratio_ppm(aegis_goodput - moon_goodput, moon_goodput),
        },
    }


def _build_document(
    *,
    cells: Sequence[Mapping[str, Any]],
    source_contract: Mapping[str, Any],
    config_binding: Mapping[str, Any],
    workload_binding: Mapping[str, Any],
    workload_manifest_fingerprint: str,
    context_bucket: str,
    git_commit: str,
) -> dict[str, Any]:
    if tuple(sorted(_integer(cell.get("seed"), "cell.seed") for cell in cells)) != DEFAULT_SEEDS:
        raise NoFailureOverheadError("completed cells do not cover exact seeds 0..4")
    ordered_cells = sorted(cells, key=lambda item: _integer(item.get("seed"), "cell.seed"))
    paired = [_build_paired_seed(cell) for cell in ordered_cells]
    admission_hashes = {
        cast(
            str,
            _mapping(
                _mapping(cell.get("systems"), "cell.systems").get(MOONCAKE_VARIANT_ID),
                "cell.systems.mooncake",
            ).get("workflow_admission_order_sha256"),
        )
        for cell in ordered_cells
    }
    if len(admission_hashes) != len(DEFAULT_SEEDS):
        raise NoFailureOverheadError(
            "experiment seeds did not produce five distinct realized admission orders"
        )
    all_deltas = [
        _integer(row.get("aegiskv_minus_mooncake_ns"), "workflow_pair.delta", minimum=-(10**30))
        for item in paired
        for row in cast(Sequence[Mapping[str, Any]], item["workflow_pairs"])
    ]
    if len(all_deltas) != len(DEFAULT_SEEDS) * EXPECTED_WORKFLOW_COUNT:
        raise NoFailureOverheadError("aggregate workflow-pair count drifted")
    makespan_ppm = [
        _integer(
            _mapping(item["makespan"], "paired.makespan").get("aegiskv_overhead_ppm_floor"),
            "paired.makespan.overhead_ppm",
            minimum=-(10**30),
        )
        for item in paired
    ]
    goodput_ppm = [
        _integer(
            _mapping(item["goodput"], "paired.goodput").get("aegiskv_delta_ppm_floor"),
            "paired.goodput.delta_ppm",
            minimum=-(10**30),
        )
        for item in paired
    ]
    body = {
        "schema": SCHEMA,
        "status": "PASS",
        "evidence": {
            "class": "E2",
            "scope": "modeled/preliminary",
            "calibration": "not_calibrated",
            "physical_execution": False,
            "physical_timing_claim_allowed": False,
            "paper_ready": False,
            "effect_direction_gate_applied": False,
        },
        "protocol": {
            "model": "Qwen/Qwen3-8B",
            "data_parallel_size": 8,
            "scenario": Scenario.NO_FAILURE.value,
            "workflow_concurrency": BASE_CONCURRENCY,
            "workflow_count": EXPECTED_WORKFLOW_COUNT,
            "record_count": EXPECTED_RECORD_COUNT,
            "seeds": list(DEFAULT_SEEDS),
            "workflow_admission_randomization": {
                "policy": "observed_submit_then_seeded_sha256_workflow_permutation",
                "seed_source": "paired_experiment_seed",
                "paired_systems_share_exact_permutation": True,
                "peer_placement_held_fixed": True,
            },
            "peer_binding_seed": 0,
            "peer_binding_seed_decoupled_from_experiment_seed": True,
            "systems": list(VARIANT_IDS),
            "continuous_batching_required": True,
            "failure_events_required": 0,
            "failure_focus_bucket_rule": "highest_nonempty_context_bucket",
            "failure_focus_bucket": context_bucket,
            "bootstrap_warmup": {
                "bootstrap_cohort_size": BASE_CONCURRENCY,
                "cohort_rule": "first_C_workflows_in_causal_admission_order",
                "warmup_end_rule": (
                    "all_bootstrap_workflows_have_started_first_compute_per_system"
                ),
                "primary_metrics_include_bootstrap": True,
                "cohort_breakdown_reported": True,
            },
            "interpretation": (
                "descriptive_no_failure_backup_overhead; no threshold or desired trend enforced"
            ),
        },
        "provenance": {
            "git_commit": git_commit,
            "source_contract": dict(source_contract),
            "config_binding": dict(config_binding),
            "workload_binding": dict(workload_binding),
            "workload_manifest_fingerprint": workload_manifest_fingerprint,
            "output_schema": {
                "path": SCHEMA_RELATIVE_PATH,
                "sha256": cast(Mapping[str, str], source_contract["files"])[SCHEMA_RELATIVE_PATH],
            },
        },
        "cells": ordered_cells,
        "paired": paired,
        "aggregate": {
            "seed_count": len(DEFAULT_SEEDS),
            "workflow_pair_count": len(all_deltas),
            "wct_delta_ns": _distribution(all_deltas),
            "makespan_overhead_ppm_floor_across_seeds": _distribution(makespan_ppm),
            "goodput_delta_ppm_floor_across_seeds": _distribution(goodput_ppm),
        },
        "audit": {
            "status": "PASS",
            "checks": {
                "exact_frozen_160_workflows": True,
                "exact_1304_spans": True,
                "exact_seeds_0_through_4": True,
                "seed_changes_realized_workflow_admission_order": True,
                "paired_systems_share_workflow_admission_order": True,
                "same_workflow_ids_paired_per_seed": True,
                "scenario_no_failure_for_every_run": True,
                "zero_failure_and_recovery_events": True,
                "continuous_batch_scheduler_audited_both_systems": True,
                "algorithm2_and_algorithm3_audited_for_aegiskv": True,
                "mooncake_emitted_no_algorithm2_or_algorithm3_events": True,
                "protection_transfer_byte_conservation": True,
                "bootstrap_and_steady_state_reported_separately": True,
                "raw_payload_span_event_and_flow_provenance_retained": True,
                "no_effect_direction_gate": True,
            },
        },
    }
    return {**body, "fingerprint": sha256_json(body)}


def _validate_output_schema(document: Mapping[str, Any], schema_path: Path) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NoFailureOverheadError(f"cannot load output schema: {error}") from error
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        preview = "; ".join(f"{list(error.absolute_path)}: {error.message}" for error in errors[:8])
        raise NoFailureOverheadError(f"output schema validation failed: {preview}")


def _parse_seeds(text: str) -> tuple[int, ...]:
    try:
        values = tuple(int(item) for item in text.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("seeds must be comma-separated integers") from error
    if values != DEFAULT_SEEDS:
        raise argparse.ArgumentTypeError("this protocol requires exact ordered seeds 0,1,2,3,4")
    return values


def _failure_document(error: BaseException) -> dict[str, Any]:
    body = {
        "schema": FAILURE_SCHEMA,
        "status": "FAIL",
        "paper_ready": False,
        "exception": {
            "type": f"{type(error).__module__}.{type(error).__qualname__}",
            "message": str(error),
            "traceback": "".join(traceback.TracebackException.from_exception(error).format()),
        },
    }
    return {**body, "fingerprint": sha256_json(body)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--jobs", type=int, default=min(5, os.cpu_count() or 1))
    parser.add_argument("--seeds", type=_parse_seeds, default=DEFAULT_SEEDS)
    return parser


def run_protocol(*, output_dir: Path, config_dir: Path | None, jobs: int) -> Path:
    if type(jobs) is not int or jobs <= 0:
        raise NoFailureOverheadError("jobs must be a positive integer")
    root = repository_root().resolve()
    destination = output_dir.resolve()
    if destination.exists():
        raise NoFailureOverheadError(f"output directory already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    try:
        resolved_config_dir = (config_dir or default_config_dir(root)).resolve()
        configs = load_experiment_configs(resolved_config_dir, root=root)
        configured_seeds = matrix_seeds(configs.requests)
        if configured_seeds != DEFAULT_SEEDS:
            raise NoFailureOverheadError("requests.json must declare exact seeds 0..4")
        if workflow_concurrency(configs.requests) != BASE_CONCURRENCY:
            raise NoFailureOverheadError("requests.json must declare base concurrency C=16")
        workload_path, manifest_path = workload_paths(configs.requests, root=root)
        records, workload_binding, manifest = load_frozen_workload(
            workload_path,
            manifest_path,
            retain_exact_token_ids=True,
        )
        if len(records) != EXPECTED_RECORD_COUNT:
            raise NoFailureOverheadError("frozen workload must contain exactly 1304 records")
        _require_exact_token_records(records)
        ordered_workflows = _workflow_order(records)
        if len(ordered_workflows[:BASE_CONCURRENCY]) != BASE_CONCURRENCY:
            raise NoFailureOverheadError("frozen workload cannot form the bootstrap cohort")
        parameters = model_parameters_from_configs(configs)
        variants = _select_variants(parameters)
        source_contract = _source_contract(root)
        config_binding = _config_binding(resolved_config_dir)
        context_bucket = _highest_nonempty_context_bucket(manifest)
        manifest_fingerprint = manifest.get("fingerprint")
        if not _is_sha256(manifest_fingerprint):
            raise NoFailureOverheadError("workload manifest fingerprint is malformed")
        raw_root = staging / "raw"
        raw_root.mkdir(parents=True)
        cells: list[dict[str, Any]] = []
        with ProcessPoolExecutor(
            max_workers=min(jobs, len(DEFAULT_SEEDS)),
            initializer=_initialize_worker,
            initargs=(
                root.as_posix(),
                resolved_config_dir.as_posix(),
                source_contract["fingerprint"],
                workload_binding.fingerprint,
                config_binding["fingerprint"],
            ),
        ) as executor:
            futures = {
                executor.submit(_execute_worker_seed, seed, raw_root.as_posix()): seed
                for seed in DEFAULT_SEEDS
            }
            for future in as_completed(futures):
                seed = futures[future]
                try:
                    cells.append(future.result())
                except BaseException as error:
                    for pending in futures:
                        pending.cancel()
                    raise NoFailureOverheadError(f"seed-{seed} worker failed: {error}") from error
        if _source_contract(root)["fingerprint"] != source_contract["fingerprint"]:
            raise NoFailureOverheadError("source contract changed during the protocol")
        if _config_binding(resolved_config_dir)["fingerprint"] != config_binding["fingerprint"]:
            raise NoFailureOverheadError("three-layer configs changed during the protocol")
        reloaded_records, reloaded_binding, reloaded_manifest = load_frozen_workload(
            workload_path,
            manifest_path,
            retain_exact_token_ids=True,
        )
        if (
            len(reloaded_records) != len(records)
            or reloaded_binding.fingerprint != workload_binding.fingerprint
            or reloaded_manifest.get("fingerprint") != manifest_fingerprint
        ):
            raise NoFailureOverheadError("frozen workload changed during the protocol")
        if tuple(item.variant_id for item in variants) != VARIANT_IDS:
            raise NoFailureOverheadError("variant catalog changed during the protocol")
        document = _build_document(
            cells=cells,
            source_contract=source_contract,
            config_binding=config_binding,
            workload_binding=workload_binding.to_dict(),
            workload_manifest_fingerprint=cast(str, manifest_fingerprint),
            context_bucket=context_bucket,
            git_commit=_git_commit(root),
        )
        _validate_output_schema(document, root / SCHEMA_RELATIVE_PATH)
        _write_json_atomic(staging / OUTPUT_FILENAME, document)
        os.replace(staging, destination)
        return destination / OUTPUT_FILENAME
    except BaseException as error:
        _write_json_atomic(staging / "FAILURE.json", _failure_document(error))
        os.replace(staging, destination)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_path = run_protocol(
        output_dir=args.output_dir,
        config_dir=args.config_dir,
        jobs=args.jobs,
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
