#!/usr/bin/env python3
"""Frozen, post-review small-pool O3 diagnostic; never changes the natural input."""
# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import resource
import shutil
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import monotonic, process_time

ROOT = Path(__file__).resolve().parents[5]
RELATIVE_SCRIPT = Path(__file__).resolve().relative_to(ROOT)
sys.path.insert(0, str(ROOT / "python"))
from moonkvsim.aegiskv.current import DESIGN_VERSION  # noqa: E402
from moonkvsim.aegiskv.current.__main__ import (  # noqa: E402
    digest,
    encoded,
    load_workload,
    manifest,
    write_json,
    write_lines,
)
from moonkvsim.aegiskv.current.model import Config, Failure  # noqa: E402
from moonkvsim.aegiskv.current.runtime import CurrentRuntime  # noqa: E402
from moonkvsim.aegiskv.evaluation_campaign import save_workload  # noqa: E402
from moonkvsim.aegiskv.evaluation_profile import (  # noqa: E402
    GridDurationProfile,
    profile_manifest_fields,
)
from moonkvsim.aegiskv.evaluation_quota import FixedQuotaRuntime  # noqa: E402
from moonkvsim.aegiskv.evaluation_walltime_predictor import WalltimePredictor  # noqa: E402

BASE = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924"
DEFAULT = BASE / "quota-pressure-postreview-v1"
VARIANTS = (
    ("none", "none", None),
    ("dram", "dram", None),
    ("fixed32", "static_hbm", 32),
    ("fixed128", "static_hbm", 128),
    ("fixed4096", "static_hbm", 4096),
    ("adaptive", "aegiskv", None),
)
TRANSPARENCY_ID = "margin0-dma0.005-fixed4096-F1"
_CACHE = {}


def read(path):
    return json.loads(path.read_text())


def object_sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def csv_write(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    k: json.dumps(v, separators=(",", ":")) if isinstance(v, (list, dict)) else v
                    for k, v in row.items()
                }
            )


