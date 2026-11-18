"""Analytical runtime-error coverage bounds, not reconstructed measurements.

For positive measured durations t_i, e_i = |prediction_i-t_i|/t_i and
w_i = t_i/sum(t_i), WAPE = sum(w_i*e_i). Markov's inequality gives
sum(w_i*1[e_i <= x]) >= max(0, 1-WAPE/x) for x > 0.

No per-example prediction errors or distributional assumptions are generated.
The zero-error ideal reference is not a result achieved by a cited method.
"""
from pathlib import Path
import csv
import hashlib
import json
import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-runtime-bounds-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pymupdf as fitz
from design_plot_typography import FONT_PT, configure

ROOT = Path(__file__).resolve().parents[5]
DATA = ROOT / "benchmark/AegisKV/experiments/data/agent-runtime-relatedwork/reported-runtime.json"
OUT = ROOT / "benchmark/AegisKV/paper/figures/agent-runtime-bounds"
CAPTION = (
    "Analytical references for runtime prediction. Colored curves are lower bounds "
    "on the runtime-weighted fraction of configurations whose relative prediction "
    "error is at most the horizontal-axis threshold, derived using Markov's "
    "inequality and the reported Runtime WAPE of Wang et al. "
    "(arXiv:2609.03335v1, Table 1): Predictor 7.25% and GBDT 11.05%. "
    "The dashed reference assumes zero prediction error. These are not measured "
    "CDFs, configuration-count fractions, or attainable-optimum results. "
    "The source studies configuration-conditioned execution costs, not complete "
    "multi-round agent durations. Calculations use the published rounded WAPE values."
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coverage_bound(threshold_pct, wape_pct):
    threshold_pct = np.asarray(threshold_pct, dtype=float)
    result = np.zeros_like(threshold_pct)
    positive = threshold_pct > 0
    result[positive] = 100 * np.maximum(0, 1 - wape_pct / threshold_pct[positive])
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads(DATA.read_text())
    wape = {r["source_method"]: r["runtime_wape_pct"] for r in data["rows"]}
    assert wape["Predictor"] == 7.25 and wape["GBDT"] == 11.05
    # Breakpoints are included exactly; the grid samples functions, not agents.
    x = np.unique(np.r_[np.linspace(0, 100, 2001), list(wape.values())])
    curves = {name: coverage_bound(x, wape[name]) for name in ["Predictor", "GBDT"]}
    assert np.isclose(coverage_bound([20], 7.25)[0], 63.75)
    assert np.isclose(coverage_bound([20], 11.05)[0], 44.75)
    for y in curves.values():
        assert np.all((y >= 0) & (y <= 100)) and np.all(np.diff(y) >= -1e-10)

    with (OUT / "analytical-curves.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["relative_error_threshold_pct", "predictor_weighted_coverage_lower_pct",
                         "gbdt_weighted_coverage_lower_pct", "zero_error_ideal_coverage_pct"])
        writer.writerows(zip(x, curves["Predictor"], curves["GBDT"], np.full(len(x), 100)))

    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                        "axes.linewidth": .7, "pdf.fonttype": 42, "svg.fonttype": "none",
                        "savefig.dpi": 250})
    typography = configure()
    fig = plt.figure(figsize=(3.34, 2.65))
    ax = fig.add_axes([.205, .255, .755, .505])
    ax.plot(x, curves["Predictor"], color="#246B94", linewidth=1.6,
            label="Predictor bound (7.25% WAPE)")
    ax.plot(x, curves["GBDT"], color="#BA672C", linewidth=1.6,
            linestyle="-.", label="GBDT bound (11.05% WAPE)")
    ax.plot([0, 100], [100, 100], color="#68737A", linewidth=1.3,
            linestyle="--", label="Perfect prediction (ideal)", clip_on=False)
    ax.set_xlim(0, 100); ax.set_ylim(0, 105)
    ax.set_xticks([0, 25, 50, 75, 100]); ax.set_yticks([0, 50, 100])
    ax.set_xlabel("Relative-error threshold (%)", labelpad=3)
    ax.set_ylabel("Weighted coverage (%)", labelpad=3)
    ax.tick_params(length=3, pad=3)
    ax.grid(axis="y", color="#E1E6E9", linewidth=.6); ax.set_axisbelow(True)
    fig.legend(*ax.get_legend_handles_labels(), loc="upper center", frameon=False,
               bbox_to_anchor=(.52, 1.025), ncol=1, handlelength=1.8,
               handletextpad=.55, labelspacing=.18)
    fig.text(.53, .022, "Analytical bounds; not measured", ha="center", fontsize=FONT_PT)
    stem = "runtime-prediction-bounds"
    for ext in ["pdf", "svg", "png"]:
        fig.savefig(OUT / f"{stem}.{ext}", facecolor="white")
    plt.close(fig)
    with fitz.open(OUT / f"{stem}.pdf") as doc:
        page = doc[0]
        page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False).save(OUT / "pdf-render.png")
        page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), colorspace=fitz.csGRAY,
                       alpha=False).save(OUT / "pdf-render-gray.png")
    (OUT / "caption.txt").write_text(CAPTION + "\n")
    manifest = {
        "evidence_kind": "Analytical weighted-coverage lower bounds parameterized by published aggregates",
        "source": data["source"], "source_sha256": sha(DATA),
        "generator_sha256": sha(Path(__file__)), "typography": typography,
        "size_inches": [3.34, 2.65], "reported_runtime_wape_pct": wape,
        "formula": "L_w(epsilon) = max(0, 1 - WAPE / epsilon), epsilon > 0",
        "weights": "measured runtime_i / sum(measured runtime)",
        "assumptions": ["Measured runtimes are positive", "Published rounded WAPE treated as nominal mean",
                        "Perfect-prediction reference assumes all errors are zero; it is separate from nonzero-WAPE methods"],
        "statistical_units": "No independent samples or experimental runs generated; CSV rows sample analytical functions",
        "empirical_cdf": False, "achievable_optimum_established": False,
        "whole_agent_accuracy_established": False, "replaces_manuscript_figure": False,
        "caption": CAPTION,
        "outputs": {p.name: sha(p) for p in OUT.iterdir()
                    if p.suffix in [".pdf", ".png", ".svg", ".csv", ".txt"]},
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
