"""Render the three design-evidence panels from audited data, at paper width.

Panel (a) deliberately preserves a failed predictability premise. No smoothing,
outlier exclusion, favorable-fold selection, or fit on the plotted test agents.
Panel (b) is a primary-source survey, not model-market-share measurement.
Panel (c) measures distinct historical KV needed by a held-out retry tail.
"""
from pathlib import Path
import csv
import hashlib
import json
import os
from datetime import date

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-insights-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
import numpy as np
import fitz
from design_plot_typography import FONT_PT, configure

ROOT = Path(__file__).resolve().parents[5]
DATA = ROOT / "benchmark/AegisKV/experiments/data/design-insights"
OUT = ROOT / "benchmark/AegisKV/paper/figures/design-insights"
W, H = 2.24, 1.85
BLUE, ORANGE, GRAY = "#246B94", "#B55B25", "#65727C"
MODEL_COLORS = [BLUE, "#527D59", ORANGE]
MODELS = ["NOSA-3B", "MiniCPM4-8B", "SeerAttention-Qwen3-8B"]
MODEL_LABELS = ["NOSA\n3B", "MiniCPM\n4-8B", "Seer\nQwen3-8B"]
plt.rcParams.update({
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": .7, "pdf.fonttype": 42, "ps.fonttype": 42,
    "svg.fonttype": "none", "savefig.dpi": 250,
})
TYPOGRAPHY = configure()


def read_csv(name):
    with (DATA / name).open() as f:
        return list(csv.DictReader(f))


def save(fig, name):
    # No tight bounding box: preserve the exact insertion size and font scale.
    for ext in ("pdf", "png", "svg"):
        fig.savefig(OUT / f"{name}.{ext}", facecolor="white")
    plt.close(fig)


def agent_panel():
    rows = read_csv("agent-errors.csv")
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([.255, .245, .71, .51])
    for key, name, color, style in [
        ("progress_nmae", "GBDT", BLUE, "-"),
        ("role_median_nmae", "Median", GRAY, "--"),
        ("role_p90_nmae", "P90", ORANGE, ":"),
    ]:
        v = np.sort([100 * float(r[key]) for r in rows])
        assert len(v) == 1688 and np.isfinite(v).all() and (v >= 0).all()
        ax.step(np.r_[0, v, 30000], np.r_[0, np.arange(1, len(v)+1)/len(v)*100, 100],
                where="post", lw=1.35, ls=style, color=color, label=name)
    ax.set_xscale("symlog", linthresh=10, linscale=.5)
    ax.set_xlim(0, 30000)
    ax.set_ylim(0, 103)
    ax.set_xticks([0, 100, 10000], ["0", "100", "10k"])
    ax.set_yticks([0, 50, 100])
    ax.minorticks_off()
    ax.set_xlabel("Normalized MAE (%)", labelpad=4)
    ax.set_ylabel("Agents (%)", labelpad=3)
    ax.tick_params(length=3, pad=3)
    ax.grid(axis="y", color="#E1E6E9", lw=.6)
    ax.set_axisbelow(True)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper center",
               bbox_to_anchor=(.55, 1.01), frameon=False, ncol=2,
               handlelength=1.7, handletextpad=.4, labelspacing=.2, columnspacing=.7)
    save(fig, "agent-time-audit")


