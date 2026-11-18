#!/usr/bin/env python3
"""Synthetic arithmetic checks for the paper, not serving/runtime validation."""
from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path


def tier_and_fallback(slack, r_recompute, r_dram, dram_committed):
    """R remains feasible from the stipulated surviving inputs in these fixtures."""
    if r_recompute is None or r_dram is None:
        return {"tier": "D_attempt", "fallback": "D" if dram_committed else "R"}
    if min(slack, r_recompute, r_dram) < 0:
        raise ValueError("nonnegative seconds required")
    tier = "R" if slack >= r_recompute else (
        "D" if r_dram < r_recompute and slack >= r_dram else "P_candidate")
    fallback = "D" if dram_committed and r_dram < r_recompute else "R"
    return {"tier": tier, "fallback": fallback}


def route_with_intervals(current, r, d, *, dram_committed=True, margin=0.0):
    """R is feasible. Only valid committed D is a route, regardless of prediction."""
    if not dram_committed:
        return "R"
    if r[0] == r[1] == d[0] == d[1]:
        return "R"
    old, alt = (r, d) if current == "R" else (d, r)
    return ("D" if current == "R" else "R") if alt[1] + margin < old[0] else current


def completion_times(nodes, delays):
    """Topologically ordered, resource-free DAG; no queue/compute simulation."""
    finish = {}
    for node, seconds, parents in nodes:
        finish[node] = seconds + delays.get(node, 0) + max(
            (finish[p] for p in parents), default=0)
    return finish


def source_event_counterexample():
    # One physical source fails once, affecting A, B and C at the same event.
    # A/B are parallel critical branches of W1; C belongs to independent W2.
    nodes = [("A", 1, ()), ("B", 1, ()), ("joinAB", 0, ("A", "B")),
             ("C", 1, ()), ("joinC", 0, ("C",))]
    costs = {"A": 10, "B": 10, "C": 6}
    sinks = ("joinAB", "joinC")
    baseline = completion_times(nodes, {})
    rows = []
    # All protection objects have unit size. Budget=1; R=0 if fully protected.
    for count in (0, 1):
        for subset in itertools.combinations(costs, count):
            delays = {r: 0 if r in subset else v for r, v in costs.items()}
            finish = completion_times(nodes, delays)
            losses = {s: finish[s] - baseline[s] for s in sinks}
            rows.append({"protected": list(subset), "local_penalty_sum_s": sum(delays.values()),
                         "workflow_delays_s": losses, "total_wct_delay_s": sum(losses.values())})
    policy = next(x for x in rows if x["protected"] == ["A"])
    oracle = min(rows, key=lambda x: (x["total_wct_delay_s"], x["protected"]))
    return {"event": "one_common_source_failure", "capacity_units": 1,
            "all_slacks_s": 0, "tie_order": ["A", "B", "C"],
            "assumptions": "constructed equal-size protections; no resource contention; deterministic DAG",
            "allocations": rows, "policy": policy, "finite_oracle": oracle,
            "regret_s": policy["total_wct_delay_s"] - oracle["total_wct_delay_s"]}


def check():
    checks = []
    examples = [
        ("recompute equality", (10, 10, 4, True), ("R", "D")),
        ("DRAM threshold equality", (4, 10, 4, True), ("D", "D")),
        ("zero slack Peer competition", (0, 10, 4, True), ("P_candidate", "D")),
        ("congested DRAM is dominated", (0, 3, 8, True), ("P_candidate", "R")),
        ("equal route costs prefer R", (0, 3, 3, True), ("P_candidate", "R")),
        ("DRAM allocation not automatically successful", (0, 10, 4, False), ("P_candidate", "R")),
        ("missing profile attempts backing without speed claim", (0, None, 4, True), ("D_attempt", "D")),
        ("missing profile and no backing", (0, None, None, False), ("D_attempt", "R")),
    ]
    for name, args, expected in examples:
        result = tier_and_fallback(*args)
        assert (result["tier"], result["fallback"]) == expected, (name, result)
        checks.append({"name": name, "input": args, "result": result})
    assert route_with_intervals("D", (2, 5), (4, 7)) == "D"
    assert route_with_intervals("R", (2, 5), (4, 7)) == "R"
    checks.append({"name": "uncertain crossing retains feasible current route"})
    assert route_with_intervals("D", (2, 3), (4, 7), margin=.5) == "R"
    assert route_with_intervals("D", (2, 5), (1, 3), dram_committed=False) == "R"
    assert route_with_intervals("D", (3, 3), (3, 3)) == "R"
    checks.append({"name": "dominance, availability and exact tie override route preference"})
    counterexample = source_event_counterexample()
    unprotected = counterexample["allocations"][0]
    protected_a = counterexample["policy"]
    assert unprotected["workflow_delays_s"]["joinAB"] == protected_a["workflow_delays_s"]["joinAB"] == 10
    assert unprotected["local_penalty_sum_s"] - protected_a["local_penalty_sum_s"] == 10
    checks.append({"name": "one protected critical branch does not reduce the join delay"})
    assert counterexample["finite_oracle"]["protected"] == ["C"]
    assert math.isclose(counterexample["regret_s"], 6)
    checks.append({"name": "enumerated feasible small-DAG oracle exposes positive heuristic regret"})
    return {"evidence_type": "constructed_cpu_arithmetic_only", "passed": len(checks),
            "checks": checks, "counterexample": counterexample,
            "not_validated": ["real workload prevalence", "profile accuracy", "engine implementation",
                              "concurrent recovery", "commit/lease correctness", "performance"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(check(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result)
        print(f"Wrote {args.output}")
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
