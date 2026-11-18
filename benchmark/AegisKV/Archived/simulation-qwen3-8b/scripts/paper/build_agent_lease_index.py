"""Build the Chinese manuscript draft, figure records and placement proof."""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

from agent_lease_story_content import captions
from agent_lease_draft_captions import CAPTIONS as DRAFT_CAPTIONS
from build_paper_story_index import tex_escape
from paper_paths import ROOT
from three_system_data import SYSTEMS, LABELS, sha

DIRECTORY = ROOT / "benchmark/AegisKV/experiments"
ARTIFACTS = ROOT / "output/agent-lease-20260908"
OUT = ROOT / "output/pdf/aegiskv-agent-lease-20260908"
TEMPLATE = Path(__file__).with_name("templates") / "agent-lease-draft.md"
BASELINE = OUT / "before-paperbanana" / "REVISION_BASE.json"
REFERENCES = ROOT / "benchmark/AegisKV/docs/related_works/figure-references-20260908/manifest.json"
EVIDENCE = {
    "trace_anchored_counterfactual": "轨迹锚定反事实",
    "mixed_reference_CPU_and_simulation": "分项实测 CPU 与模拟",
    "design": "设计示意", "trace_observation": "观测动机", "analytical": "解析计算",
    "workload_description": "输入统计", "modeled_exploration": "未标定机制模拟",
    "measured_Python_reference_CPU": "Python 参考 CPU 实测",
    "analytical_mixture_of_simulations": "模拟结果的解析混合",
    "native_component_microbenchmark": "真实 GPU 组件微基准",
    "physical_microbenchmark": "真实 GPU 组件微基准",
}


def rel(path):
    return os.path.relpath(path, DIRECTORY)


def link(path, label):
    return f"[{label}]({rel(path)})"


def assets(row):
    name = row["name"]
    pieces = [link(OUT / f"{name}.{e}", e.upper()) for e in ["pdf", "svg"]]
    extra = "drawio" if row["evidence"] == "design" else "csv"
    pieces.append(link(OUT / f"{name}.{extra}", "可编辑源" if extra == "drawio" else "逐点数据"))
    pieces += [EVIDENCE[row["evidence"]], f"{row['width_in']:.2f} inch"]
    return " · ".join(pieces)


def preview(row):
    width = 1008 if row["width_in"] > 5 else 480
    name = row["name"]
    return f'[<img src="{rel(OUT / (name + ".png"))}" width="{width}" alt="{html.escape(row["id"] + " " + row.get("draft_title", row["title"]), quote=True)}">]({rel(OUT / (name + ".pdf"))})'


def read_csv(name):
    import csv
    with (OUT / name).open() as f:
        return list(csv.DictReader(f))


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|"*len(headers)] +
        ["| " + " | ".join(map(str, row)) + " |" for row in rows])