def design():
    original = BASE / "sensitivity-campaign-v2-corrected"
    old_plan, old_manifest = read(original / "PLAN.json"), read(original / "MANIFEST.json")
    for name, expected in old_manifest["control_sha256"].items():
        assert digest(original / name) == expected
    source_workload = original / old_plan["workload"]["path"]
    assert digest(source_workload) == old_plan["workload"]["sha256"]
    agents = load_workload(source_workload)
    assert object_sha([asdict(a) for a in agents]) == old_plan["workload"]["content_sha256"]
    training = BASE / "reviews/walltime-predictor-training-v1"
    model_path = training / "models/Qwen3-8B/model.json"
    model_seal = read(training / "MODELS_COMPLETE.json")
    for name in ("models/Qwen3-8B/model.json", "models/Qwen3-8B/deployment.json"):
        assert digest(training / name) == model_seal["sha256"][name]
    predictor = WalltimePredictor.from_dict(read(model_path))
    deployed = predictor.apply_priors(agents)
    for before, after in zip(agents, deployed, strict=True):
        assert replace(after, prior_ns=before.prior_ns) == before
        assert all(c.output_limit_tokens == 512 for c in after.calls)
    config = Config(
        **{
            **old_plan["protocol"]["baseline_config"],
            "hosts": tuple(old_plan["protocol"]["baseline_config"]["hosts"]),
            "slack_guard_ns": predictor.slack_guard_ns,
        }
    )
    reservations = [
        {
            "agent": a.key,
            "invocation": i,
            "prompt_tokens": len(c.prompt),
            "declared_output_limit_tokens": c.output_limit_tokens,
            "required_bytes_per_rank": config.checkpoint_bytes(
                len(c.prompt) + c.output_limit_tokens
            ),
        }
        for a in deployed
        for i, c in enumerate(a.calls)
    ]
    maximum = max(r["required_bytes_per_rank"] for r in reservations)
    assert maximum == 5_039_327_808 and config.reserve_bytes == 2 * 1024**3
    assert len(deployed) == 52 and len({a.workflow for a in deployed}) == 4
    jobs = []
    for margin in (0, 32, 128):
        for dma in (0.0, 0.005):
            condition = f"margin{margin}-dma{dma:g}"
            c = replace(
                config,
                hbm_bytes_per_rank=maximum + config.reserve_bytes + margin * 1024**2,
                compute_dma_slowdown=dma,
            )
            assert all(
                r["required_bytes_per_rank"] <= c.hbm_bytes_per_rank - c.reserve_bytes
                for r in reservations
            )
            for variant, policy, target in VARIANTS:
                for fault in ("F0", "F1"):
                    identity = f"{condition}-{variant}-{fault}"
                    jobs.append(
                        dict(
                            id=identity,
                            condition=condition,
                            margin_MiB=margin,
                            dma=dma,
                            variant=variant,
                            policy=policy,
                            fixed_quota_bytes=None if target is None else target * 1024**2,
                            config=asdict(c),
                            fault=fault,
                            failure=old_plan["protocol"]["failure"] if fault == "F1" else None,
                            f0_id=f"{condition}-{variant}-F0",
                            detailed_logs=identity == TRANSPARENCY_ID,
                        )
                    )
    assert len(jobs) == len({j["id"] for j in jobs}) == 72
    sources = [
        original / "PLAN.json",
        original / "MANIFEST.json",
        source_workload,
        training / "MODELS_COMPLETE.json",
        model_path,
        training / "models/Qwen3-8B/deployment.json",
    ]
    protocol = dict(
        schema="aegiskv.postreview-quota-pressure.v1",
        status="declared_before_DES",
        declared_utc=datetime.now(UTC).isoformat(),
        planned_runs=72,
        model="Qwen3-8B",
        workflows=old_plan["protocol"]["workflows"],
        agents=52,
        original_workload_content_sha256=old_plan["workload"]["content_sha256"],
        input_changes="Agent.prior_ns only from sealed walltime model; exact tokens/DAG/order/arrival/model/layout/declared caps unchanged",
        predictor="sealed submission-to-Agent-completion walltime regressor and role priors; no service proxy",
        predictor_sha256=digest(model_path),
        slack_guard_ns=predictor.slack_guard_ns,
        depth=config.depth,
        top_k=config.top_k,
        failure=old_plan["protocol"]["failure"],
        failure_descriptor=old_plan["protocol"]["failure_descriptor"],
        repeats_per_workflow=1,
        margins_MiB=[0, 32, 128],
        dma_slowdown=[0.0, 0.005],
        variants=[v[0] for v in VARIANTS],
        reserve_bytes=config.reserve_bytes,
        maximum_declared_foreground_bytes=maximum,
        reservation_arithmetic=reservations,
        pool_formula="max Config.checkpoint_bytes(prompt+512), including selector/count metadata, plus original 2GiB reserve plus margin",
        capacity_interpretation="post-hoc constructed small allocatable pool boundary; not evidence that an 80GB production GPU is capacity-bound",
        fixed_comparator="configured target re-applied each control window and clamped to min(target, live ceiling); foreground reclaim and reader leases use unchanged core",
        observation="pure reads at existing allocation/admission/control/invariant boundaries; no extra DES events, no Tracker.slack or policy estimates from observer",
        admission_semantics="successful _reserve_primary is recorded at actual admission clock before _admit starts service; unsuccessful attempts retained; ordinary latency is not relabeled queue",
        transparency=dict(
            job=TRANSPARENCY_ID,
            base_vs_observed=True,
            compare="exact summary plus decompressed events/flows bytes; require nonempty flow control",
            counted_in_72=False,
        ),
        statistics="one fixed natural-input DAG per run; four dependent Workflow observations; one fixed logical fault; no population CI",
        evidence_limits=[
            "input DAG is public human decomposition, prompts constructed; no live Agent task trace",
            "pool size and DMA interference are constructed sensitivities, no exogenous foreground curve",
            "walltime predictor trained on simulator labels; high guard can suppress selection",
            "ceiling changes alone do not establish pressure, reclaimed capacity or admission benefit",
            "FCFS remains the serving policy; no guaranteed non-interference/CB claim",
            "zero and adverse results retained without tuning/replacement",
        ],
        source_inputs_sha256={str(p.relative_to(ROOT)): digest(p) for p in sources},
    )
    return protocol, jobs, deployed, original / old_plan["profile"], model_path


