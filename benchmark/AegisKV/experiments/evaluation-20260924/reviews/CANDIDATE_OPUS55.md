I'll start by locating the Evaluation source, protocol, review disposition, and campaign artifacts, then work through the underlying configs, code, and figures.Hashes of `evaluation.tex`, `main.pdf`, `system_design.tex`, and the four Evaluation figures match the recorded invocation. Next I'm viewing the rendered Evaluation pages.I've viewed rendered pages 7–13 (color). Now reading the frozen System Design and Motivation to check Evaluation/design conformance.The rendered pages are readable. Next I'm checking the frozen runtime in the formal-core snapshot for recovery semantics, dense-attention demand, and the Agent-selection rule.I have enough primary-replay evidence. Instead of retrying flaky shell calls, I'll read the remaining campaign results files directly.I have the evidence I need. Before writing, I'm re-reading the exact wording of the HBM-increment attribution and the Static-HBM statements so I quote them accurately.I now have the exact manuscript wording. One final lookup gets exact line numbers for the two code citations I'll use: the dense-demand HBM residency and the tracker's fallback.Let me confirm the exact context of my earlier target-workflow reconstruction numbers in the transcript before citing them.## Verdict: not ready

Within its stated simulation-only scope, the Evaluation is not yet rigorous or persuasive enough for a top-tier systems submission. Its disclosure is careful, and the numbers I rechecked reproduce from the artifacts.

However, no run shows that any of AegisKV's three distinguishing decisions changes workflow completion time (WCT):
- Slack-based Agent selection (O1).
- Top-K HBM placement sized by the depth rule (O2).
- The adaptive HBM quota (O3).

The tests meant to probe O1 and O3 could not have shown a difference in this setup. The evidence supports a narrower finding: a periodic DRAM checkpoint shortens recovery of the failed workflow when the checkpoint fits and load is moderate. Several target-workflow, adverse and overhead results that bear directly on the claims are computed but not reported. Meeting the conditions below would make the Evaluation defensible; it would not guarantee acceptance.

## What I counted and inspected

- **Read-only:** I changed no files and launched no runs.
- **Counted as complete:** 180/180 primary, 135/135 main structural, 126/126 sensitivity and 32/32 capacity/Slack runs. The hashes of `evaluation.tex`, `main.pdf`, `system_design.tex` and the four Evaluation figures match `CANDIDATE_REVIEW_INVOCATION.json`.
- **Excluded, results not inferred:**
  - The two running 128-workflow structural runs (status 141/143).
  - The post-hoc DRAM/Slack diagnostic in `slack-mechanism-posthoc-v1/`. I did not read its results.
- **Rendered pages:** I visually inspected the colour renders of pages 7–13 under `paper-preview/` as images. I did not inspect grayscale renders.

## Material blockers, in priority order

### 1. Slack-based selection (O1) has no WCT evidence, and its only ablation cannot discriminate

- **The zero-Slack control gives identical WCT by construction** (`evaluation.tex:254–264`).
  - `capacity-slack-ablation-v1/binding-diagnostics.csv` shows the target's protected checkpoint is 0 tokens under every variant at 2 GiB. It is 16,128 tokens under every variant at 4, 8 and 256 GiB.
  - With one failure per run, only the target's protection can change WCT, so equality was fixed before the runs.
- **At 2 GiB and below, no policy can protect the target.** Its own checkpoint (16,128 tokens × 147,456 B ≈ 2.2 GiB) cannot fit.
  - This also covers Figure 10(b)'s 0.25 and 1 GiB points.
  - The text calls these points a "capacity boundary" (`evaluation.tex:249–252`) without saying this.
