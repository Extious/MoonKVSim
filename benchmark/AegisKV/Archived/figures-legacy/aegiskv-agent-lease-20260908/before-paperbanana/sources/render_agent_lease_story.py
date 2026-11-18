"""Recompute the paper's statistical evidence from the current frozen algorithms."""
from __future__ import annotations
import argparse
import csv
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np
import render_paper_story as plot
from paper_paths import ROOT
from three_system_data import SYSTEMS, LABELS, load_case, sha, write_csv

OUT = ROOT / "output/pdf/aegiskv-agent-lease-20260908"
RUNS = ROOT / "output/agent-lease-20260908/data"
ORIGINAL_FINISH = plot.finish


def finish_current(fig, name, rows, **kwargs):
    if name == "f0-revisit-controller-breakdown":
        for label in fig.axes[0].get_legend().get_texts():
            if label.get_text() == "Lookup":
                label.set_text("Dispatch")
    kwargs["sources"] = ["f0-base" if x == "f0-revisit" else x
        for x in kwargs.get("sources", [])]
    ORIGINAL_FINISH(fig, name, rows, **kwargs)


@lru_cache(maxsize=3)
def case(name):
    if name == "f0-revisit": name = "f0-base"
    available = {s: json.loads((RUNS / name / f"{s}.json").read_text())
        for s in SYSTEMS if (RUNS / name / f"{s}.json").exists()}
    assert available, name
    if len(available) == 3:
        available = load_case(RUNS / name)
    for s in available:
        p = RUNS / name / f"{s}.json"
        plot.INPUTS[str(p.relative_to(ROOT))] = sha(p)
    return available


def summaries():
    result = {}
    for directory in RUNS.iterdir():
        if not directory.is_dir(): continue
        result[directory.name] = {}
        for system in SYSTEMS:
            path = directory / f"{system}.json"
            if path.exists():
                result[directory.name][system] = json.loads(path.read_text())["summary"]
                plot.INPUTS[str(path.relative_to(ROOT))] = sha(path)
    return result


