from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
DOCS_ROOT = ROOT / "benchmark/AegisKV/docs"
AUDIT_PATH = DOCS_ROOT / "audit_patent_contract.py"


def _load_audit_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("aegiskv_patent_contract_audit", AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AUDIT = _load_audit_module()


def test_authoritative_bundle_passes_fail_closed_audit() -> None:
    assert AUDIT.audit_bundle(DOCS_ROOT, ROOT) == []


def test_contract_has_complete_ordered_coverage_and_unique_tests() -> None:
    contract = AUDIT.load_contract(DOCS_ROOT / "design/patent-contract.yaml")
    clauses = contract["clauses"]

    assert [clause["id"] for clause in clauses] == list(AUDIT.REQUIRED_CLAUSE_IDS)
    assert contract["coverage"]["required_categories"] == list(AUDIT.REQUIRED_CATEGORIES)
    assert {clause["category"] for clause in clauses} == set(AUDIT.REQUIRED_CATEGORIES)
    assert len({clause["test_id"] for clause in clauses}) == len(clauses)
    assert all(clause["owner"].startswith("python/moonkvsim/aegiskv/") for clause in clauses)


def test_missing_patent_clause_fails_closed() -> None:
    contract = copy.deepcopy(AUDIT.load_contract(DOCS_ROOT / "design/patent-contract.yaml"))
    manifest = AUDIT.load_manifest(DOCS_ROOT / "provenance/SOURCE_MANIFEST.json")
    contract["clauses"] = contract["clauses"][:-1]

    errors = AUDIT.validate_contract(contract, manifest)

    assert any("required clause ids are missing" in error for error in errors)


def test_unknown_semantic_or_implementation_overclaim_fails_closed() -> None:
    contract = copy.deepcopy(AUDIT.load_contract(DOCS_ROOT / "design/patent-contract.yaml"))
    manifest = AUDIT.load_manifest(DOCS_ROOT / "provenance/SOURCE_MANIFEST.json")
    contract["semantic_sets"]["forbidden_semantics"].append("unreviewed_new_semantic")
    contract["manual_review"] = "complete"
    contract["clauses"][1]["status"] = "implemented"

    errors = AUDIT.validate_contract(contract, manifest)

    assert any("forbidden_semantics" in error for error in errors)
    assert any("manual_review" in error for error in errors)
    assert any("specified_unimplemented" in error for error in errors)


def test_source_manifest_rejects_any_second_input() -> None:
    manifest = copy.deepcopy(
        AUDIT.load_manifest(DOCS_ROOT / "provenance/SOURCE_MANIFEST.json")
    )
    manifest["source_count"] = 2
    manifest["sources"].append(copy.deepcopy(manifest["sources"][0]))

    errors = AUDIT.validate_manifest(manifest)

    assert any("source_count" in error for error in errors)
    assert any("exactly the current patent input" in error for error in errors)


def test_duplicate_yaml_key_is_rejected(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema: first\nschema: second\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate YAML key"):
        AUDIT.load_contract(duplicate)


def test_manifest_and_contract_bind_the_actual_patent_hash() -> None:
    contract = AUDIT.load_contract(DOCS_ROOT / "design/patent-contract.yaml")
    manifest = AUDIT.load_manifest(DOCS_ROOT / "provenance/SOURCE_MANIFEST.json")
    patent = ROOT / AUDIT.PATENT_PATH

    assert AUDIT.sha256_file(patent) == AUDIT.PATENT_SHA256
    assert contract["authority"]["sha256"] == AUDIT.PATENT_SHA256
    assert manifest["source_count"] == 1
    assert manifest["sources"][0]["destination_sha256"] == AUDIT.PATENT_SHA256


def test_sha256sums_is_accepted_by_sha256sum() -> None:
    executable = shutil.which("sha256sum")
    assert executable is not None
    result = subprocess.run(
        [executable, "--strict", "-c", "benchmark/AegisKV/docs/provenance/SHA256SUMS"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_audit_cli_emits_machine_readable_pass() -> None:
    result = subprocess.run(
        [sys.executable, str(AUDIT_PATH), "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert payload == {
        "error_count": 0,
        "errors": [],
        "schema": "moonkvsim.aegiskv.patent-contract-audit.v1",
        "status": "PASS",
    }
