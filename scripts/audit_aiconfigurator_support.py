#!/usr/bin/env python3
"""Generate or check the target-specific AIConfigurator support audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA = "moonkvsim.aiconfigurator-support-audit.v1"
EXPECTED_COMMIT = "4b9d9dc51e02b5e9d4acc3688f3edf41693834c6"
EXPECTED_PACKAGE_VERSION = "0.9.0"
MODEL_ID = "Qwen/Qwen3-8B"
MODEL_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
TARGET_VLLM_SOURCE_COMMIT = "644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504"
TARGET_VLLM_VERSION = "1.2.2"
TARGET_VLLM_INSTALLED_VERSION = "1.2.2+aegiskv.sm89"
REFERENCE_VLLM_VERSION = "0.14.0"
SYSTEMS = ("l40s", "a100_sxm", "a100_pcie")
SOURCE_LOCK_RELATIVE_PATH = Path("reference/source-lock.json")
SDK_GOLDEN_RELATIVE_PATH = Path(
    "reference/goldens/aiconfigurator-0.9.0-vllm-0.14.0-sdk.json"
)
GENERATOR_RELATIVE_PATH = Path("scripts/audit_aiconfigurator_support.py")
DEFAULT_OUTPUT = Path("reference/aiconfigurator-support.json")
EXPECTED_SDK_GOLDEN_SHA256 = (
    "11018ca36d82b977767421be485c56949691b774b02bd5b9028cdc04ba362874"
)


class AuditError(RuntimeError):
    """Raised when an input or declared support boundary drifts."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.repository_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        document = build_support_audit(root)
        expected = _canonical_json_bytes(document) + b"\n"
        if args.check:
            if args.overwrite:
                raise AuditError("--check and --overwrite are mutually exclusive")
            try:
                actual = output.read_bytes()
            except OSError as error:
                raise AuditError(f"cannot read support artifact: {error}") from error
            if actual != expected:
                raise AuditError(f"{output} is not byte-identical to a fresh audit")
            status = "checked"
        else:
            if output.exists() and not args.overwrite:
                raise AuditError(f"refusing to overwrite existing artifact: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(expected)
            status = "generated"
    except (AuditError, OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": str(output),
                "sha256": hashlib.sha256(expected).hexdigest(),
                "status": status,
                "target_status": document["decision"]["status"],
            },
            sort_keys=True,
        )
    )
    return 0


