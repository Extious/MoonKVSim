#!/usr/bin/env python3
"""Pinned Vanilla vLLM + clean Mooncake cross-instance E4 harness.

Two independent TP=1 vLLM servers run on the two RTX 4090 devices assigned by
Slurm.  Both use the upstream ``MooncakeStoreConnector`` in ``kv_both`` mode
and contribute only embedded DRAM segments over TCP.  Each matched round runs
an equal-length cold prompt on server B, primes a different prompt on server A,
then reuses that prompt for the first time on server B.

The result is accepted only when Mooncake's successful Store PUT, lookup, and
GET counters, transferred bytes, and vLLM's externally cached-token reduction
all agree.  Request spans report queue, prefill/forward residual, KV RPC I/O,
engine E2E, and client E2E.  The spans are not asserted to be additive because
lookup and asynchronous Store work can overlap other request phases.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, TextIO

SCHEMA: Final = "moonkvsim.vanilla_mooncake_e4.v1"
PINNED_MOONCAKE_COMMIT: Final = "f161118c18dbea1b56dd5c7908b9eaa440353e2e"
PINNED_VLLM_COMMIT: Final = "644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504"
PINNED_VLLM_VERSION: Final = "1.2.2+aegiskv.sm89"
PINNED_VLLM_WHEEL_SHA256: Final = "3db1279f72293195d6a1a5ef97f48cd72bedac6dfb10237c9b790ae8650491b2"
PINNED_MODEL_REVISION: Final = "b968826d9c46dd6066d109eabc6255188de91218"
PINNED_MODEL: Final = Path(
    "/home/comp/zhanzhao/.cache/huggingface/hub/"
    "models--Qwen--Qwen3-8B/snapshots/"
    f"{PINNED_MODEL_REVISION}"
)
PINNED_RUNTIME: Final = Path("/home/comp/zhanzhao/Mooncake/aegiskv/.venv-vllm-sm89/bin/python")
PINNED_VLLM_BUILD_MANIFEST: Final = Path(
    "/home/comp/zhanzhao/Mooncake/aegiskv/paper/fallback_4090/runtime-build-manifest.json"
)
HELD_PENDING_JOBS: Final = (136567, 135889, 135847, 135326)
READ_ONLY_MONITORED_JOBS: Final = (142290, 142291)
PROTECTED_JOBS: Final = HELD_PENDING_JOBS + READ_ONLY_MONITORED_JOBS
PROMETHEUS_LINE: Final = re.compile(
    r"^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)(?:\{(?P<labels>.*)\})?\s+"
    r"(?P<value>[-+0-9.eE]+)$"
)
LABEL: Final = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:\\.|[^"\\])*)"')
HEX64: Final = re.compile(r"^[0-9a-f]{64}$")


class E4Error(RuntimeError):
    """A fail-closed physical preflight, launch, request, or evidence error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def write_json(path: Path, value: object) -> None:
    path.write_text(canonical_json(value), encoding="utf-8")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise E4Error(f"cannot load JSON {path}: {error}") from error


