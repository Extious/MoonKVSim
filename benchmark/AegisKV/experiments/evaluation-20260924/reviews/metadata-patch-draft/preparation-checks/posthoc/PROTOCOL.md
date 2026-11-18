# Post-hoc constructed Slack mechanism diagnostic: frozen design proposal

This is an explicitly post-hoc, constructed mechanism diagnostic motivated by the completed capacity/Slack campaign's null WCT result. It does not replace those 32 runs, establish naturally occurring Agent behavior, or validate predictor accuracy. No DAG simulation or outcome-based parameter search preceded this protocol. Static profile and capacity arithmetic are the only preflight calculations. All ten specified runs, including zero/adverse results, will be retained.

## Fixed workload and resources

One original four-Agent workflow executes once: root -> {a_critical, b_expensive} -> join. Deterministic random token IDs use seed 7, pinned Qwen3-8B TP1 / BF16 KV, one invocation per Agent. Root and join each have 512 prompt / 16 output tokens; critical has 1,024 / 8,192; expensive has 8,192 / 2,048. Every invocation declares a 16,384-token output limit before admission; all prompt+limit bounds are within 40,960.

Use the existing AIC GridDurationProfile and model_config, DP3, hosts=(0,0,1), worker failures, 1 ms detection, Z=256, dense attention, zero modeled foreground DMA slowdown, and maximum simulated time 300 s. Peer HBM cap and initial quota are zero. The only compared selection mode is policy=dram with slack_mode=dag versus zero. Thus HBM placement cannot mediate this particular comparison. Fixed hand-declared role priors are root=5 s, critical=120 s, expensive=40 s, join=5 s; guard=0 and prediction TTL=120 s. These are mechanism inputs, not predictions fitted against run outcomes.

Routing is an observed precondition, not patched in the simulator. With root first and then a_critical before b_expensive, the existing queue/load tie rule should put the branches on workers 0 and 1, both host 0. Worker 2 is their only cross-host peer, so both backups contend for host 1's finite DRAM. A worker-0 fault should leave expensive's worker 1 alive and retry critical on worker 2. If actual routing differs, retain/report it; do not reconfigure after seeing results.

## Fixed matrix and failure

Ten runs: DRAM/normal-DAG-Slack and DRAM/zero-Slack x DRAM per-host budgets {1.25 GiB, 4 GiB} x {F0,F1} = 8, plus Restart F0/F1 at 1.25 GiB = 2. No seed or arrival sweep is performed. F1 always targets a_critical invocation 0 at logical token 1,536 (512 accepted decode outputs), implemented as Failure.progress=(1536-0.5)/9216. This is not the primary study's 80% total-progress rule. Each F1 subtracts its own same-ID/config/policy F0. The one workflow has no population confidence interval.

## Pre-execution arithmetic, including metadata and transient copies

The pinned model has 36 layers and 4,096 KV bytes per token per layer/rank: 147,456 B/token. Each block/layer/rank also carries 16 selector bytes and 8 count bytes. Exact checkpoint and next-append footprints are computed with Config.checkpoint_bytes and prefix_bytes; an append reserves Z new KV tokens plus the entire next version's metadata while the old metadata remains charged.

| Committed frontier | Complete checkpoint B | Next append B | Committed + pending B |
|---:|---:|---:|---:|
|1,280|188,760,960|37,769,472|226,530,432|
|1,536|226,513,152|37,772,928|264,286,080|
|8,192|1,208,070,144|37,862,784|1,245,932,928|
|8,448|1,245,822,336|37,866,240|1,283,688,576|
|8,704|1,283,574,528|37,869,696|1,321,444,224|

The initial draft's 1.125 GiB (=1,207,959,552 B) was rejected before any simulation: even the 8,192-token complete checkpoint cannot fit after metadata. The corrected tight budget is 1.25 GiB (=1,342,177,280 B). Either branch individually fits at the predicted failure frontier, even with its next pending version, but CP1280+CP8448 alone totals 1,434,583,296 B and cannot fit simultaneously. Using the critical 1536 ceiling gives 1,472,335,488 B; allowing both next appends gives 1,547,974,656 B. The loose 4 GiB control fits all of these. This check is local to the prescribed failure point, not a promise that either growing branch fits forever.

A read-only sum of pinned forward durations, assuming immediate branch admission and no failure, places critical's fault +6.029185542 s from branch start. Expensive's prefill is 0.801630975 s; its durable frontier then is 8,608 with checkpoint ceiling 8,448. Whole critical/expensive service is 98.701951271 / 26.268461433 s. These calculations establish the intended separation of reconstruction footprint from remaining branch length; they are not simulated placement or WCT results.

## Required endpoint evidence and limitations

Freeze PLAN, PROTOCOL, source snapshot, profile, workload, and all job bindings before execution. Retain full event/flow/journal records for all ten runs. A read-only subclass wraps _fail: it copies state at the exact failure-handler entry and then calls the original base method once with the same arguments. An external DES invariant observer also copies states after events. These hooks must not call mutating policy functions, change scheduling, or inspect future outputs for decisions. Save the exact failure-entry state, including current computed/durable tokens, worker/peer, every committed/pending/retired checkpoint and its holder/account bytes, queued/busy workers, and Tracker estimate timestamps/versions. Reconstruct guarded Slack and E=max(0, profile_recompute(durable)-Slack) offline from those observed inputs, using a separate Tracker/profile instance.

Report actual failure wall time, failed workers/hosts, Agent/call/logical-token identity, and co-victim IDs across modes. Verify whether both branches really compete for the same host, whether their complete/current and pending sizes exhaust the shared budget, whether the expensive branch displaces or prevents admission of the critical checkpoint, and what usable frontier/holder critical actually has at the fault. Retain transition evidence and distinguish absence, prevention of admission, retirement, and completed-copy publication; a periodic policy_sample is not an exact at-fault state.

For each case report all four Agent invocation submit/finish timestamps, final gating parent, F0/F1 WCT and delta, detection/recorded retry queue/admitted recovery service, modeled backup bytes, peak DRAM, and byte-time integrals. Ordinary admission timestamps are not part of the base summary: do not relabel ordinary submit-to-finish latency as measured queueing. The observer may record an exact idle-to-busy admission transition, but any such extra measurement must be explicitly identified as the diagnostic observer's record.

The favorable mechanism requires a verified protection/competition difference that connects to the fixed critical failure, not merely a WCT difference. If routing, Slack fallback, metadata capacity, timing, or checkpoint publication prevents that chain, report the failed precondition and keep the negative result. No post-outcome rerun with different lengths, priors, capacity or failure placement is authorized by this protocol. Healthy equal WCT is conditional on the model's zero DMA slowdown and is not measured zero hardware overhead.

## Observation transparency validation (not an experimental sample)

After the ten frozen runs, execute the exact Restart F1 job once using the unmodified base CurrentRuntime through run_one, without the observer. Require byte-identical summary.json and identical decompressed event/flow records, retaining both hashes in OBSERVATION_TRANSPARENCY.json. This eleventh execution is solely a validation and is excluded from all ten-run experiment and five-pair counts. Journals may differ by added INVARIANT_CHECKED observation records, which do not create DES events.
