"""Execution and peer placement for the design Router.

A retry target sits outside the execution worker's host. Among those
workers, Router prefers a short queue, then a quiet H2D path, then more
free peer DRAM.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable


class Router:
    def __init__(
        self,
        hosts: tuple[int, ...],
        *,
        queue_load: Callable[[int], int],
        free_dram: Callable[[int], int],
        h2d_flows: Callable[[int], int],
        has_prefix: Callable[[int], bool],
    ):
        self.hosts = hosts
        self.queue_load = queue_load
        self.free_dram = free_dram
        self.h2d_flows = h2d_flows
        self.has_prefix = has_prefix

    def place_execution(self, alive: Iterable[int]) -> int:
        return min(
            alive,
            key=lambda worker: (
                self.queue_load(worker) - int(self.has_prefix(worker)),
                worker,
            ),
        )

    def choose_peer(self, source: int, alive: Iterable[int]) -> int | None:
        source_host = self.hosts[source]
        candidates = [worker for worker in alive if self.hosts[worker] != source_host]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda worker: (
                self.queue_load(worker),
                self.h2d_flows(worker),
                -self.free_dram(worker),
                worker,
            ),
        )
