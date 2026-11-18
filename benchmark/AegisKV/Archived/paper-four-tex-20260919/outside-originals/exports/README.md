# AegisKV paper exports

- [aegiskv-overleaf.zip](aegiskv-overleaf.zip): uploadable source package, with `main.tex` at its root.
- [aegiskv.pdf](aegiskv.pdf): locally compiled current manuscript; System Overview uses proportional single-column placement.
- [aegiskv-overleaf.manifest.json](aegiskv-overleaf.manifest.json): source-file and ZIP checksums.
- [VALIDATION.json](VALIDATION.json): isolated ZIP build, dependency, bibliography, page and archive checks.
- `latex-build/`: local compiler intermediates; excluded from the upload ZIP.

The English manuscript currently contains the abstract and Sections 2–3. This packaging does not constitute a completed submission or an online Overleaf build.

Sources and local build instructions: [paper/README.md](../paper/README.md).
Preserved originals and figure-source mapping: [archive](../Archived/paper-overleaf-20260919/README.md).

```sh
sh benchmark/AegisKV/paper/build.sh
python benchmark/AegisKV/experiments/scripts/paper/package_overleaf.py
```

Use **Upload Project**, select `main.tex`, and choose **pdfLaTeX** on Overleaf; see the [official upload guide](https://www.overleaf.com/learn/latex/Kb/Uploading_a_project). Do not upload this entire exports directory.
