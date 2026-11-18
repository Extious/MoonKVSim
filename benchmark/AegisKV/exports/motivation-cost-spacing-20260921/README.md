# Motivation cost-panel spacing

Current Figure 1 revision for the user's complaint that panel (c) remains crowded.
Panel widths are 2.65 / 1.86 / 2.35 inches; all retain 1.65-inch height.
The cost axes grow from 1.43 to 1.70 inches without reducing the 10.25-point font.
Alternate decades carry labels; intermediate decade grid lines remain. Shorter
axis wording and line/marker legend keys reduce visual density; the plotted
data still include the original error bars and all four paths at four contexts.

The workflow and standalone Figure 2 assets are unchanged. Previous targets
are in `before/`, source snapshots in `sources/`, generated assets in `figures/`,
and paper-sized, 72 dpi and grayscale renders in `review/`. `REVIEW.json` records
data/hash checks and the actual manuscript review; it does not claim user approval.

Reproduce from the repository root using the current source scripts:

```bash
python3 benchmark/AegisKV/experiments/scripts/paper/render_motivation_compact.py \
  --output-dir benchmark/AegisKV/exports/motivation-cost-spacing-20260921/figures
python3 benchmark/AegisKV/experiments/scripts/paper/render_reuse_physical.py \
  benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/measured.json \
  --output benchmark/AegisKV/exports/motivation-cost-spacing-20260921/figures/recovery-cost \
  --width 2.35 --height 1.65 --layout compact
```

Only `workflow-gaps` and `recovery-cost` PDF/PNG assets are published to
`paper/figures/` and `paper/figures/preview/`. Their LaTeX insertion widths match
their native sizes. The unchanged Markdown links resolve to the updated PNGs.
Build the canonical manuscript with:

```bash
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```
