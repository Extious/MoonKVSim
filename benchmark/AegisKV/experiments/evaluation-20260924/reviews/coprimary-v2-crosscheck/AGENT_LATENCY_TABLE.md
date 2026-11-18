# Agent failure-to-first-new-output latency

Descriptive means over the same five fixed failure identities. Total includes detection, retry queue and service. HBM gain is DRAM minus AegisKV; positive is better.

| Model | Nominal load | Restart total (s) | DRAM total (s) | HBM gain (ms) |
|---|---:|---:|---:|---:|
| Qwen3-8B | 0.3 | 0.956403 | 0.488464 | 0.219979 |
| Qwen3-8B | 0.65 | 0.956403 | 0.488464 | 0.219464 |
| Qwen3-8B | 0.9 | 2.694406 | 1.970189 | 0.508370 |
| Qwen3-32B | 0.3 | 1.910054 | 1.607198 | 0.027498 |
| Qwen3-32B | 0.65 | 1.144348 | 0.550953 | 0.027499 |
| Qwen3-32B | 0.9 | 2.221522 | 1.253272 | 0.035886 |

All exact per-identity integers, queue/service decomposition and sink/non-sink comparisons (including adverse cases) are in AGENT_LATENCY_EVIDENCE.json. These are simulation outputs; displayed precision is not hardware accuracy.

## Queue and service shares

- none: queue 30.003% to 75.784%; service 24.179% to 69.909% of each cell's mean total.
- dram: queue 62.221% to 90.634%; service 9.316% to 37.574% of each cell's mean total.
- aegiskv: queue 62.249% to 90.657%; service 9.292% to 37.546% of each cell's mean total.

These ranges compare six cell means, not per-request maxima or CIs.

## Stratified signs

DRAM minus Restart; negative means the DRAM endpoint is smaller.

| Model | Load | Stratum | n fixed IDs | Target Workflow delta difference (s) | Failure-to-first-new difference (s) |
|---|---:|---|---:|---:|---:|
| Qwen3-32B | 0.3 | sink | 3 | 0.455173 | 0.455173 |
| Qwen3-32B | 0.3 | non-sink | 2 | -1.439901 | -1.439901 |
| Qwen3-32B | 0.65 | sink | 3 | -0.029057 | -0.029057 |
| Qwen3-32B | 0.65 | non-sink | 2 | -1.439901 | -1.439901 |
| Qwen3-32B | 0.9 | sink | 3 | -1.400201 | -1.400201 |
| Qwen3-32B | 0.9 | non-sink | 2 | -1.147166 | -0.320325 |
| Qwen3-8B | 0.3 | sink | 3 | -0.021716 | -0.021716 |
| Qwen3-8B | 0.3 | non-sink | 2 | -1.137274 | -1.137274 |
| Qwen3-8B | 0.65 | sink | 3 | -0.021716 | -0.021716 |
| Qwen3-8B | 0.65 | non-sink | 2 | -1.137274 | -1.137274 |
| Qwen3-8B | 0.9 | sink | 3 | -0.448846 | -0.448846 |
| Qwen3-8B | 0.9 | non-sink | 2 | 0.863419 | -1.137274 |
