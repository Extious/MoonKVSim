"""Deterministic, standard-library SVG figures for the AegisKV E2 study.

The renderer consumes only canonical GlobalDES result artifacts.  It neither
executes a simulator nor consults a wall clock.  Every plotted mark carries a
``run_id`` and the canonical payload SHA-256 in both the SVG and its sidecar.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from moonkvsim.aegiskv.experiment_suite import EXPECTED_VARIANT_IDS
from moonkvsim.common.hash import sha256_json

EVIDENCE_FOOTER: Final = "E2 modeled/preliminary · not calibrated · no physical experiment"
FIGURE_EVIDENCE: Final[dict[str, Any]] = {
    "class": "E2",
    "scope": "modeled/preliminary",
    "calibration": "not_calibrated",
    "physical_execution": False,
    "physical_timing_claim_allowed": False,
    "formal_use_allowed": False,
    "paper_ready": False,
    "slurm_used": False,
}
GENERATOR_VERSION: Final = "moonkvsim.aegiskv.figures.v1"
BUCKETS: Final = ("8k", "32k", "64k", "96k", "128k")
SVG_WIDTH: Final = 1200
SVG_HEIGHT: Final = 720
PLOT_LEFT: Final = 105
PLOT_RIGHT: Final = 1145
PLOT_TOP: Final = 118
PLOT_BOTTOM: Final = 620
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COLORS: Final = (
    "#2563eb",
    "#dc2626",
    "#059669",
    "#7c3aed",
    "#d97706",
    "#0891b2",
    "#be185d",
    "#4b5563",
)


class FigureInputError(ValueError):
    """A canonical figure input is missing, inconsistent, or overclaims E2."""


class ExistingFigureError(FileExistsError):
    """A target would be overwritten without explicit authorization."""


@dataclass(frozen=True, slots=True)
class PointBinding:
    """Exact source binding for one SVG data mark."""

    point_id: str
    run_id: str
    result_hash: str
    coordinates: Mapping[str, int | float | str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "point_id": self.point_id,
            "run_id": self.run_id,
            "result_hash": self.result_hash,
            "result_hash_kind": "payload_sha256",
            "coordinates": dict(self.coordinates),
        }


@dataclass(frozen=True, slots=True)
class MatrixRow:
    """Validated result row used by the renderer."""

    run_id: str
    result_hash: str
    suite: str
    variant_id: str
    context_bucket: str
    scenario: str
    seed: int
    repetition: str
    payload: Mapping[str, Any]
    raw: Mapping[str, Any]

    @property
    def metrics(self) -> Mapping[str, Any]:
        return _mapping(self.payload.get("metrics"), f"{self.run_id}.payload.metrics")


@dataclass(frozen=True, slots=True)
class RepresentativeRun:
    """Validated representative-run bundle for event-level figures."""

    row: MatrixRow
    representative: Mapping[str, Any]
    span_details: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class FigureArtifact:
    figure_id: str
    title: str
    svg_path: Path | None
    provenance_path: Path


@dataclass(frozen=True, slots=True)
class FigureSetResult:
    artifacts: tuple[FigureArtifact, ...]
    manifest_path: Path
    results_sha256: str
    manifest_sha256: str
    representative_sha256: str


@dataclass(frozen=True, slots=True)
class _FigureSpec:
    figure_id: str
    slug: str
    title: str

    @property
    def stem(self) -> str:
        return f"{self.figure_id.lower()}-{self.slug}"


@dataclass(frozen=True, slots=True)
class _RenderedFigure:
    svg: str
    bindings: tuple[PointBinding, ...]
    notes: tuple[str, ...] = ()


FIGURES: Final = (
    _FigureSpec("F1", "system-architecture", "AegisKV modeled system architecture"),
    _FigureSpec("F2", "failure-recovery-timeline", "GPU failure recovery timeline"),
    _FigureSpec("F3", "peer-hbm-timeline", "Peer-HBM occupancy at event boundaries"),
    _FigureSpec("F4", "store-dram-timeline", "Store DRAM occupancy at event boundaries"),
    _FigureSpec("F5", "kv-migration-gantt", "KV migration Gantt"),
    _FigureSpec("F6", "wct-goodput", "Matched WCT and goodput"),
    _FigureSpec("F7", "recovery-cdf", "Runtime recovery-ready delay empirical CDF"),
    _FigureSpec("F8", "coverage-recompute", "Protection coverage and recomputation"),
    _FigureSpec("F9", "policy-ablation", "Policy ablations"),
    _FigureSpec("F10", "budget-sensitivity", "Peer-HBM and Store budget sensitivity"),
    _FigureSpec("F11", "scale", "Modeled intra-node bandwidth and control-delay sensitivity"),
    _FigureSpec("F13", "resource-cost", "AegisKV resource-cost decomposition"),
    _FigureSpec("F14", "peak-mean", "Resource peak and time-weighted mean"),
    _FigureSpec("F15", "trace-coverage", "Real multi-agent trace five-bucket coverage"),
)
F12_STEM: Final = "f12-simulator-accuracy"


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FigureInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_input_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise FigureInputError(f"{path}: expected a regular non-symlink input file")
    try:
        return path.read_bytes()
    except OSError as error:
        raise FigureInputError(f"cannot read {path}: {error}") from error


def _load_json_bytes(raw_bytes: bytes, path: Path) -> Mapping[str, Any]:
    try:
        raw = raw_bytes.decode("utf-8")
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FigureInputError(f"cannot load JSON {path}: {error}") from error
    document = _mapping(value, str(path))
    if raw != _canonical_json(document):
        raise FigureInputError(f"{path}: JSON is not canonical sorted compact JSON")
    return document


def _load_jsonl_bytes(raw_bytes: bytes, path: Path) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FigureInputError(f"cannot decode JSONL {path}: {error}") from error
    for line_number, line in enumerate(raw.splitlines(keepends=True), start=1):
        if not line.strip():
            raise FigureInputError(f"{path}:{line_number}: blank line")
        try:
            value = json.loads(line, object_pairs_hook=_reject_duplicate_pairs)
        except json.JSONDecodeError as error:
            raise FigureInputError(f"{path}:{line_number}: invalid JSON: {error}") from error
        row = _mapping(value, f"{path}:{line_number}")
        if line != _canonical_json(row):
            raise FigureInputError(
                f"{path}:{line_number}: row is not canonical sorted compact JSON"
            )
        rows.append(row)
    if not rows:
        raise FigureInputError("matrix results JSONL is empty")
    return rows


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FigureInputError(f"{location}: expected object")
    return value


def _sequence(value: object, location: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise FigureInputError(f"{location}: expected array")
    return value


def _required_str(mapping: Mapping[str, Any], key: str, location: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise FigureInputError(f"{location}.{key}: expected non-empty string")
    return value


def _required_sha256(mapping: Mapping[str, Any], key: str, location: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise FigureInputError(f"{location}.{key}: expected lowercase SHA-256")
    return value


def _first_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _first_mapping(*values: object) -> Mapping[str, Any] | None:
    for value in values:
        if isinstance(value, Mapping):
            return value
    return None


def _nested(mapping: Mapping[str, Any], *keys: str) -> object:
    value: object = mapping
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    )


def _validate_e2(payload: Mapping[str, Any], location: str) -> None:
    if payload.get("schema") != "moonkvsim.aegiskv.study_run_payload.v1":
        raise FigureInputError(f"{location}: unexpected study payload schema")
    if payload.get("status") != "PASS":
        raise FigureInputError(f"{location}: study payload status is not PASS")
    evidence = _mapping(payload.get("evidence"), f"{location}.evidence")
    expected: dict[str, object] = {
        "class": "E2",
        "scope": "modeled/preliminary",
        "calibration": "not_calibrated",
        "physical_execution": False,
        "physical_timing_claim_allowed": False,
        "formal_use_allowed": False,
        "paper_ready": False,
    }
    for key, expected_value in expected.items():
        if evidence.get(key) != expected_value:
            raise FigureInputError(
                f"{location}.evidence.{key}: expected {expected_value!r}, got {evidence.get(key)!r}"
            )
    clock = _mapping(payload.get("global_clock"), f"{location}.global_clock")
    if clock.get("kind") != "single_global_virtual_clock":
        raise FigureInputError(f"{location}: figure input is not GlobalDES")
    if clock.get("time_unit") != "ns":
        raise FigureInputError(f"{location}.global_clock.time_unit: expected ns")
    if clock.get("event_order") != "timestamp_priority_stable_sequence":
        raise FigureInputError(f"{location}.global_clock.event_order: unexpected ordering")
    if clock.get("wall_clock_or_sleep_used") is not False:
        raise FigureInputError(f"{location}: wall-clock/sleep evidence is forbidden")
    forbidden = _mapping(payload.get("forbidden_semantics"), f"{location}.forbidden_semantics")
    expected_forbidden = {
        "hbm_to_dram_writeback_count",
        "target_owned_destage_count",
        "dram_prerequisite_for_hbm_count",
        "cross_tier_abort_propagation_count",
        "second_directory_count",
        "ssd_nvme_event_count",
    }
    if set(forbidden) != expected_forbidden or any(
        type(value) is not int or value != 0 for value in forbidden.values()
    ):
        raise FigureInputError(f"{location}: forbidden semantics are missing or nonzero")
    output_audit = _mapping(payload.get("output_audit"), f"{location}.output_audit")
    expected_output_fields = {
        "expected_output_tokens",
        "external_output_tokens",
        "duplicate_or_missing_tokens",
        "stale_route_output_count",
    }
    if set(output_audit) != expected_output_fields:
        raise FigureInputError(f"{location}.output_audit: unexpected fields")
    for field in ("duplicate_or_missing_tokens", "stale_route_output_count"):
        if type(output_audit.get(field)) is not int or output_audit[field] != 0:
            raise FigureInputError(f"{location}.output_audit.{field}: expected integer zero")
    expected_tokens = output_audit.get("expected_output_tokens")
    external_tokens = output_audit.get("external_output_tokens")
    if (
        type(expected_tokens) is not int
        or type(external_tokens) is not int
        or expected_tokens < 0
        or expected_tokens != external_tokens
    ):
        raise FigureInputError(f"{location}: external output token audit mismatch")
    scope = _mapping(payload.get("execution_scope"), f"{location}.execution_scope")
    if scope.get("cpu_metadata_only") is not True:
        raise FigureInputError(f"{location}.execution_scope.cpu_metadata_only: expected true")
    for field in ("slurm_used", "cuda_used", "network_io_used"):
        if scope.get(field) is not False:
            raise FigureInputError(f"{location}.execution_scope.{field}: expected false")
    resources = _mapping(payload.get("resource_model"), f"{location}.resource_model")
    for field in (
        "peer_hbm_resources",
        "store_dram_segments",
        "copy_engines",
        "fabric_resources",
    ):
        _sequence(resources.get(field), f"{location}.resource_model.{field}")
    if resources.get("per_gpu_peer_hbm_quota_enforced") is not True:
        raise FigureInputError(f"{location}: per-GPU Peer-HBM quota is not enforced")
    if resources.get("failed_gpu_hbm_becomes_unavailable_not_free") is not True:
        raise FigureInputError(f"{location}: failed GPU HBM availability semantics drifted")
    recovery = _mapping(payload.get("recovery_model"), f"{location}.recovery_model")
    expected_recovery = {
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
    }
    if recovery != expected_recovery:
        raise FigureInputError(f"{location}: recovery model semantics drifted")
    workload = _mapping(payload.get("workload"), f"{location}.workload")
    if workload.get("no_truncation_or_padding") is not True:
        raise FigureInputError(f"{location}: workload permits truncation or padding")


def _row_binding(raw: Mapping[str, Any]) -> tuple[str, str]:
    bindings = _first_mapping(raw.get("bindings"), raw.get("binding")) or {}
    run_id = _first_str(raw.get("run_id"), bindings.get("run_id"))
    result_hash = _first_str(
        raw.get("result_payload_sha256"),
        raw.get("payload_sha256"),
        raw.get("result_hash"),
        bindings.get("result_payload_sha256"),
        bindings.get("payload_sha256"),
        bindings.get("result_hash"),
    )
    if run_id is None:
        raise FigureInputError("matrix row has no run_id binding")
    if result_hash is None or _SHA256.fullmatch(result_hash) is None:
        raise FigureInputError(f"{run_id}: missing canonical payload SHA-256")
    return run_id, result_hash


def _parse_matrix_row(raw: Mapping[str, Any]) -> MatrixRow:
    if raw.get("schema") != "moonkvsim.aegiskv.e2_matrix_suite.v1.result_row":
        raise FigureInputError("matrix row has an unexpected schema")
    if raw.get("status") != "PASS":
        raise FigureInputError("matrix row status is not PASS")
    run_id, result_hash = _row_binding(raw)
    payload = _mapping(raw.get("payload"), f"{run_id}.payload")
    _validate_e2(payload, f"{run_id}.payload")
    actual_hash = sha256_json(payload)
    if actual_hash != result_hash:
        raise FigureInputError(
            f"{run_id}: payload SHA-256 mismatch: {actual_hash} != {result_hash}"
        )
    variant = _mapping(raw.get("variant_config"), f"{run_id}.variant_config")
    suite = _first_str(raw.get("suite"), variant.get("suite"))
    variant_id = _first_str(raw.get("variant_id"), variant.get("variant_id"))
    context_bucket = _first_str(raw.get("context_bucket"), payload.get("context_bucket"))
    scenario = _first_str(raw.get("scenario"), payload.get("scenario"))
    repetition = _first_str(raw.get("repetition"))
    seed = raw.get("seed")
    if suite is None or variant_id is None:
        raise FigureInputError(f"{run_id}: suite/variant_id missing")
    if raw.get("suite") != suite or variant.get("suite") != suite:
        raise FigureInputError(f"{run_id}: suite binding drift")
    if raw.get("variant_id") != variant_id or variant.get("variant_id") != variant_id:
        raise FigureInputError(f"{run_id}: variant_id binding drift")
    if raw.get("context_bucket") != payload.get("context_bucket"):
        raise FigureInputError(f"{run_id}: context bucket differs between row and payload")
    if raw.get("scenario") != payload.get("scenario"):
        raise FigureInputError(f"{run_id}: scenario differs between row and payload")
    row_bindings = _mapping(raw.get("bindings"), f"{run_id}.bindings")
    payload_variant_fingerprint = payload.get("variant_fingerprint")
    row_variant_fingerprint = row_bindings.get("variant_fingerprint")
    if (
        not isinstance(payload_variant_fingerprint, str)
        or _SHA256.fullmatch(payload_variant_fingerprint) is None
        or sha256_json(variant) != payload_variant_fingerprint
        or row_variant_fingerprint != payload_variant_fingerprint
    ):
        raise FigureInputError(f"{run_id}: variant fingerprint binding drift")
    if context_bucket not in BUCKETS:
        raise FigureInputError(f"{run_id}: invalid context bucket {context_bucket!r}")
    if scenario not in {"no_failure", "gpu_failure"}:
        raise FigureInputError(f"{run_id}: invalid scenario {scenario!r}")
    if repetition not in {"A", "B"}:
        raise FigureInputError(f"{run_id}: repetition must be A or B")
    if type(seed) is not int or seed < 0:
        raise FigureInputError(f"{run_id}: seed must be a non-negative integer")
    expected_pair_id = f"{suite}:{variant_id}:{context_bucket}:{scenario}:seed-{seed}"
    if raw.get("pair_id") != expected_pair_id:
        raise FigureInputError(f"{run_id}: pair_id binding drift")
    if run_id != f"{expected_pair_id}:repeat-{repetition}":
        raise FigureInputError(f"{run_id}: run_id is not canonical for its matrix cell")
    for key, expected_binding in (
        ("context_bucket", context_bucket),
        ("scenario", scenario),
        ("seed", seed),
    ):
        if row_bindings.get(key) != expected_binding:
            raise FigureInputError(f"{run_id}: bindings.{key} drift")
    schedule = payload.get("failure_schedule")
    if scenario == "no_failure" and schedule is not None:
        raise FigureInputError(f"{run_id}: no-failure row carries a failure schedule")
    if scenario == "gpu_failure":
        schedule_mapping = _mapping(schedule, f"{run_id}.payload.failure_schedule")
        if schedule_mapping.get("type") != "GPU_FAILURE":
            raise FigureInputError(f"{run_id}: only GPU_FAILURE is allowed")
        if schedule_mapping.get("bucket") != context_bucket:
            raise FigureInputError(f"{run_id}: failure schedule bucket drift")
        if schedule_mapping.get("seed") != seed:
            raise FigureInputError(f"{run_id}: failure schedule seed drift")
    parameters = _mapping(variant.get("parameters"), f"{run_id}.variant_config.parameters")
    parameters_fingerprint = sha256_json(parameters)
    if row_bindings.get("parameters_fingerprint") != parameters_fingerprint:
        raise FigureInputError(f"{run_id}: parameters fingerprint drift")
    failure_schedule_fingerprint = (
        sha256_json(_mapping(schedule, f"{run_id}.payload.failure_schedule"))
        if scenario == "gpu_failure"
        else sha256_json({"scenario": "no_failure", "failure_schedule": None})
    )
    if row_bindings.get("failure_schedule_fingerprint") != failure_schedule_fingerprint:
        raise FigureInputError(f"{run_id}: failure schedule fingerprint drift")
    failure_binding_fingerprint = (
        sha256_json(
            {
                "parameters_fingerprint": parameters_fingerprint,
                "failure_schedule_fingerprint": failure_schedule_fingerprint,
            }
        )
        if scenario == "gpu_failure"
        else failure_schedule_fingerprint
    )
    if row_bindings.get("failure_binding_fingerprint") != failure_binding_fingerprint:
        raise FigureInputError(f"{run_id}: failure binding fingerprint drift")
    matched_input = {
        "implementation_fingerprint": _required_sha256(
            row_bindings, "implementation_fingerprint", f"{run_id}.bindings"
        ),
        "workload_fingerprint": _required_sha256(
            row_bindings, "workload_fingerprint", f"{run_id}.bindings"
        ),
        "protocol_fingerprint": _required_sha256(
            row_bindings, "protocol_fingerprint", f"{run_id}.bindings"
        ),
        "variant_fingerprint": payload_variant_fingerprint,
        "parameters_fingerprint": parameters_fingerprint,
        "context_bucket": context_bucket,
        "scenario": scenario,
        "seed": seed,
        "failure_schedule_fingerprint": failure_schedule_fingerprint,
        "failure_binding_fingerprint": failure_binding_fingerprint,
    }
    matched_input_fingerprint = sha256_json(matched_input)
    if row_bindings.get("matched_input_fingerprint") != matched_input_fingerprint:
        raise FigureInputError(f"{run_id}: matched input fingerprint drift")
    expected_cell_fingerprint = sha256_json(
        {"matched_input_fingerprint": matched_input_fingerprint, "repetition": repetition}
    )
    if row_bindings.get("cell_fingerprint") != expected_cell_fingerprint:
        raise FigureInputError(f"{run_id}: cell fingerprint drift")
    return MatrixRow(
        run_id=run_id,
        result_hash=result_hash,
        suite=suite,
        variant_id=variant_id,
        context_bucket=context_bucket,
        scenario=scenario,
        seed=seed,
        repetition=repetition,
        payload=payload,
        raw=raw,
    )


def _validate_manifest_bindings(
    manifest: Mapping[str, Any],
    *,
    results_sha256: str,
    results_size_bytes: int,
    rows: Sequence[MatrixRow],
) -> None:
    _validate_manifest_artifact(
        manifest,
        name="results.jsonl",
        sha256=results_sha256,
        size_bytes=results_size_bytes,
    )

    expected = {row.run_id: (row.result_hash, str(row.raw.get("journal_sha256"))) for row in rows}
    binding_lists = [
        (key, _sequence(manifest[key], f"matrix_manifest.{key}"))
        for key in ("result_bindings", "results_index", "results")
        if key in manifest
    ]
    if not binding_lists:
        raise FigureInputError("matrix manifest has no explicit result binding index")
    for key, raw_bindings in binding_lists:
        observed: dict[str, tuple[str, str]] = {}
        for index, raw_binding in enumerate(raw_bindings):
            binding = _mapping(raw_binding, f"matrix_manifest.{key}[{index}]")
            run_id = _required_str(binding, "run_id", f"matrix_manifest.{key}[{index}]")
            payload_sha256 = _first_str(
                binding.get("payload_sha256"),
                binding.get("result_payload_sha256"),
                binding.get("result_hash"),
            )
            journal_sha256 = binding.get("journal_sha256")
            if payload_sha256 is None or _SHA256.fullmatch(payload_sha256) is None:
                raise FigureInputError(f"matrix_manifest.{key}[{index}]: invalid payload hash")
            if not isinstance(journal_sha256, str) or _SHA256.fullmatch(journal_sha256) is None:
                raise FigureInputError(f"matrix_manifest.{key}[{index}]: invalid journal hash")
            if run_id in observed:
                raise FigureInputError(f"matrix_manifest.{key}: duplicate binding for {run_id}")
            observed[run_id] = (payload_sha256, journal_sha256)
        if observed != expected:
            missing = sorted(set(expected) - set(observed))
            extra = sorted(set(observed) - set(expected))
            mismatched = sorted(
                run_id
                for run_id in set(expected) & set(observed)
                if expected[run_id] != observed[run_id]
            )
            raise FigureInputError(
                f"matrix_manifest.{key} differs from results: "
                f"missing={missing[:3]}, extra={extra[:3]}, mismatched={mismatched[:3]}"
            )


def _validate_manifest_artifact(
    manifest: Mapping[str, Any],
    *,
    name: str,
    sha256: str,
    size_bytes: int,
) -> None:
    artifact_maps = [
        (key, _mapping(manifest[key], f"matrix_manifest.{key}"))
        for key in ("artifact_hashes", "artifacts")
        if key in manifest
    ]
    if not artifact_maps:
        raise FigureInputError("matrix manifest has no artifact hash map")
    for key, artifacts in artifact_maps:
        artifact = _mapping(artifacts.get(name), f"matrix_manifest.{key}.{name}")
        if artifact.get("sha256") != sha256:
            raise FigureInputError(f"matrix manifest {name} SHA-256 mismatch")
        declared_size = artifact.get("size_bytes")
        if declared_size is not None and declared_size != size_bytes:
            raise FigureInputError(f"matrix manifest {name} size mismatch")


def _validate_matrix_completeness(rows: Sequence[MatrixRow], manifest: Mapping[str, Any]) -> None:
    if manifest.get("status") != "PASS":
        raise FigureInputError("matrix manifest status is not PASS")
    schema = manifest.get("schema")
    if schema != "moonkvsim.aegiskv.e2_matrix_suite.v1.manifest":
        raise FigureInputError(f"matrix manifest schema is unexpected: {schema!r}")
    fingerprint = manifest.get("fingerprint")
    if not isinstance(fingerprint, str) or _SHA256.fullmatch(fingerprint) is None:
        raise FigureInputError("matrix manifest fingerprint is missing or invalid")
    fingerprint_payload = dict(manifest)
    del fingerprint_payload["fingerprint"]
    if sha256_json(fingerprint_payload) != fingerprint:
        raise FigureInputError("matrix manifest fingerprint mismatch")
    evidence = _mapping(manifest.get("evidence"), "matrix_manifest.evidence")
    for key, expected in FIGURE_EVIDENCE.items():
        if evidence.get(key) != expected:
            raise FigureInputError(
                f"matrix_manifest.evidence.{key}: expected {expected!r}, got {evidence.get(key)!r}"
            )
    if evidence.get("slurm_used", False) is not False:
        raise FigureInputError("matrix manifest reports Slurm execution")
    result_count = manifest.get("result_count")
    if type(result_count) is not int or result_count != len(rows):
        raise FigureInputError(
            f"matrix manifest result_count {result_count!r} differs from {len(rows)} rows"
        )
    suites = {row.suite for row in rows}
    expected_suites = {"core", "ablation", "sensitivity"}
    if suites != expected_suites:
        raise FigureInputError(
            f"canonical all-suite figure inputs require suites {sorted(expected_suites)}, "
            f"got {sorted(suites)}"
        )
    seeds = sorted({row.seed for row in rows})
    if len(seeds) < 2:
        raise FigureInputError(
            f"canonical all-suite preview inputs require multiple seeds, got {seeds}"
        )
    for suite, expected_variant_ids in EXPECTED_VARIANT_IDS.items():
        actual_variant_ids = {row.variant_id for row in rows if row.suite == suite}
        if actual_variant_ids != set(expected_variant_ids):
            raise FigureInputError(
                f"{suite} variant catalog differs from canonical all-suite protocol"
            )
    by_cell: dict[tuple[str, str, str, str, int], list[MatrixRow]] = defaultdict(list)
    for row in rows:
        if row.raw.get("status") != "PASS":
            raise FigureInputError(f"{row.run_id}: result row status is not PASS")
        if row.raw.get("fresh_global_des_instance") is not True:
            raise FigureInputError(f"{row.run_id}: fresh GlobalDES instance not proven")
        row_evidence = _mapping(row.raw.get("evidence"), f"{row.run_id}.evidence")
        for evidence_key, expected in FIGURE_EVIDENCE.items():
            if row_evidence.get(evidence_key) != expected:
                raise FigureInputError(
                    f"{row.run_id}: row evidence boundary drifted at {evidence_key}"
                )
        by_cell[(row.suite, row.variant_id, row.context_bucket, row.scenario, row.seed)].append(row)
    for suite in sorted(expected_suites):
        variants = sorted({row.variant_id for row in rows if row.suite == suite})
        for variant_id in variants:
            for bucket in BUCKETS:
                for scenario in ("no_failure", "gpu_failure"):
                    for seed in seeds:
                        cell_key = (suite, variant_id, bucket, scenario, seed)
                        pair = by_cell.get(cell_key, [])
                        if sorted(row.repetition for row in pair) != ["A", "B"]:
                            raise FigureInputError(
                                f"matrix cell is missing an exact A/B pair: {cell_key}"
                            )
                        if len({row.result_hash for row in pair}) != 1:
                            raise FigureInputError(f"matrix A/B payload hashes differ: {cell_key}")
                        journals = [row.raw.get("journal_sha256") for row in pair]
                        if (
                            any(
                                not isinstance(value, str) or _SHA256.fullmatch(value) is None
                                for value in journals
                            )
                            or len(set(journals)) != 1
                        ):
                            raise FigureInputError(f"matrix A/B journal hashes differ: {cell_key}")


def _parse_representative(
    raw: Mapping[str, Any], rows_by_run: Mapping[str, MatrixRow]
) -> RepresentativeRun:
    if raw.get("schema") != "moonkvsim.aegiskv.e2_matrix_suite.v1.representative_run":
        raise FigureInputError("representative run has an unexpected schema")
    if raw.get("status") != "PASS":
        raise FigureInputError("representative run status is not PASS")
    run_id, result_hash = _row_binding(raw)
    row = rows_by_run.get(run_id)
    if row is None:
        raise FigureInputError(f"representative run {run_id} is absent from matrix results")
    if row.result_hash != result_hash:
        raise FigureInputError("representative result hash differs from matrix row")
    expected_rows = [
        candidate
        for candidate in rows_by_run.values()
        if candidate.suite == "core"
        and candidate.variant_id == "aegiskv_unified"
        and candidate.context_bucket == "128k"
        and candidate.scenario == "gpu_failure"
        and candidate.seed == min(item.seed for item in rows_by_run.values())
        and candidate.repetition == "A"
    ]
    if len(expected_rows) != 1 or row.run_id != expected_rows[0].run_id:
        raise FigureInputError(
            "representative run is not the frozen unified/128k/failure/min-seed/A row"
        )
    candidate = _mapping(raw.get("payload"), "representative.payload")
    if sha256_json(candidate) != result_hash or candidate != row.payload:
        raise FigureInputError("representative payload differs from its matrix row")
    if raw.get("journal_sha256") != row.raw.get("journal_sha256"):
        raise FigureInputError("representative journal hash differs from its matrix row")
    if raw.get("evidence") != row.raw.get("evidence"):
        raise FigureInputError("representative evidence differs from its matrix row")
    if raw.get("bindings") != row.raw.get("bindings"):
        raise FigureInputError("representative bindings differ from its matrix row")
    if raw.get("variant_config") != row.raw.get("variant_config"):
        raise FigureInputError("representative variant config differs from its matrix row")
    representative = _mapping(raw.get("representative"), "representative.representative")
    raw_details = raw.get("span_details", ())
    details = tuple(
        _mapping(item, f"representative.span_details[{index}]")
        for index, item in enumerate(_sequence(raw_details, "representative.span_details"))
    )
    required = {
        "failure_events",
        "recovery_events",
        "transfers",
        "peer_hbm_timeline",
        "store_dram_timeline",
    }
    missing = sorted(required - set(representative))
    if missing:
        raise FigureInputError(f"representative run misses event arrays: {missing}")
    for key in sorted(required):
        _sequence(representative[key], f"representative.representative.{key}")
    return RepresentativeRun(row=row, representative=representative, span_details=details)


def _number(value: object, location: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FigureInputError(f"{location}: expected number")
    if isinstance(value, float) and not math.isfinite(value):
        raise FigureInputError(f"{location}: non-finite number")
    return value


def _num(value: object, location: str) -> float:
    return float(_number(value, location))


def _nonnegative_int(value: object, location: str) -> int:
    if type(value) is not int or value < 0:
        raise FigureInputError(f"{location}: expected non-negative integer")
    return value


def _metric_number(row: MatrixRow, *keys: str) -> int | float:
    value: object = row.metrics
    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            raise FigureInputError(f"{row.run_id}.metrics.{'.'.join(keys)} missing")
        value = value[key]
    return _number(value, f"{row.run_id}.metrics.{'.'.join(keys)}")


def _metric(row: MatrixRow, *keys: str) -> float:
    return float(_metric_number(row, *keys))


def _sum_numeric_mapping(row: MatrixRow, *keys: str) -> float:
    value: object = row.metrics
    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            raise FigureInputError(f"{row.run_id}.metrics.{'.'.join(keys)} missing")
        value = value[key]
    mapping = _mapping(value, f"{row.run_id}.metrics.{'.'.join(keys)}")
    return sum(_num(item, f"{row.run_id}.{key}") for key, item in mapping.items())


def _sum_numeric_mapping_exact(row: MatrixRow, *keys: str) -> int | float:
    value: object = row.metrics
    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            raise FigureInputError(f"{row.run_id}.metrics.{'.'.join(keys)} missing")
        value = value[key]
    mapping = _mapping(value, f"{row.run_id}.metrics.{'.'.join(keys)}")
    values = [_number(item, f"{row.run_id}.{key}") for key, item in mapping.items()]
    return sum(values)


def _parameter(row: MatrixRow, key: str, default: float | None = None) -> float:
    candidates: tuple[object, ...] = (
        _nested(row.raw, "variant", "parameters", key),
        _nested(row.raw, "variant_config", "parameters", key),
        _nested(row.raw, "bindings", "variant", "parameters", key),
        _nested(row.raw, "bindings", "parameters", key),
        row.raw.get(key),
    )
    for value in candidates:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    if default is not None:
        return default
    raise FigureInputError(f"{row.run_id}: variant parameter {key} missing")


def _fmt(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise FigureInputError("SVG coordinate is non-finite")
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


class _Canvas:
    """Small deterministic SVG builder with no renderer dependency."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        self.root = ET.Element(
            "svg",
            {
                "xmlns": "http://www.w3.org/2000/svg",
                "width": str(SVG_WIDTH),
                "height": str(SVG_HEIGHT),
                "viewBox": f"0 0 {SVG_WIDTH} {SVG_HEIGHT}",
                "role": "img",
            },
        )
        ET.SubElement(self.root, "title").text = title
        style = ET.SubElement(self.root, "style")
        style.text = (
            "text{font-family:DejaVu Sans,Arial,sans-serif;fill:#111827}"
            ".title{font-size:26px;font-weight:700}.subtitle{font-size:14px;fill:#4b5563}"
            ".axis{stroke:#374151;stroke-width:1}.grid{stroke:#e5e7eb;stroke-width:1}"
            ".tick{font-size:12px;fill:#4b5563}.label{font-size:14px;font-weight:600}"
            ".small{font-size:11px}.footer{font-size:13px;font-weight:700;fill:#991b1b}"
        )
        self.rect(0, 0, SVG_WIDTH, SVG_HEIGHT, fill="#ffffff")
        self.text(55, 46, title, css="title")
        if subtitle:
            self.text(55, 74, subtitle, css="subtitle")

    def group(self, binding: PointBinding) -> ET.Element:
        attributes = {
            "data-point-id": binding.point_id,
            "data-run-id": binding.run_id,
            "data-result-hash": binding.result_hash,
        }
        vanilla_run_id = binding.coordinates.get("vanilla_run_id")
        vanilla_result_hash = binding.coordinates.get("vanilla_result_hash")
        if isinstance(vanilla_run_id, str) and isinstance(vanilla_result_hash, str):
            attributes["data-vanilla-run-id"] = vanilla_run_id
            attributes["data-vanilla-result-hash"] = vanilla_result_hash
        group = ET.SubElement(
            self.root,
            "g",
            attributes,
        )
        coordinates = json.dumps(
            dict(binding.coordinates),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        ET.SubElement(
            group, "title"
        ).text = f"{binding.point_id} | {binding.run_id} | {binding.result_hash} | {coordinates}"
        return group

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        stroke: str = "#374151",
        width: float = 1,
        parent: ET.Element | None = None,
        dash: str | None = None,
    ) -> ET.Element:
        attrs = {
            "x1": _fmt(x1),
            "y1": _fmt(y1),
            "x2": _fmt(x2),
            "y2": _fmt(y2),
            "stroke": stroke,
            "stroke-width": _fmt(width),
        }
        if dash is not None:
            attrs["stroke-dasharray"] = dash
        target = self.root if parent is None else parent
        return ET.SubElement(target, "line", attrs)

    def rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: str,
        stroke: str = "none",
        radius: float = 0,
        parent: ET.Element | None = None,
        opacity: float = 1,
    ) -> ET.Element:
        target = self.root if parent is None else parent
        return ET.SubElement(
            target,
            "rect",
            {
                "x": _fmt(x),
                "y": _fmt(y),
                "width": _fmt(max(0, width)),
                "height": _fmt(max(0, height)),
                "rx": _fmt(radius),
                "fill": fill,
                "stroke": stroke,
                "opacity": _fmt(opacity),
            },
        )

    def circle(
        self,
        x: float,
        y: float,
        radius: float,
        *,
        fill: str,
        stroke: str = "#ffffff",
        parent: ET.Element | None = None,
    ) -> ET.Element:
        target = self.root if parent is None else parent
        return ET.SubElement(
            target,
            "circle",
            {
                "cx": _fmt(x),
                "cy": _fmt(y),
                "r": _fmt(radius),
                "fill": fill,
                "stroke": stroke,
                "stroke-width": "1",
            },
        )

    def polyline(
        self,
        points: Sequence[tuple[float, float]],
        *,
        stroke: str,
        width: float = 2,
        parent: ET.Element | None = None,
    ) -> ET.Element:
        target = self.root if parent is None else parent
        return ET.SubElement(
            target,
            "polyline",
            {
                "points": " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in points),
                "fill": "none",
                "stroke": stroke,
                "stroke-width": _fmt(width),
                "stroke-linejoin": "round",
            },
        )

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        css: str = "tick",
        anchor: str = "start",
        parent: ET.Element | None = None,
        rotate: float | None = None,
    ) -> ET.Element:
        attrs = {
            "x": _fmt(x),
            "y": _fmt(y),
            "class": css,
            "text-anchor": anchor,
        }
        if rotate is not None:
            attrs["transform"] = f"rotate({_fmt(rotate)} {_fmt(x)} {_fmt(y)})"
        target = self.root if parent is None else parent
        element = ET.SubElement(target, "text", attrs)
        element.text = value
        return element

    def footer(self) -> None:
        self.line(55, 676, 1145, 676, stroke="#fecaca")
        self.text(600, 704, EVIDENCE_FOOTER, css="footer", anchor="middle")

    def serialize(self) -> str:
        self.footer()
        ET.indent(self.root, space="  ")
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(self.root, encoding="unicode", short_empty_elements=True)
            + "\n"
        )


