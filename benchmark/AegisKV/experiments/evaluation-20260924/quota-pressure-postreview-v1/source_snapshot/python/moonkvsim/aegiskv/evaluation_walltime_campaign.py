"""Execute the preregistered wall-time-predictor intervention on frozen inputs.

This module does not train or tune a model. Context observation delegates to the
same serialized predictor and labels are joined only after healthy completion.
The existing core simulator and Tracker are used without modification.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .current.__main__ import digest, encoded, load_workload, write_json, write_lines
from .current.model import Config, Failure
from .current.runtime import CurrentRuntime
from .evaluation_profile import GridDurationProfile
from .evaluation_walltime_predictor import (
    WalltimePredictor,
    error_metrics,
    error_rows,
    pair_labels,
)

ROOT = Path(__file__).resolve().parents[3]


def read(path):
    return json.loads(Path(path).read_bytes())


def utc():
    return datetime.now(UTC).isoformat()


def object_sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def atomic_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    write_json(temporary, value)
    temporary.replace(path)


class ObservedPredictor:
    """Transparent delegate; identity metadata stays outside online features."""

    def __init__(self, runtime, predictor):
        self.runtime, self.predictor = runtime, predictor
        self.name = predictor.name
        self.training_workflows = predictor.training_workflows

    def __call__(self, context):
        identity = self.runtime._capture_identity
        if identity is None or identity[3] != self.runtime.des.now_ns:
            raise RuntimeError("context observation outside its submission event")
        agent, workflow, invocation, submitted = identity
        self.runtime.captured_contexts.append(
            dict(
                agent=agent,
                workflow=workflow,
                invocation=invocation,
                submitted_ns=submitted,
                raw_context=asdict(context),
            )
        )
        return self.predictor(context)


class ObservedRuntime(CurrentRuntime):
    def __init__(self, config, agents, *, predictor, **kwargs):
        self.captured_contexts = []
        self._capture_identity = None
        super().__init__(config, agents, predictor=ObservedPredictor(self, predictor), **kwargs)

    def _submit(self, state):
        previous = self._capture_identity
        self._capture_identity = (
            state.spec.key,
            state.spec.workflow,
            state.call + 1,
            self.des.now_ns,
        )
        try:
            super()._submit(state)
        finally:
            self._capture_identity = previous


def imported_sources():
    sources = {}
    for name, module in sorted(sys.modules.items()):
        if name == "moonkvsim" or name.startswith("moonkvsim."):
            path = Path(module.__file__).resolve()
            if not path.is_relative_to(ROOT / "python"):
                raise ImportError("MoonKVSim import escaped frozen package: " + name)
            sources[str(path.relative_to(ROOT))] = digest(path)
    return sources


def verify_frozen(out, *, executing=True):
    manifest, plan = read(out / "MANIFEST.json"), read(out / "PLAN.json")
    seal = read(out / "PROTOCOL_SEAL.json")
    for relative, expected in seal["sha256"].items():
        if digest(out / relative) != expected:
            raise ValueError("sealed input changed: " + relative)
    for group in ("control_sha256", "profile_sha256", "predictor_sha256"):
        for relative, expected in manifest[group].items():
            if digest(out / relative) != expected:
                raise ValueError("input hash mismatch: " + relative)
    for relative, expected in manifest["source_sha256"].items():
        if digest(out / "source_snapshot" / relative) != expected:
            raise ValueError("frozen source mismatch: " + relative)
        if executing and digest(ROOT / relative) != expected:
            raise ValueError("execution source differs from snapshot: " + relative)
    if executing:
        for relative, actual in imported_sources().items():
            if manifest["source_sha256"].get(relative) != actual:
                raise ValueError("import not bound to snapshot: " + relative)
    for entry in plan["workloads"].values():
        path = out / entry["path"]
        if digest(path) != entry["sha256"]:
            raise ValueError("workload compressed hash mismatch")
        if (
            hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest()
            != entry["content_sha256"]
        ):
            raise ValueError("workload content hash mismatch")
    return manifest, plan


def run_condition(out, job, *, capture, target=None):
    manifest, plan = read(out / "MANIFEST.json"), read(out / "PLAN.json")
    target = target or out / "runs" / job["id"]
    target.mkdir(parents=True, exist_ok=False)
    workload = plan["workloads"][job["workload"]]
    agents = load_workload(out / workload["path"])
    config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
    predictor = WalltimePredictor.from_dict(read(out / job["predictor"]))
    if predictor.apply_priors(agents) != agents:
        raise ValueError("prepared workload does not contain deployment priors")
    if config.slack_guard_ns != predictor.slack_guard_ns:
        raise ValueError("guard differs from training-only calibration")
    profile_path = out / "profiles" / f"{job['model']}.json"
    if digest(out / job["predictor"]) != manifest["predictor_sha256"][job["predictor"]]:
        raise ValueError("serialized predictor changed")
    profile = GridDurationProfile(profile_path)
    failure = Failure(**job["failure"]) if job["failure"] else None
    write_json(target / "config.json", job["config"])
    write_json(target / "failure.json", job["failure"])
    write_json(
        target / "RUN_START.json",
        dict(
            started_utc=utc(),
            pid=os.getpid(),
            capture_context=capture,
            protocol_seal_sha256=digest(out / "PROTOCOL_SEAL.json"),
            job_sha256=object_sha(job),
            predictor_sha256=digest(out / job["predictor"]),
            imported_source_sha256=imported_sources(),
            root=str(ROOT),
        ),
    )
    runtime_class = ObservedRuntime if capture else CurrentRuntime
    runtime = runtime_class(
        config,
        agents,
        policy=job["policy"],
        failure=failure,
        predictor=predictor,
        duration_profile=profile,
        retain_detailed_logs=job["detailed_logs"],
    )
    started = time.monotonic()
    try:
        summary = runtime.run()
        summary["config_sha256"] = digest(target / "config.json")
        summary["workload_sha256"] = object_sha([asdict(a) for a in agents])
        if summary["workload_sha256"] != workload["content_sha256"]:
            raise ValueError("runtime workload differs from frozen input")
        write_json(target / "summary.json", summary)
        write_lines(target / "events.jsonl.gz", runtime.events)
        write_lines(target / "flows.jsonl.gz", (asdict(r) for r in runtime.flow_model.intervals))
        artifacts = [
            "summary.json",
            "config.json",
            "failure.json",
            "events.jsonl.gz",
            "flows.jsonl.gz",
            "RUN_START.json",
        ]
        if capture:
            labels = pair_labels(
                runtime.captured_contexts,
                summary,
                run_id=job["id"],
                load=workload["offered_load_proxy"],
            )
            errors = error_rows(predictor, labels, heldout=True)
            write_lines(target / "contexts.jsonl.gz", runtime.captured_contexts)
            write_lines(target / "labels.jsonl.gz", labels)
            write_lines(target / "errors.jsonl.gz", errors)
            write_json(target / "HELDOUT_ERROR.json", error_metrics(errors))
            artifacts += [
                "contexts.jsonl.gz",
                "labels.jsonl.gz",
                "errors.jsonl.gz",
                "HELDOUT_ERROR.json",
            ]
        if not all(
            summary.get(k) is True
            for k in ("complete", "terminal_allocations_zero", "output_tokens_exact")
        ):
            raise ValueError("runtime acceptance failed")
        if summary.get("oracle_reservation_count") != 0:
            raise ValueError("oracle reservation in primary run")
        marker = dict(
            id=job["id"],
            complete=True,
            summary_sha256=digest(target / "summary.json"),
            job_sha256=object_sha(job),
            priors_sha256=digest(out / "PRIORS.json"),
            profile_sha256=digest(profile_path),
            workload_sha256=workload["sha256"],
            predictor_sha256=digest(out / job["predictor"]),
            protocol_seal_sha256=digest(out / "PROTOCOL_SEAL.json"),
            capture_context=capture,
            artifacts_sha256={r: digest(target / r) for r in artifacts},
            wall_seconds=time.monotonic() - started,
            completed_utc=utc(),
        )
        atomic_json(target / "COMPLETE.json", marker)
        return marker
    except Exception as error:
        write_json(
            target / "FAILED.json",
            dict(
                error_type=type(error).__name__,
                message=str(error),
                time_ns=runtime.des.now_ns,
                wall_seconds=time.monotonic() - started,
            ),
        )
        raise


def verify_completed(out, job, *, target=None, capture=None):
    target = target or out / "runs" / job["id"]
    row, summary = read(target / "COMPLETE.json"), read(target / "summary.json")
    workload = read(out / "PLAN.json")["workloads"][job["workload"]]
    capture = job["capture_context"] if capture is None else capture
    required = dict(
        id=job["id"],
        complete=True,
        summary_sha256=digest(target / "summary.json"),
        job_sha256=object_sha(job),
        priors_sha256=digest(out / "PRIORS.json"),
        profile_sha256=digest(out / "profiles" / f"{job['model']}.json"),
        workload_sha256=workload["sha256"],
        predictor_sha256=digest(out / job["predictor"]),
        protocol_seal_sha256=digest(out / "PROTOCOL_SEAL.json"),
        capture_context=capture,
    )
    if any(row.get(k) != v for k, v in required.items()):
        raise ValueError("completion marker identity mismatch")
    for relative, expected in row["artifacts_sha256"].items():
        if digest(target / relative) != expected:
            raise ValueError("completed artifact changed: " + relative)
    if (
        read(target / "config.json") != job["config"]
        or read(target / "failure.json") != job["failure"]
    ):
        raise ValueError("completed config/failure mismatch")
    expected_predictor = WalltimePredictor.from_dict(read(out / job["predictor"]))
    if (
        summary["config_sha256"],
        summary["workload_sha256"],
        summary["policy"],
        summary["predictor"],
    ) != (
        object_sha(job["config"]),
        workload["content_sha256"],
        job["policy"],
        expected_predictor.name,
    ):
        raise ValueError("completed summary input identity mismatch")
    if (
        not all(
            summary.get(k) is True
            for k in ("complete", "terminal_allocations_zero", "output_tokens_exact")
        )
        or summary["oracle_reservation_count"] != 0
    ):
        raise ValueError("completed run failed runtime acceptance")
    return row


def execute_job(arguments):
    out, job = arguments
    return run_condition(Path(out), job, capture=job["capture_context"])


def transparency(out, plan):
    protocol = read(out / "PROTOCOL.json")
    job = next(j for j in plan["jobs"] if j["id"] == protocol["transparency_case"])
    observed = out / "runs" / job["id"]
    if not (observed / "COMPLETE.json").exists():
        return
    target = out / "validation" / "base-runtime"
    if (target / "COMPLETE.json").exists():
        verify_completed(out, job, target=target, capture=False)
    else:
        run_condition(out, job, capture=False, target=target)
    rows = {}
    for name in ("summary.json", "events.jsonl.gz", "flows.jsonl.gz"):
        raw = [p.read_bytes() for p in (observed / name, target / name)]
        payloads = [gzip.decompress(p) for p in raw] if name.endswith(".gz") else raw
        if payloads[0] != payloads[1]:
            raise ValueError("Context observer changed a runtime artifact: " + name)
        rows[name] = dict(
            byte_equal=True,
            compared_decompressed=name.endswith(".gz"),
            content_sha256=hashlib.sha256(payloads[0]).hexdigest(),
            bytes=len(payloads[0]),
        )
    atomic_json(
        out / "OBSERVATION_TRANSPARENCY.json",
        dict(
            status="PASS",
            run=job["id"],
            artifacts=rows,
            scope="one prespecified full-workload none/F0 condition; not all arbitrary predictors",
            extra_experimental_samples=0,
            base_complete_sha256=digest(target / "COMPLETE.json"),
            observed_complete_sha256=digest(observed / "COMPLETE.json"),
        ),
    )


def heldout_report(out, plan):
    jobs = [j for j in plan["jobs"] if j["capture_context"]]
    if any(not (out / "runs" / j["id"] / "COMPLETE.json").exists() for j in jobs):
        return
    groups, inputs = {}, {}
    for job in jobs:
        verify_completed(out, job)
        path = out / "runs" / job["id"] / "errors.jsonl.gz"
        with gzip.open(path, "rt") as stream:
            groups.setdefault(job["model"], []).extend(json.loads(line) for line in stream)
        inputs[str(path.relative_to(out))] = digest(path)
    atomic_json(
        out / "HELDOUT_ERROR.json",
        dict(
            schema="aegiskv.walltime-heldout-primary.v1",
            models={m: error_metrics(rs) for m, rs in groups.items()},
            input_sha256=inputs,
            predictor_sha256=read(out / "MANIFEST.json")["predictor_sha256"],
            evaluation_workflows=plan["evaluation_workflows"],
            training_workflows=plan["training_workflows"],
            fitting_or_tuning_performed=False,
            sampling_unit=(
                "62 held-out workflows; same workflow repeated across 3 loads per model; "
                "rows share queues"
            ),
            label=(
                "Agent final finish minus invocation submission, "
                "healthy none-policy trajectory including queue"
            ),
            limitations=[
                "modeled wall time, not physical execution",
                "lightweight hashed-text regressor, not validated semantic encoder",
                "no load/queue input feature",
                (
                    "healthy-none labels do not establish accuracy after failures "
                    "or under other policies"
                ),
            ],
        ),
    )


def run(out, workers=2, limit=None):
    if not 1 <= workers <= 2:
        raise ValueError("protocol allows at most two workers")
    _, plan = verify_frozen(out)
    jobs, completed, todo = plan["jobs"], [], []
    for job in jobs:
        path = out / "runs" / job["id"]
        if (path / "COMPLETE.json").exists():
            completed.append(verify_completed(out, job))
        elif path.exists():
            raise ValueError("partial run retained; explicit archival is required: " + str(path))
        else:
            todo.append(job)
    order = {j["id"]: i for i, j in enumerate(jobs)}
    # All six none/F0 conditions are always first, independent of their outcomes.
    todo.sort(key=lambda j: (not j["capture_context"], order[j["id"]]))
    if limit is not None:
        todo = todo[:limit]

    def progress():
        completed.sort(key=lambda r: order[r["id"]])
        atomic_json(out / "RUNS.json", completed)
        atomic_json(
            out / "STATUS.json",
            dict(
                complete=len(completed) == len(jobs),
                completed_runs=len(completed),
                planned_runs=len(jobs),
                updated_utc=utc(),
                workers=workers,
            ),
        )

    progress()
    # A separate pool per phase keeps validation within the two-worker ceiling.
    for capture_phase in (True, False):
        selected = [j for j in todo if j["capture_context"] == capture_phase]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(execute_job, (str(out), j)): j for j in selected}
            for future in as_completed(futures):
                result = future.result()
                completed.append(result)
                progress()
                print(
                    f"completed {len(completed)}/{len(jobs)} {result['id']} "
                    f"{result['wall_seconds']:.2f}s",
                    flush=True,
                )
        if capture_phase:
            transparency(out, plan)
            heldout_report(out, plan)
    verify_frozen(out)
    progress()
