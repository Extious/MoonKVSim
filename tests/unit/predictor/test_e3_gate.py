from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from moonkvsim.common.hash import canonical_json_bytes
from moonkvsim.predictor import (
    AICONFIGURATOR_PINNED_COMMIT,
    AICONFIGURATOR_PINNED_VERSION,
    AIConfiguratorE3Error,
    AIConfiguratorProfileSelection,
    AIConfiguratorSupportManifest,
    ForwardBoundary,
    HeldOutCalibrationRecord,
    PredictionPhase,
    PredictionProfile,
    SelectedDatabaseFile,
    database_bundle_fingerprint,
    evaluate_e3_readiness,
    load_aiconfigurator_profile_selection,
)

_DATABASE_CONTENTS = {
    "systems/data/test/vllm/test/context_attention_perf.txt": b"context-row\n",
    "systems/data/test/vllm/test/generation_attention_perf.txt": b"generation-row\n",
}
_RAW_FORWARD = b'{"phase":"prefill"}\n{"phase":"decode"}\n'
_HELD_OUT_SPLIT = b'{"split":"fixture"}'


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _calibration_contents(profile_fingerprint: str) -> dict[str, bytes]:
    threshold_path = "calibration/residual-thresholds.json"
    thresholds = canonical_json_bytes(
        {
            "schema": "moonkvsim.aiconfigurator-residual-thresholds.v1",
            "profile_fingerprint": profile_fingerprint,
            "calibration_method": "phase_shape_residual_table",
            "shape_axes": ["batch_size", "extend_length", "past_kv_length"],
            "phase_thresholds": {
                phase: {
                    "max_mean_absolute_percentage_error": 0.2,
                    "max_p95_absolute_relative_error": 0.3,
                }
                for phase in ("prefill", "decode")
            },
        }
    )
    report = canonical_json_bytes(
        {
            "schema": "moonkvsim.aiconfigurator-held-out-residual-report.v1",
            "profile_fingerprint": profile_fingerprint,
            "source_evidence_sha256": _sha256(_RAW_FORWARD),
            "held_out_split_manifest_sha256": _sha256(_HELD_OUT_SPLIT),
            "calibration_method": "phase_shape_residual_table",
            "shape_axes": ["batch_size", "extend_length", "past_kv_length"],
            "threshold_declaration": {
                "path": threshold_path,
                "sha256": _sha256(thresholds),
                "size_bytes": len(thresholds),
            },
            "phase_results": {
                phase: {
                    "sample_count": 10,
                    "residual_bucket_count": 3,
                    "mean_absolute_percentage_error": 0.1,
                    "p95_absolute_relative_error": 0.2,
                    "passed": True,
                }
                for phase in ("prefill", "decode")
            },
            "formal_use_allowed": True,
        }
    )
    return {
        "calibration/held-out-residual-report.json": report,
        "calibration/raw-forward.jsonl": _RAW_FORWARD,
        "calibration/held-out-split.json": _HELD_OUT_SPLIT,
        threshold_path: thresholds,
    }