def _scale(value: float, lower: float, upper: float, out_lower: float, out_upper: float) -> float:
    if upper <= lower:
        return (out_lower + out_upper) / 2
    return out_lower + (value - lower) * (out_upper - out_lower) / (upper - lower)


def _axes(
    canvas: _Canvas,
    *,
    x_label: str,
    y_label: str,
    y_max: float,
    x_labels: Sequence[str] = (),
) -> None:
    canvas.line(PLOT_LEFT, PLOT_TOP, PLOT_LEFT, PLOT_BOTTOM, width=1.4)
    canvas.line(PLOT_LEFT, PLOT_BOTTOM, PLOT_RIGHT, PLOT_BOTTOM, width=1.4)
    safe_y = max(1.0, y_max)
    for index in range(6):
        y = PLOT_BOTTOM - (PLOT_BOTTOM - PLOT_TOP) * index / 5
        value = safe_y * index / 5
        canvas.line(PLOT_LEFT, y, PLOT_RIGHT, y, stroke="#e5e7eb")
        canvas.text(PLOT_LEFT - 12, y + 4, _compact(value), anchor="end")
    if x_labels:
        step = (PLOT_RIGHT - PLOT_LEFT) / max(1, len(x_labels))
        for index, label in enumerate(x_labels):
            x = PLOT_LEFT + step * (index + 0.5)
            canvas.text(x, PLOT_BOTTOM + 18, label, anchor="middle", rotate=0)
    canvas.text((PLOT_LEFT + PLOT_RIGHT) / 2, 658, x_label, css="label", anchor="middle")
    canvas.text(22, (PLOT_TOP + PLOT_BOTTOM) / 2, y_label, css="label", rotate=-90)


