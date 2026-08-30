# Vanilla real-trace E2 harness

`vanilla-weka-e2-smoke.json` is a fail-closed, executable configuration for a
single complete Weka multi-agent workflow. It selects workflow
`e094e1381d88f8aa6c9592279d51f97c5d87`: 27 real normalized spans from seven
agents, including six-way fan-out and one 104,217-token request. The source is
the exact 46,142-span normalized file at
`/tmp/moonkvsim-weka-normalized-run1.jsonl`, SHA-256
`0a1c37deea32f2c393ba7d8d2d9a7c5629854b874b01ace8953140ad889f6d54`.
The selected workflow has 3,553 source-block references and 3,272 unique
source hash IDs: 33,530,314,752 reference bytes and a 30,878,466,048-byte
unique-hash lower bound at the frozen target payload. Both fit the explicit
64-GiB smoke Store; this selected-workflow check is separate from the full
46,142-span scale audit below.

The normalized `cached_prefix_tokens` field measures longest direct
causal-parent hash overlap; it is not a Store-hit declaration or a lookup
limit. Runtime lookup scans the complete current hash vector from block zero,
accepts committed/published Store objects only, and stops at the first miss.
The selected workflow's source-vector audit identifies 281 repeated prefix
blocks in three exact pairs: 80 blocks for `000154:000001` from
`000090:000001`, 12 for `000174:000005` from `000174:000001`, and 189 for
`000184:000005` from `000184:000001`. These are static input expectations for
the eventual replay audit, not measured timing or proof that a Store object was
resident when queried.

This configuration is E2 trace-shape evidence only. All predictor durations,
HBM fixed reserves, Store capacity, rates, and the enlarged one-source-block
flow slice are tagged `assumed`; `predictor_database_sha256` is null and the
result writer reports `not_calibrated`. The Qwen3-8B 128K YaRN target remains
`proposed_unvalidated`. Mixed prefill/decode steps use the config-declared joint
integer formula: one base term, one overhead term over all requests, then
prefill-token and decode-request/past-KV terms. The rule and parameter artifact
are fingerprinted in every mixed-step record; they remain preliminary E2 inputs,
not a calibrated composition. Failure injection is disabled, and this checked-in
smoke continues to run through the no-failure CLI only.

Run twice into new local `/tmp` directories:

```bash
uv run python scripts/run_vanilla_trace_e2.py \
  --config configs/experiments/vanilla-weka-e2-smoke.json \
  --output /tmp/moonkvsim-weka-e2-smoke-run-a

uv run python scripts/run_vanilla_trace_e2.py \
  --config configs/experiments/vanilla-weka-e2-smoke.json \
  --output /tmp/moonkvsim-weka-e2-smoke-run-b
```

Exit 0 means every selected span completed and the capacity/replay audits
passed. Exit 3 means the runner published an honest `BLOCKED` result; inspect
`run-audit.json` and `summary.json`. Input, provenance, no-clobber, filesystem,
or invariant failures exit 2. Existing output paths are always rejected.

Each published run contains exactly the fixed 19-file section-16 matrix,
including all 13 fixed-schema Parquet tables. Empty or incomplete event classes
remain valid typed tables rather than missing files. Runner-owned trace source,
whole-workflow selection, predictor/gap state, capacity/replay audit, and the
semantic source manifest are merged into the projection rather than replaced.
Per-span artifacts retain both normalized causal-parent overlap and the
observed committed Store prefix; the two are intentionally allowed to differ.

Before replay and again before publication, the launcher hashes Git HEAD/tree
and porcelain state plus every `python/moonkvsim` source, the CLI, all JSON
schemas, the selected config/layout, and dependency locks. Any drift rejects
publication. An unborn or dirty worktree is recorded as `source_frozen=false`;
it is never described as a frozen run. Matching file hashes across two runs are
meaningful only when their semantic-source snapshot fingerprints also match.

## Near-128K trace-shape harness

`vanilla-weka-near128-e2.json` is a second complete, strict harness config. It
differs from the smoke config only in its whole-workflow selection and retains
the same assumed hardware profile and fingerprint. It selects workflow
`0e4206535a79f980e2b1091181202ea987fe`, containing eight normalized spans and
590,080 aggregate prompt tokens. Its largest record is `main:000006`, with a
130,176-token prompt and 619 output tokens (130,795 total), so every selected
record passes the no-truncation `prompt_tokens + output_tokens <= 131072`
guard. The aggregate workflow total is reported only as a workload-shape
descriptor; it is not one model context.

These token counts come from the trace's `source_hash_blocks_64` representation:
one source hash block is counted as 64 tokens. They are not Qwen3 tokenizer
counts and are not evidence of tokenizer equivalence. Likewise, selecting a
near-128K trace shape does not physically validate Qwen3-8B at 128K, validate
the proposed YaRN target, calibrate timing or resources, or produce formal,
E3, E4, E5, or paper-ready evidence. No checked-in result claims that this
workflow has been executed; the external normalized trace must exist at the
exact path and SHA-256 declared in the config before the strict loader accepts
it.

## Independent fixed-failure harness

Failure-enabled replay is a separate protocol and CLI; it does not reinterpret
`vanilla-weka-e2-smoke.json`. A runnable failure config must enumerate only
`GPU_FAILURE` events at strictly increasing, unique virtual nanoseconds and bind
each event to an exact configured `(replica_id, gpu_id, hbm_resource_id)` tuple.
The gates reject negative, duplicate, or out-of-order times, other fault kinds,
unknown targets, repeated fail-stop of one PhysicalGPU, random selection,
repair, and implicit fallback. Run a materialized config only with:

```bash
uv run python scripts/run_vanilla_failure_trace_e2.py \
  --config configs/experiments/vanilla-weka-failure-e2.json \
  --output /tmp/moonkvsim-weka-failure-e2-run
```

`vanilla-weka-failure-e2-unresolved.template.json` is deliberately not a
harness config: `runnable=false`, its timestamp and target contain literal
`UNRESOLVED` sentinels, and strict loading rejects it. One clean,
source-frozen diagnostic series at commit `2f4ffb8570bfaad24ea27d288e545a7351291e78`
executed no-failure, near-128K, and fixed-failure pairs byte-identically. The
corrected failure pair fenced and rerouted only the one active route; seven
already finished routes were excluded. These bundles predate the final
Section-16 completeness change and are regression evidence, not tag acceptance.
The deterministic selector produced
`reference/vanilla-weka-failure-point-selection.json` and the checked-in fixed
failure config above.

The current projection emits pristine timestamp-zero capacity ledgers for every
declared resource, including untouched accounts/resources. Cross-request TPOT
is explicitly not applicable instead of being treated as missing; TTFT and WCT
still require complete simulated boundaries. The strict comparator now rejects
any bundle with an incomplete capacity snapshot, a non-empty incomplete-resource
list, incomplete request/workflow timing, or contradictory decoded Parquet row
flags. Final acceptance therefore requires all
six bundles to be rerun on one clean final commit and compared there; no existing
diagnostic bundle is promoted automatically.

## Caller-owned transfer resource plans

The strict network schema optionally enables an assumed, non-formal
`transfer_resource_plan`. Every DP path then binds its actual PUT/GET source
copy lane, destination copy lane, and endpoint/QP lane. The shared manager
journals acquisition, reserved start/end, all lane reservations, terminal
outcome, and one release, so queue wait, service, and abort are reconstructable
from the 19 artifacts. Missing plans or bindings, unknown resources, duplicate
IDs, and non-positive capacity/lane inputs fail closed.

Host staging pools are explicit when planning is enabled, but transport
semantics remain authoritative: `RDMA_GDR` paths cannot bind or charge Host
staging, while `TCP_HOST_STAGED` paths must bind both endpoints and charge
fully explained aligned allocations from acquisition through release. The
checked real-trace smoke now supplies explicit caller-owned rate/copy/QP plans
while retaining RDMA GDR transport: its declared Host pools are not bound or
charged. A toy real-shape TCP fixture covers staging, concurrent queueing, and
GPU-failure cancellation/release. All duration/capacity/lane values are assumed
E2 inputs, not SSD/NVMe behavior, physical concurrency, or calibration.

Every checked-in path also binds its directional source/destination endpoint,
node, NUMA, and HCA IDs. Retry zero is explicit and deterministic; the
preferred/available distinction remains in the path schema instead of being
inferred from rate priority. A separate assumed registration-worker resource
drives cold registration and warm pooled lookup through their own GlobalDES
events before any transfer lease or FlowDES byte movement begins. Those delays
are recorded in the KV-transfer projection and are never added to GPU forward.
They do not represent sysfs/CUDA discovery, real memory registration,
connect/QP handshake, reconnect behavior, or physical timing calibration.

The workspace is NFS and is intentionally rejected as an experiment-output
target. The launcher reads `/proc/self/mountinfo`, requires a path below
`/tmp/`, and rejects NFS/NFS4 plus any existing target. This preserves the
runner's current local-filesystem no-clobber boundary; it is not an NFS atomic
publication implementation.

## Open scalability and fidelity gates

- `load_trace_run_input` streams, validates, hashes, and counts all 46,142 rows
  while retaining the large source-hash vectors only for explicitly selected
  workflows. This removes selection-time resident memory proportional to the
  full corpus, but a full all-span replay and its journal/artifacts remain a
  separate scalability exercise and must not be launched casually.
- The smoke uses real multi-agent fan-out with
  `max_num_running_requests=4`. A single-span or serial workflow can be a
  launcher sanity check only; it is never multi-agent acceptance.
- The no-failure real-trace smoke and independent failure protocol both use the
  same explicit caller-owned RDMA-GDR rate/copy/QP bindings. The integer lease
  duration and lane counts are resolved only as assumed control-flow inputs;
  e094 still has no physical copy/queue/overlap calibration.
- A streaming scale audit found 44,462,997 source-block references,
  2,951,227 within-workflow unique source hash IDs, 31,990,468 output tokens,
  and 13 zero-output spans across the full 46,142-span trace. At the frozen
  9,437,184-byte target payload/source block, even the unique-hash lower bound
  is 27,851,272,224,768 Store bytes, far above this smoke config's 64 GiB.
  Zero-output spans are also intentionally rejected by the current Request
  contract. A full command is therefore blocked before launch; it needs a
  separately resolved full deployment plus bounded-memory input/output and a
  non-fabricating zero-output policy.
- The complete file set and semantic source manifest are E2 publication
  contracts only. They do not create a calibrated predictor database, validate
  the proposed 128K target, turn assumed resource rates into measurements, or
  establish baseline acceptance, E3/E4/E5, or paper-ready evidence.