def visual_treatment(name):
    specific = {
        "motivation-recovery-exposure": "从旧五分支 CSV 重画独立吸收/暴露条形图；不与 Qwen3-8B 实验混用。",
        "evaluation-resource-cost": "五个成本逐项相对 Mooncake 归一化，实测与模拟逐行明示；独立对数轴与三系统形状；正文保留绝对量。",
        "evaluation-native-interference": "将 batch 1/4 的 120 个既有观测放在一个共同坐标；条件不连线，保留五块配对倍率的中位数及全范围。",
        "evaluation-configuration-effects": "八个单因素配置逐行对照同配置 Mooncake；统一百分比轴，配置间不连线，完整均值留在 CSV。",
        "system-overview": "一张完整架构：Source/Peer/DRAM/Recovery 四个资源域，同名 C0/C1 贯穿独立复制及恢复，P0/P1 保留给无关前台；独立显存反馈闭环。",
        "design-joint-wct": "三种状态共用毫秒轴；填充表示工作，虚线表示恢复；Join 与边际分账可手算。",
        "design-agent-subleases": "透明 Q 边界保留内部对象；同宽信用条分别显示 A/B 余额与已花信用。",
        "design-prefix-admission": "同一前缀树贯穿释放与提交；可读集合、两种准入门及 ACK 次序明确标出。",
        "design-guarded-aimd": "按比例画 40 GiB；三种控制条件分别对照 C、Q、Used；下一步需求与 free ACK 分开。",
        "commit-tier-timeline": "同一个 C1 对齐两个 tier 的提交与故障；恢复路径显示装入前缀和重算后缀。",
        "motivation-kv-capacity": "容量曲线与参考线直接标注；参考线明确为扣除权重和 runtime 后的容量。",
        "ablation-lazy-refresh": "绝对操作计数从零起；千位分隔，保留 Lazy/Eager 的完整尾块检查与价值计算。",
        "aimd-quota-and-occupancy": "时序线型和独立图例区分硬上限、授权与实际占用；轴上 GiB，图注明确八卡合计。",
        "aimd-warning-windows": "0–20% 显示全部观测；统一线型区分动态与静态，保留各自执行终点。",
        "native-memory-occupancy": "局部秒轴与完整观测范围；颜色、线型、空心标记同时区分四种复制条件。",
        "failure-focal-recovery-phases": "九根柱保持故障位置分组；系统与恢复阶段分别编码，图例独立于柱体。",
    }
    if name in specific: return specific[name]
    if name.startswith("native-forward-"): return "batch 1/4 共用 0.96–1.36 倍纵轴；统一四系列编码，保留中位数与全观测范围。"
    if name.startswith("native-"): return "单栏紧凑图例与方向标记；保留中位数及最小/最大值，单位和组件测量范围不变。"
    if name.startswith("f1-q"): return "三个故障位置共用纵轴；每十对象设识别标记，保留全部 160 个对象及正、负、零值。"
    if name.startswith("order-"): return "相同对象的三个入场顺序以线和包络表达；CDF 保留完整尾部，顶部留出刻度空间。"
    if name in {"sensitivity-cpu-quote", "sensitivity-dma"}: return "使用明确刻度的局部秒轴辨认小差异；三个系统共用范围，全部设置与数值不变。"
    if name.startswith("sensitivity-") or name == "failure-progress-p95-penalty": return "三系统紧凑图例；颜色、线型和标记联合编码；仅连接实际执行的设置。"
    if name in {"f0-revisit-wct", "f0-revisit-wct-difference", "f0-revisit-dram-hit", "f0-revisit-scheduler-queue", "f0-revisit-hbm-wait", "f0-revisit-controller-service-difference", "f0-revisit-background-copy", "f0-revisit-peer-copy"}:
        return "固定 Workflow ID 与顺序；折线保留每个对象，每十个对象加识别标记；差值图加清晰零线。"
    if name.endswith("breakdown") or name == "f0-revisit-cache-sources": return "分解柱从零起，图例放在独立顶部区域；系统标在横轴，颜色与纹理表示组成。"
    return "按 3.33/7 inch 统一字体、线宽、留白和图例；保留完整数据范围、单位及统计口径。"


def visual_revision(records):
    refs = [r for r in json.loads(REFERENCES.read_text()) if r["name"] in {"enso-osdi23", "mooncake-fast25", "causalsim-nsdi23"}]
    for ref in refs: assert sha(ROOT/ref["path"]) == ref["pdf_sha256"]
    return dict(method="PaperBanana sequential reference / content / style / rendering / critique",
        scope="Compact manuscript: 3 Motivation + 1 Overview + 8 Evaluation figures; all prior statistical exports preserved",
        algorithm2_implementation_sync="Deferred by user while Algorithm 2 is being revised; this iteration is a visual revision only",
        baseline_sha256=sha(BASELINE), reference_manifest_sha256=sha(REFERENCES),
        references=refs, statistical_style_sha256=sha(Path(__file__).with_name("agent_lease_style.py")),
        invariants=["Original 49 CSV files unchanged byte for byte", "New views retain paired objects, values and complete selected sample ranges", "Old trace counterfactual stays separate from Qwen3-8B evaluation", "Algorithm 2 implementation deferred"],
        compact_baseline_sha256=sha(OUT/"before-compact-paper/REVISION_BASE.json"),
        compact_spec_sha256=sha(Path(__file__).with_name("templates")/"compact-figure-spec.md"),
        treatments={r["name"]:visual_treatment(r["name"]) for r in records})


