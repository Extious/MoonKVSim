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

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-insights-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import fitz

ROOT = Path(__file__).resolve().parents[5]
DATA = ROOT / "benchmark/AegisKV/experiments/data/design-insights"
OUT = ROOT / "benchmark/AegisKV/paper/figures/design-insights"
W, H = 2.24, 2.65
BLUE, ORANGE, GRAY = "#246B94", "#B55B25", "#65727C"
MODEL_COLORS = [BLUE, "#527D59", ORANGE]
MODELS = ["NOSA-1B", "NOSA-3B", "MiniCPM4-8B"]
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10.25,
    "axes.labelsize": 10.25, "xtick.labelsize": 10.25,
    "ytick.labelsize": 10.25, "legend.fontsize": 10.25,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": .7, "pdf.fonttype": 42, "ps.fonttype": 42,
    "svg.fonttype": "none", "savefig.dpi": 250,
})


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
    ax = fig.add_axes([.255, .21, .71, .505])
    for key, name, color, style in [
        ("progress_nmae", "Progress GBDT", BLUE, "-"),
        ("role_median_nmae", "Median prior", GRAY, "--"),
        ("role_p90_nmae", "P90 prior", ORANGE, ":"),
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
    fig.legend(*ax.get_legend_handles_labels(), loc="upper left",
               bbox_to_anchor=(.21, 1.005), frameon=False,
               handlelength=1.35, handletextpad=.4, labelspacing=.24)
    save(fig, "agent-time-audit")


def survey_panel():
    models = json.loads((DATA / "sparse-models.json").read_text())["models"]
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([.09, .21, .855, .745])
    ax.set_xscale("log", base=2)
    ax.set_xlim(16384, 1.85 * 1048576)
    ax.set_ylim(-.45, 3.9)
    for i, m in enumerate(models):
        y = 3-i
        label = f"'{str(m['year'])[2:]}  {m['display']} · {m['mechanism']}"
        ax.text(16384, y+.45, label, ha="left", va="center", fontsize=10.25)
        ax.hlines(y, 16384, 1048576, colors="#DDE4E8", lw=.8)
        ax.plot(m["context_tokens"], y, "o", ms=5, color=BLUE)
        ax.annotate(m["context_label"], (m["context_tokens"], y),
                    xytext=(0, -3), textcoords="offset points",
                    ha="center", va="top", color=BLUE)
    ax.set_xticks([32768, 131072, 1048576], ["32K", "128K", "1M"])
    ax.set_yticks([])
    ax.minorticks_off()
    ax.spines["left"].set_visible(False)
    ax.tick_params(length=3, pad=3)
    ax.set_xlabel("Context length (tokens)", labelpad=4)
    save(fig, "sparse-attention-survey")


def kv_panel(rows):
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([.265, .21, .71, .505])
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
        x = np.arange(3) + (j-.5)*width
        ax.bar(x, means, width, label=label, color=color, hatch=hatch,
               edgecolor="#344957", linewidth=.5,
               yerr=[lows, highs], capsize=2,
               error_kw=dict(ecolor="#243A46", lw=.8, capthick=.8))
    ax.set_xlim(-.55, 2.55); ax.set_ylim(0, 100)
    ax.set_yticks([0, 50, 100])
    ax.set_xticks(np.arange(3), ["NOSA\n1B", "NOSA\n3B", "Mini\nCPM4"])
    ax.set_ylabel("Needed KV covered (%)", labelpad=3)
    ax.tick_params(length=3, pad=3)
    ax.grid(axis="y", color="#E1E6E9", lw=.6); ax.set_axisbelow(True)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper left",
               bbox_to_anchor=(.19, 1.005), frameon=False,
               handlelength=1.15, handletextpad=.4, labelspacing=.28)
    fig.text(.54, .785, "40% KV budget", ha="center", color=GRAY)
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
    doc = fitz.open(); page = doc.new_page(width=7*72, height=(H+.34)*72)
    for i, (name, caption) in enumerate(zip(names, captions)):
        left = i*(W+.14)*72
        with fitz.open(OUT/f"{name}.pdf") as src:
            page.show_pdf_page(fitz.Rect(left, 0, left+W*72, H*72), src, 0)
        result = page.insert_textbox(fitz.Rect(left, H*72, left+W*72, (H+.33)*72), caption,
                                    fontsize=10.25, fontname="helv", align=1)
        assert result >= 0, caption
    doc.save(OUT/"design-insights-row.pdf")
    page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False).save(OUT/"design-insights-row.png")
    page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), colorspace=fitz.csGRAY, alpha=False).save(OUT/"design-insights-row-gray.png")
    doc.close()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = read_csv("retry-kv-documents.csv")
    agent_panel(); survey_panel(); kv_panel(rows); budget_panel(rows); compose_row()
    sources = [DATA/n for n in ["agent-errors.csv", "agent-summary.json", "agent-extraction.json",
               "retry-kv-documents.csv", "retry-kv-summary.json", "sparse-models.json"]]
    manifest = dict(generator=str(Path(__file__).relative_to(ROOT)), generator_sha256=sha(Path(__file__)),
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in sources},
        panel_size_in=[W,H], row_width_in=7, font_pt=10.25,
        row_label="fig:design-insights", insertion="Three 0.32-textwidth subfigures in a figure* environment.",
        first_premise="Not established: all raw roles are Subagent; preserve the negative diagnostic result.",
        survey_scope="Four representative releases, not a population adoption rate.",
        retry_metric="Per-document covered/needed historical layer-blocks, then mean over 3 documents; whiskers min/max, not CI.",
        retry_scope="Native weighted-model PG19 captures; hypothetical 64-token uncommitted tail, not fault-injected agent retry.")
    (OUT/"MANIFEST.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps({"output":str(OUT),"panel_size_in":[W,H],"font_pt":10.25}))


if __name__ == "__main__":
    main()
