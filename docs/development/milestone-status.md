# Milestone status

Status is evidence-based. A task is complete only when its acceptance evidence
is linked here; a passing static gate is not calibration or experiment evidence.

Current delivery scope is CPU metadata-only GlobalDES with one monotonic virtual
clock. Its evidence ceiling is E2. E3 physical calibration, E4 real-system
matching, and E5/paper claims are deliberately outside the current Definition
of Done; their unresolved blockers are retained as claim boundaries rather than
being silently marked solved.

## M0 - project freeze and initialization

Status: baseline E2 accepted at `v0.1.0-mooncake-baseline`

Completed or under direct verification:

- Git repository initialized on `main`; the accepted baseline tag resolves to
  commit `f2684c2b692c381f9e7db24ef808deb7551d62fc` and tree
  `f2613f45c15421f49f526ed86c77fc3b5ad63b73`.
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

Retained higher-evidence limitations:

- `SRC-BLOCK-001`: no target vLLM 1.2.2/L40S forward profile and held-out
  residual pass;
- `SRC-BLOCK-002`: no canonical Qwen3-8B native/YaRN physical-functional PASS;
- `SRC-BLOCK-003`: the reviewed Weka sources do not disclose exact capture start
  and end. The protocol amendment permits only E0--E2/preliminary use and does
  not permit formal/paper E4/E5 claims;
- `SRC-BLOCK-001..003` prohibit calibrated/formal/paper claims but do not prohibit
  the explicitly modeled E2 runs in the current scope.

The final source-frozen no-failure, fixed-`GPU_FAILURE`, and near-128K scenarios
were each run twice. All three strict comparisons decoded and validated 19/19
artifacts and were byte-identical. Aggregate hashes and frozen bundle paths are
recorded in `benchmark/AegisKV/experiments/baseline-tag-evidence.json`.

## M1 - common DES kernel

Status: E2 accepted for the tagged baseline

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

Remaining non-blocking or final-acceptance work:

- broader randomized/property coverage and minimal-replay-prefix diagnostics.
  Physical validation is not part of the current scope.

## M2 - vLLM engine baseline

Status: E2 accepted for the tagged baseline; pinned CPU metadata differential present

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
- A separate GPU-invisible pinned-vLLM `FullAttentionSpec` capture now binds the
  hash-locked Qwen3-8B TP1/PP1 BF16 block-16 shape. It observes 65,536 bytes per
  layer page and 2,359,296 bytes across 36 layers, and matches both native and
  proposed-YaRN MoonKVSim layouts exactly. CUDA remains uninitialized before and
  after the metadata operation; no weights, tokenizer, forward, runtime capacity,
  timing, or physical 128K claim is involved.

Open higher-evidence or broader-mode gaps are CUDA allocation/runtime capacity,
tokenizer-equivalent physical 128K validation, and hybrid/broader scheduler
modes. The source-frozen real-trace repeat is complete.

## M3 - AIConfigurator

Status: E2 modeled candidate. The phase/shape
adapter, pinned source/database support audit, real vLLM-0.14.0 SDK golden, and
fail-closed formal profile/calibration loader pass static and unit gates. The
target vLLM 1.2.2/L40S has no supported AIConfigurator database, so current
forward durations remain source-bound/assumed, `modeled/preliminary`, and
`not_calibrated`. No physical target table, held-out residual, Slurm job, or E3
claim is part of the current execution plan; `SRC-BLOCK-001` remains preserved.

## M4 - Vanilla Mooncake Store

Status: E2 candidate with bounded external metadata differential. The logical object/replica
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
folded into GPU forward. Their latencies remain assumed.

A pinned Mooncake `f161118` CPU metadata oracle now directly compares allocator
placement/extents, FIFO/LRU order, Master publication visibility, and TE slice
status/byte accounting with MoonKVSim. Eight comparable cases pass exactly or
through an explicit normalized projection. Three differences remain declared:
Master RPC error codes, upstream all-matching `PutEnd`, and BatchID capacity/free
lifecycle. The oracle initializes no TransferEngine, network, RPC, GPU, CUDA, or
payload copy and records no timing. It is a bounded E2 subset, not full parity.

## M5 - baseline GPU failure and end-to-end validation

Status: E2 accepted at the baseline tag. The normalized trace runner uses
one Store/HBM allocation registry, exact PhysicalGPU-to-ledger failure domains,
and HBM bridge observers wired through an atomic fail-stop handler. Directed
compute-failure and active prefix-Get-failure runs deterministically cancel,
fence, reroute, load a committed Store prefix, recompute the missing suffix,
suppress duplicate output, and replay both ledgers and the allocation registry
byte-identically. This is not timing calibration or physical validation.

Committed output-position recovery is now externally fenced: modeled internal
forwards replay committed positions silently, and activation occurs only after
`READY_TO_ACTIVATE`. Diagnostic runs at `main@2f4ffb8` now have byte-identical
no-failure, near-128K, and corrected single-active-route failure pairs. They are
not final acceptance because the Section-16 projection subsequently changed.

