# Motivation compact layout, 2026-09-21

This layout is superseded by `../motivation-aligned-20260921/`. Retained as
the previous revision; use the newer directory's reproduction instructions.

Layout-only revision of the four current Motivation panels. Canonical delivery:
`benchmark/AegisKV/paper/main.pdf`, page 3. No GPU or new simulation run.

| Panel | Final insertion width | Height | Change |
|---|---:|---:|---|
| Workflow, Figure 1(a) | 2.65 in | 1.655 in | Main nodes widened from 22 to 35 CSS px; all branch timing ratios retained |
| Workflow gaps, Figure 1(b) | 2.00 in | 1.65 in | Shorter axes and tighter annotations |
| Prefill cost, Figure 1(c) | 2.21 in | 1.65 in | Two-row legend, horizontal context ticks; all four context points retained |
| Recovery exposure, Figure 2 | column width, about 3.334 in | about 1.447 in | One-row legend and less unused axis space |

Figure 1 reserves a common 1.67-inch row, down from 2.25 inches. Figure 2's
native canvas is 3.34 by 1.45 inches, down from 3.34 by 2.05 inches. The actual
inserted plot fonts are 10.23–10.45 pt. Subcaptions retain the template's 10 pt
body style. Repeated protocol details were removed from captions and retained
in the main text. A0/A5 remain schematic, red Main stages; A1–A4 bars encode
observed start/finish times on one linear scale, with single-line labels.

## Evidence retained

- The four-branch trace example, common time scale and dashed join slack.
- All 121 workflow maxima, temporal fan-in caveat, median and P90.
- All 16 measured values and original repetition ranges from job 1517208;
  Shared FS remains the measured DPC path with uncontrolled internal caches.
- All four independent single-branch counterfactuals and the original
  Qwen3-14B/A100 static cost model. They are not physical fault measurements.

`before/` preserves the replaced manuscript, plots and edited existing
generators. `sources/` contains editable Draw.io XML and its timing manifest;
`figures/` contains vector plots and provenance. `review/REVIEW.json` records
data checks, font sizes, hashes and the actual manuscript/gray previews.

## Reproduction

Run from the repository root:

```bash
python3 benchmark/AegisKV/experiments/scripts/paper/build_motivation_workflow.py \
  --output-dir benchmark/AegisKV/exports/motivation-compact-layout-20260921/sources

/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f pdf -e --crop -b 0 \
  -o benchmark/AegisKV/exports/motivation-compact-layout-20260921/figures/workflow.pdf \
  benchmark/AegisKV/exports/motivation-compact-layout-20260921/sources/motivation-workflow.drawio

/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f png -e -b 0 -s 3 \
  -o benchmark/AegisKV/exports/motivation-compact-layout-20260921/figures/workflow.png \
  benchmark/AegisKV/exports/motivation-compact-layout-20260921/sources/motivation-workflow.drawio

python3 benchmark/AegisKV/experiments/scripts/paper/render_motivation_compact.py \
  --output-dir benchmark/AegisKV/exports/motivation-compact-layout-20260921/figures

python3 benchmark/AegisKV/experiments/scripts/paper/render_reuse_physical.py \
  benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/measured.json \
  --output benchmark/AegisKV/exports/motivation-compact-layout-20260921/figures/recovery-cost \
  --width 2.21 --height 1.65 --layout compact \
  --paths HBM DRAM_no_overlap SharedFS_no_overlap FullPrefill
```

Publish only these four PDFs to `paper/figures/`, render their matching PNGs
under `paper/figures/preview/`, and run:

```bash
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

Review native exports and the actual insertion widths again after any layout
change. Do not run the legacy reordered renderer to republish the cost panel:
that historical generator uses superseded analytical inputs.
