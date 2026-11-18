"""Reproducible analytical figures; no model execution or measured timings."""
from __future__ import annotations

import csv
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-kv-motivation-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np
import pymupdf

OUT = Path(__file__).resolve().parent
FONT = Path("/home/comp/zhanzhao/.local/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf")
font_manager.fontManager.addfont(FONT)
TITLE_WEIGHT = "normal"
if FONT.with_name("NotoSansCJKsc-Bold.otf").exists():
    font_manager.fontManager.addfont(FONT.with_name("NotoSansCJKsc-Bold.otf"))
    TITLE_WEIGHT = "bold"
plt.rcParams.update({
    "font.family": font_manager.FontProperties(fname=FONT).get_name(),
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
    "axes.unicode_minus": False, "pdf.fonttype": 3, "svg.fonttype": "none",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": .65,
})
BLUE, GREEN, ORANGE, PURPLE, GRAY = "#0072B2", "#009E73", "#D55E00", "#8C5AA7", "#E8EDF2"
CONFIG = {
    "model": "Qwen3-8B", "layers": 36, "hidden_size": 4096,
    "intermediate_size": 12288, "query_heads": 32, "kv_heads": 8,
    "head_dim": 128, "kv_element_bytes": 2, "tp": 1,
    "effective_compute_TFLOP_s_ASSUMED": 100,
    "effective_transfer_GB_s_ASSUMED": 25,
    "model_config_url": "https://huggingface.co/Qwen/Qwen3-8B/raw/main/config.json",
    "config_checked_on": "2026-09-13",
    "evidence": "Analytical example, not model execution or hardware measurement",
    "physical_experiments": 0, "statistical_replicates": None,
    "figure_width_mm": 178,
}
L = CONFIG["layers"]
KV_PER_TOKEN_LAYER = 2 * CONFIG["kv_heads"] * CONFIG["head_dim"] * CONFIG["kv_element_bytes"]
H, Q, G, d, I = (CONFIG[k] for k in ("hidden_size", "query_heads", "kv_heads", "head_dim", "intermediate_size"))
LINEAR_WEIGHTS = H * (Q * d + 2 * G * d) + Q * d * H + 3 * H * I
assert LINEAR_WEIGHTS == 192937984 and KV_PER_TOKEN_LAYER == 4096


