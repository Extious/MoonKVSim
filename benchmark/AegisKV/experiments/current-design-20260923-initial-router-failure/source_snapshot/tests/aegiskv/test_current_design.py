from dataclasses import replace

import pytest

from moonkvsim.aegiskv.current.model import Agent, Config, Failure, Invocation
from moonkvsim.aegiskv.current.policy import Adapter, demand, top_blocks
from moonkvsim.aegiskv.current.predictor import ContextRegressor, TrainingExample, features
from moonkvsim.aegiskv.current.runtime import CurrentRuntime
from moonkvsim.aegiskv.current.tracker import Context, Tracker
from moonkvsim.aegiskv.current.workload import mechanism_workload
from moonkvsim.simulation.resource import RateResource


def small(**changes):
    return replace(Config(), layers=8, depth=2, **changes)


def task(name, duration, parents=()):
    return Agent("w", name, parents, (Invocation((1,), (2,)),), duration)


def test_cpm_counts_agent_once_and_preserves_full_unstarted_prior():
    tracker = Tracker(
        (task("a", 10), task("b", 4), task("c", 3, ("a", "b"))), small(slack_guard_ns=1)
    )
    assert tracker.slack(0) == {"w/a": 0, "w/b": 5, "w/c": 0}
    tracker.submit("w/a", 0, 0)
    assert tracker.slack(2)["w/b"] == 3  # b has not started: do not subtract two
    tracker.states["w/a"].finished = True
    assert tracker.slack(2) == {"w/a": 0, "w/b": 0, "w/c": 0}


def test_prediction_timestamp_and_stale_async_publication():
    tracker = Tracker((task("a", 20), task("b", 10)), small())
    tracker.submit("w/a", 0, 3)
    tracker.submit("w/a", 1, 5)
    assert not tracker.publish("w/a", 0, 3, 999)
    assert tracker.publish("w/a", 1, 5, 20)
    assert tracker.slack(8)["w/b"] == 7  # 20 - (8-5) - 10


@pytest.mark.parametrize("value", [None, float("nan"), -1, 0])
def test_any_invalid_prediction_zeros_entire_workflow(value):
    tracker = Tracker((task("a", 20), task("b", 10)), small())
    tracker.submit("w/a", 0, 0)
    tracker.publish("w/a", 0, 0, value)
    assert set(tracker.slack(0).values()) == {0}
    assert tracker.fallback_workflows == {"w"}


def test_expired_estimate_zeros_entire_workflow():
    tracker = Tracker((task("a", 100), task("b", 10)), small(prediction_ttl_ns=5))
    tracker.submit("w/a", 0, 0)
    assert set(tracker.slack(6).values()) == {0}


def test_invalid_dag_is_rejected():
    with pytest.raises(ValueError, match="cycle"):
        Tracker((task("a", 10, ("b",)), task("b", 10, ("a",))), small())
    with pytest.raises(ValueError, match="missing"):
        Tracker((task("a", 10, ("missing",)),), small())


def test_adapter_does_not_grow_without_deferred_demand_and_obeys_ceiling():
    c = small(initial_quota_bytes=100, hbm_cap_bytes=1000, additive_bytes=100, stable_windows=2)
    adapter = Adapter(c, 100)
    assert adapter.update(0, False, False) == (100, 100)
    assert adapter.update(0, False, True) == (100, 200)
    assert adapter.update(0, True, True) == (200, 150)
    assert adapter.update(c.hbm_bytes_per_rank - c.reserve_bytes - 10, False, True)[1] == 10


def test_topk_uses_current_native_counts_and_stable_ties():
    assert top_blocks({(0, 2): 5, (0, 1): 2}, 0, 4, 2) == (2, 1)
    assert top_blocks({}, 0, 4, 2) == (0, 1)
    assert demand(small(), 0, 255, 100) == {0}
    assert demand(small(), 0, 256, 100) == {0, 1}


@pytest.mark.parametrize("policy", ["none", "dram", "aegiskv", "all_dram", "static_hbm"])
def test_paired_recovery_completes_without_leaks_or_duplicate_outputs(policy):
    runtime = CurrentRuntime(
        small(), mechanism_workload(workflows=1), policy=policy, failure=Failure("wf00/slow")
    )
    result = runtime.run()
    assert result["complete"] and result["terminal_allocations_zero"]
    assert result["output_tokens_exact"]
    recovery = result["recoveries"][0]
    assert recovery["rebuild_tokens"] == recovery["durable_tokens"] - recovery["checkpoint_tokens"]
    assert recovery["first_new_token_ns"] >= recovery["admitted_ns"]
    assert recovery["retry_worker"] not in result["failure"]["workers"]
    if policy == "none":
        assert recovery["checkpoint_tokens"] == 0
    else:
        assert recovery["checkpoint_tokens"] > 0
    if policy in {"dram", "all_dram", "none"}:
        assert recovery["hbm_blocks"] == 0


def test_full_dram_and_hbm_models_have_identical_fault_progress_and_rebuild():
    results = [
        CurrentRuntime(
            small(), mechanism_workload(workflows=1), policy=p, failure=Failure("wf00/slow")
        ).run()
        for p in ("dram", "aegiskv")
    ]
    assert results[0]["failure"]["logical_tokens"] == results[1]["failure"]["logical_tokens"]
    assert (
        results[0]["recoveries"][0]["rebuild_tokens"]
        == results[1]["recoveries"][0]["rebuild_tokens"]
    )
    assert results[1]["metrics"]["hbm_adopted_bytes"] > 0
    assert results[1]["metrics"]["restore_bytes"] < results[0]["metrics"]["restore_bytes"]