def failure_figures():
    baseline = case("f0-base")
    order = [r["workflow_id"] for r in csv.DictReader((OUT / "workflow-order.csv").open())]
    original = {s: {r["workflow_id"]: r["wct_s"] for r in baseline[s]["workflows"]} for s in SYSTEMS}
    result, phases, selected = [], [], []
    penalties = {}
    for q in (25, 50, 75):
        data = case(f"f1-q{q}")
        plan = data["mooncake"]["manifest"]["failure_schedule"]["events"][0]
        focus = plan["focus_span_id"]
        count = plan["workload_position"]["reference_completed_workflow_count"]
        selected.append(dict(nominal_progress_pct=q, actual_reference_completed=count, focus_span_id=focus))
        deltas = {}
        for s in SYSTEMS:
            current = {r["workflow_id"]: r["wct_s"] for r in data[s]["workflows"]}
            deltas[s] = np.array([current[w] - original[s][w] for w in order])
            result.append(dict(case=f"f1-q{q}", system=s, progress_pct=q,
                actual_reference_progress_pct=count / len(order) * 100,
                mean_penalty_s=float(deltas[s].mean()), p95_penalty_s=float(np.percentile(deltas[s], 95)),
                faster_workflows=int(sum(deltas[s] < -1e-9)), slower_workflows=int(sum(deltas[s] > 1e-9))))
            failed = [r for r in data[s]["failures"] if r["span_id"] == focus]
            assert len(failed) == 1
            f = failed[0]
            event = [r for r in data[s]["recovery_events"] if r["span_id"] == focus and r["event"] == "CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED"]
            assert len(event) == 1
            materialized = event[0]["timestamp_ns"]
            resume = f["resume_decode_start_ns"]
            assert f["failure_at_ns"] <= materialized <= resume
            phases.append(dict(system=s, progress_pct=q, focus_span_id=focus,
                materialize_s=(materialized - f["failure_at_ns"]) / 1e9,
                suffix_and_resume_s=(resume - materialized) / 1e9,
                resume_s=(resume - f["failure_at_ns"]) / 1e9,
                restored_peer_tokens=f["restored_peer_tokens"], restored_store_tokens=f["restored_store_tokens"],
                recompute_tokens=f["recompute_tokens"]))
        penalties[q] = (count, deltas)
    # Keep the early/middle/late fault magnitudes visually comparable, including
    # the two diagnostic exports that are placed in the supplement.
    values = np.concatenate([v for _, deltas in penalties.values() for v in deltas.values()])
    margin = .05 * np.ptp(values)
    limits = (float(values.min() - margin), float(values.max() + margin))
    for q, (count, deltas) in penalties.items():
        fig, ax = plot.canvas("Workflow (same order as no failure)", "Failure-induced WCT change (s)", wide=True)
        for s in SYSTEMS: plot.line(ax, s, np.arange(1, len(order)+1), deltas[s], thin=True)
        ax.axhline(0, color="#A9B1B8", lw=.7, zorder=0)
        ax.set_xlim(1, len(order)); ax.set_xticks([1,40,80,120,160]); ax.set_ylim(*limits)
        plot.legend(ax, header=True, columns=3)
        plot.finish(fig, f"f1-q{q}-workflow-penalty", [dict(workflow_rank=i+1, workflow_id=w,
            **{s:float(deltas[s][i]) for s in SYSTEMS}) for i,w in enumerate(order)], sources=["f0-base", f"f1-q{q}"],
            note=f"F1 minus own matched F0, same 2608-request workload; all 160 workflows including those already finished; {count}/160 finished at the Mooncake reference trigger; signed values. Common y limits across all three fault positions.")
    fig, ax = plot.canvas("Failure selection position (%)", "P95 WCT penalty (s)")
    for s in SYSTEMS:
        plot.line(ax, s, [25,50,75], [r["p95_penalty_s"] for r in result if r["system"]==s], markers=True)
    ax.set_xticks([25,50,75]); ax.set_xlim(20,80); plot.legend(ax, header=True, columns=3)
    plot.finish(fig, "failure-progress-p95-penalty", result, sources=["f0-base", "f1-q25", "f1-q50", "f1-q75"],
        note="Three distinct prespecified logical events, not independent repeats; percentile is over all paired workflows in each event, not a per-workflow bound.")
    fig, ax = plot.canvas("Failure selection position (%)", "Focal request resume delay (s)", wide=True)
    x = np.arange(3)
    for j,s in enumerate(SYSTEMS):
        rows = [r for r in phases if r["system"]==s]
        ax.bar(x+(j-1)*.25, [r["materialize_s"] for r in rows], width=.22, color=plot.COLORS[s], label=LABELS[s])
        ax.bar(x+(j-1)*.25, [r["suffix_and_resume_s"] for r in rows], bottom=[r["materialize_s"] for r in rows],
            width=.22, color=plot.COLORS[s], hatch="///", edgecolor="white", linewidth=.4)
    ax.set_xticks(x,["25","50","75"]); fig.set_figheight(3.1); fig.subplots_adjust(top=.70)
    # Stacking key belongs in a separate legend, not ambiguous tiny bar text.
    from matplotlib.patches import Patch
    handles = [Patch(facecolor="#BEC5CC",label="Materialize prefix"),
               Patch(facecolor="#BEC5CC",hatch="///",edgecolor="white",label="Suffix + resume")]
    fig.legend(handles=handles,loc="upper center",bbox_to_anchor=(.55,.9),ncol=2,frameon=False,fontsize=10)
    # Preserve both the series and the component key.
    fig.legend([Patch(facecolor=plot.COLORS[s]) for s in SYSTEMS], [LABELS[s] for s in SYSTEMS],
        loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(.55,1))
    plot.finish(fig,"failure-focal-recovery-phases",phases,sources=["f1-q25","f1-q50","f1-q75"],
        note="Each stacked bar is the same prespecified focal request: prefix materialization plus suffix/recovery decode queue; restored token counts are in CSV; shorter materialization alone is not a recovery benefit.")
    write_csv(OUT/"failure-summary.csv",result);write_csv(OUT/"failure-focuses.csv",selected)
    # Explicitly analytical mixing of matched observations, not measured MTBF.
    means = summaries()
    pvalues = np.linspace(0,1,101)
    rows=[]
    fig,ax=plot.canvas("Probability of one fault per execution", "Expected mean WCT (s)",wide=True)
    for s in SYSTEMS:
        healthy=means["f0-base"][s]["mean_wct_s"]
        penalty=float(np.mean([r["mean_penalty_s"] for r in result if r["system"]==s]))
        y=healthy+pvalues*penalty
        plot.line(ax,s,pvalues,y)
        rows += [dict(system=s,fault_probability=float(p),no_fault_mean_wct_s=healthy,
            mean_fault_penalty_s=penalty,expected_mean_wct_s=float(v)) for p,v in zip(pvalues,y)]
    ax.set_xlim(0,1);plot.legend(ax,header=True,columns=3)
    plot.finish(fig,"benefit-cost-fault-mixture",rows,evidence="analytical_mixture_of_simulations",
        sources=["f0-base","f1-q25","f1-q50","f1-q75"],
        note="(1-p)*mean(F0)+p*mean(F1), at most one failure per full execution, equal 1/3 weight for three prespecified fault positions. p and these weights are assumptions; this is not observed failure frequency or extrapolation to repeated failures.")


