from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from moonkvsim.aegiskv.experiment import (
    CellSpec,
    Scenario,
    core_variants,
    run_study_cell,
)
from moonkvsim.aegiskv.experiment_workload import load_experiment_records

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_RUNNER_PATH = (
    _REPOSITORY_ROOT / "benchmark/AegisKV/experiments/scripts/run_aegiskv_paper_sweeps.py"
)


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_test_continuous_batch_paper_gate",
        _RUNNER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_paper_runner_blocks_unwired_continuous_batch_residency() -> None:
    runner = _load_runner()

    with pytest.raises(
        runner.ExperimentError,
        match="paper sweep BLOCKED: continuous scheduler-step residency is not wired",
    ):
        runner._require_continuous_batch_paper_capability(
            {
                "metrics": {
                    "policy_effects": {
                        "compute_scheduler_model": (
                            "ONE_NONPREEMPTIVE_REQUEST_LANE_PER_GPU"
                        ),
                        "continuous_batch_residency_modeled": False,
                    }
                }
            },
            variant_id="aegiskv_unified",
            failure_count=2,
            concurrency=16,
            repetition="A",
        )


def test_paper_runner_accepts_explicit_wired_capability() -> None:
    runner = _load_runner()

    runner._require_continuous_batch_paper_capability(
        {
            "metrics": {
                "policy_effects": {
                    "compute_scheduler_model": "VLLM_CONTINUOUS_BATCH_SCHEDULER_STEP",
                    "continuous_batch_residency_modeled": True,
                }
            }
        },
        variant_id="aegiskv_unified",
        failure_count=2,
        concurrency=16,
        repetition="A",
    )


def test_current_study_payload_is_explicitly_blocked_from_paper_runner() -> None:
    runner = _load_runner()
    records = load_experiment_records(
        _REPOSITORY_ROOT
        / "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-shapes.jsonl"
    )
    result = run_study_cell(
        records,
        CellSpec(
            variant=core_variants()[0],
            context_bucket="8k",
            scenario=Scenario.NO_FAILURE,
            seed=7,
            repetition="A",
        ),
    )

    policy_effects = result.payload["metrics"]["policy_effects"]
    assert policy_effects["compute_scheduler_model"] == (
        "ONE_NONPREEMPTIVE_REQUEST_LANE_PER_GPU"
    )
    assert policy_effects["continuous_batch_residency_modeled"] is False
    with pytest.raises(runner.ExperimentError, match="paper sweep BLOCKED"):
        runner._require_continuous_batch_paper_capability(
            result.payload,
            variant_id="vanilla_mooncake_dram",
            failure_count=2,
            concurrency=16,
            repetition="A",
        )
