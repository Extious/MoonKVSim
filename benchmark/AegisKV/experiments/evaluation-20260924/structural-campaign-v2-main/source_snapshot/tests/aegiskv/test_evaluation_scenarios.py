import json
from collections import Counter
from dataclasses import replace
from math import ceil

import pytest

from moonkvsim.aegiskv.current.model import Agent, Config, Failure, Invocation
from moonkvsim.aegiskv.current.runtime import CurrentRuntime
from moonkvsim.aegiskv.current.tracker import Tracker
from moonkvsim.aegiskv.evaluation_scenarios import (
    ROLE_PRIORS_NS,
    SCENARIO_NAMES,
    SyntheticPhaseDemand,
    build_evaluation_scenario,
    describe_failure,
    resolve_stage_failure,
)


@pytest.mark.parametrize("name", SCENARIO_NAMES)
def test_scenarios_have_valid_dags_compatible_histories_and_honest_metadata(name):
    scenario = build_evaluation_scenario(name, model="fixture-model", seed=17)
    Tracker(scenario.agents, Config())  # Checks cycles, missing parents and duplicate IDs.
    assert len(scenario.agents) == 32
    assert set(Counter(agent.workflow for agent in scenario.agents).values()) == {4}
    for agent in scenario.agents:
        assert agent.prior_ns == ROLE_PRIORS_NS[agent.role]
        for ordinal, call in enumerate(agent.calls):
            assert call.model == "fixture-model" and len(call.tokens) <= 40_960
            assert len(call.output) <= call.output_limit_tokens == 16_384
            assert len(call.prompt) + call.output_limit_tokens <= 40_960
            assert not call.text  # Do not synthesize semantic-predictor evidence.
            if ordinal:
                previous = agent.calls[ordinal - 1].tokens
                assert call.prompt[: len(previous)] == previous
                assert len(call.prompt) - len(previous) == 512
    for key, failure in scenario.failures.items():
        descriptor = describe_failure(scenario.agents, failure)
        assert descriptor["phase"] == key.split(".")[1]
        assert (
            descriptor["logical_trigger_tokens"] > descriptor["potentially_reusable_history_tokens"]
        )
        assert descriptor["logical_trigger_tokens"] == ceil(
            failure.progress * descriptor["total_tokens"]
        )
    metadata = json.loads(json.dumps(scenario.metadata))
    assert metadata["evidence_class"] == "constructed_intervention"
    assert not metadata["observed_trace"] and not metadata["native_model_demand"]
    assert metadata["workflow_repetitions"] == 1


@pytest.mark.parametrize("count", (8, 32, 128))
def test_scale_is_unique_workflows_within_context_bound(count):
    scenario = build_evaluation_scenario("forkjoin_skew", model="model", workflows=count)
    assert len({agent.workflow for agent in scenario.agents}) == count
    assert len({agent.key for agent in scenario.agents}) == count * 4
    assert scenario.metadata["invocation_count"] == count * 6
    assert scenario.metadata["maximum_context_tokens"] <= 40_960


def test_seed_reproducibility_role_priors_and_balanced_work():
    a = build_evaluation_scenario("forkjoin_balanced", model="one", seed=2)
    b = build_evaluation_scenario("forkjoin_balanced", model="one", seed=2)
    c = build_evaluation_scenario("forkjoin_balanced", model="two", seed=3)
    assert a == b and a.agents != c.agents
    assert [(x.role, x.prior_ns) for x in a.agents] == [(x.role, x.prior_ns) for x in c.agents]
    for offset in range(0, len(a.agents), 4):
        left, right = a.agents[offset + 1 : offset + 3]
        assert [len(call.tokens) for call in left.calls] == [
            len(call.tokens) for call in right.calls
        ]
        assert left.calls[0].prompt != right.calls[0].prompt


def test_stage_resolution_does_not_place_followup_failure_inside_reusable_history():
    first = Invocation(tuple(range(10)), (10, 11))
    second = Invocation((*first.tokens, 12, 13, 14), (15, 16, 17, 18))
    agent = Agent("w", "a", (), (first, second), 100)
    for phase in ("prefill", "decode"):
        fault = resolve_stage_failure((agent,), agent=agent.key, invocation=1, phase=phase)
        assert describe_failure((agent,), fault)["phase"] == phase
    with pytest.raises(ValueError, match="reusable history"):
        describe_failure((agent,), Failure(agent.key, invocation=1, progress=0.2))
    with pytest.raises(ValueError, match="invocation"):
        resolve_stage_failure((agent,), agent=agent.key, invocation=2, phase="decode")
    with pytest.raises(ValueError, match="phase"):
        resolve_stage_failure((agent,), agent=agent.key, invocation=0, phase="postfill")
    with pytest.raises(ValueError, match="exactly one"):
        describe_failure((agent,), Failure("w/absent"))


