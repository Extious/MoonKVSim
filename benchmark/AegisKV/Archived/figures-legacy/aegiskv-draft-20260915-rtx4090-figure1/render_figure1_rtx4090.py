"""Archived Figure 1 (2026-09-16/17 version): three native sparse models on one RTX 4090, retained-KV protocol.

Superseded on 2026-09-17 by the A100 version (MiniCPM4-8B measured 8K-128K next to AIConfigurator estimates for
Qwen3-8B / Qwen3-30B-A3B), rendered by experiments/scripts/paper/render_draft_20260915.py.  This standalone copy of
the old figure code reads the unchanged RTX 4090 data files (Slurm job 151751) so the archived figure can be
regenerated; nothing in the paper draft references it.

Run from the repository root:  .venv/bin/python <this file>
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
assert (ROOT / "benchmark/AegisKV").is_dir(), ROOT
SPARSE = ROOT / "benchmark/AegisKV/experiments/native-sparse/20260915"
LATENCY = {"MiniCPM4-8B": SPARSE / "prefill-latency-minicpm4-8b-retained-kv-151751.json",
           "NOSA-1B": SPARSE / "prefill-latency-nosa-1b-retained-kv-151751.json",
           "NOSA-3B": SPARSE / "prefill-latency-nosa-3b-retained-kv-151751.json"}
BLUE, ORANGE, GREEN = "#0072B2", "#B86B00", "#007D60"
COLOR = {"MiniCPM4-8B": ORANGE, "NOSA-1B": BLUE, "NOSA-3B": GREEN}
MARKER = {"MiniCPM4-8B": "o", "NOSA-1B": "s", "NOSA-3B": "D"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10.5, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.linewidth": .7, "pdf.fonttype": 42, "legend.frameon": False})


def load(model):
    data = json.loads(LATENCY[model].read_text())
    assert data["status"] == "complete" and data["protocol_version"] == 2
    rows = sorted(data["rows"], key=lambda r: r["context"])
    return (np.array([r["context"] for r in rows], dtype=float),
            np.array([float(np.median(r["prefill_s"])) for r in rows]), data["gpu"])


def main():
    series = {m: load(m) for m in ("MiniCPM4-8B", "NOSA-3B", "NOSA-1B")}
    gpu = series["MiniCPM4-8B"][2]
    ctx_m, pre_m, _ = series["MiniCPM4-8B"]
    per_token_32k = pre_m[-1] / ctx_m[-1]
    fig, ax = plt.subplots(figsize=(3.4, 2.85))
    fig.subplots_adjust(left=.165, right=.97, bottom=.195, top=.835)
    ext = np.array([ctx_m[-1], 65536.0, 131072.0])
    ax.plot(ext, per_token_32k * ext, color=ORANGE, lw=1.4, ls=(0, (3, 2)), zorder=2)
    ax.plot(ext[1:], per_token_32k * ext[1:], marker="o", ls="none", color=ORANGE, ms=5.5, mfc="white", mew=1.4, zorder=3)
    for model, (ctx, prefill, _) in series.items():
        ax.plot(ctx, prefill, marker=MARKER[model], color=COLOR[model], lw=1.8, ms=5.5 if model == "MiniCPM4-8B" else 4.8, zorder=4)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xticks([8192, 16384, 32768, 65536, 131072])
    ax.set_xticklabels(["8K", "16K", "32K", "64K", "128K"])
    ax.set_yticks([0.5, 1, 2, 5, 10, 20, 50])
    ax.set_yticklabels(["0.5", "1", "2", "5", "10", "20", "50"])
    ax.set_ylim(0.4, 60)
    ax.set_xlim(7000, 160000)
    ax.minorticks_off()
    ax.set_xlabel("Lost prefix (tokens)")
    ax.set_ylabel("Full recompute (s)")
    ax.annotate(f"{pre_m[-1]:.1f} s", xy=(ctx_m[-1], pre_m[-1]), xytext=(-4, 9), textcoords="offset points",
                ha="right", va="bottom", color=ORANGE)
    ax.annotate(f"≥ {per_token_32k * 131072:.1f} s", xy=(131072, per_token_32k * 131072), xytext=(6, 11),
                textcoords="offset points", ha="right", va="bottom", color=ORANGE)
    c3, p3, _ = series["NOSA-3B"]
    cn, pn, _ = series["NOSA-1B"]
    ax.annotate(f"{p3[-1]:.1f} s", xy=(c3[-1], p3[-1]), xytext=(-8, 5), textcoords="offset points", ha="right", va="center", color=GREEN)
    ax.annotate(f"{pn[-1]:.1f} s", xy=(cn[-1], pn[-1]), xytext=(4, -13), textcoords="offset points", ha="center", va="top", color=BLUE)
    handles = [Line2D([], [], color=ORANGE, marker="o", ms=5.5, lw=1.8, label="MiniCPM4-8B"),
               Line2D([], [], color=ORANGE, marker="o", ms=5.5, mfc="white", mew=1.4, lw=1.4, ls=(0, (3, 2)), label="linear lower bound"),
               Line2D([], [], color=GREEN, marker="D", ms=4.8, lw=1.8, label="NOSA-3B"),
               Line2D([], [], color=BLUE, marker="s", ms=4.8, lw=1.8, label="NOSA-1B")]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.56, 1.0), ncol=2, handlelength=1.6,
               columnspacing=1.0, handletextpad=.5, borderaxespad=0, labelspacing=.3)
    for suffix in ("pdf", "png"):
        fig.savefig(HERE / f"motivation-recompute-rtx4090.{suffix}", dpi=240)
    (HERE / "motivation-recompute-rtx4090.json").write_text(json.dumps(dict(
        gpu=gpu, protocol="retained-KV v2, Slurm job 151751", sources=[str(p.relative_to(ROOT)) for p in LATENCY.values()],
        prefill_median_s={m: {int(c): float(p) for c, p in zip(s[0], s[1])} for m, s in series.items()},
        linear_lower_bound_128k_s=float(per_token_32k * 131072)), indent=2) + "\n")
    print("wrote", HERE)


if __name__ == "__main__":
    main()
