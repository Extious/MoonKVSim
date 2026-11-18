"""Agent subleases, frontier rent and exact modeled WCT; CPU reference only.

The reference explicitly debits eligible tails so its accounting is easy to
audit. H = L + remaining_credit / bytes is the equivalent active-tail key;
this module makes no production heap, copy protocol or performance claim.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from fractions import Fraction as Q


class CostOracle:
    """Lazy DAG evaluation. Input invalidation does not evaluate any WCT."""

    def __init__(self, model, active):
        self.evaluations = 0
        self.revision = 0
        self.tables = {}
        self.update(model, active)

    def update(self, model, active):
        self.model, self.active = model, frozenset(active)
        self.revision += 1

    def prefixes(self, mask):
        return {a.key: self.model.frontier(a, mask) for a in self.model.agents.values()}

    def workflow_cost(self, workflow, prefixes):
        m = self.model
        stamp, table = self.tables.get(workflow.key, (-1, {}))
        if stamp != self.revision:
            table = {}
            self.tables[workflow.key] = (self.revision, table)
        key = tuple(prefixes[n.agent] for n in workflow.nodes if n.agent is not None)
        if key not in table:
            cost = Q(0)
            for scenario in m.scenarios:
                finish = {}
                for node in workflow.nodes:
                    delay = Q(node.duration)
                    if node.agent in self.active and node.agent in scenario.affected:
                        delay += m.curves[scenario.key, node.agent][prefixes[node.agent]]
                    finish[node.key] = delay + max((finish[p] for p in node.parents), default=Q(0))
                cost += scenario.weight * max(finish.values(), default=Q(0))
            table[key] = cost
            self.evaluations += 1
        return table[key]

    def cost(self, mask):
        if not self.model.legal(mask):
            raise ValueError('only contiguous committed prefixes have a recovery value')
        prefixes = self.prefixes(mask)
        return sum((self.workflow_cost(w, prefixes) for w in self.model.workflows.values()), Q(0))

    def shares(self, without, with_chunk, chunk):
        """Fixed Agent-ID ordered marginals telescope to ONE physical gain.

        Intermediate Agent-specific recovery vectors are accounting states,
        not partially committed physical copies. No equal-share bonus is used.
        """
        m = self.model
        bit = 1 << m.index[chunk]
        if with_chunk != without | bit or without & bit or not m.legal(with_chunk) or not m.legal(without):
            raise ValueError('share calculation must add exactly one legal chunk')
        before, after = self.prefixes(without), self.prefixes(with_chunk)
        refs = {a for a in self.active if chunk in m.agents[a].path}
        grants = {a: Q(0) for a in sorted(refs)}
        for w in m.workflows.values():
            order = sorted(n.agent for n in w.nodes if n.agent in refs)
            if not order:
                continue
            working = before.copy()
            old = self.workflow_cost(w, working)
            for a in order:
                working[a] = after[a]
                new = self.workflow_cost(w, working)
                grants[a] += old - new
                old = new
        assert all(c >= 0 for c in grants.values())
        return grants


@dataclass
class Lease:
    credit: dict[str, Q] = field(default_factory=dict)
    seen_round: dict[str, int] = field(default_factory=dict)

    @property
    def total(self):
        return sum(self.credit.values(), Q(0))

    def debit(self, amount):
        """One physical charge; all Agent shares pay proportionally."""
        total = self.total
        if amount < 0 or amount > total:
            raise ValueError('rent must be within the remaining physical credit')
        if total:
            factor = (total - amount) / total
            self.credit = {a: c * factor for a, c in self.credit.items()}


@dataclass(frozen=True)
class Decision:
    status: str
    mask: int
    gain: Q = Q(0)
    loss: Q = Q(0)
    net: Q = Q(0)
    victims: tuple[str, ...] = ()


class SlackLandlord:
    def __init__(self, model):
        self.model = model
        self.current = 0
        self.L = Q(0)
        self.leases = {}
        self.rounds = {a: 1 for a in model.agents}
        self.active = set(model.agents)
        self.ended = set()
        self.values = CostOracle(model, self.active)
        self.rent_charged = Q(0)

    def new_request(self, agent, round_id, model=None):
        """One Agent record changes; no chunk walk, WCT call or credit reset.

        A pending round is consumed before the next rent step involving that
        chunk. Multiple pending rounds can coalesce: no intervening eligible
        rent step is permitted without first consuming them.
        """
        if agent not in self.rounds or agent in self.ended:
            raise ValueError('unknown/ended Agent; use a new lifecycle identity')
        if round_id == self.rounds[agent]:
            return False  # idempotent delivery of this event
        if round_id < self.rounds[agent]:
            raise ValueError('out-of-order request event')
        if model is not None:
            self.update_inputs(model)
        self.rounds[agent] = round_id
        return True

    def update_inputs(self, model):
        """Cost/DAG changes invalidate values but do not authorize renewal."""
        if model.chunks != self.model.chunks or model.agents.keys() != self.model.agents.keys():
            raise ValueError('this bounded reference uses a fixed physical forest and Agent IDs')
        self.model = model
        self.values.update(model, self.active)

    def request_finished(self, agent):
        if agent not in self.rounds:
            raise ValueError('unknown Agent')
        # The Agent and its subleases survive between requests.

    def end_agent(self, agent):
        if agent not in self.rounds:
            raise ValueError('unknown Agent')
        self.active.discard(agent)
        self.ended.add(agent)
        self.values.update(self.model, self.active)
        # Stale per-chunk entries are removed on frontier refresh, before rent.

    def tails(self, mask=None, pinned=0, exclude=0):
        m = self.model
        mask = self.current if mask is None else mask
        parents = {m.parents[i] for i in range(len(m.chunks)) if mask >> i & 1}
        return tuple(c.key for i, c in enumerate(m.chunks)
                     if mask >> i & 1 and i not in parents and not (pinned | exclude) >> i & 1)

    def _refresh(self, key, mask):
        m = self.model
        bit = 1 << m.index[key]
        grants = self.values.shares(mask ^ bit, mask, key)
        lease = self.leases.setdefault(key, Lease())
        # Preserve consumed round IDs after reference removal. Detaching and
        # reattaching the same Agent in the same round must not mint credit.
        updated, seen = {}, lease.seen_round.copy()
        for a, grant in grants.items():
            pending = lease.seen_round.get(a, -1) != self.rounds[a]
            updated[a] = grant if pending else min(lease.credit.get(a, Q(0)), grant)
            seen[a] = self.rounds[a]
        lease.credit, lease.seen_round = updated, seen
        return grants

    def refresh_frontier(self, *, pinned=0):
        for key in self.tails(pinned=pinned):
            self._refresh(key, self.current)

    def key(self, key):
        """Valid for a refreshed eligible tail; internal keys are inactive."""
        return self.L + self.leases[key].total / self.model.chunks[self.model.index[key]].size

    def _rent_step(self, mask, *, pinned=0, exclude=0):
        tails = self.tails(mask, pinned, exclude)
        if not tails:
            return None
        # Correctness barrier: check ALL eligible tails, not only an old top.
        for key in tails:
            self._refresh(key, mask)
        delta, victim = min((self.key(key) - self.L, key) for key in tails)
        self.L += delta
        for key in tails:
            charge = self.model.chunks[self.model.index[key]].size * delta
            self.leases[key].debit(charge)
            self.rent_charged += charge
        assert self.leases[victim].total == 0
        return victim

    def _fork(self):
        trial = object.__new__(type(self))
        trial.__dict__ = self.__dict__.copy()
        trial.leases = deepcopy(self.leases)
        # The oracle is a read-only input cache; trials may warm it.
        return trial

    def _commit(self, trial):
        self.current, self.L, self.leases = trial.current, trial.L, trial.leases
        self.rent_charged = trial.rent_charged

    def admit(self, chunk, capacity, *, pinned=0, available=None):
        m = self.model
        if capacity < 0 or not m.legal(pinned) or pinned & ~self.current:
            raise ValueError('invalid capacity or pins')
        bit = 1 << m.index[chunk]
        if self.current & bit:
            return Decision('REUSE', self.current)
        if m.size(self.current) > capacity:
            return Decision('WAIT_FOR_RECLAIM', self.current)
        if available is not None and not available & bit:
            return Decision('WAIT_FOR_SOURCE', self.current)
        if m.ancestors[m.index[chunk]] & self.current != m.ancestors[m.index[chunk]]:
            return Decision('WAIT_FOR_PREFIX', self.current)
        protected = pinned | bit | m.ancestors[m.index[chunk]]
        if m.size(protected) > capacity:
            return Decision('BYPASS', self.current)
        draft = self.current | bit
        baseline, extended = self.values.cost(self.current), self.values.cost(draft)
        gain = baseline - extended
        if gain <= 0:
            return Decision('BYPASS', self.current)
        trial = self._fork()
        victims = []
        while m.size(draft) > capacity:
            victim = trial._rent_step(draft, pinned=protected, exclude=bit)
            if victim is None:
                return Decision('BYPASS', self.current)
            draft ^= 1 << m.index[victim]
            del trial.leases[victim]
            victims.append(victim)
        loss = self.values.cost(draft) - extended
        if gain <= loss:
            return Decision('BYPASS', self.current)
        trial.current = draft
        # A real new physical copy gets its CURRENT single-chunk WCT grant.
        trial._refresh(chunk, draft)
        self._commit(trial)
        return Decision('REPLACE' if victims else 'ADMIT', draft, gain, loss, gain-loss, tuple(victims))

    def reclaim(self, capacity, *, pinned=0):
        """Forced quota shrink. Pins can block it; shrink has no positive-gain gate."""
        m = self.model
        if capacity < 0 or not m.legal(pinned) or pinned & ~self.current:
            raise ValueError('invalid capacity or pins')
        if m.size(pinned) > capacity:
            return Decision('WAIT_FOR_UNPIN', self.current)
        trial, victims = self._fork(), []
        old = self.values.cost(self.current)
        while m.size(trial.current) > capacity:
            victim = trial._rent_step(trial.current, pinned=pinned)
            if victim is None:
                return Decision('WAIT_FOR_UNPIN', self.current)
            trial.current ^= 1 << m.index[victim]
            del trial.leases[victim]
            victims.append(victim)
        loss = self.values.cost(trial.current) - old
        self._commit(trial)
        return Decision('RECLAIM' if victims else 'KEEP', self.current, loss=loss, net=-loss, victims=tuple(victims))
