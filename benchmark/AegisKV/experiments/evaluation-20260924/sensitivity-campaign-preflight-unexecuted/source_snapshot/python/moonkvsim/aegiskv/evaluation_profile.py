"""Pinned shape-grid timing adapter for the current AegisKV simulator.

All interpolation is explicit and bounded. An AIConfigurator source tag is not
an end-to-end calibration, and no hardware is executed by this module.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from functools import lru_cache
from math import ceil, isfinite
from pathlib import Path

from .current.model import Config, Invocation


def bracket(values: tuple[int, ...], query: int) -> tuple[int, int, float]:
    if query < values[0] or query > values[-1]:
        raise ValueError(f"shape {query} outside profiled range [{values[0]}, {values[-1]}]")
    upper = bisect_left(values, query)
    if values[upper] == query:
        return query, query, 0.0
    lo, hi = values[upper - 1], values[upper]
    return lo, hi, (query - lo) / (hi - lo)


class GridDurationProfile:
    """Bilinear prefix/extend interpolation; decode costs summed per token.

    Large prefill estimates are the sum of the same forward chunks used by the
    runtime. Thus admission never estimates one long prefill while execution
    charges many smaller forwards. Endpoints are integers; no extrapolation.
    """

    def __init__(self, path: Path | str, *, scale: float = 1.0):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text())
        if self.data.get("schema") != "aegiskv.duration-grid.v1":
            raise ValueError("unrecognized duration profile")
        if not isfinite(scale) or scale <= 0:
            raise ValueError("duration scale must be finite and positive")
        self.scale = scale
        self.contexts = tuple(self.data["context_grid"])
        self.extends = tuple(self.data["prefill_extend_grid"])
        if sorted(set(self.contexts)) != list(self.contexts) or self.contexts[0] != 0:
            raise ValueError("context grid must be unique, sorted, and begin at zero")
        if sorted(set(self.extends)) != list(self.extends) or self.extends[0] != 1:
            raise ValueError("extend grid must be unique, sorted, and begin at one")
        self.values = {}
        for row in self.data["rows"]:
            key = row["stage"], row["context"], row["extend"]
            if key in self.values or row["latency_ns"] <= 0:
                raise ValueError("duplicate/nonpositive profile shape")
            self.values[key] = row["latency_ns"]
        expected = {
            (stage, context, extend)
            for context in self.contexts
            for stage, extend in [("decode", 1), *[("prefill", n) for n in self.extends]]
        }
        if self.values.keys() != expected:
            raise ValueError("incomplete or surplus timing grid")
        self.shape = lru_cache(maxsize=65536)(self._shape)
        self.duration = lru_cache(maxsize=131072)(self._duration)

    def _shape(self, stage: str, context: int, extend: int) -> float:
        lo, hi, weight = bracket(self.contexts, context)
        e_lo, e_hi, e_weight = bracket(self.extends if stage == "prefill" else (1,), extend)

        def at(prefix):
            first = self.values[stage, prefix, e_lo]
            return first + e_weight * (self.values[stage, prefix, e_hi] - first)

        first = at(lo)
        return (first + weight * (at(hi) - first)) * self.scale

    def validate(self, config: Config, invocation: Invocation) -> None:
        geometry = self.data["config"]
        expected_kv = (
            2 * geometry["num_key_value_heads"] * geometry["head_dim"] * 2 // self.data["tp"]
        )
        if (config.tp, config.layers, config.kv_bytes_per_token_per_layer_rank) != (
            self.data["tp"],
            geometry["num_hidden_layers"],
            expected_kv,
        ):
            raise ValueError("duration profile and simulated model/TP geometry disagree")
        if invocation.model != self.data["model"]:
            raise ValueError("invocation model differs from duration profile")
        if invocation.layout != "bf16-kv":
            raise ValueError("profile requires BF16 KV layout")

    def _duration(self, start: int, end: int, stage: str, chunk: int, checkpoint: int = 256) -> int:
        if not 0 <= start <= end <= self.contexts[-1]:
            raise ValueError("duration query exceeds profile bounds")
        if stage not in {"prefill", "decode"}:
            raise ValueError("unknown forward phase")
        if chunk < 1 or chunk > self.extends[-1] or checkpoint < 1:
            raise ValueError("prefill chunk exceeds profile coverage")
        if start == end:
            return 0
        total = 0.0
        if stage == "decode":
            # Each generated token requires one sequential decode forward.
            # Token batching in DES coalesces events, not independent steps.
            total = sum(self.shape("decode", token, 1) for token in range(start, end))
        else:
            cursor = start
            while cursor < end:
                stop = min(end, cursor + chunk, (cursor // checkpoint + 1) * checkpoint)
                total += self.shape("prefill", cursor, stop - cursor)
                cursor = stop
        return ceil(total)

    def __call__(
        self, config: Config, invocation: Invocation, start: int, end: int, stage: str
    ) -> int:
        self.validate(config, invocation)
        chunk = getattr(config, "prefill_chunk_tokens", config.block_tokens)
        return self.duration(start, end, stage, chunk, config.checkpoint_tokens)
