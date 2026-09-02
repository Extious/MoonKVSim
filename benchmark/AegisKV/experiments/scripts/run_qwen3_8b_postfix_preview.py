#!/usr/bin/env python3
"""Run four current-source Qwen3-8B preview variants in parallel.

This is a fail-closed, modeled-uncalibrated development preview.  It reuses the
frozen 160-workflow input and the historical seed-0 logical failure focus, but
does not claim deterministic identity with the historical aggregate.
"""

from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing
import os
import tempfile
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Final, cast

from moonkvsim.aegiskv.experiment import (
    CellSpec,
    ExperimentVariant,
    FailureEventSchedule,
    FailureSchedule,
    Scenario,
    core_variants,
    derive_failure_schedule,
    project_failure_schedule_to_profile,
    run_study_cell,
)
from moonkvsim.aegiskv.experiment_config import (
    default_config_dir,
    load_experiment_configs,
    model_parameters_from_configs,
    repository_root,
    workload_paths,
)
from moonkvsim.aegiskv.experiment_suite import load_frozen_workload
from moonkvsim.common.hash import sha256_json

SYSTEMS: Final = ("vanilla_mooncake_dram", "aegiskv_unified")
MOONCAKE: Final = "vanilla_mooncake_dram"
SCENARIOS: Final = ("no_failure", "gpu_failure")
BASE_FAILURES: Final = 2
BASE_CONCURRENCY: Final = 16

_RECORDS: Sequence[Mapping[str, Any]] | None = None
_VARIANTS: Mapping[str, ExperimentVariant] | None = None
_SCHEDULES: Mapping[str, FailureSchedule] | None = None
_BUCKET: str | None = None
_CHECKPOINT_DIR: Path | None = None


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{where} must be an array")
    return value


def _historical_base_cell(aggregate: Mapping[str, Any]) -> Mapping[str, Any]:
    raw_cells = aggregate.get("raw_seed_cells")
    candidates = (
        _array(raw_cells, "aggregate.raw_seed_cells")
        if raw_cells is not None
        else _array(aggregate.get("cells"), "aggregate.cells")
    )
    matches = [
        _mapping(item, "aggregate cell")
        for item in candidates
        if isinstance(item, Mapping)
        and item.get("seed") == 0
        and item.get("failure_count") == BASE_FAILURES
        and item.get("workflow_concurrency") == BASE_CONCURRENCY
    ]
    if len(matches) != 1:
        raise ValueError("historical aggregate lacks one seed-0 F=2 C=16 base cell")
    return matches[0]


def _legacy_failure_schedule(value: object) -> FailureSchedule:
    raw = _mapping(value, "historical failure_schedule")
    raw_events = _array(raw.get("events"), "historical failure_schedule.events")
    events = []
    for index, value_event in enumerate(raw_events):
        event = _mapping(value_event, f"historical failure_schedule.events[{index}]")
        workload = _mapping(event.get("workload_position"), "historical workload_position")
        trigger = _mapping(event.get("trigger"), "historical trigger")
        events.append(
            FailureEventSchedule(
                failure_id=str(event["failure_id"]),
                event_index=int(event["event_index"]),
                bucket=str(event["bucket"]),
                seed=int(event["seed"]),
                focus_span_id=str(event["focus_span_id"]),
                target_gpu_id=str(event["target_gpu_id"]),
                reference_at_ns=int(event["reference_at_ns"]),
                target_workload_progress_per_mille=int(
                    workload["target_progress_per_mille"]
                ),
                reference_completed_workflow_count=int(
                    workload["reference_completed_workflow_count"]
                ),
                reference_workflow_count=int(workload["reference_workflow_count"]),
                detection_delay_ns=int(event["detection_delay_ns"]),
                trigger_progress_per_mille=int(trigger["progress_per_mille"]),
                gpu_recovery_time_ns=(
                    None
                    if event.get("repair_after_ns") is None
                    else int(event["repair_after_ns"])
                ),
                selection_scope=str(event["selection_scope"]),
            )
        )
    return FailureSchedule(
        tuple(events),
        selection_scope=str(raw["selection_scope"]),
    )


def _init_worker(
    records: Sequence[Mapping[str, Any]],
    variants: Mapping[str, ExperimentVariant],
    schedules: Mapping[str, FailureSchedule],
    bucket: str,
    checkpoint_dir: Path,
) -> None:
    global _RECORDS, _VARIANTS, _SCHEDULES, _BUCKET, _CHECKPOINT_DIR
    _RECORDS = records
    _VARIANTS = variants
    _SCHEDULES = schedules
    _BUCKET = bucket
    _CHECKPOINT_DIR = checkpoint_dir


