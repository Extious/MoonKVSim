#!/usr/bin/env python3
"""Run the exact 160-workflow AegisKV paper-figure sweep protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Any, Final, cast

from moonkvsim.aegiskv.experiment import (
    CellSpec,
    ExperimentError,
    ExperimentVariant,
    FailureEventSchedule,
    FailureImpactContract,
    FailureSchedule,
    Scenario,
    core_variants,
    derive_failure_schedule,
    failure_workload_progress_targets_per_mille,
    project_failure_schedule_to_profile,
    run_study_cell,
)
from moonkvsim.aegiskv.experiment_config import (
    default_config_dir,
    load_experiment_configs,
    matrix_seeds,
    model_parameters_from_configs,
    repository_root,
    workload_paths,
)
from moonkvsim.aegiskv.experiment_suite import load_frozen_workload
from moonkvsim.aegiskv.formal_algorithm_audit import (
    CONTINUOUS_SCHEDULER_AUDIT_SCHEMA,
    FORMAL_ALGORITHM_AUDIT_SCHEMA,
    FormalAlgorithmAuditError,
    audit_continuous_scheduler_evidence,
    audit_formal_algorithm_run,
)
from moonkvsim.aegiskv.paper_artifacts import write_raw_evidence
from moonkvsim.aegiskv.paper_sweep_statistics import (
    MINIMUM_SEED_COUNT,
    build_paper_sweep_statistics,
)
from moonkvsim.common.hash import sha256_json

SCHEMA: Final = "moonkvsim.aegiskv.paper_sweeps.v4"
FAILURE_COUNTS: Final = (1, 2, 4, 8)
WORKFLOW_CONCURRENCIES: Final = (8, 16, 24, 32)
BASE_FAILURE_COUNT: Final = 2
BASE_CONCURRENCY: Final = 16
AEGISKV_VARIANT_ID: Final = "aegiskv_unified"
DEFAULT_SEEDS: Final = (0, 1, 2, 3, 4)
REPETITIONS: Final = ("A",)
CHECKPOINT_SCHEMA: Final = "moonkvsim.aegiskv.paper_sweeps.checkpoint-contract.v4"
RUN_CHECKPOINT_SCHEMA: Final = "moonkvsim.aegiskv.paper_sweeps.run-checkpoint.v4"
CANONICAL_PLAN_CHECKPOINT_SCHEMA: Final = (
    "moonkvsim.aegiskv.paper_sweeps.canonical-plan-checkpoint.v3"
)
FAILURE_SCHEMA: Final = "moonkvsim.aegiskv.paper_sweeps.failure.v1"
CANONICAL_FAILURE_COUNT: Final = 8
CANONICAL_CONCURRENCIES: Final = WORKFLOW_CONCURRENCIES
CANONICAL_NESTED_EVENT_INDICES: Final = {
    1: (2,),
    2: (2, 5),
    4: (1, 2, 5, 6),
    8: tuple(range(8)),
}
PROCESS_ABORT_JOIN_TIMEOUT_SECONDS: Final = 0.05
SOURCE_RELATIVE_PATHS: Final = (
    "benchmark/AegisKV/experiments/scripts/run_aegiskv_paper_sweeps.py",
    "python/moonkvsim/aegiskv/experiment.py",
    "python/moonkvsim/aegiskv/experiment_config.py",
    "python/moonkvsim/aegiskv/experiment_statistics.py",
    "python/moonkvsim/aegiskv/experiment_hbm_authority.py",
    "python/moonkvsim/aegiskv/experiment_suite.py",
    "python/moonkvsim/aegiskv/continuous_batch_des.py",
    "python/moonkvsim/aegiskv/formal_algorithm_audit.py",
    "python/moonkvsim/aegiskv/hbm_quota_aimd.py",
    "python/moonkvsim/aegiskv/ideal_trace_cpm.py",
    "python/moonkvsim/aegiskv/lazy_refresh.py",
    "python/moonkvsim/aegiskv/paper_sweep_statistics.py",
    "python/moonkvsim/aegiskv/paper_randomization.py",
    "python/moonkvsim/aegiskv/paper_artifacts.py",
    "python/moonkvsim/aegiskv/recovery_harm.py",
    "python/moonkvsim/aegiskv/rental_value.py",
    "python/moonkvsim/aegiskv/slack_landlord.py",
    "python/moonkvsim/aegiskv/scheduler_step_bridge.py",
    "python/moonkvsim/aegiskv/types.py",
    "python/moonkvsim/integration/vllm/block_pool.py",
    "python/moonkvsim/integration/vllm/hbm_block_ledger.py",
    "python/moonkvsim/integration/vllm/request.py",
    "python/moonkvsim/integration/vllm/scheduler.py",
    "python/moonkvsim/simulation/event.py",
    "python/moonkvsim/simulation/flow_des.py",
    "python/moonkvsim/simulation/global_des.py",
    "python/moonkvsim/simulation/ledger.py",
    "python/moonkvsim/simulation/network.py",
    "python/moonkvsim/simulation/resource.py",
    "python/moonkvsim/simulation/transaction.py",
    "python/moonkvsim/store/transfer_engine.py",
    "python/moonkvsim/store/transfer_runtime.py",
    "python/moonkvsim/workload/causal_replay.py",
    "python/moonkvsim/workload/causal_trace.py",
)

_WORKER_RECORDS: Sequence[Mapping[str, Any]] | None = None
_WORKER_VARIANTS: tuple[ExperimentVariant, ExperimentVariant] | None = None
_WORKER_BUCKET: str | None = None


class PaperSweepWorkerError(ExperimentError):
    """A worker failure bound to the exact canonical-plan or cell task."""

    def __init__(self, *, task_context: Mapping[str, object], error: Exception) -> None:
        if not task_context:
            raise ValueError("paper sweep worker task context must be non-empty")
        self.task_context = dict(task_context)
        super().__init__(
            "paper sweep worker failed "
            f"({_task_context_label(self.task_context)}): {error}"
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=repository_root(),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source_bindings(root: Path) -> dict[str, dict[str, str]]:
    return {
        relative: {
            "path": (root / relative).as_posix(),
            "sha256": _sha256_file(root / relative),
        }
        for relative in SOURCE_RELATIVE_PATHS
    }


def _cell_id(failure_count: int, concurrency: int, seed: int | None = None) -> str:
    base = f"failure-{failure_count}:concurrency-{concurrency}"
    return base if seed is None else f"{base}:seed-{seed}"


def _checkpoint_path(checkpoint_dir: Path, task: tuple[int, int, int, str]) -> Path:
    failure_count, concurrency, seed, variant_id = task
    return checkpoint_dir / (
        f"failure-{failure_count}_concurrency-{concurrency}_seed-{seed}_{variant_id}.json"
    )


def _canonical_plan_checkpoint_path(
    checkpoint_dir: Path,
    seed: int,
    concurrency: int,
) -> Path:
    return checkpoint_dir / (
        f"canonical_failure_plan_concurrency-{concurrency}_seed-{seed}.json"
    )


def _variant_task_binding(
    task: tuple[int, int, int, str],
    *,
    logical_plan_fingerprint: str,
) -> dict[str, object]:
    failure_count, concurrency, seed, variant_id = task
    return {
        "kind": "variant_run",
        "failure_count": failure_count,
        "workflow_concurrency": concurrency,
        "seed": seed,
        "variant_id": variant_id,
        "logical_plan_fingerprint": logical_plan_fingerprint,
    }


def _canonical_plan_task_binding(seed: int, concurrency: int) -> dict[str, object]:
    if concurrency not in CANONICAL_CONCURRENCIES:
        raise ValueError(f"unsupported canonical-plan concurrency: {concurrency}")
    return {
        "kind": "canonical_failure_plan",
        "failure_count": _canonical_plan_failure_count(concurrency),
        "workflow_concurrency": concurrency,
        "seed": seed,
        "variant_id": "vanilla_mooncake_dram",
    }


def _cell_task_binding(
    failure_count: int,
    concurrency: int,
    seed: int,
    variant_ids: Sequence[str],
) -> dict[str, object]:
    if not variant_ids:
        raise ValueError("cell task must bind at least one variant")
    return {
        "kind": "variant_cell",
        "failure_count": failure_count,
        "workflow_concurrency": concurrency,
        "seed": seed,
        "variant_ids": list(variant_ids),
    }


def _task_context_label(task_context: Mapping[str, object]) -> str:
    kind = task_context.get("kind")
    if kind == "canonical_failure_plan":
        return (
            f"canonical-plan seed={task_context.get('seed')} "
            f"concurrency={task_context.get('workflow_concurrency')}"
        )
    if kind == "variant_cell":
        raw_variant_ids = task_context.get("variant_ids")
        variants = (
            ",".join(str(item) for item in raw_variant_ids)
            if isinstance(raw_variant_ids, Sequence)
            and not isinstance(raw_variant_ids, (str, bytes))
            else str(raw_variant_ids)
        )
        return (
            f"cell F={task_context.get('failure_count')} "
            f"C={task_context.get('workflow_concurrency')} "
            f"seed={task_context.get('seed')} variants={variants}"
        )
    return json.dumps(dict(task_context), sort_keys=True, separators=(",", ":"))


def _canonical_plan_failure_count(concurrency: int) -> int:
    if concurrency not in CANONICAL_CONCURRENCIES:
        raise ValueError(f"unsupported canonical-plan concurrency: {concurrency}")
    return CANONICAL_FAILURE_COUNT if concurrency == BASE_CONCURRENCY else BASE_FAILURE_COUNT


def _canonical_plan_supported_failure_counts(concurrency: int) -> tuple[int, ...]:
    return FAILURE_COUNTS if concurrency == BASE_CONCURRENCY else (BASE_FAILURE_COUNT,)


def _bound_checkpoint_document(
    *,
    schema: str,
    task: Mapping[str, object],
    content: Mapping[str, Any],
    contract_fingerprint: str,
    source_contract_sha256: str,
) -> dict[str, Any]:
    content_sha256 = sha256_json(content)
    body: dict[str, Any] = {
        "schema": schema,
        "task": dict(task),
        "contract_fingerprint": contract_fingerprint,
        "source_contract_sha256": source_contract_sha256,
        "content_sha256": content_sha256,
        "content": dict(content),
    }
    return {**body, "fingerprint": sha256_json(body)}


def _validated_checkpoint_content(
    document: object,
    *,
    schema: str,
    task: Mapping[str, object],
    contract_fingerprint: str,
    source_contract_sha256: str,
) -> tuple[dict[str, Any], dict[str, object]]:
    if not isinstance(document, Mapping):
        raise ValueError("checkpoint must be a JSON object")
    expected_keys = {
        "schema",
        "task",
        "contract_fingerprint",
        "source_contract_sha256",
        "content_sha256",
        "content",
        "fingerprint",
    }
    if set(document) != expected_keys:
        raise ValueError("checkpoint fields do not match the bound schema")
    if document.get("schema") != schema:
        raise ValueError("checkpoint schema mismatch")
    if document.get("task") != task:
        raise ValueError("checkpoint task binding mismatch")
    if document.get("contract_fingerprint") != contract_fingerprint:
        raise ValueError("checkpoint contract fingerprint mismatch")
    if document.get("source_contract_sha256") != source_contract_sha256:
        raise ValueError("checkpoint source contract mismatch")
    content = document.get("content")
    if not isinstance(content, Mapping):
        raise ValueError("checkpoint content must be a JSON object")
    canonical_content = dict(content)
    content_sha256 = sha256_json(canonical_content)
    if document.get("content_sha256") != content_sha256:
        raise ValueError("checkpoint content hash mismatch")
    body = {key: document[key] for key in expected_keys - {"fingerprint"}}
    if document.get("fingerprint") != sha256_json(body):
        raise ValueError("checkpoint envelope fingerprint mismatch")
    binding = {
        "schema": schema,
        "task": dict(task),
        "contract_fingerprint": contract_fingerprint,
        "source_contract_sha256": source_contract_sha256,
        "content_sha256": content_sha256,
        "checkpoint_fingerprint": document["fingerprint"],
    }
    return canonical_content, binding


def _required_mapping(
    value: object,
    *,
    path: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return cast(Mapping[str, Any], value)


def _required_text(value: object, *, path: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _required_integer(value: object, *, path: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{path} must be an integer >= {minimum}")
    return value


def _failure_schedule_from_dict(value: object) -> FailureSchedule:
    raw = _required_mapping(value, path="failure_schedule")
    raw_events = raw.get("events")
    if not isinstance(raw_events, list) or not raw_events:
        raise ValueError("failure_schedule.events must be a non-empty array")
    events = []
    def impact(value: object) -> FailureImpactContract | None:
        if value is None:
            return None
        raw_impact = _required_mapping(value, path="failure impact")
        contract = FailureImpactContract(
            active_span_ids=tuple(raw_impact["active_span_ids"]),
            queued_span_ids=tuple(raw_impact["queued_span_ids"]),
            reroute_only_queued_span_ids=tuple(raw_impact["reroute_only_queued_span_ids"]),
        )
        if contract.to_dict() != raw_impact:
            raise ValueError("noncanonical failure impact contract")
        return contract

    for index, raw_event_value in enumerate(raw_events):
        path = f"failure_schedule.events[{index}]"
        raw_event = _required_mapping(raw_event_value, path=path)
        position = _required_mapping(
            raw_event.get("workload_position"),
            path=f"{path}.workload_position",
        )
        trigger = _required_mapping(raw_event.get("trigger"), path=f"{path}.trigger")
        repair_after_ns = raw_event.get("repair_after_ns")
        if repair_after_ns is not None:
            repair_after_ns = _required_integer(
                repair_after_ns,
                path=f"{path}.repair_after_ns",
                minimum=1,
            )
        events.append(
            FailureEventSchedule(
                failure_id=_required_text(
                    raw_event.get("failure_id"), path=f"{path}.failure_id"
                ),
                event_index=_required_integer(
                    raw_event.get("event_index"), path=f"{path}.event_index"
                ),
                bucket=_required_text(raw_event.get("bucket"), path=f"{path}.bucket"),
                seed=_required_integer(raw_event.get("seed"), path=f"{path}.seed"),
                focus_span_id=_required_text(
                    raw_event.get("focus_span_id"), path=f"{path}.focus_span_id"
                ),
                target_gpu_id=_required_text(
                    raw_event.get("target_gpu_id"), path=f"{path}.target_gpu_id"
                ),
                reference_at_ns=_required_integer(
                    raw_event.get("reference_at_ns"), path=f"{path}.reference_at_ns"
                ),
                target_workload_progress_per_mille=_required_integer(
                    position.get("target_progress_per_mille"),
                    path=f"{path}.workload_position.target_progress_per_mille",
                    minimum=1,
                ),
                reference_completed_workflow_count=_required_integer(
                    position.get("reference_completed_workflow_count"),
                    path=f"{path}.workload_position.reference_completed_workflow_count",
                ),
                reference_workflow_count=_required_integer(
                    position.get("reference_workflow_count"),
                    path=f"{path}.workload_position.reference_workflow_count",
                    minimum=1,
                ),
                detection_delay_ns=_required_integer(
                    raw_event.get("detection_delay_ns"),
                    path=f"{path}.detection_delay_ns",
                ),
                trigger_progress_per_mille=_required_integer(
                    trigger.get("progress_per_mille"),
                    path=f"{path}.trigger.progress_per_mille",
                    minimum=1,
                ),
                gpu_recovery_time_ns=repair_after_ns,
                physical_target_frozen=(
                    raw_event.get("target_gpu_id_semantics") == "FROZEN_PHYSICAL_FAILURE_TARGET"
                ),
                impact_contract=impact(raw_event.get("impact_contract")),
                profile_impact_contracts=(
                    None
                    if raw_event.get("profile_impact_contracts") is None
                    else {
                        key: cast(FailureImpactContract, impact(item))
                        for key, item in _required_mapping(
                            raw_event["profile_impact_contracts"], path="profile impacts"
                        ).items()
                    }
                ),
                selection_scope=_required_text(
                    raw_event.get("selection_scope"), path=f"{path}.selection_scope"
                ),
            )
        )
    schedule = FailureSchedule(
        tuple(events),
        selection_scope=_required_text(
            raw.get("selection_scope"), path="failure_schedule.selection_scope"
        ),
    )
    if schedule.to_dict() != dict(raw):
        raise ValueError("failure schedule is not in canonical serialized form")
    return schedule


def _canonical_schedule_for_failure_count(
    canonical_schedule: FailureSchedule,
    failure_count: int,
) -> FailureSchedule:
    canonical_failure_count = len(canonical_schedule.events)
    if canonical_failure_count == BASE_FAILURE_COUNT:
        if failure_count != BASE_FAILURE_COUNT:
            raise ValueError("direct F2 canonical plan only supports failure_count=2")
        if tuple(
            event.target_workload_progress_per_mille
            for event in canonical_schedule.events
        ) != failure_workload_progress_targets_per_mille(BASE_FAILURE_COUNT):
            raise ValueError("direct F2 canonical plan must remain at 33% and 67%")
        if not any(
            event.physical_target_frozen
            or event.impact_contract is not None
            or event.profile_impact_contracts is not None
            for event in canonical_schedule.events
        ):
            return canonical_schedule
        return FailureSchedule(
            tuple(
                replace(
                    event,
                    physical_target_frozen=False,
                    impact_contract=None,
                    profile_impact_contracts=None,
                    selection_scope="sensitivity_logical_focus_natural_routing",
                )
                for event in canonical_schedule.events
            ),
            selection_scope="sensitivity_logical_focus_natural_routing",
        )
    if canonical_failure_count != CANONICAL_FAILURE_COUNT:
        raise ValueError("canonical failure plan must contain exactly two or eight events")
    expected_targets = failure_workload_progress_targets_per_mille(
        CANONICAL_FAILURE_COUNT
    )
    if tuple(
        event.target_workload_progress_per_mille
        for event in canonical_schedule.events
    ) != expected_targets:
        raise ValueError("canonical failure plan has unexpected workload targets")
    try:
        selected_indices = CANONICAL_NESTED_EVENT_INDICES[failure_count]
    except KeyError as error:
        raise ValueError(f"unsupported paper failure count: {failure_count}") from error
    selected = tuple(
        replace(
            canonical_schedule.events[canonical_index],
            event_index=event_index,
            physical_target_frozen=False,
            impact_contract=None,
            profile_impact_contracts=None,
            selection_scope="canonical_nested_within_concurrency_logical_focus",
        )
        for event_index, canonical_index in enumerate(selected_indices)
    )
    schedule = FailureSchedule(
        selected,
        selection_scope="canonical_nested_within_concurrency_logical_focus_plan",
    )
    if failure_count == BASE_FAILURE_COUNT and tuple(
        event.target_workload_progress_per_mille for event in schedule.events
    ) != (333, 667):
        raise ValueError("base F2 canonical plan must remain at 33% and 67%")
    return schedule


def _logical_schedule_identity(
    schedule: FailureSchedule,
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            event.failure_id,
            event.event_index,
            event.bucket,
            event.seed,
            event.focus_span_id,
            event.target_workload_progress_per_mille,
            event.trigger_progress_per_mille,
        )
        for event in schedule.events
    )


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _abort_process_pool(executor: Any, futures: Sequence[Any]) -> None:
    """Best-effort immediate shutdown that never masks the triggering error."""

    for future in futures:
        with suppress(Exception):
            future.cancel()
    raw_processes = executor._processes
    processes = () if raw_processes is None else tuple(raw_processes.values())
    for process in processes:
        with suppress(Exception):
            if process.is_alive():
                process.terminate()
    for process in processes:
        with suppress(Exception):
            process.join(timeout=PROCESS_ABORT_JOIN_TIMEOUT_SECONDS)
    for process in processes:
        with suppress(Exception):
            if process.is_alive():
                process.kill()
    for process in processes:
        with suppress(Exception):
            process.join(timeout=PROCESS_ABORT_JOIN_TIMEOUT_SECONDS)
    with suppress(Exception):
        executor.shutdown(wait=False, cancel_futures=True)


def _future_result_with_context(
    future: Any,
    *,
    task_context: Mapping[str, object],
) -> Any:
    if not task_context:
        raise ValueError("future failure task context must be non-empty")
    try:
        return future.result()
    except Exception as error:
        raise PaperSweepWorkerError(
            task_context=task_context,
            error=error,
        ) from error


def _qualified_exception_type(error: BaseException) -> str:
    error_type = type(error)
    return f"{error_type.__module__}.{error_type.__qualname__}"


def _exception_chain(error: BaseException) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    current: BaseException | None = error
    relation = "raised"
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(
            {
                "relation": relation,
                "type": _qualified_exception_type(current),
                "message": str(current),
            }
        )
        if current.__cause__ is not None:
            current = current.__cause__
            relation = "cause"
        elif current.__context__ is not None and not current.__suppress_context__:
            current = current.__context__
            relation = "context"
        else:
            current = None
    return chain


def _failure_document(
    *,
    output_dir: Path,
    error: BaseException,
    task_context: Mapping[str, object] | None,
    source_contract_sha256: str | None,
    checkpoint_contract_fingerprint: str | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": FAILURE_SCHEMA,
        "status": "FAIL",
        "output_dir": output_dir.as_posix(),
        "task_context": (
            {"kind": "runner"} if task_context is None else dict(task_context)
        ),
        "exception": {
            "type": _qualified_exception_type(error),
            "message": str(error),
            "chain": _exception_chain(error),
            "traceback": "".join(
                traceback.TracebackException.from_exception(error).format(chain=True)
            ),
        },
        "source_contract_sha256": source_contract_sha256,
        "checkpoint_contract_fingerprint": checkpoint_contract_fingerprint,
        "paper_ready": False,
    }
    return {**body, "fingerprint": sha256_json(body)}


def _write_failure_artifact(
    *,
    output_dir: Path,
    error: BaseException,
    task_context: Mapping[str, object] | None,
    source_contract_sha256: str | None,
    checkpoint_contract_fingerprint: str | None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=False)
    failure_path = output_dir / "FAILURE.json"
    _write_json_atomic(
        failure_path,
        _failure_document(
            output_dir=output_dir,
            error=error,
            task_context=task_context,
            source_contract_sha256=source_contract_sha256,
            checkpoint_contract_fingerprint=checkpoint_contract_fingerprint,
        ),
    )
    return failure_path


def _formal_algorithm_report(
    variant: ExperimentVariant,
    *,
    payload: Mapping[str, object],
    representative: Mapping[str, object],
    failure_count: int,
    concurrency: int,
    repetition: str,
) -> dict[str, object] | None:
    """Gate every AegisKV paper run; Mooncake has no formal Algorithm 2/3 path."""

    if variant.variant_id != AEGISKV_VARIANT_ID:
        return None
    try:
        return audit_formal_algorithm_run(payload, representative).to_dict()
    except FormalAlgorithmAuditError as error:
        raise ExperimentError(
            "AegisKV formal Algorithm 2/3 paper gate rejected "
            f"failure_count={failure_count}, concurrency={concurrency}, "
            f"repetition={repetition}: {error}"
        ) from error


def _continuous_scheduler_report(
    *,
    payload: Mapping[str, object],
    representative: Mapping[str, object],
    variant_id: str,
    failure_count: int,
    concurrency: int,
    repetition: str,
) -> dict[str, object]:
    """Reconstruct scheduler/request/WCT/HBM evidence for both systems."""

    try:
        return audit_continuous_scheduler_evidence(payload, representative).to_dict()
    except FormalAlgorithmAuditError as error:
        raise ExperimentError(
            "continuous scheduler paper gate rejected "
            f"variant={variant_id}, failure_count={failure_count}, "
            f"concurrency={concurrency}, repetition={repetition}: {error}"
        ) from error


def _require_continuous_batch_paper_capability(
    payload: Mapping[str, object],
    *,
    variant_id: str,
    failure_count: int,
    concurrency: int,
    repetition: str,
) -> None:
    """Fail closed until the study payload proves end-to-end batch residency."""

    raw_metrics = payload.get("metrics")
    policy_effects = raw_metrics.get("policy_effects") if isinstance(raw_metrics, Mapping) else None
    if (
        not isinstance(policy_effects, Mapping)
        or policy_effects.get("continuous_batch_residency_modeled") is not True
        or policy_effects.get("compute_scheduler_model") != "VLLM_CONTINUOUS_BATCH_SCHEDULER_STEP"
    ):
        raise ExperimentError(
            "paper sweep BLOCKED: continuous scheduler-step residency is not "
            "wired end-to-end "
            f"variant={variant_id}, failure_count={failure_count}, "
            f"concurrency={concurrency}, repetition={repetition}"
        )


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_compact_system(
    system_value: object,
    *,
    task: tuple[int, int, int, str],
    expected_variant_fingerprint: str,
    logical_schedule: FailureSchedule,
) -> None:
    """Re-run every paper gate supported by a compact variant checkpoint."""

    failure_count, concurrency, seed, variant_id = task
    system = _required_mapping(system_value, path="compact.system")
    if system.get("variant_id") != variant_id:
        raise ValueError("compact checkpoint variant mismatch")
    if system.get("variant_fingerprint") != expected_variant_fingerprint:
        raise ValueError("compact checkpoint variant fingerprint mismatch")
    schedule = _failure_schedule_from_dict(system.get("failure_schedule"))
    if system.get("failure_schedule_fingerprint") != schedule.fingerprint:
        raise ValueError("compact checkpoint schedule fingerprint mismatch")
    if _logical_schedule_identity(schedule) != _logical_schedule_identity(
        logical_schedule
    ):
        raise ValueError("compact checkpoint diverges from the canonical logical plan")
    if schedule.seed != seed or len(schedule.events) != failure_count:
        raise ValueError("compact checkpoint schedule task dimensions mismatch")

    run = _required_mapping(system.get("run"), path="compact.system.run")
    if run.get("repetition") != REPETITIONS[0]:
        raise ValueError("compact checkpoint repetition mismatch")
    for field in (
        "payload_sha256",
        "journal_sha256",
        "span_details_sha256",
        "representative_sha256",
    ):
        if not _is_sha256(run.get(field)):
            raise ValueError(f"compact checkpoint {field} is not a SHA-256 digest")
    workload = _required_mapping(run.get("workload"), path="compact.system.run.workload")
    if workload.get("workflow_count") != 160:
        raise ExperimentError("checkpoint paper run did not execute exactly 160 workflows")
    metrics = _required_mapping(run.get("metrics"), path="compact.system.run.metrics")
    workflow_wct = _required_mapping(
        _required_mapping(
            metrics.get("workflow_completion_time_ns"),
            path="compact.system.run.metrics.workflow_completion_time_ns",
        ).get("by_workflow_id"),
        path=(
            "compact.system.run.metrics.workflow_completion_time_ns.by_workflow_id"
        ),
    )
    if len(workflow_wct) != 160:
        raise ExperimentError(
            "checkpoint paper run WCT map must contain exactly 160 workflows"
        )
    failure_impact = _required_mapping(
        metrics.get("failure_impact"), path="compact.system.run.metrics.failure_impact"
    )
    if failure_impact.get("failure_event_count") != failure_count:
        raise ExperimentError("checkpoint paper run did not execute every planned failure")
    active_requests = failure_impact.get("active_requests")
    if type(active_requests) is not int or active_requests < failure_count:
        raise ExperimentError("checkpoint planned failure did not impact an active request")
    recovery = _required_mapping(
        metrics.get("gpu_capacity_recovery"),
        path="compact.system.run.metrics.gpu_capacity_recovery",
    )
    if recovery.get("scheduled_count") != failure_count:
        raise ExperimentError("checkpoint paper run did not schedule every planned repair")
    if recovery.get("completed_count") != failure_count:
        raise ExperimentError("checkpoint paper run did not complete every planned repair")
    _require_continuous_batch_paper_capability(
        {"metrics": metrics},
        variant_id=variant_id,
        failure_count=failure_count,
        concurrency=concurrency,
        repetition=REPETITIONS[0],
    )
    policy_effects = _required_mapping(
        metrics.get("policy_effects"),
        path="compact.system.run.metrics.policy_effects",
    )
    algorithm1 = _required_mapping(
        policy_effects.get("algorithm1"),
        path="compact.system.run.metrics.policy_effects.algorithm1",
    )
    if (
        algorithm1.get("algorithm") != "ideal_trace_exact_dag_cpm_v1"
        or algorithm1.get("duration_source") != "trace.recorded_api_time_ns"
        or algorithm1.get("predictor_used") is not False
        or algorithm1.get("prediction_error_modeled") is not False
        or algorithm1.get("absolute_observed_finish_used") is not False
        or algorithm1.get("failure_location_used") is not False
    ):
        raise ExperimentError("checkpoint paper run did not use ideal-trace exact CPM slack")
    focus_spans = run.get("failure_focus_spans")
    if not isinstance(focus_spans, list):
        raise ValueError("compact checkpoint failure focus spans are malformed")
    focus_ids = {event.focus_span_id for event in logical_schedule.events}
    checkpoint_focus_ids = {
        str(detail.get("span_id"))
        for detail in focus_spans
        if isinstance(detail, Mapping)
    }
    if checkpoint_focus_ids != focus_ids:
        raise ExperimentError("checkpoint scheduled focus span was not failure-impacted")
    formal_report = run.get("formal_algorithm_audit")
    scheduler_report = _required_mapping(
        run.get("continuous_scheduler_audit"),
        path="compact.system.run.continuous_scheduler_audit",
    )
    if (
        scheduler_report.get("schema") != CONTINUOUS_SCHEDULER_AUDIT_SCHEMA
        or scheduler_report.get("status") != "PASS"
    ):
        raise ExperimentError("checkpoint continuous scheduler report did not pass")
    scheduler_fingerprint = scheduler_report.get("fingerprint")
    canonical_scheduler_report = dict(scheduler_report)
    canonical_scheduler_report.pop("fingerprint", None)
    if (
        not _is_sha256(scheduler_fingerprint)
        or scheduler_fingerprint != sha256_json(canonical_scheduler_report)
    ):
        raise ValueError("checkpoint continuous scheduler report hash mismatch")
    if variant_id == AEGISKV_VARIANT_ID:
        report = _required_mapping(
            formal_report,
            path="compact.system.run.formal_algorithm_audit",
        )
        if (
            report.get("schema") != FORMAL_ALGORITHM_AUDIT_SCHEMA
            or report.get("status") != "PASS"
        ):
            raise ExperimentError("checkpoint formal Algorithm 2/3 report did not pass")
        fingerprint = report.get("fingerprint")
        canonical_report = dict(report)
        canonical_report.pop("fingerprint", None)
        if not _is_sha256(fingerprint) or fingerprint != sha256_json(canonical_report):
            raise ValueError("checkpoint formal Algorithm 2/3 report hash mismatch")
    elif formal_report is not None:
        raise ValueError("Mooncake compact checkpoint must not claim a formal audit")


def _selected_route_prefix_tokens(route: Mapping[str, object], *, field: str) -> int:
    """Read a route-bound prefix without borrowing another GPU's KV."""

    selected_gpu_id = route.get("selected_gpu_id")
    prefixes = route.get(field)
    if type(selected_gpu_id) is not str or not isinstance(prefixes, Mapping):
        raise ExperimentError("recovery route prefix index is malformed")
    value = prefixes.get(selected_gpu_id)
    if type(value) is not int or value < 0:
        raise ExperimentError("selected recovery route has no valid tier prefix")
    return value


