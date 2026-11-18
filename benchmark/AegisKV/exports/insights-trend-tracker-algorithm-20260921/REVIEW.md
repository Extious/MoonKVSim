# Insights survey and Tracker algorithm review

User request (2026-09-21): restore the sparse-model evolution figure in Insights; replace the Workflow Tracker figure with an algorithm.

## Delivered content

- Figure 3: selected sparse/hybrid releases, reported context versus announcement/repository date. Original ten survey records are unchanged; the source data remain `experiments/data/design-insights/sparse-releases.json`. Renderer `experiments/scripts/paper/render_sparse_release_trend.py` emits editable SVG, vector PDF and PNG, and records hashes in MANIFEST.json.
- Figure 4: existing NOSA-8B / NSA-8B / MiniCPM4.1-8B native access concentration, unchanged. Figure 5: existing architecture, unchanged. Figures 6–9 retain both their numbers and their asset bytes.
- Algorithm 1: ten-line causal GBDT / CPM / guarded Slack update. Invalid estimates publish no positive Slack; valid publication carries original durations and guard for joint Master evaluation. Both publication paths invalidate old estimates. Helper semantics, causal features, calibration, event triggers and evidence limits remain in prose.
- Algorithm 2: existing compact Master direct-revaluation algorithm, only renumbered by the counter.
- Chinese companion mirrors figure order, mechanism and algorithm pseudocode. The old Tracker float is in `archived/figures/`; prior editable sources and adverse prediction diagnostics are preserved outside the upload directory.

## Evidence and encoding

The figure is a literature survey of ten selected releases, not ten independent experiments. There are no repeats, confidence intervals, experimental comparisons, fitted trends or measured sparsity percentages. X uses the recorded announcement/repository date; Y uses reported nominal context classes on a log2 axis. Color plus marker shape encodes the sparse branch's selection unit. Model IDs map to individually cited sources in the caption. SALA's block branch and V4's CSA branch do not describe all attention layers. The prose makes no census, deployment-share, monotonic-sparsity or supported-runtime claim.

The September 18 source snapshot and date-basis metadata are retained. This turn rechecked primary model cards for MiniCPM4.1, GLM-5, SALA, DeepSeek-V4, GLM-5.2 and LongCat, DeepSeek V3.2 release pages, MiniMax M3's official announcement, and GLM-5.2/LongCat repository histories. GLM-5's report at https://arxiv.org/html/2602.15763v1 documents the 200K class; its current config is 202,752 positions, so the axis is deliberately **reported context**, not an exact uniform token limit. The DeepSeek April announcement endpoint failed to render in this turn; V4's recorded April preview date is inherited from the prior checked snapshot, and its hybrid architecture and 1M context were verified in the current official model card. This update launches no experiments and changes no measured results.

## Actual export review

- Native size: 84.700 × 46.99 mm. At 84.6667 mm placement, minimum extracted font is 10.296 pt; no raster images, outside text or undersized text were reported.
- Viewed the actual color and grayscale PNGs: IDs, marker shapes, axes and legend are legible and do not overlap. No interpolated/step line implies an unmeasured industry trend.
- Viewed canonical main.pdf pages 4, 5 and 8 after rendering: the survey, concentration and Overview remain single-column; both algorithms fit and remain at body size; no clipping or collision.
- Build: `sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh` completed, with no undefined citations/references, duplicate labels or overfull boxes. Remaining log messages are acmart spacing advisories and underfull paragraphs.
- CHECKS.json records seven subsections, seven Design figures, two algorithms, all figure/algorithm labels, valid Markdown image paths and 36 unchanged other figure assets. The four root TeX files remain the only root TeX files. main.tex, abstract, Background and references.bib are byte-identical to the pre-change snapshot.

Canonical manuscript: `paper/main.pdf` (21 pages). Before snapshot is `before/paper/`; source/data, replaced figure, previews and checks stay outside the Overleaf directory. The review verifies this content/layout revision, not predictor accuracy or integrated recovery performance.
