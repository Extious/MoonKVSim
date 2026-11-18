I'll re-review the replaced package from scratch against the v2 evidence, starting with the manuscript, the package-ready manifest, and the review/disposition documents.The implementation docs claim both fixes: causal-domain selection and queued-history restore. Now the primary v2 campaign: audit, statistics, and the per-identity endpoint tables.The page PNGs cited in `VISUAL_REVIEW.json` are not in `paper-preview/`, which holds only the two JSON files. I'm searching the wider workspace for them.The renders exist; the file-search tool doesn't list them, probably because PNGs are ignored. Before viewing them, I'm checking their hashes against `VISUAL_REVIEW.json`.The render hashes match `VISUAL_REVIEW.json`. I'm now opening the actual Evaluation page images, starting with the colour renders.**Verdict: NOT READY.** As delivered, within its simulation-only scope, the Evaluation is rigorous as an audit but not persuasive as an evaluation of AegisKV. Every number I rechecked reproduces, both runtime fixes are in the code that produced all 483 runs, adverse results are kept, and all seven reporting remedies from my v1 review are in the text. The problem is what the corrected evidence shows:

- **The three distinguishing mechanisms show no WCT benefit on the natural workload.** These are Slack-based selection (O1), Peer-HBM staging (O2) and the adaptive quota (O3). The one positive O1 result is a constructed, post-hoc case worth 110.8 ms.
- **The benefit that does appear comes from DRAM checkpoint restore, which the paper itself attributes to prior work** (`motivation.tex:4`). Even that benefit is unstable at workflow level. In the constructed multi-call matrix, checkpointing worsens the faulted workflow in 6 of 10 cells. Several primary outcomes depend on which worker the retry lands on, not on reconstruction savings.
- **The frozen Design still asserts guarantees the Evaluation disproves or never tests.** A scope sentence in the Evaluation doesn't repair that.

## What I checked

- **Read-only.** I edited nothing and ran no tests or simulations. Shell use was limited to `sha256sum` and `find`.
- **Hashes.** The live `runtime.py` is `de3a9ce7…`, matching all five campaigns. `evaluation.tex`, `main.pdf` and the four figure PDFs match `FINAL_PACKAGE_READY.json`. `system_design.tex`, `motivation.tex` and `background.tex` match `FINAL_REVIEW_INVOCATION.json`, so the preceding sources are preserved.
- **Code.** I read `_demand`, the recovery layer step, `_fail`, `_admit`, `_choose_peer` and `_submit`.
- **Visual inspection.** I opened these renders as images: `paper-preview/page-7…12-color.png` and `page-10/11/12-gray.png`. Their hashes match `VISUAL_REVIEW.json`. I did not open the grayscale renders of pages 7–9 (text and Table 1) or of the reference pages 13–14.

## Resolved since v1

- **Runtime conformance.** The code now does what the package claims:
  - Recovery selects over the full causal domain, then separates checkpoint blocks from the locally recomputed tail (`runtime.py:290–299`, `1180–1195`).
  - Queued continuations lease their committed checkpoint before local state is released, and restore on the Peer. These are recorded as `history_restores`, separate from active `recoveries` (`runtime.py:1343–1416`).
  - Displaced first calls get their own wake-up (`runtime.py:1439–1450`).
  - I read the logged 74-test pass but did not rerun it. The queued-history fix affects only the constructed matrix (279 restores); single-invocation FanOutQA has none.
