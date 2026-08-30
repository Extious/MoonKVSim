import pytest

from moonkvsim.simulation.resource import ConcurrencyResource, RateResource


def test_concurrency_calendar_finds_first_stable_lane() -> None:
    resource = ConcurrencyResource(resource_id="gpu-0.copy", lanes=2)
    first = resource.reserve(
        ready_ns=0, duration_ns=10, reservation_id="r0", cause="MOONCAKE_PUT"
    )
    second = resource.reserve(
        ready_ns=0, duration_ns=10, reservation_id="r1", cause="MOONCAKE_GET"
    )
    third = resource.reserve(
        ready_ns=0, duration_ns=5, reservation_id="r2", cause="RECOVERY"
    )

    assert (first.lane, first.start_ns, first.end_ns) == (0, 0, 10)
    assert (second.lane, second.start_ns, second.end_ns) == (1, 0, 10)
    assert (third.lane, third.start_ns, third.end_ns) == (0, 10, 15)

    assert resource.reservation("r0") is first
    assert resource.reservation("missing") is None
    lane_zero_snapshot = resource.reservations_on_lane(0)
    assert lane_zero_snapshot == (first, third)
    assert resource.reservations_on_lane(1) == (second,)

    assert resource.cancel("r0") == first
    assert resource.reservation("r0") is None
    assert lane_zero_snapshot == (first, third)
    assert resource.reservations_on_lane(0) == (third,)
    replacement = resource.reserve(
        ready_ns=0, duration_ns=7, reservation_id="r3", cause="MOONCAKE_PUT"
    )
    assert (replacement.lane, replacement.start_ns) == (0, 0)


def test_concurrency_calendar_rejects_invalid_lane_views() -> None:
    resource = ConcurrencyResource(resource_id="gpu-0.copy", lanes=2)

    with pytest.raises(TypeError, match="lane must be an integer"):
        resource.reservations_on_lane(True)
    with pytest.raises(IndexError, match="outside"):
        resource.reservations_on_lane(-1)
    with pytest.raises(IndexError, match="outside"):
        resource.reservations_on_lane(2)


def test_cancel_from_preserves_elapsed_prefix_and_releases_future_suffix() -> None:
    resource = ConcurrencyResource(resource_id="gpu-0.copy", lanes=1)
    planned = resource.reserve(
        ready_ns=10,
        duration_ns=20,
        reservation_id="r0",
        cause="AEGIS_PEER_PROTECTION",
    )
    queued = resource.reserve(
        ready_ns=10,
        duration_ns=10,
        reservation_id="r1",
        cause="AEGIS_PEER_PROTECTION",
    )

    assert resource.cancel_from("r0", timestamp_ns=18) == planned
    elapsed = resource.reservation("r0")
    assert elapsed is not None
    assert (elapsed.start_ns, elapsed.end_ns) == (10, 18)
    assert resource.reservation("r1") == queued

    replacement = resource.reserve(
        ready_ns=18,
        duration_ns=5,
        reservation_id="r2",
        cause="RECOVERY",
    )
    assert (replacement.start_ns, replacement.end_ns) == (18, 23)
    assert resource.cancel_from("missing", timestamp_ns=18) is None


def test_rate_resource_has_deterministic_equal_share() -> None:
    resource = RateResource(resource_id="nic-0.tx", capacity_bytes_per_second=100.0)
    assert resource.equal_fair_share({"flow-b", "flow-a"}) == {
        "flow-a": 50.0,
        "flow-b": 50.0,
    }
