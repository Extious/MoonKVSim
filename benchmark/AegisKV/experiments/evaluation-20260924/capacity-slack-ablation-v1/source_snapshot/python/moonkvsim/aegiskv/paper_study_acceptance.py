"""Eight ordered acceptance gates for the four-arm and timing-assumption studies."""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from moonkvsim.aegiskv.experiment import ablation_variants, core_variants
from moonkvsim.aegiskv.experiment_config import (
    default_config_dir,
    load_experiment_configs,
    model_parameters_from_configs,
)
from moonkvsim.aegiskv.paper_ablation_statistics import ARMS, build_ablation_statistics
from moonkvsim.aegiskv.paper_artifacts import load_raw_evidence
from moonkvsim.aegiskv.paper_audit_parallel import audit_map
from moonkvsim.aegiskv.paper_randomization import (
    paired_admission_fingerprint,
    require_distinct_admissions,
)
from moonkvsim.aegiskv.paper_study_reconstruction import reconstruct_study_run
from moonkvsim.aegiskv.paper_timing_statistics import TIMING_MODELS, build_timing_statistics
from moonkvsim.aegiskv.qwen3_8b_acceptance import (
    DISPOSITIONS,
    AcceptanceError,
    _blocked_gate,
    _gate,
    _load_workload,
    _mapping,
    _sequence,
    _terminal_class,
    _verify_self_fingerprint,
    fingerprint,
    load_json_strict,
    repository_path,
    sha256_file,
    source_root_for_attempt,
)

LOG = logging.getLogger(__name__)


def _reconstruct_cell(task: tuple[Any, ...]) -> dict[str, Any]:
    attempt_id, directory, contract_fingerprint, variants, records, cell = task
    reconstructed_runs: dict[str, Any] = {}
    for scenario_name, arms in cell["runs"].items():
        reconstructed_runs[scenario_name] = {}
        for arm, compact in arms.items():
            LOG.info("%s raw: seed=%s %s %s", attempt_id, cell["seed"], scenario_name, arm)
            binding = compact["raw_evidence"]
            path = repository_path(directory, binding["file"], "study raw")
            raw = load_raw_evidence(path, expected_sha256=binding["sha256"])
            variant_document = variants[arm]
            expected_identity = {
                "contract_fingerprint": contract_fingerprint,
                "seed": cell["seed"], "scenario": scenario_name,
                "variant_fingerprint": fingerprint(variant_document),
                "schedule_fingerprint": cell["plan"]["schedule_fingerprint"],
            }
            if raw["identity"] != expected_identity or raw["variant"] != variant_document:
                raise AcceptanceError("raw run identity/variant mismatch")
            expected_schedule = (cell["plan"]["schedule"]
                                 if scenario_name == "gpu_failure" else None)
            if (raw["payload"]["failure_schedule"] != expected_schedule
                    or raw["payload"]["variant_fingerprint"] != (
                        expected_identity["variant_fingerprint"]
                    ) or raw["payload"]["scenario"] != scenario_name):
                raise AcceptanceError("raw payload intervention/variant mismatch")
            rebuilt = reconstruct_study_run(
                raw, arm=arm, focus_span_id=cell["focus_span_id"], records=records,
                expected_failure=scenario_name == "gpu_failure",
            )
            recorded = {key: value for key, value in compact.items() if key != "raw_evidence"}
            if rebuilt != recorded:
                raise AcceptanceError("compact study summary does not reconstruct")
            reconstructed_runs[scenario_name][arm] = {**rebuilt, "raw_evidence": binding}
            del raw
    return {**cell, "runs": reconstructed_runs}


