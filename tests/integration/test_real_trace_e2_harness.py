from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import moonkvsim.baseline.e2_harness as e2_harness_module
from moonkvsim.baseline.e2_harness import (
    E2HarnessError,
    capture_semantic_source_snapshot,
    load_harness_config,
    resolve_failure_specs,
    run_harness,
)
from moonkvsim.baseline.trace_runner import (
    TraceFailureSpec,
    TraceRunStatus,
    VanillaBaselineTraceRunner,
)
from moonkvsim.common.hash import canonical_json_bytes
from moonkvsim.output.section16 import SECTION_16_ARTIFACTS

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASE_CONFIG = REPOSITORY_ROOT / "tests/fixtures/vanilla-e2/vanilla-weka-e2-smoke.json"
FIXTURE = Path(__file__).parent / "fixtures/weka-real-shape-three-span.jsonl"


@pytest.fixture
def local_output_root() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="moonkvsim-e2-test-", dir="/tmp") as path:
        yield Path(path)


def _fixture_document() -> dict[str, Any]:
    document: dict[str, Any] = copy.deepcopy(json.loads(BASE_CONFIG.read_bytes()))
    document["trace"].update(
        {
            "path": str(FIXTURE.resolve()),
            "sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            "expected_total_valid_span_count": 3,
            "selection": {
                "workflow_ids": [
                    "002001296e8a8c38ad9d7cc436d691afc602",
                    "wf-toy-001",
                ],
                "whole_workflow_closure": True,
            },
        }
    )
    return document


