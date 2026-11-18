# Figure 3(a): early remaining-time prediction

This is a new fixed-landmark cross-validation experiment on observed CC
agent episodes, not a reconstruction of related-work accuracy and not a
physical AegisKV experiment. Current manuscript: `../../sections/design_insights.tex`.

## What is predicted

At the second LLM request's arrival, provided the first has completed, predict
seconds until the reported **whole-agent** completion. The trace does not
provide a separate tool-completion timestamp; this landmark must not be
described as an observed LLM-plus-tool completion event. Reported wall-clock
labels retain intervening service/tool effects. Episodes are not reconstructed
fork/join-separated Tracker segments.

The upstream extraction retains 1,688 episodes from 174 workflows after
excluding 9 inconsistent episode/request clocks. At this landmark, exclude
3 single-request episodes and 242 whose first two requests overlap. The
remaining **1,443 agents from 170 workflows** cover **85.49%** of valid episodes.
No duration threshold or prediction-error filter is applied. The landmark's
elapsed/total-duration fraction has p10/median/p90 **0.82%/4.67%/23.60%**;
these are retrospective diagnostics, never model inputs or selection rules.

## Training and statistics

Each agent contributes one training/test sample at the same landmark. Five
folds group complete workflows using the previous experiment's frozen hash
salt. There is no train/test workflow overlap; this is not a chronological
deployment evaluation. Agents remain clustered within workflows, not 1,443
independent physical repetitions. Five models are fitted once with a fixed
configuration; no test-set hyperparameter search or independent repeated run.

Numeric inputs: elapsed time, current and first prompt lengths, first completed
output length and API latency, and time since first API completion. Role and
current model are one-hot encoded with training-fold vocabulary. All role
labels are `Subagent`; there are no task semantics or tool-phase annotations.
Future outputs, future request counts, final duration, and identities are not
inputs. The model predicts remaining seconds directly, with a log1p target.

GBDT uses the existing deterministic NumPy implementation: 80 trees, depth 3,
learning rate 0.06, minimum leaf 32, 32 bins. The baseline is the training-fold
median **remaining time at this same landmark**, grouped by role and model;
unseen groups fall back to role, then global history.

Each ECDF observation is
`100 * abs(predicted_remaining - actual_remaining) / actual_remaining`.
The denominator is remaining time, not total episode duration. Every eligible
agent has equal descriptive CDF weight, and both methods use identical agents.
All errors are retained; no smoothing. The x-axis is linear to 100%, then
logarithmic, with limit 20,000% covering both full tails.

| Method | Median relative error | P90 | Fraction within 20% |
|---|---:|---:|---:|
| GBDT | 75.87% | 766.59% | 13.37% |
| Historical median | 76.23% | 766.20% | 11.23% |

**This corpus/configuration does not establish accurate early prediction.**
It does not establish that all agent-time predictors fail either. The prior
51.8%/49.3% diagnostic uses a different cohort, snapshot aggregation, and
total-duration denominator; those values are not directly comparable to this
experiment. Original figures and predictions remain preserved in
`../design-insights/` and `../../../experiments/data/design-insights/`.

## Artifacts and reproduction

- `agent-time-panel.{pdf,svg,png}`: 2.24 × 1.85 inch, Figure 3(a).
- `agent-time-single-column.{pdf,svg,png}`: 3.34 × 2.30 inch, standalone.
- `figure3-row.{pdf,png}`: vector composition with current panels (b)/(c).
- `../../../experiments/data/agent-time-early/`: protocol, landmarks,
  held-out predictions, fold/model hashes, and summary statistics.
- `MANIFEST.json`: source and export hashes; SVG retains editable text.

From the repository root:

```sh
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_agent_early_prediction.py
# Only redraw existing predictions and refresh the row after panels (b)/(c) change:
.venv/bin/python benchmark/AegisKV/experiments/scripts/paper/render_agent_early_prediction.py --render-only
sh benchmark/AegisKV/paper/build.sh
```

Actual PDF/render/paper checks are recorded in
`../../../../../output/pdf/aegiskv-agent-early-20260918/REVIEW.json`.
