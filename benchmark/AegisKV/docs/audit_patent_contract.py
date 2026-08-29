#!/usr/bin/env python3
"""Fail-closed audit for the immutable AegisKV patent contract bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml

SCHEMA = "moonkvsim.aegiskv.patent-contract.v1"
MANIFEST_SCHEMA = "moonkvsim.aegiskv.source-manifest.v1"
PATENT_SHA256 = "d80de557e63edfc0d77a860a262470bf3dca666340724e9a6bfe7f34a507ecb9"
PATENT_PATH = "benchmark/AegisKV/docs/patent/AegisKV专利交底书-final-version.docx"
MANIFEST_PATH = "benchmark/AegisKV/docs/provenance/SOURCE_MANIFEST.json"

REQUIRED_CATEGORIES = (
    "authority_and_directory",
    "rental_value",
    "lazy_refresh",
    "independent_admission",
    "commit_state",
    "hbm_quota_aimd",
    "failure_recovery",
)
REQUIRED_CLAUSE_IDS = (
    "AUTHORITY-001",
    "DIRECTORY-001",
    "DIRECTORY-002",
    "RENTAL-001",
    "RENTAL-002",
    "RENTAL-003",
    "LAZY-001",
    "LAZY-002",
    "LAZY-003",
    "POOL-001",
    "ADMISSION-001",
    "ADMISSION-002",
    "TRANSFER-001",
    "TRANSFER-002",
    "TRANSFER-003",
    "COMMIT-001",
    "COMMIT-002",
    "COMMIT-003",
    "AIMD-001",
    "AIMD-002",
    "AIMD-003",
    "AIMD-004",
    "RECOVERY-001",
    "RECOVERY-002",
    "RECOVERY-003",
    "RECOVERY-004",
    "RECOVERY-005",
)
EXPECTED_SEMANTIC_SETS = {
    "policy_pools": ["PEER_HBM", "STORE_DRAM"],
    "residency_states": ["HBM_ONLY", "DRAM_ONLY", "HBM_AND_DRAM", "BYPASS"],
    "path_commit_states": ["PENDING", "COMMITTED", "ABORTED"],
    "recovery_sources": ["PEER_HBM", "STORE_DRAM", "RECOMPUTE"],
    "forbidden_semantics": [
        "target_hbm_to_store_dram_writeback",
        "target_owned_background_destage",
        "dram_commit_prerequisite_for_hbm_admission",
        "one_tier_failure_aborts_the_other_tier",
        "second_reuse_or_protection_directory",
    ],
}
ALLOWED_OWNERS = {
    "python/moonkvsim/aegiskv/audit.py",
    "python/moonkvsim/aegiskv/controller.py",
    "python/moonkvsim/aegiskv/failure_fence.py",
    "python/moonkvsim/aegiskv/hbm_quota_aimd.py",
    "python/moonkvsim/aegiskv/kv_directory.py",
    "python/moonkvsim/aegiskv/lazy_refresh.py",
    "python/moonkvsim/aegiskv/peer_hbm_pool.py",
    "python/moonkvsim/aegiskv/propagation.py",
    "python/moonkvsim/aegiskv/recovery_planner.py",
    "python/moonkvsim/aegiskv/rental_value.py",
    "python/moonkvsim/aegiskv/slack_landlord.py",
}
EXPECTED_CHECKSUM_PATHS = {
    PATENT_PATH,
    "benchmark/AegisKV/docs/design/patent-contract.yaml",
    MANIFEST_PATH,
    "benchmark/AegisKV/docs/audit_patent_contract.py",
}
COMPATIBILITY_GLYPHS = "ₚᵢₓᵣᵧʳ"
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
TEST_ID = re.compile(r"^AEGIS-[A-Z0-9-]+-[0-9]{3}$")


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeyLoader, node: yaml.nodes.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_contract(path: Path) -> dict[str, Any]:
    value = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    if not isinstance(value, dict):
        raise ValueError("patent contract must be a YAML mapping")
    return value


def load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_pairs
    )
    if not isinstance(value, dict):
        raise ValueError("source manifest must be a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exact_keys(
    value: Mapping[str, Any], expected: set[str], location: str, errors: list[str]
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        errors.append(f"{location}: missing keys {missing}")
    if unknown:
        errors.append(f"{location}: unknown keys {unknown}")


def _mapping(value: Any, location: str, errors: list[str]) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        errors.append(f"{location}: expected mapping")
        return None
    return value


def validate_manifest(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    _exact_keys(
        manifest,
        {"schema", "manifest_status", "scope", "source_count", "sources"},
        "manifest",
        errors,
    )
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append(f"manifest.schema: expected {MANIFEST_SCHEMA!r}")
    if manifest.get("manifest_status") != "active_design_input_only":
        errors.append("manifest.manifest_status: must be active_design_input_only")
    if manifest.get("source_count") != 1:
        errors.append("manifest.source_count: must be exactly 1")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or len(sources) != 1:
        errors.append("manifest.sources: must contain exactly the current patent input")
        return errors

    source = _mapping(sources[0], "manifest.sources[0]", errors)
    if source is None:
        return errors
    expected_keys = {
        "source_id",
        "source_path",
        "source_repository",
        "source_commit",
        "source_dirty",
        "source_tracked",
        "source_sha256",
        "destination_path",
        "destination_sha256",
        "role",
        "evidence_class",
        "status",
        "authority",
    }
    _exact_keys(source, expected_keys, "manifest.sources[0]", errors)
    expected_values = {
        "source_id": "aegiskv-patent-final-d80de557",
        "source_repository": "SGLSim",
        "source_dirty": True,
        "source_tracked": False,
        "source_sha256": PATENT_SHA256,
        "destination_path": PATENT_PATH,
        "destination_sha256": PATENT_SHA256,
        "role": "design",
        "evidence_class": "immutable_design_input",
        "status": "active",
        "authority": "patent-final",
    }
    for key, expected in expected_values.items():
        if source.get(key) != expected:
            errors.append(f"manifest.sources[0].{key}: expected {expected!r}")
    source_path = source.get("source_path")
    if not isinstance(source_path, str) or not Path(source_path).is_absolute():
        errors.append("manifest.sources[0].source_path: must be an absolute provenance path")
    commit = source.get("source_commit")
    if not isinstance(commit, str) or not HEX_40.fullmatch(commit):
        errors.append("manifest.sources[0].source_commit: must be a 40-hex commit")
    return errors


def validate_contract(
    contract: Mapping[str, Any], manifest: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    _exact_keys(
        contract,
        {
            "schema",
            "contract_id",
            "contract_status",
            "manual_review",
            "evidence_boundary",
            "authority",
            "semantic_sets",
            "coverage",
            "clauses",
        },
        "contract",
        errors,
    )
    if contract.get("schema") != SCHEMA:
        errors.append(f"contract.schema: expected {SCHEMA!r}")
    if contract.get("contract_status") != "machine_transcribed_pending_manual_review":
        errors.append("contract.contract_status: must preserve the pending-manual-review boundary")
    if contract.get("manual_review") != "pending":
        errors.append("contract.manual_review: must remain pending until a recorded human review")
    boundary = contract.get("evidence_boundary")
    if not isinstance(boundary, str) or "does not prove" not in boundary:
        errors.append("contract.evidence_boundary: must reject runtime/evidence overclaiming")

    authority = _mapping(contract.get("authority"), "contract.authority", errors)
    if authority is not None:
        _exact_keys(
            authority,
            {
                "kind",
                "precedence",
                "document_path",
                "sha256",
                "provenance_manifest",
                "ooxml_contract",
            },
            "contract.authority",
            errors,
        )
        expected_authority = {
            "kind": "patent-final",
            "precedence": "highest",
            "document_path": PATENT_PATH,
            "sha256": PATENT_SHA256,
            "provenance_manifest": MANIFEST_PATH,
        }
        for key, expected in expected_authority.items():
            if authority.get(key) != expected:
                errors.append(f"contract.authority.{key}: expected {expected!r}")

    semantic_sets = _mapping(contract.get("semantic_sets"), "contract.semantic_sets", errors)
    if semantic_sets is not None:
        _exact_keys(semantic_sets, set(EXPECTED_SEMANTIC_SETS), "contract.semantic_sets", errors)
        for key, expected in EXPECTED_SEMANTIC_SETS.items():
            if semantic_sets.get(key) != expected:
                errors.append(
                    f"contract.semantic_sets.{key}: expected exact ordered set {expected}"
                )

    coverage = _mapping(contract.get("coverage"), "contract.coverage", errors)
    if coverage is not None:
        _exact_keys(
            coverage,
            {"required_categories", "required_clause_ids"},
            "contract.coverage",
            errors,
        )
        if coverage.get("required_categories") != list(REQUIRED_CATEGORIES):
            errors.append("contract.coverage.required_categories: incomplete or reordered")
        if coverage.get("required_clause_ids") != list(REQUIRED_CLAUSE_IDS):
            errors.append("contract.coverage.required_clause_ids: incomplete or reordered")

    clauses = contract.get("clauses")
    if not isinstance(clauses, list):
        errors.append("contract.clauses: expected list")
        return errors
    clause_ids: list[str] = []
    test_ids: list[str] = []
    categories: set[str] = set()
    clause_keys = {
        "id",
        "category",
        "requirement",
        "normative",
        "authority_locator",
        "owner",
        "test_id",
        "status",
    }
    for index, raw_clause in enumerate(clauses):
        location = f"contract.clauses[{index}]"
        clause = _mapping(raw_clause, location, errors)
        if clause is None:
            continue
        _exact_keys(clause, clause_keys, location, errors)
        clause_id = clause.get("id")
        if not isinstance(clause_id, str):
            errors.append(f"{location}.id: expected string")
        else:
            clause_ids.append(clause_id)
        category = clause.get("category")
        if category not in REQUIRED_CATEGORIES:
            errors.append(f"{location}.category: unknown category {category!r}")
        elif isinstance(category, str):
            categories.add(category)
        requirement = clause.get("requirement")
        if not isinstance(requirement, str) or len(requirement.strip()) < 20:
            errors.append(f"{location}.requirement: missing normative detail")
        if clause.get("normative") not in {"MUST", "MUST_NOT"}:
            errors.append(f"{location}.normative: expected MUST or MUST_NOT")
        locator = _mapping(clause.get("authority_locator"), f"{location}.authority_locator", errors)
        if locator is not None:
            _exact_keys(
                locator,
                {"docx_section", "anchor"},
                f"{location}.authority_locator",
                errors,
            )
            for key in ("docx_section", "anchor"):
                if not isinstance(locator.get(key), str) or not locator[key].strip():
                    errors.append(f"{location}.authority_locator.{key}: required")
        if clause.get("owner") not in ALLOWED_OWNERS:
            errors.append(f"{location}.owner: not a planned AegisKV code owner")
        test_id = clause.get("test_id")
        if not isinstance(test_id, str) or not TEST_ID.fullmatch(test_id):
            errors.append(f"{location}.test_id: invalid test id")
        else:
            test_ids.append(test_id)
        expected_status = (
            "verified_design_input" if clause_id == "AUTHORITY-001" else "specified_unimplemented"
        )
        if clause.get("status") != expected_status:
            errors.append(f"{location}.status: expected {expected_status!r}")

    if clause_ids != list(REQUIRED_CLAUSE_IDS):
        errors.append("contract.clauses: required clause ids are missing, duplicated, or reordered")
    if len(test_ids) != len(set(test_ids)):
        errors.append("contract.clauses: test_id values must be unique")
    if categories != set(REQUIRED_CATEGORIES):
        errors.append("contract.clauses: not every required category is covered")

    sources = manifest.get("sources")
    if isinstance(sources, list) and len(sources) == 1 and isinstance(sources[0], Mapping):
        manifest_sha = sources[0].get("destination_sha256")
        authority_sha = authority.get("sha256") if authority is not None else None
        if authority_sha != manifest_sha:
            errors.append("contract/manifest: patent SHA-256 values disagree")
    return errors


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normal_text(value: str) -> str:
    return "".join(value.split()).casefold()


def validate_patent(
    patent_path: Path, contract: Mapping[str, Any]
) -> list[str]:
    errors: list[str] = []
    if not patent_path.is_file():
        return [f"patent: missing {patent_path}"]
    actual_sha = sha256_file(patent_path)
    if actual_sha != PATENT_SHA256:
        errors.append(f"patent: SHA-256 mismatch, got {actual_sha}")
        return errors

    required_parts = {
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
        "word/_rels/document.xml.rels",
        "word/styles.xml",
        "word/settings.xml",
    }
    roots: dict[str, ElementTree.Element] = {}
    raw_xml: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(patent_path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                errors.append(f"patent: corrupt ZIP member {bad_member}")
            names = set(archive.namelist())
            missing = sorted(required_parts - names)
            if missing:
                errors.append(f"patent: missing OOXML parts {missing}")
            for name in sorted(names):
                if name.endswith((".xml", ".rels")):
                    payload = archive.read(name)
                    raw_xml[name] = payload
                    try:
                        roots[name] = ElementTree.fromstring(payload)
                    except ElementTree.ParseError as exc:
                        errors.append(f"patent: XML parse failure in {name}: {exc}")
    except zipfile.BadZipFile as exc:
        return [f"patent: invalid DOCX ZIP: {exc}"]

    document = roots.get("word/document.xml")
    if document is None:
        return errors
    text = "".join(
        element.text or "" for element in document.iter() if _local_name(element.tag) == "t"
    )
    normalized_text = _normal_text(text)

    clauses = contract.get("clauses")
    if isinstance(clauses, list):
        for index, clause in enumerate(clauses):
            if not isinstance(clause, Mapping):
                continue
            locator = clause.get("authority_locator")
            if not isinstance(locator, Mapping):
                continue
            anchor = locator.get("anchor")
            if isinstance(anchor, str) and _normal_text(anchor) not in normalized_text:
                errors.append(
                    f"contract.clauses[{index}].authority_locator.anchor: not found in patent"
                )

    counts = {
        "paragraph_count": sum(_local_name(element.tag) == "p" for element in document.iter()),
        "table_count": sum(_local_name(element.tag) == "tbl" for element in document.iter()),
        "drawing_count": sum(
            _local_name(element.tag) == "drawing" for element in document.iter()
        ),
        "native_subscript_count": 0,
        "native_superscript_count": 0,
        "tracked_insertions": 0,
        "tracked_deletions": 0,
    }
    for root in roots.values():
        for element in root.iter():
            local = _local_name(element.tag)
            if local == "vertAlign":
                value = next(
                    (item for key, item in element.attrib.items() if _local_name(key) == "val"),
                    None,
                )
                if value == "subscript":
                    counts["native_subscript_count"] += 1
                elif value == "superscript":
                    counts["native_superscript_count"] += 1
            elif local == "ins":
                counts["tracked_insertions"] += 1
            elif local == "del":
                counts["tracked_deletions"] += 1
            elif local == "trackRevisions":
                errors.append("patent: trackRevisions must be disabled")

    authority = contract.get("authority")
    ooxml_contract = authority.get("ooxml_contract") if isinstance(authority, Mapping) else None
    if isinstance(ooxml_contract, Mapping):
        for key, actual in counts.items():
            if ooxml_contract.get(key) != actual:
                errors.append(f"patent: {key} expected {ooxml_contract.get(key)!r}, got {actual}")
        if ooxml_contract.get("compatibility_glyphs") != []:
            errors.append("contract.authority.ooxml_contract.compatibility_glyphs: must be empty")
    all_xml_text = b"".join(raw_xml.values()).decode("utf-8", errors="ignore")
    glyph_hits = sorted({glyph for glyph in COMPATIBILITY_GLYPHS if glyph in all_xml_text})
    if glyph_hits:
        errors.append(f"patent: compatibility superscript/subscript glyphs remain: {glyph_hits}")
    return errors


def validate_checksums(sums_path: Path, repo_root: Path) -> list[str]:
    errors: list[str] = []
    if not sums_path.is_file():
        return [f"checksums: missing {sums_path}"]
    entries: dict[str, str] = {}
    for line_number, line in enumerate(sums_path.read_text(encoding="utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if match is None:
            errors.append(f"checksums:{line_number}: invalid sha256sum format")
            continue
        digest, relative_path = match.groups()
        if relative_path in entries:
            errors.append(f"checksums:{line_number}: duplicate path {relative_path}")
        entries[relative_path] = digest
    if set(entries) != EXPECTED_CHECKSUM_PATHS:
        missing = sorted(EXPECTED_CHECKSUM_PATHS - set(entries))
        unknown = sorted(set(entries) - EXPECTED_CHECKSUM_PATHS)
        errors.append(f"checksums: exact path set required; missing={missing}, unknown={unknown}")
    resolved_root = repo_root.resolve()
    for relative_path, expected_sha in entries.items():
        if not HEX_64.fullmatch(expected_sha):
            errors.append(f"checksums: invalid digest for {relative_path}")
            continue
        target = (repo_root / relative_path).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError:
            errors.append(f"checksums: path escapes repository: {relative_path}")
            continue
        if not target.is_file():
            errors.append(f"checksums: missing file {relative_path}")
            continue
        actual_sha = sha256_file(target)
        if actual_sha != expected_sha:
            errors.append(
                f"checksums: SHA-256 mismatch for {relative_path}; "
                f"expected {expected_sha}, got {actual_sha}"
            )
    return errors


def audit_bundle(docs_root: Path, repo_root: Path) -> list[str]:
    """Return all audit errors; an empty list means the bundle passes."""

    contract_path = docs_root / "design/patent-contract.yaml"
    manifest_path = docs_root / "provenance/SOURCE_MANIFEST.json"
    sums_path = docs_root / "provenance/SHA256SUMS"
    try:
        contract = load_contract(contract_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [f"contract: cannot load fail-closed: {exc}"]
    try:
        manifest = load_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"manifest: cannot load fail-closed: {exc}"]

    errors = validate_manifest(manifest)
    errors.extend(validate_contract(contract, manifest))
    errors.extend(validate_patent(repo_root / PATENT_PATH, contract))
    errors.extend(validate_checksums(sums_path, repo_root))
    return errors


def main(argv: list[str] | None = None) -> int:
    default_docs_root = Path(__file__).resolve().parent
    default_repo_root = default_docs_root.parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-root", type=Path, default=default_docs_root)
    parser.add_argument("--repo-root", type=Path, default=default_repo_root)
    parser.add_argument("--json", action="store_true", help="emit a machine-readable result")
    args = parser.parse_args(argv)

    errors = audit_bundle(args.docs_root.resolve(), args.repo_root.resolve())
    result = {
        "schema": "moonkvsim.aegiskv.patent-contract-audit.v1",
        "status": "PASS" if not errors else "FAIL",
        "error_count": len(errors),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif errors:
        print("AegisKV patent contract audit: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print("AegisKV patent contract audit: PASS")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
