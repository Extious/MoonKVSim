# AegisKV simulation audit — 2026-09-01

This audit records the implementation defects behind the earlier unexpected
figures, the repairs that are already active, and the gates that still prevent
a paper-ready run. Desired trends are not acceptance criteria: only observed,
aligned simulator output may be plotted.

## Current status

| Area | Earlier problem | Current disposition |
|---|---|---|
| Workload length | The model limit was confused with observed 128K coverage. | The frozen 160-workflow FanOutQA trace is unmodified, but has median prompt 16,437 tokens, P95 55,272, maximum 86,198, and `128k: 0`. Artifacts must publish `observed_128k_coverage=false`; no padding or concatenation is allowed. |
| Algorithm 1 | Predictor and ideal-trace modes were ambiguous. | `ideal_trace_cpm.py` uses each span's known `recorded_api_time_ns` and an exact DAG CPM forward/backward pass. No predictor is trained or invoked. |
| Algorithm 2 | A compact pool value approximation did not implement the formal suffix lifecycle and exact joint loss. | The full AegisKV variant now has independent Peer-HBM and Store-DRAM `SlackLandlord` instances, safe suffixes, same-request exclusion, exact `A`/`D`, strict gates, and `PENDING`/commit/abort journals. |
| Source ownership | Peer-HBM and Store-DRAM could be misread as a target-owned writeback hierarchy. | Both are source-owned, independently admitted protection paths. Each has its own destination reserve and `PENDING -> COMMITTED/ABORTED` lifecycle; failure or bypass on one path does not terminate the other, and there is no Peer-to-Store destage dependency. |
| Policy granularity | A performance shortcut merged the configured 1,024-token policy chunks into roughly four large admission candidates. Rejecting the second large candidate blocked the remaining suffix and could leave only the shared 64-token prefix, materially understating Peer/Store reuse. | Repaired. Every non-global candidate is previewed/applied independently and is at most the configured 1,024 tokens; the global system-template unit may remain the separate 64-token source block. Only after independent admission may the transfer service combine at most eight adjacent `PENDING` policy chunks into one physical task. Commit remains in policy order and abort rolls back the pending suffix in reverse order. |
| Content reuse | Protection writes and route lookups used different physical keys; shared prompt content could be merged into a private batch. | Protection is content addressed, logical aliases retain independent frontiers, alias-dependent requests participate in exact `D`, and the global 64-token source block remains a separate protection unit. |
| Formal Store lookup | Formal Store writes used content-addressed protection keys while one lookup path still queried original request-chunk keys, producing false zero Store reuse. | Repaired. Formal normal-route and recovery lookup use Store protection chunks, while Mooncake's ordinary Store path retains its original request-key semantics. Tests cover a committed private Store prefix. Four-segment Store scheduling also preserves global candidate order and coalesces only adjacent candidates targeting the same segment, preventing segment-name ordering from corrupting the prefix frontier. |
| Mooncake HBM reuse | One figure treated HBM as AegisKV Peer protection only and therefore drew zero Mooncake HBM reuse. | Failure reuse statistics distinguish opportunistic `normal_hbm_local` from AegisKV `peer_hbm`; both are reported. The first 64-token source block is shared by all 1,304 requests, so zero Mooncake normal-HBM focus reuse is inconsistent with the frozen input semantics and fails closed as an integrity error, not as an effect-direction gate. |
| Algorithm 3 | Pressure was latched but multiplicative decrease waited until a later control window. | Foreground pressure immediately performs MD and resets stability; only AI waits for `K` stable fixed windows. Quota contraction invokes formal safe-tail eviction and leaves Store DRAM independent. |
| CDF interpretation | A single whole-workload CDF visually implied that AegisKV improves unaffected requests. | Whole-workload and failure-affected WCT ECDFs are separate. The per-seed non-focus absolute mean difference and its `<=1%` expectation are reported as diagnostics, not artifact-generation gates. |
| Scale statistics | One deterministic seed and simple lines had no uncertainty or alignment proof. | The living request config and sweep runner use seeds 0–4. Statistics require exact paired system/workflow/focus alignment, seed-level Student-t 95% CIs, absolute WCT, affected/focus gains, alpha range/mean, pressure rate, affected count, and tier-selected KV. No smoothing or monotonic fitting is permitted, and negative, zero, or CI-crossing-zero results remain publishable simulator observations. |
| Failure-plan pairing | Logical targets could be selected independently per variant or reused across incompatible concurrency states. | The runner derives one canonical plan per seed and concurrency. Its causal oracle executes both frozen system profiles and accepts only a focus that remains unaffected and temporally feasible in both. C=16 derives one causal-recursive F8 plan and freezes nested F1/F2/F4/F8 subsets; C=8/24/32 derive direct causal-recursive F2 plans. Measured cells receive identical logical focus IDs without re-selecting them, then resolve their own natural GPU and virtual timing. |
| Compute scheduler and HBM authority | Workflow concurrency changed admission/queue depth, but each GPU still used one non-preemptive request lane and scheduler pages had no unique physical owner. | The exact-token path now runs scheduler-step continuous batching with one `CapacityLedger`-backed physical HBM authority. Scheduler block pools remain logical 16-token pages; the authority maps them atomically onto rounded 64-token source allocations, audits resident logical bytes against physical `ACTIVE` ownership after every step, and derives pressure from resident/ledger state. The source-hash fallback remains the legacy non-preemptive lane and must keep `continuous_batch_residency_modeled=false`. |
| Failure/recovery ownership | Failure handling could release the same HBM through both scheduler and experiment paths or restart every request from token zero. | Repaired for the exact-token path. The scheduler fence runs before physical mutation; the experiment applies the one-time `UNAVAILABLE` transition. Recovery may adopt only a verified block-aligned external prefix, recomputes the remaining prompt suffix, silently replays already committed output positions, and emits each external output once. Lost HBM is never reused and a repeated failure release is rejected. |
| Qwen3-32B | Qwen3-8B timing could have been reused as if it were a 32B result. | The DP=8, TP=4 execution/recovery path models four rank shards, barriers, directory install, and model collectives separately. Its strict runner returns `BLOCKED` without an exact Qwen3-32B scheduler-duration artifact. |
| Predicted figures | Projected images could be confused with simulator output. | Projected generators and generated projected artifacts were removed. Figure code accepts only aligned simulator aggregates and exports separate PNG/SVG/PDF files. |

