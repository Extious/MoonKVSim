# Depth score and profile contract (revision 2026-09-19)

This is a paper/design specification and arithmetic reference, not a completed
runtime, trained predictor, calibrated table, or performance result. It accompanies
Section 3.5 and Algorithm 2. The numerical example is explicitly synthetic.

## Objective and fixed comparison

For a given request r, freeze the target snapshot S, its current slack sigma,
one policy horizon H, the candidate grid and quota rule, and a conditional
failure-state distribution with weights summing to one. The conditioning event
is a source failure within H, under the declared failure model.

For a Poisson assumption, p = 1 - exp(-lambda * H), with lambda in failures/second.
The paper denotes this probability by pi_r; p_r remains the retry DP rank.
The weights are conditional probabilities, so p is multiplied exactly once.
Do not plug an unconverted annual failure rate into the score.
The operational risk prior is separate from an experiment's injected failure
frequency; the synthetic fixture's rate is invented arithmetic input.

J(d) = A(d) + p * sum_j w(j) * max(0, R(d,j) - sigma).

A(d) is aggregate foreground request-delay change, in seconds, relative to an
explicit keep plan from the same S. A may be negative. It includes dirty
writeback, new-copy work, temporary occupancy, queueing and admission effects.
It is not simply copy_bytes / link_bandwidth.

For a reproducible matched normal-service profile, declare the foreground
cohort: requests already active at the decision plus arrivals in [0,H).
Run both candidates with the same cohort/arrival order, batching, runtime
versions and resource scheduler, with no additional policy changes. Observe
the declared cohort to completion (including completions beyond H), or mark
the profile unsupported if the measurement/model terminates earlier.
A is the sum of per-request completion-time differences from keep. This
held-policy, finite-cohort measurement is a local cost proxy, not an exact
forecast of an open serving system with future replanning.

R(d,j) is elapsed time from the sample's failure event to the retry's required
state being ready to continue. Its timeline includes detection, reroute/admission,
restoration, selector execution, tail replay and their actual overlap. It
credits only matching replicas committed before the sampled failure instant.
A prediction/preload is never itself a commit. Measure R directly or use a
declared calibrated event model; do not add full overlapping copy and compute
durations. All candidates use the same scenarios and exogenous arrivals.
Scenario-dependent state may differ only because the candidate changes placement,
migration completion and resource interference.

The first term is a foreground aggregate and the second is this request's
expected slack excess. Their sum is a deliberately local proxy. It is not a
workflow-makespan equation, global optimum, full stochastic expectation over all
requests, or proof that one layer count is optimal for future unknown failures.

## Required profile input

| Field | Meaning / units |
|---|---|
| schema_version, generation_id | Versioned profile interface and immutable calibration generation |
| model_revision, weights_revision, selector_revision | Exact architecture/weights/native selection path |
| kv_dtype, kv_layout, block_tokens, shard_map | Physical bytes and compatibility, including all required auxiliary state |
| topology, effective_link_profiles, hbm_profile | Shared resources and measured/modelled support, not peak-link constants alone |
| snapshot_id | Directory generations, ownership sets, I/O leases, reservations, occupancy and active queues |
| grant_plan_id | Retains, owner releases, protected system demotions, new allocations, temporary buffers and expected completion times |
| quota_rule | fixed_blocks or declared fraction; values per applicable model/layer; forced-block accounting |
| depth_grid | Explicit finite set containing zero and current depth, plus a separate keep plan |
| horizon_s, failure_model | H and its matching source-failure probability model |
| conditional_failure_samples | Unique sample IDs, normalized weights, failure offset within H, M, N, commit lag, request growth and concurrency |
| scheduler_configuration | Foreground/recovery dispatch shares, per-link foreground/demand/writeback shares, outstanding limits and operation granules |
| switch_margin_s | Nonnegative uncertainty-separation margin |
| validity_configuration | Supported ranges, expires_at, drift_relative_error, drift_patience and positive error denominator floor |

A quota is an input to this revision, not the attention selector's top-k and not
the actual K. K is the cardinality of each request/layer's published committed
Peer set. A fixed quota need not be fully admitted; fraction-based quotas must
be named explicitly. Mandatory state and transient/retiring space remain charged.

## Required profile output

- Candidate A interval [lower, estimate, upper] in seconds, allowing signed values.
- For each common scenario, nonnegative R interval [lower, estimate, upper].
- Evidence type: measured, calibrated_model, or unsupported; never silently
  relabel the synthetic arithmetic fixture as calibrated.
- Calibration/source hashes, generation, creation/expiry times and applicable
  model, context, replay-tail, bandwidth and concurrency support.
