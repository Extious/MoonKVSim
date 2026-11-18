"""Byte-exact capacity ledgers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class CapacityResourceKind(StrEnum):
    GPU_HBM = "GPU_HBM"
    HOST_DRAM = "HOST_DRAM"
    STORE_DRAM = "STORE_DRAM"


FREE_ACCOUNT = "FREE"
UNAVAILABLE_CAPACITY_ACCOUNT = "UNAVAILABLE_CAPACITY"


@dataclass(frozen=True, slots=True)
class AccountTransfer:
    account_from: str
    account_to: str
    delta_bytes: int

    def __post_init__(self) -> None:
        if not self.account_from or not self.account_to:
            raise ValueError("account names must be non-empty")
        if self.account_from == self.account_to:
            raise ValueError("account transfer must change accounts")
        if self.delta_bytes <= 0:
            raise ValueError("delta_bytes must be positive")


class CapacityLedger:
    """A closed byte ledger whose accounts always sum to physical capacity."""

    def __init__(
        self,
        *,
        resource_id: str,
        resource_kind: CapacityResourceKind,
        capacity_bytes: int,
        initial_accounts: Mapping[str, int] | None = None,
    ) -> None:
        if not resource_id:
            raise ValueError("resource_id must be non-empty")
        if capacity_bytes <= 0:
            raise ValueError("capacity_bytes must be positive")
        accounts = dict(initial_accounts or {})
        if FREE_ACCOUNT in accounts:
            raise ValueError("FREE is derived and must not be supplied in initial_accounts")
        if any(not account for account in accounts):
            raise ValueError("account names must be non-empty")
        if any(value < 0 for value in accounts.values()):
            raise ValueError("account values must be non-negative")
        used_bytes = sum(accounts.values())
        if used_bytes > capacity_bytes:
            raise ValueError("initial accounts exceed physical capacity")
        accounts[FREE_ACCOUNT] = capacity_bytes - used_bytes
        self.resource_id = resource_id
        self.resource_kind = resource_kind
        self.capacity_bytes = capacity_bytes
        self._accounts = accounts
        self._assert_valid(accounts)

    @property
    def accounts(self) -> Mapping[str, int]:
        return dict(self._accounts)

    def bytes_in(self, account: str) -> int:
        return self._accounts.get(account, 0)

    def preview(self, transfers: list[AccountTransfer]) -> dict[str, int]:
        proposed = dict(self._accounts)
        for transfer in transfers:
            source_before = proposed.get(transfer.account_from, 0)
            if source_before < transfer.delta_bytes:
                raise ValueError(
                    f"{self.resource_id}:{transfer.account_from} has {source_before}, "
                    f"cannot transfer {transfer.delta_bytes}"
                )
            proposed[transfer.account_from] = source_before - transfer.delta_bytes
            proposed[transfer.account_to] = (
                proposed.get(transfer.account_to, 0) + transfer.delta_bytes
            )
        self._assert_valid(proposed)
        return proposed

    def _replace_accounts(self, accounts: Mapping[str, int]) -> None:
        proposed = dict(accounts)
        self._assert_valid(proposed)
        self._accounts = proposed

    def _assert_valid(self, accounts: Mapping[str, int]) -> None:
        if any(value < 0 for value in accounts.values()):
            raise ValueError(f"negative account value on {self.resource_id}")
        total = sum(accounts.values())
        if total != self.capacity_bytes:
            raise ValueError(
                f"ledger does not conserve capacity on {self.resource_id}: "
                f"accounts={total}, capacity={self.capacity_bytes}"
            )