def _run_one(system_id: str, scenario_id: str) -> dict[str, Any]:
    if (
        _RECORDS is None
        or _VARIANTS is None
        or _SCHEDULES is None
        or _BUCKET is None
        or _CHECKPOINT_DIR is None
    ):
        raise RuntimeError("preview worker was not initialized")
    started = time.monotonic()
    print(f"[postfix-preview] {scenario_id}/{system_id} START", flush=True)
    scenario = Scenario.NO_FAILURE if scenario_id == "no_failure" else Scenario.GPU_FAILURE
    schedule = None if scenario is Scenario.NO_FAILURE else _SCHEDULES[system_id]
    result = run_study_cell(
        _RECORDS,
        CellSpec(
            variant=_VARIANTS[system_id],
            context_bucket=_BUCKET,
            scenario=scenario,
            seed=0,
            repetition="A",
            failure_schedule=schedule,
            workflow_concurrency=BASE_CONCURRENCY,
        ),
    )
    print(
        f"[postfix-preview] {scenario_id}/{system_id} DONE "
        f"wall_s={time.monotonic() - started:.1f}",
        flush=True,
    )
    payload = result.payload
    representative = result.representative
    compact_result = {
        "system_id": system_id,
        "scenario": scenario_id,
        "variant_fingerprint": _VARIANTS[system_id].fingerprint,
        "failure_schedule": None if schedule is None else schedule.to_dict(),
        "failure_schedule_fingerprint": None if schedule is None else schedule.fingerprint,
        "payload": {
            key: payload[key]
            for key in (
                "schema",
                "scenario",
                "variant_id",
                "workload",
                "metrics",
                "resource_cost",
                "output_audit",
            )
            if key in payload
        },
        "payload_sha256": result.payload_sha256,
        "journal_sha256": result.journal_sha256,
        "span_details": list(result.span_details),
        "span_details_sha256": sha256_json(result.span_details),
        "representative": {
            key: representative[key]
            for key in (
                "failure_schedule",
                "failure_events",
                "recovery_events",
                "failure_focus_spans",
                "failure_impacted_spans",
                "foreground_store_events",
                "aimd_events",
                "scheduler_preemption_events",
                "algorithm1_slack_updates",
                "formal_algorithm2_events",
                "gpu_hbm_timelines",
                "normal_hbm_timelines",
                "peer_hbm_timeline",
                "peer_hbm_timelines",
                "store_dram_timeline",
                "store_dram_timelines",
            )
            if key in representative
        },
        "continuous_batch_scheduler_sha256": sha256_json(
            representative.get("continuous_batch_scheduler")
        ),
        "representative_sha256": sha256_json(result.representative),
    }
    _write_checkpoint(
        _CHECKPOINT_DIR / f"{scenario_id}__{system_id}.json.gz",
        compact_result,
    )
    return compact_result


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=stream,
            compresslevel=6,
            mtime=0,
        ) as compressed:
            payload = (
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            compressed.write(payload)
    temporary.replace(path)


def _write_checkpoint(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as stream:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=stream,
            compresslevel=6,
            mtime=0,
        ) as compressed:
            compressed.write(
                (
                    json.dumps(
                        value,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n"
                ).encode("utf-8")
            )
    temporary.replace(path)


def _read_checkpoint(path: Path) -> Mapping[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return _mapping(json.load(stream), f"checkpoint {path.name}")


def _select_complete_workflows(
    records: Sequence[Mapping[str, Any]],
    *,
    focus_span_ids: Sequence[str],
    workflow_limit: int,
) -> tuple[list[Mapping[str, Any]], tuple[str, ...]]:
    if workflow_limit < 2:
        raise ValueError("workflow-limit must be at least two")
    by_workflow: dict[str, list[Mapping[str, Any]]] = {}
    workflow_by_span: dict[str, str] = {}
    for record in records:
        workflow_id = str(record.get("workflow_id", ""))
        span_id = str(record.get("span_id", ""))
        if not workflow_id or not span_id:
            raise ValueError("preview workload record lacks workflow/span identity")
        by_workflow.setdefault(workflow_id, []).append(record)
        workflow_by_span[span_id] = workflow_id
    focus_workflows = {
        workflow_by_span[span_id]
        for span_id in focus_span_ids
        if span_id in workflow_by_span
    }
    if len(focus_workflows) != len(set(focus_span_ids)):
        raise ValueError("preview workload lacks a failure-focus span")
    if len(focus_workflows) > workflow_limit:
        raise ValueError("workflow-limit cannot contain all failure-focus workflows")

    def token_volume(workflow_id: str) -> int:
        total = 0
        for record in by_workflow[workflow_id]:
            content = record.get("messages_or_token_ids")
            if isinstance(content, Mapping) and isinstance(content.get("value"), list):
                total += len(content["value"])
            output_tokens = record.get("output_tokens")
            if type(output_tokens) is int:
                total += output_tokens
        return total

    ranked = sorted(
        by_workflow,
        key=lambda workflow_id: (-token_volume(workflow_id), workflow_id),
    )
    selected = list(sorted(focus_workflows))
    selected.extend(
        workflow_id
        for workflow_id in ranked
        if workflow_id not in focus_workflows
    )
    selected = selected[:workflow_limit]
    selected_set = set(selected)
    subset = [
        record for record in records if str(record.get("workflow_id")) in selected_set
    ]
    return subset, tuple(selected)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical-aggregate", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--workflow-limit", type=int, default=16)
    parser.add_argument("--failure-count", type=int, default=BASE_FAILURES)
    parser.add_argument("--failure-focus-bucket", default="96k")
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    parser.add_argument(
        "--shared-plan-all-systems",
        action="store_true",
        help="recursively validate each logical failure focus under every measured system",
    )
    args = parser.parse_args(argv)
    if args.jobs < 1 or args.jobs > 4:
        raise ValueError("jobs must be between 1 and 4")
    if args.failure_count < 1:
        raise ValueError("failure-count must be positive")

    root = repository_root()
    checkpoint_dir = args.checkpoint_dir or args.output.with_suffix(".checkpoints")
    configs = load_experiment_configs(default_config_dir(root), root=root)
    workload_path, manifest_path = workload_paths(configs.requests, root=root)
    records, workload_binding, _manifest = load_frozen_workload(
        workload_path,
        manifest_path,
        retain_exact_token_ids=True,
    )
    aggregate: Mapping[str, Any] | None = None
    base: Mapping[str, Any] | None = None
    schedules: dict[str, FailureSchedule]
    focus_span_ids: tuple[str, ...]
    if args.historical_aggregate is not None:
        aggregate = _mapping(
            json.loads(args.historical_aggregate.read_text(encoding="utf-8")),
            "historical aggregate",
        )
        base = _historical_base_cell(aggregate)
        systems = _mapping(base.get("systems"), "base.systems")
        schedules = {
            system_id: _legacy_failure_schedule(
                _mapping(systems.get(system_id), f"base.systems.{system_id}").get(
                    "failure_schedule"
                )
            )
            for system_id in SYSTEMS
        }
        focus_sets = {
            tuple(event.focus_span_id for event in schedule.events)
            for schedule in schedules.values()
        }
        if len(focus_sets) != 1:
            raise ValueError("historical base systems do not share logical failure focus")
        focus_span_ids = tuple(next(iter(focus_sets)))
    else:
        focus_span_ids = ()
    selected_records, selected_workflow_ids = _select_complete_workflows(
        records,
        focus_span_ids=focus_span_ids,
        workflow_limit=args.workflow_limit,
    )
    variants = {
        item.variant_id: item
        for item in core_variants(model_parameters_from_configs(configs))
        if item.variant_id in SYSTEMS
    }
    if set(variants) != set(SYSTEMS):
        raise ValueError("current variant catalog lacks preview systems")
    bucket = (
        str(base.get("failure_focus_bucket"))
        if base is not None
        else str(args.failure_focus_bucket)
    )
    if aggregate is None:
        reference_variant = variants[MOONCAKE]
        plan_path = checkpoint_dir / "logical-failure-plan.json"
        if plan_path.exists():
            plan_document = _mapping(
                json.loads(plan_path.read_text(encoding="utf-8")),
                "logical failure plan checkpoint",
            )
            if (
                plan_document.get("workflow_ids") != list(selected_workflow_ids)
                or plan_document.get("failure_count") != args.failure_count
                or plan_document.get("bucket") != bucket
            ):
                raise ValueError("logical failure plan checkpoint binding mismatch")
            logical_schedule = _legacy_failure_schedule(plan_document.get("schedule"))
        else:
            print("[postfix-preview] SCHEDULE_START", flush=True)
            logical_schedule = derive_failure_schedule(
                selected_records,
                bucket=bucket,
                seed=0,
                parameters=reference_variant.parameters,
                workflow_concurrency=min(BASE_CONCURRENCY, len(selected_workflow_ids)),
                failure_count=args.failure_count,
                # Select the logical intervention once from the baseline reference.
                # Every measured system receives the same focus spans and trigger
                # progress, while its physical GPU route is resolved at runtime.
                # Re-running the recursive oracle under AegisKV only duplicates
                # the full formal Algorithm 2/3 audit and made plan generation
                # slower than the four measured cells combined.
                compared_profiles=(
                    tuple(variant.profile for variant in variants.values())
                    if args.shared_plan_all_systems
                    else (reference_variant.profile,)
                ),
            )
            _write_checkpoint(
                plan_path,
                {
                    "workflow_ids": list(selected_workflow_ids),
                    "failure_count": args.failure_count,
                    "bucket": bucket,
                    "schedule": logical_schedule.to_dict(),
                    "schedule_fingerprint": logical_schedule.fingerprint,
                },
            )
            print("[postfix-preview] SCHEDULE_DONE", flush=True)
        schedules = {
            system_id: project_failure_schedule_to_profile(
                selected_records,
                reference=logical_schedule,
                profile=variant.profile,
                parameters=variant.parameters,
                workflow_concurrency=min(BASE_CONCURRENCY, len(selected_workflow_ids)),
                seed=0,
            )
            for system_id, variant in variants.items()
        }
        focus_span_ids = tuple(event.focus_span_id for event in logical_schedule.events)

    results: dict[str, dict[str, Any]] = {scenario: {} for scenario in SCENARIOS}
    jobs = []
    for scenario in SCENARIOS:
        for system in SYSTEMS:
            checkpoint_path = checkpoint_dir / f"{scenario}__{system}.json.gz"
            legacy_checkpoint_path = checkpoint_dir / f"{scenario}__{system}.json"
            if not checkpoint_path.exists() and legacy_checkpoint_path.exists():
                checkpoint_path = legacy_checkpoint_path
            if checkpoint_path.exists():
                checkpoint = (
                    _read_checkpoint(checkpoint_path)
                    if checkpoint_path.suffix == ".gz"
                    else _mapping(
                        json.loads(checkpoint_path.read_text(encoding="utf-8")),
                        f"checkpoint {scenario}/{system}",
                    )
                )
                if (
                    checkpoint.get("scenario") != scenario
                    or checkpoint.get("system_id") != system
                ):
                    raise ValueError("run checkpoint binding mismatch")
                results[scenario][system] = dict(checkpoint)
            else:
                jobs.append((scenario, system))
    context = multiprocessing.get_context("fork")
    with ProcessPoolExecutor(
        max_workers=min(args.jobs, len(jobs)) if jobs else 1,
        mp_context=context,
        initializer=_init_worker,
        initargs=(selected_records, variants, schedules, bucket, checkpoint_dir),
    ) as executor:
        futures = {
            executor.submit(_run_one, system, scenario): (scenario, system)
            for scenario, system in jobs
        }
        for future in as_completed(futures):
            scenario, system = futures[future]
            result = future.result()
            results[scenario][system] = result

    body: dict[str, Any] = {
        "schema": "moonkvsim.aegiskv.qwen3_8b.postfix_preview.v1",
        "status": "PASS",
        "evidence": {
            "class": "E2",
            "physical_execution": False,
            "calibrated": False,
            "paper_ready": False,
            "formal_matrix_complete": False,
            "modeled_uncalibrated": True,
            "observed_values_only": True,
        },
        "protocol": {
            "model": "Qwen/Qwen3-8B",
            "dp": 8,
            "tp": 1,
            "pp": 1,
            "seed": 0,
            "workflow_count": len(selected_workflow_ids),
            "workflow_concurrency": min(BASE_CONCURRENCY, len(selected_workflow_ids)),
            "failure_count": args.failure_count,
            "focus_span_ids": list(focus_span_ids),
            "parallel_run_count": len(jobs),
        },
        "source": {
            "historical_aggregate_path": (
                None
                if args.historical_aggregate is None
                else args.historical_aggregate.resolve().as_posix()
            ),
            "historical_aggregate_fingerprint": (
                None if aggregate is None else aggregate.get("fingerprint")
            ),
            "workload": workload_binding.to_dict(),
            "selection": {
                "kind": "complete_workflows_focus_plus_long_context",
                "workflow_limit": args.workflow_limit,
                "selected_workflow_ids": list(selected_workflow_ids),
                "record_count": len(selected_records),
                "no_span_slicing": True,
                "no_cross_workflow_concatenation": True,
            },
        },
        "runs": results,
    }
    artifact = {**body, "fingerprint": sha256_json(body)}
    _write_atomic(args.output, artifact)
    print(json.dumps({"status": "PASS", "output": args.output.resolve().as_posix()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
