"""Figures for the 2026-09-15 AegisKV paper draft (paper/draft/*.md) -- native sparse attention edition.

Motivation has two points and four figures: (a) multi-agent workflows add dependencies among requests, so requests
differ in how much recovery delay they can absorb (Figures 1, 2: coding-agent trace x measured recompute cost);
(b) the agent era makes contexts longer, open flagship models move to trained sparse attention (Figure 3: survey of
sparse-attention releases, no measurement), and recomputing a lost prefix keeps getting dearer (Figure 4: measured
prefill latency on one A100 80GB plus two AIConfigurator estimates).  The recompute-cost calibration is MiniCPM4-8B
(InfLLM-v2 native sparse attention) measured by us; the access-concentration evidence that supports the hotness-based
placement of Design section 3.3 (Figure 6) comes from three openly released native sparse attention models that we ran
ourselves.  Figures 4 and 6 plot only completed, validated runs:

  MiniCPM4-8B  (InfLLM-v2 selector)   32 layers, 2 KV heads, 1 KiB of KV per token per layer   (Figures 4, 6; cost model)
  NOSA-1B      (NOSA selector)         28 layers, 2 KV heads, 1 KiB of KV per token per layer   (Figure 6)
  NOSA-3B      (NOSA selector)         32 layers, 2 KV heads, 1 KiB of KV per token per layer   (Figure 6)

Figure 4 additionally carries two dense/MoE reference curves that are *estimates*, not measurements: Qwen3-8B and
Qwen3-30B-A3B full-prefix prefill on A100 from NVIDIA AIConfigurator (HYBRID database mode = measured kernel
tables where the tool has them, SOL elsewhere; the SOL lower bounds at 128K are quoted in the MANIFEST note).
MiniCPM4-8B is not modelled by that tool, hence measured.  Evidence classes are kept apart in file names and in
MANIFEST.json:

  measured      motivation-branch-gap             Figure 1: CC/Weka coding-agent trace: max parallel-branch duration gap per
                                                  workflow (ECDF); recompute comparisons remain in the prose and JSON only
  trace+model   motivation-recovery-exposure      Figure 2: CC trace fan-out x measured MiniCPM4-8B cost (log-log
                                                  interpolation, 8K-128K)
  survey        motivation-sparse-releases        Figure 3: release date x native context of open models with trained sparse
                                                  attention (sources in SPARSE_RELEASES); no measurement involved
  measured      motivation-recompute              Figure 4: MiniCPM4-8B full-prefill latency vs. context, A100 80GB, retained-KV
  + estimate                                      protocol (8K-128K, no extrapolation) next to the two AIConfigurator estimates;
                                                  the measured curve anchors the cost model used by Figures 1/2/7
  measured      design-sparse-concentration       Figure 6 (Design 3.3): solid (layer, block) offline concentration curves,
                                                  first 256/512 subsequent queries of each causal capture
                design-needed-coverage            Figure 8: needed-set coverage by hot-first / recency-first preload
  supplement    motivation-needed-fraction        former Figure 5 of the 2026-09-15 numbering; removed from Motivation,
                                                  valid union tables retained
  analytic      design-layer-pipeline, design-wait-vs-bytes (Figures 7 and 9)
                single-request pipeline and quota approximations, NOT a serialized queue of requests.
  historical    design-cascade, eval-*             retired serial-queue examples; NOT current design evidence.
                Their functions and Model remain below for provenance only. Default rendering excludes them;
                existing records are retained under archived_figures in MANIFEST.json.

Design constants that the text quotes: sealing per 64-token block -> worst-case replay of REPLAY_QUERIES = 64 queries;
u~ (U_PROFILES) = preload the hottest blocks up to the previous same-length window's union, then demand-fetch misses.

Run:
  .venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_draft_20260915.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, NullLocator  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.text import Text  # noqa: E402

ROOT = Path(__file__).resolve().parents[5]           # .../MoonKVSim
assert (ROOT / "benchmark/AegisKV").is_dir(), ROOT
OUT = ROOT / "benchmark/AegisKV/paper/figures"
SPARSE = ROOT / "benchmark/AegisKV/experiments/native-sparse/20260915"          # cross-model tables + MiniCPM4-8B traces + latency
# MiniCPM4-8B on one A100 80GB (Slurm job 152626, measure_minicpm4_a100.sbatch).  Full-prefix prefill, retained-KV protocol
# (v2): every layer's KV stays resident through a CUDA synchronisation, the native selector call count is validated per
# forward, 5 timed repeats after one validated warm-up, 8K-128K without OOM.  The same allocation measured the replay of an
# unsealed tail over a resident history (design constant C).  The RTX 4090 files of the earlier campaign (Slurm job 151751,
# *-retained-kv-151751.json) stay in this directory as provenance of the archived figure version; nothing here reads them.
A100_TAG = "a100-152626"
LATENCY = {"MiniCPM4-8B": SPARSE / f"prefill-latency-minicpm4-8b-{A100_TAG}.json"}
REPLAY_JSON = SPARSE / f"replay-latency-minicpm4-8b-{A100_TAG}.json"      # forward of n tail tokens over a resident history
# Dense / MoE reference curves of Figure 4: NVIDIA AIConfigurator estimates (a100_sxm, vLLM backend, batch 1, TP 1), HYBRID
# and SOL database modes, produced by experiments/data/recompute-aiconfigurator-a100/estimate_recompute_a100.py.
AIC_JSON = ROOT / "benchmark/AegisKV/experiments/data/recompute-aiconfigurator-a100/estimates.json"
CC_CSV = ROOT / "benchmark/AegisKV/experiments/data/motivation-real-cc/real-cc-example-failure-position.csv"

BLUE, ORANGE, GREEN, PURPLE, RED, GRAY, INK = (
    "#0072B2", "#B86B00", "#007D60", "#7952A2", "#B83C46", "#59636F", "#303943")
PALE_BLUE, PALE_ORANGE, PALE_GREEN, PALE_RED = "#DCEBF5", "#FCEBD2", "#DDF0E7", "#F6DADD"
MODEL_COLOR = {"MiniCPM4-8B": ORANGE, "NOSA-1B": BLUE, "NOSA-3B": GREEN, "Qwen3-8B": BLUE, "Qwen3-30B-A3B": PURPLE}
MODEL_MARKER = {"MiniCPM4-8B": "o", "NOSA-1B": "s", "NOSA-3B": "D", "Qwen3-8B": "s", "Qwen3-30B-A3B": "^"}
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10.5,
    "axes.labelsize": 10.5, "axes.titlesize": 10.5, "axes.titleweight": "bold",
    "xtick.labelsize": 10.5, "ytick.labelsize": 10.5, "legend.fontsize": 10.5,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": .7,
    "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
    "svg.hashsalt": "aegiskv-draft-20260915", "hatch.linewidth": .6,
    "savefig.facecolor": "white", "legend.frameon": False,
})
MANIFEST: dict[str, dict] = {}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(fig, name, *, evidence, width_in, note, sources):
    """Export pdf/svg/png; every visible label must be >= 10 pt and inside the page."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    hidden = set()
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            lo, hi = sorted(axis.get_view_interval())
            for tick in [*axis.get_major_ticks(), *axis.get_minor_ticks()]:
                if not lo <= tick.get_loc() <= hi:
                    hidden.update((id(tick.label1), id(tick.label2)))
    for obj in fig.findobj(match=Text):
        if id(obj) in hidden or not obj.get_visible() or not obj.get_text().strip():
            continue
        b = obj.get_window_extent(renderer)
        assert b.x0 >= -.7 and b.y0 >= -.7 and b.x1 <= fig.bbox.width + .7 and b.y1 <= fig.bbox.height + .7, \
            (name, obj.get_text(), tuple(b.extents))
        assert obj.get_fontsize() >= 10.0, (name, obj.get_text(), obj.get_fontsize())
    OUT.mkdir(parents=True, exist_ok=True)
    for suffix in ("pdf", "svg", "png"):
        fig.savefig(OUT / f"{name}.{suffix}", dpi=240)
    w, h = fig.get_size_inches()
    assert abs(w - width_in) < 1e-6, (name, w, width_in)
    plt.close(fig)
    MANIFEST[name] = dict(evidence=evidence, size_in=[round(w, 3), round(h, 3)], note=note,
                          sources=sources, files={s: sha(OUT / f"{name}.{s}") for s in ("pdf", "svg", "png")})


# ----------------------------------------------------------------------------------------
# Measured model costs (MiniCPM4-8B, A100 80GB, batch 1, native sparse path) -> shared by Figures 1, 2, 4, 7, 8 and the model.
# ----------------------------------------------------------------------------------------
def load_latency(model):
    """Median of the 5 timed full-prefix prefills per context (retained-KV protocol); contexts that ran out of HBM would be
    absent from the rows (none on the A100)."""
    data = json.loads(LATENCY[model].read_text())
    assert data["status"] == "complete" and data["protocol_version"] == 2, (model, data["status"])
    rows = sorted(data["rows"], key=lambda r: r["context"])
    for r in rows:
        v = r["validation"]
        assert v["all_layer_kv_retained"] and v["logits_finite"] and v["native_selector_calls"] == data["meta"]["layers"], (model, r["context"])
        assert len(r["prefill_s"]) == 5 and abs(np.median(r["prefill_s"]) - r["prefill_median_s"]) < 1e-3, (model, r["context"])
    ctx = np.array([r["context"] for r in rows], dtype=float)
    prefill = np.array([float(np.median(r["prefill_s"])) for r in rows])
    return ctx, prefill, data


def load_aiconfigurator():
    """AIConfigurator TTFT (= full-prefix prefill, GPU forward only) per model: {model: {mode: (ctx, seconds)}}."""
    data = json.loads(AIC_JSON.read_text())
    assert data["tool"]["system"] == "a100_sxm" and data["protocol"]["batch_size"] == 1 and data["protocol"]["tp_size"] == 1, data["tool"]
    out = {}
    for model, entry in data["models"].items():
        by_mode = defaultdict(list)
        for p in entry["points"]:
            by_mode[p["mode"]].append((p["isl"], p["ttft_ms"] / 1e3))
        out[model] = {mode: tuple(np.array(v, dtype=float) for v in zip(*sorted(pts))) for mode, pts in by_mode.items()}
        assert set(out[model]) == {"HYBRID", "SOL"} and np.all(out[model]["SOL"][1] <= out[model]["HYBRID"][1]), model
    return out, data


CTX_M, PREFILL_M, LAT_META_M = load_latency("MiniCPM4-8B")
AIC, AIC_META = load_aiconfigurator()
GPU_NAME = LAT_META_M["gpu"]
assert "A100" in GPU_NAME, GPU_NAME
LAYERS = LAT_META_M["meta"]["layers"]                        # 32
KV_PER_TOKEN_LAYER = LAT_META_M["meta"]["kv_bytes_per_token_per_layer"]   # 1024 B: 2 KV heads x 128 x (K,V) x BF16
assert LAYERS == 32 and KV_PER_TOKEN_LAYER == 1024, (LAYERS, KV_PER_TOKEN_LAYER)
assert CTX_M[0] == 8192 and CTX_M[-1] == 131072 and len(CTX_M) >= 5, CTX_M   # the 128K point is measured, not extrapolated
PER_TOKEN_128K = PREFILL_M[-1] / CTX_M[-1]                   # s/token at the longest measured context (only used beyond it)
LATENCY_PARAMETERS = dict(                                   # recorded in MANIFEST.json (full run and --only motivation-recompute)
    latency_protocol=f"retained-KV v2, Slurm job {LAT_META_M['slurm_job_id']}, {GPU_NAME}",
    prefill_measured_s={int(c): float(p) for c, p in zip(CTX_M, PREFILL_M)},
    recompute_measured_32k_s=float(PREFILL_M[list(CTX_M).index(32768)]),
    recompute_measured_128k_s=float(PREFILL_M[-1]),
    reference_estimates=dict(
        tool=f"NVIDIA AIConfigurator {AIC_META['tool']['version']} ({AIC_META['tool']['commit'][:12]}), system a100_sxm, "
             f"backend {AIC_META['protocol']['backend']}, static estimate, batch 1, TP 1",
        ttft_s_by_model_and_mode={m: {mode: {int(c): float(t) for c, t in zip(*AIC[m][mode])} for mode in AIC[m]} for m in AIC}))


def recompute_s(ctx):
    """Full-prefix prefill of MiniCPM4-8B on the A100: log-log interpolation of the measured medians (8K-128K); the
    per-token cost at 128K times the context beyond the measured range (a lower bound; not used by any current figure)."""
    ctx = float(ctx)
    if ctx <= CTX_M[-1]:
        return float(np.exp(np.interp(np.log(ctx), np.log(CTX_M), np.log(PREFILL_M))))
    return float(PER_TOKEN_128K * ctx)


REPLAY_META = json.loads(REPLAY_JSON.read_text())
assert REPLAY_META["gpu"] == GPU_NAME and REPLAY_META["slurm_job_id"] == LAT_META_M["slurm_job_id"], (REPLAY_META["gpu"], GPU_NAME)
REPLAY_ROWS = {(r["context"], r["tail"]): r for r in REPLAY_META["rows"]}


def replay_ms_per_layer(ctx, tail=64):
    """Cost of replaying `tail` tokens over a resident ctx-token history, split evenly over the layers.

    Measured directly (prefill L into the cache, then time the forward of the next `tail` ids, median of 5 repeats on deep
    copies of the same cache); piecewise linear in ctx between the measured contexts, held at the end slope beyond."""
    ctxs = sorted({c for c, t in REPLAY_ROWS if t == tail})
    assert len(ctxs) >= 2, ("replay of this tail length was not measured", tail)
    values = [REPLAY_ROWS[(c, tail)]["replay_median_s"] for c in ctxs]
    if ctx > ctxs[-1]:
        slope = (values[-1] - values[-2]) / (ctxs[-1] - ctxs[-2])
        return float(values[-1] + slope * (ctx - ctxs[-1])) / LAYERS * 1e3
    return float(np.interp(ctx, ctxs, values)) / LAYERS * 1e3


