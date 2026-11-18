#!/usr/bin/env python3
"""Read-only, version-bound O1/fallback and DMA sensitivity evidence audit.

Accepts campaign directories, never imports their runtime or executes DES.
Detailed fallback reconstruction requires the single-invocation workload in
these campaigns and checks every reconstructed Slack against recorded samples.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import deque
from math import isfinite
from pathlib import Path
from statistics import mean


class Evidence:
    def __init__(self):
        self.hashes = {}

    def bytes(self, path):
        path = Path(path).resolve()
        data = path.read_bytes()
        self.hashes[str(path)] = hashlib.sha256(data).hexdigest()
        return data

    def read(self, path):
        return json.loads(self.bytes(path))

    def sha(self, path):
        self.bytes(path)
        return self.hashes[str(Path(path).resolve())]


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n"
    ).encode()


def value_sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def write_csv(path, rows):
    if not rows:
        path.write_text("")
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def campaign(evidence, base):
    plan = evidence.read(base / "PLAN.json")
    manifest = evidence.read(base / "MANIFEST.json")
    for name, digest in manifest.get("control_sha256", {}).items():
        assert evidence.sha(base / name) == digest
    for relative, digest in manifest["source_sha256"].items():
        if relative.endswith(
            ("current/runtime.py", "current/tracker.py", "evaluation_campaign.py")
        ):
            assert evidence.sha(base / "source_snapshot" / relative) == digest
    runs = {}
    for job in plan["jobs"]:
        directory = base / "runs" / job["id"]
        marker = evidence.read(directory / "COMPLETE.json")
        summary = evidence.read(directory / "summary.json")
        assert marker["id"] == job["id"] and marker["job_sha256"] == value_sha(job)
        expected_summary = marker.get(
            "summary_sha256", marker.get("artifact_sha256", {}).get("summary.json")
        )
        assert expected_summary == evidence.sha(directory / "summary.json")
        config = evidence.read(directory / "config.json")
        assert config == job["config"]
        assert summary["config_sha256"] == value_sha(config)
        assert summary["complete"] is True and summary["policy"] == job["policy"]
        assert summary["duration_profile"] == "GridDurationProfile"
        workload = plan["workload"] if "workload" in plan else plan["workloads"][job["workload"]]
        assert summary["workload_sha256"] == workload["content_sha256"]
        assert evidence.sha(base / workload["path"]) == workload["sha256"]
        assert (
            summary["failure"] is None if job["failure"] is None else summary["failure"] is not None
        )
        assert all(
            w["finish_ns"] - w["start_ns"] == w["wct_ns"] for w in summary["workflows"].values()
        )
        profile = (
            base / plan["profile"]
            if "profile" in plan
            else base / "profiles" / f"{job['model']}.json"
        )
        assert evidence.sha(profile) == marker["profile_sha256"]
        assert evidence.sha(base / "PRIORS.json") == marker["priors_sha256"]
        runs[job["id"]] = (job, summary)
    return plan, manifest, runs


def backup(summary):
    metrics = summary["metrics"]
    return {
        name: metrics.get(name, 0)
        for name in ("checkpoint_bytes", "hot_bytes", "canceled_copy_transferred_bytes")
    }


def primary_rows(runs):
    healthy, pairs = [], []
    for job, summary in runs.values():
        if job["failure"] is not None:
            continue
        row = dict(
            run_id=job["id"], model=job["model"], workload=job["workload"], policy=job["policy"]
        )
        row.update(backup(summary))
        row.update(
            backup_transferred_bytes=sum(backup(summary).values()),
            fallback_rebalance_workflow_observations=summary["metrics"].get(
                "slack_fallback_observations", 0
            ),
            workflow_count=len(summary["workflows"]),
            wct_mean_s=mean(w["wct_ns"] for w in summary["workflows"].values()) / 1e9,
        )
        healthy.append(row)
    comparisons = []
    for row in healthy:
        if row["policy"] != "dram":
            continue
        other = next(
            r for r in healthy if r["workload"] == row["workload"] and r["policy"] == "all_dram"
        )
        comparisons.append(
            dict(
                model=row["model"],
                workload=row["workload"],
                dram_fallback_observations=row["fallback_rebalance_workflow_observations"],
                all_dram_fallback_observations=other["fallback_rebalance_workflow_observations"],
                dram_completed_checkpoint_bytes=row["checkpoint_bytes"],
                all_dram_completed_checkpoint_bytes=other["checkpoint_bytes"],
                completed_checkpoint_saving_pct=100
                * (1 - row["checkpoint_bytes"] / other["checkpoint_bytes"]),
                dram_canceled_transferred_bytes=row["canceled_copy_transferred_bytes"],
                all_dram_canceled_transferred_bytes=other["canceled_copy_transferred_bytes"],
                dram_total_backup_bytes=row["backup_transferred_bytes"],
                all_dram_total_backup_bytes=other["backup_transferred_bytes"],
                all_transferred_backup_saving_pct=100
                * (1 - row["backup_transferred_bytes"] / other["backup_transferred_bytes"]),
                dram_healthy_mean_wct_s=row["wct_mean_s"],
                all_dram_healthy_mean_wct_s=other["wct_mean_s"],
            )
        )
    for job, summary in runs.values():
        if job["policy"] != "dram":
            continue
        other_job, other = next(
            (j, s)
            for j, s in runs.values()
            if j["policy"] == "all_dram"
            and j["workload"] == job["workload"]
            and j["fault_index"] == job["fault_index"]
        )
        assert other_job["config"] == job["config"] and other_job["failure"] == job["failure"]
        assert summary["workflows"].keys() == other["workflows"].keys()
        target = summary["failure"]["agent"].split("/", 1)[0] if summary["failure"] else None
        for workflow, record in summary["workflows"].items():
            pairs.append(
                dict(
                    model=job["model"],
                    workload=job["workload"],
                    fault_index=job["fault_index"],
                    workflow=workflow,
                    is_target=workflow == target,
                    dram_wct_ns=record["wct_ns"],
                    all_dram_wct_ns=other["workflows"][workflow]["wct_ns"],
                    all_dram_minus_dram_ns=other["workflows"][workflow]["wct_ns"]
                    - record["wct_ns"],
                )
            )
    return healthy, comparisons, pairs


def fallback_samples(evidence, base, plan, runs):
    aggregates, samples = [], []
    for job, summary in runs.values():
        if not summary.get("detailed_event_and_flow_logs_retained"):
            continue
        workload = plan["workloads"][job["workload"]]
        raw = evidence.bytes(base / workload["path"])
        assert hashlib.sha256(raw).hexdigest() == workload["sha256"]
        raw = gzip.decompress(raw)
        assert hashlib.sha256(raw).hexdigest() == workload["content_sha256"]
        rows = json.loads(raw)
        assert all(len(a["calls"]) == 1 for a in rows), (
            "fallback replay requires single-invocation Agents"
        )
        agents = {a["workflow"] + "/" + a["name"]: a for a in rows}
        requests = {r["agent"]: r for r in summary["requests"]}
        assert len(requests) == len(rows) == len(summary["requests"])
        parents = {
            k: [a["workflow"] + "/" + name for name in a["predecessors"]] for k, a in agents.items()
        }
        children = {k: [] for k in agents}
        for key, preds in parents.items():
            for pred in preds:
                children[pred].append(key)
        indegree = {k: len(v) for k, v in parents.items()}
        ready = deque(sorted(k for k, n in indegree.items() if n == 0))
        order = []
        while ready:
            key = ready.popleft()
            order.append(key)
            for child in sorted(children[key]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        assert len(order) == len(agents)
        states = {}
        events = [
            json.loads(line)
            for line in gzip.decompress(
                evidence.bytes(base / "runs" / job["id"] / "events.jsonl.gz")
            ).splitlines()
        ]
        config = job["config"]
        checked = 0
        run_samples = []
        i = 0
        while i < len(events):
            event = events[i]
            if event["kind"] == "submit":
                assert event["invocation"] == 0 and event["agent"] not in states
                states[event["agent"]] = (event["time_ns"], agents[event["agent"]]["prior_ns"])
            elif event["kind"] == "prediction" and event["accepted"]:
                states[event["agent"]] = (event["submitted_ns"], event["remaining_ns"])
            elif event["kind"] == "policy_sample":
                time = event["time_ns"]
                group = []
                while (
                    i < len(events)
                    and events[i]["kind"] == "policy_sample"
                    and events[i]["time_ns"] == time
                ):
                    group.append(events[i])
                    i += 1
                observed = {e["agent"] for e in group}
                workflows = {agents[k]["workflow"] for k in observed}
                expected_slack = {}
                for workflow in sorted(workflows):
                    # Same-time completions are resolved by the captured active set.
                    keys = [
                        k
                        for k in order
                        if agents[k]["workflow"] == workflow
                        and (requests[k]["finish_ns"] > time or k in observed)
                    ]
                    duration, invalid = {}, {}
                    for key in keys:
                        submitted, value = states.get(key, (time, agents[key]["prior_ns"]))
                        age = time - submitted
                        reason = None
                        if value is None or not isfinite(value):
                            reason = "missing_or_nonfinite"
                        elif age < 0:
                            reason = "negative_age"
                        elif age > config["prediction_ttl_ns"]:
                            reason = "ttl_expired"
                        elif value - age <= 0:
                            reason = "prediction_minus_age_nonpositive"
                        if reason:
                            invalid[key] = reason
                        else:
                            duration[key] = int(value) - age
                    if invalid:
                        expected_slack.update(dict.fromkeys(keys, 0))
                    else:
                        earliest = {}
                        for key in keys:
                            earliest[key] = duration[key] + max(
                                (earliest[p] for p in parents[key] if p in duration), default=0
                            )
                        end = max(earliest.values())
                        latest = {}
                        for key in reversed(keys):
                            latest[key] = min(
                                [end]
                                + [latest[c] - duration[c] for c in children[key] if c in duration]
                            )
                            expected_slack[key] = max(
                                0, latest[key] - earliest[key] - config["slack_guard_ns"]
                            )
                    row = dict(
                        run_id=job["id"],
                        model=job["model"],
                        policy=job["policy"],
                        failure_run=job["failure"] is not None,
                        time_ns=time,
                        workflow=workflow,
                        fallback=bool(invalid),
                        invalid_agents=len(invalid),
                        active_agents=sum(agents[k]["workflow"] == workflow for k in observed),
                        invalid_reasons="|".join(sorted(set(invalid.values()))),
                    )
                    samples.append(row)
                    run_samples.append(row)
                for observed_sample in group:
                    expected = expected_slack[observed_sample["agent"]]
                    if config.get("slack_mode", "dag") == "zero":
                        expected = 0
                    assert expected == observed_sample["slack_ns"], (
                        job["id"],
                        observed_sample,
                        expected,
                    )
                    checked += 1
                continue
            i += 1
        assert run_samples and checked > 0
        count = sum(row["fallback"] for row in run_samples)
        aggregates.append(
            dict(
                run_id=job["id"],
                model=job["model"],
                policy=job["policy"],
                failure_run=job["failure"] is not None,
                active_workflow_control_window_samples=len(run_samples),
                fallback_samples=count,
                fallback_sample_share=count / len(run_samples),
                all_sampled_agent_slacks_reconstructed_exactly=checked,
                active_agent_samples=sum(row["active_agents"] for row in run_samples),
                fallback_weighted_agent_samples=sum(
                    row["active_agents"] for row in run_samples if row["fallback"]
                ),
                reason_sample_counts={
                    reason: sum(reason in row["invalid_reasons"] for row in run_samples)
                    for reason in sorted(
                        {
                            part
                            for row in run_samples
                            for part in row["invalid_reasons"].split("|")
                            if part
                        }
                    )
                },
            )
        )
    return aggregates, samples


def dma_rows(plan, runs):
    scenarios, workflows = [], []
    aliases = [
        a for a in plan["protocol"]["factor_aliases"] if a["factor"] == "compute_dma_slowdown"
    ]
    for alias in aliases:
        condition = alias["condition"]
        subset = {
            (j["policy"], j["fault"]): (j, s)
            for j, s in runs.values()
            if j["condition"] == condition
        }
        none0, none1 = (subset["none", f][1] for f in ("F0", "F1"))
        target = none1["failure"]["agent"].split("/", 1)[0]
        for policy in ("dram", "aegiskv"):
            j0, p0 = subset[policy, "F0"]
            j1, p1 = subset[policy, "F1"]
            assert j0["config"] == j1["config"] == subset["none", "F0"][0]["config"]
            assert j1["failure"] == subset["none", "F1"][0]["failure"]
            for field in ("agent", "invocation", "logical_tokens", "total_tokens"):
                assert p1["failure"][field] == none1["failure"][field]
            assert (
                p0["workflows"].keys()
                == none0["workflows"].keys()
                == p1["workflows"].keys()
                == none1["workflows"].keys()
            )
            local = []
            for workflow in p0["workflows"]:
                n0, n1, w0, w1 = [
                    s["workflows"][workflow]["wct_ns"] for s in (none0, none1, p0, p1)
                ]
                row = dict(
                    condition=condition,
                    dma_slowdown=alias["value"],
                    policy=policy,
                    workflow=workflow,
                    is_target=workflow == target,
                    none_f0_ns=n0,
                    none_f1_ns=n1,
                    policy_f0_ns=w0,
                    policy_f1_ns=w1,
                    healthy_extra_ns=w0 - n0,
                    incremental_fault_advantage_ns=(n1 - n0) - (w1 - w0),
                    absolute_f1_advantage_ns=n1 - w1,
                )
                assert (
                    row["incremental_fault_advantage_ns"]
                    == row["healthy_extra_ns"] + row["absolute_f1_advantage_ns"]
                )
                workflows.append(row)
                local.append(row)
            for metric, records in (
                ("four_workflow_sum_wct", local),
                ("target_workflow_wct", [r for r in local if r["is_target"]]),
            ):
                healthy = sum(r["healthy_extra_ns"] for r in records)
                advantage = sum(r["incremental_fault_advantage_ns"] for r in records)
                pstar = healthy / advantage if advantage > 0 else None
                scenarios.append(
                    dict(
                        condition=condition,
                        dma_slowdown=alias["value"],
                        policy=policy,
                        metric=metric,
                        workflow_observations=len(records),
                        healthy_extra_s=healthy / 1e9,
                        incremental_fault_advantage_s=advantage / 1e9,
                        absolute_f1_advantage_s=sum(r["absolute_f1_advantage_ns"] for r in records)
                        / 1e9,
                        hypothetical_break_even_probability=pstar,
                        feasible_probability_in_0_1=pstar is not None and 0 <= pstar <= 1,
                        none_healthy_mean_wct_s=mean(r["none_f0_ns"] for r in records) / 1e9,
                        policy_healthy_mean_wct_s=mean(r["policy_f0_ns"] for r in records) / 1e9,
                        healthy_wct_increase_pct=100
                        * healthy
                        / sum(r["none_f0_ns"] for r in records),
                        none_healthy_max_wct_s=max(r["none_f0_ns"] for r in records) / 1e9,
                        policy_healthy_max_wct_s=max(r["policy_f0_ns"] for r in records) / 1e9,
                        policy_healthy_run_modeled_dma_compute_slowdown_ns=p0["metrics"].get(
                            "modeled_dma_compute_slowdown_ns", 0
                        ),
                    )
                )
    return scenarios, workflows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--sensitivity", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--label", required=True, help="Explicit evidence version, e.g. historical-v1"
    )
    args = parser.parse_args()
    args.primary, args.sensitivity, args.out = (
        p.resolve() for p in (args.primary, args.sensitivity, args.out)
    )
    args.out.mkdir(parents=True, exist_ok=False)
    evidence = Evidence()
    pp, pm, pr = campaign(evidence, args.primary)
    sp, sm, sr = campaign(evidence, args.sensitivity)
    healthy, comparisons, pairs = primary_rows(pr)
    fallback, windows = fallback_samples(evidence, args.primary, pp, pr)
    dma, dma_workflows = dma_rows(sp, sr)
    # Existing CSV is a cross-check only; all quantities above use raw summaries.
    table = args.primary / "run-metrics.csv"
    if table.exists():
        rows = {r["run_id"]: r for r in csv.DictReader(evidence.bytes(table).decode().splitlines())}
        for row in healthy:
            assert (
                int(rows[row["run_id"]]["metric_slack_fallback_observations"])
                == row["fallback_rebalance_workflow_observations"]
            )
    outputs = {
        "primary-healthy.csv": healthy,
        "dram-threshold-comparison.csv": comparisons,
        "dram-threshold-workflow-pairs.csv": pairs,
        "fallback-control-windows.csv": windows,
        "dma-scenarios.csv": dma,
        "dma-workflow-pairs.csv": dma_workflows,
    }
    for name, rows in outputs.items():
        write_csv(args.out / name, rows)
    for path, digest in evidence.hashes.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
    report = dict(
        status="PASS",
        evidence_label=args.label,
        primary_campaign=str(args.primary),
        sensitivity_campaign=str(args.sensitivity),
        design_versions={"primary": pm["design_version"], "sensitivity": sm["design_version"]},
        primary_runs_verified=len(pr),
        sensitivity_runs_verified=len(sr),
        input_files_unchanged_during_audit=True,
        fallback_counter_unit="sum of fallback workflows over _rebalance evaluations; denominator and elapsed-time share unavailable in summary",
        detailed_fallback=fallback,
        healthy_dram_comparisons=comparisons,
        primary_dram_all_dram_workflow_pairs=len(pairs),
        healthy_dram_all_dram_nonidentical_wct_count=sum(
            r["fault_index"] == -1 and r["all_dram_minus_dram_ns"] != 0 for r in pairs
        ),
        primary_dram_all_dram_nonidentical_workflows=[
            r for r in pairs if r["all_dram_minus_dram_ns"]
        ],
        dma_scenarios=dma,
        hypothetical_mixture="p is probability of exactly this fixed F1 scenario versus its F0 over the same four-workflow cohort; expected policy advantage=p*D-H. Not a measured failure rate or extrapolation to multiple failures.",
        limitations=[
            (
                "These historical frozen simulations predate the recovery-domain correction; new implementations require their own matched reruns."
                if any("causal-domain" not in manifest["design_version"] for manifest in (pm, sm))
                else "These directories bind their own corrected design versions; old historical results remain separate evidence."
            ),
            "Repeated fallback observations are not unique fallback events, accuracy measurements, or independent statistical samples.",
            "Detailed window fractions concern the actual logged AegisKV F1 conditions, not healthy DRAM runs or other load cells.",
            "Control-window samples are regularly spaced discrete observations, not an exact continuous-time fallback integral; unfinished workflow counts are the denominator.",
            "Zero Slack also occurs legitimately on critical paths or through guard clipping; it is not itself proof of fallback.",
            "All-DRAM bypasses the tolerance threshold but preserves Slack-derived E ranking and finite-capacity admission; it is not a no-Slack baseline.",
            "Canceled-copy bytes count work already transferred, alongside completed checkpoint/hot bytes; successful-checkpoint-only savings use a narrower numerator.",
            "DMA overhead is generated by configured event-start slowdown, not physical serving measurements or calibrated overhead.",
            "Same protected checkpoint does not logically force equal WCT: publication/readiness, transfer contention, compute interference and later routing can differ.",
            "Target-only recovery advantage and cohort-total healthy cost have different objective denominators and cannot be combined into a break-even rate.",
        ],
        input_sha256=evidence.hashes,
        analysis_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        output_sha256={
            name: hashlib.sha256((args.out / name).read_bytes()).hexdigest() for name in outputs
        },
    )
    (args.out / "AUDIT.json").write_bytes(encoded(report))
    lines = [
        f"# O1 and DMA evidence audit: {args.label}",
        "",
        "PASS: raw summaries and configuration/job/completion bindings verified. No simulation executed.",
        "",
        f"Primary: {len(pr)} runs, `{pm['design_version']}`. Sensitivity: {len(sr)} runs, `{sm['design_version']}`.",
        "",
        "## Healthy DRAM versus All-DRAM",
        "",
        "| Workload | DRAM fallback observations | Completed checkpoint saving | All transferred backup saving |",
        "|---|---:|---:|---:|",
    ]
    for row in comparisons:
        lines.append(
            f"| {row['workload']} | {row['dram_fallback_observations']} | {row['completed_checkpoint_saving_pct']:.6f}% | {row['all_transferred_backup_saving_pct']:.6f}% |"
        )
    lines += [
        "",
        f"Healthy nonidentical per-workflow WCT pairs: {report['healthy_dram_all_dram_nonidentical_wct_count']}. F1 differences are retained in AUDIT.json and the full same-ID CSV; aggregate cancellation is not per-workflow equality.",
        "",
        "## Fallback observation units",
        "",
        report["fallback_counter_unit"] + ".",
        "",
    ]
    for row in fallback:
        lines.append(
            f"- `{row['run_id']}`: {row['fallback_samples']}/{row['active_workflow_control_window_samples']} active workflow/control-window samples ({100 * row['fallback_sample_share']:.4f}%). All {row['all_sampled_agent_slacks_reconstructed_exactly']} recorded Agent Slack values independently reconstructed exactly."
        )
    lines += [
        "",
        "## DMA sensitivity",
        "",
        "| Slowdown | Policy | Healthy mean WCT | Increase | Cohort healthy extra | Cohort incremental fault advantage | Hypothetical break-even p |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in dma:
        if row["metric"] == "four_workflow_sum_wct":
            lines.append(
                f"| {row['dma_slowdown']} | {row['policy']} | {row['policy_healthy_mean_wct_s']:.9f} s | {row['healthy_wct_increase_pct']:.4f}% | {row['healthy_extra_s']:.9f} s | {row['incremental_fault_advantage_s']:.9f} s | {row['hypothetical_break_even_probability']} |"
            )
    lines += ["", report["hypothetical_mixture"], "", "## Causal and evidence boundaries", ""]
    lines += [f"- {limit}" for limit in report["limitations"]]
    lines += [
        "",
        "All exported rows retain negative outcomes. Neither workflows within a cohort nor control-window observations are independent repetitions.",
        "",
    ]
    (args.out / "RESULTS.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "status": "PASS",
                "out": str(args.out),
                "fallback": fallback,
                "workflow_exceptions": report["primary_dram_all_dram_nonidentical_workflows"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
