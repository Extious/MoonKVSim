# Design-section readiness, 2026-09-21

## Scope

The user clarified that the requested deliverable is a submission-quality **System Design section**, rather than completion of the full paper's empirical campaign. This revision therefore makes mechanism definitions, decision rules and conditional correctness arguments concrete. Prediction accuracy, integrated recovery speedup, overhead and their empirical validation remain Evaluation responsibilities. This does not turn the unimplemented or unmeasured parts of the proposal into verified implementation results.

Canonical files: `../../paper/system_design.tex`, `../../paper/paper_draft.md`, and `../../paper/main.pdf`. The seven Design subsections and seven figure positions remain. This task replaces Figure 5 and preserves the other existing figure assets. A concurrent task separately updated Figure 3 and its Insights paragraph to the native access-concentration plot; that update is preserved. All eight active Evaluation images retain their exact prior bytes.

## Changes required for the section itself

1. **Tracker target and interface:** define an execution segment between exposed dependency boundaries, distinguish parent waiting from child execution, state causal features and segment-end labels, and partition complete workflows for training/calibration/evaluation. Whole-Agent labels are explicitly not substituted for segment labels. Define model/graph versions, maximum age, support checks, update events and request-cost fallback.
2. **Slack derivation and error handling:** forward/backward DAG passes derive nominal Slack. The calibrated bundle supplies an empirical overestimation guard, applied once per interrupted segment in the joint fault scenario. Published clipped Slack is advisory; the Master consumes original durations and the guard without double charging. No per-request calibration guarantee is claimed.
3. **An operational placement objective:** all candidate plans share the same declared continuation scenarios, queue snapshot and resource scheduling rules. Migration interference and temporary occupancy affect those same workflow completion forecasts. Remove the underdefined separate `A(P',P)` byte/transition price and avoid double counting baseline execution or copying cost. Invalid duration forecasts use request completion costs; invalid resource profiles freeze optional promotion.
4. **Explicit L/K candidates:** mandatory native dependencies precede causal query-frequency ranking, with deterministic tie breaking and physical-block deduplication across heads. Finite budget templates enumerate model-depth times template-count alternatives, including zero Peer/current placement. Bounded tied-branch bundles address nonadditive joins; the search has an explicit work budget and no global-optimality claim.
5. **Distinct acceptance rules:** optional moves require negative predicted cost beyond a time margin. Forced capacity relief can accept a positive cost and chooses the least costly examined feasible plan. Both obey the same leases, copy dependencies, true byte capacity and version recheck. Algorithm 1 now makes the branch explicit.
6. **Three-tier recovery and correctness:** follow an incomplete-checkpoint fault from fencing through committed manifest selection, Peer hits, DRAM or storage miss paths, log replay and resumed decode. State three invariants and argue their preservation across pending copy, commit, demotion, last-copy deletion and failed copies. Safety is conditional on the stated surviving metadata/log/backing assumptions; progress also requires eventual resources. The argument does not claim an implemented fault-injection test.

These are concrete design specifications, including newly resolved algorithm choices. Their presence in the manuscript is not evidence that the runtime already implements them. Future implementation and Evaluation must match this contract or update it explicitly.

## Figure 5 and retained unfavorable evidence

The new `tracker-slack` is an editable Draw.io mechanism example. A fork has B=6 s and C=10 s, then D=2 s: completion is 12 s and nominal B/C Slack is 4/0 s. Updating B to 11 s changes completion to 13 s and Slack to 0/1 s. Bold borders identify the initial critical path. Values are constructed before the calibration guard; the caption explicitly says they are not accuracy measurements.

The old `tracker-correlations.pdf` and PNG are retained byte-for-byte in `archived-diagnostics/` along with the prior audit. The original 1,443 Agent / 170 workflow data and five held-out folds are unchanged. MAEs 438.6/406.7/407.1 s, paired interval [-80.9,4.9] s and weak correlation findings are now explicitly stated in Evaluation 4.12 and the Chinese companion. Removing the diagnostic float from Design does not remove its adverse result or validate the new training target.

## Review performed

- Native Draw.io PDF and PNG exports inspected; final column-width figure and grayscale rendering inspected. The 84.6825 mm wide figure is 61.02 mm tall, with minimum placed font 10.256 pt.
- Complete manuscript pages 5, 6, 8 and 9 inspected for Tracker, Master, algorithm, Adapter, Connector and the Design/Evaluation transition; page 7 checked for the unchanged mechanisms and new candidate text.
- Static arithmetic checks verified both DAG examples. No predictor refit, simulator campaign or physical experiment was run.
- Build/reference/image checks, four-root-TeX contract, figure hashes and synchronized English/Chinese mechanisms are recorded in `VALIDATION.json`.

The section now presents the mechanism, its operating assumptions, executable choices and correctness rationale in paper form. Empirical success is explicitly left to Evaluation; full-paper page limits and acceptance are not used as a gate for this section-focused task.

## Sources and build

Generator: `experiments/scripts/paper/build_tracker_slack.py`; editable source: `sources/tracker-slack.drawio`; arithmetic source: `data/tracker-slack-example.json`. Use repository `.venv/bin/python` to regenerate, followed by the native Draw.io CLI. Published assets use `paper/figures/tracker-slack.pdf` and `paper/figures/preview/tracker-slack.png`. Build with `sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh` from the repository root.
