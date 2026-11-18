"""Recompute finite-case error minima with sorted lower/upper-half sums."""

import csv
import gzip
import hashlib
import json
from collections import defaultdict
from fractions import Fraction
from pathlib import Path


HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lines(path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(s) for s in stream]


source = read(HERE / "SOURCE_HASHES.json")
campaign = Path(source["campaign"])
closure = dict(source["sha256"])
assert sha(HERE / "diagnose.py") == source["diagnostic_source_sha256"]
assert sha(HERE / "DIAGNOSTIC_PROTOCOL.json") == source["diagnostic_protocol_sha256"]
for relative, expected in source["sha256"].items():
    assert sha(campaign / relative) == expected, relative
plan = read(campaign / "PLAN.json")
groups, identities = defaultdict(list), defaultdict(list)
online_checked = 0
for job in plan["jobs"]:
    if not job["capture_context"]:
        continue
    folder = campaign / "runs" / job["id"]
    complete = read(folder / "COMPLETE.json")
    for relative, expected in complete["artifacts_sha256"].items():
        path = folder / relative
        assert sha(path) == expected
        closure[str(path.relative_to(campaign))] = expected
    events = [r for r in lines(folder / "events.jsonl.gz") if r["kind"] == "prediction"]
    event_map = {(r["agent"], r["invocation"], r["submitted_ns"]): r for r in events}
    assert len(events) == len(event_map) == 503
    for row in lines(folder / "errors.jsonl.gz"):
        key = row["agent"], row["invocation"], row["submitted_ns"]
        assert event_map[key]["accepted"]
        assert event_map[key]["remaining_ns"] == row["prediction_ns"]
        online_checked += 1
        assert row["raw_context"] == row["derived_context"]
        # Key on complete canonical Context content, never on identity or load.
        context = json.dumps(
            row["derived_context"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        groups[context].append(row)
        identities[job["model"], row["agent"], row["invocation"]].append((context, row))
details = {r["context_sha256"]: r for r in lines(HERE / "context-groups.jsonl.gz")}
assert len(details) == len(groups)
totals = defaultdict(
    lambda: dict(n=0, minimum=0, actual=0, baseline=0, groups=0, varying=0, cross_agent=0)
)
for context, members in groups.items():
    labels = sorted(row["remaining_ns"] for row in members)
    half = len(labels) // 2
    # For odd n the central item is omitted; for even n the median interval is
    # unrestricted. This avoids using the generator's median/Fraction residuals.
    optimal_sum = sum(labels[len(labels) - half :]) - sum(labels[:half])
    actual = sum(abs(row["prediction_ns"] - row["remaining_ns"]) for row in members)
    baseline = sum(abs(row["derived_context"]["prior_ns"] - row["remaining_ns"]) for row in members)
    assert len({r["prediction_ns"] for r in members}) == 1
    assert optimal_sum <= actual and optimal_sum <= baseline
    record = details[hashlib.sha256(context).hexdigest()]
    assert record["derived_context"] == json.loads(context)
    assert record["minimum_sum_absolute_error_ns"] == optimal_sum
    assert record["actual_sum_absolute_error_ns"] == actual
    assert record["baseline_sum_absolute_error_ns"] == baseline
    assert sorted((r["sample_id"], r["remaining_ns"]) for r in members) == sorted(
        (r["sample_id"], r["label_ns"]) for r in record["members"]
    )
    model = record["model"]
    total = totals[model]
    total["n"] += len(labels)
    total["minimum"] += optimal_sum
    total["actual"] += actual
    total["baseline"] += baseline
    total["groups"] += 1
    total["varying"] += len(set(labels)) > 1
    total["cross_agent"] += len({r["agent"] for r in members}) > 1
results = read(HERE / "RESULTS.json")
for model, total in totals.items():
    result = results["models"][model]
    assert result["observations"] == total["n"]
    assert result["context_groups"] == total["groups"]
    assert result["cross_agent_context_groups"] == total["cross_agent"]
    assert result["same_context_different_label_groups"] == total["varying"]
    for field, key in [
        ("minimum_empirical_context_only_mae", "minimum"),
        ("actual_model_mae", "actual"),
        ("role_median_mae", "baseline"),
    ]:
        fraction = Fraction(total[key], total["n"])
        assert result[field]["sum_absolute_error_ns"] == total[key]
        assert result[field]["mae_ns_numerator"] == fraction.numerator
        assert result[field]["mae_ns_denominator"] == fraction.denominator
for (model, agent, invocation), items in identities.items():
    assert len(items) == 3 and {r["nominal_load"] for _, r in items} == {0.3, 0.65, 0.9}
    assert len({ctx for ctx, _ in items}) == 1
    assert len({r["prediction_ns"] for _, r in items}) == 1
with (HERE / "observations.csv").open() as stream:
    exported = list(csv.DictReader(stream))
assert len(exported) == online_checked == 3018
assert len({r["sample_id"] for r in exported}) == 3018
report = dict(
    status="PASS",
    online_event_predictions_verified=online_checked,
    unique_model_agent_invocation_identities=len(identities),
    canonical_context_groups=len(groups),
    independent_arithmetic="sum upper half minus sum lower half of each sorted label group",
    model_integer_totals=dict(totals),
    source_artifact_closure_sha256=closure,
    diagnostic_output_sha256={
        name: sha(HERE / name)
        for name in (
            "RESULTS.json",
            "DIAGNOSTIC_PROTOCOL.json",
            "SOURCE_HASHES.json",
            "context-groups.jsonl.gz",
            "observations.csv",
            "identity-load-consistency.csv",
            "diagnose.py",
        )
    },
    auditor_sha256=sha(Path(__file__)),
    limitation="finite-test-case diagnostic using test outcomes; no deployment, tuning, population or future lower-bound interpretation",
)
(HERE / "INDEPENDENT_AUDIT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
print(json.dumps(dict(status="PASS", model_integer_totals=dict(totals)), indent=2))
