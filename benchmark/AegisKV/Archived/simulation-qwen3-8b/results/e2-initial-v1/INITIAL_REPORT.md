# AegisKV GlobalDES initial E2 report

> Legacy bundle: this report is retained for history. The current Qwen3-8B
> DP-only full matrix is `e2-qwen3-8b-dp-all-v1` and its report is
> `QWEN3_8B_DP_ALL_V1_REPORT.md`. The current strict auditor intentionally
> rejects this legacy bundle because its rows predate the explicit
> `model_deployment` contract.

This is the first complete, auditable simulation-only result bundle for the
MoonKVSim AegisKV branch. Every run uses a single nanosecond global virtual
clock over CPU metadata. No CUDA, physical inference, network I/O, RDMA, or
Slurm execution occurred.

## Frozen inputs and outputs

- simulator implementation: `b73b51f34873e7543fbb7d56e4fd037dfa647963`;
- implementation tree: `ab84d4560d5c4cad965a5b5424ffb92c096e93a5`;
- workload: 117 unmodified real Weka trace spans from two workflows;
- context evidence: source hash-block-64 shape replay with observed 8K, 32K,
  64K, 96K, and 128K buckets; this is not target-tokenizer-equivalent evidence;
- scenarios: no failure and the only supported fault type, `GPU_FAILURE`;
- seeds: 0, 1, and 2; repeat A is the statistical observation and repeat B is
  an exact-determinism replay, not another independent sample;
- matrix: 46 variants, 2,760 result rows, 1,380 exact A/B pairs, and 285 frozen
  failure schedules;
- matrix manifest fingerprint:
  `e8b5da31e0fc61eaea2450ed307f69b37e91fc766837e93c60e020189994ce18`;
- figure manifest SHA-256:
  `2c843b6a5c2a8beeec3c83cb573f283c08fb2a0db9c2d04f32718e8a56a9af64`.

The canonical matrix is in `e2-initial-v1/`; the figure set is in
`figures/e2-initial-v1/`. `statistics.json` contains deterministic per-seed
means, conservative two-sided 95% Student-t intervals, source-bound samples,
and paired effects. All timing values remain modeled, preliminary, and not
calibrated.

## Preliminary observations

The following diagnostic comparison uses matched repeat-A rows for full
AegisKV and Vanilla Mooncake DRAM under `GPU_FAILURE`, paired by bucket and
seed. Negative WCT delta favors AegisKV. These are whole-workload results; the
bucket names the failure-focus cell rather than a different workload.

| Failure-focus bucket | Vanilla mean WCT (s) | AegisKV mean WCT (s) | Delta (s) | Relative delta |
| --- | ---: | ---: | ---: | ---: |
| 8K | 6342.427 | 6329.289 | -13.138 | -0.207% |
| 32K | 6343.214 | 6312.913 | -30.301 | -0.478% |
| 64K | 6353.166 | 6320.923 | -32.242 | -0.508% |
| 96K | 6359.455 | 6328.143 | -31.311 | -0.492% |
| 128K | 6347.065 | 6323.906 | -23.159 | -0.365% |

The result is deliberately not presented as a broad performance win:

- only the 8K WCT delta has a three-seed 95% interval that remains below zero;
  the 32K--128K intervals cross zero;
- modeled goodput changes are very small and their failure-case intervals
  generally cross zero;
- restored-token and recomputation benefits are sparse and unstable across
  buckets; the 128K comparison is negative in this initial parameterization;
- AegisKV adds substantial Peer-HBM, Store-DRAM, network byte-time, and copy
  engine cost, as shown in F13 and F14;
- the result motivates further policy and contention-model refinement rather
  than supporting a paper-ready causal claim.

## Initial figures

- F1: modeled system architecture;
- F2: GPU failure recovery timeline;
- F3--F5: Peer-HBM, Store DRAM, and KV-transfer timelines;
- F6--F9: WCT/goodput, recovery, coverage/recompute, and ablation diagnostics;
- F10--F11: budget, scale, fabric, detection, and reroute sensitivity;
- F13--F15: resource cost, peak/mean occupancy, and real-trace coverage;
- F12: intentionally excluded because simulator accuracy would require a
  physical calibration experiment, which is outside the requested scope.

Run the fail-closed offline audit from the repository root:

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/audit_aegiskv_e2_artifacts.py \
  --matrix-dir benchmark/AegisKV/experiments/results/e2-initial-v1 \
  --figure-dir benchmark/AegisKV/experiments/results/figures/e2-initial-v1
```

That command describes the historical audit used at publication time. Use the
current bundle and command in `QWEN3_8B_DP_ALL_V1_REPORT.md` for a present-day
`PASS` audit.