def sensitivity_figures():
    means=summaries()
    for name,x,names,xlabel,metric,ylabel in [
        ("bandwidth",[5,25,50],["f0-bw5","f0-base","f0-bw50"],"Shared bandwidth (GB/s)","mean_wct_s","Mean WCT (s)"),
        ("concurrency",[16,32],["f0-base","f0-c32"],"Active workflows","mean_wct_s","Mean WCT (s)"),
        ("dram-capacity",[250,1000],["f0-dram250","f0-base"],"DRAM capacity (GB)","dram_hit_pct","DRAM token hit rate (%)"),
        ("cpu-quote",[1,2],["f0-base","f0-cpu2"],"Controller CPU quote multiplier","mean_wct_s","Mean WCT (s)"),
        ("dma",[0,5,30],["f0-base","f0-dma5","f0-dma30"],"Extra forward time with DMA (%)","mean_wct_s","Mean WCT (s)")]:
        fig,ax=plot.canvas(xlabel,ylabel)
        for s in SYSTEMS:plot.line(ax,s,x,[means[n][s][metric] for n in names],markers=True)
        # A zero baseline changes the displayed range: recompute headroom from
        # that range so the highest marker does not touch the plot boundary.
        maximum = max(means[n][s][metric] for n in names for s in SYSTEMS)
        ax.set_xticks(x);ax.set_ylim(0, 1.10 * maximum);plot.legend(ax,header=True,columns=3)
        plot.finish(fig,f"sensitivity-{name}",[dict(case=n,x=v,**{s:means[n][s][metric] for s in SYSTEMS}) for n,v in zip(names,x)],
            sources=names,note="Only displayed settings were executed; one paired execution per setting and system. Segment connections are guides. CPU and DMA coefficients are model sensitivity parameters.")