REPLAY_MEASURED = any(t == 64 for _, t in REPLAY_ROWS)
assert REPLAY_MEASURED


def kv_bytes(ctx):
    return ctx * KV_PER_TOKEN_LAYER * LAYERS


def needed_fraction_table():
    """Per (model, history, replay length, layer), mean over documents of three fractions of a layer's history blocks:
    needed      = blocks the next n queries select at least once (oracle union; a replay cannot finish without them)
    effective   = path bytes of the online loader: preload the hottest blocks (previous-window rank) up to the union size
                  of the previous n queries, then fetch the still-missing needed blocks on demand  (speculate-then-demand)
    recency     = same loader with a most-recent-first order instead of the hotness rank."""
    table = defaultdict(lambda: defaultdict(list))
    with open(SPARSE / "needed_fraction_models.csv") as f:
        for r in csv.DictReader(f):
            k = (r["model"], int(r["M"]), int(r["replay_queries"]), int(r["layer"]))
            table[k]["needed"].append(float(r["needed_fraction"]))
            table[k]["effective"].append(float(r["effective_fraction_hot_first_matched"]))
            table[k]["preload"].append(float(r["preload_fraction_matched"]))
            table[k]["recency"].append(float(r["effective_fraction_recency_first"]))
    return {k: {q: float(np.mean(v)) for q, v in d.items()} for k, d in table.items()}


NEEDED = needed_fraction_table()
REPLAY_QUERIES = 64                                          # worst-case unsealed tail: one 64-token block (sealed per block)
MODEL_LAYERS = {"MiniCPM4-8B": 32, "NOSA-1B": 28}


def u_profile(model, M=32768, n=REPLAY_QUERIES, quantity="effective"):
    return float(np.mean([NEEDED[(model, M, n, l)][quantity] for l in range(1, MODEL_LAYERS[model] + 1)]))


U_PROFILES = {m: u_profile(m) for m in ("MiniCPM4-8B", "NOSA-1B")}            # effective (online) fraction: the design quantity
U_ORACLE = {m: u_profile(m, quantity="needed") for m in ("MiniCPM4-8B", "NOSA-1B")}
U_REQ = U_PROFILES["MiniCPM4-8B"]                            # default: the model whose sizes and costs the draft uses
BETA = 25e9                                                  # bytes/s: host-local DRAM pool -> GPU (GPU-level failure)
BETA_REMOTE = 6.25e9                                         # bytes/s: remote pool, 4 GPUs of a failed host recovering at once


# ----------------------------------------------------------------------------------------
# Figure 3 (survey): open model releases with trained sparse attention, 2025-06 .. 2026-08 -- release date x native context.
#   Only models whose softmax-attention layers are trained top-k sparse are drawn; full-attention and linear-attention
#   releases are not in the figure.  One point per release that introduced a new sparse mechanism or a new native
#   context in its model line; follow-ups with unchanged architecture and context (GLM-5.1, GLM-5.3) are omitted.
#   Marker = selection granularity of the mechanism: 64/128-token blocks (InfLLM-v2, MSA), single tokens (DSA, LSA),
#   4-token compressed entries (CSA).  Nothing here is measured: dates and native context lengths are copied from the
#   model cards / technical reports in SPARSE_RELEASES (checked 2026-09-17).  MiniCPM-SALA keeps 25% InfLLM-v2 layers
#   next to 75% linear-attention layers; it is drawn because every softmax-attention layer it has is sparse.
# ----------------------------------------------------------------------------------------
GRANULARITY = {                            # granularity -> legend label, marker, colour
    "block": ("block top-k  (InfLLM-v2, MSA)", "o", ORANGE),
    "token": ("token top-k  (DSA, LSA)", "s", BLUE),
    "entry": ("compressed-entry top-k  (CSA)", "D", PURPLE),
}
# (label, release date, native context in K tokens, selection granularity, label placement, source)
SPARSE_RELEASES = [
    ("MiniCPM4", date(2025, 6, 6), 32, "block", "right",
     "https://github.com/OpenBMB/MiniCPM  (release log 2025-06-06; InfLLM-v2 block top-k, 32K native, 128K with LongRoPE)"),
    ("MiniCPM4.1", date(2025, 9, 5), 64, "block", "right",
     "https://huggingface.co/openbmb/MiniCPM4.1-8B  (2025-09-05; InfLLM-v2, 65,536 native, 131,072 with LongRoPE)"),
    ("DeepSeek-V3.2-Exp", date(2025, 9, 29), 128, "token", "above",
     "https://huggingface.co/deepseek-ai/DeepSeek-V3.2-Exp  (2025-09-29; DSA: lightning indexer, token-level top-2048, 128K)"),
    ("DeepSeek-V3.2", date(2025, 12, 1), 128, "token", "below",
     "https://www.deepseek.com/en/news/deepseek-v3-2/  (2025-12-01; production successor of V3.2-Exp, DSA, 128K)"),
    ("GLM-5", date(2026, 2, 12), 200, "token", "right",
     "https://z.ai/blog/glm-5  (2026-02-12; 744B MoE with DeepSeek Sparse Attention, 200K)"),
    ("MiniCPM-SALA", date(2026, 2, 11), 1024, "block", "below",
     "https://huggingface.co/openbmb/MiniCPM-SALA  (2026-02-11; 25% InfLLM-v2 + 75% Lightning Attention layers, 1M)"),
    ("DeepSeek-V4", date(2026, 4, 24), 1024, "entry", "above",
     "https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro  (2026-04-24 preview; CSA = 4x compressed entries + top-k, 1M)"),
    ("MiniMax-M3", date(2026, 6, 1), 1024, "block", "below",
     "https://github.com/MiniMax-AI/MiniMax-M3  (2026-06-01; MSA: 128-token blocks, top-16 per GQA group, 1M)"),
    ("GLM-5.2", date(2026, 6, 16), 1024, "token", "above-right",
     "https://github.com/huggingface/transformers/blob/main/docs/source/en/model_doc/glm_moe_dsa.md  (GLM-5.2, 2026-06-16; "
     "DSA with IndexShare, 1M)"),
    ("LongCat-Flash-\nLite-Sparse", date(2026, 7, 31), 1024, "token", "below-right",
     "https://huggingface.co/meituan-longcat/LongCat-Flash-Lite-Sparse  (2026-07-31; LSA: sink + window + token top-k, 1M)"),
]
RELEASE_SPAN = (date(2025, 4, 1), date(2026, 11, 15))
RELEASE_PLACEMENT = {                      # placement -> (dx pt, dy pt, ha, va)
    "right": (7, 0, "left", "center"), "left": (-7, 0, "right", "center"),
    "above": (0, 7.5, "center", "bottom"), "below": (0, -7.5, "center", "top"),
    "above-right": (3, 6.5, "left", "bottom"), "below-right": (3, -6.5, "left", "top"),
}


def figure_sparse_releases():
    fig, ax = plt.subplots(figsize=(7.0, 2.7))
    fig.subplots_adjust(left=.105, right=.985, bottom=.165, top=.955)
    assert all(RELEASE_SPAN[0] < p[1] < RELEASE_SPAN[1] for p in SPARSE_RELEASES)
    # Thin staircase behind the points: the largest native context among sparse-attention releases to date.
    frontier_x, frontier_y, best = [], [], 0
    for _label, day, ctx_k, *_ in sorted(SPARSE_RELEASES, key=lambda p: p[1]):
        if ctx_k > best:
            frontier_x.append(day)
            frontier_y.append(ctx_k)
            best = ctx_k
    frontier_x.append(RELEASE_SPAN[1])
    frontier_y.append(best)
    ax.step(frontier_x, frontier_y, where="post", color="#C9CED4", lw=1.2, zorder=1)
    for label, day, ctx_k, gran, place, _src in SPARSE_RELEASES:
        _, marker, color = GRANULARITY[gran]
        ax.plot([day], [ctx_k], marker=marker, ms=7.5 if marker != "D" else 6.5, mfc=color, mec="white", mew=.8,
                ls="none", zorder=3)
        dx, dy, ha, va = RELEASE_PLACEMENT[place]
        ax.annotate(label, xy=(day, ctx_k), xytext=(dx, dy), textcoords="offset points", ha=ha, va=va,
                    color=INK, linespacing=1.0, zorder=4)
    ax.set_yscale("log", base=2)
    ax.set_yticks([32, 64, 128, 256, 512, 1024])
    ax.set_yticklabels(["32K", "64K", "128K", "256K", "512K", "1M"])
    ax.yaxis.set_minor_locator(NullLocator())
    ax.set_ylim(22, 1700)
    ax.set_ylabel("Native context")
    ax.set_xlim(*RELEASE_SPAN)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.grid(axis="y", color="#E3E6EA", lw=.6, zorder=0)
    handles = [Line2D([], [], marker=m, ms=7.5 if m != "D" else 6.5, mfc=c, mec="white", mew=.8, ls="none", label=lab)
               for lab, m, c in GRANULARITY.values()]
    ax.legend(handles=handles, loc="lower right", bbox_to_anchor=(1.005, -.03), handletextpad=.3, labelspacing=.35,
              borderaxespad=0)
    save(fig, "motivation-sparse-releases", evidence="survey", width_in=7.0,
         note="Survey figure (no measurement): open model releases whose softmax-attention layers are trained top-k sparse, "
              "2025-06 to 2026-08, release date against the native (trained) context length stated by the vendor. One point "
              "per release that introduced a new sparse mechanism or a new native context in its model line; follow-ups with "
              "unchanged architecture and context (GLM-5.1, GLM-5.3) are omitted, and full-attention or linear-attention "
              "releases are not shown. Marker = selection granularity: 64/128-token blocks (InfLLM-v2, MSA), single tokens "
              "(DSA, LSA), 4-token compressed entries (CSA). MiniCPM-SALA is drawn because all of its softmax-attention layers "
              "are InfLLM-v2 (the other 75% are linear-attention layers). Dates and contexts were copied from the model cards "
              "and technical reports listed under sources on 2026-09-17; native context is the trained length, not a "
              "provider-side window.",
         sources=[p[5] for p in SPARSE_RELEASES])


# ----------------------------------------------------------------------------------------
# Figure 4 (measured + estimate): full-prefix recompute cost versus context length on one A100 80GB.
#   MiniCPM4-8B (native sparse attention)  measured, solid line, filled markers, 8K-128K
#   Qwen3-8B (dense) / Qwen3-30B-A3B (MoE) AIConfigurator estimates, dashed line + hollow markers = HYBRID mode;
#                                          the SOL (speed-of-light) lower bounds at 128K are quoted in the MANIFEST note
# ----------------------------------------------------------------------------------------
REFERENCE_MODELS = ("Qwen3-30B-A3B", "Qwen3-8B")


def figure_recompute():
    fig, ax = plt.subplots(figsize=(3.4, 2.85))
    fig.subplots_adjust(left=.165, right=.975, bottom=.195, top=.97)
    for model in REFERENCE_MODELS:
        ctx, hybrid = AIC[model]["HYBRID"]
        ax.plot(ctx, hybrid, marker=MODEL_MARKER[model], color=MODEL_COLOR[model], lw=1.5, ls=(0, (3, 2)),
                ms=5.0, mfc="white", mew=1.4, zorder=3)
    ax.plot(CTX_M, PREFILL_M, marker="o", color=ORANGE, lw=1.8, ms=5.5, zorder=4)
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xticks([8192, 16384, 32768, 65536, 131072])
    ax.set_xticklabels(["8K", "16K", "32K", "64K", "128K"])
    ax.set_yticks([0.5, 1, 2, 5, 10, 20, 50])
    ax.set_yticklabels(["0.5", "1", "2", "5", "10", "20", "50"])
    ax.set_ylim(0.3, 70)
    ax.set_xlim(7000, 280000)
    ax.minorticks_off()
    ax.set_xlabel("Lost prefix (tokens)")
    ax.set_ylabel("Full recompute (s)")
    # Value labels to the right of the 128K end of every curve (the x range leaves room for them).
    end = {m: float(AIC[m]["HYBRID"][1][-1]) for m in REFERENCE_MODELS}
    end["MiniCPM4-8B"] = float(PREFILL_M[-1])
    sol_128k = {m: float(AIC[m]["SOL"][1][-1]) for m in REFERENCE_MODELS}
    ax.annotate(f"{end['Qwen3-30B-A3B']:.0f} s", xy=(131072, end["Qwen3-30B-A3B"]), xytext=(6, 2),
                textcoords="offset points", ha="left", va="center", color=PURPLE)
    ax.annotate(f"{end['Qwen3-8B']:.0f} s", xy=(131072, end["Qwen3-8B"]), xytext=(6, -4),
                textcoords="offset points", ha="left", va="center", color=BLUE)
    ax.annotate(f"{end['MiniCPM4-8B']:.1f} s", xy=(131072, end["MiniCPM4-8B"]), xytext=(6, -2),
                textcoords="offset points", ha="left", va="center", color=ORANGE)
    handles = [Line2D([], [], color=PURPLE, marker="^", ms=5.0, mfc="white", mew=1.4, lw=1.5, ls=(0, (3, 2)),
                      label="Qwen3-30B-A3B"),
               Line2D([], [], color=BLUE, marker="s", ms=5.0, mfc="white", mew=1.4, lw=1.5, ls=(0, (3, 2)),
                      label="Qwen3-8B"),
               Line2D([], [], color=ORANGE, marker="o", ms=5.5, lw=1.8, label="MiniCPM4-8B")]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(-.01, 1.02), ncol=1, handlelength=1.8,
              handletextpad=.5, borderaxespad=0, labelspacing=.25)
    ax.text(.985, .03, "dashed: estimated\nsolid: measured", transform=ax.transAxes,
            ha="right", va="bottom", color=INK, linespacing=1.15)
    save(fig, "motivation-recompute", evidence="measured+estimate", width_in=3.4,
         note=f"Full-prefix prefill of a lost prefix on one A100 80GB, batch 1, BF16. MiniCPM4-8B (InfLLM-v2 native sparse "
              f"attention, 8.2B): measured, median of 5 timed full causal prefills per point after one validated warm-up, "
              f"native sparse kernels, {GPU_NAME}; the wall clock includes block selection and the KV writes of every layer "
              f"(retained-KV protocol, Slurm job {LAT_META_M['slurm_job_id']}); all six points 8K-128K are measured, nothing is "
              f"extrapolated. Qwen3-8B (dense, 36 layers) and Qwen3-30B-A3B (MoE, 3.3B active, 48 layers): NVIDIA "
              f"AIConfigurator {AIC_META['tool']['version']} static estimates of TTFT for an A100-SXM (vLLM backend, TP 1), "
              f"HYBRID database mode (measured kernel tables where the tool has them, otherwise speed-of-light x empirical "
              f"efficiency); the pure speed-of-light bounds (SOL mode) at 128K are "
              + ", ".join(f"{m} {v:.1f} s" for m, v in sol_128k.items())
              + ". Neither number includes failure detection, transfer or queueing. Curve end points at 128K: "
              + "; ".join(f"{m} = {v:.2f} s" for m, v in end.items()) + ".",
         sources=[str(p.relative_to(ROOT)) for p in LATENCY.values()] + [str(AIC_JSON.relative_to(ROOT))])


