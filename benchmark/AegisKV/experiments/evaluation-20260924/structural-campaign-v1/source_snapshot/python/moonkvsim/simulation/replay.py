"""Deterministic replay of normative capacity transactions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any, cast

from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import AccountTransfer, CapacityLedger


class JournalReplayError(RuntimeError):
    pass


def replay_capacity_transactions(
    journal: EventJournal,
    ledgers: Mapping[str, CapacityLedger],
) -> None:
    """Apply journaled resource transactions to pristine ledgers.

    The recorded before/after values are treated as assertions, so a modified,
    incomplete, or out-of-order journal fails closed.
    """

    for record in journal.records:
        if record.record_type != "RESOURCE_TRANSACTION":
            continue
        raw_deltas = record.data.get("allocation_deltas")
        if not isinstance(raw_deltas, list):
            raise JournalReplayError("resource transaction is missing allocation_deltas")
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for raw_delta in raw_deltas:
            if not isinstance(raw_delta, dict):
                raise JournalReplayError("allocation delta must be an object")
            delta = cast(dict[str, Any], raw_delta)
            resource_id = delta.get("resource_id")
            if not isinstance(resource_id, str):
                raise JournalReplayError("allocation delta has no string resource_id")
            grouped[resource_id].append(delta)

        proposed: dict[str, dict[str, int]] = {}
        for resource_id, deltas in grouped.items():
            ledger = ledgers.get(resource_id)
            if ledger is None:
                raise JournalReplayError(f"unknown replay resource: {resource_id}")
            working = dict(ledger.accounts)
            transfers: list[AccountTransfer] = []
            for delta in deltas:
                account_from = _required(delta, "account_from", str)
                account_to = _required(delta, "account_to", str)
                delta_bytes = _required(delta, "delta_bytes", int)
                source_before = working.get(account_from, 0)
                target_before = working.get(account_to, 0)
                if source_before != _required(delta, "from_before_bytes", int):
                    raise JournalReplayError("source before value does not match replay state")
                if target_before != _required(delta, "to_before_bytes", int):
                    raise JournalReplayError("target before value does not match replay state")
                transfer = AccountTransfer(account_from, account_to, delta_bytes)
                transfers.append(transfer)
                working[account_from] = source_before - delta_bytes
                working[account_to] = target_before + delta_bytes
                if working[account_from] != _required(delta, "from_after_bytes", int):
                    raise JournalReplayError("source after value does not match replay state")
                if working[account_to] != _required(delta, "to_after_bytes", int):
                    raise JournalReplayError("target after value does not match replay state")
                if ledger.capacity_bytes != _required(delta, "capacity_bytes", int):
                    raise JournalReplayError("capacity differs from recorded transaction")
            proposed[resource_id] = ledger.preview(transfers)

        for resource_id, accounts in proposed.items():
            ledgers[resource_id]._replace_accounts(accounts)


def _required(data: Mapping[str, Any], key: str, expected_type: type[Any]) -> Any:
    value = data.get(key)
    if not isinstance(value, expected_type):
        raise JournalReplayError(f"{key} has wrong or missing type")
    return value
