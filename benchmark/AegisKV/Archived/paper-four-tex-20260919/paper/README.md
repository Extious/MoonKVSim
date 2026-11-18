# AegisKV LaTeX project

This directory is the self-contained source project for the current manuscript.

## Overleaf

1. Create a project with **New Project → Upload Project** and select `aegiskv-overleaf.zip`.
2. Set **Main document** to `main.tex` and **Compiler** to **pdfLaTeX**.
3. Recompile; bibliography processing uses BibTeX and `ACM-Reference-Format.bst`.

The local validation uses TeX Live 2026. Keep the bundled `acmart.cls` and bibliography style; no Python, Draw.io, external data paths, or shell escape is needed to compile. This package has not been uploaded to an Overleaf account as part of the local validation.

Official instructions: [upload a project](https://www.overleaf.com/learn/latex/Kb/Uploading_a_project), [main document](https://docs.overleaf.com/getting-started/recompiling-your-project/the-main-document), and [compiler settings](https://docs.overleaf.com/getting-started/recompiling-your-project/selecting-a-tex-live-version-and-latex-compiler).

## Contents and current scope

- `main.tex`: the only manuscript entry point; retains the existing anonymous SIGPLAN configuration.
- `sections/`: 13 included LaTeX files for the abstract, Background and Motivation, and System Design.
- `figures/`: nine vector PDF assets for Figures 1–5, named by figure and panel.
- `references.bib`: the merged bibliography; citation keys are unchanged.
- `acmart.cls`, `ACM-Reference-Format.bst`: the existing local ACM template and bibliography style.
- `latexmkrc`, `build.sh`: portable compilation settings and optional local build command.

**This is the current partial manuscript, not a completed submission.** It contains the abstract and Sections 2–3. Existing section numbering, text, algorithms, and captions are retained. System Overview (Figure 4) uses proportional single-column placement; the other figure dimensions are unchanged. Introduction, Implementation, Evaluation, Related Work, and Conclusion from the Chinese writing draft have not been silently inserted or translated into this English version.

## Local build

From this directory, run:

```sh
sh build.sh
```

The PDF is written to `../exports/aegiskv.pdf`; intermediate files stay in `../exports/latex-build/`, outside the source project. To choose another destination:

```sh
AEGISKV_OUTPUT_DIR=/tmp/aegiskv-build sh build.sh
```

When uploading sources, exclude generated `main.pdf`, `.aux`, `.log`, `.bbl`, and build directories. Figure PDFs under `figures/` are required inputs and must remain in the package.

## Repository archive and figure editing

In the repository, the complete pre-cleanup tree is preserved under `../Archived/paper-overleaf-20260919/paper/`. It contains Chinese drafts, Draw.io/SVG/PNG sources, candidate figures, data/provenance notes, and the old build products. The accompanying archive `FILE_MAP.csv` maps original paths to the active source files and preserved originals.

That archive is not required on Overleaf. For figure edits, use the archived editable source or the corresponding experiment generator, then publish the selected vector PDF to the matching filename under `figures/`. Earlier generators retain their historical output paths and should not be used as the packaging step.

From the repository root, regenerate the upload ZIP with:

```sh
python benchmark/AegisKV/experiments/scripts/paper/package_overleaf.py
```
