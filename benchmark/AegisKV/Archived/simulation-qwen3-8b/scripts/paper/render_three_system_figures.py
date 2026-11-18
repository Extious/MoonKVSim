"""Standalone scientific figures. Workflow indices always map to the same IDs."""

from __future__ import annotations

import argparse
import csv
import json
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from figure_style import save
from matplotlib.lines import Line2D
from paper_paths import DATA
from three_system_data import LABELS, SYSTEMS, load_case, sha, write_csv
from three_system_review_notes import controller_service

COLORS = {"mooncake": "#59636F", "dram": "#B86B00", "aegis": "#0072B2"}
STYLES = {"mooncake": "-", "dram": "--", "aegis": "-."}
RECORDS = []


def canvas(xlabel, ylabel, *, wide=False):
    fig, ax = plt.subplots(figsize=(7.2 if wide else 3.5, 3.6))
    fig.subplots_adjust(
        left=0.14 if wide else 0.28,
        right=0.96 if wide else 0.92,
        bottom=0.22,
        top=0.83 if wide else 0.73,
    )
    if not wide:
        xlabel = textwrap.fill(xlabel, width=30, break_long_words=False, break_on_hyphens=False)
    ylabel = textwrap.fill(ylabel, width=36, break_long_words=False, break_on_hyphens=False)
    ax.set(xlabel=xlabel, ylabel=ylabel)
    ax.yaxis.set_label_coords(0.40 / fig.get_size_inches()[0], 0.5, transform=fig.transFigure)
    ax.ticklabel_format(axis="y", style="sci", scilimits=(-2, 3), useOffset=False)
    ax.grid(alpha=0.17)
    return fig, ax


def legend(ax):
    small = ax.figure.get_size_inches()[0] < 5
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 0.99),
        bbox_transform=ax.figure.transFigure,
        ncol=2 if len(ax.get_legend_handles_labels()[1]) > 3 else (1 if small else 3),
        frameon=False,
        borderaxespad=0,
        columnspacing=1.2,
        handlelength=1.8 if small else 2.8,
    )


def finish(fig, ax, name, out, description, case=None, *, custom_legend=False):
    series = [np.asarray(item.get_ydata(), dtype=float) for item in ax.lines]
    finite = np.concatenate([a[np.isfinite(a)] for a in series]) if series else np.array([])
    if not len(finite) and ax.patches:
        finite = np.asarray([p.get_height() for p in ax.patches if hasattr(p, "get_height")])
    if len(finite) and np.all(finite == 0) and ax.get_yscale() == "linear":
        signed = any(word in ax.get_ylabel().lower() for word in ("difference", "change", "penalty"))
        ax.set_ylim((-1, 1) if signed else (0, 1))
    if ax.get_xlabel().startswith("Workflow index"):
        xs = [np.asarray(item.get_xdata(), dtype=float) for item in ax.lines]
        ax.set_xlim(min(a.min() for a in xs if len(a)), max(a.max() for a in xs if len(a)))
    if not custom_legend:
        legend(ax)
    save(fig, name, directory=out)
    RECORDS.append(
        {
            "name": name,
            "description": description,
            "case": case,
            "png_sha256": sha(out / f"{name}.png"),
            "pdf_sha256": sha(out / f"{name}.pdf"),
            "svg_sha256": sha(out / f"{name}.svg"),
        }
    )
    table = out / f"{name}.csv"
    if table.exists():
        RECORDS[-1]["csv_sha256"] = sha(table)


def line(ax, s, x, y, **kwargs):
    ax.plot(x, y, color=COLORS[s], ls=STYLES[s], lw=1.35, label=LABELS[s], **kwargs)


def window_centers(data, count):
    width = data["window_ns"] / 1e9
    result = (np.arange(count) + 0.5) * width
    result[-1] = ((count - 1) * width + data["summary"]["workload_end_s"]) / 2
    return result


def ecdf(ax, s, values):
    x = np.sort([v for v in values if v is not None])
    if len(x):
        ax.step(
            x,
            np.arange(1, len(x) + 1) / len(x),
            where="post",
            color=COLORS[s],
            ls=STYLES[s],
            lw=1.65,
            label=LABELS[s],
        )
    else:
        ax.plot([], [], color=COLORS[s], ls=STYLES[s], label=LABELS[s] + " (no samples)")
    ax.set_ylim(0, 1.02)


