#!/usr/bin/env python3
"""Fail-closed declaration and optional live audit for source-lock.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_COMMITS = {
    "vllm": "644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504",
    "mooncake": "f161118c18dbea1b56dd5c7908b9eaa440353e2e",
    "sglsim_reference": "ca1fe76e88959a2bac0f6060e3042dc2c7d4f855",
    "aiconfigurator": "4b9d9dc51e02b5e9d4acc3688f3edf41693834c6",
}
EXPECTED_MODEL_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
EXPECTED_MODEL_CARD = {
    "path": "README.md",
    "revision": EXPECTED_MODEL_REVISION,
    "blob_url": (f"https://huggingface.co/Qwen/Qwen3-8B/blob/{EXPECTED_MODEL_REVISION}/README.md"),
    "resolve_url": (
        f"https://huggingface.co/Qwen/Qwen3-8B/resolve/{EXPECTED_MODEL_REVISION}/README.md"
    ),
    "git_blob": "ecc3ebd0849aa08d9484bd911dddfd5261b10d30",
    "sha256": "0f36caaff9c2516411a7738db384606263ba653c1e63e61d72f511606164d5a6",
    "size_bytes": 16660,
}
EXPECTED_VLLM_KV_HEAD_FILE = {
    "path": "vllm/config/model.py",
    "source": "commit_object",
    "git_blob": "b41ab189c108573cc9ec652fd5b035b6d4ca3549",
    "sha256": "84d887740d547d4a9c3d52a05bc2b2806437d9627780a87853f59dc2f9de7266",
}
EXPECTED_PATENT_SHA256 = "d80de557e63edfc0d77a860a262470bf3dca666340724e9a6bfe7f34a507ecb9"
EXPECTED_TRACE_SHA256 = "29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276"


@dataclass
class AuditReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def _is_sha40(value: object) -> bool:
    return isinstance(value, str) and HEX40.fullmatch(value) is not None


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _mapping(value: object, location: str, report: AuditReport) -> dict[str, Any]:
    if not isinstance(value, dict):
        report.errors.append(f"{location}: expected object")
        return {}
    return value


def _list(value: object, location: str, report: AuditReport) -> list[Any]:
    if not isinstance(value, list):
        report.errors.append(f"{location}: expected array")
        return []
    return value


def _validate_relative_path(value: object, location: str, report: AuditReport) -> None:
    if not isinstance(value, str) or not value:
        report.errors.append(f"{location}: expected non-empty relative path")
        return
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        report.errors.append(f"{location}: path must stay within its declared repository")


def _validate_worktree(value: object, location: str, report: AuditReport) -> None:
    worktree = _mapping(value, location, report)
    if not isinstance(worktree.get("dirty"), bool):
        report.errors.append(f"{location}.dirty: expected boolean")
    for key in ("tracked_change_count", "untracked_entry_count"):
        count = worktree.get(key)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            report.errors.append(f"{location}.{key}: expected non-negative integer")
    if not _is_sha256(worktree.get("porcelain_sha256")):
        report.errors.append(f"{location}.porcelain_sha256: expected SHA-256")
    dirty = worktree.get("dirty")
    total = int(worktree.get("tracked_change_count", 0)) + int(
        worktree.get("untracked_entry_count", 0)
    )
    if isinstance(dirty, bool) and dirty != (total > 0):
        report.errors.append(f"{location}: dirty flag disagrees with declared counts")


def _validate_repo_file(item: object, location: str, report: AuditReport) -> None:
    entry = _mapping(item, location, report)
    _validate_relative_path(entry.get("path"), f"{location}.path", report)
    source = entry.get("source")
    if source not in {"commit_object", "worktree_snapshot"}:
        report.errors.append(f"{location}.source: unsupported source mode {source!r}")
    if not _is_sha256(entry.get("sha256")):
        report.errors.append(f"{location}.sha256: expected SHA-256")
    blob = entry.get("git_blob")
    if source == "commit_object" and not _is_sha40(blob):
        report.errors.append(f"{location}.git_blob: commit_object requires Git blob")
    if blob is not None and not _is_sha40(blob):
        report.errors.append(f"{location}.git_blob: expected Git blob or null")
    commit_sha = entry.get("commit_sha256")
    if commit_sha is not None and not _is_sha256(commit_sha):
        report.errors.append(f"{location}.commit_sha256: expected SHA-256 or null")
    if source == "worktree_snapshot":
        if entry.get("worktree_state") not in {"modified", "untracked", "clean"}:
            report.errors.append(f"{location}.worktree_state: snapshot requires an explicit state")
        if blob is not None and commit_sha is None:
            report.errors.append(
                f"{location}: tracked snapshot with a base blob needs commit_sha256"
            )


def validate_declarations(lock: object) -> AuditReport:
    """Validate schema shape and project-specific immutable decisions."""

    report = AuditReport()
    root = _mapping(lock, "$", report)
    if root.get("schema") != "moonkvsim.source-lock.v1":
        report.errors.append("$.schema: expected moonkvsim.source-lock.v1")

    readiness = _mapping(root.get("readiness"), "$.readiness", report)
    blockers = _list(readiness.get("blockers"), "$.readiness.blockers", report)
    blocker_ids: set[str] = set()
    for index, raw in enumerate(blockers):
        blocker = _mapping(raw, f"$.readiness.blockers[{index}]", report)
        blocker_id = blocker.get("id")
        if not isinstance(blocker_id, str) or not blocker_id:
            report.errors.append(f"$.readiness.blockers[{index}].id: required")
        elif blocker_id in blocker_ids:
            report.errors.append(f"$.readiness.blockers: duplicate id {blocker_id}")
        else:
            blocker_ids.add(blocker_id)
            report.blockers.append(blocker_id)
        for key in ("area", "reason", "required_evidence"):
            if not isinstance(blocker.get(key), str) or not blocker[key]:
                report.errors.append(
                    f"$.readiness.blockers[{index}].{key}: non-empty string required"
                )
    if blockers and readiness.get("formal_run_allowed") is not False:
        report.errors.append("$.readiness.formal_run_allowed: must be false while blockers exist")

    repositories = _mapping(root.get("repositories"), "$.repositories", report)
    if set(repositories) != set(EXPECTED_COMMITS):
        report.errors.append(
            "$.repositories: expected exactly " + ", ".join(sorted(EXPECTED_COMMITS))
        )
    for name, expected_commit in EXPECTED_COMMITS.items():
        repo = _mapping(repositories.get(name), f"$.repositories.{name}", report)
        path = repo.get("repository")
        if not isinstance(path, str) or not Path(path).is_absolute():
            report.errors.append(f"$.repositories.{name}.repository: absolute path required")
        if repo.get("kind") != "git":
            report.errors.append(f"$.repositories.{name}.kind: expected git")
        if repo.get("commit") != expected_commit:
            report.errors.append(f"$.repositories.{name}.commit: expected {expected_commit}")
        if not _is_sha40(repo.get("tree")):
            report.errors.append(f"$.repositories.{name}.tree: expected Git tree")
        _validate_worktree(
            repo.get("worktree"),
            f"$.repositories.{name}.worktree",
            report,
        )
        files = _list(repo.get("files"), f"$.repositories.{name}.files", report)
        if not files:
            report.errors.append(f"$.repositories.{name}.files: may not be empty")
        seen_paths: set[str] = set()
        for index, item in enumerate(files):
            location = f"$.repositories.{name}.files[{index}]"
            _validate_repo_file(item, location, report)
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                if item["path"] in seen_paths:
                    report.errors.append(f"{location}.path: duplicate file")
                seen_paths.add(item["path"])

    mooncake = _mapping(repositories.get("mooncake"), "$.repositories.mooncake", report)
    if mooncake.get("source_policy") != "commit_object_only":
        report.errors.append(
            "$.repositories.mooncake.source_policy: baseline must use commit objects"
        )
    for index, item in enumerate(mooncake.get("files", [])):
        if isinstance(item, dict) and item.get("source") != "commit_object":
            report.errors.append(
                f"$.repositories.mooncake.files[{index}]: worktree source forbidden"
            )

    vllm = _mapping(repositories.get("vllm"), "$.repositories.vllm", report)
    vllm_files_by_path = {
        item.get("path"): item
        for item in vllm.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    kv_head_file = vllm_files_by_path.get(EXPECTED_VLLM_KV_HEAD_FILE["path"])
    if kv_head_file is None:
        report.errors.append(
            "$.repositories.vllm.files: vllm/config/model.py KV-head source required"
        )
    else:
        for key, expected in EXPECTED_VLLM_KV_HEAD_FILE.items():
            if kv_head_file.get(key) != expected:
                report.errors.append(
                    f"$.repositories.vllm.files[vllm/config/model.py].{key}: expected {expected}"
                )
        semantic = kv_head_file.get("locked_semantic")
        if not isinstance(semantic, str) or (
            "max(1, total_num_kv_heads // tensor_parallel_size)" not in semantic
        ):
            report.errors.append(
                "$.repositories.vllm.files[vllm/config/model.py].locked_semantic: "
                "must preserve TP KV-head replication"
            )

    aiconfig = _mapping(
        repositories.get("aiconfigurator"),
        "$.repositories.aiconfigurator",
        report,
    )
    if aiconfig.get("package_version") != "0.9.0":
        report.errors.append("$.repositories.aiconfigurator.package_version: expected 0.9.0")
    database = _mapping(
        aiconfig.get("database"),
        "$.repositories.aiconfigurator.database",
        report,
    )
    if database.get("calibrated") is not False:
        report.errors.append("$.repositories.aiconfigurator.database.calibrated: expected false")
    if database.get("formal_use_allowed") is not False:
        report.errors.append(
            "$.repositories.aiconfigurator.database.formal_use_allowed: expected false"
        )
    if "SRC-BLOCK-001" not in blocker_ids:
        report.errors.append("SRC-BLOCK-001 must record uncalibrated AIConfigurator")

    model = _mapping(root.get("model_tokenizer"), "$.model_tokenizer", report)
    if model.get("revision") != EXPECTED_MODEL_REVISION:
        report.errors.append(f"$.model_tokenizer.revision: expected {EXPECTED_MODEL_REVISION}")
    model_card = _mapping(
        model.get("official_model_card"),
        "$.model_tokenizer.official_model_card",
        report,
    )
    for key, expected in EXPECTED_MODEL_CARD.items():
        if model_card.get(key) != expected:
            report.errors.append(
                f"$.model_tokenizer.official_model_card.{key}: expected {expected}"
            )
    if model_card.get("evidence_role") != "fixed_revision_configuration_guidance_only":
        report.errors.append(
            "$.model_tokenizer.official_model_card.evidence_role: "
            "must remain configuration guidance only"
        )
    if model_card.get("experiment_pass") is not False:
        report.errors.append("$.model_tokenizer.official_model_card.experiment_pass: must be false")
    model_files = _list(model.get("files"), "$.model_tokenizer.files", report)
    for index, item in enumerate(model_files):
        entry = _mapping(item, f"$.model_tokenizer.files[{index}]", report)
        _validate_relative_path(
            entry.get("path"),
            f"$.model_tokenizer.files[{index}].path",
            report,
        )
        if not _is_sha256(entry.get("sha256")):
            report.errors.append(f"$.model_tokenizer.files[{index}].sha256: expected SHA-256")
    tokenizer = _mapping(model.get("tokenizer"), "$.model_tokenizer.tokenizer", report)
    if not _is_sha256(tokenizer.get("chat_template_sha256")):
        report.errors.append("$.model_tokenizer.tokenizer.chat_template_sha256: expected SHA-256")
    model_config = _mapping(
        model.get("model_config"),
        "$.model_tokenizer.model_config",
        report,
    )
    context = _mapping(
        model.get("context_128k"),
        "$.model_tokenizer.context_128k",
        report,
    )
    native_limit = model_config.get("max_position_embeddings")
    requested_limit = context.get("requested_max_model_len")
    expected_context = {
        "requested_max_model_len": 131072,
        "status": "proposed_unvalidated",
        "readiness": "BLOCKED",
        "engine": "vllm",
        "vllm_revision": EXPECTED_COMMITS["vllm"],
        "max_model_len": 131072,
        "model_card_is_experiment_evidence": False,
        "formal_128k_allowed": False,
    }
    for key, expected in expected_context.items():
        if context.get(key) != expected:
            report.errors.append(f"$.model_tokenizer.context_128k.{key}: expected {expected}")
    rope_scaling = _mapping(
        context.get("rope_scaling"),
        "$.model_tokenizer.context_128k.rope_scaling",
        report,
    )
    expected_rope_scaling = {
        "rope_type": "yarn",
        "factor": 4.0,
        "original_max_position_embeddings": 32768,
    }
    if rope_scaling != expected_rope_scaling:
        report.errors.append(
            f"$.model_tokenizer.context_128k.rope_scaling: expected {expected_rope_scaling}"
        )
    risk = context.get("static_yarn_short_context_risk")
    if not isinstance(risk, str) or "shorter-context" not in risk:
        report.errors.append(
            "$.model_tokenizer.context_128k.static_yarn_short_context_risk: "
            "short-context risk must be explicit"
        )
    physical_validation = _mapping(
        context.get("physical_validation"),
        "$.model_tokenizer.context_128k.physical_validation",
        report,
    )
    if physical_validation.get("required") is not True:
        report.errors.append(
            "$.model_tokenizer.context_128k.physical_validation.required: must be true"
        )
    if physical_validation.get("completed") is not False:
        report.errors.append(
            "$.model_tokenizer.context_128k.physical_validation.completed: "
            "must remain false until evidence is locked"
        )
    if physical_validation.get("evidence_path") is not None:
        report.errors.append(
            "$.model_tokenizer.context_128k.physical_validation.evidence_path: "
            "must be null while unvalidated"
        )
    if (
        isinstance(native_limit, int)
        and isinstance(requested_limit, int)
        and requested_limit > native_limit
    ):
        if context.get("formal_128k_allowed") is not False:
            report.errors.append("$.model_tokenizer.context_128k: formal use must remain false")
        if "SRC-BLOCK-002" not in blocker_ids:
            report.errors.append("SRC-BLOCK-002 must record the 128K model gap")

    artifacts = _mapping(root.get("artifacts"), "$.artifacts", report)
    for name, raw in artifacts.items():
        artifact = _mapping(raw, f"$.artifacts.{name}", report)
        if not isinstance(artifact.get("path"), str) or not artifact["path"]:
            report.errors.append(f"$.artifacts.{name}.path: required")
        if artifact.get("path_base") not in {"absolute", "project_root"}:
            report.errors.append(f"$.artifacts.{name}.path_base: expected absolute or project_root")
        if not _is_sha256(artifact.get("sha256")):
            report.errors.append(f"$.artifacts.{name}.sha256: expected SHA-256")
    patent = _mapping(artifacts.get("aegiskv_patent"), "$.artifacts.aegiskv_patent", report)
    trace = _mapping(artifacts.get("weka_trace"), "$.artifacts.weka_trace", report)
    if patent.get("sha256") != EXPECTED_PATENT_SHA256:
        report.errors.append("$.artifacts.aegiskv_patent.sha256: unexpected hash")
    if trace.get("sha256") != EXPECTED_TRACE_SHA256:
        report.errors.append("$.artifacts.weka_trace.sha256: unexpected hash")
    trace_collection = _mapping(
        trace.get("collection_interval"),
        "$.artifacts.weka_trace.collection_interval",
        report,
    )
    collection_value = trace_collection.get("value")
    if collection_value is None:
        if trace_collection.get("status") != ("not_disclosed_by_reviewed_public_sources"):
            report.errors.append(
                "$.artifacts.weka_trace.collection_interval.status: "
                "unknown interval must remain explicitly undisclosed"
            )
        if trace_collection.get("build_timestamp_is_collection_interval") is not False:
            report.errors.append(
                "$.artifacts.weka_trace.collection_interval: a build timestamp "
                "must not be substituted for the capture interval"
            )
        if "SRC-BLOCK-003" not in blocker_ids:
            report.errors.append("SRC-BLOCK-003 must record the missing trace collection interval")
    elif not isinstance(collection_value, str) or not collection_value:
        report.errors.append(
            "$.artifacts.weka_trace.collection_interval.value: "
            "expected a non-empty interval string or null"
        )
    collection_sources = _list(
        trace_collection.get("source_urls"),
        "$.artifacts.weka_trace.collection_interval.source_urls",
        report,
    )
    if not collection_sources or not all(
        isinstance(source, str) and source for source in collection_sources
    ):
        report.errors.append(
            "$.artifacts.weka_trace.collection_interval.source_urls: "
            "at least one non-empty publisher source is required"
        )
    return report


def _run_git(repository: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_porcelain(status: bytes) -> tuple[int, int]:
    tracked = 0
    untracked = 0
    for line in status.splitlines():
        if line.startswith(b"??"):
            untracked += 1
        elif line:
            tracked += 1
    return tracked, untracked


def verify_git_repository_live(
    name: str,
    spec: dict[str, Any],
    report: AuditReport,
) -> None:
    """Verify one repository against commit objects and declared dirty state."""

    repository = Path(str(spec["repository"]))
    if not repository.is_dir():
        report.errors.append(f"{name}: repository missing: {repository}")
        return
    commit = str(spec["commit"])
    try:
        actual_tree = _run_git(repository, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    except RuntimeError as error:
        report.errors.append(f"{name}: {error}")
        return
    if actual_tree != spec.get("tree"):
        report.errors.append(
            f"{name}: tree mismatch: declared={spec.get('tree')} actual={actual_tree}"
        )

    for entry in spec.get("files", []):
        relative = str(entry["path"])
        source = entry["source"]
        blob = entry.get("git_blob")
        if blob is not None:
            try:
                actual_blob = (
                    _run_git(repository, "rev-parse", f"{commit}:{relative}").decode().strip()
                )
                commit_bytes = _run_git(repository, "show", f"{commit}:{relative}")
            except RuntimeError as error:
                report.errors.append(f"{name}:{relative}: {error}")
                continue
            if actual_blob != blob:
                report.errors.append(
                    f"{name}:{relative}: blob mismatch declared={blob} actual={actual_blob}"
                )
            expected_commit_sha = (
                entry["sha256"] if source == "commit_object" else entry["commit_sha256"]
            )
            if _sha256_bytes(commit_bytes) != expected_commit_sha:
                report.errors.append(f"{name}:{relative}: commit-object SHA-256 mismatch")
        if source == "worktree_snapshot":
            worktree_path = repository / relative
            if not worktree_path.is_file():
                report.errors.append(f"{name}:{relative}: worktree snapshot missing")
            elif _sha256_file(worktree_path) != entry["sha256"]:
                report.errors.append(f"{name}:{relative}: worktree SHA-256 mismatch")

    for generated in spec.get("generated_files", []):
        path = repository / str(generated["path"])
        if not path.is_file():
            report.errors.append(f"{name}:{generated['path']}: generated file missing")
        elif _sha256_file(path) != generated["sha256"]:
            report.errors.append(f"{name}:{generated['path']}: generated file SHA-256 mismatch")

    worktree = spec["worktree"]
    try:
        status = _run_git(
            repository,
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
        )
    except RuntimeError as error:
        report.errors.append(f"{name}: {error}")
        return
    tracked, untracked = _count_porcelain(status)
    if tracked != worktree["tracked_change_count"]:
        report.errors.append(
            f"{name}: tracked dirty count mismatch "
            f"declared={worktree['tracked_change_count']} actual={tracked}"
        )
    if untracked != worktree["untracked_entry_count"]:
        report.errors.append(
            f"{name}: untracked count mismatch "
            f"declared={worktree['untracked_entry_count']} actual={untracked}"
        )
    if _sha256_bytes(status) != worktree["porcelain_sha256"]:
        report.errors.append(f"{name}: porcelain status fingerprint mismatch")

    database = spec.get("database")
    if isinstance(database, dict):
        example = database.get("discovered_materialized_example")
        if isinstance(example, dict):
            relative = str(example["path"])
            materialized = repository / relative
            if not materialized.is_file():
                report.errors.append(f"{name}:{relative}: materialized LFS file missing")
            else:
                if _sha256_file(materialized) != example["materialized_sha256"]:
                    report.errors.append(f"{name}:{relative}: materialized LFS SHA-256 mismatch")
                if materialized.stat().st_size != example["materialized_size_bytes"]:
                    report.errors.append(f"{name}:{relative}: materialized size mismatch")
            try:
                pointer_blob = (
                    _run_git(repository, "rev-parse", f"{commit}:{relative}").decode().strip()
                )
                pointer_bytes = _run_git(repository, "show", f"{commit}:{relative}")
            except RuntimeError as error:
                report.errors.append(f"{name}:{relative}: {error}")
            else:
                if pointer_blob != example["git_lfs_pointer_blob"]:
                    report.errors.append(f"{name}:{relative}: LFS pointer blob mismatch")
                if _sha256_bytes(pointer_bytes) != example["git_lfs_pointer_sha256"]:
                    report.errors.append(f"{name}:{relative}: LFS pointer SHA mismatch")
    report.verified.append(name)


def _resolve_artifact(path_base: str, raw_path: str, project_root: Path) -> Path:
    if path_base == "absolute":
        return Path(raw_path)
    return project_root / raw_path


def _verify_model_live(model: dict[str, Any], report: AuditReport) -> None:
    cache = Path(str(model["cache_repository"]))
    revision = str(model["revision"])
    observed_ref = cache / "refs" / str(model["observed_ref"])
    if not observed_ref.is_file():
        report.errors.append("model_tokenizer: observed ref missing")
    elif observed_ref.read_text().strip() != revision:
        report.errors.append("model_tokenizer: observed ref no longer matches revision")
    snapshot = Path(str(model["snapshot_path"]))
    if snapshot.name != revision or not snapshot.is_dir():
        report.errors.append("model_tokenizer: immutable snapshot directory missing")
        return
    for entry in model["files"]:
        path = snapshot / str(entry["path"])
        if not path.is_file():
            report.errors.append(f"model_tokenizer:{entry['path']}: missing")
        elif _sha256_file(path) != entry["sha256"]:
            report.errors.append(f"model_tokenizer:{entry['path']}: SHA-256 mismatch")
    try:
        tokenizer_config = json.loads((snapshot / "tokenizer_config.json").read_text())
        model_config = json.loads((snapshot / "config.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        report.errors.append(f"model_tokenizer: cannot parse config: {error}")
        return
    template = tokenizer_config.get("chat_template")
    if not isinstance(template, str):
        report.errors.append("model_tokenizer: embedded chat template missing")
    else:
        tokenizer = model["tokenizer"]
        if _sha256_bytes(template.encode()) != tokenizer["chat_template_sha256"]:
            report.errors.append("model_tokenizer: chat template SHA-256 mismatch")
        if len(template.encode()) != tokenizer["chat_template_utf8_length"]:
            report.errors.append("model_tokenizer: chat template length mismatch")
    expected_model = model["model_config"]
    for key in (
        "model_type",
        "hidden_size",
        "num_hidden_layers",
        "num_attention_heads",
        "num_key_value_heads",
        "head_dim",
        "max_position_embeddings",
        "rope_theta",
        "rope_scaling",
    ):
        if model_config.get(key) != expected_model.get(key):
            report.errors.append(f"model_tokenizer: config field {key} changed")
    report.verified.append("model_tokenizer")


def verify_live(
    lock: dict[str, Any],
    lock_path: Path,
    report: AuditReport,
) -> None:
    for name, spec in lock["repositories"].items():
        verify_git_repository_live(name, spec, report)
    project_root = lock_path.resolve().parent.parent
    for name, artifact in lock["artifacts"].items():
        path = _resolve_artifact(
            str(artifact["path_base"]),
            str(artifact["path"]),
            project_root,
        )
        if not path.is_file():
            report.errors.append(f"artifact {name}: missing: {path}")
            continue
        if _sha256_file(path) != artifact["sha256"]:
            report.errors.append(f"artifact {name}: SHA-256 mismatch")
        expected_size = artifact.get("size_bytes")
        if isinstance(expected_size, int) and path.stat().st_size != expected_size:
            report.errors.append(f"artifact {name}: size mismatch")
        if artifact.get("zip_integrity_verified") is True:
            try:
                with zipfile.ZipFile(path) as archive:
                    failed_member = archive.testzip()
            except (OSError, zipfile.BadZipFile) as error:
                report.errors.append(f"artifact {name}: invalid ZIP: {error}")
            else:
                if failed_member is not None:
                    report.errors.append(f"artifact {name}: corrupt ZIP member {failed_member}")
        report.verified.append(f"artifact:{name}")
    _verify_model_live(lock["model_tokenizer"], report)


def audit_lock(
    lock: object,
    *,
    lock_path: Path,
    live: bool = False,
) -> AuditReport:
    report = validate_declarations(lock)
    if live and report.valid:
        verify_live(lock, lock_path, report)  # type: ignore[arg-type]
    return report


def _render_text(report: AuditReport, *, live: bool) -> str:
    if report.errors:
        status = "INVALID"
    elif report.blockers:
        status = "VALID_WITH_BLOCKERS"
    else:
        status = "READY"
    lines = [
        f"source-lock: {status}",
        f"live_verification: {'enabled' if live else 'disabled'}",
        f"errors: {len(report.errors)}",
        f"blockers: {len(report.blockers)}",
    ]
    lines.extend(f"ERROR: {item}" for item in report.errors)
    lines.extend(f"BLOCKER: {item}" for item in report.blockers)
    lines.extend(f"WARNING: {item}" for item in report.warnings)
    if live:
        lines.extend(f"VERIFIED: {item}" for item in report.verified)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock",
        type=Path,
        default=project_root / "reference" / "source-lock.json",
    )
    parser.add_argument(
        "--verify-live",
        action="store_true",
        help="also compare declared repositories and artifacts with local state",
    )
    parser.add_argument(
        "--strict-ready",
        action="store_true",
        help="return failure while declared readiness blockers remain",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON summary")
    args = parser.parse_args(argv)
    try:
        lock = json.loads(args.lock.read_text())
    except (OSError, json.JSONDecodeError) as error:
        print(f"source-lock: cannot read {args.lock}: {error}", file=sys.stderr)
        return 2
    report = audit_lock(lock, lock_path=args.lock, live=args.verify_live)
    if args.json:
        print(
            json.dumps(
                {
                    "valid": report.valid,
                    "ready": report.valid and not report.blockers,
                    "live_verification": args.verify_live,
                    "errors": report.errors,
                    "blockers": report.blockers,
                    "warnings": report.warnings,
                    "verified": report.verified,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(_render_text(report, live=args.verify_live))
    if report.errors:
        return 1
    if args.strict_ready and report.blockers:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
