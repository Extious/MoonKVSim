# Candidate numeric and causal reconciliation — historical v1

This is a read-only audit of the old frozen primary/sensitivity simulations.
It does not convert them into results for the later recovery-domain correction.
The reusable script reads all 180 primary and 126 sensitivity summaries,
validates job/config/COMPLETE/profile/prior/workload bindings, and exports raw
same-ID rows. Its detailed fallback reconstruction imports no runtime code.

**Fallback counts are numerically correct, but the denominators differ.** The
four quoted healthy DRAM counts are exactly 21,088 / 376,685 for 8B at loads
0.3 / 0.9 and 20,487 / 307,099 for 32B. The runtime adds the number of fallback
workflows on every `_rebalance` call. These repeated observations have no
recorded denominator of all rebalance/workflow observations in the summary;
they are neither unique fallback events nor elapsed-time percentages.

The approximately 56% claim is corroborated for its actual detailed trajectory:
8B, load 0.65, **AegisKV F1-2**, not healthy DRAM. It is 3,122 / 5,586 =
55.889724% of distinct active-workflow/control-window observations. The
corresponding 32B trajectory is 3,605 / 6,518 = 55.308377%. We reconstructed
every recorded Agent Slack exactly (13,888 and 16,212 comparisons) from the
captured submissions/prediction publications, original priors/DAG, and request
completion records. All fallback samples have `prediction - age <= 0`; none
require TTL expiry. The age includes time since submission, including queueing;
the causal predictor estimates profile-based service work. This is not a
prediction-accuracy benchmark, nor an exact continuous-time fallback integral.
Zero Slack alone is not a fallback indicator because critical paths and guard
clipping also produce zero Slack.

**The quoted backup percentages use completed checkpoint bytes only.** They
recompute to 10.301952% / -0.070625% for 8B at loads 0.3 / 0.9 and 10.905324% /
1.175975% for 32B, explaining the Candidate's rounding. With canceled-copy
bytes already transferred also included, the same figures become 10.214462% /
-0.094946% and 10.814489% / 1.158762%. The CSVs preserve both definitions and
the middle-load conditions. A traffic claim should use completed checkpoint +
hot + canceled-transferred bytes; a completed-checkpoint-only claim must name
that narrower metric.

Healthy DRAM and All-DRAM have equal per-workflow WCT in all six cells. Their
F1 per-workflow WCT is not universally identical: for 32B/load 0.9/fault 4,
All-DRAM minus DRAM is -4.113432720 s on `3118a657689d83a5` and +4.113432720 s
on target `d88a046051e878a4`. These cancel in the cohort mean. All-DRAM changes
the tolerance threshold while retaining Slack-derived E ordering and finite
capacity; it is not the zero-Slack control.

**DMA healthy overhead is real within the configured model.** The healthy
four-workflow mean rises from 8.398206670 s to 8.677666978 s at slowdown 0.05
and 8.957127187 s at 0.1, for both DRAM and AegisKV. The increases are about
3.33% and 6.66%. Maximum WCT rises from 19.354031920 s to 19.968400114 s and
20.582768102 s. These are explicit event-start interference assumptions,
not physical or calibrated serving overhead.

The Candidate juxtaposes about 1.74 s of **target-only incremental fault
advantage** with 2.24 s of **four-workflow healthy cost**. Those objectives
cannot be divided to produce a break-even frequency. For a consistent
four-workflow sum-WCT objective, AegisKV has:

| Configured slowdown | Healthy extra H | Incremental fault advantage D | H / D |
|---:|---:|---:|---:|
| 0.05 | 1.117841231 s | 0.731108859 s | 1.528966880 |
| 0.1 | 2.235682069 s | 1.496744969 s | 1.493696064 |

For a hypothetical mixture of no failure and **this exact single fixed
failure**, expected net advantage is `p * D - H`. Both thresholds exceed 1,
so this mixture has no feasible break-even probability for cohort sum WCT.
Target-only thresholds are instead 0.070337801 and 0.140614070, using
target-only healthy costs and target-only fault advantages throughout. Neither
is an observed failure rate or a prediction for multiple faults or other fault
identities. Negative absolute F1 cohort advantages are retained in the CSV.

**Equal checkpoint frontiers do not prove equal WCT by construction.** Transfer
readiness, contention, foreground interference and subsequent routing can all
affect completion; the 32B opposite-sign pair above demonstrates why a cohort
mean can hide such effects. The 32-run zero-Slack null WCT result remains an
observed null under its fixed conditions, not a general implication of a
shared target checkpoint frontier.

The script is parameterized for later directories. Its current outputs remain
historical v1; after corrected campaigns complete, generate a new audit in a
new output directory and compare versions without adding statistical samples.
