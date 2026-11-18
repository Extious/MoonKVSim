"""Fail-closed artifact gate for the formal AegisKV Algorithm 2/3 path.

The gate consumes only a completed experiment ``payload`` and its
``representative`` record.  It deliberately does not import the simulator runtime or
re-run policy decisions.  Every accepted arithmetic claim is reconstructed from the
canonical rational evidence emitted with the decision.

Passing this gate establishes trace-level policy semantics, not calibrated physical
performance.  In particular, projected or smoothed artifacts are rejected and the
report keeps the E2/physical evidence boundary explicit.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from fractions import Fraction
from itertools import pairwise
from typing import Any, TypedDict

from moonkvsim.aegiskv.types import fraction_from_json
from moonkvsim.common.hash import sha256_json

FORMAL_ALGORITHM_AUDIT_SCHEMA = "moonkvsim.aegiskv.formal-algorithm-paper-gate.v1"
CONTINUOUS_SCHEDULER_AUDIT_SCHEMA = (
    "moonkvsim.aegiskv.continuous-scheduler-evidence-gate.v1"
)
_ACTIVE_PRIMARY_ACCOUNT = "ACTIVE_PRIMARY_KV"
_FOREGROUND_STORE_RESERVED_ACCOUNT = "FOREGROUND_STORE_RESTORE_RESERVED"
_EXACT_JOINT_LOSS = "recompute_once_per_affected_request_from_tentative_victim_set"
_FORBIDDEN_EVIDENCE_MARKERS = ("projected", "projection", "smoothed")
_RESULT_DECLARATION_KEYS = {
    "data_origin",
    "derivation",
    "evidence",
    "figure",
    "figure_metadata",
    "figure_source",
    "figures",
    "result_declaration",
    "result_kind",
    "result_source",
}
_AIMD_ACTIONS = {
    "MULTIPLICATIVE_DECREASE",
    "STABLE_WINDOW",
    "ADDITIVE_INCREASE",
}


class FormalAlgorithmAuditError(ValueError):
    """Raised when formal Algorithm 2/3 evidence is absent or inconsistent."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("formal Algorithm 2/3 audit failed: " + "; ".join(self.errors))

    def __reduce__(self) -> tuple[object, tuple[tuple[str, ...]]]:
        # ProcessPoolExecutor reconstructs exceptions from their constructor
        # arguments. Preserve the error sequence, rather than splitting the
        # formatted message into individual characters in the parent process.
        return type(self), (self.errors,)


