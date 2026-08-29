#!/usr/bin/env python3
"""Pinned Qwen3-8B/vLLM short- and 128K-context physical probe.

The default mode is an orchestrator.  It verifies all pinned inputs before any
model is loaded, checks only the one CUDA device exposed to this Slurm job, and
runs native and static-YaRN engines in separate child processes.  The timing
fields are operational telemetry only; this probe is not a latency calibration
or a performance benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import time
import traceback
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

SCHEMA: Final = "moonkvsim.qwen3_8b_context_physical_probe.v1"
WORKER_SCHEMA: Final = "moonkvsim.qwen3_8b_context_worker.v1"
EXPECTED_MODEL_REVISION: Final = "b968826d9c46dd6066d109eabc6255188de91218"
EXPECTED_VLLM_COMMIT: Final = "644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504"
EXPECTED_VLLM_VERSION: Final = "1.2.2+aegiskv.sm89"
EXPECTED_VLLM_DISTRIBUTION: Final = "1cat-vllm"
EXPECTED_RUNTIME_PYTHON: Final = Path(
    "/home/comp/zhanzhao/Mooncake/aegiskv/.venv-vllm-sm89/bin/python"
)
EXPECTED_MODEL_SNAPSHOT: Final = Path(
    "/home/comp/zhanzhao/.cache/huggingface/hub/"
    "models--Qwen--Qwen3-8B/snapshots/"
    f"{EXPECTED_MODEL_REVISION}"
)
SHORT_PROMPT_TOKENS: Final = 8192
LONG_PROMPT_TOKENS: Final = 131071
MAX_MODEL_LEN: Final = 131072
MAX_OUTPUT_TOKENS: Final = 1
PROMPT_TOKEN_ID: Final = 42
YARN_SCALING: Final = {
    "rope_type": "yarn",
    "factor": 4.0,
    "original_max_position_embeddings": 32768,
}
NATIVE_KV_LAYOUT_RELATIVE: Final = Path("configs/resolved/qwen3-8b/native-tp1-pp1/kv-layout.json")
YARN_KV_LAYOUT_RELATIVE: Final = Path(
    "configs/resolved/qwen3-8b/proposed-yarn-128k-tp1-pp1/kv-layout.json"
)
HEX64: Final = re.compile(r"^[0-9a-f]{64}$")


class ProbeValidationError(RuntimeError):
    """A fail-closed input, runtime, or result validation failure."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the canonical JSON representation used for probe evidence."""

    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def write_canonical_json(path: Path, value: object) -> None:
    """Create a canonical JSON file without overwriting an existing artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical_json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_source_lock(lock_path: Path) -> dict[str, Any]:
    try:
        value = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProbeValidationError(f"cannot load source lock {lock_path}: {error}") from error
    if not isinstance(value, dict):
        raise ProbeValidationError("source lock root must be an object")
    return value


def build_probe_plan(lock: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the immutable candidate and return the exact three-case plan."""

    try:
        vllm = lock["repositories"]["vllm"]
        model = lock["model_tokenizer"]
        context = model["context_128k"]
    except (KeyError, TypeError) as error:
        raise ProbeValidationError(f"source lock lacks required probe fields: {error}") from error

    checks = {
        "vllm_commit": (vllm.get("commit"), EXPECTED_VLLM_COMMIT),
        "vllm_version": (
            vllm.get("observed_generated_version"),
            EXPECTED_VLLM_VERSION,
        ),
        "model_revision": (model.get("revision"), EXPECTED_MODEL_REVISION),
        "snapshot_path": (model.get("snapshot_path"), str(EXPECTED_MODEL_SNAPSHOT)),
        "context_status": (context.get("status"), "proposed_unvalidated"),
        "context_readiness": (context.get("readiness"), "BLOCKED"),
        "max_model_len": (context.get("max_model_len"), MAX_MODEL_LEN),
        "requested_max_model_len": (
            context.get("requested_max_model_len"),
            MAX_MODEL_LEN,
        ),
        "rope_scaling": (context.get("rope_scaling"), YARN_SCALING),
        "physical_completed": (
            context.get("physical_validation", {}).get("completed"),
            False,
        ),
        "formal_128k_allowed": (context.get("formal_128k_allowed"), False),
    }
    mismatches = [
        f"{name}: observed={observed!r}, expected={expected!r}"
        for name, (observed, expected) in checks.items()
        if observed != expected
    ]
    if mismatches:
        raise ProbeValidationError("probe pin mismatch: " + "; ".join(mismatches))

    return {
        "engine_processes": [
            {
                "mode": "native",
                "max_model_len": 40960,
                "rope_scaling": None,
                "cases": ["native_short"],
            },
            {
                "mode": "yarn",
                "max_model_len": MAX_MODEL_LEN,
                "rope_scaling": dict(YARN_SCALING),
                "cases": ["yarn_short", "yarn_exact_128k"],
            },
        ],
        "cases": {
            "native_short": {
                "mode": "native",
                "prompt_tokens": SHORT_PROMPT_TOKENS,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "total_tokens": SHORT_PROMPT_TOKENS + MAX_OUTPUT_TOKENS,
            },
            "yarn_short": {
                "mode": "yarn",
                "prompt_tokens": SHORT_PROMPT_TOKENS,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "total_tokens": SHORT_PROMPT_TOKENS + MAX_OUTPUT_TOKENS,
            },
            "yarn_exact_128k": {
                "mode": "yarn",
                "prompt_tokens": LONG_PROMPT_TOKENS,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "total_tokens": MAX_MODEL_LEN,
            },
        },
        "prompt_token_id": PROMPT_TOKEN_ID,
        "sampling": {
            "temperature": 0.0,
            "seed": 0,
            "ignore_eos": True,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "detokenize": False,
        },
        "evidence_boundary": {
            "class": "physical_functional_diagnostic",
            "evidence_level_ceiling": "physical_functional_only",
            "functional_validation_only": True,
            "latency_fields_are_telemetry_only": True,
            "calibration": False,
            "performance_result": False,
            "short_context_quality_validation": False,
            "formal_experiment_result": False,
        },
    }


