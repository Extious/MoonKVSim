from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import types
from copy import deepcopy
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HARNESS_PATH = PROJECT_ROOT / "scripts" / "physical" / "qwen3_8b_vllm_forward_calibration.py"
SBATCH_PATH = (
    PROJECT_ROOT / "scripts" / "physical" / "run_aiconfigurator_vllm_forward_calibration.sbatch"
)
PLAN_DIR = PROJECT_ROOT / "configs" / "physical" / "aiconfigurator" / "qwen3-8b-l40s-native-40960"
PLAN_PATH = PLAN_DIR / "shape-plan.json"
THRESHOLD_PATH = PLAN_DIR / "residual-thresholds.json"
README_PATH = PROJECT_ROOT / "benchmark" / "physical" / "aiconfigurator-vllm-forward" / "README.md"

MODULE_SPEC = importlib.util.spec_from_file_location("qwen_forward_calibration", HARNESS_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
CAL = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = CAL
MODULE_SPEC.loader.exec_module(CAL)


def _load_plan() -> dict[str, object]:
    return json.loads(PLAN_PATH.read_text(encoding="utf-8"))


def _materialize_plan(tmp_path: Path, plan: dict[str, object]) -> Path:
    thresholds = json.loads(THRESHOLD_PATH.read_text(encoding="utf-8"))
    thresholds["profile_fingerprint"] = CAL.planned_profile_fingerprint(plan)
    threshold_bytes = CAL.canonical_json_bytes(thresholds)
    threshold_path = tmp_path / "residual-thresholds.json"
    threshold_path.write_bytes(threshold_bytes)
    declaration = plan["threshold_declaration"]
    assert isinstance(declaration, dict)
    declaration["sha256"] = hashlib.sha256(threshold_bytes).hexdigest()
    declaration["size_bytes"] = len(threshold_bytes)
    plan_path = tmp_path / "shape-plan.json"
    plan_path.write_bytes(CAL.canonical_json_bytes(plan))
    return plan_path


def test_checked_in_native_plan_and_thresholds_are_canonical_and_exact() -> None:
    plan, shapes, thresholds = CAL.load_and_validate_shape_plan(PLAN_PATH)

    assert len(shapes) == 7
    assert [shape.phase for shape in shapes].count("prefill") == 3
    assert [shape.phase for shape in shapes].count("decode") == 3
    assert [shape.phase for shape in shapes].count("mixed") == 1
    assert CAL.maximum_scheduler_token_budget(shapes) == 512
    assert plan["context_mode"] == {"max_model_len": 40960, "rope_scaling": None}
    assert plan["warmup_repeats"] == 5
    assert plan["measured_repeats"] == 20
    assert plan["tensor_parallel_size"] == plan["pipeline_parallel_size"] == 1
    assert thresholds["profile_fingerprint"] == CAL.planned_profile_fingerprint(plan)
    assert PLAN_PATH.read_bytes() == CAL.canonical_json_bytes(plan)
    assert THRESHOLD_PATH.read_bytes() == CAL.canonical_json_bytes(thresholds)


def test_plan_rejects_unknown_fields_pin_drift_and_noncanonical_bytes(tmp_path: Path) -> None:
    changed = deepcopy(_load_plan())
    changed["unknown"] = True
    changed_path = _materialize_plan(tmp_path, changed)
    with pytest.raises(CAL.InvalidInputError, match="fields differ"):
        CAL.load_and_validate_shape_plan(changed_path)

    pin_dir = tmp_path / "pin"
    pin_dir.mkdir()
    changed = deepcopy(_load_plan())
    changed["context_mode"] = {"max_model_len": 131072, "rope_scaling": None}
    changed_path = _materialize_plan(pin_dir, changed)
    with pytest.raises(CAL.InvalidInputError, match="native max_model_len"):
        CAL.load_and_validate_shape_plan(changed_path)

    noncanonical_dir = tmp_path / "noncanonical"
    noncanonical_dir.mkdir()
    plan = _load_plan()
    canonical_path = _materialize_plan(noncanonical_dir, plan)
    canonical_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    with pytest.raises(CAL.InvalidInputError, match="canonical JSON"):
        CAL.load_and_validate_shape_plan(canonical_path)


@pytest.mark.parametrize(
    ("phase", "shape", "message"),
    [
        ("decode", {"extend_lengths": [2], "past_kv_lengths": [127]}, "decode"),
        ("decode", {"extend_lengths": [1], "past_kv_lengths": [0]}, "positive past"),
        ("mixed", {"extend_lengths": [1, 1], "past_kv_lengths": [127, 511]}, "prefill"),
        ("mixed", {"extend_lengths": [128, 512], "past_kv_lengths": [0, 0]}, "decode"),
        ("prefill", {"extend_lengths": [0], "past_kv_lengths": [0]}, "positive"),
        ("prefill", {"extend_lengths": [128, 1], "past_kv_lengths": [0]}, "equally"),
    ],
)
def test_shape_parser_rejects_nonexact_phase_vectors(
    phase: str, shape: dict[str, list[int]], message: str
) -> None:
    with pytest.raises(CAL.InvalidInputError, match=message):
        CAL._parse_shape(phase, shape, 0)


def test_threshold_hash_size_and_profile_are_bound_by_plan(tmp_path: Path) -> None:
    plan_path = _materialize_plan(tmp_path, deepcopy(_load_plan()))
    threshold_path = tmp_path / "residual-thresholds.json"
    threshold_path.write_bytes(threshold_path.read_bytes() + b" ")
    with pytest.raises(CAL.InvalidInputError, match="canonical JSON"):
        CAL.load_and_validate_shape_plan(plan_path)

    second = tmp_path / "second"
    second.mkdir()
    plan = deepcopy(_load_plan())
    plan_path = _materialize_plan(second, plan)
    thresholds = json.loads((second / "residual-thresholds.json").read_text())
    thresholds["profile_fingerprint"] = "0" * 64
    threshold_bytes = CAL.canonical_json_bytes(thresholds)
    (second / "residual-thresholds.json").write_bytes(threshold_bytes)
    declaration = plan["threshold_declaration"]
    assert isinstance(declaration, dict)
    declaration["sha256"] = hashlib.sha256(threshold_bytes).hexdigest()
    declaration["size_bytes"] = len(threshold_bytes)
    plan_path.write_bytes(CAL.canonical_json_bytes(plan))
    with pytest.raises(CAL.InvalidInputError, match="profile_fingerprint mismatch"):
        CAL.load_and_validate_shape_plan(plan_path)


def test_held_out_split_is_frozen_deterministic_and_covers_all_axes() -> None:
    plan, shapes, _ = CAL.load_and_validate_shape_plan(PLAN_PATH)
    first = CAL.build_held_out_split(shapes, plan["held_out_split_seed"])
    second = CAL.build_held_out_split(shapes, plan["held_out_split_seed"])

    assert first == second
    assert first["frozen_before_measurement"] is True
    assignments = first["assignments"]
    assert isinstance(assignments, list)
    held_out_phases = {record["phase"] for record in assignments if record["split"] == "held_out"}
    assert held_out_phases == {"prefill", "decode"}
    assert first["coverage"] == {
        "batch_sizes": [1, 2],
        "extend_lengths": [1, 128, 512],
        "past_kv_lengths": [0, 127, 511],
        "phases": ["decode", "mixed", "prefill"],
        "shape_axes": ["batch_size", "extend_length", "past_kv_length"],
    }


class _InputBatch:
    def __init__(
        self,
        request_ids: list[str],
        computed: list[int],
        prompts: list[int],
    ) -> None:
        self.req_ids = request_ids
        self.num_computed_tokens_cpu = computed
        self.num_prompt_tokens = prompts


class _Runner:
    def __init__(self, input_batch: _InputBatch) -> None:
        self.input_batch = input_batch


def test_observed_shape_joins_scheduler_and_runner_in_runner_order() -> None:
    runner = _Runner(_InputBatch(["decode", "prefill"], [127, 0], [127, 128]))
    metadata = CAL.SchedulerMetadata(
        num_scheduled_tokens={"prefill": 128, "decode": 1},
        total_num_scheduled_tokens=129,
    )

    observed = CAL.derive_observed_scheduler_shape(runner, metadata)

    assert observed.phase == "mixed"
    assert observed.extend_lengths == (1, 128)
    assert observed.past_kv_lengths == (127, 0)
    assert observed.prompt_lengths == (127, 128)
    assert observed.request_ids == ("decode", "prefill")
    assert len(observed.model_runner_input_fingerprint) == 64


def test_observed_shape_rejects_non_bijective_join_and_post_prompt_multitoken() -> None:
    runner = _Runner(_InputBatch(["a", "b"], [0, 0], [128, 128]))
    with pytest.raises(CAL.ShapeConstructionError, match="one-to-one"):
        CAL.derive_observed_scheduler_shape(
            runner,
            CAL.SchedulerMetadata({"a": 128, "c": 128}, 256),
        )

    invalid = _Runner(_InputBatch(["a"], [128], [128]))
    with pytest.raises(CAL.ShapeConstructionError, match="extension other than one"):
        CAL.derive_observed_scheduler_shape(
            invalid,
            CAL.SchedulerMetadata({"a": 2}, 2),
        )


def test_scheduler_metadata_validates_positive_counts_and_total() -> None:
    output = types.SimpleNamespace(num_scheduled_tokens={"r": 1}, total_num_scheduled_tokens=1)
    assert CAL.scheduler_metadata_from_output(output) == CAL.SchedulerMetadata({"r": 1}, 1)

    output.total_num_scheduled_tokens = 2
    with pytest.raises(CAL.ShapeConstructionError, match="inconsistent"):
        CAL.scheduler_metadata_from_output(output)
    output.num_scheduled_tokens = {"r": 0}
    output.total_num_scheduled_tokens = 0
    with pytest.raises(CAL.ShapeConstructionError, match="count is invalid"):
        CAL.scheduler_metadata_from_output(output)


class _FakeShapeEngine:
    def __init__(self, expected_steps: int, events: list[tuple[object, ...]]) -> None:
        self.expected_steps = expected_steps
        self.events = events
        self.steps = 0
        self.request_count = 0

    def add_request(self, request_id: str, prompt: object, params: object) -> None:
        self.events.append(("add", request_id, prompt, params))
        self.request_count += 1

    def step(self) -> None:
        self.events.append(("engine_step", self.steps))
        self.steps += 1

    def has_unfinished_requests(self) -> bool:
        return self.request_count > 0 and self.steps < self.expected_steps


class _FakeShapeController:
    def __init__(self, events: list[tuple[object, ...]]) -> None:
        self.events = events

    def begin_step(self, expectation: object) -> None:
        assert isinstance(expectation, CAL.StepExpectation)
        self.events.append(
            (
                "begin",
                expectation.role,
                expectation.shape.phase,
                expectation.shape.extend_lengths,
                expectation.shape.past_kv_lengths,
                expectation.record_sample,
                expectation.warmup,
                expectation.repeat_index,
            )
        )

    def finish_step(self) -> None:
        self.events.append(("finish",))


def test_shape_driver_decode_adds_setup_then_exact_ordered_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []
    monkeypatch.setattr(CAL, "_tokens_prompt", lambda length: ("prompt", length))
    monkeypatch.setattr(CAL, "_sampling_params", lambda max_tokens: ("params", max_tokens))
    engine = _FakeShapeEngine(expected_steps=2, events=events)
    driver = CAL.ShapeDriver(engine, _FakeShapeController(events))

    driver.run_shape(
        CAL.CalibrationShape("decode", (1, 1), (127, 511)),
        record_sample=True,
        warmup=True,
        repeat_index=4,
    )

    assert events == [
        ("add", "moonkv-00000000-decode", ("prompt", 127), ("params", 2)),
        ("add", "moonkv-00000001-decode", ("prompt", 511), ("params", 2)),
        ("begin", "measurement_setup", "prefill", (127, 511), (0, 0), False, True, 4),
        ("engine_step", 0),
        ("finish",),
        ("begin", "target", "decode", (1, 1), (127, 511), True, True, 4),
        ("engine_step", 1),
        ("finish",),
    ]


def test_shape_driver_mixed_preserves_decode_then_prefill_target_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []
    monkeypatch.setattr(CAL, "_tokens_prompt", lambda length: ("prompt", length))
    monkeypatch.setattr(CAL, "_sampling_params", lambda max_tokens: ("params", max_tokens))
    engine = _FakeShapeEngine(expected_steps=2, events=events)
    driver = CAL.ShapeDriver(engine, _FakeShapeController(events))

    driver.run_shape(
        CAL.CalibrationShape("mixed", (1, 128), (127, 0)),
        record_sample=True,
        repeat_index=6,
    )

    assert events == [
        ("add", "moonkv-00000000-mixed-decode", ("prompt", 127), ("params", 2)),
        ("begin", "measurement_setup", "prefill", (127,), (0,), False, False, 6),
        ("engine_step", 0),
        ("finish",),
        ("add", "moonkv-00000001-mixed-prefill", ("prompt", 128), ("params", 1)),
        ("begin", "target", "mixed", (1, 128), (127, 0), True, False, 6),
        ("engine_step", 1),
        ("finish",),
    ]


def test_slurm_gate_requires_bound_l40s_short_policy_and_one_visible_gpu() -> None:
    environment = {
        "SLURM_JOB_ID": "12345",
        "SLURM_JOB_PARTITION": "short",
        "SLURM_JOB_GPUS": "3",
        "CUDA_VISIBLE_DEVICES": "3",
        "MOONKVSIM_ASSIGNED_GPU_ALLOCATION": "PASS",
        "MOONKVSIM_BATCH_SCRIPT_CAPTURE_STATUS": "PASS",
        "MOONKVSIM_SLURM_JOB_OVERSUBSCRIBE": "YES",
        "MOONKVSIM_SLURM_PARTITION_OVERSUBSCRIBE": "FORCE:4",
    }
    record = CAL.validate_slurm_environment(environment)
    assert record["job_id"] == "12345"
    assert record["cuda_visible_devices"] == "3"

    unbound = dict(environment, MOONKVSIM_ASSIGNED_GPU_ALLOCATION="FAIL")
    with pytest.raises(CAL.GPUMismatchError, match="GRES binding"):
        CAL.validate_slurm_environment(unbound)
    changed_policy = dict(environment, MOONKVSIM_SLURM_PARTITION_OVERSUBSCRIBE="NO")
    with pytest.raises(CAL.GPUMismatchError, match="sharing policy drifted"):
        CAL.validate_slurm_environment(changed_policy)
    missing_runtime_field = dict(environment, MOONKVSIM_SLURM_JOB_OVERSUBSCRIBE="")
    with pytest.raises(CAL.GPUMismatchError, match="was not captured"):
        CAL.validate_slurm_environment(missing_runtime_field)
    missing_capture = dict(environment, MOONKVSIM_BATCH_SCRIPT_CAPTURE_STATUS="FAIL")
    with pytest.raises(CAL.SourceDriftError, match="spooled wrapper"):
        CAL.validate_slurm_environment(missing_capture)
    two_gpus = dict(environment, CUDA_VISIBLE_DEVICES="2,3")
    with pytest.raises(CAL.GPUMismatchError, match="exactly one"):
        CAL.validate_slurm_environment(two_gpus)
    wrong_partition = dict(environment, SLURM_JOB_PARTITION="long")
    with pytest.raises(CAL.GPUMismatchError, match="requires short"):
        CAL.validate_slurm_environment(wrong_partition)


def test_launch_provenance_accepts_only_executed_staging_and_spooled_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory(prefix="moonkv-aic-test-", dir="/tmp") as directory:
        staging = Path(directory)
        staged_harness = staging / HARNESS_PATH.name
        staged_harness.write_bytes(HARNESS_PATH.read_bytes())
        wrapper = staging / "submitted-batch-script.sh"
        wrapper.write_bytes(SBATCH_PATH.read_bytes())
        monkeypatch.setattr(CAL, "__file__", str(staged_harness))
        environment = {
            "MOONKVSIM_CALIBRATION_SCRIPT_SHA256": hashlib.sha256(
                staged_harness.read_bytes()
            ).hexdigest(),
            "MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256": hashlib.sha256(
                wrapper.read_bytes()
            ).hexdigest(),
        }

        record = CAL.validate_launch_provenance(staging, environment)

        assert record["status"] == "PASS"
        assert record["repository_wrapper_used_as_substitute"] is False
        wrapper.write_text("tampered\n")
        with pytest.raises(CAL.SourceDriftError, match="SHA-256 drift"):
            CAL.validate_launch_provenance(staging, environment)


def test_controller_times_only_exact_target_with_cuda_event_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations: list[str] = []
    event_counter = 0

    class FakeEvent:
        def __init__(self, index: int) -> None:
            self.index = index

        def record(self) -> None:
            operations.append(f"record-{self.index}")

        def synchronize(self) -> None:
            operations.append(f"sync-{self.index}")

        def elapsed_time(self, other: object) -> float:
            assert isinstance(other, FakeEvent)
            operations.append(f"elapsed-{self.index}-{other.index}")
            return 0.125

    def event_factory(*, enable_timing: bool) -> FakeEvent:
        nonlocal event_counter
        assert enable_timing is True
        event_counter += 1
        return FakeEvent(event_counter)

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: True, Event=event_factory)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    runner = _Runner(_InputBatch(["r"], [0], [128]))
    metadata = CAL.SchedulerMetadata({"r": 128}, 128)
    shape = CAL.CalibrationShape("prefill", (128,), (0,))
    controller = CAL.ForwardCalibrationController(
        hardware_profile_fingerprint="1" * 64,
        profile_fingerprint="2" * 64,
    )
    with (
        CAL.AppendOnlyJSONL(tmp_path / "raw.jsonl") as raw,
        CAL.AppendOnlyJSONL(tmp_path / "metadata.jsonl") as sidecar,
    ):
        controller.bind_writers(raw, sidecar)
        controller.begin_step(
            CAL.StepExpectation(shape, record_sample=True, warmup=False, repeat_index=3)
        )

        def original(_runner: object) -> str:
            operations.append("model-forward")
            return "result"

        result = controller.run_model_forward(runner, original, (), {}, metadata)
        controller.finish_step()

    assert result == "result"
    assert operations == [
        "record-1",
        "model-forward",
        "record-2",
        "sync-2",
        "elapsed-1-2",
    ]
    sample = json.loads((tmp_path / "raw.jsonl").read_text())
    assert set(sample) == CAL._SAMPLE_KEYS
    assert sample["duration_ns"] == 125_000
    assert sample["measurement_method"] == ("cuda_events_gpu_model_runner_model_forward")
    assert sample["cudagraph_mode"] == "NONE"
    assert sample["repeat_index"] == 3
    sidecar = json.loads((tmp_path / "metadata.jsonl").read_text())
    assert sidecar["scheduled_token_budget"] == 128
    assert sidecar["measurement_role"] == "target"
    assert sidecar["model_internal_collective"] == "none_tp1"
    assert len(sidecar["model_runner_input_fingerprint"]) == 64


