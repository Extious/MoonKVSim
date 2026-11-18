"""Numerical, per-image review notes derived from the exact plotted records."""

import re
from collections import defaultdict

import numpy as np
from three_system_data import LABELS, SYSTEMS

WORKFLOW_METRICS = {
    "wct": ("wct_s", "s"),
    "wct_s": ("wct_s", "s"),
    "scheduler-queue": ("mean_scheduler_queue_s", "s"),
    "mean_scheduler_queue_s": ("mean_scheduler_queue_s", "s"),
    "hbm-wait": ("mean_foreground_hbm_wait_s", "s"),
    "preemptions": ("preemptions", "次"),
    "cache-hit": ("total_hit_pct", "%"),
    "dram-hit": ("dram_hit_pct", "%"),
    "dram_hit_pct": ("dram_hit_pct", "%"),
    "request-hit": ("request_hit_pct", "%"),
    "wait": ("mean_precompute_wait_s", "s"),
    "cpu": ("reference_admission_cpu_ms", "ms"),
    "cpu-queue": ("foreground_cpu_queue_ms", "ms"),
    "background-copy": ("background_copy_gib", "GiB"),
    "foreground-copy": ("foreground_copy_gib", "GiB"),
    "peer-copy": ("peer_copy_gib", "GiB"),
    "dram-copy": ("dram_copy_gib", "GiB"),
    "get-latency": ("foreground_get_p95_ms", "ms"),
    "get-slowdown": ("foreground_get_slowdown_p95", "×"),
}


def controller_service(data):
    """Quoted foreground lookup and admission work attributed to each DAG."""
    result = {}
    for system in SYSTEMS:
        spans = {r["span_id"]: r["workflow_id"] for r in data[system]["requests"]}
        totals = defaultdict(int)
        for row in data[system]["cpu_queue"]:
            totals[spans[row["span_id"]]] += row["service_ns"]
        result[system] = [totals[r["workflow_id"]] / 1e6 for r in data[system]["workflows"]]
    return result


def describe(values, unit, *, distribution=False):
    values = [v for v in values if v is not None]
    if not values:
        return "无样本"
    a = np.asarray(values)
    if distribution:
        return f"n={len(a)}，中位数/P95={np.median(a):.4g}/{np.percentile(a, 95):.4g} {unit}"
    return f"中位数 {np.median(a):.4g}，范围 [{a.min():.4g}, {a.max():.4g}] {unit}"


def key_findings(cases):
    """Answer the three mechanism questions without causal overclaiming."""
    if not all(s in cases.get("f0-revisit", {}) for s in SYSTEMS):
        return []
    data = cases["f0-revisit"]
    summaries = {s: data[s]["summary"] for s in SYSTEMS}
    changes = np.array(
        [
            a["wct_s"] - b["wct_s"]
            for a, b in zip(data["aegis"]["workflows"], data["mooncake"]["workflows"], strict=True)
        ]
    )
    worst = int(np.argmax(changes))
    lines = [
        "### 本轮数据回答了什么",
        "",
        "以下数值均来自统一源码的受控两轮访问配置，按 Mooncake / DRAM-only AegisKV / AegisKV 顺序列出。它主动提供相同输入的再次访问机会，不是采集到的用户复用分布。",
        "",
        "**DRAM 准入与复用。** 正常 DRAM token 命中贡献为 "
        + " / ".join(f"{summaries[s]['dram_hit_pct']:.3f}%" for s in SYSTEMS)
        + "；Mean WCT 为 "
        + " / ".join(f"{summaries[s]['mean_wct_s']:.4f} s" for s in SYSTEMS)
        + f"。AegisKV 相对 Mooncake 有 {int(np.sum(changes > 1e-9))}/160 个 Workflow 的 WCT 更长；"
        + f"最大增量是索引 {worst + 1}（`{data['aegis']['workflows'][worst]['workflow_id']}`）的 {changes[worst]:.4f} s。",
        "",
        "**Peer HBM 与前台等待。** 为正常 GET 取得目标 HBM 的累计等待为 "
        + " / ".join(f"{summaries[s]['foreground_hbm_wait_s']:.3f} s" for s in SYSTEMS)
        + "，调度抢占次数为 "
        + " / ".join(str(summaries[s]["scheduler_preemptions"]) for s in SYSTEMS)
        + "，请求纯 GPU 排队 P95 为 "
        + " / ".join(f"{summaries[s]['p95_scheduler_queue_s']:.4f} s" for s in SYSTEMS)
        + "。累计等待是跨请求求和，不能直接当成增加的 WCT；AegisKV 与 DRAM-only 的配对曲线用于观察加入 Peer 后的整体资源影响。",
        "",
        "**CPU 与传输。** 冻结模型中的控制器服务工作量为 "
        + " / ".join(f"{summaries[s]['modeled_controller_service_s']:.4f} s" for s in SYSTEMS)
        + "；实测 Python 参考准入线程 CPU 时间为 "
        + " / ".join(f"{summaries[s]['reference_admission_cpu_s']:.4f} s" for s in SYSTEMS)
        + "。两种口径分别绘制，后者受共享主机运行环境影响，不是原生 serving CPU 利用率。后台 DRAM 写入和 Peer 复制另列，GET 减速比依据每次读取自己的字节数与路径瓶颈归一化。",
        "",
        "**解释限制。** GET 的样本数与读取量会随缓存命中变化，跨系统 GET P95 的差异包含这些变化；它不是单独关闭 Peer 流量后的反事实效应。图中同时保留逐 Workflow 命中、等待、复制量以及实际链路分项。原始一次访问 trace 的正常 DRAM hit 为零，因此只能作为低复用对照。",
        "",
    ]
    if all(s in cases.get("f0-revisit-bw5", {}) for s in SYSTEMS):
        lines += [
            "**配置敏感性与零结果。** 上述 25 GB/s 配置中的 WCT 方向不能推广到所有带宽。"
            "在其他设置相同的 5 GB/s 配置下，三系统 Mean WCT 为 "
            + " / ".join(
                f"{cases['f0-revisit-bw5'][s]['summary']['mean_wct_s']:.4f} s"
                for s in SYSTEMS
            )
            + "，AegisKV 此时更快，但 DRAM 命中贡献仍更低。命中收益需要同时考虑读取成本；"
            "这组对比尚未独立分离各项调度与传输效应。",
            "",
        ]
    if all(c in cases for c in ("f0-no-slack", "f1-no-slack")):
        unchanged = all(
            a["wct_s"] == b["wct_s"]
            for fault in ("f0", "f1")
            for system in ("dram", "aegis")
            for a, b in zip(
                cases[f"{fault}-no-slack"][system]["workflows"],
                cases[f"{fault}-natural"][system]["workflows"],
                strict=True,
            )
        )
        if unchanged:
            lines += [
                "本轮 F0/F1 零 Slack 消融中，两个 AegisKV 变体的所有 Workflow WCT "
                "均与各自基础配置相同；当前样本不能支持 Slack 带来性能改善的结论。",
                "",
            ]
    return lines


