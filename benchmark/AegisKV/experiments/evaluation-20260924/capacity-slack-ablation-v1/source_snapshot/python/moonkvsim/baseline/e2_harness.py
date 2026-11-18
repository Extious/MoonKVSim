"""Fail-closed launcher for one uncalibrated vanilla real-trace E2 replay.

The launcher intentionally lives outside the baseline state machines.  It
resolves every resource from one strict configuration, verifies byte hashes
before construction, accepts either no failure or an independent explicit
fixed-time GPU-failure protocol, and atomically publishes the complete
fixed-schema 19-artifact section-16 projection.

Nothing in this module is timing calibration.  Its integer predictor and all
deployment/rate values are explicitly assumed inputs used to drive a
deterministic E2 state-machine probe.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from moonkvsim.baseline.runtime import (
    BaselineCoordinator,
    BaselineReplicaRuntime,
    TransferTaskResourcePlan,
)
from moonkvsim.baseline.trace_runner import (
    EVIDENCE_BOUNDARY,
    SOURCE_BLOCK_SIZE_TOKENS,
    STORE_PAYLOAD_BYTE_BASIS,
    TraceFailureSpec,
    TraceReplicaBinding,
    TraceRunnerConfig,
    TraceRunResult,
    TraceSelection,
    VanillaBaselineTraceRunner,
    load_trace_run_input,
)
from moonkvsim.common.hash import canonical_json_bytes
from moonkvsim.integration.vllm.block_pool import BlockPool
from moonkvsim.integration.vllm.hbm_block_ledger import (
    HbmBlockLedgerBridge,
    HbmStageRankBinding,
)
from moonkvsim.integration.vllm.kv_layout import StageBlockLayout
from moonkvsim.integration.vllm.router import DPRouter, RoutePolicy
from moonkvsim.integration.vllm.scheduler import ContinuousBatchScheduler
from moonkvsim.output.section16 import SECTION_16_ARTIFACTS
from moonkvsim.predictor import (
    AssumedIntegerMixedPhaseCompositionRule,
    CalibrationEvidence,
    ForwardBoundary,
    ForwardPredictor,
    PredictionBatch,
    PredictionPhase,
    PredictionProfile,
)
from moonkvsim.recovery.baseline import EngineTarget, PhysicalGPU
from moonkvsim.simulation.allocation_registry import AllocationRegistry
from moonkvsim.simulation.flow_des import FlowDESController
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.network import FlowContentionModel
from moonkvsim.simulation.resource import ConcurrencyResource, RateResource
from moonkvsim.store.allocation_strategy import RandomAllocationStrategy
from moonkvsim.store.client import StoreClient
from moonkvsim.store.endpoint import (
    EndpointRegistrationManager,
    EndpointRegistrationProfile,
)
from moonkvsim.store.master import MasterService
from moonkvsim.store.segment import Segment
from moonkvsim.store.transfer_engine import (
    MemoryKind,
    MemoryLocation,
    PathPreference,
    Topology,
    TopologyPath,
    TransferTask,
    TransportKind,
)
from moonkvsim.store.transfer_resources import (
    StagingAllocationSpec,
    TransferResourceLeaseManager,
)
from moonkvsim.store.transfer_runtime import TransferRuntime

HARNESS_SCHEMA: Final = "moonkvsim.vanilla-trace-e2-harness.v1"
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
SCHEMA_PATH: Final = REPOSITORY_ROOT / "schemas/vanilla-trace-e2-harness.schema.json"
MODEL_WEIGHTS_ACCOUNT: Final = "MODEL_WEIGHTS"
RUNTIME_FIXED_ACCOUNT: Final = "RUNTIME_FIXED"
RUNTIME_DYNAMIC_ACCOUNT: Final = "RUNTIME_DYNAMIC"
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_MOUNT_ESCAPE_RE: Final = re.compile(r"\\([0-7]{3})")
SEMANTIC_SOURCE_SNAPSHOT_SCHEMA: Final = "moonkvsim.semantic-source-snapshot.v1"


class E2HarnessError(RuntimeError):
    """An input or output cannot preserve the harness evidence boundary."""


@dataclass(frozen=True, slots=True)
class SemanticSourceSnapshot:
    """Content-addressed semantic sources plus an honest Git worktree state."""

    repository_root: str
    git_branch: str | None
    git_head_state: str
    git_head_commit: str | None
    git_head_tree: str | None
    git_porcelain_sha256: str
    git_porcelain_entry_count: int
    git_worktree_clean: bool
    semantic_files: tuple[Mapping[str, object], ...]
    semantic_files_sha256: str
    repository_semantic_file_count: int
    tracked_repository_semantic_file_count: int
    source_frozen: bool
    source_freeze_blockers: tuple[str, ...]
    source_frozen_reason: str

    def canonical_fields(self) -> dict[str, object]:
        return {
            "schema": SEMANTIC_SOURCE_SNAPSHOT_SCHEMA,
            "repository_root": self.repository_root,
            "git": {
                "branch": self.git_branch,
                "head_state": self.git_head_state,
                "head_commit": self.git_head_commit,
                "head_tree": self.git_head_tree,
                "porcelain_sha256": self.git_porcelain_sha256,
                "porcelain_entry_count": self.git_porcelain_entry_count,
                "worktree_clean": self.git_worktree_clean,
            },
            "semantic_sources": {
                "selection_policy": {
                    "python": "all .py/.pyi files recursively under python/moonkvsim",
                    "cli": (
                        "scripts/run_vanilla_trace_e2.py for no-failure; "
                        "scripts/run_vanilla_failure_trace_e2.py for fixed GPU failure"
                    ),
                    "schemas": "all top-level schemas/*.json",
                    "config": "selected harness config",
                    "layout": "selected target KV layout",
                    "dependencies": "pyproject.toml and uv.lock when present",
                    "bytecode_and_caches_included": False,
                },
                "files": [dict(item) for item in self.semantic_files],
                "file_count": len(self.semantic_files),
                "repository_file_count": self.repository_semantic_file_count,
                "tracked_repository_file_count": (self.tracked_repository_semantic_file_count),
                "aggregate_sha256": self.semantic_files_sha256,
            },
            "source_frozen": self.source_frozen,
            "source_freeze_blockers": list(self.source_freeze_blockers),
            "source_frozen_reason": self.source_frozen_reason,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.canonical_fields())).hexdigest()

    def to_dict(self) -> dict[str, object]:
        value = self.canonical_fields()
        value["fingerprint"] = self.fingerprint
        return value


@dataclass(frozen=True, slots=True)
class HarnessConfig:
    """Validated raw document plus immutable byte provenance."""

    raw_document: bytes
    path: Path
    sha256: str
    repository_root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.raw_document, bytes) or not self.raw_document:
            raise ValueError("raw harness document must be non-empty bytes")
        if hashlib.sha256(self.raw_document).hexdigest() != self.sha256:
            raise ValueError("raw harness document does not match its SHA-256")

    @property
    def document(self) -> Mapping[str, Any]:
        """Return an isolated parse so callers cannot mutate validated semantics."""

        value = json.loads(self.raw_document)
        if not isinstance(value, dict):
            raise E2HarnessError("validated harness bytes no longer decode to an object")
        return cast(Mapping[str, Any], value)

    @property
    def trace_path(self) -> Path:
        return Path(cast(str, self.document["trace"]["path"]))

    @property
    def trace_sha256(self) -> str:
        return cast(str, self.document["trace"]["sha256"])

    @property
    def workflow_ids(self) -> tuple[str, ...]:
        values = cast(list[str], self.document["trace"]["selection"]["workflow_ids"])
        return tuple(sorted(values))

    @property
    def failure_enabled(self) -> bool:
        return cast(bool, self.document["failure"]["enabled"])

    @property
    def transfer_resource_plan_enabled(self) -> bool:
        network = cast(Mapping[str, Any], self.document["network"])
        return "transfer_resource_plan" in network


@dataclass(frozen=True, slots=True)
class HarnessOutcome:
    """Published artifact identities and the underlying trace-run result."""

    config: HarnessConfig
    result: TraceRunResult
    output_directory: Path
    artifact_sha256: Mapping[str, str]
    output_filesystem_type: str
    assumed_formula_parameter_sha256: str
    semantic_source_snapshot: SemanticSourceSnapshot
    failure_specs: tuple[TraceFailureSpec, ...] = ()

    def to_dict(self) -> dict[str, object]:
        coverage = self.result.context_coverage_document()
        document: dict[str, object] = {
            "schema": "moonkvsim.vanilla-trace-e2-harness-result.v1",
            "status": self.result.status.value,
            "exit_semantics": "PASS=0,BLOCKED=3,input_or_invariant_error=2",
            "evidence_boundary": EVIDENCE_BOUNDARY,
            "formal_use_allowed": False,
            "physical_timing_claim_allowed": False,
            "predictor_calibration_status": "not_calibrated",
            "predictor_database_sha256": None,
            "assumed_formula_parameter_sha256": self.assumed_formula_parameter_sha256,
            "semantic_source_snapshot_fingerprint": (self.semantic_source_snapshot.fingerprint),
            "semantic_source_manifest_sha256": (
                self.semantic_source_snapshot.semantic_files_sha256
            ),
            "semantic_source_file_count": len(self.semantic_source_snapshot.semantic_files),
            "semantic_source_unchanged_during_run": True,
            "semantic_source_frozen": self.semantic_source_snapshot.source_frozen,
            "semantic_source_freeze_blockers": list(
                self.semantic_source_snapshot.source_freeze_blockers
            ),
            "semantic_source_frozen_reason": (self.semantic_source_snapshot.source_frozen_reason),
            "git_head_state": self.semantic_source_snapshot.git_head_state,
            "git_head_commit": self.semantic_source_snapshot.git_head_commit,
            "git_head_tree": self.semantic_source_snapshot.git_head_tree,
            "git_porcelain_sha256": (self.semantic_source_snapshot.git_porcelain_sha256),
            "config_path": str(self.config.path),
            "config_sha256": self.config.sha256,
            "trace_path": str(self.config.trace_path),
            "trace_sha256": self.result.run_input.source_sha256,
            "total_valid_span_count": self.result.run_input.total_valid_span_count,
            "selected_workflow_ids": list(self.result.run_input.selected_workflow_ids),
            "selected_span_count": len(self.result.run_input.spans),
            "context_coverage": coverage["context_buckets"],
            "max_total_model_tokens": coverage["max_total_model_tokens"],
            "gap_codes": [item.code for item in self.result.gaps],
            "output_directory": str(self.output_directory),
            "output_filesystem_type": self.output_filesystem_type,
            "artifact_sha256": dict(sorted(self.artifact_sha256.items())),
        }
        if self.failure_specs:
            document["failure_protocol"] = _failure_protocol_document(
                self.config,
                self.failure_specs,
            )
        if self.config.transfer_resource_plan_enabled:
            document["transfer_resource_protocol"] = _transfer_resource_protocol_document(
                self.config
            )
        return document


class AssumedIntegerShapeProvider:
    """Positive integer shape formula used only to make an E2 replay executable."""

    def __init__(self, provider_name: str, formula: Mapping[str, int]) -> None:
        self.provider_name = provider_name
        self.formula = dict(formula)

    def predict_forward_duration_ns(self, batch: PredictionBatch) -> int:
        shape = batch.shape
        duration = (
            self.formula["base_ns"] + self.formula["batch_request_overhead_ns"] * shape.batch_size
        )
        if batch.phase is PredictionPhase.PREFILL:
            duration += self.formula["prefill_ns_per_scheduled_token"] * shape.total_extend_length
        else:
            duration += self.formula["decode_ns_per_request"] * shape.batch_size
            duration += self.formula["decode_ns_per_past_token"] * sum(shape.past_kv_lengths)
        if duration <= 0:
            raise E2HarnessError("assumed predictor formula produced a non-positive duration")
        return duration


@dataclass(frozen=True, slots=True)
class AssumedTransferResourcePlanProvider:
    """Build one task-bound, uncalibrated calendar/staging plan."""

    duration_ns: int
    latest_start_slack_ns: int
    staging_alignment_bytes: int
    staging_allocator_metadata_bytes: int
    known_staging_resource_ids: frozenset[str]
    known_concurrency_resource_ids: frozenset[str]
    parameter_fingerprint: str

    def __call__(self, task: TransferTask) -> TransferTaskResourcePlan:
        path = task.metadata.path
        unknown_concurrency = (
            set(path.concurrency_resource_ids) - self.known_concurrency_resource_ids
        )
        if unknown_concurrency:
            raise E2HarnessError(
                f"transfer path names unknown concurrency resources: {sorted(unknown_concurrency)}"
            )
        staging_ids = tuple(
            dict.fromkeys(
                resource_id
                for resource_id in (
                    path.source_host_staging_resource_id,
                    path.destination_host_staging_resource_id,
                )
                if resource_id is not None
            )
        )
        unknown_staging = set(staging_ids) - self.known_staging_resource_ids
        if unknown_staging:
            raise E2HarnessError(
                f"transfer path names unknown Host staging resources: {sorted(unknown_staging)}"
            )
        if path.transport is TransportKind.RDMA_GDR and staging_ids:
            raise E2HarnessError("RDMA_GDR resource plan cannot charge Host staging")
        if (
            path.transport
            in {
                TransportKind.RDMA_HOST_STAGED,
                TransportKind.TCP_HOST_STAGED,
            }
            and not staging_ids
        ):
            raise E2HarnessError("host-staged transfer plan has no Host staging resource")

        requested_bytes = task.metadata.total_bytes
        prealigned_bytes = requested_bytes + self.staging_allocator_metadata_bytes
        allocated_bytes = (
            (prealigned_bytes + self.staging_alignment_bytes - 1)
            // self.staging_alignment_bytes
            * self.staging_alignment_bytes
        )
        staging_specs = tuple(
            StagingAllocationSpec(
                allocation_id=(f"e2-harness-staging:{task.metadata.transfer_id}:{resource_id}"),
                resource_id=resource_id,
                payload_bytes=task.metadata.total_bytes,
                requested_bytes=requested_bytes,
                allocated_bytes=allocated_bytes,
                padding_bytes=0,
                allocator_metadata_bytes=self.staging_allocator_metadata_bytes,
                internal_fragmentation_bytes=(allocated_bytes - prealigned_bytes),
                alignment_bytes=self.staging_alignment_bytes,
            )
            for resource_id in staging_ids
        )
        return TransferTaskResourcePlan(
            duration_ns=self.duration_ns,
            latest_start_ns=(task.metadata.ready_ns + self.latest_start_slack_ns),
            staging_specs=staging_specs,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "moonkvsim.assumed-transfer-resource-plan.v1",
            "parameter_source": "assumed",
            "calibration_status": "not_calibrated",
            "formal_use_allowed": False,
            "duration_ns": self.duration_ns,
            "latest_start_slack_ns": self.latest_start_slack_ns,
            "staging_alignment_bytes": self.staging_alignment_bytes,
            "staging_allocator_metadata_bytes": (self.staging_allocator_metadata_bytes),
            "known_staging_resource_ids": sorted(self.known_staging_resource_ids),
            "known_concurrency_resource_ids": sorted(self.known_concurrency_resource_ids),
            "parameter_fingerprint": self.parameter_fingerprint,
        }


def load_harness_config(
    path: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> HarnessConfig:
    """Load the strict harness config and verify every referenced input hash."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise E2HarnessError("harness config must be a regular non-symlink file")
    raw = source.read_bytes()
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise E2HarnessError(f"invalid harness JSON: {error}") from error
    if not isinstance(document, dict):
        raise E2HarnessError("harness config must be a JSON object")
    schema = json.loads(SCHEMA_PATH.read_bytes())
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        validation_error = errors[0]
        location = ".".join(str(part) for part in validation_error.absolute_path) or "<root>"
        raise E2HarnessError(
            f"harness schema validation failed at {location}: {validation_error.message}"
        )

    config = HarnessConfig(
        raw_document=raw,
        path=source.resolve(),
        sha256=hashlib.sha256(raw).hexdigest(),
        repository_root=Path(repository_root).resolve(),
    )
    _validate_config_semantics(config)
    return config


