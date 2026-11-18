# Figure 3(c): Qwen3-8B with SeerAttention Prefill gates

The user requested a model using the **SeerAttention mechanism**, without
requiring a particular publisher. This experiment uses Qwen3-8B with Jiwon
Song's experimental **Prefill** gate, not the official SeerAttention-R
Decode-only adapter. It complements NOSA-3B and MiniCPM4-8B in the main figure.
NOSA-1B's existing measurements remain in the source tables and archive.

## Pinned artifacts

- Base: `Qwen/Qwen3-8B`, revision `b968826d9c46dd6066d109eabc6255188de91218`;
  reuse the existing local checkpoint without changing it.
- Gate: `jiwonsong/SeerAttention-Qwen3-8B-AttnGates`, revision
  `ce40326c0ed088757b9cae99273724deb0f0ae85`. The model card calls it experimental
  and reports training on RedPajama-1T-Sample.
- Publisher's implementation: `jiwonsong-dev/CompactAttention`, revision
  `4ed4d7db2faa3b59672cfedccdf6308c3f1d50dc`, under
  `../20260918-seer/qwen3-review/CompactAttention/`.
- Use `SeerAttnQwen3ForCausalLM` and its original **block-sparse** execution
  backend. The separate CompactAttention block-union execution backend is not
  used, so the trace is not relabeled CompactAttention output.

The capture verifies official LFS SHA256 values for all base shards and gate
weights, and verifies that every expected gate parameter loads exactly.
`bootstrap.py` avoids importing unrelated model backends. Unused FlashAttention
entry points are fail-closed guards; invoking any of them fails the run.
No gate scoring, sparse-mask construction, attention calculation, or native
sparse kernel is replaced.

## Protocol

BF16, no quantization/offload, one GPU, batch one, all 36 layers. Use the same
PG19 documents 10146, 10321, 10356 as the other models and this base checkpoint's
tokenizer. Capture a full native forward over 32,768 + 512 tokens. Keep the
gate checkpoint's threshold `0.001` and YaRN settings. Disable its optional
last-two-query-block dense override so truncating a retry does not change
that rule. This configuration is not an accuracy-equivalence claim.

Capture each original native kernel's actual boolean mask as
`[query head, 64-query block, 64-key block]`. The observer must leave short-run
logits unchanged; all layers and final logits must remain finite.

Past queries 32,257–32,768 predict historical KV required by queries
32,769–32,832. Both boundaries align to the native query blocks. The ranking
does not see target masks. A placement object is one layer's 64-token block,
including all KV heads. Allocate 205 of 512 historical blocks per layer for
both policies. There are no fixed sink/local-window reservations in this
SeerAttention configuration; the other models retain their own mandatory
blocks within their budget.

The 40% budget is **relative to each model's historical KV bytes**; the two
policies have identical bytes within a model. Absolute bytes and sparse
attention density are not equalized across architectures. Aggregate distinct
covered/needed objects over layers per document, then show document mean and
min/max over three documents. Native query-block masks count for their 64
queries when computing past frequency.

These are observed sparse Prefill selections and an offline held-out demand
proxy. They are not measurements of injected failures, physical retry latency,
agentic workloads, or sparse-model answer quality.

## Observed result

Slurm job `153224` completed all three documents and 36 layers/document.
The 1,024-token observer on/off validation had exactly zero maximum logit
difference. Capture manifests retain per-layer masks, checksums and finite
output checks.

At the unchanged 40% budget, past frequency covers **43.02%** of distinct
needed objects versus **41.96%** for recent first: **+1.06 percentage points**.
The union of needed blocks across heads spans 92.53% of historical objects;
even per-layer oracle placement reaches only 43.28% coverage at this budget.
This small gain is retained. Neither the threshold nor document selection was
changed after seeing it. Results concern all-head physical placement blocks,
not per-head attention density or measured transfer traffic.

## Reproduction

With pinned weights, source and metadata present:

```sh
sbatch benchmark/AegisKV/experiments/native-sparse/20260918-seer-qwen3/capture.sbatch
# After all three run.json files report complete:
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/analyze_retry_kv_insight.py
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_design_insights.py --only-retry
sh benchmark/AegisKV/paper/build.sh
```

The earlier Llama preparation in `../20260918-seer/` was paused when the user
proposed Qwen3. Its partial downloads are retained; it has no full native
capture and supplies no paper result.
