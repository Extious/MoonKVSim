"""Independently bind v3 captures/models, then reuse unchanged primary endpoints.

This auditor imports no simulator or predictor. It performs no fitting and no
DES execution. The original endpoint arithmetic is copied and hash checked;
new provenance identifies the wall-time intervention separately from core code.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import shutil
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[5]
SCRIPTS = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def lines(path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_audit(out):
    plan, manifest = read(out / "PLAN.json"), read(out / "MANIFEST.json")
    train, evaluation = set(plan["training_workflows"]), set(plan["evaluation_workflows"])
    assert len(train) == 12 and len(evaluation) == 62 and not train & evaluation
    for relative, expected in read(out / "PROTOCOL_SEAL.json")["sha256"].items():
        assert sha(out / relative) == expected, relative
    for relative, expected in manifest["source_sha256"].items():
        assert sha(out / "source_snapshot" / relative) == expected, relative
    jobs = [j for j in plan["jobs"] if j["capture_context"]]
    assert len(jobs) == 6
    reports, samples = [], defaultdict(list)
    for job in jobs:
        folder = out / "runs" / job["id"]
        marker, summary = read(folder / "COMPLETE.json"), read(folder / "summary.json")
        start, model = read(folder / "RUN_START.json"), read(out / job["predictor"])
        assert job["policy"] == "none" and job["failure"] is None
        assert marker["predictor_sha256"] == sha(out / job["predictor"])
        assert marker["protocol_seal_sha256"] == sha(out / "PROTOCOL_SEAL.json")
        assert marker["summary_sha256"] == sha(folder / "summary.json")
        assert summary["predictor"] == model["name"]
        assert set(model["regressor"]["training_workflows"]) == train
        assert job["config"]["slack_guard_ns"] == model["slack_guard_ns"]
        assert start["started_utc"] > read(out / "PROTOCOL_SEAL.json")["sealed_utc"]
        for relative, expected in start["imported_source_sha256"].items():
            assert expected == manifest["source_sha256"][relative]
        for relative, expected in marker["artifacts_sha256"].items():
            assert sha(folder / relative) == expected
        descriptor = plan["workloads"][job["workload"]]
        agents = json.loads(gzip.decompress((out / descriptor["path"]).read_bytes()))
        agents = {a["workflow"] + "/" + a["name"]: a for a in agents}
        requests = {(r["agent"], r["invocation"], r["submit_ns"]): r for r in summary["requests"]}
        final = defaultdict(int)
        for r in summary["requests"]:
            final[r["agent"]] = max(final[r["agent"]], r["finish_ns"])
        contexts, labels, errors = [
            lines(folder / n) for n in ("contexts.jsonl.gz", "labels.jsonl.gz", "errors.jsonl.gz")
        ]
        assert len(contexts) == len(labels) == len(errors) == len(requests) == 503
        seen = set()
        for context, label, error in zip(contexts, labels, errors, strict=True):
            key = context["agent"], context["invocation"], context["submitted_ns"]
            assert key not in seen and key in requests
            seen.add(key)
            agent, request = agents[key[0]], requests[key]
            assert context["workflow"] == agent["workflow"] in evaluation
            invocation = agent["calls"][key[1]]
            assert len(agent["calls"]) == 1 and key[1] == 0
            expected_context = dict(
                model=invocation["model"],
                role=agent["role"],
                text=invocation["text"],
                prompt_tokens=len(invocation["prompt"]),
                completed_calls=0,
                previous_durations_ns=[],
                previous_output_tokens=[],
                elapsed_ns=0,
                prior_ns=model["role_priors_ns"].get(
                    agent["role"], model["role_priors_ns"]["__all__"]
                ),
            )
            assert context["raw_context"] == expected_context
            assert error["derived_context"] == expected_context
            for record in (label, error):
                assert all(record[k] == v for k, v in context.items())
                assert record["remaining_ns"] == final[key[0]] - key[2]
                assert record["agent_final_finish_ns"] == final[key[0]]
                assert record["invocation_finish_ns"] == request["finish_ns"]
                assert record["run_id"] == job["id"]
                assert record["nominal_load"] == descriptor["offered_load_proxy"]
            assert set(error["prior_training_workflows"]) == train
            assert error["signed_error_ns"] == error["prediction_ns"] - label["remaining_ns"]
            assert error["absolute_error_ns"] == abs(error["signed_error_ns"])
            assert error["role_median_baseline_ns"] == expected_context["prior_ns"]
            assert error["baseline_absolute_error_ns"] == abs(
                expected_context["prior_ns"] - label["remaining_ns"]
            )
            samples[job["model"]].append(error)
        assert seen == requests.keys()
        reports.append(
            dict(
                run=job["id"],
                observations=len(labels),
                workflows=len(evaluation),
                context_label_pairing="PASS",
                reconstructed_causal_context_exact=True,
                summary_sha256=sha(folder / "summary.json"),
                contexts_sha256=sha(folder / "contexts.jsonl.gz"),
                errors_sha256=sha(folder / "errors.jsonl.gz"),
            )
        )
    transparency = read(out / "OBSERVATION_TRANSPARENCY.json")
    assert transparency["status"] == "PASS"
    observed = out / "runs" / transparency["run"]
    base = out / "validation/base-runtime"
    for name, row in transparency["artifacts"].items():
        data = [p.read_bytes() for p in (observed / name, base / name)]
        if name.endswith(".gz"):
            data = [gzip.decompress(d) for d in data]
        assert data[0] == data[1]
        assert hashlib.sha256(data[0]).hexdigest() == row["content_sha256"]
    aggregates = {}
    for model, values in samples.items():
        aggregates[model] = {}
        for rho in sorted({r["nominal_load"] for r in values}):
            rows = [r for r in values if r["nominal_load"] == rho]
            ordered = sorted(r["absolute_error_ns"] for r in rows)
            metrics = dict(
                observations=len(rows),
                workflows=len({r["workflow"] for r in rows}),
                mae_ns=mean(r["absolute_error_ns"] for r in rows),
                bias_ns=mean(r["signed_error_ns"] for r in rows),
                p90_absolute_error_ns=ordered[math.ceil(len(rows) * 0.9) - 1],
                role_median_mae_ns=mean(r["baseline_absolute_error_ns"] for r in rows),
            )
            reported = read(out / "HELDOUT_ERROR.json")["models"][model]["by_load"][str(rho)]
            assert all(reported[k] == v for k, v in metrics.items())
            aggregates[model][str(rho)] = metrics
    result = dict(
        status="PASS",
        audited_runs=6,
        observations=3018,
        per_run=reports,
        independent_error_arithmetic=aggregates,
        all_online_context_fields_reconstructed_from_submission_inputs=True,
        observation_transparency_case=transparency["run"],
        training_evaluation_workflows_disjoint=True,
        test_set_refitting_performed=False,
        frozen_sources_verified=True,
        scope=(
            "stdlib artifact/Context/label/error arithmetic audit; no simulator or predictor "
            "imported; raw prediction values are tied to the frozen model by execution "
            "provenance, not independently reimplemented"
        ),
        auditor_sha256=sha(Path(__file__)),
    )
    write(out / "HELDOUT_INDEPENDENT_AUDIT.json", result)
    return result


def numeric_endpoints(out):
    # Run the sealed original audit code with the real repository used only to
    # resolve already-hashed upstream inputs, never simulator execution.
    audit_path = (
        out
        / "source_snapshot"
        / "benchmark/AegisKV/experiments/scripts/current_design/audit_profile_campaign.py"
    )
    auditor = load_module("sealed_profile_auditor", audit_path)
    auditor.ROOT = ROOT
    report = auditor.audit(out)
    assert report["status"] == "PASS", report["status"]
    original = Path(read(out / "PROTOCOL.json")["original_campaign"])
    original_provenance = read(original / "endpoints/PROVENANCE.json")
    path = SCRIPTS / "analyze_primary_endpoints.py"
    assert sha(path) == original_provenance["analysis_sha256"]
    saved = out / "analysis_source_snapshot" / path.name
    saved.parent.mkdir(exist_ok=True)
    if saved.exists():
        assert sha(saved) == sha(path)
    else:
        shutil.copyfile(path, saved)
    analysis = load_module("unchanged_primary_endpoints", saved)
    analysis.analyze(out)
    write(
        out / "endpoints/WALLTIME_MODEL_PROVENANCE.json",
        dict(
            intervention="joint final walltime predictor, role priors and training-only guard",
            core_version_unchanged=True,
            predictor_sha256=read(out / "MANIFEST.json")["predictor_sha256"],
            protocol_seal_sha256=sha(out / "PROTOCOL_SEAL.json"),
            plan_sha256=sha(out / "PLAN.json"),
            heldout_independent_audit_sha256=sha(out / "HELDOUT_INDEPENDENT_AUDIT.json"),
            endpoint_provenance_sha256=sha(out / "endpoints/PROVENANCE.json"),
            analysis_source_sha256=sha(saved),
            label="new walltime-trained v3 intervention; not original service-proxy v2",
        ),
    )


def main():
    global ROOT, SCRIPTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--capture-only", action="store_true")
    args = parser.parse_args()
    ROOT = args.repository_root.resolve()
    SCRIPTS = ROOT / "benchmark/AegisKV/experiments/scripts/current_design"
    out = args.campaign.resolve()
    while not (out / "HELDOUT_ERROR.json").exists():
        if not args.wait:
            raise SystemExit("PARTIAL: heldout capture phase is unfinished")
        if (out / "RUN_ERROR.json").exists():
            raise SystemExit("runner error; retaining partial campaign")
        time.sleep(20)
    capture_audit(out)
    print("heldout capture/context/label/error audit PASS", flush=True)
    if args.capture_only:
        return
    while not read(out / "STATUS.json")["complete"]:
        if not args.wait:
            raise SystemExit("PARTIAL: waiting for all180 conditions")
        if (out / "RUN_ERROR.json").exists():
            raise SystemExit("runner error; retaining partial campaign")
        time.sleep(30)
    numeric_endpoints(out)
    print("full resource/identity audit and unchanged numeric endpoint analysis PASS", flush=True)


if __name__ == "__main__":
    main()