def _write_config(tmp_path: Path, document: dict[str, Any], name: str = "harness.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _fixture_config(tmp_path: Path) -> Path:
    return _write_config(tmp_path, _fixture_document())


def _assumed(value: int, note: str) -> dict[str, object]:
    return {"value": value, "source": "assumed", "note": note}


def _refresh_hardware_fingerprint(document: dict[str, Any]) -> None:
    predictor = document["predictor"]
    hardware_shape = {
        "schema": "moonkvsim.assumed-hardware-shape-profile.v1",
        "parameter_source": "assumed",
        "hardware_profile_id": predictor["hardware_profile_id"],
        "gpus": document["deployment"]["gpus"],
        "store": document["store"],
        "network": document["network"],
    }
    predictor["hardware_profile_fingerprint"] = hashlib.sha256(
        canonical_json_bytes(hardware_shape)
    ).hexdigest()


def _add_transfer_resource_plan(
    document: dict[str, Any],
    *,
    transport: str = "RDMA_GDR",
    duration_ns: int = 5_000_000,
) -> None:
    network = document["network"]
    network["transport"] = transport
    network["transfer_resource_plan"] = {
        "enabled": True,
        "parameter_source": "assumed",
        "calibration_status": "not_calibrated",
        "formal_use_allowed": False,
        "duration_ns": _assumed(duration_ns, "fixture-only lease interval"),
        "latest_start_slack_ns": _assumed(
            10_000_000_000,
            "fixture-only fail-closed queue deadline",
        ),
        "staging_alignment_bytes": _assumed(256, "fixture-only Host alignment"),
        "staging_allocator_metadata_bytes": _assumed(
            0,
            "fixture-only explicit zero metadata",
        ),
    }
    store_node_id = document["store"]["node_id"]
    gpus = document["deployment"]["gpus"]
    network["host_staging_resources"] = [
        {
            "resource_id": f"{item['replica_id']}.host-staging",
            "node_id": item["node_id"],
            "capacity_bytes": _assumed(1 << 30, "fixture-only Host staging capacity"),
        }
        for item in gpus
    ] + [
        {
            "resource_id": "store.host-staging",
            "node_id": store_node_id,
            "capacity_bytes": _assumed(1 << 30, "fixture-only Host staging capacity"),
        }
    ]
    network["concurrency_resources"] = (
        [
            {
                "resource_id": f"{item['replica_id']}.gpu-copy",
                "node_id": item["node_id"],
                "kind": "copy_engine_lane",
                "lanes": _assumed(1, "fixture-only copy lane"),
            }
            for item in gpus
        ]
        + [
            {
                "resource_id": "store.copy",
                "node_id": store_node_id,
                "kind": "copy_engine_lane",
                "lanes": _assumed(1, "fixture-only shared Store copy lane"),
            }
        ]
        + [
            {
                "resource_id": f"{item['replica_id']}.endpoint-qp",
                "node_id": item["node_id"],
                "kind": "endpoint_qp_lane",
                "lanes": _assumed(1, "fixture-only endpoint QP lane"),
            }
            for item in gpus
        ]
    )
    gpu_by_replica = {item["replica_id"]: item for item in gpus}
    for path in network["paths"]:
        replica_id = path["replica_id"]
        path["put_source_copy_resource_id"] = f"{replica_id}.gpu-copy"
        path["put_destination_copy_resource_id"] = "store.copy"
        path["put_endpoint_qp_resource_id"] = f"{replica_id}.endpoint-qp"
        path["get_source_copy_resource_id"] = "store.copy"
        path["get_destination_copy_resource_id"] = f"{replica_id}.gpu-copy"
        path["get_endpoint_qp_resource_id"] = f"{replica_id}.endpoint-qp"
        if transport == "TCP_HOST_STAGED":
            path["put_source_host_staging_resource_id"] = f"{replica_id}.host-staging"
            path["put_destination_host_staging_resource_id"] = "store.host-staging"
            path["get_source_host_staging_resource_id"] = "store.host-staging"
            path["get_destination_host_staging_resource_id"] = f"{replica_id}.host-staging"
        assert gpu_by_replica[replica_id]["node_id"]
    network.pop("concurrency_gap", None)
    _refresh_hardware_fingerprint(document)


def _remove_transfer_resource_plan(document: dict[str, Any]) -> None:
    network = document["network"]
    network.pop("transfer_resource_plan", None)
    network.pop("host_staging_resources", None)
    network["concurrency_resources"] = []
    for path in network["paths"]:
        for field in (
            "put_source_copy_resource_id",
            "put_destination_copy_resource_id",
            "put_endpoint_qp_resource_id",
            "get_source_copy_resource_id",
            "get_destination_copy_resource_id",
            "get_endpoint_qp_resource_id",
            "put_source_host_staging_resource_id",
            "put_destination_host_staging_resource_id",
            "get_source_host_staging_resource_id",
            "get_destination_host_staging_resource_id",
        ):
            path.pop(field, None)
    network.pop("concurrency_gap", None)
    _refresh_hardware_fingerprint(document)


def _failure_event(
    *,
    failure_id: str,
    at_ns: int,
    replica_id: str = "dp-0",
    gpu_id: str = "gpu-0",
    hbm_resource_id: str = "gpu-0.hbm",
) -> dict[str, object]:
    return {
        "failure_id": failure_id,
        "type": "GPU_FAILURE",
        "at_ns": at_ns,
        "detection_delay_ns": 0,
        "target": {
            "replica_id": replica_id,
            "gpu_id": gpu_id,
            "hbm_resource_id": hbm_resource_id,
        },
        "repair_after_ns": None,
        "semantics": "fail_stop_hbm_lost",
    }


def _enable_failures(
    document: dict[str, Any],
    events: list[dict[str, object]],
) -> None:
    document["failure"] = {
        "enabled": True,
        "mode": "fixed_virtual_time_gpu_fail_stop",
        "parameter_source": "assumed",
        "calibration_status": "not_calibrated",
        "formal_use_allowed": False,
        "random_selection": False,
        "implicit_fallback": False,
        "events": events,
    }


def test_fixture_replay_publishes_deterministic_complete_section_16_matrix(
    tmp_path: Path,
    local_output_root: Path,
) -> None:
    config_path = _fixture_config(tmp_path)
    first = run_harness(load_harness_config(config_path), local_output_root / "run-a")
    second = run_harness(load_harness_config(config_path), local_output_root / "run-b")

    assert first.result.status is TraceRunStatus.PASS
    assert first.artifact_sha256 == second.artifact_sha256
    assert set(first.artifact_sha256) == set(SECTION_16_ARTIFACTS)
    assert first.result.run_input.total_valid_span_count == 3
    assert first.failure_specs == ()
    assert first.result.mixed_phase_composition_rule is not None
    assert first.result.run_audit_document()["predictor"] == {
        "provider_name": "moonkvsim-assumed-integer-shape-formula",
        "profile_fingerprint": first.result.predictor_profile_fingerprint,
        "calibration_label": "preliminary",
        "calibration_status": "not_calibrated",
        "database_sha256": None,
        "mixed_phase_composition": {
            "configured": True,
            "used_step_count": first.result.mixed_phase_composition_count,
            "rule": first.result.mixed_phase_composition_rule.to_dict(),
        },
    }
    run_audit = json.loads((first.output_directory / "run-audit.json").read_text(encoding="utf-8"))
    assert run_audit["section_16"]["artifact_count"] == 19
    assert run_audit["transfer_resource_protocol"]["config"]["transport"] == "RDMA_GDR"
    assert (
        run_audit["transfer_resource_protocol"][
            "endpoint_registration_delay_aggregated_into_gpu_forward"
        ]
        is False
    )
    assert first.to_dict()["transfer_resource_protocol"]["config"]["transport"] == ("RDMA_GDR")
    assert all(
        not record.data["staging_allocations"]
        for record in first.result.journal.records
        if record.record_type == "TRANSFER_RESOURCE_LEASE_ACQUIRED"
    )
    endpoint_ready = [
        record
        for record in first.result.journal.records
        if record.record_type == "TRANSFER_ENDPOINT_READY"
    ]
    assert endpoint_ready
    assert all(record.data["aggregated_into_gpu_forward"] is False for record in endpoint_ready)
    assert {
        record.data["kind"]
        for record in first.result.journal.records
        if record.record_type == "EVENT_EXECUTING"
        and str(record.data["kind"]).startswith("ENDPOINT_")
    } == {
        "ENDPOINT_REGISTRATION_START",
        "ENDPOINT_REGISTRATION_COMPLETE",
        "ENDPOINT_READY",
    }
    assert run_audit["semantic_source_provenance"]["unchanged_during_run"] is True
    assert first.semantic_source_snapshot.git_head_state in {"unborn", "resolved"}
    assert first.semantic_source_snapshot.source_frozen is False
    initial_hbm = first.result.initial_ledgers["gpu-0.hbm"].accounts
    assert initial_hbm["MODEL_WEIGHTS"] == 17_179_869_184
    assert initial_hbm["RUNTIME_FIXED"] == 4_294_967_296
    assert initial_hbm["RUNTIME_DYNAMIC"] == 0
    assert "UNATTRIBUTED_RESERVE" not in initial_hbm

    projection = first.result.section_16_projection()
    capacity_projection = projection.document("capacity-audit.json")
    assert capacity_projection["snapshot_state_complete"] is True
    assert capacity_projection["incomplete_resource_ids"] == []
    assert capacity_projection["resource_count"] == len(first.result.initial_ledgers)
    assert capacity_projection["truth_sources"] == [
        "flow-rate-events",
        "initial-capacity-ledgers",
        "resource-ledger-deltas",
    ]
    assert "initial-capacity-ledgers" in projection.document("run-audit.json")["truth_sources"]
    snapshot_rows = projection.table_rows("resource-ledger-snapshots.parquet")
    assert all(row["snapshot_complete"] is True for row in snapshot_rows)
    assert {
        row["resource_id"] for row in snapshot_rows if row["boundary_index"] == 0
    } == set(first.result.initial_ledgers)

    request_rows = projection.table_rows("request-metrics.parquet")
    assert all(row["timing_complete"] is True for row in request_rows)
    assert projection.document("summary.json")["request_timing_complete_count"] == len(
        request_rows
    )

    workflow_rows = projection.table_rows("workflow-metrics.parquet")
    assert all(row["timing_complete"] is True for row in workflow_rows)
    [multi_request_workflow] = [row for row in workflow_rows if row["request_count"] > 1]
    assert multi_request_workflow["tpot_applicable"] is False
    assert multi_request_workflow["tpot_complete"] is True
    assert multi_request_workflow["tpot_evidence"] == (
        "not_applicable_across_multiple_request_output_streams"
    )
    assert projection.document("summary.json")["workflow_timing_complete_count"] == len(
        workflow_rows
    )


def test_harness_rejects_existing_output_and_unknown_config_key(
    tmp_path: Path,
    local_output_root: Path,
) -> None:
    config_path = _fixture_config(tmp_path)
    existing = local_output_root / "existing"
    existing.mkdir()
    with pytest.raises(E2HarnessError, match="already exists"):
        run_harness(load_harness_config(config_path), existing)

    document = json.loads(config_path.read_bytes())
    document["unrecognized"] = True
    config_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(E2HarnessError, match="schema validation failed"):
        load_harness_config(config_path)


def test_harness_refuses_publication_when_semantic_source_snapshot_drifts(
    tmp_path: Path,
    local_output_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_harness_config(_fixture_config(tmp_path))
    stable = e2_harness_module.capture_semantic_source_snapshot(config)
    changed = replace(stable, semantic_files_sha256="f" * 64)
    snapshots = iter((stable, changed))
    monkeypatch.setattr(
        e2_harness_module,
        "capture_semantic_source_snapshot",
        lambda _config: next(snapshots),
    )
    output = local_output_root / "drifted"

    with pytest.raises(E2HarnessError, match="changed during the run"):
        run_harness(config, output)

    assert not output.exists()


def test_checked_in_config_is_explicitly_nonformal_and_failure_free() -> None:
    config = load_harness_config(BASE_CONFIG)

    assert config.document["evidence"]["class"] == "E2"
    assert config.document["evidence"]["formal_use_allowed"] is False
    assert config.document["predictor"]["predictor_database_sha256"] is None
    assert config.document["predictor"]["calibration_status"] == "not_calibrated"
    composition = config.document["predictor"]["mixed_phase_composition"]
    assert composition["kind"] == "joint_assumed_integer_formula"
    assert composition["base_application"] == "once_per_joint_scheduler_step"
    assert composition["phase_provider_predictions_summed"] is False
    assert config.document["failure"]["enabled"] is False
    network = config.document["network"]
    assert config.transfer_resource_plan_enabled
    assert network["transport"] == "RDMA_GDR"
    assert len(network["concurrency_resources"]) == 5
    assert network["host_staging_resources"]
    assert all("host_staging_resource_id" not in key for path in network["paths"] for key in path)
    assert config.document["scheduler"]["max_num_running_requests"] > 1
    assert set(config.document["output"]["artifact_set"]) == set(SECTION_16_ARTIFACTS)
    assert config.workflow_ids == ("e094e1381d88f8aa6c9592279d51f97c5d87",)

    snapshot = capture_semantic_source_snapshot(config)
    entries = {item["path"]: item for item in snapshot.semantic_files}
    python_sources = tuple(
        path for path in (REPOSITORY_ROOT / "python/moonkvsim").rglob("*.py") if path.is_file()
    )
    assert sum(
        "python/moonkvsim-source" in item["roles"] for item in snapshot.semantic_files
    ) == len(python_sources)
    assert "scripts/run_vanilla_trace_e2.py" in entries
    assert "scripts/run_vanilla_failure_trace_e2.py" not in entries
    assert "schemas/vanilla-trace-e2-harness.schema.json" in entries
    assert config.document["target"]["kv_layout_path"] in entries
    assert len(snapshot.semantic_files_sha256) == 64
    assert len(snapshot.git_porcelain_sha256) == 64
    if snapshot.git_head_state == "unborn":
        assert snapshot.git_head_commit is None
        assert snapshot.git_head_tree is None
        assert "unborn_git_head" in snapshot.source_freeze_blockers


def test_loaded_config_is_immutable_and_run_revalidates_exact_file_bytes(
    tmp_path: Path,
    local_output_root: Path,
) -> None:
    config_path = _fixture_config(tmp_path)
    config = load_harness_config(config_path)
    original_sha256 = config.sha256
    detached = config.document
    assert isinstance(detached, dict)
    _enable_failures(detached, [_failure_event(failure_id="detached", at_ns=1)])

    assert config.sha256 == original_sha256
    assert config.failure_enabled is False
    assert resolve_failure_specs(config) == ()

    changed = _fixture_document()
    changed["failure"]["reason"] = "changed_after_validation"
    config_path.write_text(json.dumps(changed), encoding="utf-8")
    output = local_output_root / "changed-config"
    with pytest.raises(E2HarnessError, match="bytes changed after validation"):
        run_harness(config, output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda event: event.update(type="CPU_FAILURE"), "schema validation failed"),
        (lambda event: event.update(at_ns=-1), "schema validation failed"),
    ],
)
def test_failure_schema_rejects_non_gpu_and_negative_time(
    tmp_path: Path,
    mutation: Any,
    message: str,
) -> None:
    document = _fixture_document()
    event = _failure_event(failure_id="invalid", at_ns=1)
    mutation(event)
    _enable_failures(document, [event])

    with pytest.raises(E2HarnessError, match=message):
        load_harness_config(_write_config(tmp_path, document))


