**Verdict: NOT READY.** I am Claude Opus 5.5. Every number I checked matches the artifacts, and the retired service-proxy sentences are gone. What fails is interpretation. One statement about system behavior is false. Several omissions let a reader infer benefits the evidence does not show. And the section never says plainly that AegisKV's three distinctive mechanisms do nothing measurable in the primary replay: Slack-based Agent selection, the Top-K×L Peer-HBM tier, and the adaptive HBM quota.

This was read-only: no files edited and no simulations run. Two gaps: `AUDIT.json` is too large to read and is unverified, and the 52-of-52 protection count comes from the earlier methods review, not my own derivation. Paths are relative to `benchmark/AegisKV/`, and `v3/` means `experiments/evaluation-20260924/walltime-primary-v3/`.

## (a) Confirmed errors, omissions and hypotheses

**Verified with no discrepancy:**
- Guards (0.910/0.995 s), held-out mean absolute error (MAE) and role-median baselines, and every Table 1 cell.
- HBM increments of 3 ns–1.444 ms (8B) and 0–0.137 ms (32B).
- Byte savings of 0.016/0/0% and 0.087/0.082/0.015%, and the fallback counts 3,426/5,586 and 3,826/6,518.
- The routing counterexample (−3.40 s cohort sum), every primary-section number, and the low-DMA and native-coverage values.
- `paper/figures/eval-primary-wct.pdf` is byte-identical to `v3/figures/primary-target-wct.pdf`. The final-size color and gray PNGs match `per-identity.csv` and stay legible in grayscale.

**Confirmed errors**

1. **Static-HBM versus AegisKV (`paper/evaluation.tex` lines 154–156).** "Despite different allocation and transfer behavior" is false for 32B.
   - In `v3/run-metrics.csv`, AegisKV's 32B quota never grows (0 increase events, maximum 128 MiB). Its healthy (F0) records equal Static-HBM's in every column.
   - For 8B, the quota peaks at 192 MiB (ρ = 0.3/0.65) and 256 MiB (ρ = 0.9), against a 4 GiB cap.
   - No healthy run of either model records a quota decrease or pressure event, so the adaptive half of the quota controller never runs.
2. **Identical healthy WCT comes from the configuration (lines 157–159).** `v3/runs/Qwen3-8B-load0.65-dram-F0/config.json` sets `compute_dma_slowdown` to 0.0. Identical healthy WCT across all five policies despite nonzero backup traffic confirms no interference charge applies anywhere. The phrase "execution and interference assumptions" hides that the coefficient is zero, so readers will conclude protection is free. The Operating Range subsection itself shows a 3.33–6.66% healthy cost at coefficients 0.05–0.1.
3. **Predictor description omits its main error (lines 70–72).**
   - `v3/HELDOUT_ERROR.json` gives a bias of −1.515 s (8B) and −1.524 s (32B), reaching −3.12/−3.10 s at ρ = 0.9.
   - The improvement over role medians shrinks from 6.6%/8.6% out-of-fold (`reviews/walltime-predictor-training-v1/README.md`: 1.011 vs 1.082 s, 1.207 vs 1.321 s) to 2.2%/2.1% held-out.
   - "High load dominates that error" is true but hides the systematic under-prediction, and no held-out check of guard coverage is reported.
4. **Visual-review gate still open.** `v3/PAPER_POSTPROCESS_COMPLETE.json` is `NUMERIC_COMPLETE_VISUAL_REVIEW_PENDING`, and the page previews in `paper-preview/` (05:13) predate the current `main.pdf` (10:02:57). I saw no figure defect.

**Confirmed omissions that bear on the design**

