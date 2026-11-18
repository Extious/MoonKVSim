"""External, deterministic DP routing boundary for independent vLLM schedulers.

The Router consumes immutable health/queue snapshots and optional Store-directory
cache signals.  It neither owns Store state nor moves KV bytes, and it does not
model or infer vLLM's internal DP balancing.  This is E1 static semantics only,
not runtime or performance validation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from moonkvsim.common.hash import canonical_json_bytes, sha256_json

ROUTE_AUTHORITY_SCHEMA = "moonkvsim.vllm-route-authority.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _require_non_empty(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be non-empty and have no outer whitespace")


def _require_sha256(value: object, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256")


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


class RoutePolicy(StrEnum):
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    CACHE_AWARE = "cache_aware"


class RouterError(RuntimeError):
    """Base error for fail-closed route decisions."""


class NoHealthyReplicaError(RouterError):
    """Raised instead of falling back to an unhealthy or excluded target."""


class StaleRouteAuthorityError(RouterError):
    """Raised when an old target/version attempts to execute after reroute."""


@dataclass(frozen=True, slots=True)
class DPReplicaSnapshot:
    """External metrics for one DP replica and its independent scheduler."""

    replica_id: str
    dp_rank: int
    scheduler_id: str
    healthy: bool
    waiting_requests: int
    running_requests: int
    queued_tokens: int
    observed_at_ns: int

    def __post_init__(self) -> None:
        _require_non_empty(self.replica_id, "replica_id")
        _require_non_empty(self.scheduler_id, "scheduler_id")
        _require_non_negative_int(self.dp_rank, "dp_rank")
        if not isinstance(self.healthy, bool):
            raise TypeError("healthy must be boolean")
        _require_non_negative_int(self.waiting_requests, "waiting_requests")
        _require_non_negative_int(self.running_requests, "running_requests")
        _require_non_negative_int(self.queued_tokens, "queued_tokens")
        _require_non_negative_int(self.observed_at_ns, "observed_at_ns")

    def to_dict(self) -> dict[str, object]:
        return {
            "replica_id": self.replica_id,
            "dp_rank": self.dp_rank,
            "scheduler_id": self.scheduler_id,
            "healthy": self.healthy,
            "waiting_requests": self.waiting_requests,
            "running_requests": self.running_requests,
            "queued_tokens": self.queued_tokens,
            "observed_at_ns": self.observed_at_ns,
        }


@dataclass(frozen=True, slots=True)
class CacheHitSignal:
    """Read-only Store-directory lookup result supplied to a cache-aware route."""

    request_id: str
    replica_id: str
    lookup_id: str
    directory_snapshot_fingerprint: str
    requested_prefix_tokens: int
    compatible_cached_tokens: int

    def __post_init__(self) -> None:
        _require_non_empty(self.request_id, "request_id")
        _require_non_empty(self.replica_id, "replica_id")
        _require_non_empty(self.lookup_id, "lookup_id")
        _require_sha256(
            self.directory_snapshot_fingerprint,
            "directory_snapshot_fingerprint",
        )
        _require_non_negative_int(
            self.requested_prefix_tokens,
            "requested_prefix_tokens",
        )
        _require_non_negative_int(
            self.compatible_cached_tokens,
            "compatible_cached_tokens",
        )
        if self.compatible_cached_tokens > self.requested_prefix_tokens:
            raise ValueError("compatible cache tokens cannot exceed the requested prefix")

    @property
    def cache_hit(self) -> bool:
        return self.compatible_cached_tokens > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "source": "external_store_directory_snapshot",
            "request_id": self.request_id,
            "replica_id": self.replica_id,
            "lookup_id": self.lookup_id,
            "directory_snapshot_fingerprint": self.directory_snapshot_fingerprint,
            "requested_prefix_tokens": self.requested_prefix_tokens,
            "compatible_cached_tokens": self.compatible_cached_tokens,
            "cache_hit": self.cache_hit,
        }


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Complete audit record for one candidate, eligible or not."""

    replica: DPReplicaSnapshot
    explicitly_excluded: bool
    eligible: bool
    cache_signal: CacheHitSignal | None
    selection_key: tuple[int, ...] | None
    score_reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.replica, DPReplicaSnapshot):
            raise TypeError("replica must be a DPReplicaSnapshot")
        if not isinstance(self.explicitly_excluded, bool) or not isinstance(
            self.eligible, bool
        ):
            raise TypeError("candidate exclusion and eligibility flags must be boolean")
        if self.cache_signal is not None:
            if not isinstance(self.cache_signal, CacheHitSignal):
                raise TypeError("cache_signal must be a CacheHitSignal")
            if self.cache_signal.replica_id != self.replica.replica_id:
                raise ValueError("cache signal belongs to a different replica")
        _require_non_empty(self.score_reason, "score_reason")
        if self.eligible != (self.replica.healthy and not self.explicitly_excluded):
            raise ValueError("candidate eligibility must follow health and exclusion")
        if self.eligible:
            if not isinstance(self.selection_key, tuple):
                raise TypeError("eligible candidate selection key must be a tuple")
            if not self.selection_key:
                raise ValueError("eligible candidates require a selection key")
            for value in self.selection_key:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError("selection key entries must be integers")
        elif self.selection_key is not None:
            raise ValueError("ineligible candidates cannot carry a selection key")

    def to_dict(self) -> dict[str, object]:
        return {
            **self.replica.to_dict(),
            "explicitly_excluded": self.explicitly_excluded,
            "eligible": self.eligible,
            "cache_signal": (
                None if self.cache_signal is None else self.cache_signal.to_dict()
            ),
            "selection_key": (
                None if self.selection_key is None else list(self.selection_key)
            ),
            "score_reason": self.score_reason,
            "tie_break_key": [self.replica.dp_rank, self.replica.replica_id],
        }