def prepare(out, *, draft=False):
    out.mkdir(parents=True, exist_ok=True)
    if (out / "MANIFEST.json").exists():
        raise FileExistsError("preserve frozen campaign")
    protocol, jobs, agents, profile_path, model_path = design()
    if draft:
        write_json(out / "PROTOCOL-DRAFT.json", protocol)
        return
    for name in ("profiles", "workloads", "predictor"):
        (out / name).mkdir(exist_ok=True)
    profile = out / "profiles/Qwen3-8B.json"
    shutil.copy2(profile_path, profile)
    model = out / "predictor/model.json"
    shutil.copy2(model_path, model)
    workload = out / "workloads/four-native-workflows.json.gz"
    content = save_workload(workload, agents)
    protocol["status"] = "frozen_before_DES"
    write_json(out / "PROTOCOL.json", protocol)
    plan = dict(
        jobs=jobs,
        protocol=protocol,
        profile=str(profile.relative_to(out)),
        predictor=str(model.relative_to(out)),
        workload=dict(
            path=str(workload.relative_to(out)), sha256=digest(workload), content_sha256=content
        ),
    )
    write_json(out / "PLAN.json", plan)
    source = manifest(out)
    for path in [*sorted((ROOT / "python/moonkvsim").rglob("*.py")), Path(__file__).resolve()]:
        relative = path.relative_to(ROOT)
        saved = out / "source_snapshot" / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
        source["source_sha256"][str(relative)] = digest(saved)
    source.update(
        source_execution="snapshotted Python modules and independent observer runner",
        profile_sha256=digest(profile),
        predictor_sha256=digest(model),
        workload=plan["workload"],
        control_sha256={name: digest(out / name) for name in ("PLAN.json", "PROTOCOL.json")},
        physical_execution=False,
        native_recovery_execution=False,
        **profile_manifest_fields(GridDurationProfile(profile), [j["config"] for j in jobs]),
    )
    write_json(out / "MANIFEST.json", source)
    write_json(
        out / "PREPARED.json",
        dict(
            status="PREPARED_NOT_EXECUTED",
            manifest_sha256=digest(out / "MANIFEST.json"),
            planned_runs=72,
        ),
    )
    print(f"Frozen 72 runs: {out}", flush=True)


def verify(out):
    prepared, source = read(out / "PREPARED.json"), read(out / "MANIFEST.json")
    assert prepared["manifest_sha256"] == digest(out / "MANIFEST.json")
    for relative, expected in source["source_sha256"].items():
        assert digest(out / "source_snapshot" / relative) == expected, relative
    for name, expected in source["control_sha256"].items():
        assert digest(out / name) == expected
    plan = read(out / "PLAN.json")
    assert digest(out / plan["profile"]) == source["profile_sha256"]
    assert digest(out / plan["predictor"]) == source["predictor_sha256"]
    assert digest(out / plan["workload"]["path"]) == plan["workload"]["sha256"]
    assert source["design_version"] == DESIGN_VERSION
    return plan


