#!/usr/bin/env python3
"""Create a no-clobber audit record before the Vanilla physical submission.

This program never submits, cancels, requeues, releases, or otherwise mutates a
Slurm job.  It validates the clean build, hashes the exact repository inputs,
runs ``sbatch --test-only``, and records current gpu10/protected-job state.  A
successful record is only permission to submit the already-hashed batch file;
the allocated job still performs the fail-closed GPU-process audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

SCHEMA: Final = "moonkvsim.vanilla_mooncake_e4_preflight.v1"
EXPECTED_REPOSITORY_ROOT: Final = Path("/home/comp/zhanzhao/MoonKVSim")
PINNED_MOONCAKE_COMMIT: Final = "f161118c18dbea1b56dd5c7908b9eaa440353e2e"
PINNED_VLLM_COMMIT: Final = "644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504"
PINNED_VLLM_VERSION: Final = "1.2.2+aegiskv.sm89"
PINNED_VLLM_WHEEL_SHA256: Final = "3db1279f72293195d6a1a5ef97f48cd72bedac6dfb10237c9b790ae8650491b2"
PINNED_VLLM_RUNTIME: Final = Path("/home/comp/zhanzhao/Mooncake/aegiskv/.venv-vllm-sm89/bin/python")
PINNED_VLLM_MANIFEST: Final = Path(
    "/home/comp/zhanzhao/Mooncake/aegiskv/paper/fallback_4090/runtime-build-manifest.json"
)
PINNED_MODEL_REVISION: Final = "b968826d9c46dd6066d109eabc6255188de91218"
PINNED_MODEL: Final = (
    Path("/home/comp/zhanzhao/.cache/huggingface/hub/models--Qwen--Qwen3-8B/snapshots")
    / PINNED_MODEL_REVISION
)
PINNED_NATIVE_DEPENDENCY_SOURCE: Final = Path(
    "/home/comp/zhanzhao/Mooncake/.deps-sglang-profiler"
)
PINNED_CUDART: Final = Path(
    "/usr/local/cuda-12.8/targets/x86_64-linux/lib/libcudart.so.12.8.90"
)
PINNED_GCC_RUNTIME_ROOT: Final = Path("/usr/local/gcc/gcc-11.2.0/lib64")
LOCAL_WHEEL_PLATFORM_TAG: Final = "linux_x86_64"
AUDITWHEEL_REPAIR_PLATFORM_TAG: Final = "manylinux_2_34_x86_64"
PINNED_BUILD_PACKAGES: Final = (
    "pip==26.2.1",
    "build==1.3.0",
    "wheel==0.46.3",
    "auditwheel==6.5.0",
    "setuptools==80.10.2",
)
HELD_PENDING_JOBS: Final = (136567, 135889, 135847, 135326)
READ_ONLY_MONITORED_JOBS: Final = (142290, 142291)
PROTECTED_JOBS: Final = HELD_PENDING_JOBS + READ_ONLY_MONITORED_JOBS
EXPECTED_SBATCH: Final = {
    "--partition": "debug",
    "--nodelist": "gpu10",
    "--gres": "gpu:rtx4090:2",
    "--nodes": "1",
    "--ntasks": "1",
    "--cpus-per-task": "32",
    "--mem": "160G",
    "--time": "01:30:00",
    "--exclusive": None,
}
HEX64: Final = re.compile(r"^[0-9a-f]{64}$")


class PreflightError(RuntimeError):
    """A fail-closed source, bundle, scheduler, or publication error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PreflightError(f"cannot load JSON {path}: {error}") from error


