from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from moonkvsim.aegiskv import qwen3_8b_acceptance as acceptance
from moonkvsim.aegiskv import qwen3_8b_failure_campaign as campaign
from moonkvsim.aegiskv.qwen3_8b_acceptance import fingerprint, write_json_atomic
from moonkvsim.common.hash import sha256_json

ROOT = Path(__file__).resolve().parents[2]
CLASSIFIER = (
    ROOT
    / "benchmark/AegisKV/experiments/scripts/classify_qwen3_8b_direct_recovery.py"
)
FIGURES = (
    ROOT
    / "benchmark/AegisKV/experiments/results/figures/"
    "generate_qwen3_8b_failure_campaign_figures.py"
)
SCHEMA = ROOT / "schemas/aegiskv-qwen3-8b-failure-campaign.schema.json"
MOONCAKE, AEGISKV = campaign.SYSTEM_IDS


def _module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _signed(body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "fingerprint": fingerprint(body)}


def _schedule(focus: str, seed: int) -> dict[str, Any]:
    return {
        "type": "GPU_FAILURE",
        "failure_count": 1,
        "selection_scope": "fixture",
        "events": [
            {
                "failure_id": "failure-0",
                "event_index": 0,
                "type": "GPU_FAILURE",
                "bucket": "96k",
                "seed": seed,
                "focus_span_id": focus,
                "target_gpu_id": "gpu-3",
                "target_gpu_id_semantics": "FROZEN_PHYSICAL_FAILURE_TARGET",
                "impact_contract": None,
                "profile_impact_contracts": None,
                "workload_position": {
                    "kind": "COMPLETED_WORKFLOW_FRACTION_NEAREST_COMMON_ROUTE_SPAN",
                    "target_progress_per_mille": 600,
                    "reference_completed_workflow_count": 10,
                    "reference_workflow_count": 160,
                },
                "trigger": {
                    "kind": "FOCUS_SPAN_COMPUTE_PROGRESS",
                    "progress_per_mille": 500,
                },
                "reference_at_ns": 70,
                "reference_at_ns_semantics": "fixture",
                "detection_delay_ns": 1,
                "selection_scope": "fixture",
                "repair_after_ns": 1_000,
                "parameter_source": "fixture",
            }
        ],
    }


def _selector(focus: str, *, selected: str, recompute: int) -> dict[str, Any]:
    effective_prefix = 100 - recompute
    candidates = {
        "PEER_FIRST_CONTROL": {
            "feasible": True,
            "intervals": [
                {
                    "source": "NORMAL_HBM_LOCAL",
                    "start_token": 0,
                    "end_token": 10,
                    "token_count": 10,
                },
                {
                    "source": "PEER_HBM",
                    "start_token": 10,
                    "end_token": effective_prefix,
                    "token_count": effective_prefix - 10,
                },
            ],
            "transfers": [],
            "total_transferred_bytes": 700,
            "estimated_prefix_materialization_ns": 100,
            "estimated_scheduler_admission_ns": 110,
            "estimated_scheduler_completion_ns": 210,
            "selection_key": [0, 210, 110, 100, 700, 0],
        },
        "STORE_FIRST": {
            "feasible": True,
            "intervals": [
                {
                    "source": "NORMAL_HBM_LOCAL",
                    "start_token": 0,
                    "end_token": 10,
                    "token_count": 10,
                },
                {
                    "source": "STORE_DRAM",
                    "start_token": 10,
                    "end_token": effective_prefix,
                    "token_count": effective_prefix - 10,
                },
            ],
            "transfers": [],
            "total_transferred_bytes": 700,
            "estimated_prefix_materialization_ns": 80,
            "estimated_scheduler_admission_ns": 90,
            "estimated_scheduler_completion_ns": 190,
            "selection_key": [0, 190, 90, 80, 700, 1],
        },
    }
    if selected == "PEER_FIRST_CONTROL":
        candidates["STORE_FIRST"]["selection_key"] = [0, 210, 110, 100, 700, 1]
        candidates["STORE_FIRST"]["estimated_prefix_materialization_ns"] = 100
        candidates["STORE_FIRST"]["estimated_scheduler_admission_ns"] = 110
        candidates["STORE_FIRST"]["estimated_scheduler_completion_ns"] = 210
    chosen = candidates[selected]
    control = candidates["PEER_FIRST_CONTROL"]
    return {
        "timestamp_ns": 80,
        "event": "RECOVERY_SOURCE_SELECTION",
        "span_id": focus,
        "route_version": 1,
        "target_gpu_id": "gpu-4",
        "peer_source_gpu_id": "gpu-5",
        "selected_strategy": selected,
        "control_strategy": "PEER_FIRST_CONTROL",
        "effective_prefix_tokens": effective_prefix,
        "recompute_tokens": recompute,
        "candidate_order": ["PEER_FIRST_CONTROL", "STORE_FIRST"],
        "candidates": candidates,
        "prediction_scope": "snapshot_active_flows_plus_candidate_no_future_arrivals",
        "prediction_limitations": ["fixture"],
        "target_load_snapshot": {},
        "invariance_assertions": {
            "same_effective_prefix": True,
            "same_recompute_suffix": True,
            "same_target_gpu": True,
            "source_ownership_only": True,
            "candidate_evaluation_side_effect_free": True,
        },
        "selected_vs_control_deltas_ns": {
            "scheduler_completion": (
                chosen["estimated_scheduler_completion_ns"]
                - control["estimated_scheduler_completion_ns"]
            ),
            "scheduler_admission": (
                chosen["estimated_scheduler_admission_ns"]
                - control["estimated_scheduler_admission_ns"]
            ),
            "prefix_materialization": (
                chosen["estimated_prefix_materialization_ns"]
                - control["estimated_prefix_materialization_ns"]
            ),
        },
        "selected_vs_control_transferred_bytes_delta": 0,
    }


