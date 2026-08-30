# MoonKVSim source map

This map is subordinate to `source-lock.json`. A file path is not a lock: Git
sources are read from the recorded commit object and checked against the
recorded blob and SHA-256. Dirty worktree snapshots are reference-only and are
identified by their exact SHA-256.

## vLLM engine semantics

| MoonKVSim responsibility | Pinned source and symbols | Preserved control flow | Deliberate simulation replacement | Verification |
|---|---|---|---|---|
| Request lifecycle | `vllm/v1/request.py`: `Request`, `RequestStatus` | Waiting/running/preempted/finished state and request-owned token/KV metadata | No model tensors or worker IPC | Hash-verified E2 CPU golden covers ordinary new/running/preempted/resumed/finished transitions in three directed traces; broader request modes remain open |
| Continuous scheduler | `vllm/v1/core/sched/scheduler.py`: `Scheduler.schedule` | Scheduling order, token budget, preemption/recompute, scheduler output, ordinary local prefix lookup/touch/refcount/free-queue reuse, and the full-prompt final-block recompute boundary; the default harness keeps `enable_prefix_caching=false`, while the opt-in cache remains independent per scheduler/DP | Work becomes DES events on one `now_ns`; `VLLMSchedulerBatchAdapter` validates one output against the corresponding post-schedule request counters and converts its actual scheduled-token shapes into canonical, phase-separated prediction batches | `generate_vllm_scheduler_golden.py` first verifies installed semantic-file hashes and the locked Qwen snapshot, then captures an E2 CPU golden. MoonKVSim exactly matches continuous/chunked prefill plus decode, KV-pressure recompute, and local prefix hit/share/inactive/LRU-reuse traces; hybrid-cache, priority-policy, async-scheduling, and broader scheduler paths remain open |
| KV allocation | `vllm/v1/core/kv_cache_manager.py`: `get_computed_blocks`, `allocate_slots`, `free` | Scheduler block admission, chunked-prefill/decode boundary allocation, reverse-order free, preemption/recompute generation, active alias refcounts, and inactive cacheable physical residency | `hbm_block_ledger.py` maps each ordinary physical block to unique per-PP-stage/TP-rank `PhysicalAllocation` records. The explicit `INACTIVE_REUSABLE_KV` account retains cacheable pages without a second capacity charge; active aliases change refs only, and LRU reuse evicts inactive residency before a new generation. This local HBM cache never becomes the shared Mooncake Store truth source | Directed E1/E2-toy ledger tests plus the pinned E2 CPU golden cover append, reverse release, reuse, preemption, recompute, cache hit/miss, collision guard, refcount sharing, inactive residency, and eviction; CUDA capacity and broader allocation modes remain open |
| Block pool/hash | `vllm/v1/core/block_pool.py`; `vllm/v1/core/kv_cache_utils.py`: ordinary SHA-256 block hasher, parent chain, cache map, free queue | Pinned `sha256(pickle(...))` bytes under an explicit `PYTHONHASHSEED`, full-block parent chaining, collision-witness guard, cache touch/refcount, reverse free, inactive free-queue residency, and LRU reuse | Stable simulator block IDs replace Python object identity; an explicit preimage witness fails closed on injected digest collision | Pinned CPU golden plus directed tests cover exact hashes, hit/miss, active sharing, inactive reuse, collision guard, refcount, free order, and eviction |
| Cache layout | `vllm/v1/kv_cache_interface.py`: `AttentionSpec`/`FullAttentionSpec` page-byte rules | Uniform full-attention group, block payload, padding, metadata, alignment fragmentation, and per-stage/rank max-context footprint | `kv_layout_artifact.py` generates separate native-40960 and proposed-unvalidated-131072 artifacts; `load_hbm_stage_rank_bindings` audits and binds every stage/rank entry to an explicit physical GPU resource; runtime GPU cache capacity remains null | In addition to E1 geometry audits and the toy spec, a hash-bound GPU-invisible E2 capture constructs the pinned Qwen3-8B TP1/PP1 BF16 block-16 `FullAttentionSpec`: 65,536 bytes/layer and 2,359,296 bytes/36 layers exactly match both layouts. CUDA remains uninitialized; runtime capacity, forward, timing, and physical 128K remain outside the claim |
| TP KV-head layout | `vllm/config/model.py`: `ModelConfig.get_num_kv_heads` | Preserve `max(1, total_num_kv_heads // tensor_parallel_size)`, including GQA/MQA KV-head replication when TP exceeds the KV-head count | Store total and resolved local per-rank KV heads in every stage/rank entry | E1 GQA/MQA replication tests pass; runtime differential remains open |
| PP layer placement | `vllm/distributed/utils.py`: `get_pp_indices`; `ModelConfig.get_layers_start_end_indices` | Preserve the default uneven partition and validate an explicit `VLLM_PP_LAYER_PARTITION`-equivalent override | Record every layer index/name and `DP_x_PP_x_TP` rank order in `kv-layout.json` | E1 default/explicit partition tests pass; runtime placement differential remains open |
| Connector lifecycle | `vllm/distributed/kv_transfer/kv_connector/v1/base.py`: `KVConnectorBase_V1`, `build_connector_meta`, bind/clear/get-finished contracts; Store scheduler/data/worker transitive modules are separately SHA-bound by the golden generator | Scheduler lookup→allocation→metadata, worker bind→issue/completion→clear, send-completion delayed free, and receive visibility at the next scheduler pass | `TensorFreeStoreConnectorScheduler`/`Worker` carry only immutable IDs, token/block metadata, and completions; they neither move tensors nor own a KV directory | Pinned E2 CPU differential covers full-hit tail recompute, miss, mutually exclusive load/save metadata, normal bind/clear, delayed send completion, and receive completion; CUDA events, Mooncake RPC/data movement, failures, multi-group HMA, and physical timing remain open |
| Direct Mooncake connector | `.../mooncake/mooncake_connector.py` | Direct connector lifecycle only | No baseline shared-Store semantics inferred from this file | Reference-only connector golden case |
| Shared Mooncake Store connector | `.../mooncake/store/connector.py` and its scheduler/data/worker modules | Shared block-hash Store lookup/save metadata lifecycle, without conflating the Store with each DP's local HBM prefix cache | The tensor-free adapter consults a caller-supplied single baseline Store lookup and emits lifecycle metadata/completions; Store state remains solely in the existing MoonKVSim KV directory | Pinned CPU differential covers scheduler/worker metadata and completion only. `test_baseline_composed_runtime.py` separately covers DP0 pending Put, atomic visibility, DP1 Get, and restored-prefix handoff at toy E2; external connector plus real Store/worker transfer differential remains open |

