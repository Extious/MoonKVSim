"""Revision 3 foreground-constrained, revocable Peer-HBM budget specification.

The quota is a desired envelope, never evidence of physically freed bytes.
Physical enforcement is PrefixPool.set_quota + repeated reclaim/free ACKs.
An uncalibrated production controller grants zero backup quota by default.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryEnvelope:
    total_bytes: int
    nonrevocable_bytes: int
    primary_reserved_bytes: int
    next_primary_bytes: int
    burst_reserve_bytes: int
    allocator_reserve_bytes: int
    lendable_bytes: int

    def __post_init__(self) -> None:
        if any(x < 0 for x in vars(self).values()) or self.total_bytes == 0:
            raise ValueError("memory terms must be nonnegative, total must be positive")

    @property
    def backup_limit(self) -> int:
        """Disjoint reservations; next_primary is additional, not total demand.

        burst_reserve bounds incremental demand during copy cancel + free ACK.
        lendable_bytes must come from the serving allocator, not CUDA free alone.
        A fixed preallocated KV arena that cannot lend pages reports zero.
        """
        available = (self.total_bytes - self.nonrevocable_bytes - self.primary_reserved_bytes
                     - self.next_primary_bytes - self.burst_reserve_bytes
                     - self.allocator_reserve_bytes)
        return max(0, min(self.lendable_bytes, available))


@dataclass(frozen=True)
class QoSCertificate:
    profile: str
    region: str
    expires_ns: int
    quota_limit: int
    copy_bytes_per_second: int
    copy_batch_bytes: int
    max_reclaim_ns: int
    ttft_p99_relative_ucb: float
    tpot_p99_relative_ucb: float
    goodput_relative_loss_ucb: float
    evidence: str
    kind: str = "physical"

    def __post_init__(self) -> None:
        if self.kind not in {"physical", "modeled"} or not self.evidence:
            raise ValueError("certificate must identify measured or modeled evidence")
        if (not self.profile or not self.region or self.expires_ns < 0 or self.quota_limit < 0
                or self.copy_bytes_per_second < 0 or self.copy_batch_bytes < 0
                or self.max_reclaim_ns < 0):
            raise ValueError("invalid certificate domain or resources")
        for x in (self.ttft_p99_relative_ucb, self.tpot_p99_relative_ucb,
                  self.goodput_relative_loss_ucb):
            if not math.isfinite(x):
                raise ValueError("QoS bounds must be finite")


@dataclass(frozen=True)
class Observation:
    epoch: int
    sequence: int
    now_ns: int
    sampled_ns: int
    profile: str
    region: str
    memory: MemoryEnvelope
    backup_physical_bytes: int
    outstanding_reclaim_bytes: int
    useful_demand_bytes: int
    valid: bool = True
    foreground_violation: bool = False
    certificate: QoSCertificate | None = None

    def __post_init__(self) -> None:
        if min(self.epoch, self.sequence, self.now_ns, self.sampled_ns,
               self.backup_physical_bytes, self.outstanding_reclaim_bytes,
               self.useful_demand_bytes) < 0 or self.sampled_ns > self.now_ns:
            raise ValueError("invalid observation")
        if self.outstanding_reclaim_bytes > self.backup_physical_bytes:
            raise ValueError("reclaim debt is part of physical occupancy")


@dataclass(frozen=True)
class BudgetDecision:
    epoch: int
    sequence: int
    quota_bytes: int
    alpha: float
    memory_cap_bytes: int
    foreground_ready: bool
    pause_copy: bool
    reclaim_needed_bytes: int
    copy_bytes_per_second: int
    copy_batch_bytes: int
    permit_expires_ns: int
    reason: str


class ForegroundBudget:
    def __init__(
        self, *, epoch: int, registered_bytes: int, policy_cap_bytes: int,
        epsilon: float = 0.01, stable_ns: int = 1_000_000_000,
        grow_bytes_per_second: int = 256 * 1024 * 1024,
        max_observation_age_ns: int = 100_000_000,
        max_reclaim_ns: int = 10_000_000, allow_modeled: bool = False,
    ) -> None:
        if (epoch < 0 or registered_bytes <= 0 or not 0 <= policy_cap_bytes <= registered_bytes
                or not math.isfinite(epsilon) or epsilon < 0 or stable_ns < 0
                or grow_bytes_per_second <= 0 or max_observation_age_ns <= 0
                or max_reclaim_ns <= 0):
            raise ValueError("invalid foreground budget configuration")
        self.epoch = epoch
        self.registered_bytes = registered_bytes
        self.policy_cap_bytes = policy_cap_bytes
        self.epsilon = epsilon
        self.stable_ns = stable_ns
        self.grow_bytes_per_second = grow_bytes_per_second
        self.max_age_ns = max_observation_age_ns
        self.max_reclaim_ns = max_reclaim_ns
        self.allow_modeled = allow_modeled
        self.quota = 0
        self.healthy_since_ns: int | None = None
        self._last: Observation | None = None
        self._decision: BudgetDecision | None = None

    def _certificate_valid(self, obs: Observation) -> bool:
        c = obs.certificate
        return (c is not None and (c.kind == "physical" or self.allow_modeled)
                and c.profile == obs.profile and c.region == obs.region
                and obs.now_ns < c.expires_ns and c.max_reclaim_ns <= self.max_reclaim_ns
                and max(c.ttft_p99_relative_ucb, c.tpot_p99_relative_ucb,
                        c.goodput_relative_loss_ucb) <= self.epsilon)

    def observe(self, obs: Observation) -> BudgetDecision:
        if obs.epoch != self.epoch:
            raise ValueError("controller incarnation mismatch; reconcile inventory on restart")
        previous = self._last
        if previous is not None:
            if obs.sequence == previous.sequence:
                if obs != previous:
                    raise ValueError("observation ID reused with different content")
                assert self._decision is not None
                return self._decision
            if obs.sequence < previous.sequence or obs.now_ns < previous.now_ns:
                raise ValueError("stale control observation")
        cap = min(obs.memory.backup_limit, self.policy_cap_bytes, self.registered_bytes)
        healthy = (obs.valid and obs.now_ns - obs.sampled_ns <= self.max_age_ns
                   and not obs.foreground_violation and self._certificate_valid(obs))
        gap = previous is not None and obs.now_ns - previous.now_ns > self.max_age_ns
        domain_change = previous is not None and (
            obs.profile != previous.profile or obs.region != previous.region
            or obs.certificate != previous.certificate
        )
        dt = 0 if previous is None or gap or domain_change else obs.now_ns - previous.now_ns
        reason = "bounded-expansion"
        cert = obs.certificate
        if not healthy:
            self.quota = 0
            self.healthy_since_ns = None
            reason = "unknown-or-foreground-violation"
        else:
            assert cert is not None
            cap = min(cap, cert.quota_limit, obs.useful_demand_bytes)
            if self.healthy_since_ns is None or gap or domain_change:
                self.healthy_since_ns = obs.now_ns
            old_quota = self.quota
            self.quota = min(self.quota, cap)  # Every event may shrink immediately.
            if self.quota < old_quota:
                self.healthy_since_ns = obs.now_ns
                reason = "immediate-shrink"
            elif (obs.outstanding_reclaim_bytes == 0 and obs.backup_physical_bytes <= self.quota
                  and obs.now_ns - self.healthy_since_ns >= self.stable_ns):
                self.quota = min(cap, self.quota + self.grow_bytes_per_second * dt // 10**9)
            else:
                reason = "hold-for-stability-or-reclaim"
        debt = max(0, obs.backup_physical_bytes - self.quota)
        pause = not healthy or debt > 0 or obs.outstanding_reclaim_bytes > 0 or self.quota == 0
        expiry = obs.now_ns if cert is None else min(
            cert.expires_ns, obs.sampled_ns + self.max_age_ns
        )
        result = BudgetDecision(
            self.epoch, obs.sequence, self.quota, self.quota / self.registered_bytes,
            cap, obs.valid and obs.now_ns - obs.sampled_ns <= self.max_age_ns
            and obs.backup_physical_bytes <= obs.memory.backup_limit,
            pause, debt, 0 if pause or cert is None else cert.copy_bytes_per_second,
            0 if pause or cert is None else cert.copy_batch_bytes, expiry, reason,
        )
        self._last, self._decision = obs, result
        return result


@dataclass
class TransferBucket:
    rate_bytes_per_second: int
    burst_bytes: int
    batch_bytes: int
    expires_ns: int
    tokens: float = 0
    updated_ns: int = 0

    def __post_init__(self) -> None:
        if (min(self.rate_bytes_per_second, self.burst_bytes, self.batch_bytes,
                self.expires_ns, self.updated_ns) < 0 or not math.isfinite(self.tokens)
                or not 0 <= self.tokens <= self.burst_bytes):
            raise ValueError("invalid transfer bucket")


class TransferBudget:
    """Atomic source + target + shared-link tokens, used by both copy tiers.

    Each physical resource has one bucket shared by all paths. Transfer Engine
    must split groups into bounded DMA batches and recheck permits per batch.
    Unused permits expire; canceled work gets no refund for consumed service.
    """

    def __init__(self, buckets: dict[str, TransferBucket]) -> None:
        self.buckets = buckets

    def take(self, resources: tuple[str, ...], size: int, now_ns: int) -> bool:
        if size <= 0 or not resources or len(set(resources)) != len(resources):
            raise ValueError("positive bytes and unique path resource IDs required")
        selected = [self.buckets[key] for key in resources]
        if any(now_ns < b.updated_ns for b in selected):
            raise ValueError("transfer clock moved backwards")
        for bucket in selected:
            bucket.tokens = min(bucket.burst_bytes, bucket.tokens +
                                bucket.rate_bytes_per_second * (now_ns - bucket.updated_ns) / 1e9)
            bucket.updated_ns = now_ns
        if any(now_ns >= b.expires_ns or size > min(b.batch_bytes, b.tokens) for b in selected):
            return False
        for bucket in selected:
            bucket.tokens -= size
        return True
