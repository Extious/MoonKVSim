#!/usr/bin/env python3
"""Audit runtime evidence without mutating the pending patent transcription."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from moonkvsim.aegiskv.experiment_config import repository_root


def audit_runtime_evidence(root: Path) -> dict[str, Any]:
    contract_path = root / "benchmark/AegisKV/docs/patent/patent-contract.yaml"
    evidence_path = root / "benchmark/AegisKV/docs/patent/runtime-clause-evidence.json"
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if not isinstance(contract, Mapping) or not isinstance(evidence, Mapping):
        raise ValueError("contract and evidence must both be mappings")
    if contract.get("manual_review") != "pending":
        errors.append("patent manual review boundary changed unexpectedly")
    if evidence.get("contract_manual_review") != "pending":
        errors.append("runtime evidence must preserve pending human review")
    if evidence.get("contract_id") != contract.get("contract_id"):
        errors.append("runtime evidence contract_id mismatch")
    interpretation = evidence.get("interpretations")
    if not isinstance(interpretation, Mapping):
        errors.append("runtime evidence interpretations must be an object")
    elif (
        interpretation.get("status") != "machine_interpretation_pending_manual_review"
        or interpretation.get("manual_review_confirmed") is not False
    ):
        errors.append("runtime evidence overclaims the D_Y interpretation review")
    expected_evidence = {
        "class": "E2",
        "scope": "modeled/preliminary",
        "calibration": "not_calibrated",
        "physical_execution": False,
        "physical_timing_claim_allowed": False,
        "formal_use_allowed": False,
        "paper_ready": False,
    }
    if evidence.get("evidence") != expected_evidence:
        errors.append("runtime evidence exceeds or changes the frozen E2 boundary")

    raw_clauses = contract.get("clauses")
    runtime_clauses = evidence.get("clauses")
    if not isinstance(raw_clauses, list) or not isinstance(runtime_clauses, list):
        errors.append("contract and runtime clauses must be arrays")
        raw_clauses = []
        runtime_clauses = []
    contract_by_id = {
        item["id"]: item for item in raw_clauses if isinstance(item, Mapping) and "id" in item
    }
    runtime_by_id = {
        item["clause_id"]: item
        for item in runtime_clauses
        if isinstance(item, Mapping) and "clause_id" in item
    }
    if len(runtime_by_id) != len(runtime_clauses):
        errors.append("runtime evidence contains duplicate or malformed clause IDs")
    if set(runtime_by_id) != set(contract_by_id):
        errors.append("runtime evidence clause coverage differs from the patent contract")
    for clause_id, clause in sorted(runtime_by_id.items()):
        contract_clause = contract_by_id.get(clause_id)
        if contract_clause is None:
            continue
        owner = clause.get("owner")
        if owner != contract_clause.get("owner"):
            errors.append(f"{clause_id}: owner differs from contract")
        if not isinstance(owner, str) or not (root / owner).is_file():
            errors.append(f"{clause_id}: runtime owner file is missing")
        tests = clause.get("tests")
        if not isinstance(tests, list) or not tests:
            errors.append(f"{clause_id}: at least one automated test file is required")
        elif any(not isinstance(path, str) or not (root / path).is_file() for path in tests):
            errors.append(f"{clause_id}: automated test file is missing")
        status = clause.get("status")
        if not isinstance(status, str) or not (
            status.startswith("automated_")
            or status == "verified_design_input_and_evidence_boundary"
        ):
            errors.append(f"{clause_id}: invalid runtime evidence status")
    return {
        "schema": "moonkvsim.aegiskv.runtime-clause-audit.v1",
        "status": "PASS" if not errors else "FAIL",
        "clause_count": len(runtime_by_id),
        "complete_contract_coverage": set(runtime_by_id) == set(contract_by_id),
        "evidence_boundary": expected_evidence,
        "manual_review": "pending",
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="MoonKVSim repository root; defaults to auto-detected checkout root.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = repository_root() if args.root is None else args.root.resolve()
    result = audit_runtime_evidence(root)
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
