from copy import deepcopy

import pytest

from moonkvsim.aegiskv.paper_ablation_statistics import ARMS, build_ablation_statistics
from moonkvsim.aegiskv.paper_randomization import ADMISSION_POLICY
from moonkvsim.common.hash import sha256_json


def _cells():
    ids = [f"workflow-{index:03d}" for index in range(160)]
    cells = []
    for seed in range(5):
        order = ids[seed:] + ids[:seed]
        runs = {}
        for scenario in ("no_failure", "gpu_failure"):
            runs[scenario] = {}
            for arm in ARMS:
                # Baseline differences cancel in DiD; one affected workflow
                # has a known 160 ns ablation penalty (whole mean = 1 ns).
                wct = dict.fromkeys(ids, 1000 + (500 if arm != "full" else 0))
                if scenario == "gpu_failure":
                    wct[ids[0]] += 10 + (160 if arm != "full" else 0)
                runs[scenario][arm] = {
                    "workflow_admission": {
                        "order_policy": ADMISSION_POLICY, "seed": seed,
                        "realized_workflow_order": order,
                        "realized_workflow_order_sha256": sha256_json(order),
                    },
                    "randomization": {"workflow_admission_seed": seed, "peer_binding_seed": 0},
                    "wct_ns": wct, "failure_event_count": int(scenario == "gpu_failure"),
                    "focus_tokens": {"prompt": 100, "normal": 0, "peer": 0,
                                     "store": 0, "recompute": 100},
                    "protection_transferred_bytes": 0,
                }
        cells.append({"seed": seed, "focus_workflow_id": ids[0], "runs": runs})
    return cells


def test_ablation_did_cancels_baseline_and_does_not_filter_zero_hits_or_adverse_effects():
    result = build_ablation_statistics(_cells())
    assert result["status"] == "PASS"
    arm = result["arms"]["no_slack"]
    assert arm["focus_did_ns"]["mean"]["rounded_half_even"] == 160
    assert arm["whole_mean_did_ns"]["mean"]["rounded_half_even"] == 1
    assert arm["restored_fraction_ppb"]["mean"]["rounded_half_even"] == 0
    assert arm["focus_did_ns"]["sample_count"] == 5


@pytest.mark.parametrize("corruption", ["missing_arm", "double_count_tokens", "missing_seed"])
def test_ablation_rejects_incomplete_or_nonconserving_evidence(corruption):
    cells = deepcopy(_cells())
    if corruption == "missing_arm":
        del cells[0]["runs"]["no_failure"]["no_aimd"]
    elif corruption == "double_count_tokens":
        cells[0]["runs"]["gpu_failure"]["full"]["focus_tokens"]["peer"] = 1
    else:
        cells.pop()
    with pytest.raises(ValueError):
        build_ablation_statistics(cells)