# ----------------------------------------------------------------------------------------
# Figure 1 (measured trace): imbalance of parallel branches versus the measured recompute cost.
# ----------------------------------------------------------------------------------------
GAP_CSV = CC_CSV.parent / "real-cc-workflow-parallel-gap.csv"


def figure_branch_gap():
    with open(GAP_CSV) as f:
        rows = list(csv.DictReader(f))
    gap = np.sort([float(r["max_duration_gap_s"]) for r in rows])
    widths = np.array([int(r["fanout_width"]) for r in rows])
    n = len(gap)
    assert n == 124, n
    # Keep the empirical distribution and quantiles in the plot. Dataset details
    # and recompute comparisons belong in the caption and accompanying prose.
    fig, ax = plt.subplots(figsize=(3.4, 3.15))
    fig.subplots_adjust(left=.19, right=.965, bottom=.18, top=.965)
    xs = np.concatenate([[.3], gap, [3e4]])
    ys = np.concatenate([[0], np.arange(1, n + 1) / n, [1]])
    ax.step(xs, ys, where="post", color=BLUE, lw=1.9, zorder=3)
    refs = {}
    for ctx in (32768, 131072):
        t = recompute_s(ctx)
        refs[ctx] = dict(recompute_s=round(t, 3), fraction_of_workflows_with_larger_gap=round(float((gap > t).mean()), 4))
    med = float(np.median(gap))
    p90 = float(np.percentile(gap, 90))
    ax.hlines(.5, .3, med, color="#C5CDD3", lw=.7, ls=(0, (2, 3)), zorder=1)
    ax.plot(med, .5, marker="o", color=BLUE, ms=4.8, zorder=4)
    ax.annotate(f"Median\n{med:.0f} s", xy=(med, .5), xytext=(.60, .32), textcoords="axes fraction",
                ha="left", va="center", color=BLUE, linespacing=1.2,
                arrowprops=dict(arrowstyle="-", color=BLUE, lw=.7, shrinkA=3, shrinkB=4))
    # P90 is an interpolated sample quantile, so its label points to the actual
    # ECDF height at that x rather than inventing an empirical observation at 0.9.
    p90_cdf = float(np.searchsorted(gap, p90, side="right") / n)
    ax.annotate(f"P90\n{p90:,.0f} s", xy=(p90, p90_cdf), xytext=(.71, .65), textcoords="axes fraction",
                ha="left", va="center", color=BLUE, linespacing=1.2,
                arrowprops=dict(arrowstyle="-", color=BLUE, lw=.7, shrinkA=3, shrinkB=3))
    ax.set_xscale("log")
    ax.set_xlim(.3, 3e4)
    ax.set_ylim(0, 1.04)
    ax.set_xticks([1, 10, 100, 1000, 10000])
    ax.set_xticklabels(["1", "10", "100", "1k", "10k"])
    ax.minorticks_off()
    ax.set_yticks([0, .25, .5, .75, 1])
    ax.set_yticklabels(["0", "25", "50", "75", "100"])
    ax.set_xlabel("Branch-duration gap (s, log scale)")
    ax.set_ylabel("Workflows (ECDF, %)")
    ax.tick_params(length=3, color=GRAY)
    save(fig, "motivation-branch-gap", evidence="measured", width_in=3.4,
         note=f"ECDF over {n} workflows of a public coding-agent trace (CC/Weka, 393 sessions) that contain a sub-agent fan-out whose "
              f"branches strictly overlap in time (fan-out width 2-10, median {int(np.median(widths))}); each workflow contributes the largest "
              "longest-minus-shortest branch duration among its fan-outs. Blue: unsmoothed ECDF, percent of workflows, log-seconds x axis, "
              "all observations retained. No in-plot title or recompute references. Accompanying prose compares the gaps with measured MiniCPM4-8B full-prefix recompute "
              f"of 32K ({refs[32768]['recompute_s']:.2f} s) and 128K "
              f"({refs[131072]['recompute_s']:.2f} s); both from Figure 4 ({GPU_NAME}), retained in the JSON summary only. "
              f"Median {med:.3f} s and interpolated P90 {p90:.3f} s are annotated. Fractions above the recompute costs "
              "are not fractions of failures guaranteed to be absorbed. A duration gap is not join Slack when branch starts differ, "
              "nor the Slack left at an arbitrary failure time.",
         sources=[str(GAP_CSV.relative_to(ROOT)), str(LATENCY["MiniCPM4-8B"].relative_to(ROOT))])
    (OUT / "motivation-branch-gap.json").write_text(json.dumps(dict(
        workflows=n, median_gap_s=round(med, 3), p90_gap_s=round(float(np.percentile(gap, 90)), 3),
        fanout_width_histogram={int(w): int(c) for w, c in zip(*np.unique(widths, return_counts=True))}, references=refs), indent=2) + "\n")
    return refs


# ----------------------------------------------------------------------------------------
# Figure 2 (trace + measured cost): the same fault exposes different branches differently.
# ----------------------------------------------------------------------------------------
def figure_exposure():
    with open(CC_CSV) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5
    branches, absorbed, exposed, exported = [], [], [], []
    for r in rows:
        tokens, slack = int(r["prefix_tokens"]), float(r["slack_s"])
        t = recompute_s(tokens)
        e = max(t - slack, 0.0)
        branches.append("A" + str(int(r["branch_index"]) + 1))
        absorbed.append(t - e)
        exposed.append(e)
        exported.append(dict(branch=branches[-1], prefix_tokens=tokens, slack_s=slack, recompute_s=round(t, 3),
                             absorbed_s=round(t - e, 3), exposed_s=round(e, 3), workflow_id=r["workflow_id"],
                             failure_time_s=r["failure_time_s"]))
    # Keep the five paired counterfactuals in trace order. Fixed numeric columns
    # separate available Slack from the (possibly smaller) time it absorbs.
    fig = plt.figure(figsize=(3.4, 3.15))
    ax = fig.add_axes([.21, .20, .45, .59])
    stats = fig.add_axes([.72, .20, .26, .59], sharey=ax)
    y = np.arange(len(branches))
    ax.barh(y, absorbed, height=.58, color=PALE_GREEN, edgecolor=GREEN, hatch="//", lw=.6,
            label="Slack absorbs", zorder=2)
    ax.barh(y, exposed, left=absorbed, height=.58, color=RED, label="WCT loss", zorder=2)
    for yi, r in zip(y, exported):
        ax.text(r["recompute_s"] + .45, yi, f"{r['recompute_s']:.1f}", va="center", ha="left", color=INK)
        stats.text(.22, yi, f"{r['slack_s']:.1f}", va="center", ha="center", color=GRAY)
        stats.text(.82, yi, f"{r['exposed_s']:.1f}", va="center", ha="center",
                   color=RED if r["exposed_s"] > 0 else GREEN,
                   weight="bold" if r["exposed_s"] > 0 else "normal")
    ax.set_yticks(y)
    ax.set_yticklabels(branches)
    ax.set_ylim(len(branches) - .45, -.55)
    ax.set_xlim(0, 24)
    ax.set_xticks([0, 10, 20])
    ax.set_xlabel("Recompute time (s)")
    ax.set_ylabel("Agent branch", labelpad=7)
    ax.tick_params(axis="y", length=0, pad=5)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#E3E7EB", lw=.6)
    stats.set_xlim(0, 1)
    stats.set_axis_off()
    stats.text(.22, 1.025, "Slack\n(s)", transform=stats.transAxes, ha="center", va="bottom", color=GRAY,
               linespacing=1.1)
    stats.text(.82, 1.025, "Loss\n(s)", transform=stats.transAxes, ha="center", va="bottom", color=RED,
               linespacing=1.1)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper left", bbox_to_anchor=(.14, .98), ncol=2,
               columnspacing=1.0, handlelength=1.2, handletextpad=.45, borderaxespad=0)
    save(fig, "motivation-recovery-exposure", evidence="trace+measured-cost", width_in=3.4,
         note="Five separate single-branch fault counterfactuals in one reconstructed CC-trace fan-out at 349.5 s (workflow 8ab0a089); "
              f"prefix tokens 65K-112K from the trace; recompute = log-log interpolation of the measured MiniCPM4-8B curve (Fig. 4, {GPU_NAME}, 8K-128K); "
              "exposed = max(0, recompute - Slack). Green hatching = min(recompute, Slack); red = exposed WCT loss. "
              "Bar-end labels show total recompute seconds; the aligned right-hand columns show full available Slack and exposed seconds, "
              "both to one decimal. Axes identify recompute time (s) and agent branch; no in-plot title or formula. "
              "Five rows remain in trace order, one workflow, not five independent failure runs. "
              "Only trace prefix tokens, Slack, and identifiers are used; legacy Qwen predictor costs in the input CSV are ignored. "
              "Other branches and queues held unchanged.",
         sources=[str(CC_CSV.relative_to(ROOT)), str(LATENCY["MiniCPM4-8B"].relative_to(ROOT))])
    (OUT / "motivation-recovery-exposure.csv").write_text(
        "\n".join([",".join(exported[0].keys())] + [",".join(str(v) for v in r.values()) for r in exported]) + "\n")


# ----------------------------------------------------------------------------------------
# Figure 6 (measured, Design section 3.3): one observation only -- concentrated (layer, block) access.
# ----------------------------------------------------------------------------------------
def figure_sparse_concentration(M=32768, data_dir=SPARSE):
    """Solid offline concentration curves; nested 256/512-query windows, no prediction or span curves."""
    data_dir = Path(data_dir).resolve()
    curves = defaultdict(list)
    with open(data_dir / "concentration_curves_models.csv") as f:
        for r in csv.DictReader(f):
            if int(r["M"]) == M and r["granularity"] == "layer_block" and int(r["N"]) in (256, 512):
                curves[(r["model"], int(r["N"]), r["book_id"])].append(
                    (float(r["byte_fraction"]), float(r["access_coverage"])))
    # Only models backed by completed captures enter the plot; missing models are never synthesized.
    preferred = ("NOSA-1B", "NOSA-3B", "NOSA-8B", "MiniCPM4-8B", "MiniCPM4.1-8B", "HiLS-Attention-7B")
    available = {m for m, _, _ in curves}
    models = [m for m in preferred if m in available] + sorted(available - set(preferred))
    assert len(models) >= 2
    colors = {**MODEL_COLOR, "NOSA-3B": GREEN, "NOSA-8B": PURPLE,
              "MiniCPM4.1-8B": RED, "HiLS-Attention-7B": GRAY}
    grid = np.linspace(0, 1, 401)
    fig, ax = plt.subplots(figsize=(7.0, 3.55))
    legend_cols = min(len(models), 3)
    legend_rows = -(-len(models) // legend_cols)
    fig.subplots_adjust(left=.115, right=.965, bottom=.18, top=.94 - .075 * legend_rows)
    exported = []
    # Marker phases are staggered per model and per window (period 48 grid points = 12 % of the x axis), so the
    # markers of curves that coincide -- NOSA-1B and NOSA-3B are nearly identical -- alternate instead of overlapping.
    for shift, model in enumerate(models):
        color = colors[model]
        for q, marker, offset in ((256, "o", 4), (512, "s", 28)):
            books = sorted(d for m, n, d in curves if m == model and n == q)
            assert books == ["10146", "10321", "10356"], (model, q, books)
            stack = np.vstack([np.interp(grid, *np.array(sorted(curves[(model, q, d)])).T) for d in books])
            median = np.median(stack, axis=0)
            assert np.all(np.diff(median) >= -1e-12)
            assert np.isclose(median[0], 0) and np.isclose(median[-1], 1)
            ax.plot(grid * 100, median * 100, color=color, ls="-", lw=1.7,
                    marker=marker, mfc=color, mec=color, ms=4.5, markevery=(offset + 8 * shift, 48),
                    label=f"{model}, {q} queries")
            exported.append(dict(model=model, subsequent_queries=q, documents=books,
                                 top20_median=float(np.interp(.2, grid, median)),
                                 top20_document_range=[float(np.interp(.2, grid, stack.min(0))),
                                                       float(np.interp(.2, grid, stack.max(0)))],
                                 byte_fraction=grid.tolist(), median_access_coverage=median.tolist()))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 102)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.set_xlabel("History KV bytes in hot set (%)")
    ax.set_ylabel("Selection events covered (%)")
    # Models share colors, windows use filled markers. All coordinates remain exact.
    handles = [Line2D([], [], color=colors[m], lw=1.7, label=m) for m in models]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.55, .995), ncol=legend_cols,
               columnspacing=2.0, handlelength=2.0, handletextpad=.5, borderaxespad=0,
               labelspacing=.3)
    ax.legend(handles=[Line2D([], [], color=INK, ls="-", marker=mark, mfc=INK, ms=4.5,
                              label=f"{q} subsequent queries") for q, mark in ((256, "o"), (512, "s"))],
              loc="lower right", handlelength=2.1, labelspacing=.4, borderaxespad=.7)
    assert all(line.get_linestyle() == "-" for line in ax.lines)
    save(fig, "design-sparse-concentration", evidence="measured", width_in=7.0,
         note=f"{len(models)} native sparse checkpoints: {', '.join(models)}. 3 PG19 documents per model, "
              f"{M} history tokens, first 256/512 subsequent queries from the same causal 512-query capture. "
              "Each model/document/history has one instrumented forward; the two nested windows are not independent repeats. "
              "Only (layer, 64-token block) offline frequency rankings are plotted, containing all KV heads per object. "
              "X divides hot-set bytes by all history KV bytes; Y divides covered selection events by all history "
              "selection events, counting repeats across queries/heads, excluding newly appended KV. "
              "Solid lines are pointwise medians across 3 documents; filled circles/squares distinguish 256/512 queries. "
              "No hollow predictions, span-unit comparisons, guide lines or variability bands; per-document curves "
              "and ranges remain in source tables and the figure JSON. Offline event coverage is not an online hit rate, "
              "attention mass, distinct needed-set coverage, or recovery-byte savings.",
         sources=[str((data_dir / name).relative_to(ROOT))
                  for name in ("concentration_curves_models.csv", "SUMMARY_MODELS.json")])
    MANIFEST["design-sparse-concentration"]["source_sha256"] = {
        path: sha(ROOT / path) for path in MANIFEST["design-sparse-concentration"]["sources"]}
    (OUT / "design-sparse-concentration.json").write_text(
        json.dumps(dict(history_tokens=M, series=exported), indent=2) + "\n")


