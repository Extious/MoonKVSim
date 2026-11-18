"""Fail-closed aggregation of Qwen3-8B paper-causal failure seed artifacts."""

from __future__ import annotations

import gzip
import importlib.util
import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from moonkvsim.aegiskv.qwen3_8b_acceptance import (
    AcceptanceError,
    fingerprint,
    load_json_strict,
    sha256_file,
    write_json_atomic,
)

CAMPAIGN_SCHEMA: Final = "moonkvsim.aegiskv.qwen3_8b.failure_campaign.v1"
EXPECTED_POSTFIX_SCHEMA: Final = "moonkvsim.aegiskv.qwen3_8b.postfix_preview.v1"
EXPECTED_CLASSIFIER_SCHEMA: Final = (
    "moonkvsim.aegiskv.qwen3_8b.direct_recovery_classification.v2"
)
EXPECTED_SEEDS: Final = (0, 1, 2, 3, 4)
SYSTEM_IDS: Final = ("vanilla_mooncake_dram", "aegiskv_unified")
DIRECT_CLASSES: Final = {
    "DIRECT_RECOVERY_BENEFIT_CONCORDANT",
    "DIRECT_RECOVERY_MIXED",
    "SOURCE_SUBSTITUTION_OR_NULL_DIRECT_MECHANISM",
    "ADVERSE_DIRECT_MECHANISM",
}
ALLOWED_PANEL_IDS: Final = (
    "FIGURE_3_A",
    "FIGURE_3_B",
    "FIGURE_3_C",
    "FIGURE_3_D",
    "FIGURE_4_B",
    "FIGURE_4_C",
    "FIGURE_4_D",
)
T_975: Final = {
    1: 12.706204736,
    2: 4.30265273,
    3: 3.182446305,
    4: 2.776445105,
}


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AcceptanceError(f"{where} must be an object")
    return cast(Mapping[str, Any], value)


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise AcceptanceError(f"{where} must be an array")
    return value


