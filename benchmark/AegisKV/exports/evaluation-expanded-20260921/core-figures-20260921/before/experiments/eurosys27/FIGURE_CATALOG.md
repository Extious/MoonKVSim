# Evaluation 图像目录

33 张独立单栏图。以下按正文顺序列出；最终图号由 LaTeX 生成。数据、PDF、SVG、PNG 使用同一描述性文件名。

## 1. eval-workflow-outcomes

证据：**analytical**；图型：`cdf`；x：Failure penalty (s)；y：Scenario fraction。

Single-failure penalties over 36 declared configurations of state size, residual-branch slack, and storage bandwidth. The same configuration is used for every policy. The CDF weights configurations equally; it is not a distribution of measured workflows. The allocation oracle searches the same whole-group candidate family.

![eval-workflow-outcomes](../../paper/figures/preview/eval-workflow-outcomes.png)

CSV: `../data/eurosys27/expanded/eval-workflow-outcomes.csv`。

## 2. eval-paired-benefit

证据：**analytical**；图型：`cdf`；x：LRU minus AegisKV penalty (s)；y：Scenario fraction。

Paired single-failure benefit over LRU. Positive values favor workflow value; zero denotes a tie. Of 36 analytical configurations, 17 improve and 19 tie. This paired view preserves correspondence that separate outcome CDFs cannot show.

![eval-paired-benefit](../../paper/figures/preview/eval-paired-benefit.png)

CSV: `../data/eurosys27/expanded/eval-paired-benefit.csv`。

## 3. eval-branch-exposure

证据：**analytical**；图型：`barh`；x：Time (s)；y：。

Where the base-case benefit originates. A0--A3 have join slack 0, 2, 7, and 11\,s. Bars compare that slack with actual modeled restoration completion after the common fault. Speeding up the largest history A3 has little workflow value here; delaying A0 directly extends the join.

![eval-branch-exposure](../../paper/figures/preview/eval-branch-exposure.png)

CSV: `../data/eurosys27/expanded/eval-branch-exposure.csv`。

## 4. eval-recovery-attribution

证据：**analytical**；图型：`stackh`；x：Failure penalty (s)；y：。

Ordered counterfactual decomposition of workflow delay at fixed placement. Starting with free resources, restore the detection floor, read costs, network, H2D, and replay in that order. Increments telescope to total workflow penalty. They include interactions assigned by this order, rather than sums of overlapping operation durations.

![eval-recovery-attribution](../../paper/figures/preview/eval-recovery-attribution.png)

CSV: `../data/eurosys27/expanded/eval-recovery-attribution.csv`。

## 5. eval-storage-traffic

证据：**analytical**；图型：`barh`；x：Storage read volume (GiB)；y：。

Total capacity-tier traffic for the same single fault. Workflow value reads 28\,GiB versus LRU's 24\,GiB, despite reducing the workflow penalty. Faster workflow completion is therefore not evidence of lower aggregate I/O. The 16\,GiB DRAM constraint is an upper bound; indivisible candidates can leave space unused.

![eval-storage-traffic](../../paper/figures/preview/eval-storage-traffic.png)

CSV: `../data/eurosys27/expanded/eval-storage-traffic.csv`。

## 6. eval-burst-interference

证据：**analytical**；图型：`line`；x：Interrupted workflows；y：Mean failure penalty (s)。

FIFO recovery-pool stress model: a simultaneous burst of identical interrupted workflows shares one two-target pool. The pool is reserved until each workflow's last restore completes. Queue delay is added to the join penalty. This deliberately restrictive policy exposes externalities that an isolated-fault comparison misses.

![eval-burst-interference](../../paper/figures/preview/eval-burst-interference.png)

CSV: `../data/eurosys27/expanded/eval-burst-interference.csv`。

## 7. eval-background-backlog

证据：**analytical**；图型：`line`；x：Time after recovery burst (s)；y：I/O backlog (GiB)。

Fluid I/O backlog after the fault, with normal traffic consuming 70\% of the 4\,GiB/s storage reader. The initial backlog equals recovery bytes and drains at residual bandwidth. This conservation-of-work example measures I/O backlog, not background workflow WCT or TTFT.

![eval-background-backlog](../../paper/figures/preview/eval-background-backlog.png)

CSV: `../data/eurosys27/expanded/eval-background-backlog.csv`。

## 8. eval-logical-fault-phase

证据：**analytical**；图型：`line`；x：Matched token progress (%)；y：Failure penalty (s)。

Matched logical progress with growing checkpoint state. Each branch's bytes scale with progress relative to the 80\% base case; remaining durations, rates, and the absolute DRAM budget stay fixed. This controlled sweep isolates state growth and does not represent a measured distribution of fault phases.