- **Endpoints (v1 item 3).** Target ΔWCT and interrupted-Agent latency are co-primary. Both carry the queue/service split, sink/non-sink strata, per-identity values and adverse cases.
- **O1 reporting.** The text now gives fallback counts with denominators and cause, and DRAM-vs-All-DRAM bytes under both definitions. It also gives the ±4.113 s swap and the 2.215 GiB target checkpoint that explains the zero-Slack null.
- **O2, overhead and O3 reporting.** The text adds K=16 and event comparators and says "few misses" is not supported. It states that Eq. 3's premise is not exercised and that bytes/bandwidth is local only. DMA cost is reported with a matched-objective break-even, and O3 is stated as untested.
- **Controls and provenance.** Non-crossing controls are relabelled as code-path checks, and the Z=64 coupling is stated. The copy-lag and 32/128-workflow results are labelled historical, and no v1 number appears as a corrected result.
- **Consistency.** All 18 cells of Table 1 match the source summary exactly. So do the primary, O1, DMA, sensitivity, post-hoc, structural (including seed 19) and native numbers.
- **Rendering.** All four figures and Table 1 are legible in colour and grayscale at print size, with no clipping.

## Remaining material blockers

### 1. Slack selection (O1) has no natural-workload evidence, and the natural test doesn't use the Design's predictor

**Evidence:**
- **Selection never differs for the target.** In the 32-run control, the target's protected checkpoint is 0 tokens for every variant at 2 GiB and 16,128 tokens for every variant at 4, 8 and 256 GiB (`capacity-slack-ablation-v2-corrected/binding-diagnostics.csv`).
- **Cohort WCT doesn't move.** DRAM vs All-DRAM changes it only through one ±4.113 s swap, and saves 10.21/5.70/−0.095% (8B) and 10.81/7.98/1.16% (32B) of backup bytes.
- **Slack is zero in about 56% of logged windows.** Counts are 3,122/5,586 and 3,605/6,518, all from "prediction minus age ≤ 0" (`reviews/o1-dma-corrected-v2-audit/PAPER_O1_NUMBERS_V2.md:20–21`).
- **The implementation predicts invocation service only** (`evaluation.tex:62–65`). The Design's Tracker predicts the Agent's remaining completion time, trained on submission-to-completion labels (`system_design.tex:59–81`). For single-invocation Agents the difference is the queue wait, which is exactly what triggers the fallback. So the natural-trace null tests a proxy, not the Design.
- **The positive result is a constructed witness.** It uses hand-declared priors (`slack-mechanism-posthoc-v2-corrected/PROTOCOL.md:9`) and one fault, giving 23.97 vs 134.79 ms (`reviews/POSTHOC_SLACK_V2_INDEPENDENT_REVIEW.md:39–45`). That is about 0.1% of a workflow whose critical branch alone runs 98.7 s (`PROTOCOL.md:31`).

**Smallest remedy:**
- **Implementation correction:** implement the Design's Tracker target, trained on the 12 training workflows' healthy runs. Add a noncausal oracle-Slack variant as an upper bound.
- **Additional simulation:** one pre-declared natural-workload contention run. Size DRAM budgets so that at least two candidates compete at the retry Peer, as the post-hoc preflight did. Fail each Agent whose protection differs between zero, proxy and oracle Slack, and report all outcomes.
- **Claim narrowing, if still null:** O1 becomes "up to about 11% less backup traffic at equal WCT, vanishing at high load", and the λ sentence in the Design changes.

### 2. Peer-HBM staging (O2) never matters, and block selection is never exercised in a WCT run

**Evidence:**
- **The gains are sub-millisecond against second-scale queues.** Target gain is −0.0026 to 1.442 ms (8B) and 0 to 0.137 ms (32B) (`evaluation.tex:139–140`). Agent-latency gain is 0.027–0.508 ms (Table 1). Structural gain is under 0.875 ms, and the H2D sweep gives 0.72–5.78 ms. Mean DRAM retry queues are 0.30–1.79 s.
- **Top-K is degenerate under dense demand.** Access counts are monotone in block age and ties go to earlier blocks, so every WCT run keeps simply the first K blocks (`reviews/DESIGN_CONFORMANCE_SPOTCHECK.md:49`). The decay/hysteresis selector, the depth rule and G ordering are therefore untested in WCT.
- **At the deployed K=16, the offline selector doesn't beat recency.** Distinct coverage equals or trails recency for all three models. Event coverage trails it for two: NSA 11.46 vs 15.44%, MiniCPM 5.37 vs 11.45% (`reviews/native-topk-operating-point/RESULTS.md:7–8, 25–26`).

