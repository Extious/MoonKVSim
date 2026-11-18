#!/usr/bin/env python3
"""Descriptive paired figures for audited constructed interventions."""
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path

import fitz
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/structural-campaign-v1"
OUT = SOURCE / "figures"
WIDTH = 178 / 25.4
FONT = 10.3
SCENARIOS = (
    "forkjoin_skew",
    "forkjoin_balanced",
    "history_reuse",
    "long_decode_drift",
    "shared_host",
)
LABELS = (
    "Skewed\nfork-join",
    "Balanced\nfork-join",
    "History\nreuse",
    "Long\ndecode",
    "Shared\nhost",
)
POLICIES = ("none", "dram", "aegiskv")
SEEDS = (7, 19, 41)
FAULTS = ("left.prefill", "left.decode")
COLORS = {"none": "#6d6d6d", "dram": "#3b78a4", "aegiskv": "#b7474b"}
MARKERS = {"none": "o", "dram": "s", "aegiskv": "D"}
NAMES = {"none": "Restart", "dram": "DRAM", "aegiskv": "AegisKV"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def setup():
    path = subprocess.check_output(["kpsewhich", "LinLibertine_R.otf"], text=True).strip()
    font_manager.fontManager.addfont(path)
    family = font_manager.FontProperties(fname=path).get_name()
    plt.rcParams.update(
        {
            "font.family": family,
            "font.size": FONT,
            "axes.labelsize": FONT,
            "axes.titlesize": FONT,
            "xtick.labelsize": FONT,
            "ytick.labelsize": FONT,
            "legend.fontsize": FONT,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 0.65,
            "xtick.major.width": 0.6,
            "ytick.major.width": 0.6,
            "xtick.major.size": 2.6,
            "ytick.major.size": 2.6,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.fonttype": "none",
            "savefig.dpi": 300,
        }
    )
    return path, family


def verify_inputs(main_only=False):
    audit_name = "MAIN_TRACE_MECHANISM_AUDIT.json" if main_only else "TRACE_MECHANISM_AUDIT.json"
    prefix = "main-" if main_only else ""
    audit_path = SOURCE / audit_name
    audit = json.loads(audit_path.read_text())
    assert audit["all_passed"] and len(audit["run_bindings"]) == (135 if main_only else 143)
    assert audit["plan_sha256"] == sha(SOURCE / "PLAN.json")
    assert audit["manifest_sha256"] == sha(SOURCE / "MANIFEST.json")
    for name, expected in audit["source_sha256"].items():
        assert sha(SOURCE / name) == expected
    if main_only:
        assert audit["paired_failure_runs"] == 90 and audit["campaign_status"] == "PARTIAL"
    else:
        valid = json.loads((SOURCE / "VALIDATION.json").read_text())
        assert valid["all_passed"] and valid["runs"] == 143 and valid["pairs"] == 94
    paired = read_csv(SOURCE / f"{prefix}paired-workflows.csv")
    recoveries = read_csv(SOURCE / f"{prefix}recovery-events.csv")
    target = {
        (row["scenario"], row["fault"], row["policy"], int(row["seed"])): float(row["delta_wct_s"])
        for row in paired
        if row["target_workflow"] == "True" and row["workflows"] == "8"
    }
    service, queue = {}, {}
    for row in recoveries:
        if row["primary_target_agent"] != "True" or row["workflows"] != "8":
            continue
        key = row["scenario"], row["fault"], row["policy"], int(row["seed"])
        assert key not in service
        service[key] = float(row["service_ns"]) / 1e6
        queue[key] = float(row["queue_ns"]) / 1e9
        assert int(row["detection_ns"]) == 1_000_000
    assert len(target) == len(queue) == len(service) == 90
    # Recompute every plotted WCT delta from the immutable paired summaries.
    plan = json.loads((SOURCE / "PLAN.json").read_text())
    for job in plan["jobs"]:
        if job["workflows"] != 8 or job["fault"] == "F0":
            continue
        failed = json.loads((SOURCE / "runs" / job["id"] / "summary.json").read_text())
        normal = json.loads((SOURCE / "runs" / job["f0_id"] / "summary.json").read_text())
        identity = job["scenario"], job["fault"], job["policy"], job["seed"]
        target_id = job["failure"]["agent"].split("/")[0]
        delta = (
            failed["workflows"][target_id]["wct_ns"] - normal["workflows"][target_id]["wct_ns"]
        ) / 1e9
        assert abs(target[identity] - delta) < 1e-10
        recovery = [row for row in failed["recoveries"] if row["agent"] == job["failure"]["agent"]]
        assert len(recovery) == 1
        assert service[identity] == recovery[0]["service_ns"] / 1e6
        assert queue[identity] == recovery[0]["queue_ns"] / 1e9
    return target, queue, service, paired


def legend(fig):
    handles = [
        Line2D(
            [],
            [],
            marker=MARKERS[p],
            color=COLORS[p],
            ls="none",
            markersize=5,
            markerfacecolor="white",
            label=NAMES[p],
        )
        for p in POLICIES
    ]
    fig.legend(
        handles=handles,
        loc="upper center",
        ncol=3,
        frameon=False,
        bbox_to_anchor=(0.535, 0.998),
        columnspacing=2.0,
        handletextpad=0.4,
    )


def points(ax, metric, fault):
    all_values = []
    for case, scenario in enumerate(SCENARIOS):
        for seed_i, seed in enumerate(SEEDS):
            shift = (seed_i - 1) * 0.045
            x = [case + (i - 1) * 0.245 + shift for i in range(3)]
            y = [metric[scenario, fault, policy, seed] for policy in POLICIES]
            ax.plot(x, y, color="#c5c5c5", lw=0.65, zorder=1)
        for i, policy in enumerate(POLICIES):
            center = case + (i - 1) * 0.245
            values = [metric[scenario, fault, policy, seed] for seed in SEEDS]
            ax.vlines(center, min(values), max(values), color=COLORS[policy], lw=1.1, zorder=2)
            ax.plot(
                [center - 0.07, center + 0.07],
                [np.mean(values)] * 2,
                color=COLORS[policy],
                lw=1.4,
                zorder=4,
            )
            for seed_i, value in enumerate(values):
                ax.plot(
                    center + (seed_i - 1) * 0.045,
                    value,
                    marker=MARKERS[policy],
                    ls="none",
                    markersize=4.2,
                    markerfacecolor="white",
                    markeredgecolor=COLORS[policy],
                    markeredgewidth=0.9,
                    zorder=3,
                )
            all_values.extend(values)
    ax.set_xticks(range(5), LABELS)
    ax.set_xlim(-0.55, 4.55)
    ax.axhline(0, color="#777777", lw=0.6, ls="--", zorder=0)
    ax.yaxis.grid(True, color="#e4e4e4", lw=0.5)
    ax.set_axisbelow(True)
    return all_values


def common_limits(axes, values):
    low, high = min(0, min(values)), max(0, max(values))
    pad = max((high - low) * 0.055, 0.001)
    for ax in axes:
        ax.set_ylim(low - pad, high + pad)


def save(fig, name):
    for extension in ("pdf", "svg", "png"):
        fig.savefig(OUT / f"{name}.{extension}", facecolor="white")
    plt.close(fig)
    pdf = fitz.open(OUT / f"{name}.pdf")
    page = pdf[0]
    assert abs(page.rect.width / 72 - WIDTH) < 1e-5
    spans = [
        span
        for block in page.get_text("dict")["blocks"]
        if "lines" in block
        for line in block["lines"]
        for span in line["spans"]
        if span["text"].strip()
    ]
    assert min(span["size"] for span in spans) >= 10.29
    assert all(page.rect.contains(fitz.Rect(span["bbox"])) for span in spans)
    for dpi in (96, 144):
        for label, colorspace in (("color", fitz.csRGB), ("grayscale", fitz.csGRAY)):
            page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), colorspace=colorspace).save(
                OUT / f"{name}-{dpi}dpi-{label}.png"
            )
    return {
        "name": name,
        "width_mm": page.rect.width / 72 * 25.4,
        "height_mm": page.rect.height / 72 * 25.4,
        "minimum_font_pt": min(span["size"] for span in spans),
        "pdf_sha256": sha(OUT / f"{name}.pdf"),
        "png_sha256": sha(OUT / f"{name}.png"),
        "font_names": sorted({item[3] for item in page.get_fonts()}),
    }


