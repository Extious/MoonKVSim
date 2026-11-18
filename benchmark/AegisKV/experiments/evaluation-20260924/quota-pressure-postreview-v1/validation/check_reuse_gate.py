#!/usr/bin/env python3
"""Hermetic file-integrity tests for the live reuse gate, without a simulator run."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "python/moonkvsim").is_dir())
SOURCE = (
    ROOT / "benchmark/AegisKV/experiments/scripts/current_design/run_quota_pressure_campaign.py"
)
SPEC = importlib.util.spec_from_file_location("quota_reuse_gate_tested", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def check():
    # Isolate the reuse-file gate. Real source/job/run bindings are checked by
    # the separate full-campaign auditor; this fixture supplies their contract.
    expected = {"id": MODULE.TRANSPARENCY_ID, "job_sha256": "expected-job"}
    MODULE.bindings = lambda *_args: expected
    MODULE.validate = lambda *_args: None
    plan = {"jobs": [{"id": MODULE.TRANSPARENCY_ID}]}
    outcomes = []
    with TemporaryDirectory(prefix="quota-reuse-test-") as directory:
        out = Path(directory)
        validation = out / "validation/observer-transparency"
        official = out / "runs" / MODULE.TRANSPARENCY_ID
        validation.mkdir(parents=True)
        official.mkdir(parents=True)
        payloads = {
            "summary.json": b'{"test": true}\n',
            "events.jsonl.gz": b'{"event": "test"}\n',
            "flows.jsonl.gz": b'{"nonempty_flow": "test"}\n',
        }
        record = {
            "status": "PASS",
            "counts_as_experimental_sample": False,
            **expected,
            "checks": {},
        }
        for name, payload in payloads.items():
            data = gzip.compress(payload) if name.endswith(".gz") else payload
            for path in (validation, official):
                (path / name).write_bytes(data)
            record["checks"][name] = {
                "equal": True,
                "decompressed_sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }

        def save():
            (validation / "COMPLETE.json").write_text(json.dumps(record))

        def rejected(label):
            try:
                MODULE.verify_transparency_artifacts(out, plan)
            except AssertionError:
                outcomes.append({"test": label, "status": "PASS_REJECTED"})
            else:
                raise AssertionError("corrupted validation was accepted: " + label)

        save()
        MODULE.verify_transparency_artifacts(out, plan)
        outcomes.append({"test": "intact nonempty control", "status": "PASS_ACCEPTED"})
        (validation / "events.jsonl.gz").write_bytes(gzip.compress(b"changed\n"))
        rejected("modified base events rejected despite retained COMPLETE")
        (validation / "events.jsonl.gz").write_bytes(gzip.compress(payloads["events.jsonl.gz"]))
        record["job_sha256"] = "different-job"
        save()
        rejected("wrong job binding rejected")
        record["job_sha256"] = expected["job_sha256"]
        for path in (validation, official):
            (path / "flows.jsonl.gz").write_bytes(gzip.compress(b""))
        record["checks"]["flows.jsonl.gz"] = {
            "equal": True,
            "decompressed_sha256": hashlib.sha256(b"").hexdigest(),
            "bytes": 0,
        }
        save()
        rejected("empty equal flows rejected")
    result = {
        "status": "PASS",
        "DES_runs": 0,
        "tested_live_runner_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "test_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": (
            "reuse file-integrity gate in isolation; full actual bindings independently audited"
        ),
        "tests": outcomes,
    }
    Path(__file__).with_name("REUSE_GATE_TESTS.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    check()