5. **Swapping the predictor barely changed outcomes.** `v3/paper-summary/V2_V3_COMPARISON.json` shows only 11 of 150 target endpoints and 16 of 11,160 workflow pairs changed. The one large change (+4.113 s at 32B ρ = 0.9 S5) is a retry moving from worker 6 to worker 5 (`v2-v3-placement.csv`), not a selection change. This is the most direct evidence that Slack prediction does not drive outcomes, and it is missing.
6. **Adverse per-identity cases are missing.** `paper-summary/README.md` lists 5 target/cohort and 2 target/Agent sign reversals among 120 contrasts.
   - At 8B ρ = 0.9 N4, DRAM recovers the Agent 1.775 s faster yet the target workflow finishes 2.226 s later.
   - At 32B ρ = 0.9 N4, DRAM's Agent latency is 9.4 ms worse than restart.
   - Restart and checkpointing often retry on different workers (32B ρ = 0.3 S5: worker 2 vs 3; 32B ρ = 0.9 N4: 3 vs 6), so DRAM-versus-restart WCT mixes reconstruction with placement. The text notes this for one identity only.
7. **Two null result packages are left out.**
   - `quota-pressure-postreview-v1/RESULTS.md`: adaptive quota equals fixed 128 MiB and 4 GiB quotas in 24 of 24 endpoint comparisons, with pressure in 0 of 36 faulted runs.
   - The earlier methods review reports that the native-transfer package finds the deployed (Current) ordering no better than Recency in 35 of 36 cells.
   - These are the only direct tests of quota adaptation and transfer ordering.
8. **The native comparison at K = 16 is one-sided (lines 367–376).** At the deployed K = 16, Recency's distinct coverage equals Current's for NOSA and NSA (8.31%, 4.20%) and beats it for MiniCPM (4.13% vs 4.06%) (`native-topk-warm/summary.csv`). The text gives Recency only for event coverage at K = 16 and places the favorable Δ at K = 64.

**Hypotheses (not verified)**
- The 8B HBM maximum of 1.444 ms is close to 11 layers × 16 blocks × 64 tokens × 4,096 B ÷ 32 GB/s ≈ 1.442 ms. The HBM gain may therefore be bytes divided by bandwidth rather than an emergent effect; lines 390–393 partly concede this.
- DRAM's mean latency is identical to 10 digits at 8B ρ = 0.3 and 0.65 (0.4884638662 s). Retries may be waiting on the target's own sibling Agents rather than background load.
- The zero-Slack fallback, whose logged reason is always `prediction_minus_age_nonpositive`, is plausibly caused by the negative bias in item 3.

## (b) Status of earlier methods-review defects

| Earlier defect | Current status |
|---|---|
| Quota cohort protects all 52 Agents | Package omitted; implication still misleading |
| Native-transfer headline bandwidth chosen post hoc | Moot because omitted; its adverse result is omitted too |
| Low-DMA payload rate is not the slowdown dose | Error removed; dose still undefined |
| Held-out MAE only ~2% better than role medians | Numbers stated; bias, out-of-fold drop and load confound omitted |

- **Quota cohort.** The capacity paragraph (lines 285–293) credits Current with a 4.58–4.66% reduction in healthy backup bytes. That saving belongs to the service proxy, which protects 45 of 52 Agents on this cohort. The evaluated predictor protects all 52, and in the primary replay DRAM saves at most 0.087%. The global predictor labels (lines 74–76, 122–123) are correct, but this paragraph invites crediting the evaluated predictor with a saving it does not produce.
- **Low-DMA.** The coefficients are now used as the dose. Still missing:
  - that the slowdown is charged as a binary penalty on each compute start overlapping any active copy (78.8% of healthy starts, 75.3–75.4% of base compute);
  - that the primary uses a coefficient of 0;
  - that the 24-run extension was added after review.
  
  The 1.494 root is correctly described as infeasible.
- **Retired service-proxy sentences.** The ±4.113 s exchange, the old 10% saving, and the −0.0026 ms HBM gain appear nowhere in `paper/*.tex`.
- **"Near-complete checkpoint coverage" (line 204).** Not overstated relative to All-DRAM, but it needs a denominator. Bytes alone cannot support it because long contexts dominate them. Checkpoint commits can: DRAM commits 25,414–25,437 of All-DRAM's 25,437 healthy checkpoints, at most 23 gaps per run.

