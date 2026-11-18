I'll read the manuscript, the evaluation protocol, the prior findings, and the current runtime, then write a prioritized review.The manuscript and protocol are loaded. Next I'm reading the current runtime modules to see what the simulator actually models versus what the design claims.Runtime is loaded. Now checking the FanOutQA input, the prior preflight review, and Motivation's O1–O3 claims that the Evaluation must support.The shell sandbox is unavailable on this kernel, so I'll use the file-reading tools directly instead.FanOutQA has explicit `depends_on` edges and Wikipedia evidence per sub-question. I'll check its structure (nesting depth, fan-out, whether any timing or model outputs exist).The frozen file has 310 top-level questions, while the protocol says 160. I'll check the file's tail and a nested decomposition to see how join edges are represented.The FanOutQA adapter expects 310 tasks and uses a declared-uncalibrated linear timing model. I'll check how it produces outputs and maps nodes to tasks.That file is a raw transcript of an earlier run of this same prompt. I'll check its ending to see whether it completed and what it concluded.I'll verify the 128K guard inside `_record` so the selection description is exact.**Verdict: the planned Evaluation is not yet defensible as a top-tier simulation-only study, and nothing here is publication-ready.** Four gaps block it:

- The foreground model runs one request per worker.
- The main workload never exercises multi-invocation Agent histories, and its outputs are gold answers.
- Costs are uncalibrated, and some estimates reuse the simulator's own cost function.
- There are no native sparse-attention selection traces for the evaluated prompts.

The prior campaign already shows the effects:

- HBM changed mean faulted WCT by under 2 ms compared with DRAM-only: 1.4 ms faster with dense attention, 1.6 ms slower with the synthetic sparse selector.
- The failed invocation waited 1.62 s in the retry queue under every policy.
- Mean healthy WCT was 10.1700 s for every policy, because no overhead is modeled.

For each dimension below, in priority order, I give the gap, the smallest repair, and the acceptance criteria.

### P0: Shared queues and batching

- **Gap.** Each DP worker runs one request at a time, in arrival order. A failure therefore interrupts exactly one busy request:

```1316:1316:/home/comp/zhanzhao/MoonKVSim/python/moonkvsim/aegiskv/current/runtime.py
        affected = [self.states[k] for w in sorted(failed) if (k := self.busy[w]) is not None]
```

  This has three consequences:
  - A retry waits for the whole running request instead of joining the next batch. That inflates queueing equally for every policy and shrinks the differences between them.
  - Background's failure event (every Agent co-resident on the worker) and Motivation's non-additive common failure only happen when a whole host fails.
  - The O3 trade-off (replica HBM versus foreground capacity) cannot show up. Replica HBM never shrinks batch capacity; it can only block one request from being admitted.
- **Repair.** Run the current policy on MoonKVSim's existing vLLM-semantics scheduler. `integration/vllm/scheduler.py` is already checked against a golden captured from pinned vLLM, and `aegiskv/continuous_batch_des.py` drives it across multiple GPUs. Add:
  - chunked prefill, capacity-limited admission, preemption, and a step-cost model that depends on batch composition;
  - replica HBM subtracted from the scheduler's block pool;
  - restore and tail rebuild joining the target worker's batches;
  - shared PCIe links for checkpoint copies, restore copies and foreground traffic.
- **Accept when:**
  - the scheduler differential passes on this evaluation's request mix;
  - a worker failure interrupts every co-scheduled request, and results are broken down by how many Agents were interrupted;
  - foreground throughput, time to first token and time per output token are plotted against replica quota, and the Adapter is compared with at least three fixed quotas on that curve.

### P0: Workload provenance

- **Gap: what the FanOutQA replay actually contains.** It is a human-written DAG plus revision-pinned Wikipedia evidence, wrapped in an adapter prompt template. It uses gold answers as outputs (`output=answers[node_id]`), zero tool delay, and a linear timing model the adapter itself labels uncalibrated. Its records also put modeled values into fields named "observed":

```843:845:/home/comp/zhanzhao/MoonKVSim/python/moonkvsim/aegiskv/fanoutqa.py
        "observed_submit_ns": 0,
        "observed_finish_ns": duration_ns,
        "recorded_api_time_ns": duration_ns,
```

  Every edge, including the adapter-added fan-in edges, is tagged `origin: "observed"`, and every record says `synthetic: False`.
