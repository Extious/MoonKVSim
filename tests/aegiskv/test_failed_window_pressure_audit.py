"""A failure label cannot excuse a missing healthy control-window decrease."""
from copy import deepcopy

import pytest

from moonkvsim.aegiskv.formal_algorithm_audit import (
    _pressure_cleared_by_failed_control_window,
)


def evidence():
    return {
        "aimd_events": [
            {"target_id": "gpu-0", "timestamp_ns": 30, "control_window_ns": 10},
            {"target_id": "gpu-1", "timestamp_ns": 50, "control_window_ns": 10},
        ],
        "failure_events": [{
            "event": "FAILURE_INJECT", "target_gpu_id": "gpu-0",
            "timestamp_ns": 35, "repair_completed_at_ns": 55,
        }],
        "gpu_hbm_timelines": {"gpu-0": [
            {"timestamp_ns": 35, "cause": "GPU_FAILURE_ALL_HBM_UNAVAILABLE",
             "capacity_bytes": 100, "accounts": {"UNAVAILABLE_CAPACITY": 100}},
            {"timestamp_ns": 55, "cause": "GPU_REPAIR_HBM_EMPTY_REUSABLE",
             "capacity_bytes": 100, "accounts": {"UNAVAILABLE_CAPACITY": 0}},
        ]},
    }


def test_pressure_cleared_in_a_proven_failed_window():
    assert _pressure_cleared_by_failed_control_window(evidence(), "gpu-0", 31)


@pytest.mark.parametrize("mutation", [
    "late_failure", "earlier_failure", "early_repair", "wrong_gpu",
    "missing_physical_loss", "partial_loss", "missing_physical_repair",
    "wrong_capacity", "ended_before_window", "missing_cadence", "missed_healthy_window",
])
def test_missing_md_requires_outage_and_physical_proof(mutation):
    data = deepcopy(evidence())
    failure = data["failure_events"][0]
    loss, repair = data["gpu_hbm_timelines"]["gpu-0"]
    if mutation == "late_failure":
        failure["timestamp_ns"] = loss["timestamp_ns"] = 41
    elif mutation == "earlier_failure":
        failure["timestamp_ns"] = loss["timestamp_ns"] = 29
    elif mutation == "early_repair":
        failure["repair_completed_at_ns"] = repair["timestamp_ns"] = 39
    elif mutation == "wrong_gpu":
        failure["target_gpu_id"] = "gpu-1"
    elif mutation == "missing_physical_loss":
        loss["cause"] = "TEST"
    elif mutation == "partial_loss":
        loss["accounts"]["UNAVAILABLE_CAPACITY"] = 99
    elif mutation == "missing_physical_repair":
        repair["cause"] = "TEST"
    elif mutation == "wrong_capacity":
        repair["capacity_bytes"] = 101
    elif mutation == "ended_before_window":
        data["aimd_events"].pop()
    elif mutation == "missing_cadence":
        data["aimd_events"][0].pop("control_window_ns")
    elif mutation == "missed_healthy_window":
        data["aimd_events"][0]["timestamp_ns"] = 20
    assert not _pressure_cleared_by_failed_control_window(data, "gpu-0", 31)
