#!/usr/bin/env python3
"""Package the current manuscript's local dependency closure for Overleaf."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path


def project_files(root: Path) -> list[Path]:
    selected: set[Path] = set()
    visited: set[Path] = set()

    def resolve(name: str, suffixes: tuple[str, ...] = ("",)) -> Path:
        for suffix in suffixes:
            path = (root / (name.strip() + suffix)).resolve()
            if path != root and root not in path.parents:
                raise ValueError(f"Dependency leaves the project: {name}")
            if path.is_file():
                selected.add(path)
                return path
        raise FileNotFoundError(f"Missing project dependency: {name}")

    def walk(path: Path) -> None:
        if path in visited:
            return
        visited.add(path)
        source = re.sub(r"(?<!\\)%[^\n]*", "", path.read_text())
        for name in re.findall(r"\\(?:input|include)\s*\{([^}]+)\}", source):
            walk(resolve(name, ("", ".tex")))
        for name in re.findall(
            r"\\includegraphics(?:\[[^]]*\])?\s*\{([^}]+)\}", source
        ):
            resolve(name, ("", ".pdf", ".png", ".jpg", ".jpeg"))
        for names in re.findall(r"\\bibliography\s*\{([^}]+)\}", source):
            for name in names.split(","):
                resolve(name, ("", ".bib"))
        for command, suffix in (("documentclass", ".cls"), ("bibliographystyle", ".bst")):
            for name in re.findall(
                rf"\\{command}(?:\[[^]]*\])?\s*\{{([^}}]+)\}}", source
            ):
                # Keep an explicitly bundled style; system packages stay in TeX Live.
                if (root / (name + suffix)).is_file():
                    resolve(name, (suffix,))

    walk(resolve("main.tex"))
    for name in ("README.md", "latexmkrc", "build.sh"):
        if (root / name).is_file():
            resolve(name)
    return sorted(selected)


def main() -> None:
    aegiskv = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-dir", type=Path, default=aegiskv / "paper")
    parser.add_argument("--output", type=Path, default=aegiskv / "exports/aegiskv-overleaf.zip")
    args = parser.parse_args()
    root = args.paper_dir.resolve()
    output = args.output.resolve()
    if output == root or root in output.parents:
        parser.error("Write the ZIP outside paper/ to keep the source project clean.")
    files = project_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".zip.tmp")
    entries = []
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path in files:
            data = path.read_bytes()
            name = path.relative_to(root).as_posix()
            package.write(path, name)
            entries.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    with zipfile.ZipFile(temporary) as package:
        bad = package.testzip()
        if bad:
            raise ValueError(f"ZIP integrity check failed: {bad}")
    temporary.replace(output)
    manifest = {
        "main_document": "main.tex",
        "compiler": "pdfLaTeX",
        "bibliography": "BibTeX",
        "file_count": len(entries),
        "zip_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "files": entries,
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Packaged {len(entries)} files: {output}")
    print(f"ZIP bytes: {output.stat().st_size}; SHA-256: {manifest['zip_sha256']}")


if __name__ == "__main__":
    main()