- Reason when any value is missing or outside support. Missing is not zero.
- Cost breakdown sufficient to audit writeback, new-copy work, metadata,
  queueing, ready events and double-counted overlap.
- Uncertainty method and sample count. Intervals must be interpreted jointly
  according to that declared method; marginal intervals alone are not a claimed
  simultaneous confidence guarantee over an arbitrarily large grid.

No calibrated A/R table is supplied by this revision. Existing Figure 5 numbers
do not instantiate this interface for arbitrary M, N, load or migration plans.

## Deterministic choice and fallback

1. Preview each candidate independently from identical S. In a multi-request
   refresh, commit only the chosen virtual plan before processing the next
   request in (slack, stable ID) order.
2. Exclude infeasible or unsupported candidates. A missing keep profile, or an
   invalid generation, freezes discretionary change and retains existing
   protection only if feasible. A new request attempts finite DRAM admission;
   failed backing admission uses an older valid checkpoint or recomputation.
3. Compute score intervals by applying the monotone positive-part function to
   each R endpoint, using the declared weights and probability; add A endpoints.
4. Minimize estimated J, then smaller depth, then stable plan ID. Switch only
   when new_upper + switch_margin < keep_lower. Otherwise keep the old set.
5. Budget contraction and correctness constraints have higher authority.
   An infeasible keep plan triggers safe demotion rather than waiting for the
   profile to improve or the LLM request to finish.
6. Atomically recheck real reservations and directory generations before
   execution. Smaller actual grants are reported and later re-evaluated.

A comparable duration observation x invalidates the matching profile generation
after drift_patience consecutive violations of

abs(predicted_x - observed_x) / max(observed_x, error_floor_s) > drift_relative_error.

Reset that key's violation count after a comparable in-threshold observation.
Do not use a different model/load/phase as validation. Raw component timing
residuals can invalidate a profile; they do not prove that the aggregate
counterfactual A or fault-time R is accurate. Expiry/support checks remain
necessary even without observed failures. Missing parameters are configuration
errors; a production caller must use the safe fallback rather than invent them.

## Replica retirement and scheduler boundary

Ordinary request priority cannot revoke another request's ownership protection.
The owner may release its own heat-set memberships; if other owners remain,
the physical location stays protected. Adapter contraction can override
ownership protection but cannot override an I/O lease.

Required physical retirement sequence:

1. Commit compatible DRAM backing, allocating and copying only when necessary.
2. Atomically publish DRAM as the new lookup location and close old-generation
   lease acquisition. A stale lookup must fail generation validation.
3. Wait for old read/write/DMA lease holders; a pending write is not a readable
   committed replica.
4. Free the physical HBM buffer and only then return its bytes.

All these operations require an implementation and race/failure testing.
Reference-score checks below do not validate them.

During copy pressure, each shared bottleneck accounts for foreground, demand
fetch and required writeback with configured service shares; recovery demand
and shrink writeback must have positive progress shares while active, and
foreground retains a share. Their sum is <= 1. Unused service can be borrowed.
Within demand service, byte DRR plus bounded outstanding transfers prevents
one request monopolizing the class. Speculation yields to actual demand.
Fair compute dispatch is likewise bounded and does not wait for a prior retry
to complete. These rules do not promise finite latency under infeasible
memory demand, failures of the serving resources, or overload.

## Arithmetic reproduction

From the repository root:

    python3 benchmark/AegisKV/experiments/scripts/paper/check_depth_policy_contract.py --self-check --output output/pdf/aegiskv-external-review-revision-20260919/DEPTH_SCORE_CHECKS.json

The file includes the synthetic input and numerical output. It checks marginal
depth value, zero risk, fully absorbed recovery, interval stability, writeback
cost, invalid-profile fallback, contraction priority and identical snapshots.
It does not implement admission, infer profiles, simulate a GPU, or validate WCT.
Supply a JSON input with the same schema via --input to recompute a declared
candidate comparison. The reference rejects malformed intervals/distributions;
a runtime wrapper must convert such validation errors into the safe fallback.

## Still required empirical work

Versioned joint M/N profiles; Agent-phase selection traces; matched foreground
costs under migration; actual checkpoint commit lag; source-failure risk
calibration; confidence and drift behavior; long-running request replacement;
shared-block retirement; source failure during each migration phase; recovery
fairness and saturation; DRAM exhaustion; physical HBM backpressure; and paired
end-to-end workflow completion time/normal-overhead evaluations.

## Review supplement: minimum recovery and backing contract

These are required, checkable interfaces, not a claimed implemented protocol.