All rows above use vLLM commit `644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504`.
The ignored generated `vllm/_version.py` is observational metadata, not a
semantic source file.

## Vanilla Mooncake Store

All rows below use commit-object reads from vanilla commit
`f161118c18dbea1b56dd5c7908b9eaa440353e2e`. The current
`codex/aegiskv` worktree is never an input.

| MoonKVSim responsibility | Pinned source and symbols | Preserved control flow | Abstracted detail | Verification |
|---|---|---|---|---|
| Master directory and publication | `mooncake-store/include/master_service.h`, `src/master_service.cpp`: `MasterService`, `PutStart`, `PutEnd`, `GetReplicaList`, `Remove` | `PutStart` creates upstream `PROCESSING` replicas that are unreadable; `PutEnd` makes matching `ReplicaType` entries `COMPLETE`; only complete valid-endpoint descriptors are readable; `Remove` requires every replica complete | RPC/thread/lease errors become DES metadata operations. Pending `GetReplicaList`'s upstream `REPLICA_IS_NOT_READY` is represented as an empty visible set. MoonKVSim's explicit successful-replica subset plus atomic abort is a failure-accounting replacement for upstream `PutEnd`, not API parity | The CPU metadata oracle directly matches the normalized absent→pending-invisible→committed-visible→removed lifecycle. Exact RPC error codes and upstream all-matching `PutEnd` remain declared non-comparable gaps |
| Master client lifecycle | `include/master_client.h`, `src/master_client.cpp`: `MasterClient` and batch/single Put/Get/Remove calls | Request/response boundaries and error propagation | No real RPC serialization | Unit sequence tests and composed DP0/DP1 toy E2 smoke pass; external API differential trace remains open |
| Store client data path | `include/client_service.h`, `src/client_service.cpp`: `Client`, Put/Get/Remove paths | Master metadata before/after Transfer Engine byte movement; terminal data-plane tasks reconcile exactly once into PutEnd/GetEnd | Async work becomes stable transfer/task events | Store Client integration tests plus composed FlowDES lifecycle smoke pass |
| Placement and eviction | `include/allocation_strategy.h`: `AllocationStrategy`; `include/eviction_strategy.h`: `EvictionStrategy`; `src/master_service.cpp`: `AllocateAndInsertMetadata`, `EvictionThreadFunc`, `BatchEvict` | Preferred-first best effort, one segment per replica of a slice, source LRU/FIFO container order, FIFO random `RemoveKey` no-op, and the Master safety predicate of complete memory replicas with zero refcount | Seeded permutation replaces upstream process randomness; only DRAM-backed baseline paths exist and no Aegis hook is present. Pinned `PutStart` sets `need_mem_eviction_` and returns `NO_AVAILABLE_HANDLE`; a later asynchronous, lease-aware `BatchEvict` does not retry that call, and the standalone LRU/FIFO classes are not wired into this Master path. MoonKVSim deliberately replaces this with one journaled deterministic LRU pressure pass plus retry in the same DES event, atomically combining committed-victim release and pending reservation. Pending replicas and live GET source pins are ineligible | The external CPU metadata subset matches empty/preferred/best-effort allocation, exact OffsetAllocator reuse offsets, and directed FIFO/LRU sequences. Lease/watermark concurrency and the deliberate pressure-retry replacement remain outside exact parity |
| Segment/replica state | `include/segment.h`, `src/segment.cpp`: `SegmentManager`; `include/replica.h`: `Replica`, `ReplicaStatus` | Source status mapping `INITIALIZED/PROCESSING/COMPLETE` to allocated/pending/committed visibility and per-segment ownership | Cachelib/OffsetAllocator geometry becomes explicit simulator requested/allocated/fragmentation extents | Source enum/test bytes and official unit results are pinned; the CPU oracle now also matches exact in-memory allocator offsets and normalized publication state |
| Store transfer task | `include/transfer_task.h`, `src/transfer_task.cpp` | Task construction, completion/failure accounting, and same-process locality only for identical full endpoint strings | Threads become DES task/slice events; stable resource IDs replace virtual addresses | The CPU metadata oracle directly matches the 64-KiB slice size, three successful slices, and 131,073 transferred bytes without initializing a transport or copying payload |

