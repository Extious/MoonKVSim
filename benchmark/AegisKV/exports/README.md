# AegisKV paper exports

- [aegiskv.pdf](aegiskv.pdf): locally compiled current manuscript; System Overview uses proportional single-column placement.
- [VALIDATION.json](VALIDATION.json): source-directory compilation, dependency, bibliography, page and archive checks.
- `latex-build/`: local compiler intermediates; kept outside the upload source directory.

Download only [paper/](../paper/) for Overleaf. It contains exactly four `.tex` files and their compilation assets. ZIP generation has been retired. The English manuscript currently contains the abstract and Sections 2–3; local compilation is not an online Overleaf build.

Sources and local build instructions: [project README](../README.md).
Preserved originals and current filename mapping: [archive](../Archived/paper-four-tex-20260919/README.md).

```sh
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
```

Use the contents of `paper/`, select `main.tex`, and choose **pdfLaTeX** on Overleaf. This exports directory contains only local build and review artifacts.
