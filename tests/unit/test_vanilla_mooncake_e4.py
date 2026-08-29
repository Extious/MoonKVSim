from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import jsonschema
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, relative: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPOSITORY_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E4 = load_script("vanilla_mooncake_e4", "scripts/physical/vanilla_mooncake_e4.py")
BUILD = load_script(
    "vanilla_mooncake_clean_build",
    "scripts/physical/vanilla_mooncake_clean_build.py",
)
PREFLIGHT = load_script(
    "vanilla_mooncake_e4_preflight",
    "scripts/physical/vanilla_mooncake_e4_preflight.py",
)


def valid_store_config() -> dict[str, Any]:
    return {
        "metadata_server": "http://127.0.0.1:8000/metadata",
        "master_server_address": "127.0.0.1:50051",
        "protocol": "tcp",
        "device_name": "",
        "mode": "embedded",
        "global_segment_size": 8 * 1024**3,
        "local_buffer_size": 1024**3,
        "enable_offload": False,
    }


def empty_delta(*, computed_tokens: float = 4096.0) -> dict[str, Any]:
    operations = {
        operation: {
            "calls": 0.0,
            "seconds": 0.0,
            "keys": 0.0,
            "bytes": 0.0,
            "failed_keys": 0.0,
            "ok_calls": 0.0,
            "error_calls": 0.0,
        }
        for operation in ("lookup_exists", "load_get", "save_exists", "save_put")
    }
    return {
        "request": {
            "e2e_count": 1.0,
            "e2e_seconds": 1.0,
            "queue_count": 1.0,
            "queue_seconds": 0.1,
            "inference_count": 1.0,
            "inference_seconds": 0.8,
            "prefill_count": 1.0,
            "prefill_seconds": 0.7,
            "computed_tokens_count": 1.0,
            "computed_tokens": computed_tokens,
        },
        "operations": operations,
    }


def case(name: str, server: str, fingerprint: str, delta: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "server_id": server,
        "request_fingerprint": fingerprint,
        "http_status": 200,
        "metrics_delta": delta,
        "decomposition": E4.decompose_request(delta, 1.2),
    }


def passing_round(index: int = 0) -> dict[str, Any]:
    cold_delta = empty_delta()
    prime_delta = empty_delta()
    prime_delta["operations"]["save_put"].update(
        {"calls": 1.0, "ok_calls": 1.0, "bytes": 4096.0, "keys": 2.0}
    )
    reuse_delta = empty_delta(computed_tokens=16.0)
    reuse_delta["operations"]["lookup_exists"].update({"calls": 1.0, "ok_calls": 1.0, "keys": 2.0})
    reuse_delta["operations"]["load_get"].update(
        {
            "calls": 1.0,
            "ok_calls": 1.0,
            "bytes": 4096.0,
            "keys": 2.0,
            "seconds": 0.2,
        }
    )
    record = {
        "round": index,
        "cold_reference": case("cold", "server_b", "a" * 64, cold_delta),
        "prime_on_a": case("prime", "server_a", "b" * 64, prime_delta),
        "reuse_on_b": case("reuse", "server_b", "b" * 64, reuse_delta),
    }
    record["gate_errors"] = E4.validate_round(record, 4096)
    return record


def test_store_config_accepts_tcp_embedded_dram_only() -> None:
    assert E4.validate_store_config(valid_store_config())["enable_offload"] is False


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("protocol", "rdma"),
        ("mode", "standalone-store"),
        ("enable_offload", True),
        ("global_segment_size", 0),
        ("global_segment_size", True),
        ("local_buffer_size", False),
        ("ssd_path", "/tmp/cache"),
        ("nvmeof_device", "nvme0n1"),
    ],
)
def test_store_config_rejects_non_baseline_and_bool_integer_bypass(key: str, value: object) -> None:
    config = valid_store_config()
    config[key] = value
    with pytest.raises(E4.E4Error):
        E4.validate_store_config(config)


