# O3 constructed small-pool diagnostic

Status: COMPLETE, 72/72 formal scenarios and one separate nonempty-flow observer validation. This is a simulation accounting result, not external paper acceptance or a production capacity guarantee.

- `RESULTS.md`: full conditions, null results, pressure timing and evidence limits.
- `PAPER_CANDIDATE.md`: 165-word English candidate, NOT APPLIED to the manuscript.
- `INDEPENDENT_ACCOUNTING_AUDIT.json`: separate source/result binding, ledger integration, actual observer-file comparison and all 24 exact adaptive/fixed endpoint checks.
- `audited-bindings.csv` / `audited-endpoints.csv`: corrected statistical names, all resource/fault endpoints.
- `MECHANISM_ENDPOINTS.json`: every run's pressure control/admission snapshots and native quota events, including empty sets.
- `raw-runs.csv`, `paired-workflows.csv`, `policy-contrasts.csv`: retained original runner outputs.
- `runs/`: 72 complete per-run summaries, ordinary admission timestamps, physical resource transitions, quota/pressure windows and reclaims.
- `validation/observer-transparency/`: base-runtime control. Summary and decompressed events/flows exactly match the observed formal run; flows are nonempty.
- `validation/REUSE_GATE_TESTS.json`: four hermetic file-integrity tests, zero DES runs.

The matrix keeps the original four workflows/52 single-invocation Agents, exact tokens/DAG/arrivals/cap512, and one logical fault. It uses the sealed online walltime predictor, role priors and guard. The small pool is constructed from the largest declared foreground allocation plus reserve and margin; all invocations individually fit. No new workload, fault, margin or DMA level was selected after observing outcomes.

Pressure appears in 12 F0 runs and zero F1 runs; all 12 pressure observations occur after the target workflow finishes. Two 32MiB adaptive conditions exercise a real 32-to-24MiB multiplicative decrease. No capacity-denied admission occurs. Adaptive and fixed128/fixed4096 have identical Workflow endpoints in all24 paired comparisons. These outcomes establish neither adaptive superiority nor recovery under observed pressure.

## Verification and replay

From the repository root, use:

```bash
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/run_quota_pressure_campaign.py verify --out benchmark/AegisKV/experiments/evaluation-20260924/quota-pressure-postreview-v1
.venv/bin/python benchmark/AegisKV/experiments/scripts/current_design/audit_quota_pressure_campaign.py --out benchmark/AegisKV/experiments/evaluation-20260924/quota-pressure-postreview-v1
```

Both commands verify existing evidence without launching DES. The live launcher first rechecks any existing observer validation and then re-executes the original frozen runner. `RUNNER_INTERFACE_REPAIR.json` records this interface-only repair; the frozen numerical source was not overwritten and no formal run was replaced. Direct old-snapshot execution requires the independent audit before accepting reused validation. `review-source/` preserves the exact safe launcher and auditor bytes for inspection/restoration at their canonical repository paths; these flat copies are not standalone entry points.

`FINAL_AUDIT.json` seals this delivery. Original experiments, v3 primary results and the paper were not modified by this campaign.