def case_figures(case, data, out, baseline=None):
    base = data["mooncake"]["workflows"]
    x = np.arange(1, len(base) + 1)
    services = controller_service(data)
    for difference in (False, True):
        name = f"{case}-controller-service" + ("-difference" if difference else "")
        ylabel = (
            "Controller service difference from Mooncake (ms)"
            if difference
            else "Modeled controller service time (ms)"
        )
        values = (
            {
                s: [a - b for a, b in zip(v, services["mooncake"], strict=True)]
                for s, v in services.items()
            }
            if difference
            else services
        )
        fig, ax = canvas("Workflow index (fixed ID order)", ylabel, wide=True)
        for s in SYSTEMS:
            line(ax, s, x, values[s])
        ax.set_xlim(1, len(x))
        write_csv(
            out / f"{name}.csv",
            [
                {
                    "index": i + 1,
                    "workflow_id": r["workflow_id"],
                    **{s + "_ms": values[s][i] for s in SYSTEMS},
                }
                for i, r in enumerate(base)
            ],
        )
        finish(
            fig,
            ax,
            name,
            out,
            "逐 workflow 冻结 CPU 模型服务量（查询＋准入），用于可重复的控制面代价比较",
            case,
        )
    for key, ylabel, suffix, desc in (
        ("wct_s", "Workflow completion time (s)", "wct", "逐 workflow 的 WCT"),
        (
            "mean_scheduler_queue_s",
            "Mean GPU scheduler queue delay (s)",
            "scheduler-queue",
            "逐 workflow 的纯 GPU 调度等待，起点为 KV 就绪后的调度准入",
        ),
        (
            "mean_foreground_hbm_wait_s",
            "Mean foreground HBM wait (s)",
            "hbm-wait",
            "逐 workflow 为 DRAM GET 目标申请 HBM 的等待时间",
        ),
        (
            "preemptions",
            "GPU scheduler preemptions",
            "preemptions",
            "逐 workflow 因 KV 压力发生的抢占次数",
        ),
        (
            "total_hit_pct",
            "Reused prompt tokens (%)",
            "cache-hit",
            "正常服务的 token 加权 KV 命中率",
        ),
        (
            "dram_hit_pct",
            "Prompt tokens served by DRAM (%)",
            "dram-hit",
            "DRAM 对正常 prompt 复用的贡献",
        ),
        (
            "request_hit_pct",
            "Requests with any cache hit (%)",
            "request-hit",
            "正常请求至少命中一个前缀的比例",
        ),
        (
            "mean_precompute_wait_s",
            "Mean precompute wait (s)",
            "wait",
            "逐 workflow 请求平均首次计算前等待，包含 GET 和 CPU 排队",
        ),
        (
            "reference_admission_cpu_ms",
            "Reference admission CPU time (ms)",
            "cpu",
            "逐 workflow Python 准入参考实现实测线程 CPU 时间",
        ),
        (
            "foreground_cpu_queue_ms",
            "Foreground CPU queue time (ms)",
            "cpu-queue",
            "逐 workflow 模型前台 CPU 排队时间总和",
        ),
        (
            "background_copy_gib",
            "Background copy traffic (GiB)",
            "background-copy",
            "逐 workflow 后台 DRAM/Peer 复制实际消耗字节，包含中止前已经传输的字节",
        ),
        (
            "foreground_copy_gib",
            "Foreground GET traffic (GiB)",
            "foreground-copy",
            "逐 workflow 正常 DRAM GET 实际传输字节",
        ),
        (
            "peer_copy_gib",
            "Peer backup copy traffic (GiB)",
            "peer-copy",
            "逐 workflow Peer HBM 后台复制实际字节；Mooncake/DRAM-only 没有这项流量",
        ),
        (
            "dram_copy_gib",
            "DRAM cache write traffic (GiB)",
            "dram-copy",
            "逐 workflow DRAM 写入实际字节，独立于 Peer 后台复制",
        ),
        (
            "foreground_get_p95_ms",
            "P95 foreground DRAM GET latency (ms)",
            "get-latency",
            "每个 workflow 内成功 GET 的 P95 延迟，无 GET 的位置留空",
        ),
        (
            "foreground_get_slowdown_p95",
            "P95 foreground GET slowdown (×)",
            "get-slowdown",
            "每个 workflow 内成功 GET 的 P95 数据服务减速比，无样本留空",
        ),
    ):
        if all(r[key] is None for s in SYSTEMS for r in data[s]["workflows"]):
            continue
        fig, ax = canvas("Workflow index (fixed ID order)", ylabel, wide=True)
        for s in SYSTEMS:
            assert [r["workflow_id"] for r in data[s]["workflows"]] == [
                r["workflow_id"] for r in base
            ]
            line(ax, s, x, [r[key] for r in data[s]["workflows"]])
        ax.set_xlim(1, len(x))
        if "pct" in key:
            maximum = max(r[key] for s in SYSTEMS for r in data[s]["workflows"])
            ax.set_ylim(0, min(100, max(1, maximum * 1.1)))
        finish(fig, ax, f"{case}-{suffix}", out, desc, case)
    for key, ylabel, suffix in (
        ("wct_s", "WCT difference from Mooncake (s)", "wct-difference"),
        ("total_hit_pct", "Cache-hit difference from Mooncake (pp)", "cache-hit-difference"),
        ("dram_hit_pct", "DRAM-hit difference from Mooncake (pp)", "dram-hit-difference"),
        (
            "mean_scheduler_queue_s",
            "GPU queue difference from Mooncake (s)",
            "scheduler-queue-difference",
        ),
        (
            "mean_foreground_hbm_wait_s",
            "HBM wait difference from Mooncake (s)",
            "hbm-wait-difference",
        ),
        (
            "reference_admission_cpu_ms",
            "Admission CPU difference from Mooncake (ms)",
            "cpu-difference",
        ),
        (
            "background_copy_gib",
            "Background copy difference from Mooncake (GiB)",
            "background-copy-difference",
        ),
    ):
        scale = 1
        if (
            key == "wct_s"
            and max(
                abs(r[key] - b[key])
                for s in SYSTEMS
                for r, b in zip(data[s]["workflows"], base, strict=True)
            )
            < 0.1
        ):
            scale = 1000
            ylabel = "WCT difference from Mooncake (ms)"
        fig, ax = canvas("Workflow index (fixed ID order)", ylabel, wide=True)
        for s in SYSTEMS:
            line(
                ax,
                s,
                x,
                [
                    scale * (r[key] - b[key])
                    for r, b in zip(data[s]["workflows"], base, strict=True)
                ],
            )
        ax.set_xlim(1, len(x))
        finish(fig, ax, f"{case}-{suffix}", out, ylabel, case)
    for key, unit, label in (
        ("foreground_hbm_wait_ns", 1e9, "Foreground HBM reservation wait (s)"),
        ("scheduler_queue_ns", 1e9, "GPU scheduler queue delay (s)"),
        ("precompute_wait_ns", 1e9, "Precompute wait (s)"),
        ("ttft_ns", 1e9, "Time to first token (s)"),
        ("request_tpot_ns", 1e6, "Per-request mean time per output token (ms)"),
    ):
        fig, ax = canvas(label, "Empirical CDF")
        for s in SYSTEMS:
            ecdf(ax, s, [r[key] / unit for r in data[s]["requests"] if r[key] is not None])
        if key == "request_tpot_ns":
            assert all(r[key] is None or r[key] > 0 for s in SYSTEMS for r in data[s]["requests"])
            ax.set_xscale("log")
        else:
            ax.set_xlim(left=0)
        if all(r[key] in (None, 0) for s in SYSTEMS for r in data[s]["requests"]):
            ax.set_xlim(0, 1)
        finish(fig, ax, f"{case}-{key.removesuffix('_ns')}-cdf", out, label + "；请求为样本", case)
    fig, ax = canvas("Reference admission CPU time (µs)", "Empirical CDF")
    for s in SYSTEMS:
        ecdf(ax, s, [r["cpu_ns"] / 1000 for r in data[s]["policy_cpu"]])
    ax.set_xscale("log")
    finish(fig, ax, f"{case}-cpu-cdf", out, "准入调用 CPU 时间分布，仅 Python 参考实现", case)
    for key, xlabel in (
        ("duration_ms", "Foreground DRAM GET latency (ms)"),
        ("service_slowdown", "Foreground GET service slowdown (×)"),
    ):
        if not any(data[s]["foreground_transfers"] for s in SYSTEMS):
            continue
        fig, ax = canvas(xlabel, "Empirical CDF")
        for s in SYSTEMS:
            ecdf(ax, s, [r[key] for r in data[s]["foreground_transfers"]])
        finish(fig, ax, f"{case}-transfer-{key}", out, xlabel, case)
    for metric, ylabel in (
        ("total_gbs", "Shared PCIe traffic (GB/s)"),
        ("foreground_gbs", "Foreground DRAM GET traffic (GB/s)"),
        ("protection_gbs", "Background transfer traffic (GB/s)"),
        ("peer_put_gbs", "Peer backup copy traffic (GB/s)"),
        ("dram_put_gbs", "DRAM cache write traffic (GB/s)"),
    ):
        fig, ax = canvas("Simulated time (s)", ylabel, wide=True)
        for s in SYSTEMS:
            values = data[s]["network"][metric]
            line(ax, s, window_centers(data[s], len(values)), values)
        ax.set_ylim(bottom=0)
        finish(fig, ax, f"{case}-{metric}", out, ylabel + "；1 s 时间窗", case)
    for gpu in data["mooncake"]["hbm"]:
        for metric, ylabel in (
            ("free_gib", "Free HBM (GiB)"),
            ("peer_gib", "Peer protection HBM (GiB)"),
        ):
            fig, ax = canvas("Simulated time (s)", ylabel, wide=True)
            for s in SYSTEMS:
                values = data[s]["hbm"][gpu][metric]
                line(ax, s, window_centers(data[s], len(values)), values)
            ax.set_ylim(bottom=0)
            finish(
                fig,
                ax,
                f"{case}-{gpu}-{metric}",
                out,
                gpu + " " + ylabel + "；按时间加权的 1 s 均值",
                case,
            )
    fig, ax = canvas("GPU index", "Time with free HBM below 1 GiB (%)")
    for s in SYSTEMS:
        line(
            ax,
            s,
            list(range(8)),
            [data[s]["hbm_pressure"][f"gpu-{i}"]["free_below_1gib_pct"] for i in range(8)],
            marker="o",
        )
    ax.set_xticks(range(8))
    ax.set_ylim(bottom=0)
    finish(fig, ax, f"{case}-hbm-pressure", out, "逐 GPU 精确积分的低空闲显存时间比例", case)
    if baseline is not None:
        fig, ax = canvas(
            "Workflow index (fixed ID order)", "Failure penalty: WCT(F1) − WCT(F0) (s)", wide=True
        )
        for s in SYSTEMS:
            line(
                ax,
                s,
                x,
                [
                    a["wct_s"] - b["wct_s"]
                    for a, b in zip(data[s]["workflows"], baseline[s]["workflows"], strict=True)
                ],
            )
        finish(
            fig,
            ax,
            f"{case}-failure-penalty",
            out,
            "各系统相对自身匹配 F0 的逐 workflow 故障罚时",
            case,
        )


