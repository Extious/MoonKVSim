# AegisKV three-tier evaluation protocol

Revision: 2026-09-23. Scope: the current fixed-L/K/Z, exclusive-owner, lower-tier lazy-credit design in `paper/system_design.tex`. This document supersedes the former no-Peer and joint-search protocol. `EXPERIMENT_MATRIX.md` supplies the eight research questions; `campaign-plan.json` enumerates planned comparison cells and their statistical hierarchy. The literature basis is recorded in `EVALUATION_LITERATURE_20260923.md`.

**Status: planned, not executed.** No complete serving runner implementing all current semantics has been verified. Hardware and exact model/workload revisions are not frozen. Existing static models, old simulator policies, path microbenchmarks and public-trace summaries are evidence with narrower scope, not physical results for this controller. A plan cell, an analytical CSV row and an independent physical run are different objects. This package launches no GPU job.

## 1. Readiness and frozen contract

Before promoting a planned cell to executable, attach: (1) a checked implementation-to-design map; (2) correctness results for its engine/model/layout; (3) a resource/failure-domain inventory; (4) immutable workload and fault manifests; (5) training/calibration/test IDs; (6) measured pilot timings and a resource reservation. Unsupported cells stay in the ledger with reasons. Do not fill them with theory or silently replace the model/backend.

| Item | Required contract |
|---|---|
| State | Sealed model/layout-compatible layer/token/TP objects, all required KV heads and native selector/auxiliary state; dependency-complete manifest |
| Ownership | One stable managed owner per object across Peer/DRAM/storage; execution working KV is separate; both migration copies count until safe release |
| Peer | Fixed calibrated L layers/K blocks per layer/Z review interval; mandatory state separately charged; only zero guarded Slack enters AegisKV admission; no Peer rent |
| Peer ordering | Reclaim completed/tool-handoff slots first; active requests by descending Slack; normal equal-Slack admission preserves incumbents; mandatory shrink ties use least recent request use |
| Lower tiers | Separate DRAM/storage pressure clocks; per-Agent grant and paid amounts; actual deduplicated use renews only that Agent; migration/Slack/access-statistic/checkpoint-growth updates retain paid rent |
| Lazy work | Settle prior rent, refresh versions, then consider victims; q low-key plus q rotating candidates within a frozen CPU/work budget; arbitrary stale-key decreases do not imply an exact heap minimum |
| Adapter | Changes total Peer authorization, not online L/K/Z; guarded AIMD with deferred zero-Slack demand measured before quota filtering; target bytes are not freed bytes |
| Safety | Destination confirmation → owner redirect → readers drain → source release; rejected preview does not commit rent; committed handoff cannot be undone by later failure; last-copy removal publishes valid fallback |
| Fault domain | GPU process, whole serving replica, host and storage-host are distinct; a same-host SSD does not survive host loss; additional sole-owner loss requires reachable state or explicit older-checkpoint/log replay |
| Normal workload | Original DAG once (`rounds=1`), fixed IDs/arrival order, full prompt-token denominator including first calls; frozen tool outputs in the first reproducibility mode |
| Clock | Monotonic host events plus CUDA timing/correlation, with cross-host alignment and synchronization errors recorded |
| Termination | One fixed horizon per workload cell; record every released workflow, failed anchor, timeout, rejected request and correctness error |

Freeze code, weights/repository revision, tokenizer, precision, native kernels/selector budgets, CUDA/driver, TP/layout/block size, transport topology, storage mount/cache/durability semantics, fault injector and input hashes. Any change creates a new campaign version. Pilot/calibration data is not reused as held-out evidence without an explicit disclosure.

## 2. Systems and equal-resource comparisons

The minimum main comparison is **H-LRU, Reuse, AegisKV, Recompute**. H-LRU uses tuned incremental checkpoints, finite exclusive tiers, request-recency Peer slots over active requests, lower-tier LRU, the same safe transfers/Adapter pressure rules, and the same load/locality Router. Its deferred-demand counter is its own eligible backlog; it does not use predicted Slack to grow its quota. Reuse uses normal next-use saved work/byte without the failure term; its Peer eligibility includes active requests and its ordering is reuse-based. All policies use the same physical ceiling, window and pressure thresholds; the demand signal follows each policy's declared eligibility. AegisKV uses the current table above. Recompute retains ordinary execution prefix caching and the accepted-token/input log, without added fault-safe KV retention. Recompute is a reconstruction-cost and normal-service control; it does not have equal checkpoint coverage.