def figure_needed_fraction(M=32768):
    """Supplement only (former Figure 5 of the 2026-09-15 numbering): needed union and online loader bytes; not in current Motivation."""
    ns = [32, 64, 128, 256, 512]
    fig, b = plt.subplots(figsize=(3.4, 2.9))
    fig.subplots_adjust(left=.24, right=.95, bottom=.175, top=.885)
    for model in ("NOSA-1B", "MiniCPM4-8B"):
        color, marker = MODEL_COLOR[model], MODEL_MARKER[model]
        layers = MODEL_LAYERS[model]
        need = np.array([[NEEDED[(model, M, n, l)]["needed"] for l in range(1, layers + 1)] for n in ns])      # (n, layers)
        eff = np.array([[NEEDED[(model, M, n, l)]["effective"] for l in range(1, layers + 1)] for n in ns])
        q1, q3 = np.percentile(need, [25, 75], axis=1)
        b.fill_between(ns, q1 * 100, q3 * 100, color=color, alpha=.20, lw=0)
        b.plot(ns, eff.mean(1) * 100, marker=marker, color=color, lw=1.2, ls=(0, (3, 2)), ms=5.5, mfc="white", mew=1.4)
        b.plot(ns, need.mean(1) * 100, marker=marker, color=color, lw=1.7, ms=5.5, label=model)
    b.plot([REPLAY_QUERIES, REPLAY_QUERIES], [24, 100], color=GRAY, lw=.7, ls=(0, (1, 2)), zorder=1)
    b.text(68, 99, "one sealed block", ha="left", va="top", color=GRAY)
    b.set_xscale("log", base=2)
    b.set_xticks(ns)
    b.set_xticklabels([str(n) for n in ns])
    b.set_xlim(28, 600)
    b.set_ylim(0, 100)
    b.set_xlabel("Replayed queries after the history")
    b.set_ylabel("Distinct history blocks (%)\n(required or moved by loader)")
    b.legend(handles=[Line2D([], [], color=INK, marker="o", ms=5.5, lw=1.7, label="needed (distinct union)"),
                      Line2D([], [], color=INK, marker="o", ms=5.5, mfc="white", mew=1.4, lw=1.2, ls=(0, (3, 2)), label="online loader (ũ)")],
             loc="lower left", bbox_to_anchor=(0, 0), handlelength=1.6, borderaxespad=0, labelspacing=.2)
    handles = [Line2D([], [], color=BLUE, marker="s", ms=5.5, lw=1.7, label="NOSA-1B"),
               Line2D([], [], color=ORANGE, marker="o", ms=5.5, lw=1.7, label="MiniCPM4-8B")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(.13, 1.0), ncol=2, columnspacing=1.4, handlelength=1.6,
               handletextpad=.5, borderaxespad=0)
    save(fig, "motivation-needed-fraction", evidence="measured", width_in=3.4,
         note="Same traces as design-sparse-concentration (32K history); n=512 uses its exact same query window. "
              "Y denominator = all history blocks in a layer, each including all KV heads. Filled: distinct blocks selected at least once "
              "by the next n queries; repeated selections count once. Mean over documents then layers, band = interquartile range over "
              "document-averaged layers (not a confidence interval). Hollow: trace-derived union of preloaded and needed blocks = ũ "
              "(preload by previous 512-query rank up to the previous n-query union size, then demand-fetch misses). Assumes no eviction "
              "or repeat transfer; not a measured DMA trace or peak concurrent residency. Dotted line: one 64-token sealed block, "
              "the worst-case unsealed tail. Event coverage in Figure 6 cannot be interpreted as distinct-block coverage here.",
         sources=["benchmark/AegisKV/experiments/native-sparse/20260915/needed_fraction_models.csv"])


# ----------------------------------------------------------------------------------------
# Figures 7 and 9 (analytic): layer-major recovery and quotas; measured MiniCPM4-8B calibration.
# ----------------------------------------------------------------------------------------
CTX_REF = 32768
D_MS = CTX_REF * KV_PER_TOKEN_LAYER / BETA_REMOTE * 1e3      # 5.37 ms per layer: 32 MiB over 6.25 GB/s
C_MS = replay_ms_per_layer(CTX_REF)                          # measured: 64-token replay at 32K, per layer


def pipeline(resident_layers, per_layer_ms, compute_ms, layers=LAYERS, layer_major=True):
    """Layer-major: sequential stream of non-resident layers from t=0, layer l computes after its KV and layer l-1.
    Token-block order (all layers per span): nothing can compute before the whole history has arrived."""
    if layer_major:
        ready = np.array([0.0 if l < resident_layers else (l - resident_layers + 1) * per_layer_ms for l in range(layers)])
    else:
        ready = np.full(layers, (layers - resident_layers) * per_layer_ms)
    start, finish, prev = np.zeros(layers), np.zeros(layers), 0.0
    for l in range(layers):
        start[l] = max(prev, ready[l])
        finish[l] = start[l] + compute_ms
        prev = finish[l]
    return ready, start, finish


def w0(per_layer_ms, compute_ms, layers=LAYERS):
    return per_layer_ms + (layers - 1) * max(per_layer_ms - compute_ms, 0.0)


def sparse_pipeline(peer_front_layers, preload_fraction, effective_fraction, compute_ms,
                    full_layer_ms, layers=LAYERS):
    """One ideal preemptible copy stream, with demand fetch released at each layer.

    Only the previous-window Top-k preload set of the first peer_front_layers is
    resident. Misses still need H2D, and are known only after the previous layer
    finishes. Layer-major preloads run in the gaps; cold blocks follow all replay
    work. Fractions are homogeneous layer/document means, not a hardware trace.
    """
    if not 0 <= peer_front_layers <= layers:
        raise ValueError("Peer layer count must be within the model")
    if not 0 <= preload_fraction <= effective_fraction <= 1:
        raise ValueError("Expected 0 <= preload <= effective <= 1")
    if compute_ms <= 0 or full_layer_ms <= 0:
        raise ValueError("Layer durations must be positive")
    remaining = np.full(layers, preload_fraction * full_layer_ms)
    remaining[:peer_front_layers] = 0.0
    miss_ms = (effective_fraction - preload_fraction) * full_layer_ms
    start, finish = np.zeros(layers), np.zeros(layers)
    transfers = []  # (kind, layer, start_ms, duration_ms)
    t = 0.0

    def preload_until(deadline):
        nonlocal t
        for layer in range(layers):
            if t >= deadline:
                break
            duration = min(remaining[layer], deadline - t)
            if duration > 1e-9:
                transfers.append(("preload", layer, t, duration))
                remaining[layer] = max(0.0, remaining[layer] - duration)
                t += duration
        t = deadline

    for layer in range(layers):
        # Query-dependent misses are released here, never prefetched as an oracle.
        if miss_ms > 1e-9:
            transfers.append(("demand", layer, t, miss_ms))
            t += miss_ms
        if remaining[layer] > 1e-9:
            transfers.append(("preload", layer, t, remaining[layer]))
            t += remaining[layer]
            remaining[layer] = 0.0
        start[layer] = t
        finish[layer] = t + compute_ms
        preload_until(finish[layer])

    cold_ms = layers * (1 - effective_fraction) * full_layer_ms
    if cold_ms > 1e-9:
        # Includes unprotected cold KV in the Peer-protected front layers as well.
        transfers.append(("cold", -1, t, cold_ms))
    peer_layer_equivalents = peer_front_layers * preload_fraction
    transferred_ms = sum(duration for _, _, _, duration in transfers)
    assert np.isclose(transferred_ms / full_layer_ms + peer_layer_equivalents, layers)
    return start, finish, transfers


def topk_peer_frontier(preload_fraction, effective_fraction, compute_ms, full_layer_ms,
                       layers=LAYERS):
    """Smallest front-layer prefix reaching the modeled demand-only wait floor.

    Scan the same causal Top-k pipeline used in Figure 7. This is an analytic
    comparison point for a fixed hot-set size, not an online oracle or an optimum
    over arbitrary block placements. Keep the scan for reproducible selection.
    """
    scan = []
    for front_layers in range(layers + 1):
        _, finish, _ = sparse_pipeline(front_layers, preload_fraction, effective_fraction,
                                       compute_ms, full_layer_ms, layers=layers)
        scan.append(dict(peer_front_layers=front_layers,
                         exposed_wait_ms=float(max(finish[-1] - layers * compute_ms, 0.0))))
    floor_ms = layers * (effective_fraction - preload_fraction) * full_layer_ms
    tolerance_ms = 1e-8 * max(1.0, layers * (compute_ms + full_layer_ms))
    assert np.isclose(scan[-1]["exposed_wait_ms"], floor_ms, rtol=0, atol=tolerance_ms)
    frontier = next(row["peer_front_layers"] for row in scan
                    if row["exposed_wait_ms"] <= floor_ms + tolerance_ms)
    return frontier, float(floor_ms), scan


