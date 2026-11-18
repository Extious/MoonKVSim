# EuroSys 2027 submission status

Checked 2026-09-20 against the [official CFP](https://2027.eurosys.org/cfp.html). The user confirmed registration of the title/abstract. Fall full-paper deadline: **2026-09-24 AoE** (2026-09-25 19:59:59 Asia/Hong_Kong at the end of the AoE day). The paper must be self-contained, at most **12 pages of technical content**, with references on additional pages. Optional supplementary material is a separate file, not extra compulsory technical pages. The official formatting specifies 7×9 inch text area, at least 0.33 inch column gap, at least 10 pt text/figures/captions and 12 pt leading, page numbers, and grayscale readability. The review is double blind. AI use must be disclosed. Re-check the CFP before upload in case it changes.

## Current expanded research draft (2026-09-21)

The user explicitly deferred the 12-page constraint. The current manuscript prioritizes complete experiment design and analysis; this is not the upload layout. Exactly four root tex files remain, with canonical `paper/main.pdf` and an updated Chinese companion.

- Evaluation: all 17 subsections retained, with eight selected single-column figures in the manuscript and 26 supporting/alternative plots in the experiment package. Complete single-failure decomposition, real-trace provenance/replay, twelve ablation variants and four factorial interactions, healthy cost, safety, robustness and scaling remain specified.
- Numerical evidence: the original 33 plots are preserved; one additional combined ablation view reuses two existing tables exactly. Main figures comprise seven analytical/mechanism views and one trace-driven-model view. Zero new physical serving campaigns or independent observations.
- LANL copy: pinned redistribution, 23,739 rows versus 23,741 documented officially; original-archive identity unresolved. The replay tests a conditional spare-pool model, not full fleet availability. Modern Reflex alerts lack sufficient outage/repair semantics and are kept separate.
- Negative evidence: original-timing trace mean improves while p95/p99 regress; the isolated trial-rent case costs more than direct revaluation. These are explicit research/design questions, not hidden exclusions.
- Raw data, hashes, model and figure code, fixed visual spec, measured-data packager, empty CSV templates and full experimental execution matrix are retained.

## Still required before making a measured systems claim

| Requirement | Current evidence | Remaining work |
|---|---|---|
| Prototype of revised online controller | Rental/sparse/overlap pseudocode and separate analytical static allocator | Integrate the exact controller, profiles and backing-store lifecycle; evaluate rent versus direct revaluation and sparse ranking versus pipelining independently |
| Real fault-safe state | Protocol specification; earlier path-specific microbenchmarks remain in Motivation | Surviving log, epoch fencing, manifest closure and adversarial transition tests for revised design |
| Strong baseline | Detailed fair-comparison contract | Execute tuned hierarchical cache + matched load-aware recovery; original systems or accurately named reproductions |
| Faulty WCT and normal overhead | Analytical and conditional trace-driven scenarios only | Paired executable workflow campaigns, including unaffected workflows and healthy service |
| DRAM/SSD or shared-filesystem behavior | Motivation contains job 1517208's four-path, single-worker Qwen2.5-7B-1M microbenchmark on DPC shared storage; the new evaluation uses separate declared generic rates | Measure the revised multi-worker path, capacity pressure, concurrency, writeback and cache state; DPC server cache is uncontrolled and this is not cold-SSD evidence |
| Runtime prediction | Method and perturbation study | Workflow-separated causal validation; preserve weak/negative previous diagnostics |
| Generality | Fixed four-branch analytical model | Multiple workload families, actual prompts/tools, models and supported contexts |

The current PDF is a **complete research draft**, not a validated submission-ready system. Formatting, complete prose and attractive theory figures cannot establish a high acceptance probability. The most consequential unresolved question is whether the workflow/common-failure value adds a meaningful improvement over close prior work under realistic normal-service cost and failure frequency.

A practical order before the deadline is: E0 correctness → one bounded E1 slice (80 runs) → E7 healthy overhead → E2 capacity boundary → E4 decisive ablations. Schedule additional matrix cells only after measuring actual run cost. This is a prioritization, not a promise that these results can be completed in the remaining days. If evidence is weak, narrow the claim and preserve the negative result; do not convert model numbers into measured results.

The final page count, LaTeX checks, placed figure fonts and inspected pages are recorded in `../../exports/evaluation-expanded-20260921/CHECKS-expanded.json` and `REVIEW.json`. No paper is submitted by this task.
