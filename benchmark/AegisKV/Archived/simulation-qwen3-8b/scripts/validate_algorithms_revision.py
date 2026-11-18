#!/usr/bin/env python3
"""Record reproducible revision-3 reference checks without relabeling old runs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "benchmark/AegisKV/experiments/results/algorithm-revision-v3"
MODULES = ["python/moonkvsim/aegiskv/" + name + ".py"
           for name in ("prefix_frontier", "foreground_budget", "revision_runtime")]
TESTS = ["tests/aegiskv/test_prefix_frontier_revision.py",
         "tests/aegiskv/test_foreground_budget_revision.py"]
LEGACY_TESTS = ["tests/aegiskv/test_slack_landlord.py", "tests/aegiskv/test_hbm_quota_aimd.py",
                "tests/unit/aegiskv/test_patent_contract.py",
                "tests/aegiskv/test_runtime_clause_evidence.py"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "python"))
    commands = {
        "reference": [sys.executable, "-m", "pytest", "-q", *TESTS,
                      "--junitxml=" + str(OUT / "reference.xml")],
        "legacy_contracts": [sys.executable, "-m", "pytest", "-q", *LEGACY_TESTS,
                             "--junitxml=" + str(OUT / "legacy_contracts.xml")],
        "lint": [sys.executable, "-m", "ruff", "check", *MODULES, *TESTS, str(Path(__file__))],
        "types": [sys.executable, "-m", "mypy", *MODULES],
    }
    checks = {}
    for name, command in commands.items():
        result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        log = OUT / f"{name}.log"
        log.write_text(result.stdout)
        record = {"command": command, "returncode": result.returncode,
                  "log": log.name, "sha256": sha(log)}
        xml = OUT / f"{name}.xml"
        if name in {"reference", "legacy_contracts"} and xml.exists():
            suites = list(ET.parse(xml).getroot().iter("testsuite"))
            record["counts"] = {key: sum(int(s.get(key, 0)) for s in suites)
                                for key in ("tests", "failures", "errors", "skipped")}
        checks[name] = record
        print(name, "PASS" if result.returncode == 0 else "FAIL", flush=True)
    sources = [*MODULES, *TESTS, *LEGACY_TESTS, str(Path(__file__).relative_to(ROOT)),
               "benchmark/AegisKV/docs/patent/ALGORITHMS_2_3_REVISION.md"]
    passed = all(c["returncode"] == 0 for c in checks.values())
    report = {
        "schema": "moonkvsim.algorithm-revision.v3", "status": "PASS" if passed else "FAIL",
        "scope": "serial reference + old contracts; no CUDA or new DES matrix",
        "native_integrated": False, "full_des_integrated": False,
        "physical_qos_certificate": None, "default_target_relative_overhead": 0.01,
        "checks": checks, "source_sha256": {name: sha(ROOT / name) for name in sources},
    }
    (OUT / "VALIDATION.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