def _compact(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2g}G"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.2g}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.2g}K"
    if absolute >= 10:
        return f"{value:.0f}"
    return f"{value:.2g}"


def _padded_nonnegative_domain(values: Sequence[float]) -> tuple[float, float]:
    if not values:
        raise FigureInputError("cannot scale an empty metric series")
    lower = min(values)
    upper = max(values)
    if lower < 0:
        raise FigureInputError("non-negative figure metric contains a negative value")
    spread = upper - lower
    padding = max(1.0, spread * 0.12, upper * 0.002)
    return max(0.0, lower - padding), upper + padding


def _point(
    row: MatrixRow,
    figure_id: str,
    index: int,
    **coordinates: int | float | str,
) -> PointBinding:
    return PointBinding(
        point_id=f"{figure_id.lower()}-point-{index:05d}",
        run_id=row.run_id,
        result_hash=row.result_hash,
        coordinates=coordinates,
    )


def _architecture(rep: RepresentativeRun, spec: _FigureSpec) -> _RenderedFigure:
    canvas = _Canvas(spec.title, "Design schematic only; not runtime-component execution proof")
    binding = _point(rep.row, spec.figure_id, 0, diagram="architecture")
    group = canvas.group(binding)
    boxes = (
        ("Router", 70, 210, "#dbeafe"),
        ("vLLM Source Workers\nproduction HBM", 265, 145, "#e0e7ff"),
        ("Global KV directory\n(single authority)", 505, 210, "#f3e8ff"),
        ("Peer-HBM pools\nD2D/P2P", 760, 125, "#dcfce7"),
        ("Store Master", 760, 285, "#ffedd5"),
        ("Store DRAM nodes\nsource D2H", 970, 285, "#fef3c7"),
    )
    for label, x, y, color in boxes:
        canvas.rect(x, y, 170, 90, fill=color, stroke="#475569", radius=10, parent=group)
        lines = label.split("\n")
        for line_index, line in enumerate(lines):
            canvas.text(
                x + 85,
                y + 40 + line_index * 19,
                line,
                css="label" if line_index == 0 else "tick",
                anchor="middle",
                parent=group,
            )
    arrows = (
        (240, 255, 265, 190, "route", 250, 210),
        (435, 190, 505, 235, "lookup / commit", 470, 205),
        (675, 235, 760, 170, "Peer decision", 715, 194),
        (675, 255, 760, 330, "Store candidate", 714, 278),
        (930, 330, 970, 330, "metadata + placement", 950, 276),
    )
    for x1, y1, x2, y2, label, label_x, label_y in arrows:
        canvas.line(x1, y1, x2, y2, stroke="#334155", width=2, parent=group)
        canvas.circle(x2, y2, 4, fill="#334155", parent=group)
        canvas.text(label_x, label_y, label, anchor="middle", parent=group)
    canvas.rect(255, 440, 700, 92, fill="#f8fafc", stroke="#94a3b8", radius=8, parent=group)
    canvas.text(
        605,
        474,
        "Source Worker owns direct production-HBM→Peer D2D and →Store D2H bytes",
        css="label",
        anchor="middle",
        parent=group,
    )
    canvas.text(
        605,
        502,
        "Directory/Store Master make metadata decisions; bytes do not traverse them",
        anchor="middle",
        parent=group,
    )
    return _RenderedFigure(
        canvas.serialize(),
        (binding,),
        (
            "design_schematic_not_runtime_component_execution_proof",
            "named_production_modules_are_not_claimed_as_executed_by_the_study_harness",
            "source_worker_owns_direct_D2D_and_D2H_data_paths_bytes_bypass_directory",
        ),
    )