def figure_pipeline():
    h = u_profile("MiniCPM4-8B", quantity="preload")
    k, demand_floor_ms, frontier_scan = topk_peer_frontier(h, U_REQ, C_MS, D_MS)
    # Same recovery endpoint in every panel: rebuild KV through the known tail.
    # No one-shot 32K+64 prefill was measured. Compose the measured 32K prefill
    # with the existing calibrated tail cost, and expose that provenance.
    history_row = next(row for row in LAT_META_M["rows"] if row["context"] == CTX_REF)
    history_s = float(history_row["prefill_median_s"])
    tail_s = float(LAYERS * C_MS / 1e3)
    full_total_s = history_s + tail_s
    full_reference = dict(
        history_tokens=CTX_REF, tail_tokens=REPLAY_QUERIES,
        total_tokens=CTX_REF + REPLAY_QUERIES,
        history_prefill_measured_s=history_s, tail_calibrated_s=tail_s,
        total_s=full_total_s, history_timing_repeats=len(history_row["prefill_s"]),
        evidence="composed measured-cost reference, not a measured one-shot full-token run",
        protocol="recompute the 32K history from scratch, then the known 64-token tail; no KV restore",
    )
    variants = [("(b) Token-block order (whole history first)", None),
                ("(c) Layer-major, full-KV loading", None),
                ("(d) Layer-major, online loader (preload + demand fetch)", 0),
                (f"(e) Online loader + Top-k hot blocks of layers 1\u2013{k} in Peer HBM ({k*h*32:.0f} MiB)", k)]
    fig = plt.figure(figsize=(10.0, 6.0))
    full_ax = fig.add_axes([.13, .72, .86, .16])
    # An aggregate history bar avoids inventing unmeasured per-layer prefill timings.
    full_ax.barh(0, history_s, height=.62, color=PURPLE, edgecolor="white", lw=.3)
    full_ax.barh(0, tail_s, left=history_s, height=.62, color=GRAY, edgecolor="white", lw=.3)
    full_ax.text(history_s / 2, 0, f"32K-token history prefill: {history_s:.2f} s (measured)",
                 ha="center", va="center", color="white")
    full_ax.text(.08, 1, "no KV restore", ha="left", va="center", color=BLUE)
    full_ax.annotate(f"64-token tail: {tail_s:.3f} s", xy=(history_s + tail_s / 2, .32),
                     xytext=(history_s - 1.5, 1.03), ha="left", va="center", color=INK,
                     arrowprops=dict(arrowstyle="-", color=GRAY, lw=.7))
    full_ax.text(full_total_s + .10, 0, f"total ~{full_total_s:.2f} s",
                 ha="left", va="center", color=INK)
    full_ax.text(0, 1.58, "(a) Full recompute without KV backup (seconds)",
                 ha="left", va="bottom", weight="bold", color=INK)
    full_ax.set_yticks([0, 1])
    full_ax.set_yticklabels(["Full recompute", "H2D"])
    full_ax.get_yticklabels()[1].set_color(BLUE)
    full_ax.set_ylim(-.5, 2.30)
    full_ax.set_xlim(0, np.ceil(full_total_s + 1))
    full_ax.set_xticks(np.arange(0, np.ceil(full_total_s) + 1, 1))
    full_ax.tick_params(axis="y", length=0)
    full_ax.set_xlabel("Time after take-over starts (s)")
    grid = fig.add_gridspec(len(variants), 1, left=.13, right=.99, bottom=.08, top=.555, hspace=.45)
    axes = []
    for i in range(len(variants)):
        axes.append(fig.add_subplot(grid[i], sharex=axes[0] if axes else None))
        if i < len(variants) - 1:
            axes[-1].tick_params(axis="x", labelbottom=False)
    waits, totals = [], []
    xmax = 0.0
    colors = {"preload": BLUE, "demand": ORANGE, "cold": PALE_BLUE}
    for i, (ax, (label, peer_layers)) in enumerate(zip(axes, variants)):
        if peer_layers is None:
            _, start, finish = pipeline(0, D_MS, C_MS, layer_major=(i == 1))
            transfers = [("preload", l, l * D_MS, D_MS) for l in range(LAYERS)]
        else:
            start, finish, transfers = sparse_pipeline(peer_layers, h, U_REQ, C_MS, D_MS)
        for kind, _, left, duration in transfers:
            ax.barh(1, duration, left=left, height=.62, color=colors[kind],
                    edgecolor="white", lw=.25, hatch="///" if kind == "demand" else None)
        for l in range(LAYERS):
            ax.barh(0, C_MS, left=start[l], height=.62, color=GRAY, edgecolor="white", lw=.3)
            previous = finish[l - 1] if l else 0.0
            if start[l] - previous > 1e-9:
                ax.barh(0, start[l] - previous, left=previous, height=.62, color=RED, edgecolor="none")
        wait = max(finish[-1] - LAYERS * C_MS, 0.0)
        waits.append(float(wait))
        totals.append(float(finish[-1]))
        ax.text(finish[-1] + 4, 0, f"wait {wait:.0f} ms", ha="left", va="center", color=RED)
        ax.text(0, 1.58, label, ha="left", va="bottom", weight="bold", color=INK)
        ax.text(1, 1.58, f"total {finish[-1]:.0f} ms", transform=ax.get_yaxis_transform(),
                ha="right", va="bottom", color=INK)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["Tail recompute", "H2D"])
        ax.get_yticklabels()[1].set_color(BLUE)
        ax.set_ylim(-.5, 2.30)
        ax.tick_params(axis="y", length=0)
        xmax = max(xmax, finish[-1], max(left + duration for _, _, left, duration in transfers))
    top = np.ceil((xmax + 35) / 25) * 25
    for ax in axes:
        ax.set_xlim(0, top)
        ax.set_xticks(np.arange(0, xmax + 1, 50))
    axes[-1].set_xlabel("Time after take-over starts (ms)")
    handles = [Patch(color=BLUE, label="H2D: full KV / preload"),
               Patch(facecolor=ORANGE, edgecolor="white", hatch="///", label="H2D: demand fetch (misses)"),
               Patch(color=PALE_BLUE, label="H2D: cold KV"),
               Patch(color=GRAY, label="Tail recompute (one layer)"), Patch(color=RED, label="Wait for KV"),
               Patch(color=PURPLE, label="Full-history prefill")]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, .995), ncol=3, columnspacing=1.3,
               handlelength=1.1, handletextpad=.4, borderaxespad=0, labelspacing=.35)
    fig.text(.13, .610, "(b\u2013e) Recovery with KV backup (milliseconds; note the change of time scale)",
             ha="left", va="bottom", color=INK, weight="bold")
    fig.text(.13, .582, f"Top-k in (e): hot set of the previous window (~{h:.0%} of each layer); all other KV stays in DRAM",
             ha="left", va="bottom", color=INK)
    save(fig, "design-layer-pipeline", evidence="analytic", width_in=10.0,
         note=f"Panel (a) is a composed measured-cost reference for full-token recomputation without KV backup: "
              f"32K history prefill {history_s:.9f} s (median of {len(history_row['prefill_s'])} timing repeats, random IDs, "
              f"batch 1, native sparse path, {GPU_NAME}) plus the same calibrated known 64-token tail {tail_s:.9f} s "
              f"as (b-e), total {full_total_s:.9f} s for {CTX_REF + REPLAY_QUERIES} tokens. "
              "Not a measured one-shot 32K+64 run or end-to-end failure recovery. Purple is one aggregate prefill bar, "
              "not measured per-layer timing; panel (a) gray is the entire tail. No history-KV H2D restore. "
              "Panel (a) uses seconds on a separate linear axis; panels (b-e) share an expanded millisecond axis. "
              "Cross-panel bar lengths between these two scales must not be compared. "
              f"Panels (b-e) are analytic pipelines, 32 layers, 32K history (32 MiB of KV per layer, MiniCPM4-8B), H2D {BETA_REMOTE / 1e9:.2f} GB/s: "
              f"D = {D_MS:.2f} ms; C = {C_MS:.2f} ms from the measured 64-token tail recomputation on {GPU_NAME}. "
              "Tail recomputation is a forward pass over known, previously generated tail tokens to rebuild unbacked KV, "
              "not token resampling or full-prefix recomputation. In (b-e), gray blocks show one layer of compute; red shows KV wait. "
              f"Homogeneous means over documents then layers: preload h = {h:.6f}, effective ũ = {U_REQ:.6f}; "
              f"miss fraction = ũ-h = {U_REQ-h:.6f}. Top-k is the past-window hot set, with its size estimated from the previous "
              "64-query union, not the selector's per-query total budget of 96 blocks and not an oracle union. "
              f"Only this set of layers 1-{k} resides in Peer HBM ({k*h*32:.1f} MiB, not {k*32} MiB of full layers). "
              f"The layer count is recomputed by scanning 0-{LAYERS}: {k} is the smallest front-layer prefix reaching "
              f"the demand-only wait floor {demand_floor_ms:.6f} ms for the fixed hot-set fraction; "
              "this is not an optimum over arbitrary block placements or a fixed deployment parameter. "
              "Demand copies are released after the preceding layer computes and preempt layer-major preloads. "
              "Orange hatching shows misses, including those in Peer-protected layers. All nonresident cold KV, including "
              "cold blocks of the front layers, is copied after tail recomputation. Bytes are conserved across Peer, preload, demand and cold. "
              f"Exposed waits (b)-(e): {', '.join(f'{v:.3f}' for v in waits)} ms; zero wait is not assumed. "
              f"Totals through tail completion (b)-(e): {', '.join(f'{v:.3f}' for v in totals)} ms, "
              f"including the common {tail_s * 1e3:.3f} ms of pure tail compute but not the cold-KV completion time. "
              "Token-block baseline assumes a full-history barrier. One ideally preemptible copy stream, no launch/selection "
              "overhead or interference; all panels exclude detection, queueing, token-ID transfer and weight loading. "
              "The pipelines are not hardware measurements.",
         sources=["benchmark/AegisKV/experiments/native-sparse/20260915/prefill-latency-minicpm4-8b.json", "benchmark/AegisKV/experiments/native-sparse/20260915/replay-latency-minicpm4-8b.json",
                  "benchmark/AegisKV/experiments/native-sparse/20260915/needed_fraction_models.csv"])
    return dict(peer_front_layers=k, preload_fraction=h, effective_fraction=U_REQ,
                peer_mib=k*h*32, exposed_wait_ms=waits, demand_wait_floor_ms=demand_floor_ms,
                pipeline_panels=["b", "c", "d", "e"], tail_completion_ms=totals,
                full_token_recompute=full_reference,
                time_axes=dict(a="seconds", b_to_e="milliseconds; independent expanded scale"),
                selection_rule="smallest front-layer prefix reaching the demand-only wait floor",
                frontier_scan=frontier_scan)


def coverage_curves(M=32768, n=REPLAY_QUERIES):
    """Mean over layers and documents: fraction of the blocks a replay of n queries needs that are resident after the
    hottest h fraction of the layer has been preloaded (previous-window rank) or the most recent h fraction (recency)."""
    table = defaultdict(lambda: defaultdict(list))
    with open(SPARSE / "needed_coverage_models.csv") as f:
        for r in csv.DictReader(f):
            if int(r["M"]) == M and int(r["replay_queries"]) == n:
                k = (r["model"], float(r["preloaded_fraction"]))
                table[k]["hot"].append(float(r["needed_covered_hot_first"]))
                table[k]["recency"].append(float(r["needed_covered_recency_first"]))
    out = {}
    for model in MODEL_LAYERS:
        hs = sorted({h for m, h in table if m == model})
        out[model] = (np.array(hs), np.array([np.mean(table[(model, h)]["hot"]) for h in hs]),
                      np.array([np.mean(table[(model, h)]["recency"]) for h in hs]))
    return out


def figure_needed_coverage():
    """Figure 8: online preload coverage, independent of the analytic Peer-byte model."""
    fig, ax = plt.subplots(figsize=(3.4, 2.9))
    fig.subplots_adjust(left=.19, right=.95, bottom=.20, top=.83)
    cov = coverage_curves()
    for model in ("NOSA-1B", "MiniCPM4-8B"):
        hs, hot, rec = cov[model]
        color = MODEL_COLOR[model]
        uo = U_ORACLE[model]
        ax.plot(hs * 100, np.minimum(hs / uo, 1) * 100, color=color, lw=.9, ls=(0, (1, 1.5)), zorder=2)
        ax.plot(hs * 100, rec * 100, color=color, lw=1.4, ls=(0, (3, 2)), zorder=3)
        ax.plot(hs * 100, hot * 100, color=color, lw=1.8, marker=MODEL_MARKER[model],
                ms=3.5, markevery=4, zorder=4, label=model)
        ax.plot([uo * 100], [100], marker=MODEL_MARKER[model], color=color, ms=6,
                mfc="white", mew=1.4, zorder=5, clip_on=False)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Layer bytes preloaded (%)")
    ax.set_ylabel("Needed blocks resident (%)")
    models = [Line2D([], [], color=MODEL_COLOR[m], marker=MODEL_MARKER[m], ms=5,
                     lw=1.7, label=m) for m in ("NOSA-1B", "MiniCPM4-8B")]
    fig.legend(handles=models, loc="upper center", bbox_to_anchor=(.54, .99), ncol=2,
               columnspacing=.9, handlelength=1.2, handletextpad=.4, borderaxespad=0)
    ax.legend(handles=[Line2D([], [], color=INK, lw=1.8, label="hot-first"),
                       Line2D([], [], color=INK, lw=1.4, ls=(0, (3, 2)), label="recency-first"),
                       Line2D([], [], color=INK, lw=.9, ls=(0, (1, 1.5)), label="oracle")],
              loc="lower right", handlelength=2.0, borderaxespad=.3, labelspacing=.25)
    save(fig, "design-needed-coverage", evidence="measured", width_in=3.4,
         note="Figure 8 (Figure 7 in the 2026-09-15 numbering): native selected-block traces, 32K history, 64-query replay, "
              "3 PG19 documents per model, mean over layers and documents. X divides preloaded bytes by all history KV "
              "in the layer; Y divides resident needed blocks by the replay's needed set. Solid = previous-window "
              "hotness rank; dashed = most-recent-first. Dotted oracle guide = min(preloaded fraction / mean needed "
              "fraction, 1), not the mean of per-layer oracle curves; hollow endpoint = mean needed fraction. "
              "The unmeasured y=x diagonal and its token-order legend were removed; all remaining curve values are unchanged.",
         sources=["benchmark/AegisKV/experiments/native-sparse/20260915/needed_coverage_models.csv",
                  "benchmark/AegisKV/experiments/native-sparse/20260915/needed_fraction_models.csv"])


def figure_wait_bytes():
    """Figure 9: exposed wait against Peer-resident bytes in the causal Top-k pipeline of Figure 7.

    Every curve keeps the hot set of the first L layers in Peer HBM (L = 0..32, so the x axis grows in steps of one
    layer's hot set) and preloads/demand-fetches everything else from DRAM.  The wait falls to the demand floor
    N (u-tilde - h) D and then stays there; the triangle marks the footprint F and the layer count L at which the
    floor is reached.  No Slack enters this figure: the footprint is a property of the request (context, model
    profile, bandwidth), not of its deadline."""
    fig, ax = plt.subplots(figsize=(3.4, 3.15))
    fig.subplots_adjust(left=.18, right=.95, bottom=.18, top=.76)
    layer_mib = CTX_REF * KV_PER_TOKEN_LAYER / 2**20                 # 32 MiB of KV per layer at 32K
    profiles = [("Full-layer load", 1.0, 1.0, GRAY, (12, 8)),
                ("MiniCPM4-8B profile", u_profile("MiniCPM4-8B", quantity="preload"), U_PROFILES["MiniCPM4-8B"], ORANGE, (10, 10)),
                ("NOSA-1B profile", u_profile("NOSA-1B", quantity="preload"), U_PROFILES["NOSA-1B"], BLUE, (10, -14))]
    summary = {}
    for label, h, u, color, offset in profiles:
        k, floor, scan = topk_peer_frontier(h, u, C_MS, D_MS)
        bytes_mib = np.array([row["peer_front_layers"] * h * layer_mib for row in scan])
        waits = np.array([row["exposed_wait_ms"] for row in scan])
        ax.step(bytes_mib, waits, where="post", color=color, lw=1.8, zorder=3,
                label=f"{label}, {bytes_mib[k]:.0f} MiB")
        if floor > 0:
            ax.axhline(floor, color=color, lw=.8, ls=(0, (4, 2)), zorder=1)
        ax.plot([bytes_mib[k]], [waits[k]], marker="v", color=color, ms=8, mec=INK, mew=.6, zorder=4)
        ax.annotate(f"L = {k}", xy=(bytes_mib[k], waits[k]), xytext=offset, textcoords="offset points",
                    ha="left", va="center", color=color,
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=.8, shrinkA=0, shrinkB=4))
        summary[label] = dict(h=h, u_tilde=u, w0_ms=float(waits[0]), floor_ms=floor, front_layers=k,
                              footprint_mib=float(bytes_mib[k]),
                              closed_form_footprint_mib=float(BETA_REMOTE * max(waits[0] - floor, 0.0) / 1e3 / 2**20))
    ax.text(660, summary["MiniCPM4-8B profile"]["floor_ms"] + 2.5, "demand floor", ha="right", va="bottom", color=GRAY)
    ax.set_xlim(0, 672)
    ax.set_ylim(0, 100)
    ax.set_xticks([0, 128, 256, 384, 512, 640])
    ax.set_xlabel("Peer-resident bytes (MiB)")
    ax.set_ylabel("Exposed wait (ms)")
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(.16, .995),
               handlelength=2.0, borderaxespad=0, labelspacing=.25)
    save(fig, "design-wait-vs-bytes", evidence="analytic", width_in=3.4,
         note=f"Figure 9 (Figure 8 in the 2026-09-15 numbering): the causal Top-k pipeline of Figure 7 scanned over the number "
              f"of front layers whose hot set (fraction h of the layer) resides in Peer HBM; x = L*h*{layer_mib:.0f} MiB, so the "
              f"curves are step functions with one step per layer. All curves hold MiniCPM4-8B's {LAYERS} layers, "
              f"{layer_mib:.0f} MiB per layer, C = {C_MS:.2f} ms and {BETA_REMOTE / 1e9:.2f} GB/s H2D (D = {D_MS:.2f} ms) fixed; "
              "only the (h, u-tilde) profile changes. Dashed horizontal lines are the demand floors N*(u-tilde-h)*D; "
              "triangles mark the footprint F = smallest front-layer prefix whose wait reaches the floor, with its layer count L. "
              + "; ".join(f"{k}: h = {v['h']:.4f}, u-tilde = {v['u_tilde']:.4f}, W0 = {v['w0_ms']:.2f} ms, floor = {v['floor_ms']:.2f} ms, "
                          f"L = {v['front_layers']}, F = {v['footprint_mib']:.1f} MiB (closed form beta*(W0-floor) = "
                          f"{v['closed_form_footprint_mib']:.1f} MiB)" for k, v in summary.items())
              + ". The former fluid curve W(x) = [W0 - x/beta]+ and the Slack-dependent useful quota B_use were removed: the "
              "footprint no longer depends on Slack. Controlled profile comparison, not measured per-model recovery latency.",
         sources=["benchmark/AegisKV/experiments/native-sparse/20260915/prefill-latency-minicpm4-8b.json",
                  "benchmark/AegisKV/experiments/native-sparse/20260915/replay-latency-minicpm4-8b.json",
                  "benchmark/AegisKV/experiments/native-sparse/20260915/needed_fraction_models.csv"])
    return summary


