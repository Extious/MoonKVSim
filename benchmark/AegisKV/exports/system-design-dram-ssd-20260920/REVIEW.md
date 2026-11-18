# DRAM / SSD System Design revision

This is the reviewed design expansion requested in task `01a0bd4a-76fc-70a2-9e63-cddccb4facca`, 2026-09-20. Canonical manuscript: `../../paper/main.pdf`; source and Chinese companion: `../../paper/system_design.tex` and `../../paper/paper_draft.md`.

## Final design contract

1. Shared DRAM and finite SSD/shared storage replace dedicated Peer HBM. Normal GPU execution and bounded recovery workspace remain. Backing stores, manifests, and token logs must survive the declared compute fault.
2. Reuse and failure protection share immutable physical objects. Normal reuse value remains even with large workflow Slack or low failure probability. Each physical replica has one byte charge.
3. Fixed, block-aligned Z triggers review; prefill sealed groups can be offered immediately. Actual M is the complete committed frontier; asynchronous lag may make N exceed Z.
4. Causal native sparse demand proposes legal groups. Layer overlap profiles SSD read, H2D and still-required replay; prediction does not prune the model's actual attention or remove the complete recovery fallback.
5. Per-tier rent screens candidates, with owner-local renewal and paid-rent settlement. Leased replicas still age. Q restricts safe release, not rent. A private trial is committed only after the whole feasible replacement passes joint workflow valuation, uncertainty/hysteresis, version, and reservation checks.
6. DRAM demotion and SSD last-copy deletion have distinct continuation costs. Last-copy deletion must publish a valid older-checkpoint or prompt/log replay fallback and drain old readers before removing data. Finite lower-tier victims are included in the same bounded plan.
7. A common worker failure affects all interrupted branches together; local credit proxies are not additive WCT guarantees. The controller and its profiles remain proposals requiring implementation and validation.

## Figure responsibilities

| Current figure | Source/output stem | Role and evidence |
|---|---|---|
| 3 | sparse-models; retry-kv-prediction | Retained primary-source survey and three-document/model native-demand captures; not failure-recovery performance |
| 4 | system-overview | New proportional single-column Draw.io architecture; control, metadata and byte paths |
| 5 | agent-prefix-reuse | Same trace data, enlarged type and adequate bar height; completed-source prefix proxy, not runtime hits |
| 6 | sparse-recovery | New Draw.io example: mixed-tier full checkpoint, causal predicted/actual selections and mandatory miss path |
| 7 | recovery-pipeline | Replaces the old Peer-specific pipeline: same-byte early/late DRAM retention over SSD/H2D/GPU resources |
| 8 | overlap-frontier | Matched zero-retention baselines and diminishing returns within each compute profile |
| 9 | rental-competition | New Draw.io trial-rent arithmetic; all committed replicas age, eligible victim is only a proposal |
| 10 | checkpoint-lifecycle | New Draw.io distinction between checkpoint advancement, safe DRAM demotion, and explicit SSD fallback/deletion |

The six newly designed figures are 4 and 6–10. Four retain editable `.drawio` sources in `sources/`; their native PNG exports embed `mxGraphModel`. The two numerical figures have CSVs, model configuration, Python and SVG sources. Figure numbers come only from LaTeX.

## Review iterations

- **Semantic pass:** separated complete recovery coverage from sparse residency; preserved normal reuse; replaced Peer-HBM transfer assumptions with SSD→DRAM→HBM; separated tier-local rental ranking from joint common-fault value. Added a complete last-copy fallback branch when reviewing finite SSD behavior.
- **First native-export pass:** found title/connector crossings, text boxes too shallow for line wrapping, tiny gaps hiding bidirectional arrow shafts, plot-header crowding, and prediction colors that mixed selection with residency. Corrected the Draw.io geometry and Matplotlib margins at source.
- **Second export / paper-size pass:** kept Overview single-column at >10 pt, resized native prefix-reuse type and bar heights so white numeric labels fit inside their bars, marked leased credit aging explicitly (1→0), changed “demote” to “propose,” and kept algorithms adjacent to their text instead of floating into Evaluation.
- **Final color/grayscale pass:** added D/S letters and bold selection outlines so sparse placement remains readable in grayscale. Inspected actual canonical pages 4–10 and grayscale pages 7, 9, 10. Figure 10 can float to the next page after its discussion, as a normal full-width LaTeX float; its number and references are consistent.

