"""Independent reconstruction of ablation/timing summaries from complete raw runs."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from moonkvsim.aegiskv.formal_algorithm_audit import (
    audit_continuous_scheduler_evidence,
    audit_formal_algorithm_run,
    audit_lru_ablation_run,
    audit_store_only_control_run,
)
from moonkvsim.common.hash import sha256_json


def reconstruct_workflow_metrics(
    raw: Mapping[str, Any], records: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, int], int]:
    """Rebuild the complete workload's intervals and prescribed output counts."""
    payload = raw["payload"]
    spans = {span["span_id"]: span for span in raw["span_details"]}
    if len(spans) != 1304 or len(raw["span_details"]) != 1304 or set(spans) != set(records):
        raise ValueError("raw run does not contain exactly the frozen span population")
    starts: dict[str, int] = {}
    ends: dict[str, int] = {}
    for span_id, span in spans.items():
        workflow_id = records[span_id]["workflow_id"]
        if span["workflow_id"] != workflow_id:
            raise ValueError("raw span changed its workflow identity")
        start, end = span["released_ns"], span["completed_ns"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError("raw completion/release interval is invalid")
        if span["external_output_emissions"] != records[span_id]["output_tokens"]:
            raise ValueError("raw run lost or duplicated external output")
        starts[workflow_id] = min(starts.get(workflow_id, start), start)
        ends[workflow_id] = max(ends.get(workflow_id, end), end)
    wct = {workflow_id: ends[workflow_id] - start for workflow_id, start in starts.items()}
    metrics = payload["metrics"]
    if (len(wct) != 160 or payload["workload"]["workflow_count"] != 160
            or wct != metrics["workflow_completion_time_ns"]["by_workflow_id"]
            or max(ends.values()) != metrics["workload_end_ns"]):
        raise ValueError("workflow completion metrics do not reconstruct from span intervals")
    return wct, max(ends.values())


def reconstruct_transfer_cost(raw: Mapping[str, Any]) -> dict[str, int]:
    """Sum bytes actually transferred, including partial bytes on aborted PUTs."""
    cause_bytes: dict[str, int] = defaultdict(int)
    for transfer in raw["representative"]["transfers"]:
        total, sent, aborted = (transfer[key] for key in
                                ("bytes", "transferred_bytes", "aborted_bytes"))
        if (any(type(value) is not int or value < 0 for value in (total, sent, aborted))
                or sent + aborted != total):
            raise ValueError("physical transfer bytes do not conserve")
        cause_bytes[transfer["cause"]] += sent
    cost = raw["payload"]["metrics"]["resource_cost"]
    if (dict(cause_bytes) != cost["cause_bytes"]
            or cost["transfer_byte_conservation_valid"] is not True):
        raise ValueError("resource cost does not reconstruct from physical transfers")
    return dict(cause_bytes)


def reconstruct_study_run(
    raw: Mapping[str, Any], *, arm: str, focus_span_id: str,
    records: Mapping[str, Mapping[str, Any]], expected_failure: bool,
) -> dict[str, Any]:
    if raw.get("schema") != "moonkvsim.aegiskv.paper_ablation_raw.v1":
        raise ValueError("unknown study raw schema")
    wct, end_ns = reconstruct_workflow_metrics(raw, records)
    payload, representative = raw["payload"], raw["representative"]
    spans = {span["span_id"]: span for span in raw["span_details"]}
    metrics = payload["metrics"]
    events = representative["failure_events"]
    if (len(events) != int(expected_failure)
            or metrics["failure_impact"]["failure_event_count"] != len(events)
            or metrics["gpu_capacity_recovery"]["completed_count"] != len(events)):
        raise ValueError("actual failure/repair population differs from the declared scenario")
    focus = spans[focus_span_id]
    tokens = None
    if expected_failure:
        event = events[0]
        if (event["logical_trigger"]["focus_span_id"] != focus_span_id
                or focus["failure_at_ns"] != event["timestamp_ns"]
                or not focus["released_ns"] <= event["timestamp_ns"] < focus["completed_ns"]):
            raise ValueError("actual focus failure is not bound to the logical intervention")
        tokens = {
            "prompt": records[focus_span_id]["prompt_tokens"],
            "normal": focus["recovery_normal_hbm_local_tokens"],
            "peer": focus["restored_peer_tokens"], "store": focus["restored_store_tokens"],
            "recompute": focus["recompute_tokens"],
        }
        if any(type(value) is not int or value < 0 for value in tokens.values()):
            raise ValueError("invalid recovery token count")
        if sum(tokens[key] for key in ("normal", "peer", "store", "recompute")) != (
            tokens["prompt"]
        ):
            raise ValueError("recovery intervals do not conserve the frozen focus prompt")
    elif any(span["failure_at_ns"] is not None for span in spans.values()):
        raise ValueError("a failure-free run contains failed spans")
    cause_bytes = reconstruct_transfer_cost(raw)
    cost = metrics["resource_cost"]
    scheduler = audit_continuous_scheduler_evidence(payload, representative).to_dict()
    if arm.startswith("store_only"):
        policy = audit_store_only_control_run(payload, representative)
    elif arm == "lru_eviction":
        policy = audit_lru_ablation_run(payload, representative)
    else:
        policy = audit_formal_algorithm_run(
            payload, representative, expected_aimd_enabled=arm != "no_aimd",
        ).to_dict()
    if metrics["policy_effects"]["slack_signal_enabled"] != (
        arm != "no_slack" and not arm.startswith("store_only")
    ):
        raise ValueError("raw slack switch differs from the declared arm")
    return {
        "payload_sha256": sha256_json(payload),
        "representative_sha256": sha256_json(representative),
        "span_details_sha256": sha256_json(raw["span_details"]),
        "workflow_admission": payload["workflow_admission"],
        "randomization": payload["randomization"], "wct_ns": wct,
        "workload_end_ns": end_ns, "failure_event_count": len(events),
        "focus_tokens": tokens, "focus_detail": focus,
        "failure_impact": metrics["failure_impact"],
        "protection_transferred_bytes": sum(
            value for cause, value in cause_bytes.items() if cause.endswith("_PROTECTION")
        ),
        "resource_cost": cost, "continuous_scheduler_audit": scheduler, "policy_audit": policy,
    }
