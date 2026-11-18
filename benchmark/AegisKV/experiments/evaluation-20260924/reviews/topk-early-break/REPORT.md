# Isolated Top-K early-break evaluation

The two-line early break is exact for the simulator's finite count domain.
No live policy or frozen campaign source was changed.

Once a descending candidate fails the strict hysteresis threshold, `chosen`
remains unchanged. Its weakest member and threshold therefore remain unchanged,
and every later candidate has an equal or smaller count. No later candidate can
enter. Existing tie ordering, incumbent retention, invalid-ID filtering and
returned tuple order are preserved. The optimization reduces the post-sort scan
from up to B*K key evaluations to at most K replacements plus the first rejected
candidate; it does not avoid sorting the B candidates.

190,356 exhaustive finite-count combinations and 20,000 seeded randomized cases
matched the original tuple exactly. Inputs cover zero/missing counts, ties,
negative finite values, subnormals, large magnitudes, strict epsilon boundaries,
all incumbent subsets through five blocks, duplicate/out-of-range incumbents,
K=0, K>B, and layers with unrelated counts. An additional 1,920 infinity cases
also match. Negative/infinite counts are broader than production needs.

Unrestricted equivalence is false for NaN: counts [1, NaN, 2], K=1, incumbent [0]
give original (2,) and prototype (0,). NaN destroys the assumed total order.
The runtime accumulates nonnegative finite query counts and applies finite beta;
no NaN count provider exists. A public function promising arbitrary NaN behavior
would need validation or a fallback rather than this unconditional early break.

The supplied profile has 4.136 seconds cumulative runtime, 1.015 seconds in
`top_blocks` (24.5%), 1,991 Top-K calls, and 2,071,520 rank-key calls. The observed
microbenchmark below is descriptive timing on a shared CPU, with alternating
original/prototype order and five batches. It is not an end-to-end campaign
speedup. Even removing all Top-K cost from that particular profile would cap
end-to-end speedup near 1.325x if every other cost remained constant.

| Blocks | K | Pattern | Original median µs | Prototype median µs | Speedup |
| ---: | ---: | --- | ---: | ---: | ---: |
| 128 | 4 | all_tied | 131.80 | 19.97 | 6.60x |
| 128 | 4 | stable_hot | 139.19 | 19.62 | 7.09x |
| 128 | 4 | stale_incumbents | 145.06 | 31.90 | 4.55x |
| 128 | 16 | all_tied | 281.25 | 25.42 | 11.06x |
| 128 | 16 | stable_hot | 292.10 | 34.00 | 8.59x |
| 128 | 16 | stale_incumbents | 328.00 | 60.86 | 5.39x |
| 512 | 4 | all_tied | 482.89 | 57.73 | 8.36x |
| 512 | 4 | stable_hot | 447.52 | 54.05 | 8.28x |
| 512 | 4 | stale_incumbents | 464.10 | 57.65 | 8.05x |
| 512 | 16 | all_tied | 1048.48 | 74.32 | 14.11x |
| 512 | 16 | stable_hot | 1062.04 | 67.07 | 15.83x |
| 512 | 16 | stale_incumbents | 1211.71 | 93.51 | 12.96x |
| 2048 | 4 | all_tied | 1931.44 | 283.67 | 6.81x |
| 2048 | 4 | stable_hot | 1883.78 | 226.87 | 8.30x |
| 2048 | 4 | stale_incumbents | 1849.39 | 231.38 | 7.99x |
| 2048 | 16 | all_tied | 4114.68 | 270.09 | 15.23x |
| 2048 | 16 | stable_hot | 4256.52 | 250.52 | 16.99x |
| 2048 | 16 | stale_incumbents | 4443.03 | 275.61 | 16.12x |

## Later optimization candidates (not implemented)

* `_rebalance_inner` sorts unchanged `candidates` and `hot_candidates` twice.
  Reuse each sorted list within that single call. Do not suppress actual policy
  events or cache across changes to slack/checkpoint/available capacity.
* Retired checkpoints accumulate in `self.checkpoints`; several rebalance and
  invariant passes scan the historical list. Pruning only fully retired,
  zero-frontier, zero-reader, zero-pending, zero-HBM objects could bound this by
  live objects, after proving no diagnostic depends on retaining that history.
* Summary-only `_control` still evaluates all `policy_sample` arguments before
  `_record` discards the event. The DRAM/HBM estimates are repeated by `hbm_gain`.
  Avoid discarded calculations or cache local estimates only at the exact same
  state/version. Duration-provider purity is a necessary boundary for that change.
* Flow allocation is the other major hotspot: 3,272 starts and 3,503 full rate
  recomputations; `_recompute_rates` costs 1.301 seconds in this profile. Each
  water-filling round repeatedly scans all flows for each resource. A per-call
  resource-to-flow incidence index could remove redundant membership scans, but
  accumulation order, tie resolution and floating-point clamp behavior must be
  retained and audited exactly.
* Registering a TP/block group in one same-timestamp batch could reduce repeated
  rate recomputation/rescheduling, because no bytes transfer between zero-time
  registrations. This changes intermediate journal events and needs a separate
  transaction/rollback and deterministic-ID review; it is not a drop-in policy
  optimization and was deliberately not implemented here.

Artifacts: `policy_original.py`, `policy_prototype.py`, `policy.patch`,
`check_and_benchmark.py`, `RESULTS.json`, and the original supplied pstats.
