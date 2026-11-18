# Paper directory contract

These are the user's current manuscript-maintenance preferences. Current user instructions take precedence; preserve unrelated active work and scientific provenance.

- `paper/` is the sole directory downloaded for Overleaf. Keep compilation inputs and the explicitly requested writing companion `paper/paper_draft.md` with inline PNGs in `paper/figures/preview/` there. Scripts, logs, raw data, drawing sources and review artifacts stay outside `paper/`.
- Keep exactly four root `.tex` files: `main.tex`, `abstract.tex`, `background_and_motivation.tex`, `system_design.tex`. The new Introduction, Evaluation, Related Work and Conclusion are inline in `main.tex`; subsection/algorithm/figure environments remain in their chapter.
- Publish the canonical compiled manuscript as `paper/main.pdf`. Build from the repository root with `sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh`; auxiliaries stay in `exports/latex-build/`. Do not create a second current manuscript as `exports/aegiskv.pdf` or automatically create a ZIP.
- Use descriptive figure filenames without figure-number prefixes. Let LaTeX captions/references number the figures. Preserve editable sources and replaced material in archives.

## Current design and full-paper decision (2026-09-20)

The user explicitly requested a complete EuroSys 2027 paper, confirmed abstract registration, and chose **DRAM plus SSD/shared storage, requiring a design rewrite**, in task `01a0befa-cbd6-78a3-acd9-bc8b3f24386b`. This supersedes the previous Peer-HBM R/D/P, layer-depth L, hot-block K and Peer-capacity rules. Ordinary inference still uses its own HBM working set.

- The complete manuscript has Introduction; Background and Motivation; AegisKV Design; Evaluation; Related Work; Conclusion. The Chinese writing companion covers the same full structure, rather than starting at Background.
- Design has six subsections: Design Insights; System Overview; Workflow Tracker: Remaining Time and Slack; Recovery-aware Router; KV Master: Online Retention and Demotion; Adapter and Connector: Safe Concurrent Execution.
- KV Master has three subsubsections: Valuing a placement change; Selecting a bounded online plan; Committing a checkpoint. Normal reuse is independent of Slack. Value DRAM demotion and last-copy deletion separately. Common-source failure affects all colocated requests and must propagate through the DAG, not a sum of isolated slack penalties.
- The current online candidate uses direct marginal revaluation plus migration hysteresis. Rental is an optional same-value-model ablation, not a proven new contribution or an inherited competitive guarantee.
- Router dispatches by load/locality and selects compatible surviving targets; it does not bind a Peer backup location. Adapter/Connector handle bounded transfer queues, byte ledgers, manifests, leases and safe release.
- New Overview is proportional single-column: editable source `exports/eurosys-complete-20260920/storage-overview.drawio`, generator `experiments/scripts/eurosys27/build_overview.py`, paper asset `figures/storage-overview.pdf`.
- New Evaluation figures are explicitly **analytical**, with no physical runs or fabricated confidence intervals. Generator/renderer and model configuration live in `experiments/scripts/eurosys27/` and `experiments/eurosys27/`. Preserve model assumptions, zero/negative results, static-versus-online scope, and separate the measured Motivation microbenchmarks from new theoretical curves.
- Future measured replacement uses the same CSV schema and `plot.py --mode measured`, with verified raw-source hashes and independent-campaign statistics. Update prose/captions/abstract together; changing a data file alone does not make an analytical claim measured.

## Preserved Motivation contract

- Background covers agent roles/subagents and serving-scale failures. Motivation covers WCT priorities and growing-context reconstruction costs, followed by a standalone failure-position paragraph introducing AegisKV.
- Figure 1 is the full-width row `workflow`, `workflow-gaps`, `recovery-cost`; Figure 2 is standalone `recovery-exposure`. Preserve source values, real branch timing, model/configuration, sample definitions, units and evidence boundaries. Same-column HBM reuse in a microbenchmark is a resident-state reference, not a reinstated Peer-HBM protection policy.
- The Motivation task can update the physical recovery-cost panel with measured shared-filesystem results; retain actual backend/cache/fault-domain labels, never relabel an unverified filesystem path as SSD.
- Trace prefix locality and historical native-sparse prediction results remain source evidence, not runtime cache hits or measured failure-recovery benefits. Superseded Peer-specific Insight/pipeline figures remain archived.

## Scientific review and concurrency

Use `/home/comp/zhanzhao/.codex/skills/scientific-figure-review/SKILL.md`, read applicable corrections, and inspect final-size actual exports and paper pages. For this EuroSys submission, verify official 10 pt figure text and grayscale readability. Preserve other tasks' edits by re-reading changed source files before integration. Earlier full source snapshots and initial figure hashes for this rewrite are under `exports/eurosys-complete-20260920/before/` and `source-snapshot.json`.
