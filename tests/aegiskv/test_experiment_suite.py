from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import moonkvsim.aegiskv.experiment_suite as suite
from moonkvsim.aegiskv.experiment import (
    CellSpec,
    FailureEventSchedule,
    FailureSchedule,
    ModelParameters,
    Scenario,
    StudyRunResult,
    core_variants,
    qwen3_8b_dp_deployment,
    qwen3_8b_dp_only_contract,
    transport_sensitivity_variants,
)
from moonkvsim.aegiskv.experiment_statistics import confidence_summary
from moonkvsim.aegiskv.experiment_suite import (
    EVIDENCE_BOUNDARY,
    NO_FAILURE_SCHEDULE_FINGERPRINT,
    ExperimentSuiteError,
    ImplementationBinding,
    WorkloadBinding,
    build_protocol,
    execute_fresh_pair,
    load_frozen_workload,
    run_e2_matrix,
    run_explicit_e2_matrix,
)

ROOT = Path(__file__).resolve().parents[2]
WORKLOAD = ROOT / "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-shapes.jsonl"
WORKLOAD_MANIFEST = (
    ROOT / "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-manifest.json"
)


def _implementation() -> ImplementationBinding:
    return ImplementationBinding(commit="a" * 40, tree="b" * 40, worktree_clean=True)


def _workload() -> WorkloadBinding:
    return WorkloadBinding(
        declared_path="benchmark/AegisKV/experiments/workloads/frozen.jsonl",
        sha256="c" * 64,
        record_count=1,
        semantic_fingerprint="d" * 64,
        manifest_sha256="e" * 64,
        manifest_schema="moonkvsim.aegiskv.experiment_workload_manifest.v1",
    )


def _payload(spec: CellSpec) -> dict[str, Any]:
    return {
        "schema": "moonkvsim.aegiskv.study_run_payload.v1",
        "status": "PASS",
        "evidence": {
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
        },
        "global_clock": {"kind": "single_global_virtual_clock"},
        "model_deployment": qwen3_8b_dp_deployment(spec.variant.parameters.dp_count),
        "variant_fingerprint": spec.variant.fingerprint,
        "context_bucket": spec.context_bucket,
        "scenario": spec.scenario.value,
        "failure_schedule": (
            None if spec.failure_schedule is None else spec.failure_schedule.to_dict()
        ),
        "metrics": {
            "virtual_end_ns": 123,
            "workflow_completion_time_ns": {"mean": 100, "p95": 110},
            "goodput_output_tokens_per_second_milli": 1_000,
            "recovery_latency_ns": {"mean": 20},
            "restored_tokens": {"total": 30},
            "recompute_tokens_after_failure": 40,
            "resource_cost": {
                "peer_hbm_peak_bytes": 50,
                "store_dram_peak_bytes": 60,
                "network_byte_ns": {"FAKE_TRANSFER": 70},
                "copy_engine_busy_ns": {"FAKE_TRANSFER": 80},
            },
        },
        "output_audit": {
            "duplicate_or_missing_tokens": 0,
            "stale_route_output_count": 0,
        },
        "forbidden_semantics": {
            "hbm_to_dram_writeback_count": 0,
            "ssd_nvme_event_count": 0,
        },
    }


def _fake_run(_records: object, spec: CellSpec) -> StudyRunResult:
    return StudyRunResult(
        payload=_payload(spec),
        journal_sha256=hashlib.sha256(spec.pair_id.encode()).hexdigest(),
        span_details=({"span_id": "span-0"},),
        representative={"events": []},
    )


def _fake_schedule(
    _records: object,
    *,
    bucket: str,
    seed: int,
    parameters: ModelParameters,
    failure_count: int = 2,
    workflow_concurrency: int | None = None,
    compared_profiles: object = None,
) -> FailureSchedule:
    del workflow_concurrency, compared_profiles
    return FailureSchedule(
        tuple(
            FailureEventSchedule(
                failure_id=f"gpu-failure:{bucket}:seed-{seed}:event-{event_index}",
                event_index=event_index,
                bucket=bucket,
                seed=seed,
                focus_span_id=f"span-{event_index}",
                target_gpu_id=f"gpu-{event_index}",
                reference_at_ns=100 + seed + event_index,
                target_workload_progress_per_mille=(
                    1_000 * (event_index + 1) + (failure_count + 1) // 2
                )
                // (failure_count + 1),
                reference_completed_workflow_count=event_index + 1,
                reference_workflow_count=failure_count + 1,
                detection_delay_ns=parameters.failure_detection_ns,
                trigger_progress_per_mille=parameters.failure_progress_per_mille,
                gpu_recovery_time_ns=parameters.gpu_recovery_time_ns,
            )
            for event_index in range(failure_count)
        )
    )


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_protocol_defines_exact_default_cross_products() -> None:
    core = build_protocol("core", (0, 1, 2))
    all_suites = build_protocol("all", (0, 1, 2))

    assert core["execution"]["expected_row_count"] == 420
    assert core["execution"]["expected_pair_count"] == 210
    assert all_suites["execution"]["expected_row_count"] == 2_400
    assert all_suites["execution"]["expected_pair_count"] == 1_200
    assert all_suites["suite_catalog"]["ablation"]["default_expected_row_count"] == 720
    assert all_suites["suite_catalog"]["sensitivity"]["default_expected_row_count"] == 1_260
    assert core["execution"]["failure_count_per_failure_cell"] == 2
    assert core["execution"]["silent_fallback_allowed"] is False
    assert core["evidence"] == EVIDENCE_BOUNDARY
    assert core["model_deployment_contract"] == qwen3_8b_dp_only_contract()


