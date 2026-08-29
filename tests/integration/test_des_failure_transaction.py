from moonkvsim.simulation.event import EventKind
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.network import ActiveFlow, FlowContentionModel
from moonkvsim.simulation.resource import ConcurrencyResource, RateResource
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction


def test_failure_cancels_transfer_and_releases_pending_reservation() -> None:
    des = GlobalDES()
    ledger = CapacityLedger(
        resource_id="store-0.segment-0",
        resource_kind=CapacityResourceKind.STORE_DRAM,
        capacity_bytes=100,
    )
    ledgers = {ledger.resource_id: ledger}
    ResourceTransaction(
        event_id="reserve-destination",
        timestamp_ns=0,
        cause="MOONCAKE_PUT",
        allocation_deltas=[
            AllocationDelta(
                resource_id=ledger.resource_id,
                account_from="FREE",
                account_to="PENDING_REPLICA",
                delta_bytes=40,
                allocation_id="alloc-0",
                transfer_id="transfer-0",
            )
        ],
    ).commit(ledgers, journal=des.journal)

    copy_engine = ConcurrencyResource(resource_id="gpu-0.copy", lanes=1)
    copy_engine.reserve(
        ready_ns=0,
        duration_ns=10,
        reservation_id="copy-0",
        cause="MOONCAKE_PUT",
    )
    flows = FlowContentionModel([RateResource("pcie-0", 1_000_000_000.0)])
    flows.add_flow(
        ActiveFlow(
            flow_id="flow-0",
            transfer_id="transfer-0",
            slice_id="slice-0",
            cause="MOONCAKE_PUT",
            path_resource_ids=("pcie-0",),
            payload_bytes=40,
            remaining_bytes=40.0,
        ),
        now_ns=0,
    )

    completion_seen: list[str] = []
    des.register_handler(
        EventKind.TRANSFER_COMPLETE,
        lambda event, _: completion_seen.append(event.event_id),
    )
    completion = des.schedule_at(10, EventKind.TRANSFER_COMPLETE, event_id="complete-0")

    def fail_transfer(_event: object, state: GlobalDES) -> None:
        assert state.cancel(completion, reason="GPU_FAILURE")
        canceled = flows.cancel_flow("flow-0", now_ns=state.now_ns, reason="GPU_FAILURE")
        assert canceled.aborted_bytes > 0
        assert copy_engine.cancel("copy-0") is not None
        ResourceTransaction(
            event_id="abort-transfer",
            timestamp_ns=state.now_ns,
            cause="MOONCAKE_PUT",
            allocation_deltas=[
                AllocationDelta(
                    resource_id=ledger.resource_id,
                    account_from="PENDING_REPLICA",
                    account_to="FREE",
                    delta_bytes=40,
                    allocation_id="alloc-0",
                    transfer_id="transfer-0",
                )
            ],
        ).commit(ledgers, journal=state.journal)

    des.register_handler(EventKind.FAILURE_INJECT, fail_transfer)
    des.register_invariant(
        "store_capacity_conserved",
        lambda _state: _assert_capacity_conserved(ledger),
    )
    des.schedule_at(5, EventKind.FAILURE_INJECT, event_id="failure-0")

    des.run()

    assert completion_seen == []
    assert ledger.accounts == {"FREE": 100, "PENDING_REPLICA": 0}
    assert copy_engine.reservations() == ()
    assert flows.flows == {}


def _assert_capacity_conserved(ledger: CapacityLedger) -> None:
    assert all(value >= 0 for value in ledger.accounts.values())
    assert sum(ledger.accounts.values()) == ledger.capacity_bytes
