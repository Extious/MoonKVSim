import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from moonkvsim.aegiskv.current.model import Agent, Config, Invocation
from moonkvsim.aegiskv.current.predictor import ContextRegressor
from moonkvsim.aegiskv.current.runtime import CurrentRuntime
from moonkvsim.aegiskv.current.tracker import Context
from moonkvsim.aegiskv.evaluation_walltime_predictor import (
    ContextCaptureRuntime,
    WalltimePredictor,
    context_from_dict,
    error_rows,
    fit_model,
    pair_labels,
    quantile,
    reference_slack_errors,
)


def small():
    return replace(
        Config(),
        hosts=(0, 1),
        tp=1,
        layers=2,
        depth=1,
        prefill_ns_per_token=1_000_000,
        decode_ns_per_token=2_000_000,
    )


def task(workflow, name, calls=1, output=(9,)):
    return Agent(
        workflow,
        name,
        (),
        tuple(
            Invocation((1, 2, 3), output, text="same visible question", output_limit_tokens=8)
            for _ in range(calls)
        ),
        10**10,
    )


def samples():
    result = []
    for workflow, duration in [("a", 10**9), ("b", 3 * 10**9), ("held", 9 * 10**9)]:
        context = Context("model", "role", "visible question", 12, 0, (), (), 0, 10**10)
        for load in (0.3, 0.65, 0.9):
            result.append(
                dict(
                    sample_id=f"{load}/{workflow}/x#0",
                    workflow=workflow,
                    agent=f"{workflow}/x",
                    invocation=0,
                    nominal_load=load,
                    raw_context=asdict(context),
                    remaining_ns=round(duration * (1 + load)),
                    submitted_ns=0,
                    agent_final_finish_ns=round(duration * (1 + load)),
                    run_id=f"load{load}",
                )
            )
    return result


def test_capture_matches_runtime_and_same_context_identities_do_not_collapse():
    agents = (task("w", "a"), task("w", "b"), task("w", "c"))
    observed = ContextCaptureRuntime(small(), agents)
    baseline = CurrentRuntime(small(), agents, policy="none", retain_detailed_logs=False)
    summary = observed.run()
    assert summary["requests"] == baseline.run()["requests"]
    captures = observed.captured_contexts
    assert len(captures) == 3 and len({r["agent"] for r in captures}) == 3
    assert captures[0]["raw_context"] == captures[1]["raw_context"]
    labels = pair_labels(captures, summary, run_id="test", load=0.3)
    # The third Agent was submitted at zero but had to queue behind an active request.
    assert max(r["remaining_ns"] for r in labels) > min(r["remaining_ns"] for r in labels)


def test_multicall_labels_end_at_agent_final_finish_and_only_past_history_is_visible():
    runtime = ContextCaptureRuntime(small(), (task("w", "a", calls=2),))
    summary = runtime.run()
    labeled = pair_labels(runtime.captured_contexts, summary, run_id="test", load=0.3)
    assert len(labeled) == 2
    assert labeled[0]["agent_final_finish_ns"] == labeled[1]["agent_final_finish_ns"]
    assert labeled[0]["remaining_ns"] > labeled[0]["invocation_finish_ns"]
    assert labeled[1]["remaining_ns"] == summary["requests"][1]["latency_ns"]
    assert labeled[0]["raw_context"]["previous_output_tokens"] == ()
    assert labeled[1]["raw_context"]["previous_output_tokens"] == (1,)


def test_future_output_change_does_not_enter_first_online_context():
    contexts = []
    for output in [(8,), (8, 9, 10)]:
        runtime = ContextCaptureRuntime(small(), (task("w", "a", output=output),))
        runtime.run()
        contexts.append(runtime.captured_contexts[0]["raw_context"])
    assert contexts[0] == contexts[1]


def test_fold_priors_and_predictions_are_unchanged_by_heldout_label_poisoning():
    original = samples()
    altered = deepcopy(original)
    for row in altered:
        if row["workflow"] == "held":
            row["remaining_ns"] *= 100
            row["raw_context"]["prior_ns"] *= 20

    def fit(rs):
        return fit_model([r for r in rs if r["workflow"] != "held"], epochs=5)

    before, after = fit(original), fit(altered)
    assert before.to_dict() == after.to_dict()
    first = error_rows(before, [r for r in original if r["workflow"] == "held"])
    second = error_rows(after, [r for r in altered if r["workflow"] == "held"])
    assert [r["prediction_ns"] for r in first] == [r["prediction_ns"] for r in second]
    assert {r["nominal_load"] for r in first} == {0.3, 0.65, 0.9}
    assert set(before.training_workflows) == {"a", "b"}
    assert first[0]["raw_context"]["prior_ns"] == 10**10
    assert first[0]["derived_context"]["prior_ns"] != 10**10


def test_model_roundtrip_model_identity_and_training_separation():
    fitted = fit_model([r for r in samples() if r["workflow"] != "held"], epochs=5)
    loaded = WalltimePredictor.from_dict(json.loads(json.dumps(fitted.to_dict())))
    context = context_from_dict(samples()[-1]["raw_context"])
    assert loaded(context) == fitted(context)
    with pytest.raises(ValueError, match="overlaps"):
        error_rows(loaded, samples())
    with pytest.raises(ValueError, match="overlap"):
        loaded.apply_priors((task("a", "x"),))
    with pytest.raises(ValueError, match="model"):
        loaded(replace(context, model="other"))
    with pytest.raises(ValueError, match="overlap"):
        CurrentRuntime(small(), (task("a", "x"),), predictor=loaded)


def test_slack_guard_uses_positive_cpm_error_not_duration_error():
    config = replace(small(), control_window_ns=10**9, prediction_latency_ns=0)
    agents = (task("held", "a"), task("held", "b"))
    context = Context("model", "role", "same", 3, 0, (), (), 0, 10**10)
    # Equal actual branches have zero slack. Their unstarted role priors below
    # deliberately differ, producing a positive pre-submission slack error.
    agents = (replace(agents[0], role="long"), replace(agents[1], role="short"))
    model = WalltimePredictor(
        ContextRegressor((0.0,) * 40, ("train",)),
        {"long": 10**10, "short": 10**9, "__all__": 10**9},
        "model",
    )
    rows = [
        dict(
            workflow="held",
            agent=a.key,
            invocation=0,
            submitted_ns=2 * 10**9,
            agent_final_finish_ns=5 * 10**9,
            remaining_ns=3 * 10**9,
            raw_context=asdict(replace(context, role=a.role)),
            run_id="test",
        )
        for a in agents
    ]
    points = reference_slack_errors(agents, config, rows, {"held": model})
    first = next(p for p in points if p["agent"] == "held/b" and p["time_ns"] == 0)
    assert first["reference_slack_ns"] == 0
    assert first["overestimation_ns"] == 9 * 10**9
    assert quantile([0] * 10 + [9, 20]) == 9


def test_incomplete_or_unpaired_labels_are_rejected():
    runtime = ContextCaptureRuntime(small(), (task("w", "a"),))
    summary = runtime.run()
    with pytest.raises(ValueError, match="lacks"):
        pair_labels([], summary, run_id="test", load=0.3)
    with pytest.raises(ValueError, match="complete"):
        pair_labels(runtime.captured_contexts, {**summary, "complete": False}, run_id="x", load=0.3)
