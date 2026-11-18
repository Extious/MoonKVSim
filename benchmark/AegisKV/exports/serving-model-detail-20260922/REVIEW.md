# serving_model detail revision — 2026-09-22

User request: “对于 serving_model.pdf 图像，我需要图像中的更多细节”.

## Delivered change

- Unfold Agent B as B1 → Tool → B2, retaining the parallel C branch and a second workflow. A1/A2 and D1/D2 are successive coordinator invocations, not different agents.
- Show accepted per-agent histories as role/task input, model text, tool results and other-agent output. Build a concrete B2 prompt from a reusable prefix and new tokens.
- Identify ready requests by workflow and invocation; dispatch mixed-workflow batches to two TP2 workers and return accepted outputs to the runtime.
- Expand each TP rank into local model-weight shards, per-agent KV grids and block-table metadata. Grid rows represent layers and columns represent token blocks; the rightmost blocks illustrate KV appended by new input or decoding.
- Keep logical worker failure scopes below the accepted-history store. KV reuse is conditional on matching, available state.

This is a conceptual serving diagram. Node positions, grid dimensions, request placement and failure boundaries are illustrative; they do not report timing, measured placement, physical host topology or experimental performance. Repeated KV grids across ranks depict local shards at the same token positions, not complete replicated KV. The mixed batches illustrate concurrency, not a fixed routing rule.

## Integration

Canonical diagram: `paper/figures/serving_model.pdf`; inline preview: `paper/figures/preview/serving_model.png`. Editable source: `sources/serving_model.drawio` in this package. Native PNG/SVG and native embedded-diagram PDF are also retained here.

The English caption and accessibility description in `paper/background.tex` and the Chinese Figure 1 caption in `paper/paper_draft.md` are synchronized. A comparison against `before/paper/` confirms the Background body is unchanged outside its figure environment; the companion diff changes only the Figure 1 caption. Previous figure/source/manuscript files remain under `before/`.

## Export and checks

Commands from the repository root:

```sh
bash benchmark/AegisKV/experiments/scripts/paper/render_serving_model.sh
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

Native Draw.io export uses a process-local Fontconfig configuration exposing the TeX installation's Linux Libertine O. `fc-match` is checked before export. Chromium embeds the CFF face as Type 3 glyphs; text remains extractable.

The final vector PDF is 84.6825 × 139.9026 mm natively (approximately 84.68 × 139.90 mm when placed). At 84.68 mm, the minimum extracted font is 10.1331 pt. The metadata check finds no undersized spans, outside-page text or embedded rasters. The native PNG includes diagram XML under its `mxGraphModel` key. All 133 XML cells have unique IDs; all 18 edges have valid geometry and references.

Visual review covered the final native PNG, column-size PDF renders in color and grayscale, and the actual manuscript page 2. Shortened history/table labels resolve wrapping, and 4 source pixels of top-title padding eliminate a clipped ligature. No visible label overlaps or clipping remain. Workflow/agent IDs, spatial grouping, rightmost-block position and solid/dashed paths retain the main meaning in grayscale.

The canonical `paper/main.pdf` builds successfully (24 pages); Figure 1 and its caption remain together on page 2. The build log contains no undefined references/citations, overfull boxes, multiply defined labels, oversized floats or outstanding cross-reference rerun warnings. These checks cover the edited diagram and its placement; they do not certify the manuscript's full scientific or submission readiness.

`figure-inspection.json`, render/build logs and `review/` preserve the inspection outputs. `manifest.json` records the final files and hashes.