![eval-logical-fault-phase](../../paper/figures/preview/eval-logical-fault-phase.png)

CSV: `../data/eurosys27/expanded/eval-logical-fault-phase.csv`。

## 9. eval-checkpoint-lag

证据：**analytical**；图型：`line`；x：Commit lag (s)；y：Failure penalty (s)。

Actual commit lag can dominate nominal checkpoint spacing. The analytical sweep adds tail reconstruction implied by commit lag, with the same transport resources. Physical replacement must use the last committed frontier at the fault, including failed or backlogged writes; a trigger interval is not a durability guarantee.

![eval-checkpoint-lag](../../paper/figures/preview/eval-checkpoint-lag.png)

CSV: `../data/eurosys27/expanded/eval-checkpoint-lag.csv`。

## 10. eval-trace-outages

证据：**observed trace**；图型：`cdf`；x：Outage duration (min)；y：Interval fraction。

Observed outage-duration distribution after the stated LANL compute-node filtering and interval merge: 21,738 intervals across 22 systems. Durations come from recorded start/end times, not from the serving model. The source is a pinned redistribution with the original-archive verification limitation stated in the text.

![eval-trace-outages](../../paper/figures/preview/eval-trace-outages.png)

CSV: `../data/eurosys27/expanded/eval-trace-outages.csv`。

## 11. eval-trace-bursts

证据：**observed trace**；图型：`cdf`；x：Nodes per recorded start；y：Start-group fraction。

Observed counts of distinct nodes whose outage intervals start at the same recorded minute within a system. There are 19,561 start groups, including 568 multi-node groups; the largest contains 45 nodes. Timestamp coarsening and simultaneous outages are not distinguishable at this resolution.

![eval-trace-bursts](../../paper/figures/preview/eval-trace-bursts.png)

CSV: `../data/eurosys27/expanded/eval-trace-bursts.csv`。

## 12. eval-modern-trace-labels

证据：**observed trace**；图型：`cdf`；x：Fault-labeled nodes per job；y：Training job fraction。

Modern GPU-trace audit: fault-labeled nodes per job in the 98-job Reflex alert dataset. Job labels identify 144 faulty node/job entries, but 108 have no matching alert on that node. These labels do not provide a time of failure or repair; the curve is not an outage-frequency estimate.

![eval-modern-trace-labels](../../paper/figures/preview/eval-modern-trace-labels.png)

CSV: `../data/eurosys27/expanded/eval-modern-trace-labels.csv`。

## 13. eval-trace-penalty

证据：**trace-driven model**；图型：`cdf`；x：Modeled penalty (s)；y：Episode fraction。

LANL-start-time-driven FIFO recovery model, one assumed four-branch workflow per cleaned node outage, preserving per-system start times at their original rate. Curves show 21,738 conditional recovery episodes. The observed input is the outage calendar; recovery durations and workflow penalties are modeled.

![eval-trace-penalty](../../paper/figures/preview/eval-trace-penalty.png)

CSV: `../data/eurosys27/expanded/eval-trace-penalty.csv`。

## 14. eval-trace-queue

证据：**trace-driven model**；图型：`barh`；x：Mean modeled delay (s)；y：。

Separating intrinsic join delay from queue wait in the trace-driven model. Workflow value reduces intrinsic delay but lengthens pool occupancy, increasing queue delay. The bars use all replayed episodes with equal episode weights and make no claim about healthy-workload arrivals.

![eval-trace-queue](../../paper/figures/preview/eval-trace-queue.png)

CSV: `../data/eurosys27/expanded/eval-trace-queue.csv`。

## 15. eval-trace-system-benefit

证据：**trace-driven model**；图型：`barv`；x：System ID；y：Mean benefit (s)。

Per-system paired mean benefit under the original recorded start times, computed as LRU minus workflow-value mean penalty. All 22 system IDs are shown. Positive values favor workflow value; negative values are retained. Each system is shown separately instead of treating its many correlated node events as independent experimental repetitions.

![eval-trace-system-benefit](../../paper/figures/preview/eval-trace-system-benefit.png)

CSV: `../data/eurosys27/expanded/eval-trace-system-benefit.csv`。

## 16. eval-trace-burst-control

证据：**trace-driven model**；图型：`barh`；x：Mean failure penalty (s)；y：。

Timing controls for the same episodes: evenly spaced starts preserve each system's count and span; within-minute spreading distributes tied starts over 59\,s in node order. The latter probes timestamp resolution. These are declared transformations, not recovered physical timestamps or new observed traces.

![eval-trace-burst-control](../../paper/figures/preview/eval-trace-burst-control.png)

CSV: `../data/eurosys27/expanded/eval-trace-burst-control.csv`。

