"""Fixed fixtures for the existing-policy byte-identity regression.

The goldens in ``data/current_existing_policy_goldens.json`` were produced by the
runtime before the external modeled policies were added.  Every existing policy
must keep reproducing them exactly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from moonkvsim.aegiskv.current.model import Config, Failure
from moonkvsim.aegiskv.current.runtime import CurrentRuntime
from moonkvsim.aegiskv.current.workload import mechanism_workload

EXISTING_POLICIES = ("none", "all_dram", "dram", "static_hbm", "aegiskv")


def small(**changes):
    return replace(Config(), layers=8, depth=2, **changes)


def cases():
    one, two, three = (mechanism_workload(workflows=n) for n in (1, 2, 3))
    oracle = {agent.key: 1_500_000_000 + 100_000_000 * i for i, agent in enumerate(one)}
    return {
        "base-f0": (small(), one, None, {}),
        "base-f1": (small(), one, Failure("wf00/slow"), {}),
        "host-scope-budget": (
            small(hosts=(0, 0, 1, 1), dram_bytes_per_host=160 * 1024**2),
            two,
            Failure("wf00/slow", scope="host"),
            {},
        ),
        "copy-lag": (small(network_bytes_per_second=20e6), one, Failure("wf00/slow"), {}),
        "sparse-demand": (
            small(attention="synthetic_sparse", top_k=1),
            one,
            Failure("wf00/slow"),
            {},
        ),
        "dma-slowdown": (
            small(compute_dma_slowdown=0.05),
            two,
            Failure("wf01/fast", progress=0.9),
            {},
        ),
        "oracle-slack": (
            small(slack_mode="oracle"),
            one,
            Failure("wf00/slow"),
            {"oracle_duration_ns": oracle},
        ),
        "tight-budget": (
            small(dram_bytes_per_host=40 * 1024**2),
            three,
            Failure("wf01/slow"),
            {},
        ),
        "summary-journal": (
            small(),
            one,
            Failure("wf00/slow", invocation=0, progress=0.6),
            {"retain_detailed_logs": False},
        ),
    }


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fingerprint(config, agents, policy, failure, kwargs) -> dict[str, str]:
    runtime = CurrentRuntime(config, agents, policy=policy, failure=failure, **kwargs)
    summary = runtime.run()
    result = {
        "summary": sha(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
        ),
        "events": sha(
            json.dumps(runtime.events, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
        ),
        "flows": sha(runtime.flow_model.snapshot_bytes()),
    }
    journal = runtime.des.journal
    counts = getattr(journal, "counts", None)
    result["journal"] = sha(
        json.dumps(sorted(counts.items())).encode()
        if counts is not None
        else journal.to_jsonl_bytes()
    )
    return result


def all_fingerprints() -> dict[str, dict[str, str]]:
    return {
        f"{name}/{policy}": fingerprint(config, agents, policy, failure, kwargs)
        for name, (config, agents, failure, kwargs) in cases().items()
        for policy in EXISTING_POLICIES
    }
