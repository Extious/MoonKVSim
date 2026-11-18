from dataclasses import replace

from moonkvsim.aegiskv.current.model import Agent, Config, Invocation
from moonkvsim.aegiskv.current.runtime import CurrentRuntime


def test_zero_slack_ablation_protects_an_otherwise_hidden_branch_earlier():
    agents = (
        Agent("w", "long", (), (Invocation((1,) * 2048, (2,) * 16),), 10_000_000),
        Agent("w", "short", (), (Invocation((3,) * 1024, (4,) * 16),), 1_000_000),
    )
    base = replace(
        Config(),
        hosts=(0, 1, 2),
        layers=2,
        depth=1,
        tp=1,
        prefill_ns_per_token=1000,
        decode_ns_per_token=10_000,
        prediction_latency_ns=0,
    )
    results = {}
    for mode in ("dag", "zero"):
        runtime = CurrentRuntime(replace(base, slack_mode=mode), agents, policy="dram")
        result = runtime.run()
        frontiers = [
            e["frontier"]
            for e in runtime.events
            if e["kind"] == "checkpoint_commit" and e["agent"] == "w/short"
        ]
        results[mode] = result, frontiers
        assert result["output_tokens_exact"] and result["terminal_allocations_zero"]
    # Holding work and resources fixed, removing the hidden branch's Slack
    # should change protection before a timing or output change is possible.
    assert min(results["zero"][1]) == 256
    assert not results["dag"][1] or min(results["dag"][1]) > 256
    assert results["zero"][0]["workflows"] == results["dag"][0]["workflows"]
