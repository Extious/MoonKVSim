# AegisKV DRAM/storage evaluation protocol

Revision: 2026-09-21. See **EXPERIMENT_MATRIX.md** for the expanded single-failure, real-trace and complete-ablation specification; it supersedes the previous compact figure selection. The user has removed the draft-stage page limit. Target: EuroSys 2027 fall submission; the user confirmed an abstract is registered. This is an **experiment specification**, not a report that the experiments were run. The current Evaluation separates deterministic analytical scenarios, observed public-trace descriptions, and conditional trace-driven model outcomes. No GPU job is launched by this package.

The scientific question is whether workflow dependencies and common-failure recovery costs improve **online KV retention, DRAM-to-storage demotion, and final eviction**, after charging ordinary reuse and migration costs. Dedicated Peer HBM, layer-depth L, hot-block K, and Peer-capacity control are outside the revised design. Inference still needs its ordinary HBM working set.

## 1. Frozen experiment contract

| Item | Required setting / record |
|---|---|
| State | Immutable model-compatible layer/token blocks; all KV heads per layer; exact TP shard and selector metadata; sealed intervals; dependency-complete checkpoint manifest |
| Storage | Finite DRAM and finite SSD or shared-filesystem pools; committed, reserved, retiring, metadata and staging bytes separately |
| Fault domain | Distinguish GPU process, full serving replica, host, and storage-host failure; a same-host SSD does not survive host loss |
| Control state | Surviving route versions, source epoch, manifest, accepted input and acknowledged-token log |
| Placement | Normal cache eligibility independent of Slack; value normal reuse and recovery; storage deletion compared against reconstruction, not DRAM latency |
| Recovery | Same compatible model, layout, precision, native attention semantics, and accepted token sequence; all policies use identical execution/transfer scheduling in attribution comparisons |
| Logical fault | Workflow ID + Agent/segment ID + request ID + token position + phase; primary decode event at 80% of that Agent's frozen total-token progress |
| Normal workload | One pass over each original DAG (`rounds=1`), identical Workflow IDs and arrival order, full prompt-token denominator including first calls |
| Pairing | Each policy has a healthy mate; randomize policy order within the independently launched campaign |
| Measurement clock | Monotonic host clock plus CUDA events for kernels/copies; report synchronization and cross-host clock alignment |
| Termination | Common observation horizon; completion and timeout counts; no silent omission of killed, incomplete, or slow workflows |

Pin code commits, model repository revision and weight hashes, tokenizer/config, CUDA/driver/kernel versions, layout/block size, NIC topology, filesystem mount and backend properties, fault injector, and workload data hashes before formal runs. Changing any of these creates a new campaign version. Theory rates are not permitted to fill unmeasured physical cells.

## 2. Systems and baselines

Use two complementary comparison sets. Keep the main figure to six named policies, with fixed colors/markers in `plot.py`; additional systems receive a supplementary panel with the same schema.

**Mechanism attribution (same substrate):**

1. Recompute: ordinary local prefix cache; no additional fault-safe checkpoint. Keep accepted tokens and control state. Count reconstruction and its interference.
2. DRAM/storage LRU: incremental checkpoints, finite pools, same manifest/lease/transport protocol, LRU demotion. This is the central baseline.
3. Reuse-only: retain by predicted next-use benefit per byte; identical movement cost and safety constraints.
4. AegisKV without dependencies: every request has zero slack and source-event costs use independent requests. This isolates DAG information.
5. AegisKV: normal reuse plus failure-domain DAG value, causal sparse/layer candidates, tier-local trial rent, joint marginal checks, hysteresis, asynchronous safe demotion and explicit final-copy fallback.
6. Feasible oracle: offline true durations and exhaustive placement only for small instances. Mark infeasible on larger instances; do not make it a deployable competitor.

Also compare no reuse term, no migration hysteresis, local sum-of-penalties instead of joint source-event DAG replay, historical prediction, zero-slack fallback, frozen placement, and direct revaluation without rental credit **under the same value model**. Do not ascribe rental gains to a changed value formula.

