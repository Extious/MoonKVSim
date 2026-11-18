# Finite-capacity Slack ablation

32 frozen runs: DRAM per host 2/4/8/256 GiB, four policy variants and paired F0/F1. The source sensitivity campaign's four full workflows, 52 Agents, profile, priors, arrivals and same-ID 80%-progress fault are copied byte-for-byte. No L/K/guard retuning.

Variants: dram; all_dram; aegiskv; aegiskv_no_slack. The last still reports summary.policy=aegiskv, with the auditable Config.slack_mode=zero. Tracker predictions and asynchronous events remain active; Slack used by protection decisions is zero. All-DRAM is a separate selection baseline and must not be relabeled no-Slack.

Capacities bracket the fixed target checkpoint size (~2.4 GB) and concurrent footprints; they are not chosen by observed benefit. This is one fixed fault intervention with four dependent workflows, not random-failure sampling or real prediction-accuracy evidence. Raw metrics, paired workflow deltas, negatives and binding diagnostics are retained. There is no complete master budget denial counter or independent per-flow audit for these summary-only runs. PLAN/PROTOCOL/PRIORS and sources are snapshotted and sealed.
