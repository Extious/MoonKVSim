"""Read-only reproduction of EOS while recovery cold-prefetch remains active.

ObserveRuntime records timing without altering production behavior. WakeOnly is
an explicitly diagnostic counterfactual: it adds only the missing final wake,
illustrating the EOS-to-drain penalty of retaining the original completion gate.
No current runtime module or frozen campaign source is modified.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "python"))

from moonkvsim.aegiskv.current.model import Agent, Config, Failure, Invocation  # noqa: E402
from moonkvsim.aegiskv.current.runtime import CurrentRuntime  # noqa: E402


def sparse_block_zero(config, invocation, layer, query, history_blocks):
    return (0,)


class ObserveRuntime(CurrentRuntime):
    def __init__(self, *args, **kwargs):
        self.observed = {}
        super().__init__(*args, **kwargs)

    def _forward_done(self, state, start, end, replaying):
        if end == len(state.invocation.tokens):
            self.observed.setdefault("eos_forward_done_ns", self.des.now_ns)
            self.observed.setdefault("eos_recovering", state.recovering is not None)
            self.observed.setdefault("eos_active_restore", state.load_active)
            self.observed.setdefault("eos_queued_batches", len(state.load_queue))
        super()._forward_done(state, start, end, replaying)

    def _complete(self, state):
        self.observed.setdefault("first_complete_attempt_ns", self.des.now_ns)
        super()._complete(state)

    def _load_next(self, state):
        was_recovering = state.recovering is not None
        super()._load_next(state)
        if was_recovering and state.recovering is None:
            self.observed.setdefault("restore_cleared_ns", self.des.now_ns)
            self.observed.setdefault("waiting_after_restore_clear", state.waiting is not None)


class WakeOnly(ObserveRuntime):
    def _load_next(self, state):
        was_recovering = state.recovering is not None
        super()._load_next(state)
        if was_recovering and state.recovering is None and state.waiting is not None:
            wake, state.waiting = state.waiting, None
            wake()


def execute(policy, sparse, wake_only=False):
    config = replace(
        Config(),
        hosts=(0, 1, 2),
        tp=1,
        layers=2,
        depth=2,
        top_k=1,
        h2d_bytes_per_second=10e6,
        decode_ns_per_token=10_000,
        max_time_ns=2_000_000_000,
        attention="synthetic_sparse" if sparse else "dense",
        synthetic_selected_blocks=1,
    )
    inv = Invocation(tuple(range(1024)), tuple(range(32)), output_limit_tokens=32)
    agent = Agent("w", "a", (), (inv,), 1_000_000_000)
    failure = Failure("w/a", invocation=0, progress=0.99)
    runtime = (WakeOnly if wake_only else ObserveRuntime)(
        config,
        (agent,),
        policy=policy,
        failure=failure,
        demand_provider=sparse_block_zero if sparse else None,
    )
    error, result = None, None
    try:
        result = runtime.run()
    except RuntimeError as exc:
        error = str(exc)
    state = runtime.states["w/a"]
    return {
        "policy": policy,
        "attention": "constructed-block-zero" if sparse else "dense",
        "diagnostic_final_wake_only": wake_only,
        "config": asdict(config),
        "failure_spec": asdict(failure),
        "observed": runtime.observed,
        "failure": runtime.failure_record,
        "recovery": runtime.recoveries,
        "completed_requests": runtime.requests,
        "runtime_error": error,
        "complete": bool(result),
        "post_drain_eos_delay_ns": (
            runtime.requests[0]["finish_ns"] - runtime.observed["eos_forward_done_ns"]
            if runtime.requests
            else None
        ),
        "terminal_state": {
            "time_ns": runtime.des.now_ns,
            "computed": state.computed,
            "emitted_tokens": runtime.metrics["emitted_tokens"],
            "finished_ns": state.finished,
            "recovering": state.recovering is not None,
            "waiting": state.waiting is not None,
            "busy_worker": runtime.busy[state.worker],
            "active_flows": len(runtime.flow_model.flows),
            "primary_bytes": sum(
                ledger.bytes_in("primary:w/a") for ledger in runtime.ledgers.values()
            ),
        },
    }


def main():
    runtime_path = ROOT / "python/moonkvsim/aegiskv/current/runtime.py"
    runs = [
        execute(policy, sparse, wake)
        for policy in ("dram", "aegiskv")
        for sparse, wake in ((False, False), (True, False), (True, True))
    ]
    payload = {
        "evidence_class": (
            "constructed deterministic simulator regression, not model/GPU measurement"
        ),
        "production_runtime_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
        "reproduction_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runs": runs,
    }
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    for run in runs:
        recovery = run["recovery"][0]
        print(
            json.dumps(
                {
                    "policy": run["policy"],
                    "attention": run["attention"],
                    "wake_only": run["diagnostic_final_wake_only"],
                    "first_new_token_ns": recovery.get("first_new_token_ns"),
                    "eos_ns": run["observed"].get("eos_forward_done_ns"),
                    "restore_done_ns": recovery.get("restore_done_ns"),
                    "request_finish_ns": run["terminal_state"]["finished_ns"],
                    "delay_ns": run["post_drain_eos_delay_ns"],
                    "error": run["runtime_error"],
                }
            )
        )


if __name__ == "__main__":
    main()
