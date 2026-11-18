# Qwen3-8B simulation paper completion plan

Started: 2026-09-05. Status: completed within the authorized simulation-only scope.

## Authorized objective

Use the current MoonKVSim implementation to execute simulations, produce all
scientifically justified paper figures, and deliver a complete submission-ready
paper. Scope is Qwen3-8B, DP=8, TP=1, PP=1, simulation only. Physical inference,
physical timing calibration, and Qwen3-32B TP/PP are outside this delivery.
Negative and null results must remain visible. Submission-ready does not mean
accepted, physically validated, or demonstrated performance dominance.

The existing EuroSys format is retained: at most 12 technical pages, references
additional; at least 10 pt figure/body text and 12 pt leading; anonymous review.
Source checked 2026-09-05: https://2027.eurosys.org/cfp.html .

## Required deliverables and evidence

1. **Implementation:** complete Algorithms 2/3 in the executed simulator;
   document ideal-CPM Algorithm 1, scheduler, transfer and duration assumptions;
   pass relevant regression, typing and lint checks before freezing execution.
2. **Frozen experiments:** immutable code/config/workload snapshots and hash-bound
   resumable raw results. Five distinct paired admission seeds, complete 160
   workflows / 1,304 spans, no outcome-based seed or workflow filtering.
3. **Figures 1--4:** workload/intervention validity, no-failure protection costs,
   failure effects and recovery mechanism. Use injection-relative durations and
   paired failure/no-failure estimands. Do not claim an exclusive phase
   decomposition without non-overlapping raw intervals.
4. **Figure 5:** the predeclared F={1,2,4,8}, C=16 and C={8,16,24,32}, F=2 matrix;
   seven points by five seeds, complete paired observations or explicitly
   recorded infeasibility. Preserve natural routing and intervention differences.
5. **Figure 6:** full versus no_slack, lru_eviction, no_aimd under a fixed logical
   intervention; protection cost and restored fraction with exact denominators;
   deterministic counterexample reporting. No selection on desired gains.
6. **Model robustness:** analytical checks and sensitivity to uncalibrated timing
   assumptions needed for the actual claims. Numerical simulation precision is
   not physical accuracy. Observed FanOutQA context tops out at 86,214 tokens;
   the 128K bucket is empty and must remain explicit.
7. **Manuscript:** self-contained abstract through conclusion, current-model
   methods/limitations, verified primary related-work sources, all claims tied
   to current artifacts. Exclude legacy SGLSim/projection/32B outcomes from the
   active empirical evaluation. Preserve the old manuscript as historical input.
8. **Delivery audit:** rebuildable TeX and PDF, regenerated vector figures/data,
   statistical and provenance checks, citation/reference resolution, technical
   page count, grayscale legibility, and visual inspection of every PDF page.
   A requirement-by-requirement completion report must contain no open required
   item before the active goal is marked complete.

## Initial evidence and next actions

- Baseline tag resolves to f2684c2b692c381f9e7db24ef808deb7551d62fc.
- Working checkout HEAD b108867 has extensive pre-existing uncommitted work.
- v13 primary campaign retains a small adverse whole-workload mean and an
  inconclusive focus-workflow effect; these are useful findings, not reasons to
  alter the comparator or suppress seeds.
- No-failure v12 is stale against current source and needs replacement.
- Figure 5 acceptance exists; Figure 6 execution/acceptance is incomplete.
- Before executing, remove any remaining gates that require a nonzero recovery
  benefit or tier hit. Resource/correctness gates remain mandatory.
- Freeze in a separate reproducible execution snapshot; do not commit unrelated
  user work or erase historical results.

## Work log

