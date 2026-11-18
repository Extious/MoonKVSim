#!/usr/bin/env python3
"""Materialize the detailed evaluation in main.tex; preserve other chapters.

This is an authoring snapshot, not part of the data/plot rebuild command.
"""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[3]

CAPTIONS={
'workflow-outcomes':r'''Single-failure penalties over 36 declared configurations of state size, residual-branch slack, and storage bandwidth. The same configuration is used for every policy. The CDF weights configurations equally; it is not a distribution of measured workflows. The allocation oracle searches the same whole-group candidate family.''',
'paired-benefit':r'''Paired single-failure benefit over LRU. Positive values favor workflow value; zero denotes a tie. Of 36 analytical configurations, 17 improve and 19 tie. This paired view preserves correspondence that separate outcome CDFs cannot show.''',
'branch-exposure':r'''Where the base-case benefit originates. A0--A3 have join slack 0, 2, 7, and 11\,s. Bars compare that slack with actual modeled restoration completion after the common fault. Speeding up the largest history A3 has little workflow value here; delaying A0 directly extends the join.''',
'recovery-attribution':r'''Ordered counterfactual decomposition of workflow delay at fixed placement. Starting with free resources, restore the detection floor, read costs, network, H2D, and replay in that order. Increments telescope to total workflow penalty. They include interactions assigned by this order, rather than sums of overlapping operation durations.''',
'storage-traffic':r'''Total capacity-tier traffic for the same single fault. Workflow value reads 28\,GiB versus LRU's 24\,GiB, despite reducing the workflow penalty. Faster workflow completion is therefore not evidence of lower aggregate I/O. The 16\,GiB DRAM constraint is an upper bound; indivisible candidates can leave space unused.''',
'burst-interference':r'''FIFO recovery-pool stress model: a simultaneous burst of identical interrupted workflows shares one two-target pool. The pool is reserved until each workflow's last restore completes. Queue delay is added to the join penalty. This deliberately restrictive policy exposes externalities that an isolated-fault comparison misses.''',
'background-backlog':r'''Fluid I/O backlog after the fault, with normal traffic consuming 70\% of the 4\,GiB/s storage reader. The initial backlog equals recovery bytes and drains at residual bandwidth. This conservation-of-work example measures I/O backlog, not background workflow WCT or TTFT.''',
'logical-fault-phase':r'''Matched logical progress with growing checkpoint state. Each branch's bytes scale with progress relative to the 80\% base case; remaining durations, rates, and the absolute DRAM budget stay fixed. This controlled sweep isolates state growth and does not represent a measured distribution of fault phases.''',
'checkpoint-lag':r'''Actual commit lag can dominate nominal checkpoint spacing. The analytical sweep adds tail reconstruction implied by commit lag, with the same transport resources. Physical replacement must use the last committed frontier at the fault, including failed or backlogged writes; a trigger interval is not a durability guarantee.''',
'trace-outages':r'''Observed outage-duration distribution after the stated LANL compute-node filtering and interval merge: 21,738 intervals across 22 systems. Durations come from recorded start/end times, not from the serving model. The source is a pinned redistribution with the original-archive verification limitation stated in the text.''',
'trace-bursts':r'''Observed counts of distinct nodes whose outage intervals start at the same recorded minute within a system. There are 19,561 start groups, including 568 multi-node groups; the largest contains 45 nodes. Timestamp coarsening and simultaneous outages are not distinguishable at this resolution.''',
'modern-trace-labels':r'''Modern GPU-trace audit: fault-labeled nodes per job in the 98-job Reflex alert dataset. Job labels identify 144 faulty node/job entries, but 108 have no matching alert on that node. These labels do not provide a time of failure or repair; the curve is not an outage-frequency estimate.''',
'trace-penalty':r'''LANL-start-time-driven FIFO recovery model, one assumed four-branch workflow per cleaned node outage, preserving per-system start times at their original rate. Curves show 21,738 conditional recovery episodes. The observed input is the outage calendar; recovery durations and workflow penalties are modeled.''',
'trace-queue':r'''Separating intrinsic join delay from queue wait in the trace-driven model. Workflow value reduces intrinsic delay but lengthens pool occupancy, increasing queue delay. The bars use all replayed episodes with equal episode weights and make no claim about healthy-workload arrivals.''',
'trace-system-benefit':r'''Per-system paired mean benefit under the original recorded start times, computed as LRU minus workflow-value mean penalty. All 22 system IDs are shown. Positive values favor workflow value; negative values are retained. Each system is shown separately instead of treating its many correlated node events as independent experimental repetitions.''',
'trace-burst-control':r'''Timing controls for the same episodes: evenly spaced starts preserve each system's count and span; within-minute spreading distributes tied starts over 59\,s in node order. The latter probes timestamp resolution. These are declared transformations, not recovered physical timestamps or new observed traces.''',
'trace-time-stress':r'''Timestamp compression sensitivity. Factor 1 preserves recorded spacing; larger factors compress within-system spacing while leaving modeled service times unchanged. All factors retain every cleaned event. Accelerated points are explicit load stress tests and must not be reported as the original failure rate.''',
'ablation-fault':r'''Static value ablations over 12 size/slack scenarios at 4\,GiB/s storage bandwidth, a subset of the 36-case outcome grid. Removing DAG information, removing normal-use value, or using an allocation oracle changes only the stated decision rule. This panel evaluates value selection, not the full online system.''',
'ablation-reuse':r'''Normal next-use cost for the same 12 static placements and scenario weights as the failure ablation. This companion panel prevents recovery gains from concealing a normal-reuse regression. No-reuse removes the value term, not the ability to perform normal cache lookups.''',
'common-fault':r'''Common-failure complementarity in a constructed join. The exact joint outcome is compared with an additive isolated-request estimate as more required branches are retained. A bounded controller must revalue complete plans; per-request slack deductions cannot generally be added.''',
'layer-factorial':r'''Equal-budget $2\!\times\!2$ layer-placement/scheduling experiment on eight synthetic layer payloads. Early/late policies retain two payloads; serial/pipeline schedules use the same selected demand, rates, and two-layer transient workspace. The x-axis changes selected payload density for all policies equally, not attention semantics.''',
'layer-exposure':r'''Layer-model completion decomposed into required compute and exposed waiting. At full demand, each of eight layers computes for 3\,ms. Early versus late DRAM placement ties under serial scheduling (56\,ms), but gives 32 versus 34\,ms with the bounded pipeline. The interaction, rather than independent speedup sums, explains the difference.''',
'sparse-misses':r'''Sensitivity to constructed prefetch correctness with full required demand held fixed. A wrong prefetch consumes an extra storage read, and the required payload becomes available only after its reveal point. Correctness fraction is an input to this mechanism model, not the measured accuracy of a sparse predictor.''',
'rental-churn':r'''Accepted migrations on one deterministic 512-opportunity stream with eight resident slots and 24 equal-byte candidates. Direct value and trial rent use the same instantaneous value and migration test; the other variants remove hysteresis or renewal. This additive tier model is isolated from DAG and serving execution.''',
'rental-revaluation':r'''Exact replacement-plan revaluations on the same stream. Counting operations tests whether screening reduces expensive evaluations; it does not measure CPU milliseconds. Trial rent and direct value both perform 396 revaluations here, so this case provides no screening-cost improvement.''',
'rental-cost':r'''Next-use miss cost and migration cost on the same rental stream, in declared abstract delay-cost units. Trial rent makes slightly fewer migrations but incurs greater total cost than direct revaluation. The result is retained as a limitation of the heuristic; fewer migrations alone do not establish a better policy.''',
'capacity-frontier':r'''Single-failure DRAM-capacity sweep at fixed storage capacity, rates, and logical fault. Value and oracle policies optimize the joint normal-use/failure score; their fault-only penalty need not decrease monotonically. Equal DRAM capacity is required for deployable-policy comparisons.''',
'storage-bottleneck':r'''Storage-rate sensitivity with DRAM, shared-network, and H2D capacities held fixed. Improvements flatten when a different stage becomes limiting. Each curve uses the same workload and physical byte convention; generic rates are assumptions, not SSD device measurements.''',
'prediction-robustness':r'''Signed alternating perturbation of estimated remaining durations, followed by policy decisions and evaluation against true durations. This is policy sensitivity, not predictor accuracy. Adverse points are retained, including the $-25\%$ case where workflow value is worse than LRU.''',
'healthy-io':r'''Separate M/D/1 I/O illustration with constant service time: mean I/O response rises with background backup utilization. This queueing calculation neither measures GPU interference nor supplies an end-to-end TTFT or SLO result.''',
'rate-break-even':r'''Net expected saving in an isolated-fault horizon: failure probability times the base-case 2.0083\,s saving, minus an assumed healthy cost. Curves cross zero at different probabilities. These healthy costs and probabilities are sensitivity inputs, not production measurements.''',
'safe-demotion':r'''Capacity pressure and safe release. Lowering the target from 24 to 16\,GiB does not free physical DRAM immediately. Copy completion precedes manifest redirection and reader drain; this modeled trace releases the 8\,GiB at 5.5\,s. It demonstrates accounting, not a tested distributed implementation.''',
'controller-scaling':r'''Analytical controller work under the explicitly assumed per-node visit cost and bounded episode count. The curve shows an operation-cost projection, not measured scalability. Physical validation must include graph edges, candidate enumeration, profile evaluation, locking, and metadata contention.''',
}