## Mooncake Transfer Engine

| MoonKVSim responsibility | Pinned source and symbols | Preserved behavior | Deliberate replacement | Verification |
|---|---|---|---|---|
| Public TE lifecycle | `include/transfer_engine.h`, `src/transfer_engine.cpp`: `TransferEngine`, `allocateBatchID`, `submitTransfer`, `getTransferStatus`, `freeBatchID` | Pinned API fixes batch capacity at allocation, rejects over-capacity submit, and rejects free while a submitted task is unfinished | Stable simulator IDs replace pointer-valued opaque `BatchID`; no CUDA/RDMA execution. The current simulator does not claim exact allocate/free error parity | The external oracle records pinned overflow/busy/completed-free outcomes, while the comparison intentionally marks MoonKVSim BatchID capacity/free as a known gap; no false parity claim is made |
| Multi-transport dispatch | `include/multi_transport.h`, `src/multi_transport.cpp`: `MultiTransport` | Source groups tasks by selected target protocol; GPU-local HIP/MACA is intra-node only and the pinned multi-protocol preference precedes RDMA/TCP fallback | Each simulator path fixes one transport and its complete directional endpoint/resource binding; installed-protocol discovery is not executed | Commit-object dispatch anchors plus directed local/cross-node path rejection are covered; external protocol selection and submission trace remain open |
| Topology/locality | `include/topology.h`, `src/topology.cpp`: `Topology` | Exact source/destination endpoint, node, NUMA and directional HCA binding; preferred-only retry-zero selection with available fallback only when preferred is empty; positive retries enumerate preferred then available; disabled path/HCA rejection without ID renumbering | Stable `(priority, path_id)` order replaces upstream retry-zero random/thread-local round-robin HCA choice; sysfs/CUDA device discovery and physical distance are not inferred | Official topology API is hash-bound; directed tests cover wrong endpoint, cross-node local/NVLINK rejection, preferred/available fallback, retry, path/HCA disable, and invariants. No real path/device differential or physical parity is claimed |
| Memory location | `include/memory_location.h`, `src/memory_location.cpp` | CPU/GPU/NUMA identity participates in exact path choice | Configured stable endpoint/node/NUMA/resource IDs replace page observation and NUMA-region discovery | Official source is hash-bound; StoreClient/harness exact-binding tests pass. Real endpoint/page/NUMA differential remains open |
| Endpoint registration pool | `include/topology.h`, `src/topology.cpp`; endpoint-backed transports in `include/multi_transport.h`, `src/multi_transport.cpp` | One complete directional endpoint/HCA key has explicit cold/registering/warm/disabled state; concurrent cold waiters join one registration; failure teardown invalidates the generation | `endpoint.py` schedules registration start, completion, and ready as independent `GlobalDES` events on a named registration-worker lane. Cold and warm lookup latencies are assumed and never aggregated into GPU forward; real memory registration, connect/QP handshake, reconnect, and pool eviction are not executed | Directed tests cover cold-to-warm, joined waiters, cancel/retry generation, teardown/disable, worker release, and quiescent audit; journal rows project into section-16 KV-transfer events. Physical endpoint timing/parity remains open |
| Slice/task state | `include/transport/transport.h`: `Transport::Slice`, `TransferTask` | Pinned `WAITING/PENDING/...` task statuses, `PENDING/POSTED/SUCCESS/TIMEOUT/FAILED` slice statuses, and success-byte accounting | Fluid flow plus discrete device lanes; simulator adds explicit `CANCELED` slice state for failure audit | The external CPU metadata oracle and MoonKVSim match the selected success-count/default-slice/transferred-byte projection exactly; failure, timeout, and live transport paths remain outside the subset |
| Transfer resource lease | `TopologyPath` staging and concurrency resource IDs; baseline `CapacityLedger`, `ResourceTransaction`, and `ConcurrencyResource` contracts | Host-staged paths atomically charge an explicit temporary Host DRAM allocation and one lane on every named copy/QP resource before flow start; GDR charges no implicit staging; terminal completion/abort/GPU failure releases exactly once | `transfer_resources.py` uses an explicit uncalibrated duration to reserve a deterministic common interval and conservatively charges queued staging from acquisition; `baseline/runtime.py` accepts either one explicit plan or a post-construction task-bound provider (never both) and starts FlowDES at `lease.start_ns` on the same `GlobalDES`; the strict trace harness resolves actual PUT/GET endpoint bindings | Directed E2 TCP/GDR, composed DP Store Put/Get, real-shape harness queueing, atomic failure, failure-release, ledger/calendar replay, and canonical-byte tests pass; physical overlap calibration remains open |
| RDMA/TCP paths | `src/transport/rdma_transport/rdma_transport.cpp`; `src/transport/tcp_transport/tcp_transport.cpp` | GDR versus host-staging path distinction | Resource graph and lease calendar, not peak-bandwidth delay | Directed E2 resource semantics pass; planned C0-C4 communication validation remains open |
| Slice default | `include/config.h`: `TransferEngineConfig.slice_size`; `src/config.cpp` | Default `65536` bytes and positive `MC_SLICE_SIZE` override | Resolved manifest freezes the final value | Commit-object golden and mapped `[65536, 65536, 1]` case for 131073 bytes pass |