All systems share physical GPU/HBM, DRAM, storage, link limits, inference/restore kernels and declared execution resources. Account for model weights, working KV, mandatory selector state, workspace, metadata, reserved/retiring bytes and duplicate migration copies. A policy need not waste its unused Peer quota; report actual physical occupancy and productive serving capacity. Normalize load to the same H-LRU pilot and use exactly the same absolute arrivals, not each policy's own saturation point.

Tune H-LRU/Reuse and AegisKV on the same disjoint validation budget. Report parameter search space, number of pilot trials and selection objective. All-DRAM is a **resource-relaxed reference**; small exhaustive placements are **offline references**. Neither is a deployable equal-resource baseline. No protocol invariant is disabled as a speed ablation.

For external validity, select a compatible, pinned artifact from the literature after checking deployment support. LUMEN, DéjàVu, GhostServe and workload/cache systems address different scopes; do not require every one to run or claim an unexecuted artifact result. A reproduced mechanism is labeled `...-style (reimplementation)`, with omitted features documented. Count redundancy/parity, coding work, checkpoint lag and backing capacity. An external workflow policy gets the same failure-safe substrate when testing workflow awareness.

## 3. Workload, model and resource cells

Planned families: W1 executable multi-agent coding; W2 FanOutQA with real dependency consumption; W3 controlled sequential/balanced/heterogeneous fork-join and repeated tool-return workloads. Start with at least 30 distinct workflow IDs/family; W3 has ten of each DAG shape, with repeated calls/tool events specified in its frozen manifest. Public metadata can characterize durations/locality but does not provide missing prompts, tool results or dependency edges. Live tools are a separate external-validity mode.

Planned model roles: M-D dense Qwen3-8B and M-S native MiniCPM4-8B-NSA, subject to exact revision and complete-path support. Keep native attention semantics fixed within each model. The supported 32K context bucket must respect model/kernel limits; its exact token lengths are frozen before comparison, not padded to an unsupported label. Models differ in more than sparsity; cross-model throughput is not a causal sparse-attention speedup. Optional Qwen2.5-7B-Instruct-1M/other sparse models require separate adapters, correctness and calibration.

Planned center topology is DP2/TP1 with failure-separated serving replicas and reachable storage. Host-level claims require actual host separation; multiple GPUs on one host validate only the specified narrower failure. TP2 requires enough independent resources and a compatible shard/failure model. All topology fields are unresolved until inventory is attached.

Center resource ratios: Peer cap 0.10 of managed HBM pool; DRAM 0.25 and storage 1.0 of a common frozen unique-checkpoint working-set census; baseline load 0.60. Ratios are experimental points, not system defaults. Store absolute GiB, time-varying unique demand, actual allocation and achieved bandwidth. The managed pool excludes weights/fixed allocations; reserve/workspace and serving high watermark follow the design ceiling. Additional ratio cells are one-factor interventions, not an implicit Cartesian product.

Measure native local/remote NVMe or shared-filesystem paths by their real backend name. Report cold client cache, warm client and server-cache uncertainty, read/write concurrency, request sizes, commit/fsync semantics and GPU-ready time. A rate limiter cannot create bandwidth above the hardware maximum; unsupported requested rates remain unsupported. Use achieved bandwidth on result axes. Same-directory cached reads are not evidence for SSD/host-failure durability.

Load calibration uses predeclared workload TTFT/ITL/WCT SLOs and a stable sustainable-throughput rule. Apply 0.30/0.60/0.85 times that common rate; count rejected/late/incomplete requests in goodput. Record utilization after losing a replica, which may exceed surviving capacity. SLO thresholds, horizon, warmup and overload stop conditions are frozen from pilot, before reading test-policy results.

## 4. Pairing, fault injection and attribution

