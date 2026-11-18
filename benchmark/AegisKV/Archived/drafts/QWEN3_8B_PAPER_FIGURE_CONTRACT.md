# Qwen3-8B paper figure contract

This document pre-registers the hypotheses, estimands, controls, and evidence
required for AegisKV-versus-Mooncake figures. Desired trends never gate result
publication. Null, adverse, infeasible, and failed cells remain visible.

All primary results use Qwen3-8B, DP=8, TP=1, PP=1, continuous batching,
the complete frozen 160-workflow/1,304-span FanOutQA workload, and exact token
IDs. Timing remains modeled and uncalibrated until a separate physical A100
calibration artifact exists.

## Simulation-only production correction (2026-09-05)

The next production uses five **executed admission permutations**, with the
Peer-placement seed fixed at zero. Seed labels, variant tie-break hashes, and
deterministic repetitions alone do not establish independent sampling. Each
paired arm must record the same complete admission permutation; the five
permutations must be distinct and their hashes are reconstructed before any
seed-level interval is accepted.

For Figure 5, a nested subset of an F8 plan retains the frozen logical focus
IDs and token-progress thresholds. It does not inherit the F8 oracle's physical
target or active/queued victim partition: removing earlier failures changes
those outcomes. The original oracle plan is retained as provenance; measured
sensitivity runs use natural routing and record their realized interventions.
They are robustness contrasts, not identical-physical-state interventions.

Zero Peer availability and zero normal-HBM recovery reuse are valid outcomes.
Neither may block execution, checkpoint reuse, aggregation, or rendering.
Resource conservation, exact pairing and complete failure execution remain
mandatory. Full payloads, span details and representative event streams are
retained in deterministic compressed raw files; compact summaries bind them by
hash and cannot stand alone as evidence of omitted event content.

Algorithm 3 ablation explicitly disables the controller. Its audit must still
verify Algorithm 2, scheduler and resource invariants, require zero AIMD
decisions, and identify Algorithm 3 as disabled rather than claim a full
Algorithms 2/3 pass. Algorithm 2 ablation uses the predeclared LRU control and
must likewise identify formal-landlord checks as not applicable.

## Comparator semantics

The comparator encoded by `vanilla_mooncake_dram` is reported as
**Mooncake proactive Store-only 75% prefix (LRU)**.  It is a strong protection
baseline, not a passive or unprotected Mooncake cache:

- sealed prompt chunks are proactively copied to the 1 TB Store;
- the candidate frontier is a 75% continuous prefix beginning at token zero;
- committed Store copies are eligible for failure recovery;
- retention uses LRU rather than AegisKV Algorithm 2;
- the same cache-aware router and continuous scheduler are used.

AegisKV's Peer 75% and Store 90% values are likewise candidate prefix ceilings
beginning at token zero.  They are nested replicas, not additive 165% token
coverage.  Figures must distinguish available tier prefix from disjoint
selected recovery-source tokens.  Historical artifacts retaining the old
“Vanilla Mooncake DRAM” label must be captioned with these actual semantics.
The baseline may not be weakened after observing results.

## Causal intervention classes

### Primary synchronized single-failure experiment

The primary failure figures use one fresh, fail-closed failure event:

- identical frozen workload and causal releases;
- identical workflow concurrency and experiment seed;
- independently recorded, fixed Peer-placement policy seed;
- identical focus workflow, focus span/request, and rational token threshold;
- the first scheduler-visible threshold crossing only;
- identical frozen physical GPU under natural routing;
- identical detection delay and GPU-unavailable duration;
- no workflow filtering and no legacy schedule;
- no forced route, queue, victim set, or absolute wall-clock synchronization.

The injection timestamp and collateral active/queued victims are measured
post-treatment outcomes. A pair is invalid if workflow, request, threshold,
physical GPU, or outage duration differs.

### Repeated-failure pressure experiment

F=2/4/8 experiments are robustness tests. Later events occur after earlier
treatment has changed routing, cache state, and completion order. They must
report treatment-specific injection times and victim partitions and must not be
described as identical-victim or identical-wall-clock causal interventions.

