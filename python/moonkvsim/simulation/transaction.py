"""Atomic multi-ledger resource transactions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import AccountTransfer, CapacityLedger


@dataclass(frozen=True, slots=True)
class AllocationDelta:
    resource_id: str
    account_from: str
    account_to: str
    delta_bytes: int
    allocation_id: str
    object_id: str | None = None
    replica_id: str | None = None
    transfer_id: str | None = None

    def as_transfer(self) -> AccountTransfer:
        return AccountTransfer(
            account_from=self.account_from,
            account_to=self.account_to,
            delta_bytes=self.delta_bytes,
        )


@dataclass(frozen=True, slots=True)
class AppliedAllocationDelta:
    delta: AllocationDelta
    from_before_bytes: int
    from_after_bytes: int
    to_before_bytes: int
    to_after_bytes: int
    capacity_bytes: int


class ResourceTransaction:
    """A transaction is previewed in full before any ledger is mutated."""

    def __init__(
        self,
        *,
        event_id: str,
        timestamp_ns: int,
        cause: str,
        allocation_deltas: list[AllocationDelta],
    ) -> None:
        if not event_id or not cause:
            raise ValueError("event_id and cause must be non-empty")
        if timestamp_ns < 0:
            raise ValueError("timestamp_ns must be non-negative")
        if not allocation_deltas:
            raise ValueError("transaction must contain at least one allocation delta")
        self.event_id = event_id
        self.timestamp_ns = timestamp_ns
        self.cause = cause
        self.allocation_deltas = tuple(allocation_deltas)
        self._committed = False

    def commit(
        self,
        ledgers: Mapping[str, CapacityLedger],
        *,
        journal: EventJournal | None = None,
    ) -> tuple[AppliedAllocationDelta, ...]:
        if self._committed:
            raise RuntimeError("resource transaction was already committed")

        grouped: dict[str, list[AllocationDelta]] = defaultdict(list)
        for delta in self.allocation_deltas:
            if delta.resource_id not in ledgers:
                raise KeyError(f"unknown capacity resource: {delta.resource_id}")
            grouped[delta.resource_id].append(delta)

        proposed: dict[str, dict[str, int]] = {}
        applied: list[AppliedAllocationDelta] = []
        for resource_id, deltas in grouped.items():
            ledger = ledgers[resource_id]
            working = dict(ledger.accounts)
            for delta in deltas:
                transfer = delta.as_transfer()
                source_before = working.get(transfer.account_from, 0)
                target_before = working.get(transfer.account_to, 0)
                if source_before < transfer.delta_bytes:
                    raise ValueError(
                        f"{resource_id}:{transfer.account_from} has {source_before}, "
                        f"cannot transfer {transfer.delta_bytes}"
                    )
                source_after = source_before - transfer.delta_bytes
                target_after = target_before + transfer.delta_bytes
                working[transfer.account_from] = source_after
                working[transfer.account_to] = target_after
                applied.append(
                    AppliedAllocationDelta(
                        delta=delta,
                        from_before_bytes=source_before,
                        from_after_bytes=source_after,
                        to_before_bytes=target_before,
                        to_after_bytes=target_after,
                        capacity_bytes=ledger.capacity_bytes,
                    )
                )
            proposed[resource_id] = ledger.preview(
                [delta.as_transfer() for delta in deltas]
            )

        if (
            journal is not None
            and journal.records
            and self.timestamp_ns < journal.records[-1].timestamp_ns
        ):
            raise ValueError("transaction timestamp would move journal backwards")

        for resource_id, accounts in proposed.items():
            ledgers[resource_id]._replace_accounts(accounts)

        if journal is not None:
            journal.append(
                self.timestamp_ns,
                "RESOURCE_TRANSACTION",
                {
                    "event_id": self.event_id,
                    "cause": self.cause,
                    "allocation_deltas": [
                        {
                            "resource_id": item.delta.resource_id,
                            "allocation_id": item.delta.allocation_id,
                            "object_id": item.delta.object_id,
                            "replica_id": item.delta.replica_id,
                            "transfer_id": item.delta.transfer_id,
                            "account_from": item.delta.account_from,
                            "account_to": item.delta.account_to,
                            "delta_bytes": item.delta.delta_bytes,
                            "from_before_bytes": item.from_before_bytes,
                            "from_after_bytes": item.from_after_bytes,
                            "to_before_bytes": item.to_before_bytes,
                            "to_after_bytes": item.to_after_bytes,
                            "capacity_bytes": item.capacity_bytes,
                        }
                        for item in applied
                    ],
                },
            )
        self._committed = True
        return tuple(applied)
