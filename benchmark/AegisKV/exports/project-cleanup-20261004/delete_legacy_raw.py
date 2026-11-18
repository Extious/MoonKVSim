"""Delete only the five inventoried historical raw event results, preserving designs/images."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
AUDIT = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    if (AUDIT / "RAW_RESULT_DELETION_COMPLETE.json").exists():
        raise SystemExit("raw-result deletion already completed")
    plan = json.loads((AUDIT / "RAW_RESULT_DELETE_PLAN.json").read_text())
    permitted = ROOT / "benchmark/AegisKV/Archived/simulation-qwen3-8b/audits"
    candidates = set()
    for item in plan:
        path = ROOT / item["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(permitted):
            raise RuntimeError(f"out-of-scope path: {path}")
        if path.name not in {"representative.json", "diagnostic.json"}:
            raise RuntimeError(f"unexpected raw-result filename: {path}")
        stat = path.stat()
        if (stat.st_ino, stat.st_dev, stat.st_size, stat.st_mtime_ns) != (
            item["inode"], item["device"], item["bytes"], item["mtime_ns"]
        ):
            raise RuntimeError(f"candidate changed after inventory: {path}")
        candidates.add(str(path))
    holders = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            for descriptor in (proc / "fd").iterdir():
                try:
                    target = os.readlink(descriptor)
                except OSError:
                    continue
                if target in candidates:
                    holders.append({"pid": proc.name, "path": target})
        except OSError:
            continue
    if holders:
        raise RuntimeError(f"raw results are open by local processes: {holders}")
    before = json.loads((AUDIT / "ACTIVE_PAPER_BEFORE.json").read_text())
    if any(sha(ROOT / path) != digest for path, digest in before.items()):
        raise RuntimeError("active manuscript drifted during cleanup")
    journal = AUDIT / "RAW_RESULT_DELETION_JOURNAL.jsonl"
    for item in plan:
        path = ROOT / item["path"]
        digest = sha(path)
        if path.stat().st_mtime_ns != item["mtime_ns"]:
            raise RuntimeError(f"raw result changed while hashing: {path}")
        row = {**item, "sha256": digest, "action": "authorized_delete"}
        with journal.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        path.unlink()
    result = {
        "status": "COMPLETE",
        "deleted_files": len(plan),
        "deleted_apparent_bytes": sum(item["bytes"] for item in plan),
        "images_deleted": 0,
        "designs_deleted": 0,
        "markdown_exception_status": "still awaiting exact Markdown path",
        "local_open_handle_check": "PASS",
        "active_paper_hashes": "PASS",
    }
    (AUDIT / "RAW_RESULT_DELETION_COMPLETE.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