class ObservationMixin:
    """Read-only evidence; calls each original method once without extra DES events."""

    def __init__(self, *args, **kwargs):
        self.observations = {k: [] for k in ("resources", "controls", "admissions", "reclaims")}
        self._observed_previous = {}
        self._observed_usage, self._observed_integral, self._observed_peak = (
            Counter(),
            Counter(),
            Counter(),
        )
        self._observed_time = 0
        super().__init__(*args, **kwargs)
        self._capture("initial")

    def _resource(self, name):
        ledger = self.ledgers[name]
        row = dict(
            resource=name,
            alive=True,
            primary_bytes=0,
            replica_bytes=0,
            free_bytes=ledger.bytes_in("FREE"),
            quota_bytes=None,
            ceiling_bytes=None,
        )
        if name.startswith("hbm:"):
            _, worker, rank = name.split(":")
            worker, rank = int(worker), int(rank)
            row.update(
                alive=worker in self.alive,
                primary_bytes=sum(
                    n for a, n in ledger.accounts.items() if a.startswith("primary:")
                ),
                replica_bytes=sum(
                    n for a, n in ledger.accounts.items() if a.startswith("replica:")
                ),
                quota_bytes=self.adapters[worker, rank].quota,
            )
            row["ceiling_bytes"] = max(
                0,
                min(
                    self.config.hbm_cap_bytes,
                    self.config.hbm_bytes_per_rank
                    - row["primary_bytes"]
                    - self.config.reserve_bytes,
                ),
            )
        else:
            row["replica_bytes"] = ledger.capacity_bytes - row["free_bytes"]
        return row

    def _capture(self, cause):
        now, usage = self.des.now_ns, Counter()
        for name in sorted(self.ledgers):
            row = self._resource(name)
            if name.startswith("hbm:"):
                usage["primary_hbm"] += row["primary_bytes"]
                usage["replica_hbm"] += row["replica_bytes"]
            else:
                usage["replica_dram"] += row["replica_bytes"]
            if row != self._observed_previous.get(name):
                self.observations["resources"].append(dict(time_ns=now, cause=cause, **row))
                self._observed_previous[name] = row
        for kind in ("primary_hbm", "replica_hbm", "replica_dram"):
            self._observed_integral[kind] += self._observed_usage[kind] * (
                now - self._observed_time
            )
            self._observed_peak[kind] = max(self._observed_peak[kind], usage[kind])
        self._observed_usage, self._observed_time = usage, now

    def _move(self, changes, cause):
        super()._move(changes, cause)
        if any(n for _, _, _, n in changes):
            self._capture("allocation:" + cause)
        if cause in {"HOT_RELEASE", "HOT_ABORT", "PRIMARY_RELEASE", "PEER_HBM_ADOPT_IN_PLACE"}:
            self.observations["reclaims"].append(
                dict(time_ns=self.des.now_ns, cause=cause, changes=changes)
            )

    def _reserve_primary(self, state):
        worker = state.worker
        before = self._resource(f"hbm:{worker}:0")
        failure_retry = state.recovery_row is not None
        readers = sum(cp.readers for cp in self.checkpoints if cp.peer == worker)
        result = super()._reserve_primary(state)
        after = self._resource(f"hbm:{worker}:0")
        self.observations["admissions"].append(
            dict(
                time_ns=self.des.now_ns,
                agent=state.spec.key,
                invocation=state.call,
                worker=worker,
                successful=result,
                is_active_failure_retry=failure_retry,
                submit_ns=state.submitted,
                retry_enqueued_ns=state.recovery_row.get("retry_enqueued_ns")
                if failure_retry
                else None,
                pressure_after=worker in self.pressure,
                existing_checkpoint_readers=readers,
                before=before,
                after=after,
            )
        )
        self._capture("admission_attempt")
        return result

    def _control(self):
        before = {
            (w, r): dict(
                quota=self.adapters[w, r].quota,
                stable=self.adapters[w, r].stable,
                pressure=w in self.pressure,
                deferred=w in self.deferred,
                resource=self._resource(f"hbm:{w}:{r}"),
            )
            for w in sorted(self.alive)
            for r in range(self.config.tp)
        }
        super()._control()
        for (w, r), data in before.items():
            self.observations["controls"].append(
                dict(
                    time_ns=self.des.now_ns,
                    worker=w,
                    rank=r,
                    before=data,
                    after=dict(
                        quota=self.adapters[w, r].quota,
                        stable=self.adapters[w, r].stable,
                        resource=self._resource(f"hbm:{w}:{r}"),
                    ),
                )
            )
        self._capture("control_complete")

    def _invariants(self, des):
        super()._invariants(des)
        self._capture("after_event")


class ObservedCurrent(ObservationMixin, CurrentRuntime):
    pass


class ObservedFixed(ObservationMixin, FixedQuotaRuntime):
    pass


