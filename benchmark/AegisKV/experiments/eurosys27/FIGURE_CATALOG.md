# Evaluation 图像目录

当前正文 **6 张图**、补充 **1 张图**；下面继续保留历史34候选的原说明和数据路径。完整实验计划见 [EXPERIMENT_MATRIX.md](EXPERIMENT_MATRIX.md)，证据选择见 [FIGURE_SELECTION.md](FIGURE_SELECTION.md)。所有图均为已有证据的重新绘制，未新增物理实验。

## 当前正文

### eval-placement-pairs

证据：**historical deterministic analytical model**。历史放置解析模型：展示同配置配对差值与19个零收益；不能作为当前端到端主结论。

Paired LRU-minus-workflow-value failure penalties in 36 declared historical model configurations. Every case uses identical rates, bytes and resources for both policies: 17 improve and 19 tie. This deterministic Peer-disabled whole-checkpoint allocator is not the current online controller.

![eval-placement-pairs](../../exports/evaluation-rework-20260922T170350Z/figures/eval-placement-pairs.png)

[PDF](../../exports/evaluation-rework-20260922T170350Z/figures/eval-placement-pairs.pdf) · [SVG](../../exports/evaluation-rework-20260922T170350Z/figures/eval-placement-pairs.svg) · [CSV](../../exports/evaluation-rework-20260922T170350Z/plot-data/eval-placement-pairs.csv)

### eval-recovery-paths

证据：**physical_worker_microbenchmark**。物理worker微基准：确定重建/复用成本量级，保留真实后端、单一输入流和计时范围。

Measured reconstruction paths on one fixed input stream. Points use three timing repeats for resident HBM and serial DRAM (whiskers: min-max), and one timing for full prefill and DPC shared filesystem. All paths end at the same KV-ready endpoint; this is a worker microbenchmark, not a Peer-policy comparison.

![eval-recovery-paths](../../exports/evaluation-rework-20260922T170350Z/figures/eval-recovery-paths.png)

[PDF](../../exports/evaluation-rework-20260922T170350Z/figures/eval-recovery-paths.pdf) · [SVG](../../exports/evaluation-rework-20260922T170350Z/figures/eval-recovery-paths.svg) · [CSV](../../exports/evaluation-rework-20260922T170350Z/plot-data/eval-recovery-paths.csv)

### eval-rental-diagnostic

证据：**historical constructed additive rental diagnosis**。历史rent负结果与修复：揭示成本/控制工作权衡，不能替代当前lazy lower-tier credit评估。

Preserved rental regression in a deterministic equal-byte model. Direct, original rent and repaired rent cost 462.96, 506.39 and 466.76 abstract units. The repair refreshes current value without refunding paid rent and examines two victims; it still exceeds direct cost and performs more scalar checks. These are neither CPU times nor current-controller results.

![eval-rental-diagnostic](../../exports/evaluation-rework-20260922T170350Z/figures/eval-rental-diagnostic.png)

[PDF](../../exports/evaluation-rework-20260922T170350Z/figures/eval-rental-diagnostic.pdf) · [SVG](../../exports/evaluation-rework-20260922T170350Z/figures/eval-rental-diagnostic.svg) · [CSV](../../exports/evaluation-rework-20260922T170350Z/plot-data/eval-rental-diagnostic.csv)

### eval-tracker-errors

证据：**held-out recorded-trace prediction**。真实记录上的held-out预测误差：展示全部长尾，明确whole-Agent和当前segment-Slack的差距。

Complete held-out absolute-error distributions at the second request: 1,443 completed Subagents from 170 workflows, split into five workflow-disjoint folds. The target is whole-Agent remaining time; all long-tail errors remain visible. This does not validate residual-segment Slack.

![eval-tracker-errors](../../exports/evaluation-rework-20260922T170350Z/figures/eval-tracker-errors.png)

