"""Constructed interventions for the current AegisKV simulation runtime.

These are synthetic token workloads, not recorded Agent/model executions. The
known four-Agent DAG is root -> {left, right} -> join; only a submitted call is
visible to the runtime predictor. Priors are fixed role parameters and never
computed from the generated future calls or the runtime's service profile.
"""

from __future__ import annotations

import random
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from math import ceil, isfinite
from typing import Any

from .current.model import Agent, Config, Failure, Invocation

SCENARIO_NAMES = (
    "forkjoin_skew",
    "forkjoin_balanced",
    "history_reuse",
    "long_decode_drift",
    "shared_host",
)
WORKFLOW_SCALES = (8, 32, 128)
ROLE_PRIORS_NS = {
    "planner": 2_000_000_000,
    "analyst": 60_000_000_000,
    "reviewer": 20_000_000_000,
    "writer": 4_000_000_000,
}


@dataclass(frozen=True)
class SyntheticPhaseDemand:
    """Causal rotating hot banks; no native-selector or measured-demand claim.

    A fixed prefix bank changes every ``phase_tokens`` query positions. The
    current block is also selected. No future token content, call count, failure
    point or desired HBM placement participates in selection. Use explicitly
    with ``Config(attention="synthetic_sparse")``.
    """

    hot_blocks: int = 4
    phase_tokens: int = 1024
    bank_blocks: int = 16
    banks: int = 2
    name: str = "constructed-causal-phase-demand-v1"

    def __post_init__(self) -> None:
        for field in ("hot_blocks", "phase_tokens", "bank_blocks", "banks"):
            value = getattr(self, field)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field} must be a positive integer")

    def __call__(
        self, config: Config, invocation: Invocation, layer: int, query: int, history_blocks: int
    ) -> tuple[int, ...]:
        del invocation  # In particular, do not inspect its future output tokens.
        if config.attention != "synthetic_sparse":
            raise ValueError("constructed phase demand requires attention='synthetic_sparse'")
        if min(layer, query, history_blocks) < 0:
            raise ValueError("layer, query and history_blocks must be nonnegative")
        visible = min(history_blocks, query // config.block_tokens + 1)
        if not visible:
            return ()
        width = min(self.bank_blocks, max(1, visible // self.banks))
        phase = query // self.phase_tokens % self.banks
        start = min(phase * width, visible - 1)
        width = min(width, visible - start)
        chosen = {
            start + (layer * self.hot_blocks + offset) % width
            for offset in range(min(self.hot_blocks, width))
        }
        chosen.add(visible - 1)
        return tuple(sorted(chosen))


@dataclass(frozen=True)
class EvaluationScenario:
    agents: tuple[Agent, ...]
    failures: dict[str, Failure]
    metadata: dict[str, Any]
    demand_provider: SyntheticPhaseDemand | None = None

    def validate_config(self, config: Config) -> None:
        """Reject a topology/selector that would defeat the declared intervention."""
        if self.metadata["scenario"] == "shared_host" and len(set(config.hosts)) == len(
            config.hosts
        ):
            raise ValueError("shared_host requires multiple workers on at least one host")
        if self.demand_provider and config.attention != "synthetic_sparse":
            raise ValueError("long_decode_drift requires attention='synthetic_sparse'")
        if (
            self.demand_provider
            and config.synthetic_selected_blocks != self.demand_provider.hot_blocks
        ):
            raise ValueError("synthetic_selected_blocks must match the constructed hot-bank width")


def _find_agent(agents: Iterable[Agent], key: str) -> Agent:
    found = [agent for agent in agents if agent.key == key]
    if len(found) != 1:
        raise ValueError(f"failure target must identify exactly one Agent: {key}")
    return found[0]


def _reusable_history(agent: Agent, invocation: int) -> int:
    if invocation == 0:
        return 0
    old, new = agent.calls[invocation - 1], agent.calls[invocation]
    if (old.model, old.layout) != (new.model, new.layout):
        return 0
    # The current runtime reuses a retained complete previous history, rather
    # than an arbitrary common substring. Actual eviction/routing may reuse less.
    previous = old.tokens
    return len(previous) if new.prompt[: len(previous)] == previous else 0


def describe_failure(agents: Iterable[Agent], failure: Failure) -> dict[str, Any]:
    """Resolve the actual phase of a concrete runtime Failure, including rounding.

    A point inside a potentially reusable full history is rejected: otherwise a
    cache hit could skip it, creating policy-dependent fault eligibility.
    """
    agent = _find_agent(agents, failure.agent)
    if failure.invocation >= len(agent.calls):
        raise ValueError("failure invocation is absent from the target Agent")
    if not isfinite(failure.progress):
        raise ValueError("failure progress must be finite")
    call = agent.calls[failure.invocation]
    prompt, total = len(call.prompt), len(call.tokens)
    trigger = ceil(total * failure.progress)
    reusable = _reusable_history(agent, failure.invocation)
    if not reusable < trigger < total:
        raise ValueError("failure must follow reusable history and precede invocation completion")
    phase = "prefill" if trigger < prompt else "decode" if trigger > prompt else "boundary"
    return {
        **asdict(failure),
        "phase": phase,
        "logical_trigger_tokens": trigger,
        "prompt_tokens": prompt,
        "output_tokens": len(call.output),
        "total_tokens": total,
        "potentially_reusable_history_tokens": reusable,
        "accepted_output_tokens_at_trigger": max(0, trigger - prompt),
        "identity_and_total_progress_fixed_across_policies": True,
    }


def resolve_stage_failure(
    agents: Iterable[Agent],
    *,
    agent: str,
    invocation: int,
    phase: str,
    phase_progress: float = 0.8,
    scope: str = "worker",
) -> Failure:
    """Convert an interior prefill/decode location into total-token progress.

    For a follow-up call, the prefill interval starts after its compatible full
    history. ``phase_progress`` is a construction parameter; the returned
    Failure.progress (not that parameter) is passed unchanged to every policy.
    """
    spec = _find_agent(agents, agent)
    if type(invocation) is not int or not 0 <= invocation < len(spec.calls):
        raise ValueError("failure invocation is absent from the target Agent")
    if phase not in {"prefill", "decode"}:
        raise ValueError("phase must be prefill or decode")
    if not isfinite(phase_progress) or not 0 < phase_progress < 1:
        raise ValueError("phase_progress must be finite and in (0,1)")
    call = spec.calls[invocation]
    start, end = (
        (_reusable_history(spec, invocation), len(call.prompt))
        if phase == "prefill"
        else (len(call.prompt), len(call.tokens))
    )
    if end - start < 2:
        raise ValueError("requested phase has no interior fault point after reusable history")
    trigger = min(end - 1, start + max(1, ceil((end - start) * phase_progress)))
    # Midpoint in ceil's interval avoids e.g. ceil((q/n)*n) becoming q+1.
    result = Failure(agent, invocation, (trigger - 0.5) / len(call.tokens), scope)
    if describe_failure((spec,), result)["phase"] != phase:
        raise ValueError("rounded failure point does not belong to the requested phase")
    return result


def build_evaluation_scenario(
    name: str,
    *,
    model: str,
    workflows: int = 8,
    seed: int = 7,
    layout: str = "bf16-kv",
    release_interval_ns: int | None = None,
    max_context_tokens: int = 40_960,
    vocabulary_size: int = 32_000,
) -> EvaluationScenario:
    """Build one immutable Agent sequence plus JSON-serializable provenance.

    Model/layout labels are caller supplied; integer tokens are generated within
    the supplied vocabulary bound. They are not meaningful text or evidence of
    actual generation quality. Only 8/32/128 whole-workflow scales are accepted.
    """
    if name not in SCENARIO_NAMES:
        raise ValueError(f"unknown constructed scenario: {name}")
    if type(workflows) is not int or workflows not in WORKFLOW_SCALES:
        raise ValueError("workflows must be one of 8, 32, 128")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if not isinstance(model, str) or not model or not isinstance(layout, str) or not layout:
        raise ValueError("model and layout must be nonempty strings")
    if type(max_context_tokens) is not int or not 0 < max_context_tokens <= 40_960:
        raise ValueError("max_context_tokens must be a positive integer no larger than 40960")
    if type(vocabulary_size) is not int or vocabulary_size <= 100:
        raise ValueError("vocabulary_size must be an integer greater than 100")
    if release_interval_ns is None:
        release_interval_ns = 0 if name == "shared_host" else 250_000_000
    if type(release_interval_ns) is not int or release_interval_ns < 0:
        raise ValueError("release_interval_ns must be a nonnegative integer")

    # Each tuple is (initial prompt length, output lengths). Follow-ups append
    # the full previous prompt+output and 512 new input tokens, never truncate.
    recipes = {
        "forkjoin_skew": ((4096, (2048, 4096)), (2048, (512, 1024))),
        "forkjoin_balanced": ((4096, (2048, 4096)), (4096, (2048, 4096))),
        "history_reuse": ((4096, (1024, 2048, 4096)), (4096, (1024, 2048, 4096))),
        "long_decode_drift": ((2048, (8192, 8192)), (2048, (4096, 4096))),
        "shared_host": ((2048, (8192, 8192)), (2048, (8192, 8192))),
    }
    rng = random.Random(seed)

    def tokens(count: int) -> tuple[int, ...]:
        return tuple(rng.randrange(100, vocabulary_size) for _ in range(count))

    def calls(prompt: int, outputs: tuple[int, ...], jitter: int) -> tuple[Invocation, ...]:
        history: tuple[int, ...] = ()
        result = []
        for ordinal, output in enumerate(outputs):
            source = history + tokens(512 if ordinal else prompt + jitter)
            call = Invocation(
                source, tokens(output + jitter), model, layout, "", output_limit_tokens=16_384
            )
            if len(call.tokens) > max_context_tokens:
                raise ValueError("constructed invocation exceeds max_context_tokens; no truncation")
            if len(call.prompt) + call.output_limit_tokens > max_context_tokens:
                raise ValueError("declared output capacity exceeds max_context_tokens")
            result.append(call)
            history = call.tokens
        return tuple(result)

    agents = []
    for index in range(workflows):
        workflow, release = f"wf{index:04d}", index * release_interval_ns
        # Shared workload-length perturbation preserves balanced branch work.
        # Seed controls content and explicit shape variation, not just labels.
        jitter = 64 * rng.randrange(3)
        left_recipe, right_recipe = recipes[name]
        right_role = "reviewer" if name in {"forkjoin_skew", "long_decode_drift"} else "analyst"
        rows = (
            ("root", (), "planner", (1024, (256,))),
            ("left", ("root",), "analyst", left_recipe),
            ("right", ("root",), right_role, right_recipe),
            ("join", ("left", "right"), "writer", (2048, (256,))),
        )
        for agent_name, parents, role, recipe in rows:
            agents.append(
                Agent(
                    workflow,
                    agent_name,
                    parents,
                    calls(*recipe, jitter),
                    ROLE_PRIORS_NS[role],
                    role,
                    release,
                )
            )
    agent_tuple = tuple(agents)
    scope = "host" if name == "shared_host" else "worker"
    failures = {
        f"{branch}.{phase}": resolve_stage_failure(
            agent_tuple,
            agent=f"wf0000/{branch}",
            invocation=1,
            phase=phase,
            scope=scope,
        )
        for branch in ("left", "right")
        for phase in ("prefill", "decode")
    }
    provider = SyntheticPhaseDemand() if name == "long_decode_drift" else None
    metadata = {
        "schema": "aegiskv.constructed_evaluation_scenario.v1",
        "evidence_class": "constructed_intervention",
        "scenario": name,
        "seed": seed,
        "model": model,
        "layout": layout,
        "workflow_count": workflows,
        "agent_count": len(agents),
        "invocation_count": sum(len(agent.calls) for agent in agents),
        "maximum_context_tokens": max(len(call.tokens) for agent in agents for call in agent.calls),
        "context_limit_tokens": max_context_tokens,
        "known_agent_dag": {
            "root": [],
            "left": ["root"],
            "right": ["root"],
            "join": ["left", "right"],
        },
        "faults": {key: describe_failure(agent_tuple, fault) for key, fault in failures.items()},
        "artificial_parameters": {
            "branch_recipes": recipes[name],
            "root_recipe": (1024, (256,)),
            "join_recipe": (2048, (256,)),
            "followup_new_input_tokens": 512,
            "per_workflow_length_jitter_tokens": [0, 64, 128],
            "declared_output_limit_tokens": 16_384,
            "reservation": "submitted prompt plus fixed output cap; no future-length oracle",
            "role_priors_ns": dict(ROLE_PRIORS_NS),
            "prior_source": "fixed uncalibrated role constants; not generated remaining work",
            "release_interval_ns": release_interval_ns,
            "fault_phase_progress": 0.8,
            "vocabulary_size": vocabulary_size,
            "phase_demand": asdict(provider) if provider else None,
        },
        "required_config": {"attention": "synthetic_sparse"} if provider else {},
        "recommended_hosts": [0, 0, 1, 1] if name == "shared_host" else [0, 1, 2, 3],
        "shared_host_covictims": (
            "simultaneous arrivals provide contention; actual covictims must be read from runtime"
            if name == "shared_host"
            else "not forced"
        ),
        "observed_trace": False,
        "native_model_demand": False,
        "workflow_repetitions": 1,
        "tool_delays": "none",
        "history": "exact previous prompt+output followed by new input; same model/layout",
        "criticality": "branch work/prior intervention; actual critical path depends on runtime",
        "prediction_features": "no task semantics, future call counts or future output features",
    }
    return EvaluationScenario(agent_tuple, failures, metadata, provider)
