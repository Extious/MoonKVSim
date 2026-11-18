"""Agent subleases, single-chunk admission and tail-only Landlord rent.

An owner serializes this metadata policy with physical copy/free operations.
The caller supplies a frozen decision-time WCT oracle. Normal cache-hit utility
is deliberately absent. Failed planning does not consume credits or renewal
rounds; an executed eviction cannot be rolled back after a later copy failure.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
from typing import Protocol


class RecoveryValue(Protocol):
    rounds: dict[str, int]

    def shares(self, resident: set[str], key: str) -> dict[str, float]:
        """Nonduplicated WCT marginals of adding key to a legal prefix forest."""
        ...

    def cost(self, resident: set[str]) -> float: ...

    def stamp(self, key: str, resident: set[str]) -> object: ...


@dataclass
class Subleases:
    credit: dict[str, float] = field(default_factory=dict)
    seen_round: dict[str, int] = field(default_factory=dict)
    value_stamp: object = None

    @property
    def total(self) -> float:
        return math.fsum(self.credit.values())

    def clone(self) -> Subleases:
        return Subleases(self.credit.copy(), self.seen_round.copy(), self.value_stamp)

    def charge(self, amount: float) -> None:
        total = self.total
        if amount < -1e-10 or amount > total + max(1e-10, total * 1e-10):
            raise ValueError("physical rent exceeds available credit")
        if total > 0:
            factor = max(0.0, 1.0 - amount / total)
            self.credit = {a: c * factor for a, c in self.credit.items()}


@dataclass
class LeasePlan:
    key: str | None
    status: str
    gain_ms: float
    loss_ms: float
    victims: tuple[str, ...]
    rent: float
    updates: dict[str, Subleases]
    baseline_version: int
    checks: int = 0
    evaluations: int = 0


class AgentLeasePolicy:
    def __init__(self, quota: int, *, eager_refresh: bool = False, strict_free_gain: bool = False):
        if quota < 0:
            raise ValueError("negative pool quota")
        self.quota = quota
        self.eager_refresh = eager_refresh
        self.strict_free_gain = strict_free_gain
        self.sizes: dict[str, int] = {}
        self.parents: dict[str, str | None] = {}
        self.children: dict[str, set[str]] = {}
        self.committed: set[str] = set()
        self.credits: dict[str, Subleases] = {}
        self.rent = 0.0
        self.version = 0
        self.counts: Counter = Counter()

    def register(self, key: str, parent: str | None, size: int) -> None:
        if size <= 0 or (parent is not None and parent not in self.parents):
            raise ValueError("invalid physical prefix object")
        if key in self.parents:
            if (self.parents[key], self.sizes[key]) != (parent, size):
                raise ValueError("physical object identity changed")
            return
        self.parents[key], self.sizes[key] = parent, size
        if parent is not None:
            self.children.setdefault(parent, set()).add(key)

    def nbytes(self, keys: set[str]) -> int:
        return sum(self.sizes[k] for k in keys)

    def ancestors(self, key: str) -> set[str]:
        result = set()
        parent = self.parents[key]
        while parent is not None:
            result.add(parent)
            parent = self.parents[parent]
        return result

    def tails(self, resident: set[str], pinned: set[str]) -> list[str]:
        return sorted(k for k in resident - pinned if not self.children.get(k, set()) & resident)

    def _refresh(
        self, key: str, resident: set[str], values: RecoveryValue, updates: dict[str, Subleases]
    ) -> tuple[Subleases, bool]:
        lease = updates.get(key)
        if lease is None:
            lease = self.credits.get(key, Subleases()).clone()
            updates[key] = lease
        stamp = values.stamp(key, resident)
        if not self.eager_refresh and lease.value_stamp == stamp:
            return lease, False
        grants = values.shares(resident - {key}, key)
        updated = {}
        for a, gain in grants.items():
            if not math.isfinite(gain) or gain < -1e-8:
                raise ValueError("recovery oracle returned negative/nonfinite shared gain")
            gain = max(0.0, gain)
            current_round = values.rounds[a]
            new_round = lease.seen_round.get(a, -1) < current_round
            updated[a] = gain if new_round else min(lease.credit.get(a, 0.0), gain)
            lease.seen_round[a] = current_round
        # Tombstone round IDs survive detach/rejoin within a lifecycle.
        lease.credit, lease.value_stamp = updated, stamp
        return lease, True

    def _trial(
        self,
        resident: set[str],
        capacity: int,
        pinned: set[str],
        values: RecoveryValue,
        *,
        key: str | None,
        gain: float,
        extended_cost: float,
    ) -> LeasePlan:
        draft = resident.copy()
        updates: dict[str, Subleases] = {}
        rent, victims, checks, evaluations = self.rent, [], 0, 0
        while self.nbytes(draft) > capacity:
            q = self.tails(draft, pinned)
            if not q:
                return LeasePlan(key, "WAIT_FOR_UNPIN", gain, 0, (), self.rent, {}, self.version)
            # A non-head key can decrease. Inspect every eligible tail before
            # advancing L, while cached unchanged values avoid DAG evaluation.
            remaining = {}
            for y in q:
                lease, evaluated = self._refresh(y, draft, values, updates)
                remaining[y] = lease.total
                checks += 1
                evaluations += int(evaluated)
            delta, victim = min((remaining[y] / self.sizes[y], y) for y in q)
            rent += delta
            for y in q:
                updates[y].charge(self.sizes[y] * delta)
            # Eliminate round-off only on the selected exact minimum.
            updates[victim].credit = {a: 0.0 for a in updates[victim].credit}
            draft.remove(victim)
            victims.append(victim)
        loss = max(0.0, values.cost(draft) - extended_cost) if victims else 0.0
        accepted = key is None or (
            gain > loss + 1e-9
            if victims
            else gain > 1e-9
            if self.strict_free_gain
            else gain >= -1e-9
        )
        return LeasePlan(
            key,
            ("RECLAIM" if key is None else "REPLACE" if victims else "ADMIT")
            if accepted
            else "BYPASS",
            gain,
            loss,
            tuple(victims),
            rent,
            updates if accepted else {},
            self.version,
            checks,
            evaluations,
        )

    def plan(
        self, key: str, values: RecoveryValue, *, pinned: set[str], pending_bytes: int = 0
    ) -> LeasePlan:
        def reject(status):
            return LeasePlan(key, status, 0, 0, (), self.rent, {}, self.version)

        if key in self.committed:
            return reject("REUSE")
        if key not in self.sizes:
            raise ValueError("unknown candidate")
        ancestors = self.ancestors(key)
        if not ancestors <= self.committed:
            return reject("WAIT_FOR_PREFIX")
        capacity = self.quota - pending_bytes
        if self.nbytes(self.committed) > capacity:
            return reject("WAIT_FOR_RECLAIM")
        if self.nbytes(ancestors | pinned | {key}) > capacity:
            return reject("BYPASS")
        grants = values.shares(self.committed, key)
        gain = max(0.0, math.fsum(grants.values()))
        draft = self.committed | {key}
        extended = values.cost(draft) if self.nbytes(draft) > capacity else 0.0
        return self._trial(
            draft,
            capacity,
            pinned | ancestors | {key},
            values,
            key=key,
            gain=gain,
            extended_cost=extended,
        )

    def reclaim(self, capacity: int, values: RecoveryValue, *, pinned: set[str]) -> LeasePlan:
        if capacity < 0:
            raise ValueError("negative reclaim target")
        return self._trial(
            self.committed,
            capacity,
            pinned,
            values,
            key=None,
            gain=0.0,
            extended_cost=values.cost(self.committed),
        )

    def apply_releases(self, plan: LeasePlan) -> None:
        """Apply after fenced victim frees; candidate is still uncommitted."""
        if plan.baseline_version != self.version or plan.status not in {
            "ADMIT",
            "REPLACE",
            "RECLAIM",
        }:
            raise ValueError("stale or rejected admission plan")
        if not set(plan.victims) <= self.committed:
            raise ValueError("release is not backed by a committed allocation")
        self.committed.difference_update(plan.victims)
        self.credits.update(plan.updates)
        for key in plan.victims:
            self.credits.pop(key, None)
        self.rent = plan.rent
        self.counts["tail_checks"] += plan.checks
        self.counts["refresh_evaluations"] += plan.evaluations
        self.counts["evictions"] += len(plan.victims)
        self.version += 1

    def commit(self, key: str, values: RecoveryValue) -> None:
        """Initialize a new physical lease only after the complete copy ACK."""
        if key in self.committed or not self.ancestors(key) <= self.committed:
            raise ValueError("duplicate or noncontiguous copy commit")
        grants = values.shares(self.committed, key)
        self.credits[key] = Subleases(
            {a: max(0.0, g) for a, g in grants.items()},
            {a: values.rounds[a] for a in grants},
        )
        self.committed.add(key)
        self.version += 1
        self.counts["commits"] += 1

    def refresh_hit(self, keys: set[str], values: RecoveryValue, *, pinned: set[str]) -> None:
        """Refresh eligible hit tails; internal/reading chunks retain balances."""
        updates: dict[str, Subleases] = {}
        q = set(self.tails(self.committed, pinned)) & keys
        for key in sorted(q):
            _, evaluated = self._refresh(key, self.committed, values, updates)
            self.counts["hit_refresh_evaluations"] += int(evaluated)
        self.credits.update(updates)
        if updates:
            self.version += 1

    def check(self) -> None:
        if set(self.credits) != self.committed:
            raise AssertionError("physical chunks and credit accounts differ")
        for key in self.committed:
            if self.parents[key] is not None and self.parents[key] not in self.committed:
                raise AssertionError("hole in committed prefix")
            if any(not math.isfinite(v) or v < -1e-9 for v in self.credits[key].credit.values()):
                raise AssertionError("invalid remaining credit")