def _run_variant(
    variant: ExperimentVariant,
    *,
    schedule: FailureSchedule,
    failure_count: int,
    concurrency: int,
    seed: int,
    raw_path: Path | None = None,
) -> dict[str, Any]:
    if _WORKER_RECORDS is None or _WORKER_BUCKET is None:
        raise RuntimeError("paper-sweep worker was not initialized")
    runs = []
    for repetition in REPETITIONS:
        result = run_study_cell(
            _WORKER_RECORDS,
            CellSpec(
                variant=variant,
                context_bucket=_WORKER_BUCKET,
                scenario=Scenario.GPU_FAILURE,
                seed=seed,
                repetition=repetition,
                failure_schedule=schedule,
                workflow_concurrency=concurrency,
                workflow_admission_seed=seed,
                peer_binding_seed=0,
            ),
        )
        raw_binding = None
        if raw_path is not None:
            raw_binding = write_raw_evidence(
                raw_path,
                {
                    "schema": "moonkvsim.aegiskv.paper_raw_run.v1",
                    "variant": variant.to_dict(),
                    "payload": result.payload,
                    "span_details": result.span_details,
                    "representative": result.representative,
                    "journal_sha256": result.journal_sha256,
                },
            )
        _require_continuous_batch_paper_capability(
            result.payload,
            variant_id=variant.variant_id,
            failure_count=failure_count,
            concurrency=concurrency,
            repetition=repetition,
        )
        continuous_scheduler_audit = _continuous_scheduler_report(
            payload=result.payload,
            representative=result.representative,
            variant_id=variant.variant_id,
            failure_count=failure_count,
            concurrency=concurrency,
            repetition=repetition,
        )
        metrics = result.payload["metrics"]
        if result.payload["workload"]["workflow_count"] != 160:
            raise ExperimentError("paper sweep did not execute exactly 160 workflows")
        if metrics["failure_impact"]["failure_event_count"] != failure_count:
            raise ExperimentError("paper sweep did not execute every planned failure")
        if metrics["failure_impact"]["active_requests"] < failure_count:
            raise ExperimentError("a planned failure did not impact an active request")
        if metrics["gpu_capacity_recovery"]["scheduled_count"] != failure_count:
            raise ExperimentError("paper sweep did not schedule every planned repair")
        if metrics["gpu_capacity_recovery"]["completed_count"] != failure_count:
            raise ExperimentError("paper sweep did not complete every planned repair")
        recovery_routes = {
            str(route["span_id"]): route
            for route in result.representative["route_events"]
            if int(route["route_version"]) > 0
        }
        all_impacted = [
            {
                **{
                    key: detail[key]
                    for key in (
                        "span_id",
                        "workflow_id",
                        "gpu_id",
                        "failure_at_ns",
                        "recovery_ready_ns",
                        "reused_primary_tokens",
                        "reused_peer_tokens",
                        "reused_store_tokens",
                        "recovery_normal_hbm_local_tokens",
                        "restored_peer_tokens",
                        "restored_peer_local_tokens",
                        "restored_peer_d2d_tokens",
                        "restored_store_tokens",
                        "recompute_tokens",
                    )
                },
                "available_peer_tokens_at_failure": _selected_route_prefix_tokens(
                    recovery_routes[str(detail["span_id"])],
                    field="peer_prefix_tokens_by_gpu",
                ),
                "available_normal_hbm_tokens_at_failure": _selected_route_prefix_tokens(
                    recovery_routes[str(detail["span_id"])],
                    field="normal_hbm_prefix_tokens_by_gpu",
                ),
                "available_store_tokens_at_failure": int(
                    recovery_routes[str(detail["span_id"])]["store_prefix_tokens"]
                ),
            }
            for detail in result.span_details
            if detail["failure_at_ns"] is not None
        ]
        focus_ids = {event.focus_span_id for event in schedule.events}
        focus_impacted = [detail for detail in all_impacted if detail["span_id"] in focus_ids]
        if {detail["span_id"] for detail in focus_impacted} != focus_ids:
            raise ExperimentError("a scheduled focus span was not failure-impacted")
        algorithm1 = metrics["policy_effects"]["algorithm1"]
        if (
            algorithm1.get("algorithm") != "ideal_trace_exact_dag_cpm_v1"
            or algorithm1.get("duration_source") != "trace.recorded_api_time_ns"
            or algorithm1.get("predictor_used") is not False
            or algorithm1.get("prediction_error_modeled") is not False
            or algorithm1.get("absolute_observed_finish_used") is not False
            or algorithm1.get("failure_location_used") is not False
        ):
            raise ExperimentError("paper sweep did not use ideal-trace exact CPM slack")
        formal_algorithm_audit = _formal_algorithm_report(
            variant,
            payload=result.payload,
            representative=result.representative,
            failure_count=failure_count,
            concurrency=concurrency,
            repetition=repetition,
        )
        runs.append(
            {
                "repetition": repetition,
                "raw_evidence": raw_binding,
                "payload_sha256": result.payload_sha256,
                "journal_sha256": result.journal_sha256,
                "span_details_sha256": sha256_json(result.span_details),
                "representative_sha256": sha256_json(result.representative),
                "workflow_admission": result.payload["workflow_admission"],
                "randomization": result.payload["randomization"],
                "workload": {
                    "workflow_count": result.payload["workload"]["workflow_count"],
                },
                "metrics": {
                    "workload_end_ns": metrics["workload_end_ns"],
                    "workflow_completion_time_ns": metrics["workflow_completion_time_ns"],
                    "restored_tokens": metrics["restored_tokens"],
                    "restored_peer_transport_tokens": metrics["restored_peer_transport_tokens"],
                    "failure_cache_reuse_tokens": metrics["failure_cache_reuse_tokens"],
                    "failure_effective_prefix_tokens": metrics["failure_effective_prefix_tokens"],
                    "recompute_tokens_after_failure": metrics["recompute_tokens_after_failure"],
                    "cache_reuse_tokens": metrics["cache_reuse_tokens"],
                    "recovery_latency_ns": metrics["recovery_latency_ns"],
                    "failure_impact": metrics["failure_impact"],
                    "gpu_capacity_recovery": metrics["gpu_capacity_recovery"],
                    "policy_effects": metrics["policy_effects"],
                    "resource_cost": metrics["resource_cost"],
                },
                "failure_focus_spans": focus_impacted,
                "failure_impacted_spans": all_impacted,
                "aimd_events": result.representative["aimd_events"],
                "continuous_scheduler_audit": continuous_scheduler_audit,
                "formal_algorithm_audit": formal_algorithm_audit,
            }
        )
    first = runs[0]
    return {
        "variant_id": variant.variant_id,
        "variant_fingerprint": variant.fingerprint,
        "failure_schedule": schedule.to_dict(),
        "failure_schedule_fingerprint": schedule.fingerprint,
        "run": first,
        "repeat_b_hashes": None,
        "fresh_repeat_determinism": (
            "NOT_REPEATED; deterministic kernel covered by regression tests"
        ),
    }


