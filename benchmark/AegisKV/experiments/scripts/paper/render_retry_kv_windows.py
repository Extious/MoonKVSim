"""Plot the requested past-512/next-512 offline coverage experiment."""

import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-retry-z512-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import fitz

from design_plot_typography import configure


BASE = Path(__file__).resolve().parents[3]
DATA = BASE / "experiments/data/retry-kv-z512"
OUT = BASE / "exports/retry-kv-z512"
MODELS = ["NOSA-3B", "MiniCPM4-8B", "SeerAttention-Qwen3-8B"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = json.loads((DATA / "summary.json").read_text())
    typography = configure()
    plt.rcParams.update({"axes.linewidth": .7, "pdf.fonttype": 42,
                         "ps.fonttype": 42, "svg.fonttype": "none"})
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 3.1), sharey=True)
    fig.subplots_adjust(left=.105, right=.985, bottom=.23, top=.74, wspace=.20)
    styles = [
        ("past_frequency", "Past-512 frequency", "#246B94", "o", "-", True),
        ("recent_first", "Recent first", "#B65D24", "s", "--", False),
        ("oracle_mandatory", "Oracle bound", "#424A50", "^", ":", False),
    ]
    plotted = []
    for panel, (ax, model) in enumerate(zip(axes, MODELS)):
        selected = sorted([r for r in rows if r["model"] == model and r["target_queries"] == 512],
                          key=lambda r: r["budget_fraction"])
        assert len(selected) == 8 and all(r["documents"] == 3 for r in selected)
        x = np.array([100 * r["selected_blocks_per_layer"] / 512 for r in selected])
        for key, label, color, marker, line, filled in styles:
            y = np.array([100 * r[key]["mean"] for r in selected])
            low = y - np.array([100 * r[key]["min"] for r in selected])
            high = np.array([100 * r[key]["max"] for r in selected]) - y
            ax.errorbar(x, y, yerr=[low, high], label=label, color=color,
                        marker=marker, linestyle=line, markersize=3.8,
                        markerfacecolor=color if filled else "white",
                        markeredgewidth=.8, linewidth=1.1,
                        elinewidth=.55, capsize=1.8, capthick=.55, zorder=3)
            plotted.extend(dict(model=model, method=key, budget_pct=float(a), mean_pct=float(b),
                                min_pct=float(b - c), max_pct=float(b + d))
                           for a, b, c, d in zip(x, y, low, high))
        ax.axvline(205 / 512 * 100, color="#B8BEC2", linewidth=.7, linestyle=(0, (2, 3)), zorder=1)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_xlim(0, 103)
        ax.set_ylim(0, 103)
        ax.set_xticks([0, 20, 40, 60, 80, 100])
        ax.set_yticks([0, 20, 40, 60, 80, 100])
        ax.tick_params(length=2.5, pad=2)
        ax.grid(axis="y", color="#E1E6E9", linewidth=.6)
        ax.set_axisbelow(True)
        title = ["(a) NOSA-3B", "(b) MiniCPM4-8B", "(c) Seer-Qwen3-8B"][panel]
        ax.set_title(title, pad=7)
    fig.text(.535, .965, "Past 512 queries to next 512 queries", ha="center", va="top")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(.535, .90),
               ncol=3, frameon=False, handlelength=2, handletextpad=.5, columnspacing=1.3,
               borderaxespad=0)
    fig.text(.535, .055, "Per-layer Peer budget (% of historical KV)", ha="center", va="bottom")
    fig.text(.018, .485, "Historical KV coverage (%)", rotation=90, ha="left", va="center")
    for ext in ["pdf", "svg"]:
        fig.savefig(OUT / f"coverage-vs-budget.{ext}", facecolor="white")
    plt.close(fig)
    with fitz.open(OUT / "coverage-vs-budget.pdf") as doc:
        page = doc[0]
        page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).save(OUT / "coverage-vs-budget.png")
        page.get_pixmap(matrix=fitz.Matrix(3, 3), colorspace=fitz.csGRAY, alpha=False).save(OUT / "coverage-vs-budget-gray.png")
        spans = [span for block in page.get_text("dict")["blocks"] if "lines" in block
                 for line in block["lines"] for span in line["spans"] if span["text"].strip()]
        outside = [span["text"] for span in spans if not page.rect.contains(fitz.Rect(span["bbox"]))]
        assert not outside, outside
        min_font = min(span["size"] for span in spans)
        assert min_font >= 10
        dimensions = [page.rect.width, page.rect.height]
    manifest = {
        "evidence": "Offline native-selector analysis, not recovery-latency measurements",
        "generator": str(Path(__file__).resolve()), "generator_sha256": sha(__file__),
        "inputs": {str(DATA / name): sha(DATA / name) for name in ["summary.json", "documents.csv", "protocol.json"]},
        "statistics": "Three document means; error bars are document min/max, not confidence intervals",
        "target_width_inches": 7.0, "pdf_dimensions_pt": dimensions, "minimum_font_pt": min_font,
        "typography": typography, "points": plotted,
        "outputs": {name: sha(OUT / name) for name in ["coverage-vs-budget.pdf", "coverage-vs-budget.svg", "coverage-vs-budget.png"]},
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(OUT), "minimum_font_pt": min_font, "pdf_dimensions_pt": dimensions}))


if __name__ == "__main__":
    main()