## Figure 1: workload and intervention validity

**Hypothesis.** The frozen workload contains enough prompt-size and workflow
structure heterogeneity to exercise tiered KV management, while the failure
contract selects the same logical intervention in both systems.

- A: request prompt-token ECDF; x=prompt tokens (log scale), y=request fraction.
- B: requests per workflow; x=span count, y=workflow count or ECDF.
- C: context-bucket population and failure-focus population; include zero 128K
  coverage explicitly.
- D: planned and realized intervention audit: workflow/request identity,
  threshold, physical GPU, injection time, and victim counts by system.

Evidence: workload/manifest hashes, full record count, no-filtering flag,
planned/realized intervention fingerprints, and exact crossing evidence.

## Figure 2: no-failure protection cost

**Hypothesis.** Peer-HBM and Store-DRAM protection add substantial background
traffic but only limited steady-state WCT, makespan, and goodput overhead.

- A: per-seed paired mean workflow WCT difference,
  `AegisKV - Mooncake` in seconds, split into bootstrap/steady/all cohorts.
- B: per-seed makespan overhead and goodput change in percent.
- C: Peer/Store submitted and aborted protection traffic in GiB per run,
  split into bootstrap and steady state.
- D: protection rate or copy-engine busy fraction versus steady-state WCT
  overhead; one labeled point per independent seed.

The independent unit is the shared route-randomization seed. Workflows are
descriptive paired observations, not inferential replicates. The figure reports
all seed points and a paired seed-level interval; no negligible-overhead
threshold suppresses output.

An experiment seed is an independent unit only if it changes a pre-registered
exogenous input to the realized execution, such as a workload admission
permutation or another explicitly defined route-randomization stream.  Merely
serializing a different seed or changing unused/tie-losing diagnostic hashes
does not create an independent replicate.  Before computing a seed-level
interval, the acceptance verifier compares per-seed journal and span-detail
hashes and records which realized decisions differ.  If all realized execution
hashes are identical, the cells are classified as deterministic repeats:
reported for reproducibility, but excluded from inferential CI claims.

Figure 2 derivation is fail-closed:

- The generator verifies the aggregate self-fingerprint and every referenced
  raw artifact SHA-256 before reading transfer-level evidence.
- The paired seed statistic for panel A is the mean of the 160 within-seed
  `AegisKV - Mooncake` workflow deltas.  The primary interval is a two-sided
  Student-t 95% interval over the five seed means (`df=4`); the 800 workflow
  pairs are not treated as independent samples.
- Bootstrap and steady-state seed means use the predeclared 16/144 workflow
  cohorts.  Their intervals are likewise across five seed-level cohort means.
- Panel C derives Peer and Store rows from terminal protection transfers grouped
  by exact cause and by the recorded warmup boundary.  Submitted and aborted
  bytes are both shown; overlapping tier contents are irrelevant because this
  panel measures traffic, not unique protected-token coverage.
- Panel D uses incremental submitted protection bytes divided by the paired
  Mooncake makespan as the configured protection-rate diagnostic, and
  steady-state paired mean WCT delta as the effect.  It labels all five seeds and
  does not fit a regression line.
- The overhead evidence bundle separately reports, per seed and system:
  protection submitted/transferred/aborted bytes and queue/service time;
  Algorithm 2 preview/admit/bypass/defer/evict counts; Algorithm 3
  MD/stable/AI counts and time-weighted alpha; cache-aware route-change count and
  top-two completion-margin distribution; scheduler preemption count,
  preempted request count, and discarded computed/prompt/output tokens.  These
  are attribution diagnostics, not an additive decomposition of WCT: closed-loop
  timing interactions prevent summing them into a unique latency total.
- Missing raw files, hash mismatches, failed formal audits, non-terminal
  transfers, or a seed/cohort cardinality mismatch prevent rendering rather than
  silently reducing the sample.

## Figure 3: primary synchronized failure effect