def build_support_audit(root: Path) -> dict[str, Any]:
    source_lock_path = root / SOURCE_LOCK_RELATIVE_PATH
    source_lock = _load_json(source_lock_path)
    repositories = _mapping(source_lock.get("repositories"), "repositories")
    aic_lock = _mapping(repositories.get("aiconfigurator"), "aiconfigurator lock")
    vllm_lock = _mapping(repositories.get("vllm"), "vllm lock")
    model_lock = _mapping(source_lock.get("model_tokenizer"), "model_tokenizer")
    if aic_lock.get("commit") != EXPECTED_COMMIT:
        raise AuditError("AIConfigurator source-lock commit drift")
    if aic_lock.get("package_version") != EXPECTED_PACKAGE_VERSION:
        raise AuditError("AIConfigurator source-lock version drift")
    if vllm_lock.get("commit") != TARGET_VLLM_SOURCE_COMMIT:
        raise AuditError("target vLLM source-lock commit drift")
    if vllm_lock.get("upstream_tag_version") != TARGET_VLLM_VERSION:
        raise AuditError("target vLLM version drift")
    if vllm_lock.get("observed_generated_version") != TARGET_VLLM_INSTALLED_VERSION:
        raise AuditError("target installed vLLM version drift")
    if model_lock.get("model_id") != MODEL_ID or model_lock.get("revision") != MODEL_REVISION:
        raise AuditError("target model identity drift")

    repository = Path(_string(aic_lock.get("repository"), "repository")).resolve()
    if _git(repository, "rev-parse", "HEAD").strip() != EXPECTED_COMMIT:
        raise AuditError("AIConfigurator checkout HEAD drift")
    if _git(repository, "status", "--porcelain=v1", "-z"):
        raise AuditError("AIConfigurator checkout is dirty")

    golden_path = root / SDK_GOLDEN_RELATIVE_PATH
    golden_bytes = golden_path.read_bytes()
    if hashlib.sha256(golden_bytes).hexdigest() != EXPECTED_SDK_GOLDEN_SHA256:
        raise AuditError("AIConfigurator SDK golden hash drift")
    golden = _load_json(golden_path)
    if _canonical_json_bytes(golden) + b"\n" != golden_bytes:
        raise AuditError("AIConfigurator SDK golden is not canonical JSON")
    if golden.get("formal_use_allowed") is not False:
        raise AuditError("reference SDK golden must forbid formal use")
    provenance = _mapping(golden.get("provenance"), "golden.provenance")
    if provenance.get("source_commit") != EXPECTED_COMMIT:
        raise AuditError("SDK golden source commit drift")

    support_rows = _list(golden.get("support_probe"), "golden.support_probe")
    support_by_key = {
        (
            _string(_mapping(row, "support row").get("system"), "support.system"),
            _string(_mapping(row, "support row").get("backend_version"), "support.version"),
        ): _mapping(row, "support row")
        for row in support_rows
    }
    database_bundles = _mapping(
        provenance.get("vllm_database_bundles"),
        "golden.provenance.vllm_database_bundles",
    )

    systems: list[dict[str, object]] = []
    for system in SYSTEMS:
        reference_support = support_by_key[(system, REFERENCE_VLLM_VERSION)]
        target_support = support_by_key[(system, TARGET_VLLM_VERSION)]
        if target_support.get("agg_supported") is not False or target_support.get(
            "disagg_supported"
        ) is not False:
            raise AuditError(f"target vLLM unexpectedly became supported for {system}")
        bundle = database_bundles.get(system)
        shape_coverage = (
            None
            if bundle is None
            else _qwen_shape_coverage(repository, system, REFERENCE_VLLM_VERSION)
        )
        backend_inventory = _backend_inventory(repository, system)
        systems.append(
            {
                "hardware_profile_id": system,
                "hardware_profile": _materialized_input(provenance, f"systems/{system}.yaml"),
                "backend_database_inventory": backend_inventory,
                "target_vllm_support": dict(target_support),
                "nearest_reference_vllm_support": dict(reference_support),
                "reference_vllm_database_bundle": bundle,
                "qwen3_8b_bf16_shape_coverage": shape_coverage,
                "selection_eligible": False,
                "selection_reason": _selection_reason(system, shape_coverage),
            }
        )

    sdk_scenarios = _list(golden.get("scenarios"), "golden.scenarios")
    return {
        "schema": SCHEMA,
        "evidence_class": "E1_source_audit_plus_E2_reference_sdk_golden",
        "probe_input": {
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "target_vllm_source_commit": TARGET_VLLM_SOURCE_COMMIT,
            "target_vllm_version": TARGET_VLLM_VERSION,
            "target_vllm_installed_version": TARGET_VLLM_INSTALLED_VERSION,
            "target_hardware_candidates": list(SYSTEMS),
            "required_phases": ["prefill", "decode"],
            "required_shape_axes": [
                "batch_size",
                "extend_length",
                "past_kv_length",
            ],
            "required_max_context_tokens": 131072,
            "mixed_phase_contract": (
                "MoonKVSim preserves separate phase batches and requires an explicitly "
                "calibrated composition for mixed scheduler steps"
            ),
        },
        "provider": {
            "package": "aiconfigurator",
            "package_version": EXPECTED_PACKAGE_VERSION,
            "source_repository": str(repository),
            "source_commit": EXPECTED_COMMIT,
            "source_tree": provenance["source_tree"],
            "package_import_path": provenance["package_import_path"],
            "semantic_source_lock": provenance["semantic_source_lock"],
            "semantic_source_lock_fingerprint": provenance[
                "semantic_source_lock_fingerprint"
            ],
            "model_config": _materialized_input(
                provenance, "model_configs/Qwen--Qwen3-8B_config.json"
            ),
            "backend_implementation": {
                "path": "src/aiconfigurator/sdk/backends/vllm_backend.py",
                "sha256": _locked_file_sha(
                    aic_lock,
                    "src/aiconfigurator/sdk/backends/vllm_backend.py",
                ),
            },
        },
        "systems": systems,
        "sdk_reference_golden": {
            "path": SDK_GOLDEN_RELATIVE_PATH.as_posix(),
            "sha256": EXPECTED_SDK_GOLDEN_SHA256,
            "scenario_count": len(sdk_scenarios),
            "scope": (
                "AIC vLLM-0.14.0 static prefill/decode SDK behavior only; not target "
                "vLLM-1.2.2 compatibility or calibration"
            ),
            "formal_use_allowed": False,
        },
        "adapter_boundary": {
            "moonkvsim_input": {
                "prefill": ["extend_lengths", "past_kv_lengths"],
                "decode": ["past_kv_lengths"],
            },
            "aiconfigurator_static_sdk_input": ["batch_size", "isl", "osl", "prefix"],
            "exact_arbitrary_per_request_vectors_supported": False,
            "mixed_phase_exact_vector_supported": False,
            "decision": (
                "Do not bind AIConfiguratorPhaseBackend to the real SDK until an exact "
                "shape mapping and held-out residual validation exist"
            ),
        },
        "database_backend_isolation": {
            "rule": "only vllm database files may satisfy a vllm profile",
            "sglang_database_reuse_for_vllm": "forbidden",
            "trtllm_database_reuse_for_vllm": "forbidden",
        },
        "decision": {
            "status": "UNSUPPORTED_FOR_TARGET_PROFILE",
            "selected_profile": None,
            "selected_hardware_profile": None,
            "selected_database_mode": None,
            "selected_database_sha256": None,
            "held_out_calibration_report": None,
            "formal_use_allowed": False,
            "src_block_001_cleared": False,
            "diagnostics": [
                {
                    "code": "target_backend_version_unsupported",
                    "detail": "support matrix has no Qwen3-8B vLLM 1.2.2 profile",
                },
                {
                    "code": "a100_pcie_database_missing",
                    "detail": (
                        "A100 PCIe has a system estimate only and no materialized "
                        "vLLM database"
                    ),
                },
                {
                    "code": "prefill_128k_shape_uncovered",
                    "detail": "Qwen3-8B BF16 context-attention rows stop at 16384 tokens",
                },
                {
                    "code": "decode_128k_shape_uncovered",
                    "detail": "Qwen3-8B BF16 generation-attention rows stop at past KV 32767",
                },
                {
                    "code": "exact_mixed_vector_mapping_unavailable",
                    "detail": (
                        "SDK static/aggregate coordinates do not preserve arbitrary "
                        "request vectors"
                    ),
                },
                {
                    "code": "held_out_residuals_missing",
                    "detail": (
                        "no target vLLM forward measurements or held-out residual "
                        "report exists"
                    ),
                },
            ],
        },
        "next_step": {
            "status": "physical_calibration_out_of_current_scope",
            "required_output_schema": "moonkvsim.aiconfigurator-profile-selection.v1",
            "selection_schema": "schemas/predictor-profile-selection.schema.json",
            "calibration_method": "phase_shape_residual_table",
            "global_scale_factor": "forbidden",
        },
        "generator": {
            "path": GENERATOR_RELATIVE_PATH.as_posix(),
            "sha256": _sha256_file(root / GENERATOR_RELATIVE_PATH),
        },
    }


