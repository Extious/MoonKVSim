# Motivation Figure 1(b)/(c): the median-gap example

Workflow `cfad46925e9d22c6ffb3e0cc4bb925a8a5e3`, group 2, contributes
the exact median of the 121 workflow maxima in Figure 1(a): **137.758 s**.
Selection minimizes distance to that median, with workflow-ID tie-breaking;
it does not rank by prefix length, slack, recomputation cost, or WCT loss.
The same temporally inferred fan-in filter applies to all three panels.

| Branch | Duration (s) | Slack (s) | Prefix tokens | Recompute (s) | WCT loss (s) |
|---|---:|---:|---:|---:|---:|
| A1 | 178.842 | 77.901 | 99,520 | 16.143 | 0 |
| A2 | 253.542 | 0 | 107,968 | 17.773 | 17.773 |
| A3 | 115.784 | 135.118 | 111,168 | 18.396 | 0 |

All original timestamps are retained. Figure 1(b) subtracts the earliest
branch start (5,772.526 s) from the displayed clock, without rescaling it.
The branch join is at 6,029.269 s (256.743 s after the fork), and the
following Main request starts at 6,032.459 s (259.933 s after the fork).
Fan-in remains inferred from timing rather than explicit dependency edges.

Partition the common branch overlap at request boundaries, then choose
the all-LLM-active interval midpoint closest to the branch-overlap midpoint.
Round to 0.1 s only if the result stays in that interval. This yields
5,839.9 s (67.374 s after the fork), inside [5,838.619, 5,841.140] s.
All three prefixes are within the measured 8K--128K cost domain; there is
no extrapolation and no outcome-dependent failure-time selection.

Figure 1(c) interpolates the unchanged MiniCPM4-8B measured curve in log-log
space. Each row is an independent single-branch counterfactual, holding
other branches, downstream execution and queues fixed. Under the assumed
join, the loss is `max(0, recompute-slack)`. Similar costs lead to different
losses, including two fully absorbed delays. These are illustrative cost
substitutions, not original-model failure replays or population-average
failure impacts.

`SELECTION.json` records the complete rule, source hashes, timing and
population linkage. `selected-trace-excerpt.json` retains original branch
metadata and active requests including prefix hash IDs. The old short
example is preserved in `../motivation-short-cc/`.

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/select_motivation_median_example.py --trace /path/to/traces.materialized.jsonl
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_motivation_row.py --only example
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/build_motivation_workflow.py
```

Export the native Draw.io PDF/PNG as documented in `Archived/paper-overleaf-20260919/paper/sections/README.md`,
then rebuild the paper. Figure 1(a)'s ECDF and Figure 2 are unchanged.
