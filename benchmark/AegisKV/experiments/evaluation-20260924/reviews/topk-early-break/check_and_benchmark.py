"""Differential/microbenchmark evidence for an isolated Top-K early-break change."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import platform
import random
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT / "python"))


def load(name):
    qualified = "moonkvsim.aegiskv.current." + name
    spec = importlib.util.spec_from_file_location(qualified, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module.top_blocks


ORIGINAL, PROTOTYPE = load("policy_original"), load("policy_prototype")


def compare(scores, k, incumbent, epsilon, *, layer=0, omit_zeros=False):
    counts = {(layer, b): score for b, score in enumerate(scores) if score or not omit_zeros}
    counts.update({(layer + 1, b): 99999 for b in range(3)})
    arguments = counts, layer, len(scores), k
    options = dict(incumbent=incumbent, hysteresis=epsilon)
    old = ORIGINAL(*arguments, **options)
    new = PROTOTYPE(*arguments, **options)
    assert old == new, (scores, k, incumbent, epsilon, old, new)


def differential():
    started = time.perf_counter()
    exhaustive = 0
    for blocks in range(6):
        for scores in itertools.product((0, 1, 2), repeat=blocks):
            for mask in range(1 << blocks):
                members = tuple(b for b in range(blocks) if mask & (1 << b))
                # Duplicate and invalid IDs exercise existing set/filter behavior.
                incumbent = (-1, blocks + 1, *members, *reversed(members))
                for k in range(blocks + 2):
                    for epsilon in (0.0, 0.1, 1.0):
                        compare(scores, k, incumbent, epsilon, omit_zeros=True)
                        exhaustive += 1
    rng = random.Random(20260924)
    numeric = (
        -1e300,
        -1.0,
        -math.ulp(0.0),
        -0.0,
        0.0,
        math.ulp(0.0),
        1e-200,
        0.1,
        0.9,
        1.0,
        math.nextafter(1.0, 2.0),
        math.nextafter(1.1, 0.0),
        1.1,
        math.nextafter(1.1, 2.0),
        2.0,
        1000.0,
        1e200,
        1e300,
    )
    randomized = 20000
    for index in range(randomized):
        blocks = rng.choice((0, 1, 2, 4, 8, 16, 32, 64, 128, 256))
        scores = [rng.choice(numeric) for _ in range(blocks)]
        if index % 3 == 0:
            scores = [rng.randrange(100) * rng.random() for _ in range(blocks)]
        k = rng.choice((0, 1, 4, 16, blocks, blocks + 1))
        incumbent = tuple(rng.randint(-3, blocks + 3) for _ in range(rng.randrange(blocks + 5)))
        epsilon = rng.choice((0.0, 0.1, 0.9, 1.0, 10.0, 1e300))
        compare(scores, k, incumbent, epsilon, layer=index % 36, omit_zeros=index % 2 == 0)
    infinite = 0
    for scores in itertools.product((-math.inf, 0.0, 1.0, math.inf), repeat=3):
        for incumbent in ((), (0,), (1,), (2,), (0, 2), (0, 1, 2)):
            for k in range(5):
                compare(scores, k, incumbent, 0.1)
                infinite += 1
    # NaN is intentionally NOT part of the admissible runtime count domain.
    nan_counts = {(0, 0): 1.0, (0, 1): math.nan, (0, 2): 2.0}
    old = ORIGINAL(nan_counts, 0, 3, 1, incumbent=(0,))
    new = PROTOTYPE(nan_counts, 0, 3, 1, incumbent=(0,))
    assert old != new
    return dict(
        exhaustive_finite_cases=exhaustive,
        randomized_finite_cases=randomized,
        additional_infinity_cases=infinite,
        all_admissible_cases_exact_tuple_match=True,
        seconds=time.perf_counter() - started,
        nan_counterexample=dict(
            scores=[1.0, "NaN", 2.0],
            k=1,
            incumbent=[0],
            hysteresis=0,
            original=old,
            prototype=new,
            conclusion="NaN breaks the rank total order; do not claim unrestricted API equivalence",
        ),
    )


def elapsed(function, arguments, options, iterations):
    started = time.perf_counter_ns()
    for _ in range(iterations):
        function(*arguments, **options)
    return (time.perf_counter_ns() - started) / iterations


def benchmark():
    rows = []
    for blocks in (128, 512, 2048):
        for k in (4, 16):
            for case in ("all_tied", "stable_hot", "stale_incumbents"):
                scores = [1.0] * blocks if case == "all_tied" else list(range(blocks, 0, -1))
                incumbent = (
                    tuple(range(k))
                    if case != "stale_incumbents"
                    else tuple(range(blocks - k, blocks))
                )
                arguments = ({(0, b): s for b, s in enumerate(scores)}, 0, blocks, k)
                options = dict(incumbent=incumbent, hysteresis=0.1)
                assert ORIGINAL(*arguments, **options) == PROTOTYPE(*arguments, **options)
                cost = elapsed(ORIGINAL, arguments, options, 3)
                iterations = min(1000, max(5, int(50_000_000 / cost)))
                original, prototype = [], []
                for repeat in range(5):
                    order = (ORIGINAL, PROTOTYPE) if repeat % 2 == 0 else (PROTOTYPE, ORIGINAL)
                    for function in order:
                        target = original if function is ORIGINAL else prototype
                        target.append(elapsed(function, arguments, options, iterations))
                rows.append(
                    dict(
                        blocks=blocks,
                        k=k,
                        scenario=case,
                        iterations_per_repeat=iterations,
                        repeats=5,
                        original_ns_per_call=original,
                        prototype_ns_per_call=prototype,
                        original_median_ns=statistics.median(original),
                        prototype_median_ns=statistics.median(prototype),
                        median_speedup=statistics.median(original) / statistics.median(prototype),
                    )
                )
    return rows


def main():
    live = ROOT / "python/moonkvsim/aegiskv/current/policy.py"
    before = hashlib.sha256(live.read_bytes()).hexdigest()
    results = dict(
        differential=differential(),
        microbenchmark=benchmark(),
        python=platform.python_version(),
        platform=platform.platform(),
        clock="time.perf_counter_ns; alternating order; median of five batches",
        timing_limits=(
            "shared CPU host; descriptive microbenchmark, not end-to-end campaign speedup"
        ),
        live_policy_sha256=before,
        sources_sha256={
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob("*.py")
        },
    )
    assert hashlib.sha256(live.read_bytes()).hexdigest() == before
    results["live_policy_unchanged"] = True
    (HERE / "RESULTS.json").write_text(
        json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    print(json.dumps(results["differential"], indent=2))
    print(
        "microbenchmark speedups:",
        [round(r["median_speedup"], 2) for r in results["microbenchmark"]],
    )


if __name__ == "__main__":
    main()
