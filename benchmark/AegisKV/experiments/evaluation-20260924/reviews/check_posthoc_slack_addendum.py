"""Read-only checks for later observation validation and metadata erratum."""

import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "slack-mechanism-posthoc-v1"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    plan = read(OUT / "PLAN.json")
    proof = read(OUT / "NONEMPTY_OBSERVATION_TRANSPARENCY.json")
    job = next(j for j in plan["jobs"] if j["id"] == proof["job_id"])
    base = OUT / "validation/tight-dag-F1-base-runtime"
    observed = OUT / "runs" / job["id"]
    for name, expected in read(OUT / "SEAL.json").items():
        assert sha(OUT / name) == expected
    for name, expected in read(OUT / "MANIFEST.json")["source_sha256"].items():
        assert sha(OUT / "source_snapshot" / name) == expected
    for name in ("summary.json", "config.json", "failure.json"):
        assert (base / name).read_bytes() == (observed / name).read_bytes()
    assert read(base / "config.json") == job["config"]
    assert read(base / "failure.json") == job["failure"]
    for key, expected in {
        "plan_sha256": sha(OUT / "PLAN.json"),
        "manifest_sha256": sha(OUT / "MANIFEST.json"),
        "profile_sha256": plan["profile_sha256"],
        "workload_sha256": plan["workload_sha256"],
        "base_summary_sha256": sha(base / "summary.json"),
        "observed_summary_sha256": sha(observed / "summary.json"),
        "validation_extension_sha256": sha(OUT / "VALIDATION_EXTENSION.md"),
        "validation_script_sha256": sha(OUT / "validate_nonempty_observer.py"),
    }.items():
        assert proof[key] == expected
    for name, expected in proof["traces"].items():
        a, b = gzip.decompress((base / name).read_bytes()), gzip.decompress(
            (observed / name).read_bytes()
        )
        assert a == b and a
        assert len(a) == expected["decompressed_bytes"]
        assert len(a.splitlines()) == expected["rows"]
        assert hashlib.sha256(a).hexdigest() == expected["decompressed_sha256"]
        assert sha(base / name) == expected["base_file_sha256"]
        assert sha(observed / name) == expected["observed_file_sha256"]
    erratum_file = OUT / "TIMING_METADATA_ERRATUM.json"
    erratum = read(erratum_file)
    assert erratum["original_manifest_sha256"] == sha(OUT / "MANIFEST.json")
    assert erratum["profile_sha256"] == plan["profile_sha256"]
    assert not erratum["fallback_used"] and not erratum["numeric_results_changed"]
    for name, expected in erratum["original_artifacts_sha256"].items():
        assert sha(OUT / name) == expected, name
    report_file = HERE / "POSTHOC_SLACK_INDEPENDENT_REVIEW.json"
    report = read(report_file)
    for identity, digest in report["summary_sha256"].items():
        assert sha(OUT / "runs" / identity / "summary.json") == digest
    report["observer_validation_executions"] = 2
    report["observation_transparency_addendum"] = {
        "status": "PASS",
        "simulations_executed_by_reviewer": 0,
        "experiment_samples_added": 0,
        "job_id": job["id"],
        "summary_sha256": sha(base / "summary.json"),
        "traces": proof["traces"],
        "supplemental_proof_sha256": sha(OUT / "NONEMPTY_OBSERVATION_TRANSPARENCY.json"),
        "supersedes_initial_scope": (
            "Empirical parity now covers Restart F1 and this fixed nonempty DRAM F1 case; "
            "not all ten conditions or every possible workload. Journals include observer records."
        ),
    }
    report["timing_metadata_addendum"] = {
        "status": "ERRATUM_VERIFIED_ORIGINAL_SEAL_UNCHANGED",
        "path": str(erratum_file.relative_to(HERE.parent)),
        "sha256": sha(erratum_file),
        "bound_original_artifacts_reverified": len(erratum["original_artifacts_sha256"]),
        "corrected_interpretation": erratum["corrected_interpretation"],
    }
    report["addendum_script_sha256"] = sha(Path(__file__))
    report_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("PASS: nonempty observation parity and timing erratum; original seals unchanged")


if __name__ == "__main__":
    main()
