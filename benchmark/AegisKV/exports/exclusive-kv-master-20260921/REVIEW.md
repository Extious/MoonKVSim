# KV Master revision review — 2026-09-21

User request: explain KV Master through request value, prefix/block value, three-tier placement/Peer acceleration, and renewable credit/online management. Incorporate the preceding accepted exclusive-residency and lower-tier-only-rent decisions.

## Delivered scope

- English 3.5 and Chinese draft use the four requested headings, with one compact event-loop Algorithm 2. Tracker/Adapter pseudocode is unchanged.
- Overview, Router rebind, Adapter reclamation, abstract, introduction, evaluation contract and conclusion now use cross-tier checkpoint coverage. Normal execution working KV is separate from managed owners. Migration temporarily consumes two copies, with destination confirmation and old-reader drain preceding source release.
- Peer direct acceleration revaluation; DRAM/storage renewable credit. Value refresh/migration retain paid rent, absence pauses pool aging, true Agent use renews only that Agent. Downward cascade and last-copy fallback are part of complete-plan checks.
- Only four canonical root TeX files. Generated PDF is `paper/main.pdf`; figure sources, numerical records and checks live outside paper.

## Figure review

| Figure | Purpose and evidence | Revision |
|---|---|---|
| 5 System Overview | Constructed architecture, no empirical claim | Preserve three bands, DP symmetry, callouts 1–4 and Master/Connector control edges; show locations and D/S credit, consistent DRAM colors. |
| 7 Request value | Existing constructed cost/size example | Preserved exactly; now belongs to 3.5.1. |
| 8 Sparse recovery | Constructed ownership map | New 3×4 P/D/S matrix; L=2, K1=2, K2=1; each object has one owner; explicit three demand paths and downward handoff. |
| 9 Recovery pipeline | Frozen calibrated analytical schedule | Same numerical inputs and timings; exclusive 1024 MiB managed coverage in all cases. Case d moves 147.492 MiB from DRAM to Peer. Storage inactive, placement already complete; no migration or new integrated result claimed. |
| 10 Credit | Constructed lower-tier arithmetic | Explicit DRAM object with matching mint/green encoding, per-Agent renewal and value-only refresh. No Peer rent. |

Reviewed native PNG and native PDF rasterization at 84.7 mm width, color and grayscale. Placed minimum fonts: overview 10.139 pt; ownership 10.338 pt; credit 10.179 pt; pipeline 10.300 pt. Native Draw.io exports use embedded Type3 glyphs; visual review confirms the intended Libertine appearance and K subscripts. Pipeline uses embedded TrueType Libertine. No missing-glyph replacement markers found.

Iterations: fixed pipeline legend/header overlap before publishing; split the Algorithm 2 state/pressure assignment to prevent stretched wrapping; aligned the DRAM credit object color with the tier map. Inspected manuscript pages 1 and 4–9, including the final regenerated page 8. No overlapping/cropped labels, algorithm spill, overflow or unresolved references/citations. Existing ACM minipage spacing and bibliography underfull notices remain; they do not affect these figures.

## Evidence and reproducibility

- `REVISION_CHECKS.json`: 90 source-preservation, heading, arithmetic, calibration-hash and PDF checks. Most include retained-file checks; this is not 90 controller tests.
- `data/exclusive-layout.json`: complete constructed map and counts.
- `data/pipeline-events.csv`, `pipeline-provenance.json`: per-layer transport records, same-source hashes and explicit assumptions; total/exposed waits reproduced exactly. Peer benefit is approximately 24.160 ms in this profile.
- All unrelated paper figures are byte-identical to the before snapshot. Historical rental costs 462.96/506.39 and the repaired-but-still-inferior results are preserved. No new physical runs; the exclusive online controller and predictor remain unvalidated end-to-end.
- `before/` and `before-manifest.json` preserve the prior paper and project instructions.

Reproduction: run `build_exclusive_kv_figures.py`, native Draw.io PNG/PDF exports with the supplied font config, `render_exclusive_pipeline.py`, publish only the four changed figure PDF/PNG pairs, then `build_paper.sh` and `check_exclusive_kv_revision.py`. Use the repository `.venv/bin/python` for plotting and the audit.
