# Structural campaign: audited descriptive results

All 135 frozen main runs completed; 90 F1/F0 pairs produce 720 workflow observations. Target and all-workflow figures use the same 90 eight-workflow failure runs; the all-workflow view first averages all eight same-ID paired deltas within each run. Independent constructed seeds are 7, 19 and 41; workflows within a run share resources.

| Scenario | Fault | Restart ΔWCT (s) | DRAM ΔWCT (s) | AegisKV ΔWCT (s) | AegisKV vs DRAM gain (ms) |
|---|---|---:|---:|---:|---:|
| forkjoin_skew | left.prefill | 49.847821 | 64.278092 | 64.277259 | 0.832298 |
| forkjoin_skew | left.decode | 18.944698 | 17.964583 | 17.963962 | 0.620927 |
| forkjoin_balanced | left.prefill | 40.781083 | 40.170426 | 40.169943 | 0.483625 |
| forkjoin_balanced | left.decode | 30.479364 | 29.627446 | 29.626951 | 0.494957 |
| history_reuse | left.prefill | 82.620163 | 94.671569 | 94.670706 | 0.863011 |
| history_reuse | left.decode | 85.340233 | 76.771808 | 76.770934 | 0.874401 |
| long_decode_drift | left.prefill | 77.380513 | 108.002453 | 108.002453 | 0.000147 |
| long_decode_drift | left.decode | 39.545141 | 60.786677 | 60.786677 | 0.000252 |
| shared_host | left.prefill | 190.546872 | 220.551328 | 220.550454 | 0.874625 |
| shared_host | left.decode | 116.366212 | 157.377937 | 157.377062 | 0.874737 |

Values are means of already-paired seed deltas. Exact points, ranges and recovery decomposition are retained in headline-results.csv and figure-data.csv. Negative deltas/gains are retained.

The same Agent/call and resolved total-token threshold are fixed across policies. Prefill and decode use different threshold positions in that call, so the two panels do not isolate stage at one common 80% total-progress point. Primary and collateral victims remain explicit in PHASE_AUDIT.json.

Role priors are hand-set causal proxies, not measured predictor accuracy. All calls declare a fixed 16,384-token output limit; no actual-output-length reservation oracle is used. Long-decode demand is a constructed two-bank selector with a dense Qwen3-8B compute profile; K=16 can accommodate both four-block banks, so its zero misses do not establish robustness under insufficient native-cache capacity.

No scale extensions are included in this 135-run plan. Runtime wall/CPU seconds begin after input loading; peak RSS is the worker-process lifetime high-water mark, including cached workloads and log serialization, not a per-run engine-only peak. Simulated HBM/DRAM byte peaks are separate columns. Every included scale run uses summary logs and its pinned source identity. Historical and revised implementations must not be pooled into one execution-cost series.

Integrated evidence remains simulation: the AIC grid mixes empirical and silicon-derived operators; there is no physical model execution, native-kernel timing validation, continuous batching or measured DMA/compute interference in these results. Zero healthy latency differences are conditional on that model.
