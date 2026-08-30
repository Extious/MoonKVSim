# AegisKV GlobalDES fluid-core v2 preliminary report

## Evidence boundary

This bundle is an **E2 modeled/preliminary** result produced by CPU-only metadata
simulation. It is not calibrated, paper-ready, or evidence of physical hardware
performance. No CUDA kernel, model inference, network transfer, Slurm job, sleep,
or wall-clock timing measurement was executed.

The v2 core bundle supplements rather than replaces `e2-initial-v1`:

- v1 remains the frozen 46-variant initial matrix and 14-figure preview;
- v2 binds the higher-fidelity fluid-contention and HBM-ledger implementation;
- v2 currently covers the seven core systems only, with two seeds;
- ablation and sensitivity results in v1 must not be mixed with v2 core values.

## Frozen implementation and matrix

- implementation commit: `cd21355e11055eb336953684c855250c41496b70`
- implementation tree: `aeee99f78166771198ef621b7beb0da2eeb7f5dc`
- communication backend: sliced, work-conserving weighted max-min fluid flows
- clock: one nanosecond `GlobalDES.now_ns` per fresh run
- topology rate resources: per-GPU HBM path, Peer fabric, Store fabric, Store DRAM
- GPU HBM: one closed 80-GiB ledger per physical GPU
- recovery transaction order: destination reserve, staging acquire, fluid transfer,
  staging release, restored/recomputed KV materialization, request release
- failure semantics: failed GPU HBM becomes entirely `UNAVAILABLE_CAPACITY`

Matrix cross product:

- 7 core systems;
- 5 context buckets: 8K, 32K, 64K, 96K, 128K;
- `no_failure` and `GPU_FAILURE`;
- seeds 0 and 1;
- fresh deterministic repeats A and B;
- 280 result rows, 140 matched A/B pairs, 10 frozen failure schedules.

Publication identity:

- matrix manifest fingerprint:
  `38c49bc4707f514a446b53d9ff7a9d550f6340351347704e70c808b1f908e1c6`
- matrix manifest SHA-256:
  `824ee24550c055e1ead2de8ab805cbad1beaeb1fd4861229a5abad28226d382c`
- results SHA-256:
  `c5f27c6b152a50b8d01fb960cd51950a84d2ca2311f8319c90559a34d572ce45`
- statistics SHA-256:
  `3a5455a97ed745346da45757542d0e8d375c01e21d6379d85ff81272e3e2ac7c`
- representative-run SHA-256:
  `6b8abe56277ef1df763f172b5d266cabea7f0c12e44e631825e5247fa897e006`

## Preliminary result snapshot

The table compares full AegisKV unified management with Vanilla Mooncake DRAM
under matched `GPU_FAILURE` workloads. Percentages are two-seed means. The
95% interval is a Student-t interval with only one degree of freedom, so its
main use here is to expose uncertainty rather than establish a claim.

| Bucket | Mean WCT delta | WCT interval sign | Mean goodput delta | Recovery observation |
|---|---:|---|---:|---|
| 8K | -0.197% | below zero | +0.259% | same modeled recovery latency and recompute |
| 32K | -0.261% | crosses zero | +0.138% | latency -38.0%; 4,096 more restored tokens |
| 64K | -0.313% | below zero | +0.173% | no restored-token difference |
| 96K | -0.699% | crosses zero | +0.554% | latency mean -5.6%, interval crosses zero |
| 128K | -0.073% | crosses zero | +0.147% | latency mean +9.2%; restoration is unstable |

The v2 result therefore does **not** support a blanket AegisKV performance win.
Only 8K and 64K keep the two-seed WCT interval below zero. Every goodput interval
crosses zero. The 32K failure cell shows a useful recovery-local signal, while
the representative 128K cell has no restorable committed replica and performs
full prompt recomputation.

Resource cost is material:

- aggregate Peer-HBM peak across four GPUs is 21.52--28.69 GiB;
- modeled network byte-time rises by 19.9--69.3% versus Vanilla across buckets;
- HBM-path busy time rises by 58.4--72.9% in the two-seed means;
- both systems fill the modeled 64-GiB Store pool in these cells;
- every HBM snapshot conserves the 80-GiB physical ledger and has
  `UNATTRIBUTED_RESERVE=0`;
- final healthy-GPU recovery reserve, staging, and active primary accounts are zero;
- the failed GPU finishes with all 80 GiB in `UNAVAILABLE_CAPACITY`.

## Focused v2 preview figures

Three SVGs are generated directly from the canonical v2 matrix and its bound
representative run:

1. `F3V2` -- full per-GPU HBM account stacks at every event boundary;
2. `F5V2` -- Peer/Store/GPU-HBM utilization over compressed active fluid epochs;
3. `F16` -- recovery destination reserve, staging, active KV, and Peer-HBM state.

The representative run is
`core:aegiskv_unified:128k:gpu_failure:seed-0:repeat-A`. It contains 353 fluid
rate intervals. Active flow time is 5.773 virtual seconds inside a 10,955.4-second
wall-window. Its recovery target reserves 16.40 GiB; staging remains zero because
that cell has no restorable committed replica. This zero is an observed modeled
result, not a missing series.

- figure manifest SHA-256:
  `cc102fbd7f7bf30c105184e1925f3ff23893a2abc21a18411ec05e37ebccf753`
- generator source SHA-256:
  `ecf8400113cd7a8064f7de5d2093c363fe50a9830470d724f5cefba30c3c854d`
- offline audit: PASS, 3 figures, 280 matrix rows, 140 pairs,
  `physical_execution=false`, `slurm_used=false`

## Verification

- AegisKV tests: `140 passed`;
- full repository: `750 passed, 1 skipped`;
- Ruff: PASS;
- strict mypy: PASS for 91 source files;
- focused preview renderer/auditor tests: included in the 140-test AegisKV gate;
- core matrix completeness, A/B determinism, byte conservation, rate capacity,
  HBM capacity conservation, artifact hashes, representative binding, SVG XML,
  provenance, and no-physical-execution boundaries: PASS.

## Remaining blockers

- only two v2 seeds; intervals are too wide for stable general conclusions;
- v2 ablation and sensitivity matrices have not yet been rerun;
- no physical calibration or external network-simulator cross-validation;
- no TP/PP topology, registration worker, or discrete copy-engine lane model;
  the later focused `e2-transport-v1` bundle covers modeled RDMA/TCP/GDR paths
  and Host-DRAM staging transactions, while `e2-store-nodes-v1` covers
  fixed-total-capacity multi-Store placement;
- primary-KV bytes use the declared source-derived Qwen3-8B TP1/PP1 layout;
- source hash-block coverage is not tokenizer-equivalent 128K token evidence;
- F12 simulator-accuracy evidence remains intentionally unavailable;
- manual patent-contract review remains pending.