def _timeline_events(rep: RepresentativeRun) -> list[tuple[int, str]]:
    representative = rep.representative
    failures = _sequence(representative["failure_events"], "failure_events")
    recoveries = _sequence(representative["recovery_events"], "recovery_events")
    events: list[tuple[int, str]] = []
    impacted_span_ids: set[str] = set()
    recovery_span_ids: set[str] = set()
    for index, raw in enumerate(failures):
        event = _mapping(raw, f"failure_events[{index}]")
        timestamp = _nonnegative_int(
            event.get("timestamp_ns"), f"failure_events[{index}].timestamp_ns"
        )
        events.extend(
            ((timestamp, "failure"), (timestamp, "execution/data-path fence (immediate)"))
        )
        for key in ("impacted_active_span_ids", "impacted_queued_span_ids"):
            raw_span_ids = event.get(key, ())
            for raw_span_id in _sequence(raw_span_ids, f"failure_events[{index}].{key}"):
                if not isinstance(raw_span_id, str) or not raw_span_id:
                    raise FigureInputError(
                        f"failure_events[{index}].{key}: expected non-empty span ids"
                    )
                impacted_span_ids.add(raw_span_id)
                if key == "impacted_active_span_ids":
                    recovery_span_ids.add(raw_span_id)
        schedule = rep.row.payload.get("failure_schedule")
        if isinstance(schedule, Mapping):
            delay = _nonnegative_int(schedule.get("detection_delay_ns", 0), "detection_delay_ns")
            detection_timestamp = timestamp + delay
            events.append((detection_timestamp, "detection (schedule-derived)"))
    for index, raw in enumerate(recoveries):
        event = _mapping(raw, f"recovery_events[{index}]")
        timestamp = _nonnegative_int(
            event.get("timestamp_ns"), f"recovery_events[{index}].timestamp_ns"
        )
        name = str(event.get("event", "recovery")).lower().replace("_", " ")
        if name == "recovery plan":
            events.append((timestamp, "reroute / recovery plan"))
        elif name == "recovery atomic activation":
            events.append((timestamp, "atomic activation / resume"))
        else:
            events.append((timestamp, name))
    recovery_transfer_intervals: list[tuple[int, int]] = []
    local_activation_timestamps: list[int] = []
    for index, raw in enumerate(_sequence(representative["transfers"], "transfers")):
        transfer = _mapping(raw, f"transfers[{index}]")
        cause = str(transfer.get("cause", ""))
        if not cause.startswith("AEGIS_RECOVERY_"):
            continue
        path = str(transfer.get("path", ""))
        start_ns = _nonnegative_int(transfer.get("start_ns"), f"transfers[{index}].start_ns")
        end_ns = _nonnegative_int(transfer.get("end_ns"), f"transfers[{index}].end_ns")
        if end_ns < start_ns:
            raise FigureInputError(f"transfers[{index}]: recovery transfer ends before start")
        if path == "PEER_HBM_LOCAL_ACTIVATION":
            if end_ns != start_ns:
                raise FigureInputError(
                    f"transfers[{index}]: local Peer activation must be zero-duration"
                )
            local_activation_timestamps.append(start_ns)
        elif path in {"D2D_P2P", "STORE_H2D"}:
            recovery_transfer_intervals.append((start_ns, end_ns))
    if recovery_transfer_intervals:
        events.append(
            (
                min(start for start, _end in recovery_transfer_intervals),
                "aggregate recovery transfer start",
            )
        )
        events.append(
            (
                max(end for _start, end in recovery_transfer_intervals),
                "aggregate recovery transfer end",
            )
        )
    for timestamp in sorted(set(local_activation_timestamps)):
        events.append((timestamp, "local Peer activation (zero-duration)"))
    explicit_resume = any(
        label in {"resume", "request resume", "atomic activation / resume"}
        for _, label in events
    )
    if impacted_span_ids and not explicit_resume:
        completion_timestamps: list[int] = []
        for index, detail in enumerate(rep.span_details):
            span_id = detail.get("span_id")
            if span_id not in impacted_span_ids:
                continue
            completed_ns = detail.get("completed_ns")
            if completed_ns is None:
                continue
            completion_timestamps.append(
                _nonnegative_int(completed_ns, f"span_details[{index}].completed_ns")
            )
        if completion_timestamps:
            events.append((max(completion_timestamps), "affected requests complete"))
    if not events:
        raise FigureInputError("F2 requires a representative GPU_FAILURE run")
    order = {
        name: index
        for index, name in enumerate(
            (
                "failure",
                "execution/data-path fence (immediate)",
                "detection (schedule-derived)",
                "reroute / recovery plan",
                "local Peer activation (zero-duration)",
                "aggregate recovery transfer start",
                "aggregate recovery transfer end",
                "prompt suffix recompute start",
                "prompt suffix recompute complete",
                "silent replay start",
                "silent replay complete",
                "atomic activation / resume",
                "request resume",
                "resume",
                "affected requests complete",
            )
        )
    }
    return sorted(events, key=lambda item: (item[0], order.get(item[1], 99), item[1]))


def _failure_timeline(rep: RepresentativeRun, spec: _FigureSpec) -> _RenderedFigure:
    events = _timeline_events(rep)
    has_affected_completion = any(label == "affected requests complete" for _, label in events)
    has_explicit_resume = any(
        label in {"resume", "request resume", "atomic activation / resume"}
        for _, label in events
    )
    if has_explicit_resume:
        subtitle = "Diagnostic aggregate recovery bounds with explicit resume on virtual time"
        terminal_note = "explicit_resume_event_present"
    elif has_affected_completion:
        subtitle = "Diagnostic aggregate bounds; final marker is affected-request completion"
        terminal_note = "affected_request_completion_is_not_an_explicit_resume_event"
    else:
        subtitle = "No explicit resume event; whole-run end is not used as a recovery proxy"
        terminal_note = "resume_event_unavailable_no_synthetic_run_end_marker"
    recovery_transfers = [
        item
        for item in _sequence(rep.representative["transfers"], "transfers")
        if isinstance(item, Mapping)
        and str(item.get("cause", "")).startswith("AEGIS_RECOVERY_")
    ]
    transfer_binding_note = (
        "recovery_transfer_records_bind_span_id_for_causal_join"
        if recovery_transfers
        and all(
            isinstance(item.get("span_id"), str) and bool(item.get("span_id"))
            for item in recovery_transfers
        )
        else (
            "representative_transfer_records_lack_span_id_so_no_single_span_"
            "causal_chain_is_claimed"
        )
    )
    canvas = _Canvas(spec.title, subtitle)
    start = min(item[0] for item in events)
    end = max(item[0] for item in events)
    canvas.line(100, 360, 1110, 360, stroke="#334155", width=3)
    bindings: list[PointBinding] = []
    display_labels = {
        "execution/data-path fence (immediate)": "immediate fail-stop fence",
        "detection (schedule-derived)": "detection",
        "reroute / recovery plan": "reroute + recovery plan",
        "prompt suffix recompute start": "recompute start",
        "prompt suffix recompute complete": "recompute complete",
        "atomic activation / resume": "atomic activation",
    }
    for index, (timestamp, label) in enumerate(events):
        x = _scale(float(timestamp), float(start), float(end), 130, 1080)
        binding = _point(rep.row, spec.figure_id, index, timestamp_ns=timestamp, event=label)
        bindings.append(binding)
        group = canvas.group(binding)
        color = (
            "#dc2626"
            if label in {"failure", "execution/data-path fence (immediate)"}
            else "#2563eb"
        )
        canvas.circle(x, 360, 9, fill=color, parent=group)
        label_x = _scale(float(index), 0, float(max(1, len(events) - 1)), 125, 1075)
        label_anchor = "start" if label_x < 190 else "end" if label_x > 1010 else "middle"
        above = index % 2 == 0
        canvas.line(
            x,
            350 if above else 370,
            label_x,
            260 if above else 460,
            stroke=color,
            parent=group,
        )
        canvas.text(
            label_x,
            242 if above else 486,
            display_labels.get(label, label),
            css="label",
            anchor=label_anchor,
            parent=group,
        )
        canvas.text(
            label_x,
            263 if above else 507,
            f"{(timestamp - start) / 1_000_000:.3f} ms",
            anchor=label_anchor,
            parent=group,
        )
    notes = (
        "execution_data_path_fence_is_immediate_at_failure_in_current_runtime",
        "detection_marker_is_derived_from_failure_schedule_delay",
        "reroute_marker_is_recovery_plan_route_selection_not_reroute_completion",
        "transfer_markers_are_aggregate_D2D_P2P_and_STORE_H2D_bounds_not_per_span_load",
        "local_peer_activation_is_zero_duration_and_not_a_load_transfer",
        "prompt_suffix_recompute_precedes_silent_replay_on_the_global_clock",
        "atomic_activation_marks_resume_before_remaining_decode",
        transfer_binding_note,
        terminal_note,
    )
    return _RenderedFigure(canvas.serialize(), tuple(bindings), notes)


def _pool_timeline(
    rep: RepresentativeRun,
    spec: _FigureSpec,
    *,
    key: str,
    series_key: str,
    color: str,
    subtitle: str,
    scope_note: str,
) -> _RenderedFigure:
    canvas = _Canvas(spec.title, subtitle)
    raw_series = rep.representative.get(series_key)
    sources: list[tuple[str, Sequence[Any]]] = []
    per_resource = isinstance(raw_series, Mapping) and bool(raw_series)
    if per_resource:
        assert isinstance(raw_series, Mapping)
        for resource_id, raw_points in sorted(raw_series.items()):
            sources.append((str(resource_id), _sequence(raw_points, f"{series_key}.{resource_id}")))
    else:
        sources.append(("aggregate_pool", _sequence(rep.representative[key], key)))
    series: list[tuple[str, list[tuple[int, int, int, int, int, str]]]] = []
    for resource_id, raw_points in sources:
        points: list[tuple[int, int, int, int, int, str]] = []
        for index, raw in enumerate(raw_points):
            point = _mapping(raw, f"{series_key}.{resource_id}[{index}]")
            timestamp = _nonnegative_int(
                point.get("timestamp_ns"),
                f"{series_key}.{resource_id}[{index}].timestamp_ns",
            )
            occupied = _nonnegative_int(
                point.get("occupied_bytes"),
                f"{series_key}.{resource_id}[{index}].occupied_bytes",
            )
            committed = _nonnegative_int(
                point.get("committed_bytes", occupied),
                f"{series_key}.{resource_id}[{index}].committed_bytes",
            )
            pending = _nonnegative_int(
                point.get("pending_bytes", 0),
                f"{series_key}.{resource_id}[{index}].pending_bytes",
            )
            unavailable = _nonnegative_int(
                point.get("unavailable_bytes", 0),
                f"{series_key}.{resource_id}[{index}].unavailable_bytes",
            )
            if occupied != committed + pending:
                raise FigureInputError(
                    f"{series_key}.{resource_id}[{index}]: occupancy does not conserve"
                )
            cause = str(point.get("cause", "UNKNOWN"))
            points.append((timestamp, occupied, committed, pending, unavailable, cause))
        if not points:
            raise FigureInputError(f"{series_key}.{resource_id} is empty")
        if any(current[0] < previous[0] for previous, current in itertools.pairwise(points)):
            raise FigureInputError(f"{series_key}.{resource_id}: timestamps must be non-decreasing")
        series.append((resource_id, points))
    all_points = [point for _resource_id, points in series for point in points]
    start = min(item[0] for item in all_points)
    end = max(item[0] for item in all_points)
    peak = max(item[1] for item in all_points)
    _axes(canvas, x_label="global virtual time", y_label="allocated bytes", y_max=float(peak))
    bindings: list[PointBinding] = []
    point_index = 0
    for series_index, (resource_id, points) in enumerate(series):
        series_color = color if len(series) == 1 else _COLORS[series_index % len(_COLORS)]
        xy = [
            (
                _scale(float(timestamp), float(start), float(end), PLOT_LEFT, PLOT_RIGHT),
                _scale(float(occupied), 0, float(max(1, peak)), PLOT_BOTTOM, PLOT_TOP),
            )
            for timestamp, occupied, _committed, _pending, _unavailable, _cause in points
        ]
        step_xy = [xy[0]]
        for previous, current in itertools.pairwise(xy):
            step_xy.extend(((current[0], previous[1]), current))
        canvas.polyline(step_xy, stroke=series_color, width=2.5)
        canvas.rect(130 + series_index * 180, 92, 14, 8, fill=series_color)
        canvas.text(150 + series_index * 180, 101, resource_id)
        for (
            timestamp,
            occupied,
            committed,
            pending,
            unavailable,
            cause,
        ), (x, y) in zip(points, xy, strict=True):
            binding = _point(
                rep.row,
                spec.figure_id,
                point_index,
                resource_id=resource_id,
                timestamp_ns=timestamp,
                occupied_bytes=occupied,
                committed_bytes=committed,
                pending_bytes=pending,
                unavailable_bytes=unavailable,
                cause=cause,
            )
            point_index += 1
            bindings.append(binding)
            group = canvas.group(binding)
            canvas.circle(x, y, 3, fill=series_color, parent=group)
    canvas.text(1120, 102, f"event-boundary peak: {_compact(float(peak))} B", anchor="end")
    note = (
        "per_resource_event_boundary_timelines"
        if per_resource
        else "aggregate_pool_timeline_not_per_gpu_or_per_store_node"
    )
    return _RenderedFigure(
        canvas.serialize(),
        tuple(bindings),
        (
            scope_note,
            note,
            "committed_plus_pending_equals_occupied_at_every_event_boundary",
            "unavailable_bytes_are_bound_separately_from_occupied_bytes",
            "peaks_are_from_event_boundaries_not_interval_samples",
        ),
    )


def _migration_gantt(rep: RepresentativeRun, spec: _FigureSpec) -> _RenderedFigure:
    canvas = _Canvas(
        spec.title,
        "Terminal transfer ledger: queue, service, commit/abort, and conserved bytes",
    )
    raw_transfers = _sequence(rep.representative["transfers"], "transfers")
    transfers: list[
        tuple[str, str, str, int, int, int, str, int, int, int, int, str | None]
    ] = []
    for index, raw in enumerate(raw_transfers):
        transfer = _mapping(raw, f"transfers[{index}]")
        transfer_id = _required_str(transfer, "transfer_id", f"transfers[{index}]")
        path = _required_str(transfer, "path", f"transfers[{index}]")
        cause = str(transfer.get("cause", "UNKNOWN"))
        start = _nonnegative_int(transfer.get("start_ns"), f"transfers[{index}].start_ns")
        end = _nonnegative_int(transfer.get("end_ns"), f"transfers[{index}].end_ns")
        size = _nonnegative_int(transfer.get("bytes"), f"transfers[{index}].bytes")
        status = str(transfer.get("status", "COMMITTED"))
        ready = _nonnegative_int(
            transfer.get("ready_ns", start), f"transfers[{index}].ready_ns"
        )
        planned_end = _nonnegative_int(
            transfer.get("planned_end_ns", end),
            f"transfers[{index}].planned_end_ns",
        )
        moved = _nonnegative_int(
            transfer.get("transferred_bytes", size),
            f"transfers[{index}].transferred_bytes",
        )
        aborted = _nonnegative_int(
            transfer.get("aborted_bytes", 0),
            f"transfers[{index}].aborted_bytes",
        )
        span_id_raw = transfer.get("span_id")
        span_id = span_id_raw if isinstance(span_id_raw, str) and span_id_raw else None
        if end < start:
            raise FigureInputError(f"transfer {transfer_id} ends before it starts")
        if (
            status not in {"COMMITTED", "ABORTED"}
            or ready > start
            or planned_end < end
            or size != moved + aborted
        ):
            raise FigureInputError(f"transfer {transfer_id} terminal ledger is inconsistent")
        transfers.append(
            (
                transfer_id,
                path,
                cause,
                start,
                end,
                size,
                status,
                ready,
                planned_end,
                moved,
                aborted,
                span_id,
            )
        )
    if not transfers:
        raise FigureInputError("F5 requires at least one representative transfer")
    transfers.sort(key=lambda item: (item[3], item[4], item[0]))
    if len(transfers) <= 40:
        shown = list(transfers)
    else:
        strata: dict[
            tuple[str, str],
            list[
                tuple[
                    str,
                    str,
                    str,
                    int,
                    int,
                    int,
                    str,
                    int,
                    int,
                    int,
                    int,
                    str | None,
                ]
            ],
        ] = defaultdict(list)
        for transfer_record in transfers:
            strata[(transfer_record[1], transfer_record[2])].append(transfer_record)
        shown = []
        round_index = 0
        while len(shown) < 40:
            added = False
            for stratum in sorted(strata):
                records = strata[stratum]
                if round_index < len(records):
                    shown.append(records[round_index])
                    added = True
                    if len(shown) == 40:
                        break
            if not added:
                break
            round_index += 1
        shown.sort(key=lambda item: (item[3], item[4], item[0]))
    start_ns = min(item[3] for item in shown)
    end_ns = max(item[4] for item in shown)
    row_height = min(12.0, 470 / max(1, len(shown)))
    bindings: list[PointBinding] = []
    for index, (
        transfer_id,
        path,
        cause,
        start,
        end,
        size,
        status,
        ready,
        planned_end,
        moved,
        aborted,
        span_id,
    ) in enumerate(shown):
        y = 130 + index * row_height
        x1 = _scale(float(start), float(start_ns), float(end_ns), 250, 1120)
        x2 = _scale(float(end), float(start_ns), float(end_ns), 250, 1120)
        binding = _point(
            rep.row,
            spec.figure_id,
            index,
            transfer_id=transfer_id,
            path=path,
            cause=cause,
            start_ns=start,
            end_ns=end,
            bytes=size,
            status=status,
            ready_ns=ready,
            planned_end_ns=planned_end,
            transferred_bytes=moved,
            aborted_bytes=aborted,
            span_id=span_id if span_id is not None else "UNBOUND",
        )
        bindings.append(binding)
        group = canvas.group(binding)
        color = (
            "#dc2626"
            if status == "ABORTED"
            else _COLORS[sum(path.encode("utf-8")) % len(_COLORS)]
        )
        if end == start:
            canvas.line(x1, y, x1, y + max(4, row_height - 2), stroke=color, width=3, parent=group)
            canvas.circle(x1, y + max(4, row_height - 2) / 2, 3, fill=color, parent=group)
        else:
            canvas.rect(x1, y, x2 - x1, max(4, row_height - 2), fill=color, parent=group)
        short_path = path if len(path) <= 18 else f"{path[:15]}…"
        canvas.text(
            240,
            y + row_height - 3,
            f"{short_path} · {transfer_id[-12:]}",
            anchor="end",
            parent=group,
        )
        ET.SubElement(group, "desc").text = (
            f"cause={cause}; status={status}; submitted={size}; "
            f"transferred={moved}; aborted={aborted}"
        )
    canvas.line(250, 110, 250, 625)
    canvas.line(250, 625, 1120, 625)
    canvas.text(
        685,
        648,
        f"global virtual time · displayed {len(shown)}/{len(transfers)} transfers",
        css="label",
        anchor="middle",
    )
    notes = (
        "terminal_transfer_rows_conserve_submitted_equals_transferred_plus_aborted_bytes",
        "ready_start_planned_end_and_terminal_end_expose_queue_and_service_intervals",
        "resource_intervals_are_available_in_representative_schema_but_not_drawn_as_separate_rows",
        (
            "all_displayed_transfers_bind_span_id"
            if all(item[11] is not None for item in shown)
            else "some_displayed_transfers_lack_span_id"
        ),
    ) + (
        ()
        if len(transfers) <= 40
        else (
            f"displayed_40_of_{len(transfers)}",
            "selection_is_round_robin_stratified_by_path_and_cause_then_displayed_by_time",
        )
    )
    return _RenderedFigure(canvas.serialize(), tuple(bindings), notes)


