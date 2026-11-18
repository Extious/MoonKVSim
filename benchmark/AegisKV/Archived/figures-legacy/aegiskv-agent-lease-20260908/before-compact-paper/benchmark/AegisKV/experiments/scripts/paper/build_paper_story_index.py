"""Build the three-part narrative and reusable captions without losing old plots."""

import html
import json
import os
import re
import subprocess
from pathlib import Path

from paper_paths import ROOT, DATA
from paper_story_content import records
from three_system_data import SYSTEMS, sha

DIRECTORY = ROOT / "benchmark/AegisKV/experiments"
OUT = ROOT / "output/pdf/aegiskv-paper-story-20260908"
ARTIFACTS = ROOT / "output/paper-story-20260908"
TEMPLATE = Path(__file__).with_name("templates") / "paper-story.md"
SELECTION = DATA / "paper-story-selection.json"
START = "<!-- THREE_SYSTEM_REVIEW_START -->"
END = "<!-- THREE_SYSTEM_REVIEW_END -->"


def link(path, label):
    return f"[{label}]({os.path.relpath(path, DIRECTORY)})"


def image_link(row):
    name = row["name"]
    width = 1008 if row["width_in"] > 5 else 480
    src = os.path.relpath(OUT / f"{name}.png", DIRECTORY)
    target = os.path.relpath(OUT / f"{name}.pdf", DIRECTORY)
    alt = html.escape(row["id"] + " " + row["title"], quote=True)
    return f'[<img src="{src}" width="{width}" alt="{alt}">]({target})'


def tex_escape(value):
    mapping = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(mapping.get(c, c) for c in value)


def build_archive():
    archive = DIRECTORY / "Old_Figures.md"
    text = archive.read_text()
    a = text.index(START)
    b = text.index(END) + len(END)
    section = text[a:b]
    names = set(re.findall(r"!\[[^\]]*\]\([^\n)]+/([^/]+)\.png\)", section))
    if len(names) != 186:
        original = (
            ROOT / "output/three-system-20260908/campaign-final/FIGURES-before-split.txt"
        ).read_text()
        section = original[original.index(START) : original.index(END) + len(END)]
    section = section.replace(
        "## 本轮更新：三系统逐 Workflow 对比（2026-09-08）", "## 2026-09-08 source-v6 完整图与诊断"
    )
    section = re.sub(
        r"^(?:当前本轮有|本节展示) .*?$",
        "本节保留 source-v6 的 **186 张原始独立图**；它们的重绘版及新增证据见 [Paper_Draft.md](Paper_Draft.md)。",
        section,
        flags=re.M,
    )
    prefix = (
        "# AegisKV 旧图与诊断归档\n\n[论文叙述与新图](Paper_Draft.md) · [逐图修改记录](PAPER_FIGURE_REVIEW.md) · [总导航](FIGURES.md)\n\n"
        "这里保留 source-v6 的 186 张原版图、历史版本、格式副本和原审查记录。原图文件与原始数据均未覆盖。"
        "本轮对原论文版 21 张图全部重绘；新增机制与结果图在论文版按三部分叙述。归档保留零结果和不利结果，不能据是否入选判断数据真假。\n\n"
        + link(ARTIFACTS / "before-story-Paper_Figures.md", "重写前的 21 图论文版")
        + " · "
        + link(ARTIFACTS / "before-story-Old_Figures.md", "重写前的归档")
        + "\n\n"
    )
    prefix += (
        link(OUT / "before-best-paper-review/FIGURES.md", "本次获奖论文对照改版前的 36 图") + "\n\n"
    )
    archive.write_text(prefix + section + text[b:])


