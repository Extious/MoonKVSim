#!/usr/bin/env python3
"""Run a bounded CPU metadata differential against pinned Mooncake.

The external oracle is compiled against the already-built, hash-bound
``f161118`` Store/TransferEngine libraries.  Its source deliberately exercises
only in-memory allocator, directory, eviction, batch-handle, and slice-state
code.  It never initializes TransferEngine, discovers devices, opens an RPC
endpoint, moves payload bytes, or invokes CUDA.

This is a subset differential.  A PASS narrows GAP-009 but does not establish
full Mooncake parity, RPC/concurrency parity, timing calibration, or physical
evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from moonkvsim.common.types import KVIdentity
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.store.allocation_strategy import RandomAllocationStrategy
from moonkvsim.store.eviction import FIFOEvictionStrategy, LRUEvictionStrategy
from moonkvsim.store.master import MasterService
from moonkvsim.store.segment import Segment
from moonkvsim.store.transfer_engine import (
    DEFAULT_SLICE_SIZE_BYTES,
    MemoryKind,
    MemoryLocation,
    SliceStatus,
    TopologyPath,
    TransferMetadata,
    TransferOpcode,
    TransferTask,
    TransportKind,
)

SCHEMA: Final = "moonkvsim.mooncake-metadata-differential.v1"
EVIDENCE_CLASS: Final = "E2_external_metadata_semantic_differential_subset"
PINNED_COMMIT: Final = "f161118c18dbea1b56dd5c7908b9eaa440353e2e"
PINNED_TREE: Final = "a5de4c0a0ec90a526edcb72609f6b90e2dc2332a"
DEFAULT_SOURCE_ROOT: Final = Path("/tmp/moonkvsim-mooncake-f161118.45Cs3n")
DEFAULT_BUILD_ROOT: Final = DEFAULT_SOURCE_ROOT / "build-golden-prefix"
SOURCE_GOLDEN_RELATIVE: Final = Path("reference/goldens/mooncake-f161118-store-te-source-api.json")
OFFICIAL_VALIDATION_RELATIVE: Final = Path(
    "reference/goldens/mooncake-f161118-official-test-validation.json"
)
ORACLE_SOURCE_RELATIVE: Final = Path(
    "tests/integration/fixtures/mooncake_f161118_metadata_oracle.cpp"
)
RUNNER_RELATIVE: Final = Path("scripts/run_mooncake_metadata_differential.py")
DEFAULT_OUTPUT_RELATIVE: Final = Path(
    "reference/goldens/mooncake-f161118-metadata-differential.json"
)
EXPECTED_COMPILER: Final = Path("/usr/local/gcc/gcc-11.2.0/bin/c++")

_ARTIFACT_PATHS: Final[dict[str, Path]] = {
    "CMakeCache.txt": Path("CMakeCache.txt"),
    "LastTest.log": Path("Testing/Temporary/LastTest.log"),
    "allocation_strategy_test": Path("mooncake-store/tests/allocation_strategy_test"),
    "eviction_strategy_test": Path("mooncake-store/tests/eviction_strategy_test"),
    "master_service_test": Path("mooncake-store/tests/master_service_test"),
    "memory_location_test": Path("mooncake-transfer-engine/tests/memory_location_test"),
    "segment_test": Path("mooncake-store/tests/segment_test"),
    "topology_test": Path("mooncake-transfer-engine/tests/topology_test"),
    "transfer_task_test": Path("mooncake-store/tests/transfer_task_test"),
    "libmooncake_store.a": Path("mooncake-store/src/libmooncake_store.a"),
    "libtransfer_engine.a": Path("mooncake-transfer-engine/src/libtransfer_engine.a"),
}


class DifferentialError(RuntimeError):
    """Raised when an input, external oracle, or comparison fails closed."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=repository_root())
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--build-root", type=Path, default=DEFAULT_BUILD_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_RELATIVE)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless the checked-in report is byte-identical to a fresh live run",
    )
    parser.add_argument(
        "--print-report",
        action="store_true",
        help="emit the full report instead of the compact completion record",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.repository_root.resolve()
    source_root = args.source_root.resolve()
    build_root = args.build_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        document = build_report(root=root, source_root=source_root, build_root=build_root)
        encoded = canonical_json_bytes(document)
        if document["status"] != "PARTIAL_PASS":
            raise DifferentialError("comparable external semantic cases did not all pass")
        if args.check:
            actual = _read_regular_file(output)
            if actual != encoded:
                raise DifferentialError(
                    f"{output} is not byte-identical to a fresh live differential"
                )
            action = "checked"
        else:
            _write_no_clobber(output, encoded)
            action = "generated"
    except (DifferentialError, OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2

    if args.print_report:
        sys.stdout.buffer.write(encoded)
    else:
        print(
            json.dumps(
                {
                    "action": action,
                    "comparable_case_count": document["summary"]["comparable_case_count"],
                    "known_gap_count": document["summary"]["known_gap_count"],
                    "output": str(output),
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                    "status": document["status"],
                },
                sort_keys=True,
            )
        )
    return 0


def build_report(*, root: Path, source_root: Path, build_root: Path) -> dict[str, Any]:
    source_golden_path = root / SOURCE_GOLDEN_RELATIVE
    validation_path = root / OFFICIAL_VALIDATION_RELATIVE
    oracle_source = root / ORACLE_SOURCE_RELATIVE
    source_golden = _load_object(source_golden_path)
    validation = _load_object(validation_path)
    _verify_inputs(
        source_root=source_root,
        build_root=build_root,
        source_golden=source_golden,
        validation=validation,
        source_golden_path=source_golden_path,
    )
    external, build_provenance = _compile_and_run_oracle(
        oracle_source=oracle_source,
        source_root=source_root,
        build_root=build_root,
    )
    simulated = moonkvsim_observation()
    comparisons = compare_observations(external=external, simulated=simulated)
    comparable = [row for row in comparisons if row["status"] in {"PASS", "FAIL"}]
    gaps = [row for row in comparisons if row["status"] == "KNOWN_GAP"]
    failed = [row for row in comparable if row["status"] == "FAIL"]
    return {
        "schema": SCHEMA,
        "status": "FAIL" if failed else "PARTIAL_PASS",
        "evidence_class": EVIDENCE_CLASS,
        "full_parity_claim_allowed": False,
        "formal_use_allowed": False,
        "claim_exclusions": [
            "full_MoonKVSim-versus-Mooncake_parity",
            "RPC_or_concurrency_parity",
            "real_network_or_TransferEngine_initialization",
            "GPU_or_CUDA_execution",
            "communication_timing_or_calibration",
            "physical_validation",
            "E3_E4_or_E5_evidence",
        ],
        "provenance": {
            "pinned_commit": PINNED_COMMIT,
            "pinned_tree": PINNED_TREE,
            "source_archive_policy": "verified_files_from_git_commit_object_archive",
            "source_golden": {
                "path": SOURCE_GOLDEN_RELATIVE.as_posix(),
                "sha256": _sha256(source_golden_path),
            },
            "official_test_validation": {
                "path": OFFICIAL_VALIDATION_RELATIVE.as_posix(),
                "sha256": _sha256(validation_path),
                "gtest_cases_passed": validation["validation"]["selected_ctest"][
                    "gtest_cases_passed"
                ],
                "gtest_cases_skipped": validation["validation"]["selected_ctest"][
                    "gtest_cases_skipped"
                ],
                "dependency_prefix_hash_locked": validation["validation"]["build"][
                    "dependency_prefix_hash_locked"
                ],
            },
            "oracle_source": {
                "path": ORACLE_SOURCE_RELATIVE.as_posix(),
                "sha256": _sha256(oracle_source),
            },
            "runner": {
                "path": RUNNER_RELATIVE.as_posix(),
                "sha256": _sha256(root / RUNNER_RELATIVE),
            },
            "build": build_provenance,
        },
        "execution_boundary": {
            "verification_method": "fixture_source_audit_not_kernel_sandbox",
            "network_namespace_enforced": False,
            "reason_network_namespace_not_enforced": (
                "unshare(CLONE_NEWNET) is not permitted on this host; the audited oracle "
                "does not initialize TransferEngine, topology discovery, transport, or RPC"
            ),
            "cuda_visible_devices": "",
            "gpu_or_cuda_api_called_by_oracle": False,
            "network_or_rpc_api_called_by_oracle": False,
            "payload_bytes_copied": False,
            "timing_collected": False,
            "linked_dependencies_may_include_transport_and_cuda_runtime": True,
            "linked_dependencies_are_not_proof_of_api_execution": True,
        },
        "external_observation": external,
        "moonkvsim_observation": simulated,
        "comparisons": comparisons,
        "summary": {
            "comparable_case_count": len(comparable),
            "comparable_pass_count": len(comparable) - len(failed),
            "comparable_fail_count": len(failed),
            "known_gap_count": len(gaps),
            "gap009_closed": False,
            "effect": (
                "Adds a direct external metadata-state differential for a bounded subset; "
                "the official 248-pass suite remains supporting upstream-unit evidence only."
            ),
        },
    }


def _verify_inputs(
    *,
    source_root: Path,
    build_root: Path,
    source_golden: Mapping[str, Any],
    validation: Mapping[str, Any],
    source_golden_path: Path,
) -> None:
    if source_golden.get("schema") != "moonkvsim.mooncake-source-api-golden.v1":
        raise DifferentialError("Mooncake source/API golden schema drift")
    provenance = _mapping(source_golden.get("provenance"), "source golden provenance")
    if provenance.get("commit") != PINNED_COMMIT or provenance.get("tree") != PINNED_TREE:
        raise DifferentialError("Mooncake source/API golden pin drift")
    files = _list(provenance.get("files"), "source golden files")
    if len(files) != 27:
        raise DifferentialError("Mooncake source/API golden must bind exactly 27 files")
    for raw in files:
        record = _mapping(raw, "source file record")
        relative = _safe_relative(record.get("path"), "source file path")
        target = source_root / relative
        if _sha256(target) != record.get("sha256"):
            raise DifferentialError(f"pinned source archive hash drift: {relative}")

    if validation.get("schema") != "moonkvsim.mooncake-official-test-validation.v1":
        raise DifferentialError("Mooncake official validation schema drift")
    validation_provenance = _mapping(validation.get("provenance"), "validation provenance")
    if (
        validation_provenance.get("commit") != PINNED_COMMIT
        or validation_provenance.get("tree") != PINNED_TREE
    ):
        raise DifferentialError("Mooncake official validation pin drift")
    if validation_provenance["source_golden"]["sha256"] != _sha256(source_golden_path):
        raise DifferentialError("official validation no longer binds the source golden")
    selected = validation["validation"]["selected_ctest"]
    if selected != {
        "ctest_targets": [
            "topology_test",
            "memory_location_test",
            "allocation_strategy_test",
            "eviction_strategy_test",
            "master_service_test",
            "transfer_task_test",
            "segment_test",
        ],
        "failed": 0,
        "gtest_cases_passed": 248,
        "gtest_cases_skipped": 2,
        "gtest_cases_total": 250,
        "status": "PASS",
    }:
        raise DifferentialError("official selected-test result drift")
    expected_artifacts = validation["validation"]["artifacts"]
    if set(expected_artifacts) != set(_ARTIFACT_PATHS):
        raise DifferentialError("official validation artifact set drift")
    for name, relative in _ARTIFACT_PATHS.items():
        if _sha256(build_root / relative) != expected_artifacts[name]:
            raise DifferentialError(f"pinned build artifact hash drift: {name}")


def _compile_and_run_oracle(
    *, oracle_source: Path, source_root: Path, build_root: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    compile_commands_path = build_root / "compile_commands.json"
    commands = json.loads(_read_regular_file(compile_commands_path))
    if not isinstance(commands, list):
        raise DifferentialError("compile_commands.json must contain an array")
    selected = [
        row
        for row in commands
        if isinstance(row, dict)
        and str(row.get("file", "")).endswith("allocation_strategy_test.cpp")
    ]
    if len(selected) != 1:
        raise DifferentialError("cannot resolve the pinned allocator compile command")
    compile_row = selected[0]
    compile_tokens = shlex.split(_string(compile_row.get("command"), "compile command"))
    if Path(compile_tokens[0]) != EXPECTED_COMPILER:
        raise DifferentialError("pinned build compiler path drift")

    link_path = build_root / "mooncake-store/tests/CMakeFiles/allocation_strategy_test.dir/link.txt"
    link_tokens = shlex.split(_read_regular_file(link_path).decode().strip())
    if not link_tokens or Path(link_tokens[0]) != EXPECTED_COMPILER:
        raise DifferentialError("pinned build linker path drift")

    compiler_version = subprocess.run(
        [str(EXPECTED_COMPILER), "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()[0]
    if compiler_version != "c++ (GCC) 11.2.0":
        raise DifferentialError("pinned compiler version drift")

    with tempfile.TemporaryDirectory(prefix="moonkvsim-mooncake-metadata-") as temp:
        temp_root = Path(temp)
        object_path = temp_root / "oracle.o"
        executable_path = temp_root / "oracle"
        compile_tokens = _replace_compile_outputs(
            compile_tokens,
            source=oracle_source,
            output=object_path,
        )
        compile_result = subprocess.run(
            compile_tokens,
            cwd=Path(_string(compile_row.get("directory"), "compile directory")),
            check=False,
            capture_output=True,
            text=True,
        )
        if compile_result.returncode != 0:
            raise DifferentialError(
                "external metadata oracle compilation failed: " + compile_result.stderr.strip()
            )
        link_tokens = _replace_link_outputs(
            link_tokens,
            object_path=object_path,
            executable_path=executable_path,
        )
        link_result = subprocess.run(
            link_tokens,
            cwd=build_root / "mooncake-store/tests",
            check=False,
            capture_output=True,
            text=True,
        )
        if link_result.returncode != 0:
            raise DifferentialError(
                "external metadata oracle link failed: " + link_result.stderr.strip()
            )
        executable_sha256 = _sha256(executable_path)
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("MC_") and not key.startswith("NCCL_")
        }
        environment["CUDA_VISIBLE_DEVICES"] = ""
        run = subprocess.run(
            [str(executable_path)],
            cwd=temp_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if run.returncode != 0:
            raise DifferentialError(
                "external metadata oracle failed: "
                + (run.stderr.strip() or f"exit {run.returncode}")
            )
        try:
            observation = json.loads(run.stdout)
        except json.JSONDecodeError as error:
            raise DifferentialError("external metadata oracle emitted invalid JSON") from error
        if not isinstance(observation, dict):
            raise DifferentialError("external metadata oracle output must be an object")
        if observation.get("schema") != "moonkvsim.external-mooncake-metadata-oracle.v1":
            raise DifferentialError("external metadata oracle schema drift")
        if observation.get("execution_boundary") != {
            "cuda": False,
            "gpu": False,
            "network": False,
            "payload_copy": False,
        }:
            raise DifferentialError("external metadata oracle boundary drift")

    normalizers = {
        str(oracle_source.resolve()): "$ORACLE_SOURCE",
        str(source_root.resolve()): "$PINNED_SOURCE_ROOT",
        str(build_root.resolve()): "$PINNED_BUILD_ROOT",
        str(object_path): "$ORACLE_OBJECT",
        str(executable_path): "$ORACLE_EXECUTABLE",
    }
    return observation, {
        "compiler": str(EXPECTED_COMPILER),
        "compiler_version": compiler_version,
        "compile_commands_sha256": _sha256(compile_commands_path),
        "link_txt_sha256": _sha256(link_path),
        "compile_command": _normalize_command(compile_tokens, normalizers),
        "link_command": _normalize_command(link_tokens, normalizers),
        "oracle_executable_sha256": executable_sha256,
        "linked_store_archive_sha256": _sha256(build_root / _ARTIFACT_PATHS["libmooncake_store.a"]),
        "linked_transfer_engine_archive_sha256": _sha256(
            build_root / _ARTIFACT_PATHS["libtransfer_engine.a"]
        ),
        "dependency_prefix_hash_locked": False,
    }


def moonkvsim_observation() -> dict[str, Any]:
    empty_strategy = RandomAllocationStrategy(seed=7)
    empty = empty_strategy.allocate((), slice_id="empty", slice_length_bytes=1024, replica_count=1)

    ordinary = _segment("ordinary", 16 * 1024 * 1024, alignment=1)
    preferred = _segment("preferred", 16 * 1024 * 1024, alignment=1)
    preferred_result = RandomAllocationStrategy(seed=7).allocate(
        (ordinary, preferred),
        slice_id="preferred",
        slice_length_bytes=1024,
        replica_count=1,
        preferred_segment_ids=("preferred",),
    )

    segment_a = _segment("segment-a", 16 * 1024 * 1024, alignment=1)
    segment_b = _segment("segment-b", 16 * 1024 * 1024, alignment=1)
    best_effort = RandomAllocationStrategy(seed=7).allocate(
        (segment_a, segment_b),
        slice_id="best-effort",
        slice_length_bytes=1024,
        replica_count=3,
    )

    # Pinned OffsetBufferAllocator exposes 8-byte extent alignment.  Match the
    # same allocator configuration rather than the deployment-level Store
    # alignment used by other MoonKVSim fixtures.
    extent = _segment("extent", 4096, alignment=8)
    extent_a = extent.allocate(buffer_id="a", requested_bytes=100)
    extent_b = extent.allocate(buffer_id="b", requested_bytes=200)
    if extent_a is None or extent_b is None:
        raise DifferentialError("MoonKVSim extent setup unexpectedly failed")
    extent.deallocate("a")
    extent_c = extent.allocate(buffer_id="c", requested_bytes=50)
    if extent_c is None:
        raise DifferentialError("MoonKVSim extent reuse unexpectedly failed")

    lru = LRUEvictionStrategy()
    lru.add_key("key1")
    lru.add_key("key2")
    lru_evicted = [lru.evict_key()]
    lru.add_key("key3")
    lru.add_key("key4")
    lru.update_key("key2")
    lru.update_key("key3")
    lru_evicted.append(lru.evict_key())

    fifo = FIFOEvictionStrategy()
    fifo.add_key("key1")
    fifo.add_key("key2")
    fifo.remove_key("key2")
    fifo_size_after_remove = len(fifo)
    fifo_evicted = [fifo.evict_key()]
    fifo.add_key("key3")
    fifo.add_key("key4")
    fifo.update_key("key2")
    fifo.update_key("key3")
    fifo_evicted.append(fifo.evict_key())

    service = _master()
    identity = _identity()
    missing_count = len(service.get_replica_list(identity))
    ticket = service.put_start(
        identity,
        put_id="metadata-put",
        payload_bytes=1024,
        replica_count=1,
        timestamp_ns=1,
    )
    put_start_status = ticket.state.value
    pending_count = len(service.get_replica_list(identity))
    committed = service.put_end(
        ticket.put_id,
        successful_replica_ids=ticket.replica_ids,
        timestamp_ns=2,
    )
    committed_count = len(service.get_replica_list(identity))
    removed_count = service.remove(identity, timestamp_ns=3)
    after_remove_count = len(service.get_replica_list(identity))

    transfer = TransferTask.create(_transfer_metadata(total_bytes=131_073))
    transfer.start(timestamp_ns=10)
    for index, item in enumerate(tuple(transfer.slices)):
        transfer.update_slice(item.post(timestamp_ns=11 + index))
        transfer.update_slice(
            transfer.slices[index].finish(SliceStatus.SUCCESS, timestamp_ns=20 + index)
        )
    transfer.audit()

    return {
        "allocator": {
            "empty_outcome": "EMPTY_PLACEMENTS" if not empty else "ALLOCATED",
            "preferred_endpoint": preferred_result[0].segment_id,
            "preferred_size_bytes": preferred_result[0].buffer.requested_bytes,
            "best_effort_replica_count": len(best_effort),
            "best_effort_distinct_segments": len(
                {placement.segment_id for placement in best_effort}
            ),
            "offset_extent_trace": [
                extent_a.offset_bytes,
                extent_b.offset_bytes,
                extent_c.offset_bytes,
            ],
        },
        "eviction": {
            "lru_evicted": lru_evicted,
            "fifo_evicted": fifo_evicted,
            "fifo_size_after_remove": fifo_size_after_remove,
        },
        "master": {
            "missing_get": "EMPTY_VISIBLE_SET",
            "missing_visible_replica_count": missing_count,
            "put_start_status": put_start_status,
            "pending_get": "EMPTY_VISIBLE_SET",
            "pending_visible_replica_count": pending_count,
            "put_end": "OK",
            "committed_get": "OK",
            "committed_replica_count": committed_count,
            "committed_status": committed[0].state.value,
            "remove": "OK",
            "removed_replica_count": removed_count,
            "removed_get": "EMPTY_VISIBLE_SET",
            "removed_visible_replica_count": after_remove_count,
        },
        "transfer_engine": {
            "default_slice_size_bytes": DEFAULT_SLICE_SIZE_BYTES,
            "slice_lengths": [item.length_bytes for item in transfer.slices],
            "successful_slice_count": sum(
                item.status is SliceStatus.SUCCESS for item in transfer.slices
            ),
            "transferred_bytes": transfer.transferred_bytes,
            "terminal_status": transfer.status.value,
            "batch_capacity_outcome": "NOT_IMPLEMENTED",
            "batch_free_outcome": "NOT_IMPLEMENTED",
        },
    }


def compare_observations(
    *, external: Mapping[str, Any], simulated: Mapping[str, Any]
) -> list[dict[str, Any]]:
    external_allocator = _mapping(external.get("allocator"), "external allocator")
    simulated_allocator = _mapping(simulated.get("allocator"), "simulated allocator")
    external_eviction = _mapping(external.get("eviction"), "external eviction")
    simulated_eviction = _mapping(simulated.get("eviction"), "simulated eviction")
    external_master = _mapping(external.get("master"), "external master")
    simulated_master = _mapping(simulated.get("master"), "simulated master")
    external_te = _mapping(external.get("transfer_engine"), "external transfer engine")
    simulated_te = _mapping(simulated.get("transfer_engine"), "simulated transfer engine")

    rows = [
        _comparison(
            "allocator.empty_capacity",
            "semantic_projection",
            external_allocator["empty_error"],
            simulated_allocator["empty_outcome"],
            external_allocator["empty_error"] == "NO_AVAILABLE_HANDLE"
            and simulated_allocator["empty_outcome"] == "EMPTY_PLACEMENTS",
        ),
        _comparison(
            "allocator.preferred_segment",
            "exact_common_fields",
            [
                external_allocator["preferred_endpoint"],
                external_allocator["preferred_size_bytes"],
            ],
            [
                simulated_allocator["preferred_endpoint"],
                simulated_allocator["preferred_size_bytes"],
            ],
        ),
        _comparison(
            "allocator.best_effort_distinct_segments",
            "exact_common_fields",
            [
                external_allocator["best_effort_replica_count"],
                external_allocator["best_effort_distinct_segments"],
            ],
            [
                simulated_allocator["best_effort_replica_count"],
                simulated_allocator["best_effort_distinct_segments"],
            ],
        ),
        _comparison(
            "allocator.offset_extent_reuse",
            "exact_offsets",
            external_allocator["offset_extent_trace"],
            simulated_allocator["offset_extent_trace"],
        ),
        _comparison(
            "eviction.lru_sequence",
            "exact",
            external_eviction["lru_evicted"],
            simulated_eviction["lru_evicted"],
        ),
        _comparison(
            "eviction.fifo_remove_noop_sequence",
            "exact",
            [
                external_eviction["fifo_size_after_remove"],
                external_eviction["fifo_evicted"],
            ],
            [
                simulated_eviction["fifo_size_after_remove"],
                simulated_eviction["fifo_evicted"],
            ],
        ),
        _comparison(
            "master.publication_lifecycle",
            "normalized_state_projection",
            _external_master_projection(external_master),
            _simulated_master_projection(simulated_master),
        ),
        _comparison(
            "transfer_engine.slice_status_and_bytes",
            "exact_common_fields",
            [
                external_te["default_slice_size_bytes"],
                external_te["successful_slice_count"],
                external_te["transferred_bytes"],
            ],
            [
                simulated_te["default_slice_size_bytes"],
                simulated_te["successful_slice_count"],
                simulated_te["transferred_bytes"],
            ],
        ),
        _gap(
            "master.GetReplicaList_error_codes",
            external={
                "missing": external_master["missing_get"],
                "pending": external_master["pending_get"],
                "removed": external_master["removed_get"],
            },
            simulated={
                "missing": simulated_master["missing_get"],
                "pending": simulated_master["pending_get"],
                "removed": simulated_master["removed_get"],
            },
            reason=("MoonKVSim exposes a visibility query, not pinned Master RPC error codes"),
        ),
        _gap(
            "master.PutEnd_all_matching_scope",
            external="PutEnd marks every matching PROCESSING memory replica COMPLETE",
            simulated="put_end accepts an explicit successful-replica subset",
            reason="intentional failure-accounting replacement; exact API parity is absent",
        ),
        _gap(
            "transfer_engine.BatchID_capacity_and_free",
            external={
                "overflow_submit": external_te["overflow_submit"],
                "unfinished_batch_free": external_te["unfinished_batch_free"],
                "finished_batch_free": external_te["finished_batch_free"],
            },
            simulated={
                "capacity": simulated_te["batch_capacity_outcome"],
                "free": simulated_te["batch_free_outcome"],
            },
            reason="MoonKVSim BatchTransfer has neither fixed capacity nor freeBatchID lifecycle",
        ),
    ]
    return rows


def _external_master_projection(master: Mapping[str, Any]) -> list[str]:
    return [
        "ABSENT" if master["missing_get"] == "OBJECT_NOT_FOUND" else "DRIFT",
        "PENDING" if master["put_start_status"] == "PROCESSING" else "DRIFT",
        "PENDING_NOT_VISIBLE" if master["pending_get"] == "REPLICA_IS_NOT_READY" else "DRIFT",
        "COMMITTED_VISIBLE"
        if master["committed_get"] == "OK"
        and master["committed_status"] == "COMPLETE"
        and master["committed_replica_count"] == 1
        else "DRIFT",
        "ABSENT" if master["removed_get"] == "OBJECT_NOT_FOUND" else "DRIFT",
    ]


def _simulated_master_projection(master: Mapping[str, Any]) -> list[str]:
    return [
        "ABSENT"
        if master["missing_get"] == "EMPTY_VISIBLE_SET"
        and master["missing_visible_replica_count"] == 0
        else "DRIFT",
        "PENDING" if master["put_start_status"] == "PENDING" else "DRIFT",
        "PENDING_NOT_VISIBLE"
        if master["pending_get"] == "EMPTY_VISIBLE_SET"
        and master["pending_visible_replica_count"] == 0
        else "DRIFT",
        "COMMITTED_VISIBLE"
        if master["committed_get"] == "OK"
        and master["committed_status"] == "COMMITTED"
        and master["committed_replica_count"] == 1
        else "DRIFT",
        "ABSENT"
        if master["removed_get"] == "EMPTY_VISIBLE_SET"
        and master["removed_visible_replica_count"] == 0
        and master["removed_replica_count"] == 1
        else "DRIFT",
    ]


def _comparison(
    case: str,
    scope: str,
    external: object,
    simulated: object,
    passed: bool | None = None,
) -> dict[str, Any]:
    if passed is None:
        passed = external == simulated
    return {
        "case": case,
        "scope": scope,
        "status": "PASS" if passed else "FAIL",
        "external": external,
        "moonkvsim": simulated,
    }


def _gap(case: str, *, external: object, simulated: object, reason: str) -> dict[str, Any]:
    return {
        "case": case,
        "scope": "not_comparable",
        "status": "KNOWN_GAP",
        "external": external,
        "moonkvsim": simulated,
        "reason": reason,
    }


def _segment(segment_id: str, capacity: int, *, alignment: int) -> Segment:
    segment = Segment(
        segment_id=segment_id,
        name=segment_id,
        node_id=f"node-{segment_id}",
        numa_node_id=f"numa:{segment_id}:0",
        transport_endpoint=segment_id,
        capacity_bytes=capacity,
        allocation_alignment_bytes=alignment,
    )
    segment.mount()
    return segment


def _master() -> MasterService:
    service = MasterService(allocation_strategy=RandomAllocationStrategy(seed=7))
    segment = Segment(
        segment_id="metadata-segment",
        name="metadata-segment",
        node_id="node-metadata",
        numa_node_id="numa:metadata:0",
        transport_endpoint="metadata-segment",
        capacity_bytes=16 * 1024 * 1024,
        allocation_alignment_bytes=1,
    )
    service.mount_segment(
        segment,
        CapacityLedger(
            resource_id="metadata-segment",
            resource_kind=CapacityResourceKind.STORE_DRAM,
            capacity_bytes=16 * 1024 * 1024,
        ),
        timestamp_ns=0,
    )
    return service


def _identity() -> KVIdentity:
    return KVIdentity(
        tenant_id="tenant-0",
        model_id="model",
        model_revision="revision",
        kv_dtype="bf16",
        kv_abi="vllm-v1",
        kv_layout="tp1-pp1",
        tp_size=1,
        pp_size=1,
        block_size_tokens=16,
        stable_block_hash="metadata-key",
        token_start=0,
        token_end=16,
        shard_id="tp0",
        request_id="request-0",
        session_id="session-0",
        workflow_id="workflow-0",
        route_version=0,
        source_gpu_id="node-0.gpu-0",
    )


def _transfer_metadata(*, total_bytes: int) -> TransferMetadata:
    source = MemoryLocation(
        resource_id="gpu.hbm",
        node_id="node-0",
        numa_node_id="numa:node-0:0",
        kind=MemoryKind.GPU_HBM,
        endpoint="metadata-source",
        gpu_id="gpu-0",
    )
    destination = MemoryLocation(
        resource_id="store.dram",
        node_id="node-1",
        numa_node_id="numa:node-1:0",
        kind=MemoryKind.STORE_DRAM,
        endpoint="metadata-destination",
    )
    path = TopologyPath(
        path_id="metadata-path",
        source_kind=source.kind,
        destination_kind=destination.kind,
        transport=TransportKind.RDMA_GDR,
        rate_resource_ids=("gpu.read", "store.write"),
        concurrency_resource_ids=(),
        source_endpoint=source.endpoint,
        destination_endpoint=destination.endpoint,
        source_node_id=source.node_id,
        destination_node_id=destination.node_id,
        source_numa_node_id=source.numa_node_id,
        destination_numa_node_id=destination.numa_node_id,
        source_hca_id="hca-0",
        destination_hca_id="hca-1",
    )
    return TransferMetadata(
        transfer_id="metadata-transfer",
        object_id="object-0",
        replica_id="replica-0",
        source=source,
        destination=destination,
        opcode=TransferOpcode.WRITE,
        total_bytes=total_bytes,
        cause="GAP_009_METADATA_DIFFERENTIAL",
        route_version=0,
        ready_ns=10,
        path=path,
    )


def _replace_compile_outputs(tokens: list[str], *, source: Path, output: Path) -> list[str]:
    result = list(tokens)
    try:
        output_index = result.index("-o") + 1
        source_index = result.index("-c") + 1
    except (ValueError, IndexError) as error:
        raise DifferentialError("unexpected pinned compile command shape") from error
    result[output_index] = str(output)
    result[source_index] = str(source)
    return result


def _replace_link_outputs(
    tokens: list[str], *, object_path: Path, executable_path: Path
) -> list[str]:
    result = list(tokens)
    objects = [
        index
        for index, token in enumerate(result)
        if token.endswith("allocation_strategy_test.cpp.o")
    ]
    if len(objects) != 1:
        raise DifferentialError("unexpected pinned allocator link object set")
    result[objects[0]] = str(object_path)
    try:
        output_index = result.index("-o") + 1
    except (ValueError, IndexError) as error:
        raise DifferentialError("unexpected pinned link command shape") from error
    result[output_index] = str(executable_path)
    return result


def _normalize_command(tokens: Sequence[str], replacements: Mapping[str, str]) -> list[str]:
    normalized: list[str] = []
    ordered = sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
    for token in tokens:
        value = token
        for original, replacement in ordered:
            value = value.replace(original, replacement)
        normalized.append(value)
    return normalized


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(_read_regular_file(path))
    if not isinstance(value, dict):
        raise DifferentialError(f"{path} must contain a JSON object")
    return value


def _read_regular_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise DifferentialError(f"required regular file is missing: {path}")
    return path.read_bytes()


def _write_no_clobber(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as error:
        raise DifferentialError(f"refusing to overwrite existing report: {path}") from error
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DifferentialError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise DifferentialError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DifferentialError(f"{label} must be a non-empty string")
    return value


def _safe_relative(value: object, label: str) -> Path:
    text = _string(value, label)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        raise DifferentialError(f"{label} must be a safe relative path")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
