# System Design: figure and claim review, 2026-09-21

The canonical delivery is `../../paper/main.pdf`, with synchronized `../../paper/paper_draft.md` and four root LaTeX sources. This revision improves the manuscript and checks the delivered figures; it does not certify the paper as submission-ready. No new physical experiments or favorable synthetic prediction results were produced.

## Changes requested by the user

| Figure | Decision and role | Evidence boundary |
|---|---|---|
| 3: native coverage | Retain: motivates selective Peer copies plus a complete miss path. | Three documents/model, matched 40% budget and oracle; coverage is not speedup. |
| 4: Overview | Redraw compact Application / Controller / Engine bands, parallel Controller modules, black callouts 1–5, symmetric Local/Peer HBM, Adapter/Connector, full shared backing. | Architecture and ownership, not a measured capacity allocation. |
| 5: Tracker | Compact the real correlations and held-out error CDFs; preserve weak associations and all tails. | Supports an uncertainty guard; does not validate accurate residual-segment Slack. |
| 6: reuse | Retain same-Agent and other-Agent prefix evidence for Router affinity. | Potential prefix reuse, not runtime cache-hit rate. |
| 7: retention value | Remove the in-plot title and reduce height, preserving both exact curves and marked cases. | Constructed counterexample to Slack-only ranking, not measured policy benefit. |
| 8: KV placement | Add complete DRAM history, uncommitted tail, L=2, unequal per-layer K, actual layer-1 demand and named miss path. | Concrete legal-state example; full backing includes all TP shards and selector state. |
| 9: recovery pipeline | Restore the pre-removal four-path PDF/PNG exactly, with corrected publication caption and explicit source assumptions. | Calibrated homogeneous analytical schedules, not end-to-end fault recovery. |

The three redundant Design figures (overlap frontier, replacement walkthrough, checkpoint lifecycle) moved out of the paper into `removed/`; their necessary content remains in the placement algorithm and commit protocol. Eleven older unreferenced PDF/PNG pairs also moved there after checking every current LaTeX and Markdown image reference. Sources and numerical evidence remain available. All eight active Evaluation PDFs are byte-identical to the before snapshot.

## Manuscript consistency and algorithm contract

- Keep seven subsections: Insights, Overview, Tracker, Router, KV Master, Adapter and Connector. Master retains three subsubsections: full checkpoint / Peer decisions, per-request L and hot blocks, full admission/revaluation/eviction flow.
- DRAM and storage manifests are complete through M. Peer L/K copies are optional acceleration and require complete committed backing. New state copies incrementally; partial progress cannot advertise a complete new frontier.
- Z is a configured checkpoint trigger. Actual uncommitted N can exceed Z under copying lag. Adapter changes the total Peer budget by a configurable window; Master controls per-request L/K.
- Direct revaluation compares complete candidate-plus-victim plans. Continuation scenarios are mutually exclusive normal-use or normal-use-plus-fault cases, with probabilities summing to one; normal and fault costs are not double-counted. Whole-DAG effects are not sums of block scores.
- Invalid segment forecasts/dependency information receive no positive Slack credit. The fallback uses normal-use and request-recovery costs, without claiming a valid WCT prediction. This is a degraded objective, not an accuracy guarantee.
- Normal competition respects running requests' logical Peer pins. Self replacement and required capacity relief may override logical pins, never active reader/copy leases. Valid immutable backing avoids a redundant Peer writeback. Removing the last complete backing retires dependent Peer claims.
- Connector reserves real capacity and follows copy, persistence, commit, redirect, drain and release. Required relief and optional promotion have distinct acceptance rules; exhausted search pauses admission rather than exposing incomplete recovery state.

## Figure 5 audit

Source: `experiments/data/agent-gbdt-steps/primary-landmark.csv`; 1,443 second-request Agent samples from 170 whole workflows, with the existing five workflow-disjoint held-out folds. Correlation intervals resample whole workflows 2,000 times. Neither labels nor fitted predictions were changed.

Median/basic/history MAEs are 438.6/406.7/407.1 seconds. The paired basic-minus-median interval is [-80.9, 4.9] seconds and crosses zero. All six marginal feature intervals cross zero. Complete-Agent remaining time includes subsequent calls and gaps, whereas the proposed Tracker requires residual execution-segment estimates. Completed Subagents and token-length proxies further limit generalization. Consequently the revised text explicitly rejects an accuracy claim. Detailed numeric checks are in `data/tracker-audit.json`; prior audit and raw data remain intact.

