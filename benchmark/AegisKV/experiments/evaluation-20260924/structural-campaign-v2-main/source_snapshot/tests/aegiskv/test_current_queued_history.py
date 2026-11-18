"""Failure recovery of a compatible continuation that is waiting in a DP queue."""

from dataclasses import replace

import pytest

from moonkvsim.aegiskv.current.model import Agent, Config, Failure, Invocation
from moonkvsim.aegiskv.current.runtime import CurrentRuntime


class Observed(CurrentRuntime):
    def _fail(self, target):
        history = self.states["a/history"]
        cp = history.checkpoint
        self.history_at_fault = dict(
            call=history.call,
            worker=history.worker,
            durable=history.durable,
            queued=history.spec.key in self.queues[history.worker],
            busy=self.busy[history.worker],
            frontier=cp.frontier if cp else 0,
            peer=cp.peer if cp else None,
            counts=cp.counts.copy() if cp else {},
            live_counts=history.counts.copy(),
        )
        super()._fail(target)
        self.history_after_fault = dict(
            frontier=history.recovering.frontier if history.recovering else 0,
            readers=history.recovering.readers if history.recovering else 0,
        )
        self.lost_live_counts = history.counts.copy()
        self.lost_snapshots = dict(history.count_snapshots)

    def _restore(self, state):
        super()._restore(state)
        if state.spec.key == "a/history":
            self.restored_history_counts = state.counts.copy()


def run_case(*, tp=1, policy="dram", scope="worker", sparse_eos=False, unpublished=False):
    config = Config(
        hosts=(0, 1) if scope == "worker" else (0, 0, 1),
        tp=tp,
        layers=2,
        depth=1,
        decode_ns_per_token=1_000_000,
        initial_quota_bytes=0 if policy != "aegiskv" else 16 * 2**20,
        hbm_cap_bytes=0 if policy != "aegiskv" else 256 * 2**20,
    )
    first = Invocation(tuple(range(512)), tuple(range(900, 908)), output_limit_tokens=8)
    second = Invocation(first.tokens + (10,) * 128, (11,) * 8, output_limit_tokens=8)
    calls = (first, second)
    if sparse_eos:
        second = Invocation((*first.tokens, 10), (11,) * 8, output_limit_tokens=8)
        calls = (
            first,
            second,
            Invocation(second.tokens + (12,) * 32, (13,) * 8, output_limit_tokens=8),
        )
        config = replace(config, attention="synthetic_sparse", h2d_bytes_per_second=1e6)
    if unpublished:
        config = replace(config, d2h_bytes_per_second=1e6)
    blocker = Invocation(
        (1,) * 64, (2,) * (64 if scope == "worker" else 512), output_limit_tokens=512
    )
    agents = [
        Agent("a", "history", (), calls, 10**10),
        Agent("b", "blocker", (), (blocker,), 10**10),
    ]
    if scope == "host":
        agents.append(Agent("d", "survivor", (), (blocker,), 10**10))
    victim = Invocation(tuple(range(1024)), (3,) * 8, output_limit_tokens=8)
    agents.append(Agent("c", "victim", (), (victim,), 10**10, release_ns=50_000_000))
    runtime = Observed(
        config,
        tuple(agents),
        policy=policy,
        failure=Failure("c/victim", 0, (256 - 0.5) / 1032, scope),
        demand_provider=(lambda c, inv, layer, query, blocks: (0,)) if sparse_eos else None,
    )
    result = runtime.run()
    return runtime, result


@pytest.mark.parametrize("tp,policy", [(1, "dram"), (2, "dram"), (2, "aegiskv"), (1, "none")])
def test_failed_worker_preserves_queued_continuation_checkpoint(tp, policy):
    runtime, result = run_case(tp=tp, policy=policy)
    before = runtime.history_at_fault
    assert before["queued"] and before["call"] == 1 and before["durable"] == 520
    assert before["busy"] == "c/victim"
    assert before["frontier"] == (0 if policy == "none" else 512)
    history = result["history_restores"]
    assert len(history) == 1 and history[0]["agent"] == "a/history"
    assert history[0]["kind"] == "queued_history"
    assert history[0]["checkpoint_tokens"] == before["frontier"]
    assert history[0]["rebuild_tokens"] == 520 - before["frontier"]
    assert {r["agent"] for r in result["recoveries"]} == {"c/victim"}
    if policy != "none":
        assert runtime.history_after_fault == dict(frontier=512, readers=1)
        assert runtime.restored_history_counts == before["counts"]
        assert history[0]["retry_worker"] == before["peer"]
    assert result["oracle_reservation_count"] == 0 and result["output_tokens_exact"]
    assert result["terminal_allocations_zero"] and not runtime.groups
    assert all(cp.readers == 0 for cp in runtime.checkpoints)
    assert all(s.recovering is None for s in runtime.states.values())
    assert not runtime.lost_live_counts and not runtime.lost_snapshots
    assert len([r for r in result["requests"] if r["agent"] == "a/history"]) == 2
    if policy == "aegiskv":
        assert result["metrics"]["hbm_adopted_bytes"] > 0


