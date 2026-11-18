# 2026-09-24 algorithm mechanism campaign

All 78 runs and 39 F0/F1 pairs completed. `AUDIT.json` independently verifies frozen source hashes, output accounting, recovery-time decomposition, per-resource flow rates, physical transfer bytes, checkpoint/block alignment, checkpoint-only Top-K updates, and the incremental HBM gain formula in recorded policy samples. The 45 current-algorithm tests and 55 core DES/flow/ledger tests are documented in `ALGORITHM_VALIDATION.json`; their source copies are in `validation_sources/`.

This campaign uses the constructed fixed-Agent DAG, configured linear timing costs, and either dense demand or an explicitly synthetic sparse selector. It is a mechanism regression campaign, not a FanOutQA, native-model, calibrated throughput, or physical GPU experiment. No paper-grade confidence interval is inferred from its three-seed cells.

The tested algorithm separates the 256-token checkpoint interval from 64-token KV blocks. Accepted queries contribute once per selected block after deduplication across heads. Counts are decayed and frozen at a checkpoint frontier; publication waits for all TP shards, and only the first L layers are re-ranked then with strict 1+epsilon hysteresis. Later layers are ranked during recovery. Checkpoint versions charge selection metadata and count arrays; first-L HBM versions also charge that metadata. HBM admission and quota shrink use the incremental exposed-delay gain G. Recovery reveals demand after each layer's metadata arrives, gives misses priority over prefetch without losing partially served bytes, and overlaps hit computation with miss transfer.

The main benefit remains the complete DRAM checkpoint. Relative to DRAM alone, HBM reduces mean F1 WCT by 0.35042 ms in the dense fixture and 0.26327 ms in the synthetic sparse fixture. The host-failure fixture saves 1.05318 ms on average. DRAM pressure and lambda=1 s produce zero incremental HBM benefit. All zero results are retained. These are small configured-model effects, not a broad HBM performance claim; K=4 now represents four 64-token blocks rather than the previous four 256-token chunks.

Copy lag remains a concrete limitation: in both protected `slow_copy` runs the failure occurs at 6247 accepted tokens, while the complete published checkpoint ends at token 1024. Recovery therefore rebuilds 5223 tokens, well above Z=256. The simulator does not clip this tail, and the unchanged Design's unconditional at-most-Z wording is not established under asynchronous copy lag.

Important model boundaries:

- Counting and sorting operations are counted but have no calibrated GPU execution charge. DMA/compute interference defaults to zero; `compute_dma_slowdown` is an explicit start-of-event sensitivity parameter. Identical F0 WCT in this campaign is therefore not evidence of zero physical overhead.
- The gain estimator uses configured no-contention transfer and compute costs, and does not inspect future native selections. Real recovery separately contends for shared links.
- Layer compute time is divided in proportion to selected query/block references. The numerical attention and log-sum-exp kernels do not execute. Fluid preemption preserves transferred bytes and assumes no DMA switching delay.
- Actual metadata grows with context; short histories can have fewer than K blocks. HBM copies therefore need not have identical sizes. The implementation follows the stated G ordering without claiming general optimal packing for unequal-sized histories.
- Foreground execution remains FCFS per DP/TP worker, with independently configurable prefill chunks. A failure is one permanent worker or host failure; there is no second failure during recovery.