def test_controller_setup_step_uses_no_cuda_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=lambda: True,
            Event=lambda **_kwargs: pytest.fail("setup step created a CUDA event"),
        )
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    controller = CAL.ForwardCalibrationController(
        hardware_profile_fingerprint="1" * 64,
        profile_fingerprint="2" * 64,
    )
    shape = CAL.CalibrationShape("prefill", (127,), (0,))
    runner = _Runner(_InputBatch(["r"], [0], [127]))
    with CAL.AppendOnlyJSONL(tmp_path / "metadata.jsonl") as metadata:
        controller.bind_metadata_writer(metadata)
        controller.begin_step(CAL.StepExpectation(shape, record_sample=False, role="setup"))
        assert (
            controller.run_model_forward(
                runner,
                lambda _runner: "setup-result",
                (),
                {},
                CAL.SchedulerMetadata({"r": 127}, 127),
            )
            == "setup-result"
        )
        controller.finish_step()
    assert controller.scheduler_step_count == 1
    assert json.loads((tmp_path / "metadata.jsonl").read_text())["measurement_role"] == ("setup")


def test_controller_rejects_relabel_padding_or_order_change() -> None:
    controller = CAL.ForwardCalibrationController(
        hardware_profile_fingerprint="1" * 64,
        profile_fingerprint="2" * 64,
    )
    requested = CAL.CalibrationShape("mixed", (1, 128), (127, 0))
    controller.begin_step(CAL.StepExpectation(requested, record_sample=False))
    runner = _Runner(_InputBatch(["prefill", "decode"], [0, 127], [128, 127]))
    with pytest.raises(CAL.ShapeConstructionError, match="differs from requested"):
        controller.run_model_forward(
            runner,
            lambda _runner: None,
            (),
            {},
            CAL.SchedulerMetadata({"prefill": 128, "decode": 1}, 129),
        )