def test_assigned_gpu_uuids_resolves_two_distinct_devices() -> None:
    rows = [
        ["0", "GPU-aaa", "RTX 4090", "0000:01:00.0", "24564", "0", "0", "30", "P8"],
        ["1", "GPU-bbb", "RTX 4090", "0000:02:00.0", "24564", "0", "0", "31", "P8"],
    ]
    assigned, records = E4.assigned_gpu_uuids(rows, "0,GPU-bbb")
    assert assigned == ["GPU-aaa", "GPU-bbb"]
    assert [row["name"] for row in records] == ["RTX 4090", "RTX 4090"]


def test_assigned_gpu_uuids_rejects_wrong_cardinality() -> None:
    rows = [["0", "GPU-aaa", "RTX 4090", "bus", "1", "0", "0", "30", "P8"]]
    with pytest.raises(E4.E4Error):
        E4.assigned_gpu_uuids(rows, "0")


def test_metrics_parser_and_non_additive_decomposition() -> None:
    raw = "\n".join(
        [
            'vllm:e2e_request_latency_seconds_count{model_name="qwen"} 1',
            'vllm:e2e_request_latency_seconds_sum{model_name="qwen"} 1.25',
            'vllm:request_queue_time_seconds_count{model_name="qwen"} 1',
            'vllm:request_queue_time_seconds_sum{model_name="qwen"} 0.1',
            'vllm:request_inference_time_seconds_count{model_name="qwen"} 1',
            'vllm:request_inference_time_seconds_sum{model_name="qwen"} 1.0',
            'vllm:request_prefill_time_seconds_count{model_name="qwen"} 1',
            'vllm:request_prefill_time_seconds_sum{model_name="qwen"} 0.8',
            'vllm:request_prefill_kv_computed_tokens_count{model_name="qwen"} 1',
            'vllm:request_prefill_kv_computed_tokens_sum{model_name="qwen"} 16',
            'vllm:mooncake_store_operation_total{operation="lookup_exists",status="ok"} 1',
            'vllm:mooncake_store_operation_total{operation="load_get",status="ok"} 1',
            'vllm:mooncake_store_operation_time_seconds_sum{operation="load_get",status="ok"} 0.2',
            'vllm:mooncake_store_operation_bytes_total{operation="load_get",status="ok"} 4096',
            'vllm:mooncake_store_operation_keys_total{operation="load_get",status="ok"} 2',
            'vllm:mooncake_store_operation_failed_keys_total{operation="load_get",status="ok"} 0',
        ]
    )
    snapshot = E4.metrics_snapshot(raw)
    assert snapshot["request"]["computed_tokens"] == 16
    assert snapshot["operations"]["load_get"]["bytes"] == 4096
    decomposition = E4.decompose_request(snapshot, 1.3)
    assert decomposition["forward_path_residual_seconds"] == pytest.approx(0.6)
    assert decomposition["spans_are_additive"] is False


def test_validate_round_requires_cross_instance_store_hit() -> None:
    record = passing_round()
    assert record["gate_errors"] == []
    record["reuse_on_b"]["metrics_delta"]["operations"]["load_get"]["bytes"] = 0
    assert "reuse Store GET has no transferred bytes" in E4.validate_round(record, 4096)


