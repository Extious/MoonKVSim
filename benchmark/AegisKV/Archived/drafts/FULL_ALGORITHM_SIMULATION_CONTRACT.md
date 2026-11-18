# Full Algorithm 2/3 simulation contract

This contract defines the evidence required before MoonKVSim results may be described as
the complete AegisKV Algorithm 2/3 simulation requested for Qwen3-8B and Qwen3-32B.  It is
derived from `/home/comp/zhanzhao/Mooncake/aegiskv/design/current_design.md`; passing plots
or desirable trends do not override these gates.

Frozen design SHA-256: `0fdfd097a536ab73cd9f7eb12099eb6f5b9c068a061da30af57a8e6798caacac`.

## 1. Algorithm 2: SlackLandlord

Every experiment run claiming Algorithm 2 MUST prove all of the following:

1. Peer HBM and Store DRAM use independent `SlackLandlord` instances, rents, capacity
   snapshots, pending states, and commit/abort callbacks.  Peer state is scoped to one
   Router-designated target, not a deployment-wide aggregate.
2. One pool exposes at most one safe contiguous suffix tail per logical request.  The
   candidate request is excluded from its own victim set.  A newly exposed predecessor
   and a stale heap head are refreshed without reissuing the hidden chunk's old credit.
3. Candidate gain is the tier-local fail-now recovery-harm reduction
   `A=[J_before-J_after]^+`, where `J=[T-s(t)]^+`.  `T` includes tier load, missing suffix
   recomputation, silent replay, and any required TP collective synchronization.  Hit/LRU
   utility from an older composite formulation cannot affect the current-design result.
4. `Loss(Y,t)` is recomputed from complete before/after recovery states, grouped once per
   affected request.  Admission requires both strict `H_y < Theta` for every victim and
   strict `A > D_Y`; summing stale per-chunk credits is not an accepted implementation.
5. Eviction, destination allocation, `PENDING`, transfer, and `COMMITTED`/`ABORTED` are
   separately journaled.  Evicted victims do not roll back after copy failure.  A pending
   chunk is never recovery eligible.
6. Content aliases may share one physical allocation, but each logical request retains an
   independent frontier/key binding.  An alias hit cannot be reported as a policy bypass
   or used to collapse two requests' suffix order.
7. AIMD contraction, request completion, failure fencing, and recovery activation remove
   policy entries only through audited suffix-safe lifecycle operations; physical and
   policy occupancy must remain byte-identical after every event.
8. Candidate admission and suffix-frontier state use the configured policy-chunk
   granularity (1,024 tokens for the living Qwen3-8B engine, except a shorter source-scope
   boundary such as the 64-token global template).  Adjacent admitted chunks may share one
   transport service operation, but batching MUST NOT merge their `A`, `D_Y`, `H_y`, or
   suffix decisions into one oversized policy candidate.

The run artifact MUST set `formal_suffix_frontier_modeled=true`,
`formal_joint_gain_loss_gate_modeled=true`, and identify the exact design and policy source
hashes.  A compatibility wrapper around `_ModeledPool.reserve()` is insufficient.

## 2. Algorithm 3: HBMQuotaAIMD

Every experiment run claiming Algorithm 3 MUST prove:

1. One state `(alpha_p,z_p)` per Router-designated Peer-HBM target and one update per fixed
   GlobalDES control window, with strict monotonically increasing target-local timestamps.
2. Pressure is latched before protection reclaim from primary allocation shortfall,
   reservation failure, or reclaim stall.  It is derived from scheduler-step resident
   requests and physical HBM accounts; queued workflow count alone is not pressure.
3. Pressure performs an immediate multiplicative decrease and resets `z_p`.  Only `K`
   consecutive stable windows perform one additive increase.  Every decision records the
   prior/next state, reason, resident-primary bytes, free/reclaimable bytes, and quota.
4. Publishing a smaller quota immediately blocks new Peer-HBM admissions and invokes the
   formal Algorithm 2 tail index until committed plus pending protection bytes fit.  Store
   DRAM is unaffected.  Physical HBM conservation is checked at every contraction.
5. A target failure fences its control state and capacity without turning failed HBM into
   free capacity.  Repair creates a versioned replacement state instead of silently
   reviving stale committed backups.

The run artifact MUST set `continuous_batch_residency_modeled=true` and bind the scheduler,
batch-duration provider, HBM-ledger, Algorithm 3, and policy source hashes.

## 3. Qwen3-8B experiment matrix

- Modeled layout: Qwen3-8B, BF16 KV, DP=8, TP=1, PP=1, 8 x A100-40GB.
- Workload: the frozen 160-workflow FanOutQA workload with no truncation or padding.
- Seven unique paired dimensions are required: failure counts 1, 2, 4, and 8 at
  concurrency 16, plus concurrency 8, 24, and 32 at failure count 2.  The shared
  `(failure_count=2, concurrency=16)` base is counted once.
