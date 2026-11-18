# Structural campaign: audited descriptive results

All 143 frozen runs completed; 94 F1/F0 pairs produce 1,040 workflow observations. Main figures use only the fault-target workflow of each of the 90 eight-workflow failure runs. Independent constructed seeds are 7, 19 and 41; workflows within a run share resources.

| Scenario | Fault | No backup ΔWCT (s) | DRAM ΔWCT (s) | AegisKV ΔWCT (s) | AegisKV vs DRAM gain (ms) |
|---|---|---:|---:|---:|---:|
| forkjoin_skew | left.prefill | 65.838576 | 65.422962 | 65.422612 | 0.349733 |
| forkjoin_skew | left.decode | 34.744237 | 21.711628 | 21.711278 | 0.349841 |
| forkjoin_balanced | left.prefill | 58.132656 | 57.924849 | 57.924674 | 0.174867 |
| forkjoin_balanced | left.decode | 63.659937 | 62.775039 | 62.774689 | 0.349841 |
| history_reuse | left.prefill | 104.781312 | 104.262363 | 104.262061 | 0.301720 |
| history_reuse | left.decode | 93.308750 | 81.228814 | 81.228639 | 0.174879 |
| long_decode_drift | left.prefill | 78.798311 | 76.651159 | 76.651131 | 0.027391 |
| long_decode_drift | left.decode | 63.133522 | 61.174825 | 61.174783 | 0.041164 |
| shared_host | left.prefill | 402.987400 | 405.736027 | 405.735327 | 0.699831 |
| shared_host | left.decode | 341.902124 | 319.582345 | 319.581819 | 0.525096 |

Values are means of already-paired seed deltas. Exact points, ranges and recovery decomposition are retained in headline-results.csv and figure-data.csv. Negative deltas/gains are retained.

The same Agent/call and resolved total-token threshold are fixed across policies. Prefill and decode use different threshold positions in that call, so the two panels do not isolate stage at one common 80% total-progress point. Primary and collateral victims remain explicit in PHASE_AUDIT.json.

Role priors are hand-set causal proxies, not measured predictor accuracy. All calls declare a fixed 16,384-token output limit; no actual-output-length reservation oracle is used. Long-decode demand is a constructed two-bank selector with a dense Qwen3-8B compute profile; K=16 can accommodate both four-block banks, so its zero misses do not establish robustness under insufficient native-cache capacity.

Scale resource results retain all 12 seed-7 history cases at 8/32/128 workflows. Runtime wall/CPU seconds begin after input loading; peak RSS is the worker-process lifetime high-water mark, including cached workloads and log serialization, not a per-run engine-only peak. Simulated HBM/DRAM byte peaks are separate columns. Every scale run uses summary logs; this frozen version still computes discarded policy_sample estimates. No later performance optimization is applied, and there is no scale reduction.

Integrated evidence remains simulation: the AIC grid mixes empirical and silicon-derived operators; there is no physical model execution, native-kernel timing validation, continuous batching or measured DMA/compute interference in these results. Zero healthy latency differences are conditional on that model.

These results describe the original frozen runtime. The subsequently diagnosed recovery-selector domain issue can affect dense overlap fractions and sparse selected block identities; numerical recovery/WCT effects have not been measured by corrected runs. Completion, ledger and EOS checks establish historical-model accounting only, not repaired semantics. See RECOVERY_DOMAIN_ERRATUM.md at the campaign root.
