# Motivation alignment and connectors, 2026-09-21

Superseded by `../motivation-balanced-20260921/` after the user rejected the
remaining visual imbalance. This version records the earlier axes-only alignment.

Corrects the preceding compact layout: equal canvas heights and aligned
subcaptions alone did not align the plots' internal regions. The short
branch-entry lines were also almost completely occupied by filled arrowheads.

Figure 1 now uses a shared 1.65-inch canvas height, with the main drawing
region extending from 0.43 to 1.27 inches below the top in all three panels.
Both plots have the same horizontal-axis title baseline. The workflow's first
bar top and last bar bottom match that region; branch widths and start/end
positions remain unchanged. Median/P90 labels occupy the header band, level
with the cost legend. The 2.65/2.00/2.21-inch panel widths are preserved.

The workflow uses thin fork/join connectors without filled branch-entry
arrowheads. A single small open arrow into A5 states the overall direction.
A0/A5 retain their padded 35-by-30 CSS-pixel boxes, and A0/A2/A5 stay red.
All branch labels remain on one line. No data or inference protocol changed.

`review/REVIEW.json` records actual PDF vector bounds, manuscript baselines,
font sizes, hashes and visual review. Native Draw.io outputs and editable XML
are retained. The publication PDF maps the complete native canvas onto its
declared physical size, avoiding the Draw.io exporter's border rounding;
no diagram content is cropped or redrawn. XML is also attached to that PDF.

## Reproduction

From the repository root:

```bash
python3 benchmark/AegisKV/experiments/scripts/paper/build_motivation_workflow.py \
  --output-dir benchmark/AegisKV/exports/motivation-aligned-20260921/sources

python3 benchmark/AegisKV/experiments/scripts/paper/export_motivation_workflow.py \
  benchmark/AegisKV/exports/motivation-aligned-20260921/sources/motivation-workflow.drawio \
  --output-dir benchmark/AegisKV/exports/motivation-aligned-20260921/figures

python3 benchmark/AegisKV/experiments/scripts/paper/render_motivation_compact.py \
  --output-dir benchmark/AegisKV/exports/motivation-aligned-20260921/figures

python3 benchmark/AegisKV/experiments/scripts/paper/render_reuse_physical.py \
  benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/measured.json \
  --output benchmark/AegisKV/exports/motivation-aligned-20260921/figures/recovery-cost \
  --width 2.21 --height 1.65 --layout compact \
  --paths HBM DRAM_no_overlap SharedFS_no_overlap FullPrefill
```

Publish `workflow.pdf`, `workflow-gaps.pdf`, and `recovery-cost.pdf` to
`paper/figures/` and render matching PNGs under `paper/figures/preview/`.
Figure 2 was not changed by this correction. Then build the canonical paper:

```bash
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

Physical layout constants are shared in
`experiments/scripts/paper/motivation_layout.py`. Recheck native output,
internal drawing bounds, axis-title baselines and the actual manuscript row
after future edits; canvas or caption alignment alone is insufficient.
