#!/usr/bin/env python3
"""Classify direct recovery evidence without filtering null or adverse cells."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from moonkvsim.common.hash import sha256_json

MOONCAKE = "vanilla_mooncake_dram"
AEGISKV = "aegiskv_unified"
SOURCE_NAMES = (
    "NORMAL_HBM_LOCAL",
    "PEER_HBM",
    "STORE_DRAM",
    "RECOMPUTE",
)
VICTIM_FIELDS = (
    "active_span_ids",
    "queued_span_ids",
    "reroute_only_queued_span_ids",
)


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{where} must be an array")
    return value


def _integer(value: object, where: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{where} must be an integer")
    return value


def _nonnegative_integer(value: object, where: str) -> int:
    result = _integer(value, where)
    if result < 0:
        raise ValueError(f"{where} must be nonnegative")
    return result


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{where} must be a non-empty string")
    return value


def _fingerprint_body(value: Mapping[str, Any], where: str) -> dict[str, Any]:
    fingerprint = _text(value.get("fingerprint"), f"{where}.fingerprint")
    body = dict(value)
    del body["fingerprint"]
    if fingerprint != sha256_json(body):
        raise ValueError(f"{where} self-fingerprint mismatch")
    return body


def _load(path: Path) -> Mapping[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return _mapping(json.load(stream), "artifact")
    with path.open("rt", encoding="utf-8") as stream:
        return _mapping(json.load(stream), "artifact")


def _event(
    representative: Mapping[str, Any],
    *,
    span_id: str,
    event_name: str,
) -> Mapping[str, Any]:
    matches = [
        _mapping(raw, f"recovery_events.{event_name}")
        for raw in _array(
            representative.get("recovery_events"),
            "representative.recovery_events",
        )
        if isinstance(raw, Mapping)
        and raw.get("span_id") == span_id
        and raw.get("event") == event_name
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {event_name} for focus span {span_id}, "
            f"found {len(matches)}"
        )
    return matches[0]


def _unique_span_detail(
    run: Mapping[str, Any],
    *,
    span_id: str,
    system_id: str,
) -> Mapping[str, Any]:
    matches = [
        _mapping(raw, f"{system_id}.span_details")
        for raw in _array(run.get("span_details"), f"{system_id}.span_details")
        if isinstance(raw, Mapping) and raw.get("span_id") == span_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one span detail for {system_id} focus span "
            f"{span_id}, found {len(matches)}"
        )
    return matches[0]


def _completion_timestamp(
    run: Mapping[str, Any],
    representative: Mapping[str, Any],
    *,
    span_id: str,
    system_id: str,
) -> tuple[int, str]:
    detail_matches = [
        _mapping(raw, f"{system_id}.span_details")
        for raw in _array(run.get("span_details", ()), f"{system_id}.span_details")
        if isinstance(raw, Mapping) and raw.get("span_id") == span_id
    ]
    if len(detail_matches) > 1:
        raise ValueError(f"{system_id} has duplicate focus span details")
    if detail_matches:
        value = detail_matches[0].get("completed_ns")
        if value is not None:
            return _nonnegative_integer(value, f"{system_id}.completed_ns"), (
                "span_details.completed_ns"
            )

    terminal_names = {
        "REQUEST_COMPLETE",
        "SPAN_COMPLETE",
        "AEGIS_EXTERNAL_OUTPUT_COMMITTED",
    }
    candidates: list[Mapping[str, Any]] = []
    for collection_name in ("terminal_events", "events", "journal"):
        raw_collection = representative.get(collection_name)
        if raw_collection is None:
            continue
        for raw in _array(raw_collection, f"{system_id}.{collection_name}"):
            if not isinstance(raw, Mapping):
                continue
            item = _mapping(raw, f"{system_id}.{collection_name}")
            event_name = item.get("event", item.get("kind"))
            if (
                item.get("span_id", item.get("request_id")) == span_id
                and event_name in terminal_names
            ):
                candidates.append(item)
    if len(candidates) != 1:
        raise ValueError(
            f"{system_id} focus completion timestamp is missing or non-unique"
        )
    timestamp = candidates[0].get("timestamp_ns", candidates[0].get("completed_ns"))
    return _nonnegative_integer(timestamp, f"{system_id}.terminal completion"), (
        "unique_terminal_event"
    )


def _canonical_victims(value: object, where: str) -> list[str]:
    result = [_text(item, where) for item in _array(value, where)]
    if result != sorted(result) or len(result) != len(set(result)):
        raise ValueError(f"{where} must be sorted and unique")
    return result


def _failure_evidence(
    representative: Mapping[str, Any],
    *,
    span_id: str,
    where: str,
) -> Mapping[str, Any]:
    matches = [
        _mapping(raw, f"{where}.failure_events")
        for raw in _array(
            representative.get("failure_events"),
            f"{where}.failure_events",
        )
        if isinstance(raw, Mapping)
        and raw.get("event") == "FAILURE_INJECT"
        and _mapping(raw.get("logical_trigger"), "failure.logical_trigger").get(
            "focus_span_id"
        )
        == span_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{where} must contain exactly one focus FAILURE_INJECT event"
        )
    return matches[0]


def _sign(value: int) -> str:
    if value < 0:
        return "IMPROVEMENT"
    if value > 0:
        return "REGRESSION"
    return "UNCHANGED"


def _propagation_label(direct_improves: bool, completion_delta: int) -> str:
    if not direct_improves:
        return "NO_DIRECT_IMPROVEMENT_TO_PROPAGATE"
    if completion_delta < 0:
        return "PROPAGATED_TO_FAILED_REQUEST_COMPLETION"
    if completion_delta == 0:
        return "MASKED_BEFORE_FAILED_REQUEST_COMPLETION"
    return "REVERSED_BY_FAILED_REQUEST_COMPLETION"


def classify(document: Mapping[str, Any]) -> dict[str, Any]:
    if document.get("status") != "PASS":
        raise ValueError("input artifact must have PASS status")
    input_body = _fingerprint_body(document, "input artifact")
    protocol = _mapping(document.get("protocol"), "protocol")
    if protocol.get("paper_causal_mode") is not True:
        raise ValueError("direct recovery classification requires paper_causal_mode")
    focus_span_ids = tuple(
        str(item) for item in _array(protocol.get("focus_span_ids"), "focus_span_ids")
    )
    if len(focus_span_ids) != 1:
        raise ValueError("direct recovery classification requires one focus span")
    focus_span_id = focus_span_ids[0]
    failure_runs = _mapping(
        _mapping(document.get("runs"), "runs").get("gpu_failure"),
        "runs.gpu_failure",
    )

    validation_checks: list[dict[str, Any]] = [
        {"check": "INPUT_STATUS_PASS", "status": "PASS", "evidence": "PASS"},
        {
            "check": "INPUT_SELF_FINGERPRINT",
            "status": "PASS",
            "evidence": document["fingerprint"],
        },
        {"check": "PAPER_CAUSAL_MODE", "status": "PASS", "evidence": True},
        {
            "check": "EXACTLY_ONE_FOCUS_SPAN",
            "status": "PASS",
            "evidence": focus_span_id,
        },
    ]
    systems: dict[str, dict[str, Any]] = {}
    schedules: dict[str, Mapping[str, Any]] = {}
    schedule_fingerprints: dict[str, str] = {}
    failure_evidence: dict[str, Mapping[str, Any]] = {}
    for system_id in (MOONCAKE, AEGISKV):
        run = _mapping(failure_runs.get(system_id), f"gpu_failure.{system_id}")
        representative = _mapping(
            run.get("representative"), f"{system_id}.representative"
        )
        schedule = _mapping(
            run.get("failure_schedule"), f"{system_id}.failure_schedule"
        )
        schedule_fingerprint = _text(
            run.get("failure_schedule_fingerprint"),
            f"{system_id}.failure_schedule_fingerprint",
        )
        if schedule_fingerprint != sha256_json(schedule):
            raise ValueError(f"{system_id} failure schedule fingerprint mismatch")
        if schedule.get("failure_count") != 1:
            raise ValueError(f"{system_id} failure schedule must have one event")
        schedule_events = _array(
            schedule.get("events"), f"{system_id}.failure_schedule.events"
        )
        if len(schedule_events) != 1:
            raise ValueError(f"{system_id} failure schedule must have one event")
        scheduled_event = _mapping(
            schedule_events[0], f"{system_id}.failure_schedule.events[0]"
        )
        if scheduled_event.get("focus_span_id") != focus_span_id:
            raise ValueError(f"{system_id} schedule focus identity mismatch")
        if (
            scheduled_event.get("target_gpu_id_semantics")
            != "FROZEN_PHYSICAL_FAILURE_TARGET"
        ):
            raise ValueError(f"{system_id} physical failure target is not frozen")
        if (
            scheduled_event.get("impact_contract") is not None
            or scheduled_event.get("profile_impact_contracts") is not None
        ):
            raise ValueError(
                "paper causal classification rejects frozen post-treatment "
                "victim partitions"
            )

        observed_failure = _failure_evidence(
            representative, span_id=focus_span_id, where=system_id
        )
        observed_victims = {
            field: _canonical_victims(
                observed_failure.get(
                    f"impacted_{field}"
                    if field != "reroute_only_queued_span_ids"
                    else field
                ),
                f"{system_id}.failure_event.{field}",
            )
            for field in VICTIM_FIELDS
        }
        if focus_span_id not in observed_victims["active_span_ids"]:
            raise ValueError(f"{system_id} focus span is not an active victim")

        plan = _event(
            representative,
            span_id=focus_span_id,
            event_name="RECOVERY_PLAN",
        )
        ready = _event(
            representative,
            span_id=focus_span_id,
            event_name="PROMPT_SUFFIX_RECOMPUTE_COMPLETE",
        )
        materialized = _event(
            representative,
            span_id=focus_span_id,
            event_name="CONTINUOUS_RECOVERY_PREFIX_MATERIALIZED",
        )
        source_tokens = _mapping(plan.get("source_tokens"), "source_tokens")
        if set(source_tokens) != set(SOURCE_NAMES):
            raise ValueError(
                f"{system_id} RECOVERY_PLAN must contain exactly {SOURCE_NAMES}"
            )
        tokens = {
            name: _nonnegative_integer(
                source_tokens.get(name), f"{system_id}.source_tokens.{name}"
            )
            for name in SOURCE_NAMES
        }
        detail = _unique_span_detail(
            run, span_id=focus_span_id, system_id=system_id
        )
        logical_trigger = _mapping(
            observed_failure.get("logical_trigger"),
            f"{system_id}.failure_event.logical_trigger",
        )
        prompt_tokens_value = plan.get("prompt_tokens")
        if prompt_tokens_value is None:
            prompt_tokens_value = detail.get("prompt_tokens")
        if prompt_tokens_value is None:
            prompt_tokens_value = logical_trigger.get("prompt_tokens")
        if prompt_tokens_value is None:
            progress_evidence = _mapping(
                logical_trigger.get("continuous_progress_evidence"),
                f"{system_id}.failure_event.logical_trigger."
                "continuous_progress_evidence",
            )
            prompt_tokens_value = progress_evidence.get("prompt_tokens")
        prompt_tokens = _nonnegative_integer(
            prompt_tokens_value, f"{system_id}.prompt_tokens"
        )
        if sum(tokens.values()) != prompt_tokens:
            raise ValueError(f"{system_id} recovery source tokens do not conserve prompt")
        effective_prefix = _nonnegative_integer(
            plan.get("effective_prefix_tokens"),
            f"{system_id}.effective_prefix_tokens",
        )
        non_recompute = sum(tokens[name] for name in SOURCE_NAMES[:-1])
        if effective_prefix != non_recompute or effective_prefix != (
            prompt_tokens - tokens["RECOMPUTE"]
        ):
            raise ValueError(f"{system_id} effective recovery prefix is inconsistent")
        peer_local = detail.get("restored_peer_local_tokens")
        peer_d2d = detail.get("restored_peer_d2d_tokens")
        if peer_local is not None or peer_d2d is not None:
            if peer_local is None or peer_d2d is None:
                raise ValueError(f"{system_id} peer split evidence is incomplete")
            if (
                _nonnegative_integer(peer_local, f"{system_id}.peer_local")
                + _nonnegative_integer(peer_d2d, f"{system_id}.peer_d2d")
                != tokens["PEER_HBM"]
            ):
                raise ValueError(f"{system_id} peer token split is inconsistent")
        completion_ns, completion_source = _completion_timestamp(
            run,
            representative,
            span_id=focus_span_id,
            system_id=system_id,
        )
        injection_ns = _nonnegative_integer(
            observed_failure.get("timestamp_ns"),
            f"{system_id}.failure_event.timestamp_ns",
        )
        prefix_materialized_ns = _nonnegative_integer(
            materialized.get("timestamp_ns"),
            f"{system_id}.prefix_materialized_ns",
        )
        recovery_ready_ns = _nonnegative_integer(
            ready.get("timestamp_ns"), f"{system_id}.recovery_ready_ns"
        )
        if min(prefix_materialized_ns, recovery_ready_ns, completion_ns) < injection_ns:
            raise ValueError(f"{system_id} recovery timestamp precedes failure injection")
        systems[system_id] = {
            "prompt_tokens": prompt_tokens,
            "source_tokens": tokens,
            "effective_prefix_tokens": effective_prefix,
            "injection_timestamp_ns": injection_ns,
            "prefix_materialized_ns": prefix_materialized_ns,
            "prefix_materialization_latency_ns": prefix_materialized_ns - injection_ns,
            "recovery_ready_ns": recovery_ready_ns,
            "recovery_ready_latency_ns": recovery_ready_ns - injection_ns,
            "failed_request_completion_ns": completion_ns,
            "failure_to_completion_latency_ns": completion_ns - injection_ns,
            "failed_request_completion_source": completion_source,
        }
        schedules[system_id] = schedule
        schedule_fingerprints[system_id] = schedule_fingerprint
        failure_evidence[system_id] = observed_failure

    if len(set(schedule_fingerprints.values())) != 1:
        raise ValueError("Mooncake and AegisKV failure schedule fingerprints differ")
    if schedules[MOONCAKE] != schedules[AEGISKV]:
        raise ValueError("Mooncake and AegisKV failure schedules differ")
    scheduled_event = _mapping(
        _array(schedules[MOONCAKE]["events"], "failure_schedule.events")[0],
        "failure_schedule.events[0]",
    )
    realized_outcomes: dict[str, dict[str, Any]] = {}
    for system_id in (MOONCAKE, AEGISKV):
        evidence = failure_evidence[system_id]
        realized_outcomes[system_id] = {
            "injection_timestamp_ns": _nonnegative_integer(
                evidence.get("timestamp_ns"),
                f"{system_id}.failure_event.timestamp_ns",
            ),
            "active_span_ids": list(
                _canonical_victims(
                    evidence.get("impacted_active_span_ids"),
                    f"{system_id}.failure_event.active_span_ids",
                )
            ),
            "queued_span_ids": list(
                _canonical_victims(
                    evidence.get("impacted_queued_span_ids"),
                    f"{system_id}.failure_event.queued_span_ids",
                )
            ),
            "reroute_only_queued_span_ids": list(
                _canonical_victims(
                    evidence.get("reroute_only_queued_span_ids"),
                    f"{system_id}.failure_event.reroute_only_queued_span_ids",
                )
            ),
        }
    matched_fields = {
        "focus_span_id": focus_span_id,
        "target_gpu_id": scheduled_event.get("target_gpu_id"),
        "target_workload_progress_per_mille": _mapping(
            scheduled_event.get("workload_position"), "workload_position"
        ).get("target_progress_per_mille"),
        "outage_duration_ns": scheduled_event.get("repair_after_ns"),
        "realized_outcomes_by_system": realized_outcomes,
    }
    mooncake_trigger = _mapping(
        failure_evidence[MOONCAKE].get("logical_trigger"), "Mooncake.logical_trigger"
    )
    aegiskv_trigger = _mapping(
        failure_evidence[AEGISKV].get("logical_trigger"), "AegisKV.logical_trigger"
    )
    if failure_evidence[MOONCAKE].get("target_gpu_id") != failure_evidence[AEGISKV].get(
        "target_gpu_id"
    ):
        raise ValueError("failure evidence differs for target_gpu_id")
    if mooncake_trigger.get("progress_per_mille") != aegiskv_trigger.get(
        "progress_per_mille"
    ):
        raise ValueError("failure evidence differs for focus progress")
    if mooncake_trigger.get("progress_per_mille") != _mapping(
        scheduled_event.get("trigger"), "trigger"
    ).get("progress_per_mille"):
        raise ValueError("failure evidence progress differs from schedule")
    validation_checks.extend(
        [
            {
                "check": "MATCHED_SINGLE_FAILURE_SCHEDULE",
                "status": "PASS",
                "evidence": next(iter(schedule_fingerprints.values())),
            },
            {
                "check": "FROZEN_PHYSICAL_TARGET",
                "status": "PASS",
                "evidence": scheduled_event.get("target_gpu_id"),
            },
            {
                "check": "NO_FROZEN_POST_TREATMENT_IMPACT_CONTRACT",
                "status": "PASS",
                "evidence": None,
            },
            {
                "check": "PROFILE_IMPACT_CONTRACTS_ABSENT_OR_NULL",
                "status": "PASS",
                "evidence": None,
            },
            {
                "check": "MATCHED_INTERVENTION_AND_REALIZED_OUTCOMES",
                "status": "PASS",
                "evidence": matched_fields,
            },
            {
                "check": "PROMPT_TOKEN_CONSERVATION",
                "status": "PASS",
                "evidence": {
                    system_id: {
                        "prompt_tokens": systems[system_id]["prompt_tokens"],
                        "source_tokens": systems[system_id]["source_tokens"],
                        "effective_prefix_tokens": systems[system_id][
                            "effective_prefix_tokens"
                        ],
                    }
                    for system_id in (MOONCAKE, AEGISKV)
                },
            },
            {
                "check": "REQUIRED_TIMESTAMPS_PRESENT",
                "status": "PASS",
                "evidence": {
                    system_id: {
                        key: systems[system_id][key]
                        for key in (
                            "prefix_materialized_ns",
                            "recovery_ready_ns",
                            "failed_request_completion_ns",
                        )
                    }
                    for system_id in (MOONCAKE, AEGISKV)
                },
            },
        ]
    )

    mooncake = systems[MOONCAKE]
    aegiskv = systems[AEGISKV]
    recompute_delta = (
        aegiskv["source_tokens"]["RECOMPUTE"]
        - mooncake["source_tokens"]["RECOMPUTE"]
    )
    ready_delta_ns = (
        aegiskv["recovery_ready_latency_ns"]
        - mooncake["recovery_ready_latency_ns"]
    )
    prefix_delta_ns = (
        aegiskv["prefix_materialization_latency_ns"]
        - mooncake["prefix_materialization_latency_ns"]
    )
    completion_delta_ns = (
        aegiskv["failure_to_completion_latency_ns"]
        - mooncake["failure_to_completion_latency_ns"]
    )
    direct_improves = recompute_delta < 0 or ready_delta_ns < 0
    direct_regresses = recompute_delta > 0 or ready_delta_ns > 0
    if recompute_delta <= 0 and ready_delta_ns <= 0 and direct_improves:
        classification = "DIRECT_RECOVERY_BENEFIT_CONCORDANT"
    elif direct_improves and direct_regresses:
        classification = "DIRECT_RECOVERY_MIXED"
    elif recompute_delta == 0 and ready_delta_ns == 0:
        classification = "SOURCE_SUBSTITUTION_OR_NULL_DIRECT_MECHANISM"
    else:
        classification = "ADVERSE_DIRECT_MECHANISM"
    deltas = {
        "recompute_tokens": recompute_delta,
        "prefix_materialization_latency_ns": prefix_delta_ns,
        "recovery_ready_latency_ns": ready_delta_ns,
        "failure_to_completion_latency_ns": completion_delta_ns,
    }
    body = {
        "schema": "moonkvsim.aegiskv.qwen3_8b.direct_recovery_classification.v2",
        "status": "PASS",
        "input_artifact_fingerprint": document.get("fingerprint"),
        "focus_span_id": focus_span_id,
        "systems": systems,
        "validation": {
            "status": "PASS",
            "fail_closed": True,
            "checks": validation_checks,
            "input_body_sha256": sha256_json(input_body),
        },
        "paired_deltas_aegiskv_minus_mooncake": deltas,
        "delta_signs": {key: _sign(value) for key, value in deltas.items()},
        "direct_mechanism_exercised": direct_improves,
        "classification": classification,
        "propagation_label": _propagation_label(
            direct_improves, completion_delta_ns
        ),
        "classification_axes": ["recompute_tokens", "recovery_ready_latency_ns"],
        "diagnostic_only_axes": [
            "prefix_materialization_latency_ns",
            "failure_to_completion_latency_ns",
        ],
        "effect_direction_gate_applied": False,
        "all_cells_retained": True,
        "retention_rule": "ALL_VALID_CELLS_RETAINED_INCLUDING_NULL_AND_ADVERSE",
    }
    return {**body, "fingerprint": sha256_json(body)}


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = classify(_load(args.input))
    _write_atomic(args.output, result)
    print(json.dumps({"status": "PASS", "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
