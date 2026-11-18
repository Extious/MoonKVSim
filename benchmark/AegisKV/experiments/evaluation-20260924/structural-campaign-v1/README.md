# Constructed structural campaign v1

143 frozen runs: five prescribed four-Agent DAG interventions, three seeds and three policies; additional history-reuse scale controls use 32 and 128 independent workflows. Each DAG executes once. Workload token IDs, arrivals, role priors and phase-drift patterns are constructed.

Qwen3-8B TP1 / DP4 uses the pinned AIC duration grid; no GPU inference is executed. All calls declare a fixed 16K output cap for admission. Role priors are hand-set proxies; this campaign cannot establish remaining-time prediction accuracy. Long-decode drift combines constructed sparse selection with dense-model compute cost; it is not a native sparse model run.

PLAN.json freezes the matrix, every workload hash, failure identity and total-token trigger. MANIFEST.json and source_snapshot/ pin the executed sources. Formal run results live in runs/. smoke/ is excluded from all formal tables. Two prespecified formal runs retain detailed event, flow and journal logs, indexed by TRACE_AUDIT.json.

raw-runs.csv contains one row per run and all counters; paired-workflows.csv contains same-ID F1 minus its own-policy F0, including negative and collateral outcomes. summary.csv reports descriptive mean/p95/p99 without significance claims or request-as-independent confidence intervals. The worker or host remains failed, so collateral capacity-loss effects are part of F1.

VALIDATION.json checks hashes, paired input/config/IDs, exact outputs, zero residual allocations and absence of output-length-oracle admission. Evidence remains modeled and uncalibrated for integrated serving: no continuous batching or measured DMA/compute interference is represented.

These results describe the original frozen runtime. The subsequently diagnosed recovery-selector domain issue can affect dense overlap fractions and sparse selected block identities; numerical recovery/WCT effects have not been measured by corrected runs. Completion, ledger and EOS checks establish historical-model accounting only, not repaired semantics. See RECOVERY_DOMAIN_ERRATUM.md at the campaign root.
