import json
from dataclasses import replace
from pathlib import Path

import pytest

from moonkvsim.aegiskv.current.model import Config, Failure
from moonkvsim.aegiskv.current.runtime import (
    EXTERNAL_POLICIES,
    EXTERNAL_POLICY_RULES,
    CurrentRuntime,
)
from moonkvsim.aegiskv.current.workload import mechanism_workload
from tests.aegiskv._external_policy_cases import EXISTING_POLICIES, cases, fingerprint, small

GOLDENS = Path(__file__).with_name("data") / "current_existing_policy_goldens.json"
EXTERNAL = sorted(EXTERNAL_POLICIES)


@pytest.mark.parametrize("name", sorted(cases()))
def test_existing_policies_are_byte_identical_to_pre_external_runtime(name):
    """Summary, event log, DES journal and flow intervals must not change."""
    golden = json.loads(GOLDENS.read_text())["fingerprints"]
    config, agents, failure, kwargs = cases()[name]
    for policy in EXISTING_POLICIES:
        assert fingerprint(config, agents, policy, failure, kwargs) == golden[f"{name}/{policy}"]


def run(policy, config=None, agents=None, failure=Failure("wf00/slow"), **kwargs):
    runtime = CurrentRuntime(
        config or small(),
        agents or mechanism_workload(workflows=1),
        policy=policy,
        failure=failure,
        **kwargs,
    )
    return runtime, runtime.run()


@pytest.mark.parametrize("policy", EXTERNAL)
@pytest.mark.parametrize("name", ["base-f1", "host-scope-budget", "tight-budget", "copy-lag"])
def test_external_policies_complete_without_leaks_or_hbm_copies(policy, name):
    config, agents, failure, kwargs = cases()[name]
    runtime, result = run(policy, config, agents, failure, **kwargs)
    assert result["complete"] and result["terminal_allocations_zero"]
    assert result["output_tokens_exact"]
    assert result["external_policy_rule"] == EXTERNAL_POLICY_RULES[policy]
    assert result["peak_bytes"]["replica_hbm"] == 0
    assert not [e for e in runtime.events if e["kind"] in {"quota", "topk_update"}]
    for row in result["recoveries"]:
        assert row["hbm_blocks"] == 0
        assert row["rebuild_tokens"] == row["durable_tokens"] - row["checkpoint_tokens"]
        assert row["latency_ns"] == row["detection_ns"] + row["queue_ns"] + row["service_ns"]
        assert row["retry_worker"] not in result["failure"]["workers"]


@pytest.mark.parametrize("policy", EXTERNAL)
def test_external_decisions_do_not_read_slack_exposure_or_gain(policy):
    agents = mechanism_workload(workflows=2)
    failure = Failure("wf01/slow")
    oracle = {a.key: 10**9 * (i + 1) for i, a in enumerate(agents)}
    variants = [
        (small(), {}),
        (small(slack_mode="zero"), {}),
        (small(slack_mode="oracle"), {"oracle_duration_ns": oracle}),
        (small(tolerance_ns=10**12, slack_guard_ns=10**11), {}),
        (small(tolerance_ns=0), {"predictor": lambda context: 10**6}),
    ]
    results = []
    for config, kwargs in variants:
        _, result = run(policy, config, agents, failure, **kwargs)
        result.pop("predictor")
        result["metrics"].pop("slack_fallback_observations", None)
        results.append(result)
    assert all(result == results[0] for result in results[1:])


def test_all_dram_still_ranks_by_exposure_under_a_binding_budget():
    """One shared peer host holds a single chunk. Exposure order, not key order, decides it.

    ``a`` and ``b`` are parallel and join at ``j``. Zero slack ties them, so the
    lower key wins. Oracle durations put ``b`` on the critical path and give
    ``a`` enough slack to hide its reconstruction, so ``b`` wins instead.
    """
    from moonkvsim.aegiskv.current.model import Agent, Invocation

    def agent(name, parents=()):
        return Agent(
            "wf",
            name,
            parents,
            (Invocation(tuple(range(256)), tuple(range(64)), text="evidence"),),
            1_000_000_000,
        )

    agents = (agent("a"), agent("b"), agent("j", ("a", "b")))
    config = small(hosts=(0, 0, 1), dram_bytes_per_host=small().checkpoint_bytes(256) * small().tp)
    zero_rt, _ = run("all_dram", replace(config, slack_mode="zero"), agents, None)
    oracle_rt, _ = run(
        "all_dram",
        replace(config, slack_mode="oracle"),
        agents,
        None,
        oracle_duration_ns={"wf/a": 1_000_000_000, "wf/b": 1_100_000_000, "wf/j": 1_000_000_000},
    )

    def first_commit(runtime):
        return next(e["agent"] for e in runtime.events if e["kind"] == "checkpoint_commit")

    assert first_commit(zero_rt) == "wf/a"
    assert first_commit(oracle_rt) == "wf/b"