def _run(
    *,
    system_id: str,
    seed: int,
    focus: str,
    wct_offset: int,
    recompute: int,
    ready_ns: int,
    selected: str,
) -> dict[str, Any]:
    schedule = _schedule(focus, seed)
    workflow_ids = [f"workflow-{index:03d}" for index in range(160)]
    order = workflow_ids[seed:] + workflow_ids[:seed]
    source_tokens = {
        "NORMAL_HBM_LOCAL": 10,
        "PEER_HBM": 0 if system_id == MOONCAKE else 30,
        "STORE_DRAM": 100 - recompute - 10 - (0 if system_id == MOONCAKE else 30),
        "RECOMPUTE": recompute,
    }
    return {
        "system_id": system_id,
        "scenario": "gpu_failure",
        "input_binding_fingerprint": f"{system_id}-{seed}",
        "variant_fingerprint": f"{system_id}-fixed",
        "failure_schedule": schedule,
        "failure_schedule_fingerprint": sha256_json(schedule),
        "payload": {
            "schema": "payload.fixture.v1",
            "scenario": "gpu_failure",
            "variant_id": system_id,
            "workload": {"workflow_count": 160},
            "workflow_admission": {
                "mode": "closed_loop_workflow_concurrency",
                "workflow_concurrency": 16,
                "order_policy": (
                    "observed_submit_then_seeded_sha256_workflow_permutation"
                ),
                "seed": seed,
                "realized_workflow_order": order,
                "realized_workflow_order_sha256": fingerprint(order),
            },
            "metrics": {
                "workflow_completion_time_ns": {
                    "by_workflow_id": {
                        workflow_id: 1_000_000_000 + index * 1_000_000 + wct_offset
                        for index, workflow_id in enumerate(workflow_ids)
                    }
                }
            },
        },
        "full_payload_sha256": "1" * 64,
        "compact_payload_sha256": "2" * 64,
        "payload_omitted_fields": [],
        "journal_sha256": f"{seed + 3:064x}",
        "span_details": [
            {
                "span_id": focus,
                "prompt_tokens": 100,
                "completed_ns": 20_000_000_000 + wct_offset,
                "restored_peer_local_tokens": source_tokens["PEER_HBM"] // 2,
                "restored_peer_d2d_tokens": source_tokens["PEER_HBM"]
                - source_tokens["PEER_HBM"] // 2,
            }
        ],
        "span_details_sha256": "4" * 64,
        "representative": {
            "failure_events": [
                {
                    "timestamp_ns": 80,
                    "event": "FAILURE_INJECT",
                    "target_gpu_id": "gpu-3",
                    "impacted_active_span_ids": [focus],
                    "impacted_queued_span_ids": [],
                    "reroute_only_queued_span_ids": [],
                    "logical_trigger": {
                        "focus_span_id": focus,
                        "progress_per_mille": 500,
                        "resolved_target_gpu_id": "gpu-3",
                    },
                }
            ],
            "recovery_events": [
                _selector(focus, selected=selected, recompute=recompute),
                {
                    "event": "RECOVERY_PLAN",
                    "span_id": focus,
                    "prompt_tokens": 100,
                    "effective_prefix_tokens": 100 - recompute,
                    "source_tokens": source_tokens,
                },
                {
                    "event": "CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED",
                    "span_id": focus,
                    "timestamp_ns": 100,
                },
                {
                    "event": "PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
                    "span_id": focus,
                    "timestamp_ns": ready_ns,
                },
            ],
        },
    }


