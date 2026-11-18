# Corrected structural Evaluation numbers (v2)

All 135 fixed conditions completed on checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1. Independent source/input/event/resource checks, integer-timestamp figure-endpoint checks, and 178 mm color/grayscale figure review passed. There are 90 F1/F0 pairs and 720 same-ID workflow deltas. Source application and INPUT_MATCH.json bind the fresh implementation; these corrected conditions replace the historical version and are not extra statistical samples.

Each workflow delta is its F1 WCT minus the same-policy F0 WCT. The target view uses the directly faulted workflow. The all-workflow view averages all eight paired deltas within each run before summarizing three constructed seeds. Tables give equal-seed means in seconds. DRAM gain = Restart delta minus DRAM delta; a negative gain is adverse. These are descriptive three-seed results, not confidence intervals or population-tail estimates.

## Target workflow

| Scenario | Fault | Restart ΔWCT (s) | DRAM ΔWCT (s) | AegisKV ΔWCT (s) | DRAM gain vs Restart (s) |
|---|---|---:|---:|---:|---:|
| forkjoin_skew | left.prefill | 49.847821 | 64.278092 | 64.277259 | -14.430271 |
| forkjoin_skew | left.decode | 18.944698 | 17.964583 | 17.963962 | 0.980115 |
| forkjoin_balanced | left.prefill | 40.781083 | 40.170426 | 40.169943 | 0.610657 |
| forkjoin_balanced | left.decode | 30.479364 | 29.627446 | 29.626951 | 0.851918 |
| history_reuse | left.prefill | 82.620163 | 94.671569 | 94.670706 | -12.051406 |
| history_reuse | left.decode | 85.340233 | 76.771808 | 76.770934 | 8.568424 |
| long_decode_drift | left.prefill | 77.380513 | 108.002453 | 108.002453 | -30.621940 |
| long_decode_drift | left.decode | 39.545141 | 60.786677 | 60.786677 | -21.241536 |
| shared_host | left.prefill | 190.546872 | 220.551328 | 220.550454 | -30.004457 |
| shared_host | left.decode | 116.366212 | 157.377937 | 157.377062 | -41.011725 |

## All eight workflows, mean within each run

| Scenario | Fault | Restart ΔWCT (s) | DRAM ΔWCT (s) | AegisKV ΔWCT (s) | DRAM gain vs Restart (s) |
|---|---|---:|---:|---:|---:|
| forkjoin_skew | left.prefill | 37.285774 | 40.172263 | 40.171812 | -2.886489 |
| forkjoin_skew | left.decode | 21.055517 | 17.775000 | 17.774644 | 3.280516 |
| forkjoin_balanced | left.prefill | 42.211081 | 41.737587 | 41.737217 | 0.473494 |
| forkjoin_balanced | left.decode | 28.446548 | 27.918850 | 27.918515 | 0.527698 |
| history_reuse | left.prefill | 93.902944 | 90.570086 | 90.569413 | 3.332858 |
| history_reuse | left.decode | 86.053010 | 85.986661 | 85.986005 | 0.066350 |
| long_decode_drift | left.prefill | 79.321763 | 78.980571 | 78.980571 | 0.341192 |
| long_decode_drift | left.decode | 44.704864 | 51.339560 | 51.339559 | -6.634696 |
| shared_host | left.prefill | 352.048195 | 335.938802 | 335.937096 | 16.109393 |
| shared_host | left.decode | 257.347134 | 238.340432 | 238.338901 | 19.006702 |

Exact means and seed min/max are in figures/wct-endpoint-comparisons.csv; all 90 seed/run points are in figures/wct-endpoints-per-run.csv. AegisKV minus DRAM incremental benefit is small: target mean gains range from 0.000147 to 0.874737 ms, and all-workflow mean gains from 0.00009025 to 1.705603 ms. The long-drift sub-microsecond differences do not establish useful native-sparse HBM recovery benefit.

## Per-seed recovery and two adverse examples

paper-target-recovery-per-seed.csv retains detection, retry queue and admitted recovery service separately for all 90 primary-target observations, along with actual failure/admission/first-output times. The examples below use single seeds and matched policies; they do not concatenate mean component changes into a fictional run. Selected ordinary requests have submit/finish/worker records but no ordinary admission timestamp, so their latency differences cannot be relabelled queue differences.

### history_reuse / left.prefill / seed 19