- Current execution is **source-v3 / runs-v3**, commit
  `0878c9eabf60ede00cbbb8ef27e0c4fdbf90c931`, 349 copied/hash-verified files.
  Frozen-tree focused checks: 100 passed. C32 seed-1 F0 exposed an AIMD
  early-return bug after canceling pending PUTs: their physical HBM charge
  was not released when quota contraction was blocked. The targeted test
  failed before the fix, eight controller regressions pass, and the exact
  complete 160-workflow replay now passes. Preserve source-v2/runs-v2 as
  superseded diagnostic evidence, excluded from final numerical results.
  Only this task's verified v2 process groups were terminated; identities
  and commands are retained in runs-v2/termination.json.
- Primary F0/F1 runs now retain complete compressed payloads, scheduler and
  resource event streams alongside compact artifacts. Central acceptance
  reconstructs all 20 runs, validates frozen source/config/workload bindings,
  and reruns scheduler/policy checks. New ablation/timing acceptance covers
  complete raw evidence; sensitivity acceptance also rebuilds cost/effect
  diagnostics and the five lowest exact paired effects. Every verifier gate
  records the source-package hashes captured before auditing; source mutation
  during an audit rejects the result.
- Figure 6/7 generators now require panel-specific VALID acceptance and
  render at final 7-inch width with at least 10-point labels. They have not
  yet rendered empirical figures because final v3 acceptance is pending.

- 2026-09-05: inspected current scope, manuscript, runner, acceptance and figure
  gaps; initiated focused regression checks. No new paper experiment yet.
- 2026-09-05: repaired Figure 5 admission-seed wiring, removed outcome-based
  zero-hit exclusions, and relaxed inherited physical/victim constraints in
  nested sensitivity schedules. Complete compressed raw runs now back the
  Figure 5 audit; compact summaries and scheduler/policy reports are rebuilt
  against the raw evidence.
- Added four-arm F0/F1 ablation runner, complete raw retention and checkpoint
  reconstruction, seed-level DiD statistics, and explicit no-AIMD/LRU audits.
  Focus prompt tokens use a conserving disjoint-tier denominator.
- Validation: 125 targeted paper tests passed; Ruff passed for changed code;
  mypy passed for six execution/acceptance modules. Broad first regression:
  1063 passed, 18 failed, 25 setup errors, 1 skipped. Fixed obsolete KV-layout
  fixture hashes, hard-coded 10% failure fixtures, and auditor compatibility
  with explicit target/victim semantics. Subsequent failed-test rerun:
  39 passed, 4 deselected; separate experiment-suite rerun: 8 passed.
  External pinned Mooncake C++ metadata oracle still lacks its old dependency
  include environment (ylt then msgpack); this is not a GPU/inference run.
- Frozen execution source: output/paper-simulation-8b/20260905/source-v1,
  336 verified copied files, Git commit
  445fdf1a9b52d9e814a55f9b1cfc94797e0a377b. Source tree clean at launch.
  Later experiment-suite changes repair test fixtures only and do not change
  this execution snapshot or its runtime code. Preserve the snapshot.
- Launched eight supervised tasks under
  output/paper-simulation-8b/20260905/runs-v1: no-failure (5 workers),
  sensitivity (8), ablations (5), and primary F1 seeds 0--4 (2 workers each).
  execution.json records commands/PIDs/status; each task has its own log.
  First five Store-only no-failure runs completed their producer audits;
  AegisKV partners and failure-plan oracles are still running. No new aggregate
  performance claim has been accepted yet.
- Added simulation-8b manuscript methods/experimental-method/related-work
  sections and a verified primary-literature ledger. Rendered and visually
  checked the descriptive two-panel workload PDF/SVG/PNG with exact chart
  data and hashes. Remaining figures still depend on accepted new runs.
- No-failure v1 completed all ten measured runs and published its producer-PASS
  aggregate. Independent reconstruction of the complete raw evidence is running.
  Sensitivity v1 failed in the C32 seed-0 first failure trial. An instrumented
  replay of the same recorded focus reproduced the error: one pinned inactive
  64-token source chunk was advertised as reclaimable scheduler capacity, despite
  the primary pool having zero evictable bytes. Keep both failure records.
