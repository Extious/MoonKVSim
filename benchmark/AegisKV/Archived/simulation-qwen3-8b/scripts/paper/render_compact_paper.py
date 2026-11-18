"""PaperBanana compact edition: new views of existing, immutable evidence.

No experiments or algorithm implementation run here. The original 51 figure
sets remain available; only the overview is replaced (with a saved original).
"""
from __future__ import annotations

import csv
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pymupdf

import agent_lease_style as style
import build_paper_story_diagrams as native
import render_paper_story as plot
from build_paper_story_diagrams import Diagram, INK, GRAY, BLUE, ORANGE, GREEN, PALE, PB, PO, PG
from paper_paths import ROOT
from three_system_data import SYSTEMS, LABELS, sha

OUT = ROOT / "output/pdf/aegiskv-agent-lease-20260908"
ART = ROOT / "output/agent-lease-20260908"
INPUTS = {}


def rows(path):
    INPUTS[str(path.relative_to(ROOT))] = sha(path)
    with path.open() as f:
        return list(csv.DictReader(f))


def source(name):
    return rows(OUT / (name + ".csv"))


def recovery_exposure():
    path = ROOT / "benchmark/AegisKV/experiments/results/paper/data/motivation-real-cc/real-cc-example-failure-position.csv"
    values = rows(path)
    assert len(values) == 5
    exported = []
    for r in values:
        t, s, exposed = (float(r[k]) for k in ["recompute_s", "slack_s", "delta_wct_s"])
        assert np.isclose(exposed, max(0, t-s))
        exported.append(dict(branch="A"+str(int(r["branch_index"])+1),
            recompute_s=t, slack_s=s, absorbed_s=t-exposed, exposed_s=exposed,
            workflow_id=r["workflow_id"], failure_time_s=r["failure_time_s"],
            predictor_model=r["predictor_model"], predictor_topology=r["predictor_topology"],
            predictor_accelerator=r["predictor_accelerator"],
            evidence="trace_anchored_counterfactual"))
    fig, ax = plot.canvas("Modeled recovery delay (s)", "")
    fig.subplots_adjust(left=.14, right=.97, top=.765, bottom=.225)
    y = np.arange(5)
    absorbed = [r["absorbed_s"] for r in exported]
    exposed = [r["exposed_s"] for r in exported]
    ax.barh(y, absorbed, height=.57, color="#DDEEE8", edgecolor=GREEN,
            hatch="///", linewidth=.65, label="Absorbed by parallel work")
    ax.barh(y, exposed, left=absorbed, height=.57, color="#B83C46",
            label="Exposed to workflow")
    ax.set_yticks(y, [r["branch"] for r in exported]); ax.invert_yaxis()
    ax.set_xlim(0, 51); ax.set_xticks([0, 20, 40])
    ax.grid(False); ax.grid(axis="x", color="#DFE5EA", lw=.55)
    plot.legend(ax, columns=1)
    plot.finish(fig, "motivation-recovery-exposure", exported,
        evidence="trace_anchored_counterfactual", sources=[str(path.relative_to(ROOT))],
        note="Five separate branch-fault counterfactuals in one reconstructed trace fan-out, at 349.5 s; max(0, recompute minus join gap). Frozen AIConfigurator Qwen3-235B-A22B/A100-80GB/TP8-PP4-EP8 model, not a measured failure or the Qwen3-8B evaluation. Other branches and queues are held unchanged.")


def fault_workflows():
    values = source("f1-q50-workflow-penalty")
    all_values = [float(r[s]) for q in [25,50,75]
                  for r in source(f"f1-q{q}-workflow-penalty") for s in SYSTEMS]
    margin = .05*np.ptp(all_values)
    fig, ax = plot.canvas("Workflow (same order as no failure)", "F1 − F0 WCT (s)", wide=True)
    for s in SYSTEMS:
        plot.line(ax,s,[int(r["workflow_rank"]) for r in values],
                  [float(r[s]) for r in values],thin=True)
    ax.axhline(0,color=GRAY,lw=.85,zorder=0)
    ax.set_xlim(1,160);ax.set_xticks([1,40,80,120,160])
    ax.set_ylim(min(all_values)-margin,max(all_values)+margin)
    plot.legend(ax,columns=3)
    before=sha(OUT/"f1-q50-workflow-penalty.csv")
    plot.finish(fig,"f1-q50-workflow-penalty",values,
        sources=["f0-base","f1-q50"],
        note="Only the ordinate label is shortened. Same 160 paired workflow values and common q25/q50/q75 limits; original CSV bytes must remain unchanged.")
    assert sha(OUT/"f1-q50-workflow-penalty.csv")==before