**External systems:** use pinned original implementations where possible: DéjàVu replication, GhostServe parity, and LUMEN load-aware recovery. RaidServe requires its TP/irregular-GPU setting. Ordinary hierarchical caching should include a tuned Mooncake/SGLang or Strata-style implementation. TOPAS/KVFlow are normal workflow/cache baselines; combine them with the same failure-safe backing mechanism before attributing a fault-tolerance gain to AegisKV. If only a mechanism is independently reproduced, label it “load-aware restore (reimplementation)” or “parity checkpoint (reimplementation)”; do not use the original system's name as if its full artifact ran. Count parity bytes, coding CPU/GPU work, redundancy, checkpoint lag, and all backing capacity. No theoretical curve in this package is a result for these named systems.

## 3. Deployment and workload matrix

**Minimum physical topology.** Two failure-separated replicas, plus storage reachable after either compute failure. For TP2 and host-level isolation, use four GPUs on separate serving hosts. One host with multiple GPUs can validate a process/GPU failure only. The surviving GPU must reserve real execution KV and activation/staging space. Record the capacity lost when one replica fails.

**Primary model cells.** Qwen3-8B (dense reference) and Qwen2.5-7B-Instruct-1M (exact supported MInference/DCA path). MiniCPM4-8B is an additional native-sparse adapter. TP1/TP2 are different cells. Contexts: 32K, 128K, 512K, 1.01M where supported; label capacity/kernel failures instead of inventing a long-context measurement. Current physical Qwen2.5 measurements in Motivation are state-population microbenchmarks, not these full-system cells.

**Workloads.** (W1) an executable multi-agent coding application with explicit dependency consumption; (W2) FanOutQA with recorded prompts, tool responses and joins; (W3) controlled sequential, balanced fork/join, and heterogeneous fork/join DAGs. Use at least 30 distinct workflows/family in the primary campaign and list exact IDs. The public CC/Weka metadata can parameterize locality and durations but cannot substitute for original prompts or prove dependency edges. Frozen tool-response replay is the first reproducibility mode; live tools are a separate external-validity experiment.

**Load.** Calibrate arrival rates at 30%, 60%, and 85% of the LRU baseline's sustainable throughput under predeclared latency SLOs. Apply the same absolute arrival trace to every policy; do not separately normalize each policy to its own capacity. Report load after the replica loss, which can exceed the surviving capacity. Use open-loop arrivals where possible and report overload/completion instead of deleting outliers.

**Capacity.** DRAM/unique-checkpoint-working-set ratios 0, 0.1, 0.25, 0.5, 1.0; storage ratios 0.5, 1, 2. Count shared objects once in the denominator and record the time-varying working set. All-DRAM is a capacity-relaxed reference. Backing-pool bytes, index metadata, uncommitted staging and retiring copies are included.

**Storage.** Local/remote NVMe and shared filesystem are separate columns, never interchangeable names. Measure cold client-page-cache, warm client, and documented server-cache conditions. Use direct I/O where supported or record exactly how client cache is controlled. A shared filesystem may have uncontrollable server cache; label that state. Measure both read and write paths, request sizes, concurrency, fsync/commit semantics, NIC sharing, and end-to-end GPU readiness. Do not claim SSD latency from an unverified virtual disk.

**Repeats.** Start with 10 independently launched paired campaigns/primary cell. Distinct campaign seeds change arrival jitter, run order and/or fixed failure mapping as declared; they do not make the same 30 workflows into 300 distinct tasks. Warmup is explicit and outside the reported cohort. Expand repetitions based on uncertainty, not until a p-value is favorable.

## 4. Experiments and figures

### E0 — State and recovery correctness (must precede performance)

- Question: do all policies resume the same accepted state, and can every published manifest be resolved after the declared failure?
- Inject immediately before/after reservation, partial copy, checksum completion, storage commitment, directory redirect, token acknowledgement, and lease drain. Include process kill, full replica kill, target loss, duplicate completion, stale epoch, full DRAM, full storage, missing shard/selector state, and write timeout.
- Compare restored history bytewise, all-layer tail KV and hidden states against the same supported reference, and the next greedy output; state allowed numerical tolerances for non-bitwise execution. Test sparse replay equivalence separately from dense quality; otherwise use token-wise replay.
- Check zero reads of PENDING data, zero reused leased buffers, bounded ledgers/queues, stale callback rejection, and no duplicate acknowledged output. Tool side effects use the application's idempotency key and are logged separately.
- Unit: distinct injected protocol interleaving, not timing repeats. Exhaustively enumerate the small state machine and run at least 100 randomized interleavings/type for the prototype. A failed correctness case blocks that implementation cell's performance claim.
- Artifact: `correctness.csv`; `safe-demotion.csv` gets timestamped physical/reserved/retiring bytes from a selected **declared** trajectory, not the best-looking trajectory.

