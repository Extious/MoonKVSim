"""Plot two published approximate values; no benchmark or model execution.

Source: Gao et al., CachedAttention, USENIX ATC 2024, section 2.4,
printed page 114 (USENIX PDF page 5, including its cover).
https://www.usenix.org/system/files/atc24-gao-bin-cost.pdf
"""
from pathlib import Path
import csv
import hashlib
import json
import os

HERE = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(HERE / ".mplconfig"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pymupdf

FONT = Path("/home/comp/zhanzhao/.local/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf")
font_manager.fontManager.addfont(FONT)
plt.rcParams.update({
    "font.family": font_manager.FontProperties(fname=FONT).get_name(),
    "font.size": 10,
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 10,
    "axes.unicode_minus": False,
    "pdf.fonttype": 3,
    "svg.fonttype": "none",
})
with (HERE / "reported-times.csv").open(newline="") as f:
    rows = list(csv.DictReader(f))
values = [float(r["time_ms"]) for r in rows]
assert values == [360.0, 192.0]
width_mm, height_mm = 168, 82
fig = plt.figure(figsize=(width_mm / 25.4, height_mm / 25.4), facecolor="white")
ax = fig.add_axes([.31, .28, .63, .43])
bars = ax.barh([1, 0], values, height=.50, color=["#D55E00", "#0072B2"],
               edgecolor=["#974402", "#005989"], linewidth=.7)
bars[1].set_hatch("///")
ax.set_yticks([1, 0], ["完整 Prefill 重算", "DRAM → GPU\nKV 加载（H2D）"])
ax.tick_params(axis="y", length=0, pad=10)
ax.set_xlim(0, 430)
ax.set_ylim(-.52, 1.52)
ax.set_xticks([0, 100, 200, 300, 400])
ax.set_xlabel("时间（ms）", labelpad=5)
ax.set_axisbelow(True)
ax.grid(axis="x", color="#DADFE4", linewidth=.65)
for k in ["top", "right", "left"]:
    ax.spines[k].set_visible(False)
ax.spines["bottom"].set_color("#9BA2A8")
for y, val in zip([1, 0], values):
    ax.text(val + 9, y, f"约 {val:.0f} ms", va="center", fontsize=11, color="#1C2630")
fig.text(.045, .91, "H2D 加载与 Prefill 重算：论文报告值", fontsize=13,
         va="center", color="#172B3A")
fig.text(.045, .82, "LLaMA-65B  |  4 × NVIDIA A100  |  同一组 2K tokens", fontsize=10,
         color="#485664")
fig.text(.045, .115, "来源：CachedAttention，USENIX ATC 2024，§2.4（正文第 114 页）。", fontsize=9)
fig.text(.045, .045, "按文中近似数值重绘；两种独立操作，不相加；非本项目实测。", fontsize=9, color="#485664")
for ext in ["png", "pdf", "svg"]:
    fig.savefig(HERE / f"h2d-vs-prefill-published.{ext}", dpi=300, facecolor="white")
plt.close(fig)
pdf = pymupdf.open(HERE / "h2d-vs-prefill-published.pdf")
page = pdf[0]
assert abs(page.rect.width * 25.4 / 72 - width_mm) < .05
assert abs(page.rect.height * 25.4 / 72 - height_mm) < .05
page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(HERE / "h2d-vs-prefill-pdf-review.png")
page.get_pixmap(matrix=pymupdf.Matrix(2, 2), colorspace=pymupdf.csGRAY).save(HERE / "h2d-vs-prefill-gray-review.png")
report = {
    "evidence_type": "redrawn_published_approximate_values",
    "source_url": "https://www.usenix.org/system/files/atc24-gao-bin-cost.pdf",
    "source_section": "2.4, printed page 114, USENIX PDF page 5 including cover",
    "source_checked_on": "2026-09-11",
    "project_benchmarks_executed": 0,
    "published_repeat_count": None,
    "independent_replicates_in_this_artifact": None,
    "rows_are": "two operation-level reported values, not two independent runs",
    "error_bars": "not available in source paragraph; omitted",
    "interpretation": "two alternative costs for the same prefix; not additive parts of one retry",
    "h2d_over_full_prefill_ratio": values[1] / values[0],
    "reported_context": "2K tokens, 5 GB KV; units preserved as reported",
    "reported_effective_pcie_bandwidth_GB_s": 26,
    "unresolved_topology_detail": "The paragraph does not specify the per-rank byte split or how concurrent links are accounted for. The figure preserves the published numbers without inferring a TP layout.",
    "limits": [
        "This is one LLaMA-65B hardware configuration, not a Qwen3 or universal latency model.",
        "Full-prefix recomputation is not the remaining prefill window after valid backups are reused.",
        "Not a failure experiment; no direct claim about Peer HBM placement or workflow WCT.",
    ],
    "placed_size_mm": [width_mm, height_mm],
    "visual_review": "pending",
    "artifacts_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob("h2d-vs-prefill-*") if p.is_file()},
}
(HERE / "REVIEW.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
print(json.dumps({"output": str(HERE), "values_ms": values, "H2D_div_prefill": values[1] / values[0], "size_mm": [width_mm, height_mm]}, ensure_ascii=False))
