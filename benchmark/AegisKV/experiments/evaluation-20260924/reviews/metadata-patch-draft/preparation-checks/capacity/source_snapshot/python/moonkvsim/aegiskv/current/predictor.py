"""Small trainable, serializable context regressor with no runtime dependencies.

This provides the paper's submission-context interface, not a claim of adequate
prediction accuracy. Text uses signed feature hashing; log-duration regression
is fitted offline. Calibration of workflow slack guards is a separate input.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass

from .tracker import Context


def features(context: Context) -> list[float]:
    def log(value: float) -> float:
        return math.log1p(max(0, value)) / 10

    numeric = [
        1.0,
        log(context.prompt_tokens),
        log(context.completed_calls),
        log(context.elapsed_ns / 1e9),
        log(context.prior_ns / 1e9),
        log(sum(context.previous_durations_ns) / 1e9),
        log(context.previous_durations_ns[-1] / 1e9 if context.previous_durations_ns else 0),
        log(sum(context.previous_output_tokens)),
    ]
    encoded = [0.0] * 32
    words = [f"model:{context.model}", f"role:{context.role}"]
    words += re.findall(r"\w+", context.text.lower())
    for word in words:
        digest = hashlib.sha256(word.encode()).digest()
        encoded[digest[0] % len(encoded)] += 1.0 if digest[1] % 2 else -1.0
    norm = max(1, math.sqrt(sum(v * v for v in encoded)))
    return numeric + [v / norm for v in encoded]


@dataclass(frozen=True)
class TrainingExample:
    workflow: str
    context: Context
    remaining_ns: int


@dataclass(frozen=True)
class ContextRegressor:
    weights: tuple[float, ...]
    training_workflows: tuple[str, ...]
    name: str = "hashed-context-log-duration-regression-v1"

    def __post_init__(self) -> None:
        if len(self.weights) != 40 or not all(math.isfinite(x) for x in self.weights):
            raise ValueError("invalid context regressor weights")

    def __call__(self, context: Context) -> int:
        prediction = sum(w * x for w, x in zip(self.weights, features(context), strict=True))
        return max(1, round(math.exp(min(20.0, max(-20.0, prediction))) * 1e9))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def fit(cls, examples: tuple[TrainingExample, ...], *, epochs: int = 300) -> ContextRegressor:
        if not examples or any(e.remaining_ns <= 0 for e in examples) or epochs <= 0:
            raise ValueError("positive duration labels and a nonempty training set are required")
        rows = [(features(e.context), math.log(e.remaining_ns / 1e9)) for e in examples]
        weights = [0.0] * 40
        weights[0] = sum(y for _, y in rows) / len(rows)
        for _ in range(epochs):
            gradient = [0.0] * len(weights)
            for vector, label in rows:
                residual = sum(w * x for w, x in zip(weights, vector, strict=True)) - label
                for j, value in enumerate(vector):
                    gradient[j] += residual * value / len(rows)
            for j in range(len(weights)):
                weights[j] -= 0.1 * (gradient[j] + (0.001 * weights[j] if j else 0))
        return cls(tuple(weights), tuple(sorted({e.workflow for e in examples})))