def test_append_only_jsonl_is_canonical_fsynced_and_no_clobber(tmp_path: Path) -> None:
    path = tmp_path / "raw.jsonl"
    with CAL.AppendOnlyJSONL(path) as writer:
        writer.append({"z": 1, "a": "physical"})
        writer.append({"z": 2, "a": "forward"})
    assert path.read_bytes() == (b'{"a":"physical","z":1}\n{"a":"forward","z":2}\n')
    with pytest.raises(FileExistsError), CAL.AppendOnlyJSONL(path):
        pass


def test_oom_cleanup_removes_all_latency_streams_and_keeps_other_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "raw-forward.jsonl").write_text('{"duration_ns":1}\n')
    (tmp_path / "step-metadata.jsonl").write_text('{"shape_id":"x"}\n')
    (tmp_path / "held-out-split.json").write_text("{}\n")

    CAL._remove_latency_outputs_for_oom(tmp_path)

    assert not (tmp_path / "raw-forward.jsonl").exists()
    assert not (tmp_path / "step-metadata.jsonl").exists()
    assert (tmp_path / "held-out-split.json").is_file()
    assert CAL.is_cuda_oom(RuntimeError("CUDA out of memory"))


def test_publication_is_no_clobber_checksum_verified_and_fail_marked(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "raw-forward.jsonl").write_text('{"duration_ns":1}\n')
    (staging / "manifest.json").write_bytes(CAL.canonical_json_bytes({"formal_use_allowed": False}))
    CAL._write_sha256sums(staging)
    final = tmp_path / "published"

    CAL.publish_staging_no_clobber(staging, final)

    CAL.verify_sha256sums(final)
    assert (final / "PUBLICATION_COMPLETE.json").is_file()
    assert not (final / "PUBLICATION_INCOMPLETE").exists()
    assert (
        json.loads((final / "PUBLICATION_COMPLETE.json").read_text())["formal_use_allowed"] is False
    )
    with pytest.raises(CAL.PublicationError, match="refusing existing"):
        CAL.publish_staging_no_clobber(staging, final)


