"""Render all layers for the fixed window-presence diagnostic, at final size."""

import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-window-presence-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import fitz

from design_plot_typography import configure


BASE = Path(__file__).resolve().parents[3]
DATA = BASE / "experiments/data/retry-kv-window-presence"
OUT = BASE / "exports/retry-kv-window-presence"
MODELS = ["NOSA-3B", "MiniCPM4-8B", "SeerAttention-Qwen3-8B"]
HORIZONS = [256, 512]
STYLES = [
    ("window_presence", "Window presence", "#246B94", "o", "-"),
    ("frequency_2048", "Frequency (same history)", "#B65D24", "s", "--"),
    ("oracle", "Oracle bound", "#424A50", "^", ":"),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = json.loads((DATA / "layer-summary.json").read_text())
    summary = json.loads((DATA / "summary.json").read_text())
    typography = configure()
    plt.rcParams.update({"axes.linewidth": .65, "pdf.fonttype": 42,
                         "ps.fonttype": 42, "svg.fonttype": "none"})
    fig, axes = plt.subplots(3, 2, figsize=(7.0, 7.15), sharey=True)
    fig.subplots_adjust(left=.098, right=.98, bottom=.125, top=.815,
                        hspace=.38, wspace=.19)
    plotted = []
    for row_index, model in enumerate(MODELS):
        for col_index, target in enumerate(HORIZONS):
            ax = axes[row_index, col_index]
            group = sorted([r for r in rows if r["model"] == model and r["target_queries"] == target],
                           key=lambda r: r["layer"])
            x = np.array([r["layer"] for r in group])
            expected = 36 if model.startswith("Seer") else 32
            assert np.array_equal(x, np.arange(1, expected + 1))
            assert all(r["documents"] == 3 for r in group)
            for method, label, color, marker, linestyle in STYLES:
                y = np.array([r[method]["mean"] * 100 for r in group])
                lo = np.array([r[method]["min"] * 100 for r in group])
                hi = np.array([r[method]["max"] * 100 for r in group])
                if method == "window_presence":
                    ax.fill_between(x, lo, hi, color=color, alpha=.13, linewidth=0, zorder=1)
                ax.plot(x, y, label=label, color=color, linestyle=linestyle,
                        linewidth=1.05 if method == "window_presence" else .95,
                        marker=marker, markersize=2.5, markevery=4,
                        markeredgewidth=.65,
                        markerfacecolor=color if method == "window_presence" else "white",
                        zorder=4 if method == "window_presence" else 3)
                plotted.extend(dict(model=model, target_queries=target, layer=int(l), method=method,
                                    mean_pct=float(v), min_pct=float(a), max_pct=float(b))
                               for l, v, a, b in zip(x, y, lo, hi))
            model_summary = next(r for r in summary if r["model"] == model and r["target_queries"] == target)
            macro = model_summary["window_presence"]["macro"]["mean"] * 100
            assert abs(np.mean([r["window_presence"]["mean"] for r in group]) * 100 - macro) < 1e-10
            ax.text(.025, .075, f"All-layer mean: {macro:.2f}%", transform=ax.transAxes,
                    ha="left", va="bottom", color="#1D5070")
            title = "SeerAttention-Qwen3-8B" if model.startswith("Seer") else model
            panel = chr(ord("a") + row_index * 2 + col_index)
            ax.set_title(f"({panel}) {title}", pad=6)
            ax.spines[["top", "right"]].set_visible(False)
            ax.set_xlim(.5, expected + .5)
            ax.set_ylim(0, 105)
            ax.set_yticks([0, 20, 40, 60, 80, 100])
            ax.set_xticks([1, 8, 16, 24, 32] + ([36] if expected == 36 else []))
            ax.tick_params(length=2.5, pad=2)
            ax.grid(axis="y", color="#E1E6E9", linewidth=.5)
            ax.set_axisbelow(True)
    fig.text(.54, .985, "Window-presence prediction at 40% per-layer capacity", ha="center", va="top")
    fig.text(.54, .951, "Past 2048 queries; decay = 0.5/window; 205 of 512 blocks per layer",
             ha="center", va="top")
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="upper center",
               bbox_to_anchor=(.54, .919), ncol=3, frameon=False, handlelength=2,
               handletextpad=.5, columnspacing=1.1, borderaxespad=0)
    for col_index, target in enumerate(HORIZONS):
        bbox = axes[0, col_index].get_position()
        fig.text((bbox.x0 + bbox.x1) / 2, .859, f"Next {target} queries", ha="center", va="center")
    fig.text(.54, .076, "Layer ID", ha="center", va="center")
    fig.text(.016, .47, "Distinct historical KV coverage (%)", rotation=90, ha="left", va="center")
    fig.text(.54, .038, "Shading: document min–max (n = 3); means weight all layers equally.",
             ha="center", va="center")
    fig.text(.54, .014, "Offline native-selector traces; fixed placement throughout each target window.",
             ha="center", va="center")
    stem = "coverage-by-layer"
    for ext in ("pdf", "svg"):
        fig.savefig(OUT / f"{stem}.{ext}", facecolor="white")
    plt.close(fig)
    with fitz.open(OUT / f"{stem}.pdf") as doc:
        page = doc[0]
        page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).save(OUT / f"{stem}.png")
        page.get_pixmap(matrix=fitz.Matrix(3, 3), colorspace=fitz.csGRAY, alpha=False).save(OUT / f"{stem}-gray.png")
        # 100% reading scale (96 dpi) accompanies the high-resolution export.
        page.get_pixmap(matrix=fitz.Matrix(4 / 3, 4 / 3), alpha=False).save(OUT / f"{stem}-reading-size.png")
        spans = [s for b in page.get_text("dict")["blocks"] if "lines" in b
                 for line in b["lines"] for s in line["spans"] if s["text"].strip()]
        outside = [s["text"] for s in spans if not page.rect.contains(fitz.Rect(s["bbox"]))]
        assert not outside, outside
        min_font = min(s["size"] for s in spans)
        assert min_font >= 10
        dimensions = [page.rect.width, page.rect.height]
    manifest = {
        "evidence": "Offline native-selector diagnostic, no new forward or recovery execution",
        "generator": str(Path(__file__).resolve()), "generator_sha256": sha(__file__),
        "inputs": {str(DATA / name): sha(DATA / name) for name in ("protocol.json", "layer-summary.json", "summary.json")},
        "target_width_inches": 7., "pdf_dimensions_pt": dimensions, "minimum_font_pt": min_font,
        "typography": typography,
        "statistics": "Each layer is averaged over 3 reused documents; shade is min/max. Annotated model means equally weight all layers",
        "baseline": "Frequency uses the same 2048 past queries, physical objects, mandatory blocks, and 205-block quota",
        "points": plotted,
        "outputs": {name: sha(OUT / name) for name in (f"{stem}.pdf", f"{stem}.svg", f"{stem}.png",
                                                        f"{stem}-gray.png", f"{stem}-reading-size.png")},
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(OUT), "minimum_font_pt": min_font, "pdf_dimensions_pt": dimensions}))


if __name__ == "__main__":
    main()