def _worker_canonical_plan(
    seed: int,
    concurrency: int,
    *,
    checkpoint_dir: Path,
    contract_fingerprint: str,
    source_contract_sha256: str,
) -> dict[str, Any]:
    if _WORKER_RECORDS is None or _WORKER_VARIANTS is None or _WORKER_BUCKET is None:
        raise RuntimeError("paper-sweep worker was not initialized")
    reference_variant = next(
        item for item in _WORKER_VARIANTS if item.variant_id == "vanilla_mooncake_dram"
    )
    compared_profiles = tuple(item.profile for item in _WORKER_VARIANTS)
    schedule = derive_failure_schedule(
        _WORKER_RECORDS,
        bucket=_WORKER_BUCKET,
        seed=seed,
        parameters=reference_variant.parameters,
        workflow_concurrency=concurrency,
        workflow_admission_seed=seed,
        peer_binding_seed=0,
        failure_count=_canonical_plan_failure_count(concurrency),
        compared_profiles=compared_profiles,
        freeze_post_treatment_impact_contracts=False,
    )
    supported_failure_counts = _canonical_plan_supported_failure_counts(concurrency)
    _canonical_schedule_for_failure_count(schedule, supported_failure_counts[-1])
    content = {
        "seed": seed,
        "workflow_concurrency": concurrency,
        "canonical_failure_count": len(schedule.events),
        "schedule": schedule.to_dict(),
        "schedule_fingerprint": schedule.fingerprint,
        "logical_focus_span_ids": [event.focus_span_id for event in schedule.events],
        "focus_span_ids_by_failure_count": {
            str(failure_count): [
                event.focus_span_id
                for event in _canonical_schedule_for_failure_count(
                    schedule, failure_count
                ).events
            ]
            for failure_count in supported_failure_counts
        },
        "targets_per_mille_by_failure_count": {
            str(failure_count): [
                event.target_workload_progress_per_mille
                for event in _canonical_schedule_for_failure_count(
                    schedule, failure_count
                ).events
            ]
            for failure_count in supported_failure_counts
        },
    }
    document = _bound_checkpoint_document(
        schema=CANONICAL_PLAN_CHECKPOINT_SCHEMA,
        task=_canonical_plan_task_binding(seed, concurrency),
        content=content,
        contract_fingerprint=contract_fingerprint,
        source_contract_sha256=source_contract_sha256,
    )
    _write_json_atomic(
        _canonical_plan_checkpoint_path(checkpoint_dir, seed, concurrency),
        document,
    )
    return document