def build():
    # The Agent-lease manuscript owns the live draft once that edition exists.
    # Old pipeline entrypoints must not restore PrefixAdmission text over it.
    if (ROOT/"output/agent-lease-20260908/paper-selection.json").exists():
        from build_agent_lease_index import main
        return main()
    manifest_files = [
        OUT / f
        for f in ("statistics-manifest.json", "diagrams-manifest.json", "failure-manifest.json")
    ]
    manifests = [json.loads(p.read_text()) for p in manifest_files]
    media = {r["name"]: r for m in manifests for r in m["figures"]}
    figures = records()
    assert {r["name"] for r in figures} == media.keys() and len(figures) == 33
    text = TEMPLATE.read_text()
    groups = [m.split("|") for m in re.findall(r"\{\{(?:fig|row):([^}]+)\}\}", text)]
    order = [name for group in groups for name in group]
    assert len(order) == len(set(order)) and set(order) == media.keys()
    by_name = {r["name"]: r for r in figures}
    figures = [by_name[name] for name in order]
    counters = {}
    for row in figures:
        section = row["section"]
        counters[section] = counters.get(section, 0) + 1
        row["id"] = {"Motivation": "M", "System Design": "S", "Evaluation": "E"}[section] + str(
            counters[section]
        )
    failure = manifests[-1]
    labels = {
        "trace_observation": "trace 观测",
        "analytical": "解析推导",
        "design": "设计示意",
        "workload_description": "输入统计",
        "modeled_exploration": "机制模拟",
    }
    rendered = {}
    for row in figures:
        name = row["name"]
        record = media[name]
        for ext, digest in record["files"].items():
            assert sha(OUT / f"{name}.{ext}") == digest, (name, ext)
        row["width_in"] = record["width_in"]
        row["files"] = record["files"]
        parts = [
            f'<a id="paper-{name}"></a>',
            "",
            f"**图 {row['id']}｜{row['title']}。** {row['caption_zh']}",
            "",
            link(OUT / f"{name}.pdf", "PDF")
            + " · "
            + link(OUT / f"{name}.svg", "SVG")
            + " · "
            + link(
                OUT / (name + "." + ("drawio" if row["evidence"] == "design" else "csv")),
                "可编辑源" if row["evidence"] == "design" else "图中数据",
            )
            + f" · {labels[row['evidence']]} · {record['width_in']:.2f} inch",
            "",
            image_link(row),
        ]
        rendered[name] = "\n".join(parts)
    text = re.sub(r"\{\{fig:([^}]+)\}\}", lambda m: rendered[m[1]], text)

    def pair(match):
        rows = [by_name[name] for name in match[1].split("|")]
        assert len(rows) == 2 and all(r["width_in"] < 5 for r in rows)
        anchors = "\n".join(f'<a id="paper-{r["name"]}"></a>' for r in rows)

        def cells(values):
            return (
                "| "
                + " | ".join(v.replace("|", "&#124;").replace("\n", " ") for v in values)
                + " |"
            )

        return "\n".join(
            [
                anchors,
                "",
                cells([f"**图 {r['id']}：{r['title']}**" for r in rows]),
                "| :--- | :--- |",
                cells([image_link(r) for r in rows]),
                cells([r["caption_zh"] for r in rows]),
                cells(
                    [
                        link(OUT / (r["name"] + ".pdf"), "PDF")
                        + " · "
                        + link(OUT / (r["name"] + ".svg"), "SVG")
                        + " · "
                        + link(OUT / (r["name"] + ".csv"), "数据")
                        + " · "
                        + labels[r["evidence"]]
                        for r in rows
                    ]
                ),
            ]
        )

    text = re.sub(r"\{\{row:([^}]+)\}\}", pair, text)
    text = re.sub(r"\{\{ref:([^}]+)\}\}", lambda m: by_name[m[1]]["id"], text)
    table = [
        "补跑包括 **12 次执行**：三个系统各一次无故障对照，加三个故障位置各三个系统；各位置每系统一次，未把不同干预当成独立重复。三组新 F0 的 160 个 WCT 均与原 source-v6 对照完全一致。",
        "",
        "| 预定位置 | 参考时已完成 Workflow | Mooncake / DRAM-only / AegisKV 的 P95 配对 WCT 差值 |",
        "|---|---:|---|",
    ]
    for plan in failure["plans"]:
        vals = {r["system"]: r for r in failure["summary"] if r["case"] == plan["case"]}
        table.append(
            f"| {plan['nominal_progress_pct']}% 附近 | {plan['reference_completed_workflows']}/160（{plan['reference_progress_pct']:.3f}%） | "
            + " / ".join(f"{vals[s]['p95_wct_delta_s']:.3f} s" for s in SYSTEMS)
            + " |"
        )
    table += [
        "",
        "这些数值衡量不同故障位置对本输入的影响；同一 GPU 上的其他活跃请求也可能受故障影响。完整选点、实际事件、恢复 token 与阶段时长见 "
        + link(OUT / "failure-focus-plan.csv", "选点 CSV")
        + " 和 "
        + link(OUT / "failure-focal-recovery-phases.csv", "恢复阶段 CSV")
        + "。",
    ]
    text = text.replace("{{fault_results}}", "\n".join(table))
    assert "{{" not in text
    (DIRECTORY / "Paper_Draft.md").write_text(text)
    selection = {
        "schema": "aegiskv.paper_story.selection.v2",
        "figures_directory": str(OUT.relative_to(ROOT)),
        "story_template": str(TEMPLATE.relative_to(ROOT)),
        "figures": figures,
        "layout_groups": groups,
        "manifest_bindings": {str(p.relative_to(ROOT)): sha(p) for p in manifest_files},
        "evidence_scope": "observed_motivation_analytical_design_and_explicitly_modeled_evaluation_not_native_submission_claims",
    }
    SELECTION.write_text(json.dumps(selection, indent=2, ensure_ascii=False) + "\n")
    build_archive()
    (DIRECTORY / "FIGURES.md").write_text(
        "# AegisKV 图像导航\n\n- [论文图与叙述：Motivation / System Design / Evaluation](Paper_Draft.md)\n- [逐图审查、修改与待补实验](PAPER_FIGURE_REVIEW.md)\n- [旧图与诊断归档](Old_Figures.md)\n"
    )
    build_latex(figures, groups)
    build_review(figures)
    return {
        "paper_figures": len(figures),
        "design_figures": 5,
        "paired_rows": sum(len(g) == 2 for g in groups),
        "archive_original_figures": 186,
    }


