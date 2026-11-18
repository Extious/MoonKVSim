"""Revision 3 executable specification: shared, prefix-closed protection.

This serial event executor is intentionally separate from the frozen v1 DES and
Mooncake C++ runtime. It executes metadata/copy/ACK transitions, not CUDA copies.
All public operations must run under one pool owner (or an external mutex).
Times are monotonic nanoseconds; recovery costs and Slack are milliseconds.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class KVObject:
    key: str
    parent: str | None
    namespace: str
    size: int
    shards: int = 1

    @classmethod
    def sealed(
        cls, namespace: str, parent: str | None, token_ids: tuple[int, ...],
        size: int, shards: int = 1,
    ) -> KVObject:
        """Namespace binds tenant, model revision, adapters, KV ABI and layout.

        Tokens must describe completed immutable pages. The caller must also bind
        non-token inputs (e.g. image embeddings) into the namespace or content ID.
        """
        if not namespace or not token_ids or size <= 0 or shards <= 0:
            raise ValueError("sealed content, namespace, positive bytes/shards required")
        payload = json.dumps([namespace, parent, token_ids], separators=(",", ":"))
        return cls(hashlib.sha256(payload.encode()).hexdigest(), parent, namespace, size, shards)


@dataclass(frozen=True)
class Consumer:
    request: str
    namespace: str
    path: tuple[str, ...]
    recovery_ms: tuple[float, ...]
    slack_ms: float = 0.0
    ticket_ns: int = 0
    weight: float = 1.0
    route_epoch: int = 0
    expires_ns: int = 10**18
    active: bool = True

    def __post_init__(self) -> None:
        values = (*self.recovery_ms, self.slack_ms, self.weight)
        if any(not math.isfinite(x) or x < 0 for x in values):
            raise ValueError("costs, Slack and weights must be finite and nonnegative")
        if len(self.recovery_ms) != len(self.path) + 1:
            raise ValueError("one recovery estimate per frontier, including zero")
        if any(a < b for a, b in zip(self.recovery_ms, self.recovery_ms[1:], strict=False)):
            raise ValueError("recovery estimator must include best fallback at each prefix")
        if self.ticket_ns < 0 or self.expires_ns <= self.ticket_ns or self.route_epoch < 0:
            raise ValueError("invalid ticket lifetime or route epoch")


@dataclass(frozen=True)
class Plan:
    request: str
    epoch: int
    route_epoch: int
    add: frozenset[str]
    victims: frozenset[str]
    before_harm: float
    after_harm: float
    bytes_to_copy: int
    deadline_ns: int


@dataclass
class CopyTransaction:
    transaction: int
    plan: Plan
    acks: set[tuple[str, int]] = field(default_factory=set)
    terminal: str | None = None


class PrefixPool:
    """One tier/target, with a staging reserve inside its granted quota.

    COMMITTED, COPYING and RECLAIMING allocations count until a physical free
    ACK. Cancellation/free ACK means the worker fenced all outstanding DMA.
    One in-flight group per pool simplifies optimistic validation; throughput
    is a separate question. Retention consumers are bounded leases, not pins.
    """

    def __init__(
        self, quota: int, staging_bytes: int, *, max_group: int = 4,
        min_residence_ns: int = 1, improvement_ms: float = 1e-9,
    ) -> None:
        if not 0 < staging_bytes <= quota or max_group < 1 or min_residence_ns < 1:
            raise ValueError("positive, quota-bounded staging and group limits required")
        if not math.isfinite(improvement_ms) or improvement_ms < 0:
            raise ValueError("invalid improvement margin")
        self.quota = quota
        self.staging_bytes = staging_bytes
        self.max_group = max_group
        self.min_residence_ns = min_residence_ns
        self.improvement_ms = improvement_ms
        self.objects: dict[str, KVObject] = {}
        self.consumers: dict[str, Consumer] = {}
        self._children: dict[str, set[str]] = {}
        self._weighted_active: dict[str, Consumer] = {}
        self.committed: set[str] = set()
        self.allocations: dict[str, int] = {}
        self.reclaiming: dict[str, int] = {}
        self.leases: dict[str, tuple[frozenset[str], int]] = {}
        self.transactions: dict[int, CopyTransaction] = {}
        self.pending: int | None = None
        self.epoch = 0
        self._next_transaction = 1
        self._next_reclaim = 1
        self._issued_plan: Plan | None = None

    @property
    def physical_bytes(self) -> int:
        return sum(self.allocations.values())

    @property
    def steady_limit(self) -> int:
        return max(0, self.quota - self.staging_bytes)

    def nbytes(self, keys: set[str] | frozenset[str]) -> int:
        return sum(self.objects[k].size for k in keys)

    def register_object(self, obj: KVObject) -> None:
        if obj.size <= 0 or obj.shards <= 0 or not obj.namespace or not obj.key:
            raise ValueError("invalid immutable object")
        existing = self.objects.get(obj.key)
        if existing is not None:
            if existing != obj:
                raise ValueError("content key collision or incompatible allocation")
            return
        if obj.parent is not None:
            parent = self.objects.get(obj.parent)
            if parent is None or parent.namespace != obj.namespace:
                raise ValueError("unknown or incompatible parent")
        self.objects[obj.key] = obj
        if obj.parent is not None:
            self._children.setdefault(obj.parent, set()).add(obj.key)

    def update_consumer(self, consumer: Consumer) -> None:
        parent = None
        for key in consumer.path:
            obj = self.objects[key]
            if obj.parent != parent or obj.namespace != consumer.namespace:
                raise ValueError("consumer path must be a compatible contiguous prefix")
            parent = key
        old = self.consumers.get(consumer.request)
        if old is not None:
            if consumer == old:
                return
            if (consumer.route_epoch < old.route_epoch or consumer.ticket_ns < old.ticket_ns
                    or consumer.namespace != old.namespace):
                raise ValueError("stale consumer version or namespace change")
        self.consumers[consumer.request] = consumer
        if consumer.active and consumer.weight > 0:
            self._weighted_active[consumer.request] = consumer
        else:
            self._weighted_active.pop(consumer.request, None)
        self.epoch += 1

    def remove_consumer(self, request: str) -> None:
        if self.consumers.pop(request, None) is not None:
            self._weighted_active.pop(request, None)
            self.epoch += 1

    def frontier(self, request: str, keys: set[str] | frozenset[str] | None = None) -> int:
        visible = self.committed if keys is None else keys
        for i, key in enumerate(self.consumers[request].path):
            if key not in visible:
                return i
        return len(self.consumers[request].path)

    def harm(self, keys: set[str] | frozenset[str], now_ns: int) -> float:
        """Tier-local sum over distinct live calls; not a workflow WCT theorem."""
        total = 0.0
        for c in self._weighted_active.values():
            if not c.active or now_ns >= c.expires_ns:
                continue
            slack = max(0.0, c.slack_ms - max(0, now_ns - c.ticket_ns) / 1e6)
            total += c.weight * max(0.0, c.recovery_ms[self.frontier(c.request, keys)] - slack)
        return total

    def _closure(self, root: str, visible: set[str]) -> set[str]:
        cut = {root}
        pending = [root]
        while pending:
            parent = pending.pop()
            added = (self._children.get(parent, set()) & visible) - cut
            cut.update(added)
            pending.extend(added)
        return cut

    def pinned(self) -> set[str]:
        return {k for keys, _ in self.leases.values() for k in keys}

    def _victims(
        self, added: frozenset[str], protected: set[str], now_ns: int, limit: int,
    ) -> frozenset[str] | None:
        visible = set(self.committed)
        victims: set[str] = set()
        forbidden = protected | self.pinned()
        while self.nbytes(visible | added) > limit:
            baseline = self.harm(visible | added, now_ns)
            choices = []
            for root in sorted(visible):
                cut = self._closure(root, visible)
                if cut & forbidden:
                    continue
                loss = self.harm((visible - cut) | added, now_ns) - baseline
                choices.append((loss / self.nbytes(cut), self.nbytes(cut), root, cut))
            if not choices:
                return None
            cut = min(choices, key=lambda x: x[:3])[3]
            victims.update(cut)
            visible.difference_update(cut)
        return frozenset(victims)

    def plan(
        self, request: str, *, now_ns: int, source_available: set[str],
        copy_budget_bytes: int, copy_ns_per_byte: float, setup_ns: int = 0,
        permit_expires_ns: int = 10**18,
    ) -> Plan | None:
        """Retry on sealed-prefix, capacity, value, lifetime or permit changes.

        A None result pauses this tier's protection only. It never seals the
        request forever and never skips a missing prefix. No future KV is copied.
        The caller owns a source-read lease and a path-wide transfer permit.
        """
        if (now_ns < 0 or copy_budget_bytes < 0 or setup_ns < 0
                or not math.isfinite(copy_ns_per_byte) or copy_ns_per_byte < 0):
            raise ValueError("invalid copy budget/time")
        self._issued_plan = None
        if self.pending is not None or self.reclaiming:
            return None
        c = self.consumers[request]
        if not c.active or now_ns >= c.expires_ns:
            return None
        start = self.frontier(request)
        before = self.harm(self.committed, now_ns)
        best: Plan | None = None
        for stop in range(start + 1, min(len(c.path), start + self.max_group) + 1):
            add = frozenset(c.path[start:stop])
            if not add <= source_available:
                break
            size = self.nbytes(add)
            deadline = min(c.expires_ns - self.min_residence_ns, permit_expires_ns)
            if (size > min(self.staging_bytes, copy_budget_bytes)
                    or self.physical_bytes + size > self.quota
                    or now_ns + setup_ns + math.ceil(size * copy_ns_per_byte) >= deadline):
                continue
            victims = self._victims(add, set(c.path[:stop]), now_ns, self.steady_limit)
            if victims is None:
                continue
            after = self.harm((self.committed - victims) | add, now_ns)
            if before - after <= self.improvement_ms:
                continue
            candidate = Plan(request, self.epoch, c.route_epoch, add, victims,
                             before, after, size, deadline)
            if best is None or (after, size) < (best.after_harm, best.bytes_to_copy):
                best = candidate
        self._issued_plan = best
        return best

    def begin(self, plan: Plan, now_ns: int) -> int:
        c = self.consumers.get(plan.request)
        if (plan != self._issued_plan or self.pending is not None or self.reclaiming
                or plan.epoch != self.epoch
                or now_ns >= plan.deadline_ns or c is None or c.route_epoch != plan.route_epoch
                or plan.add & self.allocations.keys()
                or self.physical_bytes + plan.bytes_to_copy > self.quota):
            raise ValueError("stale or infeasible copy plan")
        # Plans are capabilities created by this owner's planner; re-evaluate to
        # prevent a caller from evicting pinned data or inventing profitable plans.
        if (plan.victims & self.pinned() or not plan.victims <= self.committed
                or self.nbytes(plan.add) != plan.bytes_to_copy
                or plan.bytes_to_copy > self.staging_bytes
                or self.nbytes((self.committed - plan.victims) | plan.add) > self.steady_limit):
            raise ValueError("invalid plan resources")
        self._check_prefix((self.committed - plan.victims) | plan.add)
        if self.harm(self.committed, now_ns) - self.harm(
            (self.committed - plan.victims) | plan.add, now_ns
        ) <= self.improvement_ms:
            raise ValueError("candidate no longer improves the current objective")
        txid = self._next_transaction
        self._next_transaction += 1
        self.transactions[txid] = CopyTransaction(txid, plan)
        self._issued_plan = None
        self.pending = txid
        for key in plan.add:
            self.allocations[key] = self.objects[key].size
        return txid

    def acknowledge_shard(self, transaction: int, key: str, shard: int) -> None:
        tx = self.transactions[transaction]
        if tx.terminal is not None:
            return  # Late/duplicate transfer ACK never resurrects an aborted copy.
        if key not in tx.plan.add or not 0 <= shard < self.objects[key].shards:
            raise ValueError("unexpected shard ACK")
        tx.acks.add((key, shard))

    def finish(self, transaction: int, now_ns: int, *, success: bool = True) -> str:
        tx = self.transactions[transaction]
        if tx.terminal is not None:
            return tx.terminal
        plan = tx.plan
        c = self.consumers.get(plan.request)
        expected = {(k, shard) for k in plan.add for shard in range(self.objects[k].shards)}
        valid = (success and tx.acks == expected and self.epoch == plan.epoch
                 and now_ns < plan.deadline_ns and c is not None
                 and c.route_epoch == plan.route_epoch and not plan.victims & self.pinned()
                 and self.physical_bytes <= self.quota
                 and self.nbytes((self.committed - plan.victims) | plan.add) <= self.steady_limit)
        if valid:
            valid = self.harm(self.committed, now_ns) - self.harm(
                (self.committed - plan.victims) | plan.add, now_ns
            ) > self.improvement_ms
        self.pending = None
        if valid:
            # Atomic visibility swap. Old copies survive until this point.
            self.committed.update(plan.add)
            self.committed.difference_update(plan.victims)
            self._queue_reclaim(plan.victims)
            tx.terminal = "COMMITTED"
        else:
            self._queue_reclaim(plan.add)
            tx.terminal = "ABORTED"
        self.epoch += 1
        self.check()
        return tx.terminal

    def _queue_reclaim(self, keys: set[str] | frozenset[str]) -> None:
        for key in sorted(keys):
            if key not in self.reclaiming:
                self.reclaiming[key] = self._next_reclaim
                self._next_reclaim += 1

    def reclaim_tasks(self) -> tuple[tuple[str, int], ...]:
        """Repeat these IDs until ACK, including after a failed delete RPC."""
        return tuple(sorted(self.reclaiming.items()))

    def acknowledge_free(self, key: str, reclaim_id: int) -> bool:
        if self.reclaiming.get(key) != reclaim_id:
            return False  # Stale ACK cannot free a later allocation of this key.
        if key in self.pinned():
            raise ValueError("worker must finish/cancel reads before physical free ACK")
        del self.reclaiming[key]
        del self.allocations[key]
        self.epoch += 1
        return True

    def acquire_read(
        self, lease_id: str, keys: set[str], until_ns: int, now_ns: int,
        *, primary_reserved: bool,
    ) -> None:
        if not primary_reserved or not keys <= self.committed or until_ns <= now_ns:
            raise ValueError("reserve primary destination before pinning a live source")
        lease = (frozenset(keys), until_ns)
        if lease_id in self.leases and self.leases[lease_id] != lease:
            raise ValueError("lease identity reused")
        self.leases[lease_id] = lease
        self.epoch += 1

    def expired_reads(self, now_ns: int) -> tuple[str, ...]:
        # Expiration requests cancellation; it is NOT proof that GPU DMA stopped.
        return tuple(k for k, (_, expiry) in self.leases.items() if expiry <= now_ns)

    def acknowledge_read_done(self, lease_id: str) -> None:
        if self.leases.pop(lease_id, None) is not None:
            self.epoch += 1

    def set_quota(self, quota: int, now_ns: int) -> int:
        """Immediate desired cap, asynchronous enforcement; return physical debt.

        Foreground may use reclaimed bytes ONLY after free ACK. If a read cannot
        be canceled promptly, its destination reservation/fallback must absorb it.
        """
        if quota < 0:
            raise ValueError("negative quota")
        self.quota = quota
        self.epoch += 1
        if self.pending is not None:
            self.finish(self.pending, now_ns, success=False)
        victims = self._victims(frozenset(), set(), now_ns, self.steady_limit)
        if victims is None:
            # Reclaim all available leaves/closures; active reads remain charged.
            visible = set(self.committed)
            victims_set: set[str] = set()
            for root in sorted(visible):
                cut = self._closure(root, visible)
                if not cut & self.pinned():
                    victims_set.update(cut)
            victims = frozenset(victims_set)
        self.committed.difference_update(victims)
        self._queue_reclaim(victims)
        self.check()
        return max(0, self.physical_bytes - quota)

    def collect_expired(self, now_ns: int) -> None:
        """Finished rounds may retain zero-weight references until a bounded TTL."""
        expired = [key for key, c in self.consumers.items() if c.expires_ns <= now_ns]
        for key in expired:
            self.remove_consumer(key)
        keep = {k for c in self.consumers.values() for k in c.path}
        keep.update(self.pinned())
        # A pinned descendant still needs all committed ancestors.
        for key in tuple(keep):
            parent = self.objects[key].parent
            while parent is not None:
                keep.add(parent)
                parent = self.objects[parent].parent
        victims = self.committed - keep
        if victims:
            self.committed.difference_update(victims)
            self._queue_reclaim(victims)
            self.epoch += 1

    def _check_prefix(self, keys: set[str] | frozenset[str]) -> None:
        if any(self.objects[k].parent not in keys and self.objects[k].parent is not None
               for k in keys):
            raise AssertionError("visible replica set is not prefix closed")

    def check(self) -> None:
        self._check_prefix(self.committed)
        assert not self.committed & self.reclaiming.keys()
        pending = set() if self.pending is None else set(self.transactions[self.pending].plan.add)
        assert not pending & (self.committed | self.reclaiming.keys())
        assert set(self.allocations) == self.committed | pending | self.reclaiming.keys()
        assert self.pinned() <= self.committed
        assert self.physical_bytes == self.nbytes(set(self.allocations))
