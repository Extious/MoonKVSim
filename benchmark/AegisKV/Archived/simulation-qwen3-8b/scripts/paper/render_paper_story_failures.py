"""Paired early/middle/late logical faults from a frozen, separate campaign."""

import csv
import json
from pathlib import Path

import numpy as np

import render_paper_story as plot
from paper_paths import ROOT
from three_system_data import SYSTEMS, LABELS, load_case, sha, write_csv

CAMPAIGN = ROOT / "output/paper-story-20260908/failure-campaign"
DATA = ROOT / "output/paper-story-20260908/failure-data"


def main():
    status = json.loads((CAMPAIGN / "STATUS.json").read_text())
    assert len(status["completed"]) == 12 and not any(
        status[k] for k in ("failed", "active", "pending")
    )
    protocol = json.loads((CAMPAIGN / "PROTOCOL.json").read_text())
    baseline = load_case(DATA / "f0-natural")
    ids = [r["workflow_id"] for r in csv.DictReader((plot.OUT / "workflow-order.csv").open())]
    summaries = []
    phases = []
    plans = []
    bindings = {}
    for case in ("f0-natural", "f1-q25", "f1-q50", "f1-q75"):
        for s in SYSTEMS:
            p = DATA / case / f"{s}.json"
            bindings[str(p.relative_to(ROOT))] = sha(p)
    for q in (25, 50, 75):
        name = f"f1-q{q}"
        data = load_case(DATA / name)
        event = data["mooncake"]["manifest"]["failure_schedule"]["events"][0]
        focus = event["focus_span_id"]
        count = event["workload_position"]["reference_completed_workflow_count"]
        progress = count / 160 * 100
        plans.append(
            dict(
                case=name,
                nominal_progress_pct=q,
                reference_progress_pct=progress,
                reference_completed_workflows=count,
                focus_span_id=focus,
            )
        )
        paired = {}
        for s in SYSTEMS:
            current = {r["workflow_id"]: r for r in data[s]["workflows"]}
            prior = {r["workflow_id"]: r for r in baseline[s]["workflows"]}
            assert current.keys() == prior.keys() == set(ids)
            paired[s] = np.array([current[w]["wct_s"] - prior[w]["wct_s"] for w in ids])
            failures = [r for r in data[s]["failures"] if r["span_id"] == focus]
            assert len(failures) == 1
            failed = failures[0]
            prefix = [
                e
                for e in data[s]["recovery_events"]
                if e["span_id"] == focus and e["event"] == "CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED"
            ]
            assert len(prefix) == 1
            start = failed["failure_at_ns"]
            materialized = prefix[0]["timestamp_ns"]
            ready = failed["resume_decode_start_ns"]
            assert start <= materialized <= ready
            injected = [e for e in data[s]["failure_events"] if e["event"] == "FAILURE_INJECT"]
            assert len(injected) == 1 and injected[0]["logical_trigger"]["focus_span_id"] == focus
            phases.append(
                dict(
                    case=name,
                    system=s,
                    nominal_progress_pct=q,
                    reference_progress_pct=progress,
                    prefix_materialization_s=(materialized - start) / 1e9,
                    suffix_to_resume_s=(ready - materialized) / 1e9,
                    resume_delay_s=(ready - start) / 1e9,
                    restored_peer_tokens=failed["restored_peer_tokens"],
                    restored_store_tokens=failed["restored_store_tokens"],
                    recompute_tokens=failed["recompute_tokens"],
                    impacted_active_requests=len(injected[0]["impacted_active_span_ids"]),
                    actual_failure_ns=start,
                    focus_span_id=focus,
                )
            )
            summaries.append(
                dict(
                    case=name,
                    system=s,
                    reference_progress_pct=progress,
                    mean_wct_delta_s=float(paired[s].mean()),
                    p95_wct_delta_s=float(np.percentile(paired[s], 95)),
                    slower_workflows=int((paired[s] > 1e-6).sum()),
                    faster_workflows=int((paired[s] < -1e-6).sum()),
                    mean_wct_s=data[s]["summary"]["mean_wct_s"],
                )
            )
        fig, ax = plot.canvas(
            "Workflow (same order as no-failure revisit)",
            "Failure-induced WCT change (s)",
            wide=True,
        )
        for s in SYSTEMS:
            plot.line(ax, s, np.arange(1, 161), paired[s], thin=True)
        ax.set_xlim(1, 160)
        ax.set_xticks([1, 40, 80, 120, 160])
        ax.axhline(0, color="#ABB2BA", lw=0.65, zorder=0)
        plot.legend(ax, header=True, columns=3)
        plot.finish(
            fig,
            f"{name}-workflow-penalty",
            [
                dict(
                    workflow_rank=i + 1, workflow_id=w, **{s: float(paired[s][i]) for s in SYSTEMS}
                )
                for i, w in enumerate(ids)
            ],
            sources=[name, "f0-natural"],
            note=f"F1(system, workflow) - matched F0(system, workflow); {count}/160 baseline workflows complete at reference trigger; signed, not truncated.",
        )

    fig, ax = plot.canvas(
        "Baseline workflow progress (%)", "Workflow WCT change, P95 (s)", wide=True
    )
    for s in SYSTEMS:
        rows = [r for r in summaries if r["system"] == s]
        plot.line(
            ax,
            s,
            [r["reference_progress_pct"] for r in rows],
            [r["p95_wct_delta_s"] for r in rows],
            markers=True,
        )
    ax.set_xlim(0, 100)
    ax.set_ylim(bottom=0)
    ax.set_xticks([0, 25, 50, 75, 100])
    plot.legend(ax, header=True, columns=3)
    plot.finish(
        fig,
        "failure-progress-p95-penalty",
        summaries,
        sources=["f0-natural", "f1-q25", "f1-q50", "f1-q75"],
        note="Percentile of 160 paired workflow deltas, not difference of WCT percentiles; one execution per point/system, not nine independent repeats.",
    )

    fig, ax = plot.canvas("Focal request: failure to decode resume (s)", "", wide=True, height=3.8)
    fig.subplots_adjust(left=0.285, top=0.85, bottom=0.15)
    y = np.array([i + (i // 3) * 0.55 for i in range(9)])
    a = np.array([r["prefix_materialization_s"] for r in phases])
    b = np.array([r["suffix_to_resume_s"] for r in phases])
    ax.barh(y, a, height=0.64, color="#0072B2", label="Prefix materialization")
    ax.barh(
        y,
        b,
        left=a,
        height=0.64,
        color="#B86B00",
        hatch="//",
        edgecolor="white",
        lw=0.4,
        label="Suffix + resume",
    )
    ax.set_yticks(y, [f"{r['nominal_progress_pct']}% / {LABELS[r['system']]}" for r in phases])
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color="#D8DCE1", lw=0.55)
    plot.legend(ax, header=True, columns=2)
    plot.finish(
        fig,
        "failure-focal-recovery-phases",
        phases,
        sources=["f1-q25", "f1-q50", "f1-q75"],
        note="One predeclared focal request per location; materialization includes reservation/setup/copy wait. Second phase includes suffix compute, scheduler wait and resume; phase boundaries from events, not recovery_ready-as-copy-complete.",
    )
    write_csv(plot.OUT / "failure-focus-plan.csv", plans)
    paths = [
        Path(__file__),
        Path(plot.__file__),
        Path(__file__).with_name("figure_style.py"),
        Path(__file__).with_name("three_system_data.py"),
        CAMPAIGN / "PROTOCOL.json",
        CAMPAIGN / "STATUS.json",
        Path(protocol["source"]) / "MECHANISM_SOURCE_SNAPSHOT.json",
    ]
    bindings.update({str(p.relative_to(ROOT)): sha(p) for p in paths})
    (plot.OUT / "failure-manifest.json").write_text(
        json.dumps(
            {
                "schema": "aegiskv.paper_story.failure.v1",
                "figures": plot.RECORDS,
                "input_bindings": bindings,
                "plans": plans,
                "summary": summaries,
                "phases": phases,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {"figures": len(plot.RECORDS), "runs": 12, "plans": plans, "summary": summaries},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
