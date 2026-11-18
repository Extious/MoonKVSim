"""Sweep batch size = initially resident prefix over all 1..36 layers.

Uses the unchanged cost model and whole-batch pipeline of the six-layer figure.
All results are deterministic analytical schedules, not hardware measurements.
"""
from __future__ import annotations

import csv
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
SOURCE = OUT.parent / "batched-layer-pipeline-20260914"
spec = importlib.util.spec_from_file_location("batch_base", SOURCE / "build_batched_pipeline.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle
import numpy as np
import pymupdf

MS, NS, BETAS = base.MS, base.NS, base.BETAS
BS = tuple(range(1, 37))
DISPLAY_BS = (1, 2, 3, 4, 6, 8, 9, 12, 18, 20, 24, 30, 36)
BLUE, GREEN, ORANGE = base.BLUE, base.GREEN, base.ORANGE


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_csv(name, rows):
    with (OUT / name).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export(fig, name):
    for suffix in ("png", "pdf", "svg"):
        fig.savefig(OUT / f"{name}.{suffix}", dpi=300, facecolor="white")
    plt.close(fig)
    with pymupdf.open(OUT / f"{name}.pdf") as pdf:
        assert abs(pdf[0].rect.width / 72 * 25.4 - 178) < .01
        for dpi in (96, 150):
            pdf[0].get_pixmap(dpi=dpi, alpha=False).save(OUT / f"{name}.pdf-{dpi}dpi.png")


def collect():
    rows, minima, event_rows, increases = [], [], [], []
    for m in MS:
        for beta in BETAS:
            for n in NS:
                c, d, size = base.layer_costs(m, n, beta)
                waits = {}
                for b in BS:
                    events = base.schedule(c, d, batch=b)
                    ref = base.layer_reference(c, d, 36, b)
                    wait = base.exact_wait(events)
                    finish = events[-1]["compute_end_ms"]
                    counts = [e["layer_count"] for e in events]
                    # Local pair-duration check is independent of event timestamps.
                    pairs = sum((max(counts[i]*d-counts[i-1]*c, 0)
                                 for i in range(1, len(counts))), Fraction(0))
                    assert wait == pairs == sum(x[3] for x in ref)
                    assert finish == 36*c+wait == ref[-1][2]
                    assert sum(counts) == 36 and counts[0] == b
                    assert all(e["compute_start_ms"] >= e["batch_ready_ms"] for e in events)
                    for i in range(1, len(events)):
                        assert events[i]["copy_start_ms"] == events[i-1]["compute_start_ms"]
                        if i > 1:
                            assert events[i]["copy_start_ms"] >= events[i-1]["copy_end_ms"]
                    if 36 % b == 0:
                        assert wait == (36-b)*max(d-c, 0)
                    waits[b] = wait
                    key = {"M": m, "N": n, "effective_bandwidth_GB_s_assumed": beta,
                           "batch_layers": b, "initial_resident_layers": b}
                    rows.append({
                        **key, "batch_partition": "+".join(map(str, counts)),
                        "batch_count": len(counts), "last_batch_layers": counts[-1],
                        "per_layer_compute_ms": float(c), "per_layer_load_ms": float(d),
                        "total_exposed_wait_ms": float(wait), "total_compute_ms": float(36*c),
                        "total_pipeline_ms": float(finish), "zero_exposed_wait_exact": wait == 0,
                        "initial_HBM_MiB": b*size/2**20,
                        "remaining_H2D_MiB": (36-b)*size/2**20,
                        "final_history_MiB": 36*size/2**20,
                    })
                    event_rows.extend({**key, **base.json_values(e)} for e in events)
                minimum = next(b for b in BS if waits[b] == 0)
                if c >= d:
                    expected = 1
                else:
                    ratio = 36*d/(c+d)
                    expected = -(-ratio.numerator // ratio.denominator)
                assert minimum == expected
                assert all(waits[b] == 0 for b in BS if b >= minimum)
                minima.append({"M": m, "N": n, "effective_bandwidth_GB_s_assumed": beta,
                               "minimum_zero_wait_batch_layers": minimum,
                               "initial_HBM_at_zero_wait_MiB": minimum*size/2**20,
                               "initial_HBM_at_zero_wait_GiB": minimum*size/2**30})
                for b in BS[:-1]:
                    if waits[b+1] > waits[b]:
                        increases.append({"M": m, "N": n, "effective_bandwidth_GB_s_assumed": beta,
                                          "from_batch": b, "to_batch": b+1,
                                          "from_wait_ms": float(waits[b]), "to_wait_ms": float(waits[b+1])})
    lookup = {(r["M"], r["N"], r["effective_bandwidth_GB_s_assumed"], r["batch_layers"]): r for r in rows}
    with (SOURCE / "batch-pipeline-grid.csv").open() as f:
        old_rows = list(csv.DictReader(f))
    assert len(old_rows) == 60
    for old in old_rows:
        new = lookup[int(old["M"]), int(old["N"]), float(old["effective_bandwidth_GB_s_assumed"]), 6]
        assert new["total_exposed_wait_ms"] == float(old["total_exposed_wait_ms"])
        assert new["total_pipeline_ms"] == float(old["total_pipeline_ms"])
    write_csv("batch-size-sweep.csv", rows)
    write_csv("minimum-zero-wait-batch.csv", minima)
    write_csv("batch-events.csv", event_rows)
    write_csv("nonmonotonic-adjacent-cases.csv", increases)
    examples = [lookup[32768, 512, 25, b] for b in (6, 8, 9, 12, 19, 20, 36)]
    checks = {"analytical_parameter_states": len(rows), "cost_states": len(minima),
              "batch_sizes_per_cost_state": 36, "physical_experiments": 0,
              "independent_statistical_replicates": None,
              "exact_batch_and_layer_recurrences_agree": True,
              "exact_batch_pair_duration_crosscheck": True,
              "minimum_zero_wait_crosscheck": True,
              "original_six_layer_states_matched": len(old_rows),
              "nonmonotonic_adjacent_cases_retained": len(increases),
              "examples_32K_512_25GBps": examples}
    dump("validation.json", checks)
    return rows, minima, lookup, checks


def main_heatmaps(lookup):
    fig = plt.figure(figsize=(178/25.4, 151/25.4))
    fig.text(.065, .955, "批大小、重放长度与带宽共同影响加载等待", fontsize=11.5)
    fig.text(.065, .922, "解析估算，非实测｜Qwen3-8B，36 层｜历史 32K｜假设 100 TFLOP/s", fontsize=8.2)
    fig.text(.065, .889, "每批层数与初始 Peer HBM 驻留层数相同；每层历史 KV 占 128 MiB。", fontsize=8.2)
    fig.text(.065, .856, "仅预取下一批；整批就绪后切换；末批保留实际层数。格内单位：ms。", fontsize=8.2)
    im = None
    for idx, beta in enumerate(BETAS):
        ax = fig.add_axes([.105 + .30*idx, .275, .25, .495])
        arr = np.array([[lookup[32768, n, beta, b]["total_exposed_wait_ms"] for n in NS] for b in DISPLAY_BS])
        im = ax.imshow(arr, vmin=0, vmax=350, cmap="Blues", aspect="auto", origin="upper")
        for i, b in enumerate(DISPLAY_BS):
            for j, n in enumerate(NS):
                v = arr[i, j]
                ax.text(j, i, "0" if v == 0 else f"{v:.1f}", ha="center", va="center",
                        fontsize=7.9, color="white" if v >= 195 else "#19384A")
        ax.set_xticks(range(5), [str(n) for n in NS], fontsize=7.8)
        ax.set_yticks(range(len(DISPLAY_BS)), [str(b) for b in DISPLAY_BS] if idx == 0 else [])
        ax.set_xlabel("重放 token 数", fontsize=8.3, labelpad=5)
        if idx == 0:
            ax.set_ylabel("每批层数 / 初始驻留层数", fontsize=8.5, labelpad=6)
        ax.set_title(f"({chr(97+idx)}) {beta:g} GB/s", loc="left", fontsize=9.5, pad=11)
        ax.add_patch(Rectangle((-.49, DISPLAY_BS.index(6)-.49), 4.98, .98,
                               fill=False, edgecolor=ORANGE, lw=.85))
    cbax = fig.add_axes([.39, .161, .43, .014])
    cb = fig.colorbar(im, cax=cbax, orientation="horizontal", ticks=[0, 50, 100, 200, 350])
    cb.ax.tick_params(labelsize=8)
    fig.text(.105, .158, "累计加载等待（ms）", fontsize=8)
    fig.text(.065, .106, "框选行对应原图的 6 层设置；36 层表示全部历史已驻留，没有后续加载。", fontsize=8)
    fig.text(.065, .072, "本图列出代表批大小；实际扫描 1–36 层。增大批次也增加了初始驻留容量。", fontsize=8)
    fig.text(.065, .038, "固定历史与重放长度时，计算量不随批大小变化；本图不能比较不同重放的总耗时。", fontsize=8)
    export(fig, "batch-size-bandwidth-replay")


def minimum_heatmaps(minima):
    data = {(r["M"], r["N"], r["effective_bandwidth_GB_s_assumed"]): r for r in minima}
    fig = plt.figure(figsize=(178/25.4, 112/25.4))
    fig.text(.065, .940, "多少层一批，才能消除后续加载等待？", fontsize=11.5)
    fig.text(.065, .882, "每格：零等待的最小每批层数，同时也是初始 Peer HBM 驻留层数。", fontsize=8.5)
    fig.text(.065, .827, "解析估算，非实测｜Qwen3-8B，36 层｜100 TFLOP/s｜整批就绪后切换", fontsize=8.1)
    im = None
    for idx, beta in enumerate(BETAS):
        ax = fig.add_axes([.105 + .30*idx, .335, .25, .365])
        arr = np.array([[data[m, n, beta]["minimum_zero_wait_batch_layers"] for n in NS] for m in MS])
        im = ax.imshow(arr, vmin=1, vmax=36, cmap="Blues", aspect="auto", origin="lower")
        for i, m in enumerate(MS):
            for j, n in enumerate(NS):
                v = arr[i, j]
                ax.text(j, i, str(v), ha="center", va="center", fontsize=9.5,
                        color="white" if v >= 23 else "#19384A")
        ax.set_xticks(range(5), [str(n) for n in NS], fontsize=7.8)
        ax.set_yticks(range(4), ["4K", "8K", "16K", "32K"] if idx == 0 else [])
        ax.set_xlabel("重放 token 数", fontsize=8.3, labelpad=5)
        if idx == 0:
            ax.set_ylabel("可复用历史", fontsize=8.5)
        ax.set_title(f"({chr(97+idx)}) {beta:g} GB/s", loc="left", fontsize=9.5, pad=11)
    cax = fig.add_axes([.39, .197, .43, .018])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal", ticks=[1, 6, 12, 18, 24, 36])
    cb.ax.tick_params(labelsize=8)
    fig.text(.105, .196, "最小每批层数", fontsize=8)
    fig.text(.065, .112, "32K 历史、重放 512 token：三种带宽分别需要 25、20、1 层。", fontsize=8)
    fig.text(.065, .063, "这是当前调度下的零等待门槛，未计备份成本与前台容量竞争，不是系统最优配额。", fontsize=7.8)
    export(fig, "minimum-zero-wait-batch")


def detail_curves(lookup):
    selected = (6, 8, 9, 12, 20)
    fig = plt.figure(figsize=(178/25.4, 124/25.4))
    fig.text(.065, .947, "批次并非越大越好：末批大小会改变等待", fontsize=11.5)
    fig.text(.065, .892, "固定历史 32K、重放 512 token、25 GB/s｜解析估算，非实测｜100 TFLOP/s", fontsize=8.1)
    ax = fig.add_axes([.105, .400, .36, .35])
    waits = [lookup[32768, 512, 25, b]["total_exposed_wait_ms"] for b in BS]
    ax.plot(BS, waits, color=BLUE, marker="o", markersize=2.3, lw=1.1)
    ax.scatter(selected, [lookup[32768, 512, 25, b]["total_exposed_wait_ms"] for b in selected],
               color=ORANGE, s=19, zorder=4)
    ax.set_xlim(0, 37); ax.set_ylim(-1.0, 25)
    ax.set_xticks([1, 6, 12, 18, 24, 30, 36]); ax.set_yticks([0, 5, 10, 15, 20, 25])
    ax.tick_params(labelsize=8)
    ax.set_xlabel("每批层数 / 初始驻留层数", fontsize=8.4)
    ax.set_ylabel("累计加载等待（ms）", fontsize=8.4)
    ax.set_title("(a) 完整扫描 1–36 层", loc="left", fontsize=9.5, pad=10)
    ax.grid(alpha=.16)
    ax.annotate("20 层\n首次零等待", xy=(20, 0), xytext=(27, 8), fontsize=7.6,
                ha="center", arrowprops={"arrowstyle":"->", "lw":.7, "color":"#526678"})
    ax = fig.add_axes([.605, .400, .35, .35])
    compute = [lookup[32768, 512, 25, b]["total_compute_ms"] for b in selected]
    wait = [lookup[32768, 512, 25, b]["total_exposed_wait_ms"] for b in selected]
    ax.bar(range(5), compute, color=GREEN, width=.60)
    ax.bar(range(5), wait, bottom=compute, color=ORANGE, width=.60, hatch="///")
    for i, b in enumerate(selected):
        ax.text(i, compute[i]+wait[i]+4, f"{compute[i]+wait[i]:.2f}", ha="center", fontsize=7.8)
    ax.set_ylim(0, 218); ax.set_yticks([0, 50, 100, 150, 200]); ax.tick_params(labelsize=8)
    ax.set_xticks(range(5), [f"{b}\n{b*128}" for b in selected], fontsize=8)
    ax.set_xlabel("上：每批层数；下：初始 HBM（MiB）", fontsize=7.6)
    ax.set_ylabel("执行时间（ms）", fontsize=8.4)
    ax.set_title("(b) 计算量不变，等待发生变化", loc="left", fontsize=9.3, pad=10)
    fig.legend(handles=[Patch(facecolor=GREEN, label="整层前向计算"),
                        Patch(facecolor=ORANGE, hatch="///", label="加载等待")],
               loc="center", bbox_to_anchor=(.77, .829), ncol=2, frameon=False, fontsize=8,
               handlelength=1.2, columnspacing=1.0)
    fig.text(.065, .264, "8 层一批：8 + 8 + 8 + 8 + 4；末批较短，累计等待 14.95 ms。", fontsize=8.4)
    fig.text(.065, .213, "9 层一批：9 + 9 + 9 + 9；末批也是整批，累计等待增至 16.81 ms。", fontsize=8.4)
    fig.text(.065, .145, "本例每层历史 KV 为 128 MiB；6 层占 768 MiB，20 层占 2560 MiB。", fontsize=8.1)
    fig.text(.065, .092, "增大批大小同时增加初始驻留、减少待加载量；这些变化不能都归因于流水粒度。", fontsize=7.9)
    fig.text(.065, .039, "各点均保留实际尾批与精确等待；曲线连接整数批大小，不平滑、不填充整批。", fontsize=7.9)
    export(fig, "batch-size-detail")


def main():
    rows, minima, lookup, checks = collect()
    main_heatmaps(lookup)
    minimum_heatmaps(minima)
    detail_curves(lookup)
    parameters = json.loads((SOURCE / "parameters.json").read_text())
    parameters.update({"batch_layers": list(BS), "initial_resident_layers": list(BS),
                       "coupling": "Initial resident prefix length equals batch size for every configuration",
                       "batch_count": "Variable; last batch uses actual remaining layer count",
                       "batch_transition_count": "Variable",
                       "parameter_states": len(rows), "main_figure_history_tokens": 32768,
                       "displayed_batch_sizes_main": DISPLAY_BS,
                       "threshold_states": len(minima),
                       "one_history_layer_MiB_by_M": {str(m): m*4096/2**20 for m in MS},
                       "byte_budget_comparison": "Not an equal-budget comparison across batch sizes; capacity and schedule vary together",
                       "minimum_metric": "Smallest integer batch size from 1 to 36 with exactly zero exposed waiting in this schedule"})
    dump("parameters.json", parameters)
    source_paths = [SOURCE / name for name in ("build_batched_pipeline.py", "parameters.json", "batch-pipeline-grid.csv", "batched-layer-pipeline.pdf")]
    dump("MANIFEST.json", {
        "source_files_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
        "files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir())
                         if p.suffix in {".py", ".csv", ".json", ".png", ".pdf", ".svg", ".md"}
                         and p.name not in {"MANIFEST.json", "REVIEW.json", "figure-lesson.json"}},
    })
    print(json.dumps({"parameter_states": len(rows), "threshold_states": len(minima),
                      "nonmonotonic_cases": checks["nonmonotonic_adjacent_cases_retained"],
                      "figures": ["batch-size-bandwidth-replay", "minimum-zero-wait-batch", "batch-size-detail"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
