"""Schedule fluid-flow completions on the one global DES clock."""

from __future__ import annotations

from collections.abc import Callable

from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.network import ActiveFlow, CanceledFlow, FlowContentionModel

FlowCompletionHandler = Callable[[ActiveFlow, GlobalDES], None]


class FlowDESController:
    """Reschedule the earliest completion after every contention mutation."""

    def __init__(self, *, des: GlobalDES, model: FlowContentionModel) -> None:
        if model.last_update_ns != des.now_ns:
            raise ValueError("flow model and DES must start at the same virtual time")
        self.des = des
        self.model = model
        self._completion_handlers: dict[str, FlowCompletionHandler] = {}
        self._completion_event: EventHandle | None = None
        self._event_generation = 0
        des.register_handler(EventKind.TRANSFER_SLICE_COMPLETE, self._handle_completion)

    def start_flow(
        self,
        flow: ActiveFlow,
        *,
        on_complete: FlowCompletionHandler,
    ) -> None:
        if flow.flow_id in self._completion_handlers:
            raise ValueError(f"duplicate flow completion handler: {flow.flow_id}")
        previous_flow_ids = frozenset(self.model.flows)
        previous_rates = self.model.rates()
        previous_event = self._completion_event
        self.model.add_flow(flow, now_ns=self.des.now_ns)
        self._completion_handlers[flow.flow_id] = on_complete
        try:
            self._reschedule()
        except Exception as error:
            # `_reschedule` publishes a replacement before canceling the old
            # completion, so the old handle is still executable on failure.
            # Remove only this just-added flow and restore the pre-start rates;
            # do not call this controller's public cancel path, which would
            # attempt the same failed reschedule again.
            canceled = self.model.cancel_flow(
                flow.flow_id,
                now_ns=self.des.now_ns,
                reason="FLOW_START_ROLLBACK",
            )
            del self._completion_handlers[flow.flow_id]
            flow.allocated_rate_bytes_per_second = 0.0
            if (
                frozenset(self.model.flows) != previous_flow_ids
                or self.model.rates() != previous_rates
                or self._completion_event != previous_event
                or canceled.transferred_bytes != 0.0
            ):
                raise RuntimeError("flow start rollback did not restore prior state") from error
            self.des.journal.append(
                self.des.now_ns,
                "FLOW_DES_START_ROLLED_BACK",
                {
                    "error_type": type(error).__name__,
                    "flow_id": flow.flow_id,
                    "preserved_completion_event_id": (
                        None if self._completion_event is None else self._completion_event.event_id
                    ),
                },
            )
            raise

    def cancel_flow(self, flow_id: str, *, reason: str) -> CanceledFlow:
        canceled = self.model.cancel_flow(flow_id, now_ns=self.des.now_ns, reason=reason)
        try:
            del self._completion_handlers[flow_id]
        except KeyError as error:
            raise RuntimeError("active flow has no completion handler") from error
        self._reschedule()
        return canceled

    def _handle_completion(self, event: ScheduledEvent, des: GlobalDES) -> None:
        if self._completion_event is None or event.event_id != self._completion_event.event_id:
            raise RuntimeError("stale flow completion event executed")
        self._completion_event = None
        completed = self.model.complete_flows(now_ns=des.now_ns)
        if not completed:
            raise RuntimeError("flow completion event did not complete a flow")
        for flow in sorted(completed, key=lambda item: item.flow_id):
            try:
                handler = self._completion_handlers.pop(flow.flow_id)
            except KeyError as error:
                raise RuntimeError("completed flow has no handler") from error
            handler(flow, des)
        self._reschedule()

    def _reschedule(self) -> None:
        previous_event = self._completion_event
        next_completion_ns = self.model.next_completion_ns()
        if next_completion_ns is None:
            if previous_event is not None:
                if not self.des.cancel(
                    previous_event,
                    reason="FLOW_RATE_RECOMPUTED",
                ):
                    raise RuntimeError("active flow completion event could not be canceled")
                self._completion_event = None
            return
        event_id = f"flow-completion-{self._event_generation:016d}"
        self._event_generation += 1
        replacement = self.des.schedule_at(
            next_completion_ns,
            EventKind.TRANSFER_SLICE_COMPLETE,
            event_id=event_id,
            payload={
                "active_flow_ids": sorted(self.model.flows),
                "rates_bytes_per_second": self.model.rates(),
            },
        )
        if previous_event is not None and not self.des.cancel(
            previous_event,
            reason="FLOW_RATE_RECOMPUTED",
        ):
            if not self.des.cancel(
                replacement,
                reason="FLOW_RESCHEDULE_ROLLBACK",
            ):
                raise RuntimeError("flow completion replacement and rollback could not be canceled")
            raise RuntimeError("active flow completion event could not be canceled")
        self._completion_event = replacement