def run_capture(command: Sequence[str]) -> dict[str, Any]:
    completed = subprocess.run(list(command), text=True, capture_output=True, check=False)
    record = {
        "command": list(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if completed.returncode != 0:
        raise PreflightError(
            f"command failed ({completed.returncode}): {' '.join(command)}: "
            f"{completed.stderr.strip()}"
        )
    return record


def parse_sbatch_directives(text: str) -> dict[str, str | None]:
    directives: dict[str, str | None] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("#SBATCH "):
            continue
        value = line.removeprefix("#SBATCH ").strip()
        if not value.startswith("--"):
            raise PreflightError(f"short-form SBATCH directive is forbidden: {value!r}")
        item: str | None
        if "=" in value:
            key, item = value.split("=", 1)
        else:
            parts = value.split(maxsplit=1)
            key = parts[0]
            item = None if len(parts) == 1 else parts[1]
        if key in directives:
            raise PreflightError(f"duplicate SBATCH directive: {key}")
        directives[key] = item
    mismatches = {
        key: {"observed": directives.get(key), "expected": expected}
        for key, expected in EXPECTED_SBATCH.items()
        if key not in directives or directives.get(key) != expected
    }
    if mismatches:
        raise PreflightError(f"SBATCH resource contract mismatch: {mismatches}")
    return directives


def verify_checksum_bundle(directory: Path) -> dict[str, Any]:
    if not directory.is_dir() or directory.is_symlink():
        raise PreflightError(f"clean build is missing or unsafe: {directory}")
    checksum_path = directory / "SHA256SUMS"
    if not checksum_path.is_file() or checksum_path.is_symlink():
        raise PreflightError("clean build lacks a safe SHA256SUMS")
    expected: dict[str, str] = {}
    for raw_line in checksum_path.read_text(encoding="utf-8").splitlines():
        if "  " not in raw_line:
            raise PreflightError(f"malformed SHA256SUMS row: {raw_line!r}")
        digest, relative = raw_line.split("  ", 1)
        relative_path = Path(relative)
        if (
            not HEX64.fullmatch(digest)
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or relative in expected
        ):
            raise PreflightError(f"unsafe SHA256SUMS row: {raw_line!r}")
        expected[relative] = digest
    entries = list(directory.rglob("*"))
    symlinks = sorted(
        path.relative_to(directory).as_posix() for path in entries if path.is_symlink()
    )
    if symlinks:
        raise PreflightError(f"clean-build bundle contains symlinks: {symlinks}")
    unsupported = sorted(
        path.relative_to(directory).as_posix()
        for path in entries
        if not path.is_dir() and not path.is_file()
    )
    if unsupported:
        raise PreflightError(f"clean-build bundle contains unsupported entries: {unsupported}")
    actual_files = {
        path.relative_to(directory).as_posix()
        for path in entries
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if set(expected) != actual_files:
        raise PreflightError(
            "clean-build checksum inventory mismatch: "
            f"missing={sorted(actual_files - set(expected))}, "
            f"extra={sorted(set(expected) - actual_files)}"
        )
    for relative, digest in expected.items():
        path = directory / relative
        if not path.is_file() or path.is_symlink() or sha256_file(path) != digest:
            raise PreflightError(f"clean-build checksum mismatch or symlink: {relative}")
    return {
        "directory": str(directory.resolve()),
        "sha256sums": str(checksum_path.resolve()),
        "sha256sums_sha256": sha256_file(checksum_path),
        "artifact_count": len(expected),
    }


def regular_file_tree_manifest(directory: Path) -> list[dict[str, Any]]:
    """Recompute a symlink-free regular-file tree with build-manifest semantics."""

    if not directory.is_dir() or directory.is_symlink():
        raise PreflightError(f"runtime library directory is missing or unsafe: {directory}")
    records: list[dict[str, Any]] = []
    for current, directories, files in os.walk(directory, followlinks=False):
        current_path = Path(current)
        directories.sort()
        files.sort()
        for name in directories:
            path = current_path / name
            if path.is_symlink():
                raise PreflightError(f"runtime library directory contains symlink: {path}")
        for name in files:
            path = current_path / name
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise PreflightError(f"runtime library entry is not regular: {path}")
            records.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
                    "type": "regular",
                    "bytes": metadata.st_size,
                    "sha256": sha256_file(path),
                }
            )
    records.sort(key=lambda row: str(row["path"]))
    if not records:
        raise PreflightError("runtime library directory is empty")
    return records


def verify_clean_build(directory: Path) -> dict[str, Any]:
    record = verify_checksum_bundle(directory)
    incomplete_markers = [
        path.name
        for path in (directory / "BUILD_INCOMPLETE", directory / "PUBLICATION_INCOMPLETE")
        if path.exists() or path.is_symlink()
    ]
    if incomplete_markers:
        raise PreflightError(f"clean build contains incomplete markers: {incomplete_markers}")
    complete = load_json(directory / "PUBLICATION_COMPLETE.json")
    manifest_path = directory / "build-manifest.json"
    manifest = load_json(manifest_path)
    wheels = sorted(directory.glob("*.whl"))
    if len(wheels) != 1 or wheels[0].is_symlink():
        raise PreflightError(f"expected one safe clean wheel, found {wheels}")
    wheel = wheels[0]
    source = manifest.get("source", {}) if isinstance(manifest, dict) else {}
    build = manifest.get("build", {}) if isinstance(manifest, dict) else {}
    wheel_manifest = manifest.get("wheel", {}) if isinstance(manifest, dict) else {}
    native_manifest_path = directory / "native-dependency-manifest.json"
    native_manifest = load_json(native_manifest_path)
    if not isinstance(native_manifest, dict):
        raise PreflightError("native dependency manifest must be an object")
    native_tree = native_manifest.get("tree_manifest")
    selected_native_paths = native_manifest.get("selected_paths")
    if (
        not isinstance(native_tree, list)
        or not native_tree
        or not isinstance(selected_native_paths, list)
        or not selected_native_paths
        or not all(
            isinstance(item, str)
            and item
            and not Path(item).is_absolute()
            and ".." not in Path(item).parts
            for item in selected_native_paths
        )
        or len(set(selected_native_paths)) != len(selected_native_paths)
    ):
        raise PreflightError("native dependency manifest paths/tree are incomplete or unsafe")
    native_tree_sha256 = hashlib.sha256(
        canonical_json(native_tree).encode("utf-8")
    ).hexdigest()
    native_runtime_manifest_path = directory / "native-runtime-manifest.json"
    native_runtime_manifest = load_json(native_runtime_manifest_path)
    if not isinstance(native_runtime_manifest, dict):
        raise PreflightError("native runtime manifest must be an object")
    native_runtime_directory = directory / "native-runtime"
    native_runtime_tree = native_runtime_manifest.get("tree_manifest")
    observed_runtime_tree = regular_file_tree_manifest(native_runtime_directory)
    if native_runtime_tree != observed_runtime_tree:
        raise PreflightError("native runtime manifest does not match published runtime files")
    native_runtime_tree_sha256 = hashlib.sha256(
        canonical_json(observed_runtime_tree).encode("utf-8")
    ).hexdigest()
    elf_audit_path = directory / "elf-runtime-audit.json"
    elf_audit = load_json(elf_audit_path)
    elf_audit_manifest = (
        wheel_manifest.get("elf_runtime_audit", {})
        if isinstance(wheel_manifest, dict)
        else {}
    )
    if not isinstance(elf_audit, dict) or not isinstance(elf_audit_manifest, dict):
        raise PreflightError("ELF runtime audit and its wheel binding must be objects")
    pinned_runtime_sha256 = elf_audit.get("pinned_runtime_sha256")
    observed_pinned_runtimes = elf_audit.get("observed_pinned_runtimes")
    elf_records = elf_audit.get("records")
    if (
        not isinstance(pinned_runtime_sha256, dict)
        or not isinstance(observed_pinned_runtimes, dict)
        or not isinstance(elf_records, list)
        or not elf_records
    ):
        raise PreflightError("ELF runtime audit is incomplete")
    expected_runtime_pins = {
        "libcudart.so.12": sha256_file(PINNED_CUDART),
        "libgcc_s.so.1": sha256_file(PINNED_GCC_RUNTIME_ROOT / "libgcc_s.so.1"),
        "libstdc++.so.6": sha256_file(PINNED_GCC_RUNTIME_ROOT / "libstdc++.so.6"),
    }
    actual_runtime_pins = {
        soname: sha256_file(native_runtime_directory / soname)
        for soname in expected_runtime_pins
    }
    expected = {
        "publication_complete": (complete.get("publication"), "COMPLETE"),
        "publication_status": (complete.get("status"), "PASS"),
        "manifest_status": (manifest.get("status"), "PASS"),
        "source_commit": (source.get("commit"), PINNED_MOONCAKE_COMMIT),
        "dirty_files_copied": (source.get("dirty_worktree_files_copied"), False),
        "dirty_mooncake_venv_modified": (
            build.get("dirty_mooncake_venv_modified"),
            False,
        ),
        "pinned_vllm_venv_modified": (
            build.get("pinned_vllm_venv_modified"),
            False,
        ),
        "ssd_nvme_enabled": (build.get("ssd_nvme_enabled"), False),
        "native_dependency_source": (
            build.get("native_dependency_source"),
            str(PINNED_NATIVE_DEPENDENCY_SOURCE),
        ),
        "native_dependency_construction": (
            native_manifest.get("construction"),
            "relocated_hash_manifested_subset",
        ),
        "native_dependency_manifest_sha256": (
            build.get("native_dependency_manifest_sha256"),
            sha256_file(native_manifest_path),
        ),
        "native_dependency_tree_manifest_sha256": (
            build.get("native_dependency_tree_manifest_sha256"),
            native_tree_sha256,
        ),
        "native_manifest_internal_tree_sha256": (
            native_manifest.get("tree_manifest_sha256"),
            native_tree_sha256,
        ),
        "native_runtime_directory": (
            build.get("native_runtime_directory"),
            "native-runtime",
        ),
        "native_runtime_construction": (
            native_runtime_manifest.get("construction"),
            "dereferenced_regular_files_from_hashed_native_subset",
        ),
        "native_runtime_library_count": (
            native_runtime_manifest.get("library_count"),
            len(observed_runtime_tree),
        ),
        "native_runtime_manifest_sha256": (
            build.get("native_runtime_manifest_sha256"),
            sha256_file(native_runtime_manifest_path),
        ),
        "native_runtime_tree_manifest_sha256": (
            build.get("native_runtime_tree_manifest_sha256"),
            native_runtime_tree_sha256,
        ),
        "native_runtime_internal_tree_sha256": (
            native_runtime_manifest.get("tree_manifest_sha256"),
            native_runtime_tree_sha256,
        ),
        "local_wheel_platform_tag": (
            build.get("local_wheel_platform_tag"),
            LOCAL_WHEEL_PLATFORM_TAG,
        ),
        "auditwheel_repair_platform_tag": (
            build.get("auditwheel_repair_platform_tag"),
            AUDITWHEEL_REPAIR_PLATFORM_TAG,
        ),
        "wheel_platform_tag": (
            wheel_manifest.get("platform_tag"),
            LOCAL_WHEEL_PLATFORM_TAG,
        ),
        "elf_audit_path": (elf_audit_manifest.get("path"), elf_audit_path.name),
        "elf_audit_sha256": (
            elf_audit_manifest.get("sha256"),
            sha256_file(elf_audit_path),
        ),
        "elf_audit_manifest_status": (elf_audit_manifest.get("status"), "PASS"),
        "elf_audit_status": (elf_audit.get("status"), "PASS"),
        "elf_audit_schema": (
            elf_audit.get("schema"),
            "moonkvsim.vanilla_mooncake_elf_runtime_audit.v1",
        ),
        "elf_audit_count": (
            elf_audit_manifest.get("elf_count"),
            len(elf_records),
        ),
        "elf_audit_internal_count": (elf_audit.get("elf_count"), len(elf_records)),
        "elf_audit_pinned_runtime_sha256": (
            pinned_runtime_sha256,
            expected_runtime_pins,
        ),
        "published_pinned_runtime_sha256": (
            actual_runtime_pins,
            expected_runtime_pins,
        ),
        "observed_pinned_runtime_names": (
            set(observed_pinned_runtimes),
            set(expected_runtime_pins),
        ),
        "pinned_build_packages": (
            tuple(build.get("pinned_build_packages", ())),
            PINNED_BUILD_PACKAGES,
        ),
        "pep517_constrained": (build.get("pep517_build_isolation_constrained"), True),
        "source_manifest_sha256": (
            source.get("tree_manifest_sha256"),
            sha256_file(directory / "source-tree-manifest.json"),
        ),
        "constraints_sha256": (
            build.get("build_constraints_sha256"),
            sha256_file(directory / "build-constraints.txt"),
        ),
        "freeze_sha256": (
            build.get("build_tool_freeze_sha256"),
            sha256_file(directory / "build-tool-freeze.txt"),
        ),
        "wheel_sha256": (wheel_manifest.get("sha256"), sha256_file(wheel)),
    }
    mismatches = {
        key: {"observed": observed, "expected": wanted}
        for key, (observed, wanted) in expected.items()
        if observed != wanted
    }
    if mismatches:
        raise PreflightError(f"clean-build manifest mismatch: {mismatches}")
    if "aegis" in wheel.name.lower() or not wheel.name.endswith(
        f"-{LOCAL_WHEEL_PLATFORM_TAG}.whl"
    ):
        raise PreflightError("clean wheel filename contains Aegis or has a false platform tag")
    record.update(
        {
            "manifest": str(manifest_path.resolve()),
            "manifest_sha256": sha256_file(manifest_path),
            "native_dependency_manifest": str(native_manifest_path.resolve()),
            "native_dependency_manifest_sha256": sha256_file(native_manifest_path),
            "native_dependency_tree_manifest_sha256": native_tree_sha256,
            "native_runtime_directory": str(native_runtime_directory.resolve()),
            "native_runtime_manifest": str(native_runtime_manifest_path.resolve()),
            "native_runtime_manifest_sha256": sha256_file(native_runtime_manifest_path),
            "native_runtime_tree_manifest_sha256": native_runtime_tree_sha256,
            "elf_runtime_audit": str(elf_audit_path.resolve()),
            "elf_runtime_audit_sha256": sha256_file(elf_audit_path),
            "source_commit": source["commit"],
            "wheel": str(wheel.resolve()),
            "wheel_sha256": sha256_file(wheel),
        }
    )
    return record


def verify_vllm_bundle() -> dict[str, Any]:
    runtime = PINNED_VLLM_RUNTIME
    manifest_path = PINNED_VLLM_MANIFEST
    if not runtime.is_file() or not manifest_path.is_file() or not PINNED_MODEL.is_dir():
        raise PreflightError("pinned vLLM runtime, manifest, or model snapshot is missing")
    manifest = load_json(manifest_path)
    source = manifest.get("source", {}) if isinstance(manifest, dict) else {}
    distribution = manifest.get("distribution", {}) if isinstance(manifest, dict) else {}
    wheel = Path("/home/comp/zhanzhao/Mooncake") / str(distribution.get("wheel_relative_path", ""))
    expected = {
        "build_status": (manifest.get("build_status"), "PASS"),
        "static_cuda_audit_status": (manifest.get("static_cuda_audit_status"), "PASS"),
        "commit": (source.get("commit"), PINNED_VLLM_COMMIT),
        "tracked_source_modified": (source.get("tracked_source_modified"), False),
        "version": (distribution.get("version"), PINNED_VLLM_VERSION),
        "wheel_manifest_sha256": (
            distribution.get("wheel_sha256"),
            PINNED_VLLM_WHEEL_SHA256,
        ),
    }
    mismatches = {
        key: {"observed": observed, "expected": wanted}
        for key, (observed, wanted) in expected.items()
        if observed != wanted
    }
    if not wheel.is_file() or wheel.is_symlink() or sha256_file(wheel) != PINNED_VLLM_WHEEL_SHA256:
        mismatches["wheel_file"] = {"observed": str(wheel), "expected": "pinned hash"}

    vllm_root = runtime.parent.parent / "lib/python3.12/site-packages/vllm"
    policy_sources = [
        vllm_root / "config/kv_transfer.py",
        vllm_root / "distributed/kv_transfer/kv_connector/factory.py",
    ]
    store_root = vllm_root / "distributed/kv_transfer/kv_connector/v1/mooncake/store"
    policy_sources.extend(sorted(store_root.glob("*.py")))
    policy_hashes: dict[str, str] = {}
    aegis_hits: list[str] = []
    for path in policy_sources:
        if not path.is_file() or path.is_symlink():
            mismatches[str(path)] = {"observed": "missing/unsafe", "expected": "regular file"}
            continue
        content = path.read_text(encoding="utf-8")
        if "aegis" in content.lower():
            aegis_hits.append(str(path))
        policy_hashes[str(path.relative_to(vllm_root))] = sha256_file(path)
    if aegis_hits:
        mismatches["active_policy_aegis_hits"] = {"observed": aegis_hits, "expected": []}
    if mismatches:
        raise PreflightError(f"pinned vLLM baseline mismatch: {mismatches}")
    return {
        "runtime": str(runtime),
        "runtime_resolved": str(runtime.resolve()),
        "runtime_sha256": sha256_file(runtime.resolve()),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "commit": source["commit"],
        "version": distribution["version"],
        "wheel": str(wheel.resolve()),
        "wheel_sha256": sha256_file(wheel),
        "model": str(PINNED_MODEL),
        "model_revision": PINNED_MODEL_REVISION,
        "active_policy_source_sha256": policy_hashes,
        "aegis_policy_enabled": False,
        "version_aegis_substring_is_build_marker_only": True,
        "physical_runtime_validation_still_required": True,
    }


def _parse_job_states(snapshot: str, *, source: str) -> dict[int, str]:
    observed: dict[int, str] = {}
    for line in snapshot.splitlines():
        fields = line.split("|")
        if (
            len(fields) < 2
            or not fields[0].isdigit()
            or not re.fullmatch(r"[A-Z][A-Z_]*(?:\+| by [0-9]+)?", fields[1])
        ):
            raise PreflightError(f"malformed {source} job row: {line!r}")
        job_id = int(fields[0])
        if job_id in observed:
            raise PreflightError(f"duplicate {source} job row: {job_id}")
        observed[job_id] = fields[1]
    return observed


def validate_protected_jobs(
    queue_snapshot: str,
    accounting_snapshot: str,
) -> dict[str, Any]:
    """Validate two distinct, read-only scheduler observation contracts.

    The four held jobs are a hard ``squeue=PENDING`` gate.  The two short-lived
    monitored jobs may naturally leave ``squeue``; an exact root-job ``sacct``
    row is therefore mandatory for each of them.  Callers intentionally do not
    compare pre/post states.
    """

    queue = _parse_job_states(queue_snapshot, source="squeue")
    accounting = _parse_job_states(accounting_snapshot, source="sacct")
    unexpected_queue = sorted(set(queue) - set(PROTECTED_JOBS))
    unexpected_accounting = sorted(set(accounting) - set(READ_ONLY_MONITORED_JOBS))
    missing = sorted(set(HELD_PENDING_JOBS) - set(queue))
    non_pending = {
        job: queue[job]
        for job in HELD_PENDING_JOBS
        if job in queue and queue[job] != "PENDING"
    }
    missing_accounting = sorted(set(READ_ONLY_MONITORED_JOBS) - set(accounting))
    if missing or non_pending or missing_accounting or unexpected_queue or unexpected_accounting:
        raise PreflightError(
            "protected-job observation failed: "
            f"missing_held_squeue={missing}, non_pending_held={non_pending}, "
            f"missing_monitored_sacct={missing_accounting}, "
            f"unexpected_squeue={unexpected_queue}, "
            f"unexpected_sacct={unexpected_accounting}"
        )
    return {
        "held_pending": {
            str(job): {"squeue_state": queue[job]} for job in HELD_PENDING_JOBS
        },
        "read_only_monitored": {
            str(job): {
                "squeue_state": queue.get(job),
                "sacct_state": accounting[job],
            }
            for job in READ_ONLY_MONITORED_JOBS
        },
        "pre_post_state_equality_required": False,
        "scheduler_mutation_performed": False,
    }


def validate_gpu10_node(node_text: str, queue_text: str) -> dict[str, Any]:
    state_match = re.search(r"\bState=([^ ]+)", node_text)
    free_memory_match = re.search(r"\bFreeMem=(\d+)", node_text)
    if state_match is None or free_memory_match is None:
        raise PreflightError("cannot parse gpu10 State/FreeMem")
    state = state_match.group(1).split("+")[0]
    free_memory_mib = int(free_memory_match.group(1))
    if state != "IDLE":
        raise PreflightError(f"gpu10 is not IDLE: {state}")
    if free_memory_mib < 160 * 1024:
        raise PreflightError(f"gpu10 FreeMem is below requested 160G: {free_memory_mib} MiB")
    if not (
        "Gres=gpu:rtx4090:2" in node_text
        or "gres/gpu:rtx4090=2" in node_text
        or "gres/gpu=2" in node_text
    ):
        raise PreflightError("gpu10 does not advertise two RTX4090 GPUs")
    active_rows = [
        line for line in queue_text.splitlines() if line.split("|", 2)[1] not in {"PENDING"}
    ]
    if active_rows:
        raise PreflightError(f"gpu10 has active Slurm jobs: {active_rows}")
    return {
        "state": state,
        "free_memory_mib": free_memory_mib,
        "active_job_rows": active_rows,
        "in_job_foreign_gpu_process_gate_still_required": True,
    }


def atomic_write_json(path: Path, value: object) -> None:
    requested = path.absolute()
    if requested.exists() or requested.is_symlink():
        raise PreflightError(f"refusing to overwrite preflight record: {requested}")
    if (
        not requested.parent.is_dir()
        or requested.parent.is_symlink()
        or requested.parent.resolve() != requested.parent
    ):
        raise PreflightError("preflight output parent must be a safe existing directory")
    staging = requested.parent / f".{requested.name}.staging.{os.getpid()}"
    if staging.exists() or staging.is_symlink():
        raise PreflightError(f"preflight staging path already exists: {staging}")
    payload = canonical_json(value).encode("utf-8")
    with staging.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staging, requested)