[PDF](../../exports/evaluation-rework-20260922T170350Z/figures/eval-tracker-errors.pdf) · [SVG](../../exports/evaluation-rework-20260922T170350Z/figures/eval-tracker-errors.svg) · [CSV](../../exports/evaluation-rework-20260922T170350Z/plot-data/eval-tracker-errors.csv)

### eval-sparse-demand

证据：**offline causal analysis of native selector captures**。原生选择器历史窗口到未来需求的离线覆盖：等物理预算、三文档和oracle上限，保留弱效应。

Future-demand coverage at K=205 of 512 physical blocks per layer. A ranking from the previous 512 queries predicts the next 64; mandatory blocks count toward the same budget. Open points are three documents; horizontal marks are their means. The historical-frequency baseline is distinct from the current visibility-normalized policy; the oracle knows future demand.

![eval-sparse-demand](../../exports/evaluation-rework-20260922T170350Z/figures/eval-sparse-demand.png)

[PDF](../../exports/evaluation-rework-20260922T170350Z/figures/eval-sparse-demand.pdf) · [SVG](../../exports/evaluation-rework-20260922T170350Z/figures/eval-sparse-demand.svg) · [CSV](../../exports/evaluation-rework-20260922T170350Z/plot-data/eval-sparse-demand.csv)

### eval-trace-tails

证据：**historical trace-driven queue model**。历史trace-driven队列模型：平均收益与p95/p99回归同时可见，不能充当真实服务恢复。

Mean and tail penalties from the historical LANL-start-driven FIFO model (21,738 cleaned intervals in 22 systems). Workflow value reduces the mean but increases p95 and p99 versus LRU. Points are deterministic summaries of modeled episodes, without confidence intervals or physical serving claims.

![eval-trace-tails](../../exports/evaluation-rework-20260922T170350Z/figures/eval-trace-tails.png)

[PDF](../../exports/evaluation-rework-20260922T170350Z/figures/eval-trace-tails.pdf) · [SVG](../../exports/evaluation-rework-20260922T170350Z/figures/eval-trace-tails.svg) · [CSV](../../exports/evaluation-rework-20260922T170350Z/plot-data/eval-trace-tails.csv)

## 当前补充

### eval-sparse-horizon

证据：**offline native-trace horizon sensitivity**。补充预测范围：固定K与排名，展示64到512个future Queries的频率增益衰减。

Supporting horizon sensitivity at the same K=205 quota. Lines show the mean paired coverage gain of historical frequency over recent-first; bands and whiskers are three-document min-max. The fixed ranking uses the previous 512 queries and never sees target selections. Near-zero long-window gains are retained.

![eval-sparse-horizon](../../exports/evaluation-rework-20260922T170350Z/figures/eval-sparse-horizon.png)

[PDF](../../exports/evaluation-rework-20260922T170350Z/figures/eval-sparse-horizon.pdf) · [SVG](../../exports/evaluation-rework-20260922T170350Z/figures/eval-sparse-horizon.svg) · [CSV](../../exports/evaluation-rework-20260922T170350Z/plot-data/eval-sparse-horizon.csv)

完整样本数、统计定义、源数据哈希与限制见 [figure-manifest.json](../../exports/evaluation-rework-20260922T170350Z/figure-manifest.json)。

---

# 历史归档：34 个候选视图

这是旧版8张正文与26张补充选择，现已由上方当前证据集替代。合并消融图复用原有两张消融图的数值，不是新增实验。选择依据见 [FIGURE_SELECTION.md](FIGURE_SELECTION.md)，完整实验设计见 [EXPERIMENT_MATRIX.md](EXPERIMENT_MATRIX.md)。

## 旧版8张选择

### 1. eval-workflow-outcomes

证据：**analytical**；图型：`cdf`；x：Failure penalty (s)；y：Scenario fraction。

Single-failure penalties over 36 declared configurations of state size, residual-branch slack, and storage bandwidth. The same configuration is used for every policy. The CDF weights configurations equally; it is not a distribution of measured workflows. The allocation oracle searches the same whole-group candidate family.

