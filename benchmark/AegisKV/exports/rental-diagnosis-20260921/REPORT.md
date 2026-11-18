# Rental counterexample: diagnosis and bounded mechanism changes

2026-09-21. User asked to diagnose and repair the negative result instead of rejecting rental outright. No published data or manuscript is modified. All calculations below are deterministic analytical simulations, not physical runs or full patent reproduction.

## Fixed comparison contract

The preserved original uses 8 equal-byte slots, 24 objects, 512 candidate opportunities, movement cost 0.1, hysteresis 0.2, sinusoidal current values, and a separate scored next-use stream. The baseline source function is extracted with AST and compared at every step: miss cost, movement cost, migrations, scalar replacement checks and committed rent match exactly for both original policies. The initial arbitrary keys are deliberately preserved.

The scored request is revealed after the placement decision; no future-use information enters any candidate choice. Actual hits can renew in a designated variant. Scored misses remain transiently served and do not automatically admit an object, matching the original experiment. This event model must not be mistaken for the complete Agent request/checkpoint lifecycle.

## Original counterexample

Direct miss/movement: 452.158616/10.800000. Original rent: 495.786869/10.600000. Rent saves 0.2 movement-cost units but pays 43.628253 more miss-cost units.

The original rental trajectory rejects 104 candidate opportunities although another resident at that same snapshot would pass the current-value improvement threshold. It also accepts 57 replacements whose victim has higher current value than another resident. These are diagnostic counts, not an additive causal attribution of the 43.43 gap: future state and miss outcomes depend on earlier choices. A current-value-improving move need not improve future demand cost.

## Mechanism variants and all base-case results

| Policy | Miss | Movement | Total | Moves | Replacement checks | Key-value refreshes |
|---|---:|---:|---:|---:|---:|---:|
| Direct value | 452.16 | 10.80 | 462.96 | 108 | 396 | 0 |
| Original rent | 495.79 | 10.60 | 506.39 | 106 | 396 | 0 |
| Rent + scored-hit renewal | 502.47 | 10.20 | 512.67 | 102 | 379 | 0 |
| Rent + two victims | 474.98 | 10.70 | 485.68 | 107 | 771 | 0 |
| Rent + both changes | 471.88 | 10.40 | 482.28 | 104 | 727 | 0 |
| Rent + current-value refresh | 467.16 | 10.70 | 477.86 | 107 | 387 | 4088 |
| Rent + current-value refresh + two victims | 456.36 | 10.40 | 466.76 | 104 | 747 | 4088 |

1. Scored-hit renewal: after an observed hit, renew that resident. It worsens this base case; stronger renewal alone is not the repair.
2. Two victims: inspect the two lowest credit keys and choose the feasible candidate with the larger current replacement gain. Rent advances only when a plan is accepted; rejected trials do not change it.
3. Current-value refresh: adjust H by G_new - G_old, leaving H - G unchanged between real renewals. Thus the original grant origin and rent paid since it are preserved. This is a new dynamic-value variant, not the archived patent rule. It eagerly updates all resident keys to validate semantics; a scalable implementation remains to be designed.

The current-value refresh plus two-victim variant costs 466.755787, shrinking the original direct/rent gap by 91.26%. Its remaining base-case cost is 0.82% above direct value. The comparison does not establish controller efficiency: this variant adds 4,088 key updates and has 747 scalar replacement checks versus 396, while scans/sorts and common value production are outside that counter.

## Fixed sensitivity grid

Phases {0,32,96,192}, drift periods {9,18,36}, and capacities {4,8,12} give 36 constructed cases. The full grid, thresholds, candidate/use formulas and variant settings were fixed before seeing their outcomes; no threshold or shortlist-size search was used. The current-value variant was added after the initial renewal/shortlist results and checked on the same grid. These are sensitivity cases, not independent experimental repetitions or a held-out workload validation.

| Variant | Mean total delta vs direct | Wins / losses vs direct | Wins / losses vs original rent |
|---|---:|---:|---:|
| Direct value | 0.000 | 0 / 0 | 36 / 0 |
| Original rent | 28.543 | 0 / 36 | 0 / 0 |
| Rent + scored-hit renewal | 33.948 | 0 / 36 | 8 / 28 |
| Rent + two victims | 14.544 | 2 / 34 | 31 / 5 |
| Rent + both changes | 15.733 | 2 / 34 | 32 / 4 |
| Rent + current-value refresh | 8.168 | 9 / 27 | 31 / 5 |
| Rent + current-value refresh + two victims | 3.276 | 9 / 27 | 36 / 0 |

The refresh-plus-two variant improves over original rent in all 36 cases, but beats direct value in only 9 and loses in 27. This supports continued repair and identifies stale value / narrow screening as actionable mechanisms; it does not justify declaring rental superior.

## What remains to solve

- Align causal renewal with actual new Agent rounds, prefix reuse and deduplicated per-Agent shares; this toy has none of those.
- Define normal-reuse and fault recovery value on legal prefix/checkpoint groups, including shared execution interference; avoid placing whole-request value on the newest block.
- Use tier-conditional value against surviving backing and legal Peer L/K bundles; add bounded shared storage and safe asynchronous demotion.
- Implement versioned/lazy value maintenance with a bounded stale-candidate escape path; compare policies under matched work budgets and measure actual control overhead. Do not reset all rent origins whenever a profile changes.
- Keep this negative case as a regression alongside request persistence, tool-gap, shared-role-prefix, phase-change and capacity-pressure cases. Preserve ties and regressions.

Reproduction: `.venv/bin/python benchmark/AegisKV/experiments/scripts/eurosys27/diagnose_rental.py`. Source hash and generator hash are in RESULTS.json; base-events.csv contains all per-step records; sensitivity.csv includes every case and variant.