- A separate regression exposes double counting after partial adoption of a
  resident interval. Both repairs are staged outside the immutable source-v1;
  29 HBM authority tests pass. The original C32 intervention and broader scheduler
  tests are being rerun. Existing v1 primary and ablation jobs continue and retain
  their original provenance. Do not silently combine them with a corrected run.
- The five-page working manuscript now compiles. No complete-results claim or
  submission-ready designation is made. A four-panel Figure 2 compositor is
  authored, but requires independent acceptance before rendering empirical data.
- Confirmed a third HBM bug with a runtime regression: shared inactive backing
  lost its pin at adoption while active logical readers still referenced it.
  Pins now last until scheduler retirement/preemption, rollback, or GPU loss.
  The full 160-workflow C32/F1 diagnostic passed after all three HBM repairs,
  with the original logical focus/progress and natural target resolution.
  v1 managed jobs were stopped; termination.json records the exact 22 verified
  campaign processes. Preserve all old artifacts, but exclude them from final
  empirical evidence. The separate pilot had already failed at its overly
  strict LRU event-stream audit; its retained raw run now passes the corrected
  audit (440 AIMD decisions). Generic foreground reclaim events are allowed;
  formal landlord decisions remain forbidden for LRU.
- Added predeclared batching-assumption robustness: beta={0,500,1000} mixes
  max/sum participant shares, with the same composition in execution and route
  estimates. It is not a physical latency bound or calibration. The runner uses
  one full-default logical F1 focus across six policy/model arms, each with F0,
  for 60 measured runs across five paired seeds. Added source-bound variants,
  exact token conservation, paired DiD and relative-focus statistics.
- Current checks: 117 HBM/timing/policy/statistics tests and 116 runner/config/
  artifact integration tests passed; four changed modules passed mypy; nine
  changed modules/tests passed Ruff. An earlier v2a scheduler/experiment run
  passed 202 tests in 1312.07 s, before the final pin-lifetime/timing edits.
  The monolithic experiment.py retains five pre-existing lint findings.
- Frozen corrected source-v2: 340 verified files, commit
  672e604d8fb7b28197ce078f4b5cdeea714b378b, clean at launch. Nine supervised
  tasks are running in runs-v2: no-failure, sensitivity (20 workers), ablations,
  timing robustness, and primary seeds 0--4. Do not edit this snapshot or mix
  its outputs with v1. All final acceptance/figures/manuscript results remain
  pending this corrected campaign.

## 2026-09-05: immutable independent analysis and figure contract completion

- Frozen analysis-v2 `9928aa771e161029c45cb3375a2dc98d03fa414d` adds bounded parallel independent raw checks. Main checks: 76 passed; frozen snapshot checks: 60 passed; three audit modules pass mypy. Runtime source-v3 remains unchanged.
- Audit watcher PID 1329782 uses explicit source-v3 source bindings and immutable analysis-v2. F0 producer completed all 10 runs; independent acceptance PID 1367047 started at 07:26:52 UTC. Other v3 studies continue.
- Figure 1 four-panel compositor now includes workload and focus populations plus seed-level planned/realized intervention audit. Figure 2 now reconstructs Peer/Store traffic separately and uses the predeclared Store-only-makespan rate denominator. Both await final accepted data/rendered review.
- Figure 2 tier reconstruction was checked against two complete raw files from one superseded v2 seed; totals and warmup phases matched. This is a diagnostic of analysis code, not accepted v3 numerical evidence.
- Expanded manuscript model/parameters/intervention semantics; table overflow fixed and rendered page inspected. Manuscript remains incomplete pending final results. Official GhostServe/RaidServe PDF page counts verified; unverified proceedings page ranges removed.

## 2026-09-05: accepted healthy-serving result and complete-batch endpoint

