from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from moonkvsim.aegiskv import paper_study_reconstruction as reconstruction
from moonkvsim.aegiskv.qwen3_8b_acceptance import AcceptanceError, source_root_for_attempt


@dataclass
class _Report:
    def to_dict(self) -> dict[str, str]:
        return {"status": "PASS"}


def _raw(monkeypatch: pytest.MonkeyPatch, *, failed: bool = True) -> tuple[dict, dict]:
    # These tests isolate independent numerical reconstruction. Public scheduler
    # and policy auditors have their own real-event regression suites.
    monkeypatch.setattr(reconstruction, "audit_continuous_scheduler_evidence",
                        lambda *args, **kwargs: _Report())
    monkeypatch.setattr(reconstruction, "audit_formal_algorithm_run",
                        lambda *args, **kwargs: _Report())
    records, spans = {}, []
    for index in range(1304):
        span_id, workflow_id = f"span-{index}", f"workflow-{index % 160}"
        records[span_id] = {"workflow_id": workflow_id, "prompt_tokens": 100,
                            "output_tokens": 2}
        spans.append({
            "span_id": span_id, "workflow_id": workflow_id,
            "released_ns": 10, "completed_ns": 110 + index,
            "external_output_emissions": 2,
            "failure_at_ns": 30 if failed and index == 0 else None,
            "recovery_normal_hbm_local_tokens": 10,
            "restored_peer_tokens": 20, "restored_store_tokens": 30,
            "recompute_tokens": 40,
        })
    wct = {f"workflow-{i}": max(s["completed_ns"] for s in spans
                               if s["workflow_id"] == f"workflow-{i}") - 10
           for i in range(160)}
    return {
        "schema": "moonkvsim.aegiskv.paper_ablation_raw.v1",
        "span_details": spans,
        "payload": {
            "workload": {"workflow_count": 160}, "workflow_admission": {},
            "randomization": {}, "metrics": {
                "workflow_completion_time_ns": {"by_workflow_id": wct},
                "workload_end_ns": 1413,
                "failure_impact": {"failure_event_count": int(failed)},
                "gpu_capacity_recovery": {"completed_count": int(failed)},
                "resource_cost": {"cause_bytes": {"PEER_PROTECTION": 60,
                                                    "STORE_RECOVERY": 40},
                                  "transfer_byte_conservation_valid": True},
                "policy_effects": {"slack_signal_enabled": True},
            },
        },
        "representative": {
            "failure_events": [{"logical_trigger": {"focus_span_id": "span-0"},
                                "timestamp_ns": 30}] if failed else [],
            "transfers": [{"cause": "PEER_PROTECTION", "bytes": 80,
                           "transferred_bytes": 60, "aborted_bytes": 20},
                          {"cause": "STORE_RECOVERY", "bytes": 40,
                           "transferred_bytes": 40, "aborted_bytes": 0}],
        },
    }, records


@pytest.mark.parametrize("failed", [False, True])
def test_numerical_reconstruction_uses_complete_population(monkeypatch, failed):
    raw, records = _raw(monkeypatch, failed=failed)
    result = reconstruction.reconstruct_study_run(
        raw, arm="full", focus_span_id="span-0", records=records, expected_failure=failed,
    )
    assert len(result["wct_ns"]) == 160
    assert result["wct_ns"]["workflow-0"] == 1380
    assert result["protection_transferred_bytes"] == 60
    assert result["focus_tokens"] == ({"prompt": 100, "normal": 10, "peer": 20,
                                        "store": 30, "recompute": 40} if failed else None)


@pytest.mark.parametrize("tamper,match", [
    ("population", "span population"), ("workflow", "workflow identity"),
    ("output", "external output"), ("interval", "interval is invalid"),
    ("wct", "completion metrics"), ("end", "completion metrics"),
    ("repair", "failure/repair"), ("focus", "logical intervention"),
    ("token", "conserve the frozen focus prompt"), ("negative", "invalid recovery"),
    ("transfer", "transfer bytes do not conserve"), ("cost", "resource cost"),
])
def test_reconstruction_rejects_changed_raw_numerical_evidence(monkeypatch, tamper, match):
    raw, records = _raw(monkeypatch)
    spans, metrics = raw["span_details"], raw["payload"]["metrics"]
    if tamper == "population":
        spans[-1] = dict(spans[0])
    elif tamper == "workflow":
        spans[0]["workflow_id"] = "workflow-1"
    elif tamper == "output":
        spans[0]["external_output_emissions"] = 3
    elif tamper == "interval":
        spans[0]["released_ns"] = 110
    elif tamper == "wct":
        metrics["workflow_completion_time_ns"]["by_workflow_id"]["workflow-0"] += 1
    elif tamper == "end":
        metrics["workload_end_ns"] += 1
    elif tamper == "repair":
        metrics["gpu_capacity_recovery"]["completed_count"] = 0
    elif tamper == "focus":
        spans[0]["failure_at_ns"] = 31
    elif tamper == "token":
        spans[0]["recompute_tokens"] += 1
    elif tamper == "negative":
        spans[0]["restored_peer_tokens"] = -1
    elif tamper == "transfer":
        raw["representative"]["transfers"][0]["aborted_bytes"] = 0
    else:
        metrics["resource_cost"]["cause_bytes"]["PEER_PROTECTION"] += 1
    with pytest.raises(ValueError, match=match):
        reconstruction.reconstruct_study_run(
            raw, arm="full", focus_span_id="span-0", records=records, expected_failure=True,
        )


