import json

from moonkvsim.common.hash import sha256_json
from moonkvsim.simulation.event import EventKind
from moonkvsim.simulation.global_des import GlobalDES


def test_stable_order_for_equal_timestamp_and_priority() -> None:
    des = GlobalDES()
    seen: list[str] = []

    def record(event: object, _des: GlobalDES) -> None:
        seen.append(event.event_id)  # type: ignore[attr-defined]

    des.register_handler(EventKind.REQUEST_ARRIVAL, record)
    des.schedule_at(10, EventKind.REQUEST_ARRIVAL, event_id="first")
    des.schedule_at(10, EventKind.REQUEST_ARRIVAL, event_id="second")

    assert des.run() == 2
    assert seen == ["first", "second"]
    assert des.now_ns == 10


def test_failure_precedes_completion_at_same_timestamp() -> None:
    des = GlobalDES()
    seen: list[EventKind] = []

    def record(event: object, _des: GlobalDES) -> None:
        seen.append(event.kind)  # type: ignore[attr-defined]

    des.register_handler(EventKind.TRANSFER_COMPLETE, record)
    des.register_handler(EventKind.FAILURE_INJECT, record)
    des.schedule_at(10, EventKind.TRANSFER_COMPLETE)
    des.schedule_at(10, EventKind.FAILURE_INJECT)

    des.run()
    assert seen == [EventKind.FAILURE_INJECT, EventKind.TRANSFER_COMPLETE]


def test_cancel_prevents_execution() -> None:
    des = GlobalDES()
    seen: list[str] = []
    des.register_handler(EventKind.TRANSFER_COMPLETE, lambda event, _: seen.append(event.event_id))
    handle = des.schedule_after(5, EventKind.TRANSFER_COMPLETE)

    assert des.cancel(handle, reason="GPU_FAILURE")
    assert not des.cancel(handle, reason="duplicate")
    assert des.run() == 0
    assert seen == []


def test_cannot_schedule_in_the_past() -> None:
    des = GlobalDES()
    des.run(until_ns=10)

    try:
        des.schedule_at(9, EventKind.REQUEST_ARRIVAL)
    except ValueError as error:
        assert "past" in str(error)
    else:
        raise AssertionError("scheduling in the past must fail")


def test_same_inputs_produce_byte_identical_journal() -> None:
    def run_once() -> bytes:
        des = GlobalDES()
        des.schedule_at(3, EventKind.REQUEST_ARRIVAL, payload={"request_id": "r0"})
        des.schedule_at(4, EventKind.REQUEST_COMPLETE, payload={"request_id": "r0"})
        des.run()
        return des.journal.to_jsonl_bytes()

    assert run_once() == run_once()


def test_payload_is_json_validated_and_detached_from_caller() -> None:
    des = GlobalDES()
    payload = {"nested": {"value": 1}}
    des.schedule_at(1, EventKind.REQUEST_ARRIVAL, payload=payload)
    payload["nested"]["value"] = 2

    assert b'"value":1' in des.journal.to_jsonl_bytes()

    try:
        des.schedule_at(2, EventKind.REQUEST_ARRIVAL, payload={"bad": object()})
    except TypeError:
        pass
    else:
        raise AssertionError("non-JSON event payload must fail at scheduling time")


def test_execution_record_links_to_single_canonical_scheduled_payload() -> None:
    des = GlobalDES()
    payload = {"request_id": "large", "opaque": "x" * 100_000}
    des.schedule_at(1, EventKind.REQUEST_ARRIVAL, payload=payload)

    des.run()

    scheduled = next(
        record for record in des.journal.records if record.record_type == "EVENT_SCHEDULED"
    )
    executing = next(
        record for record in des.journal.records if record.record_type == "EVENT_EXECUTING"
    )
    assert scheduled.data["payload"] == payload
    assert "payload" not in executing.data
    assert executing.data["payload_sha256"] == sha256_json(payload)
    assert executing.data["event_id"] == scheduled.data["event_id"]
    compact_bytes = json.dumps(
        executing.data,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert len(compact_bytes) < 512


def test_invariant_runs_after_every_executed_event() -> None:
    des = GlobalDES()
    checked_at: list[int] = []
    des.register_invariant("clock_non_negative", lambda state: checked_at.append(state.now_ns))
    first = des.schedule_at(2, EventKind.REQUEST_ARRIVAL)
    des.schedule_at(5, EventKind.REQUEST_COMPLETE)

    des.run()

    assert checked_at == [2, 5]
    assert not des.cancel(first, reason="cannot cancel executed event")
