"""Offline frozen-Tracker diagnostic; no DES, fitting, or prediction forward."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from statistics import mean

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
CAMPAIGN = ROOT / "walltime-primary-v3"
TRAINING = ROOT / "reviews/walltime-predictor-training-v1"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def rows(path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def quantile(values, q=0.9):
    values = sorted(values)
    return values[math.ceil(q * len(values)) - 1]


def forbidden(*args, **kwargs):
    raise AssertionError("DES/fitting/prediction-forward is forbidden in this diagnostic")


def main():
    if (OUT / "COMPLETE.json").exists():
        raise FileExistsError("assessment already sealed")
    sources = {str(Path(__file__).resolve()): digest(Path(__file__))}

    def bind(path, expected=None):
        actual = digest(path)
        if expected is not None:
            assert actual == expected, path
        sources[str(path.resolve())] = actual
        return actual

    seal = read(CAMPAIGN / "PROTOCOL_SEAL.json")
    seal_hash = bind(CAMPAIGN / "PROTOCOL_SEAL.json")
    for name, expected in seal["sha256"].items():
        bind(CAMPAIGN / name, expected)
    manifest = read(CAMPAIGN / "MANIFEST.json")
    for name, expected in manifest["source_sha256"].items():
        bind(CAMPAIGN / "source_snapshot" / name, expected)
    for name in ("HELDOUT_ERROR.json", "HELDOUT_INDEPENDENT_AUDIT.json"):
        bind(CAMPAIGN / name)
    assert read(CAMPAIGN / "HELDOUT_INDEPENDENT_AUDIT.json")["status"] == "PASS"
    plan = read(CAMPAIGN / "PLAN.json")
    jobs = [j for j in plan["jobs"] if j["policy"] == "none" and j["failure"] is None]
    assert len(jobs) == 6
    for job in jobs:
        target = CAMPAIGN / "runs" / job["id"]
        marker = read(target / "COMPLETE.json")
        bind(target / "COMPLETE.json")
        assert marker["complete"] and marker["protocol_seal_sha256"] == seal_hash
        assert marker["id"] == job["id"]
        for name, expected in marker["artifacts_sha256"].items():
            bind(target / name, expected)
        workload = plan["workloads"][job["workload"]]
        bind(CAMPAIGN / workload["path"], workload["sha256"])
        assert marker["workload_sha256"] == workload["sha256"]
        assert marker["predictor_sha256"] == bind(CAMPAIGN / job["predictor"])
        assert read(target / "config.json") == job["config"]
        assert read(target / "failure.json") is None
    for model in ("Qwen3-8B", "Qwen3-32B"):
        for name in ("REPORT.json", "model.json", "oof-slack-errors.jsonl.gz"):
            bind(TRAINING / "models" / model / name)
        assert digest(TRAINING / "models" / model / "model.json") == digest(
            CAMPAIGN / "models" / f"{model}.json"
        )
    write("SOURCE_HASHES.json", sources)
    write(
        "PROTOCOL.json",
        {
            "scope": "post-hoc offline diagnostic on six completed healthy none-F0 captures",
            "sampling": "exact training reference_slack_errors, 100ms right-continuous grid",
            "prediction": "recorded prediction_ns lookup, no regressor forward or fitting",
            "guard": "unchanged deployed guard, subtract after unguarded predicted Slack",
            "reference": "healthy queue-conditioned realized durations including future finishes offline",
            "fallback": "frozen Tracker TTL and nonpositive-duration workflow fallback retained",
            "unit": "62 held-out workflows/model, maximum across all points and three loads",
            "not": "not DES, actual protection observation, counterfactual or probabilistic coverage",
            "source_hashes_sha256": digest(OUT / "SOURCE_HASHES.json"),
        },
    )
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(CAMPAIGN / "source_snapshot/python"))
    from moonkvsim.aegiskv.current.__main__ import encoded, load_workload
    from moonkvsim.aegiskv.current.model import Config
    from moonkvsim.aegiskv.current.predictor import ContextRegressor
    from moonkvsim.aegiskv.current.runtime import CurrentRuntime
    from moonkvsim.aegiskv.evaluation_walltime_predictor import reference_slack_errors

    CurrentRuntime.__init__ = forbidden
    ContextRegressor.fit = forbidden
    ContextRegressor.__call__ = forbidden

    class RecordedModel:
        def __init__(self, model, observations):
            self.training_workflows = tuple(model["regressor"]["training_workflows"])
            self.role_priors_ns = model["role_priors_ns"]
            self.predictions = {}
            for row in observations:
                key = canonical(row["raw_context"])
                value = row["prediction_ns"]
                assert key not in self.predictions or self.predictions[key] == value
                self.predictions[key] = value

        def __call__(self, context):
            return self.predictions[canonical(asdict(context))]

    def metrics(points, guard):
        raw_signed = [p["predicted_slack_ns"] - p["reference_slack_ns"] for p in points]
        guarded_signed = [
            max(0, p["predicted_slack_ns"] - guard) - p["reference_slack_ns"] for p in points
        ]
        maxima = defaultdict(int)
        for point in points:
            maxima[point["workflow"]] = max(maxima[point["workflow"]], point["overestimation_ns"])
        windows = {(p["run_id"], p["workflow"], p["time_ns"]) for p in points}
        fallback = {(p["run_id"], p["workflow"], p["time_ns"]) for p in points if p["fallback"]}
        result = {
            "unfinished_agent_control_points": len(points),
            "workflow_control_windows": len(windows),
            "fallback_workflow_control_windows": len(fallback),
            "fallback_agent_points": sum(p["fallback"] for p in points),
            "raw_signed_mean_ns": mean(raw_signed),
            "raw_positive_points": sum(x > 0 for x in raw_signed),
            "raw_positive_mean_over_all_points_ns": mean(max(0, x) for x in raw_signed),
            "raw_positive_max_ns": max(raw_signed),
            "guarded_signed_mean_ns": mean(guarded_signed),
            "guarded_positive_points": sum(x > 0 for x in guarded_signed),
            "guarded_positive_mean_over_all_points_ns": mean(max(0, x) for x in guarded_signed),
            "guarded_positive_max_ns": max(0, max(guarded_signed)),
            "workflows": len(maxima),
            "workflow_max_exceed_guard": sum(x > guard for x in maxima.values()),
            "workflow_max_at_most_guard": sum(x <= guard for x in maxima.values()),
            "workflow_max_p90_ns": quantile(maxima.values()),
        }
        return result, maxima

    reports, workflow_rows = {}, []
    for model_name in ("Qwen3-8B", "Qwen3-32B"):
        model = read(CAMPAIGN / "models" / f"{model_name}.json")
        guard = model["slack_guard_ns"]
        train_report = read(TRAINING / "models" / model_name / "REPORT.json")
        assert guard == train_report["slack_guard_ns"]
        assert guard == quantile(train_report["workflow_max_slack_overestimation_ns"].values())
        all_points, by_load = [], {}
        for job in [j for j in jobs if j["model"] == model_name]:
            target = CAMPAIGN / "runs" / job["id"]
            marker = read(target / "COMPLETE.json")
            assert hashlib.sha256(encoded(job)).hexdigest() == marker["job_sha256"]
            observations = rows(target / "errors.jsonl.gz")
            labels = rows(target / "labels.jsonl.gz")
            assert len(observations) == len(labels) == 503
            assert {r["workflow"] for r in observations} == set(plan["evaluation_workflows"])
            recorded = RecordedModel(model, observations)
            assert not set(recorded.training_workflows) & set(plan["evaluation_workflows"])
            assert all(r["invocation"] == 0 for r in observations)
            assert all(
                r["remaining_ns"] == r["agent_final_finish_ns"] - r["submitted_ns"]
                for r in observations
            )
            for label, observation in zip(labels, observations, strict=True):
                assert all(observation[key] == value for key, value in label.items())
            config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
            assert config.slack_guard_ns == guard and config.control_window_ns == 100_000_000
            agents = load_workload(CAMPAIGN / plan["workloads"][job["workload"]]["path"])
            points = reference_slack_errors(
                agents, config, labels, {w: recorded for w in plan["evaluation_workflows"]}
            )
            for point in points:
                assert point["overestimation_ns"] == max(
                    0, point["predicted_slack_ns"] - point["reference_slack_ns"]
                )
                if point["fallback"]:
                    assert point["predicted_slack_ns"] == 0
            load = str(observations[0]["nominal_load"])
            result, maxima = metrics(points, guard)
            by_load[load] = result
            for workflow, maximum in sorted(maxima.items()):
                workflow_rows.append(
                    dict(
                        model=model_name,
                        nominal_load=load,
                        workflow=workflow,
                        guard_ns=guard,
                        max_positive_overestimate_ns=maximum,
                        exceeds_guard=maximum > guard,
                    )
                )
            all_points.extend(points)
            print(job["id"], result, flush=True)
        pooled, maxima = metrics(all_points, guard)
        assert pooled["workflows"] == 62
        for workflow, maximum in sorted(maxima.items()):
            workflow_rows.append(
                dict(
                    model=model_name,
                    nominal_load="max_across_3_loads",
                    workflow=workflow,
                    guard_ns=guard,
                    max_positive_overestimate_ns=maximum,
                    exceeds_guard=maximum > guard,
                )
            )
        with (OUT / f"{model_name}-points.jsonl.gz").open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as stream:
                for point in all_points:
                    stream.write((canonical(point) + "\n").encode())
        reports[model_name] = dict(
            guard_ns=guard,
            by_load=by_load,
            grouped_across_loads=pooled,
            history_weights={str(i): model["regressor"]["weights"][i] for i in (2, 3, 5, 6, 7)},
        )
    with (OUT / "workflow-maxima.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(workflow_rows[0]))
        writer.writeheader()
        writer.writerows(workflow_rows)
    for path, expected in sources.items():
        assert digest(Path(path)) == expected, path
    write(
        "RESULTS.json",
        dict(
            status="PASS",
            models=reports,
            guard_retuned=False,
            des_run=False,
            prediction_forward_run=False,
            source_hashes_unchanged=True,
        ),
    )
    imported = {}
    for name, module in sys.modules.items():
        if name == "moonkvsim" or name.startswith("moonkvsim."):
            path = Path(module.__file__).resolve()
            assert path.is_relative_to((CAMPAIGN / "source_snapshot/python").resolve())
            imported[name] = dict(path=str(path), sha256=digest(path))
    write("IMPORTS.json", imported)
    write(
        "COMPLETE.json",
        dict(
            status="COMPLETE",
            sha256={p.name: digest(p) for p in sorted(OUT.iterdir()) if p.is_file()},
        ),
    )


if __name__ == "__main__":
    main()