def order_figures():
    healthy = [case(c) for c in ["f0-base", "f0-seed1", "f0-seed2"]]
    failed = [case(c) for c in ["f1-q50", "f1-seed1", "f1-seed2"]]
    for name, xlabel, fault in [
        ("order-normal-wct", "WCT (s)", False),
        ("order-failure-penalty", "Failure-induced WCT change (s)", True),
    ]:
        fig, ax = plot.canvas(xlabel, "Fraction of workflows")
        rows = []
        for system in SYSTEMS:
            ordered = []
            for seed in range(3):
                f0 = {r["workflow_id"]: r["wct_s"] for r in healthy[seed][system]["workflows"]}
                f1 = {r["workflow_id"]: r["wct_s"] for r in failed[seed][system]["workflows"]}
                assert f0.keys() == f1.keys() and len(f0) == 160
                values = sorted(f1[w] - f0[w] if fault else f0[w] for w in f0)
                ordered.append([values[0], *values])
            quantiles = np.arange(161) / 160
            low, median, high = np.min(ordered, axis=0), np.median(ordered, axis=0), np.max(ordered, axis=0)
            ax.fill_betweenx(quantiles, low, high, color=plot.COLORS[system], alpha=.13, lw=0, step="pre")
            ax.step(median, quantiles, where="post", color=plot.COLORS[system],
                ls=plot.STYLES[system], label=LABELS[system], lw=1.5)
            rows.extend(dict(system=system, quantile=float(q), minimum_s=float(a), median_s=float(b),
                maximum_s=float(c), seed0_s=float(ordered[0][i]), seed1_s=float(ordered[1][i]),
                seed2_s=float(ordered[2][i])) for i, (q, a, b, c) in enumerate(zip(quantiles, low, median, high)))
        ax.set_ylim(0, 1); plot.legend(ax, header=True, columns=3)
        if fault: ax.axvline(0, color="#A9B1B8", lw=.7, zorder=0)
        else: ax.set_xlim(left=0)
        plot.finish(fig, name, rows, sources=["f0-base", "f0-seed1", "f0-seed2"] +
            (["f1-q50", "f1-seed1", "f1-seed2"] if fault else []),
            note="At each empirical rank, line = median and shading = min/max across three admission orders. Each order contains the same 160 workflows; no pooling into 480 independent observations and no confidence interval. Fault focus is chosen at 50% progress in each order's Mooncake F0.")