def test_student_t_summary_uses_seed_count_not_determinism_repetitions() -> None:
    summary = confidence_summary((1, 2, 3))

    assert summary["sample_count"] == 3
    assert summary["mean"] == {
        "numerator": 6,
        "denominator": 3,
        "rounded_half_even": 2,
    }
    assert summary["sample_stddev_rounded_half_even"] == 1
    assert summary["ci95"] == {
        "status": "ESTIMATED",
        "method": "two_sided_student_t_95_conservative_table",
        "degrees_of_freedom": 2,
        "critical_t_millionths": 4_302_653,
        "lower_floor": -1,
        "upper_ceiling": 5,
    }


def test_single_seed_summary_fails_closed_to_not_estimable_interval() -> None:
    summary = confidence_summary((7,))

    assert summary["mean"]["rounded_half_even"] == 7
    assert summary["ci95"]["status"] == "NOT_ESTIMABLE_SINGLE_SEED"
    assert summary["ci95"]["lower_floor"] is None


def test_one_frozen_workload_pair_is_fresh_and_byte_deterministic() -> None:
    if not WORKLOAD.is_file() or not WORKLOAD_MANIFEST.is_file():
        pytest.skip("frozen AegisKV workload is not present")
    records, workload, manifest = load_frozen_workload(WORKLOAD, WORKLOAD_MANIFEST)
    variant = core_variants()[0]
    protocol = build_protocol("core", (0,))

    execution = execute_fresh_pair(
        records,
        variant=variant,
        context_bucket="8k",
        scenario=Scenario.NO_FAILURE,
        seed=0,
        failure_schedule=None,
        failure_binding_fingerprint=NO_FAILURE_SCHEDULE_FINGERPRINT,
        implementation=_implementation(),
        workload=workload,
        protocol_fingerprint=protocol["fingerprint"],
    )

    row_a, row_b = execution.rows
    assert manifest["artifact"]["record_count"] == 117
    assert row_a["run_id"].endswith("repeat-A")
    assert row_b["run_id"].endswith("repeat-B")
    assert row_a["payload_sha256"] == row_b["payload_sha256"]
    assert row_a["journal_sha256"] == row_b["journal_sha256"]
    assert (
        row_a["bindings"]["matched_input_fingerprint"]
        == row_b["bindings"]["matched_input_fingerprint"]
    )
    assert execution.audit["fresh_global_des_instances"] == 2


def test_core_publication_has_one_two_event_failure_cell_and_rejects_existing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(suite, "derive_failure_schedule", _fake_schedule)
    monkeypatch.setattr(suite, "run_study_cell", _fake_run)
    output = tmp_path / "core-matrix"

    manifest = run_e2_matrix(
        ({"record": "fake"},),
        workload=_workload(),
        implementation=_implementation(),
        output_dir=output,
        selection="core",
        seeds=(0, 1, 2),
        jobs=1,
        config_snapshot_dir=ROOT / "benchmark/AegisKV/experiments/configs",
    )

    rows = _jsonl(output / "results.jsonl")
    pairs = _jsonl(output / "pair-audit.jsonl")
    schedules = _jsonl(output / "failure-schedules.jsonl")
    completeness = json.loads((output / "completeness.json").read_text(encoding="utf-8"))
    representative = json.loads((output / "representative-run.json").read_text(encoding="utf-8"))
    statistics = json.loads((output / "statistics.json").read_text(encoding="utf-8"))
    assert len(rows) == 420
    assert len(pairs) == 210
    assert len(schedules) == 105
    assert all(len(item["used_by_variants"]) == 1 for item in schedules)
    assert rows == sorted(rows, key=lambda row: row["run_id"])
    assert all(row["evidence"] == EVIDENCE_BOUNDARY for row in rows)
    assert all(row["variant_config"] for row in rows)
    assert all(
        row["model_deployment"]
        == qwen3_8b_dp_deployment(row["variant_config"]["parameters"]["dp_count"])
        for row in rows
    )
    assert all(pair["payload_sha256_exact_match"] for pair in pairs)
    assert all(pair["journal_sha256_exact_match"] for pair in pairs)
    assert completeness["status"] == "PASS"
    assert completeness["silent_fallback_count"] == 0
    assert manifest["result_count"] == 420
    assert len(manifest["result_bindings"]) == 420
    assert representative["run_id"].endswith("repeat-A")
    assert representative["payload_sha256"]
    assert statistics["status"] == "PASS"
    assert statistics["sampling_contract"]["included_repetition"] == "A"
    assert statistics["sampling_contract"]["excluded_repetition"] == "B"
    assert statistics["sampling_contract"]["seed_count"] == 3
    assert statistics["audit"]["included_repeat_a_row_count"] == 210
    assert statistics["audit"]["excluded_repeat_b_row_count"] == 210
    assert statistics["audit"]["descriptive_group_count"] == 700
    assert statistics["audit"]["paired_effect_group_count"] == 600
    network_group = next(
        group
        for group in statistics["descriptive"]
        if group["metric_id"] == "network_byte_ns"
    )
    assert [sample["value"] for sample in network_group["samples"]] == [70, 70, 70]
    assert manifest["statistics_fingerprint"] == statistics["fingerprint"]
    assert "statistics.json" in manifest["artifact_hashes"]
    assert manifest["config_snapshot"]["directory"] == "configs"
    assert set(manifest["config_snapshot"]["files"]) == {
        "requests.json",
        "failure.json",
        "engine.json",
    }
    for name, descriptor in manifest["config_snapshot"]["files"].items():
        snapshot = output / "configs" / name
        assert descriptor["size_bytes"] == snapshot.stat().st_size
        assert descriptor["sha256"] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert (output / "manifest.json").is_file()

    with pytest.raises(ExperimentSuiteError, match="existing output target"):
        run_e2_matrix(
            ({"record": "fake"},),
            workload=_workload(),
            implementation=_implementation(),
            output_dir=output,
            selection="core",
            seeds=(0, 1, 2),
            jobs=1,
        )


