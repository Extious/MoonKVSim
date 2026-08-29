#!/usr/bin/env python3
"""Capture a source-verified AIConfigurator SDK reference golden.

This capture exercises the nearest available Qwen3-8B vLLM database
(``0.14.0``) on L40S and A100-SXM.  MoonKVSim targets pinned vLLM ``1.2.2``;
therefore the output is a reference SDK/API golden only, never a selected
profile, calibration result, or permission for formal simulator runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_INTERPRETER = Path("/home/comp/zhanzhao/aiconfigurator/.venv/bin/python")
EXPECTED_COMMIT = "4b9d9dc51e02b5e9d4acc3688f3edf41693834c6"
EXPECTED_TREE = "6d3489b5b726a1d1988d451bba1822114b61bb6e"
EXPECTED_PACKAGE_VERSION = "0.9.0"
TARGET_VLLM_VERSION = "1.2.2"
REFERENCE_VLLM_VERSION = "0.14.0"
MODEL_ID = "Qwen/Qwen3-8B"
MODEL_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
SCHEMA = "moonkvsim.aiconfigurator-sdk-golden.v1"
EVIDENCE_CLASS = "E2_reference_sdk_semantics_only"
DEFAULT_OUTPUT = Path("reference/goldens/aiconfigurator-0.9.0-vllm-0.14.0-sdk.json")
GENERATOR_RELATIVE_PATH = Path("scripts/generate_aiconfigurator_sdk_golden.py")
SOURCE_LOCK_RELATIVE_PATH = Path("reference/source-lock.json")
SYSTEMS = ("l40s", "a100_sxm", "a100_pcie")
REFERENCE_SYSTEMS = ("l40s", "a100_sxm")
_LFS_POINTER = re.compile(
    rb"version https://git-lfs.github.com/spec/v1\noid sha256:([0-9a-f]{64})\nsize ([0-9]+)\n"
)


class CaptureError(RuntimeError):
    """Raised on source, environment, support, or artifact drift."""


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
        provenance = _verify_source_and_environment(root)
        support, scenarios = _capture_sdk()
        document: dict[str, object] = {
            "schema": SCHEMA,
            "evidence_class": EVIDENCE_CLASS,
            "formal_use_allowed": False,
            "claim_exclusions": [
                "target_vllm_1.2.2_compatibility",
                "physical_forward_measurement",
                "calibration",
                "held_out_error",
                "exact_per_request_mixed_phase_prediction",
                "global_scale_factor",
                "performance_claim",
            ],
            "provenance": provenance,
            "support_probe": support,
            "scenarios": scenarios,
        }
        expected = _canonical_json_bytes(document) + b"\n"
        if args.check:
            if args.overwrite:
                raise CaptureError("--check and --overwrite are mutually exclusive")
            try:
                actual = output.read_bytes()
            except OSError as error:
                raise CaptureError(f"cannot read golden for --check: {error}") from error
            if actual != expected:
                raise CaptureError(f"{output} is not byte-identical to a fresh capture")
            status = "checked"
        else:
            if output.exists() and not args.overwrite:
                raise CaptureError(f"refusing to overwrite existing golden: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(expected)
            status = "generated"
    except (CaptureError, OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "evidence_class": EVIDENCE_CLASS,
                "output": str(output),
                "scenario_count": len(scenarios),
                "sha256": hashlib.sha256(expected).hexdigest(),
                "status": status,
            },
            sort_keys=True,
        )
    )
    return 0


def _verify_source_and_environment(root: Path) -> dict[str, object]:
    actual_interpreter = Path(sys.executable).absolute()
    expected_interpreter = EXPECTED_INTERPRETER.absolute()
    if actual_interpreter != expected_interpreter:
        raise CaptureError(
            "wrong interpreter; run with "
            f"{expected_interpreter}, got {actual_interpreter}"
        )
    source_lock = _load_json(root / SOURCE_LOCK_RELATIVE_PATH)
    repositories = _mapping(source_lock.get("repositories"), "repositories")
    locked = _mapping(repositories.get("aiconfigurator"), "repositories.aiconfigurator")
    if locked.get("commit") != EXPECTED_COMMIT:
        raise CaptureError("source-lock AIConfigurator commit drift")
    if locked.get("tree") != EXPECTED_TREE:
        raise CaptureError("source-lock AIConfigurator tree drift")
    if locked.get("package_version") != EXPECTED_PACKAGE_VERSION:
        raise CaptureError("source-lock AIConfigurator package version drift")
    repository = Path(_string(locked.get("repository"), "repository")).resolve()
    if _git(repository, "rev-parse", "HEAD").decode().strip() != EXPECTED_COMMIT:
        raise CaptureError("AIConfigurator checkout HEAD drift")
    if _git(repository, "rev-parse", "HEAD^{tree}").decode().strip() != EXPECTED_TREE:
        raise CaptureError("AIConfigurator checkout tree drift")
    if _git(repository, "status", "--porcelain=v1", "-z"):
        raise CaptureError("AIConfigurator checkout is dirty")

    locked_source_files: dict[str, str] = {}
    for raw in _list(locked.get("files"), "repositories.aiconfigurator.files"):
        record = _mapping(raw, "AIConfigurator source file")
        relative = _safe_relative(record.get("path"), "source path")
        expected_sha = _sha_string(record.get("sha256"), f"source SHA {relative}")
        commit_bytes = _git(repository, "show", f"{EXPECTED_COMMIT}:{relative.as_posix()}")
        if hashlib.sha256(commit_bytes).hexdigest() != expected_sha:
            raise CaptureError(f"AIConfigurator commit-object hash drift: {relative}")
        if _sha256_file(repository / relative) != expected_sha:
            raise CaptureError(f"AIConfigurator worktree source hash drift: {relative}")
        locked_source_files[relative.as_posix()] = expected_sha

    try:
        installed_version = metadata.version("aiconfigurator")
    except metadata.PackageNotFoundError as error:
        raise CaptureError("aiconfigurator distribution is not installed") from error
    if installed_version != EXPECTED_PACKAGE_VERSION:
        raise CaptureError("installed AIConfigurator version drift")
    import aiconfigurator  # type: ignore[import-not-found]

    expected_import = (repository / "src/aiconfigurator/__init__.py").resolve()
    actual_import = Path(_string(aiconfigurator.__file__, "aiconfigurator.__file__")).resolve()
    if actual_import != expected_import:
        raise CaptureError(f"AIConfigurator imported outside pinned checkout: {actual_import}")

    model_path = Path("src/aiconfigurator/model_configs/Qwen--Qwen3-8B_config.json")
    materialized: dict[str, object] = {
        model_path.as_posix(): _plain_file_record(repository, model_path)
    }
    database_bundles: dict[str, object] = {}
    for system in SYSTEMS:
        system_path = Path(f"src/aiconfigurator/systems/{system}.yaml")
        matrix_path = Path(f"src/aiconfigurator/systems/support_matrix/{system}.csv")
        materialized[system_path.as_posix()] = _plain_file_record(repository, system_path)
        if matrix_path.is_file() or (repository / matrix_path).is_file():
            materialized[matrix_path.as_posix()] = _plain_file_record(repository, matrix_path)
        database_dir = repository / (
            f"src/aiconfigurator/systems/data/{system}/vllm/{REFERENCE_VLLM_VERSION}"
        )
        if not database_dir.is_dir():
            database_bundles[system] = None
            continue
        records = tuple(
            _lfs_file_record(repository, path.relative_to(repository))
            for path in sorted(database_dir.glob("*.txt"))
        )
        database_bundles[system] = {
            "backend": "vllm",
            "backend_version": REFERENCE_VLLM_VERSION,
            "files": list(records),
            "bundle_fingerprint": _sha256_json(list(records)),
        }

    generator_path = root / GENERATOR_RELATIVE_PATH
    semantic_lock = {
        "commit": EXPECTED_COMMIT,
        "tree": EXPECTED_TREE,
        "package_version": EXPECTED_PACKAGE_VERSION,
        "files": locked_source_files,
    }
    return {
        "interpreter": str(actual_interpreter),
        "python_version": platform.python_version(),
        "package_import_path": str(actual_import),
        "source_repository": str(repository),
        "source_commit": EXPECTED_COMMIT,
        "source_tree": EXPECTED_TREE,
        "package_version": EXPECTED_PACKAGE_VERSION,
        "semantic_source_lock": semantic_lock,
        "semantic_source_lock_fingerprint": _sha256_json(semantic_lock),
        "materialized_inputs": materialized,
        "vllm_database_bundles": database_bundles,
        "generator": {
            "path": GENERATOR_RELATIVE_PATH.as_posix(),
            "sha256": _sha256_file(generator_path),
        },
        "model": {
            "model_id": MODEL_ID,
            "target_model_revision": MODEL_REVISION,
            "note": "SDK uses the pinned AIC model-config bytes, not model weights or CUDA",
        },
    }


def _capture_sdk() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    from aiconfigurator.cli.api import cli_estimate  # type: ignore[import-not-found]
    from aiconfigurator.sdk import common  # type: ignore[import-not-found]

    support: list[dict[str, object]] = []
    for system in SYSTEMS:
        for version in (REFERENCE_VLLM_VERSION, TARGET_VLLM_VERSION):
            result = common.check_support(MODEL_ID, system, "vllm", version)
            support.append(
                {
                    "model_id": MODEL_ID,
                    "system": system,
                    "backend": "vllm",
                    "backend_version": version,
                    "agg_supported": result.agg_supported,
                    "disagg_supported": result.disagg_supported,
                    "exact_match": result.exact_match,
                    "inferred_architecture": result.architecture,
                }
            )

    definitions = (
        ("prefill_bs1_extend128_past0", "static_ctx", 128, 2, 1),
        ("prefill_bs4_extend2048_past0", "static_ctx", 2048, 2, 4),
        ("decode_bs1_extend1_past128", "static_gen", 128, 2, 1),
        ("decode_bs4_extend1_past8192", "static_gen", 8192, 2, 4),
    )
    scenarios: list[dict[str, object]] = []
    for system in REFERENCE_SYSTEMS:
        for name, mode, isl, osl, batch_size in definitions:
            result = cli_estimate(
                model_path=MODEL_ID,
                system_name=system,
                mode=mode,
                backend_name="vllm",
                backend_version=REFERENCE_VLLM_VERSION,
                database_mode="SILICON",
                isl=isl,
                osl=osl,
                batch_size=batch_size,
                tp_size=1,
                pp_size=1,
                stride=1,
            )
            if result.summary is None:
                raise CaptureError(f"AIConfigurator SDK returned no summary: {system}/{name}")
            context_sources = result.summary.get_context_source_dict() or {}
            generation_sources = result.summary.get_generation_source_dict() or {}
            if not any(
                source in {"silicon", "mixed"}
                for source in (*context_sources.values(), *generation_sources.values())
            ):
                raise CaptureError(f"reference SDK probe used no materialized silicon data: {name}")
            phase = "prefill" if mode == "static_ctx" else "decode"
            scenarios.append(
                {
                    "name": f"{system}_{name}",
                    "input": {
                        "model_id": MODEL_ID,
                        "system": system,
                        "backend": "vllm",
                        "backend_version": REFERENCE_VLLM_VERSION,
                        "database_mode": "SILICON",
                        "sdk_mode": mode,
                        "phase": phase,
                        "batch_size": batch_size,
                        "extend_length_per_request": isl if phase == "prefill" else 1,
                        "past_kv_length_per_request": 0 if phase == "prefill" else isl,
                        "tp_size": 1,
                        "pp_size": 1,
                    },
                    "output": {
                        "ttft_ms": result.ttft,
                        "tpot_ms": result.tpot,
                        "context_operation_sources": context_sources,
                        "generation_operation_sources": generation_sources,
                    },
                    "boundary": (
                        "AIC static SDK estimate; not an exact arbitrary per-request vector "
                        "or mixed continuous-batching scheduler-step prediction"
                    ),
                }
            )
    return support, scenarios


def _plain_file_record(repository: Path, relative: Path) -> dict[str, object]:
    data = (repository / relative).read_bytes()
    commit_data = _git(repository, "show", f"{EXPECTED_COMMIT}:{relative.as_posix()}")
    if data != commit_data:
        raise CaptureError(f"plain source input differs from commit object: {relative}")
    return {
        "path": relative.as_posix(),
        "git_blob": _git(repository, "rev-parse", f"{EXPECTED_COMMIT}:{relative.as_posix()}")
        .decode()
        .strip(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _lfs_file_record(repository: Path, relative: Path) -> dict[str, object]:
    data = (repository / relative).read_bytes()
    pointer = _git(repository, "show", f"{EXPECTED_COMMIT}:{relative.as_posix()}")
    match = _LFS_POINTER.fullmatch(pointer)
    if match is None:
        raise CaptureError(f"performance database commit object is not an LFS pointer: {relative}")
    expected_sha = match.group(1).decode()
    expected_size = int(match.group(2))
    actual_sha = hashlib.sha256(data).hexdigest()
    if (actual_sha, len(data)) != (expected_sha, expected_size):
        raise CaptureError(f"materialized LFS database drift: {relative}")
    return {
        "path": relative.as_posix(),
        "git_lfs_pointer_blob": _git(
            repository, "rev-parse", f"{EXPECTED_COMMIT}:{relative.as_posix()}"
        )
        .decode()
        .strip(),
        "sha256": actual_sha,
        "size_bytes": len(data),
    }


def _git(repository: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise CaptureError(
            f"git {' '.join(args)} failed: {completed.stderr.decode(errors='replace').strip()}"
        )
    return completed.stdout


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaptureError(f"cannot load JSON {path}: {error}") from error
    return _mapping(value, str(path))


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CaptureError(f"{location} must be an object")
    return value


def _list(value: object, location: str) -> list[object]:
    if not isinstance(value, list):
        raise CaptureError(f"{location} must be an array")
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise CaptureError(f"{location} must be a non-empty string")
    return value


def _sha_string(value: object, location: str) -> str:
    text = _string(value, location)
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise CaptureError(f"{location} must be a SHA-256")
    return text


def _safe_relative(value: object, location: str) -> Path:
    text = _string(value, location)
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts:
        raise CaptureError(f"{location} must be a safe relative path")
    return Path(*pure.parts)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Mapping[str, Any] | Sequence[Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _sha256_json(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