def result_text():
    data = {s: json.loads((ARTIFACTS / f"data/f0-base/{s}.json").read_text()) for s in SYSTEMS}
    means = {s: d["summary"] for s, d in data.items()}
    primary = {r["workflow_id"]: r["wct_s"] for r in data["mooncake"]["workflows"]}
    rows = []
    for s in SYSTEMS:
        d = means[s]
        slow = sum(r["wct_s"] > primary[r["workflow_id"]] + 1e-9 for r in data[s]["workflows"])
        rows.append([LABELS[s], f"{d['mean_wct_s']:.3f}", f"{d['dram_hit_pct']:.2f}",
            f"{d['p99_ttft_s']:.3f}", f"{slow}/160"])
    healthy = table(["系统", "平均 WCT (s)", "DRAM token 命中率 (%)", "P99 TTFT (s)", "比 Mooncake 更慢的 Workflow"], rows)
    failure = read_csv("failure-summary.csv")
    focus = {int(r["nominal_progress_pct"]): r for r in read_csv("failure-focuses.csv")}
    rows = []
    for q in (25, 50, 75):
        for s in SYSTEMS:
            r = next(r for r in failure if r["system"] == s and int(r["progress_pct"]) == q)
            failed = json.loads((ARTIFACTS/f"data/f1-q{q}/{s}.json").read_text())["summary"]
            rows.append([f"{q}%（{focus[q]['actual_reference_completed']}/160）", LABELS[s],
                f"{failed['mean_wct_s']:.3f}", f"{float(r['mean_penalty_s']):.3f}", f"{float(r['p95_penalty_s']):.3f}"])
    compact_faults = []
    phases = read_csv("failure-focal-recovery-phases.csv")
    for r in rows:
        q = int(r[0].split("%",1)[0]); s = next(s for s in SYSTEMS if LABELS[s] == r[1])
        phase = next(p for p in phases if int(p["progress_pct"])==q and p["system"]==s)
        compact_faults.append("| " + " | ".join([f"{q}%",r[1],r[2],r[4],f"{float(phase['resume_s']):.3f}"]) + " |")
    faults = table(["预定位置（基准已完成）", "系统", "F1 平均 WCT (s)", "平均增量 (s)", "增量 P95 (s)"], rows)
    dag = table(["价值模型", "F0 平均 WCT (s)", "中期 F1 平均 WCT (s)", "F1−F0 (s)"],
        [[r["value_model"], *[f"{float(r[k]):.3f}" for k in ["healthy_wct_s", "failed_wct_s", "fault_penalty_s"]]] for r in read_csv("dag-ablation-summary.csv")])
    aimd = table(["30% DMA 敏感性条件", "平均 WCT (s)"],
        [[r["mode"], f"{float(r['mean_wct_s']):.3f}"] for r in read_csv("ablation-aimd-interference.csv")])
    mixes = read_csv("benefit-cost-fault-mixture.csv")
    z = {s: next(r for r in mixes if r["system"] == s) for s in SYSTEMS}
    comparisons = []
    for s in ["mooncake", "dram"]:
        intercept = float(z["aegis"]["no_fault_mean_wct_s"]) - float(z[s]["no_fault_mean_wct_s"])
        slope = float(z["aegis"]["mean_fault_penalty_s"]) - float(z[s]["mean_fault_penalty_s"])
        crossing = -intercept/slope if abs(slope) > 1e-12 else None
        if crossing is not None and 0 <= crossing <= 1:
            comparisons.append(f"相对 {LABELS[s]}，两条直线在 p={crossing:.3f} 相交")
        else:
            comparisons.append(f"相对 {LABELS[s]}，在 p∈[0,1] 没有交点（p=0/1 的 AegisKV−基线为 {intercept:.3f}/{intercept+slope:.3f} s）")
    overhead = (means["aegis"]["mean_wct_s"]/means["mooncake"]["mean_wct_s"]-1)*100
    return dict(compact_fault_rows="\n".join(compact_faults), healthy_results=healthy, fault_results=faults, dag_results=dag, aimd_results=aimd,
        mixture_results="；".join(comparisons)+"。这些交点只适用于图中明确的概率混合假设。",
        aegis_wct=f"{means['aegis']['mean_wct_s']:.3f}", overhead=f"{'增加' if overhead >= 0 else '下降'} {abs(overhead):.1f}%",
        aegis_hit=f"{means['aegis']['dram_hit_pct']:.2f}", mooncake_hit=f"{means['mooncake']['dram_hit_pct']:.2f}")


