# Corrected auxiliary numbers for the Evaluation draft

All numbers below come from the 126 + 32 corrected conditions; old runs remain historical versions. They are not added repetitions. Timing is AIC-informed and uncalibrated. No paper source was edited.

Source: `checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1`. Detailed bindings and raw precision: `PAPER_NUMBERS_V2.json`.

## H2D and center

| H2D GB/s | DRAM target penalty (ms) | AegisKV target penalty (ms) | DRAM - AegisKV (ms) |
|---:|---:|---:|---:|
| 8 | 283.947137 | 278.171653 | 5.775484 |
| 16 | 135.297881 | 132.410139 | 2.887742 |
| 32 | 60.973253 | 59.529382 | 1.443871 |
| 64 | 24.015869 | 23.300331 | 0.715538 |

Center target penalties: Restart 1.802310283 s; DRAM 0.060973253 s; AegisKV 0.059529382 s. HBM adds 1.443871 ms.

## Capacity / zero Slack

All Current-versus-zero-Slack workflow records equal across four capacities and F0/F1: **True**. This is 32 paired workflow records, not 32 independent samples. Zero Slack affects both DRAM exposure and HBM gain, so this is not O1-only.

| DRAM GiB/host | Current healthy backup GiB | Zero-Slack healthy backup GiB | Reduction |
|---:|---:|---:|---:|
| 2 | 70.292094297 | 73.727164298 | 4.659165% |
| 4 | 91.903213066 | 96.317263305 | 4.582824% |
| 8 | 91.093702507 | 95.507752746 | 4.621667% |
| 256 | 91.093702507 | 95.507752746 | 4.621667% |

Backup includes completed checkpoint + hot-placement + canceled-transferred bytes. In the 0.25/1 GiB sensitivity cases, target checkpoint remains zero; peak host occupancy remains about 98.45%, and both backup policies have Restart penalty 1.802310283 s. HBM cap 0/32 MiB does not improve the target over DRAM. These finite tests do not establish a universal threshold.

## DMA healthy cost and matched-objective break-even

| Slowdown | Policy | Healthy mean WCT s | Mean increase | Target healthy extra s | Target incremental fault advantage s | Target p* | Cohort p* |
|---:|---|---:|---:|---:|---:|---:|---:|
| 0.05 | dram | 8.677666978 | 3.327619% | 0.122636393 | 1.742099716 | 0.070395737 | 1.531973625 |
| 0.05 | aegiskv | 8.677666978 | 3.327619% | 0.122636393 | 1.743543587 | 0.070337440 | 1.528948159 |
| 0.1 | dram | 8.957127187 | 6.655237% | 0.245272745 | 1.742862401 | 0.140729839 | 1.495129434 |
| 0.1 | aegiskv | 8.957127187 | 6.655237% | 0.245272745 | 1.744306272 | 0.140613348 | 1.493687130 |

Restart healthy mean is 8.398206670 s; maximum 19.354031920 s. DRAM/AegisKV maximum is 19.968400114 s at 0.05 and 20.582768102 s at 0.1. The target-only and four-workflow-sum objectives have separate H and D. Under the hypothetical mixture of F0 and this exact F1, advantage is pD-H; cohort p*>1 has no feasible break-even in [0,1]. These are not measured failure rates, nor extrapolations to other or multiple faults. A smaller F1-F0 under slowdown does not mean faster absolute service.

## Controls that do not cross the target decision boundary

- `online_prediction_multiplier`: maximum target-penalty spread across tested levels is 0.000000000 s for every policy; this is a finite null, not predictor accuracy or staleness robustness.
- `prediction_latency_ms_at_TTL100ms`: maximum target-penalty spread across tested levels is 0.000000000 s for every policy; this is a finite null, not predictor accuracy or staleness robustness.
- `tolerance_seconds`: maximum target-penalty spread across tested levels is 0.000000000 s for every policy; this is a finite null, not predictor accuracy or staleness robustness.
- TTL pair: all 52 replies at 200 ms exceed the 100 ms TTL; zero at 0.1 ms. Accepted publication is not valid-for-Slack evidence. No exact timeout count is claimed.
- Detection levels remain 1/10/100 ms. Their exposure and other controls are retained in the complete raw tables.

| Z tokens | Restart penalty s | DRAM penalty s | AegisKV penalty s |
|---:|---:|---:|---:|
| 64 | 17.711292058 | 0.377999237 | 0.376555355 |
| 256 | 1.802310283 | 0.060973253 | 0.059529382 |
| 1024 | 1.802310283 | 0.161889201 | 0.160445429 |

Z=64 also forces at-most-64-token forward chunks, while Z=1024 keeps the 256-token compute chunk. This is a coupled compute/checkpoint intervention. All 31 negative paired collateral outcomes remain in the CSV; one length-selected fixed fault is the independent intervention, not a failure population.

The new 10-point post-hoc audit is separate: tight DAG ΔWCT 23.974643 ms, zero 134.793723 ms (difference 110.819080 ms); 4 GiB remains null. See POSTHOC_SLACK_V2_INDEPENDENT_REVIEW.md for the fault-entry/budget chain and observer checks.

The full corrected primary O1/DMA audit now passes all 180 primary and 126 sensitivity runs. See [primary O1 numbers and historical comparison](o1-dma-corrected-v2-audit/PAPER_O1_NUMBERS_V2.md) for the exact fallback denominators, both traffic definitions, and version changes. The auxiliary numbers above are unchanged by this finalization.
