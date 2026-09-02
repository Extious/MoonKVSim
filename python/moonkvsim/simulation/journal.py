"""Canonical append-only event journal."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class JournalRecord:
    timestamp_ns: int
    journal_sequence: int
    record_type: str
    data: dict[str, Any]


class EventJournal:
    """In-memory canonical journal that can be written byte-identically."""

    def __init__(self) -> None:
        self._records: list[JournalRecord] = []
        self._next_sequence = 0
        self._last_timestamp_ns = 0

    @property
    def records(self) -> tuple[JournalRecord, ...]:
        return tuple(self._records)

    @property
    def record_count(self) -> int:
        """Return the number of records without copying the journal."""

        return len(self._records)

    @property
    def last_timestamp_ns(self) -> int | None:
        """Return the terminal timestamp without materializing ``records``."""

        return None if not self._records else self._last_timestamp_ns

    def append(self, timestamp_ns: int, record_type: str, data: dict[str, Any]) -> None:
        if timestamp_ns < self._last_timestamp_ns:
            raise ValueError("journal timestamp cannot move backwards")
        canonical_data = json.loads(
            json.dumps(
                data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        if not isinstance(canonical_data, dict):
            raise TypeError("journal record data must serialize as an object")
        record = JournalRecord(
            timestamp_ns=timestamp_ns,
            journal_sequence=self._next_sequence,
            record_type=record_type,
            data=canonical_data,
        )
        self._records.append(record)
        self._next_sequence += 1
        self._last_timestamp_ns = timestamp_ns

    def to_jsonl_bytes(self) -> bytes:
        lines = [
            json.dumps(
                asdict(record),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            for record in self._records
        ]
        return ("\n".join(lines) + ("\n" if lines else "")).encode()

    def write(self, path: Path, *, overwrite: bool = False) -> None:
        """Publish without clobbering an earlier evidence artifact by default."""

        mode = "wb" if overwrite else "xb"
        with path.open(mode) as stream:
            stream.write(self.to_jsonl_bytes())
