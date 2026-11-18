# Predictor item 7: updated candidate after training — NOT APPLIED

The original `FINAL_CLAIM_CHANGE_PROPOSAL.md` remains frozen. Its item 7
describes the reviewed service proxy and explicitly requires new wording if
the task-completion predictor is implemented. That old replacement must not
be applied to describe the new implementation.

This candidate changes only the previously identified predictor/guard wording
and adjacent Chinese comments. It does not authorize edits to the preceding
manuscript. The user's earlier permission question is unanswered; no preceding
source has changed. Items 1–6 retain their original proposed scope.

## Current evidence

- `walltime-predictor-training-v1/DELIVERY.json` and its independent audit bind
  six healthy training runs, 570 labels, two fitted predictors, grouped
  leave-one-workflow-out calibration, role priors and guards.
- `../walltime-primary-v3/HELDOUT_ERROR.json` and its independent audit bind
  the six healthy held-out captures (3,018 observations over the same 62
  workflows at three loads per model). Overall MAE is 2.0274/2.2008 s for
  8B/32B, with substantially larger high-load error.
- `heldout-context-ambiguity-v3/` verifies identical actual Contexts and
  predictions across loads. No load or queue feature is supplied. Its
  test-label median calculation is an offline finite-case diagnostic, not a
  deployed predictor or a population bound.
- The matched 180-condition policy replay is still running. This candidate
  claims neither a failure-conditioned accuracy result nor a WCT improvement.
- The original 483 conditions keep their service-proxy/declared-prior identities.

## Proposed replacement for the predictor implementation paragraph

Retain the Tracker's intended submission-to-Agent-task-completion target,
context interface, history identity, timestamps and residual-DAG definitions.
Replace the implementation/validation claims with:

```tex
At invocation submission, Tracker estimates the wall-clock time until
the Agent completes its task, using only the submitted Context.
Our evaluated prototype uses a fixed hashed-text regressor with
40 features, trained on healthy submission-to-same-Agent-completion
labels that include queue residence.
The training and evaluation workflows are disjoint.
Unstarted Agents use training-only role priors.
The replayed training Agents each have one invocation, so this
validation does not establish prediction of future calls or tool gaps.
The prototype has no load or queue feature and does not instantiate
a separately validated semantic encoder; Evaluation reports its
held-out errors and distinguishes it from the earlier service proxy.
```

For the explanation of the guard, retaining the surrounding definitions:

```tex
The prototype sets the guard to the training 90th percentile of
workflow-maximum positive Slack overestimation under grouped
leave-one-workflow-out calibration; all loads of a workflow stay
in the same fold and its role priors are fitted on other workflows.
The reference uses healthy realized completion times, including
queue residence, rather than a counterfactual queue-free schedule.
This is an empirical guard, not a probabilistic bound on failure delay.
```

If adopted after approval, the adjacent Chinese comments should distinguish
the intended whole-Agent target, the implemented hashed-text prototype, the
single-invocation evidence limit, and the empirical healthy calibration.
Do not describe the new guard as a decode-service residual quantile. Do not
claim that healthy validation establishes future-call or failure-conditioned
accuracy. Exact guards and full error tables stay in Evaluation and the
versioned artifacts rather than becoming architectural guarantees.

The final text should be checked against the completed primary replay and
fresh external review before any approved application. This document changes
no manuscript, runtime, model, policy input or sealed result.
