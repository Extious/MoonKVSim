"""Report every condition and two explicitly descriptive adverse-case reconstructions."""

import csv
import gzip
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
REPORTS = OUT / "reports"
REPORTS.mkdir(exist_ok=True)


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rows(p):
    with p.open() as stream:
        return list(csv.DictReader(stream))


def write_csv(path, data):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)


plan = read(OUT / "PLAN.json")
audit = read(OUT / "TRACE_MECHANISM_AUDIT.json")
assert audit["all_passed"] and audit["recovery_event_count"] == 108
assert audit["queued_history_restore_event_count"] == 279
assert len(audit["eos_full_restore_exposure_checks"]) == 258
assert audit["eos_before_full_restore_count"] == audit["eos_canceled_prefetch_count"] == 0
case_records = []
call_records = []
workflow_records = []
source_hashes = {}
headlines = rows(OUT / "figures/wct-endpoint-comparisons.csv")
recovery_rows = [
    row for row in rows(OUT / "recovery-events.csv") if row["primary_target_agent"] == "True"
]
assert len(recovery_rows) == 90
write_csv(OUT / "paper-target-recovery-per-seed.csv", recovery_rows)
for scenario, fault in [("history_reuse", "left.prefill"), ("long_decode_drift", "left.decode")]:
    summaries = {}
    healthy = {}
    gates = {}
    calls = {}
    recoveries = {}
    workload_id = f"{scenario}-n8-s19"
    specs = json.loads(gzip.decompress((OUT / plan["workloads"][workload_id]["path"]).read_bytes()))
    join_spec = next(a for a in specs if a["workflow"] == "wf0000" and a["name"] == "join")
    assert join_spec["predecessors"] == ["left", "right"]
    for policy in ("none", "dram", "aegiskv"):
        path = OUT / "runs" / f"{workload_id}-{policy}-{fault}" / "summary.json"
        normal = OUT / "runs" / f"{workload_id}-{policy}-F0" / "summary.json"
        summaries[policy] = read(path)
        healthy[policy] = read(normal)
        for file in (path, normal):
            source_hashes[str(file.relative_to(OUT))] = sha(file)
        s = summaries[policy]
        target = s["failure"]["agent"].split("/")[0]
        selected = [r for r in s["requests"] if r["agent"].startswith(target + "/")]
        calls[policy] = {(r["agent"].split("/")[1], r["invocation"]): r for r in selected}
        ends = {
            name: max(r["finish_ns"] for r in selected if r["agent"] == target + "/" + name)
            for name in join_spec["predecessors"]
        }
        gates[policy] = max(ends, key=ends.get)
        assert calls[policy]["join", 0]["submit_ns"] == max(ends.values())
        assert calls[policy]["join", 0]["finish_ns"] == s["workflows"][target]["finish_ns"]
        recoveries[policy] = next(r for r in s["recoveries"] if r["agent"] == s["failure"]["agent"])
        assert recoveries[policy]["latency_ns"] == sum(
            recoveries[policy][k] for k in ("detection_ns", "queue_ns", "service_ns")
        )
        for r in selected:
            call_records.append(dict(scenario=scenario, fault=fault, seed=19, policy=policy, **r))
        for wf, info in s["workflows"].items():
            delta = info["wct_ns"] - healthy[policy]["workflows"][wf]["wct_ns"]
            workflow_records.append(
                dict(
                    scenario=scenario,
                    fault=fault,
                    seed=19,
                    policy=policy,
                    workflow=wf,
                    f0_wct_ns=healthy[policy]["workflows"][wf]["wct_ns"],
                    f1_wct_ns=info["wct_ns"],
                    paired_delta_ns=delta,
                )
            )
    a, b = summaries["none"], summaries["dram"]
    target = a["failure"]["agent"].split("/")[0]
    assert set(gates.values()) == {"left"}
    assert all(
        [row["agent"] for row in s["recoveries"]] == [s["failure"]["agent"]]
        for s in summaries.values()
    )
    assert all(s["failure"] == a["failure"] for s in summaries.values())
    assert all(
        {wf: x["wct_ns"] for wf, x in healthy[p]["workflows"].items()}
        == {wf: x["wct_ns"] for wf, x in healthy["none"]["workflows"].items()}
        for p in healthy
    )
    perwf = {
        wf: b["workflows"][wf]["wct_ns"] - a["workflows"][wf]["wct_ns"] for wf in a["workflows"]
    }
    target_change = perwf[target]
    join_submit = calls["dram"]["join", 0]["submit_ns"] - calls["none"]["join", 0]["submit_ns"]
    join_latency = calls["dram"]["join", 0]["latency_ns"] - calls["none"]["join", 0]["latency_ns"]
    assert target_change == join_submit + join_latency
    record = dict(
        scenario=scenario,
        fault=fault,
        seed=19,
        target_workflow=target,
        failure=a["failure"],
        same_failure_identity_wall_and_workers=True,
        healthy_wct_equal_across_policies=True,
        active_agents={p: [r["agent"] for r in s["recoveries"]] for p, s in summaries.items()},
        queued_history_agents={
            p: [r["agent"] for r in s["history_restores"]] for p, s in summaries.items()
        },
        primary_recovery_by_policy=recoveries,
        join_gating_agent_by_policy=gates,
        target_dram_minus_restart_ns=target_change,
        all_workflow_sum_dram_minus_restart_ns=sum(perwf.values()),
        all_workflow_mean_dram_minus_restart_s=sum(perwf.values()) / 8e9,
        other_seven_workflow_sum_dram_minus_restart_ns=sum(perwf.values()) - target_change,
        join_submit_dram_minus_restart_ns=join_submit,
        join_latency_dram_minus_restart_ns=join_latency,
        target_endpoint_decomposition_exact=True,
        primary_recovery_total_dram_minus_restart_ns=recoveries["dram"]["latency_ns"]
        - recoveries["none"]["latency_ns"],
        ordinary_admission_timestamps_available=False,
        limits="Observed completion/dependency/routing association. Ordinary request latency is not measured queue wait; no per-request admission timestamps or full event logs for these selected summary-only cases.",
    )
    if scenario == "history_reuse":
        d = calls["dram"]["left", 2]
        n = calls["none"]["left", 2]
        record["left_final_submit_dram_minus_restart_ns"] = d["submit_ns"] - n["submit_ns"]
        record["left_final_latency_dram_minus_restart_ns"] = d["latency_ns"] - n["latency_ns"]
        assert (
            join_submit
            == record["left_final_submit_dram_minus_restart_ns"]
            + record["left_final_latency_dram_minus_restart_ns"]
        )
        record["right_final_worker_none_dram"] = [
            calls[p]["right", 2]["worker"] for p in ("none", "dram")
        ]
        record["join_worker_none_dram"] = [calls[p]["join", 0]["worker"] for p in ("none", "dram")]
    case_records.append(record)