def test_failure_semantics_reject_unknown_duplicate_and_out_of_order_targets(
    tmp_path: Path,
) -> None:
    unknown = _fixture_document()
    _enable_failures(
        unknown,
        [
            _failure_event(
                failure_id="unknown-target",
                at_ns=1,
                replica_id="dp-missing",
            )
        ],
    )
    with pytest.raises(E2HarnessError, match="exactly match"):
        load_harness_config(_write_config(tmp_path, unknown, "unknown.json"))

    duplicate_time = _fixture_document()
    _enable_failures(
        duplicate_time,
        [
            _failure_event(failure_id="failure-a", at_ns=10),
            _failure_event(
                failure_id="failure-b",
                at_ns=10,
                replica_id="dp-1",
                gpu_id="gpu-1",
                hbm_resource_id="gpu-1.hbm",
            ),
        ],
    )
    with pytest.raises(E2HarnessError, match="at_ns values must be unique"):
        load_harness_config(_write_config(tmp_path, duplicate_time, "duplicate.json"))

    out_of_order = _fixture_document()
    _enable_failures(
        out_of_order,
        [
            _failure_event(failure_id="failure-a", at_ns=20),
            _failure_event(
                failure_id="failure-b",
                at_ns=10,
                replica_id="dp-1",
                gpu_id="gpu-1",
                hbm_resource_id="gpu-1.hbm",
            ),
        ],
    )
    with pytest.raises(E2HarnessError, match="ordered by increasing"):
        load_harness_config(_write_config(tmp_path, out_of_order, "order.json"))