def resolve_failure_specs(config: HarnessConfig) -> tuple[TraceFailureSpec, ...]:
    """Resolve only explicit fixed-time GPU fail-stop events."""

    failure = cast(Mapping[str, Any], config.document["failure"])
    if not cast(bool, failure["enabled"]):
        return ()
    events = cast(list[Mapping[str, Any]], failure["events"])
    event_times = [cast(int, item["at_ns"]) for item in events]
    if event_times != sorted(event_times):
        raise E2HarnessError("failure events must be ordered by increasing at_ns")
    if len(event_times) != len(set(event_times)):
        raise E2HarnessError("failure event at_ns values must be unique")
    failure_ids = [cast(str, item["failure_id"]) for item in events]
    if len(failure_ids) != len(set(failure_ids)):
        raise E2HarnessError("failure IDs must be unique")

    gpu_items = cast(list[Mapping[str, Any]], config.document["deployment"]["gpus"])
    deployment_targets = {
        (
            cast(str, item["replica_id"]),
            cast(str, item["gpu_id"]),
            cast(str, item["hbm_resource_id"]),
        )
        for item in gpu_items
    }
    targeted_gpus: set[str] = set()
    specs: list[TraceFailureSpec] = []
    for event in events:
        if event["type"] != "GPU_FAILURE":
            raise E2HarnessError("only GPU_FAILURE is accepted by the E2 failure harness")
        target = cast(Mapping[str, Any], event["target"])
        target_key = (
            cast(str, target["replica_id"]),
            cast(str, target["gpu_id"]),
            cast(str, target["hbm_resource_id"]),
        )
        if target_key not in deployment_targets:
            raise E2HarnessError(
                "failure target must exactly match one configured replica/PhysicalGPU/HBM tuple"
            )
        gpu_id = target_key[1]
        if gpu_id in targeted_gpus:
            raise E2HarnessError("one PhysicalGPU cannot have two fail-stop events")
        targeted_gpus.add(gpu_id)
        specs.append(
            TraceFailureSpec(
                failure_id=cast(str, event["failure_id"]),
                gpu_id=gpu_id,
                at_ns=cast(int, event["at_ns"]),
                detection_delay_ns=cast(int, event["detection_delay_ns"]),
            )
        )
    return tuple(specs)