![eval-workflow-outcomes](../../exports/evaluation-expanded-20260921/figures/eval-workflow-outcomes.png)

CSV: `../data/eurosys27/expanded/eval-workflow-outcomes.csv`。

### 2. eval-branch-exposure

证据：**analytical**；图型：`barh`；x：Time (s)；y：。

Where the base-case benefit originates. A0--A3 have join slack 0, 2, 7, and 11\,s. Bars compare that slack with actual modeled restoration completion after the common fault. Speeding up the largest history A3 has little workflow value here; delaying A0 directly extends the join.

![eval-branch-exposure](../../exports/evaluation-expanded-20260921/figures/eval-branch-exposure.png)

CSV: `../data/eurosys27/expanded/eval-branch-exposure.csv`。

### 3. eval-burst-interference

证据：**analytical**；图型：`line`；x：Interrupted workflows；y：Mean failure penalty (s)。

FIFO recovery-pool stress model: a simultaneous burst of identical interrupted workflows shares one two-target pool. The pool is reserved until each workflow's last restore completes. Queue delay is added to the join penalty. This deliberately restrictive policy exposes externalities that an isolated-fault comparison misses.

![eval-burst-interference](../../exports/evaluation-expanded-20260921/figures/eval-burst-interference.png)

CSV: `../data/eurosys27/expanded/eval-burst-interference.csv`。

### 4. eval-trace-penalty

证据：**trace-driven model**；图型：`cdf`；x：Modeled penalty (s)；y：Episode fraction。

LANL-start-time-driven FIFO recovery model, one assumed four-branch workflow per cleaned node outage, preserving per-system start times at their original rate. Curves show 21,738 conditional recovery episodes. The observed input is the outage calendar; recovery durations and workflow penalties are modeled.

![eval-trace-penalty](../../exports/evaluation-expanded-20260921/figures/eval-trace-penalty.png)

CSV: `../data/eurosys27/expanded/eval-trace-penalty.csv`。

### 5. eval-value-ablation

证据：**analytical**；图型：`barh`；x：Mean delay (s)；y：。

Static value ablations over the same 12 size/slack scenarios at 4\,GiB/s storage bandwidth. Each policy has a failure-penalty bar and a normal next-use-cost bar; these are distinct costs, not additive phases. The six policies use identical weights, capacity, and candidate groups. Keeping both outcomes visible exposes the normal-reuse cost of recovery prioritization. This is a static placement model, not the full online system.

![eval-value-ablation](../../exports/evaluation-expanded-20260921/figures/eval-value-ablation.png)

CSV: `../data/eurosys27/expanded/eval-value-ablation.csv`。

### 6. eval-layer-factorial

证据：**analytical**；图型：`line`；x：Selected KV fraction (%)；y：Recovery time (ms)。

Equal-budget $2\!\times\!2$ layer-placement/scheduling experiment on eight synthetic layer payloads. Early/late policies retain two payloads; serial/pipeline schedules use the same selected demand, rates, and two-layer transient workspace. The x-axis changes selected payload density for all policies equally, not attention semantics.

![eval-layer-factorial](../../exports/evaluation-expanded-20260921/figures/eval-layer-factorial.png)

CSV: `../data/eurosys27/expanded/eval-layer-factorial.csv`。

### 7. eval-rental-cost

证据：**analytical**；图型：`stackh`；x：Modeled cumulative cost；y：。

Next-use miss cost and migration cost on the same rental stream, in declared abstract delay-cost units. Trial rent makes slightly fewer migrations but incurs greater total cost than direct revaluation. The result is retained as a limitation of the heuristic; fewer migrations alone do not establish a better policy.

![eval-rental-cost](../../exports/evaluation-expanded-20260921/figures/eval-rental-cost.png)

CSV: `../data/eurosys27/expanded/eval-rental-cost.csv`。

### 8. eval-capacity-frontier

证据：**analytical**；图型：`line`；x：DRAM budget (GiB)；y：Failure penalty (s)。