def supporting_figures(out):
    inputs = json.loads((DATA / "publication-figure-inputs.json").read_text())
    for key, scale, xlabel, label in (
        ("prompt_tokens", 1024, "Prompt length (Ki tokens)", "Requests"),
        ("workflow_call_counts", 1, "Calls per workflow", "Workflows"),
    ):
        values = np.sort(np.asarray(inputs[key]) / scale)
        fig, ax = canvas(xlabel, "Empirical CDF")
        ax.step(
            values, np.arange(1, len(values) + 1) / len(values), where="post", lw=1.7, label=label
        )
        ax.set_ylim(0, 1.02)
        finish(fig, ax, f"workload-{key}", out, f"原始冻结 FanOutQA；{len(values)} 个 {label}")
    fig, ax = canvas("Context upper bound (Ki tokens)", "Number of requests")
    bins = np.array([0, 8, 16, 32, 64, 96, 128])
    counts = np.histogram(inputs["context_tokens"], bins=bins * 1024)[0]
    ax.bar(range(6), counts, color=COLORS["aegis"], label="Requests")
    ax.set_xticks(range(6), [str(i) for i in bins[1:]])
    finish(fig, ax, "workload-context-bins", out, "上下文分桶，96–128 Ki 桶保持零样本")
    fig, ax = canvas("Prompt length (Ki tokens)", "KV footprint (GiB)")
    x = np.linspace(0, 96, 193)
    one = x * 1024 * 147456 / 1024**3
    ax.plot(x, one, label="One KV copy", color=COLORS["aegis"])
    ax.plot(x, 2 * one, label="Two KV copies", color=COLORS["dram"], ls="--")
    ax.axhline(
        (40 * 1024**3 - 16381470720 - 2 * 1024**3) / 1024**3,
        color=COLORS["mooncake"],
        ls=":",
        label="Post-reserve HBM",
    )
    ax.set_xlim(0, 96)
    finish(
        fig, ax, "motivation-kv-capacity", out, "Qwen3-8B BF16 KV 的解析容量关系；不是系统性能测量"
    )
    profile = json.loads((DATA / "physical-pilot/pilot-cost-profile.json").read_text())
    fig, ax = canvas("Effective transfer rate (GB/s)", "")
    fig.subplots_adjust(left=0.33)
    for i, key in enumerate(("hbm_protection", "dram_protection", "hbm_recovery", "dram_recovery")):
        samples = np.asarray(profile["physical_samples"][key])
        rates = samples[:, 0] / samples[:, 1] / 1e6
        aggregate = samples[:, 0].sum() / samples[:, 1].sum() / 1e6
        ax.scatter(
            rates,
            i + np.linspace(-0.09, 0.09, len(rates)) if len(rates) > 1 else [i],
            facecolor="white",
            edgecolor=COLORS["aegis"],
            s=33,
        )
        ax.scatter([aggregate], [i], marker="D", color=COLORS["dram"], s=33)
    ax.set_yticks(range(4), ["HBM write", "DRAM write", "HBM load", "DRAM load"])
    ax.invert_yaxis()
    ax.legend(
        handles=[
            Line2D(
                [],
                [],
                marker="o",
                ls="",
                markerfacecolor="white",
                color=COLORS["aegis"],
                label="Sample",
            ),
            Line2D([], [], marker="D", ls="", color=COLORS["dram"], label="Aggregate rate"),
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, 0.99),
        bbox_transform=fig.transFigure,
        ncol=2,
        frameon=False,
    )
    finish(
        fig,
        ax,
        "motivation-physical-paths",
        out,
        "2×RTX4090 host-staged 小规模物理路径样本，与 A100 模拟配置分开",
        custom_legend=True,
    )
    directory = DATA / "motivation-real-cc"
    rows = list(csv.DictReader((directory / "real-cc-workflow-parallel-gap.csv").open()))
    values = np.sort([float(r["max_duration_gap_s"]) for r in rows])
    fig, ax = canvas("Maximum parallel-branch duration gap (s)", "Empirical CDF")
    ax.step(
        values,
        np.arange(1, len(values) + 1) / len(values),
        where="post",
        label="Observed workflows",
    )
    ax.set_xscale("log")
    ax.set_ylim(0, 1.02)
    finish(
        fig, ax, "motivation-branch-gap", out, "124 个有观测重叠分支的工作流；原始持续时间差分布"
    )
    rows = sorted(
        csv.DictReader((directory / "real-cc-example-failure-position.csv").open()),
        key=lambda r: int(r["branch_index"]),
    )
    recompute = np.array([float(r["recompute_s"]) for r in rows])
    slack = np.array([float(r["slack_s"]) for r in rows])
    exposed = np.array([float(r["delta_wct_s"]) for r in rows])
    assert np.allclose(exposed, np.maximum(recompute - slack, 0))
    fig, ax = canvas("Branch index", "Counterfactual recovery time (s)")
    indices = np.array([int(r["branch_index"]) for r in rows])
    ax.bar(indices, recompute - exposed, label="Absorbed by slack", color=COLORS["mooncake"])
    ax.bar(
        indices,
        exposed,
        bottom=recompute - exposed,
        label="Exposed to workflow",
        color=COLORS["dram"],
    )
    ax.set_xticks(indices)
    finish(
        fig, ax, "motivation-failure-position", out, "历史 235B 模型反事实；不是 Qwen3-8B 实测恢复"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--case")
    p.add_argument("--baseline", type=Path)
    p.add_argument("--supporting", action="store_true")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.supporting:
        supporting_figures(args.output)
    if args.data:
        case_figures(
            args.case,
            load_case(args.data),
            args.output,
            load_case(args.baseline) if args.baseline else None,
        )
    name = args.case or "supporting"
    (args.output / f"{name}-figure-manifest.json").write_text(
        json.dumps(RECORDS, indent=2, ensure_ascii=False) + "\n"
    )
    print(f"Exported {len(RECORDS)} standalone figures to {args.output}")


if __name__ == "__main__":
    main()