def build_latex(figures, groups):
    snippets = []
    proof = []
    for row in figures:
        name = row["name"]
        wide = row["width_in"] > 5
        env = "figure*" if wide else "figure"
        width = r"\textwidth" if wide else r"\columnwidth"
        # Paths are relative to benchmark/AegisKV/paper, the manuscript build directory.
        image = "../../../output/pdf/aegiskv-paper-story-20260908/" + name + ".pdf"
        body = (
            f"\\begin{{{env}}}[t]\n\\centering\n\\includegraphics[width={width}]{{{image}}}\n"
            f"\\caption{{{tex_escape(row['caption_en'])}}}\n\\label{{fig:{name}}}\n\\end{{{env}}}\n"
        )
        snippets.append(f"% {row['id']} | {name} | {row['evidence']}\n" + body)
    by_name = {row["name"]: row for row in figures}
    pair_snippets = []
    for names in groups:
        rows = [by_name[n] for n in names]
        if len(rows) == 1:
            row = rows[0]
            name = row["name"]
            wide = row["width_in"] > 5
            env = "figure*" if wide else "figure"
            width = r"\textwidth" if wide else r"\columnwidth"
            body = f"\\begin{{{env}}}[t]\n\\centering\n\\includegraphics[width={width}]{{{OUT / (name + '.pdf')}}}\n\\caption{{{tex_escape(row['caption_en'])}}}\n\\end{{{env}}}\n"
        else:
            pieces = []
            for row in rows:
                pieces.append(
                    "\\begin{minipage}[t]{0.47619\\textwidth}\\vspace{0pt}\\centering\n"
                    + f"\\includegraphics[width=\\linewidth]{{{OUT / (row['name'] + '.pdf')}}}\n"
                    + f"\\caption{{{tex_escape(row['caption_en'])}}}\\label{{fig:{row['name']}}}\n"
                    + "\\end{minipage}"
                )
            body = "\\begin{figure*}[t]\n" + "\n\\hfill\n".join(pieces) + "\n\\end{figure*}\n"
            pair_snippets.append(
                body.replace(str(OUT), "../../../output/pdf/aegiskv-paper-story-20260908")
            )
        proof.append(body + "\\clearpage\n")
    (OUT / "paper-story-pairs.tex").write_text(
        "% Optional composition; images remain independent.\n\n" + "\n".join(pair_snippets)
    )
    (OUT / "paper-story-figures.tex").write_text(
        "% Insert from benchmark/AegisKV/paper; independent figures may be composed by LaTeX.\n\n"
        + "\n".join(snippets)
    )
    preamble = (
        r"\documentclass[sigplan,10pt,anonymous,balance=false]{acmart}"
        + "\n"
        + r"\setcopyright{none}\settopmatter{printacmref=false,printccs=false}"
        + "\n"
        + r"\acmConference[Figure proof]{AegisKV figure placement proof}{}{}\acmYear{2026}\copyrightyear{2026}\acmDOI{}\acmISBN{}"
        + "\n"
        + r"\renewcommand\footnotetextcopyrightpermission[1]{}"
        + "\n"
        + r"\usepackage{graphicx}\raggedbottom"
        + "\n"
        + r"\begin{document}\title{AegisKV: Figure Placement Proof}"
        + "\n"
        + r"\author{Anonymous}\affiliation{\institution{Anonymous}\country{Anonymous}}\maketitle\pagestyle{plain}"
        + "\n"
        + "Figures at the repository manuscript's actual column and text widths. This is a placement proof, not a complete manuscript or a statement of native-system validation.\n\\clearpage\n"
    )
    source = OUT / "paper-story-placement.tex"
    body = preamble + "\n".join(proof) + "\\end{document}\n"
    source.write_text(body)
    inputs = {
        "tex_sha256": sha(source),
        "class_sha256": sha(ROOT / "benchmark/AegisKV/paper/acmart.cls"),
        "figure_pdf_hashes": {row["name"]: sha(OUT / (row["name"] + ".pdf")) for row in figures},
    }
    input_file = OUT / "placement-inputs.json"
    unchanged = input_file.exists() and json.loads(input_file.read_text()) == inputs
    if not unchanged or not (OUT / "paper-story-placement.pdf").exists():
        env = dict(os.environ, SOURCE_DATE_EPOCH="1788825600", FORCE_SOURCE_DATE="1")
        with (ARTIFACTS / "placement-build.log").open("w") as log:
            for _ in range(2):
                subprocess.run(
                    [
                        "pdflatex",
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        f"-output-directory={OUT}",
                        str(source),
                    ],
                    cwd=ROOT / "benchmark/AegisKV/paper",
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                )
        input_file.write_text(json.dumps(inputs, indent=2) + "\n")


