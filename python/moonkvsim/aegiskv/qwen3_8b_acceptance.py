"""Generic, fail-closed acceptance manifests for Qwen3-8B paper artifacts.

The verifier is intentionally independent of the plotting layer.  It accepts a
small registry of attempted cells, materializes all eight ordered contract
gates, and embeds every value needed by a later figure/Canvas consumer.
Failure attempts bind a separately generated schema-v2 direct-recovery
classification artifact.  That classifier is evidence, not an effect-direction
filter: concordant, mixed, null, and adverse valid cells are all retained.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Final

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from moonkvsim.aegiskv.formal_algorithm_audit import (
    FormalAlgorithmAuditError,
    audit_continuous_scheduler_evidence,
    audit_formal_algorithm_run,
)

MANIFEST_SCHEMA: Final = "moonkvsim.aegiskv.qwen3-8b-acceptance-manifest.v1"
REGISTRY_SCHEMA: Final = "moonkvsim.aegiskv.qwen3-8b-acceptance-registry.v1"
VERIFIER_NAME: Final = "moonkvsim.aegiskv.qwen3_8b_acceptance"
VERIFIER_VERSION: Final = "2"
LOG = logging.getLogger(__name__)


def _capture_verifier_files() -> dict[str, str]:
    """Bind the verifier and its imported package before a long audit starts."""
    package = Path(__file__).resolve().parents[1]
    root = package.parents[1]
    paths = [*package.rglob("*.py"),
             root / "benchmark/AegisKV/experiments/schemas/aegiskv-qwen3-8b-acceptance-manifest.schema.json",
             root / "benchmark/AegisKV/Archived/simulation-qwen3-8b/scripts/build_qwen3_8b_acceptance_manifest.py"]
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


_VERIFIER_FILES: Final = _capture_verifier_files()
EXPECTED_AGGREGATE_SCHEMA: Final = "moonkvsim.aegiskv.no-failure-overhead.v1"
EXPECTED_FAILURE_CAMPAIGN_SCHEMA: Final = (
    "moonkvsim.aegiskv.qwen3_8b.failure_campaign.v1"
)
EXPECTED_PAPER_SWEEP_SCHEMA: Final = "moonkvsim.aegiskv.paper_sweeps.v4"
EXPECTED_PAPER_SWEEP_STATISTICS_SCHEMA: Final = (
    "moonkvsim.aegiskv.paper_sweep_statistics.v3"
)
EXPECTED_RAW_SCHEMA: Final = "moonkvsim.aegiskv.no-failure-overhead.raw-run.v1"
EXPECTED_WORKLOAD_SCHEMA: Final = "moonkvsim.aegiskv.experiment_workload_manifest.v1"
EXPECTED_DIRECT_CLASSIFIER_SCHEMA: Final = (
    "moonkvsim.aegiskv.qwen3_8b.direct_recovery_classification.v2"
)
EXPECTED_WORKFLOW_COUNT: Final = 160
EXPECTED_SPAN_COUNT: Final = 1304
EXPECTED_SEEDS: Final = (0, 1, 2, 3, 4)
SYSTEM_IDS: Final = ("vanilla_mooncake_dram", "aegiskv_unified")
PROTECTION_CAUSES: Final = {
    "AEGIS_PEER_HBM_PROTECTION": "peer_hbm",
    "AEGIS_STORE_DRAM_PROTECTION": "store_dram",
}
DISPOSITIONS: Final = {"COMPLETED", "FAILED", "INFEASIBLE", "ABORTED", "MISSING"}
TERMINAL_CLASSES: Final = {
    "VALID",
    "FAILED",
    "INFEASIBLE",
    "STALE",
    "HISTORICAL",
    "NULL_DIRECT",
    "MIXED_DIRECT",
    "ADVERSE_DIRECT",
}
AUTHORIZED_FIGURE_2_PANELS: Final = (
    "FIGURE_2_A",
    "FIGURE_2_B",
    "FIGURE_2_C",
    "FIGURE_2_D",
)
AUTHORIZED_FAILURE_DIRECT_PANELS: Final = (
    "FIGURE_4_B",
    "FIGURE_4_C",
    "FIGURE_4_D",
)
AUTHORIZED_FAILURE_AGGREGATE_PANELS: Final = (
    "FIGURE_3_A",
    "FIGURE_3_B",
    "FIGURE_3_C",
    "FIGURE_3_D",
)
AUTHORIZED_FAILURE_CAMPAIGN_PANELS: Final = (
    "FIGURE_3_A",
    "FIGURE_3_B",
    "FIGURE_3_C",
    "FIGURE_3_D",
    "FIGURE_4_B",
    "FIGURE_4_C",
    "FIGURE_4_D",
)
AUTHORIZED_FIGURE_5_PANELS: Final = (
    "FIGURE_5_A",
    "FIGURE_5_B",
    "FIGURE_5_C",
    "FIGURE_5_D",
    "FIGURE_5_E",
    "FIGURE_5_F",
)
DIRECT_CLASSES: Final = {
    "DIRECT_RECOVERY_BENEFIT_CONCORDANT",
    "DIRECT_RECOVERY_MIXED",
    "SOURCE_SUBSTITUTION_OR_NULL_DIRECT_MECHANISM",
    "ADVERSE_DIRECT_MECHANISM",
}
CAUSAL_CLASSIFIER_CHECKS: Final = {
    "PAPER_CAUSAL_MODE",
    "EXACTLY_ONE_FOCUS_SPAN",
    "MATCHED_SINGLE_FAILURE_SCHEDULE",
    "FROZEN_PHYSICAL_TARGET",
    "NO_FROZEN_POST_TREATMENT_IMPACT_CONTRACT",
    "PROFILE_IMPACT_CONTRACTS_ABSENT_OR_NULL",
    "MATCHED_INTERVENTION_AND_REALIZED_OUTCOMES",
}
_HEX = frozenset("0123456789abcdef")


class AcceptanceError(ValueError):
    """Raised for malformed registries or non-canonical acceptance documents."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AcceptanceError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise AcceptanceError(f"non-finite JSON number {value!r}")


def load_json_strict(path: Path) -> Any:
    """Load UTF-8 JSON while rejecting duplicate keys and non-finite numbers."""

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except AcceptanceError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"cannot load JSON {path}: {error}") from error


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AcceptanceError(f"value is not canonical finite JSON: {error}") from error