def _label(row: MatrixRow) -> str:
    return f"{row.variant_id}/{row.context_bucket}/{row.scenario}/s{row.seed}{row.repetition}"


def _minimum_seed_a(rows: Sequence[MatrixRow]) -> list[MatrixRow]:
    """Choose the declared minimum seed/repeat-A without inspecting outcomes."""

    if not rows:
        return []
    seed = min(row.seed for row in rows)
    selected = [row for row in rows if row.seed == seed and row.repetition == "A"]
    if not selected:
        raise FigureInputError("canonical matrix has no repeat-A row at its minimum seed")
    return selected


def _bucket_legend(canvas: _Canvas, *, y: float = 94) -> None:
    start_x = 325.0
    for index, bucket in enumerate(BUCKETS):
        x = start_x + index * 112
        canvas.circle(x, y - 4, 4, fill=_COLORS[index])
        canvas.text(x + 9, y, bucket, css="small")


def _seed_jitter(seed: int, seeds: Sequence[int]) -> float:
    if len(seeds) <= 1:
        return 0.0
    return _scale(float(seeds.index(seed)), 0, float(len(seeds) - 1), -6, 6)


def _categorical_bars(
    rows: Sequence[MatrixRow],
    spec: _FigureSpec,
    *,
    value_fn: Any,
    y_label: str,
    subtitle: str,
    max_rows: int = 80,
) -> _RenderedFigure:
    selected = sorted(
        rows,
        key=lambda row: (
            row.variant_id,
            BUCKETS.index(row.context_bucket),
            row.seed,
            row.repetition,
        ),
    )[:max_rows]
    if not selected:
        raise FigureInputError(f"{spec.figure_id} has no eligible matrix rows")
    values = [float(value_fn(row)) for row in selected]
    peak = max(values, default=1.0)
    canvas = _Canvas(spec.title, subtitle)
    _axes(canvas, x_label="canonical matrix row (stable order)", y_label=y_label, y_max=peak)
    step = (PLOT_RIGHT - PLOT_LEFT) / len(selected)
    bindings: list[PointBinding] = []
    for index, (row, value) in enumerate(zip(selected, values, strict=True)):
        x = PLOT_LEFT + index * step + step * 0.12
        width = max(1.0, step * 0.76)
        y = _scale(value, 0, max(1.0, peak), PLOT_BOTTOM, PLOT_TOP)
        binding = _point(row, spec.figure_id, index, value=value, label=_label(row))
        bindings.append(binding)
        group = canvas.group(binding)
        color = _COLORS[BUCKETS.index(row.context_bucket) % len(_COLORS)]
        canvas.rect(x, y, width, PLOT_BOTTOM - y, fill=color, parent=group, opacity=0.82)
    canvas.text(1125, 102, f"n={len(selected)}", anchor="end")
    return _RenderedFigure(canvas.serialize(), tuple(bindings))


def _wct_goodput(rows: Sequence[MatrixRow], spec: _FigureSpec) -> _RenderedFigure:
    core = _minimum_seed_a([row for row in rows if row.suite == "core"])
    if not core:
        raise FigureInputError("F6 requires core-suite rows")
    compared_variants = ("vanilla_mooncake_dram", "aegiskv_unified")
    indexed: dict[tuple[str, str, str], MatrixRow] = {}
    for row in core:
        if row.variant_id not in compared_variants:
            continue
        key = (row.variant_id, row.context_bucket, row.scenario)
        if key in indexed:
            raise FigureInputError(f"F6 duplicate comparison row for {row.run_id}")
        indexed[key] = row
    expected_pair_keys = {
        (variant, bucket, scenario)
        for variant in compared_variants
        for bucket in BUCKETS
        for scenario in ("no_failure", "gpu_failure")
    }
    if set(indexed) != expected_pair_keys:
        raise FigureInputError("F6 Vanilla/AegisKV matched comparison grid is incomplete")
    pair_keys = [
        (bucket, scenario) for bucket in BUCKETS for scenario in ("no_failure", "gpu_failure")
    ]
    matched_binding_keys = (
        "implementation_fingerprint",
        "workload_fingerprint",
        "protocol_fingerprint",
        "parameters_fingerprint",
        "context_bucket",
        "scenario",
        "seed",
        "failure_schedule_fingerprint",
        "failure_binding_fingerprint",
        "implementation_commit",
        "workload_sha256",
    )
    for bucket, scenario in pair_keys:
        baseline = indexed[(compared_variants[0], bucket, scenario)]
        aegis = indexed[(compared_variants[1], bucket, scenario)]
        baseline_bindings = _mapping(baseline.raw.get("bindings"), f"{baseline.run_id}.bindings")
        aegis_bindings = _mapping(aegis.raw.get("bindings"), f"{aegis.run_id}.bindings")
        mismatch = [
            key
            for key in matched_binding_keys
            if key not in baseline_bindings
            or key not in aegis_bindings
            or baseline_bindings[key] != aegis_bindings[key]
        ]
        if mismatch:
            raise FigureInputError(
                f"F6 pair {baseline.run_id}/{aegis.run_id} is not matched at {mismatch}"
            )
    canvas = _Canvas(
        spec.title,
        "Whole-workload metrics; bucket is failure-focus cell; matched Vanilla↔AegisKV",
    )
    _bucket_legend(canvas)
    canvas.circle(890, 90, 5, fill="#ffffff", stroke="#334155")
    canvas.text(902, 95, "Vanilla", css="small")
    canvas.circle(995, 90, 5, fill="#334155", stroke="#334155")
    canvas.text(1007, 95, "AegisKV", css="small")
    bindings: list[PointBinding] = []
    metrics: tuple[tuple[str, Callable[[MatrixRow], float]], ...] = (
        (
            "mean workflow WCT (ms)",
            lambda row: _metric(row, "workflow_completion_time_ns", "mean") / 1_000_000,
        ),
        (
            "goodput (tokens/s)",
            lambda row: _metric(row, "goodput_output_tokens_per_second_milli") / 1_000,
        ),
    )
    point_index = 0
    panel_width = 510.0
    for panel, (title, getter) in enumerate(metrics):
        left = 55.0 + panel * 580
        right = left + panel_width
        top = 125.0
        bottom = 535.0
        comparison_rows = list(indexed.values())
        panel_values = [getter(row) for row in comparison_rows]
        domain_lower, domain_upper = _padded_nonnegative_domain(panel_values)
        canvas.line(left, top, left, bottom)
        canvas.line(left, bottom, right, bottom)
        canvas.text((left + right) / 2, 115, title, css="label", anchor="middle")
        for pair_index, (bucket, scenario) in enumerate(pair_keys):
            x = _scale(
                float(pair_index),
                0,
                float(len(pair_keys) - 1),
                left + 28,
                right - 18,
            )
            baseline = indexed[(compared_variants[0], bucket, scenario)]
            aegis = indexed[(compared_variants[1], bucket, scenario)]
            baseline_value = getter(baseline)
            aegis_value = getter(aegis)
            baseline_y = _scale(baseline_value, domain_lower, domain_upper, bottom, top)
            aegis_y = _scale(aegis_value, domain_lower, domain_upper, bottom, top)
            color = _COLORS[BUCKETS.index(bucket)]
            canvas.line(x, baseline_y, x, aegis_y, stroke=color, width=1.5)
            for system, row, value, y in (
                (compared_variants[0], baseline, baseline_value, baseline_y),
                (compared_variants[1], aegis, aegis_value, aegis_y),
            ):
                binding = _point(
                    row,
                    spec.figure_id,
                    point_index,
                    panel=title,
                    value=value,
                    variant_id=system,
                    context_bucket=bucket,
                    scenario=scenario,
                    matched_pair=f"{bucket}/{scenario}",
                )
                point_index += 1
                bindings.append(binding)
                group = canvas.group(binding)
                canvas.circle(
                    x,
                    y,
                    3.5,
                    fill="#ffffff" if system == compared_variants[0] else color,
                    stroke=color,
                    parent=group,
                )
            canvas.text(x, bottom + 16, bucket, css="small", anchor="middle")
            canvas.text(
                x,
                bottom + 29,
                "NF" if scenario == "no_failure" else "GF",
                css="small",
                anchor="middle",
            )
        canvas.text(left - 8, top + 4, _compact(domain_upper), anchor="end")
        canvas.text(left - 8, bottom + 4, _compact(domain_lower), anchor="end")
    canvas.text(600, 590, "NF=no failure · GF=GPU failure", css="small", anchor="middle")
    return _RenderedFigure(
        canvas.serialize(),
        tuple(bindings),
        (
            "minimum_seed_repeat_A_diagnostic_no_cross_seed_statistics_or_confidence_interval",
            "each_line_connects_exact_Vanilla_and_unified_AegisKV_rows_at_same_bucket_scenario_seed",
            "bucket_is_color_encoded_and_system_is_fill_encoded",
            "per_panel_axis_is_zoomed_with_explicit_nonzero_lower_and_upper_labels",
            "WCT_and_goodput_are_whole_workload_metrics_bucket_is_the_failure_focus_cell",
        ),
    )


def _recovery_cdf(rows: Sequence[MatrixRow], spec: _FigureSpec) -> _RenderedFigure:
    selected = [
        row
        for row in rows
        if row.suite == "core"
        and row.scenario == "gpu_failure"
        and row.repetition == "A"
        and _metric(row, "recovery_latency_ns", "count") > 0
    ]
    if not selected:
        raise FigureInputError("F7 requires failure rows with recovery samples")
    grouped: dict[str, list[MatrixRow]] = defaultdict(list)
    for row in selected:
        peer = _metric(row, "restored_tokens", "peer_hbm")
        store = _metric(row, "restored_tokens", "store_dram")
        recompute = _metric(row, "recompute_tokens_after_failure")
        maximum = max(peer, store, recompute)
        if maximum == peer and peer > 0:
            group = "Peer-HBM dominant"
        elif maximum == store and store > 0:
            group = "Store DRAM dominant"
        else:
            group = "Recompute dominant"
        grouped[group].append(row)
    values = [_metric(row, "recovery_latency_ns", "mean") / 1_000_000 for row in selected]
    canvas = _Canvas(
        spec.title,
        "Core repeat-A means: failure to SILENT_REPLAY_COMPLETE (runtime recovery_ready)",
    )
    _axes(
        canvas,
        x_label="runtime recovery_ready mean: failure → silent replay complete (ms)",
        y_label="empirical CDF",
        y_max=1.0,
    )
    peak_x = max(values, default=1.0)
    bindings: list[PointBinding] = []
    point_index = 0
    for group_index, (source, source_rows) in enumerate(sorted(grouped.items())):
        source_rows.sort(key=lambda row: (_metric(row, "recovery_latency_ns", "mean"), row.run_id))
        poly: list[tuple[float, float]] = []
        previous_y = float(PLOT_BOTTOM)
        color = _COLORS[group_index]
        for index, row in enumerate(source_rows, start=1):
            value = _metric(row, "recovery_latency_ns", "mean") / 1_000_000
            x = _scale(value, 0, max(1.0, peak_x), PLOT_LEFT, PLOT_RIGHT)
            cdf = index / len(source_rows)
            y = _scale(cdf, 0, 1, PLOT_BOTTOM, PLOT_TOP)
            poly.extend(((x, previous_y), (x, y)))
            previous_y = y
            binding = _point(
                row,
                spec.figure_id,
                point_index,
                recovery_source_group=source,
                recovery_mean_ms=value,
                cdf=cdf,
            )
            point_index += 1
            bindings.append(binding)
            mark = canvas.group(binding)
            canvas.circle(x, y, 4, fill=color, parent=mark)
        canvas.polyline(poly, stroke=color, width=2)
        canvas.rect(130 + group_index * 250, 92, 14, 8, fill=color)
        canvas.text(150 + group_index * 250, 101, source)
    canvas.text(1120, 102, f"max={peak_x:.3f} ms · n={len(selected)}", anchor="end")
    return _RenderedFigure(
        canvas.serialize(),
        tuple(bindings),
        (
            "ecdf_samples_are_per_run_recovery_means_not_request_level_latencies",
            "runtime_metric_is_failure_to_SILENT_REPLAY_COMPLETE_not_resume_or_request_completion",
            "ecdf_is_core_system_cell_weighted_not_a_request_population_distribution",
            "source_group_is_dominant_modeled_token_source_not_an_exclusive_recovery_path",
        ),
    )


