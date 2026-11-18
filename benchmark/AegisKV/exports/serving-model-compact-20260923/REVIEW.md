# Compact serving model — 2026-09-23

User correction: “我不想要这种很窄很高的图像”. The previous detail requirement remains applicable.

## Layout and meaning

The diagram keeps its single-column placement. The two workflow DAGs occupy the top; accepted histories, B2 prompt construction, ready queue and scheduler occupy the left; the two TP2 workers occupy the right. Four history fields and the ready queue now use two rows. Request dispatch runs along the inner bus; accepted outputs return along an outer dashed bus to the history store. This preserves the individual inference requests, B1→Tool→B2 sequence, mixed-workflow assignments, both TP ranks, weights, per-agent KV grids and table metadata. Repeated explanatory wording is in the caption, with no smaller labels.

All ten DAG edge endpoints are unchanged from the detailed version. B/E remain on Worker 0 and C/F on Worker 1, with both agents represented on each rank. Weight/KV grids represent rank-local shards; block counts, placement and geometry remain conceptual, without a timing or physical-host interpretation. The English and Chinese captions now explicitly say that each invocation label denotes one inference request. The accessibility description identifies the new positions. Background prose outside the figure environment is unchanged.

## Final-size review

- Native placed width: 84.6825 mm, unchanged.
- Old/new height: 139.9026 / 87.3373 mm; 37.57% lower.
- Width:height is approximately 1:1.03.
- Minimum extracted font at 84.68 mm: 10.4020 pt, compared with approximately 10.13 pt previously.
- No undersized text, possible out-of-page text or embedded rasters in the figure PDF.
- Native Draw.io PNG includes XML under `mxGraphModel`; 129 unique cells and 17 edges have valid geometry/references.

Viewed the native PNG, final column-width PDF renders in color and grayscale, and the actual manuscript page 2. No visible clipping or label overlaps were found. Workflow/request/agent labels, spatial grouping and the stated rightmost-block encoding retain meaning in grayscale. Fontconfig remains local to the exporter and verifies the TeX installation's Libertine face before native export.

The canonical `paper/main.pdf` builds successfully (23 pages); Figure 1 and its caption remain on page 2. No undefined references/citations, overfull boxes, oversized floats, duplicate-label warnings or outstanding reference-rerun warnings were reported. This checks the figure and its placement, not the scientific completeness of the full paper.

## Reproduce and deliver

```sh
bash benchmark/AegisKV/experiments/scripts/paper/render_serving_model.sh
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

Canonical figure: `paper/figures/serving_model.pdf`; preview: `paper/figures/preview/serving_model.png`; editable source: `sources/serving_model.drawio` in this package. Native PNG/PDF/SVG, metadata, rendering/build logs and page previews are retained here. Previous source, assets, text and manuscript are under `before/`. No raw data or other figures changed. This is a reviewed layout revision, not a claim of user aesthetic acceptance.
