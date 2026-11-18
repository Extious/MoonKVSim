# Finite-case Context ambiguity diagnostic

**PASS: every model/Agent has the same complete derived Context and the same
actual online prediction at all three tested loads.** Grouping by canonical
Context bytes across all Agents, rather than by identity, gives 503 groups per
model. Each group contains three observations. No two different Agents happen
to share an identical complete Context in this case-set.

| Model | Observations | Context groups | Groups with unequal labels | Empirical minimum MAE (s) | Actual model MAE (s) | Role-prior MAE (s) |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3-8B | 1,509 | 503 | 442 | 0.995560 | 2.027391 | 2.072973 |
| Qwen3-32B | 1,509 | 503 | 429 | 1.012505 | 2.200767 | 2.247830 |

The independent inputs are the six completed `none`/F0 conditions in
`walltime-primary-v3`. They repeat the same 62 held-out workflows and 503 Agent
tasks at nominal loads 0.3, 0.65 and 0.9 for each model. These are dependent
observations of a fixed case-set with shared queues, not 1,509 independent
trials. The denominator is all 1,509 Agent-submission observations per model;
each load contributes exactly 503, with no exclusions or favorable selection.

The complete Context comprises model, role, visible text, prompt-token count,
completed-call count, previous durations/output counts, elapsed Agent time and
the deployed training-derived prior. This workload has one call per Agent, so
completed-call count and elapsed time are zero and the history arrays are empty.
It supplies no load, queue length or absolute submission-time feature. Sidecar
Agent/Workflow IDs and load labels are not inserted into the grouping key.

For each exact Context group, the best unrestricted deterministic mapping for
absolute loss assigns a median of that group's observed completion-time labels.
The reported minimum is the sum of these within-group absolute deviations,
divided by all 1,509 observations. Exact integer-nanosecond sums are:

- 8B: 1,502,299,867,949 ns / 1,509 = 0.9955598859834327 s.
- 32B: 1,527,869,959,765 ns / 1,509 = 1.0125049435155733 s.

The generator computes rational medians and absolute deviations. The independent
auditor instead sorts each group's labels and subtracts the sum of its lower
half from the sum of its upper half. Both methods agree exactly. All 3,018 saved
prediction values were also checked against the actual accepted online
`prediction` events, rather than merely reevaluating the serialized regressor.

This is the **minimum empirical MAE on this finite test case-set for an arbitrary
deterministic mapping from the complete visible Context**. It is not a
population or future-prediction lower bound. The minimizing group medians use
held-out outcomes offline, are not deployable predictions, and were not used for
training, calibration, tuning, configuration changes or run selection. Nor is
this the minimum achievable by the particular linear hashed-text regressor:
that restricted model family need not realize an arbitrary Context-to-median
mapping. The remaining gap between the actual model and this empirical minimum
does not identify a unique model or encoding failure.

The diagnostic establishes a concrete information limitation in this case-set:
different healthy completion-time labels occur under exactly identical visible
Contexts, while the deterministic deployed predictor necessarily returns the
same value. It does not prove that adding a queue/load feature would solve the
prediction problem, and it does not authorize a new Design, model or matrix.

Artifacts:

- `RESULTS.json`: complete model aggregates and all six online-event checks.
- `identity-load-consistency.csv`: all 1,006 model/Agent/invocation identities.
- `observations.csv`: every observation with its Context hash and signed-input labels.
- `context-groups.jsonl.gz`: full canonical Contexts, all members and median arithmetic.
- `SOURCE_HASHES.json`: original completed input bindings and generator hash.
- `INDEPENDENT_AUDIT.json`: alternate arithmetic, full source-artifact hash closure,
  output hashes and independent auditor hash.

All new files reside in this diagnostic directory. No v3 training artifact,
configuration, workload, matrix, frozen source or prior report was modified.
