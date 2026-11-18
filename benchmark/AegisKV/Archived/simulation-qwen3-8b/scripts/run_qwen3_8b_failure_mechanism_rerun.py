#!/usr/bin/env python3
"""Capture full base-cell evidence for the Qwen3-8B mechanism figures."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import tempfile
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

AGGREGATE_SCHEMA: Final = "moonkvsim.aegiskv.paper_sweeps.v4"
RERUN_SCHEMA: Final = "moonkvsim.aegiskv.qwen3_8b.failure_mechanism_rerun.v1"
SYSTEMS: Final = ("vanilla_mooncake_dram", "aegiskv_unified")
BASE_FAILURE_COUNT: Final = 2
BASE_CONCURRENCY: Final = 16

_WORKER_RECORDS: Sequence[Mapping[str, Any]] | None = None
_WORKER_VARIANTS: Mapping[str, ExperimentVariant] | None = None
_WORKER_BUCKET: str | None = None


class DetailedRerunError(ValueError):
    """The formal base cell cannot be reproduced exactly."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument("--jobs", type=int, default=2)
    return parser


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DetailedRerunError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise DetailedRerunError(f"{where} must be an array")
    return value


def _text(value: object, where: str) -> str:
    if type(value) is not str or not value:
        raise DetailedRerunError(f"{where} must be a non-empty string")
    return value


