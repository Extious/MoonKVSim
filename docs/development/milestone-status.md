# Milestone status

Status is evidence-based. A task is complete only when its acceptance evidence
is linked here; a passing static gate is not calibration or experiment evidence.

## M0 - project freeze and initialization

Status: implementation present (E0/E1); acceptance in progress

Completed or under direct verification:

- Git repository initialized on `main`; no baseline commit/tag has been accepted.
- README, design boundary, package metadata, CI, lint and test skeleton exist.
- Immutable patent input is present and its required SHA-256/OOXML integrity are
  covered by passing automated checksum, OOXML, and patent-contract audits. No
  human review claim is inferred from those checks.
- Local vLLM, Mooncake, SGLSim, AIConfigurator, and Weka trace sources were
  discovered; dirty source trees are treated as non-authoritative working copies.
- Strict schemas, deterministic Weka normalization, tokenizer/chat-template
  fingerprinting, and the corrected
  `context_before_step + output <= 131072` coverage audit pass their static gates.
- The source-lock structure/content audit is valid, but strict readiness fails
  closed on `SRC-BLOCK-001`, `SRC-BLOCK-002`, and `SRC-BLOCK-003`.

Open gates:

- `SRC-BLOCK-001`: no target vLLM 1.2.2/L40S forward profile and held-out
  residual pass;
- `SRC-BLOCK-002`: no canonical Qwen3-8B native/YaRN physical-functional PASS;
- `SRC-BLOCK-003`: the reviewed Weka sources do not disclose exact capture start
  and end. The protocol amendment permits only E0--E2/preliminary use and does
  not permit formal/paper E4/E5 claims;
- an accepted source-frozen baseline commit and repeated complete real-trace
  bundles do not yet exist.

## M1 - common DES kernel

Status: in progress (E1 plus directed E2-toy semantics)

Implemented and covered by tests:

- monotonic nanosecond clock and stable `(timestamp, priority, sequence)` heap;
- conservative same-time failure/fence priority and event cancellation;
- capacity, rate, and concurrency resource primitives;
- closed byte ledgers and atomic multi-ledger transactions;
- physical-allocation/logical-role separation;
- canonical journal and deterministic capacity-transaction replay;
- deterministic interval calendars and weighted max-min path contention;
- failure cancellation releases a pending destination and copy reservation;
- capacity ledgers, allocation registry, transfer-resource calendars, and
  flow-rate state have byte-identical replay gates, including negative tamper
  tests.

Open gates:

- broader randomized/property coverage and minimal-replay-prefix diagnostics;
- source-frozen whole-workflow replay and external/physical validation.

## M2 - vLLM engine baseline

Status: in progress (E1 plus pinned E2 CPU differential/toy semantics)

- The tensor-free request state ordering and finish-reason mapping mirror the
  pinned `vllm/v1/request.py` source, and the 131072 guard rejects
  `prompt + output reserve` overflow without truncation.
- The hash-bound CPU golden covers three directed scheduler/block traces plus a
  tensor-free Store-connector lifecycle. It exercises continuous/chunked
  prefill, decode, preemption/recompute, block release/reuse, opt-in local prefix
  caching, collision guards, refcounts, inactive/LRU reuse, and full-prompt
  final-block recompute.
- CacheSpec-derived native and proposed-YaRN layouts, explicit per-GPU HBM
  ledgers, continuous batching, causal replay, and independent DP routing have
  directed E1/E2-toy coverage.

Open gates are target Qwen-shaped live CacheSpec/CUDA allocation and runtime
capacity, tokenizer-equivalent 128K validation, hybrid/broader scheduler modes,
and an accepted source-frozen real-trace run.

## M3 - AIConfigurator

Status: in progress (E1 plus E2 reference semantics only). The phase/shape
adapter, pinned source/database support audit, real vLLM-0.14.0 SDK golden, and
fail-closed formal profile/calibration loader pass static and unit gates. The
  target vLLM 1.2.2/L40S has no supported AIConfigurator database; no accepted
  physical target forward table or held-out residual pass exists. A queued,
  dependency-gated Slurm plan is not E3, and `SRC-BLOCK-001` remains unresolved.

## M4 - Vanilla Mooncake Store

Status: in progress (E1 plus E2-toy semantics). The logical object/replica
directory enforces all-shard commit, atomic publication visibility, continuous
prefix lookup, cross-route content identity, and unique physical allocations.
The DRAM allocator is now coupled to a deterministic LRU capacity-pressure
pass: only published committed, zero-source-pin replicas are eligible; pending
replicas and live GET aliases are protected; victim release and new pending
reserve share one atomic transaction; rollback and journal replay are tested.
This is explicitly a DES replacement for pinned Mooncake's asynchronous,
lease/watermark-aware eviction thread, not an external parity result. Exact
allocator extents and upstream capacity-pressure/concurrency differentials
remain open. Configured source/destination endpoint, node, NUMA, and HCA
bindings now drive deterministic preferred/available/retry/disabled path
selection. Endpoint cold registration and warm lookup consume a separate
registration-worker lane through independent GlobalDES events and are never
folded into GPU forward. Their latencies are assumed: device/page discovery,
physical registration/connect/QP behavior, calibrated paths, external
differentials, and physical validation remain open.

## M5 - baseline GPU failure and end-to-end validation

Status: in progress (E2 semantics only). The normalized trace runner now uses
one Store/HBM allocation registry, exact PhysicalGPU-to-ledger failure domains,
and HBM bridge observers wired through an atomic fail-stop handler. Directed
compute-failure and active prefix-Get-failure runs deterministically cancel,
fence, reroute, load a committed Store prefix, recompute the missing suffix,
suppress duplicate output, and replay both ledgers and the allocation registry
byte-identically. This is not timing calibration or physical validation.

Committed output-position recovery is now externally fenced: modeled internal
forwards replay committed positions silently, and activation occurs only after
`READY_TO_ACTIVATE`. One clean source-frozen full-selected-workflow e094
no-failure diagnostic PASS exists; it is selector discovery only and is not an
accepted repeat. A deterministic fixed failure config has been materialized
from that diagnostic. Open gates are two accepted complete no-failure runs, two
accepted failure runs, two accepted near-128K trace-shape runs, token-content
equivalence, physical/matched validation, and baseline acceptance.

## M6-M9

Status: pre-branch M6 design-input preparation is partially complete through the
immutable patent, provenance manifest, contract, and automated audit. No
baseline tag, AegisKV branch/runtime, matched AegisKV experiment, or paper-ready
result exists yet; runtime work remains forbidden before baseline acceptance.
