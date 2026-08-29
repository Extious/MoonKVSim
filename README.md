# MoonKVSim

MoonKVSim is an offline, metadata-only discrete-event simulator for vLLM-style
inference and a Mooncake DRAM Store. Every simulated component advances through
one monotonic global virtual clock.

The implementation contract is [MOONKVSIM_PLAN.md](MOONKVSIM_PLAN.md). This
checkout contains M0--M5 E1/E2 implementation and directed semantic evidence.
It has no accepted baseline commit/tag, accepted repeated real-trace run, E3
calibration, E4 matched validation, or E5/paper-ready AegisKV result yet.

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

## Physical protected-job contract

The Vanilla Mooncake physical preflight and harness are read-only observers of
other Slurm jobs. Jobs `136567`, `135889`, `135847`, and `135326` are a hard
gate and must each be visible as `PENDING` in `squeue`. Jobs `142290` and
`142291` are monitored, not held: they may naturally be `PENDING`, `RUNNING`,
`COMPLETED`, `FAILED`, or another scheduler state. Their snapshots combine
optional `squeue` visibility with a required, well-formed root-job `sacct`
record, so normal completion and disappearance from `squeue` do not permanently
block the experiment. Pre-run and post-run snapshots are validated separately;
their states are never required to remain equal, and neither path mutates jobs.

The simulator CLI is installed as `moonkv-sim`. Raw traces remain in their
access-controlled source location; manifests record hashes and provenance.