A **comparison block** fixes scenario/model/family and contains its policies. An independently launched **paired campaign** uses one block's common arrival/fault seed and all policies/conditions, randomized in execution order. A **run** is one policy/condition launch. Each run contains workflows, which contain requests/layers/blocks; report all levels of sample accounting. Start with ten campaigns/block. Ten repeats of 30 workflow IDs are not 300 distinct workflows.

Primary trigger: anchor workflow + Agent/segment/request ID + 80% of its frozen total-token logical progress + decode phase. Kill the **whole source replica**, including all colocated requests. This differs from canceling the anchor request. Keep the same anchor across policies, even if Router changes its physical source. If the anchor cannot be reached, log that outcome and keep the original cohort; do not substitute another request. Use fixed accepted tokens for paired recovery-replay experiments, and disclose teacher-forced/frozen-token mode separately from normal generation.

A policy-specific F0 run is always the mate for its F1. The main estimand is intent-to-treat over all released workflows. Separately classify actual interrupted, shared reader/link/target but not interrupted, and isolated workflows. Routing can change membership, so comparisons only among each policy's interrupted set are secondary descriptive results. Match arrivals/IDs even when paths diverge.

Full-system runs expose actual commit lag, placement, routing, queueing and movement. Attribution runs replay the same prefault state/native demand/committed frontier/resources and change only a named factor. For exclusive Peer on/off, retain equal unique coverage while reallocating within common tier caps. Record preparation costs separately; a prepositioned attribution experiment cannot establish steady-state migration overhead.

Extended logical phases are 20/50/80/95%, plus separately specified prefill, tool wait and migration boundaries. Log actual acknowledged and committed frontiers M/N. N can exceed Z under copy lag. Enumerating N=0…Z−1 is only an ideal analytical calculation. A common wall-clock kill is not a matched-progress test. Continuous trace runs instead use the fixed external calendar and report the resulting logical phases.

## 5. Eight research questions and measurements

**RQ1 — End-to-end.** Primary mean WCT and policy-specific fault penalty, paired H-LRU/Reuse minus AegisKV contrasts, completion at the common horizon and SLO-goodput; report F0 and F1 separately. Include distributions/per-workflow paired differences as secondary views. P95 is descriptive with n; do not imply reliable p99 from a small family cohort. Benefits only over Recompute do not establish workflow-aware placement value.

**RQ2 — Causal recovery and interference.** Log detection/fencing, admission, storage/NIC/H2D, required replay, first unacknowledged token, branch/join and workflow completion on one event graph. Critical-path intervals must not overlap; GPU work and total bytes are separate metrics. Run Peer×pipeline and Router×shared-contention four-corner blocks; keep native selection, coverage, available workspace and candidates fixed. Report useful/unused prefetch, misses, reveal-to-ready wait, migration and all three cohorts. Do not count avoided historical prefill as overlap computation.

**RQ3 — Operating boundaries.** One-factor Peer/DRAM/storage/load/bandwidth/context/phase scans at the same center, then replicate important change points on other families. Include all-fit and Peer=0, last-copy storage pressure and congested links. A missing safe destination causes bounded wait/rejection, not an invisible buffer. Report actual coverage, peak physical occupancy, achieved throughput/lag and completion beside WCT.

**RQ4 — Priority and slot ablations.** Remove Slack, reuse, fault term or shared-Agent shares individually; run Slack×shares all four corners. Shared credit ablation preserves physical deduplication. Compare fixed-quota Slack/FCFS/recency/benefit policies. The minimum FCFS/recency references admit from all active requests, so they compare eligibility and ordering together; an extension replays an identical candidate list to isolate ordering alone. Ordinary ties preserve incumbents and shrink ties follow declared request-use recency. Frozen placement still performs required safe pressure relief. Adaptive-depth/oracle alternatives are explicitly more expensive references.

**RQ5 — Credit and control cost.** Cross same-value direct revaluation/renewable-credit with lazy/capped-eager under identical candidate opportunities, CPU budget and safety. Direct means current local grant-per-byte comparison, not the superseded global joint-WCT search. Add no-renew/no-aging; extension includes ordinary GDS/Landlord, no-rotation and unlimited eager. Measure CPU time, decisions/s, q/Agent-share visits, scan age, victim disagreement/rank regret, migration and WCT together. Unlimited eager is a reference with disclosed work; do not describe a capped eager pass as refreshing all objects.

