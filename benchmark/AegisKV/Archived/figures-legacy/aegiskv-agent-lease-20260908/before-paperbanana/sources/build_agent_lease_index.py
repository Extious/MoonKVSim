"""Publish the current algorithm's story, captions and final-width placement proof."""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

from agent_lease_story_content import captions
from build_paper_story_index import tex_escape
from paper_paths import ROOT
from three_system_data import SYSTEMS, LABELS, sha

DIRECTORY = ROOT / "benchmark/AegisKV/experiments"
ARTIFACTS = ROOT / "output/agent-lease-20260908"
OUT = ROOT / "output/pdf/aegiskv-agent-lease-20260908"
TEMPLATE = Path(__file__).with_name("templates") / "agent-lease-story.md"
EVIDENCE = {
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
    return f'[<img src="{rel(OUT / (name + ".png"))}" width="{width}" alt="{html.escape(row["id"] + " " + row["title"], quote=True)}">]({rel(OUT / (name + ".pdf"))})'


def read_csv(name):
    import csv
    with (OUT / name).open() as f:
        return list(csv.DictReader(f))


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|"*len(headers)] +
        ["| " + " | ".join(map(str, row)) + " |" for row in rows])


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
        rows.append([f"{q}%", f"{focus[q]['actual_reference_completed']}/160",
            " / ".join(f"{float(next(r for r in failure if r['system']==s and int(r['progress_pct'])==q)['p95_penalty_s']):.3f}" for s in SYSTEMS)])
    faults = table(["预定位置", "参考时已完成 Workflow", "P95 配对 WCT 变化 (s)：Mooncake / DRAM-only / AegisKV"], rows)
    faults += "\n\n这些百分位是单次配置中 160 个对象的描述统计；三个不同位置没有被当作独立重复。"
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
    return dict(healthy_results=healthy, fault_results=faults, dag_results=dag, aimd_results=aimd,
        mixture_results="；".join(comparisons)+"。这些交点只适用于图中明确的概率混合假设。",
        aegis_wct=f"{means['aegis']['mean_wct_s']:.3f}", overhead=f"{'增加' if overhead >= 0 else '下降'} {abs(overhead):.1f}%",
        aegis_hit=f"{means['aegis']['dram_hit_pct']:.2f}", mooncake_hit=f"{means['mooncake']['dram_hit_pct']:.2f}")


def build_latex(figures, groups):
    def standalone(r, source_path):
        wide = r["width_in"] > 5
        env, width = ("figure*", r"\textwidth") if wide else ("figure", r"\columnwidth")
        return (f"\\begin{{{env}}}[t]\n\\centering\n\\includegraphics[width={width}]{{{source_path}}}\n"
            f"\\caption{{{tex_escape(r['caption_en'])}}}\n\\label{{fig:lease-{r['name']}}}\n\\end{{{env}}}\n")
    by_name = {r["name"]: r for r in figures}
    snippet_root = "../../../output/pdf/aegiskv-agent-lease-20260908/"
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
        "Placement proof at the manuscript's actual column and text widths. Evidence classes are stated in captions.\n\\clearpage\n")
    source = OUT / "paper-placement.tex"
    source.write_text(preamble + "\n\\clearpage\n".join(proof) + "\n\\clearpage\n" +
        "\n\\clearpage\n".join(standalone(r, str(OUT/(r["name"]+".pdf"))) for r in figures if not r["primary"]) + "\n\\end{document}\n")
    bindings = {"source": sha(source), "class": sha(ROOT/"benchmark/AegisKV/paper/acmart.cls"),
        "figures": {r["name"]: sha(OUT/(r["name"]+".pdf")) for r in figures}}
    bind_path = OUT / "placement-inputs.json"
    if not bind_path.exists() or json.loads(bind_path.read_text()) != bindings or not (OUT/"paper-placement.pdf").exists():
        with (ARTIFACTS/"placement-build.log").open("w") as log:
            for _ in range(2):
                subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={OUT}", str(source)],
                    cwd=ROOT/"benchmark/AegisKV/paper", env=dict(os.environ, SOURCE_DATE_EPOCH="1788825600", FORCE_SOURCE_DATE="1"), stdout=log, stderr=subprocess.STDOUT, check=True)
        bind_path.write_text(json.dumps(bindings, indent=2)+"\n")