def test_host_failure_keeps_queued_history_separate_from_busy_covictims():
    runtime, result = run_case(tp=2, scope="host")
    assert result["failure"]["workers"] == [0, 1]
    assert {r["agent"] for r in result["recoveries"]} == {"c/victim", "b/blocker"}
    assert {r["agent"] for r in result["history_restores"]} == {"a/history"}
    history = result["history_restores"][0]
    assert history["checkpoint_tokens"] == 512 and history["retry_worker"] == 2
    assert runtime.history_after_fault == dict(frontier=512, readers=1)
    assert result["output_tokens_exact"] and result["terminal_allocations_zero"]


def test_queued_history_sparse_eos_cleanup_allows_the_next_call():
    runtime, result = run_case(sparse_eos=True)
    history = result["history_restores"][0]
    assert history["checkpoint_tokens"] == 512
    assert "restore_canceled_at_eos_ns" in history
    calls = [r for r in result["requests"] if r["agent"] == "a/history"]
    assert [r["invocation"] for r in calls] == [0, 1, 2]
    assert calls[1]["finish_ns"] == history["restore_canceled_at_eos_ns"]
    assert result["output_tokens_exact"] and result["terminal_allocations_zero"]
    assert all(cp.readers == 0 for cp in runtime.checkpoints)


def test_unpublished_queued_history_copy_is_not_recovered_or_used_for_counters():
    runtime, result = run_case(unpublished=True)
    assert runtime.history_at_fault["frontier"] == 0
    assert runtime.history_at_fault["live_counts"]
    assert not runtime.lost_live_counts and not runtime.lost_snapshots
    history = result["history_restores"][0]
    assert history["checkpoint_tokens"] == 0 and history["rebuild_tokens"] == 520
    assert result["metrics"]["canceled_copy_transferred_bytes"] > 0
    assert result["output_tokens_exact"] and result["terminal_allocations_zero"]


def test_displaced_first_call_wakes_its_other_idle_destination():
    config = Config(
        hosts=(0, 1, 2),
        layers=2,
        depth=1,
        tp=1,
        decode_ns_per_token=1_000_000,
        hbm_cap_bytes=0,
        initial_quota_bytes=0,
    )
    victim = Invocation(tuple(range(1024)), (1,) * 8, output_limit_tokens=8)
    blocker = Invocation((2,) * 64, (3,) * 512, output_limit_tokens=512)
    short = Invocation((4,) * 64, (5,) * 64, output_limit_tokens=64)
    fresh = Invocation((6,) * 64, (7,) * 8, output_limit_tokens=8)
    agents = (
        Agent("v", "victim", (), (victim,), 10**10),
        Agent("b", "blocker", (), (blocker,), 10**10),
        Agent("s", "short", (), (short,), 10**10),
        Agent("f", "fresh", (), (fresh,), 10**10, release_ns=50_000_000),
        Agent("q", "other", (), (fresh,), 10**10, release_ns=51_000_000),
    )

    class Admissions(CurrentRuntime):
        def _admit(self, worker):
            before = self.busy.get(worker)
            super()._admit(worker)
            if before is None and self.busy.get(worker) == "f/fresh":
                self.fresh_admitted = self.des.now_ns

    runtime = Admissions(
        config, agents, policy="dram", failure=Failure("v/victim", 0, (848 - 0.5) / 1032)
    )
    result = runtime.run()
    assert result["failure"]["time_ns"] == 84_800_000
    assert runtime.fresh_admitted == 85_800_000
    assert next(r["worker"] for r in result["requests"] if r["agent"] == "f/fresh") == 2
    assert result["history_restores"] == []
    assert result["output_tokens_exact"] and result["terminal_allocations_zero"]
