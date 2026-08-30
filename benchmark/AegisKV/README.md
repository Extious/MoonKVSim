# AegisKV on the tag-derived `aegiskv` branch

This directory contains the immutable patent input, its machine-auditable
transcription, provenance checks, and branch-local AegisKV implementation and
experiment assets.

The branch was created from the accepted `v0.1.0-mooncake-baseline` tag. The
exact six-run baseline evidence binding is recorded in
`experiments/baseline-tag-evidence.json`. Historical Mooncake/SGLSim assets are
selected one file at a time through a source manifest; they are never imported
as a directory and never gain a stronger evidence class merely by being copied.

All current runtime and experiment evidence is CPU metadata-only GlobalDES,
`modeled/preliminary`, `not_calibrated`, and capped at E2. It is not a physical
GPU/CUDA/RDMA/Slurm experiment and is not a paper-ready claim. The patent
contract remains machine-transcribed with manual review pending.

The first complete E2 simulation bundle is available at
`experiments/e2-initial-v1/`, with preliminary SVG paper figures at
`experiments/figures/e2-initial-v1/` and an evidence-bounded interpretation in
`experiments/INITIAL_REPORT.md`. It contains 2,760 rows and 1,380 exact A/B
pairs across three seeds. The offline matrix/figure audit passes; F12 is
explicitly excluded because no physical calibration experiment was requested.

The follow-up fluid-core preview is available at
`experiments/e2-fluid-core-v2/`, with three focused resource/recovery figures at
`experiments/figures/e2-fluid-core-v2/` and interpretation in
`experiments/FLUID_CORE_V2_REPORT.md`. It uses work-conserving weighted max-min
fluid contention and event-boundary per-GPU HBM account stacks. It remains E2,
modeled/preliminary, and not calibrated.

Verify the current design bundle from the repository root:

```bash
uv run python benchmark/AegisKV/docs/audit_patent_contract.py
sha256sum --strict -c benchmark/AegisKV/docs/provenance/SHA256SUMS
```

Audit the initial GlobalDES results and figures:

```bash
.venv/bin/python scripts/audit_aegiskv_e2_artifacts.py \
  --matrix-dir benchmark/AegisKV/experiments/e2-initial-v1 \
  --figure-dir benchmark/AegisKV/experiments/figures/e2-initial-v1

.venv/bin/python scripts/audit_aegiskv_fluid_preview.py \
  --matrix-dir benchmark/AegisKV/experiments/e2-fluid-core-v2 \
  --figure-dir benchmark/AegisKV/experiments/figures/e2-fluid-core-v2
```
