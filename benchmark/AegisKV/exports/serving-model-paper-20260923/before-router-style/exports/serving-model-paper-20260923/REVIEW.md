# Concise serving model: manuscript revision

The user accepted the proposed tradeoff: retain workflow DAGs, request dispatch, every rank's K/V and head ranges, and B1-to-B2 prefix reuse; remove the detailed Q/input/attention/projection/all-reduce drawing and explain its essential relationship in the caption.

## Delivered files and scope

- Canonical vector figure: `../../paper/figures/serving_model.pdf`.
- Canonical preview: `../../paper/figures/preview/serving_model.png`.
- Editable source: `sources/serving_model.drawio`; native PNG/PDF/SVG exports are retained here.
- Generator and exporter: `../../experiments/scripts/paper/build_serving_model.py` and `render_serving_model.sh`.
- English caption and accessibility Description in `../../paper/background.tex`; Chinese caption in `../../paper/paper_draft.md`.
- Canonical compiled manuscript: `../../paper/main.pdf`, 23 pages; revised Figure 1 is on page 2.

The old editable source, scripts, manuscript text and PDFs are saved under `before/`. The built-in imagegen edit and its exact prompt are preserved as `imagegen-simplified-study.png` and `IMAGE_EDIT_PROMPT.txt`. The generated study guided the simplified visual structure; the manuscript uses the actual editable native Draw.io export, with deterministic typography. No benchmark results or data were changed.

## Scientific content and native review

The latest user-requested correction removes the Tool node and replaces B1/Tool/B2 with a direct B1-to-B2 edge. All nine DAG nodes now represent agent invocations/requests; nine dependency edges and both join points remain. B2/E1 go to Worker 0 and C1/F1 to Worker 1. Each worker contains both TP ranks; both agents assigned to that worker appear in each rank, each with separate K and V bars. The immediately preceding source and paper assets are retained under `before-tool-removal/`.

The caption explicitly scopes the head ranges to an illustrative eight-head MHA layer with TP=2. Rank 0 has Q/KV heads 0–3 and Rank 1 has heads 4–7, with equal token coverage for a given agent. Every B K/V bar has the same retained-prefix/new-suffix split; diagonal hatching redundantly encodes new tokens in grayscale. The schematic bars do not assert token counts, measured lengths or universal nonreplicated KV layouts. Internal computation is omitted from the figure; one caption sentence describes local matching Q/KV heads and summation after output projection. Dashed output-return paths start at both whole-worker boundaries and end at accepted histories.

The first native export placed `Q/KV heads` close to the rank-box edges. The final export uses two short lines, `Q/KV` and `heads 0–3` / `heads 4–7`, preserving the font size and head meaning.

The final native PNG, placed PNG, grayscale PNG and actual compiled manuscript page 2 were opened. No clipped text, overlapping labels, broken return paths or misplaced head labels were observed. The final size is **84.6825 x 89.5109 mm**, a near-square single-column figure. The minimum extracted font is **10.1963 pt** at that width. The vector PDF contains **no embedded raster images**. These checks establish the revised drawing and typography, not a scientific performance result or inferred user aesthetic acceptance.

## Validation

`layout-checks.json` records the nine DAG edges, two workers, four ranks, eight agent/rank K/V pairs, all head-range labels and removal of the computation flow. `figure-inspection.json` records the PDF hash, exact placement and font checks. `render.log` and `build.log` retain the native export and manuscript build results. The latest LaTeX log has no undefined citations/references, overfull boxes, missing characters or LaTeX errors.

Reproduce from the repository root:

```bash
bash benchmark/AegisKV/experiments/scripts/paper/render_serving_model.sh
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```
