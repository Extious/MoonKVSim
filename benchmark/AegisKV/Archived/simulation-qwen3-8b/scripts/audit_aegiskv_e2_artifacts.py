#!/usr/bin/env python3
"""Fail-closed, offline audit of AegisKV GlobalDES E2 artifacts.

The auditor only reads an already-published matrix bundle and figure bundle.
It has no simulator, physical-runtime, network, CUDA, or Slurm execution path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from moonkvsim.aegiskv.experiment_statistics import StatisticsError, build_statistics

AUDIT_SCHEMA: Final = "moonkvsim.aegiskv.e2_artifact_audit.v1"
MATRIX_SCHEMA: Final = "moonkvsim.aegiskv.e2_matrix_suite.v1"
MATRIX_ARTIFACTS: Final = (
    "results.jsonl",
    "pair-audit.jsonl",
    "failure-schedules.jsonl",
    "completeness.json",
    "provenance.json",
    "protocol.json",
    "statistics.json",
    "representative-run.json",
)
BUCKETS: Final = ("8k", "32k", "64k", "96k", "128k")
SCENARIOS: Final = ("no_failure", "gpu_failure")
REPETITIONS: Final = ("A", "B")
MATRIX_EVIDENCE: Final[dict[str, Any]] = {
    "class": "E2",
    "scope": "modeled/preliminary",
    "calibration": "not_calibrated",
    "physical_execution": False,
    "physical_timing_claim_allowed": False,
    "formal_use_allowed": False,
    "paper_ready": False,
    "slurm_used": False,
}
PAYLOAD_EVIDENCE: Final[dict[str, Any]] = {
    key: MATRIX_EVIDENCE[key]
    for key in (
        "class",
        "scope",
        "calibration",
        "physical_execution",
        "physical_timing_claim_allowed",
        "formal_use_allowed",
        "paper_ready",
    )
}
FIGURE_EVIDENCE: Final[dict[str, Any]] = dict(MATRIX_EVIDENCE)
EVIDENCE_FOOTER: Final = "E2 modeled/preliminary · not calibrated · no physical experiment"
GENERATOR: Final = "moonkvsim.aegiskv.figures.v1"
A100_40GB_HBM_BYTES: Final = 40 * 1024**3
LEGACY_80GIB_HBM_BYTES: Final = 80 * 1024**3
LOCKED_DP_COUNT: Final = 8
LEGACY_MODEL_DEPLOYMENT_CONTRACT: Final[dict[str, Any]] = {
    "scope_id": "qwen3-8b-dp-only-tp1-pp1-v1",
    "model": {
        "id": "Qwen/Qwen3-8B",
        "revision": "b968826d9c46dd6066d109eabc6255188de91218",
        "config_sha256": (
            "f7c4eadfbbf522470667b797a3c89be2524832d2d599797248dc304fff447c30"
        ),
        "other_models_allowed": False,
    },
    "kv_layout": {
        "bytes_per_64_source_tokens": 9_437_184,
        "native_tp1_pp1_fingerprint": (
            "616330f7a5e168edfad90d6e53dc8b754ef3f4c78925e80a49516e4f3f3d8d4f"
        ),
        "proposed_yarn_128k_tp1_pp1_fingerprint": (
            "d9863189bf94c967e18d4926ecb1fc88cc26e7dcb1553eb69972afaff7dc7d4d"
        ),
        "evidence": "source_derived_not_physically_calibrated",
    },
    "parallelism": {
        "only_varied_dimension": "data_parallel_size",
        "allowed_data_parallel_sizes": [2, 4, 8],
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "tensor_parallel_sensitivity_allowed": False,
        "pipeline_parallel_sensitivity_allowed": False,
    },
}
MODEL_DEPLOYMENT_CONTRACT: Final[dict[str, Any]] = {
    "scope_id": "qwen3-8b-dp8-a100-40gb-single-node-v1",
    "model": {
        "id": "Qwen/Qwen3-8B",
        "revision": "b968826d9c46dd6066d109eabc6255188de91218",
        "config_sha256": (
            "f7c4eadfbbf522470667b797a3c89be2524832d2d599797248dc304fff447c30"
        ),
        "other_models_allowed": False,
    },
    "kv_layout": {
        "bytes_per_64_source_tokens": 9_437_184,
        "native_tp1_pp1_fingerprint": (
            "a2652848f10c2902063dbdb33195c4b58804e9cbc3d867c5767037278f437973"
        ),
        "proposed_yarn_128k_tp1_pp1_fingerprint": (
            "42cff103674b5a857c1e6308247fbd006bf80ac444efd50a377c40ab4696a29e"
        ),
        "evidence": "source_derived_not_physically_calibrated",
    },
    "parallelism": {
        "data_parallel_size": LOCKED_DP_COUNT,
        "allowed_data_parallel_sizes": [LOCKED_DP_COUNT],
        "data_parallel_sensitivity_allowed": False,
        "tensor_parallel_size": 1,
        "pipeline_parallel_size": 1,
        "tensor_parallel_sensitivity_allowed": False,
        "pipeline_parallel_sensitivity_allowed": False,
    },
    "hardware": {
        "gpu_sku": "NVIDIA-A100-40GB",
        "gpu_count": LOCKED_DP_COUNT,
        "node_count": 1,
        "topology": "single_node",
        "physical_hbm_bytes_per_gpu": A100_40GB_HBM_BYTES,
        "evidence": "modeled_not_physically_calibrated",
    },
}
FIGURE_STEMS: Final[dict[str, str]] = {
    "F1": "f1-system-architecture",
    "F2": "f2-failure-recovery-timeline",
    "F3": "f3-peer-hbm-timeline",
    "F4": "f4-store-dram-timeline",
    "F5": "f5-kv-migration-gantt",
    "F6": "f6-wct-goodput",
    "F7": "f7-recovery-cdf",
    "F8": "f8-coverage-recompute",
    "F9": "f9-policy-ablation",
    "F10": "f10-budget-sensitivity",
    "F11": "f11-scale",
    "F13": "f13-resource-cost",
    "F14": "f14-peak-mean",
    "F15": "f15-trace-coverage",
}
REQUIRED_FIGURE_IDS: Final = tuple(FIGURE_STEMS)
F12_FILE: Final = "f12-simulator-accuracy.excluded.json"
HEX_40: Final = re.compile(r"[0-9a-f]{40}\Z")
HEX_64: Final = re.compile(r"[0-9a-f]{64}\Z")
CORE_VARIANTS: Final = (
    "recompute_only",
    "vanilla_mooncake_dram",
    "static_peer_hbm",
    "aegiskv_dram_only",
    "aegiskv_peer_only",
    "aegiskv_hbm_dram",
    "aegiskv_unified",
)
ABLATION_VARIANTS: Final = (
    "full",
    "no_slack",
    "no_reuse_value",
    "no_recovery_value",
    "two_managers",
    "no_aimd",
    "static_hbm_quota",
    "random_eviction",
    "lru_eviction",
    "lfu_eviction",
    "no_anti_colocation",
    "no_cache_aware_routing",
)
SENSITIVITY_VARIANTS: Final = tuple(
    f"{dimension}={value}"
    for dimension, values in (
        ("peer_hbm_alpha_percent", (0, 20, 50)),
        ("store_budget_gib", (32, 64, 128)),
        ("store_bandwidth_gbps", (12, 25, 50)),
        ("peer_fabric_bandwidth_gbps", (50, 100, 200)),
        ("failure_progress_percent", (10, 50, 90)),
        ("reroute_delay_ms", (0, 1, 5)),
        ("policy_chunk_tokens", (256, 1_024, 4_096)),
    )
    for value in values
)
V2_CURRENT_SENSITIVITY_VARIANTS: Final = tuple(
    f"{dimension}={value}"
    for dimension, values in (
        ("peer_hbm_alpha_percent", (0, 20, 50)),
        ("store_budget_gib", (32, 64, 128)),
        ("store_bandwidth_gbps", (12, 25, 50)),
        ("peer_fabric_bandwidth_gbps", (50, 100, 200)),
        ("failure_progress_percent", (10, 50, 90)),
        ("detection_delay_ms", (1, 5, 20)),
        ("reroute_delay_ms", (0, 1, 5)),
        ("policy_chunk_tokens", (256, 1_024, 4_096)),
    )
    for value in values
)
LEGACY_SENSITIVITY_VARIANTS: Final = tuple(
    f"{dimension}={value}"
    for dimension, values in (
        ("peer_budget_gib", (4, 8, 12)),
        ("store_budget_gib", (32, 64, 128)),
        ("store_bandwidth_gbps", (12, 25, 50)),
        ("peer_fabric_bandwidth_gbps", (50, 100, 200)),
        ("dp_count", (2, 4, 8)),
        ("failure_progress_percent", (10, 50, 90)),
        ("detection_delay_ms", (1, 5, 20)),
        ("reroute_delay_ms", (0, 1, 5)),
        ("policy_chunk_tokens", (256, 1_024, 4_096)),
    )
    for value in values
)
VARIANTS: Final = {
    "core": CORE_VARIANTS,
    "ablation": ABLATION_VARIANTS,
    "sensitivity": SENSITIVITY_VARIANTS,
}
V2_CURRENT_VARIANTS: Final = {
    "core": CORE_VARIANTS,
    "ablation": ABLATION_VARIANTS,
    "sensitivity": V2_CURRENT_SENSITIVITY_VARIANTS,
}
LEGACY_VARIANTS: Final = {
    "core": CORE_VARIANTS,
    "ablation": ABLATION_VARIANTS,
    "sensitivity": LEGACY_SENSITIVITY_VARIANTS,
}


class AuditFailure(ValueError):
    """An artifact violated the immutable E2 publication contract."""


@dataclass(frozen=True, slots=True)
class AuditScope:
    scope_id: str
    model_deployment_contract: dict[str, Any]
    allowed_dp_counts: tuple[int, ...]
    hbm_bytes_per_gpu: int
    variants: dict[str, tuple[str, ...]]
    resource_hardware_metadata: bool


CURRENT_SCOPE: Final = AuditScope(
    scope_id="qwen3-8b-dp8-a100-40gb-single-node-v1",
    model_deployment_contract=MODEL_DEPLOYMENT_CONTRACT,
    allowed_dp_counts=(8,),
    hbm_bytes_per_gpu=A100_40GB_HBM_BYTES,
    variants=VARIANTS,
    resource_hardware_metadata=True,
)
V2_CURRENT_SCOPE: Final = AuditScope(
    scope_id="qwen3-8b-dp8-a100-40gb-single-node-v1",
    model_deployment_contract=MODEL_DEPLOYMENT_CONTRACT,
    allowed_dp_counts=(8,),
    hbm_bytes_per_gpu=A100_40GB_HBM_BYTES,
    variants=V2_CURRENT_VARIANTS,
    resource_hardware_metadata=True,
)
LEGACY_SCOPE: Final = AuditScope(
    scope_id="qwen3-8b-dp-only-tp1-pp1-v1",
    model_deployment_contract=LEGACY_MODEL_DEPLOYMENT_CONTRACT,
    allowed_dp_counts=(2, 4, 8),
    hbm_bytes_per_gpu=LEGACY_80GIB_HBM_BYTES,
    variants=LEGACY_VARIANTS,
    resource_hardware_metadata=False,
)


@dataclass(frozen=True, slots=True)
class MatrixState:
    manifest: dict[str, Any]
    manifest_sha256: str
    artifact_hashes: dict[str, str]
    rows: tuple[dict[str, Any], ...]
    rows_by_id: dict[str, dict[str, Any]]
    pair_count: int
    config_snapshot_binding: str


def _canonical_bytes(value: object, *, newline: bool) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + ("\n" if newline else "")
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value, newline=False))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise AuditFailure(f"cannot hash {path.name}: {error}") from error
    return digest.hexdigest()


def _reject_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuditFailure(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise AuditFailure(f"non-finite JSON number is forbidden: {value}")


def _parse_json(text: str, location: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_pairs,
            parse_constant=_reject_constant,
        )
    except AuditFailure:
        raise
    except json.JSONDecodeError as error:
        raise AuditFailure(f"{location}: invalid JSON: {error.msg}") from error
    except RecursionError as error:
        raise AuditFailure(f"{location}: JSON nesting is too deep") from error


def _regular_file(path: Path, location: str) -> bytes:
    if path.is_symlink():
        raise AuditFailure(f"{location}: symlinks are forbidden")
    if not path.is_file():
        raise AuditFailure(f"{location}: required regular file is missing")
    try:
        return path.read_bytes()
    except OSError as error:
        raise AuditFailure(f"{location}: cannot read: {error}") from error


def _safe_child(root: Path, declared: object, location: str) -> Path:
    if not isinstance(declared, str) or not declared:
        raise AuditFailure(f"{location}: expected a non-empty relative file name")
    if (
        declared in {".", ".."}
        or "/" in declared
        or "\\" in declared
        or Path(declared).is_absolute()
        or Path(declared).name != declared
    ):
        raise AuditFailure(f"{location}: path escape or nested path is forbidden: {declared!r}")
    candidate = root / declared
    if candidate.is_symlink():
        raise AuditFailure(f"{location}: symlinks are forbidden")
    try:
        root_resolved = root.resolve()
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise AuditFailure(f"{location}: cannot resolve path: {error}") from error
    if resolved.parent != root_resolved:
        raise AuditFailure(f"{location}: path escapes the declared bundle")
    return candidate


def _object(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuditFailure(f"{location}: expected JSON object")
    return value


def _array(value: object, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise AuditFailure(f"{location}: expected JSON array")
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuditFailure(f"{location}: expected non-empty string")
    return value


def _integer(value: object, location: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise AuditFailure(f"{location}: expected integer >= {minimum}")
    return value


def _hex(value: object, location: str, *, length: int = 64) -> str:
    result = _string(value, location)
    pattern = HEX_40 if length == 40 else HEX_64
    if pattern.fullmatch(result) is None:
        raise AuditFailure(f"{location}: expected lowercase {length}-hex digest")
    return result


def _exact_keys(value: Mapping[str, Any], keys: set[str], location: str) -> None:
    actual = set(value)
    if actual != keys:
        raise AuditFailure(
            f"{location}: field set mismatch; missing={sorted(keys - actual)}, "
            f"unexpected={sorted(actual - keys)}"
        )


def _same_json(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict) and isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _same_json(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _same_json(left, right) for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def _equal(actual: object, expected: object, location: str) -> None:
    if not _same_json(actual, expected):
        raise AuditFailure(f"{location}: expected {expected!r}, got {actual!r}")


def _load_json(path: Path, location: str, *, canonical: bool = True) -> dict[str, Any]:
    raw = _regular_file(path, location)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AuditFailure(f"{location}: not valid UTF-8") from error
    value = _object(_parse_json(text, location), location)
    if canonical and raw != _canonical_bytes(value, newline=True):
        raise AuditFailure(f"{location}: JSON is not canonical with one trailing newline")
    return value


def _load_jsonl(path: Path, location: str) -> tuple[dict[str, Any], ...]:
    raw = _regular_file(path, location)
    if not raw:
        raise AuditFailure(f"{location}: JSONL is empty")
    lines = raw.splitlines(keepends=True)
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        row_location = f"{location}:{index}"
        if not line or line == b"\n":
            raise AuditFailure(f"{row_location}: blank lines are forbidden")
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AuditFailure(f"{row_location}: not valid UTF-8") from error
        row = _object(_parse_json(text, row_location), row_location)
        if line != _canonical_bytes(row, newline=True):
            raise AuditFailure(f"{row_location}: JSONL row is not canonical")
        rows.append(row)
    return tuple(rows)


def _verify_fingerprint(document: dict[str, Any], location: str) -> str:
    fingerprint = _hex(document.get("fingerprint"), f"{location}.fingerprint")
    unhashed = dict(document)
    del unhashed["fingerprint"]
    _equal(fingerprint, _sha256_json(unhashed), f"{location}.fingerprint")
    return fingerprint


def _scope_for_contract(value: object, protocol: Mapping[str, Any]) -> AuditScope:
    if _same_json(value, MODEL_DEPLOYMENT_CONTRACT):
        catalog = _object(protocol.get("suite_catalog"), "protocol.suite_catalog")
        sensitivity = _object(catalog.get("sensitivity"), "protocol.sensitivity")
        variant_ids = tuple(
            _string(item, "protocol.sensitivity.variant_ids")
            for item in _array(
                sensitivity.get("variant_ids"),
                "protocol.sensitivity.variant_ids",
            )
        )
        if variant_ids == SENSITIVITY_VARIANTS:
            return CURRENT_SCOPE
        if variant_ids == V2_CURRENT_SENSITIVITY_VARIANTS:
            return V2_CURRENT_SCOPE
        raise AuditFailure("current model contract has an unknown sensitivity catalog")
    if _same_json(value, LEGACY_MODEL_DEPLOYMENT_CONTRACT):
        return LEGACY_SCOPE
    raise AuditFailure("model deployment contract is neither current nor a recognized snapshot")


def _expected_model_deployment(dp_count: int, scope: AuditScope) -> dict[str, Any]:
    if dp_count not in scope.allowed_dp_counts:
        raise AuditFailure(
            f"data-parallel size {dp_count} is outside scope {scope.scope_id}"
        )
    contract = dict(scope.model_deployment_contract)
    if scope is LEGACY_SCOPE:
        parallelism = dict(
            _object(
                scope.model_deployment_contract["parallelism"],
                "auditor model deployment contract.parallelism",
            )
        )
        parallelism["data_parallel_size"] = dp_count
        contract["parallelism"] = parallelism
    return contract


def _validate_payload(row: dict[str, Any], location: str, scope: AuditScope) -> None:
    payload = _object(row.get("payload"), f"{location}.payload")
    _exact_keys(
        payload,
        {
            "schema",
            "status",
            "evidence",
            "global_clock",
            "execution_scope",
            "model_deployment",
            "resource_model",
            "recovery_model",
            "variant_fingerprint",
            "context_bucket",
            "scenario",
            "workload",
            "failure_schedule",
            "metrics",
            "output_audit",
            "forbidden_semantics",
        },
        f"{location}.payload",
    )
    _equal(
        payload.get("schema"),
        "moonkvsim.aegiskv.study_run_payload.v1",
        f"{location}.payload.schema",
    )
    _equal(payload.get("status"), "PASS", f"{location}.payload.status")
    _equal(payload.get("evidence"), PAYLOAD_EVIDENCE, f"{location}.payload.evidence")
    _equal(
        payload.get("global_clock"),
        {
            "kind": "single_global_virtual_clock",
            "time_unit": "ns",
            "wall_clock_or_sleep_used": False,
            "event_order": "timestamp_priority_stable_sequence",
        },
        f"{location}.payload.global_clock",
    )
    _equal(
        payload.get("execution_scope"),
        {
            "cpu_metadata_only": True,
            "slurm_used": False,
            "cuda_used": False,
            "network_io_used": False,
        },
        f"{location}.payload.execution_scope",
    )
    _equal(
        payload.get("model_deployment"),
        row.get("model_deployment"),
        f"{location}.payload.model_deployment",
    )
    resources = _object(payload.get("resource_model"), f"{location}.payload.resource_model")
    resource_keys = {
        "peer_hbm_resources",
        "store_dram_segments",
        "store_node_count",
        "host_dram_staging_resources",
        "store_transport",
        "host_staging_capacity_transactions",
        "source_pin_overlay_without_double_charge",
        "communication_backend",
        "fairness",
        "flow_clock",
        "slice_size_policy_chunks",
        "copy_engines",
        "fabric_resources",
        "rate_resources",
        "gpu_hbm_capacity_bytes_per_gpu",
        "gpu_hbm_account_stack",
        "gpu_hbm_event_boundary_snapshots",
        "per_gpu_peer_hbm_quota_enforced",
        "failed_gpu_hbm_becomes_unavailable_not_free",
    }
    if scope.resource_hardware_metadata:
        resource_keys.update({"gpu_sku", "topology", "node_count", "gpu_node_id"})
    _exact_keys(
        resources,
        resource_keys,
        f"{location}.payload.resource_model",
    )
    for field in (
        "peer_hbm_resources",
        "store_dram_segments",
        "host_dram_staging_resources",
        "copy_engines",
        "fabric_resources",
        "gpu_hbm_account_stack",
    ):
        _array(resources.get(field), f"{location}.payload.resource_model.{field}")
    _integer(
        resources.get("store_node_count"),
        f"{location}.payload.resource_model.store_node_count",
        minimum=1,
    )
    _integer(
        resources.get("slice_size_policy_chunks"),
        f"{location}.payload.resource_model.slice_size_policy_chunks",
        minimum=1,
    )
    _integer(
        resources.get("gpu_hbm_capacity_bytes_per_gpu"),
        f"{location}.payload.resource_model.gpu_hbm_capacity_bytes_per_gpu",
        minimum=1,
    )
    _equal(
        resources.get("gpu_hbm_capacity_bytes_per_gpu"),
        scope.hbm_bytes_per_gpu,
        f"{location}.payload.resource_model.gpu_hbm_capacity_bytes_per_gpu",
    )
    if scope.resource_hardware_metadata:
        _equal(
            resources.get("gpu_sku"),
            "NVIDIA-A100-40GB",
            f"{location}.payload.resource_model.gpu_sku",
        )
        _equal(
            resources.get("topology"),
            "single_node",
            f"{location}.payload.resource_model.topology",
        )
        _equal(
            resources.get("gpu_node_id"),
            "node-inference-0",
            f"{location}.payload.resource_model.gpu_node_id",
        )
        _equal(
            resources.get("node_count"),
            1,
            f"{location}.payload.resource_model.node_count",
        )
    _equal(
        resources.get("communication_backend"),
        "flow_contention",
        f"{location}.payload.resource_model.communication_backend",
    )
    _equal(
        resources.get("fairness"),
        "weighted_max_min_work_conserving",
        f"{location}.payload.resource_model.fairness",
    )
    _equal(
        resources.get("flow_clock"),
        "shared_global_des_now_ns",
        f"{location}.payload.resource_model.flow_clock",
    )
    if resources.get("store_transport") not in {
        "PCIE",
        "RDMA_GDR",
        "RDMA_HOST_STAGED",
        "TCP_HOST_STAGED",
    }:
        raise AuditFailure(f"{location}.payload.resource_model.store_transport: invalid")
    rate_resources = _object(
        resources.get("rate_resources"),
        f"{location}.payload.resource_model.rate_resources",
    )
    if not rate_resources or any(
        isinstance(rate, bool)
        or not isinstance(rate, (int, float))
        or not math.isfinite(rate)
        or rate <= 0
        for rate in rate_resources.values()
    ):
        raise AuditFailure(
            f"{location}.payload.resource_model.rate_resources: expected positive finite rates"
        )
    for field in (
        "host_staging_capacity_transactions",
        "source_pin_overlay_without_double_charge",
        "gpu_hbm_event_boundary_snapshots",
    ):
        _equal(resources.get(field), True, f"{location}.payload.resource_model.{field}")
    _equal(
        resources.get("per_gpu_peer_hbm_quota_enforced"),
        True,
        f"{location}.payload.resource_model.per_gpu_peer_hbm_quota_enforced",
    )
    _equal(
        resources.get("failed_gpu_hbm_becomes_unavailable_not_free"),
        True,
        f"{location}.payload.resource_model.failed_gpu_hbm_becomes_unavailable_not_free",
    )
    _equal(
        payload.get("recovery_model"),
        {
            "committed_replica_only": True,
            "continuous_prefix_only": True,
            "in_flight_protection_estimate_used": False,
            "missing_suffix_recomputed": True,
            "phase_order": [
                "RESTORE_COMMITTED_PREFIX",
                "PROMPT_SUFFIX_RECOMPUTE",
                "SILENT_REPLAY_COMMITTED_OUTPUT",
                "ATOMIC_ACTIVATION",
                "REMAINING_DECODE",
            ],
        },
        f"{location}.payload.recovery_model",
    )
    workload = _object(payload.get("workload"), f"{location}.payload.workload")
    _equal(
        workload.get("no_truncation_or_padding"),
        True,
        f"{location}.payload.workload.no_truncation_or_padding",
    )
    _equal(
        payload.get("context_bucket"),
        row.get("context_bucket"),
        f"{location}.payload.context_bucket",
    )
    _equal(payload.get("scenario"), row.get("scenario"), f"{location}.payload.scenario")
    bindings = _object(row.get("bindings"), f"{location}.bindings")
    _equal(
        payload.get("variant_fingerprint"),
        bindings.get("variant_fingerprint"),
        f"{location}.payload.variant_fingerprint",
    )
    forbidden = _object(
        payload.get("forbidden_semantics"), f"{location}.payload.forbidden_semantics"
    )
    expected_forbidden = {
        "hbm_to_dram_writeback_count",
        "target_owned_destage_count",
        "dram_prerequisite_for_hbm_count",
        "cross_tier_abort_propagation_count",
        "second_directory_count",
        "ssd_nvme_event_count",
    }
    _exact_keys(forbidden, expected_forbidden, f"{location}.payload.forbidden_semantics")
    if any(type(value) is not int or value != 0 for value in forbidden.values()):
        raise AuditFailure(
            f"{location}.payload.forbidden_semantics: every count must be integer zero"
        )
    output = _object(payload.get("output_audit"), f"{location}.payload.output_audit")
    _exact_keys(
        output,
        {
            "expected_output_tokens",
            "external_output_tokens",
            "duplicate_or_missing_tokens",
            "stale_route_output_count",
        },
        f"{location}.payload.output_audit",
    )
    expected = _integer(
        output.get("expected_output_tokens"),
        f"{location}.payload.output_audit.expected_output_tokens",
    )
    external = _integer(
        output.get("external_output_tokens"),
        f"{location}.payload.output_audit.external_output_tokens",
    )
    _equal(external, expected, f"{location}.payload.output_audit.external_output_tokens")
    _equal(
        output.get("duplicate_or_missing_tokens"),
        0,
        f"{location}.payload.output_audit.duplicate_or_missing_tokens",
    )
    _equal(
        output.get("stale_route_output_count"),
        0,
        f"{location}.payload.output_audit.stale_route_output_count",
    )
    scenario = row.get("scenario")
    schedule = payload.get("failure_schedule")
    if scenario == "no_failure":
        _equal(schedule, None, f"{location}.payload.failure_schedule")
    else:
        schedule_object = _object(schedule, f"{location}.payload.failure_schedule")
        _equal(
            schedule_object.get("type"), "GPU_FAILURE", f"{location}.payload.failure_schedule.type"
        )
        if "failure_count" in row:
            _equal(
                schedule_object.get("failure_count"),
                row.get("failure_count"),
                f"{location}.payload.failure_schedule.failure_count",
            )


def _validate_multi_failure_schedule(
    schedule: dict[str, Any],
    *,
    location: str,
    context_bucket: str,
    seed: int,
    failure_count: int,
) -> None:
    _exact_keys(
        schedule,
        {"type", "failure_count", "selection_scope", "events"},
        location,
    )
    _equal(schedule.get("type"), "GPU_FAILURE", f"{location}.type")
    _equal(schedule.get("failure_count"), failure_count, f"{location}.failure_count")
    events = _array(schedule.get("events"), f"{location}.events")
    _equal(len(events), failure_count, f"{location}.events length")
    progresses: list[int] = []
    focus_span_ids: list[str] = []
    failure_ids: list[str] = []
    for event_index, raw_event in enumerate(events):
        event_location = f"{location}.events[{event_index}]"
        event = _object(raw_event, event_location)
        routing_fields = {"target_gpu_id_semantics", "impact_contract", "profile_impact_contracts"}
        has_routing_semantics = bool(routing_fields & event.keys())
        _exact_keys(
            event,
            {
                "failure_id",
                "event_index",
                "type",
                "bucket",
                "seed",
                "focus_span_id",
                "target_gpu_id",
                "workload_position",
                "trigger",
                "reference_at_ns",
                "reference_at_ns_semantics",
                "detection_delay_ns",
                "selection_scope",
                "repair_after_ns",
                "parameter_source",
            } | (routing_fields if has_routing_semantics else set()),
            event_location,
        )
        if has_routing_semantics:
            semantics = event["target_gpu_id_semantics"]
            if semantics not in {
                "FROZEN_PHYSICAL_FAILURE_TARGET",
                "REFERENCE_ROUTE_PROVENANCE_NOT_RUNTIME_FAILURE_TARGET",
            }:
                raise AuditFailure(f"{event_location}: unknown physical target semantics")
            shared = event["impact_contract"]
            profiles = event["profile_impact_contracts"]
            if shared is not None and profiles is not None:
                raise AuditFailure(f"{event_location}: shared/profile victim contracts conflict")
            if (
                shared is not None or profiles is not None
            ) and semantics != "FROZEN_PHYSICAL_FAILURE_TARGET":
                raise AuditFailure(
                    f"{event_location}: victim contract lacks frozen physical target"
                )
            contracts = [] if shared is None else [shared]
            if profiles is not None:
                profile_map = _object(profiles, f"{event_location}.profile_impact_contracts")
                if not profile_map:
                    raise AuditFailure(f"{event_location}: empty profile impact contracts")
                for profile, contract in profile_map.items():
                    _hex(profile, f"{event_location}.profile_fingerprint")
                    contracts.append(contract)
            for raw_contract in contracts:
                contract = _object(raw_contract, f"{event_location}.impact_contract")
                _exact_keys(contract, {
                    "kind", "active_span_ids", "queued_span_ids", "reroute_only_queued_span_ids",
                }, f"{event_location}.impact_contract")
                _equal(contract["kind"], "EXACT_NATURAL_PRE_FENCE_REQUEST_PARTITION",
                       f"{event_location}.impact_contract.kind")
                partitions = []
                for field in ("active_span_ids", "queued_span_ids", "reroute_only_queued_span_ids"):
                    ids = _array(contract[field], f"{event_location}.impact_contract.{field}")
                    if any(not isinstance(value, str) or not value for value in ids):
                        raise AuditFailure(f"{event_location}: malformed victim ID")
                    if ids != sorted(set(ids)):
                        raise AuditFailure(
                            f"{event_location}: victim IDs must be sorted and unique"
                        )
                    partitions.append(set(ids))
                active, queued, reroute = partitions
                if active & queued or not reroute <= queued or event["focus_span_id"] not in active:
                    raise AuditFailure(f"{event_location}: inconsistent impact partitions")
        _equal(event.get("event_index"), event_index, f"{event_location}.event_index")
        _equal(event.get("type"), "GPU_FAILURE", f"{event_location}.type")
        _equal(event.get("bucket"), context_bucket, f"{event_location}.bucket")
        _equal(event.get("seed"), seed, f"{event_location}.seed")
        failure_ids.append(_string(event.get("failure_id"), f"{event_location}.failure_id"))
        focus_span_ids.append(
            _string(event.get("focus_span_id"), f"{event_location}.focus_span_id")
        )
        _string(event.get("target_gpu_id"), f"{event_location}.target_gpu_id")
        position = _object(event.get("workload_position"), f"{event_location}.workload_position")
        _exact_keys(
            position,
            {
                "kind",
                "target_progress_per_mille",
                "reference_completed_workflow_count",
                "reference_workflow_count",
            },
            f"{event_location}.workload_position",
        )
        progress = _integer(
            position.get("target_progress_per_mille"),
            f"{event_location}.workload_position.target_progress_per_mille",
            minimum=1,
        )
        if progress > 999:
            raise AuditFailure(f"{event_location}: workload progress is outside (0, 1000)")
        progresses.append(progress)
        workflow_count = _integer(
            position.get("reference_workflow_count"),
            f"{event_location}.workload_position.reference_workflow_count",
            minimum=1,
        )
        completed_count = _integer(
            position.get("reference_completed_workflow_count"),
            f"{event_location}.workload_position.reference_completed_workflow_count",
        )
        if completed_count >= workflow_count:
            raise AuditFailure(f"{event_location}: completed workflow count is invalid")
        trigger = _object(event.get("trigger"), f"{event_location}.trigger")
        _exact_keys(trigger, {"kind", "progress_per_mille"}, f"{event_location}.trigger")
        _equal(
            trigger.get("kind"),
            "FOCUS_SPAN_COMPUTE_PROGRESS",
            f"{event_location}.trigger.kind",
        )
        trigger_progress = _integer(
            trigger.get("progress_per_mille"),
            f"{event_location}.trigger.progress_per_mille",
            minimum=1,
        )
        if trigger_progress > 999:
            raise AuditFailure(f"{event_location}: request progress is outside (0, 1000)")
        _integer(event.get("reference_at_ns"), f"{event_location}.reference_at_ns")
        _integer(event.get("detection_delay_ns"), f"{event_location}.detection_delay_ns")
        repair_after_ns = event.get("repair_after_ns")
        if repair_after_ns is not None:
            _integer(repair_after_ns, f"{event_location}.repair_after_ns", minimum=1)
    if progresses != sorted(set(progresses)):
        raise AuditFailure(f"{location}: workload progress targets are not strictly increasing")
    if len(set(focus_span_ids)) != len(focus_span_ids):
        raise AuditFailure(f"{location}: focus spans are not unique")
    if len(set(failure_ids)) != len(failure_ids):
        raise AuditFailure(f"{location}: failure IDs are not unique")


def _validate_result_row(row: dict[str, Any], index: int, scope: AuditScope) -> None:
    location = f"results.jsonl:{index}"
    row_keys = {
        "schema",
        "status",
        "run_id",
        "pair_id",
        "suite",
        "variant_id",
        "variant_config",
        "context_bucket",
        "scenario",
        "seed",
        "repetition",
        "fresh_global_des_instance",
        "evidence",
        "model_deployment",
        "bindings",
        "payload_sha256",
        "journal_sha256",
        "payload",
    }
    has_failure_sample_index = "independent_failure_sample_index" in row
    has_failure_count = "failure_count" in row
    if has_failure_sample_index and has_failure_count:
        raise AuditFailure(f"{location}: mixed legacy sample and multi-failure fields")
    if has_failure_sample_index:
        row_keys.add("independent_failure_sample_index")
    if has_failure_count:
        row_keys.add("failure_count")
    _exact_keys(
        row,
        row_keys,
        location,
    )
    _equal(row["schema"], f"{MATRIX_SCHEMA}.result_row", f"{location}.schema")
    _equal(row["status"], "PASS", f"{location}.status")
    _equal(row["fresh_global_des_instance"], True, f"{location}.fresh_global_des_instance")
    _equal(row["evidence"], MATRIX_EVIDENCE, f"{location}.evidence")
    suite = _string(row["suite"], f"{location}.suite")
    variant_id = _string(row["variant_id"], f"{location}.variant_id")
    bucket = _string(row["context_bucket"], f"{location}.context_bucket")
    scenario = _string(row["scenario"], f"{location}.scenario")
    seed = _integer(row["seed"], f"{location}.seed")
    repetition = _string(row["repetition"], f"{location}.repetition")
    if bucket not in BUCKETS or scenario not in SCENARIOS or repetition not in REPETITIONS:
        raise AuditFailure(f"{location}: invalid bucket/scenario/repetition")
    sample_index = row.get("independent_failure_sample_index")
    observed_failure_count = row.get("failure_count")
    if has_failure_sample_index:
        if scenario == "no_failure":
            _equal(sample_index, None, f"{location}.independent_failure_sample_index")
            sample_suffix = ""
        else:
            sample_index = _integer(
                sample_index,
                f"{location}.independent_failure_sample_index",
            )
            sample_suffix = f":failure-sample-{sample_index}"
    else:
        sample_suffix = ""
    if has_failure_count:
        failure_count = _integer(
            observed_failure_count,
            f"{location}.failure_count",
        )
        if scenario == "no_failure":
            _equal(failure_count, 0, f"{location}.failure_count")
        elif failure_count <= 0:
            raise AuditFailure(f"{location}.failure_count: expected positive integer")
    pair_id = f"{suite}:{variant_id}:{bucket}:{scenario}:seed-{seed}{sample_suffix}"
    _equal(row["pair_id"], pair_id, f"{location}.pair_id")
    _equal(row["run_id"], f"{pair_id}:repeat-{repetition}", f"{location}.run_id")
    variant = _object(row["variant_config"], f"{location}.variant_config")
    _equal(variant.get("suite"), suite, f"{location}.variant_config.suite")
    _equal(variant.get("variant_id"), variant_id, f"{location}.variant_config.variant_id")
    bindings = _object(row["bindings"], f"{location}.bindings")
    binding_keys = {
        "implementation_fingerprint",
        "workload_fingerprint",
        "protocol_fingerprint",
        "variant_fingerprint",
        "parameters_fingerprint",
        "context_bucket",
        "scenario",
        "seed",
        "workflow_concurrency",
        "failure_schedule_fingerprint",
        "failure_binding_fingerprint",
        "matched_input_fingerprint",
        "cell_fingerprint",
        "implementation_commit",
        "workload_sha256",
    }
    if has_failure_sample_index:
        binding_keys.add("independent_failure_sample_index")
    if has_failure_count:
        binding_keys.add("failure_count")
    _exact_keys(bindings, binding_keys, f"{location}.bindings")
    for key in binding_keys - {
        "context_bucket",
        "scenario",
        "seed",
        "workflow_concurrency",
        "independent_failure_sample_index",
        "failure_count",
        "implementation_commit",
    }:
        _hex(bindings.get(key), f"{location}.bindings.{key}")
    _hex(
        bindings.get("implementation_commit"),
        f"{location}.bindings.implementation_commit",
        length=40,
    )
    _equal(bindings.get("context_bucket"), bucket, f"{location}.bindings.context_bucket")
    _equal(bindings.get("scenario"), scenario, f"{location}.bindings.scenario")
    _equal(bindings.get("seed"), seed, f"{location}.bindings.seed")
    if has_failure_sample_index:
        _equal(
            bindings.get("independent_failure_sample_index"),
            sample_index,
            f"{location}.bindings.independent_failure_sample_index",
        )
    if has_failure_count:
        _equal(
            bindings.get("failure_count"),
            observed_failure_count,
            f"{location}.bindings.failure_count",
        )
    if bindings.get("workflow_concurrency") is not None:
        _integer(
            bindings.get("workflow_concurrency"),
            f"{location}.bindings.workflow_concurrency",
            minimum=1,
        )
    _equal(
        bindings.get("variant_fingerprint"),
        _sha256_json(variant),
        f"{location}.bindings.variant_fingerprint",
    )
    parameters = _object(variant.get("parameters"), f"{location}.variant_config.parameters")
    dp_count = _integer(
        parameters.get("dp_count"),
        f"{location}.variant_config.parameters.dp_count",
        minimum=1,
    )
    if dp_count not in scope.allowed_dp_counts:
        raise AuditFailure(f"{location}: data-parallel size is outside the locked scope")
    hbm_bytes = _integer(
        parameters.get("physical_hbm_bytes_per_gpu"),
        f"{location}.variant_config.parameters.physical_hbm_bytes_per_gpu",
        minimum=1,
    )
    if hbm_bytes != scope.hbm_bytes_per_gpu:
        raise AuditFailure(f"{location}: GPU HBM is outside the declared scope")
    expected_deployment = _expected_model_deployment(dp_count, scope)
    _equal(row.get("model_deployment"), expected_deployment, f"{location}.model_deployment")
    _equal(
        parameters.get("model_deployment"),
        expected_deployment,
        f"{location}.variant_config.parameters.model_deployment",
    )
    _equal(
        bindings.get("parameters_fingerprint"),
        _sha256_json(parameters),
        f"{location}.bindings.parameters_fingerprint",
    )
    matched_keys = [
            "implementation_fingerprint",
            "workload_fingerprint",
            "protocol_fingerprint",
            "variant_fingerprint",
            "parameters_fingerprint",
            "context_bucket",
            "scenario",
            "seed",
    ]
    if has_failure_sample_index:
        matched_keys.append("independent_failure_sample_index")
    if has_failure_count:
        matched_keys.append("failure_count")
    matched_keys.extend(
        [
            "workflow_concurrency",
            "failure_schedule_fingerprint",
            "failure_binding_fingerprint",
        ]
    )
    matched = {key: bindings[key] for key in matched_keys}
    _equal(
        bindings.get("matched_input_fingerprint"),
        _sha256_json(matched),
        f"{location}.bindings.matched_input_fingerprint",
    )
    _equal(
        bindings.get("cell_fingerprint"),
        _sha256_json(
            {
                "matched_input_fingerprint": bindings["matched_input_fingerprint"],
                "repetition": repetition,
            }
        ),
        f"{location}.bindings.cell_fingerprint",
    )
    _validate_payload(row, location, scope)
    payload = _object(row["payload"], f"{location}.payload")
    _equal(row["payload_sha256"], _sha256_json(payload), f"{location}.payload_sha256")
    _hex(row["journal_sha256"], f"{location}.journal_sha256")


def _validate_representative_semantics(representative: dict[str, Any]) -> None:
    runtime = _object(representative.get("representative"), "representative.representative")
    failures = _array(runtime.get("failure_events"), "representative.failure_events")
    recoveries = _array(runtime.get("recovery_events"), "representative.recovery_events")
    transfers = _array(runtime.get("transfers"), "representative.transfers")
    payload = _object(representative.get("payload"), "representative.payload")
    schedule = _object(payload.get("failure_schedule"), "representative.payload.failure_schedule")
    scheduled_events = (
        _array(schedule.get("events"), "representative.payload.failure_schedule.events")
        if "events" in schedule
        else [schedule]
    )
    if len(failures) != len(scheduled_events):
        raise AuditFailure(
            "representative.failure_events: count diverged from the frozen schedule"
        )
    scheduled_by_id = {
        _string(
            _object(item, f"representative.payload.failure_schedule.events[{index}]").get(
                "failure_id"
            ),
            f"representative.payload.failure_schedule.events[{index}].failure_id",
        ): _object(item, f"representative.payload.failure_schedule.events[{index}]")
        for index, item in enumerate(scheduled_events)
    }
    active_failure_times: dict[str, int] = {}
    target_final_repair: dict[str, bool] = {}
    for failure_index, raw_failure in enumerate(failures):
        failure_location = f"representative.failure_events[{failure_index}]"
        failure = _object(raw_failure, failure_location)
        failure_id = _string(failure.get("failure_id"), f"{failure_location}.failure_id")
        try:
            scheduled_event = scheduled_by_id[failure_id]
        except KeyError as error:
            raise AuditFailure(
                f"{failure_location}.failure_id: absent from the frozen schedule"
            ) from error
        failure_at = _integer(failure.get("timestamp_ns"), f"{failure_location}.timestamp_ns")
        trigger = _object(failure.get("logical_trigger"), f"{failure_location}.logical_trigger")
        _equal(
            trigger.get("resolved_at_ns"),
            failure_at,
            f"{failure_location}.logical_trigger.resolved_at_ns",
        )
        focus_span_id = _string(
            trigger.get("focus_span_id"),
            f"{failure_location}.logical_trigger.focus_span_id",
        )
        _equal(
            focus_span_id,
            scheduled_event.get("focus_span_id"),
            f"{failure_location}.logical_trigger.focus_span_id",
        )
        progress = _integer(
            trigger.get("progress_per_mille"),
            f"{failure_location}.logical_trigger.progress_per_mille",
        )
        if not 1 <= progress <= 999:
            raise AuditFailure(f"{failure_location}: logical trigger is outside (0, 1000)")
        scheduled_trigger = _object(
            scheduled_event.get("trigger"),
            f"{failure_location}.scheduled_trigger",
        )
        _equal(
            progress,
            scheduled_trigger.get("progress_per_mille"),
            f"{failure_location}.logical_trigger.progress_per_mille",
        )
        target_gpu = _string(
            failure.get("target_gpu_id"), f"{failure_location}.target_gpu_id"
        )
        _equal(
            target_gpu,
            scheduled_event.get("target_gpu_id"),
            f"{failure_location}.target_gpu_id",
        )
        active_span_ids = _array(
            failure.get("impacted_active_span_ids"),
            f"{failure_location}.impacted_active_span_ids",
        )
        if focus_span_id not in active_span_ids:
            raise AuditFailure(f"{failure_location}: logical focus span was not actively failed")
        for span_id_value in active_span_ids:
            span_id = _string(span_id_value, f"{failure_location}.impacted_active_span_ids")
            if span_id in active_failure_times:
                raise AuditFailure(
                    f"{failure_location}: one span was actively impacted by multiple failures"
                )
            active_failure_times[span_id] = failure_at
        repair_after_ns = scheduled_event.get("repair_after_ns")
        repaired = repair_after_ns is not None
        if repaired:
            repair_after_ns = _integer(
                repair_after_ns,
                f"{failure_location}.scheduled_repair_after_ns",
                minimum=1,
            )
            repair_completed_at_ns = _integer(
                failure.get("repair_completed_at_ns"),
                f"{failure_location}.repair_completed_at_ns",
            )
            _equal(
                repair_completed_at_ns,
                failure_at + repair_after_ns,
                f"{failure_location}.repair_completed_at_ns",
            )
        else:
            _equal(
                failure.get("repair_completed_at_ns"),
                None,
                f"{failure_location}.repair_completed_at_ns",
            )
        target_final_repair[target_gpu] = repaired

    expected_phases = [
        "RECOVERY_PLAN",
        "PROMPT_SUFFIX_RECOMPUTE_START",
        "PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
        "SILENT_REPLAY_START",
        "SILENT_REPLAY_COMPLETE",
        "RECOVERY_ATOMIC_ACTIVATION",
    ]
    phases_by_span: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for index, raw_event in enumerate(recoveries):
        event = _object(raw_event, f"representative.recovery_events[{index}]")
        span_id = _string(event.get("span_id"), f"representative.recovery_events[{index}].span_id")
        timestamp = _integer(
            event.get("timestamp_ns"),
            f"representative.recovery_events[{index}].timestamp_ns",
        )
        name = _string(event.get("event"), f"representative.recovery_events[{index}].event")
        phases_by_span[span_id].append((timestamp, name))
    for span_id, failure_at in active_failure_times.items():
        phases = phases_by_span.get(str(span_id), [])
        if [name for _timestamp, name in phases] != expected_phases:
            raise AuditFailure(f"representative recovery phases drifted for {span_id}")
        timestamps = [timestamp for timestamp, _name in phases]
        if timestamps != sorted(timestamps) or timestamps[0] < failure_at:
            raise AuditFailure(f"representative recovery timestamps drifted for {span_id}")

    if not transfers:
        raise AuditFailure("representative.transfers: expected terminal transfer rows")
    saw_aborted = False
    for index, raw_transfer in enumerate(transfers):
        location = f"representative.transfers[{index}]"
        transfer = _object(raw_transfer, location)
        status = _string(transfer.get("status"), f"{location}.status")
        if status not in {"COMMITTED", "ABORTED"}:
            raise AuditFailure(f"{location}.status: non-terminal transfer")
        submitted = _integer(transfer.get("bytes"), f"{location}.bytes")
        moved = _integer(
            transfer.get("transferred_bytes"), f"{location}.transferred_bytes"
        )
        aborted = _integer(transfer.get("aborted_bytes"), f"{location}.aborted_bytes")
        if submitted != moved + aborted:
            raise AuditFailure(f"{location}: submitted bytes do not conserve")
        saw_aborted = saw_aborted or status == "ABORTED"
        _string(transfer.get("span_id"), f"{location}.span_id")
        start = _integer(transfer.get("start_ns"), f"{location}.start_ns")
        end = _integer(transfer.get("end_ns"), f"{location}.end_ns")
        planned_end = _integer(
            transfer.get("planned_end_ns"), f"{location}.planned_end_ns"
        )
        terminal = _integer(transfer.get("terminal_ns"), f"{location}.terminal_ns")
        if end < start or end > planned_end or terminal > planned_end:
            raise AuditFailure(f"{location}: terminal interval is inconsistent")
        for resource_index, raw_interval in enumerate(
            _array(transfer.get("resource_intervals"), f"{location}.resource_intervals")
        ):
            interval_location = f"{location}.resource_intervals[{resource_index}]"
            interval = _object(raw_interval, interval_location)
            interval_start = _integer(
                interval.get("start_ns"), f"{interval_location}.start_ns"
            )
            actual_end = _integer(
                interval.get("actual_end_ns"), f"{interval_location}.actual_end_ns"
            )
            interval_planned_end = _integer(
                interval.get("planned_end_ns"),
                f"{interval_location}.planned_end_ns",
            )
            if not interval_start <= actual_end <= interval_planned_end:
                raise AuditFailure(f"{interval_location}: actual interval is inconsistent")
    state_counts = _object(
        _object(
            _object(representative.get("payload"), "representative.payload").get("metrics"),
            "representative.payload.metrics",
        ).get("resource_cost"),
        "representative.payload.metrics.resource_cost",
    ).get("transfer_state_counts")
    counts = _object(state_counts, "representative transfer_state_counts")
    _equal(
        counts.get("ABORTED", 0),
        sum(1 for item in transfers if _object(item, "transfer row").get("status") == "ABORTED"),
        "representative aborted transfer count",
    )
    if saw_aborted and counts.get("ABORTED", 0) == 0:
        raise AuditFailure("representative aborted transfer count was lost")

    peer_timelines = _object(
        runtime.get("peer_hbm_timelines"), "representative.peer_hbm_timelines"
    )
    for timeline_name, raw_timeline in (
        *peer_timelines.items(),
        *(
            (name, timeline)
            for name, timeline in _object(
                runtime.get("store_dram_timelines"),
                "representative.store_dram_timelines",
            ).items()
        ),
    ):
        points = _array(raw_timeline, f"representative.timeline.{timeline_name}")
        if not points:
            raise AuditFailure(f"representative.timeline.{timeline_name}: empty")
        saw_pending = False
        for point_index, raw_point in enumerate(points):
            point_location = f"representative.timeline.{timeline_name}[{point_index}]"
            point = _object(raw_point, point_location)
            occupied = _integer(point.get("occupied_bytes"), f"{point_location}.occupied")
            committed = _integer(point.get("committed_bytes"), f"{point_location}.committed")
            pending = _integer(point.get("pending_bytes"), f"{point_location}.pending")
            if occupied != committed + pending:
                raise AuditFailure(f"{point_location}: occupancy does not conserve")
            saw_pending = saw_pending or pending > 0
        final = _object(points[-1], f"representative.timeline.{timeline_name}[-1]")
        _equal(final.get("pending_bytes"), 0, f"representative.timeline.{timeline_name}.final")
        if not saw_pending:
            raise AuditFailure(f"representative.timeline.{timeline_name}: no pending reserve seen")
    for target_gpu, repaired in target_final_repair.items():
        failed_timeline = _array(
            peer_timelines.get(target_gpu),
            f"representative.peer_hbm_timelines.{target_gpu}",
        )
        failed_final = _object(
            failed_timeline[-1], f"representative failed Peer-HBM final {target_gpu}"
        )
        unavailable_history = [
            _integer(
                _object(point, "representative failed Peer-HBM point").get(
                    "unavailable_bytes"
                ),
                "representative failed Peer-HBM unavailable bytes",
            )
            for point in failed_timeline
        ]
        if not any(value > 0 for value in unavailable_history):
            raise AuditFailure(f"failed Peer-HBM {target_gpu} did not become unavailable")
        final_unavailable = _integer(
            failed_final.get("unavailable_bytes"), "failed unavailable bytes"
        )
        if not repaired and final_unavailable <= 0:
            raise AuditFailure("unrepaired Peer-HBM did not remain unavailable")
        if repaired and final_unavailable != 0:
            raise AuditFailure("repaired Peer-HBM did not return empty usable capacity")


def _expected_run_ids(protocol: dict[str, Any], scope: AuditScope) -> set[str]:
    _exact_keys(
        protocol,
        {
            "schema",
            "status",
            "evidence",
            "model_deployment_contract",
            "global_clock",
            "failure_types",
            "physical_or_slurm_path",
            "suite_catalog",
            "default_contract",
            "execution",
            "fingerprint",
        },
        "protocol",
    )
    _equal(
        protocol.get("model_deployment_contract"),
        scope.model_deployment_contract,
        "protocol.model_deployment_contract",
    )
    catalog = _object(protocol.get("suite_catalog"), "protocol.suite_catalog")
    _equal(set(catalog), set(scope.variants), "protocol.suite_catalog suites")
    execution = _object(protocol.get("execution"), "protocol.execution")
    has_failure_samples = "independent_failure_sample_count" in execution
    has_multi_failure_cell = "failure_count_per_failure_cell" in execution
    if has_failure_samples and has_multi_failure_cell:
        raise AuditFailure("protocol.execution mixes legacy samples and multi-failure cells")
    failure_sample_count = (
        _integer(
            execution.get("independent_failure_sample_count"),
            "protocol.execution.independent_failure_sample_count",
            minimum=1,
        )
        if has_failure_samples
        else 1
    )
    default_failure_sample_count = 2 if has_failure_samples else 1
    if has_multi_failure_cell:
        _integer(
            execution.get("failure_count_per_failure_cell"),
            "protocol.execution.failure_count_per_failure_cell",
            minimum=1,
        )
    cross_product = [
        "variant_id",
        "context_bucket",
        "scenario",
        "seed",
    ]
    if has_failure_samples:
        cross_product.append("independent_failure_sample_index")
    cross_product.append("repetition")
    default_rows: dict[str, int] = {}
    for suite_name, variants in scope.variants.items():
        descriptor = _object(catalog[suite_name], f"protocol.suite_catalog.{suite_name}")
        _exact_keys(
            descriptor,
            {
                "variant_ids",
                "variant_count",
                "cross_product",
                "default_seed_count",
                "default_expected_pair_count",
                "default_expected_row_count",
            },
            f"protocol.suite_catalog.{suite_name}",
        )
        pair_count = (
            len(variants)
            * len(BUCKETS)
            * (2 if has_multi_failure_cell else 1 + default_failure_sample_count)
            * 3
        )
        row_count = pair_count * len(REPETITIONS)
        default_rows[suite_name] = row_count
        _equal(
            descriptor["variant_ids"],
            list(variants),
            f"protocol.suite_catalog.{suite_name}.variant_ids",
        )
        _equal(
            descriptor["variant_count"],
            len(variants),
            f"protocol.suite_catalog.{suite_name}.variant_count",
        )
        _equal(
            descriptor["cross_product"],
            cross_product,
            f"protocol.suite_catalog.{suite_name}.cross_product",
        )
        _equal(
            descriptor["default_seed_count"],
            3,
            f"protocol.suite_catalog.{suite_name}.default_seed_count",
        )
        _equal(
            descriptor["default_expected_pair_count"],
            pair_count,
            f"protocol.suite_catalog.{suite_name}.default_expected_pair_count",
        )
        _equal(
            descriptor["default_expected_row_count"],
            row_count,
            f"protocol.suite_catalog.{suite_name}.default_expected_row_count",
        )
    expected_default_contract = {
        "seeds": [0, 1, 2],
        "core_expected_rows": default_rows["core"],
        "ablation_expected_rows": default_rows["ablation"],
        "sensitivity_expected_rows": default_rows["sensitivity"],
        "all_expected_rows": sum(default_rows.values()),
    }
    if has_failure_samples:
        expected_default_contract["independent_failure_sample_count"] = (
            default_failure_sample_count
        )
    if has_multi_failure_cell:
        expected_default_contract["failure_count_per_failure_cell"] = 2
    _equal(
        protocol.get("default_contract"),
        expected_default_contract,
        "protocol.default_contract",
    )
    selection = execution.get("selection")
    expected_suites = ["core"] if selection == "core" else ["core", "ablation", "sensitivity"]
    if selection not in {"core", "all"}:
        raise AuditFailure("protocol.execution.selection: only core or all is allowed")
    _equal(execution.get("included_suites"), expected_suites, "protocol.execution.included_suites")
    _equal(execution.get("context_buckets"), list(BUCKETS), "protocol.execution.context_buckets")
    _equal(execution.get("scenarios"), list(SCENARIOS), "protocol.execution.scenarios")
    _equal(execution.get("repetitions"), list(REPETITIONS), "protocol.execution.repetitions")
    _equal(
        execution.get("silent_fallback_allowed"),
        False,
        "protocol.execution.silent_fallback_allowed",
    )
    _equal(
        execution.get("fresh_global_des_per_repetition"),
        True,
        "protocol.execution.fresh_global_des_per_repetition",
    )
    _equal(
        execution.get("required_pair_hashes"),
        ["payload_sha256", "journal_sha256"],
        "protocol.execution.required_pair_hashes",
    )
    seeds_raw = _array(execution.get("seeds"), "protocol.execution.seeds")
    seeds = [
        _integer(seed, f"protocol.execution.seeds[{index}]") for index, seed in enumerate(seeds_raw)
    ]
    if not seeds or seeds != sorted(set(seeds)):
        raise AuditFailure("protocol.execution.seeds: must be non-empty, sorted, and unique")
    suites = _object(execution.get("suites"), "protocol.execution.suites")
    _equal(set(suites), set(expected_suites), "protocol.execution.suites")
    expected_ids: set[str] = set()
    expected_pairs = 0
    for suite_name in expected_suites:
        descriptor = _object(suites[suite_name], f"protocol.execution.suites.{suite_name}")
        variant_ids = list(scope.variants[suite_name])
        _equal(
            descriptor.get("variant_ids"),
            variant_ids,
            f"protocol.execution.suites.{suite_name}.variant_ids",
        )
        pair_count = (
            len(variant_ids)
            * len(BUCKETS)
            * (2 if has_multi_failure_cell else 1 + failure_sample_count)
            * len(seeds)
        )
        _equal(
            descriptor.get("expected_pair_count"),
            pair_count,
            f"protocol.execution.suites.{suite_name}.expected_pair_count",
        )
        _equal(
            descriptor.get("expected_row_count"),
            pair_count * 2,
            f"protocol.execution.suites.{suite_name}.expected_row_count",
        )
        expected_pairs += pair_count
        for variant_id in variant_ids:
            for bucket in BUCKETS:
                for seed in seeds:
                    for repetition in REPETITIONS:
                        expected_ids.add(
                            f"{suite_name}:{variant_id}:{bucket}:no_failure:"
                            f"seed-{seed}:repeat-{repetition}"
                        )
                        for sample_index in range(
                            1 if has_multi_failure_cell else failure_sample_count
                        ):
                            suffix = (
                                f":failure-sample-{sample_index}"
                                if has_failure_samples and not has_multi_failure_cell
                                else ""
                            )
                            expected_ids.add(
                                f"{suite_name}:{variant_id}:{bucket}:gpu_failure:"
                                f"seed-{seed}{suffix}:repeat-{repetition}"
                            )
    _equal(
        execution.get("expected_pair_count"),
        expected_pairs,
        "protocol.execution.expected_pair_count",
    )
    _equal(
        execution.get("expected_row_count"),
        len(expected_ids),
        "protocol.execution.expected_row_count",
    )
    return expected_ids


def _validate_pair_audits(
    rows: tuple[dict[str, Any], ...], audits: tuple[dict[str, Any], ...]
) -> None:
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_pair.setdefault(str(row["pair_id"]), []).append(row)
    _equal(len(audits), len(by_pair), "pair-audit.jsonl count")
    audit_ids: list[str] = []
    for index, audit in enumerate(audits, start=1):
        location = f"pair-audit.jsonl:{index}"
        _exact_keys(
            audit,
            {
                "schema",
                "status",
                "pair_id",
                "run_ids",
                "fresh_global_des_instances",
                "same_process_allowed",
                "payload_sha256",
                "journal_sha256",
                "payload_sha256_exact_match",
                "journal_sha256_exact_match",
                "matched_input_fingerprint",
                "evidence",
            },
            location,
        )
        _equal(audit["schema"], f"{MATRIX_SCHEMA}.pair_audit", f"{location}.schema")
        _equal(audit["status"], "PASS", f"{location}.status")
        _equal(audit["evidence"], MATRIX_EVIDENCE, f"{location}.evidence")
        pair_id = _string(audit["pair_id"], f"{location}.pair_id")
        audit_ids.append(pair_id)
        pair_rows = sorted(by_pair.get(pair_id, ()), key=lambda row: str(row["repetition"]))
        if [row.get("repetition") for row in pair_rows] != list(REPETITIONS):
            raise AuditFailure(f"{location}: pair must contain exact A/B repetitions")
        first, second = pair_rows
        for field in ("payload_sha256", "journal_sha256"):
            _equal(second[field], first[field], f"{location}.{field} A/B exactness")
            _equal(audit[field], first[field], f"{location}.{field}")
        first_bindings = _object(first["bindings"], f"{location}.A.bindings")
        second_bindings = _object(second["bindings"], f"{location}.B.bindings")
        _equal(
            second_bindings["matched_input_fingerprint"],
            first_bindings["matched_input_fingerprint"],
            f"{location}.matched_input_fingerprint A/B exactness",
        )
        _equal(
            audit["matched_input_fingerprint"],
            first_bindings["matched_input_fingerprint"],
            f"{location}.matched_input_fingerprint",
        )
        _equal(audit["run_ids"], [first["run_id"], second["run_id"]], f"{location}.run_ids")
        _equal(audit["fresh_global_des_instances"], 2, f"{location}.fresh_global_des_instances")
        _equal(audit["same_process_allowed"], True, f"{location}.same_process_allowed")
        _equal(audit["payload_sha256_exact_match"], True, f"{location}.payload_sha256_exact_match")
        _equal(audit["journal_sha256_exact_match"], True, f"{location}.journal_sha256_exact_match")
    if audit_ids != sorted(audit_ids) or len(set(audit_ids)) != len(audit_ids):
        raise AuditFailure("pair-audit.jsonl: pair_id values must be unique and canonically sorted")


def _validate_snapshot_configs(
    matrix_dir: Path,
    scope: AuditScope,
    rows: tuple[dict[str, Any], ...],
    provenance: dict[str, Any],
) -> None:
    config_dir = matrix_dir / "configs"
    if config_dir.is_symlink() or not config_dir.is_dir():
        raise AuditFailure("matrix configs: expected a non-symlink directory")
    _equal(
        {path.name for path in config_dir.iterdir()},
        {"requests.json", "failure.json", "engine.json"},
        "matrix configs directory entries",
    )
    requests = _load_json(config_dir / "requests.json", "matrix configs requests", canonical=False)
    failure = _load_json(config_dir / "failure.json", "matrix configs failure", canonical=False)
    engine = _load_json(config_dir / "engine.json", "matrix configs engine", canonical=False)
    _equal(requests.get("schema"), "moonkvsim.aegiskv.requests.v1", "requests schema")
    engine_schema = engine.get("schema")
    if engine_schema not in {
        "moonkvsim.aegiskv.engine.v1",
        "moonkvsim.aegiskv.engine.v2",
    }:
        raise AuditFailure(
            "engine schema: expected moonkvsim.aegiskv.engine.v1 or "
            "moonkvsim.aegiskv.engine.v2"
        )
    failure_schema = failure.get("schema")
    if failure_schema == "moonkvsim.aegiskv.failure.v1":
        _equal(failure.get("allowed_types"), ["GPU_FAILURE"], "failure allowed_types")
        _equal(failure.get("type"), "GPU_FAILURE", "failure type")
        repair = _object(failure.get("repair"), "failure repair")
        _equal(repair.get("enabled"), False, "failure repair.enabled")
    elif failure_schema == "moonkvsim.aegiskv.failure.v2":
        _exact_keys(
            failure,
            {
                "schema",
                "type",
                "conditioned_progress_per_mille",
                "per_gpu_mttf_hours",
                "gpu_recovery_time_hours",
                "detection_delay_ms",
            },
            "failure v2",
        )
        _equal(failure.get("type"), "GPU_FAILURE", "failure type")
        progress = _integer(
            failure.get("conditioned_progress_per_mille"),
            "failure conditioned_progress_per_mille",
            minimum=1,
        )
        if progress > 999:
            raise AuditFailure("failure conditioned_progress_per_mille: expected integer <= 999")
        mttf = failure.get("per_gpu_mttf_hours")
        if (
            isinstance(mttf, bool)
            or not isinstance(mttf, (int, float))
            or not math.isfinite(mttf)
            or mttf <= 0
        ):
            raise AuditFailure("failure per_gpu_mttf_hours: expected positive finite number")
        recovery_time = failure.get("gpu_recovery_time_hours")
        if (
            isinstance(recovery_time, bool)
            or not isinstance(recovery_time, (int, float))
            or not math.isfinite(recovery_time)
            or recovery_time <= 0
        ):
            raise AuditFailure(
                "failure gpu_recovery_time_hours: expected positive finite number"
            )
        _integer(
            failure.get("detection_delay_ms"),
            "failure detection_delay_ms",
            minimum=1,
        )
    elif failure_schema == "moonkvsim.aegiskv.failure.v3":
        _exact_keys(
            failure,
            {
                "schema",
                "type",
                "injection_progress_percent",
                "gpu_recovery_time_minutes",
            },
            "failure v3",
        )
        _equal(failure.get("type"), "GPU_FAILURE", "failure type")
        progress = _integer(
            failure.get("injection_progress_percent"),
            "failure injection_progress_percent",
            minimum=1,
        )
        if progress > 99:
            raise AuditFailure("failure injection_progress_percent: expected integer <= 99")
        _integer(
            failure.get("gpu_recovery_time_minutes"),
            "failure gpu_recovery_time_minutes",
            minimum=1,
        )
    elif failure_schema == "moonkvsim.aegiskv.failure.v4":
        _exact_keys(
            failure,
            {
                "schema",
                "type",
                "independent_failure_sample_count",
                "injection_progress_percent",
                "gpu_recovery_time_minutes",
            },
            "failure v4",
        )
        _equal(failure.get("type"), "GPU_FAILURE", "failure type")
        _integer(
            failure.get("independent_failure_sample_count"),
            "failure independent_failure_sample_count",
            minimum=1,
        )
        progress = _integer(
            failure.get("injection_progress_percent"),
            "failure injection_progress_percent",
            minimum=1,
        )
        if progress > 99:
            raise AuditFailure("failure injection_progress_percent: expected integer <= 99")
        _integer(
            failure.get("gpu_recovery_time_minutes"),
            "failure gpu_recovery_time_minutes",
            minimum=1,
        )
    elif failure_schema == "moonkvsim.aegiskv.failure.v5":
        _exact_keys(
            failure,
            {
                "schema",
                "type",
                "failure_count",
                "injection_progress_percent",
                "gpu_recovery_time_minutes",
            },
            "failure v5",
        )
        _equal(failure.get("type"), "GPU_FAILURE", "failure type")
        _integer(
            failure.get("failure_count"),
            "failure failure_count",
            minimum=1,
        )
        progress = _integer(
            failure.get("injection_progress_percent"),
            "failure injection_progress_percent",
            minimum=1,
        )
        if progress > 99:
            raise AuditFailure("failure injection_progress_percent: expected integer <= 99")
        _integer(
            failure.get("gpu_recovery_time_minutes"),
            "failure gpu_recovery_time_minutes",
            minimum=1,
        )
    else:
        raise AuditFailure(
            "failure schema: expected moonkvsim.aegiskv.failure.v1, "
            "moonkvsim.aegiskv.failure.v2, moonkvsim.aegiskv.failure.v3, "
            "moonkvsim.aegiskv.failure.v4, or moonkvsim.aegiskv.failure.v5"
        )
    parallelism = _object(engine.get("parallelism"), "engine parallelism")
    observed_dp = sorted(
        {
            _integer(
                _object(
                    _object(row["variant_config"], "row.variant_config").get("parameters"),
                    "row.variant_config.parameters",
                ).get("dp_count"),
                "row.variant_config.parameters.dp_count",
                minimum=1,
            )
            for row in rows
        }
    )
    if engine_schema == "moonkvsim.aegiskv.engine.v1":
        _equal(engine.get("scope_id"), scope.scope_id, "engine scope_id")
        _equal(
            parallelism.get("allowed_data_parallel_sizes"),
            observed_dp,
            "engine allowed_data_parallel_sizes/results",
        )
    else:
        _exact_keys(
            engine,
            {
                "schema",
                "model",
                "parallelism",
                "hardware",
                "memory",
                "store",
                "network",
                "control",
            },
            "engine v2",
        )
        _exact_keys(
            parallelism,
            {"data_parallel_size", "tensor_parallel_size", "pipeline_parallel_size"},
            "engine v2 parallelism",
        )
        _equal(
            [parallelism.get("data_parallel_size")],
            observed_dp,
            "engine v2 data_parallel_size/results",
        )
        model = _object(engine.get("model"), "engine v2 model")
        _exact_keys(model, {"id", "revision", "kv_layout_path"}, "engine v2 model")
        _equal(model.get("id"), "Qwen/Qwen3-8B", "engine v2 model.id")
        _equal(
            model.get("revision"),
            "b968826d9c46dd6066d109eabc6255188de91218",
            "engine v2 model.revision",
        )
        memory = _object(engine.get("memory"), "engine v2 memory")
        _exact_keys(memory, {"peer_hbm_alpha"}, "engine v2 memory")
        alpha = memory.get("peer_hbm_alpha")
        if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
            raise AuditFailure("engine v2 memory.peer_hbm_alpha must be numeric")
        if not 0 <= float(alpha) <= 0.5:
            raise AuditFailure("engine v2 memory.peer_hbm_alpha must be in [0, 0.5]")
        store = _object(engine.get("store"), "engine v2 store")
        _exact_keys(
            store,
            {"kind", "capacity_bytes", "colocated_with_inference"},
            "engine v2 store",
        )
        _equal(store.get("kind"), "mooncake_dram", "engine v2 store.kind")
        _equal(store.get("capacity_bytes"), 1_000_000_000_000, "engine v2 Store 1 TB")
        _equal(
            store.get("colocated_with_inference"),
            True,
            "engine v2 Store colocation",
        )
        network = _object(engine.get("network"), "engine v2 network")
        _exact_keys(
            network,
            {"transport", "effective_bandwidth_bytes_per_second", "transfer_setup_ns"},
            "engine v2 network",
        )
        _equal(network.get("transport"), "PCIE", "engine v2 network.transport")
        _equal(
            network.get("effective_bandwidth_bytes_per_second"),
            25_000_000_000,
            "engine v2 PCIe effective bandwidth",
        )
        _integer(
            network.get("transfer_setup_ns"),
            "engine v2 network.transfer_setup_ns",
            minimum=1,
        )
    _equal(parallelism.get("tensor_parallel_size"), 1, "engine tensor_parallel_size")
    _equal(parallelism.get("pipeline_parallel_size"), 1, "engine pipeline_parallel_size")
    hardware = _object(engine.get("hardware"), "engine hardware")
    if engine_schema == "moonkvsim.aegiskv.engine.v2":
        _exact_keys(
            hardware,
            {"gpu_sku", "gpu_count", "node_count", "physical_hbm_bytes_per_gpu"},
            "engine v2 hardware",
        )
        _equal(hardware.get("gpu_sku"), "NVIDIA-A100-40GB", "engine v2 gpu_sku")
        _equal(hardware.get("gpu_count"), 8, "engine v2 gpu_count")
        _equal(hardware.get("node_count"), 1, "engine v2 node_count")
    _equal(
        hardware.get("physical_hbm_bytes_per_gpu"),
        scope.hbm_bytes_per_gpu,
        "engine physical_hbm_bytes_per_gpu",
    )
    workload = _object(provenance.get("workload"), "provenance workload")
    request_workload = _object(requests.get("workload"), "requests workload")
    frozen = _object(request_workload.get("frozen_artifact"), "requests frozen_artifact")
    for field in ("sha256", "record_count", "semantic_fingerprint"):
        _equal(frozen.get(field), workload.get(field), f"requests workload {field}")


def _validate_config_snapshot_hashes(matrix_dir: Path, value: object) -> None:
    snapshot = _object(value, "matrix manifest.config_snapshot")
    _exact_keys(snapshot, {"directory", "files"}, "matrix manifest.config_snapshot")
    _equal(snapshot.get("directory"), "configs", "matrix manifest.config_snapshot.directory")
    files = _object(snapshot.get("files"), "matrix manifest.config_snapshot.files")
    expected_names = {"requests.json", "failure.json", "engine.json"}
    _equal(set(files), expected_names, "matrix manifest.config_snapshot.files names")
    for name in sorted(expected_names):
        descriptor = _object(files[name], f"matrix manifest.config_snapshot.files.{name}")
        _exact_keys(
            descriptor,
            {"sha256", "size_bytes"},
            f"matrix manifest.config_snapshot.files.{name}",
        )
        path = matrix_dir / "configs" / name
        raw = _regular_file(path, f"matrix config snapshot {name}")
        _equal(
            len(raw),
            _integer(
                descriptor.get("size_bytes"),
                f"matrix manifest.config_snapshot.files.{name}.size_bytes",
                minimum=1,
            ),
            f"matrix config snapshot {name} size",
        )
        _equal(
            _sha256_bytes(raw),
            _hex(
                descriptor.get("sha256"),
                f"matrix manifest.config_snapshot.files.{name}.sha256",
            ),
            f"matrix config snapshot {name} SHA-256",
        )


def _validate_matrix(matrix_dir: Path) -> MatrixState:
    if matrix_dir.is_symlink() or not matrix_dir.is_dir():
        raise AuditFailure("matrix-dir: expected a non-symlink directory")
    manifest_path = _safe_child(matrix_dir, "manifest.json", "matrix manifest")
    manifest = _load_json(manifest_path, "matrix manifest")
    manifest_keys = {
        "schema",
        "status",
        "evidence",
        "artifact_hashes",
        "result_bindings",
        "result_count",
        "pair_count",
        "failure_schedule_count",
        "protocol_fingerprint",
        "completeness_fingerprint",
        "provenance_fingerprint",
        "statistics_fingerprint",
        "fingerprint",
    }
    if "config_snapshot" in manifest:
        manifest_keys.add("config_snapshot")
    _exact_keys(
        manifest,
        manifest_keys,
        "matrix manifest",
    )
    _equal(manifest["schema"], f"{MATRIX_SCHEMA}.manifest", "matrix manifest.schema")
    _equal(manifest["status"], "PASS", "matrix manifest.status")
    _equal(manifest["evidence"], MATRIX_EVIDENCE, "matrix manifest.evidence")
    _verify_fingerprint(manifest, "matrix manifest")
    declared_hashes = _object(manifest["artifact_hashes"], "matrix manifest.artifact_hashes")
    _equal(set(declared_hashes), set(MATRIX_ARTIFACTS), "matrix manifest.artifact_hashes files")
    required_entries = {"manifest.json", *MATRIX_ARTIFACTS}
    actual_entries = {path.name for path in matrix_dir.iterdir()}
    missing_entries = required_entries - actual_entries
    if missing_entries:
        raise AuditFailure(f"matrix bundle directory entries: missing {sorted(missing_entries)}")
    ancillary_entries = actual_entries - required_entries
    report_entries = {name for name in ancillary_entries if name.endswith("_REPORT.md")}
    allowed_ancillary = report_entries | ({"configs"} if "configs" in ancillary_entries else set())
    if ancillary_entries != allowed_ancillary or len(report_entries) > 1:
        raise AuditFailure(
            f"matrix bundle directory entries: unsupported extras {sorted(ancillary_entries)}"
        )
    for report_name in report_entries:
        _regular_file(matrix_dir / report_name, f"matrix report {report_name}")
    if "config_snapshot" in manifest:
        if "configs" not in ancillary_entries:
            raise AuditFailure("matrix manifest binds configs but configs directory is missing")
        _validate_config_snapshot_hashes(matrix_dir, manifest["config_snapshot"])
        config_snapshot_binding = "manifest_bound"
    elif "configs" in ancillary_entries:
        config_snapshot_binding = "reconstructed_unbound"
    else:
        config_snapshot_binding = "absent"
    artifact_hashes: dict[str, str] = {}
    artifact_paths: dict[str, Path] = {}
    for name in MATRIX_ARTIFACTS:
        descriptor = _object(declared_hashes[name], f"matrix manifest.artifact_hashes.{name}")
        _exact_keys(descriptor, {"sha256", "size_bytes"}, f"matrix manifest.artifact_hashes.{name}")
        declared_hash = _hex(descriptor["sha256"], f"matrix manifest.artifact_hashes.{name}.sha256")
        declared_size = _integer(
            descriptor["size_bytes"],
            f"matrix manifest.artifact_hashes.{name}.size_bytes",
            minimum=1,
        )
        path = _safe_child(matrix_dir, name, f"matrix artifact {name}")
        raw = _regular_file(path, f"matrix artifact {name}")
        _equal(len(raw), declared_size, f"matrix artifact {name} size")
        _equal(_sha256_bytes(raw), declared_hash, f"matrix artifact {name} SHA-256")
        artifact_hashes[name] = declared_hash
        artifact_paths[name] = path
    rows = _load_jsonl(artifact_paths["results.jsonl"], "results.jsonl")
    audits = _load_jsonl(artifact_paths["pair-audit.jsonl"], "pair-audit.jsonl")
    schedules = _load_jsonl(artifact_paths["failure-schedules.jsonl"], "failure-schedules.jsonl")
    completeness = _load_json(artifact_paths["completeness.json"], "completeness.json")
    provenance = _load_json(artifact_paths["provenance.json"], "provenance.json")
    protocol = _load_json(artifact_paths["protocol.json"], "protocol.json")
    statistics = _load_json(artifact_paths["statistics.json"], "statistics.json")
    representative = _load_json(
        artifact_paths["representative-run.json"], "representative-run.json"
    )
    scope = _scope_for_contract(provenance.get("model_deployment_contract"), protocol)
    for index, row in enumerate(rows, start=1):
        _validate_result_row(row, index, scope)
    run_ids = [str(row["run_id"]) for row in rows]
    if run_ids != sorted(run_ids) or len(set(run_ids)) != len(run_ids):
        raise AuditFailure("results.jsonl: run_id values must be unique and canonically sorted")
    _equal(manifest["result_count"], len(rows), "matrix manifest.result_count")
    expected_bindings = [
        {
            "run_id": row["run_id"],
            "payload_sha256": row["payload_sha256"],
            "journal_sha256": row["journal_sha256"],
            "cell_fingerprint": _object(row["bindings"], "row.bindings")["cell_fingerprint"],
        }
        for row in rows
    ]
    _equal(manifest["result_bindings"], expected_bindings, "matrix manifest.result_bindings")
    _equal(protocol.get("schema"), f"{MATRIX_SCHEMA}.protocol", "protocol.schema")
    _equal(protocol.get("status"), "PASS", "protocol.status")
    _equal(protocol.get("evidence"), MATRIX_EVIDENCE, "protocol.evidence")
    _equal(protocol.get("global_clock"), "single_global_virtual_clock", "protocol.global_clock")
    _equal(protocol.get("failure_types"), ["GPU_FAILURE"], "protocol.failure_types")
    _equal(protocol.get("physical_or_slurm_path"), False, "protocol.physical_or_slurm_path")
    protocol_fp = _verify_fingerprint(protocol, "protocol")
    _equal(manifest["protocol_fingerprint"], protocol_fp, "matrix manifest.protocol_fingerprint")
    expected_ids = _expected_run_ids(protocol, scope)
    _equal(set(run_ids), expected_ids, "results/protocol exact cross-product")
    for row in rows:
        bindings = _object(row["bindings"], "row.bindings")
        _equal(bindings["protocol_fingerprint"], protocol_fp, f"{row['run_id']} protocol binding")
    execution_protocol = _object(protocol.get("execution"), "protocol.execution")
    if "failure_count_per_failure_cell" in execution_protocol:
        protocol_failure_count = _integer(
            execution_protocol.get("failure_count_per_failure_cell"),
            "protocol.execution.failure_count_per_failure_cell",
            minimum=1,
        )
        for row in rows:
            expected_failure_count = (
                0 if row["scenario"] == "no_failure" else protocol_failure_count
            )
            _equal(
                row.get("failure_count"),
                expected_failure_count,
                f"{row['run_id']} failure-count binding",
            )
    workflow_concurrency = execution_protocol.get("workflow_concurrency")
    if workflow_concurrency is not None:
        _integer(
            workflow_concurrency,
            "protocol.execution.workflow_concurrency",
            minimum=1,
        )
    for row in rows:
        bindings = _object(row["bindings"], "row.bindings")
        _equal(
            bindings["workflow_concurrency"],
            workflow_concurrency,
            f"{row['run_id']} workflow concurrency binding",
        )
    declared_seeds = _array(execution_protocol.get("seeds"), "protocol.execution.seeds")
    if any(type(seed) is not int or seed < 0 for seed in declared_seeds):
        raise AuditFailure("protocol.execution.seeds: expected non-negative integers")
    try:
        expected_statistics = build_statistics(
            rows,
            seeds=tuple(int(seed) for seed in declared_seeds),
            evidence=MATRIX_EVIDENCE,
        )
    except StatisticsError as error:
        raise AuditFailure(
            f"statistics.json: cannot recompute from result rows: {error}"
        ) from error
    _equal(statistics, expected_statistics, "statistics.json exact recomputation")
    statistics_fp = _verify_fingerprint(statistics, "statistics.json")
    _equal(
        manifest["statistics_fingerprint"],
        statistics_fp,
        "matrix manifest.statistics_fingerprint",
    )
    _validate_pair_audits(rows, audits)
    _equal(manifest["pair_count"], len(audits), "matrix manifest.pair_count")
    _exact_keys(
        completeness,
        {
            "schema",
            "status",
            "expected_row_count",
            "actual_row_count",
            "expected_pair_count",
            "actual_pair_count",
            "duplicate_run_ids",
            "missing_run_ids",
            "unexpected_run_ids",
            "all_pairs_exact",
            "silent_fallback_count",
            "evidence",
            "fingerprint",
        },
        "completeness",
    )
    _equal(completeness.get("schema"), f"{MATRIX_SCHEMA}.completeness", "completeness.schema")
    _equal(completeness.get("status"), "PASS", "completeness.status")
    _equal(completeness.get("evidence"), MATRIX_EVIDENCE, "completeness.evidence")
    completeness_fp = _verify_fingerprint(completeness, "completeness")
    _equal(
        manifest["completeness_fingerprint"],
        completeness_fp,
        "matrix manifest.completeness_fingerprint",
    )
    for field in ("duplicate_run_ids", "missing_run_ids", "unexpected_run_ids"):
        _equal(completeness.get(field), [], f"completeness.{field}")
    _equal(
        completeness.get("expected_row_count"), len(expected_ids), "completeness.expected_row_count"
    )
    _equal(completeness.get("actual_row_count"), len(rows), "completeness.actual_row_count")
    _equal(completeness.get("expected_pair_count"), len(audits), "completeness.expected_pair_count")
    _equal(completeness.get("actual_pair_count"), len(audits), "completeness.actual_pair_count")
    _equal(completeness.get("all_pairs_exact"), True, "completeness.all_pairs_exact")
    _equal(completeness.get("silent_fallback_count"), 0, "completeness.silent_fallback_count")
    _exact_keys(
        provenance,
        {
            "schema",
            "status",
            "evidence",
            "model_deployment_contract",
            "implementation",
            "implementation_fingerprint",
            "workload",
            "workload_fingerprint",
            "protocol_fingerprint",
            "variant_fingerprints",
            "failure_binding_fingerprints",
            "execution",
            "fingerprint",
        },
        "provenance",
    )
    _equal(provenance.get("schema"), f"{MATRIX_SCHEMA}.provenance", "provenance.schema")
    _equal(provenance.get("status"), "PASS", "provenance.status")
    _equal(provenance.get("evidence"), MATRIX_EVIDENCE, "provenance.evidence")
    _equal(
        provenance.get("model_deployment_contract"),
        scope.model_deployment_contract,
        "provenance.model_deployment_contract",
    )
    provenance_fp = _verify_fingerprint(provenance, "provenance")
    _equal(
        manifest["provenance_fingerprint"], provenance_fp, "matrix manifest.provenance_fingerprint"
    )
    implementation = _object(provenance.get("implementation"), "provenance.implementation")
    _exact_keys(
        implementation,
        {"commit", "tree", "worktree_clean", "source_frozen"},
        "provenance.implementation",
    )
    _equal(implementation.get("worktree_clean"), True, "provenance.implementation.worktree_clean")
    _equal(implementation.get("source_frozen"), True, "provenance.implementation.source_frozen")
    implementation_commit = _hex(
        implementation.get("commit"), "provenance.implementation.commit", length=40
    )
    _hex(implementation.get("tree"), "provenance.implementation.tree", length=40)
    implementation_fp = _sha256_json(implementation)
    _equal(
        provenance.get("implementation_fingerprint"),
        implementation_fp,
        "provenance.implementation_fingerprint",
    )
    workload = _object(provenance.get("workload"), "provenance.workload")
    _exact_keys(
        workload,
        {
            "declared_path",
            "sha256",
            "record_count",
            "semantic_fingerprint",
            "manifest_sha256",
            "manifest_schema",
            "workload_kind",
        },
        "provenance.workload",
    )
    _string(workload.get("declared_path"), "provenance.workload.declared_path")
    _integer(workload.get("record_count"), "provenance.workload.record_count", minimum=1)
    _hex(workload.get("semantic_fingerprint"), "provenance.workload.semantic_fingerprint")
    _hex(workload.get("manifest_sha256"), "provenance.workload.manifest_sha256")
    _string(workload.get("manifest_schema"), "provenance.workload.manifest_schema")
    workload_kind = _string(workload.get("workload_kind"), "provenance.workload.workload_kind")
    if workload_kind not in {
        "legacy_weka",
        "odr_complete_tasks",
        "fanoutqa_complete_tasks",
    }:
        raise AuditFailure("provenance.workload.workload_kind: unsupported workload kind")
    workload_fp = _sha256_json(workload)
    _equal(provenance.get("workload_fingerprint"), workload_fp, "provenance.workload_fingerprint")
    workload_sha = _hex(workload.get("sha256"), "provenance.workload.sha256")
    if "configs" in ancillary_entries:
        _validate_snapshot_configs(matrix_dir, scope, rows, provenance)
    _equal(provenance.get("protocol_fingerprint"), protocol_fp, "provenance.protocol_fingerprint")
    execution = _object(provenance.get("execution"), "provenance.execution")
    _exact_keys(
        execution,
        {
            "engine",
            "clock",
            "parallel_worker_processes",
            "fresh_global_des_per_repetition",
            "canonical_result_sort_key",
            "wall_clock_measurements_recorded",
            "physical_components_executed",
            "slurm_used",
        },
        "provenance.execution",
    )
    _equal(execution.get("engine"), "GlobalDES", "provenance.execution.engine")
    _equal(execution.get("clock"), "single_global_virtual_clock", "provenance.execution.clock")
    _integer(
        execution.get("parallel_worker_processes"),
        "provenance.execution.parallel_worker_processes",
        minimum=1,
    )
    for field, expected in (
        ("fresh_global_des_per_repetition", True),
        ("canonical_result_sort_key", "run_id"),
        ("wall_clock_measurements_recorded", False),
        ("physical_components_executed", False),
        ("slurm_used", False),
    ):
        _equal(execution.get(field), expected, f"provenance.execution.{field}")
    variant_fingerprints = {
        f"{row['suite']}:{row['variant_id']}": _object(row["bindings"], "row.bindings")[
            "variant_fingerprint"
        ]
        for row in rows
    }
    _equal(
        provenance.get("variant_fingerprints"),
        variant_fingerprints,
        "provenance.variant_fingerprints",
    )
    schedule_bindings: set[str] = set()
    schedule_by_binding: dict[tuple[str, str], dict[str, Any]] = {}
    schedule_keys: list[str] = []
    expected_schedule_users: dict[
        tuple[str, str, str, int, int | None, int | None],
        dict[tuple[str, str], dict[str, str]],
    ] = {}
    for row in rows:
        if row["scenario"] != "gpu_failure":
            continue
        row_bindings = _object(row["bindings"], "row.bindings")
        user_key = (
            str(row_bindings["parameters_fingerprint"]),
            str(row_bindings["variant_fingerprint"])
            if "failure_count" in row
            else "",
            str(row["context_bucket"]),
            int(row["seed"]),
            row_bindings["workflow_concurrency"],
            (
                row.get("failure_count")
                if "failure_count" in row
                else row.get("independent_failure_sample_index")
            ),
        )
        identity = (str(row["suite"]), str(row["variant_id"]))
        expected_schedule_users.setdefault(user_key, {})[identity] = {
            "suite": str(row["suite"]),
            "variant_id": str(row["variant_id"]),
            "variant_fingerprint": str(row_bindings["variant_fingerprint"]),
        }
    for index, schedule_doc in enumerate(schedules, start=1):
        location = f"failure-schedules.jsonl:{index}"
        schedule_doc_keys = {
            "schema",
            "status",
            "schedule_key",
            "parameters_fingerprint",
            "failure_schedule_fingerprint",
            "failure_binding_fingerprint",
            "context_bucket",
            "seed",
            "workflow_concurrency",
            "schedule",
            "used_by_variants",
            "evidence",
        }
        has_failure_sample_index = "independent_failure_sample_index" in schedule_doc
        has_failure_count = "failure_count" in schedule_doc
        if has_failure_sample_index and has_failure_count:
            raise AuditFailure(f"{location}: mixed legacy sample and multi-failure fields")
        if has_failure_sample_index:
            schedule_doc_keys.add("independent_failure_sample_index")
        if has_failure_count:
            schedule_doc_keys.update({"failure_count", "variant_fingerprint"})
        _exact_keys(
            schedule_doc,
            schedule_doc_keys,
            location,
        )
        _equal(
            schedule_doc.get("schema"), f"{MATRIX_SCHEMA}.failure_schedule", f"{location}.schema"
        )
        _equal(schedule_doc.get("status"), "PASS", f"{location}.status")
        _equal(schedule_doc.get("evidence"), MATRIX_EVIDENCE, f"{location}.evidence")
        key = _hex(schedule_doc.get("schedule_key"), f"{location}.schedule_key")
        schedule_keys.append(key)
        parameters_fp = _hex(
            schedule_doc.get("parameters_fingerprint"), f"{location}.parameters_fingerprint"
        )
        variant_fp = (
            _hex(
                schedule_doc.get("variant_fingerprint"),
                f"{location}.variant_fingerprint",
            )
            if has_failure_count
            else None
        )
        context_bucket = _string(schedule_doc.get("context_bucket"), f"{location}.context_bucket")
        seed = _integer(schedule_doc.get("seed"), f"{location}.seed")
        independent_sample_index = (
            _integer(
                schedule_doc.get("independent_failure_sample_index"),
                f"{location}.independent_failure_sample_index",
            )
            if has_failure_sample_index
            else None
        )
        failure_count = (
            _integer(
                schedule_doc.get("failure_count"),
                f"{location}.failure_count",
                minimum=1,
            )
            if has_failure_count
            else None
        )
        workflow_concurrency = schedule_doc.get("workflow_concurrency")
        if workflow_concurrency is not None:
            workflow_concurrency = _integer(
                workflow_concurrency,
                f"{location}.workflow_concurrency",
                minimum=1,
            )
        schedule_key_input = {
            "parameters_fingerprint": parameters_fp,
            "context_bucket": context_bucket,
            "seed": seed,
            "workflow_concurrency": workflow_concurrency,
        }
        if has_failure_sample_index:
            schedule_key_input["independent_sample_index"] = independent_sample_index
        if has_failure_count:
            schedule_key_input["failure_count"] = failure_count
            schedule_key_input["variant_fingerprint"] = variant_fp
        _equal(
            key,
            _sha256_json(schedule_key_input),
            f"{location}.schedule_key",
        )
        schedule = _object(schedule_doc.get("schedule"), f"{location}.schedule")
        if has_failure_count:
            _validate_multi_failure_schedule(
                schedule,
                location=f"{location}.schedule",
                context_bucket=context_bucket,
                seed=seed,
                failure_count=cast(int, failure_count),
            )
        else:
            schedule_fields = {
                "failure_id",
                "type",
                "bucket",
                "seed",
                "focus_span_id",
                "target_gpu_id",
                "trigger",
                "reference_at_ns",
                "reference_at_ns_semantics",
                "detection_delay_ns",
                "selection_scope",
                "repair_after_ns",
                "parameter_source",
            }
            if has_failure_sample_index:
                schedule_fields.add("independent_sample_index")
            _exact_keys(schedule, schedule_fields, f"{location}.schedule")
            _equal(schedule.get("type"), "GPU_FAILURE", f"{location}.schedule.type")
            _equal(
                schedule.get("reference_at_ns_semantics"),
                "recompute_only_oracle_provenance_not_cell_time",
                f"{location}.schedule.reference_at_ns_semantics",
            )
            trigger = _object(schedule.get("trigger"), f"{location}.schedule.trigger")
            _exact_keys(
                trigger,
                {"kind", "progress_per_mille"},
                f"{location}.schedule.trigger",
            )
            _equal(
                trigger.get("kind"),
                "FOCUS_SPAN_COMPUTE_PROGRESS",
                f"{location}.schedule.trigger.kind",
            )
            progress = _integer(
                trigger.get("progress_per_mille"),
                f"{location}.schedule.trigger.progress_per_mille",
            )
            if not 1 <= progress <= 999:
                raise AuditFailure(
                    f"{location}.schedule.trigger.progress_per_mille: out of range"
                )
            _integer(
                schedule.get("detection_delay_ns"),
                f"{location}.schedule.detection_delay_ns",
            )
            _equal(
                schedule.get("bucket"),
                schedule_doc.get("context_bucket"),
                f"{location}.schedule.bucket",
            )
            _equal(schedule.get("seed"), schedule_doc.get("seed"), f"{location}.schedule.seed")
            if has_failure_sample_index:
                _equal(
                    schedule.get("independent_sample_index"),
                    independent_sample_index,
                    f"{location}.schedule.independent_sample_index",
                )
            repair_after_ns = schedule.get("repair_after_ns")
            if repair_after_ns is not None:
                _integer(
                    repair_after_ns,
                    f"{location}.schedule.repair_after_ns",
                    minimum=1,
                )
        expected_users = sorted(
            expected_schedule_users.get(
                (
                    parameters_fp,
                    cast(str, variant_fp) if has_failure_count else "",
                    context_bucket,
                    seed,
                    workflow_concurrency,
                    failure_count if has_failure_count else independent_sample_index,
                ),
                {},
            ).values(),
            key=lambda item: (item["suite"], item["variant_id"]),
        )
        _equal(
            schedule_doc.get("used_by_variants"),
            expected_users,
            f"{location}.used_by_variants",
        )
        schedule_fp = _hex(
            schedule_doc.get("failure_schedule_fingerprint"),
            f"{location}.failure_schedule_fingerprint",
        )
        _equal(schedule_fp, _sha256_json(schedule), f"{location}.failure_schedule_fingerprint")
        binding_fp = _hex(
            schedule_doc.get("failure_binding_fingerprint"),
            f"{location}.failure_binding_fingerprint",
        )
        binding_input = {
            "parameters_fingerprint": parameters_fp,
            "failure_schedule_fingerprint": schedule_fp,
            "workflow_concurrency": workflow_concurrency,
        }
        if has_failure_sample_index:
            binding_input["independent_sample_index"] = independent_sample_index
        if has_failure_count:
            binding_input["failure_count"] = failure_count
            binding_input["variant_fingerprint"] = variant_fp
        _equal(
            binding_fp,
            _sha256_json(binding_input),
            f"{location}.failure_binding_fingerprint",
        )
        schedule_bindings.add(binding_fp)
        if (schedule_fp, binding_fp) in schedule_by_binding:
            raise AuditFailure(f"{location}: duplicate failure schedule/binding pair")
        schedule_by_binding[(schedule_fp, binding_fp)] = schedule_doc
    if schedule_keys != sorted(schedule_keys) or len(set(schedule_keys)) != len(schedule_keys):
        raise AuditFailure("failure-schedules.jsonl: schedule_key values must be unique and sorted")
    _equal(
        manifest["failure_schedule_count"], len(schedules), "matrix manifest.failure_schedule_count"
    )
    _equal(
        provenance.get("failure_binding_fingerprints"),
        sorted(schedule_bindings),
        "provenance.failure_binding_fingerprints",
    )
    no_failure_fp = _sha256_json({"scenario": "no_failure", "failure_schedule": None})
    for row in rows:
        bindings = _object(row["bindings"], "row.bindings")
        _equal(
            bindings["implementation_fingerprint"],
            implementation_fp,
            f"{row['run_id']} implementation binding",
        )
        _equal(
            bindings["implementation_commit"],
            implementation_commit,
            f"{row['run_id']} implementation commit",
        )
        _equal(bindings["workload_fingerprint"], workload_fp, f"{row['run_id']} workload binding")
        _equal(bindings["workload_sha256"], workload_sha, f"{row['run_id']} workload SHA binding")
        payload = _object(row["payload"], "row.payload")
        if row["scenario"] == "no_failure":
            _equal(
                bindings["failure_schedule_fingerprint"],
                no_failure_fp,
                f"{row['run_id']} no-failure schedule binding",
            )
            _equal(
                bindings["failure_binding_fingerprint"],
                no_failure_fp,
                f"{row['run_id']} no-failure binding",
            )
        else:
            bound_schedule = schedule_by_binding.get(
                (
                    str(bindings["failure_schedule_fingerprint"]),
                    str(bindings["failure_binding_fingerprint"]),
                )
            )
            if bound_schedule is None:
                raise AuditFailure(
                    f"{row['run_id']}: failure schedule is absent from frozen schedules"
                )
            _equal(
                bound_schedule["schedule"],
                payload.get("failure_schedule"),
                f"{row['run_id']} failure schedule payload binding",
            )
            _equal(
                bound_schedule["failure_binding_fingerprint"],
                bindings["failure_binding_fingerprint"],
                f"{row['run_id']} failure binding",
            )
    _exact_keys(
        representative,
        {
            "schema",
            "status",
            "run_id",
            "payload_sha256",
            "journal_sha256",
            "evidence",
            "bindings",
            "variant_config",
            "payload",
            "representative",
            "span_details",
        },
        "representative",
    )
    _object(representative.get("representative"), "representative.representative")
    _array(representative.get("span_details"), "representative.span_details")
    _equal(
        representative.get("schema"), f"{MATRIX_SCHEMA}.representative_run", "representative.schema"
    )
    _equal(representative.get("status"), "PASS", "representative.status")
    _equal(representative.get("evidence"), MATRIX_EVIDENCE, "representative.evidence")
    representative_run_id = _string(representative.get("run_id"), "representative.run_id")
    rows_by_id = {str(row["run_id"]): row for row in rows}
    representative_row = rows_by_id.get(representative_run_id)
    if representative_row is None:
        raise AuditFailure("representative.run_id: not present in results.jsonl")
    for field in ("payload_sha256", "journal_sha256", "bindings", "variant_config", "payload"):
        _equal(representative.get(field), representative_row[field], f"representative.{field}")
    _validate_representative_semantics(representative)
    return MatrixState(
        manifest=manifest,
        manifest_sha256=_sha256_file(manifest_path),
        artifact_hashes=artifact_hashes,
        rows=rows,
        rows_by_id=rows_by_id,
        pair_count=len(audits),
        config_snapshot_binding=config_snapshot_binding,
    )


def _expected_figure_inputs(matrix: MatrixState) -> dict[str, Any]:
    return {
        "matrix_results": {
            "file": "results.jsonl",
            "sha256": matrix.artifact_hashes["results.jsonl"],
        },
        "matrix_manifest": {"file": "manifest.json", "sha256": matrix.manifest_sha256},
        "representative_run": {
            "file": "representative-run.json",
            "sha256": matrix.artifact_hashes["representative-run.json"],
        },
    }


def _validate_figure_bundle(figure_dir: Path, matrix: MatrixState) -> str:
    if figure_dir.is_symlink() or not figure_dir.is_dir():
        raise AuditFailure("figure-dir: expected a non-symlink directory")
    _equal(
        {row["suite"] for row in matrix.rows},
        {"core", "ablation", "sensitivity"},
        "figure input matrix suite set",
    )
    manifest_path = _safe_child(figure_dir, "manifest.json", "figure manifest")
    manifest = _load_json(manifest_path, "figure manifest")
    _exact_keys(
        manifest,
        {
            "schema",
            "status",
            "generator",
            "canonical_json",
            "evidence",
            "evidence_footer",
            "inputs",
            "required_svg_figure_ids",
            "excluded_figure_ids",
            "figures",
            "exclusions",
            "generated_artifact_count",
            "point_binding_contract",
            "paper_ready",
        },
        "figure manifest",
    )
    _equal(manifest["schema"], "moonkvsim.aegiskv.figure_set_manifest.v1", "figure manifest.schema")
    _equal(manifest["status"], "PASS", "figure manifest.status")
    _equal(manifest["generator"], GENERATOR, "figure manifest.generator")
    _equal(manifest["canonical_json"], True, "figure manifest.canonical_json")
    _equal(manifest["evidence"], FIGURE_EVIDENCE, "figure manifest.evidence")
    _equal(manifest["evidence_footer"], EVIDENCE_FOOTER, "figure manifest.evidence_footer")
    expected_inputs = _expected_figure_inputs(matrix)
    _equal(manifest["inputs"], expected_inputs, "figure manifest.inputs")
    _equal(
        manifest["required_svg_figure_ids"],
        list(REQUIRED_FIGURE_IDS),
        "figure manifest.required_svg_figure_ids",
    )
    _equal(manifest["excluded_figure_ids"], ["F12"], "figure manifest.excluded_figure_ids")
    _equal(manifest["generated_artifact_count"], 29, "figure manifest.generated_artifact_count")
    _equal(
        manifest["point_binding_contract"],
        {
            "required_fields": [
                "point_id",
                "run_id",
                "result_hash",
                "result_hash_kind",
                "coordinates",
            ],
            "result_hash_kind": "payload_sha256",
            "same_bindings_embedded_in_svg_data_attributes": True,
        },
        "figure manifest.point_binding_contract",
    )
    _equal(manifest["paper_ready"], False, "figure manifest.paper_ready")
    figures = _array(manifest["figures"], "figure manifest.figures")
    _equal(len(figures), len(REQUIRED_FIGURE_IDS), "figure manifest.figures count")
    expected_files = {"manifest.json", F12_FILE}
    for stem in FIGURE_STEMS.values():
        expected_files.update({f"{stem}.svg", f"{stem}.provenance.json"})
    actual_files = {path.name for path in figure_dir.iterdir()}
    _equal(actual_files, expected_files, "figure bundle directory entries")
    observed_ids: list[str] = []
    for index, raw_entry in enumerate(figures):
        entry = _object(raw_entry, f"figure manifest.figures[{index}]")
        _exact_keys(
            entry,
            {"figure_id", "svg", "provenance", "point_count"},
            f"figure manifest.figures[{index}]",
        )
        figure_id = _string(entry["figure_id"], f"figure manifest.figures[{index}].figure_id")
        observed_ids.append(figure_id)
        if figure_id not in FIGURE_STEMS:
            raise AuditFailure(
                f"figure manifest.figures[{index}]: unexpected figure id {figure_id}"
            )
        stem = FIGURE_STEMS[figure_id]
        svg_name = f"{stem}.svg"
        provenance_name = f"{stem}.provenance.json"
        svg_ref = _object(entry["svg"], f"figure manifest.figures[{index}].svg")
        provenance_ref = _object(
            entry["provenance"], f"figure manifest.figures[{index}].provenance"
        )
        _equal(svg_ref.get("file"), svg_name, f"{figure_id} SVG file")
        _equal(provenance_ref.get("file"), provenance_name, f"{figure_id} provenance file")
        svg_path = _safe_child(figure_dir, svg_ref.get("file"), f"{figure_id} SVG")
        provenance_path = _safe_child(
            figure_dir, provenance_ref.get("file"), f"{figure_id} provenance"
        )
        svg_bytes = _regular_file(svg_path, f"{figure_id} SVG")
        svg_sha = _hex(svg_ref.get("sha256"), f"{figure_id} SVG sha256")
        _equal(_sha256_bytes(svg_bytes), svg_sha, f"{figure_id} SVG SHA-256")
        provenance_bytes = _regular_file(provenance_path, f"{figure_id} provenance")
        provenance_sha = _hex(provenance_ref.get("sha256"), f"{figure_id} provenance sha256")
        _equal(_sha256_bytes(provenance_bytes), provenance_sha, f"{figure_id} provenance SHA-256")
        provenance = _load_json(provenance_path, f"{figure_id} provenance")
        _exact_keys(
            provenance,
            {
                "schema",
                "figure_id",
                "title",
                "generator",
                "svg",
                "inputs",
                "evidence",
                "point_bindings",
                "notes",
            },
            f"{figure_id} provenance",
        )
        _equal(
            provenance["schema"],
            "moonkvsim.aegiskv.figure_provenance.v1",
            f"{figure_id} provenance.schema",
        )
        _equal(provenance["figure_id"], figure_id, f"{figure_id} provenance.figure_id")
        _string(provenance["title"], f"{figure_id} provenance.title")
        _equal(provenance["generator"], GENERATOR, f"{figure_id} provenance.generator")
        _equal(
            provenance["svg"], {"file": svg_name, "sha256": svg_sha}, f"{figure_id} provenance.svg"
        )
        _equal(provenance["inputs"], expected_inputs, f"{figure_id} provenance.inputs")
        _equal(provenance["evidence"], FIGURE_EVIDENCE, f"{figure_id} provenance.evidence")
        _array(provenance["notes"], f"{figure_id} provenance.notes")
        bindings = _array(provenance["point_bindings"], f"{figure_id} provenance.point_bindings")
        _equal(entry["point_count"], len(bindings), f"{figure_id} point_count")
        if not bindings:
            raise AuditFailure(f"{figure_id}: point_bindings must not be empty")
        binding_triples: dict[str, tuple[str, str]] = {}
        for binding_index, raw_binding in enumerate(bindings):
            location = f"{figure_id} provenance.point_bindings[{binding_index}]"
            binding = _object(raw_binding, location)
            _exact_keys(
                binding,
                {"point_id", "run_id", "result_hash", "result_hash_kind", "coordinates"},
                location,
            )
            point_id = _string(binding["point_id"], f"{location}.point_id")
            run_id = _string(binding["run_id"], f"{location}.run_id")
            result_hash = _hex(binding["result_hash"], f"{location}.result_hash")
            _equal(binding["result_hash_kind"], "payload_sha256", f"{location}.result_hash_kind")
            _object(binding["coordinates"], f"{location}.coordinates")
            row = matrix.rows_by_id.get(run_id)
            if row is None:
                raise AuditFailure(f"{location}: run_id is absent from matrix results")
            _equal(result_hash, row["payload_sha256"], f"{location}.result_hash")
            if point_id in binding_triples:
                raise AuditFailure(f"{figure_id}: duplicate point_id {point_id}")
            binding_triples[point_id] = (run_id, result_hash)
        try:
            root = ET.fromstring(svg_bytes)
        except ET.ParseError as error:
            raise AuditFailure(f"{figure_id} SVG: invalid XML: {error}") from error
        if root.tag.rsplit("}", 1)[-1] != "svg":
            raise AuditFailure(f"{figure_id} SVG: root element is not svg")
        try:
            svg_text = svg_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AuditFailure(f"{figure_id} SVG: not valid UTF-8") from error
        if EVIDENCE_FOOTER not in svg_text:
            raise AuditFailure(f"{figure_id} SVG: E2 evidence footer is missing")
        embedded: dict[str, tuple[str, str]] = {}
        for element in root.iter():
            attributes = element.attrib
            binding_fields = {"data-point-id", "data-run-id", "data-result-hash"}
            present = binding_fields & set(attributes)
            if present and present != binding_fields:
                raise AuditFailure(f"{figure_id} SVG: partial point binding attributes")
            if present:
                point_id = attributes["data-point-id"]
                if point_id in embedded:
                    raise AuditFailure(f"{figure_id} SVG: duplicate embedded point_id {point_id}")
                embedded[point_id] = (attributes["data-run-id"], attributes["data-result-hash"])
        _equal(embedded, binding_triples, f"{figure_id} SVG/provenance point bindings")
    _equal(observed_ids, list(REQUIRED_FIGURE_IDS), "figure manifest figure ordering/IDs")
    exclusions = _array(manifest["exclusions"], "figure manifest.exclusions")
    _equal(len(exclusions), 1, "figure manifest.exclusions count")
    exclusion_ref = _object(exclusions[0], "figure manifest.exclusions[0]")
    _exact_keys(
        exclusion_ref,
        {"figure_id", "file", "sha256", "svg_generated"},
        "figure manifest.exclusions[0]",
    )
    _equal(exclusion_ref["figure_id"], "F12", "figure manifest.exclusions[0].figure_id")
    _equal(exclusion_ref["file"], F12_FILE, "figure manifest.exclusions[0].file")
    _equal(exclusion_ref["svg_generated"], False, "figure manifest.exclusions[0].svg_generated")
    exclusion_path = _safe_child(figure_dir, exclusion_ref["file"], "F12 exclusion")
    exclusion_sha = _hex(exclusion_ref["sha256"], "figure manifest.exclusions[0].sha256")
    _equal(_sha256_file(exclusion_path), exclusion_sha, "F12 exclusion SHA-256")
    exclusion = _load_json(exclusion_path, "F12 exclusion")
    _exact_keys(
        exclusion,
        {
            "schema",
            "figure_id",
            "status",
            "svg_generated",
            "reason",
            "required_evidence",
            "current_evidence",
            "evidence",
            "paper_ready",
            "inputs",
        },
        "F12 exclusion",
    )
    _equal(exclusion["schema"], "moonkvsim.aegiskv.figure_exclusion.v1", "F12 exclusion.schema")
    _equal(exclusion["figure_id"], "F12", "F12 exclusion.figure_id")
    _equal(exclusion["status"], "EXCLUDED", "F12 exclusion.status")
    _equal(exclusion["svg_generated"], False, "F12 exclusion.svg_generated")
    _equal(exclusion["paper_ready"], False, "F12 exclusion.paper_ready")
    _equal(exclusion["evidence"], FIGURE_EVIDENCE, "F12 exclusion.evidence")
    _equal(exclusion["inputs"], expected_inputs, "F12 exclusion.inputs")
    _equal(
        exclusion["required_evidence"],
        ["E3 modeled_with_physical_calibration", "E4 physical_baseline"],
        "F12 exclusion.required_evidence",
    )
    _equal(
        exclusion["current_evidence"],
        "E2 modeled/preliminary; not calibrated; no physical experiment",
        "F12 exclusion.current_evidence",
    )
    _equal(
        exclusion["reason"],
        "simulator accuracy requires observed-vs-predicted E3/E4 evidence",
        "F12 exclusion.reason",
    )
    return _sha256_file(manifest_path)


def audit_artifacts(matrix_dir: Path, figure_dir: Path) -> dict[str, Any]:
    """Return a canonical-serializable PASS/FAIL report without writing files."""

    try:
        matrix = _validate_matrix(matrix_dir)
        figure_manifest_sha = _validate_figure_bundle(figure_dir, matrix)
    except (AuditFailure, OSError) as error:
        return {
            "schema": AUDIT_SCHEMA,
            "status": "FAIL",
            "errors": [str(error)],
            "physical_execution": False,
            "slurm_used": False,
        }
    return {
        "schema": AUDIT_SCHEMA,
        "status": "PASS",
        "matrix": {
            "status": "PASS",
            "artifact_count": len(MATRIX_ARTIFACTS),
            "result_count": len(matrix.rows),
            "pair_count": matrix.pair_count,
            "config_snapshot_binding": matrix.config_snapshot_binding,
            "manifest_fingerprint": matrix.manifest["fingerprint"],
            "manifest_sha256": matrix.manifest_sha256,
        },
        "figures": {
            "status": "PASS",
            "required_svg_count": len(REQUIRED_FIGURE_IDS),
            "excluded_figure_ids": ["F12"],
            "generated_artifact_count": 29,
            "manifest_sha256": figure_manifest_sha,
        },
        "evidence": FIGURE_EVIDENCE,
        "physical_execution": False,
        "slurm_used": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Strict offline audit of canonical AegisKV GlobalDES E2 matrix and figures"
    )
    parser.add_argument("--matrix-dir", type=Path, required=True)
    parser.add_argument("--figure-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = audit_artifacts(args.matrix_dir, args.figure_dir)
    sys.stdout.buffer.write(_canonical_bytes(report, newline=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
