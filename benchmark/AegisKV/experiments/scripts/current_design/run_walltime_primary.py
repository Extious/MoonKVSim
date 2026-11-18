"""Prepare and detach an immutable 180-condition wall-time-predictor intervention.

Only serialized predictors, their deployment priors and training-only guards
change relative to the original primary. No training or test-set tuning occurs.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import run_frozen_profile_campaign as replay

from moonkvsim.aegiskv.current.__main__ import digest, encoded, load_workload, write_json
from moonkvsim.aegiskv.evaluation_walltime_campaign import verify_frozen
from moonkvsim.aegiskv.evaluation_walltime_predictor import WalltimePredictor

ROOT = Path(__file__).resolve().parents[5]
RELATIVE = "benchmark/AegisKV/experiments/scripts/current_design"
MODULE = "python/moonkvsim/aegiskv/evaluation_walltime_predictor.py"

BOOTSTRAP = """from __future__ import annotations
import argparse, fcntl, hashlib, importlib.abc, importlib.machinery, json, sys, traceback
from pathlib import Path
TREE = Path(__file__).resolve().parent
PACKAGE = TREE / "python"
sys.path.insert(0, str(PACKAGE))
class FrozenOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "moonkvsim" or fullname.startswith("moonkvsim."):
            spec = importlib.machinery.PathFinder.find_spec(fullname, path or [str(PACKAGE)])
            if (spec is None or spec.origin is None
                    or not Path(spec.origin).resolve().is_relative_to(PACKAGE)):
                raise ImportError("MoonKVSim import escaped immutable snapshot: " + fullname)
            return spec
        return None