def test_copy_lag_is_reported_instead_of_clipped_to_256():
    runtime = CurrentRuntime(
        small(network_bytes_per_second=20e6),
        mechanism_workload(workflows=1),
        failure=Failure("wf00/slow"),
    )
    result = runtime.run()
    recovery = result["recoveries"][0]
    assert recovery["checkpoint_tokens"] > 0
    assert recovery["rebuild_tokens"] > 256 and recovery["tail_exceeds_256"]
    assert result["metrics"]["canceled_copy_transferred_bytes"] > 0


def test_tp_manifest_waits_for_slowest_shard():
    c = small()
    runtime = CurrentRuntime(c, mechanism_workload(workflows=1), policy="dram")
    for worker in range(len(c.hosts)):
        runtime.flow_model.resources[f"d2h:{worker}:1"] = RateResource(f"d2h:{worker}:1", 1e6)
    runtime.des.run(until_ns=1_000_000_000)
    # First shard can finish in ms, but rank 1 needs >4 seconds for one chunk.
    assert not [e for e in runtime.events if e["kind"] == "checkpoint_commit"]
    assert any(cp.pending for cp in runtime.checkpoints)
    assert runtime.metrics["checkpoint_bytes"] > 0


def test_host_dram_is_shared_and_host_failure_fences_all_workers():
    c = small(hosts=(0, 0, 1, 1), dram_bytes_per_host=160 * 1024**2)
    runtime = CurrentRuntime(
        c, mechanism_workload(workflows=2), failure=Failure("wf00/slow", scope="host")
    )
    result = runtime.run()
    assert len([name for name in runtime.ledgers if name.startswith("dram:")]) == 2
    assert len(result["failure"]["workers"]) == 2
    assert result["peak_bytes"]["dram:0"] <= c.dram_bytes_per_host
    assert result["peak_bytes"]["dram:1"] <= c.dram_bytes_per_host


def test_zero_hbm_budget_retains_dram_checkpoints():
    c = small(hbm_cap_bytes=0, initial_quota_bytes=0)
    result = CurrentRuntime(c, mechanism_workload(workflows=1), failure=Failure("wf00/slow")).run()
    assert result["recoveries"][0]["checkpoint_tokens"] > 0
    assert result["peak_bytes"]["replica_hbm"] == 0


def test_high_threshold_disables_backups_without_breaking_recovery():
    c = small(tolerance_ns=10**12)
    result = CurrentRuntime(c, mechanism_workload(workflows=1), failure=Failure("wf00/slow")).run()
    assert result["recoveries"][0]["checkpoint_tokens"] == 0
    assert result["peak_bytes"]["replica_dram"] == 0


def test_incompatible_same_agent_prefix_is_not_reused():
    first = Invocation(tuple(range(512)), (1000,) * 128)
    second = Invocation((9,) * 768, (2000,) * 128)
    agent = Agent("w", "a", (), (first, second), 5_000_000_000)
    runtime = CurrentRuntime(small(), (agent,))
    runtime.run()
    submissions = [e for e in runtime.events if e["kind"] == "submit"]
    assert submissions[1]["local_prefix_tokens"] == 0


def test_compatible_history_survives_invocation_completion():
    runtime = CurrentRuntime(small(), mechanism_workload(workflows=1))
    runtime.run()
    submissions = [e for e in runtime.events if e["kind"] == "submit" and e["invocation"] == 1]
    assert any(e["local_prefix_tokens"] > 0 for e in submissions)


def test_sparse_demand_misses_fetch_from_dram_and_do_not_change_attention():
    runtime = CurrentRuntime(
        small(attention="synthetic_sparse", top_k=1),
        mechanism_workload(workflows=1),
        failure=Failure("wf00/slow"),
    )
    result = runtime.run()
    assert result["metrics"]["demand_promoted_blocks"] > 0
    assert result["metrics"]["restore_bytes"] > 0
    assert result["output_tokens_exact"]


def test_predictor_sees_only_submission_context_and_predicts_once_per_call():
    seen = []

    def predictor(context):
        seen.append(context)
        return context.prior_ns

    runtime = CurrentRuntime(small(), mechanism_workload(workflows=1), predictor=predictor)
    result = runtime.run()
    assert len(seen) == len(result["requests"])
    assert all(len(c.previous_durations_ns) == c.completed_calls for c in seen)
    assert not hasattr(seen[0], "future_calls") and not hasattr(seen[0], "actual_remaining_ns")


def test_context_regressor_can_train_serialize_and_reject_workflow_leakage():
    context = Context("m", "r", "task text", 1000, 0, (), (), 0, 1_000_000_000)
    examples = tuple(TrainingExample("train", context, 2_000_000_000) for _ in range(5))
    model = ContextRegressor.fit(examples)
    loaded = ContextRegressor(**model.to_dict())
    assert abs(loaded(context) - 2_000_000_000) < 1_000_000
    assert features(context) == features(replace(context))
    agent = Agent("train", "a", (), (Invocation((1,), (2,)),), 100)
    with pytest.raises(ValueError, match="overlap"):
        CurrentRuntime(small(), (agent,), predictor=model)


def test_deterministic_event_replay():
    runs = [
        CurrentRuntime(small(), mechanism_workload(workflows=1), failure=Failure("wf00/slow"))
        for _ in range(2)
    ]
    assert runs[0].run() == runs[1].run()
    assert runs[0].des.journal.to_jsonl_bytes() == runs[1].des.journal.to_jsonl_bytes()
