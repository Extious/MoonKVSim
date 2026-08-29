from __future__ import annotations

import json

import pytest

from moonkvsim.integration.vllm.router import (
    CacheHitSignal,
    DPReplicaSnapshot,
    DPRouter,
    NoHealthyReplicaError,
    RoutePolicy,
    RouterError,
    StaleRouteAuthorityError,
)


def replica(
    rank: int,
    *,
    healthy: bool = True,
    waiting: int = 0,
    running: int = 0,
    queued_tokens: int = 0,
    scheduler_id: str | None = None,
) -> DPReplicaSnapshot:
    return DPReplicaSnapshot(
        replica_id=f"dp-{rank}",
        dp_rank=rank,
        scheduler_id=scheduler_id or f"scheduler-{rank}",
        healthy=healthy,
        waiting_requests=waiting,
        running_requests=running,
        queued_tokens=queued_tokens,
        observed_at_ns=100,
    )


def cache_signal(
    request_id: str,
    rank: int,
    cached_tokens: int,
) -> CacheHitSignal:
    return CacheHitSignal(
        request_id=request_id,
        replica_id=f"dp-{rank}",
        lookup_id=f"lookup-{request_id}-{rank}",
        directory_snapshot_fingerprint="a" * 64,
        requested_prefix_tokens=128,
        compatible_cached_tokens=cached_tokens,
    )


def test_round_robin_is_stable_across_input_order_and_records_scores() -> None:
    replicas = (replica(2), replica(0), replica(1))
    router = DPRouter(router_id="router-0", policy=RoutePolicy.ROUND_ROBIN)

    routes = [
        router.route(request_id=f"request-{index}", replicas=reversed(replicas))
        for index in range(4)
    ]

    assert [item.target_replica_id for item in routes] == ["dp-0", "dp-1", "dp-2", "dp-0"]
    assert all(item.route_version == 0 for item in routes)
    assert routes[0].selection_reason.startswith("round_robin")
    assert routes[0].tie_break_rule == "lexicographic_dp_rank_then_replica_id"
    assert [score.replica.dp_rank for score in routes[0].candidate_scores] == [0, 1, 2]
    assert [score.selection_key for score in routes[0].candidate_scores] == [
        (0,),
        (1,),
        (2,),
    ]

    identical = DPRouter(router_id="router-0", policy=RoutePolicy.ROUND_ROBIN).route(
        request_id="request-0",
        replicas=replicas,
    )
    assert identical.to_json_bytes() == routes[0].to_json_bytes()
    assert json.loads(identical.to_json_bytes())["route_version"] == 0


def test_least_loaded_uses_independent_scheduler_snapshots_and_deterministic_tie_break() -> None:
    candidates = (
        replica(2, queued_tokens=50, waiting=1, running=1),
        replica(0, queued_tokens=100, waiting=0, running=0),
        replica(1, queued_tokens=50, waiting=1, running=1),
    )
    router = DPRouter(router_id="router-0", policy=RoutePolicy.LEAST_LOADED)

    route = router.route(request_id="request-0", replicas=candidates)

    assert route.target_replica_id == "dp-1"
    assert route.target_scheduler_id == "scheduler-1"
    assert route.selection_reason.startswith("least_loaded")
    assert route.candidate_scores[1].selection_key == (50, 1, 1)
    assert candidates[0].queued_tokens == 50

    duplicate_scheduler = (
        replica(0, scheduler_id="one-scheduler"),
        replica(1, scheduler_id="one-scheduler"),
    )
    with pytest.raises(ValueError, match="unique scheduler_id"):
        DPRouter(router_id="router-1", policy=RoutePolicy.LEAST_LOADED).route(
            request_id="request-1",
            replicas=duplicate_scheduler,
        )


def test_cache_aware_route_uses_explicit_directory_hits_without_owning_store() -> None:
    replicas = (
        replica(0, queued_tokens=0),
        replica(1, queued_tokens=1_000),
    )
    signals = (
        cache_signal("request-0", 1, 64),
        cache_signal("request-0", 0, 0),
    )
    router = DPRouter(router_id="router-0", policy=RoutePolicy.CACHE_AWARE)

    route = router.route(
        request_id="request-0",
        replicas=replicas,
        cache_hits=signals,
    )

    assert route.target_replica_id == "dp-1"
    assert route.selection_reason.startswith("cache_hit")
    selected = next(
        score for score in route.candidate_scores if score.replica.replica_id == "dp-1"
    )
    assert selected.cache_signal is not None
    assert selected.cache_signal.compatible_cached_tokens == 64
    assert selected.selection_key == (-64, 1_000, 0, 0)
    assert b"external_store_directory_snapshot" in route.to_json_bytes()
    assert not hasattr(router, "store")

    with pytest.raises(RouterError, match="explicit directory signal"):
        DPRouter(router_id="router-1", policy=RoutePolicy.CACHE_AWARE).route(
            request_id="request-0",
            replicas=replicas,
            cache_hits=(cache_signal("request-0", 0, 0),),
        )


