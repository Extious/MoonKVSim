"""Analytical six-layer KV pipeline. No model run or measured GPU timings.

Reproduce with: python3 output/pdf/batched-layer-pipeline-20260914/build_batched_pipeline.py
The initial prefix and each subsequent batch contain six layers. The next
batch is submitted when computation of the current batch starts. A batch is
consumed only after its complete historical KV has arrived. Copied KV is
retained; this is a scheduling lookahead bound, not a 12-layer capacity cap.
"""
from __future__ import annotations

import csv
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-batched-pipeline-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import Normalize
from matplotlib.patches import Patch, Rectangle
import numpy as np
import pymupdf

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
ORIGINAL = OUT.parent / "kv-motivation-20260913"
ATTACHMENT = Path("/home/comp/zhanzhao/.codex/attachments/794213d0-96d1-45eb-b781-0216c9934b5c/codex-clipboard-f0206bd6-7f42-4b63-89dc-d7a89038c6dc.png")
FONT = Path("/home/comp/zhanzhao/.local/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf")
font_manager.fontManager.addfont(FONT)
plt.rcParams.update({
    "font.family": font_manager.FontProperties(fname=FONT).get_name(),
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
    "axes.unicode_minus": False, "pdf.fonttype": 3, "svg.fonttype": "none",
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": .65,
})
BLUE, GREEN, ORANGE, PURPLE = "#0072B2", "#009E73", "#D55E00", "#8C5AA7"
MS, NS, BETAS = (4096, 8192, 16384, 32768), (128, 256, 512, 1024, 2048), (12.5, 25, 50)
LAYERS, BATCH, INITIAL = 36, 6, 6
KV_BYTES_PER_TOKEN_LAYER = 4096
LINEAR_WEIGHTS_PER_LAYER = 192937984


