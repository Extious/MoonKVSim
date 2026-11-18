"""Independent audit gates use small real simulator artifacts, including corruption."""

from __future__ import annotations

import gzip
import importlib.util
import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from moonkvsim.aegiskv.current.__main__ import digest, manifest, run_one, write_json
from moonkvsim.aegiskv.current.model import Agent, Config, Failure, Invocation
from moonkvsim.aegiskv.evaluation_campaign import save_workload
from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile

AUDITOR = Path(__file__).resolve().parents[2] / (
    "benchmark/AegisKV/experiments/scripts/current_design/audit_profile_campaign.py"
)
spec = importlib.util.spec_from_file_location("profile_campaign_auditor", AUDITOR)
auditor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auditor)


@pytest.fixture
def campaign(tmp_path):
    out = tmp_path / "campaign"
    (out / "profiles").mkdir(parents=True)
    (out / "workloads").mkdir()
    data = dict(
        schema="aegiskv.duration-grid.v1",
        model="test",
        tp=1,
        config=dict(num_hidden_layers=2, num_key_value_heads=1, head_dim=2),
        context_grid=[0, 2048],
        prefill_extend_grid=[1, 64, 256],
        rows=[],
    )
    for context in data["context_grid"]:
        for stage, extend in [("decode", 1), ("prefill", 1), ("prefill", 64), ("prefill", 256)]:
            data["rows"].append(
                dict(
                    stage=stage,
                    context=context,
                    extend=extend,
                    latency_ns=10_000 if stage == "decode" else extend * 1000,
                )
            )
    write_json(out / "profiles/test.json", data)
    profile = GridDurationProfile(out / "profiles/test.json")
    config = replace(
        Config(),
        hosts=(0, 1, 2),
        tp=1,
        layers=2,
        depth=1,
        top_k=1,
        kv_bytes_per_token_per_layer_rank=8,
        hbm_bytes_per_rank=8 * 1024**2,
        dram_bytes_per_host=16 * 1024**2,
        reserve_bytes=4096,
        hbm_cap_bytes=4096,
        initial_quota_bytes=4096,
        network_bytes_per_second=100e6,
        h2d_bytes_per_second=100e6,
    )
    inv = Invocation(tuple(range(512)), (1,) * 256, model="test", output_limit_tokens=300)
    agents = tuple(Agent(w, "a", (), (inv,), 10**9) for w in ("w1", "w2"))
    content = save_workload(out / "workloads/w.json.gz", agents)
    work = dict(
        path="workloads/w.json.gz",
        sha256=digest(out / "workloads/w.json.gz"),
        content_sha256=content,
        workflows=2,
        agents=2,
    )
    write_json(out / "PRIORS.json", {"test": {"training_workflows": ["train"]}})
    jobs, index = [], []
    for policy in ("none", "dram"):
        for fault in (False, True):
            identity = f"{policy}-F{int(fault)}"
            failure = Failure("w1/a", invocation=0, progress=0.8) if fault else None
            job = dict(
                id=identity,
                model="test",
                workload="w",
                dataset="fixture",
                case="test",
                config=asdict(config),
                policy=policy,
                failure=asdict(failure) if failure else None,
                f0_id=f"{policy}-F0",
                fault_index=0 if fault else -1,
                detailed_logs=policy == "dram",
            )
            jobs.append(job)
            run_one(
                out / "runs" / identity,
                config,
                agents,
                policy,
                failure,
                duration_profile=profile,
                retain_detailed_logs=job["detailed_logs"],
            )
            row = dict(
                id=identity,
                complete=True,
                summary_sha256=digest(out / "runs" / identity / "summary.json"),
                job_sha256=auditor.object_sha(job),
                priors_sha256=digest(out / "PRIORS.json"),
                profile_sha256=digest(out / "profiles/test.json"),
                workload_sha256=work["sha256"],
            )
            write_json(out / "runs" / identity / "COMPLETE.json", row)
            index.append(row)
    write_json(out / "RUNS.json", index)
    write_json(
        out / "PLAN.json",
        dict(
            jobs=jobs,
            workloads={"w": work},
            training_workflows=["train"],
            evaluation_workflows=["w1", "w2"],
        ),
    )
    frozen = manifest(out)
    frozen["control_sha256"] = {n: digest(out / n) for n in ("PLAN.json", "PRIORS.json")}
    frozen["profile_sha256"] = {"profiles/test.json": digest(out / "profiles/test.json")}
    write_json(out / "MANIFEST.json", frozen)
    return out