- **Slack is off most of the time under load.**
  - The Tracker zeroes Slack for the whole workflow when any started Agent's prediction minus its age is ≤ 0 (`formal-core-v1/source_snapshot/python/moonkvsim/aegiskv/current/tracker.py:106–118`).
  - Age counts from submission, so it includes queue wait. `CausalLengthPredictor` predicts service time only.
  - Healthy DRAM runs log 21,088 fallback observations at 8B ρ=0.3 and 376,685 at ρ=0.9 (32B: 20,487 → 307,099; `formal-core-v1/run-metrics.csv`).
  - In the one run with detailed logs (8B, ρ=0.65), my approximate reconstruction puts about 56% of active workflow windows in fallback.
- **The consequence is in the data but unreported.**
  - DRAM copies 10.3% fewer backup bytes than All-DRAM at 8B ρ=0.3, but 0.07% more at ρ=0.9. For 32B the saving shrinks from 10.9% to 1.2%.
  - Even at low load, selection skips only about a tenth of the bytes.
  - The DRAM-versus-All-DRAM contrast, which isolates the protection threshold, is never reported.

**Smallest remedy:**
- Report the fallback share and DRAM-versus-All-DRAM bytes and WCT per load. These exist already.
- Then choose one:
  - Add a discriminating experiment. Under binding DRAM (e.g., 4 GiB), fail each Agent whose protection differs between Slack and zero Slack, and report every outcome.
  - Restrict O1 to "reduces backup traffic at low load; no WCT effect shown".
- The pending constructed diagnostic can at most show the mechanism can matter in one case. It must be labelled post-hoc and cannot substitute for that experiment.

### 2. The HBM tier (O2, depth rule) is measured only where its gain is a fixed transfer-time identity, and native evidence contradicts "misses are few"

```563:574:/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v1/source_snapshot/python/moonkvsim/aegiskv/current/runtime.py
        cp = state.checkpoint
        blocks = (cp.frontier if cp else state.computed) // c.block_tokens
        required = (
            blocks if c.attention == "dense" else min(blocks, c.synthetic_selected_blocks + 1)
        )
        # ... more code ...
        gpu = transfer_done = 0
        for layer in range(c.layers):
            resident = min(required, c.top_k) if hbm and layer < c.depth else 0
```

- **The HBM gain is exactly the transfer time of L×K blocks.** Dense attention demands every block, and HBM holds at most K per layer in the first L layers.
  - 11 × 16 × 256 KiB plus metadata ≈ 46.2 MB, which is 1.44 ms at 32 GB/s. That is the reported maximum (`evaluation.tex:149`).
  - The sensitivity values 5.78, 2.89, 1.44 and 0.72 ms at 8, 16, 32 and 64 GB/s are this byte count divided by bandwidth.
  - Across protected Agents in the detailed run, the HBM gain G_a has a median of 1.443 ms and a maximum of 1.447 ms. HBM admission ordered by G_a is therefore effectively a tie.
- **The depth rule's premise fails.** Eq. 3 (`system_design.tex:428–439`) assumes the first L layers start without H2D transfer.
  - K=16 holds 1,024 of the 8,704-token median context, so about 88% of each "resident" layer is still fetched as misses.
  - `evaluation.tex:190–194` attributes the small increment to "the configured bandwidth and compute costs". It is structural.
- **Native coverage contradicts "misses are few"** (`system_design.tex:380`).
  - At K=64 the current rule covers 32.8/16.8/15.5% of distinct future demand. On query–block events it covers 59.9/36.0/22.4%.
  - Recency on events is 33.8/34.4/33.8% (`native-topk-warm/RESULTS.md`). Against recency the current rule is +26.1, +1.7 and −11.4 points; the text omits these comparators.
  - At K=16, the budget used in the WCT runs, Figure 11 shows roughly 8/5/5% distinct coverage. The text reports only K=64.

**Smallest remedy:**
- State that under dense demand HBM saves at most L·K block transfers per recovery and that Eq. 3's no-wait pipeline is not exercised.
- Report the K=16 values and the event-measure recency and oracle values. Say the native evidence does not support "misses are few" at these budgets.
- Any positive O2 claim needs a sparse-demand recovery analysis, at minimum an offline timeline from native per-layer hit sets at K=16. Otherwise drop O2 benefit claims.