`scripts/generate_mooncake_source_api_golden.py --check` verifies 27 source and
official-test blobs plus both pinned gitlinks without reading the dirty
Mooncake worktree. The canonical artifact is
`reference/goldens/mooncake-f161118-store-te-source-api.json` (SHA-256
`2f118525d96b908abeb0c3feba2885fabeb90e87008aed00eb57af924cb806a1`). It is
explicitly E1 source/API evidence; its mapped simulator cases are E2-toy only.
The separate isolated official-unit record is
`reference/goldens/mooncake-f161118-official-test-validation.json` (SHA-256
`573373003657e9ccca0e1e80335c19de754e8d0b08a956259b6348384a322b17`): selected
official binaries pass, but its local dependency prefix is not hash-locked and
it contains neither a MoonKVSim differential nor physical data-plane evidence.

The bounded external metadata differential is
`reference/goldens/mooncake-f161118-metadata-differential.json`. Its live oracle
compiles against the pinned archives but initializes no TransferEngine,
network/RPC, GPU/CUDA, or payload copy and records no timing. Eight comparable
cases pass and three cases are explicit `KNOWN_GAP`; `PARTIAL_PASS` therefore
means a selected E2 semantic subset, never full Store/TE parity.

## SGLSim and AIConfigurator references

| Area | Hash-locked source | Allowed reuse | Forbidden inference | Status |
|---|---|---|---|---|
| Global DES method | SGLSim `python/sglsim/srt/simulation/global_des.py` worktree snapshot | Stable heap, cancellation, journal and invariant ideas | Its SGLang/HiCache/AegisKV tiers, accounts and scheduler behavior | Reference-only; untracked SHA is locked |
| Predictor interface | SGLSim `time_predictor/base.py` snapshot | Engine-neutral `extend_length`, `past_kv_length`, phase split | SGLang batch types or PP scaling as validated vLLM truth | Reference-only |
| Predictor adapter | SGLSim `time_predictor/aiconfigurator.py` commit object | Database/session API and shape-aware interpolation ideas | SGLang/HiCache profile scale | Reference-only |
| Predictor library | AIConfigurator `InferenceSession`, `get_database`, `get_backend`, `vllm_backend.py`; `reference/aiconfigurator-support.json` | Use the pinned library's vLLM backend only behind an explicit package/model/hardware/database support manifest | Treating source-level Qwen3/vLLM support, a vLLM 0.14.0 table, or any SGLang/TRT-LLM table as target vLLM 1.2.2 calibration | Source/DB hashes and real SDK calls are audited. Qwen3-8B vLLM 0.14.0 is supported on L40S/A100-SXM, but target vLLM 1.2.2/L40S is unsupported; A100-PCIe has no vLLM DB; no profile is selected and `SRC-BLOCK-001` remains open |
| Predictor E1/E2-toy boundary | `python/moonkvsim/predictor/`: neutral request/batch/profile, `VLLMSchedulerBatchAdapter`, explicit AIConfigurator provider/probe, forward-only result, residual report, and formal E3 selection loader | Prefill/decode separation from pre-step request counters, exact scheduled-token and past-KV vectors, one-token prefill, canonical mixed-step phase split, source/profile fingerprints, raw/calibrated/observed residuals, and no-follow materialized evidence verification | No SGLang/HiCache types, block/connector/KV I/O fields, implicit profile, global correction scale, unverified residual-report semantics, or uncalibrated mixed-phase latency composition | Strict unit/type/lint gates, deterministic toy replay, real vLLM-0.14.0 SDK golden, and fail-closed formal-selection tests pass. These establish adapter/reference semantics only; target phase/shape forward measurement and held-out residual evidence do not exist, so E3 remains blocked |