- V3 no-failure independent acceptance completed VALID at 08:04 UTC. Figure 2 was generated from the accepted aggregate and complete raw transfer records, then repaired to remove a legend/bar overlap. Native and manuscript-embedded text is at least 10 pt. All eight current PDF pages were rendered and inspected; `output/paper-simulation-8b/20260905/figure-review.json` binds this review to exact output hashes.
- The healthy-serving section reports a mean WCT difference of -0.137 s (95% interval -0.297 to +0.024 s), near-zero average makespan change, and 66.3% additional submitted protection traffic. It also retains 304 adverse paired task-runs and the worst +48.342 s case; near-zero mean is not treated as per-task safety or statistical equivalence.
- All five primary seed producers exited successfully; independent primary raw audit started at 08:05 UTC and remains live. Sensitivity, ablation, and service-model studies continue. Both source-v3 and analysis-v2 Git snapshots remain clean.
- Clarified closed-loop admission: WCT excludes waiting for an admission slot. Added a fail-closed primary makespan supplement that requires full primary acceptance, then reconstructs all 20 complete span populations and verifies batch start zero, completion maxima, output counts, raw bindings, and source hashes. Supervisor PID 1627826 waits for primary acceptance; no supplementary numerical claims have been accepted yet.
- Updated foundational CPM, Landlord, and AIMD references from primary publisher/author metadata. Figure 6 adverse cases will display full workflow IDs and both policies' completion times; full request identities and raw hashes remain in its sidecar. Result captions now have individual files so each figure is included only after its own acceptance and visual review.

## 2026-09-05: healthy adverse-case mechanism and reproduction instructions

- Reconstructed the maximum adverse healthy task across all 800 paired task-runs from both accepted complete raw records. Its 27-call DAG ends 48.342 s later under AegisKV: final-call release is 16.961 s later relative to task start, and final-call latency increases by 31.381 s. Both final calls reuse exactly 64 normal-HBM tokens.
- Verified all final-call scheduler steps, zero-based output positions 0 through 139, nonoverlapping step intervals, and the exact maximum of all participant service shares. The call waits less before its first step under AegisKV (2.258 vs 4.761 s), but its participating-step duration rises from 8.082 to 41.966 s; there are no inter-step gaps. It participates in 108 mixed-phase steps versus 20. This is a conditional model diagnosis, not isolated causality or physical latency evidence.
- Added `build_simulation_healthy_case.py` and the hash-bound `runs-v3/healthy-worst-case.json`; Ruff passes. The manuscript now explains this case. It remains eight pages; changed pages 5-8 were rendered and inspected with no overflow.
- Added `simulation-8b/REPRODUCE.md` with preserved input identities, exact fresh-run parameters, acceptance and figure provenance, and build commands. All shell blocks pass `bash -n`; they were not executed to duplicate the active simulations.

## 2026-09-05: accepted primary experiment and manuscript integration

- Primary V3 independent acceptance completed all eight gates at 09:18 UTC, with terminal class VALID. Acceptance SHA-256: `60d054294d8bce50d70843154be97dad45944e6808fd10168bebaa8de52eb90d`.
- The complete-batch supplement reconstructed all 20 full span populations and finished successfully. Its result SHA-256 is `a2a91b7a545be40cde6b962c5a4730cb4702798ebf3de18d971eb8cd6dbfc4ee`. The primary F1 makespan difference is +1.022 s, CI [-0.871, 2.915]; the makespan failure-penalty difference is +0.994 s, CI [-1.468, 3.456].
- Integrated Figures 1, 3 and 4 plus the primary outcome and direct-mechanism sections. Repaired overlapping workflow/request IDs in Figure 1 by giving each its own column; shortened Figure 3's clipped axis label. Added explicit nonzero abort-volume labels to Figure 2. All four figures retain at least 10 pt native and embedded text.
- The main F1 mean WCT difference is -0.048 s, CI [-0.240, 0.143]; the focus failure-penalty difference is +8.130 s, CI [-5.116, 21.375]. All five pairs recover equal effective prefixes, despite different recovery sources. Retained 316 adverse F1 task pairs and separately reported recovery-ready, request-completion and workflow effects. No consistent-benefit claim is made.
- Added `PRIMARY_RESULT_AUDIT.md`, checked official Qwen model citation, and retained `FIGURE_METHODS.md` as the seven-figure interpretation contract. The eleven-page working PDF compiles without final-pass undefined references or overflow. Changed pages 4--11 were visually checked; pages 1--3 match the prior reviewed render byte-for-byte.
- Ablation execution finished all 40 runs and entered independent acceptance at 09:22 UTC. Sensitivity has completed all 20 canonical failure plans and is progressing into measured paired runs. Timing sensitivity remains live. The complete manuscript, Figures 5--7, and final submission audit remain unfinished.

