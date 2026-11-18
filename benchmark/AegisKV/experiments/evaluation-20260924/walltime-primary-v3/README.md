# Wall-time predictor intervention, primary v3

This is a new matched replay of the original 180 primary conditions. It does not
replace or relabel the 483 v2 campaign results. The intervention is the jointly
deployed final wall-time regressor, training-derived role priors, and training-only
Slack guard. It does not isolate the contribution of those three components.

The two models, three nominal loads, five policies, five fixed failure identities
plus F0, 62 workflow identities/order, all 503 Agent tasks, arrival timestamps,
tokens, output reservations, model timing profiles, hardware, L/K, and all config
fields other than `slack_guard_ns` are preserved. `INPUT_MATCH.json` records these
comparisons against the original `formal-core-v2-corrected` inputs. The predictor
latency remains the original configured 0.1 ms; no new physical inference latency
measurement is claimed.

`PROTOCOL.json` and `PROTOCOL_SEAL.json` are written before any simulation. The
original core implementation and its ancillary import support are copied from
the original sealed campaign. The new predictor implementation is copied from
the sealed training run. `MANIFEST.json` records each source's origin and hash.
The standalone bootstrap rejects any MoonKVSim import outside this snapshot.
Later general-CLI support for the wall-time model is a separate delivery change;
it does not alter this campaign's frozen CLI or runtime.

The serialized models were fitted on the same disjoint 12 training workflows
(95 Agents) using six healthy model/load conditions. Their labels include
queueing and end at the same Agent's final completion. The regressor uses signed
text hashing and numeric causal Context features; it is not a validated semantic
encoder. Workflow-held-out cross-fitting supplies the guard: 910,471,105 ns for
8B and 995,028,646 ns for 32B. The reference CPM used in training is conditioned
on realized healthy queueing and is not a counterfactual no-delay Slack oracle.
Training provenance and its fixed calibration rule are linked in `training/`.

The six healthy `none` runs execute first and retain actual submission Contexts,
post-completion labels, and every signed prediction error. `HELDOUT_ERROR.json`
summarizes the 62 held-out workflows, separately by model/load; its 3,018 rows
are not 3,018 independent samples. No held-out outcome is used for fitting,
guard calibration, hyperparameter choice, or selecting conditions. These healthy
errors do not establish accuracy after failures or under other policies.

The predeclared transparency validation repeats only 8B/load0.65/none/F0 with
the base runtime and the identical deployed predictor. It checks exact summary
bytes and decompressed event/flow bytes against the observed run. This is one
validation replay, not an additional experimental sample. Unit regressions also
check nonempty detailed logs with none, DRAM, and AegisKV.

Execution uses a detached process with at most two worker processes. `run.log`,
`launches/`, `RUN_IMPORTS.json`, per-run `RUN_START.json`, `COMPLETE.json`,
`RUNS.json`, and `STATUS.json` retain execution and binding evidence. A complete
marker requires exact output, zero terminal allocations, and no oracle output
reservation. Reuse verifies model/input/output hashes; incomplete run directories
are retained and rejected rather than overwritten. Until every condition and
the independent resource/identity audit completes, the campaign remains partial.

This remains a modeled FCFS, one-active-request-per-worker, batch-one-profile
simulation. It does not establish production continuous-batching behavior,
native sparse-kernel timing, physical failure recovery, or end-to-end production
benefits. All adverse and negative paired results must be retained.

Preparation and launch commands (repository root, using the existing venv):

```bash
PYTHONPATH=python .venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_walltime_primary.py prepare \
  --original benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v2-corrected \
  --training benchmark/AegisKV/experiments/evaluation-20260924/reviews/walltime-predictor-training-v1 \
  --out benchmark/AegisKV/experiments/evaluation-20260924/walltime-primary-v3
PYTHONPATH=python .venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_walltime_primary.py launch \
  --out benchmark/AegisKV/experiments/evaluation-20260924/walltime-primary-v3 --workers 2
```

Preparation requires a nonexistent destination. This README was added while the
initial prepare process was running; it is descriptive documentation outside the
immutable input seal. To reproduce elsewhere, choose a new destination.