def resource_cost():
    cpu = source("reference-cpu-breakdown")
    service = source("f0-revisit-controller-breakdown")
    traffic = source("f0-revisit-traffic-breakdown")
    transfer = source("f0-revisit-transfer-service_slowdown")
    data = {}
    for s in SYSTEMS:
        sv = next(r for r in service if r["system"] == s)
        tr = next(r for r in traffic if r["system"] == s)
        data[s] = [sum(float(r["cpu_s"]) for r in cpu if r["system"] == s),
            float(sv["foreground_lookup"])+float(sv["admission"]),
            float(tr["dram"])+float(tr["peer"]), float(tr["foreground"]),
            float(np.percentile([float(r["service_slowdown"]) for r in transfer if r["system"]==s],95))]
    specs = [("Reference Python CPU", "s", "measured_Python_reference_CPU"),
        ("Modeled CPU service", "s", "modeled_exploration"),
        ("DRAM + Peer write bytes", "TiB", "modeled_exploration"),
        ("Foreground GET bytes", "TiB", "modeled_exploration"),
        ("GET service slowdown P95", "ratio_to_exclusive_service", "modeled_exploration")]
    fig, ax = plot.canvas("Ratio to Mooncake (log scale)", "", wide=True, height=3.15)
    fig.subplots_adjust(left=.375, right=.978, top=.80, bottom=.19)
    exported = []
    for j,s in enumerate(SYSTEMS):
        values = np.asarray(data[s])/data["mooncake"]
        y = np.arange(len(specs))+(j-1)*.19
        ax.plot(values, y, ls="none", marker=style.MARKERS[s], color=style.COLORS[s],
                ms=5, markerfacecolor="white", label=LABELS[s])
        for i, (label, unit, evidence) in enumerate(specs):
            exported.append(dict(metric=label, unit=unit, evidence=evidence, system=s,
                value=data[s][i], mooncake_value=data["mooncake"][i], ratio=float(values[i])))
    ax.axvline(1, color=GRAY, lw=.8, zorder=0)
    ax.set_yticks(range(len(specs)), [r[0] for r in specs]); ax.invert_yaxis()
    ax.set_xscale("log"); ax.set_xlim(.65, 9)
    ax.set_xticks([1, 2, 4, 8], ["1", "2", "4", "8"])
    from matplotlib.ticker import NullLocator
    ax.xaxis.set_minor_locator(NullLocator())
    ax.grid(False); ax.grid(axis="x", color="#DFE5EA", lw=.55)
    plot.legend(ax, columns=3)
    plot.finish(fig, "evaluation-resource-cost", exported,
        evidence="mixed_reference_CPU_and_simulation",
        sources=["reference-cpu-breakdown.csv", "f0-revisit-controller-breakdown.csv",
                 "f0-revisit-traffic-breakdown.csv", "f0-revisit-transfer-service_slowdown.csv"],
        note="Each row is a separate metric divided by that metric in Mooncake. Python thread CPU is measured; controller service, bytes and GET contention use frozen DES. No sum across rows. A lower GET byte count can reflect more misses, not efficiency. GET samples are system-specific successful reads. Absolute values and units are retained in CSV.")


