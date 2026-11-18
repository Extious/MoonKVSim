I'll start by mapping the study directory and the five review packages, then read each package's protocol, results, and audit files directly.Now reading the predictor-training package's protocol, report, audit, and models.The predictor package's guard quantile arithmetic checks out (nearest-rank p90 of 12 maxima = 11th value). Now reading the frozen predictor and trainer implementations.The predictor module is byte-identical across all packages and the current tree. Reading the trainer and the runtime `Tracker`/`ContextRegressor` it relies on.Predictor package reviewed. Moving to the low-DMA package: results, endpoint CSVs, flow audit, and completion seal.The shell sandbox is failing intermittently, so I'll use the file-search tools on the CSVs directly.For scale: MiniCPM doc 10146 DRAM at 8 GB/s / 2560 µs finishes at 132.87 ms, so the ~0.5 ms differences are under 0.5%. Native package reviewed; moving to the quota-pressure package.The priors aren't a config field, so I'll check how `evaluation_quota.py` binds predictor, priors, guard and the fixed/dram policies, and whether the frozen copy matches the current one.Frozen and current `evaluation_quota.py` are byte-identical (sha 7713fac0…, 69 lines). Reading it along with the protocol.The four quota workflow IDs appear in the predictor's `TRAINING_PROTOCOL.json` and split file. Checking which side of the split they're on.The four quota workflows are in `excluded_evaluation_workflows`, so there's no train/eval leakage. `runtime.py` distinguishes `dram` from `all_dram`, so I'll check what `dram` protects.Checking whether the low-DMA package labels the `dram` policy as "All-DRAM", which would be a naming error given `all_dram` is a separate policy.Old-concern mapping is clear. I'll grab exact line references for the low-DMA denominator and break-even statements to cite in the report.I'll re-pull the headline held-out and transparency numbers from the package files so the report cites them exactly.I'm Claude Opus 5.5. Everything was read-only: I made no edits, ran no DES and retrained nothing. Beyond reading code and sealed artifacts, I only ran offline counts over existing event logs. I did not open the running F1 jobs or `paper/evaluation.tex`.

**Verdict (methods and reporting only, not EuroSys readiness):** The five packages are methodologically sound as bounded, modeled diagnostics. These all check out, and I found no code bug that changes a reported number:
- hash bindings
- train/evaluation disjointness
- native causality
- fixed-quota semantics
- break-even arithmetic

The null and negative results are legitimately retained. The reporting is not yet clean:
- **Undisclosed (main issue):** in the quota cohort, the new predictor makes Slack protect all 52 of 52 Agents.
- **Post-hoc headline:** the native component replay's headline bandwidth was chosen after execution.
- **Wrong dose:** the low-DMA payload rate is not the quantity the slowdown model responds to.

Fix these before any number is reused.

## (a) Errors, confounds, leakage, provenance

### Confirmed

1. **Quota: Slack protects every Agent, and the reports don't say so.**
   - In `quota-pressure-postreview-v1/runs/margin0-dma0-dram-F0/events.jsonl.gz`, 52 of 52 Agents commit checkpoints to their last full 256-token boundary (100,141,725,312 B).
   - The old-proxy parent run `sensitivity-campaign-v2-corrected/runs/center-dram-F0` protects 45 of 52 (95,341,871,232 B).
   - `dram` is the Slack-selected DRAM arm, not All-DRAM (`current/runtime.py:632`). So DRAM, the fixed quotas and adaptive all protect the same set, which is why each adds exactly 28.840 ms of healthy cost.
   - Neither `RESULTS.md` nor `PAPER_CANDIDATE.md` says this.
   - `PROTOCOL.json:14` says "high guard can suppress selection", which reads backwards. A larger guard lowers Slack and *increases* protection.

2. **Quota: the endpoints reproduce the old-proxy runs exactly.**
   - At DMA 0, adaptive, fixed128 and fixed4096 match the low-DMA package's old-proxy AegisKV run to the nanosecond (target ΔWCT 59,529,382 ns; cohort 3,587,123,021 ns). DRAM matches too (60,973,253 / 3,588,566,892).
   - So neither the predictor swap nor the small pool changes any DMA-0 endpoint. At 0.005 only the healthy cohort sum moves (115.36 vs 111.78 ms).
   - The 1.444 ms HBM-tier gain is essentially the historical Peer-HBM staging (O2) maximum of 1.442 ms, so this package adds no new O2 evidence. The `dram` arm's results depend on which predictor version it ran with.
   - Units are mixed. `quota-pressure-postreview-v1/RESULTS.md:34` sets a cohort *sum* contrast beside a per-workflow *mean* healthy cost, while low-DMA reports cohort sums.