**Hypothesis.** Under one matched physical failure, AegisKV lowers failure-local
Mean and P95 WCT while causing limited spillover to non-focus workflows.

- A: absolute workflow WCT for Mooncake and AegisKV, split into whole workload,
  pre-registered focus workflow, naturally impacted union, and non-focus cohort.
- B: whole-workload and focus-workflow WCT ECDFs; pooled curves are descriptive.
- C: primary per-seed focus-workflow failure-penalty difference-in-differences,
  `(AegisKV_failure - AegisKV_no_failure) -
  (Mooncake_failure - Mooncake_no_failure)`, with interval and zero reference.
- D: secondary per-seed whole-workload mean failure-penalty
  difference-in-differences with interval and explicit population size. Raw
  failure-run Mean, nearest-rank P95, and Max remain mandatory descriptive
  safety outcomes in the campaign artifact.

The pre-registered focus cohort is primary. The impacted union is
post-treatment and descriptive. Report absolute values together with relative
effects so a percentage cannot hide the denominator.

Whole-workload Mean or P95 improvement is not sufficient evidence of a direct
recovery benefit.  Figure 3 must be cross-checked against Figure 4.  If restored
tokens, recomputed tokens, recovery-ready time, and failed-request completion
are unchanged, the cell is labeled a routing/scheduling redistribution
counterexample even when aggregate Mean or P95 improves.  Max WCT, paired
winner/tie/loser counts, and the worst collateral workflow remain mandatory so
tail regressions cannot be hidden by aggregate percentiles.

## Figure 4: recovery mechanism

**Hypothesis.** Peer/Store KV recovery can substitute a faster source for
Store-only recovery and reduce failure-relative recovery-ready latency;
transfer queueing, silent replay, and resumed inference explain cases where the
saving does not reach workflow completion. Reduced prompt recomputation is
claimed only when the measured recompute-token count decreases.

- A: failure-to-completion timeline by request, decomposed into detection,
  reroute setup, KV recall, retry queue, prompt recompute, silent replay queue,
  silent replay, activation gap, and resumed inference.
- B: prompt-token fractions from local HBM, Peer local activation, Peer D2D,
  Store DRAM, and recompute; fractions must sum to one.
- C: recomputed prompt fraction versus recovery-ready latency with matched
  system pairs.
- D: recovery-ready latency versus failure-to-request-completion latency.

Rows are selected only by a predeclared identity rule (all focus requests or a
fixed event/index), never by observed gain. Token and phase conservation must
pass before rendering.

The direct mechanism is considered exercised only if at least one predeclared
focus request has either fewer recomputed prompt tokens or an earlier
recovery-ready timestamp than its matched Mooncake request.  This is a
classification rule, not an effect-direction gate: cells that fail it are still
published, but as source-substitution/null-mechanism counterexamples rather
than evidence for the theoretical recovery chain.

For every cell, report both:

- direct-path quantities: source-token composition, recompute, materialization,
  scheduler admission, recovery-ready, and failed-request completion; and
- downstream quantities: first selected-route divergence, top-two estimated
  completion margin, number of later route changes, workflow winner/tie/loser
  counts, P95 identity, Max identity, and worst collateral delta.

A near-tie margin is diagnostic evidence only.  No route hysteresis constant may
be chosen from an observed result; any future stability policy must derive its
band from a predeclared scheduler quantum or independently measured prediction
error bound and must retain the original policy as a reported control.

### Pre-registered overlapping-source selection

Recovery-source optimization may change only which committed replica supplies
an already-covered token position.  It must not change protection admission,
the effective continuous prefix, recompute suffix, recovery destination,
failure plan, focus identity, or workload.

Two complete interval assignments are evaluated:

- `PEER_FIRST_CONTROL`: Normal HBM, then Peer, then Store.  This reproduces the
  current source-priority policy and remains a required control.
- `STORE_FIRST`: Normal HBM, then Store, then Peer for any remaining suffix.

