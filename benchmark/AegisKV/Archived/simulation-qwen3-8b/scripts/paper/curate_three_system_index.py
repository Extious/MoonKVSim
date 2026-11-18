"""Keep the paper selection short and retain every other figure in the archive."""

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

START = "<!-- THREE_SYSTEM_REVIEW_START -->"
END = "<!-- THREE_SYSTEM_REVIEW_END -->"
ROOT = Path(__file__).resolve().parents[5]
DIRECTORY = ROOT / "benchmark/AegisKV/experiments"
SELECTION = DIRECTORY / "results/paper/data/three-system-paper-selection.json"
ENTRY = re.compile(
    r"^\*\*([^*\n]+)\*\* — .*?(?=^\*\*[^*\n]+\*\* — |^</details>)", re.M | re.S
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def link(path, label):
    return f"[{label}]({os.path.relpath(path.resolve(), DIRECTORY)})"


def curate(selection_file=SELECTION):
    # The narrative edition owns Paper_Draft.md once installed. Legacy
    # catalog refreshes must not restore the former 21-entry catalog over it.
    if (DIRECTORY / "results/paper/data/paper-story-selection.json").exists():
        from build_paper_story_index import build
        return build()
    selection = json.loads(selection_file.read_text())
    campaign = ROOT / selection["campaign"]
    figures = ROOT / selection["figures_directory"]
    data = ROOT / selection["data"]
    audit = json.loads((campaign / "DELIVERY_AUDIT.json").read_text())
    records = {}
    for manifest in sorted(figures.glob("*-figure-manifest.json")):
        for record in json.loads(manifest.read_text()):
            assert record["name"] not in records
            records[record["name"]] = {**record, "manifest": manifest}
    chosen = {r["name"]: r for r in selection["figures"]}
    assert len(chosen) == len(selection["figures"])
    assert chosen.keys() <= records.keys()
    # A document edit does not change the already-reviewed image exports.
    for name in records:
        for ext in ("png", "pdf", "svg"):
            assert sha(figures / f"{name}.{ext}") == audit["figures_by_name"][name]["files"][ext]

    hub = DIRECTORY / "FIGURES.md"
    archive = DIRECTORY / "Old_Figures.md"
    paper = DIRECTORY / "Paper_Draft.md"
    source = archive if archive.exists() else hub
    original = source.read_text()
    before = campaign / "FIGURES-before-split.txt"
    if not before.exists():
        assert source == hub and sha(source) == audit["index_sha256"]
        before.write_bytes(source.read_bytes())
    assert START in original and END in original
    section_start = original.index(START)
    section_end = original.index(END) + len(END)
    section = original[section_start:section_end]
    history = original[section_end:]
    section = ENTRY.sub(lambda m: "" if m.group(1) in chosen else m.group(0), section)
    remaining = {m.group(1) for m in ENTRY.finditer(section)}
    assert remaining == records.keys() - chosen.keys(), "archive lost or duplicated an entry"
    section = section.replace(
        "## 本轮更新：三系统逐 Workflow 对比（2026-09-08）",
        "## 三系统未入选图与完整配置（2026-09-08）",
    )
    section = re.sub(
        r"^(?:当前本轮有|本节展示) .*?$",
        f"本节展示 **{len(remaining)} 张未入选图**；{len(chosen)} 张论文用图见 "
        "[Paper_Draft.md](Paper_Draft.md)。下方保留完整配置、负面与零结果及逐图审查记录。",
        section,
        flags=re.M,
    )
    mapping = {
        "G01-01 / 11 / 12 / 13": "[论文 P01：观测动机](Paper_Draft.md#paper-motivation-branch-gap)；[归档：单例重建与反事实](#three-system-supporting)",
        "G01-02": "[论文 P02：解析 KV 容量](Paper_Draft.md#paper-motivation-kv-capacity)；[归档：物理 pilot](#three-system-supporting)",
        "G01-03 / 04": "[论文 P03：架构](Paper_Draft.md#paper-system-overview)；[P04–P06：提交与恢复示意](Paper_Draft.md#paper-commit-tier-timeline)",
        "G01-05": "[论文 P07–P08：工作负载](Paper_Draft.md#paper-workload-prompt_tokens)；[归档：上下文分桶](#three-system-supporting)",
        "G01-06": "[论文 P09–P18：三系统机制分析](Paper_Draft.md#paper-f0-revisit-wct)；[其余诊断](#three-system-f0-revisit)",
        "G01-09 / 10": "[论文 P19–P21：必要敏感性](Paper_Draft.md#paper-sensitivity-bandwidth-mean_wct_s)；[归档：完整扫描与零值消融](#three-system-cross-case)",
    }
    for old_id, destination in mapping.items():
        section = re.sub(
            r"^\| " + re.escape(old_id) + r" \|.*$",
            f"| {old_id} | {destination} |",
            section,
            flags=re.M,
        )

    def count_details(match):
        body = match.group(1)
        count = len(list(ENTRY.finditer(body + "</details>")))
        if not count:
            return (
                "<details>\n<summary>本组图已移入论文版</summary>\n\n"
                "见 [Paper_Draft.md](Paper_Draft.md)。\n\n</details>"
            )
        return (
            f"<details>\n<summary>展开 {count} 张未入选图及原审查记录</summary>\n"
            + body + "</details>"
        )

    section = re.sub(
        r"<details(?: open)?>\n<summary>.*?</summary>\n(.*?)</details>",
        count_details,
        section,
        flags=re.S,
    )
    reasons = Counter()
    for name in sorted(remaining):
        reason = next(r["reason"] for r in selection["archive_rules"] if re.search(r["pattern"], name))
        reasons[reason] += 1
    old_lines = [
        "# AegisKV 旧图与诊断归档",
        "",
        "[论文用图](Paper_Draft.md) · [总导航](FIGURES.md)",
        "",
        f"这里保留本轮未选入正文的 **{len(remaining)} 张独立图**，以及拆分前的历史版本、"
        "格式副本和原始审查记录。图片与原始数据保留原位置。归档不表示数据错误；"
        "入选依据是证据与论文论点是否匹配、是否有独立信息增量，而非结果是否有利于 AegisKV。",
        "",
        "## 本轮未入选原因",
        "",
        "| 图数 | 原因 |",
        "|---:|---|",
        *[f"| {count} | {reason} |" for reason, count in reasons.items()],
        "",
        link(selection_file, "逐图入选名单与归档规则") + " · "
        + link(before, "拆分前索引原文（保留原审计哈希）"),
        "",
        section,
        history,
    ]
    archive.write_text("\n".join(old_lines).rstrip() + "\n")

    labels = {
        "trace_observation": "真实 trace 观测",
        "analytical": "解析推导",
        "design": "设计示意",
        "workload_description": "输入统计",
        "modeled_exploration": "机制模拟",
    }
    lines = [
        "# AegisKV 论文用图",
        "",
        "[旧图与诊断归档](Old_Figures.md) · [总导航](FIGURES.md)",
        "",
        f"保留 **{len(chosen)} 张独立图**，按论文论点排序。每张提供可使用的图注、来源与 PDF。"
        "这是独立素材数，可在 LaTeX 中组合，不要求正文设置同样多的图号。",
        "",
        "**使用范围：** 观测、解析、设计与机制模拟分别标注。后面的三系统结果可用于明确声明模型"
        "假设的机制分析；不能作为原生 Mooncake/AegisKV 实测性能或完整 Algorithm 3 QoS 认证。"
        "不利结果保留，未把“能导出”或“审计 PASS”视为系统性能论证已经充分。",
        "",
        "## 共同实验配置",
        "",
        "模拟图比较 Mooncake（独立 LRU Store 模型）、DRAM-only AegisKV（PrefixAdmission、"
        "禁用 Peer）和 AegisKV（相同 DRAM 策略、启用受容量包络约束的 Peer 资源探索）。"
        "下文“依次”均按此顺序。Qwen3-8B BF16，DP8/TP1/PP1，8×40 GiB GPU，"
        "基础 C=16、DRAM=1 TB、共享路径 25 GB/s、chunk=4,096 tokens。",
        "",
        "无故障主对比使用 **160 个 Workflow、2,608 个请求的受控两轮重访**："
        "原始 DAG 完整执行两轮，精确输入相同，属于 synthetic 复用压力测试。"
        "每配置每系统执行一次，按同一 Workflow ID 配对；不是把运行编号当作横轴，"
        "也不把 Workflow 数作为独立重复数。本轮三系统模拟统一使用冻结 source-v6。",
        "",
        "CPU 图使用冻结服务报价；GPU 服务时序未用目标硬件标定，未建模 kernel 与 DMA 的硬件 "
        "HBM 带宽竞争。完整参数、分母及模型范围见 "
        + link(DIRECTORY / "THREE_SYSTEM_PROTOCOL.md", "实验协议") + "。",
        "",
        "原始一次访问对照的 DRAM 正常命中为零，三系统平均 WCT 约为 39.066 s；"
        "不能由此宣称准入没有影响。零 Slack 消融未改变 WCT，严格无证书配置关闭 Peer；"
        "这些零结果保留在文字与归档中，不用平坦重复图占据正文。",
        "",
        "宽度建议：Workflow 曲线及机制示意通栏 7.2 inch，CDF/小型比较单栏 3.5 inch。"
        "优先插入矢量 PDF；不要把通栏图直接缩成半栏。下列图注保留模拟/观测等证据类型。",
        "",
        "| 编号 | 图与用途 | 证据 |",
        "|---|---|---|",
    ]
    for i, item in enumerate(selection["figures"], 1):
        lines.append(
            f"| P{i:02d} | [{item['title']}](#paper-{item['name']}) | {labels[item['evidence']]} |"
        )
    lines.append("")
    previous_group = None
    for i, item in enumerate(selection["figures"], 1):
        name = item["name"]
        record = records[name]
        if item["section"] != previous_group:
            lines += ["## " + selection["sections"][item["section"]], ""]
            previous_group = item["section"]
        lines += [
            f'<a id="paper-{name}"></a>',
            f"### P{i:02d} {item['title']}",
            "",
            item["purpose"],
            "",
            "**图注：** " + item["caption"],
            "",
        ]
        paths = [link(figures / f"{name}.{ext}", ext.upper()) for ext in ("pdf", "svg", "png")]
        if (figures / f"{name}.drawio").exists():
            paths.append(link(figures / f"{name}.drawio", "Draw.io"))
        if "source" in item:
            paths.append(link(ROOT / item["source"], "数据/定义"))
        else:
            for case in record["case"].split(","):
                paths.append(link(data / case, "数据 " + case))
        if (figures / f"{name}.csv").exists():
            paths.append(link(figures / f"{name}.csv", "曲线 CSV"))
        paths.append(link(record["manifest"], "来源清单"))
        lines += [" · ".join(paths), "", f"![{item['title']}]({os.path.relpath(figures / (name + '.png'), DIRECTORY)})", ""]
    lines += [
        "来源及审查：" + link(selection_file, "筛选记录") + " · "
        + link(campaign / "DELIVERY_AUDIT.json", "数据与文件审计") + " · "
        + link(campaign / "VISUAL_REVIEW.json", "导出视觉检查") + "。",
        "",
    ]
    paper.write_text("\n".join(lines))
    hub.write_text(
        "# AegisKV 图像导航\n\n"
        "图像索引已按论文用途拆分：\n\n"
        f"- [Paper_Draft.md](Paper_Draft.md)：{len(chosen)} 张精选独立图，附用途、可用图注、数据来源和矢量文件。\n"
        f"- [Old_Figures.md](Old_Figures.md)：本轮其余 {len(remaining)} 张诊断图，以及历史版本、未入选原因和完整审查记录。\n\n"
        "实验口径见 [THREE_SYSTEM_PROTOCOL.md](THREE_SYSTEM_PROTOCOL.md)。\n"
    )
    result = {
        "paper_figures": len(chosen),
        "archived_current_figures": len(remaining),
        "previous_index_sha256": sha(before),
        "selection_sha256": sha(selection_file),
    }
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=SELECTION)
    curate(parser.parse_args().selection)
