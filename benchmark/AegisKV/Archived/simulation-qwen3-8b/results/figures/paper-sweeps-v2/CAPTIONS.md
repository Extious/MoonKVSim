# Figure captions

All panels report deterministic CPU-only GlobalDES simulation (Qwen3-8B, DP=8, seed=0), not physical measurements.

1. Base WCT ECDF (160 workflows, C=16, F=2). Mean WCT gain: -0.04%.
2. AIMD trace for gpu-1, selected by pressure-event count with GPU-ID tie-break.
3. Failure-time committed continuous-prefix KV independently available in each tier for the strictly scheduled focus requests (tiers may both hold the same logical prefix; incidental co-located requests are excluded). Mooncake GPU/DRAM=0/68608; AegisKV GPU/DRAM=32768/68608.
4. Failure-count sweep at C=16; alpha is the time-weighted mean and full observed range across DP ranks.
5. Workflow-concurrency sweep at F=2; alpha is the time-weighted mean and full observed range across DP ranks.