### E1 — End-to-end workflow failure penalty (main result)

- Question: at equal resource budgets, does AegisKV reduce workflow failure penalty against a strong hierarchical baseline, including unaffected workflows?
- Matrix: 3 workload families × 2 models × 3 arrival rates × 2 fault scopes (single request and common worker) × 6 policies × 10 campaigns × 2 conditions (healthy/faulty) = **4,320 complete runs**, for one capacity setting. This is the full primary matrix, not a claim it fits the four days before the deadline.
- First bounded slice: one supported model, one workload family, 60% load, one common-worker event, 4 practical policies, 10 campaigns × 2 conditions = **80 runs**. A passing slice establishes only that slice. Do not generalize it to all workloads/models.
- Fix the source event by workflow/Agent identity and 80% logical progress; kill the worker with all colocated requests. Keep arrival and output/token traces fixed across policies.
- Report healthy and faulty mean WCT, paired penalty difference, p50/p95/p99 with sample counts, completion rate and restricted completion time; show ECDF and paired per-workflow differences. Positive difference means improvement. Include a standalone no-slack workload.
- Plot inputs: `workflow-outcomes.csv` plus raw `workflows.csv`. The theoretical scenario ECDF is replaced by a measured workload ECDF; caption and text must explicitly change evidence and n.
- Falsification: intervals include zero, benefit disappears against tuned LRU plus load-aware recovery, or failure savings are outweighed by healthy cost. Retain these results.

### E2 — Capacity frontier and finite storage

- Sweep the DRAM ratios and finite-storage ratios above at fixed model, workload, load, policy, and source event. Keep copy/foreground bandwidth allocation constant.
- Report paired WCT penalty, cache-covered tokens, reconstructed tokens, bytes read/written, dirty-demotion fraction, rejected backups, manifest lag, and peak physical occupancy. Plot absolute bytes alongside normalized ratio in the log.
- Plot: `capacity-frontier.csv`; main y is WCT penalty, x is GiB. Additional storage-exhaustion panel uses the same long-table schema.
- Controls: zero DRAM and all-state-fits should converge under an otherwise identical policy; missing a safe storage victim must lead to bounded rejection, not hidden memory.
- Unit/repeats: 10 paired campaigns per capacity point, same workload IDs and nominal arrivals. Do not treat each byte sample as an independent trial.

### E3 — Recovery decomposition, storage path and contention

- Measure detection/fencing, readmission, backing read, NIC, H2D, replay, first unacknowledged token, and workflow completion on one causal timeline. Report overlap; never sum durations that execute concurrently.
- Vary storage bandwidth (native plus rate-limited .5/1/2/4/8/12/20 GiB/s where feasible), background I/O, ready retries (1/2/4/8/16), target count, and context. Use measured achieved bandwidth, not limiter settings, on the x-axis.
- Compare serialized restoration and a tuned layer/chunk pipeline for all applicable policies. Only still-required replay computation can hide I/O. Same-directory warm-cache speed does not prove a faster physical medium.
- Plot: `storage-bottleneck.csv`; per-request decomposition data live in `events.csv`. All-DRAM is an explicit memory-relaxed control, never a fair equal-capacity competitor.
- Unit: paired independent campaign; report both device service and observed queue time. Falsification: shared NIC/compute dominates and DRAM policy has no residual WCT value.

### E4 — Mechanism ablations and allocation oracle

