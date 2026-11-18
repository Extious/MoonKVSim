"""Run one old/new isolated variant; output equality is checked separately."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter, process_time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("old", "optimized"), required=True)
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    evidence = Path(__file__).resolve().parent
    manifest = json.loads((evidence / "SOURCE.json").read_text())
    isolated = Path(manifest["prototype_root"]) / args.variant / "python"
    sys.path.insert(0, str(isolated))
    from moonkvsim.aegiskv.current import runtime
    from moonkvsim.aegiskv.current.__main__ import load_workload, run_one
    from moonkvsim.aegiskv.current.model import Config, Failure
    from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile
    from moonkvsim.aegiskv.evaluation_scenarios import SyntheticPhaseDemand

    assert Path(runtime.__file__).is_relative_to(isolated)
    campaign = evidence.parent.parent / "structural-campaign-v1"
    plan = json.loads((campaign / "PLAN.json").read_text())
    job = next(j for j in plan["jobs"] if j["id"] == args.job)
    workload = campaign / plan["workloads"][job["workload_id"]]["path"]
    profile_path = campaign / plan["profile"]
    assert sha(profile_path) == plan["profile_sha256"]
    agents, profile = load_workload(workload), GridDurationProfile(profile_path)
    config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
    failure = Failure(**job["failure"]) if job["failure"] else None
    provider = SyntheticPhaseDemand(**job["demand_provider"]) if job["demand_provider"] else None
    destination = evidence / "runs" / args.variant / job["id"]
    start, cpu = perf_counter(), process_time()
    result = run_one(
        destination,
        config,
        agents,
        job["policy"],
        failure,
        duration_profile=profile,
        demand_provider=provider,
        retain_detailed_logs=False,
    )
    row = dict(
        variant=args.variant,
        id=args.job,
        wall_seconds=perf_counter() - start,
        cpu_seconds=process_time() - cpu,
        summary_sha256=sha(destination / "summary.json"),
        config_sha256=sha(destination / "config.json"),
        failure_sha256=sha(destination / "failure.json"),
        workload_sha256=result["workload_sha256"],
        runtime_sha256=sha(Path(runtime.__file__)),
        profile_sha256=sha(profile_path),
        profile_duration_cache=profile.duration.cache_info()._asdict(),
        profile_shape_cache=profile.shape.cache_info()._asdict(),
    )
    assert result["workload_sha256"] == plan["workloads"][job["workload_id"]]["sha256"]
    (destination / "TIMING.json").write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    print(json.dumps(row, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
