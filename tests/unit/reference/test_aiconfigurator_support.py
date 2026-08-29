from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from moonkvsim.common.hash import canonical_json_bytes


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load() -> tuple[Path, dict[str, Any]]:
    path = _root() / "reference/aiconfigurator-support.json"
    raw = path.read_bytes()
    document = json.loads(raw)
    assert isinstance(document, dict)
    assert raw == canonical_json_bytes(document) + b"\n"
    return path, document


def test_target_profile_is_explicitly_unsupported_and_unselected() -> None:
    _, document = _load()
    decision = cast(dict[str, Any], document["decision"])

    assert decision["status"] == "UNSUPPORTED_FOR_TARGET_PROFILE"
    assert decision["formal_use_allowed"] is False
    assert decision["src_block_001_cleared"] is False
    assert decision["selected_profile"] is None
    assert decision["selected_database_sha256"] is None
    assert decision["held_out_calibration_report"] is None
    assert {
        item["code"] for item in decision["diagnostics"]
    } == {
        "target_backend_version_unsupported",
        "a100_pcie_database_missing",
        "prefill_128k_shape_uncovered",
        "decode_128k_shape_uncovered",
        "exact_mixed_vector_mapping_unavailable",
        "held_out_residuals_missing",
    }


def test_vllm_database_inventory_is_backend_isolated_and_shape_bounded() -> None:
    _, document = _load()
    systems = {item["hardware_profile_id"]: item for item in document["systems"]}

    for system_name in ("l40s", "a100_sxm"):
        system = systems[system_name]
        assert system["target_vllm_support"]["backend_version"] == "1.2.2"
        assert system["target_vllm_support"]["agg_supported"] is False
        assert system["target_vllm_support"]["disagg_supported"] is False
        assert system["nearest_reference_vllm_support"]["backend_version"] == "0.14.0"
        assert system["nearest_reference_vllm_support"]["agg_supported"] is True
        coverage = system["qwen3_8b_bf16_shape_coverage"]
        assert coverage["prefill"]["max_extend_length"] == 16384
        assert coverage["prefill"]["covers_131072"] is False
        assert coverage["decode"]["max_past_kv_length"] == 32767
        assert coverage["decode"]["covers_131072"] is False
        assert coverage["mixed"]["supported"] is False
        assert system["selection_eligible"] is False

    assert systems["a100_pcie"]["reference_vllm_database_bundle"] is None
    isolation = document["database_backend_isolation"]
    assert isolation["sglang_database_reuse_for_vllm"] == "forbidden"
    assert isolation["trtllm_database_reuse_for_vllm"] == "forbidden"


def test_reference_sdk_golden_is_hash_bound_and_never_formal() -> None:
    _, document = _load()
    golden_record = document["sdk_reference_golden"]
    golden_path = _root() / golden_record["path"]

    assert hashlib.sha256(golden_path.read_bytes()).hexdigest() == golden_record["sha256"]
    assert golden_record["formal_use_allowed"] is False
    assert golden_record["scenario_count"] == 8
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    assert golden["formal_use_allowed"] is False
    assert golden["evidence_class"] == "E2_reference_sdk_semantics_only"
    assert len(golden["scenarios"]) == 8


def test_real_sdk_generator_refuses_project_interpreter_without_silent_skip() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(_root() / "scripts/generate_aiconfigurator_sdk_golden.py"),
            "--check",
        ],
        cwd=_root(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "wrong interpreter" in completed.stderr
