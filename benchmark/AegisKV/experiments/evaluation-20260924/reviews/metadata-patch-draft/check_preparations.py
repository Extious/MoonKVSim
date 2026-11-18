"""Prepare-only integration check in the isolated tree; never execute DES."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE = HERE / "tree"
LIVE = Path(json.loads((HERE / "BASELINE.json").read_text())["source_root"])
REL = Path("benchmark/AegisKV/experiments/evaluation-20260924")
sys.path.insert(0, str(TREE / "python"))
sys.path.insert(0, str(TREE / "benchmark/AegisKV/experiments/scripts/current_design"))

import run_capacity_slack_ablation as capacity  # noqa: E402
import run_sensitivity_campaign as sensitivity  # noqa: E402
import run_slack_mechanism_diagnostic as posthoc  # noqa: E402

from moonkvsim.aegiskv.current.model import Config  # noqa: E402
from moonkvsim.aegiskv.current.runtime import CurrentRuntime  # noqa: E402


def reject_execution(*args, **kwargs):
    raise AssertionError("metadata verification must not execute a simulation")


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(job):
    result = dict(job)
    config = {**job["config"], "hosts": tuple(job["config"]["hosts"])}
    # Sensitivity-v1 predates the new explicit, default-dag slack_mode field.
    result["config"] = asdict(Config(**config))
    return result


def check(out, historical, expected_count, levels):
    manifest, plan = read(out / "MANIFEST.json"), read(out / "PLAN.json")
    old = read(historical / "PLAN.json")
    assert len(plan["jobs"]) == expected_count
    assert [normalize(j) for j in plan["jobs"]] == [normalize(j) for j in old["jobs"]]
    assert manifest["duration_profile"] == "GridDurationProfile"
    assert manifest["timing"].startswith("AIConfigurator HYBRID operator estimates;")
    assert "configured linear compute" not in manifest["timing"]
    metadata = manifest["duration_profile_metadata"]
    assert metadata["model"] == "Qwen/Qwen3-8B"
    assert metadata["tp"] == 1 and metadata["scale"] == 1.0
    assert metadata["calibrated"] is False and metadata["physical_execution"] is False
    assert manifest["compute_dma_slowdown_values"] == levels
    assert manifest["evidence_class"] == "modeled_uncalibrated"
    assert manifest["physical_execution"] is False and manifest["paper_ready"] is False
    assert ("disabled" in manifest["foreground_dma_compute_interference"]) == (levels == [0.0])
    relative = "python/moonkvsim/aegiskv/evaluation_profile.py"
    assert manifest["source_sha256"][relative] == sha(TREE / relative)
    assert sha(out / "source_snapshot" / relative) == sha(TREE / relative)
    assert sha(out / plan["profile"]) == sha(historical / old["profile"])
    workload = plan["workload"]
    old_workload = old["workload"]
    if isinstance(workload, dict):
        workload, old_workload = workload["path"], old_workload["path"]
    assert gzip.decompress((out / workload).read_bytes()) == gzip.decompress(
        (historical / old_workload).read_bytes()
    )
    assert not list(out.rglob("summary.json"))
    assert not list(out.rglob("COMPLETE.json"))
    return {
        "path": str(out),
        "planned_jobs": expected_count,
        "executed_jobs": 0,
        "manifest_sha256": sha(out / "MANIFEST.json"),
        "plan_sha256": sha(out / "PLAN.json"),
        "duration_profile": manifest["duration_profile"],
        "compute_dma_slowdown_values": levels,
        "historical_jobs_equal_after_default_config_normalization": True,
        "historical_profile_bytes_identical": True,
        "historical_decoded_workload_identical": True,
        "profile_helper_snapshotted": True,
    }


def main():
    assert sensitivity.ROOT == capacity.ROOT == posthoc.ROOT == TREE
    assert Path(sys.modules[CurrentRuntime.__module__].__file__).is_relative_to(TREE)
    CurrentRuntime.run = reject_execution
    base = HERE / "preparation-checks"
    base.mkdir(exist_ok=False)
    sens, cap, diag = (base / name for name in ("sensitivity", "capacity", "posthoc"))
    priors = TREE / REL / "formal-core-v1/PRIORS.json"
    priors.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LIVE / REL / "formal-core-v1/PRIORS.json", priors)
    assert sha(priors) == sha(LIVE / REL / "formal-core-v1/PRIORS.json")
    sensitivity.prepare(sens, priors)
    sensitivity.verify(sens)
    capacity.prepare(cap, sens)
    sensitivity.verify(cap)
    posthoc.prepare(diag)
    posthoc.verify(diag)
    rows = [
        check(sens, LIVE / REL / "sensitivity-campaign-v1", 126, [0.0, 0.05, 0.1]),
        check(cap, LIVE / REL / "capacity-slack-ablation-v1", 32, [0.0]),
        check(diag, LIVE / REL / "slack-mechanism-posthoc-v1", 10, [0.0]),
    ]
    seal = read(diag / "SEAL.json")
    assert seal["MANIFEST.json"] == sha(diag / "MANIFEST.json")
    rows[-1]["final_manifest_sealed"] = True
    baseline = read(HERE / "BASELINE.json")
    for relative, expected in baseline["source_sha256"].items():
        assert sha(LIVE / relative) == expected, relative
    report = {
        "status": "PASS",
        "execution_guard": "CurrentRuntime.run replaced by an exception; no simulator invoked",
        "isolated_import_root": str(TREE),
        "live_source_files_verified_unchanged": len(baseline["source_sha256"]),
        "groups": rows,
        "scope": "prepare-only real-input checks; not corrected-domain simulation results",
    }
    (HERE / "PREPARATION_CHECK.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