**RQ6 — Prediction and calibration.** Split whole workflows chronologically into train, calibration and held-out test; publish IDs and causal feature/label definitions. Labels end at residual segment boundaries. Baselines are history/median and zero-Slack fallback. Report signed remaining-time errors, MAE, overestimated Slack, critical-path ranking, fallback rate and downstream WCT. Native sparse evaluation deduplicates block selections per Query and divides by causal visibility opportunities; compare raw counts/recency at equal future Queries, bytes and cold-start priors. Cross normalized-vs-raw with serial-vs-pipeline. Freeze L/K/Z after independent calibration; test shifted M/N/load, correlated/unbiased/asymmetric forecast errors and missing graph edges.

**RQ7 — Healthy and trace outcomes.** One-pass F0 uses all requests including first calls, separates token-hit/request-hit and HBM/Peer/DRAM/storage. Report absolute WCT, TTFT, ITL, SLO-goodput, GPU/controller and read/write overhead at shared arrival rates. Potential trace prefix coverage is not a runtime hit. Original trace timing, down/up, clusters and repeated faults retain capacity loss/repair; unresolved labels do not become guessed crashes. Include zero-fault windows. Amortized break-even uses measured healthy cost and conditional fault benefit in common units/horizon, and states where benefit vanishes.

**RQ8 — Correctness and scaling.** Sixteen named interleaving types are in the matrix and JSON. Run at least 100 seeded interleavings/type plus small-state enumeration; verify same accepted history, complete restored layer/shard/selector state, next-token/hidden-state tolerance, no pending reads or duplicate acknowledgements, safe byte ledgers and leases. Sparse batched replay needs independent parity; otherwise use token-wise supported replay. A failed safety case blocks that implementation cell. Pressure traces use Peer/DRAM shrink/recovery with finite lower pools and source failure; controller stress varies DAG/groups/q under a fixed CPU allocation, with selected end-to-end validation. Count state-machine tests separately from physical campaigns.

## 6. Statistical estimands and unsuccessful outcomes

For campaign c, policy p and workflow w, define D(c,p,w) = WCT(F1) − WCT(F0), using that policy's own mate. The contrast against AegisKV is B(c,p,w) = D(c,p,w) − D(c,AegisKV,w); positive means lower AegisKV fault penalty. Compute family/cohort aggregates within campaign before bootstrapping **campaign contrasts**, 10,000 resamples, fixed analysis seed. Report 95% intervals and absolute effect sizes. Never subtract unrelated CI endpoints. A secondary hierarchical bootstrap resamples campaigns then matched workflow IDs, carrying all policy/condition mates together.

Primary confirmatory contrasts are H-LRU and Reuse against AegisKV on each family/model cell. Do not declare all systems/workloads improved from one favorable omnibus mean. Secondary ablations and scans are exploratory unless a multiplicity/decision rule is frozen in the analysis manifest. Ten campaigns is an initial design, not a guarantee of power. Pilot-based precision planning is allowed before the main campaign; do not keep adding seeds until significance appears. Declare any equivalence margin before claiming negligible overhead.

The five factorial blocks estimate I = (Y11−Y10)−(Y01−Y00), within campaign, on a single stated outcome. Main effects/interaction need all four paired cells; speedups from separate experiments cannot be added. Qualitative correctness evidence has no fabricated latency confidence band.

Keep all released workflow IDs in the denominator. At common administrative horizon tau, report completion and restricted completion cost mean(min(T,tau)); unresolved workflows contribute tau, with counts and reasons. This finite-horizon metric is not their eventual WCT. Complete-case latency is secondary and selection-sensitive. A survival estimator such as Kaplan–Meier RMST requires its censoring assumptions and cannot convert implementation crashes into benign independent censoring. Use within-run administrative horizons consistently. CI quantiles at small n are reported cautiously; no p99 precision claim from a few dozen workflows.

