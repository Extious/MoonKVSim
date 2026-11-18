"""Corrected initial-prefix placement with continuous layer-wise H2D and compute.

Only initial residency k changes. No runtime batch size or whole-batch barrier.
The fixed baseline uses the identical per-layer scheduler with k=0.
"""
from __future__ import annotations

import csv
from fractions import Fraction as F
import hashlib
import importlib.util
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ORIGINAL = OUT.parent / "kv-motivation-20260913/build_motivation.py"
OLD_RATIO = OUT.parent / "batched-layer-ratio-benefit-20260914"
OLD_REAL = OUT.parent / "batched-layer-relative-benefit-20260914"
spec = importlib.util.spec_from_file_location("original_layerwise", ORIGINAL)
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pymupdf

LAYERS, MIB_PER_LAYER = 36, 128
RATIOS = (F(1, 2), F(1), F(5, 4), F(2), F(4))
CONDITIONS = ((512, 12.5), (512, 25), (512, 50), (128, 25), (256, 25), (1024, 25), (2048, 25))
GREEN, TEAL, BLUE, PURPLE, ORANGE = "#009E73", "#596F78", "#0072B2", "#8C5AA7", "#D55E00"
COLORS = (GREEN, TEAL, BLUE, PURPLE, ORANGE)
STYLES = (":", (0, (5, 1, 1, 1)), "--", "-.", "-")


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def write_csv(name, rows):
    with (OUT / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def schedule(c, d, k):
    """One serial H2D stream starts at t=0 and never waits for compute batches."""
    assert 0 <= k <= LAYERS and c > 0 and d > 0
    copy_end, compute_end = F(0), F(0)
    events = []
    for layer in range(1, LAYERS + 1):
        resident = layer <= k
        copy_start = None if resident else copy_end
        if not resident:
            copy_end += d
        ready = F(0) if resident else copy_end
        compute_start = max(compute_end, ready)
        events.append({
            "layer": layer, "initially_resident": resident,
            "copy_start": copy_start, "copy_end": None if resident else copy_end,
            "ready": ready, "compute_start": compute_start,
            "compute_end": compute_start + c, "wait": compute_start - compute_end,
        })
        compute_end = compute_start + c
    # Independent max-plus critical-path expansion from all readiness deadlines.
    critical_path = max([LAYERS * c] + [e["ready"] + (LAYERS-e["layer"]+1)*c for e in events])
    assert compute_end == critical_path
    assert compute_end == LAYERS*c + sum(e["wait"] for e in events)
    assert copy_end == (LAYERS-k)*d
    assert sum(e["initially_resident"] for e in events) == k
    return events


def curve(c, d):
    baseline_events = schedule(c, d, 0)
    baseline = baseline_events[-1]["compute_end"]
    rows = []
    for k in range(LAYERS+1):
        events = baseline_events if k == 0 else schedule(c, d, k)
        total = events[-1]["compute_end"]
        rows.append({"k": k, "total": total, "wait": sum(e["wait"] for e in events),
                     "baseline": baseline, "gain": 100*(baseline-total)/baseline, "events": events})
    best = None
    for p in rows:
        p["dominated_by"] = [q["k"] for q in rows if q["k"] < p["k"] and q["total"] <= p["total"]]
        p["pareto"] = not p["dominated_by"]
        record = best is None or p["gain"] > best
        assert record == p["pareto"]
        if record:
            best = p["gain"]
    for p, q in zip(rows, rows[1:]):
        assert q["total"] <= p["total"] and q["gain"] >= p["gain"]
        for e, f in zip(p["events"], q["events"]):
            assert f["ready"] <= e["ready"] and f["compute_end"] <= e["compute_end"]
    assert rows[0]["gain"] == 0 and rows[-1]["wait"] == 0
    first_zero = next(p["k"] for p in rows if p["wait"] == 0)
    assert [p["k"] for p in rows if p["pareto"]] == list(range(first_zero+1))
    return rows


def data():
    ratio_curves, real_curves, public, event_rows, summaries = {}, {}, [], [], []
    cases = [("ratio", str(r), F(1), r, None, None) for r in RATIOS]
    cases += [("bandwidth_replay", f"N{n}_BW{bw:g}", *original.layer_costs(32768, n, bw)[:2], n, bw)
              for n, bw in CONDITIONS]
    for family, label, c, d, n, bw in cases:
        rows = curve(c, d)
        ratio = d/c
        if family == "ratio":
            ratio_curves[ratio] = rows
            for scale in (F(1, 10), F(4), F(10)):
                scaled = curve(c*scale, d*scale)
                for p, q in zip(rows, scaled):
                    assert p["gain"] == q["gain"] and p["pareto"] == q["pareto"]
                    assert q["total"] == p["total"]*scale
        else:
            real_curves[n, bw] = rows
            normalized = curve(F(1), ratio)
            for p, q in zip(rows, normalized):
                old_events, old_total, _ = original.timeline(32768, n, p["k"], bw)
                assert p["total"] == old_total
                assert p["gain"] == q["gain"] and p["pareto"] == q["pareto"]
                for e, old in zip(p["events"], old_events):
                    assert float(e["compute_start"]) == old["compute_start_ms"]
                    assert float(e["wait"]) == old["exposed_wait_ms"]
                    assert (None if e["copy_start"] is None else float(e["copy_start"])) == old["copy_start_ms"]
        first_zero = next(p["k"] for p in rows if p["wait"] == 0)
        unit = "one_layer_compute" if family == "ratio" else "ms"
        summaries.append({"family": family, "condition": label, "transfer_to_compute_ratio": float(ratio),
                          "replay_tokens": n, "H2D_GB_s_assumed": bw, "time_unit": unit,
                          "baseline_total": float(rows[0]["baseline"]), "per_layer_compute": float(c),
                          "per_layer_transfer": float(d), "first_saturation_prefix_layers": first_zero,
                          "maximum_gain_percent": float(rows[first_zero]["gain"]),
                          "pareto_prefix_layers": [p["k"] for p in rows if p["pareto"]]})
        for p in rows:
            identity = {"family": family, "condition": label, "initial_prefix_layers": p["k"], "time_unit": unit}
            public.append({**identity, "ratio_exact": str(ratio), "transfer_to_compute_ratio": float(ratio),
                           "initial_Peer_HBM_MiB": p["k"]*MIB_PER_LAYER,
                           "remaining_H2D_MiB": (LAYERS-p["k"])*MIB_PER_LAYER,
                           "per_layer_compute": float(c), "per_layer_transfer": float(d),
                           "total_compute": float(LAYERS*c), "total_exposed_wait": float(p["wait"]),
                           "total_delay": float(p["total"]), "zero_backup_baseline": float(p["baseline"]),
                           "relative_gain_percent": float(p["gain"]),
                           "gain_exact_numerator": p["gain"].numerator, "gain_exact_denominator": p["gain"].denominator,
                           "pareto_within_condition": p["pareto"],
                           "dominated_by_prefix_layers": ";".join(map(str, p["dominated_by"]))})
            event_rows.extend({**identity, **{key: float(v) if isinstance(v, F) else v for key, v in e.items()}}
                              for e in p["events"])
    # Quantify the correction. Historical batched outputs remain provenance only.
    comparisons = []
    for folder, filename, family in ((OLD_RATIO, "ratio-benefit.csv", "ratio"),
                                     (OLD_REAL, "relative-benefit.csv", "bandwidth_replay")):
        with (folder / filename).open() as f:
            for old in csv.DictReader(f):
                k = int(old["batch_layers"])
                if family == "ratio":
                    r = F(old["ratio_exact"])
                    p = ratio_curves[r][k]
                    label, old_total, old_base, old_gain = (str(r), float(old["protected_total_normalized"]),
                        float(old["fixed_zero_backup_baseline_normalized"]), float(old["relative_latency_gain_percent"]))
                else:
                    n, bw = int(old["replay_tokens"]), float(old["H2D_GB_s_assumed"])
                    p = real_curves[n, bw][k]
                    label, old_total, old_base, old_gain = (f"N{n}_BW{bw:g}", float(old["protected_total_ms"]),
                        float(old["common_zero_backup_total_ms"]), float(old["relative_gain_percent_common_baseline"]))
                assert float(p["baseline"]) == old_base
                assert float(p["total"]) <= old_total + 1e-10
                comparisons.append({"family": family, "condition": label, "initial_prefix_layers": k,
                    "historical_batched_total": old_total, "corrected_layerwise_total": float(p["total"]),
                    "historical_batched_gain_percent": old_gain, "corrected_layerwise_gain_percent": float(p["gain"]),
                    "baseline_unchanged": True})
    assert ratio_curves[F(2)][8]["total"] == 57 and ratio_curves[F(2)][9]["total"] == 55
    assert [next(p["k"] for p in ratio_curves[r] if p["wait"] == 0) for r in RATIOS] == [1, 1, 8, 19, 28]
    assert len(public) == 444 and len(event_rows) == 15984 and len(comparisons) == 432
    write_csv("prefix-benefit.csv", public)
    write_csv("layer-events.csv", event_rows)
    write_csv("historical-batch-comparison.csv", comparisons)
    dump("curve-summaries.json", summaries)
    dump("validation.json", {
        "ratio_conditions": 5, "bandwidth_replay_conditions": 7,
        "unique_initial_prefix_states_including_zero": 444, "layer_events": 15984,
        "critical_path_and_serial_event_recurrence_agree": True,
        "all_prefix_increments_have_nondecreasing_gain_and_nonincreasing_delay": True,
        "every_layer_ready_and_finish_deadline_is_nondegrading_with_more_backup": True,
        "exact_pareto_status_matches_record_gains": True,
        "ratio_scale_invariance_checks": 555,
        "original_continuous_layerwise_states_matched_exactly": 259,
        "real_conditions_map_to_normalized_ratios_exactly": True,
        "old_batched_comparisons_with_unchanged_baselines": 432,
        "old_batched_latency_is_never_better_for_the_same_prefix": True,
        "ratio_2_prefix_8_total": 57, "ratio_2_prefix_9_total": 55,
        "physical_runs": 0, "statistical_replicates": None,
    })
    return ratio_curves, real_curves


def axes(ax, ymax, ticks, wide=True):
    ax.set_xlim(-1, 37); ax.set_ylim(-.035*ymax, ymax)
    ax.set_xticks([0, 6, 12, 18, 24, 30, 36]); ax.set_yticks(ticks)
    ax.tick_params(labelsize=9 if wide else 8)
    ax.set_xlabel("初始在 Peer HBM 备份的前层数", fontsize=9.3 if wide else 8.3, labelpad=6)
    ax.set_ylabel("相对无备份的总延迟降低（%）", fontsize=9.3 if wide else 8.5)
    ax.set_axisbelow(True); ax.grid(alpha=.15)
    top = ax.secondary_xaxis("top", functions=(lambda x: x*MIB_PER_LAYER, lambda x: x/MIB_PER_LAYER))
    k_ticks = [0, 6, 12, 18, 24, 30, 36] if wide else [0, 12, 24, 36]
    top.set_xticks([k*MIB_PER_LAYER for k in k_ticks]); top.tick_params(labelsize=8.5 if wide else 7.5, pad=3)
    return top


def draw(ax, series):
    for rows, color, style, label in series:
        ax.plot([p["k"] for p in rows], [float(p["gain"]) for p in rows], color=color, ls=style, lw=1.2, zorder=1)
    for keep in (False, True):
        for rows, color, style, label in series:
            points = [p for p in rows if p["pareto"] == keep and p["k"] > 0]
            ax.scatter([p["k"] for p in points], [float(p["gain"]) for p in points],
                       color=color, marker="o" if keep else "x", s=22 if keep else 10,
                       linewidths=.4 if keep else .65, alpha=1 if keep else .43,
                       zorder=4 if keep else 2, **({"edgecolors": "white"} if keep else {}))
    ax.scatter([0], [0], color="#526574", marker="o", s=22, zorder=5)


def marker_legend(fig, y, size=8.5):
    fig.legend(handles=[Line2D([], [], color=BLUE, marker="o", linestyle="none", markersize=4.5,
                               label="实心圆：该曲线内的帕累托点"),
                        Line2D([], [], color="#8B929A", marker="x", linestyle="none", markersize=4.5,
                               label="叉号：被支配点")],
               loc="center", bbox_to_anchor=(.51, y), ncol=2, frameon=False, fontsize=size,
               columnspacing=1.8, handlelength=1.1)


def series_legend(ax, series, title=None, size=8.5):
    ax.legend(handles=[Line2D([], [], color=c, ls=s, lw=1.3, label=label) for _, c, s, label in series],
              title=title, title_fontsize=size-.2, loc="upper left", fontsize=size, frameon=False,
              handlelength=2.6, labelspacing=.35)


def export(fig, name):
    for ext in ("png", "pdf", "svg"):
        fig.savefig(OUT / f"{name}.{ext}", dpi=300, facecolor="white")
    plt.close(fig)
    with pymupdf.open(OUT / f"{name}.pdf") as pdf:
        assert abs(pdf[0].rect.width/72*25.4-178) < .01
        for dpi in (96, 150):
            pdf[0].get_pixmap(dpi=dpi, alpha=False).save(OUT / f"{name}.pdf-{dpi}dpi.png")


def render_ratio(curves):
    fig = plt.figure(figsize=(178/25.4, 142/25.4))
    fig.text(.065, .943, "逐层流水下，初始前层备份的相对收益", fontsize=12)
    fig.text(.065, .908, "解析估算，非实测｜36 层｜各层耗时一致｜每层历史 KV 为 128 MiB", fontsize=8.5)
    fig.text(.065, .871, "逐层连续传输、逐层就绪后计算；每条曲线以相同调度下的 0 层备份作为基线。", fontsize=8.2)
    marker_legend(fig, .829)
    ax = fig.add_axes([.11, .250, .835, .458])
    top = axes(ax, 85, [0, 20, 40, 60, 80]); top.set_xlabel("初始 Peer HBM 占用（MiB）", fontsize=9, labelpad=6)
    series = [(curves[r], c, s, f"{float(r):g} 倍") for r, c, s in zip(RATIOS, COLORS, STYLES)]
    draw(ax, series); series_legend(ax, series, "单层传输耗时为计算的")
    for r, color in zip(RATIOS[2:], COLORS[2:]):
        p = next(p for p in curves[r] if p["wait"] == 0)
        ax.text(36, float(p["gain"])+2.2, f"{p['k']} 层起：{float(p['gain']):.2f}%", color=color,
                fontsize=8.3, ha="right", va="bottom")
    ax.text(.54, .145, "传输不慢于计算时，从 1 层起：\n"
            f"0.5 倍：{float(curves[F(1,2)][1]['gain']):.2f}%；1 倍：{float(curves[F(1)][1]['gain']):.2f}%",
            transform=ax.transAxes, fontsize=8.4, color="#526574", linespacing=1.5)
    ax.text(.54, .40, "1.25、2、4 倍的上升段接近重合。", transform=ax.transAxes,
            fontsize=8.1, color="#526574")
    fig.text(.065, .139, "横轴仅改变初始驻留层数；收益越往上越好，增加备份层数时收益上升或持平。", fontsize=8.2)
    fig.text(.065, .101, "H2D 从恢复起点连续复制未驻留层；该层 KV 到齐且前一层算完，即可计算该层。", fontsize=8.15)
    fig.text(.065, .063, "总延迟包含全部重放计算与加载等待；假设缓冲充足、复制与计算无争用，未经硬件校准。", fontsize=8.15)
    export(fig, "layerwise-ratio-benefit")


def render_conditions(curves):
    fig = plt.figure(figsize=(178/25.4, 185/25.4))
    fig.text(.065, .957, "逐层流水下的备份收益：带宽与重放长度", fontsize=11.3)
    fig.text(.065, .933, "解析估算，非实测｜Qwen3-8B，36 层｜历史 32K｜假设有效算力 100 TFLOP/s", fontsize=8)
    fig.text(.065, .904, "基线：相同带宽与重放工作量，初始 0 层备份；两侧均逐层计算、按层连续传输。", fontsize=8)
    fig.text(.065, .875, "上横轴为初始 Peer HBM（MiB），每层 128 MiB；下横轴仅为初始备份前层数。", fontsize=7.8)
    marker_legend(fig, .843, 8)
    fig.text(.065, .803, "(a) 基准：25 GB/s，512 token", fontsize=9.4)
    fig.text(.580, .803, "(b) H2D 带宽对比：512 token", fontsize=9.4)
    ax = fig.add_axes([.105, .545, .35, .207]); axes(ax, 16, [0, 4, 8, 12, 16], False)
    rows = curves[512, 25]; draw(ax, [(rows, BLUE, "-", "512 token")])
    first = next(p for p in rows if p["wait"] == 0)
    ax.annotate(f"{first['k']} 层起：{float(first['gain']):.2f}%\n此后收益持平", xy=(first["k"], float(first["gain"])),
                xytext=(.62, .46), textcoords="axes fraction", ha="center", fontsize=7.6,
                arrowprops={"arrowstyle": "->", "lw": .65, "color": "#8B929A"})
    ax.text(.10, .08, f"无备份：{float(rows[0]['baseline']):.2f} ms", transform=ax.transAxes, fontsize=7.3, color="#526574")
    ax = fig.add_axes([.605, .545, .35, .207]); axes(ax, 65, [0, 15, 30, 45, 60], False)
    bw_series = [(curves[512, 12.5], ORANGE, "-", "12.5 GB/s"), (curves[512, 25], BLUE, "--", "25 GB/s"),
                 (curves[512, 50], GREEN, ":", "50 GB/s")]
    draw(ax, bw_series); series_legend(ax, bw_series, size=8)
    fig.text(.065, .467, "(c) 重放 token 数对比：H2D 带宽固定为 25 GB/s", fontsize=9.7)
    ax = fig.add_axes([.105, .175, .85, .247]); axes(ax, 85, [0, 20, 40, 60, 80])
    replay = [(curves[128, 25], ORANGE, "-", "128 token"), (curves[256, 25], PURPLE, "-.", "256 token"),
              (curves[512, 25], BLUE, "--", "512 token"), (curves[1024, 25], GREEN, ":", "1024 token"),
              (curves[2048, 25], TEAL, STYLES[1], "2048 token")]
    draw(ax, replay); series_legend(ax, replay, size=8)
    ax.text(.55, .29, "从 1 层备份起，两条长重放曲线保持：\n"
            f"1024 token：{float(curves[1024,25][1]['gain']):.2f}%；2048 token：{float(curves[2048,25][1]['gain']):.2f}%",
            transform=ax.transAxes, fontsize=7.8, color="#526574", linespacing=1.5)
    fig.text(.065, .090, "纵轴越往上收益越好；0 层点为无备份基线，各条件的帕累托集合分别计算。", fontsize=7.9)
    fig.text(.065, .060, "恢复开始即连续复制未驻留层；每层 KV 就绪且前一层计算完成后即可执行。", fontsize=7.8)
    fig.text(.065, .031, "总延迟计入重放计算和加载等待；不含故障检测、接管排队、权重加载、备份维护与争用。", fontsize=7.65)
    export(fig, "layerwise-relative-benefit")


def main():
    ratios, conditions = data()
    render_ratio(ratios); render_conditions(conditions)
    dump("parameters.json", {
        "user_correction":"8 or9 layers are initial HBM residency only; real compute and KV transfers proceed one layer at a time",
        "initial_prefix_layers":list(range(37)), "layers":36, "history_tokens_for_capacity":32768,
        "KV_MiB_per_layer":128, "ratio_values":[float(r) for r in RATIOS],
        "conditions":[{"replay_tokens":n,"H2D_GB_s_assumed":bw} for n,bw in CONDITIONS],
        "runtime_batch_size":None,"whole_batch_barrier":False,
        "transfer":"At t=0 start copying first nonresident layer; each next copy starts at previous copy completion",
        "compute":"Each layer starts after its own historical KV is ready and previous layer compute completes",
        "baseline":"Exactly the same continuous layer-wise scheduler with zero initial HBM prefix; fixed per condition",
        "lookahead":"No group limit; one active H2D transfer at a time, already copied KV retained",
        "saturation":"Smallest prefix with zero exposed wait; subsequent prefixes are dominated at the same maximum benefit",
        "time_units":"One layer compute for abstract ratios; milliseconds for model-derived bandwidth/replay cases",
        "assumptions":["uniform layer costs","sufficient HBM buffer","no launch overhead","no compute/transfer slowdown"],
        "time_exclusions":["failure detection","takeover queue","weight loading","backup maintenance"],
        "evidence":"Analytical and uncalibrated, no GPU run","gain_axis":"increases upward",
        "figure_sizes_mm":{"ratio":[178,142],"bandwidth_replay":[178,185]},
    })
    sources=[ORIGINAL,OLD_RATIO/"ratio-benefit.csv",OLD_REAL/"relative-benefit.csv"]
    dump("MANIFEST.json", {
        "sources_sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "files_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir())
            if p.suffix in {".py",".csv",".json",".png",".pdf",".svg",".md"}
            and p.name not in {"MANIFEST.json","REVIEW.json","figure-lesson.json"}},
    })
    print(json.dumps({"states":444,"ratio_saturation_prefixes":[1,1,8,19,28],
                      "reference_saturation_prefix":next(p["k"] for p in conditions[512,25] if p["wait"]==0)}))


if __name__ == "__main__":
    main()
