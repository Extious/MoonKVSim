"""Resume only absent primary outcomes from the exact retained frozen inputs."""

from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
STUDY = Path(__file__).resolve().parent.parent
CAMPAIGN = STUDY / "formal-core-v2-corrected"
REVIEW = STUDY / "reviews"
SCRIPTS = ROOT / "benchmark/AegisKV/experiments/scripts/current_design"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main():
    launcher = CAMPAIGN / "REPLAY_LAUNCHER.py"
    record = json.loads((CAMPAIGN / "REPLAY_MANIFEST.json").read_text())
    assert sha(launcher) == record["launcher_sha256"]
    spec = importlib.util.spec_from_file_location("retained_frozen_launcher", launcher)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    assert hashlib.sha256(helper.BOOTSTRAP.encode()).hexdigest() == record["bootstrap_sha256"]
    manifest, plan = helper.verify_artifacts(CAMPAIGN)
    before = {
        p.parent.name: {"marker": sha(p), "summary": sha(p.parent / "summary.json")}
        for p in (CAMPAIGN / "runs").glob("*/COMPLETE.json")
    }
    assert len(before) == 177
    missing = [j for j in plan["jobs"] if j["id"] not in before]
    assert {j["id"] for j in missing} == {
        "Qwen3-32B-load0.9-aegiskv-F1-1",
        "Qwen3-32B-load0.9-aegiskv-F1-2",
        "Qwen3-32B-load0.9-aegiskv-F1-4",
    }
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    archive = CAMPAIGN / "interrupted-attempts" / stamp
    archive.mkdir(parents=True, exist_ok=False)
    partials = {}
    for job in missing:
        source = CAMPAIGN / "runs" / job["id"]
        assert source.is_dir() and not (source / "summary.json").exists()
        assert {p.name for p in source.iterdir()} == {"config.json", "failure.json"}
        partials[job["id"]] = {p.name: sha(p) for p in source.iterdir()}
        source.rename(archive / job["id"])
    tree = Path(tempfile.mkdtemp(prefix="aegiskv-frozen-resume-", dir="/home/comp/zhanzhao/.tmp"))
    supplements = helper.build_tree(CAMPAIGN, manifest, tree, support=CAMPAIGN / "replay_support")
    assert supplements == record["supplement_sha256"]
    preflight = helper.call_frozen(tree, CAMPAIGN / "RESUME_PREFLIGHT_IMPORTS.json")
    helper.validate_import_report(preflight, manifest, supplements)
    resume = dict(
        started_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        initial_process_exit_code=143,
        interruption_cause="not determined; exit 143 is consistent with SIGTERM",
        status="RUNNING",
        preserved_completed=before,
        archived_partial_directory=str(archive.relative_to(CAMPAIGN)),
        archived_partial_sha256=partials,
        executed_missing_conditions=[j["id"] for j in missing],
        workers=3,
        frozen_tree=str(tree),
        manifest_sha256=sha(CAMPAIGN / "MANIFEST.json"),
        bootstrap_sha256=record["bootstrap_sha256"],
        supplement_sha256=supplements,
        preflight=preflight,
        import_report_scope="resumed execution; original preflight retained in REPLAY_MANIFEST",
        simulation_source_changed=False,
        interrupted_attempts_are_samples=False,
    )
    write(CAMPAIGN / "INTERRUPTION_RECOVERY.json", resume)
    imported = helper.call_frozen(tree, CAMPAIGN / "REPLAY_IMPORTS.json", out=CAMPAIGN, workers=3)
    helper.validate_import_report(imported, manifest, supplements)
    for identity, hashes in before.items():
        directory = CAMPAIGN / "runs" / identity
        assert sha(directory / "COMPLETE.json") == hashes["marker"], identity
        assert sha(directory / "summary.json") == hashes["summary"], identity
    status = helper.read(CAMPAIGN / "STATUS.json")
    assert status["complete"] and status["completed_runs"] == 180
    result = dict(
        status="COMPLETE",
        completed_runs=180,
        planned_runs=180,
        comparisons=helper.compare_replay(Path(record["original_campaign"]), CAMPAIGN),
        original_campaign_modified=False,
        preserved_completed_runs=177,
        completed_after_interruption=3,
        interruption_recovery_sha256=sha(CAMPAIGN / "INTERRUPTION_RECOVERY.json"),
    )
    resume.update(
        status="COMPLETE",
        finished_utc=datetime.datetime.now(datetime.UTC).isoformat(),
        all_previous_markers_and_summaries_unchanged=True,
        imported_sources_verified=True,
    )
    write(CAMPAIGN / "INTERRUPTION_RECOVERY.json", resume)
    result["interruption_recovery_sha256"] = sha(CAMPAIGN / "INTERRUPTION_RECOVERY.json")
    write(CAMPAIGN / "REPLAY_RESULT.json", result)
    for script in (
        "audit_profile_campaign.py",
        "analyze_primary_endpoints.py",
        "plot_profile_campaign.py",
        "plot_primary_endpoints.py",
    ):
        print("RUN", script, flush=True)
        subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--campaign", str(CAMPAIGN)],
            cwd=ROOT,
            check=True,
        )
    print("RESUMED PRIMARY AUDIT AND PLOTS COMPLETE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        write(
            REVIEW / "PRIMARY_RESUME_FAILED.json",
            dict(type=type(error).__name__, message=str(error)),
        )
        raise
