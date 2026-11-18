#!/usr/bin/env python3
"""Reference arithmetic for the paper depth objective; not a runtime/profile fit.

Inputs are already-admitted candidate plans and declared profile predictions.
--self-check uses synthetic numbers only. It runs no serving/hardware experiment.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path


def interval(value, *, nonnegative=False):
    """Accept [lower, estimate, upper], in seconds."""
    if len(value) != 3 or not all(math.isfinite(float(x)) for x in value):
        raise ValueError("finite [lower, estimate, upper] required")
    lo, mean, hi = map(float, value)
    if not lo <= mean <= hi or (nonnegative and lo < 0):
        raise ValueError("invalid interval")
    return lo, mean, hi


def decide(problem):
    """All candidates must refer to the same immutable snapshot and scenarios."""
    h, rate = float(problem["horizon_s"]), float(problem["failure_rate_per_s"])
    slack, margin = float(problem["slack_s"]), float(problem["switch_margin_s"])
    if not all(math.isfinite(x) for x in (h, rate, slack, margin)):
        raise ValueError("nonfinite configuration")
    if h <= 0 or min(rate, slack, margin) < 0:
        raise ValueError("invalid configuration")
    samples = problem["conditional_failure_samples"]
    if not samples:
        raise ValueError("conditional samples required")
    weights = [float(s["weight"]) for s in samples]
    if any(not math.isfinite(w) or w < 0 for w in weights):
        raise ValueError("nonnegative finite weights required")
    if not math.isclose(sum(weights), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError("conditional sample weights must sum to one")
    if len({s["id"] for s in samples}) != len(samples):
        raise ValueError("duplicate scenario id")
    plans = problem["plans"]
    if len({x["id"] for x in plans}) != len(plans):
        raise ValueError("duplicate plan id")
    keep = [x for x in plans if x["keep"]]
    if len(keep) != 1:
        raise ValueError("exactly one explicit keep plan required")
    keep = keep[0]
    fallback = {
        "selected": keep["id"] if keep["feasible"] else "dram_demotion",
        "action": "hold" if keep["feasible"] else "mandatory_retirement",
        "reason": "invalid profile; retain only feasible residency",
        "score_intervals_s": {},
    }
    # A resource contraction has higher authority than an uncertain cost estimate.
    if not keep["feasible"]:
        fallback["reason"] = "keep exceeds feasible capacity; safe retirement required"
        return fallback
    if not problem["profile_generation_valid"] or not keep["profile_valid"]:
        return fallback
    probability = -math.expm1(-rate * h)
    scores = {}
    for plan in plans:
        if not plan["feasible"] or not plan["profile_valid"]:
            continue
        if plan["snapshot_id"] != problem["snapshot_id"]:
            raise ValueError("candidate snapshot mismatch")
        a = interval(plan["foreground_delay_delta_s"])
        if set(plan["recovery_s"]) != {s["id"] for s in samples}:
            raise ValueError("candidate scenario set mismatch")
        r = [interval(plan["recovery_s"][s["id"]], nonnegative=True) for s in samples]
        scores[plan["id"]] = [
            a[k] + probability * sum(w * max(0.0, ri[k] - slack)
                                    for w, ri in zip(weights, r))
            for k in range(3)
        ]
    valid = [p for p in plans if p["id"] in scores]
    best = min(valid, key=lambda p: (scores[p["id"]][1], p["depth"], p["id"]))
    choose = best if scores[best["id"]][2] + margin < scores[keep["id"]][0] else keep
    return {
        "selected": choose["id"],
        "action": "hold" if choose["keep"] else "apply_plan",
        "reason": "interval-separated improvement" if not choose["keep"] else "no robust improvement",
        "source_failure_probability": probability,
        "score_intervals_s": scores,
    }


def fixture():
    # Arithmetic example: these are invented test values, not AegisKV measurements.
    return {
        "evidence_type": "synthetic_arithmetic_example",
        "snapshot_id": "same-snapshot-for-all-plans",
        "horizon_s": 10.0,
        "failure_rate_per_s": 0.01,
        "slack_s": 0.0,
        "switch_margin_s": 0.001,
        "profile_generation_valid": True,
        "conditional_failure_samples": [
            {"id": "short_tail", "weight": 0.5, "M_tokens": 32768, "N_tokens": 8},
            {"id": "copy_lag", "weight": 0.5, "M_tokens": 33024, "N_tokens": 96},
        ],
        "plans": [
            {"id": "keep", "keep": True, "depth": 0, "feasible": True, "profile_valid": True,
             "snapshot_id": "same-snapshot-for-all-plans",
             "foreground_delay_delta_s": [0, 0, 0],
             "recovery_s": {"short_tail": [1, 1, 1], "copy_lag": [2, 2, 2]}},
            {"id": "depth4", "keep": False, "depth": 4, "feasible": True, "profile_valid": True,
             "snapshot_id": "same-snapshot-for-all-plans",
             "foreground_delay_delta_s": [0.01, 0.01, 0.01],
             "recovery_s": {"short_tail": [0.3, 0.3, 0.3], "copy_lag": [0.7, 0.7, 0.7]}},
            {"id": "depth8", "keep": False, "depth": 8, "feasible": True, "profile_valid": True,
             "snapshot_id": "same-snapshot-for-all-plans",
             "foreground_delay_delta_s": [0.03, 0.03, 0.03],
             "recovery_s": {"short_tail": [0.25, 0.25, 0.25], "copy_lag": [0.65, 0.65, 0.65]}},
        ],
    }


def self_check():
    cases = []
    p = fixture()
    untouched = copy.deepcopy(p)
    assert decide(p)["selected"] == "depth4"  # Greater depth need not justify overhead.
    assert p == untouched
    cases.append("marginal-depth benefit, migration cost, and input immutability")
    p = fixture(); p["failure_rate_per_s"] = 0
    assert decide(p)["selected"] == "keep"
    cases.append("zero failure risk does not pay positive protection cost")
    p = fixture(); p["slack_s"] = 3
    assert decide(p)["selected"] == "keep"
    cases.append("slack absorbs all sampled recovery delays")
    p = fixture(); p["profile_generation_valid"] = False
    assert decide(p)["action"] == "hold"
    cases.append("invalid generation retains only feasible existing residency")
    p["plans"][0]["feasible"] = False
    assert decide(p)["action"] == "mandatory_retirement"
    cases.append("budget contraction overrides profile-based hold")
    p = fixture()
    for q in p["plans"][1:]:
        q["foreground_delay_delta_s"] = [0, q["foreground_delay_delta_s"][1], 1]
    assert decide(p)["selected"] == "keep"
    cases.append("overlapping uncertainty prevents unsupported switching")
    p = fixture(); p["plans"][1]["foreground_delay_delta_s"] = [0.2, 0.2, 0.2]
    assert decide(p)["selected"] == "depth8"
    cases.append("writeback cost changes the chosen plan")
    p = fixture(); p["plans"][1]["snapshot_id"] = "different"
    try:
        decide(p)
    except ValueError:
        pass
    else:
        raise AssertionError("mixed candidate snapshots accepted")
    cases.append("mixed-snapshot comparisons rejected")
    p = fixture(); p["conditional_failure_samples"][0]["weight"] = 0.7
    try:
        decide(p)
    except ValueError:
        pass
    else:
        raise AssertionError("unnormalized conditional weights accepted")
    cases.append("invalid conditional distribution rejected")
    return {"evidence_type": "synthetic_arithmetic_checks_only", "passed": len(cases),
            "checks": cases, "example_input": fixture(), "example_output": decide(fixture()),
            "not_validated": ["profiles/calibration", "optimality/WCT", "concurrent allocator",
                              "fault/lease correctness", "GPU kernels", "foreground overhead"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_check:
        result = self_check()
    elif args.input:
        result = decide(json.loads(args.input.read_text()))
    else:
        parser.error("provide --input or --self-check")
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
        print(f"Wrote {args.output}")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