def test_disabled_failure_protocol_passes_exact_empty_tuple(
    tmp_path: Path,
    local_output_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[TraceFailureSpec, ...]] = []
    original = VanillaBaselineTraceRunner.run

    def recording_run(
        runner: VanillaBaselineTraceRunner,
        run_input: Any,
        *,
        failures: tuple[TraceFailureSpec, ...] = (),
    ) -> Any:
        observed.append(tuple(failures))
        return original(runner, run_input, failures=failures)

    monkeypatch.setattr(VanillaBaselineTraceRunner, "run", recording_run)
    outcome = run_harness(
        load_harness_config(_fixture_config(tmp_path)),
        local_output_root / "disabled",
    )

    assert observed == [()]
    assert outcome.failure_specs == ()
    assert "failure_protocol" not in outcome.to_dict()
    assert "failure_protocol" not in outcome.result.run_audit_document()


def test_enabled_failure_protocol_passes_configured_canonical_order(
    tmp_path: Path,
    local_output_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _fixture_document()
    _enable_failures(
        document,
        [
            _failure_event(failure_id="late-dp0", at_ns=1_000_000_000),
            _failure_event(
                failure_id="late-dp1",
                at_ns=1_100_000_000,
                replica_id="dp-1",
                gpu_id="gpu-1",
                hbm_resource_id="gpu-1.hbm",
            ),
        ],
    )
    observed: list[tuple[TraceFailureSpec, ...]] = []
    original = VanillaBaselineTraceRunner.run

    def recording_run(
        runner: VanillaBaselineTraceRunner,
        run_input: Any,
        *,
        failures: tuple[TraceFailureSpec, ...] = (),
    ) -> Any:
        observed.append(tuple(failures))
        return original(runner, run_input, failures=failures)

    monkeypatch.setattr(VanillaBaselineTraceRunner, "run", recording_run)
    config = load_harness_config(_write_config(tmp_path, document))
    expected = resolve_failure_specs(config)
    outcome = run_harness(config, local_output_root / "enabled-order")

    assert observed == [expected]
    assert tuple(item.failure_id for item in expected) == ("late-dp0", "late-dp1")
    assert tuple(item.at_ns for item in expected) == (1_000_000_000, 1_100_000_000)
    protocol = outcome.result.run_audit_document()["failure_protocol"]
    assert protocol["events"][0]["target"] == {
        "replica_id": "dp-0",
        "gpu_id": "gpu-0",
        "hbm_resource_id": "gpu-0.hbm",
    }
    assert protocol["random_selection"] is False
    assert protocol["implicit_fallback"] is False
    assert outcome.to_dict()["failure_protocol"]["events"] == protocol["events"]


def test_fixed_post_output_failure_recovers_committed_prefix_atomically(
    tmp_path: Path,
    local_output_root: Path,
) -> None:
    document = _fixture_document()
    _add_transfer_resource_plan(document, transport="RDMA_GDR")
    _enable_failures(
        document,
        [
            _failure_event(
                failure_id="fixture-post-output-dp0",
                # One nanosecond after output zero with the configured
                # independent cold endpoint registration lifecycle.
                at_ns=262_213_202,
            )
        ],
    )
    outcome = run_harness(
        load_harness_config(_write_config(tmp_path, document)),
        local_output_root / "post-output-failure",
    )
    records = outcome.result.journal.records
    output_records = [item for item in records if item.record_type == "BASELINE_OUTPUT_ACTIVATED"]
    output_keys = [(item.data["request_id"], item.data["output_index"]) for item in output_records]

    assert outcome.result.status is TraceRunStatus.PASS
    assert len(output_keys) == len(set(output_keys))
    assert any(
        item.timestamp_ns == 262_213_201
        and item.data["output_index"] == 0
        and "subagent:000001" in item.data["request_id"]
        for item in output_records
    )
    recovery_gets = [
        item
        for item in records
        if item.record_type == "STORE_CLIENT_GET_STARTED"
        and item.data["cause"] == "BASELINE_E2_COMMITTED_STORE_PREFIX_RESTORE"
    ]
    assert len(recovery_gets) == 2
    assert all(item.data["required_allocation_ids"] for item in recovery_gets)
    required_types = {
        "VLLM_HBM_RECOVERY_BLOCKS_RESERVED",
        "BASELINE_RECOVERY_FETCHES_STARTED",
        "BASELINE_RECOVERY_SCHEDULER_PREPARED",
        "BASELINE_SILENT_REPLAY_FORWARD_SCHEDULED",
        "BASELINE_SILENT_REPLAY_FORWARD_COMPLETED",
        "TRACE_RUNNER_RECOVERY_ACTIVATED",
    }
    assert required_types <= {item.record_type for item in records}
    completed_sequence = next(
        item.journal_sequence
        for item in records
        if item.record_type == "BASELINE_SILENT_REPLAY_FORWARD_COMPLETED"
    )
    activation = next(
        item for item in records if item.record_type == "TRACE_RUNNER_RECOVERY_ACTIVATED"
    )
    assert completed_sequence < activation.journal_sequence
    assert activation.data["silent_replay"]["status"] == "ACTIVATED"
    assert activation.data["activation_gate"] == (
        "READY_TO_ACTIVATE_after_modeled_forward_completion"
    )
    assert outcome.result.capacity_audit.valid
    assert outcome.result.allocation_registry_replay_byte_identical
    assert outcome.result.run_audit_document()["journal_replay_byte_identical"] is True
    assert set(outcome.artifact_sha256) == set(SECTION_16_ARTIFACTS)
    semantic_paths = {item["path"] for item in outcome.semantic_source_snapshot.semantic_files}
    assert "scripts/run_vanilla_failure_trace_e2.py" in semantic_paths
    assert "scripts/run_vanilla_trace_e2.py" not in semantic_paths
    resource_protocol = outcome.result.run_audit_document()["transfer_resource_protocol"]
    assert resource_protocol["config"]["transport"] == "RDMA_GDR"
    acquired = [item for item in records if item.record_type == "TRANSFER_RESOURCE_LEASE_ACQUIRED"]
    assert acquired
    assert all(not item.data["staging_allocations"] for item in acquired)


def test_second_gpu_failure_without_reroute_target_releases_compute_lease(
    tmp_path: Path,
    local_output_root: Path,
) -> None:
    document = _fixture_document()
    _enable_failures(
        document,
        [
            _failure_event(failure_id="fail-dp0", at_ns=10),
            _failure_event(
                failure_id="fail-dp1",
                at_ns=20,
                replica_id="dp-1",
                gpu_id="gpu-1",
                hbm_resource_id="gpu-1.hbm",
            ),
        ],
    )
    outcome = run_harness(
        load_harness_config(_write_config(tmp_path, document)),
        local_output_root / "no-reroute-target",
    )
    records = outcome.result.journal.records
    compute_releases = [
        item for item in records if item.record_type == "TRACE_RUNNER_GPU_COMPUTE_LEASE_RELEASED"
    ]

    assert outcome.result.status is TraceRunStatus.BLOCKED
    assert "TRC-BLOCK-RECOVERY-NO-TARGET" in {item.code for item in outcome.result.gaps}
    assert any(
        str(item.data["outcome"]).startswith("CANCELED:GPU_FAILURE:fail-dp1")
        for item in compute_releases
    )
    acquired_transfer_leases = sum(
        item.record_type == "TRANSFER_RESOURCE_LEASE_ACQUIRED" for item in records
    )
    released_transfer_leases = sum(
        item.record_type == "TRANSFER_RESOURCE_LEASE_RELEASED" for item in records
    )
    assert released_transfer_leases == acquired_transfer_leases
    assert outcome.result.capacity_audit.valid
    assert outcome.result.allocation_registry_replay_byte_identical


def test_tcp_host_staging_queues_and_releases_all_caller_owned_resources(
    tmp_path: Path,
    local_output_root: Path,
) -> None:
    document = _fixture_document()
    _add_transfer_resource_plan(document, transport="TCP_HOST_STAGED")
    outcome = run_harness(
        load_harness_config(_write_config(tmp_path, document)),
        local_output_root / "tcp-queue",
    )
    records = outcome.result.journal.records
    acquired = [item for item in records if item.record_type == "TRANSFER_RESOURCE_LEASE_ACQUIRED"]
    released = [item for item in records if item.record_type == "TRANSFER_RESOURCE_LEASE_RELEASED"]

    assert outcome.result.status is TraceRunStatus.PASS
    assert acquired and len(released) == len(acquired)
    assert any(item.data["start_ns"] > item.data["acquired_ns"] for item in acquired)
    assert all(len(item.data["concurrency_reservations"]) == 3 for item in acquired)
    assert all(len(item.data["staging_allocations"]) == 2 for item in acquired)
    assert {item.data["outcome"] for item in released} == {"COMPLETED"}
    for resource_id, ledger in outcome.result.final_ledgers.items():
        if resource_id.endswith("host-staging"):
            assert ledger.bytes_in("FREE") == ledger.capacity_bytes
    assert outcome.result.capacity_audit.valid
    protocol = outcome.result.run_audit_document()["transfer_resource_protocol"]
    assert protocol["host_staging_charge_rule"] == (
        "forbidden_for_RDMA_GDR_required_for_TCP_HOST_STAGED"
    )
    assert protocol["queue_wait_reconstruction"] == ("lease.start_ns_minus_acquired_ns")


def test_tcp_failure_cancels_active_and_queued_staging_leases_once(
    tmp_path: Path,
    local_output_root: Path,
) -> None:
    document = _fixture_document()
    _add_transfer_resource_plan(document, transport="TCP_HOST_STAGED")
    _enable_failures(
        document,
        [
            _failure_event(
                failure_id="fixture-active-put-dp1",
                # Endpoint registration completes at 1_190_825 ns; fail
                # after the first lease starts while the second is queued.
                at_ns=1_190_826,
                replica_id="dp-1",
                gpu_id="gpu-1",
                hbm_resource_id="gpu-1.hbm",
            )
        ],
    )
    outcome = run_harness(
        load_harness_config(_write_config(tmp_path, document)),
        local_output_root / "tcp-failure-release",
    )
    releases = [
        item
        for item in outcome.result.journal.records
        if item.record_type == "TRANSFER_RESOURCE_LEASE_RELEASED"
        and item.data["outcome"] == "GPU_FAILURE"
    ]

    assert outcome.result.status is TraceRunStatus.PASS
    assert len(releases) == 2
    assert len({item.data["lease_id"] for item in releases}) == len(releases)
    assert all(len(item.data["staging_allocation_ids"]) == 2 for item in releases)
    assert all(len(item.data["concurrency_reservation_ids"]) == 3 for item in releases)
    endpoint_teardowns = [
        item
        for item in outcome.result.journal.records
        if item.record_type == "TRANSFER_ENDPOINT_TORN_DOWN"
        and item.data["reason"] == "GPU_FAILURE:fixture-active-put-dp1"
    ]
    assert endpoint_teardowns
    assert all(item.data["new_state"] == "COLD" for item in endpoint_teardowns)
    for resource_id, ledger in outcome.result.final_ledgers.items():
        if resource_id.endswith("host-staging"):
            assert ledger.bytes_in("FREE") == ledger.capacity_bytes
    assert outcome.result.capacity_audit.valid
    assert outcome.result.allocation_registry_replay_byte_identical


def test_transfer_resource_config_fails_closed_without_plan_or_known_resource(
    tmp_path: Path,
) -> None:
    no_plan = _fixture_document()
    _remove_transfer_resource_plan(no_plan)
    no_plan["network"]["transport"] = "TCP_HOST_STAGED"
    _refresh_hardware_fingerprint(no_plan)
    with pytest.raises(E2HarnessError, match="schema validation failed"):
        load_harness_config(_write_config(tmp_path, no_plan, "no-plan.json"))

    missing_binding = _fixture_document()
    _add_transfer_resource_plan(missing_binding)
    del missing_binding["network"]["paths"][0]["put_endpoint_qp_resource_id"]
    _refresh_hardware_fingerprint(missing_binding)
    with pytest.raises(E2HarnessError, match="schema validation failed"):
        load_harness_config(_write_config(tmp_path, missing_binding, "missing.json"))


def test_harness_rejects_wrong_endpoint_and_unknown_hca_bindings(tmp_path: Path) -> None:
    wrong_endpoint = _fixture_document()
    wrong_endpoint["network"]["paths"][0]["put_source_endpoint"] = "rdma://compute-0/wrong-gpu"
    _refresh_hardware_fingerprint(wrong_endpoint)
    with pytest.raises(E2HarnessError, match="does not match its source location"):
        load_harness_config(_write_config(tmp_path, wrong_endpoint, "wrong-endpoint.json"))

    unknown_hca = _fixture_document()
    unknown_hca["network"]["paths"][0]["get_destination_hca_id"] = "missing-hca"
    _refresh_hardware_fingerprint(unknown_hca)
    with pytest.raises(E2HarnessError, match="names unknown HCA"):
        load_harness_config(_write_config(tmp_path, unknown_hca, "unknown-hca.json"))

    unknown = _fixture_document()
    _add_transfer_resource_plan(unknown)
    unknown["network"]["paths"][0]["put_endpoint_qp_resource_id"] = "unknown-qp"
    _refresh_hardware_fingerprint(unknown)
    with pytest.raises(E2HarnessError, match="unknown concurrency resource"):
        load_harness_config(_write_config(tmp_path, unknown, "unknown-resource.json"))

    duplicate_id = _fixture_document()
    _add_transfer_resource_plan(duplicate_id)
    duplicate = copy.deepcopy(duplicate_id["network"]["concurrency_resources"][0])
    duplicate["lanes"]["note"] = "same ID with a distinct declaration"
    duplicate_id["network"]["concurrency_resources"].append(duplicate)
    _refresh_hardware_fingerprint(duplicate_id)
    with pytest.raises(E2HarnessError, match="resource IDs must be unique"):
        load_harness_config(_write_config(tmp_path, duplicate_id, "duplicate-resource.json"))

    duplicate_path = _fixture_document()
    duplicate_path["network"]["paths"].append(copy.deepcopy(duplicate_path["network"]["paths"][0]))
    duplicate_path["network"]["paths"][-1]["put_path_id"] = "duplicate-dp0-put"
    _refresh_hardware_fingerprint(duplicate_path)
    with pytest.raises(E2HarnessError, match="path replica IDs must be unique"):
        load_harness_config(_write_config(tmp_path, duplicate_path, "duplicate-path.json"))

    duplicate_directional_path = _fixture_document()
    duplicate_directional_path["network"]["paths"][1]["get_path_id"] = duplicate_directional_path[
        "network"
    ]["paths"][0]["put_path_id"]
    _refresh_hardware_fingerprint(duplicate_directional_path)
    with pytest.raises(E2HarnessError, match="directional network path IDs must be unique"):
        load_harness_config(
            _write_config(tmp_path, duplicate_directional_path, "duplicate-path-id.json")
        )


@pytest.mark.parametrize(
    ("field", "index"),
    [("lanes", 0), ("capacity_bytes", 0)],
)
def test_transfer_resource_schema_requires_positive_lanes_and_capacity(
    tmp_path: Path,
    field: str,
    index: int,
) -> None:
    document = _fixture_document()
    collection = "concurrency_resources" if field == "lanes" else "host_staging_resources"
    document["network"][collection][index][field]["value"] = 0
    _refresh_hardware_fingerprint(document)

    with pytest.raises(E2HarnessError, match="schema validation failed"):
        load_harness_config(_write_config(tmp_path, document, f"zero-{field}.json"))


def test_unresolved_failure_template_is_deliberately_not_runnable() -> None:
    template = (
        REPOSITORY_ROOT
        / "tests/fixtures/vanilla-e2/vanilla-weka-failure-e2-unresolved.template.json"
    )

    with pytest.raises(E2HarnessError, match="schema validation failed"):
        load_harness_config(template)
