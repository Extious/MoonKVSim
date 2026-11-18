"""Strict paired multi-seed statistics for one Qwen3-8B paper-sweep cell.

The independent sampling unit is one seed.  Mooncake and AegisKV are paired
within a seed; deterministic A/B replays are deliberately not treated as extra
samples.  The module computes observed statistics only: it performs no
smoothing, interpolation, projection, monotonic fitting, or trend generation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, Final

from moonkvsim.aegiskv.experiment_statistics import confidence_summary
from moonkvsim.aegiskv.paper_randomization import (
    paired_admission_fingerprint,
    require_distinct_admissions,
)
from moonkvsim.common.hash import sha256_json

STATISTICS_SCHEMA: Final = "moonkvsim.aegiskv.paper_sweep_statistics.v3"
MOONCAKE: Final = "vanilla_mooncake_dram"
AEGISKV: Final = "aegiskv_unified"
MINIMUM_SEED_COUNT: Final = 5
PERCENT_MILLIONTH_SCALE: Final = 1_000_000
FRACTION_MILLIONTH_SCALE: Final = 1_000_000


class PaperSweepStatisticsError(ValueError):
    """The supplied cells cannot support a paired multi-seed statistic."""


def _object(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PaperSweepStatisticsError(f"{where} must be an object")
    return value


def _array(value: object, where: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PaperSweepStatisticsError(f"{where} must be an array")
    return value


def _string(value: object, where: str) -> str:
    if type(value) is not str or not value:
        raise PaperSweepStatisticsError(f"{where} must be a non-empty string")
    return value


def _integer(value: object, where: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        qualifier = "positive" if positive else "non-negative"
        raise PaperSweepStatisticsError(f"{where} must be a {qualifier} integer")
    return value


def _boolean(value: object, where: str) -> bool:
    if type(value) is not bool:
        raise PaperSweepStatisticsError(f"{where} must be a boolean")
    return value


def _fraction(value: object, where: str) -> Fraction:
    if type(value) is not str or not value:
        raise PaperSweepStatisticsError(f"{where} must be a decimal string")
    try:
        result = Fraction(Decimal(value))
    except (InvalidOperation, ValueError, ZeroDivisionError) as error:
        raise PaperSweepStatisticsError(f"{where} is not a finite decimal") from error
    if result < 0 or result > 1:
        raise PaperSweepStatisticsError(f"{where} must be in [0,1]")
    return result


def _round_half_even(value: Fraction) -> int:
    quotient, remainder = divmod(abs(value.numerator), value.denominator)
    doubled = remainder * 2
    rounded = quotient + int(
        doubled > value.denominator or (doubled == value.denominator and quotient % 2)
    )
    return -rounded if value < 0 else rounded


def _fraction_json(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _summarize(
    values_by_seed: Sequence[tuple[int, Fraction]],
    *,
    unit: str,
    scale: int,
) -> dict[str, object]:
    if len(values_by_seed) < MINIMUM_SEED_COUNT:
        raise PaperSweepStatisticsError("statistics require at least five seed samples")
    rounded_values = [_round_half_even(value * scale) for _seed, value in values_by_seed]
    samples = [
        {
            "seed": seed,
            "exact": _fraction_json(value),
            "rounded_value": rounded,
        }
        for (seed, value), rounded in zip(values_by_seed, rounded_values, strict=True)
    ]
    estimate = confidence_summary(rounded_values)
    return {
        "unit": unit,
        "integer_scale": scale,
        "per_seed": samples,
        "estimate": estimate,
        "confidence_interval_interpretation": (
            "two-sided 95% Student-t interval across independent seed-level paired "
            "observations; conservative tabulated critical value"
        ),
        "smoothing_performed": False,
    }


def _run(cell: Mapping[str, Any], system: str, seed: int) -> Mapping[str, Any]:
    systems = _object(cell.get("systems"), f"seed-{seed}.systems")
    if set(systems) != {MOONCAKE, AEGISKV}:
        raise PaperSweepStatisticsError(
            f"seed-{seed} systems must be exactly {MOONCAKE} and {AEGISKV}"
        )
    system_row = _object(systems[system], f"seed-{seed}.systems.{system}")
    return _object(system_row.get("run"), f"seed-{seed}.systems.{system}.run")


def _wct(run: Mapping[str, Any], where: str) -> dict[str, int]:
    metrics = _object(run.get("metrics"), f"{where}.metrics")
    workflow_metric = _object(
        metrics.get("workflow_completion_time_ns"),
        f"{where}.metrics.workflow_completion_time_ns",
    )
    raw = _object(
        workflow_metric.get("by_workflow_id"),
        f"{where}.metrics.workflow_completion_time_ns.by_workflow_id",
    )
    if not raw:
        raise PaperSweepStatisticsError(f"{where} has no workflow WCT observations")
    result: dict[str, int] = {}
    for workflow_id, value in raw.items():
        result[_string(workflow_id, f"{where}.workflow_id")] = _integer(
            value, f"{where}.wct[{workflow_id}]", positive=True
        )
    return result


def _span_index(run: Mapping[str, Any], key: str, where: str) -> dict[str, Mapping[str, Any]]:
    rows = _array(run.get(key), f"{where}.{key}")
    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(rows):
        row = _object(raw, f"{where}.{key}[{index}]")
        span_id = _string(row.get("span_id"), f"{where}.{key}[{index}].span_id")
        _string(row.get("workflow_id"), f"{where}.{key}[{index}].workflow_id")
        if span_id in result:
            raise PaperSweepStatisticsError(f"{where}.{key} contains duplicate {span_id}")
        result[span_id] = row
    return result


def _affected_workflows(run: Mapping[str, Any], where: str) -> set[str]:
    rows = _array(run.get("failure_impacted_spans"), f"{where}.failure_impacted_spans")
    return {
        _string(
            _object(row, f"{where}.failure_impacted_spans[{index}]").get("workflow_id"),
            f"{where}.failure_impacted_spans[{index}].workflow_id",
        )
        for index, row in enumerate(rows)
    }


def _mean_gain_percent(
    mooncake: Mapping[str, int], aegiskv: Mapping[str, int], workflow_ids: set[str]
) -> Fraction:
    if not workflow_ids:
        raise PaperSweepStatisticsError("WCT gain subset cannot be empty")
    moon_sum = sum(mooncake[item] for item in workflow_ids)
    aegis_sum = sum(aegiskv[item] for item in workflow_ids)
    if moon_sum <= 0:
        raise PaperSweepStatisticsError("Mooncake mean WCT denominator must be positive")
    return Fraction((moon_sum - aegis_sum) * 100, moon_sum)


def _mean_wct_ns(values: Mapping[str, int], workflow_ids: set[str]) -> Fraction:
    if not workflow_ids:
        raise PaperSweepStatisticsError("mean WCT subset cannot be empty")
    return Fraction(sum(values[item] for item in workflow_ids), len(workflow_ids))


def _nearest_rank_p95(values: Sequence[int]) -> int:
    if not values:
        raise PaperSweepStatisticsError("P95 subset cannot be empty")
    ordered = sorted(values)
    index = (95 * len(ordered) + 99) // 100 - 1
    return ordered[index]


def _p95_gain_percent(
    mooncake: Mapping[str, int], aegiskv: Mapping[str, int], workflow_ids: set[str]
) -> Fraction:
    moon_p95 = _nearest_rank_p95([mooncake[item] for item in workflow_ids])
    aegis_p95 = _nearest_rank_p95([aegiskv[item] for item in workflow_ids])
    return Fraction((moon_p95 - aegis_p95) * 100, moon_p95)


def _unaffected_gap_percent(
    mooncake: Mapping[str, int], aegiskv: Mapping[str, int], workflow_ids: set[str]
) -> Fraction:
    if not workflow_ids:
        raise PaperSweepStatisticsError("unaffected workflow subset cannot be empty")
    moon_sum = sum(mooncake[item] for item in workflow_ids)
    aegis_sum = sum(aegiskv[item] for item in workflow_ids)
    if moon_sum <= 0:
        raise PaperSweepStatisticsError("unaffected Mooncake WCT denominator must be positive")
    return Fraction(abs(moon_sum - aegis_sum) * 100, moon_sum)


def _alpha_statistics(
    run: Mapping[str, Any], seed: int
) -> tuple[Fraction, Fraction, Fraction, Fraction, list[dict[str, object]]]:
    events = _array(run.get("aimd_events"), f"seed-{seed}.AegisKV.aimd_events")
    if not events:
        raise PaperSweepStatisticsError(f"seed-{seed} has no AegisKV AIMD events")
    metrics = _object(run.get("metrics"), f"seed-{seed}.AegisKV.metrics")
    end_ns = _integer(metrics.get("workload_end_ns"), f"seed-{seed}.workload_end_ns", positive=True)
    by_target: dict[str, list[tuple[int, Fraction, Fraction]]] = defaultdict(list)
    pressure_count = 0
    all_values: list[Fraction] = []
    trace: list[dict[str, object]] = []
    for index, raw in enumerate(events):
        where = f"seed-{seed}.AegisKV.aimd_events[{index}]"
        event = _object(raw, where)
        previous = _object(event.get("previous_state"), f"{where}.previous_state")
        next_state = _object(event.get("next_state"), f"{where}.next_state")
        previous_target = _string(previous.get("target_id"), f"{where}.previous.target_id")
        next_target = _string(next_state.get("target_id"), f"{where}.next.target_id")
        if previous_target != next_target:
            raise PaperSweepStatisticsError(f"{where} changes AIMD target identity")
        timestamp = _integer(event.get("timestamp_ns"), f"{where}.timestamp_ns")
        if timestamp > end_ns:
            raise PaperSweepStatisticsError(f"{where} occurs after workload_end_ns")
        previous_alpha = _fraction(
            previous.get("protection_fraction"), f"{where}.previous.protection_fraction"
        )
        next_alpha = _fraction(
            next_state.get("protection_fraction"), f"{where}.next.protection_fraction"
        )
        pressure_count += int(_boolean(event.get("foreground_pressure"), f"{where}.pressure"))
        by_target[next_target].append((timestamp, previous_alpha, next_alpha))
        all_values.extend((previous_alpha, next_alpha))
        trace.append(
            {
                "timestamp_ns": timestamp,
                "target_id": next_target,
                "active_request_count": _integer(
                    event.get("active_request_count"), f"{where}.active_request_count"
                ),
                "pressure_resident_primary_count": _integer(
                    event.get("pressure_resident_primary_count"),
                    f"{where}.pressure_resident_primary_count",
                ),
                "protection_fraction": _fraction_json(next_alpha),
                "foreground_pressure": _boolean(
                    event.get("foreground_pressure"), f"{where}.pressure"
                ),
            }
        )

    integral = Fraction(0)
    for target, target_events in sorted(by_target.items()):
        ordered = sorted(target_events)
        current = ordered[0][1]
        last_ns = 0
        for timestamp, previous_alpha, next_alpha in ordered:
            if timestamp <= last_ns:
                raise PaperSweepStatisticsError(
                    f"seed-{seed} target {target} AIMD timestamps are not strictly increasing"
                )
            if previous_alpha != current:
                raise PaperSweepStatisticsError(
                    f"seed-{seed} target {target} AIMD state is discontinuous"
                )
            integral += current * (timestamp - last_ns)
            current = next_alpha
            last_ns = timestamp
        integral += current * (end_ns - last_ns)
    time_weighted = integral / (end_ns * len(by_target))
    pressure_rate_percent = Fraction(pressure_count * 100, len(events))
    trace.sort(
        key=lambda row: (
            _integer(row["timestamp_ns"], "internal.trace.timestamp_ns"),
            _string(row["target_id"], "internal.trace.target_id"),
        )
    )
    return time_weighted, min(all_values), max(all_values), pressure_rate_percent, trace


def _selected_tier_tokens(focus: Mapping[str, Mapping[str, Any]], seed: int) -> dict[str, int]:
    field_by_tier = {
        "normal_hbm_local": "recovery_normal_hbm_local_tokens",
        "peer_hbm": "restored_peer_tokens",
        "store_dram": "restored_store_tokens",
    }
    result: dict[str, int] = {}
    for tier, field in field_by_tier.items():
        result[tier] = sum(
            _integer(row.get(field), f"seed-{seed}.focus[{span_id}].{field}")
            for span_id, row in focus.items()
        )
    return result


def _available_tier_tokens(
    focus: Mapping[str, Mapping[str, Any]], seed: int, system: str
) -> dict[str, int]:
    field_by_tier = {
        "normal_hbm_local": "available_normal_hbm_tokens_at_failure",
        "peer_hbm": "available_peer_tokens_at_failure",
        "store_dram": "available_store_tokens_at_failure",
    }
    return {
        tier: sum(
            _integer(row.get(field), f"seed-{seed}.{system}.focus[{span_id}].{field}")
            for span_id, row in focus.items()
        )
        for tier, field in field_by_tier.items()
    }


def build_paper_sweep_statistics(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate the exact five paired seed cells for one formal sweep point."""

    if len(cells) != MINIMUM_SEED_COUNT:
        raise PaperSweepStatisticsError("paper-sweep statistics require exactly five seed cells")
    normalized: list[tuple[int, Mapping[str, Any]]] = []
    seen_seeds: set[int] = set()
    cell_identity: tuple[int, int] | None = None
    for index, cell in enumerate(cells):
        seed = _integer(cell.get("seed"), f"cells[{index}].seed")
        failure_count = _integer(
            cell.get("failure_count"), f"cells[{index}].failure_count", positive=True
        )
        concurrency = _integer(
            cell.get("workflow_concurrency"),
            f"cells[{index}].workflow_concurrency",
            positive=True,
        )
        if seed in seen_seeds:
            raise PaperSweepStatisticsError(f"duplicate seed cell: {seed}")
        seen_seeds.add(seed)
        identity = (failure_count, concurrency)
        if cell_identity is None:
            cell_identity = identity
        elif identity != cell_identity:
            raise PaperSweepStatisticsError("all cells must share failure_count and concurrency")
        normalized.append((seed, cell))
    normalized.sort(key=lambda item: item[0])
    assert cell_identity is not None
    if tuple(seed for seed, _ in normalized) != tuple(range(MINIMUM_SEED_COUNT)):
        raise PaperSweepStatisticsError(
            "paper-sweep statistics require the exact seed vector 0,1,2,3,4"
        )

    metric_samples: dict[str, list[tuple[int, Fraction]]] = defaultdict(list)
    impact_count_samples: dict[str, list[tuple[int, Fraction]]] = defaultdict(list)
    absolute_wct_samples: dict[str, dict[str, list[tuple[int, Fraction]]]] = {
        subset: {MOONCAKE: [], AEGISKV: []}
        for subset in ("whole", "failure_focus", "variant_local_impacted_union")
    }
    selected_tier_samples: dict[str, dict[str, list[tuple[int, Fraction]]]] = {
        system: defaultdict(list) for system in (MOONCAKE, AEGISKV)
    }
    available_tier_samples: dict[str, dict[str, list[tuple[int, Fraction]]]] = {
        system: defaultdict(list) for system in (MOONCAKE, AEGISKV)
    }
    ecdf_whole: list[dict[str, object]] = []
    ecdf_failure_focus: list[dict[str, object]] = []
    ecdf_variant_local_impacted_union: list[dict[str, object]] = []
    aimd_traces: list[dict[str, object]] = []
    alignment_rows: list[dict[str, object]] = []
    reference_workflows: set[str] | None = None
    admission_fingerprints: list[str] = []
    workload_fingerprint: str | None = None
    for seed, cell in normalized:
        current_workload_fingerprint = _string(
            cell.get("workload_fingerprint"), f"seed-{seed}.workload_fingerprint"
        )
        if workload_fingerprint is None:
            workload_fingerprint = current_workload_fingerprint
        elif current_workload_fingerprint != workload_fingerprint:
            raise PaperSweepStatisticsError("workload fingerprint drifted across seeds")
        moon_run = _run(cell, MOONCAKE, seed)
        aegis_run = _run(cell, AEGISKV, seed)
        moon_wct = _wct(moon_run, f"seed-{seed}.{MOONCAKE}")
        aegis_wct = _wct(aegis_run, f"seed-{seed}.{AEGISKV}")
        workflow_ids = set(moon_wct)
        if workflow_ids != set(aegis_wct):
            raise PaperSweepStatisticsError(f"seed-{seed} workflow WCT sets are not aligned")
        try:
            admission_fingerprints.append(
                paired_admission_fingerprint(
                    {MOONCAKE: moon_run, AEGISKV: aegis_run},
                    seed=seed,
                    workflow_ids=workflow_ids,
                )
            )
        except ValueError as error:
            raise PaperSweepStatisticsError(str(error)) from error
        if reference_workflows is None:
            reference_workflows = workflow_ids
        elif workflow_ids != reference_workflows:
            raise PaperSweepStatisticsError("workflow WCT set drifted across seeds")

        moon_focus = _span_index(moon_run, "failure_focus_spans", f"seed-{seed}.{MOONCAKE}")
        aegis_focus = _span_index(aegis_run, "failure_focus_spans", f"seed-{seed}.{AEGISKV}")
        if not moon_focus or set(moon_focus) != set(aegis_focus):
            raise PaperSweepStatisticsError(f"seed-{seed} logical focus span sets are not aligned")
        for span_id in moon_focus:
            if moon_focus[span_id]["workflow_id"] != aegis_focus[span_id]["workflow_id"]:
                raise PaperSweepStatisticsError(
                    f"seed-{seed} focus span {span_id} maps to different workflows"
                )
        declared_focus = _object(
            cell.get("failure_focus_span_ids_by_system"),
            f"seed-{seed}.failure_focus_span_ids_by_system",
        )
        if set(declared_focus) != {MOONCAKE, AEGISKV}:
            raise PaperSweepStatisticsError(f"seed-{seed} focus declaration systems drifted")
        for system in (MOONCAKE, AEGISKV):
            declared_ids = {
                _string(value, f"seed-{seed}.declared_focus.{system}[]")
                for value in _array(declared_focus[system], f"seed-{seed}.declared_focus.{system}")
            }
            if declared_ids != set(moon_focus):
                raise PaperSweepStatisticsError(
                    f"seed-{seed} declared focus IDs do not match logical focus rows"
                )

        moon_affected = _affected_workflows(moon_run, f"seed-{seed}.{MOONCAKE}")
        aegis_affected = _affected_workflows(aegis_run, f"seed-{seed}.{AEGISKV}")
        impacted_union = moon_affected | aegis_affected
        focus_workflows = {str(row["workflow_id"]) for row in moon_focus.values()}
        if not impacted_union <= workflow_ids or not focus_workflows <= workflow_ids:
            raise PaperSweepStatisticsError(
                f"seed-{seed} impacted/focus workflows are outside the aligned workload"
            )
        # The logical focus is frozen before either variant is executed.  It is
        # therefore the only causal failure-local cohort.  Variant-local impact
        # reports are post-treatment diagnostics and must not select either the
        # primary benefit cohort or its non-focus complement.
        non_focus = workflow_ids - focus_workflows
        impact_count_samples[MOONCAKE].append((seed, Fraction(len(moon_affected))))
        impact_count_samples[AEGISKV].append((seed, Fraction(len(aegis_affected))))
        impact_count_samples["union"].append((seed, Fraction(len(impacted_union))))
        impact_count_samples["logical_focus"].append((seed, Fraction(len(focus_workflows))))
        metric_samples["whole_mean_wct_gain_percent"].append(
            (seed, _mean_gain_percent(moon_wct, aegis_wct, workflow_ids))
        )
        metric_samples["failure_focus_mean_wct_gain_percent"].append(
            (seed, _mean_gain_percent(moon_wct, aegis_wct, focus_workflows))
        )
        metric_samples["failure_focus_p95_wct_gain_percent"].append(
            (seed, _p95_gain_percent(moon_wct, aegis_wct, focus_workflows))
        )
        metric_samples["variant_local_impacted_union_mean_wct_gain_percent"].append(
            (seed, _mean_gain_percent(moon_wct, aegis_wct, impacted_union))
        )
        metric_samples["variant_local_impacted_union_p95_wct_gain_percent"].append(
            (seed, _p95_gain_percent(moon_wct, aegis_wct, impacted_union))
        )
        non_focus_gap = _unaffected_gap_percent(moon_wct, aegis_wct, non_focus)
        metric_samples["non_focus_mean_absolute_gap_percent"].append(
            (seed, non_focus_gap)
        )
        for subset, subset_ids in (
            ("whole", workflow_ids),
            ("failure_focus", focus_workflows),
            ("variant_local_impacted_union", impacted_union),
        ):
            absolute_wct_samples[subset][MOONCAKE].append(
                (seed, _mean_wct_ns(moon_wct, subset_ids))
            )
            absolute_wct_samples[subset][AEGISKV].append(
                (seed, _mean_wct_ns(aegis_wct, subset_ids))
            )
        alpha_mean, alpha_min, alpha_max, pressure_rate, trace = _alpha_statistics(aegis_run, seed)
        metric_samples["alpha_time_weighted_mean"].append((seed, alpha_mean))
        metric_samples["alpha_min"].append((seed, alpha_min))
        metric_samples["alpha_max"].append((seed, alpha_max))
        metric_samples["pressure_event_rate_percent"].append((seed, pressure_rate))
        aimd_traces.append({"seed": seed, "events": trace})
        for system, focus in ((MOONCAKE, moon_focus), (AEGISKV, aegis_focus)):
            selected = _selected_tier_tokens(focus, seed)
            available = _available_tier_tokens(focus, seed, system)
            for tier, value in selected.items():
                selected_tier_samples[system][tier].append((seed, Fraction(value)))
            for tier, value in available.items():
                available_tier_samples[system][tier].append((seed, Fraction(value)))
        ordered_workflows = sorted(workflow_ids)
        ordered_focus = sorted(focus_workflows)
        ordered_impacted_union = sorted(impacted_union)
        ecdf_whole.append(
            {
                "seed": seed,
                "workflow_ids": ordered_workflows,
                "wct_ns": {
                    MOONCAKE: [moon_wct[item] for item in ordered_workflows],
                    AEGISKV: [aegis_wct[item] for item in ordered_workflows],
                },
            }
        )
        ecdf_failure_focus.append(
            {
                "seed": seed,
                "workflow_ids": ordered_focus,
                "wct_ns": {
                    MOONCAKE: [moon_wct[item] for item in ordered_focus],
                    AEGISKV: [aegis_wct[item] for item in ordered_focus],
                },
            }
        )
        ecdf_variant_local_impacted_union.append(
            {
                "seed": seed,
                "workflow_ids": ordered_impacted_union,
                "wct_ns": {
                    MOONCAKE: [moon_wct[item] for item in ordered_impacted_union],
                    AEGISKV: [aegis_wct[item] for item in ordered_impacted_union],
                },
            }
        )
        alignment_rows.append(
            {
                "seed": seed,
                "workflow_count": len(workflow_ids),
                "failure_focus_workflow_count": len(focus_workflows),
                "variant_local_impacted_union_workflow_count": len(impacted_union),
                # Compatibility counts retain their historical spelling but
                # are explicitly descriptive, never cohort selectors.
                "affected_workflow_count": len(impacted_union),
                "focus_workflow_count": len(focus_workflows),
                "focus_span_count": len(moon_focus),
                "workflow_ids_sha256": sha256_json(sorted(workflow_ids)),
                "focus_span_ids_sha256": sha256_json(sorted(moon_focus)),
                "failure_focus_workflow_ids_sha256": sha256_json(ordered_focus),
                "primary_failure_local_selection": (
                    "pre_frozen_logical_failure_focus_workflow_ids"
                ),
                "descriptive_impacted_selection": (
                    "union_of_variant_local_impacted_workflow_ids"
                ),
                "affected_selection": "union_of_variant_local_impacted_workflow_ids",
                "system_pair_aligned": True,
                "workflow_set_aligned": True,
                "logical_focus_aligned": True,
            }
        )

    percent_metrics = {
        key: _summarize(values, unit="percent_millionths", scale=PERCENT_MILLIONTH_SCALE)
        for key, values in metric_samples.items()
        if key.endswith("_percent")
    }
    alpha_metrics = {
        key.removeprefix("alpha_"): _summarize(
            values, unit="fraction_millionths", scale=FRACTION_MILLIONTH_SCALE
        )
        for key, values in metric_samples.items()
        if key.startswith("alpha_")
    }
    non_focus_samples = metric_samples["non_focus_mean_absolute_gap_percent"]
    per_seed_gate = [
        {
            "seed": seed,
            "exact_gap_percent": _fraction_json(value),
            "pass": value <= 1,
        }
        for seed, value in non_focus_samples
    ]
    try:
        require_distinct_admissions(admission_fingerprints)
    except ValueError as error:
        raise PaperSweepStatisticsError(str(error)) from error
    non_focus_gate_pass = all(bool(row["pass"]) for row in per_seed_gate)

    failure_focus_mean = percent_metrics["failure_focus_mean_wct_gain_percent"]
    failure_focus_p95 = percent_metrics["failure_focus_p95_wct_gain_percent"]
    impacted_union_mean = percent_metrics[
        "variant_local_impacted_union_mean_wct_gain_percent"
    ]
    impacted_union_p95 = percent_metrics[
        "variant_local_impacted_union_p95_wct_gain_percent"
    ]
    p95_seed_values = metric_samples["failure_focus_p95_wct_gain_percent"]
    p95_point_estimate = sum(
        (value for _seed, value in p95_seed_values), start=Fraction(0)
    ) / len(p95_seed_values)
    p95_estimate = _object(failure_focus_p95["estimate"], "internal.failure_focus_p95.estimate")
    p95_ci = _object(p95_estimate.get("ci95"), "internal.failure_focus_p95.ci95")
    p95_ci_lower = p95_ci.get("lower_floor")
    p95_ci_upper = p95_ci.get("upper_ceiling")
    if (
        p95_ci.get("status") != "ESTIMATED"
        or type(p95_ci_lower) is not int
        or type(p95_ci_upper) is not int
    ):
        raise PaperSweepStatisticsError(
            "failure-focus P95 interpretation requires an estimated seed-level 95% CI"
        )
    base_gate_applies = cell_identity == (2, 16)
    base_point_positive = p95_point_estimate > 0
    base_ci_lower_positive = p95_ci_lower > 0
    base_ci_upper_negative = p95_ci_upper < 0
    base_failure_focus_expectation_met = (
        base_point_positive and base_ci_lower_positive
    )
    if base_ci_lower_positive:
        result_interpretation = "POSITIVE_SIGNIFICANT_AT_95_PERCENT"
    elif base_ci_upper_negative:
        result_interpretation = "NEGATIVE_SIGNIFICANT_AT_95_PERCENT"
    elif base_point_positive:
        result_interpretation = "POSITIVE_POINT_ESTIMATE_CI_CROSSES_ZERO"
    elif p95_point_estimate < 0:
        result_interpretation = "NEGATIVE_POINT_ESTIMATE_CI_CROSSES_ZERO"
    else:
        result_interpretation = "ZERO_POINT_ESTIMATE_CI_CROSSES_ZERO"
    base_failure_focus_gate = {
        "applies": base_gate_applies,
        "status": (
            result_interpretation
            if base_gate_applies
            else "NOT_APPLICABLE"
        ),
        "base_failure_count": 2,
        "base_workflow_concurrency": 16,
        "primary_cohort": "pre_frozen_logical_failure_focus_workflow_ids",
        "metric_path": "wct_gain.failure_focus_p95",
        "point_estimate_exact_percent": _fraction_json(p95_point_estimate),
        "point_estimate_positive": base_point_positive,
        "ci95_lower_percent_millionths": p95_ci_lower,
        "ci95_lower_positive": base_ci_lower_positive,
        "ci95_upper_percent_millionths": p95_ci_upper,
        "ci95_upper_negative": base_ci_upper_negative,
        "result_interpretation": result_interpretation,
        "diagnostic_definition": (
            "for F=2,C=16, classify the observed paired seed-level failure-focus "
            "P95 WCT gain from its point estimate and two-sided 95% Student-t CI"
        ),
        "expected_positive_significant_result_observed": (
            base_failure_focus_expectation_met if base_gate_applies else None
        ),
        "blocks_artifact_generation": False,
        # Compatibility field: this is an expectation check, not a validity gate.
        "pass": base_failure_focus_expectation_met if base_gate_applies else None,
    }
    unmet_result_expectations: list[str] = []
    if not non_focus_gate_pass:
        unmet_result_expectations.append("NON_FOCUS_MEAN_GAP_EXCEEDS_1_PERCENT")
    if base_gate_applies and not base_failure_focus_expectation_met:
        unmet_result_expectations.append(
            "BASE_FAILURE_FOCUS_P95_NOT_POSITIVE_SIGNIFICANT_AT_95_PERCENT"
        )

    absolute_mean_wct = {
        subset: {
            system: _summarize(values, unit="ns", scale=1)
            for system, values in systems.items()
        }
        for subset, systems in absolute_wct_samples.items()
    }
    # Compatibility aliases use the corrected causal cohort.  The old
    # variant-local union is retained under an explicitly descriptive name.
    absolute_mean_wct["focus"] = absolute_mean_wct["failure_focus"]
    absolute_mean_wct["affected"] = absolute_mean_wct["failure_focus"]
    non_focus_match = {
        "cohort": "all_workflows_minus_pre_frozen_logical_failure_focus_workflows",
        "metric": percent_metrics["non_focus_mean_absolute_gap_percent"],
        "gate_definition": "each seed absolute mean WCT gap <= 1% of Mooncake mean",
        "threshold_percent": 1,
        "per_seed_gate": per_seed_gate,
        "all_seeds_pass": non_focus_gate_pass,
        "variant_local_impacted_membership_used": False,
    }
    impacted_workflow_counts = {
        key: _summarize(values, unit="workflows", scale=1)
        for key, values in sorted(impact_count_samples.items())
    }
    document: dict[str, Any] = {
        "schema": STATISTICS_SCHEMA,
        "status": "PASS",
        "status_semantics": (
            "PASS means paired inputs and statistics are valid; observed effect "
            "direction and significance never block artifact generation"
        ),
        "failed_paper_gates": [],
        "unmet_result_expectations": unmet_result_expectations,
        "cell_identity": {
            "failure_count": cell_identity[0],
            "workflow_concurrency": cell_identity[1],
        },
        "workload_fingerprint": workload_fingerprint,
        "sampling_contract": {
            "independent_unit": "seed",
            "randomized_input": "workflow_admission_permutation",
            "distinct_admission_order_count": len(set(admission_fingerprints)),
            "admission_order_sha256_by_seed": dict(
                zip((str(seed) for seed, _cell in normalized), admission_fingerprints, strict=True)
            ),
            "minimum_seed_count": MINIMUM_SEED_COUNT,
            "seed_count": len(normalized),
            "seeds": [seed for seed, _cell in normalized],
            "paired_systems": [MOONCAKE, AEGISKV],
            "confidence_level_percent": 95,
            "interval_method": "two_sided_student_t_95_conservative_table",
            "p95_method": "nearest_rank_ceiling",
            "smoothing_performed": False,
        },
        "alignment_audit": alignment_rows,
        "wct_gain": {
            "effect_definition": "100*(Mooncake-AegisKV)/Mooncake",
            "whole_mean": percent_metrics["whole_mean_wct_gain_percent"],
            "primary_failure_local_cohort": (
                "pre_frozen_logical_failure_focus_workflow_ids"
            ),
            "failure_focus_mean": failure_focus_mean,
            "failure_focus_p95": failure_focus_p95,
            "descriptive_variant_local_impacted_union_mean": impacted_union_mean,
            "descriptive_variant_local_impacted_union_p95": impacted_union_p95,
            # Legacy paths are aliases of the corrected primary cohort.  They
            # must not be interpreted as the variant-local impacted union.
            "failure_affected_mean": failure_focus_mean,
            "logical_focus_mean": failure_focus_mean,
            "failure_affected_p95": failure_focus_p95,
        },
        "absolute_mean_wct_ns": absolute_mean_wct,
        "ecdf_observations": {
            "whole_workload": {"per_seed": ecdf_whole},
            "failure_focus": {"per_seed": ecdf_failure_focus},
            "variant_local_impacted_union": {
                "per_seed": ecdf_variant_local_impacted_union
            },
            "failure_affected": {"per_seed": ecdf_failure_focus},
            "pooling_rule": "descriptive concatenation of seed-level observed WCTs",
            "seed_is_independent_unit_for_ci": True,
        },
        "paper_gates": {
            "non_focus_workflow_match": non_focus_match,
            "base_failure_focus_p95_gain": base_failure_focus_gate,
            "all_applicable_pass": not unmet_result_expectations,
            "blocks_artifact_generation": False,
            "semantics": (
                "compatibility name only; entries are result diagnostics and do not "
                "filter negative, null, or statistically inconclusive observations"
            ),
        },
        "non_focus_workflow_match": non_focus_match,
        "unaffected_workflow_match": non_focus_match,
        "descriptive_variant_local_impacted_workflow_count": impacted_workflow_counts,
        "failure_impacted_workflow_count": impacted_workflow_counts,
        "field_compatibility": {
            "wct_gain.failure_affected_mean": "wct_gain.failure_focus_mean",
            "wct_gain.logical_focus_mean": "wct_gain.failure_focus_mean",
            "wct_gain.failure_affected_p95": "wct_gain.failure_focus_p95",
            "absolute_mean_wct_ns.affected": "absolute_mean_wct_ns.failure_focus",
            "absolute_mean_wct_ns.focus": "absolute_mean_wct_ns.failure_focus",
            "ecdf_observations.failure_affected": "ecdf_observations.failure_focus",
            "unaffected_workflow_match": "non_focus_workflow_match",
            "failure_impacted_workflow_count": (
                "descriptive_variant_local_impacted_workflow_count"
            ),
        },
        "aimd": {
            "time_weighted_mean": alpha_metrics["time_weighted_mean"],
            "range_min": alpha_metrics["min"],
            "range_max": alpha_metrics["max"],
            "pressure_event_rate": percent_metrics["pressure_event_rate_percent"],
            "time_weighting": (
                "integral of each target alpha over [0, workload_end_ns], averaged across targets"
            ),
            "observed_trace_by_seed": aimd_traces,
        },
        "tier_selected_kv_tokens": {
            system: {
                tier: _summarize(values, unit="tokens", scale=1)
                for tier, values in sorted(tiers.items())
            }
            for system, tiers in selected_tier_samples.items()
        },
        "tier_selected_aggregation_rule": (
            "report actual source-selected tiers separately; cross-tier total omitted to avoid "
            "double-counting overlapping logical prefixes"
        ),
        "tier_available_kv_tokens": {
            system: {
                tier: _summarize(values, unit="tokens", scale=1)
                for tier, values in sorted(tiers.items())
            }
            for system, tiers in available_tier_samples.items()
        },
        "provenance": {
            "input_cell_sha256_by_seed": {
                str(seed): sha256_json(cell) for seed, cell in normalized
            },
            "observed_values_only": True,
            "trend_generation_performed": False,
            "physical_measurement_claimed": False,
        },
    }
    document["fingerprint"] = sha256_json(document)
    return document


__all__ = [
    "AEGISKV",
    "FRACTION_MILLIONTH_SCALE",
    "MINIMUM_SEED_COUNT",
    "MOONCAKE",
    "PERCENT_MILLIONTH_SCALE",
    "STATISTICS_SCHEMA",
    "PaperSweepStatisticsError",
    "build_paper_sweep_statistics",
]
