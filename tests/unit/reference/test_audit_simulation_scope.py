from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCOPE_PATH = PROJECT_ROOT / "reference" / "simulation-scope.json"
SOURCE_LOCK_PATH = PROJECT_ROOT / "reference" / "source-lock.json"
AUDIT_SCRIPT = PROJECT_ROOT / "scripts" / "audit_simulation_scope.py"
MODULE_SPEC = importlib.util.spec_from_file_location("audit_simulation_scope", AUDIT_SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = AUDIT
MODULE_SPEC.loader.exec_module(AUDIT)


def _inputs() -> tuple[dict[str, object], dict[str, object], bytes, bytes]:
    scope_bytes = SCOPE_PATH.read_bytes()
    source_lock_bytes = SOURCE_LOCK_PATH.read_bytes()
    return (
        json.loads(scope_bytes),
        json.loads(source_lock_bytes),
        scope_bytes,
        source_lock_bytes,
    )


def test_checked_in_scope_allows_only_modeled_e2_simulation() -> None:
    report = AUDIT.audit_paths(SCOPE_PATH, SOURCE_LOCK_PATH)

    assert report == {
        "errors": [],
        "formal_ready": False,
        "maximum_evidence_class": "E2",
        "physical_execution_allowed": False,
        "simulation_ready": True,
        "slurm_submission_allowed": False,
        "timing_status": "modeled_preliminary_not_calibrated",
    }


def test_scope_rejects_physical_execution_or_removed_formal_blocker() -> None:
    scope, source_lock, scope_bytes, source_lock_bytes = _inputs()
    changed_scope = deepcopy(scope)
    changed_scope["execution"]["real_gpu_execution_allowed"] = True  # type: ignore[index]
    scope_errors = AUDIT.validate_scope(
        changed_scope,
        source_lock,
        scope_bytes=AUDIT.canonical_json_bytes(changed_scope),
        source_lock_bytes=source_lock_bytes,
    )
    assert "simulation scope differs from the exact checked-in contract" in scope_errors

    changed_lock = deepcopy(source_lock)
    changed_lock["readiness"]["blockers"] = changed_lock["readiness"]["blockers"][1:]  # type: ignore[index]
    lock_errors = AUDIT.validate_scope(
        scope,
        changed_lock,
        scope_bytes=scope_bytes,
        source_lock_bytes=source_lock_bytes,
    )
    assert "source-lock formal blockers were removed, reordered, or changed" in lock_errors


def test_scope_rejects_noncanonical_bytes_and_source_lock_drift() -> None:
    scope, source_lock, _, source_lock_bytes = _inputs()
    noncanonical = json.dumps(scope).encode("utf-8")
    errors = AUDIT.validate_scope(
        scope,
        source_lock,
        scope_bytes=noncanonical,
        source_lock_bytes=source_lock_bytes + b"\n",
    )

    assert "simulation scope is not canonical pretty JSON" in errors
    assert any(error.startswith("source-lock SHA-256 drift:") for error in errors)