Section 16 now receives pristine initial ledgers, emits complete timestamp-zero
snapshots for untouched resources/accounts, and makes capacity completeness a
strict comparator gate. Multi-request workflow TPOT is explicitly not
applicable across independent output streams, while TTFT and WCT remain complete.
The comparator decodes Parquet content and requires every request/workflow timing
row and capacity snapshot row to be complete; JSON summaries alone cannot assert
completeness. The final six bundles were rerun on the clean tagged commit and
passed strict comparison. Token-content equivalence and physical/matched
validation remain higher-evidence limitations outside the E2-only DoD.

## M6-M9

Status: initial E2 simulation release completed on `aegiskv`; broader plan
closure and paper-ready evidence remain open.

Current repository gate: `757 passed, 1 skipped`; Ruff PASS; strict mypy PASS
for 94 source files. These are implementation and artifact-integrity gates, not
calibration or physical-performance evidence.

- M6: the tag-derived branch, immutable patent, provenance manifest, contract,
  27-clause runtime evidence, and automated audits are present. Manual patent
  review remains pending.
- M7: source-owned Peer-HBM and Store-DRAM paths independently reserve,
  transfer, commit, abort, and expose `HBM_ONLY`, `DRAM_ONLY`,
  `HBM_AND_DRAM`, and `BYPASS` outcomes. Transfer byte conservation and
  per-cause resource accounting are strict gates.
- M8: one `GPU_FAILURE` causes immediate fail-stop fencing, route-version
  invalidation, reroute, committed-prefix restore, prompt-suffix recompute,
  silent replay, and atomic activation on the one global virtual clock.
- M9 initial release: 46 variants over five observed context buckets, two
  scenarios, three seeds, and two fresh determinism repetitions produced 2,760
  rows and 1,380 exact A/B pairs. Multi-seed statistics use repeat A only and
  report conservative two-sided 95% Student-t intervals. Fourteen preliminary
  SVGs (F1--F11 and F13--F15) pass provenance audit; F12 is explicitly excluded
  because physical calibration is outside the requested simulation-only scope.
- M9 fluid-core follow-up: seven core systems over the same five buckets and
  two scenarios, two seeds, and exact A/B repetitions produced 280 rows and
  140 pairs. Transfers now use sliced work-conserving weighted max-min fluid
  contention; every GPU exposes a closed event-boundary HBM account stack.
  Three focused SVGs expose HBM occupancy, fluid resource utilization, and
  recovery reserve/staging without upgrading the E2 evidence class.
- M9 transport follow-up: GDR, RDMA Host-staged, and TCP Host-staged paths now
  have a separate five-bucket, two-scenario, two-seed matrix with 120 rows and
  60 exact A/B pairs. Host staging/source-pin lifecycles are ledger-audited and
  F17 exposes WCT, network byte-time, and Host staging without a physical claim.
- M9 Store-node follow-up: one, two, and four physical Store segments now have
  independent DRAM ledgers and modeled fabric resources under a fixed 64-GiB
  total capacity budget. The five-bucket, two-scenario, two-seed matrix has 120
  rows and 60 exact A/B pairs. F18 exposes WCT delta, modeled network byte-time,
  and 128K recovery composition without claiming a physical scale-out result.

The canonical matrix is
`benchmark/AegisKV/experiments/e2-initial-v1/`; the figure set is
`benchmark/AegisKV/experiments/figures/e2-initial-v1/`; and the bounded initial
interpretation is in `benchmark/AegisKV/experiments/INITIAL_REPORT.md`.

The fluid-core matrix is
`benchmark/AegisKV/experiments/e2-fluid-core-v2/`; its focused figures are in
`benchmark/AegisKV/experiments/figures/e2-fluid-core-v2/`; and its bounded
interpretation is in `benchmark/AegisKV/experiments/FLUID_CORE_V2_REPORT.md`.

The Store-transport matrix is
`benchmark/AegisKV/experiments/e2-transport-v1/`; F17 is in
`benchmark/AegisKV/experiments/figures/e2-transport-v1/`; and its bounded
interpretation is in `benchmark/AegisKV/experiments/TRANSPORT_V1_REPORT.md`.

The multi-Store-node matrix is
`benchmark/AegisKV/experiments/e2-store-nodes-v1/`; F18 is in
`benchmark/AegisKV/experiments/figures/e2-store-nodes-v1/`; and its bounded
interpretation is in
`benchmark/AegisKV/experiments/STORE_NODE_V1_REPORT.md`.

This initial release is not paper-ready. The current experiment harness still
does not model TP/PP sensitivity and does not establish physical timing
accuracy. The branch-local harness now supports explicit GDR and Host-staged
Store paths with Host DRAM staging/source-pin transactions, plus sharded
multi-node Store placement and ledgers. The focused transport and Store-node
matrices are complete; TP/PP sensitivity remains open.
