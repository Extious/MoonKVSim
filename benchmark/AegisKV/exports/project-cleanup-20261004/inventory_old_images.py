"""Preserve the union of Markdown image references while exact file is unknown."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
AEGIS = ROOT / "benchmark/AegisKV"
AUDIT = Path(__file__).resolve().parent
EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", "project-cleanup-20261004"}


def main() -> None:
    markdowns = []
    for base in [AEGIS, ROOT / "docs"]:
        for current, children, names in os.walk(base, followlinks=False):
            children[:] = [n for n in children if n not in EXCLUDED
                           and not n.startswith("runtime-")
                           and not (Path(current) / n).is_symlink()]
            markdowns.extend(Path(current) / n for n in names if n.endswith(".md"))
    markdowns.extend(ROOT.glob("*.md"))
    references: dict[str, set[str]] = {}
    directory_references = []
    bodies = []
    pattern = re.compile(r"([^\s<>\[\]()\"'`]+\.(?:png|svg|pdf|jpg|jpeg|webp|drawio))", re.I)
    links = re.compile(r"(?:\]\(|(?:src|href)\s*=\s*[\"'])([^)\s\"']+)")
    for markdown in sorted(set(markdowns)):
        body = unquote(markdown.read_text(errors="replace"))
        relative = markdown.relative_to(ROOT).as_posix()
        bodies.append((relative, body))
        for match in pattern.finditer(body):
            references.setdefault(match.group(1).split("/")[-1], set()).add(relative)
        for match in links.finditer(body):
            value = unquote(match.group(1)).split("#")[0]
            if "://" in value or not value:
                continue
            path = (markdown.parent / value).resolve()
            if "output/pdf/" in value:
                path = AEGIS / "Archived/paper-reviews" / value.split("output/pdf/", 1)[1]
            if path.is_dir() and path.is_relative_to(AEGIS):
                directory_references.append((path, relative))
    scopes = [AEGIS / "Archived/figures-legacy", AEGIS / "Archived/paper-reviews"]
    base = AEGIS / "experiments/evaluation-20260924"
    for path in sorted(base.iterdir()):
        if not path.is_dir() or path.name in {"blsc-online-v1", "blsc-scale-v1", "native-topk-warm", "inputs"}:
            continue
        if (path / "figures").is_dir():
            scopes.append(path / "figures")
        if path.name.startswith("paper-preview"):
            scopes.append(path)
    for path in sorted((AEGIS / "exports").iterdir()):
        if path.is_dir() and "202609" in path.name:
            scopes.append(path)
    candidates, retained = {}, {}
    full_text = "\n".join(body for _, body in bodies)
    for scope in scopes:
        for current, children, names in os.walk(scope, followlinks=False):
            children[:] = [n for n in children if n not in EXCLUDED | {
                "source_snapshot", "source-snapshot", "source", "inputs", "sources", "references",
            } and not (Path(current) / n).is_symlink()]
            for name in names:
                path = Path(current) / name
                if path.is_symlink() or path.suffix.lower() not in {".png", ".svg", ".pdf", ".jpg", ".jpeg", ".webp"}:
                    continue
                # Full manuscripts and reference papers are not classified as figure PDFs.
                if path.suffix.lower() == ".pdf" and not any(
                    p in {"figures", "figure", "preview", "review", "reviews", "panels", "rendered"}
                    for p in path.relative_to(scope).parts[:-1]
                ):
                    continue
                reasons = []
                # Catch quoted names, spaces and Markdown emphasis outside normal links.
                if name not in references and name in full_text:
                    references[name] = {md for md, body in bodies if name in body}
                if name in references:
                    reasons.append("filename mentioned in Markdown")
                if any(path.is_relative_to(folder) for folder, _ in directory_references):
                    reasons.append("under a Markdown-linked directory")
                stat = path.stat()
                relative = path.relative_to(ROOT).as_posix()
                item = {"path": relative, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                        "inode": stat.st_ino, "device": stat.st_dev, "uid": stat.st_uid}
                if reasons:
                    retained[relative] = {**item, "reasons": reasons,
                                          "markdown_mentions": sorted(references.get(name, []))}
                else:
                    candidates[relative] = item
    summary = {
        "candidate_files": len(candidates), "candidate_bytes": sum(i["bytes"] for i in candidates.values()),
        "retained_files": len(retained), "retained_bytes": sum(i["bytes"] for i in retained.values()),
        "markdown_scanned": len(set(markdowns)),
        "rule": "conservative union of all Markdown filename and directory references; exact requested Markdown remains unknown",
        "editable_sources_deleted": 0,
        "scopes": [p.relative_to(ROOT).as_posix() for p in scopes],
    }
    for name, value in [
        ("UNREFERENCED_OLD_IMAGE_DELETE_PLAN.json", list(candidates.values())),
        ("MARKDOWN_IMAGE_RETENTION.json", list(retained.values())),
        ("IMAGE_INVENTORY_SUMMARY.json", summary),
    ]:
        (AUDIT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "scopes"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