def _integer(value: object, where: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = "" if minimum is None else f" >= {minimum}"
        raise AcceptanceError(f"{where} must be an integer{suffix}")
    return value


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise AcceptanceError(f"{where} must be a non-empty string")
    return value


def _load_document(path: Path) -> Mapping[str, Any]:
    try:
        gzip_encoded = path.read_bytes()[:2] == b"\x1f\x8b"
    except OSError as error:
        raise AcceptanceError(f"cannot read JSON {path}: {error}") from error
    if gzip_encoded:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                import json

                return _mapping(json.load(stream), str(path))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise AcceptanceError(f"cannot load JSON {path}: {error}") from error
    return _mapping(load_json_strict(path), str(path))


def _verify_fingerprint(document: Mapping[str, Any], where: str) -> str:
    claimed = _text(document.get("fingerprint"), f"{where}.fingerprint")
    body = {key: value for key, value in document.items() if key != "fingerprint"}
    if fingerprint(body) != claimed:
        raise AcceptanceError(f"{where} self-fingerprint mismatch")
    return claimed


def _classifier_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("qwen3_8b_direct_classifier", path)
    if spec is None or spec.loader is None:
        raise AcceptanceError(f"cannot import classifier {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _nearest_rank(values: Mapping[str, int], percentile: int) -> dict[str, Any]:
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    rank = max(1, (len(ordered) * percentile + 99) // 100)
    workflow_id, value = ordered[rank - 1]
    return {
        "rule": "nearest_rank",
        "percentile": percentile,
        "population_size": len(ordered),
        "rank": rank,
        "workflow_id": workflow_id,
        "value_ns": value,
    }


def _distribution(values: Mapping[str, int]) -> dict[str, Any]:
    ordered = sorted(values.values())
    return {
        "population": "paired_workflows_within_seed",
        "independent_for_inference": False,
        "count": len(ordered),
        "min_ns": ordered[0],
        "mean_ns": sum(ordered) / len(ordered),
        "p95_ns": ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)],
        "max_ns": ordered[-1],
    }


def _t_interval(values: Sequence[int | float]) -> dict[str, Any]:
    count = len(values)
    mean = sum(values) / count
    if count < 2:
        return {
            "method": "two_sided_student_t_95",
            "eligible": False,
            "n": count,
            "degrees_of_freedom": None,
            "mean": mean,
            "low": None,
            "high": None,
            "limitation": "AT_LEAST_TWO_INDEPENDENT_SEEDS_REQUIRED",
        }
    df = count - 1
    if df not in T_975:
        raise AcceptanceError("unsupported Student-t sample size")
    variance = sum((float(value) - mean) ** 2 for value in values) / df
    half_width = T_975[df] * math.sqrt(variance / count)
    return {
        "method": "two_sided_student_t_95",
        "eligible": True,
        "n": count,
        "degrees_of_freedom": df,
        "critical_value": T_975[df],
        "mean": mean,
        "low": mean - half_width,
        "high": mean + half_width,
        "independent_unit": "workflow_admission_randomization_seed",
    }


def _run(
    document: Mapping[str, Any],
    system_id: str,
    scenario: str = "gpu_failure",
) -> Mapping[str, Any]:
    return _mapping(
        _mapping(
            _mapping(document.get("runs"), "runs").get(scenario),
            f"runs.{scenario}",
        ).get(system_id),
        f"runs.{scenario}.{system_id}",
    )


def _workflow_wct(run: Mapping[str, Any], where: str) -> dict[str, int]:
    metric = _mapping(
        _mapping(_mapping(run.get("payload"), f"{where}.payload").get("metrics"), "metrics").get(
            "workflow_completion_time_ns"
        ),
        f"{where}.workflow_completion_time_ns",
    )
    values = {
        _text(key, f"{where}.workflow_id"): _integer(
            value, f"{where}.workflow_wct[{key}]", minimum=1
        )
        for key, value in _mapping(
            metric.get("by_workflow_id"), f"{where}.by_workflow_id"
        ).items()
    }
    if not values:
        raise AcceptanceError(f"{where} has no workflow WCT map")
    return values


def _admission_binding(run: Mapping[str, Any], where: str) -> tuple[list[str], str]:
    payload = _mapping(run.get("payload"), f"{where}.payload")
    admission = _mapping(payload.get("workflow_admission"), f"{where}.workflow_admission")
    if (
        admission.get("order_policy")
        != "observed_submit_then_seeded_sha256_workflow_permutation"
    ):
        raise AcceptanceError(f"{where} lacks seeded admission randomization")
    order = [_text(item, f"{where}.realized_workflow_order") for item in _array(
        admission.get("realized_workflow_order"), f"{where}.realized_workflow_order"
    )]
    if len(order) != len(set(order)):
        raise AcceptanceError(f"{where} admission order contains duplicate workflows")
    claimed = _text(
        admission.get("realized_workflow_order_sha256"),
        f"{where}.realized_workflow_order_sha256",
    )
    if fingerprint(order) != claimed:
        raise AcceptanceError(f"{where} admission order fingerprint mismatch")
    return order, claimed


def _selection_event(
    run: Mapping[str, Any],
    *,
    focus_span_id: str,
    where: str,
) -> dict[str, Any]:
    representative = _mapping(run.get("representative"), f"{where}.representative")
    matches = [
        _mapping(item, f"{where}.recovery_events[]")
        for item in _array(
            representative.get("recovery_events"), f"{where}.recovery_events"
        )
        if isinstance(item, Mapping)
        and item.get("event") == "RECOVERY_SOURCE_SELECTION"
        and item.get("span_id") == focus_span_id
    ]
    if len(matches) != 1:
        raise AcceptanceError(
            f"{where} requires exactly one focus RECOVERY_SOURCE_SELECTION event"
        )
    event = matches[0]
    if (
        event.get("candidate_order") != ["PEER_FIRST_CONTROL", "STORE_FIRST"]
        or event.get("control_strategy") != "PEER_FIRST_CONTROL"
        or event.get("prediction_scope")
        != "snapshot_active_flows_plus_candidate_no_future_arrivals"
    ):
        raise AcceptanceError(f"{where} selector protocol mismatch")
    candidates = _mapping(event.get("candidates"), f"{where}.selector.candidates")
    if set(candidates) != {"PEER_FIRST_CONTROL", "STORE_FIRST"}:
        raise AcceptanceError(f"{where} selector lacks exact control/candidate pair")
    assertions = _mapping(
        event.get("invariance_assertions"), f"{where}.selector.invariance_assertions"
    )
    if any(
        assertions.get(field) is not True
        for field in (
            "same_effective_prefix",
            "same_recompute_suffix",
            "same_target_gpu",
            "source_ownership_only",
            "candidate_evaluation_side_effect_free",
        )
    ):
        raise AcceptanceError(f"{where} selector causal invariance failed")
    selected = _text(event.get("selected_strategy"), f"{where}.selected_strategy")
    if selected not in candidates:
        raise AcceptanceError(f"{where} selected strategy is absent from candidates")
    selected_candidate = _mapping(candidates[selected], f"{where}.selected_candidate")
    _mapping(candidates["PEER_FIRST_CONTROL"], f"{where}.control_candidate")
    for strategy, candidate in candidates.items():
        if type(candidate.get("feasible")) is not bool:
            raise AcceptanceError(f"{where}.{strategy}.feasible must be boolean")
        key = _array(candidate.get("selection_key"), f"{where}.{strategy}.selection_key")
        if len(key) != 6 or any(type(value) is not int for value in key):
            raise AcceptanceError(f"{where}.{strategy}.selection_key is malformed")
        intervals = _array(candidate.get("intervals"), f"{where}.{strategy}.intervals")
        cursor = 0
        for raw in intervals:
            interval = _mapping(raw, f"{where}.{strategy}.interval")
            start = _integer(interval.get("start_token"), "interval.start", minimum=0)
            end = _integer(interval.get("end_token"), "interval.end", minimum=0)
            if start != cursor or end < start or interval.get("token_count") != end - start:
                raise AcceptanceError(f"{where}.{strategy} intervals are not contiguous")
            cursor = end
        if candidate.get("feasible") is True and cursor != event.get(
            "effective_prefix_tokens"
        ):
            raise AcceptanceError(f"{where}.{strategy} does not cover fixed prefix")
    selected_key = tuple(_array(selected_candidate["selection_key"], "selected key"))
    minimum_key = min(
        tuple(_array(_mapping(value, "candidate")["selection_key"], "candidate key"))
        for value in candidates.values()
    )
    if selected_key != minimum_key:
        raise AcceptanceError(f"{where} selected strategy does not minimize selection key")
    realized = _mapping(
        _mapping(
            _load_classifier_system(run, focus_span_id=focus_span_id, where=where),
            f"{where}.realized",
        ),
        f"{where}.realized",
    )
    return {
        "selected_strategy": selected,
        "control_strategy": "PEER_FIRST_CONTROL",
        "selection_changed": selected != "PEER_FIRST_CONTROL",
        "prediction_scope": event["prediction_scope"],
        "candidates": {key: dict(value) for key, value in sorted(candidates.items())},
        "selected_vs_control_deltas_ns": dict(
            _mapping(
                event.get("selected_vs_control_deltas_ns"),
                f"{where}.selected_vs_control_deltas_ns",
            )
        ),
        "selected_vs_control_transferred_bytes_delta": _integer(
            event.get("selected_vs_control_transferred_bytes_delta"),
            f"{where}.selected_vs_control_transferred_bytes_delta",
        ),
        "realized": dict(realized),
    }


def _load_classifier_system(
    run: Mapping[str, Any],
    *,
    focus_span_id: str,
    where: str,
) -> Mapping[str, Any]:
    representative = _mapping(run.get("representative"), f"{where}.representative")
    plans = [
        _mapping(item, f"{where}.recovery_events[]")
        for item in _array(
            representative.get("recovery_events"), f"{where}.recovery_events"
        )
        if isinstance(item, Mapping)
        and item.get("event") == "RECOVERY_PLAN"
        and item.get("span_id") == focus_span_id
    ]
    if len(plans) != 1:
        raise AcceptanceError(f"{where} lacks unique realized RECOVERY_PLAN")
    plan = plans[0]
    source_tokens = _mapping(plan.get("source_tokens"), f"{where}.source_tokens")
    if set(source_tokens) != {"NORMAL_HBM_LOCAL", "PEER_HBM", "STORE_DRAM", "RECOMPUTE"}:
        raise AcceptanceError(f"{where} realized source-token set mismatch")
    return {
        "source_tokens": {
            key: _integer(value, f"{where}.source_tokens.{key}", minimum=0)
            for key, value in sorted(source_tokens.items())
        },
        "effective_prefix_tokens": _integer(
            plan.get("effective_prefix_tokens"), f"{where}.effective_prefix_tokens", minimum=0
        ),
    }


def _validate_classifier(
    classifier: Mapping[str, Any],
    *,
    artifact_fingerprint: str,
) -> None:
    if (
        classifier.get("schema") != EXPECTED_CLASSIFIER_SCHEMA
        or classifier.get("status") != "PASS"
    ):
        raise AcceptanceError("direct classifier schema/status mismatch")
    _verify_fingerprint(classifier, "direct classifier")
    if classifier.get("input_artifact_fingerprint") != artifact_fingerprint:
        raise AcceptanceError("direct classifier input fingerprint mismatch")
    if classifier.get("classification") not in DIRECT_CLASSES:
        raise AcceptanceError("unsupported direct classifier class")
    if (
        classifier.get("effect_direction_gate_applied") is not False
        or classifier.get("all_cells_retained") is not True
    ):
        raise AcceptanceError("direct classifier retention contract mismatch")


def _binding(document: Mapping[str, Any]) -> dict[str, Any]:
    protocol = _mapping(document.get("protocol"), "protocol")
    source = _mapping(document.get("source"), "source")
    systems = {
        system_id: _text(
            _run(document, system_id).get("variant_fingerprint"),
            f"{system_id}.variant_fingerprint",
        )
        for system_id in SYSTEM_IDS
    }
    workload = _mapping(source.get("workload"), "source.workload")
    return {
        "implementation_fingerprint": _text(
            source.get("implementation_fingerprint"),
            "source.implementation_fingerprint",
        ),
        "configuration_fingerprint": fingerprint(
            {
                "variant_fingerprints": systems,
                "workflow_concurrency": protocol.get("workflow_concurrency"),
                "failure_progress_per_mille": protocol.get(
                    "failure_progress_per_mille"
                ),
                "model": protocol.get("model"),
                "dp": protocol.get("dp"),
                "tp": protocol.get("tp"),
                "pp": protocol.get("pp"),
            }
        ),
        "variant_fingerprints": systems,
        "workload_binding": dict(workload),
        "workload_binding_fingerprint": fingerprint(workload),
        "peer_binding_seed": _integer(
            protocol.get("peer_binding_seed"), "protocol.peer_binding_seed", minimum=0
        ),
    }


def build_campaign(
    *,
    artifact_paths: Sequence[Path],
    classifier_paths: Sequence[Path],
    classifier_source: Path,
    require_independent_admission: bool = True,
) -> dict[str, Any]:
    """Build one complete five-seed campaign without filtering effect directions."""

    if len(artifact_paths) != len(EXPECTED_SEEDS):
        raise AcceptanceError("campaign requires exactly five artifact paths")
    if len(classifier_paths) != len(EXPECTED_SEEDS):
        raise AcceptanceError("campaign requires exactly five classifier paths")
    classify = cast(
        Callable[[Mapping[str, Any]], dict[str, Any]],
        _classifier_module(classifier_source).classify,
    )
    seeds: list[dict[str, Any]] = []
    campaign_binding: dict[str, Any] | None = None
    admission_hashes: set[str] = set()
    focus_ids_by_seed: dict[str, str] = {}
    for expected_seed, artifact_path, classifier_path in zip(
        EXPECTED_SEEDS, artifact_paths, classifier_paths, strict=True
    ):
        if not artifact_path.is_file():
            raise AcceptanceError(f"missing required seed {expected_seed}: {artifact_path}")
        document = _load_document(artifact_path)
        if document.get("schema") != EXPECTED_POSTFIX_SCHEMA or document.get("status") != "PASS":
            raise AcceptanceError(f"seed {expected_seed} postfix schema/status mismatch")
        artifact_fingerprint = _verify_fingerprint(document, f"seed {expected_seed} artifact")
        protocol = _mapping(document.get("protocol"), f"seed {expected_seed}.protocol")
        if (
            protocol.get("seed") != expected_seed
            or protocol.get("paper_causal_mode") is not True
            or protocol.get("failure_count") != 1
            or protocol.get("workflow_filtering") is not False
            or protocol.get("workflow_count") != protocol.get("source_workflow_count")
        ):
            raise AcceptanceError(f"seed {expected_seed} paper protocol mismatch")
        if classifier_path.exists():
            classifier = _load_document(classifier_path)
        else:
            classifier = classify(document)
            write_json_atomic(classifier_path, classifier)
        _validate_classifier(classifier, artifact_fingerprint=artifact_fingerprint)
        focus_span_id = _text(classifier.get("focus_span_id"), "classifier.focus_span_id")
        focus_ids_by_seed[str(expected_seed)] = focus_span_id
        binding = _binding(document)
        if campaign_binding is None:
            campaign_binding = binding
        elif binding != campaign_binding:
            raise AcceptanceError(
                f"seed {expected_seed} implementation/config/workload/peer binding differs"
            )
        runs = {system_id: _run(document, system_id) for system_id in SYSTEM_IDS}
        no_failure_runs = {
            system_id: _run(document, system_id, "no_failure")
            for system_id in SYSTEM_IDS
        }
        orders = {
            system_id: _admission_binding(
                runs[system_id], f"seed {expected_seed}.{system_id}"
            )
            for system_id in SYSTEM_IDS
        }
        if orders[SYSTEM_IDS[0]] != orders[SYSTEM_IDS[1]]:
            raise AcceptanceError(f"seed {expected_seed} paired admission orders differ")
        order, admission_hash = orders[SYSTEM_IDS[0]]
        if protocol.get("seed") != _mapping(
            _mapping(runs[SYSTEM_IDS[0]].get("payload"), "payload").get(
                "workflow_admission"
            ),
            "workflow_admission",
        ).get("seed"):
            raise AcceptanceError(f"seed {expected_seed} admission seed mismatch")
        admission_hashes.add(admission_hash)
        wct = {
            system_id: _workflow_wct(
                runs[system_id], f"seed {expected_seed}.{system_id}"
            )
            for system_id in SYSTEM_IDS
        }
        if (
            set(wct[SYSTEM_IDS[0]]) != set(wct[SYSTEM_IDS[1]])
            or set(order) != set(wct[SYSTEM_IDS[0]])
            or len(order) != 160
        ):
            raise AcceptanceError(
                f"seed {expected_seed} WCT/workflow identities differ or are incomplete"
            )
        moon = wct[SYSTEM_IDS[0]]
        aegis = wct[SYSTEM_IDS[1]]
        deltas = {key: aegis[key] - moon[key] for key in sorted(moon)}
        no_failure_wct = {
            system_id: _workflow_wct(
                no_failure_runs[system_id],
                f"seed {expected_seed}.no_failure.{system_id}",
            )
            for system_id in SYSTEM_IDS
        }
        if any(set(values) != set(moon) for values in no_failure_wct.values()):
            raise AcceptanceError(
                f"seed {expected_seed} four-cell WCT identities differ"
            )
        failure_penalty_did = {
            workflow_id: (
                aegis[workflow_id]
                - no_failure_wct[SYSTEM_IDS[1]][workflow_id]
                - moon[workflow_id]
                + no_failure_wct[SYSTEM_IDS[0]][workflow_id]
            )
            for workflow_id in sorted(moon)
        }
        moon_p95 = _nearest_rank(moon, 95)
        aegis_p95 = _nearest_rank(aegis, 95)
        moon_max = _nearest_rank(moon, 100)
        aegis_max = _nearest_rank(aegis, 100)
        selectors = {
            system_id: _selection_event(
                runs[system_id],
                focus_span_id=focus_span_id,
                where=f"seed {expected_seed}.{system_id}",
            )
            for system_id in SYSTEM_IDS
        }
        causal = _mapping(
            next(
                check
                for check in _array(
                    _mapping(classifier.get("validation"), "classifier.validation").get(
                        "checks"
                    ),
                    "classifier.validation.checks",
                )
                if isinstance(check, Mapping)
                and check.get("check")
                == "MATCHED_INTERVENTION_AND_REALIZED_OUTCOMES"
            ).get("evidence"),
            "causal evidence",
        )
        workflow_ids = set(deltas)
        focus_matches = [
            workflow_id
            for workflow_id in workflow_ids
            if focus_span_id == workflow_id
            or focus_span_id.startswith(f"{workflow_id}:")
            or f":{workflow_id}:" in f":{focus_span_id}:"
        ]
        if len(focus_matches) != 1:
            raise AcceptanceError(
                "focus span does not map to exactly one workflow identity"
            )
        focus_workflow = focus_matches[0]
        collateral = {
            key: value for key, value in deltas.items() if key != focus_workflow
        }
        worst_collateral = (
            max(collateral.items(), key=lambda item: (item[1], item[0]))
            if collateral
            else None
        )
        seeds.append(
            {
                "seed": expected_seed,
                "artifact": {
                    "path": artifact_path.as_posix(),
                    "sha256": sha256_file(artifact_path),
                    "fingerprint": artifact_fingerprint,
                },
                "classifier": {
                    "path": classifier_path.as_posix(),
                    "sha256": sha256_file(classifier_path),
                    "fingerprint": classifier["fingerprint"],
                },
                "admission_order_sha256": admission_hash,
                "workflow_count": len(deltas),
                "workflow_wct_ns": {key: dict(value) for key, value in wct.items()},
                "no_failure_workflow_wct_ns": {
                    key: dict(value) for key, value in no_failure_wct.items()
                },
                "workflow_deltas_aegiskv_minus_mooncake_ns": deltas,
                "workflow_failure_penalty_did_ns": failure_penalty_did,
                "workflow_level_descriptive_distribution": _distribution(deltas),
                "seed_level_estimands_ns": {
                    "mean_delta": sum(deltas.values()) / len(deltas),
                    "p95_delta": aegis_p95["value_ns"] - moon_p95["value_ns"],
                    "max_delta": aegis_max["value_ns"] - moon_max["value_ns"],
                    "focus_failure_penalty_did": failure_penalty_did[
                        focus_workflow
                    ],
                    "whole_mean_failure_penalty_did": (
                        sum(failure_penalty_did.values())
                        / len(failure_penalty_did)
                    ),
                },
                "percentile_identities": {
                    "mooncake_p95": moon_p95,
                    "aegiskv_p95": aegis_p95,
                    "mooncake_max": moon_max,
                    "aegiskv_max": aegis_max,
                },
                "winner_tie_loser": {
                    "aegiskv_winner_count": sum(value < 0 for value in deltas.values()),
                    "tie_count": sum(value == 0 for value in deltas.values()),
                    "aegiskv_loser_count": sum(value > 0 for value in deltas.values()),
                },
                "worst_collateral": (
                    None
                    if worst_collateral is None
                    else {
                        "workflow_id": worst_collateral[0],
                        "delta_ns": worst_collateral[1],
                    }
                ),
                "causal_contract": dict(causal),
                "failure_schedule": dict(
                    _mapping(
                        runs[SYSTEM_IDS[0]].get("failure_schedule"),
                        f"seed {expected_seed}.failure_schedule",
                    )
                ),
                "direct_class": classifier["classification"],
                "direct_evidence": {
                    "systems": classifier.get("systems"),
                    "paired_deltas_aegiskv_minus_mooncake": classifier.get(
                        "paired_deltas_aegiskv_minus_mooncake"
                    ),
                    "propagation_label": classifier.get("propagation_label"),
                },
                "recovery_selector_evidence": selectors,
            }
        )
    if set(item["seed"] for item in seeds) != set(EXPECTED_SEEDS):
        raise AcceptanceError("campaign seed set must be exactly 0..4")
    if require_independent_admission and len(admission_hashes) != len(EXPECTED_SEEDS):
        raise AcceptanceError(
            "duplicate admission order prevents independent seed-level uncertainty"
        )
    intervals = {
        estimand: _t_interval(
            [
                _mapping(item["seed_level_estimands_ns"], "seed estimands")[estimand]
                for item in seeds
            ]
        )
        for estimand in (
            "focus_failure_penalty_did",
            "whole_mean_failure_penalty_did",
            "mean_delta",
            "p95_delta",
            "max_delta",
        )
    }
    class_counts = Counter(str(item["direct_class"]) for item in seeds)
    body: dict[str, Any] = {
        "schema": CAMPAIGN_SCHEMA,
        "status": "PASS",
        "protocol": {
            "model": "Qwen/Qwen3-8B",
            "seeds": list(EXPECTED_SEEDS),
            "paired_systems": list(SYSTEM_IDS),
            "workflow_filtering": False,
            "peer_binding_fixed": True,
            "effect_direction_filter_applied": False,
            "retention": "EVERY_SEED_INCLUDING_NULL_MIXED_AND_ADVERSE",
        },
        "binding": campaign_binding,
        "focus_span_ids_by_seed": focus_ids_by_seed,
        "seed_count": len(seeds),
        "seeds": seeds,
        "inference": {
            "independent_unit": "workflow_admission_randomization_seed",
            "workflow_observations_are_descriptive_not_inferential": True,
            "distinct_admission_order_count": len(admission_hashes),
            "student_t_95": intervals,
        },
        "direct_class_counts": {
            key: class_counts.get(key, 0) for key in sorted(DIRECT_CLASSES)
        },
        "acceptance": {
            "status": "PASS",
            "fail_closed": True,
            "allowed_panel_ids": list(ALLOWED_PANEL_IDS),
            "omitted_panel_ids": {
                "FIGURE_4_A": (
                    "FULL_EXCLUSIVE_FAILURE_TO_COMPLETION_PHASE_DECOMPOSITION_NOT_PROVEN"
                )
            },
        },
        "modeled_uncalibrated": True,
        "physical_execution": False,
        "paper_ready": False,
        "classifier_generator": {
            "path": classifier_source.as_posix(),
            "sha256": sha256_file(classifier_source),
        },
    }
    return {**body, "fingerprint": fingerprint(body)}


def validate_campaign(
    document: Mapping[str, Any],
    schema_path: Path | None = None,
) -> None:
    """Validate the campaign envelope before any plotting consumer uses it."""

    if document.get("schema") != CAMPAIGN_SCHEMA or document.get("status") != "PASS":
        raise AcceptanceError("unsupported failure campaign schema/status")
    if schema_path is not None:
        schema = _mapping(load_json_strict(schema_path), "failure campaign schema")
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(document),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if errors:
            raise AcceptanceError(
                f"failure campaign schema validation failed: {errors[0].message}"
            )
    _verify_fingerprint(document, "failure campaign")
    acceptance = _mapping(document.get("acceptance"), "campaign.acceptance")
    if acceptance.get("status") != "PASS" or acceptance.get("fail_closed") is not True:
        raise AcceptanceError("failure campaign is not accepted")
    allowed = _array(acceptance.get("allowed_panel_ids"), "allowed_panel_ids")
    if any(panel not in ALLOWED_PANEL_IDS for panel in allowed):
        raise AcceptanceError("failure campaign authorizes an unsupported panel")
    if "FIGURE_4_A" in allowed:
        raise AcceptanceError("Figure 4A is not proven by this campaign schema")
    seeds = _array(document.get("seeds"), "campaign.seeds")
    if [item.get("seed") for item in seeds if isinstance(item, Mapping)] != list(
        EXPECTED_SEEDS
    ):
        raise AcceptanceError("failure campaign seed order/set mismatch")