- Exactly one canonical logical failure plan is derived for each `(seed, concurrency)`.
  Event zero comes from an F0 no-failure oracle; event `i` comes from a fresh partial-Fi
  oracle for each frozen system profile that executes every already-selected event.  The
  next focus must remain unaffected by prior failures and trigger strictly after them in
  both profiles.
- At concurrency 16, one causal-recursive F8 plan supplies frozen nested F1/F2/F4/F8
  subsets.  At concurrency 8, 24, and 32, a direct causal-recursive F2 plan is derived;
  focus identity is not required to match across different concurrency values.
- The same canonical logical focus IDs are projected into both measured variants without
  re-selection.  Each variant resolves its own natural physical GPU and virtual timing;
  no common physical GPU is pinned for comparison.
- Seeds are the independent sampling units.  With the default seeds 0--4 and two
  variants, the seven dimensions contain 70 variant-seed runs, materialized as 35 paired
  raw-seed cells and seven aggregate cells.  They also require 20 per-seed/per-concurrency
  canonical-plan checkpoints.  Repetition `A` is not an additional independent sample;
  one seed remains development evidence only.

## 4. Qwen3-32B experiment matrix

- Modeled layout: DP=8, TP=4, PP=1, eight nodes, four A100-80GB GPUs per node; one complete TP
  replica per node.  Intra-node TP communication uses an explicit NVLink/NVSwitch rate
  resource.  Cross-node protection never borrows that resource.
- Peer-HBM protection: each source TP rank copies its KV shard to the corresponding rank in
  one route-bound standby TP group.  The four shard records have one logical chunk commit:
  all rank transfers, model revision, KV ABI, layout, route version, and failure domains
  must agree before the chunk becomes recovery eligible.
- Peer recovery: each target rank adopts or loads only its own shard.  KV bytes are not
  mathematically all-reduced.  Recovery nevertheless models the required rank barrier and
  the model's subsequent TP collectives (including all-reduce where the model forward uses
  it) before atomic activation and output unfreezing.
- Store recovery: Store DRAM remains an independent source-owned path.  Each rank loads its
  own committed shard; activation waits for all four ranks and uses the same collective
  synchronization boundary.
- A single-rank source failure fences the whole affected TP replica's output and activates
  a complete compatible standby TP group.  Partial-shard success cannot recover a chunk.
- The base and scale figures match the Qwen3-8B suite, with topology and collective costs
  included in the artifact rather than added during plotting.
- The strict runner remains blocked without an exact Qwen3-32B scheduler-duration
  artifact.  Even an unblocked DES result remains modeled and is not physical GPU or
  collective execution evidence.

## 5. Output-validity, result-diagnostic, and figure requirements

The simulator MUST emit actual deterministic-event results; figure code may aggregate,
bootstrap, or format them but may not replace, smooth, project, or modify observations.
The enclosing sweep and variant-run checkpoint schemas are
`moonkvsim.aegiskv.paper_sweeps.v4` and
`moonkvsim.aegiskv.paper_sweeps.run-checkpoint.v4`.  Canonical-plan checkpoints use
`moonkvsim.aegiskv.paper_sweeps.canonical-plan-checkpoint.v3`, and every aggregate cell
uses `moonkvsim.aegiskv.paper_sweep_statistics.v3`.  Statistics `PASS` means that paired
inputs and calculations are valid; effect direction and significance never block
artifact generation.

1. Whole-workload WCT ECDF and a separate failure-affected WCT ECDF are both required.
   The per-seed non-focus absolute mean gap and its `<=1%` expectation are always reported
   as diagnostics; exceeding that expectation does not suppress the artifact.  The
   failure-local plot is the primary benefit view.
2. The base failure-focus P95 WCT gain and its two-sided multi-seed 95% confidence interval
   are always reported.  Negative, zero, or statistically inconclusive observations remain
   valid outputs.  The result may be called a clear advantage only when the point estimate
   is positive and the confidence-interval lower bound is greater than zero.
3. KV figures separately report committed availability and the source actually selected by
   recovery.  Overlapping Peer-HBM and Store prefixes are never summed.
4. The AIMD time series shows resident-primary pressure, alpha, action, and pressure events.
   A multiplicative decrease is claimed only when pressure is present in the event journal.
5. Failure/concurrency scale cells report absolute WCT, whole-workload gain, failure-local
   gain, alpha range/time-weighted mean, pressure rate, affected count, and tier-selected KV.
   Desired monotonic trends are conclusions to test, not plotting constraints.
6. Every paper figure is exported as PNG/SVG/PDF, contains no prediction/projection labels,
   uses readable publication-size text, and passes visual overlap inspection.

All timings and rates retain `modeled_uncalibrated` provenance until an A100 calibration
artifact supplies measured batch-shape, NVLink collective, Peer copy, and Store load data.
Calibration can parameterize the DES but does not turn it into physical execution.  Modeled
success is not physical validation; that requires separate real GPU/CUDA/NCCL/PCIe/RDMA
execution evidence.