def validate_store_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Enforce the Vanilla E4 TCP, embedded-DRAM-only storage contract."""

    expected = {
        "protocol": "tcp",
        "device_name": "",
        "mode": "embedded",
        "enable_offload": False,
    }
    mismatches = [
        f"{key}={config.get(key)!r}, expected={value!r}"
        for key, value in expected.items()
        if config.get(key) != value
    ]
    global_size = config.get("global_segment_size")
    local_size = config.get("local_buffer_size")
    if type(global_size) is not int or global_size <= 0:
        mismatches.append("global_segment_size must be a positive integer")
    if type(local_size) is not int or local_size <= 0:
        mismatches.append("local_buffer_size must be a positive integer")
    for required in ("metadata_server", "master_server_address"):
        if not isinstance(config.get(required), str) or not config[required]:
            mismatches.append(f"{required} must be a non-empty string")

    forbidden_markers = ("ssd", "nvme", "nvmf", "storage_path", "file_storage")
    forbidden = sorted(
        key for key in config if any(marker in key.lower() for marker in forbidden_markers)
    )
    if forbidden:
        mismatches.append(f"forbidden persistent-tier keys: {forbidden}")
    if mismatches:
        raise E4Error("invalid Vanilla Store config: " + "; ".join(mismatches))
    return dict(config)


def parse_csv_rows(text: str) -> list[list[str]]:
    return [
        [cell.strip() for cell in row]
        for row in csv.reader(text.splitlines())
        if row and not row[0].strip().lower().startswith("no running")
    ]


def assigned_gpu_uuids(
    gpu_rows: Sequence[Sequence[str]], visible: str
) -> tuple[list[str], list[dict[str, str]]]:
    records = [
        {
            "index": row[0],
            "uuid": row[1],
            "name": row[2],
            "pci_bus_id": row[3],
            "memory_total_mib": row[4],
            "memory_used_mib": row[5],
            "utilization_gpu_percent": row[6],
            "temperature_c": row[7],
            "pstate": row[8],
        }
        for row in gpu_rows
        if len(row) == 9
    ]
    if len(records) != len(gpu_rows):
        raise E4Error("unexpected nvidia-smi GPU CSV shape")
    tokens = [token.strip() for token in visible.split(",") if token.strip()]
    if len(tokens) != 2:
        raise E4Error(f"exactly two CUDA_VISIBLE_DEVICES entries required, got {visible!r}")
    resolved: list[str] = []
    for token in tokens:
        candidates = [
            row
            for row in records
            if token == row["index"]
            or token == row["uuid"]
            or row["uuid"].startswith(token)
            or row["uuid"].removeprefix("GPU-").startswith(token.removeprefix("GPU-"))
        ]
        if len(candidates) != 1:
            raise E4Error(f"cannot uniquely resolve assigned GPU token {token!r}")
        resolved.append(candidates[0]["uuid"])
    if len(set(resolved)) != 2:
        raise E4Error("CUDA_VISIBLE_DEVICES resolves to duplicate GPUs")
    selected = [row for row in records if row["uuid"] in resolved]
    non_4090 = [row for row in selected if "RTX 4090" not in row["name"]]
    if non_4090:
        raise E4Error(f"assigned GPUs are not both RTX4090 devices: {non_4090}")
    return resolved, records


def run_text(command: Sequence[str]) -> str:
    completed = subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise E4Error(
            f"command failed ({completed.returncode}): {' '.join(command)}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout


def collect_gpu_snapshot(visible: str) -> dict[str, Any]:
    gpu_text = run_text(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,pci.bus_id,memory.total,memory.used,"
            "utilization.gpu,temperature.gpu,pstate",
            "--format=csv,noheader,nounits",
        ]
    )
    process_text = run_text(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    assigned, gpus = assigned_gpu_uuids(parse_csv_rows(gpu_text), visible)
    processes = [
        {
            "gpu_uuid": row[0],
            "pid": row[1],
            "process_name": row[2],
            "used_memory_mib": row[3],
        }
        for row in parse_csv_rows(process_text)
        if len(row) == 4 and row[0] in assigned
    ]
    return {
        "observed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cuda_visible_devices": visible,
        "assigned_gpu_uuids": assigned,
        "gpus": [row for row in gpus if row["uuid"] in assigned],
        "compute_processes": processes,
        "process_gate": "PASS" if not processes else "FAIL_COMPUTE_PROCESSES_PRESENT",
        "raw_gpu_csv": gpu_text,
        "raw_process_csv": process_text,
    }


def validate_slurm(environment: Mapping[str, str]) -> dict[str, str]:
    job_id = environment.get("SLURM_JOB_ID", "")
    node = environment.get("SLURMD_NODENAME", environment.get("HOSTNAME", ""))
    partition = environment.get("SLURM_JOB_PARTITION", "")
    visible = environment.get("CUDA_VISIBLE_DEVICES", "")
    if not job_id.isdigit():
        raise E4Error("a numeric SLURM_JOB_ID is required")
    if node != "gpu10":
        raise E4Error(f"Vanilla E4 is pinned to gpu10, observed {node!r}")
    if partition not in {"debug", "long"}:
        raise E4Error(f"unexpected gpu10 partition {partition!r}")
    if environment.get("PYTHONHASHSEED") != "0":
        raise E4Error("PYTHONHASHSEED must equal 0")
    if len([item for item in visible.split(",") if item.strip()]) != 2:
        raise E4Error("two Slurm-assigned GPUs are required")
    return {
        "job_id": job_id,
        "node": node,
        "partition": partition,
        "cuda_visible_devices": visible,
        "job_gpus": environment.get("SLURM_JOB_GPUS", ""),
        "cpus_per_task": environment.get("SLURM_CPUS_PER_TASK", ""),
        "memory_per_node": environment.get("SLURM_MEM_PER_NODE", ""),
        "pythonhashseed": environment["PYTHONHASHSEED"],
    }


def validate_build_bundle(manifest_path: Path, wheel_path: Path, overlay: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("status") != "PASS":
        raise E4Error("clean Mooncake build manifest is not PASS")
    source = manifest.get("source", {})
    if source.get("commit") != PINNED_MOONCAKE_COMMIT:
        raise E4Error("clean Mooncake source commit mismatch")
    if source.get("dirty_worktree_files_copied") is not False:
        raise E4Error("clean build does not prove exclusion of dirty worktree files")
    build = manifest.get("build", {})
    if build.get("ssd_nvme_enabled") is not False:
        raise E4Error("clean build does not prove SSD/NVMe disabled")
    wheel = manifest.get("wheel", {})
    observed_sha = sha256_file(wheel_path)
    if wheel.get("sha256") != observed_sha or not HEX64.fullmatch(observed_sha):
        raise E4Error("clean Mooncake wheel SHA-256 mismatch")
    if "aegis" in wheel_path.name.lower():
        raise E4Error("clean Mooncake wheel filename contains Aegis marker")

    mooncake_spec = importlib.util.find_spec("mooncake")
    if mooncake_spec is None or mooncake_spec.origin is None:
        raise E4Error("mooncake package is missing from the clean overlay")
    origin = Path(mooncake_spec.origin).resolve()
    if overlay.resolve() not in origin.parents:
        raise E4Error(f"mooncake resolves outside clean overlay: {origin}")
    distribution = importlib.metadata.distribution("mooncake-transfer-engine")
    version = distribution.version
    if "aegis" in version.lower() or version != "0.3.12.post1":
        raise E4Error(f"unexpected clean Mooncake version {version!r}")
    distribution_root = Path(str(distribution.locate_file(""))).resolve()
    if (
        overlay.resolve() != distribution_root
        and overlay.resolve() not in distribution_root.parents
    ):
        raise E4Error(
            f"Mooncake distribution metadata resolves outside overlay: {distribution_root}"
        )
    return {
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "wheel_path": str(wheel_path.resolve()),
        "wheel_sha256": observed_sha,
        "package_origin": str(origin),
        "distribution_root": str(distribution_root),
        "version": version,
        "source_commit": source["commit"],
    }


def probe_clean_native_loader(
    runtime: Path,
    overlay: Path,
    manifest_path: Path,
    artifact_dir: Path,
) -> dict[str, Any]:
    """Import both native extensions and preserve the real dynamic-loader trace."""

    native_runtime = manifest_path.resolve().parent / "native-runtime"
    expected_ld_library_path = f"{native_runtime}:{native_runtime / 'libibverbs'}"
    if os.environ.get("LD_LIBRARY_PATH") != expected_ld_library_path:
        raise E4Error(
            "native loader path is not the exact frozen bundle: "
            f"{os.environ.get('LD_LIBRARY_PATH')!r}"
        )
    probe_path = artifact_dir / "native-import-probe.json"
    command = [
        str(runtime),
        "-c",
        (
            "import importlib,json,pathlib,sys; "
            "mods=[importlib.import_module('mooncake.engine'),"
            "importlib.import_module('mooncake.store')]; "
            "lines=pathlib.Path('/proc/self/maps').read_text().splitlines(); "
            "paths=sorted({line.split()[-1] for line in lines "
            "if len(line.split()) >= 6 and line.split()[-1].startswith('/')}); "
            "payload={'module_origins':{m.__name__:m.__file__ for m in mods},"
            "'mapped_paths':paths}; "
            "pathlib.Path(sys.argv[1]).open('x').write("
            "json.dumps(payload,sort_keys=True,separators=(',',':'))+'\\n')"
        ),
        str(probe_path),
    ]
    environment = dict(os.environ)
    environment["LD_DEBUG"] = "libs"
    completed = subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    (artifact_dir / "native-import-probe.stdout.log").write_text(
        completed.stdout, encoding="utf-8"
    )
    loader_log = artifact_dir / "native-import-probe.ld-debug.log"
    loader_log.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0 or not probe_path.is_file():
        raise E4Error(
            f"clean native import probe failed with code {completed.returncode}; "
            f"loader_log={loader_log}"
        )
    payload = load_json(probe_path)
    if not isinstance(payload, dict):
        raise E4Error("clean native import probe result is not an object")
    origins = payload.get("module_origins")
    mapped_paths = payload.get("mapped_paths")
    if not isinstance(origins, dict) or not isinstance(mapped_paths, list):
        raise E4Error("clean native import probe result is incomplete")
    overlay_root = overlay.resolve()
    for module_name in ("mooncake.engine", "mooncake.store"):
        origin = Path(str(origins.get(module_name, ""))).resolve()
        if overlay_root not in origin.parents:
            raise E4Error(f"{module_name} imported outside the clean overlay: {origin}")

    required_native_sonames = (
        "libcudart.so.12",
        "libcurl.so.4",
        "libgcc_s.so.1",
        "libibverbs.so.1",
        "libmlx5.so.1",
        "libnuma.so.1",
        "libstdc++.so.6",
    )
    resolved_native: dict[str, dict[str, str]] = {}
    mapped = [Path(str(value)).resolve() for value in mapped_paths]
    if any(path.name.startswith("libcudart.so.13") for path in mapped):
        raise E4Error("clean native import loaded forbidden CUDA 13 runtime")
    for soname in required_native_sonames:
        matches = sorted({path for path in mapped if path.name == soname})
        if len(matches) != 1 or native_runtime.resolve() not in matches[0].parents:
            raise E4Error(
                f"native loader did not resolve {soname} uniquely inside the bundle: {matches}"
            )
        resolved_native[soname] = {
            "path": str(matches[0]),
            "sha256": sha256_file(matches[0]),
        }

    manifest = load_json(manifest_path)
    toolchain = manifest.get("build", {}).get("toolchain", {})
    expected_pins = {
        "libcudart.so.12": toolchain.get("cudart", {}).get("sha256"),
        "libgcc_s.so.1": toolchain.get("libgcc_s", {}).get("sha256"),
        "libstdc++.so.6": toolchain.get("libstdc++", {}).get("sha256"),
    }
    pin_mismatches = {
        soname: {
            "observed": resolved_native[soname]["sha256"],
            "expected": expected,
        }
        for soname, expected in expected_pins.items()
        if resolved_native[soname]["sha256"] != expected
    }
    if pin_mismatches:
        raise E4Error(f"native loader pin mismatch: {pin_mismatches}")
    payload.update(
        {
            "status": "PASS",
            "ld_library_path": expected_ld_library_path,
            "required_native_resolution": resolved_native,
            "ld_debug_log": str(loader_log),
            "ld_debug_log_sha256": sha256_file(loader_log),
        }
    )
    write_json(probe_path, payload)
    return payload


def validate_vllm_runtime(runtime: Path, manifest_path: Path) -> dict[str, Any]:
    if runtime.resolve() != PINNED_RUNTIME.resolve() or not runtime.is_file():
        raise E4Error(f"unexpected pinned runtime {runtime}")
    manifest = load_json(manifest_path)
    try:
        source = manifest["source"]
        distribution = manifest["distribution"]
    except (KeyError, TypeError) as error:
        raise E4Error("pinned vLLM manifest lacks source/distribution") from error
    expected = {
        "commit": (source.get("commit"), PINNED_VLLM_COMMIT),
        "tracked_source_modified": (source.get("tracked_source_modified"), False),
        "version": (distribution.get("version"), PINNED_VLLM_VERSION),
        "wheel_sha256": (distribution.get("wheel_sha256"), PINNED_VLLM_WHEEL_SHA256),
    }
    mismatches = [
        f"{key}: observed={observed!r}, expected={wanted!r}"
        for key, (observed, wanted) in expected.items()
        if observed != wanted
    ]
    wheel_path = Path("/home/comp/zhanzhao/Mooncake") / distribution["wheel_relative_path"]
    if not wheel_path.is_file() or sha256_file(wheel_path) != PINNED_VLLM_WHEEL_SHA256:
        mismatches.append("pinned vLLM wheel file/hash mismatch")
    if not PINNED_MODEL.is_dir():
        mismatches.append(f"pinned offline model snapshot missing: {PINNED_MODEL}")
    aegis_environment_keys = sorted(key for key in os.environ if "AEGIS" in key.upper())
    if aegis_environment_keys:
        mismatches.append(f"Aegis policy environment keys are set: {aegis_environment_keys}")

    vllm_spec = importlib.util.find_spec("vllm")
    if vllm_spec is None or vllm_spec.origin is None:
        mismatches.append("vLLM package source is not discoverable")
        vllm_root = Path("/")
    else:
        vllm_root = Path(vllm_spec.origin).resolve().parent
    required_metric_sources = {
        "request": vllm_root / "v1" / "metrics" / "loggers.py",
        "mooncake_store": (
            vllm_root
            / "distributed"
            / "kv_transfer"
            / "kv_connector"
            / "v1"
            / "mooncake"
            / "store"
            / "metrics.py"
        ),
    }
    expected_metric_names = {
        "request": (
            "vllm:e2e_request_latency_seconds",
            "vllm:request_queue_time_seconds",
            "vllm:request_inference_time_seconds",
            "vllm:request_prefill_time_seconds",
            "vllm:request_prefill_kv_computed_tokens",
        ),
        "mooncake_store": (
            "vllm:mooncake_store_operation_time_seconds",
            "vllm:mooncake_store_operation_total",
            "vllm:mooncake_store_operation_bytes_total",
            "vllm:mooncake_store_operation_failed_keys_total",
        ),
    }
    metric_source_hashes: dict[str, str] = {}
    for group, path in required_metric_sources.items():
        if not path.is_file():
            mismatches.append(f"required metrics source missing: {path}")
            continue
        content = path.read_text(encoding="utf-8")
        missing_metrics = [name for name in expected_metric_names[group] if name not in content]
        if missing_metrics:
            mismatches.append(f"runtime lacks required {group} metrics: {missing_metrics}")
        metric_source_hashes[group] = sha256_file(path)

    policy_sources = [
        vllm_root / "config" / "kv_transfer.py",
        vllm_root / "distributed" / "kv_transfer" / "kv_connector" / "factory.py",
    ]
    store_source_root = (
        vllm_root / "distributed" / "kv_transfer" / "kv_connector" / "v1" / "mooncake" / "store"
    )
    if store_source_root.is_dir():
        policy_sources.extend(sorted(store_source_root.glob("*.py")))
    aegis_source_hits = []
    for path in policy_sources:
        if path.is_file() and "aegis" in path.read_text(encoding="utf-8").lower():
            aegis_source_hits.append(str(path))
    if aegis_source_hits:
        mismatches.append(f"Aegis marker found in active KV policy sources: {aegis_source_hits}")
    if mismatches:
        raise E4Error("pinned vLLM/model mismatch: " + "; ".join(mismatches))
    return {
        "runtime": str(runtime.resolve()),
        "manifest": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "commit": PINNED_VLLM_COMMIT,
        "version": PINNED_VLLM_VERSION,
        "wheel": str(wheel_path.resolve()),
        "wheel_sha256": PINNED_VLLM_WHEEL_SHA256,
        "model_snapshot": str(PINNED_MODEL),
        "model_revision": PINNED_MODEL_REVISION,
        "required_metrics_source_sha256": metric_source_hashes,
        "required_metrics": expected_metric_names,
        "policy_audit": {
            "connector": "MooncakeStoreConnector",
            "aegis_environment_keys": aegis_environment_keys,
            "aegis_active_source_hits": aegis_source_hits,
            "aegis_policy_enabled": False,
            "version_tag_contains_aegis_build_marker": True,
            "build_marker_is_not_policy_evidence": True,
        },
    }


def parse_labels(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    return {
        match.group(1): bytes(match.group(2), "utf-8").decode("unicode_escape")
        for match in LABEL.finditer(raw)
    }


def parse_prometheus(text: str) -> list[tuple[str, dict[str, str], float]]:
    samples: list[tuple[str, dict[str, str], float]] = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = PROMETHEUS_LINE.match(line)
        if match is None:
            continue
        samples.append(
            (
                match.group("name"),
                parse_labels(match.group("labels")),
                float(match.group("value")),
            )
        )
    return samples


def metric_total(
    samples: Sequence[tuple[str, Mapping[str, str], float]],
    name: str,
    labels: Mapping[str, str] | None = None,
) -> float:
    wanted = {} if labels is None else dict(labels)
    return sum(
        value
        for sample_name, sample_labels, value in samples
        if sample_name == name
        and all(sample_labels.get(key) == expected for key, expected in wanted.items())
    )


def metrics_snapshot(text: str) -> dict[str, Any]:
    samples = parse_prometheus(text)
    request_metrics = {
        key: metric_total(samples, prometheus)
        for key, prometheus in {
            "e2e_count": "vllm:e2e_request_latency_seconds_count",
            "e2e_seconds": "vllm:e2e_request_latency_seconds_sum",
            "queue_count": "vllm:request_queue_time_seconds_count",
            "queue_seconds": "vllm:request_queue_time_seconds_sum",
            "inference_count": "vllm:request_inference_time_seconds_count",
            "inference_seconds": "vllm:request_inference_time_seconds_sum",
            "prefill_count": "vllm:request_prefill_time_seconds_count",
            "prefill_seconds": "vllm:request_prefill_time_seconds_sum",
            "computed_tokens_count": "vllm:request_prefill_kv_computed_tokens_count",
            "computed_tokens": "vllm:request_prefill_kv_computed_tokens_sum",
        }.items()
    }
    operations: dict[str, dict[str, float]] = {}
    for operation in ("lookup_exists", "load_get", "save_exists", "save_put"):
        operations[operation] = {
            key: metric_total(samples, name, {"operation": operation})
            for key, name in {
                "calls": "vllm:mooncake_store_operation_total",
                "seconds": "vllm:mooncake_store_operation_time_seconds_sum",
                "keys": "vllm:mooncake_store_operation_keys_total",
                "bytes": "vllm:mooncake_store_operation_bytes_total",
                "failed_keys": "vllm:mooncake_store_operation_failed_keys_total",
            }.items()
        }
        operations[operation]["ok_calls"] = metric_total(
            samples,
            "vllm:mooncake_store_operation_total",
            {"operation": operation, "status": "ok"},
        )
        operations[operation]["error_calls"] = sum(
            metric_total(
                samples,
                "vllm:mooncake_store_operation_total",
                {"operation": operation, "status": status},
            )
            for status in ("error", "partial_failure")
        )
    return {"request": request_metrics, "operations": operations}


def subtract_snapshot(after: Mapping[str, Any], before: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "request": {
            key: float(after["request"][key]) - float(before["request"][key])
            for key in after["request"]
        },
        "operations": {
            operation: {
                key: float(after["operations"][operation][key])
                - float(before["operations"][operation][key])
                for key in after["operations"][operation]
            }
            for operation in after["operations"]
        },
    }


def decompose_request(delta: Mapping[str, Any], client_seconds: float) -> dict[str, Any]:
    request = delta["request"]
    operations = delta["operations"]
    prefill = float(request["prefill_seconds"])
    load_get = float(operations["load_get"]["seconds"])
    return {
        "queue_seconds": float(request["queue_seconds"]),
        "prefill_phase_seconds": prefill,
        "forward_path_residual_seconds": max(0.0, prefill - load_get),
        "forward_path_residual_method": "prefill_phase_minus_instrumented_load_get",
        "inference_running_seconds": float(request["inference_seconds"]),
        "kv_read_io_seconds": float(operations["lookup_exists"]["seconds"]) + load_get,
        "kv_write_io_seconds": float(operations["save_exists"]["seconds"])
        + float(operations["save_put"]["seconds"]),
        "kv_io_total_seconds": sum(float(values["seconds"]) for values in operations.values()),
        "engine_e2e_seconds": float(request["e2e_seconds"]),
        "client_e2e_seconds": client_seconds,
        "spans_are_additive": False,
    }


def http_request(
    url: str,
    *,
    method: str = "GET",
    body: object | None = None,
    timeout: float = 30.0,
) -> tuple[int, bytes, Mapping[str, str]]:
    payload = None if body is None else canonical_json(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers.items())


def wait_ready(base_url: str, process: subprocess.Popen[bytes], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last = "not attempted"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise E4Error(f"server exited before readiness with code {process.returncode}")
        try:
            status, body, _headers = http_request(f"{base_url}/health", timeout=2.0)
            if status == 200:
                return
            last = f"HTTP {status}: {body[:200]!r}"
        except (OSError, TimeoutError) as error:
            last = str(error)
        time.sleep(1.0)
    raise E4Error(f"server readiness timeout ({timeout}s): {last}")


def fetch_metrics(base_url: str) -> tuple[str, dict[str, Any]]:
    status, body, _headers = http_request(f"{base_url}/metrics", timeout=10.0)
    if status != 200:
        raise E4Error(f"metrics endpoint returned HTTP {status}")
    text = body.decode("utf-8", "replace")
    return text, metrics_snapshot(text)


def wait_metrics_quiet(
    base_url: str,
    *,
    timeout: float = 30.0,
    interval: float = 1.0,
    stable_intervals: int = 2,
) -> tuple[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    previous: dict[str, Any] | None = None
    stable = 0
    latest_text = ""
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest_text, latest = fetch_metrics(base_url)
        if latest == previous:
            stable += 1
            if stable >= stable_intervals:
                return latest_text, latest
        else:
            stable = 0
        previous = latest
        time.sleep(interval)
    raise E4Error(f"metrics did not become quiescent for {base_url}: {latest}")


def request_fingerprint(body: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(body).encode()).hexdigest()


def run_case(
    *,
    name: str,
    server_id: str,
    base_url: str,
    body: Mapping[str, Any],
    artifact_dir: Path,
    expect_operation: str | None,
    settle_timeout: float = 45.0,
) -> dict[str, Any]:
    before_text, before = fetch_metrics(base_url)
    (artifact_dir / f"{name}.metrics.before.prom").write_text(before_text, encoding="utf-8")
    write_json(artifact_dir / f"{name}.request.json", body)
    started = time.perf_counter()
    status, raw_response, headers = http_request(
        f"{base_url}/v1/completions", method="POST", body=body, timeout=180.0
    )
    client_seconds = time.perf_counter() - started
    (artifact_dir / f"{name}.response.raw.json").write_bytes(raw_response)
    write_json(artifact_dir / f"{name}.response.headers.json", dict(headers))
    if status != 200:
        raise E4Error(f"{name} returned HTTP {status}: {raw_response[:1000]!r}")
    try:
        response = json.loads(raw_response)
    except json.JSONDecodeError as error:
        raise E4Error(f"{name} response is not JSON") from error
    if not isinstance(response, dict) or not response.get("choices"):
        raise E4Error(f"{name} response lacks choices")

    deadline = time.monotonic() + settle_timeout
    after_text = ""
    after: dict[str, Any] = {}
    delta: dict[str, Any] = {}
    previous_after: dict[str, Any] | None = None
    stable_intervals = 0
    while time.monotonic() < deadline:
        after_text, after = fetch_metrics(base_url)
        delta = subtract_snapshot(after, before)
        request_finished = delta["request"]["e2e_count"] >= 1.0
        operation_finished = (
            expect_operation is None or delta["operations"][expect_operation]["ok_calls"] >= 1.0
        )
        if request_finished and operation_finished:
            if after == previous_after:
                stable_intervals += 1
                if stable_intervals >= 4:
                    break
            else:
                stable_intervals = 0
        else:
            stable_intervals = 0
        previous_after = after
        time.sleep(0.5)
    else:
        raise E4Error(
            f"{name} metrics did not settle: expected operation={expect_operation}, delta={delta}"
        )
    (artifact_dir / f"{name}.metrics.after.prom").write_text(after_text, encoding="utf-8")
    write_json(artifact_dir / f"{name}.metrics.delta.json", delta)
    return {
        "name": name,
        "server_id": server_id,
        "request_fingerprint": request_fingerprint(body),
        "http_status": status,
        "response_id": response.get("id"),
        "usage": response.get("usage"),
        "metrics_delta": delta,
        "decomposition": decompose_request(delta, client_seconds),
    }


def launch_process(
    command: Sequence[str],
    *,
    environment: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        list(command),
        env=dict(environment),
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )


def stop_process(process: subprocess.Popen[bytes] | None, timeout: float = 20.0) -> None:
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10.0)


def protected_jobs_snapshot() -> str:
    return run_text(
        [
            "squeue",
            "-h",
            "-j",
            ",".join(str(job) for job in PROTECTED_JOBS),
            "-o",
            "%i|%T|%P|%j|%u|%N|%b|%C|%M|%l|%R",
        ]
    )


def monitored_jobs_accounting_snapshot() -> str:
    return run_text(
        [
            "sacct",
            "-X",
            "-n",
            "-P",
            "-j",
            ",".join(str(job) for job in READ_ONLY_MONITORED_JOBS),
            "-o",
            "JobIDRaw,State%64,Partition,JobName,NodeList,Elapsed,Start,End,ExitCode",
        ]
    )


def _parse_job_states(snapshot: str, *, source: str) -> dict[int, str]:
    observed: dict[int, str] = {}
    for line in snapshot.splitlines():
        fields = line.split("|")
        if (
            len(fields) < 2
            or not fields[0].isdigit()
            or not re.fullmatch(r"[A-Z][A-Z_]*(?:\+| by [0-9]+)?", fields[1])
        ):
            raise E4Error(f"malformed {source} job row: {line!r}")
        job_id = int(fields[0])
        if job_id in observed:
            raise E4Error(f"duplicate {source} job row: {job_id}")
        observed[job_id] = fields[1]
    return observed


def validate_protected_jobs_snapshot(
    queue_snapshot: str,
    accounting_snapshot: str,
) -> dict[str, Any]:
    """Validate held-job gates and ephemeral monitored-job observations.

    The accounting snapshot makes completed/failed monitored jobs observable
    after they naturally leave ``squeue``.  No caller compares pre/post states.
    """

    queue = _parse_job_states(queue_snapshot, source="squeue")
    accounting = _parse_job_states(accounting_snapshot, source="sacct")
    unexpected_queue = sorted(set(queue) - set(PROTECTED_JOBS))
    unexpected_accounting = sorted(set(accounting) - set(READ_ONLY_MONITORED_JOBS))
    missing = sorted(set(HELD_PENDING_JOBS) - set(queue))
    non_pending = {
        job_id: queue[job_id]
        for job_id in HELD_PENDING_JOBS
        if job_id in queue and queue[job_id] != "PENDING"
    }
    missing_accounting = sorted(set(READ_ONLY_MONITORED_JOBS) - set(accounting))
    if missing or non_pending or missing_accounting or unexpected_queue or unexpected_accounting:
        raise E4Error(
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


def choose_ports() -> list[int]:
    # Bind-to-zero is used only to obtain currently unused loopback ports.  The
    # exclusive-node Slurm contract and immediate launches close the race.
    import socket

    sockets = []
    ports = []
    try:
        for _ in range(4):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
            ports.append(int(sock.getsockname()[1]))
    finally:
        for sock in sockets:
            sock.close()
    return ports


def validate_round(round_result: Mapping[str, Any], prompt_tokens: int) -> list[str]:
    errors: list[str] = []
    cold = round_result["cold_reference"]
    prime = round_result["prime_on_a"]
    reuse = round_result["reuse_on_b"]
    cold_delta = cold["metrics_delta"]
    prime_delta = prime["metrics_delta"]
    reuse_delta = reuse["metrics_delta"]
    if prime["server_id"] == reuse["server_id"]:
        errors.append("prime and reuse ran on the same vLLM instance")
    if prime["request_fingerprint"] != reuse["request_fingerprint"]:
        errors.append("prime/reuse request fingerprints differ")
    if cold["request_fingerprint"] == reuse["request_fingerprint"]:
        errors.append("cold/reuse request fingerprints are not distinct")
    if prime_delta["operations"]["save_put"]["ok_calls"] < 1:
        errors.append("prime lacks a successful Store PUT")
    if prime_delta["operations"]["save_put"]["bytes"] <= 0:
        errors.append("prime Store PUT has no transferred bytes")
    if reuse_delta["operations"]["lookup_exists"]["ok_calls"] < 1:
        errors.append("reuse lacks a successful Store lookup")
    if reuse_delta["operations"]["load_get"]["ok_calls"] < 1:
        errors.append("reuse lacks a successful Store GET")
    if reuse_delta["operations"]["load_get"]["bytes"] <= 0:
        errors.append("reuse Store GET has no transferred bytes")
    if reuse_delta["operations"]["load_get"]["failed_keys"] != 0:
        errors.append("reuse Store GET contains failed keys")
    cold_computed = cold_delta["request"]["computed_tokens"]
    reuse_computed = reuse_delta["request"]["computed_tokens"]
    if cold_computed < prompt_tokens - 32:
        errors.append(f"cold case unexpectedly computed only {cold_computed} tokens")
    if reuse_computed >= cold_computed:
        errors.append(
            "reuse did not reduce computed prefix tokens: "
            f"cold={cold_computed}, reuse={reuse_computed}"
        )
    for case_name, case in (("cold", cold), ("prime", prime), ("reuse", reuse)):
        delta = case["metrics_delta"]
        for metric in (
            "e2e_count",
            "queue_count",
            "inference_count",
            "prefill_count",
            "computed_tokens_count",
        ):
            if delta["request"][metric] != 1:
                errors.append(f"{case_name} does not bind exactly one {metric} observation")
        if any(values["error_calls"] for values in delta["operations"].values()):
            errors.append(f"{case_name} contains failed Mooncake operations")
    return errors


def run_experiment(args: argparse.Namespace, artifact_dir: Path) -> dict[str, Any]:
    slurm = validate_slurm(os.environ)
    pre_gpu = collect_gpu_snapshot(slurm["cuda_visible_devices"])
    write_json(artifact_dir / "gpu-pre.json", pre_gpu)
    (artifact_dir / "gpu-pre.csv").write_text(
        pre_gpu["raw_gpu_csv"] + pre_gpu["raw_process_csv"], encoding="utf-8"
    )
    if pre_gpu["compute_processes"]:
        raise E4Error(
            f"compute processes found on assigned GPUs before launch: "
            f"{pre_gpu['compute_processes']}"
        )
    before_jobs = protected_jobs_snapshot()
    (artifact_dir / "protected-jobs-pre.txt").write_text(before_jobs, encoding="utf-8")
    before_accounting = monitored_jobs_accounting_snapshot()
    (artifact_dir / "monitored-jobs-accounting-pre.txt").write_text(
        before_accounting, encoding="utf-8"
    )
    write_json(
        artifact_dir / "protected-jobs-observation-pre.json",
        validate_protected_jobs_snapshot(before_jobs, before_accounting),
    )

    build = validate_build_bundle(args.build_manifest, args.clean_wheel, args.overlay)
    vllm = validate_vllm_runtime(args.runtime, args.vllm_build_manifest)
    native_loader_probe = probe_clean_native_loader(
        args.runtime,
        args.overlay,
        args.build_manifest,
        artifact_dir,
    )
    post_probe_gpu = collect_gpu_snapshot(slurm["cuda_visible_devices"])
    write_json(artifact_dir / "gpu-post-native-import-probe.json", post_probe_gpu)
    if post_probe_gpu["compute_processes"]:
        raise E4Error(
            "compute processes remain on assigned GPUs after native import probe: "
            f"{post_probe_gpu['compute_processes']}"
        )
    ports = choose_ports()
    master_port, metadata_port, server_a_port, server_b_port = ports
    config = validate_store_config(
        {
            "metadata_server": f"http://127.0.0.1:{metadata_port}/metadata",
            "master_server_address": f"127.0.0.1:{master_port}",
            "protocol": "tcp",
            "device_name": "",
            "mode": "embedded",
            "global_segment_size": args.global_segment_bytes,
            "local_buffer_size": args.local_buffer_bytes,
            "enable_offload": False,
        }
    )
    config_path = artifact_dir / "mooncake-config.json"
    write_json(config_path, config)

    base_environment = dict(os.environ)
    base_environment.update(
        {
            "PYTHONPATH": f"{args.overlay}:{base_environment.get('PYTHONPATH', '')}",
            "PYTHONHASHSEED": "0",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "VLLM_USE_V1": "1",
            "MOONCAKE_CONFIG_PATH": str(config_path),
            "MC_DISABLE_MMAP_ARENA": "1",
            "MC_STORE_USE_HUGEPAGE": "0",
        }
    )
    visible_tokens = [
        token.strip() for token in slurm["cuda_visible_devices"].split(",") if token.strip()
    ]
    connector = {
        "kv_connector": "MooncakeStoreConnector",
        "kv_role": "kv_both",
        "kv_connector_extra_config": {"load_async": True},
    }
    common_server = [
        str(args.runtime),
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        str(PINNED_MODEL),
        "--served-model-name",
        args.served_model,
        "--host",
        "127.0.0.1",
        "--dtype",
        "bfloat16",
        "--max-model-len",
        str(args.max_model_len),
        "--gpu-memory-utilization",
        str(args.gpu_memory_utilization),
        "--max-num-batched-tokens",
        str(args.max_model_len),
        "--max-num-seqs",
        "4",
        "--enforce-eager",
        "--enable-prefix-caching",
        "--disable-uvicorn-access-log",
        "--generation-config",
        "vllm",
        "--kv-transfer-config",
        canonical_json(connector).strip(),
    ]

    processes: list[subprocess.Popen[bytes]] = []
    streams: list[TextIO] = []
    launch_records: list[dict[str, Any]] = []
    try:
        master_stdout = (artifact_dir / "mooncake-master.stdout.log").open("w", encoding="utf-8")
        master_stderr = (artifact_dir / "mooncake-master.stderr.log").open("w", encoding="utf-8")
        streams.extend((master_stdout, master_stderr))
        master_command = [
            str(args.runtime),
            "-m",
            "mooncake.cli",
            "--port",
            str(master_port),
            "--enable_http_metadata_server=true",
            "--http_metadata_server_host=127.0.0.1",
            f"--http_metadata_server_port={metadata_port}",
        ]
        master = launch_process(
            master_command,
            environment=base_environment,
            stdout=master_stdout,
            stderr=master_stderr,
        )
        processes.append(master)
        launch_records.append({"id": "master", "pid": master.pid, "command": master_command})
        time.sleep(2.0)
        if master.poll() is not None:
            raise E4Error(f"Mooncake master exited with code {master.returncode}")

        servers: dict[str, tuple[subprocess.Popen[bytes], str]] = {}
        for server_id, port, gpu_token, lookup_id in (
            ("server_a", server_a_port, visible_tokens[0], 41001),
            ("server_b", server_b_port, visible_tokens[1], 41002),
        ):
            stdout = (artifact_dir / f"{server_id}.stdout.log").open("w", encoding="utf-8")
            stderr = (artifact_dir / f"{server_id}.stderr.log").open("w", encoding="utf-8")
            streams.extend((stdout, stderr))
            rpc_dir = artifact_dir / f"rpc-{server_id}"
            rpc_dir.mkdir()
            environment = dict(base_environment)
            environment.update(
                {
                    "CUDA_VISIBLE_DEVICES": gpu_token,
                    "VLLM_RPC_BASE_PATH": str(rpc_dir),
                }
            )
            per_server_connector = json.loads(canonical_json(connector))
            per_server_connector["kv_connector_extra_config"]["lookup_rpc_port"] = lookup_id
            command = list(common_server)
            command[-1] = canonical_json(per_server_connector).strip()
            command.extend(("--port", str(port)))
            process = launch_process(command, environment=environment, stdout=stdout, stderr=stderr)
            processes.append(process)
            base_url = f"http://127.0.0.1:{port}"
            servers[server_id] = (process, base_url)
            launch_records.append(
                {
                    "id": server_id,
                    "pid": process.pid,
                    "gpu_token": gpu_token,
                    "base_url": base_url,
                    "command": command,
                    "environment_contract": {
                        "PYTHONHASHSEED": "0",
                        "MOONCAKE_CONFIG_PATH": str(config_path),
                        "PYTHONPATH_overlay_first": str(args.overlay),
                    },
                }
            )
        write_json(artifact_dir / "launch.json", launch_records)
        for process, base_url in servers.values():
            wait_ready(base_url, process, args.startup_timeout)

        # Functional warm-up is kept outside every measured metrics window.
        for index, (server_id, (_process, base_url)) in enumerate(servers.items()):
            warmup = {
                "model": args.served_model,
                "prompt": [1000 + index] * 128,
                "max_tokens": 1,
                "temperature": 0.0,
                "seed": 0,
                "ignore_eos": True,
                "stream": False,
            }
            status, response, _headers = http_request(
                f"{base_url}/v1/completions", method="POST", body=warmup, timeout=180.0
            )
            write_json(artifact_dir / f"warmup-{server_id}.request.json", warmup)
            (artifact_dir / f"warmup-{server_id}.response.raw.json").write_bytes(response)
            if status != 200:
                raise E4Error(f"{server_id} warm-up returned HTTP {status}")
        for server_id, (_process, base_url) in servers.items():
            quiet_text, quiet_snapshot = wait_metrics_quiet(base_url)
            (artifact_dir / f"warmup-{server_id}.metrics.quiet.prom").write_text(
                quiet_text, encoding="utf-8"
            )
            write_json(artifact_dir / f"warmup-{server_id}.metrics.quiet.json", quiet_snapshot)

        round_results: list[dict[str, Any]] = []
        for round_index in range(args.rounds):
            cold_token = 2000 + round_index
            reuse_token = 3000 + round_index
            cold_body = {
                "model": args.served_model,
                "prompt": [cold_token] * args.prompt_tokens,
                "max_tokens": 1,
                "temperature": 0.0,
                "seed": 0,
                "ignore_eos": True,
                "stream": False,
            }
            reuse_body = dict(cold_body)
            reuse_body["prompt"] = [reuse_token] * args.prompt_tokens
            cold = run_case(
                name=f"r{round_index}-cold-b",
                server_id="server_b",
                base_url=servers["server_b"][1],
                body=cold_body,
                artifact_dir=artifact_dir,
                expect_operation="save_put",
            )
            prime = run_case(
                name=f"r{round_index}-prime-a",
                server_id="server_a",
                base_url=servers["server_a"][1],
                body=reuse_body,
                artifact_dir=artifact_dir,
                expect_operation="save_put",
            )
            reuse = run_case(
                name=f"r{round_index}-reuse-b",
                server_id="server_b",
                base_url=servers["server_b"][1],
                body=reuse_body,
                artifact_dir=artifact_dir,
                expect_operation="load_get",
            )
            record = {
                "round": round_index,
                "cold_reference": cold,
                "prime_on_a": prime,
                "reuse_on_b": reuse,
            }
            record["gate_errors"] = validate_round(record, args.prompt_tokens)
            round_results.append(record)

        all_errors = [
            f"round {row['round']}: {error}"
            for row in round_results
            for error in row["gate_errors"]
        ]
        if all_errors:
            raise E4Error("cross-instance evidence gate failed: " + "; ".join(all_errors))

        return {
            "schema": SCHEMA,
            "status": "PASS",
            "evidence_level": "E3_SMALL_SCALE_PHYSICAL_COMPONENT",
            "evidence_scope": "Vanilla baseline only; two RTX4090; TP1 x two instances",
            "paper_ready": False,
            "e4_status": "BLOCKED_MISSING_MATCHED_MOONKVSIM_ERROR_COMPARISON",
            "slurm": slurm,
            "source_and_build": {
                "mooncake": build,
                "vllm": vllm,
                "native_loader_probe": native_loader_probe,
            },
            "store_config": config,
            "topology": {
                "connector": "MooncakeStoreConnector",
                "role": "kv_both",
                "instances": ["server_a", "server_b"],
                "cross_instance_route": "prime server_a -> first reuse server_b",
                "transport": "tcp",
                "tier": "embedded_dram_only",
                "ssd_nvme": False,
                "metadata_control_plane": "master_embedded_http",
                "http_metadata_is_data_or_persistent_tier": False,
                "pythonhashseed": 0,
            },
            "workload": {
                "rounds": args.rounds,
                "prompt_tokens": args.prompt_tokens,
                "output_tokens": 1,
                "matched_cold_and_reuse_lengths": True,
            },
            "rounds": round_results,
            "decomposition_semantics": {
                "forward_path_residual": "prefill phase minus instrumented load_get RPC time",
                "kv_io": "MooncakeStoreConnector RPC Prometheus deltas",
                "queue": "vLLM completed-request WAITING histogram delta",
                "engine_e2e": "vLLM completed-request E2E histogram delta",
                "client_e2e": "client monotonic wall span",
                "spans_are_additive": False,
            },
            "evidence_boundary": {
                "physical_request_path_executed": True,
                "import_or_startup_only": False,
                "matched_simulator_run_present": False,
                "simulator_error_comparison_present": False,
                "formal_e4_claim_allowed": False,
            },
            "gate": {
                "status": "PASS",
                "requirements": [
                    "distinct prime/reuse vLLM instances",
                    "successful prime save_put with bytes",
                    "successful reuse lookup_exists and load_get with bytes",
                    "zero Store GET failed keys",
                    "reuse computes fewer prompt KV tokens than matched cold",
                    "exactly one completed request metric per measured case",
                ],
            },
        }
    finally:
        active_error = sys.exc_info()[1]
        cleanup_errors: list[str] = []
        for process in reversed(processes):
            try:
                stop_process(process)
            except Exception as error:
                cleanup_errors.append(f"process teardown failed: {error}")
        for stream in streams:
            try:
                stream.close()
            except Exception as error:
                cleanup_errors.append(f"log stream close failed: {error}")
        try:
            post_gpu = collect_gpu_snapshot(slurm["cuda_visible_devices"])
            write_json(artifact_dir / "gpu-post.json", post_gpu)
            (artifact_dir / "gpu-post.csv").write_text(
                post_gpu["raw_gpu_csv"] + post_gpu["raw_process_csv"], encoding="utf-8"
            )
            if post_gpu["compute_processes"]:
                raise E4Error(
                    f"compute processes found on assigned GPUs after teardown: "
                    f"{post_gpu['compute_processes']}"
                )
        except Exception as error:
            (artifact_dir / "gpu-post-error.txt").write_text(str(error) + "\n", encoding="utf-8")
            cleanup_errors.append(f"post-run GPU gate failed: {error}")
        try:
            after_jobs = protected_jobs_snapshot()
            (artifact_dir / "protected-jobs-post.txt").write_text(after_jobs, encoding="utf-8")
            after_accounting = monitored_jobs_accounting_snapshot()
            (artifact_dir / "monitored-jobs-accounting-post.txt").write_text(
                after_accounting, encoding="utf-8"
            )
            write_json(
                artifact_dir / "protected-jobs-observation-post.json",
                validate_protected_jobs_snapshot(after_jobs, after_accounting),
            )
        except Exception as error:
            (artifact_dir / "protected-jobs-post-error.txt").write_text(
                str(error) + "\n", encoding="utf-8"
            )
            cleanup_errors.append(f"protected-job post gate failed: {error}")
        if cleanup_errors:
            write_json(artifact_dir / "cleanup-gate-errors.json", cleanup_errors)
            if active_error is None:
                raise E4Error("; ".join(cleanup_errors))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--artifact-dir", type=Path, required=True)
    value.add_argument("--clean-wheel", type=Path, required=True)
    value.add_argument("--build-manifest", type=Path, required=True)
    value.add_argument("--overlay", type=Path, required=True)
    value.add_argument("--runtime", type=Path, default=PINNED_RUNTIME)
    value.add_argument("--vllm-build-manifest", type=Path, default=PINNED_VLLM_BUILD_MANIFEST)
    value.add_argument("--served-model", default="Qwen/Qwen3-8B")
    value.add_argument("--rounds", type=int, default=2)
    value.add_argument("--prompt-tokens", type=int, default=4096)
    value.add_argument("--max-model-len", type=int, default=8192)
    value.add_argument("--global-segment-bytes", type=int, default=8 * 1024**3)
    value.add_argument("--local-buffer-bytes", type=int, default=1024**3)
    value.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    value.add_argument("--startup-timeout", type=float, default=1200.0)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    requested_artifact_dir = args.artifact_dir.absolute()
    artifact_dir = requested_artifact_dir.resolve()
    if (
        not artifact_dir.is_dir()
        or requested_artifact_dir.is_symlink()
        or requested_artifact_dir != artifact_dir
    ):
        print("MOONKVSIM_E4_ERROR=artifact directory must pre-exist and be safe", file=sys.stderr)
        return 2
    result_path = artifact_dir / "result.json"
    if result_path.exists() or result_path.is_symlink():
        print("MOONKVSIM_E4_ERROR=refusing to overwrite result.json", file=sys.stderr)
        return 2
    try:
        if args.rounds < 2:
            raise E4Error("at least two matched rounds are required")
        if args.prompt_tokens < 512 or args.prompt_tokens >= args.max_model_len:
            raise E4Error("prompt_tokens must be in [512, max_model_len)")
        result = run_experiment(args, artifact_dir)
        write_json(result_path, result)
        print(canonical_json(result), end="")
        return 0
    except Exception as error:
        failure = {
            "schema": SCHEMA,
            "status": "FAIL",
            "evidence_level": "NONE",
            "paper_ready": False,
            "error_type": type(error).__name__,
            "error": str(error),
        }
        if not result_path.exists():
            write_json(result_path, failure)
        print(f"MOONKVSIM_E4_ERROR={type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
