> Historical three-path record. The current published figure adds the measured Shared FS path from allocation 1517208. See [SHAREDFS_RESULTS.md](SHAREDFS_RESULTS.md) and [SHAREDFS_PROTOCOL.md](SHAREDFS_PROTOCOL.md). The historical measurements below remain unchanged.

# Sparse Prefill and KV reuse: current three-path figure

Latest user direction (2026-09-20): **DRAM only without overlap**.
The published figure selects `FullPrefill`, `HBM`, and `DRAM_no_overlap`.
The user changed this scope while allocation 1517033 was already running.
That allocation subsequently ran out of memory during 1M Full Prefill and
does not supply a complete publishable matrix. Retain its partial overlap
records as historical diagnostics. The completed replacement allocation 1517055 ran only the
requested three paths, from scratch with the same implementation across all
lengths. This scope is explicit in the plot manifest, publication validation,
and `published-three-paths.csv`.
The current measurement script defaults to only these three paths
(`sparse_prefill_kv_fill_one_token_v2`); the original four-path source and
records remain in the run archive (`v1`). No extra overlap run is scheduled.

Final status: 1517055 completed all 28 formal timings; cumulative usage is
15,882 GPU-seconds (4.4117 GPU-hours) of the 19,800-second cap. See
`SPARSE_RESULTS.md` and `blsc/results/1517055/publication-validation.json`.

## Original allocation contract

User request (2026-09-20): redraw the cost comparison with sparse Full Prefill,
HBM reuse, DRAM reuse with overlap, and DRAM reuse without overlap. The user
authorized an additional 2 GPU-hours, raising the cumulative cap to **5.5
GPU-hours (19,800 GPU-seconds)**. Prior allocations consumed 12,172 GPU-seconds.
The remote budget ledger remains authoritative; no automatic budget increase.

## Fixed contract

- Qwen2.5-7B-Instruct-1M, weights revision
  `e28526f7bb80e2a9c8af03b831a9af3812f18fba`; 2 A100-PCIE-40GB, TP2, BF16,
  batch one; contexts 8,192 / 65,536 / 262,144 / 1,010,000.
- Total context C=M+1. Reuse computes **one new token**, with M historical
  tokens. Empty-cache Full Prefill computes M in chunks of at most 8,192 and
  then the same final one-token EXTEND. The endpoint is synchronized model-body
  completion with all C-token KV resident; excludes the output projection.
- The prefix uses the Qwen1M MInference vertical/slash parameters from the
  official Microsoft repository, pinned and hashed in `sparse-config/`.
  DCA position remapping, scaling, and inter/intra/successive regions remain.
  The source's 32,768 context threshold is retained. Above that context threshold, the final one-token EXTEND also uses
  the original sparse selector. At/below the threshold, all paths use the
  validated grouped dense DCA. No separate multi-token recovery tail is used.
- Each HBM/DRAM trial reuses exactly the historical KV produced by that same
  sparse Full Prefill. Sparse and dense prefixes must not be mixed.
- All paths retain the full KV cache. No KV compression or selective H2D.
  Full-prefill time is never used as the compute window of a cache hit.

## Four paths and timing

1. `FullPrefill`: empty KV at timer start; sparse-prefix Prefill and one final
   token. One formal sample per length, with short operator warmup disclosed.
2. `HBM`: prefix KV loaded before the timer; same final token, three formal
   repetitions and one warmup.
3. `DRAM_no_overlap`: pinned prefix KV copied completely and synchronized
   inside the timer, followed by the same final token; three formal samples.
4. `DRAM_overlap`: a dedicated CUDA copy stream submits layer-ordered K/V
   copies. The compute stream waits on each layer's ready event immediately
   before that layer; later copies can continue concurrently. Three formal
   samples. No device-wide synchronization between restore and forward.

Every timed endpoint synchronizes all work; report the maximum elapsed time
across TP ranks. Alternate/rotate reuse path order. D2H backup creation and
cache clearing are untimed. Every layer copies the same exact M-token bytes,
including partial final pages. CUDA events separately record copy intervals
and layer-compute intervals to verify actual overlap, startup delay and layer
dependencies; an asynchronous call alone is not evidence of overlap. Layer
forward intervals include possible CPU-dispatch gaps; their intersections
with copy intervals are evidence of the layerwise pipeline, not a measurement
of simultaneous kernel execution or SM utilization.

## Implementation and validation

The installed ARM64 wheel's common_ops does not contain a verified SM80 sparse
path. Build the existing upstream sparse CUDA and index-conversion sources
on CPU into a separate `aegis_sparse` operator namespace. Preserve installed
libraries and hash both sources and the new library.

The sparse kernel supports GQA directly. Remove the selector's six temporary
K/V head-replication assignments and compute its three QK products by batching
the query groups by KV head. The source transformation is guarded by exact
source hash and AST counts. For multi-query prefix chunks, schedule at most
two query heads sharing one KV head to bound selector-score memory; for one
query, batch all query heads. Keep the original top-k selection and budgets.
Compare this schedule versus the original all-head selector on short
and DCA-boundary shapes, then compare actual model states at an affordable
length before accepting timings. The runtime records sparse invocation counts
and must show the sparse kernel executed above its threshold.

Pilot 1517015 passed all-head upstream comparisons for six shapes through
600K, plus a complete 64K model reference. With the 1M KV pool preallocated,
job 1517028 ran out of memory in the upstream reference's 253,968-token
selector before formal timing. Keep that failed run. In the full matrix,
execute only the synthetic upstream reference in at-most-four-head groups
to bound its temporary replication; the optimized operator still uses its
actual production schedule, and the 64K full-model reference remains
all-head. Per-head selection is unchanged. Preserve the all-head pilot
evidence separately; do not mix its timing samples into the full matrix.

Allocation 1517033 later exhausted memory in the optimized float32 selector
at long context with four-head prefix groups. The replacement uses two-head
groups, releases selector score tensors and their views immediately after
building sparse indices, and enables expandable CUDA allocator segments.
Before formal timing, it adds a 1,010,000-token / 8,192-query operator check
with the fully allocated KV pool. This checks the maximum shape directly;
the upstream reference for that shape uses one head at a time to bound its
own GQA expansion. All failed and partial records remain intact.

Require finite outputs; compare final-token hidden states, all-layer new KV,
and greedy outputs across the four matched paths. Verify restored historical
KV matches the source, the expected transferred byte count, all 28 layer wait
events, and real cross-stream interval intersections. Use the same hooks on
reuse paths so instrumentation does not favor a path.

Sparse-versus-dense differences are approximation effects, not expected to be
zero; within-sparse restoration checks do not establish task accuracy. Do not
claim the sparse method preserves quality on this one repeated-text input.

## Publication under the latest user direction

Publish the three requested series from a complete, validated physical matrix.
Label DRAM as a serialized restore without transfer--compute overlap; do not
generalize its latency gap to a pipelined DRAM baseline. Keep prior dense results
and failures as historical data, never scale them into sparse timings. Use
color plus distinct line/marker patterns; uncertainty denotes min/max timing
repeats, not independent-workload confidence. The current manuscript's cost
panel is Figure 1(c), `paper/figures/recovery-cost.pdf`. Update that panel,
Motivation text/caption, Markdown preview and canonical `paper/main.pdf`.
Inspect the figure at its actual panel width and the compiled manuscript.