def wct_figure(target):
    fig, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.95), sharey=True)
    fig.subplots_adjust(left=0.095, right=0.985, bottom=0.24, top=0.79, wspace=0.12)
    values = []
    for ax, fault, title in zip(
        axes, FAULTS, ("(a) Prefill fault", "(b) Decode fault"), strict=True
    ):
        values += points(ax, target, fault)
        ax.set_title(title, pad=8)
    axes[0].set_ylabel("Target workflow ΔWCT (s)")
    common_limits(axes, values)
    legend(fig)
    return save(fig, "structural-target-wct")


def recovery_figure(queue, service):
    fig, axes = plt.subplots(2, 2, figsize=(WIDTH, 4.95), sharex=True, sharey="row")
    fig.subplots_adjust(left=0.105, right=0.985, bottom=0.145, top=0.855, hspace=0.25, wspace=0.12)
    for row, (metric, label) in enumerate(
        ((queue, "Retry queue (s)"), (service, "Recovery service (ms)"))
    ):
        values = []
        for col, fault in enumerate(FAULTS):
            values += points(axes[row, col], metric, fault)
            if row == 0:
                axes[row, col].set_title(("(a) Prefill fault", "(b) Decode fault")[col], pad=8)
        axes[row, 0].set_ylabel(label)
        common_limits(axes[row], values)
    legend(fig)
    return save(fig, "structural-recovery-breakdown")