def _qwen_shape_coverage(
    repository: Path, system: str, backend_version: str
) -> dict[str, object]:
    base = (
        repository
        / "src/aiconfigurator/systems/data"
        / system
        / "vllm"
        / backend_version
    )
    filters = {
        "num_heads": "32",
        "num_key_value_heads": "8",
        "head_dim": "128",
        "attn_dtype": "bfloat16",
        "kv_cache_dtype": "bfloat16",
    }
    context = _filtered_rows(base / "context_attention_perf.txt", filters)
    generation = _filtered_rows(base / "generation_attention_perf.txt", filters)
    if not context or not generation:
        raise AuditError(f"Qwen3-8B BF16 attention rows are missing for {system}")
    return {
        "filter": filters,
        "prefill": {
            "row_count": len(context),
            "batch_sizes": _unique_ints(context, "batch_size"),
            "extend_lengths": _unique_ints(context, "isl"),
            "max_extend_length": max(_unique_ints(context, "isl")),
            "kernel_sources": sorted({row["kernel_source"] for row in context}),
            "covers_131072": False,
        },
        "decode": {
            "row_count": len(generation),
            "batch_sizes": _unique_ints(generation, "batch_size"),
            "past_kv_lengths": _unique_ints(generation, "step"),
            "max_past_kv_length": max(_unique_ints(generation, "step")),
            "kernel_sources": sorted({row["kernel_source"] for row in generation}),
            "covers_131072": False,
        },
        "mixed": {
            "exact_per_request_vector_rows": 0,
            "supported": False,
            "reason": "database/API coordinates are aggregate rather than arbitrary vectors",
        },
    }


