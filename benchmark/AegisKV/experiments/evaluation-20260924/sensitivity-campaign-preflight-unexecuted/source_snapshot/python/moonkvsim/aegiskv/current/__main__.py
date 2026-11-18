"""Reproducible CLI and paired mechanism campaign for the current manuscript."""
# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import platform
import shutil
import subprocess
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from . import DESIGN_VERSION
from .model import Agent, Config, Failure, Invocation
from .predictor import ContextRegressor
from .runtime import CurrentRuntime
from .tracker import prior_predictor
from .workload import mechanism_workload

ROOT = Path(__file__).resolve().parents[4]


def encoded(value) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2) + "\n"
    ).encode()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_bytes(encoded(value))


def write_lines(path: Path, rows) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
            )


def load_workload(path: Path) -> tuple[Agent, ...]:
    payload = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    rows = json.loads(payload)
    result = []
    for raw in rows:
        row = dict(raw)
        row["predecessors"] = tuple(row["predecessors"])
        row["calls"] = tuple(
            Invocation(**{**call, "prompt": tuple(call["prompt"]), "output": tuple(call["output"])})
            for call in row["calls"]
        )
        result.append(Agent(**row))
    return tuple(result)


def manifest(out: Path) -> dict:
    sources = sorted((ROOT / "python/moonkvsim/aegiskv/current").glob("*.py"))
    sources += sorted((ROOT / "python/moonkvsim/simulation").glob("*.py"))
    sources += sorted((ROOT / "python/moonkvsim/aegiskv").glob("evaluation_*.py"))
    sources += sorted((ROOT / "tests/aegiskv").glob("test_current*.py"))
    sources += sorted((ROOT / "tests/aegiskv").glob("test_evaluation*.py"))
    sources += [
        ROOT / "python/moonkvsim/common/hash.py",
        ROOT / "benchmark/AegisKV/paper/system_design.tex",
        ROOT / "benchmark/AegisKV/AGENTS.md",
    ]
    hashes = {}
    for source in sources:
        relative = source.relative_to(ROOT)
        destination = out / "source_snapshot" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        hashes[str(relative)] = digest(destination)
    result = {
        "design_version": DESIGN_VERSION,
        "created_utc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "git_status_sha256": hashlib.sha256(
            subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=ROOT)
        ).hexdigest(),
        "source_sha256": hashes,
        "evidence_class": "modeled_uncalibrated",
        "workload_class": "constructed_fixed_agent_dag",
        "attention": "dense or explicitly constructed sparse selector, not native model traces",
        "foreground_model": (
            "FCFS per DP, TP barrier, token-batched forwards; no continuous batching"
        ),
        "foreground_dma_compute_interference": (
            "omitted; healthy zero slowdown is not measured overhead"
        ),
        "timing": "configured linear compute and shared weighted max-min fair byte flows",
        "prediction": (
            "causal prior baseline by default; optional independently trained context regressor"
        ),
        "checkpoint": "256-token commit units; asynchronous copy lag is NOT capped at 256",
        "failure": "logical token progress; resolved trigger in each run/failure.json",
        "ack_model": "modeled TP shard barriers; cancellation fencing is synchronous in the DES",
        "repetitions": "one original DAG per workload; no repeated-round amplification",
        "physical_execution": False,
        "paper_ready": False,
    }
    write_json(out / "MANIFEST.json", result)
    return result