def survey_panel():
    models = json.loads((DATA / "sparse-releases.json").read_text())["models"]
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([.305, .245, .66, .51])
    styles = {"block": ("o", ORANGE, "Block"),
              "token": ("s", BLUE, "Token"),
              "entry": ("D", "#826593", "Compressed")}
    offsets = [(5, -2), (-4, 6), (0, 7), (0, -14), (3, -14),
               (-2, 7), (-3, 8), (-6, -17), (2, 7), (0, -17)]
    frontier_x, frontier_y, best = [], [], 0
    for m in sorted(models, key=lambda r:r["date"]):
        if m["context_k"] > best:
            frontier_x.append(date.fromisoformat(m["date"]))
            best = m["context_k"]; frontier_y.append(best)
    frontier_x.append(date(2026, 10, 1)); frontier_y.append(best)
    ax.step(frontier_x, frontier_y, where="post", color="#C9CED4", lw=1, zorder=1)
    for m, offset in zip(models, offsets):
        marker, color, _ = styles[m["granularity"]]
        x, y = date.fromisoformat(m["date"]), m["context_k"]
        ax.plot(x, y, marker=marker, ms=4.8, color=color, mec="white", mew=.5, zorder=3)
        ax.annotate(str(m["id"]), (x, y), xytext=offset, textcoords="offset points",
                    ha="center", va="bottom", color=color,
                    arrowprops=dict(arrowstyle="-", lw=.45, color=color, shrinkA=0, shrinkB=3))
    ax.set_yscale("log", base=2)
    ax.set_ylim(20, 4096)
    ax.set_xlim(date(2025, 5, 15), date(2026, 10, 1))
    ax.set_yticks([32, 128, 1024], ["32K", "128K", "1M"])
    ax.set_xticks([date(2025,6,1), date(2026,1,1), date(2026,8,1)])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
    ax.minorticks_off()
    ax.tick_params(length=3, pad=3)
    ax.set_xlabel("Release date", labelpad=3)
    ax.set_ylabel("Native context", labelpad=3)
    ax.grid(axis="y", color="#E1E6E9", lw=.6); ax.set_axisbelow(True)
    handles = [Line2D([], [], marker=marker, color=color, ls="none", ms=5, label=label)
               for marker, color, label in styles.values()]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.56, 1.01),
               frameon=False, ncol=2, handlelength=.8, handletextpad=.35,
               labelspacing=.2, columnspacing=.7)
    save(fig, "sparse-attention-survey")


def kv_panel(rows):
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([.265, .245, .71, .51])
    width = .31
    for j, (key, label, color, hatch) in enumerate([
        ("past_frequency", "Past frequency", BLUE, None),
        ("recent_first", "Recent first", "#E6B896", "//"),
    ]):
        means, lows, highs = [], [], []
        for model in MODELS:
            a = np.array([float(r[key])*100 for r in rows
                          if r["model"] == model and float(r["budget_fraction"]) == .4])
            assert len(a) == 3
            means.append(a.mean()); lows.append(a.mean()-a.min()); highs.append(a.max()-a.mean())
        x = np.arange(len(MODELS)) + (j-.5)*width
        ax.bar(x, means, width, label=label, color=color, hatch=hatch,
               edgecolor="#344957", linewidth=.5,
               yerr=[lows, highs], capsize=2,
               error_kw=dict(ecolor="#243A46", lw=.8, capthick=.8))
    ax.set_xlim(-.55, len(MODELS)-.45); ax.set_ylim(0, 100)
    ax.set_yticks([0, 50, 100])
    ax.set_xticks(np.arange(len(MODELS)), MODEL_LABELS)
    ax.set_ylabel("KV coverage (%)", labelpad=3)
    ax.tick_params(length=3, pad=3)
    ax.grid(axis="y", color="#E1E6E9", lw=.6); ax.set_axisbelow(True)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper center",
               bbox_to_anchor=(.59, 1.01), frameon=False,
               handlelength=1.15, handletextpad=.4, labelspacing=.28)
    save(fig, "retry-kv-prediction")