def _selection() -> AIConfiguratorProfileSelection:
    """Return an internally complete test fixture, never a measured profile."""

    database_files = (
        SelectedDatabaseFile(
            path="systems/data/test/vllm/test/context_attention_perf.txt",
            sha256=_sha256(
                _DATABASE_CONTENTS[
                    "systems/data/test/vllm/test/context_attention_perf.txt"
                ]
            ),
            size_bytes=len(
                _DATABASE_CONTENTS[
                    "systems/data/test/vllm/test/context_attention_perf.txt"
                ]
            ),
        ),
        SelectedDatabaseFile(
            path="systems/data/test/vllm/test/generation_attention_perf.txt",
            sha256=_sha256(
                _DATABASE_CONTENTS[
                    "systems/data/test/vllm/test/generation_attention_perf.txt"
                ]
            ),
            size_bytes=len(
                _DATABASE_CONTENTS[
                    "systems/data/test/vllm/test/generation_attention_perf.txt"
                ]
            ),
        ),
    )
    profile = PredictionProfile(
        provider_name="aiconfigurator",
        provider_version=AICONFIGURATOR_PINNED_VERSION,
        provider_source_revision=AICONFIGURATOR_PINNED_COMMIT,
        database_mode="SILICON-test-fixture",
        database_sha256=database_bundle_fingerprint(database_files),
        hardware_profile_id="test-fixture-gpu",
        hardware_profile_fingerprint="3" * 64,
        model_id="test-fixture/model",
        model_revision="test-fixture-revision",
        tensor_parallel_size=1,
        pipeline_parallel_size=1,
        forward_boundary=ForwardBoundary(includes_model_collectives=False),
    )
    support = AIConfiguratorSupportManifest(
        provider_version=profile.provider_version,
        provider_source_revision=profile.provider_source_revision,
        profile_fingerprint=profile.fingerprint,
        backend_name="vllm",
        database_mode=profile.database_mode,
        database_sha256=profile.database_sha256,
        hardware_profile_id=profile.hardware_profile_id,
        hardware_profile_fingerprint=profile.hardware_profile_fingerprint,
        model_id=profile.model_id,
        model_revision=profile.model_revision,
        tensor_parallel_size=profile.tensor_parallel_size,
        pipeline_parallel_size=profile.pipeline_parallel_size,
        supported_phases=(PredictionPhase.PREFILL, PredictionPhase.DECODE),
    )
    calibration_contents = _calibration_contents(profile.fingerprint)
    calibration = HeldOutCalibrationRecord(
        report_fingerprint=_sha256(
            calibration_contents["calibration/held-out-residual-report.json"]
        ),
        report_path="calibration/held-out-residual-report.json",
        report_size_bytes=len(
            calibration_contents["calibration/held-out-residual-report.json"]
        ),
        profile_fingerprint=profile.fingerprint,
        source_evidence_sha256=_sha256(_RAW_FORWARD),
        source_evidence_path="calibration/raw-forward.jsonl",
        source_evidence_size_bytes=len(_RAW_FORWARD),
        held_out_split_manifest_sha256=_sha256(_HELD_OUT_SPLIT),
        held_out_split_manifest_path="calibration/held-out-split.json",
        held_out_split_manifest_size_bytes=len(_HELD_OUT_SPLIT),
        calibration_method="phase_shape_residual_table",
        shape_axes=("batch_size", "extend_length", "past_kv_length"),
        prefill_sample_count=10,
        decode_sample_count=10,
        prefill_residual_bucket_count=3,
        decode_residual_bucket_count=3,
        formal_use_allowed=True,
    )
    return AIConfiguratorProfileSelection(
        profile=profile,
        support=support,
        target_backend_version="test-backend",
        database_backend_version="test-backend",
        database_files=database_files,
        calibration=calibration,
        formal_use_allowed=True,
    )


def _write_document(path: Path, document: dict[str, Any]) -> None:
    path.write_bytes(canonical_json_bytes(document))


def _materialize_fixture(
    root: Path, selection: AIConfiguratorProfileSelection | None = None
) -> None:
    selected = _selection() if selection is None else selection
    for relative_path, contents in {
        **_DATABASE_CONTENTS,
        **_calibration_contents(selected.profile.fingerprint),
    }.items():
        output = root / relative_path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(contents)


def test_complete_phase_shape_held_out_record_passes_e3_gate(tmp_path: Path) -> None:
    selection = _selection()
    path = tmp_path / "selection.json"
    _materialize_fixture(tmp_path)
    path.write_bytes(selection.to_json_bytes())

    loaded = load_aiconfigurator_profile_selection(
        path,
        installed_version=AICONFIGURATOR_PINNED_VERSION,
    )

    assert loaded.to_json_bytes() == selection.to_json_bytes()
    assert evaluate_e3_readiness(
        loaded,
        installed_version=AICONFIGURATOR_PINNED_VERSION,
    ).ready


def test_in_memory_claims_without_materialized_files_cannot_pass_e3() -> None:
    codes = {
        item.code
        for item in evaluate_e3_readiness(
            _selection(),
            installed_version=AICONFIGURATOR_PINNED_VERSION,
        ).diagnostics
    }

    assert "materialized_database_evidence_unverified" in codes
    assert "materialized_calibration_evidence_unverified" in codes


