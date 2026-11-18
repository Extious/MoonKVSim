# Past 512 queries → next 512 queries: fixed Peer-KV selection

This experiment evaluates the user's proposed windowed adaptation of temporal
locality: at a checkpoint, rank historical KV blocks using the preceding 512
queries, keep a fixed per-layer set, and measure its coverage of the following
512 queries. It reuses existing native sparse-selector traces. It does not run
new GPU forwards, inject failures, or measure recovery latency.

## Protocol

- Checkpoint history: **M = 32,768 tokens**, or 512 physical 64-token blocks per
  layer. The physical placement object is `(layer, 64-token block)`, containing
  all physical KV heads. This is not a per-head placement experiment.
- Predictor observations, using one-based query positions: **32,257–32,768**.
- Primary held-out target: **32,769–33,280**, i.e. the next **512** queries.
- For each layer, reserve the same mandatory sink/local blocks as the original
  comparison, then fill the remaining quota with blocks having the highest
  selection frequency in the observation window. Frequency sums native selector
  occurrences across query positions and selector groups. Ties prefer more
  recent positions. Seer's native 64-query mask applies to all 64 queries in that
  query block; these are not 64 independent selection decisions.
- The chosen set stays fixed throughout the target window. Future selections
  never enter the predictor. This is a windowed adaptation, **not a reproduction
  of SolidAttention's previous-decode-step prefetch policy**; see
  [SolidAttention, §5.1](https://www.usenix.org/conference/fast26/presentation/zheng).
- Per-layer quota: `K = ceil(budget_fraction × 512)`. The main comparison keeps
  the previous approximately 40% quota: **K = 205** (40.039%). Mandatory blocks
  count toward K. This K differs from each native model's selector top-k.
- Budget sensitivity: 10%, 20%, 30%, 40%, 50%, 60%, 80%, and 100%, using the actual
  rounded quota on the plot's horizontal axis.
- Target-window sensitivity: 64, 128, 256, and 512 queries, with exactly the same
  fixed placement for a given model/document/layer/budget.

## Coverage definition and statistics

For a layer, let `S` be the chosen historical blocks and `U` be the **union** of
historical blocks selected anywhere in the target window. Within each document:

```text
coverage = sum_over_layers |S intersect U| / sum_over_layers |U|
```

Repeated accesses to one physical block count once. Therefore this measures
coverage of distinct historical KV objects, **not per-query hit rate, selection
event hit rate, attention-mass coverage, or recovery latency saved**. New suffix
KV is excluded because it does not exist at the checkpoint and is regenerated
during replay. This definition assumes a loaded block can be reused over the
replay window; it does not simulate finite recovery-cache eviction or reloads.

Each model uses the same three previously analyzed PG19 documents (`10146`,
`10321`, `10356`), with one checkpoint per document. Reported means average the
three document-level ratios, after aggregating layers within each document.
Whiskers show document min/max, **not confidence intervals**. Layers and query
positions are not treated as independent document samples.

Recent-first reserves the same mandatory blocks and then chooses the most recent
historical positions. The oracle knows the target demand but retains the same
per-layer quota and mandatory blocks; it cannot move spare quota between layers.
Both mandatory-respecting and relaxed oracles are saved; they coincide for this
dataset. Oracle information is used only for evaluation.

## Results at K = 205 per layer

All entries below are percentages; rounding occurs only for display.

| Model | Past-frequency coverage, next 64 queries | Past-frequency coverage, next 512 queries | Recent-first, next 512 queries | Oracle, next 512 queries | Historical blocks needed by next 512 queries |
|---|---:|---:|---:|---:|---:|
| NOSA-3B | 77.82 | 58.90 | 53.94 | 63.41 | 61.41 |
| MiniCPM4-8B | 53.57 | 44.08 | 43.98 | 44.66 | 89.66 |
| SeerAttention-Qwen3-8B | 43.02 | 40.47 | 40.43 | 40.47 | 98.93 |

The last column divides the demand union by all historical layer/block objects,
not by K. Seer uses the pinned experimental native learned prefill gate captured
in the existing traces; these results are not a claim about stock dense Qwen3.

| Model | Next 64 | Next 128 | Next 256 | Next 512 |
|---|---:|---:|---:|---:|
| NOSA-3B | 77.82 | 70.01 | 64.52 | 58.90 |
| MiniCPM4-8B | 53.57 | 50.03 | 46.78 | 44.08 |
| SeerAttention-Qwen3-8B | 43.02 | 42.16 | 41.13 | 40.47 |

The second table keeps the chosen set fixed and varies only the future window.
Coverage decreases in these traces as the demand union expands. Union size is
necessarily nondecreasing with window length; a decreasing coverage ratio is an
empirical result here, not a general mathematical guarantee.

For the 512-query target, increasing the placement quota gives:

| Model | K = 103 (~20%) | K = 205 (~40%) | K = 308 (~60%) | K = 410 (~80%) |
|---|---:|---:|---:|---:|
| NOSA-3B | 32.41 | 58.90 | 79.14 | 91.47 |
| MiniCPM4-8B | 22.41 | 44.08 | 64.99 | 84.26 |
| SeerAttention-Qwen3-8B | 20.33 | 40.47 | 60.79 | 80.82 |

At 40%, past frequency improves on recent-first by 4.96 percentage points for
NOSA, 0.10 for MiniCPM4, and 0.04 for Seer. MiniCPM4 and Seer are already close to
their distinct-demand oracle. Thus a substantially better predictor alone cannot
give high coverage of their entire 512-query demand union at this fixed quota.
The experiment supports testing temporal locality with an explicit prediction
horizon; it does not establish that a static small hot set covers a long recovery
window across models.

## Evidence boundaries

- These are offline statistics from existing native selector captures on three
  PG19 documents per model, not fresh agentic traces or a generalization test.
- The historical selections and subsequent target selections come from the
  captured native forward path. A deployed decode/checkpoint predictor or an
  actual failure-replay path has not been validated by this experiment.
- `N = Z = 512` is a fixed full-window target. Failures may occur at `N < Z`; the
  primary result is not an average over failure positions. The smaller-window
  results retain this distinction.
- Coverage alone does not determine exposed H2D wait, Peer-over-DRAM benefit, or
  WCT. Those also depend on demand timing, replay compute, transfer overlap,
  bandwidth, and capacity available during recovery.
- The prior manuscript's 512→64 figure and manuscript sources remain unchanged.
  This is a separate diagnostic experiment and figure.

## Files and reproduction

- `protocol.json`: machine-readable experiment contract.
- `layers.csv`: per-layer demand and covered-object counts for every setting.
- `documents.csv`: document-level ratios.
- `summary.json`: document means and min/max.
- `source-sha256.json`: verified trace/configuration/run hashes and analysis
  source hashes. All reused input hashes are checked against the prior figure's
  recorded provenance.
- Plot: `benchmark/AegisKV/exports/retry-kv-z512/coverage-vs-budget.pdf`, plus
  SVG, PDF-rendered PNG, grayscale PNG, `MANIFEST.json`, and `REVIEW.json`.

From `/home/comp/zhanzhao/MoonKVSim`, with NumPy, Matplotlib, and PyMuPDF available:

```bash
python3 benchmark/AegisKV/experiments/scripts/paper/analyze_retry_kv_windows.py
python3 benchmark/AegisKV/experiments/scripts/paper/render_retry_kv_windows.py
```

Analysis checks include input/run integrity, sufficient captured query extent,
causal fixed rankings, quota validity, coverage bounded by oracle, monotonic
demand unions, monotonic coverage across increasing budgets, 100% coverage at full
capacity, and exact reproduction of every original 512→64 document result at all
eight budgets. The standalone figure is designed for 7-inch width; its PDF uses
at least 10.05 pt text. It should be re-laid out before single-column insertion.