**Smallest remedy:**
- **Additional simulation, with a small implementation change:** replay the sealed native selector traces through the existing `demand_provider` hook (`runtime.py:294–299`). Run at a bandwidth-bound point (H2D 8–16 GB/s, where DRAM penalties are 135–284 ms) with the L and K the depth rule gives.
- **Claim narrowing, otherwise:** say that O2 saves at most L·K block transfers (≤1.44 ms here) and that the selector doesn't beat recency at K=16.

### 3. The adaptive quota (O3) is untested because the simulator lacks the pressure it responds to

**Evidence:**
- Static-HBM equals AegisKV in every primary row (e.g., `stratified-summary.csv` lines 2 vs 14 and 77 vs 89).
- The quota grew 4 times and never shrank for 8B, and never changed for 32B (the evidence cited in the unapplied `PROPOSED_CLAIM_CORRECTIONS.md`).
- The Evaluation itself says FCFS cannot test it (`evaluation.tex:141–143, 367–368`). Yet the Motivation presents adaptation as one of three requirements (`motivation.tex:75–82`).

**Smallest remedy:**
- **Additional simulation:** a stress setting where the ceiling binds and moves, e.g., per-rank HBM near the foreground high watermark. Compare the Adapter with several fixed quotas on WCT and reserve violations.
- **Implementation correction:** continuous batching, for a realistic version.
- **Claim narrowing, otherwise:** present the Adapter as a safety mechanism with unverified benefit.
- **Future physical evidence:** real batch-pressure traces, for any positive claim.

### 4. WCT differences are driven by retry placement and FCFS ordering, and the text under-reports adverse cells

**Retry targets depend on the policy.** The retry goes to the checkpoint holder, or for Restart to the designated Peer (`runtime.py:1418–1429`). Both come from `_choose_peer`, which breaks ties by existing checkpoint counts:

```409:421:/home/comp/zhanzhao/MoonKVSim/python/moonkvsim/aegiskv/current/runtime.py
    def _choose_peer(self, source: int) -> int | None:
        candidates = [w for w in self.alive if self.config.hosts[w] != self.config.hosts[source]]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda w: (
                len(self.queues[w]) + int(self.busy[w] is not None),
                sum(cp.peer == w and not cp.retired for cp in self.checkpoints),
                -self.ledgers[f"dram:{self.config.hosts[w]}"].bytes_in("FREE"),
                w,
            ),
        )
```

Two current runs show the effect on the S5 identity (run suffix `F1-4`):
- **32B ρ=0.9:** Restart and All-DRAM retry on worker 5, DRAM on worker 6 (`runs/Qwen3-32B-load0.9-{none,all_dram,dram}-F1-4/summary.json`). The retry queue is 5.27 vs 1.16 s. This one identity supplies 0.83 s (64%) of the 1.30 s mean target improvement at that cell.
- **32B ρ=0.3:** Restart retries on worker 2, DRAM on worker 3, and the retry queue rises from 3.83 to 5.28 s. This is the "worst identity" regression at `evaluation.tex:128–129`.

**Retries never preempt:**

```911:913:/home/comp/zhanzhao/MoonKVSim/python/moonkvsim/aegiskv/current/runtime.py
    def _admit(self, worker: int) -> None:
        if worker not in self.alive or self.busy[worker] is not None or not self.queues[worker]:
            return
```

So the "retry queue" that makes up 62–91% of DRAM Agent latency is the wait for the Peer's in-flight invocation to finish. The text doesn't say this.

**Structural results are mostly adverse, and the text omits the worst cells.**
- DRAM worsens the mean target penalty in 6 of 10 cells (`structural-campaign-v2-main/figures/wct-endpoint-comparisons.csv` lines 2, 6, 8–11):
  - Skewed prefill: −14.43 s.
  - History-reuse prefill: −12.05 s.
  - Long-decode: −30.62 s (prefill fault) and −21.24 s (decode fault).
  - Shared-host: −30.00 s (prefill) and −41.01 s (decode).