| Operation | Preconditions and postcondition |
|---|---|
| Publish new source epoch | Surviving authority fences old writers; every new copy/metadata commit and token acknowledgement checks the epoch. Previously committed immutable replicas remain usable if their contents and manifest are valid. |
| Acknowledge output | Persist request ID, logical token index, token ID and epoch in an ordered surviving log first; recoverable prompt and accepted tool inputs precede their dependent output. Delivery deduplicates by request/index. Tool side effects use the orchestrator's idempotency mechanism. |
| Commit object | A sealed interval, canonical prefix, weights/model/layout, layer/shard, byte size, content/version identity and selector-state schema match the reserved object. PENDING is unreadable. Physical location generation is distinct from logical content identity. |
| Publish frontier F | A versioned manifest covers every required dependency through F: all layer/shard KV, applicable selector/index/compression state and the log prefix. Entries may reuse older immutable objects with proven matching content; they need not have the same physical copy timestamp. |
| Resolve mixed locations | Each entry independently resolves to a committed, surviving compatible Peer or DRAM replica. Independent path commits do not create a joint checkpoint automatically. The largest individual object offset is never the global frontier. |
| Recover | Fence first, validate surviving manifest closure again, restore the greatest valid frontier, replay the acknowledged suffix from the log. If none exists, use recoverable inputs. A partial new manifest never discards the last valid older one. |
| Change replay batching | Demonstrate native selector and recurrent state evolution equivalence under declared tolerances, causal visibility, weights and numerical configuration. Otherwise use the original token-wise path. A native prefill gate is insufficient evidence; unresolved numerical diagnostics remain open. Future stochastic outputs are not required to be bitwise equal. |

Failure assumptions must list the surviving control/log authority, DRAM and Peer
failure domains, and failures outside coverage. Source fencing does not recover
data whose only surviving backing is also lost. For a complete reproducibility
run, retain the epoch, manifest ID, dependencies, ACK/log frontiers, logical-object
versions, physical-location generations, and the observed active readers.

New backup requests apply to D/P; tier R does not unconditionally create DRAM
backups. Writeback required by safe retirement remains a separate migration action.

DRAM has its own capacity and ownership ledger. Charge committed, pending,
retiring and temporary bytes plus metadata, deduplicating physical sharing.
Reserve the missing closure before accepting a new checkpoint. A published
manifest and active reader hold references; zero-reference blocks use LRU and
lease-safe retirement. Keep the older manifest until the newer closure commits
or explicitly withdraw its backup claim and report the recompute fallback.
An allocation/transfer failure cannot convert a partial set into full D coverage.
Peer placement or denial never implies that DRAM admission succeeded. If no
complete backing can be obtained, retain the greatest valid older frontier plus
replay, or fall back to R. Required protected Peer demotion waits and reports
pending bytes if backing cannot be committed; it cannot silently discard data.

Each copy queue has byte/operation limits. A new plan replaces only superseded
unstarted work; preserve dependencies and reservations of in-flight and committed
versions. Cancel abandoned reservations only after physical work is stopped and
leases drain. If a new checkpoint cannot be admitted, skip/coalesce it and expose
the actual lag. Z is a decision trigger, not an upper bound on the replay tail.

## Review supplement: tier boundaries, cold start and event correlation

For valid point estimates, R is selected when sigma >= R_R. Otherwise D is
selected only when R_D < R_R and sigma >= R_D; other requests compete for Peer.
The non-Peer fallback is the cheaper feasible route (R wins ties), not always D.
Unknown profiles attempt admitted DRAM without asserting superiority; an
unavailable backing store falls back to an older checkpoint or R. If only one
route is feasible it must be used. At recovery, overlapping uncertainty intervals
retain the feasible current route; switch only if the alternative upper bound
plus a configured margin is below the current lower bound. Exact equal point
costs use R. Route choice must never declare a copy readable before it commits.

Tier P eligibility does not mandate a positive L. At zero failure probability,
the depth score reduces to A. A positive-cost expansion loses to zero-cost keep;
a zero-cost tie need not trigger demotion. Any negative A needs a supported
foreground-benefit profile, not an assumed free replication. Source risk,
resource pressure and interval crossings must be checked separately.

Use up to the available 512 previous decode observations. At zero observations,
mandatory blocks rank first, then recency and stable ID. If mandatory sealed
sink/window blocks exceed the configured quota, request an explicitly charged
larger quota or decline that layer's Peer grant. Never silently truncate native
requirements. The first-L-layer family is a restricted policy class; per-layer
heterogeneity can make non-prefix allocations better.