def test_missing_profile_selection_or_database_or_held_out_record_fails_closed() -> None:
    unresolved = evaluate_e3_readiness(None, installed_version=AICONFIGURATOR_PINNED_VERSION)
    assert {item.code for item in unresolved.diagnostics} == {
        "profile_selection_unresolved"
    }

    no_database = replace(_selection(), database_files=())
    no_database_codes = {
        item.code
        for item in evaluate_e3_readiness(
            no_database,
            installed_version=AICONFIGURATOR_PINNED_VERSION,
        ).diagnostics
    }
    assert "database_bundle_missing" in no_database_codes

    no_calibration = replace(_selection(), calibration=None)
    no_calibration_result = evaluate_e3_readiness(
        no_calibration,
        installed_version=AICONFIGURATOR_PINNED_VERSION,
    )
    assert "held_out_calibration_missing" in {
        item.code for item in no_calibration_result.diagnostics
    }
    with pytest.raises(AIConfiguratorE3Error, match="held_out_calibration_missing"):
        no_calibration_result.require_ready()


def test_backend_version_mismatch_and_preliminary_evidence_cannot_pass_e3() -> None:
    calibration = _selection().calibration
    assert calibration is not None
    preliminary = replace(
        _selection(),
        database_backend_version="vllm-older",
        formal_use_allowed=False,
        calibration=replace(calibration, formal_use_allowed=False),
    )

    codes = {
        item.code
        for item in evaluate_e3_readiness(
            preliminary,
            installed_version=AICONFIGURATOR_PINNED_VERSION,
        ).diagnostics
    }

    assert {
        "backend_database_version_mismatch",
        "held_out_calibration_preliminary",
        "selection_not_approved",
    }.issubset(codes)


def test_loader_rejects_global_scale_factor_and_noncanonical_json(tmp_path: Path) -> None:
    document = _selection().to_dict()
    calibration = cast(dict[str, Any], document["calibration"])
    calibration["global_scale_factor"] = 1.25
    injected = tmp_path / "global-scale.json"
    _write_document(injected, document)

    with pytest.raises(AIConfiguratorE3Error, match="global_scale_factor"):
        load_aiconfigurator_profile_selection(
            injected,
            installed_version=AICONFIGURATOR_PINNED_VERSION,
        )

    noncanonical = tmp_path / "pretty.json"
    noncanonical.write_text("{\n  \"schema\": \"invalid\"\n}\n", encoding="utf-8")
    with pytest.raises(AIConfiguratorE3Error, match="not_canonical"):
        load_aiconfigurator_profile_selection(
            noncanonical,
            installed_version=AICONFIGURATOR_PINNED_VERSION,
        )


def test_loader_rejects_absent_selection_file(tmp_path: Path) -> None:
    with pytest.raises(AIConfiguratorE3Error, match="file_unavailable"):
        load_aiconfigurator_profile_selection(
            tmp_path / "missing.json",
            installed_version=AICONFIGURATOR_PINNED_VERSION,
        )


@pytest.mark.parametrize(
    ("relative_path", "expected_fragment"),
    [
        (
            "systems/data/test/vllm/test/context_attention_perf.txt",
            "database file",
        ),
        ("calibration/held-out-residual-report.json", "held-out residual report"),
        ("calibration/raw-forward.jsonl", "raw calibration source evidence"),
        ("calibration/held-out-split.json", "held-out split manifest"),
        ("calibration/residual-thresholds.json", "predeclared residual thresholds"),
    ],
)
def test_loader_rejects_missing_or_tampered_materialized_artifacts(
    tmp_path: Path,
    relative_path: str,
    expected_fragment: str,
) -> None:
    selection = _selection()
    _materialize_fixture(tmp_path)
    path = tmp_path / "selection.json"
    path.write_bytes(selection.to_json_bytes())
    (tmp_path / relative_path).write_bytes(b"tampered")

    with pytest.raises(AIConfiguratorE3Error, match=expected_fragment):
        load_aiconfigurator_profile_selection(
            path,
            installed_version=AICONFIGURATOR_PINNED_VERSION,
            require_e3=False,
        )