- DRAM worsens the all-workflow mean in 2 of 10 cells (lines 12 and 19): skewed prefill (−2.89 s) and long-decode decode (−6.63 s).
- Single-seed extremes range from −425.8 s to +217.4 s.
- The text (`evaluation.tex:208–237`) shows only the reversals where the cohort improves. It omits the cells where both endpoints worsen, including seed-19 long-decode: +49.70 s on the target and +15.34 s on the cohort (`structural-campaign-v2-main/PAPER_NUMBERS_V2.md:57–69`).

**Statistical power is thin.**
- Each primary cell has 5 identities, and 3 of them are sinks with at most 100 tokens to rebuild.
- 8B ρ=0.3 and 0.65 give identical target values (`stratified-summary.csv` lines 53/68 and 56/71).
- Structural cells have 3 seeds, and there is no measured noise floor.

**Smallest remedy:**
- **Claim narrowing (text only):** state the 6/10 and 2/10 counts, the retry-queue mechanism, and the S5 retry-worker attribution.
- **Implementation correction plus additional simulation:** fix each identity's retry worker across policies, or drop the checkpoint-count tie-break, and rerun the 180 primary runs.
- **Additional simulation:** a same-policy perturbation control (e.g., shift one unrelated event by 1 ms) to measure ordering noise. Add enough identities and seeds for paired intervals, e.g., all 62 primary workflows as targets and at least 20 seeds per structural cell.
- **Implementation correction (larger):** a preemptive-retry or continuous-batching foreground model.

### 5. Healthy overhead is zero by assumption and adverse under the only interference model

**Evidence:**
- Primary healthy WCT is identical across policies only because the modelled DMA slowdown is zero (`evaluation.tex:143–146`).
- At slowdown 0.05 and 0.1, AegisKV's cohort break-even p is 1.529 and 1.494. The same rows show the four-workflow total finishing 0.39 and 0.74 s later than Restart even in the failure run (`reviews/o1-dma-corrected-v2-audit/dma-scenarios.csv` lines 8 and 12). The text reports only p > 1.
- The Design says "Normal execution pays little … Unprotected Agents incur no cost" (`system_design.tex:522–523`).

**Smallest remedy:**
- **Additional simulation:** sweep the slowdown coefficient from 0.002 to 0.02 to locate the break-even coefficient, and report healthy D2H bytes per second per host.
- **Claim narrowing:** replace "pays little" with the measured traffic and that break-even condition.
- **Future physical evidence:** measured copy interference on the target GPUs. For a fault-tolerance design this is first-order.

### 6. The evaluated regime is not the one that motivates the design

**Evidence:**
- The primary workload is single-invocation Agents with gold outputs. Multi-call evidence comes only from constructed four-Agent DAGs, and there are no idle gaps between invocations (`evaluation.tex:31–49, 361–362`).
- The 40,960-token bound excludes 86 of 160 workflows (`evaluation.tex:35–36`). The Motivation's cost case is at 1M tokens (`motivation.tex:13–16`).
- There is one cluster size, and the larger controls are historical only.
- Only internal variants are compared; there is no prior-work baseline (`evaluation.tex:78–79`).
- The recommended ≥2 real trace families, DP 4–64 sweep and load-aware baseline in `LITERATURE_AND_DESIGN.md` were not implemented.

**Smallest remedy:**
- **Implementation correction plus additional simulation:** add idle gaps and replay one natural multi-call trace family. The Motivation's own trace (`motivation.tex:30`), with inferred DAGs, is a candidate. Also add contexts up to the 98,304-token profile bound, one DP scale sweep, and a DéjàVu-style streaming baseline.
- **Claim narrowing, otherwise:** restrict conclusions to shallow single-invocation workflows under 41k tokens on 8 workers.

