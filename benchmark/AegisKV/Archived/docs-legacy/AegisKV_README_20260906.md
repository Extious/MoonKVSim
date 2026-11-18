# AegisKV on the tag-derived `aegiskv` branch

This directory is the AegisKV experiment and paper tree. The MoonKVSim
simulator library lives outside it. On this branch the library is the
AegisKV-modified Mooncake simulation; patent input, experiment configs, run
scripts, published results, and paper figures stay here.

**设计与实现对比：**[Mooncake 本身、AegisKV on Mooncake、AegisKV on MoonKVSim](../../docs/development/mooncake-aegiskv-three-way-design-implementation.md)。涵盖架构、三个算法、元数据与 API、双层复制、故障恢复、实际执行路径及验证边界。
配套架构图、论文和专利材料见 [文档索引](docs/README.md)。

The branch was created from the accepted `v0.1.0-mooncake-baseline` tag. The
exact six-run baseline evidence binding is recorded in
`experiments/baseline-tag-evidence.json`. Historical Mooncake/SGLSim assets are
selected one file at a time through a source manifest; they are never imported
as a directory and never gain a stronger evidence class merely by being copied.

All current runtime and experiment evidence is CPU-executed deterministic-event
simulation with modeled scheduler, HBM-accounting, and transfer semantics. It is
`modeled/preliminary`, `not_calibrated`, and capped at E2. It is not physical
GPU/CUDA/NCCL/PCIe/RDMA/Slurm execution evidence and is not a paper-ready claim.
The patent contract remains machine-transcribed with manual review pending.

The current experiment contract machine-locks `Qwen/Qwen3-8B`, DP=8, TP=1,
PP=1, and a modeled single-node 8x NVIDIA A100-40GB host (40 GiB HBM per GPU).
Those three layers are
`experiments/configs/{requests,failure,engine}.json`.
The formal Qwen3-8B sweep contract is
`experiments/FULL_ALGORITHM_SIMULATION_CONTRACT.md`, with current defect and
evidence status in `experiments/SIMULATION_AUDIT_2026-09-01.md`. The sweep has
seven unique paired `(failure_count, workflow_concurrency)` dimensions. With
seeds 0--4 and two variants, it requires 70 variant-seed runs and materializes
35 paired raw-seed cells, seven aggregate cells, and 20 per-seed/per-concurrency
canonical-plan checkpoints.

At concurrency 16, each seed derives one causal-recursive F8 plan and freezes
nested F1/F2/F4/F8 subsets. At concurrency 8, 24, and 32, each seed derives a
direct causal-recursive F2 plan. Both variants receive the same canonical logical
focus IDs selected by a two-profile causal oracle, while retaining natural variant-local GPU
routing and virtual timing. The enclosing sweep and variant-run checkpoint
schemas are v4; canonical-plan checkpoints and per-cell
`paper_sweep_statistics` are v3. Negative, zero, and confidence intervals that
cross zero are retained effect estimates and never block artifact generation. A
positive point estimate whose 95% confidence-interval lower bound exceeds zero
is required only before the result is described as a clear advantage.

The last published full matrix remains
`experiments/results/e2-qwen3-8b-dp-all-v1/`
(2,760 rows over DP={2,4,8} and 80-GiB HBM) and is now a superseded snapshot.
A replacement DP=8 A100-40GB matrix has not been published yet. F12 remains
excluded because no physical calibration experiment was requested.
`e2-initial-v1` is retained as an earlier legacy bundle.
The config directories on these migrated historical releases are reconstructed
snapshots and therefore are not retroactively hash-bound by their original
manifests. The auditor checks their values and labels them
`reconstructed_unbound`; future publications bind the three config hashes
atomically and must report `manifest_bound`.

The follow-up fluid-core preview is
`experiments/results/e2-fluid-core-v2/`, with three focused resource/recovery
figures at `experiments/results/figures/e2-fluid-core-v2/` and interpretation
in `experiments/results/e2-fluid-core-v2/FLUID_CORE_V2_REPORT.md`.

The focused Store-transport matrix is
`experiments/results/e2-transport-v1/`, with audited figure F17 at
`experiments/results/figures/e2-transport-v1/` and interpretation in
`experiments/results/e2-transport-v1/TRANSPORT_V1_REPORT.md`.

The focused multi-Store-node matrix is
`experiments/results/e2-store-nodes-v1/`, with audited figure F18 at
`experiments/results/figures/e2-store-nodes-v1/` and interpretation in
`experiments/results/e2-store-nodes-v1/STORE_NODE_V1_REPORT.md`.

Patent materials and audit utilities are collected in [docs/patent](docs/patent/README.md).
Verify the patent input bundle from the repository root:

```bash
uv run python benchmark/AegisKV/docs/patent/audit_patent_contract.py
sha256sum --strict -c benchmark/AegisKV/docs/patent/SHA256SUMS
```

Audit superseded historical GlobalDES results and figures. These commands do not
validate the current canonical-plan paper sweep:

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/audit_aegiskv_e2_artifacts.py \
  --matrix-dir benchmark/AegisKV/experiments/results/e2-qwen3-8b-dp-all-v1 \
  --figure-dir benchmark/AegisKV/experiments/results/figures/e2-qwen3-8b-dp-all-v1

.venv/bin/python benchmark/AegisKV/experiments/scripts/audit_aegiskv_fluid_preview.py \
  --matrix-dir benchmark/AegisKV/experiments/results/e2-fluid-core-v2 \
  --figure-dir benchmark/AegisKV/experiments/results/figures/e2-fluid-core-v2

.venv/bin/python benchmark/AegisKV/experiments/scripts/audit_aegiskv_transport_preview.py \
  --matrix-dir benchmark/AegisKV/experiments/results/e2-transport-v1 \
  --figure-dir benchmark/AegisKV/experiments/results/figures/e2-transport-v1

.venv/bin/python benchmark/AegisKV/experiments/scripts/audit_aegiskv_store_node_preview.py \
  --matrix-dir benchmark/AegisKV/experiments/results/e2-store-nodes-v1 \
  --figure-dir benchmark/AegisKV/experiments/results/figures/e2-store-nodes-v1
```
