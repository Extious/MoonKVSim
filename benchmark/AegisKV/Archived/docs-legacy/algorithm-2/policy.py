"""Event-driven metadata controller for the capacity-rent model.

This runs no GPU work. Callers supply causally available, validated model
snapshots and execute/fence the returned allocation, copy and free obligations.
"""
from __future__ import annotations

from dataclasses import dataclass
from protocol import Pool
from reference import (ComponentCache, Model, Problem, ProfileBudgetExceeded,
                       Solution, ValueCache, fractional_bound, solve, solve_components)


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    result: Solution | None = None
    transaction: int | None = None
    path: str | None = None


class Controller:
    def __init__(self, model: Model, quota: int, committed=0, *,
                 require_exact=False, max_configurations=100000,
                 max_transitions=1000000, max_pops=10000):
        self.pool = Pool(model, quota, committed)
        self.values, self.profiles = ValueCache(model), ComponentCache()
        self.require_exact = require_exact
        self.max_configurations = max_configurations
        self.max_transitions = max_transitions
        self.max_pops = max_pops
        self.queued_model = None

    def update(self, *, model=None, quota=None, hard=False):
        # Pure valuation updates can wait for the current valid copy transaction.
        # Source, layout, read-pin or fault changes MUST use hard=True; quota
        # changes always invalidate immediately. Coalescing prevents unrelated
        # new chunks from repeatedly aborting an otherwise valid copy.
        if model is not None and quota is None and not hard and self.pool.pending is not None:
            self.queued_model = model
            return
        if model is None:
            model = self.queued_model
        self.pool.external_change(model=model, quota=quota)
        self.queued_model = None
        if model is not None:
            self.values.update(model)

    def decide(self, *, required=0, available=None, shards=1):
        if self.queued_model is not None and self.pool.pending is None:
            self.update(model=self.queued_model)
        pool, model = self.pool, self.pool.model
        if pool.pending is not None or any(s == 'RETIRING' for s in pool.allocations.values()):
            return Decision('DEFER', 'copy or physical free is unfinished')
        force = model.size(pool.committed) > pool.quota
        if force:
            # Reclamation cannot depend on allocating another physical copy.
            available = pool.committed
        try:
            problem = Problem(model, pool.quota, pool.committed, required, available)
        except ValueError as error:
            return Decision('DEFER', str(error))
        start = self.values.workflow_evaluations
        try:
            mask, value, _ = solve_components(problem, self.profiles, self.values,
                max_configurations=self.max_configurations,
                max_transitions=self.max_transitions)
            rent = fractional_bound(model, problem.allowed, problem.capacity).rent
            result = Solution(mask, value, value, True, 0,
                              self.values.workflow_evaluations-start, 0, rent)
            path = 'complete component profiles and integer DP'
        except ProfileBudgetExceeded:
            result = solve(problem, self.values, max_pops=self.max_pops)
            path = 'bounded search with an objective interval'
        if self.require_exact and not result.exact and not force:
            return Decision('DEFER', 'exact mode awaits a complete certificate', result, path=path)
        if not force and result.value <= model.gain(pool.committed):
            reason = 'no better feasible candidate found within budget'
            if result.exact:
                reason = 'current allocation attains the model optimum'
            return Decision('KEEP', reason, result, path=path)
        transaction = pool.begin(problem, result, pool.epoch, shards=shards,
                                 force=force, require_exact=self.require_exact)
        return Decision('RECLAIM' if force else 'REPLACE',
                        'fence frees, then copy and publish after all shard ACKs',
                        result, transaction, path)
