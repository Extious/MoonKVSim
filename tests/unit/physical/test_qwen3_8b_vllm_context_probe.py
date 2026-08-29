from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROBE_SCRIPT = PROJECT_ROOT / "scripts" / "physical" / "qwen3_8b_vllm_context_probe.py"
SBATCH_SCRIPT = PROJECT_ROOT / "scripts" / "physical" / "qwen3_8b_vllm_context_probe.sbatch"
LOCK_PATH = PROJECT_ROOT / "reference" / "source-lock.json"
MODULE_SPEC = importlib.util.spec_from_file_location("qwen_context_probe", PROBE_SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
PROBE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = PROBE
MODULE_SPEC.loader.exec_module(PROBE)


def _load_lock() -> dict[str, object]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _passing_manifest() -> dict[str, object]:
    return {
        "source_verification": {"status": "PASS"},
        "gpu": {"pre": {"status": "PASS"}, "post": {"status": "PASS"}},
        "worker_results": {
            "native": {
                "status": "PASS",
                "runtime_kv_cache_spec_audit": {"status": "PASS"},
                "cases": [
                    {
                        "case": "native_short",
                        "status": "PASS",
                        "total_tokens": 8193,
                    }
                ],
            },
            "yarn": {
                "status": "PASS",
                "runtime_kv_cache_spec_audit": {"status": "PASS"},
                "cases": [
                    {
                        "case": "yarn_short",
                        "status": "PASS",
                        "total_tokens": 8193,
                    },
                    {
                        "case": "yarn_exact_128k",
                        "status": "PASS",
                        "total_tokens": 131072,
                    },
                ],
            },
        },
    }


class _QuantMode(Enum):
    NONE = "none"


@dataclass
class FullAttentionSpec:
    block_size: int = 16
    num_kv_heads: int = 8
    head_size: int = 128
    head_size_v: int = 128
    dtype: str = "torch.bfloat16"
    kv_quant_mode: _QuantMode = _QuantMode.NONE
    page_size_padded: int | None = None
    sliding_window: int | None = None
    attention_chunk_size: int | None = None

    @property
    def real_page_size_bytes(self) -> int:
        return 65_536

    @property
    def page_size_bytes(self) -> int:
        return self.real_page_size_bytes


def test_checked_in_plan_freezes_exact_native_yarn_and_128k_cases() -> None:
    plan = PROBE.build_probe_plan(_load_lock())

    assert plan["cases"] == {
        "native_short": {
            "mode": "native",
            "prompt_tokens": 8192,
            "max_tokens": 1,
            "total_tokens": 8193,
        },
        "yarn_short": {
            "mode": "yarn",
            "prompt_tokens": 8192,
            "max_tokens": 1,
            "total_tokens": 8193,
        },
        "yarn_exact_128k": {
            "mode": "yarn",
            "prompt_tokens": 131071,
            "max_tokens": 1,
            "total_tokens": 131072,
        },
    }
    assert plan["engine_processes"][1]["rope_scaling"] == {
        "rope_type": "yarn",
        "factor": 4.0,
        "original_max_position_embeddings": 32768,
    }
    assert plan["evidence_boundary"] == {
        "class": "physical_functional_diagnostic",
        "evidence_level_ceiling": "physical_functional_only",
        "functional_validation_only": True,
        "latency_fields_are_telemetry_only": True,
        "calibration": False,
        "performance_result": False,
        "short_context_quality_validation": False,
        "formal_experiment_result": False,
    }


def test_plan_rejects_a_changed_yarn_candidate_or_premature_ready_state() -> None:
    changed = deepcopy(_load_lock())
    context = changed["model_tokenizer"]["context_128k"]  # type: ignore[index]
    context["rope_scaling"]["factor"] = 2.0  # type: ignore[index]
    context["physical_validation"]["completed"] = True  # type: ignore[index]

    with pytest.raises(PROBE.ProbeValidationError, match="probe pin mismatch"):
        PROBE.build_probe_plan(changed)


def test_slurm_environment_requires_one_visible_device_and_short_partition() -> None:
    record = PROBE.validate_slurm_environment(
        {
            "SLURM_JOB_ID": "12345",
            "SLURM_JOB_PARTITION": "short",
            "SLURM_JOB_GPUS": "3",
            "CUDA_VISIBLE_DEVICES": "3",
        }
    )
    assert record["job_id"] == "12345"
    assert record["cuda_visible_devices"] == "3"

    with pytest.raises(PROBE.ProbeValidationError, match="exactly one"):
        PROBE.validate_slurm_environment({"SLURM_JOB_ID": "12345", "CUDA_VISIBLE_DEVICES": "0,1"})
    with pytest.raises(PROBE.ProbeValidationError, match="partition short"):
        PROBE.validate_slurm_environment(
            {
                "SLURM_JOB_ID": "12345",
                "SLURM_JOB_PARTITION": "long",
                "CUDA_VISIBLE_DEVICES": "0",
            }
        )


def test_launch_provenance_rejects_unstaged_or_unpinned_code(tmp_path: Path) -> None:
    with pytest.raises(PROBE.ProbeValidationError, match="staged"):
        PROBE.validate_launch_provenance(tmp_path, {})


def test_manifest_passes_only_when_all_three_exact_cases_and_gpu_checks_pass() -> None:
    status, failures = PROBE.evaluate_functional_status(_passing_manifest())
    assert status == "PASS"
    assert failures == []

    failed = _passing_manifest()
    failed["worker_results"]["yarn"]["cases"][1]["total_tokens"] = 131071  # type: ignore[index]
    failed["gpu"]["post"] = {"status": "FAIL"}  # type: ignore[index]
    status, failures = PROBE.evaluate_functional_status(failed)
    assert status == "FAIL"
    assert "case_yarn_exact_128k_not_exact_pass" in failures
    assert "gpu_post_process_check_not_pass" in failures

    missing_runtime_spec = _passing_manifest()
    del missing_runtime_spec["worker_results"]["native"][  # type: ignore[index]
        "runtime_kv_cache_spec_audit"
    ]
    status, failures = PROBE.evaluate_functional_status(missing_runtime_spec)
    assert status == "FAIL"
    assert "worker_native_runtime_kv_cache_spec_not_pass" in failures


def test_runtime_cache_spec_audit_matches_actual_vllm_object_contract() -> None:
    layout_path = PROJECT_ROOT / "configs/resolved/qwen3-8b/native-tp1-pp1/kv-layout.json"
    worker_specs = [
        {f"model.layers.{index}.self_attn.attn": FullAttentionSpec() for index in range(36)}
    ]

    audit = PROBE.audit_runtime_kv_cache_specs(
        worker_specs,
        layout_path=layout_path,
    )

    assert audit["status"] == "PASS"
    assert audit["layer_count"] == 36
    assert audit["aggregate_real_page_size_bytes"] == 2_359_296
    assert audit["aggregate_page_size_bytes"] == 2_359_296
    assert audit["layout_allocated_bytes"] == 2_359_296


def test_runtime_cache_spec_audit_fails_closed_on_shape_or_layer_drift() -> None:
    layout_path = PROJECT_ROOT / "configs/resolved/qwen3-8b/native-tp1-pp1/kv-layout.json"
    worker_specs = [
        {f"model.layers.{index}.self_attn.attn": FullAttentionSpec() for index in range(36)}
    ]
    worker_specs[0]["model.layers.0.self_attn.attn"].num_kv_heads = 4
    with pytest.raises(PROBE.ProbeValidationError, match="dimensions diverged"):
        PROBE.audit_runtime_kv_cache_specs(worker_specs, layout_path=layout_path)

    worker_specs[0]["model.layers.0.self_attn.attn"].num_kv_heads = 8
    worker_specs[0]["unexpected.attn"] = worker_specs[0].pop("model.layers.0.self_attn.attn")
    with pytest.raises(PROBE.ProbeValidationError, match="layer names diverged"):
        PROBE.audit_runtime_kv_cache_specs(worker_specs, layout_path=layout_path)


def test_canonical_json_is_stable_and_exclusive(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    PROBE.write_canonical_json(output, {"z": 1, "a": "物理"})
    expected = b'{"a":"\xe7\x89\xa9\xe7\x90\x86","z":1}\n'
    assert output.read_bytes() == expected

    with pytest.raises(FileExistsError):
        PROBE.write_canonical_json(output, {"status": "overwritten"})


def _make_staging(parent: Path, name: str) -> Path:
    staging = parent / name
    staging.mkdir()
    artifact = staging / "result.json"
    artifact.write_bytes(b'{"status":"FAIL"}\n')
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (staging / "SHA256SUMS").write_text(f"{checksum}  ./result.json\n", encoding="utf-8")
    return staging


def test_publication_is_no_clobber_and_has_fail_closed_markers(tmp_path: Path) -> None:
    staging = _make_staging(tmp_path, ".123.staging.fixture")
    final = tmp_path / "123"

    PROBE.publish_staging_no_clobber(staging, final)

    assert not staging.exists()
    assert (final / "PUBLICATION_COMPLETE.json").is_file()
    assert not (final / "PUBLICATION_INCOMPLETE").exists()
    assert (final / "result.json").read_bytes() == b'{"status":"FAIL"}\n'
    complete = json.loads((final / "PUBLICATION_COMPLETE.json").read_text())
    assert complete["status"] == "COMPLETE"
    assert complete["no_clobber"] is True

    second_staging = _make_staging(tmp_path, ".123.staging.second")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        PROBE.publish_staging_no_clobber(second_staging, final)
    assert second_staging.is_dir()
    assert (final / "result.json").read_bytes() == b'{"status":"FAIL"}\n'


def test_sbatch_requests_one_l40s_and_contains_no_destructive_gpu_action() -> None:
    text = SBATCH_SCRIPT.read_text(encoding="utf-8")

    assert text.count("#SBATCH --partition=short") == 1
    assert text.count("#SBATCH --constraint=l40s") == 1
    assert text.count("#SBATCH --gres=gpu:l40s:1") == 1
    assert "#SBATCH --exclusive" not in text
    assert "scancel" not in text
    assert "pkill" not in text
    assert "kill " not in text
    assert "nvidia-smi" not in text
    assert "HF_HUB_OFFLINE=1" in text
    assert "--publish-staging" in text
    assert "SHA256SUMS" in text
    assert 'scontrol write batch_script "${job_id}" "${submitted_batch_script}"' in text
    assert '"${runtime_python}" "${probe_snapshot}"' in text
    assert "MOONKVSIM_PROBE_SCRIPT_SHA256" in text
    assert "MOONKVSIM_SUBMITTED_BATCH_SCRIPT_SHA256" in text
    assert 'submitted_root="${SLURM_SUBMIT_DIR:-}"' in text
    assert 'expected_repo_root="/home/comp/zhanzhao/MoonKVSim"' in text
    assert "BASH_SOURCE" not in text
    combined = (
        text
        + PROBE_SCRIPT.read_text(encoding="utf-8")
        + (PROJECT_ROOT / "benchmark" / "physical" / "qwen3-8b-context" / "README.md").read_text(
            encoding="utf-8"
        )
    )
    assert "E3_physical" not in combined
    assert "E4" not in combined
    assert "E5" not in combined
