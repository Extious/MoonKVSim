"""Per-query block demand from a captured sparse-model forward.

``selected_blocks`` has shape (groups, queries, indices) and already
records only blocks that query was allowed to read.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .model import Config, Invocation


class NativeTraceDemand:
    name = "native-selector-trace"

    def __init__(self, layers: list[np.ndarray]):
        if not layers:
            raise ValueError("native trace has no layers")
        queries = layers[0].shape[1]
        if any(layer.ndim != 3 or layer.shape[1] != queries for layer in layers):
            raise ValueError("native layers do not share a query axis")
        self.layers = layers
        self.queries = queries

    @classmethod
    def load(cls, directory: Path, *, n_layers: int) -> NativeTraceDemand:
        layers = []
        for index in range(1, n_layers + 1):
            path = directory / f"layer-{index:02d}.npz"
            with np.load(path) as archive:
                layers.append(np.array(archive["selected_blocks"], copy=True))
        return cls(layers)

    def __call__(
        self,
        config: Config,
        invocation: Invocation,
        layer: int,
        query: int,
        visible: int,
    ) -> set[int]:
        del invocation
        if layer >= len(self.layers) or query >= self.queries:
            raise ValueError("query is outside the captured trace")
        selected = self.layers[layer][:, query].reshape(-1)
        return {int(block) for block in selected if 0 <= int(block) < visible}
