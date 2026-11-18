# Reference implementation and simulator alignment

> 当前算法 2/3 已修订为 revision 3。本文原有测试、构建/交付与实验数据是旧版记录；最新范围见 [修订说明](ALGORITHM_REVISION_V3.md) 和 [发布状态](REVISION_STATUS.json)。旧 PASS 不覆盖当前 PDF 或新算法的运行性能。

Reference task: `01a06fae-403a-7852-97c1-475ca121b4c8`, read from the local
Codex rollout dated 2026-09-05. Current Mooncake checkout is dirty; its Git
HEAD alone does not identify the AegisKV implementation. The individual
source hashes are in `output/paper-simulation-8b/20260906-alignment/MOONCAKE_REFERENCE.json`.

Authoritative design: `/home/comp/zhanzhao/Mooncake/benchmarks/aegiskv/design/current_design.md`.
The older `Mooncake/aegiskv/design` path no longer exists.

## Findings and corrected prompt-protection model

| Aspect | Reference source | Previous simulation | Revised behavior |
|---|---|---|---|
| Independent admission | native `TierHarm`, `GrossGain`, `JointLoss` | Independent tier-local harm already present | Retained; 260 differential native cases cover gain, pending invisibility and AIMD |
| Candidate coverage | `vllm/gate.py:_next_logical_tokens` | HBM 75%, DRAM 90% envelopes | All sealed prompt chunks are candidates; each tier can bypass |
| Chunk size | `connector.py`: prefix 4096, decode 256 defaults | Uniform 1024-token prompt chunks | Default prefix 4096; decode protection is outside this prompt-only projection |
| Buffer visibility | connector publishes completed forward buffers | Seal time interpolated inside an atomic scheduler step | Publication at forward completion |
| Pending prefix | one ordinal, independent tier outcomes | Multiple ordinal candidates and tiers advanced at different speeds | One candidate per transfer; shared ordinal barrier waits for both outcomes and seals only a bypassed lagging tier |
| HBM envelope | `HbmTargetConfig.total_hbm_bytes` | Alpha times post-weight KV capacity | Alpha times explicitly modeled registered HBM capacity; physical allocator remains separate |
| Control period | physical full-treatment config: **5 s** | Median ideal workflow makespan | Fixed **1 s**; declared model parameter, not matched physical cadence |
| Routing | `router/state.py`: rendezvous hash, route-bound standby | Cache/queue-aware minimum estimated completion | Same role/request/worker rendezvous rule, stable standby identity |
| Recovery source | `gate.py:batch_get_into_multi_buffers`: HBM first, DRAM fallback | Chooses predicted-faster Peer-first or Store-first | Peer-first; DRAM loading follows HBM loading |
| Target-local HBM | `hbm.py:load_local_batch` copies to vLLM slots | Zero-copy role reclassification | Explicit copy and separate destination reservation; backup remains occupied during load |
| Read lifetime | Local load locks slots; activation leases govern key visibility, not a blanket pressure-eviction exclusion | Missing source lease during destination reclaim | Committed recovery source pinned through materialization; quota victims exclude it |
| Request completion | native `CompleteRequest` waits for pending paths then reclaims | Protection entries persist after completion | Drain pending paths, release both request-owned tiers |
| Content ownership | Router injects `_request_cache_salt(request_id)`; Controller records belong to request/route/ordinal | Cross-request primary and protection aliases | Request-scoped primary and protection keys, matching the reference request salt |

The revision mode is `mooncake_prompt_v1`; `legacy_v3` preserves the previous
model for reproducibility. Current `engine.json` selects the revised mode.
Old September 5 executions are not evidence for the revised mode.

## Boundaries that must remain explicit

This is a projection of the implementation's prompt-protection paths, not a
bitwise vLLM emulator or a calibrated digital twin. The frozen FanOutQA-derived
workload supplies exact prompt tokens and prescribed output counts, not actual
generated-token KV tensors. The simulator therefore does not invent protected
decode chunks. Unprotected output positions are silently replayed. The real
connector's 256-token decode sealing is described as implementation behavior,
not credited as a simulated recovery benefit.

The simulated residual CPM uses prescribed ideal durations. The real
Application uses causal GBDT estimates and a workflow-disjoint lower-margin
calibration, and fails closed for unknown structure or missing metadata.
The 4090 predictor was fitted to short synthetic two-branch workflows; applying
it to 86K FanOutQA calls would be unjustified extrapolation. Ideal and zero-Slack
experiments characterize assumptions; they do not validate predictor quality.