- Compare no dependencies, local independent penalties, no normal reuse, no migration cost, no hysteresis, zero-slack fallback, full method, and feasible offline optimum. Change one mechanism at a time.
- Enumerate 2–8 checkpoint groups and all legal assignments with the same capacities, source-failure events and movement constraints. Score absolute fault WCT separately from the mixed objective; an objective oracle need not minimize fault WCT alone.
- For dynamic experiments, compare direct revaluation with full trial rent, rent without aging, and rent without causal renewal, using identical value models, candidate-work budgets, ownership and migration rules. Keep separate DRAM and storage ledgers; exercise leased zero-credit objects, duplicate demand events, rejected previews and SSD-full cascades. Verify that rejected previews leave committed rent unchanged and that every committed replica ages even when outside the safe victim set. Measure bytes migrated, decisions/s, CPU time and rejected/promoted plans; no rental benefit is currently established.
- Cross sparse demand ranking (recency versus causal access history) with restoration scheduling (serial versus bounded layer pipeline). Hold committed recovery coverage, transient GPU/host workspace, candidate byte budget and actual native attention path equal. Report useful/unused prefetched bytes, demand misses, reveal-to-ready wait, replay duration and total WCT. Dense models use full demand and form a separate control. Do not count avoided prefix computation as overlap time or change attention selections to improve a cache policy.
- Plot: `policy-ablation.csv`, two panels: fault penalty and normal next-use restore. Report paired campaign confidence intervals. Preserve any normal-service regression from a fault-prioritized policy.
- Falsification: simple reuse-only or dependency-free policy achieves the same frontier, or the greedy gap is too large relative to benefit.

### E5 — Runtime prediction, causal validity and robustness

- Train GBDT on earlier complete workflows, tune on a disjoint validation split, test on later held-out workflows. No snapshots of one workflow in multiple splits.
- Landmarks: request arrival after a completed prior call, fork, join, and tool completion. Features must be visible at that exact landmark; label actual remaining segment time. Report eligibility/exclusions and cold starts.
- Raw diagnostic: per-agent/segment absolute error (s), relative error using **remaining-time** denominator, critical-path ranking, false-positive slack and zero-slack fallback rate. Do not manufacture a CDF from correlation or WAPE aggregates. Existing weak/negative GBDT diagnostics remain valid historical evidence and are not overwritten.
- Inject correlated and independent ±10/25/50/100% duration error, underprediction versus overprediction, missing DAG edges, workload/model shifts, and failure-rate miscalibration. Replay actual policy decisions and measure WCT regret/changed plans.
- Plot: `prediction-robustness.csv` for end-to-end perturbation response; an additional error-CDF table must be built from raw predictions. The provided analytical perturbation curve is **not** a learned predictor's accuracy curve.
- Unit: independent workflow with campaign clustering for serving metrics. Falsification: inference/monitoring cost cancels benefit, or error makes the method consistently worse than fallback.

### E6 — Checkpoint interval, actual lag and logical fault phase

- Z ∈ {64, 256, 1024} generated tokens, block aligned. Record each trigger, attempt, committed frontier and copy completion. Full context is not recopied at each trigger.
- Fault progress ∈ {20%,50%,80%,95%} of the same Agent's frozen total token progress; separately inject in prefill and during demotion. Do not equate a common wall-clock time with matched work.
- Enumerate phase N=0..Z−1 only for the ideal analytical model, pair same-Z policies state by state, then average. Actual measurement uses the observed committed frontier; N may exceed Z.
- Plot: `checkpoint-lag.csv` with mean/p95 replay and WCT against achieved commit lag. Report common detection floor, tail-replay token rate, backup/write traffic, stale-frontier rate, and failed commits.
- Falsification: backlog prevents useful coverage before the fault, or extra writes dominate normal service. Report complete distributions rather than claiming Z is a durability bound.

### E7 — Healthy service and multi-turn reuse

- No failures; each original workflow runs once. Include first calls and every request in the denominator. Run the full normal cache policy for high-Slack Agents as well.
- At each baseline-defined load, report WCT, TTFT, token delay, SLO goodput, active GPU time, storage traffic, cost per completed workflow, and controller CPU/memory. Separate request-hit/token-hit and local HBM/shared DRAM/storage hits. Potential trace prefix sharing is not an observed runtime hit.
- Compare normal reuse plus fault value against fault-only value, ordinary LRU, and no new protection. Vary next-use frequency, context growth, tool waits, and normal/fault probability weights.
- Plot: `healthy-io.csv` may hold measured I/O response-time versus backup utilization with the same axes; **do not relabel it TTFT**. TTFT/SLO plots have separate metric names/config entries and must preserve units.
- Unit: 10 independent paired campaigns; report absolute healthy metrics and paired changes. A non-significant difference does not prove zero overhead or equivalence.

### E8 — Dynamic pressure and safe demotion

