from __future__ import annotations

from copy import deepcopy

import pytest

from moonkvsim.aegiskv.paper_sweep_cost_statistics import (
    AEGISKV,
    MOONCAKE,
    POINTS,
    build_sweep_cost_statistics,
)


def _fixture():
    records = {f"s{i}": {"workflow_id": f"w{i}", "prompt_tokens": 100} for i in range(8)}
    cells = []
    for f, c in sorted(POINTS):
        for seed in range(5):
            systems = {}
            for system in (MOONCAKE, AEGISKV):
                wct = {f"w{i}": 100 for i in range(160)}
                if system == AEGISKV and (f, c, seed) == (8, 16, 2):
                    wct["w0"] = 200
                systems[system] = {"run": {
                    "metrics": {"workflow_completion_time_ns": {"by_workflow_id": wct},
                                "resource_cost": {
                                    "transfer_byte_conservation_valid": True,
                                    "cause_bytes": {"PEER_PROTECTION": (
                                                        1000 if system == AEGISKV else 0),
                                                    "STORE_PROTECTION": 500,
                                                    "STORE_RECOVERY": 100},
                                }},
                    "failure_focus_spans": [{
                        "span_id": f"s{i}", "workflow_id": f"w{i}",
                        "recovery_normal_hbm_local_tokens": 10,
                        "restored_peer_tokens": 20 if system == AEGISKV else 0,
                        "restored_store_tokens": 30 if system == AEGISKV else 50,
                        "recompute_tokens": 40,
                    } for i in range(f)],
                    "raw_evidence": {"sha256": "a" * 64 if system == AEGISKV else "b" * 64},
                }}
            cells.append({"failure_count": f, "workflow_concurrency": c,
                          "seed": seed, "systems": systems})
    return cells, records


def test_complete_cost_diagnostics_retain_null_and_adverse_cases():
    cells, records = _fixture()
    result = build_sweep_cost_statistics(list(reversed(cells)), records)
    assert result == build_sweep_cost_statistics(cells, records)
    assert len(result["points"]) == 7
    worst = result["five_lowest_paired_effects"][0]
    assert (worst["seed"], worst["failure_count"], worst["workflow_id"]) == (2, 8, "w0")
    assert worst["gain_percent_exact"] == {"numerator": -100, "denominator": 1}
    assert result["five_lowest_paired_effects"][1]["gain_percent_exact"]["numerator"] == 0
    point = result["points"][0]
    assert point["protection_transferred_bytes"][AEGISKV]["per_seed"][0]["rounded_value"] == 1500
    # Normal local HBM is deliberately excluded; overlapping available copies
    # must not inflate the mutually exclusive selected recovery token counts.
    assert point["restored_prompt_percent"][AEGISKV]["per_seed"][0]["exact"] == {
        "numerator": 50, "denominator": 1,
    }
    assert point["restored_prompt_percent"][MOONCAKE]["per_seed"][0]["exact"] == {
        "numerator": 50, "denominator": 1,
    }


@pytest.mark.parametrize("change,match", [
    ("missing", "35-cell"), ("duplicate", "35-cell"), ("tokens", "conserve"),
    ("focus", "focus population"), ("workflow", "frozen workload"),
    ("cost", "nonnegative"), ("wct", "WCT population"),
])
def test_cost_diagnostics_reject_incomplete_or_inconsistent_inputs(change, match):
    cells, records = _fixture()
    run = cells[0]["systems"][AEGISKV]["run"]
    if change == "missing":
        cells.pop()
    elif change == "duplicate":
        cells[-1] = deepcopy(cells[0])
    elif change == "tokens":
        run["failure_focus_spans"][0]["restored_peer_tokens"] += 1
    elif change == "focus":
        run["failure_focus_spans"].append(deepcopy(run["failure_focus_spans"][0]))
    elif change == "workflow":
        run["failure_focus_spans"][0]["workflow_id"] = "w2"
    elif change == "cost":
        run["metrics"]["resource_cost"]["cause_bytes"]["PEER_PROTECTION"] = -1
    else:
        run["metrics"]["workflow_completion_time_ns"]["by_workflow_id"]["w0"] = 0
    with pytest.raises(ValueError, match=match):
        build_sweep_cost_statistics(cells, records)
