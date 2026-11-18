import hashlib
import json

import pytest

from moonkvsim.aegiskv.current.__main__ import digest, encoded, write_json
from moonkvsim.aegiskv.evaluation_campaign import run, verify_completed


@pytest.fixture
def completed_campaign(tmp_path):
    out = tmp_path
    target = out / "runs" / "test-F0"
    target.mkdir(parents=True)
    (out / "profiles").mkdir()
    job = dict(
        id="test-F0",
        workload="w",
        model="fixture",
        config=dict(depth=4),
        failure=None,
        policy="aegiskv",
    )
    write_json(out / "profiles/fixture.json", dict(test=True))
    write_json(out / "PRIORS.json", dict(training_workflows=["train"]))
    write_json(out / "workload.json", [dict(workflow="eval")])
    work = dict(
        path="workload.json",
        sha256=digest(out / "workload.json"),
        content_sha256=digest(out / "workload.json"),
    )
    write_json(target / "config.json", job["config"])
    write_json(target / "failure.json", None)
    write_json(
        target / "summary.json",
        dict(
            complete=True,
            terminal_allocations_zero=True,
            output_tokens_exact=True,
            policy="aegiskv",
            config_sha256=digest(target / "config.json"),
            workload_sha256=work["content_sha256"],
        ),
    )
    write_json(
        target / "COMPLETE.json",
        dict(
            id=job["id"],
            complete=True,
            summary_sha256=digest(target / "summary.json"),
            job_sha256=hashlib.sha256(encoded(job)).hexdigest(),
            priors_sha256=digest(out / "PRIORS.json"),
            profile_sha256=digest(out / "profiles/fixture.json"),
            workload_sha256=work["sha256"],
        ),
    )
    write_json(out / "PLAN.json", dict(jobs=[job], workloads=dict(w=work)))
    write_json(
        out / "MANIFEST.json",
        dict(
            source_sha256={},
            profile_sha256={},
            control_sha256={name: digest(out / name) for name in ("PLAN.json", "PRIORS.json")},
        ),
    )
    return out, job, work


def test_resume_recovers_parent_crash_after_all_workers_complete(completed_campaign):
    out, _, _ = completed_campaign
    assert not (out / "RUNS.json").exists()
    run(out, workers=1)
    assert len(json.loads((out / "RUNS.json").read_text())) == 1
    assert json.loads((out / "STATUS.json").read_text())["complete"]


def test_frozen_prediction_change_cannot_reuse_old_results(completed_campaign):
    out, _, _ = completed_campaign
    write_json(out / "PRIORS.json", dict(training_workflows=["different"]))
    with pytest.raises(ValueError, match="frozen control"):
        run(out, workers=1)


def test_completed_run_rejects_changed_fault_or_config(completed_campaign):
    out, job, work = completed_campaign
    verify_completed(out, job, work)
    with pytest.raises(ValueError, match="identity"):
        verify_completed(out, {**job, "failure": dict(agent="different")}, work)
    write_json(out / "runs/test-F0/config.json", dict(depth=8))
    with pytest.raises(ValueError, match="config mismatch"):
        verify_completed(out, job, work)