def _artifact(
    seed: int,
    *,
    moon_offset: int = 0,
    aegis_offset: int = -10_000_000,
    moon_recompute: int = 50,
    aegis_recompute: int = 20,
    moon_ready: int = 150,
    aegis_ready: int = 120,
    selected: str = "STORE_FIRST",
) -> dict[str, Any]:
    focus = "workflow-000:span-000"
    body = {
        "schema": campaign.EXPECTED_POSTFIX_SCHEMA,
        "status": "PASS",
        "evidence": {
            "class": "E2",
            "physical_execution": False,
            "calibrated": False,
            "paper_ready": False,
            "modeled_uncalibrated": True,
        },
        "protocol": {
            "model": "Qwen/Qwen3-8B",
            "dp": 8,
            "tp": 1,
            "pp": 1,
            "seed": seed,
            "workflow_admission_seed": seed,
            "peer_binding_seed": 0,
            "paper_causal_mode": True,
            "workflow_count": 160,
            "source_workflow_count": 160,
            "workflow_filtering": False,
            "workflow_concurrency": 16,
            "failure_progress_per_mille": 600,
            "failure_count": 1,
            "focus_span_ids": [focus],
        },
        "source": {
            "implementation_fingerprint": "a" * 64,
            "implementation_paths": ["fixture.py"],
            "workload": {
                "declared_path": "workload.jsonl",
                "sha256": "b" * 64,
                "record_count": 1304,
            },
            "selection": {
                "kind": "complete_frozen_workload_no_filtering",
                "selected_workflow_ids": [
                    f"workflow-{index:03d}" for index in range(160)
                ],
            },
        },
        "runs": {
            "no_failure": {
                MOONCAKE: _run(
                    system_id=MOONCAKE,
                    seed=seed,
                    focus=focus,
                    wct_offset=0,
                    recompute=moon_recompute,
                    ready_ns=moon_ready,
                    selected="PEER_FIRST_CONTROL",
                ),
                AEGISKV: _run(
                    system_id=AEGISKV,
                    seed=seed,
                    focus=focus,
                    wct_offset=0,
                    recompute=aegis_recompute,
                    ready_ns=aegis_ready,
                    selected=selected,
                ),
            },
            "gpu_failure": {
                MOONCAKE: _run(
                    system_id=MOONCAKE,
                    seed=seed,
                    focus=focus,
                    wct_offset=moon_offset,
                    recompute=moon_recompute,
                    ready_ns=moon_ready,
                    selected="PEER_FIRST_CONTROL",
                ),
                AEGISKV: _run(
                    system_id=AEGISKV,
                    seed=seed,
                    focus=focus,
                    wct_offset=aegis_offset,
                    recompute=aegis_recompute,
                    ready_ns=aegis_ready,
                    selected=selected,
                ),
            }
        },
    }
    return {**body, "fingerprint": fingerprint(body)}


