# Current complete-history native-selector figures

`native-topk-warm-coverage.pdf` is the recommended primary figure.
`native-topk-warm-replacement.pdf` is a complementary, optional figure for the
one-checkpoint logical replacement cost. Both retain the MiniCPM negative result.
The preserved `../../native-topk/figures/` uses a different cold/tie protocol and
is not the current-policy primary result.

Both canvases are 3.33465 inches (84.70011 mm) wide. Their heights are 3.30 and
2.30 inches. Insert at that width to preserve the verified Linux Libertine
10.3 pt text. Source: `experiments/scripts/current_design/plot_native_topk_warm.py`.
The editable SVGs are also retained.

## Distinct future-history demand coverage

**Suggested caption.** Native-selector Top-K coverage with complete observed
history. Counters evolve from query 0, decay by 0.9 every 256 queries, and update
with 0.1 relative hysteresis. K is the block budget **per layer**. Coverage counts
distinct historical blocks present at the checkpoint and requested by the next
256 queries, over the first four layers. Evaluated checkpoints are 32000 and
32256. Each point is an equal-weight mean of three PG19 documents; whiskers show
min/max. Within each document, covered and requested counts are summed over
layers and both checkpoints before division. The oracle knows future demand
and has the same K. Δ is Current minus Recency at K=64 in percentage points.

**LaTeX draft (no manuscript files changed):**

```tex
\begin{figure}[t]
  \centering
  \includegraphics[width=\columnwidth]{figures/native-topk-warm-coverage.pdf}
  \caption{Native-selector Top-$K$ coverage with complete observed history.
  Counters evolve from query 0 with decay $\beta=0.9$, checkpoint interval
  $Z=256$, and hysteresis $\epsilon=0.1$. $K$ is the block budget per layer.
  Coverage counts distinct historical blocks present at the checkpoint and
  requested by the next 256 queries, over the first four layers. Checkpoints
  are 32000 and 32256. Points average three PG19 documents; whiskers show
  min/max. Each document's ratio sums covered and requested counts over layers
  and checkpoints. The future-aware oracle has the same $K$.
  $\Delta$ is Current minus Recency at $K=64$, in percentage points.}
  \label{fig:eval-native-topk}
\end{figure}
```

Current covers 32.77%, 16.76%, and 15.45% of distinct demand for NOSA-8B,
NSA-8B, and MiniCPM4.1-8B at K=64. Its differences from Recency are +2.36,
+0.97, and **-1.07 percentage points**. The same-budget oracle covers 33.25%,
16.79%, and 16.53%, so the fixed byte budget itself bounds achievable distinct
coverage. These are descriptive three-document comparisons, not significance
claims or evidence that recovery misses are rare.

## Logical replacement footprint

**Suggested caption.** New raw-KV blocks entering the selected set from
checkpoint 32000 to 32256. K=64 blocks per layer and L=4. For each document,
entering blocks are summed across four layers and multiplied by 65,536 bytes;
bars average the three documents and whiskers show min/max. Initial capacity
fill and all earlier warmup admissions are excluded. The plot measures a logical
placement transition, not measured copy traffic or transfer latency.

Current's means are 0.15, 0.88, and 1.19 MiB; Recency is 1.00 MiB for each
model. Thus the MiniCPM result is worse in both selected-set demand coverage
and replacement footprint at this setting. Only one heldout transition per
document is observed; the full earlier admission history remains in the CSVs.

## Evidence and reproduction

These plots replay sealed native selection records; no new model execution or
recovery timing is inferred. Warm counter evolution has 125/126 completed
updates at the evaluated checkpoints. The deployed earlier-index tie rule is
checked against the actual `current.policy.top_blocks` function. All 288 source arrays
are hash-verified. NOSA's selectors originate natively from q0, while saved
packed-mask identity is only checked over queries [31680,32704); early-query
mask identity is not upgraded by this replay. MiniCPM's full native forward
exceeds its dense-dispatch length; the replay does not rerun smaller model calls.

Independent samples are the three documents per model, not layers or adjacent
windows. `figure-data.csv` contains every plotted point and unit. Full event
coverage, all methods, K/L values, per-document/layer rows, paired cold resets,
and retained adverse results remain outside the compact main figures.

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/plot_native_topk_warm.py
```

`EXPORT_METADATA.json` records source/figure hashes and geometry. Actual PNG and
PDF-render color/grayscale inspection is recorded in `FIGURE_REVIEW.json`.
Compiled-paper placement must still be checked by the parent task after insertion.