### 3. The primary endpoint and fault bank hide the checkpoint's effect on the failed workflow, including adverse cases

- **The endpoint is inconsistent across sections.**
  - DRAM versus restart is compared only on the 62-workflow mean (`evaluation.tex:140–147`).
  - HBM (line 149) and the structural and sensitivity sections use the target-workflow penalty.
  - The choice matters. In the sensitivity centre runs, restart → DRAM is 1.802 → 0.061 s for the target workflow but 1.113 → 0.897 s on the cohort mean (sensitivity `raw-runs.csv`).
- **Target-workflow results in the primary summaries are omitted:**
  - DRAM cuts the 8B ρ=0.3 target penalty from 0.530 to 0.062 s.
  - It worsens the 8B ρ=0.9 target mean from 1.994 to 2.071 s.
  - It worsens the 32B ρ=0.3 worst identity from 3.88 to 5.30 s.
  - `PRIMARY_8B_ADVERSE.md` leaves a 117.55 ms DRAM regression at ρ=0.65 unattributed.
- **Three of five fault identities cannot show a meaningful effect.** They are sink Agents failing at 257–356 logical tokens with a 256-token checkpoint, and their recovery service is about 25 ms (`run-metrics.csv`, 8B ρ=0.3 F1-0/2/4). Routing noise is measured in seconds: the 1.10 ms → +3.40 s example at `evaluation.tex:171–181`.
- **The aggregate penalty mostly measures post-failure overload under FCFS scheduling.**
  - After a failure at ρ=0.9, seven workers carry nominal load 0.9 × 8/7 ≈ 1.03.
  - Healthy WCT at ρ=0.9 is already 2.6× that at ρ=0.3.
  - Structural penalties of 60–400 s come from losing a quarter or half of a four-worker cluster. DRAM moves the skewed-prefill penalty only from 65.84 to 65.42 s.
  - Even favourable identities are dominated by queueing: 8B ρ=0.3 F1-3 spends 1.520 s in the retry queue and 0.675 s in service.

**Smallest remedy:**
- Make the target-workflow penalty and interrupted-Agent recovery latency co-primary endpoints, with per-identity paired values; the data exist.
- Report sink and middle identities separately, and state the post-failure load.

### 4. The foreground model cannot exercise O3 or healthy overhead, and the one interference control that could is adverse and unreported

- **The Adapter has no foreground HBM pressure to respond to.** The model is FCFS with one active invocation per worker and no continuous batching; `CONTINUOUS_BATCHING_GAP.md` is only a feasibility memo.
  - Static-HBM and AegisKV give identical WCT everywhere (`evaluation.tex:151–153`).
  - The copies that matter fit in Static-HBM's 128 MiB; one 8B copy is about 46 MB.
- **The 10% DMA-slowdown control shows a real healthy cost** (sensitivity condition-14).
  - Healthy mean WCT rises from 8.398 s (restart) to 8.957 s for DRAM and AegisKV, which is +6.7%. The maximum rises from 19.35 to 20.58 s.
  - One failure saves about 1.74 s on the target, but the healthy cost summed over the cohort's four workflows is about 2.24 s per run.
  - The text says only that absolute WCT is "retained" (lines 286–288), while line 153 says healthy WCT is identical.

**Smallest remedy:**
- Report the healthy-WCT increases at 0.05 and 0.1 slowdown and the break-even failure frequency.
- Call zero healthy overhead a modelling assumption, and state that O3 is untested.

### 5. Design-conformance gaps change what is being evaluated

```1350:1353:/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v1/source_snapshot/python/moonkvsim/aegiskv/current/runtime.py
            if state.worker in failed:
                self._release_primary(state)
                state.computed = 0
                state.worker = None
```