All co-located requests are hit by one sampled source event with the same failure
offset and shared target/link state. Do not independently sample their failures.
For two equal critical branches with 10-second penalties each, one protection
changes the sum of local penalties from 20 to 10 seconds but the join is still
10 seconds late. This invalidates interpreting that sum as workflow loss.
Finite small-DAG validation should enumerate feasible placements, use the same
failure events/arrivals/resource scheduler, recompute DAG completion times, and
report policy-versus-oracle regret with a declared aggregate (e.g. sum of WCT).
The oracle is only over its stated finite candidate set and constraints.

`check_policy_boundary_cases.py` additionally constructs a third, independent
6-second-delayed workflow. With capacity for one equal-size protection, the
Slack/ID policy picks A and leaves total WCT delay at 16 seconds; the enumerated
oracle protects C and yields 10 seconds. The resulting 6-second regret is a
CPU arithmetic counterexample with no resource contention, not workload evidence
or an estimate of practical regret. Contended event simulation remains required.

    python3 benchmark/AegisKV/experiments/scripts/paper/check_policy_boundary_cases.py --output output/pdf/aegiskv-external-review-revision-20260919/POLICY_BOUNDARY_CHECKS.json

## Figure 5 calibration boundary

The retained replay JSON records A100 80GB PCIe, batch one, MiniCPM4-8B
revision bb2ae14cf59d4ca769c4e42ece54cc3b82a58ef7, BF16, 32K resident history,
64 known random token IDs, a deep-copied InfLLMv2Cache, one shape warm-up and
five repeats. The 91.830096 ms median forward divided by 32 gives C=2.869691 ms.
This homogeneous layer average includes the timed whole forward; it is not a
per-layer measurement or a correctness comparison against token-wise decode.
The 6.25 GB/s input is a 25 GB/s pool link shared equally by four recoveries.

One layer has 32768 tokens * 2 KV heads * 128 dimensions * 2 (K,V) * 2 bytes
=32 MiB. The mean preload fraction h=0.658447265625 over seven layers yields
147.4921875 MiB of KV payload. It excludes selector state, allocator rounding,
metadata and transient copies; mean fractions do not specify integer K per layer.
The modeled effective fraction is 0.7748209635416666. Both sparse timelines
retain 38.685464 ms of cold copying after tail reconstruction. Report tail-ready
latency separately from total transfer completion and subsequent TPOT.

Source JSON, trace table and Figure 5 generator hashes remain in
`paper/figures/design-single/MANIFEST.json`; data and figure geometry are unchanged.

## Execution and object interfaces

| Object | Owner | Lifetime and invalidation |
|---|---|---|
| Agent execution segment | Workflow Tracker | Sequential work between dependency barriers; mapping/DAG expansion invalidates prior slack |
| LLM request | Recovery Manager and native engine | Arrival through response/tool handoff; logical prefix remains addressable by the orchestrator after request references drop |
| Checkpoint manifest | Surviving recovery metadata | Retained until replaced by a complete successor or its protection claim is explicitly withdrawn |
| Per-layer Peer set H | KV Master request owner(s) | Committed memberships; owner replacement/end or Adapter demotion changes K and actual coverage |
| Physical replica | Connector/allocator | Charged through pending, committed and retiring states; free only after safe directory transition and I/O lease drain |

The orchestrator declares the remaining dependency structure complete only
when fork/join successors are expanded and live-request mappings are known.
A new branch or unresolved mapping invalidates the declaration. Missing structure
or duration profiles returns workflow-wide zero slack. This fallback can be
frequent; its frequency is an evaluation metric, not hidden predictor success.
Use workflow/time-separated data, and retain seconds error, false-safe slack,
critical-path ranking and decision regret. Heddle correlation is attributed
trajectory evidence, not a GBDT wall-clock calibration.

Recovery queue states are WAIT_SPACE -> WAIT_DATA -> READY -> RUNNING. State
transitions acquire physical reservations before I/O leases. Kernels enter only
with their required inputs, activations and transfer-progress workspace reserved.
A backend-supported pause after a kernel boundary may return to WAIT_DATA while
retaining charged activations. The batch coordinator sends identical batch,
layer and collective order to all TP ranks. Requests at different layers are
not arbitrarily interleaved by independent local rank schedulers. If a batch
cannot split at a miss, the whole batch waits; the profile includes that penalty.
No directory/queue lock may be held while waiting for DMA or a collective.
The positive demand/writeback shares require reserved progress buffers, not
merely priority labels in a saturated allocation pool. These interfaces require
backend integration and deadlock/batch-interference tests before performance
or fairness claims.