def test_preserved_execution_source_resolves_separately(tmp_path: Path):
    frozen = tmp_path / "snapshots" / "source-v2"
    frozen.mkdir(parents=True)
    assert source_root_for_attempt(tmp_path, {}) == tmp_path
    assert source_root_for_attempt(tmp_path, {"source_root": "snapshots/source-v2"}) == frozen
    (tmp_path / "alias").symlink_to(frozen, target_is_directory=True)
    for bad in ("alias", "../outside", "/tmp", "missing", "snapshots/./source-v2"):
        with pytest.raises(AcceptanceError):
            source_root_for_attempt(tmp_path, {"source_root": bad})


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("tamper", [None, "compact", "raw", "scheduler", "variant", "numeric"])
def test_primary_reconstruction_binds_complete_content(monkeypatch, tamper, failed):
    from moonkvsim.aegiskv import paper_primary_reconstruction as primary
    from moonkvsim.common.hash import sha256_json

    raw, records = _raw(monkeypatch, failed=failed)
    raw["span_details"][0].update(restored_peer_local_tokens=5, restored_peer_d2d_tokens=15)
    raw["schema"] = "moonkvsim.aegiskv.paper_primary_raw.v1"
    raw["input_binding_fingerprint"] = "binding"
    variant = {"variant_id": "aegiskv_unified"}
    raw["variant"] = variant
    raw["journal_sha256"] = "journal"
    scenario = "gpu_failure" if failed else "no_failure"
    schedule = {"events": [{"focus_span_id": "span-0"}]} if failed else None
    raw["payload"].update(variant_fingerprint=sha256_json(variant), scenario=scenario,
                          failure_schedule=schedule)
    raw["representative"]["continuous_batch_scheduler"] = {"complete_steps": [1, 2, 3]}
    compact = {
        "input_binding_fingerprint": "binding", "variant_fingerprint": sha256_json(variant),
        "system_id": "aegiskv_unified", "scenario": scenario, "failure_schedule": schedule,
        "payload": {"scenario": scenario}, "representative": {
            "failure_events": list(raw["representative"]["failure_events"])},
        "span_details": list(raw["span_details"]),
        "span_details_sha256": sha256_json(raw["span_details"]), "journal_sha256": "journal",
        "continuous_batch_scheduler_sha256": sha256_json(
            raw["representative"]["continuous_batch_scheduler"]
        ),
    }
    for name in ("payload", "representative"):
        compact[f"full_{name}_sha256"] = sha256_json(raw[name])
        compact[f"compact_{name}_sha256"] = sha256_json(compact[name])
        compact[f"{name}_omitted_fields"] = sorted(set(raw[name])-set(compact[name]))
    monkeypatch.setattr(primary, "audit_continuous_scheduler_evidence", lambda *a: _Report())
    monkeypatch.setattr(primary, "audit_formal_algorithm_run", lambda *a: _Report())
    if tamper == "compact":
        compact["payload"]["scenario"] = "changed"
    elif tamper == "raw":
        raw["representative"]["transfers"] = []
    elif tamper == "scheduler":
        compact["continuous_batch_scheduler_sha256"] = "changed"
    elif tamper == "variant":
        raw["variant"] = {"variant_id": "other"}
    elif tamper == "numeric":
        raw["payload"]["metrics"]["workload_end_ns"] += 1
        compact["full_payload_sha256"] = sha256_json(raw["payload"])
    if tamper is None:
        report = primary.verify_primary_raw(raw, compact, records=records, expected_variant=variant)
        assert (report["workflow_count"], report["span_count"], report["failure_count"]) == (
            160, 1304, int(failed),
        )
        if failed:
            assert report["focus_recovery"][0]["tokens"]["peer_d2d"] == 15
    else:
        with pytest.raises(ValueError):
            primary.verify_primary_raw(raw, compact, records=records, expected_variant=variant)
