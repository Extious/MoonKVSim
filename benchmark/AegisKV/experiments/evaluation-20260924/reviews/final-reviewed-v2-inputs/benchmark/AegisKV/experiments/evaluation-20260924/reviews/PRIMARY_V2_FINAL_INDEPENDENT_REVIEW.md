# Corrected primary endpoints and five-group version comparison: final independent review

**PASS.** The independent checker verifies all 180 primary summaries, 150 per-identity endpoint rows and 90 descriptive stratum rows. Across five groups, all 483 old/new pairs are complete and all 159 healthy (F0) full numerical summaries are identical. No simulation was run by this review; no frozen source, original result or paper was changed.

The target is the planned and actual failed Agent/invocation, matched to its unique active recovery. Queued history restoration is kept separate. WCT is independently reconstructed from request submit/finish timestamps, and failure-to-first-new-token from failure/first-new timestamps; detection + retry queue + service sums exactly. The same five identities are S1/N2/S3/N4/S5 (three DAG sinks, two non-sinks), not independent repetitions.

## Co-primary latency table

Each cell is the descriptive mean of five fixed identities. HBM gain = DRAM minus AegisKV, positive better. Full precision and both signs are retained in CSV/JSON; displayed digits do not assert physical accuracy.

| Model | rho | Restart (s) | DRAM (s) | HBM gain (ms) |
|---|---:|---:|---:|---:|
| Qwen3-8B | 0.3 | 0.956403 | 0.488464 | 0.219979 |
| Qwen3-8B | 0.65 | 0.956403 | 0.488464 | 0.219464 |
| Qwen3-8B | 0.9 | 2.694406 | 1.970189 | 0.508370 |
| Qwen3-32B | 0.3 | 1.910054 | 1.607198 | 0.027498 |
| Qwen3-32B | 0.65 | 1.144348 | 0.550953 | 0.027499 |
| Qwen3-32B | 0.9 | 2.221522 | 1.253272 | 0.035886 |

Direct single-column snippet: `coprimary-v2-crosscheck/agent-latency-single-column.tex`. Its actual PDF preview uses 84.7 mm content width and nominal 10 pt text; no overfull boxes or clipping. The final target-WCT figure's actual PDF was rendered and inspected at its 178 x 105 mm size, with 10.3 pt text, all six panels, 150 policy/identity markers, negative outcomes and the S/N legend visible. The tiny HBM differences require the numeric table; they are not visibly resolved by the main figure scale.

## Interpretation and retained adverse outcomes

- DRAM retry-queue share spans 62.221%--90.634% of each cell's mean total, with service 9.316%--37.574%. Aegis shares are 62.249%--90.657% and 9.292%--37.546%. These ranges are over six descriptive cell means, not request maxima, CIs, or population estimates. Detection is 1 ms.
- At 32B/rho=0.3, DRAM minus Restart target Workflow delta is +0.455173414 s for the three sinks but -1.4399009675 s for the two non-sinks. At 8B/rho=0.9 it is -0.4488459627 s for sinks and +0.863419005 s for non-sinks. In that latter non-sink stratum, failure-to-first-new-token is nevertheless 1.1372736035 s shorter. The two endpoints need separate presentation; sink is a structural DAG label, not a critical-path guarantee.
- The 8B/rho=0.9 second identity's routing adverse outcome remains exactly: Aegis target WCT -1.099886 ms versus DRAM, all-62-WF sum +3.402435834 s, one collateral WF +3.411234922 s, eight improving WFs, 53 equal. Existing submit events and request intervals prove a fork-time Router assignment change. No unrecorded ordinary-request admission time is inferred. See `PRIMARY_8B_ADVERSE_V2_RECHECK.md/json`.

## Version differences

| Group | Pairs | Exact healthy summaries | F1 changed WCT | Queued-history rows |
|---|---:|---:|---:|---:|
| formal | 180 | 30 | 84/150 | 0 |
| structural | 135 | 45 | 90/90 | 279 |
| sensitivity | 126 | 63 | 38/63 | 0 |
| capacity | 32 | 16 | 12/16 | 0 |
| posthoc | 10 | 5 | 3/5 | 0 |

All old/new active-recovery Agent sets match. The 279 queued-history rows occur only in the structural group; they are not extra active co-victims. Primary F1 changes affect 84/150 runs and lower each changed run's all-WF WCT sum by at most 0.163840 ms; 66 are exactly unchanged. Structural changes include 17 adverse and 73 improving all-WF sums, range -892.620078413 s to +48.561723047 s; none were dropped. All signed endpoints and source hashes are in `v1-v2-comparison/`.

F0 normalization ignores only bound identity/schema differences: design version, config/workload hashes after verifying semantic config and decompressed workload equality, EOS-model description, and absent versus explicitly empty history_restores. Missing old slack_mode is verified equivalent to dag. Nonempty history_restores are never dropped. The structural comparison covers its declared 135 main jobs; the eight old extra scale jobs are explicitly outside this corrected group's scope.

The new posthoc independent check and both observer transparency cases pass separately (`POSTHOC_SLACK_V2_INDEPENDENT_REVIEW.json`). Its tight-budget DAG versus zero-slack Workflow penalties are 23.974643 versus 134.793723 ms; 4 GiB remains null. This does not replace the prior 32-point null result or turn the posthoc workload into a primary sample.

## Interrupted execution and provenance

The original parent process exited 143 after 177 completed conditions; cause remains undetermined. Only the three missing original 32B/load0.9 Aegis conditions were resumed, using the original source snapshot and separately hashed dependency supplements. This review independently rehashes all 177 earlier markers and summaries unchanged, all archived partial input files, and both resume import reports against frozen/supplement hashes. Archived partial attempts are not additional samples. `INTERRUPTION_RECOVERY.json` retains the execution boundary.

`PRIMARY_V2_FINAL_INDEPENDENT_REVIEW.json` binds the final reports, table, exports and provenance. Resource fields from summary-only runs rely on in-run assertions; this read-only endpoint review is not an independent integration of unavailable flow events. Endpoint results remain FCFS, profile-based simulation evidence, not hardware or production continuous-batching measurements.
