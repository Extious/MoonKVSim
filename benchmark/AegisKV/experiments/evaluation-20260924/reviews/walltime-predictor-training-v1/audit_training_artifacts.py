"""Post-run stdlib artifact audit; never imports or runs the simulator/model fitter."""

import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lines(path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def run():
    protocol = read(ROOT / "TRAINING_PROTOCOL.json")
    train = set(protocol["training_workflows"])
    excluded = set(protocol["excluded_evaluation_workflows"])
    assert len(train) == 12 and len(excluded) == 62 and not train & excluded
    for name, value in read(ROOT / "TRAINING_SEAL.json")["sha256"].items():
        assert sha(ROOT / name) == value, name
    manifest = read(ROOT / "MANIFEST.json")
    for name, value in manifest["source_sha256"].items():
        assert sha(ROOT / "source_snapshot" / name) == value, name
    complete = read(ROOT / "MODELS_COMPLETE.json")
    assert complete["training_seal_sha256"] == sha(ROOT / "TRAINING_SEAL.json")
    for name, value in complete["sha256"].items():
        assert sha(ROOT / name) == value, name
    labels = {}
    starts = []
    for job in protocol["jobs"]:
        directory = ROOT / "runs" / job["id"]
        marker = read(directory / "COMPLETE.json")
        assert marker["job"] == job and marker["captures"] == 95
        assert marker["training_seal_sha256"] == sha(ROOT / "TRAINING_SEAL.json")
        assert marker["applied_prior_model_sha256"] == hashlib.sha256(b"null").hexdigest()
        for name, value in marker["sha256"].items():
            assert sha(directory / name) == value
        start = read(directory / "RUN_START.json")
        starts.append(start["started_utc"])
        assert start["started_utc"] > read(ROOT / "TRAINING_SEAL.json")["sealed_utc"]
        for path, value in start["imports"].items():
            source = Path(path)
            assert source.is_relative_to(ROOT / "source_snapshot"), path
            relative = str(source.relative_to(ROOT / "source_snapshot"))
            assert value == manifest["source_sha256"][relative] == sha(source)
        workload = json.loads(gzip.decompress((ROOT / job["workload"]).read_bytes()))
        agents = {a["workflow"] + "/" + a["name"]: a for a in workload}
        assert {a["workflow"] for a in agents.values()} == train
        summary = read(directory / "summary.json")
        assert summary["complete"] and summary["output_tokens_exact"]
        assert summary["terminal_allocations_zero"] and summary["oracle_reservation_count"] == 0
        assert summary["failure"] is None and not summary["recoveries"]
        requests = {(r["agent"], r["invocation"]): r for r in summary["requests"]}
        contexts = {
            (r["agent"], r["invocation"]): r for r in lines(directory / "contexts.jsonl.gz")
        }
        records = lines(directory / "labels.jsonl.gz")
        assert len(records) == len(contexts) == len(requests) == 95
        for row in records:
            identity = row["agent"], row["invocation"]
            agent = agents[row["agent"]]
            call = agent["calls"][row["invocation"]]
            request, capture = requests[identity], contexts[identity]
            assert capture["raw_context"] == row["raw_context"]
            assert capture["submitted_ns"] == request["submit_ns"] == row["submitted_ns"]
            assert row["raw_context"]["text"] == call["text"]
            assert row["raw_context"]["prompt_tokens"] == len(call["prompt"])
            assert row["raw_context"]["prior_ns"] == 10**10
            assert row["raw_context"]["completed_calls"] == 0
            assert row["raw_context"]["previous_durations_ns"] == []
            assert row["raw_context"]["previous_output_tokens"] == []
            finish = max(r["finish_ns"] for r in requests.values() if r["agent"] == row["agent"])
            assert row["agent_final_finish_ns"] == finish
            assert row["remaining_ns"] == finish - request["submit_ns"]
            assert row["sample_id"] not in labels
            labels[row["sample_id"]] = row
    assert len(labels) == 570
    results = {}
    for model_dir in sorted((ROOT / "models").iterdir()):
        final, report = read(model_dir / "model.json"), read(model_dir / "REPORT.json")
        assert set(final["regressor"]["training_workflows"]) == train
        oof = lines(model_dir / "oof-errors.jsonl.gz")
        assert len(oof) == len({r["sample_id"] for r in oof}) == 285
        final_groups = {}
        for row in oof:
            for role in [row["raw_context"]["role"], "__all__"]:
                final_groups.setdefault(role, []).append(row["remaining_ns"])
        assert final["role_priors_ns"] == {
            role: round(median(values)) for role, values in final_groups.items()
        }
        for workflow in train:
            fold = read(model_dir / "folds" / (workflow + ".json"))
            assert set(fold["regressor"]["training_workflows"]) == train - {workflow}
            training_rows = [r for r in oof if r["workflow"] != workflow]
            groups = {}
            for row in training_rows:
                for role in [row["raw_context"]["role"], "__all__"]:
                    groups.setdefault(role, []).append(labels[row["sample_id"]]["remaining_ns"])
            expected_prior = {role: round(median(values)) for role, values in groups.items()}
            assert fold["role_priors_ns"] == expected_prior
            for row in (r for r in oof if r["workflow"] == workflow):
                actual = labels[row["sample_id"]]
                assert all(row[key] == value for key, value in actual.items())
                assert set(row["prior_training_workflows"]) == train - {workflow}
                derived = dict(row["raw_context"])
                derived["prior_ns"] = expected_prior.get(derived["role"], expected_prior["__all__"])
                assert row["derived_context"] == derived
                assert row["signed_error_ns"] == row["prediction_ns"] - row["remaining_ns"]
                assert row["absolute_error_ns"] == abs(row["signed_error_ns"])
        assert report["oof"]["all"]["mae_ns"] == mean(r["absolute_error_ns"] for r in oof)
        points = lines(model_dir / "oof-slack-errors.jsonl.gz")
        maxima = {w: 0 for w in train}
        for point in points:
            assert point["overestimation_ns"] == max(
                0, point["predicted_slack_ns"] - point["reference_slack_ns"]
            )
            maxima[point["workflow"]] = max(maxima[point["workflow"]], point["overestimation_ns"])
        assert maxima == report["workflow_max_slack_overestimation_ns"]
        guard = sorted(maxima.values())[math.ceil(0.9 * len(maxima)) - 1]
        assert final["slack_guard_ns"] == report["slack_guard_ns"] == guard
        results[model_dir.name] = dict(
            oof_rows=len(oof),
            workflow_folds=12,
            slack_points=len(points),
            guard_ns=guard,
            model_sha256=sha(model_dir / "model.json"),
        )
    transparency = read(ROOT / "PRIOR_TRANSPARENCY.json")
    assert transparency["status"] == "PASS" and transparency["applied_deployment_priors_verified"]
    result = dict(
        status="PASS",
        auditor_sha256=sha(Path(__file__)),
        training_seal_sha256=sha(ROOT / "TRAINING_SEAL.json"),
        models_complete_sha256=sha(ROOT / "MODELS_COMPLETE.json"),
        healthy_training_runs=6,
        validation_runs=1,
        captured_labels=len(labels),
        training_workflows=12,
        excluded_evaluation_workflows=62,
        training_started_after_freeze=True,
        frozen_import_paths_verified=True,
        model_results=results,
        future_features_found=False,
        scope="artifact identity/labels/fold priors/errors/quantile; no simulator/fitter imported",
        limitations=[
            "not independent physical data",
            "not62-workflow validation",
            "does not establish semantic encoder accuracy or system WCT improvement",
        ],
    )
    (ROOT / "INDEPENDENT_ARTIFACT_AUDIT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run()
