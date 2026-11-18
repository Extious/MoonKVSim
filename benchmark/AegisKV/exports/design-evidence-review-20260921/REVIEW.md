# System Design: motivation and figure evidence review

User request: enrich Controller, justify the rental algorithm from a real problem, and make every Design figure support its associated claim. This review treats reasonable data as traceable observations or explicit, reproducible model inputs, not numbers selected to produce a favorable story.

## Main findings

1. **Rent is motivated but not validated as a superior policy.** Fixed capacity, heterogeneous saved delay/size, unknown future use, and changing demand motivate a cost/size-aware, renewable ordering. The new retention-value example proves that Slack alone cannot provide that ordering. Landlord provides a known pressure-aging accounting mechanism. Neither fact proves the adapted controller superior to direct current-value revaluation. The already-published isolated stream has 396 revaluations for both policies, with total modeled costs 462.96 for direct value and 506.39 for trial rent. These negative results remain in Evaluation and are now explicitly acknowledged in Design.
2. **Figure 5 did not establish GBDT accuracy.** Its six feature associations are weak with intervals crossing zero. Replotting existing workflow-held-out predictions gives MAE 438.6/406.7/407.1 s for median/basic/history. Basic-minus-median MAE has conditional paired-workflow 95% interval [-80.9, 4.9] s. Only 36.5% of basic predictions have APE <= 50%. Labels cover the whole remaining Agent, including gaps; they are not residual-segment labels. The revision preserves all samples and error tails and states the zero-Slack fallback for unvalidated segment forecasts.
3. **Sparse coverage needed an oracle reference.** At equal 40% physical-block budget, past-frequency mean coverage is 77.82/53.57/43.02%, while same-budget oracle coverage is 93.75/58.98/43.28%. The Seer result is near its capacity-constrained upper bound for the future-query union. Low coverage alone cannot be interpreted as a large predictor error.
4. **Architecture detail must show actual responsibilities and state.** The three bands remain Application / Controller / Engine. Controller now exposes GBDT→CPM/Slack, layer-I/O and WCT cost, separate D/S credits, a joint DAG check and reservation, Router load/locality and fencing/retry, and directory manifests/log/leases. GPU/HBM worker boundaries remain separate from shared backing.

## Sources and checks by figure

The figure numbers below are from the compiled revision. Primary arithmetic/provenance results are in `review/AUDIT.json`; raw per-Agent errors and model inputs are in `data/`.

| Figure | Provenance / independent object | Checked support | Remaining boundary |
|---|---|---|---|
| 3, native KV prediction | `experiments/data/design-insights/retry-kv-documents.csv` and `retry-kv-summary.json`; three PG19 documents/model, one recorded native capture/document | Means/ranges and oracle values match retained rows; all methods respect oracle bounds at identical budget and mandatory-state conventions | No new forward or fault replay; not a population-wide or 1M Agent recovery result |
| 4, Overview | Native `sources/system-overview.drawio`, generator `build_overview_controller_detail.py` | Explicit bands, symmetric resources, legal endpoints, modeled state and decision ownership | Design specification, not implementation or low-overhead evidence |
| 5, Tracker | `agent-time-early/landmarks.csv`, `agent-gbdt-steps/primary-landmark.csv`, existing `protocol.json` | All 1,443 IDs/targets match; 170 workflows; one request-2 snapshot/Agent; rechecked correlations, all errors and summary metrics; five workflow folds; 2,000 paired workflow-bootstrap draws with fitted predictions fixed | Completed Subagents only, no chronological validation; proxy lengths and missing semantics; no segment/Slack accuracy proof |
| 6, locality | `agent-prefix-reuse/same-model-reuse-scope.csv`, `audit.json` | 98,827 requests/2,090 agents/393 workflows; full token-proxy denominators; exclusive shares sum to total; same/cross bars overlap | Potential within-workflow/model prefix reuse, not actual hits, cross-workflow matching or WCT savings |
| 7, retention value | `data/retention-value.csv`, `render_design_evidence.py` | A: (4→2 s, size 2, Slack 0) saves 1 s/unit; B: (18→8 s, size 1, Slack 6) saves 10 s/unit; complete curves from explicit positive-part formula | Constructed conditional isolated-fault example; no normal-use term; not a rental comparison |
| 8, sparse recovery | Updated native `sources/sparse-recovery.drawio`; `build_design_columns.py:sparse` | Panel (b) explicitly refers to layer 1, whose B2 is on SSD and B0/B3 are on DRAM | Illustrative selector mismatch; not a miss-rate measurement or full correctness test |
| 9, pipeline | `model_storage_overlap.py:schedule`, retained `pipeline-events.csv` | 48 resource/dependency schedule checks; 20/19/16 ms equal-byte comparison; every retained interval matches recomputation | All demand known at t=0, space for four groups, independent serial resources, no interference or misses |
| 10, frontier | Same scheduler and `overlap-frontier.csv` | All 15 plotted totals match each compute profile and its own zero-retention baseline | Restricted early-layer candidate family; not a common L or a universal Z trend |
| 11, rental step | Retained native Draw.io source under `design-figure-revision-20260920/sources/` | Equal-size credit arithmetic, incoming-vs-resident distinction, aging despite lease, safe-release guard | Accounting illustration, not a performance comparison or inherited competitive guarantee |
| 12, lifecycle | Retained native Draw.io source under `design-figure-revision-20260920/sources/` | Pending dependency prevents frontier advance; commit/redirect/drain precede release; last-copy deletion changes advertised fallback | Protocol requirement, not proof of backend persistence or tested failure concurrency |