def _failure_protocol_document(
    config: HarnessConfig,
    specs: tuple[TraceFailureSpec, ...],
) -> dict[str, object]:
    failure = cast(Mapping[str, Any], config.document["failure"])
    configured_events = cast(list[Mapping[str, Any]], failure.get("events", []))
    return {
        "schema": "moonkvsim.vanilla-trace-e2-failure-protocol.v1",
        "enabled": bool(specs),
        "mode": failure.get("mode", "disabled"),
        "event_count": len(specs),
        "events": [dict(item) for item in configured_events],
        "runner_specs": [
            {
                "failure_id": spec.failure_id,
                "gpu_id": spec.gpu_id,
                "at_ns": spec.at_ns,
                "detection_delay_ns": spec.detection_delay_ns,
            }
            for spec in specs
        ],
        "canonical_order": "strictly_increasing_at_ns",
        "random_selection": False,
        "implicit_fallback": False,
        "repair_enabled": False,
        "parameter_source": "assumed",
        "evidence_boundary": EVIDENCE_BOUNDARY,
        "calibration_status": "not_calibrated",
        "formal_use_allowed": False,
    }


def run_harness(config: HarnessConfig, output_directory: Path) -> HarnessOutcome:
    """Run one explicit selection/protocol and publish from a stable source set."""

    config = _revalidate_config_for_run(config)
    output, filesystem_type = _validate_output_target(config, output_directory)
    source_before = capture_semantic_source_snapshot(config)
    trace = config.document["trace"]
    run_input = load_trace_run_input(
        config.trace_path,
        selection=TraceSelection(workflow_ids=config.workflow_ids),
    )
    expected_count = cast(int, trace["expected_total_valid_span_count"])
    if run_input.source_sha256 != config.trace_sha256:
        raise E2HarnessError("normalized trace SHA-256 changed after config validation")
    if run_input.total_valid_span_count != expected_count:
        raise E2HarnessError(
            "normalized trace span count changed: "
            f"expected {expected_count}, observed {run_input.total_valid_span_count}"
        )
    if run_input.selected_workflow_ids != config.workflow_ids:
        raise E2HarnessError("whole-workflow trace selection diverged from the config")

    failure_specs = resolve_failure_specs(config)
    runner, parameter_sha256 = _build_runner(config)
    result = runner.run(run_input, failures=failure_specs)
    source_after = capture_semantic_source_snapshot(config)
    if source_before.fingerprint != source_after.fingerprint:
        raise E2HarnessError(
            "semantic source snapshot changed during the run; refusing publication: "
            f"before={source_before.fingerprint}, after={source_after.fingerprint}"
        )
    result = replace(
        result,
        semantic_source_provenance={
            "schema": "moonkvsim.semantic-source-run-provenance.v1",
            "unchanged_during_run": True,
            "formal_use_allowed": False,
            "evidence_boundary": EVIDENCE_BOUNDARY,
            "start_snapshot": source_before.to_dict(),
            "end_snapshot_fingerprint": source_after.fingerprint,
            "comparison": "byte_identical_canonical_snapshot",
        },
        failure_protocol_provenance=(
            _failure_protocol_document(config, failure_specs) if failure_specs else None
        ),
        transfer_resource_protocol_provenance=(
            _transfer_resource_protocol_document(config)
            if config.transfer_resource_plan_enabled
            else None
        ),
    )
    result.write_section_16_artifacts(output)
    expected_files = set(cast(list[str], config.document["output"]["artifact_set"]))
    observed_files = {item.name for item in output.iterdir()}
    if observed_files != expected_files:
        raise E2HarnessError(
            "published artifact set diverged: "
            f"expected={sorted(expected_files)}, observed={sorted(observed_files)}"
        )
    hashes = {name: _sha256_file(output / name) for name in sorted(observed_files)}
    return HarnessOutcome(
        config=config,
        result=result,
        output_directory=output,
        artifact_sha256=hashes,
        output_filesystem_type=filesystem_type,
        assumed_formula_parameter_sha256=parameter_sha256,
        semantic_source_snapshot=source_before,
        failure_specs=failure_specs,
    )


def _revalidate_config_for_run(config: HarnessConfig) -> HarnessConfig:
    """Bind execution to the exact regular file bytes validated by the loader."""

    if not isinstance(config, HarnessConfig):
        raise TypeError("config must be a HarnessConfig")
    source = config.path
    if source.is_symlink() or not source.is_file():
        raise E2HarnessError("harness config changed type after validation")
    try:
        raw = source.read_bytes()
    except OSError as error:
        raise E2HarnessError(f"cannot reread harness config before execution: {error}") from error
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    if raw != config.raw_document or observed_sha256 != config.sha256:
        raise E2HarnessError(
            "harness config bytes changed after validation; refusing execution: "
            f"expected={config.sha256}, observed={observed_sha256}"
        )
    refreshed = load_harness_config(source, repository_root=config.repository_root)
    if refreshed.raw_document != config.raw_document or refreshed.sha256 != config.sha256:
        raise E2HarnessError("harness config revalidation did not preserve byte identity")
    return refreshed


def _validate_config_semantics(config: HarnessConfig) -> None:
    document = config.document
    if document["schema"] != HARNESS_SCHEMA:
        raise E2HarnessError("unsupported harness schema")
    trace = document["trace"]
    trace_path = config.trace_path
    if not trace_path.is_absolute() or trace_path.is_symlink() or not trace_path.is_file():
        raise E2HarnessError("trace.path must be an existing absolute non-symlink file")
    observed_trace_sha = _sha256_file(trace_path)
    if observed_trace_sha != trace["sha256"]:
        raise E2HarnessError(
            f"trace SHA-256 mismatch: expected {trace['sha256']}, observed {observed_trace_sha}"
        )

    target = document["target"]
    layout_path = _repository_file(config, cast(str, target["kv_layout_path"]))
    observed_layout_sha = _sha256_file(layout_path)
    if observed_layout_sha != target["kv_layout_sha256"]:
        raise E2HarnessError(
            "KV layout SHA-256 mismatch: "
            f"expected {target['kv_layout_sha256']}, observed {observed_layout_sha}"
        )

    gpu_items = cast(list[Mapping[str, Any]], document["deployment"]["gpus"])
    unique_fields = (
        "replica_id",
        "dp_rank",
        "scheduler_id",
        "gpu_id",
        "hbm_resource_id",
        "transport_endpoint",
    )
    for field_name in unique_fields:
        values = [item[field_name] for item in gpu_items]
        if len(values) != len(set(values)):
            raise E2HarnessError(f"deployment GPU field is not unique: {field_name}")
    if sorted(item["dp_rank"] for item in gpu_items) != list(range(len(gpu_items))):
        raise E2HarnessError("DP ranks must be contiguous from zero")
    for item in gpu_items:
        physical = _sourced_int(item["physical_capacity_bytes"])
        fixed = _sourced_int(item["fixed_weights_bytes"]) + _sourced_int(
            item["fixed_runtime_bytes"]
        )
        if fixed >= physical:
            raise E2HarnessError(f"fixed HBM consumes the whole GPU: {item['gpu_id']}")

    paths = cast(list[Mapping[str, Any]], document["network"]["paths"])
    path_replica_ids = [cast(str, item["replica_id"]) for item in paths]
    if len(path_replica_ids) != len(set(path_replica_ids)):
        raise E2HarnessError("network path replica IDs must be unique")
    if set(path_replica_ids) != {item["replica_id"] for item in gpu_items}:
        raise E2HarnessError("network path bindings must exactly cover DP replicas")
    directional_path_ids = [
        cast(str, item[field]) for item in paths for field in ("put_path_id", "get_path_id")
    ]
    if len(directional_path_ids) != len(set(directional_path_ids)):
        raise E2HarnessError("directional network path IDs must be unique")
    rates = cast(list[Mapping[str, Any]], document["network"]["rate_resources"])
    rate_ids = [cast(str, item["resource_id"]) for item in rates]
    if len(rate_ids) != len(set(rate_ids)):
        raise E2HarnessError("rate resource IDs must be unique")
    known_rates = set(rate_ids)
    for item in paths:
        for direction in ("put_rate_resource_ids", "get_rate_resource_ids"):
            unknown = set(cast(list[str], item[direction])) - known_rates
            if unknown:
                raise E2HarnessError(f"network path contains unknown rate resources: {unknown}")
    _validate_topology_semantics(config, gpu_items, paths)
    _validate_transfer_resource_semantics(config, gpu_items, paths)
    predictor = cast(Mapping[str, Any], document["predictor"])
    hardware_shape = {
        "schema": "moonkvsim.assumed-hardware-shape-profile.v1",
        "parameter_source": "assumed",
        "hardware_profile_id": predictor["hardware_profile_id"],
        "gpus": gpu_items,
        "store": document["store"],
        "network": document["network"],
    }
    expected_hardware_fingerprint = hashlib.sha256(canonical_json_bytes(hardware_shape)).hexdigest()
    if predictor["hardware_profile_fingerprint"] != expected_hardware_fingerprint:
        raise E2HarnessError(
            "assumed hardware profile fingerprint does not bind the configured resources"
        )
    artifact_set = cast(list[str], document["output"]["artifact_set"])
    if tuple(sorted(artifact_set)) != tuple(sorted(SECTION_16_ARTIFACTS)):
        raise E2HarnessError("output artifact set must equal the exact 19-file section-16 contract")
    resolve_failure_specs(config)