## 2026-09-05: accepted ablation and unavailable-window audit correction

- Ablation completed VALID at 09:51 UTC, acceptance SHA `c95043025c6d62be92f9fd0e3448cc45976017fca9efd337ceb444b7c7ba9065`. An additional arithmetic pass reconstructed all four arms and all 160-workflow means for each seed. Integrated the ablation subsection: LRU-minus-full focus penalty +7.377 s, CI [1.953, 12.800]; disabled slack +6.818 s, CI [-14.298, 27.935]; disabled AIMD +5.511 s, CI [-8.676, 19.699]. All whole-workload intervals cross zero. `ABLATION_RESULT_AUDIT.md` records the limits.
- V3 sensitivity failed its formal pressure-consumption check at F4/C16/seed3. Full raw evidence shows pressure at 252.835349731 s, failure at 255.300179866 s, skipped control window at 258.7525 s, repair at 375.300179866 s, and next decision at 379.1025 s. Runtime intentionally clears old pressure in an unavailable-device window. Added a proof-based audit exception, with negative tests; the original complete raw now passes in 166.14 s. Preserve the original failure. No simulated transition or parameter changed.
- Frozen execution `source-v3-auditfix` commit `d3e1e7357e00f35a79fd63f1b91e81778dfadf4d` and analysis-v3 commit `0b7995e457c9cb7c45b1ecd397c1ccbd99b6fd8f` differ from predecessors only in this checker and new regressions. Both frozen focused suites pass 111 tests; Ruff and mypy pass for the checker. Existing accepted studies retain their original source bindings.
- New sensitivity supervisor PID 1974787, producer PID 1974788, started 09:56:59 UTC. It executes all 70 measurements afresh, then independently audits and renders Figures 5/6. The 20 original Store-only canonical plans were revalidated without reselection; original envelopes, exact unchanged contents, new envelope hashes and zero imported measured outcomes are preserved in `runs-auditfix/CANONICAL_PLAN_IMPORT.json`. `AUDITFIX.md` explains the distinction.
- All 60 timing executions have finished; independent audit PID 1939306 started 09:48 UTC and is progressing. Current corrected sensitivity has 20 raw outputs as of 10:04 UTC; these are producer intermediates, not accepted matrix evidence.
- Added `verify_delivery.py`, checked its rejection of stale/unreviewed figure bindings, and verified all source inventories and completed figures. The working PDF remains 11 pages; all pages were rendered and inspected, no final-pass overflow or unresolved references, and embedded figure text remains at least 10 pt. Its SHA is `97df45f59608dd045f217559b5c5b72315426ed45a76ee7d8667869e3457b2ba`. Final abstract/conclusion, remaining figures/results and full delivery review remain required.

## Final closure

All eight required deliverables are closed. See `simulation-8b/COMPLETION_REPORT.md`
for exact evidence, limits, source archives and final hashes. All 200 measured
runs are accepted, seven figures are reviewed, and the 13-page manuscript
contains at most 12 technical pages. The source-only bundle independently
builds to identical page pixels. All 17 delivery checks pass. Earlier work-log
entries below their original dates remain historical, not current status.