@dataclass(frozen=True, slots=True)
class FormalAlgorithmAuditReport:
    """Canonical passing report suitable for a paper runner sidecar."""

    preview_count: int
    admitted_preview_count: int
    aimd_decision_count: int
    continuous_duration_provider_count: int
    continuous_request_count: int
    continuous_step_count: int
    pool_ids: tuple[str, ...]
    aimd_enabled: bool = True

    def canonical_fields(self) -> dict[str, object]:
        return {
            "aimd_decision_count": self.aimd_decision_count,
            "aimd_enabled": self.aimd_enabled,
            "checks": {
                "aimd_md_immediate_and_ai_after_k_stable_windows": self.aimd_enabled,
                "disabled_aimd_has_no_control_decisions": not self.aimd_enabled,
                "aimd_quota_lifecycle_uses_formal_safe_tails": True,
                "continuous_batch_scheduler_step_bridge": True,
                "continuous_scheduler_evidence_reconstructed": True,
                "exact_candidate_gain_A": True,
                "exact_victim_set_loss_D": True,
                "formal_byte_and_rent_conservation": True,
                "foreground_store_restore_transaction_lifecycle": True,
                "no_projected_or_smoothed_evidence": True,
                "peer_and_store_landlords_independent": True,
                "pending_never_recovery_visible": True,
                "physical_alias_harm_and_candidate_dependency_exclusion": True,
                "physical_pool_byte_conservation": True,
                "strict_H_below_Theta_and_A_above_D": True,
                "suffix_frontier_and_same_request_exclusion": True,
            },
            "evidence_boundary": {
                "calibrated_physical_performance": False,
                "claim_scope": "formal_policy_trace_semantics_only",
                "paper_performance_claim_allowed_by_this_gate": False,
                "physical_execution": False,
            },
            "continuous_scheduler": {
                "duration_provider_count": self.continuous_duration_provider_count,
                "request_count": self.continuous_request_count,
                "step_count": self.continuous_step_count,
            },
            "formal_algorithm2_admitted_preview_count": self.admitted_preview_count,
            "formal_algorithm2_preview_count": self.preview_count,
            "pool_ids": list(self.pool_ids),
            "schema": FORMAL_ALGORITHM_AUDIT_SCHEMA,
            "status": "PASS",
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        return {**self.canonical_fields(), "fingerprint": self.fingerprint}


@dataclass(frozen=True, slots=True)
class ContinuousSchedulerAuditReport:
    """Cross-system scheduler/physical-authority evidence report.

    This report is deliberately independent of the AegisKV landlord events so
    the paper runner can apply the same executable-evidence gate to Mooncake
    and AegisKV.
    """

    duration_provider_count: int
    request_count: int
    step_count: int
    terminal_request_count: int
    hbm_resource_ids: tuple[str, ...]

    def canonical_fields(self) -> dict[str, object]:
        return {
            "checks": {
                "all_requests_executed_and_uniquely_terminated": True,
                "participant_and_completion_ids_bound_to_requests": True,
                "request_and_workflow_timing_reconstructed": True,
                "resident_snapshots_bound_to_physical_hbm_ledger": True,
            },
            "duration_provider_count": self.duration_provider_count,
            "evidence_boundary": {
                "calibrated_physical_performance": False,
                "claim_scope": "continuous_scheduler_trace_structure_only",
                "paper_performance_claim_allowed_by_this_gate": False,
                "physical_execution": False,
            },
            "hbm_resource_ids": list(self.hbm_resource_ids),
            "request_count": self.request_count,
            "schema": CONTINUOUS_SCHEDULER_AUDIT_SCHEMA,
            "status": "PASS",
            "step_count": self.step_count,
            "terminal_request_count": self.terminal_request_count,
        }

    @property
    def fingerprint(self) -> str:
        return sha256_json(self.canonical_fields())

    def to_dict(self) -> dict[str, object]:
        return {**self.canonical_fields(), "fingerprint": self.fingerprint}


@dataclass(frozen=True, slots=True)
class _RentObservation:
    pool_id: str
    timestamp_ns: int
    kind: str
    local_index: int
    rent_before: Fraction
    rent_after: Fraction
    path: str


@dataclass(frozen=True, slots=True)
class _HBMLedgerEvidence:
    gpu_id: str
    resource_id: str
    capacity_bytes: int
    account_names: tuple[str, ...]
    states: tuple[tuple[int, Mapping[str, int]], ...]


class _Candidate(TypedDict):
    allocated_bytes: int
    chunk_id: str
    request_id: str
    sequence_index: int


class _Audit:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def add(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def mapping(self, value: object, path: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            self.add(path, "must be an object")
            return {}
        return value

    def sequence(self, value: object, path: str) -> Sequence[object]:
        if not isinstance(value, list):
            self.add(path, "must be a JSON array")
            return ()
        return value

    def integer(self, value: object, path: str, *, minimum: int = 0) -> int:
        if type(value) is not int or value < minimum:
            self.add(path, f"must be an integer >= {minimum}")
            return minimum
        return value

    def text(self, value: object, path: str) -> str:
        if not isinstance(value, str) or not value:
            self.add(path, "must be a non-empty string")
            return ""
        return value

    def boolean(self, value: object, path: str) -> bool:
        if type(value) is not bool:
            self.add(path, "must be a boolean")
            return False
        return value

    def fraction(self, value: object, path: str) -> Fraction:
        raw = self.mapping(value, path)
        try:
            return fraction_from_json(raw)
        except (TypeError, ValueError) as error:
            self.add(path, f"must be a canonical exact fraction ({error})")
            return Fraction(0, 1)

    def decimal(self, value: object, path: str) -> Decimal:
        if not isinstance(value, str):
            self.add(path, "must be a canonical decimal string")
            return Decimal(0)
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            self.add(path, "must be a finite decimal string")
            return Decimal(0)
        if not parsed.is_finite():
            self.add(path, "must be a finite decimal string")
            return Decimal(0)
        # The runtime uses exponent-free text with insignificant zeroes removed.
        canonical = format(parsed, "f")
        if "." in canonical:
            canonical = canonical.rstrip("0").rstrip(".")
        canonical = "0" if canonical in {"", "-0"} else canonical
        if canonical != value:
            self.add(path, "must use the runtime's canonical decimal spelling")
        return parsed


def _candidate(raw_value: Mapping[str, object], audit: _Audit, path: str) -> _Candidate:
    candidate = audit.mapping(raw_value.get("candidate"), f"{path}.candidate")
    chunk_id = audit.text(candidate.get("chunk_id"), f"{path}.candidate.chunk_id")
    request_id = audit.text(candidate.get("request_id"), f"{path}.candidate.request_id")
    sequence_index = audit.integer(
        candidate.get("sequence_index"), f"{path}.candidate.sequence_index"
    )
    allocated = audit.integer(
        candidate.get("actual_allocated_bytes"),
        f"{path}.candidate.actual_allocated_bytes",
        minimum=1,
    )
    duplicated = audit.integer(
        raw_value.get("actual_allocated_bytes"),
        f"{path}.actual_allocated_bytes",
        minimum=1,
    )
    if duplicated != allocated:
        audit.add(path, "candidate and rental-value allocated bytes diverge")
    return {
        "allocated_bytes": allocated,
        "chunk_id": chunk_id,
        "request_id": request_id,
        "sequence_index": sequence_index,
    }


def _harm_snapshot(
    raw: object,
    audit: _Audit,
    path: str,
) -> tuple[str, str, Fraction]:
    snapshot = audit.mapping(raw, path)
    request_id = audit.text(snapshot.get("request_id"), f"{path}.request_id")
    pool = audit.text(snapshot.get("pool"), f"{path}.pool")
    evaluated = audit.integer(snapshot.get("evaluated_at_ns"), f"{path}.evaluated_at_ns")
    recovery = audit.mapping(snapshot.get("recovery_time"), f"{path}.recovery_time")
    components = [
        audit.fraction(recovery.get(name), f"{path}.recovery_time.{name}")
        for name in (
            "load_ns",
            "prompt_suffix_recompute_ns",
            "silent_replay_ns",
            "collective_sync_ns",
        )
    ]
    total = audit.fraction(recovery.get("total_ns"), f"{path}.recovery_time.total_ns")
    if total != sum(components, start=Fraction(0, 1)):
        audit.add(path, "recovery total does not equal its exact components")
    slack = audit.mapping(snapshot.get("slack"), f"{path}.slack")
    observed = audit.integer(slack.get("observed_at_ns"), f"{path}.slack.observed_at_ns")
    if evaluated < observed:
        audit.add(path, "snapshot predates its slack observation")
    slack_observed = audit.fraction(
        slack.get("slack_at_observation_ns"),
        f"{path}.slack.slack_at_observation_ns",
    )
    slack_now = audit.fraction(slack.get("s_i_t"), f"{path}.slack.s_i_t")
    expected_slack = max(slack_observed - Fraction(evaluated - observed, 1), 0)
    if slack_now != expected_slack:
        audit.add(path, "s_i(t) does not follow GlobalDES slack decay")
    harm = audit.fraction(snapshot.get("harm_J_ns"), f"{path}.harm_J_ns")
    if harm != max(total - slack_now, 0):
        audit.add(path, "J does not equal [T-s_i(t)]^+")
    return request_id, pool, harm


def _rental_value(
    raw: object,
    audit: _Audit,
    path: str,
) -> tuple[_Candidate, str, Fraction, Fraction, Fraction]:
    value = audit.mapping(raw, path)
    candidate = _candidate(value, audit, path)
    pool = audit.text(value.get("pool"), f"{path}.pool")
    allocated = int(candidate["allocated_bytes"])
    gain = audit.fraction(value.get("G"), f"{path}.G")
    workflow_gain = audit.fraction(value.get("W"), f"{path}.W")
    p_value = audit.fraction(value.get("P"), f"{path}.P")
    rent = audit.fraction(value.get("pool_rent"), f"{path}.pool_rent")
    h_value = audit.fraction(value.get("H"), f"{path}.H")
    if gain != workflow_gain:
        audit.add(path, "formal recovery-only G must equal W")
    if audit.fraction(value.get("Uhit"), f"{path}.Uhit") != 0:
        audit.add(path, "formal recovery-only Uhit must be zero")
    if audit.fraction(value.get("Ulru"), f"{path}.Ulru") != 0:
        audit.add(path, "formal recovery-only Ulru must be zero")
    if p_value != gain / allocated:
        audit.add(path, "P must equal G divided by actual allocated bytes")
    if h_value != rent + p_value:
        audit.add(path, "H must equal pool rent plus P")
    return candidate, pool, gain, rent, h_value


def _audit_refreshes(
    raw_refreshes: object,
    audit: _Audit,
    path: str,
) -> None:
    for index, item in enumerate(audit.sequence(raw_refreshes, path)):
        item_path = f"{path}[{index}]"
        refresh = audit.mapping(item, item_path)
        trigger = refresh.get("trigger")
        if trigger not in {"HEAP_TOP", "NEWLY_EXPOSED"}:
            audit.add(item_path, "refresh trigger is outside the two authorized sites")
        refreshed = audit.boolean(refresh.get("refreshed"), f"{item_path}.refreshed")
        before = audit.mapping(refresh.get("before"), f"{item_path}.before")
        after = audit.mapping(refresh.get("after"), f"{item_path}.after")
        before_candidate = _candidate(before, audit, f"{item_path}.before")
        after_candidate = _candidate(after, audit, f"{item_path}.after")
        if before_candidate != after_candidate or before.get("pool") != after.get("pool"):
            audit.add(item_path, "refresh changed chunk identity or pool")
        if refreshed != (before != after):
            audit.add(item_path, "refreshed flag does not match before/after values")
        before_time = audit.integer(
            before.get("evaluated_at_ns"), f"{item_path}.before.evaluated_at_ns"
        )
        after_time = audit.integer(
            after.get("evaluated_at_ns"), f"{item_path}.after.evaluated_at_ns"
        )
        if after_time < before_time:
            audit.add(item_path, "lazy refresh regressed GlobalDES time")
        before_versions = audit.mapping(
            before.get("signal_versions"), f"{item_path}.before.signal_versions"
        )
        after_versions = audit.mapping(
            after.get("signal_versions"), f"{item_path}.after.signal_versions"
        )
        for name in ("slack", "hit", "lru", "frontier"):
            old = audit.integer(before_versions.get(name), f"{item_path}.before.{name}")
            new = audit.integer(after_versions.get(name), f"{item_path}.after.{name}")
            if new < old:
                audit.add(item_path, f"lazy refresh regressed {name} version")


def _audit_preview(
    event: Mapping[str, object],
    audit: _Audit,
    path: str,
    *,
    alias_locations: Mapping[tuple[str, str, str], set[str]],
) -> tuple[str, str, bool, Fraction, Fraction]:
    event_path = audit.text(event.get("path"), f"{path}.path")
    pool_id = audit.text(event.get("pool_id"), f"{path}.pool_id")
    span_id = audit.text(event.get("span_id"), f"{path}.span_id")
    candidate_token_start = audit.integer(
        event.get("candidate_token_start"),
        f"{path}.candidate_token_start",
    )
    candidate_token_count = audit.integer(
        event.get("candidate_token_count"),
        f"{path}.candidate_token_count",
        minimum=1,
    )
    policy_chunk_tokens = audit.integer(
        event.get("engine_policy_chunk_tokens"),
        f"{path}.engine_policy_chunk_tokens",
        minimum=1,
    )
    global_system_template = audit.boolean(
        event.get("candidate_global_system_template"),
        f"{path}.candidate_global_system_template",
    )
    if candidate_token_count > policy_chunk_tokens:
        audit.add(path, "Algorithm 2 candidate exceeds engine policy-chunk granularity")
    if global_system_template and candidate_token_start != 0:
        audit.add(path, "global system-template candidate must start at token zero")
    if global_system_template and candidate_token_count > 64:
        audit.add(path, "global system-template candidate exceeds one source-hash block")
    preview = audit.mapping(event.get("preview"), f"{path}.preview")
    pool = audit.text(preview.get("pool"), f"{path}.preview.pool")
    if pool != event_path or not pool_id.startswith(f"{pool}:"):
        audit.add(path, "event path, formal pool, and physical pool_id are not tier-local")

    candidate, candidate_pool, gain, rent, h_value = _rental_value(
        preview.get("candidate_value"), audit, f"{path}.preview.candidate_value"
    )
    if candidate_pool != pool:
        audit.add(path, "candidate belongs to a different landlord tier")
    if candidate["request_id"] != span_id:
        audit.add(path, "event span_id and candidate request_id diverge")
    threshold = audit.fraction(preview.get("threshold_Theta"), f"{path}.preview.threshold_Theta")
    if threshold != h_value:
        audit.add(path, "Theta must equal the candidate's exact H")

    gain_evidence = audit.mapping(
        preview.get("candidate_gain_evidence"),
        f"{path}.preview.candidate_gain_evidence",
    )
    before_request, before_pool, before_harm = _harm_snapshot(
        gain_evidence.get("before"), audit, f"{path}.preview.candidate_gain_evidence.before"
    )
    after_request, after_pool, after_harm = _harm_snapshot(
        gain_evidence.get("after"), audit, f"{path}.preview.candidate_gain_evidence.after"
    )
    exact_a = max(before_harm - after_harm, 0)
    emitted_a = audit.fraction(
        gain_evidence.get("gain_A_ns"),
        f"{path}.preview.candidate_gain_evidence.gain_A_ns",
    )
    if before_request != after_request or before_request != candidate["request_id"]:
        audit.add(path, "candidate A snapshots belong to another request")
    if before_pool != after_pool or before_pool != pool:
        audit.add(path, "candidate A snapshots belong to another tier")
    if emitted_a != exact_a or gain != exact_a:
        audit.add(path, "candidate G/A is not exact [J_before-J_after]^+")

    def references_physical_key(chunk_id: str, physical_key: str) -> bool:
        marker = f":{physical_key}"
        return chunk_id.endswith(marker) or f"{marker}:attempt:" in chunk_id

    raw_victims = audit.sequence(
        preview.get("selected_victims"), f"{path}.preview.selected_victims"
    )
    victims: list[tuple[_Candidate, Fraction]] = []
    per_request_indices: defaultdict[str, list[int]] = defaultdict(list)
    for index, raw_victim in enumerate(raw_victims):
        victim_path = f"{path}.preview.selected_victims[{index}]"
        victim, victim_pool, _victim_g, _victim_rent, victim_h = _rental_value(
            raw_victim, audit, victim_path
        )
        if victim_pool != pool:
            audit.add(victim_path, "victim belongs to another landlord tier")
        if victim["request_id"] == candidate["request_id"]:
            audit.add(victim_path, "same-request victim exclusion was violated")
        if victim_h >= threshold:
            audit.add(victim_path, "victim does not satisfy strict H_y < Theta")
        per_request_indices[str(victim["request_id"])].append(int(victim["sequence_index"]))
        victims.append((victim, victim_h))
    selected_chunk_ids = {str(victim["chunk_id"]) for victim, _ in victims}
    raw_excluded = audit.sequence(
        preview.get("excluded_victim_chunk_ids"),
        f"{path}.preview.excluded_victim_chunk_ids",
    )
    excluded_ids = [
        audit.text(item, f"{path}.preview.excluded_victim_chunk_ids[{index}]")
        for index, item in enumerate(raw_excluded)
    ]
    if len(excluded_ids) != len(set(excluded_ids)):
        audit.add(path, "excluded physical-victim chunk IDs are not unique")
    if selected_chunk_ids.intersection(excluded_ids):
        audit.add(path, "candidate-dependent physical victim was selected despite exclusion")
    candidate_alias_keys = alias_locations.get((span_id, event_path, pool_id), set())
    raw_excluded_reasons = audit.mapping(
        preview.get("excluded_victim_reasons"),
        f"{path}.preview.excluded_victim_reasons",
    )
    excluded_reasons = {
        chunk_id: {
            audit.text(
                reason,
                f"{path}.preview.excluded_victim_reasons[{chunk_id!r}][{index}]",
            )
            for index, reason in enumerate(
                audit.sequence(
                    raw_excluded_reasons.get(chunk_id),
                    f"{path}.preview.excluded_victim_reasons[{chunk_id!r}]",
                )
            )
        }
        for chunk_id in excluded_ids
    }
    if set(raw_excluded_reasons) != set(excluded_ids):
        audit.add(path, "excluded victim reasons do not exactly cover excluded chunk IDs")
    allowed_exclusion_reasons = {
        "CANDIDATE_PHYSICAL_ALIAS",
        "PENDING_SUCCESSOR_CONTIGUITY",
        "PHYSICAL_SOURCE_PIN",
    }
    for chunk_id, reasons in excluded_reasons.items():
        if not reasons:
            audit.add(path, f"excluded victim {chunk_id!r} has no exclusion reason")
        if reasons.difference(allowed_exclusion_reasons):
            audit.add(path, f"excluded victim {chunk_id!r} has an unknown exclusion reason")
    for physical_key in sorted(candidate_alias_keys):
        if not any(
            references_physical_key(chunk_id, physical_key)
            and "CANDIDATE_PHYSICAL_ALIAS" in excluded_reasons.get(chunk_id, set())
            for chunk_id in excluded_ids
        ):
            audit.add(
                path,
                "candidate physical alias dependency is absent from excluded_victim_chunk_ids",
            )
    for chunk_id in excluded_ids:
        is_candidate_alias = any(
            references_physical_key(chunk_id, key) for key in candidate_alias_keys
        )
        if (
            "CANDIDATE_PHYSICAL_ALIAS" in excluded_reasons.get(chunk_id, set())
            and not is_candidate_alias
        ):
            audit.add(path, "excluded victim is not a recorded candidate alias dependency")
    for request_id, indices in per_request_indices.items():
        if len(indices) != len(set(indices)) or any(
            right != left - 1 for left, right in pairwise(indices)
        ):
            audit.add(
                path,
                f"victims for request {request_id!r} are not a descending contiguous suffix",
            )

    victim_requests = {str(victim["request_id"]) for victim, _ in victims}
    loss_evidence_raw = preview.get("joint_loss_evidence")
    exact_d = Fraction(0, 1)
    if victims:
        loss_evidence = audit.mapping(loss_evidence_raw, f"{path}.preview.joint_loss_evidence")
        before_items = audit.sequence(
            loss_evidence.get("before_by_request"),
            f"{path}.preview.joint_loss_evidence.before_by_request",
        )
        after_items = audit.sequence(
            loss_evidence.get("after_by_request"),
            f"{path}.preview.joint_loss_evidence.after_by_request",
        )
        before_by_request: dict[str, tuple[str, Fraction]] = {}
        after_by_request: dict[str, tuple[str, Fraction]] = {}
        for index, raw_snapshot in enumerate(before_items):
            request, evidence_pool, harm = _harm_snapshot(
                raw_snapshot,
                audit,
                f"{path}.preview.joint_loss_evidence.before_by_request[{index}]",
            )
            if request in before_by_request:
                audit.add(path, "victim-set before evidence duplicates a request")
            before_by_request[request] = (evidence_pool, harm)
        for index, raw_snapshot in enumerate(after_items):
            request, evidence_pool, harm = _harm_snapshot(
                raw_snapshot,
                audit,
                f"{path}.preview.joint_loss_evidence.after_by_request[{index}]",
            )
            if request in after_by_request:
                audit.add(path, "victim-set after evidence duplicates a request")
            after_by_request[request] = (evidence_pool, harm)
        evidence_requests = set(before_by_request)
        if evidence_requests != set(after_by_request):
            audit.add(path, "victim-set D before/after request sets diverge")
        if not victim_requests.issubset(evidence_requests):
            audit.add(path, "victim-set D omits a selected victim owner")
        if str(candidate["request_id"]) in evidence_requests:
            audit.add(path, "victim-set D includes the protected candidate request")
        alias_affected_requests = {
            request_id
            for (request_id, alias_path, alias_pool_id), physical_keys in alias_locations.items()
            if alias_path == event_path
            and alias_pool_id == pool_id
            and any(
                references_physical_key(chunk_id, physical_key)
                for chunk_id in selected_chunk_ids
                for physical_key in physical_keys
            )
        }
        if evidence_requests != victim_requests | alias_affected_requests:
            audit.add(
                path,
                "victim-set D must include exactly victim owners and affected content aliases",
            )
        for request_id in sorted(evidence_requests):
            before_pool_harm = before_by_request.get(request_id)
            after_pool_harm = after_by_request.get(request_id)
            if before_pool_harm is None or after_pool_harm is None:
                continue
            if before_pool_harm[0] != pool or after_pool_harm[0] != pool:
                audit.add(path, "victim-set D crosses landlord tiers")
            exact_d += max(
                after_pool_harm[1] - before_pool_harm[1],
                Fraction(0, 1),
            )
        emitted_evidence_d = audit.fraction(
            loss_evidence.get("joint_loss_D_ns"),
            f"{path}.preview.joint_loss_evidence.joint_loss_D_ns",
        )
        if emitted_evidence_d != exact_d:
            audit.add(path, "joint loss D is not the exact before/after victim-set delta")
    elif loss_evidence_raw is not None:
        audit.add(path, "empty victim set must not carry joint-loss evidence")

    emitted_d = audit.fraction(preview.get("joint_loss_D_Y"), f"{path}.preview.joint_loss_D_Y")
    if emitted_d != exact_d:
        audit.add(path, "preview D diverges from exact victim-set evidence")
    if preview.get("joint_loss_interpretation") != _EXACT_JOINT_LOSS:
        audit.add(path, "preview did not use the current-design exact D interpretation")
    if preview.get("joint_loss_review_status") != "current_design_exact":
        audit.add(path, "preview joint-loss review status is not current-design exact")
    if preview.get("joint_loss_manual_review_confirmed") is not False:
        audit.add(path, "machine event improperly claims manual review")

    free_before = audit.integer(
        preview.get("free_bytes_before"), f"{path}.preview.free_bytes_before"
    )
    free_after = audit.integer(
        preview.get("free_bytes_after_selection"),
        f"{path}.preview.free_bytes_after_selection",
    )
    victim_bytes = sum(int(victim["allocated_bytes"]) for victim, _ in victims)
    if free_after != free_before + victim_bytes:
        audit.add(path, "formal byte conservation failed for selected victims")
    proposed_rent = audit.fraction(preview.get("proposed_rent"), f"{path}.preview.proposed_rent")
    outcome = preview.get("outcome")
    admitted = outcome == "ADMIT"
    if outcome not in {"ADMIT", "BYPASS"}:
        audit.add(path, "outcome must be ADMIT or BYPASS")
    if admitted:
        if preview.get("bypass_reason") is not None:
            audit.add(path, "admitted preview carries a bypass reason")
        if free_after < int(candidate["allocated_bytes"]):
            audit.add(path, "admitted preview did not establish capacity")
        if gain <= exact_d:
            audit.add(path, "admission violates strict A > D")
        expected_rent = max([rent, *(victim_h for _, victim_h in victims)])
        if proposed_rent != expected_rent:
            audit.add(path, "admission rent does not equal max prior rent/victim H")
    else:
        reason = preview.get("bypass_reason")
        if not isinstance(reason, str) or not reason:
            audit.add(path, "bypass lacks a reason")
        if proposed_rent != rent:
            audit.add(path, "bypass changed pool rent")
        if reason == "CANDIDATE_G_NOT_STRICTLY_ABOVE_JOINT_LOSS":
            if free_after < int(candidate["allocated_bytes"]) or gain > exact_d:
                audit.add(path, "A/D bypass reason is inconsistent with strict gate")
        elif reason == "FAILURE_DOMAIN_UNAVAILABLE":
            if free_before != 0 or victims:
                audit.add(path, "unavailable-domain bypass has capacity or victims")
        elif reason in {
            "INSUFFICIENT_CAPACITY_OR_NO_LEGAL_VICTIM",
            "VICTIM_KEY_NOT_STRICTLY_BELOW_THRESHOLD",
        }:
            if free_after >= int(candidate["allocated_bytes"]):
                audit.add(path, "capacity/victim bypass nevertheless establishes capacity")
        elif isinstance(reason, str) and reason:
            audit.add(path, f"unknown fail-closed bypass reason {reason!r}")

    _audit_refreshes(preview.get("refresh_checks"), audit, f"{path}.preview.refresh_checks")
    return pool_id, pool, admitted, rent, proposed_rent


def _nearest_rank(values: Sequence[int], percentile: int) -> int:
    ordered = sorted(values)
    rank = max(1, (len(ordered) * percentile + 99) // 100)
    return ordered[rank - 1]


def _audit_hbm_authority_evidence(
    payload: Mapping[str, object],
    representative: Mapping[str, object],
    audit: _Audit,
) -> dict[str, _HBMLedgerEvidence]:
    """Bind step residency to the experiment's physical CapacityLedger views."""

    timeline_path = "representative.gpu_hbm_timelines"
    timelines = audit.mapping(representative.get("gpu_hbm_timelines"), timeline_path)
    metrics = audit.mapping(payload.get("metrics"), "payload.metrics")
    resource_cost = audit.mapping(metrics.get("resource_cost"), "payload.metrics.resource_cost")
    summaries = audit.mapping(
        resource_cost.get("gpu_hbm_account_stack_by_gpu"),
        "payload.metrics.resource_cost.gpu_hbm_account_stack_by_gpu",
    )
    resource_model = audit.mapping(payload.get("resource_model"), "payload.resource_model")
    declared_accounts_raw = audit.sequence(
        resource_model.get("gpu_hbm_account_stack"),
        "payload.resource_model.gpu_hbm_account_stack",
    )
    declared_accounts = tuple(
        sorted(
            audit.text(value, f"payload.resource_model.gpu_hbm_account_stack[{index}]")
            for index, value in enumerate(declared_accounts_raw)
        )
    )
    if _ACTIVE_PRIMARY_ACCOUNT not in declared_accounts:
        audit.add(
            "payload.resource_model.gpu_hbm_account_stack",
            f"must declare {_ACTIVE_PRIMARY_ACCOUNT}",
        )
    if not timelines:
        audit.add(timeline_path, "physical HBM ledger timelines must be non-empty")
    if set(timelines) != set(summaries):
        audit.add(timeline_path, "timeline GPUs and payload account-stack GPUs diverged")

    result: dict[str, _HBMLedgerEvidence] = {}
    for gpu_key in sorted(set(timelines) | set(summaries), key=str):
        gpu_id = str(gpu_key)
        raw_states = audit.sequence(timelines.get(gpu_key), f"{timeline_path}.{gpu_id}")
        summary = audit.mapping(
            summaries.get(gpu_key),
            f"payload.metrics.resource_cost.gpu_hbm_account_stack_by_gpu.{gpu_id}",
        )
        if not raw_states:
            audit.add(f"{timeline_path}.{gpu_id}", "ledger timeline must be non-empty")
            continue
        states: list[tuple[int, Mapping[str, int]]] = []
        resource_id = ""
        capacity_bytes = 0
        account_names: tuple[str, ...] = ()
        peak_accounts: dict[str, int] = {}
        previous_timestamp = -1
        for index, raw_state in enumerate(raw_states):
            state_path = f"{timeline_path}.{gpu_id}[{index}]"
            state = audit.mapping(raw_state, state_path)
            timestamp_ns = audit.integer(state.get("timestamp_ns"), f"{state_path}.timestamp_ns")
            if timestamp_ns < previous_timestamp:
                audit.add(state_path, "physical HBM ledger time regressed")
            previous_timestamp = timestamp_ns
            current_resource_id = audit.text(
                state.get("resource_id"), f"{state_path}.resource_id"
            )
            current_capacity = audit.integer(
                state.get("capacity_bytes"), f"{state_path}.capacity_bytes", minimum=1
            )
            raw_accounts = audit.mapping(state.get("accounts"), f"{state_path}.accounts")
            accounts: dict[str, int] = {}
            for account_key, raw_value in raw_accounts.items():
                account = audit.text(account_key, f"{state_path}.accounts.<key>")
                accounts[account] = audit.integer(
                    raw_value, f"{state_path}.accounts.{account}"
                )
            current_names = tuple(sorted(accounts))
            if index == 0:
                resource_id = current_resource_id
                capacity_bytes = current_capacity
                account_names = current_names
                peak_accounts = {name: 0 for name in account_names}
            elif (
                current_resource_id != resource_id
                or current_capacity != capacity_bytes
                or current_names != account_names
            ):
                audit.add(state_path, "ledger resource, capacity, or account stack drifted")
            if sum(accounts.values()) != current_capacity:
                audit.add(state_path, "physical HBM accounts do not conserve capacity")
            if _ACTIVE_PRIMARY_ACCOUNT not in accounts:
                audit.add(state_path, f"ledger lacks {_ACTIVE_PRIMARY_ACCOUNT} account")
            for name, value in accounts.items():
                peak_accounts[name] = max(peak_accounts.get(name, 0), value)
            states.append((timestamp_ns, accounts))
        if declared_accounts and account_names != declared_accounts:
            audit.add(
                f"{timeline_path}.{gpu_id}",
                "representative account stack differs from payload resource model",
            )
        if summary.get("valid") is not True:
            audit.add(
                f"payload.metrics.resource_cost.gpu_hbm_account_stack_by_gpu.{gpu_id}.valid",
                "physical account-stack summary must be valid",
            )
        expected_summary: dict[str, object] = {
            "resource_id": resource_id,
            "capacity_bytes": capacity_bytes,
            "final_accounts": dict(sorted(states[-1][1].items())),
            "peak_account_bytes": dict(sorted(peak_accounts.items())),
            "event_boundary_snapshot_count": len(states),
        }
        for field, expected in expected_summary.items():
            if summary.get(field) != expected:
                audit.add(
                    f"payload.metrics.resource_cost.gpu_hbm_account_stack_by_gpu.{gpu_id}.{field}",
                    "does not reconstruct from representative physical HBM timeline",
                )
        result[gpu_id] = _HBMLedgerEvidence(
            gpu_id=gpu_id,
            resource_id=resource_id,
            capacity_bytes=capacity_bytes,
            account_names=account_names,
            states=tuple(states),
        )
    return result


def _audit_resident_snapshot(
    raw: object,
    audit: _Audit,
    path: str,
    *,
    request_ids: set[str],
    gpu_id: str,
    timestamp_ns: int,
    hbm_ledgers: Mapping[str, _HBMLedgerEvidence],
) -> tuple[set[str], tuple[int, ...], dict[str, int]]:
    snapshot = audit.mapping(raw, path)
    raw_request_ids = audit.sequence(snapshot.get("request_ids"), f"{path}.request_ids")
    resident_ids = [
        audit.text(value, f"{path}.request_ids[{index}]")
        for index, value in enumerate(raw_request_ids)
    ]
    if len(resident_ids) != len(set(resident_ids)):
        audit.add(f"{path}.request_ids", "resident request IDs must be unique")
    if not set(resident_ids) <= request_ids:
        audit.add(f"{path}.request_ids", "resident snapshot names an unknown request")
    raw_blocks = audit.sequence(
        snapshot.get("unique_block_ids"), f"{path}.unique_block_ids"
    )
    block_ids = tuple(
        audit.integer(value, f"{path}.unique_block_ids[{index}]")
        for index, value in enumerate(raw_blocks)
    )
    if block_ids != tuple(sorted(set(block_ids))):
        audit.add(f"{path}.unique_block_ids", "resident logical blocks must be sorted and unique")
    raw_resources = audit.mapping(
        snapshot.get("bytes_by_hbm_resource"), f"{path}.bytes_by_hbm_resource"
    )
    resource_bytes: dict[str, int] = {}
    for resource_key, raw_value in raw_resources.items():
        resource_id = audit.text(resource_key, f"{path}.bytes_by_hbm_resource.<key>")
        resource_bytes[resource_id] = audit.integer(
            raw_value, f"{path}.bytes_by_hbm_resource.{resource_id}"
        )
    resident_bytes = audit.integer(
        snapshot.get("resident_primary_bytes"), f"{path}.resident_primary_bytes"
    )
    if resident_bytes != sum(resource_bytes.values()):
        audit.add(path, "per-resource bytes do not conserve resident primary bytes")
    if audit.integer(
        snapshot.get("resident_primary_request_count"),
        f"{path}.resident_primary_request_count",
    ) != len(resident_ids):
        audit.add(path, "resident request count does not match request IDs")
    if audit.integer(
        snapshot.get("resident_primary_block_count"),
        f"{path}.resident_primary_block_count",
    ) != len(block_ids):
        audit.add(path, "resident block count does not match block IDs")
    if bool(resident_ids) != bool(block_ids) or bool(resident_ids) != (resident_bytes > 0):
        audit.add(path, "resident request, logical-page, and physical-byte emptiness diverged")

    ledger = hbm_ledgers.get(gpu_id)
    if ledger is None:
        audit.add(path, f"resident snapshot references unknown GPU {gpu_id!r}")
    else:
        if set(resource_bytes) != {ledger.resource_id}:
            audit.add(path, "resident snapshot is not owned by its GPU HBM resource")
        else:
            # One DES timestamp can contain completion, retirement, and the next
            # schedule mutation in stable sequence order.  The serialized ledger
            # keeps timestamps but not that cross-record sequence number, so a
            # phase snapshot may legitimately match either the last state before
            # the timestamp or one of the states committed at the timestamp.
            earlier = [accounts for at, accounts in ledger.states if at < timestamp_ns]
            exact_states = [accounts for at, accounts in ledger.states if at == timestamp_ns]
            candidate_states = [*earlier[-1:], *exact_states]
            claimed = resource_bytes[ledger.resource_id]
            if not any(
                accounts.get(_ACTIVE_PRIMARY_ACCOUNT) == claimed
                for accounts in candidate_states
            ):
                audit.add(
                    path,
                    "resident physical bytes do not match the HBM ACTIVE account at this event",
                )
    return set(resident_ids), block_ids, resource_bytes


def _audit_continuous_scheduler(
    payload: Mapping[str, object],
    representative: Mapping[str, object],
    audit: _Audit,
) -> ContinuousSchedulerAuditReport:
    """Reject scheduler evidence that is not joined to requests and HBM authority."""

    path = "representative.continuous_batch_scheduler"
    scheduler = audit.mapping(representative.get("continuous_batch_scheduler"), path)
    finished_at_ns = audit.integer(scheduler.get("finished_at_ns"), f"{path}.finished_at_ns")
    requests = audit.sequence(scheduler.get("requests"), f"{path}.requests")
    steps = audit.sequence(scheduler.get("steps"), f"{path}.steps")
    failures = audit.sequence(scheduler.get("failures"), f"{path}.failures")
    duration_evidence = audit.sequence(
        scheduler.get("duration_evidence"), f"{path}.duration_evidence"
    )
    if not requests:
        audit.add(f"{path}.requests", "must contain completed scheduler requests")
    if not steps:
        audit.add(f"{path}.steps", "must contain executed scheduler steps")
    if not duration_evidence:
        audit.add(f"{path}.duration_evidence", "must bind the modeled duration provider")
    if scheduler.get("calibration_boundary") != (
        "MODELED_UNCALIBRATED_NOT_PHYSICAL_BATCH_LATENCY_EVIDENCE"
    ):
        audit.add(path, "continuous scheduler lost its uncalibrated evidence boundary")

    hbm_ledgers = _audit_hbm_authority_evidence(payload, representative, audit)
    request_ids: set[str] = set()
    request_timing: dict[str, tuple[int, int, int]] = {}
    max_output_by_request: dict[str, int] = {}
    for index, raw_request in enumerate(requests):
        request_path = f"{path}.requests[{index}]"
        request = audit.mapping(raw_request, request_path)
        spec = audit.mapping(request.get("spec"), f"{request_path}.spec")
        request_id = audit.text(spec.get("request_id"), f"{request_path}.spec.request_id")
        if request_id in request_ids:
            audit.add(request_path, "duplicate scheduler request_id")
        request_ids.add(request_id)
        release_ns = audit.integer(spec.get("release_ns"), f"{request_path}.spec.release_ns")
        max_output_by_request[request_id] = audit.integer(
            spec.get("max_output_tokens"),
            f"{request_path}.spec.max_output_tokens",
            minimum=1,
        )
        completion_ns = audit.integer(request.get("completion_ns"), f"{request_path}.completion_ns")
        wct_ns = audit.integer(request.get("wct_ns"), f"{request_path}.wct_ns")
        if completion_ns < release_ns or wct_ns != completion_ns - release_ns:
            audit.add(request_path, "completion/release timestamps do not reconstruct WCT")
        request_timing[request_id] = (release_ns, completion_ns, wct_ns)
        route_history = audit.sequence(
            request.get("route_history"), f"{request_path}.route_history"
        )
        if not route_history:
            audit.add(f"{request_path}.route_history", "must bind at least one physical route")

    terminal_times: defaultdict[str, list[int]] = defaultdict(list)
    participant_counts: defaultdict[str, int] = defaultdict(int)
    step_ids: set[str] = set()
    fenced_failure_ids: set[str] = set()
    for index, raw_step in enumerate(steps):
        step_path = f"{path}.steps[{index}]"
        step = audit.mapping(raw_step, step_path)
        step_id = audit.text(step.get("step_id"), f"{step_path}.step_id")
        if step_id in step_ids:
            audit.add(step_path, "duplicate scheduler step_id")
        step_ids.add(step_id)
        status = audit.text(step.get("status"), f"{step_path}.status")
        if status not in {"COMPLETED", "FENCED"}:
            audit.add(step_path, "scheduler step must be completed or failure-fenced")
        start_ns = audit.integer(step.get("start_ns"), f"{step_path}.start_ns")
        planned_end_ns = audit.integer(
            step.get("planned_end_ns"), f"{step_path}.planned_end_ns"
        )
        effective_end_ns = audit.integer(
            step.get("effective_end_ns"), f"{step_path}.effective_end_ns"
        )
        duration = audit.mapping(step.get("duration"), f"{step_path}.duration")
        duration_ns = audit.integer(
            duration.get("duration_ns"), f"{step_path}.duration.duration_ns", minimum=1
        )
        if planned_end_ns != start_ns + duration_ns:
            audit.add(step_path, "planned end does not equal start plus modeled duration")
        if effective_end_ns < start_ns or effective_end_ns > planned_end_ns:
            audit.add(step_path, "effective step end is outside the planned interval")
        participants = audit.sequence(step.get("participants"), f"{step_path}.participants")
        participant_ids = [
            audit.text(
                audit.mapping(item, f"{step_path}.participants[{participant_index}]").get(
                    "request_id"
                ),
                f"{step_path}.participants[{participant_index}].request_id",
            )
            for participant_index, item in enumerate(participants)
        ]
        if not participant_ids:
            audit.add(f"{step_path}.participants", "scheduler step has no participants")
        if len(participant_ids) != len(set(participant_ids)):
            audit.add(f"{step_path}.participants", "scheduler step repeats a participant")
        if not set(participant_ids) <= request_ids:
            audit.add(f"{step_path}.participants", "scheduler step names an unknown request")
        for request_id in participant_ids:
            participant_counts[request_id] += 1
            request_times = request_timing.get(request_id)
            if request_times is not None and start_ns < request_times[0]:
                audit.add(step_path, "scheduler request participated before release")
        gpu_id = audit.text(step.get("gpu_id"), f"{step_path}.gpu_id")
        _audit_resident_snapshot(
            step.get("resident_before"),
            audit,
            f"{step_path}.resident_before",
            request_ids=request_ids,
            gpu_id=gpu_id,
            timestamp_ns=start_ns,
            hbm_ledgers=hbm_ledgers,
        )
        resident_after_ids, _, _ = _audit_resident_snapshot(
            step.get("resident_after_schedule"),
            audit,
            f"{step_path}.resident_after_schedule",
            request_ids=request_ids,
            gpu_id=gpu_id,
            timestamp_ns=start_ns,
            hbm_ledgers=hbm_ledgers,
        )
        if not set(participant_ids) <= resident_after_ids:
            audit.add(step_path, "forward participants lack physical ACTIVE residency")

        completion_raw = step.get("completion")
        retire_raw = step.get("resident_after_retire")
        if status == "COMPLETED":
            completion = audit.mapping(completion_raw, f"{step_path}.completion")
            if completion.get("step_id") != step_id:
                audit.add(f"{step_path}.completion.step_id", "completion owns another step")
            output_positions = audit.mapping(
                completion.get("output_positions"), f"{step_path}.completion.output_positions"
            )
            if set(output_positions) != set(participant_ids):
                audit.add(
                    f"{step_path}.completion.output_positions",
                    "completion output positions do not cover participants exactly",
                )
            terminal_raw = audit.sequence(
                completion.get("terminal_output_request_ids"),
                f"{step_path}.completion.terminal_output_request_ids",
            )
            terminal_ids = [
                audit.text(
                    value,
                    f"{step_path}.completion.terminal_output_request_ids[{terminal_index}]",
                )
                for terminal_index, value in enumerate(terminal_raw)
            ]
            if len(terminal_ids) != len(set(terminal_ids)):
                audit.add(step_path, "one completion terminates a request more than once")
            if not set(terminal_ids) <= set(participant_ids):
                audit.add(step_path, "completion terminates a non-participant request")
            for request_id in terminal_ids:
                terminal_times[request_id].append(effective_end_ns)
            _audit_resident_snapshot(
                completion.get("residency_after_completion"),
                audit,
                f"{step_path}.completion.residency_after_completion",
                request_ids=request_ids,
                gpu_id=gpu_id,
                timestamp_ns=effective_end_ns,
                hbm_ledgers=hbm_ledgers,
            )
            retired_ids, _, _ = _audit_resident_snapshot(
                retire_raw,
                audit,
                f"{step_path}.resident_after_retire",
                request_ids=request_ids,
                gpu_id=gpu_id,
                timestamp_ns=effective_end_ns,
                hbm_ledgers=hbm_ledgers,
            )
            if set(terminal_ids) & retired_ids:
                audit.add(step_path, "terminal request retained ACTIVE ownership after retire")
            if effective_end_ns != planned_end_ns:
                audit.add(step_path, "completed scheduler step did not reach its planned end")
            if step.get("fenced_by_failure_id") is not None:
                audit.add(step_path, "completed scheduler step carries a failure fence")
        elif status == "FENCED":
            if completion_raw is not None or retire_raw is not None:
                audit.add(step_path, "failure-fenced step contains completion/retirement evidence")
            failure_id = audit.text(
                step.get("fenced_by_failure_id"), f"{step_path}.fenced_by_failure_id"
            )
            fenced_failure_ids.add(failure_id)

    failure_ids: set[str] = set()
    for index, raw_failure in enumerate(failures):
        failure_path = f"{path}.failures[{index}]"
        failure = audit.mapping(raw_failure, failure_path)
        failure_id = audit.text(failure.get("failure_id"), f"{failure_path}.failure_id")
        if failure_id in failure_ids:
            audit.add(failure_path, "duplicate scheduler failure_id")
        failure_ids.add(failure_id)
    if not fenced_failure_ids <= failure_ids:
        audit.add(f"{path}.steps", "fenced scheduler step names an unknown failure")

    for request_id in sorted(request_ids):
        if participant_counts[request_id] == 0:
            audit.add(f"{path}.requests[{request_id}]", "scheduler request was never executed")
        terminals = terminal_times[request_id]
        if len(terminals) != 1:
            audit.add(
                f"{path}.requests[{request_id}]",
                "scheduler request must have exactly one terminal completion",
            )
        elif request_timing.get(request_id, (0, -1, 0))[1] != terminals[0]:
            audit.add(
                f"{path}.requests[{request_id}].completion_ns",
                "request completion does not equal its terminal step end",
            )

    algorithm1 = audit.mapping(
        representative.get("algorithm1_cpm"), "representative.algorithm1_cpm"
    )
    if set(algorithm1) != request_ids:
        audit.add(
            "representative.algorithm1_cpm",
            "CPM span IDs and continuous scheduler request IDs diverged",
        )
    workflow_by_request: dict[str, str] = {}
    for request_id in sorted(request_ids):
        cpm_timing = audit.mapping(
            algorithm1.get(request_id), f"representative.algorithm1_cpm.{request_id}"
        )
        workflow_by_request[request_id] = audit.text(
            cpm_timing.get("workflow_id"),
            f"representative.algorithm1_cpm.{request_id}.workflow_id",
        )

    metrics = audit.mapping(payload.get("metrics"), "payload.metrics")
    request_latencies = [timing[2] for timing in request_timing.values()]
    request_metric = audit.mapping(
        metrics.get("request_latency_ns"), "payload.metrics.request_latency_ns"
    )
    if request_latencies:
        if request_metric.get("mean") != sum(request_latencies) // len(request_latencies):
            audit.add(
                "payload.metrics.request_latency_ns.mean",
                "does not reconstruct from requests",
            )
        if request_metric.get("p95") != _nearest_rank(request_latencies, 95):
            audit.add(
                "payload.metrics.request_latency_ns.p95",
                "does not reconstruct from requests",
            )
    workflow_starts: dict[str, int] = {}
    workflow_ends: dict[str, int] = {}
    for request_id, (release_ns, completion_ns, _wct_ns) in request_timing.items():
        workflow_id = workflow_by_request.get(request_id, "")
        workflow_starts[workflow_id] = min(workflow_starts.get(workflow_id, release_ns), release_ns)
        workflow_ends[workflow_id] = max(
            workflow_ends.get(workflow_id, completion_ns), completion_ns
        )
    reconstructed_workflow_wct = {
        workflow_id: workflow_ends[workflow_id] - start_ns
        for workflow_id, start_ns in sorted(workflow_starts.items())
    }
    workflow_metric = audit.mapping(
        metrics.get("workflow_completion_time_ns"),
        "payload.metrics.workflow_completion_time_ns",
    )
    if workflow_metric.get("by_workflow_id") != reconstructed_workflow_wct:
        audit.add(
            "payload.metrics.workflow_completion_time_ns.by_workflow_id",
            "does not reconstruct from scheduler request timing and workflow binding",
        )
    workflow_values = list(reconstructed_workflow_wct.values())
    if workflow_values:
        expected_workflow = {
            "mean": sum(workflow_values) // len(workflow_values),
            "p95": _nearest_rank(workflow_values, 95),
            "max": max(workflow_values),
        }
        for field, expected in expected_workflow.items():
            if workflow_metric.get(field) != expected:
                audit.add(
                    f"payload.metrics.workflow_completion_time_ns.{field}",
                    "does not reconstruct from scheduler workflow timing",
                )
        if metrics.get("workload_end_ns") != max(workflow_ends.values()):
            audit.add("payload.metrics.workload_end_ns", "does not equal last request completion")
    workload = audit.mapping(payload.get("workload"), "payload.workload")
    if workload.get("span_count") != len(request_ids):
        audit.add("payload.workload.span_count", "does not match scheduler request count")
    if workload.get("workflow_count") != len(reconstructed_workflow_wct):
        audit.add("payload.workload.workflow_count", "does not match reconstructed workflows")
    if request_timing and finished_at_ns < max(value[1] for value in request_timing.values()):
        audit.add(f"{path}.finished_at_ns", "scheduler finished before a request completed")
    output_audit = audit.mapping(payload.get("output_audit"), "payload.output_audit")
    expected_outputs = sum(max_output_by_request.values())
    if output_audit.get("expected_output_tokens") != expected_outputs:
        audit.add("payload.output_audit.expected_output_tokens", "does not match request specs")
    if output_audit.get("external_output_tokens") != expected_outputs:
        audit.add("payload.output_audit.external_output_tokens", "does not prove all outputs")
    if output_audit.get("duplicate_or_missing_tokens") != 0:
        audit.add("payload.output_audit.duplicate_or_missing_tokens", "must be zero")

    for index, raw_evidence in enumerate(duration_evidence):
        evidence_path = f"{path}.duration_evidence[{index}]"
        evidence = audit.mapping(raw_evidence, evidence_path)
        if evidence.get("evidence_class") != "UNCALIBRATED_MODEL":
            audit.add(evidence_path, "unexpected scheduler-duration evidence class")
        if evidence.get("physically_measured") is not False:
            audit.add(evidence_path, "modeled scheduler duration claims physical measurement")
        if evidence.get("formal_use_allowed") is not False:
            audit.add(evidence_path, "uncalibrated scheduler duration claims formal use")
    return ContinuousSchedulerAuditReport(
        duration_provider_count=len(duration_evidence),
        request_count=len(requests),
        step_count=len(steps),
        terminal_request_count=sum(len(values) == 1 for values in terminal_times.values()),
        hbm_resource_ids=tuple(sorted(item.resource_id for item in hbm_ledgers.values())),
    )


def _pressure_cleared_by_failed_control_window(
    representative: Mapping[str, Any], target: str, timestamp_ns: int,
) -> bool:
    """Prove that the next periodic window ran while this GPU was unavailable.

    The runtime clears a window's pressure latch before checking GPU liveness.
    A failed device cannot change quota. A failure label alone is insufficient:
    require the preceding cadence, the complete outage, and physical HBM loss.
    """
    events = representative.get("aimd_events", [])
    preceding = [event for event in events if isinstance(event, Mapping)
                 and event.get("target_id") == target
                 and type(event.get("timestamp_ns")) is int
                 and event["timestamp_ns"] <= timestamp_ns]
    if not preceding:
        return False
    previous = max(preceding, key=lambda event: event["timestamp_ns"])
    window_ns = previous.get("control_window_ns")
    if type(window_ns) is not int or window_ns <= 0:
        return False
    deadline = previous["timestamp_ns"] + window_ns
    if not timestamp_ns < deadline:
        return False
    # A later decision proves that global workload execution continued beyond
    # the skipped window; completed repair alone could be after workload end.
    if not any(isinstance(event, Mapping)
               and type(event.get("timestamp_ns")) is int
               and event["timestamp_ns"] > deadline for event in events):
        return False
    timelines = representative.get("gpu_hbm_timelines", {})
    if not isinstance(timelines, Mapping):
        return False
    timeline = timelines.get(target, [])
    for failure in representative.get("failure_events", []):
        if not isinstance(failure, Mapping) or failure.get("event") != "FAILURE_INJECT":
            continue
        start, end = failure.get("timestamp_ns"), failure.get("repair_completed_at_ns")
        if (failure.get("target_gpu_id") != target or type(start) is not int
                or type(end) is not int or not timestamp_ns <= start < deadline < end):
            continue
        loss = [state for state in timeline if isinstance(state, Mapping)
                and state.get("timestamp_ns") == start
                and state.get("cause") == "GPU_FAILURE_ALL_HBM_UNAVAILABLE"]
        repair = [state for state in timeline if isinstance(state, Mapping)
                  and state.get("timestamp_ns") == end
                  and state.get("cause") == "GPU_REPAIR_HBM_EMPTY_REUSABLE"]
        if len(loss) != 1 or len(repair) != 1:
            continue
        capacity = loss[0].get("capacity_bytes")
        accounts = loss[0].get("accounts", {})
        restored = repair[0].get("accounts", {})
        if (type(capacity) is int and capacity > 0
                and isinstance(accounts, Mapping) and isinstance(restored, Mapping)
                and accounts.get("UNAVAILABLE_CAPACITY") == capacity
                and repair[0].get("capacity_bytes") == capacity
                and restored.get("UNAVAILABLE_CAPACITY") == 0):
            return True
    return False


def _audit_lifecycle(
    raw: object,
    audit: _Audit,
    path: str,
    *,
    expected_capacity: int,
) -> tuple[Fraction, Fraction]:
    lifecycle = audit.mapping(raw, path)
    if lifecycle.get("action") != "CAPACITY_CHANGE":
        audit.add(path, "AIMD lifecycle must be a formal CAPACITY_CHANGE")
    if lifecycle.get("pool") != "PEER_HBM":
        audit.add(path, "AIMD lifecycle must belong to its Peer-HBM landlord")
    if (
        lifecycle.get("available_before") is not True
        or lifecycle.get("available_after") is not True
    ):
        audit.add(path, "AIMD cannot mutate an unavailable Peer-HBM landlord")
    before_capacity = audit.integer(
        lifecycle.get("capacity_bytes_before"), f"{path}.capacity_bytes_before"
    )
    after_capacity = audit.integer(
        lifecycle.get("capacity_bytes_after"), f"{path}.capacity_bytes_after"
    )
    if after_capacity != expected_capacity:
        audit.add(path, "formal capacity and AIMD quota diverge")
    rent_before = audit.fraction(lifecycle.get("rent_before"), f"{path}.rent_before")
    rent_after = audit.fraction(lifecycle.get("rent_after"), f"{path}.rent_after")
    if rent_after < rent_before:
        audit.add(path, "capacity lifecycle refunded accumulated rent")
    released = audit.sequence(lifecycle.get("released_entries"), f"{path}.released_entries")
    per_request: defaultdict[str, list[int]] = defaultdict(list)
    released_bytes = 0
    released_h: list[Fraction] = []
    for index, raw_entry in enumerate(released):
        entry_path = f"{path}.released_entries[{index}]"
        candidate, pool, _gain, _rent, h_value = _rental_value(raw_entry, audit, entry_path)
        if pool != "PEER_HBM":
            audit.add(entry_path, "quota victim crosses into another tier")
        per_request[str(candidate["request_id"])].append(int(candidate["sequence_index"]))
        released_bytes += int(candidate["allocated_bytes"])
        released_h.append(h_value)
    for request_id, indices in per_request.items():
        if len(indices) != len(set(indices)) or any(
            right != left - 1 for left, right in pairwise(indices)
        ):
            audit.add(path, f"quota victims for {request_id!r} are not safe suffix tails")
    if audit.integer(lifecycle.get("released_bytes"), f"{path}.released_bytes") != released_bytes:
        audit.add(path, "formal quota released-byte accounting diverges")
    pending = audit.sequence(lifecycle.get("aborted_pending"), f"{path}.aborted_pending")
    pending_bytes = audit.integer(
        lifecycle.get("aborted_pending_bytes"), f"{path}.aborted_pending_bytes"
    )
    if pending or pending_bytes != 0:
        audit.add(path, "AIMD lifecycle leaked PENDING into safe-tail eviction")
    if released_h and rent_after != max(rent_before, max(released_h)):
        audit.add(path, "quota lifecycle rent does not conserve selected tail H")
    if not released_h and rent_after != rent_before:
        audit.add(path, "empty quota lifecycle changed rent")
    if after_capacity < before_capacity and lifecycle.get("cause") not in {
        "AEGIS_AIMD_MULTIPLICATIVE_DECREASE",
        "AEGIS_AIMD_STABLE_WINDOW",
    }:
        audit.add(path, "quota contraction lacks its audited AIMD cause")
    _audit_refreshes(lifecycle.get("refresh_checks"), audit, f"{path}.refresh_checks")
    return rent_before, rent_after


def _audit_aimd(
    representative: Mapping[str, object],
    audit: _Audit,
    *,
    require_formal_lifecycle: bool = True,
) -> tuple[int, list[_RentObservation]]:
    events = audit.sequence(representative.get("aimd_events"), "representative.aimd_events")
    last_timestamp: dict[str, int] = {}
    rent_observations: list[_RentObservation] = []
    last_next_state: dict[str, Mapping[str, object]] = {}
    md_keys: set[tuple[str, int]] = set()
    for index, raw_event in enumerate(events):
        path = f"representative.aimd_events[{index}]"
        event = audit.mapping(raw_event, path)
        action = event.get("action")
        if action not in _AIMD_ACTIONS:
            audit.add(path, "unknown AIMD action")
        pressure = audit.boolean(event.get("foreground_pressure"), f"{path}.foreground_pressure")
        timestamp = audit.integer(event.get("timestamp_ns"), f"{path}.timestamp_ns")
        previous = audit.mapping(event.get("previous_state"), f"{path}.previous_state")
        next_state = audit.mapping(event.get("next_state"), f"{path}.next_state")
        parameters = audit.mapping(event.get("parameters"), f"{path}.parameters")
        target = audit.text(previous.get("target_id"), f"{path}.previous_state.target_id")
        if next_state.get("target_id") != target:
            audit.add(path, "AIMD target changed across a decision")
        prior_next = last_next_state.get(target)
        if prior_next is not None and previous != prior_next:
            audit.add(path, "AIMD previous_state is not the target's prior next_state")
        last_next_state[target] = next_state
        if target in last_timestamp and timestamp <= last_timestamp[target]:
            audit.add(path, "per-target AIMD timestamps are not strictly increasing")
        last_timestamp[target] = timestamp
        if next_state.get("last_update_ns") != timestamp:
            audit.add(path, "AIMD decision was not applied at its control-window boundary")
        previous_alpha = audit.decimal(
            previous.get("protection_fraction"), f"{path}.previous_state.protection_fraction"
        )
        next_alpha = audit.decimal(
            next_state.get("protection_fraction"), f"{path}.next_state.protection_fraction"
        )
        minimum = audit.decimal(
            parameters.get("minimum_fraction"), f"{path}.parameters.minimum_fraction"
        )
        maximum = audit.decimal(
            parameters.get("maximum_fraction"), f"{path}.parameters.maximum_fraction"
        )
        gamma = audit.decimal(
            parameters.get("multiplicative_decrease"),
            f"{path}.parameters.multiplicative_decrease",
        )
        delta = audit.decimal(
            parameters.get("additive_increase"), f"{path}.parameters.additive_increase"
        )
        stable_k = audit.integer(
            parameters.get("stable_window_count"),
            f"{path}.parameters.stable_window_count",
            minimum=1,
        )
        previous_stable = audit.integer(
            previous.get("stable_windows"), f"{path}.previous_state.stable_windows"
        )
        next_stable = audit.integer(
            next_state.get("stable_windows"), f"{path}.next_state.stable_windows"
        )
        if pressure:
            expected_action = "MULTIPLICATIVE_DECREASE"
            expected_alpha = max(minimum, gamma * previous_alpha)
            expected_stable = 0
            md_keys.add((target, timestamp))
        elif previous_stable + 1 >= stable_k:
            expected_action = "ADDITIVE_INCREASE"
            expected_alpha = min(maximum, previous_alpha + delta)
            expected_stable = 0
        else:
            expected_action = "STABLE_WINDOW"
            expected_alpha = previous_alpha
            expected_stable = previous_stable + 1
        if (
            action != expected_action
            or next_alpha != expected_alpha
            or next_stable != expected_stable
        ):
            audit.add(path, "AIMD transition violates windowed MD / K-window AI")
        expected_basis = "FIXED_GLOBAL_DES_CONTROL_WINDOW"
        if event.get("update_basis") != expected_basis:
            audit.add(path, f"AIMD event update_basis must equal {expected_basis!r}")
        capacity = audit.integer(
            previous.get("peer_hbm_capacity_bytes"),
            f"{path}.previous_state.peer_hbm_capacity_bytes",
            minimum=1,
        )
        if next_state.get("peer_hbm_capacity_bytes") != capacity:
            audit.add(path, "AIMD physical target capacity changed")
        expected_quota = int(
            (next_alpha * Decimal(capacity)).to_integral_value(rounding=ROUND_FLOOR)
        )
        quota = audit.integer(event.get("quota_bytes"), f"{path}.quota_bytes")
        if quota != expected_quota:
            audit.add(path, "AIMD quota is not floor(alpha * M)")
        current = audit.integer(
            event.get("current_protection_bytes"), f"{path}.current_protection_bytes"
        )
        reclaim = max(0, current - quota)
        if event.get("bytes_to_reclaim") != reclaim:
            audit.add(path, "AIMD reclaim bytes do not match protection/quota difference")
        if event.get("admission_blocked") is not (reclaim > 0):
            audit.add(path, "AIMD admission_blocked does not match reclaim pressure")
        if not require_formal_lifecycle:
            continue
        pool_id = f"PEER_HBM:{target}"
        rent_before, rent_after = _audit_lifecycle(
            event.get("formal_algorithm2_capacity_lifecycle"),
            audit,
            f"{path}.formal_algorithm2_capacity_lifecycle",
            expected_capacity=quota,
        )
        rent_observations.append(
            _RentObservation(
                pool_id=pool_id,
                timestamp_ns=timestamp,
                kind="AIMD",
                local_index=index,
                rent_before=rent_before,
                rent_after=rent_after,
                path=path,
            )
        )
    observations = audit.sequence(
        representative.get("hbm_pressure_observations"),
        "representative.hbm_pressure_observations",
    )
    observations_by_target: defaultdict[str, list[int]] = defaultdict(list)
    for index, raw_observation in enumerate(observations):
        path = f"representative.hbm_pressure_observations[{index}]"
        observation = audit.mapping(raw_observation, path)
        target = audit.text(observation.get("target_gpu_id"), f"{path}.target_gpu_id")
        timestamp = audit.integer(observation.get("timestamp_ns"), f"{path}.timestamp_ns")
        observations_by_target[target].append(timestamp)
    md_by_target: defaultdict[str, list[int]] = defaultdict(list)
    for target, timestamp in md_keys:
        md_by_target[target].append(timestamp)
    for target, timestamps in observations_by_target.items():
        decisions = sorted(md_by_target[target])
        for timestamp in sorted(timestamps):
            if not any(decision_at >= timestamp for decision_at in decisions):
                if _pressure_cleared_by_failed_control_window(
                    representative, target, timestamp
                ):
                    continue
                terminal_state = audit.mapping(
                    representative.get("aimd_terminal_state"),
                    "representative.aimd_terminal_state",
                )
                target_terminal = audit.mapping(
                    terminal_state.get(target),
                    f"representative.aimd_terminal_state.{target}",
                )
                if (
                    target_terminal.get(
                        "control_window_canceled_at_workload_completion"
                    )
                    is True
                    and target_terminal.get("pending_pressure") is True
                ):
                    continue
                audit.add(
                    "representative.hbm_pressure_observations",
                    f"pressure on {target!r} at {timestamp} ns was not "
                    "consumed by a later control-window MD",
                )
    for target, timestamp in sorted(md_keys):
        previous_timestamp = max(
            (
                event_timestamp
                for event_target, event_timestamp in md_keys
                if event_target == target and event_timestamp < timestamp
            ),
            default=-1,
        )
        if not any(
            previous_timestamp < observation_at <= timestamp
            for observation_at in observations_by_target[target]
        ):
            audit.add(
                "representative.aimd_events",
                f"windowed MD on {target!r} at {timestamp} ns lacks "
                "pressure in its control interval",
            )
    return len(events), rent_observations


def _audit_rent_chronology(
    observations: Sequence[_RentObservation],
    audit: _Audit,
) -> None:
    """Merge preview and AIMD rent evidence on each physical pool's DES clock.

    The two source lists have independent local indices, so same-timestamp records do
    not expose their global stable sequence.  Ordering equal-time records by their
    exact before/after rent, then kind/index, reconstructs the only monotone ordering
    the evidence can support without inventing a cross-list sequence number.
    """

    by_pool: defaultdict[str, list[_RentObservation]] = defaultdict(list)
    for observation in observations:
        by_pool[observation.pool_id].append(observation)
    for pool_id, pool_observations in sorted(by_pool.items()):
        previous_rent = Fraction(0, 1)
        for observation in sorted(
            pool_observations,
            key=lambda item: (
                item.timestamp_ns,
                item.rent_before,
                item.rent_after,
                item.kind,
                item.local_index,
            ),
        ):
            if observation.rent_before < previous_rent:
                audit.add(
                    observation.path,
                    f"pool {pool_id!r} rent regressed in merged DES chronology",
                )
            if observation.rent_after < observation.rent_before:
                audit.add(observation.path, "rent mutation refunded accumulated rent")
            previous_rent = max(previous_rent, observation.rent_after)


def _audit_physical_pools(
    payload: Mapping[str, object],
    representative: Mapping[str, object],
    audit: _Audit,
) -> None:
    metrics = audit.mapping(payload.get("metrics"), "payload.metrics")
    pools = audit.mapping(metrics.get("pool_audit"), "payload.metrics.pool_audit")
    for tier in ("peer_hbm", "store_dram"):
        tier_audit = audit.mapping(pools.get(tier), f"payload.metrics.pool_audit.{tier}")
        if tier_audit.get("valid") is not True:
            audit.add(f"payload.metrics.pool_audit.{tier}", "physical pool audit is not valid")
        children_name = "per_gpu" if tier == "peer_hbm" else "per_segment"
        children = audit.mapping(
            tier_audit.get(children_name),
            f"payload.metrics.pool_audit.{tier}.{children_name}",
        )
        if not children:
            audit.add(f"payload.metrics.pool_audit.{tier}.{children_name}", "must not be empty")
        for child_id, raw_child in children.items():
            child = audit.mapping(
                raw_child, f"payload.metrics.pool_audit.{tier}.{children_name}.{child_id}"
            )
            if child.get("valid") is not True:
                audit.add(
                    f"payload.metrics.pool_audit.{tier}.{children_name}.{child_id}",
                    "physical child pool is invalid",
                )
            final_bytes = audit.integer(
                child.get("final_bytes"),
                f"payload.metrics.pool_audit.{tier}.{children_name}.{child_id}.final_bytes",
            )
            capacity_key = "quota_bytes" if tier == "peer_hbm" else "capacity_bytes"
            capacity = audit.integer(
                child.get(capacity_key),
                f"payload.metrics.pool_audit.{tier}.{children_name}.{child_id}.{capacity_key}",
            )
            if final_bytes > capacity:
                audit.add(str(child_id), "final physical bytes exceed capacity")
    if pools.get("pending_destination_bytes_final") != 0:
        audit.add("payload.metrics.pool_audit", "final physical PENDING bytes are nonzero")
    if pools.get("unattributed_reserve_bytes") != 0:
        audit.add("payload.metrics.pool_audit", "unattributed physical reserve bytes are nonzero")
    resource_cost = audit.mapping(
        metrics.get("resource_cost"), "payload.metrics.resource_cost"
    )
    if resource_cost.get("source_pin_count_final") != 0:
        audit.add(
            "payload.metrics.resource_cost.source_pin_count_final",
            "run ended with active transfer source pins",
        )
    if resource_cost.get("gpu_hbm_foreground_store_reserve_final_bytes") != 0:
        audit.add(
            "payload.metrics.resource_cost.gpu_hbm_foreground_store_reserve_final_bytes",
            "run ended with foreground Store destination reservations",
        )
    for tier in ("normal_hbm", "store_dram"):
        tier_audit = audit.mapping(
            pools.get(tier), f"payload.metrics.pool_audit.{tier}"
        )
        for field in ("pinned_entry_count_final", "pinned_reference_count_final"):
            if tier_audit.get(field) != 0:
                audit.add(
                    f"payload.metrics.pool_audit.{tier}.{field}",
                    "run ended with pinned physical KV entries",
                )

    for key in (
        "peer_hbm_timelines",
        "store_dram_timelines",
    ):
        timelines = audit.mapping(representative.get(key), f"representative.{key}")
        if not timelines:
            audit.add(f"representative.{key}", "must not be empty")
        for pool_id, raw_timeline in timelines.items():
            timeline = audit.sequence(raw_timeline, f"representative.{key}.{pool_id}")
            previous_timestamp = -1
            for index, raw_point in enumerate(timeline):
                point_path = f"representative.{key}.{pool_id}[{index}]"
                point = audit.mapping(raw_point, point_path)
                timestamp = audit.integer(point.get("timestamp_ns"), f"{point_path}.timestamp_ns")
                committed = audit.integer(
                    point.get("committed_bytes"), f"{point_path}.committed_bytes"
                )
                pending = audit.integer(point.get("pending_bytes"), f"{point_path}.pending_bytes")
                occupied = audit.integer(
                    point.get("occupied_bytes"), f"{point_path}.occupied_bytes"
                )
                capacity = audit.integer(
                    point.get("capacity_bytes"), f"{point_path}.capacity_bytes"
                )
                unavailable = audit.integer(
                    point.get("unavailable_bytes"), f"{point_path}.unavailable_bytes"
                )
                if timestamp < previous_timestamp:
                    audit.add(point_path, "physical pool timeline regressed DES time")
                previous_timestamp = timestamp
                if occupied != committed + pending:
                    audit.add(point_path, "occupied bytes do not equal committed plus pending")
                if occupied > capacity and unavailable == 0:
                    audit.add(point_path, "available physical bytes exceed quota")


def _audit_foreground_store_restore_transactions(
    representative: Mapping[str, object],
    audit: _Audit,
) -> None:
    """Reconstruct every foreground Store GET group from canonical events."""

    raw_events = representative.get("foreground_store_events")
    if raw_events is None:
        return
    events = audit.sequence(
        raw_events,
        "representative.foreground_store_events",
    )
    groups: dict[str, dict[str, object]] = {}
    previous_timestamp = -1
    for index, raw_event in enumerate(events):
        path = f"representative.foreground_store_events[{index}]"
        event = audit.mapping(raw_event, path)
        timestamp_ns = audit.integer(event.get("timestamp_ns"), f"{path}.timestamp_ns")
        if timestamp_ns < previous_timestamp:
            audit.add(path, "foreground Store event chronology regressed")
        previous_timestamp = timestamp_ns
        span_id = audit.text(event.get("span_id"), f"{path}.span_id")
        kind = audit.text(event.get("event"), f"{path}.event")
        state = groups.setdefault(
            span_id,
            {
                "started": set(),
                "completed": set(),
                "restore_complete": False,
                "terminal": None,
            },
        )
        started = state["started"]
        completed = state["completed"]
        if not isinstance(started, set) or not isinstance(completed, set):
            audit.add(path, "foreground Store audit state is malformed")
            continue
        if state["terminal"] is not None:
            audit.add(path, "foreground Store event followed a terminal event")
        if kind == "FOREGROUND_STORE_GET_START":
            transfer_id = audit.text(event.get("transfer_id"), f"{path}.transfer_id")
            if transfer_id in started:
                audit.add(path, "foreground Store transfer started more than once")
            started.add(transfer_id)
        elif kind == "FOREGROUND_STORE_GET_SEGMENT_COMPLETE":
            transfer_id = audit.text(event.get("transfer_id"), f"{path}.transfer_id")
            if transfer_id not in started:
                audit.add(path, "foreground Store segment completed before GET start")
            if transfer_id in completed:
                audit.add(path, "foreground Store segment completed more than once")
            completed.add(transfer_id)
        elif kind == "FOREGROUND_STORE_RESTORE_COMPLETE":
            if state["restore_complete"]:
                audit.add(path, "foreground Store group completed more than once")
            if not started or completed != started:
                audit.add(path, "foreground Store group completed before all segments")
            segment_count = audit.integer(
                event.get("segment_transfer_count"),
                f"{path}.segment_transfer_count",
                minimum=1,
            )
            if segment_count != len(started):
                audit.add(path, "foreground Store segment count does not match transfers")
            if event.get("destination_account") != _FOREGROUND_STORE_RESERVED_ACCOUNT:
                audit.add(path, "foreground Store completion lost destination reservation")
            state["restore_complete"] = True
        elif kind == "FOREGROUND_STORE_RESTORE_ADOPTED":
            if state["restore_complete"] is not True:
                audit.add(path, "foreground Store destination adopted before GET completion")
            adopted_bytes = audit.integer(
                event.get("adopted_bytes"), f"{path}.adopted_bytes", minimum=1
            )
            if adopted_bytes <= 0:
                audit.add(path, "foreground Store adoption has no physical bytes")
            state["terminal"] = kind
        elif kind == "FOREGROUND_STORE_RESTORE_ABORTED":
            completed_count = audit.integer(
                event.get("completed_segment_count"),
                f"{path}.completed_segment_count",
            )
            segment_count = audit.integer(
                event.get("segment_transfer_count"),
                f"{path}.segment_transfer_count",
            )
            if completed_count != len(completed) or segment_count != len(started):
                audit.add(path, "foreground Store abort counts do not reconstruct")
            state["terminal"] = kind
        else:
            audit.add(path, f"unknown foreground Store event {kind!r}")
    for span_id, state in groups.items():
        if state["terminal"] is None:
            audit.add(
                f"representative.foreground_store_events.{span_id}",
                "foreground Store group lacks ADOPTED or ABORTED terminal event",
            )


def _audit_pending_visibility(representative: Mapping[str, object], audit: _Audit) -> None:
    recovery_events = audit.sequence(
        representative.get("recovery_events"), "representative.recovery_events"
    )
    plans = 0
    for index, raw_event in enumerate(recovery_events):
        event = audit.mapping(raw_event, f"representative.recovery_events[{index}]")
        if event.get("event") != "RECOVERY_PLAN":
            continue
        plans += 1
        if event.get("protection_sources_committed_only") is not True:
            audit.add(
                f"representative.recovery_events[{index}]",
                "recovery visibility is not restricted to COMMITTED protection",
            )
        if event.get("in_flight_protection_estimate_used") is not False:
            audit.add(
                f"representative.recovery_events[{index}]",
                "recovery consumed in-flight/PENDING protection",
            )
    failure_events = audit.sequence(
        representative.get("failure_events"), "representative.failure_events"
    )
    if failure_events and plans == 0:
        audit.add("representative.recovery_events", "failures exist without audited recovery plans")

    def walk(value: object, path: str) -> None:
        if isinstance(value, Mapping):
            state = value.get("state")
            if state == "PENDING":
                audit.add(path, "PENDING object appeared in recovery-source evidence")
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(representative.get("recovery_source_events", []), "representative.recovery_source_events")


def _audit_forbidden_text(value: object, audit: _Audit, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _audit_forbidden_text(child, audit, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _audit_forbidden_text(child, audit, f"{path}[{index}]")
    elif isinstance(value, str):
        text = value.casefold()
        if any(marker in text for marker in _FORBIDDEN_EVIDENCE_MARKERS):
            audit.add(path, "projected/smoothed evidence is forbidden")


def _audit_result_declarations(value: object, audit: _Audit, path: str) -> None:
    """Reject synthetic declarations without scanning ordinary runtime metadata.

    Failure scheduling legitimately uses a function named ``project_*``.  Function
    names, event causes, and internal policy metadata are not result declarations and
    therefore must not be rejected merely because they contain that substring.
    """

    if not isinstance(value, Mapping):
        return
    for key, child in value.items():
        key_text = str(key).casefold()
        child_path = f"{path}.{key}"
        if key_text in _RESULT_DECLARATION_KEYS:
            _audit_forbidden_text(child, audit, child_path)
        elif isinstance(child, Mapping):
            _audit_result_declarations(child, audit, child_path)
        elif isinstance(child, list):
            for index, item in enumerate(child):
                _audit_result_declarations(item, audit, f"{child_path}[{index}]")


def audit_continuous_scheduler_evidence(
    payload: Mapping[str, object],
    representative: Mapping[str, object],
) -> ContinuousSchedulerAuditReport:
    """Audit scheduler-step, request-timing, and physical-HBM evidence.

    Unlike :func:`audit_formal_algorithm_run`, this API has no AegisKV
    landlord prerequisite and is therefore suitable for both systems in a
    paired paper cell.
    """

    audit = _Audit()
    _audit_result_declarations(payload, audit, "payload")
    _audit_result_declarations(representative, audit, "representative")
    if payload.get("status") != "PASS":
        audit.add("payload.status", "completed experiment status must be PASS")
    metrics = audit.mapping(payload.get("metrics"), "payload.metrics")
    policy = audit.mapping(metrics.get("policy_effects"), "payload.metrics.policy_effects")
    required_policy = {
        "compute_scheduler_model": "VLLM_CONTINUOUS_BATCH_SCHEDULER_STEP",
        "continuous_batch_residency_modeled": True,
    }
    for name, expected in required_policy.items():
        if policy.get(name) != expected:
            audit.add(
                f"payload.metrics.policy_effects.{name}",
                f"must equal {expected!r}",
            )
    report = _audit_continuous_scheduler(payload, representative, audit)
    if audit.errors:
        raise FormalAlgorithmAuditError(audit.errors)
    return report


def audit_formal_algorithm_run(
    payload: Mapping[str, object],
    representative: Mapping[str, object],
    *,
    expected_aimd_enabled: bool = True,
    expected_tiers: tuple[str, ...] = ("PEER_HBM", "STORE_DRAM"),
) -> FormalAlgorithmAuditReport:
    """Audit one completed formal-policy run or raise with every detected defect.

    This is intentionally a strict paper-runner precondition.  A baseline run, a
    legacy ``_ModeledPool`` run, or an artifact that merely asserts formal fields
    without the per-preview exact evidence cannot pass.
    """

    audit = _Audit()
    if not expected_tiers or set(expected_tiers) - {"PEER_HBM", "STORE_DRAM"}:
        raise ValueError("formal audit requires declared nonempty protection tiers")
    _audit_result_declarations(payload, audit, "payload")
    _audit_result_declarations(representative, audit, "representative")
    if payload.get("status") != "PASS":
        audit.add("payload.status", "completed experiment status must be PASS")
    policy = audit.mapping(payload.get("metrics"), "payload.metrics")
    policy = audit.mapping(policy.get("policy_effects"), "payload.metrics.policy_effects")
    required_policy = {
        "landlord_runtime": "FORMAL_SLACK_LANDLORD_CURRENT_DESIGN",
        "formal_suffix_frontier_modeled": True,
        "formal_joint_gain_loss_gate_modeled": True,
        "formal_joint_loss_interpretation": (
            "RECOMPUTE_ONCE_PER_AFFECTED_REQUEST_FROM_TENTATIVE_VICTIM_SET"
        ),
        "aimd_enabled": expected_aimd_enabled,
        "aimd_update_basis": "FIXED_GLOBAL_DES_CONTROL_WINDOW",
        "aimd_quota_lifecycle_uses_formal_safe_tails": True,
        "compute_scheduler_model": "VLLM_CONTINUOUS_BATCH_SCHEDULER_STEP",
        "continuous_batch_residency_modeled": True,
    }
    for name, expected in required_policy.items():
        if policy.get(name) != expected:
            audit.add(
                f"payload.metrics.policy_effects.{name}",
                f"must equal {expected!r}",
            )

    formal_events = audit.sequence(
        representative.get("formal_algorithm2_events"),
        "representative.formal_algorithm2_events",
    )
    if policy.get("formal_algorithm2_event_count") != len(formal_events):
        audit.add(
            "payload.metrics.policy_effects.formal_algorithm2_event_count",
            "does not match representative formal event count",
        )
    previews: list[tuple[Mapping[str, object], Mapping[tuple[str, str, str], set[str]]]] = []
    alias_locations: defaultdict[tuple[str, str, str], set[str]] = defaultdict(set)
    for index, raw_event in enumerate(formal_events):
        event = audit.mapping(raw_event, f"representative.formal_algorithm2_events[{index}]")
        if event.get("event") in {
            "FORMAL_CONTENT_ALIAS_COMMITTED",
            "FORMAL_STORE_CONTENT_ALIAS_COMMITTED",
        }:
            event_prefix = f"representative.formal_algorithm2_events[{index}]"
            span_id = audit.text(event.get("span_id"), f"{event_prefix}.span_id")
            event_path = audit.text(event.get("path"), f"{event_prefix}.path")
            pool_id = audit.text(event.get("pool_id"), f"{event_prefix}.pool_id")
            physical_key = audit.text(
                event.get("physical_chunk_key"), f"{event_prefix}.physical_chunk_key"
            )
            if not pool_id.startswith(f"{event_path}:"):
                audit.add(event_prefix, "content alias crosses formal landlord tiers")
            alias_locations[(span_id, event_path, pool_id)].add(physical_key)
        if event.get("event") == "FORMAL_ALGORITHM2_PREVIEW":
            previews.append(
                (
                    event,
                    {key: set(values) for key, values in alias_locations.items()},
                )
            )
    if not previews:
        audit.add(
            "representative.formal_algorithm2_events",
            "formal paper gate requires at least one Algorithm 2 preview",
        )

    admitted = 0
    pools: dict[str, str] = {}
    rent_observations: list[_RentObservation] = []
    for index, (event, aliases_at_preview) in enumerate(previews):
        pool_id, tier, is_admitted, rent_before, rent_after = _audit_preview(
            event,
            audit,
            f"representative.formal_algorithm2_events.preview[{index}]",
            alias_locations=aliases_at_preview,
        )
        admitted += is_admitted
        preview = audit.mapping(
            event.get("preview"),
            f"representative.formal_algorithm2_events.preview[{index}].preview",
        )
        landlord_applied_raw = preview.get("landlord_applied")
        landlord_applied = (
            bool(is_admitted)
            if landlord_applied_raw is None
            else audit.boolean(
                landlord_applied_raw,
                (
                    "representative.formal_algorithm2_events."
                    f"preview[{index}].preview.landlord_applied"
                ),
            )
        )
        if landlord_applied and not is_admitted:
            audit.add(
                f"representative.formal_algorithm2_events.preview[{index}]",
                "bypassed preview cannot be applied to the landlord",
            )
        old_tier = pools.get(pool_id)
        if old_tier is not None and old_tier != tier:
            audit.add(pool_id, "one physical pool_id was shared across landlord tiers")
        pools[pool_id] = tier
        rent_observations.append(
            _RentObservation(
                pool_id=pool_id,
                timestamp_ns=audit.integer(
                    event.get("timestamp_ns"),
                    f"representative.formal_algorithm2_events.preview[{index}].timestamp_ns",
                ),
                kind="PREVIEW",
                local_index=index,
                rent_before=rent_before,
                rent_after=rent_after if landlord_applied else rent_before,
                path=f"representative.formal_algorithm2_events.preview[{index}]",
            )
        )
    for tier, label in (("PEER_HBM", "Peer-HBM"), ("STORE_DRAM", "Store-DRAM")):
        if tier in expected_tiers and tier not in pools.values():
            audit.add("formal pools", f"missing independent {label} landlord evidence")
        if tier not in expected_tiers and tier in pools.values():
            audit.add("formal pools", f"undeclared {label} landlord executed")

    if expected_aimd_enabled:
        aimd_count, aimd_rent_observations = _audit_aimd(representative, audit)
    else:
        aimd_count = len(audit.sequence(representative.get("aimd_events"), "aimd_events"))
        aimd_rent_observations = []
    if expected_aimd_enabled and aimd_count == 0:
        audit.add("representative.aimd_events", "formal Algorithm 3 evidence is empty")
    if not expected_aimd_enabled and aimd_count:
        audit.add("representative.aimd_events", "disabled Algorithm 3 emitted control decisions")
    _audit_rent_chronology([*rent_observations, *aimd_rent_observations], audit)
    continuous = _audit_continuous_scheduler(payload, representative, audit)
    _audit_pending_visibility(representative, audit)
    _audit_foreground_store_restore_transactions(representative, audit)
    _audit_physical_pools(payload, representative, audit)

    if audit.errors:
        raise FormalAlgorithmAuditError(audit.errors)
    return FormalAlgorithmAuditReport(
        preview_count=len(previews),
        admitted_preview_count=admitted,
        aimd_decision_count=aimd_count,
        continuous_duration_provider_count=continuous.duration_provider_count,
        continuous_request_count=continuous.request_count,
        continuous_step_count=continuous.step_count,
        pool_ids=tuple(sorted(pools)),
        aimd_enabled=expected_aimd_enabled,
    )


def audit_lru_ablation_run(
    payload: Mapping[str, object], representative: Mapping[str, object],
) -> dict[str, object]:
    """Audit LRU control, AIMD arithmetic and physical evidence without Algorithm 2."""
    return _audit_non_landlord_run(payload, representative, aegis_lru=True)


def audit_store_only_control_run(
    payload: Mapping[str, object], representative: Mapping[str, object],
) -> dict[str, object]:
    """Reconstruct the Store-only control's scheduler, pools and transfer lifecycle."""
    return _audit_non_landlord_run(payload, representative, aegis_lru=False)


def _audit_non_landlord_run(
    payload: Mapping[str, object], representative: Mapping[str, object], *, aegis_lru: bool,
) -> dict[str, object]:
    audit = _Audit()
    _audit_result_declarations(payload, audit, "payload")
    _audit_result_declarations(representative, audit, "representative")
    metrics = audit.mapping(payload.get("metrics"), "metrics")
    policy = audit.mapping(metrics.get("policy_effects"), "metrics.policy_effects")
    for field, expected in {
        "landlord_runtime": "MODELED_POOL_BASELINE_POLICY",
        "formal_suffix_frontier_modeled": False,
        "formal_joint_gain_loss_gate_modeled": False,
        "aimd_enabled": aegis_lru,
        "slack_signal_enabled": aegis_lru,
    }.items():
        if policy.get(field) != expected:
            audit.add(field, f"non-landlord control requires {expected!r}")
    events = audit.sequence(representative.get("formal_algorithm2_events"),
                            "formal_algorithm2_events")
    if policy.get("formal_algorithm2_event_count") != len(events):
        audit.add("formal_algorithm2_event_count", "event count does not match raw trace")
    for index, raw_event in enumerate(events):
        event = audit.mapping(raw_event, f"formal_algorithm2_events[{index}]")
        if event.get("event") == "RUNTIME_SHARED_ORDINAL_ADVANCED":
            # This is a connector lifecycle event, also required by the LRU
            # control. It is not a SlackLandlord preview or admission decision.
            outcomes = audit.mapping(event.get("tier_outcomes"), "tier_outcomes")
            if (not outcomes or set(outcomes) - {"PEER_HBM", "STORE_DRAM"}
                    or set(outcomes.values()) - {"COMMITTED", "BYPASS"}
                    or "COMMITTED" not in outcomes.values()):
                audit.add("tier_outcomes", "ordinal advanced without a valid commit")
            continue
        if event.get("event") in {"FORMAL_PREFIX_DROPPED_AT_TERMINAL", "FORMAL_PREFIX_SUFFIX_BYPASS"}:
            # Shared connector queues also drain in the retention ablation.
            if event.get("path") not in {"PEER_HBM", "STORE_DRAM"} or not event.get("plan_id"):
                audit.add("prefix lifecycle", "malformed queued protection release")
            continue
        # The runtime retains ordinary foreground reclaim diagnostics in the
        # same stream. Those observations are not landlord policy decisions.
        if (event.get("event") != "FOREGROUND_KV_RECLAIM_PEER_RESULT"
                or event.get("formal_policy_enabled") is not False):
            audit.add(f"formal_algorithm2_events[{index}]",
                      "LRU must not emit formal Algorithm 2 decisions")
    continuous = _audit_continuous_scheduler(payload, representative, audit)
    if aegis_lru:
        aimd_count, _ = _audit_aimd(representative, audit, require_formal_lifecycle=False)
        if not aimd_count:
            audit.add("aimd_events", "LRU control must preserve Algorithm 3 decisions")
    else:
        aimd_count = 0
        if representative.get("aimd_events") != []:
            audit.add("aimd_events", "Store-only control must not execute Algorithm 3")
    _audit_pending_visibility(representative, audit)
    _audit_foreground_store_restore_transactions(representative, audit)
    _audit_physical_pools(payload, representative, audit)
    if audit.errors:
        raise FormalAlgorithmAuditError(audit.errors)
    body: dict[str, object] = {
        "schema": (
            "moonkvsim.aegiskv.lru-ablation-audit.v1" if aegis_lru
            else "moonkvsim.aegiskv.store-only-control-audit.v1"
        ), "status": "PASS",
        "algorithm2": "NOT_APPLICABLE_REPLACED_WITH_LRU",
        "formal_safe_tail_lifecycle": "NOT_APPLICABLE_REPLACED_WITH_LRU",
        "aimd_arithmetic_and_pressure_audited": aegis_lru,
        "aimd_decision_count": aimd_count,
        "physical_pool_and_pending_visibility_audited": True,
        "continuous_scheduler": continuous.to_dict(),
    }
    return {**body, "fingerprint": sha256_json(body)}
