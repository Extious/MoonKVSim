"""Remove only named tool caches and Python bytecode, after validation."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
AUDIT = Path(__file__).resolve().parent


def write(name: str, value: object) -> None:
    (AUDIT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    if (AUDIT / "CACHE_DELETION_COMPLETE.json").exists():
        raise SystemExit("cache deletion already completed; do not repeat")
    directories: set[Path] = set()
    targets: set[Path] = set()
    for name in [".mypy_cache", ".pytest_cache", ".ruff_cache"]:
        base = ROOT / name
        if not base.exists():
            continue
        if base.is_symlink() or not base.is_dir():
            raise RuntimeError(f"unexpected tool cache: {base}")
        directories.add(base)
        for current, children, files in os.walk(base, followlinks=False):
            directory = Path(current)
            for name in children:
                child = directory / name
                if child.is_symlink():
                    raise RuntimeError(f"cache symlink: {child}")
                directories.add(child)
            targets.update(directory / name for name in files)
    for relative in [
        "python", "scripts", "tests", "traces",
        "benchmark/AegisKV/exports/notion/aegiskv-20261002",
    ]:
        base = ROOT / relative
        if not base.is_dir():
            continue
        for current, children, files in os.walk(base, followlinks=False):
            directory = Path(current)
            children[:] = [
                name for name in children
                if name not in {".git", ".venv", "node_modules", "source_snapshot"}
                and not (directory / name).is_symlink()
            ]
            if directory.name == "__pycache__":
                directories.add(directory)
                if any(not name.endswith(".pyc") for name in files) or children:
                    raise RuntimeError(f"unexpected contents in bytecode cache: {directory}")
            targets.update(directory / name for name in files if name.endswith(".pyc"))
    plan = []
    for path in sorted(targets):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"unexpected cache file: {path}")
        stat = path.stat()
        plan.append({
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "inode": stat.st_ino, "device": stat.st_dev,
        })
    write("CACHE_DELETE_PLAN.json", plan)
    for item in plan:
        path = ROOT / item["path"]
        stat = path.stat()
        if (stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_dev) != (
            item["bytes"], item["mtime_ns"], item["inode"], item["device"],
        ):
            raise RuntimeError(f"cache changed during cleanup: {path}")
        path.unlink()
    for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        if path.exists() and not any(path.iterdir()):
            path.rmdir()
    result = {
        "status": "COMPLETE", "deleted_files": len(plan),
        "deleted_bytes": sum(item["bytes"] for item in plan),
        "excluded": [".venv", "model weights", "native runtime", "source snapshots"],
    }
    write("CACHE_DELETION_COMPLETE.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
