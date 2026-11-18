# AegisKV overview: editable revision v10

This is a retained previous revision. The user found its mechanism detail
too sparse; `draft/system_design.md` and `sections/system_overview.tex` now
use [v11](system-overview-v11.md). The v9 model-generated image is retained as
the visual starting point. Every element in v10 is a native Draw.io shape,
label, group, or edge; there is no raster image embedded in the source.

## Content and section mapping

| Annotation | Component | Design section |
|---|---|---|
| 1 | Workflow Tracker | 3.3: slack, tiers, ordering |
| 2 | KV Placement Planner | 3.4–3.5: blocks/layers and admission |
| 3 | Recovery Manager | 3.6: detection signals and concurrent takeover |
| 4 | Adapter, annotated only on DP0 | 3.7: commits, foreground protection, loading |

Connector has no annotation or separate subsection. It executes transfer
plans; policy belongs to KV Placement Planner. DP0 and DP1 expose equivalent
interfaces. Their memory layouts are mirrored to keep the Peer path short.
Local KV is wider than Peer KV; neither width is a measured capacity ratio.

The `Architecture` layer contains the system; the independent `Paper
annotations` layer contains only four black badges. The user can hide or
move annotations without changing module geometry. DP and Planner groups
retain local coordinates. All edges carry relative geometry and bind to
native source/target cells.

## Visual changes and review

1. Replaced the nested module inventory with three open background bands,
   a small workflow DAG, two memory domains, and directly labeled paths.
   Retained frames only where they carry ownership or storage meaning.
2. First native PNG review found request/metadata arrows crossing headings,
   a badge near the Slack label, and plan lines crossing subtitles.
   Moved the routing gutters, put the Planner title/details in one group,
   moved edge endpoints below descriptions, and shortened the DRAM label.
3. Second native PNG review checked symmetry, one badge per component,
   independent DRAM paths, and the direct Peer path. Corrected the remaining
   slanted retry segment. Inspected the native PDF at 177.8 mm width and
   then the figure as placed in `main.pdf` (Figure 4).

At 7-inch placement the native PDF's minimum text size is approximately
10.48 pt. PDF export has no raster images. Review records and rendered
paper pages are in `output/pdf/aegiskv-design-integration-20260918/`.
The graph depicts a logical design, not a completed implementation.
The native SVG includes PNG fallbacks for HTML text labels for viewer
compatibility; use the PDF for fully vector paper placement and the
`.drawio` for editing the graph.

## Rebuild

From the repository root:

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_system_overview.py
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f png -e -b 0 -s 2 -o benchmark/AegisKV/paper/figures/system-overview-v10.drawio.png benchmark/AegisKV/paper/figures/system-overview-v10.drawio
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f pdf -e --crop -b 0 -o benchmark/AegisKV/paper/figures/system-overview-v10.drawio.pdf benchmark/AegisKV/paper/figures/system-overview-v10.drawio
/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli -x -f svg -e -b 0 -o benchmark/AegisKV/paper/figures/system-overview-v10.drawio.svg benchmark/AegisKV/paper/figures/system-overview-v10.drawio
```

Editing the `.drawio` directly is supported; re-export after editing.
Running the Python generator again replaces manual source edits.

## Reference scope

The user's three-band example and earlier generated v9 determine the main
visual hierarchy. Prior inspection of [RACER Figure 7](https://arxiv.org/pdf/2605.04450)
and [LiveUpdate Figure 7](https://arxiv.org/pdf/2512.12295) informed grouping
and alignment, not AegisKV's policy. [RcLLM](https://arxiv.org/pdf/2605.07443),
especially its insights-to-challenges-to-design progression, informs the
reorganized narrative. None of those papers supplies AegisKV experiment results.
