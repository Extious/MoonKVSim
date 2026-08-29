from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REDUCER_PATH = (
    PROJECT_ROOT / "scripts" / "physical" / "reduce_aiconfigurator_forward_calibration.py"
)
CONFIG_PATH = (
    PROJECT_ROOT
    / "configs"
    / "physical"
    / "aiconfigurator"
    / "qwen3-8b-l40s-native-40960"
    / "reducer-config.json"
)
PLAN_PATH = CONFIG_PATH.parent / "shape-plan.json"
THRESHOLD_PATH = CONFIG_PATH.parent / "residual-thresholds.json"

MODULE_SPEC = importlib.util.spec_from_file_location("aic_forward_reducer", REDUCER_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
RED = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = RED
MODULE_SPEC.loader.exec_module(RED)


def _source_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _write_source_json(path: Path, value: object) -> None:
    path.write_bytes(_source_bytes(value))


def _split_document(plan: dict[str, Any], shapes: tuple[Any, ...]) -> dict[str, object]:
    seed = int(plan["held_out_split_seed"])
    assignments = RED._expected_split(shapes, seed)
    records = []
    for shape in shapes:
        record = shape.to_vectors()
        record["split"] = assignments[shape.shape_id]
        records.append(record)
    return {
        "algorithm": "sha256-seeded-phase-stratified-first-held-out-v1",
        "assignments": records,
        "coverage": {
            "batch_sizes": sorted({shape.batch_size for shape in shapes}),
            "extend_lengths": sorted({value for shape in shapes for value in shape.extend_lengths}),
            "past_kv_lengths": sorted(
                {value for shape in shapes for value in shape.past_kv_lengths}
            ),
            "phases": sorted({shape.phase for shape in shapes}),
            "shape_axes": ["batch_size", "extend_length", "past_kv_length"],
        },
        "frozen_before_measurement": True,
        "seed": seed,
        "schema": RED.SOURCE_SPLIT_SCHEMA,
    }


def _duration_ns(shape: Any, repeat_index: int, warmup: bool) -> int:
    # Deliberately small deterministic fixture values.  They are not physical
    # observations and fixture mode prevents any formal/calibrated claim.
    base = (
        10_000
        + shape.batch_size * 1_000
        + max(shape.extend_lengths) * 20
        + max(shape.past_kv_lengths) * 5
    )
    return int(base + repeat_index + int(warmup))


def _streams(
    plan: dict[str, Any],
    shapes: tuple[Any, ...],
    campaign_fingerprint: str,
    hardware_fingerprint: str,
) -> tuple[bytes, bytes, int]:
    expected_steps = RED._expected_steps(
        shapes,
        int(plan["warmup_repeats"]),
        int(plan["measured_repeats"]),
    )
    metadata_lines: list[bytes] = []
    raw_lines: list[bytes] = []
    for index, expected in enumerate(expected_steps):
        shape = expected.shape
        request_hash = f"{index + 1:064x}"[-64:]
        input_hash = f"{index + 10_000:064x}"[-64:]
        prompts = [
            previous if previous > 0 else extension
            for extension, previous in zip(shape.extend_lengths, shape.past_kv_lengths, strict=True)
        ]
        metadata = {
            "batch_size": shape.batch_size,
            "cudagraph_mode": "NONE",
            "extend_lengths": list(shape.extend_lengths),
            "measurement_role": expected.role,
            "model_internal_collective": "none_tp1",
            "model_runner_input_fingerprint": input_hash,
            "past_kv_lengths": list(shape.past_kv_lengths),
            "phase": shape.phase,
            "pipeline_parallel_rank": 0,
            "prompt_lengths": prompts,
            "repeat_index": expected.repeat_index,
            "request_count": shape.batch_size,
            "request_ids_sha256": request_hash,
            "scheduled_token_budget": sum(shape.extend_lengths),
            "schema": RED.SOURCE_STEP_SCHEMA,
            "shape_id": shape.shape_id,
            "tensor_parallel_rank": 0,
            "warmup": expected.warmup,
        }
        metadata_lines.append(_source_bytes(metadata))
        if expected.has_raw_sample:
            raw = {
                "batch_size": shape.batch_size,
                "cudagraph_mode": "NONE",
                "duration_ns": _duration_ns(shape, expected.repeat_index, expected.warmup),
                "extend_lengths": list(shape.extend_lengths),
                "hardware_profile_fingerprint": hardware_fingerprint,
                "measurement_method": "cuda_events_gpu_model_runner_model_forward",
                "model_runner_source_sha256": "9" * 64,
                "past_kv_lengths": list(shape.past_kv_lengths),
                "phase": shape.phase,
                "pipeline_parallel_rank": 0,
                "profile_fingerprint": campaign_fingerprint,
                "repeat_index": expected.repeat_index,
                "request_ids_sha256": request_hash,
                "schema": RED.SOURCE_SAMPLE_SCHEMA,
                "shape_id": shape.shape_id,
                "tensor_parallel_rank": 0,
                "warmup": expected.warmup,
            }
            raw_lines.append(_source_bytes(raw))
    return b"".join(raw_lines), b"".join(metadata_lines), len(expected_steps)


def _reseal_bundle(root: Path, manifest: dict[str, Any]) -> None:
    artifact_names = sorted(
        path.name
        for path in root.iterdir()
        if path.is_file()
        and path.name not in {"manifest.json", "SHA256SUMS", "PUBLICATION_COMPLETE.json"}
    )
    manifest["artifacts"] = {
        name: {
            "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(),
            "size_bytes": (root / name).stat().st_size,
        }
        for name in artifact_names
    }
    _write_source_json(root / "manifest.json", manifest)
    checksum_names = sorted([*artifact_names, "manifest.json"])
    checksum = "".join(
        f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}\n"
        for name in checksum_names
    ).encode()
    (root / "SHA256SUMS").write_bytes(checksum)
    publication = {
        "formal_use_allowed": False,
        "no_clobber": True,
        "schema": RED.SOURCE_PUBLICATION_SCHEMA,
        "sha256sums_sha256": hashlib.sha256(checksum).hexdigest(),
        "status": "COMPLETE",
    }
    _write_source_json(root / "PUBLICATION_COMPLETE.json", publication)