## Baseline output and observability contract

| MoonKVSim responsibility | Normative source | Canonical truth source | Derived output and fail-closed boundary | Verification |
|---|---|---|---|---|
| Event journal JSONL | `MOONKVSIM_PLAN.md` section 16.1 | `EventJournal` append order and contiguous `journal_sequence` | Compact, key-sorted UTF-8 JSONL; malformed sequence/time/data is rejected before writing; evidence files are exclusive-create unless the caller explicitly passes `overwrite=True` | Directed canonical-byte/no-clobber unit tests; E1/E2-toy only |
| Capacity delta output and audit | `MOONKVSIM_PLAN.md` sections 9.8 and 16.3 | `RESOURCE_TRANSACTION` rows plus journaled or explicitly supplied allocation geometry | Typed `resource-ledger-deltas` rows, per-boundary replay audit, and event-boundary peak summary; missing requested/allocated geometry is never inferred | Directed conservation, stable-sort, replay-mismatch, and transient-peak tests; E1/E2-toy only |
| Flow-rate output | `MOONKVSIM_PLAN.md` section 16.3 | `FlowRateInterval` boundaries emitted by `FlowContentionModel` | Typed intervals retain payload/start/end remaining bytes, rate, queue/service time, and path; per-flow continuity and payload conservation are checked | Directed contention-boundary and byte-conservation tests; E1/E2-toy only |
| Parquet serialization | `MOONKVSIM_PLAN.md` section 16.1 | Same typed rows as JSONL | Fixed-schema real Parquet only when optional `pyarrow` is installed; otherwise fails before creating a `.parquet` file; publication is atomic and no-clobber by default | Dependency-absent fail-closed test; no physical or cross-version Parquet validation |
| Run artifact bundle | `MOONKVSIM_PLAN.md` sections 15.4 and 16 | Validated `ResolvedConfigBundle`, explicit `RunManifestInputs`, and files produced by canonical output writers | Canonical `resolved-config.json` and schema-valid `manifest.json` are staged beside declared outputs; the complete section-16 output matrix is mandatory in `expected_artifacts`, present/missing sets are checked, and sorted `SHA256SUMS` covers every non-self file. Activation uses `renameat2(RENAME_NOREPLACE)` only; unsupported filesystems abort and clean staging instead of falling back to a racy rename. Scan-time type checks plus `O_NOFOLLOW` file opens reject symlink artifacts and leaf swaps. Code, source-lock, predictor, raw/normalized trace, normalizer, tokenizer, coverage, evidence-class, and calibration claims have no defaults and are never discovered or upgraded here | Directed byte-determinism, complete-matrix omission, concurrent/pre-existing no-clobber, unsupported-filesystem rollback, declaration drift, static/scan-to-hash symlink rejection, checksum corruption, and explicit-incomplete-result tests pass on `/tmp` XFS; the current workspace NFS returns `EINVAL` for `RENAME_NOREPLACE` and is correctly blocked; E1 publication integrity only |