def validate_slurm_environment(environment: Mapping[str, str]) -> dict[str, str]:
    job_id = environment.get("SLURM_JOB_ID", "")
    visible = environment.get("CUDA_VISIBLE_DEVICES", "")
    if not job_id or not job_id.isdigit():
        raise ProbeValidationError("SLURM_JOB_ID must be a numeric Slurm job id")
    visible_parts = [item.strip() for item in visible.split(",") if item.strip()]
    if len(visible_parts) != 1:
        raise ProbeValidationError(
            f"exactly one CUDA_VISIBLE_DEVICES entry is required; observed {visible!r}"
        )
    partition = environment.get("SLURM_JOB_PARTITION", "")
    if partition and partition != "short":
        raise ProbeValidationError(
            f"the physical probe requires partition short, observed {partition!r}"
        )
    return {
        "job_id": job_id,
        "partition": partition or "recorded_by_slurm_job_artifact",
        "job_gpus": environment.get("SLURM_JOB_GPUS", ""),
        "cuda_visible_devices": visible_parts[0],
        "node": environment.get("SLURMD_NODENAME", environment.get("HOSTNAME", "")),
        "submit_dir": environment.get("SLURM_SUBMIT_DIR", ""),
        "cpus_per_task": environment.get("SLURM_CPUS_PER_TASK", ""),
        "memory_per_node": environment.get("SLURM_MEM_PER_NODE", ""),
    }


def validate_launch_provenance(
    artifact_dir: Path, environment: Mapping[str, str]
) -> dict[str, Any]:
    """Bind the executing staged probe and Slurm-spooled wrapper to the run."""

    executing_probe = Path(__file__).resolve()
    resolved_artifact_dir = artifact_dir.resolve()
    if executing_probe.parent != resolved_artifact_dir:
        raise ProbeValidationError(
            "the orchestrator must execute the probe copy staged in the artifact directory"
        )
    expected_probe_sha = environment.get("MOONKVSIM_PROBE_SCRIPT_SHA256", "")
    if not HEX64.fullmatch(expected_probe_sha):
        raise ProbeValidationError("missing valid MOONKVSIM_PROBE_SCRIPT_SHA256")
    observed_probe_sha = sha256_file(executing_probe)
    if observed_probe_sha != expected_probe_sha:
        raise ProbeValidationError(
            "executing staged probe SHA-256 mismatch: "
            f"observed={observed_probe_sha}, expected={expected_probe_sha}"
        )

    if environment.get("MOONKVSIM_BATCH_SCRIPT_CAPTURE_STATUS") != "PASS":
        raise ProbeValidationError("Slurm-spooled batch script capture did not pass")
    batch_script = resolved_artifact_dir / "submitted-batch-script.sh"
    if not batch_script.is_file() or batch_script.is_symlink():
        raise ProbeValidationError("captured Slurm batch script is missing or unsafe")
    expected_batch_sha = environment.get("MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256", "")
    if not HEX64.fullmatch(expected_batch_sha):
        raise ProbeValidationError("missing valid MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256")
    observed_batch_sha = sha256_file(batch_script)
    if observed_batch_sha != expected_batch_sha:
        raise ProbeValidationError(
            "captured Slurm batch script SHA-256 mismatch: "
            f"observed={observed_batch_sha}, expected={expected_batch_sha}"
        )
    return {
        "status": "PASS",
        "executing_probe": {
            "path": str(executing_probe),
            "sha256": observed_probe_sha,
            "is_staged_copy": True,
        },
        "slurm_spooled_batch_script": {
            "path": str(batch_script),
            "sha256": observed_batch_sha,
            "capture_command": "scontrol write batch_script",
            "repository_wrapper_used_as_substitute": False,
        },
    }


