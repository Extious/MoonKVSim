# Four-file Overleaf source layout (2026-09-19)

The user requested exactly four LaTeX files, semantic figure filenames without numerical prefixes, and `paper/` as the only directory to download for Overleaf. No further ZIP generation is part of the workflow.

The active directory contains `main.tex`, `abstract.tex`, `background_and_motivation.tex`, `system_design.tex`, one bibliography, two template/style files, and nine vector figure PDFs (16 files total). Figures and algorithms formerly split across subsection files are inlined into their containing chapter. All nine figure PDFs are byte-identical to their previous counterparts; the single-column System Overview is preserved.

- `paper/`: all 29 pre-change source/helper files, preserved and hash-checked.
- `FILE_MAP.csv`: old chapter/figure paths to the four-file layout.
- `FIGURE_MAP.json`: previous numbered figure filenames to semantic filenames.
- `BUILD_COMPARISON.json`: unchanged 12-page text and rendered output after consolidation.
- `retired/`: the former ZIP, its manifest and the packaging script, retained for provenance.
- `outside-originals/`: navigation and validation files before updating their references.

Earlier editable figure sources and Chinese drafts remain in [the original paper archive](../paper-overleaf-20260919/README.md). Current sources are in [paper/](../../paper/) and the build instructions are in the [project README](../../README.md). The archived documents are snapshots, not active commands or current output locations.