# HISTORICAL ONLY: retired serial-queue example, excluded from current paper rendering.
CASCADE_P = np.array([.5, .3, .4])       # s of shared-path load each request needs before replay
CASCADE_D = np.array([.4, .5, 1.0])      # s: deadline = sigma - R_floor
CASCADE_BUDGET = .2                      # s of load worth of Peer bytes


def cascade_schedule(x, p=CASCADE_P, d=CASCADE_D):
    C = np.cumsum(p - x)
    return C, np.maximum(C - d, 0)


def allocate_isolated(p=CASCADE_P, d=CASCADE_D, budget=CASCADE_BUDGET):
    x, rem = np.zeros(len(p)), budget
    for i in range(len(p)):
        give = min(max(p[i] - d[i], 0), rem)         # own exposure when alone on the path
        x[i], rem = give, rem - give
    return x


def allocate_cascade(p=CASCADE_P, d=CASCADE_D, budget=CASCADE_BUDGET):
    x, rem = np.zeros(len(p)), budget
    for i in range(len(p)):
        if rem <= 0:
            break
        _, tard = cascade_schedule(x, p, d)
        down = tard[i:].max()
        if down <= 0:
            continue
        give = min(p[i] - x[i], rem, down)
        x[i], rem = x[i] + give, rem - give
    return x


def figure_cascade():
    """Design figure: isolated B_use wastes budget on a shared path; cascade-aware allocation front-loads it."""
    colors = (BLUE, ORANGE, GREEN)
    fig, axes = plt.subplots(2, 1, figsize=(3.4, 2.7), sharex=True)
    fig.subplots_adjust(left=.13, right=.975, bottom=.175, top=.86, hspace=.55)
    for ax, x, label in zip(axes, (allocate_isolated(), allocate_cascade()), ("Isolated $B_{use}$", "Cascade-aware")):
        C, tard = cascade_schedule(x)
        left = 0.0
        for i in range(3):
            y = 2 - i
            ax.barh(y, CASCADE_P[i] - x[i], left=left, height=.6, color=colors[i], edgecolor="white", lw=.5)
            if x[i] > 0:                                        # bytes served from Peer HBM: no path time
                ax.barh(y, x[i], left=left + CASCADE_P[i] - x[i], height=.6, color="white", edgecolor=colors[i], lw=1.0, hatch="////")
            ax.plot([CASCADE_D[i]], [y], marker="v", color="white", mec=INK, mew=1.2, ms=8, zorder=4)
            if tard[i] > 0:
                ax.plot([CASCADE_D[i], C[i]], [y - .42, y - .42], color=RED, lw=3.0, solid_capstyle="butt", zorder=3)
            left = C[i]
        ax.set_yticks([2, 1, 0])
        ax.set_yticklabels([f"R{i + 1}" for i in range(3)])
        ax.tick_params(axis="y", length=0)
        ax.text(0, 2.62, label, ha="left", va="bottom", weight="bold", color=INK)
        ax.text(1.3, 2.62, f"total tardiness {tard.sum():.1f} s", ha="right", va="bottom", color=RED)
        ax.set_ylim(-.6, 3.25)
        ax.set_xlim(0, 1.3)
    axes[1].set_xlabel("Time on the shared H2D path (s)")
    handles = [Line2D([], [], marker="v", ls="none", color="white", mec=INK, mew=1.2, ms=7, label="deadline"),
               Patch(facecolor="white", edgecolor=INK, hatch="////", label="saved by Peer"),
               Line2D([], [], color=RED, lw=3, label="tardiness")]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.51, 1.0), ncol=3, columnspacing=.6,
               handlelength=1.0, handletextpad=.3, borderaxespad=0)
    save(fig, "design-cascade", evidence="analytic", width_in=3.4,
         note="Worked example: three requests recover on one shared path in EDD order; load times 0.5/0.3/0.4 s, deadlines 0.4/0.5/1.0 s, "
              "Peer budget worth 0.2 s of load. Isolated B_use gives R1 0.1 s and leaves 0.1 s unused because R2 and R3 look safe alone "
              "(total tardiness 0.3 s); the cascade-aware rule gives all 0.2 s to R1, which also advances R2 and R3 (0.1 s). Hatched = bytes "
              "served from Peer HBM (no path time). Illustrative numbers.",
         sources=["render_draft_20260915.py::allocate_cascade"])


# ----------------------------------------------------------------------------------------
# Illustrative placement/recovery model for the evaluation section.
# ----------------------------------------------------------------------------------------
# HISTORICAL ONLY: this serial-recovery model does not implement current Paper_Draft.md §3.
class Model:
    """Small analytic model of workflows, co-located recoveries on one fixed Retry DP, and WCT penalty.

    Every number it produces is illustrative.  The design of the experiments (paired F0/F1 on the same
    workflow set, aligned failure progress, position sweep, ablation, sensitivity) is what the figures fix.
    Sizes and costs are MiniCPM4-8B's (1 KiB of KV per token per layer, 32 layers, measured prefill and replay
    costs on the A100); u is the measured effective path fraction of the online loader (hot-first preload + demand
    fetch) for a 64-query replay of the selected selector profile (Fig. 5, hollow markers).
    This illustrative model retains the fluid approximation, not Figure 7's demand-release schedule.
    """
    R_FLOOR = 0.5            # s: detection + reroute + admission on the Retry DP; identical for every system
    CO_LOCATED = 8           # requests active on the failed GPU; they recover together on the Retry DP
    PEER_BUDGET = 4 * 2**30  # bytes of Peer HBM reserved for backups on one Retry DP
    KAPPA = 0.10             # fraction of copy time that shows up as foreground slowdown (normal path)
    POSITIONS = ["Pre", "B1", "B2", "B3", "B4", "B5", "Join"]   # B1 = longest branch (Slack 0)

    def __init__(self, seed=20260915, workflows=160, branches=5, u=U_REQ):
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.u = u
        self.n = workflows
        pre = self.rng.lognormal(np.log(20), .5, workflows)
        br = np.sort(self.rng.lognormal(np.log(60), .9, (workflows, branches)), axis=1)[:, ::-1]   # B1 longest
        join = self.rng.lognormal(np.log(15), .4, workflows)
        self.duration = np.column_stack([pre, br, join])                       # (n, 7) seconds
        self.ctx = np.round(2 ** self.rng.uniform(14, 17, (workflows, branches + 2)) / 1024) * 1024
        self.slack = np.zeros_like(self.duration)
        self.slack[:, 1:branches + 1] = br[:, :1] - br                          # longest branch has 0 slack
        self.wct = pre + br[:, 0] + join

    # ---- placement ------------------------------------------------------------------
    def w0_dram_est(self, ctx, beta):
        """Exposed wait the system expects if this request recovers from DRAM with the co-located set (dense, FIFO share)."""
        per_layer = ctx * KV_PER_TOKEN_LAYER / beta * 1e3 * self.CO_LOCATED / 2
        c = replay_ms_per_layer(ctx)
        return (per_layer + (LAYERS - 1) * max(per_layer - c, 0)) / 1e3

    def w0_isolated(self, ctx, beta, sparse=True):
        """Exposed wait of this request if it were alone on the path (Sec. 3.3 closed form, hot-first if sparse)."""
        u = self.u if sparse else 1.0
        per_layer = u * ctx * KV_PER_TOKEN_LAYER / beta
        c = replay_ms_per_layer(ctx) / 1e3
        return per_layer + (LAYERS - 1) * max(per_layer - c, 0)

    def tiers(self, ctx, slack, beta=BETA, sparse=True, use_slack=True):
        """Return (dram_bytes, isolated B_use bytes, needs_peer) for one request.

        Tier R (no copy) if the Slack absorbs a full recompute; otherwise a DRAM copy.  The isolated B_use is the
        draft-v1 rule beta*min{W0, [R_floor + W0 - sigma]+} with W0 computed for the request alone; the cascade-aware
        allocation in place() replaces it for the full system and it survives only as the "no_cascade" ablation."""
        c_tot = replay_ms_per_layer(ctx) * LAYERS / 1e3
        if use_slack and slack >= self.R_FLOOR + recompute_s(ctx) + c_tot:
            return 0, 0, False                                                # tier R: recompute is absorbed
        w0_ = self.w0_isolated(ctx, beta, sparse)
        exposure = (self.R_FLOOR + w0_ - slack) if use_slack else w0_
        needs_peer = exposure > 0
        b_use = beta * min(w0_, max(exposure, 0.0))
        return kv_bytes(ctx), int(min(b_use, (self.u if sparse else 1.0) * kv_bytes(ctx))), needs_peer

    @staticmethod
    def edd_order(slack, need):
        """Algorithm 1, line 6: earliest deadline first; ties (same Slack) broken by the shorter gating load first (SPT),
        which minimises the total tardiness of a group that is late together."""
        return np.lexsort((np.asarray(need), np.asarray(slack)))

    def place(self, ctx, slack, system, beta=BETA, peer_budget=None):
        """Placement for the CO_LOCATED requests of one GPU. Returns dict of arrays."""
        peer_budget = self.PEER_BUDGET if peer_budget is None else peer_budget
        n = len(ctx)
        dram = np.zeros(n)
        peer = np.zeros(n)
        if system == "recompute":
            return dict(dram=dram, peer=peer, hot_first=False)
        if system in ("dram", "uniform"):
            dram[:] = [kv_bytes(c) for c in ctx]
            if system == "uniform":
                peer[:] = np.minimum(peer_budget / n, dram)                     # equal split, token-prefix fill
            return dict(dram=dram, peer=peer, hot_first=False)
        sparse = system != "no_sparse"
        use_slack = system != "no_slack"
        caps = np.zeros(n)
        for i in range(n):
            dram[i], caps[i], _ = self.tiers(ctx[i], slack[i], beta, sparse, use_slack)
        if system == "no_peer":
            return dict(dram=dram, peer=peer, hot_first=sparse)
        u = self.u if sparse else 1.0
        need = u * dram                                                        # bytes that gate replay
        if not use_slack:                                                      # equal split, no tiers
            peer[:] = np.minimum(need, peer_budget / n)
            return dict(dram=dram, peer=peer, hot_first=sparse)
        order = [int(i) for i in self.edd_order(slack, need) if dram[i] > 0]
        remaining = peer_budget
        if system == "no_cascade":                                             # draft-v1 rule: isolated B_use, sigma order
            for i in order:
                take = min(caps[i], remaining)
                peer[i], remaining = take, remaining - take
            return dict(dram=dram, peer=peer, hot_first=sparse)
        # Cascade-aware water-filling on the joint EDD schedule (Sec. 3.4, Proposition 1):
        # a byte given to the i-th request advances every request behind it on the shared path.
        c_layer = np.array([replay_ms_per_layer(c) for c in ctx]) / 1e3
        for k, i in enumerate(order):
            if remaining <= 0:
                break
            S = np.cumsum([(need[j] - peer[j]) / beta for j in order])
            C = self.R_FLOOR + S + c_layer[order]
            tard = np.maximum(C - slack[order], 0)
            down = tard[k:].max()
            if down <= 0:
                continue
            give = min(need[i] - peer[i], remaining, beta * down)
            peer[i], remaining = peer[i] + give, remaining - give
        return dict(dram=dram, peer=peer, hot_first=sparse)

    # ---- recovery on the Retry DP ---------------------------------------------------
    def recover(self, ctx, slack, system, beta=BETA, peer_budget=None):
        """Recovery finish time (s after R_FLOOR) of every co-located request, plus per-request breakdown."""
        n = len(ctx)
        pl = self.place(ctx, slack, system, beta, peer_budget)
        c_layer = np.array([replay_ms_per_layer(c) for c in ctx]) / 1e3
        c_tot = c_layer * LAYERS
        finish = np.zeros(n)
        wait = np.zeros(n)
        compute = np.zeros(n)
        streamed = np.zeros(n)
        if system == "recompute":
            t = 0.0
            for i in range(n):                                                 # FIFO on the shared GPU
                compute[i] = recompute_s(ctx[i]) + c_tot[i]
                t += compute[i]
                finish[i] = t
            return finish, dict(wait=finish - compute, compute=compute, streamed=streamed, finish=finish, **pl)
        u = self.u if pl["hot_first"] else 1.0
        order = (self.edd_order(slack, u * pl["dram"]) if system in ("aegis", "no_sparse", "no_peer", "no_cascade")
                 else np.arange(n))
        t = 0.0
        for i in order:
            if pl["dram"][i] == 0:                                             # tier R: recompute in the background stream slot
                compute[i] = recompute_s(ctx[i]) + c_tot[i]
                finish[i] = compute[i]
                continue
            need = max(u * pl["dram"][i] - pl["peer"][i], 0)                   # bytes that must arrive before replay can pass
            first_ready = t + min(need, u * ctx[i] * KV_PER_TOKEN_LAYER) / beta if pl["peer"][i] == 0 else 0.0
            t += need / beta
            streamed[i] = need
            ready_all = t
            start = first_ready
            compute[i] = c_tot[i]
            finish[i] = max(ready_all + c_layer[i], start + c_tot[i])
            wait[i] = finish[i] - c_tot[i]
        return finish, dict(wait=wait, compute=compute, streamed=streamed, finish=finish, **pl)

    def sample_colocated(self, w, pos, critical=None):
        """Failing request (w, pos) plus CO_LOCATED-1 requests from other workflows.

        critical=k forces k-1 of the co-located requests to sit at Slack-0 positions (pre, longest branch, join);
        the default draws every co-located position uniformly."""
        # Paired protocol: the co-located set depends only on (workflow, position, critical), so every system and
        # every sweep point recovers exactly the same failure scenario.
        rng = np.random.default_rng([self.seed, w, pos, 0 if critical is None else int(critical) + 1])
        others = rng.choice(np.delete(np.arange(self.n), w), self.CO_LOCATED - 1, replace=False)
        pos_o = rng.integers(0, 7, self.CO_LOCATED - 1)
        if critical is not None:
            k = max(int(critical) - 1, 0)
            pos_o[:k] = rng.choice([0, 1, 6], k)
            pos_o[k:] = rng.choice([2, 3, 4, 5], self.CO_LOCATED - 1 - k)
        ctx = np.concatenate([[self.ctx[w, pos]], self.ctx[others, pos_o]])
        slack = np.concatenate([[self.slack[w, pos]], self.slack[others, pos_o]])
        perm = rng.permutation(self.CO_LOCATED)                               # arrival order on the failed GPU
        return ctx[perm], slack[perm], int(np.where(perm == 0)[0][0])

    def penalty(self, w, pos, systems, beta=BETA, peer_budget=None, detail=False, critical=None):
        ctx, slack, idx = self.sample_colocated(w, pos, critical)
        out = {}
        for s in systems:
            finish, br = self.recover(ctx, slack, s, beta, peer_budget)
            t = self.R_FLOOR + finish[idx]
            pen = max(t - self.slack[w, pos], 0.0)
            out[s] = (pen, {k: (v[idx] if isinstance(v, np.ndarray) else v) for k, v in br.items()}, ctx[idx]) if detail else pen
        return out

    # ---- normal path ----------------------------------------------------------------
    def normal_overhead(self, system):
        """Per-workflow WCT increase (s) caused by backup copy traffic; illustrative interference model."""
        add = np.zeros(self.n)
        for w in range(self.n):
            for pos in range(7):
                ctx, slack = self.ctx[w, pos], self.slack[w, pos]
                if system == "dram":
                    b = kv_bytes(ctx)
                elif system == "uniform":
                    b = kv_bytes(ctx) + min(self.PEER_BUDGET / self.CO_LOCATED, kv_bytes(ctx))
                elif system == "aegis":
                    dram, _, needs_peer = self.tiers(ctx, slack)
                    b = dram + (min(self.u * dram, self.PEER_BUDGET / 3) if needs_peer else 0)
                else:
                    b = 0
                add[w] += self.KAPPA * b / BETA * self.rng.lognormal(0, .3)
        return add


