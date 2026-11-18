# Figure 1 visual balance, 2026-09-21

The user rejected the preceding axes-aligned revision: the workflow occupied
only the central data band, while the two plots also had substantial text above
and below it. Matching axes coordinates did not produce balanced complete panels.

This revision expands the workflow vertically across the plots' header and data
bands. Its first/last branch rectangles span 0.04–1.27 inches below the canvas top.
Useful legend keys explain the red critical path and dashed join slack in the
bottom band, with their text sharing the plots' x-axis title baseline. The ECDF's
quantile labels use the same dark text tone as the other labels. The complete row
remains 1.65 inches high; widths remain 2.65/2.00/2.21 inches.

All horizontal branch coordinates, observed times, slack ratios and padded
A0/A5 nodes are preserved. The thin fork/join connectors and small open arrow
into A5 are preserved. No time axis was reintroduced. All 121 ECDF values are
unchanged; the measured cost panel and Figure 2 PDFs were not modified.

Sources: `sources/motivation-workflow.drawio` and its manifest. Native Draw.io
exports are retained in `figures/`; the publication PDF embeds the XML. Review
includes the actual manuscript row, a 72 dpi final-size view and grayscale under
`review/`. `REVIEW.json` records both objective checks and the visual-review scope;
matching numeric baselines alone is not a claim of visual quality or acceptance.

## Reproduction

From the repository root:

```bash
python3 benchmark/AegisKV/experiments/scripts/paper/build_motivation_workflow.py \
  --output-dir benchmark/AegisKV/exports/motivation-balanced-20260921/sources

python3 benchmark/AegisKV/experiments/scripts/paper/export_motivation_workflow.py \
  benchmark/AegisKV/exports/motivation-balanced-20260921/sources/motivation-workflow.drawio \
  --output-dir benchmark/AegisKV/exports/motivation-balanced-20260921/figures

python3 benchmark/AegisKV/experiments/scripts/paper/render_motivation_compact.py \
  --output-dir benchmark/AegisKV/exports/motivation-balanced-20260921/figures
```

Publish only `workflow.pdf` and `workflow-gaps.pdf`, and render their matching
PNG previews for the Markdown companion. Preserve the existing cost and exposure
assets. Build the current manuscript with:

```bash
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```