- **Idle histories are discarded, not recovered.**
  - `_rebalance_inner` skips Agents whose worker is dead (line 609), so their checkpoints are retired and the next invocation re-prefills from zero. The `eosfix1` runtime has the same logic.
  - `system_design.tex:498–501` says replicas stay valid across invocations and are released only when the Agent finishes or drops below λ.
  - Only the busy invocation ever restores, and co-victims count only busy requests. This affects the history-reuse and shared-host cells.
- **The Tracker gets a service-only proxy**, not the remaining wall-clock time the Design specifies. This mismatch drives blocker 1. Lines 74–79 and 340–341 disclose that the proxy is circular, not that its target differs.
- **Exposure is computed with the same profile that executes recovery.** Selection therefore sees exact reconstruction costs, an idealization that should be stated.

**Smallest remedy:**
- Disclose all three.
- For idle histories, either restore queued Agents from checkpoints and rerun the affected cells, or report how many histories each failure discarded and what rebuilding them cost.

### 6. Sensitivity controls do not cross the decision boundaries they are named for

- Each condition has one fixed identity, and the target's restart penalty (1.80 s) exceeds every tested λ.
- Prediction multipliers 0.5/2 leave the target protected. In the 200 ms TTL-expiry case, fallback sets Slack to zero, which protects everything at 256 GiB.
- The harmful staleness modes never occur: over-protection under binding DRAM, or overestimated Slack dropping a critical Agent.
- Z=64 changes compute partitioning (lines 289–292). The disclaimer at lines 284–285 is accurate, but it leaves no mechanism-level result beyond H2D bandwidth and detection delay.

**Smallest remedy:**
- Pick settings that straddle the target's exposure: λ near 1.8 s, multipliers that move it on or off the critical path, and staleness at 4 GiB. Otherwise relabel these runs as code-path checks.
- Sweep Z only from 256 up.

### 7. The workload does not exercise the regime that motivates the design

- **The primary workload is shallow.** It uses single-invocation Agents in fan-out FanOutQA with gold-answer outputs (median 5 tokens), so four of five failures fall in prefill.
- **The longest contexts are excluded.** The 40,960-token guard removes 86 of 160 workflows, and arrivals are deterministic.
- **Growing histories are tested only in constructed workloads.** The Motivation's growing-history premise (`motivation.tex:99`) appears only in the constructed matrix. Its scale controls are described (line 57) but report no results.

**Smallest remedy:** narrow the conclusions to shallow single-invocation workflows, and label the multi-invocation evidence as constructed.

### 8. One quantitative example uses an undeclared runtime

The slow-copy example at `evaluation.tex:346–349` comes from `mechanism-campaign/`, which ran `runtime.py` `9f216406…`. That is neither frozen v1 (`99250879…`) nor `eosfix1` (`fe775b16…`), the only two versions declared at lines 130–135.

**Smallest remedy:** label it as pre-freeze, or rerun it under a declared version.

**Checks that passed:**
- Byte accounting.
- Shard-complete publication.
- The earlier-block tie rule (13,824 sets match).
- Separate distinct and event denominators, not relabelled as runtime hits.
- Causal target choice.

## Open Evaluation–Design contradictions

Because the Design is frozen, each item needs its own sentence in the scope section. The current wording (lines 351–352) is too general.
- "Misses are few" (line 380) versus 15–33% distinct and 22–60% event coverage.
- The Eq. 3 premise versus dense demand.
- Replicas valid across invocations versus discarded idle histories.
- A wall-clock Tracker input versus the service-only proxy.
- O3's load-varying spare HBM (line 536) versus a foreground model with none.

## Preflight issues: resolved versus remaining

**Resolved:**
- Workload provenance (`inputs/README.md`, lines 38–49).
- Calibration disclosure, including the manifest erratum. Calibration itself is still absent.
- The EOS defect, fixed in `eosfix1`. All 120 primary checkpoint recoveries pass the boundary check; the structural runs pass 60 + 12.
- The independent numeric audit (180 summaries, 9,300 pairs).
- Retention of adverse results.

