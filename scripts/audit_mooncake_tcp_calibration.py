#!/usr/bin/env python3
"""Audit the minimal imported Mooncake TCP Store calibration bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

BUNDLE_RELATIVE_PATH = Path("benchmark/physical/mooncake-tcp-store/66924-20260803-140423")
EXPECTED_SCHEMA = "moonkvsim.mooncake-tcp-store-calibration-bundle.v1"
EXPECTED_PROVENANCE_SCHEMA = "moonkvsim.mooncake-tcp-store-calibration-provenance.v1"
EXPECTED_EVENT_SHA256 = "72b5dd08dcb69a9521cca71cdd4bb8460668b383db2ee7607550f3315de140e5"
EXPECTED_EVENTS: list[dict[str, object]] = [
    {
        "bytes": 141557760,
        "dp_rank": 0,
        "duration_us": 219110.026,
        "effective_gbps": 0.6460578850919401,
        "objects": 30,
        "operation": "prefetch",
        "pid": 2069211,
        "source": "hicache_io_profiler",
        "status": "ok",
        "tid": "Thread-10 (prefetch_io_aux_func)",
        "timestamp_us": 1785737726151616.8,
        "trace_file": "hicache-io-2069211.jsonl",
    },
    {
        "bytes": 150994944,
        "dp_rank": 1,
        "duration_us": 134680.905,
        "effective_gbps": 1.1211310467508366,
        "objects": 32,
        "operation": "backup",
        "pid": 2069212,
        "source": "hicache_io_profiler",
        "status": "ok",
        "tid": "Thread-5 (backup_thread_func)",
        "timestamp_us": 1785737699577125.5,
        "trace_file": "hicache-io-2069212.jsonl",
    },
    {
        "bytes": 141557760,
        "dp_rank": 1,
        "duration_us": 161515.801,
        "effective_gbps": 0.8764328884453849,
        "objects": 30,
        "operation": "prefetch",
        "pid": 2069212,
        "source": "hicache_io_profiler",
        "status": "ok",
        "tid": "Thread-13 (prefetch_io_aux_func)",
        "timestamp_us": 1785737754250955.0,
        "trace_file": "hicache-io-2069212.jsonl",
    },
]
EXPECTED_FILES = {
    "README.md",
    "SHA256SUMS",
    "l3_io_events.jsonl",
    "manifest.json",
    "provenance.json",
    "provenance/mooncake-working-tree.patch",
    "provenance/sglang-working-tree.patch",
    "raw/hicache-io-2069211.jsonl",
    "raw/hicache-io-2069212.jsonl",
}
MANIFEST_ARTIFACTS = EXPECTED_FILES - {"SHA256SUMS", "manifest.json"}
CHECKSUM_ARTIFACTS = EXPECTED_FILES - {"SHA256SUMS"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class AuditError(RuntimeError):
    """Raised when the imported evidence or its declared boundary drifts."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _load_canonical_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot read canonical JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise AuditError(f"{path}: expected a JSON object")
    if raw != _canonical_json_bytes(value):
        raise AuditError(f"{path}: JSON is not canonical sorted two-space form")
    return value


