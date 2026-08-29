from __future__ import annotations

import pytest

from moonkvsim.integration.vllm.connector import (
    ConnectorCompletion,
    ConnectorMetadata,
    ConnectorRequest,
    ConnectorScheduledRequest,
    ConnectorScheduleStep,
    StoreRole,
    TensorFreeStoreConnectorScheduler,
    TensorFreeStoreConnectorWorker,
)


def _request(request_id: str = "request") -> ConnectorRequest:
    return ConnectorRequest(
        request_id=request_id,
        token_ids=tuple(range(1, 9)),
        block_hashes=("hash-1", "hash-2"),
    )


def _scheduled(request: ConnectorRequest) -> ConnectorScheduledRequest:
    return ConnectorScheduledRequest(
        request=request,
        block_ids=((1, 2),),
        num_computed_tokens=4,
        num_scheduled_tokens=4,
    )


def _empty_metadata() -> ConnectorMetadata:
    return ConnectorMetadata((), frozenset(), frozenset())


def test_store_load_metadata_and_receive_completion_promote_only_next_pass() -> None:
    request = _request("load")
    scheduler = TensorFreeStoreConnectorScheduler(
        block_size_tokens=4,
        role=StoreRole.BOTH,
        lookup=lambda _tokens, _hashes: 8,
    )

    assert scheduler.get_num_new_matched_tokens(request, 0) == (4, True)
    assert scheduler.get_num_new_matched_tokens(request, 0) == (4, True)
    scheduler.update_state_after_alloc(request, ((1, 2),), 4)
    metadata = scheduler.build_connector_meta(
        ConnectorScheduleStep(new_requests=(_scheduled(request),))
    )

    [row] = metadata.requests
    assert row.load_spec is not None and row.load_spec.can_load
    assert not row.can_save
    worker = TensorFreeStoreConnectorWorker(role=StoreRole.BOTH)
    worker.bind_connector_metadata(metadata)
    assert worker.get_finished(frozenset()) == ConnectorCompletion()
    worker.clear_connector_metadata()
    worker.complete_transfers(receiving=frozenset({request.request_id}))
    worker.bind_connector_metadata(_empty_metadata())
    completion = worker.get_finished(frozenset())
    worker.clear_connector_metadata()

    assert completion.finished_receiving == {request.request_id}
    assert scheduler.begin_scheduler_pass() == frozenset()
    scheduler.apply_worker_completion(completion)
    assert scheduler.begin_scheduler_pass() == {request.request_id}
    assert scheduler.begin_scheduler_pass() == frozenset()


def test_store_save_completion_is_the_only_delayed_free_gate() -> None:
    request = _request("save")
    scheduler = TensorFreeStoreConnectorScheduler(
        block_size_tokens=4,
        role=StoreRole.BOTH,
        lookup=lambda _tokens, _hashes: 0,
    )
    assert scheduler.get_num_new_matched_tokens(request, 0) == (0, False)
    scheduler.update_state_after_alloc(request, ((1, 2),), 0)
    scheduled = ConnectorScheduledRequest(
        request=request,
        block_ids=((1, 2),),
        num_computed_tokens=0,
        num_scheduled_tokens=8,
    )
    metadata = scheduler.build_connector_meta(ConnectorScheduleStep(new_requests=(scheduled,)))
    [row] = metadata.requests
    assert row.can_save and row.load_spec is None
    assert scheduler.request_finished(request.request_id, ((1, 2),))
    assert scheduler.delayed_free_request_ids == {request.request_id}

    worker = TensorFreeStoreConnectorWorker(role=StoreRole.BOTH)
    worker.bind_connector_metadata(metadata)
    assert worker.get_finished(frozenset({request.request_id})) == ConnectorCompletion()
    worker.clear_connector_metadata()
    worker.complete_transfers(sending=frozenset({request.request_id}))
    worker.bind_connector_metadata(_empty_metadata())
    completion = worker.get_finished(frozenset({request.request_id}))
    worker.clear_connector_metadata()

    assert completion.finished_sending == {request.request_id}
    assert scheduler.apply_worker_completion(completion) == {request.request_id}
    assert scheduler.delayed_free_request_ids == frozenset()


def test_connector_fails_closed_on_metadata_and_completion_lifecycle_drift() -> None:
    scheduler = TensorFreeStoreConnectorScheduler(
        block_size_tokens=4,
        role=StoreRole.CONSUMER,
        lookup=lambda _tokens, _hashes: 4,
    )
    request = _request("strict")
    assert scheduler.get_num_new_matched_tokens(request, 0) == (4, True)
    with pytest.raises(ValueError, match="differs from Store lookup"):
        scheduler.update_state_after_alloc(request, ((1, 2),), 8)
    with pytest.raises(ValueError, match="remote waiter"):
        scheduler.apply_worker_completion(
            ConnectorCompletion(finished_receiving=frozenset({"unknown"}))
        )

    worker = TensorFreeStoreConnectorWorker(role=StoreRole.CONSUMER)
    worker.bind_connector_metadata(_empty_metadata())
    with pytest.raises(ValueError, match="already bound"):
        worker.bind_connector_metadata(_empty_metadata())
    worker.clear_connector_metadata()
    with pytest.raises(ValueError, match="never issued"):
        worker.complete_transfers(receiving=frozenset({"unknown"}))
