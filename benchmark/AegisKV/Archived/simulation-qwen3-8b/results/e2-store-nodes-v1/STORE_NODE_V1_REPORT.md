# AegisKV GlobalDES multi-Store-node v1 preliminary report

## Evidence boundary

This is an **E2 modeled/preliminary**, **not calibrated** CPU metadata-only
simulation. It does not execute CUDA, model inference, a physical network,
Mooncake services, Slurm, sleeps, or wall-clock performance measurement. Every
Store-node rate is an explicit simulator assumption rather than a measured
hardware property.

## Frozen matrix

- implementation commit: `9888e82fb42884308af83a79c0509990c2d2c125`
- implementation tree: `2de4dbcda827098448e8f1b2275d77132dfe7963`
- variants: 1, 2, and 4 Store nodes
- total Store capacity: fixed at 64 GiB for every variant
- per-node Store capacity: 64, 32, and 16 GiB respectively
- modeled per-node RDMA fabric and DRAM rate: 25 GB/s each
- placement: stable SHA-256 policy-chunk placement across physical Store segments
- context buckets: 8K, 32K, 64K, 96K, 128K
- scenarios: `no_failure`, `GPU_FAILURE`
- independent seeds: 0 and 1
- deterministic repetitions: fresh A and B GlobalDES instances
- result rows: 120
- exact A/B pairs: 60
- shared logical failure schedules: 10
- only fault type: `GPU_FAILURE`

Each physical Store node has an independent DRAM ledger and independent RDMA
and TCP fabric resources. Protection and recovery transfers are split by their
actual Store segment. The total Store byte budget is conserved across the
partition, every per-segment ledger is valid, and every run finishes with zero
pending destination bytes and zero source pins.

Publication identity:

- matrix manifest fingerprint:
  `b1c9fd553159deaa3f4a2ab15078af959a322cee4504459fa3a298aa69410782`
- matrix manifest SHA-256:
  `181746cf366ae2868976c5b40708436802ae7e20ea15881ba663bb6e7aeb697b`
- results SHA-256:
  `6d0abe1da897769bb2e99c53182b2d24a615ad55e44a5f3a99c0541b002e8aa8`
- statistics SHA-256:
  `1750483fe215793f47adcb55c264e6b677ddd55f4b0c2a7f8fa44b07a5218d44`
- representative-run SHA-256:
  `18a250ae0d4944397d07428436ae64c5d559783a323cd8c2993c9fd3efd8611e`

## Preliminary result snapshot

The table reports two-seed repeat-A means for matched `GPU_FAILURE` cells.
Positive WCT delta means slower than the same-bucket, same-seed one-node
baseline. Network byte-time is transferred bytes multiplied by modeled service
time; it is not physical traffic, power, or elapsed time.

| Bucket | 2-node WCT delta | 4-node WCT delta | 2-node network ratio | 4-node network ratio |
|---|---:|---:|---:|---:|
| 8K | +0.0770% | +0.0854% | 0.640x | 0.422x |
| 32K | +0.0699% | +0.0739% | 0.610x | 0.392x |
| 64K | +0.0494% | +0.0720% | 0.622x | 0.409x |
| 96K | +0.1464% | +0.1194% | 0.650x | 0.417x |
| 128K | +0.0827% | +0.0714% | 0.582x | 0.378x |

Independent modeled endpoints reduce network byte-time materially, but the
whole-workload WCT means are all slightly worse. The two-node WCT seed range
crosses zero at 32K (-0.0023% to +0.1422%) and 64K (-0.0135% to +0.1123%).
This matrix therefore does **not** support a blanket Store-node scaling win.
Partition-local eviction and changed HBM-flow interaction can offset the
modeled endpoint parallelism.

The 128K recovery composition is also non-monotonic:

| Store nodes | Mean restored tokens | Mean recomputed tokens | Restored seed range |
|---:|---:|---:|---:|
| 1 | 23,040 | 101,376 | 0--46,080 |
| 2 | 16,896 | 107,520 | 0--33,792 |
| 4 | 20,992 | 103,424 | 0--41,984 |

Seed 0 restores no Store prefix in any variant; seed 1 restores different
amounts after partition-local capacity pressure. With only two seeds, this is a
diagnostic interaction rather than an inferential result.

## Figure F18

`figures/e2-store-nodes-v1/f18-store-node-sensitivity.svg` contains:

1. whole-workload WCT delta versus the matched one-node baseline;
2. modeled network byte-time ratio versus the matched one-node baseline;
3. mean 128K restored and recomputed token composition.

Whiskers are the seed-0/1 range. Repeat B is used only for byte-exact
determinism and is never treated as an independent sample. Every plotted point
embeds its run IDs and payload hashes.

- figure SHA-256:
  `17b21978aafbba5dd8f65392a37b83b62311eb6ff8cae76102732ab13224211e`
- figure manifest SHA-256:
  `2509d48215fde4ded5c113782e397009c0d8b941d701fc35cb788bcff6927ce2`
- offline audit: PASS, 120 rows, 60 pairs, 1 figure,
  `physical_execution=false`, `slurm_used=false`

## Verification

- full repository: `757 passed, 1 skipped`;
- Ruff: PASS;
- strict mypy: PASS for 94 source files;
- matrix completeness, exact A/B replay, artifact hashes, per-segment capacity
  conservation, pending-byte/source-pin closure, figure determinism, point
  bindings, evidence boundaries, and SVG tamper rejection: PASS.

## Remaining limitations

- two seeds are insufficient for stable inferential conclusions;
- rates and endpoint independence are modeled assumptions, not calibrated facts;
- the fixed total capacity means this is not a capacity scale-out study;
- TP/PP topology remains unparameterized;
- primary KV layout remains the declared Qwen3-8B TP1/PP1 source-derived layout;
- source hash-block coverage is not tokenizer-equivalent 128K evidence;
- F12 simulator accuracy remains intentionally unavailable;
- this focused matrix does not replace the full ablation/sensitivity matrix.
