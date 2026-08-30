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

The current complete E2 simulation bundle is available at
`experiments/e2-qwen3-8b-dp-all-v1/`, with preliminary SVG paper figures at
`experiments/figures/e2-qwen3-8b-dp-all-v1/` and an evidence-bounded
interpretation in `experiments/QWEN3_8B_DP_ALL_V1_REPORT.md`. It contains 2,760
rows and 1,380 exact A/B pairs across three seeds. It machine-locks
`Qwen/Qwen3-8B`, fixes TP=1 and PP=1, and varies only DP in {2, 4, 8}. The
offline matrix/figure audit passes; F12 is explicitly excluded because no
physical calibration experiment was requested. `e2-initial-v1` is retained as
a superseded legacy bundle.

The follow-up fluid-core preview is available at
`experiments/e2-fluid-core-v2/`, with three focused resource/recovery figures at
`experiments/figures/e2-fluid-core-v2/` and interpretation in
`experiments/FLUID_CORE_V2_REPORT.md`. It uses work-conserving weighted max-min
fluid contention and event-boundary per-GPU HBM account stacks. It remains E2,
modeled/preliminary, and not calibrated.

The focused Store-transport matrix is available at
`experiments/e2-transport-v1/`, with audited figure F17 at
`experiments/figures/e2-transport-v1/` and interpretation in
`experiments/TRANSPORT_V1_REPORT.md`. It compares GDR, RDMA Host-staged, and TCP
Host-staged paths over all five context buckets without invoking a physical
network.

The focused multi-Store-node matrix is available at
`experiments/e2-store-nodes-v1/`, with audited figure F18 at
`experiments/figures/e2-store-nodes-v1/` and interpretation in
`experiments/STORE_NODE_V1_REPORT.md`. It compares one, two, and four modeled
Store nodes under a fixed 64-GiB total capacity budget. Its endpoint rates and
results remain uncalibrated E2 assumptions rather than physical scale-out
evidence.

Verify the current design bundle from the repository root:

```bash
uv run python benchmark/AegisKV/docs/audit_patent_contract.py
sha256sum --strict -c benchmark/AegisKV/docs/provenance/SHA256SUMS
```

Audit the current GlobalDES results and figures:

```bash
.venv/bin/python scripts/audit_aegiskv_e2_artifacts.py \
  --matrix-dir benchmark/AegisKV/experiments/e2-qwen3-8b-dp-all-v1 \
  --figure-dir benchmark/AegisKV/experiments/figures/e2-qwen3-8b-dp-all-v1

.venv/bin/python scripts/audit_aegiskv_fluid_preview.py \
  --matrix-dir benchmark/AegisKV/experiments/e2-fluid-core-v2 \
  --figure-dir benchmark/AegisKV/experiments/figures/e2-fluid-core-v2

.venv/bin/python scripts/audit_aegiskv_transport_preview.py \
  --matrix-dir benchmark/AegisKV/experiments/e2-transport-v1 \
  --figure-dir benchmark/AegisKV/experiments/figures/e2-transport-v1

.venv/bin/python scripts/audit_aegiskv_store_node_preview.py \
  --matrix-dir benchmark/AegisKV/experiments/e2-store-nodes-v1 \
  --figure-dir benchmark/AegisKV/experiments/figures/e2-store-nodes-v1
```
