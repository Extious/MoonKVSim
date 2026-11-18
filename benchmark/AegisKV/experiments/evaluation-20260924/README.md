# AegisKV current-design simulation and Evaluation

**Storage update (2026-10-04):** the current manuscript's `blsc-online-v1/`,
`blsc-scale-v1/`, `native-topk-warm/` and their inputs are retained. Old campaigns'
per-run summaries, raw event/flow logs and conditional component case outputs
were deleted at the user's request. Configurations, failure plans, protocols,
frozen sources, aggregate reports and historical completion records remain.
See [the removal record](DATA_REMOVAL_20261004.md). The campaign status and
"running" descriptions below are historical; they do not assert that deleted
outputs remain available or that a job is running today.

**The five corrected v2 campaigns are complete: 483 conditions audited. The new
180-condition wall-time-predictor primary campaign is still running.** The independent
[causal-domain review](reviews/DESIGN_CONFORMANCE_SPOTCHECK.md) found that the
frozen recovery path omitted local tail KV from its selection/overlap model.
The causal-domain and queued-history corrections now pass 74 current-runtime
regressions. Existing v1 numeric results describe the original snapshots; their
audits are not proof of corrected recovery semantics. See the
[matched rerun plan](reviews/RECOVERY_DOMAIN_RERUN_PLAN.md). The offline native
Top-K diagnostic does not execute the affected recovery routine.

The common replacement source is
`checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1`
(runtime SHA-256 `de3a9ce7791218a74e8d50651c2ba1249b194e500eabc0fd9a91c52b978b8c5f`).
The 483 matched replacement conditions are in `formal-core-v2-corrected` (180),
`structural-campaign-v2-main` (135), `sensitivity-campaign-v2-corrected` (126),
`capacity-slack-ablation-v2-corrected` (32), and
`slack-mechanism-posthoc-v2-corrected` (10). Each source and input match is
retained. Primary execution was interrupted after 177 accepted conditions;
the three missing conditions were resumed from the sealed source. The
[recovery record](formal-core-v2-corrected/INTERRUPTION_RECOVERY.json) verifies
that all 177 preceding markers and summaries remained unchanged.
`reviews/primary-resume.log` records completion, audit and plot generation.

This artifact separates implementation tests, modeled performance, offline
native-selector observations, and physical evidence. No new GPU execution was
performed. A completed simulation matrix or a successful paper build does not
establish EuroSys readiness or physical calibration.

Completion is recorded in each campaign's audit and per-run `COMPLETE.json`.
The [final Claude Opus 5.5 review](reviews/FINAL_OPUS55.md) completed with
**NOT READY**: the audited 483-run package did not establish the frozen
Design's central claims. Its exact inputs remain in
`reviews/final-reviewed-v2-inputs/`. The manuscript is now an in-progress revision;
older rendered approvals do not apply to its changing contents. A separate
v3 layout preview fits 12 technical pages, but still contains explicitly marked
v2 primary results and cannot be treated as the completed v3 paper. A separate
Agent-walltime predictor is now trained; its 180-condition `walltime-primary-v3`
replay is in progress and does not relabel these sealed results. The
[seven proposed claim corrections](reviews/FINAL_CLAIM_CHANGE_PROPOSAL.md)
remain NOT APPLIED, pending the user's decision on the frozen preceding-text
scope. Its old prediction item has a separate
[updated v3 candidate](reviews/FINAL_CLAIM_PREDICTOR_UPDATE_V3.md), also unapplied.
No completed matrix or successful build supersedes the review verdict.