def audit(args: argparse.Namespace) -> dict[str, Any]:
    requested_repo_root = args.repository_root.absolute()
    repo_root = requested_repo_root.resolve()
    if (
        repo_root != EXPECTED_REPOSITORY_ROOT.resolve()
        or requested_repo_root.is_symlink()
        or requested_repo_root != repo_root
    ):
        raise PreflightError(f"unexpected repository root: {repo_root}")
    if any("AEGIS" in key.upper() for key in os.environ):
        raise PreflightError("Aegis policy environment key is present")

    sbatch_path = (repo_root / args.sbatch).resolve()
    harness_path = (repo_root / args.harness).resolve()
    schema_path = (repo_root / args.result_schema).resolve()
    preflight_path = Path(__file__).resolve()
    for path in (sbatch_path, harness_path, schema_path, preflight_path):
        if not path.is_file() or path.is_symlink() or repo_root not in path.parents:
            raise PreflightError(f"missing, symlinked, or out-of-repo source input: {path}")
    sbatch_text = sbatch_path.read_text(encoding="utf-8")
    directives = parse_sbatch_directives(sbatch_text)
    forbidden = re.findall(
        r"\b(?:scancel|scontrol\s+(?:update|requeue|release|hold)|squeue\s+--start)\b",
        sbatch_text,
        flags=re.IGNORECASE,
    )
    if forbidden:
        raise PreflightError(f"batch source contains a scheduler mutation: {forbidden}")

    requested_clean_build = args.clean_build.absolute()
    if (
        requested_clean_build.is_symlink()
        or requested_clean_build != requested_clean_build.resolve()
    ):
        raise PreflightError(f"clean build path traverses a symlink: {requested_clean_build}")
    clean_build = verify_clean_build(requested_clean_build)
    vllm = verify_vllm_bundle()
    protected_command = [
        "squeue",
        "-h",
        "-j",
        ",".join(str(job) for job in PROTECTED_JOBS),
        "-o",
        "%i|%T|%P|%j|%u|%N|%b|%C|%M|%l|%R",
    ]
    protected = run_capture(protected_command)
    monitored_accounting_command = [
        "sacct",
        "-X",
        "-n",
        "-P",
        "-j",
        ",".join(str(job) for job in READ_ONLY_MONITORED_JOBS),
        "-o",
        "JobIDRaw,State%64,Partition,JobName,NodeList,Elapsed,Start,End,ExitCode",
    ]
    monitored_accounting = run_capture(monitored_accounting_command)
    protected_states = validate_protected_jobs(
        protected["stdout"], monitored_accounting["stdout"]
    )
    node = run_capture(["scontrol", "show", "node", "gpu10", "-o"])
    gpu10_queue = run_capture(["squeue", "-h", "-w", "gpu10", "-o", "%i|%T|%P|%j|%u|%N|%b|%R"])
    gpu10_gate = validate_gpu10_node(node["stdout"], gpu10_queue["stdout"])
    sinfo = run_capture(["sinfo", "-N", "-n", "gpu10", "-o", "%N|%P|%t|%G|%c|%m|%e|%C|%E"])
    test_only = run_capture(["sbatch", "--test-only", str(sbatch_path)])

    return {
        "schema": SCHEMA,
        "status": "READY_TO_SUBMIT",
        "submission_allowed": True,
        "physical_evidence_created": False,
        "evidence_level": "NONE",
        "observed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "observed_unix": time.time(),
        "user": os.environ.get("USER", ""),
        "host": os.uname().nodename,
        "working_directory": str(Path.cwd().resolve()),
        "intended_submission": {
            "command": ["sbatch", str(args.sbatch)],
            "submit_directory": str(repo_root),
            "submitted": False,
            "test_only": test_only,
        },
        "inputs": {
            "sbatch": {"path": str(sbatch_path), "sha256": sha256_file(sbatch_path)},
            "harness": {"path": str(harness_path), "sha256": sha256_file(harness_path)},
            "result_schema": {"path": str(schema_path), "sha256": sha256_file(schema_path)},
            "preflight": {
                "path": str(preflight_path),
                "sha256": sha256_file(preflight_path),
            },
            "sbatch_directives": directives,
        },
        "clean_build": clean_build,
        "pinned_vllm": vllm,
        "slurm": {
            "protected_job_states": protected_states,
            "protected_jobs_query": protected,
            "monitored_jobs_accounting_query": monitored_accounting,
            "gpu10_gate": gpu10_gate,
            "gpu10_queue_query": gpu10_queue,
            "gpu10_node_query": node,
            "gpu10_sinfo_query": sinfo,
            "no_job_mutation_performed": True,
        },
        "remaining_in_job_gates": [
            "allocated node is exactly gpu10",
            "two assigned GPUs resolve to distinct RTX4090 UUIDs",
            "no compute process exists on either assigned GPU before model load",
            "held protected jobs remain PENDING; monitored jobs are read-only observations",
            "clean wheel resolves before the dirty Mooncake distribution",
        ],
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--repository-root", type=Path, default=EXPECTED_REPOSITORY_ROOT)
    value.add_argument(
        "--sbatch", type=Path, default=Path("scripts/physical/run_vanilla_mooncake_e4.sbatch")
    )
    value.add_argument(
        "--harness", type=Path, default=Path("scripts/physical/vanilla_mooncake_e4.py")
    )
    value.add_argument(
        "--result-schema",
        type=Path,
        default=Path("benchmark/physical/vanilla-mooncake-e4/result.schema.json"),
    )
    value.add_argument("--clean-build", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        record = audit(args)
    except Exception as error:
        record = {
            "schema": SCHEMA,
            "status": "FAIL",
            "submission_allowed": False,
            "physical_evidence_created": False,
            "evidence_level": "NONE",
            "observed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "error_type": type(error).__name__,
            "error": str(error),
        }
        exit_code = 2
    else:
        exit_code = 0
    try:
        atomic_write_json(args.output, record)
    except Exception as publication_error:
        print(f"MOONKVSIM_PREFLIGHT_PUBLICATION_ERROR={publication_error}", file=sys.stderr)
        return 3
    print(canonical_json(record), end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