def _integer(value: object, where: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise DetailedRerunError(f"{where} must be an integer >= {minimum}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_aggregate(path: Path) -> dict[str, Any]:
    try:
        document = dict(_mapping(json.loads(path.read_text(encoding="utf-8")), "aggregate"))
    except (OSError, json.JSONDecodeError) as error:
        raise DetailedRerunError(f"cannot read aggregate: {error}") from error
    if document.get("schema") != AGGREGATE_SCHEMA or document.get("status") != "PASS":
        raise DetailedRerunError("detailed rerun requires a PASS paper-sweeps v4 artifact")
    fingerprint = document.get("fingerprint")
    unsigned = dict(document)
    unsigned.pop("fingerprint", None)
    if fingerprint != sha256_json(unsigned):
        raise DetailedRerunError("aggregate fingerprint mismatch")
    protocol = _mapping(document.get("protocol"), "aggregate.protocol")
    if (
        protocol.get("model") != "Qwen/Qwen3-8B"
        or protocol.get("dp") != 8
        or protocol.get("workflow_count") != 160
        or protocol.get("base_failure_count") != BASE_FAILURE_COUNT
        or protocol.get("base_workflow_concurrency") != BASE_CONCURRENCY
    ):
        raise DetailedRerunError("aggregate base protocol mismatch")
    evidence = _mapping(document.get("evidence"), "aggregate.evidence")
    if evidence.get("physical_execution") is not False or evidence.get("paper_ready") is not False:
        raise DetailedRerunError("aggregate exceeds the modeled evidence boundary")
    return document


def _base_cell(document: Mapping[str, Any], seed: int) -> Mapping[str, Any]:
    matches = [
        _mapping(raw, "aggregate.raw_seed_cells[]")
        for raw in _array(document.get("raw_seed_cells"), "aggregate.raw_seed_cells")
        if isinstance(raw, Mapping)
        and raw.get("failure_count") == BASE_FAILURE_COUNT
        and raw.get("workflow_concurrency") == BASE_CONCURRENCY
        and raw.get("seed") == seed
    ]
    if len(matches) != 1:
        raise DetailedRerunError(f"aggregate lacks one exact base raw cell for seed {seed}")
    return matches[0]


def _failure_event(raw: object, index: int) -> FailureEventSchedule:
    event = _mapping(raw, f"failure_schedule.events[{index}]")
    workload = _mapping(event.get("workload_position"), f"failure event {index}.workload_position")
    trigger = _mapping(event.get("trigger"), f"failure event {index}.trigger")
    if (
        event.get("type") != "GPU_FAILURE"
        or event.get("target_gpu_id_semantics")
        != "REFERENCE_ROUTE_PROVENANCE_NOT_RUNTIME_FAILURE_TARGET"
        or workload.get("kind") != "COMPLETED_WORKFLOW_FRACTION_NEAREST_COMMON_ROUTE_SPAN"
        or trigger.get("kind") != "FOCUS_SPAN_COMPUTE_PROGRESS"
    ):
        raise DetailedRerunError("failure event semantics mismatch")
    repair = event.get("repair_after_ns")
    if repair is not None:
        repair = _integer(repair, f"failure event {index}.repair_after_ns", minimum=1)
    return FailureEventSchedule(
        failure_id=_text(event.get("failure_id"), f"failure event {index}.failure_id"),
        event_index=_integer(event.get("event_index"), f"failure event {index}.event_index"),
        bucket=_text(event.get("bucket"), f"failure event {index}.bucket"),
        seed=_integer(event.get("seed"), f"failure event {index}.seed"),
        focus_span_id=_text(event.get("focus_span_id"), f"failure event {index}.focus_span_id"),
        target_gpu_id=_text(event.get("target_gpu_id"), f"failure event {index}.target_gpu_id"),
        reference_at_ns=_integer(
            event.get("reference_at_ns"), f"failure event {index}.reference_at_ns"
        ),
        target_workload_progress_per_mille=_integer(
            workload.get("target_progress_per_mille"),
            f"failure event {index}.target_progress_per_mille",
            minimum=1,
        ),
        reference_completed_workflow_count=_integer(
            workload.get("reference_completed_workflow_count"),
            f"failure event {index}.reference_completed_workflow_count",
        ),
        reference_workflow_count=_integer(
            workload.get("reference_workflow_count"),
            f"failure event {index}.reference_workflow_count",
            minimum=1,
        ),
        detection_delay_ns=_integer(
            event.get("detection_delay_ns"), f"failure event {index}.detection_delay_ns"
        ),
        trigger_progress_per_mille=_integer(
            trigger.get("progress_per_mille"),
            f"failure event {index}.trigger_progress_per_mille",
            minimum=1,
        ),
        gpu_recovery_time_ns=repair,
        selection_scope=_text(
            event.get("selection_scope"), f"failure event {index}.selection_scope"
        ),
    )


def _failure_schedule(raw: object, expected_fingerprint: object) -> FailureSchedule:
    document = _mapping(raw, "failure_schedule")
    if document.get("type") != "GPU_FAILURE" or document.get("failure_count") != 2:
        raise DetailedRerunError("base failure schedule must contain two GPU failures")
    schedule = FailureSchedule(
        tuple(
            _failure_event(event, index)
            for index, event in enumerate(_array(document.get("events"), "failure_schedule.events"))
        ),
        selection_scope=_text(document.get("selection_scope"), "failure_schedule.selection_scope"),
    )
    if schedule.to_dict() != document or schedule.fingerprint != expected_fingerprint:
        raise DetailedRerunError("failure schedule canonical reconstruction mismatch")
    return schedule


def _init_worker(
    records: Sequence[Mapping[str, Any]],
    variants: Mapping[str, ExperimentVariant],
    bucket: str,
) -> None:
    global _WORKER_RECORDS, _WORKER_VARIANTS, _WORKER_BUCKET
    _WORKER_RECORDS = records
    _WORKER_VARIANTS = variants
    _WORKER_BUCKET = bucket


def _run_variant(system_id: str, schedule: FailureSchedule, seed: int) -> dict[str, Any]:
    if _WORKER_RECORDS is None or _WORKER_VARIANTS is None or _WORKER_BUCKET is None:
        raise RuntimeError("detailed-rerun worker was not initialized")
    variant = _WORKER_VARIANTS[system_id]
    result = run_study_cell(
        _WORKER_RECORDS,
        CellSpec(
            variant=variant,
            context_bucket=_WORKER_BUCKET,
            scenario=Scenario.GPU_FAILURE,
            seed=seed,
            repetition="A",
            failure_schedule=schedule,
            workflow_concurrency=BASE_CONCURRENCY,
        ),
    )
    return {
        "variant_id": system_id,
        "variant_fingerprint": variant.fingerprint,
        "failure_schedule": schedule.to_dict(),
        "failure_schedule_fingerprint": schedule.fingerprint,
        "payload": result.payload,
        "payload_sha256": result.payload_sha256,
        "journal_sha256": result.journal_sha256,
        "span_details": list(result.span_details),
        "span_details_sha256": sha256_json(result.span_details),
        "representative": result.representative,
        "representative_sha256": sha256_json(result.representative),
    }


def _validate_result(
    system_id: str,
    detailed: Mapping[str, Any],
    compact: Mapping[str, Any],
) -> None:
    compact_run = _mapping(compact.get("run"), f"compact.{system_id}.run")
    if (
        detailed.get("variant_id") != system_id
        or detailed.get("variant_fingerprint") != compact.get("variant_fingerprint")
        or detailed.get("failure_schedule") != compact.get("failure_schedule")
        or detailed.get("failure_schedule_fingerprint")
        != compact.get("failure_schedule_fingerprint")
    ):
        raise DetailedRerunError(f"{system_id} variant/schedule drifted during rerun")
    for field in (
        "payload_sha256",
        "journal_sha256",
        "span_details_sha256",
        "representative_sha256",
    ):
        if detailed.get(field) != compact_run.get(field):
            raise DetailedRerunError(
                f"{system_id} deterministic rerun {field} differs from formal aggregate"
            )
    payload = _mapping(detailed.get("payload"), f"detailed.{system_id}.payload")
    span_details = _array(detailed.get("span_details"), f"detailed.{system_id}.span_details")
    representative = _mapping(
        detailed.get("representative"), f"detailed.{system_id}.representative"
    )
    if (
        sha256_json(payload) != detailed.get("payload_sha256")
        or sha256_json(span_details) != detailed.get("span_details_sha256")
        or sha256_json(representative) != detailed.get("representative_sha256")
    ):
        raise DetailedRerunError(f"{system_id} detailed content hash mismatch")


def run_detailed_rerun(
    *,
    aggregate_path: Path,
    seed: int,
    config_dir: Path | None,
    jobs: int,
) -> dict[str, Any]:
    if seed < 0 or jobs < 1 or jobs > 2:
        raise DetailedRerunError("seed must be non-negative and jobs must be 1 or 2")
    aggregate = _load_aggregate(aggregate_path)
    base_cell = _base_cell(aggregate, seed)
    root = repository_root()
    configs = load_experiment_configs(config_dir or default_config_dir(root))
    workload_path, manifest_path = workload_paths(configs.requests, root=root)
    records, workload_binding, _manifest = load_frozen_workload(
        workload_path,
        manifest_path,
        retain_exact_token_ids=True,
    )
    aggregate_workload = _mapping(
        _mapping(aggregate.get("provenance"), "aggregate.provenance").get("workload"),
        "aggregate.provenance.workload",
    )
    if (
        workload_binding.to_dict()
        != {key: aggregate_workload.get(key) for key in workload_binding.to_dict()}
        or aggregate_workload.get("fingerprint") != workload_binding.fingerprint
        or base_cell.get("workload_fingerprint") != workload_binding.semantic_fingerprint
    ):
        raise DetailedRerunError("current frozen workload differs from the formal aggregate")
    parameters = model_parameters_from_configs(configs)
    variants = {variant.variant_id: variant for variant in core_variants(parameters)}
    selected_variants = {system_id: variants[system_id] for system_id in SYSTEMS}
    systems = _mapping(base_cell.get("systems"), "base_cell.systems")
    if set(systems) != set(SYSTEMS):
        raise DetailedRerunError("formal base cell lacks a required system")
    schedules = {
        system_id: _failure_schedule(
            _mapping(systems[system_id], f"base_cell.systems.{system_id}").get("failure_schedule"),
            _mapping(systems[system_id], f"base_cell.systems.{system_id}").get(
                "failure_schedule_fingerprint"
            ),
        )
        for system_id in SYSTEMS
    }
    focus_ids = {
        tuple(event.focus_span_id for event in schedule.events) for schedule in schedules.values()
    }
    if len(focus_ids) != 1:
        raise DetailedRerunError("formal systems do not share logical focus IDs")
    bucket = _text(base_cell.get("failure_focus_bucket"), "base_cell.failure_focus_bucket")
    context = multiprocessing.get_context("fork")
    results: dict[str, dict[str, Any]] = {}
    with ProcessPoolExecutor(
        max_workers=jobs,
        mp_context=context,
        initializer=_init_worker,
        initargs=(records, selected_variants, bucket),
    ) as executor:
        futures = {
            executor.submit(_run_variant, system_id, schedules[system_id], seed): system_id
            for system_id in SYSTEMS
        }
        for future in as_completed(futures):
            system_id = futures[future]
            results[system_id] = future.result()
    for system_id in SYSTEMS:
        _validate_result(
            system_id,
            results[system_id],
            _mapping(systems[system_id], f"base_cell.systems.{system_id}"),
        )
    body: dict[str, Any] = {
        "schema": RERUN_SCHEMA,
        "status": "PASS",
        "protocol": {
            "model": "Qwen/Qwen3-8B",
            "dp": 8,
            "failure_count": BASE_FAILURE_COUNT,
            "workflow_concurrency": BASE_CONCURRENCY,
            "scenario": "gpu_failure",
            "repetition": "A",
            "seed": seed,
            "modeled_uncalibrated": True,
            "parallel_system_jobs": jobs,
        },
        "formal_aggregate": {
            "schema": aggregate["schema"],
            "path": aggregate_path.resolve().as_posix(),
            "sha256": _sha256_file(aggregate_path),
            "fingerprint": aggregate["fingerprint"],
            "base_cell_id": base_cell["cell_id"],
        },
        "workload": {
            **workload_binding.to_dict(),
            "fingerprint": workload_binding.fingerprint,
        },
        "systems": {system_id: results[system_id] for system_id in SYSTEMS},
        "determinism_gate": {
            "payload_sha256_exact_match": True,
            "journal_sha256_exact_match": True,
            "span_details_sha256_exact_match": True,
            "representative_sha256_exact_match": True,
        },
    }
    return {**body, "fingerprint": sha256_json(body)}


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise DetailedRerunError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    artifact = run_detailed_rerun(
        aggregate_path=args.aggregate,
        seed=args.seed,
        config_dir=args.config_dir,
        jobs=args.jobs,
    )
    _write_json_atomic(args.output, artifact)
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": args.output.resolve().as_posix(),
                "fingerprint": artifact["fingerprint"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
