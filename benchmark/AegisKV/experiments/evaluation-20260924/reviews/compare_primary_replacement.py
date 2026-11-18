"""Verify matched primary inputs before executing a replacement version."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_job(job):
    job = json.loads(json.dumps(job))
    # This explicit option was added after the original primary source froze.
    # Its absent default was normal DAG Slack; no other difference is hidden.
    job["config"].setdefault("slack_mode", "dag")
    return job


def compare(old, new):
    old_plan, new_plan = read(old / "PLAN.json"), read(new / "PLAN.json")
    assert old_plan["planned_runs"] == new_plan["planned_runs"] == 180
    assert len(old_plan["jobs"]) == len(new_plan["jobs"]) == 180
    assert [normalized_job(j) for j in old_plan["jobs"]] == [
        normalized_job(j) for j in new_plan["jobs"]
    ], "job configuration, failure, order or logging selection changed"
    for key in ("training_workflows", "evaluation_workflows"):
        assert old_plan[key] == new_plan[key], f"{key} changed"
    assert (old / "PRIORS.json").read_bytes() == (new / "PRIORS.json").read_bytes()
    assert old_plan["workloads"].keys() == new_plan["workloads"].keys()
    workloads = []
    for key, entry in old_plan["workloads"].items():
        replacement = new_plan["workloads"][key]
        # Gzip file headers can contain preparation timestamps; compare decoded
        # workload bytes and every semantic descriptor as well as recording both.
        assert {k: v for k, v in entry.items() if k != "sha256"} == {
            k: v for k, v in replacement.items() if k != "sha256"
        }
        old_path, new_path = old / entry["path"], new / replacement["path"]
        original = gzip.decompress(old_path.read_bytes())
        assert original == gzip.decompress(new_path.read_bytes()), key
        assert hashlib.sha256(original).hexdigest() == entry["content_sha256"]
        workloads.append(
            dict(
                id=key,
                content_sha256=entry["content_sha256"],
                original_file_sha256=sha(old_path),
                replacement_file_sha256=sha(new_path),
            )
        )
    profiles = {}
    assert {p.name for p in (old / "profiles").glob("*.json")} == {
        p.name for p in (new / "profiles").glob("*.json")
    }
    for path in sorted((old / "profiles").glob("*.json")):
        assert path.read_bytes() == (new / "profiles" / path.name).read_bytes()
        profiles[path.name] = sha(path)
    return dict(
        status="PASS",
        original=str(old),
        replacement=str(new),
        original_plan_sha256=sha(old / "PLAN.json"),
        replacement_plan_sha256=sha(new / "PLAN.json"),
        original_manifest_sha256=sha(old / "MANIFEST.json"),
        replacement_manifest_sha256=sha(new / "MANIFEST.json"),
        matched_jobs=180,
        config_normalization="only absent slack_mode becomes its original dag behavior",
        priors_sha256=sha(new / "PRIORS.json"),
        workloads=workloads,
        profiles=profiles,
        scope="input identity only; no simulation or output-equivalence assertion",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", required=True, type=Path)
    parser.add_argument("--new", required=True, type=Path)
    args = parser.parse_args()
    result = compare(args.old.resolve(), args.new.resolve())
    (args.new / "MATCHED_REPLACEMENT_INPUTS.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result))
