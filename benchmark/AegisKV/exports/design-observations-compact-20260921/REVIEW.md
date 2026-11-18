# Observations and concise Design review — 2026-09-21

User request: replace Insight with Observation, reduce Overview typographic clutter, and shorten System Design for the paper.

## Delivered changes

- Renamed 3.1 to **Observations**, with four observation statements rather than imperative design directives.
- Preserved seven subsections, KV Master's three parts, three exact pseudocode listings, all eight Design figures, and every label/cross-reference.
- Design source word count (whitespace count, including unchanged captions/TeX) fell from 5,877 to 3,389 (42.33%). The canonical paper fell from 23 to 20 pages; Design starts on p. 3 and Evaluation now starts on p. 9 instead of p. 12.
- Consolidated repeated commit/release explanations under Connector; shortened Tracker training discussion, candidate-search exposition, event taxonomy and walkthroughs. Added an explicitly marked implementation supplement in the Chinese companion for secondary accounting/training/concurrency details. The mechanism-defining definitions, tier-conditional benefits, prefix attribution, fixed Z, variable L/K, full-plan gate, renewal-vs-revaluation distinction, and logical-pin/physical-lease separation remain in English.
- Overview: Linux Libertine O, selective bold headings, regular DP/storage labels, shortened Controller metadata and Master labels, slightly smaller black callouts, and thinner strokes. The resource topology, three bands, DP symmetry and data/control/retry paths are preserved. Minimum font in the actual manuscript is 10.0085 pt (10.0104 pt in the standalone 84.7-mm audit).

## Checks performed

- Read applicable scoped scientific-figure corrections. Used native Draw.io PDF and embedded-source PNG export; no surrogate renderer.
- Opened native PNG, actual manuscript Design pages 3–9, and the grayscale architecture page. Checked label fit, line routing, module/DP identity, column placement, captions and algorithm breaks. No observed clipping or text overlap in the revised Overview.
- Final PDF build: no overfull boxes, undefined citations/references, duplicate labels or LaTeX errors. Existing acmart vspace advisory messages persist for minipage pseudocode; no class/margin/font-size changes were made to compress the paper.
- `DOCUMENT_CHECKS.json` verifies all three pseudocode blocks exactly match the pre-edit version, all labels/figures remain, 38 other figure files are byte-identical, main.tex is unchanged, and the Chinese Evaluation-through-original-Appendix content is unchanged.
- Four-root-tex/Overleaf directory contract preserved. Historical negative results remain unchanged. No new performance experiments or serving correctness claims were added; this revision edits exposition and Overview typography only.

## Reproduction

From repository root, run `python3 benchmark/AegisKV/experiments/scripts/paper/build_observations_overview.py`. Export the generated Draw.io source with the installed native Draw.io wrapper, setting `FONTCONFIG_FILE` to this directory's `sources/fonts.conf`. Use `--crop -x -f pdf -e -b 1` and `--crop -x -f png -e -b 1 -s 2`; the configured Libertine fonts are the installed TeX font files. Publish the resulting PDF and PNG to the existing paper figure paths. Build with `sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh`.

The `before/` directory is the pre-edit source/PDF snapshot; it is not another current manuscript. Final deliverable: `paper/main.pdf`.