TEXT=r'''
\section{Evaluation}
\label{sec:evaluation}

Our evaluation asks five questions: does workflow-aware placement improve
completion after one failure; which recovery and dependency mechanisms
produce that improvement; does it persist under recorded outage timing;
which online mechanisms justify their complexity; and what healthy-service,
resource, and correctness costs accompany it? We evaluate the complete
claim chain, from retained bytes to ready KV to branch completion to
workflow completion, rather than using cache hit rate as its endpoint.

\paragraph{Evidence status.}
This expanded research draft contains reproducible analytical results,
descriptions of public traces, trace-driven model results, and a detailed
physical experiment specification. It does not report an implemented
end-to-end failure-recovery campaign. Each figure identifies its evidence
level. Measured Motivation microbenchmarks retain their own scope;
their timings are not silently substituted for the generic rates below.
The static value model, isolated rental model, and layer model test distinct
parts of the proposal, and are not combined into a fabricated system speedup.

\subsection{Experimental Contract and Baselines}
\label{sec:eval-method}

\paragraph{Deployment.}
The primary physical experiment uses failure-separated serving replicas
and independently reachable backing storage. We specify DP=2/4/8 and TP=1/2
as separate cells; a TP2 host-failure test requires at least two compatible
two-GPU replicas on separate hosts. GPU-process, whole-replica, host, and
storage-host failures are distinct experiments. Report surviving capacity
and execution/staging HBM, rather than assuming that a failover target has
unlimited memory. Local NVMe, remote NVMe, and shared filesystem backends
are separate configurations. Same-host SSD does not protect against host
loss. The physical campaign must pin model weights, attention kernels,
engine and controller commits, TP layout, block size, drivers, network
topology, filesystem configuration, and fault-injector version.

\paragraph{Workloads and load.}
Use executable coding-agent and FanOutQA workflows, together with controlled
sequential, balanced fork/join, and heterogeneous fork/join DAGs. Retain
the original graph once, with identical workflow IDs and arrival order;
do not manufacture normal reuse by repeating the DAG. Start with 30
distinct workflows per family and publish their IDs and input hashes.
Replay frozen tool responses for the primary comparison; live tool calls
form a separate validity check. Use supported dense and native-sparse
model paths, including Qwen3-8B and Qwen2.5-7B-Instruct-1M, and contexts
32K/128K/512K/1.01M where executable. Unsupported cells remain missing
with reasons. Arrival traces use 30/60/85\% of one fixed baseline's
sustainable healthy throughput, with identical absolute arrivals across
policies. Report the resulting load after losing a replica.

\paragraph{Equal-resource baselines.}
Recompute keeps durable accepted input/output logs but no additional
fault-safe KV history. Storage-only keeps complete checkpoints in the
capacity tier. Hierarchical LRU and reuse-only share AegisKV's transport,
manifest, safety, and checkpoint-frontier implementation. LRU is the main
same-substrate baseline; reuse-only isolates the benefit of dependency and
failure information. All policies pay for committed, reserved, retiring,
metadata, and staging bytes, and for checkpoint and migration traffic.
Shared physical objects are charged once per replica. All-DRAM relaxes
the capacity constraint and is a reference, not an equal-cost competitor.
An exhaustive feasible oracle is restricted to small candidate sets and
the same objective; it is not an online-system oracle.

External comparisons should use pinned D\'ej\`aVu, GhostServe, and LUMEN
artifacts when compatible, and a tuned Mooncake/SGLang or Strata-style
hierarchy~\cite{strati2024dejavu,jayakody2026ghostserve,cao2026lumen,qin2025mooncake,xie2026strata}.
Count replication/parity capacity, coding work, write traffic, and achieved
frontier lag. A reproduced mechanism is labeled as a reimplementation;
none of the present curves is a fabricated result for these named systems.
TOPAS/KVFlow comparisons require the same failure-safe backing substrate
before recovery differences can be attributed to workflow policy.

\paragraph{Outcomes and cohorts.}
For policy $p$ and workflow $w$, the paired failure penalty is
\begin{equation}
 D_{w,p}=\mathrm{WCT}^{\mathrm{fault}}_{w,p}
          -\mathrm{WCT}^{\mathrm{healthy}}_{w,p}.
 \label{eq:eval-penalty}
\end{equation}
Every policy has its own healthy mate. Positive
$D_{w,\mathrm{LRU}}-D_{w,p}$ favors $p$, but we also report absolute healthy
and faulty WCT, completion, and SLO goodput. Separate directly interrupted
workflows, other workflows sharing recovery resources, and an isolated
control cohort. The second cohort establishes interference only when
the actual shared link, queue, or GPU is identified. Report p50/p95/p99
only with adequate completed samples, along with timeouts and the common
observation horizon. Hit rate, restore latency, and workflow latency have
different denominators and are never interchangeable.

\paragraph{Declared analytical instance.}
Four branches A0--A3 have 4/8/12/16\,GiB state, remaining durations
12/10/5/1\,s, and next-use weights 0.15/0.35/0.60/0.85. Rates are
20\,GiB/s DRAM, 4\,GiB/s storage, 12\,GiB/s shared network, and
20\,GiB/s H2D per target, with two surviving targets. The common recovery
floor is 0.25\,s, replay is 0.4\,s, and reconstruction costs 8\,s/GiB.
DRAM is limited to 16\,GiB and storage to 160\,GiB. The event calendar
schedules 0.25\,GiB chunks in round-robin request order through shared
readers, a shared network, and target-local H2D/compute. Tail replay starts
after the required state arrives. Transport overlaps, but this particular
model has no layer-wise replay overlap or online rental controller.
Static admission greedily maximizes marginal value per byte with
failure-episode probability 0.05 and next-use probability 0.02 over a
60\,s horizon. These are sensitivity inputs, not observed production rates.

\subsection{One Failure: End-to-End Benefit}
\label{sec:eval-workflow}

\paragraph{Controlled intervention.}
The primary campaign kills the same source replica when a specified
workflow, Agent, and request reaches 80\% of its frozen logical token progress.
The cohort includes every interrupted request on that source, not only
the request that triggers injection. Baseline and candidate runs preserve
the same input, token history, arrival trace, target resources, and failure
identity. Separate the detection floor, routing/admission, checkpoint
lookup, restore, replay, and resumed execution in raw logs. A common
wall-clock kill would confound progress with policy speed.
Mechanism-attribution runs freeze the pre-fault source assignment and
committed coverage. Full-system runs allow policies to change routing
and achieved frontiers, and use the fixed original arrival cohort for
intent-to-treat comparisons; they also report changes in which workflows
were directly interrupted. These two experiments answer different questions.

The analytical grid spans state-size factors 0.5/1/2, slack factors
0/0.3/1/3, and storage rates 1/4/12\,GiB/s, giving 36 configurations.
DRAM scales with state size in this grid. Figures~\ref{fig:eval-workflow-outcomes}
and~\ref{fig:eval-paired-benefit} show both distributions and matched
differences. Workflow value improves 17 configurations and ties 19;
the absence of a loss in this grid is not a worst-case guarantee.
LRU and reuse-only happen to choose the same order in this declared
instance, so their agreement is not independent evidence against all
reuse policies. Physical comparisons must include other recency/reuse
orders and each workload family separately.

@@workflow-outcomes@@
@@paired-benefit@@

In the base case, storage-only adds 5.5583\,s to workflow completion,
LRU adds 3.6208\,s, and workflow value adds 1.6125\,s. The reduction
relative to LRU is 2.0083\,s, or 55.5\% of the \emph{failure penalty};
it is not a 55.5\% end-to-end WCT reduction. The healthy residual join
is 12\,s, giving faulty residual completion times 15.6208 and 13.6125\,s.
Reconstruction's 190.65\,s penalty illustrates the value of reliable
coverage, while the LRU comparison isolates fast-tier placement beyond
that coverage. Measure full workflow lifetimes in the physical experiment;
do not replace them with this residual-window example.

\subsection{One Failure: Explaining the Gain}

\paragraph{Dependency exposure.}
For a single fork/join instance with residual durations $d_i$ and restored
ready times $R_i$, the exact local join penalty is
\begin{equation}
 D=\max_i(d_i+R_i)-\max_i d_i.
\end{equation}
The base join slack is 0/2/7/11\,s. LRU retains the 16\,GiB A3 history;
workflow value retains A0 and A1 (12\,GiB total). Figure~\ref{fig:eval-branch-exposure}
shows why these choices differ. A3's long restoration can remain inside
its available margin, whereas A0 cannot hide any delay. Whole-group
granularity leaves 4\,GiB unused; it is part of the candidate restriction,
not free capacity secretly assigned to another policy.

@@branch-exposure@@

\paragraph{Critical-path accounting.}
Figure~\ref{fig:eval-recovery-attribution} attributes the final join penalty
using ordered interventions. Placement is frozen. We start with negligible
read/network/H2D service time and zero floor/replay, then restore each
cost in a specified order. Consecutive join differences sum to the final
penalty. This decomposition can assign interactions to different stages
if the intervention order changes. It is therefore an explanatory model
decomposition, not unique causal attribution. In hardware, additionally
record a dependency-linked critical path from event timestamps: sum only
non-overlapping intervals on that path, and report total GPU/I/O work
separately. Neither method may add all SSD, H2D, and GPU durations and
call that wall-clock recovery time.

@@recovery-attribution@@
@@storage-traffic@@

\paragraph{Cost of prioritization.}
Figure~\ref{fig:eval-storage-traffic} supplies a necessary counterpoint.
Workflow value reads 28\,GiB from storage, versus LRU's 24\,GiB, and
occupies the complete recovery pool for 7.6833 rather than 6.6833\,s.
It finishes this workflow earlier while consuming the resource longer.
Collect useful bytes, unused prefetched bytes, duplicate reads, checkpoint
writes, and reconstruction work in addition to the critical path. A claim
of lower storage traffic, lower GPU cost, or lower recovery makespan
would be false for this example.

\subsection{One Failure: Collateral Delay and Recovery Backlog}

\paragraph{Shared-resource experiment.}
Cross 1/2/4/8 interrupted workflows with 30/60/85\% pre-fault load and
one/two/four compatible recovery targets. Keep the faulted logical state
and healthy arrival stream fixed. Report direct-workflow delay, collateral
workflow delay, retry-queue occupancy, storage/NIC backlog, and time to
return to the predeclared latency band. Separately remove the common
reader/link by giving targets independent channels. If the collateral
effect disappears, that supports the resource-sharing explanation.
If there is no physical shared bottleneck, do not claim a cross-target
cascade from a model that imposes one.

@@burst-interference@@
@@background-backlog@@

The FIFO stress model in Figure~\ref{fig:eval-burst-interference} holds
one recovery pool until all four branch restores finish. For $n$
simultaneous identical workflows, mean penalty is
$D+(n-1)S/2$, where $S=\max_i R_i$ is pool occupancy. Workflow value
loses its isolated advantage once the additional pool waiting dominates:
at $n=8$, mean penalties are 28.5042\,s for workflow value and
27.0125\,s for LRU. This is a falsification of extrapolating the
isolated placement result to arbitrary bursts, not a measurement of the
proposed load-aware router. Figure~\ref{fig:eval-background-backlog}
similarly exposes the larger I/O drain interval under a fixed foreground
arrival rate. The physical test must include concurrent scheduling and
the joint value of affected and collateral workflows.

\subsection{Failure Position and Checkpoint Freshness}

Repeat the same-ID experiment at 20/50/80/95\% logical progress, during
prefill, during decode, during a tool wait, and immediately around a
demotion commit. State precisely whether progress counts accepted total
tokens or generated tokens; never mix denominators. Figure~\ref{fig:eval-logical-fault-phase}
isolates growing historical state under fixed remaining-work assumptions.
Real phase sweeps also change the remaining graph, native demand, and
checkpoint frontier, which must be taken from the actual run.

@@logical-fault-phase@@
@@checkpoint-lag@@

For $Z=64/256/1024$, enumerate every ideal checkpoint phase when presenting
an analytical average, pairing policies at the same $Z$ and phase.
The physical experiment records trigger, copy start, committed frontier,
acknowledged frontier, and retry start. Report lost/uncommitted tail
length, replay time, failed commits, and write backlog. Actual tail length
can exceed $Z$ under backpressure. A short trigger interval can worsen
recovery if it congests the write path. Sweep read/write interference,
write rate, and queue capacity while holding total retention budgets fixed.

\subsection{Real Traces: Provenance and Event Semantics}

\paragraph{Historical node outages.}
LANL documents node interruptions with start/end times, node/system IDs,
and cause categories~\cite{lanlFailureData,schroeder2006failures}. We use
a revision-pinned public redistribution because the original FTP archive
was unavailable during preparation. Its CSV has 23,739 records, whereas
the official page describes 23,741; byte identity and the two-record
difference remain unresolved. This limitation is recorded in the artifact
and must be resolved before presenting the copy as an authenticated
original release. The present result is explicitly for the supplied
redistributed CSV, not for an asserted identical original archive.

We retain rows with purpose exactly \texttt{compute}, exclude 1,648 other
rows and 122 zero-duration rows, and merge overlapping or touching
intervals per node, removing 231 additional interval boundaries. No
negative-duration or unparseable compute intervals occur. The resulting
21,738 intervals cover 3,542 observed nodes across 22 systems. We retain
all recorded cause categories, including interruptions that may involve
maintenance; this is not a hardware-only crash sample. Original row IDs
and every exclusion/merge are recoverable from the cleaning output.

@@trace-outages@@
@@trace-bursts@@

Recorded starts have minute resolution. Equal timestamps identify
coincident \emph{recorded} starts, not proof of a common physical cause.
There are 19,561 within-system start groups, 568 with multiple nodes,
and a maximum of 45 nodes. Systems have separate observation calendars
and are never superimposed as one cluster. These historical CPU/HPC
outages test clustered timing; they do not estimate a 2027 GPU fleet's
failure rate, repair latency, or workload mix. Missing exposure information
also prevents using the observed failing-node count as the denominator
of a fleet-wide availability estimate.

\paragraph{Modern GPU alerts as a separate check.}
The Reflex release contains 98 LLM-training jobs, 344,175 alerts, and
144 faulty node/job labels~\cite{ding2026reflex,reflexDataset}.
Figure~\ref{fig:eval-modern-trace-labels} characterizes the labels.
Of the faulty labels, 108 have no alert on the labeled node. Moreover,
timestamps are shifted independently per job and repair times are absent.
We therefore neither stitch jobs into a calendar nor label the first
alert as the fault time. This dataset can support within-job alert-pattern
or diagnosis studies, but it cannot supply an unqualified fail-stop/repair
schedule for this paper. A modern serving outage trace with explicit
event semantics remains an important external-validity target.

@@modern-trace-labels@@

\subsection{Trace-Driven Recovery: Benefits and Tail Regressions}

\paragraph{Reproducible conditional replay.}
Each cleaned LANL node-outage start releases one assumed four-branch
workflow requiring recovery. Each original system has an independent
FIFO recovery pool with two surviving targets. Its service occupation
$S_p$ and intrinsic join penalty $D_p$ are the base-case values already
derived from bytes and rates. For consecutive arrivals at $a_i$, pool
waiting is $q_i=\max(0,q_{i-1}+S_p-(a_i-a_{i-1}))$, and workflow
penalty is $q_i+D_p$. Ties use node-ID order. Starts retain their original
spacing. There is no service-time fitting to the trace and no tuned
policy-specific arrival schedule.

This replay is conditional on available independent recovery capacity
and complete committed histories. It does not replay healthy serving,
provision failed nodes, model finite spare exhaustion, or infer which
historical nodes actually hosted active agents. End times are used for
outage characterization, not as measured GPU repair times. Accordingly,
the result is a recovery-load experiment, not an availability or SLO-goodput
measurement of an operating cluster.

@@trace-penalty@@
@@trace-queue@@

At original spacing, mean modeled penalty is 10.4533\,s for LRU and
9.4673\,s for workflow value, a 9.4\% reduction. Mean queue wait rises
from 6.8324 to 7.8548\,s. The p95 penalty worsens from 37.0375 to
40.0292\,s, and p99 from 204.1208 to 232.1125\,s. Thus this input
supports a conditional average benefit and simultaneously refutes a
blanket tail-latency claim. Figure~\ref{fig:eval-trace-system-benefit}
keeps per-system losses visible. Neither thousands of events nor small
arithmetic error bars turn one historical trace into independent serving
experiments.

@@trace-system-benefit@@
@@trace-burst-control@@
@@trace-time-stress@@

\paragraph{Controls and full-system extension.}
The evenly spaced control preserves each system's event count and
calendar span while removing original clustering. Timestamp compression
and within-minute spreading distinguish load and timestamp-resolution
sensitivity. Spreading equal-minute starts over 59\,s gives LRU/workflow-value
means 8.0997/7.0224\,s and p99 values 163.8936/191.8852\,s; the adverse
tail remains. These constructed timestamps are not inferred ground truth.
Compression
factors 10/100/1000 increase load explicitly; factor 1 alone retains the
original rate. For a full serving replay, freeze a workload-to-failure-domain
mapping before comparing policies, publish its seed, and use original
start/end intervals to remove and return capacity. Replay arrivals even
during outages, allow failures during unfinished recovery, and retain
incomplete workflows at a common horizon. Repeat mappings at fixed
1/2/4 active workflows per source, different spare fractions, and both
independent and shared backing domains. Preserve correlated event groups
when mapping to fewer machines; never silently serialize a 45-node event
onto one injector. Over-capacity groups must be reported as unsupported
or simulated at the stated scale. Trace amplification and synthetic
repair-time assumptions belong in sensitivity panels, not the primary
real-time trace result.

\subsection{Complete Value and Dependency Ablations}

Every ablation changes one specified mechanism while retaining the same
fault-safe backing, candidate budget, workloads, and physical resources.
The physical matrix includes: no DAG information; independent-request
penalties instead of joint source-event propagation; no normal-reuse
term; no failure term; fixed placement; direct revaluation without rent;
no credit renewal; no migration hysteresis; recency instead of causal
sparse history; serial instead of bounded layer overlap; and locality-only
instead of load-aware recovery routing. Removing a value term never
disables the underlying safety protocol or ordinary cache eligibility.
Correctness mechanisms are tested by injected interleavings, not by
benchmarking an unsafe variant as a valid baseline.

@@ablation-fault@@
@@ablation-reuse@@
@@common-fault@@

The two static ablation panels report fault and normal-use costs together
on the 12-case size/slack subset at 4\,GiB/s storage bandwidth; their
means are not the 36-case bandwidth-mixed means in the outcome CDF.
For each real campaign, additionally log changes in resident objects,
predicted plan value, admitted/rejected migrations, actual critical-path
branches, bytes moved, and controller time. This distinguishes a useful
signal from a coincidentally equivalent placement. The common-failure
example shows why summing isolated losses is insufficient: complementary
required branches can make the marginal value of a bundle different
from the sum of its singleton values. Compare singleton-only candidates
with bounded pairs, then enumerate the oracle on small cases to quantify
candidate-family and search regret separately.

Use factorial experiments for interacting mechanisms: DAG information
$\times$ joint-fault modeling; sparse ranking $\times$ layer overlap;
rent $\times$ hysteresis; and load-aware routing $\times$ shared-link
contention. Keep all four cells of each $2\!\times\!2$ design. The
interaction is the paired difference of differences, not the sum of
individual speedups. A tied or negative ablation is informative and
cannot be removed merely because it weakens the proposed narrative.

\subsection{Sparse Demand and Layer-Overlap Ablations}

\paragraph{Controlled mechanism model.}
An eight-layer example uses an SSD payload cost of 4\,ms, H2D cost of
1\,ms, and required compute of 3\,ms/layer at full selected demand.
DRAM retains two payloads, either early or late; transient workspace
holds only the current and next layer. Serial and pipeline modes use
the same demand and resources. Payload density scales I/O for all
policies equally and is not a change to the native attention algorithm.
Figures~\ref{fig:eval-layer-factorial}--\ref{fig:eval-sparse-misses}
test placement, overlap, and prediction errors separately.

@@layer-factorial@@
@@layer-exposure@@
@@sparse-misses@@

At full demand, both serial placements take 56\,ms; pipelining gives
34\,ms with late placement and 32\,ms with early placement. Required
compute is always 24\,ms. The remaining 10 versus 8\,ms is exposed
waiting, not avoided historical prefill. Prediction errors consume
extra reads and force demand-reveal stalls; perfect prediction is only
one sensitivity point.

\paragraph{Native implementation experiment.}
Capture the actual per-layer demand union over the retry tail, with
selection metadata and reveal timestamps from the pinned native kernel.
Use historical queries only for prediction and a later held-out replay
window for evaluation; split by document/workflow, not individual blocks.
Compare recency, past access frequency, and the proposed causal profile
at equal physical bytes, mandatory sink/window reservations, and full
checkpoint coverage. Cross each with serial and bounded pipeline restore.
Report all-layer coverage, useful/unused prefetch bytes, missed demand,
reveal-to-ready wait, exposed GPU stalls, workspace peak, total replay,
and WCT. A high early-layer hit rate does not establish high total
coverage. Dense demand is a control, not an implementation failure.
Do not reduce native selections, omit auxiliary state, or count an
approximate answer as exact recovery to make an offload policy faster.

\subsection{Online Rent, Renewal, and Migration Hysteresis}

The isolated tier model has eight resident slots, 24 equal-byte objects,
and 512 deterministic candidate arrivals under smoothly drifting value.
Every policy receives the same revisit and next-use stream. Direct
revaluation and trial rent share the same current benefit calculation,
replacement check, and movement cost. The latter additionally uses
credit aging and renewal to screen a potential victim; rejected previews
leave rent unchanged. No-hysteresis and no-renewal isolate those choices.
This additive model tests the screening heuristic rather than approximating
nonadditive workflow value as measured end-to-end benefit.

@@rental-churn@@
@@rental-revaluation@@
@@rental-cost@@

Direct revaluation makes 108 migrations and trial rent 106, but both
perform 396 full revaluations. Total modeled miss-plus-movement cost
is 462.96 versus 506.39 cost units. Removing hysteresis increases
migrations to 121; removing renewal reduces migrations to 77 while
raising total cost to 526.05. These results do not validate rent as an
improvement over direct value. They show why churn, decision cost, and
actual retained value must be reported jointly.

In the prototype, replay growing contexts, abrupt workload shifts, tool
handoffs, and target-capacity changes with identical candidate opportunities.
Log trial and committed rent, expirations, renewal causes, victim eligibility,
joint revaluation counts, rejected previews, movement bytes, and realized
workflow cost. Run DRAM and storage ledgers separately and verify that
leased committed copies still age although they cannot be evicted.
Measure exact controller CPU time and metadata operations under a fixed
candidate budget. If direct revaluation matches or beats rent at acceptable
cost, the experiment supports simplifying the controller; a rental
mechanism is not a contribution merely because it has a named algorithm.

\subsection{Capacity, Storage, and Recovery Coverage}

Sweep DRAM/unique-checkpoint-working-set ratios 0/0.1/0.25/0.5/1 and
storage ratios 0.5/1/2. Count unique physical bytes and record the
time-varying working set. The finite-storage cells must exercise final-copy
deletion and valid fallback frontiers; they cannot silently turn a DRAM
demotion into unlimited backing storage. Cross equal budgets with
context length and source concurrency. Report unsupported memory/kernel
configurations explicitly. Figures~\ref{fig:eval-capacity-frontier}
and~\ref{fig:eval-storage-bottleneck} cover the static capacity and
bandwidth components; the base model assumes sufficient backing and
therefore does not validate final-copy eviction performance.

The value objective is not fault-only WCT. At budgets 16 and 28\,GiB,
the feasible oracle's joint score improves from 0.15049 to 0.14383\,s,
while its fault penalty increases from 1.6125 to 1.9458\,s because
normal reuse also benefits from retention and transfers share resources.
The raw capacity table therefore records both objectives and chosen
objects. A nonmonotone fault-only curve is not evidence that extra
capacity worsens the oracle's optimized joint objective.

@@capacity-frontier@@
@@storage-bottleneck@@

For each real backend, measure read and write bandwidth, request-size
dependence, concurrent reader/writer contention, commit durability, and
end-to-end GPU-ready time. Cold client cache, warm client cache, and
documented server-cache state are separate cells. Direct I/O controls
the client path only; an uncontrollable shared-filesystem server cache
must remain labeled unknown. Read the same payload and use the same
transport schedule across policies. Add a shared-storage slowdown or
loss experiment to distinguish surviving checkpoint coverage from
nominally low-latency placement. A system cannot recover unavailable
state just because its expected value was high.

\subsection{Prediction, Stale Profiles, and Missing Information}

Train remaining-time prediction on earlier complete workflows, tune on
a disjoint validation split, and evaluate on later workflows. Features
must be visible at the decision landmark. Report raw remaining-time
error, false-positive slack, critical-path ranking, fallback frequency,
and inference/update cost. A correlation or aggregate WAPE does not
determine a per-agent error CDF. Compare the trained model with duration
medians, zero-slack fallback, and an oracle-duration reference.

@@prediction-robustness@@

The present perturbation model alternates the sign across branches;
at $-25\%$, its 4.5583\,s penalty is worse than LRU's 3.6208\,s.
The physical robustness matrix includes independent and correlated
$\pm10/25/50/100\%$ duration error, missing edges, late tool completion,
stale bandwidth profiles, cold starts, model shifts, and failure-probability
miscalibration. Recompute decisions against actual outcomes rather than
adding an error bar to a nominal curve. Include conservative fallback
and compare the cost of lost opportunity with the cost of false slack.
High predictor accuracy alone is insufficient if it does not change
useful placement decisions.

\subsection{Healthy Service and When Protection Pays}

Run the same workflows without faults at each fixed baseline-defined
load. Include first calls, tool waits, and every Agent request in the
denominator. Report healthy WCT, TTFT, inter-token delay, SLO goodput,
GPU-seconds, controller CPU/memory, checkpoint write volume, and per-tier
request/token hits. Distinguish trace-observed prefix sharing from
realized runtime hits. Compare no new checkpoint protection, LRU,
reuse-only, full value, and no-reuse value with identical storage limits.

@@healthy-io@@
@@rate-break-even@@

Figure~\ref{fig:eval-healthy-io} supplies an I/O queueing mechanism,
not a TTFT result. For the isolated base case, a simple horizon-level
break-even calculation is $p_f\Delta D-C_h$, where $C_h$ includes
healthy-service and migration costs in the same objective units.
Figure~\ref{fig:eval-rate-break-even} shows that a fixed cost of 0.05\,s
requires $p_f>0.0249$ under the assumed 2.0083\,s benefit. This threshold
changes with workload, horizon, and queue externalities. Neither the
illustrative 0.05 probability nor the historical outage trace establishes
the production value of $p_f$. The physical study must report conditional
recovery benefit and amortized net benefit separately. Failure rarity
can invalidate a system-wide value claim even when recovery is faster.

\subsection{Correctness, Safety, and Pressure Transitions}

Inject failures immediately before/after reservation, partial copy,
checksum completion, storage commit, directory redirection, token
acknowledgement, and final reader drain. Include duplicate completions,
stale epochs, target loss, missing TP shards/selector state, write timeouts,
and full tiers. A published manifest must identify complete compatible
state; PENDING bytes cannot satisfy a restore. Validate durable accepted
tokens, all-layer replay state, next greedy output under the stated
numerical tolerance, and absence of duplicate acknowledged output.
Tool-side effects require application idempotency evidence separately.

@@safe-demotion@@

The 24-to-16\,GiB pressure example retains physical bytes until 5.5\,s,
despite the earlier target change and copy completion. Reproduce this
trajectory with overlapping leases, reverse pressure, copy failure,
and last-copy eviction. Check physical, reserved, committed, retiring,
and actually free bytes at every transition; a lower target is not free
memory. Exhaustively enumerate the small state machine and run at least
100 randomized interleavings per transition class in the implementation.
Report the number of distinct injected interleavings, failures, and
unresolved cases. Analytical invariants do not replace protocol execution.

\subsection{Scale and Controller Cost}

Sweep DP=2/4/8, DAG sizes 10/100/1,000, live groups
$10^2/10^3/10^4$, and candidate limits 16/64/256. Independently vary
source-domain concurrency and surviving target count. Record p50/p95/p99
decision time, profile calls, graph visits, edge visits, lock duration,
metadata bytes, plan age, and foreground stalls under a fixed CPU budget.
Small-instance oracle comparisons measure solution quality only where
enumeration is feasible; absence of an oracle at scale is not a zero gap.

@@controller-scaling@@

The current curve multiplies an assumed node-visit cost by declared
passes/episodes. It establishes neither actual control latency nor full
algorithmic complexity once candidate enumeration and shared-object
owners are included. A useful scaling result must show bounded queues,
acceptable stale-decision rates, and maintained workflow outcomes, not
only a fast isolated scorer. Report saturation and failed configurations
rather than omitting them from a log-scale axis.

\subsection{Statistics, Reproducibility, and Execution Order}
\label{sec:eval-plan}

Start physical primary cells with ten independently launched paired
campaigns. Randomize policy order, retain identical workflow/fault IDs,
and log what each seed changes. Within a campaign, compute each policy's
fault-minus-healthy outcome by workflow ID, then the paired difference
against LRU. Aggregate within campaign before bootstrapping campaigns
(10,000 resamples with a fixed analysis seed); resampling individual
tokens or correlated failures does not create independent repetitions.
For repeated trace windows, use non-overlapping calendar blocks and
report both event-weighted and system/window-weighted summaries.
The deterministic model and finite public-trace descriptions shown here
have zero physical repetitions and no fabricated confidence intervals.

Report common-horizon completion and deadline goodput for every input
workflow, including timeouts. Complete-case latency must use the same
eligible set across policies and show exclusions. If using restricted
mean completion time, state the estimator and censoring assumptions;
do not assign a timeout an invented finish time or let success-only
p99 appear to improve as more workflows fail. Release raw manifests,
arrivals, faults, workflow/request outcomes, dependency-linked events,
prediction snapshots, and all table-generation commands with hashes.
Fixed single-column figure canvases and a separate visual specification
allow replacement data to use the same axes, fonts, and layout.

Execute correctness and backend calibration first, then the same-ID
single-failure matrix and its decomposition, then healthy overhead and
the four factorial ablations, followed by continuous real-trace replay
and pressure/scale tests. Resolve the LANL redistribution discrepancy
and obtain a modern outage trace with trustworthy semantics before
making general fleet claims. The present tail and rental regressions
are explicit decision points for refining or simplifying the design.
An empirical claim is supported only after the corresponding matched
campaign exists; completing an experiment specification does not make
its expected advantage a measured result.

\subsection{Reusable Figures and Measurement Replacement}

All evaluation plots use individual single-column canvases with fixed
physical typography, a separate visual specification, and long-form CSV
tables. PDF, SVG, and PNG exports retain stable filenames. The manifest
records source and table hashes, evidence type, units, aggregation command,
and independent-run count. Measured replacement accepts only tables tied
to declared physical raw logs and campaign-level sample accounting;
changing an evidence badge alone is rejected. A partial measured release
replaces only the completed figure cells while other figures retain their
original labels. Data ranges expand to include negative outcomes and
tails. Changing a metric, such as replacing I/O response time with TTFT,
requires its own explicit semantic specification rather than a renamed
axis. The numerical narrative and captions must be revised with new
results; stable plotting configuration does not automatically validate
an earlier analytical interpretation.

'''