Both candidates must cover exactly `[0, E)`, where
`E = max(normal_prefix, peer_prefix, store_prefix)` after clipping to the prompt,
and must recompute exactly `[E, prompt_tokens)`.  An assignment whose intervals
cannot be represented on the committed source boundaries is retained as
infeasible rather than shrinking `E`.

The pre-registered latency-aware selection key is:

1. feasibility;
2. estimated scheduler completion;
3. estimated scheduler admission;
4. estimated prefix materialization;
5. total transferred bytes;
6. `PEER_FIRST_CONTROL` as the exact-tie winner.

Candidate evaluation must be side-effect free: it may not advance the DES,
consume IDs, mutate flow state, pools, ledgers, hit counters, journals, pending
transfers, routing, or scheduler queues.  Every candidate and its configured
path capacities, transfer bytes, interval ownership, estimate scope, and
selection key must be emitted before the selected transfer is committed.

The initial estimator is explicitly limited to
`snapshot_active_flows_plus_candidate_no_future_arrivals`.  Scheduler gating is
estimated from the current target-load shadow.  These are deterministic E2
model estimates, not exact forecasts under future flow arrivals and not
calibrated hardware measurements.  Figures must compare the latency-aware mode
against `PEER_FIRST_CONTROL`, preserve null/adverse outcomes, and report whether
the selected strategy changed only source ownership or also the realized
critical path.

## Figure 5: failure and concurrency sensitivity

**Hypothesis.** Failure intensity exposes more protected state, while higher
concurrency raises HBM pressure and may reduce effective protection; neither
trend is required to be monotonic.

- Failure column: F={1,2,4,8}, C=16.
- Concurrency column: C={8,16,24,32}, F=2.
- Rows: absolute focus Mean WCT, focus Mean effect, focus P95 effect, focus and
  impacted counts, AIMD alpha/pressure rate, and selected Peer/Store fractions.

Each point is a seed-level paired observation. Lines summarize observed points
only; no smoothing, projection, or monotonic fit is allowed.

## Figure 6: cost-benefit frontier and counterexamples

**Hypothesis.** More protected or restored KV is not sufficient for lower WCT
when placement, queueing, and resumed inference dominate.

- A: protection GiB/run versus focus Mean WCT effect.
- B: restored prompt fraction versus focus P95 WCT effect.
- C: Algorithm 1/2/3 ablations versus full AegisKV with all seed points.
- D: the five lowest valid paired effects selected by a fixed ascending-effect
  rule, labeled with seed, F, C, focus ID, and artifact hash prefix.

Negative and null points must be labeled, not omitted.

The Algorithm 1/2/3 ablations are fixed before the Figure 6 experiment:

- Algorithm 1: `no_slack`, disabling the residual-DAG slack signal while
  retaining the other AegisKV mechanisms.
- Algorithm 2: `lru_eviction`, replacing SlackLandlord retention with LRU while
  retaining the same protection fractions and other mechanisms.
- Algorithm 3: `no_aimd`, disabling HBMQuotaAIMD while retaining the full
  protection and retention policy.

These mappings are not interchangeable with the diagnostic
`no_reuse_value`, `no_recovery_value`, `two_managers`, or static-quota controls
and must not be changed after observing experiment outcomes.

The full-160, seed-0, F=1 artifact with fingerprint prefix `9f895570` is
pre-registered as a retained counterexample: 36,928 Peer tokens replace Store,
while total restored tokens, recompute, recovery-ready latency, and failed
request completion remain unchanged.  Its aggregate Mean/P95 improvements and
Max regression therefore belong to the closed-loop redistribution analysis,
not the direct-recovery claim.  This historical artifact predates native
near-tie and exclusion-reason fields; reconstructed evidence must be labeled as
such and must not be attributed to the newer implementation fingerprint.

## Figure publication and provenance

Every figure must be emitted as PNG, SVG, and PDF and its manifest must include:

- scientific hypothesis and expected causal chain;
- estimand, sign convention, population, and independent sampling unit;
- x/y/series definitions and unit conversions;
- held-constant variables and varied dimension;
- workload, config, implementation, schedule, result, generator, and output
  hashes;
