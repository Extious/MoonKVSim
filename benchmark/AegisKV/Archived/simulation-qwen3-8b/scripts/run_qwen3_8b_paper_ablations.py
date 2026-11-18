#!/usr/bin/env python3
"""Execute all four algorithm arms, F0/F1, on five paired admission orders.

Full gzip raw evidence and hash-bound checkpoints are retained before auditing.
The logical intervention is selected once from the full system's F0 oracle;
each arm fails the GPU naturally serving that request at the same progress.
This estimates a policy-specific logical failure, not an identical physical shock.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import subprocess
import time
import traceback
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

from run_aegiskv_paper_sweeps import _failure_schedule_from_dict, _write_json_atomic

from moonkvsim.aegiskv.experiment import (
    CellSpec,
    ExperimentVariant,
    FailureSchedule,
    Scenario,
    ablation_variants,
    derive_failure_schedule,
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
from moonkvsim.aegiskv.formal_algorithm_audit import (
    audit_continuous_scheduler_evidence,
    audit_formal_algorithm_run,
    audit_lru_ablation_run,
    audit_store_only_control_run,
)
from moonkvsim.aegiskv.paper_ablation_statistics import ARMS, build_ablation_statistics
from moonkvsim.aegiskv.paper_artifacts import file_sha256, load_raw_evidence, write_raw_evidence
from moonkvsim.aegiskv.paper_timing_statistics import TIMING_MODELS, build_timing_statistics
from moonkvsim.common.hash import sha256_json

_RECORDS: Sequence[Mapping[str, Any]] = ()
_VARIANTS: tuple[ExperimentVariant, ...] = ()
_BUCKET = "96k"
_CONTRACT: dict[str, Any] = {}


def _audit_and_summarize(
    raw: Mapping[str, Any], *, arm: str, focus_span_id: str, prompt_tokens: int
) -> dict[str, Any]:
    payload, representative = raw["payload"], raw["representative"]
    scheduler = audit_continuous_scheduler_evidence(payload, representative).to_dict()
    if arm.startswith("store_only"):
        policy = audit_store_only_control_run(payload, representative)
    elif arm == "lru_eviction":
        policy = audit_lru_ablation_run(payload, representative)
    else:
        policy = audit_formal_algorithm_run(
            payload,
            representative,
            expected_aimd_enabled=arm != "no_aimd",
        ).to_dict()
    effects = payload["metrics"]["policy_effects"]
    if effects["slack_signal_enabled"] != (
        arm != "no_slack" and not arm.startswith("store_only")
    ):
        raise ValueError("executed slack switch differs from the declared arm")
    metrics = payload["metrics"]
    if payload["workload"]["workflow_count"] != 160 or len(raw["span_details"]) != 1304:
        raise ValueError("ablation must execute all 160 workflows and 1304 spans")
    failed = metrics["failure_impact"]["failure_event_count"]
    expected_failed = int(payload["failure_schedule"] is not None)
    if failed != expected_failed or metrics["gpu_capacity_recovery"]["completed_count"] != failed:
        raise ValueError("planned failure or repair was not executed")
    tokens = None
    focus = next(item for item in raw["span_details"] if item["span_id"] == focus_span_id)
    if failed:
        if focus["failure_at_ns"] is None:
            raise ValueError("logical focus span was not failure-impacted")
        tokens = {
            "prompt": prompt_tokens,
            "normal": focus["recovery_normal_hbm_local_tokens"],
            "peer": focus["restored_peer_tokens"],
            "store": focus["restored_store_tokens"],
            "recompute": focus["recompute_tokens"],
        }
        if sum(value for key, value in tokens.items() if key != "prompt") != prompt_tokens:
            raise ValueError("focus prompt recovery does not conserve tokens")
    cost = metrics["resource_cost"]
    if cost["transfer_byte_conservation_valid"] is not True:
        raise ValueError("transfer byte conservation failed")
    return {
        "payload_sha256": sha256_json(payload),
        "representative_sha256": sha256_json(representative),
        "span_details_sha256": sha256_json(raw["span_details"]),
        "workflow_admission": payload["workflow_admission"],
        "randomization": payload["randomization"],
        "wct_ns": metrics["workflow_completion_time_ns"]["by_workflow_id"],
        "workload_end_ns": metrics["workload_end_ns"],
        "failure_event_count": failed,
        "focus_tokens": tokens,
        "focus_detail": focus,
        "failure_impact": metrics["failure_impact"],
        "protection_transferred_bytes": sum(
            value for cause, value in cost["cause_bytes"].items() if cause.endswith("_PROTECTION")
        ),
        "resource_cost": cost,
        "continuous_scheduler_audit": scheduler,
        "policy_audit": policy,
    }


def _seed(seed: int, output: Path) -> dict[str, Any]:
    full = next(variant for variant in _VARIANTS if variant.variant_id == "full")
    directory = output / f"seed-{seed}"
    directory.mkdir(parents=True, exist_ok=True)
    plan_path = directory / "logical-plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        if plan["contract_fingerprint"] != _CONTRACT["fingerprint"]:
            raise ValueError("checkpoint source/config/workload contract changed")
        schedule = _failure_schedule_from_dict(plan["schedule"])
        if schedule.fingerprint != plan["schedule_fingerprint"]:
            raise ValueError("checkpoint schedule fingerprint changed")
    else:
        oracle = derive_failure_schedule(
            _RECORDS,
            bucket=_BUCKET,
            seed=seed,
            parameters=full.parameters,
            workflow_concurrency=16,
            workflow_admission_seed=seed,
            peer_binding_seed=0,
            failure_count=1,
            compared_profiles=(full.profile,),
            freeze_post_treatment_impact_contracts=False,
        )
        schedule = FailureSchedule(
            events=tuple(
                replace(
                    event,
                    physical_target_frozen=False,
                    impact_contract=None,
                    profile_impact_contracts=None,
                )
                for event in oracle.events
            ),
            selection_scope="fixed_full_F0_logical_focus_natural_arm_routing",
        )
        plan = {
            "contract_fingerprint": _CONTRACT["fingerprint"],
            "schedule": schedule.to_dict(),
            "schedule_fingerprint": schedule.fingerprint,
            "oracle_schedule": oracle.to_dict(),
        }
        _write_json_atomic(plan_path, plan)
    focus_id = schedule.events[0].focus_span_id
    record = next(record for record in _RECORDS if record["span_id"] == focus_id)
    runs: dict[str, dict[str, Any]] = {}
    for scenario in (Scenario.NO_FAILURE, Scenario.GPU_FAILURE):
        runs[scenario.value] = {}
        for variant in _VARIANTS:
            arm = variant.variant_id
            stem = f"{scenario.value}-{arm}"
            raw_path, checkpoint_path = (
                directory / f"{stem}.raw.json.gz",
                directory / f"{stem}.json",
            )
            identity = {
                "contract_fingerprint": _CONTRACT["fingerprint"],
                "seed": seed,
                "scenario": scenario.value,
                "variant_fingerprint": variant.fingerprint,
                "schedule_fingerprint": schedule.fingerprint,
            }
            started = time.monotonic()
            if checkpoint_path.exists():
                checkpoint = json.loads(checkpoint_path.read_text())
                if checkpoint["identity"] != identity:
                    raise ValueError(f"checkpoint execution identity changed: {stem}")
                raw = load_raw_evidence(
                    raw_path, expected_sha256=checkpoint["raw_evidence"]["sha256"]
                )
                if raw["identity"] != identity:
                    raise ValueError("raw execution identity differs from checkpoint")
                summary = _audit_and_summarize(
                    raw, arm=arm, focus_span_id=focus_id, prompt_tokens=int(record["prompt_tokens"])
                )
                if summary != checkpoint["summary"]:
                    raise ValueError("checkpoint summary does not reconstruct from raw evidence")
            else:
                result = run_study_cell(
                    _RECORDS,
                    CellSpec(
                        variant=variant,
                        context_bucket=_BUCKET,
                        scenario=scenario,
                        seed=seed,
                        repetition="A",
                        workflow_concurrency=16,
                        workflow_admission_seed=seed,
                        peer_binding_seed=0,
                        failure_schedule=schedule if scenario is Scenario.GPU_FAILURE else None,
                    ),
                )
                raw = {
                    "schema": "moonkvsim.aegiskv.paper_ablation_raw.v1",
                    "identity": identity,
                    "variant": variant.to_dict(),
                    "payload": result.payload,
                    "span_details": result.span_details,
                    "representative": result.representative,
                    "journal_sha256": result.journal_sha256,
                }
                binding = write_raw_evidence(raw_path, raw)
                summary = _audit_and_summarize(
                    raw, arm=arm, focus_span_id=focus_id, prompt_tokens=int(record["prompt_tokens"])
                )
                checkpoint = {"identity": identity, "raw_evidence": binding, "summary": summary}
                _write_json_atomic(checkpoint_path, checkpoint)
            runs[scenario.value][arm] = {
                **summary,
                "raw_evidence": {
                    "file": raw_path.relative_to(output).as_posix(),
                    "sha256": checkpoint["raw_evidence"]["sha256"],
                },
            }
            print(f"PASS seed={seed} {stem} wall_s={time.monotonic() - started:.1f}", flush=True)
            del raw
    cell = {
        "seed": seed,
        "focus_span_id": focus_id,
        "focus_workflow_id": record["workflow_id"],
        "plan": plan,
        "runs": runs,
    }
    _write_json_atomic(directory / "cell.json", cell)
    return cell


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, default=default_config_dir(repository_root()))
    parser.add_argument("--jobs", type=int, default=5)
    parser.add_argument("--seeds", default="0,1,2,3,4", help="subsets are diagnostic only")
    parser.add_argument("--study", choices=("ablations", "timing-robustness"),
                        default="ablations")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        seeds = tuple(int(value) for value in args.seeds.split(","))
        if (
            args.jobs < 1
            or not seeds
            or len(set(seeds)) != len(seeds)
            or set(seeds) - set(range(5))
        ):
            raise ValueError("invalid jobs or seeds")
        root = repository_root()
        configs = load_experiment_configs(args.config_dir, root=root)
        workload_path, manifest_path = workload_paths(configs.requests, root=root)
        records, workload_binding, manifest = load_frozen_workload(
            workload_path,
            manifest_path,
            retain_exact_token_ids=True,
        )
        variants_by_id = {
            item.variant_id: item
            for item in ablation_variants(model_parameters_from_configs(configs))
        }
        variants = tuple(variants_by_id[arm] for arm in ARMS)
        if args.study == "timing-robustness":
            from moonkvsim.aegiskv.experiment import core_variants

            parameters = model_parameters_from_configs(configs)
            selected = []
            for beta, (aegis_id, control_id) in TIMING_MODELS.items():
                model_parameters = replace(parameters, batch_serialization_per_mille=beta)
                for variant in core_variants(model_parameters):
                    if variant.variant_id in {"aegiskv_unified", "vanilla_mooncake_dram"}:
                        selected.append(replace(
                            variant, suite="timing_robustness",
                            variant_id=(aegis_id if variant.variant_id == "aegiskv_unified"
                                        else control_id),
                        ))
            variants = tuple(selected)
        source_paths = sorted(
            {
                *root.joinpath("python").rglob("*.py"),
                *root.joinpath("benchmark/AegisKV/experiments/scripts").glob("*.py"),
                root / "pyproject.toml",
                root / "uv.lock",
            }
        )
        body = {
            "schema": "moonkvsim.aegiskv.paper-ablation-contract.v1",
            "study": args.study,
            "source_files": {
                path.relative_to(root).as_posix(): file_sha256(path) for path in source_paths
            },
            "config_files": {
                name: file_sha256(args.config_dir / name)
                for name in ("requests.json", "engine.json", "failure.json")
            },
            "workload_binding": workload_binding.to_dict(),
            "variants": [variant.to_dict() for variant in variants],
            "seeds": list(seeds),
            "workflow_concurrency": 16,
            "peer_binding_seed": 0,
            "intervention": "full-F0-selected logical focus, natural GPU, 60% request progress",
            "inference_scope": "fixed derived FanOutQA workload, ideal duration simulation only",
            "effect_direction_gate_applied": False,
        }
        contract = {**body, "fingerprint": sha256_json(body)}
        contract_path = output / "contract.json"
        if contract_path.exists() and json.loads(contract_path.read_text()) != contract:
            raise ValueError("existing output belongs to a different frozen contract")
        _write_json_atomic(contract_path, contract)
        git_head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip()
        git_clean = not subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True
        ).strip()
        global _RECORDS, _VARIANTS, _BUCKET, _CONTRACT
        _RECORDS, _VARIANTS, _CONTRACT = records, variants, contract
        counts = manifest["selection"]["audit"]["context_bucket_counts"]
        _BUCKET = next(bucket for bucket in ("128k", "96k", "64k", "32k", "8k") if counts[bucket])
        cells = []
        with ProcessPoolExecutor(
            max_workers=args.jobs, mp_context=multiprocessing.get_context("fork")
        ) as pool:
            futures = {pool.submit(_seed, seed, output): seed for seed in seeds}
            for future in as_completed(futures):
                cells.append(future.result())
        complete = set(seeds) == set(range(5))
        aggregate = {
            "schema": ("moonkvsim.aegiskv.paper-ablations.v1" if args.study == "ablations"
                       else "moonkvsim.aegiskv.paper-timing-robustness.v1"),
            "status": "PASS" if complete else "DIAGNOSTIC_SUBSET",
            "source_contract_fingerprint": contract["fingerprint"],
            "git_head": git_head,
            "git_worktree_clean": git_clean,
            "cells": sorted(cells, key=lambda cell: cell["seed"]),
            "statistics": (
                (build_ablation_statistics(cells) if args.study == "ablations"
                 else build_timing_statistics(cells)) if complete else None
            ),
        }
        _write_json_atomic(
            output / f"{args.study}.json", {**aggregate, "fingerprint": sha256_json(aggregate)}
        )
        return 0
    except Exception as error:
        _write_json_atomic(
            output / "failure.json",
            {
                "status": "FAILED",
                "error": str(error),
                "traceback": traceback.format_exc(),
            },
        )
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
