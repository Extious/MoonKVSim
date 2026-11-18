#!/usr/bin/env python3
"""Independent stdlib-only accounting for the frozen O3 diagnostic; launches no DES."""
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[5]
DEFAULT = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/quota-pressure-postreview-v1"


def encoded(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n"
    ).encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def objsha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def read(path):
    return json.loads(path.read_text())


def lines(path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def csv_write(path, rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()}
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT)
    args = parser.parse_args()
    out = args.out.resolve()
    sources = {}

    def bind(path, expected=None):
        value = sha(path)
        assert expected is None or value == expected, (str(path), expected, value)
        sources[
            str(path.relative_to(out)) if path.is_relative_to(out) else str(path.relative_to(ROOT))
        ] = value
        return value

    prepared, manifest, plan = [
        read(out / n) for n in ("PREPARED.json", "MANIFEST.json", "PLAN.json")
    ]
    bind(out / "PREPARED.json")
    bind(out / "MANIFEST.json", prepared["manifest_sha256"])
    for name, value in manifest["source_sha256"].items():
        bind(out / "source_snapshot" / name, value)
    for name, value in manifest["control_sha256"].items():
        bind(out / name, value)
    bind(out / plan["profile"], manifest["profile_sha256"])
    bind(out / plan["predictor"], manifest["predictor_sha256"])
    bind(out / plan["workload"]["path"], plan["workload"]["sha256"])
    for name, value in plan["protocol"]["source_inputs_sha256"].items():
        bind(ROOT / name, value)
    with gzip.open(out / plan["workload"]["path"], "rb") as stream:
        raw_input = stream.read()
    assert hashlib.sha256(raw_input).hexdigest() == plan["workload"]["content_sha256"]
    agents = json.loads(raw_input)
    original = (
        ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/sensitivity-campaign-v2-corrected"
    )
    old = read(original / "PLAN.json")
    bind(original / old["profile"], read(original / "MANIFEST.json")["profile_sha256"])
    assert sha(original / old["profile"]) == sha(out / plan["profile"])
    with gzip.open(original / old["workload"]["path"], "rt") as stream:
        old_agents = json.load(stream)
    predictor = read(out / plan["predictor"])
    assert len(agents) == 52 and len({a["workflow"] for a in agents}) == 4
    assert not {a["workflow"] for a in agents} & set(predictor["regressor"]["training_workflows"])
    for before, after in zip(old_agents, agents, strict=True):
        assert {k: v for k, v in before.items() if k != "prior_ns"} == {
            k: v for k, v in after.items() if k != "prior_ns"
        }
        assert after["prior_ns"] == predictor["role_priors_ns"].get(
            after["role"], predictor["role_priors_ns"]["__all__"]
        )
    jobs = plan["jobs"]
    assert len(jobs) == len({j["id"] for j in jobs}) == 72
    assert {(j["margin_MiB"], j["dma"], j["variant"], j["fault"]) for j in jobs} == {
        (m, d, v, f)
        for m in (0, 32, 128)
        for d in (0.0, 0.005)
        for v in ("none", "dram", "fixed32", "fixed128", "fixed4096", "adaptive")
        for f in ("F0", "F1")
    }
    results, rows, reconstructions, mechanism = {}, [], [], []
    for job in jobs:
        path = out / "runs" / job["id"]
        marker, summary = read(path / "COMPLETE.json"), read(path / "summary.json")
        bind(path / "COMPLETE.json")
        assert marker["status"] == "COMPLETE" and marker["id"] == job["id"]
        expected_bindings = dict(
            job_sha256=objsha(job),
            plan_sha256=sha(out / "PLAN.json"),
            manifest_sha256=sha(out / "MANIFEST.json"),
            profile_sha256=sha(out / plan["profile"]),
            predictor_sha256=sha(out / plan["predictor"]),
            workload_sha256=plan["workload"]["sha256"],
        )
        for k, v in expected_bindings.items():
            assert marker[k] == v
        for name, value in marker["artifact_sha256"].items():
            bind(path / name, value)
        config = read(path / "config.json")
        assert config == job["config"] and read(path / "failure.json") == job["failure"]
        allowed = {"hbm_bytes_per_rank", "compute_dma_slowdown", "slack_guard_ns"}
        assert {k: v for k, v in config.items() if k not in allowed} == {
            k: v for k, v in old["protocol"]["baseline_config"].items() if k not in allowed
        }
        assert config["slack_guard_ns"] == predictor["slack_guard_ns"] == 910471105
        maximum = max(
            (len(c["prompt"]) + c["output_limit_tokens"])
            * config["layers"]
            * config["kv_bytes_per_token_per_layer_rank"]
            + config["layers"]
            * ((len(c["prompt"]) + c["output_limit_tokens"] + 63) // 64)
            * (
                config["selector_metadata_bytes_per_block_per_layer_rank"]
                + config["count_bytes_per_block_per_layer_rank"]
            )
            for a in agents
            for c in a["calls"]
        )
        assert maximum == 5_039_327_808
        assert (
            config["hbm_bytes_per_rank"]
            == maximum + config["reserve_bytes"] + job["margin_MiB"] * 1024**2
        )
        assert config["compute_dma_slowdown"] == job["dma"]
        assert (
            summary["config_sha256"] == objsha(config)
            and summary["workload_sha256"] == plan["workload"]["content_sha256"]
        )
        assert summary["design_version"] == manifest["design_version"]
        assert (
            summary["policy"] == job["policy"]
            and summary["predictor"] == "hashed-text-agent-submission-to-completion-v1"
        )
        assert (
            summary["complete"]
            and summary["terminal_allocations_zero"]
            and summary["output_tokens_exact"]
            and not summary["oracle_reservation_count"]
        )
        assert len(summary["workflows"]) == 4 and len(summary["requests"]) == 52
        if job["failure"]:
            assert (
                summary["failure"]["agent"],
                summary["failure"]["invocation"],
                summary["failure"]["logical_tokens"],
            ) == (job["failure"]["agent"], 0, 16228)
        else:
            assert summary["failure"] is None
        for r in summary["recoveries"]:
            assert (
                r["detection_ns"] + r["queue_ns"] + r["service_ns"]
                == r["latency_ns"]
                == r["first_new_token_ns"] - r["failure_ns"]
            )
        resources, controls, admissions, reclaims, events = [
            lines(path / (k + ".jsonl.gz"))
            for k in ("resources", "controls", "admissions", "reclaims", "events")
        ]
        integral, previous, last_time = Counter(), {}, -1
        for r in resources:
            assert r["time_ns"] >= last_time
            last_time = r["time_ns"]
            if r["resource"] in previous:
                before = previous[r["resource"]]
                dt = r["time_ns"] - before["time_ns"]
                if r["resource"].startswith("hbm:"):
                    integral["primary_hbm"] += before["primary_bytes"] * dt
                    integral["replica_hbm"] += before["replica_bytes"] * dt
                else:
                    integral["replica_dram"] += before["replica_bytes"] * dt
            previous[r["resource"]] = r
            if r["resource"].startswith("hbm:"):
                assert r["ceiling_bytes"] == max(
                    0,
                    min(
                        config["hbm_cap_bytes"],
                        config["hbm_bytes_per_rank"] - r["primary_bytes"] - config["reserve_bytes"],
                    ),
                )
                assert (
                    r["primary_bytes"] + r["replica_bytes"] + r["free_bytes"]
                    == config["hbm_bytes_per_rank"]
                )
            else:
                assert r["replica_bytes"] + r["free_bytes"] == config["dram_bytes_per_host"]
        assert all(r["primary_bytes"] == r["replica_bytes"] == 0 for r in previous.values())
        for k in ("primary_hbm", "replica_hbm", "replica_dram"):
            assert integral[k] == summary["metrics"].get(k + "_byte_ns", 0), (job["id"], k)
        success = [r for r in admissions if r["successful"]]
        assert len(success) == 52 + len(summary["recoveries"])
        assert sum(not r["successful"] for r in admissions) == summary["metrics"].get(
            "foreground_admission_waits", 0
        )
        calls = {(r["agent"], r["invocation"]): r for r in summary["requests"]}
        ordinary = [r for r in success if not r["is_active_failure_retry"]]
        assert len(ordinary) == 52
        for r in ordinary:
            assert r["submit_ns"] == calls[r["agent"], r["invocation"]]["submit_ns"]
            assert r["submit_ns"] <= r["time_ns"] <= calls[r["agent"], r["invocation"]]["finish_ns"]
        for r in controls:
            assert r["after"]["quota"] <= r["after"]["resource"]["ceiling_bytes"]
            if job["fixed_quota_bytes"] is not None:
                assert r["after"]["quota"] <= job["fixed_quota_bytes"]
        quota_events = [e for e in events if e["kind"] == "quota"]
        fixed_events = [e for e in events if e["kind"] == "fixed_quota_ceiling"]
        mechanism.append(
            dict(
                id=job["id"],
                pressure_flag_control_entries=[r for r in controls if r["before"]["pressure"]],
                sticky_flag_admission_observations=[r for r in admissions if r["pressure_after"]],
                native_pressure_quota_events=[e for e in quota_events if e["pressure"]],
                fixed_target_ceiling_events=fixed_events,
                semantics=(
                    "admission wrapper before/after encloses the original reserve method; "
                    "pressure flags are sticky until control; zero quota cannot decrease further"
                ),
            )
        )
        for e in fixed_events:
            assert e["after"] == min(
                job["fixed_quota_bytes"],
                max(
                    0,
                    min(
                        config["hbm_cap_bytes"],
                        config["hbm_bytes_per_rank"] - e["serving_bytes"] - config["reserve_bytes"],
                    ),
                ),
            )
        hbm = [r for r in resources if r["resource"].startswith("hbm:") and r["alive"]]
        row = {k: job[k] for k in ("id", "condition", "margin_MiB", "dma", "variant", "fault")}
        row.update(
            mean_wct_ns=mean(r["wct_ns"] for r in summary["workflows"].values()),
            pressure_worker_rank_windows=sum(r["before"]["pressure"] for r in controls),
            sticky_flag_after_attempt_observations=sum(r["pressure_after"] for r in admissions),
            foreground_admission_wait_attempts=sum(not r["successful"] for r in admissions),
            ordinary_submission_to_admission_sum_ns=sum(
                r["time_ns"] - r["submit_ns"] for r in ordinary
            ),
            native_quota_pressure_decrease_events=sum(
                e["pressure"] and e["after"] < e["before"] for e in quota_events
            ),
            native_quota_nonpressure_decrease_events=sum(
                not e["pressure"] and e["after"] < e["before"] for e in quota_events
            ),
            native_quota_increase_events=sum(e["after"] > e["before"] for e in quota_events),
            fixed_target_regrowth_events=sum(e["after"] > e["before"] for e in fixed_events),
            fixed_target_ceiling_decrease_events=sum(
                e["after"] < e["before"] for e in fixed_events
            ),
            all_hot_release_abort_bytes=sum(
                n
                for r in reclaims
                if r["cause"] in {"HOT_RELEASE", "HOT_ABORT"}
                for _, _, _, n in r["changes"]
            ),
            minimum_live_ceiling_bytes=min(r["ceiling_bytes"] for r in hbm),
            peak_aggregate_replica_hbm_bytes=summary["peak_bytes"].get("replica_hbm", 0),
            peak_single_rank_replica_hbm_bytes=max(
                v for k, v in summary["peak_bytes"].items() if k.startswith("replica:hbm:")
            ),
            replica_hbm_byte_ns=integral["replica_hbm"],
            replica_dram_byte_ns=integral["replica_dram"],
            primary_hbm_byte_ns=integral["primary_hbm"],
        )
        rows.append(row)
        reconstructions.append(
            dict(
                id=job["id"],
                resource_transition_rows=len(resources),
                observed_admission_attempts=len(admissions),
                integral_byte_ns=dict(integral),
                resource_conservation=True,
                declared_foreground_fit=True,
            )
        )
        results[job["id"]] = summary
    # Independently check actual bytes even if the original frozen helper reused a marker.
    validation = out / "validation/observer-transparency"
    record = read(validation / "COMPLETE.json")
    bind(validation / "COMPLETE.json")
    job = next(j for j in jobs if j["id"] == "margin0-dma0.005-fixed4096-F1")
    marker = read(out / "runs" / job["id"] / "COMPLETE.json")
    assert record["status"] == "PASS" and not record["counts_as_experimental_sample"]
    for k in (
        "id",
        "job_sha256",
        "plan_sha256",
        "manifest_sha256",
        "profile_sha256",
        "predictor_sha256",
        "workload_sha256",
    ):
        assert record[k] == marker[k]
    for name in ("summary.json", "events.jsonl.gz", "flows.jsonl.gz"):
        bind(validation / name)
        a = (validation / name).read_bytes()
        b = (out / "runs" / job["id"] / name).read_bytes()
        if name.endswith(".gz"):
            a, b = gzip.decompress(a), gzip.decompress(b)
        assert a == b
        assert record["checks"][name] == dict(
            equal=True, decompressed_sha256=hashlib.sha256(a).hexdigest(), bytes=len(a)
        )
    assert record["checks"]["flows.jsonl.gz"]["bytes"] > 0
    # Restart controls must be reported even if a mismatch is found.
    restart = []
    for j in jobs:
        if j["variant"] != "none":
            continue
        path = original / "runs" / f"center-none-{j['fault']}" / "summary.json"
        old_marker = read(path.parent / "COMPLETE.json")
        bind(path.parent / "COMPLETE.json")
        bind(path, old_marker["artifact_sha256"]["summary.json"])
        before, after = read(path), results[j["id"]]
        restart.append(
            dict(
                id=j["id"],
                matches_original_requests=before["requests"] == after["requests"],
                matches_original_workflows=before["workflows"] == after["workflows"],
                matches_original_fault=before["failure"] == after["failure"],
                per_workflow_wct_difference_ns={
                    w: after["workflows"][w]["wct_ns"] - before["workflows"][w]["wct_ns"]
                    for w in before["workflows"]
                },
            )
        )
    # One row per condition/variant; target and cohort are never mixed.
    endpoints = []
    target = plan["protocol"]["failure"]["agent"].split("/")[0]
    for job in jobs:
        if job["fault"] != "F1":
            continue
        f0, f1 = results[job["f0_id"]], results[job["id"]]
        base0, base1 = (results[f"{job['condition']}-dram-{f}"] for f in ("F0", "F1"))
        delta = {
            w: f1["workflows"][w]["wct_ns"] - f0["workflows"][w]["wct_ns"] for w in f0["workflows"]
        }
        contrast = {
            w: delta[w] - (base1["workflows"][w]["wct_ns"] - base0["workflows"][w]["wct_ns"])
            for w in delta
        }
        recovery = next(
            r for r in f1["recoveries"] if r["agent"] == plan["protocol"]["failure"]["agent"]
        )
        endpoints.append(
            dict(
                condition=job["condition"],
                variant=job["variant"],
                margin_MiB=job["margin_MiB"],
                dma=job["dma"],
                target_delta_wct_ns=delta[target],
                cohort_sum_delta_wct_ns=sum(delta.values()),
                target_contrast_vs_dram_ns=contrast[target],
                cohort_sum_contrast_vs_dram_ns=sum(contrast.values()),
                workflows_worse_vs_dram=sum(v > 0 for v in contrast.values()),
                workflows_better_vs_dram=sum(v < 0 for v in contrast.values()),
                workflows_equal_vs_dram=sum(v == 0 for v in contrast.values()),
                healthy_mean_wct_difference_vs_none_ns=mean(
                    f0["workflows"][w]["wct_ns"]
                    - results[f"{job['condition']}-none-F0"]["workflows"][w]["wct_ns"]
                    for w in delta
                ),
                failure_time_ns=f1["failure"]["time_ns"],
                failed_workers=f1["failure"]["workers"],
                active_victims=[r["agent"] for r in f1["recoveries"]],
                queued_histories=[r["agent"] for r in f1["history_restores"]],
                retry_worker=recovery["retry_worker"],
                recovery_detection_ns=recovery["detection_ns"],
                recovery_queue_ns=recovery["queue_ns"],
                recovery_service_ns=recovery["service_ns"],
                recovery_latency_ns=recovery["latency_ns"],
            )
        )
    csv_write(out / "audited-bindings.csv", rows)
    csv_write(out / "audited-endpoints.csv", endpoints)
    (out / "RESTART_CONTROL.json").write_bytes(encoded(restart))
    (out / "MECHANISM_ENDPOINTS.json").write_bytes(encoded(mechanism))
    pressure = [r for r in rows if r["pressure_worker_rank_windows"]]
    waits = [r for r in rows if r["foreground_admission_wait_attempts"]]
    pressure_by_fault = {f: sum(r["fault"] == f for r in pressure) for f in ("F0", "F1")}
    waits_by_fault = {f: sum(r["fault"] == f for r in waits) for f in ("F0", "F1")}
    adaptive_fixed_matches = []
    for j in jobs:
        if j["variant"] == "adaptive":
            for fixed in ("fixed128", "fixed4096"):
                other_id = f"{j['condition']}-{fixed}-{j['fault']}"
                adaptive_fixed_matches.append(
                    dict(
                        adaptive=j["id"],
                        fixed=other_id,
                        exact_workflow_endpoints=(
                            results[j["id"]]["workflows"] == results[other_id]["workflows"]
                        ),
                    )
                )
    pressure_timing = []
    adaptive_md = []
    for row in mechanism:
        target_finish = results[row["id"]]["workflows"][target]["finish_ns"]
        for event in row["pressure_flag_control_entries"]:
            pressure_timing.append(
                dict(
                    id=row["id"],
                    pressure_control_ns=event["time_ns"],
                    target_finish_ns=target_finish,
                    pressure_after_target_finish=event["time_ns"] > target_finish,
                )
            )
        if "-adaptive-" in row["id"]:
            adaptive_md.extend(row["native_pressure_quota_events"])
    report = [
        "# Post-review O3 small-pool diagnostic",
        "",
        "All 72 predeclared runs completed. This is a constructed allocatable-pool boundary applied to the original four-workflow input once. It does not demonstrate production 80GB capacity pressure. The 52 exact invocations, human DAG, original order/arrivals, declared cap512, L11/K16 and logical fault16228 are preserved. The online predictor, role priors and guard use the separately sealed simulator-walltime model; pool and DMA coefficient are the predeclared sensitivities.",
        "",
        "Pool per rank = 5,039,327,808 B maximum declared foreground allocation (raw KV plus metadata) + 2GiB original reserve + 0/32/128MiB margin. Every invocation fits individually. Fixed32/128/4096 always use the same safe core reclaim and leases, reapplying their target at the next control window after capacity returns.",
        "",
        f"Observed pressure flags in **{len(pressure)}/72 runs**, and failed foreground-admission attempts in **{len(waits)}/72 runs**. A moving or zero ceiling alone is not proof of feedback pressure. "
        + (
            "This matrix therefore does not exercise the pressure feedback branch."
            if not pressure
            else "The pressure/control records identify which runs actually exercise the feedback input; endpoint benefit must still be assessed separately."
        ),
        "",
        f"Pressure splits by fault condition: **F0 {pressure_by_fault['F0']}/36; F1 {pressure_by_fault['F1']}/36**. "
        + (
            "No faulted run exhibits a control-entry pressure flag; this suite therefore does not demonstrate recovery under observed foreground-admission pressure or a recovery gain caused by pressure feedback."
            if not pressure_by_fault["F1"]
            else "Faulted-run pressure timing must be matched to failure and recovery events before assigning any recovery effect to pressure feedback."
        ),
        "",
        "## Pressure and memory diagnostics",
        "",
        "`audited-bindings.csv` uses corrected measurement names. `sticky_flag_after_attempt_observations` (the frozen raw table's `pressure_admission_attempts`) counts attempts ending while the worker flag is still true, including inherited flags until control clears them; it is not the number of new pressure triggers. `pressure_worker_rank_windows` counts the flag read at control entry (TP1 here). Native quota event fields distinguish pressure decreases, nonpressure ceiling decreases, and growth. `all_hot_release_abort_bytes` includes normal retirement/replacement and is not exclusively pressure-caused reclaim. Ordinary admission timestamps are measured; their wait is submit-to-successful-reservation, not the entire invocation latency.",
        "",
        "HBM/DRAM byte-time was independently integrated from recorded physical-ledger transitions and exactly matches all72 core summaries. Peak replica bytes and integral costs are retained, including partial/canceled transactions. Quota is a budget, not occupancy. MECHANISM_ENDPOINTS.json retains all72 runs' exact pressure-flag control/admission snapshots and native quota events, including empty sets. At a zero ceiling the pressure branch can reset stability while quota is already zero: this is not a measured nonzero multiplicative decrease.",
        "",
        "| Variant | Runs with pressure flags /12 | Runs with admission waits /12 | Native pressure quota decreases | Fixed target regrowth events |",
        "|---|---:|---:|---:|---:|",
    ]
    for variant in ("none", "dram", "fixed32", "fixed128", "fixed4096", "adaptive"):
        group = [r for r in rows if r["variant"] == variant]
        report.append(
            f"| {variant} | {sum(r['pressure_worker_rank_windows'] > 0 for r in group)} | {sum(r['foreground_admission_wait_attempts'] > 0 for r in group)} | {sum(r['native_quota_pressure_decrease_events'] for r in group)} | {sum(r['fixed_target_regrowth_events'] for r in group)} |"
        )
    for condition in ("margin0-dma0", "margin32-dma0"):
        m = next(r for r in mechanism if r["id"] == f"{condition}-adaptive-F0")
        times = [r["time_ns"] / 1e9 for r in m["pressure_flag_control_entries"]]
        f0, f1 = (results[f"{condition}-adaptive-{f}"] for f in ("F0", "F1"))
        report += [
            "",
            f"Timing check, {condition}/adaptive: F0 pressure control times {times} s, target Workflow finish {f0['workflows'][target]['finish_ns'] / 1e9:.9f} s; F1 failure {f1['failure']['time_ns'] / 1e9:.9f} s and target finish {f1['workflows'][target]['finish_ns'] / 1e9:.9f} s. These are separate runs, not a combined event chain.",
        ]
    report += [
        "",
        "## Paired workflow endpoints",
        "",
        "Contrast = (variant F1 - variant F0) - (DRAM F1 - DRAM F0), same Workflow ID. Negative is better. Target and all-four-workflow sums are separate. All zero and adverse cells remain. Healthy cost is mean F0 WCT minus Restart's same-condition mean F0 WCT. Ordinary FCFS competition remains; recovery improvement is not a WCT guarantee.",
        "",
        f"Adaptive versus fixed128/fixed4096 has exactly equal Workflow endpoints in {sum(r['exact_workflow_endpoints'] for r in adaptive_fixed_matches)}/24 comparisons (six conditions, both F0/F1, two comparators). This is a retained null difference, not evidence of adaptive superiority.",
        "",
        "| Condition | Variant | Target contrast vs DRAM (s) | Cohort sum contrast vs DRAM (s) | Worse/better/equal Workflows | Healthy mean cost vs Restart (s) |",
        "|---|---|---:|---:|---|---:|",
    ]
    for r in endpoints:
        report.append(
            f"| {r['condition']} | {r['variant']} | {r['target_contrast_vs_dram_ns'] / 1e9:.9f} | {r['cohort_sum_contrast_vs_dram_ns'] / 1e9:.9f} | {r['workflows_worse_vs_dram']}/{r['workflows_better_vs_dram']}/{r['workflows_equal_vs_dram']} | {r['healthy_mean_wct_difference_vs_none_ns'] / 1e9:.9f} |"
        )
    report += [
        "",
        "## Reproducibility and validity",
        "",
        f"Restart exactly matches original sensitivity-v2 request timestamps, Workflow endpoints and fault identity in {sum(r['matches_original_requests'] and r['matches_original_workflows'] and r['matches_original_fault'] for r in restart)}/12 controls. RESTART_CONTROL.json retains any mismatch rather than rejecting it. Failure wall/worker/co-victim differences across variants remain in the endpoint CSV; only logical target/progress is fixed by construction.",
        "",
        "The one extra observer-transparency validation uses fixed4096, margin0, DMA0.005, F1. Base and observed runtimes have byte-identical summaries and decompressed events/flows; the flow record is nonempty. It is a validation control, not a 73rd experiment. The independent audit rechecks actual files and all bindings, not merely its COMPLETE marker.",
        "",
        "The original frozen runner's existing-validation reuse gate was incomplete. RUNNER_INTERFACE_REPAIR.json records the live-only interface repair without overwriting the numerical source snapshot or rerunning formal samples. Use the live run_quota_pressure_campaign.py launcher, which verifies the existing validation before re-executing frozen sources. Direct old-snapshot replay must pass this independent audit before reused validation is accepted.",
        "",
        "Use audit_quota_pressure_campaign.py --out CAMPAIGN for this stdlib-only audit/report. It launches no DES. The single fault and four dependent Workflows, resource margins and uncalibrated DMA factors are paired conditions, not independent population samples; no CI or physical calibration claim is made. Each Agent has one invocation; this suite adds no evidence about idle histories or repeated invocations. The trained walltime target is simulator submission-to-Agent-completion time. These results do not establish a production controller guarantee or a numerical native-attention recovery implementation.",
    ]
    (out / "RESULTS.md").write_text("\n".join(report) + "\n")
    candidate = (
        "We evaluate a post-hoc small-pool O3 diagnostic using the original four-workflow input "
        "and frozen online walltime predictor, role priors, and guard. The allocatable pool equals "
        "the maximum declared foreground allocation, including metadata, plus the 2 GiB reserve "
        "and a 0/32/128 MiB margin; every invocation fits. Seventy-two runs cross DMA factors "
        "0/0.005 and F0/F1 with Restart, DRAM, fixed 32/128/4096 MiB targets, and adaptive quotas. "
        "Unlike the earlier downward-clamped static variant, fixed targets regrow each control "
        "window within the live ceiling. Pressure occurs in 12/36 F0 runs and no F1 runs, without "
        "capacity-denied admissions. At 32 MiB margin, adaptive quotas decrease from 32 to 24 MiB; "
        "pressure nevertheless occurs after the target workflow finishes. Adaptive and fixed "
        "128/4096 MiB have identical workflow endpoints, improving target delta-WCT over DRAM by "
        "1.444 ms. All protected variants add 28.840 ms mean healthy WCT at DMA=0.005. These null "
        "differences neither attribute recovery gains to AIMD nor establish recovery under "
        "pressure. This constructed boundary does not demonstrate production 80 GB capacity pressure."
    )
    assert pressure_by_fault == {"F0": 12, "F1": 0} and not waits
    assert len(pressure_timing) == 12 and all(
        r["pressure_after_target_finish"] for r in pressure_timing
    )
    assert len(adaptive_md) == 2
    assert all((e["before"], e["after"]) == (33554432, 25165824) for e in adaptive_md)
    assert all(r["exact_workflow_endpoints"] for r in adaptive_fixed_matches)
    assert {
        r["target_contrast_vs_dram_ns"]
        for r in endpoints
        if r["variant"] in {"adaptive", "fixed128", "fixed4096"}
    } == {-1_443_871}
    assert {
        r["healthy_mean_wct_difference_vs_none_ns"]
        for r in endpoints
        if r["dma"] == 0.005 and r["variant"] != "none"
    } == {28_839_775.5}
    word_count = len(candidate.split())
    assert 130 <= word_count <= 180
    (out / "PAPER_CANDIDATE.md").write_text(
        "# Candidate Evaluation paragraph\n\nNOT APPLIED. "
        + str(word_count)
        + " whitespace-delimited words; all numbers bound by INDEPENDENT_ACCOUNTING_AUDIT.json.\n\n"
        + candidate
        + "\n\nEvidence: audited-bindings.csv, audited-endpoints.csv, MECHANISM_ENDPOINTS.json, "
        "and all 24 adaptive/fixed endpoint comparisons in the independent audit. The 1.444 ms "
        "is the rounded 1.443871 ms paired target improvement; 28.840 ms is rounded from "
        "28.8397755 ms. The paper has not been edited.\n"
    )
    bind(out / "RUNNER_INTERFACE_REPAIR.json")
    for name in ("check_reuse_gate.py", "REUSE_GATE_TESTS.json"):
        bind(out / "validation" / name)
    reuse_tests = read(out / "validation/REUSE_GATE_TESTS.json")
    assert reuse_tests["status"] == "PASS" and reuse_tests["DES_runs"] == 0
    assert reuse_tests["test_source_sha256"] == sha(out / "validation/check_reuse_gate.py")
    assert (
        reuse_tests["tested_live_runner_sha256"]
        == read(out / "RUNNER_INTERFACE_REPAIR.json")["safe_live_launcher_sha256"]
    )
    for name, value in sources.items():
        path = out / name if (out / name).exists() else ROOT / name
        assert sha(path) == value, name
    outputs = (
        "audited-bindings.csv",
        "audited-endpoints.csv",
        "RESTART_CONTROL.json",
        "MECHANISM_ENDPOINTS.json",
        "PAPER_CANDIDATE.md",
        "RESULTS.md",
    )
    audit = dict(
        status="PASS",
        complete=True,
        verified_runs=72,
        verified_original_invocations=52,
        logical_fault_tokens=16228,
        per_run_resource_reconstruction=reconstructions,
        extra_DES_runs_from_this_auditor=0,
        observer_transparency_rechecked_from_actual_bytes=True,
        observer_transparency_nonempty_flows=True,
        restart_controls=restart,
        pressure_flag_runs=len(pressure),
        pressure_flag_runs_by_fault=pressure_by_fault,
        admission_wait_runs=len(waits),
        admission_wait_runs_by_fault=waits_by_fault,
        adaptive_fixed_workflow_endpoint_comparisons=adaptive_fixed_matches,
        pressure_timing_vs_target_finish=pressure_timing,
        adaptive_pressure_quota_decreases=adaptive_md,
        candidate_english_word_count=word_count,
        input_source_result_sha256=sources,
        outputs_sha256={n: sha(out / n) for n in outputs},
        auditor_sha256=sha(Path(__file__).resolve()),
    )
    (out / "INDEPENDENT_ACCOUNTING_AUDIT.json").write_bytes(encoded(audit))
    print(
        json.dumps(
            {
                k: v
                for k, v in audit.items()
                if k
                not in {
                    "input_source_result_sha256",
                    "per_run_resource_reconstruction",
                    "restart_controls",
                    "adaptive_fixed_workflow_endpoint_comparisons",
                    "pressure_timing_vs_target_finish",
                    "adaptive_pressure_quota_decreases",
                }
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
