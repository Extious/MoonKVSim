# Figure captions

All panels report deterministic CPU-only GlobalDES simulation (Qwen3-8B, DP=8, seed=0), not physical measurements.

1. Base WCT ECDF (160 workflows, C=16, F=2). Mean WCT gain: -0.93%.
2. AIMD trace for gpu-2, selected by pressure-event count with GPU-ID tie-break.
3. Restored KV tokens for failure-impacted requests. Mooncake GPU/DRAM=0/57344; AegisKV GPU/DRAM=0/29696.
4. Failure-count sweep at C=16; alpha is the mean and full range at control events.
5. Workflow-concurrency sweep at F=2; alpha is the mean and full range at control events.