Single-failure DRAM-capacity sweep at fixed storage capacity, rates, and logical fault. Value and oracle policies optimize the joint normal-use/failure score; their fault-only penalty need not decrease monotonically. Equal DRAM capacity is required for deployable-policy comparisons.

![eval-capacity-frontier](../../exports/evaluation-expanded-20260921/figures/eval-capacity-frontier.png)

CSV: `../data/eurosys27/expanded/eval-capacity-frontier.csv`。

## 补充与备用图

以下图像保留数据与绘图配置，但不在正文中逐张展开。

### 9. eval-storage-bottleneck

证据：**analytical**；图型：`line`；x：Storage read rate (GiB/s)；y：Failure penalty (s)。

Storage-rate sensitivity with DRAM, shared-network, and H2D capacities held fixed. Improvements flatten when a different stage becomes limiting. Each curve uses the same workload and physical byte convention; generic rates are assumptions, not SSD device measurements.

![eval-storage-bottleneck](../../exports/evaluation-expanded-20260921/figures/eval-storage-bottleneck.png)

CSV: `../data/eurosys27/expanded/eval-storage-bottleneck.csv`。

### 10. eval-checkpoint-lag

证据：**analytical**；图型：`line`；x：Commit lag (s)；y：Failure penalty (s)。

Actual commit lag can dominate nominal checkpoint spacing. The analytical sweep adds tail reconstruction implied by commit lag, with the same transport resources. Physical replacement must use the last committed frontier at the fault, including failed or backlogged writes; a trigger interval is not a durability guarantee.

![eval-checkpoint-lag](../../exports/evaluation-expanded-20260921/figures/eval-checkpoint-lag.png)

CSV: `../data/eurosys27/expanded/eval-checkpoint-lag.csv`。

### 11. eval-prediction-robustness

证据：**analytical**；图型：`line`；x：Duration perturbation (%)；y：Failure penalty (s)。

Signed alternating perturbation of estimated remaining durations, followed by policy decisions and evaluation against true durations. This is policy sensitivity, not predictor accuracy. Adverse points are retained, including the $-25\%$ case where workflow value is worse than LRU.

![eval-prediction-robustness](../../exports/evaluation-expanded-20260921/figures/eval-prediction-robustness.png)

CSV: `../data/eurosys27/expanded/eval-prediction-robustness.csv`。

### 12. eval-healthy-io

证据：**analytical**；图型：`line`；x：Backup link utilization (%)；y：Mean I/O response (ms)。

Separate M/D/1 I/O illustration with constant service time: mean I/O response rises with background backup utilization. This queueing calculation neither measures GPU interference nor supplies an end-to-end TTFT or SLO result.

![eval-healthy-io](../../exports/evaluation-expanded-20260921/figures/eval-healthy-io.png)

CSV: `../data/eurosys27/expanded/eval-healthy-io.csv`。

### 13. eval-safe-demotion

证据：**analytical**；图型：`step`；x：Time after pressure (s)；y：Bytes (GiB)。

Capacity pressure and safe release. Lowering the target from 24 to 16\,GiB does not free physical DRAM immediately. Copy completion precedes manifest redirection and reader drain; this modeled trace releases the 8\,GiB at 5.5\,s. It demonstrates accounting, not a tested distributed implementation.

![eval-safe-demotion](../../exports/evaluation-expanded-20260921/figures/eval-safe-demotion.png)

CSV: `../data/eurosys27/expanded/eval-safe-demotion.csv`。

### 14. eval-controller-scaling

证据：**analytical**；图型：`line`；x：Live DAG segments；y：Decision time (ms)。

Analytical controller work under the explicitly assumed per-node visit cost and bounded episode count. The curve shows an operation-cost projection, not measured scalability. Physical validation must include graph edges, candidate enumeration, profile evaluation, locking, and metadata contention.

![eval-controller-scaling](../../exports/evaluation-expanded-20260921/figures/eval-controller-scaling.png)

