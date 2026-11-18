from dataclasses import replace

import pytest

from moonkvsim.aegiskv.current.model import Agent, Config, Failure, Invocation
from moonkvsim.aegiskv.current.runtime import CurrentRuntime


def sparse(config, invocation, layer, query, history_blocks):
    return (0,)


class Observed(CurrentRuntime):
    def __init__(self, *args, **kwargs):
        self.eos = {}
        self.stale_callbacks_checked = 0
        super().__init__(*args, **kwargs)

    def _complete(self, state):
        key = state.spec.key, state.call
        self.eos.setdefault(key, self.des.now_ns)
        stale = [g.done for g in self.groups.values() if g.owner.startswith("restore:")]
        super()._complete(state)
        before = (
            state.call,
            state.epoch,
            state.computed,
            state.worker,
            set(state.available),
        )
        for callback in stale:
            callback()
            self.stale_callbacks_checked += 1
        assert before == (
            state.call,
            state.epoch,
            state.computed,
            state.worker,
            state.available,
        )


def fixture(policy, *, second=False, incompatible=False, child=False, dense=False):
    config = replace(
        Config(),
        hosts=(0, 1, 2),
        tp=1,
        layers=2,
        depth=2,
        top_k=1,
        h2d_bytes_per_second=10e6,
        decode_ns_per_token=10_000,
        max_time_ns=2_000_000_000,
        attention="dense" if dense else "synthetic_sparse",
        synthetic_selected_blocks=1,
    )
    first = Invocation(tuple(range(1024)), tuple(range(32)), output_limit_tokens=32)
    calls = (first,)
    if second:
        calls += (
            Invocation(
                ((12345,) * 1088 if incompatible else first.tokens + (99,) * 32),
                tuple(range(16)),
                output_limit_tokens=16,
            ),
        )
    agents = (Agent("w", "a", (), calls, 1_000_000_000),)
    if child:
        agents += (
            Agent(
                "w",
                "child",
                ("a",),
                (Invocation((1,) * 64, (2,) * 8, output_limit_tokens=8),),
                1_000_000_000,
            ),
        )
    return Observed(
        config,
        agents,
        policy=policy,
        failure=Failure("w/a", invocation=0, progress=0.99),
        demand_provider=None if dense else sparse,
    )


def assert_conservation(runtime, result):
    assert result["complete"] and result["output_tokens_exact"]
    assert result["terminal_allocations_zero"]
    assert not runtime.groups and not runtime.flow_model.flows
    assert all(cp.readers == 0 and cp.frontier == 0 for cp in runtime.checkpoints)
    physical = sum(row.transferred_bytes for row in runtime.flow_model.intervals)
    accounted = sum(runtime.metrics[f"{kind}_bytes"] for kind in ("checkpoint", "hot", "restore"))
    accounted += runtime.metrics["canceled_copy_transferred_bytes"]
    assert abs(physical - accounted) < 1e-5


@pytest.mark.parametrize("policy", ["dram", "aegiskv"])
def test_eos_completes_and_cancels_cold_copy_without_draining(policy):
    runtime = fixture(policy)
    result = runtime.run()
    recovery = result["recoveries"][0]
    assert recovery["first_new_token_ns"] < runtime.eos["w/a", 0]
    assert result["requests"][0]["finish_ns"] == runtime.eos["w/a", 0]
    assert recovery["restore_canceled_at_eos_ns"] == runtime.eos["w/a", 0]
    assert "restore_done_ns" not in recovery
    assert runtime.stale_callbacks_checked > 0
    assert_conservation(runtime, result)


@pytest.mark.parametrize("incompatible", [False, True])
def test_next_call_starts_at_eos_without_reusing_incomplete_history(incompatible):
    runtime = fixture("aegiskv", second=True, incompatible=incompatible)
    result = runtime.run()
    first, second = result["requests"]
    assert first["finish_ns"] == second["submit_ns"] == runtime.eos["w/a", 0]
    submission = next(e for e in runtime.events if e["kind"] == "submit" and e["invocation"] == 1)
    assert submission["local_prefix_tokens"] == 0
    assert len(runtime.states["w/a"].durations) == 2
    assert runtime.stale_callbacks_checked > 0
    assert_conservation(runtime, result)


def test_dependent_agent_is_released_at_eos_and_runs_on_surviving_worker():
    runtime = fixture("aegiskv", child=True)
    result = runtime.run()
    child = next(row for row in result["requests"] if row["agent"] == "w/child")
    assert child["submit_ns"] == runtime.eos["w/a", 0]
    assert child["worker"] not in result["failure"]["workers"]
    assert_conservation(runtime, result)


def test_queued_work_on_retry_worker_is_admitted_after_eos():
    template = fixture("aegiskv")
    extra = tuple(
        Agent(
            name,
            "job",
            (),
            (Invocation((1,), (2,) * 1000, output_limit_tokens=1000),),
            1_000_000_000,
            release_ns=105_000_000,
        )
        for name in ("other1", "other2")
    )
    runtime = Observed(
        template.config,
        (template.states["w/a"].spec, *extra),
        policy="aegiskv",
        failure=template.failure,
        demand_provider=sparse,
    )
    result = runtime.run()
    queued = next(row for row in result["requests"] if row["agent"] == "other2/job")
    assert queued["worker"] == result["recoveries"][0]["retry_worker"]
    assert queued["submit_ns"] < runtime.eos["w/a", 0]
    assert runtime.eos["w/a", 0] < queued["finish_ns"] < 150_000_000
    assert_conservation(runtime, result)


@pytest.mark.parametrize("policy", ["dram", "aegiskv"])
def test_dense_completion_and_history_behavior_are_unchanged(policy):
    runtime = fixture(policy, second=True, dense=True)
    result = runtime.run()
    first, _second = result["requests"]
    assert first["finish_ns"] == runtime.eos["w/a", 0]
    assert "restore_canceled_at_eos_ns" not in result["recoveries"][0]
    assert result["recoveries"][0]["restore_done_ns"] < first["finish_ns"]
    submission = next(e for e in runtime.events if e["kind"] == "submit" and e["invocation"] == 1)
    assert submission["local_prefix_tokens"] == 1056
    assert_conservation(runtime, result)


def test_canceling_resumed_flow_counts_only_service_since_that_resume():
    runtime = fixture("dram")
    runtime.des._heap.clear()
    runtime._callbacks.clear()
    group = runtime._start_copy(
        owner="test-resume",
        source=None,
        target=1,
        size=10_000_000,
        remaining=(5_000_000.0,),
        cause="restore",
        host=1,
        paths=[("h2d:1:0",)],
        done=lambda: None,
    )
    runtime.des.run(until_ns=200_000_000)
    runtime._cancel_group(group)
    assert runtime.metrics["canceled_copy_transferred_bytes"] == 2_000_000
    assert sum(r.transferred_bytes for r in runtime.flow_model.intervals) == 2_000_000
