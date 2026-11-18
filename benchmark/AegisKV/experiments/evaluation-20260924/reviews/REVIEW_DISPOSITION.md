# Claude Opus 5.5 review disposition

The exact requested Cursor model `claude-opus-5-5-max` was available and invoked
in read-only mode. `preflight-opus55.jsonl` is the raw review, exit code 0;
`PREFLIGHT_OPUS55.md` retains the returned answer. The reviewer **did not approve
publication readiness**. It read a moving implementation and earlier evidence;
its numerical examples from the 20260923 campaign are historical, not this
campaign's results. This file records our response rather than rewriting the
reviewer's verdict.

| Concern | Current response | Remaining boundary |
|---|---|---|
| Generic linear costs/model mismatch | Added pinned Qwen3-8B TP1 and Qwen3-32B TP4 geometry and AIConfigurator HYBRID operator grids; exact table/code hashes and bounded interpolation | Operator estimates are not end-to-end calibration; no fresh GPU execution is authorized in this simulation-only task |
| One busy invocation per worker | Explicit FCFS scope and independent queue/service accounting | Continuous batching and replica-versus-batch-capacity interaction are still absent; no real serving throughput claim |
| Gold outputs and single-call FanOutQA | Label constructed evidence-provided prompts and gold outputs; preserve exact source IDs/edges; source-order/length selection disclosed | Does not become a naturally observed multi-call workload |
| Multi-call/decode coverage | 135 corrected constructed interventions, exact historical prefixes, long decode and phase-specific failures; eight scale controls remain historical | Immediate artificial continuations do not validate real tool/think idle gaps or Agent wall-time behavior |
| Future output-size leakage | Runtime now reserves declared output limits; primary uses 512, structural 16384; tests compare equal caps with different future outputs | Older mechanism/smoke artifacts retain their explicit legacy convention |
| Predictor circularity | Current-prompt cost plus train-only role output median, train-only prior/guard, disjoint workflow IDs; explicitly a modeled-service proxy | Not a trained real Agent predictor; cannot claim semantic forecast accuracy |
| Native selectors | Reused source-pinned native model observations; per-query/head deduplication, causal checkpoint selection, same-budget oracle, cold and continuously protected history diagnostics | Different native models/prompts from Qwen WCT replay; no transfer of coverage into a claimed WCT effect |
| Statistical units | 62 complete held-out workflows; five fixed failure identities per condition; three documents per native model; no pseudo-replication CIs | Small scenario bank and document cohort constrain generalization and tails |
| Unsupported bounds | Keep 5223 > 256 copy-lag counterexample, small HBM increments, coverage denominator distinctions, and adverse results | Earlier manuscript is user-frozen; Evaluation must explicitly delimit quantitative guarantees |
| Resumption/provenance | Plan/priors/profile/workload/job/config/failure/summary hashes checked, outputs audited, source snapshots retained, independent audits | Full transfer audit only for runs retaining complete rate intervals; summary-only evidence is labelled |

The authorized 483-run replacement work and final external review have now
completed. The final Claude Opus 5.5 verdict is **NOT READY**, preserved in
[FINAL_OPUS55.md](FINAL_OPUS55.md). The preflight and candidate histories below
remain unchanged in meaning; completion and typesetting do not confer approval.

## Completed candidate review and corrective work

The candidate invocation finished successfully at 2026-09-23 18:50:15 UTC,
reported **Claude Opus 5.5 1M Max**, and recorded no input hash drift. Its exact
answer is preserved in [CANDIDATE_OPUS55.md](CANDIDATE_OPUS55.md). Its verdict
is **not ready**. It counted the 180 primary, 135 main structural, 126 resource
and 32 capacity/Slack runs, inspected actual colour pages 7--13, and explicitly
excluded the unfinished scale and post-hoc diagnostic results. This is not a
review of the subsequent implementation fixes or replacement experiments.

| Necessary issue identified | Current action and status |
|---|---|
| O1 comparison/fallback omitted, non-discriminating WCT controls | Independently recompute DRAM/All-DRAM traffic including cancellation bytes, and distinguish fallback observation counts from time fractions. Retain the 32-point null and label the later constructed diagnostic post-hoc. No general Slack WCT claim is established. |
| Dense HBM premise and native operating points | Add K=16/L=4 native distinct/event comparisons and full event comparators at K=64; explicitly distinguish these from dense WCT at L=11/1. A saved transfer-byte term is not a universal WCT bound under scheduling changes. |
| Target and recovery endpoints absent from primary presentation | Regenerated 150 per-identity records directly from all 180 corrected summaries; an independent implementation checked all records and 90 stratified summaries. The paper includes the six-panel target figure and six-row interrupted-Agent latency table. |
| DMA healthy cost omitted and quota claim unsupported | Independently compute healthy/failure cost using a single objective. Break-even must use either the target or cohort consistently and denotes a Bernoulli mixture of this one fixed failure, not a measured failure rate. O3 has no demonstrated WCT advantage in the present foreground model. |
| Queued continuation history dropped after failure | Fixed and reproduced with eight new regressions (74 current-runtime checks in total). The 483 matched replacement conditions share one frozen version. Active recoveries and queued-history restorations remain distinct; these inputs do not represent truly idle gaps. |
| Non-crossing predictor/TTL/lambda controls | Treat as code-path/operating-point checks, not accuracy or robustness validation; capacity points unable to fit even the target checkpoint must be identified. |
| Workload, depth and historical runtime scope | Explicitly narrow natural-workload claims; identify constructed multi-call interventions, partial coverage of the proposed depth rule, and the older source for the copy-lag counterexample. |

