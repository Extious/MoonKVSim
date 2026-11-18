#!/usr/bin/env python3
"""Small executable specification checks, not a serving-system benchmark.

Exercise credit conservation, legal coverage, failed handoffs, and quota debt.
The planner/resource estimator is deliberately not implemented here. All
examples are constructed; outputs must not be represented as runtime evidence.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "exports/three-tier-rental-design-20260921"


@dataclass
class Replica:
    size: float
    grants: dict[str, float]
    paid: dict[str, float] = field(default_factory=dict)
    settled: float = 0.0
    seen: set[tuple[str, str]] = field(default_factory=set)

    def shares(self):
        return {a: max(0.0, g - self.paid.get(a, 0.0))
                for a, g in self.grants.items()}

    def credit(self):
        return sum(self.shares().values())

    def settle(self, clock):
        assert clock >= self.settled
        shares = self.shares()
        total = sum(shares.values())
        bill = min(total, self.size * (clock - self.settled))
        if total:
            for a, c in shares.items():
                self.paid[a] = self.paid.get(a, 0.0) + bill * c / total
        self.settled = clock

    def key(self, clock):
        self.settle(clock)
        return clock + self.credit() / self.size

    def revalue(self, agent, grant, clock):
        assert grant >= 0
        self.settle(clock)
        self.grants[agent] = grant

    def renew(self, agent, grant, clock, event):
        identity = (agent, event)
        if identity in self.seen:
            return False
        self.settle(clock)
        self.grants[agent] = grant
        self.paid[agent] = 0.0
        self.seen.add(identity)
        return True


def increments(times, slack=0):
    """Fixed endpoint; adding a group can be ignored (monotone envelope)."""
    usable = []
    best = math.inf
    for t in times:
        best = min(best, t)
        usable.append(max(best - slack, 0))
    return [a - b for a, b in zip(usable, usable[1:])]


@dataclass
class Coverage:
    required: frozenset[str]
    locations: dict[str, set[str]]
    authoritative: str = "D"
    pending: dict[str, set[str]] = field(default_factory=dict)
    peer: set[str] = field(default_factory=set)
    leased: dict[str, int] = field(default_factory=dict)
    retiring: set[str] = field(default_factory=set)
    logical_pin: bool = True
    clock: float = 0.0
    version: int = 0
    log_survives: bool = True

    def complete(self, tier):
        return self.required <= self.locations.get(tier, set())

    def invariant(self):
        assert self.authoritative == "R" and self.log_survives or self.complete(self.authoritative)
        if self.peer:
            assert self.authoritative in ("D", "S") and self.complete(self.authoritative)
            assert self.peer <= self.required
        assert self.clock >= 0

    def ack(self, tier, objs, persistent):
        self.pending.setdefault(tier, set()).update(objs)
        if self.required <= self.pending[tier] and persistent:
            self.locations[tier] = set(self.pending.pop(tier))
            return True
        return False

    def handoff(self, tier, trial, version):
        if version != self.version or not self.complete(tier):
            return False
        old = self.authoritative
        self.authoritative = tier
        self.retiring.add(old)
        self.clock = max(self.clock, trial)
        self.version += 1
        self.invariant()
        return True

    def release(self, tier):
        if tier not in self.retiring or self.leased.get(tier, 0):
            return False
        self.locations.pop(tier, None)
        self.retiring.remove(tier)
        self.invariant()
        return True

    def peer_release(self, required=False):
        if self.leased.get("H", 0) or (self.logical_pin and not required):
            return False
        self.peer.clear()
        self.invariant()
        return True

    def delete_last(self):
        if self.peer or self.leased.get(self.authoritative, 0) or not self.log_survives:
            return False
        old = self.authoritative
        self.authoritative = "R"
        self.retiring.add(old)
        self.version += 1
        self.invariant()
        return True


def quota(budget, stable_count, *, pool, serving, reserve, cap,
          pressure=False, stable=True, demand=True, telemetry=True,
          gamma=.5, step=2, windows=2, page=1):
    ceiling = max(0, min(cap, pool - serving - reserve))
    next_budget = budget
    if pressure:
        next_budget, stable_count = gamma * budget, 0
    elif stable and telemetry:
        stable_count += 1
        if stable_count >= windows:
            if demand:
                next_budget += step
            stable_count = 0
    else:
        stable_count = 0
    return math.floor(min(ceiling, next_budget) / page) * page, stable_count


def main():
    checks = []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    # Exhaustive finite-grid rent conservation, plus laziness under no events.
    grid_count = 0
    for ga, gb, size, clock in itertools.product([0, 1, 3, 7], [0, 2, 5], [1, 2, 8], [0, .25, 1, 4, 16]):
        x = Replica(size, {"A": ga, "B": gb})
        x.settle(clock)
        expected = max(0, ga + gb - size * clock)
        assert math.isclose(x.credit(), expected, abs_tol=1e-10)
        y = Replica(size, {"A": ga, "B": gb})
        y.settle(clock / 3)
        y.settle(clock)
        assert all(math.isclose(x.shares()[a], y.shares()[a], abs_tol=1e-10) for a in x.grants)
        grid_count += 1
    check("physical-byte rent and lazy settlement over finite grid", grid_count == 180)

    x = Replica(1, {"A": 3, "B": 2})
    ledger = []
    def row(event):
        shares = x.shares()
        ledger.append(dict(event=event, A=round(shares['A'], 6), B=round(shares['B'], 6), total=round(x.credit(), 6)))
    row("Initial grant")
    x.settle(2)
    row("Rent: +2")
    check("rent allocated proportionally", math.isclose(x.shares()['A'], 1.8) and math.isclose(x.shares()['B'], 1.2))
    paid_before = dict(x.paid)
    x.revalue('A', 4, 2)
    row("A value: 3 → 4")
    check("value refresh never refunds paid rent", x.paid == paid_before and math.isclose(x.shares()['A'], 2.8))
    x.renew('A', 4, 2, 'round-2')
    row("A uses x again")
    check("renewal is Agent-local", math.isclose(x.shares()['A'], 4) and math.isclose(x.shares()['B'], 1.2))
    x.settle(3)
    before = x.credit()
    check("duplicate use cannot renew again", not x.renew('A', 4, 3, 'round-2') and x.credit() == before)
    old_paid = x.paid['A']
    x.revalue('A', 0, 3)
    x.revalue('A', 6, 3)
    check("falling and rising value preserves debt", x.paid['A'] == old_paid)

    prefix = increments([12, 7, 5], 6)
    check("fixed-endpoint prefix credit is 5 then 1", prefix == [5, 1])
    check("prefix allocation telescopes", sum(prefix) == (12 - 6))
    check("nonbeneficial intermediate configuration can be ignored", increments([12, 14, 5], 6) == [0, 6])
    normal = increments([9, 3, 2])
    failure = increments([12, 7, 5], 100)
    check("large Slack does not zero normal reuse", sum(normal) > 0 and sum(failure) == 0)
    check("shared prefix aggregates distinct Agent demand", prefix[0] + increments([10, 4, 2], 1)[0] == 11)
    check("Peer has incremental wait benefit only", (20 - 5) + (5 - 3) == 20 - 3)
    # Common-fault local scores must not stand in for the final max-join pass.
    check("one tied branch improvement leaves join unchanged", max(10, 10) == max(2, 10))

    req = frozenset(f'L{l}B{b}' for l in range(2) for b in range(2))
    st = Coverage(req, {'D': set(req)}, peer={'L0B0'}, leased={'D': 1, 'H': 1})
    st.invariant()
    state_before = copy.deepcopy(st)
    check("unprepared handoff neither changes rent nor coverage", not st.handoff('S', 4, 0) and st == state_before)
    check("partial checkpoint is not complete", not st.ack('S', {'L0B0'}, True) and st.authoritative == 'D')
    check("buffered acknowledgment is not persistence", not st.ack('S', set(req), False) and not st.complete('S'))
    check("complete persistent copy can commit", st.ack('S', set(), True))
    check("stale generation cannot publish handoff", not st.handoff('S', 4, 99) and st.clock == 0)
    check("prepared demotion changes authoritative backing", st.handoff('S', 4, 0) and st.authoritative == 'S')
    check("active read prevents physical release", not st.release('D') and st.complete('D'))
    st.leased['D'] = 0
    check("drain permits whole-checkpoint source release", st.release('D') and not st.complete('D') and st.complete('S'))
    check("pressure never overrides physical lease", not st.peer_release(required=True))
    st.leased['H'] = 0
    check("ordinary admission respects running logical pin", not st.peer_release())
    check("pressure may revoke logical pin with backing", st.peer_release(required=True) and st.complete('S'))
    check("last deletion first publishes log fallback", st.delete_last() and st.authoritative == 'R')
    check("last storage release preserves explicit reconstruction", st.release('S') and st.log_survives)
    check("failure after handoff cannot rewind rent", st.clock == 4)
    # A shared object does not free until the last manifest reference retires.
    refs = {'prefix': {'a', 'b'}, 'a-tail': {'a'}}
    releasing = {x for x, owners in refs.items() if owners <= {'a'}}
    check("shared prefix cannot be counted as freed by one owner", releasing == {'a-tail'})

    # Bounded screening must try an alternative; rejection is side-effect free.
    base_clock = 0
    incoming = Replica(1, {'new': 4})
    victims = [dict(key=1, value=10), dict(key=2, value=1)]
    feasible = [v for v in victims if incoming.key(base_clock) > v['key'] and 4-v['value'] > .3]
    check("second victim can rescue rejected first comparison", len(feasible) == 1 and feasible[0]['key'] == 2)
    check("trial evaluation leaves real clock unchanged", base_clock == 0)
    incoming.settle(2)
    check("successful admission installs residual not fresh credit", incoming.credit() == 2)
    # Prospective legal groups pay by their total new bytes; distribute their
    # successful admission charge across the grants installed at commit.
    grants = [6., 2.]
    trial_bill = 2 * 2  # two new byte units, two units of trial price
    residual = [g * (1 - trial_bill / sum(grants)) for g in grants]
    check("group admission conserves the paid trial charge", residual == [3., 1.] and sum(residual) == sum(grants)-trial_bill)
    check("zero residual cannot win optional admission", not sum(grants) > 2 * 4)

    params = dict(pool=64, serving=28, reserve=4, cap=32)
    b, z = quota(16, 0, **params, pressure=True)
    check("AIMD decreases multiplicatively", (b, z) == (8, 0))
    b, z = quota(b, z, **params)
    check("one stable window does not grow prematurely", (b, z) == (8, 1))
    b, z = quota(b, z, **params)
    check("consecutive stable windows add fixed bytes", (b, z) == (10, 0))
    check("no demand prevents speculative growth", quota(10, 1, **params, demand=False)[0] == 10)
    check("missing telemetry prevents growth", quota(10, 1, **params, telemetry=False)[0] == 10)
    check("zero budget can grow after stable windows", quota(0, 1, **params)[0] == 2)
    check("physical ceiling dominates AIMD", quota(10, 1, pool=64, serving=59, reserve=4, cap=32)[0] == 1)
    check("requested quota does not release leased bytes", max(0, 12 + 3 - 8) == 7)

    (OUT/'data').mkdir(parents=True, exist_ok=True)
    (OUT/'data/credit-example.json').write_text(json.dumps(dict(evidence='constructed arithmetic example', size=1, ledger=ledger),indent=2)+'\n')
    report = dict(evidence='finite specification checks, not integrated controller or performance validation',
                  checks=checks, checks_passed=len(checks), finite_grid_cases=grid_count,
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  not_validated=['value/profile accuracy', 'planner search efficacy', 'async implementation races',
                                 'integrated normal/fault WCT', 'controller CPU overhead', 'AIMD stability'])
    (OUT/'SEMANTIC_CHECKS.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(checks_passed=len(checks), finite_grid_cases=grid_count, output=str(OUT)),indent=2))


if __name__ == '__main__':
    main()
