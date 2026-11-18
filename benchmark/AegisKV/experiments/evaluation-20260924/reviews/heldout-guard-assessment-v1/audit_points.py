"""Recompute assessment aggregates from saved points using only stdlib."""

import csv
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    results = json.loads((ROOT / "RESULTS.json").read_text())
    for name, expected in json.loads((ROOT / "COMPLETE.json").read_text())["sha256"].items():
        assert sha(ROOT / name) == expected
    for path, expected in json.loads((ROOT / "SOURCE_HASHES.json").read_text()).items():
        assert sha(Path(path)) == expected
    strata = []
    for model, report in results["models"].items():
        guard = report["guard_ns"]
        with gzip.open(ROOT / f"{model}-points.jsonl.gz", "rt") as stream:
            points = [json.loads(line) for line in stream]
        by_run = defaultdict(list)
        for point in points:
            by_run[point["run_id"]].append(point)
            assert point["time_ns"] % 100_000_000 == 0
            assert point["overestimation_ns"] == max(
                0, point["predicted_slack_ns"] - point["reference_slack_ns"]
            )
        for load, values in [("all", points)] + [
            (key.split("-load")[1].split("-none")[0], value)
            for key, value in sorted(by_run.items())
        ]:
            stored = (
                report["grouped_across_loads"] if load == "all" else report["by_load"][load]
            )
            maxima = defaultdict(int)
            for point in values:
                maxima[point["workflow"]] = max(
                    maxima[point["workflow"]], point["overestimation_ns"]
                )
            assert len(maxima) == 62
            assert sum(x > guard for x in maxima.values()) == stored["workflow_max_exceed_guard"]
            for fallback in (False, True):
                selected = [p for p in values if p["fallback"] == fallback]
                raw = [p["predicted_slack_ns"] - p["reference_slack_ns"] for p in selected]
                guarded = [
                    max(0, p["predicted_slack_ns"] - guard) - p["reference_slack_ns"]
                    for p in selected
                ]
                if fallback:
                    assert all(p["predicted_slack_ns"] == 0 for p in selected)
                strata.append(
                    dict(
                        model=model,
                        nominal_load=load,
                        fallback=fallback,
                        agent_points=len(selected),
                        workflow_windows=len({(p["run_id"], p["workflow"], p["time_ns"]) for p in selected}),
                        raw_signed_mean_ns=mean(raw),
                        raw_positive_points=sum(x > 0 for x in raw),
                        raw_positive_mean_all_points_ns=mean(max(0, x) for x in raw),
                        guarded_signed_mean_ns=mean(guarded),
                        guarded_positive_points=sum(x > 0 for x in guarded),
                        guarded_positive_mean_all_points_ns=mean(max(0, x) for x in guarded),
                        guarded_positive_max_ns=max(0, max(guarded)),
                        guarded_slack_positive_points=sum(p["predicted_slack_ns"] > guard for p in selected),
                    )
                )
            selected_strata = strata[-2:]
            assert sum(x["agent_points"] for x in selected_strata) == stored["unfinished_agent_control_points"]
            assert sum(x["raw_positive_points"] for x in selected_strata) == stored["raw_positive_points"]
            assert sum(x["guarded_positive_points"] for x in selected_strata) == stored["guarded_positive_points"]
            assert sum(x["workflow_windows"] for x in selected_strata) == stored["workflow_control_windows"]
    with (ROOT / "fallback-strata.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(strata[0]))
        writer.writeheader()
        writer.writerows(strata)
    output = dict(
        status="PASS",
        scope="stdlib aggregate arithmetic and source hash recheck; frozen Tracker semantics shared with training",
        no_des=True,
        no_model_forward=True,
        no_fitting=True,
        auditor_sha256=sha(Path(__file__)),
        fallback_strata_sha256=sha(ROOT / "fallback-strata.csv"),
        derivation_complete_sha256=sha(ROOT / "COMPLETE.json"),
    )
    (ROOT / "POINT_AUDIT.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
