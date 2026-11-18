"""Finite-case Context-only absolute-error minimum; no predictor import or fit."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def lines(path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def csv_file(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def rate(total, count):
    exact = Fraction(total, count)
    return dict(
        sum_absolute_error_ns=total,
        observations=count,
        mae_ns_numerator=exact.numerator,
        mae_ns_denominator=exact.denominator,
        mae_seconds=float(exact / 10**9),
    )


def diagnose(campaign, out):
    if (out / "RESULTS.json").exists():
        raise FileExistsError("diagnostic output already exists")
    plan = read(campaign / "PLAN.json")
    protocol = dict(
        operation="group all six healthy actual contexts by canonical derived-Context bytes",
        features="full serialized derived Context including model; Agent/load/Workflow identity not added",
        objective="unweighted per-observation MAE across all three tested loads, separately per model",
        minimum="each group's observed labels use their exact rational median; sum absolute residuals/N",
        interpretation="minimum empirical MAE on this finite case-set for an arbitrary deterministic full-Context-only mapping",
        constraints="diagnostic uses heldout outcomes offline; not deployable, not tuning, not population/future lower bound; not a bound for one particular regressor class",
        dependencies="same62workflows at3loads/model;503Agenttasks per load; shared queues; no independent-repeat claim",
        expected_conditions=6,
        expected_rows=3018,
        source=str(campaign.resolve()),
    )
    write(out / "DIAGNOSTIC_PROTOCOL.json", protocol)
    source_names = {
        "PLAN.json",
        "MANIFEST.json",
        "PROTOCOL.json",
        "PROTOCOL_SEAL.json",
        "HELDOUT_ERROR.json",
        "HELDOUT_INDEPENDENT_AUDIT.json",
    }
    rows, bindings, event_checks = [], {}, []
    for job in [j for j in plan["jobs"] if j["capture_context"]]:
        folder = campaign / "runs" / job["id"]
        source_names.add(job["predictor"])
        for name in (
            "COMPLETE.json",
            "RUN_START.json",
            "contexts.jsonl.gz",
            "labels.jsonl.gz",
            "errors.jsonl.gz",
            "events.jsonl.gz",
            "summary.json",
            "config.json",
            "failure.json",
        ):
            source_names.add(str((folder / name).relative_to(campaign)))
        complete = read(folder / "COMPLETE.json")
        for relative, expected in complete["artifacts_sha256"].items():
            assert sha(folder / relative) == expected
        contexts = lines(folder / "contexts.jsonl.gz")
        labels, errors = lines(folder / "labels.jsonl.gz"), lines(folder / "errors.jsonl.gz")
        predictions = {
            (event["agent"], event["invocation"], event["submitted_ns"]): event
            for event in lines(folder / "events.jsonl.gz")
            if event["kind"] == "prediction"
        }
        assert len(contexts) == len(labels) == len(errors) == len(predictions) == 503
        for captured, label, error in zip(contexts, labels, errors, strict=True):
            key = error["agent"], error["invocation"], error["submitted_ns"]
            event = predictions[key]
            assert event["accepted"] and error["prediction_ns"] == event["remaining_ns"]
            assert captured["raw_context"] == error["raw_context"] == error["derived_context"]
            assert label["remaining_ns"] == error["remaining_ns"]
            assert error["remaining_ns"] == error["agent_final_finish_ns"] - error["submitted_ns"]
            assert error["absolute_error_ns"] == abs(error["prediction_ns"] - error["remaining_ns"])
            assert error["baseline_absolute_error_ns"] == abs(
                error["role_median_baseline_ns"] - error["remaining_ns"]
            )
            rows.append(
                {
                    **error,
                    "short_model": job["model"],
                    "online_prediction_ns": event["remaining_ns"],
                }
            )
        event_checks.append(
            dict(
                run=job["id"],
                observed_predictions=len(predictions),
                all_accepted=True,
                saved_error_prediction_equals_online_event=True,
            )
        )
    for name in sorted(source_names):
        bindings[name] = sha(campaign / name)
    assert len(rows) == 3018
    by_identity = defaultdict(list)
    groups = defaultdict(list)
    for row in rows:
        by_identity[row["short_model"], row["agent"], row["invocation"]].append(row)
        groups[canonical(row["derived_context"])].append(row)
    identity_rows = []
    for (model, agent, invocation), members in sorted(by_identity.items()):
        members.sort(key=lambda r: r["nominal_load"])
        assert [r["nominal_load"] for r in members] == [0.3, 0.65, 0.9]
        keys = {canonical(r["derived_context"]) for r in members}
        differing = [
            field
            for field in members[0]["derived_context"]
            if len({canonical(r["derived_context"][field]) for r in members}) > 1
        ]
        identity_rows.append(
            dict(
                model=model,
                agent=agent,
                invocation=invocation,
                identical_context_all_loads=len(keys) == 1,
                distinct_contexts=len(keys),
                differing_fields=json.dumps(differing),
                identical_online_prediction_all_loads=len(
                    {r["online_prediction_ns"] for r in members}
                )
                == 1,
                online_predictions_ns=json.dumps([r["online_prediction_ns"] for r in members]),
                labels_ns=json.dumps([r["remaining_ns"] for r in members]),
            )
        )
    details, model_groups = [], defaultdict(list)
    observation_rows = []
    for context_bytes, members in sorted(groups.items()):
        models = {r["short_model"] for r in members}
        assert len(models) == 1
        model = models.pop()
        values = sorted(r["remaining_ns"] for r in members)
        lower, upper = values[(len(values) - 1) // 2], values[len(values) // 2]
        median = Fraction(lower + upper, 2)
        optimum = sum((abs(Fraction(v) - median) for v in values), Fraction())
        assert optimum.denominator == 1
        predictions = {r["online_prediction_ns"] for r in members}
        baselines = {r["role_median_baseline_ns"] for r in members}
        assert len(predictions) == len(baselines) == 1
        detail = dict(
            context_sha256=hashlib.sha256(context_bytes).hexdigest(),
            model=model,
            derived_context=json.loads(context_bytes),
            observations=len(members),
            distinct_agents=len({r["agent"] for r in members}),
            distinct_workflows=len({r["workflow"] for r in members}),
            loads=sorted({r["nominal_load"] for r in members}),
            members=[
                dict(
                    sample_id=r["sample_id"],
                    agent=r["agent"],
                    workflow=r["workflow"],
                    load=r["nominal_load"],
                    label_ns=r["remaining_ns"],
                    online_prediction_ns=r["online_prediction_ns"],
                    baseline_ns=r["role_median_baseline_ns"],
                )
                for r in sorted(members, key=lambda r: r["sample_id"])
            ],
            median_lower_ns=lower,
            median_upper_ns=upper,
            offline_median_ns_numerator=median.numerator,
            offline_median_ns_denominator=median.denominator,
            minimum_sum_absolute_error_ns=optimum.numerator,
            actual_sum_absolute_error_ns=sum(r["absolute_error_ns"] for r in members),
            baseline_sum_absolute_error_ns=sum(r["baseline_absolute_error_ns"] for r in members),
            distinct_labels=len(set(values)),
            label_min_ns=min(values),
            label_max_ns=max(values),
        )
        details.append(detail)
        model_groups[model].append(detail)
        for member in detail["members"]:
            observation_rows.append(
                dict(model=model, context_sha256=detail["context_sha256"], **member)
            )
    summaries = {}
    heldout = read(campaign / "HELDOUT_ERROR.json")
    for model, records in sorted(model_groups.items()):
        n = sum(r["observations"] for r in records)
        optimum = sum(r["minimum_sum_absolute_error_ns"] for r in records)
        actual = sum(r["actual_sum_absolute_error_ns"] for r in records)
        baseline = sum(r["baseline_sum_absolute_error_ns"] for r in records)
        identities = [r for r in identity_rows if r["model"] == model]
        assert actual / n == heldout["models"][model]["all"]["mae_ns"]
        assert baseline / n == heldout["models"][model]["all"]["role_median_mae_ns"]
        assert optimum <= actual and optimum <= baseline
        summaries[model] = dict(
            observations=n,
            workflows=62,
            agent_identities=len(identities),
            context_groups=len(records),
            repeated_context_groups=sum(r["observations"] > 1 for r in records),
            cross_agent_context_groups=sum(r["distinct_agents"] > 1 for r in records),
            context_group_size_histogram=dict(
                sorted(Counter(r["observations"] for r in records).items())
            ),
            same_context_different_label_groups=sum(r["distinct_labels"] > 1 for r in records),
            identity_context_equal_all_loads=sum(
                r["identical_context_all_loads"] for r in identities
            ),
            identity_prediction_equal_all_loads=sum(
                r["identical_online_prediction_all_loads"] for r in identities
            ),
            minimum_empirical_context_only_mae=rate(optimum, n),
            actual_model_mae=rate(actual, n),
            role_median_mae=rate(baseline, n),
            model_error_above_empirical_minimum=rate(actual - optimum, n),
        )
    csv_file(out / "identity-load-consistency.csv", identity_rows)
    csv_file(out / "observations.csv", observation_rows)
    payload = b"".join(canonical(r) + b"\n" for r in details)
    (out / "context-groups.jsonl.gz").write_bytes(gzip.compress(payload, mtime=0))
    result = dict(
        status="PASS",
        models=summaries,
        actual_online_prediction_checks=event_checks,
        interpretation=protocol["interpretation"],
        limitations=protocol["constraints"],
        dependence=protocol["dependencies"],
        canonical_encoding="UTF-8 JSON; sorted keys; compact separators; ensure_ascii=False; allow_nan=False; arrays retain order",
    )
    write(out / "RESULTS.json", result)
    write(
        out / "SOURCE_HASHES.json",
        dict(
            campaign=str(campaign.resolve()),
            sha256=bindings,
            diagnostic_source_sha256=sha(Path(__file__)),
            diagnostic_protocol_sha256=sha(out / "DIAGNOSTIC_PROTOCOL.json"),
        ),
    )
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    diagnose(args.campaign.resolve(), args.out.resolve())
