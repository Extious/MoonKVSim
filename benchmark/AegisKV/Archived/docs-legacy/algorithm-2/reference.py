"""SlackLandlord capacity-model reference; CPU metadata only, not a runtime patch.

All arithmetic is exact. The exhaustive oracle, certified search and versioned
workflow cache are deliberately separate. A chunk ID names ONE physical copy
in ONE target pool; shared agent paths refer to that same ID.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from fractions import Fraction as Q
import heapq
from itertools import count


@dataclass(frozen=True)
class Chunk:
    key: str
    parent: str | None
    size: int


@dataclass(frozen=True)
class Agent:
    key: str
    path: tuple[str, ...]
    recovery: tuple[Q, ...]  # indexed by COMMITTED prefix length, including zero


@dataclass(frozen=True)
class Node:
    key: str
    duration: Q
    parents: tuple[str, ...] = ()
    agent: str | None = None


@dataclass(frozen=True)
class Workflow:
    key: str
    nodes: tuple[Node, ...]  # topological order; plain tool/wait nodes are allowed


@dataclass(frozen=True)
class Scenario:
    key: str
    affected: frozenset[str]
    weight: Q = Q(1)
    recovery_overrides: tuple[tuple[str, tuple[Q, ...]], ...] = ()


class Model:
    def __init__(self, chunks, agents, workflows, scenarios):
        self.chunks = tuple(chunks)
        agents, workflows = tuple(agents), tuple(workflows)
        self.agents = {a.key: a for a in agents}
        self.workflows = {w.key: w for w in workflows}
        self.scenarios = tuple(scenarios)
        if len(self.agents) != len(agents) or len(self.workflows) != len(workflows):
            raise ValueError("duplicate agent/workflow identity")
        if len({s.key for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("duplicate scenario identity")
        self.index = {c.key: i for i, c in enumerate(self.chunks)}
        if len(self.index) != len(self.chunks):
            raise ValueError("duplicate physical chunk")
        if not self.scenarios or sum(s.weight for s in self.scenarios) != 1:
            raise ValueError("conditional scenario weights must sum to one")
        if any(s.weight < 0 or not s.affected <= self.agents.keys() for s in self.scenarios):
            raise ValueError("invalid failure scenario")
        self.parents = []
        self.ancestors = []
        for i, c in enumerate(self.chunks):
            if not isinstance(c.size, int) or c.size <= 0:
                raise ValueError("physical bytes must be positive integers")
            p = self.index.get(c.parent, -1)
            if c.parent is not None and (p < 0 or p >= i):
                raise ValueError("chunks must form a topologically ordered forest")
            self.parents.append(p)
            self.ancestors.append(0 if p < 0 else self.ancestors[p] | (1 << p))
        for a in self.agents.values():
            if len(a.recovery) != len(a.path) + 1 or any(t < 0 for t in a.recovery):
                raise ValueError("one nonnegative recovery cost for each prefix")
            if any(x < y for x, y in zip(a.recovery, a.recovery[1:])):
                raise ValueError("recovery curve must include fallback to shorter prefix")
            prev = None
            for key in a.path:
                if key not in self.index or self.chunks[self.index[key]].parent != prev:
                    raise ValueError("agent path must be an exact physical prefix path")
                prev = key
        self.curves = {}
        for s in self.scenarios:
            override = dict(s.recovery_overrides)
            if len(override) != len(s.recovery_overrides) or not override.keys() <= self.agents.keys():
                raise ValueError("invalid scenario-specific recovery table")
            for a in self.agents.values():
                curve = override.get(a.key, a.recovery)
                if (len(curve) != len(a.path)+1 or any(t < 0 for t in curve)
                        or any(x < y for x, y in zip(curve, curve[1:]))):
                    raise ValueError("invalid scenario-specific recovery curve")
                self.curves[s.key, a.key] = curve
        owners = set()
        for w in self.workflows.values():
            seen = set()
            for n in w.nodes:
                if n.key in seen or not set(n.parents) <= seen or n.duration < 0:
                    raise ValueError("invalid workflow DAG")
                seen.add(n.key)
                if n.agent is not None:
                    if n.agent not in self.agents or n.agent in owners:
                        raise ValueError("each current agent branch binds one workflow node")
                    owners.add(n.agent)
        if owners != self.agents.keys():
            raise ValueError("all agents must bind a workflow node")
        self.all_mask = (1 << len(self.chunks)) - 1
        self.upper_values = [Q(0) for _ in self.chunks]
        for a in self.agents.values():
            for k, key in enumerate(a.path, 1):
                self.upper_values[self.index[key]] += sum(s.weight * (
                    self.curves[s.key, a.key][k-1] - self.curves[s.key, a.key][k])
                    for s in self.scenarios if a.key in s.affected)
        self.density_order = sorted(range(len(self.chunks)), key=lambda i: (
            -self.upper_values[i] / self.chunks[i].size, self.chunks[i].key))
        self.baseline = {(w.key, s.key): self.makespan(w, 0, s)
                         for w in self.workflows.values() for s in self.scenarios}

    def mask(self, keys):
        result = 0
        for key in keys:
            result |= 1 << self.index[key]
        return result

    def keys(self, mask):
        return tuple(c.key for i, c in enumerate(self.chunks) if mask >> i & 1)

    def size(self, mask):
        return sum(c.size for i, c in enumerate(self.chunks) if mask >> i & 1)

    def legal(self, mask):
        return mask >= 0 and not mask & ~self.all_mask and all(
            not (mask >> i & 1) or (self.ancestors[i] & mask) == self.ancestors[i]
            for i in range(len(self.chunks)))

    def frontier(self, agent, mask):
        k = 0
        for key in agent.path:
            if not mask >> self.index[key] & 1:
                break
            k += 1
        return k

    def makespan(self, workflow, mask, scenario):
        finish = {}
        for n in workflow.nodes:
            d = Q(n.duration)
            if n.agent in scenario.affected:
                a = self.agents[n.agent]
                d += self.curves[scenario.key, a.key][self.frontier(a, mask)]
            finish[n.key] = max((finish[p] for p in n.parents), default=Q(0)) + d
        return max(finish.values(), default=Q(0))

    def workflow_gain(self, workflow, mask):
        return sum(s.weight * (self.baseline[workflow.key, s.key] - self.makespan(workflow, mask, s))
                   for s in self.scenarios)

    def gain(self, mask):
        if not self.legal(mask):
            raise ValueError("utility is defined here only for legal protected prefixes")
        return sum(self.workflow_gain(w, mask) for w in self.workflows.values())

    def projection(self, workflow, mask):
        return tuple(self.frontier(self.agents[n.agent], mask)
                     for n in workflow.nodes if n.agent is not None)

    def workflow_cap(self, workflow, mask):
        # A safe upper bound, NOT an additive estimate of actual workflow benefit.
        return sum(s.weight * sum(
            self.curves[s.key, n.agent][0] - self.curves[s.key, n.agent][
                self.frontier(self.agents[n.agent], mask)]
            for n in workflow.nodes if n.agent in s.affected) for s in self.scenarios)

    def compatibility(self, w):
        agents = {n.agent for n in w.nodes if n.agent is not None}
        return (tuple((n.key, n.parents, n.agent,
                       None if n.agent is None else self.agents[n.agent].path) for n in w.nodes),
                tuple((s.key, tuple(sorted(s.affected & agents)), s.weight) for s in self.scenarios))

    def action_credit(self, before, after, rent):
        """Exact modeled WCT change minus capacity rent; may be negative.

        This is a state-dependent reduced value, NOT historical prepaid credit.
        A rent certificate alone never decides the integer allocation.
        """
        if rent < 0:
            raise ValueError("negative capacity rent")
        return self.gain(after) - self.gain(before) - rent * (self.size(after) - self.size(before))


@dataclass(frozen=True)
class Problem:
    model: Model
    capacity: int
    current: int = 0
    required: int = 0
    available: int | None = None

    def __post_init__(self):
        m = self.model
        if self.capacity < 0 or not m.legal(self.current):
            raise ValueError("invalid capacity/current committed prefixes")
        if not m.legal(self.required):
            raise ValueError("pins must include their ancestors")
        if self.allowed & ~m.all_mask or self.allowed < 0:
            raise ValueError("invalid source-available set")
        if self.required & ~self.allowed or m.size(self.required) > self.capacity:
            raise ValueError("infeasible pins: defer physical shrink; do not overcommit")
        if not m.legal(self.allowed):
            raise ValueError("available candidates must include all needed ancestors")

    @property
    def allowed(self):
        return self.model.all_mask if self.available is None else self.available

    def feasible(self, mask):
        return (self.model.legal(mask) and not mask & ~self.allowed
                and mask & self.required == self.required and self.model.size(mask) <= self.capacity)

    def rank(self, mask, gain):
        # Additive tie handling permits exact component decomposition. This is
        # applied ONLY after equal objective values, never as a utility bonus.
        return (-gain, self.model.size(mask ^ self.current),
                self.model.size(mask & ~self.current), self.model.size(mask), mask)


def exhaustive(problem):
    """Independent 2^N oracle; for small instances only."""
    best = None
    feasible = 0
    for mask in range(problem.model.all_mask + 1):
        if problem.feasible(mask):
            feasible += 1
            value = problem.model.gain(mask)
            row = (problem.rank(mask, value), mask, value)
            if best is None or row[0] < best[0]:
                best = row
    assert best is not None
    return best[1], best[2], feasible


@dataclass(frozen=True)
class RentBound:
    value: Q
    rent: Q


def fractional_bound(model, candidates, room):
    """Min_lambda lambda*room + sum(max(u_x-lambda*b_x,0)).

    Precedence, sharing in utility and integrality are relaxed ONLY in this bound.
    Physical memory is counted once. The resulting rent is derived, not tuned.
    """
    if room < 0:
        raise ValueError("negative residual capacity")
    remain, value, rent = room, Q(0), Q(0)
    for i in model.density_order:
        if not candidates >> i & 1:
            continue
        b, v = model.chunks[i].size, model.upper_values[i]
        if v == 0:
            continue
        if remain >= b:
            remain -= b
            value += v
            rent = v / b
        else:
            rent = v / b
            value += rent * remain
            remain = 0
            break
    if remain > 0 or not any(candidates >> i & 1 and model.upper_values[i] > 0
                             for i in range(len(model.chunks))):
        rent = Q(0)
    dual = rent * room + sum(max(model.upper_values[i] - rent * c.size, Q(0))
                            for i, c in enumerate(model.chunks) if candidates >> i & 1)
    assert dual == value, (dual, value)
    return RentBound(value, rent)


class ValueCache:
    """Per-workflow exact values and certified cross-round intervals.

    For compatible topology, sum of maximum node-duration perturbations is D.
    Both unprotected and protected DAG makespans change by at most D, hence
    workflow gain changes by at most 2D. D accumulates across unrefreshed rounds.
    """
    def __init__(self, model, max_entries=100000):
        if max_entries < 1:
            raise ValueError("positive cache bound required")
        self.model = model
        self.limit = max_entries
        self.entries = OrderedDict()
        self.generation = {w: 0 for w in model.workflows}
        self.drift = {w: Q(0) for w in model.workflows}
        self.workflow_evaluations = 0
        self.calls_by_workflow = {}
        self.exact_hits = 0
        self.stale_intervals = 0

    def update(self, new):
        old = self.model
        # Updates invalidate only changed workflows; they do not refresh all
        # cached states or all physical chunks. Changed profile arrays still
        # incur their own input-validation/perturbation-scan cost.
        for key, nw in new.workflows.items():
            ow = old.workflows.get(key)
            if ow is None or old.compatibility(ow) != new.compatibility(nw):
                self.generation[key] = self.generation.get(key, -1) + 1
                self.drift[key] = Q(0)
                continue
            delta = Q(0)
            for x, y in zip(ow.nodes, nw.nodes):
                delta += abs(x.duration - y.duration)
                if x.agent is not None:
                    delta += max((abs(p-q) for s in new.scenarios
                                  for p, q in zip(old.curves[s.key, x.agent],
                                                  new.curves[s.key, y.agent])), default=Q(0))
            self.drift[key] += delta
        # A removed then re-added workflow must get a new cache generation.
        for key in old.workflows.keys() - new.workflows.keys():
            self.generation[key] = self.generation.get(key, 0) + 1
        self.model = new

    def _key(self, workflow, mask):
        return (workflow.key, self.generation[workflow.key], self.model.projection(workflow, mask))

    def interval(self, mask):
        lo, hi = Q(0), Q(0)
        for w in self.model.workflows.values():
            cap = self.model.workflow_cap(w, mask)
            entry = self.entries.get(self._key(w, mask))
            if cap == 0:
                continue
            if entry is None:
                hi += cap
            else:
                value, drift = entry
                error = 2 * (self.drift[w.key] - drift)
                lower, upper = max(Q(0), value-error), min(cap, value+error)
                assert lower <= upper
                lo += lower
                hi += upper
                if error:
                    self.stale_intervals += 1
        return lo, hi

    def exact(self, mask):
        value = Q(0)
        for w in self.model.workflows.values():
            key = self._key(w, mask)
            entry = self.entries.get(key)
            if self.model.workflow_cap(w, mask) == 0:
                part = Q(0)
            elif entry is not None and entry[1] == self.drift[w.key]:
                part = entry[0]
                self.exact_hits += 1
                self.entries.move_to_end(key)
            else:
                part = self.model.workflow_gain(w, mask)
                self.workflow_evaluations += 1
                self.calls_by_workflow[w.key] = self.calls_by_workflow.get(w.key, 0) + 1
                self.entries[key] = (part, self.drift[w.key])
                self.entries.move_to_end(key)
                while len(self.entries) > self.limit:
                    self.entries.popitem(last=False)
            value += part
        return value


@dataclass(frozen=True)
class Solution:
    mask: int
    value: Q
    upper_bound: Q
    exact: bool
    pops: int
    workflow_evaluations: int
    pruned: int
    root_rent: Q

    @property
    def gap(self):
        return self.upper_bound - self.value


def solve(problem, cache=None, *, lazy=True, max_pops=None):
    """Deterministic best-bound search; exact if all remaining ties are resolved.

    Budget exhaustion returns a feasible incumbent AND a valid objective gap.
    Only a zero gap certifies the optimal value. `exact` additionally certifies
    the deterministic tie choice. No expired heap key triggers physical eviction.
    """
    m = problem.model
    if max_pops is not None and max_pops < 0:
        raise ValueError("negative search budget")
    cache = cache or ValueCache(m)
    if cache.model is not m:
        raise ValueError("publish the new model to the cache before solving")
    initial_evals = cache.workflow_evaluations
    best = problem.current if problem.feasible(problem.current) else problem.required
    best_value = cache.exact(best)
    heap, sequence = [], count()
    pruned, pops = 0, 0

    def remaining(pos, selected):
        candidates = 0
        decided = (1 << pos) - 1
        excluded = decided & ~selected
        for i in range(pos, len(m.chunks)):
            if problem.allowed >> i & 1 and not m.ancestors[i] & excluded:
                candidates |= 1 << i
        return candidates

    def bound(pos, selected):
        if lazy:
            _, upper = cache.interval(selected)
        else:
            upper = cache.exact(selected)
        rb = fractional_bound(m, remaining(pos, selected), problem.capacity - m.size(selected))
        return upper + rb.value, rb.rent

    root_upper, root_rent = bound(0, 0)
    heapq.heappush(heap, (-root_upper, next(sequence), 0, 0))
    while heap and (max_pops is None or pops < max_pops):
        neg_upper, _, pos, selected = heapq.heappop(heap)
        pops += 1
        if -neg_upper < best_value:
            pruned += 1
            continue
        value = cache.exact(selected)
        if problem.feasible(selected) and problem.rank(selected, value) < problem.rank(best, best_value):
            best, best_value = selected, value
        rb = fractional_bound(m, remaining(pos, selected), problem.capacity-m.size(selected))
        upper = value + rb.value
        if upper < best_value:
            pruned += 1
            continue
        if heap and upper < -heap[0][0]:
            heapq.heappush(heap, (-upper, next(sequence), pos, selected))
            continue
        if pos == len(m.chunks):
            continue
        bit = 1 << pos
        choices = []
        p = m.parents[pos]
        if (problem.allowed & bit and (p < 0 or selected >> p & 1)
                and m.size(selected) + m.chunks[pos].size <= problem.capacity):
            choices.append(selected | bit)
        if not problem.required & bit:
            choices.append(selected)
        for child in choices:
            # Do not explore a branch that has excluded a required ancestor.
            missing_required = problem.required & ((1 << (pos+1)) - 1) & ~child
            if missing_required:
                continue
            ub, _ = bound(pos+1, child)
            if ub < best_value:
                pruned += 1
            else:
                heapq.heappush(heap, (-ub, next(sequence), pos+1, child))
    upper = max(best_value, -heap[0][0] if heap else best_value)
    return Solution(best, best_value, upper, not heap, pops,
                    cache.workflow_evaluations-initial_evals, pruned, root_rent)


def components(model):
    """Join both prefix dependencies AND whole-workflow utility dependencies."""
    n = len(model.chunks)
    parents = list(range(n))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    def join(i, j):
        parents[root(i)] = root(j)

    for i, p in enumerate(model.parents):
        if p >= 0:
            join(i, p)
    for w in model.workflows.values():
        indices = [model.index[key] for node in w.nodes if node.agent is not None
                   for key in model.agents[node.agent].path]
        for i in indices[1:]:
            join(indices[0], i)
    groups = {}
    for i in range(n):
        groups[root(i)] = groups.get(root(i), 0) | (1 << i)
    return tuple(sorted(groups.values()))


class ProfileBudgetExceeded(RuntimeError):
    pass


class ComponentCache:
    """Complete component profiles, refreshed only on a structural/value change.

    This optional exact fast path avoids exponential GLOBAL enumeration when
    shared-prefix/workflow components are small. A giant shared system prefix
    can defeat decomposition; the caller must use a budget, not hide that case.
    """
    def __init__(self, max_profiles=1000):
        self.profiles = OrderedDict()
        self.limit = max_profiles
        self.builds = 0
        self.hits = 0
        self.configurations = 0

    def profile(self, problem, group, value_cache, budget):
        m = problem.model
        indices = tuple(i for i in range(len(m.chunks)) if group >> i & 1)
        workflows = tuple(w for w in m.workflows.values() if any(
            m.mask(m.agents[n.agent].path) & group for n in w.nodes if n.agent is not None))
        agent_keys = {n.agent for w in workflows for n in w.nodes if n.agent is not None}
        sig = (tuple((i, m.chunks[i]) for i in indices), workflows,
               tuple(m.agents[k] for k in sorted(agent_keys)),
               tuple((s.key, s.weight, s.affected & agent_keys,
                      tuple((k, m.curves[s.key, k]) for k in sorted(agent_keys))) for s in m.scenarios),
               problem.required & group, problem.allowed & group)
        if sig in self.profiles:
            self.hits += 1
            self.profiles.move_to_end(sig)
            return self.profiles[sig]
        rows = []
        stack = [(0, 0)]
        while stack:
            pos, mask = stack.pop()
            if pos == len(indices):
                if budget[0] is not None:
                    if budget[0] <= 0:
                        raise ProfileBudgetExceeded("component profile incomplete; use certified search or DEFER")
                    budget[0] -= 1
                # Components contain whole workflows, so other-component zero
                # frontiers contribute exactly zero baseline-relative gain.
                rows.append((mask, m.size(mask), value_cache.exact(mask)))
                continue
            i = indices[pos]
            bit = 1 << i
            p = m.parents[i]
            if problem.allowed & bit and (p < 0 or mask >> p & 1):
                stack.append((pos+1, mask | bit))
            if not problem.required & bit:
                stack.append((pos+1, mask))
        self.builds += 1
        self.configurations += len(rows)
        self.profiles[sig] = tuple(rows)
        while len(self.profiles) > self.limit:
            self.profiles.popitem(last=False)
        return tuple(rows)


def solve_components(problem, profiles=None, values=None, *, max_configurations=100000,
                     max_transitions=1000000):
    """Exact sparse multiple-choice DP over complete component profiles.

    Raises on budget exhaustion; an incomplete profile is NEVER treated as exact.
    Bytes remain integers; no capacity rounding or fractional chunk is committed.
    """
    profiles = profiles or ComponentCache()
    values = values or ValueCache(problem.model)
    if values.model is not problem.model:
        raise ValueError("publish the new model first")
    budget = [max_configurations]
    states = {0: (0, Q(0))}
    transitions = 0
    for group in components(problem.model):
        rows = profiles.profile(problem, group, values, budget)
        next_states = {}
        for used, (mask, value) in states.items():
            for cmask, size, gain in rows:
                transitions += 1
                if max_transitions is not None and transitions > max_transitions:
                    raise ProfileBudgetExceeded("component allocation DP exceeded work budget")
                cost = used + size
                if cost > problem.capacity:
                    continue
                candidate = (mask | cmask, value + gain)
                prev = next_states.get(cost)
                if prev is None or problem.rank(*candidate) < problem.rank(*prev):
                    next_states[cost] = candidate
        states = next_states
    if not states:
        raise ValueError("no allocation satisfies pins and quota")
    mask, value = min(states.values(), key=lambda row: problem.rank(*row))
    return mask, value, transitions
