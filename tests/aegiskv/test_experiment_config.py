from __future__ import annotations

import json
from pathlib import Path

import pytest

from moonkvsim.aegiskv.experiment import DEFAULT_PARAMETERS
from moonkvsim.aegiskv.experiment_config import (
    ExperimentConfigError,
    default_config_dir,
    load_experiment_configs,
    matrix_seeds,
    model_parameters_from_configs,
    repository_root,
    snapshot_experiment_configs,
    workload_paths,
)

ROOT = Path(__file__).resolve().parents[2]


def test_repository_root_finds_checkout_from_nested_path() -> None:
    assert repository_root(Path(__file__)) == ROOT


def test_living_three_layer_configs_map_to_locked_parameters() -> None:
    configs = load_experiment_configs(root=ROOT)
    assert configs.directory == default_config_dir(ROOT)
    parameters = model_parameters_from_configs(configs)
    assert parameters == DEFAULT_PARAMETERS
    assert matrix_seeds(configs.requests) == (0, 1, 2)
    workload, manifest = workload_paths(configs.requests, root=ROOT)
    assert workload.is_file()
    assert manifest.is_file()
    assert workload.name == "weka-e2-two-workflow-shapes.jsonl"


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


def test_engine_layer_rejects_dp_scope_drift(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    engine_path = tmp_path / "engine.json"
    engine = json.loads(engine_path.read_text(encoding="utf-8"))
    engine["parallelism"]["allowed_data_parallel_sizes"] = [4, 8]
    engine_path.write_text(json.dumps(engine), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="allowed_data_parallel_sizes"):
        load_experiment_configs(tmp_path, root=ROOT)


def test_requests_layer_rejects_frozen_workload_hash_drift(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    requests_path = tmp_path / "requests.json"
    requests = json.loads(requests_path.read_text(encoding="utf-8"))
    requests["workload"]["frozen_artifact"]["sha256"] = "0" * 64
    requests_path.write_text(json.dumps(requests), encoding="utf-8")
    with pytest.raises(ExperimentConfigError, match="SHA-256 drifted"):
        load_experiment_configs(tmp_path, root=ROOT)


def test_config_dir_rejects_extra_directory(tmp_path: Path) -> None:
    snapshot_experiment_configs(default_config_dir(ROOT), tmp_path)
    (tmp_path / "archive").mkdir()
    with pytest.raises(ExperimentConfigError, match="unexpected files"):
        load_experiment_configs(tmp_path, root=ROOT)