def native_forward():
    # Recompose the two already audited paired-ratio tables without pooling
    # conditions or taking a ratio of medians.
    exported = source("native-forward-b1") + source("native-forward-b4")
    assert len(exported) == 120
    modes = [("none", "No copy", GRAY, "o"), ("dram_put", "DRAM write", ORANGE, "s"),
        ("peer_in", "Peer input", BLUE, "^"), ("peer_out", "Peer output", "#7952A2", "D")]
    conditions = [(b,t) for b in [1,4] for t in [512,2048,4096]]
    fig, ax = plot.canvas("Prompt length (Ki tokens)", "Forward slowdown (×)", wide=True, height=3.1)
    fig.subplots_adjust(left=.115, right=.978, top=.81, bottom=.255)
    for j,(mode,label,color,marker) in enumerate(modes):
        for i,(b,t) in enumerate(conditions):
            v = [float(r["slowdown"]) for r in exported if int(r["batch"])==b and int(r["prompt_tokens"])==t and r["mode"]==mode]
            assert len(v)==5
            mid=float(np.median(v))
            ax.errorbar(i+(j-1.5)*.12, mid, yerr=[[mid-min(v)],[max(v)-mid]],
                fmt=marker, color=color, markerfacecolor="white", ms=4.5,
                capsize=2.3, elinewidth=.85, label=label if i==0 else None)
    ax.axhline(1,color=GRAY,lw=.75,zorder=0)
    ax.axvline(2.5,color="#BBC4CD",lw=.65,zorder=0)
    ax.set_xlim(-.5,5.5); ax.set_ylim(.96,1.37); ax.set_yticks([1,1.1,1.2,1.3])
    ax.set_xticks(range(6),["0.5","2","4"]*2)
    ax.text(1,1.338,"Batch 1",ha="center",fontsize=10)
    ax.text(4,1.338,"Batch 4",ha="center",fontsize=10)
    plot.legend(ax,columns=4)
    plot.finish(fig,"evaluation-native-interference",exported,evidence="physical_microbenchmark",
        sources=["native-forward-b1.csv", "native-forward-b4.csv"],
        note="One shared axis for batch 1 and 4, three discrete prompt lengths per group; no lines between categorical conditions. 120 existing observations at extra 8 GiB; Qwen3-8B BF16 SDPA, one exclusive 2xL40S allocation. Points are median of five within-block ratios; whiskers are min/max, not CI. Direction is relative to the foreground GPU. No system WCT is measured.")


def robustness():
    # All one-factor setting changes, once each. The default repeated in several
    # legacy sweep CSVs is deliberately represented only once.
    merged = {}
    for name in ["bandwidth", "concurrency", "dram-capacity", "cpu-quote", "dma"]:
        if name == "dram-capacity":
            # This old figure plotted hits. WCT comes from that exact audited
            # execution's summary instead, not from the hit-rate ordinate.
            source("sensitivity-"+name)
            vals = {}
            for s in SYSTEMS:
                p = ART / f"data/f0-dram250/{s}.json"
                INPUTS[str(p.relative_to(ROOT))] = sha(p)
                vals[s] = json.loads(p.read_text())["summary"]["mean_wct_s"]
            merged["f0-dram250"] = vals
        else:
            for r in source("sensitivity-"+name):
                vals = {s: float(r[s]) for s in SYSTEMS}
                if r["case"] in merged: assert vals == merged[r["case"]]
                merged[r["case"]] = vals
    settings = [("Default", "f0-base"), ("Bandwidth: 5 GB/s", "f0-bw5"),
        ("Bandwidth: 50 GB/s", "f0-bw50"), ("DRAM: 250 GB", "f0-dram250"),
        ("Active workflows: 32", "f0-c32"), ("CPU service quote: 2×", "f0-cpu2"),
        ("DMA forward coefficient: 5%", "f0-dma5"),
        ("DMA forward coefficient: 30%", "f0-dma30")]
    assert {case for _,case in settings} == set(merged)
    fig, ax = plot.canvas("Mean WCT change from matched Mooncake (%)", "", wide=True, height=3.65)
    fig.subplots_adjust(left=.395,right=.978,top=.84,bottom=.165)
    exported=[]
    for j,s in enumerate(SYSTEMS):
        vals = [(merged[c][s]/merged[c]["mooncake"]-1)*100 for _,c in settings]
        ax.plot(vals, np.arange(len(settings))+(j-1)*.19, ls="none",
            marker=style.MARKERS[s],color=style.COLORS[s],markerfacecolor="white",ms=5,label=LABELS[s])
        exported += [dict(setting=label,case=c,system=s,mean_wct_s=merged[c][s],
            mooncake_mean_wct_s=merged[c]["mooncake"],relative_change_pct=v)
            for (label,c),v in zip(settings,vals)]
    ax.axvline(0,color=GRAY,lw=.8,zorder=0)
    ax.set_yticks(range(len(settings)),[r[0] for r in settings]);ax.invert_yaxis()
    lo=min(r["relative_change_pct"] for r in exported);hi=max(r["relative_change_pct"] for r in exported)
    ax.set_xlim(min(-3,lo-1),hi+1.2)
    ax.grid(False); ax.grid(axis="x",color="#DFE5EA",lw=.55)
    plot.legend(ax,columns=3)
    plot.finish(fig,"evaluation-configuration-effects",exported,sources=[c for _,c in settings],
        note="Eight distinct configurations from frozen paired executions, three systems per configuration. Each nondefault row changes one factor; values are relative to Mooncake in the same row. CPU/DMA coefficients are model assumptions. No connecting line, fitted trend or confidence interval across heterogeneous settings. Full raw means retained in CSV.")


