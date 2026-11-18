# Finite-capacity Slack ablation

32 frozen runs: DRAM per host 2/4/8/256 GiB, four policy variants and paired F0/F1. The source sensitivity campaign's four full workflows, 52 Agents, profile, priors, arrivals and same-ID 80%-progress fault are copied byte-for-byte. No L/K/guard retuning.

Variants: dram; all_dram; aegiskv; aegiskv_no_slack. The last still reports summary.policy=aegiskv, with the auditable Config.slack_mode=zero. Tracker predictions and asynchronous events remain active; Slack used by protection decisions is zero. All-DRAM is a separate selection baseline and must not be relabeled no-Slack.

Capacities bracket the fixed target checkpoint size (~2.4 GB) and concurrent footprints; they are not chosen by observed benefit. This is one fixed fault intervention with four dependent workflows, not random-failure sampling or real prediction-accuracy evidence. Raw metrics, paired workflow deltas, negatives and binding diagnostics are retained. There is no complete master budget denial counter or independent per-flow audit for these summary-only runs. PLAN/PROTOCOL/PRIORS and sources are snapshotted and sealed.

## Results and reproducible independent audit

All 32 runs and 64 paired workflow rows are complete. `RESULTS.md` and
`variant-cost-results.csv` retain the null WCT contrast and the modeled transfer
cost contrast. `INDEPENDENT_VARIANT_AUDIT.json` binds the summaries and prior
campaign files to the checks. Reproduce this audit without simulating again:

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/audit_capacity_slack_ablation.py \
  --out benchmark/AegisKV/experiments/evaluation-20260924/capacity-slack-ablation-v1
```

The independent audit verifies saved artifact hashes, exact workload/profile/
prior equality, configuration differences, all individual workflow completion
times, intervention activity, and default-DAG equivalence with the preceding
sensitivity snapshot. Its script is an analysis artifact added after execution;
it does not modify the frozen execution snapshot. `slack_mode=zero` affects both
DRAM exposure and HBM gain inputs, so this is not a pure O1-only isolation.
