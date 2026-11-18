"""Submission-time predictions and guarded CPM on an Agent-task DAG.

The predictor only receives observable history. It cannot inspect future calls,
failure positions, actual remaining work, or simulated completion events.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

from .model import Agent, Config


@dataclass(frozen=True)
class Context:
    model: str
    role: str
    text: str
    prompt_tokens: int
    completed_calls: int
    previous_durations_ns: tuple[int, ...]
    previous_output_tokens: tuple[int, ...]
    elapsed_ns: int
    prior_ns: int


Predictor = Callable[[Context], int | None]


def prior_predictor(context: Context) -> int:
    """Explicit conservative baseline; this is not a trained context regressor."""
    return max(1, context.prior_ns - context.elapsed_ns)


@dataclass
class Estimate:
    version: int = -1
    submitted_ns: int = 0
    remaining_ns: int | None = None
    started: bool = False
    finished: bool = False


class Tracker:
    def __init__(self, agents: tuple[Agent, ...], config: Config):
        self.config = config
        self.agents = {a.key: a for a in agents}
        if len(self.agents) != len(agents):
            raise ValueError("duplicate Agent identity")
        self.states = {a.key: Estimate() for a in agents}
        self.parents = {a.key: tuple(f"{a.workflow}/{p}" for p in a.predecessors) for a in agents}
        self.children: dict[str, list[str]] = {k: [] for k in self.agents}
        for key, parents in self.parents.items():
            if len(set(parents)) != len(parents):
                raise ValueError("duplicate DAG edge")
            for parent in parents:
                if parent not in self.agents:
                    raise ValueError(f"missing Agent dependency {parent}")
                self.children[parent].append(key)
        indegree = {k: len(p) for k, p in self.parents.items()}
        ready = deque(sorted(k for k, n in indegree.items() if n == 0))
        self.order: list[str] = []
        while ready:
            key = ready.popleft()
            self.order.append(key)
            for child in sorted(self.children[key]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if len(self.order) != len(agents):
            raise ValueError("Agent DAG has a cycle")
        self.fallback_workflows: set[str] = set()

    def submit(self, key: str, version: int, now: int) -> None:
        state = self.states[key]
        if state.finished or version <= state.version:
            raise ValueError("out-of-order invocation submission")
        if not state.started:
            state.remaining_ns = self.agents[key].prior_ns
            state.submitted_ns = now
        state.started = True
        state.version = version

    def publish(self, key: str, version: int, submitted: int, remaining: int | None) -> bool:
        state = self.states[key]
        if state.finished or version != state.version:
            return False  # an old asynchronous response cannot overwrite a newer call
        state.remaining_ns = remaining
        state.submitted_ns = submitted  # prediction timestamp, never response timestamp
        return True

    def slack(self, now: int, *, durations: dict[str, int] | None = None) -> dict[str, int]:
        result = dict.fromkeys(self.agents, 0)
        self.fallback_workflows.clear()
        workflows: dict[str, list[str]] = {}
        for key in self.order:
            if not self.states[key].finished:
                workflows.setdefault(self.agents[key].workflow, []).append(key)
        for workflow, keys in workflows.items():
            duration: dict[str, int] = {}
            for key in keys:
                state = self.states[key]
                if durations is None:
                    value = state.remaining_ns if state.started else self.agents[key].prior_ns
                else:
                    if key not in durations:
                        raise KeyError(f"oracle duration missing for {key}")
                    value = durations[key]
                age = now - state.submitted_ns if state.started else 0
                if (
                    value is None
                    or not isfinite(value)
                    or age < 0
                    or age > self.config.prediction_ttl_ns
                    or value - age <= 0
                ):
                    break
                duration[key] = int(value) - age
            if len(duration) != len(keys):
                self.fallback_workflows.add(workflow)
                continue  # any invalid input zeros the entire residual workflow
            earliest: dict[str, int] = {}
            for key in keys:
                earliest[key] = duration[key] + max(
                    (earliest[p] for p in self.parents[key] if p in duration),
                    default=0,
                )
            end = max(earliest.values())
            latest: dict[str, int] = {}
            for key in reversed(keys):
                latest[key] = min(
                    [end] + [latest[c] - duration[c] for c in self.children[key] if c in duration]
                )
                result[key] = max(0, latest[key] - earliest[key] - self.config.slack_guard_ns)
        return result
