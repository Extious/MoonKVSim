# AegisKV design input on `main`

This directory contains the immutable patent input, its machine-auditable
transcription, and provenance checks required before the future `aegiskv`
branch is created.

It does **not** contain an AegisKV runtime or experiment result on `main`.
The `aegiskv` branch may only be created from the accepted
`v0.1.0-mooncake-baseline` tag. Historical Mooncake/SGLSim assets will then be
selected one file at a time through a source manifest; they are never imported
as a directory and never gain a stronger evidence class merely by being copied.

Verify the current design bundle from the repository root:

```bash
uv run python benchmark/AegisKV/docs/audit_patent_contract.py
sha256sum --strict -c benchmark/AegisKV/docs/provenance/SHA256SUMS
```
