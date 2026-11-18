"""Pre-execution equivalence check against all 135 original main conditions."""

import gzip
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
OLD = OUT.parent / "structural-campaign-v1"


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


plan = read(OUT / "PLAN.json")
prior = read(OLD / "PLAN.json")
app = read(OUT / "IMPLEMENTATION_APPLICATION.json")
assert app["status"] == "PASS" and app["freeze_ready"] and app["source_edits_finished"]
assert plan["matrix_scope"] == "main-only" and plan["job_count"] == 135
seal = read(OUT / "PLAN_SEAL.json")
assert sha(OUT / "PLAN.json") == seal["plan_sha256"]
assert sha(OUT / "MANIFEST.json") == seal["manifest_sha256"]
for name, expected in app["source_sha256"].items():
    if name.startswith("python/"):
        assert sha(OUT / "source_snapshot" / name) == expected, name
before = {j["id"]: j for j in prior["jobs"] if j["workflows"] == 8}
after = {j["id"]: j for j in plan["jobs"]}
assert before.keys() == after.keys() and len(after) == 135
for name, old in before.items():
    new = after[name]
    assert {k: v for k, v in old.items() if k != "config"} == {
        k: v for k, v in new.items() if k != "config"
    }, name
    assert {k: new["config"][k] for k in old["config"]} == old["config"], name
    assert {k: new["config"][k] for k in new["config"].keys() - old["config"].keys()} == {
        "slack_mode": "dag"
    }, name
assert plan["profile_sha256"] == prior["profile_sha256"] == sha(OUT / plan["profile"])
for name, item in plan["workloads"].items():
    payload = gzip.decompress((OUT / item["path"]).read_bytes())
    old = prior["workloads"][name]
    assert payload == gzip.decompress((OLD / old["path"]).read_bytes()), name
    assert hashlib.sha256(payload).hexdigest() == item["sha256"] == old["sha256"]
    assert read(OUT / item["metadata"]) == read(OLD / old["metadata"])
assert not list((OUT / "runs").iterdir()), "matching must occur before execution"
result = dict(
    passed=True,
    runs=135,
    workloads=len(plan["workloads"]),
    planned_worker_processes=16,
    all_old_config_fields_exact=True,
    all_other_job_fields_exact=True,
    added_config_default={"slack_mode": "dag"},
    old_semantics="DAG Slack was unconditional in original frozen implementation",
    decoded_workload_bytes_exact=True,
    workload_metadata_exact=True,
    profile_bytes_exact=True,
    application_version=app["design_version"],
    runtime_sha256=app["runtime_after_sha256"],
    implementation_application_sha256=sha(OUT / "IMPLEMENTATION_APPLICATION.json"),
    plan_sha256=sha(OUT / "PLAN.json"),
    manifest_sha256=sha(OUT / "MANIFEST.json"),
    original_plan_sha256=sha(OLD / "PLAN.json"),
    checker_sha256=sha(Path(__file__)),
    original_runtime_unchanged=True,
    corrected_runs_are_replacements_not_new_samples=True,
)
(OUT / "INPUT_MATCH.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
print(json.dumps(result, indent=2))