def budget_panel(rows):
    fig = plt.figure(figsize=(3.34, 2.55))
    ax = fig.add_axes([.18, .20, .78, .55])
    for i, model in enumerate(MODELS):
        fractions = sorted(set(float(r["budget_fraction"]) for r in rows))
        for method, style in [("past_frequency", "-"), ("recent_first", "--")]:
            averages = [100*np.mean([float(r[method]) for r in rows
                        if r["model"] == model and float(r["budget_fraction"]) == x]) for x in fractions]
            ax.plot(np.array(fractions)*100, averages, color=MODEL_COLORS[i], ls=style,
                    lw=1.35, marker=["o", "s", "^"][i], ms=3.4,
                    mfc=MODEL_COLORS[i] if method == "past_frequency" else "white",
                    label=model if method == "past_frequency" else None)
    ax.set_xlim(0, 102); ax.set_ylim(0, 103)
    ax.set_xticks([0, 40, 80, 100]); ax.set_yticks([0, 50, 100])
    ax.set_xlabel("Historical KV budget (%)"); ax.set_ylabel("Needed KV covered (%)", labelpad=3)
    ax.tick_params(length=3, pad=3)
    ax.grid(color="#E1E6E9", lw=.6); ax.set_axisbelow(True)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper left",
               bbox_to_anchor=(.15, 1.01), frameon=False,
               handlelength=1.2, handletextpad=.4, labelspacing=.2, ncol=2, columnspacing=.65)
    fig.text(.54, .79, "Solid: frequency; dashed: recent", ha="center")
    save(fig, "retry-kv-budget")


def compose_row():
    names = ["agent-time-audit", "sparse-attention-survey", "retry-kv-prediction"]
    captions = ["(a) Agent-time prediction", "(b) Sparse attention adoption", "(c) Retry KV prediction"]
    # Place unchanged vector PDF panels, not resampled screenshots.
    doc = fitz.open(); page = doc.new_page(width=7*72, height=(H+.28)*72)
    page.insert_font(fontname="libertine", fontfile=TYPOGRAPHY["regular_path"])
    for i, (name, caption) in enumerate(zip(names, captions)):
        left = i*(W+.14)*72
        with fitz.open(OUT/f"{name}.pdf") as src:
            page.show_pdf_page(fitz.Rect(left, 0, left+W*72, H*72), src, 0)
        result = page.insert_textbox(fitz.Rect(left, H*72, left+W*72, (H+.27)*72), caption,
                                    fontsize=FONT_PT, fontname="libertine", align=1)
        assert result >= 0, caption
    doc.save(OUT/"design-insights-row.pdf")
    page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False).save(OUT/"design-insights-row.png")
    page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), colorspace=fitz.csGRAY, alpha=False).save(OUT/"design-insights-row-gray.png")
    doc.close()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-budget", action="store_true")
    parser.add_argument("--only-retry", action="store_true",
                        help="Update panel (c) and row composition, preserving the other panel files.")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = read_csv("retry-kv-documents.csv")
    if not args.only_retry:
        agent_panel(); survey_panel()
    kv_panel(rows); compose_row()
    # The supplementary budget plot is independent of the active three-panel row.
    if args.include_budget:
        budget_panel(rows)
    sources = [DATA/n for n in ["agent-errors.csv", "agent-summary.json", "agent-extraction.json",
               "retry-kv-documents.csv", "retry-kv-summary.json", "sparse-releases.json"]]
    manifest = dict(generator=str(Path(__file__).relative_to(ROOT)), generator_sha256=sha(Path(__file__)),
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in sources},
        panel_size_in=[W,H], row_width_in=7, font_pt=FONT_PT, typography=TYPOGRAPHY,
        row_label="fig:design-insights", insertion="Three 0.32-textwidth subfigures in a figure* environment.",
        first_premise="Not established: all raw roles are Subagent; preserve the negative diagnostic result.",
        survey_scope="Ten selected sparse model releases from the recovered timeline, with official announcement/repository dates; not a population adoption rate. Numeric point IDs are keyed in the caption.",
        retry_metric="Per-document covered/needed historical layer-blocks, then mean over 3 documents; whiskers min/max, not CI.",
        retry_models=MODELS,
        retained_archive_model="NOSA-1B remains in source tables but is omitted from the main panel to diversify mechanisms.",
        retry_scope="Native weighted-model PG19 captures; hypothetical 64-token uncommitted tail, not fault-injected agent retry.")
    (OUT/"MANIFEST.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps({"output":str(OUT),"panel_size_in":[W,H],"font_pt":FONT_PT}))


if __name__ == "__main__":
    main()