write_csv(REPORTS / "negative-case-calls.csv", call_records)
write_csv(REPORTS / "negative-case-workflows.csv", workflow_records)
(REPORTS / "negative-case-attribution.json").write_text(
    json.dumps(
        dict(
            cases=case_records,
            source_sha256=source_hashes,
            script_sha256=sha(Path(__file__)),
            interpretation="Two post-analysis explanatory cases, not additional experiments or selected headline samples; all ten conditions and all seeds remain reported.",
        ),
        indent=2,
        sort_keys=True,
    )
    + "\n"
)
lines = [
    "# Corrected structural Evaluation numbers (v2)",
    "",
    "All 135 fixed conditions completed on checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1. Independent source/input/event/resource checks, integer-timestamp figure-endpoint checks, and 178 mm color/grayscale figure review passed. There are 90 F1/F0 pairs and 720 same-ID workflow deltas. Source application and INPUT_MATCH.json bind the fresh implementation; these corrected conditions replace the historical version and are not extra statistical samples.",
    "",
    "Each workflow delta is its F1 WCT minus the same-policy F0 WCT. The target view uses the directly faulted workflow. The all-workflow view averages all eight paired deltas within each run before summarizing three constructed seeds. Tables give equal-seed means in seconds. DRAM gain = Restart delta minus DRAM delta; a negative gain is adverse. These are descriptive three-seed results, not confidence intervals or population-tail estimates.",
    "",
]
for endpoint, title in [
    ("target_workflow", "Target workflow"),
    ("all_workflow_mean", "All eight workflows, mean within each run"),
]:
    lines += [
        "## " + title,
        "",
        "| Scenario | Fault | Restart ΔWCT (s) | DRAM ΔWCT (s) | AegisKV ΔWCT (s) | DRAM gain vs Restart (s) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for r in headlines:
        if r["endpoint"] == endpoint:
            lines.append(
                f"| {r['scenario']} | {r['fault']} | {float(r['none_mean_delta_s']):.6f} | {float(r['dram_mean_delta_s']):.6f} | {float(r['aegiskv_mean_delta_s']):.6f} | {float(r['dram_vs_restart_mean_gain_s']):.6f} |"
            )
    lines.append("")
lines += [
    "Exact means and seed min/max are in figures/wct-endpoint-comparisons.csv; all 90 seed/run points are in figures/wct-endpoints-per-run.csv. AegisKV minus DRAM incremental benefit is small: target mean gains range from 0.000147 to 0.874737 ms, and all-workflow mean gains from 0.00009025 to 1.705603 ms. The long-drift sub-microsecond differences do not establish useful native-sparse HBM recovery benefit.",
    "",
    "## Per-seed recovery and two adverse examples",
    "",
    "paper-target-recovery-per-seed.csv retains detection, retry queue and admitted recovery service separately for all 90 primary-target observations, along with actual failure/admission/first-output times. The examples below use single seeds and matched policies; they do not concatenate mean component changes into a fictional run. Selected ordinary requests have submit/finish/worker records but no ordinary admission timestamp, so their latency differences cannot be relabelled queue differences.",
    "",
]
for case in case_records:
    lines += [
        f"### {case['scenario']} / {case['fault']} / seed 19",
        "",
        f"The exact same wf0000/left invocation 1 fails at logical token {case['failure']['logical_tokens']:,}, wall {case['failure']['time_ns'] / 1e9:.9f} s on worker 0. Only this Agent is actively interrupted; queued-history restorations are separately listed in reports/negative-case-attribution.json. Healthy workflow WCTs are equal across policies.",
        "",
        "| Policy | Detection (s) | Retry queue (s) | Recovery service (s) | Total to first new token (s) | CP tokens |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for policy in ("none", "dram", "aegiskv"):
        r = case["primary_recovery_by_policy"][policy]
        lines.append(
            f"| {policy} | {r['detection_ns'] / 1e9:.9f} | {r['queue_ns'] / 1e9:.9f} | {r['service_ns'] / 1e9:.9f} | {r['latency_ns'] / 1e9:.9f} | {r['checkpoint_tokens']} |"
        )
    lines += [
        "",
        f"DRAM changes target WCT by **{case['target_dram_minus_restart_ns'] / 1e9:+.9f} s**, while changing the all-eight-workflow mean by **{case['all_workflow_mean_dram_minus_restart_s']:+.9f} s**. The final left invocation gates join under every policy. Join submission changes by {case['join_submit_dram_minus_restart_ns'] / 1e9:+.9f} s and join's observed call latency changes by {case['join_latency_dram_minus_restart_ns'] / 1e9:+.9f} s; these add exactly to the target WCT change. The other seven workflows' total change is {case['other_seven_workflow_sum_dram_minus_restart_ns'] / 1e9:+.9f} s.",
        "",
    ]
    if case["scenario"] == "history_reuse":
        lines += [
            "The primary recovery is 0.525124161 s faster with DRAM, with identical retry queue and worker 1. Its completion submits the final left call 0.525124161 s earlier, but that call lasts 26.173781742 s longer; hence left completion/join submission is 25.648657581 s later. Join then lasts another 17.680999920 s longer, producing the 43.329657501 s adverse target endpoint. The right final call changes worker 3→1 and join changes worker 2→1. This is a recorded placement/timing association, not a measured 26.17 s or 17.68 s ordinary queue attribution. Other workflows improve enough that the all-workflow mean improves by 4.810122646 s; the two endpoints therefore have opposite signs in this same run.",
            "",
        ]
    else:
        lines += [
            "DRAM primary recovery is 1.958738051 s faster with the same 27.807920941 s retry queue and worker 3. Left completion and join submission are correspondingly 1.958738051 s earlier. Join stays on worker 3 but its observed call latency increases by 51.659751681 s, so target WCT worsens by 49.701013630 s. The all-workflow mean also worsens, by 15.335425873 s. The saved summaries support this exact dependency/timestamp decomposition but not an ordinary admission-queue or interference decomposition; no extra simulation was run to obtain missing events.",
            "",
        ]
lines += [
    "## Version and model limits",
    "",
    "All 360 healthy workflow WCTs remain identical across versions. Fault wall times, workers and active-victim Agent sets remain identical, but 210/240 Restart failed-workflow WCTs change because queued-history recovery semantics also changed; the combined revision is not solely a checkpoint-selector correction. The corrected matrix contains 108 active recovery events and 279 separately classified queued-history restores. All 258 protected recovery records finish full restore before request EOS; no EOS-canceled prefetch occurs in this matrix. There are 11 negative same-policy paired workflow deltas (historical: 1), all retained. See VERSION_COMPARISON.json and the independently produced ../reviews/v1-v2-comparison/ artifacts.",
    "",
    "Every workload is an explicitly constructed four-Agent DAG with prescribed arrivals and multi-invocation token histories, executed once. Fixed role priors do not validate remaining-time prediction accuracy. The long-drift provider is constructed and K16 holds both four-block banks; compute uses the dense Qwen3-8B TP1 AIC profile, DP4, L4. No native-sparse WCT, physical inference, continuous batching, measured controller latency, or measured DMA/compute interference is claimed. Historical 8/32/128 simulator execution-cost results remain separately identified under structural-campaign-v1 and are not pooled with this revised implementation.",
]
(OUT / "PAPER_NUMBERS_V2.md").write_text("\n".join(lines) + "\n")
print(
    "PAPER_NUMBERS_V2.md, 90 primary recovery observations, and two case reconstructions written."
)
