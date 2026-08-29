from __future__ import annotations

import copy
import errno
import hashlib
import json
import shutil
import tempfile
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import moonkvsim.output.run_bundle as run_bundle_module
from moonkvsim.common.hash import sha256_json
from moonkvsim.config import ResolvedConfigBundle
from moonkvsim.output import (
    RunArtifactBundleError,
    RunManifestInputs,
    build_run_manifest,
    publish_run_artifact_bundle,
    verify_run_artifact_bundle,
    write_event_journal_jsonl,
)
from moonkvsim.simulation.journal import EventJournal

_CORE = {"SHA256SUMS", "manifest.json", "resolved-config.json"}
_SECTION_16 = {
    "event-journal.jsonl",
    "trace-audit.json",
    "context-coverage.json",
    "workflow-metrics.parquet",
    "request-metrics.parquet",
    "batch-events.parquet",
    "kv-residency-events.parquet",
    "kv-transfer-events.parquet",
    "physical-allocation-events.parquet",
    "resource-ledger-deltas.parquet",
    "resource-ledger-snapshots.parquet",
    "flow-rate-events.parquet",
    "resource-utilization.parquet",
    "store-directory-snapshots.parquet",
    "failure-events.parquet",
    "recovery-events.parquet",
    "capacity-audit.json",
    "run-audit.json",
    "summary.json",
}
_BOUNDS = (
    (0, 8192),
    (8192, 32768),
    (32768, 65536),
    (65536, 98304),
    (98304, 131072),
)


