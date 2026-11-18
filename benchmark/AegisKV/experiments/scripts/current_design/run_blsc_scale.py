#!/usr/bin/env python3
"""Full AegisKV online runs on captured sparse traces and the BLSC engine.

Token service times are the runtime defaults. Host-to-device bandwidth is the
measured BLSC pinned rate. Each finished cell is written before the next starts.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from moonkvsim.aegiskv.current.blsc import config as blsc_config
from moonkvsim.aegiskv.current.model import Agent, Failure, Invocation
from moonkvsim.aegiskv.current.native_demand import NativeTraceDemand
from moonkvsim.aegiskv.current.runtime import CurrentRuntime

ROOT = Path(__file__).resolve().parents[5]
SPARSE = ROOT / "benchmark/AegisKV/experiments/native-sparse"
OUT = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/blsc-scale-v1"
FAULTS = ROOT / "benchmark/AegisKV/experiments/data/background-infinitehbd/fault_trace.json"

TRACES = {
    "NOSA-8B": SPARSE
    / "20260921-concentration-nosa8b/capture-153951/traces",
    "NSA-8B": SPARSE
    / "20260921-concentration-new-models/nsa8b-attempt-153894/traces",
    "MiniCPM4.1-8B": SPARSE
    / "20260921-concentration-new-models/minicpm41/traces",
}
SUFFIX = {
    "NOSA-8B": "M32192-N512",
    "NSA-8B": "M32256-N512",
    "MiniCPM4.1-8B": "M32256-N512",
}
DOCUMENTS = ("10146", "10321", "10356")
LENGTHS = (2048, 8192, 16384, 24576)
OUTPUT = 64
WORKFLOWS = 8
FAIL_INDEX = 4
PROGRESS = 0.65
PREFILL_NS = 100_000
DECODE_NS = 2_000_000


def service_ns(prompt: int) -> int:
    return PREFILL_NS * prompt + DECODE_NS * OUTPUT


def agents_for(prompt: int, document: str, gap: int) -> tuple[Agent, ...]:
    return tuple(
        Agent(
            f"wf{i:02d}",
            "job",
            (),
            (Invocation(tuple(range(prompt)), tuple(range(OUTPUT)), text=f"pg19-{document}"),),
            1_000_000_000,
            release_ns=i * gap,
        )
        for i in range(WORKFLOWS)
    )


def trace_dir(model: str, document: str) -> Path:
    return TRACES[model] / f"pg19-{document}-{SUFFIX[model]}"


def fault_statistics() -> dict:
    events = json.loads(FAULTS.read_text())
    gpu = [event for event in events if event["fault_type"]["Class"] == "GPU"]
    starts = [event for event in gpu if event["event_type"] == "fault_start"]
    ends: dict[str, list[float]] = {}
    for event in gpu:
        if event["event_type"] == "fault_end":
            ends.setdefault(event["node_id"], []).append(event["event_time"])
    durations = []
    for event in starts:
        later = [stamp for stamp in ends.get(event["node_id"], []) if stamp >= event["event_time"]]
        if later:
            durations.append(min(later) - event["event_time"])
    durations.sort()
    span = events[-1]["event_time"] - events[0]["event_time"]
    return {
        "source": "InfiniteHBD-Trace GPU faults, event_time in days from the first event",
        "gpu_faults": len(starts),
        "gpu_nodes": len({event["node_id"] for event in starts}),
        "span_days": span,
        "downtime_days_min": durations[0],
        "downtime_days_median": durations[len(durations) // 2],
        "downtime_days": durations,
    }


def one(cell: dict, demand: NativeTraceDemand) -> dict:
    prompt = int(cell["prompt_tokens"])
    gap = int(0.45 * service_ns(prompt))
    workload = agents_for(prompt, cell["document"], gap)
    failure = None
    if cell["fault"] == "failed":
        failure = Failure(
            f"wf{FAIL_INDEX:02d}/job",
            invocation=0,
            progress=PROGRESS,
            scope="worker",
        )
    started = time.perf_counter()
    runtime = CurrentRuntime(
        blsc_config(),
        workload,
        policy=cell["policy"],
        failure=failure,
        demand_provider=demand,
    )
    summary = runtime.run()
    rows = [
        {
            "workflow": f"wf{i:02d}",
            "release_ns": i * gap,
            "wct_ns": summary["workflows"][f"wf{i:02d}"]["wct_ns"],
        }
        for i in range(WORKFLOWS)
    ]
    return {
        **cell,
        "arrival_gap_ns": gap,
        "service_ns": service_ns(prompt),
        "wall_s": round(time.perf_counter() - started, 3),
        "workflows": rows,
        "failure_ns": summary["failure"]["time_ns"] if summary.get("failure") else None,
        "recovery": summary["recoveries"][0] if summary["recoveries"] else None,
        "quota_bytes": runtime.adapters[0, 0].quota,
    }


def cells() -> list[dict]:
    planned = []
    for prompt in LENGTHS:
        for policy in ("none", "dram", "aegiskv"):
            for fault in ("healthy", "failed"):
                planned.append(
                    {
                        "model": "NOSA-8B",
                        "document": "10146",
                        "prompt_tokens": prompt,
                        "policy": policy,
                        "fault": fault,
                    }
                )
    for model in ("NSA-8B", "MiniCPM4.1-8B"):
        for policy in ("none", "dram", "aegiskv"):
            for fault in ("healthy", "failed"):
                planned.append(
                    {
                        "model": model,
                        "document": "10146",
                        "prompt_tokens": 8192,
                        "policy": policy,
                        "fault": fault,
                    }
                )
    for document in ("10321", "10356"):
        for policy in ("none", "aegiskv"):
            for fault in ("healthy", "failed"):
                planned.append(
                    {
                        "model": "NOSA-8B",
                        "document": document,
                        "prompt_tokens": 8192,
                        "policy": policy,
                        "fault": fault,
                    }
                )
    return planned


def cell_path(cell: dict) -> Path:
    name = (
        f"{cell['model']}-pg19-{cell['document']}-p{cell['prompt_tokens']}"
        f"-{cell['policy']}-{cell['fault']}.json"
    )
    return OUT / "runs" / name


def main() -> None:
    (OUT / "runs").mkdir(parents=True, exist_ok=True)
    (OUT / "fault-trace.json").write_text(json.dumps(fault_statistics()) + "\n")
    demand_key = None
    demand = None
    for cell in cells():
        path = cell_path(cell)
        if path.exists():
            print("skip", path.name, flush=True)
            continue
        key = (cell["model"], cell["document"])
        if key != demand_key:
            print("load", key, flush=True)
            demand = NativeTraceDemand.load(trace_dir(*key), n_layers=32)
            demand_key = key
        print("run", path.name, flush=True)
        payload = one(cell, demand)
        path.write_text(json.dumps(payload) + "\n")
        recovery = payload["recovery"]
        print(
            " done",
            payload["wall_s"],
            "lat",
            None if recovery is None else recovery["latency_ns"],
            flush=True,
        )


if __name__ == "__main__":
    main()