## Model, tokenizer, trace, and design inputs

- Qwen3-8B revision `b968826d9c46dd6066d109eabc6255188de91218`
  locks model config, tokenizer files and the embedded chat template.
- The official model card at that exact revision is hash-locked as configuration
  guidance. It proposes the vLLM candidate `rope_type=yarn`, `factor=4.0`,
  `original_max_position_embeddings=32768`, `max_model_len=131072`.
- The candidate status is `proposed_unvalidated` and readiness is `BLOCKED`.
  The checked-in model config still has native `max_position_embeddings=40960`
  and no `rope_scaling`. Static YaRN may impair shorter contexts, so the model
  card is not an experiment pass: the exact candidate still requires physical
  long- and short-context validation on pinned vLLM revision
  `644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504` and target hardware.
- `scripts/physical/qwen3_8b_vllm_context_probe.py` and its Slurm wrapper provide
  a fail-closed, offline, one-L40S functional diagnostic. Before model loading it
  verifies every locked installed-vLLM semantic file, locked model/tokenizer
  inputs, and SHA-addressed weight shards; it binds the executed staged Python
  copy and the actual Slurm-spooled wrapper. It then requests matched native and
  static-YaRN 8,192-token prompts plus exactly 131,071 prompt tokens and one
  generated token, with pre/post process checks limited to the assigned visible
  GPU. A canonical PASS has not yet been recorded. Even a future PASS remains
  `physical_functional_only`: timings are telemetry, the synthetic prompt is not
  a short-context quality test, and the probe never edits `source-lock.json` or
  upgrades an E-level evidence class.