def run_one(
    out: Path,
    config: Config,
    agents: tuple[Agent, ...],
    policy: str,
    failure: Failure | None,
    *,
    predictor=prior_predictor,
    journal: bool = False,
    duration_profile=None,
    demand_provider=None,
    retain_detailed_logs: bool = True,
) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "config.json", asdict(config))
    write_json(out / "failure.json", asdict(failure) if failure else None)
    runtime = CurrentRuntime(
        config,
        agents,
        policy=policy,
        failure=failure,
        predictor=predictor,
        duration_profile=duration_profile,
        demand_provider=demand_provider,
        retain_detailed_logs=retain_detailed_logs,
    )
    try:
        result = runtime.run()
    except Exception as error:
        write_json(
            out / "FAILED.json",
            {
                "complete": False,
                "error_type": type(error).__name__,
                "message": str(error),
                "time_ns": runtime.des.now_ns,
            },
        )
        write_lines(out / "events.jsonl.gz", runtime.events)
        raise
    result["workload_sha256"] = hashlib.sha256(encoded([asdict(a) for a in agents])).hexdigest()
    result["config_sha256"] = digest(out / "config.json")
    write_json(out / "summary.json", result)
    write_lines(out / "events.jsonl.gz", runtime.events)
    write_lines(out / "flows.jsonl.gz", (asdict(row) for row in runtime.flow_model.intervals))
    if journal:
        with gzip.open(out / "journal.jsonl.gz", "wb") as stream:
            stream.write(runtime.des.journal.to_jsonl_bytes())
    return result


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (pos - lower)