CSV: `../data/eurosys27/expanded/eval-controller-scaling.csv`。

### 15. eval-common-fault

证据：**analytical**；图型：`line`；x：Branches retained in DRAM；y：Delay (s)。

Common-failure complementarity in a constructed join. The exact joint outcome is compared with an additive isolated-request estimate as more required branches are retained. A bounded controller must revalue complete plans; per-request slack deductions cannot generally be added.

![eval-common-fault](../../exports/evaluation-expanded-20260921/figures/eval-common-fault.png)

CSV: `../data/eurosys27/expanded/eval-common-fault.csv`。

### 16. eval-ablation-fault

证据：**analytical**；图型：`barh`；x：Mean delay (s)；y：。

Static value ablations over 12 size/slack scenarios at 4\,GiB/s storage bandwidth, a subset of the 36-case outcome grid. Removing DAG information, removing normal-use value, or using an allocation oracle changes only the stated decision rule. This panel evaluates value selection, not the full online system.

![eval-ablation-fault](../../exports/evaluation-expanded-20260921/figures/eval-ablation-fault.png)

CSV: `../data/eurosys27/expanded/eval-ablation-fault.csv`。

### 17. eval-ablation-reuse

证据：**analytical**；图型：`barh`；x：Mean delay (s)；y：。

Normal next-use cost for the same 12 static placements and scenario weights as the failure ablation. This companion panel prevents recovery gains from concealing a normal-reuse regression. No-reuse removes the value term, not the ability to perform normal cache lookups.

![eval-ablation-reuse](../../exports/evaluation-expanded-20260921/figures/eval-ablation-reuse.png)

CSV: `../data/eurosys27/expanded/eval-ablation-reuse.csv`。

### 18. eval-paired-benefit

证据：**analytical**；图型：`cdf`；x：LRU minus AegisKV penalty (s)；y：Scenario fraction。

Paired single-failure benefit over LRU. Positive values favor workflow value; zero denotes a tie. Of 36 analytical configurations, 17 improve and 19 tie. This paired view preserves correspondence that separate outcome CDFs cannot show.

![eval-paired-benefit](../../exports/evaluation-expanded-20260921/figures/eval-paired-benefit.png)

CSV: `../data/eurosys27/expanded/eval-paired-benefit.csv`。

### 19. eval-recovery-attribution

证据：**analytical**；图型：`stackh`；x：Failure penalty (s)；y：。

Ordered counterfactual decomposition of workflow delay at fixed placement. Starting with free resources, restore the detection floor, read costs, network, H2D, and replay in that order. Increments telescope to total workflow penalty. They include interactions assigned by this order, rather than sums of overlapping operation durations.

![eval-recovery-attribution](../../exports/evaluation-expanded-20260921/figures/eval-recovery-attribution.png)

CSV: `../data/eurosys27/expanded/eval-recovery-attribution.csv`。

### 20. eval-storage-traffic

证据：**analytical**；图型：`barh`；x：Storage read volume (GiB)；y：。

Total capacity-tier traffic for the same single fault. Workflow value reads 28\,GiB versus LRU's 24\,GiB, despite reducing the workflow penalty. Faster workflow completion is therefore not evidence of lower aggregate I/O. The 16\,GiB DRAM constraint is an upper bound; indivisible candidates can leave space unused.

![eval-storage-traffic](../../exports/evaluation-expanded-20260921/figures/eval-storage-traffic.png)

CSV: `../data/eurosys27/expanded/eval-storage-traffic.csv`。

### 21. eval-background-backlog

证据：**analytical**；图型：`line`；x：Time after recovery burst (s)；y：I/O backlog (GiB)。

Fluid I/O backlog after the fault, with normal traffic consuming 70\% of the 4\,GiB/s storage reader. The initial backlog equals recovery bytes and drains at residual bandwidth. This conservation-of-work example measures I/O backlog, not background workflow WCT or TTFT.