def test_focused_transport_publication_uses_variant_local_physical_schedules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(suite, "derive_failure_schedule", _fake_schedule)
    monkeypatch.setattr(suite, "run_study_cell", _fake_run)
    output = tmp_path / "transport-matrix"
    variants = transport_sensitivity_variants()

    manifest = run_explicit_e2_matrix(
        ({"record": "fake"},),
        variants=variants,
        workload=_workload(),
        implementation=_implementation(),
        output_dir=output,
        protocol_id="test-transport",
        representative_variant_id=variants[-1].variant_id,
        seeds=(0,),
        jobs=1,
    )

    rows = _jsonl(output / "results.jsonl")
    schedules = _jsonl(output / "failure-schedules.jsonl")
    assert manifest["result_count"] == 60
    assert manifest["pair_count"] == 30
    assert len(schedules) == 15
    assert all(not item["shared_across_variant_parameters"] for item in schedules)
    assert all(len(item["used_by_variants"]) == 1 for item in schedules)
    failure_bindings: dict[tuple[str, str, int, int], set[str]] = {}
    for row in rows:
        if row["scenario"] != "gpu_failure":
            continue
        key = (
            row["variant_id"],
            row["context_bucket"],
            row["seed"],
            row["failure_count"],
        )
        failure_bindings.setdefault(key, set()).add(
            row["bindings"]["failure_binding_fingerprint"]
        )
    assert all(len(values) == 1 for values in failure_bindings.values())
    representative = json.loads(
        (output / "representative-run.json").read_text(encoding="utf-8")
    )
    assert representative["variant_config"]["variant_id"] == variants[-1].variant_id


def test_pair_fails_closed_if_fresh_journals_differ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mismatched(_records: object, spec: CellSpec) -> StudyRunResult:
        return StudyRunResult(
            payload=_payload(spec),
            journal_sha256=hashlib.sha256(spec.repetition.encode()).hexdigest(),
            span_details=(),
            representative={},
        )

    monkeypatch.setattr(suite, "run_study_cell", mismatched)
    variant = core_variants()[0]
    with pytest.raises(ExperimentSuiteError, match="fresh-run A/B mismatch"):
        execute_fresh_pair(
            ({"record": "fake"},),
            variant=variant,
            context_bucket="8k",
            scenario=Scenario.NO_FAILURE,
            seed=0,
            failure_schedule=None,
            failure_binding_fingerprint=NO_FAILURE_SCHEDULE_FINGERPRINT,
            implementation=_implementation(),
            workload=_workload(),
            protocol_fingerprint=build_protocol("core", (0,))["fingerprint"],
        )


def test_result_rows_are_canonical_json_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(suite, "derive_failure_schedule", _fake_schedule)
    monkeypatch.setattr(suite, "run_study_cell", _fake_run)
    output = tmp_path / "canonical"
    run_e2_matrix(
        ({"record": "fake"},),
        workload=_workload(),
        implementation=_implementation(),
        output_dir=output,
        selection="core",
        seeds=(7,),
        jobs=1,
    )
    for line in (output / "results.jsonl").read_bytes().splitlines(keepends=True):
        value: Mapping[str, Any] = json.loads(line)
        expected = (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode()
        assert line == expected
