from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUNDLE = ROOT / "benchmark/physical/mooncake-tcp-store/66924-20260803-140423"
AUDITOR = ROOT / "scripts/audit_mooncake_tcp_calibration.py"


def _run_audit(bundle: Path = BUNDLE) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDITOR), "--bundle", str(bundle)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_canonical_bundle_passes_fail_closed_auditor() -> None:
    completed = _run_audit()

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert report["event_count"] == 3
    assert report["source_verified"] is False
    assert report["evidence_ceiling"] == ("preliminary_physical_calibration_input_below_E3")


def test_original_event_bytes_and_numeric_values_are_fixed() -> None:
    raw = (BUNDLE / "l3_io_events.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "72b5dd08dcb69a9521cca71cdd4bb8460668b383db2ee7607550f3315de140e5"
    )
    events = [json.loads(line) for line in raw.decode().splitlines()]

    assert [(event["operation"], event["dp_rank"]) for event in events] == [
        ("prefetch", 0),
        ("backup", 1),
        ("prefetch", 1),
    ]
    assert [event["bytes"] for event in events] == [141557760, 150994944, 141557760]
    assert [event["duration_us"] for event in events] == [
        219110.026,
        134680.905,
        161515.801,
    ]
    assert [event["effective_gbps"] for event in events] == [
        0.6460578850919401,
        1.1211310467508366,
        0.8764328884453849,
    ]


def test_provenance_keeps_platform_and_claim_boundaries_open() -> None:
    provenance = json.loads((BUNDLE / "provenance.json").read_text(encoding="utf-8"))

    assert provenance["capture"]["import_audit"]["external_sglang_porcelain"] == [
        "?? benchmark/aegiskv_mooncake/"
    ]
    assert provenance["deployment"]["parallelism"] == {
        "dp_size": 2,
        "pp_size": 1,
        "tp_size": 1,
    }
    assert provenance["deployment"]["mooncake"]["same_host"] is True
    assert provenance["deployment"]["mooncake"]["transport"] == "tcp"
    mismatch = provenance["deployment"]["target_mismatch"]
    assert mismatch["source_hardware"] == "2x NVIDIA GeForce RTX 4090"
    assert mismatch["source_runtime"] == "SGLang 0.5.16 DP=2"
    assert mismatch["target_hardware"] == "NVIDIA L40S"
    assert mismatch["target_runtime"] == "vLLM 1.2.2"
    boundary = provenance["claim_boundary"]
    assert boundary["gates_cleared"] == []
    assert boundary["formal_use_allowed"] is False
    assert boundary["required_open_gates"] == [
        "GAP-003",
        "target E3 transfer and Store calibration",
        "E4 matched end-to-end validation",
        "E5 paper evidence",
    ]
    assert set(boundary["terms_forbidden_as_measurement_claims"]) == {
        "hardware peak bandwidth",
        "network link bandwidth",
        "raw DRAM bandwidth",
        "SSD bandwidth",
        "disk bandwidth",
        "isolated Transfer Engine bandwidth",
    }


def test_bundle_excludes_large_traces_and_rejects_event_tampering(tmp_path: Path) -> None:
    files = {path.relative_to(BUNDLE).as_posix() for path in BUNDLE.rglob("*") if path.is_file()}
    assert not any(path.endswith(".trace.json.gz") for path in files)
    assert files == {
        "README.md",
        "SHA256SUMS",
        "l3_io_events.jsonl",
        "manifest.json",
        "provenance.json",
        "provenance/mooncake-working-tree.patch",
        "provenance/sglang-working-tree.patch",
        "raw/hicache-io-2069211.jsonl",
        "raw/hicache-io-2069212.jsonl",
    }

    tampered = tmp_path / "bundle"
    shutil.copytree(BUNDLE, tampered)
    event_path = tampered / "l3_io_events.jsonl"
    event_path.write_bytes(event_path.read_bytes().replace(b"219110.026", b"219110.027", 1))

    completed = _run_audit(tampered)
    assert completed.returncode == 2
    assert "checksum mismatch" in completed.stderr