def build_latex(figures, groups, *, proof_note=None):
    def standalone(r, source_path):
        wide = r["width_in"] > 5
        env, width = ("figure*", r"\textwidth") if wide else ("figure", r"\columnwidth")
        return (f"\\begin{{{env}}}[t]\n\\centering\n\\includegraphics[width={width}]{{{source_path}}}\n"
            f"\\caption{{{tex_escape(r['caption_en'])}}}\n\\label{{fig:lease-{r['name']}}}\n\\end{{{env}}}\n")
    by_name = {r["name"]: r for r in figures}
    snippet_root = os.path.relpath(OUT, ROOT/"benchmark/AegisKV/paper")+"/"
    (OUT / "paper-figures.tex").write_text("% Paths relative to benchmark/AegisKV/paper.\n\n" +
        "\n".join(standalone(r, snippet_root + r["name"] + ".pdf") for r in figures if r["primary"]))
    (OUT / "supplement-figures.tex").write_text("\n".join(standalone(r, snippet_root+r["name"]+".pdf") for r in figures if not r["primary"]))
    pairs, proof = [], []
    for group in groups:
        if len(group) == 1:
            r = by_name[group[0]]
            proof.append(standalone(r, str(OUT/(r["name"]+".pdf"))))
        else:
            parts = []
            for name in group:
                r = by_name[name]; assert r["width_in"] < 5
                parts.append("\\begin{minipage}[t]{0.47619\\textwidth}\\vspace{0pt}\\centering\n" +
                    f"\\includegraphics[width=\\linewidth]{{{OUT/(name+'.pdf')}}}\n" +
                    f"\\caption{{{tex_escape(r['caption_en'])}}}\\label{{fig:lease-{name}}}\n\\end{{minipage}}")
            body = "\\begin{figure*}[t]\n"+"\n\\hfill\n".join(parts)+"\n\\end{figure*}\n"
            proof.append(body); pairs.append(body.replace(str(OUT)+"/", snippet_root))
    (OUT / "paper-pairs.tex").write_text("% Optional composition of independent PDFs.\n\n"+"\n".join(pairs))
    preamble = (r"\documentclass[sigplan,10pt,anonymous,balance=false]{acmart}" + "\n" +
        r"\setcopyright{none}\settopmatter{printacmref=false,printccs=false}" + "\n" +
        r"\acmConference[Figure proof]{AegisKV figure placement proof}{}{}\acmYear{2026}\copyrightyear{2026}\acmDOI{}\acmISBN{}" + "\n" +
        r"\renewcommand\footnotetextcopyrightpermission[1]{}\usepackage{graphicx}\raggedbottom" + "\n" +
        r"\begin{document}\title{AegisKV: Agent Subleases and Guarded AIMD}\author{Anonymous}\affiliation{\institution{Anonymous}\country{Anonymous}}\maketitle\pagestyle{plain}" + "\n" +
        (tex_escape(proof_note) if proof_note is not None else
         "Placement proof at the manuscript's actual column and text widths. Evidence classes are stated in captions. "
         "Quantitative results use frozen source-v3 experiments. Algorithm 2 is under revision; this proof reviews figure presentation only.") + "\n\\clearpage\n")
    source = OUT / "paper-placement.tex"
    source.write_text(preamble + "\n\\clearpage\n".join(proof) + "\n\\end{document}\n")
    bindings = {"source": sha(source), "class": sha(ROOT/"benchmark/AegisKV/paper/acmart.cls"),
        "figures": {r["name"]: sha(OUT/(r["name"]+".pdf")) for r in figures if r["primary"]}}
    bind_path = OUT / "placement-inputs.json"
    if not bind_path.exists() or json.loads(bind_path.read_text()) != bindings or not (OUT/"paper-placement.pdf").exists():
        with (ARTIFACTS/"placement-build.log").open("w") as log:
            for _ in range(2):
                subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={OUT}", str(source)],
                    cwd=ROOT/"benchmark/AegisKV/paper", env=dict(os.environ, SOURCE_DATE_EPOCH="1788825600", FORCE_SOURCE_DATE="1"), stdout=log, stderr=subprocess.STDOUT, check=True)
        bind_path.write_text(json.dumps(bindings, indent=2)+"\n")