def _coverage_recompute(rows: Sequence[MatrixRow], spec: _FigureSpec) -> _RenderedFigure:
    selected = _minimum_seed_a(
        [row for row in rows if row.scenario == "gpu_failure" and row.suite == "core"]
    )
    selected.sort(key=lambda row: (row.variant_id, BUCKETS.index(row.context_bucket)))
    if not selected:
        raise FigureInputError("F8 requires core GPU_FAILURE rows")
    components = (
        ("Peer-HBM restore", "#2563eb"),
        ("Store DRAM restore", "#d97706"),
        ("Recompute", "#dc2626"),
    )
    values = [
        (
            _metric(row, "restored_tokens", "peer_hbm"),
            _metric(row, "restored_tokens", "store_dram"),
            _metric(row, "recompute_tokens_after_failure"),
        )
        for row in selected
    ]
    peak = max(sum(item) for item in values)
    canvas = _Canvas(
        spec.title,
        "Minimum-seed repeat-A diagnostic: continuous-prefix restore vs recomputation",
    )
    _axes(
        canvas,
        x_label="core system / context bucket at minimum declared seed",
        y_label="tokens after GPU failure",
        y_max=peak,
    )
    step = (PLOT_RIGHT - PLOT_LEFT) / len(selected)
    bindings: list[PointBinding] = []
    for index, (row, row_values) in enumerate(zip(selected, values, strict=True)):
        x = PLOT_LEFT + index * step + step * 0.12
        width = max(1.0, step * 0.76)
        cumulative = 0.0
        binding = _point(
            row,
            spec.figure_id,
            index,
            peer_hbm_restore_tokens=row_values[0],
            store_dram_restore_tokens=row_values[1],
            recompute_tokens=row_values[2],
        )
        bindings.append(binding)
        group = canvas.group(binding)
        for value, (_label_text, color) in zip(row_values, components, strict=True):
            y1 = _scale(cumulative, 0, max(1.0, peak), PLOT_BOTTOM, PLOT_TOP)
            cumulative += value
            y2 = _scale(cumulative, 0, max(1.0, peak), PLOT_BOTTOM, PLOT_TOP)
            canvas.rect(x, y2, width, y1 - y2, fill=color, parent=group)
    for index, (label, color) in enumerate(components):
        canvas.rect(140 + index * 250, 92, 14, 8, fill=color)
        canvas.text(160 + index * 250, 101, label)
    return _RenderedFigure(
        canvas.serialize(),
        tuple(bindings),
        ("minimum_seed_repeat_A_diagnostic_no_cross_seed_statistics_or_confidence_interval",),
    )


def _ablation(rows: Sequence[MatrixRow], spec: _FigureSpec) -> _RenderedFigure:
    selected = _minimum_seed_a(
        [row for row in rows if row.suite == "ablation" and row.scenario == "gpu_failure"]
    )
    rendered = _categorical_bars(
        selected,
        spec,
        value_fn=lambda row: _metric(row, "workflow_completion_time_ns", "mean") / 1_000_000,
        y_label="mean workflow WCT (ms)",
        subtitle="Minimum-seed repeat-A WCT diagnostic across policy variants; modeled only",
    )
    return _RenderedFigure(
        rendered.svg,
        rendered.bindings,
        ("minimum_seed_repeat_A_diagnostic_no_cross_seed_statistics_or_confidence_interval",),
    )


def _budget_sensitivity(rows: Sequence[MatrixRow], spec: _FigureSpec) -> _RenderedFigure:
    selected = [
        row
        for row in rows
        if row.suite == "sensitivity"
        and row.scenario == "gpu_failure"
        and row.repetition == "A"
        and (
            row.variant_id.startswith("peer_budget_gib=")
            or row.variant_id.startswith("store_budget_gib=")
        )
    ]
    if not selected:
        raise FigureInputError("F10 requires sensitivity-suite rows")
    canvas = _Canvas(
        spec.title,
        "Separate Peer/GPU and Store axes; bucket color; deterministic seed jitter",
    )
    _bucket_legend(canvas)
    declared_seeds = sorted({row.seed for row in selected})
    dimensions: tuple[tuple[str, str, Callable[[MatrixRow], float]], ...] = (
        (
            "Peer-HBM budget (GiB/GPU)",
            "peer_budget_gib=",
            lambda row: _parameter(row, "peer_budget_bytes_per_gpu") / 1024**3,
        ),
        (
            "Store DRAM budget (global GiB)",
            "store_budget_gib=",
            lambda row: _parameter(row, "store_budget_bytes") / 1024**3,
        ),
    )
    metrics: tuple[tuple[str, Callable[[MatrixRow], float]], ...] = (
        (
            "mean WCT (ms)",
            lambda row: _metric(row, "workflow_completion_time_ns", "mean") / 1_000_000,
        ),
        (
            "goodput (tokens/s)",
            lambda row: _metric(row, "goodput_output_tokens_per_second_milli") / 1_000,
        ),
        ("restored tokens", lambda row: _metric(row, "restored_tokens", "total")),
    )
    bindings: list[PointBinding] = []
    panel_width = 350.0
    panel_height = 210.0
    panel_lefts = (35.0, 425.0, 815.0)
    panel_tops = (105.0, 370.0)
    point_index = 0
    for dimension_index, (dimension_label, prefix, x_getter) in enumerate(dimensions):
        dimension_rows = sorted(
            (row for row in selected if row.variant_id.startswith(prefix)),
            key=lambda row: (
                x_getter(row),
                BUCKETS.index(row.context_bucket),
                row.seed,
                row.run_id,
            ),
        )
        if not dimension_rows:
            raise FigureInputError(f"F10 lacks {prefix} sensitivity rows")
        for metric_index, (metric_label, y_getter) in enumerate(metrics):
            left = panel_lefts[metric_index]
            top = panel_tops[dimension_index]
            right = left + panel_width
            bottom = top + panel_height
            values = [(row, x_getter(row), y_getter(row)) for row in dimension_rows]
            min_x = min(value[1] for value in values)
            max_x = max(value[1] for value in values)
            y_lower, y_upper = _padded_nonnegative_domain([value[2] for value in values])
            canvas.rect(
                left,
                top,
                panel_width,
                panel_height,
                fill="#f8fafc",
                stroke="#cbd5e1",
                radius=4,
            )
            canvas.line(left + 48, top + 25, left + 48, bottom - 38, stroke="#64748b")
            canvas.line(
                left + 48,
                bottom - 38,
                right - 12,
                bottom - 38,
                stroke="#64748b",
            )
            canvas.text(
                left + panel_width / 2, top + 17, metric_label, css="label", anchor="middle"
            )
            canvas.text(
                left + panel_width / 2,
                bottom - 6,
                dimension_label,
                css="small",
                anchor="middle",
            )
            canvas.text(left + 43, top + 29, _compact(y_upper), css="small", anchor="end")
            canvas.text(
                left + 43, bottom - 39, _compact(y_lower), css="small", anchor="end"
            )
            for tick_value in sorted({value[1] for value in values}):
                tick_x = _scale(tick_value, min_x, max_x, left + 65, right - 28)
                canvas.line(tick_x, bottom - 38, tick_x, bottom - 33, stroke="#64748b")
                canvas.text(
                    tick_x,
                    bottom - 22,
                    _compact(tick_value),
                    css="small",
                    anchor="middle",
                )
            canvas.text(
                right - 16,
                top + 31,
                f"n={len(values)} seeds={','.join(str(seed) for seed in declared_seeds)}",
                css="small",
                anchor="end",
            )
            for row, budget, metric_value in values:
                jitter = _seed_jitter(row.seed, declared_seeds) + (
                    BUCKETS.index(row.context_bucket) - 2
                )
                x = _scale(budget, min_x, max_x, left + 65, right - 28) + jitter
                y = _scale(metric_value, y_lower, y_upper, bottom - 44, top + 32)
                binding = _point(
                    row,
                    spec.figure_id,
                    point_index,
                    sensitivity_dimension=prefix.removesuffix("="),
                    budget=budget,
                    budget_label=dimension_label,
                    metric=metric_label,
                    metric_value=metric_value,
                    seed=row.seed,
                    context_bucket=row.context_bucket,
                    display_x_jitter_px=jitter,
                )
                point_index += 1
                bindings.append(binding)
                group = canvas.group(binding)
                canvas.circle(
                    x,
                    y,
                    3,
                    fill=_COLORS[BUCKETS.index(row.context_bucket)],
                    parent=group,
                )
    return _RenderedFigure(
        canvas.serialize(),
        tuple(bindings),
        (
            "peer_per_gpu_and_global_store_budgets_are_never_summed",
            "one_at_a_time_sensitivity_repeat_A_across_all_declared_seeds",
            "bucket_is_color_encoded_and_seed_uses_deterministic_horizontal_jitter",
            "recovery_axis_is_restored_tokens_not_observed_or_physical_recovery_benefit",
        ),
    )


def _scale_sensitivity(rows: Sequence[MatrixRow], spec: _FigureSpec) -> _RenderedFigure:
    selected = [
        row
        for row in rows
        if row.suite == "sensitivity"
        and row.scenario == "gpu_failure"
        and row.repetition == "A"
        and (
            row.variant_id.startswith("store_bandwidth_gbps=")
            or row.variant_id.startswith("peer_fabric_bandwidth_gbps=")
            or row.variant_id.startswith("detection_delay_ms=")
            or row.variant_id.startswith("reroute_delay_ms=")
        )
    ]
    if not selected:
        raise FigureInputError("F11 requires sensitivity-suite rows")
    canvas = _Canvas(
        spec.title,
        "Separate bandwidth and control-delay axes; bucket color; seed jitter",
    )
    _bucket_legend(canvas)
    declared_seeds = sorted({row.seed for row in selected})
    dimensions: tuple[tuple[str, str, Callable[[MatrixRow], float]], ...] = (
        (
            "Store bandwidth (GB/s)",
            "store_bandwidth_gbps=",
            lambda row: _parameter(row, "store_bandwidth_bytes_per_second") / 1_000_000_000,
        ),
        (
            "Peer fabric (GB/s)",
            "peer_fabric_bandwidth_gbps=",
            lambda row: _parameter(row, "peer_bandwidth_bytes_per_second") / 1_000_000_000,
        ),
        (
            "Detection delay (ms)",
            "detection_delay_ms=",
            lambda row: _parameter(row, "failure_detection_ns") / 1_000_000,
        ),
        (
            "Reroute delay (ms)",
            "reroute_delay_ms=",
            lambda row: _parameter(row, "reroute_ns") / 1_000_000,
        ),
    )
    metrics: tuple[tuple[str, Callable[[MatrixRow], float]], ...] = (
        (
            "goodput (tokens/s)",
            lambda row: _metric(row, "goodput_output_tokens_per_second_milli") / 1_000,
        ),
        (
            "mean WCT (ms)",
            lambda row: _metric(row, "workflow_completion_time_ns", "mean") / 1_000_000,
        ),
    )
    bindings: list[PointBinding] = []
    panel_width = 250.0
    panel_height = 210.0
    panel_lefts = (40.0, 330.0, 620.0, 910.0)
    panel_tops = (105.0, 370.0)
    point_index = 0
    for dimension_index, (dimension_label, prefix, x_getter) in enumerate(dimensions):
        dimension_rows = sorted(
            (row for row in selected if row.variant_id.startswith(prefix)),
            key=lambda row: (
                x_getter(row),
                BUCKETS.index(row.context_bucket),
                row.seed,
                row.run_id,
            ),
        )
        if not dimension_rows:
            raise FigureInputError(f"F11 lacks {prefix} sensitivity rows")
        for metric_index, (metric_label, y_getter) in enumerate(metrics):
            left = panel_lefts[dimension_index]
            top = panel_tops[metric_index]
            right = left + panel_width
            bottom = top + panel_height
            values = [(row, x_getter(row), y_getter(row)) for row in dimension_rows]
            min_x = min(value[1] for value in values)
            max_x = max(value[1] for value in values)
            y_lower, y_upper = _padded_nonnegative_domain([value[2] for value in values])
            canvas.rect(
                left,
                top,
                panel_width,
                panel_height,
                fill="#f8fafc",
                stroke="#cbd5e1",
                radius=4,
            )
            canvas.line(left + 48, top + 25, left + 48, bottom - 38, stroke="#64748b")
            canvas.line(
                left + 48,
                bottom - 38,
                right - 12,
                bottom - 38,
                stroke="#64748b",
            )
            canvas.text(
                left + panel_width / 2, top + 17, metric_label, css="label", anchor="middle"
            )
            canvas.text(
                left + panel_width / 2,
                bottom - 6,
                dimension_label,
                css="small",
                anchor="middle",
            )
            canvas.text(left + 43, top + 29, _compact(y_upper), css="small", anchor="end")
            canvas.text(
                left + 43, bottom - 39, _compact(y_lower), css="small", anchor="end"
            )
            for tick_value in sorted({value[1] for value in values}):
                tick_x = _scale(tick_value, min_x, max_x, left + 65, right - 28)
                canvas.line(tick_x, bottom - 38, tick_x, bottom - 33, stroke="#64748b")
                canvas.text(
                    tick_x,
                    bottom - 22,
                    _compact(tick_value),
                    css="small",
                    anchor="middle",
                )
            canvas.text(
                right - 16,
                top + 31,
                f"n={len(values)} seeds={','.join(str(seed) for seed in declared_seeds)}",
                css="small",
                anchor="end",
            )
            for row, scale_value, metric_value in values:
                jitter = _seed_jitter(row.seed, declared_seeds) + (
                    BUCKETS.index(row.context_bucket) - 2
                )
                x = _scale(scale_value, min_x, max_x, left + 65, right - 28) + jitter
                y = _scale(metric_value, y_lower, y_upper, bottom - 44, top + 32)
                binding = _point(
                    row,
                    spec.figure_id,
                    point_index,
                    sensitivity_dimension=prefix.removesuffix("="),
                    scale_value=scale_value,
                    scale_label=dimension_label,
                    metric=metric_label,
                    metric_value=metric_value,
                    seed=row.seed,
                    context_bucket=row.context_bucket,
                    display_x_jitter_px=jitter,
                )
                point_index += 1
                bindings.append(binding)
                group = canvas.group(binding)
                canvas.circle(
                    x,
                    y,
                    3,
                    fill=_COLORS[BUCKETS.index(row.context_bucket)],
                    parent=group,
                )
    return _RenderedFigure(
        canvas.serialize(),
        tuple(bindings),
        (
            "store_peer_fabric_detection_and_reroute_use_separate_axes",
            "store_node_count_not_parameterized_in_canonical_E2_matrix",
            "one_at_a_time_sensitivity_repeat_A_across_all_declared_seeds",
            "bucket_is_color_encoded_and_seed_uses_deterministic_horizontal_jitter",
        ),
    )