Calendar-trace inference clusters entire source-system/calendar windows and correlated fault groups. Mapping seeds and repeated launches are additional levels, not independent source events. Preserve zero/negative differences, outliers, ties, failed/infeasible cells and all tails. Analytical enumerations have independent_runs=0 and no empirical confidence interval.

## 7. Raw logs and provenance

The common plot-table schema and packaging restrictions remain in `DATA_CONTRACT.md`. Current-control raw fields extend that schema; new metrics require a registered visual specification rather than reusing a misleading axis.

| File | Required fields beyond shared campaign/pair/config/policy/condition IDs |
|---|---|
| runs.jsonl | experiment/block/cell IDs; workload/model/code hashes; model/layout/kernel; topology/backend/fault domains; arrival/fault/mapping seeds; run order; warmup/horizon/SLO; absolute capacities/rates; start/end; planned/running/completed/failed/unsupported status and reason |
| workflows.csv | workflow/family IDs; release/finish/WCT; deadline/status; original cohort; direct interruption; shared reader/link/target exposure; completion at tau |
| requests.csv | Agent/segment/request IDs; prompt/output/accepted tokens; TTFT/token timestamps; tier-specific hits/bytes; reconstruction; routing/admission; model/layout |
| events.jsonl | event/parent/resource IDs; monotonic release/start/end; source/owner epoch; object/layer/block/TP IDs; tier; bytes; stream/CUDA correlation; copy/checksum/commit/redirect/drain/free; return code |
| checkpoints.csv | trigger/acknowledged/committed token frontier; trigger/start/commit; manifest/dependencies; owner/failure domain; failed write; actual N and lag; final short snapshot |
| controller.csv | configured L/K/Z; q/CPU cap; prediction/demand/materialization versions; visited candidates/shares; scan age; grant/paid/clock/use epoch by pool; trial vs committed clocks; renewal/revalue reason; victim order; lease eligibility; rejection/defer |
| ownership.csv | takeover DP/binding version; slot membership/evictability; hot-set version; request-use age; owner/epoch; actual physical lease; Peer budget target; reserved/committed/retiring/staging/temporary/actually-free bytes |
| predictions.csv | causal landmark/feature time; segment label definition; workflow split; predicted/actual remaining time and Slack; guard; validity/fallback; actual values marked analysis-only |
| correctness.csv | injection/type/seed; exact transition/fault domain; expected/observed state/manifest; parity/tolerances; duplicate outputs; leases at free; ledger assertions; completion/error text |
| trace-mapping.csv | source system/node/raw row IDs; cleaning group; mapping seed; destination domain; original/transformed timestamps; down/up; missing fields/assumptions |

Raw sources are immutable and hashed; manifests record table hashes, aggregation command, statistical unit, all sample levels, exclusions/censoring and revisions. Events are sufficient to reconstruct overlap and owner handoff. Hash consistency proves identity, not physical execution or correct semantics. Keep execution evidence such as scheduler/host/process logs with physical campaigns. There is no measured manifest until those sources exist.

## 8. Figure contracts and completion gates

Planned outputs: end-to-end paired effects with F0/F1/complete-cohort context; recovery critical path and collateral penalty; resource/healthy SLO curves; mechanism forest/factorial plots; WCT–CPU tradeoff; prediction error/native coverage; trace per-system/cluster outcomes; physical occupancy plus controller cost. Their exact intended metrics and sample units are in JSON `figure_contracts`. Planned contracts do not imply renderer support or populated data today.

Use single-column native canvases, readable final-size text, restrained consistent colors plus markers/linestyles and no significance stars as a substitute for intervals. Save editable source, PDF/SVG/PNG, CSV and manifest; review at actual insertion width and in grayscale. Keep current historical diagnostics under their original evidence labels. A measured WCT graph must not be synthesized by relabeling an analytical scenario CDF, a proxy correlation or a path microbenchmark.

Completion order is readiness/correctness → pilot/calibration → main paired outcomes and F0 → causal/ablation blocks → boundary/trace/scaling extensions. Submission-quality runtime claims require the complete current implementation, executed matched comparisons, scientific uncertainty, adverse outcomes and raw provenance. A readable manuscript or a beautiful figure alone does not meet those gates.
