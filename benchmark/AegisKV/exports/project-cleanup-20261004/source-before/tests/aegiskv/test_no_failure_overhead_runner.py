from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from moonkvsim.aegiskv.experiment import StudyRunResult, core_variants

_ROOT = Path(__file__).resolve().parents[2]
_RUNNER_PATH = _ROOT / "benchmark/AegisKV/experiments/scripts/run_aegiskv_no_failure_overhead.py"
_SCHEMA_PATH = _ROOT / "schemas/aegiskv-no-failure-overhead.schema.json"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_test_no_failure_overhead_runner", _RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _workflow_ids() -> list[str]:
    return [f"workflow-{index:03d}" for index in range(160)]


def _warmup(workflow_ids: list[str]) -> dict[str, Any]:
    return {
        "bootstrap_workflow_ids": workflow_ids[:16],
        "bootstrap_workflow_count": 16,
        "steady_state_workflow_count": 144,
        "warmup_start_ns": 0,
        "warmup_end_ns": 16,
        "definition": "test definition",
        "warmup_exclusion_applied_to_primary_metrics": False,
    }


def _protection() -> dict[str, Any]:
    return {
        "protection_causes": [
            "AEGIS_PEER_HBM_PROTECTION",
            "AEGIS_STORE_DRAM_PROTECTION",
        ],
        "transfer_count": 0,
        "terminal_state_counts": {},
        "submitted_bytes": 0,
        "transferred_bytes": 0,
        "aborted_bytes": 0,
        "queue_wait_ns_sum": 0,
        "service_time_ns_sum": 0,
        "copy_engine_busy_ns_sum": 0,
        "fabric_busy_ns_sum": 0,
        "by_time_phase": {
            "bootstrap_warmup": {"transfer_count": 0, "submitted_bytes": 0},
            "steady_state": {"transfer_count": 0, "submitted_bytes": 0},
        },
        "by_workflow_cohort": {
            "bootstrap_initial_admission": {
                "transfer_count": 0,
                "submitted_bytes": 0,
            },
            "steady_state": {"transfer_count": 0, "submitted_bytes": 0},
        },
        "bandwidth_competition": {
            "definition": "allocated_rate_below_minimum_path_resource_capacity",
            "protection_flow_interval_count": 0,
            "contended_flow_interval_count": 0,
            "contended_flow_interval_ns_sum": 0,
            "minimum_allocated_rate_bytes_per_second": 0,
            "maximum_allocated_rate_bytes_per_second": 0,
            "interval_time_sum_is_not_wall_clock_union": True,
        },
    }


def _compact_system(
    runner: ModuleType,
    *,
    seed: int,
    variant_id: str,
    wct_offset: int,
) -> dict[str, Any]:
    workflow_ids = _workflow_ids()
    workflow_order = workflow_ids[seed:] + workflow_ids[:seed]
    return {
        "variant_id": variant_id,
        "variant_fingerprint": "a" * 64,
        "payload_sha256": "b" * 64,
        "journal_sha256": "c" * 64,
        "span_details_sha256": "d" * 64,
        "representative_sha256": "e" * 64,
        "workflow_wct_ns": {
            workflow_id: 1_000 + index + wct_offset
            for index, workflow_id in enumerate(workflow_ids)
        },
        "workflow_admission_order": workflow_order,
        "workflow_admission_order_sha256": runner.sha256_json(tuple(workflow_order)),
        "makespan_ns": 10_000 + wct_offset,
        "goodput_output_tokens_per_second_milli": 50_000 - wct_offset,
        "warmup": _warmup(workflow_order),
        "protection": _protection(),
        "algorithm2": {
            "event_count": 1 if variant_id == runner.AEGISKV_VARIANT_ID else 0,
            "preview_count": 1 if variant_id == runner.AEGISKV_VARIANT_ID else 0,
            "event_counts_by_kind": (
                {"FORMAL_ALGORITHM2_PREVIEW": 1} if variant_id == runner.AEGISKV_VARIANT_ID else {}
            ),
            "by_time_phase": {
                "bootstrap_warmup": 1 if variant_id == runner.AEGISKV_VARIANT_ID else 0,
                "steady_state": 0,
            },
        },
        "algorithm3": {
            "event_count": 1 if variant_id == runner.AEGISKV_VARIANT_ID else 0,
            "action_counts": (
                {"STABLE_WINDOW": 1} if variant_id == runner.AEGISKV_VARIANT_ID else {}
            ),
            "by_time_phase": {
                "bootstrap_warmup": 1 if variant_id == runner.AEGISKV_VARIANT_ID else 0,
                "steady_state": 0,
            },
        },
        "raw_artifact": {
            "path": f"raw/seed-{seed}/{variant_id}.json",
            "sha256": "f" * 64,
            "schema": runner.RAW_SCHEMA,
        },
    }


