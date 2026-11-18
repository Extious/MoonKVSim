"""Event adapter joining revision-3 admission, foreground gating and copy ACKs.

Caller supplies scheduler/allocator observations and physically fenced ACKs.
This is an executable reference adapter, not the old experiment.py execution
path and not a replacement for the native Mooncake connector.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .foreground_budget import (
    BudgetDecision,
    ForegroundBudget,
    Observation,
    TransferBucket,
    TransferBudget,
)
from .prefix_frontier import PrefixPool


@dataclass
class RevisionRuntime:
    pools: dict[str, PrefixPool]
    hbm_pool: str
    governor: ForegroundBudget
    transfers: TransferBudget
    copy_resources: dict[str, tuple[str, ...]]
    decision: BudgetDecision | None = None
    last_observation: Observation | None = None

    def observe_foreground(self, observation: Observation) -> BudgetDecision:
        if self.decision is not None and observation.sequence == self.decision.sequence:
            # The earlier command may already have queued physical reclaim debt.
            # Exact packet retry returns its decision without reapplying/recounting.
            return self.governor.observe(observation)
        pool = self.pools[self.hbm_pool]
        if (observation.backup_physical_bytes != pool.physical_bytes
                or observation.outstanding_reclaim_bytes != pool.nbytes(set(pool.reclaiming))):
            raise ValueError("observation must reconcile the physical allocation ledger")
        decision = self.governor.observe(observation)
        if decision == self.decision:
            return decision
        resource = "__hbm_governor__"
        prior = self.transfers.buckets.get(resource)
        tokens = 0.0
        if prior is not None and observation.now_ns < prior.expires_ns:
            tokens = min(prior.burst_bytes, prior.tokens + prior.rate_bytes_per_second *
                         (observation.now_ns - prior.updated_ns) / 1e9)
        self.transfers.buckets[resource] = TransferBucket(
            decision.copy_bytes_per_second, decision.copy_batch_bytes,
            decision.copy_batch_bytes, decision.permit_expires_ns,
            min(tokens, decision.copy_batch_bytes), observation.now_ns,
        )
        # Do not replay a side effect for duplicate observations or unchanged caps.
        # Debt is still retried via reclaim_tasks(), not inferred from quota changes.
        if (pool.quota != decision.quota_bytes
                or pool.nbytes(pool.committed) > pool.steady_limit):
            pool.set_quota(decision.quota_bytes, observation.now_ns)
        self.decision = decision
        self.last_observation = observation
        return decision

    def watchdog(self, now_ns: int, sequence: int) -> dict[str, tuple[str, ...]]:
        """Timer events cancel expired copies/permits without inventing samples.

        sequence comes from the same target owner as foreground observations.
        Returned expired read IDs require worker cancellation and explicit ACK.
        """
        cancellations = {}
        for name, pool in self.pools.items():
            if pool.pending is not None:
                tx = pool.transactions[pool.pending]
                if now_ns >= tx.plan.deadline_ns:
                    pool.finish(pool.pending, now_ns, success=False)
            pool.collect_expired(now_ns)
            cancellations[name] = pool.expired_reads(now_ns)
        if (self.decision is not None and self.last_observation is not None
                and now_ns >= self.decision.permit_expires_ns):
            pool = self.pools[self.hbm_pool]
            self.observe_foreground(replace(
                self.last_observation, sequence=sequence, now_ns=now_ns, valid=False,
                backup_physical_bytes=pool.physical_bytes,
                outstanding_reclaim_bytes=pool.nbytes(set(pool.reclaiming)),
            ))
        return cancellations

    def begin_independent(
        self, request: str, now_ns: int, source_available: set[str], *,
        copy_budget_bytes: int, copy_ns_per_byte: float, permit_expires_ns: int,
    ) -> dict[str, int | None]:
        result: dict[str, int | None] = {}
        for name, pool in self.pools.items():
            deadline = permit_expires_ns
            if name == self.hbm_pool:
                if (self.decision is None or self.decision.pause_copy
                        or now_ns >= self.decision.permit_expires_ns):
                    result[name] = None
                    continue
                deadline = min(deadline, self.decision.permit_expires_ns)
            plan = pool.plan(request, now_ns=now_ns, source_available=source_available,
                             copy_budget_bytes=copy_budget_bytes,
                             copy_ns_per_byte=copy_ns_per_byte, permit_expires_ns=deadline)
            result[name] = None if plan is None else pool.begin(plan, now_ns)
        return result

    def copy_batch(self, pool: str, size: int, now_ns: int) -> bool:
        if pool == self.hbm_pool and (
            self.decision is None or self.decision.pause_copy
            or now_ns >= self.decision.permit_expires_ns
            or size > self.decision.copy_batch_bytes
        ):
            return False
        resources = self.copy_resources[pool]
        if pool == self.hbm_pool:
            resources = (*resources, "__hbm_governor__")
        return self.transfers.take(resources, size, now_ns)
