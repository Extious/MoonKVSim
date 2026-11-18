from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from moonkvsim.common.hash import sha256_json

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = (
    ROOT
    / "benchmark/AegisKV/experiments/results/figures/"
    "generate_qwen3_8b_no_failure_overhead.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_test_no_failure_figures", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _distribution(count: int, value: int) -> dict[str, int]:
    return {
        "count": count,
        "min": value,
        "p05": value,
        "median": value,
        "mean": value,
        "p95": value,
        "max": value,
    }


def _protection(submitted_bytes: int) -> dict[str, Any]:
    return {
        "submitted_bytes": submitted_bytes,
        "aborted_bytes": submitted_bytes // 10,
        "by_time_phase": {
            "bootstrap_warmup": {"submitted_bytes": submitted_bytes // 4},
            "steady_state": {"submitted_bytes": submitted_bytes - submitted_bytes // 4},
        },
    }


def _artifact() -> dict[str, Any]:
    paired = []
    cells = []
    for seed in range(5):
        paired.append(
            {
                "seed": seed,
                "wct_delta_ns": _distribution(160, (seed - 2) * 1_000_000),
                "wct_delta_ns_by_cohort": {
                    "bootstrap_initial_admission": _distribution(
                        16, (seed - 2) * 2_000_000
                    ),
                    "steady_state": _distribution(144, (seed - 2) * 500_000),
                },
                "makespan": {"aegiskv_overhead_ppm_floor": seed * 100},
                "goodput": {"aegiskv_delta_ppm_floor": -seed * 100},
            }
        )
        cells.append(
            {
                "seed": seed,
                "systems": {
                    "vanilla_mooncake_dram": {
                        "protection": _protection((seed + 1) * 1024**3),
                        "workflow_admission_order_sha256": f"{seed + 1:064x}",
                    },
                    "aegiskv_unified": {
                        "protection": _protection((seed + 2) * 1024**3),
                        "workflow_admission_order_sha256": f"{seed + 1:064x}",
                    },
                },
            }
        )
    body = {
        "schema": "moonkvsim.aegiskv.no-failure-overhead.v1",
        "status": "PASS",
        "evidence": {
            "physical_execution": False,
            "paper_ready": False,
            "effect_direction_gate_applied": False,
        },
        "protocol": {
            "workflow_count": 160,
            "record_count": 1304,
            "seeds": [0, 1, 2, 3, 4],
            "workflow_admission_randomization": {
                "policy": "observed_submit_then_seeded_sha256_workflow_permutation",
                "seed_source": "paired_experiment_seed",
                "paired_systems_share_exact_permutation": True,
                "peer_placement_held_fixed": True,
            },
            "peer_binding_seed": 0,
            "scenario": "no_failure",
        },
        "audit": {
            "status": "PASS",
            "checks": {
                "seed_changes_realized_workflow_admission_order": True,
                "paired_systems_share_workflow_admission_order": True,
            },
        },
        "paired": paired,
        "cells": cells,
    }
    return {**body, "fingerprint": sha256_json(body)}


def _acceptance(artifact: dict[str, Any], artifact_path: Path) -> dict[str, Any]:
    attempt_body = {
        "attempt_id": "no-failure-v9",
        "scenario": {"kind": "NO_FAILURE"},
        "disposition": "COMPLETED",
        "artifact": {
            "path": artifact_path.name,
            "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            "fingerprint": artifact["fingerprint"],
            "raw_artifact_count": 10,
            "raw_artifact_hashes": ["1" * 64] * 10,
        },
        "gates": [
            {
                "gate": gate,
                "status": "NOT_APPLICABLE" if gate == 4 else "PASS",
                "reason_codes": [],
                "evidence": {},
            }
            for gate in range(1, 9)
        ],
        "terminal_class": "VALID",
        "accepted_for_numerical_aggregates": True,
        "allowed_panel_ids": [f"FIGURE_2_{letter}" for letter in "ABCD"],
        "statistics": {},
        "direct_classifier": None,
        "reason_codes": [],
    }
    attempt = {**attempt_body, "fingerprint": sha256_json(attempt_body)}
    body = {
        "schema": "moonkvsim.aegiskv.qwen3-8b-acceptance-manifest.v1",
        "status": "PASS",
        "registry": {
            "path": "registry.json",
            "sha256": "2" * 64,
            "fingerprint": "3" * 64,
        },
        "attempts": [attempt],
        "summary": {"VALID": 1},
        "modeled_uncalibrated": True,
        "physical_execution": False,
        "paper_ready": False,
    }
    return {**body, "fingerprint": sha256_json(body)}


def test_generator_emits_three_formats_and_hashed_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _load()
    artifact = tmp_path / "artifact.json"
    artifact_document = _artifact()
    artifact.write_text(json.dumps(artifact_document), encoding="utf-8")
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(
        json.dumps(_acceptance(artifact_document, artifact)),
        encoding="utf-8",
    )
    output = tmp_path / "figures"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generator",
            "--artifact",
            str(artifact),
            "--acceptance-manifest",
            str(acceptance),
            "--output-dir",
            str(output),
        ],
    )

    assert generator.main() == 0

    manifest = json.loads((output / "FIGURE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS"
    assert manifest["figure_count"] == 4
    assert manifest["statistics"]["all_seed_points_rendered"] is True
    assert manifest["statistics"]["interval"] == "two_sided_student_t_95_percent_df4"
    assert manifest["statistics"]["effect_direction_gate_applied"] is False
    assert manifest["acceptance_manifest"]["authorized_panel_ids"] == [
        "FIGURE_2_A",
        "FIGURE_2_B",
        "FIGURE_2_C",
        "FIGURE_2_D",
    ]
    assert {item["stem"] for item in manifest["figures"]} == set(generator.STEMS)
    for item in manifest["figures"]:
        assert set(item["files"]) == {"png", "svg", "pdf"}
        for description in item["files"].values():
            assert len(description["sha256"]) == 64
            assert (output / description["file"]).is_file()
    unsigned = dict(manifest)
    fingerprint = unsigned.pop("fingerprint")
    assert fingerprint == sha256_json(unsigned)


def test_generator_rejects_unvalidated_snapshot(tmp_path: Path) -> None:
    generator = _load()
    artifact = _artifact()
    artifact["status"] = "UNVALIDATED"
    path = tmp_path / "unvalidated.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(ValueError, match="PASS"):
        generator._load(path)


def test_generator_rejects_deterministic_repeats(tmp_path: Path) -> None:
    generator = _load()
    artifact = _artifact()
    for cell in artifact["cells"]:
        for system in cell["systems"].values():
            system["workflow_admission_order_sha256"] = "1" * 64
    unsigned = dict(artifact)
    unsigned.pop("fingerprint")
    artifact["fingerprint"] = sha256_json(unsigned)
    path = tmp_path / "repeats.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(ValueError, match="deterministic repeats"):
        generator._load(path)


def test_generator_rejects_unaccepted_artifact(tmp_path: Path) -> None:
    generator = _load()
    artifact_document = _artifact()
    artifact = tmp_path / "artifact.json"
    artifact.write_text(json.dumps(artifact_document), encoding="utf-8")
    acceptance = _acceptance(artifact_document, artifact)
    acceptance["attempts"][0]["allowed_panel_ids"] = ["FIGURE_2_A"]
    unsigned = dict(acceptance)
    unsigned.pop("fingerprint")
    acceptance["fingerprint"] = sha256_json(unsigned)
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps(acceptance), encoding="utf-8")

    with pytest.raises(ValueError, match="does not authorize"):
        generator._load_acceptance(
            path,
            artifact_path=artifact,
            artifact=artifact_document,
        )
