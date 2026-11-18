# Figure organization in the local related-work corpus

The PDF corpus is `benchmark/AegisKV/docs/related_works`. Page numbers below
are PDF page numbers. Captions were extracted from the actual PDFs; overview
pages of Mooncake, GhostServe, KVFlow and Pythia were also rendered and read.
These are structural references, not figures to copy into AegisKV.

| Paper | Motivation / background | Design / mechanism | Evaluation |
|---|---|---|---|
| Mooncake, FAST 2025 | Fig. 1, p. 2: effective cache capacity | Fig. 2, p. 3: architecture; Figs. 3–5: workflow, transfer engine, scheduling | End-to-end workloads, capacity, replication, network sensitivity and breakdowns |
| GhostServe, MLSys 2026 | Figs. 1–2, pp. 3–4: checkpointing context and costs | Fig. 3, p. 5: memory pools plus a GPU execution timeline | Offline/online failure results, kernel ablation, cost-benefit and sensitivity |
| DejaVu, ICML 2024 | Figs. 1–2: KV footprint and phase costs; Fig. 4: failure impact | Fig. 5: system; Figs. 6–8: layouts and pipeline phases | Streaming overhead, end-to-end speedup, swapping and failure timelines |
| KVFlow, 2025 | Fig. 1, p. 2: workflow and an LRU counterexample; Fig. 2: memory/transfer costs | Figs. 3–4: policy tree and prefetch timeline | Workloads, concurrency and token-mixture comparisons |
| Pythia, 2026 | Figs. 1–5: workflow examples, reuse, queueing and imbalance | Fig. 6, p. 6: application, global controller, workers and shared L3 | End-to-end, prefix/queue analysis, scaling, bursts and predictor fit |
| Strata, OSDI 2026 | Figs. 1–3: load/compute tradeoff, page size and platform latency | Figs. 4–7: architecture, interference, layouts and scheduling | End-to-end, I/O and scheduler breakdowns, ablation and bandwidth sensitivity |
| Cortex, 2025 | NL2SQL stage dependencies | Fig. 1, p. 1: workflow mapped to dedicated stage pools | Fig. 2, p. 2: KV usage with isolated serving engines |

The previous seven AegisKV figures covered workload/intervention validity and
results only. Grayscale was an authoring choice, not a requirement established
by these references. The revision needs all three layers of explanation:

* **Why:** a parallel-workflow example where equal recovery work has different
  completion-time harm, plus the byte/copy/recompute tradeoff. Illustrative
  arithmetic must be labeled and kept distinct from measured motivation.
* **How:** application, Router/Controller and worker/storage ownership;
  independent source-to-HBM and source-to-DRAM paths; commit/failure race,
  suffix-safe eviction and quota control. No HBM-to-DRAM destage arrow.
* **Evidence:** workload and configuration, healthy overhead, failure outcomes,
  direct recovery breakdown, retention/quota ablations, parameter sensitivity,
  and a clearly separated physical prototype result.

Color identifies roles consistently: blue Peer-HBM, orange Store-DRAM, green
workflow/application, purple policy/control, and red failure/recompute. Plots
retain distinct markers/linestyles so that grayscale printing remains usable.
Architecture and protocol source diagrams remain editable Draw.io XML.

The subsequent figure revision replaces the illustrative Motivation with the
recovered three-panel CC/Weka trace figure, independently checks its raw data,
and redesigns all ten figures. See `FIGURE_REVISION.md` for the question,
inputs and evidence boundary of each final export. The trace/model Motivation
is distinct from the FanOutQA-derived Qwen3-8B evaluation.

## 2026-09-08 narrative edition

The current selection is [Paper_Draft.md](../../experiments/Paper_Draft.md),
organized as Motivation, System Design and Evaluation. The actual local PDFs
were revisited: Mooncake Fig. 2 (architecture), GhostServe Figs. 3–4 (state/data
paths and foreground/recovery costs), DejaVu Fig. 7 (copy/compute phases), and
KVFlow Fig. 1 (a concrete workflow/cache counterexample).

This edition redraws all 21 previously selected figures and adds 15 standalone
assets. It uses the local manuscript's measured 7-inch text and 3.33-inch column
widths, consistent workflow pairing, explicit transfer/CPU/cache breakdowns,
and a separate 12-run early/middle/late logical-failure campaign. Design diagrams
are native editable Draw.io; no related-work figure or result is copied.
The full design, uncalibrated mechanism simulation and still-missing native
evidence remain distinct. See [the per-figure review](../../experiments/PAPER_FIGURE_REVIEW.md).

## Best Paper comparison revision

The current 33-figure edition supersedes the 36-figure narrative edition above.
Five design figures now use concrete object layouts, numerical worked examples
and state transitions. Six pairs are composed in Markdown and LaTeX while
keeping every asset independent. The four verified Best Paper references and
actual inspected PDF pages are recorded in [BEST_PAPER_FIGURE_REVIEW.md](BEST_PAPER_FIGURE_REVIEW.md).