- CI method, sample size, and any multiplicity or leave-one-seed-out analysis;
- subset/representative selection rule;
- missing, failed, infeasible, null, and adverse cells;
- `modeled_uncalibrated=true`, `physical_execution=false`, and
  `paper_ready=false` until separate calibration and physical validation pass.

Visual inspection must confirm readable publication-size labels, no overlap,
and captions that explain the mechanism behind each observed trend or
counterexample.

## Artifact acceptance and Canvas ingestion

The plotting and Canvas layer may consume a cell only after the following
ordered checks.  A later check cannot compensate for a failed earlier check.

1. Verify the document status, schema, self-fingerprint, embedded compact/full
   hashes, and referenced raw artifact hashes.
2. Verify the implementation/source-contract fingerprint against the exact
   source snapshot claimed by the cell.  Historical cells remain usable only as
   explicitly labeled historical diagnostics.
3. Verify the complete frozen workload and manifest hashes, 160 workflow and
   1,304 span counts, exact token IDs, and `workflow_filtering=false`.
4. For primary failure cells, verify one fresh paper-causal event, identical
   focus workflow/request/progress, frozen physical GPU, and outage duration.
   Verify each system's first-crossing injection timestamp and exact
   active/queued/reroute-only victim partition separately. These are
   post-treatment outcomes: they must be present and internally valid, but
   must not be required to match across systems.
5. Verify prompt-token conservation, output audit, HBM/Store capacity ledgers,
   pending bytes at termination, continuous scheduler evidence, and formal
   Algorithm 2/3 evidence when applicable.
6. Run the direct-recovery classifier.  This classifies rather than filters:
   direct benefit, source substitution/null, and adverse direct mechanism all
   remain renderable.
7. Recompute paired WCT statistics and nearest-rank percentile identities from
   raw per-workflow/per-request values; do not trust a chart-input summary alone.
8. Register every attempted cell as valid, failed, infeasible, stale,
   historical, null, or adverse.  Only valid cells enter numerical aggregates,
   but all other categories and their reasons appear in the figure manifest and
   Canvas evidence ledger.

The ordered checks above must be materialized by one machine-readable acceptance
manifest rather than reimplemented independently by each plot or Canvas.  The
manifest contains:

- `attempt_id`, scenario dimensions, artifact path/hash/fingerprint, and
  implementation/config/workload/schedule bindings;
- one ordered record for gates 1--8 with `PASS`, `FAIL`, or `NOT_APPLICABLE`,
  the verifier name/version/hash, and exact evidence or rejection reasons;
- terminal registration class from
  `VALID`, `FAILED`, `INFEASIBLE`, `STALE`, `HISTORICAL`, `NULL_DIRECT`,
  `MIXED_DIRECT`, or `ADVERSE_DIRECT`;
- recomputed seed/workflow/request statistics and percentile identities, never
  only references to aggregate values embedded by the producer;
- direct-classifier output and hash for failure cells;
- every figure and Canvas panel ID allowed to consume the attempt;
- an overall self-fingerprint covering the ordered gates and all referenced
  hashes.

Plot generators consume only `VALID`, `NULL_DIRECT`, `MIXED_DIRECT`, or
`ADVERSE_DIRECT` accepted attempts.  The latter three remain valid numerical
observations and differ only in mechanism interpretation.  `FAILED`,
`INFEASIBLE`, `STALE`, and `HISTORICAL` attempts appear in the evidence ledger
but cannot enter current-fingerprint numerical aggregates.  A plot generator
must reject a raw result artifact supplied without its acceptance manifest.

For failure attempts, the registry binds a separately generated schema-v2
direct-recovery classifier by repository-relative path, file SHA-256, and
self-fingerprint.  Gate 4 consumes its fail-closed shared physical
failure-contract checks; Gate 6 consumes its four-class result and verifies that
all valid cells were retained without an effect-direction filter.  A valid
single-seed primary failure is direct-mechanism evidence for Figure 4B--D, but
does not authorize Figure 3 Mean/P95 aggregate panels or any seed-level
confidence interval.  Figure 3A--D authorization requires reconstructed paired
workflow statistics from at least two independent failure seeds.  Figure 4A
remains unauthorized until the acceptance artifact contains and verifies the
full decomposed request timeline required by that panel.

