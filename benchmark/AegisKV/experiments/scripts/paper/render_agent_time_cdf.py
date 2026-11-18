"""Render observed CC prediction errors as empirical CDFs.

The published Graph/Formula/GBDT WAPE scalars are deliberately not inputs:
aggregate WAPE does not determine a per-example error distribution.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-agent-cdf-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pymupdf as fitz
from design_plot_typography import FONT_PT, configure

ROOT = Path(__file__).resolve().parents[5]
DATA = ROOT / "benchmark/AegisKV/experiments/data/design-insights"
OUT = ROOT / "benchmark/AegisKV/paper/figures/agent-time-cdf"
EXISTING = ROOT / "benchmark/AegisKV/paper/figures/design-insights"
METHODS = [
    ("progress_nmae", "GBDT", "#246B94", "-"),
    ("role_median_nmae", "Median", "#65727C", "--"),
    ("role_p90_nmae", "P90", "#B55B25", ":"),
]
CAPTION = (
    "(a) Empirical CDFs from the existing CC experiment: 1,688 agents in 174 workflows, "
    "with workflows held out in five folds. Each agent contributes its mean absolute "
    "remaining-time error divided by its total duration. Median and P90 are training-set "
    "duration priors. All errors are retained on a symmetric-log axis. These curves "
    "do not represent the Graph predictor from the literature. Panels (b) and (c) "
    "retain the current manuscript's data and scope."
)
GBDT_CAPTION = (
    "(a) GBDT remaining-time prediction on the existing CC experiment: 1,688 agents "
    "in 174 workflows, with workflows held out in five folds. Each agent contributes "
    "its mean absolute remaining-time error divided by its total duration. The "
    "empirical CDF retains all errors on a symmetric-log axis; no smoothing or "
    "retraining is performed. This is not the GBDT result reported by Wang et al. "
    "Panels (b) and (c) retain the current manuscript's data and scope."
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render(rows, width, height, name, compact, methods=METHODS):
    fig = plt.figure(figsize=(width, height))
    ax = fig.add_axes([.255,.26,.71,.49] if compact else [.19,.24,.775,.54])
    summaries = {}
    for key, label, color, style in methods:
        values = np.sort([100*float(row[key]) for row in rows])
        assert len(values) == 1688 and np.isfinite(values).all()
        assert values.min() >= 0 and values.max() < 30000
        cdf = np.arange(1,len(values)+1)/len(values)*100
        ax.step(np.r_[0, values, 30000], np.r_[0, cdf, 100], where="post",
                label=label, color=color, linestyle=style, linewidth=1.4)
        summaries[label] = {"n":len(values), "median_pct":float(np.median(values)),
                            "p90_pct":float(np.quantile(values,.9)),
                            "max_pct":float(values.max())}
    ax.set_xscale("symlog", linthresh=10, linscale=.5)
    ax.set_xlim(0,30000); ax.set_ylim(0,103)
    ax.set_xticks([0,100,10000] if compact else [0,10,100,1000,10000],
                  ["0","100","10k"] if compact else ["0","10","100","1k","10k"])
    ax.set_yticks([0,50,100])
    ax.minorticks_off()
    ax.set_xlabel("Normalized MAE (%)",labelpad=3)
    ax.set_ylabel("Agents (%)",labelpad=3)
    ax.tick_params(length=3,pad=3)
    ax.grid(axis="y",color="#E1E6E9",linewidth=.6);ax.set_axisbelow(True)
    fig.legend(*ax.get_legend_handles_labels(),loc="upper center",
               bbox_to_anchor=(.55,1.01),ncol=min(len(methods),2 if compact else 3),frameon=False,
               handlelength=1.8,handletextpad=.4,columnspacing=.8,labelspacing=.2)
    for ext in ("pdf","svg","png"):
        fig.savefig(OUT/f"{name}.{ext}",facecolor="white")
    plt.close(fig)
    return summaries


def compose(typography, caption=CAPTION):
    doc=fitz.open();page=doc.new_page(width=7*72,height=2.95*72)
    page.insert_font(fontname="libertine",fontfile=typography["regular_path"])
    paths=[OUT/"agent-time-cdf-panel.pdf",EXISTING/"sparse-attention-survey.pdf",
           EXISTING/"retry-kv-prediction.pdf"]
    labels=["(a) Agent-time prediction","(b) Sparse attention adoption","(c) Retry KV prediction"]
    for i,(path,label) in enumerate(zip(paths,labels)):
        left=i*2.38*72
        with fitz.open(path) as src:
            page.show_pdf_page(fitz.Rect(left,0,left+2.24*72,1.85*72),src,0)
        assert page.insert_textbox(fitz.Rect(left,1.85*72,left+2.24*72,2.1*72),
            label,fontname="libertine",fontsize=FONT_PT,align=1)>=0
    assert page.insert_textbox(fitz.Rect(0,2.15*72,504,2.95*72),caption,
                               fontname="libertine",fontsize=FONT_PT,lineheight=1.12)>=0
    doc.save(OUT/"figure3-cdf-preview.pdf")
    page.get_pixmap(matrix=fitz.Matrix(2.5,2.5),alpha=False).save(OUT/"figure3-cdf-preview.png")
    page.get_pixmap(matrix=fitz.Matrix(2.5,2.5),colorspace=fitz.csGRAY,
                   alpha=False).save(OUT/"figure3-cdf-preview-gray.png")
    doc.close()


def main():
    global OUT
    parser=argparse.ArgumentParser()
    parser.add_argument("--gbdt-only",action="store_true",
                        help="Show only the existing CC GBDT error CDF; does not retrain")
    args=parser.parse_args()
    methods=METHODS[:1] if args.gbdt_only else METHODS
    caption=GBDT_CAPTION if args.gbdt_only else CAPTION
    if args.gbdt_only:
        OUT=OUT/"gbdt-only"
    OUT.mkdir(parents=True,exist_ok=True)
    with (DATA/"agent-errors.csv").open() as f:
        rows=list(csv.DictReader(f))
    plt.rcParams.update({"axes.spines.top":False,"axes.spines.right":False,
        "axes.linewidth":.7,"pdf.fonttype":42,"svg.fonttype":"none","savefig.dpi":250})
    typography=configure()
    summaries=render(rows,3.34,2.3,"agent-time-cdf-single-column",False,methods)
    render(rows,2.24,1.85,"agent-time-cdf-panel",True,methods)
    compose(typography,caption)
    manifest=dict(evidence="Existing CC held-out prediction experiment, re-rendered; no retraining",
        input_sha256=sha(DATA/"agent-errors.csv"),generator_sha256=sha(Path(__file__)),
        source_summary_sha256=sha(DATA/"agent-summary.json"),caption=caption,
        typography=typography,metrics=summaries,all_agents_retained=True,
        smoothing=False,graph_curve_available=False,
        outputs={p.name:sha(p) for p in OUT.iterdir() if p.suffix in [".pdf",".png",".svg"]})
    (OUT/"MANIFEST.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(json.dumps(summaries,indent=2))


if __name__=="__main__":
    main()
