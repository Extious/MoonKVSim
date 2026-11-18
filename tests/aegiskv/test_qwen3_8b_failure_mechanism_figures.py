from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from moonkvsim.common.hash import sha256_json

ROOT = Path(__file__).resolve().parents[2]
BUILDER = (
    ROOT / "benchmark/AegisKV/experiments/scripts/build_qwen3_8b_failure_mechanism_artifact.py"
)
GENERATOR = (
    ROOT / "benchmark/AegisKV/experiments/results/figures/"
    "generate_qwen3_8b_failure_mechanism_figures.py"
)
RERUNNER = ROOT / "benchmark/AegisKV/experiments/scripts/run_qwen3_8b_failure_mechanism_rerun.py"
MOONCAKE = "vanilla_mooncake_dram"
AEGISKV = "aegiskv_unified"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _refingerprint(value: dict[str, Any]) -> None:
    value.pop("fingerprint", None)
    value["fingerprint"] = sha256_json(value)


def _schedule(system_id: str) -> dict[str, Any]:
    return {
        "schema": "fixture.schedule.v1",
        "seed": 0,
        "system_id": system_id,
        "events": [
            {"failure_id": "failure-0", "focus_span_id": "focus-0"},
            {"failure_id": "failure-1", "focus_span_id": "focus-1"},
        ],
    }


def _focus_detail(system_id: str, index: int) -> dict[str, Any]:
    failure = (index + 1) * 1_000_000_000
    aegis = system_id == AEGISKV
    return {
        "span_id": f"focus-{index}",
        "workflow_id": f"workflow-{index}",
        "gpu_id": f"gpu-{index}",
        "route_version": 1,
        "released_ns": 0,
        "compute_start_ns": failure + 50_000_000,
        "completed_ns": failure + 300_000_000,
        "base_duration_ns": 500_000_000,
        "reused_primary_tokens": 0,
        "reused_peer_tokens": 0,
        "reused_store_tokens": 0,
        "recovery_normal_hbm_local_tokens": 100,
        "restored_peer_tokens": 500 if aegis else 0,
        "restored_peer_local_tokens": 200 if aegis else 0,
        "restored_peer_d2d_tokens": 300 if aegis else 0,
        "restored_store_tokens": 300,
        "recompute_tokens": 100 if aegis else 600,
        "failure_at_ns": failure,
        "recovery_ready_ns": failure + 120_000_000,
        "prompt_recompute_start_ns": failure + 50_000_000,
        "prompt_recompute_complete_ns": failure + 100_000_000,
        "silent_replay_start_ns": failure + 100_000_000,
        "silent_replay_complete_ns": failure + 120_000_000,
        "resume_decode_start_ns": failure + 120_000_000,
        "output_tokens": 100,
        "external_output_emissions": 100,
    }


