#!/usr/bin/env python3
"""Generate the pinned vanilla-Mooncake source/API reference golden.

The generator reads Git objects only.  It never reads Mooncake worktree files,
and it never imports or executes Mooncake.  Consequently the artifact is an E1
source/API reference, not an external-runtime differential or communication
calibration result.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_REPOSITORY = Path("/home/comp/zhanzhao/Mooncake")
EXPECTED_COMMIT = "f161118c18dbea1b56dd5c7908b9eaa440353e2e"
EXPECTED_TREE = "a5de4c0a0ec90a526edcb72609f6b90e2dc2332a"
EXPECTED_GITLINKS = {
    "extern/pybind11": "58c382a8e3d7081364d2f5c62e7f429f0412743b",
    "extern/yalantinglibs": "7801bc9ad9021781f15217552214e325a1cf7373",
}
SCHEMA = "moonkvsim.mooncake-source-api-golden.v1"
EVIDENCE_CLASS = "E1_pinned_source_api_reference_only"
SOURCE_LOCK_RELATIVE_PATH = Path("reference/source-lock.json")
DEFAULT_OUTPUT = Path("reference/goldens/mooncake-f161118-store-te-source-api.json")


class CaptureError(RuntimeError):
    """Raised when the source lock, Git object, or golden drifts."""


@dataclass(frozen=True, slots=True)
class SourceSpec:
    path: str
    role: str
    required_in_source_lock: bool = False


SOURCE_SPECS = (
    SourceSpec(
        "mooncake-store/include/allocation_strategy.h",
        "allocation_api_and_best_effort_placement",
        True,
    ),
    SourceSpec("mooncake-store/include/eviction_strategy.h", "lru_fifo_key_order", True),
    SourceSpec("mooncake-store/include/master_service.h", "master_public_api", True),
    SourceSpec("mooncake-store/include/replica.h", "replica_state_machine", True),
    SourceSpec("mooncake-store/include/segment.h", "segment_api_and_state", True),
    SourceSpec("mooncake-store/include/transfer_task.h", "store_transfer_task_api", True),
    SourceSpec("mooncake-store/src/master_service.cpp", "master_publication_semantics", True),
    SourceSpec("mooncake-store/src/segment.cpp", "segment_lifecycle", True),
    SourceSpec("mooncake-store/src/transfer_task.cpp", "store_transfer_task_lifecycle", True),
    SourceSpec("mooncake-store/tests/allocation_strategy_test.cpp", "official_allocation_tests"),
    SourceSpec("mooncake-store/tests/eviction_strategy_test.cpp", "official_eviction_tests"),
    SourceSpec("mooncake-store/tests/master_service_test.cpp", "official_master_tests"),
    SourceSpec("mooncake-store/tests/segment_test.cpp", "official_segment_tests"),
    SourceSpec("mooncake-store/tests/transfer_task_test.cpp", "official_store_task_tests"),
    SourceSpec("mooncake-transfer-engine/include/config.h", "te_slice_default", True),
    SourceSpec("mooncake-transfer-engine/include/memory_location.h", "memory_locality_api", True),
    SourceSpec(
        "mooncake-transfer-engine/include/multi_transport.h", "transport_dispatch_api", True
    ),
    SourceSpec("mooncake-transfer-engine/include/topology.h", "topology_api", True),
    SourceSpec("mooncake-transfer-engine/include/transfer_engine.h", "te_public_api", True),
    SourceSpec(
        "mooncake-transfer-engine/include/transport/transport.h",
        "batch_task_slice_state",
        True,
    ),
    SourceSpec("mooncake-transfer-engine/src/config.cpp", "te_slice_override", True),
    SourceSpec(
        "mooncake-transfer-engine/src/memory_location.cpp", "memory_locality_semantics", True
    ),
    SourceSpec(
        "mooncake-transfer-engine/src/multi_transport.cpp", "batch_dispatch_semantics", True
    ),
    SourceSpec("mooncake-transfer-engine/src/topology.cpp", "topology_selection_semantics", True),
    SourceSpec("mooncake-transfer-engine/src/transfer_engine.cpp", "te_public_delegation", True),
    SourceSpec(
        "mooncake-transfer-engine/tests/memory_location_test.cpp", "official_locality_tests"
    ),
    SourceSpec("mooncake-transfer-engine/tests/topology_test.cpp", "official_topology_tests"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless the existing golden is byte-identical to commit objects",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        document = capture(root)
        expected = _canonical_json_bytes(document)
        if args.check:
            actual = _read_regular_file_nofollow(output)
            if actual != expected:
                raise CaptureError(f"{output} is not byte-identical to a fresh capture")
            status_value = "checked"
        else:
            _write_no_clobber(output, expected)
            status_value = "generated"
    except (CaptureError, OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "evidence_class": EVIDENCE_CLASS,
                "output": str(output),
                "sha256": hashlib.sha256(expected).hexdigest(),
                "source_file_count": len(SOURCE_SPECS),
                "status": status_value,
            },
            sort_keys=True,
        )
    )
    return 0


def capture(root: Path) -> dict[str, object]:
    lock = _load_json_object(root / SOURCE_LOCK_RELATIVE_PATH)
    repositories = _mapping(lock.get("repositories"), "repositories")
    mooncake_lock = _mapping(repositories.get("mooncake"), "repositories.mooncake")
    repository = Path(_string(mooncake_lock.get("repository"), "Mooncake repository"))
    if repository != EXPECTED_REPOSITORY:
        raise CaptureError(
            f"source-lock Mooncake repository drift: expected {EXPECTED_REPOSITORY}, "
            f"got {repository}"
        )
    if mooncake_lock.get("commit") != EXPECTED_COMMIT:
        raise CaptureError("source-lock Mooncake commit drift")
    if mooncake_lock.get("tree") != EXPECTED_TREE:
        raise CaptureError("source-lock Mooncake tree drift")
    if mooncake_lock.get("source_policy") != "commit_object_only":
        raise CaptureError("source-lock permits a non-commit-object Mooncake input")

    if _git(repository, "cat-file", "-t", EXPECTED_COMMIT).decode().strip() != "commit":
        raise CaptureError("pinned Mooncake commit object is unavailable")
    actual_tree = _git(repository, "rev-parse", f"{EXPECTED_COMMIT}^{{tree}}").decode().strip()
    if actual_tree != EXPECTED_TREE:
        raise CaptureError(
            f"pinned Mooncake tree drift: expected {EXPECTED_TREE}, got {actual_tree}"
        )

    locked_by_path: dict[str, Mapping[str, Any]] = {}
    for raw in _list(mooncake_lock.get("files"), "repositories.mooncake.files"):
        record = _mapping(raw, "Mooncake source-lock file")
        path = _safe_relative(record.get("path"), "Mooncake source-lock path").as_posix()
        locked_by_path[path] = record

    source_bytes: dict[str, bytes] = {}
    file_records: list[dict[str, object]] = []
    locked_paths_verified: list[str] = []
    for spec in sorted(SOURCE_SPECS, key=lambda item: item.path):
        blob, payload = _read_commit_blob(repository, spec.path)
        sha256 = hashlib.sha256(payload).hexdigest()
        source_bytes[spec.path] = payload
        if spec.required_in_source_lock:
            locked = locked_by_path.get(spec.path)
            if locked is None:
                raise CaptureError(f"source-lock omits required Mooncake path: {spec.path}")
            if locked.get("source") != "commit_object":
                raise CaptureError(f"source-lock path is not commit-object-only: {spec.path}")
            if locked.get("git_blob") != blob or locked.get("sha256") != sha256:
                raise CaptureError(f"source-lock blob/SHA drift: {spec.path}")
            locked_paths_verified.append(spec.path)
        file_records.append(
            {
                "git_blob": blob,
                "path": spec.path,
                "role": spec.role,
                "sha256": sha256,
                "source": "commit_object",
            }
        )

    gitlinks: dict[str, str] = {}
    for path, expected_oid in sorted(EXPECTED_GITLINKS.items()):
        mode, object_type, oid = _ls_tree_entry(repository, path)
        if (mode, object_type, oid) != ("160000", "commit", expected_oid):
            raise CaptureError(
                f"pinned gitlink drift for {path}: "
                f"expected 160000 commit {expected_oid}, got {mode} {object_type} {oid}"
            )
        gitlinks[path] = oid

    observations = _source_observations(source_bytes)
    return {
        "schema": SCHEMA,
        "evidence_class": EVIDENCE_CLASS,
        "formal_use_allowed": False,
        "claim_exclusions": [
            "external_mooncake_binary_execution",
            "rpc_and_concurrency_parity",
            "allocator_extent_parity",
            "exact_random_placement_parity",
            "topology_device_selection_parity",
            "cuda_rdma_tcp_execution",
            "communication_timing_or_calibration",
            "physical_validation",
            "ssd_nof_or_local_disk_baseline_runtime",
        ],
        "provenance": {
            "repository": str(repository),
            "commit": EXPECTED_COMMIT,
            "tree": EXPECTED_TREE,
            "source_policy": "git_commit_object_only",
            "worktree_files_read": False,
            "gitlinks": gitlinks,
            "source_lock": {
                "path": SOURCE_LOCK_RELATIVE_PATH.as_posix(),
                "locked_paths_verified": locked_paths_verified,
            },
            "files": file_records,
        },
        "source_observations": observations,
        "moonkvsim_mapping_cases": _mapping_cases(),
        "external_runtime_capture": {
            "executed_by_this_generator": False,
            "status": "NOT_CAPTURED",
            "reason": (
                "This generator intentionally performs commit-object source extraction only. "
                "An isolated official build/test result must be stored separately."
            ),
            "required_next_evidence": [
                "official Master/Store tests from an isolated pinned archive",
                "official Transfer Engine batch/topology tests from that archive",
                "MoonKVSim-versus-external state/API trace comparison",
                "physical C0-C4 communication calibration",
            ],
        },
    }


def _source_observations(source: Mapping[str, bytes]) -> dict[str, object]:
    text = {path: payload.decode("utf-8") for path, payload in source.items()}
    replica_states = _enum_members(
        text["mooncake-store/include/replica.h"], "enum class ReplicaStatus"
    )
    if replica_states != (
        "UNDEFINED",
        "INITIALIZED",
        "PROCESSING",
        "COMPLETE",
        "REMOVED",
        "FAILED",
    ):
        raise CaptureError(f"unexpected pinned ReplicaStatus members: {replica_states}")
    transfer_states = _enum_members(
        text["mooncake-transfer-engine/include/transport/transport.h"],
        "enum TransferStatusEnum",
    )
    if transfer_states != (
        "WAITING",
        "PENDING",
        "INVALID",
        "CANCELED",
        "COMPLETED",
        "TIMEOUT",
        "FAILED",
    ):
        raise CaptureError(f"unexpected pinned TransferStatus members: {transfer_states}")
    slice_states = _enum_members(
        text["mooncake-transfer-engine/include/transport/transport.h"],
        "enum SliceStatus",
    )
    if slice_states != ("PENDING", "POSTED", "SUCCESS", "TIMEOUT", "FAILED"):
        raise CaptureError(f"unexpected pinned SliceStatus members: {slice_states}")

    config_header = text["mooncake-transfer-engine/include/config.h"]
    slice_match = re.search(r"\bslice_size\s*=\s*(\d+)\s*;", config_header)
    if slice_match is None or int(slice_match.group(1)) != 65_536:
        raise CaptureError("pinned Transfer Engine default slice_size is not 65536")

    required_fragments = {
        "mooncake-store/include/master_service.h": (
            "auto PutStart(",
            "auto PutEnd(",
            "auto GetReplicaList(",
            "auto Remove(",
        ),
        "mooncake-store/src/master_service.cpp": (
            "replica.is_completed()",
            "ErrorCode::REPLICA_IS_NOT_READY",
            "[](Replica& replica) { replica.mark_complete(); }",
            "if (!metadata.AllReplicas(&Replica::fn_is_completed))",
        ),
        "mooncake-store/include/allocation_strategy.h": (
            "best-effort semantics",
            "used_segments.contains",
            "ReplicaStatus::PROCESSING",
            "ErrorCode::NO_AVAILABLE_HANDLE",
        ),
        "mooncake-store/include/eviction_strategy.h": (
            "all_key_list_.push_front(key);",
            "std::string evicted_key = all_key_list_.back();",
            "class FIFOEvictionStrategy",
        ),
        "mooncake-store/tests/master_service_test.cpp": (
            "EXPECT_EQ(ErrorCode::REPLICA_IS_NOT_READY, results[4].error());",
            "TEST_F(MasterServiceTest, ReplicationFactorTwoWithSingleSegment)",
            "EXPECT_EQ(1u, replicas.size());",
        ),
        "mooncake-store/tests/eviction_strategy_test.cpp": (
            'EXPECT_EQ(evicted_key, "key1");',
            'EXPECT_EQ(evicted_key, "key4");',
            'EXPECT_EQ(evicted_key, "key2");',
            "FIFO not support remove a randomly accessed key",
        ),
        "mooncake-store/tests/transfer_task_test.cpp": (
            "Same host, different port -> different process, NOT local.",
            "TransferStrategy::LOCAL_MEMCPY",
            "TransferStrategy::TRANSFER_ENGINE",
        ),
        "mooncake-transfer-engine/include/transfer_engine.h": (
            "BatchID allocateBatchID(size_t batch_size);",
            "Status submitTransfer(BatchID batch_id,",
            "Status getTransferStatus(BatchID batch_id, size_t task_id,",
            "Status freeBatchID(BatchID batch_id);",
        ),
        "mooncake-transfer-engine/src/multi_transport.cpp": (
            "Exceed the limitation of batch capacity",
            "BatchID cannot be freed until all tasks are done",
            "submit_tasks[transport].push_back(&task);",
        ),
        "mooncake-transfer-engine/src/config.cpp": (
            'std::getenv("MC_SLICE_SIZE")',
            "config.slice_size = val;",
        ),
        "mooncake-transfer-engine/include/topology.h": (
            "int selectDevice(",
            "int selectDeviceByLocalHca(",
            "int disableDevice(",
        ),
        "mooncake-transfer-engine/tests/topology_test.cpp": (
            "TestSelectDevice",
            "TestDisableOnlyPreferredDeviceLeavesNoSelection",
            "ERR_DEVICE_NOT_FOUND",
        ),
    }
    for path, fragments in required_fragments.items():
        for fragment in fragments:
            if fragment not in text[path]:
                raise CaptureError(f"semantic anchor missing from {path}: {fragment!r}")

    return {
        "master_directory": {
            "public_api": ["PutStart", "PutEnd", "GetReplicaList", "Remove"],
            "replica_status_members": list(replica_states),
            "visibility_sequence": [
                {
                    "operation": "PutStart",
                    "upstream_replica_status": "PROCESSING",
                    "subsequent_get_outcome": "REPLICA_IS_NOT_READY",
                    "readable": False,
                },
                {
                    "operation": "PutEnd",
                    "upstream_replica_status": "COMPLETE",
                    "subsequent_get_outcome": "COMPLETE_DESCRIPTORS",
                    "readable": True,
                },
                {
                    "operation": "Remove",
                    "upstream_replica_status": "ERASED_OR_REMOVED",
                    "subsequent_get_outcome": "OBJECT_NOT_FOUND",
                    "readable": False,
                },
            ],
            "put_end_scope": (
                "PutEnd selects replicas by ReplicaType and marks every matching "
                "PROCESSING replica COMPLETE; the API has no successful-replica subset."
            ),
            "remove_precondition": "every replica is COMPLETE, even when force=true",
            "master_moves_payload_bytes": False,
        },
        "allocation": {
            "strategy": "RandomAllocationStrategy",
            "best_effort": True,
            "preferred_segments_first": True,
            "one_replica_per_distinct_segment_per_slice": True,
            "empty_pool_outcome": "NO_AVAILABLE_HANDLE",
            "official_case_replica_factor_2_single_segment_result_count": 1,
            "exact_random_choice_is_contractual": False,
        },
        "eviction": {
            "lru_official_case": {
                "operations": [
                    "add:key1",
                    "add:key2",
                    "evict",
                    "add:key3",
                    "add:key4",
                    "update:key2",
                    "update:key3",
                    "evict",
                ],
                "evicted_keys": ["key1", "key4"],
            },
            "fifo_official_case": {
                "operations": [
                    "add:key1",
                    "add:key2",
                    "evict",
                    "add:key3",
                    "add:key4",
                    "update:key2",
                    "update:key3",
                    "evict",
                ],
                "evicted_keys": ["key1", "key2"],
            },
            "fifo_remove_key": (
                "returns OK but is a no-op because FIFO AddKey does not populate "
                "the base-class key index"
            ),
        },
        "transfer_engine": {
            "public_batch_api": [
                "allocateBatchID",
                "submitTransfer",
                "getTransferStatus",
                "getBatchTransferStatus",
                "freeBatchID",
            ],
            "transfer_status_members": list(transfer_states),
            "slice_status_members": list(slice_states),
            "default_slice_size_bytes": 65_536,
            "slice_size_override": "MC_SLICE_SIZE",
            "batch_capacity_is_fixed_at_allocation": True,
            "submit_over_capacity_outcome": "TooManyRequests",
            "free_before_all_submitted_tasks_finish_outcome": "BatchBusy",
            "multi_transport_dispatch": "group tasks by selected Transport then submit",
            "success_byte_accounting": "Slice::markSuccess adds exactly Slice.length",
        },
        "store_transfer_task": {
            "same_process_locality": "full endpoint strings must be identical",
            "same_ip_different_port_is_local": False,
        },
        "topology": {
            "public_api": ["parse", "disableDevice", "selectDevice", "selectDeviceByLocalHca"],
            "selection_order": "preferred HCA before available HCA; retry enumerates both",
            "empty_or_disabled_outcome": "ERR_DEVICE_NOT_FOUND",
            "retry_zero_may_use_random_or_round_robin": True,
        },
    }


def _mapping_cases() -> dict[str, object]:
    return {
        "verification_level": "E2_toy_source_mapped_only",
        "master_visibility_single_dram": {
            "steps": [
                {"operation": "put_start", "ticket_state": "PENDING"},
                {"operation": "get_replica_list", "visible_replica_count": 0},
                {"operation": "put_end", "committed_replica_count": 1},
                {"operation": "get_replica_list", "visible_replica_count": 1},
                {"operation": "remove", "removed_replica_count": 1},
                {"operation": "get_replica_list", "visible_replica_count": 0},
            ],
            "equivalence_scope": "publication visibility and capacity lifecycle only",
            "known_api_difference": (
                "pinned GetReplicaList reports REPLICA_IS_NOT_READY for pending metadata; "
                "MoonKVSim exposes an empty visible set and does not emulate the RPC error code"
            ),
        },
        "best_effort_distinct_segments": {
            "requested_replicas": 3,
            "eligible_segments": 2,
            "expected_allocated_replicas": 2,
            "expected_distinct_segments": 2,
            "equivalence_scope": "best-effort count and per-slice segment uniqueness",
        },
        "lru_eviction": {"expected_evicted_keys": ["key1", "key4"]},
        "fifo_eviction": {
            "expected_evicted_keys": ["key1", "key2"],
            "remove_key_effect": "NO_OP",
        },
        "default_slicing": {
            "payload_bytes": 131_073,
            "expected_slice_lengths": [65_536, 65_536, 1],
            "expected_terminal_status": "COMPLETED",
            "expected_transferred_bytes": 131_073,
        },
        "deliberate_simulation_replacements": [
            {
                "area": "PutEnd",
                "replacement": (
                    "MoonKVSim accepts an explicit successful-replica subset and atomically "
                    "aborts the remaining ticket replicas for failure accounting."
                ),
                "not_claimed": "exact external PutEnd API parity",
            },
            {
                "area": "allocation_randomness",
                "replacement": "a manifest-seeded permutation replaces upstream process randomness",
                "not_claimed": "exact segment choice parity",
            },
            {
                "area": "topology",
                "replacement": (
                    "explicit resource paths and deterministic priority replace upstream "
                    "HCA-index random/round-robin selection"
                ),
                "not_claimed": "exact Topology::selectDevice parity",
            },
            {
                "area": "batch_handle",
                "replacement": (
                    "stable simulator batch/task IDs replace the pointer-valued opaque BatchID"
                ),
                "not_claimed": "binary handle or memory-lifetime parity",
            },
            {
                "area": "slice_cancel",
                "replacement": (
                    "MoonKVSim adds an explicit CANCELED slice terminal state for DES failure audit"
                ),
                "not_claimed": "exact upstream SliceStatus enum parity",
            },
        ],
    }


def _enum_members(text: str, declaration: str) -> tuple[str, ...]:
    start = text.find(declaration)
    if start < 0:
        raise CaptureError(f"enum declaration is missing: {declaration}")
    open_brace = text.find("{", start)
    close_brace = text.find("};", open_brace)
    if open_brace < 0 or close_brace < 0:
        raise CaptureError(f"enum body is malformed: {declaration}")
    body = re.sub(r"//[^\n]*|/\*.*?\*/", "", text[open_brace + 1 : close_brace], flags=re.S)
    return tuple(re.findall(r"\b[A-Z][A-Z0-9_]*\b", body))


def _read_commit_blob(repository: Path, relative_path: str) -> tuple[str, bytes]:
    path = _safe_relative(relative_path, "commit-object path").as_posix()
    mode, object_type, oid = _ls_tree_entry(repository, path)
    if mode not in {"100644", "100755"} or object_type != "blob":
        raise CaptureError(f"expected regular blob for {path}, got {mode} {object_type}")
    payload = _git(repository, "cat-file", "blob", oid)
    return oid, payload


def _ls_tree_entry(repository: Path, relative_path: str) -> tuple[str, str, str]:
    output = _git(repository, "ls-tree", EXPECTED_COMMIT, "--", relative_path)
    try:
        metadata, actual_path = output.decode("utf-8").rstrip("\n").split("\t", 1)
        mode, object_type, oid = metadata.split(" ", 2)
    except ValueError as error:
        raise CaptureError(f"missing or malformed tree entry: {relative_path}") from error
    if actual_path != relative_path:
        raise CaptureError(f"tree path mismatch: expected {relative_path}, got {actual_path}")
    return mode, object_type, oid


def _git(repository: Path, *args: str) -> bytes:
    environment = os.environ.copy()
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
        env=environment,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise CaptureError(f"git {' '.join(args)} failed: {stderr}")
    return result.stdout


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_regular_file_nofollow(path))
    except json.JSONDecodeError as error:
        raise CaptureError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise CaptureError(f"expected JSON object in {path}")
    return value


def _read_regular_file_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CaptureError(
            f"cannot open regular file without following symlinks: {path}: {error}"
        ) from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise CaptureError(f"not a regular file: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _write_no_clobber(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o644)
    except FileExistsError as error:
        raise CaptureError(f"refusing to overwrite existing golden: {path}") from error
    except OSError as error:
        raise CaptureError(f"cannot create golden without clobbering: {path}: {error}") from error
    complete = False
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise CaptureError(f"short write while creating {path}")
            view = view[written:]
        os.fsync(descriptor)
        complete = True
    finally:
        os.close(descriptor)
        if not complete:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path.parent, directory_flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _safe_relative(value: object, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise CaptureError(f"{label} must be a non-empty string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise CaptureError(f"{label} must be a normalized relative POSIX path: {value!r}")
    return path


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CaptureError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise CaptureError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CaptureError(f"{label} must be a non-empty string")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