def _filtered_rows(path: Path, filters: Mapping[str, str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return [
            row
            for row in csv.DictReader(stream)
            if all(row.get(key) == expected for key, expected in filters.items())
        ]


def _unique_ints(rows: Sequence[Mapping[str, str]], field: str) -> list[int]:
    return sorted({int(row[field]) for row in rows})


def _backend_inventory(repository: Path, system: str) -> list[dict[str, object]]:
    base = repository / "src/aiconfigurator/systems/data" / system
    if not base.is_dir():
        return []
    inventory: list[dict[str, object]] = []
    for backend_dir in sorted(path for path in base.iterdir() if path.is_dir()):
        versions = sorted(path.name for path in backend_dir.iterdir() if path.is_dir())
        inventory.append(
            {
                "backend": backend_dir.name,
                "versions": versions,
                "eligible_for_target_vllm_profile": (
                    backend_dir.name == "vllm" and TARGET_VLLM_VERSION in versions
                ),
            }
        )
    return inventory


def _selection_reason(system: str, coverage: object) -> str:
    if system == "a100_pcie":
        return "no materialized vLLM database"
    if coverage is None:
        return "no Qwen3-8B vLLM shape coverage"
    return "nearest database is vLLM 0.14.0 and lacks target-version/128K/mixed-vector coverage"


def _materialized_input(provenance: Mapping[str, Any], suffix: str) -> Mapping[str, Any]:
    inputs = _mapping(provenance.get("materialized_inputs"), "materialized_inputs")
    matches = [value for path, value in inputs.items() if path.endswith(suffix)]
    if len(matches) != 1:
        raise AuditError(f"expected one materialized input ending in {suffix!r}")
    return _mapping(matches[0], f"materialized input {suffix}")


def _locked_file_sha(lock: Mapping[str, Any], path: str) -> str:
    files = _list(lock.get("files"), "aiconfigurator.files")
    matches = [
        _mapping(item, "aiconfigurator file")
        for item in files
        if _mapping(item, "aiconfigurator file").get("path") == path
    ]
    if len(matches) != 1:
        raise AuditError(f"source lock does not bind {path}")
    return _string(matches[0].get("sha256"), f"SHA for {path}")


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AuditError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditError(f"cannot load JSON {path}: {error}") from error
    return _mapping(value, str(path))


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise AuditError(f"{location} must be an object")
    return value


def _list(value: object, location: str) -> list[object]:
    if not isinstance(value, list):
        raise AuditError(f"{location} must be an array")
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuditError(f"{location} must be a non-empty string")
    return value


def _canonical_json_bytes(value: Mapping[str, Any] | Sequence[Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
