# Agent failure-to-first-new-output latency

Descriptive means over the same five fixed failure identities. Total includes detection, retry queue and service. Negative Aegis minus DRAM denotes shorter latency.

| Model | Nominal load | Restart total (s) | DRAM total (s) | Aegis minus DRAM (ms) |
|---|---:|---:|---:|---:|
| Qwen3-8B | 0.3 | 0.956403 | 0.488489 | -0.239640 |
| Qwen3-8B | 0.65 | 0.956403 | 0.488489 | -0.239124 |
| Qwen3-8B | 0.9 | 2.694406 | 1.970214 | -0.528031 |
| Qwen3-32B | 0.3 | 1.910054 | 1.607223 | -0.034358 |
| Qwen3-32B | 0.65 | 1.144348 | 0.550979 | -0.035058 |
| Qwen3-32B | 0.9 | 2.221522 | 1.253297 | -0.042746 |

All exact per-identity integers, queue/service decomposition and sink/non-sink comparisons (including adverse cases) are in AGENT_LATENCY_EVIDENCE.json. These are simulation outputs; displayed precision is not hardware accuracy.

## Queue and service shares

- none: queue 30.003% to 75.784%; service 24.179% to 69.909% of each cell's mean total.
- dram: queue 62.218% to 90.632%; service 9.317% to 37.577% of each cell's mean total.
- aegiskv: queue 62.248% to 90.657%; service 9.293% to 37.547% of each cell's mean total.

These ranges compare six cell means, not per-request maxima or CIs.

## Stratified signs

DRAM minus Restart; negative means the DRAM endpoint is smaller.

| Model | Load | Stratum | n fixed IDs | Target Workflow delta difference (s) | Failure-to-first-new difference (s) |
|---|---:|---|---:|---:|---:|
| Qwen3-32B | 0.3 | sink | 3 | 0.455184 | 0.455184 |
| Qwen3-32B | 0.3 | non-sink | 2 | -1.439854 | -1.439854 |
| Qwen3-32B | 0.65 | sink | 3 | -0.029045 | -0.029045 |
| Qwen3-32B | 0.65 | non-sink | 2 | -1.439854 | -1.439854 |
| Qwen3-32B | 0.9 | sink | 3 | -1.400190 | -1.400190 |
| Qwen3-32B | 0.9 | non-sink | 2 | -1.147122 | -0.320278 |
| Qwen3-8B | 0.3 | sink | 3 | -0.021684 | -0.021684 |
| Qwen3-8B | 0.3 | non-sink | 2 | -1.137261 | -1.137261 |
| Qwen3-8B | 0.65 | sink | 3 | -0.021684 | -0.021684 |
| Qwen3-8B | 0.65 | non-sink | 2 | -1.137261 | -1.137261 |
| Qwen3-8B | 0.9 | sink | 3 | -0.448813 | -0.448813 |
| Qwen3-8B | 0.9 | non-sink | 2 | 0.863432 | -1.137261 |
