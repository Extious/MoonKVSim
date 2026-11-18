# Background and Motivation: reordered figures and narrative

The manuscript now contains Background (agent roles/subagents; failures at serving scale) and Motivation (workflow completion; growing-context recovery), followed by an independent failure-position paragraph introducing AegisKV.

Figure mapping:

| New label | Figure source | Prior label |
| --- | --- | --- |
| 1(a) | workflow.pdf | 1(b) |
| 1(b) | workflow-gaps.pdf | 1(a) |
| 1(c) | recovery-cost.pdf | 2 |
| 2 | recovery-exposure.pdf | 1(c) |

The two statistical panels with changed insertion sizes were re-exported from the existing data. The 75 recovery estimates and four branch counterfactuals are unchanged. The recovery panel has compact model aliases, all explained in the caption; its milliseconds and extrapolation markers are retained. Three subcaptions have a common baseline. System Overview remains proportional and single-column.

`render_motivation_reordered.py` is the reproducible source; `MANIFEST.json` records source hashes, values and output hashes. `VALIDATION.json` records manuscript hashes, compiled labels, file scope, fonts and review. Actual final-page renders and a grayscale plot are in `review/`. Editable SVGs remain here; only final PDFs and Markdown previews are in `paper/`.

Primary sources were checked for AutoGen, Anthropic's multi-agent research system, LUMEN, and the SemiAnalysis Claude Code dataset. Claims about growing adoption and deployment-scale failures are qualitative; the text does not assert majority market share or an increasing per-device failure rate. The ECDF remains a distribution of workflow-maximum branch-duration gaps, and the recovery panels remain static estimates/counterfactuals.

The build succeeded with no undefined references, missing citations, or overfull boxes. Bibliography underfull-box notices remain. No simulations or physical experiments were run. Prior manuscript files and PDF are archived at:

/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/Archived/motivation-reorder-20260920T120734