def loaded(out, plan):
    key = str(out)
    if key not in _CACHE:
        agents = load_workload(out / plan["workload"]["path"])
        predictor = WalltimePredictor.from_dict(read(out / plan["predictor"]))
        assert object_sha([asdict(a) for a in agents]) == plan["workload"]["content_sha256"]
        assert predictor.apply_priors(agents) == agents
        _CACHE[key] = agents, predictor, GridDurationProfile(out / plan["profile"])
    return _CACHE[key]


def make_runtime(out, plan, job, *, observed):
    agents, predictor, profile = loaded(out, plan)
    config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
    kwargs = dict(
        policy=job["policy"],
        failure=Failure(**job["failure"]) if job["failure"] else None,
        predictor=predictor,
        duration_profile=profile,
        retain_detailed_logs=job["detailed_logs"],
    )
    if job["fixed_quota_bytes"] is None:
        cls = ObservedCurrent if observed else CurrentRuntime
    else:
        cls = ObservedFixed if observed else FixedQuotaRuntime
        kwargs["fixed_quota_bytes"] = job["fixed_quota_bytes"]
    return cls(config, agents, **kwargs)


def bindings(out, plan, job):
    return dict(
        id=job["id"],
        job_sha256=object_sha(job),
        plan_sha256=digest(out / "PLAN.json"),
        manifest_sha256=digest(out / "MANIFEST.json"),
        profile_sha256=digest(out / plan["profile"]),
        predictor_sha256=digest(out / plan["predictor"]),
        workload_sha256=plan["workload"]["sha256"],
    )


def validate(out, plan, job):
    path = out / "runs" / job["id"]
    marker, result = read(path / "COMPLETE.json"), read(path / "summary.json")
    assert marker["status"] == "COMPLETE"
    for name, value in bindings(out, plan, job).items():
        assert marker[name] == value
    for name, value in marker["artifact_sha256"].items():
        assert digest(path / name) == value, (job["id"], name)
    assert (
        read(path / "config.json") == job["config"]
        and read(path / "failure.json") == job["failure"]
    )
    assert result["config_sha256"] == object_sha(job["config"])
    assert result["workload_sha256"] == plan["workload"]["content_sha256"]
    assert (
        result["policy"] == job["policy"]
        and result["predictor"] == "hashed-text-agent-submission-to-completion-v1"
    )
    assert result["design_version"] == DESIGN_VERSION
    assert (
        result["duration_profile"] == "GridDurationProfile"
        and result["attention_demand_provider"] == "dense"
    )
    assert (
        result["complete"]
        and result["output_tokens_exact"]
        and result["terminal_allocations_zero"]
        and result["oracle_reservation_count"] == 0
    )
    assert len(result["workflows"]) == 4 and len(result["requests"]) == 52
    if job["failure"]:
        assert (
            result["failure"]["agent"],
            result["failure"]["invocation"],
            result["failure"]["logical_tokens"],
        ) == (
            job["failure"]["agent"],
            0,
            plan["protocol"]["failure_descriptor"]["logical_trigger_tokens"],
        )
    else:
        assert result["failure"] is None
    observer = read(path / "OBSERVER.json")
    for kind, value in observer["integral_byte_ns"].items():
        assert result["metrics"].get(kind + "_byte_ns", 0) == value
    return marker, result


