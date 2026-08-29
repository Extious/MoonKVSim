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

    assert resource.cancel("r0") == first
    replacement = resource.reserve(
        ready_ns=0, duration_ns=7, reservation_id="r3", cause="MOONCAKE_PUT"
    )
    assert (replacement.lane, replacement.start_ns) == (0, 0)


def test_rate_resource_has_deterministic_equal_share() -> None:
    resource = RateResource(resource_id="nic-0.tx", capacity_bytes_per_second=100.0)
    assert resource.equal_fair_share({"flow-b", "flow-a"}) == {
        "flow-a": 50.0,
        "flow-b": 50.0,
    }