## 17. eval-trace-time-stress

证据：**trace-driven model**；图型：`line`；x：Timestamp compression；y：Mean failure penalty (s)。

Timestamp compression sensitivity. Factor 1 preserves recorded spacing; larger factors compress within-system spacing while leaving modeled service times unchanged. All factors retain every cleaned event. Accelerated points are explicit load stress tests and must not be reported as the original failure rate.

![eval-trace-time-stress](../../paper/figures/preview/eval-trace-time-stress.png)

CSV: `../data/eurosys27/expanded/eval-trace-time-stress.csv`。

## 18. eval-ablation-fault

证据：**analytical**；图型：`barh`；x：Mean delay (s)；y：。

Static value ablations over 12 size/slack scenarios at 4\,GiB/s storage bandwidth, a subset of the 36-case outcome grid. Removing DAG information, removing normal-use value, or using an allocation oracle changes only the stated decision rule. This panel evaluates value selection, not the full online system.

![eval-ablation-fault](../../paper/figures/preview/eval-ablation-fault.png)

CSV: `../data/eurosys27/expanded/eval-ablation-fault.csv`。

## 19. eval-ablation-reuse

证据：**analytical**；图型：`barh`；x：Mean delay (s)；y：。

Normal next-use cost for the same 12 static placements and scenario weights as the failure ablation. This companion panel prevents recovery gains from concealing a normal-reuse regression. No-reuse removes the value term, not the ability to perform normal cache lookups.

![eval-ablation-reuse](../../paper/figures/preview/eval-ablation-reuse.png)

CSV: `../data/eurosys27/expanded/eval-ablation-reuse.csv`。

## 20. eval-common-fault

证据：**analytical**；图型：`line`；x：Branches retained in DRAM；y：Delay (s)。

Common-failure complementarity in a constructed join. The exact joint outcome is compared with an additive isolated-request estimate as more required branches are retained. A bounded controller must revalue complete plans; per-request slack deductions cannot generally be added.

![eval-common-fault](../../paper/figures/preview/eval-common-fault.png)

CSV: `../data/eurosys27/expanded/eval-common-fault.csv`。

## 21. eval-layer-factorial

证据：**analytical**；图型：`line`；x：Selected KV fraction (%)；y：Recovery time (ms)。

Equal-budget $2\!\times\!2$ layer-placement/scheduling experiment on eight synthetic layer payloads. Early/late policies retain two payloads; serial/pipeline schedules use the same selected demand, rates, and two-layer transient workspace. The x-axis changes selected payload density for all policies equally, not attention semantics.

![eval-layer-factorial](../../paper/figures/preview/eval-layer-factorial.png)

CSV: `../data/eurosys27/expanded/eval-layer-factorial.csv`。

## 22. eval-layer-exposure

证据：**analytical**；图型：`stackh`；x：Completion time (ms)；y：。

Layer-model completion decomposed into required compute and exposed waiting. At full demand, each of eight layers computes for 3\,ms. Early versus late DRAM placement ties under serial scheduling (56\,ms), but gives 32 versus 34\,ms with the bounded pipeline. The interaction, rather than independent speedup sums, explains the difference.

![eval-layer-exposure](../../paper/figures/preview/eval-layer-exposure.png)

CSV: `../data/eurosys27/expanded/eval-layer-exposure.csv`。

## 23. eval-sparse-misses

证据：**analytical**；图型：`line`；x：Correct prefetches (%)；y：Recovery time (ms)。

Sensitivity to constructed prefetch correctness with full required demand held fixed. A wrong prefetch consumes an extra storage read, and the required payload becomes available only after its reveal point. Correctness fraction is an input to this mechanism model, not the measured accuracy of a sparse predictor.

![eval-sparse-misses](../../paper/figures/preview/eval-sparse-misses.png)

CSV: `../data/eurosys27/expanded/eval-sparse-misses.csv`。

## 24. eval-rental-churn

证据：**analytical**；图型：`line`；x：Admission opportunities；y：Accepted migrations。

Accepted migrations on one deterministic 512-opportunity stream with eight resident slots and 24 equal-byte candidates. Direct value and trial rent use the same instantaneous value and migration test; the other variants remove hysteresis or renewal. This additive tier model is isolated from DAG and serving execution.

![eval-rental-churn](../../paper/figures/preview/eval-rental-churn.png)

CSV: `../data/eurosys27/expanded/eval-rental-churn.csv`。

## 25. eval-rental-revaluation

证据：**analytical**；图型：`barh`；x：Count (512 opportunities)；y：。