def execute(payload):
    out_text, plan, job = payload
    out = Path(out_text)
    path = out / "runs" / job["id"]
    if (path / "COMPLETE.json").exists():
        return validate(out, plan, job)[0]
    path.mkdir(parents=True, exist_ok=False)
    write_json(
        path / "RUN_START.json",
        dict(
            started_utc=datetime.now(UTC).isoformat(), pid=os.getpid(), **bindings(out, plan, job)
        ),
    )
    write_json(path / "config.json", job["config"])
    write_json(path / "failure.json", job["failure"])
    runtime = make_runtime(out, plan, job, observed=True)
    wall, cpu = monotonic(), process_time()
    try:
        result = runtime.run()
    except Exception as error:
        write_json(
            path / "FAILED.json",
            dict(type=type(error).__name__, message=str(error), simulated_ns=runtime.des.now_ns),
        )
        raise
    des_wall, des_cpu = monotonic() - wall, process_time() - cpu
    result.update(
        config_sha256=object_sha(job["config"]), workload_sha256=plan["workload"]["content_sha256"]
    )
    write_json(path / "summary.json", result)
    write_lines(path / "events.jsonl.gz", runtime.events)
    write_lines(path / "flows.jsonl.gz", (asdict(x) for x in runtime.flow_model.intervals))
    for kind, rows in runtime.observations.items():
        write_lines(path / (kind + ".jsonl.gz"), rows)
    write_json(
        path / "OBSERVER.json",
        dict(
            read_only=True,
            extra_DES_events=0,
            integral_byte_ns=dict(runtime._observed_integral),
            peak_bytes_including_intra_event_transactions=dict(runtime._observed_peak),
            records={k: len(v) for k, v in runtime.observations.items()},
        ),
    )
    marker = dict(
        status="COMPLETE",
        **bindings(out, plan, job),
        completed_utc=datetime.now(UTC).isoformat(),
        des_and_observer_wall_seconds=des_wall,
        des_and_observer_process_cpu_seconds=des_cpu,
        worker_lifetime_maxrss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        timing_scope="runtime.run plus read-only observer; excludes construction and output serialization; not controller execution overhead",
        artifact_sha256={p.name: digest(p) for p in sorted(path.iterdir()) if p.is_file()},
    )
    write_json(path / "COMPLETE.json", marker)
    return validate(out, plan, job)[0]


def verify_transparency_artifacts(out, plan):
    """Validate an existing observer control before reuse, including its actual bytes."""
    path = out / "validation/observer-transparency"
    record = read(path / "COMPLETE.json")
    job = next(j for j in plan["jobs"] if j["id"] == TRANSPARENCY_ID)
    assert record["status"] == "PASS" and not record["counts_as_experimental_sample"]
    for name, value in bindings(out, plan, job).items():
        assert record[name] == value, name
    validate(out, plan, job)
    official = out / "runs" / job["id"]
    for name in ("summary.json", "events.jsonl.gz", "flows.jsonl.gz"):
        a, b = (official / name).read_bytes(), (path / name).read_bytes()
        if name.endswith(".gz"):
            a, b = gzip.decompress(a), gzip.decompress(b)
        assert a == b, name
        assert record["checks"][name] == dict(
            equal=True, decompressed_sha256=hashlib.sha256(a).hexdigest(), bytes=len(a)
        )
    assert record["checks"]["flows.jsonl.gz"]["bytes"] > 0
    return record


def transparency(out, plan):
    path = out / "validation/observer-transparency"
    if (path / "COMPLETE.json").exists():
        return verify_transparency_artifacts(out, plan)
    path.mkdir(parents=True, exist_ok=False)
    job = next(j for j in plan["jobs"] if j["id"] == TRANSPARENCY_ID)
    validate(out, plan, job)
    runtime = make_runtime(out, plan, job, observed=False)
    result = runtime.run()
    result.update(
        config_sha256=object_sha(job["config"]), workload_sha256=plan["workload"]["content_sha256"]
    )
    write_json(path / "summary.json", result)
    write_lines(path / "events.jsonl.gz", runtime.events)
    write_lines(path / "flows.jsonl.gz", (asdict(x) for x in runtime.flow_model.intervals))
    official = out / "runs" / job["id"]
    checks = {}
    for name in ("summary.json", "events.jsonl.gz", "flows.jsonl.gz"):
        a, b = (official / name).read_bytes(), (path / name).read_bytes()
        if name.endswith(".gz"):
            a, b = gzip.decompress(a), gzip.decompress(b)
        assert a == b, name
        checks[name] = dict(
            equal=True, decompressed_sha256=hashlib.sha256(a).hexdigest(), bytes=len(a)
        )
    assert checks["flows.jsonl.gz"]["bytes"] > 0
    record = dict(
        status="PASS",
        **bindings(out, plan, job),
        checks=checks,
        counts_as_experimental_sample=False,
        ordinary_admission_times_read_only=True,
    )
    write_json(path / "COMPLETE.json", record)
    return record