def _validate_topology_semantics(
    config: HarnessConfig,
    gpu_items: list[Mapping[str, Any]],
    paths: list[Mapping[str, Any]],
) -> None:
    """Require exact directional endpoint/node/NUMA/HCA config bindings."""

    network = cast(Mapping[str, Any], config.document["network"])
    if network["retry_count"] != 0:
        raise E2HarnessError("the E2 harness requires explicit retry_count zero")
    hca_items = cast(list[Mapping[str, Any]], network["hcas"])
    hcas = {cast(str, item["hca_id"]): item for item in hca_items}
    if len(hcas) != len(hca_items):
        raise E2HarnessError("HCA IDs must be unique")
    store = cast(Mapping[str, Any], config.document["store"])
    store_binding = {
        "endpoint": store["transport_endpoint"],
        "node_id": store["node_id"],
        "numa_node_id": store["numa_node_id"],
    }
    gpu_by_replica = {cast(str, item["replica_id"]): item for item in gpu_items}
    bound_hcas: set[str] = set()
    for path in paths:
        replica_id = cast(str, path["replica_id"])
        gpu = gpu_by_replica[replica_id]
        gpu_binding = {
            "endpoint": gpu["transport_endpoint"],
            "node_id": gpu["node_id"],
            "numa_node_id": gpu["numa_node_id"],
        }
        for direction, source, destination in (
            ("put", gpu_binding, store_binding),
            ("get", store_binding, gpu_binding),
        ):
            for suffix in ("endpoint", "node_id", "numa_node_id"):
                source_field = f"{direction}_source_{suffix}"
                destination_field = f"{direction}_destination_{suffix}"
                if path[source_field] != source[suffix]:
                    raise E2HarnessError(
                        f"{replica_id} {source_field} does not match its source location"
                    )
                if path[destination_field] != destination[suffix]:
                    raise E2HarnessError(
                        f"{replica_id} {destination_field} does not match its destination location"
                    )
            for side, location in (("source", source), ("destination", destination)):
                hca_id = cast(str, path[f"{direction}_{side}_hca_id"])
                bound_hcas.add(hca_id)
                try:
                    hca = hcas[hca_id]
                except KeyError as error:
                    raise E2HarnessError(
                        f"{replica_id} {direction} path names unknown HCA {hca_id}"
                    ) from error
                if (
                    hca["enabled"] is not True
                    or hca["node_id"] != location["node_id"]
                    or hca["numa_node_id"] != location["numa_node_id"]
                ):
                    raise E2HarnessError(
                        f"{replica_id} {direction} {side} HCA is not bound to its NUMA location"
                    )
    if bound_hcas != set(hcas):
        raise E2HarnessError("declared HCAs must be used by at least one exact path binding")


def _validate_transfer_resource_semantics(
    config: HarnessConfig,
    gpu_items: list[Mapping[str, Any]],
    paths: list[Mapping[str, Any]],
) -> None:
    network = cast(Mapping[str, Any], config.document["network"])
    plan = cast(Mapping[str, Any] | None, network.get("transfer_resource_plan"))
    concurrency_items = cast(
        list[Mapping[str, Any]],
        network["concurrency_resources"],
    )
    host_items = cast(
        list[Mapping[str, Any]],
        network.get("host_staging_resources", []),
    )
    binding_fields = (
        "put_source_copy_resource_id",
        "put_destination_copy_resource_id",
        "put_endpoint_qp_resource_id",
        "get_source_copy_resource_id",
        "get_destination_copy_resource_id",
        "get_endpoint_qp_resource_id",
    )
    staging_fields = (
        "put_source_host_staging_resource_id",
        "put_destination_host_staging_resource_id",
        "get_source_host_staging_resource_id",
        "get_destination_host_staging_resource_id",
    )
    endpoint_registration = cast(Mapping[str, Any], network["endpoint_registration"])
    worker_resource_id = cast(str, endpoint_registration["worker_resource_id"])
    declared_resource_ids = {
        cast(str, item["resource_id"])
        for item in (
            *cast(list[Mapping[str, Any]], network["rate_resources"]),
            *concurrency_items,
            *host_items,
        )
    }
    if worker_resource_id in declared_resource_ids:
        raise E2HarnessError("endpoint registration worker ID must not alias another resource")
    if plan is None:
        if network["transport"] != "RDMA_GDR":
            raise E2HarnessError("unplanned E2 network must retain RDMA_GDR transport")
        if concurrency_items or host_items:
            raise E2HarnessError(
                "unplanned E2 network cannot declare unused transfer resource objects"
            )
        if any(field in item for item in paths for field in (*binding_fields, *staging_fields)):
            raise E2HarnessError("unplanned E2 paths cannot bind transfer resource IDs")
        return

    concurrency_by_id = {cast(str, item["resource_id"]): item for item in concurrency_items}
    host_by_id = {cast(str, item["resource_id"]): item for item in host_items}
    if len(concurrency_by_id) != len(concurrency_items):
        raise E2HarnessError("transfer concurrency resource IDs must be unique")
    if len(host_by_id) != len(host_items):
        raise E2HarnessError("Host staging resource IDs must be unique")
    if not concurrency_by_id or not host_by_id:
        raise E2HarnessError(
            "resource-planned harness requires explicit concurrency and Host staging capacity"
        )
    gpu_by_replica = {cast(str, item["replica_id"]): item for item in gpu_items}
    store_node_id = cast(str, config.document["store"]["node_id"])
    transport = cast(str, network["transport"])

    for path in paths:
        replica_id = cast(str, path["replica_id"])
        gpu_node_id = cast(str, gpu_by_replica[replica_id]["node_id"])
        missing_bindings = [field for field in binding_fields if field not in path]
        if missing_bindings:
            raise E2HarnessError(
                f"path {replica_id} lacks transfer resource bindings: {missing_bindings}"
            )
        for field in binding_fields:
            resource_id = cast(str, path[field])
            try:
                resource = concurrency_by_id[resource_id]
            except KeyError as error:
                raise E2HarnessError(
                    f"path {replica_id} names unknown concurrency resource {resource_id}"
                ) from error
            expected_kind = "endpoint_qp_lane" if "endpoint_qp" in field else "copy_engine_lane"
            if resource["kind"] != expected_kind:
                raise E2HarnessError(f"path {field} must bind a {expected_kind} resource")
            expected_node = (
                store_node_id
                if "destination_copy" in field and field.startswith("put_")
                else store_node_id
                if "source_copy" in field and field.startswith("get_")
                else gpu_node_id
            )
            if resource["node_id"] != expected_node:
                raise E2HarnessError(
                    f"path {field} is not bound to its actual source/destination node"
                )
        for direction in ("put", "get"):
            ids = (
                cast(str, path[f"{direction}_source_copy_resource_id"]),
                cast(str, path[f"{direction}_destination_copy_resource_id"]),
                cast(str, path[f"{direction}_endpoint_qp_resource_id"]),
            )
            if len(set(ids)) != 3:
                raise E2HarnessError(
                    f"{replica_id} {direction} copy/QP bindings must be three distinct resources"
                )

        if transport == "RDMA_GDR":
            if any(field in path for field in staging_fields):
                raise E2HarnessError("RDMA_GDR paths cannot bind or charge Host staging")
            continue
        if transport != "TCP_HOST_STAGED":
            raise E2HarnessError("resource-planned transport must be RDMA_GDR or TCP_HOST_STAGED")
        missing_staging = [field for field in staging_fields if field not in path]
        if missing_staging:
            raise E2HarnessError(
                f"path {replica_id} lacks Host staging bindings: {missing_staging}"
            )
        for field in staging_fields:
            resource_id = cast(str, path[field])
            try:
                resource = host_by_id[resource_id]
            except KeyError as error:
                raise E2HarnessError(
                    f"path {replica_id} names unknown Host staging resource {resource_id}"
                ) from error
            expected_node = (
                store_node_id
                if field
                in {
                    "put_destination_host_staging_resource_id",
                    "get_source_host_staging_resource_id",
                }
                else gpu_node_id
            )
            if resource["node_id"] != expected_node:
                raise E2HarnessError(
                    f"path {field} is not bound to its actual source/destination node"
                )