These repairs close implementation-level capability gaps; they do not create a
paper result. The exact-token scheduler/authority path uses ideal-trace request
durations with an uncalibrated token-share/batch-composition model. It is not a
physical A100/CUDA/NCCL/PCIe/RDMA execution. The frozen FanOutQA workload still
has no observed 128K request. The formal default has seven paired dimensions;
five seeds and two variants therefore require 70 variant-seed runs, producing
35 paired raw-seed cells, seven aggregate cells, and 20 per-seed/per-concurrency
canonical-plan checkpoints. No artifact matching these repairs and the current
schemas has been generated. All older diagnostic outputs and attributions are
stale relative to the repaired implementation and must not be used as current
measurements or figure inputs.

## Evidence and acceptance gates

The authoritative algorithm contract is
[`FULL_ALGORITHM_SIMULATION_CONTRACT.md`](FULL_ALGORITHM_SIMULATION_CONTRACT.md).
`formal_algorithm_audit.py` reconstructs the Algorithm 2/3 decisions and rejects
capability-label-only claims. The Qwen3-8B paper runner may write a passing
paper-sweep artifact only when the following structural, alignment, execution,
and provenance conditions hold:

1. every requested failure and repair event executes in each fresh workload;
2. exactly one canonical plan is bound to each seed and concurrency: C=16 uses
   a causal-recursive F8 plan with frozen nested F1/F2/F4/F8 subsets, while
   C=8/24/32 use direct causal-recursive F2 plans;
3. both variants use the same canonical logical focus spans without oracle
   re-execution and retain their natural physical routes and timings;
4. five or more unique paired seeds use the same 160 workflows;
5. exact SlackLandlord and AIMD event reconstruction passes;
6. continuous scheduler-step residency and the unique physical HBM ledger are
   enabled and byte-identical;
7. the enclosing sweep uses `moonkvsim.aegiskv.paper_sweeps.v4`, run checkpoints
   use `moonkvsim.aegiskv.paper_sweeps.run-checkpoint.v4`, canonical-plan checkpoints
   use `moonkvsim.aegiskv.paper_sweeps.canonical-plan-checkpoint.v3`, and every
   aggregate uses `moonkvsim.aegiskv.paper_sweep_statistics.v3`;
8. figures use raw/aggregate observations only and retain modeled,
   uncalibrated provenance.

The non-focus `<=1%` expectation and the base F=2/C=16 failure-focus P95 sign and
two-sided 95% confidence interval are result diagnostics. They are recorded under
unmet result expectations but never block artifact generation, including for
negative, zero, or confidence-interval-crossing-zero effect estimates. Positive
point estimate plus a positive confidence-interval lower bound is required only
for the interpretive claim `clear advantage`.

Passing this simulator gate remains E2 modeled evidence. It is not A100
CUDA/NCCL/PCIe/RDMA validation and must not be described as a physical result.
At this audit revision the repaired exact-token implementation has targeted
end-to-end and invariant coverage, and the strict aggregate implementation exists.
However, no completed current-schema 70-variant-seed-run artifact has been
generated and audited; therefore there is no refreshed formal or paper-ready
result to publish.