def read_rows(path):
    with gzip.open(path, "rt") as stream:
        return [json.loads(line) for line in stream]


def summarize(out, plan):
    results, raw, paired, contrasts = {}, [], [], []
    for job in plan["jobs"]:
        marker, summary = validate(out, plan, job)
        results[job["id"]] = summary
        path = out / "runs" / job["id"]
        controls, admissions, resources, reclaims = [
            read_rows(path / (k + ".jsonl.gz"))
            for k in ("controls", "admissions", "resources", "reclaims")
        ]
        hbm = [r for r in resources if r["resource"].startswith("hbm:") and r["alive"]]
        changes, last = 0, {}
        for r in hbm:
            if r["resource"] in last and r["ceiling_bytes"] != last[r["resource"]]:
                changes += 1
            last[r["resource"]] = r["ceiling_bytes"]
        successful = [r for r in admissions if r["successful"]]
        assert len(successful) == len(summary["requests"]) + len(summary["recoveries"])
        ordinary = [r for r in successful if not r["is_active_failure_retry"]]
        rows = {
            k: job[k]
            for k in ("id", "condition", "margin_MiB", "dma", "variant", "policy", "fault")
        }
        raw.append(
            dict(
                **rows,
                mean_wct_s=mean(w["wct_ns"] for w in summary["workflows"].values()) / 1e9,
                pressure_worker_control_windows=sum(r["before"]["pressure"] for r in controls),
                pressure_admission_attempts=sum(r["pressure_after"] for r in admissions),
                failed_admission_attempts=sum(not r["successful"] for r in admissions),
                ordinary_admissions=len(ordinary),
                ordinary_submit_to_admit_sum_ns=sum(
                    r["time_ns"] - r["submit_ns"] for r in ordinary
                ),
                min_live_ceiling_bytes=min(r["ceiling_bytes"] for r in hbm),
                max_live_ceiling_bytes=max(r["ceiling_bytes"] for r in hbm),
                ceiling_change_records=changes,
                quota_decreases=sum(r["after"]["quota"] < r["before"]["quota"] for r in controls),
                quota_increases=sum(r["after"]["quota"] > r["before"]["quota"] for r in controls),
                hot_reclaim_bytes=sum(
                    n
                    for r in reclaims
                    if r["cause"] in {"HOT_RELEASE", "HOT_ABORT"}
                    for _, _, _, n in r["changes"]
                ),
                **{f"metric_{k}": v for k, v in summary["metrics"].items()},
                **{f"peak_{k}": v for k, v in summary["peak_bytes"].items()},
                des_wall_seconds=marker["des_and_observer_wall_seconds"],
                des_process_cpu_seconds=marker["des_and_observer_process_cpu_seconds"],
                worker_lifetime_maxrss_kib=marker["worker_lifetime_maxrss_kib"],
            )
        )
    for job in plan["jobs"]:
        if job["fault"] != "F1":
            continue
        f0, f1 = results[job["f0_id"]], results[job["id"]]
        for wf, normal in f0["workflows"].items():
            delta = f1["workflows"][wf]["wct_ns"] - normal["wct_ns"]
            paired.append(
                dict(
                    id=job["id"],
                    condition=job["condition"],
                    variant=job["variant"],
                    workflow=wf,
                    is_target=wf == job["failure"]["agent"].split("/")[0],
                    f0_wct_ns=normal["wct_ns"],
                    f1_wct_ns=f1["workflows"][wf]["wct_ns"],
                    delta_wct_ns=delta,
                    failure_time_ns=f1["failure"]["time_ns"],
                    failed_workers=f1["failure"]["workers"],
                    active_victims=sorted(r["agent"] for r in f1["recoveries"]),
                    queued_histories=sorted(r["agent"] for r in f1["history_restores"]),
                )
            )
    lookup = {(r["condition"], r["variant"], r["workflow"]): r for r in paired}
    for r in paired:
        for baseline in ("none", "dram", "fixed32", "fixed128", "fixed4096"):
            if r["variant"] == baseline:
                continue
            base = lookup[r["condition"], baseline, r["workflow"]]
            contrasts.append(
                dict(
                    condition=r["condition"],
                    variant=r["variant"],
                    baseline=baseline,
                    workflow=r["workflow"],
                    is_target=r["is_target"],
                    contrast_ns=r["delta_wct_ns"] - base["delta_wct_ns"],
                    f0_contrast_ns=r["f0_wct_ns"] - base["f0_wct_ns"],
                    f1_contrast_ns=r["f1_wct_ns"] - base["f1_wct_ns"],
                    fault_time_equal=r["failure_time_ns"] == base["failure_time_ns"],
                    failed_workers_equal=r["failed_workers"] == base["failed_workers"],
                    active_victims_equal=r["active_victims"] == base["active_victims"],
                )
            )
    csv_write(out / "raw-runs.csv", raw)
    csv_write(out / "paired-workflows.csv", paired)
    csv_write(out / "policy-contrasts.csv", contrasts)
    comparison = transparency(out, plan)
    verify(out)
    write_json(
        out / "AUDIT.json",
        dict(
            status="PASS",
            planned_runs=72,
            verified_runs=len(raw),
            paired_workflow_rows=len(paired),
            prior_changes_only=True,
            observer_transparency=comparison,
            no_population_CI=True,
            retains_all_negative_or_zero_results=True,
            source_and_result_bindings_verified=True,
            pressure_observed_runs=sum(r["pressure_worker_control_windows"] > 0 for r in raw),
            admission_wait_observed_runs=sum(r["failed_admission_attempts"] > 0 for r in raw),
            output_sha256={
                name: digest(out / name)
                for name in ("raw-runs.csv", "paired-workflows.csv", "policy-contrasts.csv")
            },
        ),
    )
    print(f"AUDIT PASS: {len(raw)} runs, {len(paired)} paired Workflow rows", flush=True)


