# Post-review O3 small-pool diagnostic

All 72 predeclared runs completed. This is a constructed allocatable-pool boundary applied to the original four-workflow input once. It does not demonstrate production 80GB capacity pressure. The 52 exact invocations, human DAG, original order/arrivals, declared cap512, L11/K16 and logical fault16228 are preserved. The online predictor, role priors and guard use the separately sealed simulator-walltime model; pool and DMA coefficient are the predeclared sensitivities.

Pool per rank = 5,039,327,808 B maximum declared foreground allocation (raw KV plus metadata) + 2GiB original reserve + 0/32/128MiB margin. Every invocation fits individually. Fixed32/128/4096 always use the same safe core reclaim and leases, reapplying their target at the next control window after capacity returns.

Observed pressure flags in **12/72 runs**, and failed foreground-admission attempts in **0/72 runs**. A moving or zero ceiling alone is not proof of feedback pressure. The pressure/control records identify which runs actually exercise the feedback input; endpoint benefit must still be assessed separately.

Pressure splits by fault condition: **F0 12/36; F1 0/36**. No faulted run exhibits a control-entry pressure flag; this suite therefore does not demonstrate recovery under observed foreground-admission pressure or a recovery gain caused by pressure feedback.

## Pressure and memory diagnostics

`audited-bindings.csv` uses corrected measurement names. `sticky_flag_after_attempt_observations` (the frozen raw table's `pressure_admission_attempts`) counts attempts ending while the worker flag is still true, including inherited flags until control clears them; it is not the number of new pressure triggers. `pressure_worker_rank_windows` counts the flag read at control entry (TP1 here). Native quota event fields distinguish pressure decreases, nonpressure ceiling decreases, and growth. `all_hot_release_abort_bytes` includes normal retirement/replacement and is not exclusively pressure-caused reclaim. Ordinary admission timestamps are measured; their wait is submit-to-successful-reservation, not the entire invocation latency.

HBM/DRAM byte-time was independently integrated from recorded physical-ledger transitions and exactly matches all72 core summaries. Peak replica bytes and integral costs are retained, including partial/canceled transactions. Quota is a budget, not occupancy. MECHANISM_ENDPOINTS.json retains all72 runs' exact pressure-flag control/admission snapshots and native quota events, including empty sets. At a zero ceiling the pressure branch can reset stability while quota is already zero: this is not a measured nonzero multiplicative decrease.

| Variant | Runs with pressure flags /12 | Runs with admission waits /12 | Native pressure quota decreases | Fixed target regrowth events |
|---|---:|---:|---:|---:|
| none | 0 | 0 | 0 | 0 |
| dram | 0 | 0 | 0 | 0 |
| fixed32 | 0 | 0 | 0 | 4 |
| fixed128 | 4 | 0 | 0 | 8 |
| fixed4096 | 4 | 0 | 0 | 340 |
| adaptive | 4 | 0 | 2 | 0 |

Timing check, margin0-dma0/adaptive: F0 pressure control times [11.3] s, target Workflow finish 7.671430958 s; F1 failure 6.540857293 s and target finish 7.730960340 s. These are separate runs, not a combined event chain.

Timing check, margin32-dma0/adaptive: F0 pressure control times [11.3] s, target Workflow finish 7.671430958 s; F1 failure 6.540857293 s and target finish 7.730960340 s. These are separate runs, not a combined event chain.

## Paired workflow endpoints

Contrast = (variant F1 - variant F0) - (DRAM F1 - DRAM F0), same Workflow ID. Negative is better. Target and all-four-workflow sums are separate. All zero and adverse cells remain. Healthy cost is mean F0 WCT minus Restart's same-condition mean F0 WCT. Ordinary FCFS competition remains; recovery improvement is not a WCT guarantee.

Adaptive versus fixed128/fixed4096 has exactly equal Workflow endpoints in 24/24 comparisons (six conditions, both F0/F1, two comparators). This is a retained null difference, not evidence of adaptive superiority.

| Condition | Variant | Target contrast vs DRAM (s) | Cohort sum contrast vs DRAM (s) | Worse/better/equal Workflows | Healthy mean cost vs Restart (s) |
|---|---|---:|---:|---|---:|
| margin0-dma0 | none | 1.741337030 | 0.864579681 | 1/2/1 | 0.000000000 |
| margin0-dma0 | dram | 0.000000000 | 0.000000000 | 0/0/4 | 0.000000000 |
| margin0-dma0 | fixed32 | 0.000000000 | 0.000000000 | 0/0/4 | 0.000000000 |
| margin0-dma0 | fixed128 | -0.001443871 | -0.001443871 | 0/1/3 | 0.000000000 |
| margin0-dma0 | fixed4096 | -0.001443871 | -0.001443871 | 0/1/3 | 0.000000000 |
| margin0-dma0 | adaptive | -0.001443871 | -0.001443871 | 0/1/3 | 0.000000000 |
| margin0-dma0.005 | none | 1.741413298 | 0.847269225 | 1/2/1 | 0.000000000 |
| margin0-dma0.005 | dram | 0.000000000 | 0.000000000 | 0/0/4 | 0.028839776 |
| margin0-dma0.005 | fixed32 | 0.000000000 | 0.000000000 | 0/0/4 | 0.028839776 |
| margin0-dma0.005 | fixed128 | -0.001443871 | -0.001443871 | 0/1/3 | 0.028839776 |
| margin0-dma0.005 | fixed4096 | -0.001443871 | -0.001443871 | 0/1/3 | 0.028839776 |
| margin0-dma0.005 | adaptive | -0.001443871 | -0.001443871 | 0/1/3 | 0.028839776 |
| margin32-dma0 | none | 1.741337030 | 0.864579681 | 1/2/1 | 0.000000000 |
| margin32-dma0 | dram | 0.000000000 | 0.000000000 | 0/0/4 | 0.000000000 |
| margin32-dma0 | fixed32 | 0.000000000 | 0.000000000 | 0/0/4 | 0.000000000 |
| margin32-dma0 | fixed128 | -0.001443871 | -0.001443871 | 0/1/3 | 0.000000000 |
| margin32-dma0 | fixed4096 | -0.001443871 | -0.001443871 | 0/1/3 | 0.000000000 |
| margin32-dma0 | adaptive | -0.001443871 | -0.001443871 | 0/1/3 | 0.000000000 |
| margin32-dma0.005 | none | 1.741413298 | 0.847269225 | 1/2/1 | 0.000000000 |
| margin32-dma0.005 | dram | 0.000000000 | 0.000000000 | 0/0/4 | 0.028839776 |
| margin32-dma0.005 | fixed32 | 0.000000000 | 0.000000000 | 0/0/4 | 0.028839776 |
| margin32-dma0.005 | fixed128 | -0.001443871 | -0.001443871 | 0/1/3 | 0.028839776 |
| margin32-dma0.005 | fixed4096 | -0.001443871 | -0.001443871 | 0/1/3 | 0.028839776 |
| margin32-dma0.005 | adaptive | -0.001443871 | -0.001443871 | 0/1/3 | 0.028839776 |
| margin128-dma0 | none | 1.741337030 | 0.864579681 | 1/2/1 | 0.000000000 |
| margin128-dma0 | dram | 0.000000000 | 0.000000000 | 0/0/4 | 0.000000000 |
| margin128-dma0 | fixed32 | 0.000000000 | 0.000000000 | 0/0/4 | 0.000000000 |
| margin128-dma0 | fixed128 | -0.001443871 | -0.001443871 | 0/1/3 | 0.000000000 |
| margin128-dma0 | fixed4096 | -0.001443871 | -0.001443871 | 0/1/3 | 0.000000000 |
| margin128-dma0 | adaptive | -0.001443871 | -0.001443871 | 0/1/3 | 0.000000000 |
| margin128-dma0.005 | none | 1.741413298 | 0.847269225 | 1/2/1 | 0.000000000 |
| margin128-dma0.005 | dram | 0.000000000 | 0.000000000 | 0/0/4 | 0.028839776 |
| margin128-dma0.005 | fixed32 | 0.000000000 | 0.000000000 | 0/0/4 | 0.028839776 |
| margin128-dma0.005 | fixed128 | -0.001443871 | -0.001443871 | 0/1/3 | 0.028839776 |
| margin128-dma0.005 | fixed4096 | -0.001443871 | -0.001443871 | 0/1/3 | 0.028839776 |
| margin128-dma0.005 | adaptive | -0.001443871 | -0.001443871 | 0/1/3 | 0.028839776 |

## Reproducibility and validity

Restart exactly matches original sensitivity-v2 request timestamps, Workflow endpoints and fault identity in 12/12 controls. RESTART_CONTROL.json retains any mismatch rather than rejecting it. Failure wall/worker/co-victim differences across variants remain in the endpoint CSV; only logical target/progress is fixed by construction.

The one extra observer-transparency validation uses fixed4096, margin0, DMA0.005, F1. Base and observed runtimes have byte-identical summaries and decompressed events/flows; the flow record is nonempty. It is a validation control, not a 73rd experiment. The independent audit rechecks actual files and all bindings, not merely its COMPLETE marker.

The original frozen runner's existing-validation reuse gate was incomplete. RUNNER_INTERFACE_REPAIR.json records the live-only interface repair without overwriting the numerical source snapshot or rerunning formal samples. Use the live run_quota_pressure_campaign.py launcher, which verifies the existing validation before re-executing frozen sources. Direct old-snapshot replay must pass this independent audit before reused validation is accepted.

Use audit_quota_pressure_campaign.py --out CAMPAIGN for this stdlib-only audit/report. It launches no DES. The single fault and four dependent Workflows, resource margins and uncalibrated DMA factors are paired conditions, not independent population samples; no CI or physical calibration claim is made. Each Agent has one invocation; this suite adds no evidence about idle histories or repeated invocations. The trained walltime target is simulator submission-to-Agent-completion time. These results do not establish a production controller guarantee or a numerical native-attention recovery implementation.