def test_fixed_holder_and_retry_follow_the_cyclic_worker_ring():
    config = Config(hosts=(0, 0, 1, 1, 2, 2), layers=8, depth=2)
    runtime, result = run(
        "fixed_checkpoint",
        config,
        mechanism_workload(workflows=3),
        Failure("wf00/slow", scope="host"),
    )
    assert runtime.checkpoints
    for cp in runtime.checkpoints:
        # Skip same-host workers; the ring may only skip dead workers otherwise.
        expected = next(
            w
            for step in range(1, 6)
            if config.hosts[w := (cp.source + step) % 6] != config.hosts[cp.source]
        )
        assert cp.peer == expected or expected in result["failure"]["workers"]
    for row in result["recoveries"]:
        ring = [(row["source_worker"] + step) % 6 for step in range(1, 6)]
        alive = [w for w in ring if w not in result["failure"]["workers"]]
        assert row["retry_worker"] == alive[0]


def test_load_aware_holder_uses_queue_busy_then_free_host_dram():
    config = Config(hosts=(0, 1, 2, 3), layers=8, depth=2)
    runtime = CurrentRuntime(config, mechanism_workload(workflows=1), policy="load_aware_checkpoint")
    runtime.busy[1] = "wf00/root"
    runtime.queues[2].append("wf00/fast")
    assert runtime._peer_for(0) == 3
    runtime.queues[3].extend(["wf00/fast", "wf00/slow"])
    assert runtime._peer_for(0) == 1  # busy (1) beats a queue of one plus... ties -> DRAM, id
    runtime.ledgers["dram:2"]._accounts["FREE"] -= 1
    runtime.ledgers["dram:2"]._accounts["hold"] = 1
    runtime.queues[1].clear()
    runtime.busy[1] = None
    assert runtime._peer_for(0) == 1
    runtime.busy[1] = "wf00/root"
    assert runtime._peer_for(0) == 1  # 1 and 2 tie on load; 1 has more free DRAM
    runtime.ledgers["dram:1"]._accounts["FREE"] -= 2
    runtime.ledgers["dram:1"]._accounts["hold"] = 2
    assert runtime._peer_for(0) == 2
    # Worker 0 is idle on another host, so it beats busy worker 1. Worker 2 is the source.
    assert runtime._peer_for(2) == 0


def test_load_aware_and_fixed_never_place_a_holder_on_the_execution_host():
    config = Config(hosts=(0, 0, 1, 1), layers=8, depth=2)
    for policy in ("load_aware_checkpoint", "fixed_checkpoint", "tail_shadow"):
        runtime, _ = run(policy, config, mechanism_workload(workflows=3), None)
        assert runtime.checkpoints
        assert all(config.hosts[cp.source] != config.hosts[cp.peer] for cp in runtime.checkpoints)


def test_tail_shadow_keeps_one_chunk_and_rebuilds_everything_else():
    config = small()
    _, restart = run("none", config)
    runtime, shadow = run("tail_shadow", config)
    z = config.checkpoint_tokens
    row = shadow["recoveries"][0]
    assert row["checkpoint_tokens"] == z
    assert row["shadow_frontier_tokens"] - row["shadow_base_tokens"] == z
    assert row["shadow_frontier_tokens"] <= row["durable_tokens"]
    assert row["rebuild_tokens"] == row["durable_tokens"] - z
    assert shadow["metrics"]["replayed_tokens"] == restart["metrics"]["replayed_tokens"] - z
    assert shadow["metrics"]["restore_bytes"] == config.prefix_bytes(z) * config.tp
    commits = [e for e in runtime.events if e["kind"] == "checkpoint_commit"]
    assert commits and all(e["frontier"] - e["base"] == z for e in commits)
    active = len(runtime.states)
    assert shadow["peak_bytes"]["replica_dram"] <= 2 * active * config.prefix_bytes(z) * config.tp


def test_tail_shadow_install_waits_for_a_slow_chunk_transfer():
    config = small(h2d_bytes_per_second=2e6)
    _, shadow = run("tail_shadow", config)
    row = shadow["recoveries"][0]
    assert row["shadow_installed_ns"] > row["shadow_prefix_done_ns"]
    assert shadow["output_tokens_exact"]


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError, match="unknown"):
        CurrentRuntime(small(), mechanism_workload(workflows=1), policy="lumen")
