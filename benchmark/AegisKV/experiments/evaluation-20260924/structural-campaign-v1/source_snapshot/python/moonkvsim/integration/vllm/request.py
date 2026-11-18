"""Tensor-free mirror of pinned vLLM v1 request lifecycle semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum, auto


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    ABORT = "abort"
    ERROR = "error"
    REPETITION = "repetition"


class RequestStatus(IntEnum):
    """Order mirrors pinned `vllm/v1/request.py::RequestStatus`."""

    WAITING = auto()
    WAITING_FOR_STRUCTURED_OUTPUT_GRAMMAR = auto()
    WAITING_FOR_REMOTE_KVS = auto()
    WAITING_FOR_STREAMING_REQ = auto()
    RUNNING = auto()
    PREEMPTED = auto()
    FINISHED_STOPPED = auto()
    FINISHED_LENGTH_CAPPED = auto()
    FINISHED_ABORTED = auto()
    FINISHED_IGNORED = auto()
    FINISHED_ERROR = auto()
    FINISHED_REPETITION = auto()

    @property
    def finished(self) -> bool:
        return self > RequestStatus.PREEMPTED

    @property
    def finish_reason(self) -> FinishReason | None:
        return _FINISHED_REASON_MAP.get(self)


_FINISHED_REASON_MAP = {
    RequestStatus.FINISHED_STOPPED: FinishReason.STOP,
    RequestStatus.FINISHED_LENGTH_CAPPED: FinishReason.LENGTH,
    RequestStatus.FINISHED_ABORTED: FinishReason.ABORT,
    RequestStatus.FINISHED_IGNORED: FinishReason.LENGTH,
    RequestStatus.FINISHED_ERROR: FinishReason.ERROR,
    RequestStatus.WAITING_FOR_STREAMING_REQ: FinishReason.STOP,
    RequestStatus.FINISHED_REPETITION: FinishReason.REPETITION,
}


@dataclass(slots=True)
class Request:
    request_id: str
    prompt_tokens: int
    max_output_tokens: int
    arrival_ns: int
    priority: int = 0
    status: RequestStatus = RequestStatus.WAITING
    num_computed_tokens: int = 0
    num_output_tokens: int = 0
    num_preemptions: int = 0
    route_version: int = 0
    max_model_len_tokens: int = 131_072
    prompt_token_ids: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id must be non-empty")
        if self.prompt_tokens < 0 or self.max_output_tokens <= 0:
            raise ValueError("prompt_tokens must be non-negative and output reserve positive")
        if self.arrival_ns < 0 or self.route_version < 0:
            raise ValueError("arrival_ns and route_version must be non-negative")
        if self.prompt_tokens + self.max_output_tokens > self.max_model_len_tokens:
            raise ValueError(
                "request exceeds model length guard; truncation and padding are forbidden"
            )
        if self.prompt_token_ids is not None:
            if len(self.prompt_token_ids) != self.prompt_tokens:
                raise ValueError("prompt_token_ids length must equal prompt_tokens")
            if any(type(token_id) is not int or token_id < 0 for token_id in self.prompt_token_ids):
                raise ValueError("prompt_token_ids must contain non-negative integers")

    @property
    def num_tokens(self) -> int:
        return self.prompt_tokens + self.num_output_tokens

    @property
    def finished(self) -> bool:
        return self.status.finished

    def mark_running(self) -> None:
        if self.status not in {
            RequestStatus.WAITING,
            RequestStatus.WAITING_FOR_REMOTE_KVS,
            RequestStatus.PREEMPTED,
        }:
            raise ValueError(f"request cannot run from {self.status.name}")
        self.status = RequestStatus.RUNNING

    def wait_for_remote_kv(self) -> None:
        if self.status is not RequestStatus.WAITING:
            raise ValueError("remote KV wait starts only from WAITING")
        self.status = RequestStatus.WAITING_FOR_REMOTE_KVS

    def resume_after_remote_kv(self) -> None:
        """Return a completed remote-KV wait to ordinary waiting admission.

        The scheduler owns the corresponding restored-token accounting.  This
        transition deliberately does not mark the request RUNNING: the pinned
        scheduler promotes a completed connector wait first, then applies the
        ordinary running-slot and KV-capacity admission checks.
        """

        if self.status is not RequestStatus.WAITING_FOR_REMOTE_KVS:
            raise ValueError("remote KV completion requires WAITING_FOR_REMOTE_KVS")
        self.status = RequestStatus.PREEMPTED if self.num_preemptions else RequestStatus.WAITING

    def preempt(self) -> None:
        if self.status is not RequestStatus.RUNNING:
            raise ValueError("only a running request may be preempted")
        self.status = RequestStatus.PREEMPTED
        self.num_preemptions += 1

    def record_computed_tokens(self, count: int) -> None:
        if self.status is not RequestStatus.RUNNING or count <= 0:
            raise ValueError("computed tokens require a running request and positive count")
        if self.num_computed_tokens + count > self.num_tokens:
            raise ValueError("computed tokens cannot exceed materialized request tokens")
        self.num_computed_tokens += count

    def append_output_tokens(self, count: int) -> None:
        if self.status is not RequestStatus.RUNNING or count <= 0:
            raise ValueError("output tokens require a running request and positive count")
        if self.num_output_tokens + count > self.max_output_tokens:
            raise ValueError("output tokens exceed the reserved maximum")
        self.num_output_tokens += count

    def finish(self, status: RequestStatus) -> None:
        if not status.finished:
            raise ValueError("finish requires a terminal request status")
        if self.finished:
            raise ValueError("request is already finished")
        self.status = status