Exact replacement-plan revaluations on the same stream. Counting operations tests whether screening reduces expensive evaluations; it does not measure CPU milliseconds. Trial rent and direct value both perform 396 revaluations here, so this case provides no screening-cost improvement.

![eval-rental-revaluation](../../paper/figures/preview/eval-rental-revaluation.png)

CSV: `../data/eurosys27/expanded/eval-rental-revaluation.csv`。

## 26. eval-rental-cost

证据：**analytical**；图型：`stackh`；x：Modeled cumulative cost；y：。

Next-use miss cost and migration cost on the same rental stream, in declared abstract delay-cost units. Trial rent makes slightly fewer migrations but incurs greater total cost than direct revaluation. The result is retained as a limitation of the heuristic; fewer migrations alone do not establish a better policy.

![eval-rental-cost](../../paper/figures/preview/eval-rental-cost.png)

CSV: `../data/eurosys27/expanded/eval-rental-cost.csv`。

## 27. eval-capacity-frontier

证据：**analytical**；图型：`line`；x：DRAM budget (GiB)；y：Failure penalty (s)。

Single-failure DRAM-capacity sweep at fixed storage capacity, rates, and logical fault. Value and oracle policies optimize the joint normal-use/failure score; their fault-only penalty need not decrease monotonically. Equal DRAM capacity is required for deployable-policy comparisons.

![eval-capacity-frontier](../../paper/figures/preview/eval-capacity-frontier.png)

CSV: `../data/eurosys27/expanded/eval-capacity-frontier.csv`。

## 28. eval-storage-bottleneck

证据：**analytical**；图型：`line`；x：Storage read rate (GiB/s)；y：Failure penalty (s)。

Storage-rate sensitivity with DRAM, shared-network, and H2D capacities held fixed. Improvements flatten when a different stage becomes limiting. Each curve uses the same workload and physical byte convention; generic rates are assumptions, not SSD device measurements.

![eval-storage-bottleneck](../../paper/figures/preview/eval-storage-bottleneck.png)

CSV: `../data/eurosys27/expanded/eval-storage-bottleneck.csv`。

## 29. eval-prediction-robustness

证据：**analytical**；图型：`line`；x：Duration perturbation (%)；y：Failure penalty (s)。

Signed alternating perturbation of estimated remaining durations, followed by policy decisions and evaluation against true durations. This is policy sensitivity, not predictor accuracy. Adverse points are retained, including the $-25\%$ case where workflow value is worse than LRU.

![eval-prediction-robustness](../../paper/figures/preview/eval-prediction-robustness.png)

CSV: `../data/eurosys27/expanded/eval-prediction-robustness.csv`。

## 30. eval-healthy-io

证据：**analytical**；图型：`line`；x：Backup link utilization (%)；y：Mean I/O response (ms)。

Separate M/D/1 I/O illustration with constant service time: mean I/O response rises with background backup utilization. This queueing calculation neither measures GPU interference nor supplies an end-to-end TTFT or SLO result.

![eval-healthy-io](../../paper/figures/preview/eval-healthy-io.png)

CSV: `../data/eurosys27/expanded/eval-healthy-io.csv`。

## 31. eval-rate-break-even

证据：**analytical**；图型：`line`；x：Fault probability per horizon；y：Net saving (s)。

Net expected saving in an isolated-fault horizon: failure probability times the base-case 2.0083\,s saving, minus an assumed healthy cost. Curves cross zero at different probabilities. These healthy costs and probabilities are sensitivity inputs, not production measurements.

![eval-rate-break-even](../../paper/figures/preview/eval-rate-break-even.png)

CSV: `../data/eurosys27/expanded/eval-rate-break-even.csv`。

## 32. eval-safe-demotion

证据：**analytical**；图型：`step`；x：Time after pressure (s)；y：Bytes (GiB)。

Capacity pressure and safe release. Lowering the target from 24 to 16\,GiB does not free physical DRAM immediately. Copy completion precedes manifest redirection and reader drain; this modeled trace releases the 8\,GiB at 5.5\,s. It demonstrates accounting, not a tested distributed implementation.

![eval-safe-demotion](../../paper/figures/preview/eval-safe-demotion.png)

CSV: `../data/eurosys27/expanded/eval-safe-demotion.csv`。

## 33. eval-controller-scaling

证据：**analytical**；图型：`line`；x：Live DAG segments；y：Decision time (ms)。

Analytical controller work under the explicitly assumed per-node visit cost and bounded episode count. The curve shows an operation-cost projection, not measured scalability. Physical validation must include graph edges, candidate enumeration, profile evaluation, locking, and metadata contention.

![eval-controller-scaling](../../paper/figures/preview/eval-controller-scaling.png)

CSV: `../data/eurosys27/expanded/eval-controller-scaling.csv`。