def _build_fixture(
    tmp_path: Path,
    *,
    mutations: dict[int, Any] | None = None,
    classifier_source: Path = CLASSIFIER,
) -> dict[str, Any]:
    artifacts = []
    classifiers = []
    for seed in range(5):
        artifact = _artifact(seed)
        if mutations and seed in mutations:
            artifact = mutations[seed](artifact)
        artifact_path = tmp_path / f"seed{seed}.json"
        write_json_atomic(artifact_path, artifact)
        artifacts.append(artifact_path)
        classifiers.append(tmp_path / f"seed{seed}.direct.json")
    return campaign.build_campaign(
        artifact_paths=artifacts,
        classifier_paths=classifiers,
        classifier_source=classifier_source,
    )


def _resign(value: dict[str, Any]) -> dict[str, Any]:
    body = deepcopy(value)
    body.pop("fingerprint", None)
    return _signed(body)


def test_campaign_retains_all_seeds_and_builds_seed_level_t_ci(tmp_path: Path) -> None:
    document = _build_fixture(tmp_path)

    assert document["seed_count"] == 5
    assert document["focus_span_ids_by_seed"] == {
        str(seed): "workflow-000:span-000" for seed in range(5)
    }
    assert [row["seed"] for row in document["seeds"]] == list(range(5))
    assert document["inference"]["student_t_95"]["focus_failure_penalty_did"]["n"] == 5
    assert document["inference"]["student_t_95"]["focus_failure_penalty_did"][
        "degrees_of_freedom"
    ] == 4
    assert document["inference"][
        "workflow_observations_are_descriptive_not_inferential"
    ] is True
    assert "FIGURE_4_A" not in document["acceptance"]["allowed_panel_ids"]
    campaign.validate_campaign(document, SCHEMA)


def test_campaign_allows_seed_specific_focus_identity(tmp_path: Path) -> None:
    def change_focus(seed: int, artifact: dict[str, Any]) -> dict[str, Any]:
        old_focus = artifact["protocol"]["focus_span_ids"][0]
        new_focus = f"workflow-{seed:03d}:span-000"

        def replace(value: Any) -> Any:
            if isinstance(value, dict):
                for key, item in value.items():
                    value[key] = replace(item)
            elif isinstance(value, list):
                return [replace(item) for item in value]
            elif value == old_focus:
                return new_focus
            return value

        replace(artifact)
        artifact["protocol"]["focus_span_ids"] = [new_focus]
        for run in artifact["runs"]["gpu_failure"].values():
            run["failure_schedule_fingerprint"] = fingerprint(
                run["failure_schedule"]
            )
        return _resign(artifact)

    document = _build_fixture(
        tmp_path,
        mutations={
            seed: lambda item, seed=seed: change_focus(seed, item)
            for seed in range(5)
        },
    )

    assert document["focus_span_ids_by_seed"] == {
        str(seed): f"workflow-{seed:03d}:span-000" for seed in range(5)
    }


def test_figure_cohorts_map_fanoutqa_span_to_workflow_identity() -> None:
    generator = _module(FIGURES, "qwen3_8b_campaign_figures_fanoutqa")
    workflow_id = "cc4e6774f97b0101"
    span_id = f"fanoutqa:{workflow_id}:f21737f38efd89e8"
    row = {
        "causal_contract": {
            "focus_span_id": span_id,
            "realized_outcomes_by_system": {
                system_id: {
                    "active_span_ids": [span_id],
                    "queued_span_ids": [],
                }
                for system_id in (MOONCAKE, AEGISKV)
            },
        },
        "workflow_wct_ns": {
            MOONCAKE: {workflow_id: 100},
            AEGISKV: {workflow_id: 90},
        },
    }

    cohorts = generator._cohort_ids(row)

    assert cohorts["focus"] == {workflow_id}
    assert cohorts["impacted_union"] == {workflow_id}