sys.meta_path.insert(0, FrozenOnly())
from moonkvsim.aegiskv import evaluation_walltime_campaign as campaign
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--limit", type=int)
    p.add_argument("--verify-only", action="store_true")
    args = p.parse_args()
    campaign.verify_frozen(args.out)
    report = dict(imported_source_sha256=campaign.imported_sources(),
                  root=str(TREE), python=sys.version)
    if args.verify_only:
        campaign.write_json(args.out / "IMPORT_PREFLIGHT.json", report)
    else:
        with (args.out / "RUNNING.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            campaign.write_json(args.out / "RUN_IMPORTS.json", report)
            try:
                campaign.run(args.out, args.workers, args.limit)
            except BaseException as error:
                campaign.write_json(args.out / "RUN_ERROR.json", dict(
                    type=type(error).__name__, message=str(error),
                    traceback=traceback.format_exc()))
                raise
            finally:
                campaign.write_json(args.out / "FINAL_IMPORTS.json", dict(
                    imported_source_sha256=campaign.imported_sources(), root=str(TREE)))
"""


def read(path):
    return json.loads(path.read_bytes())


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def prepare(out, original, training):
    original_manifest, original_plan = replay.verify_artifacts(original)
    if original_plan["planned_runs"] != 180 or len(original_plan["jobs"]) != 180:
        raise ValueError("expected original 180-condition primary")
    delivery, model_seal = read(training / "DELIVERY.json"), read(training / "MODELS_COMPLETE.json")
    for name, expected in delivery["sha256"].items():
        if digest(training / name) != expected:
            raise ValueError("training delivery changed: " + name)
    for name, expected in model_seal["sha256"].items():
        if digest(training / name) != expected:
            raise ValueError("training model seal mismatch: " + name)
    training_manifest = read(training / "MANIFEST.json")
    if digest(training / "source_snapshot" / MODULE) != training_manifest["source_sha256"][MODULE]:
        raise ValueError("training predictor implementation drifted")
    if read(training / "INDEPENDENT_ARTIFACT_AUDIT.json")["status"] != "PASS":
        raise ValueError("training independent audit did not pass")
    out.mkdir(parents=True, exist_ok=False)
    for name in ("MANIFEST.json", "PLAN.json", "PRIORS.json", "REPLAY_MANIFEST.json"):
        copy_file(original / name, out / "original" / name)
    for name in (
        "DELIVERY.json",
        "MODELS_COMPLETE.json",
        "TRAINING_SEAL.json",
        "TRAINING_PROTOCOL.json",
        "INDEPENDENT_ARTIFACT_AUDIT.json",
        "REPORT.json",
    ):
        copy_file(training / name, out / "training" / name)

    plan = copy.deepcopy(original_plan)
    original_priors = read(original / "PRIORS.json")
    models, priors, predictor_hashes = {}, {}, {}
    for model in ("Qwen3-8B", "Qwen3-32B"):
        relative = f"models/{model}.json"
        copy_file(training / f"models/{model}/model.json", out / relative)
        models[model] = predictor = WalltimePredictor.from_dict(read(out / relative))
        if set(predictor.training_workflows) != set(plan["training_workflows"]):
            raise ValueError("model fitted workflows differ from original training split")
        if set(predictor.training_workflows) & set(plan["evaluation_workflows"]):
            raise ValueError("model train/evaluation identity leakage")
        predictor_hashes[relative] = digest(out / relative)
        copy_file(original / f"profiles/{model}.json", out / f"profiles/{model}.json")
        if digest(out / f"profiles/{model}.json") != digest(training / f"profiles/{model}.json"):
            raise ValueError("training/primary model profiles differ")
        priors[model] = dict(
            evidence=(
                "healthy submission-to-same-Agent-final-completion labels including queue; "
                "training-only LOOWF slack calibration"
            ),
            role_prior_ns=predictor.role_priors_ns,
            slack_guard_ns=predictor.slack_guard_ns,
            training_workflows=list(predictor.training_workflows),
            training_tasks=95,
            predictor=relative,
            predictor_sha256=predictor_hashes[relative],
            depth_choice=original_priors[model]["depth_choice"],
            depth_choice_provenance=(
                "unchanged original offline L; not refitted with wall-time predictor"
            ),
        )
    workload_checks = []
    for key, entry in plan["workloads"].items():
        model = key.split("-load")[0]
        before = load_workload(original / entry["path"])
        after = models[model].apply_priors(before)
        first = [asdict(a) for a in before]
        second = [asdict(a) for a in after]
        if [{k: v for k, v in r.items() if k != "prior_ns"} for r in first] != [
            {k: v for k, v in r.items() if k != "prior_ns"} for r in second
        ]:
            raise ValueError("nonprior workload field changed")
        payload = encoded(second)
        path = out / entry["path"]
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(gzip.compress(payload, mtime=0))
        old_compressed, old_content = entry["sha256"], entry["content_sha256"]
        entry["sha256"] = digest(path)
        entry["content_sha256"] = hashlib.sha256(payload).hexdigest()
        workload_checks.append(
            dict(
                workload=key,
                agents=len(after),
                workflows=len({a.workflow for a in after}),
                old_compressed_sha256=old_compressed,
                old_content_sha256=old_content,
                new_compressed_sha256=entry["sha256"],
                new_content_sha256=entry["content_sha256"],
                only_agent_prior_changed=True,
                order_arrivals_tokens_limits_dependencies_preserved=True,
            )
        )
    job_checks = []
    for old, job in zip(original_plan["jobs"], plan["jobs"], strict=True):
        job["config"]["slack_guard_ns"] = models[job["model"]].slack_guard_ns
        if {k: v for k, v in old["config"].items() if k != "slack_guard_ns"} != {
            k: v for k, v in job["config"].items() if k != "slack_guard_ns"
        }:
            raise ValueError("non-guard configuration changed")
        job["predictor"] = f"models/{job['model']}.json"
        job["capture_context"] = job["policy"] == "none" and job["failure"] is None
        job_checks.append(
            dict(id=job["id"], only_config_guard_changed=True, failure_and_policy_unchanged=True)
        )
    protocol = dict(
        schema="aegiskv.walltime-primary-protocol.v3",
        frozen_utc=datetime.now(UTC).isoformat(),
        original_campaign=str(original.resolve()),
        original_manifest_sha256=digest(original / "MANIFEST.json"),
        training_campaign=str(training.resolve()),
        training_models_complete_sha256=digest(training / "MODELS_COMPLETE.json"),
        planned_runs=180,
        extra_validation_runs=1,
        max_workers=2,
        intervention=[
            "final train12 hashed-text WalltimePredictor",
            "train12 role wall-time priors",
            "train-only LOOWF guarded-CPM calibration",
        ],
        fixed=(
            "62WF identities/order/releases/full token sequences/output caps; "
            "five failure identities and logical80%; five policies; "
            "L/K/hardware/profile/all config except guard; same core source"
        ),
        execution_order=(
            "six none/F0 jobs first in original relative order, then other174 "
            "in original relative order; isolated DES per condition"
        ),
        capture=(
            "actual Context at submission; observation sidecar outside predictor features; "
            "wrapper delegates once to unchanged serialized model"
        ),
        labels=(
            "healthy same-Agent final completion minus each submission, "
            "paired only after runtime completion, including queue"
        ),
        heldout_use=(
            "descriptive errors only; no fitting, guard recalibration, "
            "hyperparameter choice or condition selection from62WF outcomes"
        ),
        transparency_case="Qwen3-8B-load0.65-none-F0",
        transparency=(
            "compare observed against base runtime at same inputs/model; exact summary "
            "and decompressed event/flow bytes; validation is not an additional sample"
        ),
        statistics=(
            "fixed5 fault identities; paired raw deltas retained including adverse values; "
            "62WF outcomes within a run share queues"
        ),
        evidence_boundary=(
            "modeled FCFS/batch1, unchanged AIC HYBRID durations; regressor is "
            "lightweight hashed text, not validated semantic encoder; healthy "
            "accuracy does not validate failure-conditioned residual duration"
        ),
    )
    write_json(out / "PLAN.json", plan)
    write_json(out / "PRIORS.json", priors)
    write_json(out / "PROTOCOL.json", protocol)
    write_json(
        out / "INPUT_MATCH.json",
        dict(status="PASS", workloads=workload_checks, jobs=job_checks, conditions=180),
    )

    source_hashes, source_origins = {}, {}
    sources = [
        (r, original / "source_snapshot" / r, h, "original sealed primary source")
        for r, h in original_manifest["source_sha256"].items()
    ]
    supplements = read(original / "REPLAY_MANIFEST.json")["supplement_sha256"]
    sources += [
        (r, original / "replay_support" / r, h, "original sealed ancillary import support")
        for r, h in supplements.items()
    ]
    sources += [
        (
            MODULE,
            training / "source_snapshot" / MODULE,
            training_manifest["source_sha256"][MODULE],
            "sealed training implementation",
        )
    ]
    new_files = [
        "python/moonkvsim/aegiskv/evaluation_walltime_campaign.py",
        f"{RELATIVE}/run_walltime_primary.py",
        f"{RELATIVE}/run_frozen_profile_campaign.py",
        f"{RELATIVE}/audit_profile_campaign.py",
        "tests/aegiskv/test_evaluation_walltime_campaign.py",
    ]
    for relative in new_files:
        # An unchanged old audit/helper already in the original seal stays old.
        if relative not in {r for r, _, _, _ in sources}:
            sources.append(
                (
                    relative,
                    ROOT / relative,
                    digest(ROOT / relative),
                    "new intervention runner/test or read-only audit",
                )
            )
    for relative, source, expected, origin in sources:
        if relative in source_hashes:
            raise ValueError("source collision: " + relative)
        copy_file(source, out / "source_snapshot" / relative)
        if digest(out / "source_snapshot" / relative) != expected:
            raise ValueError("source changed during freeze: " + relative)
        source_hashes[relative], source_origins[relative] = expected, origin
    bootstrap = out / "source_snapshot" / "_walltime_bootstrap.py"
    bootstrap.write_text(BOOTSTRAP)
    source_hashes["_walltime_bootstrap.py"] = digest(bootstrap)
    source_origins["_walltime_bootstrap.py"] = "isolated import guard and runner entrypoint"
    controls = ["PLAN.json", "PRIORS.json", "PROTOCOL.json", "INPUT_MATCH.json"]
    manifest = {
        **original_manifest,
        "created_utc": protocol["frozen_utc"],
        "source_sha256": source_hashes,
        "source_origins": source_origins,
        "control_sha256": {r: digest(out / r) for r in controls},
        "predictor_sha256": predictor_hashes,
        "prediction": (
            "trained hashed-text submission-to-Agent-completion predictor, "
            "train12 role priors and LOOWF guard; no62WF tuning"
        ),
        "purpose": "new matched180 predictor intervention; no relabeling of old results",
        "original_manifest_sha256": digest(original / "MANIFEST.json"),
        "training_models_complete_sha256": digest(training / "MODELS_COMPLETE.json"),
    }
    write_json(out / "MANIFEST.json", manifest)
    sealed = ["MANIFEST.json", *controls, *predictor_hashes, *manifest["profile_sha256"]]
    sealed += [
        str(p.relative_to(out))
        for d in ("original", "training")
        for p in (out / d).rglob("*")
        if p.is_file()
    ]
    write_json(
        out / "PROTOCOL_SEAL.json",
        dict(
            sealed_utc=datetime.now(UTC).isoformat(),
            sha256={r: digest(out / r) for r in sorted(sealed)},
        ),
    )
    replay.verify_artifacts(original)
    verify_frozen(out, executing=False)
    subprocess.run(
        [sys.executable, "-B", "-I", str(bootstrap), "--out", str(out), "--verify-only"], check=True
    )
    write_json(
        out / "PREPARE_COMPLETE.json",
        dict(
            status="PASS",
            protocol_seal_sha256=digest(out / "PROTOCOL_SEAL.json"),
            import_preflight_sha256=digest(out / "IMPORT_PREFLIGHT.json"),
            original_core_sources_identical=True,
            source_files=len(source_hashes),
            no_simulation_started=True,
        ),
    )


def launch(out, workers, limit):
    verify_frozen(out, executing=False)
    if not 1 <= workers <= 2:
        raise ValueError("at most two workers")
    bootstrap = out / "source_snapshot" / "_walltime_bootstrap.py"
    command = [
        sys.executable,
        "-B",
        "-I",
        str(bootstrap),
        "--out",
        str(out),
        "--workers",
        str(workers),
    ]
    if limit is not None:
        command += ["--limit", str(limit)]
    with (out / "run.log").open("ab") as log:
        process = subprocess.Popen(
            command,
            cwd=out,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    record = dict(
        pid=process.pid,
        command=command,
        detached=True,
        workers=workers,
        launched_utc=datetime.now(UTC).isoformat(),
        protocol_seal_sha256=digest(out / "PROTOCOL_SEAL.json"),
    )
    target = out / "launches" / f"{process.pid}.json"
    target.parent.mkdir(exist_ok=True)
    write_json(target, record)
    print(json.dumps(record, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "launch", "verify"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--training", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command == "prepare":
        if args.original is None or args.training is None:
            parser.error("prepare requires --original and --training")
        prepare(out, args.original.resolve(), args.training.resolve())
    elif args.command == "launch":
        launch(out, args.workers, args.limit)
    else:
        verify_frozen(out, executing=False)
        print("PASS")


if __name__ == "__main__":
    main()
