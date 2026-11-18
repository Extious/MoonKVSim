# Figure captions

All figures report deterministic CPU-only GlobalDES simulation (Qwen3-8B, DP=8, seed=0), not physical measurements.

1. Base WCT ECDF (160 workflows, C=16, F=2). Mean WCT gain: +0.12%.
2. AIMD trace for gpu-0, selected by pressure-event count with GPU-ID tie-break. Queued-plus-active requests are shown separately from resident-primary requests; the latter is the direct HBM-pressure diagnostic.
3a. Failure-time continuous-prefix KV actually used by the strictly scheduled focus requests. Normal HBM is target-local opportunistic reuse and is not protection evidence; Peer-HBM and Store DRAM are committed protection sources. A symmetric-log token axis keeps the small shared system-prompt hit visible beside long protected prefixes. Mooncake Normal/Peer/DRAM=128/0/50176; AegisKV Normal/Peer/DRAM=128/50176/0.
3b. Independently committed continuous prefixes available at failure. Tier values may overlap and must not be summed. Mooncake Normal/Peer/DRAM=128/0/50304; AegisKV Normal/Peer/DRAM=128/50304/50304.
4. Failure-count series at C=16. Separate figures report mean WCT gain, alpha, absolute WCT, failure-local gain, alpha/pressure, and failure-time reusable Peer-HBM/DRAM KV.
5. Workflow-concurrency series at F=2. Separate figures report mean WCT gain, alpha, absolute WCT, failure-local gain, alpha/pressure, and failure-time reusable Peer-HBM/DRAM KV.