def _physical_fixture(
    root: Path,
    *,
    mutate_plan: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    root.mkdir()
    (root / "residual-thresholds.json").write_bytes(THRESHOLD_PATH.read_bytes())
    plan = json.loads(PLAN_PATH.read_bytes())
    if mutate_plan is not None:
        mutate_plan(plan)
    _write_source_json(root / "shape-plan.json", plan)
    _, shapes = RED._load_and_validate_plan(root)
    campaign_fingerprint = RED._planned_profile_fingerprint(plan)
    split = _split_document(plan, shapes)
    _write_source_json(root / "held-out-split.json", split)

    hardware_profile = {
        "compute_capability": [8, 9],
        "driver_version": "fixture-only",
        "name": "NVIDIA L40S",
        "total_memory_bytes": 48_000_000_000,
        "uuid": "GPU-00000000-0000-0000-0000-000000000001",
    }
    hardware_fingerprint = _sha256(_source_bytes(hardware_profile))
    raw, metadata, scheduler_steps = _streams(
        plan, shapes, campaign_fingerprint, hardware_fingerprint
    )
    (root / "raw-forward.jsonl").write_bytes(raw)
    (root / "step-metadata.jsonl").write_bytes(metadata)
    gpu_snapshot = {
        "foreign_processes": [],
        "hardware_profile": hardware_profile,
        "hardware_profile_fingerprint": hardware_fingerprint,
        "status": "PASS",
    }
    manifest_instrumentation = {
        "measurement_method": "cuda_events_gpu_model_runner_model_forward",
        "model_runner_git_blob": "fixture-model-runner-blob",
        "model_runner_source_sha256": "9" * 64,
        "outer_execute_model_role": "scheduler_metadata_handoff_only",
        "source_tree_modified": False,
        "symbol": "GPUModelRunner._model_forward",
    }
    environment_instrumentation = {
        **manifest_instrumentation,
        "installation": "in_memory_monkeypatch_only",
        "timing_boundary": "cuda_events_immediately_inside_model_forward_wrapper",
    }
    environment = {
        "environment_variables": {},
        "finished_utc": "2000-01-01T00:01:00Z",
        "gpu": {"post": gpu_snapshot, "pre": gpu_snapshot},
        "instrumentation": environment_instrumentation,
        "isolation_boundary": {
            "assigned_gpu_gres_verified": True,
            "foreign_gpu_processes_post": [],
            "foreign_gpu_processes_pre": [],
            "scope": "assigned_slurm_visible_gpu_only",
        },
        "launch_provenance": {},
        "nvidia_smi_q": {},
        "schema": RED.SOURCE_ENVIRONMENT_SCHEMA,
        "slurm": {
            "assigned_gpu_allocation": "PASS",
            "job_id": "999999",
            "partition": "short",
        },
        "source_verification": {
            "aiconfigurator": {
                "commit": RED.AICONFIGURATOR_PINNED_COMMIT,
                "version": RED.AICONFIGURATOR_PINNED_VERSION,
            },
            "model": plan["model"],
            "runtime": {"vllm_version": plan["engine"]["installed_version"]},
            "status": "PASS",
            "vllm": {"commit": plan["engine"]["source_commit"]},
        },
        "started_utc": "2000-01-01T00:00:00Z",
    }
    _write_source_json(root / "environment.json", environment)
    manifest = {
        "artifacts": {},
        "evidence_label": {
            "calibrated_profile": False,
            "class": "physical_forward_raw_calibration_input",
            "formal_use_allowed": False,
            "paper_result_allowed": False,
            "reducer_required": True,
        },
        "formal_use_allowed": False,
        "hardware_profile_fingerprint": hardware_fingerprint,
        "instrumentation": manifest_instrumentation,
        "isolation_boundary": {
            "assigned_gpu_gres_verified": True,
            "cuda_visible_device_count": 1,
            "foreign_gpu_processes_rejected_pre_and_post": True,
            "scope": "assigned_slurm_visible_gpu_only",
            "whole_node_exclusive_verified": False,
        },
        "model": plan["model"],
        "profile_fingerprint": campaign_fingerprint,
        "raw_counts": {
            "measured_samples": len(shapes) * int(plan["measured_repeats"]),
            "scheduler_steps": scheduler_steps,
            "warmup_samples": len(shapes) * int(plan["warmup_repeats"]),
        },
        "schema": RED.SOURCE_MANIFEST_SCHEMA,
        "status": "RAW_FORWARD_COMPLETE",
    }
    _reseal_bundle(root, manifest)
    return manifest


def test_fixture_reduction_is_preliminary_disjoint_and_mixed_isolated(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _physical_fixture(source)
    output = tmp_path / "reduced"

    formal = RED.reduce_bundle(
        input_bundle=source,
        output_root=output,
        reducer_config=CONFIG_PATH,
        fixture_mode=True,
    )

    assert formal is False
    assert (output / "PUBLICATION_COMPLETE.json").is_file()
    assert not (output / "PUBLICATION_INCOMPLETE").exists()
    assert not (output / "profile-selection.json").exists()
    report = json.loads((output / "reduction-report.json").read_bytes())
    assert report["status"] == "PRELIMINARY_ONLY"
    assert report["evidence_class"] == "E1_E2_reducer_fixture_only"
    assert report["formal_use_allowed"] is False
    assert report["split_audit"]["disjoint"] is True
    assert set(report["split_audit"]["train_shape_ids"]).isdisjoint(
        report["split_audit"]["held_out_shape_ids"]
    )
    database = json.loads((output / "database/phase-shape-forward-database.json").read_bytes())
    assert {entry["split"] for entry in database["entries"]} == {"train"}
    assert {entry["phase"] for entry in database["entries"]} == {"prefill", "decode"}
    assert set(report["split_audit"]["mixed_shape_ids"]).isdisjoint(
        {entry["shape_id"] for entry in database["entries"]}
    )
    mixed = json.loads((output / "calibration/mixed-observations.json").read_bytes())
    assert mixed["used_for_phase_database_fit"] is False
    assert mixed["used_for_phase_residuals"] is False
    assert mixed["decomposed_into_prefill_decode"] is False
    candidate = json.loads((output / "profile-candidate.json").read_bytes())
    assert candidate["formal_use_allowed"] is False
    detail = json.loads((output / "calibration/shape-residual-detail.json").read_bytes())
    assert detail["evidence_label"] == "preliminary"
    assert detail["formal_use_allowed"] is False
    assert detail["residual_convention"] == "predicted_minus_observed_ns"
    assert detail["absolute_error_percentile_method"] == "nearest_rank"
    for observation in detail["observations"]:
        assert observation["raw_residual_ns"] == (
            observation["raw_prediction_ns"] - observation["observed_forward_duration_ns"]
        )
        assert observation["calibrated_residual_ns"] == (
            observation["calibrated_prediction_ns"] - observation["observed_forward_duration_ns"]
        )
    detail_fingerprint = detail.pop("fingerprint")
    assert RED.sha256_json(detail) == detail_fingerprint
    prediction_audit = json.loads(
        (output / "calibration/held-out-prediction-audit.json").read_bytes()
    )
    assert prediction_audit["mixed_used"] is False
    assert prediction_audit["train_and_held_out_duration_leakage"] is False
    original_thresholds = json.loads((output / RED.ORIGINAL_THRESHOLDS_COPY_PATH).read_bytes())
    rebound_thresholds = json.loads((output / RED.BOUND_THRESHOLDS_PATH).read_bytes())
    assert rebound_thresholds["phase_thresholds"] == original_thresholds["phase_thresholds"]
    assert rebound_thresholds["profile_fingerprint"] == report["profile_fingerprint"]
    assert (
        original_thresholds["profile_fingerprint"] == report["source_campaign_profile_fingerprint"]
    )
    assert report["threshold_rebinding"]["numeric_values_unchanged"] is True


def test_reducer_rejects_hash_tamper_without_creating_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _physical_fixture(source)
    with (source / "raw-forward.jsonl").open("ab") as stream:
        stream.write(b"{}\n")
    output = tmp_path / "reduced"

    with pytest.raises(RED.ReductionError, match="SHA-256 mismatch"):
        RED.reduce_bundle(
            input_bundle=source,
            output_root=output,
            reducer_config=CONFIG_PATH,
            fixture_mode=True,
        )

    assert not output.exists()


def test_reducer_rejects_semantic_step_reordering_even_when_hashes_are_resealed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    manifest = _physical_fixture(source)
    lines = (source / "step-metadata.jsonl").read_bytes().splitlines(keepends=True)
    lines[0], lines[1] = lines[1], lines[0]
    (source / "step-metadata.jsonl").write_bytes(b"".join(lines))
    _reseal_bundle(source, manifest)
    output = tmp_path / "reduced"

    with pytest.raises(RED.ReductionError, match="exact expected execution order"):
        RED.reduce_bundle(
            input_bundle=source,
            output_root=output,
            reducer_config=CONFIG_PATH,
            fixture_mode=True,
        )

    assert not output.exists()


def test_reducer_rejects_split_reassignment_even_when_hashes_are_resealed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    manifest = _physical_fixture(source)
    split = json.loads((source / "held-out-split.json").read_bytes())
    phase_records = [record for record in split["assignments"] if record["phase"] == "prefill"]
    held = next(record for record in phase_records if record["split"] == "held_out")
    train = next(record for record in phase_records if record["split"] == "train")
    held["split"], train["split"] = train["split"], held["split"]
    _write_source_json(source / "held-out-split.json", split)
    _reseal_bundle(source, manifest)
    output = tmp_path / "reduced"

    with pytest.raises(RED.ReductionError, match="differs from plan/order/algorithm"):
        RED.reduce_bundle(
            input_bundle=source,
            output_root=output,
            reducer_config=CONFIG_PATH,
            fixture_mode=True,
        )

    assert not output.exists()


def test_reducer_no_clobber_refuses_existing_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _physical_fixture(source)
    output = tmp_path / "reduced"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")

    with pytest.raises(RED.ReductionError, match="refusing existing"):
        RED.reduce_bundle(
            input_bundle=source,
            output_root=output,
            reducer_config=CONFIG_PATH,
            fixture_mode=True,
        )

    assert sentinel.read_text(encoding="utf-8") == "preserve\n"


def test_integer_median_half_up_and_native_context_limit_are_exact() -> None:
    assert RED._integer_median_half_up((10, 11)) == 11
    assert RED._integer_median_half_up((10, 12)) == 11
    assert RED._integer_median_half_up((9, 1, 5)) == 5
    with pytest.raises(RED.ReductionError, match="at least one"):
        RED._integer_median_half_up(())
    with pytest.raises(RED.ReductionError, match="max_model_len"):
        RED._parse_shape(
            "decode",
            {"extend_lengths": [1], "past_kv_lengths": [40960]},
            "overflow shape",
        )


def test_reducer_rejects_json_boolean_substituted_for_raw_integer(tmp_path: Path) -> None:
    source = tmp_path / "source"
    manifest = _physical_fixture(source)
    lines = (source / "raw-forward.jsonl").read_bytes().splitlines(keepends=True)
    record = json.loads(lines[0])
    assert record["batch_size"] == 1
    record["batch_size"] = True
    lines[0] = _source_bytes(record)
    (source / "raw-forward.jsonl").write_bytes(b"".join(lines))
    _reseal_bundle(source, manifest)
    output = tmp_path / "reduced"

    with pytest.raises(RED.ReductionError, match="does not join"):
        RED.reduce_bundle(
            input_bundle=source,
            output_root=output,
            reducer_config=CONFIG_PATH,
            fixture_mode=True,
        )

    assert not output.exists()


def test_mixed_only_coordinates_do_not_define_phase_residual_buckets(tmp_path: Path) -> None:
    source = tmp_path / "source"

    def mutate_plan(plan: dict[str, Any]) -> None:
        plan["phases"]["mixed"] = [{"extend_lengths": [1, 300], "past_kv_lengths": [300, 0]}]

    _physical_fixture(source, mutate_plan=mutate_plan)
    output = tmp_path / "reduced"
    RED.reduce_bundle(
        input_bundle=source,
        output_root=output,
        reducer_config=CONFIG_PATH,
        fixture_mode=True,
    )

    detail = json.loads((output / RED.DETAIL_REPORT_PATH).read_bytes())
    assert 300 not in detail["bucket_spec"]["extend_length_upper_bounds"]
    assert 300 not in detail["bucket_spec"]["past_kv_length_upper_bounds"]
    mixed = json.loads((output / RED.MIXED_PATH).read_bytes())
    assert mixed["observations"][0]["extend_lengths"] == [1, 300]
    assert mixed["observations"][0]["past_kv_lengths"] == [300, 0]


def test_verified_source_keeps_hash_bound_bytes_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _physical_fixture(source)
    expected_raw = (source / "raw-forward.jsonl").read_bytes()

    verified = RED.verify_source_bundle(source)
    (source / "raw-forward.jsonl").write_bytes(expected_raw + b"{}\n")

    assert verified.source_artifact_bytes["raw-forward.jsonl"] == expected_raw
    assert (
        RED._sha256_bytes(verified.source_artifact_bytes["raw-forward.jsonl"])
        == (verified.source_artifacts["raw-forward.jsonl"]["sha256"])
    )


def test_reducer_refuses_output_leaf_symlink_created_after_initial_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    _physical_fixture(source)
    output = tmp_path / "reduced"
    redirect = tmp_path / "redirect"
    original_verify = RED.verify_source_bundle

    def verify_then_race(path: Path) -> Any:
        verified = original_verify(path)
        output.symlink_to(redirect, target_is_directory=True)
        return verified

    monkeypatch.setattr(RED, "verify_source_bundle", verify_then_race)
    with pytest.raises(RED.ReductionError, match="refusing existing"):
        RED.reduce_bundle(
            input_bundle=source,
            output_root=output,
            reducer_config=CONFIG_PATH,
            fixture_mode=True,
        )

    assert output.is_symlink()
    assert not redirect.exists()


def test_reducer_output_schemas_reject_semantically_inconsistent_documents(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _physical_fixture(source)
    output = tmp_path / "reduced"
    RED.reduce_bundle(
        input_bundle=source,
        output_root=output,
        reducer_config=CONFIG_PATH,
        fixture_mode=True,
    )

    report = json.loads((output / "reduction-report.json").read_bytes())
    report_schema = json.loads(
        (PROJECT_ROOT / "schemas/aiconfigurator-forward-reduction-report.schema.json").read_bytes()
    )
    report_validator = Draft202012Validator(report_schema)
    report_validator.validate(report)
    inconsistent_report = json.loads(json.dumps(report))
    inconsistent_report["formal_use_allowed"] = True
    assert list(report_validator.iter_errors(inconsistent_report))

    database = json.loads((output / RED.DATABASE_RELATIVE_PATH).read_bytes())
    database_schema = json.loads(
        (PROJECT_ROOT / "schemas/aiconfigurator-phase-shape-database.schema.json").read_bytes()
    )
    database_validator = Draft202012Validator(database_schema)
    database_validator.validate(database)
    self_authorizing_database = json.loads(json.dumps(database))
    self_authorizing_database["formal_use_allowed"] = True
    assert list(database_validator.iter_errors(self_authorizing_database))
    invalid_decode_database = json.loads(json.dumps(database))
    decode_entry = next(
        entry for entry in invalid_decode_database["entries"] if entry["phase"] == "decode"
    )
    decode_entry["past_kv_lengths"] = [0] * len(decode_entry["past_kv_lengths"])
    assert list(database_validator.iter_errors(invalid_decode_database))
