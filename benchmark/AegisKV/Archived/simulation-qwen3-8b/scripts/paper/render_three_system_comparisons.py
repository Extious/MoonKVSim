"""Paired fault cases, ablations and one-factor three-system sensitivities."""

import argparse
import json
from pathlib import Path

import numpy as np
from render_three_system_figures import COLORS, RECORDS, canvas, finish, line
from three_system_data import LABELS, SYSTEMS, load_case


def workflow_figures(case, data, out, baseline=None):
    ids = [r["workflow_id"] for r in data["mooncake"]["workflows"]]
    x = np.arange(1, len(ids) + 1)
    metrics = (
        ("wct_s", "Workflow completion time (s)"),
        ("dram_hit_pct", "Prompt tokens served by DRAM (%)"),
        ("mean_scheduler_queue_s", "Mean GPU scheduler queue delay (s)"),
    )
    for metric, ylabel in metrics:
        fig, ax = canvas("Workflow index (fixed ID order)", ylabel, wide=True)
        for s in SYSTEMS:
            assert ids == [r["workflow_id"] for r in data[s]["workflows"]]
            line(ax, s, x, [r[metric] for r in data[s]["workflows"]])
        finish(fig, ax, f"{case}-{metric}", out, ylabel, case)
    fig, ax = canvas(
        "Workflow index (fixed ID order)", "WCT difference from Mooncake (s)", wide=True
    )
    for s in SYSTEMS:
        line(
            ax,
            s,
            x,
            [
                r["wct_s"] - b["wct_s"]
                for r, b in zip(data[s]["workflows"], data["mooncake"]["workflows"], strict=True)
            ],
        )
    finish(fig, ax, f"{case}-wct-difference", out, "逐 workflow 相对 Mooncake 的 WCT 差值", case)
    if baseline is not None:
        fig, ax = canvas(
            "Workflow index (fixed ID order)", "Failure penalty: WCT(F) − WCT(F0) (s)", wide=True
        )
        for s in SYSTEMS:
            line(
                ax,
                s,
                x,
                [
                    r["wct_s"] - b["wct_s"]
                    for r, b in zip(data[s]["workflows"], baseline[s]["workflows"], strict=True)
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


def recovery_figures(case, data, out):
    schedule = data["mooncake"]["manifest"]["failure_schedule"]
    focus_ids = [event["focus_span_id"] for event in schedule["events"]]
    for index, span_id in enumerate(focus_ids, 1):
        matched = {
            s: next(r for r in data[s]["failures"] if r["span_id"] == span_id) for s in SYSTEMS
        }
        for s in SYSTEMS:
            events = [
                e
                for e in data[s]["recovery_events"]
                if e["event"] == "CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED"
                and e["span_id"] == span_id
                and e["route_version"] == matched[s]["route_version"]
            ]
            assert len(events) == 1, (s, span_id, "missing prefix materialization event")
            matched[s] = dict(matched[s], prefix_materialized_ns=events[0]["timestamp_ns"])
        fig, ax = canvas("", "Prompt tokens (Ki)")
        bottom = np.zeros(3)
        for field, color, label in (
            ("recovery_normal_hbm_local_tokens", "#59636F", "Local reusable HBM"),
            ("restored_peer_tokens", "#0072B2", "Peer HBM"),
            ("restored_store_tokens", "#B86B00", "Store DRAM"),
            ("recompute_tokens", "#B83C46", "Recompute"),
        ):
            values = np.array([matched[s][field] / 1024 for s in SYSTEMS])
            ax.bar(range(3), values, bottom=bottom, label=label, color=color, width=0.58)
            bottom += values
        ax.set_xticks(range(3), ["Mooncake", "DRAM-only\nAegisKV", "AegisKV"])
        finish(
            fig,
            ax,
            f"{case}-fault{index}-recovery-tokens",
            out,
            "匹配逻辑故障请求的恢复来源和重算量；每柱是同一请求",
            case,
        )
        for field, ylabel in (
            ("prefix_materialized_ns", "Failure to restored prefix ready (s)"),
            ("recovery_ready_ns", "Failure to resumed decoding (s)"),
            ("completed_ns", "Failure to request completion (s)"),
        ):
            fig, ax = canvas("", ylabel)
            for i, s in enumerate(SYSTEMS):
                row = matched[s]
                ax.bar(
                    i,
                    (row[field] - row["failure_at_ns"]) / 1e9,
                    width=0.58,
                    color=COLORS[s],
                    label=LABELS[s],
                )
            ax.set_xticks(range(3), ["Mooncake", "DRAM-only\nAegisKV", "AegisKV"])
            finish(fig, ax, f"{case}-fault{index}-{field}", out, ylabel + "；同一个逻辑请求", case)


def sensitivity_figures(data, out):
    sweeps = {
        "concurrency": (
            [8, 16, 32],
            ["f0-revisit-c8", "f0-revisit", "f0-revisit-c32"],
            "Active workflow concurrency",
        ),
        "dram-capacity": (
            [32, 128, 1000e9 / 1024**3],
            ["f0-revisit-dram32", "f0-revisit-dram128", "f0-revisit"],
            "DRAM cache capacity (GiB)",
        ),
        "bandwidth": (
            [5, 25, 50],
            ["f0-revisit-bw5", "f0-revisit", "f0-revisit-bw50"],
            "Shared transfer capacity (GB/s)",
        ),
        "cpu-service": ([1, 4], ["f0-natural", "f0-cpu4x"], "Controller service-cost multiplier"),
    }
    for sweep, (xs, cases, xlabel) in sweeps.items():
        for metric, ylabel in (
            ("mean_wct_s", "Mean workflow completion time (s)"),
            ("dram_hit_pct", "Prompt tokens served by DRAM (%)"),
            ("p95_scheduler_queue_s", "P95 GPU scheduler queue delay (s)"),
            ("foreground_transfer_p95_ms", "P95 foreground DRAM GET latency (ms)"),
        ):
            if metric == "foreground_transfer_p95_ms" and sweep == "cpu-service":
                continue
            fig, ax = canvas(xlabel, ylabel)
            for s in SYSTEMS:
                line(ax, s, xs, [data[c][s]["summary"][metric] for c in cases], marker="o")
            if sweep == "dram-capacity":
                ax.set_xscale("log", base=2)
                ax.set_xticks(xs, ["32", "128", "931.3"])
            else:
                ax.set_xticks(xs)
            finish(
                fig,
                ax,
                f"sensitivity-{sweep}-{metric}",
                out,
                ylabel + "；单变量改变 " + xlabel,
                ",".join(cases),
            )


def ablation_figures(data, reduced_root, out):
    for scenario in ("f0", "f1"):
        baseline = data[f"{scenario}-natural"]
        fig, ax = canvas(
            "Workflow index (fixed ID order)", "WCT change when slack is disabled (s)", wide=True
        )
        line(ax, "mooncake", np.arange(1, 161), np.zeros(160))
        for s in ("dram", "aegis"):
            alternative = json.loads(
                (reduced_root / f"{scenario}-no-slack" / f"{s}.json").read_text()
            )
            assert alternative["manifest"]["workload"] == baseline[s]["manifest"]["workload"]
            line(
                ax,
                s,
                np.arange(1, 161),
                [
                    a["wct_s"] - b["wct_s"]
                    for a, b in zip(alternative["workflows"], baseline[s]["workflows"], strict=True)
                ],
            )
        finish(
            fig,
            ax,
            f"ablation-{scenario}-slack",
            out,
            "零 Slack 消融相对各自系统的逐 workflow WCT 变化；Mooncake 不使用 Slack，恒为零",
            f"{scenario}-no-slack",
        )
    guarded = json.loads((reduced_root / "f0-guarded-no-certificate" / "aegis.json").read_text())
    assert all(max(gpu["peer_gib"]) == 0 for gpu in guarded["hbm"].values())
    fig, ax = canvas("Workflow index (fixed ID order)", "Workflow completion time (s)", wide=True)
    for s in SYSTEMS:
        values = guarded if s == "aegis" else data["f0-natural"][s]
        line(ax, s, np.arange(1, 161), [r["wct_s"] for r in values["workflows"]])
    finish(
        fig,
        ax,
        "ablation-uncertified-guard",
        out,
        "无 QoS 证书的严格控制器；AegisKV 不发放 Peer 配额",
        "f0-guarded-no-certificate",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case")
    args = parser.parse_args()
    if args.case:
        case = args.case
        data = load_case(args.data / case)
        baseline = (
            load_case(args.data / "f0-natural") if case in {"f1-natural", "f2-natural"} else None
        )
        workflow_figures(case, data, args.output, baseline)
        if baseline:
            recovery_figures(case, data, args.output)
    else:
        cases = [
            "f0-natural",
            "f0-revisit",
            "f1-natural",
            "f0-revisit-c8",
            "f0-revisit-c32",
            "f0-revisit-dram32",
            "f0-revisit-dram128",
            "f0-revisit-bw5",
            "f0-revisit-bw50",
            "f0-cpu4x",
        ]
        data = {c: load_case(args.data / c) for c in cases}
        sensitivity_figures(data, args.output)
        ablation_figures(data, args.data, args.output)
    (args.output / f"{args.case or 'cross-case'}-figure-manifest.json").write_text(
        json.dumps(RECORDS, indent=2, ensure_ascii=False) + "\n"
    )
    print(f"Exported {len(RECORDS)} standalone figures")


if __name__ == "__main__":
    main()
