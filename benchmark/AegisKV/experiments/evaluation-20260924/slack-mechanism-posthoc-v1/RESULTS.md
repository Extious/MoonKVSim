# Post-hoc constructed Slack mechanism diagnostic

All ten frozen experimental runs and five F1/F0 workflow pairs completed. Two extra uninstrumented executions validate observation transparency and are excluded from the experimental sample count. The independent audit verifies frozen sources/inputs, whole-result bindings, capacity, and all ten DRAM byte-time integrals and per-host peaks from observer ledgers. Restart F1 has byte-identical summaries/events but empty flow logs. The additional tight-DAG-DRAM F1 control has byte-identical summaries, 1,387 event records and 158 nonempty flow records (61,240 decompressed bytes). These two controls establish equality for their fixed inputs, not all possible workloads; neither observed formal run was replaced or repeated.

| DRAM budget | Variant | CP at fault | F0 WCT (s) | F1 WCT (s) | Paired delta (ms) |
|---:|---|---:|---:|---:|---:|
| 1.25 GiB | dag | 1280 | 99.155361841 | 99.179407105 | 24.045264 |
| 1.25 GiB | zero | 0 | 99.155361841 | 99.290155564 | 134.793723 |
| 4 GiB | dag | 1280 | 99.155361841 | 99.179407105 | 24.045264 |
| 4 GiB | zero | 1280 | 99.155361841 | 99.179407105 | 24.045264 |
| 1.25 GiB | restart | 0 | 99.155361841 | 99.290155564 | 134.793723 |

At 1.25 GiB, DAG Slack retains the critical branch's 1,280-token checkpoint; zero Slack retains the expensive branch's 8,448-token checkpoint and loses critical protection. The workflow penalty differs by **110.748459 ms**. At 4 GiB both modes protect critical and have the same penalty; Restart matches tight zero Slack. All healthy WCTs are 99.155361841 s. These are one fixed constructed instance, not a confidence interval or production workload estimate.

The exact failure boundary matches across all five failed conditions: 6.255890594 s, critical invocation 0, logical token 1,536, worker 0, and no collateral victim. Both branches started at 0.226705019 s on workers 0/1 and use worker 2 (host 1) as their peer. Their computed frontiers are 1,536/8,608. Raw guarded Slack is 0/80 s; modeled reconstruction costs are 133.793720/851.408365 ms. DAG exposure therefore excludes the expensive noncritical branch, whereas zero Slack orders it before critical.

This is an observed retirement, not merely failure to admit. In tight zero Slack at 1.028336003 s, critical's existing CP1024 is removed when expensive reaches 8,192 computed tokens. Expensive's CP7936 plus pending append consumes 1,208,177,280 B; retaining critical's 151,008,768 B too would exceed the 1,342,177,280 B host budget. RETIREMENT_WITNESS.json preserves both sides of this transition. At the fault, expensive's complete CP8448 occupies 1,245,822,336 B and leaves 96,354,944 B, insufficient for critical's committed CP1280 (188,760,960 B). The DAG variant instead holds that critical checkpoint on the same peer.

Both variants retry critical on worker 2 with exactly zero recorded retry queue; detection is 1 ms. Admitted recovery service is 34.703782 ms with CP1280 versus 145.452241 ms without a checkpoint. Critical remains the join's gating parent, and the join's invocation latency is unchanged. Thus the matched WCT difference has a recorded protection/recovery/dependency chain, without inferring an ordinary request queue from latency.

resource-results.csv retains all ten checkpoint/cancellation bytes, modeled DRAM byte-time and peaks. The initial 1.125 GiB proposal was corrected before any simulation because the pinned model has 36 layers and metadata pushes even CP8192 over that budget; the pre-execution protocol records the correction. No outcome-based tuning or rerun occurred.

This diagnostic was designed after the 32-run capacity/zero-Slack study produced equal WCTs. It establishes a constructed mechanism operating region with manual role priors, HBM disabled, fixed logical token 1,536 (not the primary 80% rule), and zero modeled DMA interference. It neither supersedes that null result nor validates natural Agent workloads, semantic prediction accuracy, general effect size, or physical hardware overhead.

Version-scope correction: `RECOVERY_DOMAIN_ERRATUM.md` records a subsequently diagnosed checkpoint-recovery selector-domain error. The recovery-service and WCT values above are historical frozen-model results, not evidence for repaired semantics. The protection/retirement snapshots and accounting remain historical observations; matched corrected executions are required before carrying numerical claims into a repaired implementation. This appended note changes no raw result, source snapshot, seal or experimental sample count.