@pytest.fixture
def atomic_tmp_path() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(dir="/tmp", prefix="moonkvsim-run-bundle-test-"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


def _config_bundle(
    *, predictor_database_sha256: str | None = "a" * 64
) -> ResolvedConfigBundle:
    requests: dict[str, Any] = {
        "seed": 17,
        "workload": {
            "dataset": "real-trace",
            "trace_sha256": "4" * 64,
            "provenance": {
                "license": "Apache-2.0",
                "access_level": "public",
                "collection_interval": None,
                "content_availability": "source_hash_ids_only",
            },
        },
        "trace_token_count": {"mode": "source_hash_blocks_64"},
        "target_model_tokenizer": {
            "model_id": "Qwen/Qwen3-8B",
            "revision": "model-revision",
            "tokenizer_config_sha256": "7" * 64,
            "chat_template_sha256": "8" * 64,
        },
        "context": {"required_observed_context_buckets": [upper for _lower, upper in _BOUNDS]},
    }
    failure: dict[str, Any] = {"enabled": False, "events": []}
    deployment: dict[str, Any] = {
        "model": {
            "id": "Qwen/Qwen3-8B",
            "revision": "model-revision",
            "config_sha256": "5" * 64,
        },
        "predictor": {
            "kind": "aiconfigurator",
            "profile": "test-profile",
            "database_sha256": predictor_database_sha256,
        },
    }
    return ResolvedConfigBundle(
        requests=requests,
        failure=failure,
        deployment=deployment,
        requests_sha256=sha256_json(requests),
        failure_sha256=sha256_json(failure),
        deployment_sha256=sha256_json(deployment),
    )


def _manifest_inputs(
    *,
    present_extra: tuple[str, ...] = (),
    missing: tuple[str, ...] = (),
    status: str = "incomplete",
    predictor_database_sha256: str | None = "a" * 64,
) -> RunManifestInputs:
    present = sorted(_CORE | set(present_extra))
    declared_missing = sorted((_SECTION_16 - set(present)) | set(missing))
    expected = sorted(set(present) | set(declared_missing))
    return RunManifestInputs(
        run_id="run-17",
        code={
            "commit": "b" * 40,
            "dirty": False,
            "dirty_patch_sha256": None,
        },
        source_lock_sha256="9" * 64,
        predictor_database_sha256=predictor_database_sha256,
        trace={
            "dataset": "real-trace",
            "raw_sha256": "1" * 64,
            "normalized_sha256": "2" * 64,
            "normalizer_sha256": "3" * 64,
            "workload_trace_sha256": "4" * 64,
            "provenance": {
                "license": "Apache-2.0",
                "access_level": "public",
                "collection_interval": None,
                "content_availability": "source_hash_ids_only",
                "evidence_class": "real_trace_shape_replay",
                "token_count_mode": "source_hash_blocks_64",
            },
        },
        target_model={
            "model_id": "Qwen/Qwen3-8B",
            "model_revision": "model-revision",
            "model_config_sha256": "5" * 64,
            "tokenizer_sha256": "6" * 64,
            "tokenizer_config_sha256": "7" * 64,
            "chat_template_sha256": "8" * 64,
        },
        coverage={
            "workflow_count": 1,
            "span_count": 1,
            "sample_count": 1,
            "context_buckets": [
                {
                    "lower_exclusive": lower,
                    "upper_inclusive": upper,
                    "request_count": int(index == 0),
                    "workflow_count": int(index == 0),
                }
                for index, (lower, upper) in enumerate(_BOUNDS)
            ],
        },
        integrity={
            "synthetic": False,
            "truncated_count": 0,
            "overflow_count": 0,
        },
        seed=17,
        virtual_time={"start_ns": 0, "end_ns": 1_000},
        validation={
            "evidence_class": "E2",
            "schema_validation": "pass",
            "trace_audit": "pass",
            "calibration_status": "not_required",
        },
        result_completeness={
            "status": status,
            "expected_artifacts": expected,
            "present_artifacts": present,
            "missing_artifacts": declared_missing,
        },
    )


def _journal_writer(directory: Path) -> None:
    journal = EventJournal()
    journal.append(0, "RUN_STARTED", {"run_id": "run-17"})
    write_event_journal_jsonl(journal, directory / "event-journal.jsonl")


def _file_snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_manifest_derives_only_config_hashes_and_binds_explicit_inputs() -> None:
    bundle = _config_bundle()
    inputs = _manifest_inputs()

    manifest = build_run_manifest(bundle, inputs)

    assert manifest["config_hashes"] == {
        "requests": bundle.requests_sha256,
        "failure": bundle.failure_sha256,
        "deployment": bundle.deployment_sha256,
        "resolved_config": bundle.sha256,
    }
    assert manifest["code"] == inputs.code
    assert manifest["predictor_database_sha256"] == inputs.predictor_database_sha256
    assert manifest["trace"] == inputs.trace
    assert manifest["target_model"] == inputs.target_model
    assert manifest["coverage"] == inputs.coverage
    assert manifest["validation"] == inputs.validation


def test_e2_manifest_records_absent_predictor_database_as_null() -> None:
    bundle = _config_bundle(predictor_database_sha256=None)
    inputs = _manifest_inputs(predictor_database_sha256=None)

    manifest = build_run_manifest(bundle, inputs)

    assert manifest["predictor_database_sha256"] is None


def test_predictor_database_hash_must_match_resolved_deployment() -> None:
    with pytest.raises(RunArtifactBundleError, match="predictor_database_sha256"):
        build_run_manifest(
            _config_bundle(),
            _manifest_inputs(predictor_database_sha256="c" * 64),
        )


def test_e3_manifest_requires_a_concrete_predictor_database_hash() -> None:
    inputs = _manifest_inputs(predictor_database_sha256=None)
    inputs = replace(
        inputs,
        validation={
            **inputs.validation,
            "evidence_class": "E3",
            "calibration_status": "pass",
        },
    )

    with pytest.raises(RunArtifactBundleError, match="concrete predictor database"):
        build_run_manifest(
            _config_bundle(predictor_database_sha256=None),
            inputs,
        )


def test_e5_manifest_fails_closed_on_missing_formal_run_prerequisites() -> None:
    inputs = _manifest_inputs()
    inputs = replace(
        inputs,
        validation={
            **inputs.validation,
            "evidence_class": "E5",
            "calibration_status": "pass",
        },
    )

    with pytest.raises(RunArtifactBundleError) as captured:
        build_run_manifest(_config_bundle(), inputs)

    message = str(captured.value)
    assert "non-empty trace collection interval" in message
    assert "complete result artifact matrix" in message
    assert "observed requests/workflows in every context bucket" in message
    assert "calibrated registration timing" in message


def test_e5_manifest_accepts_only_an_explicit_formal_input_set() -> None:
    base = _config_bundle()
    requests = copy.deepcopy(dict(base.requests))
    requests["workload"]["provenance"]["collection_interval"] = (
        "2026-06-21T00:00:00Z/2026-06-22T00:00:00Z"
    )
    deployment = copy.deepcopy(dict(base.deployment))
    deployment["network"] = {
        "registration": {"mode": "calibrated", "workers_per_context": 1}
    }
    bundle = ResolvedConfigBundle(
        requests=requests,
        failure=base.failure,
        deployment=deployment,
        requests_sha256=sha256_json(requests),
        failure_sha256=base.failure_sha256,
        deployment_sha256=sha256_json(deployment),
    )
    inputs = _manifest_inputs(
        present_extra=tuple(_SECTION_16),
        status="complete",
    )
    inputs = replace(
        inputs,
        trace={
            **inputs.trace,
            "provenance": {
                **inputs.trace["provenance"],
                "collection_interval": (
                    "2026-06-21T00:00:00Z/2026-06-22T00:00:00Z"
                ),
            },
        },
        coverage={
            **inputs.coverage,
            "sample_count": 5,
            "context_buckets": [
                {**bucket, "request_count": 1, "workflow_count": 1}
                for bucket in inputs.coverage["context_buckets"]
            ],
        },
        validation={
            **inputs.validation,
            "evidence_class": "E5",
            "calibration_status": "pass",
        },
    )

    manifest = build_run_manifest(bundle, inputs)

    assert manifest["validation"]["evidence_class"] == "E5"
    assert manifest["result_completeness"]["status"] == "complete"


def test_complete_manifest_cannot_omit_mandatory_section_16_outputs() -> None:
    inputs = replace(
        _manifest_inputs(),
        result_completeness={
            "status": "complete",
            "expected_artifacts": sorted(_CORE),
            "present_artifacts": sorted(_CORE),
            "missing_artifacts": [],
        },
    )

    with pytest.raises(RunArtifactBundleError, match="omits mandatory section-16"):
        build_run_manifest(_config_bundle(), inputs)


def test_complete_status_cannot_hide_declared_missing_outputs() -> None:
    inputs = replace(
        _manifest_inputs(),
        result_completeness={
            **_manifest_inputs().result_completeness,
            "status": "complete",
        },
    )

    with pytest.raises(ValueError, match="complete status requires no missing artifacts"):
        build_run_manifest(_config_bundle(), inputs)


def test_incomplete_status_requires_a_declared_missing_output() -> None:
    all_artifacts = sorted(_CORE | _SECTION_16)
    inputs = replace(
        _manifest_inputs(),
        result_completeness={
            "status": "incomplete",
            "expected_artifacts": all_artifacts,
            "present_artifacts": all_artifacts,
            "missing_artifacts": [],
        },
    )

    with pytest.raises(ValueError, match="incomplete status requires at least one"):
        build_run_manifest(_config_bundle(), inputs)


def test_publish_is_atomic_deterministic_and_strict_no_clobber(
    atomic_tmp_path: Path,
) -> None:
    bundle = _config_bundle()
    inputs = _manifest_inputs(present_extra=("event-journal.jsonl",))
    first = atomic_tmp_path / "first"
    second = atomic_tmp_path / "second"

    def first_writer(staging: Path) -> None:
        assert not first.exists()
        _journal_writer(staging)

    result = publish_run_artifact_bundle(
        first,
        config_bundle=bundle,
        manifest_inputs=inputs,
        artifact_writer=first_writer,
    )
    publish_run_artifact_bundle(
        second,
        config_bundle=bundle,
        manifest_inputs=copy.deepcopy(inputs),
        artifact_writer=_journal_writer,
    )

    assert result.directory == first
    assert _file_snapshot(first) == _file_snapshot(second)
    assert set(_file_snapshot(first)) == _CORE | {"event-journal.jsonl"}
    assert (
        result.sha256_for("resolved-config.json")
        == hashlib.sha256(bundle.to_json_bytes()).hexdigest()
    )
    verify_run_artifact_bundle(first, config_bundle=bundle)

    original = _file_snapshot(first)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        publish_run_artifact_bundle(
            first,
            config_bundle=bundle,
            manifest_inputs=inputs,
            artifact_writer=_journal_writer,
        )
    assert _file_snapshot(first) == original

    preexisting_empty = atomic_tmp_path / "preexisting-empty"
    preexisting_empty.mkdir()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        publish_run_artifact_bundle(
            preexisting_empty,
            config_bundle=bundle,
            manifest_inputs=_manifest_inputs(),
        )
    assert list(preexisting_empty.iterdir()) == []


def test_checksum_file_is_sorted_complete_and_has_no_self_hash(
    atomic_tmp_path: Path,
) -> None:
    bundle = _config_bundle()
    destination = atomic_tmp_path / "run"
    publish_run_artifact_bundle(
        destination,
        config_bundle=bundle,
        manifest_inputs=_manifest_inputs(present_extra=("event-journal.jsonl",)),
        artifact_writer=_journal_writer,
    )

    lines = (destination / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    names = [line.split("  ", maxsplit=1)[1] for line in lines]
    assert names == sorted({"event-journal.jsonl", "manifest.json", "resolved-config.json"})
    for line in lines:
        digest, name = line.split("  ", maxsplit=1)
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest


def test_concurrent_publishers_cannot_replace_the_winning_bundle(
    atomic_tmp_path: Path,
) -> None:
    destination = atomic_tmp_path / "race"
    bundle = _config_bundle()
    inputs = _manifest_inputs()
    ready = threading.Barrier(2)

    def wait_writer(_staging: Path) -> None:
        ready.wait(timeout=5)

    def publish() -> str:
        try:
            publish_run_artifact_bundle(
                destination,
                config_bundle=bundle,
                manifest_inputs=inputs,
                artifact_writer=wait_writer,
            )
        except FileExistsError:
            return "refused"
        return "published"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (executor.submit(publish), executor.submit(publish))
        outcomes = sorted(future.result() for future in futures)

    assert outcomes == ["published", "refused"]
    verify_run_artifact_bundle(destination, config_bundle=bundle)


def test_unsupported_atomic_no_replace_fails_closed_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run_bundle_module,
        "_renameat2_no_replace_errno",
        lambda _source, _destination: errno.EINVAL,
    )
    destination = tmp_path / "unsupported"

    with pytest.raises(RunArtifactBundleError, match="does not support atomic no-clobber"):
        publish_run_artifact_bundle(
            destination,
            config_bundle=_config_bundle(),
            manifest_inputs=_manifest_inputs(),
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(".unsupported.*.tmp"))


@pytest.mark.parametrize(
    ("replacement_inputs", "message"),
    [
        (
            lambda value: replace(
                value,
                code={"commit": "b" * 40, "dirty": False},
            ),
            "explicitly provide",
        ),
        (
            lambda value: replace(
                value,
                target_model={**value.target_model, "tokenizer_config_sha256": "c" * 64},
            ),
            "tokenizer_config_sha256",
        ),
        (
            lambda value: replace(value, seed=18),
            "seed does not match",
        ),
        (
            lambda value: replace(
                value,
                validation={**value.validation, "evidence_class": "E3"},
            ),
            "calibration_status=pass",
        ),
    ],
)
def test_explicit_provenance_drift_fails_before_publication(
    tmp_path: Path,
    replacement_inputs: Any,
    message: str,
) -> None:
    destination = tmp_path / "bad"
    with pytest.raises((RunArtifactBundleError, ValueError), match=message):
        publish_run_artifact_bundle(
            destination,
            config_bundle=_config_bundle(),
            manifest_inputs=replacement_inputs(_manifest_inputs()),
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(".bad.*.tmp"))


def test_writer_outputs_must_exactly_match_declared_present_artifacts(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "mismatch"
    with pytest.raises(RunArtifactBundleError, match=r"unexpected=.*event-journal"):
        publish_run_artifact_bundle(
            destination,
            config_bundle=_config_bundle(),
            manifest_inputs=_manifest_inputs(),
            artifact_writer=_journal_writer,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(".mismatch.*.tmp"))


def test_writer_failure_rolls_back_private_staging_directory(tmp_path: Path) -> None:
    destination = tmp_path / "failed-writer"

    def failing_writer(staging: Path) -> None:
        (staging / "partial.bin").write_bytes(b"partial")
        raise RuntimeError("writer failed")

    with pytest.raises(RuntimeError, match="writer failed"):
        publish_run_artifact_bundle(
            destination,
            config_bundle=_config_bundle(),
            manifest_inputs=_manifest_inputs(),
            artifact_writer=failing_writer,
        )

    assert not destination.exists()
    assert not list(tmp_path.glob(".failed-writer.*.tmp"))


def test_post_publish_corruption_is_detected(atomic_tmp_path: Path) -> None:
    destination = atomic_tmp_path / "corrupt"
    bundle = _config_bundle()
    publish_run_artifact_bundle(
        destination,
        config_bundle=bundle,
        manifest_inputs=_manifest_inputs(present_extra=("event-journal.jsonl",)),
        artifact_writer=_journal_writer,
    )
    with (destination / "event-journal.jsonl").open("ab") as stream:
        stream.write(b"corruption")

    with pytest.raises(RunArtifactBundleError, match="SHA256 mismatch"):
        verify_run_artifact_bundle(destination, config_bundle=bundle)


def test_symlink_artifact_is_rejected_before_publication(tmp_path: Path) -> None:
    destination = tmp_path / "symlink"

    def symlink_writer(staging: Path) -> None:
        (staging / "event-journal.jsonl").symlink_to("/etc/passwd")

    with pytest.raises(RunArtifactBundleError, match="non-regular artifact"):
        publish_run_artifact_bundle(
            destination,
            config_bundle=_config_bundle(),
            manifest_inputs=_manifest_inputs(present_extra=("event-journal.jsonl",)),
            artifact_writer=symlink_writer,
        )

    assert not destination.exists()


def test_symlink_swap_between_scan_and_hash_fails_closed(
    atomic_tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = atomic_tmp_path / "swap"
    bundle = _config_bundle()
    publish_run_artifact_bundle(
        destination,
        config_bundle=bundle,
        manifest_inputs=_manifest_inputs(present_extra=("event-journal.jsonl",)),
        artifact_writer=_journal_writer,
    )
    victim = destination / "event-journal.jsonl"
    original_sha256_file = run_bundle_module._sha256_file
    swapped = False

    def swap_then_hash(path: Path) -> str:
        nonlocal swapped
        if path == victim and not swapped:
            victim.unlink()
            victim.symlink_to("/etc/passwd")
            swapped = True
        return original_sha256_file(path)

    monkeypatch.setattr(run_bundle_module, "_sha256_file", swap_then_hash)

    with pytest.raises(RunArtifactBundleError, match="without following symlinks"):
        verify_run_artifact_bundle(destination, config_bundle=bundle)


def test_incomplete_bundle_is_publishable_only_when_missing_files_are_explicit(
    atomic_tmp_path: Path,
) -> None:
    destination = atomic_tmp_path / "incomplete"
    bundle = _config_bundle()
    inputs = _manifest_inputs(missing=("summary.json",), status="incomplete")

    publish_run_artifact_bundle(
        destination,
        config_bundle=bundle,
        manifest_inputs=inputs,
    )

    verify_run_artifact_bundle(destination, config_bundle=bundle)
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result_completeness"]["status"] == "incomplete"
    assert set(manifest["result_completeness"]["missing_artifacts"]) == _SECTION_16