def overview():
    native.OUT=OUT
    d=Diagram("system-overview",1030)
    d.text("workflow-title","Workflow DAG",18,10,300,bold=True)
    for key,y,color,fill in [("A",86,ORANGE,PO),("B",166,BLUE,PB)]:
        d.box("agent-"+key,key,26,y, 60,44,fill=fill,stroke=color,shape="ellipse")
        d.path("join-"+key,[(86,y+22),(134,y+22),(134,148),(206,148)],color=color)
    d.box("join","Join",206,126,90,44,fill=PALE)
    d.text("value-title","1   Workflow value",356,10,462,bold=True)
    d.text("value-detail","Slack + joint WCT benefit",356,57,462,45)
    d.text("admission-title","2   Per-tier admission",356,131,462,bold=True)
    d.text("admission-detail","Shared chunks; tail eviction",356,177,465,45)
    d.path("dag-value",[(296,148),(329,148),(329,79),(356,79)],dashed=True)
    d.path("value-admit",[(568,104),(568,131)],dashed=True)
    d.text("controller-title","3   Peer HBM control",861,10,325,44,bold=True)
    d.text("controller-detail","Memory headroom\n+ forward feedback",864,69,320,82)
    d.path("admit-source",[(568,225),(568,269),(246,269),(246,310)],dashed=True)
    d.text("admit-label","Independent pool decisions",281,272,470,35,color=GRAY)
    d.path("quota",[(947,153),(947,310)],dashed=True)
    d.text("quota-label","Grant / revoke",751,252,190,42,color=GRAY,align="right")
    d.path("feedback",[(1133,310),(1133,250),(1189,250),(1189,165),(1115,165)],dashed=True)
    d.text("feedback-label","Observe",970,262,160,35,color=GRAY)
    for key,x,width,label in [("source",18,455,"Source worker"),("peer",690,490,"Peer worker")]:
        d.box(key+"-resource","",x,310,width,300,stroke=GRAY)
        d.box(key+"-head",label,x,310,width,47,stroke=GRAY,fill=PALE,bold=True)
    d.text("source-hbm","Primary HBM",41,367,420)
    d.chunks("source-c",["C0","C1","C2"],54,419,cell=106,height=48)
    d.text("seal-label","C0 / C1 sealed; C2 active",42,481,420,44)
    d.text("shared-label","A + B reference the same C0",42,546,420,45)
    d.text("peer-primary","Foreground primary HBM",712,364,450,39)
    d.chunks("peer-primary-c",["P0","P1"],723,407,cell=104,height=43)
    d.text("peer-backup","Revocable backup HBM",712,455,450,38,color=BLUE)
    d.chunks("peer-backup-c",["C0","C1"],723,497,cell=104,height=43,color=BLUE,fill=PB)
    d.text("peer-ack","Copy ACK → readable",712,560,450,40,color=BLUE)
    d.path("peer-copy",[(473,443),(598,443),(598,519),(723,519)],color=BLUE)
    d.text("peer-copy-label","Peer copy",486,380,188,46,color=BLUE,align="center")
    for key,x,width,label in [("store",18,455,"DRAM store"),("recovery",690,490,"Recovery worker")]:
        d.box(key+"-resource","",x,760,width,205,stroke=GRAY)
        d.box(key+"-head",label,x,760,width,47,stroke=GRAY,fill=PALE,bold=True)
    d.chunks("dram-c",["C0","C1"],66,834,cell=113,height=48,color=ORANGE,fill=PO)
    d.text("dram-ack","Copy ACK → readable",42,911,420,40,color=ORANGE)
    d.text("new-primary","New primary HBM after failover",707,810,460,43)
    d.chunks("loaded-c",["C0","C1"],714,859,cell=104,height=45,color=GREEN,fill=PG)
    d.chunks("recomputed-c",["C2"],986,859,cell=104,height=45)
    d.text("loaded-label","Loaded prefix",708,920,236,35,color=GREEN)
    d.text("recompute-label","Recompute",977,920,192,35)
    d.path("dram-copy",[(245,610),(245,760)],color=ORANGE)
    d.text("dram-copy-label","Independent\nDRAM copy",265,657,302,82,color=ORANGE)
    d.path("peer-restore",[(947,610),(947,760)],color=GREEN)
    d.text("peer-restore-label","Restore\nfrom Peer",965,658,214,80,color=GREEN)
    d.path("dram-restore",[(473,862),(690,862)],color=GREEN)
    d.text("dram-restore-label","Restore\nfrom DRAM",490,780,180,79,color=GREEN,align="center")
    d.text("legend","Solid: KV transfer    |    Dashed: control",18,982,1164,38,align="center")
    d.write()
    tmp=ROOT/"tmp/pdfs/compact-paper-native";tmp.mkdir(parents=True,exist_ok=True)
    source=OUT/"system-overview.drawio"
    ids=[c.get("id") for c in ET.parse(source).iter("mxCell")];assert len(ids)==len(set(ids))
    for ext in ["png","svg","pdf"]:
        dest=tmp/"system-overview.pdf" if ext=="pdf" else OUT/("system-overview."+ext)
        cmd=[native.CLI,"-x","-f",ext,"-e","-b","0","-o",str(dest),str(source)]
        if ext=="pdf":cmd.insert(5,"--crop")
        if ext=="png":cmd[5:5]=["-s","1.5"]
        subprocess.run(cmd,check=True,stdout=subprocess.DEVNULL)
    with pymupdf.open(tmp/"system-overview.pdf") as src:
        target=pymupdf.open();page=target.new_page(width=504,height=src[0].rect.height*504/src[0].rect.width)
        page.show_pdf_page(page.rect,src,0)
        target.set_metadata({"title":"AegisKV system overview","subject":"Design illustration; independent source-owned HBM and DRAM copies"})
        target.embfile_add("system-overview.drawio",source.read_bytes())
        target.save(OUT/"system-overview.pdf",garbage=4,deflate=True,no_new_id=True)
        height=page.rect.height/72
    plot.RECORDS.append(dict(name="system-overview",evidence="design",width_in=7,height_in=height,
        note="Same C0/C1 in independent source-owned Peer and DRAM copies; recovery into new C0/C1 primary plus C2 recomputation. P0/P1 are unrelated foreground objects and never the restore destination. Algorithm 2 internals remain deferred; AIMD observes foreground independently.",
        sources=[str(Path(__file__).relative_to(ROOT))],
        files={e:sha(OUT/("system-overview."+e)) for e in ["pdf","svg","png","drawio"]}))


def main():
    style.install(plot);plot.OUT=OUT
    for fn in [recovery_exposure,fault_workflows,resource_cost,native_forward,robustness,overview]:fn()
    for p in [Path(__file__),Path(style.__file__),Path(native.__file__),Path(plot.__file__),
              Path(__file__).with_name("figure_style.py")]:INPUTS[str(p.relative_to(ROOT))]=sha(p)
    (OUT/"compact-manifest.json").write_text(json.dumps(dict(figures=plot.RECORDS,input_bindings=INPUTS),indent=2)+"\n")
    print(json.dumps(dict(exported=len(plot.RECORDS),inputs=len(INPUTS))))


if __name__=="__main__":main()