- **Gap: which parts of the design it exercises.** Every Agent has exactly one invocation. Leaves are dominated by prefill, and their outputs are a few to a few dozen tokens, so an 80% total-token trigger lands inside prefill for almost every node. None of these is ever exercised:
  - history growth across invocations;
  - re-evaluation at invocation boundaries;
  - replica lifetime across calls;
  - checkpoint lag during decode.

  That is the setting Background and Motivation describe.
- **Gap: the 160-task set.** The protocol calls it the "complete frozen set of 160". It is actually the first 160 tasks, in SHA-256 order of task ID, among the 310 dev tasks that have pinned evidence and pass an unsegmented 128K-token guard. The guard drops every task with any record over 128K tokens, which are exactly the tasks where reconstruction costs the most.
- **Repair:**
  - Replace gold outputs with generations from the pinned served model on the exact prompts, recording token IDs and decoding settings. Keep gold outputs only as a labeled short-output variant.
  - Add one multi-invocation family with a known DAG. One option: a fixed-DAG orchestrator over the same decompositions, where each node is a tool-using sub-agent (search, read, answer), recording real calls, tool gaps and outputs. The other: observed multi-call episodes where chains within an Agent are exact and joins across Agents are labeled as assumed, as Figure 2(a) already does.
  - Declare the arrival process relative to measured capacity.
  - Fix the protocol's wording, and publish the rejected task IDs with the length distribution of included versus rejected tasks.
- **Accept when:**
  - every record carries a source class: human DAG, pinned evidence, generated output (with model revision and decoding settings), and observed versus modeled timing;
  - no modeled value sits in a field named observed or recorded;
  - each family's prompt, output and history lengths, and invocations per Agent, are published;
  - the 310-to-160 selection can be reproduced from hashes;
  - at least one family has multi-invocation Agents, nonzero gaps between invocations, and failures during decode.

### P0: Model costs and calibration

- **Gap: default parameters.** Prefill costs a flat 100 µs per token and decode 2 ms per token. Host-to-GPU (H2D) bandwidth is 2 GB/s, failure detection takes 1 ms, and `compute_dma_slowdown = 0`, so copies never slow computation. The geometry is a generic 32-layer one, while the adapter tokenizes with Qwen3-8B. The 128K guard also exceeds Qwen3-8B's native 32K window, so long prompts need YaRN rope scaling.
- **Gap: circular estimates.** Reconstruction time T_a is estimated with the same `_duration` function that `_step` uses to advance simulated time, so the estimate is exact by construction:

```617:617:/home/comp/zhanzhao/MoonKVSim/python/moonkvsim/aegiskv/current/runtime.py
            exposed = max(0, self._duration(state, 0, state.durable, "prefill") - slack[key])
```

- **Gap: no validation.** The HBM gain uses an estimate that ignores contention. No simulated path has been compared with a real engine. A 1 ms detection time inflates the share of failure-to-first-token that checkpoints can remove.
- **Repair: measurements.** For one pinned model, rope configuration and GPU type, measure:
  - prefill latency versus chunk size and context length;
  - decode step latency versus batch size and context length;
  - H2D and GPU-to-host bandwidth versus transfer size and concurrency (one 64-token block per layer per rank is 128 KiB here, a small copy);
  - NIC throughput for checkpoint chunks;
  - decode slowdown while checkpoint copies and counter updates run.
- **Repair: modeling and validation.**
  - Take detection latency from a declared health-check mechanism.
  - Fit the T_a, T^D and T^H estimators from a separate offline profile, so they carry real residual error.
  - Validate the healthy path against a real vLLM run of the same workload and arrival pattern, as serving simulators such as Vidur do.
  - Reproduce Motivation's measured DRAM-reuse point.
- **Accept when:**
  - every parameter has provenance: measurement hash, fit and residuals;
  - simulated per-request latency and workflow WCT match the real engine within pre-declared tolerances at every load level;
  - estimate error is reported and is nonzero;
  - headline results are repeated at 0.1× and 10× the declared detection latency;
  - any path still costed at zero is listed as omitted, and healthy runs differ across policies wherever interference is modeled.

### P0 for any HBM or Top-K claim: Native sparse traces

- **Gap.** The runtime's sparse mode is a rotating synthetic selector. The default is dense attention, where Top-K is meaningless because every visible block is needed.
  - Motivation's native evidence measures retrospective concentration over the last 512 queries of 32K-token PG19 prefixes, on NOSA, NSA and MiniCPM4.1. It is not on the evaluation prompts or tokenizer.
  - The design depends on causal coverage: whether the Top-K set chosen at a checkpoint predicts which blocks the recovery tail will select.
  - An archived diagnostic recorded about 43% mean coverage at a matched budget, with the offline oracle at 43.3%. That does not support "misses are few" in general.
