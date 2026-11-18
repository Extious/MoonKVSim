# Sensitivity results

All 126 runs passed exact-output, terminal-allocation, source/input/config/failure/profile and own-F0 pairing checks. There are 252 workflow pairs; 31 negative collateral deltas are retained. n=1 fixed fault identity per condition.

| Factor | Setting | Restart penalty (s) | DRAM penalty (s) | AegisKV penalty (s) |
| --- | ---: | ---: | ---: | ---: |
| h2d_GBps | 8 | 1.802310283 | 0.283956089 | 0.278180605 |
| h2d_GBps | 16 | 1.802310283 | 0.135306833 | 0.132419091 |
| h2d_GBps | 32 | 1.802310283 | 0.060982205 | 0.059538334 |
| h2d_GBps | 64 | 1.802310283 | 0.024024821 | 0.023309283 |
| dram_GiB_per_host | 0.25 | 1.802310283 | 1.802310283 | 1.802310283 |
| dram_GiB_per_host | 1 | 1.802310283 | 1.802310283 | 1.802310283 |
| dram_GiB_per_host | 256 | 1.802310283 | 0.060982205 | 0.059538334 |
| hbm_cap_MiB_per_rank | 0 | 1.802310283 | 0.060982205 | 0.060982205 |
| hbm_cap_MiB_per_rank | 32 | 1.802310283 | 0.060982205 | 0.060982205 |
| hbm_cap_MiB_per_rank | 128 | 1.802310283 | 0.060982205 | 0.059538334 |
| hbm_cap_MiB_per_rank | 4096 | 1.802310283 | 0.060982205 | 0.059538334 |
| online_prediction_multiplier | 0.5 | 1.802310283 | 0.060982205 | 0.059538334 |
| online_prediction_multiplier | 1.0 | 1.802310283 | 0.060982205 | 0.059538334 |
| online_prediction_multiplier | 2.0 | 1.802310283 | 0.060982205 | 0.059538334 |
| prediction_latency_ms_at_TTL100ms | 0.1 | 1.802310283 | 0.060982205 | 0.059538334 |
| prediction_latency_ms_at_TTL100ms | 200 | 1.802310283 | 0.060982205 | 0.059538334 |
| compute_dma_slowdown | 0.0 | 1.802310283 | 0.060982205 | 0.059538334 |
| compute_dma_slowdown | 0.05 | 1.802310283 | 0.060219519 | 0.058775648 |
| compute_dma_slowdown | 0.1 | 1.802310283 | 0.059456834 | 0.058012963 |
| failure_detection_ms | 1 | 1.802310283 | 0.060982205 | 0.059538334 |
| failure_detection_ms | 10 | 1.811310283 | 0.069982205 | 0.068538334 |
| failure_detection_ms | 100 | 1.901310283 | 0.159982205 | 0.158538334 |
| tolerance_seconds | 0 | 1.802310283 | 0.060982205 | 0.059538334 |
| tolerance_seconds | 0.01 | 1.802310283 | 0.060982205 | 0.059538334 |
| tolerance_seconds | 1 | 1.802310283 | 0.060982205 | 0.059538334 |
| checkpoint_tokens | 64 | 17.711292058 | 0.378000903 | 0.376557021 |
| checkpoint_tokens | 256 | 1.802310283 | 0.060982205 | 0.059538334 |
| checkpoint_tokens | 1024 | 1.802310283 | 0.161898399 | 0.160454627 |

At 0.25/1GiB DRAM, peak single-host use is about 98.45% of capacity and the target has zero checkpoint at failure; observed penalties equal restart. At center, HBM adds only 1.443871ms beyond DRAM. HBM0 verifies identical DRAM/AegisKV workflow finishes for both F0 and F1.

All 52 delayed replies exceed TTL100ms (200ms latency); none exceed it in the 0.1ms paired control. Target penalties do not change. These are observed reply ages, not a complete timeout-cause count or predictor-accuracy validation.

Z64 changes prefill forward segmentation, and slowdown F1-minus-F0 subtracts its own interfered healthy run. Do not attribute these deltas solely to checkpoint transfer cost or faster recovery.
