#!/usr/bin/env python3
"""Exact arithmetic checks for a conditional KV placement theorem.

No model execution, request simulation, latency calibration, or performance
experiment is performed. Integer byte/time units below are constructed inputs.
Run this file from any directory; artifacts are written beside the script.
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import subprocess
from datetime import datetime, timezone
from fractions import Fraction as F
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ZERO = F(0)


def prefix_allocation(sizes, budget):
    result = []
    left = F(budget)
    for size in sizes:
        amount = min(F(size), left)
        result.append(amount)
        left -= amount
    return tuple(result)


def event_finish(sizes, compute, pre_kv, rate, resident):
    """Actual per-layer KV readiness and serial compute, with one copy stream."""
    copy_clock = ZERO
    compute_clock = ZERO
    for size, duration, prelude, held in zip(
        sizes, compute, pre_kv, resident, strict=True
    ):
        assert 0 <= held <= size and 0 <= prelude <= duration
        missing = F(size) - held
        if missing:
            copy_clock += missing / rate
            ready = copy_clock
        else:
            ready = ZERO
        compute_clock = max(compute_clock + prelude, ready) + duration - prelude
    return compute_clock


def exposed_wait(sizes, compute, pre_kv, rate):
    cumulative_bytes = ZERO
    previous_compute = ZERO
    wait = ZERO
    for size, duration, prelude in zip(sizes, compute, pre_kv, strict=True):
        cumulative_bytes += size
        wait = max(wait, cumulative_bytes / rate - previous_compute - prelude)
        previous_compute += duration
    return wait


def analytical_value(budget, rate, wait, floor, slack, probability):
    useful_wait = min(wait, max(ZERO, floor + wait - slack))
    return probability * min(F(budget) / rate, useful_wait)


def direct_value(budget, rate, wait, floor, slack, probability):
    before = max(ZERO, floor + wait - slack)
    after = max(ZERO, floor + max(ZERO, wait - F(budget) / rate) - slack)
    return probability * (before - after)


def write_csv(name, rows):
    with (HERE / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(name, data):
    (HERE / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def check_placement():
    placement_count = 0
    prefix_count = 0
    geometry_count = 0
    for layers in range(1, 5):
        for sizes in itertools.product((1, 2), repeat=layers):
            for compute in itertools.product((F(0), F(1), F(3)), repeat=layers):
                for rate in (F(1), F(2)):
                    for prelude_fraction in (F(0), F(1, 2)):
                        geometry_count += 1
                        pre_kv = tuple(c * prelude_fraction for c in compute)
                        wait = exposed_wait(sizes, compute, pre_kv, rate)
                        for twice_budget in range(2 * sum(sizes) + 1):
                            budget = F(twice_budget, 2)
                            allocation = prefix_allocation(sizes, budget)
                            actual = event_finish(sizes, compute, pre_kv, rate, allocation)
                            formula = sum(compute) + max(ZERO, wait - budget / rate)
                            assert actual == formula, (
                                sizes, compute, pre_kv, rate, budget, actual, formula
                            )
                            prefix_count += 1
                        # Enumerate every integer-byte placement on these small
                        # constructed geometries; compare at exactly equal budget.
                        for held in itertools.product(*(range(s + 1) for s in sizes)):
                            actual = event_finish(sizes, compute, pre_kv, rate, held)
                            best = sum(compute) + max(ZERO, wait - F(sum(held)) / rate)
                            assert actual >= best, (sizes, compute, pre_kv, rate, held)
                            placement_count += 1
    return {
        "constructed_geometries": geometry_count,
        "prefix_recurrence_equalities": prefix_count,
        "all_integer_placements_dominated_or_tied": placement_count,
        "input_scope": {
            "layers": [1, 2, 3, 4],
            "layer_bytes": [1, 2],
            "compute_time_units": [0, 1, 3],
            "bytes_per_time_unit": [1, 2],
            "pre_kv_fraction_of_compute": ["0", "1/2"],
            "prefix_budget_step_bytes": "1/2",
        },
    }


def check_slack():
    count = 0
    for rate, wait, floor, slack, probability in itertools.product(
        (F(1), F(2)),
        (F(0), F(1, 2), F(1), F(3)),
        (F(0), F(1), F(2)),
        (F(-1), F(0), F(1), F(2), F(3), F(5)),
        (F(0), F(1, 10), F(1)),
    ):
        for twice_budget in range(17):
            budget = F(twice_budget, 2)
            assert analytical_value(budget, rate, wait, floor, slack, probability) == direct_value(
                budget, rate, wait, floor, slack, probability
            )
            count += 1
    rows = []
    # MiB/ms is an invented arithmetic rate here, not a device specification.
    for slack in (F(0), F(8), F(12)):
        useful = min(F(10), max(ZERO, F(2) + 10 - slack))
        for budget in (0, 20, 40, 60, 100):
            rows.append({
                "evidence": "constructed_arithmetic_not_measurement",
                "slack_ms": float(slack),
                "floor_extra_ms": 2,
                "baseline_exposed_wait_ms": 10,
                "rate_MiB_per_ms": 10,
                "conditional_failure_probability": 1,
                "hbm_MiB": budget,
                "useful_cap_MiB": float(10 * useful),
                "avoided_proxy_loss_ms": float(direct_value(
                    F(budget), F(10), F(10), F(2), slack, F(1)
                )),
            })
    write_csv("slack-cap-examples.csv", rows)
    return {"closed_form_equalities": count}


def check_allocations():
    # Equal byte quanta, independent concave request curves. Exhaustive optima
    # here check only this stated finite setting, never the joint-DAG problem.
    requests = (
        (F(1), F(2), F(1), F(0), F(1, 2)),
        (F(2), F(2), F(0), F(1), F(1, 2)),
        (F(1), F(3), F(1), F(2), F(1, 4)),
    )  # rate, wait, floor, slack, probability
    caps = [4, 4, 4]

    def value(alloc):
        return sum(analytical_value(F(b), *r) for b, r in zip(alloc, requests, strict=True))

    rows = []
    for budget in range(sum(caps) + 1):
        allocation = [0, 0, 0]
        for _ in range(budget):
            candidates = []
            before = value(allocation)
            for r in range(3):
                if allocation[r] < caps[r]:
                    candidate = allocation.copy()
                    candidate[r] += 1
                    candidates.append((value(candidate) - before, -r))
            if not candidates or max(candidates)[0] <= 0:
                break
            _, negative_id = max(candidates)
            allocation[-negative_id] += 1
        exact = max(
            value(a)
            for a in itertools.product(*(range(c + 1) for c in caps))
            if sum(a) <= budget
        )
        assert value(allocation) == exact
        rows.append({
            "budget_byte_units": budget,
            "request_0_bytes": allocation[0],
            "request_1_bytes": allocation[1],
            "request_2_bytes": allocation[2],
            "greedy_value_exact_fraction": str(value(allocation)),
            "enumerated_optimum_exact_fraction": str(exact),
        })
    write_csv("separable-allocation-examples.csv", rows)
    return {"equal_quantum_greedy_vs_enumeration": len(rows)}


def check_joint_wct():
    # One source failure delays both branches by 6 ms; the same healthy fork
    # finishes at 10 ms. A protected branch loses its entire additional delay.
    rows = []
    costs = {}
    for protect_a, protect_b in itertools.product((False, True), repeat=2):
        finish_a = 10 + (0 if protect_a else 6)
        finish_b = 10 + (0 if protect_b else 6)
        wct = max(finish_a, finish_b)
        costs[(protect_a, protect_b)] = wct
        rows.append({
            "evidence": "constructed_fork_join_arithmetic_not_measurement",
            "protect_a": protect_a,
            "protect_b": protect_b,
            "finish_a_ms": finish_a,
            "finish_b_ms": finish_b,
            "workflow_finish_ms": wct,
            "avoided_workflow_delay_ms": 16 - wct,
        })
    assert costs[(False, False)] - costs[(True, False)] == 0
    assert costs[(False, False)] - costs[(False, True)] == 0
    assert costs[(False, False)] - costs[(True, True)] == 6
    write_csv("joint-wct-counterexample.csv", rows)
    return {"placements_checked": len(rows), "single_gains_ms": [0, 0], "bundle_gain_ms": 6}


def main():
    checks = {
        "status": "PASS",
        "evidence_kind": "bounded_exact_arithmetic_checks",
        "not_evidence_of": [
            "hardware_latency", "native_sparse_selection_statistics",
            "runtime_integration", "empirical_WCT_improvement",
            "general_joint_DAG_optimality",
        ],
        "placement": check_placement(),
        "slack_caps": check_slack(),
        "separable_allocation": check_allocations(),
        "joint_wct": check_joint_wct(),
    }
    write_json("checks.json", checks)
    runtime_paths = [
        "python/moonkvsim/aegiskv/" + name for name in (
            "types.py", "recovery_harm.py", "recovery_planner.py", "lease_value.py",
            "agent_lease.py", "slack_landlord.py", "experiment.py",
        )
    ]
    document_paths = [
        "benchmark/AegisKV/docs/paper/REQUEST_KV_POLICY_SPEC_20260914.md",
        "benchmark/AegisKV/docs/paper/README.md",
        "benchmark/AegisKV/docs/paper/KV_MOTIVATION_AND_PRIORITY_20260913.md",
    ]
    generated_paths = [
        str(path.relative_to(ROOT)) for path in sorted(HERE.iterdir())
        if path.is_file() and path.name != "MANIFEST.json"
    ]

    def revision(ref):
        return subprocess.check_output(
            ["git", "rev-parse", ref], cwd=ROOT, text=True
        ).strip()

    status = subprocess.check_output(
        ["git", "status", "--porcelain", "-z"], cwd=ROOT
    )
    write_json("MANIFEST.json", {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_kind": checks["evidence_kind"],
        "head": revision("HEAD"),
        "origin_aegiskv_tracking_ref": revision("origin/aegiskv"),
        "remote_fetched": False,
        "worktree_dirty": bool(status),
        "working_tree_files_are_the_audited_sources": True,
        "files": {
            relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            for relative in sorted(set(runtime_paths + document_paths + generated_paths))
        },
    })
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
