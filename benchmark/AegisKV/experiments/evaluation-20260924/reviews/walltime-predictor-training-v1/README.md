# Agent submission-to-completion predictor training

Completed six frozen healthy training conditions, one predeclared prior-transparency validation, and offline fitting. This is a **lightweight hashed-text regressor**, not a validated semantic encoder. Labels are simulated FCFS Agent wall times, including queues, under the pinned Qwen AIC HYBRID profiles; no physical inference was run.

The original 12 training workflows contain 95 single-call Agents. Each runs once at rho 0.3/0.65/0.9 for Qwen3-8B and Qwen3-32B: 570 captured contexts and labels. The 62 evaluation workflow IDs are used only to enforce separation. Their outcomes never select features, priors, epochs, guard quantiles or models. No new failure matrix was run, and no older campaign or paper was modified.

## Frozen protocol and actual capture

`TRAINING_PROTOCOL.json`, six configs, six exact-token workloads, two profiles and 91 source files were sealed **before** collection in `TRAINING_SEAL.json` and `MANIFEST.json`. All executions imported the retained `source_snapshot/python` tree; each run records actual absolute import paths and hashes in `RUN_START.json`.

The capture-only runtime subclass observes the existing predictor call without changing runtime.py or tracker.py. It saves actual Context and a separate `(workflow, Agent, invocation, submit-time)` identity. Features receive only Context. A neutral 10 s prior is used only to collect the healthy none-policy traces. After completion, an offline join labels each Context with `same-Agent final finish - this invocation's submit`; this is not merely the current invocation's latency when an Agent has multiple calls. Synthetic regression tests cover that distinction and queued submission. Natural training Agents here are all single-call, so these runs do not establish multi-call prediction accuracy.

For each model, leave-one-workflow-out fitting holds all three load observations of that workflow together. Only the other eleven workflows supply role-median first-submission-to-Agent-final wall-time priors, with a global fallback. Only `prior_ns` is replaced in the derived Context; the original captured Context remains in the artifact. Each model uses the existing fixed 40-feature ContextRegressor, 300 epochs, learning rate 0.1, L2 0.001 and 32 signed text hash bins. No hyperparameter search is performed. The final deployment model and role priors use all twelve training workflows.

## Descriptive held-out results

| Model | OOF MAE (s) | Role-median MAE (s) | OOF p90 absolute error (s) | Slack guard (s) |
|---|---:|---:|---:|---:|
| Qwen3-8B | 1.011184 | 1.081978 | 2.265032 | 0.910471105 |
| Qwen3-32B | 1.206977 | 1.321426 | 2.596369 | 0.995028646 |

Each model has 285 observations but only twelve held-out workflow groups, sharing three queue trajectories. These are training-condition crossfit diagnostics, not 285 independent repeats, external 62-workflow results, or confidence intervals. `REPORT.json` retains signed bias, RMSE, workflow-macro MAE, and each load's errors. At rho=0.9 the 8B MAE is 1.174963 s versus the role-median baseline's 1.177491 s, a small difference; the full result is preserved. Context has no queue or load feature, so the same first-submission input cannot distinguish the three arrival conditions.

The guard is calibrated from **Slack** overestimation, not service-time residuals. At fixed 100 ms control-window snapshots, held-out fold predictions and fold-only priors feed a fresh residual-DAG Tracker with zero guard. A separate offline reference uses observed final completion minus now for started Agents, and observed full Agent duration for unstarted ones. Per-workflow maxima of positive predicted-minus-reference Slack are pooled over its three loads; the nearest-rank p90 of twelve maxima is the guard. All 14,199/16,727 Agent-window points and twelve maxima remain available. This queue-conditioned reference CPM is not a counterfactual no-delay Slack oracle or an external coverage guarantee. Future completion times are used only offline, never in deployed features.

## Transparency and validation

The predeclared 8B/rho=0.65 healthy none-policy validation replaces 10 s priors by the final deployment role priors. All requests, workflows, output correctness, recovery lists, physical peaks, and non-prediction metrics match exactly. Every captured Context differs only in prior_ns, and the applied role prior/model hash is checked. The prediction diagnostic `slack_fallback_observations` changes from 0 to 5,356, explicitly recorded in `PRIOR_TRANSPARENCY.json`; therefore this is **not byte-identical summary output**. It establishes foreground transparency only for this fixed validation condition, not for all workloads or backup policies.

Seven new tests plus the existing current suite passed: **81 passed**. They check same-context identity association, queue-inclusive/multi-call labels, future-output exclusion from first Context, held-out-label poisoning, all-load grouping, serialization/model separation, and actual positive CPM Slack error. `INDEPENDENT_ARTIFACT_AUDIT.json` separately verifies frozen hashes, import roots, exact labels, fold and final priors, OOF arithmetic, guard quantiles, and the disjoint 12/62 split using a stdlib auditor that imports neither simulator nor fitter.

## Deployment interface

Use the separate Python wrapper, not the existing CLI's bare-ContextRegressor `--predictor` loader:

```python
import json
from dataclasses import replace
from pathlib import Path
from moonkvsim.aegiskv.evaluation_walltime_predictor import WalltimePredictor

predictor = WalltimePredictor.from_dict(json.loads(Path(model_json).read_text()))
evaluation_agents = predictor.apply_priors(evaluation_agents)
evaluation_config = replace(evaluation_config, slack_guard_ns=predictor.slack_guard_ns)
# Pass predictor=predictor to CurrentRuntime or run_one.
# Both the wrapper and runtime reject training/evaluation workflow overlap.
```

`apply_priors` supplies the historical-role prior used for unstarted Agents; prediction applies the same prior feature transformation used in training. The model-specific wrapper rejects a mismatched Context model. Deployment files are `models/Qwen3-8B/model.json` and `models/Qwen3-32B/model.json`; `deployment.json` records their feature contract and guard. Deployment has not been run on the 62 evaluation workflows.

## Independent held-out error entry point and replay

`train_walltime_predictor.py evaluate --model MODEL.json --samples LABELS.jsonl.gz --out NEW` performs only inference/error reporting and rejects any workflow overlapping model training. The example `heldout-evaluation-example/` re-evaluates the first source-order training workflow against its eleven-workflow fold model, with the three loads pooled. It checks the entry point; it is not a new validation population or a new simulation.

From the repository root, verify the retained run without rerunning it:

```bash
training_dir="$PWD/benchmark/AegisKV/experiments/evaluation-20260924/reviews/walltime-predictor-training-v1"
PYTHONPATH="$training_dir/source_snapshot/python" .venv/bin/python \
  "$training_dir/source_snapshot/benchmark/AegisKV/experiments/scripts/current_design/train_walltime_predictor.py" \
  verify --out "$training_dir"
.venv/bin/python "$training_dir/audit_training_artifacts.py"
```

For a new explicitly authorized reproduction, `prepare --out NEW` refuses an existing directory, then use the newly frozen runner and its `source_snapshot/python` to execute `run --out NEW`. The final MODEL seal is written only after all six training conditions, all folds, both models, guard calibration and prior transparency pass. `MODELS_COMPLETE.json` binds original model outputs; later independent review/example artifacts are bound separately in `DELIVERY.json` and do not rewrite that seal.
