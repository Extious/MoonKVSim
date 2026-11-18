# Figure captions and placement

All figures have 178 mm canvases and Linux Libertine 10.3 pt text. Insert at that width.

**structural-target-wct.pdf.** Fault-target workflow completion penalty in five constructed
four-Agent scenarios, with eight workflows per run. Each point is F1 minus its own-policy
failure-free F0 for one of three matched workload seeds. Thin gray segments connect the same
seed across policies; colored vertical ranges show min/max and short horizontal marks show
means. Panels inject a fault during the second invocation's new Prefill or Decode; resolved
Agent/call/token identity is fixed across policies. Zero and negative values are retained.
DRAM and AegisKV points may coincide at this scale. These are simulated interventions, not
observed Agent serving traces; the two panels use distinct logical progress points.

**structural-all-workflow-wct.pdf.** The same per-workflow F1 minus own-policy F0 endpoint,
averaged over all eight original workflow IDs within each run before plotting one point
per seed. Target and all-workflow panels use the same 90 failure runs; no workflow is
discarded for avoiding the fault or receiving an adverse effect. Three seed points,
min/max and means have the same descriptive interpretation; eight workflows are not
treated as eight independent seed replicates. Raw same-ID pairs and descriptive p95/p99
of paired deltas are retained separately; a percentile of paired deltas is not the
difference between unpaired percentile WCTs.

**structural-recovery-breakdown.pdf.** Recovery delay of the directly faulted Agent in the
same 90 failure runs. Top panels show waiting between retry enqueue and admission; bottom
panels show admitted recovery service until the first new output token. Detection adds a
fixed 1 ms, so total recovery delay is detection plus queue plus service. Markers, paired
segments, means and min/max use the same three constructed seeds as the completion plot.
Separate ordinate units preserve visibility of service cost when queueing dominates.
Recovery service improvement does not imply the same workflow completion improvement.

Scale-resource tables exist only for a separately included full 143-run plan.
Final compiled-paper placement must be checked when these PDFs are integrated.
