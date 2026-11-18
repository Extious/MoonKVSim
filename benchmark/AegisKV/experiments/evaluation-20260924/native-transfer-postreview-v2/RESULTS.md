# Native raw-KV transfer component

All 864 prespecified component scenarios completed; independent timestamp/byte reconstruction passed. This is CPU replay of measured native selector indices, not execution of native recovery, generated-token timing, or workflow completion.

The unit is a PG19 document: three documents per model. The two adjacent M values, bandwidths, compute assumptions, layers and queries are paired conditions, not additional independent samples. Means and document ranges are descriptive; no CI.

## Zero-compute raw-transfer boundary

Primary M=32000; 32 GB/s. DRAM is total demanded raw-KV copy time. Positive gains mean less component time than DRAM. The exact zero-compute relation is demanded nonresident unique bytes / bandwidth; it is verified from copy events. These microsecond gains are not native inference or WCT gains.

| Model | DRAM mean (ms) | Current gain mean [range] (µs) | Recency gain (µs) | Oracle gain (µs) |
|---|---:|---:|---:|---:|
| NOSA-8B | 15.691776 | 131.072 [131.072, 131.072] | 131.072 | 131.072 |
| NSA-8B | 20.884139 | 131.072 [131.072, 131.072] | 131.072 | 131.072 |
| MiniCPM4.1-8B | 28.163413 | 127.659 [126.976, 129.024] | 131.072 | 131.072 |

## Compute-assumption sensitivity

Primary M=32000; 32 GB/s. Assumed compute is identical for every policy. Hit-compute overlap uses selected block-reference proportions; this is an uncalibrated sensitivity, not a matched native kernel profile. A positive Current-versus-Recency value means Current is faster. All signs are retained.

| Model | Assumed layer compute (µs) | Current gain vs DRAM (µs) | Current gain vs Recency (µs) |
|---|---:|---:|---:|
| NOSA-8B | 0 | 131.072 | 0.000 |
| NOSA-8B | 25.6 | 131.072 | 0.000 |
| NOSA-8B | 256 | 73.483 | -208.856 |
| NOSA-8B | 2560 | 300.718 | 0.000 |
| NSA-8B | 0 | 131.072 | 0.000 |
| NSA-8B | 25.6 | 131.072 | 0.000 |
| NSA-8B | 256 | 67.754 | -217.641 |
| NSA-8B | 2560 | 382.628 | -31.122 |
| MiniCPM4.1-8B | 0 | 127.659 | -3.413 |
| MiniCPM4.1-8B | 25.6 | 131.072 | 0.000 |
| MiniCPM4.1-8B | 256 | 131.072 | 0.000 |
| MiniCPM4.1-8B | 2560 | 209.544 | -110.588 |

## Retained signs and scope

- NOSA-8B: Current vs Recency is faster/equal/slower in 0/42/30 of 72 paired sensitivity conditions. Those 72 cases are not independent samples.
- NSA-8B: Current vs Recency is faster/equal/slower in 0/42/30 of 72 paired sensitivity conditions. Those 72 cases are not independent samples.
- MiniCPM4.1-8B: Current vs Recency is faster/equal/slower in 6/33/33 of 72 paired sensitivity conditions. Those 72 cases are not independent samples.

All policies share the same Current-derived layer-ordered background stream. Only prepared residency changes: 4 layers x 16 blocks x 65536 bytes = 4 MiB for Current, Recency and Oracle; DRAM starts with no raw-KV residency. Prepared selector/auxiliary state is equally ready by assumption. Initial fill and normal-time replacement traffic are excluded, so this is not net system benefit.

All 256 query demands are released together at layer entry. Rebuilt causal tail KV is local and never fetched from DRAM. Query-ready means all historical raw-KV copies needed by that query have completed after release, not that native attention or output has completed. Object-granular transfer completion differs from current runtime LoadBatch completion, so ordering agreement is not runtime timing equivalence. Future-frequency Oracle is not claimed latency-optimal.

Native full-prefill traces do not establish selector equivalence under chunked resume; MiniCPM's dense threshold and native compressed/index/window state remain outside this experiment. There is no matching compute profile, TP/queue/other request contention, preparation cost, or physical H2D calibration.

`document-results.csv` retains all per-document endpoints and paired DRAM differences. `layer-results.csv` retains every layer. Each `cases/*.npz` retains 8192 query-ready records and all byte-transfer segments; column definitions are in `ARRAY_SCHEMA.json`. Unused transferred bytes, partial bytes at stop, cancelled remaining bytes, and untransferred checkpoint bytes are separate fields.

The v1 directory is a preserved prepared-only snapshot. Before any matrix execution, v2 corrected an all-hit preemption-counter issue and strengthened per-case reuse bindings. Experimental conditions did not change.
