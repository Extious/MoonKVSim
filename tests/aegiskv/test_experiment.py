from __future__ import annotations

from pathlib import Path

from moonkvsim.aegiskv.experiment import (
    CellSpec,
    ModelParameters,
    Scenario,
    SystemId,
    ablation_variants,
    core_variants,
    derive_failure_schedule,
    run_study_cell,
    sensitivity_variants,
)
from moonkvsim.aegiskv.experiment_workload import load_experiment_records


def _committed_records() -> list[dict[str, object]]:
    root = Path(__file__).resolve().parents[2]
    path = root / "benchmark/AegisKV/experiments/workloads/weka-e2-two-workflow-shapes.jsonl"
    return load_experiment_records(path)


def test_protocol_enumerates_seven_systems_and_declared_variants() -> None:
    assert [item.variant_id for item in core_variants()] == [item.value for item in SystemId]
    assert len(ablation_variants()) == 12
    assert len(sensitivity_variants()) == 27
    assert {item.suite for item in core_variants()} == {"core"}
    assert {item.suite for item in ablation_variants()} == {"ablation"}
    assert {item.suite for item in sensitivity_variants()} == {"sensitivity"}


def test_sensitivity_catalog_binds_fabric_and_control_delay_parameters() -> None:
    variants = {item.variant_id: item for item in sensitivity_variants()}

    assert (
        variants["peer_fabric_bandwidth_gbps=50"]
        .parameters.peer_bandwidth_bytes_per_second
        == 50_000_000_000
    )
    assert variants["detection_delay_ms=20"].parameters.failure_detection_ns == 20_000_000
    assert variants["reroute_delay_ms=0"].parameters.reroute_ns == 0