def test_campaign_retains_mixed_null_and_adverse_classes(tmp_path: Path) -> None:
    def mutate(seed: int, artifact: dict[str, Any]) -> dict[str, Any]:
        if seed == 1:
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][1]["source_tokens"]["RECOMPUTE"] = 30
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][1]["source_tokens"]["STORE_DRAM"] = 30
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][1]["effective_prefix_tokens"] = 70
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][3]["timestamp_ns"] = 170
        elif seed == 2:
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][1]["source_tokens"]["RECOMPUTE"] = 50
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][1]["source_tokens"]["STORE_DRAM"] = 10
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][1]["effective_prefix_tokens"] = 50
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][3]["timestamp_ns"] = 150
        elif seed == 3:
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][1]["source_tokens"]["RECOMPUTE"] = 60
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][1]["source_tokens"]["STORE_DRAM"] = 0
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][1]["effective_prefix_tokens"] = 40
            artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
                "recovery_events"
            ][3]["timestamp_ns"] = 170
        return _resign(artifact)

    document = _build_fixture(
        tmp_path,
        mutations={seed: lambda item, seed=seed: mutate(seed, item) for seed in (1, 2, 3)},
    )

    classes = [row["direct_class"] for row in document["seeds"]]
    assert classes == [
        "DIRECT_RECOVERY_BENEFIT_CONCORDANT",
        "DIRECT_RECOVERY_MIXED",
        "SOURCE_SUBSTITUTION_OR_NULL_DIRECT_MECHANISM",
        "ADVERSE_DIRECT_MECHANISM",
        "DIRECT_RECOVERY_BENEFIT_CONCORDANT",
    ]


def test_campaign_fails_closed_on_missing_seed(tmp_path: Path) -> None:
    artifacts = []
    classifiers = []
    for seed in range(4):
        path = tmp_path / f"seed{seed}.json"
        write_json_atomic(path, _artifact(seed))
        artifacts.append(path)
        classifiers.append(tmp_path / f"seed{seed}.direct.json")
    artifacts.append(tmp_path / "seed4.json")
    classifiers.append(tmp_path / "seed4.direct.json")
    with pytest.raises(campaign.AcceptanceError, match="missing required seed 4"):
        campaign.build_campaign(
            artifact_paths=artifacts,
            classifier_paths=classifiers,
            classifier_source=CLASSIFIER,
        )


def test_campaign_fails_closed_on_binding_drift(tmp_path: Path) -> None:
    def drift(artifact: dict[str, Any]) -> dict[str, Any]:
        artifact["source"]["implementation_fingerprint"] = "c" * 64
        return _resign(artifact)

    with pytest.raises(campaign.AcceptanceError, match="binding differs"):
        _build_fixture(tmp_path, mutations={4: drift})


def test_campaign_rejects_duplicate_admission_orders(tmp_path: Path) -> None:
    def duplicate(artifact: dict[str, Any]) -> dict[str, Any]:
        for run in artifact["runs"]["gpu_failure"].values():
            admission = run["payload"]["workflow_admission"]
            order = sorted(admission["realized_workflow_order"])
            admission["realized_workflow_order"] = order
            admission["realized_workflow_order_sha256"] = fingerprint(order)
        return _resign(artifact)

    with pytest.raises(campaign.AcceptanceError, match="duplicate admission order"):
        _build_fixture(
            tmp_path,
            mutations={seed: duplicate for seed in range(5)},
        )


def test_campaign_rejects_missing_selector_evidence(tmp_path: Path) -> None:
    def remove(artifact: dict[str, Any]) -> dict[str, Any]:
        events = artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
            "recovery_events"
        ]
        artifact["runs"]["gpu_failure"][AEGISKV]["representative"][
            "recovery_events"
        ] = [event for event in events if event["event"] != "RECOVERY_SOURCE_SELECTION"]
        return _resign(artifact)

    with pytest.raises(campaign.AcceptanceError, match="RECOVERY_SOURCE_SELECTION"):
        _build_fixture(tmp_path, mutations={2: remove})


