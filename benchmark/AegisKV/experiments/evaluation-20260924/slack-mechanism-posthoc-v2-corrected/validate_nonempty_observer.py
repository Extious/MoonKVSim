"""One additional validation; imports only the original frozen runtime."""

import gzip
import hashlib
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
SNAPSHOT = OUT / "source_snapshot"
sys.path.insert(0, str(SNAPSHOT / "python"))

from moonkvsim.aegiskv.current.__main__ import load_workload, run_one, write_json  # noqa: E402
from moonkvsim.aegiskv.current.model import Config, Failure  # noqa: E402
from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile  # noqa: E402


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for name, expected in json.loads((OUT / "SEAL.json").read_text()).items():
        assert sha(OUT / name) == expected
    manifest = json.loads((OUT / "MANIFEST.json").read_text())
    for name, expected in manifest["source_sha256"].items():
        assert sha(SNAPSHOT / name) == expected
    for name, module in list(sys.modules.items()):
        if name.startswith("moonkvsim") and getattr(module, "__file__", None):
            assert Path(module.__file__).resolve().is_relative_to(SNAPSHOT)
    plan = json.loads((OUT / "PLAN.json").read_text())
    job = next(j for j in plan["jobs"] if j["id"] == "dram1342177280-dag-F1")
    assert sha(OUT / plan["profile"]) == plan["profile_sha256"]
    assert (
        hashlib.sha256(gzip.decompress((OUT / plan["workload"]).read_bytes())).hexdigest()
        == plan["workload_sha256"]
    )
    target = OUT / "validation/tight-dag-F1-base-runtime"
    if target.exists():
        raise FileExistsError("preserving prior validation; refusing an unrecorded rerun")
    run_one(
        target,
        Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])}),
        load_workload(OUT / plan["workload"]),
        job["policy"],
        Failure(**job["failure"]),
        duration_profile=GridDurationProfile(OUT / plan["profile"]),
        journal=True,
        retain_detailed_logs=True,
    )
    observed = OUT / "runs" / job["id"]
    assert (target / "summary.json").read_bytes() == (observed / "summary.json").read_bytes()
    records = {}
    for name in ("events.jsonl.gz", "flows.jsonl.gz"):
        original, base = (
            gzip.decompress((observed / name).read_bytes()),
            gzip.decompress((target / name).read_bytes()),
        )
        assert original == base and len(base) > 0
        records[name] = dict(
            byte_identical=True,
            decompressed_bytes=len(base),
            rows=len(base.splitlines()),
            decompressed_sha256=hashlib.sha256(base).hexdigest(),
            observed_file_sha256=sha(observed / name),
            base_file_sha256=sha(target / name),
        )
    write_json(
        OUT / "NONEMPTY_OBSERVATION_TRANSPARENCY.json",
        dict(
            passed=True,
            experiment_samples_added=0,
            additional_validation_runs=1,
            total_validation_runs=2,
            job_id=job["id"],
            summary_byte_identical=True,
            base_summary_sha256=sha(target / "summary.json"),
            observed_summary_sha256=sha(observed / "summary.json"),
            traces=records,
            plan_sha256=sha(OUT / "PLAN.json"),
            manifest_sha256=sha(OUT / "MANIFEST.json"),
            profile_sha256=plan["profile_sha256"],
            workload_sha256=plan["workload_sha256"],
            validation_extension_sha256=sha(OUT / "VALIDATION_EXTENSION.md"),
            validation_script_sha256=sha(Path(__file__)),
            scope="One fixed nonempty-checkpoint DRAM case plus the prior empty-flow Restart case; not a proof for all possible workloads.",
        ),
    )
    print("PASS: nonempty checkpoint/recovery summary, events, flows exactly equal")


if __name__ == "__main__":
    main()
