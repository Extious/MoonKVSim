"""Delete inventoried old image exports, preserving Markdown and current assets."""

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


def write(name: str, value: object) -> None:
    (AUDIT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    if (AUDIT / "OLD_IMAGE_DELETION_COMPLETE.json").exists():
        raise SystemExit("old image deletion already completed; do not repeat")
    plan = json.loads((AUDIT / "UNREFERENCED_OLD_IMAGE_DELETE_PLAN.json").read_text())
    retained = json.loads((AUDIT / "MARKDOWN_IMAGE_RETENTION.json").read_text())
    summary = json.loads((AUDIT / "IMAGE_INVENTORY_SUMMARY.json").read_text())
    scopes = [ROOT / relative for relative in summary["scopes"]]
    hashes = {item["path"]: sha(ROOT / item["path"]) for item in retained}
    boundary = json.loads((AUDIT / "CURRENT_EVIDENCE_BOUNDARY.json").read_text())
    current = boundary["protected_current_scopes"]
    old_hashes = json.loads((AUDIT / "OLD_CAMPAIGN_RETAINED_HASHES.json").read_text())
    hashes.update({path: digest for path, digest in old_hashes.items()
                   if any(path.startswith(prefix + "/") for prefix in current)})
    write("OLD_IMAGE_RETAINED_HASHES.json", hashes)
    paths = {str(ROOT / row["path"]) for row in plan}
    for row in plan:
        path = ROOT / row["path"]
        if path.is_symlink() or not any(path.resolve().is_relative_to(scope) for scope in scopes):
            raise RuntimeError(f"out-of-scope image: {path}")
        if path.suffix.lower() not in {".png", ".svg", ".pdf", ".jpg", ".jpeg", ".webp"}:
            raise RuntimeError(f"unexpected image extension: {path}")
        if any(path.is_relative_to(ROOT / prefix) for prefix in current):
            raise RuntimeError(f"current asset selected: {path}")
        stat = path.stat()
        if (stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_dev, stat.st_uid) != (
            row["bytes"], row["mtime_ns"], row["inode"], row["device"], row["uid"],
        ):
            raise RuntimeError(f"image changed after inventory: {path}")
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            descriptors = list((process / "fd").iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            if target in paths:
                raise RuntimeError(f"image held open by process {process.name}: {target}")
    with (AUDIT / "OLD_IMAGE_DELETION_JOURNAL.jsonl").open("a") as journal:
        for row in plan:
            path = ROOT / row["path"]
            digest = sha(path)
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_dev) != (
                row["bytes"], row["mtime_ns"], row["inode"], row["device"],
            ):
                raise RuntimeError(f"image changed while hashing: {path}")
            journal.write(json.dumps({**row, "sha256": digest}) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
            path.unlink()
    changed = [relative for relative, digest in hashes.items()
               if not (ROOT / relative).is_file() or sha(ROOT / relative) != digest]
    remaining = [row["path"] for row in plan if (ROOT / row["path"]).exists()]
    result = {
        "status": "COMPLETE" if not changed and not remaining else "FAIL",
        "deleted_files": len(plan), "deleted_apparent_bytes": sum(row["bytes"] for row in plan),
        "retained_files_verified": len(hashes), "changed_retained_files": changed,
        "remaining_candidates": remaining, "editable_drawio_sources_deleted": 0,
        "retention_rule": summary["rule"], "local_open_handle_check": "PASS",
        "requested_exact_Markdown": "unknown; references preserved as a conservative union",
    }
    write("OLD_IMAGE_DELETION_COMPLETE.json", result)
    print(json.dumps(result))
    if changed or remaining:
        raise RuntimeError("post-deletion image verification failed")


if __name__ == "__main__":
    main()