def archive_and_review(figures):
    primary_count = sum(r["primary"] for r in figures)
    supplement_count = len(figures)-primary_count
    for current, prior in [("Paper_Draft.md", "Paper_Figures_PrefixAdmission_20260908.md"),
        ("PAPER_FIGURE_REVIEW.md", "PAPER_FIGURE_REVIEW_PrefixAdmission_20260908.md")]:
        source, saved = DIRECTORY/current, DIRECTORY/prior
        if not saved.exists():
            assert "Agent 子租约" not in source.read_text()[:400]
            saved.write_bytes(source.read_bytes())
    archive = DIRECTORY / "Old_Figures.md"
    text = archive.read_text()
    start, end = "<!-- AGENT_LEASE_REVISION_START -->", "<!-- AGENT_LEASE_REVISION_END -->"
    if start in text:
        text = text[:text.index(start)] + text[text.index(end)+len(end):]
    lines = [start, "## 版本边界：当前算法与旧 PrefixAdmission", "",
        "当前 [Paper_Draft.md](Paper_Draft.md) 使用 Agent 子租约 / Guarded AIMD 的 source-v3 实验。此前 33 图叙述完整保存在 [旧版论文图](Paper_Figures_PrefixAdmission_20260908.md) 和 [旧审查记录](PAPER_FIGURE_REVIEW_PrefixAdmission_20260908.md)，旧 raw 与图像未改写，不能用旧数值描述新算法。", "",
        "改写为论文初稿前的图集正文保存在 " + link(OUT/"before-paper-draft/Paper_Figures.md", "38 图目录版正文") + "；精简前的 38 图初稿见 " + link(OUT/"before-compact-paper/FIGURES.md", "本次精简前归档") + f"。当前正文 {primary_count} 张，另有 {supplement_count} 张补充图保留在下方。", "",
        "本轮 PaperBanana 优化前的同版 51 图保存在 " + link(BASELINE.parent/"FIGURES.md", "视觉修改前的完整目录") + "；两版采用同一组数据，差异为表达与布局。", "",
        '<a id="agent-lease-supplements"></a>', "## 新算法的补充与诊断图", "",
        "这些图来自同一新实验或实际 GPU 微基准。它们因叙述层级或与主图互补而放入补充材料，并非因为结果为零或不利；主文也保留不利结果。", ""]
    for r in figures:
        if r["primary"]: continue
        lines += [f"### {r['id']}｜{r['title']}", "", r["caption_zh"], "", assets(r), "", preview(r), ""]
    lines += [end, ""]
    pos = text.find("\n\n") + 2
    archive.write_text(text[:pos]+"\n".join(lines)+text[pos:])
    review = ["# 论文初稿的逐图审查与证据范围", "", "[论文初稿](Paper_Draft.md) · [历史审查](PAPER_FIGURE_REVIEW_PrefixAdmission_20260908.md)", "",
        "本轮只优化图像，数据沿用此前冻结的 source-v3 实验。Algorithm 2 仍在调整，按用户要求暂缓实现同步；设计图说明机制，定量图不作为后续修改版本的运行证据。统计图统一三系统颜色、线型和固定 Workflow 映射；示意图使用具体共享块、数值账本、显存比例与同一对象的提交状态。所有输出按 7 / 3.33 inch 绘制，独立 PDF 可直接被 LaTeX 组合。实际字体、来源哈希、账本与最终导出的核对结果见 " + link(ARTIFACTS/"DELIVERY_AUDIT.json", "本轮核对记录") + "。", "",
        "## 从图集到论文初稿", "",
        "Paper_Draft.md 为中文正文，仅含 Motivation、System Design 和 Evaluation 三部分，12 张正文图连续编号（Motivation 3、System Design 1、Evaluation 8）。Motivation 用三条 Observation 推导设计要求；System Design 只展示一张完整架构；Evaluation 按八个问题选图，配置和机制消融用表格呈现。原 49 个 CSV 与全部未改统计图保持原样，新图由既有证据重新组合。", "",
        "结构与背景参考 [原论文](../paper/main.tex) 的 [Motivation](../paper/sections/motivation.tex)、[System Design](../paper/sections/system-design.tex)、[Experimental Method](../paper/sections/experimental-method.tex) 和 [Results](../paper/sections/results.tex)。原文的 PrefixAdmission、170 次旧矩阵和 RTX4090 旧结果不移入当前初稿；source-v3、三系统比较及 L40S 组件数据沿当前图像来源。Algorithm 2 后续设计调整仍未同步为本节实验。", "",
        "正文源为 [agent-lease-draft.md](scripts/paper/templates/agent-lease-draft.md)，图注源为 [agent_lease_draft_captions.py](scripts/paper/agent_lease_draft_captions.py)。" +
        " [独立图 LaTeX](" + rel(OUT/"paper-figures.tex") + ") · [可选同行 LaTeX](" + rel(OUT/"paper-pairs.tex") + ") · [图像插入尺寸样张](" + rel(OUT/"paper-placement.pdf") + ") · [正文浏览器预览](" + rel(OUT/"paper-story.html") + ")。尺寸样张只展示图与英文图注，不是中文全文 PDF。", "",
        "## PaperBanana 内容与风格规格", "",
        "本轮在 55 组可追溯图中选取 12 张正文图，43 张保留为补充。新增恢复暴露、综合成本、共同坐标原生干扰、逐配置敏感性四种图像，重画完整 System Overview。规划与保留/合并理由见 [紧凑图稿规格](scripts/paper/templates/compact-figure-spec.md)。三条动机分别使用轨迹观测、旧模型推演和解析容量，不能互相混作实验重复。", "",
        "| 实际查看的参考 | 借鉴对象 | 当前图的应用 |", "|---|---|---|",
        "| [Ensō，OSDI 2023](../docs/related_works/figure-references-20260908/enso-osdi23.pdf)，对象状态图 | 同一对象在不同状态下的排列与直接标签 | 子租约、准入、独立提交；不沿用参考论文的机制 |",
        "| [Mooncake，FAST 2025](../docs/related_works/figure-references-20260908/mooncake-fast25.pdf)，资源架构与代价分解 | 物理资源分组、分解柱与相邻证据 | Source/Peer/Store、显存布局、CPU/流量分解 |",
        "| [CausalSim，NSDI 2023](../docs/related_works/figure-references-20260908/causalsim-nsdi23.pdf)，定量比较 | 线型/标记冗余编码、共享图例与分布 | 三系统曲线、入场顺序包络、原生微基准 |", "",
        "统计图以 Mooncake 灰、DRAM-only AegisKV 橙、AegisKV 蓝为系统编码；组成柱的颜色表示来源，系统另标在横轴。密集 Workflow 图每十对象添加形状标记，连线仍保留全部对象。单栏图例集中于顶部独立区域，字号至少 10 pt；宽图为 7 inch、单栏为 3.33 inch。相邻比较共用可比坐标，局部放大的轴在图注中说明。", "",
        "设计图采用可编辑矢量对象；提交状态图中的填充表示已提交，虚线轮廓表示 pending，划除表示释放/中止；不同图中的虚线含义由局部标签与图注明确。Q 边界透明以保持对象可见。AIMD 的 C/Q/Used 分栏显示，额外前台需求先裁剪授权，物理容量由 free ACK 确认。", "",
        "## 逐图优化与核对", "",
        "| 图 | 证据类型 | 本轮优化 | 科学口径与范围 | 去向 |", "|---|---|---|---|---|"]
    for r in figures:
        dest = f"Paper_Draft.md#paper-{r['name']}" if r["primary"] else "Old_Figures.md#agent-lease-supplements"
        review.append(f"| [{r['id']} {r['title']}]({dest}) | {EVIDENCE[r['evidence']]} | {visual_treatment(r['name'])} | {r['caption_zh']} | {'正文' if r['primary'] else '补充'} |")
    review += ["", "## 验证与剩余范围", "", "52 项针对性回归覆盖 Agent 分支/轮号、同轮信用、Q 尾块刷新、拒绝回滚、复制提交、AIMD 与连续推理调度。实验源码先冻结，再执行矩阵；运行正确性不等于实际硬件性能得到验证。", "",
        "原生组件新增 360 个 forward 样本与按对象大小各 20 次释放测量。尚缺原生三系统端到端服务、在线预测器校准、多工作负载及多故障泛化。相关限制已进入主文图注，不能将形式正确或审查 PASS 写成系统收益已获证明。", "",
        "设计语言沿用 [Best Paper 实际图页审查](../docs/paper/BEST_PAPER_FIGURE_REVIEW.md) 的具体对象、状态对比和相邻证据组织；未复制参考论文的图像或数据。", ""]
    (DIRECTORY/"PAPER_FIGURE_REVIEW.md").write_text("\n".join(review))


