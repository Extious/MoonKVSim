# Corrected primary O1/DMA numbers and historical comparison

PASS: both version-bound audits cover all 180 primary and 126 sensitivity runs; their exported CSV hashes were rechecked. No simulation executed.

## Healthy DRAM versus All-DRAM

| Workload | DRAM fallback observations | Checkpoint-only saving | All transferred backup saving |
|---|---:|---:|---:|
| Qwen3-8B-load0.3 | 21088 | 10.301952% | 10.214462% |
| Qwen3-8B-load0.65 | 103476 | 5.768235% | 5.696166% |
| Qwen3-8B-load0.9 | 376685 | -0.070625% | -0.094946% |
| Qwen3-32B-load0.3 | 20487 | 10.905324% | 10.814489% |
| Qwen3-32B-load0.65 | 89327 | 8.070520% | 7.977394% |
| Qwen3-32B-load0.9 | 307099 | 1.175975% | 1.158762% |

The summary counter sums fallback workflows over rebalance evaluations. It has no exported total-evaluation denominator and is not a percentage, a unique-event count, or a continuous-time share. All-DRAM bypasses the tolerance threshold while retaining Slack-derived ranking and finite capacity. All transferred backup includes completed checkpoint/hot copies and already transferred bytes from canceled copies. Negative savings remain visible.

## Logged AegisKV F1 control windows

- `Qwen3-8B-load0.65-aegiskv-F1-2`: 3122 / 5586 unfinished workflow/control-window observations (55.889724%). All 13888 recorded Agent Slack values independently reconstruct exactly. Causes: `{'prediction_minus_age_nonpositive': 3122}`.
- `Qwen3-32B-load0.65-aegiskv-F1-2`: 3605 / 6518 unfinished workflow/control-window observations (55.308377%). All 16212 recorded Agent Slack values independently reconstruct exactly. Causes: `{'prediction_minus_age_nonpositive': 3605}`.

These fractions apply only to the two logged AegisKV failure conditions at load 0.65, not healthy DRAM or other load cells. Workflow/window observations are not independent samples. Prediction age includes queue residence since submission; zero Slack can also be legitimate critical-path or guard clipping.

## Changes from historical v1

- `healthy_dram_comparisons`: 0 / 6 records changed.
- `detailed_fallback`: 0 / 2 records changed.
- `dma_scenarios`: 12 / 12 records changed.

The DMA incremental fault-advantage changes are [8.952] microseconds per matched objective. Healthy cost fields do not change. Full-precision changes, including all eight nonzero-slowdown break-even adjustments, remain in `V1_V2_COMPARISON.json`; no negative or infeasible results are removed.

Full workflow exceptions, including positive and negative All-DRAM versus DRAM differences, remain in `V1_V2_COMPARISON.json` and the audit's same-ID CSV. Equal cohort means do not imply equal workflow outcomes.

| Workflow | Fault index | All-DRAM minus DRAM (ms) | Corrected minus old DRAM WCT (µs) | Corrected minus old All-DRAM WCT (µs) |
|---|---:|---:|---:|---:|
| 3118a657689d83a5 | 4 | -4113.432720 | +0.000000 | +0.000000 |
| d88a046051e878a4 | 4 | +4113.432720 | -10.486000 | -10.486000 |

For DMA, use separate target-only and cohort-total objectives: H is healthy policy cost over Restart; D is the difference in each policy's F1-minus-own-F0 increment. Only the hypothetical binary mixture of this exact F1 and its F0 has advantage pD-H. Infeasible p*>1 is retained; this is not an empirical failure rate. The corrected auxiliary numeric sheet retains the healthy slowdown cost alongside recovery increments.