def test_failure_cell_is_fresh_run_byte_identical_and_scope_limited() -> None:
    records = _committed_records()
    schedule = derive_failure_schedule(records, bucket="64k", seed=20260830)
    variant = core_variants()[-1]
    first = run_study_cell(
        records,
        CellSpec(
            variant=variant,
            context_bucket="64k",
            scenario=Scenario.GPU_FAILURE,
            seed=20260830,
            repetition="A",
            failure_schedule=schedule,
        ),
    )
    second = run_study_cell(
        records,
        CellSpec(
            variant=variant,
            context_bucket="64k",
            scenario=Scenario.GPU_FAILURE,
            seed=20260830,
            repetition="B",
            failure_schedule=schedule,
        ),
    )
    assert first.payload_sha256 == second.payload_sha256
    assert first.journal_sha256 == second.journal_sha256
    assert first.payload == second.payload
    assert first.payload["global_clock"] == {
        "kind": "single_global_virtual_clock",
        "time_unit": "ns",
        "wall_clock_or_sleep_used": False,
        "event_order": "timestamp_priority_stable_sequence",
    }
    assert first.payload["evidence"] == {
        "class": "E2",
        "scope": "modeled/preliminary",
        "calibration": "not_calibrated",
        "physical_execution": False,
        "physical_timing_claim_allowed": False,
        "formal_use_allowed": False,
        "paper_ready": False,
    }
    assert first.payload["metrics"]["failure_impact"]["active_requests"] >= 1
    assert first.payload["output_audit"]["duplicate_or_missing_tokens"] == 0
    assert first.payload["output_audit"]["stale_route_output_count"] == 0
    assert set(first.payload["metrics"]["restored_tokens"]) == {
        "peer_hbm",
        "store_dram",
        "total",
    }
    assert all(value == 0 for value in first.payload["forbidden_semantics"].values())
    assert first.payload["metrics"]["pool_audit"]["unattributed_reserve_bytes"] == 0
    assert first.payload["metrics"]["pool_audit"]["pending_destination_bytes_final"] == 0
    resource_model = first.payload["resource_model"]
    assert resource_model["communication_backend"] == "flow_contention"
    assert resource_model["fairness"] == "weighted_max_min_work_conserving"
    assert resource_model["flow_clock"] == "shared_global_des_now_ns"
    resource_cost = first.payload["metrics"]["resource_cost"]
    assert resource_cost["transfer_byte_conservation_valid"] is True
    assert resource_cost["transfer_state_counts"].get("PENDING", 0) == 0
    assert resource_cost["gpu_hbm_recovery_reserve_peak_bytes"] > 0
    hbm_stacks = resource_cost["gpu_hbm_account_stack_by_gpu"]
    assert all(item["valid"] for item in hbm_stacks.values())
    for item in hbm_stacks.values():
        final = item["final_accounts"]
        assert sum(final.values()) == item["capacity_bytes"]
        assert final["ACTIVE_PRIMARY_KV"] == 0
        assert final["RECOVERY_DEST_RESERVED"] == 0
        assert final["TRANSFER_STAGING"] == 0
        assert final["UNATTRIBUTED_RESERVE"] == 0
    failed_hbm = [
        item
        for item in hbm_stacks.values()
        if item["final_accounts"]["UNAVAILABLE_CAPACITY"] > 0
    ]
    assert len(failed_hbm) == 1
    assert (
        failed_hbm[0]["final_accounts"]["UNAVAILABLE_CAPACITY"]
        == failed_hbm[0]["capacity_bytes"]
    )
    assert first.payload["metrics"]["policy_effects"]["protection_path_bypasses"]
    failed_pools = [
        value
        for value in resource_cost["peer_hbm_by_gpu"].values()
        if value["failed_unavailable"]
    ]
    assert len(failed_pools) == 1
    assert failed_pools[0]["final_bytes"] == 0
    assert failed_pools[0]["quota_bytes"] == 0
    assert (
        failed_pools[0]["unavailable_bytes"]
        == failed_pools[0]["physical_capacity_bytes"]
    )
    assert all(item["status"] != "PENDING" for item in first.representative["transfers"])
    assert any(
        item["pending_peak_bytes"] > 0
        for item in resource_cost["peer_hbm_by_gpu"].values()
    )
    assert (
        resource_cost["store_dram_by_segment"]["store-0:segment-0"][
            "pending_peak_bytes"
        ]
        > 0
    )
    for transfer in first.representative["transfers"]:
        assert transfer["bytes"] == (
            transfer["transferred_bytes"] + transfer["aborted_bytes"]
        )
    assert any(
        transfer["flow_slice_count"] > 1
        for transfer in first.representative["transfers"]
    )
    remote_recovery = [
        transfer
        for transfer in first.representative["transfers"]
        if transfer["communication_backend"] == "flow_contention"
        and transfer["cause"].startswith("AEGIS_RECOVERY_")
    ]
    if remote_recovery:
        assert resource_cost["gpu_hbm_staging_peak_bytes"] > 0

    rate_capacities = resource_model["rate_resources"]
    rates_by_interval_resource: dict[tuple[int, int, str], list[float]] = {}
    for interval in first.representative["flow_rate_intervals"]:
        for resource_id in interval["path_resource_ids"]:
            key = (interval["start_ns"], interval["end_ns"], resource_id)
            rates_by_interval_resource.setdefault(key, []).append(
                interval["allocated_rate_bytes_per_second"]
            )
    shared = [
        (key, rates)
        for key, rates in rates_by_interval_resource.items()
        if len(rates) > 1
    ]
    assert shared
    for (_, _, resource_id), rates in rates_by_interval_resource.items():
        assert sum(rates) <= rate_capacities[resource_id] + 1e-5
    assert any(
        abs(sum(rates) - rate_capacities[key[2]]) <= 1e-5
        for key, rates in shared
    )

    recovered = [
        item
        for item in first.span_details
        if item["recovery_ready_ns"] is not None
    ]
    assert recovered
    for item in recovered:
        assert (
            item["failure_at_ns"]
            <= item["prompt_recompute_start_ns"]
            <= item["prompt_recompute_complete_ns"]
            <= item["silent_replay_start_ns"]
            <= item["silent_replay_complete_ns"]
            == item["recovery_ready_ns"]
            <= item["resume_decode_start_ns"]
            <= item["completed_ns"]
        )
    events_by_span: dict[str, list[str]] = {}
    for event in first.representative["recovery_events"]:
        events_by_span.setdefault(str(event["span_id"]), []).append(str(event["event"]))
    for item in recovered:
        assert events_by_span[str(item["span_id"])] == [
            "RECOVERY_PLAN",
            "PROMPT_SUFFIX_RECOMPUTE_START",
            "PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
            "SILENT_REPLAY_START",
            "SILENT_REPLAY_COMPLETE",
            "RECOVERY_ATOMIC_ACTIVATION",
        ]


def test_no_failure_recompute_has_no_protection_or_failure() -> None:
    records = _committed_records()
    result = run_study_cell(
        records,
        CellSpec(
            variant=core_variants()[0],
            context_bucket="8k",
            scenario=Scenario.NO_FAILURE,
            seed=7,
            repetition="A",
        ),
    )
    metrics = result.payload["metrics"]
    assert result.payload["failure_schedule"] is None
    assert metrics["failure_impact"] == {
        "active_requests": 0,
        "queued_requests": 0,
        "failed_gpu_count": 0,
    }
    assert metrics["resource_cost"]["peer_hbm_peak_bytes"] == 0
    assert metrics["resource_cost"]["store_dram_peak_bytes"] == 0
    assert result.payload["output_audit"]["duplicate_or_missing_tokens"] == 0