- Timeline: contexts grow → tool handoff → repeated calls → DRAM target 24→16 GiB → storage write backlog → worker failure. Also test the reverse pressure transition and overlapping reader leases.
- Log target, committed, reserved, retiring, staged and actually free bytes at every event. Follow fixed selected IDs across time. Enforce backpressure when physical occupancy exceeds the new target until legal release; never allocate against the target as if bytes already freed.
- Plot: `safe-demotion.csv`; show policy targets as dashed steps and physical bytes as solid steps. Mark commit/redirect/drain timestamps from logs. Count byte movement and requests stalled/rejected.
- Unit: independently replayed pressure traces plus correctness interleavings. Falsification: unsafe release, unbounded queue, starvation, data loss, or excessive churn.

### E9 — Scaling and control cost

- DP=2/4/8 and 1/2/4 simultaneous source-domain failures, only with the advertised spare replicas/backing survival. DAG sizes 10/100/1,000 segments, live groups 10²/10³/10⁴, bounded candidate sets 16/64/256, horizons and profile-sample counts held explicit.
- Measure controller decision p50/p95/p99, snapshot lock time, time spent in profile queries, metadata bytes, update lag, and true workflow outcome under the same CPU budget. Exhaustive oracle only for small instances.
- Treat unsupported multiple-failure cases as out of scope rather than silently converting them to independent single failures. Report response under replica loss and physical target memory limits.
- Additional plot panels use `figure,panel,series,x,y,...` schema with a registered visual spec. Do not claim scale from number of synthetic CSV rows.

## 5. Statistics and failures

The primary inferential unit is an independently launched **paired campaign**. For each campaign, first compute policy-specific fault−healthy WCT by matching workflow IDs, then baseline−AegisKV differences. Average within campaign using the predeclared cohort, then bootstrap the campaign differences (10,000 resamples with a recorded analysis seed). Bootstrap noise is analysis uncertainty, not a new physical repeat. A secondary hierarchical bootstrap resamples campaigns then workflow IDs while keeping policy/condition mates together. For workload heterogeneity, report each family and its n before any weighted aggregate; weights are fixed before measurement.

Complete-case latency may be shown only with completion counts and a companion restricted completion metric at common horizon τ. Report a timeout as censored with its reason; RMST/quantile handling must state its estimator. An implementation error is not ordinary censoring. Very small n does not support precise p99 confidence intervals. The 36 analytical configurations have **zero** physical runs and no statistical confidence bands.

The figure replacement process must keep negative y values, outliers, ties, missing cells and unsupported configurations. Axes are autoscaled to all finite values; distributions retain their full tail. Never improve a graph by selecting only favorable seeds or using a per-policy saturation normalization.

## 6. Raw logging contract

- `runs.jsonl`: campaign_id, pair_id, policy, condition, workload/model revisions, config hash, topology, backend, arrival/fault seeds, start/end, status, timeout horizon, warmup, and all capacity/bandwidth settings.
- `workflows.csv`: campaign_id, pair_id, policy, condition, workflow_id, release_s, finish_s, wct_s, status, direct_fault, shared_resource_exposure, workload_family. Empty finish is explicit; do not fill with a theoretical value.
- `requests.csv`: request/Agent/segment IDs, model/layout, prompt/output tokens, TTFT, token timestamps, tier bytes/hits, reconstruction, routing/admission delay, original accepted-token frontier.
- `events.jsonl`: monotonic time, source epoch, object/version/location generation, operation, parent event, tier, requested/reserved/committed/retiring/released bytes, queue, transfer start/end, CUDA correlation ID, checksum, manifest ID/frontier, return code.
- `predictions.csv`: causal landmark, feature snapshot time, predicted/actual remaining seconds, full-workflow split, estimated/actual slack, fallback reason. Actual values are analysis targets only.
- `correctness.csv`: injection_id, logical trigger, fault domain, expected/observed manifest, checksum/parity result, duplicate output count, live leases at free, progress/completion, error text.

Each raw file is hashed. A measured plotting manifest records hashes, exact aggregation command, statistical unit, n at all three levels, uncertainty definition, exclusions/censoring, and source revision. The renderer refuses mismatched hashes and mixed analytical/measured evidence.

## 7. Decisive interpretation

A submission-worthy positive claim requires improvements against tuned equal-resource baselines on executable workflows, correct common-source failures, acceptable healthy overhead, and parity/safety tests. An analytical model can justify hypotheses and expose limits but cannot establish those runtime claims. If effects vanish at realistic failure rates, if ordinary reuse dominates the score, or if DRAM is never actually scarce, report that operating boundary and narrow the paper. Do not replace it with more favorable synthetic input.
