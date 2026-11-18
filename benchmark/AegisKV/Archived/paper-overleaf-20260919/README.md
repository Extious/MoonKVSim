# AegisKV paper cleanup and Overleaf export (2026-09-19)

The user requested a minimal, uploadable `paper/` project and archival of non-compilation material.

- `paper/` is the complete pre-cleanup tree: **256 files, 27,310,117 bytes**. Every original file was preserved and SHA-256 checked.
- The active project now has 29 files. 228 original paths are archive-only; the other original sources are retained, renamed, or merged in the active project.
- `FILE_MAP.csv` records every original path, preserved copy, active destination (if any), and original SHA-256.
- `FIGURE_MAP.json` maps the nine original figure PDFs to their stable figure/panel filenames.
- `BUILD_COMPARISON.json` records 12-page text equality, identical 90-dpi page renders, unchanged figure hashes, and matching LaTeX diagnostics between the baseline and reorganized project.
- `outside-originals/` preserves repository navigation files before their links were updated.

The snapshot includes current Chinese writing drafts, selected figure editable sources, data/provenance notes, candidates and superseded layouts. **Archival here indicates that a file is not needed by the Overleaf compiler; it does not declare all its scientific content obsolete.**

## Useful preserved sources

- Chinese draft: [draft/README.md](paper/draft/README.md)
- Current Chinese design: [system_design.md](paper/draft/system_design.md)
- Original section guide: [sections/README.md](paper/sections/README.md)
- Figure 1(b) editable source: [motivation-workflow.drawio](paper/figures/motivation-row/motivation-workflow.drawio)
- Figure 4 editable source: [system-overview-v11.drawio](paper/figures/system-overview-v11.drawio)
- Figure provenance: `paper/figures/` contains the original README, MANIFEST, SVG and PNG files in their original relative structure.

The snapshot is intentionally unmodified. Links that originally left `paper/`, absolute paths, and historical generator output locations retain their original meaning; consult `FILE_MAP.csv` for the paths at this archival step. The later four-file layout and semantic figure names are recorded in [the next migration](../paper-four-tex-20260919/README.md). Current upload and build instructions are in the [project README](../../README.md).

The English entry point contains the abstract and Sections 2–3; this operation did not translate or add the remaining Chinese sections. The existing nine Underfull hbox diagnostics were preserved; there are no undefined citations/references, Overfull hboxes, or LaTeX errors in the reorganized build.