def _representative(system_id: str) -> dict[str, Any]:
    aegis = system_id == AEGISKV
    failure_events = []
    recovery_events = []
    recovery_source_events = []
    transfers = []
    steps = []
    driver_failures = []
    for index in range(2):
        span_id = f"focus-{index}"
        failure = (index + 1) * 1_000_000_000
        failure_events.append(
            {
                "timestamp_ns": failure,
                "event": "FAILURE_INJECT",
                "failure_id": f"failure-{index}",
                "logical_trigger": {
                    "focus_span_id": span_id,
                    "continuous_progress_evidence": {
                        "kind": "CONTINUOUS_SCHEDULER_TOKEN_PROGRESS",
                        "route_version": 0,
                        "total_request_tokens": 1100,
                        "prompt_tokens": 1000,
                        "output_tokens": 100,
                        "num_computed_tokens_before": 400,
                        "num_computed_tokens_after": 600,
                        "step_start_ns": failure - 100_000_000,
                        "step_end_ns": failure + 100_000_000,
                        "resolved_at_ns": failure,
                    },
                },
            }
        )
        steps.append(
            {
                "start_ns": failure - 500_000_000,
                "planned_end_ns": failure - 300_000_000,
                "effective_end_ns": failure - 300_000_000,
                "participants": [{"request_id": span_id, "route_version": 0}],
            }
        )
        steps.append(
            {
                "start_ns": failure - 100_000_000,
                "planned_end_ns": failure + 100_000_000,
                "effective_end_ns": failure,
                "participants": [{"request_id": span_id, "route_version": 0}],
            }
        )
        driver_failures.append(
            {
                "timestamp_ns": failure,
                "router_committed_outputs_before_requeue": {span_id: 20},
            }
        )
        source_tokens = {
            "NORMAL_HBM_LOCAL": 100,
            "PEER_HBM": 500 if aegis else 0,
            "STORE_DRAM": 300,
            "RECOMPUTE": 100 if aegis else 600,
        }
        recovery_events.extend(
            [
                {
                    "timestamp_ns": failure + 10_000_000,
                    "event": "RECOVERY_PLAN",
                    "span_id": span_id,
                    "source_tokens": source_tokens,
                },
                {
                    "timestamp_ns": failure + 40_000_000,
                    "event": "CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED",
                    "span_id": span_id,
                },
                {
                    "timestamp_ns": failure + 50_000_000,
                    "event": "PROMPT_SUFFIX_RECOMPUTE_START",
                    "span_id": span_id,
                },
                {
                    "timestamp_ns": failure + 100_000_000,
                    "event": "PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
                    "span_id": span_id,
                },
                {
                    "timestamp_ns": failure + 100_000_000,
                    "event": "SILENT_REPLAY_START",
                    "span_id": span_id,
                },
                {
                    "timestamp_ns": failure + 120_000_000,
                    "event": "SILENT_REPLAY_COMPLETE",
                    "span_id": span_id,
                },
            ]
        )
        recovery_source_events.append(
            {
                "timestamp_ns": failure + 10_000_000,
                "event": "NORMAL_HBM_LOCAL_ADOPTION",
                "span_id": span_id,
            }
        )
        if aegis:
            recovery_source_events.append(
                {
                    "timestamp_ns": failure + 10_000_000,
                    "event": "PEER_HBM_LOCAL_ACTIVATION",
                    "span_id": span_id,
                }
            )
            transfers.append(
                {
                    "transfer_id": f"peer-{index}",
                    "span_id": span_id,
                    "cause": "AEGIS_RECOVERY_PEER_HBM",
                    "status": "COMMITTED",
                    "ready_ns": failure + 20_000_000,
                    "start_ns": failure + 22_000_000,
                    "end_ns": failure + 35_000_000,
                    "terminal_ns": failure + 35_000_000,
                    "bytes": 3000,
                    "transferred_bytes": 3000,
                    "aborted_bytes": 0,
                }
            )
        transfers.append(
            {
                "transfer_id": f"store-{index}",
                "span_id": span_id,
                "cause": "AEGIS_RECOVERY_STORE_DRAM",
                "status": "COMMITTED",
                "ready_ns": failure + 20_000_000,
                "start_ns": failure + 22_000_000,
                "end_ns": failure + 40_000_000,
                "terminal_ns": failure + 40_000_000,
                "bytes": 3000,
                "transferred_bytes": 3000,
                "aborted_bytes": 0,
            }
        )
    return {
        "failure_events": failure_events,
        "recovery_events": recovery_events,
        "recovery_source_events": recovery_source_events,
        "transfers": transfers,
        "continuous_batch_scheduler": {
            "steps": steps,
            "failures": driver_failures,
        },
    }