def _transfer_resource_protocol_document(config: HarnessConfig) -> dict[str, object]:
    network = cast(Mapping[str, Any], config.document["network"])
    raw = {
        "transport": network["transport"],
        "retry_count": network["retry_count"],
        "hcas": network["hcas"],
        "endpoint_registration": network["endpoint_registration"],
        "transfer_resource_plan": network["transfer_resource_plan"],
        "host_staging_resources": network["host_staging_resources"],
        "concurrency_resources": network["concurrency_resources"],
        "paths": network["paths"],
    }
    return {
        "schema": "moonkvsim.vanilla-trace-e2-transfer-resource-protocol.v1",
        "parameter_source": "assumed",
        "calibration_status": "not_calibrated",
        "formal_use_allowed": False,
        "physical_timing_claim_allowed": False,
        "endpoint_registration_delay_aggregated_into_gpu_forward": False,
        "host_staging_charge_rule": ("forbidden_for_RDMA_GDR_required_for_TCP_HOST_STAGED"),
        "queue_wait_reconstruction": "lease.start_ns_minus_acquired_ns",
        "service_reconstruction": "lease_release_and_flow_interval_records",
        "abort_reconstruction": "lease_outcome_and_release_reason",
        "config": raw,
        "fingerprint": hashlib.sha256(canonical_json_bytes(raw)).hexdigest(),
        "evidence_boundary": EVIDENCE_BOUNDARY,
    }


def _build_endpoint_registration_manager(
    config: HarnessConfig,
    des: GlobalDES,
) -> EndpointRegistrationManager:
    network = cast(Mapping[str, Any], config.document["network"])
    endpoint = cast(Mapping[str, Any], network["endpoint_registration"])
    worker_resource_id = cast(str, endpoint["worker_resource_id"])
    profile = EndpointRegistrationProfile(
        worker_resource_id=worker_resource_id,
        cold_latency_ns=_sourced_int(endpoint["cold_latency_ns"]),
        warm_lookup_ns=_sourced_int(endpoint["warm_lookup_ns"]),
        endpoint_pooling=cast(bool, endpoint["endpoint_pooling"]),
    )
    manager = EndpointRegistrationManager(
        des=des,
        registration_worker=ConcurrencyResource(
            resource_id=worker_resource_id,
            lanes=_sourced_int(endpoint["worker_lanes"]),
        ),
        profile=profile,
    )
    des.journal.append(
        des.now_ns,
        "TRACE_HARNESS_ENDPOINT_REGISTRATION_CONFIGURED",
        {
            "worker_resource_id": worker_resource_id,
            "worker_lanes": _sourced_int(endpoint["worker_lanes"]),
            "cold_latency_ns": profile.cold_latency_ns,
            "warm_lookup_ns": profile.warm_lookup_ns,
            "endpoint_pooling": profile.endpoint_pooling,
            "parameter_source": endpoint["parameter_source"],
            "calibration_status": endpoint["calibration_status"],
            "formal_use_allowed": endpoint["formal_use_allowed"],
            "aggregated_into_gpu_forward": False,
            "fidelity_gaps": [
                "physical_registration_and_qp_handshake_are_not_executed",
                "latencies_are_assumed_not_calibrated",
            ],
        },
    )
    return manager


def _build_transfer_resource_components(
    config: HarnessConfig,
    des: GlobalDES,
) -> tuple[
    TransferResourceLeaseManager | None,
    AssumedTransferResourcePlanProvider | None,
]:
    network = cast(Mapping[str, Any], config.document["network"])
    plan = cast(Mapping[str, Any] | None, network.get("transfer_resource_plan"))
    if plan is None:
        return None, None
    host_items = cast(
        list[Mapping[str, Any]],
        network["host_staging_resources"],
    )
    concurrency_items = cast(
        list[Mapping[str, Any]],
        network["concurrency_resources"],
    )
    host_ledgers = {
        cast(str, item["resource_id"]): CapacityLedger(
            resource_id=cast(str, item["resource_id"]),
            resource_kind=CapacityResourceKind.HOST_DRAM,
            capacity_bytes=_sourced_int(item["capacity_bytes"]),
        )
        for item in host_items
    }
    concurrency_resources = {
        cast(str, item["resource_id"]): ConcurrencyResource(
            resource_id=cast(str, item["resource_id"]),
            lanes=_sourced_int(item["lanes"]),
        )
        for item in concurrency_items
    }
    manager = TransferResourceLeaseManager(
        des=des,
        capacity_ledgers=host_ledgers,
        concurrency_resources=concurrency_resources,
    )
    fingerprint_input = {
        "transport": network["transport"],
        "plan": plan,
        "host_staging_resources": host_items,
        "concurrency_resources": concurrency_items,
        "paths": network["paths"],
    }
    provider = AssumedTransferResourcePlanProvider(
        duration_ns=_sourced_int(plan["duration_ns"]),
        latest_start_slack_ns=_sourced_int(plan["latest_start_slack_ns"]),
        staging_alignment_bytes=_sourced_int(plan["staging_alignment_bytes"]),
        staging_allocator_metadata_bytes=_sourced_int(plan["staging_allocator_metadata_bytes"]),
        known_staging_resource_ids=frozenset(host_ledgers),
        known_concurrency_resource_ids=frozenset(concurrency_resources),
        parameter_fingerprint=hashlib.sha256(canonical_json_bytes(fingerprint_input)).hexdigest(),
    )
    des.journal.append(
        des.now_ns,
        "TRACE_HARNESS_TRANSFER_RESOURCE_PROTOCOL_CONFIGURED",
        {
            **provider.to_dict(),
            "transport": network["transport"],
            "host_staging_capacity_declared": True,
            "host_staging_charged_for_gdr": False,
            "queue_wait_service_abort_reconstructable": True,
        },
    )
    return manager, provider