![eval-background-backlog](../../exports/evaluation-expanded-20260921/figures/eval-background-backlog.png)

CSV: `../data/eurosys27/expanded/eval-background-backlog.csv`。

### 22. eval-logical-fault-phase

证据：**analytical**；图型：`line`；x：Matched token progress (%)；y：Failure penalty (s)。

Matched logical progress with growing checkpoint state. Each branch's bytes scale with progress relative to the 80\% base case; remaining durations, rates, and the absolute DRAM budget stay fixed. This controlled sweep isolates state growth and does not represent a measured distribution of fault phases.

![eval-logical-fault-phase](../../exports/evaluation-expanded-20260921/figures/eval-logical-fault-phase.png)

CSV: `../data/eurosys27/expanded/eval-logical-fault-phase.csv`。

### 23. eval-trace-outages

证据：**observed trace**；图型：`cdf`；x：Outage duration (min)；y：Interval fraction。

Observed outage-duration distribution after the stated LANL compute-node filtering and interval merge: 21,738 intervals across 22 systems. Durations come from recorded start/end times, not from the serving model. The source is a pinned redistribution with the original-archive verification limitation stated in the text.

![eval-trace-outages](../../exports/evaluation-expanded-20260921/figures/eval-trace-outages.png)

CSV: `../data/eurosys27/expanded/eval-trace-outages.csv`。

### 24. eval-trace-bursts

证据：**observed trace**；图型：`cdf`；x：Nodes per recorded start；y：Start-group fraction。

Observed counts of distinct nodes whose outage intervals start at the same recorded minute within a system. There are 19,561 start groups, including 568 multi-node groups; the largest contains 45 nodes. Timestamp coarsening and simultaneous outages are not distinguishable at this resolution.

![eval-trace-bursts](../../exports/evaluation-expanded-20260921/figures/eval-trace-bursts.png)

CSV: `../data/eurosys27/expanded/eval-trace-bursts.csv`。

### 25. eval-trace-queue

证据：**trace-driven model**；图型：`barh`；x：Mean modeled delay (s)；y：。

Separating intrinsic join delay from queue wait in the trace-driven model. Workflow value reduces intrinsic delay but lengthens pool occupancy, increasing queue delay. The bars use all replayed episodes with equal episode weights and make no claim about healthy-workload arrivals.

![eval-trace-queue](../../exports/evaluation-expanded-20260921/figures/eval-trace-queue.png)

CSV: `../data/eurosys27/expanded/eval-trace-queue.csv`。

### 26. eval-trace-time-stress

证据：**trace-driven model**；图型：`line`；x：Timestamp compression；y：Mean failure penalty (s)。

Timestamp compression sensitivity. Factor 1 preserves recorded spacing; larger factors compress within-system spacing while leaving modeled service times unchanged. All factors retain every cleaned event. Accelerated points are explicit load stress tests and must not be reported as the original failure rate.

![eval-trace-time-stress](../../exports/evaluation-expanded-20260921/figures/eval-trace-time-stress.png)

CSV: `../data/eurosys27/expanded/eval-trace-time-stress.csv`。

### 27. eval-trace-burst-control

证据：**trace-driven model**；图型：`barh`；x：Mean failure penalty (s)；y：。

Timing controls for the same episodes: evenly spaced starts preserve each system's count and span; within-minute spreading distributes tied starts over 59\,s in node order. The latter probes timestamp resolution. These are declared transformations, not recovered physical timestamps or new observed traces.

![eval-trace-burst-control](../../exports/evaluation-expanded-20260921/figures/eval-trace-burst-control.png)

CSV: `../data/eurosys27/expanded/eval-trace-burst-control.csv`。

### 28. eval-trace-system-benefit

证据：**trace-driven model**；图型：`barv`；x：System ID；y：Mean benefit (s)。

Per-system paired mean benefit under the original recorded start times, computed as LRU minus workflow-value mean penalty. All 22 system IDs are shown. Positive values favor workflow value; negative values are retained. Each system is shown separately instead of treating its many correlated node events as independent experimental repetitions.

