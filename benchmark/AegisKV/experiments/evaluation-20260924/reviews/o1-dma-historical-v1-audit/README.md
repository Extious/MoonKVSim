# Reproduce this historical audit

From the repository root, use a fresh output directory:

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/audit_o1_dma_evidence.py \
  --primary benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v1 \
  --sensitivity benchmark/AegisKV/experiments/evaluation-20260924/sensitivity-campaign-v1 \
  --out /tmp/aegiskv-o1-dma-historical-audit \
  --label historical-v1-before-causal-domain-fix
```

For later versions, pass the corresponding campaign directories, a new label,
and a new output path. No source import, runtime execution, or old output
mutation occurs. Multi-invocation fallback reconstruction is explicitly
unsupported and fails rather than silently treating new calls as the old one.

- `AUDIT.json` binds all raw inputs, the analysis script, versions and exported
  CSVs by SHA-256; all input hashes were checked again after analysis.
- `RESULTS.md` is generated from raw summaries.
- `CANDIDATE_RECONCILIATION.md` explains the historical review's numeric and
  causal claims, including denominator distinctions and negative results.
- `primary-healthy.csv` includes each policy and load's raw fallback counter,
  backup-byte components and healthy mean WCT.
- `dram-threshold-comparison.csv` exposes completed-only versus all-transferred
  backup savings; `dram-threshold-workflow-pairs.csv` retains every same-ID
  healthy/fault WCT comparison.
- `fallback-control-windows.csv` retains each active workflow at each observed
  control window. The two aggregate ratios use workflow/window observations;
  they are not independent samples or confidence intervals.
- `dma-workflow-pairs.csv` preserves all four raw F0/F1 values per workflow.
  `dma-scenarios.csv` separately evaluates cohort sum WCT and target-only WCT,
  including the hypothetical binary-scenario break-even calculation.

The `-initial` sibling retains the first audit pass. This final audit adds
explicit workload bindings, checks input hashes after analysis, and supports
version-dependent evidence wording; its numerical values are unchanged.
