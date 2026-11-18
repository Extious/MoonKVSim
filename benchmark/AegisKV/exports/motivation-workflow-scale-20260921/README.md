# Smaller workflow and clearer shared-storage label

Figure 1(a)'s topology is uniformly reduced to 93% of its previous width and
height. Branch durations, start/finish times and join slack retain a single
linear mapping. Text is adjusted at source and remains at least 10.19 pt;
Main nodes remain padded and branch labels remain on one line. The footer
legend retains the common baseline with the two statistical plots.

The three panel widths are 2.48 / 1.86 / 2.52 inches, with an unchanged 1.65-inch
row height. The measured cost panel now uses **Shared storage** and reorders its
two legend columns to accommodate the longer label. Its raw path identifier
`SharedFS_no_overlap` and all measurements remain unchanged. The paper describes
the actual DPC shared filesystem, serialized restore and uncontrolled internal
caches. Markdown, LaTeX and the canonical PDF use the updated terminology.

Reproduction from the repository root:

```bash
python3 benchmark/AegisKV/experiments/scripts/paper/build_motivation_workflow.py \
  --output-dir benchmark/AegisKV/exports/motivation-workflow-scale-20260921/sources
python3 benchmark/AegisKV/experiments/scripts/paper/export_motivation_workflow.py \
  benchmark/AegisKV/exports/motivation-workflow-scale-20260921/sources/motivation-workflow.drawio \
  --output-dir benchmark/AegisKV/exports/motivation-workflow-scale-20260921/figures
python3 benchmark/AegisKV/experiments/scripts/paper/render_reuse_physical.py \
  benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc/results/1517208/measured.json \
  --output benchmark/AegisKV/exports/motivation-workflow-scale-20260921/figures/recovery-cost \
  --width 2.52 --height 1.65 --layout compact
```

Only the workflow and measured-cost PDFs and PNG previews are replaced in
`paper/figures/` and `paper/figures/preview/`; the gap ECDF and Figure 2 remain
unchanged. Build the canonical `paper/main.pdf` with the repository's
`benchmark/AegisKV/experiments/scripts/paper/build_paper.sh`.

`before/` preserves replaced targets; `sources/` preserves editable Draw.io
and generator snapshots. `review/` contains actual paper-size, 72 dpi and
grayscale previews, font inspection and data-provenance checks. Concurrent
main-paper edits are retained.