def run(out, plan, workers, limit):
    if workers not in (1, 2):
        raise ValueError("at most two campaign workers authorized")
    completed, todo = [], []
    for job in plan["jobs"]:
        path = out / "runs" / job["id"]
        if (path / "COMPLETE.json").exists():
            completed.append(validate(out, plan, job)[0])
        elif path.exists():
            raise FileExistsError(f"partial run retained: {path}")
        else:
            todo.append(job)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(execute, (str(out), plan, job))
            for job in (todo if limit is None else todo[:limit])
        ]
        for future in as_completed(futures):
            row = future.result()
            completed.append(row)
            write_json(
                out / "STATUS.json", dict(completed=len(completed), planned=72, latest=row["id"])
            )
            print(
                f"{len(completed)}/72 {row['id']} {row['des_and_observer_wall_seconds']:.2f}s",
                flush=True,
            )
    if len(completed) == 72:
        summarize(out, plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("protocol", "prepare", "run", "summarize", "verify", "transparency")
    )
    parser.add_argument("--out", type=Path, default=DEFAULT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command not in {"protocol", "prepare"}:
        frozen = out / "source_snapshot" / RELATIVE_SCRIPT
        if frozen.resolve() != Path(__file__).resolve():
            if (out / "validation/observer-transparency/COMPLETE.json").exists():
                verify_transparency_artifacts(out, read(out / "PLAN.json"))
            command = [
                sys.executable,
                str(frozen),
                args.command,
                "--out",
                str(out),
                "--workers",
                str(args.workers),
            ]
            if args.limit is not None:
                command += ["--limit", str(args.limit)]
            os.execv(sys.executable, command)
    if args.command in {"protocol", "prepare"}:
        prepare(out, draft=args.command == "protocol")
    else:
        plan = verify(out)
        if args.command == "run":
            run(out, plan, args.workers, args.limit)
        elif args.command == "summarize":
            summarize(out, plan)
        elif args.command == "transparency":
            transparency(out, plan)
        else:
            print("source/input seal verified")


if __name__ == "__main__":
    main()