def test_tree_manifest_records_symlink_target_and_modes(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    executable = root / "tool"
    executable.write_text("payload\n", encoding="utf-8")
    executable.chmod(0o755)
    (root / "tool-link").symlink_to("tool")

    manifest = {row["path"]: row for row in BUILD.tree_manifest(root)}
    assert manifest["tool"] == {
        "path": "tool",
        "mode": "0755",
        "type": "regular",
        "bytes": 8,
        "sha256": BUILD.sha256_file(executable),
    }
    assert manifest["tool-link"]["type"] == "symlink"
    assert manifest["tool-link"]["link_target"] == "tool"
    assert manifest["tool-link"]["bytes"] == len(os.fsencode("tool"))


def test_compare_provided_archive_rejects_mode_drift(tmp_path: Path) -> None:
    reconstructed = tmp_path / "reconstructed"
    provided = tmp_path / "provided"
    reconstructed.mkdir()
    provided.mkdir()
    (reconstructed / "script.sh").write_text("exit 0\n", encoding="utf-8")
    (provided / "script.sh").write_text("exit 0\n", encoding="utf-8")
    (reconstructed / "script.sh").chmod(0o755)
    (provided / "script.sh").chmod(0o644)
    with pytest.raises(BUILD.BuildError):
        BUILD.compare_provided_archive(provided, reconstructed)


def test_prepare_submodule_target_accepts_only_empty_gitlink_directory(
    tmp_path: Path,
) -> None:
    archived_gitlink = tmp_path / "extern" / "pybind11"
    archived_gitlink.mkdir(parents=True)
    BUILD.prepare_submodule_target(archived_gitlink)

    (archived_gitlink / "unexpected").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(BUILD.BuildError, match="not an empty directory"):
        BUILD.prepare_submodule_target(archived_gitlink)

    symlink = tmp_path / "extern" / "yalantinglibs"
    symlink.symlink_to("pybind11", target_is_directory=True)
    with pytest.raises(BUILD.BuildError, match="symlink"):
        BUILD.prepare_submodule_target(symlink)


def test_native_dependency_subset_preserves_relative_symlinks_and_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    (source / "include" / "pkg").mkdir(parents=True)
    (source / "include" / "pkg" / "api.h").write_text("v1\n", encoding="utf-8")
    (source / "lib").mkdir()
    (source / "lib" / "libpkg.so.1").write_bytes(b"native")
    (source / "lib" / "libpkg.so").symlink_to("libpkg.so.1")
    monkeypatch.setattr(
        BUILD,
        "PINNED_NATIVE_DEPENDENCY_PATHS",
        ("include/pkg", "lib/libpkg.so", "lib/libpkg.so.1"),
    )

    destination = tmp_path / "copied"
    record = BUILD.copy_native_dependency_subset(source, destination)

    assert (destination / "lib" / "libpkg.so").is_symlink()
    assert os.readlink(destination / "lib" / "libpkg.so") == "libpkg.so.1"
    assert record["tree_manifest_sha256"] == BUILD.hashlib.sha256(
        BUILD.canonical_json(record["tree_manifest"]).encode()
    ).hexdigest()


def test_native_runtime_publication_dereferences_closed_library_tree(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    library_root = prefix / "lib"
    provider_root = library_root / "libibverbs"
    provider_root.mkdir(parents=True)
    versioned = library_root / "libpkg.so.1"
    versioned.write_bytes(b"native")
    (library_root / "libpkg.so").symlink_to("libpkg.so.1")
    (provider_root / "libpkg-rdma.so").symlink_to("../libpkg.so.1")

    destination = tmp_path / "runtime"
    record = BUILD.publish_native_runtime_libraries(prefix, destination)

    published = sorted(path for path in destination.rglob("*") if path.is_file())
    assert record["library_count"] == 3
    assert [path.relative_to(destination).as_posix() for path in published] == [
        "libibverbs/libpkg-rdma.so",
        "libpkg.so",
        "libpkg.so.1",
    ]
    assert all(not path.is_symlink() and path.read_bytes() == b"native" for path in published)
    assert PREFLIGHT.regular_file_tree_manifest(destination) == record["tree_manifest"]


def test_native_runtime_publication_rejects_dangling_library_alias(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    (prefix / "lib").mkdir(parents=True)
    (prefix / "lib" / "libmissing.so").symlink_to("libmissing.so.1")

    with pytest.raises(BUILD.BuildError, match="dangling or unreadable"):
        BUILD.publish_native_runtime_libraries(prefix, tmp_path / "runtime")


def test_final_elf_audit_accepts_system_closure_and_rejects_absolute_rpath(
    tmp_path: Path,
) -> None:
    extract_root = tmp_path / "wheel"
    runtime = tmp_path / "runtime"
    extract_root.mkdir()
    runtime.mkdir()
    elf = extract_root / "tool"
    shutil.copy2("/bin/true", elf)

    record = BUILD.audit_wheel_elf_runtime(
        extract_root,
        runtime,
        pinned_runtime_sha256={},
    )
    assert record["status"] == "PASS"
    assert record["elf_count"] == 1

    bad_source = tmp_path / "bad.c"
    bad_source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    compiler = shutil.which("cc")
    assert compiler is not None
    BUILD.run_capture(
        [compiler, str(bad_source), "-Wl,-rpath,/usr/local/cuda/lib", "-o", str(elf)]
    )
    with pytest.raises(BUILD.BuildError, match="non-relative RPATH"):
        BUILD.audit_wheel_elf_runtime(
            extract_root,
            runtime,
            pinned_runtime_sha256={},
        )


def test_result_schema_accepts_e3_pass_and_rejects_e4_claim() -> None:
    schema = json.loads(
        (REPOSITORY_ROOT / "benchmark/physical/vanilla-mooncake-e4/result.schema.json").read_text(
            encoding="utf-8"
        )
    )
    rounds = [passing_round(0), passing_round(1)]
    result = {
        "schema": E4.SCHEMA,
        "status": "PASS",
        "evidence_level": "E3_SMALL_SCALE_PHYSICAL_COMPONENT",
        "paper_ready": False,
        "e4_status": "BLOCKED_MISSING_MATCHED_MOONKVSIM_ERROR_COMPARISON",
        "rounds": rounds,
        "gate": {"status": "PASS", "requirements": ["store hit"]},
        "evidence_boundary": {
            "physical_request_path_executed": True,
            "matched_simulator_run_present": False,
            "simulator_error_comparison_present": False,
            "formal_e4_claim_allowed": False,
        },
    }
    jsonschema.validate(result, schema)
    result["evidence_level"] = "E4_SMALL_SCALE_PHYSICAL"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(result, schema)


def test_build_dependencies_are_exactly_pinned() -> None:
    assert BUILD.PINNED_BUILD_PACKAGES == (
        "pip==26.2.1",
        "build==1.3.0",
        "wheel==0.46.3",
        "auditwheel==6.5.0",
        "setuptools==80.10.2",
    )
    assert BUILD.sha256_file(BUILD.PINNED_PATCHELF) == BUILD.PINNED_PATCHELF_SHA256


def test_validate_pinned_freeze_rejects_drift() -> None:
    passing = "\n".join(BUILD.PINNED_BUILD_PACKAGES) + "\npackaging==25.0\n"
    assert BUILD.validate_pinned_freeze(passing)["pip"] == "26.2.1"
    with pytest.raises(BUILD.BuildError):
        BUILD.validate_pinned_freeze(passing.replace("wheel==0.46.3", "wheel==0.46.2"))


def test_choose_ports_returns_four_unique_ports() -> None:
    ports = E4.choose_ports()
    assert len(ports) == 4
    assert len(set(ports)) == 4


def protected_queue(*, include_monitored: bool = True) -> str:
    rows = [f"{job}|PENDING|long|held" for job in E4.HELD_PENDING_JOBS]
    if include_monitored:
        rows.extend(f"{job}|RUNNING|debug|monitor" for job in E4.READ_ONLY_MONITORED_JOBS)
    return "\n".join(rows) + "\n"


def monitored_accounting(states: tuple[str, str] = ("RUNNING", "PENDING")) -> str:
    return "\n".join(
        f"{job}|{state}|debug|monitor|gpu20|00:01:00|||0:0"
        for job, state in zip(E4.READ_ONLY_MONITORED_JOBS, states, strict=True)
    ) + "\n"


def test_protected_job_gate_splits_held_and_read_only_monitored_jobs() -> None:
    observation = E4.validate_protected_jobs_snapshot(
        protected_queue(), monitored_accounting()
    )
    assert set(observation["held_pending"]) == {str(job) for job in E4.HELD_PENDING_JOBS}
    assert observation["read_only_monitored"]["142290"] == {
        "squeue_state": "RUNNING",
        "sacct_state": "RUNNING",
    }
    assert observation["pre_post_state_equality_required"] is False


def test_completed_monitored_jobs_may_leave_squeue_without_blocking() -> None:
    before = E4.validate_protected_jobs_snapshot(
        protected_queue(), monitored_accounting(("RUNNING", "PENDING"))
    )
    after = E4.validate_protected_jobs_snapshot(
        protected_queue(include_monitored=False),
        monitored_accounting(("COMPLETED", "FAILED")),
    )
    assert before["read_only_monitored"]["142290"]["squeue_state"] == "RUNNING"
    assert after["read_only_monitored"]["142290"] == {
        "squeue_state": None,
        "sacct_state": "COMPLETED",
    }
    assert after["read_only_monitored"]["142291"]["sacct_state"] == "FAILED"


def test_held_jobs_still_require_squeue_pending() -> None:
    with pytest.raises(E4.E4Error):
        E4.validate_protected_jobs_snapshot(
            protected_queue().replace("PENDING", "RUNNING", 1), monitored_accounting()
        )
    with pytest.raises(E4.E4Error):
        E4.validate_protected_jobs_snapshot(
            protected_queue().split("\n", 1)[1], monitored_accounting()
        )


@pytest.mark.parametrize("accounting", ["", "142290|COMPLETED|debug|monitor\n", "bad\n"])
def test_monitored_jobs_require_well_formed_complete_accounting(accounting: str) -> None:
    with pytest.raises(E4.E4Error):
        E4.validate_protected_jobs_snapshot(protected_queue(), accounting)


def test_preflight_uses_same_split_read_only_job_contract() -> None:
    queue = protected_queue(include_monitored=False)
    accounting = monitored_accounting(("COMPLETED", "FAILED"))
    observation = PREFLIGHT.validate_protected_jobs(queue, accounting)
    assert observation["read_only_monitored"]["142290"] == {
        "squeue_state": None,
        "sacct_state": "COMPLETED",
    }
    with pytest.raises(PREFLIGHT.PreflightError):
        PREFLIGHT.validate_protected_jobs(queue, "")


def test_preflight_parses_exact_resource_contract() -> None:
    source = (REPOSITORY_ROOT / "scripts/physical/run_vanilla_mooncake_e4.sbatch").read_text(
        encoding="utf-8"
    )
    directives = PREFLIGHT.parse_sbatch_directives(source)
    assert directives["--nodelist"] == "gpu10"
    assert directives["--gres"] == "gpu:rtx4090:2"
    with pytest.raises(PREFLIGHT.PreflightError):
        PREFLIGHT.parse_sbatch_directives(source.replace("--mem=160G", "--mem=159G"))


def test_preflight_gpu10_gate_rejects_active_jobs_and_low_memory() -> None:
    node = "NodeName=gpu10 State=IDLE FreeMem=240000 Gres=gpu:rtx4090:2"
    assert PREFLIGHT.validate_gpu10_node(node, "")["state"] == "IDLE"
    with pytest.raises(PREFLIGHT.PreflightError):
        PREFLIGHT.validate_gpu10_node(node, "99|RUNNING|debug|foreign")
    with pytest.raises(PREFLIGHT.PreflightError):
        PREFLIGHT.validate_gpu10_node(node.replace("240000", "100000"), "")


def test_preflight_checksum_bundle_rejects_unlisted_and_symlink_files(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    payload = bundle / "payload"
    payload.write_text("value\n", encoding="utf-8")
    (bundle / "SHA256SUMS").write_text(
        f"{PREFLIGHT.sha256_file(payload)}  payload\n", encoding="utf-8"
    )
    assert PREFLIGHT.verify_checksum_bundle(bundle)["artifact_count"] == 1
    payload.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(PREFLIGHT.PreflightError, match="checksum mismatch"):
        PREFLIGHT.verify_checksum_bundle(bundle)
    payload.write_text("value\n", encoding="utf-8")
    (bundle / "extra").write_text("unlisted\n", encoding="utf-8")
    with pytest.raises(PREFLIGHT.PreflightError):
        PREFLIGHT.verify_checksum_bundle(bundle)
    (bundle / "extra").unlink()
    (bundle / "payload-link").symlink_to("payload")
    with pytest.raises(PREFLIGHT.PreflightError):
        PREFLIGHT.verify_checksum_bundle(bundle)


def test_preflight_verifies_runtime_and_elf_audit_bound_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    runtime = bundle / "native-runtime"
    runtime.mkdir(parents=True)
    native_source = tmp_path / "native-source"
    native_source.mkdir()
    cuda_root = tmp_path / "cuda"
    cudart = cuda_root / "libcudart.so.12.8.90"
    cudart.parent.mkdir()
    cudart.write_bytes(b"cuda12")
    gcc_root = tmp_path / "gcc"
    gcc_root.mkdir()
    (gcc_root / "libgcc_s.so.1").write_bytes(b"gcc")
    (gcc_root / "libstdc++.so.6").write_bytes(b"stdcpp")
    shutil.copy2(cudart, runtime / "libcudart.so.12")
    shutil.copy2(gcc_root / "libgcc_s.so.1", runtime / "libgcc_s.so.1")
    shutil.copy2(gcc_root / "libstdc++.so.6", runtime / "libstdc++.so.6")
    monkeypatch.setattr(PREFLIGHT, "PINNED_CUDART", cudart)
    monkeypatch.setattr(PREFLIGHT, "PINNED_GCC_RUNTIME_ROOT", gcc_root)
    monkeypatch.setattr(PREFLIGHT, "PINNED_NATIVE_DEPENDENCY_SOURCE", native_source)

    runtime_tree = PREFLIGHT.regular_file_tree_manifest(runtime)
    runtime_tree_sha = PREFLIGHT.hashlib.sha256(
        PREFLIGHT.canonical_json(runtime_tree).encode()
    ).hexdigest()
    native_tree = [{"path": "include/pkg.h", "type": "regular"}]
    native_tree_sha = PREFLIGHT.hashlib.sha256(
        PREFLIGHT.canonical_json(native_tree).encode()
    ).hexdigest()
    native_manifest = {
        "construction": "relocated_hash_manifested_subset",
        "selected_paths": ["include/pkg.h"],
        "tree_manifest": native_tree,
        "tree_manifest_sha256": native_tree_sha,
    }
    BUILD.write_json(bundle / "native-dependency-manifest.json", native_manifest)
    runtime_manifest = {
        "construction": "dereferenced_regular_files_from_hashed_native_subset",
        "library_count": len(runtime_tree),
        "tree_manifest": runtime_tree,
        "tree_manifest_sha256": runtime_tree_sha,
    }
    BUILD.write_json(bundle / "native-runtime-manifest.json", runtime_manifest)
    pinned = {
        "libcudart.so.12": PREFLIGHT.sha256_file(cudart),
        "libgcc_s.so.1": PREFLIGHT.sha256_file(gcc_root / "libgcc_s.so.1"),
        "libstdc++.so.6": PREFLIGHT.sha256_file(gcc_root / "libstdc++.so.6"),
    }
    elf_audit = {
        "schema": "moonkvsim.vanilla_mooncake_elf_runtime_audit.v1",
        "status": "PASS",
        "elf_count": 1,
        "pinned_runtime_sha256": pinned,
        "observed_pinned_runtimes": {
            name: {"resolved": f"staging/{name}", "sha256": digest}
            for name, digest in pinned.items()
        },
        "records": [{"path": "mooncake/engine.so"}],
    }
    BUILD.write_json(bundle / "elf-runtime-audit.json", elf_audit)
    (bundle / "source-tree-manifest.json").write_text("[]\n", encoding="utf-8")
    (bundle / "build-constraints.txt").write_text("pins\n", encoding="utf-8")
    (bundle / "build-tool-freeze.txt").write_text("freeze\n", encoding="utf-8")
    wheel = bundle / "mooncake_transfer_engine-cp312-cp312-linux_x86_64.whl"
    wheel.write_bytes(b"wheel")
    manifest = {
        "status": "PASS",
        "source": {
            "commit": PREFLIGHT.PINNED_MOONCAKE_COMMIT,
            "dirty_worktree_files_copied": False,
            "tree_manifest_sha256": PREFLIGHT.sha256_file(
                bundle / "source-tree-manifest.json"
            ),
        },
        "build": {
            "dirty_mooncake_venv_modified": False,
            "pinned_vllm_venv_modified": False,
            "ssd_nvme_enabled": False,
            "native_dependency_source": str(native_source),
            "native_dependency_manifest_sha256": PREFLIGHT.sha256_file(
                bundle / "native-dependency-manifest.json"
            ),
            "native_dependency_tree_manifest_sha256": native_tree_sha,
            "native_runtime_directory": "native-runtime",
            "native_runtime_manifest_sha256": PREFLIGHT.sha256_file(
                bundle / "native-runtime-manifest.json"
            ),
            "native_runtime_tree_manifest_sha256": runtime_tree_sha,
            "local_wheel_platform_tag": PREFLIGHT.LOCAL_WHEEL_PLATFORM_TAG,
            "auditwheel_repair_platform_tag": PREFLIGHT.AUDITWHEEL_REPAIR_PLATFORM_TAG,
            "pinned_build_packages": list(PREFLIGHT.PINNED_BUILD_PACKAGES),
            "pep517_build_isolation_constrained": True,
            "build_constraints_sha256": PREFLIGHT.sha256_file(
                bundle / "build-constraints.txt"
            ),
            "build_tool_freeze_sha256": PREFLIGHT.sha256_file(
                bundle / "build-tool-freeze.txt"
            ),
        },
        "wheel": {
            "sha256": PREFLIGHT.sha256_file(wheel),
            "platform_tag": PREFLIGHT.LOCAL_WHEEL_PLATFORM_TAG,
            "elf_runtime_audit": {
                "path": "elf-runtime-audit.json",
                "sha256": PREFLIGHT.sha256_file(bundle / "elf-runtime-audit.json"),
                "status": "PASS",
                "elf_count": 1,
            },
        },
    }
    BUILD.write_json(bundle / "build-manifest.json", manifest)
    BUILD.write_json(
        bundle / "PUBLICATION_COMPLETE.json",
        {"publication": "COMPLETE", "status": "PASS"},
    )
    BUILD.generate_checksums(bundle)

    record = PREFLIGHT.verify_clean_build(bundle)
    assert record["elf_runtime_audit_sha256"] == PREFLIGHT.sha256_file(
        bundle / "elf-runtime-audit.json"
    )


def test_preflight_atomic_publication_is_no_clobber(tmp_path: Path) -> None:
    output = tmp_path / "record.json"
    PREFLIGHT.atomic_write_json(output, {"status": "PASS"})
    assert json.loads(output.read_text(encoding="utf-8")) == {"status": "PASS"}
    with pytest.raises(PREFLIGHT.PreflightError):
        PREFLIGHT.atomic_write_json(output, {"status": "FAIL"})
