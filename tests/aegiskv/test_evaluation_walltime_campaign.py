import gzip
import json
from dataclasses import asdict, replace

import pytest

from moonkvsim.aegiskv.current.__main__ import digest, encoded, write_json
from moonkvsim.aegiskv.current.model import Agent, Config, Invocation
from moonkvsim.aegiskv.current.predictor import ContextRegressor
from moonkvsim.aegiskv.current.runtime import CurrentRuntime
from moonkvsim.aegiskv.evaluation_walltime_campaign import (
    ObservedRuntime,
    object_sha,
    run_condition,
    verify_completed,
)
from moonkvsim.aegiskv.evaluation_walltime_predictor import WalltimePredictor, pair_labels


def fixture():
    config = replace(Config(), hosts=(0, 1), tp=1, layers=2, depth=1)
    predictor = WalltimePredictor(
        ContextRegressor((0.0,) * 40, ("train",)), {"__all__": 2_000_000_000}, "test"
    )
    invocation = Invocation(tuple(range(520)), (3, 4), model="test", output_limit_tokens=8)
    agents = predictor.apply_priors(
        tuple(Agent("held", name, (), (invocation,), 10**10) for name in ("a", "b", "c"))
    )
    return config, agents, predictor


@pytest.mark.parametrize("policy", ["none", "dram", "aegiskv"])
def test_observation_delegates_prediction_and_is_exactly_transparent(policy):
    config, agents, predictor = fixture()
    kwargs = dict(policy=policy, predictor=predictor, retain_detailed_logs=True)
    base, observed = (
        CurrentRuntime(config, agents, **kwargs),
        ObservedRuntime(config, agents, **kwargs),
    )
    base_summary, summary = base.run(), observed.run()
    assert summary == base_summary
    assert observed.events == base.events and observed.events
    assert observed.flow_model.intervals == base.flow_model.intervals
    assert len(observed.captured_contexts) == len(summary["requests"]) == 3
    assert summary["predictor"] == predictor.name
    assert summary["oracle_reservation_count"] == 0
    # The delegate predicts one second, not the two-second role prior.
    assert {p.remaining_ns for p in observed.tracker.states.values()} == {10**9}
    labels = pair_labels(observed.captured_contexts, summary, run_id="unit", load=0.3)
    assert len({r["agent"] for r in labels}) == 3


def test_observer_preserves_core_training_overlap_guard():
    config, agents, predictor = fixture()
    with pytest.raises(ValueError, match="overlap"):
        ObservedRuntime(
            config, (replace(agents[0], workflow="train"),), policy="none", predictor=predictor
        )


def test_completion_reuse_binds_model_capture_and_result_artifacts(tmp_path):
    config, agents, predictor = fixture()
    for directory in ("models", "profiles", "workloads"):
        (tmp_path / directory).mkdir()
    write_json(tmp_path / "models/test.json", predictor.to_dict())
    write_json(tmp_path / "PRIORS.json", {"test": predictor.role_priors_ns})
    write_json(tmp_path / "PROTOCOL_SEAL.json", {"test": "immutable-input-seal"})
    profile = dict(
        schema="aegiskv.duration-grid.v1",
        model="test",
        tp=1,
        config=dict(num_hidden_layers=2, num_key_value_heads=4, head_dim=128),
        context_grid=[0, 1024],
        prefill_extend_grid=[1, 64, 256],
        rows=[],
    )
    for context in profile["context_grid"]:
        for stage, extend in [("prefill", 1), ("prefill", 64), ("prefill", 256), ("decode", 1)]:
            profile["rows"].append(
                dict(
                    stage=stage, context=context, extend=extend, latency_ns=1000 + context + extend
                )
            )
    write_json(tmp_path / "profiles/test.json", profile)
    payload = encoded([asdict(a) for a in agents])
    path = tmp_path / "workloads/test.json.gz"
    path.write_bytes(gzip.compress(payload, mtime=0))
    workload = dict(
        path="workloads/test.json.gz",
        sha256=digest(path),
        content_sha256=object_sha([asdict(a) for a in agents]),
        offered_load_proxy=0.3,
    )
    job = dict(
        id="unit",
        config=json.loads(encoded(asdict(config))),
        failure=None,
        policy="none",
        model="test",
        predictor="models/test.json",
        workload="test",
        detailed_logs=False,
        capture_context=True,
    )
    write_json(tmp_path / "PLAN.json", dict(jobs=[job], workloads={"test": workload}))
    write_json(
        tmp_path / "MANIFEST.json",
        dict(predictor_sha256={"models/test.json": digest(tmp_path / "models/test.json")}),
    )
    run_condition(tmp_path, job, capture=True)
    verify_completed(tmp_path, job)
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_completed(tmp_path, job, capture=False)
    model_path = tmp_path / "models/test.json"
    model = json.loads(model_path.read_text())
    model["regressor"]["weights"][0] = 1.0
    write_json(model_path, model)
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_completed(tmp_path, job)
    write_json(model_path, predictor.to_dict())
    (tmp_path / "runs/unit/contexts.jsonl.gz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="completed artifact changed"):
        verify_completed(tmp_path, job)
