"""Frozen three-system mechanism matrix with explicit dependency scheduling."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu-calibration", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--source-plan", type=Path)
    parser.add_argument("--reuse-from", type=Path, action="append", default=[])
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--case-plan", type=Path, help="Explicit frozen case mapping for a separate campaign")
    args = parser.parse_args()
    source, out = args.source.resolve(), args.output.resolve()
    calibration = args.cpu_calibration.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = {
        "f0-natural": {},
        "f0-revisit": {"rounds": 2},
        "f1-natural": {"failures": 1, "reference": "f0-natural"},
        "f2-natural": {"failures": 2, "reference": "f0-natural"},
        "f0-revisit-c8": {"rounds": 2, "concurrency": 8},
        "f0-revisit-c32": {"rounds": 2, "concurrency": 32},
        "f0-revisit-dram32": {"rounds": 2, "store-gib": 32},
        "f0-revisit-dram128": {"rounds": 2, "store-gib": 128},
        "f0-revisit-bw5": {"rounds": 2, "bandwidth-gbs": 5},
        "f0-revisit-bw50": {"rounds": 2, "bandwidth-gbs": 50},
        "f0-cpu4x": {"cpu-scale": 4},
        "f1-no-slack": {
            "failures": 1,
            "reference": "f0-natural",
            "no-slack": True,
            "systems": ["dram", "aegis"],
        },
        "f0-no-slack": {"no-slack": True, "systems": ["dram", "aegis"]},
        "f0-guarded-no-certificate": {"peer-mode": "guarded", "systems": ["aegis"]},
    }
    if args.case_plan is not None:
        cases = json.loads(args.case_plan.read_text())
        assert cases and all(isinstance(c, dict) for c in cases.values())
    overrides = {} if args.source_plan is None else json.loads(args.source_plan.read_text())
    assert not set(overrides) - set(cases), "unknown source override"
    sources = {case: Path(overrides.get(case, source)).resolve() for case in cases}
    bindings = {
        case: {
            "source": str(path),
            "source_snapshot_sha256": hashlib.sha256(
                (path / "MECHANISM_SOURCE_SNAPSHOT.json").read_bytes()
            ).hexdigest(),
        }
        for case, path in sources.items()
    }
    protocol = {
        "schema": "moonkvsim.three_system_campaign.v1",
        "source": str(source),
        "source_snapshot_sha256": hashlib.sha256(
            (source / "MECHANISM_SOURCE_SNAPSHOT.json").read_bytes()
        ).hexdigest(),
        "cpu_calibration": str(calibration),
        "cpu_calibration_sha256": hashlib.sha256(calibration.read_bytes()).hexdigest(),
        "default": {
            "workflows": 160,
            "seed": 0,
            "concurrency": 16,
            "rounds": 2,
            "bandwidth_gbs": 25,
            "store_bytes": 1_000_000_000_000,
        },
        "cases": cases,
        "source_by_case": bindings,
        "primary_workflow_order": "Mooncake_F0_seed0_WCT_then_workflow_ID_same_across_all_plots",
        "evidence": "agent_subleases_and_guarded_AIMD_DES_not_native_serving",
        "revisits": "synthetic_exact_input_DAG_replay_2_rounds_not_observed_turns",
        "replicates_per_case_system": 1,
        "orchestrator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "uncertainty": "descriptive_paired_workflows_no_population_CI_or_QoS_certificate",
    }
    path = out / "PROTOCOL.json"
    if path.exists():
        assert json.loads(path.read_text()) == protocol, "protocol drift"
    else:
        path.write_text(json.dumps(protocol, indent=2) + "\n")
    jobs = [
        (case, system)
        for case, config in cases.items()
        for system in config.get("systems", ["mooncake", "dram", "aegis"])
    ]
    selected = set(cases) if args.cases is None else set(args.cases)
    assert selected <= cases.keys(), "unknown case selection"
    pending = [job for job in jobs if job[0] in selected]
    deferred = [job for job in jobs if job[0] not in selected]
    active, completed, failed = {}, [], []

    def run(job):
        case, system = job
        target = out / "runs" / case
        target.mkdir(parents=True, exist_ok=True)
        manifest = target / f"{system}.manifest.json"
        expected_source_hash = bindings[case]["source_snapshot_sha256"]
        for prior in args.reuse_from:
            if manifest.exists():
                break
            old = prior / "runs" / case
            old_manifest = old / f"{system}.manifest.json"
            if not old_manifest.exists():
                continue
            old_protocol = json.loads((prior / "PROTOCOL.json").read_text())
            old_record = json.loads(old_manifest.read_text())
            if old_record["source_snapshot_sha256"] != expected_source_hash:
                continue
            assert old_protocol["default"] == protocol["default"]
            assert old_protocol["cases"][case] == cases[case]
            assert old_record["cpu_calibration_sha256"] == protocol["cpu_calibration_sha256"]
            raw = old / f"{system}.json.gz"
            assert hashlib.sha256(raw.read_bytes()).hexdigest() == old_record["raw_sha256"]
            for suffix in ("json.gz", "log", "command.json"):
                original = old / f"{system}.{suffix}"
                if original.exists():
                    shutil.copy2(original, target / original.name)
            (target / f"{system}.reuse.json").write_text(
                json.dumps(
                    {
                        "original_manifest": str(old_manifest.resolve()),
                        "raw_sha256": old_record["raw_sha256"],
                        "reason": "same configuration and exact source; not a new replicate",
                    },
                    indent=2,
                )
                + "\n"
            )
            shutil.copy2(old_manifest, manifest)  # Publish last for the reducer.
        if manifest.exists():
            existing = json.loads(manifest.read_text())
            assert existing["source_snapshot_sha256"] == expected_source_hash
            assert existing["cpu_calibration_sha256"] == protocol["cpu_calibration_sha256"]
            return job, 0, "existing_manifest"
        run_source = sources[case]
        env = dict(
            os.environ,
            PYTHONPATH=str(run_source / "python"),
            MOONKVSIM_PROGRESS_EVERY_EVENTS="10000",
        )
        command = [
            sys.executable,
            str(
                run_source / "benchmark/AegisKV/experiments/scripts/run_agent_lease_mechanisms.py"
            ),
            "--output",
            str(target),
            "--systems",
            system,
            "--cpu-calibration",
            str(calibration),
        ]
        for key, value in cases[case].items():
            if key == "systems":
                continue
            if key == "reference":
                command += ["--failure-reference", str(out / "runs" / value / "mooncake.json.gz")]
            elif isinstance(value, bool):
                if value:
                    command.append("--" + key)
            else:
                command += ["--" + key, str(value)]
        (target / f"{system}.command.json").write_text(json.dumps(command, indent=2) + "\n")
        start = time.monotonic()
        with (target / f"{system}.log").open("w") as log:
            result = subprocess.run(
                command, env=env, cwd=run_source, stdout=log, stderr=subprocess.STDOUT
            )
        return job, result.returncode, round(time.monotonic() - start, 2)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        while pending or active:
            if failed:
                # Finish already dispatched jobs, but do not broaden a matrix
                # after a newly discovered model or artifact failure.
                pending.clear()
            for job in tuple(pending):
                if len(active) >= args.workers:
                    break
                ref = cases[job[0]].get("reference")
                if ref and not (out / "runs" / ref / "mooncake.manifest.json").exists():
                    if (ref, "mooncake") in failed:
                        failed.append(job)
                        pending.remove(job)
                    continue
                active[pool.submit(run, job)] = job
                pending.remove(job)
                print(
                    json.dumps({"started": job, "active": len(active), "pending": len(pending)}),
                    flush=True,
                )
            done, _ = concurrent.futures.wait(
                active, timeout=10, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                job = active.pop(future)
                try:
                    _, code, elapsed = future.result()
                except Exception as error:
                    code, elapsed = 1, str(error)
                (failed if code else completed).append(job)
                print(
                    json.dumps(
                        {
                            "finished": job,
                            "exit_code": code,
                            "wall_s": elapsed,
                            "completed": len(completed),
                            "failed": len(failed),
                        }
                    ),
                    flush=True,
                )
            status = {
                "completed": completed,
                "failed": failed,
                "active": list(active.values()),
                "pending": pending + deferred,
            }
            (out / "STATUS.json").write_text(json.dumps(status, indent=2) + "\n")
    if failed:
        raise SystemExit(f"failed jobs: {failed}")


if __name__ == "__main__":
    main()
