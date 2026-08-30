import math
from dataclasses import replace

import pytest

from moonkvsim.simulation.network import ActiveFlow, FlowContentionModel
from moonkvsim.simulation.resource import RateResource


def flow(flow_id: str, *, size: int = 100, path: tuple[str, ...] = ("nic",)) -> ActiveFlow:
    return ActiveFlow(
        flow_id=flow_id,
        transfer_id=f"transfer-{flow_id}",
        slice_id=f"slice-{flow_id}",
        cause="MOONCAKE_PUT",
        path_resource_ids=path,
        payload_bytes=size,
        remaining_bytes=float(size),
    )


def test_equal_flows_share_a_bottleneck_and_conserve_bytes() -> None:
    model = FlowContentionModel([RateResource("nic", 100.0)])
    model.add_flow(flow("a"), now_ns=0)
    model.add_flow(flow("b"), now_ns=0)

    assert model.rates() == {"a": 50.0, "b": 50.0}
    assert model.next_completion_ns() == 2_000_000_000

    completed = model.complete_flows(now_ns=2_000_000_000)
    assert tuple(item.flow_id for item in completed) == ("a", "b")
    assert sum(interval.transferred_bytes for interval in model.intervals) == 200.0


def test_multi_resource_path_is_limited_by_shared_bottleneck() -> None:
    model = FlowContentionModel(
        [RateResource("pcie", 200.0), RateResource("nic", 100.0)]
    )
    model.add_flow(flow("network", path=("pcie", "nic")), now_ns=0)
    model.add_flow(flow("local", path=("pcie",)), now_ns=0)

    assert model.rates() == {"local": 100.0, "network": 100.0}


def test_cancel_reports_transferred_and_aborted_bytes() -> None:
    model = FlowContentionModel([RateResource("nic", 100.0)])
    model.add_flow(flow("a"), now_ns=0)

    canceled = model.cancel_flow("a", now_ns=500_000_000, reason="GPU_FAILURE")

    assert canceled.transferred_bytes == pytest.approx(50.0)
    assert canceled.aborted_bytes == pytest.approx(50.0)
    assert model.next_completion_ns() is None


def test_skipping_a_completion_event_fails_closed() -> None:
    model = FlowContentionModel([RateResource("nic", 100.0)])
    model.add_flow(flow("a"), now_ns=0)

    with pytest.raises(RuntimeError, match="completion event"):
        model.advance_to(2_000_000_000)


def test_many_flows_at_large_rate_trim_only_float_roundoff() -> None:
    capacity = 25_000_000_000.0
    model = FlowContentionModel([RateResource("nic", capacity)])

    for index in range(39):
        model.add_flow(flow(f"flow-{index:02d}"), now_ns=0)

    assert len(model.flows) == 39
    assert math.fsum(model.rates().values()) <= capacity
    assert math.fsum(model.rates().values()) == pytest.approx(capacity)

    first = model.flows["flow-00"]
    first.allocated_rate_bytes_per_second += math.ulp(capacity) * 100
    with pytest.raises(RuntimeError, match="rate capacity exceeded on nic"):
        model._assert_rate_invariants()


def test_later_bottleneck_progresses_past_unrelated_saturated_resource() -> None:
    capacity = 25_000_000_000.0
    model = FlowContentionModel(
        [RateResource("small", 1.0), RateResource("large", capacity)]
    )
    model.add_flow(flow("small-only", path=("small",)), now_ns=0)

    for index in range(11):
        model.add_flow(flow(f"large-{index:02d}", path=("large",)), now_ns=0)

    rates = model.rates()
    assert rates["small-only"] == 1.0
    assert math.fsum(rates[f"large-{index:02d}"] for index in range(11)) <= capacity
    assert math.fsum(rates[f"large-{index:02d}"] for index in range(11)) == pytest.approx(
        capacity
    )


def test_add_flow_recompute_failure_restores_previous_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FlowContentionModel([RateResource("nic", 100.0)])
    model.add_flow(flow("existing"), now_ns=0)
    rates_before = model.rates()

    def fail_recompute() -> None:
        for active in model.flows.values():
            active.allocated_rate_bytes_per_second = 0.0
        raise RuntimeError("injected recompute failure")

    monkeypatch.setattr(model, "_recompute_rates", fail_recompute)
    rejected = flow("rejected")
    with pytest.raises(RuntimeError, match="injected recompute failure"):
        model.add_flow(rejected, now_ns=0)

    assert tuple(model.flows) == ("existing",)
    assert model.rates() == rates_before
    assert rejected.allocated_rate_bytes_per_second == 0.0


@pytest.mark.parametrize("capacity", [math.nan, math.inf, -math.inf])
def test_rate_resource_rejects_non_finite_capacity(capacity: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        RateResource("nic", capacity)


@pytest.mark.parametrize("weight", [math.nan, math.inf, -math.inf])
def test_active_flow_rejects_non_finite_weight(weight: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        replace(flow("bad-weight"), weight=weight)


def test_tiny_positive_rate_still_has_a_completion_timestamp() -> None:
    model = FlowContentionModel([RateResource("tiny", 1e-12)])
    model.add_flow(flow("tiny", size=1, path=("tiny",)), now_ns=0)

    completion_ns = model.next_completion_ns()
    assert completion_ns is not None
    assert completion_ns > 1_000_000_000


def test_smallest_positive_float_rate_completes_without_float_overflow() -> None:
    model = FlowContentionModel([RateResource("tiny", math.ulp(0.0))])
    model.add_flow(flow("tiny", size=1, path=("tiny",)), now_ns=0)

    completion_ns = model.next_completion_ns()
    assert completion_ns is not None
    assert tuple(
        item.flow_id for item in model.complete_flows(now_ns=completion_ns)
    ) == ("tiny",)


def test_rate_invariant_rejects_non_finite_mutated_flow_state() -> None:
    model = FlowContentionModel([RateResource("nic", 100.0)])
    model.add_flow(flow("mutated"), now_ns=0)
    model.flows["mutated"].allocated_rate_bytes_per_second = math.nan

    with pytest.raises(RuntimeError, match="invalid numeric state"):
        model._assert_rate_invariants()