def test_reroute_excludes_old_and_failed_targets_and_fences_old_authority() -> None:
    router = DPRouter(router_id="router-0", policy=RoutePolicy.LEAST_LOADED)
    initial = router.route(
        request_id="request-0",
        replicas=(
            replica(0, queued_tokens=0),
            replica(1, queued_tokens=10),
            replica(2, queued_tokens=20),
        ),
    )
    assert initial.target_replica_id == "dp-0"
    assert router.is_authoritative(initial)

    rerouted = router.reroute(
        initial,
        replicas=(
            replica(0, healthy=False),
            replica(1, healthy=False),
            replica(2, queued_tokens=20),
        ),
        failed_replica_ids=("dp-1", "dp-0"),
    )

    assert rerouted.route_version == 1
    assert rerouted.target_replica_id == "dp-2"
    assert rerouted.excluded_replica_ids == ("dp-0", "dp-1")
    assert rerouted.previous_authority_fingerprint == initial.fingerprint
    assert rerouted.fenced_route_version == 0
    assert rerouted.fenced_target_replica_id == "dp-0"
    assert not router.is_authoritative(initial)
    assert router.is_authoritative(rerouted)
    with pytest.raises(StaleRouteAuthorityError, match="stale or fenced"):
        router.require_authority(initial)
    with pytest.raises(StaleRouteAuthorityError, match="version or target"):
        router.require_route(
            "request-0",
            route_version=0,
            target_replica_id="dp-0",
        )
    assert (
        router.require_route(
            "request-0",
            route_version=1,
            target_replica_id="dp-2",
        )
        is rerouted
    )

    with pytest.raises(StaleRouteAuthorityError, match="latest"):
        router.reroute(initial, replicas=(replica(2),))


def test_no_healthy_target_fails_closed_without_publishing_authority() -> None:
    router = DPRouter(router_id="router-0", policy=RoutePolicy.LEAST_LOADED)

    with pytest.raises(NoHealthyReplicaError, match="no healthy"):
        router.route(
            request_id="request-0",
            replicas=(replica(0, healthy=False), replica(1, healthy=False)),
        )
    with pytest.raises(RouterError, match="no route authority"):
        router.current_authority("request-0")


def test_failed_reroute_fences_an_unsafe_old_target_without_version_advance() -> None:
    router = DPRouter(router_id="router-0", policy=RoutePolicy.LEAST_LOADED)
    initial = router.route(request_id="request-0", replicas=(replica(0),))

    with pytest.raises(NoHealthyReplicaError, match="no healthy"):
        router.reroute(
            initial,
            replicas=(replica(0, healthy=False),),
            failed_replica_ids=("dp-0",),
        )

    assert router.current_authority("request-0") is initial
    assert not router.is_authoritative(initial)
    with pytest.raises(StaleRouteAuthorityError, match="stale or fenced"):
        router.require_authority(initial)


def test_reroute_validation_failure_does_not_publish_a_partial_version() -> None:
    router = DPRouter(router_id="router-0", policy=RoutePolicy.CACHE_AWARE)
    replicas = (replica(0), replica(1))
    initial = router.route(
        request_id="request-0",
        replicas=replicas,
        cache_hits=(
            cache_signal("request-0", 0, 64),
            cache_signal("request-0", 1, 0),
        ),
    )

    with pytest.raises(RouterError, match="explicit directory signal"):
        router.reroute(initial, replicas=replicas, cache_hits=())

    assert router.current_authority("request-0") is initial
    assert router.current_authority("request-0").route_version == 0
    assert router.is_authoritative(initial)


def test_cache_aware_json_is_deterministic_for_reordered_inputs() -> None:
    replicas = (replica(0, queued_tokens=20), replica(1, queued_tokens=10))
    signals = (
        cache_signal("request-0", 0, 32),
        cache_signal("request-0", 1, 32),
    )

    first = DPRouter(router_id="router-0", policy=RoutePolicy.CACHE_AWARE).route(
        request_id="request-0",
        replicas=replicas,
        cache_hits=signals,
    )
    second = DPRouter(router_id="router-0", policy=RoutePolicy.CACHE_AWARE).route(
        request_id="request-0",
        replicas=reversed(replicas),
        cache_hits=reversed(signals),
    )

    assert first.target_replica_id == "dp-1"
    assert first.to_json_bytes() == second.to_json_bytes()
    assert first.fingerprint == second.fingerprint