- **Repair.**
  - Use one native sparse model as the served model for all HBM experiments. Take geometry, costs, outputs and selections from the same pinned checkpoint.
  - Capture per-layer, per-query block selections on the evaluation prompts and generated outputs.
  - Replay them as the only source of demand for access counts, estimates and recovery.
  - Choose K on a separate data set, and compute the per-layer rebuild time r, load time h and break-even bandwidth B* from calibrated profiles.
- **Accept when:**
  - traces are hashed against model revision, prompt hash and kernel configuration;
  - a test proves the synthetic selector cannot be reached once a trace provider is configured;
  - causal hit rate and misses per layer at recovery are reported;
  - HBM benefit is plotted against B/B*, including the regimes where it is zero;
  - dense models are evaluated with DRAM checkpoints only.

### P1: Exact Agent DAG

- **Gap.** The edges are exact annotations plus two adapter rules: children fan into their parent, and a synthetic `final` node joins the top-level nodes. Every fan-in node in a workflow shares `agent_id: "fanout-root"`, so keying Agents by `agent_id` would silently create the multi-invocation Agent the protocol forbids.
  - When leaf durations scale with prompt length, a single-level fan-out gives slack s_i ≈ P_max − P_i, where P_i is branch i's prompt-proportional duration.
  - Ranking by exposed delay E is then almost the same as ranking by prompt length, which is known at submission.
  - On this workload, slack-aware selection can beat a size heuristic only through queueing, multi-level DAGs, or durations that don't track KV size.
- **Repair.**
  - Key Agents by span.
  - Label each edge as source or structural.
  - Publish DAG depth, width, and the joint distribution of reconstruction time T_a and slack s_a at failure time.
  - Add DAG-shape controls: a chain with no slack, an equal-slack fan-out, and a skewed fan-out.
  - Include a family where duration and KV size diverge, such as long decodes or tool gaps.
- **Accept when:**
  - the number of Agents equals the number of spans;
  - the fraction of Agents with T_a > s_a is reported per family;
  - the paper reports, for each family, whether AegisKV beats longest-prompt-first at equal bytes, including families where it does not.

### P1: Prediction realism

- **Gap.** The default predictor is the per-role duration prior, the context regressor is a hashed linear model, and the slack guard is zero.
  - In the replay, durations are deterministic functions of visible prompt length, so a regressor trained on simulated runs simply learns the simulator.
  - The only real-trace evidence (1,443 snapshots in 170 workflows) had a mean absolute error of about 400 s, with no significant gain over a median baseline.
- **Repair.** Train on durations from real runs, from the trace-collection and validation runs above. Split by source question into training, guard-calibration and test sets. Evaluate:
  - oracle slack;
  - the trained predictor;
  - the prior alone;
  - injected errors matched to held-out residuals, plus 2× and 4× inflations;
  - no slack at all.
- **Accept when:**
  - held-out error and guard coverage are reported;
  - a confusion matrix shows protect versus don't-protect decisions against oracle slack;
  - WCT regret versus oracle slack has confidence intervals;
  - the headline result uses realistic error, not the oracle.

### P1: Controls

- **Gap.** There are no oracle bounds, no selection baselines at equal bytes, and no baseline a practitioner would deploy. The budgets also did not bind: the prior DRAM-pressure and λ = 1 s cells collapsed to plain restart.
- **Repair: bounds.** Add oracle slack, an oracle that knows which Agent will fail, and the optimal protection set found by exhaustive search or an integer program on small instances.
- **Repair: baselines at equal bytes.**
  - T_a-greedy, longest-prompt-first, LRU and random selection.
  - Modeled "replicate everything" to peer DRAM or peer HBM, labeled as DéjàVu- or Lumen-style approximations rather than reproductions.
  - A Mooncake- or LMCache-style DRAM KV store with LRU eviction.
  - A restart that may reuse surviving prefix caches.
- **Repair: HBM alternatives.** Full first-L layers, random K blocks, and oracle K blocks.
- **Repair: analytical anchors.** With contention disabled, the simulator must reproduce Figure 2(b)'s protected set at λ = 17 s and the depth equation's L.
- **Accept when:**
  - selective policies share budgets, routing and failures;
  - the fraction of time DRAM and HBM budgets bind at the primary configuration is reported and is non-trivial;
  - regret to the oracle and gain over the best heuristic both have confidence intervals;
  - the analytical anchors pass within numerical tolerance.

### P1: Scale and statistics

