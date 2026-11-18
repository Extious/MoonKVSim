# Recovery causal-domain correction and matched rerun plan

Status: prospective plan, written before corrected simulations. No existing
result is relabelled by this document. The independent diagnosis and regression
evidence belong in `DESIGN_CONFORMANCE_SPOTCHECK.md` and the eventual fix report.

The recovery path currently passes the committed checkpoint frontier as the
selector's entire candidate domain. Normal forwards use the complete causal
history. This can change synthetic/native selected block identities, and even
for dense demand it omits locally reconstructed/current-step KV from the
hit-compute fraction. Transfer requirements must include only selected blocks
below the checkpoint frontier; locally produced tail blocks require no remote
restore. Selection must occur over the same full causal domain as a normal
forward before partitioning by residency.

## Before new execution

1. Finish the already-running read-only Opus candidate review and preserve its
   exact reviewed source identities and verdict.
2. Apply the smallest domain/residency correction under a new design version.
   Check dense overlap arithmetic, a domain-sensitive sparse selector, causal
   visibility, metadata-before-demand order, and EOS/copy cleanup. Existing
   current-runtime regression checks must pass.
3. Correct metadata for newly prepared profile campaigns. Existing sealed
   manifests retain their appended timing errata.
4. Freeze fresh source snapshots, plans, model profiles and workload inputs.
   Compare all old/new job configs, failure identities, decoded workloads,
   training priors and detailed-log choices before starting. Record any intended
   source or plan difference explicitly; do not select cases based on outcomes.

## Evidence replacement

The primary 180-point matrix and the 126 resource, 32 capacity/Slack, ten
post-hoc, and 135 main structural conditions need matched corrected executions
before their numerical claims can describe the new implementation. Old runs
remain historical evidence, including their negative findings. A corrected run
is a replacement version of a condition, not an additional independent sample.

Healthy and restart-only paths should be unchanged by this domain correction;
compare them explicitly. Compare each checkpoint recovery and workflow by ID,
including sign changes, unchanged outcomes, completion status, bytes and event
ordering. Recompute figures and conclusions from the corrected summaries,
rather than applying an analytical offset to old WCT: even a small local timing
change can alter later routing and queueing.

The eight existing structural scale extensions describe execution cost of their
own frozen runtime. They are not a calibration of the corrected simulator or
production control-plane overhead. Any new scale execution must have its own
source identity and recorded CPU/RSS conventions. The ongoing historical
128-workflow jobs can finish without changing their sources.

The offline native Top-K replay does not call the affected recovery routine.
Its selection results are not invalidated by this correction and are not
converted into WCT evidence.

The user-frozen preceding manuscript stays unchanged. A new Evaluation draft
must disclose the corrected version, retain historical adverse evidence where
discussed as historical, and receive a new external review. Completion of the
reruns alone is not an assertion of publication readiness.
