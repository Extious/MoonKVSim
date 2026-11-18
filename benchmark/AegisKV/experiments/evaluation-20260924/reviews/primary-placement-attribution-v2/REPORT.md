# Primary retry placement and queue attribution (corrected v2)

All differences are **to policy minus from policy**. Negative recovery latency or WCT contrasts favor the to policy; positive values are adverse. Each WCT policy contrast subtracts its own same-ID F0 first. All 90 contrasts (6 cells x 5 fixed faults x 3 comparisons) and all 5,580 workflow rows remain, including zeros and negative outcomes. No DES or new samples were run.

Recovery latency = detection + retry queue + admitted service through the first new token. Absolute first-token time also includes the actual failure-wall-time difference, reported separately. Retry worker is the actual recorded worker. Full fault identity, wall time, failed workers/hosts, active victim IDs and separately classified queued histories are retained; logical identity matching is asserted, other alignments are reported rather than assumed.

Ordinary requests record submit/finish/latency/worker, not admission. Their latency is not a measured queue decomposition. All calls in the target workflow, including transitive descendants identified from the frozen DAG and latest-finishing predecessors, are exported. For an interrupted call, summary.worker records its completing worker, not necessarily its initial worker.

## Complete-matrix directions

| Contrast | Conditions | Target worse/better/equal | Cohort sum worse/better/equal | Changed retry workers |
|---|---:|---|---|---:|
| none → dram | 30 | 2/28/0 | 4/26/0 | 5 |
| dram → aegiskv | 30 | 1/25/4 | 2/25/3 | 0 |
| all_dram → dram | 30 | 0/1/29 | 0/0/30 | 1 |

## Four requested descriptive cases

These cases were requested from known results, not selected prospectively as an inferential sample. The complete 90-condition table is the denominator.

### Qwen3-32B, load 0.3, F1-4: Restart → DRAM

Target `d88a046051e878a4/final`, invocation 0, logical 286/357; failure wall 350.938160997/350.938160997 s; failed workers [0]/[0]. Retry workers 2 → 3.

| Metric | Restart (s) | DRAM (s) | DRAM - Restart (s) |
|---|---:|---:|---:|
| Detection | 0.001000000 | 0.001000000 | 0.000000000 |
| Retry queue | 3.828532592 | 5.281222610 | 1.452690018 |
| Admitted recovery service | 0.060735219 | 0.031678627 | -0.029056592 |
| Failure to first new token | 3.890267811 | 5.313901237 | 1.423633426 |

Target paired ΔWCT contrast: **1.423633426 s**. All-62-workflow sum contrast: **1.423633426 s**; mean: **0.022961829452 s**. Worse/better/equal workflows: **1/0/61**.

| Call (target/descendant) | Submit difference (s) | Finish difference (s) | Call latency difference (s) | Worker |
|---|---:|---:|---:|---|
| `d88a046051e878a4/final` (target) | 0.000000000 | 1.423633426 | 1.423633426 | 2 → 3 |

### Qwen3-32B, load 0.9, F1-4: Restart → DRAM

Target `d88a046051e878a4/final`, invocation 0, logical 286/357; failure wall 132.218419659/132.218419659 s; failed workers [4]/[4]. Retry workers 5 → 6.

| Metric | Restart (s) | DRAM (s) | DRAM - Restart (s) |
|---|---:|---:|---:|
| Detection | 0.001000000 | 0.001000000 | 0.000000000 |
| Retry queue | 5.273524093 | 1.160091373 | -4.113432720 |
| Admitted recovery service | 0.060735219 | 0.031678627 | -0.029056592 |
| Failure to first new token | 5.335259312 | 1.192770000 | -4.142489312 |

Target paired ΔWCT contrast: **-4.142489312 s**. All-62-workflow sum contrast: **-0.029056592 s**; mean: **-0.000468654710 s**. Worse/better/equal workflows: **1/1/60**.

| Call (target/descendant) | Submit difference (s) | Finish difference (s) | Call latency difference (s) | Worker |
|---|---:|---:|---:|---|
| `d88a046051e878a4/final` (target) | 0.000000000 | -4.142489312 | -4.142489312 | 5 → 6 |

The only other changed workflow is `3118a657689d83a5`: paired WCT contrast 4.113432720 s.

### Qwen3-8B, load 0.9, F1-3: Restart → DRAM

