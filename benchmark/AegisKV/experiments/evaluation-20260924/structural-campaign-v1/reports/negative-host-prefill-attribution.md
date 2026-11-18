# Shared-host Prefill adverse result: matched seed 7

The three-seed aggregate is not a single-run causal example. DRAM minus no-backup WCT is **+111.100319927 s** at seed 7, **−100.829089012 s** at seed 19, and **−2.025350630 s** at seed 41; their mean is +2.748626762 s. Only seed 7 is adverse. At that seed, admitted recovery service becomes faster, while total recovery to the first new token becomes slower.

Inputs, failure Agent/call/token and F0 target WCT match. Both policies fail wf0000/left, invocation 1, at logical token 10,778 of 19,136, wall time 512.971105006 s, taking workers 0 and 1 down. The same co-victim is wf0000/right invocation 1. All times below are observed simulator records, in seconds.

| Agent/call | None submit | DRAM submit | None finish | DRAM finish | Change in call latency |
|---|---:|---:|---:|---:|---:|
| wf0000/root/0 | 0.000000000 | 0.000000000 | 3.812445845 | 3.812445845 | +0.000000000 |
| wf0000/left/0 | 3.812445845 | 3.812445845 | 207.014568443 | 207.014568443 | +0.000000000 |
| wf0000/left/1 | 207.014568443 | 207.014568443 | 630.414386055 | 634.189895566 | +3.775509511 |
| wf0000/right/0 | 3.812445845 | 3.812445845 | 109.639466536 | 109.639466536 | +0.000000000 |
| wf0000/right/1 | 109.639466536 | 109.639466536 | 521.788305102 | 526.628075133 | +4.839770031 |
| wf0000/join/0 | 630.414386055 | 634.189895566 | 1066.023836274 | 1177.124156201 | +107.324810416 |

Left recovery has a directly recorded decomposition: queue 8.816200096 → 13.655970127 s; admitted service 1.126923476 → 0.062662956 s; fixed detection 0.001 s. Thus total recovery is 9.944123572 → 13.719633083 s, **+3.775509511 s**. The no-backup retry runs on worker 2; the DRAM retry runs on worker 3. The right co-victim makes the same worker change and finishes +4.839770031 s later.

**The gating parent remains wf0000/left under both policies.** Join submits exactly when left finishes: 630.414386055 → 634.189895566 s, +3.775509511 s. Join stays on worker 3; its submit-to-finish latency rises 435.609450219 → 542.934260635 s, **+107.324810416 s**. These two observed terms sum exactly to the workflow completion increase of **111.100319927 s**.

Ordinary requests have submit and finish timestamps but no recorded admission or queue timestamp. Therefore the 107.324810416 s is an observed **join call latency increase**, not a measured queue increase. Equal call tokens/model and zero configured compute/DMA slowdown make unchanged standalone join computation plausible, but labeling all this extra latency as queueing would be an inference. The stored worker-completion sequences and retry route changes are descriptive supporting evidence; routing-score or controlled rerouting counterfactuals were not logged.

This correction preserves the aggregate statement that mean recovery queue/service decrease while mean WCT worsens, but does not imply that total recovery decreases in the concrete adverse seed. The JSON retains all six target-workflow calls, both failure records through the matched check, detailed recovery timestamps, observed worker completion sequences, and source hashes.
