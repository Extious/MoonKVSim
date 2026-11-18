# Teacher-aligned paper edition

## Version boundary

The user requested a separate version close to the teacher's Overleaf manuscript, limited to figures and citations. The independent upload/build directory is `benchmark/AegisKV/paper_teacher/`; its compiled manuscript is `paper_teacher/main.pdf`. This is based on the two supplied chapter texts, not a live download or synchronization of Overleaf.

The teacher's Background and Motivation are authoritative. The user approved inheriting all other chapters from the existing manuscript pending later teacher updates. The original `paper/` sources, PDF and inspected figure assets are byte-identical to the before snapshot (`review/final-checks.json`).

`review/teacher-text-parity.json` verifies that both teacher chapters' active body text is unchanged after excluding added citations, figure environments and whitespace. Original captions are retained and supplemented with figure source/measurement conditions. The disabled Motivation alternative under `\iffalse` is preserved byte-for-byte. No observations, claims, terminology or equations in the teacher's active body were rewritten.

## Changes

- Filled Background's three empty citation slots and restored support for workflow scheduling, reuse and recovery using the existing bibliography. Used the previously reviewed serving model image, with an accessibility Description.
- Added Motivation citations for checkpoint recovery, the Qwen/MInference configuration, the Claude Code trace, and the three sparse models. These bibliography entries already existed; no new literature claims or experimental runs were introduced.
- Added `agent_value.pdf`: the same frozen four-branch trace, the same matched physical reconstruction medians/ranges, and the same conditional WCT decomposition. Reconstruction is measured; the added WCT is calculated for isolated branch pauses, with other execution fixed. Bars preserve real branch start/end positions and durations. The reported trace population remains 121 workflows, median 137.758 s and P90 1172.684 s (rounded as in the teacher's text).
- Added `kv_value.pdf`: native same-window query/block concentration over all 32 layers and three PG19 texts, with text min--max bands, followed by an explicitly schematic three-layer overlap schedule. The second panel has declared constructed timings, not measured transport or a policy comparison. Data and schedule are retained in `figure-manifest.json` and `data/overlap-schedule.json`.
- Per the user's explicit choice, moved the unchanged recovery-cost plot to the existing measurement appendix as `context_recovery.pdf`. The exact longest context and measured protocol remain in the appendix; the teacher's rounded 1M/latency prose is preserved.
- Moved the existing prefix-reuse figure into Router to retain its supporting evidence. Fixed references from inherited Design and measurement-appendix text to the new observation/figure labels. Added the missing `\system` macro with proper spacing. These changes affect only the new edition.
- Omitted unused inherited figure files from the new upload directory. Their originals and provenance remain in the original edition and the before snapshot. `version-files.json` enumerates the exact new figure inputs.

## Reproduction and verification

1. Generate candidate figures with `python3 benchmark/AegisKV/experiments/scripts/paper/render_teacher_motivation.py`. PDFs/SVGs/PNGs are written under this export directory, without modifying either manuscript automatically.
2. The selected PDFs and previews are copied to `paper_teacher/figures/` and `paper_teacher/figures/preview/`.
3. Compile using `sh benchmark/AegisKV/experiments/scripts/paper/build_teacher_paper.sh`.

The reviewed edition has 18 pages. Figures 2/3 are on page 4, the serving model is on page 2, and the recovery-cost appendix plot is Figure 16 on page 17. The two new figures are each 84.6825 × 92.7100 mm, vector/text with no embedded rasters. Minimum native text is 10.25 pt; checked placed axis labels are 10.2503 pt. Actual color and grayscale exports and the compiled figure pages were inspected. Labels are not clipped, hatch/color semantics remain distinguishable, and the two groups retain matching widths.

The final build has no undefined citations/references or overfull hboxes. Existing acmart vspace advisories and the inherited unused subfigure caption setup remain. Compilation and figure checks do not validate the inherited controller empirically or establish agreement with teacher chapters that have not been supplied.

Final checks, input/output hashes and source evidence are in `review/final-checks.json`, `review/teacher-placement.json`, `review/teacher-text-parity.json`, `figure-manifest.json`, and `version-base.json`.