Target `832589258f8bf42e/f637941dbbbf9b9c`, invocation 0, logical 16544/20679; failure wall 83.888162361/83.888162361 s; failed workers [4]/[4]. Retry workers 5 → 5.

| Metric | Restart (s) | DRAM (s) | DRAM - Restart (s) |
|---|---:|---:|---:|
| Detection | 0.001000000 | 0.001000000 | 0.000000000 |
| Retry queue | 2.173993463 | 2.173993463 | 0.000000000 |
| Admitted recovery service | 2.450394090 | 0.675007762 | -1.775386328 |
| Failure to first new token | 4.625387553 | 2.850001225 | -1.775386328 |

Target paired ΔWCT contrast: **2.225998889 s**. All-62-workflow sum contrast: **-34.591675459 s**; mean: **-0.557930249339 s**. Worse/better/equal workflows: **6/11/45**.

| Call (target/descendant) | Submit difference (s) | Finish difference (s) | Call latency difference (s) | Worker |
|---|---:|---:|---:|---|
| `832589258f8bf42e/f637941dbbbf9b9c` (target) | 0.000000000 | -1.775386328 | -1.775386328 | 5 → 5 |
| `832589258f8bf42e/final` (descendant) | -0.155004587 | 2.225998889 | 2.381003476 | 5 → 5 |

Recorded latest-finishing predecessor(s) of `832589258f8bf42e/final`: ['832589258f8bf42e/f637941dbbbf9b9c'] → ['832589258f8bf42e/592d75df6e942457']. This identifies dependency release timing, not unrecorded admission delay.

Local failure-to-first-token recovery improves by 1.775386328 s, but the target finishes 2.225998889 s later. Descendant submit/finish/worker differences above describe the observed chain; they do not by themselves identify ordinary queue wait or a scheduling counterfactual.

### Qwen3-8B, load 0.65, F1-3: Restart → DRAM

Target `832589258f8bf42e/f637941dbbbf9b9c`, invocation 0, logical 16544/20679; failure wall 106.053034720/106.053034720 s; failed workers [5]/[5]. Retry workers 6 → 6.

| Metric | Restart (s) | DRAM (s) | DRAM - Restart (s) |
|---|---:|---:|---:|
| Detection | 0.001000000 | 0.001000000 | 0.000000000 |
| Retry queue | 1.519634609 | 1.519634609 | 0.000000000 |
| Admitted recovery service | 2.450394090 | 0.675007762 | -1.775386328 |
| Failure to first new token | 3.971028699 | 2.195642371 | -1.775386328 |

Target paired ΔWCT contrast: **-1.775386328 s**. All-62-workflow sum contrast: **7.288168000 s**; mean: **0.117551096774 s**. Worse/better/equal workflows: **12/6/44**.

| Call (target/descendant) | Submit difference (s) | Finish difference (s) | Call latency difference (s) | Worker |
|---|---:|---:|---:|---|
| `832589258f8bf42e/f637941dbbbf9b9c` (target) | 0.000000000 | -1.775386328 | -1.775386328 | 6 → 6 |
| `832589258f8bf42e/final` (descendant) | -1.775386328 | -1.775386328 | 0.000000000 | 2 → 0 |

Recorded latest-finishing predecessor(s) of `832589258f8bf42e/final`: ['832589258f8bf42e/f637941dbbbf9b9c'] → ['832589258f8bf42e/f637941dbbbf9b9c']. This identifies dependency release timing, not unrecorded admission delay.

**Endpoint correction:** this target improves by 1.775386328 s; the adverse approximately 0.117551097 s belongs to the all-workflow mean. It must not be reported as target degradation.

## Reproduction and evidence scope

Run `python analyze.py --campaign /absolute/path/to/formal-core-v2-corrected --out /tmp/new-primary-placement-attribution` using a fresh output directory. The script uses only the Python standard library and reads the frozen campaign; it does not import a simulator or launch DES.

AUDIT.json records SHA256 bindings for PLAN/MANIFEST, all frozen source files, profile/priors, six compressed workloads, the passing upstream audit, and all 180 run markers/configs/failure descriptors/summaries. It independently verifies COMPLETE job and summary identity, policy-specific F0, integer-time decompositions, output completion and final-release assertions, then rechecks that all bound files stayed unchanged. This is an accounting/association analysis, not proof that placement is the sole causal source of an observed WCT change. The summaries do not record ordinary admission events or a policy-independent placement counterfactual. No population confidence interval or physical performance claim is made.
