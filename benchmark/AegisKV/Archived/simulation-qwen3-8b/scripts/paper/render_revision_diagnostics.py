"""Re-express frozen diagnostics without changing data or running experiments."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np
import pymupdf
from matplotlib.lines import Line2D

import agent_lease_style as style
from paper_paths import ROOT

OUT = ROOT / "output/pdf/aegiskv-revision-20260909"
ART = ROOT / "output/aegiskv-revision-20260909"
OLD = ROOT / "output/pdf/aegiskv-evaluation-20260909"
SYSTEMS = tuple(style.COLORS)
FOCUS = "fanoutqa:3d0739b161908b67:2ff5a0169b37cd46:revisit-1"
WID = "3d0739b161908b67"
INPUTS, RECORDS = {}, []


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def bind(path):
    INPUTS[str(path.relative_to(ROOT))] = sha(path)
    return path


def read_csv(path):
    with bind(path).open() as f:
        return list(csv.DictReader(f))


def save(fig, name, rows, title, caption, caption_en, note):
    files = {}
    for ext in ["pdf", "png", "svg"]:
        path = OUT / f"{name}.{ext}"
        fig.savefig(path, dpi=220, metadata={"Creator": "AegisKV frozen diagnostic revision"} if ext == "pdf" else None)
        files[ext] = sha(path)
    with (OUT / f"{name}.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    files["csv"] = sha(OUT / f"{name}.csv")
    with pymupdf.open(OUT / f"{name}.pdf") as doc:
        assert len(doc) == 1 and abs(doc[0].rect.width - 504) < .01
        spans = [s for b in doc[0].get_text("dict")["blocks"] if "lines" in b for line in b["lines"] for s in line["spans"] if s["text"].strip()]
        assert min(s["size"] for s in spans) >= 9.9
        assert all(s["bbox"][0] >= -.1 and s["bbox"][1] >= -.1 and s["bbox"][2] <= doc[0].rect.width + .1 and s["bbox"][3] <= doc[0].rect.height + .1 for s in spans)
        doc[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).save(OUT / f"{name}-pdf-preview.png")
    RECORDS.append(dict(name=name, title=title, caption=caption, caption_en=caption_en,
        width_in=float(fig.get_figwidth()), height_in=float(fig.get_figheight()),
        evidence="historical_modeled_diagnostic", new_experiments=0, files=files,
        plotted_rows=len(rows), note=note, visual_review="PENDING"))
    plt.close(fig)


def canvas(xlabel, ylabel, height=3.0):
    fig, ax = style.canvas(xlabel, ylabel, wide=True, height=height)
    fig.subplots_adjust(left=.135, right=.975, top=.80, bottom=.205)
    return fig, ax


def legend(ax, columns=1):
    item = style.legend(ax, columns=columns)
    item.set_bbox_to_anchor((.55, .976), transform=ax.figure.transFigure)
    return item


def workflow_delay():
    original = read_csv(OLD / "eval-healthy-workflow.csv")
    rows = []
    for r in original:
        rows.append(dict(workflow_rank=int(r["workflow_rank"]), workflow_id=r["workflow_id"],
            system=r["system"], wct_s=float(r["wct_s"]), mooncake_wct_s=float(r["mooncake_wct_s"]),
            delta_wct_s=float(r["wct_s"]) - float(r["mooncake_wct_s"]),
            overhead_pct=float(r["overhead_pct"])))
    assert len(rows) == 480 and len({r["workflow_id"] for r in rows}) == 160
    fig, ax = canvas("Workflow (fixed Mooncake no-failure order)", "WCT − Mooncake WCT (s)", 3.25)
    for s in SYSTEMS:
        subset = [r for r in rows if r["system"] == s]
        assert [r["workflow_rank"] for r in subset] == list(range(1, 161))
        style.line(ax, s, [r["workflow_rank"] for r in subset], [r["delta_wct_s"] for r in subset], thin=True)
    ax.set_xlim(1, 160); ax.set_xticks([1, 40, 80, 120, 160])
    lower, upper = min(r["delta_wct_s"] for r in rows), max(r["delta_wct_s"] for r in rows)
    ax.set_ylim(lower - 8, upper + 22)
    ax.set_yticks([-80, -40, 0, 40, 80, 120])
    focal = max((r for r in rows if r["system"] == "aegis"), key=lambda r: r["delta_wct_s"])
    assert focal["workflow_id"] == WID
    ax.annotate(f"{WID[:8]}: +{focal['delta_wct_s']:.1f} s", xy=(focal["workflow_rank"], focal["delta_wct_s"]),
        xytext=(46, upper + 5), fontsize=10, color=style.BLUE,
        arrowprops={"arrowstyle": "->", "color": style.BLUE, "lw": .8}, ha="left")
    legend(ax)
    save(fig, "eval-workflow-delay", rows, "正常场景的逐 Workflow 绝对延迟变化",
        "同一无故障配置的全部 160 个配对 Workflow，固定 Mooncake 顺序；每点为同 ID 相对 Mooncake 的 WCT 差值，负值更快。最大离群对象 3d0739b1 增加 129.6 s，未裁切尾部；完整 WCT 和相对百分比保留在 CSV。每系统一次冻结模拟，连线不是时间演化，也不表示重复实验置信区间。",
        "All 160 matched workflows in one frozen fault-free configuration, ordered by Mooncake WCT. Each point is the same-ID WCT difference from Mooncake; negative is faster. Outlier 3d0739b1 adds 129.6 s. Full tails, absolute WCTs and percentage changes are retained. One historical simulation per system; connecting segments do not represent time or replicate uncertainty.",
        "Same values as eval-healthy-workflow.csv, with seconds replacing the percentage ordinate. No outlier filtering or evidence promotion.")


def initial_reuse():
    original = read_csv(OLD / "eval-healthy-reuse.csv")
    order = {(r["workflow_id"], r["system"]): int(r["workflow_rank"]) for r in read_csv(OLD / "eval-healthy-workflow.csv")}
    counts = {}
    for s in SYSTEMS:
        requests = json.loads(bind(ROOT / f"output/agent-lease-20260908/data/f0-base/{s}.json").read_text())["requests"]
        for request in requests:
            key = (request["workflow_id"], s)
            row = counts.setdefault(key, dict(all_prompt_tokens=0, all_dram_hit_tokens=0, revisit_prompt_tokens=0, revisit_dram_hit_tokens=0))
            row["all_prompt_tokens"] += request["prompt_tokens"]
            row["all_dram_hit_tokens"] += request["dram_hit_tokens"]
            if request["span_id"].endswith(":revisit-1"):
                row["revisit_prompt_tokens"] += request["prompt_tokens"]
                row["revisit_dram_hit_tokens"] += request["dram_hit_tokens"]
    rows = []
    for r in original:
        c, m = counts[r["workflow_id"], r["system"]], counts[r["workflow_id"], "mooncake"]
        all_rate = 100*c["all_dram_hit_tokens"]/c["all_prompt_tokens"]
        revisit_rate = 100*c["revisit_dram_hit_tokens"]/c["revisit_prompt_tokens"]
        moon_revisit = 100*m["revisit_dram_hit_tokens"]/m["revisit_prompt_tokens"]
        assert np.isclose(all_rate, float(r["dram_hit_pct"]))
        rows.append(dict(workflow_rank=int(r["workflow_rank"]), workflow_id=r["workflow_id"], system=r["system"],
            revisit_initial_dram_token_hit_pct=revisit_rate, mooncake_revisit_initial_dram_token_hit_pct=moon_revisit,
            revisit_change_pp=revisit_rate-moon_revisit, **c,
            all_visit_initial_dram_token_hit_pct=all_rate, all_visit_change_pp=float(r["change_pp"]),
            measurement="revisit_1_initial_lookup_not_effective_compute_avoided"))
    assert len(rows) == 480
    assert all(order[r["workflow_id"], r["system"]] == r["workflow_rank"] for r in rows)
    fig, ax = canvas("Workflow (same fixed Mooncake order)", "Revisit DRAM token hit (%)", 3.1)
    for s in SYSTEMS:
        sub = [r for r in rows if r["system"] == s]
        style.line(ax, s, [r["workflow_rank"] for r in sub], [r["revisit_initial_dram_token_hit_pct"] for r in sub], thin=True)
    ax.set_xlim(1, 160); ax.set_xticks([1, 40, 80, 120, 160]); ax.set_ylim(-2, 102); ax.set_yticks([0, 25, 50, 75, 100])
    legend(ax)
    global_rates = {s:100*sum(r["revisit_dram_hit_tokens"] for r in rows if r["system"]==s)/sum(r["revisit_prompt_tokens"] for r in rows if r["system"]==s) for s in SYSTEMS}
    rates_zh = "、".join(f"{global_rates[s]:.3f}%" for s in SYSTEMS)
    rates_en = ", ".join(f"{global_rates[s]:.3f}%" for s in SYSTEMS)
    save(fig, "eval-initial-reuse", rows, "重访请求首次查询的 DRAM token 命中",
        f"与前图相同的 160 个 Workflow 和排序，只统计第二轮 revisit-1；每个点以该 Workflow 第二轮全部 prompt token 为分母，排除首轮冷访问。三系统全局 token 加权命中率分别为 {rates_zh}。首次查询命中不能代表抢占重算之后最终避免的计算量。CSV 同时保留两轮合计与重访口径的计数、分母和百分点差，不能等权平均 Workflow 得到全局值。",
        f"Initial DRAM hits on the second visit only, for the same 160 workflow IDs and order. Each point divides by all second-visit prompt tokens for that workflow; cold first visits are excluded. Global token-weighted rates are {rates_en}. Initial lookup hits do not measure effective computation avoided after preemption. CSV retains all-visit and revisit-only counts, denominators and percentage-point deltas.",
        "Recomputed from frozen per-request initial-lookup counters. Plotted revisit-only global token-weighted rates: " + json.dumps(global_rates) + ". No effective-reuse claim; all-visit rates independently match the previous figure input.")


def extract_progress_events(force=False):
    cache = ART / "preemption-progress-events.json"
    if cache.exists() and not force:
        return json.loads(bind(cache).read_text())
    request_rows = read_csv(ART / "f0-top-three-request-details.csv")
    result = {"focus_span_id": FOCUS, "workflow_id": WID, "systems": {}, "inputs": {}}
    for s in SYSTEMS:
        candidates = [r for r in request_rows if r["system"] == s and r["workflow_id"] == WID]
        origin = min(int(r["released_ns"]) for r in candidates)
        focus = next(r for r in candidates if r["span_id"] == FOCUS)
        if s == "aegis":
            path = ART / "aegis-top-outlier-events.json"
            data = json.loads(path.read_text())
            steps = data["steps"]
            preemptions = data["preemptions"]
            route_history = data["scheduler_request"]["route_history"]
        else:
            path = ROOT / f"output/agent-lease-20260908/campaign-v3/runs/f0-base/{s}.json.gz"
            print(f"Extracting frozen scheduler events: {s}", flush=True)
            with gzip.open(path, "rt") as f:
                data = json.load(f)
            scheduler = data["representative"]["continuous_batch_scheduler"]
            steps = scheduler["steps"]
            preemptions = []
            route_history = []
        result["inputs"][str(path.relative_to(ROOT))] = sha(path)
        extracted = []
        for step in steps:
            for p in step["participants"]:
                if p["request_id"] == FOCUS:
                    assert step["status"] == "COMPLETED"
                    extracted.append(dict(start_ns=step["start_ns"], end_ns=step["effective_end_ns"], phase=p["phase"],
                        computed_before=p["num_computed_tokens_before"], computed_after=p["num_computed_tokens_after"], origin=p["origin"]))
        assert extracted
        preemptions = [dict(timestamp_ns=e["timestamp_ns"], **detail) for e in preemptions for detail in e["preemption_details"] if detail["victim_request_id"] == FOCUS]
        result["systems"][s] = dict(workflow_release_ns=origin, span_release_ns=int(focus["released_ns"]),
            prompt_tokens=int(focus["prompt_tokens"]), initial_hit_tokens=int(focus["total_hit_tokens"]),
            completion_ns=int(focus["completed_ns"]), steps=extracted, preemptions=preemptions, route_history=route_history)
        print(f"Extracted {s}: {len(extracted)} steps", flush=True)
        del data, steps
    cache.write_text(json.dumps(result, indent=2) + "\n")
    bind(cache)
    return result


def preemption_progress(events):
    source = ROOT / "output/agent-lease-20260908/source-v3/python/moonkvsim/integration/vllm/scheduler.py"
    if not source.exists():
        source = ROOT / "output/agent-lease-20260908/MECHANISM_SOURCE_SNAPSHOT/python/moonkvsim/integration/vllm/scheduler.py"
    # Event before-token count plus the executed reset implementation supports
    # a zero counter at the same DES timestamp, rather than an interpolated loss.
    source_text = bind(source).read_text()
    assert "request.num_computed_tokens = 0" in source_text
    rows = []
    fig, ax = canvas("Time since this workflow's first release (s)", "Valid prefill progress (Ki tokens)", 3.4)
    for s in SYSTEMS:
        data = events["systems"][s]
        origin, prompt = data["workflow_release_ns"], data["prompt_tokens"]
        samples = []
        for step in data["steps"]:
            if step["phase"] != "PREFILL":
                continue
            for when, value, label in [(step["start_ns"], step["computed_before"], "step_start"), (step["end_ns"], step["computed_after"], "step_end")]:
                samples.append((when, 0 if label == "step_end" else 2, min(value, prompt), label, step["origin"]))
        for e in data["preemptions"]:
            samples.append((e["timestamp_ns"], 1, 0, "preempt_reset_from_executed_semantics", "PREEMPTED"))
        samples.sort()
        for timestamp, _, tokens, event, phase in samples:
            rows.append(dict(system=s, workflow_id=WID, focus_span_id=FOCUS, workflow_release_ns=origin,
                timestamp_ns=timestamp, relative_time_s=(timestamp-origin)/1e9, valid_prefill_tokens=tokens,
                prompt_tokens=prompt, event=event, origin=phase))
        t = [(v[0]-origin)/1e9 for v in samples]
        vals = [v[2]/1024 for v in samples]
        ax.step(t, vals, where="post", color=style.COLORS[s], ls=style.STYLES[s], lw=1.35, label=style.LABELS[s])
        # Only actual boundaries are marked. Completed short traces are not
        # extended to the AegisKV completion time as hypothetical residency.
        ax.plot([t[0], t[-1]], [vals[0], vals[-1]], linestyle="none", marker=style.MARKERS[s],
            color=style.COLORS[s], markerfacecolor="white", markersize=5)
    aeg = events["systems"]["aegis"]
    preempt = aeg["preemptions"][0]["timestamp_ns"]
    readmit = next(s["start_ns"] for s in aeg["steps"] if s["origin"] == "RESUMED")
    assert preempt == 102367437007 and readmit == 207296763004
    start, end = [(t-aeg["workflow_release_ns"])/1e9 for t in [preempt, readmit]]
    ax.axvspan(start, end, color=style.BLUE, alpha=.06, zorder=0)
    ax.annotate("", xy=(start, 18), xytext=(end, 18), arrowprops={"arrowstyle": "<->", "lw": .8, "color": style.BLUE})
    ax.text((start+end)/2, 22, f"Preempted: {(readmit-preempt)/1e9:.1f} s", ha="center", va="bottom", color=style.BLUE, fontsize=10)
    ax.annotate("Reset to 0", xy=(start, 0), xytext=(start+9, 7), color=style.BLUE, fontsize=10,
        arrowprops={"arrowstyle": "->", "color": style.BLUE, "lw": .8})
    ax.set_xlim(0, 155); ax.set_xticks([0, 30, 60, 90, 120, 150]); ax.set_ylim(-3, 70); ax.set_yticks([0, 20, 40, 60])
    legend(ax)
    save(fig, "eval-preemption-progress", rows, "正常抢占使初次命中失效的具体轨迹",
        "最坏 Workflow 3d0739b1 中同一个重访请求，三系统分别以该 Workflow 首次 release 为零对齐。阶梯仅由真实 scheduler prefill 步骤边界及已执行抢占的 token-counter 重置产生，不拟合中间吞吐。AegisKV 在全局 102.367 s 抢占，207.297 s 再准入，间隔 104.929 s；图中相对位置为 26.300–131.229 s。初次命中 63,152 token 后丢失进度并从 0 重算；这是无故障 HBM 压力抢占，不是故障注入。",
        "The same revisit request in outlier workflow 3d0739b1, aligned to each system's first release of that workflow. Steps use actual prefill boundaries and the executed preemption reset, without interpolation of throughput. AegisKV preempts at global 102.367 s and readmits at 207.297 s: 104.929 s, or relative 26.300-131.229 s. The initial 63,152-token hit is invalidated and recomputation starts at zero. This is fault-free HBM-pressure preemption, not an injected failure.",
        "Progress includes an initially restored prefix, not cumulative computed work. Counter reset at the preemption timestamp is derived from the recorded preemption plus frozen scheduler._preempt_for_recompute semantics. Short completed traces are not extrapolated.")


def focal_rows():
    rows = read_csv(OLD / "eval-failure-wct.csv")
    rows.sort(key=lambda r: (r["case_id"], SYSTEMS.index(r["system"])))
    assert len(rows) == 9 and all(len({r["workflow_id"] for r in rows if r["case_id"] == case}) == 1 for case in ["C1", "C2", "C3"])
    return rows


def case_axis(xlabel):
    fig, ax = canvas(xlabel, "", 4.1)
    fig.subplots_adjust(left=.35, right=.97, top=.87, bottom=.155)
    y = [i + .5 * (i // 3) for i in range(9)]
    rows = focal_rows()
    ax.set_yticks(y, [style.LABELS[r["system"]] for r in rows])
    for i in range(3):
        center = y[3*i+1]
        ax.text(-.52, center, "C"+str(i+1), transform=ax.get_yaxis_transform(), ha="center", va="center", weight="bold", fontsize=10)
        if i < 2:
            ax.axhline((y[3*i+2]+y[3*i+3])/2, color="#D9DEE3", lw=.65)
    ax.set_ylim(y[-1]+.7, -.7)
    ax.grid(False); ax.grid(axis="x", color="#DFE5EA", lw=.55)
    return fig, ax, rows, y


def fault_paired_wct():
    fig, ax, rows, y = case_axis("Workflow completion time (s)")
    out = []
    for yy, r in zip(y, rows):
        s = r["system"]; f0, f1 = float(r["f0_wct_s"]), float(r["f1_wct_s"])
        if abs(f1-f0) < 1:
            ax.plot([f0,f1], [yy,yy], color=style.COLORS[s], lw=1.15)
            ax.text(max(f0,f1)+4, yy, f"{f1-f0:+.2f} s", va="center", fontsize=10, color=style.COLORS[s])
        else:
            ax.annotate("", xy=(f1, yy), xytext=(f0, yy), arrowprops={"arrowstyle": "->", "color": style.COLORS[s], "lw": 1.15, "shrinkA": 1, "shrinkB": 2})
        ax.plot(f0, yy, marker=style.MARKERS[s], color=style.COLORS[s], ms=6, mfc="white", linestyle="none")
        ax.plot(f1, yy, marker=style.MARKERS[s], color=style.COLORS[s], ms=5, mfc=style.COLORS[s], linestyle="none")
        out.append(dict(case_id=r["case_id"], workflow_id=r["workflow_id"], focus_span_id=r["focus_span_id"],
            system=s, f0_wct_s=f0, f1_wct_s=f1, delta_wct_s=f1-f0, legacy_progress_pct=int(r["legacy_progress_pct"])))
    ax.set_xlim(0, 200); ax.set_xticks([0, 50, 100, 150, 200])
    handles = [Line2D([],[],marker="o",mfc="white",color=style.GRAY,ls="none",ms=6,label="No failure (F0)"),
               Line2D([],[],marker="o",mfc=style.GRAY,color=style.GRAY,ls="none",ms=5,label="One failure (F1)")]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.60,.99), ncol=2,frameon=False,fontsize=10)
    save(fig,"eval-fault-paired-wct",out,"同一焦点 Workflow 的故障前后配对 WCT",
        "C1–C3 分别为预选焦点 Workflow 98ced84a、220852c6、5aa09932；每组的三系统比较同一个对象。空心为无故障 F0，实心为单故障 F1，箭头连接本系统配对 WCT；近重合点直接标注差值。保留左向的负变化，不把调度差异解释为故障有益。历史协议只固定逻辑请求与 token 进度，未固定整个受害集合，因此不是新受控协议的因果结论。",
        "Cases C1-C3 select workflows 98ced84a, 220852c6 and 5aa09932 respectively. Each group compares the same workflow. Open markers are no failure (F0), filled markers one failure (F1); arrows pair each system's WCT, while a nearly coincident pair is labeled by its difference. Leftward changes are retained and may reflect scheduling, not beneficial failures. The historical protocol matched logical requests and token progress, not the full victim population.",
        "Nine rows from eval-failure-wct.csv. Absolute values replace cross-case normalized scatter; cases are neither repeated trials nor a trend.")


def fault_token_source():
    raw = read_csv(OLD / "eval-failure-kv.csv")
    fig, ax, focal, y = case_axis("Recovered or recomputed tokens (Ki tokens)")
    specs = [("restored_peer_tokens", "Peer HBM (0)", style.BLUE, ".."),
             ("restored_store_tokens", "DRAM", "#E6AA52", "//"),
             ("recompute_tokens", "Recomputed", "#ADB5BD", "")]
    out = []
    for yy, r in zip(y, focal):
        left = 0
        for field, label, color, hatch in specs:
            source = next(v for v in raw if v["case_id"] == r["case_id"] and v["system"] == r["system"] and v["source"] == field)
            value = int(source["tokens"])
            ax.barh(yy,value/1024,left=left,height=.68,color=color,edgecolor="white",lw=.4,hatch=hatch,
                label=label if yy == y[0] else None)
            left += value/1024
            out.append(dict(case_id=r["case_id"], workflow_id=r["workflow_id"], focus_span_id=r["focus_span_id"],
                system=r["system"], source=field, tokens=value))
    assert all(r["tokens"] == 0 for r in out if r["source"] == "restored_peer_tokens")
    ax.set_xlim(0, 45); ax.set_xticks([0, 10, 20, 30, 40])
    legend(ax, columns=3)
    save(fig,"eval-fault-token-source",out,"同一故障请求的恢复来源与重算量",
        "与配对 WCT 图相同的 C1–C3 和系统行序；每条柱为该焦点请求从 Peer、DRAM 恢复及重算的 token 数，Ki=1,024。Peer 的九条记录均为零，图例保留该来源但没有人为补出柱段。这些计数不包括后续 DAG 执行，不能单独解释完整 WCT，也不能把现有局部改善归因于 Peer。",
        "The same case and system row order as paired WCT. Bars count focal-request tokens restored from Peer or DRAM and recomputed; Ki=1024. All nine Peer entries are zero and no segment is invented. Counts exclude downstream workflow execution and do not by themselves explain complete WCT or establish a Peer benefit.",
        "All 27 component records from historical eval-failure-kv.csv are retained and aligned with nine paired workflow rows. Zero Peer counts remain explicit in CSV and caption.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract-only", action="store_true")
    parser.add_argument("--force-extract", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True); ART.mkdir(parents=True, exist_ok=True)
    events = extract_progress_events(force=args.force_extract)
    if args.extract_only:
        return
    style.install(SimpleNamespace())
    workflow_delay(); initial_reuse(); preemption_progress(events); fault_paired_wct(); fault_token_source()
    result = dict(schema="aegiskv.revision_diagnostics.v1", new_experiments=0, inputs=INPUTS,
        progress_raw_inputs=events["inputs"], script_sha256=sha(Path(__file__)), figures=RECORDS)
    (OUT / "diagnostics-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Rendered {len(RECORDS)} independent frozen diagnostic figures")


if __name__ == "__main__":
    main()