SYS_STYLE = {
    "recompute": ("Recompute (no backup)", GRAY, "x"),
    "dram": ("DRAM-only", ORANGE, "s"),
    "uniform": ("Peer-uniform", PURPLE, "^"),
    "aegis": ("AegisKV", BLUE, "o"),
}
ILLUSTRATIVE = "Illustrative model output (Sec. 5.1); not a measurement."
ILLUSTRATIVE_SHORT = "Illustrative model, not measured"


def stamp(fig, text=ILLUSTRATIVE):
    fig.text(.995, .01, text, ha="right", va="bottom", color=RED, fontsize=10.0 + .5)


def figure_eval_normal(model: Model):
    fig, ax = plt.subplots(figsize=(3.4, 2.9))
    fig.subplots_adjust(left=.19, right=.94, bottom=.25, top=.78)
    for s in ("dram", "uniform", "aegis"):
        label, color, _ = SYS_STYLE[s]
        d = np.sort(model.normal_overhead(s))
        ax.step(np.concatenate([[0], d]), np.linspace(0, 1, len(d) + 1), where="post", color=color, lw=1.6, label=label)
        ax.plot(d.mean(), .5, marker="|", color=color, ms=10, mew=1.6)
    ax.axvline(0, color=GRAY, lw=.8, ls=(0, (2, 2)))
    ax.set_xlabel("WCT increase vs. no backup (s)")
    ax.set_ylabel("Fraction of workflows")
    ax.set_ylim(0, 1)
    ax.set_xlim(left=-.005)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=4))
    fig.legend(loc="upper left", bbox_to_anchor=(.17, 1.0), ncol=2, columnspacing=1.0, handlelength=1.3, borderaxespad=0)
    stamp(fig, ILLUSTRATIVE_SHORT)
    save(fig, "eval-normal-overhead", evidence="illustrative", width_in=3.4,
         note="ECDF over 160 synthetic workflows of the failure-free WCT increase attributed to backup copy traffic; "
              "ticks at y=0.5 mark means. Model: 10% of copy time becomes foreground slowdown, lognormal jitter. To be replaced by paired F0 runs.",
         sources=["render_draft_20260915.py::Model.normal_overhead"])


def figure_eval_position(model: Model):
    systems = ["recompute", "dram", "uniform", "aegis"]
    pen = {s: np.zeros((model.n, 7)) for s in systems}
    for w in range(model.n):
        for p in range(7):
            r = model.penalty(w, p, systems)
            for s in systems:
                pen[s][w, p] = r[s]
    fig, ax = plt.subplots(figsize=(7, 2.95))
    fig.subplots_adjust(left=.085, right=.985, bottom=.31, top=.87)
    offsets = np.linspace(-.27, .27, len(systems))
    for s, off in zip(systems, offsets):
        label, color, marker = SYS_STYLE[s]
        med = np.median(pen[s], 0)
        q1, q3 = np.percentile(pen[s], [25, 75], axis=0)
        x = np.arange(7) + off
        ax.vlines(x, q1, q3, color=color, lw=1.4)
        ax.plot(x, med, marker=marker, ls="none", color=color, ms=6, mfc="white", mew=1.4, label=label)
    ax.set_yscale("symlog", linthresh=1.0, linscale=.8)
    ax.set_ylim(0, 120)
    ax.set_yticks([0, .5, 1, 2, 5, 10, 20, 50, 100])
    ax.set_yticklabels(["0", "0.5", "1", "2", "5", "10", "20", "50", "100"])
    ax.set_xticks(range(7))
    ax.set_xticklabels(["Pre\n(Slack 0)", "B1 longest\n(Slack 0)", "B2", "B3", "B4", "B5\n(most Slack)", "Join\n(Slack 0)"])
    ax.set_ylabel("WCT penalty, F1 − F0 (s)")
    ax.grid(axis="y", color="#E3E6EA", lw=.6)
    ax.set_axisbelow(True)
    ax.legend(loc="upper right", bbox_to_anchor=(1.0, 1.06), ncol=4, columnspacing=1.2, handlelength=1.3, borderaxespad=0)
    stamp(fig)
    ax.set_xlabel("Failing agent (failure at 80% of its tokens, 120 s outage, 8 co-located recoveries)", labelpad=3)
    save(fig, "eval-failure-position", evidence="illustrative", width_in=7,
         note="Median and interquartile range over 160 synthetic workflows of the same-workflow WCT change when one request fails at "
              "80% progress; 8 co-located requests recover on the fixed Retry DP. B1..B5 are branches sorted by remaining Slack. "
              "symlog y axis. To be replaced by paired F0/F1 simulator runs.",
         sources=["render_draft_20260915.py::Model.penalty"])
    return pen


def figure_eval_breakdown(model: Model):
    systems = ["recompute", "dram", "uniform", "aegis"]
    bytes_src = {s: np.zeros(4) for s in systems}     # peer, dram-needed, dram-background, recompute
    time_src = {s: np.zeros(3) for s in systems}      # fixed, exposed wait, compute
    count = 0
    for w in range(model.n):
        for p in (0, 1, 6):                            # Slack-0 positions
            r = model.penalty(w, p, systems, detail=True)
            for s in systems:
                pen, br, ctx = r[s]
                total = kv_bytes(ctx)
                if s == "recompute" or br["dram"] == 0:
                    bytes_src[s] += [0, 0, 0, total]
                else:
                    u = model.u if br["hot_first"] else 1.0
                    peer = br["peer"]
                    needed = max(u * total - peer, 0)
                    bytes_src[s] += [peer, needed, total - peer - needed, 0]
                # wait = everything between take-over and finish that is not this request's own compute
                time_src[s] += [model.R_FLOOR, br["finish"] - br["compute"], br["compute"]]
            count += 1
    fig, (a, b) = plt.subplots(1, 2, figsize=(7, 3.2), gridspec_kw=dict(width_ratios=[1, 1]))
    fig.subplots_adjust(left=.155, right=.975, bottom=.25, top=.735, wspace=.28)
    labels = ["Recompute", "DRAM-only", "Peer-uniform", "AegisKV"]
    ypos = np.arange(len(systems))[::-1]
    parts_b = [("Peer HBM (resident)", BLUE), ("DRAM, needed before replay", ORANGE), ("DRAM, background", PALE_ORANGE), ("Recompute", GRAY)]
    for j, (lab, color) in enumerate(parts_b):
        vals = np.array([bytes_src[s][j] for s in systems]) / count / 2**30
        left = np.array([bytes_src[s][:j].sum() for s in systems]) / count / 2**30
        a.barh(ypos, vals, left=left, color=color, edgecolor="white", lw=.5, height=.62, label=lab)
    a.set_yticks(ypos)
    a.set_yticklabels(labels)
    a.set_xlabel("(a) History KV of the failed request (GiB)")
    a.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=1, handlelength=1.1, borderaxespad=0, labelspacing=.3, fontsize=10.5)
    parts_t = [("Detect + reroute", PALE_RED), ("Wait (shared path / queue)", RED), ("Own replay / recompute", GRAY)]
    for j, (lab, color) in enumerate(parts_t):
        vals = np.array([time_src[s][j] for s in systems]) / count
        left = np.array([time_src[s][:j].sum() for s in systems]) / count
        b.barh(ypos, vals, left=left, color=color, edgecolor="white", lw=.5, height=.62, label=lab)
    xmax = max(time_src[s].sum() for s in systems if s != "recompute") / count * 1.25
    for yp, s in zip(ypos, systems):
        tot = time_src[s].sum() / count
        if tot > xmax:                                   # Recompute is off the scale: clip the bar and print its total inside
            b.text(xmax * .985, yp, f"⋯ {tot:.1f} s", va="center", ha="right", color="white", fontsize=10.5)
        else:
            b.text(tot + xmax * .015, yp, f"{tot:.2f} s", va="center", ha="left", fontsize=10.5)
    b.set_yticks(ypos)
    b.set_yticklabels([])
    b.set_xlim(0, xmax)
    b.set_xlabel("(b) Mean recovery latency (s)")
    b.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=1, handlelength=1.1, borderaxespad=0, labelspacing=.3, fontsize=10.5)
    stamp(fig)
    save(fig, "eval-recovery-breakdown", evidence="illustrative", width_in=7,
         note="Means over 160 synthetic workflows x 3 Slack-0 positions (pre, longest branch, join). "
              "(a) bytes of the failed request's history KV by recovery source; (b) latency components including the queue position "
              "among 8 co-located recoveries. Replace with simulator token-source and timeline logs.",
         sources=["render_draft_20260915.py::Model.recover"])


