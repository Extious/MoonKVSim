"""Small fixed linear-cost diagnostics; no frozen campaign runs or calibration."""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path


def write(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.tree / "python"))
    from moonkvsim.aegiskv.current.model import Agent, Config, Failure, Invocation
    from moonkvsim.aegiskv.current.runtime import Checkpoint, CurrentRuntime, LoadBatch

    config_values = dict(
        hosts=(0, 1),
        layers=2,
        depth=1,
        tp=1,
        top_k=4,
        kv_bytes_per_token_per_layer_rank=2048,
        h2d_bytes_per_second=2e6,
        d2h_bytes_per_second=12e9,
        network_bytes_per_second=10e9,
        prefill_ns_per_token=100_000,
        decode_ns_per_token=1_000_000,
        initial_quota_bytes=0,
        hbm_cap_bytes=0,
        max_time_ns=20 * 10**9,
    )
    invocation = Invocation(tuple(range(1024)), tuple(range(2000, 2008)), output_limit_tokens=16)
    agent = Agent("wf", "a", (), (invocation,), 10 * 10**9)
    write(args.out / "workload.json", [asdict(agent)])
    for attention in ("dense", "synthetic_sparse"):
        config = Config(**config_values, attention=attention)
        for fault in (False, True):
            folder = args.out / f"workflow-{attention}-F{int(fault)}"
            folder.mkdir()
            failure = Failure(agent.key, 0, (600 - 0.5) / 1032) if fault else None
            runtime = CurrentRuntime(config, (agent,), policy="dram", failure=failure)
            result = runtime.run()
            assert result["complete"] and result["terminal_allocations_zero"]
            assert result["output_tokens_exact"] and result["oracle_reservation_count"] == 0
            write(folder / "config.json", asdict(config))
            write(folder / "failure.json", asdict(failure) if failure else None)
            write(folder / "summary.json", result)
            write(folder / "events.json", runtime.events)
            write(folder / "flows.json", [asdict(x) for x in runtime.flow_model.intervals])

        # One initialized layer with CP=512/query=600. Other layer and metadata
        # are resident. This is a causal-domain event microcase, not a workflow
        # or a naturally selected HBM placement; resident sets are explicit.
        folder = args.out / f"layer-{attention}"
        folder.mkdir()
        runtime = CurrentRuntime(config, (agent,))
        runtime.des._heap.clear()
        state = runtime.states[agent.key]
        state.call, state.worker = 0, 1
        cp = Checkpoint(agent.key, 999, 0, 1, frontier=512, readers=1, retired=True)
        state.recovering = cp
        runtime.checkpoints.append(cp)
        runtime._dram_move(cp, "FREE", cp.account, config.checkpoint_bytes(512))
        resident = {0, 1, 2, 3} if attention == "dense" else {0, 3, 4, 5}
        state.available = {(0, b) for b in range(8)} | {(0, -512), (1, -512)}
        state.available.update((1, b) for b in resident)
        state.load_queue.append(LoadBatch(tuple((1, b) for b in range(8) if b not in resident)))
        runtime._rebalance = lambda: None
        completed = []
        runtime._layer_step(
            state,
            600,
            601,
            1,
            400_000_000,
            lambda completed=completed, runtime=runtime: completed.append(runtime.des.now_ns),
        )
        runtime.des.run()
        assert len(completed) == 1
        write(
            folder / "result.json",
            dict(
                initialized_resident_blocks=sorted(resident),
                checkpoint_tokens=512,
                query=600,
                layer=1,
                layer_compute_ns=200_000_000,
                layer_finish_ns=completed[0],
                full_restore_or_drain_ns=runtime.des.now_ns,
                metrics=dict(runtime.metrics),
                evidence="initialized layer event microcase; not measured or a full workflow",
            ),
        )
        write(folder / "events.json", runtime.events)
        write(folder / "flows.json", [asdict(x) for x in runtime.flow_model.intervals])

    imports = {}
    for name, module in list(sys.modules.items()):
        if name.startswith("moonkvsim") and getattr(module, "__file__", None):
            path = Path(module.__file__).resolve()
            assert path.is_relative_to(args.tree / "python")
            imports[name] = dict(
                path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()
            )
    write(args.out / "IMPORTS.json", imports)
    print(f"completed fixed diagnostics in {args.out}")


if __name__ == "__main__":
    main()