def layer_costs(m: int, n: int, beta: float):
    # Same dense, causal incremental-prefill FLOP and KV-byte model as the source.
    flops = 2 * n * LINEAR_WEIGHTS_PER_LAYER + 4 * 32 * 128 * (m*n + n*(n+1)//2)
    compute = Fraction(flops * 1000, 100_000_000_000_000)
    size = m * KV_BYTES_PER_TOKEN_LAYER
    transfer = Fraction(size * 1000, int(beta * 1_000_000_000))
    return compute, transfer, size


def schedule(c: Fraction, d: Fraction, layers: int = LAYERS, batch: int = BATCH):
    """Exact batch-gated event recurrence; initial resident layers equal batch."""
    assert layers > 0 and batch > 0 and c > 0 and d >= 0
    groups = [(i, min(i+batch-1, layers)) for i in range(1, layers+1, batch)]
    ready = [Fraction(0)] * len(groups)
    copies = [None] * len(groups)
    previous_compute_end = Fraction(0)
    events = []
    for idx, (first, last) in enumerate(groups):
        start = max(previous_compute_end, ready[idx])
        end = start + (last-first+1) * c
        if idx + 1 < len(groups):
            next_first, next_last = groups[idx+1]
            copy_end = start + (next_last-next_first+1) * d
            copies[idx+1] = (start, copy_end)
            ready[idx+1] = copy_end
        events.append({
            "batch_id": idx+1, "first_layer": first, "last_layer": last,
            "layer_count": last-first+1, "initially_resident": idx == 0,
            "copy_start_ms": None if copies[idx] is None else copies[idx][0],
            "copy_end_ms": None if copies[idx] is None else copies[idx][1],
            "batch_ready_ms": ready[idx], "wait_start_ms": previous_compute_end,
            "exposed_wait_ms": start-previous_compute_end,
            "compute_start_ms": start, "compute_end_ms": end,
        })
        previous_compute_end = end
    return events


def layer_reference(c: Fraction, d: Fraction, layers: int, batch: int):
    """Independent per-layer reconstruction with a whole-batch readiness gate."""
    finish = Fraction(0)
    group_start = Fraction(0)
    ready = {}
    events = []
    for layer in range(1, layers+1):
        first_of_group = (layer-1) % batch == 0
        if layer <= batch:
            available = Fraction(0)
        else:
            available = ready[(layer-1)//batch]
        start = max(finish, available)
        if first_of_group:
            group_start = start
            next_first = layer+batch
            if next_first <= layers:
                next_count = min(batch, layers-next_first+1)
                ready[(layer-1)//batch+1] = group_start + next_count*d
        events.append((layer, start, start+c, start-finish))
        finish = start+c
    return events


def exact_wait(events):
    return sum((x["exposed_wait_ms"] for x in events), Fraction(0))


def json_values(row):
    return {k: float(v) if isinstance(v, Fraction) else v for k, v in row.items()}


def write_csv(name, rows):
    with (OUT/name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export(fig, name):
    for suffix in ("png", "pdf", "svg"):
        fig.savefig(OUT/f"{name}.{suffix}", dpi=300, facecolor="white")
    plt.close(fig)
    with pymupdf.open(OUT/f"{name}.pdf") as doc:
        assert abs(doc[0].rect.width/72*25.4-178) < .01
        for dpi in (96, 150):
            doc[0].get_pixmap(dpi=dpi, alpha=False).save(OUT/f"{name}.pdf-{dpi}dpi.png")


def validate():
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location("original_cost_model", ORIGINAL/"build_motivation.py")
    original = module_from_spec(spec)
    spec.loader.exec_module(original)
    rows, all_events, all_layers = [], [], []
    for beta in BETAS:
        for m in MS:
            for n in NS:
                c, d, size = layer_costs(m, n, beta)
                assert (c, d, size) == original.layer_costs(m, n, beta)
                events = schedule(c, d)
                ref = layer_reference(c, d, LAYERS, BATCH)
                wait = exact_wait(events)
                assert events[-1]["compute_end_ms"] == ref[-1][2]
                assert wait == sum(x[3] for x in ref)
                assert wait == 30*max(d-c, 0)  # independent uniform-size check
                assert events[-1]["compute_end_ms"] == LAYERS*c+wait
                assert sum(x["layer_count"] for x in events[1:]) == 30
                for i in range(1, len(events)):
                    current, previous = events[i], events[i-1]
                    assert current["copy_start_ms"] == previous["compute_start_ms"]
                    assert current["compute_start_ms"] >= current["copy_end_ms"]
                    if i > 1:
                        assert current["copy_start_ms"] >= previous["copy_end_ms"]
                key = {"M": m, "N": n, "effective_bandwidth_GB_s_assumed": beta}
                rows.append({
                    **key, "initial_resident_layers": INITIAL, "batch_layers": BATCH,
                    "per_layer_compute_ms": float(c), "per_layer_load_ms": float(d),
                    "per_batch_compute_ms": float(BATCH*c), "per_batch_load_ms": float(BATCH*d),
                    "wait_per_boundary_ms": float(events[1]["exposed_wait_ms"]),
                    "wait_boundary_count": sum(x["exposed_wait_ms"] > 0 for x in events),
                    "total_exposed_wait_ms": float(wait), "total_compute_ms": float(LAYERS*c),
                    "total_pipeline_ms": float(events[-1]["compute_end_ms"]),
                    "zero_exposed_wait_exact": wait == 0,
                    "initial_HBM_MiB": INITIAL*size/2**20,
                    "loaded_history_MiB": (LAYERS-INITIAL)*size/2**20,
                    "final_history_MiB": LAYERS*size/2**20,
                    "new_KV_MiB": LAYERS*n*KV_BYTES_PER_TOKEN_LAYER/2**20,
                })
                all_events.extend({**key, **json_values(event)} for event in events)
                all_layers.extend({**key, "layer": x[0], "compute_start_ms": float(x[1]),
                                   "compute_end_ms": float(x[2]), "exposed_wait_ms": float(x[3])}
                                  for x in ref)
    # Hand-readable edge cases check equality, throughput deficit and final tails.
    fixtures = [
        (36, 6, 1, 2, 30), (36, 6, 2, 1, 0), (36, 6, 2, 2, 0),
        (36, 36, 1, 2, 0), (35, 6, 1, 2, 28), (3, 6, 1, 2, 0),
    ]
    for layers, batch, c, d, expected in fixtures:
        events = schedule(Fraction(c), Fraction(d), layers, batch)
        assert exact_wait(events) == expected
        assert events[-1]["compute_end_ms"] == layers*c+expected
    write_csv("batch-pipeline-grid.csv", rows)
    write_csv("batch-events.csv", all_events)
    write_csv("layer-events.csv", all_layers)
    return rows, {"parameter_states": 60, "physical_experiments": 0,
                  "statistical_replicates": None, "edge_cases": len(fixtures),
                  "costs_match_original_exactly": True,
                  "batch_and_layer_recurrences_agree_exactly": True,
                  "uniform_batch_wait_crosscheck_passed": True,
                  "single_copy_stream_and_readiness_checks_passed": True}


def make_main(rows):
    fig = plt.figure(figsize=(178/25.4, 170/25.4))
    fig.text(.085, .965, "每批六层流水加载：下一批能否及时就绪？", fontsize=12)
    fig.text(.085, .936, "解析估算，非实测｜Qwen3-8B，36 层｜假设有效算力 100 TFLOP/s", fontsize=8.5)
    fig.text(.085, .908, "初始驻留前 6 层；计算当前批时仅加载下一批；整批到齐后切换。", fontsize=8.5)
    fig.text(.085, .881, "热力图数字：36 层执行期间，五次批间切换的累计加载等待（ms）。", fontsize=8.5)
    locations = ((.115, .55, .36, .245), (.595, .55, .36, .245),
                 (.115, .202, .36, .245), (.595, .202, .36, .245))
    ax = fig.add_axes(locations[0])
    xx = np.geomspace(128, 2048, 160).astype(int)
    ax.plot(xx, [float(BATCH*layer_costs(32768, int(n), 25)[0]) for n in xx],
            color=GREEN, lw=1.7, label="6 层计算")
    for beta, style, color in zip(BETAS, (":", "-", "--"), ("#777777", BLUE, PURPLE)):
        ax.axhline(float(BATCH*layer_costs(32768, 512, beta)[1]),
                   color=color, ls=style, lw=1.1, label=f"6 层加载：{beta:g} GB/s")
    ax.set_xscale("log", base=2)
    ax.set_xticks(NS, [str(n) for n in NS], fontsize=8)
    ax.set_ylim(0, 125); ax.set_yticks([0, 30, 60, 90, 120])
    ax.set_xlabel("重放 token 数 N"); ax.set_ylabel("每批时间（ms）")
    ax.set_title("(a) 每批耗时，历史 M = 32K", loc="left", pad=10, fontsize=9.6)
    ax.legend(loc="upper left", fontsize=7.8, frameon=False, handlelength=1.6, labelspacing=.24)
    ax.grid(alpha=.14)
    im = None
    for idx, beta in enumerate(BETAS, 1):
        ax = fig.add_axes(locations[idx])
        arr = np.array([[next(r["total_exposed_wait_ms"] for r in rows
                            if r["M"] == m and r["N"] == n
                            and r["effective_bandwidth_GB_s_assumed"] == beta)
                         for n in NS] for m in MS])
        im = ax.imshow(arr, vmin=0, vmax=300, cmap="Blues", aspect="auto", origin="lower")
        for i, m in enumerate(MS):
            for j, n in enumerate(NS):
                value = arr[i, j]
                label = "0" if value == 0 else f"{value:.1f}"
                ax.text(j, i, label, ha="center", va="center", fontsize=9.5,
                        color="white" if value >= 170 else "#19384A")
        if beta == 25:
            ax.add_patch(Rectangle((1.5, 2.5), 1, 1, fill=False, edgecolor=ORANGE, lw=1.2))
        ax.set_xticks(range(len(NS)), [str(n) for n in NS], fontsize=8)
        ax.set_yticks(range(len(MS)), ["4K", "8K", "16K", "32K"])
        ax.set_xlabel("重放 token 数 N"); ax.set_ylabel("可复用历史 M")
        ax.set_title(f"({chr(97+idx)}) 有效带宽 {beta:g} GB/s", loc="left", pad=10)
    cax = fig.add_axes([.40, .107, .42, .012])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal", ticks=[0, 50, 100, 200, 300])
    cb.ax.tick_params(labelsize=8)
    fig.text(.115, .103, "累计加载等待（ms）", fontsize=8)
    fig.text(.085, .051, "框选例：32K 历史、重放 512 token、25 GB/s，累计等待 18.68 ms。", fontsize=8)
    fig.text(.085, .025, "0 表示全部批间加载被隐藏；算得更久虽更易隐藏加载，总执行时间仍可能增加。", fontsize=7.8)
    export(fig, "batched-layer-pipeline")


def make_timeline():
    c, d, size = layer_costs(32768, 512, 25)
    events = schedule(c, d)
    fig = plt.figure(figsize=(178/25.4, 95/25.4))
    fig.text(.075, .925, "前六层已驻留：计算一批，同时加载下一批", fontsize=11.5)
    fig.text(.075, .856, "解析时间线，非实测｜M = 32K，N = 512｜100 TFLOP/s，25 GB/s", fontsize=8.5)
    fig.text(.075, .791, "每批 6 层：计算 28.48 ms，加载 32.21 ms；整批就绪后切换。", fontsize=8.5)
    ax = fig.add_axes([.115, .30, .84, .32])
    for i, raw in enumerate(events):
        event = json_values(raw)
        start, end = event["compute_start_ms"], event["compute_end_ms"]
        label = f"{event['first_layer']}–{event['last_layer']}"
        ax.broken_barh([(start, end-start)], (.12, .50), facecolor=GREEN,
                      edgecolor="white", linewidth=.5)
        ax.text((start+end)/2, .37, label, ha="center", va="center", fontsize=8, color="white")
        if i:
            cs, ce = event["copy_start_ms"], event["copy_end_ms"]
            ax.broken_barh([(cs, ce-cs)], (1.07, .50), facecolor=BLUE,
                          edgecolor="white", linewidth=.5)
            ax.text((cs+ce)/2, 1.32, label, ha="center", va="center", fontsize=8, color="white")
            ax.broken_barh([(event["wait_start_ms"], event["exposed_wait_ms"])], (.12, .50),
                          facecolor=ORANGE, edgecolor="none", hatch="///")
            ax.plot([ce, ce], [.64, 1.06], color="#667785", linewidth=.7, ls=":")
    ax.set_xlim(0, 195); ax.set_ylim(-.1, 1.78)
    ax.set_xticks([0, 32.21, 64.42, 96.64, 128.85, 161.06, 189.54],
                  ["0", "32.21", "64.42", "96.64", "128.85", "161.06", "189.54"], fontsize=7.7)
    ax.set_yticks([.37, 1.32], ["计算", "加载"], fontsize=8.5)
    ax.set_xlabel("从恢复执行起点计时（ms）", fontsize=8.5, labelpad=5)
    ax.spines["left"].set_visible(False); ax.tick_params(axis="y", length=0)
    ax.legend(handles=[Patch(facecolor=GREEN, label="整层前向计算"), Patch(facecolor=BLUE, label="历史 KV 加载"),
                       Patch(facecolor=ORANGE, hatch="///", label="批间等待")],
              loc="lower left", bbox_to_anchor=(0, 1.12), frameon=False, ncol=3,
              fontsize=8, handlelength=1.3, columnspacing=1.5, borderaxespad=0)
    fig.text(.075, .132, "每次切换等待 3.74 ms，共五次；计算 170.86 ms，加等待后为 189.54 ms。", fontsize=8)
    fig.text(.075, .065, "初始历史 KV 768 MiB，后续加载 3840 MiB；条内数字是层号。", fontsize=8)
    export(fig, "batched-layer-timeline")


def main():
    rows, checks = validate()
    make_main(rows)
    make_timeline()
    parameters = {
        "evidence": "Deterministic analytical event schedule; not measured or calibrated",
        "model_geometry": {"model": "Qwen3-8B", "layers": LAYERS,
                           "hidden_size": 4096, "intermediate_size": 12288,
                           "query_heads": 32, "kv_heads": 8, "head_dim": 128,
                           "kv_element_bytes": 2, "tensor_parallelism": 1},
        "model_geometry_provenance": "Unchanged from 2026-09-13 source parameters.json; no new model run",
        "effective_compute_TFLOP_s_assumed": 100,
        "effective_bandwidth_GB_s_assumed": BETAS,
        "history_tokens": MS, "replayed_tokens": NS,
        "initial_resident_layers": INITIAL, "batch_layers": BATCH,
        "batch_count": 6, "batch_transition_count": 5,
        "schedule": {
            "initial_KV_ready_at_time_zero": True,
            "prefetch_submission": "Next batch at the start of current batch computation",
            "readiness": "All historical KV of a batch must be ready before its first layer computes",
            "lookahead": "One batch only; no submission of the batch after next",
            "transfer": "One serialized H2D stream, overlapping a serialized layer compute stream",
            "memory": "Keep copied history KV. Sufficient HBM for complete history plus new KV; not a two-buffer memory cap",
            "failure_relation": "Conditional recovery replay example; the overlap mechanism is not exclusive to failure",
        },
        "excluded_costs": ["failure detection", "takeover queue", "model weight loading", "transfer launch latency",
                           "copy/compute contention", "other requests", "norm/activation and non-GEMM kernel overhead"],
        "figure_width_mm": 178,
        "parameter_states": 60, "physical_experiments": 0, "statistical_replicates": None,
    }
    (OUT/"parameters.json").write_text(json.dumps(parameters, ensure_ascii=False, indent=2)+"\n")
    example = next(r for r in rows if r["M"] == 32768 and r["N"] == 512
                   and r["effective_bandwidth_GB_s_assumed"] == 25)
    (OUT/"validation.json").write_text(json.dumps({**checks, "highlighted_example": example}, ensure_ascii=False, indent=2)+"\n")
    sources = [ORIGINAL/"build_motivation.py", ORIGINAL/"parameters.json", ORIGINAL/"layer-depth-grid.csv", ATTACHMENT]
    manifest = {
        "sources_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir())
                         if p.suffix in (".py", ".csv", ".png", ".pdf", ".svg", ".json", ".md")
                         and p.name not in ("MANIFEST.json", "REVIEW.json", "figure-lesson.json")},
    }
    (OUT/"MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"checks": checks, "highlighted_example": example,
                      "figures": ["batched-layer-pipeline", "batched-layer-timeline"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