The reference gate clamps advertised prefix recovery time to the previous
frontier and full recomputation cost. Our positive-gain linear prompt model
admits only improvements and does not infer a globally optimal recovery plan.
The revised connector gate follows the prototype shared-ordinal restriction:
it seals a lagging tier if its peer commits an ordinal that it bypassed. The
two admissions and copy results remain independent; neither tier requires
prior residency in the other. Recovery batches sort by remaining Slack, then
descending current recovery harm, then request ID. Before acquiring backup
read leases, primary destination allocation may reclaim unpinned backup tails;
if live primary KV prevents admission, the request waits on its bound target.

## Physical pilot versus the simulation regime

The accepted physical pilot is Slurm 146426, DP2 / RTX4090 / Qwen3-8B FP16,
with host-staged TCP because CUDA peer access was unavailable. It terminates a
worker process group 1.5 seconds after ACTIVE and completes all 12 requests in
each arm. It does not power off a GPU or perform a repair cycle.

The full-treatment deployment registers a **2 GiB HBM pool with alpha 0.5**;
`total_hbm_bytes` is its configured pool-capacity parameter, not a measurement
of all device memory. The design denotes this parameter by M. The revised
A100 model explicitly chooses physical 40 GiB as its registered M and alpha
0.2, while separately reserving weights and runtime memory. Thus the envelope
formula matches; the operating points differ.

The final natural-admission pilot has six HBM_ONLY admissions, 177.75 MiB of
HBM recovery, and zero DRAM admissions. Directed HBM/DRAM mechanism tests and
calibration precede it and are not counted as natural DRAM recovery hits.
Batch times are 56.310 s unprotected, 56.307 s without HBM, and 56.570 s full.
It establishes functional recovery, not a speedup. Its AIMD stable windows
and cleanup pass; pressure-driven physical tail reclamation and streaming
output fencing remain outside its accepted evidence.

Same-allocation effective rates are 0.587 / 0.336 GB/s for HBM / DRAM protection
and 2.300 / 1.233 GB/s for recovery. They include software overhead and are not
hardware peak bandwidths or A100 calibration. The simulation's assumed PCIe
25 GB/s, DP8, long contexts, 120 s repair and ideal service composition remain
separate declared assumptions.

## Retry ownership correction and experiment invalidation

The first frozen alignment source (`source-v1`) incorrectly retained the two
BYPASS outcomes after an all-bypass attempt. A later HBM commit could therefore
combine with an older DRAM bypass and seal DRAM prematurely. A deterministic
regression reproduces the defect. `source-v2` clears both old outcomes before
retry and prevents either tier from retrying while its sibling's current
attempt remains unresolved. The targeted suite passes 127 tests.

All v1 measured outputs are invalidated and retained as diagnostics. V2 runs
all 170 measured cells afresh. Its 20 logical failure plans are imported with
hash-bound provenance: every reference oracle is unprotected and never
invokes the changed protection gate. No treatment result is imported.

The simulation's 60% logical request-progress fault is interpolated within the
first crossing forward step (floor nanoseconds, clamped before its end). This
is a controlled intervention assumption, not a claim that the worker exposes
intermediate KV. Only earlier completed forwards produce readable protection
chunks. The physical pilot instead uses wall time after ACTIVE.

## Raw-verification serialization adapter

All 170 v2 measured executions completed. Restarting the original runner for
verification exposed a Python/JSON type comparison bug: in-memory tuples
become JSON arrays and reload as lists. The separate `verification-v1` adapter
compares canonical JSON digests. Its manifest records the one-line diff; it
changes neither execution nor auditing logic. The frozen source-v2 and raw
outputs remain untouched. `RAW_VERIFICATION.json` binds the completed audit
to this adapter and the acceptance file.


## Figure-revision correction (2026-09-06)

The full pilot worker configuration explicitly records `aegis_aimd_interval_s: 5.0`;
its actual feedback windows are about 5 s apart. The frozen simulation remains
at 1 s. The previous description of matched one-second windows was incorrect.
No accepted run or result was changed by this documentation correction.

The simulated read pin excludes pressure victims throughout materialization.
Native `load_local_batch` holds a local lock while copying, but native
`_free_slot_locked` hides a recovery key and frees its slot; the Controller's
pressure selection does not consult Worker leases. Activation-to-load races
are therefore not established equivalent by the current conformance harness.
The manuscript and figure captions now preserve this distinction.
