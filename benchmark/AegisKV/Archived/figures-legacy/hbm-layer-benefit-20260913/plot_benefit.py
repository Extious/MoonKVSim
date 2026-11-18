"""Reproduce the analytical figure and verify formulas against event schedules.

This script evaluates equations on the CPU; it does not benchmark inference or H2D.
"""
from __future__ import annotations

import csv
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
import fitz
import numpy as np

HERE = Path(__file__).resolve().parent
PARAMS = json.loads((HERE / "parameters.json").read_text())
L = PARAMS["layers"]
POLICIES = ("next_layer", "early_prefetch")


def schedule(layers, c, d, k, policy):
    """Independent event recurrence, returning the actual modeled layer events."""
    compute_free = 0
    copy_free = 0
    previous_compute_start = 0
    events = []
    for layer in range(1, layers + 1):
        ready = 0
        copy_start = None
        if layer > k:
            release = previous_compute_start if policy == "next_layer" else 0
            copy_start = max(copy_free, release)
            ready = copy_start + d
            copy_free = ready
        start = max(compute_free, ready)
        end = start + c
        events.append({
            "layer": layer, "resident_at_start": layer <= k,
            "copy_start": copy_start, "copy_end": ready if layer > k else None,
            "compute_start": start, "compute_end": end,
        })
        previous_compute_start = start
        compute_free = end
    return compute_free, events


def baseline(layers, c, d):
    return layers * c + d + (layers - 1) * max(d - c, 0)


def saved(layers, c, d, k, policy):
    if k == 0:
        return 0
    gap = max(d - c, 0)
    if policy == "next_layer":
        return d + (k - 1) * gap
    return min(k * d, d + (layers - 1) * gap)


def saturation_k(layers, c, d, policy):
    if c >= d:
        return 1
    if policy == "next_layer":
        return layers
    return math.ceil((d + (layers - 1) * (d - c)) / d)