def mechanism_figures():
    means=summaries(); data=case("f0-base")
    fig,ax=plot.canvas("", "Measured Python CPU (s)",wide=True)
    groups=[("Foreground dispatch",["foreground_dispatch"],"#777F87",""),
        ("Admission + DAG",["lru_admission","agent_sublease_admission"],"#0072B2",""),
        ("Commit",["copy_commit"],"#B86B00","//"),
        ("Reclaim + AIMD",["tail_reclaim","guarded_aimd_window"],"#007D60","..")]
    rows=[];bottom=np.zeros(3)
    for label,ops,color,hatch in groups:
        vals=[sum(r["cpu_ns"] for r in data[s]["policy_cpu"] if r["operation"] in ops)/1e9 for s in SYSTEMS]
        ax.bar(np.arange(3),vals,bottom=bottom,width=.55,label=label,color=color,hatch=hatch,edgecolor="white",lw=.45)
        rows += [dict(system=s,operation_group=label,cpu_s=v) for s,v in zip(SYSTEMS,vals)]
        bottom+=vals
    ax.set_xticks(range(3),["Mooncake","DRAM-only AegisKV","AegisKV"]);plot.legend(ax,header=True,columns=2)
    plot.finish(fig,"reference-cpu-breakdown",rows,evidence="measured_Python_reference_CPU",
        sources=["f0-base"],note="Exclusive local Python thread CPU with nested measurements subtracted. Global reclaim/AIMD is included once. This is not native serving CPU utilization or all server CPU work.")
    ablations=[("Full", "f0-base", "aegis"), ("No DAG value","f0-no-dag","aegis"),
        ("Strict G > 0","f0-strict-gain","aegis"),("Static Peer cap","f0-static-peer","aegis")]
    fig,ax=plot.canvas("", "Mean WCT (s)",wide=True)
    vals=[means[c][s]["mean_wct_s"] for _,c,s in ablations]
    ax.bar(range(len(vals)),vals,width=.6,color=["#0072B2","#7952A2","#B86B00","#007D60"])
    ax.set_xticks(range(len(vals)),[x[0] for x in ablations])
    plot.finish(fig,"ablation-normal-wct",[dict(ablation=n,case=c,system=s,mean_wct_s=v) for (n,c,s),v in zip(ablations,vals)],
        sources=[x[1] for x in ablations],note="One-factor changes to full AegisKV, same two-round F0 input and CPU quotes. A lower-copy variant can have lower F0 overhead while sacrificing protection; interpret with the failure and coverage results.")
    # Lazy and eager must select the same objects when only evaluation caching changes.
    lazy=data["dram"]; eager=case("f0-eager")["dram"]
    strip=lambda r:(r["span_id"],r["pool_id"],r["chunk_key"],r["status"],r["victims"])
    same=[strip(r) for r in lazy["agent_lease_events"]]==[strip(r) for r in eager["agent_lease_events"]]
    assert same,"eager/lazy changed a semantic admission decision"
    fig,ax=plot.canvas("", "Operation count",height=2.9)
    fig.subplots_adjust(left=.28, top=.77)
    rows=[]
    for i,(name,d) in enumerate([("Lazy",lazy),("Eager",eager)]):
        checks=sum(r["tail_checks"] for r in d["agent_lease_events"])
        evaluations=sum(r["refresh_evaluations"] for r in d["agent_lease_events"])
        ax.bar(i-.17,checks,width=.3,color="#777F87",label="Tail checks" if i==0 else None)
        ax.bar(i+.17,evaluations,width=.3,color="#0072B2",label="Value evaluation" if i==0 else None)
        rows.append(dict(mode=name,tail_checks=checks,refresh_evaluations=evaluations,identical_decisions=same))
    ax.set_xticks([0,1],["Lazy","Eager"]);plot.legend(ax,header=True,columns=1)
    plot.finish(fig,"ablation-lazy-refresh",rows,sources=["f0-base","f0-eager"],
        note="All eligible Q tails are checked before rent in both modes; only unchanged value evaluation may be skipped. Eager/lazy admission decisions are checked identical, including victims. Counts include rejected trials.")
    # Whole-request credit examples live in the editable design figures; real
    # execution trace here checks quota and actual charged bytes separately.
    high=case("f0-dma30")["aegis"]
    observations=high["foreground_budget"]
    totals=defaultdict(lambda:[0,0,0,0])
    for r in observations:
        t=r["timestamp_ns"]/1e9
        a=totals[t];a[0]+=r["decision"]["memory_cap_bytes"]/1024**3
        a[1]+=r["applied_quota_bytes"]/1024**3;a[2]+=r["physical_backup_bytes"]/1024**3
        a[3]+=int(r["observation"]["warning"])
    times=sorted(totals)
    fig,ax=plot.canvas("Execution time (s)", "Across-GPU backup memory (GiB)",wide=True)
    for col,label,color,ls in [(0,"Memory ceiling C","#777F87",":"),(1,"Granted quota Q","#0072B2","-"),(2,"Physical copies","#B86B00","--")]:
        ax.plot(times,[totals[t][col] for t in times],label=label,color=color,ls=ls,lw=1.1)
    plot.legend(ax,header=True,columns=3);ax.set_xlim(times[0],times[-1]);ax.set_ylim(bottom=0)
    plot.finish(fig,"aimd-quota-and-occupancy",[dict(time_s=t,ceiling_gib=totals[t][0],quota_gib=totals[t][1],physical_gib=totals[t][2],warning_targets=totals[t][3]) for t in times],
        sources=["f0-dma30"],note="Sums over eight GPU targets at each 50 ms control window; 30% modeled DMA slowdown. Q is permission, physical occupancy includes pending copies; the DES free is synchronous after fencing.")
    fig, ax = plot.canvas("Execution time (s)", "Warning target-windows (%)", wide=True)
    rows = []
    for label, current, color, style in [
        ("Guarded AIMD", high, "#0072B2", "-"),
        ("Static Peer cap", case("f0-dma30-static")["aegis"], "#007D60", "--"),
    ]:
        bins = defaultdict(lambda: [0, 0])
        for r in current["foreground_budget"]:
            key = int(r["timestamp_ns"] / 1e9)
            bins[key][0] += int(r["observation"]["warning"])
            bins[key][1] += 1
        times = sorted(bins)
        ax.plot([t + .5 for t in times], [100*bins[t][0]/bins[t][1] for t in times],
            color=color, ls=style, label=label, lw=1)
        rows.extend(dict(mode=label, bin_start_s=t, warning_windows=bins[t][0],
            target_windows=bins[t][1], warning_pct=100*bins[t][0]/bins[t][1]) for t in times)
    ax.set_ylim(0, 100); plot.legend(ax, header=True, columns=2)
    plot.finish(fig, "aimd-warning-windows", rows, sources=["f0-dma30", "f0-dma30-static"],
        note="One-second bins of the eight targets' 50 ms observations. A warning is the normalized forward-delay control signal, not a request SLO violation. Time is local to each full execution; no samples are added after completion.")
    fig,ax=plot.canvas("", "Mean WCT (s)")
    values=[means["f0-dma30"]["dram"]["mean_wct_s"],means["f0-dma30"]["aegis"]["mean_wct_s"],means["f0-dma30-static"]["aegis"]["mean_wct_s"]]
    ax.bar(range(3),values,color=["#B86B00","#0072B2","#007D60"],width=.6)
    ax.set_xticks(range(3),["DRAM\nonly","Guarded\nAIMD","Static\nPeer cap"])
    plot.finish(fig,"ablation-aimd-interference",[dict(mode=k,mean_wct_s=v) for k,v in zip(["DRAM-only AegisKV","AegisKV","Static Peer cap"],values)],
        sources=["f0-dma30","f0-dma30-static"],note="Same strong DMA-interference assumption; static Peer still respects the memory ceiling but omits warning-driven AIMD. This controls the memory rule while changing dynamic feedback.")
    # Both sides of Algorithm 2 must be evaluated under matched F0/F1 data.
    rows=[]
    for name,c0,c1 in [("DAG WCT","f0-base","f1-q50"),("Sum recovery","f0-no-dag","f1-no-dag")]:
        rows.append(dict(value_model=name,healthy_wct_s=means[c0]["aegis"]["mean_wct_s"],
            failed_wct_s=means[c1]["aegis"]["mean_wct_s"],
            fault_penalty_s=means[c1]["aegis"]["mean_wct_s"]-means[c0]["aegis"]["mean_wct_s"]))
    write_csv(OUT/"dag-ablation-summary.csv",rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part",choices=["support","core","failure","sensitivity","mechanism","order","all"],default="all")
    args=parser.parse_args()
    plot.OUT=OUT;plot.case=case;plot.finish=finish_current;OUT.mkdir(parents=True,exist_ok=True)
    if args.part in ["support","all"]:plot.support()
    if args.part in ["core","all"]:plot.workflow_views();plot.evaluation()
    if args.part in ["failure","all"]:failure_figures()
    if args.part in ["sensitivity","all"]:sensitivity_figures()
    if args.part in ["mechanism","all"]:mechanism_figures()
    if args.part in ["order","all"]:order_figures()
    for p in [Path(__file__),Path(plot.__file__),
            *[Path(__file__).with_name(n) for n in ["three_system_data.py", "three_system_review_notes.py", "figure_style.py", "paper_paths.py"]]]:
        plot.INPUTS[str(p.relative_to(ROOT))]=sha(p)
    for row in plot.RECORDS:
        if row["name"]=="f0-revisit-tpot-tail":
            d=case("f0-base")
            row["note"]="Inclusive empirical survival of request-mean TPOT; counts per system: "+str({s:sum(r["request_tpot_ns"] is not None for r in d[s]["requests"]) for s in SYSTEMS})
    (OUT/f"statistics-{args.part}-manifest.json").write_text(json.dumps({"figures":plot.RECORDS,"input_bindings":plot.INPUTS},indent=2)+"\n")
    print(f"Rendered {len(plot.RECORDS)} figures ({args.part})",flush=True)


if __name__=="__main__":main()