@dataclass(frozen=True, slots=True)
class RouteAuthority:
    """Versioned authority for exactly one external DP target."""

    router_id: str
    request_id: str
    policy: RoutePolicy
    route_version: int
    target_replica_id: str
    target_dp_rank: int
    target_scheduler_id: str
    candidate_scores: tuple[CandidateScore, ...]
    excluded_replica_ids: tuple[str, ...]
    selection_reason: str
    tie_break_rule: str
    previous_authority_fingerprint: str | None = None
    fenced_route_version: int | None = None
    fenced_target_replica_id: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.router_id, "router_id")
        _require_non_empty(self.request_id, "request_id")
        if not isinstance(self.policy, RoutePolicy):
            raise TypeError("policy must be a RoutePolicy")
        _require_non_negative_int(self.route_version, "route_version")
        _require_non_empty(self.target_replica_id, "target_replica_id")
        _require_non_negative_int(self.target_dp_rank, "target_dp_rank")
        _require_non_empty(self.target_scheduler_id, "target_scheduler_id")
        _require_non_empty(self.selection_reason, "selection_reason")
        _require_non_empty(self.tie_break_rule, "tie_break_rule")
        if not isinstance(self.candidate_scores, tuple) or not self.candidate_scores:
            raise ValueError("candidate_scores must be a non-empty tuple")
        if any(not isinstance(item, CandidateScore) for item in self.candidate_scores):
            raise TypeError("candidate_scores must contain CandidateScore values")
        ordered_scores = tuple(
            sorted(
                self.candidate_scores,
                key=lambda item: (item.replica.dp_rank, item.replica.replica_id),
            )
        )
        if self.candidate_scores != ordered_scores:
            raise ValueError("candidate scores must use canonical DP-rank ordering")
        candidate_ids = [item.replica.replica_id for item in self.candidate_scores]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate score replica IDs must be unique")
        selected = [
            item
            for item in self.candidate_scores
            if item.replica.replica_id == self.target_replica_id
        ]
        if len(selected) != 1 or not selected[0].eligible:
            raise ValueError("target must identify one eligible candidate")
        for item in self.candidate_scores:
            if (
                item.cache_signal is not None
                and item.cache_signal.request_id != self.request_id
            ):
                raise ValueError("candidate cache signal belongs to a different request")
        eligible_scores = [item for item in self.candidate_scores if item.eligible]
        expected_selected = min(
            eligible_scores,
            key=lambda item: (
                item.selection_key,
                item.replica.dp_rank,
                item.replica.replica_id,
            ),
        )
        if selected[0].replica.replica_id != expected_selected.replica.replica_id:
            raise ValueError("target does not match the minimum recorded selection key")
        if (
            selected[0].replica.dp_rank != self.target_dp_rank
            or selected[0].replica.scheduler_id != self.target_scheduler_id
        ):
            raise ValueError("target rank/scheduler must match the selected replica")
        if self.excluded_replica_ids != tuple(sorted(set(self.excluded_replica_ids))):
            raise ValueError("excluded replica IDs must be sorted and unique")
        for replica_id in self.excluded_replica_ids:
            _require_non_empty(replica_id, "excluded_replica_id")
        reroute_fields = (
            self.previous_authority_fingerprint,
            self.fenced_route_version,
            self.fenced_target_replica_id,
        )
        if self.route_version == 0:
            if any(value is not None for value in reroute_fields):
                raise ValueError("initial route cannot declare a fenced predecessor")
        else:
            if self.previous_authority_fingerprint is None:
                raise ValueError("reroute requires previous authority fingerprint")
            _require_sha256(
                self.previous_authority_fingerprint,
                "previous_authority_fingerprint",
            )
            if self.fenced_route_version != self.route_version - 1:
                raise ValueError("reroute must fence exactly the previous route version")
            _require_non_empty(
                self.fenced_target_replica_id,
                "fenced_target_replica_id",
            )
            if self.fenced_target_replica_id not in self.excluded_replica_ids:
                raise ValueError("reroute must exclude its fenced previous target")

    def canonical_fields(self) -> dict[str, object]:
        return {
            "schema": ROUTE_AUTHORITY_SCHEMA,
            "router_id": self.router_id,
            "request_id": self.request_id,
            "policy": self.policy.value,
            "route_version": self.route_version,
            "target_replica_id": self.target_replica_id,
            "target_dp_rank": self.target_dp_rank,
            "target_scheduler_id": self.target_scheduler_id,
            "candidate_scores": [item.to_dict() for item in self.candidate_scores],
            "excluded_replica_ids": list(self.excluded_replica_ids),
            "selection_reason": self.selection_reason,
            "tie_break_rule": self.tie_break_rule,
            "previous_authority_fingerprint": self.previous_authority_fingerprint,
            "fenced_route_version": self.fenced_route_version,
            "fenced_target_replica_id": self.fenced_target_replica_id,
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        value = self.canonical_fields()
        value["fingerprint"] = self.fingerprint
        return value

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


class DPRouter:
    """Stateful authority registry around deterministic, external route scoring."""

    _TIE_BREAK_RULE = "lexicographic_dp_rank_then_replica_id"

    def __init__(self, *, router_id: str, policy: RoutePolicy) -> None:
        _require_non_empty(router_id, "router_id")
        if not isinstance(policy, RoutePolicy):
            raise TypeError("policy must be a RoutePolicy")
        self._router_id = router_id
        self._policy = policy
        self._current_by_request: dict[str, RouteAuthority] = {}
        self._fenced_fingerprints: set[str] = set()
        self._round_robin_cursor = 0

    @property
    def router_id(self) -> str:
        return self._router_id

    @property
    def policy(self) -> RoutePolicy:
        return self._policy

    def route(
        self,
        *,
        request_id: str,
        replicas: Iterable[DPReplicaSnapshot],
        cache_hits: Iterable[CacheHitSignal] = (),
    ) -> RouteAuthority:
        """Create the only valid initial authority, always at route version zero."""

        _require_non_empty(request_id, "request_id")
        if request_id in self._current_by_request:
            raise RouterError("request already has a route authority; use reroute")
        authority = self._build_authority(
            request_id=request_id,
            route_version=0,
            replicas=replicas,
            cache_hits=cache_hits,
            excluded_replica_ids=(),
            previous=None,
        )
        self._current_by_request[request_id] = authority
        return authority

    def reroute(
        self,
        current: RouteAuthority,
        *,
        replicas: Iterable[DPReplicaSnapshot],
        failed_replica_ids: Iterable[str] = (),
        cache_hits: Iterable[CacheHitSignal] = (),
    ) -> RouteAuthority:
        """Fence the old target and publish version+1 only after selection succeeds."""

        latest = self._current_by_request.get(current.request_id)
        if latest is None or latest.fingerprint != current.fingerprint:
            raise StaleRouteAuthorityError("reroute requires the latest route authority")
        failures = tuple(sorted(set(failed_replica_ids)))
        for replica_id in failures:
            _require_non_empty(replica_id, "failed_replica_id")
        excluded = tuple(sorted(set(failures) | {current.target_replica_id}))
        replica_tuple = tuple(replicas)
        try:
            authority = self._build_authority(
                request_id=current.request_id,
                route_version=current.route_version + 1,
                replicas=replica_tuple,
                cache_hits=cache_hits,
                excluded_replica_ids=excluded,
                previous=current,
            )
        except RouterError:
            current_snapshot = next(
                (
                    item
                    for item in replica_tuple
                    if item.replica_id == current.target_replica_id
                ),
                None,
            )
            if (
                current.target_replica_id in failures
                or current_snapshot is None
                or not current_snapshot.healthy
            ):
                self._fenced_fingerprints.add(current.fingerprint)
            raise
        self._fenced_fingerprints.add(current.fingerprint)
        self._current_by_request[current.request_id] = authority
        return authority

    def current_authority(self, request_id: str) -> RouteAuthority:
        authority = self._current_by_request.get(request_id)
        if authority is None:
            raise RouterError("request has no route authority")
        return authority

    def is_authoritative(self, authority: RouteAuthority) -> bool:
        latest = self._current_by_request.get(authority.request_id)
        return (
            latest is not None
            and latest.fingerprint == authority.fingerprint
            and authority.fingerprint not in self._fenced_fingerprints
        )

    def require_authority(self, authority: RouteAuthority) -> None:
        """Reject a stale version/target at the scheduler execution boundary."""

        if not self.is_authoritative(authority):
            raise StaleRouteAuthorityError("route authority is stale or fenced")

    def require_route(
        self,
        request_id: str,
        *,
        route_version: int,
        target_replica_id: str,
    ) -> RouteAuthority:
        """Validate compact request metadata before admitting it to a scheduler."""

        _require_non_negative_int(route_version, "route_version")
        _require_non_empty(target_replica_id, "target_replica_id")
        authority = self.current_authority(request_id)
        if (
            authority.route_version != route_version
            or authority.target_replica_id != target_replica_id
        ):
            raise StaleRouteAuthorityError("route version or target is stale")
        self.require_authority(authority)
        return authority

    def _build_authority(
        self,
        *,
        request_id: str,
        route_version: int,
        replicas: Iterable[DPReplicaSnapshot],
        cache_hits: Iterable[CacheHitSignal],
        excluded_replica_ids: tuple[str, ...],
        previous: RouteAuthority | None,
    ) -> RouteAuthority:
        replica_tuple = self._normalize_replicas(replicas)
        cache_by_replica = self._normalize_cache_hits(
            request_id=request_id,
            replicas=replica_tuple,
            cache_hits=cache_hits,
        )
        excluded = set(excluded_replica_ids)
        eligible = [
            item
            for item in replica_tuple
            if item.healthy and item.replica_id not in excluded
        ]
        if not eligible:
            raise NoHealthyReplicaError("no healthy, non-excluded DP target")
        if self.policy is RoutePolicy.CACHE_AWARE:
            missing = sorted(
                item.replica_id
                for item in eligible
                if item.replica_id not in cache_by_replica
            )
            if missing:
                raise RouterError(
                    "cache-aware routing requires an explicit directory signal for "
                    + ", ".join(missing)
                )

        round_robin_index: dict[str, int] = {}
        if self.policy is RoutePolicy.ROUND_ROBIN:
            chosen_slot = self._round_robin_cursor % len(eligible)
            for index, replica in enumerate(eligible):
                round_robin_index[replica.replica_id] = (
                    index - chosen_slot
                ) % len(eligible)

        scored = tuple(
            self._score_candidate(
                replica=item,
                explicitly_excluded=item.replica_id in excluded,
                cache_signal=cache_by_replica.get(item.replica_id),
                round_robin_distance=round_robin_index.get(item.replica_id),
            )
            for item in replica_tuple
        )
        selectable = [item for item in scored if item.eligible]
        selected = min(
            selectable,
            key=lambda item: (
                item.selection_key,
                item.replica.dp_rank,
                item.replica.replica_id,
            ),
        )
        reason = self._selection_reason(selected, selectable)
        authority = RouteAuthority(
            router_id=self.router_id,
            request_id=request_id,
            policy=self.policy,
            route_version=route_version,
            target_replica_id=selected.replica.replica_id,
            target_dp_rank=selected.replica.dp_rank,
            target_scheduler_id=selected.replica.scheduler_id,
            candidate_scores=scored,
            excluded_replica_ids=tuple(sorted(excluded)),
            selection_reason=reason,
            tie_break_rule=self._TIE_BREAK_RULE,
            previous_authority_fingerprint=(
                None if previous is None else previous.fingerprint
            ),
            fenced_route_version=(None if previous is None else previous.route_version),
            fenced_target_replica_id=(
                None if previous is None else previous.target_replica_id
            ),
        )
        if self.policy is RoutePolicy.ROUND_ROBIN:
            self._round_robin_cursor += 1
        return authority

    def _normalize_replicas(
        self,
        replicas: Iterable[DPReplicaSnapshot],
    ) -> tuple[DPReplicaSnapshot, ...]:
        supplied = tuple(replicas)
        if not supplied:
            raise NoHealthyReplicaError("no DP replicas were supplied")
        if any(not isinstance(item, DPReplicaSnapshot) for item in supplied):
            raise TypeError("replicas must contain DPReplicaSnapshot values")
        result = tuple(
            sorted(supplied, key=lambda item: (item.dp_rank, item.replica_id))
        )
        for field_name, values in (
            ("replica_id", [item.replica_id for item in result]),
            ("dp_rank", [item.dp_rank for item in result]),
            ("scheduler_id", [item.scheduler_id for item in result]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"DP replica snapshots require unique {field_name} values")
        return result

    def _normalize_cache_hits(
        self,
        *,
        request_id: str,
        replicas: tuple[DPReplicaSnapshot, ...],
        cache_hits: Iterable[CacheHitSignal],
    ) -> dict[str, CacheHitSignal]:
        signals = tuple(cache_hits)
        if self.policy is not RoutePolicy.CACHE_AWARE and signals:
            raise RouterError("cache signals may only be supplied to cache-aware routing")
        if any(not isinstance(item, CacheHitSignal) for item in signals):
            raise TypeError("cache_hits must contain CacheHitSignal values")
        replica_ids = {item.replica_id for item in replicas}
        result: dict[str, CacheHitSignal] = {}
        for signal in signals:
            if signal.request_id != request_id:
                raise ValueError("cache signal belongs to a different request")
            if signal.replica_id not in replica_ids:
                raise ValueError("cache signal references an unknown DP replica")
            if signal.replica_id in result:
                raise ValueError("cache signals must be unique per DP replica")
            result[signal.replica_id] = signal
        snapshots = {item.directory_snapshot_fingerprint for item in signals}
        if len(snapshots) > 1:
            raise ValueError("cache signals must use one directory snapshot fingerprint")
        requested_prefixes = {item.requested_prefix_tokens for item in signals}
        if len(requested_prefixes) > 1:
            raise ValueError("cache signals must describe one requested prefix length")
        lookup_ids = [item.lookup_id for item in signals]
        if len(lookup_ids) != len(set(lookup_ids)):
            raise ValueError("cache signal lookup IDs must be unique")
        return result

    def _score_candidate(
        self,
        *,
        replica: DPReplicaSnapshot,
        explicitly_excluded: bool,
        cache_signal: CacheHitSignal | None,
        round_robin_distance: int | None,
    ) -> CandidateScore:
        eligible = replica.healthy and not explicitly_excluded
        if not eligible:
            reason = "unhealthy" if not replica.healthy else "explicitly_excluded"
            return CandidateScore(
                replica=replica,
                explicitly_excluded=explicitly_excluded,
                eligible=False,
                cache_signal=cache_signal,
                selection_key=None,
                score_reason=reason,
            )
        load_key = (
            replica.queued_tokens,
            replica.waiting_requests,
            replica.running_requests,
        )
        key: tuple[int, ...]
        if self.policy is RoutePolicy.ROUND_ROBIN:
            if round_robin_distance is None:
                raise AssertionError("eligible round-robin target has no cursor distance")
            key = (round_robin_distance,)
            reason = "round_robin_circular_distance"
        elif self.policy is RoutePolicy.LEAST_LOADED:
            key = load_key
            reason = "lexicographic_queue_load"
        else:
            if cache_signal is None:
                raise RouterError("eligible cache-aware target has no cache signal")
            key = (-cache_signal.compatible_cached_tokens, *load_key)
            reason = "explicit_cache_tokens_then_queue_load"
        return CandidateScore(
            replica=replica,
            explicitly_excluded=False,
            eligible=True,
            cache_signal=cache_signal,
            selection_key=key,
            score_reason=reason,
        )

    def _selection_reason(
        self,
        selected: CandidateScore,
        selectable: list[CandidateScore],
    ) -> str:
        if self.policy is RoutePolicy.ROUND_ROBIN:
            return "round_robin: minimum circular cursor distance"
        if self.policy is RoutePolicy.LEAST_LOADED:
            return (
                "least_loaded: minimum queued_tokens, waiting_requests, "
                "running_requests"
            )
        signal = selected.cache_signal
        if signal is None:
            raise AssertionError("selected cache-aware candidate has no cache signal")
        any_hit = any(
            item.cache_signal is not None and item.cache_signal.cache_hit
            for item in selectable
        )
        if any_hit:
            return (
                "cache_hit: maximum explicit compatible_cached_tokens, then queue load"
            )
        return "cache_miss_all_candidates: least queue load after explicit zero-hit signals"
