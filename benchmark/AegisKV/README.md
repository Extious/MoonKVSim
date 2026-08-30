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

Verify the current design bundle from the repository root:

```bash
uv run python benchmark/AegisKV/docs/audit_patent_contract.py
sha256sum --strict -c benchmark/AegisKV/docs/provenance/SHA256SUMS
```