def main():
    active = DIRECTORY/"ACTIVE_PAPER_EDITION.json"
    if active.exists() and json.loads(active.read_text()).get("edition") == "evidence-revision-20260909":
        from build_revision_story import main as build_current_revision
        return build_current_revision()
    if (DIRECTORY/"evaluation-design/protocol.json").exists():
        from build_evaluation_redesign import main as build_current_evaluation
        return build_current_evaluation()
    aggregate = OUT/"statistics-all-manifest.json"
    statistics = [aggregate] if aggregate.exists() else [OUT/f"statistics-{part}-manifest.json" for part in ["support", "core", "failure", "sensitivity", "mechanism", "order"]]
    manifest_files = statistics + [OUT/"native-manifest.json", OUT/"diagrams-manifest.json", OUT/"compact-manifest.json"]
    rendered = {r["name"]: r for p in manifest_files for r in json.loads(p.read_text())["figures"]}
    records = captions(); assert {r["name"] for r in records} == rendered.keys()
    assert set(DRAFT_CAPTIONS) == {r["name"] for r in records if r["primary"]}
    for r in records:
        r.update(rendered[r["name"]])
        assert r["evidence"] in EVIDENCE, r["evidence"]
        for ext, expected in r["files"].items(): assert sha(OUT/(r["name"]+"."+ext)) == expected
    template = TEMPLATE.read_text(); groups = [m[2].split(",") for m in re.finditer(r"\{\{(fig|row):([^}]+)\}\}", template)]
    names = [name for g in groups for name in g]
    assert len(names) == len(set(names)) and set(names) == {r["name"] for r in records if r["primary"]}
    by_name = {r["name"]: r for r in records}
    sections = {}
    section = None
    for line in template.splitlines():
        if line.startswith("## "): section = line[3:]
        for match in re.finditer(r"\{\{(?:fig|row):([^}]+)\}\}", line):
            for name in match[1].split(","): sections[name] = section
    assert Counter(sections.values()) == {"Motivation":3,"System Design":1,"Evaluation":8}
    counter = Counter()
    for number, name in enumerate(names, 1):
        section = sections[name]
        counter[section] += 1; by_name[name]["section"] = section
        by_name[name]["catalogue_id"] = {"Motivation":"M", "System Design":"S", "Evaluation":"E"}[section]+str(counter[section])
        by_name[name]["id"] = str(number)
        by_name[name]["draft_title"], by_name[name]["draft_caption"] = DRAFT_CAPTIONS[name]
    for i, r in enumerate([r for r in records if not r["primary"]], 1):
        r.update(id=f"A{i}", section="Supplement")
    def fig(m):
        r = by_name[m[1]]
        return (f'<a id="paper-{r["name"]}"></a>\n\n<figure class="paper-figure">\n\n{preview(r)}\n\n'
            f'**图 {r["id"]}：{r["draft_title"]}。** {r["draft_caption"]}\n\n</figure>')
    def pair(m):
        rows = [by_name[name] for name in m[1].split(",")]
        assert len(rows) == 2 and all(r["width_in"] < 5 for r in rows)
        return "\n".join([*(f'<a id="paper-{r["name"]}"></a>' for r in rows), "", table(
            [f"**图 {r['id']}：{r['draft_title']}**" for r in rows], [[preview(r) for r in rows], [r["draft_caption"] for r in rows]])])
    text = re.sub(r"\{\{fig:([^}]+)\}\}", fig, template)
    text = re.sub(r"\{\{row:([^}]+)\}\}", pair, text)
    text = re.sub(r"\{\{ref:([^}]+)\}\}", lambda m: by_name[m[1]]["id"], text)
    for k, v in dict(result_text(), primary_count=len(names), supplement_count=len(records)-len(names)).items():
        text = text.replace("{{"+k+"}}", str(v))
    assert "{{" not in text
    archive_and_review(records)
    (DIRECTORY/"Paper_Draft.md").write_text(text)
    (DIRECTORY/"FIGURES.md").write_text("# AegisKV 论文与图像导航\n\n- [论文初稿：Motivation / System Design / Evaluation](Paper_Draft.md)\n- [图像来源、逐图审查与复现入口](PAPER_FIGURE_REVIEW.md)\n- [实验协议](AGENT_LEASE_PROTOCOL.md)\n- [旧版本与补充图](Old_Figures.md)\n")
    selection = dict(schema="aegiskv.agent_lease.paper_selection.v1", figures=records, layout_groups=groups,
        visual_revision=visual_revision(records),
        draft=dict(path=str((DIRECTORY/"Paper_Draft.md").relative_to(ROOT)), language="zh-CN",
            captions_sha256=sha(Path(__file__).with_name("agent_lease_draft_captions.py")),
            original_paper_sources={str(p.relative_to(ROOT)):sha(p) for p in
                [ROOT/f"benchmark/AegisKV/paper/sections/{s}.tex" for s in
                    ["motivation","system-design","experimental-method","results"]]},
            scope="Compact Chinese paper: three Observations, one System Overview, eight question-driven Evaluation figures; no new experiment or algorithm implementation",
            prior_document=str((OUT/"before-compact-paper/FIGURES.md").relative_to(ROOT))),
        source_snapshot=str((ARTIFACTS/"source-v3/MECHANISM_SOURCE_SNAPSHOT.json").relative_to(ROOT)),
        manifest_bindings={str(p.relative_to(ROOT)):sha(p) for p in manifest_files},
        template_sha256=sha(TEMPLATE), generator_sha256=sha(Path(__file__)), captions_sha256=sha(Path(__file__).with_name("agent_lease_story_content.py")))
    (ARTIFACTS/"paper-selection.json").write_text(json.dumps(selection, indent=2, ensure_ascii=False)+"\n")
    build_latex([by_name[name] for name in names] + [r for r in records if not r["primary"]], groups)
    print(json.dumps(dict(primary=len(names), supplement=len(records)-len(names), paired_rows=sum(len(g)==2 for g in groups)), ensure_ascii=False))


if __name__ == "__main__": main()