![eval-trace-system-benefit](../../exports/evaluation-expanded-20260921/figures/eval-trace-system-benefit.png)

CSV: `../data/eurosys27/expanded/eval-trace-system-benefit.csv`。

### 29. eval-modern-trace-labels

证据：**observed trace**；图型：`cdf`；x：Fault-labeled nodes per job；y：Training job fraction。

Modern GPU-trace audit: fault-labeled nodes per job in the 98-job Reflex alert dataset. Job labels identify 144 faulty node/job entries, but 108 have no matching alert on that node. These labels do not provide a time of failure or repair; the curve is not an outage-frequency estimate.

![eval-modern-trace-labels](../../exports/evaluation-expanded-20260921/figures/eval-modern-trace-labels.png)

CSV: `../data/eurosys27/expanded/eval-modern-trace-labels.csv`。

### 30. eval-sparse-misses

证据：**analytical**；图型：`line`；x：Correct prefetches (%)；y：Recovery time (ms)。

Sensitivity to constructed prefetch correctness with full required demand held fixed. A wrong prefetch consumes an extra storage read, and the required payload becomes available only after its reveal point. Correctness fraction is an input to this mechanism model, not the measured accuracy of a sparse predictor.

![eval-sparse-misses](../../exports/evaluation-expanded-20260921/figures/eval-sparse-misses.png)

CSV: `../data/eurosys27/expanded/eval-sparse-misses.csv`。

### 31. eval-layer-exposure

证据：**analytical**；图型：`stackh`；x：Completion time (ms)；y：。

Layer-model completion decomposed into required compute and exposed waiting. At full demand, each of eight layers computes for 3\,ms. Early versus late DRAM placement ties under serial scheduling (56\,ms), but gives 32 versus 34\,ms with the bounded pipeline. The interaction, rather than independent speedup sums, explains the difference.

![eval-layer-exposure](../../exports/evaluation-expanded-20260921/figures/eval-layer-exposure.png)

CSV: `../data/eurosys27/expanded/eval-layer-exposure.csv`。

### 32. eval-rental-churn

证据：**analytical**；图型：`line`；x：Admission opportunities；y：Accepted migrations。

Accepted migrations on one deterministic 512-opportunity stream with eight resident slots and 24 equal-byte candidates. Direct value and trial rent use the same instantaneous value and migration test; the other variants remove hysteresis or renewal. This additive tier model is isolated from DAG and serving execution.

![eval-rental-churn](../../exports/evaluation-expanded-20260921/figures/eval-rental-churn.png)

CSV: `../data/eurosys27/expanded/eval-rental-churn.csv`。

### 33. eval-rental-revaluation

证据：**analytical**；图型：`barh`；x：Count (512 opportunities)；y：。

Scalar replacement-value checks on the same additive stream, not complete DAG revaluations or CPU measurements. Trial rent and direct value both perform 396 checks here. The historical series name is retained in the source artifact; this count does not establish controller work reduction. This is the preserved historical comparison. The current manuscript proposes revised three-tier renewable credit with a complete-plan check; this figure does not implement that controller.

![eval-rental-revaluation](../../exports/evaluation-expanded-20260921/figures/eval-rental-revaluation.png)

CSV: `../data/eurosys27/expanded/eval-rental-revaluation.csv`。

### 34. eval-rate-break-even

证据：**analytical**；图型：`line`；x：Fault probability per horizon；y：Net saving (s)。

Net expected saving in an isolated-fault horizon: failure probability times the base-case 2.0083\,s saving, minus an assumed healthy cost. Curves cross zero at different probabilities. These healthy costs and probabilities are sensitivity inputs, not production measurements.

![eval-rate-break-even](../../exports/evaluation-expanded-20260921/figures/eval-rate-break-even.png)

CSV: `../data/eurosys27/expanded/eval-rate-break-even.csv`。
