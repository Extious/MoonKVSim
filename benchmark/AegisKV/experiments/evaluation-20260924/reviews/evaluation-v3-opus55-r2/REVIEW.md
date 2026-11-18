I'm reviewing this as Claude Opus 5.5. First I'll read the prior review and the current manuscript files, then check each claim against the artifacts.The manuscript has been substantially revised. Next I'll inventory the primary-v3 artifacts and the review packages the claims depend on.Predictor, table, and cell-summary numbers match so far. Next I'll check the per-identity contrasts, byte comparison, Static/Aegis comparison, and V2/V3 comparison.Unsandboxed Python was declined, so I'll finish the verification with file reads and text search only.Healthy V3 commits match the paper: DRAM commits 25,414–25,437 against All-DRAM's 25,437, at most 23 fewer. Next are the quota columns for all 36 AegisKV runs.The 8B quota columns match the paper: 4–10 increase events, 0 decreases, 0 pressure events, and a maximum of 192 or 256 MiB. The 32B rows were cut off, so I'm extracting only those fields.The two DRAM F0 event logs are gzip-compressed. I'll try a read-only `zcat` count of per-Agent checkpoint commits.The sandbox worked this time: 2,644 commits, 52 predictions, and 52 submits. Now I'll count distinct Agents with at least one commit in both logs.The sandbox failed to start again, so I'll retry the same read-only count once.The K=64 values in `RESULTS.md` match the text. Now the K=16, L=4 rows.DRAM versus All-DRAM shows zero nonzero-gain workflow pairs across all 30 fault cells, which confirms the paper's claim. One last check is whether the visual-review gate is still open.Both V2 and V3 swap-case run directories exist under the expected names. One last sanity check: the "zero non-identical DRAM versus All-DRAM pairs" result only means something if those rows exist.**Reviewer model: Claude Opus 5.5.** I edited nothing and ran only read-only commands.

**Outcome:** Evaluation is **NOT READY**, but only narrowly. Two sentences in `evaluation.tex` state a false mechanism, and each needs a one-sentence fix. The prior review's errors are gone, and every number I checked matches the artifacts. In the front matter, one Abstract sentence goes beyond the evidence; the other issues are wording.

## Confirmed remaining errors

**1. Why the predictor swap changed one exchange** (`paper/evaluation.tex`, lines 85–87). The text says the ±4.113 s exchange happens "because the retry moves from worker 6 to worker 5, not because a different set of Agents is protected." The second clause is false. The event logs for the 32B ρ=0.9 fault-4 run (`Qwen3-32B-load0.9-{dram,all_dram}-F1-4`) show:
- **Service proxy** (`formal-core-v2-corrected/runs/`):
  - DRAM checkpoints 484 of 503 Agents (25,136 commits); All-DRAM checkpoints 498 (25,580).
  - DRAM's target retry runs on worker 6, with a 1.160 s queue.
- **Regressor** (`walltime-primary-v3/runs/`):
  - DRAM checkpoints 498 Agents (25,577 commits).
  - It retries on worker 5 with a 5.274 s queue, as All-DRAM does under both predictors (`paper-summary/v2-v3-placement.csv`).

The target has a 256-token checkpoint under both predictors. So the swap did change the protected set, and the worker move comes after that change. More broadly, healthy service-proxy DRAM runs committed 22,640–25,455 checkpoints, against 25,414–25,437 under the regressor.

**2. Why the 8B adverse case happened** (lines 248–250). "Restart and checkpointing retry on different workers in such cells" is false for the 8B ρ=0.9 N4 case cited just before it:
- Restart and DRAM both retry on worker 5 after the same 2.174 s queue.
- DRAM's service time is 0.675 s against 2.450 s (`paper-summary/per-identity.csv`, rows 55 and 65).
- The target penalty is 1.310 s under restart and 3.536 s under DRAM, so the loss happens after recovery.

Only the 32B case (workers 3 and 6) is a retry-placement difference. The Conclusion's "retry placement and later routing" is the accurate wording.

## Worth fixing, but not blockers

- **Low-DMA charge (line 378).** "Increased by the coefficient" should say the charge is ⌈base duration × coefficient⌉ (`reviews/low-dma-reporting-errata-v1/README.md`).
- **Component replay (lines 443–446).** Only Current's single win is reported. By three-document means, Current ties Recency in 19 of 36 cells and is slower in 16, by up to 1.505 ms (NOSA, 8 GB/s, 2,560 µs). Sources: `native-transfer-paper-summary-v1/SIGN_COUNTS.json` and `model-bandwidth-compute-summary.csv`.
- **Quota diagnostic.** The decrease branch did fire twice, in the margin-32 adaptive healthy runs at DMA 0 and 0.005. Each cut the quota from 32 MiB to 24 MiB at 11.3 s, after the target had finished (`reviews/quota-pressure-independent-final-v1/ADAPTIVE_DECREASES.json`). The text doesn't deny this, but it should say it.
- **What the Slack null can show.** All 30 DRAM fault targets hold a checkpoint of 256, 5,376, or 16,384 tokens (`per-identity.csv`). No fault ever hits an Agent that Slack left unprotected, and with zero DMA interference the skipped copies would have cost nothing. The Slack null therefore can't reveal either risk or benefit; one sentence should say so.
- **Duplicate sentence.** "The regressor has no load or queue feature" appears at line 75 and again at lines 79–80.

