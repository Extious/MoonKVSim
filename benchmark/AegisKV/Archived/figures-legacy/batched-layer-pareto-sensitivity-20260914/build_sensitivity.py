"""Three-panel Pareto sensitivity figure, with the user-requested inverted y axes."""
from __future__ import annotations

import csv
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
BASE = OUT.parent / "batched-layer-pipeline-20260914"
SWEEP = OUT.parent / "batched-layer-sweep-20260914"
PARETO = OUT.parent / "batched-layer-pareto-20260914"
spec = importlib.util.spec_from_file_location("batch_base", BASE / "build_batched_pipeline.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pymupdf

BLUE, ORANGE, GREEN, PURPLE = "#0072B2", "#D55E00", "#009E73", "#8C5AA7"
GREY, LIGHT = "#8B929A", "#C3C8CE"
CONDITIONS = ((512,12.5),(512,25),(512,50),(128,25),(256,25),(1024,25),(2048,25))


def dump(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")


def data():
    with (SWEEP/"batch-size-sweep.csv").open() as f:
        previous = {(int(r["M"]),int(r["N"]),float(r["effective_bandwidth_GB_s_assumed"]),int(r["batch_layers"])):r
                    for r in csv.DictReader(f)}
    curves, public, summaries = {}, [], []
    for n, bandwidth in CONDITIONS:
        c,d,size = base.layer_costs(32768,n,bandwidth)
        rows=[]
        for b in range(1,37):
            ev = base.schedule(c,d,batch=b)
            rows.append({"b":b,"bytes":b*size,"wait":base.exact_wait(ev),"total":ev[-1]["compute_end_ms"]})
        for p in rows:
            dom=[q["b"] for q in rows if q["bytes"]<=p["bytes"] and q["wait"]<=p["wait"]
                 and (q["bytes"]<p["bytes"] or q["wait"]<p["wait"])]
            p["pareto"] = not dom
            p["dominated_by"] = dom
            old=previous[32768,n,bandwidth,p["b"]]
            assert float(p["wait"]) == float(old["total_exposed_wait_ms"])
            assert p["bytes"]/2**20 == float(old["initial_HBM_MiB"])
            assert p["total"]-p["wait"] == 36*c
        best=None
        scan=[]
        for p in rows:
            if best is None or p["wait"]<best:
                scan.append(p["b"]);best=p["wait"]
        assert scan==[p["b"] for p in rows if p["pareto"]]
        first_zero=next(p["b"] for p in rows if p["wait"]==0)
        curves[n,bandwidth]=rows
        summaries.append({"replay_tokens":n,"H2D_GB_s_assumed":bandwidth,
                          "first_zero_wait_batch":first_zero,"pareto_batch_layers":scan,
                          "compute_ms":float(36*c)})
        public.extend({"M":32768,"replay_tokens":n,"H2D_GB_s_assumed":bandwidth,
                       "batch_layers":p["b"],"initial_resident_layers":p["b"],
                       "initial_HBM_MiB":p["bytes"]//2**20,"exposed_wait_ms":float(p["wait"]),
                       "wait_exact_numerator":p["wait"].numerator,"wait_exact_denominator":p["wait"].denominator,
                       "total_pipeline_ms":float(p["total"]),"pareto_within_condition":p["pareto"],
                       "dominated_by_batch_layers":";".join(map(str,p["dominated_by"]))} for p in rows)
    assert [p["b"] for p in curves[512,25] if p["pareto"]]==[1,2,3,4,5,7,8,10,13,19,20]
    assert [p["wait"] for p in curves[1024,25]]==[p["wait"] for p in curves[2048,25]]==[Fraction(0)]*36
    with (OUT/"sensitivity-classification.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(public[0]));w.writeheader();w.writerows(public)
    dump("curve-summaries.json",summaries)
    dump("validation.json",{"unique_condition_count":7,"unique_candidate_count":len(public),
                            "original_sweep_points_matched":len(public),
                            "exact_pairwise_and_record_minimum_checks_agree":True,
                            "original_reference_frontier_unchanged":True,
                            "1024_and_2048_wait_curves_exactly_identical":True,
                            "pareto_scope":"Each fixed (replay length, bandwidth) condition separately",
                            "physical_experiments":0,"independent_statistical_replicates":None})
    return curves


def setup_axis(ax, ymax, yticks, wide=False):
    # Explicit user confirmation: low waiting values at the top, high at the bottom.
    ax.set_xlim(0,37)
    ax.set_ylim(ymax,-.035*ymax)
    ax.set_yticks(yticks)
    ax.set_xticks([1,6,12,18,24,30,36])
    ax.tick_params(labelsize=8)
    ax.set_xlabel("每批层数 / 初始驻留层数",fontsize=8.3,labelpad=5)
    ax.set_ylabel("累计加载等待（ms）",fontsize=8.5)
    ax.set_axisbelow(True);ax.grid(alpha=.15)
    top=ax.secondary_xaxis("top",functions=(lambda x:x*128,lambda x:x/128))
    ticks=[1,6,12,18,24,30,36] if wide else [1,12,24,36]
    top.set_xticks([b*128 for b in ticks]);top.tick_params(labelsize=7.5,pad=3)


def draw_curves(ax, series):
    # Draw all lines, then dominated points, then frontier points. This keeps
    # overlapping zero-wait tails from covering another condition's frontier.
    for rows,color,style,label in series:
        ax.plot([p["b"] for p in rows],[float(p["wait"]) for p in rows],
                color=color,ls=style,lw=1.0,label=label,zorder=1)
    for rows,color,style,label in series:
        dominated=[p for p in rows if not p["pareto"]]
        ax.scatter([p["b"] for p in dominated],[float(p["wait"]) for p in dominated],
                   marker="x",s=10,linewidths=.65,color=color,alpha=.48,zorder=2)
    for rows,color,style,label in series:
        front=[p for p in rows if p["pareto"]]
        ax.scatter([p["b"] for p in front],[float(p["wait"]) for p in front],
                   marker="o",s=17,linewidths=.35,edgecolors="white",color=color,zorder=4)


def render(curves):
    fig=plt.figure(figsize=(178/25.4,180/25.4))
    fig.text(.065,.960,"帕累托前沿随 H2D 带宽与重放长度变化",fontsize=11.5)
    fig.text(.065,.928,"解析估算，非实测｜Qwen3-8B，36 层｜历史 32K｜有效算力假设为 100 TFLOP/s",fontsize=8)
    fig.text(.065,.896,"上横轴：初始 HBM（MiB）；下横轴：每批 / 初始驻留层数。每层 128 MiB。",fontsize=8)
    fig.legend(handles=[Line2D([],[],marker="o",linestyle="none",color=BLUE,markersize=4.5,label="该曲线内的帕累托点"),
                        Line2D([],[],marker="x",linestyle="none",color=GREY,markersize=4.5,label="被支配点")],
               loc="center",bbox_to_anchor=(.47,.860),ncol=2,frameon=False,fontsize=8,
               handlelength=1.2,columnspacing=2)
    fig.text(.065,.817,"(a) 基准：25 GB/s，512 token",fontsize=9.4)
    fig.text(.580,.817,"(b) H2D 带宽对比：512 token",fontsize=9.4)
    ax=fig.add_axes([.105,.550,.35,.214])
    setup_axis(ax,25,[0,5,10,15,20,25])
    reference=curves[512,25]
    ax.plot([p["b"] for p in reference],[float(p["wait"]) for p in reference],color=LIGHT,lw=1,zorder=1)
    for keep,color,marker in [(False,GREY,"x"),(True,BLUE,"o")]:
        pp=[p for p in reference if p["pareto"]==keep]
        ax.scatter([p["b"] for p in pp],[float(p["wait"]) for p in pp],
                   color=color,marker=marker,s=19,linewidths=.7,zorder=3 if keep else 2)
    ax.annotate("20 层起零等待",xy=(20,0),xytext=(.68,.59),textcoords="axes fraction",
                ha="center",fontsize=7.7,arrowprops={"arrowstyle":"->","lw":.65,"color":GREY})
    ax.text(.49,.15,"5 层支配 6 层",transform=ax.transAxes,fontsize=7.6,color="#526574")
    ax=fig.add_axes([.605,.550,.35,.214])
    setup_axis(ax,225,[0,50,100,150,200])
    bandwidth_series=[(curves[512,50],GREEN,":","50 GB/s"),
                      (curves[512,12.5],ORANGE,"-","12.5 GB/s"),
                      (curves[512,25],BLUE,"--","25 GB/s")]
    draw_curves(ax,bandwidth_series)
    ax.legend(handles=[Line2D([],[],color=c,ls=s,lw=1.1,label=label)
                       for _,c,s,label in [bandwidth_series[1],bandwidth_series[2],bandwidth_series[0]]],
              loc="lower right",frameon=False,fontsize=8,handlelength=2.2)
    fig.text(.065,.471,"(c) 重放 token 数对比：H2D 带宽固定为 25 GB/s",fontsize=9.7)
    ax=fig.add_axes([.105,.165,.85,.260])
    setup_axis(ax,160,[0,25,50,75,100,125,150],wide=True)
    replay_series=[(curves[1024,25],GREEN,":","1024 / 2048 token（等待曲线重合）"),
                   (curves[128,25],ORANGE,"-","128 token"),
                   (curves[256,25],PURPLE,"-.","256 token"),
                   (curves[512,25],BLUE,"--","512 token")]
    draw_curves(ax,replay_series)
    ax.legend(handles=[Line2D([],[],color=c,ls=s,lw=1.1,label=label)
                       for _,c,s,label in replay_series[1:]+replay_series[:1]],
              loc="lower right",frameon=False,fontsize=8.2,handlelength=2.3,labelspacing=.55)
    fig.text(.065,.074,"纵轴已翻转：越靠上，等待越少。各曲线分别判定帕累托，不跨带宽或重放条件排名。",fontsize=8)
    fig.text(.065,.042,"仅预取下一批、整批就绪后切换；成本仅计初始 HBM。不同重放长度的总计算时间不同。",fontsize=7.9)
    for ext in ("png","pdf","svg"):
        fig.savefig(OUT/f"pareto-sensitivity.{ext}",dpi=300,facecolor="white")
    plt.close(fig)
    with pymupdf.open(OUT/"pareto-sensitivity.pdf") as pdf:
        assert abs(pdf[0].rect.width/72*25.4-178)<.01
        for dpi in (96,150):
            pdf[0].get_pixmap(dpi=dpi,alpha=False).save(OUT/f"pareto-sensitivity.pdf-{dpi}dpi.png")


def main():
    curves=data()
    render(curves)
    dump("parameters.json",{
        "model":"Qwen3-8B","M":32768,"effective_compute_TFLOP_s_assumed":100,
        "batch_layers_and_initial_resident_layers":list(range(1,37)),
        "reference":{"H2D_GB_s":25,"replay_tokens":512},
        "right_panel":{"replay_tokens":512,"H2D_GB_s":[12.5,25,50]},
        "bottom_panel":{"H2D_GB_s":25,"replay_tokens":[128,256,512,1024,2048]},
        "y_orientation":"Low values at top, high values at bottom; explicitly confirmed by user",
        "y_scales":"All linear ms; range chosen separately for each panel",
        "pareto_comparison_scope":"Within each fixed bandwidth/replay condition only",
        "objectives":["minimize initial Peer HBM historical KV bytes","minimize exposed loading wait"],
        "overlap_display":"The exactly identical 1024 and 2048 replay waiting curves share one labeled visual line; both are retained in the CSV",
        "layout":"Reference upper left; bandwidth upper right; replay below both upper panels",
        "cost_scope":"Initial HBM only; no bandwidth procurement cost, backup maintenance, foreground cost or lifecycle cost",
        "schedule":"Next batch only, whole-batch ready, actual final partial batch, copied KV retained",
        "evidence":"Analytical, not measured or calibrated","placed_width_mm":178,
        "unique_condition_count":7,"unique_candidate_count":252,
    })
    sources=[BASE/"build_batched_pipeline.py",SWEEP/"batch-size-sweep.csv",PARETO/"pareto-classification.csv",PARETO/"batch-size-pareto.pdf"]
    dump("MANIFEST.json",{
        "sources_sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "files_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir())
                         if p.suffix in {".py",".csv",".json",".png",".pdf",".svg",".md"}
                         and p.name not in {"MANIFEST.json","REVIEW.json","figure-lesson.json"}},
    })
    print(json.dumps({"candidate_count":252,"conditions":7,"panels":3,"y_orientation":"low at top, high at bottom"}))


if __name__=="__main__":
    main()
