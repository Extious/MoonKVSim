from copy import deepcopy

import pytest

from moonkvsim.aegiskv.paper_randomization import ADMISSION_POLICY
from moonkvsim.aegiskv.paper_timing_statistics import TIMING_MODELS, build_timing_statistics
from moonkvsim.common.hash import sha256_json


def _cells():
    ids = [f"workflow-{i}" for i in range(160)]
    cells = []
    for seed in range(5):
        order = ids[seed:] + ids[:seed]
        runs = {"no_failure": {}, "gpu_failure": {}}
        for beta, (aegis, control) in TIMING_MODELS.items():
            for scenario, arms in runs.items():
                for arm in (aegis, control):
                    wct = dict.fromkeys(ids, 1000 + beta + (500 if arm == aegis else 0))
                    if scenario == "gpu_failure":
                        wct[ids[0]] += 10 + (160 if arm == aegis else 0)
                    arms[arm] = {
                        "wct_ns": wct, "failure_event_count": int(scenario == "gpu_failure"),
                        "focus_tokens": {"prompt": 100, "normal": 0, "peer": 0,
                                         "store": 0, "recompute": 100},
                        "protection_transferred_bytes": 0,
                        "workflow_admission": {
                            "order_policy": ADMISSION_POLICY, "seed": seed,
                            "realized_workflow_order": order,
                            "realized_workflow_order_sha256": sha256_json(order),
                        },
                        "randomization": {"workflow_admission_seed": seed,
                                          "peer_binding_seed": 0},
                    }
        cells.append({"seed": seed, "focus_workflow_id": ids[0], "runs": runs})
    return cells


def test_timing_robustness_cancels_model_specific_baselines_and_keeps_adverse_effects():
    result = build_timing_statistics(_cells())
    assert len(result["seed_rows"]) == 15
    for model in result["models"].values():
        assert model["focus_did_ns"]["mean"]["rounded_half_even"] == 160
        assert model["whole_mean_did_ns"]["mean"]["rounded_half_even"] == 1
        assert model["focus_did_ns"]["sample_count"] == 5
    assert result["models"]["0"]["focus_did_relative_ppb"]["mean"]["rounded_half_even"] == (
        160_000_000
    )
    assert result["models"]["1000"]["focus_did_relative_ppb"]["mean"]["rounded_half_even"] == (
        80_000_000
    )


@pytest.mark.parametrize("corruption", ["missing_arm", "missing_seed", "double_count"])
def test_timing_robustness_rejects_incomplete_or_nonconserving_runs(corruption):
    cells = deepcopy(_cells())
    if corruption == "missing_arm":
        del cells[0]["runs"]["gpu_failure"]["store_only_serial_1000"]
    elif corruption == "missing_seed":
        cells.pop()
    else:
        cells[0]["runs"]["gpu_failure"]["full"]["focus_tokens"]["peer"] = 1
    with pytest.raises(ValueError):
        build_timing_statistics(cells)