def campaign(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=False)
    source_manifest = manifest(out)
    base = Config()
    # Controls share workload, compute/resource parameters, routing, checkpoint
    # interval and the same logical fault trigger. Sparse selection is a fixture.
    cases = [
        ("dense", base, (7, 19, 41), "worker"),
        ("sparse_fixture", replace(base, attention="synthetic_sparse"), (7, 19, 41), "worker"),
        ("slow_copy", replace(base, network_bytes_per_second=100e6), (7,), "worker"),
        ("dram_pressure", replace(base, dram_bytes_per_host=512 * 1024**2), (7,), "worker"),
        (
            "hbm_growth",
            replace(
                base, initial_quota_bytes=0, additive_bytes=4 * 1024**2, hbm_cap_bytes=32 * 1024**2
            ),
            (7,),
            "worker",
        ),
        (
            "foreground_pressure",
            replace(base, hbm_bytes_per_rank=576 * 1024**2, reserve_bytes=32 * 1024**2),
            (7,),
            "worker",
        ),
        ("shared_host_failure", replace(base, hosts=(0, 0, 1, 1)), (7,), "host"),
        ("expired_prediction", replace(base, prediction_ttl_ns=1_000_000), (7,), "worker"),
        ("lambda_1s", replace(base, tolerance_ns=1_000_000_000), (7,), "worker"),
    ]
    runs = []
    paired = []
    checks = []
    (out / "workloads").mkdir()
    for seed in (7, 19, 41):
        with gzip.open(out / "workloads" / f"seed-{seed}.json.gz", "wb") as stream:
            stream.write(encoded([asdict(a) for a in mechanism_workload(seed)]))
    for case, config, seeds, scope in cases:
        for seed in seeds:
            agents = mechanism_workload(seed)
            failures = {}
            for policy in ("none", "dram", "aegiskv"):
                results = []
                for fault in (False, True):
                    identity = f"{case}-{seed}-{policy}-F{int(fault)}"
                    result = run_one(
                        out / "runs" / identity,
                        config,
                        agents,
                        policy,
                        Failure("wf00/slow", scope=scope) if fault else None,
                        journal=case in {"dense", "sparse_fixture"}
                        and seed == 7
                        and policy == "aegiskv"
                        and fault,
                    )
                    runs.append(
                        {
                            "id": identity,
                            "case": case,
                            "seed": seed,
                            "policy": policy,
                            "fault": fault,
                            "summary_sha256": digest(out / "runs" / identity / "summary.json"),
                        }
                    )
                    results.append(result)
                    print(f"completed {identity}", flush=True)
                f0, f1 = results
                failures[policy] = f1["failure"]
                checks.append(
                    {
                        "pair": f"{case}-{seed}-{policy}",
                        "same_workload": f0["workload_sha256"] == f1["workload_sha256"],
                        "same_config": f0["config_sha256"] == f1["config_sha256"],
                        "same_workflows": f0["workflows"].keys() == f1["workflows"].keys(),
                        "complete": f0["complete"] and f1["complete"],
                        "no_leaks": f0["terminal_allocations_zero"]
                        and f1["terminal_allocations_zero"],
                        "outputs_exact": f0["output_tokens_exact"] and f1["output_tokens_exact"],
                    }
                )
                for workflow in f0["workflows"]:
                    normal = f0["workflows"][workflow]["wct_ns"] / 1e9
                    failed = f1["workflows"][workflow]["wct_ns"] / 1e9
                    paired.append(
                        {
                            "case": case,
                            "seed": seed,
                            "policy": policy,
                            "workflow": workflow,
                            "f0_wct_s": normal,
                            "f1_wct_s": failed,
                            "delta_wct_s": failed - normal,
                            "slowdown": failed / normal,
                            "fault_logical_tokens": f1["failure"]["logical_tokens"],
                        }
                    )
            positions = {f["logical_tokens"] for f in failures.values()}
            checks.append(
                {"pair": f"{case}-{seed}-cross-policy", "same_fault_progress": len(positions) == 1}
            )
    valid = all(all(v for k, v in row.items() if k != "pair") for row in checks)
    if not valid:
        raise RuntimeError("campaign pair acceptance failed")
    with (out / "paired-workflows.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(paired[0]))
        writer.writeheader()
        writer.writerows(paired)
    write_json(out / "RUNS.json", runs)
    write_json(out / "ACCEPTANCE.json", {"pass": valid, "runs": len(runs), "checks": checks})
    grouped = []
    for case, _, _, _ in cases:
        for policy in ("none", "dram", "aegiskv"):
            rows = [r for r in paired if r["case"] == case and r["policy"] == policy]
            grouped.append(
                {
                    "case": case,
                    "policy": policy,
                    "workflow_samples": len(rows),
                    "mean_f0_wct_s": mean(r["f0_wct_s"] for r in rows),
                    "mean_f1_wct_s": mean(r["f1_wct_s"] for r in rows),
                    "mean_delta_wct_s": mean(r["delta_wct_s"] for r in rows),
                    "p95_f1_wct_s": percentile([r["f1_wct_s"] for r in rows], 0.95),
                    "p99_f1_wct_s": percentile([r["f1_wct_s"] for r in rows], 0.99),
                }
            )
    write_json(out / "STATISTICS.json", grouped)
    lines = [
        "# AegisKV 当前设计：首轮机制模拟",
        "",
        f"设计版本：`{DESIGN_VERSION}`。{len(runs)} 个运行全部结束，配对验收通过。",
        "",
        "这是 CPU 上执行的未校准离散事件模拟。工作负载为明确构造的固定 Agent DAG，",
        "每个工作负载只执行一次；稀疏场景使用构造 selector，不是原生模型测量。",
        "默认预测器使用提交时可见的时长先验；可训练上下文回归器接口已提供，",
        "本次未把真实任务上的训练精度作为已验证事实。",
        "",
        "各策略具有同配置的 F0（无故障）与 F1（故障）运行。故障固定到 wf00/slow",
        "第二次调用、总 token 逻辑进度 80%；注入时刻随各自运行变化。",
        "下表均值以工作流为单位；完整同 ID 配对、p95/p99 和逐次恢复分解保留在数据中。",
        "",
        "| 场景 | 策略 | F0 平均 WCT (s) | F1 平均 WCT (s) | 平均增量 (s) |",
        "|---|---|---:|---:|---:|",
    ]
    for r in grouped:
        lines.append(
            f"| {r['case']} | {r['policy']} | {r['mean_f0_wct_s']:.4f} | "
            f"{r['mean_f1_wct_s']:.4f} | {r['mean_delta_wct_s']:+.4f} |"
        )
    lines.extend(
        [
            "",
            "容量账本包含执行预留、已提交副本及复制中的目标分配。Peer DRAM 按物理主机共享，",
            "Peer HBM 按 TP rank 计费；恢复时原地接管 HBM，避免重复计费。所有运行结束时",
            "占用归零，输出 token 无重复或遗漏。低带宽下的检查点滞后及任何负面 WCT 结果均保留。",
            "",
            "局限：前台是每 DP 一个 FCFS 执行队列，没有连续批处理；GPU 计算与 DMA 的内存带宽",
            "干扰尚未校准，F0 相同不能解释为物理备份零开销。故障为单次永久 worker/host 故障；",
            "复制取消在模拟时钟内同步完成；没有模拟真实驱动取消延迟或多次连续故障。",
            "有限合成样本的分位数只是描述性统计，没有给出硬件速度或论文级置信结论。",
            "",
            "复现：在 MoonKVSim 仓库根目录执行",
            "",
            "```bash",
            ".venv/bin/python -m moonkvsim.aegiskv.current campaign "
            "--out /tmp/aegiskv-current-reproduce",
            "```",
            "",
            "`MANIFEST.json` 固定代码/设计 SHA-256；`source_snapshot/` 保留当次源文件。",
            "`runs/*/summary.json` 含请求、工作流、重建量、恢复队列/传输时刻、字节与容量数据；",
            "`events.jsonl.gz` 和 `flows.jsonl.gz` 保留原始事件/流速区间。",
            "",
            "设计源 SHA-256：`"
            + source_manifest["source_sha256"]["benchmark/AegisKV/paper/system_design.tex"]
            + "`。",
            "",
        ]
    )
    (out / "REPORT.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "campaign"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--workload", type=Path)
    parser.add_argument("--predictor", type=Path)
    parser.add_argument("--duration-profile", type=Path)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument(
        "--policy", choices=("none", "dram", "aegiskv", "all_dram", "static_hbm"), default="aegiskv"
    )
    parser.add_argument("--failure-agent")
    parser.add_argument("--failure-invocation", type=int, default=1)
    parser.add_argument("--failure-progress", type=float, default=0.8)
    parser.add_argument("--failure-scope", choices=("worker", "host"), default="worker")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--workflows", type=int, default=3)
    parser.add_argument("--journal", action="store_true")
    args = parser.parse_args()
    if args.command == "campaign":
        if (
            args.config
            or args.workload
            or args.predictor
            or args.duration_profile
            or args.summary_only
            or args.failure_agent
            or args.seed != 7
            or args.workflows != 3
            or args.policy != "aegiskv"
            or args.failure_invocation != 1
            or args.failure_progress != 0.8
            or args.failure_scope != "worker"
            or args.journal
        ):
            parser.error("campaign uses its frozen matrix; use run for custom inputs")
        campaign(args.out)
        return
    config = Config()
    if args.config:
        raw = json.loads(args.config.read_bytes())
        if "hosts" in raw:
            raw["hosts"] = tuple(raw["hosts"])
        config = Config(**raw)
    agents = (
        load_workload(args.workload)
        if args.workload
        else mechanism_workload(args.seed, args.workflows)
    )
    failure = (
        Failure(
            args.failure_agent, args.failure_invocation, args.failure_progress, args.failure_scope
        )
        if args.failure_agent
        else None
    )
    predictor = (
        ContextRegressor(**json.loads(args.predictor.read_bytes()))
        if args.predictor
        else prior_predictor
    )
    args.out.mkdir(parents=True, exist_ok=False)
    metadata = manifest(args.out)
    profile = None
    if args.duration_profile:
        from ..evaluation_profile import GridDurationProfile

        profile = GridDurationProfile(args.duration_profile)
        shutil.copy2(args.duration_profile, args.out / "duration-profile.json")
        metadata["duration_profile_sha256"] = digest(args.duration_profile)
        metadata["timing"] = profile.data["timing_evidence"]
    metadata["detailed_logs"] = not args.summary_only
    if args.workload:
        metadata["workload_class"] = "user_supplied; verify provenance before scientific use"
        metadata["input_workload_sha256"] = digest(args.workload)
    write_json(args.out / "MANIFEST.json", metadata)
    write_json(args.out / "workload.json", [asdict(a) for a in agents])
    if args.predictor:
        write_json(args.out / "predictor.json", predictor.to_dict())
    result = run_one(
        args.out / "run",
        config,
        agents,
        args.policy,
        failure,
        predictor=predictor,
        journal=args.journal,
        duration_profile=profile,
        retain_detailed_logs=not args.summary_only,
    )
    print(
        json.dumps(
            {
                "complete": result["complete"],
                "workflows": result["workflows"],
                "recoveries": result["recoveries"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
