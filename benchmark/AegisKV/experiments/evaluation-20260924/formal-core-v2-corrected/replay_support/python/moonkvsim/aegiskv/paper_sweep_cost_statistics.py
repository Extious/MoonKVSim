"""Cost/effect diagnostics and a fixed, adverse-first counterexample selection."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any

from moonkvsim.aegiskv.paper_sweep_statistics import (
    AEGISKV,
    MOONCAKE,
    _fraction_json,
    _mean_gain_percent,
    _p95_gain_percent,
    _summarize,
)
from moonkvsim.common.hash import sha256_json

POINTS = {(1, 16), (2, 16), (4, 16), (8, 16), (2, 8), (2, 24), (2, 32)}


def _nonnegative(value: Any, where: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{where} must be a nonnegative integer")
    return value


def build_sweep_cost_statistics(
    cells: Sequence[Mapping[str, Any]], records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Use all 35 paired cells; these F>0 contrasts are not difference-in-differences."""
    identities = [(c["failure_count"], c["workflow_concurrency"], c["seed"]) for c in cells]
    if len(cells) != 35 or set(identities) != {
        (f, c, seed) for f, c in POINTS for seed in range(5)
    }:
        raise ValueError("cost diagnostics require the complete 35-cell matrix")
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    counterexamples: list[tuple[Fraction, dict[str, Any]]] = []
    for cell in sorted(cells, key=lambda c: (c["failure_count"], c["workflow_concurrency"],
                                           c["seed"])):
        f, concurrency, seed = cell["failure_count"], cell["workflow_concurrency"], cell["seed"]
        runs = {s: cell["systems"][s]["run"] for s in (MOONCAKE, AEGISKV)}
        wct = {s: r["metrics"]["workflow_completion_time_ns"]["by_workflow_id"]
               for s, r in runs.items()}
        if set(wct[MOONCAKE]) != set(wct[AEGISKV]) or any(
            type(v) is not int or v <= 0 for values in wct.values() for v in values.values()
        ):
            raise ValueError("cost diagnostic WCT population is invalid")
        focus = {s: {r["span_id"]: r for r in run["failure_focus_spans"]}
                 for s, run in runs.items()}
        if set(focus[MOONCAKE]) != set(focus[AEGISKV]) or any(
            len(rows) != f or len(runs[s]["failure_focus_spans"]) != f
            for s, rows in focus.items()
        ):
            raise ValueError("cost diagnostic logical focus population is invalid")
        focus_workflows = set()
        restored = {}
        protection = {}
        for system, rows in focus.items():
            restored_tokens = prompt_tokens = 0
            for span_id, row in rows.items():
                record = records[span_id]
                if (row["workflow_id"] != record["workflow_id"]
                        or row["workflow_id"] not in wct[system]):
                    raise ValueError("focus identity differs from the frozen workload")
                focus_workflows.add(row["workflow_id"])
                prompt = _nonnegative(record["prompt_tokens"], "frozen prompt")
                parts = [_nonnegative(row[key], key) for key in (
                    "recovery_normal_hbm_local_tokens", "restored_peer_tokens",
                    "restored_store_tokens", "recompute_tokens",
                )]
                if sum(parts) != prompt or prompt == 0:
                    raise ValueError("focus recovery does not conserve its frozen prompt")
                restored_tokens += parts[1] + parts[2]
                prompt_tokens += prompt
            restored[system] = Fraction(restored_tokens * 100, prompt_tokens)
            cost = runs[system]["metrics"]["resource_cost"]
            if cost["transfer_byte_conservation_valid"] is not True:
                raise ValueError("cost diagnostic transfer conservation failed")
            protection[system] = sum(
                _nonnegative(value, "cause bytes") for cause, value in cost["cause_bytes"].items()
                if cause.endswith("_PROTECTION")
            )
        grouped[f, concurrency].append({
            "seed": seed, "protection_bytes": protection,
            "restored_percent": restored,
            "focus_mean_gain_percent": _mean_gain_percent(wct[MOONCAKE], wct[AEGISKV],
                                                          focus_workflows),
            "focus_p95_gain_percent": _p95_gain_percent(wct[MOONCAKE], wct[AEGISKV],
                                                        focus_workflows),
        })
        bindings = {s: r["raw_evidence"]["sha256"] for s, r in runs.items()}
        for workflow in sorted(focus_workflows):
            gain = Fraction((wct[MOONCAKE][workflow] - wct[AEGISKV][workflow]) * 100,
                            wct[MOONCAKE][workflow])
            counterexamples.append((gain, {
                "seed": seed, "failure_count": f, "workflow_concurrency": concurrency,
                "workflow_id": workflow,
                "focus_span_ids": sorted(span for span, r in focus[MOONCAKE].items()
                                         if r["workflow_id"] == workflow),
                "wct_ns": {s: values[workflow] for s, values in wct.items()},
                "gain_percent_exact": _fraction_json(gain),
                "raw_sha256_by_system": bindings,
            }))
    points = []
    for (f, concurrency), seed_rows in sorted(grouped.items()):
        points.append({
            "failure_count": f, "workflow_concurrency": concurrency,
            "protection_transferred_bytes": {s: _summarize(
                [(r["seed"], Fraction(r["protection_bytes"][s])) for r in seed_rows],
                unit="bytes", scale=1,
            ) for s in (MOONCAKE, AEGISKV)},
            "restored_prompt_percent": {s: _summarize(
                [(r["seed"], r["restored_percent"][s]) for r in seed_rows],
                unit="percent", scale=1_000_000,
            ) for s in (MOONCAKE, AEGISKV)},
            **{metric: _summarize([(r["seed"], r[metric]) for r in seed_rows],
                                  unit="percent", scale=1_000_000)
               for metric in ("focus_mean_gain_percent", "focus_p95_gain_percent")},
        })
    ordered = [r for _, r in sorted(counterexamples, key=lambda pair: (
        pair[0], pair[1]["seed"], pair[1]["failure_count"],
        pair[1]["workflow_concurrency"], pair[1]["workflow_id"],
    ))]
    body = {
        "schema": "moonkvsim.aegiskv.paper-sweep-cost-statistics.v1", "status": "PASS",
        "seed_count": 5, "paired_cell_count": 35, "points": points,
        "all_focus_workflow_effects_ascending": ordered,
        "five_lowest_paired_effects": ordered[:5],
        "selection_rule": ("ascending exact gain, seed, F, C, workflow ID; "
                           "deduplicate workflow within cell"),
        "gain_sign": "100 * (Store-only WCT - AegisKV WCT) / Store-only WCT; positive is faster",
        "cost_definition": ("bytes actually transmitted by protection transfers, "
                            "including aborted prefixes"),
        "restored_definition": ("100 * sum(Peer + Store restored tokens) / "
                                "sum(frozen focus prompt tokens)"),
        "effect_estimand": "policy contrast in failure runs; no F0 subtraction",
        "frontier_interpretation": ("descriptive cost/effect association; "
                                    "no Pareto or causal cost claim"),
        "independent_unit": "paired admission seed within each F,C point",
        "counterexample_dependence": ("same workload and seeds recur across F,C; "
                                      "ranked cases are diagnostics"),
        "effect_direction_filter_applied": False,
    }
    return {**body, "fingerprint": sha256_json(body)}
