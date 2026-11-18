"""Execute unchanged frozen wall-time jobs under a recorded concurrency amendment.

This wrapper changes host-side orchestration only. The original source tree,
protocol, jobs, profiles, predictors and completed runs remain byte-identical.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import runpy
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--amendment", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    amendment_bytes = args.amendment.read_bytes()
    amendment = json.loads(amendment_bytes)
    amendment_sha = hashlib.sha256(amendment_bytes).hexdigest()
    if amendment["runner_sha256"] != sha(Path(__file__)):
        raise ValueError("amended execution runner changed")
    if amendment["original_protocol_seal_sha256"] != sha(out / "PROTOCOL_SEAL.json"):
        raise ValueError("original protocol seal changed")
    if amendment["workers"] != 16:
        raise ValueError("this amendment permits exactly 16 host worker processes")
    bootstrap = out / "source_snapshot/_walltime_bootstrap.py"
    expected = read(out / "MANIFEST.json")["source_sha256"]["_walltime_bootstrap.py"]
    if sha(bootstrap) != expected:
        raise ValueError("frozen import bootstrap changed")
    # The original guarded loader imports only the original frozen MoonKVSim tree.
    campaign = runpy.run_path(str(bootstrap), run_name="amended_frozen_loader")["campaign"]
    _, plan = campaign.verify_frozen(out)
    imports = campaign.imported_sources()
    if args.verify_only:
        print(json.dumps({"status": "PASS", "frozen_imports": len(imports)}))
        return
    with (out / "RUNNING.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stopped_path = args.amendment.parent / "STOPPED_STATE.json"
        stopped_bytes = stopped_path.read_bytes()
        stopped_sha = hashlib.sha256(stopped_bytes).hexdigest()
        if amendment["stopped_state_sha256"] != stopped_sha:
            raise ValueError("stopped execution state changed")
        before = json.loads(stopped_bytes)
        for rel, expected in before["completed_artifact_sha256"].items():
            if sha(out / rel) != expected:
                raise ValueError("pre-amendment completed artifact changed: " + rel)
        completed, todo = [], []
        for job in plan["jobs"]:
            target = out / "runs" / job["id"]
            if (target / "COMPLETE.json").exists():
                completed.append(campaign.verify_completed(out, job))
            elif target.exists():
                raise ValueError("partial run was not archived: " + str(target))
            else:
                todo.append(job)
        if {row["id"] for row in completed} != set(before["completed_job_ids"]):
            raise ValueError("completed identity set differs from stopped execution record")
        if any(job["capture_context"] for job in todo):
            raise ValueError("all six initial healthy observation jobs must already be complete")
        order = {j["id"]: i for i, j in enumerate(plan["jobs"])}
        todo.sort(key=lambda j: order[j["id"]])
        validation_job = next(
            job for job in plan["jobs"] if job["id"] == amendment["validation_job"]
        )
        campaign.verify_completed(out, validation_job)
        validation_target = out / "validation/parallel16"
        if validation_target.exists():
            raise ValueError("parallelism validation already exists; review resume explicitly")
        final_verified = False

        def progress():
            completed.sort(key=lambda r: order[r["id"]])
            campaign.atomic_json(out / "RUNS.json", completed)
            campaign.atomic_json(
                out / "STATUS.json",
                dict(
                    complete=final_verified and len(completed) == len(plan["jobs"]),
                    completed_runs=len(completed),
                    planned_runs=len(plan["jobs"]),
                    updated_utc=campaign.utc(),
                    workers=16,
                    execution_amendment_sha256=amendment_sha,
                ),
            )

        campaign.write_json(
            args.amendment.parent / "EXECUTION_START.json",
            dict(
                started_utc=campaign.utc(),
                imported_source_sha256=imports,
                remaining_jobs=len(todo),
                completed_jobs=len(completed),
                amendment_sha256=amendment_sha,
                stopped_state_sha256=stopped_sha,
                python=sys.version,
            ),
        )
        progress()
        try:
            with ProcessPoolExecutor(max_workers=16) as pool:
                validation = pool.submit(
                    campaign.run_condition,
                    out,
                    validation_job,
                    capture=False,
                    target=validation_target,
                )
                futures = {pool.submit(campaign.execute_job, (str(out), job)): job for job in todo}
                for future in as_completed([validation, *futures]):
                    result = future.result()
                    if future is validation:
                        campaign.verify_completed(
                            out,
                            validation_job,
                            target=validation_target,
                            capture=False,
                        )
                        compared = {}
                        for name in ("summary.json", "events.jsonl.gz", "flows.jsonl.gz"):
                            baseline = (out / "runs" / validation_job["id"] / name).read_bytes()
                            replay = (validation_target / name).read_bytes()
                            if name.endswith(".gz"):
                                baseline = gzip.decompress(baseline)
                                replay = gzip.decompress(replay)
                            if baseline != replay or (name != "flows.jsonl.gz" and not baseline):
                                raise ValueError("parallelism changed or emptied artifact: " + name)
                            compared[name] = dict(
                                equal=True,
                                content_bytes=len(baseline),
                                nonempty=bool(baseline),
                                content_sha256=hashlib.sha256(baseline).hexdigest(),
                            )
                        campaign.write_json(
                            args.amendment.parent / "PARALLELISM_VALIDATION.json",
                            dict(
                                status="PASS",
                                case=validation_job["id"],
                                artifacts=compared,
                                extra_experimental_samples=0,
                                scope="one preselected protected F0 under concurrent execution",
                                limitation="summary-only run has no retained transfer intervals",
                            ),
                        )
                    else:
                        completed.append(result)
                        progress()
                        print(
                            f"completed {len(completed)}/{len(plan['jobs'])} "
                            f"{result['id']} {result['wall_seconds']:.2f}s",
                            flush=True,
                        )
            campaign.verify_frozen(out)
            for rel, expected in before["completed_artifact_sha256"].items():
                if sha(out / rel) != expected:
                    raise ValueError("pre-amendment artifact changed during execution: " + rel)
            for job in plan["jobs"]:
                campaign.verify_completed(out, job)
            if sha(args.amendment) != amendment_sha or sha(stopped_path) != stopped_sha:
                raise ValueError("execution amendment or stopped-state record changed")
            campaign.write_json(
                args.amendment.parent / "EXECUTION_COMPLETE.json",
                dict(
                    status="PASS",
                    completed_runs=len(completed),
                    completed_before=len(before["completed_job_ids"]),
                    all_prior_completed_artifacts_unchanged=True,
                    original_protocol_and_sources_unchanged=True,
                    imported_source_sha256=campaign.imported_sources(),
                    finished_utc=campaign.utc(),
                ),
            )
            final_verified = True
            progress()
        except BaseException as error:
            campaign.write_json(
                args.amendment.parent / "EXECUTION_ERROR.json",
                dict(
                    type=type(error).__name__, message=str(error), traceback=traceback.format_exc()
                ),
            )
            raise


if __name__ == "__main__":
    main()