def _build_runner(config: HarnessConfig) -> tuple[VanillaBaselineTraceRunner, str]:
    document = config.document
    target = cast(Mapping[str, Any], document["target"])
    scheduler_config = cast(Mapping[str, Any], document["scheduler"])
    deployment = cast(Mapping[str, Any], document["deployment"])
    store_config = cast(Mapping[str, Any], document["store"])
    network = cast(Mapping[str, Any], document["network"])
    layout_path = _repository_file(config, cast(str, target["kv_layout_path"]))
    layout = _load_stage_layout(layout_path)
    if layout.block_size_tokens != scheduler_config["block_size_tokens"]:
        raise E2HarnessError("scheduler block size diverges from the pinned KV layout")

    blocks_per_source_block = SOURCE_BLOCK_SIZE_TOKENS // layout.block_size_tokens
    if blocks_per_source_block * layout.block_size_tokens != SOURCE_BLOCK_SIZE_TOKENS:
        raise E2HarnessError("source trace blocks are not divisible by scheduler blocks")
    store_payload = _sourced_int(store_config["payload_bytes_per_source_block"])
    expected_store_payload = blocks_per_source_block * layout.payload_bytes
    if store_payload != expected_store_payload:
        raise E2HarnessError(
            "Store payload/source block diverges from the target KV layout: "
            f"expected {expected_store_payload}, configured {store_payload}"
        )

    des = GlobalDES()
    endpoint_registration_manager = _build_endpoint_registration_manager(config, des)
    transfer_resource_manager, transfer_plan_provider = _build_transfer_resource_components(
        config, des
    )
    configured_failures = resolve_failure_specs(config)
    if configured_failures:
        des.journal.append(
            des.now_ns,
            "TRACE_HARNESS_FAILURE_PROTOCOL_CONFIGURED",
            _failure_protocol_document(config, configured_failures),
        )
    registry = AllocationRegistry(journal=des.journal)
    master = MasterService(
        allocation_strategy=RandomAllocationStrategy(seed=cast(int, deployment["seed"])),
        journal=des.journal,
        allocation_registry=registry,
    )
    segment_id = cast(str, store_config["segment_id"])
    segment_capacity = _sourced_int(store_config["capacity_bytes"])
    master.mount_segment(
        Segment(
            segment_id=segment_id,
            name=segment_id,
            node_id=cast(str, store_config["node_id"]),
            numa_node_id=cast(str, store_config["numa_node_id"]),
            transport_endpoint=cast(str, store_config["transport_endpoint"]),
            capacity_bytes=segment_capacity,
            allocation_alignment_bytes=_sourced_int(store_config["allocation_alignment_bytes"]),
            allocator_metadata_bytes=_sourced_int(store_config["allocator_metadata_bytes"]),
        ),
        CapacityLedger(
            resource_id=segment_id,
            resource_kind=CapacityResourceKind.STORE_DRAM,
            capacity_bytes=segment_capacity,
        ),
        timestamp_ns=0,
    )

    rates = [
        RateResource(
            cast(str, item["resource_id"]),
            float(_sourced_int(item["capacity_bytes_per_second"])),
        )
        for item in cast(list[Mapping[str, Any]], network["rate_resources"])
    ]
    transfer_runtime = TransferRuntime(
        controller=FlowDESController(des=des, model=FlowContentionModel(rates))
    )
    path_by_replica = {
        cast(str, item["replica_id"]): item
        for item in cast(list[Mapping[str, Any]], network["paths"])
    }
    runtime_items: list[BaselineReplicaRuntime] = []
    bindings: dict[str, TraceReplicaBinding] = {}
    physical_gpus: list[PhysicalGPU] = []
    engine_targets: list[EngineTarget] = []
    hbm_ledgers: dict[str, CapacityLedger] = {}
    hbm_observers: list[HbmBlockLedgerBridge] = []
    slice_size = _sourced_int(network["slice_size_bytes"])

    def current_ns() -> int:
        return des.now_ns

    for gpu_config in cast(list[Mapping[str, Any]], deployment["gpus"]):
        replica_id = cast(str, gpu_config["replica_id"])
        gpu_id = cast(str, gpu_config["gpu_id"])
        node_id = cast(str, gpu_config["node_id"])
        numa_node_id = cast(str, gpu_config["numa_node_id"])
        hbm_resource_id = cast(str, gpu_config["hbm_resource_id"])
        physical_capacity = _sourced_int(gpu_config["physical_capacity_bytes"])
        fixed_weights = _sourced_int(gpu_config["fixed_weights_bytes"])
        fixed_runtime = _sourced_int(gpu_config["fixed_runtime_bytes"])
        ledger = CapacityLedger(
            resource_id=hbm_resource_id,
            resource_kind=CapacityResourceKind.GPU_HBM,
            capacity_bytes=physical_capacity,
            initial_accounts={
                MODEL_WEIGHTS_ACCOUNT: fixed_weights,
                RUNTIME_FIXED_ACCOUNT: fixed_runtime,
                RUNTIME_DYNAMIC_ACCOUNT: 0,
            },
        )
        hbm_ledgers[hbm_resource_id] = ledger
        bridge = HbmBlockLedgerBridge(
            bridge_id=f"e2-harness:{replica_id}:hbm-bridge",
            bindings=(HbmStageRankBinding(hbm_resource_id, layout),),
            ledgers={hbm_resource_id: ledger},
            registry=registry,
            journal=des.journal,
            now_ns=current_ns,
        )
        usable_blocks = bridge.num_free_blocks
        scheduler = ContinuousBatchScheduler(
            block_pool=BlockPool(usable_blocks + 1, enable_caching=False),
            block_size_tokens=cast(int, scheduler_config["block_size_tokens"]),
            max_num_scheduled_tokens=cast(int, scheduler_config["max_num_scheduled_tokens"]),
            max_num_running_requests=cast(int, scheduler_config["max_num_running_requests"]),
            block_lifecycle_observer=bridge,
        )
        path_config = path_by_replica[replica_id]
        transport = TransportKind(cast(str, network["transport"]))
        if transfer_plan_provider is None:
            put_concurrency_resource_ids: tuple[str, ...] = ()
            get_concurrency_resource_ids: tuple[str, ...] = ()
            put_source_staging_id = None
            put_destination_staging_id = None
            get_source_staging_id = None
            get_destination_staging_id = None
        else:
            put_concurrency_resource_ids = (
                cast(str, path_config["put_source_copy_resource_id"]),
                cast(str, path_config["put_destination_copy_resource_id"]),
                cast(str, path_config["put_endpoint_qp_resource_id"]),
            )
            get_concurrency_resource_ids = (
                cast(str, path_config["get_source_copy_resource_id"]),
                cast(str, path_config["get_destination_copy_resource_id"]),
                cast(str, path_config["get_endpoint_qp_resource_id"]),
            )
            put_source_staging_id = cast(
                str | None,
                path_config.get("put_source_host_staging_resource_id"),
            )
            put_destination_staging_id = cast(
                str | None,
                path_config.get("put_destination_host_staging_resource_id"),
            )
            get_source_staging_id = cast(
                str | None,
                path_config.get("get_source_host_staging_resource_id"),
            )
            get_destination_staging_id = cast(
                str | None,
                path_config.get("get_destination_host_staging_resource_id"),
            )
        topology = Topology(
            [
                TopologyPath(
                    path_id=cast(str, path_config["put_path_id"]),
                    source_kind=MemoryKind.GPU_HBM,
                    destination_kind=MemoryKind.STORE_DRAM,
                    transport=transport,
                    rate_resource_ids=tuple(cast(list[str], path_config["put_rate_resource_ids"])),
                    concurrency_resource_ids=put_concurrency_resource_ids,
                    source_endpoint=cast(str, path_config["put_source_endpoint"]),
                    destination_endpoint=cast(str, path_config["put_destination_endpoint"]),
                    source_node_id=cast(str, path_config["put_source_node_id"]),
                    destination_node_id=cast(str, path_config["put_destination_node_id"]),
                    source_numa_node_id=cast(str, path_config["put_source_numa_node_id"]),
                    destination_numa_node_id=cast(str, path_config["put_destination_numa_node_id"]),
                    source_hca_id=cast(str, path_config["put_source_hca_id"]),
                    destination_hca_id=cast(str, path_config["put_destination_hca_id"]),
                    preference=PathPreference(cast(str, path_config["put_preference"])),
                    priority=cast(int, path_config["put_priority"]),
                    source_host_staging_resource_id=put_source_staging_id,
                    destination_host_staging_resource_id=(put_destination_staging_id),
                ),
                TopologyPath(
                    path_id=cast(str, path_config["get_path_id"]),
                    source_kind=MemoryKind.STORE_DRAM,
                    destination_kind=MemoryKind.GPU_HBM,
                    transport=transport,
                    rate_resource_ids=tuple(cast(list[str], path_config["get_rate_resource_ids"])),
                    concurrency_resource_ids=get_concurrency_resource_ids,
                    source_endpoint=cast(str, path_config["get_source_endpoint"]),
                    destination_endpoint=cast(str, path_config["get_destination_endpoint"]),
                    source_node_id=cast(str, path_config["get_source_node_id"]),
                    destination_node_id=cast(str, path_config["get_destination_node_id"]),
                    source_numa_node_id=cast(str, path_config["get_source_numa_node_id"]),
                    destination_numa_node_id=cast(str, path_config["get_destination_numa_node_id"]),
                    source_hca_id=cast(str, path_config["get_source_hca_id"]),
                    destination_hca_id=cast(str, path_config["get_destination_hca_id"]),
                    preference=PathPreference(cast(str, path_config["get_preference"])),
                    priority=cast(int, path_config["get_priority"]),
                    source_host_staging_resource_id=get_source_staging_id,
                    destination_host_staging_resource_id=(get_destination_staging_id),
                ),
            ]
        )
        local_gpu = MemoryLocation(
            resource_id=hbm_resource_id,
            node_id=node_id,
            numa_node_id=numa_node_id,
            kind=MemoryKind.GPU_HBM,
            endpoint=cast(str, gpu_config["transport_endpoint"]),
            gpu_id=gpu_id,
        )
        client = StoreClient(
            client_id=f"e2-harness:{replica_id}:store-client",
            master=master,
            topology=topology,
            local_gpu=local_gpu,
            registered_at_ns=0,
            slice_size_bytes=slice_size,
        )
        runtime = BaselineReplicaRuntime(
            replica_id=replica_id,
            dp_rank=cast(int, gpu_config["dp_rank"]),
            scheduler_id=cast(str, gpu_config["scheduler_id"]),
            gpu_id=gpu_id,
            scheduler=scheduler,
            store_client=client,
        )
        runtime_items.append(runtime)
        bindings[replica_id] = TraceReplicaBinding(runtime, bridge)
        hbm_observers.append(bridge)
        physical_gpus.append(PhysicalGPU(gpu_id, node_id, (hbm_resource_id,)))
        engine_targets.append(
            EngineTarget(
                replica_id,
                cast(int, gpu_config["dp_rank"]),
                (gpu_id,),
                cast(str, deployment["compatibility_fingerprint"]),
            )
        )

    coordinator = BaselineCoordinator(
        des=des,
        router=DPRouter(
            router_id="e2-real-trace-round-robin",
            policy=RoutePolicy.ROUND_ROBIN,
        ),
        replicas=runtime_items,
        master=master,
        transfer_runtime=transfer_runtime,
        transfer_resource_manager=transfer_resource_manager,
        endpoint_registration_manager=endpoint_registration_manager,
        gpus=physical_gpus,
        targets=engine_targets,
        hbm_ledgers=hbm_ledgers,
        hbm_failure_observers=hbm_observers,
    )
    predictor, mixed_phase_rule, parameter_sha256 = _build_assumed_predictor(config)
    runner = VanillaBaselineTraceRunner(
        coordinator=coordinator,
        replicas=bindings,
        predictor=predictor,
        mixed_phase_composition_rule=mixed_phase_rule,
        transfer_resource_plan_provider=transfer_plan_provider,
        config=TraceRunnerConfig(
            tenant_id="weka-real-trace-e2",
            target_model_id=cast(str, target["model_id"]),
            target_model_revision=cast(str, target["model_revision"]),
            kv_dtype=cast(str, target["kv_dtype"]),
            kv_abi=cast(str, target["kv_abi"]),
            kv_layout=cast(str, target["kv_layout_id"]),
            tensor_parallel_size=cast(int, target["tensor_parallel_size"]),
            pipeline_parallel_size=cast(int, target["pipeline_parallel_size"]),
            store_payload_bytes_per_source_block=store_payload,
            store_payload_byte_basis=STORE_PAYLOAD_BYTE_BASIS,
            preferred_store_segment_ids=(segment_id,),
        ),
    )
    return runner, parameter_sha256