def _compact_cell(runner: ModuleType, seed: int) -> dict[str, Any]:
    return {
        "seed": seed,
        "systems": {
            runner.MOONCAKE_VARIANT_ID: _compact_system(
                runner,
                seed=seed,
                variant_id=runner.MOONCAKE_VARIANT_ID,
                wct_offset=0,
            ),
            runner.AEGISKV_VARIANT_ID: _compact_system(
                runner,
                seed=seed,
                variant_id=runner.AEGISKV_VARIANT_ID,
                wct_offset=10,
            ),
        },
    }


def test_protocol_seed_parser_is_exact_and_ordered() -> None:
    runner = _load_runner()

    assert runner._parse_seeds("0,1,2,3,4") == (0, 1, 2, 3, 4)
    with pytest.raises(Exception, match="exact ordered seeds"):
        runner._parse_seeds("4,3,2,1,0")
    with pytest.raises(Exception, match="exact ordered seeds"):
        runner._parse_seeds("0")


def test_paired_seed_retains_every_workflow_and_splits_bootstrap() -> None:
    runner = _load_runner()

    paired = runner._build_paired_seed(_compact_cell(runner, 0))

    assert len(paired["workflow_pairs"]) == 160
    assert paired["wct_delta_ns"] == {
        "count": 160,
        "min": 10,
        "p05": 10,
        "median": 10,
        "mean": 10,
        "p95": 10,
        "max": 10,
    }
    assert paired["wct_delta_ns_by_cohort"]["bootstrap_initial_admission"]["count"] == 16
    assert paired["wct_delta_ns_by_cohort"]["steady_state"]["count"] == 144
    assert paired["makespan"]["aegiskv_minus_mooncake_ns"] == 10


def test_paired_seed_rejects_divergent_realized_admission_order() -> None:
    runner = _load_runner()
    cell = _compact_cell(runner, 0)
    aegis = cell["systems"][runner.AEGISKV_VARIANT_ID]
    aegis["workflow_admission_order"] = list(reversed(aegis["workflow_admission_order"]))
    aegis["workflow_admission_order_sha256"] = runner.sha256_json(
        tuple(aegis["workflow_admission_order"])
    )

    with pytest.raises(runner.NoFailureOverheadError, match="exact realized"):
        runner._build_paired_seed(cell)


def test_document_rejects_seed_degenerate_admission_orders() -> None:
    runner = _load_runner()
    cells = [_compact_cell(runner, seed) for seed in range(5)]
    first_order = cells[0]["systems"][runner.MOONCAKE_VARIANT_ID][
        "workflow_admission_order"
    ]
    first_hash = runner.sha256_json(tuple(first_order))
    for cell in cells:
        for system in cell["systems"].values():
            system["workflow_admission_order"] = first_order
            system["workflow_admission_order_sha256"] = first_hash
            system["warmup"] = _warmup(first_order)

    with pytest.raises(runner.NoFailureOverheadError, match="five distinct"):
        runner._build_document(
            cells=cells,
            source_contract={
                "files": {runner.SCHEMA_RELATIVE_PATH: "1" * 64},
                "fingerprint": "2" * 64,
            },
            config_binding={"files": {}, "fingerprint": "3" * 64},
            workload_binding={},
            workload_manifest_fingerprint="4" * 64,
            context_bucket="96k",
            git_commit="5" * 40,
        )


