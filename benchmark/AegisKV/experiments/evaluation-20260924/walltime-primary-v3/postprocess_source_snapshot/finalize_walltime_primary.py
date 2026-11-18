"""Gated v3 paper-data/figure export; never executes or alters the simulator."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean

MODELS = ("Qwen3-8B", "Qwen3-32B")
LOADS = (0.3, 0.65, 0.9)
POLICIES = ("none", "all_dram", "dram", "static_hbm", "aegiskv")


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def csv_rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def csv_write(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def mean_seconds(rows, field):
    return sum(int(r[field]) for r in rows) / (len(rows) * 1_000_000_000)


def bindings(out):
    manifest, priors = read(out / "MANIFEST.json"), read(out / "PRIORS.json")
    amendment_dir = out / "execution-amendment-16workers"
    amendment = amendment_dir / "AMENDMENT.json"
    execution = None
    if amendment.exists():
        record = read(amendment)
        assert record["original_protocol_seal_sha256"] == sha(out / "PROTOCOL_SEAL.json")
        assert record["stopped_state_sha256"] == sha(amendment_dir / "STOPPED_STATE.json")
        execution = dict(
            path=str(amendment.relative_to(out)),
            sha256=sha(amendment),
            stopped_state_sha256=sha(amendment_dir / "STOPPED_STATE.json"),
            original_workers=record["original_workers"],
            amended_workers=record["workers"],
            numerical_inputs_unchanged=True,
            host_wall_seconds_comparable=False,
            boundary=record["wall_clock_reporting"],
        )
    return dict(
        manifest_sha256=sha(out / "MANIFEST.json"),
        plan_sha256=sha(out / "PLAN.json"),
        protocol_seal_sha256=sha(out / "PROTOCOL_SEAL.json"),
        priors_sha256=sha(out / "PRIORS.json"),
        predictor_sha256=manifest["predictor_sha256"],
        guard_ns={m: priors[m]["slack_guard_ns"] for m in MODELS},
        intervention=(
            "joint final hashed-text walltime regressor + train12 role priors "
            "+ train-only LOOWF guard"
        ),
        original_method="causal current-prompt plus training-role-output service proxy",
        unchanged=(
            "original core/profile/workload arrivals/fault identities/L/K/hardware; "
            "no other numerical input change"
        ),
        evidence=(
            "modeled FCFS and fixed batch-one AIC profile; "
            "not physical execution or semantic-encoder validation"
        ),
        executor_amendment=execution,
    )


def prediction_table(out):
    assert read(out / "HELDOUT_INDEPENDENT_AUDIT.json")["status"] == "PASS"
    result = read(out / "HELDOUT_ERROR.json")
    target = out / "paper-summary"
    target.mkdir(exist_ok=True)
    rows = []
    for model in MODELS:
        for load in LOADS:
            metric = result["models"][model]["by_load"][str(load)]
            rows.append(
                dict(
                    model=model,
                    nominal_load=load,
                    observations=metric["observations"],
                    workflows=metric["workflows"],
                    mae_s=metric["mae_ns"] / 1e9,
                    bias_s=metric["bias_ns"] / 1e9,
                    p90_absolute_error_s=metric["p90_absolute_error_ns"] / 1e9,
                    role_median_mae_s=metric["role_median_mae_ns"] / 1e9,
                    workflow_macro_mae_s=metric["workflow_macro_mae_ns"] / 1e9,
                )
            )
    csv_write(target / "healthy-predictor-error.csv", rows)
    write(
        target / "PREDICTOR_TABLE_PROVENANCE.json",
        dict(
            status="PASS",
            **bindings(out),
            source_sha256={
                "HELDOUT_ERROR.json": sha(out / "HELDOUT_ERROR.json"),
                "HELDOUT_INDEPENDENT_AUDIT.json": sha(out / "HELDOUT_INDEPENDENT_AUDIT.json"),
            },
            output_sha256=sha(target / "healthy-predictor-error.csv"),
            sampling=(
                "62 heldout workflows,503Agent tasks,3loads/model; rows dependent and no retuning"
            ),
        ),
    )
    return rows


def completed_gate(out):
    needed = ("AUDIT.json", "endpoints/PROVENANCE.json", "endpoints/WALLTIME_MODEL_PROVENANCE.json")
    if not all((out / name).exists() for name in needed):
        return False
    try:
        audit, endpoint = read(out / needed[0]), read(out / needed[1])
        deployment = read(out / needed[2])
        status = read(out / "STATUS.json")
    except (json.JSONDecodeError, FileNotFoundError):
        return False
    if audit["status"] != "PASS":
        return False
    assert audit["verified_runs"] == 180 and endpoint["source_summary_count"] == 180
    assert endpoint["status"] == "PASS" and endpoint["fault_rows"] == 150
    if not status["complete"]:
        return False
    assert deployment["predictor_sha256"] == read(out / "MANIFEST.json")["predictor_sha256"]
    assert deployment["protocol_seal_sha256"] == sha(out / "PROTOCOL_SEAL.json")
    assert deployment["plan_sha256"] == sha(out / "PLAN.json")
    assert deployment["endpoint_provenance_sha256"] == sha(out / "endpoints/PROVENANCE.json")
    for name, expected in endpoint["source_sha256"].items():
        assert sha(out / name) == expected
    for name, expected in endpoint["output_sha256"].items():
        assert sha(out / "endpoints" / name) == expected
    return True


def paper_data(out):
    assert completed_gate(out)
    target = out / "paper-summary"
    plan = read(out / "PLAN.json")
    rows = csv_rows(out / "endpoints/per-identity.csv")
    grouped, index = defaultdict(list), {}
    for row in rows:
        key = row["model"], float(row["nominal_load"]), row["policy"]
        grouped[key].append(row)
        index[*key, int(row["fault_index"])] = row
    assert len(index) == 150
    cells = []
    for (model, load, policy), values in sorted(grouped.items()):
        assert len(values) == 5
        latency = mean(int(r["failure_to_first_new_token_ns"]) for r in values)
        queue = mean(int(r["retry_queue_ns"]) for r in values)
        service = mean(int(r["recovery_service_ns"]) for r in values)
        assert all(
            int(r["failure_to_first_new_token_ns"])
            == int(r["detection_ns"]) + int(r["retry_queue_ns"]) + int(r["recovery_service_ns"])
            for r in values
        )
        cells.append(
            dict(
                model=model,
                nominal_load=load,
                policy=policy,
                fixed_identities=5,
                target_delta_mean_s=mean_seconds(values, "target_delta_wct_ns"),
                target_delta_min_s=min(int(r["target_delta_wct_ns"]) for r in values) / 1e9,
                target_delta_max_s=max(int(r["target_delta_wct_ns"]) for r in values) / 1e9,
                cohort_mean_delta_s=mean(float(r["all_workflow_mean_delta_ns"]) for r in values)
                / 1e9,
                failure_to_first_new_mean_s=mean_seconds(values, "failure_to_first_new_token_ns"),
                detection_mean_s=mean_seconds(values, "detection_ns"),
                retry_queue_mean_s=mean_seconds(values, "retry_queue_ns"),
                recovery_service_mean_s=mean_seconds(values, "recovery_service_ns"),
                retry_queue_share=queue / latency,
                recovery_service_share=service / latency,
            )
        )
    csv_write(target / "cell-summary.csv", cells)
    cell = {(r["model"], r["nominal_load"], r["policy"]): r for r in cells}
    table = []
    for model in MODELS:
        for load in LOADS:
            restart, dram, aegis = [
                cell[model, load, policy] for policy in ("none", "dram", "aegiskv")
            ]
            table.append(
                dict(
                    model=model,
                    nominal_load=load,
                    fixed_identities=5,
                    restart_seconds=restart["failure_to_first_new_mean_s"],
                    dram_seconds=dram["failure_to_first_new_mean_s"],
                    aegiskv_seconds=aegis["failure_to_first_new_mean_s"],
                    hbm_gain_ms=sum(
                        int(index[model, load, "dram", fault]["failure_to_first_new_token_ns"])
                        - int(index[model, load, "aegiskv", fault]["failure_to_first_new_token_ns"])
                        for fault in range(5)
                    )
                    / 5_000_000,
                )
            )
    csv_write(target / "agent-latency.csv", table)
    tex = [
        r"% v3; mean of five fixed fault identities, not independent trials.",
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Model & $\rho$ & Restart (s) & DRAM (s) & HBM gain (ms) \\",
        r"\midrule",
    ]
    for row in table:
        tex.append(
            f"{row['model'].replace('Qwen3-', '')} & {row['nominal_load']:g} & "
            f"{row['restart_seconds']:.3f} & {row['dram_seconds']:.3f} & "
            f"{row['hbm_gain_ms']:.3f} " + r"\\"
        )
    tex += [
        r"\bottomrule",
        r"\end{tabular}",
        "% HBM gain = DRAM minus AegisKV; positive is better.",
    ]
    (target / "agent-latency-single-column.tex").write_text("\n".join(tex) + "\n")
    summaries = {j["id"]: read(out / "runs" / j["id"] / "summary.json") for j in plan["jobs"]}
    byte_rows, static_rows, comparisons, workflow_pairs = [], [], [], []
    for model in MODELS:
        for load in LOADS:
            for suffix in ("F0", *[f"F1-{i}" for i in range(5)]):
                names = {policy: f"{model}-load{load:g}-{policy}-{suffix}" for policy in POLICIES}
                sample = dict(model=model, nominal_load=load, condition=suffix)
                for policy in ("all_dram", "dram"):
                    metric = summaries[names[policy]]["metrics"]
                    for kind in ("checkpoint", "hot", "restore"):
                        sample[f"{policy}_{kind}_bytes"] = metric.get(f"{kind}_bytes", 0)
                    sample[f"{policy}_canceled_transferred_bytes"] = metric.get(
                        "canceled_copy_transferred_bytes", 0
                    )
                    sample[f"{policy}_total_transferred_bytes"] = (
                        sum(
                            sample[f"{policy}_{kind}_bytes"]
                            for kind in ("checkpoint", "hot", "restore")
                        )
                        + sample[f"{policy}_canceled_transferred_bytes"]
                    )
                byte_rows.append(sample)
                static, aegis = summaries[names["static_hbm"]], summaries[names["aegiskv"]]
                assert static["workflows"].keys() == aegis["workflows"].keys()
                for workflow in sorted(static["workflows"]):
                    s, a = static["workflows"][workflow], aegis["workflows"][workflow]
                    static_rows.append(
                        dict(
                            model=model,
                            nominal_load=load,
                            condition=suffix,
                            workflow=workflow,
                            static_wct_ns=s["wct_ns"],
                            aegiskv_wct_ns=a["wct_ns"],
                            static_minus_aegiskv_wct_ns=s["wct_ns"] - a["wct_ns"],
                            entire_workflow_record_equal=s == a,
                        )
                    )
            for fault in range(5):
                for baseline, method in (
                    ("none", "dram"),
                    ("dram", "aegiskv"),
                    ("all_dram", "dram"),
                    ("static_hbm", "aegiskv"),
                ):
                    a, b = index[model, load, baseline, fault], index[model, load, method, fault]
                    assert a["target_agent"] == b["target_agent"]
                    target_gain = int(a["target_delta_wct_ns"]) - int(b["target_delta_wct_ns"])
                    per_policy = {}
                    for policy in (baseline, method):
                        failed = summaries[f"{model}-load{load:g}-{policy}-F1-{fault}"]
                        healthy = summaries[f"{model}-load{load:g}-{policy}-F0"]
                        per_policy[policy] = {
                            w: failed["workflows"][w]["wct_ns"] - state["wct_ns"]
                            for w, state in healthy["workflows"].items()
                        }
                    assert per_policy[baseline].keys() == per_policy[method].keys()
                    for workflow in sorted(per_policy[baseline]):
                        workflow_pairs.append(
                            dict(
                                model=model,
                                nominal_load=load,
                                fault_index=fault,
                                baseline=baseline,
                                method=method,
                                workflow=workflow,
                                baseline_delta_wct_ns=per_policy[baseline][workflow],
                                method_delta_wct_ns=per_policy[method][workflow],
                                gain_ns=per_policy[baseline][workflow]
                                - per_policy[method][workflow],
                            )
                        )
                    cohort_sum = sum(per_policy[baseline].values()) - sum(
                        per_policy[method].values()
                    )
                    cohort_gain = cohort_sum / len(per_policy[baseline])
                    agent_gain = int(a["failure_to_first_new_token_ns"]) - int(
                        b["failure_to_first_new_token_ns"]
                    )
                    comparisons.append(
                        dict(
                            model=model,
                            nominal_load=load,
                            fault_index=fault,
                            baseline=baseline,
                            method=method,
                            target_agent=a["target_agent"],
                            target_dag_position=a["target_dag_position"],
                            target_wct_gain_ns=target_gain,
                            cohort_mean_wct_gain_ns=cohort_gain,
                            cohort_sum_wct_gain_ns=cohort_sum,
                            cohort_workflows=len(per_policy[baseline]),
                            agent_first_new_gain_ns=agent_gain,
                            target_cohort_sign_reversal=target_gain * cohort_gain < 0,
                            target_agent_sign_reversal=target_gain * agent_gain < 0,
                        )
                    )
    csv_write(target / "all-dram-byte-comparison.csv", byte_rows)
    csv_write(target / "static-aegis-all-workflows.csv", static_rows)
    csv_write(target / "policy-comparisons-per-identity.csv", comparisons)
    csv_write(target / "paired-workflows.csv", workflow_pairs)
    assert len(static_rows) == 2232 and len(comparisons) == 120 and len(workflow_pairs) == 7440
    extremes = {}
    for baseline, method in (
        ("none", "dram"),
        ("dram", "aegiskv"),
        ("all_dram", "dram"),
        ("static_hbm", "aegiskv"),
    ):
        selected = [r for r in comparisons if (r["baseline"], r["method"]) == (baseline, method)]
        extrema = {}
        for metric in ("target_wct_gain_ns", "cohort_mean_wct_gain_ns", "agent_first_new_gain_ns"):
            extrema[metric] = dict(
                minimum=min(r[metric] for r in selected),
                maximum=max(r[metric] for r in selected),
                negative_cases=[r for r in selected if r[metric] < 0],
                minimum_cases=[
                    r for r in selected if r[metric] == min(x[metric] for x in selected)
                ],
                maximum_cases=[
                    r for r in selected if r[metric] == max(x[metric] for x in selected)
                ],
            )
        extremes[f"{baseline}-minus-{method}"] = extrema
        paired = [r for r in workflow_pairs if (r["baseline"], r["method"]) == (baseline, method)]
        minimum, maximum = min(r["gain_ns"] for r in paired), max(r["gain_ns"] for r in paired)
        extrema["individual_workflow_gain_ns"] = dict(
            pairs=len(paired),
            negative_pairs=sum(r["gain_ns"] < 0 for r in paired),
            zero_pairs=sum(r["gain_ns"] == 0 for r in paired),
            positive_pairs=sum(r["gain_ns"] > 0 for r in paired),
            minimum=minimum,
            maximum=maximum,
            minimum_cases=[r for r in paired if r["gain_ns"] == minimum],
            maximum_cases=[r for r in paired if r["gain_ns"] == maximum],
            complete_signed_data="paired-workflows.csv",
        )
    write(target / "EXTREMES_AND_NEGATIVE_CASES.json", extremes)
    write(
        target / "STATIC_AEGIS_COMPARISON.json",
        dict(
            conditions=36,
            workflow_pairs=len(static_rows),
            equal_wct_pairs=sum(r["static_minus_aegiskv_wct_ns"] == 0 for r in static_rows),
            all_wct_equal=all(r["static_minus_aegiskv_wct_ns"] == 0 for r in static_rows),
            entire_record_equal_pairs=sum(r["entire_workflow_record_equal"] for r in static_rows),
            interpretation=(
                "descriptive equality at tested inputs only; no general equivalence claim"
            ),
        ),
    )
    shutil.copyfile(out / "endpoints/stratified-summary.csv", target / "sink-nonsink-summary.csv")
    shutil.copyfile(out / "endpoints/per-identity.csv", target / "per-identity.csv")
    note = [
        "# Wall-time-trained primary v3: descriptive paper data",
        "",
        "All 180 conditions passed the independent artifact/resource audit. This is a new",
        "joint predictor/prior/guard intervention, with unchanged core, L/K, arrivals and",
        "profiles. It does not retroactively change the service-proxy v2 results.",
        "",
        "Each primary cell averages five fixed identities. Workflows within a run share",
        "queues; there are no population confidence intervals or independent-repeat claims.",
        "",
        "| Model | Load | Restart total (s) | DRAM total (s) | HBM gain (ms) |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in table:
        note.append(
            f"| {row['model']} | {row['nominal_load']} | {row['restart_seconds']:.6f} | "
            f"{row['dram_seconds']:.6f} | {row['hbm_gain_ms']:.6f} |"
        )
    note += [
        "",
        "HBM gain is DRAM minus AegisKV failure-to-first-new-token latency; positive is",
        "better. Detection, queue and service remain separately available in cell-summary.csv.",
        "Target/cohort and target/Agent sign reversals are retained in",
        "policy-comparisons-per-identity.csv.",
        "All signed extrema and every adverse case remain in EXTREMES_AND_NEGATIVE_CASES.json.",
        "All 7,440 signed workflow pairs remain in paired-workflows.csv, including offsetting",
        "positive/negative workflow changes that cancel in a cohort mean.",
        "All-DRAM only removes the exposure threshold; it retains exposure ordering.",
        "Byte columns sum completed checkpoint/hot/restore and canceled-but-transferred bytes.",
        "Static/Aegis comparison covers all2232 workflow pairs without assuming equality.",
        "This is modeled FCFS/batch-one timing. Unseen admission delay is not called queue time.",
    ]
    (target / "README.md").write_text("\n".join(note) + "\n")


def figures(out):
    import fitz

    source = out / "postprocess_source_snapshot"
    subprocess.run(
        [sys.executable, str(source / "plot_primary_endpoints.py"), "--campaign", str(out)],
        check=True,
    )
    target = out / "figures"
    target.mkdir(exist_ok=True)
    for path in (out / "endpoints/figures").iterdir():
        if path.is_file():
            shutil.copyfile(path, target / path.name)
    pdf = fitz.open(target / "primary-target-wct.pdf")
    page = pdf[0]
    width, height = page.rect.width * 25.4 / 72, page.rect.height * 25.4 / 72
    assert abs(width - 178) < 0.1 and abs(height - 105) < 0.1
    sizes = [
        span["size"]
        for block in page.get_text("dict")["blocks"]
        if "lines" in block
        for line in block["lines"]
        for span in line["spans"]
    ]
    assert min(sizes) >= 10.0
    page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72)).save(target / "final-size-color.png")
    page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), colorspace=fitz.csGRAY).save(
        target / "final-size-gray.png"
    )
    write(
        target / "FIGURE_METADATA_REVIEW.json",
        dict(
            status="METADATA_PASS_VISUAL_REVIEW_PENDING",
            canvas_mm=[width, height],
            minimum_text_pt=min(sizes),
            marker_rows=150,
            **bindings(out),
            visual_review=(
                "actual color and grayscale exports must be inspected "
                "before claiming full figure review PASS"
            ),
        ),
    )
    (target / "CAPTION.md").write_text(
        "Target-workflow failure penalty in the walltime-trained v3 intervention. Each marker "
        "is one fixed failure identity, paired with its own policy's healthy baseline. S/N denote "
        "DAG sink/non-sink. The six panels cover two models and three nominal loads; no confidence "
        "interval or independent-repeat claim is made. Negative outcomes remain visible. The "
        "predictor is a train12 hashed-text regressor with training-derived role priors and "
        "LOOWF guard; this is distinct from the old service-proxy v2 campaign.\n"
    )


def fallback_windows(out):
    source = out / "postprocess_source_snapshot/audit_o1_dma_evidence.py"
    spec = importlib.util.spec_from_file_location("frozen_fallback_audit", source)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    evidence = helper.Evidence()
    plan = evidence.read(out / "PLAN.json")
    runs = {
        job["id"]: (job, evidence.read(out / "runs" / job["id"] / "summary.json"))
        for job in plan["jobs"]
        if job["detailed_logs"]
    }
    assert len(runs) == 2
    assert all(
        j["policy"] == "aegiskv" and "load0.65" in j["id"] and j["failure"]
        for j, _ in runs.values()
    )
    aggregates, windows = helper.fallback_samples(evidence, out, plan, runs)
    csv_write(out / "paper-summary/fallback-control-windows.csv", windows)
    write(
        out / "paper-summary/FALLBACK_CONTROL_WINDOWS.json",
        dict(
            status="PASS",
            analysis_source_sha256=sha(source),
            source_sha256=evidence.hashes,
            runs=aggregates,
            denominator="logged unfinished-workflow/control-window observations",
            scope=(
                "Only the two predeclared detailed AegisKV F1/load0.65 runs; "
                "each recorded Agent Slack independently reconstructed exactly. "
                "Not a continuous-time fraction, independent samples, or all-campaign rate. "
                "Reasons may overlap within a workflow/window. Old v2 rates are not reused."
            ),
            **bindings(out),
        ),
    )


def compare_versions(out):
    original = Path(read(out / "PROTOCOL.json")["original_campaign"])
    old_audit = read(original / "AUDIT.json")
    old_provenance = read(original / "endpoints/PROVENANCE.json")
    assert old_audit["status"] == old_provenance["status"] == "PASS"
    for relative, digest in old_provenance["source_sha256"].items():
        assert sha(original / relative) == digest
    for relative, digest in old_provenance["output_sha256"].items():
        assert sha(original / "endpoints" / relative) == digest
    old_index = {r["run_id"]: r for r in csv_rows(original / "endpoints/per-identity.csv")}
    new_index = {r["run_id"]: r for r in csv_rows(out / "endpoints/per-identity.csv")}
    assert old_index.keys() == new_index.keys() and len(old_index) == 150
    endpoints, workflows, placements, changed_requests = [], [], [], []
    sources = {}
    plan = read(out / "PLAN.json")
    for job in plan["jobs"]:
        identity = job["id"]
        paths = [base / "runs" / identity / "summary.json" for base in (original, out)]
        old, new = [read(path) for path in paths]
        sources.update({str(path): sha(path) for path in paths})
        sample = dict(
            run_id=identity,
            model=job["model"],
            policy=job["policy"],
            workload=job["workload"],
            fault_index=job["fault_index"],
        )
        assert old["workflows"].keys() == new["workflows"].keys()
        for workflow in old["workflows"]:
            a, b = old["workflows"][workflow], new["workflows"][workflow]
            workflows.append(
                dict(
                    **sample,
                    workflow=workflow,
                    v2_wct_ns=a["wct_ns"],
                    v3_wct_ns=b["wct_ns"],
                    v3_minus_v2_wct_ns=b["wct_ns"] - a["wct_ns"],
                )
            )
        requests = [{(r["agent"], r["invocation"]): r for r in s["requests"]} for s in (old, new)]
        assert requests[0].keys() == requests[1].keys()
        worker_changes = timing_changes = 0
        for key in requests[0]:
            a, b = requests[0][key], requests[1][key]
            worker_changes += a["worker"] != b["worker"]
            timing_changes += any(a[f] != b[f] for f in ("submit_ns", "finish_ns", "latency_ns"))
            if a != b:
                row = dict(**sample, agent=key[0], invocation=key[1])
                for field in ("worker", "submit_ns", "finish_ns", "latency_ns", "output_tokens"):
                    row[f"v2_{field}"], row[f"v3_{field}"] = a[field], b[field]
                changed_requests.append(row)
        row = dict(
            **sample,
            request_pairs=len(requests[0]),
            saved_worker_changes=worker_changes,
            request_timing_changes=timing_changes,
        )
        for label, summary in (("v2", old), ("v3", new)):
            fault = summary["failure"]
            row[f"{label}_fault_time_ns"] = fault["time_ns"] if fault else None
            row[f"{label}_failed_workers"] = json.dumps(fault["workers"] if fault else [])
            row[f"{label}_active_recovery_agents"] = json.dumps(
                sorted(r["agent"] for r in summary["recoveries"])
            )
            row[f"{label}_history_restore_agents"] = json.dumps(
                sorted(r["agent"] for r in summary.get("history_restores", []))
            )
            matches = [
                r
                for r in summary["recoveries"]
                if fault and r["agent"] == fault["agent"] and r["invocation"] == fault["invocation"]
            ]
            assert len(matches) == (1 if fault else 0)
            for field in (
                "source_worker",
                "retry_worker",
                "checkpoint_tokens",
                "durable_tokens",
                "queue_ns",
                "service_ns",
                "first_new_token_ns",
            ):
                row[f"{label}_{field}"] = matches[0].get(field) if matches else None
        placements.append(row)
        if job["failure"]:
            a, b = old_index[identity], new_index[identity]
            for field in (
                "target_agent",
                "target_invocation",
                "fault_logical_tokens",
                "target_dag_position",
            ):
                assert a[field] == b[field]
            row = dict(
                **sample,
                target_agent=a["target_agent"],
                target_dag_position=a["target_dag_position"],
            )
            for field in (
                "target_delta_wct_ns",
                "failure_to_first_new_token_ns",
                "retry_queue_ns",
                "recovery_service_ns",
            ):
                row[f"v2_{field}"], row[f"v3_{field}"] = int(a[field]), int(b[field])
                row[f"v3_minus_v2_{field}"] = int(b[field]) - int(a[field])
            # Cohort difference from integer per-WF sums, retaining offsetting changes.
            for label, campaign, failed in (("v2", original, old), ("v3", out, new)):
                healthy = read(campaign / "runs" / job["f0_id"] / "summary.json")
                row[f"{label}_cohort_sum_delta_ns"] = sum(
                    state["wct_ns"] - healthy["workflows"][w]["wct_ns"]
                    for w, state in failed["workflows"].items()
                )
            row["cohort_workflows"] = len(old["workflows"])
            row["v3_minus_v2_cohort_sum_delta_ns"] = (
                row["v3_cohort_sum_delta_ns"] - row["v2_cohort_sum_delta_ns"]
            )
            endpoints.append(row)
    target = out / "paper-summary"
    for name, rows in (
        ("v2-v3-endpoints.csv", endpoints),
        ("v2-v3-workflows.csv", workflows),
        ("v2-v3-placement.csv", placements),
        ("v2-v3-changed-requests.csv", changed_requests),
    ):
        # The changed-only request table can legitimately be empty.
        if rows:
            csv_write(target / name, rows)
        else:
            (target / name).write_text("")
    assert len(endpoints) == 150 and len(workflows) == 11160 and len(placements) == 180
    groups = defaultdict(list)
    for row in endpoints:
        groups[row["workload"], row["policy"]].append(row)
    cells = []
    for (workload, policy), values in sorted(groups.items()):
        assert len(values) == 5
        row = dict(workload=workload, policy=policy, fixed_identities=5)
        for label in ("v2", "v3", "v3_minus_v2"):
            for field in ("target_delta_wct_ns", "failure_to_first_new_token_ns"):
                row[f"{label}_{field.removesuffix('_ns')}_mean_s"] = mean_seconds(
                    values, f"{label}_{field}"
                )
            row[f"{label}_cohort_mean_delta_s"] = sum(
                r[f"{label}_cohort_sum_delta_ns"] for r in values
            ) / (5 * 62 * 1_000_000_000)
        cells.append(row)
    csv_write(target / "v2-v3-cell-summary.csv", cells)
    endpoint_index = {r["run_id"]: r for r in endpoints}
    contrasts = []
    for model in MODELS:
        for load in LOADS:
            for fault in range(5):
                for baseline, method in (
                    ("none", "dram"),
                    ("dram", "aegiskv"),
                    ("all_dram", "dram"),
                    ("static_hbm", "aegiskv"),
                ):
                    a, b = [
                        endpoint_index[f"{model}-load{load:g}-{p}-F1-{fault}"]
                        for p in (baseline, method)
                    ]
                    row = dict(
                        model=model,
                        nominal_load=load,
                        fault_index=fault,
                        baseline=baseline,
                        method=method,
                        target_agent=a["target_agent"],
                    )
                    for label in ("v2", "v3"):
                        for metric, field in (
                            ("target_gain_ns", "target_delta_wct_ns"),
                            ("cohort_sum_gain_ns", "cohort_sum_delta_ns"),
                            ("agent_gain_ns", "failure_to_first_new_token_ns"),
                        ):
                            row[f"{label}_{metric}"] = a[f"{label}_{field}"] - b[f"{label}_{field}"]
                        row[f"{label}_target_cohort_reversal"] = (
                            row[f"{label}_target_gain_ns"] * row[f"{label}_cohort_sum_gain_ns"] < 0
                        )
                    contrasts.append(row)
    csv_write(target / "v2-v3-policy-contrasts.csv", contrasts)
    write(
        target / "V2_V3_COMPARISON.json",
        dict(
            status="PASS",
            conditions=180,
            fault_endpoints=150,
            workflow_pairs=11160,
            old_campaign=str(original),
            old_audit_sha256=sha(original / "AUDIT.json"),
            old_endpoint_provenance_sha256=sha(original / "endpoints/PROVENANCE.json"),
            input_match_sha256=sha(out / "INPUT_MATCH.json"),
            source_sha256=sources,
            changed_workflow_wct_pairs=sum(r["v3_minus_v2_wct_ns"] != 0 for r in workflows),
            changed_target_delta=sum(r["v3_minus_v2_target_delta_wct_ns"] != 0 for r in endpoints),
            changed_agent_latency=sum(
                r["v3_minus_v2_failure_to_first_new_token_ns"] != 0 for r in endpoints
            ),
            changed_saved_request_workers=sum(r["saved_worker_changes"] for r in placements),
            old_target_cohort_reversal_cases=sum(r["v2_target_cohort_reversal"] for r in contrasts),
            new_target_cohort_reversal_cases=sum(r["v3_target_cohort_reversal"] for r in contrasts),
            boundary=(
                "Saved request worker is the summary's recorded worker, "
                "not an ordinary admission trace. Placement/timing changes establish association; "
                "summary-only runs do not reveal the full routing chain. "
                "Active recoveries and queued/idle history restores are reported separately. "
                "All signed changes retained; joint predictor/prior/guard intervention "
                "cannot isolate its components."
            ),
            **bindings(out),
        ),
    )


def append_summary(out):
    target = out / "paper-summary"
    fallback = read(target / "FALLBACK_CONTROL_WINDOWS.json")
    comparison = read(target / "V2_V3_COMPARISON.json")
    static = read(target / "STATIC_AEGIS_COMPARISON.json")
    cells = csv_rows(target / "cell-summary.csv")
    contrasts = csv_rows(target / "policy-comparisons-per-identity.csv")
    notes = ["", "## Version and fallback diagnostics", ""]
    for run in fallback["runs"]:
        notes.append(
            f"- `{run['run_id']}`: fallback in {run['fallback_samples']}/"
            f"{run['active_workflow_control_window_samples']} logged unfinished-workflow/"
            f"control-window observations ({100 * run['fallback_sample_share']:.6f}%). "
            f"Reasons: `{run['reason_sample_counts']}`."
        )
    notes += [
        "",
        "These are discrete logged-window shares, not elapsed-time fractions. "
        "Reason counts can overlap; the two detailed runs do not represent all 180 conditions.",
        "",
        f"Relative to v2, {comparison['changed_target_delta']}/150 target penalties and "
        f"{comparison['changed_agent_latency']}/150 Agent first-new latencies changed. "
        f"{comparison['changed_workflow_wct_pairs']}/11160 workflow WCT pairs and "
        f"{comparison['changed_saved_request_workers']} saved request-worker fields changed. "
        "See v2-v3-cell-summary.csv and v2-v3-policy-contrasts.csv for signed changes; "
        "v2-v3-placement.csv separates active recovery and history restore identities. "
        "Summary worker/timing fields alone do not establish an ordinary-admission routing chain.",
        "",
        f"Static/Aegis WCT equality: {static['equal_wct_pairs']}/{static['workflow_pairs']} "
        "pairs; no equivalence outside these conditions is inferred.",
        "",
        "Across the 30 model/load/policy cells, retry-queue shares of mean "
        "failure-to-first-new latency range from "
        f"{min(float(r['retry_queue_share']) for r in cells):.6f} "
        f"to {max(float(r['retry_queue_share']) for r in cells):.6f}; service shares range from "
        f"{min(float(r['recovery_service_share']) for r in cells):.6f} to "
        f"{max(float(r['recovery_service_share']) for r in cells):.6f}. "
        "Detection occupies the remaining share. These are ratios of five-identity means.",
        "",
        f"The 120 within-v3 policy/identity contrasts include "
        f"{sum(r['target_cohort_sign_reversal'] == 'True' for r in contrasts)} target/cohort "
        f"and {sum(r['target_agent_sign_reversal'] == 'True' for r in contrasts)} target/Agent "
        "sign reversals. The complete sink/non-sink strata and individual negative endpoints "
        "remain in the associated CSVs.",
    ]
    with (target / "README.md").open("a") as stream:
        stream.write("\n".join(notes) + "\n")


def run(out, wait):
    seal = read(out / "PAPER_POSTPROCESS_SEAL.json")
    for relative, expected in seal["sha256"].items():
        assert sha(out / relative) == expected
    assert (
        sha(Path(__file__))
        == seal["sha256"]["postprocess_source_snapshot/finalize_walltime_primary.py"]
    )
    with (out / "PAPER_POSTPROCESS.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (out / "PAPER_POSTPROCESS_COMPLETE.json").exists():
            completed = read(out / "PAPER_POSTPROCESS_COMPLETE.json")
            assert completed_gate(out)
            for key, expected in bindings(out).items():
                assert completed[key] == expected, key
            assert completed["postprocess_seal_sha256"] == sha(out / "PAPER_POSTPROCESS_SEAL.json")
            assert completed["audit_sha256"] == sha(out / "AUDIT.json")
            assert completed["endpoint_sha256"] == sha(out / "endpoints/PROVENANCE.json")
            for relative, expected in completed["output_sha256"].items():
                assert sha(out / relative) == expected
            return
        prediction_table(out)
        while not completed_gate(out):
            if not wait:
                raise SystemExit("PARTIAL: independent180 audit/endpoints are not complete")
            time.sleep(30)
        paper_data(out)
        fallback_windows(out)
        compare_versions(out)
        append_summary(out)
        figures(out)
        outputs = {
            str(p.relative_to(out)): sha(p)
            for folder in ("paper-summary", "figures")
            for p in (out / folder).iterdir()
            if p.is_file()
        }
        write(
            out / "PAPER_POSTPROCESS_COMPLETE.json",
            dict(
                status="NUMERIC_COMPLETE_VISUAL_REVIEW_PENDING",
                output_sha256=outputs,
                **bindings(out),
                postprocess_seal_sha256=sha(out / "PAPER_POSTPROCESS_SEAL.json"),
                audit_sha256=sha(out / "AUDIT.json"),
                endpoint_sha256=sha(out / "endpoints/PROVENANCE.json"),
            ),
        )
        print("paper-data and figures generated; final-size visual review pending", flush=True)


def prepare(out, launch):
    source = out / "postprocess_source_snapshot"
    source.mkdir(exist_ok=False)
    original = Path(read(out / "PROTOCOL.json")["original_campaign"])
    reference = read(original / "endpoints/figures/PROVENANCE.json")
    for name, key in (
        ("plot_primary_endpoints.py", "plot_sha256"),
        ("plot_profile_campaign.py", "style_source_sha256"),
    ):
        path = Path(__file__).with_name(name)
        assert sha(path) == reference[key]
        shutil.copyfile(path, source / name)
    shutil.copyfile(Path(__file__), source / Path(__file__).name)
    fallback = Path(__file__).with_name("audit_o1_dma_evidence.py")
    old_fallback_audit = original.parent / "reviews/o1-dma-corrected-v2-audit/AUDIT.json"
    assert sha(fallback) == read(old_fallback_audit)["analysis_script_sha256"]
    shutil.copyfile(fallback, source / fallback.name)
    write(
        out / "PAPER_POSTPROCESS_PROTOCOL.json",
        dict(
            operation=(
                "reuse unchanged sealed v2 marker/style code and v3 original-identity endpoints"
            ),
            gates=[
                "AUDIT PASS/180verified",
                "endpoint PROVENANCE PASS/180summaries/150faultrows",
                "new walltime model binding sidecar",
            ],
            no_DES=True,
            no_paper_changes=True,
            summaries=[
                "six cells by five policies,target/cohort",
                "sixrowAgent latency",
                "AllDRAMbytes36pairs",
                "Static/Aegis2232WFpairs",
                "all extrema/adverse cases",
                "all7440 signed workflow pairs across four policy contrasts",
                "two logged Aegis .65 F1 fallback denominators/reasons, exact Slack reconstruction",
                "v2-v3 endpoints/workflows/saved placement changes for all180 conditions",
                "six healthy predictor cells",
            ],
            visual_review="render178x105mm,color/grayscale; metadata only until actual inspection",
            **bindings(out),
        ),
    )
    sources = [str(p.relative_to(out)) for p in source.iterdir()]
    sources += ["PAPER_POSTPROCESS_PROTOCOL.json"]
    write(out / "PAPER_POSTPROCESS_SEAL.json", dict(sha256={r: sha(out / r) for r in sources}))
    prediction_table(out)
    if launch:
        command = [
            sys.executable,
            str(source / Path(__file__).name),
            "run",
            "--campaign",
            str(out),
            "--wait",
        ]
        with (out / "paper-postprocess.log").open("ab") as log:
            process = subprocess.Popen(
                command,
                cwd=out,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        write(
            out / "PAPER_POSTPROCESS_LAUNCH.json",
            dict(
                pid=process.pid,
                command=command,
                no_DES=True,
                seal_sha256=sha(out / "PAPER_POSTPROCESS_SEAL.json"),
            ),
        )
        print(f"postprocess watcher PID {process.pid}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "predictions"))
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--launch", action="store_true")
    args = parser.parse_args()
    target = args.campaign.resolve()
    if args.command == "prepare":
        prepare(target, args.launch)
    elif args.command == "predictions":
        prediction_table(target)
    else:
        run(target, args.wait)
