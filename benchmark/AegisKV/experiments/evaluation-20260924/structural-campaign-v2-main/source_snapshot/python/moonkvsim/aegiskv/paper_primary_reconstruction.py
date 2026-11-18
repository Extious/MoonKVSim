"""Reconstruct primary F0/F1 evidence from complete persisted executions."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from moonkvsim.aegiskv.formal_algorithm_audit import (
    audit_continuous_scheduler_evidence,
    audit_formal_algorithm_run,
    audit_store_only_control_run,
)
from moonkvsim.aegiskv.paper_study_reconstruction import (
    reconstruct_transfer_cost,
    reconstruct_workflow_metrics,
)
from moonkvsim.common.hash import sha256_json


def verify_primary_raw(
    raw: Mapping[str, Any], compact: Mapping[str, Any], *,
    records: Mapping[str, Mapping[str, Any]], expected_variant: Mapping[str, Any],
) -> dict[str, Any]:
    if raw.get("schema") != "moonkvsim.aegiskv.paper_primary_raw.v1":
        raise ValueError("primary run has no supported complete raw evidence")
    if (raw["input_binding_fingerprint"] != compact["input_binding_fingerprint"]
            or raw["variant"] != expected_variant
            or sha256_json(expected_variant) != compact["variant_fingerprint"]):
        raise ValueError("primary raw execution identity or variant changed")
    for name in ("payload", "representative"):
        if sha256_json(raw[name]) != compact[f"full_{name}_sha256"]:
            raise ValueError(f"primary full {name} checksum differs")
        if (sha256_json(compact[name]) != compact[f"compact_{name}_sha256"]
                or any(raw[name].get(key) != value for key, value in compact[name].items())
                or sorted(set(raw[name]) - set(compact[name])) != (
                    compact[f"{name}_omitted_fields"]
                )):
            raise ValueError(f"primary compact {name} does not reconstruct")
    if (raw["span_details"] != compact["span_details"]
            or sha256_json(raw["span_details"]) != compact["span_details_sha256"]
            or raw["journal_sha256"] != compact["journal_sha256"]
            or sha256_json(raw["representative"]["continuous_batch_scheduler"]) != (
                compact["continuous_batch_scheduler_sha256"]
            )):
        raise ValueError("primary spans, journal, or scheduler binding changed")
    payload, representative = raw["payload"], raw["representative"]
    if (payload["variant_fingerprint"] != compact["variant_fingerprint"]
            or payload["scenario"] != compact["scenario"]
            or payload["failure_schedule"] != compact["failure_schedule"]):
        raise ValueError("primary raw payload changed its scenario or intervention")
    failure_count = int(compact["scenario"] == "gpu_failure")
    if (len(representative["failure_events"]) != failure_count
            or payload["metrics"]["failure_impact"]["failure_event_count"] != failure_count
            or payload["metrics"]["gpu_capacity_recovery"]["completed_count"] != failure_count):
        raise ValueError("primary raw run did not execute its failure and repair")
    wct, _ = reconstruct_workflow_metrics(raw, records)
    cause_bytes = reconstruct_transfer_cost(raw)
    focus_recovery = []
    if failure_count:
        spans = {s["span_id"]: s for s in raw["span_details"]}
        for event in payload["failure_schedule"]["events"]:
            span_id = event["focus_span_id"]
            detail = spans[span_id]
            parts = {label: detail[field] for label, field in (
                ("normal", "recovery_normal_hbm_local_tokens"),
                ("peer_local", "restored_peer_local_tokens"),
                ("peer_d2d", "restored_peer_d2d_tokens"),
                ("store", "restored_store_tokens"), ("recompute", "recompute_tokens"),
            )}
            prompt = records[span_id]["prompt_tokens"]
            if (any(type(v) is not int or v < 0 for v in parts.values())
                    or parts["peer_local"] + parts["peer_d2d"] != detail["restored_peer_tokens"]
                    or sum(parts.values()) != prompt):
                raise ValueError("primary focus recovery transport split does not conserve prompt")
            focus_recovery.append({"span_id": span_id, "prompt_tokens": prompt,
                                   "tokens": parts})
    scheduler = audit_continuous_scheduler_evidence(payload, representative).to_dict()
    policy = (audit_formal_algorithm_run(payload, representative).to_dict()
              if compact["system_id"] == "aegiskv_unified"
              else audit_store_only_control_run(payload, representative))
    return {"workflow_count": len(wct), "span_count": len(records),
            "failure_count": failure_count, "cause_bytes": cause_bytes,
            "focus_recovery": focus_recovery,
            "scheduler_audit": scheduler, "policy_audit": policy}