- **Gap.** The prior campaign used three seeds × three workflows on four hosts, one fixed failure target (`wf00/slow` at 80%), and reported p95/p99 over nine samples.
- **Repair.**
  - Enumerate failures over all Agents on a grid stratified by phase: prefill, early decode, late decode.
  - Report results both unweighted and weighted by each Agent's occupancy time; the weighted version estimates a failure that strikes a worker at a uniformly random time.
  - Use at least three load levels relative to measured saturation, and at least two cluster sizes, one with 16 or more DP workers.
  - Make arrival seeds the only source of load randomness.
  - Bootstrap paired differences by source question.
  - Pre-register the primary endpoint and the smallest effect of interest.
  - Add an expected-cost analysis that combines healthy overhead with added WCT under a failure rate, and report the break-even failure rate.
- **Accept when:**
  - the primary endpoint's confidence-interval half-width is below the declared smallest effect;
  - p99 appears only with at least 1,000 paired samples and p95 with at least 200, otherwise report the maximum and n;
  - every planned cell, unreachable trigger and failed run appears in the artifact.

### P1: Disclosure

- **Gap.** The frozen Design asserts properties the evidence contradicts or cannot show:
  - The rebuilt tail is "at most Z". The prior slow-copy run needed 5,223 tokens rebuilt against Z = 256. Prefill produces KV far faster than decode, so the prefill-heavy main workload will stress this bound hardest.
  - An unprotected Agent "adds at most λ". That fails under capacity-limited admission, estimate error, queueing, and failures that hit several Agents.
  - "Misses are few."
  - "Normal execution pays little."

  AGENTS.md discourages self-limiting prose in the manuscript, but a simulation-only Evaluation still has to state its method.
- **Repair:**
  - a methodology paragraph stating the simulation-only scope;
  - an evidence class and model/hardware source in every caption;
  - a parameter provenance table;
  - a table mapping each Design claim to its Evaluation evidence, or to "not evaluated";
  - measured violation rates for the tail bound and for λ, with causes attributed;
  - negative results in the paper, including any persistent null result for HBM.
- **Accept when:**
  - every quantitative Design assertion has a measured distribution in the Evaluation;
  - the task selection, output source and predictor split are stated in the text;
  - caption labels match the artifact manifest.

### Claims that remain unsupported even with a complete simulated matrix

A complete matrix can support two things: relative WCT, traffic and capacity trade-offs among policies in one calibrated simulator on the declared workloads, and a map of where each mechanism matters as B/B*, λ, DRAM budget, load and prediction error vary. It cannot support:

- **Physical healthy-path cost:** "normal execution pays little", "unprotected Agents incur no cost", GPU counter updates "without host synchronization", and asynchronous Tracker work never delaying dispatch. Simulation can only carry forward measured microbenchmark costs.
- **Engine and kernel capabilities:** computing attention on hits while misses load, then merging by log-sum-exp; adopting peer-HBM blocks in place; selection metadata resident in HBM; and letting misses jump ahead of the layer-ordered transfer stream. The simulator assumes these rather than demonstrating them.
- **Recovery correctness under real faults:** token-exact continuation, fencing, TP shard barriers, and "HBM copies never affect correctness" under partial writes, RDMA completion semantics or CUDA context loss. The simulator only verifies its own byte ledgers and token counts.
- **Failure behavior outside the single-failure model:** real detection and fencing latency distributions, correlated or repeated failures, and failure during recovery.
- **Generality and absolute numbers:** fit to production agent traffic, and any absolute latency or throughput figure.
- **Prediction:** predictor accuracy on real Agents, the value of the text encoder, and transfer of a calibrated guard to other workloads.
- **"Misses are few"** beyond the traced models, prompts and budgets.
- **Guarantees:** "adds at most λ" becomes an empirical violation rate. "Admitting in decreasing G_a removes the most delay within the quota" holds only with equal copy sizes, additive per-Agent gains and exact estimates.
- **Non-additive common failures:** the Design's per-Agent threshold rule does not model co-affected Agents, which Motivation says decisions must consider. The matrix can measure the gap to a joint oracle, but cannot show that AegisKV closes it.
- **Adapter safety:** "memory is not overcommitted" on a real allocator, and AIMD stability under real load.
- **Named systems:** superiority over DéjàVu, Lumen or any other named system. Only modeled approximations can be compared.

Even with every repair, a simulation-only evaluation of a design that depends on kernel- and engine-level behavior is a significant risk at EuroSys. The repairs make it a defensible simulation study, not a substitute for a prototype.