def figure_eval_ablation(model: Model):
    variants = [("aegis", "AegisKV (full)"), ("no_cascade", "isolated $B_{use}$"), ("no_slack", "w/o Slack"),
                ("no_sparse", "w/o sparse priority"), ("no_peer", "w/o Peer tier"), ("recompute", "no backup")]
    keys = [k for k, _ in variants]
    betas = [(BETA, f"(a) {BETA / 1e9:.0f} GB/s path"), (BETA_REMOTE, f"(b) {BETA_REMOTE / 1e9:.2f} GB/s path")]
    pen = {(k, beta): [] for k in keys for beta, _ in betas}
    written = {k: [] for k in keys}
    for w in range(model.n):
        for p in range(7):
            for beta, _ in betas:
                r = model.penalty(w, p, keys, beta=beta)
                for k in keys:
                    pen[(k, beta)].append(r[k])
    for k in keys:
        for w in range(model.n):
            for p in range(7):
                ctx, slack = model.ctx[w, p], model.slack[w, p]
                if k == "recompute":
                    written[k].append(0)
                elif k == "no_peer":
                    d, c, _ = model.tiers(ctx, slack)
                    written[k].append(d)
                elif k == "no_slack":
                    d, c, _ = model.tiers(ctx, slack, use_slack=False)
                    written[k].append(d + min(model.u * d, model.PEER_BUDGET / model.CO_LOCATED))
                elif k == "no_cascade":
                    d, c, _ = model.tiers(ctx, slack)
                    written[k].append(d + min(c, model.PEER_BUDGET / 3))
                else:
                    u = 1.0 if k == "no_sparse" else model.u
                    d, c, needs_peer = model.tiers(ctx, slack, sparse=(k != "no_sparse"))
                    written[k].append(d + (min(u * d, model.PEER_BUDGET / 3) if needs_peer else 0))
    fig, axes = plt.subplots(1, 3, figsize=(7, 3.1), gridspec_kw=dict(width_ratios=[1.15, 1.15, .8]))
    fig.subplots_adjust(left=.225, right=.985, bottom=.30, top=.83, wspace=.18)
    ypos = np.arange(len(keys))[::-1]
    for ax, (beta, title) in zip(axes[:2], betas):
        for yp, k in zip(ypos, keys):
            v = np.array(pen[(k, beta)])
            color = BLUE if k == "aegis" else (GRAY if k == "recompute" else PURPLE)
            ax.plot([v.mean()], [yp], marker="o", color=color, ms=6.5, mfc=color, ls="none")
            ax.plot([np.percentile(v, 95)], [yp], marker="D", color=color, ms=5.5, mfc="white", mew=1.3, ls="none")
            ax.hlines(yp, v.mean(), np.percentile(v, 95), color=color, lw=1.0)
        ax.set_yticks(ypos)
        ax.set_xscale("symlog", linthresh=1.0, linscale=.8)
        ax.set_xlim(0, 120)
        ax.set_xticks([0, 1, 10, 100])
        ax.set_xticklabels(["0", "1", "10", "100"])
        ax.set_xticks([.5, 2, 5, 20, 50], minor=True)
        ax.set_xlabel("WCT penalty (s)")
        ax.set_title(title, loc="left")
        ax.grid(axis="x", which="both", color="#E3E6EA", lw=.6)
        ax.set_axisbelow(True)
    axes[0].set_yticklabels([lab for _, lab in variants])
    axes[1].set_yticklabels([])
    c = axes[2]
    for yp, k in zip(ypos, keys):
        color = BLUE if k == "aegis" else (GRAY if k == "recompute" else PURPLE)
        c.barh(yp, np.mean(written[k]) / 2**30, color=color, height=.6)
    c.set_yticks(ypos)
    c.set_yticklabels([])
    c.set_xlabel("Copied GiB")
    c.set_title("(c) normal path", loc="left")
    fig.text(.225, .965, "mean ●, p95 ◇ over 1,120 failures", ha="left", va="center", color=INK)
    stamp(fig)
    save(fig, "eval-ablation", evidence="illustrative", width_in=7,
         note="Each variant removes one mechanism. (a)/(b) mean and 95th percentile of the WCT penalty over 160 workflows x 7 positions "
              f"with a {BETA / 1e9:.0f} GB/s (single-GPU failure, local pool) and a {BETA_REMOTE / 1e9:.2f} GB/s (host failure, remote pool "
              "shared by 4 recovering GPUs) shared H2D path; (c) mean DRAM+Peer bytes copied per request in failure-free operation. "
              "Purple = ablated variants.",
         sources=["render_draft_20260915.py::Model"])


def figure_eval_sensitivity(model: Model):
    fig, axes = plt.subplots(2, 2, figsize=(7, 5.1))
    (a, b), (c, d) = axes
    fig.subplots_adjust(left=.10, right=.985, bottom=.14, top=.845, wspace=.30, hspace=.62)
    systems = ["dram", "uniform", "aegis"]
    crit = [(w, p) for w in range(0, model.n, 2) for p in (0, 1, 6)]
    style_iso = ("AegisKV, isolated $B_{use}$", BLUE, "D")

    def curve(ax, xs_plot, xs_val, fn, s, label=None, dashed=False):
        lab, color, marker = SYS_STYLE[s] if s in SYS_STYLE else style_iso
        ys = [fn(x, s) for x in xs_val]
        ax.plot(xs_plot, ys, marker=marker, color=color, ms=5, mfc=BLUE if dashed else "white", mew=1.3, lw=1.5,
                ls=(0, (3, 2)) if dashed else "-", label=label or lab)

    # (a) Peer budget sweep
    budgets = np.array([0, 1, 2, 4, 8, 16]) * 2**30
    for s in systems:
        curve(a, budgets / 2**30, budgets, lambda x, s: np.mean([model.penalty(w, p, [s], peer_budget=x)[s] for w, p in crit]), s)
    a.set_xlabel("Peer HBM backup budget (GiB)")
    a.set_ylabel("Mean WCT penalty (s)")
    a.set_xticks([0, 4, 8, 16])
    a.set_ylim(bottom=0)
    a.set_title("(a) Peer budget", loc="left")
    # (b) H2D bandwidth sweep
    betas = np.array([6.25, 12.5, 25, 50]) * 1e9
    for s in systems + ["no_peer"]:
        curve(b, betas / 1e9, betas, lambda x, s: np.mean([model.penalty(w, p, [s], beta=x)[s] for w, p in crit]), s,
              label="AegisKV w/o Peer" if s == "no_peer" else None, dashed=(s == "no_peer"))
    b.set_xscale("log", base=2)
    b.set_xticks([6.25, 12.5, 25, 50])
    b.set_xticklabels(["6.25", "12.5", "25", "50"])
    b.set_xlabel("Shared H2D bandwidth (GB/s)")
    b.set_ylabel("Mean WCT penalty (s)")
    b.set_ylim(bottom=0)
    b.set_title("(b) Recovery bandwidth", loc="left")
    # (c) number of Slack-0 requests recovering together on the Retry DP
    ks = [1, 2, 4, 8]
    for s in systems + ["no_cascade"]:
        curve(c, ks, ks, lambda x, s: np.mean([model.penalty(w, p, [s], critical=x)[s] for w, p in crit]), s,
              dashed=(s == "no_cascade"))
    c.set_xticks(ks)
    c.set_xlabel("Slack-0 requests among 8 co-located")
    c.set_ylabel("Mean WCT penalty (s)")
    c.set_ylim(bottom=0)
    c.set_title("(c) Concurrent critical recoveries", loc="left")
    # (d) selector profile: effective path fraction of the two measured selectors and a dense model
    profiles = [("NOSA-1B", U_PROFILES["NOSA-1B"]), ("MiniCPM4-8B", U_PROFILES["MiniCPM4-8B"]), ("dense", 1.0)]
    width = .26
    for j, s in enumerate(systems):
        label, color, marker = SYS_STYLE[s]
        vals = []
        for _, u in profiles:
            saved = model.u
            model.u = u
            vals.append(np.mean([model.penalty(w, p, [s], beta=BETA_REMOTE)[s] for w, p in crit]))
            model.u = saved
        d.bar(np.arange(3) + (j - 1) * width, vals, width=width * .92, color=color, label=label)
    d.set_xticks(range(3))
    d.set_xticklabels([f"{name}\nũ = {u:.2f}" for name, u in profiles])
    d.set_ylabel("Mean WCT penalty (s)")
    d.set_ylim(bottom=0)
    d.set_title(f"(d) Selector, {BETA_REMOTE / 1e9:.2f} GB/s path", loc="left")
    handles, labels = d.get_legend_handles_labels()
    for ax_, key in ((b, "AegisKV w/o Peer"), (c, style_iso[0])):
        h_, l_ = ax_.get_legend_handles_labels()
        handles.append(h_[l_.index(key)])
        labels.append(key)
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, 1.0), ncol=3, columnspacing=1.2, handlelength=1.3,
               handletextpad=.5, borderaxespad=0, labelspacing=.3)
    stamp(fig)
    save(fig, "eval-sensitivity", evidence="illustrative", width_in=7,
         note="(a)-(d): mean penalty over 80 workflows x 3 Slack-0 positions; (c) forces k-1 co-located requests onto Slack-0 positions; "
              "(d) swaps the effective path fraction for the measured NOSA-1B and MiniCPM4-8B values (64-query replay, 32K, online loader) "
              f"and a dense model, keeping MiniCPM4-8B sizes and costs, on the contended {BETA_REMOTE / 1e9:.2f} GB/s path.",
         sources=["render_draft_20260915.py::Model", "benchmark/AegisKV/experiments/native-sparse/20260915/needed_fraction_models.csv"])


def retire_needed_figure(document):
    """Keep the valid union plot as supporting data, without an active paper figure number."""
    record = document.get("figures", {}).pop("motivation-needed-fraction", None)
    if record is not None:
        document.setdefault("archived_figures", {})["motivation-needed-fraction"] = {
            **record, "status": "removed_from_motivation",
            "reason": "Figure 6 (Design section 3.3) alone shows concentration; union/loader analysis is described in Design section 3.3. "
                      "The trace-derived data remain valid and used by the design figures."}
    document["paper_figure_numbers"] = {
        "motivation-branch-gap": 1, "motivation-recovery-exposure": 2, "motivation-sparse-releases": 3,
        "motivation-recompute": 4, "system-overview": 5, "design-sparse-concentration": 6,
        "design-layer-pipeline": 7, "design-needed-coverage": 8, "design-wait-vs-bytes": 9}
    params = document.get("model_parameters", {})
    for old_key in ("figure6_topk_pipeline",):                # key followed the pipeline figure's number
        if old_key in params:
            params["figure7_topk_pipeline"] = params.pop(old_key)


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["motivation-releases", "motivation-recompute", "motivation-workflow",
                                          "motivation-sparse", "motivation-sparse-and-needed", "design-layer-pipeline",
                                          "design-preload-and-wait"],
                        help="Regenerate Figure 3, Figure 4, Figures 1/2, Figure 6, Figure 7, or Figures 8/9; "
                             "sparse-and-needed is a legacy alias for Figure 6")
    parser.add_argument("--sparse-data-dir", type=Path, default=SPARSE,
                        help="Figure 6 tables, optionally staged separately from active paper data")
    parser.add_argument("--out-dir", type=Path,
                        help="Separate candidate directory, only supported with --only motivation-sparse")
    args = parser.parse_args()
    if args.out_dir:
        if args.only not in ("motivation-sparse", "motivation-sparse-and-needed"):
            parser.error("--out-dir requires --only motivation-sparse")
        OUT = args.out_dir.resolve()
    if args.only:
        manifest_path = OUT / "MANIFEST.json"
        document = (json.loads(manifest_path.read_text()) if manifest_path.exists() else
                    dict(figures={}, model_parameters={}, status="candidate_requires_visual_review"))
        if args.only == "design-layer-pipeline":
            summary = figure_pipeline()
            document["model_parameters"]["figure7_topk_pipeline"] = summary
        elif args.only == "motivation-releases":
            figure_sparse_releases()
            summary = {name: item["size_in"] for name, item in MANIFEST.items()}
        elif args.only == "motivation-recompute":
            figure_recompute()
            document["model_parameters"].update(LATENCY_PARAMETERS)
            summary = dict(LATENCY_PARAMETERS, sizes={name: item["size_in"] for name, item in MANIFEST.items()})
        elif args.only == "motivation-workflow":
            refs = figure_branch_gap()
            figure_exposure()
            summary = dict(branch_gap_refs=refs, sizes={name: item["size_in"] for name, item in MANIFEST.items()})
        elif args.only in ("motivation-sparse", "motivation-sparse-and-needed"):
            figure_sparse_concentration(data_dir=args.sparse_data_dir)
            summary = {name: item["size_in"] for name, item in MANIFEST.items()}
        else:
            figure_needed_coverage()
            document["model_parameters"]["figure9_footprint"] = figure_wait_bytes()
            summary = {name: item["size_in"] for name, item in MANIFEST.items()}
        document["figures"].update(MANIFEST)
        retire_needed_figure(document)
        manifest_path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(summary, indent=2))
        return
    gap_refs = figure_branch_gap()
    figure_exposure()
    figure_sparse_releases()
    figure_recompute()
    figure_sparse_concentration()
    pipeline_summary = figure_pipeline()
    figure_needed_coverage()
    footprint_summary = figure_wait_bytes()
    # Retain old results for provenance; never regenerate them as current parallel-retry evidence.
    manifest_path = OUT / "MANIFEST.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    retire_needed_figure(previous)
    archived = dict(previous.get("archived_figures", {}))
    for name, record in previous.get("figures", {}).items():
        if name == "design-cascade" or name.startswith("eval-"):
            archived[name] = {**record, "status": "retired_serial_queue_model",
                              "reason": "Requests retry concurrently; not evidence for the current placement design."}
    (OUT / "MANIFEST.json").write_text(json.dumps(dict(
        design_revision="slack-first placement; parallel retries; no request-level serial queue",
        archived_figures=archived,
        paper_figure_numbers=previous["paper_figure_numbers"],
        generator=str(Path(__file__).relative_to(ROOT)),
        evidence_classes=dict(survey="public model cards and technical reports (release date, native context, sparse-selection granularity)",
                              measured="real observations", analytic="closed-form model anchored on measured costs",
                              illustrative="placeholder model output for experiment design; replace before submission"),
        model_parameters=dict(model="MiniCPM4-8B", gpu=GPU_NAME, layers=LAYERS, kv_bytes_per_token_layer=KV_PER_TOKEN_LAYER,
                              beta_bytes_per_s=BETA, beta_remote_bytes_per_s=BETA_REMOTE, replay_tokens=REPLAY_QUERIES,
                              replay_cost_measured=REPLAY_MEASURED, sealing="per 64-token block",
                              u_effective_profiles=U_PROFILES, u_oracle_profiles=U_ORACLE, u_default=U_REQ,
                              **LATENCY_PARAMETERS,
                              replay_ms_per_layer_at_32k=C_MS, d_ms_remote_32k=D_MS,
                              figure7_topk_pipeline=pipeline_summary, figure9_footprint=footprint_summary),
        figures=MANIFEST), indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v["size_in"] for k, v in MANIFEST.items()}))
    print(json.dumps(dict(u_effective=U_PROFILES, u_oracle=U_ORACLE, C_ms=C_MS, D_ms=D_MS, per_token_128k=PER_TOKEN_128K,
                          replay_measured=REPLAY_MEASURED, pipeline=pipeline_summary, branch_gap_refs=gap_refs)))


if __name__ == "__main__":
    main()
