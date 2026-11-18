#!/usr/bin/env python3
"""Run four current-source Qwen3-8B preview variants in parallel.

This is a fail-closed, modeled-uncalibrated development preview.  It reuses the
frozen 160-workflow input and the historical seed-0 logical failure focus, but
does not claim deterministic identity with the historical aggregate.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import multiprocessing
import os
import tempfile
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any, Final, cast

from moonkvsim.aegiskv.experiment import (
    CellSpec,
    ExperimentVariant,
    FailureEventSchedule,
    FailureImpactContract,
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
from moonkvsim.aegiskv.paper_artifacts import file_sha256, write_raw_evidence
from moonkvsim.common.hash import sha256_json

SYSTEMS: Final = ("vanilla_mooncake_dram", "aegiskv_unified")
MOONCAKE: Final = "vanilla_mooncake_dram"
SCENARIOS: Final = ("no_failure", "gpu_failure")
BASE_FAILURES: Final = 2
BASE_CONCURRENCY: Final = 16
FAILURE_PLAN_PROTOCOL: Final = "paper_shared_physical_gpu_exact_impact_v4"
IMPLEMENTATION_PATHS: Final = (
    "benchmark/AegisKV/experiments/scripts/run_qwen3_8b_postfix_preview.py",
    "python/moonkvsim/aegiskv/continuous_batch_des.py",
    "python/moonkvsim/aegiskv/experiment.py",
    "python/moonkvsim/aegiskv/experiment_hbm_authority.py",
    "python/moonkvsim/aegiskv/formal_algorithm_audit.py",
    "python/moonkvsim/aegiskv/paper_artifacts.py",
    "python/moonkvsim/aegiskv/scheduler_step_bridge.py",
    "python/moonkvsim/integration/vllm/scheduler.py",
)

_RECORDS: Sequence[Mapping[str, Any]] | None = None
_VARIANTS: Mapping[str, ExperimentVariant] | None = None
_SCHEDULES: Mapping[str, FailureSchedule] | None = None
_BUCKET: str | None = None
_CHECKPOINT_DIR: Path | None = None
_SEED: int | None = None
_PEER_BINDING_SEED: int | None = None
_PAPER_CAUSAL_MODE: bool | None = None
_WORKFLOW_CONCURRENCY: int | None = None

COMPACT_REPRESENTATIVE_FIELDS = (
    "failure_schedule",
    "failure_events",
    "recovery_events",
    "failure_focus_spans",
    "failure_impacted_spans",
    "foreground_store_events",
    "aimd_events",
    "scheduler_preemption_events",
    "route_events",
    "peer_target_binding_events",
    "algorithm1_slack_updates",
    "formal_algorithm2_events",
    "gpu_hbm_timelines",
    "normal_hbm_timelines",
    "peer_hbm_timeline",
    "peer_hbm_timelines",
    "store_dram_timeline",
    "store_dram_timelines",
)


def _compact_hash_metadata(
    full: Mapping[str, Any],
    compact: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "compact_sha256": sha256_json(compact),
        "omitted_fields": sorted(set(full) - set(compact)),
    }


def _implementation_fingerprint(root: Path) -> str:
    sources = []
    for relative_path in IMPLEMENTATION_PATHS:
        path = root / relative_path
        sources.append(
            {
                "path": relative_path,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return sha256_json(sources)


def _run_binding_fingerprint(
    records: Sequence[Mapping[str, Any]],
    variant: ExperimentVariant,
    *,
    scenario_id: str,
    schedule: FailureSchedule | None,
    bucket: str,
    seed: int,
    peer_binding_seed: int,
    workflow_concurrency: int = BASE_CONCURRENCY,
    paper_causal_mode: bool = False,
) -> str:
    return sha256_json(
        {
            "protocol": FAILURE_PLAN_PROTOCOL,
            "implementation_fingerprint": _implementation_fingerprint(
                repository_root()
            ),
            "records": records,
            "variant_fingerprint": variant.fingerprint,
            "scenario": scenario_id,
            "failure_schedule_fingerprint": (
                None if schedule is None else schedule.fingerprint
            ),
            "bucket": bucket,
            "workflow_concurrency": workflow_concurrency,
            "seed": seed,
            "peer_binding_seed": peer_binding_seed,
            "paper_causal_mode": paper_causal_mode,
            "repetition": "A",
        }
    )


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
        raw_contract = event.get("impact_contract")
        def parse_contract(raw_value: object, label: str) -> FailureImpactContract:
            contract_mapping = _mapping(raw_value, label)
            return FailureImpactContract(
                active_span_ids=tuple(
                    sorted(
                        str(item)
                        for item in _array(
                            contract_mapping.get("active_span_ids"),
                            f"{label}.active_span_ids",
                        )
                    )
                ),
                queued_span_ids=tuple(
                    sorted(
                        str(item)
                        for item in _array(
                            contract_mapping.get("queued_span_ids"),
                            f"{label}.queued_span_ids",
                        )
                    )
                ),
                reroute_only_queued_span_ids=tuple(
                    sorted(
                        str(item)
                        for item in _array(
                            contract_mapping.get("reroute_only_queued_span_ids"),
                            f"{label}.reroute_only_queued_span_ids",
                        )
                    )
                ),
            )
        contract = (
            None
            if raw_contract is None
            else parse_contract(raw_contract, "impact_contract")
        )
        raw_profile_contracts = event.get("profile_impact_contracts")
        profile_contracts = (
            None
            if raw_profile_contracts is None
            else {
                str(profile_fingerprint): parse_contract(
                    raw_profile_contract,
                    f"profile_impact_contracts.{profile_fingerprint}",
                )
                for profile_fingerprint, raw_profile_contract in _mapping(
                    raw_profile_contracts, "profile_impact_contracts"
                ).items()
            }
        )
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
                physical_target_frozen=(
                    event.get("target_gpu_id_semantics")
                    == "FROZEN_PHYSICAL_FAILURE_TARGET"
                ),
                impact_contract=contract,
                profile_impact_contracts=profile_contracts,
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
    seed: int,
    peer_binding_seed: int,
    paper_causal_mode: bool,
    workflow_concurrency: int,
) -> None:
    global _RECORDS, _VARIANTS, _SCHEDULES, _BUCKET, _CHECKPOINT_DIR, _SEED
    global _PEER_BINDING_SEED
    global _PAPER_CAUSAL_MODE
    global _WORKFLOW_CONCURRENCY
    _RECORDS = records
    _VARIANTS = variants
    _SCHEDULES = schedules
    _BUCKET = bucket
    _CHECKPOINT_DIR = checkpoint_dir
    _SEED = seed
    _PEER_BINDING_SEED = peer_binding_seed
    _PAPER_CAUSAL_MODE = paper_causal_mode
    _WORKFLOW_CONCURRENCY = workflow_concurrency


def _run_one(system_id: str, scenario_id: str) -> dict[str, Any]:
    if (
        _RECORDS is None
        or _VARIANTS is None
        or _SCHEDULES is None
        or _BUCKET is None
        or _CHECKPOINT_DIR is None
        or _SEED is None
        or _PEER_BINDING_SEED is None
        or _PAPER_CAUSAL_MODE is None
        or _WORKFLOW_CONCURRENCY is None
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
            seed=_SEED,
            repetition="A",
            failure_schedule=schedule,
            workflow_concurrency=_WORKFLOW_CONCURRENCY,
            workflow_admission_seed=_SEED,
            peer_binding_seed=_PEER_BINDING_SEED,
            paper_causal_mode=_PAPER_CAUSAL_MODE,
        ),
    )
    print(
        f"[postfix-preview] {scenario_id}/{system_id} DONE "
        f"wall_s={time.monotonic() - started:.1f}",
        flush=True,
    )
    payload = result.payload
    representative = result.representative
    compact_payload = {
        key: payload[key]
        for key in (
            "schema",
            "scenario",
            "variant_id",
            "workload",
            "workflow_admission",
            "randomization",
            "causal_failure_contract",
            "metrics",
            "resource_cost",
            "output_audit",
        )
        if key in payload
    }
    compact_representative = {
        key: representative[key]
        for key in COMPACT_REPRESENTATIVE_FIELDS
        if key in representative
    }
    payload_hash_metadata = _compact_hash_metadata(payload, compact_payload)
    representative_hash_metadata = _compact_hash_metadata(
        representative,
        compact_representative,
    )
    compact_result = {
        "system_id": system_id,
        "scenario": scenario_id,
        "input_binding_fingerprint": _run_binding_fingerprint(
            _RECORDS,
            _VARIANTS[system_id],
            scenario_id=scenario_id,
            schedule=schedule,
            bucket=_BUCKET,
            seed=_SEED,
            peer_binding_seed=_PEER_BINDING_SEED,
            workflow_concurrency=_WORKFLOW_CONCURRENCY,
            paper_causal_mode=_PAPER_CAUSAL_MODE,
        ),
        "variant_fingerprint": _VARIANTS[system_id].fingerprint,
        "failure_schedule": None if schedule is None else schedule.to_dict(),
        "failure_schedule_fingerprint": None if schedule is None else schedule.fingerprint,
        "payload": compact_payload,
        "full_payload_sha256": result.payload_sha256,
        "compact_payload_sha256": payload_hash_metadata["compact_sha256"],
        "payload_omitted_fields": payload_hash_metadata["omitted_fields"],
        "journal_sha256": result.journal_sha256,
        "span_details": list(result.span_details),
        "span_details_sha256": sha256_json(result.span_details),
        "representative": compact_representative,
        "continuous_batch_scheduler_sha256": sha256_json(
            cast(
                Mapping[str, Any],
                representative.get("continuous_batch_scheduler"),
            )
        ),
        "full_representative_sha256": sha256_json(result.representative),
        "compact_representative_sha256": representative_hash_metadata[
            "compact_sha256"
        ],
        "representative_omitted_fields": representative_hash_metadata[
            "omitted_fields"
        ],
    }
    raw_path = _CHECKPOINT_DIR / f"{scenario_id}__{system_id}.raw.json.gz"
    binding = write_raw_evidence(raw_path, {
        "schema": "moonkvsim.aegiskv.paper_primary_raw.v1",
        "input_binding_fingerprint": compact_result["input_binding_fingerprint"],
        "variant": _VARIANTS[system_id].to_dict(),
        "payload": payload, "representative": representative,
        "span_details": list(result.span_details), "journal_sha256": result.journal_sha256,
    })
    compact_result["raw_evidence"] = {"path": raw_path.resolve().as_posix(),
                                       "sha256": binding["sha256"]}
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
    with (
        temporary.open("wb") as stream,
        gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=stream,
            compresslevel=6,
            mtime=0,
        ) as compressed,
    ):
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
    with path.open("rb") as stream:
        magic = stream.read(2)
    opener = gzip.open if magic == b"\x1f\x8b" else open
    with opener(path, "rt", encoding="utf-8") as stream:
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


def _validate_paper_causal_inputs(
    *,
    historical_aggregate: Path | None,
    failure_count: int,
    workflow_limit: int,
    source_workflow_count: int,
) -> None:
    if historical_aggregate is not None:
        raise ValueError("paper causal mode rejects historical failure schedules")
    if failure_count != 1:
        raise ValueError("paper causal mode requires exactly one failure")
    if workflow_limit != source_workflow_count:
        raise ValueError(
            "paper causal mode requires the complete frozen workload: "
            f"--workflow-limit must equal {source_workflow_count}"
        )


def _validate_paper_failure_schedule(schedule: FailureSchedule) -> None:
    if len(schedule.events) != 1:
        raise ValueError("paper causal mode requires exactly one scheduled failure")
    event = schedule.events[0]
    if not event.physical_target_frozen:
        raise ValueError("paper causal mode requires a frozen physical target")
    if event.impact_contract is not None or event.profile_impact_contracts is not None:
        raise ValueError(
            "paper causal mode must not freeze post-treatment victim partitions"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical-aggregate", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--workflow-limit", type=int, default=16)
    parser.add_argument("--failure-count", type=int, default=BASE_FAILURES)
    parser.add_argument("--failure-focus-bucket", default="96k")
    parser.add_argument("--checkpoint-dir", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--peer-binding-seed", type=int, default=0)
    parser.add_argument("--workflow-concurrency", type=int, default=BASE_CONCURRENCY)
    parser.add_argument("--failure-progress-per-mille", type=int, default=600)
    parser.add_argument("--paper-causal-mode", action="store_true")
    args = parser.parse_args(argv)
    if args.jobs < 1 or args.jobs > 4:
        raise ValueError("jobs must be between 1 and 4")
    if args.failure_count < 1:
        raise ValueError("failure-count must be positive")
    if args.seed < 0:
        raise ValueError("seed must be non-negative")
    if args.peer_binding_seed < 0:
        raise ValueError("peer-binding-seed must be non-negative")
    if args.workflow_concurrency < 1:
        raise ValueError("workflow-concurrency must be positive")
    if not 1 <= args.failure_progress_per_mille <= 999:
        raise ValueError(
            "failure-progress-per-mille must be strictly between 0 and 1000"
        )

    root = repository_root()
    implementation_fingerprint = _implementation_fingerprint(root)
    checkpoint_dir = args.checkpoint_dir or args.output.with_suffix(".checkpoints")
    configs = load_experiment_configs(default_config_dir(root), root=root)
    workload_path, manifest_path = workload_paths(configs.requests, root=root)
    records, workload_binding, _manifest = load_frozen_workload(
        workload_path,
        manifest_path,
        retain_exact_token_ids=True,
    )
    source_workflow_ids = tuple(
        sorted({str(record.get("workflow_id", "")) for record in records})
    )
    if args.paper_causal_mode:
        _validate_paper_causal_inputs(
            historical_aggregate=args.historical_aggregate,
            failure_count=args.failure_count,
            workflow_limit=args.workflow_limit,
            source_workflow_count=len(source_workflow_ids),
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
    workflow_concurrency = min(
        args.workflow_concurrency,
        len(selected_workflow_ids),
    )
    base_parameters = model_parameters_from_configs(configs)
    parameters = replace(
        base_parameters,
        failure_progress_per_mille=args.failure_progress_per_mille,
    )
    variants = {
        item.variant_id: item
        for item in core_variants(parameters)
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
        selected_records_fingerprint = sha256_json(selected_records)
        compared_profile_fingerprints = [
            variant.fingerprint
            for variant in sorted(variants.values(), key=lambda item: item.variant_id)
        ]
        plan_binding = {
            "protocol": FAILURE_PLAN_PROTOCOL,
            "implementation_fingerprint": implementation_fingerprint,
            "selected_records_fingerprint": selected_records_fingerprint,
            "parameters_fingerprint": sha256_json(reference_variant.parameters.to_dict()),
            "compared_profile_fingerprints": compared_profile_fingerprints,
            "workflow_concurrency": workflow_concurrency,
            "workflow_admission_seed": args.seed,
            "peer_binding_seed": args.peer_binding_seed,
            "seed": args.seed,
            "strict_context_bucket_for_all_events": True,
            "require_shared_impact_contract": False,
            "freeze_post_treatment_impact_contracts": not args.paper_causal_mode,
        }
        plan_path = checkpoint_dir / "logical-failure-plan.json"
        if plan_path.exists():
            plan_document = _read_checkpoint(plan_path)
            if (
                plan_document.get("workflow_ids") != list(selected_workflow_ids)
                or plan_document.get("failure_count") != args.failure_count
                or plan_document.get("bucket") != bucket
                or plan_document.get("binding") != plan_binding
            ):
                raise ValueError("logical failure plan checkpoint binding mismatch")
            logical_schedule = _legacy_failure_schedule(plan_document.get("schedule"))
        else:
            print("[postfix-preview] SCHEDULE_START", flush=True)
            logical_schedule = derive_failure_schedule(
                selected_records,
                bucket=bucket,
                seed=args.seed,
                parameters=reference_variant.parameters,
                workflow_concurrency=workflow_concurrency,
                workflow_admission_seed=args.seed,
                peer_binding_seed=args.peer_binding_seed,
                failure_count=args.failure_count,
                # A focus is admissible only if it remains causally safe after all
                # prior failures in every measured system.  All events stay in the
                # declared context bucket so failure severity cannot drift by event.
                compared_profiles=tuple(
                    variant.profile
                    for variant in sorted(
                        variants.values(), key=lambda item: item.variant_id
                    )
                ),
                enforce_all_events_in_bucket=True,
                require_shared_impact_contract=False,
                freeze_post_treatment_impact_contracts=not args.paper_causal_mode,
            )
            _write_checkpoint(
                plan_path,
                {
                    "workflow_ids": list(selected_workflow_ids),
                    "failure_count": args.failure_count,
                    "bucket": bucket,
                    "binding": plan_binding,
                    "schedule": logical_schedule.to_dict(),
                    "schedule_fingerprint": logical_schedule.fingerprint,
                },
            )
            print("[postfix-preview] SCHEDULE_DONE", flush=True)
        if args.paper_causal_mode:
            _validate_paper_failure_schedule(logical_schedule)
        schedules = {
            system_id: project_failure_schedule_to_profile(
                selected_records,
                reference=logical_schedule,
                profile=variant.profile,
                parameters=variant.parameters,
                workflow_concurrency=workflow_concurrency,
                seed=args.seed,
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
                schedule = (
                    None
                    if scenario == "no_failure"
                    else schedules[system]
                )
                expected_binding = _run_binding_fingerprint(
                    selected_records,
                    variants[system],
                    scenario_id=scenario,
                    schedule=schedule,
                    bucket=bucket,
                    seed=args.seed,
                    peer_binding_seed=args.peer_binding_seed,
                    workflow_concurrency=workflow_concurrency,
                    paper_causal_mode=args.paper_causal_mode,
                )
                if (
                    checkpoint.get("scenario") != scenario
                    or checkpoint.get("system_id") != system
                    or checkpoint.get("variant_fingerprint")
                    != variants[system].fingerprint
                    or checkpoint.get("failure_schedule_fingerprint")
                    != (None if schedule is None else schedule.fingerprint)
                    or checkpoint.get("input_binding_fingerprint")
                    != expected_binding
                ):
                    raise ValueError("run checkpoint binding mismatch")
                raw_binding = _mapping(checkpoint.get("raw_evidence"), "checkpoint raw evidence")
                raw_path = checkpoint_dir / f"{scenario}__{system}.raw.json.gz"
                if (raw_binding.get("path") != raw_path.resolve().as_posix()
                        or file_sha256(raw_path) != raw_binding.get("sha256")):
                    raise ValueError("run checkpoint complete raw evidence is missing or changed")
                results[scenario][system] = dict(checkpoint)
            else:
                jobs.append((scenario, system))
    context = multiprocessing.get_context("fork")
    with ProcessPoolExecutor(
        max_workers=min(args.jobs, len(jobs)) if jobs else 1,
        mp_context=context,
        initializer=_init_worker,
        initargs=(
            selected_records,
            variants,
            schedules,
            bucket,
            checkpoint_dir,
            args.seed,
            args.peer_binding_seed,
            args.paper_causal_mode,
            workflow_concurrency,
        ),
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
            "seed": args.seed,
            "peer_binding_seed": args.peer_binding_seed,
            "paper_causal_mode": args.paper_causal_mode,
            "workflow_count": len(selected_workflow_ids),
            "source_workflow_count": len(source_workflow_ids),
            "workflow_filtering": len(selected_workflow_ids) != len(source_workflow_ids),
            "workflow_concurrency": workflow_concurrency,
            "workflow_admission_seed": args.seed,
            "failure_progress_per_mille": args.failure_progress_per_mille,
            "failure_count": args.failure_count,
            "focus_span_ids": list(focus_span_ids),
            "parallel_run_count": len(jobs),
            "failure_plan_protocol": FAILURE_PLAN_PROTOCOL,
            "joint_profile_focus_validation": aggregate is None,
            "strict_context_bucket_for_all_events": aggregate is None,
        },
        "source": {
            "implementation_fingerprint": implementation_fingerprint,
            "implementation_paths": list(IMPLEMENTATION_PATHS),
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
                "kind": (
                    "complete_frozen_workload_no_filtering"
                    if args.paper_causal_mode
                    else "complete_workflows_focus_plus_long_context"
                ),
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
