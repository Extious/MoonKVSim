# EuroSys 2027 reviewer audit: legacy-WCT AegisKV paper

Audit date: 2026-08-26 HKT

This is a reviewer-risk audit, not result evidence.  The frozen legacy result
artifacts are the quantitative authority; `../design/current_design.md` is the
current design authority.

## Executive verdict

The manuscript is a complete anonymous EuroSys-format draft with WCT as its
performance endpoint.  It contains a Motivation figure, editable System
Overview, three WCT result figures, two current-design mechanism figures,
explicit AI-use disclosure, and a 12-technical-page body followed by two
reference pages.

The empirical boundary is material: the system sections describe the current
source-owned independent-tier design, while every WCT result predates that
design.  The paper makes this mismatch explicit in the abstract, Evaluation,
Discussion, Conclusion, and captions.  It does not claim that the current
implementation produced the WCT results.

No new experiment was run for this revision.  A paper-only renderer read and
replotted frozen artifacts.  It did not launch SGLSim, Mooncake, vLLM, CUDA,
GPU work, or Slurm.

The paper now exposes a second, non-performance evidence line: frozen
current-design SGLSim telemetry for pressure, effective alpha, tier occupancy,
reuse, intended residency, copy amplification, and conditioned restored-token
coverage.  It is neither WCT nor Estimand B and is not pooled with the legacy
WCT line.

## Quantitative result audit

### Direct DP8 paired trial

The only multi-baseline direct WCT comparison has 24 workflows, one seed and
trial, three soft failures, and fixed alpha=0.30:

| Policy | Mean (s) | p50 (s) | p90 (s) | p99 (s) | Mean delta vs no backup |
|---|---:|---:|---:|---:|---:|
| No backup | 91.695 | 95.186 | 110.326 | 113.733 | -- |
| HostBackup | 79.734 | 79.426 | 91.163 | 99.339 | -11.961 s |
| GPUReplica | 81.731 | 82.729 | 94.054 | 97.382 | -9.964 s |
| Legacy AegisKV | 87.756 | 89.355 | 99.625 | 104.269 | -3.939 s |

Legacy AegisKV beats no backup by 4.3% in mean WCT and wins 15/24 paired
workflows.  It is worse than both HostBackup and GPUReplica.  Any dominance
claim would contradict the artifact.

### DP64 model projection

The Qwen3-8B logical-DP64 artifact projects 160 workflows from a 20-sample DP8
CDF shape plus a 128K clean-run time/token scale.  It predicts:

- mean WCT: 4,193.35 s vs 4,753.03 s for no backup (11.78% lower);
- p99 WCT: 5,705.16 s vs 6,676.35 s (14.55% lower);
- retry-token source: 26.2% legacy L1 reuse, 37.2% legacy L2 reuse, and
  36.6% recomputation, versus 100% recomputation for no backup.

This is model projection, not measurement or a direct 160-workflow execution.
It omits correlated outage, co-failure, and queue spillover.

### Heavy-failure stress smoke

The Qwen3-32B logical-PP artifact has 20 workflows and 16 injected failures
per panel.  Mean WCT reductions versus no backup are 18.9% at concurrency 8
and 30.4% at concurrency 16.  These are descriptive direct-simulator smoke
points, not a calibrated scaling law.  The source labels them
`sglsim-offline-unvalidated`, and its alpha/beta pressure check is false.

### Current-design mechanism telemetry

Frozen lineage `4a99c306e8f9` contains 3,110 completed runs: 33 scenarios,
311 policy--scenario cells, and 10 seeds over 393 Weka workflows and 98,827
requests.  The reported matrix covers two model/parallel layouts, 16--128
simulated GPUs, concurrency 32--224, 1--40 GB/s, and failure hazard 0--41.667
per 1,000 GPU-shard-hours.

- Increasing concurrency 32 to 224 raises mean pressure 0.018 to 0.590 and
  lowers mean effective alpha 0.868 to 0.129.
- At concurrency 128, increasing scale 16 to 128 GPUs lowers pressure 0.860 to
  0.077 and raises alpha 0.012 to 0.492.  Alpha is zero in 27.3% of windows at
  16 GPUs and 27.6% in the Qwen3-32B PP4 stress case.
- Workflow-local 64-token accounting finds reuse in 92.63% of requests and
  98.31% of input tokens.  The paper reports reuse-bin-specific intended
  residency and conditioned recovery coverage.
- The central point has 1.443x copy amplification.  HBM-only admissions and
  DRAM evictions are both zero across the 33 full-policy aggregates, so the
  paper presents them as unexercised cells.
- Fixed-K64 conditioned restored-token coverage changes from 0% at 1 GB/s to
  87.09%, 90.92%, and 93.28% at 10, 20, and 40 GB/s.  This is not a physical
  throughput, WCT, online failure-recovery probability, or Estimand-B claim.

## Reviewer risks

### Current-design validity

**High risk for performance; partially addressed for mechanisms.**  None of
the WCT artifacts executes the current independent
HBM/DRAM admission, independent source ACK paths, two-level victim indexes, or
current HBMQuotaAIMD semantics.  The data show that an earlier KV-protection
prototype can avoid recomputation; they do not validate current-design WCT.
The separate 3,110-run lineage exercises and characterizes current-design
policy state, but does not execute serving or close the WCT gap.

### Baseline competitiveness

**High risk.**  The only paired multi-baseline trial favors simple host and
peer-GPU backup over legacy AegisKV.  The paper retains this result and makes a
narrow usefulness claim rather than superiority.

### Statistical strength

**High risk.**  The direct trials are small and lack independent multi-seed
confidence intervals.  The three lineages cannot be pooled.  The DP64 result
is a projection.

### Physical and serving validity

**High risk.**  There is no physical failover, CUDA/Mooncake transfer,
shared-NIC contention, healthy-path serving interference, or deployed
throughput/latency measurement.

### Completeness and presentation

**Pass with caveat.**  The paper has the expected system, implementation,
evaluation, discussion, related-work, and conclusion structure, and WCT CDFs
are now visible.  The empirical caveats are too large for a strong systems
claim, but hiding them would make the paper less defensible.

## Artifact and format checks

- `figures/legacy-wct-submission.manifest.json` binds all source and output
  files and states that no new/current-design experiment was executed.
- `figures/current-mechanism-supplement.manifest.json` binds the selected
  current-design telemetry and explicitly states `workflow_completion_time_result=false`,
  `estimand_b_result=false`, and `physical_result=false`.
- All three WCT plots are vector PDFs with 10.0 pt minimum extracted text.
- `sh scripts/build.sh`: PASS.
- Technical pages: 12; References begins on page 13; total pages: 14.
- No overfull box, undefined citation/reference, fatal LaTeX error, or
  undefined control sequence.
- All pages rendered and visually inspected; no clipping or overlap found.
- Visible and PDF author metadata remain anonymous.
- Final PDF SHA-256:
  `5ab501f2f8914af575375c27d612af9c8562fb0064f50da1ec7f490fe3884c68`.

## Required work before a current-design performance claim

Run a frozen, multi-seed, current-design WCT campaign that uses the same
source/config/profile lineage for AegisKV and every baseline, executes
failover and recovery rather than querying a surrogate, includes contention
and healthy-path cost, and isolates Algorithms 1--3.  Until then, the legacy,
projection, smoke, and current-design-not-validated qualifiers are mandatory.
