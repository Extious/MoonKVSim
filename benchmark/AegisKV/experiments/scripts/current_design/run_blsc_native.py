#!/usr/bin/env python3
"""One failure on a real NOSA selector trace, on the BLSC two-node shape.

The trace is the captured PG19-10146 forward. The DAG is two Agents so
Router, KV Master and Adapter all run; it is not a recorded multi-agent log.
"""

from __future__ import annotations

from pathlib import Path

from moonkvsim.aegiskv.current.blsc import H2D_BYTES_PER_SECOND, config
from moonkvsim.aegiskv.current.model import Agent, Failure, Invocation
from moonkvsim.aegiskv.current.native_demand import NativeTraceDemand
from moonkvsim.aegiskv.current.runtime import CurrentRuntime

ROOT = Path(__file__).resolve().parents[5]
TRACE = (
    ROOT
    / "benchmark/AegisKV/experiments/native-sparse/20260921-concentration-nosa8b"
    / "capture-153951/traces/pg19-10146-M32192-N512"
)
PROMPT = 2048
OUTPUT = 32


def agent(name, parents=()):
    return Agent(
        "wf",
        name,
        parents,
        (
            Invocation(
                tuple(range(PROMPT)),
                tuple(range(OUTPUT)),
                text="pg19-10146",
            ),
        ),
        1_000_000_000,
    )


def main():
    demand = NativeTraceDemand.load(TRACE, n_layers=32)
    agents = (agent("a"), agent("b", ("a",)))
    failure = Failure("wf/b", invocation=0, progress=0.8)
    print("h2d_GBps", H2D_BYTES_PER_SECOND / 1e9)
    for policy in ("none", "dram", "aegiskv"):
        runtime = CurrentRuntime(
            config(),
            agents,
            policy=policy,
            failure=failure,
            demand_provider=demand,
        )
        summary = runtime.run()
        recovery = summary["recoveries"][0]
        print(
            policy,
            "wct_ms",
            round(summary["workflows"]["wf"]["wct_ns"] / 1e6, 3),
            "agent_ms",
            round(recovery["latency_ns"] / 1e6, 3),
            "ckpt",
            recovery["checkpoint_tokens"],
            "hbm_blocks",
            recovery["hbm_blocks"],
            "peer_ok",
            all(
                runtime.config.hosts[cp.source] != runtime.config.hosts[cp.peer]
                for cp in runtime.checkpoints
            ),
            "quota",
            runtime.adapters[0, 0].quota,
        )


if __name__ == "__main__":
    main()