3. **Native: the headline bandwidth was not prespecified.**
   - The runner's `protocol()` fixes `primary_M=32000` but no primary bandwidth (`run_native_transfer_component.py:60–64`).
   - Yet the summary, candidate paragraph and figure all headline 32 GB/s. For NOSA that is where Current's deficit is smallest.
   - `reviews/native-transfer-paper-summary-v1/model-bandwidth-compute-summary.csv` row 5 shows Current 1,504.5 µs slower than Recency at 8 GB/s with 2560 µs/layer compute. Row 9 shows −591.4 µs at 16 GB/s.
   - Current beats Recency in only 1 of 36 cells (row 33: MiniCPM at 16 GB/s and 2560 µs, +123.1 µs).
   - The headline omits absolute DRAM times. MiniCPM document 10146 finishes at 132.87 ms at 8 GB/s and 2560 µs (`native-transfer-postreview-v2/document-results.csv` row 5), so every difference is under 0.5%.
   - Averaging the two checkpoints is post hoc. They are not independent either: M=32000's future window is exactly the history M=32256 adds.

4. **Held-out predictor: nominal load is confounded.**
   - The arrival interval comes from training work (`TRAINING_PROTOCOL.json:2`) and is reused for the 62 held-out workflows. The same nominal ρ is therefore a different offered load on each side of the split.
   - My recomputation from `walltime-primary-v3/runs/*-none-F0/errors.jsonl.gz` gives held-out ρ=0.9 median labels about 2.4× the training labels. Predictions stay flat near 1.58 s (8B), and 85% of them are under-predictions.
   - `HELDOUT_ERROR.json:79` confirms "no load/queue input feature".
   - Held-out MAE beats the role median by only 2.2% for 8B (2.027 vs 2.073 s) and 2.1% for 32B. The out-of-fold gain was about 7%.

5. **The ambiguity "floor" is only across-load dispersion.**
   - `reviews/heldout-context-ambiguity-v3/RESULTS.json` has histogram {3: 503} and no cross-Agent groups, so each group is one Agent seen at three loads.
   - The minimum MAE (995.6 ms for 8B, 1,012.5 ms for 32B) is therefore just mean(range)/3, and would be zero within any single load.
   - Calling it "not a population bound" is correct, but it should be named a load-dispersion floor.

6. **The fitted regressor is essentially prompt length plus text hashes.**
   - In `models/Qwen3-8B/model.json`, every history weight is exactly 0, because all training Agents are single-call. The prior weight is 0.055.
   - `PRIOR_TRANSPARENCY.json:5–8` (fallback 0 → 5,356) validates prior transport through `prior_predictor`, not the regressor.

7. **Low-DMA: the dose and break-even presentation mislead.**
   - `low-dma-postreview-v1/FLOW_AUDIT.json:7` computes the D2H rate over "first workflow release to last workflow completion, including host idle time". That window is each run's own makespan, so it varies by run despite the "common" label.
   - The slowdown fires as a binary flag per compute event (`_compute_delay`), so bytes/s is not the dose.
   - `RESULTS.md:19–22` lists p = 1.532 at c=0.05 and 1.495 at c=0.10. When the F1 gain is ≤ 0 there is no break-even at all, and a non-monotone number above 1 invites misreading.
   - The target gain overstates the cohort gain by 0.877 s.
   - The single fault hits the longest-prompt Agent (`quota-pressure-postreview-v1/PROTOCOL.json:31`), a favourable choice.

8. **Minor:**
   - The role-median target encoding inside each fold is in-sample.
   - The reference and prediction Trackers publish 100 µs apart.
   - About 40% of training Slack points fall back to zero Slack.

### Hypotheses (not verified)

- **Out-of-fold optimism.** Workflows in one capture share queue trajectories, so leave-one-workflow-out (LOOWF) doesn't remove within-run correlation. That could explain the drop from about 7% to 2.2%.
- **Cause of protect-all.** It is probably the 910 ms guard rather than fallback: fallback counts are similar (6,736 new vs 7,249 old).
- **Guard coverage.** The 910 ms (8B) and 995 ms (32B) guards were calibrated in a less congested regime, so held-out coverage may fall below the nominal p90.
- **Native background order.** It is Current-ranked for every method (`run_native_transfer_component.py:90–93`), which plausibly favours Current. If so, the negative results are conservative.

### Checked and clean

- **Native causality.**
  - Counters use queries 0..M−1, and the replay and Oracle use M..M+255 (`run_native_transfer_component.py:236–248, 363–366`).
  - `engine.topk` equals the deployed `top_blocks`.
- **Predictor training.**
  - Fold priors come from the other 11 workflows.
  - The guard is the nearest-rank p90 of the 12 workflow maxima (the 11th of 12), computed correctly.
