"""Explicitly constructed fixed Agent DAGs; never labeled recorded/native traces."""

from __future__ import annotations

import random

from .model import Agent, Invocation


def mechanism_workload(seed: int = 7, workflows: int = 3) -> tuple[Agent, ...]:
    rng = random.Random(seed)

    def tokens(count: int) -> tuple[int, ...]:
        return tuple(rng.randrange(100, 32_000) for _ in range(count))

    def calls(prompt: int, output: int, second: int = 0) -> tuple[Invocation, ...]:
        # Work units vary across seeds; repetitions are independent constructed
        # workloads, not cosmetic token-ID changes or replicas of one DAG.
        prompt += 256 * rng.randrange(3)
        output += 128 * rng.randrange(3)
        if second:
            second += 128 * rng.randrange(3)
        first = Invocation(tokens(prompt), tokens(output), text="Research and summarize evidence")
        if not second:
            return (first,)
        return (
            first,
            Invocation(
                first.tokens + tokens(512),
                tokens(second),
                text="Extend the previous analysis and verify the result",
            ),
        )

    agents = []
    for index in range(workflows):
        workflow = f"wf{index:02}"
        release = index * 200_000_000
        agents.extend(
            [
                Agent(workflow, "root", (), calls(1024, 256), 1_000_000_000, "planner", release),
                Agent(
                    workflow,
                    "slow",
                    ("root",),
                    calls(4096, 1024, 1536),
                    8_000_000_000,
                    "researcher",
                    release,
                ),
                Agent(
                    workflow,
                    "fast",
                    ("root",),
                    calls(2048, 512, 768),
                    4_000_000_000,
                    "researcher",
                    release,
                ),
                Agent(
                    workflow,
                    "join",
                    ("slow", "fast"),
                    calls(2048, 512),
                    2_000_000_000,
                    "writer",
                    release,
                ),
            ]
        )
    return tuple(agents)