def test_complete_campaign_distinguishes_summary_and_full_flow_evidence(campaign):
    result = auditor.audit(campaign)
    assert result["status"] == "PASS"
    assert result["verified_runs"] == 4
    assert result["full_log_independent_flow_audits"] == 2
    assert len(result["f0_f1_pairs"]) == 2
    sets = result["cross_policy_fault_sets"][0]
    assert sets["primary_identity_and_progress_match"]
    assert all("co_victim_invocations" in row for row in sets["actual"])
    stats = auditor.read(campaign / "STATISTICS.json")
    assert stats["confidence_intervals"] is None
    assert stats["negative_and_zero_outcomes_retained"]


def test_missing_marker_never_passes_whole_campaign(campaign):
    (campaign / "runs/dram-F1/COMPLETE.json").unlink()
    # Simulate a live parent index that has not yet recorded this unfinished run.
    write_json(
        campaign / "RUNS.json",
        [r for r in auditor.read(campaign / "RUNS.json") if r["id"] != "dram-F1"],
    )
    result = auditor.audit(campaign)
    assert result["status"] == "PARTIAL"
    assert result["partial_runs"] == ["dram-F1"]


def test_changed_frozen_prior_is_a_failure_even_when_run_summaries_unchanged(campaign):
    write_json(campaign / "PRIORS.json", {"test": {"training_workflows": ["different"]}})
    result = auditor.audit(campaign)
    assert result["status"] == "FAIL"
    assert any("control hash mismatch" in e["message"] for e in result["errors"])


def test_independent_flow_audit_catches_modified_transfer_bytes(campaign):
    path = campaign / "runs/dram-F1/flows.jsonl.gz"
    rows = list(auditor.jsonlines(path))
    assert rows
    rows[0]["transferred_bytes"] += 100
    with gzip.open(path, "wt") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    result = auditor.audit(campaign)
    assert result["status"] == "FAIL"
    assert any("transfer bytes do not reconcile" in e["message"] for e in result["errors"])


def test_independent_flow_audit_catches_rate_changes_with_unchanged_total_bytes(campaign):
    path = campaign / "runs/dram-F1/flows.jsonl.gz"
    rows = list(auditor.jsonlines(path))
    assert rows
    rows[0]["allocated_rate_bytes_per_second"] = 0
    with gzip.open(path, "wt") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    result = auditor.audit(campaign)
    assert result["status"] == "FAIL"
    assert any("service differs" in e["message"] for e in result["errors"])


def test_same_number_of_covictims_does_not_hide_changed_identities():
    jobs = [
        dict(
            id=policy,
            model="m",
            case="c",
            workload="w",
            fault_index=0,
            policy=policy,
            config={"hosts": [0, 1]},
            failure={"agent": "w/a"},
        )
        for policy in ("none", "dram")
    ]
    summaries = {}
    for policy, victim in (("none", "w/b"), ("dram", "w/c")):
        summaries[policy] = dict(
            failure=dict(
                agent="w/a", invocation=0, logical_tokens=80, total_tokens=100, workers=[0]
            ),
            recoveries=[dict(agent="w/a", invocation=0), dict(agent=victim, invocation=0)],
        )
    errors = []
    result = auditor.compare_fault_sets(jobs, summaries, errors)[0]
    assert not errors and result["primary_identity_and_progress_match"]
    assert result["same_sets"]["failed_workers"]
    assert not result["same_sets"]["co_victim_invocations"]
    assert (
        result["actual"][0]["co_victim_invocations"] != result["actual"][1]["co_victim_invocations"]
    )
