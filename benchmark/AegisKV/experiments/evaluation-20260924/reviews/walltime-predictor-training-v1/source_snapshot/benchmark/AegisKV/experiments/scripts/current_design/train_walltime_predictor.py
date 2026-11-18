"""Freeze, collect, cross-fit and serialize a train-only Agent wall-time predictor.

Run prepare first. Execute run/fit using the frozen source_snapshot/python on
PYTHONPATH. evaluate accepts separately captured, disjoint held-out labels and
does not launch a simulator. Nothing here writes an older campaign or paper.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import shutil
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from moonkvsim.aegiskv.current.__main__ import (
    digest,
    load_workload,
    manifest,
    write_json,
    write_lines,
)
from moonkvsim.aegiskv.current.model import Config
from moonkvsim.aegiskv.evaluation_campaign import model_config, save_workload
from moonkvsim.aegiskv.evaluation_profile import GridDurationProfile, profile_manifest_fields
from moonkvsim.aegiskv.evaluation_walltime_predictor import (
    ContextCaptureRuntime,
    WalltimePredictor,
    error_metrics,
    error_rows,
    fit_model,
    pair_labels,
    quantile,
    reference_slack_errors,
)
from moonkvsim.aegiskv.evaluation_workload import load_fanoutqa_agents

ROOT = Path(__file__).resolve().parents[5]
DEFAULT_INPUTS = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/inputs"


def read(path):
    return json.loads(path.read_text())


def rows(path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def utc():
    return datetime.now(UTC).isoformat()


def prepare(out, inputs):
    out.mkdir(parents=True, exist_ok=False)
    for name in ("inputs", "profiles", "workloads", "configs"):
        (out / name).mkdir()
    split_path, bundle_path = (
        inputs / "fanoutqa-workflow-split.json",
        inputs / "fanoutqa-bundle.json",
    )
    split, bundle = read(split_path), read(bundle_path)
    train, excluded = split["native_train_ids"], split["native_eval_ids"]
    if len(train) != 12 or len(excluded) != 62 or set(train) & set(excluded):
        raise ValueError("expected the original disjoint 12/62 workflow split")
    if digest(bundle_path) != split["source_bundle_sha256"]:
        raise ValueError("split and bundle mismatch")
    bindings = {str(p.resolve()): digest(p) for p in (split_path, bundle_path)}
    for name in ("source_workload", "task_mapping", "tokenizer_equivalence"):
        entry = bundle[name]
        path = Path(entry["path"])
        if digest(path) != entry["sha256"]:
            raise ValueError(f"source binding differs: {name}")
        bindings[str(path.resolve())] = digest(path)
    for path in (split_path, bundle_path, Path(bundle["tokenizer_equivalence"]["path"])):
        shutil.copyfile(path, out / "inputs" / path.name)
    jobs, profile_evidence = [], {}
    for short_model in ("Qwen3-8B", "Qwen3-32B"):
        source_profile = inputs / "duration-profiles" / f"{short_model}.json"
        saved_profile = out / "profiles" / source_profile.name
        shutil.copyfile(source_profile, saved_profile)
        bindings[str(source_profile.resolve())] = digest(source_profile)
        profile = GridDurationProfile(saved_profile)
        equivalence = read(Path(bundle["tokenizer_equivalence"]["path"]))
        if (profile.data["model"], profile.data["revision"]) not in {
            (item["model_id"], item["revision"]) for item in equivalence["models"]
        }:
            raise ValueError("profile model revision lacks pinned tokenizer equivalence")
        agents = load_fanoutqa_agents(
            bundle_path,
            workflow_ids=train,
            prior_ns=10**10,
            target_model=profile.data["model"],
            max_context_tokens=40960,
        )
        if len(agents) != 95 or any(len(a.calls) != 1 for a in agents):
            raise ValueError("training task identities differ from the original split")
        agents = tuple(
            replace(a, calls=tuple(replace(c, output_limit_tokens=512) for c in a.calls))
            for a in agents
        )
        config = replace(model_config(profile), slack_guard_ns=0)
        profile_evidence[short_model] = profile_manifest_fields(profile, [asdict(config)])
        work = {workflow: 0 for workflow in train}
        for agent in agents:
            inv = agent.calls[0]
            work[agent.workflow] += profile(config, inv, 0, len(inv.prompt), "prefill")
            work[agent.workflow] += profile(config, inv, len(inv.prompt), len(inv.tokens), "decode")
        for load in (0.3, 0.65, 0.9):
            identity = f"{short_model}-load{load:g}-none-F0"
            interval = round(mean(work.values()) / len(config.hosts) / load)
            position = {workflow: i for i, workflow in enumerate(train)}
            scheduled = tuple(
                replace(a, release_ns=position[a.workflow] * interval) for a in agents
            )
            workload = f"workloads/{identity}.json.gz"
            save_workload(out / workload, scheduled)
            config_path = f"configs/{identity}.json"
            write_json(out / config_path, asdict(config))
            jobs.append(
                dict(
                    id=identity,
                    model=short_model,
                    model_id=profile.data["model"],
                    load=load,
                    policy="none",
                    failure=None,
                    profile=f"profiles/{short_model}.json",
                    workload=workload,
                    config=config_path,
                    workflow_count=12,
                    agent_count=95,
                    arrival_interval_ns=interval,
                )
            )
    protocol = dict(
        schema="aegiskv.walltime-training-protocol.v1",
        frozen_utc=utc(),
        jobs=jobs,
        training_workflows=train,
        excluded_evaluation_workflows=excluded,
        evaluation_workflow_use="identity-disjointness check only; no evaluation outcomes read",
        collection="six healthy none-policy FCFS runs, original 12 complete workflows once per run",
        input_context="actual runtime predictor Context; capture-only neutral prior_ns=10s",
        labels="offline Agent-final finish minus invocation submission, including queues",
        features="40 numeric/hashed-text features; not a validated semantic encoder",
        arrival_rule="mean train-only modeled workflow service / 8 / rho; frozen before DES",
        crossfit="per model leave-one-workflow-out; all three rho observations held out together",
        fit_epochs=300,
        hyperparameter_selection="none; existing learning rate=.1, L2=.001, 32 hash bins",
        role_prior="fold-train median first-submission Agent wall time by role; global fallback",
        context_transform="save raw Context; replace only prior_ns from fold training",
        final_fit="all12 workflows/all3 loads per model; deploy the same feature transform",
        guard_rule="nearest-rank p90 of12 workflow maxima of positive OOF CPM slack overestimation",
        guard_sampling="control-window grid from workflow release to completion; pool3loads",
        reference=(
            "offline residual DAG; started=final_finish-now; unstarted=final_finish-first_submit"
        ),
        reference_limit="queue-conditioned CPM, not counterfactual no-delay slack or a guarantee",
        snapshot_order="after every submission, publication and finish event at or before t",
        validation=dict(
            model="Qwen3-8B",
            load=0.65,
            purpose="one prior-only replay transparency check; not an additional sample",
        ),
        reporting="all OOF/signed errors, per-load/workflow-macro metrics, role-median baseline",
        limitations=[
            "12 workflows share six queue trajectories; observations are dependent",
            "all95 natural training Agents have one call; multi-call correctness tested separately",
            "Context has no queue/load input, so identical prompt contexts cannot distinguish rho",
            "labels are profile-based FCFS simulation wall times, not physical observations",
            "training-only calibration/final fit; no62-workflow tuning or performance matrix",
        ],
    )
    write_json(out / "TRAINING_PROTOCOL.json", protocol)
    write_json(out / "INPUT_BINDINGS.json", bindings)
    frozen = manifest(out)
    relative_script = Path(__file__).resolve().relative_to(ROOT)
    destination = out / "source_snapshot" / relative_script
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(__file__, destination)
    frozen["source_sha256"][str(relative_script)] = digest(Path(__file__))
    frozen.update(
        purpose="train-only-agent-walltime",
        prepared_utc=utc(),
        planned_healthy_runs=6,
        timing="pinned AIC HYBRID GridDurationProfile, not configured linear compute",
        profiles=profile_evidence,
        physical_execution=False,
        evidence_class="FCFS simulated Agent wall-time labels; hashed-text regression",
        foreground_dma_compute_interference="disabled in the six collection conditions",
    )
    write_json(out / "MANIFEST.json", frozen)
    paths = [out / n for n in ("TRAINING_PROTOCOL.json", "INPUT_BINDINGS.json", "MANIFEST.json")]
    for name in ("inputs", "profiles", "configs", "workloads"):
        paths.extend((out / name).iterdir())
    write_json(
        out / "TRAINING_SEAL.json",
        {
            "sealed_utc": utc(),
            "sha256": {str(p.relative_to(out)): digest(p) for p in sorted(paths)},
        },
    )
    print(f"Frozen six healthy training conditions: {out}", flush=True)


def verify(out):
    for name, expected in read(out / "TRAINING_SEAL.json")["sha256"].items():
        if digest(out / name) != expected:
            raise ValueError(f"frozen training input changed: {name}")
    source_hashes = read(out / "MANIFEST.json")["source_sha256"]
    for name, expected in source_hashes.items():
        if digest(out / "source_snapshot" / name) != expected:
            raise ValueError(f"frozen source changed: {name}")
    imported = {}
    for name, module in tuple(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if name.startswith("moonkvsim") and path and path.endswith(".py"):
            path = Path(path).resolve()
            relative = path.relative_to(ROOT)
            if source_hashes.get(str(relative)) != digest(path):
                raise ValueError(f"unsealed imported source: {path}")
            imported[str(path)] = digest(path)
    if source_hashes.get(str(Path(__file__).resolve().relative_to(ROOT))) != digest(Path(__file__)):
        raise ValueError("unsealed training runner")
    return imported


def capture(out, job, *, target=None, prior_model=None):
    target = target or out / "runs" / job["id"]
    applied_prior = prior_model.to_dict() if prior_model is not None else None
    prior_hash = hashlib.sha256(json.dumps(applied_prior, sort_keys=True).encode()).hexdigest()
    if target.exists():
        complete = read(target / "COMPLETE.json")
        if complete["applied_prior_model_sha256"] != prior_hash:
            raise ValueError("completed capture used different role priors")
        if complete["job"] != job or complete["training_seal_sha256"] != digest(
            out / "TRAINING_SEAL.json"
        ):
            raise ValueError("completed run identity mismatch")
        for name, expected in complete["sha256"].items():
            if digest(target / name) != expected:
                raise ValueError(f"completed capture changed: {name}")
        return
    target.mkdir(parents=True)
    raw = read(out / job["config"])
    config = Config(**{**raw, "hosts": tuple(raw["hosts"])})
    agents = load_workload(out / job["workload"])
    if prior_model is not None:
        agents = tuple(
            replace(
                a,
                prior_ns=prior_model.role_priors_ns.get(
                    a.role, prior_model.role_priors_ns["__all__"]
                ),
            )
            for a in agents
        )
    profile = GridDurationProfile(out / job["profile"])
    write_json(target / "config.json", asdict(config))
    write_json(
        target / "RUN_START.json",
        dict(
            started_utc=utc(),
            imports=verify(out),
            protocol_sha256=digest(out / "TRAINING_PROTOCOL.json"),
            python=platform.python_version(),
        ),
    )
    runtime = ContextCaptureRuntime(config, agents, duration_profile=profile)
    summary = runtime.run()
    if not summary["terminal_allocations_zero"] or summary["oracle_reservation_count"]:
        raise RuntimeError("healthy collection failed resource/reservation invariants")
    paired = pair_labels(runtime.captured_contexts, summary, run_id=job["id"], load=job["load"])
    write_json(target / "summary.json", summary)
    write_lines(target / "contexts.jsonl.gz", runtime.captured_contexts)
    write_lines(target / "labels.jsonl.gz", paired)
    verify(out)
    write_json(
        target / "COMPLETE.json",
        dict(
            completed_utc=utc(),
            job=job,
            captures=len(paired),
            training_seal_sha256=digest(out / "TRAINING_SEAL.json"),
            applied_prior_model_sha256=prior_hash,
            sha256={p.name: digest(p) for p in sorted(target.iterdir())},
        ),
    )
    print("Captured", job["id"], len(paired), flush=True)


def fit(out):
    verify(out)
    protocol = read(out / "TRAINING_PROTOCOL.json")
    if (out / "MODELS_COMPLETE.json").exists():
        raise FileExistsError("refusing to overwrite fitted artifacts")
    jobs = protocol["jobs"]
    all_rows = []
    for job in jobs:
        capture(out, job)  # verifies completed artifacts; caller run already collected all six
        all_rows.extend(rows(out / "runs" / job["id"] / "labels.jsonl.gz"))
    if set(r["workflow"] for r in all_rows) != set(protocol["training_workflows"]):
        raise ValueError("training identities differ from frozen split")
    if set(r["workflow"] for r in all_rows) & set(protocol["excluded_evaluation_workflows"]):
        raise ValueError("evaluation label leakage")
    model_reports = {}
    for short_model in sorted({j["model"] for j in jobs}):
        selected_jobs = [j for j in jobs if j["model"] == short_model]
        selected = [r for r in all_rows if r["run_id"] in {j["id"] for j in selected_jobs}]
        model_dir = out / "models" / short_model
        model_dir.mkdir(parents=True, exist_ok=False)
        (model_dir / "folds").mkdir()
        folds, predictions = {}, []
        for workflow in protocol["training_workflows"]:
            fitted = fit_model(
                [r for r in selected if r["workflow"] != workflow], epochs=protocol["fit_epochs"]
            )
            folds[workflow] = fitted
            write_json(model_dir / "folds" / f"{workflow}.json", fitted.to_dict())
            predictions.extend(
                error_rows(fitted, [r for r in selected if r["workflow"] == workflow])
            )
        write_lines(model_dir / "oof-errors.jsonl.gz", predictions)
        points = []
        for job in selected_jobs:
            raw = read(out / job["config"])
            config = Config(**{**raw, "hosts": tuple(raw["hosts"])})
            points.extend(
                reference_slack_errors(
                    load_workload(out / job["workload"]),
                    config,
                    [r for r in selected if r["run_id"] == job["id"]],
                    folds,
                )
            )
        write_lines(model_dir / "oof-slack-errors.jsonl.gz", points)
        maxima = {
            w: max((r["overestimation_ns"] for r in points if r["workflow"] == w), default=0)
            for w in protocol["training_workflows"]
        }
        guard = quantile(maxima.values())
        final = replace(fit_model(selected, epochs=protocol["fit_epochs"]), slack_guard_ns=guard)
        write_json(model_dir / "model.json", final.to_dict())
        write_json(
            model_dir / "deployment.json",
            dict(
                role_priors_ns=final.role_priors_ns,
                slack_guard_ns=guard,
                context_transform="replace prior_ns from saved model/role; other fields unchanged",
                unstarted_agents="apply role priors to Agent.prior_ns before runtime construction",
                model_sha256=digest(model_dir / "model.json"),
            ),
        )
        report = dict(
            status="COMPLETE",
            train_workflows=list(final.training_workflows),
            observations=len(selected),
            oof=error_metrics(predictions),
            slack_guard_ns=guard,
            workflow_max_slack_overestimation_ns=maxima,
            slack_observations=len(points),
            fallback_observations=sum(p["fallback"] for p in points),
            guard_evidence="OOF healthy-training residual CPM; not an external coverage guarantee",
            train_eval_disjoint=not (
                set(final.training_workflows) & set(protocol["excluded_evaluation_workflows"])
            ),
        )
        write_json(model_dir / "REPORT.json", report)
        model_reports[short_model] = report
        print(
            "Fitted",
            short_model,
            "OOF MAE(s)",
            report["oof"]["all"]["mae_ns"] / 1e9,
            "guard(s)",
            guard / 1e9,
            flush=True,
        )
    job = next(j for j in jobs if j["model"] == "Qwen3-8B" and j["load"] == 0.65)
    model = WalltimePredictor.from_dict(read(out / "models/Qwen3-8B/model.json"))
    validation = out / "validation" / "role-prior-transparency"
    capture(out, job, target=validation, prior_model=model)
    base, changed = (
        read(out / "runs" / job["id"] / "summary.json"),
        read(validation / "summary.json"),
    )
    excluded = {"slack_fallback_observations"}
    foreground_fields = (
        "requests",
        "workflows",
        "peak_bytes",
        "failure",
        "recoveries",
        "history_restores",
        "output_tokens_exact",
        "terminal_allocations_zero",
    )
    for field in foreground_fields:
        if base[field] != changed[field]:
            raise RuntimeError(f"role-prior transparency failed: {field}")

    def clean(summary):
        return {k: v for k, v in summary["metrics"].items() if k not in excluded}

    if clean(base) != clean(changed):
        raise RuntimeError("role-prior transparency failed: foreground metrics")
    original_contexts = rows(out / "runs" / job["id"] / "contexts.jsonl.gz")
    updated_contexts = rows(validation / "contexts.jsonl.gz")
    for original, updated in zip(original_contexts, updated_contexts, strict=True):
        original = {**original, "raw_context": dict(original["raw_context"])}
        updated = {**updated, "raw_context": dict(updated["raw_context"])}
        role = updated["raw_context"]["role"]
        if updated["raw_context"]["prior_ns"] != model.role_priors_ns.get(
            role, model.role_priors_ns["__all__"]
        ):
            raise RuntimeError("deployment role prior was not applied")
        if original["raw_context"].pop("prior_ns") != 10**10:
            raise RuntimeError("baseline prior differs from protocol")
        updated["raw_context"].pop("prior_ns")
        if original != updated:
            raise RuntimeError("role-prior transparency failed: another Context field changed")
    write_json(
        out / "PRIOR_TRANSPARENCY.json",
        dict(
            status="PASS",
            planned_validation=protocol["validation"],
            compared_fields=list(foreground_fields),
            all_other_metrics_equal=True,
            all_other_context_fields_equal=True,
            applied_deployment_priors_verified=True,
            allowed_prediction_metric_differences={
                k: [base["metrics"].get(k), changed["metrics"].get(k)] for k in excluded
            },
            base_summary_sha256=digest(out / "runs" / job["id"] / "summary.json"),
            validation_summary_sha256=digest(validation / "summary.json"),
            limitation="one fixed none-policy case; no all-workload/backup-policy generalization",
        ),
    )
    write_json(
        out / "REPORT.json",
        dict(
            status="COMPLETE",
            healthy_training_runs=6,
            validation_runs=1,
            label_rows=len(all_rows),
            models=model_reports,
            evaluation_workflows_used_for_training=0,
            evidence="lightweight hashed-text regressor of profile-based FCFS Agent wall time",
            limitations=protocol["limitations"],
        ),
    )
    verify(out)
    artifacts = [
        p
        for name in ("runs", "models", "validation")
        for p in (out / name).rglob("*")
        if p.is_file()
    ]
    artifacts += [out / "REPORT.json", out / "PRIOR_TRANSPARENCY.json"]
    write_json(
        out / "MODELS_COMPLETE.json",
        dict(
            completed_utc=utc(),
            training_seal_sha256=digest(out / "TRAINING_SEAL.json"),
            sha256={str(p.relative_to(out)): digest(p) for p in sorted(artifacts)},
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "fit", "verify", "evaluate"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--samples", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command == "prepare":
        prepare(out, args.inputs)
    elif args.command == "evaluate":
        model = WalltimePredictor.from_dict(read(args.model))
        output = error_rows(model, rows(args.samples))
        out.mkdir(parents=True, exist_ok=False)
        write_lines(out / "errors.jsonl.gz", output)
        write_json(
            out / "REPORT.json",
            dict(
                model_sha256=digest(args.model),
                samples_sha256=digest(args.samples),
                heldout_workflows=sorted({r["workflow"] for r in output}),
                metrics=error_metrics(output),
                simulation_runs=0,
                training_overlap_rejected=True,
            ),
        )
    else:
        verify(out)
        if args.command == "run":
            for job in read(out / "TRAINING_PROTOCOL.json")["jobs"]:
                capture(out, job)
            fit(out)
        elif args.command == "fit":
            if len(list((out / "runs").glob("*/COMPLETE.json"))) != 6:
                raise ValueError("fit requires six completed healthy runs")
            fit(out)
        else:
            if (out / "MODELS_COMPLETE.json").exists():
                for name, expected in read(out / "MODELS_COMPLETE.json")["sha256"].items():
                    if digest(out / name) != expected:
                        raise ValueError(f"training artifact changed: {name}")
            print("Frozen source/input/artifact hashes PASS")


if __name__ == "__main__":
    main()