def _worker_cell(
    task: tuple[int, int, int, tuple[str, ...]],
    logical_schedule: FailureSchedule,
    checkpoint_dir: Path,
    contract_fingerprint: str,
    source_contract_sha256: str,
) -> list[dict[str, Any]]:
    failure_count, concurrency, seed, variant_ids = task
    if _WORKER_RECORDS is None or _WORKER_VARIANTS is None or _WORKER_BUCKET is None:
        raise RuntimeError("paper-sweep worker was not initialized")
    variants_by_id = {item.variant_id: item for item in _WORKER_VARIANTS}
    if not variant_ids or len(set(variant_ids)) != len(variant_ids):
        raise ValueError("paper-sweep cell task must contain unique pending variants")
    unknown_variant_ids = set(variant_ids) - set(variants_by_id)
    if unknown_variant_ids:
        raise ValueError(
            "paper-sweep cell task contains unknown variants: "
            f"{sorted(unknown_variant_ids)}"
        )
    if logical_schedule.seed != seed or len(logical_schedule.events) != failure_count:
        raise ValueError("paper-sweep worker received the wrong canonical logical plan")
    results = []
    for variant_id in variant_ids:
        variant = variants_by_id[variant_id]
        schedule = project_failure_schedule_to_profile(
            _WORKER_RECORDS,
            reference=logical_schedule,
            profile=variant.profile,
            parameters=variant.parameters,
            workflow_concurrency=concurrency,
            seed=seed,
        )
        if _logical_schedule_identity(schedule) != _logical_schedule_identity(
            logical_schedule
        ):
            raise ExperimentError("runtime-resolved schedule changed the canonical logical plan")
        result = {
            "failure_count": failure_count,
            "workflow_concurrency": concurrency,
            "seed": seed,
            "variant_id": variant.variant_id,
            "system": _run_variant(
                variant,
                schedule=schedule,
                failure_count=failure_count,
                concurrency=concurrency,
                seed=seed,
                raw_path=_checkpoint_path(
                    checkpoint_dir, (failure_count, concurrency, seed, variant.variant_id)
                ).with_suffix(".raw.json.gz"),
            ),
        }
        variant_task = (failure_count, concurrency, seed, variant.variant_id)
        _validate_compact_system(
            result["system"],
            task=variant_task,
            expected_variant_fingerprint=variant.fingerprint,
            logical_schedule=logical_schedule,
        )
        document = _bound_checkpoint_document(
            schema=RUN_CHECKPOINT_SCHEMA,
            task=_variant_task_binding(
                variant_task,
                logical_plan_fingerprint=logical_schedule.fingerprint,
            ),
            content=result,
            contract_fingerprint=contract_fingerprint,
            source_contract_sha256=source_contract_sha256,
        )
        _write_json_atomic(
            _checkpoint_path(checkpoint_dir, variant_task),
            document,
        )
        results.append(document)
    return results


