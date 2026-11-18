from dataclasses import replace

from moonkvsim.aegiskv.current.model import Agent, Config, Invocation
from moonkvsim.aegiskv.current.runtime import CurrentRuntime
from moonkvsim.aegiskv.current.tracker import Tracker


def _pair():
    return (
        Agent("w", "long", (), (Invocation((1,) * 2048, (2,) * 16),), 1),
        Agent("w", "short", (), (Invocation((3,) * 1024, (4,) * 16),), 1),
    )


def test_default_slack_ignores_an_absent_duration_table():
    tracker = Tracker(_pair(), Config())
    assert tracker.slack(0) == tracker.slack(0, durations=None)


def test_oracle_durations_replace_priors_for_unstarted_agents():
    tracker = Tracker(_pair(), Config())
    default = tracker.slack(0)
    oracle = tracker.slack(0, durations={"w/long": 100, "w/short": 10})
    assert default["w/short"] == 0
    assert oracle["w/short"] == 90
    assert oracle["w/long"] == 0


def test_oracle_runtime_rejects_a_mismatched_table():
    agents = _pair()
    config = replace(Config(), hosts=(0, 1), slack_mode="oracle")
    try:
        CurrentRuntime(config, agents, policy="dram", oracle_duration_ns={"w/long": 100})
    except ValueError as error:
        if "match the workload" not in str(error):
            raise
    else:
        raise AssertionError("mismatched oracle durations were accepted")


def test_oracle_slack_changes_which_agent_is_checkpointed():
    agents = _pair()
    base = replace(
        Config(),
        hosts=(0, 1, 2),
        layers=2,
        depth=1,
        tp=1,
        slack_mode="oracle",
        prefill_ns_per_token=1000,
        decode_ns_per_token=10_000,
        prediction_latency_ns=0,
        dram_bytes_per_host=1024**3,
    )
    frontiers = {}
    for label, short, long in (("exposed", 10**9, 10**9), ("hidden", 10**9, 10**12)):
        runtime = CurrentRuntime(
            base,
            agents,
            policy="dram",
            oracle_duration_ns={"w/long": long, "w/short": short},
        )
        result = runtime.run()
        assert result["output_tokens_exact"] and result["terminal_allocations_zero"]
        frontiers[label] = [
            event["frontier"]
            for event in runtime.events
            if event["kind"] == "checkpoint_commit" and event["agent"] == "w/short"
        ]
    assert frontiers["exposed"] and min(frontiers["exposed"]) == 256
    assert not frontiers["hidden"] or min(frontiers["hidden"]) > 256