Post-review work is tracked in the [remediation protocol](reviews/POST_REVIEW_REMEDIATION_PROTOCOL.md).
The [24-point low-DMA extension](low-dma-postreview-v1/RESULTS.md) and
[864-scenario native raw-KV component](native-transfer-postreview-v2/RESULTS.md)
are complete and independently audited. They retain the original service-proxy
and conditional component boundaries, respectively; neither is a new native
WCT result. The [trained predictor](reviews/walltime-predictor-training-v1/README.md)
has a [public CLI interface](../../docs/current-design-simulation.md#运行).
The separate [72-condition bounded-HBM quota study](quota-pressure-postreview-v1/RESULTS.md)
is complete and independently audited. Pressure occurs only in healthy runs,
after the fault target would have completed; matched adaptive/fixed quotas have
identical workflow endpoints. These conditions do not establish an adaptation
benefit. A bounded Claude Opus 5.5 review of completed remediation methods is
running separately from the eventual full-paper review. Parameter
points, repeated documents and replacement runs are not independent samples.

| Evidence | Location | Purpose |
| --- | --- | --- |
| Latest implementation | `python/moonkvsim/aegiskv/current/` in repository root | Tracker, full DRAM checkpoint, incremental HBM gain, checkpoint Top-K, quota, shared-resource recovery |
| Primary replay | `formal-core-v2-corrected/` | 180 completed, audited replacements; two Qwen models, three nominal loads, five policies, five fixed failures and matched healthy baselines |
| New primary replay | `walltime-primary-v3/` | 180 planned matched conditions with trained wall-time predictor, priors and guard; consult `STATUS.json`, pending completion |
| Predictor and held-out diagnosis | `reviews/walltime-predictor-training-v1/`, `reviews/heldout-context-ambiguity-v3/` | Training and six healthy held-out captures complete; healthy errors do not establish failure-conditioned accuracy |
| DMA extension | `low-dma-postreview-v1/` | 24 completed lower-coefficient conditions, retaining the original service proxy and fixed fault |
| Quota pressure | `quota-pressure-postreview-v1/` | 72 completed conditions with the new predictor; capacity pressure without an observed adaptation benefit |
| Raw-KV component | `native-transfer-postreview-v2/` | 864 completed conditional component scenarios; independent of workflow simulation and native kernel timing |
| Structural interventions | `structural-campaign-v2-main/` | 135 completed, audited replacements; constructed histories, phase, topology and queueing; separate target and cohort endpoints |
| Model/resource sensitivity | `sensitivity-campaign-v2-corrected/` | 126 completed, audited replacements on four complete held-out workflows; fixed fault, no population confidence interval |
| Capacity and Slack control | `capacity-slack-ablation-v2-corrected/` | 32 completed, audited replacements; explicit zero-Slack variant and DRAM budget boundary |
| Post-hoc Slack mechanism | `slack-mechanism-posthoc-v2-corrected/` | Ten completed, audited replacements on one constructed fork--join workflow; two separate observation-transparency validations |
| Native selection | `native-topk-warm/` | Three documents per native model; complete counter history and exact deployed tie rule |
| Historical mechanism matrix | `mechanism-campaign/` | 78 completed linear-cost regression runs, including the uncapped checkpoint-lag counterexample |
| Inputs and timing | `inputs/` | Frozen source IDs, token provenance, train/eval split, pinned AIC operator estimates |
| Reviews and corrections | `reviews/` | Preserved Opus final NOT READY, source replay/tests, archived reviewed inputs, and unapplied claim corrections |
| Manuscript | `../../paper/evaluation.tex` | Independent Evaluation included by `paper/main.tex` |

`PROTOCOL.md` and `LITERATURE_AND_DESIGN.md` distinguish executed work from the
broader suggested matrix. The preserved cold native diagnostic is a different
counter-lifetime/tie-rule variant; it is not pooled with the current warm result.
Smoke runs and interrupted attempts are retained and are not extra samples.

All `*-v1` directories remain as historical versions. The initial core/structural
snapshots precede the EOS repair; the other three v1 campaigns precede the
causal-domain and queued-history fixes. Their accounting audits do not establish
current semantics. Historical structural scale controls completed 143 total
runs (135 main plus eight scale conditions), with version-labeled CPU/RSS
reports. Results are never retroactively relabelled as a newer version.
The zero-Slack configuration is an explicit ablation; normal operation retains
the causal DAG Tracker.

The historical sensitivity, capacity/Slack and post-hoc campaigns inherited an inaccurate
generic timing label. Their appended `TIMING_METADATA_ERRATUM.json` files bind
the original hashes and establish that all 168 runs used `GridDurationProfile`.
The sensitivity erratum also identifies its nonzero DMA-slowdown controls.
Original manifests, seals and numerical results are preserved. The v2
preparation code writes the correct profile and DMA metadata; see
[the timing review](reviews/TIMING_METADATA_REVIEW.md).

## Reproduction

Commands run from the repository root with the existing `.venv`.

Create a fresh service-proxy primary campaign using the current implementation
(this is not the trained wall-time-predictor campaign):

```sh
.venv/bin/python -m moonkvsim.aegiskv.evaluation_campaign prepare --out /tmp/aegiskv-core-replay
.venv/bin/python -m moonkvsim.aegiskv.evaluation_campaign run --out /tmp/aegiskv-core-replay --workers 32
```

For an exact sealed core source version, use the isolated frozen runner
instead of relying on the changing worktree. It verifies every seal, creates
a new output directory and records any ancillary import support separately:

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_frozen_profile_campaign.py \
  --campaign benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v2-corrected \
  --out /tmp/aegiskv-frozen-core-replay --workers 32
```

Independent primary audit and editable plots:

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/audit_profile_campaign.py \
  --campaign benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v2-corrected
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/plot_profile_campaign.py \
  --campaign benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v2-corrected
```

The co-primary figure additionally uses `analyze_primary_endpoints.py` followed
by `plot_primary_endpoints.py`, with the same `--campaign` argument.
The plot commands require the full primary matrix to pass the independent
audit. Structural, sensitivity and native directories retain their own runner,
plot command, captions, numeric data and source hashes.

Build and render the manuscript without editing preceding chapters:

```sh
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/review_evaluation_paper.py
```

Rendering writes actual color/grayscale pages and source-preservation checks;
it does not replace visual inspection. All figure sources remain editable.
