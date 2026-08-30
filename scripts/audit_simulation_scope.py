#!/usr/bin/env python3
"""Fail-closed audit of the simulation-only MoonKVSim delivery boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

EXPECTED_SCOPE: Final[dict[str, Any]] = {
    "evidence": {
        "calibrated_claim_allowed": False,
        "formal_use_allowed": False,
        "maximum_evidence_class": "E2",
        "modeled_matrix_allowed": True,
        "paper_result_allowed": False,
        "physical_claim_allowed": False,
        "timing_status": "modeled_preliminary_not_calibrated",
    },
    "execution": {
        "cpu_metadata_des_allowed": True,
        "real_gpu_execution_allowed": False,
        "real_vllm_mooncake_execution_allowed": False,
        "simulated_resource_model_allowed": True,
        "slurm_submission_allowed": False,
        "vanilla_aegiskv_matched_simulation_allowed": True,
    },
    "global_clock": {
        "kind": "single_monotonic_virtual_clock",
        "unit": "nanosecond",
    },
    "schema": "moonkvsim.simulation-scope.v1",
    "source_lock": {
        "blockers_preserved": [
            "SRC-BLOCK-001",
            "SRC-BLOCK-002",
            "SRC-BLOCK-003",
        ],
        "path": "reference/source-lock.json",
        "sha256": "d122c926c41071bb1cf6049a3ff9fada836038cee5047881399f946750a9eaf1",
    },
}


def canonical_json_bytes(value: object) -> bytes:
    """Return the repository canonical pretty JSON representation."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_scope(
    scope: object,
    source_lock: object,
    *,
    scope_bytes: bytes,
    source_lock_bytes: bytes,
) -> list[str]:
    """Validate exact scope semantics and the bound source-lock limitations."""

    errors: list[str] = []
    if scope != EXPECTED_SCOPE:
        errors.append("simulation scope differs from the exact checked-in contract")
    if isinstance(scope, Mapping) and scope_bytes != canonical_json_bytes(scope):
        errors.append("simulation scope is not canonical pretty JSON")
    if not isinstance(source_lock, Mapping):
        errors.append("source lock root must be an object")
        return errors

    declared_source = EXPECTED_SCOPE["source_lock"]
    observed_source_sha = sha256_bytes(source_lock_bytes)
    if observed_source_sha != declared_source["sha256"]:
        errors.append(
            "source-lock SHA-256 drift: "
            f"observed={observed_source_sha}, expected={declared_source['sha256']}"
        )
    readiness = source_lock.get("readiness")
    if not isinstance(readiness, Mapping):
        errors.append("source lock readiness must be an object")
        return errors
    raw_blockers = readiness.get("blockers")
    if not isinstance(raw_blockers, Sequence) or isinstance(raw_blockers, (str, bytes)):
        errors.append("source lock blockers must be an array")
        return errors
    blocker_ids = [item.get("id") if isinstance(item, Mapping) else None for item in raw_blockers]
    if blocker_ids != declared_source["blockers_preserved"]:
        errors.append("source-lock formal blockers were removed, reordered, or changed")
    if readiness.get("formal_run_allowed") is not False:
        errors.append("source lock must keep formal runs disabled")
    if readiness.get("paper_result_allowed") is not False:
        errors.append("source lock must keep paper results disabled")
    return errors


def audit_paths(scope_path: Path, source_lock_path: Path) -> dict[str, Any]:
    """Load and audit the checked-in scope and source-lock documents."""

    try:
        scope_bytes = scope_path.read_bytes()
        source_lock_bytes = source_lock_path.read_bytes()
        scope = json.loads(scope_bytes)
        source_lock = json.loads(source_lock_bytes)
    except (OSError, json.JSONDecodeError) as error:
        errors = [f"cannot load simulation scope inputs: {error}"]
    else:
        errors = validate_scope(
            scope,
            source_lock,
            scope_bytes=scope_bytes,
            source_lock_bytes=source_lock_bytes,
        )
    return {
        "errors": errors,
        "formal_ready": False,
        "maximum_evidence_class": "E2",
        "physical_execution_allowed": False,
        "simulation_ready": not errors,
        "slurm_submission_allowed": False,
        "timing_status": "modeled_preliminary_not_calibrated",
    }


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        type=Path,
        default=project_root / "reference" / "simulation-scope.json",
    )
    parser.add_argument(
        "--source-lock",
        type=Path,
        default=project_root / "reference" / "source-lock.json",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = audit_paths(args.scope, args.source_lock)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        status = "READY_FOR_E2_MODELED_SIMULATION" if report["simulation_ready"] else "INVALID"
        print(f"simulation-scope: {status}")
        for error in report["errors"]:
            print(f"ERROR: {error}")
    return 0 if report["simulation_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
