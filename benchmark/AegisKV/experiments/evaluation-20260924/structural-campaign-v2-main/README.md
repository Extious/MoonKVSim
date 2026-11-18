# Corrected constructed structural campaign v2 — main matrix

135 frozen runs: five prescribed four-Agent DAG interventions, three seeds and three policies. Scale extensions are excluded by the predeclared main-only plan. Each DAG executes once. Workload token IDs, arrivals, role priors and phase-drift patterns are constructed.

Qwen3-8B TP1 / DP4 uses the pinned AIC duration grid; no GPU inference is executed. All calls declare a fixed 16K output cap for admission. Role priors are hand-set proxies; this campaign cannot establish remaining-time prediction accuracy. Long-decode drift combines constructed sparse selection with dense-model compute cost; it is not a native sparse model run.

PLAN.json freezes the matrix, every workload hash, failure identity and total-token trigger. MANIFEST.json and source_snapshot/ pin the executed sources. Formal run results live in runs/. smoke/ is excluded from all formal tables. Two prespecified formal runs retain detailed event, flow and journal logs, indexed by TRACE_AUDIT.json.

raw-runs.csv contains one row per run and all counters; paired-workflows.csv contains same-ID F1 minus its own-policy F0, including negative and collateral outcomes. summary.csv reports descriptive mean/p95/p99 without significance claims or request-as-independent confidence intervals. The worker or host remains failed, so collateral capacity-loss effects are part of F1.

VALIDATION.json checks hashes, paired input/config/IDs, exact outputs, zero residual allocations and absence of output-length-oracle admission. Evidence remains modeled and uncalibrated for integrated serving: no continuous batching or measured DMA/compute interference is represented.

## Completed evidence and audit index

All 135 conditions completed on `checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1`, runtime SHA256 `de3a9ce7791218a74e8d50651c2ba1249b194e500eabc0fd9a91c52b978b8c5f`. `PLAN_SEAL.json` predates execution; `INPUT_MATCH.json` verifies all historical workload/profile bytes and old configuration fields, plus the explicit equivalent default `slack_mode=dag`. This is a matched replacement, not an additional sample set.

- `FINAL_AUDIT.json`: final result/figure/document binding, produced by `finalize_audit.py` without running DES.
- `TRACE_MECHANISM_AUDIT.json`: all 135 source/input/event/accounting checks; 108 active recoveries and 279 separately classified queued-history restores. All 258 protected recovery records finish full restoration before EOS; zero EOS-cancel events occur in these cases.
- `VERSION_COMPARISON.json`: all 360 healthy workflow endpoints unchanged, fault wall/worker/active-victim identities unchanged, 210/240 Restart failed-workflow endpoints changed by the combined corrected semantics. Historical and current deltas remain separate.
- `figures/FIGURE_REVIEW.json`: integer-timestamp endpoint recomputation, 90 per-run observations and 20 endpoint/comparison rows, with actual 178 mm color/grayscale review of target, all-workflow, and recovery figures.
- `PAPER_NUMBERS_V2.md`: ten conditions for target and all-workflow means; descriptive ranges, all adverse outcomes, per-seed recovery decomposition, and two exact single-seed negative examples. Ordinary call latency is not re-labelled queue time.
- `history-restores.csv` and `recovery-events.csv`: queued continuations and actively interrupted requests remain separate statistical categories.

No new scale matrix was executed on this version. Historical 8/32/128 workflow execution costs stay under `../structural-campaign-v1/figures/SCALE_RESOURCES.md`; they are whole-simulator CPU/wall and worker-lifetime RSS, not physical controller scalability. Repeated invocations submit immediately, so actual tool/think gaps are absent. The synthetic long-decode two-bank footprint fits K16 and does not test insufficient-budget native hotspot drift.
