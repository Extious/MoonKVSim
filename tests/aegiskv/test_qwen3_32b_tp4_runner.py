from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from moonkvsim.aegiskv.qwen3_32b_tp4_config import (
    MODEL_ID,
    MODEL_REVISION,
    default_qwen3_32b_tp4_config_path,
)
from moonkvsim.aegiskv.qwen3_32b_tp4_runner import (
    EVIDENCE_CLASS,
    RESULT_SCHEMA,
    SCHEDULE_SCHEMA,
    Qwen3TP4RunnerBlocked,
    Qwen3TP4RunnerError,
    run_qwen3_32b_tp4_contract,
)

ROOT = Path(__file__).resolve().parents[2]
FROZEN_8B_WORKLOAD = (
    ROOT / "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160.jsonl"
)
FROZEN_8B_MANIFEST = (
    ROOT / "benchmark/AegisKV/experiments/workloads/fanoutqa-dev-qwen3-8b-160-manifest.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _exact_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    workload = tmp_path / "qwen32.jsonl"
    records = [
        {
            "schema": "moonkvsim.multi_agent_trace.v1",
            "workflow_id": workflow_id,
            "span_id": f"span-{workflow_id}",
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
        }
        for workflow_id in ("workflow-0", "workflow-1")
    ]
    workload.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    manifest = tmp_path / "qwen32-manifest.json"
    _write_json(
        manifest,
        {
            "schema": "moonkvsim.aegiskv.experiment_workload_manifest.v1",
            "fingerprint": "fixture-manifest-fingerprint",
            "artifact": {"sha256": _sha256(workload), "record_count": 2},
            "normalizer": {"model_id": MODEL_ID, "model_revision": MODEL_REVISION},
            "selection": {"selected_workflow_ids": ["workflow-0", "workflow-1"]},
        },
    )
    schedule = tmp_path / "qwen32-schedule.json"
    _write_json(schedule, _schedule(workload, failure_count=1))
    return workload, manifest, schedule


def _schedule(workload: Path, *, failure_count: int) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    if failure_count:
        failures.append(
            {
                "failure_id": "failure-0",
                "occurred_ns": 450_000,
                "failed_gpu_ids": [],
                "failed_node_ids": ["node-0"],
                "affected_workflow_ids": ["workflow-0"],
                "recoveries": [
                    {
                        "workflow_id": "workflow-0",
                        "logical_chunk_id": "workflow-0:chunk-0",
                        "source_dp_rank": 0,
                        "token_count": 32,
                        "route_version": 1,
                        "protection_start_ns": 0,
                        "peer_hbm_available": True,
                        "store_dram_available": True,
                        "selected_pool": "PEER_HBM",
                        "recovery_start_ns": 450_000,
                        "directory_install_ns": 700,
                        "model_forward_all_reduce_bytes_per_rank": 4096,
                        "peer_activation_ns_by_rank": [10, 40, 20, 30],
                        "algorithm3_control_events": [
                            {
                                "target_dp_rank": 1,
                                "timestamp_ns": 1,
                                "foreground_pressure": True,
                                "reason": "PRIMARY_ALLOCATION_SHORTFALL",
                            },
                            *[
                                {
                                    "target_dp_rank": 1,
                                    "timestamp_ns": 1 + 100_000 * index,
                                    "foreground_pressure": False,
                                    "reason": "STABLE_WINDOW",
                                }
                                for index in range(1, 5)
                            ],
                        ],
                    }
                ],
            }
        )
    config = default_qwen3_32b_tp4_config_path(ROOT)
    return {
        "schema": SCHEDULE_SCHEMA,
        "evidence": {
            "timing_and_bandwidth": EVIDENCE_CLASS,
            "calibrated": False,
            "physical_measurement_completed": False,
            "wct_source": "explicit_external_schedule",
            "trend_generation": False,
        },
        "engine": {
            "model_id": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "config_sha256": _sha256(config),
        },
        "workload": {
            "artifact_sha256": _sha256(workload),
            "manifest_fingerprint": "fixture-manifest-fingerprint",
        },
        "cell_identity": {
            "cell_id": f"qwen32-f{failure_count}-c2-s0",
            "failure_count": failure_count,
            "workflow_concurrency": 2,
            "seed": 0,
        },
        "workflow_timings": [
            {"workflow_id": "workflow-0", "released_ns": 0, "completed_ns": 1_000_000},
            {"workflow_id": "workflow-1", "released_ns": 10, "completed_ns": 500},
        ],
        "failures": failures,
    }


def test_frozen_qwen3_8b_workload_blocks_without_emitting_wct() -> None:
    with pytest.raises(Qwen3TP4RunnerBlocked) as raised:
        run_qwen3_32b_tp4_contract(
            engine_config_path=default_qwen3_32b_tp4_config_path(ROOT),
            workload_path=FROZEN_8B_WORKLOAD,
            manifest_path=FROZEN_8B_MANIFEST,
            schedule_path=None,
        )

    report = raised.value.report
    assert report["status"] == "BLOCKED"
    assert report["result_rows_written"] == 0
    assert report["wct_emitted"] is False
    assert report["trend_generation_performed"] is False
    assert "metrics" not in report
    missing_gates = cast(list[dict[str, str]], report["missing_gates"])
    codes = {row["code"] for row in missing_gates}
    assert codes == {
        "WORKLOAD_MODEL_ID_MISMATCH",
        "WORKLOAD_MODEL_REVISION_MISMATCH",
        "QWEN3_32B_EXECUTION_SCHEDULE_MISSING",
        "QWEN3_32B_WORKFLOW_RELEASE_COMPLETION_TIMES_MISSING",
    }


def test_exact_schedule_emits_canonical_wct_reuse_and_tp_audit(tmp_path: Path) -> None:
    workload, manifest, schedule = _exact_fixture(tmp_path)

    result = run_qwen3_32b_tp4_contract(
        engine_config_path=default_qwen3_32b_tp4_config_path(ROOT),
        workload_path=workload,
        manifest_path=manifest,
        schedule_path=schedule,
    )

    assert result["schema"] == RESULT_SCHEMA
    assert result["status"] == "complete"
    assert result["evidence_class"] == EVIDENCE_CLASS
    assert result["execution_backend"] == "GlobalDES"
    assert result["des_execution_complete"] is True
    assert result["paper_ready"] is False
    assert result["trend_generation_performed"] is False
    assert result["failure_count"] == 1
    assert result["workflow_concurrency"] == 2
    metrics = cast(dict[str, Any], result["metrics"])
    assert metrics["workflow_completion_time_ns"]["by_workflow_id"] == {
        "workflow-0": 1_000_000,
        "workflow-1": 490,
    }
    assert metrics["cache_reuse_tokens"] == {
        "normal_hbm": 0,
        "peer_hbm": 32,
        "store_dram": 0,
        "peer_hbm_available": 32,
        "store_dram_available": 32,
        "peer_hbm_selected": 32,
        "store_dram_selected": 0,
    }
    assert metrics["restored_tokens"] == {"peer_hbm": 32, "store_dram": 0, "total": 32}
    workflow_rows = cast(list[dict[str, Any]], result["workflow_results"])
    by_workflow = {row["workflow_id"]: row for row in workflow_rows}
    assert by_workflow["workflow-0"]["failure_affected"] is True
    assert by_workflow["workflow-1"]["failure_affected"] is False
    audit = cast(list[dict[str, Any]], result["recovery_audit"])[0]
    assert len(audit["rank_costs"]) == 4
    assert len(audit["tp_readiness_barrier"]["participant_gpu_ids"]) == 4
    assert audit["tp_readiness_barrier"]["payload_bytes"] == 0
    assert audit["model_forward_all_reduce"]["operates_on_kv"] is False
    assert audit["model_forward_all_reduce"]["included_in_kv_recovery_latency"] is False
    assert audit["byte_conservation"]["kv_reduction_bytes"] == 0
    assert audit["byte_conservation"]["valid"] is True
    des_execution = audit["des_execution"]
    assert des_execution["backend"] == "GlobalDES"
    assert des_execution["evidence_class"] == "modeled_uncalibrated"
    assert des_execution["fenced_dp_ranks"] == [0]
    assert des_execution["failure_fence_event_count"] == 1
    assert des_execution["recovery_phase"] == "FORWARD_COMPLETE"
    assert des_execution["four_shard_recovery_executed"] is True
    assert des_execution["capacity_conservation_valid"] is True
    assert des_execution["algorithm3_controller_integration"] == ("per_dp_rank_global_des_aimd")
    assert [row["action"] for row in des_execution["algorithm3_audit"]] == [
        "MULTIPLICATIVE_DECREASE",
        "STABLE_WINDOW",
        "STABLE_WINDOW",
        "STABLE_WINDOW",
        "ADDITIVE_INCREASE",
    ]
    assert all(row["quota_enforced"] for row in des_execution["algorithm3_audit"])
    assert result["algorithm3_controller_integration"] == "per_dp_rank_global_des_aimd"
    assert [
        event["kind"]
        for event in des_execution["event_trace"]
        if "recovery-00000000" in event["event_id"]
    ] == [
        "RECOVERY_START",
        "GET_COMPLETE",
        "GET_COMPLETE",
        "GET_COMPLETE",
        "GET_COMPLETE",
        "RECOVERY_COMPLETE",
        "DIRECTORY_PUBLISH",
        "FORWARD_START",
        "FORWARD_COMPLETE",
    ]
    assert len(audit["rank_resource_audit"]) == 12
    focus = cast(list[dict[str, Any]], result["failure_focus_spans"])[0]
    assert focus["available_peer_tokens_at_failure"] == 32
    assert focus["available_store_tokens_at_failure"] == 32
    assert focus["restored_peer_tokens"] == 32
    assert focus["restored_store_tokens"] == 0
    assert result["fingerprint"]


def test_selecting_an_unavailable_reuse_path_fails_closed(tmp_path: Path) -> None:
    workload, manifest, schedule_path = _exact_fixture(tmp_path)
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    schedule["failures"][0]["recoveries"][0]["peer_hbm_available"] = False
    _write_json(schedule_path, schedule)

    with pytest.raises(Qwen3TP4RunnerError, match="selects an unavailable path"):
        run_qwen3_32b_tp4_contract(
            engine_config_path=default_qwen3_32b_tp4_config_path(ROOT),
            workload_path=workload,
            manifest_path=manifest,
            schedule_path=schedule_path,
        )


def test_formal_schedule_requires_algorithm3_control_evidence(tmp_path: Path) -> None:
    workload, manifest, schedule_path = _exact_fixture(tmp_path)
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    del schedule["failures"][0]["recoveries"][0]["algorithm3_control_events"]
    _write_json(schedule_path, schedule)

    with pytest.raises(Qwen3TP4RunnerError, match="algorithm3_control_events"):
        run_qwen3_32b_tp4_contract(
            engine_config_path=default_qwen3_32b_tp4_config_path(ROOT),
            workload_path=workload,
            manifest_path=manifest,
            schedule_path=schedule_path,
        )


def test_algorithm3_stable_window_cadence_fails_closed(tmp_path: Path) -> None:
    workload, manifest, schedule_path = _exact_fixture(tmp_path)
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    schedule["failures"][0]["recoveries"][0]["algorithm3_control_events"][1]["timestamp_ns"] += 1
    _write_json(schedule_path, schedule)

    with pytest.raises(Qwen3TP4RunnerError, match="fixed control window"):
        run_qwen3_32b_tp4_contract(
            engine_config_path=default_qwen3_32b_tp4_config_path(ROOT),
            workload_path=workload,
            manifest_path=manifest,
            schedule_path=schedule_path,
        )


def test_schedule_fails_closed_when_protection_cannot_commit_before_fence(
    tmp_path: Path,
) -> None:
    workload, manifest, schedule_path = _exact_fixture(tmp_path)
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    schedule["failures"][0]["occurred_ns"] = 100
    schedule["failures"][0]["recoveries"][0]["recovery_start_ns"] = 100
    schedule["failures"][0]["recoveries"][0]["algorithm3_control_events"] = [
        schedule["failures"][0]["recoveries"][0]["algorithm3_control_events"][0]
    ]
    _write_json(schedule_path, schedule)

    with pytest.raises(
        Qwen3TP4RunnerError,
        match="selected protection path was not committed before failure",
    ):
        run_qwen3_32b_tp4_contract(
            engine_config_path=default_qwen3_32b_tp4_config_path(ROOT),
            workload_path=workload,
            manifest_path=manifest,
            schedule_path=schedule_path,
        )


def test_formal_runner_executes_store_shards_on_global_des(tmp_path: Path) -> None:
    workload, manifest, schedule_path = _exact_fixture(tmp_path)
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    recovery = schedule["failures"][0]["recoveries"][0]
    recovery["selected_pool"] = "STORE_DRAM"
    recovery["peer_hbm_available"] = False
    recovery.pop("peer_activation_ns_by_rank")
    _write_json(schedule_path, schedule)

    result = run_qwen3_32b_tp4_contract(
        engine_config_path=default_qwen3_32b_tp4_config_path(ROOT),
        workload_path=workload,
        manifest_path=manifest,
        schedule_path=schedule_path,
    )

    audit = cast(list[dict[str, Any]], result["recovery_audit"])[0]
    assert audit["selected_pool"] == "STORE_DRAM"
    assert audit["destination_dp_rank"] == 1
    assert len(audit["rank_costs"]) == 4
    assert all(row["transfer_bytes"] > 0 for row in audit["rank_costs"])
    assert all(row["activation_bytes"] == 0 for row in audit["rank_costs"])
    assert (
        audit["byte_conservation"]["source_read_bytes"]
        == (audit["byte_conservation"]["logical_chunk_bytes"])
    )
    assert (
        audit["byte_conservation"]["destination_write_bytes"]
        == (audit["byte_conservation"]["logical_chunk_bytes"])
    )
    assert audit["des_execution"]["recovery_phase"] == "FORWARD_COMPLETE"


def test_cli_smoke_writes_complete_canonical_json(tmp_path: Path) -> None:
    workload, manifest, schedule = _exact_fixture(tmp_path)
    output = tmp_path / "result.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "moonkvsim.aegiskv.qwen3_32b_tp4_runner",
            "--engine-config",
            str(default_qwen3_32b_tp4_config_path(ROOT)),
            "--workload",
            str(workload),
            "--manifest",
            str(manifest),
            "--execution-schedule",
            str(schedule),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "complete"
    assert result["metrics"]["workflow_completion_time_ns"]["by_workflow_id"]


def test_cli_smoke_current_frozen_input_writes_blocked_gate_only(tmp_path: Path) -> None:
    output = tmp_path / "blocked.json"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "moonkvsim.aegiskv.qwen3_32b_tp4_runner",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "BLOCKED"
    assert report["wct_emitted"] is False
    assert "metrics" not in report
