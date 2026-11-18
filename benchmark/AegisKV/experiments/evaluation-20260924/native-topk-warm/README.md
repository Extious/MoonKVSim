# Native Top-K with complete observed counter history

This analysis starts counters at query 0 of the previously recorded native
causal prefill, performs every 256-query checkpoint update, and evaluates the
same two windows as the preserved cold diagnostic. It uses the actual deployed
equal-count rule: earlier block positions rank first, and strict hysteresis
retains equally scored incumbents. The original `../native-topk/` artifacts
remain a cold-start/later-index-tie protocol variant.

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/analyze_native_topk_warm.py --output /tmp/native-topk-warm-reproduction
```

The command refuses to overwrite a completed audit. A `--single-case` option
checks one actual model/document/layer before a full run. No GPU job or model
forward is required. The independent implementation is checked against imported
`moonkvsim.aegiskv.current.policy.top_blocks`, rather than merely checking itself.
`PROTOCOL.json` is written before outcomes. `AUDIT.json` binds input captures,
the capture-time weights/configuration records, observer source files, deployed
policy source, full query coverage, saved-mask validation ranges, and results.

## Native-origin and lifetime audit

All 288 saved layer arrays contain the native selector outputs from query 0:
NOSA shape `(2,32704,64)`, NSA `(2,32768,64)`, and MiniCPM4.1
`(2,32768,96)`. The capture observers call the original `compressed_attention`
function and save its complete returned indices. Dense fallback was forbidden.
NSA and MiniCPM observers additionally check that the native sparse kernel
receives that same tensor. For NOSA, selection origin is native for the whole
sequence, but packed-mask identity was captured/validated only over
`[31680,32704)`; this analysis reconstructs and checks that entire saved mask.
There is no saved mask identity check for NOSA queries before 31,680.

MiniCPM's `dense_len=8192` dispatch is based on the full native forward's length.
The recorded full request uses native sparse attention throughout. This replay
does not assert that rerunning the model in separate 256-token calls would have
identical early selectors or dense/sparse dispatch. It replays the observed
causal selections at logical checkpoint boundaries.

The runtime snapshot named in `PROTOCOL.json` accumulates counters when an Agent
is protected or recovering, decays at completed checkpoint boundaries, and
publishes Top-K when the checkpoint commits. Here the counter/placement lifecycle
is continuously active from q0, with each logical checkpoint immediately visible.
Selection changes, delayed checkpoint commits, retirements, transfers and model
forward scheduling are not simulated by this standalone diagnostic.

## Frozen protocol and fair history

- Three fixed PG19 documents per pinned model: 10146, 10321, 10356. Original
  tokens, model revisions, weights/configuration provenance and selector hashes
  are reused; no synthetic selector or prompt is substituted.
- Union the two native KV groups **per query**, then increment each block once.
  At every Z=256 checkpoint: `C = (C + new_query_block_counts) * beta`.
  Current uses beta=0.9 and epsilon=0.1; beta=1/epsilon=0 is a separate comparator.
- Update placement at every checkpoint starting at 256. The early set contains
  `min(K, complete_historical_blocks)` members. Once full, a candidate replaces
  the weakest member only on strict `candidate > (1+epsilon)*weakest`.
- Evaluate M=32000 and 32256 after 125 and 126 counter updates. Future demand is
  the next 256 queries, restricted to historical blocks present at the checkpoint.
  New tail blocks are excluded from the denominator.
- K=4,16,64 blocks per layer and first L=1,4,8 or all 32 layers are fixed in
  advance. Each 64-token raw K/V block across both KV heads is 65,536 bytes.
- Static cumulative-frequency ranks **all q0..M0 past queries** at M0=32000 and
  then freezes. It is a baseline, not a single-factor update-only ablation of
  Current. Uniform and recency update with every checkpoint. The explicitly
  future-aware oracle has the same K-block budget; no causal method reads future
  demand during placement.

## Outputs, byte accounting and units

`whole-history-chunk-counts.npz` stores exact per-query-union counts summed into
256-query chunks, including both heldout windows. The first 125 or 126 chunks,
respectively, are the only data visible to causal ranking at the two checkpoints.
It is a reproducible compact derivative of the immutable native arrays.

`layer-checkpoint-results.csv` retains each document/layer/window/K/method result
and its selected block IDs. `document-results.csv` computes both equal
layer/window means and ratios of sums; `summary.csv/json` averages document
values equally and reports their min/max. There are **three documents per model**,
not hundreds of independent layer/checkpoint samples. Ranges are descriptive,
not confidence intervals. All K/L/method results, including negative comparisons,
are retained.

Distinct coverage is covered historical blocks / requested historical blocks.
Event coverage instead counts each query/block incidence and is separately
reported. Miss bytes are the distinct required raw-KV footprint per window.
These logical counts omit compressed/selector metadata and do not measure
physical transfers, recovery latency, or WCT.

The main replacement byte column counts only additions between the two evaluated
sets, M0→M1, for every method. `initial_fill_bytes` reports the K-block capacity
fill once; it is not an assertion that all those bytes first moved at M0.
`preceding_checkpoint_entering_bytes` also records M0 versus its actual warm
predecessor for continuously updated methods; for static/oracle, M0 is their
initial fill and has no warm predecessor. `counter-lifetime-results.csv` retains all prior logical
admissions for continuously updated methods. Static and oracle are excluded from
that lifetime comparison because they are initialized only at M0.

`paired-cold-reset-*` applies the same deployed earlier-index tie rule while
resetting counters at q31744. `warm-cold-tie-comparison.csv` decomposes the
descriptive difference into warm versus this matched reset and matched reset
versus the untouched legacy later-index-tie results. No point is omitted because
it has a negative effect.
