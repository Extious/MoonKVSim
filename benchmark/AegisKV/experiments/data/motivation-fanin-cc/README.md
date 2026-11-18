# Motivation Figure 1(a): inferred fan-in subset

This directory filters the pinned CC/Weka trace used by the original
`../motivation-real-cc/real-cc-workflow-parallel-gap.csv` without changing it.

The unit of grouping is a contiguous sequence of top-level `subagent`
records. Require at least two positive-duration branches and common
overlap (`max(start) < min(end)`). Keep a group if all branches have status
`completed` and there is a later top-level Main request whose start time
is at or after the last branch end. Main may issue other requests during
the branch interval. The later Main need not be the immediately next
record. No threshold on the delay before this Main request is imposed.

This is a **temporal fan-in inference**, not an observed causal dependency.
The trace has no join IDs, wait records, or output-consumption edges.
Even a Main request after all branches finish does not prove that it
consumes every output. Paper text and captions retain this limitation.

Apply the group filter before taking the largest branch-duration gap per
workflow. Each workflow then contributes one equally weighted ECDF sample.
The gap is `max(duration)-min(duration)`, not a finish-time gap or fault-time
slack. NumPy's default linear quantiles produce the reported median/P90.

- Original: 393 sessions; 292 qualifying overlapping groups in 124 workflows.
- Retained: 286 groups in 121 workflows; six groups have no Main after all branches.
- Of retained groups, 96 have Main submissions during the branch interval;
  265 have Main execution overlapping the interval (including earlier submissions).
- Median gap: 137.758 s. P90: 1,172.684 s.
- Figure 1(b)'s current median example is reconstructed in
  `../motivation-median-cc/`. The earlier short example also passes this
  filter; its data remain in `../motivation-short-cc/`, and the audit
  retains it under `reference_short_example` for provenance.

`workflow-parallel-gap.csv` contains the plotted workflow maxima;
`group-audit.json` retains every qualifying group's inclusion/exclusion
decision, source line hash, timing, and selected later Main;
`SELECTION.json` records the source hash, rule, counts, changed selections,
and artifact hashes. The raw trace hash is checked, and all original 124
workflow maxima are reconstructed as a consistency check.

From the repository root:

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/select_motivation_fanin_groups.py --trace /path/to/traces.materialized.jsonl
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py --only gap
sh benchmark/AegisKV/paper/build-motivation.sh
```