def build_review(figures):
    issues = {
        "P01": "单条分布线仍占三行图例空间；观测 gap 容易被当成因果 Slack",
        "P02": "容量余量线名称含混，单栏中长图例与曲线相邻",
        "P03": "架构内实现小字过多、恢复数据路径难追踪",
        "P04": "逻辑时间与实测时间没有视觉区分；头尾空白过大",
        "P05": "状态图重复留白；未强调各层独立连续前缀",
        "P06": "示意链路标签悬空；前缀就绪与解码恢复易混同",
        "P07": "CDF 顶部重复图例、最大上下文覆盖需限定",
        "P08": "离散调用数 CDF 被画得过高、最大 27 需保留",
        "P09": "ID 顺序锯齿掩盖 WCT 差异，通栏缩小后难读",
        "P10": "差值需要同一排序和清晰零基线，不能隐藏负值",
        "P11": "命中分母与请求命中比例不易区分",
        "P12": "GPU queue 与 GET/CPU/HBM 等待混淆风险",
        "P13": "更少 HBM 等待不能直接归因于 Peer；需要配对来源",
        "P14": "过高单栏图和外置三行图例，GPU 间差异不够清楚",
        "P15": "CPU 服务需求容易被误称实测 utilization",
        "P16": "流量与容量语义相近，需要实际字节的独立分解",
        "P17": "两条零线重合，需要说明且不能通过跨系统相减估计 Peer",
        "P18": "GET 样本数不同，原图缺乏可直接复用的总体说明",
        "P19": "少量敏感性点需要真实数值横轴与独立 marker",
        "P20": "闭环并发扫描不能写成开放负载吞吐",
        "P21": "容量跨度大，需要真实的对数坐标和两轮分母",
    }
    lines = [
        "# AegisKV 投稿图审查与修改记录",
        "",
        "[三部分论文叙述](Paper_Draft.md) · [旧图](Old_Figures.md)",
        "",
        "按用户本次纠正，36 图版整理为 33 张独立图：公式示意并入 DAG 实例，三个提交/恢复小图合为同一对象的完整生命周期。5 张设计图以对象、布局和状态变化重新绘制；6 组互补图在 Markdown 与 LaTeX 中并排。统计口径和实验输入保持原来源。设计图有原生 Draw.io 源，定量图有逐点 CSV，均有 PDF/SVG/PNG。",
        "",
        "[获奖论文实际图页与具体改法](../docs/paper/BEST_PAPER_FIGURE_REVIEW.md) · [改版前 36 图](../../../output/pdf/aegiskv-paper-story-20260908/before-best-paper-review/FIGURES.md)",
        "",
        "## 原 21 张逐图处理",
        "",
        "| 原编号 | 审查问题 | 修改后及验证重点 |",
        "|---|---|---|",
    ]
    for r in figures:
        for old_id in r["old_ids"]:
            fix = (
                "原生重构；检查箭头/状态/实际 PDF 文字"
                if r["evidence"] == "design"
                else "按实际宽度重绘；逐点 CSV 与输入核对，查看完整 PDF"
            )
            lines.append(
                f"| {old_id} | {issues[old_id]} | [{r['id']} {r['title']}](Paper_Draft.md#paper-{r['name']})；{fix} |"
            )
    lines += ["", "## 新增图填补了什么", "", "| 新图 | 补足的证据或解释 | 类型 |", "|---|---|---|"]
    for r in figures:
        if not r["old_id"]:
            lines.append(
                f"| [{r['id']} {r['title']}](Paper_Draft.md#paper-{r['name']}) | {r['caption_zh']} | {r['evidence']} |"
            )
    lines += [
        "",
        "## 参考论文与采取的具体改法",
        "",
        "本次核验并实际查看了四篇 Best Paper：Ensō（OSDI 2023）Figs. 1–3、10–12，Anvil（OSDI 2024）Fig. 5，Mooncake（FAST 2025）Figs. 2、9–14，CausalSim（NSDI 2023）Figs. 2、6–7。所用表达手法、PDF 页码和官方获奖来源见上述对照记录。参考的是对象关系、状态反例与相邻证据图的组织，没有复制原图、数据或其专属视觉元素。",
        "",
        "仓库 acmart 模板实编译得到 textwidth=505.89 TeX pt、columnwidth=240.94499 TeX pt；以 7 / 3.33 inch 导出。曲线用颜色与线型共同编码；敏感性点再用不同 marker。所有 Workflow 共用基线 WCT 排序并公开原 ID 映射，不能分别排序三系统。TPOT 改用完整生存尾图，图例移至图外避免盖住稀少尾样本；图下注明请求均值这一统计单位。",
        "",
        "## 补实验与证据缺口",
        "",
        "[故障补跑协议](PAPER_FAILURE_PROTOCOL.md) 预先固定三个进度位置及 matched F0，共 12 次执行。source-v7 相对 v6 只有 runner 选点发生改变；三组 F0 的全部 160 个 WCT 与 v6 一致。原故障实验过晚的问题由新增早、中、后三组受控位置补充，仍不构成多 workload 或原生故障统计。",
        "",
        "原生三系统干扰、完整 Algorithm 3 QoS 证书、预测器/Slack 消融、故障泛化四类缺图的条件已逐一写在 Evaluation 末尾；没有用模拟假设、零值消融或旧 SlackLandlord/AIMD 图冒充这些结果。",
        "",
        "## 复现与核对",
        "",
        "```bash",
        ".venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_paper_story.py",
        ".venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_paper_story_diagrams.py",
        ".venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_paper_story_failures.py",
        ".venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_paper_story_index.py",
        ".venv/bin/python benchmark/AegisKV/experiments/scripts/paper/audit_paper_story.py",
        "```",
        "",
        link(SELECTION, "逐图选择与英文图注")
        + " · "
        + link(OUT / "statistics-manifest.json", "定量图来源")
        + " · "
        + link(OUT / "diagrams-manifest.json", "设计图来源")
        + " · "
        + link(OUT / "failure-manifest.json", "故障补跑图来源")
        + " · "
        + link(ARTIFACTS / "DELIVERY_AUDIT.json", "数据与文档核对")
        + " · "
        + link(ARTIFACTS / "VISUAL_REVIEW.json", "实际 PDF 视觉检查")
        + "。",
    ]
    (DIRECTORY / "PAPER_FIGURE_REVIEW.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
