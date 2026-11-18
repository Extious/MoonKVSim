"""Causal context capture and offline Agent wall-time regression.

Labels include queueing and end at the same Agent's final invocation. The model
is a lightweight hashed-text regressor, not a validated semantic encoder.
Offline reference CPM slack is a queue-conditioned diagnostic, not oracle input
to a deployed predictor or a guarantee about counterfactual scheduling slack.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from statistics import mean, median

from .current.model import Agent, Config
from .current.predictor import ContextRegressor, TrainingExample
from .current.runtime import CurrentRuntime
from .current.tracker import Context, Tracker, prior_predictor

SCHEMA = "aegiskv.agent-walltime-predictor.v1"


def context_from_dict(value: dict) -> Context:
    return Context(
        **{
            **value,
            "previous_durations_ns": tuple(value["previous_durations_ns"]),
            "previous_output_tokens": tuple(value["previous_output_tokens"]),
        }
    )


class ContextCaptureRuntime(CurrentRuntime):
    """Observe the existing predictor boundary without changing its Context.

    Identity is sidecar information; it is never passed to feature extraction.
    No timing label is constructed until the healthy runtime has completed.
    """

    def __init__(self, config: Config, agents: tuple[Agent, ...], *, duration_profile=None):
        self.captured_contexts: list[dict] = []
        self._capture_identity = None
        super().__init__(
            config,
            agents,
            policy="none",
            predictor=self._capture,
            duration_profile=duration_profile,
            retain_detailed_logs=False,
        )

    def _submit(self, state):
        previous = self._capture_identity
        self._capture_identity = (
            state.spec.key,
            state.spec.workflow,
            state.call + 1,
            self.des.now_ns,
        )
        try:
            super()._submit(state)
        finally:
            self._capture_identity = previous

    def _capture(self, context: Context) -> int:
        if self._capture_identity is None:
            raise RuntimeError("predictor called outside a submission")
        agent, workflow, invocation, submitted = self._capture_identity
        if submitted != self.des.now_ns:
            raise RuntimeError("context capture crossed an event boundary")
        self.captured_contexts.append(
            dict(
                agent=agent,
                workflow=workflow,
                invocation=invocation,
                submitted_ns=submitted,
                raw_context=asdict(context),
            )
        )
        return prior_predictor(context)


def pair_labels(captures: list[dict], summary: dict, *, run_id: str, load: float) -> list[dict]:
    """Join only after completion; never use invocation latency as a multi-call label."""
    if not summary["complete"] or not summary["output_tokens_exact"] or summary["failure"]:
        raise ValueError("labels require a complete, exact-output, healthy run")
    requests = {}
    final = defaultdict(int)
    for request in summary["requests"]:
        key = request["agent"], request["invocation"], request["submit_ns"]
        if key in requests:
            raise ValueError("duplicate invocation identity")
        requests[key] = request
        final[request["agent"]] = max(final[request["agent"]], request["finish_ns"])
    rows, seen = [], set()
    for capture in captures:
        key = capture["agent"], capture["invocation"], capture["submitted_ns"]
        if key not in requests or key in seen:
            raise ValueError("context/request pairing is not one-to-one")
        seen.add(key)
        context = context_from_dict(capture["raw_context"])
        earlier = sorted(
            (r for r in requests.values() if r["agent"] == key[0] and r["invocation"] < key[1]),
            key=lambda r: r["invocation"],
        )
        if (
            context.completed_calls != len(earlier)
            or context.previous_durations_ns != tuple(r["latency_ns"] for r in earlier)
            or context.previous_output_tokens != tuple(r["output_tokens"] for r in earlier)
            or any(r["finish_ns"] > key[2] for r in earlier)
        ):
            raise ValueError("context contains inconsistent or future history")
        label = final[key[0]] - key[2]
        if label <= 0:
            raise ValueError("nonpositive Agent-completion label")
        rows.append(
            {
                **capture,
                "sample_id": f"{run_id}/{key[0]}#{key[1]}",
                "run_id": run_id,
                "nominal_load": load,
                "agent_final_finish_ns": final[key[0]],
                "invocation_finish_ns": requests[key]["finish_ns"],
                "remaining_ns": label,
            }
        )
    if seen != requests.keys():
        raise ValueError("a completed invocation lacks captured context")
    return rows


def fit_role_priors(rows: list[dict]) -> dict[str, int]:
    groups = defaultdict(list)
    for row in rows:
        if row["invocation"] == 0:
            for role in (row["raw_context"]["role"], "__all__"):
                groups[role].append(row["remaining_ns"])
    if not groups:
        raise ValueError("role priors require first-invocation Agent labels")
    return {role: max(1, round(median(values))) for role, values in sorted(groups.items())}


@dataclass(frozen=True)
class WalltimePredictor:
    regressor: ContextRegressor
    role_priors_ns: dict[str, int]
    model: str
    slack_guard_ns: int = 0
    name: str = "hashed-text-agent-submission-to-completion-v1"

    @property
    def training_workflows(self) -> tuple[str, ...]:
        return self.regressor.training_workflows

    def context(self, raw: Context) -> Context:
        if raw.model != self.model:
            raise ValueError("predictor model does not match Context")
        return replace(
            raw, prior_ns=self.role_priors_ns.get(raw.role, self.role_priors_ns["__all__"])
        )

    def __call__(self, raw: Context) -> int:
        return self.regressor(self.context(raw))

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, **asdict(self)}

    @classmethod
    def from_dict(cls, value: dict) -> WalltimePredictor:
        value = dict(value)
        if value.pop("schema") != SCHEMA:
            raise ValueError("unsupported walltime predictor")
        regressor = dict(value.pop("regressor"))
        regressor["weights"] = tuple(regressor["weights"])
        regressor["training_workflows"] = tuple(regressor["training_workflows"])
        if any(type(v) is not int or v <= 0 for v in value["role_priors_ns"].values()):
            raise ValueError("invalid deployment role prior")
        if type(value["slack_guard_ns"]) is not int or value["slack_guard_ns"] < 0:
            raise ValueError("invalid calibrated guard")
        return cls(regressor=ContextRegressor(**regressor), **value)

    def apply_priors(self, agents: tuple[Agent, ...]) -> tuple[Agent, ...]:
        if set(a.workflow for a in agents) & set(self.training_workflows):
            raise ValueError("deployment workflows overlap training workflows")
        return tuple(
            replace(a, prior_ns=self.role_priors_ns.get(a.role, self.role_priors_ns["__all__"]))
            for a in agents
        )


def fit_model(rows: list[dict], *, epochs: int = 300) -> WalltimePredictor:
    models = {r["raw_context"]["model"] for r in rows}
    if len(models) != 1:
        raise ValueError("fit one model at a time")
    priors = fit_role_priors(rows)
    examples = tuple(
        TrainingExample(
            row["workflow"],
            replace(
                context_from_dict(row["raw_context"]),
                prior_ns=priors.get(row["raw_context"]["role"], priors["__all__"]),
            ),
            row["remaining_ns"],
        )
        for row in sorted(rows, key=lambda row: row["sample_id"])
    )
    return WalltimePredictor(ContextRegressor.fit(examples, epochs=epochs), priors, models.pop())


def error_rows(model: WalltimePredictor, rows: list[dict], *, heldout: bool = True) -> list[dict]:
    if heldout and set(r["workflow"] for r in rows) & set(model.training_workflows):
        raise ValueError("held-out evaluation overlaps fitted workflows")
    result = []
    for row in rows:
        raw = context_from_dict(row["raw_context"])
        derived = model.context(raw)
        prediction = model(raw)
        result.append(
            {
                **row,
                "derived_context": asdict(derived),
                "prior_training_workflows": list(model.training_workflows),
                "prediction_ns": prediction,
                "signed_error_ns": prediction - row["remaining_ns"],
                "absolute_error_ns": abs(prediction - row["remaining_ns"]),
                "role_median_baseline_ns": derived.prior_ns,
                "baseline_absolute_error_ns": abs(derived.prior_ns - row["remaining_ns"]),
            }
        )
    return result


def quantile(values, q=0.9):
    values = sorted(values)
    if not values or not 0 < q <= 1:
        raise ValueError("nonempty samples and a valid quantile are required")
    return values[math.ceil(q * len(values)) - 1]


def error_metrics(rows: list[dict]) -> dict:
    def group(values):
        workflows = {r["workflow"] for r in values}
        return dict(
            observations=len(values),
            workflows=len(workflows),
            mae_ns=mean(r["absolute_error_ns"] for r in values),
            rmse_ns=math.sqrt(mean(r["signed_error_ns"] ** 2 for r in values)),
            bias_ns=mean(r["signed_error_ns"] for r in values),
            p90_absolute_error_ns=quantile(r["absolute_error_ns"] for r in values),
            role_median_mae_ns=mean(r["baseline_absolute_error_ns"] for r in values),
            workflow_macro_mae_ns=mean(
                mean(r["absolute_error_ns"] for r in values if r["workflow"] == w)
                for w in sorted(workflows)
            ),
        )

    return {
        "all": group(rows),
        "by_load": {
            str(load): group([r for r in rows if r["nominal_load"] == load])
            for load in sorted({r["nominal_load"] for r in rows})
        },
    }


def reference_slack_errors(
    agents: tuple[Agent, ...], config: Config, rows: list[dict], folds: dict[str, WalltimePredictor]
) -> list[dict]:
    """OOF predictions versus offline queue-conditioned reference CPM, at fixed windows.

    Every point is right-continuous after all submits/publications/completions at
    that timestamp. Future finish times occur only in this offline comparator.
    """
    result = []
    for workflow in sorted({a.workflow for a in agents}):
        selected = [r for r in rows if r["workflow"] == workflow]
        model = folds[workflow]
        if workflow in model.training_workflows:
            raise ValueError("calibration fold includes its held-out workflow")
        first = {r["agent"]: r for r in selected if r["invocation"] == 0}
        predicted_agents = tuple(
            replace(a, prior_ns=model.role_priors_ns.get(a.role, model.role_priors_ns["__all__"]))
            for a in agents
            if a.workflow == workflow
        )
        reference_agents = tuple(
            replace(a, prior_ns=first[a.key]["remaining_ns"]) for a in predicted_agents
        )
        pred = Tracker(predicted_agents, replace(config, slack_guard_ns=0))
        ref = Tracker(reference_agents, replace(config, slack_guard_ns=0, prediction_ttl_ns=10**30))
        events = []
        for row in selected:
            events.append((row["submitted_ns"], 0, row["agent"], row))
            events.append(
                (row["submitted_ns"] + config.prediction_latency_ns, 1, row["agent"], row)
            )
        for key, row in first.items():
            events.append((row["agent_final_finish_ns"], 2, key, row))
        events.sort(key=lambda e: (e[0], e[1], e[2], e[3]["invocation"]))
        cursor = 0
        window = config.control_window_ns
        start = min(a.release_ns for a in predicted_agents)
        end = max(row["agent_final_finish_ns"] for row in selected)
        for now in range(math.ceil(start / window) * window, end + 1, window):
            while cursor < len(events) and events[cursor][0] <= now:
                _, kind, key, row = events[cursor]
                if kind == 0:
                    for tracker in (pred, ref):
                        tracker.submit(key, row["invocation"], row["submitted_ns"])
                    ref.publish(key, row["invocation"], row["submitted_ns"], row["remaining_ns"])
                elif kind == 1:
                    pred.publish(
                        key,
                        row["invocation"],
                        row["submitted_ns"],
                        model(context_from_dict(row["raw_context"])),
                    )
                else:
                    pred.states[key].finished = ref.states[key].finished = True
                cursor += 1
            predicted, reference = pred.slack(now), ref.slack(now)
            for key in pred.order:
                if not pred.states[key].finished:
                    result.append(
                        dict(
                            run_id=selected[0]["run_id"],
                            workflow=workflow,
                            agent=key,
                            time_ns=now,
                            predicted_slack_ns=predicted[key],
                            reference_slack_ns=reference[key],
                            overestimation_ns=max(0, predicted[key] - reference[key]),
                            fallback=workflow in pred.fallback_workflows,
                        )
                    )
    return result
