# Figure captions

All figures report deterministic CPU-only GlobalDES simulation (Qwen3-8B, DP=8, seed=0), not physical measurements.

1. Base WCT ECDF (160 workflows, C=16, F=2). Mean WCT gain: -0.24%.
2. AIMD trace for gpu-1, selected by pressure-event count with GPU-ID tie-break.
3. Failure-time committed continuous-prefix KV independently available in each tier for the strictly scheduled focus requests (tiers may both hold the same logical prefix; incidental co-located requests are excluded). Mooncake Peer-HBM/DRAM=0/45056; AegisKV Peer-HBM/DRAM=32768/32768.
4. Failure-count series at C=16. Separate figures report mean WCT gain, alpha, absolute WCT, failure-local gain, alpha/pressure, and failure-time reusable Peer-HBM/DRAM KV.
5. Workflow-concurrency series at F=2. Separate figures report mean WCT gain, alpha, absolute WCT, failure-local gain, alpha/pressure, and failure-time reusable Peer-HBM/DRAM KV.
