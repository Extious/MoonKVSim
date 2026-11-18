"""One-pool reference for plan versions, physical frees and copy publication.

No CUDA/network operations are executed. Workers must fence DMA before free_ack.
One transaction at a time; an aborted replacement does not resurrect victims.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from reference import Model, Problem, Solution


@dataclass
class Transaction:
    key: int
    target: int
    add: set[str]
    victims: set[str]
    epoch: int
    required_acks: set[tuple[str, int]]
    acks: set[tuple[str, int]] = field(default_factory=set)
    state: str = 'FREEING'


class Pool:
    def __init__(self, model: Model, quota: int, committed=0):
        if not model.legal(committed) or model.size(committed) > quota:
            raise ValueError('invalid initial physical pool')
        self.model, self.quota, self.committed = model, quota, committed
        self.epoch, self.next_tx = 0, 1
        self.allocations = {k: 'COMMITTED' for k in model.keys(committed)}
        self.allocation_ids = {k: 0 for k in self.allocations}
        self.pending = None
        self.transactions = {}

    @property
    def physical_bytes(self):
        return sum(self.model.chunks[self.model.index[k]].size for k in self.allocations)

    def begin(self, problem: Problem, result: Solution, epoch: int, *, shards=1,
              force=False, require_exact=True):
        if self.pending is not None or any(v == 'RETIRING' for v in self.allocations.values()):
            raise RuntimeError('DEFER: previous DMA/free obligations are unfinished')
        if epoch != self.epoch or problem.model is not self.model or problem.current != self.committed:
            raise RuntimeError('STALE_PLAN')
        if problem.capacity != self.quota or not problem.feasible(result.mask) or shards < 1:
            raise ValueError('invalid quota/target/shard count')
        if not result.exact and not force and require_exact:
            raise RuntimeError('DEFER: strict mode requires a complete decision certificate')
        if result.value != self.model.gain(result.mask):
            raise ValueError('incorrect value attached to target')
        if force:
            if result.mask & ~self.committed:
                raise ValueError('forced shrink must not allocate new backups')
        elif result.value <= self.model.gain(self.committed):
            return None  # No strict improvement: keep current, avoid equal-value churn.
        add = set(self.model.keys(result.mask & ~self.committed))
        victims = set(self.model.keys(self.committed & ~result.mask))
        t = Transaction(self.next_tx, result.mask, add, victims, self.epoch,
                        {(k, s) for k in add for s in range(shards)})
        self.next_tx += 1
        self.transactions[t.key] = t
        self.pending = t.key
        # Remove recovery eligibility, then release leaves before their parents.
        for k in sorted(victims, key=lambda x: self.model.index[x], reverse=True):
            self.allocations[k] = 'RETIRING'
        self.committed &= result.mask
        assert self.model.legal(self.committed)
        self._start_copy(t)
        return t.key

    def free_ack(self, key, allocation_id):
        if (self.allocations.get(key) != 'RETIRING'
                or self.allocation_ids.get(key) != allocation_id):
            return False
        # Callback is issued only after the worker has fenced all uses of key.
        del self.allocations[key]
        del self.allocation_ids[key]
        if self.pending is not None:
            self._start_copy(self.transactions[self.pending])
        return True

    def _start_copy(self, t):
        if t.state != 'FREEING' or any(k in self.allocations for k in t.victims):
            return
        needed = sum(self.model.chunks[self.model.index[k]].size for k in t.add)
        if self.physical_bytes + needed > self.quota:
            self.abort(t.key)
            return
        for k in t.add:
            if k in self.allocations:
                raise AssertionError('duplicate physical allocation')
            self.allocations[k] = 'COPYING'
            self.allocation_ids[k] = t.key
        t.state = 'COPYING'
        if not t.required_acks:
            self._publish(t)

    def copy_ack(self, transaction, key, shard, success=True):
        t = self.transactions.get(transaction)
        if t is None or t.state != 'COPYING':
            return False
        if not success:
            self.abort(transaction)
            return False
        if (key, shard) not in t.required_acks:
            raise ValueError('unexpected chunk/shard ACK')
        t.acks.add((key, shard))
        if t.acks == t.required_acks:
            self._publish(t)
        return True

    def _publish(self, t):
        if t.epoch != self.epoch or self.physical_bytes > self.quota:
            self.abort(t.key)
            return
        for k in t.add:
            self.allocations[k] = 'COMMITTED'
        self.committed = t.target
        assert self.model.legal(self.committed)
        t.state = 'COMMITTED'
        self.pending = None
        self.epoch += 1

    def abort(self, transaction):
        t = self.transactions[transaction]
        if t.state in ('ABORTED', 'COMMITTED'):
            return
        for k in t.add:
            if k in self.allocations:
                self.allocations[k] = 'RETIRING'
        t.state = 'ABORTED'
        self.pending = None
        self.epoch += 1

    def external_change(self, *, quota=None, model=None):
        # Request/profile/ref/source/route changes use this invalidation path.
        # Existing physical IDs must retain their identity/size/layout binding.
        if model is not None:
            for key in self.allocations:
                if key not in model.index or (model.chunks[model.index[key]] !=
                                               self.model.chunks[self.model.index[key]]):
                    raise ValueError('cannot rewrite identity of allocated KV')
        if quota is not None:
            if quota < 0:
                raise ValueError('negative quota')
            self.quota = quota
        if self.pending is not None:
            self.abort(self.pending)
        else:
            self.epoch += 1
        if model is not None:
            keys = self.model.keys(self.committed)
            self.model = model
            self.committed = model.mask(keys)
