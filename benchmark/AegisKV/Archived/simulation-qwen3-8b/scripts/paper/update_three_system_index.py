"""Update the new-figure section without discarding historical provenance."""

import argparse
import json
import os
import re
from pathlib import Path

from paper_paths import DATA
from three_system_data import LABELS, SYSTEMS
from three_system_review_notes import key_findings, observation

START = "<!-- THREE_SYSTEM_REVIEW_START -->"
END = "<!-- THREE_SYSTEM_REVIEW_END -->"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--figures", type=Path, required=True)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[5]
    index = root / "benchmark/AegisKV/experiments/FIGURES.md"
    archive = index.with_name("Old_Figures.md")
    if archive.exists():
        index = archive
    directory = index.parent

    def link(path, label):
        return f"[{label}]({os.path.relpath(Path(path).resolve(), directory)})"

    input_link = link(DATA / "publication-figure-inputs.json", "冻结输入与统计数组")
    trace_link = link(
        directory / "workloads/fanoutqa-dev-qwen3-8b-160.jsonl", "原始精确 token trace"
    )
    example_link = link(
        DATA / "motivation-real-cc/real-cc-example-failure-position.csv", "五分支重建与反事实 CSV"
    )
    support_notes = {
        "workload-prompt_tokens": (
            "展示 1,304 个原始请求的 prompt 长度 CDF，横轴 Ki=1,024 tokens。"
            "用于交代输入规模；不混入本轮人为追加的第二轮重访。来源："
            + input_link + " / " + trace_link + "。"
        ),
        "workload-workflow_call_counts": (
            "展示 160 个原始 workflow 的调用数分布，横轴包含实际最大值 27。"
            "样本单位是 workflow；受控两轮负载的调用数不用于这张原始分布图。来源："
            + input_link + " / " + trace_link + "。"
        ),
        "workload-context-bins": (
            "按 prompt 加预定输出的总上下文计数，桶边界为 0/8/16/32/64/96/128 Ki。"
            "96–128 Ki 桶为零，保留空桶以显示实际覆盖范围，不能宣称本输入覆盖 128K。来源："
            + input_link + " / " + trace_link + "。"
        ),
        "motivation-branch-gap": (
            "124 个满足观测重叠条件的真实工作流，每个样本取并行分支持续时间的最大差，"
            "横轴使用对数刻度。它说明分支持续时间不均衡，不等于经过因果 DAG 验证的可用 CPM Slack。来源："
            + link(DATA / "motivation-real-cc/real-cc-workflow-parallel-gap.csv", "观测 gap CSV")
            + " / " + link(DATA / "motivation-real-cc/RAW_RECONSTRUCTION.json", "原始重建审计") + "。"
        ),
        "motivation-failure-position": (
            "同一个五分支工作流的历史 Qwen3-235B-A22B/A100-80GB/TP8/PP4/EP8 反事实。"
            "暴露给 workflow 的恢复时间为 max(recompute−slack, 0)，其余为被 Slack 吸收的部分。"
            "五个分支不是五次故障实测，不与新 Qwen3-8B 结果合并。来源：" + example_link + "。"
        ),
        "motivation-kv-capacity": (
            "按 Qwen3-8B BF16 的 147,456 B/token 解析计算一份/两份 KV；"
            "96 Ki tokens 分别占 13.5/27 GiB。参考线从 40 GiB 扣除 16,381,470,720 B 权重"
            "及 2 GiB runtime，只是资源包络，未扣动态前台 KV；不是可直接借用的 Peer 配额。配置见 "
            + link(directory / "THREE_SYSTEM_PROTOCOL.md", "三系统协议") + "。"
        ),
        "motivation-physical-paths": (
            "历史 2×RTX4090、Qwen3-8B、DP2/TP1/PP1 小规模物理样本；HBM write/DRAM write/"
            "HBM load/DRAM load 分别有 2/4/1/1 个样本。空心圆为逐样本字节数/时间，"
            "菱形为总字节数/总时间，均用十进制 GB/s。Peer 路径经 host staging，"
            "不能当作 CUDA P2P 或本轮 25 GB/s 模型的硬件标定。来源："
            + link(DATA / "physical-pilot/pilot-cost-profile.json", "物理样本与导入来源") + "。"
        ),
        "motivation-workflow": (
            "重建一个观测五分支的执行区间，以最晚分支结束推断 join；"
            "红色故障线是 349.5 s 的反事实参考位置，绿色段是相对该 join 的剩余 Slack。"
            "横轴沿用 trace 时间，未声称该时刻真的发生过故障。来源：" + example_link + "。"
        ),
        "system-overview": (
            "表达 revision-3 的设计职责及 KV/控制路径：Source 分别写入 Peer 与 DRAM，"
            "故障后备份需装入独立 primary。实线为数据，虚线为控制。图中的 GBDT、完整 QoS "
            "认证及原生服务组件不代表本轮均已执行；实现范围见 "
            + link(directory / "THREE_SYSTEM_PROTOCOL.md", "协议的能力边界") + "。"
        ),
        "commit-tier-timeline": (
            "示例中同一 chunk 已获得 HBM copy ACK，而 DRAM 写入在源故障时仍 pending，"
            "因此两个 tier 的最终状态不同。横轴只有事件先后，长度不表示实测传输时延；"
            "这是提交语义示意，不是一次性能运行。"
        ),
        "commit-recoverable-prefix": (
            "承接提交语义示例，HBM 的 chunk 0–1 committed，DRAM 只有 chunk 0 committed；"
            "aborted/absent 不提供恢复 token。两个 tier 分别计算连续可恢复前缀，"
            "不能把未完成复制或离散对象拼成有效前缀。图中三个 chunk 是示意对象。"
        ),
        "commit-materialize-recompute": (
            "承接前缀示例，先将 committed chunks 0–1 复制到新 primary，"
            "再重算未保护 suffix 2。图示区分前缀装入完成与恢复解码，"
            "不把 Peer 对象直接视作 primary KV；箭头长度无时间或字节比例。"
        ),
    }

    figures = []
    for manifest in args.figures.glob("*-figure-manifest.json"):
        for record in json.loads(manifest.read_text()):
            record["manifest"] = manifest
            figures.append(record)
    names = [r["name"] for r in figures]
    assert len(names) == len(set(names)), "duplicate named figures"
    cases = {}
    for case_path in args.data.iterdir():
        if not case_path.is_dir():
            continue
        systems = {}
        for s in SYSTEMS:
            file = case_path / f"{s}.json"
            if file.exists():
                systems[s] = json.loads(file.read_text())
        if systems:
            cases[case_path.name] = systems
    if args.complete:
        assert args.campaign is not None
        status = json.loads((args.campaign / "STATUS.json").read_text())
        assert not status["active"] and not status["pending"] and not status["failed"]
        assert len(status["completed"]) == sum(len(s) for s in cases.values())
    lines = [
        START,
        '<a id="three-system-review"></a>',
        "## 本轮更新：三系统逐 Workflow 对比（2026-09-08）",
        "",
        (
            "本轮实验、逐图审查与独立导出已完成。"
            if args.complete
            else "本轮仍在执行与验证。下面只展示已经完成、通过数据审计的图；后续压力/故障/敏感性数据验证后继续补入。"
        ),
        "",
        f"当前本轮有 **{len(figures)} 张独立图**，分别提供 PNG/SVG/PDF；其中机制图另有可编辑 Draw.io。图像由 LaTeX 自行组合，无需裁切合图。",
        "",
        "**图例固定为 Mooncake、DRAM-only AegisKV、AegisKV。** DRAM-only 是禁用 Peer HBM 的 AegisKV 消融，Mooncake 使用单独的 LRU Store 模拟基线。每个 workflow 图的横轴按 workflow ID 升序；三条线的同一索引对应同一 workflow，差值图中的 Mooncake 为零线。",
        "",
        "**证据范围：本轮为新的机制模拟实验，仍不是原生 serving 性能或完整 Algorithm 3 的 QoS 认证结果。** AegisKV 的 Peer 主配置为受内存包络约束的资源探索；严格控制器在无证书时给出零配额。CPU 图实测 Python 参考准入线程时间，CPU 队列使用显式服务模型；未建模推理 kernel 与 DMA 的硬件 HBM 带宽竞争。旧论文图的版本与原始数据保留在后面的历史审查中。",
        "",
        link(
            directory / "THREE_SYSTEM_PROTOCOL.md", "三系统定义、配置、指标公式、实现修复及证据边界"
        )
        + " · "
        + link(root / "python/moonkvsim/aegiskv/mechanism_experiment.py", "新实验适配器")
        + " · "
        + link(directory / "scripts/run_three_system_mechanisms.py", "实验入口")
        + " · "
        + link(directory / "scripts/paper/three_system_data.py", "原始数据审计/CSV 提取")
        + " · "
        + link(directory / "scripts/paper/render_three_system_figures.py", "独立图生成器"),
        "",
        "基础配置：Qwen3-8B，DP=8/TP=PP=1，8×40 GiB GPU 模型，DRAM=10¹² B，共享路径 25 GB/s，chunk=4,096 tokens，C=16，seed=0。160 个原始 workflows 含 1,304 requests；受控 exact-input revisits 是同一 DAG 的两轮访问，含 2,608 requests，明确标记为 synthetic。每配置/系统一次执行，图中的 workflow 点不作为独立运行重复或置信区间样本。",
        "",
        "| 原论文图 | 本轮审查与更新入口 |",
        "|---|---|",
    ]
    mapping = [
        (
            "G01-01 / 11 / 12 / 13",
            "supporting",
            "观测分支差、具体工作流、旧模型反事实分别导出，分别交代观测/重建/反事实背景",
        ),
        ("G01-02", "supporting", "解析 KV 容量与 RTX4090 小规模传输样本分开"),
        (
            "G01-03 / 04",
            "diagrams",
            "架构图复查；提交时序、故障前缀、materialize/recompute 拆为三张独立图",
        ),
        ("G01-05", "supporting", "prompt、workflow calls、context bins 分开，保留 128K 零样本"),
        (
            "G01-06",
            "f0-revisit",
            "三系统逐 workflow WCT、差值、cache hit rate、排队/HBM/CPU/带宽；原始 trace 对照另列",
        ),
        (
            "G01-07 / 08",
            "f1-natural",
            "三系统故障 WCT、相对自身 F0 的罚时、同一逻辑请求的恢复来源与时序",
        ),
        (
            "G01-09 / 10",
            "cross-case",
            "当前机制消融与单因素敏感性，保留不利或零效果，不沿用旧算法的 run 散点",
        ),
    ]
    for label, group, description in mapping:
        lines.append(f"| {label} | [{description}](#three-system-{group}) |")
    if args.campaign and (args.campaign / "PROTOCOL.json").exists():
        lines += [
            "",
            link(args.campaign / "PROTOCOL.json", "冻结矩阵协议")
            + " · "
            + link(args.campaign / "STATUS.json", "执行状态"),
            "",
        ]
        if args.complete:
            lines += [
                link(args.campaign / "DELIVERY_AUDIT.json", "原始数据/统一源码/图像/链接总审计")
                + " · "
                + link(args.campaign / "VISUAL_REVIEW.json", "逐图视觉审查记录"),
                "",
            ]
    lines += key_findings(cases)
    lines += [
        "",
        "### 已完成数据与配置",
        "",
        "Mean/P95 WCT 以 workflow 为单位，P95 GPU queue 以 request 为单位；DRAM hit 为 token 贡献比例。图与 CSV 保留全部工作流，不从每个系统分别排序取点。",
        "",
        "| 配置 | 系统 | Mean WCT (s) | P95 WCT (s) | DRAM hit (%) | P95 GPU queue (s) | 来源 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for case, systems in sorted(cases.items()):
        for s, data in systems.items():
            stats = data["summary"]
            queue_text = (
                f"{stats['p95_scheduler_queue_s']:.4f}" if "p95_scheduler_queue_s" in stats else "—"
            )
            lines.append(
                f"| `{case}` | {LABELS[s]} | {stats['mean_wct_s']:.4f} | {stats['p95_wct_s']:.4f} | {stats['dram_hit_pct']:.3f} | {queue_text} | "
                + link(args.data / case / f"{s}-workflows.csv", "Workflow CSV")
                + " / "
                + link(args.data / case / f"{s}.json", "审计/配置")
                + " |"
            )
    lines += [
        "",
        "原始单次访问 trace 中，短公共前缀可使请求命中比例很高，但 token 覆盖率很低；DRAM 正常复用为零的配置不绘制空 GET 延迟分布。受控 revisits 用于检验准入与缓存容量对长前缀正常复用的影响，不能当作真实用户复用分布。FREE HBM 很低也可能只是可回收缓存占用，需同时看 HBM 等待、抢占与纯 GPU 排队图。",
        "",
    ]
    groups = {}
    for r in figures:
        group = r.get("case") or (
            "diagrams" if r.get("type") == "editable_native_drawio" else "supporting"
        )
        if "," in group or r["name"].startswith(("sensitivity-", "ablation-")):
            group = "cross-case"
        groups.setdefault(group, []).append(r)
    order = [
        "supporting",
        "diagrams",
        "f0-natural",
        "f0-revisit",
        "f1-natural",
        "f2-natural",
        "cross-case",
    ]
    all_groups = order + sorted(set(groups) - set(order))
    # Keep pending navigation valid while the campaign is still being audited.
    for group in all_groups:
        records = groups.get(group, [])
        lines += [f'<a id="three-system-{group}"></a>', f"### {group}", ""]
        if not records:
            lines += ["该组尚未通过完整实验与图像审查，暂不展示结果。", ""]
            continue
        if group in cases:
            m = next(iter(cases[group].values()))["manifest"]
            w, params = m["workload"], m["parameters"]
            lines += [
                f"配置：{w['workflows']} workflows / {w['requests']} requests；C={w['concurrency']}；revisit rounds={w['revisit_rounds']}；DRAM={params['store_budget_bytes'] / 1024**3:.3f} GiB；链路={params['peer_bandwidth_bytes_per_second'] / 1e9:g} GB/s。源码 snapshot SHA-256：`{m['source_snapshot_sha256']}`。",
                "",
            ]
        if group in {"supporting", "diagrams"}:
            lines += [
                "背景、原始数据与配置见上方逐图审查表及协议文档。此组属于观测、解析或机制图，无需强加三条系统性能曲线。",
                "",
            ]
        lines += [
            "<details open>" if group in {"f0-natural", "f0-revisit"} else "<details>",
            f"<summary>展开 {len(records)} 张独立图及绘制说明</summary>",
            "",
        ]
        for r in sorted(records, key=lambda r: r["name"]):
            name = r["name"]
            description = (
                r.get("description")
                or {
                    "system-overview": "架构与路径；实线 KV 数据、虚线控制。图表达设计，GBDT/QoS 证书等不是本轮已完成性能证据。",
                    "motivation-workflow": "单个真实 trace 工作流的五分支重建；包含推断 join 与故障参考位置，非故障实测。",
                    "commit-tier-timeline": "同一 chunk 的独立 tier 提交顺序；横轴无实测时间比例。",
                    "commit-recoverable-prefix": "逻辑故障时 committed/aborted/absent 的区别，pending 不取得恢复收益。",
                    "commit-materialize-recompute": "备份先复制到独立 primary，再重算未保护 suffix；机制示意。",
                }[name]
            )
            lines += [f"**{name}** — {description}", ""]
            note = observation(r, cases) or support_notes.get(name)
            if note:
                lines += ["审查记录：" + note, ""]
            paths = [
                link(args.figures / f"{name}.{ext}", ext.upper()) for ext in ("png", "svg", "pdf")
            ]
            if (args.figures / f"{name}.drawio").exists():
                paths.append(link(args.figures / f"{name}.drawio", "Draw.io"))
            if (args.figures / f"{name}.csv").exists():
                paths.append(link(args.figures / f"{name}.csv", "曲线 CSV"))
            paths.append(link(r["manifest"], "图像清单"))
            lines += [
                " · ".join(paths),
                "",
                f"![{name}]({os.path.relpath((args.figures / (name + '.png')).resolve(), directory)})",
                "",
            ]
        lines += ["</details>", ""]
    lines += [END, ""]
    section = "\n".join(lines)
    text = index.read_text()
    if START in text:
        text = re.sub(
            re.escape(START) + r".*?" + re.escape(END), lambda _: section.rstrip(), text, flags=re.S
        )
    else:
        text = text.replace("## 导航\n", section + "\n## 导航\n", 1)
        text = text.replace(
            "# AegisKV 实验图像总索引\n",
            "# AegisKV 实验图像总索引\n\n最新工作见[本轮三系统逐 Workflow 更新](#three-system-review)。后面的当前论文章节保留重绘前版本，用于来源追溯。\n",
            1,
        )
    index.write_text(text)
    print(f"Updated {index} with {len(figures)} standalone figures")
    if archive.exists():
        from curate_three_system_index import curate

        curate()


if __name__ == "__main__":
    main()
