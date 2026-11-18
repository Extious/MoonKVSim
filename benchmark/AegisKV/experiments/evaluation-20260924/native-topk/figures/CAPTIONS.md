# Figure selection

`native-topk-coverage.pdf` is the recommended main-paper figure. It shows the
causal selector's absolute coverage, the same-budget bound, and the retained
MiniCPM negative comparison. `native-topk-denominator.pdf` is a complementary
single-column figure if space permits; otherwise retain it with external
diagnostics. It explains why frequent query/block reads do not imply that an
equally large fraction of distinct recovery blocks is resident.

Both canvases are exactly 3.33465 inches (84.70011 mm) wide. Insert at that width,
not as half of another single-column canvas. Heights are 3.30 and 2.50 inches.
All extractable PDF text is Linux Libertine at 10.3 pt. The editable source is
`experiments/scripts/current_design/plot_native_topk.py`.

## Native Top-K coverage

**Suggested caption.** Causal Top-K selection on native sparse-attention traces.
Coverage counts distinct historical KV blocks requested by the following 256
query positions, using the first four layers. Each point averages three PG19
documents; whiskers show their min/max. Within each document, covered and
requested block counts are summed across layers and two checkpoints before
division. The oracle knows future requests but has the same block budget.
Δ is Current minus Recency at K=64, in percentage points; coincident markers
are retained.

**LaTeX draft (no manuscript files changed):**

```tex
\begin{figure}[t]
  \centering
  \includegraphics[width=\columnwidth]{figures/native-topk-coverage.pdf}
  \caption{Causal Top-$K$ selection on native sparse-attention traces.
  Coverage counts distinct historical KV blocks requested by the following
  256 query positions, using the first four layers. Points average three
  PG19 documents; whiskers show their min/max. Within each document, covered
  and requested block counts are summed over layers and two checkpoints
  before division. The oracle knows future requests but has the same
  block budget. $\Delta$ is Current minus Recency at $K=64$, in percentage
  points; coincident markers are retained.}
  \label{fig:eval-native-topk}
\end{figure}
```

**Data and interpretation.** This is causal replay of previously captured native
selectors, with beta=0.9 and epsilon=0.1, two consecutive 256-query windows and
counters initialized 256 queries before the first checkpoint. K is not tuned on
these documents. Source token IDs, source model revisions and selector/mask
identity are audited in `../AUDIT.json`. The three documents, not their layers
or adjacent windows, are the independent units. No model execution, physical
transfer, latency or WCT is inferred from this figure. Current exceeds Recency
by 2.84 and 0.93 pp for NOSA and NSA, and trails it by 0.19 pp for MiniCPM at
K=64. These are descriptive differences, not significance claims.

## Different coverage denominators

**Suggested caption.** Coverage depends on the denominator. With $K=64$ blocks
in each of the first four layers, Current covers a larger fraction of
query-block access events than of distinct historical blocks requested during
the following 256-query windows. Bars average the same three documents and
whiskers show min/max, after within-document aggregation across layers and
two checkpoints. Repeated reads count in the event metric and only once per
checkpoint/layer in the distinct-block metric.

**Data and interpretation.** The underlying selections and placements are
identical; only the metric denominator differs. These are logical selector
counts, not measured cache hits or memory transactions. Initial fill, later
entering-block bytes, all six comparators, other depths, and per-document/layer
results remain in the external CSVs instead of increasing the main figure's
legend or inventing a second performance axis.

## Reproduce

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/plot_native_topk.py
```

`figure-data.csv` contains every plotted point; `EXPORT_METADATA.json` records
input/output hashes and font/geometry metadata. `FIGURE_REVIEW.json` separately
records which actual exports were visually inspected, including color and
grayscale at native insertion width. A compiled-paper page check is still needed
after the parent task integrates either PDF.
