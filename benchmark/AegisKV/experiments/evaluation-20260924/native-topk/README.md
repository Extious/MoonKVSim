# Native sparse Top-K: causal two-checkpoint diagnostic

This CPU analysis reuses native selectors captured previously from pinned
NOSA-8B, NSA-8B and MiniCPM4.1-8B models. It runs no new model forward, invokes no
GPU job, and makes no recovery-latency or workflow-completion claim.

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/analyze_native_topk.py --rebuild-inputs
```

The optional `--rebuild-inputs` path rebuilds cross-group query/block incidence
directly from native source files and rechecks masks, tokens, hashes, causal
indices and model provenance. Without it, the compact inputs are hash-checked,
and all 288 original selector-file hashes are still reverified. `PROTOCOL.json`
is written before outcome analysis, `AUDIT.json` seals source/result hashes,
and assertions check strict hysteresis, future-information isolation and the
same-budget oracle upper bound.

## Frozen protocol

- Physical block: 64 tokens, all K/V heads of one layer, 65,536 bytes. Models
  have 32 layers and two KV heads of dimension 128 with BF16 K/V.
- Observe queries starting at absolute zero-based position 31,744. Initialize
  counters to zero there; the first 256 queries warm up the counters. This is a
  deliberately bounded warm-start diagnostic, not whole-request history.
- At checkpoints 32,000 and 32,256, count only past selections, decay all counts,
  then update the set once. Each checkpoint holds complete historical blocks.
- Future windows are `[32000,32256)` and `[32256,32512)`. Score historical blocks
  only: the tail's newly computed KV does not enter the demand denominator.
- Per query, a block is counted once after union over native KV groups.
- K is fixed at 4, 16 or 64 blocks/layer, identically across comparators. Inspect
  first L=1/4/8 layers and all 32. These are prespecified sensitivity points, not
  tuned model-specific deployment choices.
- Proposed counts decay by beta=0.9 at checkpoints; a candidate replaces a
  resident only when its count strictly exceeds `(1 + 0.1) * minimum_count`.
  Ties retain residents; deterministic initial ranking favors recent positions.
- Comparators: same admission with beta=1/epsilon=0; a frequency ranking frozen
  after the first checkpoint; deterministic evenly spaced uniform blocks;
  most-recent blocks; and a future-aware same-K upper bound. The oracle is
  explicitly noncausal and is never used by another comparator.

Native selection already includes each model's sink/local behavior. The analysis
does not add an artificial mandatory reservation that is absent from the current
paper algorithm. NOSA uses a 32,704-token native capture because its pooling
kernel requires `<32768`; every analyzed query lies within the native packed-mask
verification range `[31680,32704)`. NSA/MiniCPM have 32,768-token recordings;
the analyzed prefix is causally aligned and input IDs match across models.

## Metrics and statistical units

`layer-checkpoint-results.csv` retains 10,368 rows and selected block identities.
Its main coverage is **distinct future historical blocks covered / demanded**;
repeated reads count once. `query_block_event_coverage` separately weights each
query/block incidence and must not be substituted for unique demand coverage.
`unique_miss_bytes` counts the logical raw-KV footprint needed once per held-out
window. It is not measured H2D traffic. Selector/compressed metadata, byte headers,
DMA overlap, allocation and in-flight copies are outside this byte counter.

Initial fill, later entering-block copies and evictions are separate columns.
There are only two checkpoint observations, so replacement has only one measured
transition per layer/document; it is not a steady-state estimate. Copy completion
and contention are not simulated in this diagnostic.

`document-results.csv` retains one result per model/document/K/method/L: 648 rows.
It reports both equal layer/checkpoint averages and ratios after summing demand;
event-weighted ratios are separate. `summary.csv` and `summary.json` average the
three document values equally and retain min/max. The independent unit is the
document (n=3 per model); layers and adjacent windows are correlated and are not
treated as independent samples or used to manufacture a confidence interval.

## Retained limits and negative results

The future demand union is substantially broader than same-window frequent
accesses. At K=64 and L=4, the proposed method covers approximately 33.25% of
distinct demand for NOSA, 16.72% for NSA and 16.32% for MiniCPM. The equal-budget
oracle is approximately 33.25%, 16.79% and 16.53%, respectively: the small byte
budget itself limits unique-demand coverage. These results do not support a
general claim that recovery has very few missing blocks.

Relative to recency at that setting, the differences are about +2.83, +0.93 and
**-0.20 percentage points**, respectively. The MiniCPM negative result is kept.
Decay/hysteresis primarily changes entering-block footprints on this short
diagnostic and does not establish a large coverage advantage. The exact
per-document values and all K/L variants remain available; no point is removed
because it is unfavorable. Literature inputs, short warmup, only three documents,
and the lack of recovery timing limit generalization to real Agent workloads.

## Preserved cold-start and tie-rule variant (2026-09-24 audit)

This directory's data, scripts, figures and recorded hashes are frozen. Its
counter origin is query 31,744, and its initial equal-count ranking favors later
block positions. The deployed `current/policy.py:top_blocks` instead favors
earlier positions. Thus these figures remain an external cold-start protocol
variant, not the main evidence for the current deployed policy.

The replacement analysis lives in `../native-topk-warm/`: it evolves counts and
hysteresis from query 0, verifies sampled sets against the actual deployed
function, and retains a paired cold-counter-reset replay with the same deployed
tie rule. This separates counter-lifetime effects from tie-rule effects without
rewriting these original results. Exact document-ratio aggregation rounds the
legacy Current-minus-Recency differences to **+2.84, +0.93, and -0.19 percentage
points**; the earlier +2.83/-0.20 wording above was approximate. Every K is a
per-layer block budget, and coverage includes only historical blocks present at
the checkpoint, excluding newly computed tail blocks.