def tables(target, queue, service, paired, main_only=False):
    figure_rows, headlines = [], []
    for scenario in SCENARIOS:
        for fault in FAULTS:
            groups = {}
            for policy in POLICIES:
                values = [target[scenario, fault, policy, seed] for seed in SEEDS]
                groups[policy] = values
                for seed in SEEDS:
                    identity = scenario, fault, policy, seed
                    figure_rows.append(
                        dict(
                            scenario=scenario,
                            fault=fault,
                            policy=policy,
                            seed=seed,
                            target_delta_wct_s=target[identity],
                            primary_recovery_queue_s=queue[identity],
                            primary_recovery_service_ms=service[identity],
                        )
                    )
            dram_gain = np.array(groups["none"]) - groups["dram"]
            hbm_gain = np.array(groups["dram"]) - groups["aegiskv"]
            headlines.append(
                dict(
                    scenario=scenario,
                    fault=fault,
                    n_constructed_seeds=3,
                    **{
                        f"{policy}_mean_delta_wct_s": float(np.mean(groups[policy]))
                        for policy in POLICIES
                    },
                    dram_vs_none_mean_wct_gain_s=float(np.mean(dram_gain)),
                    dram_vs_none_min_wct_gain_s=float(min(dram_gain)),
                    dram_vs_none_max_wct_gain_s=float(max(dram_gain)),
                    aegis_vs_dram_mean_wct_gain_s=float(np.mean(hbm_gain)),
                    aegis_vs_dram_min_wct_gain_s=float(min(hbm_gain)),
                    aegis_vs_dram_max_wct_gain_s=float(max(hbm_gain)),
                    **{
                        f"{policy}_mean_queue_s": float(
                            np.mean([queue[scenario, fault, policy, s] for s in SEEDS])
                        )
                        for policy in POLICIES
                    },
                    **{
                        f"{policy}_mean_service_ms": float(
                            np.mean([service[scenario, fault, policy, s] for s in SEEDS])
                        )
                        for policy in POLICIES
                    },
                )
            )
    write_csv(OUT / "figure-data.csv", figure_rows)
    write_csv(OUT / "headline-results.csv", headlines)
    if not main_only:
        raw = read_csv(SOURCE / "raw-runs.csv")
        scale = [
            row
            for row in raw
            if row["scenario"] == "history_reuse"
            and row["seed"] == "7"
            and row["policy"] in {"dram", "aegiskv"}
            and row["fault"] in {"F0", "left.decode"}
        ]
        assert len(scale) == 12
        plan_jobs = {job["id"]: job for job in json.loads((SOURCE / "PLAN.json").read_text())["jobs"]}
        assert all(not plan_jobs[row["id"]]["retain_detailed_logs"] for row in scale)
        write_csv(OUT / "scale-resource-results.csv", scale)
        scale_lines = [
            "# Simulator resource costs at three workflow counts",
            "",
            "All 12 points use the same frozen structural-campaign-v1 runtime, profile and summary-log mode. "
            "Each count includes seed-7 history_reuse under DRAM/AegisKV and F0/left.decode. "
            "The four points are different policy/fault cases, not four timing replicates. Each original DAG executes once.",
            "",
            "| Workflows | Policy | Fault | Wall (s) | Process CPU (s) | Worker lifetime peak RSS (MiB) |",
            "|---:|---|---|---:|---:|---:|",
        ]
        for row in sorted(scale, key=lambda r: (int(r["workflows"]), r["policy"], r["fault"])):
            scale_lines.append(
                f"| {row['workflows']} | {row['policy']} | {row['fault']} | "
                f"{float(row['run_wall_seconds']):.6f} | {float(row['process_cpu_seconds']):.6f} | "
                f"{int(row['worker_lifetime_peak_rss_kib']) / 1024:.6f} |"
            )
        scale_lines += [
            "",
            "Wall and process CPU intervals start after workload/profile loading and include simulation plus result "
            "serialization. Four workers run concurrently on the shared host. RSS is Linux ru_maxrss for the worker's "
            "whole lifetime; a worker can retain prior input caches, so this is not a fresh-process or per-run-only peak. "
            "Raw values and all modeled WCT/resource metrics are retained in scale-resource-results.csv.",
            "",
            "This frozen summary-only implementation still computes policy_sample estimates before discarding those "
            "detailed records. A later optimization was tested separately but is not applied to any of these 143 runs. "
            "These measurements characterize this simulator implementation, not GPU serving throughput or AegisKV's "
            "hardware overhead; modeled HBM/DRAM peaks have separate CSV columns. No cases or sizes were reduced.",
        ]
        (OUT / "SCALE_RESOURCES.md").write_text("\n".join(scale_lines) + "\n")
    (OUT / "HEADLINE_RESULTS.json").write_text(
        json.dumps(
            {
                "rows": headlines,
                "negative_paired_workflow_deltas": sum(
                    float(row["delta_wct_s"]) < 0 for row in paired
                ),
                "comparison": "F1 minus own-policy F0; gain is comparator delta minus method delta",
                "interval": "min/max of three constructed seeds, not confidence interval",
            },
            indent=2,
        )
        + "\n"
    )
    lines = [
        "# Structural campaign: audited descriptive results",
        "",
        (
            "The complete 135-run main matrix is independently audited; the full 143-run campaign remains PARTIAL. "
            "The 90 main F1/F0 pairs produce 720 workflow observations. "
            if main_only
            else "All 143 frozen runs completed; 94 F1/F0 pairs produce 1,040 workflow observations. "
        )
        + "Main figures use only the fault-target workflow of each of the 90 eight-workflow failure runs. "
        "Independent constructed seeds are 7, 19 and 41; workflows within a run share resources.",
        "",
        "| Scenario | Fault | No backup ΔWCT (s) | DRAM ΔWCT (s) | AegisKV ΔWCT (s) | AegisKV vs DRAM gain (ms) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in headlines:
        lines.append(
            f"| {row['scenario']} | {row['fault']} | {row['none_mean_delta_wct_s']:.6f} | "
            f"{row['dram_mean_delta_wct_s']:.6f} | {row['aegiskv_mean_delta_wct_s']:.6f} | "
            f"{row['aegis_vs_dram_mean_wct_gain_s'] * 1000:.6f} |"
        )
    lines += [
        "",
        "Values are means of already-paired seed deltas. Exact points, ranges and recovery decomposition "
        "are retained in headline-results.csv and figure-data.csv. Negative deltas/gains are retained.",
        "",
        "The same Agent/call and resolved total-token threshold are fixed across policies. Prefill and decode "
        "use different threshold positions in that call, so the two panels do not isolate stage at one common "
        "80% total-progress point. Primary and collateral victims remain explicit in PHASE_AUDIT.json.",
        "",
        "Role priors are hand-set causal proxies, not measured predictor accuracy. All calls declare a fixed "
        "16,384-token output limit; no actual-output-length reservation oracle is used. Long-decode demand "
        "is a constructed two-bank selector with a dense Qwen3-8B compute profile; K=16 can accommodate both "
        "four-block banks, so its zero misses do not establish robustness under insufficient native-cache capacity.",
        "",
        (
            "Eight added scale cases are still pending final audit; main figures exclude them. "
            if main_only
            else "Scale resource results retain all 12 seed-7 history cases at 8/32/128 workflows. "
        )
        + "Runtime wall/CPU "
        "seconds begin after input loading; peak RSS is the worker-process lifetime high-water mark, including "
        "cached workloads and log serialization, not a per-run engine-only peak. Simulated HBM/DRAM byte peaks "
        "are separate columns. Every scale run uses summary logs; this frozen version still computes discarded "
        "policy_sample estimates. No later performance optimization is applied, and there is no scale reduction.",
        "",
        "Integrated evidence remains simulation: the AIC grid mixes empirical and silicon-derived operators; "
        "there is no physical model execution, native-kernel timing validation, continuous batching or measured "
        "DMA/compute interference in these results. Zero healthy latency differences are conditional on that model.",
    ]
    (OUT / "RESULTS.md").write_text("\n".join(lines) + "\n")


def main(main_only=False):
    target, queue, service, paired = verify_inputs(main_only)
    OUT.mkdir(parents=True, exist_ok=True)
    font_path, family = setup()
    exports = [wct_figure(target), recovery_figure(queue, service)]
    tables(target, queue, service, paired, main_only)
    captions = """# Figure captions and placement

Both figures have 178 mm canvases and Linux Libertine 10.3 pt text. Insert at that width.

**structural-target-wct.pdf.** Fault-target workflow completion penalty in five constructed
four-Agent scenarios, with eight workflows per run. Each point is F1 minus its own-policy
failure-free F0 for one of three matched workload seeds. Thin gray segments connect the same
seed across policies; colored vertical ranges show min/max and short horizontal marks show
means. Panels inject a fault during the second invocation's new Prefill or Decode; resolved
Agent/call/token identity is fixed across policies. Zero and negative values are retained.
DRAM and AegisKV points may coincide at this scale. These are simulated interventions, not
observed Agent serving traces; the two panels use distinct logical progress points.

**structural-recovery-breakdown.pdf.** Recovery delay of the directly faulted Agent in the
same 90 failure runs. Top panels show waiting between retry enqueue and admission; bottom
panels show admitted recovery service until the first new output token. Detection adds a
fixed 1 ms, so total recovery delay is detection plus queue plus service. Markers, paired
segments, means and min/max use the same three constructed seeds as the completion plot.
Separate ordinate units preserve visibility of service cost when queueing dominates.
Recovery service improvement does not imply the same workflow completion improvement.

scale-resource-results.csv is an external 12-run resource table, not another main-paper plot.
Final compiled-paper placement must be checked when these PDFs are integrated.
"""
    (OUT / "CAPTIONS.md").write_text(captions)
    prefix = "main-" if main_only else ""
    input_names = [
        "PLAN.json",
        f"{prefix}paired-workflows.csv",
        f"{prefix}recovery-events.csv",
        "MAIN_TRACE_MECHANISM_AUDIT.json" if main_only else "TRACE_MECHANISM_AUDIT.json",
    ]
    if not main_only:
        input_names += ["VALIDATION.json", "raw-runs.csv"]
    (OUT / "EXPORT_METADATA.json").write_text(
        json.dumps(
            {
                "script_sha256": sha(Path(__file__)),
                "font_path": font_path,
                "font_family": family,
                "inputs": {name: sha(SOURCE / name) for name in input_names},
                "exports": exports,
                "statistical_units": "three constructed workload seeds; no population inference",
                "source": "135 main snapshot-executed DES runs; 90 target-workflow points per plotted metric",
                "entire_campaign_status": "PARTIAL" if main_only else "COMPLETE",
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(exports, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-only", action="store_true")
    main(parser.parse_args().main_only)
