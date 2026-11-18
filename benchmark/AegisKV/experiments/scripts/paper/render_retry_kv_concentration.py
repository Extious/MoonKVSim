"""Plot same-window KV access concentration with explicit counting conventions."""

import csv
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-kv-concentration-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import fitz

from design_plot_typography import configure


BASE = Path(__file__).resolve().parents[3]
DATA = BASE / "experiments/data/retry-kv-access-concentration"
OUT = BASE / "exports/retry-kv-access-concentration"
STYLES = [
    ("NOSA-3B", "NOSA-3B", "#246B94", "o", "-"),
    ("MiniCPM4-8B", "MiniCPM4-8B", "#B65D24", "s", "--"),
    ("SeerAttention-Qwen3-8B", "Seer-Qwen3-8B", "#447B56", "^", "-.")
]
METRICS = [("query_block", "Heads merged per query"),
           ("selector_event", "Native selector events")]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_figure(fig, stem):
    for ext in ("pdf", "svg"):
        fig.savefig(OUT / f"{stem}.{ext}", facecolor="white")
    plt.close(fig)
    with fitz.open(OUT / f"{stem}.pdf") as doc:
        page = doc[0]
        page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).save(OUT / f"{stem}.png")
        page.get_pixmap(matrix=fitz.Matrix(3, 3), colorspace=fitz.csGRAY,
                        alpha=False).save(OUT / f"{stem}-gray.png")
        page.get_pixmap(matrix=fitz.Matrix(4 / 3, 4 / 3), alpha=False).save(OUT / f"{stem}-reading-size.png")
        spans = [s for block in page.get_text("dict")["blocks"] if "lines" in block
                 for line in block["lines"] for s in line["spans"] if s["text"].strip()]
        outside = [s["text"] for s in spans if not page.rect.contains(fitz.Rect(s["bbox"]))]
        assert not outside, outside
        minimum = min(s["size"] for s in spans)
        assert minimum >= 10, minimum
        return {"width_inches": page.rect.width / 72, "height_inches": page.rect.height / 72,
                "minimum_font_pt": minimum}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    typography = configure()
    plt.rcParams.update({"axes.linewidth": .65, "pdf.fonttype": 42,
                         "ps.fonttype": 42, "svg.fonttype": "none"})
    with (DATA / "curves.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    with (DATA / "layers.csv").open() as stream:
        layers = list(csv.DictReader(stream))
    summaries = json.loads((DATA / "summary.json").read_text())
    fig, axes = plt.subplots(2, 2, figsize=(7., 5.85), sharex=True, sharey=True)
    fig.subplots_adjust(left=.099, right=.985, top=.78, bottom=.16,
                        hspace=.43, wspace=.17)
    points = []
    for i, (metric, description) in enumerate(METRICS):
        for j, n in enumerate((256, 512)):
            ax = axes[i, j]
            for model, label, color, marker, linestyle in STYLES:
                group = sorted([r for r in rows if r["model"] == model
                                and r["metric"] == metric and int(r["window_queries"]) == n],
                               key=lambda r: int(r["K"]))
                assert [int(r["K"]) for r in group] == list(range(513))
                x = np.array([float(r["block_fraction"]) * 100 for r in group])
                y, lo, hi = [np.array([float(r[key]) * 100 for r in group])
                             for key in ("mean", "min", "max")]
                ax.fill_between(x, lo, hi, color=color, alpha=.12, linewidth=0)
                ax.plot(x, y, label=label, color=color, linestyle=linestyle,
                        linewidth=1.25, marker=marker, markersize=3.5,
                        markevery=[52, 103, 205, 307, 410], markeredgewidth=.8,
                        markerfacecolor=color if model == "NOSA-3B" else "white")
                points.extend(dict(model=model, metric=metric, window_queries=n, K=int(r["K"]),
                                   block_fraction=float(r["block_fraction"]),
                                   mean=float(r["mean"]), min=float(r["min"]), max=float(r["max"]))
                              for r in group)
            ax.plot([0, 100], [0, 100], color="#72787B", linestyle=":", linewidth=.9,
                    label="Uniform")
            ax.set_title(f"({chr(97 + i * 2 + j)}) {description}", pad=6)
            ax.spines[["top", "right"]].set_visible(False)
            ax.set_xlim(0, 100)
            ax.set_ylim(0, 103)
            ax.set_xticks([0, 20, 40, 60, 80, 100])
            ax.set_yticks([0, 20, 40, 60, 80, 100])
            ax.tick_params(length=2.5, pad=2, labelbottom=True)
            ax.grid(color="#E2E6E9", linewidth=.5)
            ax.set_axisbelow(True)
    fig.text(.54, .978, "Historical KV access concentration", ha="center", va="top")
    fig.text(.54, .933, "Same-window ranking; 512 historical blocks per layer; all KV heads stored together",
             ha="center", va="top")
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="upper center",
               bbox_to_anchor=(.54, .893), ncol=4, frameon=False, handlelength=1.8,
               handletextpad=.45, columnspacing=1.0, borderaxespad=0)
    for j, n in enumerate((256, 512)):
        bbox = axes[0, j].get_position()
        fig.text((bbox.x0 + bbox.x1) / 2, .839, f"{n}-query window", ha="center", va="center")
    fig.text(.018, .47, "Cumulative reference share (%)", rotation=90, ha="left", va="center")
    fig.text(.54, .092, "Hottest historical blocks per layer (%)", ha="center", va="center")
    fig.text(.54, .047, "Equal-layer means; shade: document min–max (n = 3).", ha="center", va="center")
    fig.text(.54, .017, "Offline native selections; concentration is not prediction accuracy or transfer savings.",
             ha="center", va="center")
    exports = {"access-concentration": export_figure(fig, "access-concentration")}

    # Keep the layer distribution visible alongside the mean curves. This is
    # the primary query/block metric, not an extra selected-model result.
    fig, axes = plt.subplots(3, 1, figsize=(7., 6.5))
    fig.subplots_adjust(left=.095, right=.985, bottom=.13, top=.79, hspace=.40)
    layer_points = []
    for ax, (model, label, _, _, _) in zip(axes, STYLES):
        expected = 36 if model.startswith("Seer") else 32
        x = np.arange(1, expected + 1)
        for n, budget, color, linestyle, marker in [
                (256, "20", "#246B94", "-", "o"),
                (512, "20", "#246B94", "--", "s"),
                (256, "40", "#B65D24", "-", "^"),
                (512, "40", "#B65D24", "--", "v")]:
            values = []
            for layer in x:
                group = [r for r in layers if r["model"] == model and r["metric"] == "query_block"
                         and int(r["window_queries"]) == n and int(r["layer"]) == layer]
                assert len(group) == 3
                v = np.array([float(r[f"top{budget}_share"]) * 100 for r in group])
                values.append(v.mean())
                layer_points.append(dict(model=model, layer=int(layer), window_queries=n, budget=budget,
                                         mean_pct=float(v.mean()), min_pct=float(v.min()), max_pct=float(v.max())))
            ax.plot(x, values, color=color, linestyle=linestyle, linewidth=1., marker=marker,
                    markevery=4, markersize=2.8, markerfacecolor="white", markeredgewidth=.7,
                    label=f"Top {budget}%, {n} queries")
            summary = next(r for r in summaries if r["model"] == model and r["window_queries"] == n
                           and r["metric"] == "query_block")
            assert abs(np.mean(values) / 100 - summary[f"top{budget}"]["macro"]["mean"]) < 1e-12
        ax.set_title(model, pad=5)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_ylim(0, 103)
        ax.set_xlim(.5, expected + .5)
        ax.set_xticks([1, 8, 16, 24, 32] + ([36] if expected == 36 else []))
        ax.set_yticks([0, 20, 40, 60, 80, 100])
        ax.tick_params(length=2.5, pad=2)
        ax.grid(axis="y", color="#E2E6E9", linewidth=.5)
        ax.set_axisbelow(True)
    fig.text(.54, .978, "Access concentration across every layer", ha="center", va="top")
    fig.text(.54, .936, "One reference per query/block; merge heads within each query", ha="center", va="top")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(.54, .895),
               ncol=2, frameon=False, handlelength=2., columnspacing=1.3, borderaxespad=0)
    fig.text(.018, .46, "Share of query–block references (%)", rotation=90, ha="left", va="center")
    fig.text(.54, .077, "Layer ID", ha="center", va="center")
    fig.text(.54, .031, "Mean over 3 reused documents; actual same-window ranking in every layer.",
             ha="center", va="center")
    exports["concentration-by-layer"] = export_figure(fig, "concentration-by-layer")
    output_paths = [OUT / f"{stem}.{ext}" for stem in exports for ext in ("pdf", "svg", "png")]
    output_paths += [OUT / f"{stem}-{suffix}.png" for stem in exports for suffix in ("gray", "reading-size")]
    manifest = {
        "evidence": "Observed native-selector concentration, offline retrospective sorting; not prediction or memory-traffic measurements",
        "generator": str(Path(__file__).resolve()), "generator_sha256": sha(__file__),
        "inputs": {str(DATA / name): sha(DATA / name) for name in ("protocol.json", "curves.csv", "layers.csv", "summary.json")},
        "typography": typography, "exports": exports,
        "statistics": "Per-layer ratios -> equal layer mean within document -> mean across three documents; shade is document min/max",
        "curve_points": points, "layer_points": layer_points,
        "outputs": {p.name: sha(p) for p in output_paths},
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(OUT), "exports": exports, "curve_points": len(points), "layer_points": len(layer_points)}))


if __name__ == "__main__":
    main()
