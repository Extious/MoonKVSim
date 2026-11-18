> **Historical record — superseded for the revised paper.** This file describes
> the September 5 legacy-model campaign. Its results are excluded from the
> Mooncake-aligned manuscript. See `MOONCAKE_ALIGNMENT.md`, `COMPLETION_REPORT.md`
> and `data/aligned-statistics.json` for the revised study.

# Primary result-to-manuscript audit

Checked 2026-09-05 after V3 primary acceptance completed all eight gates.
This is simulated, uncalibrated evidence. All remaining studies and the final scoped
submission audit are now complete; see `COMPLETION_REPORT.md`.

## Bound inputs

- Acceptance: `output/paper-simulation-8b/20260905/runs-v3/acceptance-primary.json`,
  SHA-256 `60d054294d8bce50d70843154be97dad45944e6808fd10168bebaa8de52eb90d`.
  The unique attempt is VALID and authorized for numerical aggregation.
- Primary aggregate: `runs-v3/primary-campaign.json`, relative to that same
  dated output root. Its SHA-256 was checked against acceptance before use.
- Complete-batch supplement: `runs-v3/primary-makespan-statistics.json`,
  SHA-256 `a2a91b7a545be40cde6b962c5a4730cb4702798ebf3de18d971eb8cd6dbfc4ee`.
  Its generator reconstructs all 1,304 span completions and 160 workflow WCTs
  for each of the 20 executions, with raw hashes bound to acceptance gate 5.
- Workload: the frozen 160-task manifest and JSONL recorded in `REPRODUCE.md`.

## Recomputed comparisons

All differences below are AegisKV minus Store-only. The failure-penalty
difference subtracts each policy's own F0 control. Intervals are two-sided
Student-t intervals over five seed estimates, df=4. They are exploratory and
not adjusted for multiple comparisons.

| Endpoint | Mean difference (s) | 95% interval (s) |
|---|---:|---:|
| F1 all-workflow mean WCT | -0.048459 | [-0.239654, 0.142735] |
| F1 within-seed P95 WCT | -0.094889 | [-4.830837, 4.641059] |
| F1 within-seed maximum WCT | -1.734430 | [-16.124231, 12.655372] |
| Focus failure-penalty difference | 8.129748 | [-5.115997, 21.375493] |
| All-workflow mean failure-penalty difference | 0.088401 | [-0.218289, 0.395091] |
| F1 complete-batch makespan | 1.022101 | [-0.870632, 2.914835] |
| Complete-batch failure-penalty difference | 0.994335 | [-1.467718, 3.456388] |

The relative F1 makespan difference is a mean of five paired percentages:
0.297410%, with interval [-0.251826%, 0.846647%]. It is not a ratio of
grand-average makespans.

Every one of the 800 F1 task differences was recomputed from the two WCT
maps and checked against the stored difference vector. Counts are 328 faster,
156 tied, and 316 slower. They repeat 160 distinct tasks. The extreme
differences are -57.650470224 s (seed 1, workflow `98ced84a1a9df028`) and
+46.340270522 s (seed 0, workflow `db12f9be559698b0`).

Mean absolute F1 WCTs, averaging the five within-seed cohort means:

| Cohort | Store-only (s) | AegisKV (s) |
|---|---:|---:|
| All 160 | 33.836374 | 33.787914 |
| Focus | 30.502437 | 34.570705 |
| Descriptive impacted union | 41.261511 | 42.737779 |
| 159 non-focus workflows | 33.857342 | 33.782991 |

The union contains 4, 6, 3, 3, and 4 workflows in seeds 0--4; it is defined
from both realized victim sets and is a post-treatment descriptive population.

## Recovery propagation

| Seed | Equal recovered prefix (tokens) | Ready-latency difference (s) | Failure-to-request-completion difference (s) | Focus failure-penalty difference (s) |
|---|---:|---:|---:|---:|
| 0 | 32,832 | -0.048556 | -1.722006 | 6.219202 |
| 1 | 32,832 | -1.516667 | -1.509293 | 15.984615 |
| 2 | 41,024 | -0.125822 | 0.047592 | 3.106807 |
| 3 | 41,024 | 1.399539 | -1.108477 | -5.825365 |
| 4 | 32,832 | 0.300654 | 0.297394 | 21.163481 |

The equality of recovered prefixes and recomputed prompt tokens was checked
within every pair. Figure 4 uses disjoint source intervals reconstructed by
gate 5; availability overlap is not added to selected coverage. Ready latency,
request completion after injection, and workflow failure penalty are distinct
endpoints with distinct time origins. The stored direct-mechanism class is not
used as a substitute for checking those endpoints separately.

The manuscript therefore makes no consistent overall-benefit claim, no
extra-prefix-coverage claim for these five cases, and no isolated causal claim
about the Peer-first/Store-first selector.
