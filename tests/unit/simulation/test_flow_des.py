import pytest

from moonkvsim.simulation.event import EventHandle, EventKind
from moonkvsim.simulation.flow_des import FlowDESController
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.network import ActiveFlow, FlowContentionModel
from moonkvsim.simulation.resource import RateResource


def flow(flow_id: str, size: int = 10) -> ActiveFlow:
    return ActiveFlow(
        flow_id=flow_id,
        transfer_id=f"transfer-{flow_id}",
        slice_id=f"slice-{flow_id}",
        cause="BASELINE_STORE",
        path_resource_ids=("link",),
        payload_bytes=size,
        remaining_bytes=float(size),
    )


def controller() -> tuple[GlobalDES, FlowContentionModel, FlowDESController]:
    des = GlobalDES()
    model = FlowContentionModel(
        [RateResource(resource_id="link", capacity_bytes_per_second=1_000_000_000)]
    )
    return des, model, FlowDESController(des=des, model=model)


def test_integer_nanosecond_rounding_completes_without_overshoot() -> None:
    des, model, control = controller()
    completed: list[str] = []

    def record(item: ActiveFlow, _des: GlobalDES) -> None:
        completed.append(item.flow_id)

    control.start_flow(flow("a", size=11), on_complete=record)

    des.run()

    assert completed == ["a"]
    assert des.now_ns == 11
    assert model.flows == {}


def test_new_contender_cancels_stale_event_and_recomputes_completion() -> None:
    des, _model, control = controller()
    completed: list[tuple[str, int]] = []

    def callback(item: ActiveFlow, state: GlobalDES) -> None:
        completed.append((item.flow_id, state.now_ns))

    control.start_flow(flow("a", size=10), on_complete=callback)

    def add_second(_event: object, _des: GlobalDES) -> None:
        control.start_flow(flow("b", size=5), on_complete=callback)

    des.register_handler(EventKind.REQUEST_ARRIVAL, add_second)
    des.schedule_at(2, EventKind.REQUEST_ARRIVAL, event_id="add-b")
    des.run()

    assert completed == [("b", 12), ("a", 15)]
    assert b'"reason":"FLOW_RATE_RECOMPUTED"' in des.journal.to_jsonl_bytes()


def test_failure_priority_cancels_same_timestamp_completion() -> None:
    des, model, control = controller()
    completed: list[str] = []
    canceled: list[float] = []

    def record(item: ActiveFlow, _des: GlobalDES) -> None:
        completed.append(item.flow_id)

    control.start_flow(flow("a", size=10), on_complete=record)

    def fail(_event: object, _des: GlobalDES) -> None:
        result = control.cancel_flow("a", reason="GPU_FAILURE")
        canceled.append(result.aborted_bytes)

    des.register_handler(EventKind.FAILURE_INJECT, fail)
    des.schedule_at(10, EventKind.FAILURE_INJECT, event_id="failure")
    des.run()

    assert completed == []
    assert canceled == [0.0]
    assert model.flows == {}


def test_failed_replacement_schedule_rolls_back_new_flow_and_preserves_old_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    des, model, control = controller()
    completed: list[tuple[str, int]] = []

    def callback(item: ActiveFlow, state: GlobalDES) -> None:
        completed.append((item.flow_id, state.now_ns))

    control.start_flow(flow("a", size=10), on_complete=callback)
    des.run(until_ns=2)
    previous_event = control._completion_event
    assert previous_event is not None
    previous_rates = model.rates()
    contender = flow("b", size=5)
    original_schedule_at = des.schedule_at

    def fail_schedule(*args: object, **kwargs: object) -> object:
        raise RuntimeError("injected replacement schedule failure")

    monkeypatch.setattr(des, "schedule_at", fail_schedule)
    with pytest.raises(RuntimeError, match="injected replacement"):
        control.start_flow(contender, on_complete=callback)

    assert set(model.flows) == {"a"}
    assert model.rates() == previous_rates
    assert control._completion_event == previous_event
    assert set(control._completion_handlers) == {"a"}
    assert contender.remaining_bytes == contender.payload_bytes
    assert contender.allocated_rate_bytes_per_second == 0.0
    assert des.pending_count == 1
    assert any(
        record.record_type == "FLOW_DES_START_ROLLED_BACK"
        and record.data["preserved_completion_event_id"] == previous_event.event_id
        for record in des.journal.records
    )

    monkeypatch.setattr(des, "schedule_at", original_schedule_at)
    des.run()
    assert completed == [("a", 10)]
    assert model.flows == {}


def test_failed_old_event_cancel_cancels_replacement_and_restores_start_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    des, model, control = controller()
    completed: list[str] = []
    control.start_flow(
        flow("a", size=10),
        on_complete=lambda item, _des: completed.append(item.flow_id),
    )
    previous_event = control._completion_event
    assert previous_event is not None
    previous_rates = model.rates()
    original_cancel = des.cancel

    def refuse_previous(handle: EventHandle, *, reason: str) -> bool:
        if handle == previous_event:
            return False
        return original_cancel(handle, reason=reason)

    monkeypatch.setattr(des, "cancel", refuse_previous)
    with pytest.raises(RuntimeError, match="could not be canceled"):
        control.start_flow(
            flow("b", size=5),
            on_complete=lambda item, _des: completed.append(item.flow_id),
        )

    assert set(model.flows) == {"a"}
    assert model.rates() == previous_rates
    assert control._completion_event == previous_event
    assert set(control._completion_handlers) == {"a"}
    assert des.pending_count == 1
    assert any(
        record.record_type == "EVENT_CANCELED"
        and record.data["reason"] == "FLOW_RESCHEDULE_ROLLBACK"
        for record in des.journal.records
    )

    monkeypatch.setattr(des, "cancel", original_cancel)
    des.run()
    assert completed == ["a"]
    assert model.flows == {}