Native-capture data were not regenerated. This turn did not fit a predictor, run a GPU experiment, inject a failure, or generate a new online policy stream. Existing unfavorable observations were retained. The counterexample's constants are declared analysis inputs, not fitted hardware values.

## Rental argument and primary literature

- [Young, On-Line File Caching](https://www.cs.ucr.edu/~neal/Young02Online), Algorithmica 2002; [author-hosted conference paper](https://www.cs.ucr.edu/~neal/Young98Online.pdf), Figure 1 and the discussion of fixed costs. Its classic object-size/retrieval-cost setting supplies the credit-aging inspiration. The original discussion explicitly does not model time-varying costs.
- [Cao and Irani, Cost-Aware WWW Proxy Caching Algorithms](https://www.usenix.org/conference/usits-97/cost-aware-www-proxy-caching-algorithms), USITS 1997, independently combines locality, size and cost. Added to `references.bib`.
- AegisKV has changing valuations, optional admissions, shared-fault coupling, tier transitions and leases. Classical guarantees do not transfer. The algebraic identity `c' = max(0, c − bytes × rent_increment)` establishes lazy accounting only. Joint revaluation remains necessary and stale credits can reject a beneficial candidate.

To justify the rental policy in a submission, compare it with direct revaluation using identical candidate opportunities, estimator inputs, work budgets, safety, and migration costs. Across growing contexts, tool gaps, phase shifts and pressure, report realized WCT/cost, decision work/time, migration bytes and rejected profitable candidates. Isolate renewal and hysteresis separately. A named algorithm, a toy credit diagram, or fewer migrations alone is insufficient. If direct value achieves equal or better cost at acceptable decision work, simplifying the policy is the supported conclusion.

Tracker validation additionally needs residual-segment ground truth at causal snapshots, whole-workflow and time-held-out splits, coverage under missing roles/tools, and false-positive Slack/demotion regret under uncertainty. Whole-Agent labels and weak feature correlations cannot replace these tests.

## Visual and manuscript review

- Preserved previous assets and prose under `before/`; drawing sources and reviews remain outside the Overleaf folder.
- Native overview review caught a wrapped Cost model label; shortened it to WCT cost without shrinking font. Tracker legend initially intersected the CDF; moved it into a separate row above the axes. All intervals and entire error tails remain visible.
- Checked every Design figure at the actual 84.68 mm column width; extracted minimum text is 10.03–10.47 pt. Inspected color and grayscale outputs and affected paper pages. Different line styles, hatch, markers, direct labels and resource grouping provide non-color cues.
- The expanded Overview stays compact (near square), and all Design figures retain `figure` / `columnwidth` placement. Scientific interpretation is separate from the typography checks.
- LaTeX and Chinese companion now agree on Controller internals, rental rationale, negative evidence and figure roles. A per-figure claim/evidence table is included in the companion. Evaluation content is preserved; its figures are referenced rather than reinterpreted as new experiments.
- Canonical build: `sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh`; deliverable is `paper/main.pdf`. Build has no undefined citations/references or overfull boxes. Existing acmart vertical-spacing notices remain.

## Reproduction

Run `build_overview_controller_detail.py`, `render_design_evidence.py`, native Draw.io exports, then copy matching figure PDF/PNG pairs to `paper/figures/` and `paper/figures/preview/`. The layer-1 clarification is generated by calling `build_design_columns.sparse()` with `build_storage_design.OUT` set to this export directory. Run `audit_design_evidence.py` and the canonical build. `review/DELIVERY_HASHES.json` binds final sources and exports. This review is scoped verification and an evidence-gap assessment, not a declaration that the proposed system is experimentally validated.