A five-seed primary-failure campaign is registered as the distinct
`FAILURE_CAMPAIGN` scenario kind. Its terminal rule is campaign-level rather
than a collapse of the five mechanism classes: it is `VALID` only when seeds
0--4, all source artifacts and classifier hashes, the full unfiltered workload,
five distinct paired admission orders, every per-seed causal/selector contract,
all four-class retention declarations, and reconstructed Mean/P95/Max
Student-t inference pass. Mixed, null, adverse, and concordant seeds coexist
inside that one valid campaign; no workflow or effect-direction filtering is
permitted. A one-seed artifact remains a `PRIMARY_FAILURE` observation and
cannot masquerade as campaign inference.

Failure-campaign figures require `--acceptance-manifest`. The generator binds
the exact campaign file SHA-256 and self-fingerprint to exactly one `VALID`
`FAILURE_CAMPAIGN` attempt, requires ordered Gates 1--8 to be pass/applicable,
and renders only the intersection of requested panels, the campaign's declared
set, and Gate 8 `allowed_panel_ids`. The campaign's internal `acceptance`
object is not sufficient authorization. Figure 4A remains unauthorized.

The Canvas must embed the accepted values and their hashes directly; it may not
fetch mutable files at render time.  Each panel records:

- artifact and implementation fingerprint prefixes;
- scenario, seed, Peer seed, concurrency, failure count/progress, and focus ID;
- estimand, population, sign convention, percentile rule, and independent unit;
- mechanism classification and whether route margins were native or
  reconstructed;
- source paths and generator/output hashes;
- `modeled_uncalibrated=true`, `physical_execution=false`, and
  `paper_ready=false` until separate calibration and physical validation pass.

Canvas headline text may not summarize an aggregate WCT gain as a recovery gain
when the direct-mechanism classifier is null or adverse.  In that case the
headline must name the source-substitution or routing/scheduling redistribution
counterexample and show the conflicting Max/collateral evidence beside Mean and
P95.

The final direct-recovery classifier is fail-closed and multi-axis.  Before
classification it verifies the input artifact self-fingerprint, one fresh
paper-causal failure, no frozen post-treatment victim contract, exact focus
identity in both systems, per-system realized timestamps/victim partitions,
and prompt-token conservation. It reports the signs of recompute,
prefix-materialization, recovery-ready, and failed-request-completion deltas
separately.  The classification set is:

- `DIRECT_RECOVERY_BENEFIT_CONCORDANT`: recompute does not increase,
  recovery-ready does not regress, and at least one is strictly better;
- `DIRECT_RECOVERY_MIXED`: at least one direct-path quantity improves and at
  least one regresses;
- `SOURCE_SUBSTITUTION_OR_NULL_DIRECT_MECHANISM`: recompute and recovery-ready
  are both unchanged;
- `ADVERSE_DIRECT_MECHANISM`: neither direct criterion improves and at least one
  regresses.

Failed-request completion is a downstream outcome and does not change the
direct-path class.  It is reported as propagation, masking, or reversal
evidence.  No class is an effect-direction filter.

## Current completion ledger

### Five-seed primary-failure campaign artifact

The current `e2-qwen3-8b-paper-f1-v11-seed{0..4}.json` production path is
aggregated by
`benchmark/AegisKV/experiments/scripts/build_qwen3_8b_failure_campaign.py`.
The builder consumes exactly seeds 0--4, generates a missing schema-v2 direct
classifier beside each input (or validates an existing one), and writes one
`moonkvsim.aegiskv.qwen3_8b.failure_campaign.v1` artifact.

The campaign fails closed unless all five artifacts:

- are self-fingerprinted PASS paper-causal, single-failure, full-workload runs;
- bind the same implementation, compared variants/configuration, frozen
  workload, failure protocol, and fixed Peer-placement seed;
