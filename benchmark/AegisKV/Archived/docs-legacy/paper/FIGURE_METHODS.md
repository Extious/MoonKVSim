> **Historical record — superseded for the revised paper.** This file describes
> the September 5 legacy-model campaign. Its results are excluded from the
> Mooncake-aligned manuscript. See `MOONCAKE_ALIGNMENT.md`, `COMPLETION_REPORT.md`
> and `data/aligned-statistics.json` for the revised study.

# Figure definitions and evidence boundaries

This companion defines the scientific interpretation of the seven evaluation
figures. Numeric sidecars contain the plotted observations and their exact
input/output hashes. A figure is included in the manuscript only after its
required acceptance manifest passes and its rendered output is reviewed.

All studies hold the frozen 160-task, 1,304-call workload, Qwen3-8B layout,
DP=8/TP=1/PP=1, modeled topology, and declared policy parameters fixed except
for the dimension explicitly varied. Five distinct admission permutations are
paired between policies. Seeds, rather than the repeated tasks or the number
of scheduler steps, are the inferential units. Two-sided 95% Student-t
intervals use four degrees of freedom; they are exploratory and unadjusted for
multiple comparisons. All timing is modeled and uncalibrated.

| Figure and output stem | Question and expected mechanism | Population, axes, and interpretation |
| --- | --- | --- |
| 1, `workload-and-intervention` | Which prompt sizes and workflow structures are exercised, and which failures are actually compared? | All 1,304 prompt lengths on a logarithmic token axis; call counts in all 160 workflows; context-bucket counts and fractions; all five primary focus interventions. ECDFs are descriptive, without sampling intervals. Context includes prompt plus prescribed output; prompt ECDF does not. K denotes 1,024 tokens. The empty 128K bucket remains visible. |
| 2, `no-failure-cost` | Does protecting state consume resources without a failure, and how unevenly are task effects distributed? | Ten F0 executions. Mean WCT differences in seconds for all 160, initial 16, and later 144 workflows per seed; makespan/goodput changes in percent; protection submissions by destination tier in GiB/run. Hatching identifies submissions ready before the recorded warmup boundary; crosses show aborted volume. The traffic-rate denominator is the paired Store-only makespan. Positive WCT difference is slower AegisKV. |
| 3, `failure-effects` | Does a primary failure change complete-task outcomes after each policy's own healthy baseline is subtracted? | Twenty executions: F0/F1 by two policies and five seeds. Absolute F1 WCT in seconds for all, focus, impacted union, and non-focus workflows; descriptive ECDFs; paired focus and whole-workload-mean failure penalties. The impacted union is a post-treatment diagnostic. Each ECDF's 800 task-runs repeats the same 160 tasks. Negative difference-in-differences favors AegisKV. |
| 4, `recovery-mechanism` | Does recovered KV reduce recomputation or recovery readiness, and does that difference reach request completion? | The same five preselected primary focus requests, both policies. Selected normal-HBM, local-Peer, Peer-D2D, Store, and recomputed prompt fractions are disjoint and sum to one. Scatter axes use recomputed prompt percent and injection-relative latency in seconds. Lines connect policy observations within seed. All focus cases appear, regardless of mechanism class. |
| 5, `sensitivity` | How do failure pressure and concurrency change completion, HBM pressure, and selected recovery sources? | Seven F/C points by five paired seeds: F=1/2/4/8 at C=16 and C=8/16/24/32 at F=2; the shared F2/C16 point is plotted twice. Rows show absolute focus mean WCT, mean/P95 gain, workflow counts, quota/pressure, and selected prompt fractions. Positive gain is faster AegisKV. These contrasts use F1-or-higher runs without F0 subtraction. Natural physical targets and collateral victims can differ. |
| 6, `cost-and-ablation` | Are protected/restored bytes sufficient to explain completion gains, and which policy components matter? | Seven sensitivity points relate actual protection bytes transferred and selected restored prompt fraction to WCT gains. Cost includes partial bytes on aborted transfers; restored prompt fraction includes Peer and Store, excluding normal HBM. Four ablation arms use matched F0/F1 cases across five seeds. Positive ablation-minus-full failure penalty favors full AegisKV. The five lowest exact paired focus-workflow gains are shown as diagnostics. |
| 7, `timing-robustness` | Do policy effects depend on the assumed composition of shared-step service? | Sixty executions: beta=0/0.5/1, two policies, F0/F1, five paired seeds. Each model mixes the maximum and sum of participant shares while preserving a single request's service budget. The focus difference-in-differences is normalized by that seed/model's Store-only F0 focus WCT; the whole-workload-mean effect is in seconds. Negative values favor AegisKV. The alternatives are not measured latency bounds. |

## Effect definitions

Let `A_F` and `S_F` be AegisKV and Store-only values under condition `F`.
Primary and service-model failure penalties use
`(A_1 - A_0) - (S_1 - S_0)`. The complete-batch makespan supplement uses the
same definition and includes time spent waiting for workflow admission.
Post-release WCT excludes that admission-slot wait.

Sensitivity gain is `100 * (S_F - A_F) / S_F`, computed at the prescribed
within-seed cohort level before averaging seeds. Ablation uses
`(arm_1 - arm_0) - (full_1 - full_0)`. These signs and denominators differ
and must not be merged into one generic "improvement" column.

Quota in Figure 5 is a time-weighted Peer capacity fraction. Pressure is the
fraction of controller-window decisions observing pressure; it is not the
fraction of virtual time under pressure. Focus P95 is nearest-rank and equals
the maximum when a seed contains fewer than 20 distinct focus workflows.

## Selection and interpretation

Admission seeds and primary focus-selection rules are fixed before treatment
effects are inspected. Repeated-failure subsets preserve logical focus and
token-progress thresholds, allowing routing to resolve naturally in each run.
Figure 6's diagnostic table ranks all valid paired focus-workflow effects by
exact ascending gain, then seed, F, C, and workflow ID. Its full workflow IDs
and paired completion times are displayed; request identities and raw hashes
are retained in the sidecar. The healthy adverse-case supplement selects the
maximum positive WCT difference over all 800 paired task-runs. Neither
outcome-selected diagnostic supplies additional inferential replicates.

Null, mixed, and adverse direct-recovery classes remain in primary figures.
Faster workflow completion alone does not establish direct recovery benefit.
Source substitution cannot reduce recomputed prompt length when the effective
prefix stays fixed. Candidate-source estimates are compared within the
executed selector; the study does not execute a separate permanently
Peer-first treatment arm.

The historical proposed exclusive phase-stack panel, `FIGURE_4_A`, is not
authorized by the current primary acceptance contract. Overlapping loading,
scheduling, and compute intervals are therefore not added into an exclusive
failure-latency stack. The manuscript's Figure 4 uses the three authorized
source-fraction and paired-latency panels. This omission is a representation
limit and does not exclude any seed or measured outcome.

Failed or superseded campaigns remain in the execution/provenance ledger and
are excluded from current numerical aggregates. They are not silently merged
with the frozen V3 results. Each final sidecar binds its acceptance file, which
in turn binds the workload, configuration, implementation, schedules, and raw
evidence. Visual-review records bind the exact rendered output hashes.