The exact same wf0000/left invocation 1 fails at logical token 5,786, wall 87.206603474 s on worker 0. Only this Agent is actively interrupted; queued-history restorations are separately listed in reports/negative-case-attribution.json. Healthy workflow WCTs are equal across policies.

| Policy | Detection (s) | Retry queue (s) | Recovery service (s) | Total to first new token (s) | CP tokens |
|---|---:|---:|---:|---:|---:|
| none | 0.001000000 | 1.059500110 | 0.567661226 | 1.628161336 | 0 |
| dram | 0.001000000 | 1.059500110 | 0.042537065 | 1.103037175 | 5632 |
| aegiskv | 0.001000000 | 1.059500110 | 0.042046433 | 1.102546543 | 5632 |

DRAM changes target WCT by **+43.329657501 s**, while changing the all-eight-workflow mean by **-4.810122646 s**. The final left invocation gates join under every policy. Join submission changes by +25.648657581 s and join's observed call latency changes by +17.680999920 s; these add exactly to the target WCT change. The other seven workflows' total change is -81.810638672 s.

The primary recovery is 0.525124161 s faster with DRAM, with identical retry queue and worker 1. Its completion submits the final left call 0.525124161 s earlier, but that call lasts 26.173781742 s longer; hence left completion/join submission is 25.648657581 s later. Join then lasts another 17.680999920 s longer, producing the 43.329657501 s adverse target endpoint. The right final call changes worker 3→1 and join changes worker 2→1. This is a recorded placement/timing association, not a measured 26.17 s or 17.68 s ordinary queue attribution. Other workflows improve enough that the all-workflow mean improves by 4.810122646 s; the two endpoints therefore have opposite signs in this same run.

### long_decode_drift / left.decode / seed 19

The exact same wf0000/left invocation 1 fails at logical token 17,664, wall 444.758967269 s on worker 0. Only this Agent is actively interrupted; queued-history restorations are separately listed in reports/negative-case-attribution.json. Healthy workflow WCTs are equal across policies.

| Policy | Detection (s) | Retry queue (s) | Recovery service (s) | Total to first new token (s) | CP tokens |
|---|---:|---:|---:|---:|---:|
| none | 0.001000000 | 27.807920941 | 2.008082596 | 29.817003537 | 0 |
| dram | 0.001000000 | 27.807920941 | 0.049344545 | 27.858265486 | 17408 |
| aegiskv | 0.001000000 | 27.807920941 | 0.049344341 | 27.858265282 | 17408 |

DRAM changes target WCT by **+49.701013630 s**, while changing the all-eight-workflow mean by **+15.335425873 s**. The final left invocation gates join under every policy. Join submission changes by -1.958738051 s and join's observed call latency changes by +51.659751681 s; these add exactly to the target WCT change. The other seven workflows' total change is +72.982393351 s.

DRAM primary recovery is 1.958738051 s faster with the same 27.807920941 s retry queue and worker 3. Left completion and join submission are correspondingly 1.958738051 s earlier. Join stays on worker 3 but its observed call latency increases by 51.659751681 s, so target WCT worsens by 49.701013630 s. The all-workflow mean also worsens, by 15.335425873 s. The saved summaries support this exact dependency/timestamp decomposition but not an ordinary admission-queue or interference decomposition; no extra simulation was run to obtain missing events.

## Version and model limits

All 360 healthy workflow WCTs remain identical across versions. Fault wall times, workers and active-victim Agent sets remain identical, but 210/240 Restart failed-workflow WCTs change because queued-history recovery semantics also changed; the combined revision is not solely a checkpoint-selector correction. The corrected matrix contains 108 active recovery events and 279 separately classified queued-history restores. All 258 protected recovery records finish full restore before request EOS; no EOS-canceled prefetch occurs in this matrix. There are 11 negative same-policy paired workflow deltas (historical: 1), all retained. See VERSION_COMPARISON.json and the independently produced ../reviews/v1-v2-comparison/ artifacts.

Every workload is an explicitly constructed four-Agent DAG with prescribed arrivals and multi-invocation token histories, executed once. Fixed role priors do not validate remaining-time prediction accuracy. The long-drift provider is constructed and K16 holds both four-block banks; compute uses the dense Qwen3-8B TP1 AIC profile, DP4, L4. No native-sparse WCT, physical inference, continuous batching, measured controller latency, or measured DMA/compute interference is claimed. Historical 8/32/128 simulator execution-cost results remain separately identified under structural-campaign-v1 and are not pooled with this revised implementation.
