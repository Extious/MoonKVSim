"""Deterministic cross-seed statistics for the AegisKV E2 matrix.

The experiment protocol executes repeat A and repeat B only to prove exact
determinism.  They are not independent observations.  This module therefore
uses exactly one repeat-A observation per declared seed and keeps the source
``run_id`` and payload digest attached to every reported sample.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any, Final

from moonkvsim.common.hash import sha256_json

STATISTICS_SCHEMA: Final = "moonkvsim.aegiskv.e2_matrix_suite.v1.statistics"

# The values are two-sided 95% Student-t critical values, rounded to six
# decimal places.  For df values between the listed breakpoints the previous
# (smaller-df) value is used, which is conservative.
_T_CRITICAL_MILLIONTHS: Final[tuple[tuple[int, int], ...]] = (
    (1, 12_706_205),
    (2, 4_302_653),
    (3, 3_182_446),
    (4, 2_776_445),
    (5, 2_570_582),
    (6, 2_446_912),
    (7, 2_364_624),
    (8, 2_306_004),
    (9, 2_262_157),
    (10, 2_228_139),
    (11, 2_200_985),
    (12, 2_178_813),
    (13, 2_160_369),
    (14, 2_144_787),
    (15, 2_131_450),
    (16, 2_119_905),
    (17, 2_109_816),
    (18, 2_100_922),
    (19, 2_093_024),
    (20, 2_085_963),
    (21, 2_079_614),
    (22, 2_073_873),
    (23, 2_068_658),
    (24, 2_063_899),
    (25, 2_059_539),
    (26, 2_055_529),
    (27, 2_051_831),
    (28, 2_048_407),
    (29, 2_045_230),
    (30, 2_042_272),
    (40, 2_021_075),
    (60, 2_000_298),
    (120, 1_979_930),
)

METRIC_DEFINITIONS: Final[dict[str, dict[str, Any]]] = {
    "workflow_wct_mean_ns": {
        "payload_path": ["metrics", "workflow_completion_time_ns", "mean"],
        "unit": "ns",
        "preferred_direction": "lower",
    },
    "workflow_wct_p95_ns": {
        "payload_path": ["metrics", "workflow_completion_time_ns", "p95"],
        "unit": "ns",
        "preferred_direction": "lower",
    },
    "goodput_output_tokens_per_second_milli": {
        "payload_path": ["metrics", "goodput_output_tokens_per_second_milli"],
        "unit": "milli_output_tokens_per_second",
        "preferred_direction": "higher",
    },
    "recovery_latency_mean_ns": {
        "payload_path": ["metrics", "recovery_latency_ns", "mean"],
        "unit": "ns",
        "preferred_direction": "lower",
    },
    "restored_tokens_total": {
        "payload_path": ["metrics", "restored_tokens", "total"],
        "unit": "tokens",
        "preferred_direction": "context_dependent",
    },
    "recompute_tokens_after_failure": {
        "payload_path": ["metrics", "recompute_tokens_after_failure"],
        "unit": "tokens",
        "preferred_direction": "lower",
    },
    "peer_hbm_peak_bytes": {
        "payload_path": ["metrics", "resource_cost", "peer_hbm_peak_bytes"],
        "unit": "bytes",
        "preferred_direction": "lower",
    },
    "store_dram_peak_bytes": {
        "payload_path": ["metrics", "resource_cost", "store_dram_peak_bytes"],
        "unit": "bytes",
        "preferred_direction": "lower",
    },
    "network_byte_ns": {
        "payload_path": ["metrics", "resource_cost", "network_byte_ns"],
        "unit": "byte_ns",
        "preferred_direction": "lower",
        "reduction": "sum_non_negative_integer_mapping_values",
    },
    "copy_engine_busy_ns": {
        "payload_path": ["metrics", "resource_cost", "copy_engine_busy_ns"],
        "unit": "ns",
        "preferred_direction": "lower",
        "reduction": "sum_non_negative_integer_mapping_values",
    },
}


class StatisticsError(ValueError):
    """The canonical matrix cannot support the declared statistical result."""


def _critical_t_millionths(degrees_of_freedom: int) -> int:
    if degrees_of_freedom <= 0:
        raise StatisticsError("Student-t degrees of freedom must be positive")
    selected = _T_CRITICAL_MILLIONTHS[0][1]
    for breakpoint, value in _T_CRITICAL_MILLIONTHS:
        if degrees_of_freedom < breakpoint:
            break
        selected = value
    return selected


def _rounded(value: Decimal, rounding: str) -> int:
    return int(value.to_integral_value(rounding=rounding))


def confidence_summary(values: Sequence[int]) -> dict[str, Any]:
    """Return an integer-preserving deterministic arithmetic-mean summary."""

    if not values or any(type(value) is not int for value in values):
        raise StatisticsError("statistics require one or more integer samples")
    sample_count = len(values)
    total = sum(values)
    mean = Decimal(total) / Decimal(sample_count)
    summary: dict[str, Any] = {
        "sample_count": sample_count,
        "mean": {
            "numerator": total,
            "denominator": sample_count,
            "rounded_half_even": _rounded(mean, ROUND_HALF_EVEN),
        },
    }
    if sample_count == 1:
        summary.update(
            {
                "sample_stddev_rounded_half_even": None,
                "ci95": {
                    "status": "NOT_ESTIMABLE_SINGLE_SEED",
                    "method": "two_sided_student_t_95_conservative_table",
                    "degrees_of_freedom": 0,
                    "critical_t_millionths": None,
                    "lower_floor": None,
                    "upper_ceiling": None,
                },
            }
        )
        return summary

    with localcontext() as context:
        context.prec = 60
        squared_deviation_sum = sum(
            ((Decimal(value) - mean) ** 2 for value in values),
            start=Decimal(0),
        )
        variance = squared_deviation_sum / Decimal(sample_count - 1)
        stddev = variance.sqrt()
        standard_error = (variance / Decimal(sample_count)).sqrt()
        critical_millionths = _critical_t_millionths(sample_count - 1)
        margin = standard_error * Decimal(critical_millionths) / Decimal(1_000_000)
        lower = mean - margin
        upper = mean + margin
    summary.update(
        {
            "sample_stddev_rounded_half_even": _rounded(stddev, ROUND_HALF_EVEN),
            "ci95": {
                "status": "ESTIMATED",
                "method": "two_sided_student_t_95_conservative_table",
                "degrees_of_freedom": sample_count - 1,
                "critical_t_millionths": critical_millionths,
                "lower_floor": _rounded(lower, ROUND_FLOOR),
                "upper_ceiling": _rounded(upper, ROUND_CEILING),
            },
        }
    )
    return summary


def _required_string(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise StatisticsError(f"result row has invalid {key}")
    return value


def _required_integer(row: Mapping[str, Any], key: str) -> int:
    value = row.get(key)
    if type(value) is not int or value < 0:
        raise StatisticsError(f"result row has invalid {key}")
    return value


def _failure_count(row: Mapping[str, Any]) -> int:
    """Return zero for no-failure cells and a positive count otherwise."""

    scenario = _required_string(row, "scenario")
    value = row.get("failure_count")
    if scenario == "no_failure":
        if value != 0:
            raise StatisticsError("no-failure row must have failure_count=0")
        return 0
    if type(value) is not int or value <= 0:
        raise StatisticsError("GPU-failure row lacks a positive failure_count")
    return value


def _metric_value(row: Mapping[str, Any], metric_id: str) -> int:
    definition = METRIC_DEFINITIONS[metric_id]
    current: object = row.get("payload")
    for key in definition["payload_path"]:
        if not isinstance(current, Mapping) or key not in current:
            raise StatisticsError(
                f"{_required_string(row, 'run_id')} lacks metric path for {metric_id}"
            )
        current = current[key]
    reduction = definition.get("reduction")
    if reduction == "sum_non_negative_integer_mapping_values":
        if not isinstance(current, Mapping) or not all(
            isinstance(key, str) and type(value) is int and value >= 0
            for key, value in current.items()
        ):
            raise StatisticsError(
                f"{_required_string(row, 'run_id')} has malformed cause mapping for {metric_id}"
            )
        return sum(int(value) for value in current.values())
    if reduction is not None:
        raise StatisticsError(f"unsupported metric reduction for {metric_id}: {reduction}")
    if type(current) is not int or current < 0:
        raise StatisticsError(
            f"{_required_string(row, 'run_id')} has non-integer/non-negative {metric_id}"
        )
    return current


def _sample(row: Mapping[str, Any], metric_id: str) -> dict[str, Any]:
    return {
        "seed": _required_integer(row, "seed"),
        "failure_count": _failure_count(row),
        "run_id": _required_string(row, "run_id"),
        "payload_sha256": _required_string(row, "payload_sha256"),
        "value": _metric_value(row, metric_id),
    }


def _descriptive_statistics(
    rows: Sequence[Mapping[str, Any]], seeds: Sequence[int]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("repetition") == "A":
            key = (
                _required_string(row, "suite"),
                _required_string(row, "variant_id"),
                _required_string(row, "context_bucket"),
                _required_string(row, "scenario"),
                _failure_count(row),
            )
            grouped[key].append(row)
    expected_seeds = list(seeds)
    documents: list[dict[str, Any]] = []
    for key in sorted(grouped):
        suite, variant_id, context_bucket, scenario, failure_count = key
        group_rows = sorted(grouped[key], key=lambda row: _required_integer(row, "seed"))
        actual_seeds = [_required_integer(row, "seed") for row in group_rows]
        if actual_seeds != expected_seeds:
            raise StatisticsError(
                f"{suite}/{variant_id}/{context_bucket}/{scenario} seed set drifted: "
                f"{actual_seeds} != {expected_seeds}"
            )
        for metric_id, definition in METRIC_DEFINITIONS.items():
            samples = [_sample(row, metric_id) for row in group_rows]
            documents.append(
                {
                    "suite": suite,
                    "variant_id": variant_id,
                    "context_bucket": context_bucket,
                    "scenario": scenario,
                    "failure_count": failure_count,
                    "metric_id": metric_id,
                    "unit": definition["unit"],
                    "samples": samples,
                    "estimate": confidence_summary([int(sample["value"]) for sample in samples]),
                }
            )
    return documents


def _paired_statistics(
    rows: Sequence[Mapping[str, Any]], seeds: Sequence[int]
) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str, str, int, int], Mapping[str, Any]] = {}
    variants_by_suite: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("repetition") != "A":
            continue
        suite = _required_string(row, "suite")
        variant = _required_string(row, "variant_id")
        key = (
            suite,
            variant,
            _required_string(row, "context_bucket"),
            _required_string(row, "scenario"),
            _required_integer(row, "seed"),
            _failure_count(row),
        )
        if key in by_key:
            raise StatisticsError(f"duplicate repeat-A statistical cell: {key}")
        by_key[key] = row
        variants_by_suite[suite].add(variant)

    comparator_by_suite = {"core": "recompute_only", "ablation": "full"}
    documents: list[dict[str, Any]] = []
    for suite, comparator in comparator_by_suite.items():
        variants = variants_by_suite.get(suite, set())
        if not variants:
            continue
        if comparator not in variants:
            raise StatisticsError(f"{suite} lacks paired comparator {comparator}")
        for candidate in sorted(variants - {comparator}):
            for context_bucket in ("8k", "32k", "64k", "96k", "128k"):
                for scenario in ("no_failure", "gpu_failure"):
                    failure_counts = sorted(
                        {
                            key[-1]
                            for key in by_key
                            if key[0] == suite
                            and key[2] == context_bucket
                            and key[3] == scenario
                        }
                    )
                    for failure_count in failure_counts:
                        for metric_id, definition in METRIC_DEFINITIONS.items():
                            samples: list[dict[str, Any]] = []
                            for seed in seeds:
                                candidate_row = by_key.get(
                                    (
                                        suite,
                                        candidate,
                                        context_bucket,
                                        scenario,
                                        seed,
                                        failure_count,
                                    )
                                )
                                comparator_row = by_key.get(
                                    (
                                        suite,
                                        comparator,
                                        context_bucket,
                                        scenario,
                                        seed,
                                        failure_count,
                                    )
                                )
                                if candidate_row is None or comparator_row is None:
                                    raise StatisticsError(
                                        "paired statistical cell is missing for "
                                        f"{suite}/{candidate}/{context_bucket}/{scenario}/"
                                        f"seed-{seed}/failure-count-{failure_count}"
                                    )
                                candidate_value = _metric_value(candidate_row, metric_id)
                                comparator_value = _metric_value(comparator_row, metric_id)
                                samples.append(
                                    {
                                        "seed": seed,
                                        "failure_count": failure_count,
                                        "candidate_run_id": _required_string(
                                            candidate_row, "run_id"
                                        ),
                                        "candidate_payload_sha256": _required_string(
                                            candidate_row, "payload_sha256"
                                        ),
                                        "candidate_value": candidate_value,
                                        "comparator_run_id": _required_string(
                                            comparator_row, "run_id"
                                        ),
                                        "comparator_payload_sha256": _required_string(
                                            comparator_row, "payload_sha256"
                                        ),
                                        "comparator_value": comparator_value,
                                        "difference_candidate_minus_comparator": (
                                            candidate_value - comparator_value
                                        ),
                                    }
                                )
                            documents.append(
                                {
                                    "suite": suite,
                                    "candidate_variant_id": candidate,
                                    "comparator_variant_id": comparator,
                                    "context_bucket": context_bucket,
                                    "scenario": scenario,
                                    "failure_count": failure_count,
                                    "metric_id": metric_id,
                                    "unit": definition["unit"],
                                    "preferred_direction": definition[
                                        "preferred_direction"
                                    ],
                                    "effect_definition": "candidate_minus_comparator",
                                    "samples": samples,
                                    "estimate": confidence_summary(
                                        [
                                            int(
                                                sample[
                                                    "difference_candidate_minus_comparator"
                                                ]
                                            )
                                            for sample in samples
                                        ]
                                    ),
                                }
                            )
    return documents


def build_statistics(
    rows: Sequence[Mapping[str, Any]],
    *,
    seeds: Sequence[int],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the canonical descriptive and paired cross-seed statistics artifact."""

    canonical_seeds = tuple(seeds)
    if not canonical_seeds or tuple(sorted(set(canonical_seeds))) != canonical_seeds:
        raise StatisticsError("statistics seeds must be unique and canonically sorted")
    repetitions = {row.get("repetition") for row in rows}
    if repetitions != {"A", "B"}:
        raise StatisticsError("statistics input must contain exact A/B repetitions")
    descriptive = _descriptive_statistics(rows, canonical_seeds)
    paired = _paired_statistics(rows, canonical_seeds)
    document: dict[str, Any] = {
        "schema": STATISTICS_SCHEMA,
        "status": "PASS",
        "evidence": dict(evidence),
        "sampling_contract": {
            "independent_unit": "seed",
            "included_repetition": "A",
            "excluded_repetition": "B",
            "excluded_repetition_reason": "determinism_replay_not_independent_sample",
            "seeds": list(canonical_seeds),
            "seed_count": len(canonical_seeds),
            "confidence_level_milli": 950,
            "interval_method": "two_sided_student_t_95_conservative_table",
        },
        "metric_definitions": METRIC_DEFINITIONS,
        "descriptive": descriptive,
        "paired_effects": paired,
        "paired_comparator_contract": {
            "core": "recompute_only",
            "ablation": "full",
            "sensitivity": None,
            "sensitivity_exclusion_reason": (
                "one_at_a_time_parameter_sweeps_have_no_shared_nominal_variant_row"
            ),
        },
        "audit": {
            "source_row_count": len(rows),
            "included_repeat_a_row_count": sum(
                1 for row in rows if row.get("repetition") == "A"
            ),
            "excluded_repeat_b_row_count": sum(
                1 for row in rows if row.get("repetition") == "B"
            ),
            "descriptive_group_count": len(descriptive),
            "paired_effect_group_count": len(paired),
            "all_samples_source_bound": True,
            "physical_measurements_used": False,
        },
    }
    document["fingerprint"] = sha256_json(document)
    return document