def archive_and_review(figures):
    for current, prior in [("Paper_Figures.md", "Paper_Figures_PrefixAdmission_20260908.md"),
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
        "当前 [Paper_Figures.md](Paper_Figures.md) 使用 Agent 子租约 / Guarded AIMD 的 source-v3 新实验。此前 33 图叙述完整保存在 [旧版论文图](Paper_Figures_PrefixAdmission_20260908.md) 和 [旧审查记录](PAPER_FIGURE_REVIEW_PrefixAdmission_20260908.md)，旧 raw 与图像未改写，不能用旧数值描述新算法。", "",
        '<a id="agent-lease-supplements"></a>', "## 新算法的补充与诊断图", "",
        "这些图来自同一新实验或实际 GPU 微基准。它们因叙述层级或与主图互补而放入补充材料，并非因为结果为零或不利；主文也保留不利结果。", ""]
    for r in figures:
        if r["primary"]: continue
        lines += [f"### {r['id']}｜{r['title']}", "", r["caption_zh"], "", assets(r), "", preview(r), ""]
    lines += [end, ""]
    pos = text.find("\n\n") + 2
    archive.write_text(text[:pos]+"\n".join(lines)+text[pos:])
    review = ["# 当前算法的逐图审查与证据范围", "", "[论文叙述](Paper_Figures.md) · [历史审查](PAPER_FIGURE_REVIEW_PrefixAdmission_20260908.md)", "",
        "本版重新执行新 Algorithm 2/3，旧算法数值不复用。统计图沿用三系统颜色、线型和固定 Workflow 映射；示意图使用具体共享块、数值账本、显存比例与同一对象的提交状态。所有输出按 7 / 3.33 inch 绘制，独立 PDF 可直接被 LaTeX 组合。实际字体、来源哈希、账本与最终导出的核对结果见 " + link(ARTIFACTS/"DELIVERY_AUDIT.json", "本轮核对记录") + "。", "",
        "| 图 | 证据类型 | 本次核对的核心问题 | 去向 |", "|---|---|---|---|"]
    for r in figures:
        dest = f"Paper_Figures.md#paper-{r['name']}" if r["primary"] else "Old_Figures.md#agent-lease-supplements"
        review.append(f"| [{r['id']} {r['title']}]({dest}) | {EVIDENCE[r['evidence']]} | {r['caption_zh']} | {'正文候选' if r['primary'] else '补充'} |")
    review += ["", "## 验证与剩余范围", "", "52 项针对性回归覆盖 Agent 分支/轮号、同轮信用、Q 尾块刷新、拒绝回滚、复制提交、AIMD 与连续推理调度。实验源码先冻结，再执行矩阵；运行正确性不等于实际硬件性能得到验证。", "",
        "原生组件新增 360 个 forward 样本与按对象大小各 20 次释放测量。尚缺原生三系统端到端服务、在线预测器校准、多工作负载及多故障泛化。相关限制已进入主文图注，不能将形式正确或审查 PASS 写成系统收益已获证明。", "",
        "设计语言沿用 [Best Paper 实际图页审查](../docs/paper/BEST_PAPER_FIGURE_REVIEW.md) 的具体对象、状态对比和相邻证据组织；未复制参考论文的图像或数据。", ""]
    (DIRECTORY/"PAPER_FIGURE_REVIEW.md").write_text("\n".join(review))


