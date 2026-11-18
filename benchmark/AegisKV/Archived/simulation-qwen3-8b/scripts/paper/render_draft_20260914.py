"""Figures for the 2026-09-14 AegisKV paper draft (Paper_Draft.md).

Three evidence classes are kept apart in file names and in MANIFEST.json:

  measured      motivation-sparse-concentration   NOSA-1B native selected-block traces
                                                  (output/native-sparse-20260914)
  analytic      design-layer-recovery             closed-form layer-wise recovery model
                                                  (REQUEST_KV_POLICY_SPEC_20260914.md, Sec. 2)
  illustrative  eval-*                            outputs of the small placement/recovery
                                                  model below; NOT measurements.  They fix
                                                  the experiment design and the plotting
                                                  form and must be replaced by simulator or
                                                  hardware results before submission.

Run:
  .venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_draft_20260914.py
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.text import Text  # noqa: E402

ROOT = Path(__file__).resolve().parents[5]           # .../MoonKVSim
assert (ROOT / "benchmark/AegisKV").is_dir(), ROOT
OUT = ROOT / "output/pdf/aegiskv-draft-20260914"
SPARSE = ROOT / "output/native-sparse-20260914"
RECOMPUTE_CSV = ROOT / "output/pdf/aegiskv-revision-20260909/motivation-recompute.csv"

BLUE, ORANGE, GREEN, PURPLE, RED, GRAY, INK = (
    "#0072B2", "#B86B00", "#007D60", "#7952A2", "#B83C46", "#59636F", "#303943")
PALE_BLUE, PALE_ORANGE, PALE_GREEN, PALE_RED = "#DCEBF5", "#FCEBD2", "#DDF0E7", "#F6DADD"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10.5,
    "axes.labelsize": 10.5, "axes.titlesize": 10.5, "axes.titleweight": "bold",
    "xtick.labelsize": 10.5, "ytick.labelsize": 10.5, "legend.fontsize": 10.5,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": .7,
    "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
    "svg.hashsalt": "aegiskv-draft-20260914", "hatch.linewidth": .6,
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
# Figure 4 (measured): intra-request access concentration, NOSA-1B, 32K history.
# ----------------------------------------------------------------------------------------
GRANULARITY = {  # code in concentration_curves.csv -> (label, key in budget_coverage.csv, color)
    "0": ("layer × KV group × block (32 KiB)", "layer_group_block", BLUE),
    "1": ("layer × block, all groups (64 KiB)", "layer_block", ORANGE),
    "2": ("token span, all layers (1.75 MiB)", "token_span_all_layers", GREEN),
}


def figure_sparse_concentration(M="32768", budget="0.2"):
    curves = defaultdict(list)
    with open(SPARSE / "concentration_curves.csv") as f:
        for r in csv.DictReader(f):
            if r["M"] == M:
                curves[(r["granularity"], r["book_id"])].append((float(r["byte_fraction"]), float(r["access_coverage"])))
    budgets = defaultdict(dict)
    with open(SPARSE / "budget_coverage.csv") as f:
        for r in csv.DictReader(f):
            if r["M"] == M and r["nominal_budget_fraction"] == budget:
                budgets[r["granularity"]][r["book_id"]] = (
                    float(r["actual_byte_fraction"]), float(r["offline_access_coverage"]), float(r["past_window_rank_access_coverage"]))
    grid = np.linspace(0, 1, 401)
    fig, ax = plt.subplots(figsize=(3.4, 3.35))
    fig.subplots_adjust(left=.175, right=.95, bottom=.145, top=.735)
    ax.plot([0, 100], [0, 100], color=GRAY, lw=.9, ls=(0, (3, 3)), zorder=1)
    handles = []
    for code, (label, key, color) in GRANULARITY.items():
        docs = [np.interp(grid, *np.array(sorted(curves[(code, d)])).T) for d in sorted({d for c, d in curves if c == code})]
        assert len(docs) == 3, (code, len(docs))
        stack = np.vstack(docs)
        ax.fill_between(grid * 100, stack.min(0) * 100, stack.max(0) * 100, color=color, alpha=.22, lw=0, zorder=2)
        ax.plot(grid * 100, np.median(stack, 0) * 100, color=color, lw=1.6, zorder=3)
        handles.append(Line2D([], [], color=color, lw=1.6, label=label))
        b = np.array(list(budgets[key].values()))          # rows: docs; cols: actual frac, offline, online
        assert b.shape == (3, 3)
        x = b[:, 0].mean() * 100
        for col, face, dx in ((1, color, 0), (2, "white", 3.0)):
            y = np.median(b[:, col]) * 100
            ax.errorbar(x + dx, y, yerr=[[y - b[:, col].min() * 100], [b[:, col].max() * 100 - y]],
                        fmt="o", ms=5.5, mfc=face, mec=color, ecolor=color, elinewidth=.9, capsize=2, zorder=4)
    ax.axvline(20, color=GRAY, lw=.7, ls=(0, (1, 2)), zorder=1)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.set_xlabel("Hottest history KV bytes kept (%)")
    ax.set_ylabel("Selected-block accesses covered (%)")
    markers = [Line2D([], [], marker="o", ls="none", ms=5.5, mfc=INK, mec=INK, label="offline rank"),
               Line2D([], [], marker="o", ls="none", ms=5.5, mfc="white", mec=INK, label="previous-window rank")]
    ax.legend(handles=markers, loc="lower right", bbox_to_anchor=(1.02, .10), handlelength=1.0, handletextpad=.4,
              labelspacing=.3, borderaxespad=0)
    ax.text(22, 3, "20% budget", ha="left", va="bottom", color=GRAY)
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(.02, 1.0), ncol=1, handlelength=1.6,
               borderaxespad=0, labelspacing=.35, title="Management unit", title_fontsize=10.5, alignment="left")
    save(fig, "motivation-sparse-concentration", evidence="measured", width_in=3.4,
         note="NOSA-1B native selected-block traces, 3 PG19 documents x 1 prefill each, M=32768 history, N=512 subsequent queries. "
              "Band = min-max over the 3 documents, line = median. Filled marker: offline frequency rank at the 20% byte budget; "
              "hollow marker: rank computed from the previous 512-query window. Offline coverage is not an online hit rate.",
         sources=["output/native-sparse-20260914/concentration_curves.csv", "output/native-sparse-20260914/budget_coverage.csv"])


# ----------------------------------------------------------------------------------------
# Figure 6 (analytic): layer-wise recovery pipeline and the Slack cap.
# ----------------------------------------------------------------------------------------
LAYERS = 36
KV_PER_TOKEN_LAYER = 4096          # bytes; 8 KV heads x 128 dims x (K,V) x BF16 (Qwen3-8B-like)
BETA = 25e9                        # bytes/s, shared H2D path assumed in the draft
CTX_REF = 32768
D_MS = CTX_REF * KV_PER_TOKEN_LAYER / BETA * 1e3   # 5.369 ms per layer at 32K
C_MS = 170.86 / LAYERS                              # 4.746 ms per layer, 512-token replay (Qwen3-8B, analytic profile)
U_REQ = 0.43                       # fraction of a layer's history bytes touched by a 512-query replay (NOSA-1B 32K union: 0.40-0.46)


def pipeline(resident_layers, per_layer_ms, compute_ms, layers=LAYERS):
    """Sequential H2D stream from t=0 for non-resident layers; each layer computes after its KV and the previous layer."""
    ready = np.array([0.0 if l < resident_layers else (l - resident_layers + 1) * per_layer_ms for l in range(layers)])
    start = np.zeros(layers)
    finish = np.zeros(layers)
    prev = 0.0
    for l in range(layers):
        start[l] = max(prev, ready[l])
        finish[l] = start[l] + compute_ms
        prev = finish[l]
    return ready, start, finish


def figure_pipeline():
    """Design figure: layer-wise recovery pipeline with and without resident front layers (single column)."""
    fig, axes = plt.subplots(2, 1, figsize=(3.4, 2.75), sharex=True)
    fig.subplots_adjust(left=.215, right=.975, bottom=.17, top=.835, hspace=.30)
    for ax, k, label in zip(axes, (0, 6), ("No Peer copy", "First 6 layers in Peer HBM")):
        ready, start, finish = pipeline(k, D_MS, C_MS)
        for l in range(k, LAYERS):                                  # H2D row
            ax.barh(1, D_MS, left=ready[l] - D_MS, height=.62, color=BLUE, edgecolor="white", lw=.3)
        for l in range(LAYERS):                                     # compute row
            ax.barh(0, C_MS, left=start[l], height=.62, color=INK if l < k else GRAY, edgecolor="white", lw=.3)
            gap = start[l] - (finish[l - 1] if l else 0)
            if gap > 1e-9:
                ax.barh(0, gap, left=(finish[l - 1] if l else 0), height=.62, color=RED, edgecolor="none")
        wait = max(finish[-1] - LAYERS * C_MS, 0.0)
        ax.text(finish[-1] + 6, .5, f"wait\n{wait:.0f} ms", ha="left", va="center", color=RED if wait else INK, linespacing=1.05)
        ax.text(0, 1.62, label, ha="left", va="bottom", weight="bold", color=INK)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["compute", "H2D"])
        ax.get_yticklabels()[1].set_color(BLUE)
        ax.set_ylim(-.5, 2.25)
        ax.set_xlim(0, 262)
        ax.tick_params(axis="y", length=0)
    axes[1].set_xlabel("Time after take-over starts (ms)")
    handles = [Patch(color=BLUE, label="H2D of one layer"), Patch(color=GRAY, label="replay of one layer"),
               Patch(color=RED, label="wait for KV"), Patch(color=INK, label="resident layer")]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.55, 1.0), ncol=2, columnspacing=1.0,
               handlelength=1.1, handletextpad=.4, borderaxespad=0, labelspacing=.25)
    save(fig, "design-layer-pipeline", evidence="analytic", width_in=3.4,
         note="Closed-form layer pipeline (REQUEST_KV_POLICY_SPEC_20260914 Sec. 2): 36 layers, 128 MiB history KV per layer at 32K, "
              "H2D 25 GB/s (5.37 ms/layer), 4.75 ms replay compute per layer (512 tokens), one copy stream, no launch overhead, "
              "no compute/transfer interference. Exposed wait 27 ms without residency, 0 with the first six layers resident. "
              "Detection, queueing and weight loading are excluded. Not a hardware measurement.",
         sources=["benchmark/AegisKV/docs/paper/REQUEST_KV_POLICY_SPEC_20260914.md", "output/pdf/recovery-layer-profile-20260913/summary.json"])


def figure_wait_bytes():
    """Design figure: exposed wait versus Peer-resident bytes, dense vs. hot-first stream, and the Slack cap B_use."""
    fig, ax = plt.subplots(figsize=(3.4, 2.55))
    fig.subplots_adjust(left=.18, right=.975, bottom=.19, top=.955)
    x = np.linspace(0, 900, 451)                        # MiB in Peer HBM (front layers, hot blocks first)
    per_mib_ms = 2**20 / BETA * 1e3
    w0_dense = D_MS + (LAYERS - 1) * max(D_MS - C_MS, 0)
    w0_hot = U_REQ * D_MS + (LAYERS - 1) * max(U_REQ * D_MS - C_MS, 0)
    ax.plot(x, np.maximum(w0_dense - x * per_mib_ms, 0), color=ORANGE, lw=2.0, label="dense stream")
    ax.plot(x, np.maximum(w0_hot - x * per_mib_ms, 0), color=BLUE, lw=2.0, label=f"hot-first ({U_REQ:.0%})")
    sigma = 10.0                                        # ms of Slack left after R_floor
    ax.axhline(sigma, color=GRAY, lw=1.0, ls=(0, (4, 2)))
    ax.text(885, sigma + 0.8, "σ − $R_{floor}$ = 10 ms", ha="right", va="bottom", color=GRAY)
    b_use = (w0_dense - sigma) / per_mib_ms
    ax.plot([b_use], [sigma], marker="v", color=ORANGE, ms=8, mec=INK, mew=.6, zorder=4)
    ax.annotate(f"$B_{{use}}$ = {b_use:.0f} MiB", xy=(b_use, sigma), xytext=(120, 4.5), ha="left", va="center",
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=.8, shrinkA=0, shrinkB=4))
    ax.set_xlim(0, 900)
    ax.set_ylim(0, 30)
    ax.set_xlabel("Peer-resident bytes (MiB)")
    ax.set_ylabel("Exposed wait (ms)")
    ax.legend(loc="upper right", bbox_to_anchor=(1.0, 1.0), handlelength=1.4, borderaxespad=0, labelspacing=.3)
    save(fig, "design-wait-vs-bytes", evidence="analytic", width_in=3.4,
         note="W(x)=[W0 - x/beta]+ with the Figure-6 parameters; dense W0 = 27 ms, hot-first W0 = 2.3 ms (NOSA-1B 32K union fraction 0.43). "
              "B_use = beta * min{W0, [R_floor + W0 - sigma]+} marks where additional Peer bytes stop reducing the WCT penalty. "
              "128 MiB per layer at 32K. Not a hardware measurement.",
         sources=["benchmark/AegisKV/docs/paper/REQUEST_KV_POLICY_SPEC_20260914.md"])


# Worked example for the cascade-aware allocation: three co-located requests in EDD order.
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
         sources=["render_draft_20260914.py::allocate_cascade"])


# ----------------------------------------------------------------------------------------
# Illustrative placement/recovery model for the evaluation section.
# ----------------------------------------------------------------------------------------
def _recompute_table():
    pts = []
    with open(RECOMPUTE_CSV) as f:
        for r in csv.DictReader(f):
            if r["model"] == "Qwen3-8B":
                pts.append((int(r["context_tokens"]), float(r["component_time_s"])))
    pts.sort()
    return np.array(pts, dtype=float)


RECOMPUTE_PTS = _recompute_table()


def recompute_s(ctx):
    """Log-log interpolation of the AIConfigurator full-prefix prefill predictions (Qwen3-8B)."""
    return float(np.exp(np.interp(np.log(ctx), np.log(RECOMPUTE_PTS[:, 0]), np.log(RECOMPUTE_PTS[:, 1]))))


def replay_ms_per_layer(ctx):
    return C_MS * (0.55 + 0.45 * ctx / CTX_REF)


def kv_bytes(ctx):
    return ctx * KV_PER_TOKEN_LAYER * LAYERS


class Model:
    """Small analytic model of workflows, co-located recoveries on one fixed Retry DP, and WCT penalty.

    Every number it produces is illustrative.  The design of the experiments (paired F0/F1 on the same
    workflow set, aligned failure progress, position sweep, ablation, sensitivity) is what the figures fix.
    """
    R_FLOOR = 0.5            # s: detection + reroute + admission on the Retry DP; identical for every system
    CO_LOCATED = 8           # requests active on the failed GPU; they recover together on the Retry DP
    PEER_BUDGET = 4 * 2**30  # bytes of Peer HBM reserved for backups on one Retry DP
    KAPPA = 0.10             # fraction of copy time that shows up as foreground slowdown (normal path)
    POSITIONS = ["Pre", "B1", "B2", "B3", "B4", "B5", "Join"]   # B1 = longest branch (Slack 0)

    def __init__(self, seed=20260914, workflows=160, branches=5):
        self.rng = np.random.default_rng(seed)
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
        u = U_REQ if sparse else 1.0
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
        w0 = self.w0_isolated(ctx, beta, sparse)
        exposure = (self.R_FLOOR + w0 - slack) if use_slack else w0
        needs_peer = exposure > 0
        b_use = beta * min(w0, max(exposure, 0.0))
        return kv_bytes(ctx), int(min(b_use, (U_REQ if sparse else 1.0) * kv_bytes(ctx))), needs_peer

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
        u = U_REQ if sparse else 1.0
        need = u * dram                                                        # bytes that gate replay
        if not use_slack:                                                      # equal split, no tiers
            peer[:] = np.minimum(need, peer_budget / n)
            return dict(dram=dram, peer=peer, hot_first=sparse)
        order = [int(i) for i in np.argsort(slack, kind="stable") if dram[i] > 0]
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
        u = U_REQ if pl["hot_first"] else 1.0
        order = np.argsort(slack, kind="stable") if system in ("aegis", "no_sparse", "no_peer", "no_cascade") else np.arange(n)
        t = 0.0
        for i in order:
            if pl["dram"][i] == 0:                                             # tier 0: recompute in the background stream slot
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
        others = self.rng.choice(np.delete(np.arange(self.n), w), self.CO_LOCATED - 1, replace=False)
        pos_o = self.rng.integers(0, 7, self.CO_LOCATED - 1)
        if critical is not None:
            k = max(int(critical) - 1, 0)
            pos_o[:k] = self.rng.choice([0, 1, 6], k)
            pos_o[k:] = self.rng.choice([2, 3, 4, 5], self.CO_LOCATED - 1 - k)
        ctx = np.concatenate([[self.ctx[w, pos]], self.ctx[others, pos_o]])
        slack = np.concatenate([[self.slack[w, pos]], self.slack[others, pos_o]])
        perm = self.rng.permutation(self.CO_LOCATED)                          # arrival order on the failed GPU
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
                    b = dram + (min(U_REQ * dram, self.PEER_BUDGET / 3) if needs_peer else 0)
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
    fig.subplots_adjust(left=.19, right=.965, bottom=.25, top=.78)
    for s in ("dram", "uniform", "aegis"):
        label, color, _ = SYS_STYLE[s]
        d = np.sort(model.normal_overhead(s))
        ax.step(np.concatenate([[0], d]), np.linspace(0, 1, len(d) + 1), where="post", color=color, lw=1.6, label=label)
        ax.plot(d.mean(), .5, marker="|", color=color, ms=10, mew=1.6)
    ax.axvline(0, color=GRAY, lw=.8, ls=(0, (2, 2)))
    ax.set_xlabel("WCT increase vs. no backup (s)")
    ax.set_ylabel("Fraction of workflows")
    ax.set_ylim(0, 1)
    ax.set_xlim(left=-.02)
    fig.legend(loc="upper left", bbox_to_anchor=(.17, 1.0), ncol=2, columnspacing=1.0, handlelength=1.3, borderaxespad=0)
    stamp(fig, ILLUSTRATIVE_SHORT)
    save(fig, "eval-normal-overhead", evidence="illustrative", width_in=3.4,
         note="ECDF over 160 synthetic workflows of the failure-free WCT increase attributed to backup copy traffic; "
              "ticks at y=0.5 mark means. Model: 10% of copy time becomes foreground slowdown, lognormal jitter. To be replaced by paired F0 runs.",
         sources=["render_draft_20260914.py::Model.normal_overhead"])


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
    ax.set_ylim(0, 60)
    ax.set_yticks([0, .5, 1, 2, 5, 10, 20, 50])
    ax.set_yticklabels(["0", "0.5", "1", "2", "5", "10", "20", "50"])
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
         sources=["render_draft_20260914.py::Model.penalty"])
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
                    u = U_REQ if br["hot_first"] else 1.0
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
    xmax = max(time_src[s].sum() for s in systems) / count
    for yp, s in zip(ypos, systems):
        tot = time_src[s].sum() / count
        b.text(tot + xmax * .015, yp, f"{tot:.1f} s", va="center", ha="left", fontsize=10.5)
    b.set_yticks(ypos)
    b.set_yticklabels([])
    b.set_xlim(0, xmax * 1.22)
    b.set_xlabel("(b) Mean recovery latency (s)")
    b.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=1, handlelength=1.1, borderaxespad=0, labelspacing=.3, fontsize=10.5)
    stamp(fig)
    save(fig, "eval-recovery-breakdown", evidence="illustrative", width_in=7,
         note="Means over 160 synthetic workflows x 3 Slack-0 positions (pre, longest branch, join). "
              "(a) bytes of the failed request's history KV by recovery source; (b) latency components including the queue position "
              "among 8 co-located recoveries. Replace with simulator token-source and timeline logs.",
         sources=["render_draft_20260914.py::Model.recover"])


def figure_eval_ablation(model: Model):
    variants = [("aegis", "AegisKV (full)"), ("no_cascade", "isolated $B_{use}$"), ("no_slack", "w/o Slack"),
                ("no_sparse", "w/o sparse priority"), ("no_peer", "w/o Peer tier"), ("recompute", "no backup")]
    keys = [k for k, _ in variants]
    pen = {k: [] for k in keys}
    written = {k: [] for k in keys}
    for w in range(model.n):
        for p in range(7):
            r = model.penalty(w, p, keys)
            for k in keys:
                pen[k].append(r[k])
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
                    written[k].append(d + min(U_REQ * d, model.PEER_BUDGET / model.CO_LOCATED))
                elif k == "no_cascade":
                    d, c, _ = model.tiers(ctx, slack)
                    written[k].append(d + min(c, model.PEER_BUDGET / 3))
                else:
                    u = 1.0 if k == "no_sparse" else U_REQ
                    d, c, needs_peer = model.tiers(ctx, slack, sparse=(k != "no_sparse"))
                    written[k].append(d + (min(u * d, model.PEER_BUDGET / 3) if needs_peer else 0))
    fig, (a, b) = plt.subplots(1, 2, figsize=(7, 3.0), gridspec_kw=dict(width_ratios=[1.25, 1]))
    fig.subplots_adjust(left=.215, right=.985, bottom=.31, top=.87, wspace=.22)
    ypos = np.arange(len(keys))[::-1]
    for yp, k in zip(ypos, keys):
        v = np.array(pen[k])
        color = BLUE if k == "aegis" else (GRAY if k == "recompute" else PURPLE)
        a.plot([v.mean()], [yp], marker="o", color=color, ms=6.5, mfc=color, ls="none")
        a.plot([np.percentile(v, 95)], [yp], marker="D", color=color, ms=5.5, mfc="white", mew=1.3, ls="none")
        a.hlines(yp, v.mean(), np.percentile(v, 95), color=color, lw=1.0)
        b.barh(yp, np.mean(written[k]) / 2**30, color=color, height=.6)
    a.set_yticks(ypos)
    a.set_yticklabels([lab for _, lab in variants])
    a.set_xscale("symlog", linthresh=1.0, linscale=.8)
    a.set_xlim(0, 60)
    a.set_xticks([0, .5, 1, 2, 5, 10, 20, 50])
    a.set_xticklabels(["0", "0.5", "1", "2", "5", "10", "20", "50"])
    a.set_xlabel("WCT penalty over all 1,120 failures (s)")
    a.set_title("(a) mean ● and p95 ◇ penalty", loc="left")
    a.grid(axis="x", color="#E3E6EA", lw=.6)
    a.set_axisbelow(True)
    b.set_yticks(ypos)
    b.set_yticklabels([])
    b.set_xlabel("Copied GiB per request")
    b.set_title("(b) normal-path cost", loc="left")
    stamp(fig)
    save(fig, "eval-ablation", evidence="illustrative", width_in=7,
         note="Each variant removes one mechanism. (a) mean and 95th percentile of the WCT penalty over 160 workflows x 7 positions; "
              "(b) mean DRAM+Peer bytes copied per request in failure-free operation. Purple = ablated variants.",
         sources=["render_draft_20260914.py::Model"])


def figure_eval_sensitivity(model: Model):
    fig, axes = plt.subplots(2, 2, figsize=(7, 5.1))
    (a, b), (c, d) = axes
    fig.subplots_adjust(left=.085, right=.985, bottom=.14, top=.845, wspace=.30, hspace=.62)
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
    # (d) failure-rate scaling: expected WCT inflation over the workflow lifetime
    rates = np.linspace(0, 2, 9)                        # failures per GPU-hour (exaggerated to expose the trend)
    for s in systems + ["recompute"]:
        label, color, marker = SYS_STYLE[s]
        exp_pen = np.zeros(model.n)
        for w in range(0, model.n, 2):
            for p in range(7):
                exp_pen[w] += model.duration[w, p] / 3600 * model.penalty(w, p, [s])[s]
        infl = [np.mean(exp_pen[::2] * lam / model.wct[::2]) * 100 for lam in rates]
        d.plot(rates, infl, marker=marker, color=color, ms=4.5, mfc="white", mew=1.2, lw=1.5, label="Recompute" if s == "recompute" else label)
    d.set_xlabel("Failures per GPU-hour")
    d.set_ylabel("WCT inflation (%)")
    d.set_ylim(bottom=0)
    d.set_title("(d) Failure rate", loc="left")
    handles, labels = d.get_legend_handles_labels()
    for ax_, key in ((b, "AegisKV w/o Peer"), (c, style_iso[0])):
        h_, l_ = ax_.get_legend_handles_labels()
        handles.append(h_[l_.index(key)])
        labels.append(key)
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, 1.0), ncol=3, columnspacing=1.2, handlelength=1.3,
               handletextpad=.5, borderaxespad=0, labelspacing=.3)
    stamp(fig)
    save(fig, "eval-sensitivity", evidence="illustrative", width_in=7,
         note="(a)-(c): mean penalty over 80 workflows x 3 Slack-0 positions; (c) forces k-1 co-located requests onto Slack-0 positions; "
              "(d): expected inflation = sum over requests of (duration/3600) x rate x penalty, divided by WCT; rates far above "
              "production MTBF to expose the trend.",
         sources=["render_draft_20260914.py::Model"])


def main():
    figure_sparse_concentration()
    figure_pipeline()
    figure_wait_bytes()
    figure_cascade()
    model = Model()
    figure_eval_normal(model)
    figure_eval_position(model)
    figure_eval_breakdown(model)
    figure_eval_ablation(model)
    figure_eval_sensitivity(model)
    (OUT / "MANIFEST.json").write_text(json.dumps(dict(
        generator=str(Path(__file__).relative_to(ROOT)),
        evidence_classes=dict(measured="real observations", analytic="closed-form model, uncalibrated",
                              illustrative="placeholder model output for experiment design; replace before submission"),
        model_parameters=dict(layers=LAYERS, kv_bytes_per_token_layer=KV_PER_TOKEN_LAYER, beta_bytes_per_s=BETA,
                              replay_tokens=512, u_required=U_REQ, r_floor_s=Model.R_FLOOR, co_located=Model.CO_LOCATED,
                              peer_budget_bytes=Model.PEER_BUDGET, kappa=Model.KAPPA,
                              workflows=160, branches=5, seed=20260914),
        figures=MANIFEST), indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v["size_in"] for k, v in MANIFEST.items()}))


if __name__ == "__main__":
    main()
