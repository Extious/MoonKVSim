#!/usr/bin/env python3
"""Build accepted Qwen3-8B workload and intervention evidence for Figure 1."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from moonkvsim.aegiskv.qwen3_8b_acceptance import (
    fingerprint,
    load_json_strict,
    write_json_atomic,
)

SCHEMA = "moonkvsim.aegiskv.qwen3_8b.figure1_evidence.v1"
WORKLOAD_SCHEMA = "moonkvsim.aegiskv.experiment_workload_manifest.v1"
CAMPAIGN_SCHEMA = "moonkvsim.aegiskv.qwen3_8b.failure_campaign.v1"
ACCEPTANCE_SCHEMA = "moonkvsim.aegiskv.qwen3-8b-acceptance-manifest.v1"
EXPECTED_BUCKETS = {"8k": 441, "32k": 536, "64k": 291, "96k": 36, "128k": 0}


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be an array")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_fingerprint(document: Mapping[str, Any], where: str) -> str:
    claimed = document.get("fingerprint")
    body = {key: value for key, value in document.items() if key != "fingerprint"}
    if not isinstance(claimed, str) or fingerprint(body) != claimed:
        raise ValueError(f"{where} self-fingerprint mismatch")
    return claimed


def _bucket(total_tokens: int) -> str:
    if total_tokens <= 8_192:
        return "8k"
    if total_tokens <= 32_768:
        return "32k"
    if total_tokens <= 65_536:
        return "64k"
    if total_tokens <= 98_304:
        return "96k"
    return "128k"


def _workload_rows(path: Path) -> tuple[list[int], Counter[str], Counter[str]]:
    prompts: list[int] = []
    spans_by_workflow: Counter[str] = Counter()
    buckets: Counter[str] = Counter({bucket: 0 for bucket in EXPECTED_BUCKETS})
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            record = _mapping(json.loads(line), f"workload line {line_number}")
            workflow_id = record.get("workflow_id")
            prompt_tokens = record.get("prompt_tokens")
            output_tokens = record.get("output_tokens")
            content = _mapping(
                record.get("messages_or_token_ids"),
                f"workload line {line_number}.messages_or_token_ids",
            )
            token_ids = content.get("value")
            if (
                not isinstance(workflow_id, str)
                or type(prompt_tokens) is not int
                or type(output_tokens) is not int
                or prompt_tokens <= 0
                or output_tokens <= 0
                or not isinstance(token_ids, list)
                or len(token_ids) != prompt_tokens
                or not all(type(token) is int for token in token_ids)
            ):
                raise ValueError(f"workload line {line_number} violates exact-token contract")
            prompts.append(prompt_tokens)
            spans_by_workflow[workflow_id] += 1
            buckets[_bucket(prompt_tokens + output_tokens)] += 1
    return prompts, spans_by_workflow, buckets


def build(
    *,
    workload_path: Path,
    workload_manifest_path: Path,
    campaign_path: Path,
    acceptance_path: Path,
) -> dict[str, Any]:
    workload_manifest = _mapping(
        load_json_strict(workload_manifest_path), "workload manifest"
    )
    campaign = _mapping(load_json_strict(campaign_path), "failure campaign")
    acceptance = _mapping(load_json_strict(acceptance_path), "acceptance manifest")
    workload_manifest_fingerprint = _verify_fingerprint(
        workload_manifest, "workload manifest"
    )
    campaign_fingerprint = _verify_fingerprint(campaign, "failure campaign")
    acceptance_fingerprint = _verify_fingerprint(acceptance, "acceptance manifest")
    if workload_manifest.get("schema") != WORKLOAD_SCHEMA:
        raise ValueError("unsupported workload manifest schema")
    if campaign.get("schema") != CAMPAIGN_SCHEMA or campaign.get("status") != "PASS":
        raise ValueError("unsupported failure campaign")
    if acceptance.get("schema") != ACCEPTANCE_SCHEMA or acceptance.get("status") != "PASS":
        raise ValueError("unsupported acceptance manifest")

    artifact = _mapping(workload_manifest.get("artifact"), "workload artifact")
    if (
        artifact.get("sha256") != _sha256(workload_path)
        or artifact.get("record_count") != 1_304
    ):
        raise ValueError("workload file differs from frozen manifest")
    prompts, spans_by_workflow, buckets = _workload_rows(workload_path)
    manifest_audit = _mapping(
        _mapping(workload_manifest.get("selection"), "selection").get("audit"),
        "selection.audit",
    )
    if (
        len(prompts) != 1_304
        or len(spans_by_workflow) != 160
        or dict(sorted(buckets.items())) != EXPECTED_BUCKETS
        or manifest_audit.get("context_bucket_counts") != EXPECTED_BUCKETS
        or manifest_audit.get("workflow_span_counts")
        != dict(sorted(spans_by_workflow.items()))
    ):
        raise ValueError("workload population differs from frozen audit")

    accepted_attempts = [
        _mapping(raw, "acceptance.attempts[]")
        for raw in _array(acceptance.get("attempts"), "acceptance.attempts")
        if isinstance(raw, Mapping)
        and raw.get("terminal_class") == "VALID"
        and _mapping(raw.get("scenario"), "acceptance scenario").get("kind")
        == "FAILURE_CAMPAIGN"
        and _mapping(raw.get("artifact"), "acceptance artifact").get("fingerprint")
        == campaign_fingerprint
        and _mapping(raw.get("artifact"), "acceptance artifact").get("sha256")
        == _sha256(campaign_path)
    ]
    if len(accepted_attempts) != 1:
        raise ValueError("campaign is not uniquely bound to a VALID acceptance attempt")
    gates = {
        int(_mapping(raw, "gate").get("gate")): _mapping(raw, "gate")
        for raw in _array(accepted_attempts[0].get("gates"), "acceptance gates")
    }
    gate4 = gates.get(4)
    if gate4 is None or gate4.get("status") != "PASS":
        raise ValueError("accepted campaign lacks PASS intervention gate")
    seed_contracts = _array(
        _mapping(gate4.get("evidence"), "gate 4 evidence").get("seed_contracts"),
        "gate 4 seed contracts",
    )
    if len(seed_contracts) != 5:
        raise ValueError("intervention audit must retain exactly five seeds")

    campaign_seeds = {
        int(_mapping(row, "campaign seed")["seed"]): _mapping(row, "campaign seed")
        for row in _array(campaign.get("seeds"), "campaign seeds")
    }
    intervention_rows = []
    for expected_seed, raw in enumerate(seed_contracts):
        contract = _mapping(raw, f"seed contract {expected_seed}")
        outcomes = _mapping(
            contract.get("realized_outcomes_by_system"),
            f"seed contract {expected_seed}.outcomes",
        )
        if contract.get("seed") != expected_seed or len(outcomes) != 2:
            raise ValueError("intervention seed/order/system contract mismatch")
        systems: dict[str, Any] = {}
        for system_id in ("vanilla_mooncake_dram", "aegiskv_unified"):
            outcome = _mapping(outcomes.get(system_id), f"seed {expected_seed}.{system_id}")
            systems[system_id] = {
                "injection_timestamp_ns": outcome.get("injection_timestamp_ns"),
                "active_victim_count": len(
                    _array(outcome.get("active_span_ids"), "active victims")
                ),
                "queued_victim_count": len(
                    _array(outcome.get("queued_span_ids"), "queued victims")
                ),
                "reroute_only_victim_count": len(
                    _array(
                        outcome.get("reroute_only_queued_span_ids"),
                        "reroute-only victims",
                    )
                ),
            }
        intervention_rows.append(
            {
                "seed": expected_seed,
                "focus_span_id": contract.get("focus_span_id"),
                "focus_bucket": _mapping(
                    _array(
                        _mapping(
                            campaign_seeds[expected_seed].get("failure_schedule"),
                            "failure schedule",
                        ).get("events"),
                        "failure events",
                    )[0],
                    "failure event",
                ).get("bucket"),
                "target_workload_progress_per_mille": contract.get(
                    "target_workload_progress_per_mille"
                ),
                "physical_failure_target": contract.get("physical_failure_target"),
                "outage_duration_ns": contract.get("outage_duration_ns"),
                "failure_schedule_fingerprint": contract.get(
                    "failure_schedule_fingerprint"
                ),
                "systems": systems,
            }
        )

    body: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS",
        "workload": {
            "path": workload_path.resolve().as_posix(),
            "sha256": _sha256(workload_path),
            "manifest_path": workload_manifest_path.resolve().as_posix(),
            "manifest_sha256": _sha256(workload_manifest_path),
            "manifest_fingerprint": workload_manifest_fingerprint,
            "record_count": len(prompts),
            "workflow_count": len(spans_by_workflow),
            "exact_token_ids_verified": True,
            "workflow_filtering": False,
            "prompt_tokens": prompts,
            "workflow_span_counts": dict(sorted(spans_by_workflow.items())),
            "context_bucket_counts": EXPECTED_BUCKETS,
        },
        "intervention_audit": {
            "campaign_path": campaign_path.resolve().as_posix(),
            "campaign_sha256": _sha256(campaign_path),
            "campaign_fingerprint": campaign_fingerprint,
            "acceptance_path": acceptance_path.resolve().as_posix(),
            "acceptance_sha256": _sha256(acceptance_path),
            "acceptance_fingerprint": acceptance_fingerprint,
            "seed_contracts": intervention_rows,
            "same_focus_and_progress_within_seed": True,
            "realized_timestamp_and_victims_are_post_treatment": True,
        },
        "scientific_contract": {
            "hypothesis": (
                "The frozen workload spans heterogeneous prompt sizes and workflow "
                "structures, and paired systems receive the same logical failure "
                "intervention within each seed."
            ),
            "independent_unit": "workflow_admission_randomization_seed",
            "modeled_uncalibrated": True,
            "physical_execution": False,
            "paper_ready": False,
        },
    }
    return {**body, "fingerprint": fingerprint(body)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--workload-manifest", type=Path, required=True)
    parser.add_argument("--failure-campaign", type=Path, required=True)
    parser.add_argument("--acceptance-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    document = build(
        workload_path=args.workload,
        workload_manifest_path=args.workload_manifest,
        campaign_path=args.failure_campaign,
        acceptance_path=args.acceptance_manifest,
    )
    write_json_atomic(args.output, document)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
