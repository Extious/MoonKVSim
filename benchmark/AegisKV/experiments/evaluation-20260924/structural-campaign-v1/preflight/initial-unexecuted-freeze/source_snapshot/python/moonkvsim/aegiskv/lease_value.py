"""Frozen decision-time recovery vectors and nonduplicated workflow value.

The endpoint is *already produced* KV, including a sealed but not yet copied
suffix. Future generation is never charged as recovery. Transfer and recompute
rates are supplied estimates; this module does not claim GPU calibration.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import math


def execution_branches(workflows, agents_by_node):
    """Deterministic causal chains for concurrent branches of one Agent.

    This is immutable trace metadata, not a schedule-dependent new identity.
    Nodes on a chain must be causally ordered; separate parallel branches retain
    independent current request/Slack records as required by the design.
    """
    result = {}
    for workflow, nodes in workflows.items():
        ancestors, tails = {}, {}
        for node in nodes:
            ancestors[node.key] = set(node.parents)
            for p in node.parents:
                ancestors[node.key].update(ancestors[p])
            aid = agents_by_node[node.key]
            chain_tails = tails.setdefault(aid, [])
            eligible = [i for i, p in enumerate(chain_tails) if p in ancestors[node.key]]
            if eligible:
                branch = eligible[0]
                chain_tails[branch] = node.key
            else:
                branch = len(chain_tails)
                chain_tails.append(node.key)
            result[node.key] = branch
    return result


@dataclass(frozen=True)
class RecoveryAgent:
    key: str
    workflow: str
    node: str
    round_id: int
    source_gpu: str
    path: tuple[str, ...]
    ends: tuple[int, ...]
    sizes: tuple[int, ...]
    produced_tokens: int
    prompt_tokens: int
    unit_ms: float
    route_epoch: int = 0

    def curve(self, rate: float, setup_ms: float) -> tuple[float, ...]:
        def work(left):
            # Prompt prefill and known output replay use the serving model's
            # respective 1:8 work weights. No predicted future suffix enters.
            end = self.produced_tokens
            return max(0, min(end, self.prompt_tokens) - left) + 8 * max(
                0, end - max(left, self.prompt_tokens)
            )

        curve = [work(0) * self.unit_ms]
        copied = 0
        for end, size in zip(self.ends, self.sizes, strict=True):
            copied += size
            if end > self.produced_tokens:
                curve.append(curve[-1])
            else:
                curve.append(
                    min(curve[-1], setup_ms + copied / rate * 1000 + work(end) * self.unit_ms)
                )
        return tuple(curve)


@dataclass(frozen=True)
class RecoveryNode:
    key: str
    parents: tuple[str, ...]
    duration_ms: float


class WorkflowRecoveryValue:
    """Uniform single-GPU-failure prior, independent of an injected outcome.

    Nodes must be in topological order. A peer target that fails cannot contribute
    its own backup. Fixed Agent-ID ordered marginal WCT decreases telescope to one
    physical gain; these accounting states are not partial physical commits.
    """

    def __init__(
        self, *, agents, workflows, gpu_ids, rate, setup_ms=0.0, target_gpu=None, dag_enabled=True
    ):
        self.agents = {a.key: a for a in agents}
        if len(self.agents) != len(agents):
            raise ValueError("parallel requests cannot overwrite an Agent recovery state")
        self.workflows = workflows
        self.gpu_ids = tuple(gpu_ids)
        self.target_gpu = target_gpu
        self.rounds = {a.key: a.round_id for a in agents}
        self.curves = {a.key: a.curve(rate, setup_ms) for a in agents}
        self.dag_enabled = dag_enabled
        self.by_workflow = {}
        self.refs = {}
        for a in agents:
            self.by_workflow.setdefault(a.workflow, []).append(a.key)
            for k, end in zip(a.path, a.ends, strict=True):
                if end <= a.produced_tokens:
                    self.refs.setdefault(k, set()).add(a.key)
        self.tables = {}
        self.evaluations = 0
        self._prefix_cache = {}

    def prefix(self, agent, resident):
        count = 0
        for key, end in zip(agent.path, agent.ends, strict=True):
            if key not in resident or end > agent.produced_tokens:
                break
            count += 1
        return count

    def prefixes(self, workflow, resident):
        return {
            a: self.prefix(self.agents[a], resident) for a in self.by_workflow.get(workflow, ())
        }

    def workflow_cost(self, workflow, prefixes):
        stamp = (workflow, tuple(sorted(prefixes.items())))
        if stamp in self.tables:
            return self.tables[stamp]
        refs = self.by_workflow.get(workflow, ())
        total = 0.0
        for failed in self.gpu_ids:
            recoveries = {}
            for aid in refs:
                a = self.agents[aid]
                if a.source_gpu == failed:
                    k = 0 if failed == self.target_gpu else prefixes[aid]
                    recoveries[a.node] = self.curves[aid][k]
            if not self.dag_enabled:
                total += math.fsum(recoveries.values())
                continue
            finish = {}
            for node in self.workflows[workflow]:
                finish[node.key] = (
                    node.duration_ms
                    + recoveries.get(node.key, 0.0)
                    + max((finish[p] for p in node.parents), default=0.0)
                )
            total += max(finish.values(), default=0.0)
        value = total / len(self.gpu_ids)
        self.tables[stamp] = value
        self.evaluations += 1
        return value

    def cost(self, resident):
        return math.fsum(
            self.workflow_cost(w, self.prefixes(w, resident)) for w in self.by_workflow
        )

    def shares(self, resident, key):
        refs = self.refs.get(key, set())
        grants = {a: 0.0 for a in sorted(refs)}
        for w in sorted({self.agents[a].workflow for a in refs}):
            before = self.prefixes(w, resident)
            after = self.prefixes(w, resident | {key})
            old = self.workflow_cost(w, before)
            for aid in sorted(a for a in refs if self.agents[a].workflow == w):
                before[aid] = after[aid]
                new = self.workflow_cost(w, before)
                delta = old - new
                if delta < -1e-8:
                    raise ValueError("prefix fallback violated monotonic recovery value")
                grants[aid] += max(0.0, delta)
                old = new
        return grants

    @cached_property
    def workflow_stamps(self):
        return {
            w: tuple(self.agents[a] for a in sorted(ids)) for w, ids in self.by_workflow.items()
        }

    def stamp(self, key, resident):
        # Relevant workflow recovery states AND prefix frontiers are inputs.
        # A changed non-head tail must invalidate its key before the next rent.
        relevant = sorted({self.agents[a].workflow for a in self.refs.get(key, ())})
        return tuple(
            (w, self.workflow_stamps[w], tuple(sorted(self.prefixes(w, resident).items())))
            for w in relevant
        )
