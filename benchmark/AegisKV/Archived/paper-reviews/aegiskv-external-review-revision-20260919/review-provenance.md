# AegisKV external review, 2026-09-19

## Baseline

- Local: outputs/main-review-baseline.pdf
- Remote: /home/comp/zhanzhao/MoonKVSim/output/pdf/aegiskv-external-review-baseline-20260919T041842Z/AegisKV-review-baseline.pdf
- SHA-256: 32aa352a81387c4cb982603742e679b7fcb9f83a22383eaa72f9c78299a89a52
- 9 pages, 662743 bytes. Abstract, Background and Motivation, System Design, References. This is an integrated section preview, not a complete submission.
- Remote compilation succeeded with all 24 citations resolved; baseline includes a known Figure 4 small-font defect.

## Independent web review conversations

The same PDF and initial prompt were submitted through Chrome using Computer Use. Existing signed-in accounts and available models were used; no subscription was purchased.

| Service | Visible mode | Conversation |
|---|---|---|
| ChatGPT | 6 Pro | https://chatgpt.com/c/6aae1081-a1a4-83ec-90a8-2db8c1a398dd |
| Claude | Opus 5 Extra | https://claude.ai/chat/01c3010a-61b1-4e78-8806-020a555b92b6 |
| Grok | Fast (Expert opened a subscription gate) | https://grok.com/c/749bc90f-b81f-4f88-b9c8-242048dc816c |

Official venue guidance checked directly: https://2027.eurosys.org/cfp.html . The local coordinator verified the submission's evidence scope and inspected the PDF pages and figures. No claim of actual conference peer review or acceptance prediction is implied.

## Grok review quality control

Grok returned 16 numbered comments, evaluation suggestions, and five rewrite/figure suggestions. Its follow-up accepted corrections requested by the coordinator. The following mistakes must not enter author revisions:

1. P0-2/P0-3 reversed the sign of some predictor/threshold effects. With P iff sigma < R_D = R_base + W0, underestimating W0 shrinks the P region (holding other variables fixed). Underestimating the actual critical branch can create false positive slack and cause underprotection. Correct example: two branches have true remaining times A=100, B=90, so slack(A)=0; estimates A=60, B=90 produce estimated slack(A)=30. Grok's follow-up example calling a branch with slack=8 'critical' is also incorrect and is excluded.
2. P0-5's tool-wait pin example conflicts with the PDF, which releases a request reference when the LLM request ends, including a response handing control to an external tool. Retained active long-decode copies and migration delays are valid pressure cases.
3. Figure 1(c), Figure 2, Figure 3(a), and Figure 5 already disclose counterfactual/static/literature/modeled status. Missing end-to-end validation remains valid; an assertion that this provenance is absent is not.
4. Cross-schedule bit-identical recovery is too strong; logical state/metadata consistency and declared numerical tolerances under controlled deterministic configurations are appropriate.
5. A slack-aware recovery scheduler is not automatically required. R3 explicitly avoids request-level serialization; non-preemptive DMA, foreground fairness, starvation bounds and contention should be specified/tested without changing this design merely to satisfy a review preference.
6. No general optimality or approximation theorem is required for a heuristic. A precise objective, reproducible decision rule, counterexamples and oracle comparison are useful.
7. Grok confirmed reading nine pages of text, but could not reliably confirm exact figure font sizes, grayscale contrast or line widths. Local visual/font QA takes precedence.

Useful retained themes: end-to-end evidence, real dependency validation, realistic failure/concurrency scope, predictor calibration, exact cost/score definition, stable admission and shrink semantics, recovery commit/state contracts, matched strong baselines, hot-set domain shift, terminology, and figure readability.

## Preliminary Claude quality-control observations (pending full response)

- Do not require favorable experimental outcomes. Suggested acceptance thresholds such as 'Peer accounts for >=10% of total benefit', 'rank overlap must be low', or 'DRAM and recompute curves must cross' are not universal correctness criteria. Report measured outcomes, including negative ones.
- Figure 1 uses a selected counterfactual. A concrete counterexample can establish that recovery-cost ranking need not equal WCT ranking; population analysis is needed for prevalence and practical significance, not for the existential mathematical statement.
- 121/393 is about 30.8% session coverage under the study filter. The excluded 69.2% cannot be labeled serial or zero-slack without examining their structures; absence from a strict overlap filter is not that evidence.
- The baseline says costs are jointly profiled under representative concurrency. It is fair to ask for the actual interface/calibration/contended profiles; it is inaccurate to assert W0 is necessarily the no-contention Figure2 value.
- A cost described as foreground delay caused by memory occupancy is still a delay quantity, not raw bytes added to seconds. Need explicit conversion and same policy horizon; no demonstrated dimensional inconsistency from this sentence alone.
- A tier eligibility gate independent of failure probability does not necessarily assume p=1; the subsequent economic/admission decision can legitimately choose zero Peer depth. Low-failure-rate break-even analysis is needed, but 'always d=0' needs assumptions about nonzero normal cost and risk.
- Stable request ID tie-breaking is not necessarily FCFS. Compare marginal Peer-over-DRAM gains, not R-over-DRAM gains when criticizing Peer allocation.
- A numerical example of 16 simultaneous 20 GiB histories on a single 80 GiB source GPU is infeasible; account for foreground weights/activation/KV pool, topology, offloading, and TP before assigning concurrency.
- A1's 35.2s recompute cost is not the largest among A1-A4 (A4=38.9s).
- 'No implemented system results in this attached draft' does not prove the repository has no implementation or no underlying measurements. Figure3c native selector captures and Figure5 measured compute component must not disappear from provenance.
