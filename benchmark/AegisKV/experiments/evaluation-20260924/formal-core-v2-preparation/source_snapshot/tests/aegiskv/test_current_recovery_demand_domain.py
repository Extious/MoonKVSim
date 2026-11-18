"""Normal/recovery causal selection domains and locally rebuilt KV hits."""

import pytest

from moonkvsim.aegiskv.current.model import Agent, Config, Invocation
from moonkvsim.aegiskv.current.runtime import Checkpoint, CurrentRuntime


def reveal(*, query, end=None, attention="dense", provider=None):
    config = Config(layers=2, depth=1, tp=1, attention=attention)
    invocation = Invocation(tuple(range(1024)), (7,), output_limit_tokens=16)
    agent = Agent("wf", "a", (), (invocation,), 10**9)
    runtime = CurrentRuntime(config, (agent,), demand_provider=provider)
    runtime.des._heap.clear()
    state = runtime.states[agent.key]
    state.call, state.worker = 0, 1
    state.recovering = Checkpoint(agent.key, 999, 0, 1, frontier=512, readers=1)
    state.available = {(1, -512), *((1, b) for b in (0, 1, 2, 3))}
    observed = []

    def require(_state, required, callback):
        if required == {(1, -512)}:
            assert required <= state.available
            observed.append(("metadata-ready", set(required)))
            callback()
        else:
            observed.append(("checkpoint-demand", set(required)))
            # Hold the miss callback: this unit only inspects revelation.

    runtime._require = require
    runtime._layer_step(state, query, end or query + 1, 1, 1800, lambda: None)
    return runtime, observed


@pytest.mark.parametrize("query,expected_hit_ns", [(512, 500), (600, 540)])
def test_dense_includes_local_tail_and_current_query_in_hit_fraction(query, expected_hit_ns):
    runtime, observed = reveal(query=query)
    assert observed[0][0] == "metadata-ready"
    assert observed[1] == ("checkpoint-demand", {(1, b) for b in range(8)})
    assert runtime.metrics["recovery_hit_compute_ns"] == expected_hit_ns
    assert runtime.metrics["recovery_demand_miss_blocks"] == 4


def test_synthetic_selection_occurs_before_checkpoint_domain_filtering():
    runtime, observed = reveal(query=600, attention="synthetic_sparse")
    assert observed[1] == ("checkpoint-demand", {(1, b) for b in (0, 3, 4, 5, 6)})
    assert runtime.metrics["recovery_hit_compute_ns"] == 360


def test_external_trace_can_select_local_self_kv_without_dram_recall():
    observed_domain = []

    def provider(config, invocation, layer, query, history_blocks):
        del invocation, layer
        observed_domain.append(history_blocks)
        return [query // config.block_tokens]

    runtime, observed = reveal(query=512, provider=provider)
    assert observed_domain == [9]
    assert observed[1] == ("checkpoint-demand", set())
    assert runtime.metrics["recovery_hit_compute_ns"] == 900
    assert runtime.metrics["recovery_demand_miss_blocks"] == 0


def test_external_trace_still_rejects_future_kv():
    def provider(config, invocation, layer, query, history_blocks):
        del invocation, layer, history_blocks
        return [query // config.block_tokens + 1]

    with pytest.raises(ValueError, match="causally invisible"):
        reveal(query=512, provider=provider)


def test_batched_forward_normal_and_recovery_provider_domains_match_per_query():
    seen = []

    def provider(config, invocation, layer, query, history_blocks):
        del invocation, layer
        seen.append((query, history_blocks))
        return [query // config.block_tokens]

    runtime, _ = reveal(query=512, end=768, provider=provider)
    recovery_domains = list(seen)
    seen.clear()
    state = runtime.states["wf/a"]
    # The normal _forward_done caller passes ceil(end/block)=12 for this
    # multi-block forward. _demand must clip it separately for each query.
    for query in range(512, 768):
        runtime._demand(state, 1, query, 12)
    assert seen == recovery_domains == [(q, q // 64 + 1) for q in range(512, 768)]
