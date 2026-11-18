# Simulated-only result integration plan

Status: completed simulated-result integration record. This file is not
empirical evidence; the immutable campaign and generated manifest are the
evidence sources.

## Current page boundary

The final `main.pdf` has 14 PDF pages: exactly 12 technical pages followed by
two reference pages, with References starting on page 13.  The build-time page
gate passed, the compilation log has no overfull/undefined/fatal errors, and a
14-page rendered visual audit found no clipping or overlap.  This exactly
consumes the EuroSys technical-page allowance.

## Insertion point and activation rule

`sections/05-evaluation.tex` ends with a fail-closed conditional include for
`sections/05-simulation-results.tex`. This is the only active insertion point:
after methodology and result gates, before Discussion and Limitations. The
new `sections/05-simulation-results-skeleton.tex` is deliberately not included.
The audited renderer may use it as a structural template, but must generate the
active result file only after the complete manifest and every declared cell,
gate, statistic, figure, and table hash pass.

The generated package is active in this order:

1. central paired comparison, separate A/B/C fault quantities, and Figure 2;
2. load/failure/controller behavior with Figures 3 and 4;
3. resources, reuse, and model/layout sensitivity with Figure 5;
4. complete Algorithms 1/2/3 factorial and predictor stress with Figure 6;
5. a short selection/evidence-boundary paragraph leading into Discussion.

## Figure and table budget

The fail-closed renderer accepts only the seven PDF/PNG stems in the final
figure manifest.  Its current experiment-forward default places five
full-width vector PDFs: headline baseline/matrix outcomes, concurrency and
failure sensitivity, resource/model sensitivity, the complete Algorithm
factorial, and a joint alpha/occupancy/reuse mechanism view.  Two secondary
reuse/recovery and Algorithm-1 diagnostics remain hash-bound in the artifact.
Figure selection does not filter any result row or headline number.  The
renderer still emits `tables/sim-eval-ablation-mechanisms.tex` as an audited
machine-readable presentation artifact, but the active manuscript uses the
factorial figure instead of duplicating the full numerical table.

All placed text, legends, and captions must remain at least 10 point and be
legible in grayscale. Do not trade compliance for more panels.  Each placed
view is therefore full width; secondary diagnostics remain in the bound
artifact rather than being shrunk into unreadable one-column panels.

## Claim contract

- A is the full-horizon wall-clock Poisson incidence experiment. Idle and
  ineffective events remain; no effective-event floor is allowed.  Its
  endpoint is the per-workflow maximum actual-Slack overrun, a join-harm
  surrogate rather than an event-additive sum or workflow completion time.
- B is the policy-independent active-source, complete-sealed-frontier shadow
  estimand in the matching rate-zero normal state. Each seed first averages its
  equal-exposure strata; formal uncertainty resamples only matched seed means.
- C is a first-order eligible-exposure burden derived from B and the declared
  hazard. It is not a third executed failure process, steady-state repeated-
  failure behavior, or an addend to A.
- Algorithm 1 changes causal policy Slack; Algorithm 2 changes independent-tier
  admission/victim choice; Algorithm 3 changes only the target-local Peer-HBM
  quota from pressure/stability. When Algorithm 2 is disabled, Algorithm 1 is
  structurally inactive and its main/interaction effects require a
  hierarchical interpretation. Failure rate is never wired into alpha.
- The `t=0` control row is an initial snapshot, not an AIMD update.  Only
  positive-time periodic windows apply Algorithm 3.
- Standby rotation is absent.  Natural target history is a conservative
  no-rotation sensitivity that may underestimate Peer-HBM availability and
  must not be described as complete failover.
- DejaVu, RaidServe, KevlarFlow, and GhostServe rows remain capacity-matched
  component adaptations and retain the `-style` qualifier.
- All service coefficients, capacities, effective path rates, and failure
  processes are synthetic simulator inputs. There is no physical calibration,
  vLLM/CUDA/Mooncake performance result, executed worker replacement, or
  end-to-end DAG re-execution result.
- Healthy-time claims are limited to simulated backup memory, copy traffic,
  occupancy, churn, and amplification. The model does not establish foreground
  latency or throughput overhead.

## Compression order if a future regeneration overflows

1. Deduplicate Evaluation's mechanism-gate prose against the generated sanity
   table; preserve every gate but avoid describing it twice.
2. Convert repeated scenario constants in Trace, Models, and Failure Injection
   into one compact native-LaTeX setup table; keep topology and unit semantics.
3. Merge duplicated failure limitations across Implementation, Evaluation, and
   Discussion while retaining one precise primary definition and one threats
   paragraph.
4. Tighten Related Work prose and citations without removing the distinction
   from component adaptations.

Do not shrink body, caption, legend, or table text below the EuroSys minimum;
do not use negative vertical spacing; do not remove null, negative, failed, or
invalid cells; and do not move claim-critical evidence to supplementary
material merely to meet the page limit.

## Final activation checklist (completed)

The activated package binds
`final_audit_experiment_heavy_20260826.json` (canonical SHA-256
`43ee6140a937da85f7cb918594d8fcd25205dec62fb09502b739e4952d8f1eb3`),
the five expected `selected_figure_stems`, and paper-manifest canonical SHA-256
`1adb94c35755e4d07336a34756ce692a54234c7c34362b9ae1d7a88f2c590352`.
The final PDF SHA-256 is
`12c2b26b8f61dcea6fcf30891ea417f2defe7084cd934b311cac45f82fc237f0`.

- Generated result TeX and every figure/table are bound to the immutable
  simulator, workload, matrix, seed, and raw-artifact hashes.
- Absolute outcomes, matched-seed uncertainty, and healthy memory/copy cost are
  shown together; no headline is only a relative improvement.
- A, B, and C remain separately labeled, with the conditioned probes never
  treated as independent seeds.
- Full Algorithms 1/2/3 factorial rows and all baseline adaptations are
  present, including null and adverse outcomes.
- The abstract, Introduction, Conclusion, captions, and result prose receive
  numbers only from the same manifest.
- The final build has at most 12 technical pages; references begin afterward;
  no undefined reference/citation, overfull box, clipped object, or unreadable
  figure text remains.
