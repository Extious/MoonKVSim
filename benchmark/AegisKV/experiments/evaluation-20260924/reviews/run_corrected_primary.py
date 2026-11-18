"""Freeze and execute the same primary matrix after the conformance fixes."""

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
STUDY = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "benchmark/AegisKV/experiments/scripts/current_design"
PYTHON = ROOT / ".venv/bin/python"


def run(*arguments):
    print("RUN", *map(str, arguments), flush=True)
    subprocess.run([str(PYTHON), *map(str, arguments)], cwd=ROOT, check=True)


if __name__ == "__main__":
    gate = STUDY / "reviews/QUEUED_HISTORY_APPLICATION.json"
    while not gate.exists() or not json.loads(gate.read_text()).get("freeze_ready"):
        time.sleep(5)
    record = json.loads(gate.read_text())
    assert record["status"] == "PASS"
    preparation = STUDY / "formal-core-v2-preparation"
    campaign = STUDY / "formal-core-v2-corrected"
    assert not preparation.exists() and not campaign.exists()
    run("-m", "moonkvsim.aegiskv.evaluation_campaign", "prepare", "--out", preparation)
    run(
        STUDY / "reviews/compare_primary_replacement.py",
        "--old",
        STUDY / "formal-core-v1",
        "--new",
        preparation,
    )
    run(
        SCRIPTS / "run_frozen_profile_campaign.py",
        "--campaign",
        preparation,
        "--out",
        campaign,
        "--workers",
        "32",
    )
    for script in (
        "audit_profile_campaign.py",
        "analyze_primary_endpoints.py",
        "plot_profile_campaign.py",
        "plot_primary_endpoints.py",
    ):
        run(SCRIPTS / script, "--campaign", campaign)
    print("CORRECTED PRIMARY EXECUTION AND FIRST AUDIT COMPLETE", flush=True)
