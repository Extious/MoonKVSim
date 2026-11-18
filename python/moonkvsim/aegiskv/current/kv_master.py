"""KV Master decisions that do not depend on the event loop.

Agent admission is E = max(T - slack, 0) above lambda, highest E first.
Within a protected Agent the HBM set is the Top-K of the first L layers.
"""

from __future__ import annotations


class KVMaster:
    def __init__(self, *, tolerance_ns: int, depth: int, top_k: int):
        self.tolerance_ns = tolerance_ns
        self.depth = depth
        self.top_k = top_k

    def needs_checkpoint(self, exposed_ns: int, *, protect_all: bool) -> bool:
        return protect_all or exposed_ns > self.tolerance_ns

    @staticmethod
    def admission_rank(exposed_ns: int, key: str) -> tuple[int, str]:
        return (-exposed_ns, key)