def test_loader_rejects_symlinked_selection_database_and_calibration_files(
    tmp_path: Path,
) -> None:
    selection = _selection()
    _materialize_fixture(tmp_path)
    path = tmp_path / "selection.json"
    path.write_bytes(selection.to_json_bytes())

    selection_link = tmp_path / "selection-link.json"
    selection_link.symlink_to(path.name)
    with pytest.raises(AIConfiguratorE3Error, match="file_unavailable"):
        load_aiconfigurator_profile_selection(
            selection_link,
            installed_version=AICONFIGURATOR_PINNED_VERSION,
        )

    database_path = tmp_path / next(iter(_DATABASE_CONTENTS))
    database_target = tmp_path / "database-target.txt"
    database_target.write_bytes(database_path.read_bytes())
    database_path.unlink()
    database_path.symlink_to(os.path.relpath(database_target, database_path.parent))
    with pytest.raises(AIConfiguratorE3Error, match="artifact_verification_failed"):
        load_aiconfigurator_profile_selection(
            path,
            installed_version=AICONFIGURATOR_PINNED_VERSION,
        )

    database_path.unlink()
    database_path.write_bytes(_DATABASE_CONTENTS[next(iter(_DATABASE_CONTENTS))])
    report_path = tmp_path / "calibration/held-out-residual-report.json"
    report_target = tmp_path / "report-target.json"
    report_target.write_bytes(report_path.read_bytes())
    report_path.unlink()
    report_path.symlink_to(os.path.relpath(report_target, report_path.parent))
    with pytest.raises(AIConfiguratorE3Error, match="artifact_verification_failed"):
        load_aiconfigurator_profile_selection(
            path,
            installed_version=AICONFIGURATOR_PINNED_VERSION,
        )


def test_formal_loader_rejects_preliminary_and_spoofed_boundary(
    tmp_path: Path,
) -> None:
    _materialize_fixture(tmp_path)
    preliminary = _selection().to_dict()
    calibration = cast(dict[str, Any], preliminary["calibration"])
    calibration["formal_use_allowed"] = False
    preliminary["formal_use_allowed"] = False
    path = tmp_path / "selection.json"
    _write_document(path, preliminary)
    with pytest.raises(AIConfiguratorE3Error, match="formal selection loader"):
        load_aiconfigurator_profile_selection(
            path,
            installed_version=AICONFIGURATOR_PINNED_VERSION,
            require_e3=False,
        )

    spoofed = _selection().to_dict()
    profile = cast(dict[str, Any], spoofed["profile"])
    boundary = cast(dict[str, Any], profile["forward_boundary"])
    boundary["included_components"] = ["model_forward", "scheduler"]
    _write_document(path, spoofed)
    with pytest.raises(AIConfiguratorE3Error, match="fixed contract"):
        load_aiconfigurator_profile_selection(
            path,
            installed_version=AICONFIGURATOR_PINNED_VERSION,
            require_e3=False,
        )


@pytest.mark.parametrize(
    ("mutation", "expected_fragment"),
    [
        ("wrong_profile", "profile_fingerprint mismatch"),
        ("wrong_count", "counts do not match selection"),
        ("false_pass", "passed flag does not match"),
    ],
)
def test_hash_valid_but_semantically_false_residual_report_is_rejected(
    tmp_path: Path,
    mutation: str,
    expected_fragment: str,
) -> None:
    selection = _selection()
    contents = _calibration_contents(selection.profile.fingerprint)
    report_path = "calibration/held-out-residual-report.json"
    report = cast(dict[str, Any], json.loads(contents[report_path]))
    if mutation == "wrong_profile":
        report["profile_fingerprint"] = "f" * 64
    else:
        phases = cast(dict[str, Any], report["phase_results"])
        prefill = cast(dict[str, Any], phases["prefill"])
        if mutation == "wrong_count":
            prefill["sample_count"] = 9
        else:
            prefill["mean_absolute_percentage_error"] = 0.9
    changed_report = canonical_json_bytes(report)
    calibration = selection.calibration
    assert calibration is not None
    selection = replace(
        selection,
        calibration=replace(
            calibration,
            report_fingerprint=_sha256(changed_report),
            report_size_bytes=len(changed_report),
        ),
    )
    _materialize_fixture(tmp_path, selection)
    (tmp_path / report_path).write_bytes(changed_report)
    path = tmp_path / "selection.json"
    path.write_bytes(selection.to_json_bytes())

    with pytest.raises(AIConfiguratorE3Error, match=expected_fragment):
        load_aiconfigurator_profile_selection(
            path,
            installed_version=AICONFIGURATOR_PINNED_VERSION,
            require_e3=False,
        )