Earlier rendered paper pages in `review/page-*.png`, revised pages in `review/final-page-*.png`, and canonical/color/grayscale pages in `review/canonical-page-*.png` / `review/gray-page-*.png` retain review evidence. Numeric text bounds and effective inserted font sizes are in `REVIEW.json`. All nine Design figure assets have minimum inserted type at least 10 bp; this is a scoped Design audit, not a new certification of every figure owned by other chapters.

## Reproduction and checks

From the MoonKVSim root, use the project `.venv/bin/python` (the system `python` is too old for the Draw.io generator's ElementTree formatting).

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_storage_design.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/model_storage_overlap.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/check_storage_design_model.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_agent_prefix_reuse.py --output-dir benchmark/AegisKV/exports/system-design-dram-ssd-20260920/figures
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

Export each Draw.io file with the installed native wrapper at `/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli`, using `--crop -x -f pdf -e -b 0` for PDF and `-s 2 -x -f png -e -b 0` for embedded-source PNG, with explicit input and output paths. Generation produces assets in this export directory; copy reviewed PDFs to `paper/figures/` and PNGs to `paper/figures/preview/` before rebuilding. `integrate_storage_design.py` records the one-time concurrent-chapter merge and intentionally rejects changed source anchors; it is not a routine build command.

Validation completed:

- 48 deterministic pipeline configurations: resource exclusion and SSD→H2D→compute dependencies, plus totals 20/19/16 ms for the three plotted cases.
- 16 specification/arithmetic checks: trial rent, tie handling, exhausted Q, multiple victims, monotone rent, unaffected shared-owner credit, common-fault join complementarity, and copy/read-release separation.
- Exactly four root LaTeX files; 23 referenced PDF assets and 23 Markdown images resolved; no undefined references/citations, multiply-defined labels, or overfull boxes in the final canonical build.
- Native Draw.io text remains within export bounds; actual imported scale and font audit passed. Source hashes are in `SOURCE_MANIFEST.json`.

These checks do **not** validate distributed races, backend durability, real engine integration, model-profile calibration, online management overhead, or end-to-end WCT. The existing Evaluation's static four-branch allocator does not evaluate rental, sparse demand, or layer replay; the manuscript now explicitly says so and names their required ablations.

## Analytical assumptions and submission scope

`data/MODEL.json` declares four equal groups, SSD=4 ms/group, H2D=1 ms/group, default compute=3 ms/layer, all demands correctly known at t=0, a separate four-group transient workspace, and independent resources. It excludes foreground contention, predictor misses, SSD jitter, TP and control overhead. The frontier varies compute at fixed transfer work, not a measured mapping from M or N to time. Longer compute can hide later I/O while increasing total restore time.

This expanded manuscript has **16 pages: 14 technical pages and 2 reference pages**. It is a design-review draft; it exceeds EuroSys's 12-technical-page limit. A submission version must consolidate explanation/figures and reconcile overlapping Evaluation illustrations without shrinking required type. No new physical experiment or paper submission was performed.

## Concurrent work and preservation

Fresh Introduction, Background, Evaluation, Related Work, Conclusion and unrelated figures were retained. Integration changed only contribution wording, analytical scope and the requested new ablations in those chapters. The complete previous upload folder is archived at the path in `INTEGRATION.json`; an earlier start-of-task snapshot is in `BASELINE.json`. The no-longer-referenced alternative `storage-overview` asset was moved out of the upload folder. No ZIP was created.