- The Weka trace is an untracked, SHA-locked source artifact. Its lengths use
  `source_hash_blocks_64`; it is not Qwen-tokenizer-exact input. Reviewed
  publisher-authored sources do not disclose its exact capture start/end, so
  `SRC-BLOCK-003` remains open. `TRACE-PROTOCOL-AMENDMENT-001` preserves the
  interval as `unknown` and allows E0--E2/preliminary use only; it neither
  supplies the missing provenance nor permits formal/paper E4/E5 claims. The
  current source lock has not yet absorbed the amendment hash.
- The immutable patent DOCX is the highest AegisKV design authority. SGLSim
  and Mooncake AegisKV files cannot override it.

## Composed vanilla baseline smoke

`python/moonkvsim/baseline/runtime.py` is the minimal E2 toy composition layer.
`tests/integration/test_baseline_composed_runtime.py` verifies two independent DP
schedulers under one external `DPRouter`, pending-before-commit Store visibility,
real sliced FlowDES Put/Get bytes, same-time GPU failure cancellation/fencing,
router-owned reroute, committed-prefix restore, explicit suffix recompute, and
byte-identical journal plus capacity-ledger replay. Direct paths remain usable
without a lease plan. Host-staged or concurrency-limited tasks fail closed
unless the caller supplies explicit duration, staging geometry, and start
deadline inputs to the shared resource manager; queued tasks start FlowDES at
the reserved timestamp on the same global clock, and completion/abort/GPU
failure releases and reconciles exactly once. Its evidence boundary is
`E2_toy_composed_baseline_semantics_only`: payload sizes and times are synthetic,
and no external runtime, calibration, or physical performance result is implied.

## Normalized vanilla trace replay

`python/moonkvsim/baseline/trace_runner.py` composes the vanilla DP schedulers,
HBM ledgers, Store/Master/Transfer runtime, causal release, and one explicitly
injected forward predictor on the shared DES clock. It never substitutes
aggregate recorded API wall time for a simulated delay. Trace selection retains
whole workflows: `max_spans` may stop only between workflow DAGs and fails closed
when it would cut causal closure. Source `local` hash IDs are interpreted only as
`within_workflow_only`, with cross-workflow reuse forbidden. The strict
`prompt_tokens + output_tokens <= 131072` guard rejects an oversized span and
records zero truncation and zero padding; it never truncates or pads to fit.
Same-phase requests selected by one DP scheduler execute as one physical batch
under a journaled capacity-one GPU compute lease. Chunked-prefill participants
do not emit outputs until their prompt is fully computed. A remote Store prefix
is discovered by scanning the complete within-workflow source-hash vector from
block zero against committed/published objects and stopping at the first miss.
The normalized `cached_prefix_tokens` value is only the direct causal-parent
overlap metric and never bounds that Store query; artifacts retain it separately
from the observed committed Store prefix. A hit keeps the request in
`WAITING_FOR_REMOTE_KVS`; transfer completion records prefix readiness, and
ordinary scheduler admission later allocates HBM and enters `RUNNING` only when
a slot is free. Full-prefix hits recompute the final prompt token before
sampling. A mixed step may proceed only with the E2 harness's
explicit fingerprinted joint assumed-integer rule (one base, whole-step request
overhead, and separate prefill/decode shape terms); the record is always
`not_calibrated`/non-formal, and absence of a rule remains fail-closed. A
calibrated arbitrary mixed-shape provider and TP/PP layouts other than TP=1/PP=1
remain open.