def _system(system_id: str) -> dict[str, Any]:
    schedule = _schedule(system_id)
    payload = {
        "variant_fingerprint": f"{system_id}-fingerprint",
        "scenario": "gpu_failure",
        "failure_schedule": schedule,
        "workload": {"workflow_count": 160},
    }
    span_details = [_focus_detail(system_id, index) for index in range(2)]
    representative = _representative(system_id)
    return {
        "variant_id": system_id,
        "variant_fingerprint": f"{system_id}-fingerprint",
        "failure_schedule": schedule,
        "failure_schedule_fingerprint": sha256_json(schedule),
        "payload": payload,
        "payload_sha256": sha256_json(payload),
        "journal_sha256": "a" * 64 if system_id == MOONCAKE else "b" * 64,
        "span_details": span_details,
        "span_details_sha256": sha256_json(span_details),
        "representative": representative,
        "representative_sha256": sha256_json(representative),
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    workload_path = tmp_path / "workload.jsonl"
    records = []
    for index in range(160):
        records.append(
            {
                "span_id": f"focus-{index}" if index < 2 else f"span-{index}",
                "workflow_id": f"workflow-{index}",
                "prompt_tokens": 1000,
                "output_tokens": 100,
            }
        )
    workload_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    workload_sha = hashlib.sha256(workload_path.read_bytes()).hexdigest()
    semantic = "f" * 64
    systems = {MOONCAKE: _system(MOONCAKE), AEGISKV: _system(AEGISKV)}
    aggregate_systems = {}
    for system_id, detailed in systems.items():
        aggregate_systems[system_id] = {
            "variant_id": system_id,
            "variant_fingerprint": detailed["variant_fingerprint"],
            "failure_schedule": detailed["failure_schedule"],
            "failure_schedule_fingerprint": detailed["failure_schedule_fingerprint"],
            "run": {
                "payload_sha256": detailed["payload_sha256"],
                "journal_sha256": detailed["journal_sha256"],
                "span_details_sha256": detailed["span_details_sha256"],
                "representative_sha256": detailed["representative_sha256"],
            },
        }
    aggregate: dict[str, Any] = {
        "schema": "moonkvsim.aegiskv.paper_sweeps.v4",
        "status": "PASS",
        "protocol": {
            "base_failure_count": 2,
            "base_workflow_concurrency": 16,
            "workflow_count": 160,
            "model": "Qwen/Qwen3-8B",
            "dp": 8,
        },
        "evidence": {"physical_execution": False, "paper_ready": False},
        "provenance": {
            "workload": {
                "sha256": workload_sha,
                "record_count": 160,
                "semantic_fingerprint": semantic,
            }
        },
        "raw_seed_cells": [
            {
                "failure_count": 2,
                "workflow_concurrency": 16,
                "seed": 0,
                "workload_fingerprint": semantic,
                "failure_focus_span_ids_by_system": {
                    MOONCAKE: ["focus-0", "focus-1"],
                    AEGISKV: ["focus-0", "focus-1"],
                },
                "run_content_bindings": {
                    MOONCAKE: {"content_sha256": "c" * 64},
                    AEGISKV: {"content_sha256": "d" * 64},
                },
                "systems": aggregate_systems,
            }
        ],
    }
    _refingerprint(aggregate)
    aggregate_path = tmp_path / "aggregate.json"
    _write_json(aggregate_path, aggregate)
    rerun: dict[str, Any] = {
        "schema": "moonkvsim.aegiskv.qwen3_8b.failure_mechanism_rerun.v1",
        "status": "PASS",
        "protocol": {
            "model": "Qwen/Qwen3-8B",
            "dp": 8,
            "failure_count": 2,
            "workflow_concurrency": 16,
            "scenario": "gpu_failure",
            "repetition": "A",
            "seed": 0,
            "modeled_uncalibrated": True,
        },
        "formal_aggregate": {
            "schema": aggregate["schema"],
            "fingerprint": aggregate["fingerprint"],
        },
        "workload": {
            "sha256": workload_sha,
            "record_count": 160,
            "semantic_fingerprint": semantic,
        },
        "systems": systems,
    }
    _refingerprint(rerun)
    rerun_path = tmp_path / "rerun.json"
    _write_json(rerun_path, rerun)
    return aggregate_path, rerun_path, workload_path


def test_builder_binds_full_rerun_to_formal_base_cell_and_conserves_phases(
    tmp_path: Path,
) -> None:
    builder = _load(BUILDER, "_test_qwen8_mechanism_builder")
    aggregate, rerun, workload = _fixture(tmp_path)

    artifact = builder.build_mechanism_artifact(
        aggregate_path=aggregate,
        detailed_rerun_path=rerun,
        workload_path=workload,
    )

    assert artifact["status"] == "PASS"
    assert len(artifact["observations"]) == 4
    assert artifact["evidence"]["source_windows_parallel_non_additive"] is True
    for observation in artifact["observations"]:
        assert (
            sum(observation["exclusive_latency_phases_ns"].values())
            == observation["failure_to_completion_ns"]
        )
        tokens = observation["recovery_tokens"]
        assert (
            tokens["normal_hbm_local"]
            + tokens["peer_hbm"]
            + tokens["store_dram"]
            + tokens["prompt_recompute"]
            == tokens["total_prompt"]
        )
    mooncake = next(
        item
        for item in artifact["observations"]
        if item["system_id"] == MOONCAKE and item["span_id"] == "focus-0"
    )
    aegis = next(
        item
        for item in artifact["observations"]
        if item["system_id"] == AEGISKV and item["span_id"] == "focus-0"
    )
    assert mooncake["recovery_tokens"]["prompt_recompute"] == 600
    assert aegis["recovery_tokens"]["peer_hbm"] == 500
    assert {item["source"] for item in aegis["source_transfer_intervals"]} == {
        "peer_hbm",
        "store_dram",
    }


def test_builder_rejects_any_full_content_hash_drift(tmp_path: Path) -> None:
    builder = _load(BUILDER, "_test_qwen8_mechanism_hash_builder")
    aggregate, rerun_path, workload = _fixture(tmp_path)
    rerun = json.loads(rerun_path.read_text(encoding="utf-8"))
    rerun["systems"][AEGISKV]["payload"]["unexpected"] = True
    rerun["systems"][AEGISKV]["payload_sha256"] = sha256_json(rerun["systems"][AEGISKV]["payload"])
    _refingerprint(rerun)
    _write_json(rerun_path, rerun)

    with pytest.raises(builder.MechanismArtifactError, match="formal aggregate"):
        builder.build_mechanism_artifact(
            aggregate_path=aggregate,
            detailed_rerun_path=rerun_path,
            workload_path=workload,
        )


def test_builder_rejects_missing_source_transfer_evidence(tmp_path: Path) -> None:
    builder = _load(BUILDER, "_test_qwen8_mechanism_transfer_builder")
    aggregate_path, rerun_path, workload = _fixture(tmp_path)
    aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
    rerun = json.loads(rerun_path.read_text(encoding="utf-8"))
    representative = rerun["systems"][AEGISKV]["representative"]
    representative["transfers"] = [
        item
        for item in representative["transfers"]
        if not (item["span_id"] == "focus-0" and item["cause"] == "AEGIS_RECOVERY_PEER_HBM")
    ]
    new_hash = sha256_json(representative)
    rerun["systems"][AEGISKV]["representative_sha256"] = new_hash
    aggregate["raw_seed_cells"][0]["systems"][AEGISKV]["run"]["representative_sha256"] = new_hash
    _refingerprint(aggregate)
    rerun["formal_aggregate"]["fingerprint"] = aggregate["fingerprint"]
    _refingerprint(rerun)
    _write_json(aggregate_path, aggregate)
    _write_json(rerun_path, rerun)

    with pytest.raises(builder.MechanismArtifactError, match="Peer-HBM transfer evidence"):
        builder.build_mechanism_artifact(
            aggregate_path=aggregate_path,
            detailed_rerun_path=rerun_path,
            workload_path=workload,
        )


def test_builder_accepts_zero_length_silent_replay_without_start_event() -> None:
    builder = _load(BUILDER, "_test_qwen8_zero_silent_replay_builder")
    representative = _representative(AEGISKV)
    representative["continuous_batch_scheduler"]["failures"][0][
        "router_committed_outputs_before_requeue"
    ]["focus-0"] = 0
    representative["recovery_events"] = [
        event
        for event in representative["recovery_events"]
        if not (event["span_id"] == "focus-0" and event["event"] == "SILENT_REPLAY_START")
    ]
    for event in representative["recovery_events"]:
        if event["span_id"] == "focus-0" and event["event"] == "SILENT_REPLAY_COMPLETE":
            event["timestamp_ns"] = 1_100_000_000
    detail = _focus_detail(AEGISKV, 0)
    detail["silent_replay_start_ns"] = 1_100_000_000
    detail["silent_replay_complete_ns"] = 1_100_000_000
    detail["recovery_ready_ns"] = 1_100_000_000
    detail["resume_decode_start_ns"] = 1_100_000_000

    observation = builder._phase_record(
        system_id=AEGISKV,
        span_id="focus-0",
        detail=detail,
        representative=representative,
        workload_record={
            "span_id": "focus-0",
            "workflow_id": "workflow-0",
            "prompt_tokens": 1000,
            "output_tokens": 100,
        },
    )

    assert observation["pre_failure"]["committed_output_tokens_at_failure"] == 0
    assert observation["exclusive_latency_phases_ns"]["silent_replay_ns"] == 0


def test_figure_pipeline_emits_four_separate_pdf_png_figures(tmp_path: Path) -> None:
    builder = _load(BUILDER, "_test_qwen8_mechanism_figure_builder")
    generator = _load(GENERATOR, "_test_qwen8_mechanism_generator")
    aggregate, rerun, workload = _fixture(tmp_path)
    artifact = builder.build_mechanism_artifact(
        aggregate_path=aggregate,
        detailed_rerun_path=rerun,
        workload_path=workload,
    )
    artifact_path = tmp_path / "mechanism.json"
    _write_json(artifact_path, artifact)
    output_dir = tmp_path / "figures"
    pdf_dir = tmp_path / "pdf"

    assert (
        generator.main(
            [
                "--artifact",
                str(artifact_path),
                "--output-dir",
                str(output_dir),
                "--pdf-output-dir",
                str(pdf_dir),
            ]
        )
        == 0
    )

    assert {path.stem for path in output_dir.glob("*.png")} == set(generator.EXPECTED_STEMS)
    assert {path.stem for path in output_dir.glob("*.pdf")} == set(generator.EXPECTED_STEMS)
    assert {path.stem for path in pdf_dir.glob("*.pdf")} == set(generator.EXPECTED_STEMS)
    manifest = json.loads((output_dir / "FIGURE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS"
    assert manifest["figure_count"] == 4
    assert manifest["forbidden_label_scan"]["status"] == "PASS"
    assert all(
        hashlib.sha256((output_dir / item["pdf"]["file"]).read_bytes()).hexdigest()
        == item["pdf"]["sha256"]
        for item in manifest["figures"]
    )


def test_figure_validator_rejects_nonconserving_latency(tmp_path: Path) -> None:
    builder = _load(BUILDER, "_test_qwen8_mechanism_bad_figure_builder")
    generator = _load(GENERATOR, "_test_qwen8_mechanism_bad_generator")
    aggregate, rerun, workload = _fixture(tmp_path)
    artifact = builder.build_mechanism_artifact(
        aggregate_path=aggregate,
        detailed_rerun_path=rerun,
        workload_path=workload,
    )
    broken = deepcopy(artifact)
    broken["observations"][0]["exclusive_latency_phases_ns"]["prompt_recompute_ns"] += 1
    _refingerprint(broken)

    with pytest.raises(ValueError, match="do not conserve"):
        generator._validate_document(broken)


def test_rendered_labels_exclude_deprecated_projection_wording() -> None:
    source = GENERATOR.read_text(encoding="utf-8")
    for forbidden in ("Projected", "Simulation projection", "No-measured"):
        assert source.count(f'"{forbidden}"') == 1
    assert "np.interp" not in source
    assert "polyfit" not in source.lower()
    assert "savgol" not in source.lower()
    assert source.count("plt.subplots(") == 4
    assert "plt.subplot(" not in source


def _canonical_failure_schedule() -> dict[str, Any]:
    events = []
    for index, progress in enumerate((333, 667)):
        events.append(
            {
                "failure_id": f"failure-{index}",
                "event_index": index,
                "type": "GPU_FAILURE",
                "bucket": "96k",
                "seed": 0,
                "focus_span_id": f"focus-{index}",
                "target_gpu_id": f"gpu-{index}",
                "target_gpu_id_semantics": (
                    "REFERENCE_ROUTE_PROVENANCE_NOT_RUNTIME_FAILURE_TARGET"
                ),
                "impact_contract": None,
                "profile_impact_contracts": None,
                "workload_position": {
                    "kind": "COMPLETED_WORKFLOW_FRACTION_NEAREST_COMMON_ROUTE_SPAN",
                    "target_progress_per_mille": progress,
                    "reference_completed_workflow_count": index + 1,
                    "reference_workflow_count": 160,
                },
                "trigger": {
                    "kind": "FOCUS_SPAN_COMPUTE_PROGRESS",
                    "progress_per_mille": 600,
                },
                "reference_at_ns": (index + 1) * 1_000_000_000,
                "reference_at_ns_semantics": ("recompute_only_oracle_provenance_not_cell_time"),
                "detection_delay_ns": 1_000_000,
                "selection_scope": (
                    "variant_local_focus_span_gpu_at_shared_workload_target_after_prior_failures"
                ),
                "repair_after_ns": 5_000_000_000,
                "parameter_source": "deterministic_focus_span_progress_global_des",
            }
        )
    return {
        "type": "GPU_FAILURE",
        "failure_count": 2,
        "selection_scope": "single_global_des_run_multiple_gpu_failure_events",
        "events": events,
    }


def test_detailed_rerun_reconstructs_exact_formal_schedule() -> None:
    rerunner = _load(RERUNNER, "_test_qwen8_mechanism_rerunner")
    document = _canonical_failure_schedule()

    schedule = rerunner._failure_schedule(document, sha256_json(document))

    assert schedule.to_dict() == document
    assert schedule.fingerprint == sha256_json(document)
    assert [event.focus_span_id for event in schedule.events] == [
        "focus-0",
        "focus-1",
    ]


def test_detailed_rerun_gate_requires_all_four_formal_hashes() -> None:
    rerunner = _load(RERUNNER, "_test_qwen8_mechanism_rerun_gate")
    schedule = _canonical_failure_schedule()
    payload = {
        "variant_fingerprint": "variant-fingerprint",
        "failure_schedule": schedule,
    }
    span_details = [{"span_id": "focus-0"}]
    representative = {"failure_events": []}
    detailed = {
        "variant_id": MOONCAKE,
        "variant_fingerprint": "variant-fingerprint",
        "failure_schedule": schedule,
        "failure_schedule_fingerprint": sha256_json(schedule),
        "payload": payload,
        "payload_sha256": sha256_json(payload),
        "journal_sha256": "a" * 64,
        "span_details": span_details,
        "span_details_sha256": sha256_json(span_details),
        "representative": representative,
        "representative_sha256": sha256_json(representative),
    }
    compact = {
        "variant_fingerprint": "variant-fingerprint",
        "failure_schedule": schedule,
        "failure_schedule_fingerprint": sha256_json(schedule),
        "run": {
            field: detailed[field]
            for field in (
                "payload_sha256",
                "journal_sha256",
                "span_details_sha256",
                "representative_sha256",
            )
        },
    }

    rerunner._validate_result(MOONCAKE, detailed, compact)
    compact["run"]["representative_sha256"] = "f" * 64
    with pytest.raises(rerunner.DetailedRerunError, match="representative_sha256"):
        rerunner._validate_result(MOONCAKE, detailed, compact)


def test_detailed_rerun_is_independent_of_v7_runner_module() -> None:
    source = RERUNNER.read_text(encoding="utf-8")

    assert "run_aegiskv_paper_sweeps" not in source
    assert "ProcessPoolExecutor" in source
    assert 'multiprocessing.get_context("fork")' in source
    assert "payload_sha256_exact_match" in source
    assert "representative_sha256_exact_match" in source
