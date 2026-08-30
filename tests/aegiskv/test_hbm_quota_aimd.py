from __future__ import annotations

import json
from decimal import Decimal

import pytest

from moonkvsim.aegiskv.hbm_quota_aimd import (
    AIMDAction,
    AIMDParameters,
    AIMDTargetState,
    HBMQuotaAIMD,
)
from moonkvsim.common.hash import canonical_json_bytes, sha256_json


def parameters() -> AIMDParameters:
    return AIMDParameters(
        minimum_fraction=Decimal("0.20"),
        maximum_fraction=Decimal("0.90"),
        multiplicative_decrease=Decimal("0.5"),
        additive_increase=Decimal("0.1"),
        stable_window_count=2,
    )


def state(*, fraction: str = "0.8", stable_windows: int = 0) -> AIMDTargetState:
    return AIMDTargetState(
        target_id="engine-dp1",
        peer_hbm_capacity_bytes=1_000,
        protection_fraction=Decimal(fraction),
        stable_windows=stable_windows,
    )


def test_pressure_uses_exact_multiplicative_decrease_and_gates_admission() -> None:
    decision = HBMQuotaAIMD(parameters()).update(
        state(),
        foreground_pressure=True,
        current_protection_bytes=700,
        timestamp_ns=10,
    )

    assert decision.action is AIMDAction.MULTIPLICATIVE_DECREASE
    assert decision.next_state.protection_fraction == Decimal("0.40")
    assert decision.next_state.stable_windows == 0
    assert decision.quota_bytes == 400
    assert decision.bytes_to_reclaim == 300
    assert decision.admission_blocked is True
    assert decision.canonical_fields()["controller_scope"] == "PEER_HBM_QUOTA_ONLY"
    assert "STORE_DRAM" not in decision.to_json_bytes().decode()


def test_stability_counter_then_exact_additive_increase() -> None:
    controller = HBMQuotaAIMD(parameters())
    first = controller.update(
        state(fraction="0.4"),
        foreground_pressure=False,
        current_protection_bytes=300,
        timestamp_ns=10,
    )
    second = controller.update(
        first.next_state,
        foreground_pressure=False,
        current_protection_bytes=300,
        timestamp_ns=20,
    )

    assert first.action is AIMDAction.STABLE_WINDOW
    assert first.next_state.protection_fraction == Decimal("0.4")
    assert first.next_state.stable_windows == 1
    assert second.action is AIMDAction.ADDITIVE_INCREASE
    assert second.next_state.protection_fraction == Decimal("0.5")
    assert second.next_state.stable_windows == 0
    assert second.quota_bytes == 500


def test_formula_clamps_to_minimum_and_maximum() -> None:
    controller = HBMQuotaAIMD(parameters())
    decrease = controller.update(
        state(fraction="0.3"),
        foreground_pressure=True,
        current_protection_bytes=200,
        timestamp_ns=1,
    )
    increase = controller.update(
        state(fraction="0.9", stable_windows=1),
        foreground_pressure=False,
        current_protection_bytes=800,
        timestamp_ns=1,
    )

    assert decrease.next_state.protection_fraction == Decimal("0.2")
    assert increase.next_state.protection_fraction == Decimal("0.9")


def test_decision_has_stable_canonical_json_and_fingerprint() -> None:
    controller = HBMQuotaAIMD(parameters())
    left = controller.update(
        state(),
        foreground_pressure=True,
        current_protection_bytes=700,
        timestamp_ns=10,
    )
    right = controller.update(
        state(),
        foreground_pressure=True,
        current_protection_bytes=700,
        timestamp_ns=10,
    )

    assert left.to_json_bytes() == right.to_json_bytes()
    document = json.loads(left.to_json_bytes())
    assert left.to_json_bytes() == canonical_json_bytes(document) + b"\n"
    payload = {key: value for key, value in document.items() if key != "fingerprint"}
    assert document["fingerprint"] == sha256_json(payload)


def test_invalid_or_non_monotonic_control_windows_fail_closed() -> None:
    controller = HBMQuotaAIMD(parameters())
    updated = controller.update(
        state(),
        foreground_pressure=False,
        current_protection_bytes=100,
        timestamp_ns=5,
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        controller.update(
            updated.next_state,
            foreground_pressure=False,
            current_protection_bytes=100,
            timestamp_ns=5,
        )
    with pytest.raises(ValueError, match="fit target capacity"):
        controller.update(
            state(),
            foreground_pressure=True,
            current_protection_bytes=1_001,
            timestamp_ns=6,
        )
    with pytest.raises(ValueError, match="strictly between"):
        AIMDParameters(
            minimum_fraction=Decimal("0"),
            maximum_fraction=Decimal("1"),
            multiplicative_decrease=Decimal("1"),
            additive_increase=Decimal("0.1"),
            stable_window_count=2,
        )
