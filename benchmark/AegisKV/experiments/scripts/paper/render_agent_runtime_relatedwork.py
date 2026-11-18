"""A sourced candidate for Figure 3(a), with no invented per-example data.

This candidate does not replace the current CC audit or its negative results.
The literature evaluates conditional execution cost, not whole-agent residual
wall-clock time. Keep that distinction visible in the exported caption.
"""
from pathlib import Path
import hashlib
import json
import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp/aegiskv-runtime-literature-mpl")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pymupdf as fitz
from design_plot_typography import FONT_PT, configure

ROOT = Path(__file__).resolve().parents[5]
DATA = ROOT / "benchmark/AegisKV/experiments/data/agent-runtime-relatedwork/reported-runtime.json"
OUT = ROOT / "benchmark/AegisKV/paper/figures/agent-runtime-relatedwork"
EXISTING = ROOT / "benchmark/AegisKV/paper/figures/design-insights"
W, H = 2.24, 1.85
CAPTION = (
    "(a) Prior-work runtime prediction, redrawn from Wang et al., arXiv:2609.03335v1, "
    "Table 1. WAPE is the sum of absolute errors divided by the sum of measured "
    "runtimes. The reported evaluation uses 2,798 Qwen3 deployment configurations. "
    "Graph denotes their graph-based Predictor. These are configuration-conditioned "
    "cost estimates, not AegisKV measurements of whole-agent remaining time. "
    "Panels (b) and (c) retain the current manuscript's data and scope."
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_panel(data, width, height, stem):
    fig = plt.figure(figsize=(width, height))
    # Align the data rectangle with the other two existing Figure 3 panels.
    ax = fig.add_axes([.30, .245, .66, .51])
    rows = data["rows"]
    for y, row in enumerate(rows):
        graph = row["source_method"] == "Predictor"
        ax.barh(y, row["runtime_wape_pct"], height=.48,
                color="#246B94" if graph else "#CED5DA",
                edgecolor="#365467" if graph else "#6F7D86",
                linewidth=.65, hatch="///" if graph else None)
        ax.text(row["runtime_wape_pct"] + .45, y,
                f'{row["runtime_wape_pct"]:.2f}', va="center")
    ax.set_yticks(range(len(rows)), [r["display_method"] for r in rows])
    ax.set_ylim(2.55, -.55)
    ax.set_xlim(0, 21)
    ax.set_xticks([0, 10, 20])
    ax.set_xlabel("Runtime WAPE (%)", labelpad=3)
    ax.tick_params(axis="y", length=0, pad=4)
    ax.tick_params(axis="x", length=3, pad=3)
    ax.grid(axis="x", color="#E1E6E9", linewidth=.6)
    ax.set_axisbelow(True)
    fig.text(.57, .88, "Prior work: Wang et al.", ha="center")
    for ext in ("pdf", "svg", "png"):
        fig.savefig(OUT / f"{stem}.{ext}", facecolor="white")
    plt.close(fig)


def compose(typography):
    doc = fitz.open()
    page = doc.new_page(width=7*72, height=2.95*72)
    page.insert_font(fontname="libertine", fontfile=typography["regular_path"])
    sources = [OUT/"runtime-panel.pdf", EXISTING/"sparse-attention-survey.pdf",
               EXISTING/"retry-kv-prediction.pdf"]
    captions = ["(a) Runtime prediction", "(b) Sparse attention adoption", "(c) Retry KV prediction"]
    for i, (path, caption) in enumerate(zip(sources, captions)):
        x = i*(W+.14)*72
        with fitz.open(path) as src:
            page.show_pdf_page(fitz.Rect(x, 0, x+W*72, H*72), src, 0)
        assert page.insert_textbox(fitz.Rect(x, H*72, x+W*72, (H+.25)*72), caption,
                                   fontsize=FONT_PT, fontname="libertine", align=1) >= 0
    assert page.insert_textbox(fitz.Rect(0, (H+.30)*72, 7*72, 2.95*72), CAPTION,
                               fontsize=FONT_PT, fontname="libertine", lineheight=1.12) >= 0
    doc.save(OUT/"figure3-candidate.pdf")
    page.get_pixmap(matrix=fitz.Matrix(2.5,2.5), alpha=False).save(OUT/"figure3-candidate.png")
    page.get_pixmap(matrix=fitz.Matrix(2.5,2.5), colorspace=fitz.csGRAY,
                   alpha=False).save(OUT/"figure3-candidate-gray.png")
    doc.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads(DATA.read_text())
    assert [r["runtime_wape_pct"] for r in data["rows"]] == [15.29,11.05,7.25]
    plt.rcParams.update({"axes.spines.top":False, "axes.spines.right":False,
                        "axes.linewidth":.7, "pdf.fonttype":42, "ps.fonttype":42,
                        "svg.fonttype":"none", "savefig.dpi":250})
    typography = configure()
    render_panel(data, W, H, "runtime-panel")
    render_panel(data, 3.34, 2.3, "runtime-single-column")
    compose(typography)
    manifest = dict(
        evidence_kind=data["evidence_kind"], source=data["source"],
        generator_sha256=sha(Path(__file__)), data_sha256=sha(DATA),
        panel_size_in=[W,H], single_column_size_in=[3.34,2.3], typography=typography,
        status="Candidate only: conditional runtime cost is not whole-agent remaining time",
        caption=CAPTION, raw_samples_generated=False, uncertainty_bars_generated=False,
        unchanged_inputs={str(p.relative_to(ROOT)):sha(p) for p in [
            EXISTING/"agent-time-audit.pdf", EXISTING/"sparse-attention-survey.pdf",
            EXISTING/"retry-kv-prediction.pdf"]},
        outputs={p.name:sha(p) for p in OUT.iterdir() if p.suffix in [".png",".pdf",".svg"]})
    (OUT/"MANIFEST.json").write_text(json.dumps(manifest,indent=2)+"\n")
    print(OUT)


if __name__ == "__main__":
    main()
