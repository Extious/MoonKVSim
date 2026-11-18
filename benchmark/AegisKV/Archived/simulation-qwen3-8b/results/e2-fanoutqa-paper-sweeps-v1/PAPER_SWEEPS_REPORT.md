# AegisKV Qwen3-8B paper-sweep report

## Evidence status

This run is deterministic, CPU-only GlobalDES evidence (`E2`, modeled/preliminary,
not calibrated). It is not a physical A100/NCCL/RDMA measurement and is not yet
paper-ready empirical evidence. The figure layout is insertion-ready; the numeric
claims remain simulation results.

The full result artifact has document fingerprint
`d877854c7c38bc234d773acdfb115e3d8e36ebb07bfd23fefb15a1c3713ef978`
and file SHA-256
`9e33bad86efc8c9031aa584422de2dc4259eb266301ad8cc1689d4330f2443da`.
All Mooncake and AegisKV cells passed fresh-run A/B hash equality.

## Protocol

- Model: Qwen/Qwen3-8B; DP=8, TP=1, PP=1; modeled 8 x A100-40GB node.
- Workload: exactly 160 independent FanOutQA workflows and 1,304 model-request
  spans, with workflow concurrency 16 for the base cell.
- Failure: `GPU_FAILURE`, two injections in the base cell, fixed two-minute
  virtual repair time, zero modeled detection delay.
- Failure-count scale: 1, 2, 4, and 8 failures at concurrency 16.
- Workflow-concurrency scale: 8, 16, 24, and 32 at two failures. Concurrency 16
  is the shared base cell.
- Failure schedules are independently derived per system at matched logical
  workload progress (`variant_local_shared_logical_progress`).
- Seed: 0. Each system/cell is executed twice from fresh state and must produce
  identical payload, journal, span-detail, and representative hashes.

The frozen workload has no truncation, padding, span slicing, workflow
concatenation, or synthesis. The model limit is 131,072 tokens, but the maximum
observed context in this frozen workload is 86,214 tokens and the 128K bucket is
empty; this run therefore does not establish observed 128K-request coverage.

## Base cell: F=2, C=16

Mean WCT gain is defined as `(Mooncake mean - AegisKV mean) / Mooncake mean`.

| Metric | Mooncake | AegisKV | Observation |
|---|---:|---:|---|
| Mean WCT | 36.449 s | 36.790 s | -0.934% gain; AegisKV regresses |
| Median WCT | 33.718 s | 34.411 s | AegisKV is 2.05% slower |
| P95 WCT | 67.419 s | 58.350 s | AegisKV improves P95 by 13.45% |
| Maximum WCT | 95.519 s | 100.838 s | AegisKV maximum is worse |
| Restored GPU-HBM tokens | 0 | 0 | no GPU restoration in either system |
| Restored Store-DRAM tokens | 57,344 | 29,696 | AegisKV restores 48.21% fewer |
| Recomputed tokens after failure | 46,084 | 37,371 | AegisKV reduces recompute by 18.91% |
| Mean recovery latency | 26.002 s | 30.571 s | AegisKV is slower |

The ECDFs cross. There is no clear whole-distribution left shift: AegisKV has a
better P95 but a worse mean, median, and maximum. The requested hypothesis of a
clear AegisKV left shift is therefore not supported by this base run.

The selected AIMD trace is `gpu-2`, which has 718 control observations and 158
pressure events. Every pressure observation maps to a multiplicative decrease,
every additive-increase action adds 0.05 up to the 0.5 cap, and stable windows
hold the prior alpha: 0 transition violations. Across all ranks the base run has
762 additive increases, 1,084 multiplicative decreases, and 3,410 stable-window
observations. Thus the controller obeys its AIMD transition rules, although the
resulting time series is workload-driven and is not a smooth monotone curve.

For failure-impacted restoration, the requested hypothesis that AegisKV reuses
more KV in both GPU and DRAM is not supported: GPU restoration is tied at zero,
and AegisKV restores fewer DRAM tokens. AegisKV does reduce recompute tokens, but
that distinct benefit must not be relabeled as GPU/DRAM reuse.

## Scale results

### Failure-count scale at C=16

| Failures | Mean WCT gain vs. Mooncake | Mean alpha at control events |
|---:|---:|---:|
| 1 | -0.019% | 0.07837 |
| 2 | -0.934% | 0.07817 |
| 4 | +0.390% | 0.07682 |
| 8 | -0.398% | 0.07457 |

Only F=4 is positive. Gain is not monotone in failure count, and mean alpha
slightly decreases rather than increasing. The F=8 hard gate passed for both
systems: 8 schedule events, 8 executed failures, 8 scheduled repairs, and 8
completed repairs, with fresh A/B determinism passing.

### Workflow-concurrency scale at F=2

| Workflow concurrency | Mean WCT gain vs. Mooncake | Mean alpha at control events |
|---:|---:|---:|
| 8 | -0.072% | 0.07308 |
| 16 | -0.934% | 0.07817 |
| 24 | -0.949% | 0.07318 |
| 32 | +0.232% | 0.07652 |

Only C=32 is positive. Gain is not monotone, and mean alpha neither decreases
monotonically nor reaches zero. Individual pressure responses can approach zero;
the event-weighted mean remains about 0.073--0.078.

## Figure and data artifacts

- `fig1_base_wct_cdf.{pdf,png,svg}`: base WCT ECDF.
- `fig2_base_aimd_pressure.{pdf,png,svg}`: selected-rank request pressure and
  alpha over virtual time.
- `fig3_base_failure_kv_reuse.{pdf,png,svg}`: failure-impacted restored KV tokens.
- `fig4_failure_scale.{pdf,png,svg}`: failure-count WCT gain and alpha summary.
- `fig5_concurrency_scale.{pdf,png,svg}`: concurrency WCT gain and alpha summary.
- `figure-data.csv`: exact plotted aggregates.
- `CAPTIONS.md`: compact figure captions and evidence caveat.

All five final PDFs were rendered back to raster and visually inspected. The
final layouts have no detected text overlap or clipping and retain publication-
sized fonts. Figure 5 uses vertical panels to preserve legibility for the
8/16/24/32 concurrency ticks.

Qwen3-32B was not run, as requested.