### 7. The delivered paper contradicts itself

| Frozen Design statement | Evaluation | In unapplied proposals? |
|---|---|---|
| λ bounds an unprotected Agent's added delay (`system_design.tex:243–245`) | not a guarantee (`evaluation.tex:373–374`) | Yes (#1) |
| G ordering "removes the most delay" (486–487) | a 1.10 ms local gain becomes +3.40 s globally (193–203) | Yes (#2) |
| Tail of at most Z (273, 289, 369, 407) | can exceed Z; historical evidence only (370–372) | Yes (#3) |
| "Misses are few"; no-wait depth rule (380–381) | 4–8% distinct coverage at K=16; premise not exercised (341–345, 364–366) | Yes (#4) |
| Spare HBM varies, so the quota must adapt (535–536) | Static-HBM equals AegisKV (141–143) | Yes (#5) |
| "Normal execution pays little" (522–523) | adverse at 5–10% modelled slowdown (307–313) | No |
| Tracker predicts remaining Agent time (59–81) | service-only proxy (62–65) | No |

**Remedy:** claim narrowing in the Design, which requires lifting the freeze, or the evidence from blockers 1–5.

## Optional improvements

- **Figure 9:** the 0–450 s shared-host range hides the 1–30 s effects elsewhere. Plot per-seed paired differences on a symmetric-log axis.
- **Figure 10(b):** the 1→256 GiB line implies a gradual change, but the real step lies between 2 and 4 GiB. Add the 2/4/8 GiB points from the capacity control, which uses identical inputs, or plot markers only.
- **Selector comparison:** report that decay plus hysteresis beats cumulative counting at K=64 (+3.15/+9.74/+2.64 points distinct; `RESULTS.md:13, 22, 31`), alongside its K=16 deficit to recency.
- **Load identity:** explain why 8B targets are identical at ρ=0.3 and 0.65.
- **Tail longer than Z:** reproduce it on the current runtime. No v2 summary records such a tail.
- **Displaced calls:** placement at `runtime.py:1442` ignores busy workers, unlike normal routing at `runtime.py:810–818`.
- **Other additions:**
  - Predictor error on the held-out split, from existing runs.
  - A worker-repair variant.
  - Z decoupled from the forward-chunk size.
- **Page budget:** there is no Introduction, Related Work or Conclusion yet, and the Evaluation ends on page 12 of 12.

## Claim-to-evidence

| Claim | Status | Deciding evidence |
|---|---|---|
| WCT | Local recovery supported in-model; workflow WCT not established | Agent latency falls 16–52% in all 6 cells. Target improves in 5 of 6 cells (two identical) but worsens at 8B ρ=0.9. Structural target worsens in 6 of 10 cells. |
| Slack | Not supported naturally | About 56% of windows fall back; zero-Slack WCT is identical; one 110.8 ms witness |
| HBM | Not supported | ≤1.44 ms target gain; can reverse globally |
| Selection | Traffic only; block selection unexercised | ≤10.8% bytes saved; dense runs keep the first K blocks |
| Quota | Untested | Static-HBM equals AegisKV everywhere |
| Prediction | Unvalidated; not the Design's predictor | Service proxy; no error measured; non-crossing controls |
| Healthy overhead | Assumed zero; adverse when modelled | +3.3/+6.7% healthy WCT; cohort worse even with the failure |
| Scalability | No current evidence | 8 workers; larger runs historical |
| Native demand | Offline only; contradicts "few misses" | K=16: 4–8% distinct, 5–16% events |

**Two corrections to my v1 review.** First, I said that with one failure only the target's own protection can change its WCT. That was too strong: other Agents' checkpoints change `_choose_peer`'s tie-break and hence the target's retry worker, and queued-history restores also use checkpoints. The 32-run null still holds, because the target checkpoints and all workflow WCTs are identical. Second, the L·K·(block bytes)/bandwidth term bounds local recovery service only, not WCT once routing changes.