def _group_variant_tasks_by_cell(
    tasks: Sequence[tuple[int, int, int, str]],
) -> list[tuple[int, int, int, tuple[str, ...]]]:
    """Group only pending variants while preserving variant checkpoint granularity."""

    grouped: dict[tuple[int, int, int], list[str]] = {}
    for failure_count, concurrency, seed, variant_id in tasks:
        key = (failure_count, concurrency, seed)
        variants = grouped.setdefault(key, [])
        if variant_id in variants:
            raise ValueError(f"duplicate paper-sweep task: {(*key, variant_id)}")
        variants.append(variant_id)
    return [(*key, tuple(variant_ids)) for key, variant_ids in grouped.items()]


def _validated_canonical_plan_checkpoint(
    document: object,
    *,
    seed: int,
    concurrency: int,
    contract_fingerprint: str,
    source_contract_sha256: str,
) -> tuple[FailureSchedule, dict[str, object], dict[str, Any]]:
    content, binding = _validated_checkpoint_content(
        document,
        schema=CANONICAL_PLAN_CHECKPOINT_SCHEMA,
        task=_canonical_plan_task_binding(seed, concurrency),
        contract_fingerprint=contract_fingerprint,
        source_contract_sha256=source_contract_sha256,
    )
    expected_keys = {
        "seed",
        "workflow_concurrency",
        "canonical_failure_count",
        "schedule",
        "schedule_fingerprint",
        "logical_focus_span_ids",
        "focus_span_ids_by_failure_count",
        "targets_per_mille_by_failure_count",
    }
    if (
        set(content) != expected_keys
        or content.get("seed") != seed
        or content.get("workflow_concurrency") != concurrency
        or content.get("canonical_failure_count")
        != _canonical_plan_failure_count(concurrency)
    ):
        raise ValueError("canonical failure plan checkpoint content is malformed")
    schedule = _failure_schedule_from_dict(content.get("schedule"))
    if schedule.seed != seed or content.get("schedule_fingerprint") != schedule.fingerprint:
        raise ValueError("canonical failure plan schedule binding mismatch")
    supported_failure_counts = _canonical_plan_supported_failure_counts(concurrency)
    _canonical_schedule_for_failure_count(schedule, supported_failure_counts[-1])
    expected_focus_ids = [event.focus_span_id for event in schedule.events]
    if content.get("logical_focus_span_ids") != expected_focus_ids:
        raise ValueError("canonical failure plan focus ID summary mismatch")
    expected_focus = {
        str(failure_count): [
            event.focus_span_id
            for event in _canonical_schedule_for_failure_count(
                schedule, failure_count
            ).events
        ]
        for failure_count in supported_failure_counts
    }
    expected_targets = {
        str(failure_count): [
            event.target_workload_progress_per_mille
            for event in _canonical_schedule_for_failure_count(
                schedule, failure_count
            ).events
        ]
        for failure_count in supported_failure_counts
    }
    if content.get("focus_span_ids_by_failure_count") != expected_focus:
        raise ValueError("canonical failure plan focus summary mismatch")
    if content.get("targets_per_mille_by_failure_count") != expected_targets:
        raise ValueError("canonical failure plan target summary mismatch")
    return schedule, {**binding, "schedule_fingerprint": schedule.fingerprint}, content


def _validated_run_checkpoint(
    document: object,
    *,
    task: tuple[int, int, int, str],
    contract_fingerprint: str,
    source_contract_sha256: str,
    expected_variant_fingerprint: str,
    logical_schedule: FailureSchedule,
) -> tuple[dict[str, Any], dict[str, object]]:
    content, binding = _validated_checkpoint_content(
        document,
        schema=RUN_CHECKPOINT_SCHEMA,
        task=_variant_task_binding(
            task,
            logical_plan_fingerprint=logical_schedule.fingerprint,
        ),
        contract_fingerprint=contract_fingerprint,
        source_contract_sha256=source_contract_sha256,
    )
    failure_count, concurrency, seed, variant_id = task
    if set(content) != {
        "failure_count",
        "workflow_concurrency",
        "seed",
        "variant_id",
        "system",
    }:
        raise ValueError("run checkpoint content fields are malformed")
    if (
        content.get("failure_count"),
        content.get("workflow_concurrency"),
        content.get("seed"),
        content.get("variant_id"),
    ) != (failure_count, concurrency, seed, variant_id):
        raise ValueError("run checkpoint compact task mismatch")
    _validate_compact_system(
        content.get("system"),
        task=task,
        expected_variant_fingerprint=expected_variant_fingerprint,
        logical_schedule=logical_schedule,
    )
    return content, binding


