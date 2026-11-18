"""Current threshold/Top-K policy and per-rank AIMD, with no rental state."""

from __future__ import annotations

from dataclasses import dataclass

from .model import Config


@dataclass
class Adapter:
    config: Config
    quota: int
    stable: int = 0

    def update(self, serving_bytes: int, pressure: bool, deferred: bool) -> tuple[int, int]:
        old = self.quota
        ceiling = max(
            0,
            min(
                self.config.hbm_cap_bytes,
                self.config.hbm_bytes_per_rank - serving_bytes - self.config.reserve_bytes,
            ),
        )
        if pressure:
            self.quota = int(self.quota * self.config.decrease)
            self.stable = 0
        else:
            self.stable += 1
            if self.stable >= self.config.stable_windows and deferred:
                self.quota += self.config.additive_bytes
                self.stable = 0
        self.quota = min(self.quota, ceiling)
        return old, self.quota


def top_blocks(
    counts: dict[tuple[int, int], int], layer: int, blocks: int, k: int
) -> tuple[int, ...]:
    """Native selection COUNTS, per the 2026-09-23 manuscript (stable block ties)."""
    return tuple(sorted(range(blocks), key=lambda b: (-counts.get((layer, b), 0), b))[:k])


def demand(config: Config, layer: int, query: int, history_blocks: int) -> set[int]:
    """Causal demand provider used only by the explicit mechanism fixtures.

    Dense requests require all visible history. The synthetic selector rotates
    one extra block; history Top-K never determines actual recovery demand.
    """
    visible = min(history_blocks, query // config.block_tokens + 1)
    if config.attention == "dense":
        return set(range(visible))
    hot = min(config.synthetic_selected_blocks, visible)
    chosen = {(layer * 3 + i) % visible for i in range(hot)} if visible else set()
    if visible:
        chosen.add((query // config.block_tokens + layer) % visible)
    return chosen