def _build_assumed_predictor(
    config: HarnessConfig,
) -> tuple[
    ForwardPredictor,
    AssumedIntegerMixedPhaseCompositionRule,
    str,
]:
    predictor_config = cast(Mapping[str, Any], config.document["predictor"])
    target = cast(Mapping[str, Any], config.document["target"])
    formula_config = cast(Mapping[str, Any], predictor_config["formula"])
    formula = {
        field_name: _sourced_int(value) for field_name, value in sorted(formula_config.items())
    }
    parameter_document = {
        "schema": "moonkvsim.assumed-integer-shape-formula.v1",
        "parameter_source": "assumed",
        "calibration_status": "not_calibrated",
        "formal_use_allowed": False,
        "formula": formula,
        "mixed_phase_composition": predictor_config["mixed_phase_composition"],
    }
    parameter_sha256 = hashlib.sha256(canonical_json_bytes(parameter_document)).hexdigest()
    compatibility = cast(Mapping[str, Any], predictor_config["profile_api_compatibility"])
    profile = PredictionProfile(
        provider_name=cast(str, predictor_config["provider_name"]),
        provider_version=cast(str, predictor_config["provider_version"]),
        provider_source_revision=cast(str, compatibility["provider_source_revision"]),
        database_mode=("assumed_parameter_artifact_not_predictor_or_calibration_database"),
        # PredictionProfile v1 requires this field.  It binds the real canonical
        # assumed-parameter artifact above; run-audit keeps predictor DB null.
        database_sha256=parameter_sha256,
        hardware_profile_id=cast(str, predictor_config["hardware_profile_id"]),
        hardware_profile_fingerprint=cast(str, predictor_config["hardware_profile_fingerprint"]),
        model_id=cast(str, target["model_id"]),
        model_revision=cast(str, target["model_revision"]),
        tensor_parallel_size=cast(int, target["tensor_parallel_size"]),
        pipeline_parallel_size=cast(int, target["pipeline_parallel_size"]),
        forward_boundary=ForwardBoundary(includes_model_collectives=False),
    )
    provider = AssumedIntegerShapeProvider(profile.provider_name, formula)
    mixed_phase_rule = AssumedIntegerMixedPhaseCompositionRule(
        parameter_fingerprint=parameter_sha256,
        base_ns=formula["base_ns"],
        batch_request_overhead_ns=formula["batch_request_overhead_ns"],
        prefill_ns_per_scheduled_token=formula["prefill_ns_per_scheduled_token"],
        decode_ns_per_request=formula["decode_ns_per_request"],
        decode_ns_per_past_token=formula["decode_ns_per_past_token"],
    )
    return (
        ForwardPredictor(
            profile=profile,
            evidence=CalibrationEvidence.preliminary(profile.fingerprint),
            provider=provider,
        ),
        mixed_phase_rule,
        parameter_sha256,
    )


def capture_semantic_source_snapshot(
    config: HarnessConfig,
) -> SemanticSourceSnapshot:
    """Capture a self-consistent semantic file and Git provenance snapshot."""

    git_before = _git_snapshot(config.repository_root)
    files_first = _semantic_file_manifest(config)
    files_second = _semantic_file_manifest(config)
    git_after = _git_snapshot(config.repository_root)
    if files_first != files_second or git_before != git_after:
        raise E2HarnessError("repository changed while capturing the semantic source snapshot")

    repository_entries = [item for item in files_first if item["scope"] == "repository"]
    external_entries = [item for item in files_first if item["scope"] == "external"]
    tracked = cast(frozenset[str], git_before["tracked_paths"])
    tracked_count = sum(cast(str, item["path"]) in tracked for item in repository_entries)
    head_commit = cast(str | None, git_before["head_commit"])
    worktree_clean = cast(bool, git_before["worktree_clean"])
    freeze_blockers: list[str] = []
    if head_commit is None:
        freeze_blockers.append("unborn_git_head")
    if not worktree_clean:
        freeze_blockers.append("dirty_git_worktree")
    if external_entries:
        freeze_blockers.append("external_semantic_source_not_git_tracked")
    if tracked_count != len(repository_entries):
        freeze_blockers.append("repository_semantic_source_not_git_tracked")
    source_frozen = not freeze_blockers
    frozen_reason = (
        "clean_head_and_all_semantic_sources_git_tracked"
        if source_frozen
        else ",".join(freeze_blockers)
    )

    semantic_files_sha256 = hashlib.sha256(canonical_json_bytes(files_first)).hexdigest()
    return SemanticSourceSnapshot(
        repository_root=str(config.repository_root),
        git_branch=cast(str | None, git_before["branch"]),
        git_head_state="unborn" if head_commit is None else "resolved",
        git_head_commit=head_commit,
        git_head_tree=cast(str | None, git_before["head_tree"]),
        git_porcelain_sha256=cast(str, git_before["porcelain_sha256"]),
        git_porcelain_entry_count=cast(int, git_before["porcelain_entry_count"]),
        git_worktree_clean=worktree_clean,
        semantic_files=tuple(files_first),
        semantic_files_sha256=semantic_files_sha256,
        repository_semantic_file_count=len(repository_entries),
        tracked_repository_semantic_file_count=tracked_count,
        source_frozen=source_frozen,
        source_freeze_blockers=tuple(freeze_blockers),
        source_frozen_reason=frozen_reason,
    )