## (c) Claims the evidence supports

These claims hold only for an uncalibrated discrete-event model with FCFS, one-invocation-per-worker execution. The trace is a constructed FanOutQA replay of 62 held-out workflows, with single-invocation Agents and short gold-answer outputs. The models are dense Qwen3-8B and Qwen3-32B, with five fixed faults per cell.

1. DRAM checkpoint-and-replay lowers the interrupted Agent's mean failure-to-first-new-token latency versus restart in all six cells (for example, 0.956 to 0.488 s at 8B ρ = 0.3). Retry queueing accounts for 62–91% of the remaining latency.
2. Workflow effects are mixed:
   - The target penalty improves at 8B ρ ≤ 0.65 and on average at 32B ρ = 0.3, but worsens at 8B ρ = 0.9.
   - Target, cohort and Agent endpoints can disagree in sign.
   - Retry placement can cost more than reconstruction saves (+1.453 s of queueing versus −29 ms of service).
3. Peer HBM adds at most 1.444 ms (8B) and 0.137 ms (32B) per target workflow. A 1.10 ms local gain can reroute work and raise the 62-workflow sum by 3.40 s.
4. With the evaluated predictor, the exposure threshold is almost inactive:
   - DRAM matches All-DRAM WCT on every pair and saves at most 0.087% of bytes.
   - The regressor beats role medians by about 2% and under-predicts by about 1.5 s.
5. Adaptive quota shows no WCT difference from a static quota, and its decrease path never runs.
6. Under one constructed DRAM constraint, DAG Slack keeps the critical checkpoint (23.97 vs 134.79 ms). This is post hoc and shows only that the mechanism can work.
7. Native first-four-layer distinct coverage at K = 16 is 4–8%, so the design's "misses are few" is unsupported, and Current does not consistently beat Recency.
8. At interference coefficients 0.05 and 0.1, healthy cost exceeds this single fault's cohort benefit at every failure probability.

The evidence cannot support claims that:
- Slack selection, Top-K×L HBM, or AIMD adaptation improves workflow completion;
- protection is free in healthy operation;
- the results carry over to continuous batching, multi-call Agents, or physical overhead.

## (d) Verdict and essential repairs

**NOT READY.** The null results are legitimate, and much of the section is admirably transparent: the retained negative penalties in Figure 8, the routing counterexample, and the structural reversals. But a reader would believe the section tests AegisKV's distinctive mechanisms. It actually tests generic DRAM checkpointing, while the mechanisms are switched off by configuration: dense attention, λ = 10 ms, zero interference, and a quota that never binds.

None of these repairs requires a new experiment:

1. Correct the Static-HBM/AegisKV sentence. Report the quota-pressure null result, or state that quota adaptation is untested.
2. State that the primary uses `compute_dma_slowdown = 0`, and define the low-DMA dose.
3. Report the predictor's bias, the drop from out-of-fold to held-out gain, and the load confound. Add the near-invariance under the predictor swap.
4. Define checkpoint coverage by commits. Attach the service-proxy caveat and the 52-of-52 contrast to the 4.58–4.66% saving.
5. Report the reversal counts, the 8B ρ = 0.9 N4 case, and the difference in retry workers between restart and checkpointing.
6. Report Recency at K = 16, and include or explicitly exclude the native-transfer null result.
7. Open the Evaluation by stating that Slack selection, Top-K×L HBM and quota adaptation are inactive or null in the primary replay, and that the demonstrated benefit is Agent-level DRAM recovery. Reconcile "misses are few" in `system_design.tex` with the native results.

Even with these repairs, an uncalibrated simulator on a trace that never exercises the mechanisms may fall short of EuroSys expectations. That limits what the paper can claim; it is not a reason to look for a setting that produces a positive result.