def observation(record, cases):
    name, case = record["name"], record.get("case")
    if name.startswith("sensitivity-"):
        case_names = case.split(",")
        for metric, unit in (
            ("mean_wct_s", "s"),
            ("dram_hit_pct", "%"),
            ("p95_scheduler_queue_s", "s"),
            ("foreground_transfer_p95_ms", "ms"),
        ):
            if name.endswith(metric):
                return (
                    "按横轴配置顺序，"
                    + "；".join(
                        LABELS[s]
                        + "="
                        + "/".join(f"{cases[c][s]['summary'][metric]:.4g}" for c in case_names)
                        + " "
                        + unit
                        for s in SYSTEMS
                    )
                    + "。这些点是不同配置，未画重复运行置信区间。"
                )
    if name.startswith("ablation-") and name.endswith("-slack"):
        base = case.replace("no-slack", "natural")
        return (
            "Mooncake 不使用 Slack，变化为零；"
            + "；".join(
                LABELS[s]
                + "："
                + describe(
                    [
                        a["wct_s"] - b["wct_s"]
                        for a, b in zip(
                            cases[case][s]["workflows"], cases[base][s]["workflows"], strict=True
                        )
                    ],
                    "s",
                )
                for s in ("dram", "aegis")
            )
            + "。"
        )
    if name == "ablation-uncertified-guard":
        return (
            "严格无证书配置的 AegisKV 在所有 GPU、所有时间窗的 Peer 占用均为零；"
            "此图检验控制器的关闭行为，不能作为启用 Peer 后无干扰的证据。"
        )
    if case not in cases or not all(s in cases[case] for s in SYSTEMS):
        return None
    data = cases[case]
    suffix = name.removeprefix(case + "-")
    if suffix in {"controller-service", "controller-service-difference"}:
        series = controller_service(data)
        if suffix.endswith("-difference"):
            series = {
                s: [a - b for a, b in zip(v, series["mooncake"], strict=True)]
                for s, v in series.items()
            }
        return (
            "冻结 CPU 服务模型的工作量："
            + "；".join(LABELS[s] + "：" + describe(series[s], "ms") for s in SYSTEMS)
            + "。相同报价用于整个矩阵；实测 Python 线程时间另图列出。"
        )
    difference = suffix.endswith("-difference")
    metric_name = suffix.removesuffix("-difference")
    if metric_name in WORKFLOW_METRICS:
        metric, unit = WORKFLOW_METRICS[metric_name]
        series = {s: [r[metric] for r in data[s]["workflows"]] for s in SYSTEMS}
        if difference:
            series = {
                s: [a - b for a, b in zip(v, series["mooncake"], strict=True)]
                for s, v in series.items()
            }
            unit = "pp" if unit == "%" else unit
            if metric == "wct_s" and max(abs(v) for vs in series.values() for v in vs) < 0.1:
                unit = "ms"
                series = {s: [v * 1000 for v in vs] for s, vs in series.items()}
        return (
            "160 个配对 Workflow："
            + "；".join(LABELS[s] + "：" + describe(series[s], unit) for s in SYSTEMS)
            + "。"
        )
    if suffix == "failure-penalty":
        baseline = cases["f0-natural"]
        return (
            "相对各自 F0 的逐 Workflow 变化："
            + "；".join(
                LABELS[s]
                + "："
                + describe(
                    [
                        a["wct_s"] - b["wct_s"]
                        for a, b in zip(data[s]["workflows"], baseline[s]["workflows"], strict=True)
                    ],
                    "s",
                )
                for s in SYSTEMS
            )
            + "。负值可能来自闭环调度的变化，原样保留。"
        )
    if suffix.endswith("-cdf"):
        metric = suffix.removesuffix("-cdf")
        if metric == "cpu":
            series = {s: [r["cpu_ns"] / 1000 for r in data[s]["policy_cpu"]] for s in SYSTEMS}
            unit = "µs"
        else:
            divisor, unit = (1e6, "ms") if metric == "request_tpot" else (1e9, "s")
            series = {
                s: [
                    r[metric + "_ns"] / divisor
                    for r in data[s]["requests"]
                    if r[metric + "_ns"] is not None
                ]
                for s in SYSTEMS
            }
        return (
            "；".join(
                LABELS[s] + "：" + describe(series[s], unit, distribution=True) for s in SYSTEMS
            )
            + "。CDF 的样本单位为请求或图注指定的准入调用，未当作独立运行重复。"
        )
    if suffix.startswith("transfer-"):
        metric = suffix.removeprefix("transfer-")
        unit = "ms" if metric == "duration_ms" else "×"
        return (
            "成功 GET："
            + "；".join(
                LABELS[s]
                + "："
                + describe(
                    [r[metric] for r in data[s]["foreground_transfers"]], unit, distribution=True
                )
                for s in SYSTEMS
            )
            + "。"
        )
    match = re.fullmatch(r"(gpu-\d+)-(free_gib|peer_gib)", suffix)
    if match:
        gpu, metric = match.groups()
        return (
            "1 s 窗口均值："
            + "；".join(
                LABELS[s] + "：" + describe(data[s]["hbm"][gpu][metric], "GiB") for s in SYSTEMS
            )
            + "。窗口数由各系统的实际完成时长决定。"
        )
    if suffix.endswith("_gbs"):
        return (
            "1 s 窗内最大速率："
            + "；".join(f"{LABELS[s]}={max(data[s]['network'][suffix]):.4g} GB/s" for s in SYSTEMS)
            + "。前台 GET 争用另由 GET slowdown 图量化。"
        )
    if suffix == "hbm-pressure":
        return (
            "八个 GPU 的低 FREE 时间占比："
            + "；".join(
                LABELS[s]
                + "："
                + describe(
                    [v["free_below_1gib_pct"] for v in data[s]["hbm_pressure"].values()], "%"
                )
                for s in SYSTEMS
            )
            + "。需结合分配等待与抢占解释。"
        )
    match = re.match(r"fault(\d+)-(.+)", suffix)
    if match:
        i, metric = match.groups()
        span_id = data["mooncake"]["manifest"]["failure_schedule"]["events"][int(i) - 1][
            "focus_span_id"
        ]
        rows = {s: next(r for r in data[s]["failures"] if r["span_id"] == span_id) for s in SYSTEMS}
        lead = f"配对请求 `{span_id}`。"
        if metric == "recovery-tokens":
            return (
                lead
                + "按 local/Peer/DRAM/recompute tokens："
                + "；".join(
                    LABELS[s]
                    + "="
                    + "/".join(
                        str(rows[s][k])
                        for k in (
                            "recovery_normal_hbm_local_tokens",
                            "restored_peer_tokens",
                            "restored_store_tokens",
                            "recompute_tokens",
                        )
                    )
                    for s in SYSTEMS
                )
                + "。"
            )
        if metric == "prefix_materialized_ns":
            values = {
                s: next(
                    e["timestamp_ns"]
                    for e in data[s]["recovery_events"]
                    if e["event"] == "CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED"
                    and e["span_id"] == span_id
                    and e["route_version"] == rows[s]["route_version"]
                )
                for s in SYSTEMS
            }
        else:
            values = {s: rows[s][metric] for s in SYSTEMS}
        return (
            lead
            + "故障后间隔："
            + "；".join(
                f"{LABELS[s]}={(values[s] - rows[s]['failure_at_ns']) / 1e9:.6g} s" for s in SYSTEMS
            )
            + "。"
        )
    return None
