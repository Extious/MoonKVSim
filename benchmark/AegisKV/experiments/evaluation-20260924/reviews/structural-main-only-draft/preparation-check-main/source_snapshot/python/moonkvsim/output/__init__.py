"""Baseline-only canonical outputs derived from MoonKVSim truth sources.

This package contains no AegisKV policy or runtime semantics.  Its JSONL path
is suitable for static and toy semantic tests; physical validation and the
complete section 16 artifact matrix remain separate evidence gates.
"""

from moonkvsim.output.artifacts import (
    ParquetUnavailableError,
    event_journal_jsonl_bytes,
    flow_rate_events_jsonl_bytes,
    resource_ledger_deltas_jsonl_bytes,
    write_event_journal_jsonl,
    write_flow_rate_events_jsonl,
    write_flow_rate_events_parquet,
    write_resource_ledger_deltas_jsonl,
    write_resource_ledger_deltas_parquet,
)
from moonkvsim.output.capacity import (
    AccountCapacitySummary,
    CapacityDeltaAudit,
    CapacityDeltaFailure,
    CapacitySummary,
    derive_capacity_artifacts,
)
from moonkvsim.output.records import (
    AllocationByteShape,
    FlowRateEventRow,
    OutputContractError,
    ResourceLedgerDeltaRow,
    build_flow_rate_event_rows,
    extract_resource_ledger_delta_rows,
    validate_flow_rate_sequence,
)
from moonkvsim.output.run_bundle import (
    PublishedRunArtifactBundle,
    RunArtifactBundleError,
    RunManifestInputs,
    build_run_manifest,
    publish_run_artifact_bundle,
    verify_run_artifact_bundle,
)

__all__ = [
    "AccountCapacitySummary",
    "AllocationByteShape",
    "CapacityDeltaAudit",
    "CapacityDeltaFailure",
    "CapacitySummary",
    "FlowRateEventRow",
    "OutputContractError",
    "ParquetUnavailableError",
    "PublishedRunArtifactBundle",
    "ResourceLedgerDeltaRow",
    "RunArtifactBundleError",
    "RunManifestInputs",
    "build_flow_rate_event_rows",
    "build_run_manifest",
    "derive_capacity_artifacts",
    "event_journal_jsonl_bytes",
    "extract_resource_ledger_delta_rows",
    "flow_rate_events_jsonl_bytes",
    "publish_run_artifact_bundle",
    "resource_ledger_deltas_jsonl_bytes",
    "validate_flow_rate_sequence",
    "verify_run_artifact_bundle",
    "write_event_journal_jsonl",
    "write_flow_rate_events_jsonl",
    "write_flow_rate_events_parquet",
    "write_resource_ledger_deltas_jsonl",
    "write_resource_ledger_deltas_parquet",
]
