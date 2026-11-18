# Qwen3-32B DP8/TP4 engine contract

`qwen3-32b-dp8-tp4-8node-a100-80gb.json` is a strict, simulation-only
configuration. It remains separate from the shared Qwen3-8B `experiment.py`
path, but the dedicated `qwen3_32b_tp4_runner.py` formal schedule path now
executes it through `Qwen3TP4GroupDES` rather than reconstructing recovery
timestamps with the isolated integer-cost helper.

For every scheduled recovery, that path executes both independent four-shard
protection transactions, the complete source-TP4 failure fence, four parallel
rank recovery events, the zero-payload readiness barrier, one directory
generation install, and the subsequent model-forward collective. The result
binds the GlobalDES journal SHA-256, ordered event trace, fenced DP groups,
path commit states, and physical capacity-conservation result.

This wiring exercises the Qwen3-32B four-shard Algorithm-2 transaction surface
and a real Q32-specific Algorithm-3 controller. Each Router-designated target
DP rank owns an independent `(alpha, stable-window-count)` state. An explicit
schedule pressure signal executes an immediate multiplicative decrease and
resets the counter; exactly spaced stable windows produce one additive increase
after `K=4` windows. Every transition records the previous and next state,
reason, resident-primary/free-reclaimable/Peer-HBM physical account snapshot,
quota, enforcement result, and deterministic decision fingerprint in the
GlobalDES journal.

The configured modeled parameters are `alpha_min=0`,
`alpha_initial=alpha_max=0.50`, multiplicative factor `0.50`, additive step
`0.05`, and a `100,000 ns`
control window. They are provenance-bound assumptions, not fitted results. A
quota contraction is published only when current committed-plus-pending Peer
HBM already fits; otherwise this Q32 path fails closed because it has no
Q32-specific suffix-safe reclaim transaction. Store admission and bytes remain
independent. The runner therefore remains CPU-modeled, uncalibrated,
non-physical evidence even after all DES phases complete.

The 32 inference GPUs are placed as eight DP replicas. Each replica occupies
all four A100-SXM4-80GB GPUs in one node, and its TP group uses the node-local
NVLink fabric. Peer-HBM protection maps every source DP replica to a different
node and preserves TP rank: source shard `tp=k` is copied independently to
target shard slot `tp=k`. A logical chunk commits only after all four shard
writes acknowledge.

Peer HBM and Mooncake Store DRAM are independent source-owned paths. Both read
from the primary-HBM production buffer. Neither tier may be populated from the
other, and admission or failure on one path does not gate the other path.

## Fail-closed modeled capacity

Each TP rank declares 80 GiB (`85,899,345,920` bytes) of A100-SXM4 HBM. The
locked model revision's `model.safetensors.index.json` reports
`65,524,246,528` serialized weight bytes; the contract models an even TP4
division of `16,381,061,632` bytes per rank. That division remains subject to
runtime partition validation because replicated runtime tensors and allocator
behavior have not been measured. The fixed runtime reserve is modeled as one
eighth of the per-rank weight bytes rounded up to a GiB, or `2,147,483,648`
bytes. The arithmetic remainder is `67,370,800,640` KV-capable bytes per rank.

The Peer-HBM dynamic upper bound is `33,685,400,320` bytes per rank, exactly
50% of that KV-capable HBM. It is a reclaimable subquota shared with primary
and reusable KV, not an additional reservation: weight + fixed runtime +
KV-capable HBM equals physical rank HBM. The configured Store DRAM L3 is one
dedicated Store node with one `store-0:segment-0` segment of
`1,000,000,000,000` bytes. Its failure domain is outside all eight inference
nodes; it is not an inference-node-local L2 buffer.

Every capacity field is marked `modeled_uncalibrated` and has an individual
provenance string. The serialized total comes from the
[locked Qwen3-32B safetensors index](https://huggingface.co/Qwen/Qwen3-32B/blob/9216db5781bf21249d130ec9da846c4624c16137/model.safetensors.index.json).
The HBM usable capacity, runtime reserve, TP4 split, Peer-HBM 50% ceiling, and
Store capacity have not been physically observed or selected from result
trends.

## Frozen Qwen3-32B workload

`../../workloads/fanoutqa-dev-qwen3-32b-tp4-160.jsonl` is derived from the
frozen Qwen3-8B 160-workflow workload. The pinned 8B and 32B revisions have
byte-identical `tokenizer.json`, `tokenizer_config.json`, `vocab.json`, and
`merges.txt` artifacts, as recorded in
`../../workloads/qwen3-8b-32b-tokenizer-equivalence.json`. The derivation keeps
all 1,304 exact prompt-token-ID vectors, hashes, span IDs, parent edges,
workflow IDs, record order, and token counts. It changes only model identity,
`recorded_api_time_ns`, and the corresponding `observed_finish_ns`.

The new duration is computed by the Qwen3-32B TP4 analytical roofline provider
using prompt chunks of at most 4,096 tokens followed by single-token decode
steps. This is a deterministic, modeled and uncalibrated Algorithm-1 duration;
it is not a trained predictor, a physical measurement, or an externally
observed execution schedule. The independent manifest
`../../workloads/fanoutqa-dev-qwen3-32b-tp4-160-manifest.json` binds the source
workload and manifest, tokenizer-equivalence evidence, duration-provider
provenance, generated artifact, and exact derivation whitelist.

Of the 1,304 records, 1,099 fit the native 40,960-token context and 205 require
the proposed YaRN extension. At workflow granularity, 74 are entirely native
and 86 contain at least one YaRN-dependent request. The maximum observed
context is 86,214 tokens. No record is truncated, padded, synthesized, sliced,
or concatenated. The proposed 131,072-token runtime remains unvalidated.

## Proposed 128K context boundary

The locked model revision's native configuration remains recorded as `40,960`
tokens. This simulation contract targets `131,072` tokens through a proposed
YaRN extension so the frozen 160-workflow input can be represented without
truncation or padding. The field
`proposed_yarn_128k_modeled_runtime_validation_pending` is deliberately
fail-closed: it records a modeled layout target, not successful vLLM/CUDA
loading, memory-fit validation, or physical 128K execution.

## “All-reduce” semantic boundary

Recovery is **per-rank shard load plus collective synchronization**, not a
mathematical all-reduce. Each target TP rank activates its Peer-HBM shard or
loads its Store-DRAM shard into primary HBM. When all four ranks are ready, a
TP barrier installs one directory generation. The collective carries only
readiness/block-table metadata; the configured data-reduction byte count is
zero. Summing or averaging KV tensors is forbidden because the four rank-local
KV tensors are partitions, not reduction operands.

All bandwidth, setup time, and collective-overhead values are explicit modeled
assumptions. They are uncalibrated and permit simulation-only claims. Runtime KV
layout differential validation and same-topology physical calibration remain
required before this configuration can support empirical performance claims.
