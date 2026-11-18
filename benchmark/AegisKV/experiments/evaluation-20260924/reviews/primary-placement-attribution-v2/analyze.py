#!/usr/bin/env python3
"""Recompute paired placement/recovery endpoints from sealed v2 records; no DES imports."""

# Long literal lines keep generated Markdown paragraphs and tables readable.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "python/moonkvsim").is_dir())
DEFAULT = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v2-corrected"
COMPARISONS = (("none", "dram"), ("dram", "aegiskv"), ("all_dram", "dram"))
CASES = (
    ("Qwen3-32B", "0.3", 4),
    ("Qwen3-32B", "0.9", 4),
    ("Qwen3-8B", "0.9", 3),
    ("Qwen3-8B", "0.65", 3),
)


def encoded(x):
    return (
        json.dumps(x, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n"
    ).encode()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seconds(ns):
    return f"{ns / 1e9:.9f}"


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        for row in rows:
            w.writerow(
                {
                    k: json.dumps(v, separators=(",", ":")) if isinstance(v, (list, dict)) else v
                    for k, v in row.items()
                }
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=DEFAULT)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    base, out = args.campaign.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "AUDIT.json").exists():
        raise SystemExit("Output already sealed; reproduce into a new --out directory.")
    source_hashes = {}

    def bind(path, expected=None):
        value = digest(path)
        if expected is not None:
            assert value == expected, (path, value, expected)
        source_hashes[str(path.relative_to(base))] = value
        return value

    def read(relative):
        path = base / relative
        bind(path)
        return json.loads(path.read_text())

    plan, manifest, upstream = read("PLAN.json"), read("MANIFEST.json"), read("AUDIT.json")
    assert upstream["passed"] and upstream["status"] == "PASS"
    assert upstream["verified_runs"] == upstream["planned_runs"] == 180
    assert all(x["verified"] for x in upstream["runs"])
    for name, value in manifest["control_sha256"].items():
        bind(base / name, value)
    for name, value in manifest["profile_sha256"].items():
        bind(base / name, value)
    for name, value in manifest["source_sha256"].items():
        bind(base / "source_snapshot" / name, value)

    dags = {}
    for name, info in plan["workloads"].items():
        p = base / info["path"]
        bind(p, info["sha256"])
        with gzip.open(p, "rb") as f:
            raw = f.read()
        assert hashlib.sha256(raw).hexdigest() == info["content_sha256"]
        agents = json.loads(raw)
        dags[name] = {
            a["workflow"] + "/" + a["name"]: {
                "workflow": a["workflow"],
                "predecessors": [a["workflow"] + "/" + x for x in a["predecessors"]],
                "release_ns": a["release_ns"],
                "calls": len(a["calls"]),
            }
            for a in agents
        }
        assert len(dags[name]) == 503 and all(x["calls"] == 1 for x in dags[name].values())
        del agents, raw

    summaries, jobs, completions = {}, {}, {}
    for job in plan["jobs"]:
        name = job["id"]
        jobs[name] = job
        marker = read(f"runs/{name}/COMPLETE.json")
        summary = read(f"runs/{name}/summary.json")
        config = read(f"runs/{name}/config.json")
        failure = read(f"runs/{name}/failure.json")
        assert marker["complete"] and marker["id"] == name
        assert marker["job_sha256"] == hashlib.sha256(encoded(job)).hexdigest()
        assert marker["summary_sha256"] == source_hashes[f"runs/{name}/summary.json"]
        assert marker["priors_sha256"] == source_hashes["PRIORS.json"]
        assert marker["profile_sha256"] == source_hashes[f"profiles/{job['model']}.json"]
        assert marker["workload_sha256"] == plan["workloads"][job["workload"]]["sha256"]
        assert config == job["config"] and failure == job["failure"]
        assert summary["config_sha256"] == hashlib.sha256(encoded(config)).hexdigest()
        assert summary["workload_sha256"] == plan["workloads"][job["workload"]]["content_sha256"]
        assert summary["design_version"] == manifest["design_version"]
        assert (
            summary["complete"]
            and summary["output_tokens_exact"]
            and summary["terminal_allocations_zero"]
        )
        assert len(summary["workflows"]) == 62 and len(summary["requests"]) == 503
        for rr in summary["requests"]:
            assert rr["finish_ns"] - rr["submit_ns"] == rr["latency_ns"]
        for rec in summary["recoveries"]:
            assert rec["detection_ns"] + rec["queue_ns"] + rec["service_ns"] == rec["latency_ns"]
            assert rec["first_new_token_ns"] - rec["failure_ns"] == rec["latency_ns"]
            assert rec["admitted_ns"] - rec["retry_enqueued_ns"] == rec["queue_ns"]
        summaries[name], completions[name] = summary, marker
    assert len(summaries) == 180

    comparisons, workflows, calls, details = [], [], [], {}
    for model in ("Qwen3-8B", "Qwen3-32B"):
        for load in ("0.3", "0.65", "0.9"):
            cell = f"{model}-load{load}"
            dag = dags[cell]
            for fault in range(5):
                for left, right in COMPARISONS:
                    ids = [f"{cell}-{p}-F1-{fault}" for p in (left, right)]
                    a, z = [summaries[i] for i in ids]
                    f0ids = [jobs[i]["f0_id"] for i in ids]
                    a0, z0 = [summaries[i] for i in f0ids]
                    assert (
                        a["config_sha256"]
                        == z["config_sha256"]
                        == a0["config_sha256"]
                        == z0["config_sha256"]
                    )
                    assert (
                        a["workload_sha256"]
                        == z["workload_sha256"]
                        == a0["workload_sha256"]
                        == z0["workload_sha256"]
                    )
                    assert a["policy"] == a0["policy"] == left
                    assert z["policy"] == z0["policy"] == right
                    assert a0["failure"] is None and z0["failure"] is None
                    fa, fz = a["failure"], z["failure"]
                    for key in ("agent", "invocation", "logical_tokens", "total_tokens"):
                        assert fa[key] == fz[key], (ids, key)
                    target = fa["agent"].rsplit("/", 1)[0]
                    recs = [
                        next(
                            v
                            for v in s["recoveries"]
                            if (v["agent"], v["invocation"]) == (fa["agent"], fa["invocation"])
                        )
                        for s in (a, z)
                    ]
                    row = dict(
                        id=f"{cell}-F1-{fault}-{left}-to-{right}",
                        model=model,
                        load=load,
                        fault_index=fault,
                        comparison=f"{left}_to_{right}",
                        from_policy=left,
                        to_policy=right,
                        from_run=ids[0],
                        to_run=ids[1],
                        from_f0=f0ids[0],
                        to_f0=f0ids[1],
                        agent=fa["agent"],
                        invocation=fa["invocation"],
                        target_workflow=target,
                        logical_tokens=fa["logical_tokens"],
                        total_tokens=fa["total_tokens"],
                        same_logical_fault=True,
                        fault_time_equal=fa["time_ns"] == fz["time_ns"],
                        failed_workers_equal=fa["workers"] == fz["workers"],
                    )
                    for prefix, f, rec, summary, run_id in zip(
                        ("from", "to"), (fa, fz), recs, (a, z), ids, strict=True
                    ):
                        row[prefix + "_failure_time_ns"] = f["time_ns"]
                        row[prefix + "_failed_workers"] = f["workers"]
                        row[prefix + "_failed_hosts"] = sorted(
                            {jobs[run_id]["config"]["hosts"][w] for w in f["workers"]}
                        )
                        row[prefix + "_active_victims"] = sorted(
                            [v["agent"], v["invocation"]] for v in summary["recoveries"]
                        )
                        row[prefix + "_queued_histories"] = sorted(
                            [v["agent"], v["invocation"]] for v in summary["history_restores"]
                        )
                        for key in (
                            "retry_worker",
                            "source_worker",
                            "checkpoint_tokens",
                            "admitted_ns",
                            "retry_enqueued_ns",
                            "detection_ns",
                            "queue_ns",
                            "service_ns",
                            "latency_ns",
                            "first_new_token_ns",
                        ):
                            row[prefix + "_" + key] = rec[key]
                    row["retry_worker_changed"] = recs[0]["retry_worker"] != recs[1]["retry_worker"]
                    row["active_victims_equal"] = (
                        row["from_active_victims"] == row["to_active_victims"]
                    )
                    row["queued_histories_equal"] = (
                        row["from_queued_histories"] == row["to_queued_histories"]
                    )
                    for key in (
                        "failure_time_ns",
                        "detection_ns",
                        "queue_ns",
                        "service_ns",
                        "latency_ns",
                        "first_new_token_ns",
                    ):
                        delta = row["to_" + key] - row["from_" + key]
                        row[key.removesuffix("_ns") + "_delta_ns"] = delta
                        row[key.removesuffix("_ns") + "_delta_s"] = delta / 1e9
                    assert row["latency_delta_ns"] == sum(
                        row[k + "_delta_ns"] for k in ("detection", "queue", "service")
                    )
                    assert (
                        row["first_new_token_delta_ns"]
                        == row["failure_time_delta_ns"] + row["latency_delta_ns"]
                    )
                    deltas = []
                    for wf in sorted(a["workflows"]):
                        assert all(wf in s["workflows"] for s in (z, a0, z0))
                        wa, wz, wa0, wz0 = [s["workflows"][wf] for s in (a, z, a0, z0)]
                        assert (
                            wa["start_ns"] == wz["start_ns"] == wa0["start_ns"] == wz0["start_ns"]
                        )
                        pa, pz = wa["wct_ns"] - wa0["wct_ns"], wz["wct_ns"] - wz0["wct_ns"]
                        delta = pz - pa
                        entry = dict(
                            comparison_id=row["id"],
                            workflow=wf,
                            is_target=wf == target,
                            from_f0_wct_ns=wa0["wct_ns"],
                            to_f0_wct_ns=wz0["wct_ns"],
                            from_f1_wct_ns=wa["wct_ns"],
                            to_f1_wct_ns=wz["wct_ns"],
                            from_paired_delta_ns=pa,
                            to_paired_delta_ns=pz,
                            policy_contrast_ns=delta,
                            policy_contrast_s=delta / 1e9,
                            raw_f1_difference_ns=wz["wct_ns"] - wa["wct_ns"],
                        )
                        workflows.append(entry)
                        deltas.append(delta)
                        if wf == target:
                            for k, v in entry.items():
                                if k not in {"comparison_id", "workflow", "is_target"}:
                                    row["target_" + k] = v
                    row.update(
                        workflow_count=62,
                        cohort_sum_contrast_ns=sum(deltas),
                        cohort_sum_contrast_s=sum(deltas) / 1e9,
                        cohort_mean_contrast_s=sum(deltas) / 62e9,
                        workflows_worse=sum(v > 0 for v in deltas),
                        workflows_better=sum(v < 0 for v in deltas),
                        workflows_equal=sum(v == 0 for v in deltas),
                    )
                    assert (
                        row["workflows_worse"] + row["workflows_better"] + row["workflows_equal"]
                        == 62
                    )
                    descendants = set()
                    while True:
                        expanded = {
                            k
                            for k, v in dag.items()
                            if any(p in descendants or p == fa["agent"] for p in v["predecessors"])
                        }
                        if expanded <= descendants:
                            break
                        descendants |= expanded
                    requests = [
                        {(v["agent"], v["invocation"]): v for v in s["requests"]}
                        for s in (a, z, a0, z0)
                    ]
                    own_calls = []
                    for key in sorted(k for k in requests[0] if dag[k[0]]["workflow"] == target):
                        ra, rz, ra0, rz0 = [q[key] for q in requests]
                        call = dict(
                            comparison_id=row["id"],
                            agent=key[0],
                            invocation=key[1],
                            relation="target"
                            if key[0] == fa["agent"]
                            else "descendant"
                            if key[0] in descendants
                            else "other_same_workflow",
                            predecessors=dag[key[0]]["predecessors"],
                            ordinary_admission_recorded=False,
                        )
                        for prefix, request in zip(
                            ("from", "to", "from_f0", "to_f0"), (ra, rz, ra0, rz0), strict=True
                        ):
                            for key2 in ("submit_ns", "finish_ns", "latency_ns", "worker"):
                                call[prefix + "_" + key2] = request[key2]
                        for key2 in ("submit_ns", "finish_ns", "latency_ns"):
                            call[key2.removesuffix("_ns") + "_delta_ns"] = rz[key2] - ra[key2]
                        assert (
                            call["finish_delta_ns"]
                            == call["submit_delta_ns"] + call["latency_delta_ns"]
                        )
                        for prefix, request_map in zip(("from", "to"), requests[:2], strict=True):
                            preds = call["predecessors"]
                            latest = max(
                                (request_map[p, 0]["finish_ns"] for p in preds), default=None
                            )
                            call[prefix + "_latest_finishing_predecessors"] = [
                                p for p in preds if request_map[p, 0]["finish_ns"] == latest
                            ]
                        calls.append(call)
                        own_calls.append(call)
                    comparisons.append(row)
                    if left == "none" and right == "dram" and (model, load, fault) in CASES:
                        details[row["id"]] = dict(
                            comparison=row,
                            same_workflow_requests=own_calls,
                            workflow_contrasts=[w for w in workflows[-62:]],
                        )
    assert len(comparisons) == 90 and len(workflows) == 5580 and len(details) == 4
    selected = {
        (x["comparison"]["model"], x["comparison"]["load"], x["comparison"]["fault_index"]): x[
            "comparison"
        ]
        for x in details.values()
    }
    assert selected[CASES[0]]["queue_delta_ns"] == 1452690018
    assert selected[CASES[0]]["service_delta_ns"] == -29056592
    assert selected[CASES[2]]["latency_delta_ns"] == -1775386328
    assert selected[CASES[2]]["target_policy_contrast_ns"] == 2225998889
    assert selected[CASES[3]]["target_policy_contrast_ns"] == -1775386328
    assert abs(round(selected[CASES[3]]["cohort_mean_contrast_s"] * 1e9) - 117551097) <= 1

    write_csv(out / "comparisons.csv", comparisons)
    write_csv(out / "workflow-contrasts.csv", workflows)
    write_csv(out / "same-workflow-requests.csv", calls)
    (out / "case-details.json").write_bytes(encoded(details))
    (out / "comparisons.json").write_bytes(encoded(comparisons))
    lines = [
        "# Primary retry placement and queue attribution (corrected v2)",
        "",
        "All differences are **to policy minus from policy**. Negative recovery latency or WCT contrasts favor the to policy; positive values are adverse. Each WCT policy contrast subtracts its own same-ID F0 first. All 90 contrasts (6 cells x 5 fixed faults x 3 comparisons) and all 5,580 workflow rows remain, including zeros and negative outcomes. No DES or new samples were run.",
        "",
        "Recovery latency = detection + retry queue + admitted service through the first new token. Absolute first-token time also includes the actual failure-wall-time difference, reported separately. Retry worker is the actual recorded worker. Full fault identity, wall time, failed workers/hosts, active victim IDs and separately classified queued histories are retained; logical identity matching is asserted, other alignments are reported rather than assumed.",
        "",
        "Ordinary requests record submit/finish/latency/worker, not admission. Their latency is not a measured queue decomposition. All calls in the target workflow, including transitive descendants identified from the frozen DAG and latest-finishing predecessors, are exported. For an interrupted call, summary.worker records its completing worker, not necessarily its initial worker.",
        "",
        "## Complete-matrix directions",
        "",
        "| Contrast | Conditions | Target worse/better/equal | Cohort sum worse/better/equal | Changed retry workers |",
        "|---|---:|---|---|---:|",
    ]
    for a, z in COMPARISONS:
        group = [v for v in comparisons if v["comparison"] == f"{a}_to_{z}"]

        def signs(key, values=group):
            return "/".join(
                str(
                    sum(
                        (v[key] > 0 if i == 0 else v[key] < 0 if i == 1 else v[key] == 0)
                        for v in values
                    )
                )
                for i in range(3)
            )

        lines.append(
            f"| {a} → {z} | {len(group)} | {signs('target_policy_contrast_ns')} | {signs('cohort_sum_contrast_ns')} | {sum(v['retry_worker_changed'] for v in group)} |"
        )
    lines += [
        "",
        "## Four requested descriptive cases",
        "",
        "These cases were requested from known results, not selected prospectively as an inferential sample. The complete 90-condition table is the denominator.",
    ]
    for key in CASES:
        row = selected[key]
        detail = details[row["id"]]
        lines += [
            "",
            f"### {row['model']}, load {row['load']}, F1-{row['fault_index']}: Restart → DRAM",
            "",
            f"Target `{row['agent']}`, invocation {row['invocation']}, logical {row['logical_tokens']}/{row['total_tokens']}; failure wall {seconds(row['from_failure_time_ns'])}/{seconds(row['to_failure_time_ns'])} s; failed workers {row['from_failed_workers']}/{row['to_failed_workers']}. Retry workers {row['from_retry_worker']} → {row['to_retry_worker']}.",
            "",
            "| Metric | Restart (s) | DRAM (s) | DRAM - Restart (s) |",
            "|---|---:|---:|---:|",
        ]
        for label, k in [
            ("Detection", "detection"),
            ("Retry queue", "queue"),
            ("Admitted recovery service", "service"),
            ("Failure to first new token", "latency"),
        ]:
            lines.append(
                f"| {label} | {seconds(row['from_' + k + '_ns'])} | {seconds(row['to_' + k + '_ns'])} | {seconds(row[k + '_delta_ns'])} |"
            )
        lines += [
            "",
            f"Target paired ΔWCT contrast: **{seconds(row['target_policy_contrast_ns'])} s**. All-62-workflow sum contrast: **{seconds(row['cohort_sum_contrast_ns'])} s**; mean: **{row['cohort_mean_contrast_s']:.12f} s**. Worse/better/equal workflows: **{row['workflows_worse']}/{row['workflows_better']}/{row['workflows_equal']}**.",
            "",
            "| Call (target/descendant) | Submit difference (s) | Finish difference (s) | Call latency difference (s) | Worker |",
            "|---|---:|---:|---:|---|",
        ]
        for c in detail["same_workflow_requests"]:
            if c["relation"] not in {"target", "descendant"}:
                continue
            lines.append(
                f"| `{c['agent']}` ({c['relation']}) | {seconds(c['submit_delta_ns'])} | {seconds(c['finish_delta_ns'])} | {seconds(c['latency_delta_ns'])} | {c['from_worker']} → {c['to_worker']} |"
            )
        for c in detail["same_workflow_requests"]:
            if c["relation"] == "descendant":
                lines += [
                    "",
                    f"Recorded latest-finishing predecessor(s) of `{c['agent']}`: "
                    f"{c['from_latest_finishing_predecessors']} → {c['to_latest_finishing_predecessors']}. "
                    "This identifies dependency release timing, not unrecorded admission delay.",
                ]
        other_changes = [
            v
            for v in detail["workflow_contrasts"]
            if not v["is_target"] and v["policy_contrast_ns"]
        ]
        if len(other_changes) == 1:
            w = other_changes[0]
            lines += [
                "",
                f"The only other changed workflow is `{w['workflow']}`: "
                f"paired WCT contrast {seconds(w['policy_contrast_ns'])} s.",
            ]
        if key == CASES[3]:
            lines += [
                "",
                "**Endpoint correction:** this target improves by 1.775386328 s; the adverse approximately 0.117551097 s belongs to the all-workflow mean. It must not be reported as target degradation.",
            ]
        if key == CASES[2]:
            lines += [
                "",
                "Local failure-to-first-token recovery improves by 1.775386328 s, but the target finishes 2.225998889 s later. Descendant submit/finish/worker differences above describe the observed chain; they do not by themselves identify ordinary queue wait or a scheduling counterfactual.",
            ]
    lines += [
        "",
        "## Reproduction and evidence scope",
        "",
        "Run `python analyze.py --campaign /absolute/path/to/formal-core-v2-corrected --out /tmp/new-primary-placement-attribution` using a fresh output directory. The script uses only the Python standard library and reads the frozen campaign; it does not import a simulator or launch DES.",
        "",
        "AUDIT.json records SHA256 bindings for PLAN/MANIFEST, all frozen source files, profile/priors, six compressed workloads, the passing upstream audit, and all 180 run markers/configs/failure descriptors/summaries. It independently verifies COMPLETE job and summary identity, policy-specific F0, integer-time decompositions, output completion and final-release assertions, then rechecks that all bound files stayed unchanged. This is an accounting/association analysis, not proof that placement is the sole causal source of an observed WCT change. The summaries do not record ordinary admission events or a policy-independent placement counterfactual. No population confidence interval or physical performance claim is made.",
    ]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    assert all(digest(base / name) == value for name, value in source_hashes.items())
    output_names = [
        "comparisons.csv",
        "comparisons.json",
        "workflow-contrasts.csv",
        "same-workflow-requests.csv",
        "case-details.json",
        "REPORT.md",
    ]
    audit = dict(
        status="PASS",
        version=manifest["design_version"],
        verified_complete_runs=180,
        comparison_rows=90,
        workflow_rows=len(workflows),
        same_workflow_request_rows=len(calls),
        requested_cases=4,
        logical_fault_matches=sum(v["same_logical_fault"] for v in comparisons),
        fault_wall_matches=sum(v["fault_time_equal"] for v in comparisons),
        failed_worker_matches=sum(v["failed_workers_equal"] for v in comparisons),
        active_victim_matches=sum(v["active_victims_equal"] for v in comparisons),
        history_restore_matches=sum(v["queued_histories_equal"] for v in comparisons),
        source_files_unchanged=True,
        all_complete_job_config_failure_summary_bindings_verified=True,
        ordinary_admission_observed=False,
        no_new_simulation=True,
        analysis_script_sha256=digest(Path(__file__).resolve()),
        source_sha256=source_hashes,
        output_sha256={n: digest(out / n) for n in output_names},
    )
    (out / "AUDIT.json").write_bytes(encoded(audit))
    print(
        json.dumps(
            {k: v for k, v in audit.items() if k not in {"source_sha256", "output_sha256"}},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
