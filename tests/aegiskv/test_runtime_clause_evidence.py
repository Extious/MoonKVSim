from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_audit(root: Path) -> ModuleType:
    path = root / "benchmark/AegisKV/docs/patent/audit_aegiskv_runtime_contract.py"
    spec = importlib.util.spec_from_file_location("audit_aegiskv_runtime_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load runtime contract audit")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_clause_evidence_covers_contract_without_overclaim() -> None:
    root = Path(__file__).resolve().parents[2]
    result = _load_audit(root).audit_runtime_evidence(root)
    assert result["status"] == "PASS"
    assert result["clause_count"] == 27
    assert result["complete_contract_coverage"] is True
    assert result["manual_review"] == "pending"
    assert result["evidence_boundary"]["class"] == "E2"
    assert result["evidence_boundary"]["physical_execution"] is False
    assert result["evidence_boundary"]["paper_ready"] is False
    assert result["errors"] == []
