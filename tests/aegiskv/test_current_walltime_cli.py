"""The public CLI deploys the same role priors and guard as the trained model."""

import hashlib
import json
import sys
from dataclasses import asdict, replace

import pytest

from moonkvsim.aegiskv.current.__main__ import load_workload, main
from moonkvsim.aegiskv.current.model import Agent, Config, Invocation
from moonkvsim.aegiskv.current.predictor import ContextRegressor
from moonkvsim.aegiskv.current.runtime import CurrentRuntime
from moonkvsim.aegiskv.evaluation_walltime_predictor import WalltimePredictor


def inputs(tmp_path, *, workflow="eval", invocation_model="model"):
    agent = Agent(
        workflow,
        "a",
        (),
        (Invocation((1, 2), (3,), model=invocation_model, output_limit_tokens=2),),
        999,
        role="worker",
    )
    config = Config(
        hosts=(0, 1),
        tp=1,
        layers=2,
        depth=1,
        slack_guard_ns=123,
        compute_dma_slowdown=0.005,
    )
    model = WalltimePredictor(
        ContextRegressor((0.0,) * 40, ("train",)),
        {"__all__": 10**9, "worker": 2 * 10**9},
        "model",
        slack_guard_ns=456,
    )
    paths = {}
    for name, data in (
        ("config", asdict(config)),
        ("workload", [asdict(agent)]),
        ("predictor", model.to_dict()),
    ):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(data))
    return agent, config, model, paths


def command(paths, out):
    return [
        "current",
        "run",
        "--out",
        str(out),
        "--config",
        str(paths["config"]),
        "--workload",
        str(paths["workload"]),
        "--walltime-predictor",
        str(paths["predictor"]),
        "--policy",
        "none",
        "--summary-only",
    ]


def test_cli_applies_model_priors_guard_and_seals_actual_deployment(tmp_path, monkeypatch):
    agent, config, model, paths = inputs(tmp_path)
    out = tmp_path / "result"
    monkeypatch.setattr(sys, "argv", command(paths, out))
    main()
    deployed = model.apply_priors((agent,))
    assert load_workload(out / "workload.json") == deployed
    assert json.loads((out / "run/config.json").read_text())["slack_guard_ns"] == 456
    manifest = json.loads((out / "MANIFEST.json").read_text())
    assert manifest["input_config_before_predictor"]["slack_guard_ns"] == 123
    assert manifest["prediction"]["training_workflows"] == ["train"]
    assert manifest["foreground_dma_compute_interference"]["coefficient"] == 0.005
    assert (
        manifest["predictor_sha256"]
        == hashlib.sha256((out / "predictor.json").read_bytes()).hexdigest()
    )
    expected = CurrentRuntime(
        replace(config, slack_guard_ns=model.slack_guard_ns),
        deployed,
        policy="none",
        predictor=model,
        retain_detailed_logs=False,
    ).run()
    actual = json.loads((out / "run/summary.json").read_text())
    for name, value in expected.items():
        assert actual[name] == value


@pytest.mark.parametrize(
    "workflow,model_name,error",
    [
        ("train", "model", ValueError),
        ("eval", "different-model", SystemExit),
    ],
)
def test_invalid_deployment_fails_before_output_creation(
    tmp_path, monkeypatch, workflow, model_name, error
):
    _, _, _, paths = inputs(tmp_path, workflow=workflow, invocation_model=model_name)
    out = tmp_path / "result"
    monkeypatch.setattr(sys, "argv", command(paths, out))
    with pytest.raises(error):
        main()
    assert not out.exists()


def test_legacy_and_walltime_models_cannot_be_silently_combined(tmp_path, monkeypatch):
    _, _, _, paths = inputs(tmp_path)
    out = tmp_path / "result"
    monkeypatch.setattr(sys, "argv", [*command(paths, out), "--predictor", str(paths["predictor"])])
    with pytest.raises(SystemExit):
        main()
    assert not out.exists()