**Partially resolved:**
- Native traces: K mismatch, omitted event comparators, and no link to WCT.
- Controls: present, but none discriminates.
- Multi-call DAG evidence: synthetic, affected by the idle-history gap, scale runs pending.
- Statistics: five identities per cell, three uninformative, no estimate of the routing-noise floor.
- Disclosure: missing the DMA overhead, target-workflow results, K=16 coverage and the third runtime.

**Unresolved:**
- Continuous batching: memo only.
- Prediction: circular, service-only, mismatched with the Design.

## Necessary for approval versus optional

**Necessary:**
1. O1: a discriminating experiment or withdrawal of WCT attribution to Slack, plus fallback and DRAM-versus-All-DRAM reporting.
2. O2: recast the HBM increment as the transfer identity, add K=16 and event comparators, and state both Design contradictions.
3. Endpoints: per-identity target-workflow penalty and recovery latency, adverse cases included, stratified by sink and middle.
4. Overhead: the DMA-slowdown healthy cost and break-even, and O3 stated as untested.
5. Conformance: disclose the three gaps, and fix or quantify the idle-history effect.
6. Controls: relabel or replace the non-crossing controls, and state that DRAM at or below 2 GiB is infeasible for every policy.
7. Scope and provenance: narrower workload claims, a labelled slow-copy runtime, and pending runs kept out of the text.

**Optional:**
- A zero-cost-restore oracle per identity and a worker-repair model.
- A same-policy ±1 ms perturbation control to measure routing noise; the 32B ρ=0.9 ±4.113 s swap shows why.
- Report that decay plus hysteresis beats cumulative counts on all three models: +9.7/+2.6/+3.2 points distinct and +19.4/+20.6/+13.6 on events.
- A trace-driven multi-call workload, or larger clusters.
- A foreground-pressure model; this is needed only for a positive O3 claim.
- More than one frozen replay.

## Claim-to-evidence

- **WCT:** Narrowly supported. The failed workflow's penalty drops: 1.80 → 0.06 s in sensitivity, 34.74 → 21.71 s and 93.31 → 81.23 s in structural decode, and 0.53 → 0.06 s for the 8B ρ=0.3 target. There is no aggregate benefit: the reported primary means move by at most 9%, reverse at ρ=0.65, and shared-host prefill is adverse.
- **HBM increment:** Supported only as L·K·block bytes divided by bandwidth (≤1.44 ms). The no-wait pipeline is untested.
- **Selection:** Slack has no WCT effect; traffic falls 4.6% in the ablation and about 10% at low load, vanishing at high load. Block selection is offline only: near-oracle distinct coverage at K=64 but low in absolute terms, level with recency for NSA on events and worse for MiniCPM.
- **Quota:** No evidence. Static-HBM equals AegisKV.
- **Prediction:** No accuracy evidence. Its service-only target causes fallback, and the controls cross no decision boundary.
- **Healthy overhead:** Zero by construction. The only interference control shows +6.7%, unreported.
- **Scalability:** No evidence and no claim. Eight workers are fixed, and the scale controls vary workflow count and are incomplete.
- **Native coverage:** A sound offline diagnostic, but its results are mixed, contradict the Design, and use a different K and L from the WCT runs.

## Rendered pages

- **Fonts:** legible; the export review reports at least 10.3 pt.
- **Figure 8:** the ρ=0.9 ranges (about 0–9.2 s and 0–11.3 s) swamp the policy differences, so the five policies are visually indistinguishable. Because three of five scenarios are sink failures, it cannot show the target-workflow effect.
- **Figures 9–10:** DRAM and AegisKV largely coincide.
- **Figure 11:** its K=16 points are visible but not discussed in the text.
- **Not checked:** grayscale and colour-blind legibility.
