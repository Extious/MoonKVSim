from pathlib import Path

import pytest

from moonkvsim.aegiskv.paper_artifacts import (
    load_raw_evidence,
    verify_compact_run,
    write_raw_evidence,
)
from moonkvsim.common.hash import sha256_json


def test_complete_evidence_roundtrip_is_byte_deterministic(tmp_path: Path) -> None:
    document = {"events": [{"timestamp_ns": i, "label": "请求"} for i in range(100)]}
    first = write_raw_evidence(tmp_path / "a.gz", document)
    second = write_raw_evidence(tmp_path / "b.gz", document)
    assert first["sha256"] == second["sha256"]
    assert load_raw_evidence(tmp_path / "a.gz", expected_sha256=first["sha256"]) == document


def test_invalid_serialization_preserves_previous_evidence(tmp_path: Path) -> None:
    path = tmp_path / "run.gz"
    original = write_raw_evidence(path, {"complete": True})
    with pytest.raises(ValueError):
        write_raw_evidence(path, {"invalid": float("nan")})
    assert load_raw_evidence(path, expected_sha256=original["sha256"]) == {"complete": True}
    assert list(tmp_path.iterdir()) == [path]


def test_corrupted_raw_file_is_rejected_before_decode(tmp_path: Path) -> None:
    path = tmp_path / "run.gz"
    binding = write_raw_evidence(path, {"events": [1, 2, 3]})
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        load_raw_evidence(path, expected_sha256=binding["sha256"])


def test_compact_metrics_cannot_be_changed_while_retaining_raw_hashes() -> None:
    raw = {
        "schema": "moonkvsim.aegiskv.paper_raw_run.v1",
        "payload": {"metrics": {"mean_ns": 20}, "workflow_admission": {},
                    "randomization": {}, "failure_schedule": {"events": []}},
        "span_details": [], "representative": {"route_events": []}, "journal_sha256": "j",
    }
    compact = {
        **{f"{key}_sha256": sha256_json(raw[key])
           for key in ("payload", "span_details", "representative")},
        "journal_sha256": "j", "workflow_admission": {}, "randomization": {},
        "metrics": {"mean_ns": 20}, "failure_impacted_spans": [], "failure_focus_spans": [],
    }
    verify_compact_run(raw, compact)
    compact["metrics"]["mean_ns"] = 10
    with pytest.raises(ValueError, match="compact metric"):
        verify_compact_run(raw, compact)