def test_dp2_128k_uses_same_logical_failure_trigger_across_core_systems() -> None:
    records = _committed_records()
    parameters = ModelParameters(dp_count=2)
    for seed in (0, 7):
        schedule = derive_failure_schedule(
            records,
            bucket="128k",
            seed=seed,
            parameters=parameters,
        )
        resolved_times: set[int] = set()
        for variant in core_variants(parameters):
            result = run_study_cell(
                records,
                CellSpec(
                    variant=variant,
                    context_bucket="128k",
                    scenario=Scenario.GPU_FAILURE,
                    seed=seed,
                    repetition="A",
                    failure_schedule=schedule,
                ),
            )
            failure = result.representative["failure_events"][0]
            trigger = failure["logical_trigger"]
            assert trigger["focus_span_id"] == schedule.focus_span_id
            assert trigger["progress_per_mille"] == parameters.failure_progress_per_mille
            assert schedule.focus_span_id in failure["impacted_active_span_ids"]
            resolved_times.add(int(trigger["resolved_at_ns"]))
        # Absolute time is an outcome of each system. Matching is on the frozen
        # logical span/progress trigger, not on an unrelated active request.
        assert len(resolved_times) > 1


def test_failure_aborts_only_unserved_transfer_suffix_and_conserves_bytes() -> None:
    records = _committed_records()
    parameters = ModelParameters(
        peer_bandwidth_bytes_per_second=10_000_000,
        store_bandwidth_bytes_per_second=10_000_000,
        failure_progress_per_mille=500,
    )
    schedule = derive_failure_schedule(
        records,
        bucket="64k",
        seed=2,
        parameters=parameters,
    )
    result = run_study_cell(
        records,
        CellSpec(
            variant=core_variants(parameters)[-1],
            context_bucket="64k",
            scenario=Scenario.GPU_FAILURE,
            seed=2,
            repetition="A",
            failure_schedule=schedule,
        ),
    )
    aborted = [
        transfer
        for transfer in result.representative["transfers"]
        if transfer["status"] == "ABORTED"
    ]
    assert aborted
    assert sum(item["aborted_bytes"] for item in aborted) > 0
    for transfer in aborted:
        assert transfer["terminal_ns"] <= transfer["planned_end_ns"]
        assert transfer["bytes"] == (
            transfer["transferred_bytes"] + transfer["aborted_bytes"]
        )
        for interval in transfer["resource_intervals"]:
            assert interval["start_ns"] <= interval["actual_end_ns"]
            assert interval["actual_end_ns"] <= interval["planned_end_ns"]
    resource_cost = result.payload["metrics"]["resource_cost"]
    assert resource_cost["transfer_state_counts"]["ABORTED"] == len(aborted)
    assert resource_cost["transfer_byte_conservation_valid"] is True


def test_cache_aware_routing_moves_execution_to_peer_cache_without_remote_free_hit() -> None:
    records = _committed_records()
    enabled = run_study_cell(
        records,
        CellSpec(
            variant=core_variants()[-1],
            context_bucket="64k",
            scenario=Scenario.NO_FAILURE,
            seed=0,
            repetition="A",
        ),
    )
    changed = [
        event
        for event in enabled.representative["route_events"]
        if event["selected_gpu_id"] != event["hashed_gpu_id"]
    ]
    assert changed
    aimd_actions = enabled.payload["metrics"]["policy_effects"]["aimd_action_counts"]
    assert aimd_actions["ADDITIVE_INCREASE"] > 0
    assert "MULTIPLICATIVE_DECREASE" not in aimd_actions
    for event in changed:
        assert event["selected_gpu_id"] == event["selected_peer_cache_source_gpu_id"]
        assert event["peer_prefix_tokens_by_gpu"][event["selected_gpu_id"]] == max(
            event["peer_prefix_tokens_by_gpu"].values()
        )

    disabled_variant = next(
        item for item in ablation_variants() if item.variant_id == "no_cache_aware_routing"
    )
    disabled = run_study_cell(
        records,
        CellSpec(
            variant=disabled_variant,
            context_bucket="64k",
            scenario=Scenario.NO_FAILURE,
            seed=0,
            repetition="A",
        ),
    )
    assert all(
        event["selected_gpu_id"] == event["hashed_gpu_id"]
        for event in disabled.representative["route_events"]
    )


def test_two_manager_ablation_keeps_visibility_but_separates_value_bids() -> None:
    records = _committed_records()
    results = {}
    for variant_id in ("full", "two_managers"):
        variant = next(
            item for item in ablation_variants() if item.variant_id == variant_id
        )
        results[variant_id] = run_study_cell(
            records,
            CellSpec(
                variant=variant,
                context_bucket="64k",
                scenario=Scenario.NO_FAILURE,
                seed=0,
                repetition="A",
            ),
        )
    full_effects = results["full"].payload["metrics"]["policy_effects"]
    split_effects = results["two_managers"].payload["metrics"]["policy_effects"]
    assert full_effects["manager_mode"] == "UNIFIED_ADDITIVE_REUSE_RECOVERY_VALUE"
    assert (
        split_effects["manager_mode"]
        == "TWO_INDEPENDENT_VALUE_BIDS_SHARED_DIRECTORY"
    )
    assert all(split_effects["committed_reuse_visibility"].values())
    assert sum(results["two_managers"].payload["metrics"]["cache_reuse_tokens"].values()) > 0
    assert (
        results["full"].payload["metrics"]["pool_audit"]
        != results["two_managers"].payload["metrics"]["pool_audit"]
    )
