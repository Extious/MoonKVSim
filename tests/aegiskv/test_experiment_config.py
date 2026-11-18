from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from moonkvsim.aegiskv.experiment import DEFAULT_PARAMETERS
from moonkvsim.aegiskv.experiment_config import (
    ExperimentConfigError,
    default_config_dir,
    failure_count,
    gpu_recovery_time_minutes,
    load_experiment_configs,
    matrix_seeds,
    model_parameters_from_configs,
    repository_root,
    snapshot_experiment_configs,
    workflow_concurrency,
    workload_paths,
)

ROOT = Path(__file__).resolve().parents[2]


def test_repository_root_finds_checkout_from_nested_path() -> None:
    assert repository_root(Path(__file__)) == ROOT


def test_living_three_layer_configs_map_to_locked_parameters() -> None:
    configs = load_experiment_configs(root=ROOT)
    assert configs.directory == default_config_dir(ROOT)
    parameters = model_parameters_from_configs(configs)
    assert parameters == replace(DEFAULT_PARAMETERS, policy_chunk_tokens=4096,
                                 runtime_semantics="mooncake_prompt_v1")
    assert set(configs.engine) == {
        "schema",
        "model",
        "parallelism",
        "hardware",
        "memory",
        "store",
        "network",
        "control",
    }
    assert configs.engine["store"]["capacity_bytes"] == 1_000_000_000_000
    assert configs.engine["memory"] == {"peer_hbm_alpha": 0.2}
    assert configs.engine["network"] == {
        "transport": "PCIE",
        "effective_bandwidth_bytes_per_second": 25_000_000_000,
        "transfer_setup_ns": 250_000,
    }
    assert matrix_seeds(configs.requests) == (0, 1, 2, 3, 4)
    assert workflow_concurrency(configs.requests) == 16
    assert set(configs.requests) == {
        "schema",
        "status",
        "seeds",
        "dataset",
        "replay",
        "context",
    }
    assert set(configs.requests["dataset"]) == {
        "name",
        "split",
        "source_revision",
        "source_sha256",
        "frozen_artifact",
    }
    assert configs.requests["replay"] == {"workflow_concurrency": 16}
    assert configs.requests["context"] == {
        "max_model_len_tokens": 131_072,
        "minimum_task_count_for_ecdf": 160,
        "overflow_policy": "split_evidence_if_below_minimum",
    }
    assert configs.requests["dataset"]["name"] == "FanOutQA"
    assert configs.requests["status"] == "ready_frozen_fanoutqa_workload"
    assert configs.requests["dataset"]["frozen_artifact"]["task_count"] == 160
    assert set(configs.failure) == {
        "schema",
        "type",
        "failure_count",
        "injection_progress_percent",
        "gpu_recovery_time_minutes",
    }
    assert failure_count(configs.failure) == 2
    assert configs.failure["injection_progress_percent"] == 60
    assert gpu_recovery_time_minutes(configs.failure) == 2
    assert parameters.failure_detection_ns == 0
    assert parameters.failure_progress_per_mille == 600
    assert parameters.gpu_recovery_time_ns == 120_000_000_000
    assert parameters.model_weights_bytes_per_gpu == 16_381_470_720
    assert parameters.runtime_fixed_bytes_per_gpu == 2 * 1024**3
    assert parameters.kv_capacity_bytes_per_gpu == 24_420_718_592
    assert parameters.peer_hbm_quota_bytes_per_gpu == 8_589_934_592
    assert parameters.peer_hbm_max_quota_bytes_per_gpu == 21_474_836_480


def test_living_fanoutqa_workload_resolves_frozen_artifact() -> None:
    configs = load_experiment_configs(root=ROOT)
    workload, manifest = workload_paths(configs.requests, root=ROOT)
    assert workload.name == "fanoutqa-dev-qwen3-8b-160.jsonl"
    assert manifest.name == "fanoutqa-dev-qwen3-8b-160-manifest.json"