def _resource_cost(rows: Sequence[MatrixRow], spec: _FigureSpec) -> _RenderedFigure:
    aegis_rows = _minimum_seed_a(
        [
            row
            for row in rows
            if row.suite == "core"
            and row.scenario == "gpu_failure"
            and row.variant_id == "aegiskv_unified"
        ]
    )
    vanilla_index = {
        (row.context_bucket, row.scenario, row.seed, row.repetition): row
        for row in rows
        if row.suite == "core" and row.variant_id == "vanilla_mooncake_dram"
    }
    pairs: list[tuple[MatrixRow, MatrixRow]] = []
    for row in sorted(aegis_rows, key=lambda item: BUCKETS.index(item.context_bucket)):
        key = (row.context_bucket, row.scenario, row.seed, row.repetition)
        vanilla = vanilla_index.get(key)
        if vanilla is None:
            raise FigureInputError(f"F13 lacks matched Vanilla row for {row.run_id}")
        aegis_bindings = _mapping(row.raw.get("bindings"), f"{row.run_id}.bindings")
        vanilla_bindings = _mapping(vanilla.raw.get("bindings"), f"{vanilla.run_id}.bindings")
        matched_keys = (
            "implementation_fingerprint",
            "workload_fingerprint",
            "protocol_fingerprint",
            "parameters_fingerprint",
            "context_bucket",
            "scenario",
            "seed",
            "failure_schedule_fingerprint",
            "failure_binding_fingerprint",
            "implementation_commit",
            "workload_sha256",
        )
        mismatched = [
            binding_key
            for binding_key in matched_keys
            if binding_key not in aegis_bindings
            or binding_key not in vanilla_bindings
            or aegis_bindings[binding_key] != vanilla_bindings[binding_key]
        ]
        if mismatched:
            raise FigureInputError(
                f"F13 pair {row.run_id}/{vanilla.run_id} is not matched at {mismatched}"
            )
        pairs.append((row, vanilla))
    if not pairs:
        raise FigureInputError("F13 requires matched unified-AegisKV and Vanilla rows")

    def peer(row: MatrixRow) -> int | float:
        return _metric_number(row, "resource_cost", "peer_hbm_byte_ns")

    def store(row: MatrixRow) -> int | float:
        return _metric_number(row, "resource_cost", "store_dram_byte_ns")

    def network(row: MatrixRow) -> int | float:
        return _sum_numeric_mapping_exact(row, "resource_cost", "network_byte_ns")

    def copy_busy(row: MatrixRow) -> int | float:
        return _sum_numeric_mapping_exact(row, "resource_cost", "copy_engine_busy_ns")

    def recompute(row: MatrixRow) -> int | float:
        return _metric_number(row, "recompute_tokens_after_failure")

    components = (
        ("Peer-HBM byte-ns", "byte-ns", peer, False),
        ("Store DRAM byte-ns", "byte-ns", store, False),
        ("network byte-time", "byte-ns", network, False),
        ("copy-engine busy", "ns", copy_busy, False),
        ("recompute avoided", "tokens", recompute, True),
    )
    canvas = _Canvas(
        spec.title,
        "Matched Vanilla deltas by unit; staging peak and recompute GPU time unavailable",
    )
    bindings: list[PointBinding] = []
    point_index = 0
    panel_positions = ((65, 125), (435, 125), (805, 125), (250, 390), (620, 390))
    panel_width = 330.0
    panel_height = 185.0
    for (label, unit, getter, reversed_delta), (left, top) in zip(
        components, panel_positions, strict=True
    ):
        samples: list[tuple[MatrixRow, MatrixRow, int | float, int | float, int | float]] = []
        for aegis, vanilla in pairs:
            aegis_value = getter(aegis)
            vanilla_value = getter(vanilla)
            delta = vanilla_value - aegis_value if reversed_delta else aegis_value - vanilla_value
            samples.append((aegis, vanilla, aegis_value, vanilla_value, delta))
        extent = max((abs(item[4]) for item in samples), default=1.0)
        extent = max(1.0, extent)
        baseline = top + panel_height / 2
        canvas.rect(
            left,
            top,
            panel_width,
            panel_height,
            fill="#f8fafc",
            stroke="#cbd5e1",
            radius=4,
        )
        canvas.line(left + 20, baseline, left + panel_width - 15, baseline, stroke="#64748b")
        canvas.text(
            left + panel_width / 2, top - 9, f"{label} Δ ({unit})", css="label", anchor="middle"
        )
        canvas.text(left + 16, top + 13, f"+{_compact(extent)}", anchor="start")
        canvas.text(left + 16, top + panel_height - 5, f"-{_compact(extent)}", anchor="start")
        step = (panel_width - 65) / len(samples)
        for sample_index, (
            row,
            vanilla_row,
            aegis_value,
            vanilla_value,
            delta,
        ) in enumerate(samples):
            x = left + 50 + step * (sample_index + 0.5)
            y = _scale(delta, -extent, extent, top + panel_height - 18, top + 18)
            binding = _point(
                row,
                spec.figure_id,
                point_index,
                component=label,
                unit=unit,
                context_bucket=row.context_bucket,
                vanilla_run_id=vanilla_row.run_id,
                vanilla_result_hash=vanilla_row.result_hash,
                aegiskv_absolute=aegis_value,
                vanilla_absolute=vanilla_value,
                delta_vs_vanilla=delta,
                delta_definition=(
                    "vanilla_minus_aegiskv" if reversed_delta else "aegiskv_minus_vanilla"
                ),
            )
            point_index += 1
            bindings.append(binding)
            group = canvas.group(binding)
            color = "#059669" if delta <= 0 and not reversed_delta else "#2563eb"
            if reversed_delta:
                color = "#059669" if delta >= 0 else "#dc2626"
            elif delta > 0:
                color = "#dc2626"
            canvas.line(x, baseline, x, y, stroke=color, width=5, parent=group)
            canvas.circle(x, y, 4, fill=color, parent=group)
            canvas.text(
                x,
                top + panel_height + 12,
                row.context_bucket,
                css="small",
                anchor="middle",
            )
    notes = (
        "minimum_seed_repeat_A_diagnostic_no_cross_seed_statistics_or_confidence_interval",
        "staging_peak_unavailable_in_canonical_E2_payload",
        "recompute_gpu_time_unavailable; tokens_avoided_reported_without_time_claim",
        "no_cross_unit_aggregation",
        "network_and_copy_cost_derive_from_terminal_transfer_ledger_with_byte_conservation",
        "AegisKV_and_Vanilla_absolute_values_are_bound_in_point_coordinates_and_sidecar",
        "dual_sources_are_in_coordinates_and_svg_data_vanilla_attributes",
    )
    return _RenderedFigure(canvas.serialize(), tuple(bindings), notes)


def _peak_mean(rows: Sequence[MatrixRow], spec: _FigureSpec) -> _RenderedFigure:
    selected = _minimum_seed_a([row for row in rows if row.suite == "core"])
    if not selected:
        raise FigureInputError("F14 requires core-suite rows")
    canvas = _Canvas(
        spec.title,
        "Occupancy only: peak vs mean; p95/utilization unavailable; imbalance is sidecar-only",
    )
    points: list[tuple[MatrixRow, float, float, str, str, float]] = []
    used_fallback = False
    for row in selected:
        end = max(1.0, _metric(row, "virtual_end_ns"))
        cost = _mapping(row.metrics.get("resource_cost"), f"{row.run_id}.resource_cost")
        resources: list[tuple[str, str, float, float]] = []
        peer_by_gpu = cost.get("peer_hbm_by_gpu")
        if isinstance(peer_by_gpu, Mapping) and peer_by_gpu:
            for resource_id, raw in sorted(peer_by_gpu.items()):
                record = _mapping(raw, f"{row.run_id}.peer_hbm_by_gpu.{resource_id}")
                resources.append(
                    (
                        "Peer-HBM",
                        str(resource_id),
                        _num(record.get("peak_bytes"), f"{resource_id}.peak_bytes"),
                        _num(record.get("byte_ns"), f"{resource_id}.byte_ns") / end,
                    )
                )
        else:
            used_fallback = True
            resources.append(
                (
                    "Peer-HBM",
                    "aggregate_pool",
                    _metric(row, "resource_cost", "peer_hbm_peak_bytes"),
                    _metric(row, "resource_cost", "peer_hbm_byte_ns") / end,
                )
            )
        store_by_segment = cost.get("store_dram_by_segment")
        if isinstance(store_by_segment, Mapping) and store_by_segment:
            for resource_id, raw in sorted(store_by_segment.items()):
                record = _mapping(raw, f"{row.run_id}.store_dram_by_segment.{resource_id}")
                resources.append(
                    (
                        "Store DRAM",
                        str(resource_id),
                        _num(record.get("peak_bytes"), f"{resource_id}.peak_bytes"),
                        _num(record.get("byte_ns"), f"{resource_id}.byte_ns") / end,
                    )
                )
        else:
            used_fallback = True
            resources.append(
                (
                    "Store DRAM",
                    "aggregate_pool",
                    _metric(row, "resource_cost", "store_dram_peak_bytes"),
                    _metric(row, "resource_cost", "store_dram_byte_ns") / end,
                )
            )
        for tier in ("Peer-HBM", "Store DRAM"):
            tier_resources = [item for item in resources if item[0] == tier]
            peaks = [item[2] for item in tier_resources]
            peak_mean = sum(peaks) / max(1, len(peaks))
            imbalance = (max(peaks) - min(peaks)) / max(1.0, peak_mean)
            for _tier, resource_id, peak, mean in tier_resources:
                points.append((row, peak, mean, tier, resource_id, imbalance))
    max_axis = max(max(peak, mean) for _row, peak, mean, _tier, _resource_id, _imbalance in points)
    _axes(
        canvas,
        x_label="time-weighted mean allocated bytes",
        y_label="event-boundary peak bytes",
        y_max=max_axis,
    )
    canvas.circle(390, 94, 5, fill="#2563eb")
    canvas.text(402, 99, "Peer-HBM", css="small")
    canvas.circle(500, 94, 5, fill="#d97706")
    canvas.text(512, 99, "Store DRAM", css="small")
    bindings: list[PointBinding] = []
    for index, (row, peak, mean, tier, resource_id, imbalance) in enumerate(points):
        x = _scale(mean, 0, max(1.0, max_axis), PLOT_LEFT, PLOT_RIGHT)
        y = _scale(peak, 0, max(1.0, max_axis), PLOT_BOTTOM, PLOT_TOP)
        binding = _point(
            row,
            spec.figure_id,
            index,
            tier=tier,
            resource_id=resource_id,
            mean_bytes=mean,
            peak_bytes=peak,
            tier_peak_imbalance_ratio=imbalance,
            p95_available=False,
        )
        bindings.append(binding)
        group = canvas.group(binding)
        canvas.circle(x, y, 4, fill="#2563eb" if tier == "Peer-HBM" else "#d97706", parent=group)
    canvas.line(PLOT_LEFT, PLOT_BOTTOM, PLOT_RIGHT, PLOT_TOP, stroke="#94a3b8", dash="6 5")
    return _RenderedFigure(
        canvas.serialize(),
        tuple(bindings),
        tuple(
            [
                "p95_occupancy_not_available_in_canonical_E2_payload",
                "minimum_seed_repeat_A_diagnostic_no_cross_seed_statistics_or_confidence_interval",
                "link_and_copy_utilization_not_available_in_this_figure",
                "imbalance_is_bound_in_point_coordinates_but_not_visually_encoded",
                "imbalance_is_range_over_mean_of_event_boundary_peaks",
            ]
            + (
                ["aggregate_pool_fallback_used_for_rows_without_per_resource_metrics"]
                if used_fallback
                else []
            )
        ),
    )


def _bucket_counts(rep: RepresentativeRun) -> dict[str, int]:
    if not rep.span_details:
        raise FigureInputError("F15 requires representative.span_details")
    counter: Counter[str] = Counter()
    for index, detail in enumerate(rep.span_details):
        bucket = detail.get("context_bucket")
        if bucket not in BUCKETS:
            raise FigureInputError(
                f"representative.span_details[{index}].context_bucket is invalid: {bucket!r}"
            )
        assert isinstance(bucket, str)
        counter[bucket] += 1
    if any(counter[bucket] <= 0 for bucket in BUCKETS):
        raise FigureInputError("F15 representative span details lack five-bucket coverage")
    return {bucket: counter[bucket] for bucket in BUCKETS}


def _trace_coverage(
    rep: RepresentativeRun,
    manifest: Mapping[str, Any],
    spec: _FigureSpec,
) -> _RenderedFigure:
    counts = _bucket_counts(rep)
    canvas = _Canvas(
        spec.title,
        "Five-bucket counts only; source hash-block-64; not target-tokenizer-equivalent",
    )
    _axes(
        canvas,
        x_label="single-span model context bucket",
        y_label="real trace spans",
        y_max=float(max(counts.values())),
        x_labels=BUCKETS,
    )
    bindings: list[PointBinding] = []
    artifact_hashes = _first_mapping(manifest.get("artifact_hashes"), manifest.get("artifacts"))
    provenance_artifact = (
        _first_mapping(artifact_hashes.get("provenance.json"))
        if artifact_hashes is not None
        else None
    )
    suite_provenance_sha256 = (
        _required_sha256(
            provenance_artifact,
            "sha256",
            "matrix_manifest.artifact_hashes.provenance.json",
        )
        if provenance_artifact is not None
        else None
    )
    row = rep.row
    row_bindings = _mapping(row.raw.get("bindings"), f"{row.run_id}.bindings")
    workload_sha256 = _required_sha256(row_bindings, "workload_sha256", f"{row.run_id}.bindings")
    workload_fingerprint = _required_sha256(
        row_bindings, "workload_fingerprint", f"{row.run_id}.bindings"
    )
    direct_manifest_sha256 = row_bindings.get("workload_manifest_sha256")
    manifest_coordinates: dict[str, Any]
    if direct_manifest_sha256 is not None:
        direct_manifest_sha256 = _required_sha256(
            row_bindings,
            "workload_manifest_sha256",
            f"{row.run_id}.bindings",
        )
        binding_note = "workload_manifest_sha256_is_directly_bound"
        manifest_coordinates = {
            "workload_manifest_binding": "direct",
            "workload_manifest_sha256": direct_manifest_sha256,
        }
    else:
        if suite_provenance_sha256 is None:
            raise FigureInputError(
                "F15 requires workload_manifest_sha256 or a matrix-manifest hash lock "
                "for suite provenance.json"
            )
        binding_note = (
            "workload_manifest_sha256_not_directly_available;matrix_manifest_declared_"
            "suite_provenance_hash_recorded_but_not_resolved"
        )
        manifest_coordinates = {
            "workload_manifest_binding": "not_directly_available",
            "matrix_manifest_declared_suite_provenance_sha256": suite_provenance_sha256,
        }
    step = (PLOT_RIGHT - PLOT_LEFT) / len(BUCKETS)
    for index, bucket in enumerate(BUCKETS):
        value = counts[bucket]
        x = PLOT_LEFT + step * index + step * 0.2
        width = step * 0.6
        y = _scale(float(value), 0, float(max(counts.values())), PLOT_BOTTOM, PLOT_TOP)
        binding = _point(
            row,
            spec.figure_id,
            index,
            bucket=bucket,
            real_trace_spans=value,
            count_source="representative.span_details",
            token_count_mode="source_hash_blocks_64",
            target_tokenizer_equivalence=False,
            workload_sha256=workload_sha256,
            workload_fingerprint=workload_fingerprint,
            **manifest_coordinates,
        )
        bindings.append(binding)
        group = canvas.group(binding)
        canvas.rect(x, y, width, PLOT_BOTTOM - y, fill=_COLORS[index], parent=group)
        canvas.text(x + width / 2, y - 8, str(value), anchor="middle", parent=group)
    return _RenderedFigure(
        canvas.serialize(),
        tuple(bindings),
        (
            "source_hash_blocks_64_are_not_target_tokenizer_equivalent_token_ids",
            "128k_is_one_model_context_not_workflow_aggregated_tokens",
            "counts_are_derived_only_from_representative_span_details_and_bind_the_representative_row",
            "dag_size_fan_in_fan_out_concurrency_and_resource_recovery_WCT_overlays_unavailable",
            binding_note,
        ),
    )


