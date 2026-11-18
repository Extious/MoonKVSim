"""File-level deletion of obsolete campaign outputs; preserve inputs and images."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
AUDIT = Path(__file__).resolve().parent
BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
GROUPS = [
    "capacity-slack-ablation-v1", "capacity-slack-ablation-v2-corrected",
    "external-baseline-v1", "formal-core-v1", "formal-core-v2-corrected",
    "low-dma-postreview-v1", "mechanism-campaign", "mechanism-decision-v1",
    "profile-smoke-v1", "profile-smoke-v3", "quota-pressure-postreview-v1",
    "sensitivity-campaign-v1", "sensitivity-campaign-v2-corrected",
    "slack-mechanism-posthoc-v1", "slack-mechanism-posthoc-v2-corrected",
    "structural-campaign-v1", "structural-campaign-v2-main", "walltime-primary-v3",
]
RUN_OUTPUTS = {
    "summary.json", "events.jsonl.gz", "flows.jsonl.gz", "resources.jsonl.gz",
    "controls.jsonl.gz", "admissions.jsonl.gz", "reclaims.jsonl.gz",
    "journal.jsonl.gz", "state-transitions.jsonl.gz", "fault-state.json",
    "HELDOUT_ERROR.json", "hbm-snapshots.jsonl.gz",
}
ARCHIVED_OUTPUTS = {
    "all-runs.json.gz", "statistics.json", "representative-run.json",
    "no-failure-overhead.json", "postfix-preview.json.gz",
}
CURRENT = [
    ROOT / "benchmark/AegisKV/paper",
    BASE / "blsc-online-v1", BASE / "blsc-scale-v1", BASE / "native-topk-warm",
    ROOT / "benchmark/AegisKV/experiments/blsc-online",
]


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def files(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    result = []
    for current, children, names in os.walk(path, followlinks=False):
        children[:] = [n for n in children if n not in {".git", "__pycache__"}]
        result.extend(Path(current) / n for n in names)
    return sorted(result)


def write(name: str, value: object) -> None:
    (AUDIT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def inventory() -> None:
    scopes = [(BASE / group / "runs", "old campaign run") for group in GROUPS]
    for name in [
        "current-design-20260923", "current-design-20260923-before-recovery-accounting",
        "current-design-20260923-initial-router-failure",
    ]:
        scopes.append((ROOT / "benchmark/AegisKV/experiments" / name / "runs", "old design run"))
    cases = BASE / "native-transfer-postreview-v2/cases"
    scopes.append((cases, "old conditional component case"))
    archive = ROOT / "benchmark/AegisKV/Archived/simulation-qwen3-8b/results"
    scopes.append((archive, "archived simulation result"))
    candidates: dict[str, dict] = {}
    retained: dict[str, str] = {}
    for scope, reason in scopes:
        for path in files(scope):
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"unexpected file in output scope: {path}")
            eligible = path.name in RUN_OUTPUTS
            if scope == cases:
                eligible = path.suffix == ".npz" or (
                    path.suffix == ".json" and not path.name.endswith(".complete.json")
                )
            elif scope == archive:
                eligible = path.name in ARCHIVED_OUTPUTS
            relative = path.relative_to(ROOT).as_posix()
            if eligible:
                stat = path.stat()
                candidates[relative] = {
                    "path": relative, "reason": reason, "bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino,
                    "device": stat.st_dev, "uid": stat.st_uid,
                }
            else:
                retained[relative] = sha(path)
    for scope in CURRENT:
        retained.update({p.relative_to(ROOT).as_posix(): sha(p) for p in files(scope)})
    plan = sorted(candidates.values(), key=lambda row: row["path"])
    write("OLD_CAMPAIGN_OUTPUT_DELETE_PLAN.json", plan)
    write("OLD_CAMPAIGN_RETAINED_HASHES.json", retained)
    write("CURRENT_EVIDENCE_BOUNDARY.json", {
        "basis": "live paper/main.tex, paper/evaluation.tex and BLSC client configs",
        "protected_current_scopes": [p.relative_to(ROOT).as_posix() for p in CURRENT],
        "other_protected_classes": [
            "all images and editable drawing sources pending Markdown selection",
            "run config.json and failure.json", "completion and source-binding records",
            "workloads and duration profiles", "native captures and model weights",
            "experiment protocols and frozen source snapshots",
        ],
        "local_experiment_writers": [], "slurm_queue": "empty at inventory",
    })
    groups = defaultdict(lambda: {"files": 0, "bytes": 0})
    for row in plan:
        groups[row["reason"]]["files"] += 1
        groups[row["reason"]]["bytes"] += row["bytes"]
    print(json.dumps({"mode": "inventory", "files": len(plan),
                      "bytes": sum(row["bytes"] for row in plan),
                      "retained_hashes": len(retained), "groups": groups}))


def delete() -> None:
    if (AUDIT / "OLD_CAMPAIGN_OUTPUT_DELETION_COMPLETE.json").exists():
        raise SystemExit("old campaign deletion already completed; do not repeat")
    plan = json.loads((AUDIT / "OLD_CAMPAIGN_OUTPUT_DELETE_PLAN.json").read_text())
    retained = json.loads((AUDIT / "OLD_CAMPAIGN_RETAINED_HASHES.json").read_text())
    candidates = {str(ROOT / row["path"]) for row in plan}
    for row in plan:
        path = ROOT / row["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT / "benchmark/AegisKV"):
            raise RuntimeError(f"unsafe candidate: {path}")
        stat = path.stat()
        if (stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_dev, stat.st_uid) != (
            row["bytes"], row["mtime_ns"], row["inode"], row["device"], row["uid"],
        ):
            raise RuntimeError(f"candidate changed after inventory: {path}")
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
            if target in candidates:
                raise RuntimeError(f"candidate held open by process {process.name}: {target}")
    with (AUDIT / "OLD_CAMPAIGN_OUTPUT_DELETION_JOURNAL.jsonl").open("a") as journal:
        for row in plan:
            path = ROOT / row["path"]
            digest = sha(path)
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_dev) != (
                row["bytes"], row["mtime_ns"], row["inode"], row["device"],
            ):
                raise RuntimeError(f"candidate changed while hashing: {path}")
            journal.write(json.dumps({**row, "sha256": digest}) + "\n")
            journal.flush()
            os.fsync(journal.fileno())
            path.unlink()
    changed = [relative for relative, digest in retained.items()
               if not (ROOT / relative).is_file() or sha(ROOT / relative) != digest]
    remaining = [row["path"] for row in plan if (ROOT / row["path"]).exists()]
    result = {
        "status": "COMPLETE" if not changed and not remaining else "FAIL",
        "deleted_files": len(plan), "deleted_apparent_bytes": sum(row["bytes"] for row in plan),
        "retained_files_verified": len(retained), "changed_retained_files": changed,
        "remaining_candidates": remaining, "images_deleted": 0, "designs_deleted": 0,
        "local_open_handle_check": "PASS", "markdown_exception": "awaiting exact Markdown path",
    }
    write("OLD_CAMPAIGN_OUTPUT_DELETION_COMPLETE.json", result)
    print(json.dumps(result))
    if changed or remaining:
        raise RuntimeError("post-deletion validation failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inventory", "delete"])
    args = parser.parse_args()
    inventory() if args.action == "inventory" else delete()