def _mapping(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuditError(f"{location}: expected object")
    return value


def _list(value: object, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise AuditError(f"{location}: expected array")
    return value


def _safe_relative_path(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuditError(f"{location}: expected non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise AuditError(f"{location}: unsafe path")
    return value


def _inventory(bundle: Path) -> set[str]:
    if bundle.is_symlink() or not bundle.is_dir():
        raise AuditError(f"bundle must be a real directory: {bundle}")
    paths: set[str] = set()
    for path in bundle.rglob("*"):
        if path.is_symlink():
            raise AuditError(f"symlink forbidden in evidence bundle: {path}")
        if path.is_file():
            paths.add(path.relative_to(bundle).as_posix())
    if paths != EXPECTED_FILES:
        raise AuditError(
            f"bundle inventory drift: expected {sorted(EXPECTED_FILES)}, got {sorted(paths)}"
        )
    return paths


def _parse_sha256sums(bundle: Path) -> dict[str, str]:
    path = bundle / "SHA256SUMS"
    lines = path.read_text(encoding="utf-8").splitlines()
    records: dict[str, str] = {}
    declared_order: list[str] = []
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
        if match is None:
            raise AuditError(f"invalid SHA256SUMS entry: {line!r}")
        digest, raw_path = match.groups()
        relative = _safe_relative_path(raw_path, "SHA256SUMS path")
        if relative in records:
            raise AuditError(f"duplicate SHA256SUMS path: {relative}")
        records[relative] = digest
        declared_order.append(relative)
    if declared_order != sorted(declared_order):
        raise AuditError("SHA256SUMS paths must be lexically sorted")
    if set(records) != CHECKSUM_ARTIFACTS:
        raise AuditError("SHA256SUMS does not cover the exact non-self file set")
    for relative, expected in records.items():
        if _sha256(bundle / relative) != expected:
            raise AuditError(f"checksum mismatch: {relative}")
    return records


def _audit_manifest(bundle: Path, checksums: Mapping[str, str]) -> dict[str, Any]:
    manifest = _load_canonical_json(bundle / "manifest.json")
    if manifest.get("schema") != EXPECTED_SCHEMA:
        raise AuditError("manifest schema drift")
    if manifest.get("run_id") != "66924-20260803-140423":
        raise AuditError("manifest run identity drift")
    records: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_list(manifest.get("artifacts"), "manifest.artifacts")):
        record = _mapping(raw, f"manifest.artifacts[{index}]")
        relative = _safe_relative_path(record.get("path"), "manifest artifact path")
        if relative in records:
            raise AuditError(f"duplicate manifest artifact: {relative}")
        records[relative] = record
    if set(records) != MANIFEST_ARTIFACTS:
        raise AuditError("manifest artifact inventory drift")
    for relative, record in records.items():
        path = bundle / relative
        if record.get("sha256") != checksums[relative]:
            raise AuditError(f"manifest/checksum disagreement: {relative}")
        if record.get("size_bytes") != path.stat().st_size:
            raise AuditError(f"manifest size disagreement: {relative}")
    evidence = _mapping(manifest.get("evidence"), "manifest.evidence")
    _audit_claim_boundary(evidence, "manifest.evidence")
    publication = _mapping(manifest.get("publication"), "manifest.publication")
    if publication != {
        "complete_minimal_bundle": True,
        "source_verification_available": True,
        "torch_traces_imported": False,
    }:
        raise AuditError("manifest publication boundary drift")
    excluded = _list(manifest.get("excluded_source_artifacts"), "excluded artifacts")
    excluded_paths = {_mapping(item, "excluded artifact").get("path") for item in excluded}
    if excluded_paths != {
        "torch_profiles/aegiskv-mooncake-TP-0-DP-0.trace.json.gz",
        "torch_profiles/aegiskv-mooncake-TP-0-DP-1.trace.json.gz",
    }:
        raise AuditError("torch-trace exclusion inventory drift")
    return manifest


def _audit_claim_boundary(boundary: Mapping[str, Any], location: str) -> None:
    if boundary.get("evidence_ceiling") != ("preliminary_physical_calibration_input_below_E3"):
        raise AuditError(f"{location}: evidence ceiling drift")
    if boundary.get("formal_use_allowed") is not False:
        raise AuditError(f"{location}: formal use must remain forbidden")
    if boundary.get("gates_cleared") != []:
        raise AuditError(f"{location}: imported observations may clear no gates")
    required = boundary.get("required_open_gates")
    if required != [
        "GAP-003",
        "target E3 transfer and Store calibration",
        "E4 matched end-to-end validation",
        "E5 paper evidence",
    ]:
        raise AuditError(f"{location}: required open-gate set drift")


def _audit_events(bundle: Path, provenance: Mapping[str, Any]) -> None:
    event_path = bundle / "l3_io_events.jsonl"
    if _sha256(event_path) != EXPECTED_EVENT_SHA256:
        raise AuditError("raw event bytes drifted from source")
    events: list[dict[str, object]] = []
    for line_number, line in enumerate(
        event_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise AuditError(f"event line {line_number}: {error}") from error
        if not isinstance(value, dict):
            raise AuditError(f"event line {line_number}: expected object")
        events.append(value)
    if events != EXPECTED_EVENTS:
        raise AuditError("the three original event values or order changed")
    raw_events: list[dict[str, object]] = []
    for relative in ("raw/hicache-io-2069211.jsonl", "raw/hicache-io-2069212.jsonl"):
        raw_events.extend(
            json.loads(line)
            for line in (bundle / relative).read_text(encoding="utf-8").splitlines()
        )
    if raw_events != [
        {
            "bytes": 141557760,
            "duration_us": 219110.026,
            "end_unix_ns": 1785737726372954750,
            "objects": 30,
            "operation": "prefetch",
            "pid": 2069211,
            "start_unix_ns": 1785737726151616724,
            "status": "ok",
            "thread": "Thread-10 (prefetch_io_aux_func)",
        },
        {
            "bytes": 150994944,
            "duration_us": 134680.905,
            "end_unix_ns": 1785737699713420477,
            "objects": 32,
            "operation": "backup",
            "pid": 2069212,
            "start_unix_ns": 1785737699577125530,
            "status": "ok",
            "thread": "Thread-5 (backup_thread_func)",
        },
        {
            "bytes": 141557760,
            "duration_us": 161515.801,
            "end_unix_ns": 1785737754421154849,
            "objects": 30,
            "operation": "prefetch",
            "pid": 2069212,
            "start_unix_ns": 1785737754250955077,
            "status": "ok",
            "thread": "Thread-13 (prefetch_io_aux_func)",
        },
    ]:
        raise AuditError("the three byte-identical original profiler events changed")
    for index, event in enumerate(events):
        computed = float(event["bytes"]) / float(event["duration_us"]) / 1000.0
        if not math.isclose(computed, float(event["effective_gbps"]), rel_tol=1e-15, abs_tol=0.0):
            raise AuditError(f"event {index}: effective decimal GB/s disagrees")
    measurements = _mapping(provenance.get("measurements"), "provenance.measurements")
    if measurements.get("event_count") != 3:
        raise AuditError("provenance event count drift")
    operations = _mapping(measurements.get("operations"), "measurements.operations")
    if operations != {
        "backup": {
            "dp_ranks": [1],
            "effective_GB_per_s_decimal": 1.1211310467508366,
            "event_count": 1,
            "total_bytes": 150994944,
            "total_duration_us": 134680.905,
        },
        "prefetch": {
            "dp_ranks": [0, 1],
            "effective_GB_per_s_decimal": 0.7438158420080095,
            "event_count": 2,
            "total_bytes": 283115520,
            "total_duration_us": 380625.82700000005,
        },
    }:
        raise AuditError("operation summary drift")
    raw_provenance = _mapping(measurements.get("raw_events"), "measurements.raw_events")
    original_files = _list(raw_provenance.get("original_files"), "raw original files")
    if [item.get("path") for item in original_files if isinstance(item, dict)] != [
        "raw/hicache-io-2069211.jsonl",
        "raw/hicache-io-2069212.jsonl",
    ]:
        raise AuditError("raw original-file provenance drift")


def _audit_provenance(bundle: Path) -> dict[str, Any]:
    provenance = _load_canonical_json(bundle / "provenance.json")
    if provenance.get("schema") != EXPECTED_PROVENANCE_SCHEMA:
        raise AuditError("provenance schema drift")
    boundary = _mapping(provenance.get("claim_boundary"), "claim_boundary")
    _audit_claim_boundary(boundary, "provenance.claim_boundary")
    forbidden = set(_list(boundary.get("terms_forbidden_as_measurement_claims"), "terms"))
    if forbidden != {
        "hardware peak bandwidth",
        "network link bandwidth",
        "raw DRAM bandwidth",
        "SSD bandwidth",
        "disk bandwidth",
        "isolated Transfer Engine bandwidth",
    }:
        raise AuditError("forbidden measurement-claim vocabulary drift")
    deployment = _mapping(provenance.get("deployment"), "deployment")
    mismatch = _mapping(deployment.get("target_mismatch"), "target_mismatch")
    if mismatch != {
        "hardware_match": False,
        "runtime_match": False,
        "source_hardware": "2x NVIDIA GeForce RTX 4090",
        "source_runtime": "SGLang 0.5.16 DP=2",
        "target_hardware": "NVIDIA L40S",
        "target_runtime": "vLLM 1.2.2",
    }:
        raise AuditError("source/target mismatch boundary drift")
    mooncake = _mapping(deployment.get("mooncake"), "deployment.mooncake")
    if mooncake.get("transport") != "tcp" or mooncake.get("same_host") is not True:
        raise AuditError("same-host TCP deployment boundary drift")
    parallelism = _mapping(deployment.get("parallelism"), "parallelism")
    if parallelism != {"dp_size": 2, "pp_size": 1, "tp_size": 1}:
        raise AuditError("parallelism drift")
    import_audit = _mapping(
        _mapping(provenance.get("capture"), "capture").get("import_audit"),
        "capture.import_audit",
    )
    if import_audit.get("external_sglang_porcelain") != ["?? benchmark/aegiskv_mooncake/"]:
        raise AuditError("untracked external source-subtree declaration drift")
    _audit_events(bundle, provenance)
    sglang_patch = (bundle / "provenance/sglang-working-tree.patch").read_text(encoding="utf-8")
    for marker in (
        'with _profile_mooncake_io("backup", len(key_strs), buffer_sizes):',
        'with _profile_mooncake_io("prefetch", len(key_strs), buffer_sizes):',
        "start_ns = time.perf_counter_ns()",
        "end_ns = time.perf_counter_ns()",
    ):
        if marker not in sglang_patch:
            raise AuditError(f"instrumentation boundary missing: {marker}")
    return provenance


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AuditError(f"git {' '.join(args)} failed in {repository}: {completed.stderr.strip()}")
    return completed.stdout


def _command_value(argv: list[str], flag: str) -> str:
    try:
        index = argv.index(flag)
        return argv[index + 1]
    except (ValueError, IndexError) as error:
        raise AuditError(f"source server command lacks {flag}") from error


def _verify_source(provenance: Mapping[str, Any], bundle: Path) -> None:
    capture = _mapping(provenance.get("capture"), "capture")
    source = Path(str(capture.get("source_result_directory")))
    if source.is_symlink() or not source.is_dir():
        raise AuditError(f"source result directory unavailable: {source}")
    artifacts = _mapping(capture.get("source_artifacts"), "capture.source_artifacts")
    for relative, raw_record in artifacts.items():
        safe = _safe_relative_path(relative, "source artifact path")
        record = _mapping(raw_record, f"source artifact {safe}")
        path = source / safe
        if path.is_symlink() or not path.is_file():
            raise AuditError(f"source artifact unavailable or symlinked: {safe}")
        if path.stat().st_size != record.get("size_bytes"):
            raise AuditError(f"source artifact size drift: {safe}")
        if _sha256(path) != record.get("sha256"):
            raise AuditError(f"source artifact hash drift: {safe}")
    if (source / "SUCCESS").read_bytes() != b"verified\n":
        raise AuditError("source SUCCESS marker drift")
    if (source / "l3_io_events.jsonl").read_bytes() != (bundle / "l3_io_events.jsonl").read_bytes():
        raise AuditError("imported event file is not byte-identical to live source")
    for pid in (2069211, 2069212):
        imported = bundle / f"raw/hicache-io-{pid}.jsonl"
        original = source / f"torch_profiles/hicache-io-{pid}.jsonl"
        if imported.read_bytes() != original.read_bytes():
            raise AuditError(f"imported raw profiler event file drift: {pid}")
    repositories = _mapping(capture.get("repositories"), "capture.repositories")
    for name in ("sglang", "mooncake"):
        record = _mapping(repositories.get(name), f"repositories.{name}")
        repository = Path(str(record.get("repository")))
        commit = str(record.get("commit"))
        if _git(repository, "cat-file", "-t", commit).strip() != "commit":
            raise AuditError(f"{name} captured commit object is unavailable")
        status = (source / f"{name}-git-status.txt").read_text(encoding="utf-8")
        if status.splitlines() != record.get("recorded_status"):
            raise AuditError(f"{name} recorded dirty status drift")
        if (source / f"{name}-git-sha.txt").read_text(encoding="utf-8").strip() != commit:
            raise AuditError(f"{name} captured commit file drift")
    import_audit = _mapping(capture.get("import_audit"), "capture.import_audit")
    sglang_repo = Path(str(_mapping(repositories["sglang"], "sglang")["repository"]))
    if _git(sglang_repo, "rev-parse", "HEAD").strip() != import_audit.get("external_sglang_head"):
        raise AuditError("live external SGLang HEAD drifted since import audit")
    branch = _git(sglang_repo, "branch", "--show-current").strip()
    if branch != import_audit.get("external_sglang_branch"):
        raise AuditError("live external SGLang branch drifted since import audit")
    scoped_status = _git(
        sglang_repo, "status", "--porcelain=v1", "--", "benchmark/aegiskv_mooncake"
    ).splitlines()
    if scoped_status != import_audit.get("external_sglang_porcelain"):
        raise AuditError("live external source subtree is no longer entirely untracked")
    server_command = (source / "server-command.txt").read_text(encoding="utf-8")
    if server_command != (source / "server-launch-command.txt").read_text(encoding="utf-8"):
        raise AuditError("server command copies disagree")
    argv = shlex.split(server_command)
    expected_values = {
        "--dp-size": "2",
        "--dtype": "bfloat16",
        "--hicache-mem-layout": "page_first",
        "--hicache-size": "4",
        "--hicache-storage-backend": "mooncake",
        "--hicache-storage-prefetch-policy": "wait_complete",
        "--hicache-write-policy": "write_through",
        "--page-size": "64",
        "--tp-size": "1",
    }
    for flag, expected in expected_values.items():
        if _command_value(argv, flag) != expected:
            raise AuditError(f"source server command drift for {flag}")
    if "--enable-hierarchical-cache" not in argv:
        raise AuditError("source server command lacks hierarchical cache")
    server_info = json.loads((source / "server_info.json").read_text(encoding="utf-8"))
    if not isinstance(server_info, dict) or server_info.get("status") != "ready":
        raise AuditError("source server_info is not ready")
    if (
        server_info.get("version") != "0.5.16"
        or server_info.get("dp_size") != 2
        or server_info.get("hicache_storage_backend") != "mooncake"
    ):
        raise AuditError("source server_info deployment drift")
    calibration = json.loads((source / "aegiskv_calibration.json").read_text(encoding="utf-8"))
    verification = _mapping(
        _mapping(calibration, "source calibration").get("verification"),
        "source calibration.verification",
    )
    if verification.get("passed") is not True or verification.get("profiler_prefetch_dp_ranks") != [
        0,
        1,
    ]:
        raise AuditError("source calibration verification drift")
    nvidia_before = (source / "nvidia-smi-before.txt").read_text(encoding="utf-8")
    gpu_inventory = _mapping(
        _mapping(provenance.get("deployment"), "deployment").get("gpu_inventory"),
        "gpu_inventory",
    )
    for raw_device in _list(gpu_inventory.get("devices"), "gpu_inventory.devices"):
        device = _mapping(raw_device, "gpu device")
        for value in (device.get("name"), device.get("uuid"), device.get("bus_id")):
            if not isinstance(value, str) or value not in nvidia_before:
                raise AuditError(f"GPU inventory value absent from source nvidia-smi: {value}")
    server_log = (source / "sglang-server.log").read_text(encoding="utf-8")
    for marker in (
        "Using default malloc/free for protocol: tcp",
        "TCP-only environment, memcpy enabled",
        "Creating storage backend 'mooncake'",
        "Mooncake store setup successfully.",
    ):
        if marker not in server_log:
            raise AuditError(f"same-host TCP source marker missing: {marker}")
    metadata_log = (source / "mooncake-metadata.log").read_text(encoding="utf-8")
    if "gpu12" not in metadata_log or "192.168.0.12" not in metadata_log:
        raise AuditError("same-host Mooncake endpoint evidence missing")
    master_log = (source / "mooncake-master.log").read_text(encoding="utf-8")
    for marker in (
        "rpc protocol=tcp",
        "Mem Storage: 144.01 MB / 8.00 GB",
        "SSD Storage: 0 B / 0 B",
    ):
        if marker not in master_log:
            raise AuditError(f"Mooncake Store source marker missing: {marker}")


def audit_bundle(bundle: Path, *, verify_source: bool = False) -> dict[str, object]:
    """Fail closed on any bundle, numeric, provenance, or optional source drift."""

    bundle = bundle.resolve()
    _inventory(bundle)
    checksums = _parse_sha256sums(bundle)
    manifest = _audit_manifest(bundle, checksums)
    provenance = _audit_provenance(bundle)
    if verify_source:
        _verify_source(provenance, bundle)
    return {
        "bundle": str(bundle),
        "event_count": 3,
        "evidence_ceiling": _mapping(manifest["evidence"], "evidence")["evidence_ceiling"],
        "manifest_sha256": _sha256(bundle / "manifest.json"),
        "source_verified": verify_source,
        "status": "PASS",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--bundle", type=Path, default=BUNDLE_RELATIVE_PATH)
    parser.add_argument("--verify-source", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.repository_root.resolve()
    bundle = args.bundle if args.bundle.is_absolute() else root / args.bundle
    try:
        report = audit_bundle(bundle, verify_source=args.verify_source)
    except (AuditError, OSError, TypeError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
