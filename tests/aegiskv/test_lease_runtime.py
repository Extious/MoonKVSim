"""End-to-end invariants of the current Algorithm 2/3 adapter."""

from copy import deepcopy
from dataclasses import replace
import importlib.util
from pathlib import Path

from moonkvsim.aegiskv.experiment import FailureEventSchedule, FailureSchedule, ModelParameters
from moonkvsim.aegiskv.lease_experiment import LeaseConfig, LeaseRuntime
from moonkvsim.aegiskv.mechanism_experiment import mechanism_variant
from tests.aegiskv.test_experiment import _single_exact_token_record


def test_same_agent_revisit_full_copy_ack_and_live_idle_aimd_heartbeat():
    path = (
        Path(__file__).resolve().parents[2]
        / "benchmark/AegisKV/experiments/scripts/run_agent_lease_mechanisms.py"
    )
    spec = importlib.util.spec_from_file_location("lease_runner_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    record = deepcopy(_single_exact_token_record())
    record["parent_span_ids"] = []
    records = mod.revisit_records([record], rounds=2)
    assert records[0]["agent_id"] == records[1]["agent_id"]
    parameters = ModelParameters(runtime_semantics="shared_prefix_v3", policy_chunk_tokens=64)
    results = {}
    for system in ("mooncake", "dram", "aegis"):
        runtime = LeaseRuntime(
            system=system,
            mechanism_config=LeaseConfig(),
            records=records,
            variant=replace(mechanism_variant(system, parameters), suite="agent-sublease-test"),
            context_bucket="96k",
            seed=0,
            failure_schedule=None,
            workflow_concurrency=1,
        )
        result = runtime.run()
        assert result.payload["status"] == "PASS"
        assert result.payload["output_audit"]["duplicate_or_missing_tokens"] == 0
        m = result.representative["mechanism"]
        admissions = {
            r["spec"]["request_id"]: r["route_history"][0]["timestamp_ns"]
            for r in result.representative["continuous_batch_scheduler"]["requests"]
        }
        get_starts = [
            e for e in result.representative["foreground_store_events"]
            if e["event"] == "FOREGROUND_STORE_GET_START"
        ]
        assert get_starts  # The second round exercises the actual Store path.
        assert all(e["timestamp_ns"] >= admissions[e["span_id"]] for e in get_starts)
        assert m["foreground_connector_events"]
        for target in runtime.continuous_batch_driver._targets.values():
            assert not target.bridge.scheduler._external_page_reservations
            assert not target.bridge.scheduler._external_kv_waiters
        assert [x["round"] for x in m["agent_lifecycle"]] == [1, 2]
        if system != "mooncake":
            commits = sum(len(p.entries) for p in runtime.store_pools.values())
            assert commits > 2  # ACK drains beyond the old two-chunk group.
        if system == "aegis":
            assert all(x["observation"]["valid"] for x in m["foreground_budget"])
            assert any(x["applied_reason"] == "increase" for x in m["foreground_budget"])
        results[system] = result
    assert results["dram"].payload["metrics"]["cache_reuse_tokens"]["store_dram"] > 0


def test_queue_owned_connector_keeps_single_pass_failure_recovery_output_exact():
    record = deepcopy(_single_exact_token_record())
    record["parent_span_ids"] = []
    parameters = ModelParameters(
        runtime_semantics="shared_prefix_v3", policy_chunk_tokens=64,
        failure_progress_per_mille=800, gpu_recovery_time_ns=100_000_000,
    )
    for system in ("mooncake", "dram", "aegis"):
        def runtime(schedule):
            return LeaseRuntime(
                system=system, mechanism_config=LeaseConfig(), records=[record],
                variant=mechanism_variant(system, parameters), context_bucket="96k",
                seed=0, failure_schedule=schedule, workflow_concurrency=1,
            )
        control = runtime(None).run()
        reference = control.span_details[0]
        schedule = FailureSchedule((FailureEventSchedule(
            failure_id="queue-owned-single-pass", event_index=0, bucket="96k", seed=0,
            focus_span_id=record["span_id"], target_gpu_id=reference["gpu_id"],
            reference_at_ns=reference["completed_ns"] * 800 // 1000,
            target_workload_progress_per_mille=500,
            reference_completed_workflow_count=0, reference_workflow_count=1,
            detection_delay_ns=0, trigger_progress_per_mille=800,
            gpu_recovery_time_ns=100_000_000,
            selection_scope="single_pass_connector_regression",
        ),), selection_scope="single_pass_connector_regression")
        failed = runtime(schedule)
        result = failed.run()
        assert len(result.representative["failure_events"]) == 1
        audit = result.payload["output_audit"]
        assert audit["expected_output_tokens"] == audit["external_output_tokens"]
        assert audit["duplicate_or_missing_tokens"] == audit["stale_route_output_count"] == 0
        for target in failed.continuous_batch_driver._targets.values():
            assert not target.bridge.scheduler._external_page_reservations
            assert not target.bridge.scheduler._external_kv_waiters
