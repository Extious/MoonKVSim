"""Validated inputs for the current-design GlobalDES runtime (integer ns/bytes)."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Config:
    hosts: tuple[int, ...] = (0, 1, 2, 3)
    tp: int = 2
    layers: int = 32
    block_tokens: int = 64
    checkpoint_tokens: int = 256
    prefill_chunk_tokens: int = 256
    count_decay: float = 0.9
    topk_hysteresis: float = 0.1
    selector_metadata_bytes_per_block_per_layer_rank: int = 16
    count_bytes_per_block_per_layer_rank: int = 8
    kv_bytes_per_token_per_layer_rank: int = 2048
    hbm_bytes_per_rank: int = 2 * 1024**3  # after weights/fixed allocations
    dram_bytes_per_host: int = 4 * 1024**3
    hbm_cap_bytes: int = 256 * 1024**2
    initial_quota_bytes: int = 16 * 1024**2
    reserve_bytes: int = 64 * 1024**2
    depth: int = 4
    top_k: int = 4
    tolerance_ns: int = 0
    prefill_ns_per_token: int = 100_000
    decode_ns_per_token: int = 2_000_000
    h2d_bytes_per_second: float = 2e9
    network_bytes_per_second: float = 10e9
    dram_bytes_per_second: float = 40e9
    d2h_bytes_per_second: float = 12e9
    control_window_ns: int = 100_000_000
    prediction_latency_ns: int = 100_000
    prediction_ttl_ns: int = 120_000_000_000
    slack_guard_ns: int = 0
    additive_bytes: int = 16 * 1024**2
    decrease: float = 0.75
    stable_windows: int = 3
    failure_detection_ns: int = 1_000_000
    decode_batch_tokens: int = 32
    max_time_ns: int = 300_000_000_000
    attention: str = "dense"
    # Synthetic sparse selector is a mechanism fixture, never native model evidence.
    synthetic_selected_blocks: int = 4
    compute_dma_slowdown: float = 0.0

    def __post_init__(self) -> None:
        if len(self.hosts) < 2 or len(set(self.hosts)) < 2:
            raise ValueError("at least two independent host failure domains are required")
        positive = (
            "tp",
            "layers",
            "kv_bytes_per_token_per_layer_rank",
            "hbm_bytes_per_rank",
            "dram_bytes_per_host",
            "prefill_ns_per_token",
            "decode_ns_per_token",
            "control_window_ns",
            "prediction_ttl_ns",
            "stable_windows",
            "decode_batch_tokens",
            "max_time_ns",
            "synthetic_selected_blocks",
            "block_tokens",
            "checkpoint_tokens",
            "prefill_chunk_tokens",
        )
        for name in positive:
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "hbm_cap_bytes",
            "initial_quota_bytes",
            "reserve_bytes",
            "top_k",
            "depth",
            "tolerance_ns",
            "prediction_latency_ns",
            "slack_guard_ns",
            "additive_bytes",
            "failure_detection_ns",
            "selector_metadata_bytes_per_block_per_layer_rank",
            "count_bytes_per_block_per_layer_rank",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.checkpoint_tokens % self.block_tokens:
            raise ValueError("checkpoint_tokens must be a multiple of block_tokens")
        if not isfinite(self.count_decay) or not 0 < self.count_decay < 1:
            raise ValueError("count_decay must be in (0,1)")
        if not isfinite(self.topk_hysteresis) or self.topk_hysteresis < 0:
            raise ValueError("topk_hysteresis must be finite and nonnegative")
        if not isfinite(self.compute_dma_slowdown) or self.compute_dma_slowdown < 0:
            raise ValueError("compute_dma_slowdown must be finite and nonnegative")
        if self.depth > self.layers or self.initial_quota_bytes > self.hbm_cap_bytes:
            raise ValueError("invalid depth or initial quota")
        if not 0 < self.decrease < 1 or self.reserve_bytes >= self.hbm_bytes_per_rank:
            raise ValueError("invalid AIMD decrease or reserve")
        for name in (
            "h2d_bytes_per_second",
            "network_bytes_per_second",
            "dram_bytes_per_second",
            "d2h_bytes_per_second",
        ):
            if not isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.attention not in {"dense", "synthetic_sparse"}:
            raise ValueError("attention must be dense or explicitly synthetic_sparse")

    @property
    def block_bytes(self) -> int:
        return self.block_tokens * self.kv_bytes_per_token_per_layer_rank

    def prefix_bytes(self, tokens: int) -> int:
        return tokens * self.layers * self.kv_bytes_per_token_per_layer_rank

    def metadata_layer_bytes(self, tokens: int) -> int:
        """Checkpointed selector state and count arrays, per layer and TP rank."""
        blocks = (tokens + self.block_tokens - 1) // self.block_tokens
        return blocks * (
            self.selector_metadata_bytes_per_block_per_layer_rank
            + self.count_bytes_per_block_per_layer_rank
        )

    def checkpoint_bytes(self, tokens: int) -> int:
        return self.prefix_bytes(tokens) + self.layers * self.metadata_layer_bytes(tokens)


@dataclass(frozen=True)
class Invocation:
    prompt: tuple[int, ...]
    output: tuple[int, ...]
    model: str = "modeled-32-layer-tp2"
    layout: str = "bf16-kv"
    text: str = ""
    output_limit_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.prompt or not self.output:
            raise ValueError("invocations require nonempty prompt and output token IDs")
        if self.output_limit_tokens is not None and (
            type(self.output_limit_tokens) is not int or self.output_limit_tokens < len(self.output)
        ):
            raise ValueError("output_limit_tokens must cover the recorded output length")

    @property
    def tokens(self) -> tuple[int, ...]:
        return self.prompt + self.output


@dataclass(frozen=True)
class Agent:
    workflow: str
    name: str
    predecessors: tuple[str, ...]
    calls: tuple[Invocation, ...]
    prior_ns: int
    role: str = "worker"
    release_ns: int = 0

    @property
    def key(self) -> str:
        return f"{self.workflow}/{self.name}"

    def __post_init__(self) -> None:
        if not self.workflow or not self.name or "/" in self.workflow or "/" in self.name:
            raise ValueError("workflow and Agent names must be nonempty and slash-free")
        if not self.calls or self.prior_ns <= 0 or self.release_ns < 0:
            raise ValueError("invalid Agent calls, duration prior or release time")


@dataclass(frozen=True)
class Failure:
    agent: str
    invocation: int = 1  # zero based
    progress: float = 0.8  # logical total-token progress, identical across policies
    scope: str = "worker"  # one failed TP group, or all groups/DRAM on its host

    def __post_init__(self) -> None:
        if not 0 < self.progress < 1 or self.invocation < 0:
            raise ValueError("failure progress must be in (0,1)")
        if self.scope not in {"worker", "host"}:
            raise ValueError("failure scope must be worker or host")