def _record_and_verify_file(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not HEX64.fullmatch(expected_sha256):
        raise ProbeValidationError(f"invalid pinned SHA-256 for {path}: {expected_sha256!r}")
    if not path.is_file():
        raise ProbeValidationError(f"required pinned file is missing: {path}")
    observed = sha256_file(path)
    if observed != expected_sha256:
        raise ProbeValidationError(
            f"SHA-256 mismatch for {path}: observed={observed}, expected={expected_sha256}"
        )
    return {
        "path": str(path),
        "resolved_path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": observed,
        "status": "PASS",
    }


def verify_pinned_inputs(lock_path: Path, lock: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the installed vLLM semantic sources and cached model bytes."""

    plan = build_probe_plan(lock)
    runtime_prefix = EXPECTED_RUNTIME_PYTHON.parent.parent.resolve()
    if Path(sys.prefix).resolve() != runtime_prefix:
        raise ProbeValidationError(
            "probe must run in the pinned vLLM environment: "
            f"sys.prefix={Path(sys.prefix).resolve()}, expected={runtime_prefix}"
        )

    distribution = importlib.metadata.distribution(EXPECTED_VLLM_DISTRIBUTION)
    if distribution.version != EXPECTED_VLLM_VERSION:
        raise ProbeValidationError(
            "installed vLLM version mismatch: "
            f"observed={distribution.version}, expected={EXPECTED_VLLM_VERSION}"
        )
    package_root = Path(distribution.locate_file("vllm")).resolve()
    vllm_spec = lock["repositories"]["vllm"]
    verified_vllm: list[dict[str, Any]] = []
    for item in vllm_spec["files"]:
        relative = Path(item["path"])
        if relative.parts[0] != "vllm" or ".." in relative.parts:
            raise ProbeValidationError(f"invalid installed vLLM path in lock: {relative}")
        installed_path = package_root.joinpath(*relative.parts[1:])
        verified_vllm.append(_record_and_verify_file(installed_path, item["sha256"]))

    snapshot = EXPECTED_MODEL_SNAPSHOT
    if not snapshot.is_dir():
        raise ProbeValidationError(f"pinned model snapshot is missing: {snapshot}")
    model_spec = lock["model_tokenizer"]
    verified_model: list[dict[str, Any]] = []
    for item in model_spec["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ProbeValidationError(f"invalid model path in lock: {relative}")
        verified_model.append(_record_and_verify_file(snapshot / relative, item["sha256"]))

    config = json.loads((snapshot / "config.json").read_text(encoding="utf-8"))
    declared_config = model_spec["model_config"]
    semantic_keys = (
        "model_type",
        "hidden_size",
        "num_hidden_layers",
        "num_attention_heads",
        "num_key_value_heads",
        "head_dim",
        "max_position_embeddings",
        "rope_theta",
        "rope_scaling",
    )
    config_mismatches = [
        f"{key}: observed={config.get(key)!r}, expected={declared_config.get(key)!r}"
        for key in semantic_keys
        if config.get(key) != declared_config.get(key)
    ]
    if config_mismatches:
        raise ProbeValidationError(
            "model config semantic mismatch: " + "; ".join(config_mismatches)
        )

    index_path = snapshot / "model.safetensors.index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    filenames = sorted(set(index.get("weight_map", {}).values()))
    if not filenames:
        raise ProbeValidationError("model weight index has no shard filenames")
    verified_weights: list[dict[str, Any]] = []
    for filename in filenames:
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ProbeValidationError(f"unsafe model shard filename: {filename!r}")
        shard = snapshot / filename
        if not shard.is_symlink():
            raise ProbeValidationError(f"model shard must be a pinned cache symlink: {shard}")
        resolved = shard.resolve(strict=True)
        expected = resolved.name
        if not HEX64.fullmatch(expected):
            raise ProbeValidationError(
                f"model shard cache blob is not SHA-256 addressed: {resolved}"
            )
        record = _record_and_verify_file(shard, expected)
        record["cache_blob_sha256"] = expected
        verified_weights.append(record)

    return {
        "status": "PASS",
        "source_lock": {
            "path": str(lock_path.resolve()),
            "sha256": sha256_file(lock_path),
            "schema": lock.get("schema"),
            "readiness_status_at_launch": lock.get("readiness", {}).get("status"),
            "src_block_002_left_unchanged": True,
        },
        "runtime_environment": {
            "expected_python": str(EXPECTED_RUNTIME_PYTHON),
            "sys_executable": sys.executable,
            "sys_prefix": sys.prefix,
            "distribution": distribution.metadata.get("Name"),
            "version": distribution.version,
            "package_root": str(package_root),
        },
        "vllm": {
            "commit": EXPECTED_VLLM_COMMIT,
            "semantic_files": verified_vllm,
        },
        "model": {
            "id": model_spec["model_id"],
            "revision": EXPECTED_MODEL_REVISION,
            "snapshot": str(snapshot),
            "critical_files": verified_model,
            "weight_shards": verified_weights,
            "config_semantics": {key: config.get(key) for key in semantic_keys},
            "model_card_sha256_declaration": model_spec["official_model_card"]["sha256"],
            "model_card_role": "fixed_revision_configuration_guidance_only",
        },
        "probe_plan_sha256": hashlib.sha256(canonical_json_bytes(plan)).hexdigest(),
    }


def _nvml_process_records(module: Any, handle: Any) -> list[dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    getters = (
        ("compute", module.nvmlDeviceGetComputeRunningProcesses),
        ("graphics", module.nvmlDeviceGetGraphicsRunningProcesses),
    )
    for process_kind, getter in getters:
        try:
            processes = getter(handle)
        except module.NVMLError_NotSupported:
            processes = []
        for process in processes:
            pid = int(process.pid)
            record = records.setdefault(
                pid,
                {
                    "pid": pid,
                    "kinds": [],
                    "used_gpu_memory_bytes": int(getattr(process, "usedGpuMemory", 0)),
                },
            )
            record["kinds"].append(process_kind)
            try:
                name = module.nvmlSystemGetProcessName(pid)
                record["name"] = (
                    name.decode("utf-8", errors="replace") if isinstance(name, bytes) else str(name)
                )
            except module.NVMLError:
                record["name"] = "process_exited_during_snapshot"
    return [records[pid] for pid in sorted(records)]


def inspect_assigned_gpu() -> dict[str, Any]:
    """Inspect only CUDA ordinal 0, the sole device exposed by Slurm."""

    import pynvml
    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ProbeValidationError(
            "the Slurm probe requires exactly one CUDA device visible to torch"
        )
    properties = torch.cuda.get_device_properties(0)
    if "L40S" not in properties.name:
        raise ProbeValidationError(f"expected an NVIDIA L40S, observed {properties.name!r}")
    torch_uuid = str(properties.uuid)
    nvml_uuid = torch_uuid if torch_uuid.startswith("GPU-") else f"GPU-{torch_uuid}"
    pynvml.nvmlInit()
    try:
        handle = pynvml.nvmlDeviceGetHandleByUUID(nvml_uuid.encode("ascii"))
        observed_uuid = pynvml.nvmlDeviceGetUUID(handle)
        if isinstance(observed_uuid, bytes):
            observed_uuid = observed_uuid.decode("ascii")
        if str(observed_uuid) != nvml_uuid:
            raise ProbeValidationError(
                f"torch/NVML UUID mismatch: torch={nvml_uuid}, nvml={observed_uuid}"
            )
        processes = _nvml_process_records(pynvml, handle)
        foreign = [record for record in processes if record["pid"] != os.getpid()]
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        driver = pynvml.nvmlSystemGetDriverVersion()
        if isinstance(driver, bytes):
            driver = driver.decode("ascii", errors="replace")
        return {
            "status": "PASS" if not foreign else "FAIL",
            "cuda_ordinal_inspected": 0,
            "only_assigned_visible_gpu_inspected": True,
            "name": properties.name,
            "uuid": nvml_uuid,
            "compute_capability": [properties.major, properties.minor],
            "total_memory_bytes": int(properties.total_memory),
            "nvml_total_memory_bytes": int(memory.total),
            "nvml_free_memory_bytes": int(memory.free),
            "driver_version": str(driver),
            "torch_version": torch.__version__,
            "torch_cuda_version": torch.version.cuda,
            "processes": processes,
            "foreign_processes": foreign,
        }
    finally:
        pynvml.nvmlShutdown()


def _gpu_inspector_entry(output_path: Path) -> int:
    report: dict[str, Any]
    exit_code = 1
    try:
        report = inspect_assigned_gpu()
        if report["status"] == "PASS":
            exit_code = 0
    except BaseException as error:
        report = {
            "status": "FAIL",
            "error_type": type(error).__name__,
            "error": str(error),
        }
        traceback.print_exc()
    try:
        write_canonical_json(output_path, report)
    except BaseException:
        traceback.print_exc()
        return 2
    return exit_code


def _run_gpu_inspector(artifact_dir: Path, boundary: str) -> dict[str, Any]:
    """Inspect in a short-lived child so its CUDA context is released."""

    if boundary not in {"pre", "post"}:
        raise ProbeValidationError(f"invalid GPU inspection boundary {boundary!r}")
    result_path = artifact_dir / f"gpu-{boundary}.json"
    stdout_path = artifact_dir / f"gpu-{boundary}.stdout.log"
    stderr_path = artifact_dir / f"gpu-{boundary}.stderr.log"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--gpu-inspect-output",
        str(result_path),
    ]
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            completed = subprocess.run(
                command,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                timeout=120,
                env=dict(os.environ),
            )
    except subprocess.TimeoutExpired:
        return {
            "status": "FAIL",
            "error_type": "TimeoutExpired",
            "error": "assigned-GPU inspector exceeded 120 seconds",
        }
    if not result_path.is_file():
        return {
            "status": "FAIL",
            "error_type": "GPUInspectorArtifactMissing",
            "error": "assigned-GPU inspector produced no canonical JSON",
            "return_code": completed.returncode,
        }
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "status": "FAIL",
            "error_type": type(error).__name__,
            "error": f"cannot read assigned-GPU inspector result: {error}",
            "return_code": completed.returncode,
        }
    result["inspector_process"] = {
        "return_code": completed.returncode,
        "stdout_artifact": stdout_path.name,
        "stderr_artifact": stderr_path.name,
        "result_artifact": result_path.name,
        "short_lived_process_releases_cuda_context_before_next_phase": True,
    }
    if completed.returncode != 0:
        result["status"] = "FAIL"
    return result


def _engine_arguments(mode: str) -> dict[str, Any]:
    if mode not in {"native", "yarn"}:
        raise ProbeValidationError(f"unsupported worker mode {mode!r}")
    arguments: dict[str, Any] = {
        "model": str(EXPECTED_MODEL_SNAPSHOT),
        "tokenizer": str(EXPECTED_MODEL_SNAPSHOT),
        "skip_tokenizer_init": True,
        "trust_remote_code": False,
        "dtype": "bfloat16",
        "tensor_parallel_size": 1,
        "max_model_len": 40960 if mode == "native" else MAX_MODEL_LEN,
        "gpu_memory_utilization": 0.92,
        "enforce_eager": True,
        "seed": 0,
        "disable_custom_all_reduce": True,
        "max_num_seqs": 1,
        "max_num_batched_tokens": SHORT_PROMPT_TOKENS,
        "enable_chunked_prefill": True,
        "enable_prefix_caching": False,
        "swap_space": 0,
        "disable_log_stats": True,
    }
    if mode == "yarn":
        arguments["hf_overrides"] = {"rope_scaling": dict(YARN_SCALING)}
    return arguments


def _normalized_rope_scaling(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ProbeValidationError(f"runtime rope_scaling is not a mapping: {value!r}")
    return {
        "rope_type": value.get("rope_type", value.get("type")),
        "factor": value.get("factor"),
        "original_max_position_embeddings": value.get("original_max_position_embeddings"),
    }


def _run_generation_case(llm: Any, case_name: str, prompt_tokens: int) -> dict[str, Any]:
    from vllm import SamplingParams
    from vllm.inputs import TokensPrompt

    prompt = TokensPrompt(prompt_token_ids=[PROMPT_TOKEN_ID] * prompt_tokens)
    sampling = SamplingParams(
        temperature=0.0,
        max_tokens=MAX_OUTPUT_TOKENS,
        seed=0,
        ignore_eos=True,
        detokenize=False,
        skip_special_tokens=False,
    )
    started = time.monotonic_ns()
    outputs = llm.generate(prompt, sampling, use_tqdm=False)
    elapsed_ns = time.monotonic_ns() - started
    if len(outputs) != 1 or len(outputs[0].outputs) != 1:
        raise ProbeValidationError(f"{case_name}: expected one request and one completion output")
    request_output = outputs[0]
    token_ids = list(request_output.outputs[0].token_ids)
    observed_prompt_tokens = len(request_output.prompt_token_ids)
    if observed_prompt_tokens != prompt_tokens:
        raise ProbeValidationError(
            f"{case_name}: prompt length changed: {observed_prompt_tokens} != {prompt_tokens}"
        )
    if len(token_ids) != MAX_OUTPUT_TOKENS:
        raise ProbeValidationError(
            f"{case_name}: expected one generated token, observed {len(token_ids)}"
        )
    return {
        "case": case_name,
        "status": "PASS",
        "prompt_token_id": PROMPT_TOKEN_ID,
        "prompt_tokens": observed_prompt_tokens,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "generated_token_ids": token_ids,
        "generated_tokens": len(token_ids),
        "total_tokens": observed_prompt_tokens + len(token_ids),
        "finished": bool(request_output.finished),
        "finish_reason": request_output.outputs[0].finish_reason,
        "telemetry": {
            "elapsed_ns": elapsed_ns,
            "classification": "functional_run_wall_clock_telemetry_not_calibration",
            "performance_comparison_allowed": False,
        },
    }


def _normalized_runtime_layer_name(layer_name: str) -> str:
    """Map vLLM's concrete Attention module name to the model-layer name.

    Qwen3 constructs ``Attention`` at ``<self_attn prefix>.attn`` while the
    source-locked layout names the owning self-attention layer.  No other
    rewrite is allowed, so an unexpected runtime topology fails closed.
    """

    suffix = ".attn"
    return layer_name[: -len(suffix)] if layer_name.endswith(suffix) else layer_name


def audit_runtime_kv_cache_specs(
    worker_specs: object,
    *,
    layout_path: Path,
) -> dict[str, Any]:
    """Compare actual worker ``FullAttentionSpec`` objects with kv-layout.json.

    This is a runtime structure/byte differential, not a CUDA allocator or
    timing measurement.  The current physical probe is deliberately TP1/PP1,
    so it rejects multiple worker-spec dictionaries instead of guessing a rank
    mapping.
    """

    if not isinstance(worker_specs, list) or len(worker_specs) != 1:
        raise ProbeValidationError(
            "runtime KV CacheSpec audit requires exactly one TP1 worker result"
        )
    runtime_by_name = worker_specs[0]
    if not isinstance(runtime_by_name, dict) or not runtime_by_name:
        raise ProbeValidationError("runtime worker returned no KV CacheSpec entries")
    if any(not isinstance(name, str) or not name for name in runtime_by_name):
        raise ProbeValidationError("runtime KV CacheSpec layer names must be strings")

    if layout_path.is_symlink() or not layout_path.is_file():
        raise ProbeValidationError(f"KV layout is missing or unsafe: {layout_path}")
    try:
        layout_document = json.loads(layout_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProbeValidationError(f"cannot load KV layout {layout_path}: {error}") from error
    if not isinstance(layout_document, dict) or layout_document.get("schema") != (
        "moonkvsim.kv_layout.v1"
    ):
        raise ProbeValidationError("runtime KV CacheSpec audit received a wrong layout schema")
    stage_rank_layouts = layout_document.get("stage_rank_layouts")
    if not isinstance(stage_rank_layouts, list) or len(stage_rank_layouts) != 1:
        raise ProbeValidationError("runtime KV CacheSpec audit requires one TP1/PP1 layout")
    stage = stage_rank_layouts[0]
    if not isinstance(stage, dict):
        raise ProbeValidationError("runtime KV layout stage is not an object")
    block = stage.get("block")
    cache_spec = stage.get("cache_spec")
    expected_names = stage.get("layer_names")
    if (
        not isinstance(block, dict)
        or not isinstance(cache_spec, dict)
        or not isinstance(expected_names, list)
        or not expected_names
        or not all(isinstance(name, str) and name for name in expected_names)
    ):
        raise ProbeValidationError("runtime KV layout lacks block/cache/layer data")

    normalized_runtime: dict[str, tuple[str, Any]] = {}
    for runtime_name, spec in runtime_by_name.items():
        normalized_name = _normalized_runtime_layer_name(runtime_name)
        if normalized_name in normalized_runtime:
            raise ProbeValidationError(
                f"runtime KV layer normalization collided at {normalized_name}"
            )
        normalized_runtime[normalized_name] = (runtime_name, spec)
    if set(normalized_runtime) != set(expected_names):
        missing = sorted(set(expected_names) - set(normalized_runtime))
        extra = sorted(set(normalized_runtime) - set(expected_names))
        raise ProbeValidationError(
            f"runtime/layout KV layer names diverged: missing={missing}, extra={extra}"
        )

    expected_values = {
        "block_size": cache_spec.get("block_size_tokens"),
        "num_kv_heads": cache_spec.get("local_num_kv_heads"),
        "head_size": cache_spec.get("head_size_k"),
        "head_size_v": cache_spec.get("head_size_v"),
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in expected_values.values()
    ):
        raise ProbeValidationError("layout cache dimensions are not positive integers")
    if cache_spec.get("kind") != "full_attention":
        raise ProbeValidationError("physical Qwen3 probe requires full-attention CacheSpec")
    if cache_spec.get("kv_dtype") != "bfloat16" or cache_spec.get("kv_quant_mode") != "none":
        raise ProbeValidationError("physical Qwen3 probe requires unquantized bfloat16 KV")

    layer_records: list[dict[str, Any]] = []
    aggregate_real_page_size = 0
    aggregate_page_size = 0
    for expected_name in expected_names:
        runtime_name, spec = normalized_runtime[expected_name]
        if type(spec).__name__ != "FullAttentionSpec":
            raise ProbeValidationError(
                f"{runtime_name}: expected FullAttentionSpec, observed {type(spec).__name__}"
            )
        observed_values = {
            field_name: getattr(spec, field_name, None) for field_name in expected_values
        }
        if observed_values != expected_values:
            raise ProbeValidationError(
                f"{runtime_name}: CacheSpec dimensions diverged: "
                f"observed={observed_values}, expected={expected_values}"
            )
        dtype_name = str(getattr(spec, "dtype", ""))
        quant_mode = getattr(spec, "kv_quant_mode", None)
        quant_name = getattr(quant_mode, "name", None)
        if dtype_name != "torch.bfloat16" or quant_name != "NONE":
            raise ProbeValidationError(
                f"{runtime_name}: unexpected dtype/quant mode {dtype_name}/{quant_name}"
            )
        if (
            getattr(spec, "page_size_padded", None) is not None
            or getattr(spec, "sliding_window", None) is not None
            or getattr(spec, "attention_chunk_size", None) is not None
        ):
            raise ProbeValidationError(
                f"{runtime_name}: padded/sliding/chunked CacheSpec is outside this layout"
            )
        real_page_size = getattr(spec, "real_page_size_bytes", None)
        page_size = getattr(spec, "page_size_bytes", None)
        if (
            isinstance(real_page_size, bool)
            or not isinstance(real_page_size, int)
            or real_page_size <= 0
            or isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or page_size < real_page_size
        ):
            raise ProbeValidationError(f"{runtime_name}: invalid runtime page byte counts")
        aggregate_real_page_size += real_page_size
        aggregate_page_size += page_size
        layer_records.append(
            {
                "layout_layer_name": expected_name,
                "runtime_layer_name": runtime_name,
                "spec_type": type(spec).__name__,
                "block_size_tokens": observed_values["block_size"],
                "local_num_kv_heads": observed_values["num_kv_heads"],
                "head_size_k": observed_values["head_size"],
                "head_size_v": observed_values["head_size_v"],
                "dtype": dtype_name,
                "kv_quant_mode": str(quant_name).lower(),
                "real_page_size_bytes": real_page_size,
                "page_size_bytes": page_size,
            }
        )

    expected_real = block.get("payload_bytes")
    expected_page = block.get("requested_bytes")
    if aggregate_real_page_size != expected_real or aggregate_page_size != expected_page:
        raise ProbeValidationError(
            "runtime/layout aggregate page bytes diverged: "
            f"real={aggregate_real_page_size}/{expected_real}, "
            f"page={aggregate_page_size}/{expected_page}"
        )
    return {
        "status": "PASS",
        "classification": "physical_runtime_cache_spec_structure_and_bytes_only",
        "performance_or_allocator_measurement": False,
        "layout_path": str(layout_path.resolve()),
        "layout_sha256": sha256_file(layout_path),
        "layout_fingerprint": layout_document.get("fingerprint"),
        "worker_count": 1,
        "layer_count": len(layer_records),
        "aggregate_real_page_size_bytes": aggregate_real_page_size,
        "aggregate_page_size_bytes": aggregate_page_size,
        "layout_allocated_bytes": block.get("allocated_bytes"),
        "layers": layer_records,
    }


def run_engine_worker(mode: str, *, repository_root: Path) -> dict[str, Any]:
    """Load one engine configuration and execute its exact case set."""

    import torch
    import vllm
    from vllm import LLM

    if vllm.__version__ != EXPECTED_VLLM_VERSION:
        raise ProbeValidationError(
            f"worker imported vLLM {vllm.__version__}, expected {EXPECTED_VLLM_VERSION}"
        )
    arguments = _engine_arguments(mode)
    engine_started = time.monotonic_ns()
    llm = LLM(**arguments)
    engine_load_ns = time.monotonic_ns() - engine_started
    vllm_config = llm.llm_engine.vllm_config
    observed_max_len = int(vllm_config.model_config.max_model_len)
    expected_max_len = int(arguments["max_model_len"])
    if observed_max_len != expected_max_len:
        raise ProbeValidationError(
            f"runtime max_model_len mismatch: {observed_max_len} != {expected_max_len}"
        )
    observed_rope = _normalized_rope_scaling(
        getattr(vllm_config.model_config.hf_config, "rope_scaling", None)
    )
    expected_rope = None if mode == "native" else YARN_SCALING
    if observed_rope != expected_rope:
        raise ProbeValidationError(
            f"runtime rope_scaling mismatch: {observed_rope!r} != {expected_rope!r}"
        )

    repository_root = repository_root.resolve(strict=True)
    layout_relative = NATIVE_KV_LAYOUT_RELATIVE if mode == "native" else YARN_KV_LAYOUT_RELATIVE
    runtime_kv_cache_spec_audit = audit_runtime_kv_cache_specs(
        llm.llm_engine.collective_rpc("get_kv_cache_spec"),
        layout_path=repository_root / layout_relative,
    )

    case_specs = (
        [("native_short", SHORT_PROMPT_TOKENS)]
        if mode == "native"
        else [
            ("yarn_short", SHORT_PROMPT_TOKENS),
            ("yarn_exact_128k", LONG_PROMPT_TOKENS),
        ]
    )
    cases = [_run_generation_case(llm, name, length) for name, length in case_specs]
    cache_config = vllm_config.cache_config
    result = {
        "schema": WORKER_SCHEMA,
        "status": "PASS",
        "mode": mode,
        "vllm_version": vllm.__version__,
        "vllm_path": str(Path(vllm.__file__).resolve()),
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "engine_arguments": arguments,
        "runtime_engine_config": {
            "max_model_len": observed_max_len,
            "rope_scaling": observed_rope,
            "dtype": str(vllm_config.model_config.dtype),
            "block_size": getattr(cache_config, "block_size", None),
            "cache_dtype": getattr(cache_config, "cache_dtype", None),
            "gpu_memory_utilization": getattr(cache_config, "gpu_memory_utilization", None),
            "num_gpu_blocks": getattr(cache_config, "num_gpu_blocks", None),
        },
        "runtime_kv_cache_spec_audit": runtime_kv_cache_spec_audit,
        "cases": cases,
        "telemetry": {
            "engine_load_ns": engine_load_ns,
            "classification": "functional_run_wall_clock_telemetry_not_calibration",
            "performance_comparison_allowed": False,
        },
    }
    return result


def _worker_entry(mode: str, output_path: Path, repository_root: Path) -> int:
    report: dict[str, Any] = {
        "schema": WORKER_SCHEMA,
        "status": "FAIL",
        "mode": mode,
        "errors": [],
    }
    exit_code = 1
    try:
        report = run_engine_worker(mode, repository_root=repository_root)
        exit_code = 0
    except BaseException as error:
        report["errors"] = [
            {
                "type": type(error).__name__,
                "message": str(error),
            }
        ]
        traceback.print_exc()
    try:
        write_canonical_json(output_path, report)
    except BaseException:
        traceback.print_exc()
        return 2
    return exit_code


def _run_worker_process(
    *,
    mode: str,
    artifact_dir: Path,
    repository_root: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    result_path = artifact_dir / f"worker-{mode}.json"
    stdout_path = artifact_dir / f"worker-{mode}.stdout.log"
    stderr_path = artifact_dir / f"worker-{mode}.stderr.log"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        mode,
        "--worker-output",
        str(result_path),
        "--repository-root",
        str(repository_root),
    ]
    started = time.monotonic_ns()
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            completed = subprocess.run(
                command,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout_seconds,
                env=dict(os.environ),
            )
        return_code: int | None = completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        return_code = None
        timed_out = True
    elapsed_ns = time.monotonic_ns() - started
    if not result_path.is_file():
        return {
            "schema": WORKER_SCHEMA,
            "status": "FAIL",
            "mode": mode,
            "errors": [
                {
                    "type": "WorkerArtifactMissing",
                    "message": "worker did not produce its canonical result JSON",
                }
            ],
            "process": {
                "return_code": return_code,
                "timed_out": timed_out,
                "elapsed_ns": elapsed_ns,
            },
        }
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        result = {
            "schema": WORKER_SCHEMA,
            "status": "FAIL",
            "mode": mode,
            "errors": [
                {
                    "type": type(error).__name__,
                    "message": f"cannot read worker result: {error}",
                }
            ],
        }
    result["process"] = {
        "return_code": return_code,
        "timed_out": timed_out,
        "elapsed_ns": elapsed_ns,
        "stdout_artifact": stdout_path.name,
        "stderr_artifact": stderr_path.name,
        "result_artifact": result_path.name,
    }
    if return_code != 0 or timed_out:
        result["status"] = "FAIL"
    return result


def evaluate_functional_status(manifest: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Fail closed unless all pins, GPU checks, and exact cases passed."""

    failures: list[str] = []
    source = manifest.get("source_verification", {})
    if not isinstance(source, Mapping) or source.get("status") != "PASS":
        failures.append("source_verification_not_pass")
    gpu = manifest.get("gpu", {})
    if not isinstance(gpu, Mapping):
        failures.append("gpu_record_missing")
    else:
        for boundary in ("pre", "post"):
            record = gpu.get(boundary, {})
            if not isinstance(record, Mapping) or record.get("status") != "PASS":
                failures.append(f"gpu_{boundary}_process_check_not_pass")

    worker_results = manifest.get("worker_results", {})
    if not isinstance(worker_results, Mapping):
        failures.append("worker_results_missing")
        worker_results = {}
    observed_cases: dict[str, Mapping[str, Any]] = {}
    for mode in ("native", "yarn"):
        worker = worker_results.get(mode, {})
        if not isinstance(worker, Mapping) or worker.get("status") != "PASS":
            failures.append(f"worker_{mode}_not_pass")
            continue
        cache_spec_audit = worker.get("runtime_kv_cache_spec_audit", {})
        if not isinstance(cache_spec_audit, Mapping) or cache_spec_audit.get("status") != "PASS":
            failures.append(f"worker_{mode}_runtime_kv_cache_spec_not_pass")
        cases = worker.get("cases", [])
        if not isinstance(cases, Sequence):
            failures.append(f"worker_{mode}_cases_missing")
            continue
        for case in cases:
            if isinstance(case, Mapping) and isinstance(case.get("case"), str):
                observed_cases[str(case["case"])] = case

    expected = {
        "native_short": SHORT_PROMPT_TOKENS + MAX_OUTPUT_TOKENS,
        "yarn_short": SHORT_PROMPT_TOKENS + MAX_OUTPUT_TOKENS,
        "yarn_exact_128k": MAX_MODEL_LEN,
    }
    for case_name, total_tokens in expected.items():
        case = observed_cases.get(case_name)
        if case is None:
            failures.append(f"case_{case_name}_missing")
        elif case.get("status") != "PASS" or case.get("total_tokens") != total_tokens:
            failures.append(f"case_{case_name}_not_exact_pass")
    return ("PASS" if not failures else "FAIL", failures)


def _short_context_comparison(worker_results: Mapping[str, Any]) -> dict[str, Any]:
    def find_case(mode: str, name: str) -> Mapping[str, Any] | None:
        worker = worker_results.get(mode, {})
        if not isinstance(worker, Mapping):
            return None
        for raw in worker.get("cases", []):
            if isinstance(raw, Mapping) and raw.get("case") == name:
                return raw
        return None

    native = find_case("native", "native_short")
    yarn = find_case("yarn", "yarn_short")
    both_pass = bool(
        native and yarn and native.get("status") == "PASS" and yarn.get("status") == "PASS"
    )
    return {
        "matched_prompt_token_ids": True,
        "prompt_tokens_each": SHORT_PROMPT_TOKENS,
        "native_functional_pass": bool(native and native.get("status") == "PASS"),
        "yarn_functional_pass": bool(yarn and yarn.get("status") == "PASS"),
        "generated_token_ids_equal": bool(
            both_pass
            and native is not None
            and yarn is not None
            and native.get("generated_token_ids") == yarn.get("generated_token_ids")
        ),
        "generated_token_equality_is_not_a_quality_or_performance_gate": True,
        "short_context_quality_validation": "not_run",
    }


def run_orchestrator(
    *,
    lock_path: Path,
    artifact_dir: Path,
    output_path: Path,
    worker_timeout_seconds: int,
) -> int:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "FAIL",
        "functional_validation": "FAIL",
        "errors": [],
        "probe_started_unix_ns": time.time_ns(),
        "evidence_boundary": {
            "class": "physical_functional_diagnostic",
            "evidence_level_ceiling": "physical_functional_only",
            "functional_validation_only": True,
            "latency_fields_are_telemetry_only": True,
            "calibration": False,
            "performance_result": False,
            "short_context_quality_validation": False,
            "formal_experiment_result": False,
            "source_lock_updated_by_probe": False,
        },
        "offline_environment": {
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
            "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
            "HF_DATASETS_OFFLINE": os.environ.get("HF_DATASETS_OFFLINE"),
        },
    }
    exit_code = 1
    try:
        if manifest["offline_environment"] != {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
        }:
            raise ProbeValidationError("all Hugging Face/Transformers offline flags must be 1")
        lock = load_source_lock(lock_path)
        manifest["probe_plan"] = build_probe_plan(lock)
        manifest["slurm"] = validate_slurm_environment(os.environ)
        manifest["launch_provenance"] = validate_launch_provenance(artifact_dir, os.environ)
        manifest["source_verification"] = verify_pinned_inputs(lock_path, lock)
        pre_gpu = _run_gpu_inspector(artifact_dir, "pre")
        manifest["gpu"] = {"pre": pre_gpu}
        if pre_gpu["status"] != "PASS":
            raise ProbeValidationError(
                "foreign GPU process detected on the assigned GPU before model launch"
            )

        worker_results: dict[str, Any] = {}
        for mode in ("native", "yarn"):
            worker_results[mode] = _run_worker_process(
                mode=mode,
                artifact_dir=artifact_dir,
                repository_root=lock_path.resolve().parent.parent,
                timeout_seconds=(
                    min(worker_timeout_seconds, 900) if mode == "native" else worker_timeout_seconds
                ),
            )
            if worker_results[mode].get("status") != "PASS":
                break
        manifest["worker_results"] = worker_results
    except BaseException as error:
        manifest["errors"].append(
            {
                "type": type(error).__name__,
                "message": str(error),
            }
        )
        traceback.print_exc()
    finally:
        if "gpu" in manifest:
            try:
                manifest["gpu"]["post"] = _run_gpu_inspector(artifact_dir, "post")
            except BaseException as error:
                manifest["gpu"]["post"] = {
                    "status": "FAIL",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                traceback.print_exc()

    worker_results = manifest.get("worker_results", {})
    if isinstance(worker_results, Mapping):
        manifest["matched_short_context"] = _short_context_comparison(worker_results)
    status, failures = evaluate_functional_status(manifest)
    manifest["status"] = status
    manifest["functional_validation"] = status
    manifest["validation_failures"] = failures
    manifest["probe_finished_unix_ns"] = time.time_ns()
    if status == "PASS":
        exit_code = 0
    try:
        write_canonical_json(output_path, manifest)
    except BaseException:
        traceback.print_exc()
        return 2
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "status": status,
                "result": str(output_path),
                "performance_result": False,
            },
            sort_keys=True,
        )
    )
    return exit_code