def test_manifest_is_preliminary_and_binds_every_staged_regular_file(tmp_path: Path) -> None:
    (tmp_path / "shape-plan.json").write_bytes(PLAN_PATH.read_bytes())
    (tmp_path / "residual-thresholds.json").write_bytes(THRESHOLD_PATH.read_bytes())
    plan = _load_plan()
    manifest = CAL._prepare_manifest(
        tmp_path,
        status="RAW_FORWARD_COMPLETE",
        plan=plan,
        slurm={
            "assigned_gpu_allocation": "PASS",
            "job_oversubscribe": "YES",
            "partition_oversubscribe": "FORCE:4",
        },
        hardware_profile_fingerprint="1" * 64,
        sample_count=140,
        scheduler_step_count=286,
        warmup_count=35,
    )

    assert manifest["formal_use_allowed"] is False
    assert manifest["evidence_label"]["calibrated_profile"] is False
    assert manifest["evidence_label"]["paper_result_allowed"] is False
    assert manifest["isolation_boundary"] == {
        "assigned_gpu_gres_verified": True,
        "cuda_visible_device_count": 1,
        "foreign_gpu_processes_rejected_pre_and_post": True,
        "job_oversubscribe": "YES",
        "partition_oversubscribe": "FORCE:4",
        "scope": "assigned_slurm_visible_gpu_only",
        "slurm_exclusive_directive_requested": False,
        "whole_node_exclusive_verified": False,
    }
    assert set(manifest["artifacts"]) == {
        "shape-plan.json",
        "residual-thresholds.json",
    }
    assert manifest["instrumentation"]["source_tree_modified"] is False