def main():
    text=TEXT
    for name,caption in CAPTIONS.items():
        body=(r'\begin{figure}[!htbp]'+'\n'+r' \centering'+'\n'+
          r' \includegraphics[width=\columnwidth]{figures/eval-'+name+'.pdf}\n'+
          ' \\caption{'+caption+'}\n'+r' \label{fig:eval-'+name+'}\n'+
          ' \\Description{'+re.sub(r'\\(?:emph|texttt)\{([^}]+)\}',r'\1',caption)+'}\n'+r'\end{figure}'+'\n')
        text=text.replace('@@'+name+'@@',body)
    assert '@@' not in text
    # Keep experiment figures with the subsection that explains them. Length
    # is intentionally unconstrained in this research draft.
    text=text.replace('\\subsection{','\\FloatBarrier\n\\subsection{')
    text+='\\FloatBarrier\n'
    mainfile=ROOT/'paper/main.tex';current=mainfile.read_text()
    if '\\usepackage{placeins}' not in current:
        current=current.replace('\\usepackage{tabularx}','\\usepackage{tabularx}\n\\usepackage{placeins}')
    start=current.index('\\section{Evaluation}');end=current.index('\\section{Related Work}')
    mainfile.write_text(current[:start]+text.strip()+'\n\n'+current[end:])
    print('Expanded Evaluation inserted:',len(CAPTIONS),'single-column figures')

if __name__=='__main__':main()
