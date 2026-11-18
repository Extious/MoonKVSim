# Wall-time-trained primary v3: descriptive paper data

All 180 conditions passed the independent artifact/resource audit. This is a new
joint predictor/prior/guard intervention, with unchanged core, L/K, arrivals and
profiles. It does not retroactively change the service-proxy v2 results.

Each primary cell averages five fixed identities. Workflows within a run share
queues; there are no population confidence intervals or independent-repeat claims.

| Model | Load | Restart total (s) | DRAM total (s) | HBM gain (ms) |
|---|---:|---:|---:|---:|
| Qwen3-8B | 0.3 | 0.956403 | 0.488464 | 0.508760 |
| Qwen3-8B | 0.65 | 0.956403 | 0.488464 | 0.508244 |
| Qwen3-8B | 0.9 | 2.694406 | 1.970189 | 0.508370 |
| Qwen3-32B | 0.3 | 1.910054 | 1.607198 | 0.035936 |
| Qwen3-32B | 0.65 | 1.144348 | 0.550953 | 0.035937 |
| Qwen3-32B | 0.9 | 2.221522 | 2.075959 | 0.035886 |

HBM gain is DRAM minus AegisKV failure-to-first-new-token latency; positive is
better. Detection, queue and service remain separately available in cell-summary.csv.
Target/cohort and target/Agent sign reversals are retained in
policy-comparisons-per-identity.csv.
All signed extrema and every adverse case remain in EXTREMES_AND_NEGATIVE_CASES.json.
All 7,440 signed workflow pairs remain in paired-workflows.csv, including offsetting
positive/negative workflow changes that cancel in a cohort mean.
All-DRAM only removes the exposure threshold; it retains exposure ordering.
Byte columns sum completed checkpoint/hot/restore and canceled-but-transferred bytes.
Static/Aegis comparison covers all2232 workflow pairs without assuming equality.
This is modeled FCFS/batch-one timing. Unseen admission delay is not called queue time.

## Version and fallback diagnostics

- `Qwen3-8B-load0.65-aegiskv-F1-2`: fallback in 3426/5586 logged unfinished-workflow/control-window observations (61.331901%). Reasons: `{'prediction_minus_age_nonpositive': 3426}`.
- `Qwen3-32B-load0.65-aegiskv-F1-2`: fallback in 3826/6518 logged unfinished-workflow/control-window observations (58.698987%). Reasons: `{'prediction_minus_age_nonpositive': 3826}`.

These are discrete logged-window shares, not elapsed-time fractions. Reason counts can overlap; the two detailed runs do not represent all 180 conditions.

Relative to v2, 11/150 target penalties and 11/150 Agent first-new latencies changed. 16/11160 workflow WCT pairs and 6 saved request-worker fields changed. See v2-v3-cell-summary.csv and v2-v3-policy-contrasts.csv for signed changes; v2-v3-placement.csv separates active recovery and history restore identities. Summary worker/timing fields alone do not establish an ordinary-admission routing chain.

Static/Aegis WCT equality: 2232/2232 pairs; no equivalence outside these conditions is inferred.

Across the 30 model/load/policy cells, retry-queue shares of mean failure-to-first-new latency range from 0.300035 to 0.906569; service shares range from 0.092923 to 0.699091. Detection occupies the remaining share. These are ratios of five-identity means.

The 120 within-v3 policy/identity contrasts include 5 target/cohort and 2 target/Agent sign reversals. The complete sink/non-sink strata and individual negative endpoints remain in the associated CSVs.
