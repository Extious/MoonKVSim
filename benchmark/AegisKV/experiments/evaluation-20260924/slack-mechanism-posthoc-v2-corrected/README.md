# Corrected post-hoc Slack mechanism replay

All ten prespecified conditions completed under the same corrected frozen source
as the other v2 auxiliary groups. `MATCHED_INPUTS.json` verifies exact old/new
job conditions, profile bytes and decoded workload, including assigned priors.
This is a matched replacement of v1, not ten additional independent samples.

`AUDIT.json` binds the ten runs. `OBSERVATION_TRANSPARENCY.json` and
`NONEMPTY_OBSERVATION_TRANSPARENCY.json` verify the two fixed base-versus-observer
cases under the new snapshot: Restart F1 and tight 1.25 GiB DAG DRAM F1. Their
summary bytes and decompressed event/flow bytes match; the second case has
nonempty checkpoint/recovery flows. Two validation executions add zero
experimental samples. Neither proof extends to all possible workloads.

Independent numeric, source, fault-state, capacity/metadata and causal-chain
review is in `../reviews/POSTHOC_SLACK_V2_INDEPENDENT_REVIEW.md` and `.json`.
The tight DAG/zero-Slack penalty difference remains 110.819080 ms; the ample
4 GiB case remains a null. All F0 results are identical to v1. The three
checkpoint-backed F1 conditions each improve by 0.070621 ms after correction.
Raw paired results and all adverse outcomes remain in `PAIRED_RESULTS.json`.

This intentionally constructed, post-hoc case demonstrates a finite-budget
mechanism under fixed assigned priors, not real predictor accuracy or natural
workflow population performance. All ten summaries have empty history-restores
records; this single-invocation workload does not exercise the new queued
cross-invocation-history recovery path. Timing remains profile-informed and
uncalibrated. No old output or paper was modified.