def fingerprint(value: Any) -> str:
    """SHA-256 of canonical JSON without the output-only trailing newline."""

    return hashlib.sha256(canonical_json_bytes(value)[:-1]).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    """Atomically replace *path* with one canonical JSON serialization."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _sha256(value: object, where: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise AcceptanceError(f"{where} must be lowercase SHA-256")
    return value


def repository_path(root: Path, value: object, where: str, *, must_exist: bool = True) -> Path:
    """Resolve a strict repository-relative path with no symlink component."""

    if not isinstance(value, str) or not value:
        raise AcceptanceError(f"{where} must be a non-empty repository-relative path")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or value != pure.as_posix()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise AcceptanceError(f"{where} must be a normalized repository-relative path")
    root = root.resolve()
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise AcceptanceError(f"{where} contains symlink component {part!r}")
    try:
        current.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise AcceptanceError(f"{where} escapes repository root") from error
    if must_exist and not current.is_file():
        raise AcceptanceError(f"{where} is not a regular file")
    return current


def source_root_for_attempt(root: Path, entry: Mapping[str, Any]) -> Path:
    """Resolve an explicit preserved execution tree separately from result paths."""
    if "source_root" not in entry:
        return root.resolve()
    source_root = repository_path(root, entry["source_root"], "attempt.source_root",
                                  must_exist=False)
    if not source_root.is_dir():
        raise AcceptanceError("attempt.source_root is not a directory")
    return source_root


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AcceptanceError(f"{where} must be an object")
    return value


def _sequence(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise AcceptanceError(f"{where} must be an array")
    return value


def _integer(value: object, where: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = "" if minimum is None else f" >= {minimum}"
        raise AcceptanceError(f"{where} must be an integer{suffix}")
    return value


def _verify_self_fingerprint(document: Mapping[str, Any], where: str) -> str:
    claimed = _sha256(document.get("fingerprint"), f"{where}.fingerprint")
    body = {key: value for key, value in document.items() if key != "fingerprint"}
    if fingerprint(body) != claimed:
        raise AcceptanceError(f"{where} self-fingerprint mismatch")
    return claimed


def _gate(
    number: int,
    status: str,
    codes: Sequence[str],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    LOG.info("acceptance gate %d %s", number, status)
    verifier_body = {
        "name": VERIFIER_NAME,
        "version": VERIFIER_VERSION,
        "source_sha256": _VERIFIER_FILES["python/moonkvsim/aegiskv/qwen3_8b_acceptance.py"],
        "source_files": _VERIFIER_FILES,
    }
    return {
        "gate": number,
        "status": status,
        "verifier": {**verifier_body, "fingerprint": fingerprint(verifier_body)},
        "reason_codes": list(codes),
        "evidence": dict(evidence),
    }


def _blocked_gate(number: int, first_failed_gate: int) -> dict[str, Any]:
    return _gate(
        number,
        "NOT_APPLICABLE",
        ["BLOCKED_BY_EARLIER_GATE"],
        {"blocked_by_gate": first_failed_gate},
    )


def _load_workload(root: Path, binding: Mapping[str, Any]) -> dict[str, Any]:
    declared = repository_path(root, binding.get("declared_path"), "workload.declared_path")
    manifest_path_value = binding.get("manifest_path")
    if manifest_path_value is None:
        manifest_path_value = (
            "benchmark/AegisKV/experiments/workloads/"
            "fanoutqa-dev-qwen3-8b-160-manifest.json"
        )
    manifest_path = repository_path(root, manifest_path_value, "workload.manifest_path")
    if sha256_file(declared) != _sha256(binding.get("sha256"), "workload.sha256"):
        raise AcceptanceError("workload artifact SHA-256 mismatch")
    manifest = _mapping(load_json_strict(manifest_path), "workload manifest")
    if manifest.get("schema") != EXPECTED_WORKLOAD_SCHEMA or manifest.get("status") != "pass":
        raise AcceptanceError("workload manifest schema/status mismatch")
    manifest_fingerprint = _verify_self_fingerprint(manifest, "workload manifest")
    if binding.get("manifest_sha256") != sha256_file(manifest_path):
        raise AcceptanceError("workload manifest file SHA-256 mismatch")
    expected_manifest_fingerprint = binding.get("manifest_fingerprint")
    if (
        expected_manifest_fingerprint is not None
        and expected_manifest_fingerprint != manifest_fingerprint
    ):
        raise AcceptanceError("workload manifest fingerprint binding mismatch")
    artifact = _mapping(manifest.get("artifact"), "workload manifest.artifact")
    if artifact.get("sha256") != binding.get("sha256"):
        raise AcceptanceError("workload artifact binding differs from manifest")

    workflows: set[str] = set()
    spans: set[str] = set()
    token_hashes: list[str] = []
    count = 0
    try:
        with declared.open("r", encoding="utf-8", newline="") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise AcceptanceError(f"workload line {line_number} is blank")
                record = json.loads(
                    line,
                    object_pairs_hook=_reject_duplicate_pairs,
                    parse_constant=_reject_nonfinite,
                )
                record = _mapping(record, f"workload line {line_number}")
                workflow_id = record.get("workflow_id")
                span_id = record.get("span_id")
                if not isinstance(workflow_id, str) or not isinstance(span_id, str):
                    raise AcceptanceError("workload record lacks workflow/span identity")
                if span_id in spans:
                    raise AcceptanceError("workload contains duplicate span IDs")
                content = _mapping(
                    record.get("messages_or_token_ids"),
                    f"workload line {line_number}.messages_or_token_ids",
                )
                token_ids = content.get("value")
                if content.get("kind") != "token_ids" or not isinstance(token_ids, list):
                    raise AcceptanceError("workload lacks exact token IDs")
                if any(type(token) is not int for token in token_ids):
                    raise AcceptanceError("workload token IDs must be integers")
                prompt_tokens = _integer(
                    record.get("prompt_tokens"), "prompt_tokens", minimum=1
                )
                if len(token_ids) != prompt_tokens:
                    raise AcceptanceError("workload prompt token count differs from exact IDs")
                token_hash = fingerprint(token_ids)
                if token_hash != content.get("sha256") or token_hash != record.get(
                    "prompt_token_ids_hash"
                ):
                    raise AcceptanceError("workload exact token-ID hash mismatch")
                if record.get("truncated") is not False:
                    raise AcceptanceError("workload contains a truncated record")
                workflows.add(workflow_id)
                spans.add(span_id)
                token_hashes.append(token_hash)
                count += 1
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceError(f"cannot load canonical workload: {error}") from error
    if len(workflows) != EXPECTED_WORKFLOW_COUNT or count != EXPECTED_SPAN_COUNT:
        raise AcceptanceError("workload is not exactly 160 workflows/1304 spans")
    selected = _sequence(
        _mapping(manifest.get("selection"), "workload manifest.selection").get(
            "selected_workflow_ids"
        ),
        "workload manifest.selected_workflow_ids",
    )
    if set(selected) != workflows or len(selected) != EXPECTED_WORKFLOW_COUNT:
        raise AcceptanceError("workload IDs differ from frozen manifest selection")
    return {
        "workflow_count": len(workflows),
        "span_count": count,
        "workflow_ids_sha256": fingerprint(sorted(workflows)),
        "span_ids_sha256": fingerprint(sorted(spans)),
        "exact_token_ids_sha256": fingerprint(token_hashes),
        "manifest_fingerprint": manifest_fingerprint,
        "workflow_filtering": False,
    }


def _verify_source_and_config(root: Path, provenance: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(provenance.get("source_contract"), "provenance.source_contract")
    files = _mapping(source.get("files"), "source_contract.files")
    actual: dict[str, str] = {}
    for relative, claimed in sorted(files.items()):
        path = repository_path(root, relative, f"source_contract.files[{relative!r}]")
        actual[str(relative)] = sha256_file(path)
        if actual[str(relative)] != _sha256(claimed, f"source hash {relative}"):
            raise AcceptanceError(f"source-contract file hash mismatch: {relative}")
    source_body = {
        "binding_kind": source.get("binding_kind"),
        "files": dict(files),
    }
    if fingerprint(source_body) != source.get("fingerprint"):
        raise AcceptanceError("source-contract fingerprint mismatch")

    config = _mapping(provenance.get("config_binding"), "provenance.config_binding")
    config_files = _mapping(config.get("files"), "config_binding.files")
    config_dir_value = provenance.get(
        "config_directory", "benchmark/AegisKV/experiments/configs"
    )
    for name, claimed in sorted(config_files.items()):
        relative = f"{config_dir_value}/{name}"
        path = repository_path(root, relative, f"config_binding.files[{name!r}]")
        if sha256_file(path) != _sha256(claimed, f"config hash {name}"):
            raise AcceptanceError(f"config-binding file hash mismatch: {name}")
    if fingerprint(dict(config_files)) != config.get("fingerprint"):
        raise AcceptanceError("config-binding fingerprint mismatch")
    return {
        "source_contract_fingerprint": source.get("fingerprint"),
        "source_file_count": len(files),
        "config_binding_fingerprint": config.get("fingerprint"),
        "config_file_count": len(config_files),
    }


def _verify_raw(
    aggregate_path: Path,
    system: Mapping[str, Any],
    *,
    run_public_audits: bool,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    raw_description = _mapping(system.get("raw_artifact"), "system.raw_artifact")
    raw_relative = raw_description.get("path")
    if not isinstance(raw_relative, str):
        raise AcceptanceError("raw artifact path must be a string")
    raw_path = repository_path(
        aggregate_path.parent,
        raw_relative,
        "system.raw_artifact.path",
    )
    if sha256_file(raw_path) != _sha256(raw_description.get("sha256"), "raw artifact sha256"):
        raise AcceptanceError("referenced raw artifact SHA-256 mismatch")
    raw = _mapping(load_json_strict(raw_path), "raw artifact")
    if raw.get("schema") != EXPECTED_RAW_SCHEMA or raw.get("status") != "PASS":
        raise AcceptanceError("raw artifact schema/status mismatch")
    components = _mapping(raw.get("component_sha256"), "raw.component_sha256")
    embedded = {
        "payload": raw.get("payload"),
        "span_details": raw.get("span_details"),
        "representative": raw.get("representative"),
        "continuous_scheduler_audit": raw.get("continuous_scheduler_audit"),
        "formal_algorithm_audit": raw.get("formal_algorithm_audit"),
    }
    for name, content in embedded.items():
        claimed = components.get(name)
        if content is None:
            if claimed is not None:
                raise AcceptanceError(f"raw component {name} hash exists without content")
            continue
        if fingerprint(content) != claimed:
            raise AcceptanceError(f"raw component hash mismatch: {name}")
    compact_pairs = {
        "payload_sha256": "payload",
        "span_details_sha256": "span_details",
        "representative_sha256": "representative",
    }
    for compact_name, component_name in compact_pairs.items():
        if system.get(compact_name) != components.get(component_name):
            raise AcceptanceError(f"compact/raw component hash mismatch: {component_name}")
    reports: dict[str, Any] = {}
    if run_public_audits:
        payload = _mapping(raw.get("payload"), "raw.payload")
        representative = _mapping(raw.get("representative"), "raw.representative")
        try:
            reports["continuous_scheduler"] = audit_continuous_scheduler_evidence(
                payload, representative
            ).to_dict()
            if system.get("variant_id") == "aegiskv_unified":
                reports["formal_algorithms"] = audit_formal_algorithm_run(
                    payload, representative
                ).to_dict()
        except FormalAlgorithmAuditError as error:
            raise AcceptanceError(str(error)) from error
    return reports, raw


def _counter(
    rows: Sequence[Mapping[str, Any]],
    field: str,
    where: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for index, row in enumerate(rows):
        value = row.get(field)
        if not isinstance(value, str) or not value:
            raise AcceptanceError(f"{where}[{index}].{field} must be a non-empty string")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _reconstruct_no_failure_attribution(
    system: Mapping[str, Any],
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    """Reconstruct diagnostic overhead attribution from hash-bound raw evidence."""

    variant_id = system.get("variant_id")
    if variant_id not in SYSTEM_IDS:
        raise AcceptanceError("attribution system has an unsupported variant_id")
    payload = _mapping(raw.get("payload"), "raw.payload")
    representative = _mapping(raw.get("representative"), "raw.representative")
    policy = _mapping(
        _mapping(payload.get("metrics"), "raw.payload.metrics").get("policy_effects"),
        "raw.payload.metrics.policy_effects",
    )
    warmup = _mapping(system.get("warmup"), "system.warmup")
    warmup_end_ns = _integer(warmup.get("warmup_end_ns"), "system.warmup.warmup_end_ns", minimum=0)

    transfers = [
        _mapping(value, f"representative.transfers[{index}]")
        for index, value in enumerate(
            _sequence(representative.get("transfers"), "representative.transfers")
        )
        if _mapping(value, f"representative.transfers[{index}]").get("cause")
        in PROTECTION_CAUSES
    ]
    tier_phase: dict[str, dict[str, dict[str, int]]] = {
        tier: {
            phase: {
                "transfer_count": 0,
                "committed_count": 0,
                "aborted_count": 0,
                "submitted_bytes": 0,
                "transferred_bytes": 0,
                "aborted_bytes": 0,
            }
            for phase in ("bootstrap_warmup", "steady_state")
        }
        for tier in PROTECTION_CAUSES.values()
    }
    terminal_counts = {"COMMITTED": 0, "ABORTED": 0}
    for index, transfer in enumerate(transfers):
        where = f"representative.transfers[{index}]"
        cause = str(transfer.get("cause"))
        status = transfer.get("status")
        if status not in terminal_counts:
            raise AcceptanceError(f"{where}.status is not a terminal protection state")
        submitted = _integer(transfer.get("bytes"), f"{where}.bytes", minimum=0)
        transferred = _integer(
            transfer.get("transferred_bytes"), f"{where}.transferred_bytes", minimum=0
        )
        aborted = _integer(
            transfer.get("aborted_bytes"), f"{where}.aborted_bytes", minimum=0
        )
        if submitted != transferred + aborted:
            raise AcceptanceError("protection transfer byte identity mismatch")
        if (status == "COMMITTED" and aborted != 0) or (
            status == "ABORTED" and transferred == submitted
        ):
            raise AcceptanceError("protection transfer terminal-state/byte identity mismatch")
        ready_ns = _integer(transfer.get("ready_ns"), f"{where}.ready_ns", minimum=0)
        phase = "bootstrap_warmup" if ready_ns < warmup_end_ns else "steady_state"
        bucket = tier_phase[PROTECTION_CAUSES[cause]][phase]
        bucket["transfer_count"] += 1
        bucket[f"{str(status).lower()}_count"] += 1
        bucket["submitted_bytes"] += submitted
        bucket["transferred_bytes"] += transferred
        bucket["aborted_bytes"] += aborted
        terminal_counts[str(status)] += 1

    protection = _mapping(system.get("protection"), "system.protection")
    totals = {
        name: sum(
            tier_phase[tier][phase][name]
            for tier in tier_phase
            for phase in tier_phase[tier]
        )
        for name in (
            "transfer_count",
            "submitted_bytes",
            "transferred_bytes",
            "aborted_bytes",
        )
    }
    for name, observed in totals.items():
        if protection.get(name) != observed:
            raise AcceptanceError(f"protection compact aggregate mismatch: {name}")
    compact_terminal = _mapping(
        protection.get("terminal_state_counts"), "system.protection.terminal_state_counts"
    )
    if any(compact_terminal.get(name, 0) != count for name, count in terminal_counts.items()):
        raise AcceptanceError("protection compact terminal-state mismatch")
    compact_phases = _mapping(
        protection.get("by_time_phase"), "system.protection.by_time_phase"
    )
    for phase in ("bootstrap_warmup", "steady_state"):
        compact_phase = _mapping(compact_phases.get(phase), f"protection.by_time_phase.{phase}")
        for name in ("transfer_count", "submitted_bytes"):
            reconstructed = sum(tier_phase[tier][phase][name] for tier in tier_phase)
            if compact_phase.get(name) != reconstructed:
                raise AcceptanceError(f"protection compact phase mismatch: {phase}.{name}")

    algorithm2_events = [
        _mapping(value, f"representative.formal_algorithm2_events[{index}]")
        for index, value in enumerate(
            _sequence(
                representative.get("formal_algorithm2_events"),
                "representative.formal_algorithm2_events",
            )
        )
    ]
    aimd_events = [
        _mapping(value, f"representative.aimd_events[{index}]")
        for index, value in enumerate(
            _sequence(representative.get("aimd_events"), "representative.aimd_events")
        )
    ]
    pressure = [
        _mapping(value, f"representative.hbm_pressure_observations[{index}]")
        for index, value in enumerate(
            _sequence(
                representative.get("hbm_pressure_observations"),
                "representative.hbm_pressure_observations",
            )
        )
    ]
    algorithm2_kinds = _counter(algorithm2_events, "event", "algorithm2_events")
    aimd_actions = _counter(aimd_events, "action", "aimd_events")
    pressure_reasons = _counter(pressure, "reason", "hbm_pressure_observations")
    compact_algorithm2 = _mapping(system.get("algorithm2"), "system.algorithm2")
    compact_algorithm3 = _mapping(system.get("algorithm3"), "system.algorithm3")
    if (
        compact_algorithm2.get("event_count") != len(algorithm2_events)
        or compact_algorithm2.get("preview_count")
        != algorithm2_kinds.get("FORMAL_ALGORITHM2_PREVIEW", 0)
        or compact_algorithm2.get("event_counts_by_kind") != algorithm2_kinds
        or policy.get("formal_algorithm2_event_count") != len(algorithm2_events)
    ):
        raise AcceptanceError("Algorithm 2 compact/policy summary mismatch")
    if (
        compact_algorithm3.get("event_count") != len(aimd_events)
        or compact_algorithm3.get("action_counts") != aimd_actions
        or policy.get("aimd_decision_count") != len(aimd_events)
        or policy.get("aimd_action_counts") != aimd_actions
        or policy.get("hbm_pressure_observation_count") != len(pressure)
    ):
        raise AcceptanceError("Algorithm 3 compact/policy summary mismatch")
    if variant_id == "vanilla_mooncake_dram" and (
        algorithm2_events or aimd_events or pressure
    ):
        raise AcceptanceError("Mooncake emitted formal Algorithm 2/3 evidence")

    route_events = [
        _mapping(value, f"representative.route_events[{index}]")
        for index, value in enumerate(
            _sequence(representative.get("route_events"), "representative.route_events")
        )
    ]
    evaluated = [event for event in route_events if event.get("cache_aware") is True]
    route_changes = sum(
        event.get("selected_gpu_id") != event.get("hashed_gpu_id") for event in evaluated
    )
    if (
        policy.get("cache_aware_route_evaluations") != len(evaluated)
        or policy.get("cache_aware_route_changes") != route_changes
    ):
        raise AcceptanceError("route evaluation/change policy counter mismatch")
    selected_preferred_divergence = sum(
        event.get("preferred_gpu_id") is not None
        and event.get("selected_gpu_id") != event.get("preferred_gpu_id")
        for event in route_events
    )

    preemption_events = [
        _mapping(value, f"representative.scheduler_preemption_events[{index}]")
        for index, value in enumerate(
            _sequence(
                representative.get("scheduler_preemption_events"),
                "representative.scheduler_preemption_events",
            )
        )
    ]
    reasons: dict[str, int] = {}
    phases: dict[str, int] = {}
    prompt_tokens = 0
    output_tokens = 0
    victim_count = 0
    for event_index, event in enumerate(preemption_events):
        ids = list(
            _sequence(
                event.get("preempted_request_ids"),
                f"scheduler_preemption_events[{event_index}].preempted_request_ids",
            )
        )
        details = [
            _mapping(value, "scheduler preemption detail")
            for value in _sequence(
                event.get("preemption_details"),
                f"scheduler_preemption_events[{event_index}].preemption_details",
            )
        ]
        detail_ids = [detail.get("victim_request_id") for detail in details]
        if len(ids) != len(set(ids)) or ids != detail_ids:
            raise AcceptanceError("scheduler preemption victim identity mismatch")
        victim_count += len(details)
        for detail in details:
            total = _integer(
                detail.get("victim_num_computed_tokens_before_preemption"),
                "preemption.victim_num_computed_tokens_before_preemption",
                minimum=0,
            )
            prompt_limit = _integer(
                detail.get("victim_prompt_tokens"),
                "preemption.victim_prompt_tokens",
                minimum=0,
            )
            output = _integer(
                detail.get("victim_output_tokens_before_preemption"),
                "preemption.victim_output_tokens_before_preemption",
                minimum=0,
            )
            computed_prompt = min(total, prompt_limit)
            if total != computed_prompt + output:
                raise AcceptanceError("scheduler preemption computed-token identity mismatch")
            expected_phase = "PREFILL" if total < prompt_limit else "DECODE"
            observed_phase = detail.get("victim_phase_before_preemption")
            if observed_phase != expected_phase:
                raise AcceptanceError("scheduler preemption phase identity mismatch")
            reason = detail.get("reason")
            if not isinstance(reason, str) or not reason:
                raise AcceptanceError("scheduler preemption reason is missing")
            reasons[reason] = reasons.get(reason, 0) + 1
            phases[expected_phase] = phases.get(expected_phase, 0) + 1
            prompt_tokens += computed_prompt
            output_tokens += output

    result = {
        "declaration": {
            "attribution_kind": "DIAGNOSTIC_NON_ADDITIVE",
            "wct_sum_explanation_claimed": False,
            "modeled_uncalibrated": True,
            "physical_execution": False,
        },
        "protection": {
            "totals": totals,
            "terminal_state_counts": terminal_counts,
            "by_tier_and_time_phase": tier_phase,
        },
        "algorithm2": {
            "event_count": len(algorithm2_events),
            "event_counts_by_kind": algorithm2_kinds,
        },
        "algorithm3": {
            "decision_count": len(aimd_events),
            "action_counts": aimd_actions,
            "pressure_observation_count": len(pressure),
            "pressure_reasons": pressure_reasons,
        },
        "routing": {
            "route_event_count": len(route_events),
            "cache_aware_evaluation_count": len(evaluated),
            "selected_vs_hashed_change_count": route_changes,
            "selected_vs_preferred_divergence_count": selected_preferred_divergence,
        },
        "scheduler_preemptions": {
            "event_count": len(preemption_events),
            "victim_count": victim_count,
            "reason_counts": dict(sorted(reasons.items())),
            "phase_counts": dict(sorted(phases.items())),
            "victim_computed_prompt_tokens": prompt_tokens,
            "victim_computed_output_tokens": output_tokens,
            "victim_computed_tokens_total": prompt_tokens + output_tokens,
        },
    }
    return {**result, "evidence_fingerprint": fingerprint(result)}


def _nearest_rank_identity(values: Mapping[str, int], percentile: int) -> dict[str, Any]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    rank = max(1, (len(ordered) * percentile + 99) // 100)
    workflow_id, value = ordered[rank - 1]
    return {
        "rule": "nearest_rank",
        "percentile": percentile,
        "population_size": len(ordered),
        "rank": rank,
        "workflow_id": workflow_id,
        "value_ns": value,
    }


def _recompute_no_failure_statistics(aggregate: Mapping[str, Any]) -> dict[str, Any]:
    cells = _sequence(aggregate.get("cells"), "aggregate.cells")
    if len(cells) != len(EXPECTED_SEEDS):
        raise AcceptanceError("no-failure aggregate must contain five seed cells")
    per_seed: list[dict[str, Any]] = []
    admission_hashes: set[str] = set()
    realized_hashes: set[tuple[str, str]] = set()
    for expected_seed, cell_value in zip(EXPECTED_SEEDS, cells, strict=True):
        cell = _mapping(cell_value, "aggregate.cells[]")
        seed = _integer(cell.get("seed"), "cell.seed")
        if seed != expected_seed:
            raise AcceptanceError("seed cells must be ordered exactly 0..4")
        systems = _mapping(cell.get("systems"), "cell.systems")
        if set(systems) != set(SYSTEM_IDS):
            raise AcceptanceError("cell lacks the exact paired systems")
        moon = _mapping(systems[SYSTEM_IDS[0]], "cell.systems.mooncake")
        aegis = _mapping(systems[SYSTEM_IDS[1]], "cell.systems.aegiskv")
        moon_wct = {
            str(key): _integer(value, f"moon WCT {key}", minimum=1)
            for key, value in _mapping(moon.get("workflow_wct_ns"), "moon WCT").items()
        }
        aegis_wct = {
            str(key): _integer(value, f"aegis WCT {key}", minimum=1)
            for key, value in _mapping(aegis.get("workflow_wct_ns"), "aegis WCT").items()
        }
        if set(moon_wct) != set(aegis_wct) or len(moon_wct) != EXPECTED_WORKFLOW_COUNT:
            raise AcceptanceError("paired WCT maps must share exactly 160 workflow IDs")
        moon_order = tuple(_sequence(moon.get("workflow_admission_order"), "moon order"))
        aegis_order = tuple(_sequence(aegis.get("workflow_admission_order"), "aegis order"))
        order_hash = fingerprint(moon_order)
        if (
            moon_order != aegis_order
            or len(set(moon_order)) != EXPECTED_WORKFLOW_COUNT
            or set(moon_order) != set(moon_wct)
            or moon.get("workflow_admission_order_sha256") != order_hash
            or aegis.get("workflow_admission_order_sha256") != order_hash
        ):
            raise AcceptanceError("paired admission-order evidence is inconsistent")
        admission_hashes.add(order_hash)
        for system in (moon, aegis):
            realized_hashes.add(
                (
                    str(system.get("journal_sha256")),
                    str(system.get("span_details_sha256")),
                )
            )
        deltas = {key: aegis_wct[key] - moon_wct[key] for key in sorted(moon_wct)}
        winners = sum(value < 0 for value in deltas.values())
        ties = sum(value == 0 for value in deltas.values())
        losers = sum(value > 0 for value in deltas.values())
        per_seed.append(
            {
                "seed": seed,
                "workflow_pair_count": len(deltas),
                "workflow_deltas_ns": deltas,
                "mean_delta_ns": sum(deltas.values()) / len(deltas),
                "mooncake_p95": _nearest_rank_identity(moon_wct, 95),
                "aegiskv_p95": _nearest_rank_identity(aegis_wct, 95),
                "winner_tie_loser": {
                    "aegiskv_winner_count": winners,
                    "tie_count": ties,
                    "aegiskv_loser_count": losers,
                },
                "admission_order_sha256": order_hash,
            }
        )
    distinct_orders = len(admission_hashes)
    # Admission order is the pre-registered independent randomization.  Journal
    # and span hashes are retained as diagnostics, but distinct orders are the
    # required eligibility condition.
    student_t_eligible = distinct_orders == len(EXPECTED_SEEDS)
    return {
        "seed_count": len(per_seed),
        "workflow_pair_count": sum(item["workflow_pair_count"] for item in per_seed),
        "per_seed": per_seed,
        "distinct_admission_order_count": distinct_orders,
        "realized_journal_span_hash_pair_count": len(realized_hashes),
        "deterministic_repeats": not student_t_eligible,
        "student_t_95_eligible": student_t_eligible,
        "student_t_degrees_of_freedom": 4 if student_t_eligible else None,
        "independent_unit": "shared_workflow_admission_randomization_seed",
    }


def _validate_aggregate_schema(root: Path, aggregate: Mapping[str, Any]) -> None:
    schema_path = repository_path(
        root,
        "benchmark/AegisKV/experiments/schemas/aegiskv-no-failure-overhead.schema.json",
        "no-failure aggregate schema",
    )
    schema = _mapping(load_json_strict(schema_path), "no-failure aggregate schema")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(aggregate),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        raise AcceptanceError(f"aggregate schema validation failed: {errors[0].message}")


def _classifier_checks(classifier: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    validation = _mapping(classifier.get("validation"), "direct classifier.validation")
    if validation.get("status") != "PASS" or validation.get("fail_closed") is not True:
        raise AcceptanceError("direct classifier validation is not fail-closed PASS")
    checks: dict[str, Mapping[str, Any]] = {}
    for value in _sequence(validation.get("checks"), "direct classifier.validation.checks"):
        check = _mapping(value, "direct classifier validation check")
        name = check.get("check")
        if not isinstance(name, str) or not name:
            raise AcceptanceError("direct classifier validation check lacks a name")
        if name in checks:
            raise AcceptanceError(f"duplicate direct classifier validation check {name!r}")
        if check.get("status") != "PASS":
            raise AcceptanceError(f"direct classifier validation check {name!r} did not PASS")
        checks[name] = check
    return checks


def _verify_direct_classifier(
    root: Path,
    entry: Mapping[str, Any],
    *,
    aggregate_fingerprint: str,
) -> tuple[dict[str, Any], Mapping[str, Any], dict[str, Mapping[str, Any]]]:
    reference = _mapping(
        entry.get("direct_classifier"),
        "registry direct_classifier",
    )
    path_value = reference.get("path")
    path = repository_path(root, path_value, "direct_classifier.path")
    claimed_file_hash = _sha256(reference.get("sha256"), "direct_classifier.sha256")
    actual_file_hash = sha256_file(path)
    if actual_file_hash != claimed_file_hash:
        raise AcceptanceError("direct classifier file SHA-256 mismatch")
    classifier = _mapping(load_json_strict(path), "direct classifier")
    if (
        classifier.get("schema") != EXPECTED_DIRECT_CLASSIFIER_SCHEMA
        or classifier.get("status") != "PASS"
    ):
        raise AcceptanceError("direct classifier schema/status mismatch")
    classifier_fingerprint = _verify_self_fingerprint(classifier, "direct classifier")
    expected_fingerprint = reference.get("fingerprint")
    if expected_fingerprint is not None and (
        classifier_fingerprint
        != _sha256(expected_fingerprint, "direct_classifier.fingerprint")
    ):
        raise AcceptanceError("direct classifier fingerprint binding mismatch")
    if classifier.get("input_artifact_fingerprint") != aggregate_fingerprint:
        raise AcceptanceError("direct classifier input fingerprint mismatch")
    checks = _classifier_checks(classifier)
    evidence = {
        "path": str(path_value),
        "sha256": actual_file_hash,
        "fingerprint": classifier_fingerprint,
        "input_artifact_fingerprint": aggregate_fingerprint,
        "validation_check_count": len(checks),
        "fail_closed": True,
    }
    return evidence, classifier, checks


def _verify_direct_classification(classifier: Mapping[str, Any]) -> dict[str, Any]:
    classification = classifier.get("classification")
    if classification not in DIRECT_CLASSES:
        raise AcceptanceError("direct classifier has an unsupported classification")
    if classifier.get("effect_direction_gate_applied") is not False:
        raise AcceptanceError("direct classifier applied an effect-direction filter")
    if classifier.get("all_cells_retained") is not True:
        raise AcceptanceError("direct classifier did not retain all valid cells")
    if (
        classifier.get("retention_rule")
        != "ALL_VALID_CELLS_RETAINED_INCLUDING_NULL_AND_ADVERSE"
    ):
        raise AcceptanceError("direct classifier retention rule mismatch")
    axes = _sequence(
        classifier.get("classification_axes"), "direct classifier.classification_axes"
    )
    if list(axes) != ["recompute_tokens", "recovery_ready_latency_ns"]:
        raise AcceptanceError("direct classifier axes are not the accepted direct-path axes")
    deltas = _mapping(
        classifier.get("paired_deltas_aegiskv_minus_mooncake"),
        "direct classifier paired deltas",
    )
    required_deltas = {
        "recompute_tokens",
        "prefix_materialization_latency_ns",
        "recovery_ready_latency_ns",
        "failure_to_completion_latency_ns",
    }
    if set(deltas) != required_deltas:
        raise AcceptanceError("direct classifier lacks the exact four paired deltas")
    for name, value in deltas.items():
        _integer(value, f"direct classifier delta {name}")
    return {
        "classification": classification,
        "paired_deltas_aegiskv_minus_mooncake": dict(deltas),
        "delta_signs": classifier.get("delta_signs"),
        "propagation_label": classifier.get("propagation_label"),
        "effect_direction_gate_applied": False,
        "all_cells_retained": True,
        "retention_rule": classifier.get("retention_rule"),
    }


def _verify_failure_causal_contract(
    classifier: Mapping[str, Any],
    checks: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    missing = sorted(CAUSAL_CLASSIFIER_CHECKS - checks.keys())
    if missing:
        raise AcceptanceError(
            "direct classifier lacks causal validation checks: " + ", ".join(missing)
        )
    focus_span_id = classifier.get("focus_span_id")
    if not isinstance(focus_span_id, str) or not focus_span_id:
        raise AcceptanceError("direct classifier lacks a focus span identity")
    focus_check = checks["EXACTLY_ONE_FOCUS_SPAN"].get("evidence")
    if focus_check != focus_span_id:
        raise AcceptanceError("direct classifier focus validation evidence mismatch")
    matched = _mapping(
        checks["MATCHED_INTERVENTION_AND_REALIZED_OUTCOMES"].get("evidence"),
        "matched intervention and realized outcomes",
    )
    if matched.get("focus_span_id") != focus_span_id:
        raise AcceptanceError("causal failure evidence focus identity mismatch")
    for field in (
        "target_gpu_id",
        "target_workload_progress_per_mille",
        "outage_duration_ns",
        "realized_outcomes_by_system",
    ):
        if field not in matched:
            raise AcceptanceError(f"causal failure evidence lacks {field}")
    outcomes = _mapping(
        matched["realized_outcomes_by_system"],
        "causal failure realized outcomes",
    )
    if set(outcomes) != set(SYSTEM_IDS):
        raise AcceptanceError("causal failure outcomes lack the exact two systems")
    for system_id in SYSTEM_IDS:
        outcome = _mapping(outcomes[system_id], f"causal outcome {system_id}")
        for field in (
            "injection_timestamp_ns",
            "active_span_ids",
            "queued_span_ids",
            "reroute_only_queued_span_ids",
        ):
            if field not in outcome:
                raise AcceptanceError(
                    f"causal outcome {system_id} lacks {field}"
                )
        if focus_span_id not in _sequence(
            outcome["active_span_ids"],
            f"causal outcome {system_id}.active_span_ids",
        ):
            raise AcceptanceError(
                f"causal outcome {system_id} does not include the focus victim"
            )
    return {
        "focus_span_id": focus_span_id,
        "failure_schedule_fingerprint": checks["MATCHED_SINGLE_FAILURE_SCHEDULE"].get(
            "evidence"
        ),
        "post_treatment_impact_contract_frozen": False,
        "physical_failure_target": matched["target_gpu_id"],
        "target_workload_progress_per_mille": matched[
            "target_workload_progress_per_mille"
        ],
        "outage_duration_ns": matched["outage_duration_ns"],
        "realized_outcomes_by_system": dict(outcomes),
    }


def _failure_pair_statistics(
    aggregate: Mapping[str, Any],
    classifier: Mapping[str, Any],
) -> dict[str, Any]:
    cells_value = aggregate.get("cells")
    if not isinstance(cells_value, list):
        return {
            "supported": False,
            "reason": "AGGREGATE_HAS_NO_PAIRED_WORKFLOW_CELLS",
            "direct_mechanism_evidence_accepted": True,
            "student_t_95_eligible": False,
            "aggregate_mean_p95_panels_authorized": False,
        }
    cells = _sequence(cells_value, "aggregate.cells")
    if not cells:
        return {
            "supported": False,
            "reason": "AGGREGATE_HAS_NO_PAIRED_WORKFLOW_CELLS",
            "direct_mechanism_evidence_accepted": True,
            "student_t_95_eligible": False,
            "aggregate_mean_p95_panels_authorized": False,
        }
    per_seed: list[dict[str, Any]] = []
    seeds: set[int] = set()
    for value in cells:
        cell = _mapping(value, "aggregate.cells[]")
        seed = _integer(cell.get("seed"), "failure cell.seed")
        if seed in seeds:
            raise AcceptanceError("failure aggregate contains duplicate seed cells")
        seeds.add(seed)
        systems = _mapping(cell.get("systems"), "failure cell.systems")
        if set(systems) != set(SYSTEM_IDS):
            raise AcceptanceError("failure cell lacks the exact paired systems")
        moon = _mapping(systems[SYSTEM_IDS[0]], "failure cell Mooncake")
        aegis = _mapping(systems[SYSTEM_IDS[1]], "failure cell AegisKV")
        moon_wct = {
            str(key): _integer(value, f"failure Mooncake WCT {key}", minimum=1)
            for key, value in _mapping(
                moon.get("workflow_wct_ns"), "failure Mooncake WCT"
            ).items()
        }
        aegis_wct = {
            str(key): _integer(value, f"failure AegisKV WCT {key}", minimum=1)
            for key, value in _mapping(
                aegis.get("workflow_wct_ns"), "failure AegisKV WCT"
            ).items()
        }
        if set(moon_wct) != set(aegis_wct) or not moon_wct:
            raise AcceptanceError("failure paired WCT maps must share workflow IDs")
        deltas = {key: aegis_wct[key] - moon_wct[key] for key in sorted(moon_wct)}
        per_seed.append(
            {
                "seed": seed,
                "workflow_pair_count": len(deltas),
                "workflow_deltas_ns": deltas,
                "mean_delta_ns": sum(deltas.values()) / len(deltas),
                "mooncake_p95": _nearest_rank_identity(moon_wct, 95),
                "aegiskv_p95": _nearest_rank_identity(aegis_wct, 95),
                "winner_tie_loser": {
                    "aegiskv_winner_count": sum(value < 0 for value in deltas.values()),
                    "tie_count": sum(value == 0 for value in deltas.values()),
                    "aegiskv_loser_count": sum(value > 0 for value in deltas.values()),
                },
            }
        )
    per_seed.sort(key=lambda item: item["seed"])
    seed_count = len(per_seed)
    interval_eligible = seed_count >= 2
    return {
        "supported": True,
        "focus_span_id": classifier.get("focus_span_id"),
        "seed_count": seed_count,
        "workflow_pair_count": sum(item["workflow_pair_count"] for item in per_seed),
        "per_seed": per_seed,
        "independent_unit": "shared_failure_experiment_seed",
        "student_t_95_eligible": interval_eligible,
        "student_t_degrees_of_freedom": seed_count - 1 if interval_eligible else None,
        "direct_mechanism_evidence_accepted": True,
        "aggregate_mean_p95_panels_authorized": interval_eligible,
        "limitation": (
            None
            if interval_eligible
            else "SINGLE_SEED_PRIMARY_FAILURE_CANNOT_JUSTIFY_SEED_LEVEL_INTERVAL"
        ),
    }


def _terminal_class(
    *,
    disposition: str,
    first_failed_gate: int | None,
    historical: bool,
    stale: bool,
    direct_class: str | None,
) -> str:
    # Explicit precedence required by the acceptance architecture.
    if disposition == "INFEASIBLE":
        return "INFEASIBLE"
    if historical:
        return "HISTORICAL"
    if stale:
        return "STALE"
    if disposition != "COMPLETED" or first_failed_gate is not None:
        return "FAILED"
    direct_terminals = {
        "SOURCE_SUBSTITUTION_OR_NULL_DIRECT_MECHANISM": "NULL_DIRECT",
        "DIRECT_RECOVERY_MIXED": "MIXED_DIRECT",
        "ADVERSE_DIRECT_MECHANISM": "ADVERSE_DIRECT",
    }
    return "VALID" if direct_class is None else direct_terminals.get(direct_class, "VALID")


def _campaign_repository_path(root: Path, value: object, where: str) -> Path:
    if not isinstance(value, str) or not value:
        raise AcceptanceError(f"{where} must be a non-empty path")
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            relative = candidate.resolve().relative_to(root.resolve()).as_posix()
        except ValueError as error:
            raise AcceptanceError(f"{where} must remain inside the repository") from error
    else:
        relative = value
    return repository_path(root, relative, where)


def _campaign_attempt(root: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    """Materialize the eight campaign-specific gates without trusting its acceptance."""

    # Imported lazily because the campaign builder imports this module's JSON/hash helpers.
    from moonkvsim.aegiskv import qwen3_8b_failure_campaign as campaign

    attempt_id = entry.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise AcceptanceError("registry attempt_id must be a non-empty string")
    disposition = entry.get("disposition")
    if disposition not in DISPOSITIONS:
        raise AcceptanceError(f"attempt {attempt_id}: unsupported disposition")
    scenario = _mapping(entry.get("scenario"), f"attempt {attempt_id}.scenario")
    gates: list[dict[str, Any]] = []
    first_failed: int | None = None
    artifact_evidence: dict[str, Any] = {}
    document: Mapping[str, Any] | None = None
    artifact_path: Path | None = None
    source_documents: list[Mapping[str, Any]] = []
    classifier_documents: list[Mapping[str, Any]] = []
    artifact_paths: list[Path] = []
    classifier_paths: list[Path] = []
    reconstructed: Mapping[str, Any] | None = None
    verification_root = root
    frozen_records: dict[str, Mapping[str, Any]] = {}
    expected_variants: dict[str, Mapping[str, Any]] = {}

    if disposition != "COMPLETED":
        code = {
            "MISSING": "ARTIFACT_MISSING",
            "FAILED": "PRODUCER_REPORTED_FAILED",
            "ABORTED": "ATTEMPT_ABORTED",
            "INFEASIBLE": "ATTEMPT_INFEASIBLE",
        }[str(disposition)]
        gates.append(_gate(1, "FAIL", [code], {"disposition": disposition}))
        first_failed = 1
    else:
        try:
            artifact_path = repository_path(
                root, entry.get("artifact_path"), f"attempt {attempt_id}.artifact_path"
            )
            document = _mapping(load_json_strict(artifact_path), "failure campaign")
            if (
                document.get("schema") != EXPECTED_FAILURE_CAMPAIGN_SCHEMA
                or document.get("status") != "PASS"
            ):
                raise AcceptanceError("unsupported failure campaign schema/status")
            campaign_fingerprint = _verify_self_fingerprint(document, "failure campaign")
            seeds = _sequence(document.get("seeds"), "failure campaign.seeds")
            if len(seeds) != len(EXPECTED_SEEDS):
                raise AcceptanceError("failure campaign must contain exactly five seeds")
            source_hashes: list[str] = []
            classifier_hashes: list[str] = []
            for expected_seed, raw_seed in zip(EXPECTED_SEEDS, seeds, strict=True):
                seed = _mapping(raw_seed, f"failure campaign seed {expected_seed}")
                if seed.get("seed") != expected_seed:
                    raise AcceptanceError("failure campaign seed order/set mismatch")
                artifact_reference = _mapping(seed.get("artifact"), "seed artifact")
                classifier_reference = _mapping(seed.get("classifier"), "seed classifier")
                source_path = _campaign_repository_path(
                    root, artifact_reference.get("path"), "seed artifact.path"
                )
                classifier_path = _campaign_repository_path(
                    root, classifier_reference.get("path"), "seed classifier.path"
                )
                source = _mapping(campaign._load_document(source_path), "seed artifact")
                classifier = _mapping(
                    campaign._load_document(classifier_path), "seed classifier"
                )
                source_fingerprint = _verify_self_fingerprint(source, "seed artifact")
                classifier_fingerprint = _verify_self_fingerprint(
                    classifier, "seed classifier"
                )
                source_hash = sha256_file(source_path)
                classifier_hash = sha256_file(classifier_path)
                if (
                    source_hash != _sha256(artifact_reference.get("sha256"), "artifact sha256")
                    or source_fingerprint
                    != _sha256(artifact_reference.get("fingerprint"), "artifact fingerprint")
                    or classifier_hash
                    != _sha256(classifier_reference.get("sha256"), "classifier sha256")
                    or classifier_fingerprint
                    != _sha256(
                        classifier_reference.get("fingerprint"),
                        "classifier fingerprint",
                    )
                ):
                    raise AcceptanceError("campaign seed artifact/classifier binding mismatch")
                if classifier.get("input_artifact_fingerprint") != source_fingerprint:
                    raise AcceptanceError("classifier input artifact binding mismatch")
                artifact_paths.append(source_path)
                classifier_paths.append(classifier_path)
                source_documents.append(source)
                classifier_documents.append(classifier)
                source_hashes.append(source_hash)
                classifier_hashes.append(classifier_hash)
            artifact_evidence = {
                "path": str(entry.get("artifact_path")),
                "sha256": sha256_file(artifact_path),
                "fingerprint": campaign_fingerprint,
                "raw_artifact_count": 10,
                "raw_artifact_hashes": [
                    value
                    for pair in zip(source_hashes, classifier_hashes, strict=True)
                    for value in pair
                ],
            }
            gates.append(
                _gate(
                    1,
                    "PASS",
                    [],
                    {
                        **artifact_evidence,
                        "source_artifact_hashes": source_hashes,
                        "classifier_hashes": classifier_hashes,
                        "seed_count": 5,
                    },
                )
            )
        except (AcceptanceError, OSError) as error:
            gates.append(
                _gate(1, "FAIL", ["CAMPAIGN_INTEGRITY_FAILED"], {"detail": str(error)})
            )
            first_failed = 1

    if first_failed is None:
        assert document is not None
        try:
            bindings = [campaign._binding(value) for value in source_documents]
            if any(value != bindings[0] for value in bindings[1:]):
                raise AcceptanceError("source/config/workload binding differs across seeds")
            if _mapping(document.get("binding"), "campaign.binding") != bindings[0]:
                raise AcceptanceError("campaign binding differs from source artifacts")
            verification_root = source_root_for_attempt(root, entry)
            for source in source_documents:
                binding = source["source"]
                implementation_files = [{
                    "path": rel,
                    "sha256": sha256_file(repository_path(verification_root, rel,
                                                           "primary implementation")),
                } for rel in binding["implementation_paths"]]
                if fingerprint(implementation_files) != binding["implementation_fingerprint"]:
                    raise AcceptanceError("primary implementation differs from frozen source")
            from moonkvsim.aegiskv.experiment import core_variants
            from moonkvsim.aegiskv.experiment_config import (
                default_config_dir,
                load_experiment_configs,
                model_parameters_from_configs,
            )
            parameters = model_parameters_from_configs(load_experiment_configs(
                default_config_dir(verification_root), root=verification_root,
            ))
            expected_variants = {v.variant_id: v.to_dict() for v in core_variants(parameters)
                                 if v.variant_id in SYSTEM_IDS}
            if {s: fingerprint(v) for s, v in expected_variants.items()} != (
                bindings[0]["variant_fingerprints"]
            ):
                raise AcceptanceError("primary configuration differs from frozen variants")
            normalized_protocols = []
            for expected_seed, source in zip(EXPECTED_SEEDS, source_documents, strict=True):
                protocol = dict(_mapping(source.get("protocol"), "seed protocol"))
                if protocol.pop("seed", None) != expected_seed:
                    raise AcceptanceError("source protocol seed mismatch")
                if protocol.pop("workflow_admission_seed", None) != expected_seed:
                    raise AcceptanceError("source workflow admission seed mismatch")
                focus_span_ids = _sequence(
                    protocol.pop("focus_span_ids", None),
                    "seed protocol.focus_span_ids",
                )
                if len(focus_span_ids) != 1:
                    raise AcceptanceError("source protocol must declare one focus span")
                normalized_protocols.append(protocol)
            if any(value != normalized_protocols[0] for value in normalized_protocols[1:]):
                raise AcceptanceError("failure protocol differs across seeds")
            gates.append(
                _gate(
                    2,
                    "PASS",
                    [],
                    {
                        "binding_fingerprint": fingerprint(bindings[0]),
                        "normalized_protocol_fingerprint": fingerprint(
                            normalized_protocols[0]
                        ),
                        "source_seed_count": 5,
                        "source_root": entry.get("source_root", "."),
                    },
                )
            )
        except AcceptanceError as error:
            gates.append(
                _gate(2, "FAIL", ["CAMPAIGN_BINDING_FAILED"], {"detail": str(error)})
            )
            first_failed = 2
    else:
        gates.append(_blocked_gate(2, first_failed))

    if first_failed is None:
        try:
            admission_hashes: list[str] = []
            workflow_id_hashes: list[str] = []
            workload_binding = source_documents[0]["source"]["workload"]
            _load_workload(verification_root, workload_binding)
            path = repository_path(verification_root, workload_binding["declared_path"],
                                   "primary workload")
            with path.open() as stream:
                for line in stream:
                    record = json.loads(line)
                    frozen_records[record["span_id"]] = {
                        key: record[key] for key in
                        ("workflow_id", "prompt_tokens", "output_tokens")
                    }
            for expected_seed, source in zip(EXPECTED_SEEDS, source_documents, strict=True):
                seed_protocol = _mapping(source.get("protocol"), "seed protocol")
                selection = _mapping(
                    _mapping(source.get("source"), "seed source").get("selection"),
                    "seed source.selection",
                )
                workload = _mapping(
                    _mapping(source.get("source"), "seed source").get("workload"),
                    "seed source.workload",
                )
                selected = list(
                    _sequence(selection.get("selected_workflow_ids"), "selected workflows")
                )
                if (
                    seed_protocol.get("workflow_count") != EXPECTED_WORKFLOW_COUNT
                    or seed_protocol.get("source_workflow_count") != EXPECTED_WORKFLOW_COUNT
                    or seed_protocol.get("workflow_filtering") is not False
                    or workload.get("record_count") != EXPECTED_SPAN_COUNT
                    or selection.get("kind") != "complete_frozen_workload_no_filtering"
                    or len(selected) != EXPECTED_WORKFLOW_COUNT
                    or len(set(selected)) != EXPECTED_WORKFLOW_COUNT
                ):
                    raise AcceptanceError("campaign does not use the exact full workload")
                runs = {
                    system_id: campaign._run(source, system_id)
                    for system_id in SYSTEM_IDS
                }
                paired = [
                    campaign._admission_binding(
                        runs[system_id], f"seed {expected_seed}.{system_id}"
                    )
                    for system_id in SYSTEM_IDS
                ]
                if paired[0] != paired[1] or set(paired[0][0]) != set(selected):
                    raise AcceptanceError("paired admission/workload identities differ")
                if len(paired[0][0]) != EXPECTED_WORKFLOW_COUNT:
                    raise AcceptanceError("admission order is not the full workload")
                admission_hashes.append(paired[0][1])
                workflow_id_hashes.append(fingerprint(sorted(selected)))
            if len(set(admission_hashes)) != len(EXPECTED_SEEDS):
                raise AcceptanceError(
                    "five distinct admission orders are required for campaign inference"
                )
            if len(set(workflow_id_hashes)) != 1:
                raise AcceptanceError("selected workflow identities differ across seeds")
            gates.append(
                _gate(
                    3,
                    "PASS",
                    [],
                    {
                        "workflow_count": EXPECTED_WORKFLOW_COUNT,
                        "span_count": EXPECTED_SPAN_COUNT,
                        "workflow_filtering": False,
                        "distinct_admission_order_count": 5,
                        "admission_order_hashes": admission_hashes,
                        "workflow_ids_sha256": workflow_id_hashes[0],
                    },
                )
            )
        except AcceptanceError as error:
            gates.append(
                _gate(3, "FAIL", ["CAMPAIGN_WORKLOAD_FAILED"], {"detail": str(error)})
            )
            first_failed = 3
    else:
        gates.append(_blocked_gate(3, first_failed))

    if first_failed is None:
        assert document is not None
        try:
            causal_evidence = []
            focus_ids_by_seed: dict[str, str] = {}
            rows = _sequence(document.get("seeds"), "campaign.seeds")
            for expected_seed, classifier, raw_row in zip(
                EXPECTED_SEEDS, classifier_documents, rows, strict=True
            ):
                checks = _classifier_checks(classifier)
                causal = _verify_failure_causal_contract(classifier, checks)
                row = _mapping(raw_row, "campaign seed")
                matched = _mapping(
                    checks["MATCHED_INTERVENTION_AND_REALIZED_OUTCOMES"].get(
                        "evidence"
                    ),
                    "matched intervention and realized outcomes",
                )
                if (
                    _mapping(row.get("causal_contract"), "campaign causal contract")
                    != matched
                ):
                    raise AcceptanceError("campaign causal contract differs from classifier")
                focus_ids_by_seed[str(expected_seed)] = str(causal["focus_span_id"])
                causal_evidence.append({"seed": expected_seed, **causal})
            gates.append(
                _gate(
                    4,
                    "PASS",
                    [],
                    {
                        "seed_contracts": causal_evidence,
                        "focus_span_ids_by_seed": focus_ids_by_seed,
                        "shared_contract_per_seed": True,
                    },
                )
            )
        except AcceptanceError as error:
            gates.append(
                _gate(4, "FAIL", ["CAMPAIGN_CAUSAL_CONTRACT_FAILED"], {"detail": str(error)})
            )
            first_failed = 4
    else:
        gates.append(_blocked_gate(4, first_failed))

    if first_failed is None:
        assert document is not None
        try:
            selector_fingerprints: list[str] = []
            classifier_check_counts: list[int] = []
            raw_audits = []
            from moonkvsim.aegiskv.paper_artifacts import load_raw_evidence
            from moonkvsim.aegiskv.paper_primary_reconstruction import verify_primary_raw
            rows = _sequence(document.get("seeds"), "campaign.seeds")
            for expected_seed, source, classifier, raw_row in zip(
                EXPECTED_SEEDS,
                source_documents,
                classifier_documents,
                rows,
                strict=True,
            ):
                checks = _classifier_checks(classifier)
                classifier_check_counts.append(len(checks))
                for scenario_name in ("no_failure", "gpu_failure"):
                    for system_id in SYSTEM_IDS:
                        compact = campaign._run(source, system_id, scenario_name)
                        LOG.info("primary raw seed=%d %s %s", expected_seed,
                                 scenario_name, system_id)
                        binding = _mapping(compact.get("raw_evidence"), "primary raw evidence")
                        raw_path = _campaign_repository_path(root, binding["path"], "primary raw")
                        raw = load_raw_evidence(raw_path, expected_sha256=binding["sha256"])
                        report = verify_primary_raw(
                            raw, compact, records=frozen_records,
                            expected_variant=expected_variants[system_id],
                        )
                        raw_audits.append({"seed": expected_seed, "scenario": scenario_name,
                                           "system": system_id, "raw_sha256": binding["sha256"],
                                           "focus_recovery": report["focus_recovery"],
                                           "audit_sha256": fingerprint(report)})
                        del raw
                focus = str(classifier.get("focus_span_id"))
                runs = {
                    system_id: campaign._run(source, system_id)
                    for system_id in SYSTEM_IDS
                }
                selectors = {
                    system_id: campaign._selection_event(
                        runs[system_id],
                        focus_span_id=focus,
                        where=f"seed {expected_seed}.{system_id}",
                    )
                    for system_id in SYSTEM_IDS
                }
                row = _mapping(raw_row, "campaign seed")
                if (
                    _mapping(
                        row.get("recovery_selector_evidence"), "campaign selector evidence"
                    )
                    != selectors
                ):
                    raise AcceptanceError("campaign selector evidence differs from source")
                selector_fingerprints.append(fingerprint(selectors))
            gates.append(
                _gate(
                    5,
                    "PASS",
                    [],
                    {
                        "direct_classifier_validation_check_counts": classifier_check_counts,
                        "selector_evidence_fingerprints": selector_fingerprints,
                        "selector_seed_count": 5,
                        "public_direct_classifier_evidence": True,
                        "complete_raw_reconstruction": raw_audits,
                    },
                )
            )
        except (ValueError, KeyError, TypeError, OSError, StopIteration) as error:
            gates.append(
                _gate(5, "FAIL", ["CAMPAIGN_DIRECT_EVIDENCE_FAILED"], {"detail": str(error)})
            )
            first_failed = 5
    else:
        gates.append(_blocked_gate(5, first_failed))

    if first_failed is None:
        assert document is not None
        try:
            classes = []
            for classifier in classifier_documents:
                evidence = _verify_direct_classification(classifier)
                classes.append(str(evidence["classification"]))
            rows = _sequence(document.get("seeds"), "campaign.seeds")
            if [row.get("direct_class") for row in rows if isinstance(row, Mapping)] != classes:
                raise AcceptanceError("campaign direct classes differ from classifiers")
            counts = {name: classes.count(name) for name in sorted(DIRECT_CLASSES)}
            if _mapping(document.get("direct_class_counts"), "direct class counts") != counts:
                raise AcceptanceError("campaign direct class counts are not exact")
            campaign_protocol = _mapping(document.get("protocol"), "campaign.protocol")
            if (
                campaign_protocol.get("effect_direction_filter_applied") is not False
                or campaign_protocol.get("workflow_filtering") is not False
                or campaign_protocol.get("retention")
                != "EVERY_SEED_INCLUDING_NULL_MIXED_AND_ADVERSE"
            ):
                raise AcceptanceError("campaign retention/no-filtering contract mismatch")
            gates.append(
                _gate(
                    6,
                    "PASS",
                    [],
                    {
                        "classification_universe": sorted(DIRECT_CLASSES),
                        "observed_direct_classes": classes,
                        "direct_class_counts": counts,
                        "all_five_seeds_retained": True,
                        "effect_direction_filter_applied": False,
                        "workflow_filtering": False,
                    },
                )
            )
        except AcceptanceError as error:
            gates.append(
                _gate(6, "FAIL", ["CAMPAIGN_RETENTION_FAILED"], {"detail": str(error)})
            )
            first_failed = 6
    else:
        gates.append(_blocked_gate(6, first_failed))

    statistics: dict[str, Any] | None = None
    if first_failed is None:
        assert document is not None
        try:
            generator = _mapping(document.get("classifier_generator"), "classifier generator")
            generator_path = _campaign_repository_path(
                root, generator.get("path"), "classifier_generator.path"
            )
            if sha256_file(generator_path) != _sha256(
                generator.get("sha256"), "classifier_generator.sha256"
            ):
                raise AcceptanceError("classifier generator source hash mismatch")
            reconstructed = campaign.build_campaign(
                artifact_paths=artifact_paths,
                classifier_paths=classifier_paths,
                classifier_source=generator_path,
                require_independent_admission=True,
            )
            for field in (
                "protocol",
                "binding",
                "focus_span_ids_by_seed",
                "seed_count",
                "seeds",
                "inference",
                "direct_class_counts",
                "modeled_uncalibrated",
                "physical_execution",
                "paper_ready",
                "classifier_generator",
            ):
                if document.get(field) != reconstructed.get(field):
                    raise AcceptanceError(
                        f"campaign {field} differs from verifier reconstruction"
                    )
            inference = _mapping(reconstructed.get("inference"), "reconstructed inference")
            intervals = _mapping(inference.get("student_t_95"), "student_t_95")
            if any(
                _mapping(intervals.get(name), f"student_t_95.{name}").get("n") != 5
                or _mapping(intervals.get(name), f"student_t_95.{name}").get("eligible")
                is not True
                for name in (
                    "focus_failure_penalty_did",
                    "whole_mean_failure_penalty_did",
                    "mean_delta",
                    "p95_delta",
                    "max_delta",
                )
            ):
                raise AcceptanceError("campaign lacks five-seed Student-t inference")
            statistics = {
                "seed_count": 5,
                "workflow_pair_count": 5 * EXPECTED_WORKFLOW_COUNT,
                "independent_unit": inference.get("independent_unit"),
                "distinct_admission_order_count": inference.get(
                    "distinct_admission_order_count"
                ),
                "student_t_95": dict(intervals),
                "per_seed": [
                    {
                        "seed": row["seed"],
                        "seed_level_estimands_ns": row["seed_level_estimands_ns"],
                        "percentile_identities": row["percentile_identities"],
                        "winner_tie_loser": row["winner_tie_loser"],
                        "worst_collateral": row["worst_collateral"],
                    }
                    for row in _sequence(reconstructed.get("seeds"), "reconstructed seeds")
                    if isinstance(row, Mapping)
                ],
                "workflow_observations_are_descriptive_not_inferential": True,
                "single_seed_masquerade_rejected": True,
            }
            gates.append(
                _gate(
                    7,
                    "PASS",
                    [],
                    {
                        "statistics_sha256": fingerprint(statistics),
                        "seed_count": 5,
                        "student_t_95_eligible": True,
                        "reconstructed_estimands": [
                            "Focus failure-penalty DiD",
                            "Whole mean failure-penalty DiD",
                            "Failure-run Mean",
                            "Failure-run P95",
                            "Failure-run Max",
                        ],
                        "winner_tie_loser_verified": True,
                        "collateral_identities_verified": True,
                    },
                )
            )
        except (AcceptanceError, KeyError, TypeError) as error:
            gates.append(
                _gate(7, "FAIL", ["CAMPAIGN_INFERENCE_FAILED"], {"detail": str(error)})
            )
            first_failed = 7
    else:
        gates.append(_blocked_gate(7, first_failed))

    historical = entry.get("historical", False) is True
    stale = entry.get("stale", False) is True
    terminal = _terminal_class(
        disposition=str(disposition),
        first_failed_gate=first_failed,
        historical=historical,
        stale=stale,
        direct_class=None,
    )
    allowed_panels = (
        list(AUTHORIZED_FAILURE_CAMPAIGN_PANELS) if terminal == "VALID" else []
    )
    gates.append(
        _gate(
            8,
            "PASS",
            [],
            {
                "disposition": disposition,
                "terminal_class": terminal,
                "first_failed_gate": first_failed,
                "campaign_terminal_rule": (
                    "VALID_ONLY_IF_ALL_FIVE_SEEDS_AND_ALL_CLASSES_ARE_RETAINED_"
                    "WITHOUT_WORKFLOW_OR_EFFECT_DIRECTION_FILTERING"
                ),
                "allowed_panel_ids": allowed_panels,
                "explicitly_unauthorized_panel_ids": ["FIGURE_4_A"],
            },
        )
    )
    body: dict[str, Any] = {
        "attempt_id": attempt_id,
        "scenario": dict(scenario),
        "disposition": disposition,
        "artifact": artifact_evidence or None,
        "gates": gates,
        "terminal_class": terminal,
        "accepted_for_numerical_aggregates": terminal == "VALID",
        "allowed_panel_ids": allowed_panels,
        "statistics": statistics,
        "direct_classifier": {
            "kind": "FIVE_SEED_CLASSIFIER_SET",
            "artifacts": [
                {
                    "path": path.resolve().relative_to(root.resolve()).as_posix(),
                    "sha256": sha256_file(path),
                    "fingerprint": classifier.get("fingerprint"),
                    "classification": classifier.get("classification"),
                }
                for path, classifier in zip(
                    classifier_paths, classifier_documents, strict=True
                )
            ],
            "all_cells_retained": first_failed is None,
            "effect_direction_gate_applied": False,
        }
        if classifier_documents
        else None,
        "reason_codes": list(entry.get("reason_codes", [])),
    }
    return {**body, "fingerprint": fingerprint(body)}


def _reconstruct_sweep_cell(task: tuple[Any, ...]) -> tuple[int, int]:
    from moonkvsim.aegiskv.paper_artifacts import load_raw_evidence, verify_compact_run
    from moonkvsim.aegiskv.paper_study_reconstruction import (
        reconstruct_transfer_cost,
        reconstruct_workflow_metrics,
    )

    raw_value, artifact_path, records = task
    scheduler_count = 0
    formal_count = 0
    cell = _mapping(raw_value, "raw_seed_cell")
    systems = _mapping(cell.get("systems"), "raw_seed_cell.systems")
    for system_id in SYSTEM_IDS:
        LOG.info("sensitivity raw seed=%s F=%s C=%s %s", cell.get("seed"),
                 cell.get("failure_count"), cell.get("workflow_concurrency"), system_id)
        run = _mapping(
            _mapping(systems.get(system_id), f"systems.{system_id}").get("run"),
            f"systems.{system_id}.run",
        )
        assert artifact_path is not None
        binding = _mapping(run.get("raw_evidence"), "run.raw_evidence")
        raw_name = binding.get("file")
        if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
            raise AcceptanceError("raw evidence filename must be a basename")
        try:
            raw = load_raw_evidence(
                artifact_path.parent / "checkpoint-proof" / raw_name,
                expected_sha256=_sha256(binding.get("sha256"), "raw.sha256"),
            )
            verify_compact_run(raw, run)
            reconstruct_workflow_metrics(raw, records)
            reconstruct_transfer_cost(raw)
            rebuilt_scheduler = audit_continuous_scheduler_evidence(
                raw["payload"], raw["representative"]
            ).to_dict()
            if rebuilt_scheduler != run.get("continuous_scheduler_audit"):
                raise ValueError("recorded scheduler report differs from raw audit")
            if system_id == SYSTEM_IDS[1]:
                rebuilt_formal = audit_formal_algorithm_run(
                    raw["payload"], raw["representative"]
                ).to_dict()
                if rebuilt_formal != run.get("formal_algorithm_audit"):
                    raise ValueError("recorded policy report differs from raw audit")
            del raw
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise AcceptanceError(
                f"raw evidence reconstruction failed: {error}"
            ) from error
        scheduler = _mapping(
            run.get("continuous_scheduler_audit"),
            f"{system_id}.continuous_scheduler_audit",
        )
        if scheduler.get("status") != "PASS":
            raise AcceptanceError("continuous scheduler audit did not pass")
        _verify_self_fingerprint(scheduler, "continuous scheduler audit")
        scheduler_count += 1
        if system_id == SYSTEM_IDS[1]:
            formal = _mapping(
                run.get("formal_algorithm_audit"),
                "aegiskv formal_algorithm_audit",
            )
            if formal.get("status") != "PASS":
                raise AcceptanceError("AegisKV formal audit did not pass")
            _verify_self_fingerprint(formal, "AegisKV formal audit")
            formal_count += 1
    return scheduler_count, formal_count


def _paper_sweep_attempt(root: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    """Accept the complete five-seed Figure 5 sensitivity matrix fail-closed."""

    from moonkvsim.aegiskv.paper_sweep_cost_statistics import build_sweep_cost_statistics
    from moonkvsim.aegiskv.paper_sweep_statistics import (
        build_paper_sweep_statistics,
    )

    attempt_id = entry.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise AcceptanceError("paper-sweep attempt_id must be non-empty")
    disposition = entry.get("disposition")
    if disposition not in DISPOSITIONS:
        raise AcceptanceError(f"attempt {attempt_id}: unsupported disposition")
    scenario = _mapping(entry.get("scenario"), f"attempt {attempt_id}.scenario")
    gates: list[dict[str, Any]] = []
    first_failed: int | None = None
    document: Mapping[str, Any] | None = None
    artifact_path: Path | None = None
    artifact_evidence: dict[str, Any] = {}
    statistics: dict[str, Any] | None = None
    verification_root = root
    records: dict[str, Mapping[str, Any]] = {}
    cost_statistics: dict[str, Any] | None = None

    if disposition != "COMPLETED":
        code = {
            "MISSING": "ARTIFACT_MISSING",
            "FAILED": "PRODUCER_REPORTED_FAILED",
            "ABORTED": "ATTEMPT_ABORTED",
            "INFEASIBLE": "ATTEMPT_INFEASIBLE",
        }[str(disposition)]
        gates.append(_gate(1, "FAIL", [code], {"disposition": disposition}))
        first_failed = 1
    else:
        try:
            artifact_path = repository_path(
                root, entry.get("artifact_path"), f"attempt {attempt_id}.artifact_path"
            )
            document = _mapping(load_json_strict(artifact_path), "paper sweep")
            if (
                document.get("schema") != EXPECTED_PAPER_SWEEP_SCHEMA
                or document.get("status") != "PASS"
            ):
                raise AcceptanceError("unsupported or non-PASS paper-sweep artifact")
            artifact_fingerprint = _verify_self_fingerprint(document, "paper sweep")
            raw_cells = _sequence(document.get("raw_seed_cells"), "raw_seed_cells")
            if len(raw_cells) != 35:
                raise AcceptanceError("paper sweep must retain exactly 35 seed cells")
            raw_hashes = [
                fingerprint(_mapping(cell, f"raw_seed_cells[{index}]"))
                for index, cell in enumerate(raw_cells)
            ]
            artifact_evidence = {
                "path": str(entry.get("artifact_path")),
                "sha256": sha256_file(artifact_path),
                "fingerprint": artifact_fingerprint,
                "raw_artifact_count": len(raw_hashes),
                "raw_artifact_hashes": raw_hashes,
            }
            gates.append(_gate(1, "PASS", [], artifact_evidence))
        except AcceptanceError as error:
            gates.append(
                _gate(1, "FAIL", ["ARTIFACT_INTEGRITY_FAILED"], {"detail": str(error)})
            )
            first_failed = 1

    if first_failed is None:
        assert document is not None
        try:
            provenance = _mapping(document.get("provenance"), "provenance")
            verification_root = source_root_for_attempt(root, entry)
            source_files = _mapping(provenance.get("source_files"), "source_files")
            if not source_files:
                raise AcceptanceError("paper sweep has no source-file bindings")
            verified: list[str] = []
            for relative, raw_binding in source_files.items():
                binding = _mapping(raw_binding, f"source_files.{relative}")
                path = repository_path(verification_root, relative,
                                       f"source_files.{relative}.path")
                if sha256_file(path) != _sha256(
                    binding.get("sha256"), f"source_files.{relative}.sha256"
                ):
                    raise AcceptanceError(f"source binding changed: {relative}")
                verified.append(relative)
            if provenance.get("git_worktree_clean") is not True:
                raise AcceptanceError("paper sweep was not produced from a clean worktree")
            gates.append(
                _gate(
                    2,
                    "PASS",
                    [],
                    {
                        "source_file_count": len(verified),
                        "source_root": entry.get("source_root", "."),
                        "source_files": sorted(verified),
                        "git_head": provenance.get("git_head"),
                        "git_worktree_clean": True,
                    },
                )
            )
        except AcceptanceError as error:
            gates.append(
                _gate(2, "FAIL", ["SOURCE_OR_CONFIG_BINDING_FAILED"], {"detail": str(error)})
            )
            first_failed = 2
    else:
        gates.append(_blocked_gate(2, first_failed))

    if first_failed is None:
        assert document is not None
        try:
            provenance = _mapping(document.get("provenance"), "provenance")
            workload = _mapping(provenance.get("workload"), "provenance.workload")
            workload_evidence = _load_workload(verification_root, workload)
            workload_path = repository_path(verification_root, workload["declared_path"],
                                            "sweep workload")
            with workload_path.open() as stream:
                for line in stream:
                    record = json.loads(line)
                    records[record["span_id"]] = {
                        key: record[key] for key in
                        ("workflow_id", "prompt_tokens", "output_tokens")
                    }
            protocol = _mapping(document.get("protocol"), "protocol")
            if (
                protocol.get("workflow_count") != EXPECTED_WORKFLOW_COUNT
                or workload.get("record_count") != EXPECTED_SPAN_COUNT
            ):
                raise AcceptanceError("paper-sweep workload population mismatch")
            gates.append(_gate(3, "PASS", [], workload_evidence))
        except AcceptanceError as error:
            gates.append(_gate(3, "FAIL", ["WORKLOAD_BINDING_FAILED"], {"detail": str(error)}))
            first_failed = 3
    else:
        gates.append(_blocked_gate(3, first_failed))

    if first_failed is None:
        assert document is not None
        try:
            protocol = _mapping(document.get("protocol"), "protocol")
            if (
                protocol.get("seeds") != list(EXPECTED_SEEDS)
                or protocol.get("seed_count") != len(EXPECTED_SEEDS)
                or protocol.get("failure_counts") != [1, 2, 4, 8]
                or protocol.get("workflow_concurrencies") != [8, 16, 24, 32]
                or protocol.get("failure_scale_canonical_concurrency") != 16
                or protocol.get("concurrency_scale_failure_count") != 2
            ):
                raise AcceptanceError("paper-sweep F/C grid or seed contract mismatch")
            identities: set[tuple[int, int, int]] = set()
            for index, raw_value in enumerate(
                _sequence(document.get("raw_seed_cells"), "raw_seed_cells")
            ):
                cell = _mapping(raw_value, f"raw_seed_cells[{index}]")
                identity = (
                    _integer(cell.get("failure_count"), "failure_count", minimum=1),
                    _integer(cell.get("workflow_concurrency"), "workflow_concurrency", minimum=1),
                    _integer(cell.get("seed"), "seed", minimum=0),
                )
                if identity in identities:
                    raise AcceptanceError("duplicate paper-sweep seed cell")
                identities.add(identity)
                systems = _mapping(cell.get("systems"), "cell.systems")
                if set(systems) != set(SYSTEM_IDS):
                    raise AcceptanceError("paper-sweep seed cell lacks a paired system")
                focuses = _mapping(
                    cell.get("failure_focus_span_ids_by_system"),
                    "failure_focus_span_ids_by_system",
                )
                if focuses.get(SYSTEM_IDS[0]) != focuses.get(SYSTEM_IDS[1]):
                    raise AcceptanceError("paired systems used different logical failure focuses")
                targets = _sequence(
                    cell.get("failure_target_workload_progress_per_mille"),
                    "failure targets",
                )
                if len(targets) != identity[0]:
                    raise AcceptanceError("failure target count differs from failure count")
            expected = {
                (failure_count, concurrency, seed)
                for failure_count, concurrency in (
                    *((value, 16) for value in (1, 2, 4, 8)),
                    *((2, value) for value in (8, 24, 32)),
                )
                for seed in EXPECTED_SEEDS
            }
            if identities != expected:
                raise AcceptanceError("paper-sweep seed-cell matrix is incomplete")
            gates.append(
                _gate(
                    4,
                    "PASS",
                    [],
                    {
                        "paired_seed_cell_count": len(identities),
                        "same_logical_focus_within_each_pair": True,
                        "post_treatment_timestamps_or_victims_forced_equal": False,
                    },
                )
            )
        except AcceptanceError as error:
            gates.append(
                _gate(4, "FAIL", ["SENSITIVITY_CAUSAL_CONTRACT_FAILED"], {"detail": str(error)})
            )
            first_failed = 4
    else:
        gates.append(_blocked_gate(4, first_failed))

    if first_failed is None:
        assert document is not None
        try:
            from moonkvsim.aegiskv.paper_audit_parallel import audit_map

            counts = audit_map(_reconstruct_sweep_cell, [
                (cell, artifact_path, records)
                for cell in _sequence(document.get("raw_seed_cells"), "raw_seed_cells")
            ])
            scheduler_count = sum(count[0] for count in counts)
            formal_count = sum(count[1] for count in counts)
            gates.append(
                _gate(
                    5,
                    "PASS",
                    [],
                    {
                        "continuous_scheduler_audit_count": scheduler_count,
                        "formal_aegiskv_audit_count": formal_count,
                        "full_raw_runs_reconstructed": scheduler_count,
                    },
                )
            )
        except AcceptanceError as error:
            gates.append(_gate(5, "FAIL", ["FORMAL_AUDIT_FAILED"], {"detail": str(error)}))
            first_failed = 5
    else:
        gates.append(_blocked_gate(5, first_failed))

    if first_failed is None:
        assert document is not None
        try:
            cost_statistics = build_sweep_cost_statistics(document["raw_seed_cells"], records)
            gates.append(_gate(6, "PASS", [], {
                "cost_effect_statistics_fingerprint": cost_statistics["fingerprint"],
                "focus_recovery_conserves_frozen_prompts": True,
                "ranked_focus_workflow_count": len(
                    cost_statistics["all_focus_workflow_effects_ascending"]
                ),
                "direct_classifier": None,
                "effect_direction_filter_applied": False,
            }))
        except (ValueError, KeyError, TypeError) as error:
            first_failed = 6
            gates.append(_gate(6, "FAIL", ["COST_EFFECT_RECONSTRUCTION_FAILED"],
                               {"detail": str(error)}))
    else:
        gates.append(_blocked_gate(6, first_failed))

    if first_failed is None:
        assert document is not None
        try:
            raw_cells = [
                _mapping(value, "raw_seed_cells[]")
                for value in _sequence(document.get("raw_seed_cells"), "raw_seed_cells")
            ]
            aggregate_by_identity = {
                (
                    _integer(cell.get("failure_count"), "aggregate failure_count", minimum=1),
                    _integer(
                        cell.get("workflow_concurrency"),
                        "aggregate workflow_concurrency",
                        minimum=1,
                    ),
                ): _mapping(cell.get("statistics"), "aggregate statistics")
                for cell in (
                    _mapping(value, "cells[]")
                    for value in _sequence(document.get("cells"), "cells")
                )
            }
            recomputed_hashes: dict[str, str] = {}
            for aggregate_identity in sorted(aggregate_by_identity):
                selected = [
                    cell
                    for cell in raw_cells
                    if (cell.get("failure_count"), cell.get("workflow_concurrency"))
                    == aggregate_identity
                ]
                rebuilt = build_paper_sweep_statistics(selected)
                recorded = aggregate_by_identity[aggregate_identity]
                if rebuilt != recorded:
                    raise AcceptanceError(
                        "paper-sweep statistics mismatch for "
                        f"F={aggregate_identity[0]},C={aggregate_identity[1]}"
                    )
                if (
                    recorded.get("schema") != EXPECTED_PAPER_SWEEP_STATISTICS_SCHEMA
                    or recorded.get("status") != "PASS"
                ):
                    raise AcceptanceError("paper-sweep statistics schema/status mismatch")
                _verify_self_fingerprint(recorded, "paper-sweep statistics")
                recomputed_hashes[
                    f"F{aggregate_identity[0]}C{aggregate_identity[1]}"
                ] = fingerprint(rebuilt)
            if len(recomputed_hashes) != 7:
                raise AcceptanceError("paper sweep must contain seven aggregate cells")
            statistics = {
                "supported": True,
                "seed_count": 5,
                "independent_unit": "paired_experiment_seed",
                "student_t_95_eligible": True,
                "aggregate_statistics_fingerprints": recomputed_hashes,
                "cost_effect": cost_statistics,
                "smoothing_performed": False,
            }
            gates.append(
                _gate(
                    7,
                    "PASS",
                    [],
                    {
                        "statistics_sha256": fingerprint(statistics),
                        "student_t_95_eligible": True,
                        "aggregate_cell_count": 7,
                    },
                )
            )
        except (AcceptanceError, KeyError, TypeError, ValueError) as error:
            gates.append(
                _gate(
                    7,
                    "FAIL",
                    ["PAIRED_STATISTICS_OR_INDEPENDENCE_FAILED"],
                    {"detail": str(error)},
                )
            )
            first_failed = 7
    else:
        gates.append(_blocked_gate(7, first_failed))

    terminal = _terminal_class(
        disposition=str(disposition),
        first_failed_gate=first_failed,
        historical=entry.get("historical", False) is True,
        stale=entry.get("stale", False) is True,
        direct_class=None,
    )
    allowed_panels = ([*AUTHORIZED_FIGURE_5_PANELS, "FIGURE_6_A", "FIGURE_6_B", "FIGURE_6_D"]
                      if terminal == "VALID" else [])
    gates.append(
        _gate(
            8,
            "PASS",
            [],
            {
                "disposition": disposition,
                "terminal_class": terminal,
                "first_failed_gate": first_failed,
                "allowed_panel_ids": allowed_panels,
            },
        )
    )
    body: dict[str, Any] = {
        "attempt_id": attempt_id,
        "scenario": dict(scenario),
        "disposition": disposition,
        "artifact": artifact_evidence or None,
        "gates": gates,
        "terminal_class": terminal,
        "accepted_for_numerical_aggregates": terminal == "VALID",
        "allowed_panel_ids": allowed_panels,
        "statistics": statistics,
        "direct_classifier": None,
        "reason_codes": list(entry.get("reason_codes", [])),
    }
    return {**body, "fingerprint": fingerprint(body)}


def _attempt(root: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    attempt_id = entry.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise AcceptanceError("registry attempt_id must be a non-empty string")
    disposition = entry.get("disposition")
    if disposition not in DISPOSITIONS:
        raise AcceptanceError(f"attempt {attempt_id}: unsupported disposition")
    scenario = _mapping(entry.get("scenario"), f"attempt {attempt_id}.scenario")
    scenario_kind = scenario.get("kind")
    if scenario_kind not in {
        "NO_FAILURE",
        "PRIMARY_FAILURE",
        "RECOVERY_SELECTOR",
        "FAILURE_CAMPAIGN",
        "SENSITIVITY_SWEEP",
        "ABLATION_STUDY",
        "TIMING_ROBUSTNESS",
    }:
        raise AcceptanceError(f"attempt {attempt_id}: unsupported scenario kind")
    if scenario_kind == "FAILURE_CAMPAIGN":
        return _campaign_attempt(root, entry)
    if scenario_kind == "SENSITIVITY_SWEEP":
        return _paper_sweep_attempt(root, entry)
    if scenario_kind in {"ABLATION_STUDY", "TIMING_ROBUSTNESS"}:
        from moonkvsim.aegiskv.paper_study_acceptance import accept_study

        return accept_study(root, entry)

    gates: list[dict[str, Any]] = []
    artifact_evidence: dict[str, Any] = {}
    statistics: dict[str, Any] | None = None
    first_failed: int | None = None
    aggregate: Mapping[str, Any] | None = None
    aggregate_path: Path | None = None
    raw_documents: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    direct_classifier: Mapping[str, Any] | None = None
    direct_classifier_evidence: dict[str, Any] | None = None
    direct_classifier_checks: dict[str, Mapping[str, Any]] | None = None
    direct_class: str | None = None
    no_failure_attribution: list[dict[str, Any]] | None = None
    verification_root = root

    if disposition != "COMPLETED":
        code = {
            "MISSING": "ARTIFACT_MISSING",
            "FAILED": "PRODUCER_REPORTED_FAILED",
            "ABORTED": "ATTEMPT_ABORTED",
            "INFEASIBLE": "ATTEMPT_INFEASIBLE",
        }[str(disposition)]
        gates.append(_gate(1, "FAIL", [code], {"disposition": disposition}))
        first_failed = 1
    else:
        try:
            aggregate_path = repository_path(
                root, entry.get("artifact_path"), f"attempt {attempt_id}.artifact_path"
            )
            aggregate = _mapping(load_json_strict(aggregate_path), "aggregate")
            if aggregate.get("schema") != EXPECTED_AGGREGATE_SCHEMA:
                raise AcceptanceError("unsupported aggregate schema")
            if aggregate.get("status") != "PASS":
                raise AcceptanceError("aggregate status is not PASS")
            aggregate_fingerprint = _verify_self_fingerprint(aggregate, "aggregate")
            _validate_aggregate_schema(root, aggregate)
            raw_hashes: list[str] = []
            for cell_value in _sequence(aggregate.get("cells"), "aggregate.cells"):
                systems = _mapping(
                    _mapping(cell_value, "aggregate.cells[]").get("systems"), "cell.systems"
                )
                for system_id in SYSTEM_IDS:
                    system = _mapping(systems.get(system_id), f"cell.systems.{system_id}")
                    _, raw = _verify_raw(
                        aggregate_path,
                        system,
                        run_public_audits=False,
                    )
                    raw_documents.append((system, raw))
                    raw_hashes.append(
                        _sha256(
                            _mapping(system.get("raw_artifact"), "raw description").get("sha256"),
                            "raw sha256",
                        )
                    )
            artifact_evidence = {
                "path": str(entry.get("artifact_path")),
                "sha256": sha256_file(aggregate_path),
                "fingerprint": aggregate_fingerprint,
                "raw_artifact_count": len(raw_hashes),
                "raw_artifact_hashes": raw_hashes,
            }
            gates.append(_gate(1, "PASS", [], artifact_evidence))
        except AcceptanceError as error:
            gates.append(_gate(1, "FAIL", ["ARTIFACT_INTEGRITY_FAILED"], {"detail": str(error)}))
            first_failed = 1

    if first_failed is None:
        assert aggregate is not None
        try:
            verification_root = source_root_for_attempt(root, entry)
            binding_evidence = _verify_source_and_config(
                verification_root, _mapping(aggregate.get("provenance"), "aggregate.provenance")
            )
            binding_evidence["source_root"] = entry.get("source_root", ".")
            gates.append(_gate(2, "PASS", [], binding_evidence))
        except AcceptanceError as error:
            gates.append(
                _gate(2, "FAIL", ["SOURCE_OR_CONFIG_BINDING_FAILED"], {"detail": str(error)})
            )
            first_failed = 2
    else:
        gates.append(_blocked_gate(2, first_failed))

    if first_failed is None:
        assert aggregate is not None
        try:
            provenance = _mapping(aggregate.get("provenance"), "aggregate.provenance")
            workload = _mapping(provenance.get("workload_binding"), "workload_binding")
            workload_evidence = _load_workload(verification_root, workload)
            protocol = _mapping(aggregate.get("protocol"), "aggregate.protocol")
            if (
                protocol.get("workflow_count") != EXPECTED_WORKFLOW_COUNT
                or protocol.get("record_count") != EXPECTED_SPAN_COUNT
                or protocol.get("workflow_filtering", False) is not False
            ):
                raise AcceptanceError("aggregate workload protocol binding failed")
            gates.append(_gate(3, "PASS", [], workload_evidence))
        except AcceptanceError as error:
            gates.append(_gate(3, "FAIL", ["WORKLOAD_BINDING_FAILED"], {"detail": str(error)}))
            first_failed = 3
    else:
        gates.append(_blocked_gate(3, first_failed))

    if first_failed is None:
        if scenario_kind == "NO_FAILURE":
            assert aggregate is not None
            try:
                protocol = _mapping(aggregate.get("protocol"), "aggregate.protocol")
                if protocol.get("scenario") != "no_failure":
                    raise AcceptanceError("registry/aggregate scenario mismatch")
                for _, raw in raw_documents:
                    payload = _mapping(raw.get("payload"), "raw.payload")
                    metrics = _mapping(payload.get("metrics"), "raw.payload.metrics")
                    impact = _mapping(metrics.get("failure_impact"), "failure_impact")
                    if any(
                        impact.get(name) != 0
                        for name in (
                            "failure_event_count",
                            "active_requests",
                            "queued_requests",
                            "failed_gpu_count",
                        )
                    ):
                        raise AcceptanceError("no-failure artifact contains failure activity")
                gates.append(
                    _gate(
                        4,
                        "NOT_APPLICABLE",
                        ["NO_FAILURE_SCENARIO"],
                        {"verified_failure_event_count": 0},
                    )
                )
            except AcceptanceError as error:
                gates.append(
                    _gate(4, "FAIL", ["NO_FAILURE_ZERO_EVENT_CHECK_FAILED"], {"detail": str(error)})
                )
                first_failed = 4
        else:
            assert aggregate is not None
            try:
                aggregate_fingerprint = _sha256(
                    aggregate.get("fingerprint"), "aggregate fingerprint"
                )
                (
                    direct_classifier_evidence,
                    direct_classifier,
                    direct_classifier_checks,
                ) = _verify_direct_classifier(
                    root,
                    entry,
                    aggregate_fingerprint=aggregate_fingerprint,
                )
                causal_evidence = _verify_failure_causal_contract(
                    direct_classifier, direct_classifier_checks
                )
                gates.append(_gate(4, "PASS", [], causal_evidence))
            except AcceptanceError as error:
                gates.append(
                    _gate(
                        4,
                        "FAIL",
                        ["FAILURE_CAUSAL_CONTRACT_FAILED"],
                        {"detail": str(error), "scenario_kind": scenario_kind},
                    )
                )
                first_failed = 4
    else:
        gates.append(_blocked_gate(4, first_failed))

    if first_failed is None:
        try:
            audit_fingerprints: list[str] = []
            reconstructed_attribution: list[dict[str, Any]] = []
            for system, raw in raw_documents:
                reports, _ = _verify_raw(
                    aggregate_path if aggregate_path is not None else root,
                    system,
                    run_public_audits=True,
                )
                audit_fingerprints.extend(fingerprint(report) for report in reports.values())
                if scenario_kind == "NO_FAILURE":
                    reconstructed_attribution.append(
                        _reconstruct_no_failure_attribution(system, raw)
                    )
            if scenario_kind == "NO_FAILURE":
                no_failure_attribution = reconstructed_attribution
            gates.append(
                _gate(
                    5,
                    "PASS",
                    [],
                    {
                        "public_audit_count": len(audit_fingerprints),
                        "public_audit_fingerprints": audit_fingerprints,
                        "no_failure_attribution_count": len(reconstructed_attribution),
                        "no_failure_attribution_fingerprints": [
                            item["evidence_fingerprint"]
                            for item in reconstructed_attribution
                        ],
                        "diagnostic_non_additive": scenario_kind == "NO_FAILURE",
                        "modeled_uncalibrated": scenario_kind == "NO_FAILURE",
                    },
                )
            )
        except AcceptanceError as error:
            gates.append(_gate(5, "FAIL", ["FORMAL_AUDIT_FAILED"], {"detail": str(error)}))
            first_failed = 5
    else:
        gates.append(_blocked_gate(5, first_failed))

    if first_failed is None:
        if scenario_kind == "NO_FAILURE":
            gates.append(
                _gate(
                    6,
                    "NOT_APPLICABLE",
                    ["NO_FAILURE_SCENARIO"],
                    {"direct_classifier": None},
                )
            )
        else:
            assert direct_classifier is not None
            assert direct_classifier_evidence is not None
            try:
                classification_evidence = _verify_direct_classification(
                    direct_classifier
                )
                direct_class = str(classification_evidence["classification"])
                gates.append(
                    _gate(
                        6,
                        "PASS",
                        [],
                        {
                            **direct_classifier_evidence,
                            **classification_evidence,
                        },
                    )
                )
            except AcceptanceError as error:
                gates.append(
                    _gate(
                        6,
                        "FAIL",
                        ["DIRECT_CLASSIFICATION_FAILED"],
                        {
                            **direct_classifier_evidence,
                            "detail": str(error),
                        },
                    )
                )
                first_failed = 6
    else:
        gates.append(_blocked_gate(6, first_failed))

    if first_failed is None:
        assert aggregate is not None
        try:
            if scenario_kind == "NO_FAILURE":
                statistics = _recompute_no_failure_statistics(aggregate)
                assert no_failure_attribution is not None
                statistics["no_failure_attribution"] = no_failure_attribution
                statistics["attribution_declaration"] = {
                    "attribution_kind": "DIAGNOSTIC_NON_ADDITIVE",
                    "wct_sum_explanation_claimed": False,
                    "modeled_uncalibrated": True,
                    "physical_execution": False,
                }
                if not statistics["student_t_95_eligible"]:
                    raise AcceptanceError("deterministic repeats are not Student-t CI eligible")
            else:
                assert direct_classifier is not None
                statistics = _failure_pair_statistics(aggregate, direct_classifier)
            gates.append(
                _gate(
                    7,
                    "PASS",
                    [],
                    {
                        "statistics_sha256": fingerprint(statistics),
                        "student_t_95_eligible": statistics["student_t_95_eligible"],
                        "aggregate_mean_p95_panels_authorized": statistics.get(
                            "aggregate_mean_p95_panels_authorized",
                            True,
                        ),
                    },
                )
            )
        except AcceptanceError as error:
            evidence: dict[str, Any] = {"detail": str(error)}
            if statistics is not None:
                evidence["statistics_sha256"] = fingerprint(statistics)
            gates.append(
                _gate(7, "FAIL", ["PAIRED_STATISTICS_OR_INDEPENDENCE_FAILED"], evidence)
            )
            first_failed = 7
    else:
        gates.append(_blocked_gate(7, first_failed))

    historical = entry.get("historical", False) is True
    stale = entry.get("stale", False) is True
    terminal = _terminal_class(
        disposition=str(disposition),
        first_failed_gate=first_failed,
        historical=historical,
        stale=stale,
        direct_class=direct_class,
    )
    if scenario_kind == "NO_FAILURE":
        allowed_panels = list(AUTHORIZED_FIGURE_2_PANELS) if terminal == "VALID" else []
    elif terminal in {"VALID", "NULL_DIRECT", "MIXED_DIRECT", "ADVERSE_DIRECT"}:
        allowed_panels = list(AUTHORIZED_FAILURE_DIRECT_PANELS)
        if statistics is not None and statistics.get(
            "aggregate_mean_p95_panels_authorized"
        ) is True:
            allowed_panels.extend(AUTHORIZED_FAILURE_AGGREGATE_PANELS)
    else:
        allowed_panels = []
    gates.append(
        _gate(
            8,
            "PASS",
            [],
            {
                "disposition": disposition,
                "terminal_class": terminal,
                "first_failed_gate": first_failed,
                "allowed_panel_ids": allowed_panels,
            },
        )
    )
    if len(gates) != 8 or [gate["gate"] for gate in gates] != list(range(1, 9)):
        raise AssertionError("acceptance verifier did not materialize exactly gates 1..8")
    body: dict[str, Any] = {
        "attempt_id": attempt_id,
        "scenario": dict(scenario),
        "disposition": disposition,
        "artifact": artifact_evidence or None,
        "gates": gates,
        "terminal_class": terminal,
        "accepted_for_numerical_aggregates": terminal
        in {"VALID", "NULL_DIRECT", "MIXED_DIRECT", "ADVERSE_DIRECT"},
        "allowed_panel_ids": allowed_panels,
        "statistics": statistics,
        "direct_classifier": (
            None
            if direct_classifier is None or direct_classifier_evidence is None
            else {
                "artifact": direct_classifier_evidence,
                "output": dict(direct_classifier),
            }
        ),
        "reason_codes": list(entry.get("reason_codes", [])),
    }
    return {**body, "fingerprint": fingerprint(body)}


def load_registry(root: Path, registry_path: Path) -> Mapping[str, Any]:
    root = root.resolve()
    try:
        registry_path.resolve().relative_to(root)
    except ValueError as error:
        raise AcceptanceError("registry path must be inside the repository") from error
    relative = registry_path.resolve().relative_to(root).as_posix()
    safe_path = repository_path(root, relative, "registry path")
    registry = _mapping(load_json_strict(safe_path), "registry")
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise AcceptanceError("unsupported acceptance registry schema")
    _verify_self_fingerprint(registry, "registry")
    attempts = _sequence(registry.get("attempts"), "registry.attempts")
    ids = [entry.get("attempt_id") for entry in attempts if isinstance(entry, Mapping)]
    if len(ids) != len(set(ids)):
        raise AcceptanceError("registry contains duplicate attempt IDs")
    return registry


def build_manifest(root: Path, registry_path: Path) -> dict[str, Any]:
    """Build one canonical, self-fingerprinted acceptance manifest."""

    root = root.resolve()
    if _capture_verifier_files() != _VERIFIER_FILES:
        raise AcceptanceError("verifier source changed after import; run from a frozen tree")
    registry = load_registry(root, registry_path)
    attempts = [
        _attempt(root, _mapping(entry, "registry.attempts[]"))
        for entry in _sequence(registry.get("attempts"), "registry.attempts")
    ]
    body = {
        "schema": MANIFEST_SCHEMA,
        "status": "PASS",
        "registry": {
            "path": registry_path.resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(registry_path),
            "fingerprint": registry.get("fingerprint"),
        },
        "attempts": attempts,
        "summary": {
            terminal: sum(attempt["terminal_class"] == terminal for attempt in attempts)
            for terminal in sorted(TERMINAL_CLASSES)
        },
        "modeled_uncalibrated": True,
        "physical_execution": False,
        "paper_ready": False,
    }
    if _capture_verifier_files() != _VERIFIER_FILES:
        raise AcceptanceError("verifier source changed during acceptance; discard this audit")
    return {**body, "fingerprint": fingerprint(body)}


def validate_manifest(document: Mapping[str, Any], schema_path: Path) -> None:
    """Validate schema plus manifest and per-attempt self-fingerprints."""

    schema = _mapping(load_json_strict(schema_path), "acceptance manifest schema")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        raise AcceptanceError(f"acceptance manifest schema validation failed: {errors[0].message}")
    _verify_self_fingerprint(document, "acceptance manifest")
    for index, attempt in enumerate(_sequence(document.get("attempts"), "manifest.attempts")):
        _verify_self_fingerprint(_mapping(attempt, f"manifest.attempts[{index}]"), "attempt")
    # Walk all numbers to make the finite-number invariant explicit even for
    # programmatically constructed documents.
    def check_finite(value: Any, where: str) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise AcceptanceError(f"{where} contains a non-finite number")
        if isinstance(value, Mapping):
            for key, child in value.items():
                check_finite(child, f"{where}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                check_finite(child, f"{where}[{index}]")

    check_finite(document, "manifest")
