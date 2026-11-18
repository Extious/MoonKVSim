"""Render paired original-workload F0 cache, WCT and critical-path figures."""
from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np
import pymupdf

import agent_lease_style as style
from reduce_single_pass_f0 import ROOT, sha, csv_write

ART = ROOT / "output/aegiskv-single-pass-20260909"
OUT = ROOT / "output/pdf/aegiskv-single-pass-20260909"
SYSTEMS = ("mooncake", "dram", "aegis")


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|"*len(headers)] +
                     ["| " + " | ".join(map(str, row)) + " |" for row in rows])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    style.install(SimpleNamespace())
    data = {}
    inputs = {}
    for s in SYSTEMS:
        p = ART / "data" / f"{s}.diagnosis.json.gz"
        with gzip.open(p, "rt") as stream:
            data[s] = json.load(stream)
        inputs[str(p.relative_to(ROOT))] = sha(p)
        assert data[s]["summary"]["rounds"] == 1
    assert len({d["source_snapshot_sha256"] for d in data.values()}) == 1
    assert len({d["cpu_quotes_sha256"] for d in data.values()}) == 1
    assert all(d["parameters"] == data["mooncake"]["parameters"] for d in data.values())
    ws = {s: {r["workflow_id"]: r for r in d["workflows"]} for s, d in data.items()}
    order = sorted(ws["mooncake"], key=lambda k: (ws["mooncake"][k]["wct_s"], k))
    assert len(order) == 160 and all(set(w) == set(order) for w in ws.values())
    paired, stats = [], {}
    for s in SYSTEMS:
        rows = []
        for rank, wid in enumerate(order, 1):
            r, baseline = ws[s][wid], ws["mooncake"][wid]
            assert r["prompt_tokens"] == baseline["prompt_tokens"]
            row = dict(workflow_rank=rank, **r,
                       delta_wct_s=r["wct_s"]-baseline["wct_s"],
                       delta_total_hit_tokens=r["total_hit_tokens"]-baseline["total_hit_tokens"],
                       delta_prefill_tokens=r["prefill_executed_tokens"]-baseline["prefill_executed_tokens"],
                       delta_release_s=(r["release_ns"]-baseline["release_ns"])/1e9,
                       delta_completion_s=(r["completion_ns"]-baseline["completion_ns"])/1e9)
            assert abs(row["delta_completion_s"]-row["delta_release_s"]-row["delta_wct_s"]) < 1e-10
            paired.append(row)
            rows.append(row)
        stats[s] = dict(**data[s]["summary"],
                        slower=sum(r["delta_wct_s"] > 0 for r in rows),
                        faster=sum(r["delta_wct_s"] < 0 for r in rows),
                        equal=sum(r["delta_wct_s"] == 0 for r in rows),
                        unchanged_hit_workflows=sum(r["delta_total_hit_tokens"] == 0 for r in rows),
                        mean_wct_change_pct=100*(data[s]["summary"]["mean_wct_s"]/data["mooncake"]["summary"]["mean_wct_s"]-1))
    csv_write(OUT / "all-workflows-paired.csv", paired)
    focal = max((r for r in paired if r["system"] == "aegis"), key=lambda r: r["delta_wct_s"])
    wid = focal["workflow_id"]
    figures = []

    def save(fig, name, title, caption, caption_en, rows):
        files = {}
        for ext in ("pdf", "png", "svg"):
            p = OUT/f"{name}.{ext}"
            fig.savefig(p, dpi=220)
            files[ext] = sha(p)
        csv_write(OUT/f"{name}.csv", rows)
        files["csv"] = sha(OUT/f"{name}.csv")
        with pymupdf.open(OUT/f"{name}.pdf") as doc:
            assert len(doc) == 1 and abs(doc[0].rect.width-504) < .01
            spans = [s for b in doc[0].get_text("dict")["blocks"] if "lines" in b
                     for line in b["lines"] for s in line["spans"] if s["text"].strip()]
            assert min(s["size"] for s in spans) >= 9.9
            assert all(s["bbox"][0] >= -.1 and s["bbox"][1] >= -.1 and
                       s["bbox"][2] <= doc[0].rect.width+.1 and s["bbox"][3] <= doc[0].rect.height+.1 for s in spans)
            doc[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).save(OUT/f"{name}-pdf-preview.png")
        figures.append(dict(name=name, title=title, caption=caption, caption_en=caption_en,
                            files=files, directory=str(OUT.relative_to(ROOT)),
                            width_in=float(fig.get_figwidth()), height_in=float(fig.get_figheight()),
                            run_scope="original_single_pass_F0", evidence="uncalibrated_frozen_DES",
                            complete_runs=3, runs_per_system=1, workflows_per_run=160,
                            requests_per_run=1304, reused_campaign="agent80 F0", visual_review="PENDING"))
        plt.close(fig)

    x = np.arange(1, 161)
    fig, ax = style.canvas("Workflow (single-pass Mooncake WCT order)", "WCT − Mooncake WCT (s)", wide=True, height=3.25)
    fig.subplots_adjust(left=.135, right=.975, top=.81, bottom=.205)
    for s in SYSTEMS:
        rr = [r for r in paired if r["system"] == s]
        style.line(ax, s, x, [r["delta_wct_s"] for r in rr], thin=True)
    vals = [r["delta_wct_s"] for r in paired]
    ax.set(xlim=(1,160), xticks=[1,40,80,120,160], ylim=(min(vals)-5,max(vals)+12))
    ax.axhline(0, color=style.GRAY, lw=.75)
    ax.annotate(f"{wid[:8]}: +{focal['delta_wct_s']:.2f} s",
                xy=(focal["workflow_rank"], focal["delta_wct_s"]),
                xytext=(max(34,focal["workflow_rank"]+18), max(vals)+5), fontsize=10,
                color=style.BLUE, arrowprops=dict(arrowstyle="->",color=style.BLUE,lw=.8))
    style.legend(ax)
    save(fig, "eval-workflow-delay", "原始 160 个 Workflow 单轮无故障的 WCT 差值",
         f"每个原始 DAG 执行一次，共 1,304 个请求；三系统各一次完整无故障模拟，按同 ID 配对并共享单轮 Mooncake WCT 排序。AegisKV 有 {stats['aegis']['slower']} 个更慢、{stats['aegis']['faster']} 个更快；最大增量 {focal['delta_wct_s']:.3f} s。均值 {stats['mooncake']['mean_wct_s']:.3f}/{stats['dram']['mean_wct_s']:.3f}/{stats['aegis']['mean_wct_s']:.3f} s；不作重复运行显著性推断。",
         "Same-ID WCT differences for 160 original workflows, each DAG executed once (1,304 requests). One fault-free simulation per system; the common order is the single-pass Mooncake WCT. All positive and negative differences are retained. These are descriptive, uncalibrated simulations without replicate confidence intervals.", paired)

    fig, axes = plt.subplots(2,1,figsize=(7,4.35),sharex=True,gridspec_kw=dict(height_ratios=[2.1,1]))
    fig.subplots_adjust(left=.14,right=.975,top=.855,bottom=.14,hspace=.42)
    for s in SYSTEMS:
        rr = [r for r in paired if r["system"] == s]
        style.line(axes[0],s,x,[r["total_hit_pct"] for r in rr],thin=True)
        style.line(axes[1],s,x,[r["delta_total_hit_tokens"] for r in rr],thin=True)
    for ax in axes:
        ax.set_xlim(1,160)
        ax.grid(axis="y",color="#DFE5EA",lw=.55)
    axes[0].set_ylabel("Hit / prompt tokens (%)")
    axes[0].set_ylim(0,max(r["total_hit_pct"] for r in paired)*1.17)
    axes[0].text(.02,.92,"(a) Local HBM + DRAM + Peer",transform=axes[0].transAxes,fontsize=10)
    axes[1].set_ylabel("Hit-token difference\nfrom Mooncake")
    axes[1].set_xlabel("Workflow (same single-pass Mooncake order)")
    axes[1].set_xticks([1,40,80,120,160])
    axes[1].set_ylim(-10,max(64,max(r["delta_total_hit_tokens"] for r in paired))+28)
    axes[1].set_yticks([0,64])
    axes[1].text(.02,.85,f"(b) AegisKV: {stats['aegis']['unchanged_hit_workflows']}/160 unchanged; DRAM = Peer = 0",transform=axes[1].transAxes,fontsize=10)
    style.legend(axes[0])
    save(fig, "eval-initial-reuse", "原始 Workflow 全部请求的缓存命中",
         f"与图 5 完全相同的单轮 F0 运行、160 个 ID 及排序。上图为每个 Workflow 全部请求命中的 token 数（本地 HBM + DRAM + Peer）除以其全部 prompt token 数，冷请求保留；下图为命中 token 数相对同 ID Mooncake 的差值。所有 Workflow 的 DRAM 和 Peer 命中均为零；总体命中率为 {stats['mooncake']['total_hit_pct']:.6f}%、{stats['dram']['total_hit_pct']:.6f}%、{stats['aegis']['total_hit_pct']:.6f}%。初次复用计数不直接等于全生命周期避免的计算量。",
         "The same single-pass F0 runs, IDs and order as Figure 5. Top: total normal-path hit tokens (local HBM + DRAM + Peer) divided by every prompt token in each workflow, including cold requests. Bottom: hit-token count difference from same-ID Mooncake. DRAM and Peer hits are zero for every workflow. Initial reuse counters do not measure lifetime avoided computation.",paired)

    cp_rows = [ws[s][wid] for s in SYSTEMS]
    assert len({r["total_hit_tokens"] for r in cp_rows}) == 1
    assert len({r["prefill_executed_tokens"] for r in cp_rows}) == 1
    assert all(r["preemptions"] == 0 for r in cp_rows)
    components = [("critical_gpu_step_ns","GPU batch steps","#729DC6"),
                  ("critical_queue_other_ns","Queue / scheduling gaps","#D6DFE7"),
                  ("other_stages_ns","Dispatch / GET / DAG gaps","#D5A159")]
    costs = []
    for s, r in zip(SYSTEMS,cp_rows,strict=True):
        costs.append(dict(system=s,workflow_id=wid,wct_s=r["wct_s"],
                          critical_gpu_step_ns=r["critical_gpu_step_ns"],
                          critical_queue_other_ns=r["critical_queue_other_ns"],
                          other_stages_ns=r["critical_get_exclusive_ns"]+r["critical_dispatch_cpu_exclusive_ns"]+r["critical_dependency_gap_ns"],
                          critical_get_exclusive_ns=r["critical_get_exclusive_ns"],
                          critical_dispatch_cpu_exclusive_ns=r["critical_dispatch_cpu_exclusive_ns"],
                          critical_dependency_gap_ns=r["critical_dependency_gap_ns"],
                          total_hit_tokens=r["total_hit_tokens"],
                          prefill_executed_tokens=r["prefill_executed_tokens"],preemptions=r["preemptions"]))
    fig, ax = plt.subplots(figsize=(7,3.4))
    fig.subplots_adjust(left=.22,right=.975,top=.74,bottom=.29)
    left = np.zeros(3)
    for key,label,color in components:
        values = np.array([r[key]/1e9 for r in costs])
        ax.barh(np.arange(3),values,left=left,height=.53,color=color,edgecolor="white",linewidth=.4,label=label)
        for i,v in enumerate(values):
            if v > 4:
                ax.text(left[i]+v/2,i,f"{v:.2f}",ha="center",va="center",fontsize=10)
        left += values
    assert np.allclose(left,[r["wct_s"] for r in costs],rtol=0,atol=1e-10)
    for i,r in enumerate(costs):
        ax.text(r["wct_s"]+.7,i,f"{r['wct_s']:.2f} s",va="center",fontsize=10)
    ax.set(yticks=[0,1,2],yticklabels=[style.LABELS[s].replace("DRAM-only AegisKV","DRAM-only\nAegisKV") for s in SYSTEMS],
           xlabel="Realized critical-path elapsed time (s)",xlim=(0,max(left)*1.2))
    ax.invert_yaxis()
    ax.grid(axis="x",color="#DFE5EA",lw=.55)
    ax.legend(loc="upper center",bbox_to_anchor=(.52,.97),bbox_transform=fig.transFigure,ncol=2,frameon=False,fontsize=10)
    fig.text(.22,.045,f"Same workflow {wid[:8]}  |  All hits: {costs[0]['total_hit_tokens']} tokens  |  No preemption",fontsize=10)
    save(fig,"eval-preemption-progress","单轮最大变慢 Workflow 的完成时间构成",
         f"图 5 中 AegisKV 增量最大的 Workflow {wid}，三系统都统计相同对象。沿各系统实际最晚完成前驱回溯至根，分解 GPU batch 参与时段、等待/调度间隙及 CPU/GET/依赖释放间隔，互斥求和等于 WCT。三系统该对象都命中 {costs[0]['total_hit_tokens']} 个 token，执行相同 prefill 工作，均无抢占。Batch 参与历时不是该请求独占 GPU 的计算时间；关键路径可随系统改变。",
         "The same largest-slowdown workflow from Figure 5. Each system follows its realized latest-completing parent chain. Disjoint GPU-batch participation, queue/scheduling gaps, and dispatch/GET/dependency-gap intervals sum exactly to WCT. Hit tokens and executed prefill work match, with no preemption. Batch participation is not exclusive GPU compute time; the realized path may differ across systems.",costs)

    # Match the identical final request, then reconstruct its batch peers from
    # the compact per-request step records. No modeled counterfactual is used.
    final_evidence = {}
    for s in SYSTEMS:
        rid = f"fanoutqa:{wid}:final"
        request = next(r for r in data[s]["requests"] if r["span_id"] == rid)
        batch_keys = {(x["gpu_id"],x["start_ns"],x["end_ns"]) for x in data[s]["steps"][rid]}
        peers = []
        for other_id, steps in data[s]["steps"].items():
            if other_id == rid:
                continue
            for step in steps:
                if (step["gpu_id"],step["start_ns"],step["end_ns"]) in batch_keys and step["prefill_tokens"]:
                    peers.append(dict(span_id=other_id,**step))
        final_evidence[s] = dict(request=request,step_count=len(batch_keys),
                                 co_batched_prefill_tokens=sum(r["prefill_tokens"] for r in peers),
                                 co_batched_prefill_requests=len({r["span_id"] for r in peers}),
                                 co_batched_prefill_steps=peers,
                                 critical_path=data[s]["critical_paths"][wid])
    (ART/"final-request-batch-evidence.json").write_text(json.dumps(final_evidence,indent=2)+"\n")

    manifest = dict(schema="aegiskv.single_pass_f0_figures.v1",figures=figures,inputs=inputs,
                    extractor=str((Path(__file__).parent/"reduce_single_pass_f0.py").relative_to(ROOT)),
                    renderer_sha256=sha(__file__),source_snapshot_sha256=data["mooncake"]["source_snapshot_sha256"],
                    statistics=stats,focus_workflow_id=wid,focus_costs=costs,
                    final_request_evidence_sha256=sha(ART/"final-request-batch-evidence.json"),
                    paired_csv_sha256=sha(OUT/"all-workflows-paired.csv"),
                    source_thread="01a0838b-2f2a-7771-bba9-4857d840b9ba",
                    new_simulations_in_this_task=0,reused_complete_f0_runs=3,
                    visual_spec=dict(reference="previous Figure 5 paired lines, existing agent_lease_style.py",
                                     purpose="all original workflow cache hits paired to WCT; distinguish execution and waiting",
                                     placement_width_mm=177.8,smallest_font_pt=10,
                                     excluded="artificial revisit-1; no subsampling of the original 160 workflows"))
    (OUT/"single-pass-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    (ART/"summary.json").write_text(json.dumps(dict(statistics=stats,focus_workflow_id=wid,focus_costs=costs),ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(dict(statistics=stats,focus_workflow_id=wid,focus_costs=costs)),flush=True)


if __name__ == "__main__":
    main()