def test_final_document_passes_checked_in_json_schema() -> None:
    runner = _load_runner()
    source_files = {
        runner.SCHEMA_RELATIVE_PATH: "1" * 64,
        "python/moonkvsim/aegiskv/experiment.py": "2" * 64,
        "pyproject.toml": "3" * 64,
        "uv.lock": "4" * 64,
    }
    source_body = {
        "binding_kind": "complete_python_tree_plus_protocol_schema_and_lockfiles",
        "files": source_files,
    }
    source_contract = {
        **source_body,
        "fingerprint": runner.sha256_json(source_body),
    }
    config_files = {
        "requests.json": "5" * 64,
        "failure.json": "6" * 64,
        "engine.json": "7" * 64,
    }
    config_binding = {
        "files": config_files,
        "fingerprint": runner.sha256_json(config_files),
    }
    workload_binding = {
        "declared_path": "benchmark/workload.jsonl",
        "sha256": "8" * 64,
        "record_count": 1304,
        "semantic_fingerprint": "9" * 64,
        "manifest_sha256": "a" * 64,
        "manifest_schema": "moonkvsim.aegiskv.experiment_workload_manifest.v1",
        "workload_kind": "fanoutqa_complete_tasks",
    }
    document = runner._build_document(
        cells=[_compact_cell(runner, seed) for seed in range(5)],
        source_contract=source_contract,
        config_binding=config_binding,
        workload_binding=workload_binding,
        workload_manifest_fingerprint="b" * 64,
        context_bucket="96k",
        git_commit="c" * 40,
    )

    runner._validate_output_schema(document, _SCHEMA_PATH)
    altered = json.loads(json.dumps(document))
    altered["protocol"]["scenario"] = "gpu_failure"
    with pytest.raises(runner.NoFailureOverheadError, match="schema validation failed"):
        runner._validate_output_schema(altered, _SCHEMA_PATH)


