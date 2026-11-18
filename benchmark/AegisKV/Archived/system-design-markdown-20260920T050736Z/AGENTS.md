# Paper directory contract

These are the user's current manuscript-maintenance preferences. Update them if the user explicitly changes the layout or chapter structure.

- `paper/` is the sole directory downloaded for Overleaf; keep compilation inputs and the explicitly requested deliverables below there.
- Explicit exception requested on 2026-09-20: keep `paper/paper_draft.md` and its inline PNG assets in `paper/figures/preview/` beside the manuscript. The draft starts directly with Background and Motivation and System Design; place each existing figure beside its supporting paragraph and explain its role. These are not LaTeX inputs; other generated or development files remain outside `paper/`.
- Design the draft's chapter structure from the latest conversation decisions and relevant primary KV/fault-tolerance literature. Existing `main.tex` section order and figure groupings are source material, not constraints on the new outline. Preserve agreed module responsibilities while allowing section numbers and placement to change; mark optional figures and missing evidence explicitly.
- Keep exactly four `.tex` files at its root: `main.tex`, `abstract.tex`, `background_and_motivation.tex`, and `system_design.tex`. Inline subsection, algorithm, and figure environments into the appropriate chapter.
- Use descriptive figure filenames without figure-number prefixes. Let LaTeX captions and references determine numbering.
- Keep System Overview proportional and single-column unless the user requests a different layout.
- Current Background and Motivation order (2026-09-20): Background covers agent roles/subagents and failures at serving scale; Motivation covers WCT priorities, then growing-context reconstruction costs, followed by a standalone failure-position paragraph introducing AegisKV. Figure 1 is the full-width row `workflow`, `workflow-gaps`, `recovery-cost`; Figure 2 is standalone `recovery-exposure`. Keep Markdown, LaTeX captions, labels, and references consistent. Re-layout changed-size statistical panels from their data with `render_motivation_reordered.py`; retain the data and their evidence labels.
- Publish the compiled manuscript as `paper/main.pdf` (user request, 2026-09-20). Keep build scripts, documentation, logs, other previews, editable figure sources, and archival material outside `paper/`.
- The preceding rule also excludes the explicitly requested draft and its inline figure previews. Render those previews from the unchanged figure PDFs with `python3 experiments/scripts/paper/render_draft_figures.py` from the AegisKV directory; keep its render manifest in `exports/`.
- Build with `sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh` from the repository root. Publish the final PDF to `paper/main.pdf`; keep intermediate files in `exports/latex-build/`. Do not publish a second current manuscript as `exports/aegiskv.pdf`.
- Do not automatically generate ZIP packages. The user downloads and uploads `paper/` directly.
- Preserve moved sources in `Archived/`, update active file references, and verify that the source directory compiles independently.
