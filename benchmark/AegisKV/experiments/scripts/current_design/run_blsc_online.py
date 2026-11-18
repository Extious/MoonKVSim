#!/usr/bin/env python3
"""Online arrivals on one captured NOSA trace, with one failure in the middle.

Workflows are released on a fixed schedule onto the BLSC two-node shape.
The failure hits one in-flight workflow after the system has already been
serving earlier arrivals. A matched run without that failure is the baseline.
"""

from __future__ import annotations

import json
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
OUT = ROOT / "benchmark/AegisKV/experiments/evaluation-20260924/blsc-online-v1"
N = 16
PROMPT = 1024
OUTPUT = 32
GAP_NS = 80_000_000
FAIL_INDEX = 8


def workload():
    agents = []
    for index in range(N):
        agents.append(
            Agent(
                f"wf{index:02d}",
                "job",
                (),
                (
                    Invocation(
                        tuple(range(PROMPT)),
                        tuple(range(OUTPUT)),
                        text="pg19-10146",
                    ),
                ),
                1_000_000_000,
                release_ns=index * GAP_NS,
            )
        )
    return tuple(agents)


def run(policy: str, demand, failure):
    runtime = CurrentRuntime(
        config(),
        workload(),
        policy=policy,
        failure=failure,
        demand_provider=demand,
    )
    summary = runtime.run()
    rows = []
    for index in range(N):
        name = f"wf{index:02d}"
        row = summary["workflows"][name]
        rows.append(
            {
                "workflow": name,
                "release_ns": index * GAP_NS,
                "wct_ns": row["wct_ns"],
                "finish_ns": row["finish_ns"],
            }
        )
    failure_ns = summary["failure"]["time_ns"] if summary.get("failure") else None
    recovery = summary["recoveries"][0] if summary["recoveries"] else None
    return {"workflows": rows, "failure_ns": failure_ns, "recovery": recovery}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    demand = NativeTraceDemand.load(TRACE, n_layers=32)
    failure = Failure(f"wf{FAIL_INDEX:02d}/job", invocation=0, progress=0.65)
    payload = {
        "trace": str(TRACE.relative_to(ROOT)),
        "h2d_bytes_per_second": H2D_BYTES_PER_SECOND,
        "workflows": N,
        "prompt_tokens": PROMPT,
        "gap_ns": GAP_NS,
        "failure_workflow": f"wf{FAIL_INDEX:02d}",
        "runs": {},
    }
    for policy in ("none", "dram", "aegiskv"):
        for fault, spec in (("healthy", None), ("failed", failure)):
            print("run", policy, fault, flush=True)
            payload["runs"][f"{policy}-{fault}"] = run(policy, demand, spec)
    (OUT / "RESULTS.json").write_text(json.dumps(payload) + "\n")
    failed = payload["runs"]["aegiskv-failed"]
    print("failure_s", failed["failure_ns"] / 1e9)
    if failed["recovery"]:
        rec = failed["recovery"]
        print(
            "aegiskv recovery_ms",
            round(rec["latency_ns"] / 1e6, 3),
            "ckpt",
            rec["checkpoint_tokens"],
            "hbm",
            rec["hbm_blocks"],
        )
    for index in range(N):
        healthy = payload["runs"]["aegiskv-healthy"]["workflows"][index]["wct_ns"]
        faulted = payload["runs"]["aegiskv-failed"]["workflows"][index]["wct_ns"]
        restart = payload["runs"]["none-failed"]["workflows"][index]["wct_ns"]
        dram = payload["runs"]["dram-failed"]["workflows"][index]["wct_ns"]
        print(
            f"wf{index:02d}",
            "delta_ms",
            round((faulted - healthy) / 1e6, 1),
            "aegis_ms",
            round(faulted / 1e6, 1),
            "dram_ms",
            round(dram / 1e6, 1),
            "restart_ms",
            round(restart / 1e6, 1),
        )


if __name__ == "__main__":
    main()
