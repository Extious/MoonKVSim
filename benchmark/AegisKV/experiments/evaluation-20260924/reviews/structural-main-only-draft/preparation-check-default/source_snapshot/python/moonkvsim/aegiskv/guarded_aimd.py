"""Windowed Algorithm 3 from the user's independent Guarded AIMD design.

The memory ceiling and workload-normalized foreground warning are distinct
inputs. A grant is an upper bound, not an allocation or a physical free ACK.
This controller does not manufacture a QoS certificate or prove zero overhead.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class AIMDObservation:
    sequence: int
    now_ns: int
    memory_cap_bytes: int
    physical_backup_bytes: int
    reclaim_bytes: int
    warning: bool
    valid: bool
    demand: bool
    adjustment_complete: bool

    def __post_init__(self):
        if (
            min(
                self.sequence,
                self.now_ns,
                self.memory_cap_bytes,
                self.physical_backup_bytes,
                self.reclaim_bytes,
            )
            < 0
        ):
            raise ValueError("negative AIMD observation")
        if self.reclaim_bytes > self.physical_backup_bytes:
            raise ValueError("reclaim bytes are still physically occupied")


@dataclass(frozen=True)
class AIMDDecision:
    sequence: int
    now_ns: int
    previous_quota_bytes: int
    quota_bytes: int
    memory_cap_bytes: int
    stable_windows: int
    alpha: float
    reclaim_needed_bytes: int
    pause_copy: bool
    reason: str


class GuardedAIMD:
    def __init__(
        self,
        *,
        denominator_bytes: int,
        policy_cap_bytes: int,
        additive_bytes: int = 256 * 1024**2,
        beta: float = 0.5,
        stable_windows: int = 4,
        window_ns: int = 50_000_000,
    ):
        if (
            denominator_bytes <= 0
            or not 0 <= policy_cap_bytes <= denominator_bytes
            or additive_bytes <= 0
            or stable_windows < 1
            or window_ns <= 0
            or not math.isfinite(beta)
            or not 0 < beta < 1
        ):
            raise ValueError("invalid Guarded AIMD configuration")
        self.denominator = denominator_bytes
        self.policy_cap = policy_cap_bytes
        self.additive = additive_bytes
        self.beta = beta
        self.required_stable = stable_windows
        self.window_ns = window_ns
        self.quota = 0
        self.stable = 0
        self.last: AIMDObservation | None = None
        self.decision: AIMDDecision | None = None

    def observe(self, obs: AIMDObservation) -> AIMDDecision:
        if self.last is not None:
            if obs.sequence == self.last.sequence:
                if obs != self.last:
                    raise ValueError("AIMD sequence reused with different input")
                assert self.decision is not None
                return self.decision
            if obs.sequence < self.last.sequence or obs.now_ns <= self.last.now_ns:
                raise ValueError("out-of-order AIMD window")
            if obs.now_ns - self.last.now_ns < self.window_ns:
                raise ValueError("AIMD must update once per complete window")
            if obs.now_ns - self.last.now_ns > self.window_ns:
                self.stable = 0  # Missing observations are not stable windows.
        previous = self.quota
        cap = min(obs.memory_cap_bytes, self.policy_cap)
        if not obs.valid:
            target, self.stable, reason = 0, 0, "invalid-feedback"
        elif obs.warning:
            target, self.stable, reason = math.floor(self.beta * previous), 0, "decrease"
        else:
            self.stable = min(self.required_stable, self.stable + 1)
            can_grow = (
                self.stable >= self.required_stable
                and cap > previous
                and obs.demand
                and obs.adjustment_complete
                and obs.reclaim_bytes == 0
                and obs.physical_backup_bytes <= previous
            )
            if can_grow:
                target, self.stable, reason = previous + self.additive, 0, "increase"
            else:
                target, reason = previous, "hold"
        self.quota = min(cap, target)
        if self.quota < previous and reason not in {"decrease", "invalid-feedback"}:
            reason = "memory-clip"
        if self.quota < previous:
            self.stable = 0
        debt = max(0, obs.physical_backup_bytes - self.quota)
        result = AIMDDecision(
            obs.sequence,
            obs.now_ns,
            previous,
            self.quota,
            cap,
            self.stable,
            self.quota / self.denominator,
            debt,
            not obs.valid or self.quota == 0 or debt > 0 or obs.reclaim_bytes > 0,
            reason,
        )
        self.last, self.decision = obs, result
        return result

    def clip_for_foreground(self, cap_bytes: int) -> int:
        """Allocation-time safety clip; it never counts an extra AIMD window."""
        if cap_bytes < 0:
            raise ValueError("negative capacity")
        if cap_bytes < self.quota:
            self.quota = cap_bytes
            self.stable = 0
        return self.quota