def _semantic_file_manifest(config: HarnessConfig) -> list[dict[str, object]]:
    roles_by_path: dict[Path, set[str]] = {}

    def add(path: Path, role: str) -> None:
        candidate = Path(path)
        if candidate.is_symlink():
            raise E2HarnessError(f"semantic source must not be a symlink: {candidate}")
        resolved = candidate.resolve()
        roles_by_path.setdefault(resolved, set()).add(role)

    python_root = config.repository_root / "python/moonkvsim"
    for path in sorted(python_root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".pyi"}:
            add(path, "python/moonkvsim-source")
    if config.failure_enabled:
        add(
            config.repository_root / "scripts/run_vanilla_failure_trace_e2.py",
            "selected-cli",
        )
    else:
        add(config.repository_root / "scripts/run_vanilla_trace_e2.py", "selected-cli")
    for path in sorted((config.repository_root / "schemas").glob("*.json")):
        if path.is_file():
            add(path, "json-schema")
    add(config.path, "selected-harness-config")
    target = cast(Mapping[str, Any], config.document["target"])
    add(
        _repository_file(config, cast(str, target["kv_layout_path"])),
        "selected-kv-layout",
    )
    for name in ("pyproject.toml", "uv.lock"):
        dependency_path = config.repository_root / name
        if dependency_path.is_file():
            add(dependency_path, "dependency-contract")

    result: list[dict[str, object]] = []
    for path, roles in sorted(roles_by_path.items(), key=lambda item: str(item[0])):
        if path.is_symlink() or not path.is_file():
            raise E2HarnessError(f"semantic source is missing or a symlink: {path}")
        try:
            relative = path.relative_to(config.repository_root).as_posix()
        except ValueError:
            scope = "external"
            display_path = str(path)
        else:
            scope = "repository"
            display_path = relative
        try:
            size_bytes = path.stat().st_size
            digest = _sha256_file(path)
        except OSError as error:
            raise E2HarnessError(f"cannot hash semantic source {path}: {error}") from error
        result.append(
            {
                "path": display_path,
                "scope": scope,
                "roles": sorted(roles),
                "size_bytes": size_bytes,
                "sha256": digest,
            }
        )
    if not result:
        raise E2HarnessError("semantic source manifest is empty")
    return sorted(result, key=lambda item: (cast(str, item["scope"]), cast(str, item["path"])))


def _git_snapshot(repository_root: Path) -> dict[str, object]:
    inside = _run_git(repository_root, "rev-parse", "--is-inside-work-tree")
    if inside != b"true\n":
        raise E2HarnessError("repository root is not a Git worktree")
    branch_result = _run_git(
        repository_root,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        allow_failure=True,
    )
    branch = branch_result.decode().strip() or None
    head_raw = _run_git(
        repository_root,
        "rev-parse",
        "--verify",
        "HEAD",
        allow_failure=True,
    )
    head_commit = head_raw.decode().strip() or None
    if head_commit is not None and re.fullmatch(r"[0-9a-f]{40,64}", head_commit) is None:
        raise E2HarnessError("Git returned an invalid HEAD object ID")
    head_tree: str | None = None
    if head_commit is not None:
        head_tree = (
            _run_git(
                repository_root,
                "rev-parse",
                "--verify",
                "HEAD^{tree}",
            )
            .decode()
            .strip()
        )
        if re.fullmatch(r"[0-9a-f]{40,64}", head_tree) is None:
            raise E2HarnessError("Git returned an invalid HEAD tree object ID")
    porcelain = _run_git(
        repository_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    tracked_raw = _run_git(repository_root, "ls-files", "-z")
    tracked_paths = frozenset(os.fsdecode(item) for item in tracked_raw.split(b"\0") if item)
    return {
        "branch": branch,
        "head_commit": head_commit,
        "head_tree": head_tree,
        "porcelain_sha256": hashlib.sha256(porcelain).hexdigest(),
        "porcelain_entry_count": len(porcelain.splitlines()),
        "worktree_clean": not porcelain,
        "tracked_paths": tracked_paths,
    }


def _run_git(
    repository_root: Path,
    *arguments: str,
    allow_failure: bool = False,
) -> bytes:
    try:
        completed = subprocess.run(
            ("git", "--no-optional-locks", *arguments),
            cwd=repository_root,
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise E2HarnessError(f"cannot execute Git for source provenance: {error}") from error
    if completed.returncode and not allow_failure:
        detail = completed.stderr.decode(errors="replace").strip()
        raise E2HarnessError(
            f"Git source-provenance command failed ({' '.join(arguments)}): {detail}"
        )
    if completed.returncode and allow_failure:
        return b""
    return completed.stdout


def _load_stage_layout(path: Path) -> StageBlockLayout:
    document = json.loads(path.read_bytes())
    if not isinstance(document, dict) or document.get("schema") != "moonkvsim.kv_layout.v1":
        raise E2HarnessError("target KV layout has the wrong schema")
    layouts = document.get("stage_rank_layouts")
    if not isinstance(layouts, list) or len(layouts) != 1:
        raise E2HarnessError("E2 harness currently requires exactly one TP1/PP1 layout")
    item = layouts[0]
    if not isinstance(item, dict) or not isinstance(item.get("block"), dict):
        raise E2HarnessError("target KV layout stage has no block document")
    block = dict(item["block"])
    fingerprint = block.pop("fingerprint", None)
    outer_stage = item.get("pp_stage")
    outer_rank = item.get("tensor_parallel_rank")
    if block.get("pp_stage") != outer_stage or block.get("tensor_parallel_rank") != outer_rank:
        raise E2HarnessError("outer and block stage/rank coordinates diverge")
    block["layer_names"] = tuple(block.get("layer_names", ()))
    block["layer_indices"] = tuple(block.get("layer_indices", ()))
    try:
        layout = StageBlockLayout(**cast(dict[str, Any], block))
    except (KeyError, TypeError, ValueError) as error:
        raise E2HarnessError(f"invalid target stage block layout: {error}") from error
    if layout.fingerprint != fingerprint:
        raise E2HarnessError("target stage block layout fingerprint mismatch")
    return layout


def _validate_output_target(
    config: HarnessConfig,
    requested: Path,
) -> tuple[Path, str]:
    if not Path(requested).is_absolute():
        raise E2HarnessError("output directory must be absolute")
    output = Path(requested).resolve(strict=False)
    required_prefix = cast(str, config.document["output"]["required_path_prefix"])
    if os.path.commonpath((str(output), required_prefix.rstrip("/"))) != required_prefix.rstrip(
        "/"
    ) or output == Path(required_prefix):
        raise E2HarnessError(f"output directory must be below {required_prefix}")
    if output.exists() or output.is_symlink():
        raise E2HarnessError("output target already exists; no-clobber policy rejects it")
    ancestor = output.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    if ancestor.is_symlink() or not ancestor.is_dir():
        raise E2HarnessError("output ancestor must be a real directory")
    filesystem_type = _filesystem_type(ancestor)
    forbidden = set(cast(list[str], config.document["output"]["forbidden_filesystem_types"]))
    if filesystem_type in forbidden:
        raise E2HarnessError(
            f"output filesystem {filesystem_type!r} lacks the required local no-clobber boundary"
        )
    return output, filesystem_type


def _filesystem_type(path: Path) -> str:
    """Resolve Linux mountinfo using the longest matching real mount point."""

    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise E2HarnessError(f"cannot prove output filesystem type: {error}") from error
    target = str(path.resolve())
    matches: list[tuple[int, str]] = []
    for line in lines:
        left, separator, right = line.partition(" - ")
        if not separator:
            raise E2HarnessError("malformed /proc/self/mountinfo record")
        left_fields = left.split()
        right_fields = right.split()
        if len(left_fields) < 5 or not right_fields:
            raise E2HarnessError("malformed /proc/self/mountinfo fields")
        mount_point = _MOUNT_ESCAPE_RE.sub(
            lambda match: chr(int(match.group(1), 8)),
            left_fields[4],
        )
        if target == mount_point or target.startswith(mount_point.rstrip("/") + "/"):
            matches.append((len(mount_point), right_fields[0]))
    if not matches:
        raise E2HarnessError(f"cannot identify filesystem containing {target}")
    return max(matches)[1]


def _repository_file(config: HarnessConfig, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        raise E2HarnessError("repository artifact paths must be relative")
    candidate = config.repository_root / path
    if candidate.is_symlink():
        raise E2HarnessError(f"repository artifact is a symlink: {relative_path}")
    resolved = candidate.resolve()
    if os.path.commonpath((str(resolved), str(config.repository_root))) != str(
        config.repository_root
    ):
        raise E2HarnessError("repository artifact path escapes the repository")
    if not resolved.is_file():
        raise E2HarnessError(f"repository artifact is missing: {relative_path}")
    return resolved


def _sourced_int(value: object) -> int:
    if not isinstance(value, dict):
        raise E2HarnessError("sourced integer must be an object")
    result = value.get("value")
    if isinstance(result, bool) or not isinstance(result, int) or result < 0:
        raise E2HarnessError("sourced integer value is invalid")
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    value = digest.hexdigest()
    if _SHA256_RE.fullmatch(value) is None:
        raise AssertionError("hashlib returned an invalid SHA-256")
    return value