def test_config_dir_rejects_extra_files(tmp_path: Path) -> None:
    source = default_config_dir(ROOT)
    snapshot_experiment_configs(source, tmp_path)
    (tmp_path / "notes.txt").write_text("extra\n", encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="only contain"):
        load_experiment_configs(tmp_path, root=ROOT)


def test_failure_layer_rejects_non_gpu_failure(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    failure_path = tmp_path / "failure.json"
    text = failure_path.read_text(encoding="utf-8").replace(
        '"GPU_FAILURE"',
        '"LINK_FAILURE"',
        1,
    )
    failure_path.write_text(text, encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="GPU_FAILURE"):
        load_experiment_configs(tmp_path, root=ROOT)


def test_failure_layer_rejects_unknown_fields(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    failure_path = tmp_path / "failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    failure["repair_after_s"] = 1
    failure_path.write_text(json.dumps(failure), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="Additional properties"):
        load_experiment_configs(tmp_path, root=ROOT)


@pytest.mark.parametrize("value", [0, -1, 100, True, None])
def test_failure_layer_rejects_invalid_injection_progress(
    tmp_path: Path,
    value: object,
) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    failure_path = tmp_path / "failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    failure["injection_progress_percent"] = value
    failure_path.write_text(json.dumps(failure), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="injection_progress_percent"):
        load_experiment_configs(tmp_path, root=ROOT)


@pytest.mark.parametrize("value", [0, -1, True, None])
def test_failure_layer_rejects_invalid_gpu_recovery_time(
    tmp_path: Path,
    value: object,
) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    failure_path = tmp_path / "failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    failure["gpu_recovery_time_minutes"] = value
    failure_path.write_text(json.dumps(failure), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="gpu_recovery_time_minutes"):
        load_experiment_configs(tmp_path, root=ROOT)


@pytest.mark.parametrize("value", [0, -1, True, None])
def test_failure_layer_rejects_invalid_failure_count(
    tmp_path: Path,
    value: object,
) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    failure_path = tmp_path / "failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    failure["failure_count"] = value
    failure_path.write_text(json.dumps(failure), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="failure_count"):
        load_experiment_configs(tmp_path, root=ROOT)


def test_engine_layer_rejects_dp_scope_drift(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    engine_path = tmp_path / "engine.json"
    engine = json.loads(engine_path.read_text(encoding="utf-8"))
    engine["parallelism"]["allowed_data_parallel_sizes"] = [8]
    engine_path.write_text(json.dumps(engine), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match=r"extra=.*allowed_data_parallel_sizes"):
        load_experiment_configs(tmp_path, root=ROOT)


@pytest.mark.parametrize("value", [-0.01, 0.51, True, None, "0.2"])
def test_engine_layer_rejects_invalid_peer_hbm_alpha(
    tmp_path: Path,
    value: object,
) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    engine_path = tmp_path / "engine.json"
    engine = json.loads(engine_path.read_text(encoding="utf-8"))
    engine["memory"]["peer_hbm_alpha"] = value
    engine_path.write_text(json.dumps(engine), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="peer_hbm_alpha"):
        load_experiment_configs(tmp_path, root=ROOT)


@pytest.mark.parametrize("value", [0, 0.5])
def test_engine_layer_accepts_peer_hbm_alpha_bounds(
    tmp_path: Path,
    value: float,
) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    engine_path = tmp_path / "engine.json"
    engine = json.loads(engine_path.read_text(encoding="utf-8"))
    engine["memory"]["peer_hbm_alpha"] = value
    engine_path.write_text(json.dumps(engine), encoding="utf-8")
    assert model_parameters_from_configs(
        load_experiment_configs(tmp_path, root=ROOT)
    ).peer_hbm_alpha == value


def test_engine_layer_rejects_manual_model_footprint_fields(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    engine_path = tmp_path / "engine.json"
    engine = json.loads(engine_path.read_text(encoding="utf-8"))
    engine["memory"]["model_weights_bytes_per_gpu"] = 16 * 1024**3
    engine_path.write_text(json.dumps(engine), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="model_weights_bytes_per_gpu"):
        load_experiment_configs(tmp_path, root=ROOT)


def test_requests_layer_rejects_fanoutqa_dataset_drift(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    requests_path = tmp_path / "requests.json"
    requests = json.loads(requests_path.read_text(encoding="utf-8"))
    requests["dataset"]["source_revision"] = "wrong-revision"
    requests_path.write_text(json.dumps(requests), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="source_revision"):
        load_experiment_configs(tmp_path, root=ROOT)


def test_frozen_fanoutqa_status_resolves_artifact_paths(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    requests_path = tmp_path / "requests.json"
    requests = json.loads(requests_path.read_text(encoding="utf-8"))
    requests["status"] = "ready_frozen_fanoutqa_workload"
    requests["dataset"]["frozen_artifact"] = {
        "path": "benchmark/AegisKV/experiments/workloads/fanoutqa.jsonl",
        "manifest_path": "benchmark/AegisKV/experiments/workloads/fanoutqa-manifest.json",
        "sha256": "0" * 64,
        "manifest_sha256": "1" * 64,
        "normalizer_version": "moonkvsim.fanoutqa.v1",
        "task_count": 310,
    }
    requests_path.write_text(json.dumps(requests), encoding="utf-8")

    configs = load_experiment_configs(tmp_path, root=ROOT)
    workload, manifest = workload_paths(configs.requests, root=ROOT)
    assert workload == ROOT / "benchmark/AegisKV/experiments/workloads/fanoutqa.jsonl"
    assert manifest == ROOT / "benchmark/AegisKV/experiments/workloads/fanoutqa-manifest.json"


def test_frozen_fanoutqa_rejects_task_count_below_ecdf_minimum(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    requests_path = tmp_path / "requests.json"
    requests = json.loads(requests_path.read_text(encoding="utf-8"))
    requests["status"] = "ready_frozen_fanoutqa_workload"
    requests["dataset"]["frozen_artifact"] = {
        "path": "benchmark/AegisKV/experiments/workloads/fanoutqa.jsonl",
        "manifest_path": "benchmark/AegisKV/experiments/workloads/fanoutqa-manifest.json",
        "sha256": "0" * 64,
        "manifest_sha256": "1" * 64,
        "normalizer_version": "moonkvsim.fanoutqa.v1",
        "task_count": 159,
    }
    requests_path.write_text(json.dumps(requests), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="task_count is below"):
        load_experiment_configs(tmp_path, root=ROOT)


@pytest.mark.parametrize("value", [0, -1, True, None])
def test_requests_layer_rejects_invalid_workflow_concurrency(
    tmp_path: Path, value: object
) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    requests_path = tmp_path / "requests.json"
    requests = json.loads(requests_path.read_text(encoding="utf-8"))
    requests["replay"]["workflow_concurrency"] = value
    requests_path.write_text(json.dumps(requests), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="workflow_concurrency"):
        load_experiment_configs(tmp_path, root=ROOT)


@pytest.mark.parametrize("value", [0, 30, 159, 311, True, None])
def test_requests_layer_rejects_invalid_minimum_task_count_for_ecdf(
    tmp_path: Path, value: object
) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    requests_path = tmp_path / "requests.json"
    requests = json.loads(requests_path.read_text(encoding="utf-8"))
    requests["context"]["minimum_task_count_for_ecdf"] = value
    requests_path.write_text(json.dumps(requests), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="minimum_task_count_for_ecdf"):
        load_experiment_configs(tmp_path, root=ROOT)


def test_requests_layer_rejects_context_overflow_policy_drift(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    requests_path = tmp_path / "requests.json"
    requests = json.loads(requests_path.read_text(encoding="utf-8"))
    requests["context"]["overflow_policy"] = "truncate"
    requests_path.write_text(json.dumps(requests), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="overflow_policy"):
        load_experiment_configs(tmp_path, root=ROOT)


def test_config_dir_rejects_extra_directory(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    (tmp_path / "archive").mkdir()
    with pytest.raises(ExperimentConfigError, match="unexpected files"):
        load_experiment_configs(tmp_path, root=ROOT)