def _build_cell(
    failure_count: int,
    concurrency: int,
    seed: int,
    workload_fingerprint: str,
    systems: Mapping[str, dict[str, Any]],
    run_content_bindings: Mapping[str, dict[str, object]],
    canonical_plan_fingerprint: str,
) -> dict[str, Any]:
    if set(systems) != {"vanilla_mooncake_dram", "aegiskv_unified"}:
        raise ExperimentError("paper comparison is missing a required system")
    schedules = {variant_id: system["failure_schedule"] for variant_id, system in systems.items()}
    progress_targets = {
        tuple(
            int(event["workload_position"]["target_progress_per_mille"])
            for event in schedule["events"]
        )
        for schedule in schedules.values()
    }
    if len(progress_targets) != 1:
        raise ExperimentError("paper comparison used divergent workload targets")
    focus_ids_by_system = {
        variant_id: [event["focus_span_id"] for event in schedule["events"]]
        for variant_id, schedule in schedules.items()
    }
    if any(
        len(focus_ids) != failure_count or len(set(focus_ids)) != failure_count
        for focus_ids in focus_ids_by_system.values()
    ):
        raise ExperimentError("paper comparison failure focus spans are malformed")
    if len({tuple(focus_ids) for focus_ids in focus_ids_by_system.values()}) != 1:
        raise ExperimentError("paper comparison used divergent logical focus spans")
    schedule_fingerprints = {
        variant_id: system["failure_schedule_fingerprint"] for variant_id, system in systems.items()
    }
    mooncake_mean = systems["vanilla_mooncake_dram"]["run"]["metrics"][
        "workflow_completion_time_ns"
    ]["mean"]
    aegiskv_mean = systems["aegiskv_unified"]["run"]["metrics"]["workflow_completion_time_ns"][
        "mean"
    ]
    return {
        "cell_id": _cell_id(failure_count, concurrency, seed),
        "failure_count": failure_count,
        "workflow_concurrency": concurrency,
        "seed": seed,
        "workload_fingerprint": workload_fingerprint,
        "failure_focus_bucket": _WORKER_BUCKET,
        "schedule_mode": (
            "per_concurrency_canonical_focus_runtime_resolved_natural_route"
        ),
        "canonical_plan_fingerprint": canonical_plan_fingerprint,
        "failure_schedule_fingerprint": sha256_json(schedule_fingerprints),
        "failure_schedule_fingerprints": schedule_fingerprints,
        "failure_focus_span_ids_by_system": focus_ids_by_system,
        "failure_target_workload_progress_per_mille": list(next(iter(progress_targets))),
        "mean_wct_gain_percent": 100.0 * (mooncake_mean - aegiskv_mean) / mooncake_mean,
        "run_content_bindings": dict(run_content_bindings),
        "systems": dict(systems),
    }


def _validate_cross_scale_alignment(
    raw_seed_cells: Sequence[Mapping[str, Any]],
    *,
    seeds: Sequence[int],
) -> None:
    """Validate within-cell pairing and per-concurrency canonical-plan nesting."""

    by_dimensions = {
        (
            _required_integer(cell.get("failure_count"), path="cell.failure_count", minimum=1),
            _required_integer(
                cell.get("workflow_concurrency"),
                path="cell.workflow_concurrency",
                minimum=1,
            ),
            _required_integer(cell.get("seed"), path="cell.seed"),
        ): cell
        for cell in raw_seed_cells
    }
    for seed in seeds:
        workload_fingerprints = set()
        for concurrency in WORKFLOW_CONCURRENCIES:
            cell = _required_mapping(
                by_dimensions.get((BASE_FAILURE_COUNT, concurrency, seed)),
                path="cross_scale.concurrency_cell",
            )
            focuses = _required_mapping(
                cell.get("failure_focus_span_ids_by_system"),
                path="cross_scale.failure_focus_span_ids_by_system",
            )
            mooncake_ids = focuses.get("vanilla_mooncake_dram")
            aegiskv_ids = focuses.get(AEGISKV_VARIANT_ID)
            if (
                not isinstance(mooncake_ids, list)
                or len(mooncake_ids) != BASE_FAILURE_COUNT
                or len(set(mooncake_ids)) != BASE_FAILURE_COUNT
                or mooncake_ids != aegiskv_ids
            ):
                raise ExperimentError("cross-scale systems diverged in logical focus IDs")
            if cell.get("failure_target_workload_progress_per_mille") != [333, 667]:
                raise ExperimentError("cross-scale F2 targets drifted from 33% and 67%")
            workload_fingerprints.add(
                _required_text(
                    cell.get("workload_fingerprint"),
                    path="cross_scale.workload_fingerprint",
                )
            )
            _required_text(
                cell.get("canonical_plan_fingerprint"),
                path="cross_scale.canonical_plan_fingerprint",
            )
        if len(workload_fingerprints) != 1:
            raise ExperimentError("workflow-concurrency scale changed the frozen workload")

        nested_sets = []
        failure_scale_plan_fingerprints = set()
        for failure_count in FAILURE_COUNTS:
            cell = _required_mapping(
                by_dimensions.get((failure_count, BASE_CONCURRENCY, seed)),
                path="cross_scale.failure_cell",
            )
            focuses = _required_mapping(
                cell.get("failure_focus_span_ids_by_system"),
                path="cross_scale.failure_focus_span_ids_by_system",
            )
            focus_ids = focuses.get("vanilla_mooncake_dram")
            aegiskv_ids = focuses.get(AEGISKV_VARIANT_ID)
            if (
                not isinstance(focus_ids, list)
                or len(focus_ids) != failure_count
                or len(set(focus_ids)) != failure_count
                or focus_ids != aegiskv_ids
            ):
                raise ExperimentError("failure-count scale has malformed logical focus IDs")
            nested_sets.append(set(focus_ids))
            failure_scale_plan_fingerprints.add(
                _required_text(
                    cell.get("canonical_plan_fingerprint"),
                    path="cross_scale.canonical_plan_fingerprint",
                )
            )
            workload_fingerprints.add(
                _required_text(
                    cell.get("workload_fingerprint"),
                    path="cross_scale.workload_fingerprint",
                )
            )
        if any(
            not nested_sets[index] < nested_sets[index + 1]
            for index in range(len(nested_sets) - 1)
        ):
            raise ExperimentError("failure-count scale logical focus sets are not nested")
        if len(failure_scale_plan_fingerprints) != 1:
            raise ExperimentError("failure-count scale changed its C16 canonical plan")
        if len(workload_fingerprints) != 1:
            raise ExperimentError("cross-scale cells changed the frozen workload")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run modeled/preliminary Qwen3-8B DP=8 paper-figure sweeps."
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=default_config_dir(repository_root()),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument(
        "--seeds",
        default=",".join(map(str, DEFAULT_SEEDS)),
        help="Exact formal seed vector; must be 0,1,2,3,4.",
    )
    parser.add_argument(
        "--claim-observed-128k-coverage",
        action="store_true",
        help="Fail unless the frozen manifest contains an actual 128k-bucket observation.",
    )
    return parser


def _parse_seeds(value: str) -> tuple[int, ...]:
    try:
        seeds = tuple(int(item) for item in value.split(","))
    except ValueError as error:
        raise ValueError("--seeds must be comma-separated integers") from error
    if seeds != DEFAULT_SEEDS:
        raise ValueError(
            "--seeds must be exactly 0,1,2,3,4 for the frozen formal protocol"
        )
    return seeds


