#!/usr/bin/env python3
"""Online simulation driven only by client.json, engine.json, and failure.json."""

from __future__ import annotations

import json
from pathlib import Path

from moonkvsim.aegiskv.current.blsc import config as blsc_config
from moonkvsim.aegiskv.current.model import Agent, Failure, Invocation
from moonkvsim.aegiskv.current.native_demand import NativeTraceDemand
from moonkvsim.aegiskv.current.runtime import CurrentRuntime

ROOT = Path(__file__).resolve().parents[5]
CONFIGS = ROOT / "benchmark/AegisKV/experiments/blsc-online/configs"
OUT = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/blsc-online-v1"


def load(name: str) -> dict:
    return json.loads((CONFIGS / name).read_text())


def workload(client: dict) -> tuple[Agent, ...]:
    prompt = int(client["prompt_tokens"])
    output = int(client["output_tokens"])
    gap = int(client["arrival_gap_ns"])
    text = str(client["document"])
    agents = []
    for index in range(int(client["workflows"])):
        agents.append(
            Agent(
                f"wf{index:02d}",
                "job",
                (),
                (Invocation(tuple(range(prompt)), tuple(range(output)), text=text),),
                1_000_000_000,
                release_ns=index * gap,
            )
        )
    return tuple(agents)


def engine_config(engine: dict):
    if int(engine["nodes"]) != 2 or int(engine["gpus_per_node"]) != 2:
        raise SystemExit("this runner expects the BLSC shape: 2 nodes, 2 GPUs each")
    if int(engine["tensor_parallel_size"]) != 2:
        raise SystemExit("BLSC measurements used TP=2")
    return blsc_config(
        h2d_bytes_per_second=float(engine["h2d_bytes_per_second"]),
        d2h_bytes_per_second=float(engine["d2h_bytes_per_second"]),
        router_mode=str(engine["router_mode"]),
        layers=int(engine["layers"]),
        depth=int(engine["depth"]),
        top_k=int(engine["top_k"]),
        tp=int(engine["tensor_parallel_size"]),
    )


def one_run(cfg, agents, demand, failure, policy: str):
    runtime = CurrentRuntime(
        cfg,
        agents,
        policy=policy,
        failure=failure,
        demand_provider=demand,
    )
    return runtime.run(), runtime


def main():
    client = load("client.json")
    engine = load("engine.json")
    failure_doc = load("failure.json")
    for name, doc, schema in (
        ("client.json", client, "aegiskv.online.client.v1"),
        ("engine.json", engine, "aegiskv.online.engine.v1"),
        ("failure.json", failure_doc, "aegiskv.online.failure.v1"),
    ):
        if doc.get("schema") != schema:
            raise SystemExit(f"{name} schema must be {schema}")
    cfg = engine_config(engine)
    agents = workload(client)
    demand = NativeTraceDemand.load(ROOT / client["trace"], n_layers=int(engine["layers"]))
    index = int(failure_doc["workflow_index"])
    failure = Failure(
        f"wf{index:02d}/job",
        invocation=int(failure_doc["invocation"]),
        progress=float(failure_doc["progress"]),
        scope=str(failure_doc["scope"]),
    )
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "client": client,
        "engine": engine,
        "failure": failure_doc,
        "runs": {},
    }
    for policy in ("none", "dram", "aegiskv"):
        for fault, spec in (("healthy", None), ("failed", failure)):
            print("run", policy, fault, flush=True)
            summary, runtime = one_run(cfg, agents, demand, spec, policy)
            rows = []
            for i in range(int(client["workflows"])):
                name = f"wf{i:02d}"
                row = summary["workflows"][name]
                rows.append(
                    {
                        "workflow": name,
                        "release_ns": i * int(client["arrival_gap_ns"]),
                        "wct_ns": row["wct_ns"],
                    }
                )
            peers = sorted(
                {
                    (cp.source, cp.peer)
                    for cp in runtime.checkpoints
                    if not cp.retired
                }
            )
            payload["runs"][f"{policy}-{fault}"] = {
                "workflows": rows,
                "failure_ns": summary["failure"]["time_ns"] if summary.get("failure") else None,
                "recovery": summary["recoveries"][0] if summary["recoveries"] else None,
                "quota_bytes": runtime.adapters[0, 0].quota,
                "live_peers": peers,
            }
    (OUT / "RESULTS.json").write_text(json.dumps(payload) + "\n")


if __name__ == "__main__":
    main()