- **Disjointness.** The four quota workflows and all 62 held-out workflows are listed in `excluded_evaluation_workflows` (`TRAINING_PROTOCOL.json:7–14`).
- **Quota binding.**
  - `predictor_sha256` e6e2e9d3… and guard 910,471,105 appear in `PROTOCOL.json:48, 418` and in the run configs.
  - The pool is 7,186,811,456 B = 5,039,327,808 + 2 GiB (+margin).
  - Frozen and current `evaluation_quota.py` (7713fac0…) and `runtime.py` (de3a9ce7…) are byte-identical.
- **Pressure.**
  - Pressure means an admission had to reclaim replica space (`runtime.py:865–866`) and then succeeded: 0 denied admissions and 0 admission waits.
  - It occurs in 12 of 36 healthy (F0) runs and 0 of 36 faulted (F1) runs.
  - It appears at 11.3 s, after the target finished at 7.67 s.
- **Fixed comparators.**
  - They track the live ceiling: the core reclaim lowers them and they regrow each control window (`evaluation_quota.py:31–55`).
  - fixed32 does start at 32 MiB (margin-128 control log), so its equality with DRAM reflects an insufficient budget, not a zero-quota artifact.
- **Retry placement.** The retry worker is 6 in every quota variant, so the old retry-placement confound is absent here.

## (b) Old concerns from `FINAL_OPUS55.md`

**Resolved:**
- The concern that the natural test used a proxy rather than the Design's target: there is now a submission-to-completion predictor, trained with grouped LOOWF on disjoint workflows.
- The adaptive quota (O3) now has a real pressure test against a live-ceiling fixed baseline.
- DMA overhead is swept rather than assumed zero.
- Native selector traces are replayed at bandwidth-bound points against Recency and a future-frequency reference.
- Adverse and zero cells are retained everywhere.

**Remaining:**
- **Slack selection (O1) still has no demonstrated benefit.** In the quota cohort it degenerates to protect-all, and zero-Slack fallback persists: 184,700 fallback observations in the v3 8B ρ=0.9 healthy none-policy run.
- **Peer-HBM staging (O2) is unchanged.**
  - Current ties or loses to Recency in 35 of 36 cells.
  - Its gain over DRAM is at most 0.54 ms (under 1%), at component level only.
  - The WCT gain is still 1.444 ms.
- **The adaptive quota (O3) remains a safety mechanism with unverified benefit.** Pressure never overlaps recovery, and the endpoints are null.
- **Scope.** One fault, four dependent workflows, single-call training data, no confidence intervals, and modeled outputs only.

## (c) Evidence-bounded claims

1. **Predictor accuracy.**
   - The walltime predictor is trained with grouped LOOWF on 12 workflows that are disjoint from every evaluation workflow.
   - On healthy held-out captures it reduces MAE by 2.2% (8B) and 2.1% (32B) versus role medians.
   - It under-predicts at high load and shows nothing about multi-call Agents.
2. **Selection.** With the calibrated 910 ms guard, Slack protects all 52 Agents of the four-workflow cohort, so O1 makes no selection there.
3. **DMA break-even.**
   - Setting: an uncalibrated binary DMA model, the old service proxy and one favourable fault.
   - The break-even failure probability rises from about 0.05 (c=0.002) to about 0.55 (c=0.02).
   - At c ≥ 0.05 the faulted cohort itself loses.
4. **Native residency.**
   - In a native-trace raw-KV component replay, Current saves at most 0.54 ms (under 1%) against DRAM.
   - It never beats Recency on NOSA or NSA, and beats it in 1 of 12 MiniCPM cells.
   - The future-frequency reference is not latency-optimal: Recency beats it by 203 µs on NOSA at 32 GB/s and 256 µs.
5. **Quota.**
   - In a constructed near-foreground pool, pressure occurs only in healthy runs and only after the target finished, with no denied admissions.
   - Adaptive quotas equal fixed 128 and 4096 MiB on all 24 paired endpoints.
   - An HBM tier of at least 128 MiB cuts target ΔWCT by 1.444 ms (2.4% of DRAM's 61 ms residual); 32 MiB gives nothing.

## (d) Essential next checks (offline, on the completed packages)

1. Add protected-Agent counts and checkpoint bytes per quota variant to `RESULTS.md` and `PAPER_CANDIDATE.md`, and fix the "suppress selection" wording.
2. Compute held-out guard coverage per load from the six v3 captures, using the existing `reference_slack_errors` logic.
3. In the native summary, either show all three bandwidths or mark 32 GB/s as post hoc. Add absolute DRAM times and name M=32000 as the primary checkpoint.
4. For low-DMA, report the fraction of compute events that overlap an active copy as the dose, and state "no break-even" wherever the F1 gain is ≤ 0.
5. Use the same sum-or-mean units across packages, and label each `dram` result with the predictor it ran under.
6. Rename the ambiguity floor as load dispersion, noting that it is zero within a single load.