## Figure 9 provenance

The published PDF is byte-identical to `Archived/peer-hbm-paper-before-storage-20260920/figures/recovery-pipeline.pdf`, SHA-256 `08870137fb479b18df155c89664a7b42d2068700a4906fd9fde108e73334c02d`.

All four source hashes match the preserved original manifest. The MiniCPM4-8B raw replay measurement at M=32,768, N=64 gives 2.869690506486222 ms/layer; the CSV's document/layer means reproduce preload 0.658447265625 and preload-plus-miss 0.7748209635416666. Effective H2D at 6.25 GB/s is assumed, not measured. The Peer-vs-DRAM comparison is panel (c) versus (d), with identical complete DRAM backing and replay. Exposed wait decreases from 44.153 to 19.993 ms with 147.492 MiB of hot sets in seven layers. The restored model assumes homogeneous layer means and an ideal preemptible stream; it does not model finite staging or foreground queues and cannot establish a universal optimal L.

## Render review and checks

Two native-diagram iterations fixed a wrapped Tracker label and control edges crossing directory text. Statistical review separated the Figure 5 x-label from the lower legend. Final PDFs were rendered at the actual 84.6825 mm column width and inspected in the complete manuscript (pages 4–8); all five changed figure exports were also inspected in grayscale. The final Figure 9 caption edit was recompiled and page 7 inspected again.

| Changed figure | Final height | Minimum placed font |
|---|---:|---:|
| Overview | 77.29 mm (previous 97.31 mm) | 10.085 pt |
| Tracker | 83.80 mm | 10.298 pt |
| Retention value | 46.98 mm (previous about 72.38 mm) | 10.298 pt |
| KV placement | 73.56 mm | 10.351 pt |
| Recovery pipeline | 77.33 mm | 10.032 pt |

System Design source length fell from 4,931 to 3,106 whitespace-separated words, including captions and LaTeX commands; this is a consistent source-size comparison, not a prose word count. Ten Design figures became seven. The final build has no overfull boxes, undefined references or missing LaTeX/Markdown images. `VALIDATION.json` records the canonical PDF hash, figure list and unchanged Evaluation hashes. Editable Draw.io sources and plotting scripts remain outside the upload folder.

## Submission gaps that editing cannot remove

1. **Prediction validity:** obtain causal, workflow-disjoint residual-segment timing labels and test Slack sign/critical-path mistakes and WCT sensitivity. Current Figure 5 cannot validate the proposed Tracker; an uncertainty fallback itself needs evaluation.
2. **Implemented policy evidence:** the direct-value three-tier controller, versioning/leases, finite-capacity transitions, normal-serving interference and matched Peer-vs-DRAM recovery need integrated validation. Existing isolated models and old DRAM/storage results cannot establish those claims. Retain the negative rent comparison as an alternative, not as validation of the new controller.
3. **Policy specification and sensitivity:** scenario probabilities, finite L/K candidate grids, uncertainty/migration margins and search budgets require concrete implementation settings and sensitivity/control-cost evidence. The manuscript defines their semantics; it does not pretend calibrated deployment settings exist.
4. **Final length:** this expanded full paper remains 19 PDF pages, with technical material through page 17. The official [EuroSys 2027 CFP](https://2027.eurosys.org/cfp.html), checked 2026-09-21, permits 12 technical-content pages plus references and requires at least 10 pt text including figures. The existing repository instruction explicitly preserves expanded Evaluation at this stage, so unrelated Evaluation content was not silently cut to force a final limit. A later full-paper submission edit is still needed.

## Reproduction

Generate the native sources with `experiments/scripts/paper/build_submit_design.py` and the data plots/restored pipeline with `experiments/scripts/paper/render_submit_design.py`, using the repository `.venv/bin/python`. Export Draw.io sources with the native Draw.io CLI (`--crop -x -f pdf -e -b 1`, and PNG with `-s 2 -x -f png -e -b 1`). Publish the five figure PDF/PNG pairs into `paper/figures` and `paper/figures/preview`, then run `sh experiments/scripts/paper/build_paper.sh` from the AegisKV directory. Build auxiliaries stay in `exports/latex-build`; the delivered PDF is always `paper/main.pdf`.
