I'll read the previous review, the manuscript sections, and the new mechanism-decision artifacts, then check each new numeric sentence against the artifacts.
Now the new cell's protocol, summary, and oracle inputs.
The target-penalty values in `SUMMARY.json` match the text. Next I'm checking the protocol (predeclaration, arms) and per-run summaries for the peak, commit-set, mean-WCT, and N4 recovery numbers.
The 7.98 GiB peak checks out (`dram:2` = 8,570,525,184 B against an 8 GiB cap). I'm locating the per-workflow WCT and per-Agent checkpoint fields in the summaries.
N4 is fault F1-3, and its restore/rebuild/service numbers match. The oracle's N4 retry queue is also longer (1.070 s vs 0.159 s). Now I'm checking the other four faults' recovery records across arms.
The per-run summaries have no per-Agent checkpoint field. I'm searching for whatever produced the "498/391 Agents" and healthy-mean figures.
The script also writes `events.jsonl.gz` per run, but the file listing didn't show any. I'm checking whether they're ignored rather than missing.
The unsandboxed read was declined, so I'll verify from the uncompressed summaries only. Checking whether they carry any per-Agent checkpoint data.
I'm Claude Opus 5.5. I made no edits and ran no simulations. I checked the new sentences against `mechanism-decision-v1/`: `PROTOCOL.json`, `SUMMARY.json` and all 18 per-run `summary.json` files. I could not open the gzipped `events.jsonl.gz` logs, because the sandbox fails on this kernel and you declined the unsandboxed read. The per-Agent checkpoint counts are therefore unverified.

**1. Verdict: NOT PAPER-READY**

**2. Do the numbers in the binding-budget section match?**

Most do:
- The 15.0 GiB peak (15.048 in the protocol), the third coefficient, and the 0.910 s guard.
- The oracle's definition: guard 0, durations not refit.
- The 7.98 GiB healthy peak (8,570,525,184 B).
- All ten target penalties.
- N4's 16,384 restored and 160 rebuilt tokens (16,544 total), and its 2.467 s versus 0.681 s service time.
- The healthy means. I recomputed them from the 62 healthy workflow times: 16.6151 s versus 15.7129 s, and All-DRAM minus DRAM is 0.0964 ms.

One sentence does not match:

> "Service stays within 0.021 ms of DRAM, and the added target delay is retry queue."

- For N2 (fault F1-1), the retry queue grows only from 58.9 to 79.0 ms, yet the target penalty grows by 1.294 s. The other 1.27 s arises after recovery.
- The sentence does hold for the three sink faults, where the queue increases (0.523, 1.350, 2.522 s) equal the penalty increases.
- The largest service gap is 21.4 µs (F1-0), so "0.021 ms" is rounded down.

Three counts cannot be checked without the event logs: "the same 498 of 503", "391 of those 498", and therefore the "107" in the abstract and conclusion. The healthy commit totals (26,764, 26,765 and 21,610) point the same way.

**3. Decisive remaining gap**

This cell is the first one that actually exercises Slack selection. It is reported only on the endpoint that disfavors the oracle, and the conclusion generalizes from that. The same summaries show more (my arithmetic from the per-workflow completion times):
- **Different baselines.** Healthy per-workflow completion time differs between the DRAM and oracle arms by −16.6 s to +12.2 s. Each arm's target penalty is measured against a very different healthy run.
- **All-workflow outcome under failure.** The oracle's mean over all 62 workflows is lower in all five faults.

| | F1-0 | F1-1 | F1-2 | F1-3 | F1-4 |
|---|---|---|---|---|---|
| Oracle (s) | 25.07 | 22.42 | 17.14 | 16.85 | 15.93 |
| DRAM (s) | 25.47 | 23.39 | 18.96 | 18.34 | 16.62 |

- **Other endpoints.** The oracle's paired all-workflow penalty is lower in 3 of 5 faults, and its absolute target-workflow time is lower in 3 of 5.
- **The paper's own break-even rule.** Apply the Evaluation's pD−H rule to the all-workflow objective. DRAM costs H = 0.902 s more when healthy and saves D ≈ −0.17 s of fault penalty, so DRAM never beats the oracle at any failure probability p.
- **Causes.** Only N4's increase involves a protection decision. The other four come from retry placement or later routing.

*Text-fixable (enough for a narrow claim):*
1. Correct the N2 sentence.
2. For this cell, add the all-workflow results, the absolute failure-case times, and the pD−H break-even. Limit "that shrinkage increases the target penalty" to N4.
3. In the conclusion, replace "A positive claim for Slack selection would have to survive a predictor that separates Agents. In the one binding-budget cell, an oracle that does so increases every target penalty." with a trade-off statement. Make matching edits in the abstract and contribution 3.
4. In the abstract, change "matches protecting every Agent" to "matches All-DRAM". Under the cap, All-DRAM also skips 7,810 checkpoint admissions.
5. Contribution 1 still claims Top-K×L HBM and the quota, and contribution 3 calls their null a "result". Yet the section says the cell "does not speak for" them, and the primary replay "cannot distinguish" them. Label both as specified but not exercised, and remove them from the evaluated contributions.

*Experiment-required (only if HBM or the quota remain claimed contributions; no sealed artifact contains either run):*
- **HBM.** Run one workflow-completion cell driven by native-selector demand. Every sealed completion-time run uses dense Qwen compute; the only non-dense demand is the synthetic long-decode banks, which K=16 fully covers. Use an effective H2D bandwidth at which the depth equation gives L > 1, and compare DRAM with AegisKV on the same five faults. `native-transfer-postreview-v2` measures components only.
- **Quota.** Run one cell where a fault lands inside a foreground memory-pressure window, and compare AegisKV with Static-HBM. The 72-run quota diagnostic records pressure in 0 of 36 faulted runs.

A noise floor and physical calibration are not decisive once every claim is limited to this deterministic, uncalibrated cell.

**4. Not applicable.**

With fixes 1–5, the Evaluation would support a narrow claim. DRAM checkpoint-and-replay shortens the interrupted Agent's recovery. The evaluated predictor does not separate Agents. In one uncalibrated cell, oracle selectivity raises target penalties but lowers healthy and failure-case completion time across all workflows.