A replay may establish only
`E2_real_trace_shape_vanilla_baseline_uncalibrated`: deterministic composition
over real normalized trace shape, not calibrated timing, physical parity, E3,
or E4 evidence. For a pre-output `GPU_FAILURE`, Store and all HBM bridges share
one journaled allocation registry; the complete failed-GPU HBM ledger becomes
`UNAVAILABLE_CAPACITY`, affected logical blocks become degraded/`LOST`, compute
or prefix-Get work is canceled, and reroute uses only a committed continuous
Store prefix plus suffix recompute. Both capacity ledgers, the allocation
registry, transfer-resource calendars, and flow-rate state must replay
byte-identically under the overall journal gate, and duplicate outputs are
rejected. Its
section 16 projection now publishes the exact 19-file contract with 13 fixed
Parquet schemas. Trace hash/selection, predictor and mixed-rule provenance,
gaps, capacity/replay audits, and a before/after semantic-source snapshot remain
embedded; source drift fails before publication and unborn/dirty Git state is
marked unfrozen. This complete E2 file set does not imply complete physical,
calibration, or paper evidence. Recovery after any already-emitted
output now remains externally fenced while `prepare_recovery` materializes the
prompt and predictor-backed internal forwards silently replay each committed
output position. Only a `READY_TO_ACTIVATE` plan reached after a modeled forward
completion may atomically activate; checkpoint zero still requires prompt
materialization, and no replay output is externally emitted. This is tested E2
position-only/tensor-free recovery semantics, not token-content equivalence,
physical execution, calibrated failure timing, or higher evidence.

## Known fidelity boundary

A source map proves provenance, not implementation parity, timing calibration,
runtime validation, or paper readiness. The three directed scheduler/block CPU
traces and one tensor-free Store connector lifecycle capture establish only
their recorded E2 semantics. They do not execute CUDA, model tensors, Mooncake
RPC/bytes, hybrid attention/cache groups, or physical timing; every remaining
differential stays open until its own trace and result are stored as evidence.

The checked-in Qwen3-8B layouts under `configs/resolved/qwen3-8b/` are E1
source-derived artifacts. Their `runtime_gpu_cache_capacity_*` fields are
intentionally null: the recorded max-context footprint is not a live vLLM
worker's cache capacity, and the 128K YaRN artifact remains
`proposed_unvalidated`.

The optional scheduler HBM observer enforces block-pool and aligned physical
ledger availability before request/block mutation, and records cause-tagged
per-GPU reserve/activate/release transactions. Cacheable pages may remain in an
explicit inactive reusable account; aliases never incur another physical
charge. Directed tests and the pinned ordinary block-pool trace close only this
toy/CPU lifecycle slice. They do not establish CUDA cache capacity, worker
allocation parity, hybrid-cache behavior, or failure-time cached-page recovery.

The normalized runner implements the complete 19-file section 16 publication
contract, including 13 fixed-schema Parquet files. Clean source-frozen
no-failure, near-128K, and corrected fixed-failure diagnostic pairs at
`2f4ffb8` are byte-identical, but they predate the complete initial-ledger and
workflow-completeness projection gates and are not final acceptance. The bundle
publisher records caller-supplied evidence claims and verifies their structure,
resolved-input bindings, declared file set, and bytes; it does not prove those
external claims. Its directed tests establish E1 publication integrity and
E2-toy semantic invariants only. They do not establish vLLM/Mooncake
differential parity, calibrated rates, physical accuracy, formal experiment
completeness, or paper readiness. No AegisKV policy/runtime semantics are
present in this output path. Verification is a point-in-time check of a
caller-controlled directory, not a signature, authenticated archive, or
immutable-storage guarantee; actors able to rewrite directory components
concurrently remain outside this boundary. Final tag acceptance requires all
six bundles to be regenerated and strictly compared on one clean final commit.