def _context_coverage(
    workload_manifest: Mapping[str, Any], *, claimed_observed_128k_coverage: bool
) -> dict[str, object]:
    selection = workload_manifest.get("selection")
    audit = selection.get("audit") if isinstance(selection, Mapping) else None
    counts = audit.get("context_bucket_counts") if isinstance(audit, Mapping) else None
    if not isinstance(counts, Mapping):
        raise ValueError("workload manifest lacks context_bucket_counts")
    assert isinstance(audit, Mapping)
    expected_buckets = ("8k", "32k", "64k", "96k", "128k")
    if set(counts) != set(expected_buckets) or any(
        type(counts[bucket]) is not int or counts[bucket] < 0 for bucket in expected_buckets
    ):
        raise ValueError("workload manifest context bucket counts are malformed")
    max_observed = audit.get("max_observed_context_tokens")
    if type(max_observed) is not int or max_observed <= 0:
        raise ValueError("workload manifest max observed context is malformed")
    observed_128k = int(counts["128k"]) > 0
    if observed_128k != (max_observed > 96 * 1024):
        raise ValueError("128k bucket count and max observed context are inconsistent")
    if claimed_observed_128k_coverage and not observed_128k:
        raise ValueError(
            "128K paper claim rejected: frozen workload has no observed 128k-bucket context"
        )
    highest_nonempty = next(
        (bucket for bucket in ("128k", "96k", "64k", "32k", "8k") if int(counts[bucket]) > 0),
        None,
    )
    if highest_nonempty is None:
        raise ValueError("workload has no non-empty failure-focus bucket")
    return {
        "context_bucket_counts": {bucket: int(counts[bucket]) for bucket in expected_buckets},
        "max_observed_context_tokens": max_observed,
        "observed_128k_coverage": observed_128k,
        "highest_nonempty_context_bucket": highest_nonempty,
        "claimed_observed_128k_coverage": claimed_observed_128k_coverage,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_dir = args.output_dir.resolve()
    output_dir_preexisting = output_dir.exists()
    temporary_dir: Path | None = None
    source_contract_sha256: str | None = None
    checkpoint_contract_fingerprint: str | None = None
    active_task_context: dict[str, object] | None = None
    try:
        if args.jobs <= 0:
            raise ValueError("jobs must be positive")
        seeds = _parse_seeds(args.seeds)
        if output_dir.exists():
            raise ValueError(f"output directory already exists: {output_dir}")
        configs = load_experiment_configs(args.config_dir, root=repository_root())
        configured_seeds = matrix_seeds(configs.requests)
        if configured_seeds != DEFAULT_SEEDS or seeds != configured_seeds:
            raise ValueError(
                "CLI and requests.json seeds must both be exactly 0,1,2,3,4"
            )
        source_bindings = _source_bindings(repository_root())
        parameters = model_parameters_from_configs(configs)
        workload_path, manifest_path = workload_paths(configs.requests, root=repository_root())
        records, workload_binding, workload_manifest = load_frozen_workload(
            workload_path,
            manifest_path,
            retain_exact_token_ids=True,
        )
        if workload_manifest["selection"]["audit"]["task_count"] != 160:
            raise ValueError("paper sweeps require exactly 160 independent workflows")
        variants = {item.variant_id: item for item in core_variants(parameters)}
        selected_variants = (
            variants["vanilla_mooncake_dram"],
            variants["aegiskv_unified"],
        )
        context_coverage = _context_coverage(
            workload_manifest,
            claimed_observed_128k_coverage=args.claim_observed_128k_coverage,
        )
        global _WORKER_RECORDS, _WORKER_VARIANTS, _WORKER_BUCKET
        _WORKER_RECORDS = records
        _WORKER_VARIANTS = selected_variants
        _WORKER_BUCKET = str(context_coverage["highest_nonempty_context_bucket"])

        cells = [
            *((count, BASE_CONCURRENCY) for count in reversed(FAILURE_COUNTS)),
            *(
                (BASE_FAILURE_COUNT, value)
                for value in WORKFLOW_CONCURRENCIES
                if value != BASE_CONCURRENCY
            ),
        ]
        system_results: dict[tuple[int, int, int], dict[str, dict[str, Any]]] = {
            (failure_count, concurrency, seed): {}
            for failure_count, concurrency in cells
            for seed in seeds
        }
        run_content_bindings: dict[
            tuple[int, int, int], dict[str, dict[str, object]]
        ] = {
            (failure_count, concurrency, seed): {}
            for failure_count, concurrency in cells
            for seed in seeds
        }
        tasks = [
            (failure_count, concurrency, seed, variant.variant_id)
            for failure_count, concurrency in cells
            for seed in seeds
            for variant in selected_variants
        ]
        checkpoint_dir = output_dir.parent / f".{output_dir.name}.checkpoints"
        source_contract_sha256 = sha256_json(source_bindings)
        checkpoint_contract_body = {
            "schema": CHECKPOINT_SCHEMA,
            "requests_sha256": _sha256_file(configs.requests_path),
            "failure_sha256": _sha256_file(configs.failure_path),
            "engine_sha256": _sha256_file(configs.engine_path),
            "workload_sha256": _sha256_file(workload_path),
            "workload_manifest_sha256": _sha256_file(manifest_path),
            "experiment_sha256": _sha256_file(
                repository_root() / "python/moonkvsim/aegiskv/experiment.py"
            ),
            "source_bindings": source_bindings,
            "tasks": [list(task) for task in tasks],
            "variant_fingerprints": {
                variant.variant_id: variant.fingerprint for variant in selected_variants
            },
            "canonical_failure_plan": {
                "reference_variant_id": "vanilla_mooncake_dram",
                "plan_scope": "per_seed_per_workflow_concurrency",
                "workflow_concurrencies": list(CANONICAL_CONCURRENCIES),
                "failure_count_by_concurrency": {
                    str(concurrency): _canonical_plan_failure_count(concurrency)
                    for concurrency in CANONICAL_CONCURRENCIES
                },
                "failure_scale_source_concurrency": BASE_CONCURRENCY,
                "concurrency_scale_failure_count": BASE_FAILURE_COUNT,
                "c16_nested_event_indices": {
                    str(failure_count): list(indices)
                    for failure_count, indices in CANONICAL_NESTED_EVENT_INDICES.items()
                },
                "projection_semantics": (
                    "c16_f8_nested_failure_scale_nonbase_direct_f2_"
                    "within_cell_fixed_logical_focus_ids_runtime_resolved_variant_local_"
                    "natural_route_and_timing_without_oracle_reexecution"
                ),
            },
            "source_contract_sha256": source_contract_sha256,
        }
        checkpoint_contract = {
            **checkpoint_contract_body,
            "fingerprint": sha256_json(checkpoint_contract_body),
        }
        checkpoint_contract_fingerprint = str(checkpoint_contract["fingerprint"])
        checkpoint_contract_path = checkpoint_dir / "contract.json"
        if checkpoint_dir.exists():
            if (
                not checkpoint_contract_path.is_file()
                or json.loads(checkpoint_contract_path.read_text(encoding="utf-8"))
                != checkpoint_contract
            ):
                raise ValueError(f"checkpoint contract mismatch: {checkpoint_dir}")
        else:
            checkpoint_dir.mkdir(parents=True)
            _write_json_atomic(checkpoint_contract_path, checkpoint_contract)

        canonical_schedules: dict[tuple[int, int], FailureSchedule] = {}
        canonical_plan_bindings: dict[tuple[int, int], dict[str, object]] = {}
        canonical_plan_contents: dict[tuple[int, int], dict[str, Any]] = {}
        canonical_plan_tasks = [
            (seed, concurrency)
            for seed in seeds
            for concurrency in CANONICAL_CONCURRENCIES
        ]
        pending_plan_tasks = []
        for seed, concurrency in canonical_plan_tasks:
            plan_path = _canonical_plan_checkpoint_path(
                checkpoint_dir,
                seed,
                concurrency,
            )
            if plan_path.is_file():
                plan_document = json.loads(plan_path.read_text(encoding="utf-8"))
                schedule, binding, content = _validated_canonical_plan_checkpoint(
                    plan_document,
                    seed=seed,
                    concurrency=concurrency,
                    contract_fingerprint=checkpoint_contract_fingerprint,
                    source_contract_sha256=source_contract_sha256,
                )
                plan_key = (seed, concurrency)
                canonical_schedules[plan_key] = schedule
                canonical_plan_bindings[plan_key] = binding
                canonical_plan_contents[plan_key] = content
                print(
                    f"reused canonical failure plan seed-{seed} concurrency-{concurrency}",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                pending_plan_tasks.append((seed, concurrency))
        context = multiprocessing.get_context("fork")
        plan_executor = ProcessPoolExecutor(max_workers=args.jobs, mp_context=context)
        pending_plans = {}
        try:
            for seed, concurrency in pending_plan_tasks:
                plan_future = plan_executor.submit(
                    _worker_canonical_plan,
                    seed,
                    concurrency,
                    checkpoint_dir=checkpoint_dir,
                    contract_fingerprint=checkpoint_contract_fingerprint,
                    source_contract_sha256=source_contract_sha256,
                )
                pending_plans[plan_future] = (seed, concurrency)
            for plan_future in as_completed(pending_plans):
                seed, concurrency = pending_plans[plan_future]
                active_task_context = _canonical_plan_task_binding(seed, concurrency)
                schedule, binding, content = _validated_canonical_plan_checkpoint(
                    _future_result_with_context(
                        plan_future,
                        task_context=active_task_context,
                    ),
                    seed=seed,
                    concurrency=concurrency,
                    contract_fingerprint=checkpoint_contract_fingerprint,
                    source_contract_sha256=source_contract_sha256,
                )
                plan_key = (seed, concurrency)
                canonical_schedules[plan_key] = schedule
                canonical_plan_bindings[plan_key] = binding
                canonical_plan_contents[plan_key] = content
                print(
                    f"completed canonical failure plan seed-{seed} concurrency-{concurrency}",
                    file=sys.stderr,
                    flush=True,
                )
                active_task_context = None
        except BaseException:
            _abort_process_pool(plan_executor, tuple(pending_plans))
            raise
        else:
            plan_executor.shutdown(wait=True)

        pending_tasks = []
        for task in tasks:
            checkpoint_path = _checkpoint_path(checkpoint_dir, task)
            failure_count, concurrency, seed, variant_id = task
            logical_schedule = _canonical_schedule_for_failure_count(
                canonical_schedules[(seed, concurrency)], failure_count
            )
            if checkpoint_path.is_file():
                result, binding = _validated_run_checkpoint(
                    json.loads(checkpoint_path.read_text(encoding="utf-8")),
                    task=task,
                    contract_fingerprint=checkpoint_contract_fingerprint,
                    source_contract_sha256=source_contract_sha256,
                    expected_variant_fingerprint=variants[variant_id].fingerprint,
                    logical_schedule=logical_schedule,
                )
                key = (failure_count, concurrency, seed)
                system_results[key][variant_id] = result["system"]
                run_content_bindings[key][variant_id] = binding
                print(
                    f"reused {_cell_id(*key)}:{variant_id}",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                pending_tasks.append(task)
        pending_cell_tasks = _group_variant_tasks_by_cell(pending_tasks)
        cell_executor = ProcessPoolExecutor(max_workers=args.jobs, mp_context=context)
        pending_cells = {}
        try:
            for cell_task_to_submit in pending_cell_tasks:
                cell_future = cell_executor.submit(
                    _worker_cell,
                    cell_task_to_submit,
                    _canonical_schedule_for_failure_count(
                        canonical_schedules[
                            (cell_task_to_submit[2], cell_task_to_submit[1])
                        ],
                        cell_task_to_submit[0],
                    ),
                    checkpoint_dir,
                    checkpoint_contract_fingerprint,
                    source_contract_sha256,
                )
                pending_cells[cell_future] = cell_task_to_submit
            for cell_future in as_completed(pending_cells):
                cell_task = pending_cells[cell_future]
                failure_count, concurrency, seed, variant_ids = cell_task
                active_task_context = _cell_task_binding(
                    failure_count,
                    concurrency,
                    seed,
                    variant_ids,
                )
                documents = _future_result_with_context(
                    cell_future,
                    task_context=active_task_context,
                )
                if len(documents) != len(variant_ids):
                    raise ValueError("paper-sweep cell worker returned an incomplete result set")
                logical_schedule = _canonical_schedule_for_failure_count(
                    canonical_schedules[(seed, concurrency)], failure_count
                )
                for variant_id, run_document in zip(
                    variant_ids, documents, strict=True
                ):
                    task = (failure_count, concurrency, seed, variant_id)
                    result, binding = _validated_run_checkpoint(
                        run_document,
                        task=task,
                        contract_fingerprint=checkpoint_contract_fingerprint,
                        source_contract_sha256=source_contract_sha256,
                        expected_variant_fingerprint=variants[variant_id].fingerprint,
                        logical_schedule=logical_schedule,
                    )
                    key = (failure_count, concurrency, seed)
                    system_results[key][variant_id] = result["system"]
                    run_content_bindings[key][variant_id] = binding
                    print(
                        f"completed {_cell_id(*key)}:{variant_id}",
                        file=sys.stderr,
                        flush=True,
                    )
                active_task_context = None
        except BaseException:
            _abort_process_pool(cell_executor, tuple(pending_cells))
            raise
        else:
            cell_executor.shutdown(wait=True)
        for failure_count, concurrency, seed, variant_id in tasks:
            _validate_compact_system(
                system_results[(failure_count, concurrency, seed)][variant_id],
                task=(failure_count, concurrency, seed, variant_id),
                expected_variant_fingerprint=variants[variant_id].fingerprint,
                logical_schedule=_canonical_schedule_for_failure_count(
                    canonical_schedules[(seed, concurrency)], failure_count
                ),
            )
        raw_seed_cells = [
            _build_cell(
                failure_count,
                concurrency,
                seed,
                workload_binding.fingerprint,
                system_results[(failure_count, concurrency, seed)],
                run_content_bindings[(failure_count, concurrency, seed)],
                canonical_schedules[(seed, concurrency)].fingerprint,
            )
            for failure_count, concurrency in cells
            for seed in seeds
        ]
        raw_seed_cells.sort(
            key=lambda item: (
                item["failure_count"],
                item["workflow_concurrency"],
                item["seed"],
            )
        )
        _validate_cross_scale_alignment(raw_seed_cells, seeds=seeds)
        aggregate_cells: list[dict[str, Any]] = []
        for failure_count, concurrency in cells:
            seed_cells = [
                cell
                for cell in raw_seed_cells
                if cell["failure_count"] == failure_count
                and cell["workflow_concurrency"] == concurrency
            ]
            statistics = build_paper_sweep_statistics(seed_cells)
            if statistics["status"] != "PASS":
                raise ExperimentError(
                    f"paper aggregate gate failed for F={failure_count}, C={concurrency}: "
                    f"{statistics['status']}"
                )
            aggregate_cells.append(
                {
                    "cell_id": _cell_id(failure_count, concurrency),
                    "failure_count": failure_count,
                    "workflow_concurrency": concurrency,
                    "statistics": statistics,
                }
            )
        aggregate_cells.sort(key=lambda item: (item["failure_count"], item["workflow_concurrency"]))
        file_bindings = {
            path.name: {"path": path.as_posix(), "sha256": _sha256_file(path)}
            for path in (
                configs.requests_path,
                configs.failure_path,
                configs.engine_path,
                workload_path,
                manifest_path,
            )
        }
        document: dict[str, Any] = {
            "schema": SCHEMA,
            "status": "PASS",
            "evidence": {
                "class": "E2",
                "scope": "modeled/preliminary",
                "calibration": "not_calibrated",
                "physical_execution": False,
                "paper_ready": False,
            },
            "protocol": {
                "model": "Qwen/Qwen3-8B",
                "dp": parameters.dp_count,
                "seeds": list(seeds),
                "seed_count": len(seeds),
                "minimum_seed_count": MINIMUM_SEED_COUNT,
                "independent_sampling_unit": "seed",
                "randomized_input": "workflow_admission_permutation",
                "peer_binding_seed": 0,
                "effect_direction_gate_applied": False,
                "workflow_count": 160,
                "base_failure_count": BASE_FAILURE_COUNT,
                "base_workflow_concurrency": BASE_CONCURRENCY,
                "failure_counts": list(FAILURE_COUNTS),
                "workflow_concurrencies": list(WORKFLOW_CONCURRENCIES),
                "failure_focus_bucket_rule": "highest_nonempty_context_bucket",
                "failure_focus_bucket": _WORKER_BUCKET,
                "context_coverage": context_coverage,
                "failure_pairing": (
                    "per_seed_per_concurrency_canonical_nested_logical_focus_"
                    "within_cell_runtime_resolved_variant_local_natural_route_and_timing"
                ),
                "failure_scale_canonical_failure_count": CANONICAL_FAILURE_COUNT,
                "canonical_workflow_concurrencies": list(CANONICAL_CONCURRENCIES),
                "canonical_failure_count_by_concurrency": {
                    str(concurrency): _canonical_plan_failure_count(concurrency)
                    for concurrency in CANONICAL_CONCURRENCIES
                },
                "failure_scale_canonical_concurrency": BASE_CONCURRENCY,
                "concurrency_scale_failure_count": BASE_FAILURE_COUNT,
                "nonbase_concurrency_plan_semantics": "direct_f2_without_f8_subselection",
                "cross_concurrency_focus_identity_required": False,
                "cross_concurrency_fixed_controls": [
                    "seed",
                    "workload_fingerprint",
                    "failure_targets_per_mille",
                ],
                "c16_canonical_nested_event_indices": {
                    str(failure_count): list(indices)
                    for failure_count, indices in CANONICAL_NESTED_EVENT_INDICES.items()
                },
                "repetitions": list(REPETITIONS),
                "smoothing_performed": False,
                "trend_shaping_performed": False,
            },
            "provenance": {
                "git_head": _git("rev-parse", "HEAD"),
                "git_worktree_clean": not bool(_git("status", "--porcelain=v1")),
                "git_status_sha256": hashlib.sha256(
                    _git("status", "--porcelain=v1", "--untracked-files=all").encode()
                ).hexdigest(),
                "workload": {
                    **workload_binding.to_dict(),
                    "fingerprint": workload_binding.fingerprint,
                },
                "files": file_bindings,
                "source_files": source_bindings,
                "checkpoint_contract": checkpoint_contract,
                "canonical_failure_plans": {
                    str(seed): {
                        str(concurrency): {
                            "content": canonical_plan_contents[(seed, concurrency)],
                            "binding": canonical_plan_bindings[(seed, concurrency)],
                        }
                        for concurrency in CANONICAL_CONCURRENCIES
                    }
                    for seed in seeds
                },
                "checkpoint_evidence": {
                    "retained_directory": "checkpoint-proof",
                    "run_checkpoint_count": len(tasks),
                    "canonical_plan_checkpoint_count": len(canonical_plan_tasks),
                    "run_content_hashes_embedded_in_raw_seed_cells": True,
                },
            },
            "raw_seed_cells": raw_seed_cells,
            "cells": aggregate_cells,
        }
        document["fingerprint"] = sha256_json(document)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
        raw_dir = temporary_dir / "raw-seed-cells"
        aggregate_dir = temporary_dir / "aggregates"
        raw_dir.mkdir()
        aggregate_dir.mkdir()
        shutil.copytree(checkpoint_dir, temporary_dir / "checkpoint-proof")
        for cell in raw_seed_cells:
            _write_json_atomic(
                raw_dir
                / (
                    f"failure-{cell['failure_count']}_concurrency-"
                    f"{cell['workflow_concurrency']}_seed-{cell['seed']}.json"
                ),
                cell,
            )
        for cell in aggregate_cells:
            _write_json_atomic(
                aggregate_dir
                / (
                    f"failure-{cell['failure_count']}_concurrency-"
                    f"{cell['workflow_concurrency']}.json"
                ),
                cell,
            )
        (temporary_dir / "paper-sweeps.json").write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_dir, output_dir)
        temporary_dir = None
        # Exact bound checkpoint envelopes remain under output/checkpoint-proof.
        shutil.rmtree(checkpoint_dir)
    except (
        OSError,
        RuntimeError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        if temporary_dir is not None:
            with suppress(OSError):
                shutil.rmtree(temporary_dir)
        print(f"AegisKV paper sweep rejected: {error}", file=sys.stderr)
        failure_task_context = (
            error.task_context
            if isinstance(error, PaperSweepWorkerError)
            else active_task_context
        )
        if not output_dir_preexisting and not output_dir.exists():
            try:
                failure_path = _write_failure_artifact(
                    output_dir=output_dir,
                    error=error,
                    task_context=failure_task_context,
                    source_contract_sha256=source_contract_sha256,
                    checkpoint_contract_fingerprint=checkpoint_contract_fingerprint,
                )
            except OSError as diagnostic_error:
                print(
                    "AegisKV paper sweep failure artifact could not be written: "
                    f"{diagnostic_error}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"AegisKV paper sweep failure artifact: {failure_path}",
                    file=sys.stderr,
                )
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "output_dir": output_dir.as_posix(),
                "aggregate_cell_count": len(aggregate_cells),
                "raw_seed_cell_count": len(raw_seed_cells),
                "seed_count": len(seeds),
                "fingerprint": document["fingerprint"],
                "evidence": "E2 modeled/preliminary not_calibrated",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
