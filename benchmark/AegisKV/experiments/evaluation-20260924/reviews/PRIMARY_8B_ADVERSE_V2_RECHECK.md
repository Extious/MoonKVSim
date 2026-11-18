# Corrected v2 retains the high-load 8B routing adverse case

The original `Qwen3-8B-load0.9-*-F1-1` adverse outcome **still exists** under the
corrected frozen runtime. The independent artifact checker executed no simulation.
Evidence: `PRIMARY_8B_ADVERSE_V2_RECHECK.json`; checker:
`check_corrected_primary_adverse.py --campaign .../formal-core-v2-corrected --out ...`.

Aegis versus DRAM has exactly the original cross-policy differences:

- Target Workflow: **−1.099886 ms**.
- Sum of all62 Workflow WCTs: **+3.402435834 s**.
- One collateral Workflow, `8f0c326505148464`: **+3.411234922 s**.
- Eight Workflows, including the target, improve by1.099886 ms each;53 are equal.
- The two own-policy healthy Workflow records are identical, so these are also
  the cross-policy differences in paired ΔWCT.

The fault still targets `4ca77c9fca665fdd/6dae310bff90ff1b`, invocation0, at
35.020635564 s and logical token5433, with CP5376 and57 replay tokens. Both lose
worker0 on host0 under a worker failure; host DRAM remains alive. The active
co-victim sets and queued-history recovery sets are empty in both cases. The
fresh queued `9543466daff141b6/final` is displaced; it is neither an active
co-victim nor a `history_restores` entry.

Retry admission remains35.918420766 s, comprising1 ms detection and896.785202 ms
queueing. Corrected recovery service is167.701610 ms for DRAM and166.601724 ms for
Aegis. Each decreases by17.041 µs relative to its own v1 result; their difference
remains1.099886 ms.

The collateral root still finishes and submits its five children at
**116.107340965 s**. The preexisting worker1 request
`7c6edfe35e844a5d/889e15bbdc2b6055` finishes at:

| Policy | Completion (s) | Relative to fork submission |
|---|---:|---:|
| DRAM | 116.107468863 | 0.127898 ms later |
| Aegis | 116.106368977 | 0.971988 ms earlier |

These are each17.041 µs earlier than v1, retaining the crossing of the fork
submission boundary. From request intervals, the outstanding busy-plus-queued
counts on workers1–7 are3,4,4,5,4,5,5 for DRAM and2,4,4,5,4,5,5 for Aegis.
The existing submit events give the exact tie-break order and confirm zero local
prefix affinity. Replaying only the frozen routing rule against these observed
counts yields child workers1,1,2,3,5 versus1,1,1,2,3, respectively, exactly matching
all five recorded assignments.

The join starts at127.696761963 s for DRAM and131.107996885 s for Aegis; both join
invocations take1.135066020 s. Its release difference therefore exactly explains
the collateral Workflow difference. This reconstruction is supported by events;
it does not infer an unrecorded ordinary-request admission time or partition its
latency into queueing versus service. The current FCFS routing model supports
this specific outcome, not an equivalent production continuous-batching effect.

The old report and data remain unchanged. This new report binds the corrected
source and four corrected summaries separately; no old result was relabeled.