## Verified as fixed or matching

- **Framing:** the opening null statement.
- **DMA coefficient:** the config has `"compute_dma_slowdown": 0.0`. Healthy WCT is 6.23–16.65 s and identical for all five policies.
- **Predictor:**
  - MAE 2.027/2.201 s against 2.073/2.248 s.
  - Bias −1.515/−1.524 s, and −3.118/−3.103 s at ρ=0.9.
  - Gain 6.5/8.7% out-of-fold against 2.2/2.1% held out.
  - Swap counts 11/150 and 16/11,160.
- **Checkpoints and HBM:**
  - Commits 25,414–25,437 of 25,437.
  - DRAM and All-DRAM differ in 0 of 1,860 workflow pairs; Static-HBM and AegisKV are equal in 2,232 of 2,232.
  - Quota maxima 192/256 MiB on 8B and 128 MiB on 32B, with no decreases and no pressure events.
  - HBM increment 3 ns–1.444 ms (8B) and 0–0.137 ms (32B).
  - Fallback 3,426/5,586 and 3,826/6,518.
- **Routing and placement:**
  - Routing counterexample: 8 workflows gain 1.10 ms, one loses 3.41 s, 53 are unchanged.
  - 32B ρ=0.3: queue +1.453 s, service −29 ms.
- **Auxiliary results:**
  - Capacity checkpoints 45/52 against 52/52.
  - Low-DMA exposure 78.81/78.77%, with the healthy-cost, gain, and break-even values.
  - Native coverage at K=16 and K=64.
  - Component replay: 1 of 36 cells, +123 µs, 0.538 ms.
- **Attribution:** every auxiliary campaign now names which predictor it used.

## Hypotheses (not verified)

- The service-proxy retry on worker 6 is caused by the 14 extra unprotected Agents, through peer occupancy or exposure-ordered checkpoint scheduling. I compared counts only, not whether DRAM and All-DRAM protect the same 498 Agents under the regressor.
- The 8B N4 loss comes from the workflow's later invocation being routed differently after the earlier recovery.
- The 58.7–61.3% zero-Slack fallback reflects the −1.5 s prediction bias.

**Not re-verified:**
- The structural and sensitivity campaign numbers.
- `main.pdf` visually. It was built after every `.tex` file, but `PAPER_POSTPROCESS_COMPLETE.json` still reads `NUMERIC_COMPLETE_VISUAL_REVIEW_PENDING`.

## Verdict 1: Evaluation is NOT READY

Both errors are false mechanism claims. The first sits in the predictor-swap statement your READY criteria explicitly require. The essential text repairs:

1. **Lines 86–87.** Replace everything from "because the retry…" with: "Under the service proxy, DRAM checkpointed 484 of 503 Agents in that run against 498 under All-DRAM, and its target retry ran on worker 6. Under the regressor, DRAM checkpoints 498 and retries on worker 5, as All-DRAM does. The service-proxy threshold therefore changed the protected set, and for DRAM its only workflow-level consequence was this zero-sum exchange."
2. **Lines 248–250.** Replace "Restart and checkpointing retry on different workers in such cells" with: "In the 32B case restart and DRAM retry on different workers; in the 8B case both retry on worker 5 after the same 2.174 s queue, and the loss arises from routing after recovery."

With those two changes, I would judge the section READY.

## Verdict 2: one front-matter sentence exceeds the evidence

**Abstract:** "Under the evaluated completion-time predictor, the slack threshold changes almost no checkpoints, peer HBM changes a target workflow by at most 1.444\,ms, and the quota never shrinks."

Under that same predictor, the quota shrank in two diagnostic runs (32 MiB to 24 MiB). Change it to "never shrinks in the primary replay."

These are imprecise but don't claim more benefit than the evidence shows:
- **Related Work:** "…a budget of $K=16$ covers only a few percent of distinct blocks and does not beat a recency policy." This overstates the negative: NOSA's event coverage is 15.70% for Current against 15.18% for Recency. Limit the claim to distinct coverage and the component replay.
- **Conclusion:** "Peer HBM adds at most 1.444\,ms to that target." This reads as added delay, but it is a gain of at most 1.444 ms.
- **Related Work:** "a fixed Top-$K$ depth." K is the number of blocks per layer; L is the depth.
- **Introduction:** "it never shrinks." Make "in the primary replay" explicit.
- **Abstract:** it omits zero modeled DMA interference, which the Introduction and Conclusion state.

Everything else I checked in these four sections holds:
- The "shortens … latency" claims in the Abstract and Conclusion hold for all six cell means, although one identity (32B ρ=0.9 N4) is 9.4 ms worse.
- The motivation numbers, 0.956 s to 0.488 s, 3.40 s, and 4–8% coverage all match.
- The contribution bullets are scoped, and every citation key resolves.

Outside these four sections, `system_design.tex` line 214 ("the few KV blocks that recovery would otherwise wait for") contradicts the Introduction's "does not assume that misses are few" and the 4–8% coverage result. Lines 380–383 of that file are already correct.
