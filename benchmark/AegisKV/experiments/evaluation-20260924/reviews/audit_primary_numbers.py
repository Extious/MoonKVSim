#!/usr/bin/env python3
"""Recompute primary plot numbers from integer-nanosecond summaries.

Does not import the plotter or its upstream auditor. Writes only independent
audit products after the complete plot provenance exists.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from fractions import Fraction
from pathlib import Path
from statistics import mean


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def rows(path):
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


def average_ns(values):
    values = list(values)
    return float(Fraction(sum(values), len(values) * 1_000_000_000))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    args = parser.parse_args()
    root = args.campaign.resolve()
    out = root / "figures"
    provenance = read(out / "PROVENANCE.json")
    for source, expected in provenance["source_sha256"].items():
        assert digest(Path(source)) == expected, source
    for name, expected in provenance["outputs_sha256"].items():
        assert digest(out / name) == expected, name
    assert read(root / "AUDIT.json")["status"] == "PASS"
    plan = read(root / "PLAN.json")
    jobs = {row["id"]: row for row in plan["jobs"]}
    assert len(jobs) == 180
    summaries, summary_hashes = {}, {}
    for key, job in jobs.items():
        path = root / "runs" / key
        marker = read(path / "COMPLETE.json")
        assert marker["summary_sha256"] == digest(path / "summary.json"), key
        summary = read(path / "summary.json")
        assert summary["complete"] and summary["terminal_allocations_zero"]
        assert summary["output_tokens_exact"]  # replay count, not numerical model identity
        assert set(summary["workflows"]) == set(plan["evaluation_workflows"])
        assert len(summary["workflows"]) == 62
        assert summary["policy"] == job["policy"]
        for workflow in summary["workflows"].values():
            assert workflow["wct_ns"] == workflow["finish_ns"] - workflow["start_ns"]
        if job["failure"]:
            assert all(
                summary["failure"][field] == job["failure"][field]
                for field in ("agent", "invocation")
            )
        summaries[key] = summary
        summary_hashes[key] = marker["summary_sha256"]
    run_rows = rows(root / "run-metrics.csv")
    indexed_runs = {row["run_id"]: row for row in run_rows}
    assert len(indexed_runs) == len(run_rows) == 180
    assert set(indexed_runs) == set(jobs)
    errors, numeric_checks = {}, Counter()

    def close(actual, expected, scope, *, milliseconds=False):
        actual = float(actual)
        error = abs(actual - expected)
        errors[scope] = max(errors.get(scope, 0), error)
        # The CSV producer subtracts second-valued floats. The independent
        # reference subtracts integer ns before converting to seconds.
        tolerance = 2e-8 if milliseconds else 2e-10
        assert math.isfinite(actual) and math.isclose(
            actual, expected, rel_tol=2e-13, abs_tol=tolerance
        ), (scope, actual, expected, error)
        numeric_checks[scope] += 1

    independent, expected_pairs = {}, {}
    for key, summary in summaries.items():
        job, row = jobs[key], indexed_runs[key]
        assert row["run_integrity_verified"] == "True"
        values = [w["wct_ns"] for w in summary["workflows"].values()]
        derived = dict(wct_mean_s=average_ns(values))
        if job["failure"]:
            baseline = summaries[job["f0_id"]]
            assert all(
                baseline[field] == summary[field]
                for field in ("config_sha256", "workload_sha256", "policy")
            )
            target = summary["failure"]["agent"].split("/", 1)[0]
            victims = {r["agent"].split("/", 1)[0] for r in summary["recoveries"]}
            deltas = []
            for workflow, failed in summary["workflows"].items():
                healthy = baseline["workflows"][workflow]
                delta = failed["wct_ns"] - healthy["wct_ns"]
                deltas.append(delta)
                expected_pairs[key, workflow] = dict(
                    f0_id=job["f0_id"],
                    f0_wct_s=healthy["wct_ns"] / 1e9,
                    f1_wct_s=failed["wct_ns"] / 1e9,
                    delta_wct_s=delta / 1e9,
                    workflow_role="primary_fault"
                    if workflow == target
                    else ("co_victim" if workflow in victims else "collateral"),
                )
            derived.update(
                delta_wct_mean_s=average_ns(deltas),
                fault_workflow_wct_s=summary["workflows"][target]["wct_ns"] / 1e9,
                fault_workflow_delta_s=(
                    summary["workflows"][target]["wct_ns"] - baseline["workflows"][target]["wct_ns"]
                )
                / 1e9,
                recovery_service_mean_s=average_ns(r["service_ns"] for r in summary["recoveries"]),
                recovery_queue_mean_s=average_ns(r["queue_ns"] for r in summary["recoveries"]),
            )
        for field, expected in derived.items():
            close(row[field], expected, "run_metrics")
        independent[key] = derived
    paired = rows(root / "paired-workflows.csv")
    assert len(paired) == len(expected_pairs) == 9300
    seen = set()
    for row in paired:
        key = row["run_id"], row["workflow"]
        assert key not in seen
        seen.add(key)
        reference = expected_pairs[key]
        job = jobs[row["run_id"]]
        for field in ("model", "policy", "workload"):
            assert row[field] == job[field]
        assert int(row["fault_index"]) == job["fault_index"]
        for field, expected in reference.items():
            if field in {"f0_id", "workflow_role"}:
                assert row[field] == expected
            else:
                close(row[field], expected, "workflow_pairs")
    models, loads = ("Qwen3-8B", "Qwen3-32B"), (0.3, 0.65, 0.9)
    policies = ("none", "all_dram", "dram", "static_hbm", "aegiskv")
    expected_figures, cells, hbm_pairs, equivalents = {}, [], [], []
    for model in models:
        for load in loads:
            prefix = f"{model}-load{load}"
            cell = dict(model=model, nominal_load=load, policies={})
            for policy in policies:
                healthy_id = f"{prefix}-{policy}-F0"
                failures = [f"{prefix}-{policy}-F1-{i}" for i in range(5)]
                healthy = summaries[healthy_id]
                numbers = dict(
                    healthy_mean_wct_s=independent[healthy_id]["wct_mean_s"],
                    failure_mean_wct_s=mean(independent[k]["wct_mean_s"] for k in failures),
                    failure_mean_delta_wct_s=mean(
                        independent[k]["delta_wct_mean_s"] for k in failures
                    ),
                    target_mean_wct_s=mean(
                        independent[k]["fault_workflow_wct_s"] for k in failures
                    ),
                    target_mean_delta_wct_s=mean(
                        independent[k]["fault_workflow_delta_s"] for k in failures
                    ),
                    recovery_service_mean_s=mean(
                        independent[k]["recovery_service_mean_s"] for k in failures
                    ),
                    recovery_queue_mean_s=mean(
                        independent[k]["recovery_queue_mean_s"] for k in failures
                    ),
                    healthy_checkpoint_bytes=healthy["metrics"].get("checkpoint_bytes", 0),
                    healthy_hot_bytes=healthy["metrics"].get("hot_bytes", 0),
                )
                numbers["delta_range_s"] = [
                    min(independent[k]["delta_wct_mean_s"] for k in failures),
                    max(independent[k]["delta_wct_mean_s"] for k in failures),
                ]
                cell["policies"][policy] = numbers
                for i, key in enumerate(failures):
                    expected_figures["core-workflow-delay", model, load, policy, i] = independent[
                        key
                    ]["delta_wct_mean_s"]
            for i in range(5):
                left_id, right_id = f"{prefix}-dram-F1-{i}", f"{prefix}-aegiskv-F1-{i}"
                left, right = summaries[left_id], summaries[right_id]
                for field in ("agent", "invocation", "logical_tokens", "total_tokens"):
                    assert left["failure"][field] == right["failure"][field]
                target = left["failure"]["agent"].split("/", 1)[0]
                benefit_ns = (
                    left["workflows"][target]["wct_ns"] - right["workflows"][target]["wct_ns"]
                )
                healthy_equal = (
                    summaries[f"{prefix}-dram-F0"]["workflows"][target]
                    == summaries[f"{prefix}-aegiskv-F0"]["workflows"][target]
                )
                assert healthy_equal
                expected_figures["core-hbm-increment", model, load, "dram-minus-aegiskv", i] = (
                    benefit_ns / 1e6
                )
                hbm_pairs.append(
                    dict(
                        model=model,
                        load=load,
                        fault_index=i,
                        target=target,
                        agent=left["failure"]["agent"],
                        logical_tokens=left["failure"]["logical_tokens"],
                        benefit_ns=benefit_ns,
                        benefit_ms=benefit_ns / 1e6,
                        own_F0_target_workflow_identical=healthy_equal,
                        actual_failure_time_equal=left["failure"]["time_ns"]
                        == right["failure"]["time_ns"],
                        failed_workers_equal=left["failure"]["workers"]
                        == right["failure"]["workers"],
                    )
                )
            cells.append(cell)
            for a, b in (("all_dram", "dram"), ("static_hbm", "aegiskv")):
                exceptions, checked, metrics_differ = [], 0, 0
                for suffix in ["F0", *[f"F1-{i}" for i in range(5)]]:
                    left, right = (
                        summaries[f"{prefix}-{a}-{suffix}"],
                        summaries[f"{prefix}-{b}-{suffix}"],
                    )
                    metrics_differ += left["metrics"] != right["metrics"]
                    for workflow in plan["evaluation_workflows"]:
                        checked += 1
                        if left["workflows"][workflow] != right["workflows"][workflow]:
                            exceptions.append(
                                dict(
                                    phase=suffix,
                                    workflow=workflow,
                                    left=left["workflows"][workflow],
                                    right=right["workflows"][workflow],
                                )
                            )
                equivalents.append(
                    dict(
                        model=model,
                        load=load,
                        comparison=f"{a}-vs-{b}",
                        workflow_pairs=checked,
                        all_start_finish_wct_identical=not exceptions,
                        exceptions=exceptions,
                        run_pairs_with_different_metrics=metrics_differ,
                    )
                )
    figure_rows = rows(out / "figure-data.csv")
    assert len(figure_rows) == len(expected_figures) == 180
    seen = set()
    for row in figure_rows:
        key = (
            row["figure"],
            row["model"],
            float(row["load"]),
            row["policy"],
            int(row["fault_index"]),
        )
        assert key not in seen
        seen.add(key)
        is_hbm = row["figure"] == "core-hbm-increment"
        assert row["unit"] == ("ms" if is_hbm else "s")
        close(
            row["value"],
            expected_figures[key],
            "figure_HBM" if is_hbm else "figure_delta",
            milliseconds=is_hbm,
        )
    results = read(out / "RESULTS.json")
    assert len(results) == 6
    lookup = {(row["model"], row["nominal_load"]): row for row in cells}
    assert {(row["model"], row["nominal_load"]) for row in results} == set(lookup)
    for result in results:
        expected = lookup[result["model"], result["nominal_load"]]
        assert set(result["policies"]) == set(policies)
        for policy, values in result["policies"].items():
            assert set(values) == set(expected["policies"][policy]) - {"delta_range_s"}
            for key, number in values.items():
                close(number, expected["policies"][policy][key], "six_group_headlines")
    negatives = dict(
        paired_workflow_deltas=sum(r["delta_wct_s"] < 0 for r in expected_pairs.values()),
        plotted_scenario_mean_deltas=sum(
            v < 0 for k, v in expected_figures.items() if k[0] == "core-workflow-delay"
        ),
        plotted_HBM_benefits=sum(r["benefit_ns"] < 0 for r in hbm_pairs),
    )
    source_paths = [
        root / n for n in ("PLAN.json", "AUDIT.json", "paired-workflows.csv", "run-metrics.csv")
    ]
    source_paths += [out / n for n in ("PROVENANCE.json", "RESULTS.json", "figure-data.csv")]
    report = dict(
        status="PASS",
        scope="numeric/statistical audit only; visual review belongs to root",
        script_sha256=digest(Path(__file__)),
        source_sha256={str(p): digest(p) for p in source_paths},
        summary_sha256=summary_hashes,
        runs=180,
        workflows_per_run=62,
        paired_workflow_rows=9300,
        plotted_numbers=180,
        scenario_mean_numbers=150,
        same_ID_HBM_numbers=30,
        headline_cells=6,
        policies_per_cell=5,
        numeric_comparisons=dict(numeric_checks),
        max_absolute_floating_errors=errors,
        negative_results_retained=negatives,
        aggregation=(
            "62 own-F0 paired workflow deltas per scenario; "
            "mean and min/max over five fixed identities, not CI"
        ),
        hbm_statistic=(
            "same-ID target workflow DRAM-F1 minus AegisKV-F1; own target F0s verified identical"
        ),
        statistical_units=(
            "five fixed failure scenarios per condition; dependent workflows; "
            "180 plotted numbers are not independent replicates"
        ),
        controls=equivalents,
        independently_derived_cells=cells,
        same_ID_HBM_pairs=hbm_pairs,
    )
    lines = [
        "# Independent primary-figure numeric audit",
        "",
        "PASS: all 180 summaries, 9,300 same-ID workflow pairs, 180 plotted numbers "
        "(150 scenario means + 30 HBM differences), and all six model/load headline cells "
        "were independently recomputed.",
        "",
        "The reference subtracts integer nanoseconds before converting units; "
        "it does not import the plotter or upstream auditor. Source and summary hashes, "
        "every control exception, group means/ranges and the 30 HBM pairs "
        "are retained in the JSON.",
        "",
        "Each workflow-delay value first averages 62 own-policy F1-F0 workflow pairs. "
        "The figure then shows the mean and min/max across five fixed fault identities, not a CI. "
        "The HBM figure uses target-workflow DRAM F1-AegisKV F1; "
        "all corresponding target F0 records are identical.",
        "",
        f"Negative values retained: {negatives['paired_workflow_deltas']} workflow pairs, "
        f"{negatives['plotted_scenario_mean_deltas']} plotted scenario means, "
        f"{negatives['plotted_HBM_benefits']} HBM target differences.",
        "",
        "| Model | Load | All-DRAM / DRAM exceptions | Static-HBM / AegisKV exceptions |",
        "|---|---:|---:|---:|",
    ]
    for model in models:
        for load in loads:
            controls = [c for c in equivalents if c["model"] == model and c["load"] == load]
            lines.append(
                f"| {model} | {load} | {len(controls[0]['exceptions'])} / 372 "
                f"| {len(controls[1]['exceptions'])} / 372 |"
            )
    for control in equivalents:
        for exception in control["exceptions"]:
            difference = exception["left"]["wct_ns"] - exception["right"]["wct_ns"]
            lines.append(
                f"\nException: {control['model']}, load {control['load']}, "
                f"{control['comparison']}, {exception['phase']}, workflow "
                f"`{exception['workflow']}`: left-minus-right WCT = {difference / 1e9:.9f} s."
            )
    lines += [
        "",
        "Six condition means (seconds; full precision remains in the JSON):",
        "",
        "| Model | Load | Healthy mean, all policies | Restart delta | "
        "All-DRAM / DRAM delta | Static-HBM / AegisKV delta |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for cell in cells:
        values = cell["policies"]
        assert len({v["healthy_mean_wct_s"] for v in values.values()}) == 1
        assert (
            values["all_dram"]["failure_mean_delta_wct_s"]
            == values["dram"]["failure_mean_delta_wct_s"]
        )
        assert (
            values["static_hbm"]["failure_mean_delta_wct_s"]
            == values["aegiskv"]["failure_mean_delta_wct_s"]
        )
        lines.append(
            f"| {cell['model']} | {cell['nominal_load']} "
            f"| {values['none']['healthy_mean_wct_s']:.9f} "
            f"| {values['none']['failure_mean_delta_wct_s']:.9f} "
            f"| {values['dram']['failure_mean_delta_wct_s']:.9f} "
            f"| {values['aegiskv']['failure_mean_delta_wct_s']:.9f} |"
        )
    lines += [
        "",
        "Each comparison checks all 62 workflows in F0 and five F1 runs, "
        "including start, finish and WCT. "
        "Equality of completion records does not imply equal traffic or measured zero overhead. "
        "All exceptions, if present, are listed with original records in the JSON.",
        "",
        "This is CPU simulation-data validation. It does not validate numerical model outputs, "
        "hardware accuracy or visual layout.",
        "",
    ]
    (out / "INDEPENDENT_NUMERIC_AUDIT.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    (out / "INDEPENDENT_NUMERIC_AUDIT.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {"status": "PASS", "numeric_checks": dict(numeric_checks), "negatives": negatives}
        )
    )


if __name__ == "__main__":
    main()
