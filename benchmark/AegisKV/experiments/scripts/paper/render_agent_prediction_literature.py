"""Redraw Heddle Figure 13's published trajectory-length correlations.

Extract aggregate bar heights from the pinned vector PDF, retaining all
three task domains and all original metrics in the source table. Do not
interpret Pearson correlation as runtime percentage accuracy or a CDF.
"""
from pathlib import Path
import csv
import hashlib
import json
import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-agent-literature-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pymupdf as fitz
from design_plot_typography import configure

ROOT = Path(__file__).resolve().parents[5]
DATA = ROOT / "benchmark/AegisKV/experiments/data/agent-time-literature"
OUT = ROOT / "benchmark/AegisKV/paper/figures/agent-time-literature"
PANELS = ROOT / "benchmark/AegisKV/paper/figures/design-insights"
PDF = DATA / "heddle-2603.28101v1.pdf"
TASKS = ["Coding", "Search", "Math"]
METHODS = ["Model-based", "History-based", "Heddle-1", "Heddle-2"]
METRICS = ["Tail 20% recall", "Tail 10% recall", "Predicted-length Pearson"]
COLORS = [(.6816, .8398, .9453), (.7539, .2236, .1687),
          (.9531, .6113, .0706), (.1726, .2432, .3137)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def extract():
    with fitz.open(PDF) as doc:
        page = doc[9]
        drawings = page.get_drawings()
        rows = []
        for ti, (left, right) in enumerate([(76, 222), (243, 389), (410, 556)]):
            horizontals = [d["rect"].y0 for d in drawings
                           if d["fill"] is None and d["rect"].height < .001
                           and d["rect"].width > 140 and left <= d["rect"].x0 < left + 1
                           and 234 < d["rect"].y0 < 306]
            levels = sorted(set(horizontals))
            assert len(levels) == 6  # Source ticks: 0, .2, .4, .6, .8, 1.
            y_one, y_zero = levels[0], levels[-1]
            bars = sorted([d for d in drawings if d["fill"] is not None
                           and left < d["rect"].x0 < right
                           and y_one < d["rect"].y0 < y_zero
                           and abs(d["rect"].y1 - y_zero) < .001
                           and 8 < d["rect"].width < 10], key=lambda d: d["rect"].x0)
            assert len(bars) == 12
            for bi, d in enumerate(bars):
                metric, method = METRICS[bi // 4], METHODS[bi % 4]
                assert max(abs(a-b) for a,b in zip(d["fill"], COLORS[bi % 4])) < .001
                value = (y_zero - d["rect"].y0) / (y_zero - y_one)
                assert 0 <= value <= 1
                rows.append(dict(task=TASKS[ti], metric=metric, method=method,
                                 value=value, rounded_2dp=round(value, 2),
                                 bar_left=d["rect"].x0, bar_top=d["rect"].y0,
                                 axis_zero_y=y_zero, axis_one_y=y_one))
        # Preserve a vector excerpt as an independently inspectable source.
        excerpt = fitz.open()
        clip = fitz.Rect(49, 220, 558, 326)
        dst = excerpt.new_page(width=clip.width, height=clip.height)
        dst.show_pdf_page(dst.rect, doc, 9, clip=clip)
        excerpt.save(DATA / "heddle-figure13-source.pdf")
        dst.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False).save(DATA / "heddle-figure13-source.png")
        excerpt.close()
    with (DATA / "heddle-figure13-values.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(DATA / "provenance.json", dict(
        source_url="https://arxiv.org/pdf/2603.28101v1", source_sha256=sha(PDF),
        figure=13, page=10, rollout_model="Qwen3-14B", task_domains=TASKS,
        extraction="Vector bar heights divided by the source axis span; no sampled predictions reconstructed",
        reported_precision="Display approximate values to two decimals; not author-supplied raw data",
        table_sha256=sha(DATA / "heddle-figure13-values.csv"),
        all_metrics_preserved=METRICS, all_methods_preserved=METHODS,
        plotted_metric=METRICS[-1], plotted_methods=METHODS[-2:],
        statistical_unit="Published per-domain aggregate correlations; 3 task domains, 2 observed steps. Per-domain trajectory counts/uncertainty not recovered from the figure.",
        scope="Prediction of remaining trajectory length, not a wall-clock error distribution or an AegisKV experiment"))
    return rows