def _render_all(
    rows: Sequence[MatrixRow],
    representative: RepresentativeRun,
    manifest: Mapping[str, Any],
) -> dict[str, _RenderedFigure]:
    specs = {spec.figure_id: spec for spec in FIGURES}
    return {
        "F1": _architecture(representative, specs["F1"]),
        "F2": _failure_timeline(representative, specs["F2"]),
        "F3": _pool_timeline(
            representative,
            specs["F3"],
            key="peer_hbm_timeline",
            series_key="peer_hbm_timelines",
            color="#2563eb",
            subtitle=(
                "Peer protection committed/pending occupancy and failure-unavailable bytes"
            ),
            scope_note=(
                "peer_protection_pool_only_excludes_weights_runtime_primary_reusable_"
                "recovery_reserve_staging_fragmentation_and_free"
            ),
        ),
        "F4": _pool_timeline(
            representative,
            specs["F4"],
            key="store_dram_timeline",
            series_key="store_dram_timelines",
            color="#d97706",
            subtitle=(
                "Store committed and pending destination occupancy at event boundaries"
            ),
            scope_note=(
                "store_pool_tracks_committed_and_pending_but_excludes_evicting_staging_"
                "allocator_metadata_fragmentation_and_free"
            ),
        ),
        "F5": _migration_gantt(representative, specs["F5"]),
        "F6": _wct_goodput(rows, specs["F6"]),
        "F7": _recovery_cdf(rows, specs["F7"]),
        "F8": _coverage_recompute(rows, specs["F8"]),
        "F9": _ablation(rows, specs["F9"]),
        "F10": _budget_sensitivity(rows, specs["F10"]),
        "F11": _scale_sensitivity(rows, specs["F11"]),
        "F13": _resource_cost(rows, specs["F13"]),
        "F14": _peak_mean(rows, specs["F14"]),
        "F15": _trace_coverage(representative, manifest, specs["F15"]),
    }


def _provenance(
    *,
    spec: _FigureSpec,
    rendered: _RenderedFigure,
    svg_sha256: str,
    results_path: Path,
    results_sha256: str,
    manifest_path: Path,
    manifest_sha256: str,
    representative_path: Path,
    representative_sha256: str,
    renderer_source_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "moonkvsim.aegiskv.figure_provenance.v1",
        "figure_id": spec.figure_id,
        "title": spec.title,
        "generator": GENERATOR_VERSION,
        "svg": {"file": f"{spec.stem}.svg", "sha256": svg_sha256},
        "inputs": {
            "matrix_results": {"file": results_path.name, "sha256": results_sha256},
            "matrix_manifest": {"file": manifest_path.name, "sha256": manifest_sha256},
            "representative_run": {
                "file": representative_path.name,
                "sha256": representative_sha256,
            },
        },
        "evidence": dict(FIGURE_EVIDENCE),
        "point_bindings": [binding.to_dict() for binding in rendered.bindings],
        "notes": [*rendered.notes, f"renderer_source_sha256={renderer_source_sha256}"],
    }


def _f12_exclusion(
    *,
    results_path: Path,
    results_sha256: str,
    manifest_path: Path,
    manifest_sha256: str,
    representative_path: Path,
    representative_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "moonkvsim.aegiskv.figure_exclusion.v1",
        "figure_id": "F12",
        "status": "EXCLUDED",
        "svg_generated": False,
        "reason": "simulator accuracy requires observed-vs-predicted E3/E4 evidence",
        "required_evidence": ["E3 modeled_with_physical_calibration", "E4 physical_baseline"],
        "current_evidence": "E2 modeled/preliminary; not calibrated; no physical experiment",
        "evidence": dict(FIGURE_EVIDENCE),
        "paper_ready": False,
        "inputs": {
            "matrix_results": {"file": results_path.name, "sha256": results_sha256},
            "matrix_manifest": {"file": manifest_path.name, "sha256": manifest_sha256},
            "representative_run": {
                "file": representative_path.name,
                "sha256": representative_sha256,
            },
        },
    }


def _figure_set_manifest(
    *,
    figure_entries: Sequence[Mapping[str, Any]],
    f12_file: str,
    f12_sha256: str,
    results_path: Path,
    results_sha256: str,
    matrix_manifest_path: Path,
    matrix_manifest_sha256: str,
    representative_path: Path,
    representative_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "moonkvsim.aegiskv.figure_set_manifest.v1",
        "status": "PASS",
        "generator": GENERATOR_VERSION,
        "canonical_json": True,
        "evidence": dict(FIGURE_EVIDENCE),
        "evidence_footer": EVIDENCE_FOOTER,
        "inputs": {
            "matrix_results": {"file": results_path.name, "sha256": results_sha256},
            "matrix_manifest": {
                "file": matrix_manifest_path.name,
                "sha256": matrix_manifest_sha256,
            },
            "representative_run": {
                "file": representative_path.name,
                "sha256": representative_sha256,
            },
        },
        "required_svg_figure_ids": [spec.figure_id for spec in FIGURES],
        "excluded_figure_ids": ["F12"],
        "figures": list(figure_entries),
        "exclusions": [
            {
                "figure_id": "F12",
                "file": f12_file,
                "sha256": f12_sha256,
                "svg_generated": False,
            }
        ],
        "generated_artifact_count": len(figure_entries) * 2 + 1,
        "point_binding_contract": {
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
        "paper_ready": False,
    }


def _expected_output_names() -> frozenset[str]:
    names = {
        name for spec in FIGURES for name in (f"{spec.stem}.svg", f"{spec.stem}.provenance.json")
    }
    names.update({f"{F12_STEM}.excluded.json", "manifest.json"})
    return frozenset(names)


def _preflight_output_dir(
    output_dir: Path,
    *,
    expected_names: frozenset[str],
    overwrite: bool,
) -> None:
    if output_dir.is_symlink():
        raise ExistingFigureError(f"refusing symlink output directory: {output_dir}")
    if not output_dir.exists():
        return
    if not output_dir.is_dir():
        raise ExistingFigureError(f"refusing non-directory output target: {output_dir}")
    entries = sorted(output_dir.iterdir(), key=lambda path: path.name)
    unsafe = [
        path.name
        for path in entries
        if path.is_symlink() or path.name not in expected_names or not path.is_file()
    ]
    if unsafe:
        raise ExistingFigureError(
            "refusing output directory with unexpected or non-regular entries: " + ", ".join(unsafe)
        )
    if entries and not overwrite:
        raise ExistingFigureError(
            "refusing to overwrite existing figure targets: "
            + ", ".join(path.name for path in entries)
        )


def _publish_bundle(
    *,
    output_dir: Path,
    files: Mapping[str, bytes],
    overwrite: bool,
) -> None:
    expected_names = _expected_output_names()
    if frozenset(files) != expected_names:
        missing = sorted(expected_names - set(files))
        extra = sorted(set(files) - expected_names)
        raise FigureInputError(f"internal figure bundle mismatch: missing={missing}, extra={extra}")
    _preflight_output_dir(
        output_dir,
        expected_names=expected_names,
        overwrite=overwrite,
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent)
    )
    backup_dir: Path | None = None
    published = False
    try:
        for name in sorted(expected_names - {"manifest.json"}):
            (staging_dir / name).write_bytes(files[name])
        # The set manifest is the commit record and is deliberately written last.
        (staging_dir / "manifest.json").write_bytes(files["manifest.json"])
        _preflight_output_dir(
            output_dir,
            expected_names=expected_names,
            overwrite=overwrite,
        )
        if output_dir.exists():
            backup_dir = Path(
                tempfile.mkdtemp(prefix=f".{output_dir.name}.backup-", dir=output_dir.parent)
            )
            backup_dir.rmdir()
            os.replace(output_dir, backup_dir)
            try:
                os.replace(staging_dir, output_dir)
            except OSError:
                os.replace(backup_dir, output_dir)
                backup_dir = None
                raise
        else:
            os.replace(staging_dir, output_dir)
        published = True
    except OSError as error:
        raise FigureInputError(f"cannot publish figure bundle to {output_dir}: {error}") from error
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        if published and backup_dir is not None and backup_dir.exists():
            shutil.rmtree(backup_dir)


def generate_e2_figures(
    *,
    results_path: Path,
    manifest_path: Path,
    representative_path: Path,
    output_dir: Path,
    overwrite: bool = False,
) -> FigureSetResult:
    """Generate the declared limited-E2 SVG set and provenance sidecars.

    Existing target files fail closed unless ``overwrite=True`` is explicitly
    provided.  F12 is represented only by an exclusion sidecar.
    """

    results_bytes = _read_input_bytes(results_path)
    manifest_bytes = _read_input_bytes(manifest_path)
    representative_bytes = _read_input_bytes(representative_path)
    renderer_source_bytes = _read_input_bytes(Path(__file__))
    results_sha256 = hashlib.sha256(results_bytes).hexdigest()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    representative_sha256 = hashlib.sha256(representative_bytes).hexdigest()
    renderer_source_sha256 = hashlib.sha256(renderer_source_bytes).hexdigest()
    raw_rows = _load_jsonl_bytes(results_bytes, results_path)
    rows = tuple(_parse_matrix_row(raw) for raw in raw_rows)
    if len({row.run_id for row in rows}) != len(rows):
        raise FigureInputError("matrix results contain duplicate run_id values")
    manifest = _load_json_bytes(manifest_bytes, manifest_path)
    _validate_matrix_completeness(rows, manifest)
    _validate_manifest_bindings(
        manifest,
        results_sha256=results_sha256,
        results_size_bytes=len(results_bytes),
        rows=rows,
    )
    _validate_manifest_artifact(
        manifest,
        name="representative-run.json",
        sha256=representative_sha256,
        size_bytes=len(representative_bytes),
    )
    representative_raw = _load_json_bytes(representative_bytes, representative_path)
    rows_by_run = {row.run_id: row for row in rows}
    representative = _parse_representative(representative_raw, rows_by_run)
    rendered = _render_all(rows, representative, manifest)

    f12_path = output_dir / f"{F12_STEM}.excluded.json"
    set_manifest_path = output_dir / "manifest.json"

    artifacts: list[FigureArtifact] = []
    figure_entries: list[dict[str, Any]] = []
    output_files: dict[str, bytes] = {}
    for spec in FIGURES:
        product = rendered[spec.figure_id]
        svg_path = output_dir / f"{spec.stem}.svg"
        provenance_path = output_dir / f"{spec.stem}.provenance.json"
        svg_bytes = product.svg.encode("utf-8")
        svg_hash = hashlib.sha256(svg_bytes).hexdigest()
        provenance = _provenance(
            spec=spec,
            rendered=product,
            svg_sha256=svg_hash,
            results_path=results_path,
            results_sha256=results_sha256,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            representative_path=representative_path,
            representative_sha256=representative_sha256,
            renderer_source_sha256=renderer_source_sha256,
        )
        provenance_bytes = _canonical_json(provenance).encode("utf-8")
        output_files[svg_path.name] = svg_bytes
        output_files[provenance_path.name] = provenance_bytes
        figure_entries.append(
            {
                "figure_id": spec.figure_id,
                "svg": {"file": svg_path.name, "sha256": svg_hash},
                "provenance": {
                    "file": provenance_path.name,
                    "sha256": hashlib.sha256(provenance_bytes).hexdigest(),
                },
                "point_count": len(product.bindings),
            }
        )
        artifacts.append(FigureArtifact(spec.figure_id, spec.title, svg_path, provenance_path))
    f12_bytes = _canonical_json(
        _f12_exclusion(
            results_path=results_path,
            results_sha256=results_sha256,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            representative_path=representative_path,
            representative_sha256=representative_sha256,
        )
    ).encode("utf-8")
    output_files[f12_path.name] = f12_bytes
    output_files[set_manifest_path.name] = _canonical_json(
        _figure_set_manifest(
            figure_entries=figure_entries,
            f12_file=f12_path.name,
            f12_sha256=hashlib.sha256(f12_bytes).hexdigest(),
            results_path=results_path,
            results_sha256=results_sha256,
            matrix_manifest_path=manifest_path,
            matrix_manifest_sha256=manifest_sha256,
            representative_path=representative_path,
            representative_sha256=representative_sha256,
        )
    ).encode("utf-8")
    _publish_bundle(
        output_dir=output_dir,
        files=output_files,
        overwrite=overwrite,
    )
    artifacts.append(FigureArtifact("F12", "Simulator accuracy", None, f12_path))
    return FigureSetResult(
        artifacts=tuple(artifacts),
        manifest_path=set_manifest_path,
        results_sha256=results_sha256,
        manifest_sha256=manifest_sha256,
        representative_sha256=representative_sha256,
    )


__all__ = [
    "EVIDENCE_FOOTER",
    "FIGURES",
    "FIGURE_EVIDENCE",
    "ExistingFigureError",
    "FigureArtifact",
    "FigureInputError",
    "FigureSetResult",
    "generate_e2_figures",
]
