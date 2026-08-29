# MoonKVSim trace inputs

The formal Weka input remains outside this repository.  This tree contains only
the contract, deterministic streaming tools, a metadata-only manifest, and tiny
test fixtures.  It deliberately does **not** contain a generated copy of the
1.8 GB raw or normalized trace.

The locked source uses `hash_id_scope="local"`: the frozen source protocol
defines this as workflow-local hash identity, and all 393 source rows report the
same value.  Normalization maps it explicitly to
`hash_id_scope="within_workflow_only"` while preserving the raw value as
`source_hash_id_scope_raw="local"` in every span and audit manifest.  Other raw
scope values fail closed.

The source-native count is evidence about 64-token Weka hash blocks, not exact
Qwen tokenizer output. Formal selection applies the complete guard
`in + out <= 131072`; it never truncates, pads, stitches, or resamples a span.
All Weka parent edges are labelled `inferred` because the source has no explicit
per-parent request identifier.

Read-only audit:

```bash
python -m traces.scripts.audit_128k_coverage RAW.jsonl \
  --expected-raw-sha256 29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276 \
  --raw-trace-read-only
```

Normalization is an explicit write and refuses to overwrite by default:

```bash
python -m traces.scripts.normalize_trace RAW.jsonl \
  --output traces/normalized/weka.jsonl \
  --manifest-output traces/normalized/weka.trace-manifest.json \
  --expected-raw-sha256 29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276
```

Run the command twice into different temporary destinations and compare the
normalized SHA256 and strict audit document before freezing an experiment trace.

The full 2026-08-30 execution did exactly that. Both 46,142-record outputs were
byte-identical (`SHA256=0a1c37deea32f2c393ba7d8d2d9a7c5629854b874b01ace8953140ad889f6d54`),
and the repository records the small comparison and DAG audit in
`audits/weka-normalization-determinism.json`. The 310,842,484-byte normalized
JSONL remains outside Git and is reproducibly regenerated from the locked raw
file.

The public dataset repository is pinned at revision
`23f152f6f0f9399a85901b89a6458def0ef16729`; its large-file pointer reports the
same raw SHA256 and byte size. The pinned dataset card states Apache-2.0 and a
2026-06-21 corpus build timestamp. The publisher's AgentX methodology separately
states that participants opted into an HTTP proxy and that the v1.0 corpus was
built on that date. Neither source discloses when the underlying proxy traces
were collected. A build timestamp is not a collection interval, so
`SRC-BLOCK-003` keeps formal and paper-ready trace claims closed. None of the
source-block checks establish target-tokenizer equivalence or a successful 128K
vLLM execution.