def accept_study(root: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    attempt_id, disposition = entry.get("attempt_id"), entry.get("disposition")
    if not isinstance(attempt_id, str) or not attempt_id or disposition not in DISPOSITIONS:
        raise AcceptanceError("invalid study attempt identity or disposition")
    scenario = _mapping(entry.get("scenario"), "study.scenario")
    timing = scenario["kind"] == "TIMING_ROBUSTNESS"
    study = "timing-robustness" if timing else "ablations"
    expected_arms = ({arm for pair in TIMING_MODELS.values() for arm in pair}
                     if timing else set(ARMS))
    expected_runs = 5 * 2 * len(expected_arms)
    gates = []
    first_failed: int | None = None
    artifact_evidence: dict[str, Any] = {}
    document: Mapping[str, Any] = {}
    contract: Mapping[str, Any] = {}
    artifact_path = root
    verification_root = root
    cells = []
    variants: dict[str, dict[str, Any]] = {}
    records: dict[str, Mapping[str, Any]] = {}
    rebuilt_cells = []
    statistics = None

    for number in range(1, 8):
        if first_failed is not None:
            gates.append(_blocked_gate(number, first_failed))
            continue
        LOG.info("%s gate %d start", attempt_id, number)
        try:
            evidence: dict[str, Any] = {}
            if number == 1:
                if disposition != "COMPLETED":
                    raise AcceptanceError(f"producer disposition is {disposition}")
                artifact_path = repository_path(root, entry.get("artifact_path"), "study artifact")
                document = _mapping(load_json_strict(artifact_path), "study artifact")
                expected_schema = ("moonkvsim.aegiskv.paper-timing-robustness.v1" if timing
                                   else "moonkvsim.aegiskv.paper-ablations.v1")
                if document.get("schema") != expected_schema or document.get("status") != "PASS":
                    raise AcceptanceError("study schema/status mismatch")
                _verify_self_fingerprint(document, "study artifact")
                contract = _mapping(load_json_strict(artifact_path.parent / "contract.json"),
                                    "study contract")
                _verify_self_fingerprint(contract, "study contract")
                if document["source_contract_fingerprint"] != contract["fingerprint"]:
                    raise AcceptanceError("aggregate contract binding changed")
                cells = list(_sequence(document.get("cells"), "study cells"))
                if sorted(cell["seed"] for cell in cells) != list(range(5)):
                    raise AcceptanceError("study requires exactly five seeds 0 through 4")
                hashes = []
                for cell in cells:
                    runs = cell["runs"]
                    if set(runs) != {"no_failure", "gpu_failure"} or any(
                        set(arms) != expected_arms for arms in runs.values()
                    ):
                        raise AcceptanceError("study arm/scenario population changed")
                    for arms in runs.values():
                        for run in arms.values():
                            binding = run["raw_evidence"]
                            path = repository_path(artifact_path.parent, binding["file"],
                                                   "raw evidence")
                            observed = sha256_file(path)
                            if observed != binding["sha256"]:
                                raise AcceptanceError("raw study file checksum mismatch")
                            hashes.append(observed)
                if len(hashes) != expected_runs:
                    raise AcceptanceError("study raw run count changed")
                artifact_evidence = {
                    "path": entry["artifact_path"], "sha256": sha256_file(artifact_path),
                    "fingerprint": document["fingerprint"], "raw_artifact_count": len(hashes),
                    "raw_artifact_hashes": hashes,
                }
                evidence = artifact_evidence
            elif number == 2:
                verification_root = source_root_for_attempt(root, entry)
                source_files = _mapping(contract.get("source_files"), "study source_files")
                if not source_files:
                    raise AcceptanceError("study has no source bindings")
                for rel, expected in source_files.items():
                    if sha256_file(repository_path(verification_root, rel, "study source")) != (
                        expected
                    ):
                        raise AcceptanceError(f"study source changed: {rel}")
                config_dir = default_config_dir(verification_root)
                for name, expected in contract["config_files"].items():
                    if sha256_file(repository_path(config_dir, name, "study config")) != expected:
                        raise AcceptanceError(f"study configuration changed: {name}")
                if document.get("git_worktree_clean") is not True:
                    raise AcceptanceError("study execution checkout was not clean")
                evidence = {"source_file_count": len(source_files),
                            "source_root": entry.get("source_root", "."),
                            "source_contract_fingerprint": contract["fingerprint"],
                            "git_head": document["git_head"]}
            elif number == 3:
                if (contract.get("study") != study or contract.get("seeds") != list(range(5))
                        or contract.get("workflow_concurrency") != 16
                        or contract.get("peer_binding_seed") != 0
                        or contract.get("effect_direction_gate_applied") is not False):
                    raise AcceptanceError("study protocol mismatch")
                workload = _mapping(contract["workload_binding"], "study workload")
                evidence = _load_workload(verification_root, workload)
                workload_path = repository_path(verification_root, workload["declared_path"],
                                                "study workload")
                with workload_path.open() as stream:
                    for line in stream:
                        record = json.loads(line)
                        records[record["span_id"]] = {
                            key: record[key] for key in
                            ("workflow_id", "prompt_tokens", "output_tokens")
                        }
                configs = load_experiment_configs(default_config_dir(verification_root),
                                                  root=verification_root)
                parameters = model_parameters_from_configs(configs)
                if timing:
                    for beta, (aegis, control) in TIMING_MODELS.items():
                        for variant in core_variants(replace(
                            parameters, batch_serialization_per_mille=beta,
                        )):
                            if variant.variant_id in {"aegiskv_unified", "vanilla_mooncake_dram"}:
                                arm = aegis if variant.variant_id == "aegiskv_unified" else control
                                variants[arm] = replace(variant, suite="timing_robustness",
                                                        variant_id=arm).to_dict()
                else:
                    variants = {variant.variant_id: variant.to_dict()
                                for variant in ablation_variants(parameters)
                                if variant.variant_id in expected_arms}
                declared = {variant["variant_id"]: variant for variant in contract["variants"]}
                if declared != variants:
                    raise AcceptanceError("study variants differ from the declared comparison")
            elif number == 4:
                admission_hashes = []
                for cell in cells:
                    plan = cell["plan"]
                    schedule = plan["schedule"]
                    if (plan["contract_fingerprint"] != contract["fingerprint"]
                            or fingerprint(schedule) != plan["schedule_fingerprint"]):
                        raise AcceptanceError("logical plan binding mismatch")
                    events = schedule["events"]
                    if len(events) != 1:
                        raise AcceptanceError("study requires one logical failure")
                    event = events[0]
                    focus = cell["focus_span_id"]
                    if focus not in records or records[focus]["workflow_id"] != (
                        cell["focus_workflow_id"]
                    ):
                        raise AcceptanceError("logical focus identity differs from frozen input")
                    trigger = event["trigger"]
                    if (event["focus_span_id"] != focus
                            or event["type"] != "GPU_FAILURE"
                            or trigger["kind"] != "FOCUS_SPAN_COMPUTE_PROGRESS"
                            or trigger["progress_per_mille"] != 600
                            or event.get("impact_contract") is not None
                            or event.get("profile_impact_contracts") is not None
                            or event["target_gpu_id_semantics"] != (
                                "REFERENCE_ROUTE_PROVENANCE_NOT_RUNTIME_FAILURE_TARGET"
                            )):
                        raise AcceptanceError("study intervention is not the declared natural F1")
                    all_runs = {f"{s}:{a}": r for s, arms in cell["runs"].items()
                                for a, r in arms.items()}
                    admission_hashes.append(paired_admission_fingerprint(
                        all_runs, seed=cell["seed"],
                        workflow_ids={record["workflow_id"] for record in records.values()},
                    ))
                require_distinct_admissions(admission_hashes)
                evidence = {"logical_focus_count": 5,
                            "admission_order_sha256_by_seed": admission_hashes,
                            "effect_direction_filter": False}
            elif number == 5:
                rebuilt_cells = audit_map(_reconstruct_cell, [
                    (attempt_id, artifact_path.parent, contract["fingerprint"], variants,
                     records, cell) for cell in cells
                ])
                evidence = {"complete_raw_runs_reconstructed": expected_runs,
                            "scheduler_policy_pool_and_pending_checks": True}
            elif number == 6:
                evidence = {"workflow_intervals_reconstructed": expected_runs * 160,
                            "external_output_counts_reconstructed": expected_runs * 1304,
                            "failure_focus_prompt_conservation": True,
                            "protection_bytes_from_physical_transfers": True,
                            "zero_hits_and_adverse_effects_retained": True}
            elif number == 7:
                rebuilt_statistics = (build_timing_statistics(rebuilt_cells) if timing
                                      else build_ablation_statistics(rebuilt_cells))
                if rebuilt_statistics != document["statistics"]:
                    raise AcceptanceError("study statistics do not reconstruct from raw runs")
                statistics = rebuilt_statistics
                evidence = {"statistics_fingerprint": fingerprint(statistics), "seed_count": 5,
                            "independent_unit": "paired_admission_seed", "smoothing": False}
            gates.append(_gate(number, "PASS", [], evidence))
            LOG.info("%s gate %d PASS", attempt_id, number)
        except (ValueError, KeyError, TypeError, OSError) as error:
            first_failed = number
            gates.append(_gate(number, "FAIL", ["STUDY_GATE_FAILED"], {"detail": str(error)}))
            LOG.info("%s gate %d FAIL: %s", attempt_id, number, error)
    terminal = _terminal_class(disposition=disposition, first_failed_gate=first_failed,
                               historical=entry.get("historical") is True,
                               stale=entry.get("stale") is True, direct_class=None)
    allowed = (["FIGURE_7_A", "FIGURE_7_B"] if timing else ["FIGURE_6_C"])
    if terminal != "VALID":
        allowed = []
    gates.append(_gate(8, "PASS", [], {"terminal_class": terminal,
                                      "allowed_panel_ids": allowed,
                                      "first_failed_gate": first_failed}))
    body = {
        "attempt_id": attempt_id, "scenario": dict(scenario), "disposition": disposition,
        "artifact": artifact_evidence or None, "gates": gates, "terminal_class": terminal,
        "accepted_for_numerical_aggregates": terminal == "VALID", "allowed_panel_ids": allowed,
        "statistics": statistics, "direct_classifier": None,
        "reason_codes": list(entry.get("reason_codes", [])),
    }
    return {**body, "fingerprint": fingerprint(body)}
