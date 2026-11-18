"""Deterministic writers for baseline canonical resource artifacts."""

from __future__ import annotations

import importlib
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from moonkvsim.output.records import (
    FlowRateEventRow,
    OutputContractError,
    ResourceLedgerDeltaRow,
    canonical_flow_rate_event_rows,
    canonical_resource_ledger_delta_rows,
    validate_flow_rate_sequence,
)
from moonkvsim.simulation.journal import EventJournal


class ParquetUnavailableError(RuntimeError):
    """The optional real Parquet writer is unavailable; no file was produced."""


def event_journal_jsonl_bytes(journal: EventJournal) -> bytes:
    """Validate and return the journal's canonical byte-identical JSONL."""

    previous_timestamp_ns = 0
    for expected_sequence, record in enumerate(journal.records):
        if type(record.timestamp_ns) is not int or record.timestamp_ns < previous_timestamp_ns:
            raise OutputContractError("journal timestamps must be non-negative and monotonic")
        if (
            type(record.journal_sequence) is not int
            or record.journal_sequence != expected_sequence
        ):
            raise OutputContractError("journal_sequence must be contiguous from zero")
        if not isinstance(record.record_type, str) or not record.record_type:
            raise OutputContractError("record_type must be a non-empty string")
        if not isinstance(record.data, dict):
            raise OutputContractError("journal record data must be an object")
        try:
            json.dumps(
                record.data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise OutputContractError("journal data is not canonical JSON") from error
        previous_timestamp_ns = record.timestamp_ns
    return journal.to_jsonl_bytes()


def resource_ledger_deltas_jsonl_bytes(
    rows: Sequence[ResourceLedgerDeltaRow],
) -> bytes:
    ordered = canonical_resource_ledger_delta_rows(rows)
    return _jsonl_bytes([row.to_dict() for row in ordered])


def flow_rate_events_jsonl_bytes(rows: Sequence[FlowRateEventRow]) -> bytes:
    ordered = canonical_flow_rate_event_rows(rows)
    validate_flow_rate_sequence(ordered)
    return _jsonl_bytes([row.to_dict() for row in ordered])


def write_event_journal_jsonl(
    journal: EventJournal, path: Path, *, overwrite: bool = False
) -> None:
    _require_suffix(path, ".jsonl")
    _write_bytes(path, event_journal_jsonl_bytes(journal), overwrite=overwrite)


def write_resource_ledger_deltas_jsonl(
    rows: Sequence[ResourceLedgerDeltaRow], path: Path, *, overwrite: bool = False
) -> None:
    _require_suffix(path, ".jsonl")
    _write_bytes(path, resource_ledger_deltas_jsonl_bytes(rows), overwrite=overwrite)


def write_flow_rate_events_jsonl(
    rows: Sequence[FlowRateEventRow], path: Path, *, overwrite: bool = False
) -> None:
    _require_suffix(path, ".jsonl")
    _write_bytes(path, flow_rate_events_jsonl_bytes(rows), overwrite=overwrite)


def write_resource_ledger_deltas_parquet(
    rows: Sequence[ResourceLedgerDeltaRow], path: Path, *, overwrite: bool = False
) -> None:
    """Write real Parquet with a fixed schema, or fail before touching the path."""

    ordered = canonical_resource_ledger_delta_rows(rows)
    fields = (
        ("timestamp_ns", "int64", False),
        ("stable_sequence", "int64", False),
        ("delta_sequence", "int64", False),
        ("event_id", "string", False),
        ("cause", "string", False),
        ("resource_id", "string", False),
        ("resource_kind", "string", False),
        ("allocation_id", "string", False),
        ("object_id", "string", True),
        ("replica_id", "string", True),
        ("transfer_id", "string", True),
        ("account_from", "string", False),
        ("account_to", "string", False),
        ("requested_bytes", "int64", False),
        ("allocated_bytes", "int64", False),
        ("delta_bytes", "int64", False),
        ("before_bytes", "int64", False),
        ("after_bytes", "int64", False),
        ("from_before_bytes", "int64", False),
        ("from_after_bytes", "int64", False),
        ("to_before_bytes", "int64", False),
        ("to_after_bytes", "int64", False),
        ("capacity_bytes", "int64", False),
    )
    _write_real_parquet(
        [row.to_dict() for row in ordered], path, fields, overwrite=overwrite
    )


def write_flow_rate_events_parquet(
    rows: Sequence[FlowRateEventRow], path: Path, *, overwrite: bool = False
) -> None:
    """Write real Parquet with a fixed schema, or fail before touching the path."""

    ordered = canonical_flow_rate_event_rows(rows)
    validate_flow_rate_sequence(ordered)
    fields = (
        ("start_ns", "int64", False),
        ("end_ns", "int64", False),
        ("stable_sequence", "int64", False),
        ("flow_id", "string", False),
        ("transfer_id", "string", False),
        ("slice_id", "string", False),
        ("cause", "string", False),
        ("path_resource_ids", "list_string", False),
        ("payload_bytes", "int64", False),
        ("remaining_bytes", "float64", False),
        ("remaining_bytes_at_end", "float64", False),
        ("transferred_bytes", "float64", False),
        ("allocated_rate_Bps", "float64", False),
        ("queue_wait_ns", "int64", False),
        ("service_ns", "int64", False),
    )
    _write_real_parquet(
        [row.to_dict() for row in ordered], path, fields, overwrite=overwrite
    )


def _write_real_parquet(
    values: list[dict[str, Any]],
    path: Path,
    fields: Sequence[tuple[str, str, bool]],
    *,
    overwrite: bool,
) -> None:
    _require_suffix(path, ".parquet")
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing evidence artifact: {path}")
    try:
        pyarrow = importlib.import_module("pyarrow")
        parquet = importlib.import_module("pyarrow.parquet")
    except ModuleNotFoundError as error:
        raise ParquetUnavailableError(
            "real Parquet output requires the optional 'trace' dependency (pyarrow); "
            "no JSON or JSONL bytes were written with a .parquet suffix"
        ) from error

    type_factories = {
        "int64": pyarrow.int64,
        "string": pyarrow.string,
        "float64": pyarrow.float64,
        "list_string": lambda: pyarrow.list_(pyarrow.string()),
    }
    schema = pyarrow.schema(
        [
            pyarrow.field(name, type_factories[type_name](), nullable=nullable)
            for name, type_name, nullable in fields
        ],
        metadata={
            b"moonkvsim.output_contract": b"baseline-section-16-v1",
            b"moonkvsim.truth_source": b"canonical-event-boundaries",
        },
    )
    table = pyarrow.Table.from_pylist(values, schema=schema)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        parquet.write_table(
            table,
            temporary_path,
            compression="NONE",
            use_dictionary=False,
            write_statistics=False,
            data_page_version="2.0",
            store_schema=True,
        )
        if overwrite:
            os.replace(temporary_path, path)
        else:
            # link() atomically refuses to clobber on this same filesystem.
            os.link(temporary_path, path)
            temporary_path.unlink()
    finally:
        temporary_path.unlink(missing_ok=True)


def _jsonl_bytes(values: Sequence[dict[str, Any]]) -> bytes:
    lines = [
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        for value in values
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode()


def _require_suffix(path: Path, suffix: str) -> None:
    if path.suffix != suffix:
        raise OutputContractError(f"output path must end in {suffix}")


def _write_bytes(path: Path, payload: bytes, *, overwrite: bool) -> None:
    mode = "wb" if overwrite else "xb"
    with path.open(mode) as stream:
        stream.write(payload)
