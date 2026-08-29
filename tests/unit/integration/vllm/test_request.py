import pytest

from moonkvsim.integration.vllm.request import FinishReason, Request, RequestStatus


def request() -> Request:
    return Request(
        request_id="request-0",
        prompt_tokens=128,
        max_output_tokens=8,
        arrival_ns=10,
    )


def test_status_order_and_finish_reason_match_pinned_vllm() -> None:
    assert RequestStatus.PREEMPTED < RequestStatus.FINISHED_STOPPED
    assert RequestStatus.WAITING_FOR_STREAMING_REQ.finished is False
    assert RequestStatus.WAITING_FOR_STREAMING_REQ.finish_reason is FinishReason.STOP
    assert RequestStatus.FINISHED_IGNORED.finish_reason is FinishReason.LENGTH


def test_wait_run_preempt_resume_finish_lifecycle() -> None:
    item = request()
    item.wait_for_remote_kv()
    item.mark_running()
    item.record_computed_tokens(64)
    item.preempt()
    item.mark_running()
    item.record_computed_tokens(64)
    item.append_output_tokens(2)
    item.record_computed_tokens(2)
    item.finish(RequestStatus.FINISHED_STOPPED)

    assert item.num_preemptions == 1
    assert item.num_tokens == 130
    assert item.num_computed_tokens == 130
    assert item.finished
    assert item.status.finish_reason is FinishReason.STOP


def test_131072_guard_rejects_output_overflow_without_truncation() -> None:
    with pytest.raises(ValueError, match="model length guard"):
        Request(
            request_id="too-long",
            prompt_tokens=131_000,
            max_output_tokens=128,
            arrival_ns=0,
        )


def test_invalid_state_transition_fails_closed() -> None:
    item = request()
    with pytest.raises(ValueError, match="running request"):
        item.append_output_tokens(1)