def test_aegiskv_run_summary_retains_protection_and_algorithm_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    variant = next(item for item in core_variants() if item.variant_id == runner.AEGISKV_VARIANT_ID)
    workflow_ids = _workflow_ids()
    details = []
    for index in range(1304):
        workflow_id = workflow_ids[index % len(workflow_ids)]
        details.append(
            {
                "span_id": f"span-{index:04d}",
                "workflow_id": workflow_id,
                "released_ns": 0,
                "compute_start_ns": index + 1,
                "completed_ns": 2_000 + index,
            }
        )
    cause = "AEGIS_PEER_HBM_PROTECTION"
    transfer = {
        "transfer_id": "transfer-0",
        "span_id": "span-0000",
        "cause": cause,
        "status": "COMMITTED",
        "ready_ns": 1,
        "start_ns": 3,
        "end_ns": 13,
        "bytes": 64,
        "transferred_bytes": 64,
        "aborted_bytes": 0,
    }
    formal_events = [{"event": "FORMAL_ALGORITHM2_PREVIEW", "timestamp_ns": 2}]
    aimd_events = [{"action": "STABLE_WINDOW", "timestamp_ns": 4}]
    payload = {
        "status": "PASS",
        "scenario": "no_failure",
        "variant_fingerprint": variant.fingerprint,
        "workflow_admission": {
            "mode": "closed_loop_workflow_concurrency",
            "workflow_concurrency": 16,
                "order_policy": "observed_submit_then_seeded_sha256_workflow_permutation",
                "seed": 0,
                "realized_workflow_order": workflow_ids,
                "realized_workflow_order_sha256": runner.sha256_json(tuple(workflow_ids)),
        },
        "workload": {
            "workflow_count": 160,
            "span_count": 1304,
            "no_truncation_or_padding": True,
        },
        "metrics": {
            "workload_end_ns": 10_000,
            "goodput_output_tokens_per_second_milli": 1_000,
            "failure_impact": {
                "failure_event_count": 0,
                "active_requests": 0,
                "queued_requests": 0,
                "failed_gpu_count": 0,
            },
            "recovery_latency_ns": {"count": 0},
            "pool_audit": {
                "normal_hbm": {
                    "valid": True,
                    "pinned_entry_count_final": 0,
                    "pinned_reference_count_final": 0,
                },
                "peer_hbm": {"valid": True},
                "store_dram": {
                    "valid": True,
                    "pinned_entry_count_final": 0,
                    "pinned_reference_count_final": 0,
                },
                "pending_destination_bytes_final": 0,
            },
            "policy_effects": {
                "formal_algorithm2_event_count": 1,
                "aimd_decision_count": 1,
            },
            "workflow_completion_time_ns": {
                "by_workflow_id": {
                    workflow_id: 1_000 + index for index, workflow_id in enumerate(workflow_ids)
                }
            },
            "resource_cost": {
                "transfer_byte_conservation_valid": True,
                "source_pin_count_final": 0,
                "gpu_hbm_foreground_store_reserve_final_bytes": 0,
                "submitted_bytes_by_cause": {cause: 64},
                "cause_bytes": {cause: 64},
                "aborted_bytes_by_cause": {cause: 0},
                "queue_wait_ns_by_cause": {cause: 2},
                "service_time_ns_by_cause": {cause: 10},
                "copy_engine_busy_ns": {cause: 10},
                "fabric_busy_ns": {cause: 10},
            },
        },
        "resource_model": {"rate_resources": {"gpu-0.hbm-rate": 100.25}},
        "output_audit": {
            "duplicate_or_missing_tokens": 0,
            "stale_route_output_count": 0,
        },
        "forbidden_semantics": {
            "hbm_to_dram_writeback_count": 0,
            "target_owned_destage_count": 0,
        },
        "evidence": {"class": "E2"},
    }
    representative = {
        "formal_algorithm2_events": formal_events,
        "aimd_events": aimd_events,
        "transfers": [transfer],
        "flow_rate_intervals": [
            {
                "cause": cause,
                "start_ns": 3,
                "end_ns": 13,
                "allocated_rate_bytes_per_second": 50.5,
                "path_resource_ids": ["gpu-0.hbm-rate"],
            }
        ],
    }
    result = StudyRunResult(
        payload=payload,
        journal_sha256="d" * 64,
        span_details=tuple(details),
        representative=representative,
    )
    report = SimpleNamespace(to_dict=lambda: {"schema": "test", "status": "PASS"})
    monkeypatch.setattr(runner, "audit_continuous_scheduler_evidence", lambda *_: report)
    monkeypatch.setattr(runner, "audit_formal_algorithm_run", lambda *_: report)

    compact, raw = runner._validate_and_summarize_run(
        result,
        variant=variant,
        seed=0,
        bootstrap_workflow_ids=workflow_ids[:16],
    )

    assert compact["protection"]["transfer_count"] == 1
    assert compact["protection"]["bandwidth_competition"]["contended_flow_interval_count"] == 1
    assert compact["algorithm2"]["event_count"] == 1
    assert compact["algorithm2"]["preview_count"] == 1
    assert compact["algorithm2"]["event_counts_by_kind"] == {"FORMAL_ALGORITHM2_PREVIEW": 1}
    assert compact["algorithm3"]["action_counts"] == {"STABLE_WINDOW": 1}
    assert raw["representative"]["formal_algorithm2_events"] == formal_events


def test_source_contract_includes_protocol_and_schema() -> None:
    runner = _load_runner()

    contract = runner._source_contract(_ROOT)

    assert (
        "benchmark/AegisKV/experiments/scripts/run_aegiskv_no_failure_overhead.py"
        in contract["files"]
    )
    assert runner.SCHEMA_RELATIVE_PATH in contract["files"]
    assert contract["fingerprint"] == runner.sha256_json(
        {
            "binding_kind": contract["binding_kind"],
            "files": contract["files"],
        }
    )
