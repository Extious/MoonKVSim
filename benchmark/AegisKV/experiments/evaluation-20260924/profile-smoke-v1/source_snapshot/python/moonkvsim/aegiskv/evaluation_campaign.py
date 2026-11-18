"""Trace-grounded, paired current-design experiment preparation and execution.

Use ``prepare`` to freeze a matrix, then ``run`` to execute it. A completed run
is reused only after its config, summary and frozen-source hashes verify. The
primary inputs are constructed FanOutQA replays, not observed serving traces.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, replace
from math import ceil
from pathlib import Path
from statistics import mean, median

from .current.__main__ import digest, encoded, load_workload, manifest, run_one, write_json
from .current.model import Agent, Config, Failure
from .current.tracker import Context
from .evaluation_profile import GridDurationProfile
from .evaluation_workload import load_fanoutqa_agents

ROOT = Path(__file__).resolve().parents[3]
INPUTS = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/inputs"
POLICIES = ("none", "all_dram", "dram", "static_hbm", "aegiskv")


def model_config(profile: GridDurationProfile, dp: int = 8) -> Config:
    data, geometry = profile.data, profile.data["config"]
    memory = data["rows"][0]["memory"]
    fixed = ceil((memory["weights"] + memory["nccl"] + 4) * 1024**3)
    return Config(
        hosts=tuple(range(dp)),
        tp=data["tp"],
        layers=geometry["num_hidden_layers"],
        kv_bytes_per_token_per_layer_rank=4
        * geometry["num_key_value_heads"]
        * geometry["head_dim"]
        // data["tp"],
        hbm_bytes_per_rank=80 * 1024**3 - fixed,
        dram_bytes_per_host=256 * 1024**3,
        hbm_cap_bytes=4 * 1024**3,
        initial_quota_bytes=128 * 1024**2,
        reserve_bytes=2 * 1024**3,
        additive_bytes=64 * 1024**2,
        h2d_bytes_per_second=32e9,
        d2h_bytes_per_second=32e9,
        network_bytes_per_second=25e9,
        dram_bytes_per_second=100e9,
        depth=4,
        top_k=16,
        tolerance_ns=10_000_000,
        max_time_ns=7200 * 10**9,
        prediction_ttl_ns=120 * 10**9,
        decode_batch_tokens=8,
    )


@dataclass
class CausalLengthPredictor:
    """Known current prompt cost plus train-only role output-length prior.

    This controlled prediction proxy estimates modeled service work. It is not
    a learned predictor of real multi-call Agent wall time or future queues.
    """

    profile: GridDurationProfile
    config: Config
    output_by_role: dict[str, int]
    training_workflows: tuple[str, ...]
    multiplier: float = 1.0
    name: str = "causal-current-prompt-plus-training-role-output"

    def __call__(self, context: Context) -> int:
        prompt = context.prompt_tokens
        output = self.output_by_role.get(context.role, self.output_by_role["__all__"])
        end = min(prompt + output, self.profile.contexts[-1])
        prefill = self.profile.duration(
            0, prompt, "prefill", self.config.prefill_chunk_tokens, self.config.checkpoint_tokens
        )
        decode = self.profile.duration(
            prompt, end, "decode", self.config.prefill_chunk_tokens, self.config.checkpoint_tokens
        )
        return max(1, ceil((prefill + decode) * self.multiplier))


def fit_priors(agents: tuple[Agent, ...], profile: GridDurationProfile, config: Config) -> dict:
    output, durations, workflow_work = defaultdict(list), defaultdict(list), defaultdict(int)
    for agent in agents:
        if len(agent.calls) != 1:
            raise ValueError("FanOutQA prediction protocol requires one call per source task")
        inv = agent.calls[0]
        cost = profile(config, inv, 0, len(inv.prompt), "prefill")
        cost += profile(config, inv, len(inv.prompt), len(inv.tokens), "decode")
        for role in (agent.role, "__all__"):
            output[role].append(len(inv.output))
            durations[role].append(cost)
        workflow_work[agent.workflow] += cost
    return dict(
        training_workflows=sorted(workflow_work),
        training_tasks=len(agents),
        role_output_tokens={k: max(1, round(median(v))) for k, v in output.items()},
        role_prior_ns={k: max(1, round(median(v))) for k, v in durations.items()},
        mean_training_workflow_service_ns=mean(workflow_work.values()),
        evidence=(
            "offline modeled service labels on disjoint training workflows; "
            "not observed Agent wall time"
        ),
    )


def with_priors_and_arrivals(agents, priors, interval_ns):
    order = list(dict.fromkeys(a.workflow for a in agents))
    positions = {workflow: i for i, workflow in enumerate(order)}
    return tuple(
        replace(
            a,
            prior_ns=priors["role_prior_ns"].get(a.role, priors["role_prior_ns"]["__all__"]),
            release_ns=positions[a.workflow] * interval_ns,
        )
        for a in agents
    )


def save_workload(path: Path, agents) -> str:
    payload = encoded([asdict(a) for a in agents])
    with gzip.open(path, "wb") as stream:
        stream.write(payload)
    return hashlib.sha256(payload).hexdigest()


def fault_bank(agents, number=5, progress=0.8):
    """ID/source-order stratification fixed without looking at policy outcomes.

    Take the middle source task in workflows at five equal source-order
    positions. Reusing the same bank across models/load/policies isolates the
    interventions; the bank is not a random sample of hardware failure times.
    """
    workflows = list(dict.fromkeys(a.workflow for a in agents))
    if len(workflows) < number:
        raise ValueError("too few workflows for the prespecified fault bank")
    result = []
    for i in range(number):
        workflow = workflows[(2 * i + 1) * len(workflows) // (2 * number)]
        tasks = [a for a in agents if a.workflow == workflow]
        result.append(Failure(tasks[len(tasks) // 2].key, invocation=0, progress=progress))
    return result


def prepare(out: Path, *, smoke: bool = False) -> None:
    out.mkdir(parents=True, exist_ok=False)
    (out / "workloads").mkdir()
    (out / "profiles").mkdir()
    split_path = INPUTS / "fanoutqa-workflow-split.json"
    split = json.loads(split_path.read_text())
    source = INPUTS / "fanoutqa-bundle.json"
    if digest(source) != split["source_bundle_sha256"]:
        raise ValueError("workflow split refers to another input bundle")
    native = load_fanoutqa_agents(
        source,
        workflow_ids=split["native_train_ids"] + split["native_eval_ids"],
        max_context_tokens=40960,
    )
    # Restore original source workflow order after train/eval selection.
    bundle = json.loads(source.read_text())
    order = {w: i for i, w in enumerate(bundle["workflow_ids"])}
    native = tuple(sorted(native, key=lambda a: order[a.workflow]))
    jobs, workloads, priors_by_model = [], {}, {}
    models = ("Qwen3-8B",) if smoke else ("Qwen3-8B", "Qwen3-32B")
    for model in models:
        profile_path = INPUTS / "duration-profiles" / f"{model}.json"
        saved_profile = out / "profiles" / profile_path.name
        saved_profile.write_bytes(profile_path.read_bytes())
        profile = GridDurationProfile(saved_profile)
        config = model_config(profile, dp=4 if smoke else 8)
        transformed = tuple(
            replace(a, calls=tuple(replace(c, model=profile.data["model"]) for c in a.calls))
            for a in native
        )
        train = tuple(a for a in transformed if a.workflow in split["native_train_ids"])
        evaluation = tuple(a for a in transformed if a.workflow in split["native_eval_ids"])
        if smoke:
            chosen = list(dict.fromkeys(a.workflow for a in evaluation))[:2]
            evaluation = tuple(a for a in evaluation if a.workflow in chosen)
        priors = fit_priors(train, profile, config)
        priors_by_model[model] = priors
        for rho in (0.65,) if smoke else (0.3, 0.65, 0.9):
            interval = round(priors["mean_training_workflow_service_ns"] / len(config.hosts) / rho)
            agents = with_priors_and_arrivals(evaluation, priors, interval)
            key = f"{model}-load{rho:g}"
            relative = f"workloads/{key}.json.gz"
            content_hash = save_workload(out / relative, agents)
            workloads[key] = dict(
                path=relative,
                sha256=digest(out / relative),
                content_sha256=content_hash,
                workflows=len({a.workflow for a in agents}),
                agents=len(agents),
                arrival_interval_ns=interval,
                offered_load_proxy=rho,
            )
            failures = fault_bank(agents, number=1 if smoke else 5)
            for policy in ("none", "dram", "aegiskv") if smoke else POLICIES:
                f0_id = f"{key}-{policy}-F0"
                for fault_index, failure in [(-1, None), *enumerate(failures)]:
                    identity = f0_id if failure is None else f"{key}-{policy}-F1-{fault_index}"
                    jobs.append(
                        dict(
                            id=identity,
                            dataset="fanoutqa-native",
                            model=model,
                            case="core",
                            workload=key,
                            config=asdict(config),
                            policy=policy,
                            failure=asdict(failure) if failure else None,
                            fault_index=fault_index,
                            f0_id=f0_id,
                            detailed_logs=smoke and policy == "aegiskv",
                        )
                    )
    frozen = manifest(out)
    frozen.update(
        evidence_class="modeled_profile_informed_not_calibrated",
        workload_class="public_human_dag_constructed_prompt_replay",
        foreground_model="FCFS one invocation per DP; no continuous batching",
        timing="pinned AIConfigurator HYBRID bounded shape-grid interpolation",
        physical_execution=False,
        paper_ready=False,
        purpose="smoke" if smoke else "formal_core",
        input_sha256={str(p.relative_to(ROOT)): digest(p) for p in (source, split_path)},
        profile_sha256={
            str(p.relative_to(out)): digest(p) for p in (out / "profiles").glob("*.json")
        },
    )
    write_json(out / "MANIFEST.json", frozen)
    write_json(out / "PRIORS.json", priors_by_model)
    write_json(
        out / "PLAN.json",
        dict(
            jobs=jobs,
            workloads=workloads,
            model_count=len(models),
            planned_runs=len(jobs),
            sampling_unit="prespecified failure identity; workflows within a run are dependent",
            training_workflows=split["native_train_ids"],
            evaluation_workflows=split["native_eval_ids"],
            repetitions="no deterministic reruns counted as additional samples",
            failure_progress="80% total logical tokens, usually prefill for this corpus",
            load="training-work-derived nominal utilization; actual utilization may differ",
        ),
    )
    print(f"Prepared {len(jobs)} {'smoke' if smoke else 'formal'} runs at {out}", flush=True)


_WORKLOAD_CACHE = {}


def execute_job(arguments):
    out_string, job = arguments
    out = Path(out_string)
    target = out / "runs" / job["id"]
    plan = json.loads((out / "PLAN.json").read_text())
    workload = plan["workloads"][job["workload"]]
    path = out / workload["path"]
    if str(path) not in _WORKLOAD_CACHE:
        if digest(path) != workload["sha256"]:
            raise ValueError("workload artifact drifted")
        _WORKLOAD_CACHE[str(path)] = load_workload(path)
    agents = _WORKLOAD_CACHE[str(path)]
    config = Config(**{**job["config"], "hosts": tuple(job["config"]["hosts"])})
    profile = GridDurationProfile(out / "profiles" / f"{job['model']}.json")
    priors = json.loads((out / "PRIORS.json").read_text())[job["model"]]
    predictor = CausalLengthPredictor(
        profile, config, priors["role_output_tokens"], tuple(priors["training_workflows"])
    )
    failure = Failure(**job["failure"]) if job["failure"] else None
    result = run_one(
        target,
        config,
        agents,
        job["policy"],
        failure,
        predictor=predictor,
        duration_profile=profile,
        retain_detailed_logs=job["detailed_logs"],
    )
    if result["workload_sha256"] != workload["content_sha256"]:
        raise RuntimeError("runtime workload identity differs from frozen plan")
    row = dict(
        id=job["id"], complete=result["complete"], summary_sha256=digest(target / "summary.json")
    )
    write_json(target / "COMPLETE.json", row)
    return row


def run(out: Path, workers: int, limit: int | None = None) -> None:
    frozen = json.loads((out / "MANIFEST.json").read_text())
    for relative, expected in frozen["source_sha256"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError(f"source drift; freeze a new campaign before running: {relative}")
    for relative, expected in frozen["profile_sha256"].items():
        if digest(out / relative) != expected:
            raise ValueError("duration-profile drift")
    jobs = json.loads((out / "PLAN.json").read_text())["jobs"]
    todo, completed = [], []
    for job in jobs:
        target = out / "runs" / job["id"]
        marker = target / "COMPLETE.json"
        if marker.exists():
            row = json.loads(marker.read_text())
            if digest(target / "summary.json") != row["summary_sha256"]:
                raise ValueError("completed summary hash mismatch")
            completed.append(row)
        else:
            if target.exists():
                raise ValueError(
                    "partial/failed run retained; inspect and supersede rather than overwrite: "
                    f"{target}"
                )
            todo.append(job)
    if limit is not None:
        todo = todo[:limit]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(execute_job, [(str(out), j) for j in todo]):
            completed.append(result)
            write_json(out / "RUNS.json", completed)
            print(f"completed {len(completed)}/{len(jobs)} {result['id']}", flush=True)
    write_json(
        out / "STATUS.json",
        dict(
            complete=len(completed) == len(jobs),
            completed_runs=len(completed),
            planned_runs=len(jobs),
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.out, smoke=args.smoke)
    else:
        run(args.out, args.workers, args.limit)


if __name__ == "__main__":
    main()