- contain the exact paired 160-workflow WCT maps and the same realized
  admission order in both systems;
- use five distinct seeded admission orders when inferential uncertainty is
  requested;
- pass the per-seed shared schedule, frozen target, impact-contract, observed
  victim, focus-progress, token-conservation, and timestamp classifier checks;
- contain exactly one `RECOVERY_SOURCE_SELECTION` event for the focus request
  in each system, with both `PEER_FIRST_CONTROL` and `STORE_FIRST`, the
  pre-registered selection key and prediction scope, complete fixed-prefix
  intervals, and all source-ownership-only invariance assertions.

Every seed is retained after validation, including concordant, mixed, null, and
adverse direct classes. The artifact embeds complete WCT maps, paired workflow
deltas and descriptive within-seed distributions, nearest-rank P95/Max
identities, winner/tie/loser counts, worst collateral effects, exact causal
contracts, direct quantities, selector predictions, and realized source
composition. Mean/P95/Max confidence intervals use the five seed-level
estimands as the inferential observations; the 800 workflows are never treated
as independent replicates.

The accepted campaign authorizes Figure 3A/C/D and Figure 4B/C/D. Figure 4A is
explicitly omitted with
`FULL_EXCLUSIVE_FAILURE_TO_COMPLETION_PHASE_DECOMPOSITION_NOT_PROVEN`; compact
postfix evidence does not establish the required exclusive phase
decomposition.

The paper generator
`benchmark/AegisKV/experiments/results/figures/generate_qwen3_8b_failure_campaign_figures.py`
accepts only this self-fingerprinted campaign together with the unified
eight-gate acceptance manifest and rejects any panel not authorized by both
the campaign and manifest Gate 8. It emits PNG, SVG, and PDF for every
rendered panel plus a self-fingerprinted `FIGURE_MANIFEST.json` containing
campaign, generator, and output hashes. Panels retain zero lines,
counterexamples, mixed/null/adverse classes, losers, and collateral
regressions; no direction filter is permitted.

Production commands, after all five runs complete:

```bash
uv run --extra paper python \
  benchmark/AegisKV/experiments/scripts/build_qwen3_8b_failure_campaign.py \
  --output benchmark/AegisKV/experiments/results/e2-qwen3-8b-paper-f1-v11-campaign.json

uv run --extra paper python \
  benchmark/AegisKV/experiments/results/figures/generate_qwen3_8b_failure_campaign_figures.py \
  --campaign benchmark/AegisKV/experiments/results/e2-qwen3-8b-paper-f1-v11-campaign.json \
  --acceptance-manifest benchmark/AegisKV/experiments/results/e2-qwen3-8b-paper-f1-v11-acceptance.json \
  --output-dir benchmark/AegisKV/experiments/results/figures/qwen3-8b-paper-f1-v11
```

This ledger is descriptive and must be updated from current-state evidence
before claiming completion.

- Synchronized single-failure contract: implemented and unit-tested; one
  full-160 historical artifact passes and is retained as a direct-mechanism null
  counterexample.  A current-code audit found one remaining primary-experiment
  blocker: `paper_causal_mode` rejects multiple failures and unfrozen physical
  targets, but still accepts `profile_impact_contracts` when Mooncake and
  AegisKV have different post-treatment active/queued/reroute-only victims.
  The primary synchronized single-failure path must reject that case and require
  one shared `impact_contract`; profile-specific contracts remain admissible
  only for explicitly labeled sensitivity diagnostics.
- Direct recovery classification: implemented; the historical F=1 artifact is
  classified as source substitution/null rather than direct recovery benefit.
  The current v1 classifier is not yet the final acceptance gate: it treats any
  single-axis improvement as generic direct benefit and does not independently
  verify the input self-fingerprint, shared impact contract, or token
  conservation.  It must be upgraded to the concordant/mixed/null/adverse
  matrix above before current-fingerprint failure cells are accepted.
- Comparator semantics: machine-readable and relabeled as proactive Store-only
  75% prefix (LRU); historical labels require corrected captions.