def publish_staging_no_clobber(staging: Path, final: Path) -> None:
    """Publish a staged flat artifact directory without clobbering a prior run.

    The destination directory is acquired with an exclusive mkdir.  A durable
    incomplete marker remains until every staged leaf has been moved and fsynced;
    the complete marker is written before that incomplete marker is removed.
    Consumers must require COMPLETE and reject INCOMPLETE.  This works on the
    project NFS where renameat2(RENAME_NOREPLACE) is unavailable.
    """

    staging = staging.absolute()
    final = final.absolute()
    if staging.parent != final.parent:
        raise ProbeValidationError("staging and final directories must be siblings")
    if not staging.is_dir() or staging.is_symlink():
        raise ProbeValidationError(f"invalid staging directory: {staging}")
    if final.exists() or final.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing physical run: {final}")
    leaves = sorted(staging.iterdir(), key=lambda path: path.name)
    if not leaves or any(not leaf.is_file() or leaf.is_symlink() for leaf in leaves):
        raise ProbeValidationError("staging must contain only regular artifact files")
    checksum_path = staging / "SHA256SUMS"
    if not checksum_path.is_file():
        raise ProbeValidationError("staging lacks SHA256SUMS")
    checksum_sha256 = sha256_file(checksum_path)

    os.mkdir(final, 0o750)
    incomplete = final / "PUBLICATION_INCOMPLETE"
    complete = final / "PUBLICATION_COMPLETE.json"
    try:
        with incomplete.open("xb") as stream:
            stream.write(b"publication in progress; do not consume\n")
            stream.flush()
            os.fsync(stream.fileno())
        for leaf in leaves:
            os.rename(leaf, final / leaf.name)
        directory_fd = os.open(final, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        write_canonical_json(
            complete,
            {
                "schema": "moonkvsim.physical_probe_publication.v1",
                "status": "COMPLETE",
                "no_clobber": True,
                "strategy": "exclusive_destination_directory_and_complete_marker",
                "sha256sums_sha256": checksum_sha256,
            },
        )
        incomplete.unlink()
        staging.rmdir()
        directory_fd = os.open(final, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        parent_fd = os.open(final.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except BaseException:
        # Leave INCOMPLETE and all already moved audit files in place.  Never
        # delete or overwrite a failed physical run publication.
        raise


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-lock",
        type=Path,
        default=Path("reference/source-lock.json"),
    )
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", choices=("native", "yarn"))
    parser.add_argument("--worker-output", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--gpu-inspect-output", type=Path)
    parser.add_argument("--worker-timeout-seconds", type=int, default=5400)
    parser.add_argument("--publish-staging", type=Path)
    parser.add_argument("--publish-final", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.publish_staging is not None or args.publish_final is not None:
        if args.publish_staging is None or args.publish_final is None:
            raise SystemExit("--publish-staging and --publish-final must be used together")
        publish_staging_no_clobber(args.publish_staging, args.publish_final)
        return 0
    if args.worker is not None:
        if args.worker_output is None or args.repository_root is None:
            raise SystemExit("--worker requires --worker-output and --repository-root")
        return _worker_entry(
            args.worker,
            args.worker_output,
            args.repository_root,
        )
    if args.gpu_inspect_output is not None:
        return _gpu_inspector_entry(args.gpu_inspect_output)
    if args.artifact_dir is None or args.output is None:
        raise SystemExit("orchestrator mode requires --artifact-dir and --output")
    if args.worker_timeout_seconds <= 0:
        raise SystemExit("--worker-timeout-seconds must be positive")
    return run_orchestrator(
        lock_path=args.source_lock,
        artifact_dir=args.artifact_dir,
        output_path=args.output,
        worker_timeout_seconds=args.worker_timeout_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