def test_sbatch_requests_one_l40s_and_gates_assigned_gpu_isolation() -> None:
    text = SBATCH_PATH.read_text(encoding="utf-8")

    assert text.count("#SBATCH --partition=short") == 1
    assert text.count("#SBATCH --constraint=l40s") == 1
    assert text.count("#SBATCH --gres=gpu:l40s:1") == 1
    assert "#SBATCH --exclusive" not in text
    assert text.count("#SBATCH --cpus-per-task=16") == 1
    assert text.count("#SBATCH --mem=96G") == 1
    assert text.count("#SBATCH --time=04:00:00") == 1
    assert 'scontrol write batch_script "${job_id}" "${submitted_batch_script}"' in text
    assert "MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256" in text
    assert "MOONKVSIM_CALIBRATION_SCRIPT_SHA256" in text
    assert "MOONKVSIM_ASSIGNED_GPU_ALLOCATION=PASS" in text
    assert "MOONKVSIM_EXCLUSIVE_ALLOCATION" not in text
    assert "Shared=0" not in text
    assert "OverSubscribe=FORCE:4" in text
    assert "TresPerNode=gpu:l40s:1" in text
    assert "set -Eeuo pipefail" in text
    assert 'if ! mkdir -p -- "${artifact_root}"' in text
    assert 'if ! staging_dir="$(mktemp -d ' in text
    assert 'if ! cp -- "${repository_harness}"' in text
    assert 'if ! calibration_sha256_line="$(sha256sum -- "${staged_harness}")"' in text
    assert 'if "${runtime_python}" "${staged_harness}"' in text
    assert "if nvidia-smi --query-compute-apps=pid,gpu_uuid" in text
    assert 'mktemp -d "/tmp/moonkvsim-aic-${job_id}.XXXXXX"' in text
    assert '"${runtime_python}" "${staged_harness}"' in text
    assert 'expected_repo_root="/home/comp/zhanzhao/MoonKVSim"' in text
    assert 'submit_dir="${SLURM_SUBMIT_DIR:-}"' in text
    assert "BASH_SOURCE" not in text
    assert "VLLM_ENABLE_V1_MULTIPROCESSING=0" in text
    assert "--query-compute-apps=pid,gpu_uuid" in text
    for forbidden in ("scancel", "squeue", "srun", "requeue", "release", "pkill"):
        assert forbidden not in text


