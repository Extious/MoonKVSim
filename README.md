# MoonKVSim

MoonKVSim is an offline, metadata-only discrete-event simulator for vLLM-style
inference and a Mooncake DRAM Store. Every simulated component advances through
one monotonic global virtual clock.

The implementation contract is [MOONKVSIM_PLAN.md](MOONKVSIM_PLAN.md). The
tagged Vanilla M0--M5 baseline and the first AegisKV M6--M9 simulation release
are present. The current AegisKV release contains a Qwen3-8B-only, DP-only
2,760-row matched matrix on the latest fluid-contention/HBM-ledger model, plus
the earlier focused Store-transport and fixed-capacity multi-Store-node sweeps
and preliminary SVG paper figures. TP and PP are fixed at one and are not
experimental dimensions. The current delivery scope
intentionally stops at E2 modeled simulation; E3 physical calibration, E4
real-system matching, and E5/paper-ready claims are out of scope.

Current gate-by-gate evidence is tracked in
[docs/development/milestone-status.md](docs/development/milestone-status.md).

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

Historical helpers under `scripts/physical/` are retained only as out-of-scope
higher-evidence references. They are neither invoked nor required by the E2
delivery gate.

The simulator CLI is installed as `moonkv-sim`. Raw traces remain in their
access-controlled source location; manifests record hashes and provenance.
