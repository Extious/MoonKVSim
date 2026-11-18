# System Design narrative revision — 2026-09-21

## User request

Remove the abrupt shift from evidence-based Observations to Peer benefits and rental design, and fix other similar narrative interruptions throughout System Design.

## Revision map

- Section opening states the workflow/storage objective; deployment assumptions and three-tier terminology are introduced in Overview.
- Observations now contain only workflow-dependent recovery urgency and concentrated historical KV accesses. Existing figure evidence and its limits remain. A short transition connects these observations to protection priorities and selective access.
- Overview introduces complete backing, Peer acceleration, module ownership, fault scope and M/N. It no longer interrupts the architecture with checkpoint scheduling, partial-block or source-lease handling.
- Tracker explains why residual segments are predicted, then defines the critical-path passes, guard and algorithm inputs before Algorithm 1.
- Router focuses on normal locality, takeover binding and rebinding. Logical pin release is owned by the online loop; logging/replay protocol is owned by Connector.
- KV Master starts from Tracker/Router inputs. Section 3.5.1 links normal reuse to the Router trace, defines tier-conditional benefits and the joint WCT objective, then introduces prefix credit as a local screening estimate. This reverses the earlier unexplained credit-before-objective ordering. Figure 7 now has an explicit prose citation and role.
- Section 3.5.2 explains exposed transfers before introducing L/K, then connects state and pipeline examples to bounded candidate enumeration.
- Section 3.5.3 motivates reuse renewal versus value updates before ledger variables. It introduces checkpoint/event timing, candidate operations and event-loop inputs at the algorithm's point of use. The theoretical-guarantee qualification remains with this mechanism.
- Adapter starts with the changing foreground demand that requires a quota controller. Quota, stability count and update parameters precede Algorithm 3.
- Connector connects accepted decisions to committed state, then presents output logging/final snapshots, transfer invariants and recovery in execution order.

## Verification

- Canonical `paper/main.pdf` builds successfully and remains 20 pages. No overfull boxes, undefined references/citations, duplicate labels or LaTeX errors in the final build.
- Opened the final rendered Design pages 3–9. Checked Observation transition, figure/text order, algorithm blocks and section starts. A first-pass Router line overflow was corrected in prose; no typography or margin reductions were used.
- All three pseudocode listings are byte-identical to the preceding version. All eight Design figure blocks, all labels and all 40 figure assets are unchanged. Other paper inputs, including Evaluation and the adverse rental results, are unchanged.
- The Chinese Design follows the same order. Its Introduction/Background and Evaluation-through-supplement content outside Design are unchanged.
- Source whitespace word count is 3,389 → 3,620: the added text supplies causal transitions and definitions before their use; it does not restore the earlier 5,877-word design specification. Four root TeX files and the Overleaf-only paper-directory contract remain.
- No new performance or correctness experiment was run for this prose-only revision. `CHECKS.json` records the structural checks and final PDF hash; `before/` preserves the prior manuscript.
