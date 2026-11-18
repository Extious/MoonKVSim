"""Current threshold/Top-K policy and per-rank AIMD, with no rental state."""

from __future__ import annotations

from collections.abc import Iterable
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
    counts: dict[tuple[int, int], float],
    layer: int,
    blocks: int,
    k: int,
    *,
    incumbent: Iterable[int] = (),
    hysteresis: float = 0.0,
) -> tuple[int, ...]:
    """Checkpoint-only re-ranking; strict hysteresis preserves near-tied members."""

    def rank(b):
        return (-counts.get((layer, b), 0), b)

    ranked = sorted(range(blocks), key=rank)
    chosen = set(sorted({b for b in incumbent if 0 <= b < blocks}, key=rank)[:k])
    for b in ranked:
        if b in chosen:
            continue
        if len(chosen) < k:
            chosen.add(b)
        elif chosen:
            weakest = max(chosen, key=rank)
            if counts.get((layer, b), 0) > (1 + hysteresis) * counts.get((layer, weakest), 0):
                chosen.remove(weakest)
                chosen.add(b)
            else:
                break
    return tuple(sorted(chosen, key=rank))


def hbm_gain(dram_ns: int, hbm_ns: int, slack_ns: int) -> int:
    """Equation (HBM gain); a slow/valueless HBM placement is never admitted."""
    return max(0, max(0, dram_ns - slack_ns) - max(0, hbm_ns - slack_ns))


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