def test_harness_source_exposes_exact_boundary_and_fixed_exit_codes() -> None:
    text = HARNESS_PATH.read_text(encoding="utf-8")

    assert CAL.MODEL_RUNNER_GIT_BLOB == "109ee6e7c836f23282df90937d5b9387b5380cdb"
    assert CAL.MODEL_RUNNER_SHA256 == (
        "960efef5498b41e59ab9a27e3c75367ad3ea2bb83caf6f8a9799a6f496b35297"
    )
    assert CAL.EXPECTED_VLLM_COMMIT == "644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504"
    assert CAL.EXPECTED_MODEL_REVISION == "b968826d9c46dd6066d109eabc6255188de91218"
    assert CAL.EXPECTED_AICONFIGURATOR_COMMIT == ("4b9d9dc51e02b5e9d4acc3688f3edf41693834c6")
    assert (
        CAL.EXIT_INVALID_INPUT,
        CAL.EXIT_SOURCE_DRIFT,
        CAL.EXIT_GPU_MISMATCH,
        CAL.EXIT_SHAPE_MISMATCH,
        CAL.EXIT_TIMING_FAILURE,
        CAL.EXIT_OOM,
        CAL.EXIT_PUBLICATION_FAILURE,
    ) == (2, 3, 4, 5, 6, 7, 8)
    assert "GPUModelRunner.execute_model = execute_model_wrapper" in text
    assert "GPUModelRunner._model_forward = model_forward_wrapper" in text
    assert "start.record()" in text
    assert "result = original(runner, *args, **kwargs)" in text
    assert "end.record()" in text
    assert "end.synchronize()" in text
    assert 'source_tree_modified": False' in text


def test_readme_has_exact_safe_command_resources_and_evidence_boundary() -> None:
    text = README_PATH.read_text(encoding="utf-8")

    assert "--gres=gpu:l40s:1 --constraint=l40s" in text
    assert "--constraint=l40s --exclusive" not in text
    assert "--cpus-per-task=16" in text
    assert "--mem=96G --time=04:00:00" in text
    assert "--hardware-profile l40s --tp-size 1 --pp-size 1" in text
    assert "formal_use_allowed=false" in text
    assert "OverSubscribe=FORCE:4" in text
    assert "whole-node exclusivity is not claimed" in text
    assert "30\N{EN DASH}90 minutes" in text
    assert "do not establish" in text
