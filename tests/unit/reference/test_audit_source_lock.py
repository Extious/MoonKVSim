from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = PROJECT_ROOT / "reference" / "source-lock.json"
AUDIT_SCRIPT = PROJECT_ROOT / "scripts" / "audit_source_lock.py"
MODULE_SPEC = importlib.util.spec_from_file_location("audit_source_lock", AUDIT_SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
AUDIT_MODULE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = AUDIT_MODULE
MODULE_SPEC.loader.exec_module(AUDIT_MODULE)
AuditReport = AUDIT_MODULE.AuditReport
audit_lock = AUDIT_MODULE.audit_lock
verify_git_repository_live = AUDIT_MODULE.verify_git_repository_live


def _load_lock() -> dict[str, object]:
    return json.loads(LOCK_PATH.read_text())


def _git(repository: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout


def test_checked_in_lock_is_valid_but_fail_closed() -> None:
    lock = _load_lock()
    report = audit_lock(lock, lock_path=LOCK_PATH)

    assert report.errors == []
    assert report.blockers == [
        "SRC-BLOCK-001",
        "SRC-BLOCK-002",
        "SRC-BLOCK-003",
    ]
    assert report.valid
    context = lock["model_tokenizer"]["context_128k"]  # type: ignore[index]
    assert context["status"] == "proposed_unvalidated"  # type: ignore[index]
    assert context["readiness"] == "BLOCKED"  # type: ignore[index]
    assert context["formal_128k_allowed"] is False  # type: ignore[index]


def test_schema_rejects_a_corrupt_file_hash() -> None:
    lock = deepcopy(_load_lock())
    lock["repositories"]["mooncake"]["files"][0]["sha256"] = "not-a-sha"  # type: ignore[index]

    report = audit_lock(lock, lock_path=LOCK_PATH)

    assert any("sha256: expected SHA-256" in error for error in report.errors)


def test_mooncake_lock_rejects_worktree_as_baseline_source() -> None:
    lock = deepcopy(_load_lock())
    lock["repositories"]["mooncake"]["files"][0]["source"] = (  # type: ignore[index]
        "worktree_snapshot"
    )
    lock["repositories"]["mooncake"]["files"][0]["worktree_state"] = (  # type: ignore[index]
        "modified"
    )
    lock["repositories"]["mooncake"]["files"][0]["commit_sha256"] = (  # type: ignore[index]
        lock["repositories"]["mooncake"]["files"][0]["sha256"]  # type: ignore[index]
    )

    report = audit_lock(lock, lock_path=LOCK_PATH)

    assert any("worktree source forbidden" in error for error in report.errors)


def test_schema_rejects_unvalidated_128k_candidate_as_ready() -> None:
    lock = deepcopy(_load_lock())
    context = lock["model_tokenizer"]["context_128k"]  # type: ignore[index]
    context["status"] = "validated"  # type: ignore[index]
    context["readiness"] = "READY"  # type: ignore[index]
    context["physical_validation"]["completed"] = True  # type: ignore[index]
    context["formal_128k_allowed"] = True  # type: ignore[index]

    report = audit_lock(lock, lock_path=LOCK_PATH)

    assert any("status: expected proposed_unvalidated" in error for error in report.errors)
    assert any("readiness: expected BLOCKED" in error for error in report.errors)
    assert any("completed: must remain false" in error for error in report.errors)
    assert any("formal_128k_allowed: expected False" in error for error in report.errors)


def test_missing_collection_interval_requires_fail_closed_blocker() -> None:
    lock = deepcopy(_load_lock())
    lock["readiness"]["blockers"] = [  # type: ignore[index]
        blocker
        for blocker in lock["readiness"]["blockers"]  # type: ignore[index]
        if blocker["id"] != "SRC-BLOCK-003"
    ]

    report = audit_lock(lock, lock_path=LOCK_PATH)

    assert any("SRC-BLOCK-003" in error for error in report.errors)


def test_schema_requires_pinned_vllm_kv_head_semantics() -> None:
    lock = deepcopy(_load_lock())
    vllm_files = lock["repositories"]["vllm"]["files"]  # type: ignore[index]
    model_file = next(  # type: ignore[arg-type]
        item for item in vllm_files if item["path"] == "vllm/config/model.py"
    )
    model_file["git_blob"] = "0" * 40

    report = audit_lock(lock, lock_path=LOCK_PATH)

    assert any("files[vllm/config/model.py].git_blob" in error for error in report.errors)


def test_live_git_verifier_uses_commit_objects_and_dirty_declaration(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "upstream"
    repository.mkdir()
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "MoonKVSim Test")
    _git(repository, "config", "user.email", "moonkvsim-test@example.invalid")
    source = repository / "source.py"
    source.write_text("VALUE = 1\n")
    _git(repository, "add", "source.py")
    _git(repository, "commit", "-q", "-m", "fixture")

    commit = _git(repository, "rev-parse", "HEAD").decode().strip()
    tree = _git(repository, "rev-parse", "HEAD^{tree}").decode().strip()
    blob = _git(repository, "rev-parse", f"{commit}:source.py").decode().strip()
    commit_bytes = _git(repository, "show", f"{commit}:source.py")
    clean_status = _git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=normal",
    )
    spec = {
        "repository": str(repository),
        "commit": commit,
        "tree": tree,
        "worktree": {
            "dirty": False,
            "tracked_change_count": 0,
            "untracked_entry_count": 0,
            "porcelain_sha256": hashlib.sha256(clean_status).hexdigest(),
        },
        "files": [
            {
                "path": "source.py",
                "source": "commit_object",
                "git_blob": blob,
                "sha256": hashlib.sha256(commit_bytes).hexdigest(),
            }
        ],
    }
    clean_report = AuditReport()

    verify_git_repository_live("fixture", spec, clean_report)

    assert clean_report.errors == []
    assert clean_report.verified == ["fixture"]

    source.write_text("VALUE = 2\n")
    dirty_report = AuditReport()
    verify_git_repository_live("fixture", spec, dirty_report)

    assert any("tracked dirty count mismatch" in error for error in dirty_report.errors)
    assert any("porcelain status fingerprint mismatch" in error for error in dirty_report.errors)
