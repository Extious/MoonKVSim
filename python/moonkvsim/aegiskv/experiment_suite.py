"""Canonical E2-only orchestration for the matched AegisKV GlobalDES study.

The orchestrator has no physical execution path.  A worker loads the frozen
metadata workload once and every repetition constructs a fresh ``GlobalDES``
through :func:`run_study_cell`.  Publication is fail-closed: every expected
cross-product cell and every A/B hash comparison must pass before an output
directory is atomically installed.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast

from moonkvsim.aegiskv.experiment import (
    CellSpec,
    ExperimentVariant,
    FailureSchedule,
    Scenario,
    StudyRunResult,
    ablation_variants,
    core_variants,
    derive_failure_schedule,
    qwen3_8b_dp_deployment,
    qwen3_8b_dp_only_contract,
    run_study_cell,
    sensitivity_variants,
)
from moonkvsim.aegiskv.experiment_statistics import build_statistics
from moonkvsim.aegiskv.experiment_workload import (
    CONTEXT_BUCKETS,
    load_experiment_records,
)
from moonkvsim.common.hash import sha256_json

SuiteSelection = Literal["core", "all"]

SCHEMA_VERSION: Final = "moonkvsim.aegiskv.e2_matrix_suite.v1"
DEFAULT_SEEDS: Final = (0, 1, 2)
REPETITIONS: Final = ("A", "B")
CONTEXT_BUCKET_NAMES: Final = tuple(bucket.name for bucket in CONTEXT_BUCKETS)
SCENARIOS: Final = (Scenario.NO_FAILURE, Scenario.GPU_FAILURE)
EVIDENCE_BOUNDARY: Final[dict[str, Any]] = {
    "class": "E2",
    "scope": "modeled/preliminary",
    "calibration": "not_calibrated",
    "physical_execution": False,
    "physical_timing_claim_allowed": False,
    "formal_use_allowed": False,
    "paper_ready": False,
    "slurm_used": False,
}
EXPECTED_VARIANT_IDS: Final[dict[str, tuple[str, ...]]] = {
    "core": (
        "recompute_only",
        "vanilla_mooncake_dram",
        "static_peer_hbm",
        "aegiskv_dram_only",
        "aegiskv_peer_only",
        "aegiskv_hbm_dram",
        "aegiskv_unified",
    ),
    "ablation": (
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
    ),
    "sensitivity": tuple(
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
    ),
}
DEFAULT_EXPECTED_ROWS: Final = {
    "core": 420,
    "ablation": 720,
    "sensitivity": 1_620,
    "all": 2_760,
}
NO_FAILURE_SCHEDULE_FINGERPRINT: Final = sha256_json(
    {"scenario": Scenario.NO_FAILURE.value, "failure_schedule": None}
)
_HEX_40 = re.compile(r"[0-9a-f]{40}\Z")


class ExperimentSuiteError(RuntimeError):
    """The suite protocol, execution, or publication failed closed."""


@dataclass(frozen=True, slots=True)
class ImplementationBinding:
    """Clean Git implementation identity used by every result row."""

    commit: str
    tree: str
    worktree_clean: bool

    def __post_init__(self) -> None:
        if _HEX_40.fullmatch(self.commit) is None:
            raise ValueError("implementation commit must be a lowercase 40-hex Git object")
        if _HEX_40.fullmatch(self.tree) is None:
            raise ValueError("implementation tree must be a lowercase 40-hex Git object")
        if not self.worktree_clean:
            raise ValueError("E2 matrix publication requires a clean implementation worktree")

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "tree": self.tree,
            "worktree_clean": self.worktree_clean,
            "source_frozen": True,
        }


@dataclass(frozen=True, slots=True)
class WorkloadBinding:
    """Content identity and provenance identity of the frozen workload."""

    declared_path: str
    sha256: str
    record_count: int
    semantic_fingerprint: str
    manifest_sha256: str
    manifest_schema: str

    def __post_init__(self) -> None:
        for name, value in (
            ("sha256", self.sha256),
            ("semantic_fingerprint", self.semantic_fingerprint),
            ("manifest_sha256", self.manifest_sha256),
        ):
            if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError(f"workload {name} must be lowercase 64-hex")
        if not self.declared_path or not self.manifest_schema or self.record_count <= 0:
            raise ValueError("workload binding fields must be non-empty and positive")

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "declared_path": self.declared_path,
            "sha256": self.sha256,
            "record_count": self.record_count,
            "semantic_fingerprint": self.semantic_fingerprint,
            "manifest_sha256": self.manifest_sha256,
            "manifest_schema": self.manifest_schema,
        }


@dataclass(frozen=True, slots=True)
class _ScheduleTask:
    parameters_fingerprint: str
    variant: ExperimentVariant
    context_bucket: str
    seed: int

    @property
    def key(self) -> str:
        return sha256_json(
            {
                "parameters_fingerprint": self.parameters_fingerprint,
                "context_bucket": self.context_bucket,
                "seed": self.seed,
            }
        )


@dataclass(frozen=True, slots=True)
class _FrozenSchedule:
    key: str
    parameters_fingerprint: str
    context_bucket: str
    seed: int
    schedule: FailureSchedule

    @property
    def binding_fingerprint(self) -> str:
        return sha256_json(
            {
                "parameters_fingerprint": self.parameters_fingerprint,
                "failure_schedule_fingerprint": self.schedule.fingerprint,
            }
        )


@dataclass(frozen=True, slots=True)
class _PairTask:
    variant: ExperimentVariant
    context_bucket: str
    scenario: Scenario
    seed: int
    failure_schedule: FailureSchedule | None
    failure_binding_fingerprint: str
    implementation: ImplementationBinding
    workload: WorkloadBinding
    protocol_fingerprint: str
    capture_representative: bool = False


@dataclass(frozen=True, slots=True)
class PairExecution:
    """Two canonical rows and their strict fresh-run comparison."""

    rows: tuple[dict[str, Any], dict[str, Any]]
    audit: dict[str, Any]
    representative: dict[str, Any] | None


_WORKER_RECORDS: Sequence[Mapping[str, Any]] | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Mapping[str, Any] | Sequence[Any]) -> bytes:
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


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExperimentSuiteError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ExperimentSuiteError(f"JSON document is not a string-keyed object: {path}")
    return cast(dict[str, Any], value)


def load_frozen_workload(
    workload_path: Path,
    manifest_path: Path,
) -> tuple[list[dict[str, Any]], WorkloadBinding, dict[str, Any]]:
    """Load the committed workload and fail closed on any provenance drift."""

    if not workload_path.is_file() or not manifest_path.is_file():
        raise ExperimentSuiteError("frozen workload and manifest must both exist")
    manifest = _read_json_object(manifest_path)
    if manifest.get("schema") != "moonkvsim.aegiskv.experiment_workload_manifest.v1":
        raise ExperimentSuiteError("unexpected frozen workload manifest schema")
    if manifest.get("status") != "pass":
        raise ExperimentSuiteError("frozen workload manifest is not passing")
    expected_evidence = {
        "class": "E2",
        "scope": "modeled/preliminary",
        "calibration": "not_calibrated",
        "physical_execution": False,
        "paper_ready": False,
    }
    if manifest.get("evidence") != expected_evidence:
        raise ExperimentSuiteError("frozen workload evidence boundary drifted")
    artifact = manifest.get("artifact")
    selection = manifest.get("selection")
    if not isinstance(artifact, dict) or not isinstance(selection, dict):
        raise ExperimentSuiteError("frozen workload manifest lacks artifact or selection")
    audit = selection.get("audit")
    if not isinstance(audit, dict):
        raise ExperimentSuiteError("frozen workload selection lacks an audit")
    required_true = (
        "no_span_slicing",
        "no_cross_workflow_concatenation",
        "no_truncation",
        "no_padding",
        "no_synthesis",
    )
    if any(selection.get(field) is not True for field in required_true):
        raise ExperimentSuiteError("frozen workload permits mutation or synthesis")
    bucket_counts = audit.get("context_bucket_counts")
    if not isinstance(bucket_counts, dict) or any(
        type(bucket_counts.get(bucket)) is not int or int(bucket_counts[bucket]) <= 0
        for bucket in CONTEXT_BUCKET_NAMES
    ):
        raise ExperimentSuiteError("frozen workload does not cover every context bucket")

    workload_sha256 = _sha256_file(workload_path)
    declared_sha256 = artifact.get("sha256")
    if declared_sha256 != workload_sha256:
        raise ExperimentSuiteError("frozen workload SHA-256 differs from its manifest")
    records = load_experiment_records(workload_path)
    record_count = artifact.get("record_count")
    if type(record_count) is not int or record_count != len(records):
        raise ExperimentSuiteError("frozen workload record count differs from its manifest")
    semantic_fingerprint = artifact.get("semantic_fingerprint")
    if not isinstance(semantic_fingerprint, str):
        raise ExperimentSuiteError("frozen workload semantic fingerprint is missing")
    declared_path = artifact.get("path")
    if not isinstance(declared_path, str):
        raise ExperimentSuiteError("frozen workload declared path is missing")
    binding = WorkloadBinding(
        declared_path=declared_path,
        sha256=workload_sha256,
        record_count=len(records),
        semantic_fingerprint=semantic_fingerprint,
        manifest_sha256=_sha256_file(manifest_path),
        manifest_schema=str(manifest["schema"]),
    )
    return records, binding, manifest


def _variants_for(suite_name: str) -> tuple[ExperimentVariant, ...]:
    if suite_name == "core":
        variants = core_variants()
    elif suite_name == "ablation":
        variants = ablation_variants()
    elif suite_name == "sensitivity":
        variants = sensitivity_variants()
    else:
        raise ExperimentSuiteError(f"unknown suite: {suite_name}")
    actual_ids = tuple(variant.variant_id for variant in variants)
    if actual_ids != EXPECTED_VARIANT_IDS[suite_name]:
        raise ExperimentSuiteError(
            f"{suite_name} variants drifted: {actual_ids} != {EXPECTED_VARIANT_IDS[suite_name]}"
        )
    if any(variant.suite != suite_name for variant in variants):
        raise ExperimentSuiteError(f"{suite_name} returned a variant with the wrong suite")
    fingerprints = {variant.fingerprint for variant in variants}
    if len(fingerprints) != len(variants):
        raise ExperimentSuiteError(f"{suite_name} variant fingerprints are not unique")
    return variants


def selected_variants(selection: SuiteSelection) -> tuple[ExperimentVariant, ...]:
    """Return the exact variant catalog selected by ``core`` or ``all``."""

    if selection == "core":
        return _variants_for("core")
    if selection == "all":
        return (
            *_variants_for("core"),
            *_variants_for("ablation"),
            *_variants_for("sensitivity"),
        )
    raise ExperimentSuiteError(f"unknown suite selection: {selection}")


def normalize_seeds(seeds: Sequence[int]) -> tuple[int, ...]:
    """Validate repeated ``--seed`` values and return canonical ascending order."""

    if not seeds:
        raise ExperimentSuiteError("at least one seed is required")
    if any(type(seed) is not int or seed < 0 for seed in seeds):
        raise ExperimentSuiteError("seeds must be non-negative integers")
    if len(set(seeds)) != len(seeds):
        raise ExperimentSuiteError("duplicate seed values are forbidden")
    return tuple(sorted(seeds))


def build_protocol(selection: SuiteSelection, seeds: Sequence[int]) -> dict[str, Any]:
    """Materialize the explicit matrix protocol and its expected cross products."""

    canonical_seeds = normalize_seeds(seeds)
    catalog: dict[str, Any] = {}
    for suite_name in ("core", "ablation", "sensitivity"):
        variant_ids = EXPECTED_VARIANT_IDS[suite_name]
        default_pairs = len(variant_ids) * len(CONTEXT_BUCKET_NAMES) * len(SCENARIOS) * 3
        default_rows = default_pairs * len(REPETITIONS)
        catalog[suite_name] = {
            "variant_ids": list(variant_ids),
            "variant_count": len(variant_ids),
            "cross_product": [
                "variant_id",
                "context_bucket",
                "scenario",
                "seed",
                "repetition",
            ],
            "default_seed_count": 3,
            "default_expected_pair_count": default_pairs,
            "default_expected_row_count": default_rows,
        }
    included = ["core"] if selection == "core" else ["core", "ablation", "sensitivity"]
    execution_suites: dict[str, Any] = {}
    expected_pairs = 0
    expected_rows = 0
    for suite_name in included:
        variant_count = len(EXPECTED_VARIANT_IDS[suite_name])
        pair_count = (
            variant_count * len(CONTEXT_BUCKET_NAMES) * len(SCENARIOS) * len(canonical_seeds)
        )
        row_count = pair_count * len(REPETITIONS)
        expected_pairs += pair_count
        expected_rows += row_count
        execution_suites[suite_name] = {
            "variant_ids": list(EXPECTED_VARIANT_IDS[suite_name]),
            "expected_pair_count": pair_count,
            "expected_row_count": row_count,
        }
    protocol: dict[str, Any] = {
        "schema": f"{SCHEMA_VERSION}.protocol",
        "status": "PASS",
        "evidence": EVIDENCE_BOUNDARY,
        "model_deployment_contract": qwen3_8b_dp_only_contract(),
        "global_clock": "single_global_virtual_clock",
        "failure_types": ["GPU_FAILURE"],
        "physical_or_slurm_path": False,
        "suite_catalog": catalog,
        "default_contract": {
            "seeds": list(DEFAULT_SEEDS),
            "core_expected_rows": DEFAULT_EXPECTED_ROWS["core"],
            "ablation_expected_rows": DEFAULT_EXPECTED_ROWS["ablation"],
            "sensitivity_expected_rows": DEFAULT_EXPECTED_ROWS["sensitivity"],
            "all_expected_rows": DEFAULT_EXPECTED_ROWS["all"],
        },
        "execution": {
            "selection": selection,
            "included_suites": included,
            "context_buckets": list(CONTEXT_BUCKET_NAMES),
            "scenarios": [scenario.value for scenario in SCENARIOS],
            "seeds": list(canonical_seeds),
            "repetitions": list(REPETITIONS),
            "suites": execution_suites,
            "expected_pair_count": expected_pairs,
            "expected_row_count": expected_rows,
            "silent_fallback_allowed": False,
            "fresh_global_des_per_repetition": True,
            "required_pair_hashes": ["payload_sha256", "journal_sha256"],
        },
    }
    protocol["fingerprint"] = sha256_json(protocol)
    return protocol


def _parameter_fingerprint(variant: ExperimentVariant) -> str:
    return sha256_json(variant.parameters.to_dict())


def _schedule_tasks(
    variants: Sequence[ExperimentVariant], seeds: Sequence[int]
) -> tuple[_ScheduleTask, ...]:
    representative_by_parameters: dict[str, ExperimentVariant] = {}
    for variant in variants:
        representative_by_parameters.setdefault(_parameter_fingerprint(variant), variant)
    return tuple(
        _ScheduleTask(parameter_fp, representative, bucket, seed)
        for parameter_fp, representative in sorted(representative_by_parameters.items())
        for seed in seeds
        for bucket in CONTEXT_BUCKET_NAMES
    )


def _derive_one_schedule(
    records: Sequence[Mapping[str, Any]], task: _ScheduleTask
) -> _FrozenSchedule:
    schedule = derive_failure_schedule(
        records,
        bucket=task.context_bucket,
        seed=task.seed,
        parameters=task.variant.parameters,
    )
    if schedule.bucket != task.context_bucket or schedule.seed != task.seed:
        raise ExperimentSuiteError("derived failure schedule lost its bucket or seed binding")
    return _FrozenSchedule(
        key=task.key,
        parameters_fingerprint=task.parameters_fingerprint,
        context_bucket=task.context_bucket,
        seed=task.seed,
        schedule=schedule,
    )


def _worker_initialize(
    workload_path: str, expected_sha256: str, expected_record_count: int
) -> None:
    global _WORKER_RECORDS
    path = Path(workload_path)
    if _sha256_file(path) != expected_sha256:
        raise ExperimentSuiteError("worker observed frozen workload content drift")
    records = load_experiment_records(path)
    if len(records) != expected_record_count:
        raise ExperimentSuiteError("worker observed frozen workload record-count drift")
    _WORKER_RECORDS = records


def _worker_records() -> Sequence[Mapping[str, Any]]:
    if _WORKER_RECORDS is None:
        raise ExperimentSuiteError("process worker did not load the frozen workload")
    return _WORKER_RECORDS


def _worker_derive_schedule(task: _ScheduleTask) -> _FrozenSchedule:
    return _derive_one_schedule(_worker_records(), task)


def _worker_execute_pair(task: _PairTask) -> PairExecution:
    return _execute_pair(_worker_records(), task)


def _validate_result(result: StudyRunResult, spec: CellSpec) -> None:
    payload = result.payload
    if result.payload_sha256 != sha256_json(payload):
        raise ExperimentSuiteError(f"payload hash drifted for {spec.run_id}")
    if re.fullmatch(r"[0-9a-f]{64}", result.journal_sha256) is None:
        raise ExperimentSuiteError(f"journal hash is malformed for {spec.run_id}")
    if payload.get("status") != "PASS" or payload.get("evidence") != {
        key: EVIDENCE_BOUNDARY[key]
        for key in (
            "class",
            "scope",
            "calibration",
            "physical_execution",
            "physical_timing_claim_allowed",
            "formal_use_allowed",
            "paper_ready",
        )
    }:
        raise ExperimentSuiteError(f"result evidence boundary failed for {spec.run_id}")
    if payload.get("variant_fingerprint") != spec.variant.fingerprint:
        raise ExperimentSuiteError(f"variant fingerprint drifted for {spec.run_id}")
    expected_deployment = qwen3_8b_dp_deployment(spec.variant.parameters.dp_count)
    if payload.get("model_deployment") != expected_deployment:
        raise ExperimentSuiteError(f"model/deployment scope drifted for {spec.run_id}")
    if payload.get("context_bucket") != spec.context_bucket:
        raise ExperimentSuiteError(f"context bucket drifted for {spec.run_id}")
    if payload.get("scenario") != spec.scenario.value:
        raise ExperimentSuiteError(f"scenario drifted for {spec.run_id}")
    expected_schedule = None if spec.failure_schedule is None else spec.failure_schedule.to_dict()
    if payload.get("failure_schedule") != expected_schedule:
        raise ExperimentSuiteError(f"failure schedule drifted for {spec.run_id}")
    clock = payload.get("global_clock")
    if not isinstance(clock, dict) or clock.get("kind") != "single_global_virtual_clock":
        raise ExperimentSuiteError(f"result did not use the global virtual clock: {spec.run_id}")
    forbidden = payload.get("forbidden_semantics")
    if not isinstance(forbidden, dict) or any(value != 0 for value in forbidden.values()):
        raise ExperimentSuiteError(f"forbidden semantics occurred for {spec.run_id}")
    output_audit = payload.get("output_audit")
    if not isinstance(output_audit, dict) or any(
        output_audit.get(field) != 0
        for field in ("duplicate_or_missing_tokens", "stale_route_output_count")
    ):
        raise ExperimentSuiteError(f"output audit failed for {spec.run_id}")


def _row_for(
    spec: CellSpec,
    result: StudyRunResult,
    task: _PairTask,
) -> dict[str, Any]:
    parameter_fingerprint = _parameter_fingerprint(spec.variant)
    schedule_fingerprint = (
        NO_FAILURE_SCHEDULE_FINGERPRINT
        if spec.failure_schedule is None
        else spec.failure_schedule.fingerprint
    )
    matched_input = {
        "implementation_fingerprint": task.implementation.fingerprint,
        "workload_fingerprint": task.workload.fingerprint,
        "protocol_fingerprint": task.protocol_fingerprint,
        "variant_fingerprint": spec.variant.fingerprint,
        "parameters_fingerprint": parameter_fingerprint,
        "context_bucket": spec.context_bucket,
        "scenario": spec.scenario.value,
        "seed": spec.seed,
        "failure_schedule_fingerprint": schedule_fingerprint,
        "failure_binding_fingerprint": task.failure_binding_fingerprint,
    }
    matched_input_fingerprint = sha256_json(matched_input)
    cell_fingerprint = sha256_json(
        {
            "matched_input_fingerprint": matched_input_fingerprint,
            "repetition": spec.repetition,
        }
    )
    return {
        "schema": f"{SCHEMA_VERSION}.result_row",
        "status": "PASS",
        "run_id": spec.run_id,
        "pair_id": spec.pair_id,
        "suite": spec.variant.suite,
        "variant_id": spec.variant.variant_id,
        "variant_config": spec.variant.to_dict(),
        "context_bucket": spec.context_bucket,
        "scenario": spec.scenario.value,
        "seed": spec.seed,
        "repetition": spec.repetition,
        "fresh_global_des_instance": True,
        "evidence": EVIDENCE_BOUNDARY,
        "model_deployment": qwen3_8b_dp_deployment(spec.variant.parameters.dp_count),
        "bindings": {
            **matched_input,
            "matched_input_fingerprint": matched_input_fingerprint,
            "cell_fingerprint": cell_fingerprint,
            "implementation_commit": task.implementation.commit,
            "workload_sha256": task.workload.sha256,
        },
        "payload_sha256": result.payload_sha256,
        "journal_sha256": result.journal_sha256,
        "payload": result.payload,
    }


def _execute_pair(records: Sequence[Mapping[str, Any]], task: _PairTask) -> PairExecution:
    expected_has_failure = task.scenario is Scenario.GPU_FAILURE
    if expected_has_failure != (task.failure_schedule is not None):
        raise ExperimentSuiteError("pair has an inconsistent scenario and failure schedule")
    results: list[tuple[CellSpec, StudyRunResult]] = []
    for repetition in REPETITIONS:
        spec = CellSpec(
            variant=task.variant,
            context_bucket=task.context_bucket,
            scenario=task.scenario,
            seed=task.seed,
            repetition=repetition,
            failure_schedule=task.failure_schedule,
        )
        result = run_study_cell(records, spec)
        _validate_result(result, spec)
        results.append((spec, result))
    (spec_a, result_a), (spec_b, result_b) = results
    payload_match = result_a.payload_sha256 == result_b.payload_sha256
    journal_match = result_a.journal_sha256 == result_b.journal_sha256
    if not payload_match or not journal_match:
        raise ExperimentSuiteError(
            f"fresh-run A/B mismatch for {spec_a.pair_id}: "
            f"payload={payload_match}, journal={journal_match}"
        )
    rows = (
        _row_for(spec_a, result_a, task),
        _row_for(spec_b, result_b, task),
    )
    if (
        rows[0]["bindings"]["matched_input_fingerprint"]
        != rows[1]["bindings"]["matched_input_fingerprint"]
    ):
        raise ExperimentSuiteError(f"A/B inputs differ for {spec_a.pair_id}")
    audit: dict[str, Any] = {
        "schema": f"{SCHEMA_VERSION}.pair_audit",
        "status": "PASS",
        "pair_id": spec_a.pair_id,
        "run_ids": [spec_a.run_id, spec_b.run_id],
        "fresh_global_des_instances": 2,
        "same_process_allowed": True,
        "payload_sha256": result_a.payload_sha256,
        "journal_sha256": result_a.journal_sha256,
        "payload_sha256_exact_match": True,
        "journal_sha256_exact_match": True,
        "matched_input_fingerprint": rows[0]["bindings"]["matched_input_fingerprint"],
        "evidence": EVIDENCE_BOUNDARY,
    }
    representative: dict[str, Any] | None = None
    if task.capture_representative:
        representative = {
            "schema": f"{SCHEMA_VERSION}.representative_run",
            "status": "PASS",
            "run_id": spec_a.run_id,
            "payload_sha256": result_a.payload_sha256,
            "journal_sha256": result_a.journal_sha256,
            "evidence": EVIDENCE_BOUNDARY,
            "bindings": rows[0]["bindings"],
            "variant_config": task.variant.to_dict(),
            "payload": result_a.payload,
            "representative": result_a.representative,
            "span_details": list(result_a.span_details),
        }
    return PairExecution(rows=rows, audit=audit, representative=representative)


def execute_fresh_pair(
    records: Sequence[Mapping[str, Any]],
    *,
    variant: ExperimentVariant,
    context_bucket: str,
    scenario: Scenario,
    seed: int,
    failure_schedule: FailureSchedule | None,
    failure_binding_fingerprint: str,
    implementation: ImplementationBinding,
    workload: WorkloadBinding,
    protocol_fingerprint: str,
    capture_representative: bool = False,
) -> PairExecution:
    """Execute one explicit A/B pair; primarily useful for focused validation."""

    return _execute_pair(
        records,
        _PairTask(
            variant=variant,
            context_bucket=context_bucket,
            scenario=scenario,
            seed=seed,
            failure_schedule=failure_schedule,
            failure_binding_fingerprint=failure_binding_fingerprint,
            implementation=implementation,
            workload=workload,
            protocol_fingerprint=protocol_fingerprint,
            capture_representative=capture_representative,
        ),
    )


def _freeze_schedules(
    records: Sequence[Mapping[str, Any]],
    tasks: Sequence[_ScheduleTask],
    *,
    jobs: int,
    worker_workload_path: Path | None,
    workload: WorkloadBinding,
) -> dict[str, _FrozenSchedule]:
    if jobs == 1:
        frozen = [_derive_one_schedule(records, task) for task in tasks]
    else:
        if worker_workload_path is None:
            raise ExperimentSuiteError("parallel execution requires a worker workload path")
        with ProcessPoolExecutor(
            max_workers=jobs,
            initializer=_worker_initialize,
            initargs=(
                worker_workload_path.as_posix(),
                workload.sha256,
                workload.record_count,
            ),
        ) as executor:
            frozen = list(
                executor.map(
                    _worker_derive_schedule,
                    tasks,
                    chunksize=len(CONTEXT_BUCKET_NAMES),
                )
            )
    result = {item.key: item for item in frozen}
    if len(result) != len(tasks):
        raise ExperimentSuiteError("failure schedule keys are not unique")
    return result


def _pair_tasks(
    variants: Sequence[ExperimentVariant],
    seeds: Sequence[int],
    schedules: Mapping[str, _FrozenSchedule],
    *,
    implementation: ImplementationBinding,
    workload: WorkloadBinding,
    protocol_fingerprint: str,
) -> tuple[_PairTask, ...]:
    first_seed = min(seeds)
    tasks: list[_PairTask] = []
    for variant in variants:
        parameter_fp = _parameter_fingerprint(variant)
        for bucket in CONTEXT_BUCKET_NAMES:
            for scenario in SCENARIOS:
                for seed in seeds:
                    schedule: FailureSchedule | None = None
                    failure_binding = NO_FAILURE_SCHEDULE_FINGERPRINT
                    if scenario is Scenario.GPU_FAILURE:
                        schedule_key = sha256_json(
                            {
                                "parameters_fingerprint": parameter_fp,
                                "context_bucket": bucket,
                                "seed": seed,
                            }
                        )
                        frozen = schedules.get(schedule_key)
                        if frozen is None:
                            raise ExperimentSuiteError(
                                f"missing frozen failure schedule for {variant.variant_id}/"
                                f"{bucket}/seed-{seed}"
                            )
                        schedule = frozen.schedule
                        failure_binding = frozen.binding_fingerprint
                    capture = (
                        variant.suite == "core"
                        and variant.variant_id == "aegiskv_unified"
                        and bucket == "128k"
                        and scenario is Scenario.GPU_FAILURE
                        and seed == first_seed
                    )
                    tasks.append(
                        _PairTask(
                            variant=variant,
                            context_bucket=bucket,
                            scenario=scenario,
                            seed=seed,
                            failure_schedule=schedule,
                            failure_binding_fingerprint=failure_binding,
                            implementation=implementation,
                            workload=workload,
                            protocol_fingerprint=protocol_fingerprint,
                            capture_representative=capture,
                        )
                    )
    return tuple(tasks)


def _run_pairs(
    records: Sequence[Mapping[str, Any]],
    tasks: Sequence[_PairTask],
    *,
    jobs: int,
    worker_workload_path: Path | None,
    workload: WorkloadBinding,
) -> list[PairExecution]:
    if jobs == 1:
        return [_execute_pair(records, task) for task in tasks]
    if worker_workload_path is None:
        raise ExperimentSuiteError("parallel execution requires a worker workload path")
    with ProcessPoolExecutor(
        max_workers=jobs,
        initializer=_worker_initialize,
        initargs=(
            worker_workload_path.as_posix(),
            workload.sha256,
            workload.record_count,
        ),
    ) as executor:
        return list(executor.map(_worker_execute_pair, tasks, chunksize=1))


def _expected_run_ids(variants: Sequence[ExperimentVariant], seeds: Sequence[int]) -> set[str]:
    return {
        CellSpec(variant, bucket, scenario, seed, repetition, None).run_id
        if scenario is Scenario.NO_FAILURE
        else (
            f"{variant.suite}:{variant.variant_id}:{bucket}:"
            f"{scenario.value}:seed-{seed}:repeat-{repetition}"
        )
        for variant in variants
        for bucket in CONTEXT_BUCKET_NAMES
        for scenario in SCENARIOS
        for seed in seeds
        for repetition in REPETITIONS
    }


def _completeness(
    rows: Sequence[Mapping[str, Any]],
    pair_audits: Sequence[Mapping[str, Any]],
    variants: Sequence[ExperimentVariant],
    seeds: Sequence[int],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    actual_ids = [str(row["run_id"]) for row in rows]
    expected_ids = _expected_run_ids(variants, seeds)
    actual_set = set(actual_ids)
    duplicate_ids = sorted(run_id for run_id in actual_set if actual_ids.count(run_id) != 1)
    missing = sorted(expected_ids - actual_set)
    unexpected = sorted(actual_set - expected_ids)
    execution = protocol.get("execution")
    if not isinstance(execution, Mapping):
        raise ExperimentSuiteError("protocol execution section is malformed")
    expected_rows = execution.get("expected_row_count")
    expected_pairs = execution.get("expected_pair_count")
    passed = (
        not duplicate_ids
        and not missing
        and not unexpected
        and len(rows) == expected_rows
        and len(pair_audits) == expected_pairs
        and all(audit.get("status") == "PASS" for audit in pair_audits)
    )
    document: dict[str, Any] = {
        "schema": f"{SCHEMA_VERSION}.completeness",
        "status": "PASS" if passed else "FAIL",
        "expected_row_count": expected_rows,
        "actual_row_count": len(rows),
        "expected_pair_count": expected_pairs,
        "actual_pair_count": len(pair_audits),
        "duplicate_run_ids": duplicate_ids,
        "missing_run_ids": missing,
        "unexpected_run_ids": unexpected,
        "all_pairs_exact": all(audit.get("status") == "PASS" for audit in pair_audits),
        "silent_fallback_count": 0,
        "evidence": EVIDENCE_BOUNDARY,
    }
    document["fingerprint"] = sha256_json(document)
    if not passed:
        raise ExperimentSuiteError(f"suite completeness failed: {document}")
    return document


def _schedule_documents(
    schedules: Mapping[str, _FrozenSchedule], variants: Sequence[ExperimentVariant]
) -> list[dict[str, Any]]:
    users: dict[str, list[dict[str, str]]] = defaultdict(list)
    for variant in variants:
        parameter_fp = _parameter_fingerprint(variant)
        for bucket in CONTEXT_BUCKET_NAMES:
            for seed in sorted({item.seed for item in schedules.values()}):
                key = sha256_json(
                    {
                        "parameters_fingerprint": parameter_fp,
                        "context_bucket": bucket,
                        "seed": seed,
                    }
                )
                if key in schedules:
                    users[key].append(
                        {
                            "suite": variant.suite,
                            "variant_id": variant.variant_id,
                            "variant_fingerprint": variant.fingerprint,
                        }
                    )
    documents: list[dict[str, Any]] = []
    for key, frozen in sorted(schedules.items()):
        documents.append(
            {
                "schema": f"{SCHEMA_VERSION}.failure_schedule",
                "status": "PASS",
                "schedule_key": key,
                "parameters_fingerprint": frozen.parameters_fingerprint,
                "failure_schedule_fingerprint": frozen.schedule.fingerprint,
                "failure_binding_fingerprint": frozen.binding_fingerprint,
                "context_bucket": frozen.context_bucket,
                "seed": frozen.seed,
                "schedule": frozen.schedule.to_dict(),
                "used_by_variants": sorted(
                    users[key], key=lambda item: (item["suite"], item["variant_id"])
                ),
                "evidence": EVIDENCE_BOUNDARY,
            }
        )
    return documents


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(_canonical_json_bytes(value))


def _write_jsonl(path: Path, values: Sequence[Mapping[str, Any]]) -> None:
    path.write_bytes(b"".join(_canonical_json_bytes(value) for value in values))


def _publish(
    output_dir: Path,
    *,
    rows: Sequence[Mapping[str, Any]],
    pair_audits: Sequence[Mapping[str, Any]],
    schedules: Sequence[Mapping[str, Any]],
    completeness: Mapping[str, Any],
    provenance: Mapping[str, Any],
    protocol: Mapping[str, Any],
    statistics: Mapping[str, Any],
    representative: Mapping[str, Any],
) -> dict[str, Any]:
    if output_dir.exists():
        raise ExperimentSuiteError(f"existing output target is forbidden: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent))
    try:
        _write_jsonl(staging / "results.jsonl", rows)
        _write_jsonl(staging / "pair-audit.jsonl", pair_audits)
        _write_jsonl(staging / "failure-schedules.jsonl", schedules)
        _write_json(staging / "completeness.json", completeness)
        _write_json(staging / "provenance.json", provenance)
        _write_json(staging / "protocol.json", protocol)
        _write_json(staging / "statistics.json", statistics)
        _write_json(staging / "representative-run.json", representative)
        artifact_names = (
            "results.jsonl",
            "pair-audit.jsonl",
            "failure-schedules.jsonl",
            "completeness.json",
            "provenance.json",
            "protocol.json",
            "statistics.json",
            "representative-run.json",
        )
        artifact_hashes = {
            name: {
                "sha256": _sha256_file(staging / name),
                "size_bytes": (staging / name).stat().st_size,
            }
            for name in artifact_names
        }
        result_bindings = [
            {
                "run_id": row["run_id"],
                "payload_sha256": row["payload_sha256"],
                "journal_sha256": row["journal_sha256"],
                "cell_fingerprint": row["bindings"]["cell_fingerprint"],
            }
            for row in rows
        ]
        manifest: dict[str, Any] = {
            "schema": f"{SCHEMA_VERSION}.manifest",
            "status": "PASS",
            "evidence": EVIDENCE_BOUNDARY,
            "artifact_hashes": artifact_hashes,
            "result_bindings": result_bindings,
            "result_count": len(rows),
            "pair_count": len(pair_audits),
            "failure_schedule_count": len(schedules),
            "protocol_fingerprint": protocol["fingerprint"],
            "completeness_fingerprint": completeness["fingerprint"],
            "provenance_fingerprint": provenance["fingerprint"],
            "statistics_fingerprint": statistics["fingerprint"],
        }
        manifest["fingerprint"] = sha256_json(manifest)
        _write_json(staging / "manifest.json", manifest)
        if output_dir.exists():
            raise ExperimentSuiteError(
                f"output target appeared during execution and will not be replaced: {output_dir}"
            )
        staging.replace(output_dir)
        return manifest
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def run_e2_matrix(
    records: Sequence[Mapping[str, Any]],
    *,
    workload: WorkloadBinding,
    implementation: ImplementationBinding,
    output_dir: Path,
    selection: SuiteSelection = "core",
    seeds: Sequence[int] = DEFAULT_SEEDS,
    jobs: int = 1,
    worker_workload_path: Path | None = None,
) -> dict[str, Any]:
    """Execute, audit, and atomically publish an explicit GlobalDES E2 matrix."""

    if output_dir.exists():
        raise ExperimentSuiteError(f"existing output target is forbidden: {output_dir}")
    if type(jobs) is not int or jobs <= 0:
        raise ExperimentSuiteError("jobs must be a positive integer")
    canonical_seeds = normalize_seeds(seeds)
    variants = selected_variants(selection)
    protocol = build_protocol(selection, canonical_seeds)
    protocol_fingerprint = str(protocol["fingerprint"])
    schedule_tasks = _schedule_tasks(variants, canonical_seeds)
    schedules = _freeze_schedules(
        records,
        schedule_tasks,
        jobs=jobs,
        worker_workload_path=worker_workload_path,
        workload=workload,
    )
    pair_tasks = _pair_tasks(
        variants,
        canonical_seeds,
        schedules,
        implementation=implementation,
        workload=workload,
        protocol_fingerprint=protocol_fingerprint,
    )
    executions = _run_pairs(
        records,
        pair_tasks,
        jobs=jobs,
        worker_workload_path=worker_workload_path,
        workload=workload,
    )
    rows = sorted(
        (row for execution in executions for row in execution.rows),
        key=lambda row: str(row["run_id"]),
    )
    pair_audits = sorted(
        (execution.audit for execution in executions),
        key=lambda audit: str(audit["pair_id"]),
    )
    representatives = [
        execution.representative for execution in executions if execution.representative is not None
    ]
    if len(representatives) != 1:
        raise ExperimentSuiteError(
            f"expected exactly one representative run, found {len(representatives)}"
        )
    completeness = _completeness(rows, pair_audits, variants, canonical_seeds, protocol)
    statistics = build_statistics(
        rows,
        seeds=canonical_seeds,
        evidence=EVIDENCE_BOUNDARY,
    )
    schedule_documents = _schedule_documents(schedules, variants)
    provenance: dict[str, Any] = {
        "schema": f"{SCHEMA_VERSION}.provenance",
        "status": "PASS",
        "evidence": EVIDENCE_BOUNDARY,
        "model_deployment_contract": qwen3_8b_dp_only_contract(),
        "implementation": implementation.to_dict(),
        "implementation_fingerprint": implementation.fingerprint,
        "workload": workload.to_dict(),
        "workload_fingerprint": workload.fingerprint,
        "protocol_fingerprint": protocol_fingerprint,
        "variant_fingerprints": {
            f"{variant.suite}:{variant.variant_id}": variant.fingerprint for variant in variants
        },
        "failure_binding_fingerprints": sorted(
            {document["failure_binding_fingerprint"] for document in schedule_documents}
        ),
        "execution": {
            "engine": "GlobalDES",
            "clock": "single_global_virtual_clock",
            "parallel_worker_processes": jobs,
            "fresh_global_des_per_repetition": True,
            "canonical_result_sort_key": "run_id",
            "wall_clock_measurements_recorded": False,
            "physical_components_executed": False,
            "slurm_used": False,
        },
    }
    provenance["fingerprint"] = sha256_json(provenance)
    return _publish(
        output_dir,
        rows=rows,
        pair_audits=pair_audits,
        schedules=schedule_documents,
        completeness=completeness,
        provenance=provenance,
        protocol=protocol,
        statistics=statistics,
        representative=representatives[0],
    )


def run_explicit_e2_matrix(
    records: Sequence[Mapping[str, Any]],
    *,
    variants: Sequence[ExperimentVariant],
    workload: WorkloadBinding,
    implementation: ImplementationBinding,
    output_dir: Path,
    protocol_id: str,
    representative_variant_id: str,
    seeds: Sequence[int],
    jobs: int = 1,
    worker_workload_path: Path | None = None,
) -> dict[str, Any]:
    """Publish a versioned focused matrix without mutating the v1 suite catalog.

    Focused sweeps share one logical failure schedule per bucket/seed across all
    candidate parameters.  The schedule is request-progress based, so each
    candidate resolves its own absolute virtual timestamp on its fresh DES.
    """

    if output_dir.exists():
        raise ExperimentSuiteError(f"existing output target is forbidden: {output_dir}")
    if type(jobs) is not int or jobs <= 0:
        raise ExperimentSuiteError("jobs must be a positive integer")
    if not protocol_id or not representative_variant_id:
        raise ExperimentSuiteError("focused protocol identifiers must be non-empty")
    canonical_seeds = normalize_seeds(seeds)
    canonical_variants = tuple(variants)
    if not canonical_variants:
        raise ExperimentSuiteError("focused matrix requires at least one variant")
    variant_keys = [(item.suite, item.variant_id) for item in canonical_variants]
    if len(set(variant_keys)) != len(variant_keys):
        raise ExperimentSuiteError("focused matrix variant IDs are not unique")
    if len({item.fingerprint for item in canonical_variants}) != len(canonical_variants):
        raise ExperimentSuiteError("focused matrix variant fingerprints are not unique")
    if representative_variant_id not in {item.variant_id for item in canonical_variants}:
        raise ExperimentSuiteError("focused representative variant is absent")

    expected_pairs = (
        len(canonical_variants)
        * len(CONTEXT_BUCKET_NAMES)
        * len(SCENARIOS)
        * len(canonical_seeds)
    )
    protocol: dict[str, Any] = {
        "schema": f"{SCHEMA_VERSION}.focused_protocol",
        "status": "PASS",
        "protocol_id": protocol_id,
        "evidence": EVIDENCE_BOUNDARY,
        "model_deployment_contract": qwen3_8b_dp_only_contract(),
        "global_clock": "single_global_virtual_clock",
        "physical_or_slurm_path": False,
        "failure_types": ["GPU_FAILURE"],
        "failure_schedule_contract": (
            "same_focus_span_target_gpu_and_request_progress_per_bucket_seed"
        ),
        "execution": {
            "variant_ids": [item.variant_id for item in canonical_variants],
            "context_buckets": list(CONTEXT_BUCKET_NAMES),
            "scenarios": [item.value for item in SCENARIOS],
            "seeds": list(canonical_seeds),
            "repetitions": list(REPETITIONS),
            "expected_pair_count": expected_pairs,
            "expected_row_count": expected_pairs * len(REPETITIONS),
            "fresh_global_des_per_repetition": True,
            "silent_fallback_allowed": False,
        },
    }
    protocol["fingerprint"] = sha256_json(protocol)
    protocol_fingerprint = str(protocol["fingerprint"])

    schedule_variant = canonical_variants[0]
    schedule_parameter_fp = _parameter_fingerprint(schedule_variant)
    schedule_tasks = tuple(
        _ScheduleTask(schedule_parameter_fp, schedule_variant, bucket, seed)
        for seed in canonical_seeds
        for bucket in CONTEXT_BUCKET_NAMES
    )
    frozen_schedules = _freeze_schedules(
        records,
        schedule_tasks,
        jobs=jobs,
        worker_workload_path=worker_workload_path,
        workload=workload,
    )
    schedules_by_bucket_seed = {
        (item.context_bucket, item.seed): item for item in frozen_schedules.values()
    }
    if len(schedules_by_bucket_seed) != len(CONTEXT_BUCKET_NAMES) * len(canonical_seeds):
        raise ExperimentSuiteError("focused failure schedule coverage is incomplete")

    pair_tasks: list[_PairTask] = []
    first_seed = min(canonical_seeds)
    for variant in canonical_variants:
        for bucket in CONTEXT_BUCKET_NAMES:
            for scenario in SCENARIOS:
                for seed in canonical_seeds:
                    schedule: FailureSchedule | None = None
                    failure_binding = NO_FAILURE_SCHEDULE_FINGERPRINT
                    if scenario is Scenario.GPU_FAILURE:
                        frozen = schedules_by_bucket_seed[(bucket, seed)]
                        schedule = frozen.schedule
                        failure_binding = sha256_json(
                            {
                                "protocol_fingerprint": protocol_fingerprint,
                                "failure_schedule_fingerprint": schedule.fingerprint,
                                "shared_across_variant_parameters": True,
                            }
                        )
                    pair_tasks.append(
                        _PairTask(
                            variant=variant,
                            context_bucket=bucket,
                            scenario=scenario,
                            seed=seed,
                            failure_schedule=schedule,
                            failure_binding_fingerprint=failure_binding,
                            implementation=implementation,
                            workload=workload,
                            protocol_fingerprint=protocol_fingerprint,
                            capture_representative=(
                                variant.variant_id == representative_variant_id
                                and bucket == "128k"
                                and scenario is Scenario.GPU_FAILURE
                                and seed == first_seed
                            ),
                        )
                    )
    executions = _run_pairs(
        records,
        pair_tasks,
        jobs=jobs,
        worker_workload_path=worker_workload_path,
        workload=workload,
    )
    rows = sorted(
        (row for execution in executions for row in execution.rows),
        key=lambda row: str(row["run_id"]),
    )
    pair_audits = sorted(
        (execution.audit for execution in executions),
        key=lambda audit: str(audit["pair_id"]),
    )
    representatives = [
        execution.representative
        for execution in executions
        if execution.representative is not None
    ]
    if len(representatives) != 1:
        raise ExperimentSuiteError(
            f"expected exactly one focused representative, found {len(representatives)}"
        )
    completeness = _completeness(
        rows,
        pair_audits,
        canonical_variants,
        canonical_seeds,
        protocol,
    )
    statistics = build_statistics(
        rows,
        seeds=canonical_seeds,
        evidence=EVIDENCE_BOUNDARY,
    )
    schedule_documents = []
    for (bucket, seed), frozen in sorted(schedules_by_bucket_seed.items()):
        binding = sha256_json(
            {
                "protocol_fingerprint": protocol_fingerprint,
                "failure_schedule_fingerprint": frozen.schedule.fingerprint,
                "shared_across_variant_parameters": True,
            }
        )
        schedule_documents.append(
            {
                "schema": f"{SCHEMA_VERSION}.focused_failure_schedule",
                "status": "PASS",
                "context_bucket": bucket,
                "seed": seed,
                "failure_schedule_fingerprint": frozen.schedule.fingerprint,
                "failure_binding_fingerprint": binding,
                "shared_across_variant_parameters": True,
                "schedule": frozen.schedule.to_dict(),
                "used_by_variants": [
                    {
                        "suite": variant.suite,
                        "variant_id": variant.variant_id,
                        "variant_fingerprint": variant.fingerprint,
                    }
                    for variant in canonical_variants
                ],
                "evidence": EVIDENCE_BOUNDARY,
            }
        )
    provenance: dict[str, Any] = {
        "schema": f"{SCHEMA_VERSION}.focused_provenance",
        "status": "PASS",
        "evidence": EVIDENCE_BOUNDARY,
        "model_deployment_contract": qwen3_8b_dp_only_contract(),
        "implementation": implementation.to_dict(),
        "implementation_fingerprint": implementation.fingerprint,
        "workload": workload.to_dict(),
        "workload_fingerprint": workload.fingerprint,
        "protocol_fingerprint": protocol_fingerprint,
        "variant_fingerprints": {
            f"{variant.suite}:{variant.variant_id}": variant.fingerprint
            for variant in canonical_variants
        },
        "failure_binding_fingerprints": sorted(
            {item["failure_binding_fingerprint"] for item in schedule_documents}
        ),
        "execution": {
            "engine": "GlobalDES",
            "clock": "single_global_virtual_clock",
            "parallel_worker_processes": jobs,
            "fresh_global_des_per_repetition": True,
            "canonical_result_sort_key": "run_id",
            "wall_clock_measurements_recorded": False,
            "physical_components_executed": False,
            "slurm_used": False,
        },
    }
    provenance["fingerprint"] = sha256_json(provenance)
    return _publish(
        output_dir,
        rows=rows,
        pair_audits=pair_audits,
        schedules=schedule_documents,
        completeness=completeness,
        provenance=provenance,
        protocol=protocol,
        statistics=statistics,
        representative=cast(Mapping[str, Any], representatives[0]),
    )
