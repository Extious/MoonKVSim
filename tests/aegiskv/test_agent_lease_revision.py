from copy import deepcopy

import pytest

from moonkvsim.aegiskv.agent_lease import AgentLeasePolicy
from moonkvsim.aegiskv.lease_value import RecoveryAgent, RecoveryNode, WorkflowRecoveryValue
from moonkvsim.aegiskv.lease_value import execution_branches


def test_same_agent_parallel_branches_preserve_separate_state_across_rounds():
    nodes = (
        RecoveryNode("a0", (), 1),
        RecoveryNode("b0", (), 1),
        RecoveryNode("j0", ("a0", "b0"), 1),
        RecoveryNode("a1", ("j0",), 1),
        RecoveryNode("b1", ("j0",), 1),
        RecoveryNode("j1", ("a1", "b1"), 1),
    )
    branches = execution_branches({"w": nodes}, {n.key: "same-Agent" for n in nodes})
    assert branches == {"a0": 0, "b0": 1, "j0": 0, "a1": 0, "b1": 1, "j1": 0}


class Values:
    def __init__(self, gains, rounds=None):
        self.gains = gains
        self.rounds = rounds or {a: 1 for v in gains.values() for a in v}
        self.version = 0

    def shares(self, resident, key):
        return self.gains.get(key, {})

    def cost(self, resident):
        return 1000 - sum(sum(self.gains[k].values()) for k in resident)

    def stamp(self, key, resident):
        return (self.version, tuple(sorted(self.rounds.items())))


def add(policy, key, values):
    p = policy.plan(key, values, pinned=set())
    assert p.status in {"ADMIT", "REPLACE"}
    policy.apply_releases(p)
    policy.commit(key, values)
    policy.check()
    return p


def test_free_zero_gain_prefix_is_admitted_but_not_zero_net_replacement():
    p = AgentLeasePolicy(2)
    p.register("root", None, 1)
    p.register("tail", "root", 1)
    p.register("other", None, 1)
    v = Values({"root": {"a": 0}, "tail": {"a": 10}, "other": {"b": 10}})
    add(p, "root", v)
    add(p, "tail", v)
    previous = deepcopy(p.credits)
    plan = p.plan("other", v, pinned=set())
    assert plan.status == "BYPASS" and plan.gain_ms == plan.loss_ms == 10
    assert p.credits == previous and p.rent == 0


def test_tail_rent_does_not_charge_internal_block_and_renew_only_new_agent():
    p = AgentLeasePolicy(3)
    for k, parent in [("root", None), ("tail", "root"), ("other", None), ("new", None)]:
        p.register(k, parent, 1)
    v = Values({"root": {"a": 7}, "tail": {"a": 6, "b": 4}, "other": {"b": 2}, "new": {"c": 3}})
    for k in ("root", "tail", "other"):
        add(p, k, v)
    plan = add(p, "new", v)
    assert plan.victims == ("other",)
    assert p.credits["root"].total == 7  # internal credit did not pay rent
    assert p.credits["tail"].credit == pytest.approx({"a": 4.8, "b": 3.2})
    p.refresh_hit({"tail"}, v, pinned=set())
    assert p.credits["tail"].total == pytest.approx(8)
    v.rounds["a"] = 2
    p.refresh_hit({"tail"}, v, pinned=set())
    assert p.credits["tail"].credit == pytest.approx({"a": 6, "b": 3.2})
    p.refresh_hit({"tail"}, v, pinned=set())
    assert p.credits["tail"].total == pytest.approx(9.2)


def test_nonhead_changed_value_is_refreshed_before_rent_and_failed_copy_does_not_restore_victims():
    p = AgentLeasePolicy(2)
    for k in ("a", "b", "c"):
        p.register(k, None, 1)
    v = Values({"a": {"one": 2}, "b": {"two": 9}, "c": {"three": 5}})
    add(p, "a", v)
    add(p, "b", v)
    v.gains["b"]["two"] = 1
    v.version += 1
    plan = p.plan("c", v, pinned=set())
    assert plan.victims == ("b",) and plan.checks == 2
    p.apply_releases(plan)
    # No commit ACK: candidate is not recoverable and the fenced victim stays gone.
    assert p.committed == {"a"}
    with pytest.raises(ValueError, match="stale"):
        p.apply_releases(plan)


def test_pins_and_prefix_are_hard_constraints():
    p = AgentLeasePolicy(1)
    p.register("a", None, 1)
    p.register("b", "a", 1)
    p.register("c", None, 1)
    v = Values({"a": {"x": 1}, "b": {"x": 2}, "c": {"y": 10}})
    assert p.plan("b", v, pinned=set()).status == "WAIT_FOR_PREFIX"
    add(p, "a", v)
    assert p.plan("c", v, pinned={"a"}).status == "BYPASS"
    assert p.reclaim(0, v, pinned={"a"}).status == "WAIT_FOR_UNPIN"


def test_joint_dag_shares_telescope_and_endpoint_uses_only_generated_tokens():
    agents = [RecoveryAgent(a, "w", a, 1, "gpu0", ("x",), (5,), (5,), 5, 10, 1) for a in ("a", "b")]
    nodes = {"w": tuple(RecoveryNode(a, (), 10) for a in ("a", "b"))}
    v = WorkflowRecoveryValue(agents=agents, workflows=nodes, gpu_ids=("gpu0",), rate=1e12)
    grants = v.shares(set(), "x")
    assert grants["a"] == 0 and grants["b"] == pytest.approx(5)
    assert sum(grants.values()) == pytest.approx(v.cost(set()) - v.cost({"x"}))
    assert v.curves["a"][0] == 5  # not the 10-token future prompt endpoint
    assert v.curves["a"][1] < 1e-6
    # Existing tail with an already-produced suffix keeps that recompute work.
    existing = RecoveryAgent("a", "w", "a", 1, "gpu0", ("x",), (5,), (5,), 10, 10, 1)
    assert existing.curve(1e12, 0)[1] == pytest.approx(5)


def test_failed_peer_target_has_no_surviving_backup_value():
    a = RecoveryAgent("a", "w", "a", 1, "gpu0", ("x",), (5,), (5,), 5, 10, 1)
    v = WorkflowRecoveryValue(
        agents=[a],
        workflows={"w": (RecoveryNode("a", (), 10),)},
        gpu_ids=("gpu0",),
        rate=1e12,
        target_gpu="gpu0",
    )
    assert v.shares(set(), "x") == {"a": 0}