def layer_costs(m: int, n: int, beta: float = 25):
    flops = 2 * n * LINEAR_WEIGHTS + 4 * Q * d * (m * n + n * (n + 1) // 2)
    c = Fraction(flops * 1000, 100_000_000_000_000)
    size = m * KV_PER_TOKEN_LAYER
    transfer = Fraction(size * 1000, int(beta * 1_000_000_000))
    return c, transfer, size


def timeline(m: int, n: int, k: int, beta: float = 25):
    c, dtime, size = layer_costs(m, n, beta)
    finish = copy_end = Fraction(0)
    events = []
    for layer in range(1, L + 1):
        resident = layer <= k
        copy_start = None if resident else copy_end
        if not resident:
            copy_end += dtime
        ready = Fraction(0) if resident else copy_end
        start = max(finish, ready)
        events.append({
            "M": m, "N": n, "k": k, "beta_GB_s": beta, "layer": layer,
            "reused_history_tokens": m, "replayed_tokens": n,
            "initial_peer_hbm_bytes": size if resident else 0,
            "h2d_bytes": 0 if resident else size,
            "copy_start_ms": None if resident else float(copy_start),
            "copy_end_ms": None if resident else float(copy_end),
            "kv_ready_ms": float(ready), "wait_start_ms": float(finish),
            "exposed_wait_ms": float(start - finish),
            "compute_start_ms": float(start), "compute_end_ms": float(start + c),
            "compute_ms": float(c),
        })
        finish = start + c
    w0 = dtime + (L - 1) * max(dtime - c, 0)
    predicted = L * c + max(w0 - k * dtime, 0)
    assert finish == predicted
    return events, finish, w0


def depth(m: int, n: int, beta: float):
    c, dtime, size = layer_costs(m, n, beta)
    w0 = dtime + (L - 1) * max(dtime - c, 0)
    ratio = w0 / dtime
    ksat = -(-ratio.numerator // ratio.denominator)
    assert 1 <= ksat <= L
    return ksat, c, dtime, size


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
        assert abs(pdf[0].rect.width / 72 * 25.4 - 178) < .02
        pdf[0].get_pixmap(matrix=pymupdf.Matrix(1.7, 1.7), alpha=False).save(OUT / f"{name}.pdf-preview.png")


def make_profile():
    m, n = 32768, 512
    c, dtime, size = layer_costs(m, n)
    traces = {k: timeline(m, n, k)[0] for k in (0, 6)}
    write_csv("fixed-retry-layer-events.csv", [r for rows in traces.values() for r in rows])
    fig = plt.figure(figsize=(178 / 25.4, 208 / 25.4))
    fig.text(.09, .969, "前层驻留到底消除了哪些等待？", fontsize=12, weight=TITLE_WEIGHT)
    fig.text(.09, .942, "解析估算，非实测｜Qwen3-8B｜M = 32768，N = 512｜固定接管 DP", fontsize=8.5)
    fig.text(.09, .917, f"每层历史 KV：128 MiB；计算 C = {float(c):.3f} ms；H2D D = {float(dtime):.3f} ms", fontsize=8.5)
    fig.text(.18, .870, "(a) 故障时的放置：前缀覆盖相同，每格是一层", fontsize=10)
    ax = fig.add_axes([.18, .757, .76, .079])
    ax.imshow([[0] * L, [1] * 6 + [0] * 30], cmap=ListedColormap([GRAY, PURPLE]),
              aspect="auto", vmin=0, vmax=1, interpolation="none", extent=(.5, L + .5, 1.5, -.5))
    ax.set_yticks([0, 1], ["HBM 0 MiB", "HBM 768 MiB"], fontsize=8)
    ax.set_xticks([1, 6, 12, 18, 24, 30, 36])
    ax.set_xticks(np.arange(.5, 37), minor=True)
    ax.grid(which="minor", axis="x", color="white", linewidth=.7)
    ax.tick_params(which="minor", length=0)
    ax.set_xlabel("层号", labelpad=2)
    ax.legend(handles=[Patch(facecolor=PURPLE, label="Peer HBM"), Patch(facecolor=GRAY, label="DRAM")],
              loc="lower left", bbox_to_anchor=(0, 1.05), ncol=2, frameon=False, fontsize=8, borderaxespad=0)
    fig.text(.18, .657, "(b) 同一时钟上的复制与计算：36 层全部画出", fontsize=10)
    ax = fig.add_axes([.18, .373, .76, .234])
    levels = {0: (3.30, 2.55), 6: (1.25, .50)}
    for k, rows in traces.items():
        copy_y, compute_y = levels[k]
        for row in rows:
            if row["h2d_bytes"]:
                ax.broken_barh([(row["copy_start_ms"], float(dtime))], (copy_y, .42),
                               facecolor=BLUE, edgecolor="white", linewidth=.28)
            if row["exposed_wait_ms"] > 0:
                ax.broken_barh([(row["wait_start_ms"], row["exposed_wait_ms"])], (compute_y, .42),
                               facecolor=ORANGE, edgecolor="none")
            ax.broken_barh([(row["compute_start_ms"], float(c))], (compute_y, .42),
                           facecolor=GREEN, edgecolor="white", linewidth=.28)
        end = rows[-1]["compute_end_ms"]
        ax.text(end + 2, compute_y + .55, f"{end:.2f} ms", fontsize=8, ha="right")
        ax.text(2, copy_y + .55, f"H2D 总量 {(L-k)*128} MiB", fontsize=8, color=BLUE)
    ax.set_yticks([3.51, 2.76, 1.46, .71], ["全 DRAM：复制", "全 DRAM：计算", "前 6 层：复制", "前 6 层：计算"], fontsize=8)
    ax.set_xlim(0, 210); ax.set_ylim(.20, 4.40)
    ax.set_xticks([0, 50, 100, 150, 200])
    ax.set_xlabel("从恢复执行开始计时（ms）")
    ax.set_axisbelow(True); ax.grid(axis="x", alpha=.18)
    ax.legend(handles=[Patch(facecolor=BLUE, label="H2D"), Patch(facecolor=GREEN, label="计算"),
                       Patch(facecolor=ORANGE, label="暴露等待")], loc="lower left", bbox_to_anchor=(0, 1.03),
              ncol=3, fontsize=8, frameon=False, borderaxespad=0)
    fig.text(.18, .281, "(c) 逐层阻塞分解：重用 KV 不会省掉 N 个 token 的计算", fontsize=9.5)
    ax = fig.add_axes([.18, .139, .76, .105])
    for k, color, marker, label in ((0, ORANGE, "o", "全 DRAM"), (6, PURPLE, "s", "前 6 层 HBM")):
        ax.plot(np.arange(1, L + 1), [r["exposed_wait_ms"] for r in traces[k]],
                color=color, marker=marker, markersize=2.7, linewidth=1.1, label=label)
    ax.set_xlim(.5, 36.5); ax.set_ylim(-.28, 6)
    ax.set_xticks([1, 6, 12, 18, 24, 30, 36]); ax.set_yticks([0, 2, 4, 6])
    ax.set_ylabel("等待（ms）"); ax.set_xlabel("层号", labelpad=2)
    ax.legend(loc="upper right", ncol=2, frameon=False, fontsize=8)
    fig.text(.09, .070, "两组均计算 170.86 ms；全 DRAM 暴露等待 27.16 ms，前 6 层驻留后为 0。", fontsize=8.5)
    fig.text(.09, .044, "100 TFLOP/s、25 GB/s 为假设；从 t = 0 连续预取，整层就绪后开始计算。", fontsize=8)
    fig.text(.09, .021, "恢复后历史 KV 占 4608 MiB，新增 KV 占 72 MiB；不含权重、激活和其他请求。", fontsize=8)
    export(fig, "fixed-retry-profile")


def make_depth_map():
    ms, ns, betas = [4096, 8192, 16384, 32768], [128, 256, 512, 1024, 2048], [12.5, 25, 50]
    rows = []
    for beta in betas:
        for m in ms:
            for n in ns:
                ksat, c, dtime, size = depth(m, n, beta)
                for k in range(L + 1):
                    timeline(m, n, k, beta)
                rows.append({"M": m, "N": n, "beta_GB_s_ASSUMED": beta, "C_ms": float(c),
                             "D_ms": float(dtime), "k_sat": ksat, "hbm_at_saturation_MiB": ksat * size / 2**20})
    write_csv("layer-depth-grid.csv", rows)
    fig = plt.figure(figsize=(178 / 25.4, 163 / 25.4))
    fig.text(.09, .971, "需要多少前层，取决于实际恢复计算与传输之比", fontsize=11.5, weight=TITLE_WEIGHT)
    fig.text(.09, .941, "解析估算，非实测｜Qwen3-8B 结构｜有效算力固定假设为 100 TFLOP/s", fontsize=8.5)
    fig.text(.09, .913, r"$k_{\rm sat}$：在连续预取模型中消除全部装入等待的最少前层数", fontsize=9)
    locations = [(.12, .555, .35, .25), (.60, .555, .35, .25), (.12, .174, .35, .25), (.60, .174, .35, .25)]
    ax = fig.add_axes(locations[0])
    xx = np.geomspace(128, 2048, 160).astype(int)
    ax.plot(xx, [float(layer_costs(32768, int(n))[0]) for n in xx], color=GREEN, lw=1.8, label="C：每层计算")
    for beta, style, color in zip(betas, (":", "-", "--"), ("#777777", BLUE, PURPLE)):
        y = float(layer_costs(32768, 512, beta)[1])
        ax.axhline(y, color=color, ls=style, lw=1.1, label=f"D：{beta:g} GB/s")
    ax.set_xscale("log", base=2); ax.set_xticks(ns, [str(x) for x in ns], fontsize=8)
    ax.set_ylim(0, 21); ax.set_yticks([0, 5, 10, 15, 20])
    ax.set_xlabel("丢失并重放的 token 数 N"); ax.set_ylabel("每层时间（ms）")
    ax.set_title("(a) 固定 M = 32768", loc="left", pad=10)
    ax.legend(loc="upper left", fontsize=8, frameon=False, handlelength=1.7, labelspacing=.23)
    ax.grid(alpha=.12)
    im = None
    for idx, beta in enumerate(betas, 1):
        ax = fig.add_axes(locations[idx])
        arr = np.array([[depth(m, n, beta)[0] for n in ns] for m in ms])
        im = ax.imshow(arr, vmin=1, vmax=36, cmap="Blues", aspect="auto", origin="lower")
        for i in range(len(ms)):
            for j in range(len(ns)):
                ax.text(j, i, str(arr[i, j]), ha="center", va="center", fontsize=10,
                        color="white" if arr[i, j] >= 23 else "#19384A", weight=TITLE_WEIGHT)
        ax.set_xticks(range(len(ns)), [str(x) for x in ns], fontsize=8)
        ax.set_yticks(range(len(ms)), ["4K", "8K", "16K", "32K"])
        ax.set_xlabel("丢失并重放的 token 数 N")
        ax.set_ylabel("可复用历史 M")
        ax.set_title(f"({chr(97+idx)}) 有效带宽 {beta:g} GB/s", loc="left", pad=10)
    cax = fig.add_axes([.37, .082, .40, .012])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal", ticks=[1, 6, 12, 24, 36])
    cb.ax.tick_params(labelsize=8); fig.text(.12, .075, "驻留层数", fontsize=8.5)
    fig.text(.09, .018, "同样只放 6 层：短重放仍可能等待；长重放较易隐藏传输，但总延迟改善可能很小。", fontsize=8)
    export(fig, "layer-depth-motivation")


def make_sparse_counterexample():
    queries, blocks, per_query = 16, 32, 4
    stable = np.zeros((queries, blocks), dtype=int)
    rotating = stable.copy()
    stable[:, [4, 5, 20, 21]] = 1
    for q in range(queries):
        rotating[q, (2 * q + np.arange(per_query)) % blocks] = 1
    assert np.all(stable.sum(1) == 4) and np.all(rotating.sum(1) == 4)
    assert stable.sum() == rotating.sum() == 64
    arrays = {"stable": stable, "rotating": rotating}
    write_csv("sparse-constructed-selections.csv", [
        {"case": name, "query": q + 1, "physical_history_block": b + 1, "selected": int(arr[q, b]),
         "evidence": "constructed_counterexample_not_native_model_trace"}
        for name, arr in arrays.items() for q in range(queries) for b in range(blocks)
    ])
    fig = plt.figure(figsize=(178 / 25.4, 164 / 25.4))
    fig.text(.09, .970, "每个 Query 都很稀疏，恢复工作集仍可能很大", fontsize=11.5, weight=TITLE_WEIGHT)
    fig.text(.09, .940, "构造反例，非模型轨迹｜单层、单 KV 组｜每个 Query 都选择 4 / 32 个历史块", fontsize=8.3)
    for idx, (name, arr) in enumerate(arrays.items()):
        ax = fig.add_axes([.12 + idx * .48, .558, .35, .268])
        color = PURPLE if name == "stable" else BLUE
        ax.imshow(arr, interpolation="none", aspect="auto", cmap=ListedColormap(["#F0F3F6", color]),
                  vmin=0, vmax=1, extent=(.5, blocks + .5, queries + .5, .5))
        ax.set_xticks([1, 8, 16, 24, 32]); ax.set_yticks([1, 4, 8, 12, 16])
        ax.set_xlabel("物理历史 KV 块的位置"); ax.set_ylabel("恢复 Query")
        title = "(a) 相同 4 块反复使用" if name == "stable" else "(b) 选块随 Query 改变"
        ax.set_title(title, loc="left", pad=13)
    fig.text(.12, .886, "颜色表示本例需要的块：两例满足同一稀疏预算，均不来自模型运行。", fontsize=8.3)
    fig.text(.12, .472, "不按 attention mass 计 I/O：一个块装入后留在 HBM，不会每次访问都重新 H2D。", fontsize=8.2)
    ax = fig.add_axes([.12, .177, .35, .205])
    for name, color, marker, label in (("stable", PURPLE, "s", "相同 4 块"), ("rotating", BLUE, "o", "变化选块")):
        arr = arrays[name]
        union = np.maximum.accumulate(arr, axis=0).sum(1)
        ax.plot(range(1, queries + 1), union, color=color, marker=marker, markersize=3, lw=1.3, label=label)
    ax.set_title("(c) 截至当前需要的不同块数", loc="left", pad=12)
    ax.set_xticks([1, 4, 8, 12, 16]); ax.set_yticks([0, 4, 16, 32]); ax.set_ylim(0, 35)
    ax.set_xlabel("恢复 Query"); ax.set_ylabel("历史需求并集大小")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.grid(alpha=.14)
    ax = fig.add_axes([.64, .177, .31, .205])
    labels = ["相同 4 块", "变化选块"]
    base = [int(stable.any(0).sum()), int(rotating.any(0).sum())]
    chosen = [v - 4 for v in base]
    y = np.arange(2)
    ax.barh(y + .16, base, height=.29, color="#D8DFE7", label="HBM 0 块")
    ax.barh(y - .16, chosen, height=.29, color=GREEN, label="HBM 4 块")
    for idx in range(2):
        ax.text(base[idx] + .5, idx + .16, str(base[idx]), va="center", fontsize=8)
        ax.text(chosen[idx] + .5, idx - .16, str(chosen[idx]), va="center", fontsize=8)
    ax.set_yticks(y, labels, fontsize=8); ax.set_xticks([0, 8, 16, 24, 32]); ax.set_xlim(0, 36)
    ax.set_ylim(-.52, 1.70)
    ax.set_title("(d) 仍需从 DRAM 首次装入", loc="left", pad=12, fontsize=9.5)
    ax.set_xlabel("整个窗口的首次加载块数")
    ax.legend(loc="upper left", bbox_to_anchor=(0, 1.02), fontsize=8, ncol=2, frameon=False,
              handlelength=1, columnspacing=.8, borderaxespad=0)
    fig.text(.09, .083, "HBM 均预放 4 块：左例可免去全部 4 次冷加载；右例仍需 28 次冷加载。", fontsize=8.5)
    fig.text(.09, .054, "假设加载后不逐出、无推测性加载；这里只数主 KV，辅助状态和暴露等待须另算。", fontsize=8)
    fig.text(.09, .025, "因此，真实 Motivation 需给出恢复窗口的选块集中性；不能用单 Query 稀疏率替代。", fontsize=8)
    export(fig, "sparse-window-counterexample")


def make_native_window():
    m, n, window, chunk = 32768, 512, 512, 64
    history_blocks = m // chunk
    query = np.arange(1, n + 1)[:, None]
    last_history_token = np.arange(1, history_blocks + 1)[None, :] * chunk
    # A previous-token window contains [M+i-w, M+i-1]. Intersect it with [1,M].
    needed = (last_history_token >= m + query - window).astype(int)
    count = needed.sum(0)
    assert needed[0].sum() == 8 and np.count_nonzero(count) == 8
    assert count[-8:].tolist() == [64, 128, 192, 256, 320, 384, 448, 512]
    write_csv("native-window-analytical-block-counts.csv", [
        {"history_block": b + 1, "first_token": b * chunk + 1, "last_token": (b + 1) * chunk,
         "query_count_needing_block": int(count[b]), "M": m, "N": n, "window": window,
         "evidence": "derived_fixed_window_branch_only_not_model_measurement"}
        for b in range(history_blocks)
    ])
    fig = plt.figure(figsize=(178 / 25.4, 162 / 25.4))
    fig.text(.09, .967, "原生局部窗口：少量历史 KV 被重复访问的可证明情形", fontsize=11, weight=TITLE_WEIGHT)
    fig.text(.09, .935, "窗口分支的解析结果，非实测｜M = 32768，N = 512，w = 512｜物理块 64 token", fontsize=8.3)
    fig.text(.15, .872, "(a) 全部历史：只有最后 512 个 token 会被此窗口分支访问", fontsize=9.5)
    ax = fig.add_axes([.15, .770, .79, .067])
    ax.barh([0], [m], height=.8, color=GRAY)
    ax.barh([0], [window], left=[m-window], height=.8, color=PURPLE)
    ax.set_xlim(0, m); ax.set_yticks([]); ax.set_xticks([0, 8192, 16384, 24576, 32768])
    ax.set_xlabel("历史 token 位置", labelpad=2)
    fig.text(.63, .816, "窗口历史仅占 1.5625%", fontsize=8, ha="center")
    fig.text(.15, .649, "(b) 放大末尾 12 个物理块：有色格表示该 Query 需要该块", fontsize=9.4)
    ax = fig.add_axes([.15, .410, .79, .205])
    ax.imshow(needed[:, -12:], interpolation="none", aspect="auto", cmap=ListedColormap([GRAY, PURPLE]),
              vmin=0, vmax=1, extent=(500.5, 512.5, n+.5, .5))
    ax.set_xticks(range(501, 513)); ax.set_yticks([1, 128, 256, 384, 512])
    ax.set_xlabel("物理历史块编号（全历史共 512 块）"); ax.set_ylabel("恢复 Query 偏移 i")
    fig.text(.15, .315, "(c) 同一物理块被需要的次数，与首次 H2D 次数不同", fontsize=9.5)
    ax = fig.add_axes([.15, .180, .79, .095])
    xx = np.arange(501, 513)
    ax.bar(xx, count[-12:], width=.72, color=PURPLE)
    ax.set_xlim(500.5, 512.5); ax.set_ylim(0, 600); ax.set_xticks(xx); ax.set_yticks([0, 256, 512])
    ax.set_ylabel("Query 次数"); ax.set_xlabel("物理历史块编号", labelpad=2)
    for x, y in zip(xx, count[-12:]):
        if y: ax.text(x, y + 14, str(y), ha="center", fontsize=8)
    fig.text(.09, .070, "首个 Query 已需要这 8 块；加载后不逐出时，每块至多首次加载一次。", fontsize=8.2)
    fig.text(.09, .039, "NSA 还需要压缩与选择分支；1.5625% 只描述窗口历史，不能当作全模型恢复预算。", fontsize=8)
    export(fig, "native-window-structural-example")


def main():
    (OUT / "parameters.json").write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2) + "\n")
    make_profile(); make_depth_map(); make_sparse_counterexample(); make_native_window()
    examples = []
    for n in (128, 512, 1024):
        ksat, c, dtime, size = depth(32768, n, 25)
        _, t0, w0 = timeline(32768, n, 0)
        _, t6, _ = timeline(32768, n, 6)
        examples.append({"M": 32768, "N": n, "C_ms": float(c), "D_ms": float(dtime),
                         "k_sat": ksat, "HBM_at_saturation_MiB": ksat * size / 2**20,
                         "T_0_ms": float(t0), "T_6_ms": float(t6), "saved_ms": float(t0 - t6),
                         "fraction_of_avoidable_wait_removed": float((t0 - t6) / w0),
                         "fraction_of_recovery_interval_saved": float((t0 - t6) / t0),
                         "initial_HBM_MiB": 6 * size / 2**20})
    write_csv("fixed-config-examples.csv", examples)
    manifest = {
        "evidence": CONFIG["evidence"], "examples": examples,
        "arithmetic_crosscheck": {"parameter_states": 60, "residency_choices_per_state": 37,
                                  "closed_form_equals_exact_event_recurrence": True},
        "sparse_evidence": "Two constructed selection schedules and a derived fixed-window mask; no native sparse access trace was used",
        "sources": [CONFIG["model_config_url"], "https://www.usenix.org/system/files/atc24-gao-bin-cost.pdf",
                    "https://arxiv.org/html/2502.11089v1"],
        "files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir()
                         if p.suffix in (".py", ".csv", ".png", ".pdf", ".svg", ".json")
                         and p.name not in ("MANIFEST.json", "REVIEW.json", "figure-lesson.json")},
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"figures": 4, "examples": examples}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
