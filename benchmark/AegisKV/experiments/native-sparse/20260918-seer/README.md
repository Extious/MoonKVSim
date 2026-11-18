# Figure 3(c): SeerAttention capture

This directory prepares **SeerAttention-Llama-3.1-8B** as a third sparse
mechanism alongside NOSA-3B and MiniCPM4-8B. NOSA-1B remains in the analysis
tables and archived figure; it is omitted from the main panel for model
diversity, not because of its result.

## Frozen inputs and execution

- Public full checkpoint: `SeerAttention/SeerAttention-Llama-3.1-8B`, revision
  `3ef8780dc42486c8187376897075fc17f52f9373`.
- Use the Python and Triton sources shipped **in that checkpoint**. The separate
  GitHub `upstream/` checkout was inspected for candidate selection; it is not
  the capture implementation.
- Verify each large weight shard against the official LFS SHA256 before loading;
  `checkpoint-verification.json` is written only after every file passes.
- Original BF16 weights, no quantization/offload, batch one, all 32 layers,
  original sparse Prefill path. No reconstructed CPU top-k scores.
- PG19 texts 10146, 10321, 10356 from the existing native-sparse runtime. Tokenize
  with this checkpoint's own tokenizer, keep the first 32,768 + 512 tokens.
- Use the model card's threshold `2e-3`. Disable the published optional
  `seerattn_last_block_dense` flag: forcing the last two query blocks dense
  would change their selection rule when a retry ends at a different boundary.
  This explicit configuration is not the model card's complete quality setup;
  no accuracy-equivalence claim is made.

## Observed objects and comparison

`capture_seer.py` intercepts the actual native threshold selector output and
asserts tensor identity at the original Triton kernel's input. It stores each
layer's boolean `[query head, query block, key block]` mask, with 64-token blocks
on both axes, plus source/text/token/trace hashes and finite-output checks.
The 1,024-token observer-on/off validation must produce identical logits.
`kernel-smoke.json` separately checks kernel compatibility on synthetic
inputs; **those inputs/results are never paper evidence**.

The paper analysis reads the previous eight complete query blocks
(queries 32,257–32,768), predicts the next block (32,769–32,832), and places
`ceil(0.4 × 512) = 205` historical 64-token blocks per layer. Placement objects
contain all KV heads. SeerAttention has no fixed sink or local-window reservation;
the NOSA/MiniCPM policies keep their respective mandatory blocks inside the
same budget. This is a per-model paired policy comparison; the attention
density and selector are not normalized across models.

Past-frequency ranking sums native head/block selections, counting each
64-query mask for its 64 queries. No target masks enter ranking. The denominator
is distinct historical layer/block objects required by the target queries,
not repeated reads. Aggregate covered/needed objects across layers within
each document, then report the mean and min/max over three documents.

The target is a held-out demand proxy under preserved tokens, prefix and
selector semantics. This is **not** an injected failure, a physical retry,
or an agentic workload evaluation. Query-block pooling and exact selector
state remain model-specific recovery requirements.

## Reproduction

From the repository root:

```sh
python3 benchmark/AegisKV/experiments/native-sparse/20260918-seer/prepare_checkpoint.py
sbatch benchmark/AegisKV/experiments/native-sparse/20260918-seer/capture.sbatch
# Run these only after capture logs report CAPTURE_COMPLETE and run.json files pass.
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/analyze_retry_kv_insight.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_design_insights.py --only-retry
sh benchmark/AegisKV/paper/build.sh
```

Preparation can resume completed range chunks. Temporary weight fragments are
not trusted checkpoints; full-file SHA256 verification is mandatory.
