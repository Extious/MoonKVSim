> **Historical record — superseded for the revised paper.** This file describes
> the September 5 legacy-model campaign. Its results are excluded from the
> Mooncake-aligned manuscript. See `MOONCAKE_ALIGNMENT.md`, `COMPLETION_REPORT.md`
> and `data/aligned-statistics.json` for the revised study.

# Sensitivity and service-model result audit

Checked against the final accepted V3/auditfix evidence on 2026-09-05.
All results are simulated and uncalibrated. No cases were selected by effect direction.

## Sensitivity

Accepted manifest: `runs-auditfix/acceptance-sensitivity.json`, relative to
`output/paper-simulation-8b/20260905`. All 70 full measured runs passed central
reconstruction. The audit-only source correction and original plan import are
documented in `AUDITFIX.md`; runtime, timing and policy bytes are unchanged.

Effects below are means of five seed-level percentage gains, positive favoring
AegisKV. Intervals are exploratory Student-t 95%, df=4, without multiplicity
adjustment. Absolute grand means must not be used to reconstruct these ratios.

| F | C | Focus mean gain % [95% interval] | Focus P95 gain % [95% interval] | All-workflow mean gain % [95% interval] |
|---:|---:|---|---|---|
| 1 | 16 | -8.817796 [-62.418974, 44.783381] | -8.817796 [-62.418974, 44.783381] | -0.245999 [-0.793433, 0.301435] |
| 2 | 8 | -10.664109 [-37.175809, 15.847590] | -11.016108 [-40.545515, 18.513300] | 0.411880 [-0.118619, 0.942379] |
| 2 | 16 | -15.936238 [-74.843557, 42.971081] | -13.835135 [-98.353006, 70.682736] | -0.458559 [-1.111749, 0.194631] |
| 2 | 24 | 6.318925 [-7.856135, 20.493986] | 1.266009 [-14.063732, 16.595751] | -0.382337 [-0.782968, 0.018294] |
| 2 | 32 | -4.230142 [-20.047258, 11.586974] | -6.710455 [-29.112939, 15.692028] | -0.084110 [-1.032024, 0.863805] |
| 4 | 16 | -0.151430 [-26.164304, 25.861444] | 15.773820 [0.410465, 31.137175] | -0.068125 [-1.048449, 0.912199] |
| 8 | 16 | 5.520995 [-4.820193, 15.862183] | -0.738833 [-43.805278, 42.327613] | 0.657359 [-0.116101, 1.430818] |

All seven focus-mean and all-workflow-mean intervals cross zero. The F4/C16
focus P95 interval excludes zero, but its four-workflow nearest-rank P95 is
the maximum. The manuscript retains this result with its small-cohort and
multiple-comparison limits, and makes no monotonicity or population-tail claim.

Controller diagnostics: F2/C8 to F2/C32 pressure frequency rises from 3.416576%
to 4.883686%; mean quota changes from 33.34368% to 28.35106%, nonmonotonically.
At C16, the quota means range from 29.14970% to 30.12394% across failure counts.
The event-level AIMD validity is a separate central-audit result.

Figure 6 keeps the fixed five-lowest-focus-gain ranking. Its worst row is
seed 4, F4/C16, workflow `9079b63f36e57692`: 14.08 s Store-only versus
43.38 s AegisKV, -207.99% gain. Cost-effect scatter points are associations
across different interventions, not a causal cost curve or Pareto frontier.

## Service composition

Accepted manifest: `runs-v3/acceptance-timing-robustness.json`. The 60 complete
runs use five fixed logical focus requests, all three service models, both
policies and each policy/model own F0 controls. These focus requests are not
the primary compatibility-conditioned foci.

| Beta | Focus penalty % [95% interval] | Whole-workload mean penalty seconds [95% interval] |
|---:|---|---|
| 0.0 | 4.250216 [-77.188834, 85.689266] | 0.089753 [-0.155439, 0.334945] |
| 0.5 | -6.764692 [-47.123427, 33.594042] | 0.031714 [-0.305333, 0.368760] |
| 1.0 | 14.079575 [-25.911436, 54.070586] | -0.038616 [-0.376261, 0.299030] |

Negative penalties favor AegisKV. Focus normalization uses each seed/model
Store-only F0 focus WCT before averaging. Every displayed interval crosses
zero; sign changes do not establish equivalence or physical latency bounds.

## Cross-check and source-to-claim map

`remaining-statistics-crosscheck.json` independently recomputes 405 retained
seed summaries and conservative Student-t endpoints without calling the
production statistics helpers. It validates arithmetic from accepted seed
rows; the central acceptance separately reconstructs full raw executions.

- Sensitivity and controller paragraphs: `sections/results-sensitivity.tex`.
- Cost associations and deterministic adverse case: `sections/results-ablation.tex`.
- Service-model effect and interpretation: `sections/results-timing.tex`.
- Abstract/conclusion: primary null comparison, added traffic, conditional LRU
  finding and model limits, supported here and by `PRIMARY_RESULT_AUDIT.md`
  and `ABLATION_RESULT_AUDIT.md`.

The final plot layout change leaves all numerical chart data identical to
the precompact figures. Only the Figure 6 legend-description string changes.
`plot-layout-data-check.json` binds the equality check to current sidecars.
