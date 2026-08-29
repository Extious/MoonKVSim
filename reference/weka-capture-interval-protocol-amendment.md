# Weka capture-interval protocol amendment

Amendment ID: `TRACE-PROTOCOL-AMENDMENT-001`

Effective date: 2026-08-30

## Locked input

- Dataset: `semianalysisai/cc-traces-weka-062126`
- Repository revision: `23f152f6f0f9399a85901b89a6458def0ef16729`
- Raw file SHA-256:
  `29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276`
- Normalized file SHA-256:
  `0a1c37deea32f2c393ba7d8d2d9a7c5629854b874b01ace8953140ad889f6d54`

## Unresolved provenance fact

The reviewed publisher-authored dataset card and AgentX methodology do not
state the source proxy-trace collection start or end. The disclosed
`2026-06-21T17:48:24Z` value is the corpus build timestamp and MUST NOT be used,
rounded, or relabeled as a collection boundary. The capture interval therefore
remains exactly `unknown` until publisher-authored evidence supplies both
boundaries.

No relative request timestamp, file modification time, repository commit time,
newsletter publication date, or inferred approximate duration may fill this
field.

## Evidence policy

Runs using this input MAY be used for:

- E0/E1 source, schema, and implementation validation;
- E2 source-hash-block trace-shape, causal-DAG, deterministic state-machine,
  and byte-accounting validation;
- explicitly preliminary simulator comparisons whose manifests keep
  `formal_use_allowed=false` and `paper_result_allowed=false`.

Runs using this input MUST NOT be used for:

- a claim that the workload represents a known calendar interval;
- formal workload-frequency, arrival-rate, seasonality, or population claims;
- formal or paper-ready E4/E5 baseline-versus-treatment conclusions;
- any figure/table cell whose gate requires complete capture-interval
  provenance;
- silently substituting the corpus build timestamp for capture start/end.

Component calibration or physical validation that does not use this trace is
not downgraded by this amendment. Combining such evidence with a Weka replay
does not upgrade the Weka replay above its own evidence ceiling.

## Required manifest fields

Every affected run must retain all of the following:

- `collection_interval.status=not_disclosed_by_reviewed_public_sources`;
- `collection_interval.value=null`;
- this amendment ID and content SHA-256;
- the locked raw and normalized hashes above;
- `formal_use_allowed=false` and `paper_result_allowed=false`;
- an explicit evidence boundary that distinguishes source-block trace shape
  from target-tokenizer equivalence and physical timing.

The run is invalid if any required field is absent or if a downstream merge
overwrites it with a stronger claim.

## Resolution

This amendment may be retired only when either:

1. a publisher-authored source states the exact capture start and end for the
   locked raw artifact; or
2. the experiment uses a separately locked real multi-agent trace with a
   complete capture interval and independently passes all provenance,
   tokenizer, causal, 128K, calibration, and completeness gates.

Retiring the amendment requires a new source-lock/manifest revision. It does
not retroactively upgrade earlier Weka runs.
