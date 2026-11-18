"""Minimal, local SlackLandlord policy; exact modeled values, no global solver.

Returns a metadata proposal. Actual release/copy/commit belongs to the existing
execution layer. reference.Model supplies only physical paths and DAG WCT.
"""
from dataclasses import dataclass
from fractions import Fraction as Q


class LazyValue:
    """Reuse a workflow value only when BOTH its inputs and prefixes match."""

    def __init__(self, model):
        self.tables = {}
        self.evaluations = 0
        self.update(model)

    def update(self, model):
        self.model = model
        self.signatures = {}
        for w in model.workflows.values():
            agents = tuple(n.agent for n in w.nodes if n.agent is not None)
            signature = (w, tuple(model.agents[a] for a in agents), tuple(
                (s.key, s.weight, tuple(a for a in agents if a in s.affected),
                 tuple(model.curves[s.key, a] for a in agents)) for s in model.scenarios))
            self.signatures[w.key] = signature
        # No workflow gains are evaluated here; obsolete entries are replaced
        # on first use, so multiple input updates can coalesce.
        self.tables = {k: v for k, v in self.tables.items() if k in model.workflows}

    def __call__(self, mask):
        m = self.model
        if not m.legal(mask):
            raise ValueError('value requires an ancestor-closed physical set')
        total = Q(0)
        for w in m.workflows.values():
            sig = self.signatures[w.key]
            old, values = self.tables.get(w.key, (None, {}))
            if old != sig:
                values = {}
                self.tables[w.key] = (sig, values)
            prefix = m.projection(w, mask)
            if prefix not in values:
                values[prefix] = m.workflow_gain(w, mask)
                self.evaluations += 1
            total += values[prefix]
        return total


@dataclass(frozen=True)
class Plan:
    status: str
    mask: int
    gain: Q = Q(0)
    rent: Q = Q(0)
    credit: Q = Q(0)
    victims: tuple[str, ...] = ()


def decide(model, current, capacity, *, pinned=0, available=None, values=None):
    """Try every available extension of ONE agent path per proposal.

    For each extension, greedily trim physical leaves by current WCT loss/byte.
    Choose the highest positive NET improvement; ties prefer less changed data.
    A capacity reduction is a separate forced-reclaim case. No global optimum
    or competitive-ratio claim is made, including for parallel complementary KV.
    """
    m = model
    if capacity < 0 or not m.legal(current) or not m.legal(pinned) or pinned & ~current:
        raise ValueError('invalid capacity, committed set or pinned prefix')
    available = m.all_mask if available is None else available
    if available < 0 or available & ~m.all_mask:
        raise ValueError('unknown source chunk')
    if m.size(pinned) > capacity:
        return Plan('WAIT_FOR_UNPIN', current)
    if values is None:
        values = LazyValue(m)
    elif values.model is not m:
        values.update(m)
    children = [0] * len(m.chunks)
    for i, parent in enumerate(m.parents):
        if parent >= 0:
            children[parent] |= 1 << i

    def trim(draft, protected):
        victims = []
        while m.size(draft) > capacity:
            before = values(draft)
            choices = [( (before - values(draft ^ (1 << i))) / c.size, c.key, i)
                       for i, c in enumerate(m.chunks)
                       if draft >> i & 1 and not protected >> i & 1
                       and not children[i] & draft]
            if not choices:
                return None
            _, key, i = min(choices)
            draft ^= 1 << i
            victims.append(key)
        return draft, tuple(victims)

    baseline = values(current)
    if m.size(current) > capacity:
        result = trim(current, pinned)
        if result is None:
            return Plan('WAIT_FOR_UNPIN', current)
        final, victims = result
        loss = baseline - values(final)
        return Plan('RECLAIM', final, rent=loss, credit=-loss, victims=victims)

    best = Plan('KEEP', current)
    best_rank = (Q(0), 0, ())
    tried = set()
    for a in m.agents.values():
        prefix = 0
        for key in a.path:
            bit = 1 << m.index[key]
            if not (current | available) & bit:
                break
            prefix |= bit
            added = prefix & ~current
            if not added or added in tried:
                continue
            tried.add(added)
            protected = prefix | pinned
            if m.size(protected) > capacity:
                continue
            union = current | added
            result = trim(union, protected)
            if result is None:
                continue
            final, victims = result
            gain = values(union) - baseline
            rent = values(union) - values(final)
            credit = gain - rent
            rank = (-credit, m.size(current ^ final), m.keys(final))
            if credit > 0 and rank < best_rank:
                best = Plan('REPLACE' if victims else 'ADMIT', final, gain, rent, credit, victims)
                best_rank = rank
    return best