An independent concurrent code review additionally found the recovery causal
domain defect, which was not part of the candidate's findings. The selection
domain and local-tail hit accounting are now corrected and, together with queued-history repairs, pass 74 runtime
checks; the [application record](CAUSAL_DOMAIN_APPLICATION.json) binds the old
and new hashes. [The replacement plan](RECOVERY_DOMAIN_RERUN_PLAN.md) requires
same-input reruns before old numerical results can describe the corrected
runtime. Completed old audits establish their recorded version's accounting,
not the repaired semantics. No source or result is retroactively relabelled.

Candidate assertions and arithmetic are reviewed independently; its report is
preserved even where a denominator, approximation or causal claim requires a
more precise response. The final external review also returned **NOT READY**;
no approval can be inferred from completion counts or test success.

## Completed corrected package and final review

All 483 same-input replacement conditions have completed and passed their
campaign audits. The primary process ended with code 143 after 177 accepted
conditions; its cause was not determined. Resuming only the three missing
conditions from the sealed source left every preceding marker and summary
hash unchanged (`formal-core-v2-corrected/INTERRUPTION_RECOVERY.json`). The
independent five-group comparison verifies 483 matched pairs and identical
complete numeric summaries for all 159 healthy conditions. Replacements are
not additional statistical samples.

- `coprimary-v2-crosscheck/` binds all primary endpoints, signed differences,
  sink/non-sink strata and exact queue/service decomposition.
- `o1-dma-corrected-v2-audit/` audits 180 primary and 126 sensitivity runs.
  It independently reconstructs all 30,100 logged Agent Slack values and
  reports the precise workflow/window fallback denominator. The manuscript
  now gives all six DRAM/All-DRAM traffic savings, the two opposing individual
  WCT outcomes, and both detailed-run fallback fractions.
- Current native operating points, healthy DMA cost, same-objective break-even,
  capacity feasibility and non-crossing predictor controls appear explicitly.
  The 32-run zero-Slack WCT null and ten-run post-hoc tight/loose result retain
  their different evidentiary roles.
- The candidate's universal claim that only target protection can affect WCT
  does not hold under shared scheduling. Corrected records reproduce the
  1.099886 ms target gain with a 3.402435834 s increase in cohort WCT sum.
  Likewise, a local saved-byte/bandwidth term is not a global WCT bound.

These corrections improve implementation fidelity and reporting; they do not
verify the frozen manuscript's unconditional delay, coverage or optimality
statements. The independent read-only assessment and concrete
[unapplied claim corrections](PROPOSED_CLAIM_CORRECTIONS.md) identify remaining
design/evidence contradictions. No preceding text has been changed, and these
proposals are not completed remedies. The final external review judged this
package **NOT READY**, specifically retaining the center-claim contradictions
and missing discriminating evidence; its invocation and 158 reviewed inputs
are preserved in `FINAL_REVIEW_INVOCATION.json` and `final-reviewed-v2-inputs/`.


## Post-review reporting revision and unresolved scope

After the final review, only three Evaluation reporting paragraphs were revised:
32B adverse retry-worker/queue-service attribution, the structural target/cohort
adverse-condition counts, and the DMA absolute-F1 cohort cost. The new manuscript
remains 12 technical pages plus two reference pages. Actual color/grayscale
inspection covered every visually changed page (9–12); all four Evaluation
figure PDFs are unchanged. `../paper-preview/VISUAL_REVIEW.json` binds this
post-review revision and explicitly records **no new external approval**.
`FINAL_OPUS55.md`, `FINAL_REVIEW_INVOCATION.json`, `FINAL_PACKAGE_READY.json`
and the archived reviewed inputs retain their original bytes and identities.

A training-wall-time predictor is being implemented separately; its completion,
validation and consequences for results are not claimed here. The reviewed 483
conditions remain service-proxy evidence. The
[seven-item final claim change proposal](FINAL_CLAIM_CHANGE_PROPOSAL.md) is
**NOT APPLIED** and awaits the user's decision on whether the frozen preceding
chapters may be changed. It also records reservations about mixing native
selectors with Qwen timing or treating time-inferred dependencies as a known
Agent-task DAG. Neither these proposals nor the reporting edits resolve the
final review's substantive objections by themselves.
