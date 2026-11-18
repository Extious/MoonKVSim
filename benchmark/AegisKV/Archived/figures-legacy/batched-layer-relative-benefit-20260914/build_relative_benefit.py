"""Reproducible analytical latency reductions against explicit zero-Peer baselines.

The primary figure holds one optimized no-backup baseline fixed within a curve.
The companion figure matches the no-backup batch size to each protected point.
Neither calculation normalizes exposed waiting alone or claims measured recovery.
"""
from __future__ import annotations

import csv
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
BASE = OUT.parent / "batched-layer-pipeline-20260914"
PREVIOUS = OUT.parent / "batched-layer-pareto-sensitivity-20260914"
spec = importlib.util.spec_from_file_location("batch_base", BASE / "build_batched_pipeline.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pymupdf

CONDITIONS = ((512, 12.5), (512, 25), (512, 50), (128, 25),
              (256, 25), (1024, 25), (2048, 25))
BLUE, ORANGE, GREEN, PURPLE, TEAL = "#0072B2", "#D55E00", "#009E73", "#8C5AA7", "#596F78"
GREY, LIGHT = "#8B929A", "#C3C8CE"


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_csv(name, rows):
    with (OUT / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def no_backup_schedule(c, d, b):
    """Load batch one at t=0; prefetch the next only at current compute start.

    This runs an explicit zero-residency schedule, independently of the protected
    recurrence. Actual tail batches are preserved; no all-layer-load barrier.
    """
    events = []
    compute_end, copy_start = Fraction(0), Fraction(0)
    for first in range(1, 37, b):
        last = min(first + b - 1, 36)
        count = last - first + 1
        ready = copy_start + count * d
        start = max(compute_end, ready)
        events.append({
            "batch_id": len(events) + 1, "first_layer": first, "last_layer": last,
            "layer_count": count, "copy_start_ms": copy_start, "copy_end_ms": ready,
            "exposed_wait_ms": start - compute_end,
            "compute_start_ms": start, "compute_end_ms": start + count * c,
        })
        compute_end = start + count * c
        copy_start = start
    return events


def data():
    with (PREVIOUS / "sensitivity-classification.csv").open() as f:
        previous = {(int(r["replay_tokens"]), float(r["H2D_GB_s_assumed"]),
                     int(r["batch_layers"])): r for r in csv.DictReader(f)}
    curves, public, all_events, summaries = {}, [], [], []
    for n, bandwidth in CONDITIONS:
        c, d, size = base.layer_costs(32768, n, bandwidth)
        rows = []
        for b in range(1, 37):
            protected = base.schedule(c, d, batch=b)
            zero = no_backup_schedule(c, d, b)
            t, z = protected[-1]["compute_end_ms"], zero[-1]["compute_end_ms"]
            w, zw = base.exact_wait(protected), base.exact_wait(zero)
            assert t == 36 * c + w and z == 36 * c + zw
            assert z - t == b * d
            # A second check using batch-duration boundary gaps, not event times.
            counts = [e["layer_count"] for e in zero]
            boundary_wait = sum((max(counts[i] * d - counts[i-1] * c, 0)
                                 for i in range(1, len(counts))), Fraction(0))
            assert zw == counts[0] * d + boundary_wait
            assert sum(counts) == 36
            for i, (p, q) in enumerate(zip(protected, zero)):
                assert q["compute_start_ms"] - p["compute_start_ms"] == b * d
                assert q["compute_end_ms"] - p["compute_end_ms"] == b * d
                assert q["compute_start_ms"] >= q["copy_end_ms"]
                if i:
                    assert q["copy_start_ms"] == zero[i-1]["compute_start_ms"]
                    assert q["copy_start_ms"] >= zero[i-1]["copy_end_ms"]
                    assert q["exposed_wait_ms"] == p["exposed_wait_ms"]
            old = previous[n, bandwidth, b]
            assert float(t) == float(old["total_pipeline_ms"])
            assert float(w) == float(old["exposed_wait_ms"])
            rows.append({"b": b, "bytes": b * size, "wait": w, "total": t,
                         "matched_zero_total": z, "matched_zero_wait": zw,
                         "paired_gain": 100 * (z - t) / z})
            all_events.extend({"replay_tokens": n, "H2D_GB_s_assumed": bandwidth,
                               "batch_layers": b, "initial_resident_layers": 0,
                               **base.json_values(e)} for e in zero)
        common_zero = min(p["matched_zero_total"] for p in rows)
        common_best = [p["b"] for p in rows if p["matched_zero_total"] == common_zero]
        assert common_best == [1]  # Result of the scan, not the selection rule.
        for p in rows:
            p["common_zero_total"] = common_zero
            p["gain"] = 100 * (common_zero - p["total"]) / common_zero
            dominated = [q["b"] for q in rows if q["bytes"] <= p["bytes"]
                         and q["total"] <= p["total"]
                         and (q["bytes"] < p["bytes"] or q["total"] < p["total"])]
            p["pareto"], p["dominated_by"] = not dominated, dominated
            assert p["pareto"] == (previous[n, bandwidth, p["b"]]["pareto_within_condition"] == "True")
            assert p["gain"] < 100 and 0 < p["paired_gain"] < 100
        # A fixed positive denominator preserves cost / latency dominance.
        for p in rows:
            dom_gain = [q["b"] for q in rows if q["bytes"] <= p["bytes"]
                        and q["gain"] >= p["gain"]
                        and (q["bytes"] < p["bytes"] or q["gain"] > p["gain"])]
            assert dom_gain == p["dominated_by"]
        curves[n, bandwidth] = rows
        summaries.append({
            "replay_tokens": n, "H2D_GB_s_assumed": bandwidth,
            "common_zero_backup_total_ms": float(common_zero),
            "best_no_backup_batch_layers": common_best,
            "total_compute_ms": float(36 * c),
            "first_zero_wait_batch_layers": next(p["b"] for p in rows if p["wait"] == 0),
            "maximum_common_baseline_gain_percent": float(max(p["gain"] for p in rows)),
            "pareto_batch_layers": [p["b"] for p in rows if p["pareto"]],
            "paired_gain_strictly_increases": all(q["paired_gain"] > p["paired_gain"]
                                                   for p, q in zip(rows, rows[1:])),
            "reference_points": [{k: float(p[k]) for k in
                                  ("b", "total", "common_zero_total", "matched_zero_total", "gain", "paired_gain")}
                                 for p in rows if p["b"] in (1, 6, 20, 36)],
        })
        for p in rows:
            public.append({
                "M": 32768, "replay_tokens": n, "H2D_GB_s_assumed": bandwidth,
                "batch_layers": p["b"], "initial_resident_layers": p["b"],
                "initial_Peer_HBM_MiB": p["bytes"] // 2**20,
                "protected_wait_ms": float(p["wait"]), "total_compute_ms": float(36 * c),
                "protected_total_ms": float(p["total"]),
                "common_zero_backup_batch_layers": common_best[0],
                "common_zero_backup_total_ms": float(common_zero),
                "relative_gain_percent_common_baseline": float(p["gain"]),
                "common_gain_exact_numerator": p["gain"].numerator,
                "common_gain_exact_denominator": p["gain"].denominator,
                "matched_zero_backup_wait_ms": float(p["matched_zero_wait"]),
                "matched_zero_backup_total_ms": float(p["matched_zero_total"]),
                "relative_gain_percent_matched_batch": float(p["paired_gain"]),
                "paired_gain_exact_numerator": p["paired_gain"].numerator,
                "paired_gain_exact_denominator": p["paired_gain"].denominator,
                "pareto_within_condition_common_baseline": p["pareto"],
                "dominated_by_batch_layers": ";".join(map(str, p["dominated_by"])),
            })
    assert len(public) == 252
    assert curves[512, 25][19]["gain"] == curves[512, 25][35]["gain"]
    assert curves[512, 25][19]["paired_gain"] < curves[512, 25][35]["paired_gain"]
    assert curves[1024, 25][0]["gain"] != curves[2048, 25][0]["gain"]
    write_csv("relative-benefit.csv", public)
    write_csv("zero-backup-batch-events.csv", all_events)
    dump("curve-summaries.json", summaries)
    dump("validation.json", {
        "unique_conditions": 7, "unique_protected_states": 252,
        "unique_zero_backup_states": 252, "protected_states_matched_to_previous": 252,
        "zero_backup_explicit_schedule_matches_boundary_sum": True,
        "matched_schedule_translation_verified_at_every_batch": True,
        "no_backup_first_batch_loading_included": True,
        "denominator_includes_all_layer_compute_and_exposed_wait": True,
        "common_baseline_selected_from_all_36_zero_backup_batch_sizes": True,
        "best_zero_backup_batch_is_one_in_all_seven_conditions": True,
        "exact_pareto_status_unchanged_with_fixed_denominator": True,
        "1024_and_2048_relative_gains_distinct_and_plotted_separately": True,
        "negative_gain_points": sum(p["relative_gain_percent_common_baseline"] < 0 for p in public),
        "physical_experiments": 0, "independent_statistical_replicates": None,
    })
    return curves


def setup_axis(ax, ymax, yticks, wide=False):
    ax.set_xlim(0, 37)
    ax.set_ylim(-.035 * ymax, ymax)  # User confirmed: higher relative benefit is higher on the page.
    ax.set_yticks(yticks)
    ax.set_xticks([1, 6, 12, 18, 24, 30, 36])
    ax.tick_params(labelsize=8)
    ax.set_xlabel("每批层数 / 初始备份前层数", fontsize=8.3, labelpad=5)
    ax.set_ylabel("总恢复延迟降低（%）", fontsize=8.5)
    ax.set_axisbelow(True)
    ax.grid(alpha=.15)
    top = ax.secondary_xaxis("top", functions=(lambda x: x*128, lambda x: x/128))
    ticks = [1, 6, 12, 18, 24, 30, 36] if wide else [1, 12, 24, 36]
    top.set_xticks([b*128 for b in ticks])
    top.tick_params(labelsize=7.5, pad=3)


def draw_curves(ax, series, paired=False):
    key = "paired_gain" if paired else "gain"
    for rows, color, style, label in series:
        ax.plot([p["b"] for p in rows], [float(p[key]) for p in rows],
                color=color, ls=style, lw=1.1, label=label, zorder=1)
    if paired:
        for rows, color, style, label in series:
            ax.scatter([p["b"] for p in rows], [float(p[key]) for p in rows],
                       color=color, s=6, marker="o", zorder=2)
        return
    for keep in (False, True):
        for rows, color, style, label in series:
            points = [p for p in rows if p["pareto"] == keep]
            ax.scatter([p["b"] for p in points], [float(p[key]) for p in points],
                       marker="o" if keep else "x", s=17 if keep else 9,
                       linewidths=.35 if keep else .65,
                       color=color, alpha=1 if keep else .45, zorder=4 if keep else 2,
                       **({"edgecolors": "white"} if keep else {}))


def render(curves, paired=False):
    name = "relative-benefit-matched-batch" if paired else "relative-benefit-sensitivity"
    fig = plt.figure(figsize=(178/25.4, 185/25.4))
    title = "Peer HBM 前层备份的相对延迟收益"
    fig.text(.065, .957, title + ("：同批配对" if paired else "：统一基线"), fontsize=11.3)
    fig.text(.065, .933, "解析估算，非实测｜Qwen3-8B，36 层｜历史 32K｜假设有效算力 100 TFLOP/s", fontsize=8)
    baseline = ("基线：相同带宽、重放长度、批大小下，初始完全没有 Peer HBM 备份。"
                if paired else "基线：各带宽、重放条件下，无 Peer HBM 备份的最低延迟；整条曲线共用。")
    fig.text(.065, .904, baseline, fontsize=8)
    fig.text(.065, .875, "延迟包含全部重放计算与加载等待；上横轴为初始 Peer HBM（MiB），每层 128 MiB。", fontsize=7.8)
    if paired:
        fig.text(.065, .845, "注意：本图分母随批大小变化；曲线上的圆点仅表示配置，不作为帕累托标记。", fontsize=8, color="#79512D")
    else:
        fig.legend(handles=[Line2D([], [], marker="o", linestyle="none", color=BLUE, markersize=4.5,
                                   label="帕累托点：容量更少、收益更大"),
                            Line2D([], [], marker="x", linestyle="none", color=GREY, markersize=4.5,
                                   label="被支配点")],
                   loc="center", bbox_to_anchor=(.50, .843), ncol=2, frameon=False,
                   fontsize=8, handlelength=1.2, columnspacing=1.5)
    fig.text(.065, .803, "(a) 基准：25 GB/s，512 token", fontsize=9.4)
    fig.text(.580, .803, "(b) H2D 带宽对比：512 token", fontsize=9.4)
    ax = fig.add_axes([.105, .545, .35, .207])
    setup_axis(ax, 60 if paired else 16, [0, 15, 30, 45, 60] if paired else [0, 4, 8, 12, 16])
    ref = curves[512, 25]
    key = "paired_gain" if paired else "gain"
    if paired:
        draw_curves(ax, [(ref, BLUE, "-", "512 token")], paired=True)
        ax.annotate("20 层后实际延迟不再降", xy=(20, float(ref[19][key])),
                    xytext=(.49, .17), textcoords="axes fraction", ha="center", fontsize=7.3,
                    arrowprops={"arrowstyle": "->", "lw": .65, "color": GREY})
    else:
        ax.plot([p["b"] for p in ref], [float(p[key]) for p in ref], color=LIGHT, lw=1)
        for keep, color, marker in ((False, GREY, "x"), (True, BLUE, "o")):
            pp = [p for p in ref if p["pareto"] == keep]
            ax.scatter([p["b"] for p in pp], [float(p[key]) for p in pp], color=color,
                       marker=marker, s=19, linewidths=.7, zorder=3 if keep else 2)
        ax.annotate(f"20 层：{float(ref[19][key]):.2f}%\n此后收益不再增加",
                    xy=(20, float(ref[19][key])), xytext=(.65, .43), textcoords="axes fraction",
                    ha="center", fontsize=7.6,
                    arrowprops={"arrowstyle": "->", "lw": .65, "color": GREY})
        ax.text(.04, .92, f"无备份：{float(ref[0]['common_zero_total']):.2f} ms", transform=ax.transAxes,
                fontsize=7.3, color="#526574")
    ax = fig.add_axes([.605, .545, .35, .207])
    setup_axis(ax, 75 if paired else 65, [0, 15, 30, 45, 60, 75] if paired else [0, 15, 30, 45, 60])
    bandwidth_series = [(curves[512, 12.5], ORANGE, "-", "12.5 GB/s"),
                        (curves[512, 25], BLUE, "--", "25 GB/s"),
                        (curves[512, 50], GREEN, ":", "50 GB/s")]
    draw_curves(ax, bandwidth_series, paired)
    ax.legend(handles=[Line2D([], [], color=c, ls=s, lw=1.1, label=lab) for _, c, s, lab in bandwidth_series],
              loc="upper left", frameon=False, fontsize=8, handlelength=2.2)
    fig.text(.065, .467, "(c) 重放 token 数对比：H2D 带宽固定为 25 GB/s", fontsize=9.7)
    ax = fig.add_axes([.105, .175, .85, .247])
    setup_axis(ax, 90 if paired else 85, [0, 20, 40, 60, 80], wide=True)
    replay_series = [(curves[128, 25], ORANGE, "-", "128 token"),
                     (curves[256, 25], PURPLE, "-.", "256 token"),
                     (curves[512, 25], BLUE, "--", "512 token"),
                     (curves[1024, 25], GREEN, ":", "1024 token"),
                     (curves[2048, 25], TEAL, (0, (5, 1, 1, 1)), "2048 token")]
    draw_curves(ax, replay_series, paired)
    ax.legend(handles=[Line2D([], [], color=c, ls=s, lw=1.1, label=lab) for _, c, s, lab in replay_series],
              loc="upper left", frameon=False, fontsize=8, handlelength=2.5, labelspacing=.45)
    if not paired:
        ax.text(.57, .30, "长重放的两条曲线均为常数：\n"
                f"1024 token：{float(curves[1024, 25][0]['gain']):.2f}%；"
                f"2048 token：{float(curves[2048, 25][0]['gain']):.2f}%", transform=ax.transAxes,
                fontsize=7.9, color="#526574", linespacing=1.5)
    fig.text(.065, .090, "纵轴正向：低值在下、高值在上，越靠上收益越大。0% 表示与无备份延迟相同。", fontsize=7.9)
    foot = ("同批配对适合隔离备份作用；增大批大小也会抬高基线，不能把百分比上升等同实际延迟下降。"
            if paired else "无备份基线扫描每批 1–36 层后选最小值，本组均为 1 层；帕累托只在固定条件内判定。")
    fig.text(.065, .060, foot, fontsize=7.65)
    fig.text(.065, .031, "仅预取下一批、整批就绪后切换。延迟不含故障检测、接管排队、权重加载与备份维护。", fontsize=7.7)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=300, facecolor="white")
    plt.close(fig)
    with pymupdf.open(OUT / f"{name}.pdf") as pdf:
        assert abs(pdf[0].rect.width / 72 * 25.4 - 178) < .01
        for dpi in (96, 150):
            pdf[0].get_pixmap(dpi=dpi, alpha=False).save(OUT / f"{name}.pdf-{dpi}dpi.png")


def main():
    curves = data()
    render(curves)
    render(curves, paired=True)
    dump("parameters.json", {
        "model": "Qwen3-8B", "layers": 36, "history_tokens": 32768,
        "effective_compute_TFLOP_s_assumed": 100, "initial_Peer_HBM_MiB_per_layer": 128,
        "batch_layers_and_initial_resident_layers": list(range(1, 37)),
        "reference": {"H2D_GB_s": 25, "replay_tokens": 512},
        "right_panel": {"replay_tokens": 512, "H2D_GB_s": [12.5, 25, 50]},
        "bottom_panel": {"H2D_GB_s": 25, "replay_tokens": [128, 256, 512, 1024, 2048]},
        "latency": "All 36-layer replay compute plus exposed KV loading wait from ready-to-replay t=0",
        "relative_gain": "Latency saved divided by the applicable no-Peer-HBM-backup total latency, expressed as percent",
        "main_baseline": "For each fixed bandwidth/replay condition, minimum zero-backup latency over batch sizes 1..36, held constant for all protected points",
        "matched_companion_baseline": "Zero initial residency, same batch size as each protected point; denominator varies along each curve",
        "zero_backup": "All historical KV initially in Host DRAM, first batch loads at t=0, next batch copies at current batch compute start",
        "main_pareto_objectives": ["minimize initial Peer HBM bytes", "maximize common-baseline relative latency gain"],
        "main_pareto_scope": "Within each fixed bandwidth and replay condition; same exact frontier as actual latency",
        "companion_markers": "Ordinary candidate markers, not old absolute-latency Pareto classifications",
        "y_orientation": "Low numeric values at bottom, high values at top; user explicitly confirmed that higher relative benefit should be higher on the page",
        "layout": "Baseline upper left, bandwidth upper right, replay below",
        "schedule": "Only next batch, entire batch ready before compute, actual partial tail, single compute and single H2D streams, copied KV retained",
        "time_exclusions": ["failure detection", "takeover queueing", "weight loading", "backup maintenance", "foreground interference", "transfer launch overhead"],
        "capacity_scope": "Initial Peer HBM historical KV only; not peak recovery allocation or lifecycle cost",
        "evidence": "Analytical and uncalibrated; zero physical runs or statistical replicates",
        "placed_width_mm": 178, "placed_height_mm": 185,
    })
    sources = [BASE / "build_batched_pipeline.py", PREVIOUS / "sensitivity-classification.csv",
               PREVIOUS / "build_sensitivity.py"]
    dump("MANIFEST.json", {
        "sources_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir())
                         if p.suffix in {".py", ".csv", ".json", ".png", ".pdf", ".svg", ".md"}
                         and p.name not in {"MANIFEST.json", "REVIEW.json", "figure-lesson.json"}},
    })
    print(json.dumps({"conditions": 7, "protected_states": 252, "zero_backup_states": 252,
                      "primary": "relative-benefit-sensitivity.pdf", "companion": "relative-benefit-matched-batch.pdf"}))


if __name__ == "__main__":
    main()