def main():
    aggregate = OUT/"statistics-all-manifest.json"
    statistics = [aggregate] if aggregate.exists() else [OUT/f"statistics-{part}-manifest.json" for part in ["support", "core", "failure", "sensitivity", "mechanism", "order"]]
    manifest_files = statistics + [OUT/"native-manifest.json", OUT/"diagrams-manifest.json"]
    rendered = {r["name"]: r for p in manifest_files for r in json.loads(p.read_text())["figures"]}
    records = captions(); assert {r["name"] for r in records} == rendered.keys()
    for r in records:
        r.update(rendered[r["name"]])
        assert r["evidence"] in EVIDENCE, r["evidence"]
        for ext, expected in r["files"].items(): assert sha(OUT/(r["name"]+"."+ext)) == expected
    template = TEMPLATE.read_text(); groups = [m[2].split(",") for m in re.finditer(r"\{\{(fig|row):([^}]+)\}\}", template)]
    names = [name for g in groups for name in g]
    assert len(names) == len(set(names)) and set(names) == {r["name"] for r in records if r["primary"]}
    by_name = {r["name"]: r for r in records}
    section = "Motivation"; counter = Counter()
    for name in names:
        if name == "system-overview": section = "System Design"
        if name == "workload-prompt_tokens": section = "Evaluation"
        counter[section] += 1; by_name[name]["section"] = section
        by_name[name]["id"] = {"Motivation":"M", "System Design":"S", "Evaluation":"E"}[section]+str(counter[section])
    for i, r in enumerate([r for r in records if not r["primary"]], 1):
        r.update(id=f"A{i}", section="Supplement")
    def fig(m):
        r = by_name[m[1]]
        return f'<a id="paper-{r["name"]}"></a>\n\n**图 {r["id"]}｜{r["title"]}。** {r["caption_zh"]}\n\n{assets(r)}\n\n{preview(r)}'
    def pair(m):
        rows = [by_name[name] for name in m[1].split(",")]
        assert len(rows) == 2 and all(r["width_in"] < 5 for r in rows)
        return "\n".join([*(f'<a id="paper-{r["name"]}"></a>' for r in rows), "", table(
            [f"**图 {r['id']}：{r['title']}**" for r in rows], [[preview(r) for r in rows], [r["caption_zh"] for r in rows], [assets(r) for r in rows]])])
    text = re.sub(r"\{\{fig:([^}]+)\}\}", fig, template)
    text = re.sub(r"\{\{row:([^}]+)\}\}", pair, text)
    text = re.sub(r"\{\{ref:([^}]+)\}\}", lambda m: by_name[m[1]]["id"], text)
    for k, v in dict(result_text(), primary_count=len(names), supplement_count=len(records)-len(names)).items():
        text = text.replace("{{"+k+"}}", str(v))
    assert "{{" not in text
    archive_and_review(records)
    (DIRECTORY/"Paper_Figures.md").write_text(text)
    (DIRECTORY/"FIGURES.md").write_text("# AegisKV 图像导航\n\n- [当前算法的论文图：Motivation / System Design / Evaluation](Paper_Figures.md)\n- [逐图审查与证据范围](PAPER_FIGURE_REVIEW.md)\n- [本轮实验协议](AGENT_LEASE_PROTOCOL.md)\n- [旧版本与当前补充图](Old_Figures.md)\n")
    selection = dict(schema="aegiskv.agent_lease.paper_selection.v1", figures=records, layout_groups=groups,
        source_snapshot=str((ARTIFACTS/"source-v3/MECHANISM_SOURCE_SNAPSHOT.json").relative_to(ROOT)),
        manifest_bindings={str(p.relative_to(ROOT)):sha(p) for p in manifest_files},
        template_sha256=sha(TEMPLATE), generator_sha256=sha(Path(__file__)), captions_sha256=sha(Path(__file__).with_name("agent_lease_story_content.py")))
    (ARTIFACTS/"paper-selection.json").write_text(json.dumps(selection, indent=2, ensure_ascii=False)+"\n")
    build_latex(records, groups)
    print(json.dumps(dict(primary=len(names), supplement=len(records)-len(names), paired_rows=sum(len(g)==2 for g in groups)), ensure_ascii=False))


if __name__ == "__main__": main()
