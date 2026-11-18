"""Data-backed Evaluation candidates and explicitly empty scaling layouts.

This renderer runs no experiment. Source-v3 values remain historical diagnostics;
they are never promoted to results of the new controlled-intervention protocol.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.ticker import NullLocator

import agent_lease_style as style
from paper_paths import ROOT

ART = ROOT / "output/evaluation-redesign-20260909"
OUT = ROOT / "output/pdf/aegiskv-evaluation-20260909"
OLD = ROOT / "output/pdf/aegiskv-agent-lease-20260908"
DATA = ROOT / "output/agent-lease-20260908/data"
SYSTEMS = tuple(style.COLORS)
INPUTS, RECORDS = {}, []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind(path):
    INPUTS[str(path.relative_to(ROOT))] = sha(path)
    return path


def read_csv(name):
    with bind(OLD / f"{name}.csv").open() as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def save(fig, name, rows, title, caption, en, *, evidence="historical_modeled_diagnostic"):
    files = {}
    for ext in ("pdf", "png", "svg"):
        path = OUT / f"{name}.{ext}"
        fig.savefig(path, dpi=220, metadata={"Creator": "AegisKV Evaluation design"} if ext == "pdf" else None)
        files[ext] = sha(path)
    if rows:
        path = OUT / f"{name}.csv"
        write_csv(path, rows)
        files["csv"] = sha(path)
    RECORDS.append(dict(name=name, title=title, caption=caption, caption_en=en,
        width_in=float(fig.get_figwidth()), height_in=float(fig.get_figheight()),
        evidence=evidence, measured_new_protocol=False, files=files))
    plt.close(fig)


def canvas(xlabel, ylabel, *, wide=True, height=2.8):
    fig, ax = style.canvas(xlabel, ylabel, wide=wide, height=height)
    fig.subplots_adjust(top=.79, bottom=.22, left=.125 if wide else .235)
    return fig, ax


def healthy(healthy_data):
    original = read_csv("f0-revisit-wct")
    output = []
    fig, ax = canvas("Workflow (fixed Mooncake F0 order)", "Relative WCT change (%)")
    for row in original:
        baseline = float(row["mooncake"])
        assert baseline > 0
        for s in SYSTEMS:
            output.append(dict(workflow_rank=int(row["workflow_rank"]), workflow_id=row["workflow_id"],
                system=s, wct_s=float(row[s]), mooncake_wct_s=baseline,
                overhead_pct=100*(float(row[s])/baseline-1)))
    for s in SYSTEMS:
        subset = [r for r in output if r["system"] == s]
        style.line(ax, s, [r["workflow_rank"] for r in subset],
                   [r["overhead_pct"] for r in subset], thin=True)
    ax.set_xlim(1, 160)
    ax.set_xticks([1, 40, 80, 120, 160])
    style.legend(ax)
    save(fig, "eval-healthy-workflow", output, "正常执行的逐 Workflow 相对开销",
        "历史 source-v3 模拟的全部 160 个配对 Workflow；每点为同一对象相对 Mooncake 的 WCT 变化。零线为 Mooncake，负值更快。沿用基准 F0 排序；连线不是时间轴。每配置一次执行，不绘制跨重复置信区间。",
        "Historical source-v3 simulation: WCT change relative to matched Mooncake for all 160 workflows. Zero is the Mooncake baseline; negative is faster. IDs follow the frozen Mooncake F0 order. Segments connect objects, not time. One execution per system; no replicate confidence intervals.")

    original = read_csv("f0-revisit-dram-hit")
    fig, ax = canvas("Workflow (same fixed order)", "DRAM hit-rate change (pp)")
    output = []
    for s in SYSTEMS:
        values = [float(r[s])-float(r["mooncake"]) for r in original]
        style.line(ax, s, [int(r["workflow_rank"]) for r in original], values, thin=True)
        for r, v in zip(original, values):
            output.append(dict(workflow_rank=r["workflow_rank"], workflow_id=r["workflow_id"],
                system=s, dram_hit_pct=float(r[s]), mooncake_dram_hit_pct=float(r["mooncake"]), change_pp=v))
    ax.set_xlim(1,160)
    ax.set_xticks([1,40,80,120,160])
    style.legend(ax)
    save(fig, "eval-healthy-reuse", output, "DRAM 准入对正常复用的影响",
        "与前图相同的对象和顺序，纵轴为 DRAM token 命中率的百分点变化。分母包含所有冷访问与重访 prompt token，排除恢复 token；总体命中率按 token 加权，不能对这些点直接求平均。",
        "Change in DRAM prompt-token hit rate for the same workflow IDs and order, in percentage points. The denominator includes cold and revisit prompt tokens and excludes recovery tokens. Aggregate hit rate is token-weighted, not the mean of these points.")

    cost = read_csv("evaluation-resource-cost")
    specs = [
        ("Reference Python CPU", "Reference CPU time (measured)", None),
        ("Modeled CPU service", "Controller service (modeled)", None),
        ("Foreground HBM wait", "Foreground HBM wait (modeled)", "foreground_hbm_wait_s"),
        ("Scheduler queue P95", "Scheduler queue P95 (modeled)", "p95_scheduler_queue_s"),
        ("DRAM + Peer write bytes", "DRAM + Peer writes (modeled)", None),
        ("Foreground GET bytes", "Foreground GET bytes (modeled)", None),
        ("GET service slowdown P95", "GET slowdown P95 (modeled)", None),
    ]
    fig, ax = canvas("Ratio to Mooncake (log scale)", "", height=3.6)
    fig.subplots_adjust(left=.405, top=.84, bottom=.16)
    output = []
    for j, s in enumerate(SYSTEMS):
        ratios = []
        for i, (key, label, field) in enumerate(specs):
            if field:
                v = healthy_data[s]["summary"][field]
                base = healthy_data["mooncake"]["summary"][field]
                unit, evidence = "s", "modeled_exploration"
            else:
                r = next(r for r in cost if r["system"] == s and r["metric"] == key)
                v, base = float(r["value"]), float(r["mooncake_value"])
                unit, evidence = r["unit"], r["evidence"]
            assert base > 0
            ratios.append(v/base)
            output.append(dict(metric=key, system=s, value=v, mooncake_value=base, ratio=v/base,
                unit=unit, evidence=evidence))
        ax.plot(ratios, np.arange(len(specs))+(j-1)*.19, ls="none", ms=5,
            marker=style.MARKERS[s], color=style.COLORS[s], mfc="white", label=style.LABELS[s])
    ax.set_yticks(range(len(specs)), [r[1] for r in specs])
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlim(.5, 9)
    ax.set_xticks([.5,1,2,4,8], [".5","1","2","4","8"])
    ax.xaxis.set_minor_locator(NullLocator())
    ax.axvline(1, color=style.GRAY, lw=.7, zorder=0)
    ax.grid(False)
    ax.grid(axis="x", color="#DFE5EA", lw=.55)
    style.legend(ax)
    save(fig, "eval-healthy-resources", output, "前台等待、控制计算与传输的分项成本",
        "各行独立除以同指标 Mooncake 值；横轴为对数倍率。参考 CPU 是 Python 实测，其余为未标定模拟。累计等待、队列分位数和流量不能相加；GET 样本总体随命中策略变化。该图不含尚未采集的原生进程 CPU 与逐 GPU HBM 峰值。",
        "Each resource metric is independently normalized to Mooncake on a log axis. Python reference CPU is measured; the other rows are uncalibrated simulation. Cumulative wait, queue percentiles and traffic are not additive. Successful GET populations differ. Native process CPU and per-GPU peak HBM remain unmeasured.",
        evidence="mixed_reference_CPU_and_simulation")


def failures(healthy_data):
    focuses = read_csv("failure-focuses")
    phases = read_csv("failure-focal-recovery-phases")
    paired, contracts = [], []
    for i, focus in enumerate(focuses,1):
        q = int(focus["nominal_progress_pct"])
        span = focus["focus_span_id"]
        wid = span.split(":")[1]
        for s in SYSTEMS:
            data = json.loads(bind(DATA / f"f1-q{q}/{s}.json").read_text())
            f1 = next(r for r in data["workflows"] if r["workflow_id"] == wid)["wct_s"]
            f0 = next(r for r in healthy_data[s]["workflows"] if r["workflow_id"] == wid)["wct_s"]
            base0 = next(r for r in healthy_data["mooncake"]["workflows"] if r["workflow_id"] == wid)["wct_s"]
            phase = next(r for r in phases if r["system"] == s and int(r["progress_pct"]) == q)
            event = next(r for r in data["failure_events"] if r["event"] == "FAILURE_INJECT")
            assert event["logical_trigger"]["focus_span_id"] == span
            assert span in event["impacted_active_span_ids"]
            paired.append(dict(case_id=f"C{i}", legacy_progress_pct=q, workflow_id=wid,
                focus_span_id=span, system=s, f0_wct_s=f0, f1_wct_s=f1,
                mooncake_f0_wct_s=base0, delta_wct_s=f1-f0,
                delta_common_pct=100*(f1-f0)/base0, resume_s=float(phase["resume_s"])))
            contracts.append(dict(case_id=f"C{i}", system=s, focus_span_id=span,
                target_gpu_id=event["target_gpu_id"], failure_at_s=event["timestamp_ns"]/1e9,
                active_spans=event["impacted_active_span_ids"],
                queued_spans=event["impacted_queued_span_ids"],
                impact_scope=event["impact_contract_scope"],
                repair_after_s=event["repair_after_ns"]/1e9,
                logical_trigger=event["logical_trigger"]))
    for r in paired:
        base1=next(x["f1_wct_s"] for x in paired if x["system"]=="mooncake" and x["case_id"]==r["case_id"])
        r.update(mooncake_f1_wct_s=base1, f1_ratio=r["f1_wct_s"]/base1)
    for name, key, ylabel, title, caption, en in [
        ("eval-failure-wct", "f1_ratio", "Failure WCT / Mooncake",
         "同一故障焦点 Workflow 的完整 WCT",
         "C1–C3 是预选的三个不同故障实例；每组只比较同一个焦点 Workflow。分母是同例 Mooncake F1 WCT，1 为基准。历史触发只对齐逻辑请求和 token 进度，尚未固定全部受影响对象；这些点不是新协议结果。",
         "Historical cases C1-C3 each compare the same focal workflow across three systems. WCT is normalized to Mooncake F1 within that case. Logical request and token progress were matched, but the complete affected population was not fixed. These are not measurements of the redesigned protocol."),
        ("eval-failure-increment", "delta_common_pct", "Fault WCT increment (%)",
         "扣除正常成本后的配对故障增量",
         "每个点先计算自身 F1−F0，再除以同例 Mooncake F0 WCT。三系统使用共同分母；保留负值。闭环调度可改变等待，因此负增量不能解释为故障有益。C1–C3 不是随机重复，未拟合趋势或置信区间。",
         "Each point is 100 times (own F1 minus own F0) divided by the same case's Mooncake F0 WCT. Negative increments are retained and may arise from scheduling changes. The three prespecified cases are not independent repetitions; no trend or confidence interval is fitted.")
    ]:
        fig, ax = canvas("Prespecified focal workflow / case", ylabel, wide=False, height=2.85)
        for j,s in enumerate(SYSTEMS):
            rows = [r for r in paired if r["system"]==s]
            ax.plot(np.arange(3)+(j-1)*.16, [r[key] for r in rows], ls="none",
                marker=style.MARKERS[s], ms=5, mfc="white", color=style.COLORS[s], label=style.LABELS[s])
        ax.axhline(1 if key=="f1_ratio" else 0, color=style.GRAY, lw=.7,zorder=0)
        ax.set_xticks([0,1,2],["C1","C2","C3"]); ax.set_xlim(-.45,2.45)
        style.legend(ax)
        save(fig,name,paired,title,caption,en)

    # Distinct series colors encode systems; hatching, not another system color,
    # distinguishes the two adjacent measured stages.
    fig, ax = canvas("Time from fault to resumed decode (s)", "", height=3.7)
    fig.subplots_adjust(left=.36, top=.84, bottom=.16)
    exported=[]
    for i, r in enumerate(paired):
        p=next(p for p in phases if p["system"]==r["system"] and int(p["progress_pct"])==r["legacy_progress_pct"])
        a,b,total=(float(p[k]) for k in ["materialize_s","suffix_and_resume_s","resume_s"])
        assert abs(a+b-total)<1e-8
        y=(i//3)*3.5+i%3
        ax.barh(y,a,color=style.COLORS[r["system"]],height=.7,alpha=.28)
        ax.barh(y,b,left=a,color="white",edgecolor=style.COLORS[r["system"]],
            height=.7,hatch="////",linewidth=.85)
        exported.append(dict(case_id=r["case_id"],system=r["system"],focus_span_id=r["focus_span_id"],
            materialize_s=a, suffix_and_resume_s=b, resume_s=total))
    ticks=[(i//3)*3.5+i%3 for i in range(9)]
    ax.set_yticks(ticks, [r["case_id"]+"  "+style.LABELS[r["system"]] for r in paired])
    ax.invert_yaxis();ax.set_xlim(0,7.5)
    ax.grid(False);ax.grid(axis="x",color="#DFE5EA",lw=.55)
    from matplotlib.patches import Patch
    handles=[Patch(facecolor="#CDD2D6",label="Fault to prefix ready"),
             Patch(facecolor="white",edgecolor=style.GRAY,hatch="////",label="Suffix + queue + resume")]
    fig.legend(handles=handles,loc="upper center",ncol=2,frameon=False,bbox_to_anchor=(.6,.99))
    save(fig,"eval-failure-recovery",exported,"恢复阶段为何不能代替完整 Workflow 收益",
        "同一 C1–C3 焦点请求的两个相邻区间：故障至前缀可读（含检测、路由与装入），以及前缀可读至恢复解码（含后缀重算与排队）。区间内的操作尚未细分；柱终点未包含后续 DAG 终点。阶段较短并不保证完整 WCT 更短。",
        "Two adjacent intervals for the same focal requests: fault to prefix ready (including detection, routing and materialization), then prefix ready to resumed decode (including suffix work and queuing). Operations within each interval are not separated. The endpoint is resumed decode, not workflow completion; a shorter bar alone does not establish a WCT benefit.")

    fig, ax = canvas("KV tokens (Ki tokens)", "", height=3.7)
    fig.subplots_adjust(left=.36,top=.84,bottom=.16)
    token_fields=[("restored_peer_tokens","Peer HBM","#0072B2",".."),
                  ("restored_store_tokens","DRAM","#E6AA52","//"),
                  ("recompute_tokens","Recomputed","#ADB5BD","")]
    exported=[]
    for j,s in enumerate(SYSTEMS):
        left=np.zeros(3); y=np.arange(3)*3.5+j
        for field,label,color,hatch in token_fields:
            values=np.array([float(next(p for p in phases if p["system"]==s and int(p["progress_pct"])==q)[field]) for q in [25,50,75]])
            ax.barh(y,values/1024,left=left,height=.7,color=color,edgecolor="white",
                linewidth=.4,hatch=hatch,label=label if j==0 else None)
            left+=values/1024
            for i,value in enumerate(values):
                exported.append(dict(case_id=f"C{i+1}",system=s,source=field,tokens=int(value)))
    ax.set_yticks(ticks,[r["case_id"]+"  "+style.LABELS[r["system"]] for r in paired])
    ax.invert_yaxis()
    ax.set_xlim(0,45)
    ax.set_xticks([0,10,20,30,40])
    ax.grid(False);ax.grid(axis="x",color="#DFE5EA",lw=.55)
    style.legend(ax,columns=3)
    save(fig,"eval-failure-kv",exported,"恢复来源与剩余重算",
        "三个焦点请求的历史 token 计数，系统与前图逐行对齐。Ki=1,024。仅统计 Peer 恢复、DRAM 恢复和重算，不是全部上下文的百分比。所有 Peer 恢复均为零；不能把前图的阶段改善归因于 Peer。",
        "Historical token counts for the same three focal requests, with systems aligned to the recovery-stage view. Ki=1024. Bars include restored Peer tokens, restored DRAM tokens and recomputed tokens, not all context tokens. All Peer restoration counts are zero.")
    (ART/"legacy-failure-contracts.json").write_text(json.dumps(contracts,ensure_ascii=False,indent=2)+"\n")
    write_csv(ART/"legacy-focal-workflows.csv",paired)
    return paired


def layouts():
    """No synthetic marks, baselines, error bars, or implied measured trends."""
    for family,xlabel,xvalues in [
        ("rate","Injected faults per cluster-hour",[0,1,2,4,8]),
        ("concurrency","Maximum active workflows",[4,8,16,32,64]),
    ]:
        for metric,ylabel in [("goodput","SLO goodput (workflows/s)"),("tail","Response time P95 (s)")]:
            fig,ax=canvas(xlabel,ylabel,wide=False,height=2.9)
            ax.set_xticks(xvalues);ax.set_xlim(min(xvalues)-.07*np.ptp(xvalues),max(xvalues)+.07*np.ptp(xvalues))
            ax.set_yticks([]);ax.set_ylim(0,1)
            ax.text(.5,.52,"LAYOUT ONLY\nNo measurements",transform=ax.transAxes,ha="center",va="center",
                fontsize=12,color=style.GRAY)
            handles=[Line2D([],[],color=style.COLORS[s],ls=style.STYLES[s],marker=style.MARKERS[s],
                mfc="white",label=style.LABELS[s]) for s in SYSTEMS]
            ax.legend(handles=handles,loc="upper center",bbox_to_anchor=(.5,.99),
                bbox_transform=fig.transFigure,ncol=3,frameon=False,fontsize=10,
                handlelength=2,handletextpad=.3,columnspacing=.6,
                labels=["Mooncake","DRAM-only\nAegisKV","AegisKV"])
            save(fig,f"layout-{family}-{metric}",[],f"{family} / {metric} 布局占位",
                "仅坐标与拟定系列；没有测量值，不能作为实验结果插入论文。",
                "Layout only: proposed axes and series, with no measured observations. Not an experimental result.",
                evidence="layout_only_no_data")


def main():
    ART.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
    import render_paper_story as plot
    style.install(plot)
    healthy_data={}
    for s in SYSTEMS:
        d=json.loads(bind(DATA/f"f0-base/{s}.json").read_text())
        healthy_data[s]={"summary":d["summary"],"workflows":d["workflows"]}
    healthy(healthy_data)
    paired=failures(healthy_data)
    layouts()
    (ART/"source-summaries.json").write_text(json.dumps({s:d["summary"] for s,d in healthy_data.items()},indent=2)+"\n")
    result=dict(schema="aegiskv.evaluation_redesign.figures.v1",new_experiments=0,
        inputs=INPUTS,figures=RECORDS,script_sha256=sha(Path(__file__)),
        core_figures=7,layout_only_figures=4)
    (OUT/"manifest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"core_figures":7,"layout_only":4,"focal_pairs":len(paired),"inputs":len(INPUTS)}))


if __name__=="__main__":main()
