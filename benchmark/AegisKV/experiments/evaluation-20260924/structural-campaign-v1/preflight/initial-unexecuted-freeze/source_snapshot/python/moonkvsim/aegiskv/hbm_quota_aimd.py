"""Pure-GlobalDES Peer-HBM quota AIMD.

The controller implements the patent formula verbatim for each target ``p``::

    pressure: alpha_p <- max(alpha_min, gamma * alpha_p); z_p <- 0
    stable:   if z_p + 1 >= K:
                  alpha_p <- min(alpha_max, alpha_p + delta); z_p <- 0
              else:
                  z_p <- z_p + 1
    quota_p = alpha_p * M_p

It changes only the Peer-HBM protection quota.  Victim selection, Store DRAM,
transfer ownership, and physical reclamation deliberately remain outside this
module.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

from moonkvsim.common.hash import canonical_json_bytes, sha256_json


class AIMDAction(StrEnum):
    MULTIPLICATIVE_DECREASE = "MULTIPLICATIVE_DECREASE"
    STABLE_WINDOW = "STABLE_WINDOW"
    ADDITIVE_INCREASE = "ADDITIVE_INCREASE"


def _decimal_text(value: Decimal) -> str:
    """Return one exponent-free canonical decimal spelling."""

    if not value.is_finite():
        raise ValueError("AIMD values must be finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


@dataclass(frozen=True, slots=True)
class AIMDParameters:
    minimum_fraction: Decimal
    maximum_fraction: Decimal
    multiplicative_decrease: Decimal
    additive_increase: Decimal
    stable_window_count: int

    def __post_init__(self) -> None:
        values = (
            self.minimum_fraction,
            self.maximum_fraction,
            self.multiplicative_decrease,
            self.additive_increase,
        )
        if any(not value.is_finite() for value in values):
            raise ValueError("AIMD parameters must be finite")
        if not Decimal(0) <= self.minimum_fraction <= self.maximum_fraction <= Decimal(1):
            raise ValueError("AIMD quota fractions must satisfy 0 <= min <= max <= 1")
        if not Decimal(0) < self.multiplicative_decrease < Decimal(1):
            raise ValueError("multiplicative_decrease must be strictly between zero and one")
        if self.additive_increase <= 0:
            raise ValueError("additive_increase must be positive")
        if self.stable_window_count <= 0:
            raise ValueError("stable_window_count must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "additive_increase": _decimal_text(self.additive_increase),
            "maximum_fraction": _decimal_text(self.maximum_fraction),
            "minimum_fraction": _decimal_text(self.minimum_fraction),
            "multiplicative_decrease": _decimal_text(self.multiplicative_decrease),
            "stable_window_count": self.stable_window_count,
        }


@dataclass(frozen=True, slots=True)
class AIMDTargetState:
    target_id: str
    peer_hbm_capacity_bytes: int
    protection_fraction: Decimal
    stable_windows: int = 0
    last_update_ns: int | None = None

    def __post_init__(self) -> None:
        if not self.target_id:
            raise ValueError("target_id must be non-empty")
        if self.peer_hbm_capacity_bytes <= 0:
            raise ValueError("peer_hbm_capacity_bytes must be positive")
        if not self.protection_fraction.is_finite():
            raise ValueError("protection_fraction must be finite")
        if self.stable_windows < 0:
            raise ValueError("stable_windows must be non-negative")
        if self.last_update_ns is not None and self.last_update_ns < 0:
            raise ValueError("last_update_ns must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "last_update_ns": self.last_update_ns,
            "peer_hbm_capacity_bytes": self.peer_hbm_capacity_bytes,
            "protection_fraction": _decimal_text(self.protection_fraction),
            "stable_windows": self.stable_windows,
            "target_id": self.target_id,
        }


@dataclass(frozen=True, slots=True)
class AIMDDecision:
    timestamp_ns: int
    action: AIMDAction
    foreground_pressure: bool
    current_protection_bytes: int
    quota_bytes: int
    bytes_to_reclaim: int
    admission_blocked: bool
    previous_state: AIMDTargetState
    next_state: AIMDTargetState
    parameters: AIMDParameters

    def canonical_fields(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "admission_blocked": self.admission_blocked,
            "bytes_to_reclaim": self.bytes_to_reclaim,
            "controller_scope": "PEER_HBM_QUOTA_ONLY",
            "current_protection_bytes": self.current_protection_bytes,
            "foreground_pressure": self.foreground_pressure,
            "next_state": self.next_state.to_dict(),
            "parameters": self.parameters.to_dict(),
            "previous_state": self.previous_state.to_dict(),
            "quota_bytes": self.quota_bytes,
            "timestamp_ns": self.timestamp_ns,
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        return {**self.canonical_fields(), "fingerprint": self.fingerprint}

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict()) + b"\n"


class HBMQuotaAIMD:
    """Deterministic per-control-window implementation of the frozen AIMD formula."""

    def __init__(self, parameters: AIMDParameters) -> None:
        self.parameters = parameters

    def update(
        self,
        state: AIMDTargetState,
        *,
        foreground_pressure: bool,
        current_protection_bytes: int,
        timestamp_ns: int,
    ) -> AIMDDecision:
        if not isinstance(foreground_pressure, bool):
            raise TypeError("foreground_pressure must be a bool")
        if timestamp_ns < 0:
            raise ValueError("timestamp_ns must be non-negative")
        if state.last_update_ns is not None and timestamp_ns <= state.last_update_ns:
            raise ValueError("AIMD updates for one target require strictly increasing DES time")
        if not 0 <= current_protection_bytes <= state.peer_hbm_capacity_bytes:
            raise ValueError("current Peer-HBM protection bytes must fit target capacity")
        if not (
            self.parameters.minimum_fraction
            <= state.protection_fraction
            <= self.parameters.maximum_fraction
        ):
            raise ValueError("target protection fraction is outside configured AIMD bounds")
        if state.stable_windows >= self.parameters.stable_window_count:
            raise ValueError("stable_windows is not a reachable AIMD state")

        if foreground_pressure:
            action = AIMDAction.MULTIPLICATIVE_DECREASE
            next_fraction = max(
                self.parameters.minimum_fraction,
                self.parameters.multiplicative_decrease * state.protection_fraction,
            )
            next_stable_windows = 0
        elif state.stable_windows + 1 >= self.parameters.stable_window_count:
            action = AIMDAction.ADDITIVE_INCREASE
            next_fraction = min(
                self.parameters.maximum_fraction,
                state.protection_fraction + self.parameters.additive_increase,
            )
            next_stable_windows = 0
        else:
            action = AIMDAction.STABLE_WINDOW
            next_fraction = state.protection_fraction
            next_stable_windows = state.stable_windows + 1

        quota_bytes = int(
            (next_fraction * Decimal(state.peer_hbm_capacity_bytes)).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        bytes_to_reclaim = max(0, current_protection_bytes - quota_bytes)
        next_state = AIMDTargetState(
            target_id=state.target_id,
            peer_hbm_capacity_bytes=state.peer_hbm_capacity_bytes,
            protection_fraction=next_fraction,
            stable_windows=next_stable_windows,
            last_update_ns=timestamp_ns,
        )
        return AIMDDecision(
            timestamp_ns=timestamp_ns,
            action=action,
            foreground_pressure=foreground_pressure,
            current_protection_bytes=current_protection_bytes,
            quota_bytes=quota_bytes,
            bytes_to_reclaim=bytes_to_reclaim,
            admission_blocked=bytes_to_reclaim > 0,
            previous_state=state,
            next_state=next_state,
            parameters=self.parameters,
        )
