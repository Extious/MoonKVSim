# Disposition after the final v2 review

This is an in-progress response to `FINAL_OPUS55.md`, not external approval.
The reviewed v2 inputs remain in `final-reviewed-v2-inputs/`. New results do
not relabel or replace those historical inputs. The full goal remains open.

## 1. Agent completion-time prediction and Slack

Implemented and trained the submission-to-same-Agent-final-completion target,
including queue time, on six healthy runs of the twelve training workflows.
The 570 labels, role priors, grouped leave-one-workflow-out fits, and guarded
CPM calibration are sealed in `walltime-predictor-training-v1/`. No held-out
workflow was used for fitting, hyperparameter selection, or guard calibration.

The six healthy held-out captures contain 3,018 observations. Mean absolute
error across the three loads is 2.0274 s for 8B and 2.2008 s for 32B, compared
with role-prior baselines of 2.0730 and 2.2478 s. High-load error remains large.
`heldout-context-ambiguity-v3/` independently verifies that each Agent receives
the same complete derived Context and actual online prediction at all three
loads. Its finite-case minimum empirical MAE for a deterministic Context-only
function is 0.9956/1.0125 s. This diagnostic uses test labels offline; it is
neither a deployed oracle nor a bound on population/future error.

The matched 180-condition `../walltime-primary-v3/` campaign is running.
It changes the trained predictor, role priors, and guard jointly; it cannot
isolate their individual contributions. No failure/WCT benefit is claimed yet.
The implemented regressor is a fixed lightweight hashed-text model, not a
validated semantic encoder. Healthy labels do not establish failure-conditioned
accuracy. The earlier constructed Slack witness remains a conditional mechanism
test, not natural-workload evidence of a WCT benefit.

## 2. Native selection and Peer-HBM staging

`../native-transfer-postreview-v2/` contains 864 completed raw-KV component
conditions and an independent reconstruction of its transfer/readiness arrays.
There are three documents per model; checkpoints, bandwidths, compute settings,
and policies are paired sensitivities, not independent samples. The same three
books are reused across models.

`native-transfer-paper-summary-v1/` averages the two checkpoints within each
document before its three-document summaries. At 32 GB/s and zero assumed
compute, Current's mean advantage over DRAM is 131.072/131.072/128.683 us for
NOSA/NSA/MiniCPM. It matches Recency on the first two and trails it by 2.389 us
on MiniCPM. At 256 us assumed compute per layer, it trails Recency by
209.436/218.124 us on NOSA/NSA. Negative results are retained.

This is a separate per-object-ready transfer component, not the integrated
runtime's atomic LoadBatch. It assumes prepared residency and auxiliary state,
omits preparation cost, and uses declared uncalibrated compute sensitivities.
Native full-prefill selection is not validated chunked-resume execution.
Neither native-kernel timing nor workflow WCT is established by this package.

## 3. Quota response under a binding foreground ceiling

`../quota-pressure-postreview-v1/` has completed and sealed all 72 declared conditions;
transparent-observer, independent accounting and separate final crosschecks pass.
The experiment uses the new wall-time predictor, role priors, and guard.
The deliberately small allocatable pool is sized from the largest declared
foreground request plus the fixed reserve and 0/32/128 MiB margins. Every
invocation fits alone. It is not a measured production pressure trace.

Pressure occurs in 12/36 F0 trajectories and 0/36 F1 trajectories, with zero
capacity-denied admissions. The two actual 32-to-24 MiB adaptive decreases,
like all pressure observations, occur after target completion. All 24 adaptive
versus fixed128/fixed4096 comparisons have identical full-workflow endpoints;
the small advantage over DRAM therefore cannot be attributed to AIMD. Fixed quotas retain the same live
foreground safety ceiling and reclaim path; their configured targets can
recover when foreground allocations are released. This differs from the older
permanently clamped Static-HBM variant. No adaptation benefit is presumed.

## 4. Placement, queueing, and adverse outcomes

The paper now explicitly reports the original structural 6/10 target and
2/10 cohort adverse cells, the non-preemptive FCFS retry queue, and the
32B low-load retry-placement regression. The independent
`primary-placement-attribution-v2/` analysis binds 90 policy pairs, all 180
original primary completion markers, and every target/cohort identity.
Queue changes are separated from service changes wherever admission is recorded.
Ordinary invocation latency is not mislabeled as measured queue time.

Routing and FCFS remain the implemented design assumptions. Artificially fixing
a retry worker or adding preemption would define another runtime experiment.
Old per-identity causal examples cannot silently be asserted for the new
predictor campaign; they need a new matched check or an explicit old-version
label. Five fixed failures remain descriptive cases without population CIs.

## 5. Healthy DMA cost

`../low-dma-postreview-v1/` adds 24 completed conditions at coefficients
0.002/0.005/0.01/0.02 and references 18 unchanged earlier conditions.
It retains the earlier service proxy and the same four-workflow fault.
The cohort absolute F1 advantage stays positive at these lower tested points,
while healthy overhead remains positive. At 0.05/0.1, even absolute F1 cohort
time is worse. All tested points and both endpoint definitions are retained.

The flow audit reconstructs completed and partially served/cancelled bytes.
Healthy per-host average D2H payload rate includes idle time between first
workflow release and last completion. It is simulated traffic, not physical
copy bandwidth. Mixture break-even probabilities are conditional arithmetic;
the coefficients and probabilities do not estimate production behavior.
No continuous crossover is interpolated.

## 6. Workload and deployment scope

The workload, eight-worker FCFS primary deployment, dense timing profiles,
single-invocation natural replay, and absence of physical calibration remain
limits. The component's native documents do not constitute a second natural
workflow family. Constructed multi-call cases do not establish observed
tool/think gaps or production-scale behavior. We do not infer a known causal
DAG from a different trace and present that inference as recorded truth.

## 7. Preceding claims and manuscript status

The user explicitly froze the manuscript preceding Evaluation. The concrete
`FINAL_CLAIM_CHANGE_PROPOSAL.md` has been presented for permission; no answer
has been received. These changes remain unapplied. Its prediction paragraph
must be refreshed against the new implementation if permission arrives.
The discrepancy between some frozen claims and the available evidence remains
an unresolved paper-level issue, not an approval inferred from silence.

The resource-capacity panel now uses only its existing tested markers, without
connecting lines across the capacity transition. Its 84-row plot data are
byte-identical. `resource-markers-postreview/` records the source changes and
actual-width color/grayscale review. The current paper is still being revised;
the new complete package requires a fresh rendered review and a fresh external
Claude Opus 5.5 review.

## Execution-only amendment

The primary campaign's original two-process host execution limit was amended
to sixteen in `../walltime-primary-v3/execution-amendment-16workers/` after
checking host capacity and independent-job semantics. The original protocol,
seal, frozen source and numeric inputs remain untouched. Sixteen completed jobs
are retained byte-for-byte and two incomplete directories are archived before
retry. A preselected completed All-DRAM/F0 condition was repeated; its summary and
nonempty decompressed event stream are byte-identical. Empty retained flow
logs do not establish flow-level equivalence. Host wall-clock durations under different concurrency
are not compared as controller-overhead evidence. This amendment changes no
simulated condition and adds no independent experimental sample.