def test_short_phases_and_rounding_cannot_silently_target_completion():
    tiny = Agent("w", "a", (), (Invocation((1,), (2,)),), 100)
    with pytest.raises(ValueError, match="no interior"):
        resolve_stage_failure((tiny,), agent=tiny.key, invocation=0, phase="decode")
    with pytest.raises(ValueError, match="completion"):
        describe_failure((tiny,), Failure(tiny.key, invocation=0, progress=0.99))


def test_phase_demand_is_causal_and_changes_without_future_tokens():
    provider = SyntheticPhaseDemand()
    config = Config(attention="synthetic_sparse")
    first = Invocation((1,), (2,))
    other = Invocation((50, 51, 52), tuple(range(100)))
    for query in (0, 1, 63, 64, 1000, 2048, 4096):
        blocks = query // config.block_tokens + 100
        selected = provider(config, first, 0, query, blocks)
        assert selected == provider(config, other, 0, query, blocks)
        assert selected and min(selected) >= 0 and max(selected) <= query // config.block_tokens
        assert len(selected) <= config.synthetic_selected_blocks + 1
    before = set(provider(config, first, 0, 4095, 128))
    after = set(provider(config, first, 0, 4096, 128))
    assert len(before - after) >= provider.hot_blocks
    with pytest.raises(ValueError, match="synthetic_sparse"):
        provider(Config(), first, 0, 100, 10)


def _fast_config(**changes):
    return replace(
        Config(),
        layers=1,
        depth=1,
        tp=1,
        kv_bytes_per_token_per_layer_rank=2,
        prefill_ns_per_token=1000,
        decode_ns_per_token=4000,
        control_window_ns=10_000_000,
        max_time_ns=10_000_000_000,
        **changes,
    )


@pytest.mark.parametrize("phase", ("prefill", "decode"))
def test_runtime_hits_exact_followup_fault_in_each_phase(phase):
    scenario = build_evaluation_scenario("history_reuse", model="fixture", seed=2)
    # One whole workflow is sufficient for an interface smoke test; campaign
    # scale remains 8/32/128. No mutation or shortened calls are needed.
    agents = scenario.agents[:4]
    fault = scenario.failures[f"left.{phase}"]
    result = CurrentRuntime(_fast_config(), agents, policy="none", failure=fault).run()
    assert result["complete"] and result["output_tokens_exact"]
    assert result["failure"]["invocation"] == 1
    assert (
        result["failure"]["logical_tokens"]
        == describe_failure(agents, fault)["logical_trigger_tokens"]
    )


def test_long_decode_provider_exercises_repeated_checkpoint_updates():
    scenario = build_evaluation_scenario("long_decode_drift", model="fixture", seed=2)
    config = _fast_config(attention="synthetic_sparse")
    scenario.validate_config(config)
    result = CurrentRuntime(
        config,
        scenario.agents[:4],
        policy="all_dram",
        demand_provider=scenario.demand_provider,
    ).run()
    assert result["complete"] and result["terminal_allocations_zero"]
    assert result["metrics"]["checkpoint_commits"] > 16
    assert result["metrics"]["count_query_block_updates"] > 0
    assert result["attention_demand_provider"] == scenario.demand_provider.name


def test_shared_host_failure_has_real_covictims_without_forcing_worker_assignment():
    scenario = build_evaluation_scenario("shared_host", model="fixture", seed=2)
    config = _fast_config(hosts=(0, 0, 1, 1))
    scenario.validate_config(config)
    result = CurrentRuntime(
        config, scenario.agents, policy="none", failure=scenario.failures["left.decode"]
    ).run()
    assert result["complete"] and result["output_tokens_exact"]
    assert len(result["failure"]["workers"]) == 2
    assert len(result["recoveries"]) >= 2
    assert len({row["source_worker"] for row in result["recoveries"]}) == 2
    with pytest.raises(ValueError, match="multiple workers"):
        scenario.validate_config(Config())


@pytest.mark.parametrize(
    "kwargs",
    (
        {"workflows": 1},
        {"seed": True},
        {"max_context_tokens": 50_000},
        {"max_context_tokens": 1024},
        {"release_interval_ns": -1},
    ),
)
def test_invalid_scale_or_hidden_truncation_is_rejected(kwargs):
    with pytest.raises(ValueError):
        build_evaluation_scenario("forkjoin_skew", model="fixture", **kwargs)
