"""Repair archived draft links only when their relocated target is unambiguous."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
AEGIS = ROOT / "benchmark/AegisKV"
AUDIT = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    if (AUDIT / "MARKDOWN_LINK_REPAIR.json").exists():
        raise SystemExit("link repair already completed; do not repeat")
    edits = json.loads((AUDIT / "PATH_EDITS.json").read_text())
    changes, unresolved = [], []
    pattern = re.compile(r"(?P<prefix>\]\(|(?:src|href)\s*=\s*[\"'])(?P<target>[^)\s\"']+)")
    for markdown in sorted((AEGIS / "Archived/drafts").glob("*.md")):
        before = markdown.read_text()
        count = 0

        def replace(match: re.Match) -> str:
            nonlocal count
            target = unquote(match.group("target"))
            if "output/pdf/" not in target:
                return match.group(0)
            tail = target.split("output/pdf/", 1)[1]
            fragment = ""
            if "#" in tail:
                tail, fragment = tail.split("#", 1)
                fragment = "#" + fragment
            choices = [AEGIS / "Archived" / folder / tail
                       for folder in ["figures-legacy", "paper-reviews"]]
            choices = [path for path in choices if path.exists() and not path.is_symlink()]
            if len(choices) == 2 and all(p.is_file() for p in choices) and sha(choices[0]) == sha(choices[1]):
                choices = choices[:1]
            if len(choices) != 1:
                unresolved.append({"markdown": markdown.relative_to(ROOT).as_posix(),
                                   "target": match.group("target"),
                                   "reason": "missing historical target" if not choices else "ambiguous targets"})
                return match.group(0)
            replacement = os.path.relpath(choices[0], markdown.parent).replace(os.sep, "/") + fragment
            count += 1
            return match.group("prefix") + replacement

        after = pattern.sub(replace, before)
        if before == after:
            continue
        relative = markdown.relative_to(ROOT).as_posix()
        backup = AUDIT / "source-before" / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(markdown, backup)
        markdown.write_text(after)
        row = {"path": relative, "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
               "after_sha256": sha(markdown), "reason": "repair relocated image links", "links": count}
        edits.append(row)
        changes.append(row)
    report = {"changed_markdown_files": len(changes), "repaired_links": sum(row["links"] for row in changes),
              "changes": changes, "unresolved_historical_links": unresolved}
    (AUDIT / "PATH_EDITS.json").write_text(json.dumps(edits, ensure_ascii=False, indent=2) + "\n")
    (AUDIT / "MARKDOWN_LINK_REPAIR.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"changed_markdown_files": len(changes), "repaired_links": report["repaired_links"],
                      "unresolved_historical_links": len(unresolved)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