- No-failure overhead: `paper-v4` completed all ten simulations but was rejected
  by the formal gate.  It exposed two defects rather than producing a usable
  aggregate: foreground pressure performed immediate AIMD MD despite the fixed
  control-window contract, and an Algorithm 2 preview rejected by the later
  foreground-headroom gate could be mistaken for an applied rent transition.
  Pressure is now latched until the next fixed GlobalDES control window and
  preview evidence carries `landlord_applied`; the affected regression suite
  passed 129 tests.  The fresh-source-fingerprint `paper-v5` campaign completed
  all ten cells and passed schema, self-fingerprint, ten raw-artifact hash, and
  built-in audit checks (aggregate fingerprint prefix `46fcd8b8`).  It measures
  AegisKV minus Mooncake as -0.336043 s mean workflow WCT, +0.1864% makespan,
  -0.1867% goodput, and +1,791.984 GiB submitted protection traffic per run.
  However, every seed has identical journal and span-detail hashes within each
  system and identical metric values.  Thus seeds 0--4 are deterministic
  repeats, not independent route-randomization samples; their zero-width
  Student-t interval is invalid as uncertainty evidence.  v5 is retained as an
  accepted deterministic no-failure result/reproducibility observation, while
  independent no-failure sensitivity remains missing.  A new fail-closed
  admission-randomization protocol now orders equal-eligibility workflows by
  `SHA256("workflow-admission:" || seed || workflow_id)`, applies the exact same
  realized order to Mooncake and AegisKV within each seed, and holds Peer
  placement fixed.  The aggregate records and verifies each realized order and
  its hash, requires five distinct hashes, and rejects paired-system order
  divergence.  v7 was invalidated by later source changes; v8 exposed the
  prefill/decode boundary and terminal pending-pressure audit defects; v9
  exposed prompt-boundary chunk-flag drift; and v10 exposed multi-token decode
  scheduling outside the ordinary decoder-only contract.  All four are retained
  as rejected/stale attempts.  `paper-v11` is the current-fingerprint campaign.
  No rejected, stale, aborted, or unvalidated snapshot may enter current
  uncertainty figures.
- Failure/concurrency/progress sensitivity: runner dimensions exist, but the
  complete current-fingerprint matrix and seed-level uncertainty are missing.
- Latency-aware overlapping-source selection: implemented with side-effect-free
  Peer-first-control and Store-first predictions, pre-registered lexicographic
  selection, and per-request audit evidence; current accepted artifacts are
  still pending.
- Paper figures: the fail-closed Figure 2 generator now requires both the
  self-fingerprinted PASS five-seed overhead artifact and its eight-gate
  acceptance manifest.  It verifies exact artifact hash/fingerprint binding,
  panel authorization, paired admission randomization, and five distinct
  realized-order hashes; reports two-sided Student-t 95% intervals across five
  seed-level values (`df=4`); splits submitted traffic into bootstrap/steady
  phases, shows total aborted traffic without inventing an unavailable
  phase-level abort split, uses steady-state WCT in the cost/effect panel, and
  emits hashed PNG/SVG/PDF files.
- Unified acceptance verifier: implemented with eight ordered fail-closed gates,
  explicit terminal classes, raw/source/config/workload binding, direct
  classifier consumption, and panel authorization.  Final v11 artifacts still
  need to be registered and accepted before Figure or Canvas ingestion.
- No-failure attribution: implemented in the acceptance verifier by
  reconstructing and binding protection traffic, Algorithm 2/3 events, routing,
  and scheduler-preemption token/phase diagnostics from referenced raw
  artifacts.  The evidence is explicitly `DIAGNOSTIC_NON_ADDITIVE`; it does not
  claim these counters sum to the observed WCT change.
- Canvas: the audited historical F=1 counterexample page exists; current
  no-failure, sensitivity, direct-benefit, and final completion evidence are not
  yet present.
- Calibration/physical validation: missing by design; all current results
  remain E2 modeled, uncalibrated, and `paper_ready=false`.
