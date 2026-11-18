"""Analytical relative-benefit curves collapsed by transfer/compute time ratio.

Times are normalized by one layer's compute duration, not hardware measurements.
Each ratio has a fixed optimized zero-Peer-backup baseline across batch sizes.
"""
from __future__ import annotations

import csv
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
PREVIOUS = OUT.parent / "batched-layer-relative-benefit-20260914"
spec = importlib.util.spec_from_file_location("relative_base", PREVIOUS / "build_relative_benefit.py")
relative = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relative)
base = relative.base
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pymupdf

RATIOS = (Fraction(1, 2), Fraction(1), Fraction(5, 4), Fraction(2), Fraction(4))
COLORS = ("#009E73", "#596F78", "#0072B2", "#8C5AA7", "#D55E00")
STYLES = (":", (0, (5, 1, 1, 1)), "--", "-.", "-")
LAYERS = 36
MIB_PER_LAYER = 128


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def write_csv(name, rows):
    with (OUT / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def curve(c, d):
    rows = []
    for b in range(1, LAYERS + 1):
        ev = base.schedule(c, d, batch=b)
        zero = relative.no_backup_schedule(c, d, b)
        total = ev[-1]["compute_end_ms"]
        zero_total = zero[-1]["compute_end_ms"]
        wait = base.exact_wait(ev)
        # An independent sum of exposed gaps at batch boundaries.
        counts = [e["layer_count"] for e in ev]
        gap_sum = sum((max(counts[i] * d - counts[i-1] * c, 0)
                       for i in range(1, len(counts))), Fraction(0))
        assert wait == gap_sum
        assert total == LAYERS * c + wait
        assert zero_total == total + b * d
        assert base.layer_reference(c, d, LAYERS, b)[-1][2] == total
        rows.append({"b": b, "wait": wait, "total": total, "zero_total": zero_total,
                     "partition": "+".join(str(x) for x in counts)})
    baseline = min(p["zero_total"] for p in rows)
    best_zero = [p["b"] for p in rows if p["zero_total"] == baseline]
    assert best_zero == [1]
    for p in rows:
        p["baseline"] = baseline
        p["gain"] = 100 * (baseline - p["total"]) / baseline
        p["dominated_by"] = [q["b"] for q in rows if q["b"] < p["b"] and q["total"] <= p["total"]]
        p["pareto"] = not p["dominated_by"]
    # Ordered record gains must agree with exact pairwise cost/gain dominance.
    best_gain = None
    for p in rows:
        record = best_gain is None or p["gain"] > best_gain
        assert record == p["pareto"]
        if record:
            best_gain = p["gain"]
    return rows


def data():
    curves, public, summaries, event_rows = {}, [], [], []
    for ratio in RATIOS:
        rows = curve(Fraction(1), ratio)
        curves[ratio] = rows
        for scale in (Fraction(1, 10), Fraction(4), Fraction(10)):
            scaled = curve(scale, scale * ratio)
            for p, q in zip(rows, scaled):
                assert p["gain"] == q["gain"]
                assert p["pareto"] == q["pareto"]
                assert q["total"] == p["total"] * scale
                assert q["baseline"] == p["baseline"] * scale
        first_zero = next(p["b"] for p in rows if p["wait"] == 0)
        assert rows[first_zero - 1]["pareto"]
        summaries.append({
            "transfer_to_compute_ratio": float(ratio), "exact_ratio": str(ratio),
            "baseline_normalized_time": float(rows[0]["baseline"]),
            "best_zero_backup_batch_layers": 1,
            "first_saturation_batch_layers": first_zero,
            "saturation_initial_HBM_MiB": first_zero * MIB_PER_LAYER,
            "maximum_gain_percent": float(max(p["gain"] for p in rows)),
            "pareto_batch_layers": [p["b"] for p in rows if p["pareto"]],
        })
        for p in rows:
            public.append({
                "transfer_to_compute_ratio": float(ratio), "ratio_exact": str(ratio),
                "batch_layers": p["b"], "initial_resident_layers": p["b"],
                "initial_Peer_HBM_MiB": p["b"] * MIB_PER_LAYER,
                "batch_partition": p["partition"],
                "protected_wait_normalized": float(p["wait"]),
                "total_compute_normalized": LAYERS,
                "protected_total_normalized": float(p["total"]),
                "same_batch_zero_total_normalized": float(p["zero_total"]),
                "fixed_zero_backup_baseline_normalized": float(p["baseline"]),
                "relative_latency_gain_percent": float(p["gain"]),
                "gain_exact_numerator": p["gain"].numerator,
                "gain_exact_denominator": p["gain"].denominator,
                "pareto_within_ratio": p["pareto"],
                "dominated_by_batch_layers": ";".join(map(str, p["dominated_by"])),
            })
            for scenario, events in (("protected", base.schedule(Fraction(1), ratio, batch=p["b"])),
                                     ("zero_backup", relative.no_backup_schedule(Fraction(1), ratio, p["b"]))):
                event_rows.extend({
                    "ratio_exact": str(ratio), "batch_layers": p["b"], "scenario": scenario,
                    "batch_id": e["batch_id"], "first_layer": e["first_layer"], "last_layer": e["last_layer"],
                    "copy_start_normalized": None if e["copy_start_ms"] is None else float(e["copy_start_ms"]),
                    "copy_end_normalized": None if e["copy_end_ms"] is None else float(e["copy_end_ms"]),
                    "compute_start_normalized": float(e["compute_start_ms"]),
                    "compute_end_normalized": float(e["compute_end_ms"]),
                    "exposed_wait_normalized": float(e["exposed_wait_ms"]),
                } for e in events)
    # Map all seven old bandwidth/replay conditions to their exact ratios. The
    # five plotted ratios are synthetic representatives, not rounded old inputs.
    mappings = []
    with (PREVIOUS / "relative-benefit.csv").open() as f:
        old = list(csv.DictReader(f))
    by_condition = {}
    for p in old:
        by_condition.setdefault((int(p["replay_tokens"]), float(p["H2D_GB_s_assumed"])), []).append(p)
    for (n, bw), old_rows in by_condition.items():
        c, d, size = base.layer_costs(32768, n, bw)
        ratio = d / c
        collapsed = curve(Fraction(1), ratio)
        for p, old_p in zip(collapsed, old_rows):
            assert p["b"] == int(old_p["batch_layers"])
            exact_old_gain = Fraction(int(old_p["common_gain_exact_numerator"]), int(old_p["common_gain_exact_denominator"]))
            assert p["gain"] == exact_old_gain
            assert p["pareto"] == (old_p["pareto_within_condition_common_baseline"] == "True")
        mappings.append({"history_tokens": 32768, "replay_tokens": n, "H2D_GB_s_assumed": bw,
                         "per_layer_compute_ms": float(c), "per_layer_transfer_ms": float(d),
                         "transfer_to_compute_ratio": float(ratio), "exact_ratio": str(ratio),
                         "all_36_previous_gains_and_pareto_status_matched_exactly": True})
    write_csv("ratio-benefit.csv", public)
    write_csv("batch-events-normalized.csv", event_rows)
    write_csv("previous-condition-ratio-mapping.csv", mappings)
    dump("curve-summaries.json", summaries)
    dump("validation.json", {
        "plotted_ratios": 5, "unique_protected_configurations": 180, "unique_zero_backup_configurations": 180,
        "physical_runs": 0, "statistical_replicates": None,
        "per_batch_gap_sum_and_layer_reference_agree": True,
        "exact_pairwise_and_record_frontiers_agree": True,
        "three_additional_time_scales_preserve_all_180_gains_and_frontiers": True,
        "old_bandwidth_replay_states_matched_at_exact_ratios": 252,
        "no_backup_first_batch_loading_counted": True,
        "baseline_is_fixed_within_each_ratio": True,
        "small_ratio_gains_are_nonzero_and_labeled": True,
        "first_saturation_layer_counts": [p["first_saturation_batch_layers"] for p in summaries],
    })
    return curves


def render(curves):
    fig = plt.figure(figsize=(178/25.4, 142/25.4))
    fig.text(.065, .943, "传输与计算时间比决定前层备份的收益", fontsize=12)
    fig.text(.065, .908, "解析估算，非实测｜36 层｜各层耗时一致｜每层历史 KV 为 128 MiB", fontsize=8.5)
    fig.text(.065, .871, "每条曲线共用该倍数下的最优无备份流水延迟；收益计入全部计算与加载等待。", fontsize=8.2)
    fig.legend(handles=[Line2D([], [], color="#0072B2", marker="o", linestyle="none", markersize=4.5,
                               label="实心圆：该曲线内的帕累托点"),
                        Line2D([], [], color="#8B929A", marker="x", linestyle="none", markersize=4.5,
                               label="叉号：被支配点")],
               loc="center", bbox_to_anchor=(.51, .829), ncol=2, frameon=False, fontsize=8.5,
               columnspacing=1.8, handlelength=1.1)
    ax = fig.add_axes([.11, .250, .835, .458])
    ax.set_xlim(0, 37)
    ax.set_ylim(-3, 85)
    ax.set_xticks([1, 6, 12, 18, 24, 30, 36])
    ax.set_yticks([0, 20, 40, 60, 80])
    ax.set_xlabel("初始备份前层数 / 流水线每批层数", fontsize=9.5, labelpad=7)
    ax.set_ylabel("相对无备份的总延迟降低（%）", fontsize=9.5)
    ax.tick_params(labelsize=9)
    ax.set_axisbelow(True)
    ax.grid(alpha=.15)
    top = ax.secondary_xaxis("top", functions=(lambda x: x * MIB_PER_LAYER, lambda x: x / MIB_PER_LAYER))
    top.set_xticks([b * MIB_PER_LAYER for b in (1, 6, 12, 18, 24, 30, 36)])
    top.set_xlabel("初始 Peer HBM 占用（MiB）", fontsize=9, labelpad=6)
    top.tick_params(labelsize=8.5, pad=3)
    for ratio, color, style in zip(RATIOS, COLORS, STYLES):
        rows = curves[ratio]
        ax.plot([p["b"] for p in rows], [float(p["gain"]) for p in rows], color=color,
                ls=style, lw=1.2, zorder=1, label=f"{float(ratio):g} 倍")
    for keep in (False, True):
        for ratio, color in zip(RATIOS, COLORS):
            points = [p for p in curves[ratio] if p["pareto"] == keep]
            ax.scatter([p["b"] for p in points], [float(p["gain"]) for p in points],
                       color=color, marker="o" if keep else "x", s=23 if keep else 10,
                       linewidths=.4 if keep else .65, alpha=1 if keep else .43,
                       zorder=4 if keep else 2, **({"edgecolors": "white"} if keep else {}))
    ax.legend(handles=[Line2D([], [], color=c, ls=s, lw=1.3, label=f"{float(r):g} 倍")
                       for r, c, s in zip(RATIOS, COLORS, STYLES)],
              title="单层传输耗时为计算的", title_fontsize=8.3, loc="upper left",
              fontsize=8.5, frameon=False, handlelength=2.6, labelspacing=.35)
    for ratio, color in zip(RATIOS[2:], COLORS[2:]):
        p = next(p for p in curves[ratio] if p["wait"] == 0)
        ax.text(36, float(p["gain"]) + 2.2,
                f"{p['b']} 层起：{float(p['gain']):.2f}%", color=color,
                fontsize=8.3, ha="right", va="bottom")
    low_label = ("传输不慢于计算时，收益仍大于零：\n"
                 f"0.5 倍：{float(curves[Fraction(1,2)][0]['gain']):.2f}%；"
                 f"1 倍：{float(curves[Fraction(1)][0]['gain']):.2f}%")
    ax.text(.54, .145, low_label, transform=ax.transAxes, fontsize=8.4, color="#526574", linespacing=1.5)
    fig.text(.065, .139, "越往上收益越好；每个倍数单独判定帕累托。备份层数增加，也同时增加初始 HBM 成本。", fontsize=8.2)
    fig.text(.065, .101, "仅预取下一批、整批就绪后切换；保留实际尾批。无备份基线扫描每批 1–36 层取最小值。", fontsize=8.15)
    fig.text(.065, .063, "计算与传输时间按相同倍数缩放时，相对收益不变；图中倍数为解析参数，未经硬件校准。", fontsize=8.15)
    for ext in ("png", "pdf", "svg"):
        fig.savefig(OUT / f"ratio-benefit.{ext}", dpi=300, facecolor="white")
    plt.close(fig)
    with pymupdf.open(OUT / "ratio-benefit.pdf") as pdf:
        assert abs(pdf[0].rect.width / 72 * 25.4 - 178) < .01
        for dpi in (96, 150):
            pdf[0].get_pixmap(dpi=dpi, alpha=False).save(OUT / f"ratio-benefit.pdf-{dpi}dpi.png")


def main():
    curves = data()
    render(curves)
    dump("parameters.json", {
        "evidence": "Normalized analytical parameter sweep, not GPU measurements or calibrated predictions",
        "layers": 36, "history_tokens_for_capacity_axis": 32768, "KV_MiB_per_layer": 128,
        "transfer_to_compute_ratios": [float(x) for x in RATIOS],
        "ratio_direction": "One layer historical KV transfer duration divided by one layer replay compute duration",
        "normalized_time_unit": "One layer replay compute duration; no absolute milliseconds are assigned to the plotted normalized events",
        "batch_layers_and_initial_resident_layers": list(range(1, 37)),
        "baseline": "Within each ratio, minimum no-Peer-backup total delay over batch sizes1..36; constant over the curve",
        "relative_gain": "Time saved as a percent of fixed no-backup total latency, including all 36 layers of compute and exposed loading wait",
        "pareto_objectives": ["minimize initial Peer HBM bytes", "maximize relative latency gain"],
        "pareto_scope": "Within each ratio only; changing the underlying workload or bandwidth is not ranked as a placement choice",
        "schedule": "Next batch only; whole-batch ready; actual final partial batch; already-loaded KV retained",
        "assumptions": ["uniform per-layer compute and transfer durations", "single compute and H2D streams without mutual slowdown",
                        "no transfer launch or fixed scheduling overhead", "sufficient recovery HBM to retain loaded KV",
                        "fixed recovery endpoint already has weights and can start replay"],
        "excluded_costs": ["failure detection", "takeover queue", "weight loading", "backup maintenance", "foreground interference"],
        "axis_direction": "Relative gain increases upward, as explicitly requested by the user",
        "placed_width_mm": 178, "placed_height_mm": 142,
    })
    sources = [PREVIOUS / "build_relative_benefit.py", PREVIOUS / "relative-benefit.csv",
               OUT.parent / "batched-layer-pipeline-20260914/build_batched_pipeline.py"]
    dump("MANIFEST.json", {
        "sources_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir())
                         if p.suffix in {".py", ".csv", ".json", ".png", ".pdf", ".svg", ".md"}
                         and p.name not in {"MANIFEST.json", "REVIEW.json", "figure-lesson.json"}},
    })
    print(json.dumps({"figure": "ratio-benefit.pdf", "ratios": 5, "candidates": 180,
                      "prior_conditions_matched_exactly": 252}))


if __name__ == "__main__":
    main()
