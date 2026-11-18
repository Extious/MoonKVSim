# MoonKVSim

MoonKVSim is an offline, metadata-only discrete-event simulator for vLLM-style
inference and a Mooncake DRAM Store. Every simulated component advances through
one monotonic global virtual clock.

The implementation contract is [MOONKVSIM_PLAN.md](MOONKVSIM_PLAN.md). The
tagged Vanilla M0--M5 baseline and the first AegisKV M6--M9 release are retained
alongside the separate current-design implementation below. Historical
Qwen3-8B/A100-40GB and 2,760-row DP matrices are not the configuration contract
for the new Agent-checkpoint campaigns. This delivery provides modeled
simulation, not physical calibration or validated production serving.

Current gate-by-gate evidence is tracked in
[docs/development/milestone-status.md](docs/development/milestone-status.md).

## Current Agent-checkpoint design (2026-09-24)

The current manuscript has a separate executable path in
[`python/moonkvsim/aegiskv/current/`](python/moonkvsim/aegiskv/current/):
Agent-level guarded Slack, threshold-selected complete Peer DRAM checkpoints,
additional first-L-layer Top-K Peer HBM replicas, and per-rank AIMD quotas.
It reuses GlobalDES, shared flow contention and byte-exact capacity transactions.
The live design version is `checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1`:
EOS cancels unnecessary cold restore work and invalidates incomplete local
history. `Config.slack_mode="zero"` is an explicit no-DAG-Slack control; the
default remains `"dag"`. Run it with `.venv/bin/python -m moonkvsim.aegiskv.current`;
see the
[implementation and reproduction guide](benchmark/AegisKV/docs/current-design-simulation.md)
and [design/code/test coverage](benchmark/AegisKV/docs/DESIGN_IMPLEMENTATION_COVERAGE.md).
This path uses one active FCFS invocation per DP, with no continuous batching.
AIConfigurator HYBRID model/TP timing grids remain uncalibrated end-to-end.
FanOutQA uses its original human-decomposed DAG with constructed prompts;
constructed mechanism workloads and previously captured native-selector CPU
diagnostics are separately labeled. The simulator does not run native attention
kernels, vLLM or Mooncake services.

The [evaluation guide](benchmark/AegisKV/docs/current-design-simulation.md#实验分组与冻结版本)
links each group's live status and audit: the sensitivity, finite-capacity
zero-Slack control and structural main matrix are complete; the profile main
matrix and structural scale extension have separate completion gates. In-flight
counts belong in those status files. The original formal/structural snapshots
pre-date EOS-fix1; newer sensitivity/ablation snapshots retain their own source
hashes and are not merged into a single source version.

## Mooncake-aligned prompt model (2026-09-06)

The historical AegisKV engine configuration selects `mooncake_prompt_v1`.
[Implementation alignment](benchmark/AegisKV/Archived/docs-legacy/paper/MOONCAKE_ALIGNMENT.md)
records ownership, routing, commit, copying and cleanup corrections against the
specified real Mooncake prototype. The
[revised paper](benchmark/AegisKV/Archived/docs-legacy/paper/REVISION_OVERVIEW.md) provides the
complete design and new paired evaluation. This remains a CPU prompt-protection
projection with idealized Slack and uncalibrated timing; it is not complete
physical-runtime equivalence. `legacy_v3` is retained for historical callers.

[Detailed three-way design and implementation comparison](benchmark/AegisKV/docs/mooncake-aegiskv-three-way-design-implementation.md)
compares native Mooncake, the real AegisKV extension, and the current simulator,
including algorithm/code mappings, evidence limits, and the verified 5-second
physical versus 1-second simulated AIMD interval difference.

## Branch contract

- `main` contains only the Vanilla Mooncake baseline. It may carry the immutable
  AegisKV patent input, but baseline runtime code must not read AegisKV policy.
- `aegiskv` may only be created from the accepted
  `v0.1.0-mooncake-baseline` tag.
- General simulator fixes land on `main` first and are then synchronized to
  `aegiskv`.

## Evidence contract

Design, static implementation, simulator semantics, component calibration,
end-to-end validation, and paper experiments are separate evidence classes
(`E0` through `E5`). Passing unit tests never implies calibrated timing or
paper readiness.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy python/moonkvsim
```

## Simulation-only delivery scope

- All experiments run as CPU metadata-only DES under one monotonic nanosecond
  virtual clock. No real GPU, CUDA, Slurm, or real vLLM/Mooncake execution is
  part of the delivery.
- GPU, HBM, DRAM, copy-engine, NIC, fabric, and Store resources are simulated
  identities with byte ledgers and availability calendars, not live devices.
- Timing and performance outputs are `modeled/preliminary` and
  `not_calibrated`. They may compare matched Vanilla and AegisKV simulations but
  may not claim hardware accuracy, calibrated performance, or paper readiness.
- The machine-readable boundary is `reference/simulation-scope.json`.

AegisKV paper, experiment assets and dedicated JSON schemas live under
[`benchmark/AegisKV/`](benchmark/AegisKV/README.md). Its simulator modules remain
under `python/moonkvsim/aegiskv/`, and its tests remain under `tests/aegiskv/`
so that package imports and the shared test suite keep working. General
MoonKVSim schemas remain under `schemas/`; model and AIConfigurator inputs
remain under `configs/`.

The simulator CLI is installed as `moonkv-sim`. Raw traces remain in their
access-controlled source location; manifests record hashes and provenance.