def draw(rows, typography, compact):
    fig = plt.figure(figsize=(2.24, 1.85) if compact else (3.34, 2.3))
    ax = fig.add_axes([.25, .255, .71, .48] if compact else [.20, .23, .755, .57])
    styles = [("#246B94", "o", "-"), ("#B55B25", "s", "--"), ("#527D59", "^", "-.")]
    for task, (color, marker, linestyle) in zip(TASKS, styles):
        values = [next(r["value"] for r in rows if r["task"] == task
                       and r["metric"] == METRICS[-1] and r["method"] == method)
                  for method in METHODS[-2:]]
        ax.plot([1, 2], values, color=color, marker=marker, linestyle=linestyle,
                linewidth=1.4, markersize=4.5, markerfacecolor="white",
                markeredgewidth=1.2, label=task)
    ax.set_xlim(.8, 2.2)
    ax.set_ylim(0, 1.03)
    ax.set_xticks([1, 2])
    ax.set_yticks([0, .5, 1], ["0", "0.5", "1"])
    ax.set_xlabel("Observed agent steps", labelpad=3)
    ax.set_ylabel("Pearson correlation", labelpad=3)
    ax.tick_params(length=3, pad=3)
    ax.grid(axis="y", color="#E1E6E9", linewidth=.6)
    ax.set_axisbelow(True)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper center",
               bbox_to_anchor=(.54, 1.015 if compact else .985), ncol=2 if compact else 3,
               frameon=False, handlelength=1.25, handletextpad=.4,
               columnspacing=.85, labelspacing=.2)
    name = "agent-predictability-panel" if compact else "agent-predictability-single-column"
    for ext in ["pdf", "svg", "png"]:
        fig.savefig(OUT / f"{name}.{ext}", facecolor="white")
    plt.close(fig)


def compose(typography):
    doc = fitz.open()
    page = doc.new_page(width=7 * 72, height=2.22 * 72)
    page.insert_font(fontname="libertine", fontfile=typography["regular_path"])
    paths = [OUT / "agent-predictability-panel.pdf", PANELS / "sparse-attention-survey.pdf",
             PANELS / "retry-kv-prediction.pdf"]
    captions = ["(a) Agent trajectory prediction", "(b) Sparse attention adoption", "(c) Retry KV prediction"]
    for i, (path, caption) in enumerate(zip(paths, captions)):
        left = i * 2.38 * 72
        with fitz.open(path) as source:
            page.show_pdf_page(fitz.Rect(left, 0, left + 2.24 * 72, 1.85 * 72), source, 0)
        remaining = page.insert_textbox(fitz.Rect(left, 1.90 * 72, left + 2.24 * 72, 2.22 * 72),
                                       caption, fontsize=10.05, fontname="libertine", align=1)
        assert remaining >= 0
    doc.save(OUT / "figure3-row.pdf")
    for gray in [False, True]:
        page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False,
                       colorspace=fitz.csGRAY if gray else fitz.csRGB).save(
                           OUT / ("figure3-row-gray.png" if gray else "figure3-row.png"))
    doc.close()
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = extract()
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                         "axes.linewidth": .7, "pdf.fonttype": 42,
                         "svg.fonttype": "none", "savefig.dpi": 250})
    typography = configure()
    draw(rows, typography, False)
    draw(rows, typography, True)
    panels = compose(typography)
    selected = [r for r in rows if r["metric"] == METRICS[-1] and r["method"] in METHODS[-2:]]
    write_json(OUT / "MANIFEST.json", dict(
        evidence="Adapted from Heddle Figure 13, arXiv:2603.28101v1; not measured by AegisKV",
        generator_sha256=sha(Path(__file__)), source_pdf_sha256=sha(PDF),
        table_sha256=sha(DATA / "heddle-figure13-values.csv"),
        typography=typography, plotted_values=selected, panel_inputs=panels,
        outputs={p.name: sha(p) for p in OUT.iterdir() if p.suffix in ["pdf", ".pdf", ".svg", ".png"]}))
    print(json.dumps([{k:r[k] for k in ["task", "method", "rounded_2dp"]} for r in selected], indent=2))


if __name__ == "__main__":
    main()
