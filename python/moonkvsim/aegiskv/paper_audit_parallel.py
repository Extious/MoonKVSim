"""Bounded process parallelism for independent raw-evidence checks."""
from __future__ import annotations

import multiprocessing
import os
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def audit_map(function: Callable[[T], R], tasks: Iterable[T]) -> list[R]:
    workers = int(os.environ.get("MOONKVSIM_AUDIT_WORKERS", "1"))
    if not 1 <= workers <= 8:
        raise ValueError("MOONKVSIM_AUDIT_WORKERS must be between 1 and 8")
    items = list(tasks)
    if workers == 1 or len(items) < 2:
        return [function(task) for task in items]
    with ProcessPoolExecutor(max_workers=min(workers, len(items)),
                             mp_context=multiprocessing.get_context("fork")) as pool:
        # map preserves the declared task order, so parallel auditing cannot
        # change statistical aggregation or manifest ordering.
        return list(pool.map(function, items, chunksize=1))
