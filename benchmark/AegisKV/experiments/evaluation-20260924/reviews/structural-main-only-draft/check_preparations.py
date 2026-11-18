"""Check preparation identity and endpoint extraction, without running simulations."""

import csv
import gzip
import hashlib
import importlib.util
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent.parent / "structural-campaign-v1"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runner = module("structural_runner_review", "run_structural_campaign.py")
original = read(OLD / "PLAN.json")
reports = []
for dirname, expected in (("preparation-check-main", 135), ("preparation-check-default", 143)):
    directory = ROOT / dirname
    plan = runner.verify(directory)
    assert len(plan["jobs"]) == expected
    assert not list((directory / "runs").iterdir()), "preparation must never execute a simulation"
    selected = {r["id"]: r for r in original["jobs"] if expected == 143 or r["workflows"] == 8}
    actual = {r["id"]: r for r in plan["jobs"]}
    assert selected.keys() == actual.keys()
    additions = []
    for identity, old in selected.items():
        new = actual[identity]
        assert {k: v for k, v in old.items() if k != "config"} == {
            k: v for k, v in new.items() if k != "config"
        }
        before, after = old["config"], new["config"]
        assert {k: after[k] for k in before} == before
        extra = {k: after[k] for k in after.keys() - before.keys()}
        assert extra == {"slack_mode": "dag"}
        assert asdict(runner.Config(**before)) == asdict(runner.Config(**after))
        additions.append(dict(id=identity, explicit_added_config_defaults=extra))
    assert plan["profile_sha256"] == original["profile_sha256"]
    checked = []
    for identity, item in plan["workloads"].items():
        payload = gzip.decompress((directory / item["path"]).read_bytes())
        reference = original["workloads"][identity]
        assert hashlib.sha256(payload).hexdigest() == item["sha256"] == reference["sha256"]
        assert payload == gzip.decompress((OLD / reference["path"]).read_bytes())
        assert read(directory / item["metadata"]) == read(OLD / reference["metadata"])
        checked.append(identity)
    reports.append(
        dict(
            preparation=dirname,
            jobs=expected,
            all_nonsource_job_fields_exact_except_documented_defaults=True,
            decoded_workload_bytes_exact=True,
            metadata_exact=True,
            workloads=checked,
            config_schema_additions=additions,
            no_simulation_executed=True,
            plan_sha256=sha(directory / "PLAN.json"),
            manifest_sha256=sha(directory / "MANIFEST.json"),
        )
    )
    with tempfile.TemporaryDirectory() as tmp:
        corrupt = Path(tmp)
        for name in ("PLAN.json", "MANIFEST.json", "PLAN_SEAL.json"):
            (corrupt / name).write_bytes((directory / name).read_bytes())
        bad = read(corrupt / "PLAN.json")
        bad["job_count"] += 1
        (corrupt / "PLAN.json").write_text(json.dumps(bad))
        try:
            runner.verify(corrupt)
        except ValueError as exc:
            assert str(exc) == "frozen plan/manifest changed"
        else:
            raise AssertionError("changed plan was accepted")
plot = module("structural_plot_review", "plot_structural_campaign.py")
plot.SOURCE = OLD
plot.OUT = ROOT / "historical-endpoint-table-check"
plot.OUT.mkdir(exist_ok=True)
target, queue, service, paired = plot.verify_inputs(main_only=True)
all_means = plot.endpoint_tables(paired)
assert len(all_means) == 90
with (plot.OUT / "wct-endpoints-per-run.csv").open() as stream:
    endpoints = list(csv.DictReader(stream))
for row in endpoints:
    key = row["scenario"], row["fault"], row["policy"], int(row["seed"])
    assert float(row["target_delta_wct_s"]) == target[key]
    same = [r for r in paired if (r["scenario"], r["fault"], r["policy"], int(r["seed"])) == key]
    assert len(same) == 8
    independent = sum(float(r["delta_wct_s"]) for r in same) / 8
    assert abs(all_means[key] - independent) < 1e-10
(plot.OUT / "README.md").write_text(
    "Historical data only, used to check endpoint aggregation code. No corrected experiment and no figure is produced.\n"
)
result = dict(
    passed=True,
    preparations=reports,
    plan_mutation_rejected=True,
    historical_endpoint_rows=90,
    paired_workflow_rows=720,
    target_and_all_workflow_endpoint_crosschecks=True,
    simulations_executed=0,
    figures_exported=0,
    scripts_sha256={p.name: sha(p) for p in ROOT.glob("*.py")},
)
(ROOT / "PREPARATION_CHECK.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
print(json.dumps({k: v for k, v in result.items() if k != "preparations"}, indent=2))