def test_campaign_accepts_post_treatment_timestamp_divergence(tmp_path: Path) -> None:
    def diverge(artifact: dict[str, Any]) -> dict[str, Any]:
        artifact["runs"]["gpu_failure"][AEGISKV]["representative"]["failure_events"][0][
            "timestamp_ns"
        ] += 1
        return _resign(artifact)

    document = _build_fixture(tmp_path, mutations={1: diverge})

    seed = document["seeds"][1]
    outcomes = seed["causal_contract"]["realized_outcomes_by_system"]
    assert outcomes[MOONCAKE]["injection_timestamp_ns"] != outcomes[AEGISKV][
        "injection_timestamp_ns"
    ]


def test_figure_generator_requires_authorized_panels_and_hashes_outputs(
    tmp_path: Path,
) -> None:
    classifier_source = tmp_path / "classify.py"
    classifier_source.write_bytes(CLASSIFIER.read_bytes())
    document = _build_fixture(
        tmp_path / "campaign-input", classifier_source=classifier_source
    )
    campaign_path = tmp_path / "campaign.json"
    write_json_atomic(campaign_path, document)
    registry_body = {
        "schema": acceptance.REGISTRY_SCHEMA,
        "attempts": [
            {
                "attempt_id": "failure-campaign",
                "disposition": "COMPLETED",
                "scenario": {"kind": "FAILURE_CAMPAIGN"},
                "artifact_path": campaign_path.relative_to(tmp_path).as_posix(),
            }
        ],
    }
    registry = {**registry_body, "fingerprint": fingerprint(registry_body)}
    registry_path = tmp_path / "registry.json"
    write_json_atomic(registry_path, registry)
    accepted = acceptance.build_manifest(tmp_path, registry_path)
    acceptance_path = tmp_path / "acceptance.json"
    write_json_atomic(acceptance_path, accepted)
    generator = _module(FIGURES, "qwen3_8b_campaign_figures")
    output = tmp_path / "figures"

    manifest = generator.generate(
        document,
        campaign_path=campaign_path,
        acceptance_manifest_path=acceptance_path,
        output_dir=output,
    )

    attempt = accepted["attempts"][0]
    assert attempt["terminal_class"] == "VALID"
    assert [gate["status"] for gate in attempt["gates"]] == ["PASS"] * 8
    assert attempt["statistics"]["seed_count"] == 5
    assert "FIGURE_4_A" not in attempt["allowed_panel_ids"]
    assert manifest["figure_count"] == len(attempt["allowed_panel_ids"])
    for figure in manifest["figures"]:
        assert {item["format"] for item in figure["outputs"]} == {"PNG", "SVG", "PDF"}
        for item in figure["outputs"]:
            path = output / item["file"]
            assert path.is_file()
            import hashlib

            assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    stored = json.loads((output / "FIGURE_MANIFEST.json").read_text(encoding="utf-8"))
    assert stored["fingerprint"] == fingerprint(
        {key: value for key, value in stored.items() if key != "fingerprint"}
    )

    with pytest.raises(ValueError, match="unauthorized"):
        generator.generate(
            document,
            campaign_path=campaign_path,
            acceptance_manifest_path=acceptance_path,
            output_dir=tmp_path / "unauthorized",
            requested_panels=["FIGURE_4_A"],
        )

    tampered = deepcopy(accepted)
    tampered["attempts"][0]["artifact"]["sha256"] = "0" * 64
    tampered_attempt = tampered["attempts"][0]
    tampered_attempt["fingerprint"] = fingerprint(
        {key: value for key, value in tampered_attempt.items() if key != "fingerprint"}
    )
    tampered["fingerprint"] = fingerprint(
        {key: value for key, value in tampered.items() if key != "fingerprint"}
    )
    tampered_path = tmp_path / "tampered-acceptance.json"
    write_json_atomic(tampered_path, tampered)
    with pytest.raises(ValueError, match="exactly one campaign"):
        generator.generate(
            document,
            campaign_path=campaign_path,
            acceptance_manifest_path=tampered_path,
            output_dir=tmp_path / "tampered",
        )


def test_single_seed_t_interval_is_descriptive_only() -> None:
    interval = campaign._t_interval([10])

    assert interval["eligible"] is False
    assert interval["n"] == 1
    assert interval["low"] is None
    assert interval["limitation"] == "AT_LEAST_TWO_INDEPENDENT_SEEDS_REQUIRED"