def verify_algebra():
    checked = 0
    for layers in (1, 2, 3, 8, 32, 36):
        for d in (Fraction(1, 10), Fraction(1), Fraction(7, 2)):
            for ratio in (Fraction(0), Fraction(1, 10), Fraction(1, 4),
                          Fraction(1, 2), Fraction(3, 4), Fraction(99, 100),
                          Fraction(1), Fraction(101, 100), Fraction(2), Fraction(10)):
                c = ratio * d
                t0 = baseline(layers, c, d)
                last_saving = dict.fromkeys(POLICIES, Fraction(-1))
                for k in range(layers + 1):
                    times = {}
                    for policy in POLICIES:
                        actual, events = schedule(layers, c, d, k, policy)
                        delta = saved(layers, c, d, k, policy)
                        assert actual == t0 - delta, (layers, c, d, k, policy)
                        assert sum(e["compute_end"]-e["compute_start"] for e in events) == layers*c
                        assert sum(e["copy_start"] is not None for e in events) == layers-k
                        assert layers*c <= actual <= t0
                        assert last_saving[policy] <= delta
                        last_saving[policy] = delta
                        times[policy] = actual
                        checked += 1
                    assert times["early_prefetch"] <= times["next_layer"]
                for policy in POLICIES:
                    star = saturation_k(layers, c, d, policy)
                    assert schedule(layers, c, d, star, policy)[0] == layers*c
                    if star > 0:
                        assert schedule(layers, c, d, star-1, policy)[0] > layers*c
    return {"exact_rational_schedule_cases": checked, "result": "passed",
            "checks": ["closed form versus independent event recurrence", "boundary C=0, C=D, L=1",
                       "all-layer computation conserved", "L-k transfers", "monotonic benefit",
                       "early prefetch never slower", "minimal saturation k"]}


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    verification = verify_algebra()
    rows = []
    for ratio in PARAMS["C_over_D_series"]:
        for k in range(L+1):
            for policy in POLICIES:
                t0 = baseline(L, ratio, 1)
                delta = saved(L, ratio, 1, k, policy)
                rows.append({"L": L, "C_over_D": ratio, "normalized_gap_D_minus_C_over_D": 1-ratio,
                             "k": k, "policy": policy, "T0_over_D": t0,
                             "Tk_over_D": t0-delta, "saved_over_D": delta,
                             "reduction_percent": 100*delta/t0,
                             "saturation_k": saturation_k(L, ratio, 1, policy)})
    write_csv(HERE / "benefit-sweep.csv", rows)

    example = []
    event_rows = []
    for k in (0, 1, 4, 8, 16, 19, 24, 36):
        for policy in POLICIES:
            c, d = PARAMS["example_only_C_ms"], PARAMS["example_only_D_ms"]
            duration, events = schedule(L, c, d, k, policy)
            t0 = baseline(L, c, d)
            example.append({"k": k, "policy": policy, "C_ms_assumed": c, "D_ms_assumed": d,
                            "T0_ms": t0, "Tk_ms": duration, "saved_ms": t0-duration,
                            "reduction_percent": 100*(t0-duration)/t0})
            event_rows += [{"k": k, "policy": policy, **event} for event in events]
    write_csv(HERE / "illustrative-times.csv", example)
    write_csv(HERE / "illustrative-layer-events.csv", event_rows)

    font = Path("/home/comp/zhanzhao/.local/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf")
    font_manager.fontManager.addfont(font)
    plt.rcParams.update({
        "font.family": font_manager.FontProperties(fname=font).get_name(),
        "font.size": 9, "axes.unicode_minus": False,
        "pdf.fonttype": 3, "svg.fonttype": "none",
        "axes.labelsize": 9.5, "axes.titlesize": 10, "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
    })
    width, height = PARAMS["figure_size_mm"]
    fig = plt.figure(figsize=(width/25.4, height/25.4), facecolor="white")
    axes = [fig.add_axes([.12, .275, .375, .43]), fig.add_axes([.60, .275, .375, .43])]
    colors = ["#0072B2", "#D55E00", "#009E73", "#A64D8B", "#525B67"]
    markers = ["^", "o", "s", "D", "x"]
    styles = ["-", "--", "-.", ":", (0, (5, 2, 1, 2))]
    kvals = np.arange(L+1)
    legend = []
    for i, ratio in enumerate(PARAMS["C_over_D_series"]):
        for ax, policy in zip(axes, POLICIES):
            ys = [100*saved(L, ratio, 1, int(k), policy)/baseline(L, ratio, 1) for k in kvals]
            ax.plot(kvals, ys, color=colors[i], linestyle=styles[i], marker=markers[i],
                    markevery=[0,1,6,12,18,24,30,36], markersize=3.6,
                    linewidth=1.5, markerfacecolor="white", markeredgewidth=.9,
                    label=f"C/D = {ratio:g}")
        legend.append(Line2D([0], [0], color=colors[i], linestyle=styles[i],
                            marker=markers[i], markersize=4, markerfacecolor="white",
                            label=f"C/D = {ratio:g}"))
        if ratio < 1:
            star = saturation_k(L, ratio, 1, "early_prefetch")
            cap = 100*saved(L, ratio, 1, L, "early_prefetch")/baseline(L, ratio, 1)
            axes[1].scatter([star], [cap], s=38, facecolors="white", edgecolors=colors[i], zorder=5)
            axes[1].text(35.4, cap+2.0, f"k* = {star}", color=colors[i], fontsize=8, ha="right")
    for ax in axes:
        ax.set_xlim(-.8, L+.8)
        ax.set_ylim(-1, 84)
        ax.set_xticks([0,6,12,18,24,30,36])
        ax.set_yticks([0,20,40,60,80])
        ax.set_xlabel("HBM 连续保留的前 k 层", labelpad=6)
        ax.set_axisbelow(True)
        ax.grid(axis="y", color="#DDE1E5", linewidth=.6)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color("#8D959D")
            ax.spines[side].set_linewidth(.6)
        ax.tick_params(length=3, width=.6)
    axes[0].set_ylabel("恢复加前向耗时减少（%）", labelpad=6)
    axes[0].set_title("(a) 严格只预取下一层", loc="left", pad=9)
    axes[1].set_title("(b) 从起点提前预取后续层", loc="left", pad=9)
    fig.text(.035, .93, "HBM 层数的收益：C/D 与预取范围共同决定", fontsize=12, color="#172B3A")
    fig.text(.035, .899, "L = 36；C：N 个 token 的单层前向；D：M 个历史 token 的单层 KV H2D。", fontsize=8.7)
    fig.text(.035, .859, r"收益 = $(T_0 - T_k)/T_0$；各 C/D 使用各自 k = 0 的基线。", fontsize=9)
    fig.legend(handles=legend, loc="center", bbox_to_anchor=(.51,.789), frameon=False,
               ncol=3, fontsize=8.5, handlelength=2.8, columnspacing=1.6, labelspacing=.55)
    fig.text(.035, .15, "(a) 首层省 D；之后每层省 max(D−C, 0)。", fontsize=9)
    fig.text(.035, .102, "(b) 需在 t=0 启动第 k+1 层 H2D，并允许连续预取；圆圈标出饱和层数。", fontsize=8.5)
    fig.text(.035, .048, "解析曲线，非实测；假设等时层、充足预取空间和无竞争；N 个 token 仍计算全部层。", fontsize=8.2, color="#52606D")
    outputs = []
    for ext in ("png", "pdf", "svg"):
        path = HERE / f"hbm-layer-benefit.{ext}"
        fig.savefig(path, dpi=300, facecolor="white")
        outputs.append(path.name)
    plt.close(fig)

    review_dir = HERE / "review"
    review_dir.mkdir(exist_ok=True)
    doc = fitz.open(HERE / "hbm-layer-benefit.pdf")
    page = doc[0]
    assert abs(page.rect.width*25.4/72-width) < .01
    assert abs(page.rect.height*25.4/72-height) < .01
    previews = []
    for name, dpi, gray in (("pdf-168mm-96dpi.png",96,False),
                            ("pdf-168mm-144dpi.png",144,False),
                            ("pdf-grayscale-168mm-144dpi.png",144,True)):
        path = review_dir / name
        page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY if gray else fitz.csRGB).save(path)
        previews.append(str(path.relative_to(HERE)))
    spans = [s for block in page.get_text("dict")["blocks"] if "lines" in block
             for line in block["lines"] for s in line["spans"]]
    outside = [s["text"] for s in spans if not page.rect.contains(fitz.Rect(s["bbox"]))]
    assert not outside, outside
    summary = {"evidence_type": PARAMS["evidence_type"], "physical_experiments": 0,
               "independent_replicates": None, "plotted_scenarios": len(rows),
               "statistical_unit": "not applicable; points are deterministic parameter evaluations",
               "verification": verification, "placed_size_mm": [width,height],
               "min_extracted_font_pt": min(s["size"] for s in spans),
               "pdf_text_outside_page": outside, "visual_review": "pending",
               "outputs": outputs, "rendered_previews": previews,
               "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in HERE.iterdir() if p.is_file() and p.name != "REVIEW.json"}}
    (HERE / "REVIEW.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"verification":verification, "plotted_scenarios":len(rows),
                      "outputs":outputs, "example":example},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
