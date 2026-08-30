from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = PROJECT_ROOT / "reference/goldens/mooncake-f161118-metadata-differential.json"
SOURCE_GOLDEN = PROJECT_ROOT / "reference/goldens/mooncake-f161118-store-te-source-api.json"
OFFICIAL_VALIDATION = (
    PROJECT_ROOT / "reference/goldens/mooncake-f161118-official-test-validation.json"
)
RUNNER = PROJECT_ROOT / "scripts/run_mooncake_metadata_differential.py"
ORACLE_SOURCE = PROJECT_ROOT / "tests/integration/fixtures/mooncake_f161118_metadata_oracle.cpp"
LIVE_SOURCE_ROOT = Path("/tmp/moonkvsim-mooncake-f161118.45Cs3n")
LIVE_BUILD_ROOT = LIVE_SOURCE_ROOT / "build-golden-prefix"
LIVE_COMPILER = Path("/usr/local/gcc/gcc-11.2.0/bin/c++")

PASS_CASES = {
    "allocator.empty_capacity",
    "allocator.preferred_segment",
    "allocator.best_effort_distinct_segments",
    "allocator.offset_extent_reuse",
    "eviction.lru_sequence",
    "eviction.fifo_remove_noop_sequence",
    "master.publication_lifecycle",
    "transfer_engine.slice_status_and_bytes",
}
KNOWN_GAP_CASES = {
    "master.GetReplicaList_error_codes",
    "master.PutEnd_all_matching_scope",
    "transfer_engine.BatchID_capacity_and_free",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_document(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    value = json.loads(payload)
    assert isinstance(value, dict)
    assert (
        payload
        == (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
    )
    return value


def _document(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    assert isinstance(value, dict)
    return value


def test_checked_in_capture_is_fail_closed_bounded_external_evidence() -> None:
    document = _canonical_document(GOLDEN)

    assert document["schema"] == "moonkvsim.mooncake-metadata-differential.v1"
    assert document["status"] == "PARTIAL_PASS"
    assert document["evidence_class"] == "E2_external_metadata_semantic_differential_subset"
    assert document["full_parity_claim_allowed"] is False
    assert document["formal_use_allowed"] is False
    assert document["summary"] == {
        "comparable_case_count": 8,
        "comparable_fail_count": 0,
        "comparable_pass_count": 8,
        "effect": (
            "Adds a direct external metadata-state differential for a bounded subset; "
            "the official 248-pass suite remains supporting upstream-unit evidence only."
        ),
        "gap009_closed": False,
        "known_gap_count": 3,
    }
    assert document["claim_exclusions"] == [
        "full_MoonKVSim-versus-Mooncake_parity",
        "RPC_or_concurrency_parity",
        "real_network_or_TransferEngine_initialization",
        "GPU_or_CUDA_execution",
        "communication_timing_or_calibration",
        "physical_validation",
        "E3_E4_or_E5_evidence",
    ]
    assert document["execution_boundary"] == {
        "cuda_visible_devices": "",
        "gpu_or_cuda_api_called_by_oracle": False,
        "linked_dependencies_are_not_proof_of_api_execution": True,
        "linked_dependencies_may_include_transport_and_cuda_runtime": True,
        "network_namespace_enforced": False,
        "network_or_rpc_api_called_by_oracle": False,
        "payload_bytes_copied": False,
        "reason_network_namespace_not_enforced": (
            "unshare(CLONE_NEWNET) is not permitted on this host; the audited oracle "
            "does not initialize TransferEngine, topology discovery, transport, or RPC"
        ),
        "timing_collected": False,
        "verification_method": "fixture_source_audit_not_kernel_sandbox",
    }
    assert document["external_observation"]["execution_boundary"] == {
        "cuda": False,
        "gpu": False,
        "network": False,
        "payload_copy": False,
    }

    comparisons = document["comparisons"]
    assert len(comparisons) == 11
    assert {row["case"] for row in comparisons if row["status"] == "PASS"} == PASS_CASES
    assert {row["case"] for row in comparisons if row["status"] == "KNOWN_GAP"} == KNOWN_GAP_CASES
    assert not [row for row in comparisons if row["status"] == "FAIL"]


def test_capture_binds_current_runner_oracle_and_pinned_source_records() -> None:
    document = _canonical_document(GOLDEN)
    source_golden = _canonical_document(SOURCE_GOLDEN)
    official = _document(OFFICIAL_VALIDATION)
    provenance = document["provenance"]

    assert provenance["pinned_commit"] == "f161118c18dbea1b56dd5c7908b9eaa440353e2e"
    assert provenance["pinned_tree"] == "a5de4c0a0ec90a526edcb72609f6b90e2dc2332a"
    assert provenance["source_archive_policy"] == ("verified_files_from_git_commit_object_archive")
    assert provenance["source_golden"] == {
        "path": "reference/goldens/mooncake-f161118-store-te-source-api.json",
        "sha256": _sha256(SOURCE_GOLDEN),
    }
    assert provenance["official_test_validation"]["sha256"] == _sha256(OFFICIAL_VALIDATION)
    assert provenance["oracle_source"] == {
        "path": "tests/integration/fixtures/mooncake_f161118_metadata_oracle.cpp",
        "sha256": _sha256(ORACLE_SOURCE),
    }
    assert provenance["runner"] == {
        "path": "scripts/run_mooncake_metadata_differential.py",
        "sha256": _sha256(RUNNER),
    }

    source_provenance = source_golden["provenance"]
    assert source_provenance["commit"] == provenance["pinned_commit"]
    assert source_provenance["tree"] == provenance["pinned_tree"]
    assert len(source_provenance["files"]) == 27
    assert all(len(record["sha256"]) == 64 for record in source_provenance["files"])

    assert official["evidence_class"] == "E2_external_official_unit_execution_subset"
    selected = official["validation"]["selected_ctest"]
    assert (selected["gtest_cases_passed"], selected["gtest_cases_skipped"]) == (
        248,
        2,
    )
    assert official["validation"]["build"]["dependency_prefix_hash_locked"] is False
    assert official["validation"]["runtime_boundaries"] == {
        "gpu_or_cuda_kernel_executed": False,
        "rdma_device_available": False,
        "test_timing_is_performance_evidence": False,
    }


def test_current_moonkvsim_reprojects_against_captured_external_observation() -> None:
    document = _canonical_document(GOLDEN)
    namespace = runpy.run_path(str(RUNNER))
    observe = cast(Callable[[], dict[str, Any]], namespace["moonkvsim_observation"])
    compare = cast(Callable[..., list[dict[str, Any]]], namespace["compare_observations"])

    simulated = observe()
    comparisons = compare(
        external=cast(Mapping[str, Any], document["external_observation"]),
        simulated=simulated,
    )

    assert simulated == document["moonkvsim_observation"]
    assert comparisons == document["comparisons"]
    assert sum(row["status"] == "PASS" for row in comparisons) == 8
    assert sum(row["status"] == "KNOWN_GAP" for row in comparisons) == 3


def test_oracle_fixture_has_no_transport_rpc_or_cuda_entrypoint_calls() -> None:
    source = ORACLE_SOURCE.read_text(encoding="utf-8")

    for forbidden in (
        "TransferEngine(",
        "MasterClient(",
        "WrappedMasterService(",
        "RpcService(",
        "installTransport(",
        "discoverTopology(",
        "socket(",
        "connect(",
        "cudaSetDevice(",
        "cudaMalloc(",
        "cudaMemcpy(",
    ):
        assert forbidden not in source


@pytest.mark.skipif(
    not (LIVE_SOURCE_ROOT.is_dir() and LIVE_BUILD_ROOT.is_dir() and LIVE_COMPILER.is_file()),
    reason="pinned local Mooncake source/build/compiler are unavailable",
)
def test_live_pinned_metadata_oracle_is_byte_identical_to_capture() -> None:
    environment = os.environ.copy()
    python_path = str(PROJECT_ROOT / "python")
    if environment.get("PYTHONPATH"):
        python_path += os.pathsep + environment["PYTHONPATH"]
    environment["PYTHONPATH"] = python_path
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--source-root",
            str(LIVE_SOURCE_ROOT),
            "--build-root",
            str(LIVE_BUILD_ROOT),
            "--output",
            str(GOLDEN),
            "--check",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    result = json.loads(completed.stdout)

    assert result["action"] == "checked"
    assert result["status"] == "PARTIAL_PASS"
    assert result["comparable_case_count"] == 8
    assert result["known_gap_count"] == 3
