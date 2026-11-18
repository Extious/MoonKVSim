"""Bind Mooncake transfer slices to the shared fluid-flow DES controller.

This is a tensor-free E1/E2 integration adapter.  It owns only the lifecycle
bridge between :class:`TransferTask`/:class:`Slice` and
:class:`FlowDESController`; Store allocation, publication, and capacity
transactions remain owned by the Store control plane.

In particular, host-staging capacity is deliberately *not* inferred here.
Staged paths name their staging resource in ``TopologyPath``, but the matching
ledger reserve/release transaction must be supplied by the Store operation
that owns the buffer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from moonkvsim.simulation.flow_des import FlowDESController
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.network import ActiveFlow, FlowContentionModel
from moonkvsim.simulation.resource import RateResource
from moonkvsim.store.transfer_engine import (
    Slice,
    SliceStatus,
    TransferStatus,
    TransferTask,
)

EVIDENCE_BOUNDARY: Final = "toy_E1_E2_transfer_flow_semantics_only"
FIDELITY_GAPS: Final[tuple[str, ...]] = (
    "host_staging_capacity_transactions_are_external_to_transfer_runtime",
    "path_concurrency_resources_are_not_reserved_by_flow_des_controller",
)

TaskTerminalHandler = Callable[[TransferTask, GlobalDES], None]


class TransferRuntimeError(RuntimeError):
    """Raised when the task-to-flow bridge would violate an invariant."""


@dataclass(frozen=True, slots=True)
class _FlowBinding:
    flow_id: str
    transfer_id: str
    slice_id: str
    slice_index: int
    offset_bytes: int
    length_bytes: int
    path_resource_ids: tuple[str, ...]


class TransferRuntime:
    """Run ``TransferTask`` slices on one existing ``FlowDESController``.

    ``start_task`` and ``abort_task`` are synchronous mutations at ``des.now_ns``.
    A caller that needs a future start or GPU-failure injection invokes them
    from its existing DES event handler.  This class intentionally registers no
    global event handlers, so it composes with the single-handler DES kernel.
    """

    def __init__(self, *, controller: FlowDESController) -> None:
        self.controller = controller
        self.des = controller.des
        self._tasks: dict[str, TransferTask] = {}
        self._bindings: dict[str, _FlowBinding] = {}
        self._flow_by_slice: dict[tuple[str, str], str] = {}
        self._terminal_handlers: dict[str, TaskTerminalHandler] = {}

    @property
    def active_flow_ids(self) -> tuple[str, ...]:
        """Return runtime-owned active flows in stable transfer/slice order."""

        return tuple(
            binding.flow_id
            for binding in sorted(
                self._bindings.values(),
                key=lambda item: (item.transfer_id, item.slice_index, item.flow_id),
            )
        )

    @property
    def active_transfer_ids(self) -> tuple[str, ...]:
        """Return transfer IDs that still have at least one active flow."""

        return tuple(sorted({item.transfer_id for item in self._bindings.values()}))

    def start_task(
        self,
        task: TransferTask,
        *,
        on_terminal: TaskTerminalHandler | None = None,
    ) -> None:
        """Start a waiting task and post every slice as a stable-order flow."""

        flows = self._preflight_start(task)
        transfer_id = task.metadata.transfer_id
        task.start(timestamp_ns=self.des.now_ns)
        self._tasks[transfer_id] = task
        if on_terminal is not None:
            self._terminal_handlers[transfer_id] = on_terminal
        try:
            self._append(
                "TRANSFER_RUNTIME_TASK_STARTED",
                {
                    "transfer_id": transfer_id,
                    "object_id": task.metadata.object_id,
                    "replica_id": task.metadata.replica_id,
                    "start_ns": self.des.now_ns,
                    "total_bytes": task.metadata.total_bytes,
                    "slice_ids": [item.slice_id for item in task.slices],
                    "path_id": task.metadata.path.path_id,
                    "path_rate_resource_ids": list(task.metadata.path.rate_resource_ids),
                    "path_concurrency_resource_ids": list(
                        task.metadata.path.concurrency_resource_ids
                    ),
                    "source_host_staging_resource_id": (
                        task.metadata.path.source_host_staging_resource_id
                    ),
                    "destination_host_staging_resource_id": (
                        task.metadata.path.destination_host_staging_resource_id
                    ),
                    "evidence_boundary": EVIDENCE_BOUNDARY,
                    "fidelity_gaps": list(FIDELITY_GAPS),
                },
            )

            for slice_index, (item, flow) in enumerate(
                zip(tuple(task.slices), flows, strict=True)
            ):
                posted = item.post(timestamp_ns=self.des.now_ns)
                task.update_slice(posted)
                binding = _FlowBinding(
                    flow_id=flow.flow_id,
                    transfer_id=transfer_id,
                    slice_id=item.slice_id,
                    slice_index=slice_index,
                    offset_bytes=item.offset_bytes,
                    length_bytes=item.length_bytes,
                    path_resource_ids=flow.path_resource_ids,
                )
                self.controller.start_flow(
                    flow,
                    on_complete=self._completion_handler(flow.flow_id),
                )
                self._bindings[flow.flow_id] = binding
                self._flow_by_slice[(transfer_id, item.slice_id)] = flow.flow_id
                self._append(
                    "TRANSFER_RUNTIME_SLICE_FLOW_STARTED",
                    {
                        "flow_id": flow.flow_id,
                        "transfer_id": transfer_id,
                        "slice_id": item.slice_id,
                        "slice_index": slice_index,
                        "offset_bytes": item.offset_bytes,
                        "payload_bytes": flow.payload_bytes,
                        "cause": flow.cause,
                        "weight": flow.weight,
                        "path_resource_ids": list(flow.path_resource_ids),
                    },
                )
        except Exception as error:
            self.abort_task(
                transfer_id,
                reason=f"TRANSFER_RUNTIME_START_FAILED:{type(error).__name__}",
            )
            raise

        self.audit()

    def abort_task(self, transfer_id: str, *, reason: str) -> None:
        """Cancel every active slice flow, then cancel all unfinished slices.

        A GPU failure handler should pass a reason containing its failure ID.
        Failure priority is provided by the global DES; calling this method from
        that handler cancels a same-timestamp completion before it can commit a
        successful slice.
        """

        if not reason:
            raise ValueError("abort reason must be non-empty")
        try:
            task = self._tasks[transfer_id]
        except KeyError as error:
            raise KeyError(f"unknown transfer_id: {transfer_id}") from error
        if task.status.terminal:
            raise TransferRuntimeError("terminal transfer cannot be aborted")

        canceled_flows: list[dict[str, object]] = []
        for item in task.slices:
            flow_id = self._flow_by_slice.get((transfer_id, item.slice_id))
            if flow_id is None:
                continue
            binding = self._bindings[flow_id]
            canceled = self.controller.cancel_flow(flow_id, reason=reason)
            if canceled.transferred_bytes < 0 or canceled.aborted_bytes < 0:
                raise TransferRuntimeError("canceled flow reported negative bytes")
            accounted = canceled.transferred_bytes + canceled.aborted_bytes
            if abs(accounted - binding.length_bytes) > 1e-6:
                raise TransferRuntimeError("canceled flow does not conserve slice bytes")
            canceled_flows.append(
                {
                    "flow_id": flow_id,
                    "slice_id": item.slice_id,
                    "transferred_fluid_bytes": canceled.transferred_bytes,
                    "aborted_fluid_bytes": canceled.aborted_bytes,
                }
            )
            del self._bindings[flow_id]
            del self._flow_by_slice[(transfer_id, item.slice_id)]

        task.cancel_remaining(timestamp_ns=self.des.now_ns, reason=reason)
        task.audit()
        self._append(
            "TRANSFER_RUNTIME_TASK_ABORTED",
            {
                "transfer_id": transfer_id,
                "reason": reason,
                "canceled_flows": canceled_flows,
                "successful_bytes": task.transferred_bytes,
                "total_bytes": task.metadata.total_bytes,
                "evidence_boundary": EVIDENCE_BOUNDARY,
            },
        )
        self._notify_terminal(task)
        self.audit()

    def audit(self) -> None:
        """Fail closed on task/slice/flow mapping or byte/path divergence."""

        if len(self._flow_by_slice) != len(self._bindings):
            raise TransferRuntimeError("slice and flow mapping cardinalities diverged")

        for transfer_id, task in sorted(self._tasks.items()):
            task.audit()
            if task.status is TransferStatus.WAITING or task.start_ns is None:
                raise TransferRuntimeError("registered runtime task was not started")
            active_for_task = {
                binding.slice_id
                for binding in self._bindings.values()
                if binding.transfer_id == transfer_id
            }
            posted = {item.slice_id for item in task.slices if item.status is SliceStatus.POSTED}
            if active_for_task != posted:
                raise TransferRuntimeError("active flows do not match posted slices")
            if task.status.terminal and active_for_task:
                raise TransferRuntimeError("terminal task retains active flows")
            if task.status is TransferStatus.COMPLETED and any(
                item.status is not SliceStatus.SUCCESS for item in task.slices
            ):
                raise TransferRuntimeError("completed task contains a non-success slice")

        for flow_id, binding in sorted(self._bindings.items()):
            reverse_key = (binding.transfer_id, binding.slice_id)
            if self._flow_by_slice.get(reverse_key) != flow_id:
                raise TransferRuntimeError("flow reverse mapping diverged")
            try:
                task = self._tasks[binding.transfer_id]
                flow = self.controller.model.flows[flow_id]
            except KeyError as error:
                raise TransferRuntimeError(
                    "runtime mapping references missing task or flow"
                ) from error
            item = self._slice(task, binding.slice_id)
            if item.status is not SliceStatus.POSTED:
                raise TransferRuntimeError("active flow is not backed by a posted slice")
            if (
                flow.transfer_id != binding.transfer_id
                or flow.slice_id != binding.slice_id
                or flow.payload_bytes != binding.length_bytes
                or flow.path_resource_ids != binding.path_resource_ids
                or binding.path_resource_ids != task.metadata.path.rate_resource_ids
                or binding.offset_bytes != item.offset_bytes
                or binding.length_bytes != item.length_bytes
            ):
                raise TransferRuntimeError("active flow diverged from its bound slice")

    def _preflight_start(self, task: TransferTask) -> tuple[ActiveFlow, ...]:
        transfer_id = task.metadata.transfer_id
        if task.status is not TransferStatus.WAITING:
            raise TransferRuntimeError("only a waiting transfer task may start")
        if transfer_id in self._tasks:
            raise TransferRuntimeError(f"duplicate transfer_id: {transfer_id}")
        if self.des.now_ns < task.metadata.ready_ns:
            raise TransferRuntimeError("transfer cannot start before ready_ns")
        try:
            task.audit()
        except RuntimeError as error:
            raise TransferRuntimeError("transfer task failed byte-layout audit") from error
        if not task.slices:
            raise TransferRuntimeError("transfer task must contain at least one slice")

        slice_ids = [item.slice_id for item in task.slices]
        if len(set(slice_ids)) != len(slice_ids):
            raise TransferRuntimeError("slice IDs must be unique within a task")
        if any(
            item.transfer_id != transfer_id or item.status is not SliceStatus.PENDING
            for item in task.slices
        ):
            raise TransferRuntimeError("new task slices must be pending and owned by the task")

        path = task.metadata.path.rate_resource_ids
        unknown_resources = set(path) - self.controller.model.resources.keys()
        if unknown_resources:
            raise TransferRuntimeError(
                f"path contains unknown rate resources: {sorted(unknown_resources)}"
            )

        flows = tuple(self._flow_for_slice(task, item) for item in task.slices)
        flow_ids = [flow.flow_id for flow in flows]
        if len(set(flow_ids)) != len(flow_ids):
            raise TransferRuntimeError("derived flow IDs are not unique")
        conflicts = set(flow_ids).intersection(self.controller.model.flows)
        conflicts.update(set(flow_ids).intersection(self._bindings))
        if conflicts:
            raise TransferRuntimeError(f"flow IDs already active: {sorted(conflicts)}")
        if sum(flow.payload_bytes for flow in flows) != task.metadata.total_bytes:
            raise TransferRuntimeError("slice flows do not conserve task bytes")
        return flows

    @staticmethod
    def _flow_for_slice(task: TransferTask, item: Slice) -> ActiveFlow:
        return ActiveFlow(
            flow_id=f"transfer-flow:{item.slice_id}",
            transfer_id=task.metadata.transfer_id,
            slice_id=item.slice_id,
            cause=task.metadata.cause,
            path_resource_ids=task.metadata.path.rate_resource_ids,
            payload_bytes=item.length_bytes,
            remaining_bytes=float(item.length_bytes),
        )

    def _completion_handler(self, expected_flow_id: str) -> Callable[[ActiveFlow, GlobalDES], None]:
        def complete(flow: ActiveFlow, des: GlobalDES) -> None:
            self._complete_flow(expected_flow_id=expected_flow_id, flow=flow, des=des)

        return complete

    def _complete_flow(
        self,
        *,
        expected_flow_id: str,
        flow: ActiveFlow,
        des: GlobalDES,
    ) -> None:
        if des is not self.des:
            raise TransferRuntimeError("flow completed on a different DES")
        if flow.flow_id != expected_flow_id:
            raise TransferRuntimeError("flow completion callback received the wrong flow")
        try:
            binding = self._bindings[flow.flow_id]
            task = self._tasks[binding.transfer_id]
        except KeyError as error:
            raise TransferRuntimeError("completion references an unknown runtime flow") from error
        item = self._slice(task, binding.slice_id)
        if item.status is not SliceStatus.POSTED:
            raise TransferRuntimeError("only a posted slice may complete")
        if (
            flow.transfer_id != binding.transfer_id
            or flow.slice_id != binding.slice_id
            or flow.payload_bytes != binding.length_bytes
            or flow.path_resource_ids != binding.path_resource_ids
            or flow.remaining_bytes != 0.0
            or item.offset_bytes != binding.offset_bytes
            or item.length_bytes != binding.length_bytes
            or task.metadata.path.rate_resource_ids != binding.path_resource_ids
        ):
            raise TransferRuntimeError("completed flow violates its slice binding")

        task.update_slice(
            item.finish(
                SliceStatus.SUCCESS,
                timestamp_ns=des.now_ns,
            )
        )
        del self._bindings[flow.flow_id]
        del self._flow_by_slice[(binding.transfer_id, binding.slice_id)]
        self._append(
            "TRANSFER_RUNTIME_SLICE_FLOW_COMPLETED",
            {
                "flow_id": flow.flow_id,
                "transfer_id": binding.transfer_id,
                "slice_id": binding.slice_id,
                "slice_index": binding.slice_index,
                "offset_bytes": binding.offset_bytes,
                "payload_bytes": binding.length_bytes,
                "path_resource_ids": list(binding.path_resource_ids),
            },
        )

        if task.status is TransferStatus.COMPLETED:
            task.audit()
            if any(
                binding.transfer_id == task.metadata.transfer_id
                for binding in self._bindings.values()
            ):
                raise TransferRuntimeError("completed task still owns an active flow")
            self._append(
                "TRANSFER_RUNTIME_TASK_COMPLETED",
                {
                    "transfer_id": task.metadata.transfer_id,
                    "start_ns": task.start_ns,
                    "end_ns": task.end_ns,
                    "transferred_bytes": task.transferred_bytes,
                    "total_bytes": task.metadata.total_bytes,
                    "evidence_boundary": EVIDENCE_BOUNDARY,
                },
            )
            self._notify_terminal(task)

    @staticmethod
    def _slice(task: TransferTask, slice_id: str) -> Slice:
        for item in task.slices:
            if item.slice_id == slice_id:
                return item
        raise TransferRuntimeError(f"task is missing slice: {slice_id}")

    def _append(self, record_type: str, data: dict[str, object]) -> None:
        self.des.journal.append(self.des.now_ns, record_type, data)

    def _notify_terminal(self, task: TransferTask) -> None:
        handler = self._terminal_handlers.pop(task.metadata.transfer_id, None)
        if handler is not None:
            handler(task, self.des)


def replay_transfer_flow_state(
    journal: EventJournal,
    resources: Mapping[str, RateResource],
) -> FlowContentionModel:
    """Rebuild the fluid-flow rate state and intervals from runtime records."""

    resolved_resources = dict(resources)
    if any(key != value.resource_id for key, value in resolved_resources.items()):
        raise TransferRuntimeError("rate replay resource keys must match resource IDs")
    model = FlowContentionModel(
        [value for _, value in sorted(resolved_resources.items())],
    )
    pending_completed: dict[str, ActiveFlow] = {}
    completion_timestamp_ns: int | None = None

    for record in journal.records:
        if (
            pending_completed
            and completion_timestamp_ns is not None
            and record.timestamp_ns > completion_timestamp_ns
        ):
            raise TransferRuntimeError(
                "completed flow is missing its terminal runtime journal record"
            )
        data = record.data
        if record.record_type == "TRANSFER_RUNTIME_SLICE_FLOW_STARTED":
            flow_id = _replay_string(data, "flow_id")
            transfer_id = _replay_string(data, "transfer_id")
            slice_id = _replay_string(data, "slice_id")
            payload_bytes = _replay_integer(data, "payload_bytes")
            cause = _replay_string(data, "cause")
            path_resource_ids = _replay_string_tuple(data, "path_resource_ids")
            weight = _replay_number(data, "weight")
            if payload_bytes <= 0 or weight <= 0:
                raise TransferRuntimeError("replayed flow payload and weight must be positive")
            model.add_flow(
                ActiveFlow(
                    flow_id=flow_id,
                    transfer_id=transfer_id,
                    slice_id=slice_id,
                    cause=cause,
                    path_resource_ids=path_resource_ids,
                    payload_bytes=payload_bytes,
                    remaining_bytes=float(payload_bytes),
                    weight=weight,
                ),
                now_ns=record.timestamp_ns,
            )
        elif record.record_type == "TRANSFER_RUNTIME_SLICE_FLOW_COMPLETED":
            flow_id = _replay_string(data, "flow_id")
            if not pending_completed:
                completed = model.complete_flows(now_ns=record.timestamp_ns)
                if not completed:
                    raise TransferRuntimeError(
                        "flow completion record did not complete an online replay flow"
                    )
                pending_completed = {item.flow_id: item for item in completed}
                completion_timestamp_ns = record.timestamp_ns
            elif record.timestamp_ns != completion_timestamp_ns:
                raise TransferRuntimeError("simultaneous flow completions changed timestamp")
            try:
                flow = pending_completed.pop(flow_id)
            except KeyError as error:
                raise TransferRuntimeError(
                    "flow completion record differs from deterministic rate replay"
                ) from error
            if (
                flow.transfer_id != _replay_string(data, "transfer_id")
                or flow.slice_id != _replay_string(data, "slice_id")
                or flow.payload_bytes != _replay_integer(data, "payload_bytes")
                or flow.path_resource_ids
                != _replay_string_tuple(data, "path_resource_ids")
            ):
                raise TransferRuntimeError(
                    "completed replay flow differs from its runtime record"
                )
            if not pending_completed:
                completion_timestamp_ns = None
        elif record.record_type == "TRANSFER_RUNTIME_TASK_ABORTED":
            reason = _replay_string(data, "reason")
            raw_canceled = data.get("canceled_flows")
            if not isinstance(raw_canceled, list):
                raise TransferRuntimeError("canceled_flows must be a list")
            for raw in raw_canceled:
                if not isinstance(raw, dict):
                    raise TransferRuntimeError("canceled flow replay item must be an object")
                item = raw
                flow_id = _replay_string(item, "flow_id")
                try:
                    flow = model.flows[flow_id]
                except KeyError as error:
                    raise TransferRuntimeError(
                        "canceled flow is absent from deterministic rate replay"
                    ) from error
                if flow.slice_id != _replay_string(item, "slice_id"):
                    raise TransferRuntimeError("canceled replay flow slice differs")
                canceled = model.cancel_flow(
                    flow_id,
                    now_ns=record.timestamp_ns,
                    reason=reason,
                )
                if (
                    canceled.transferred_bytes
                    != _replay_number(item, "transferred_fluid_bytes")
                    or canceled.aborted_bytes
                    != _replay_number(item, "aborted_fluid_bytes")
                ):
                    raise TransferRuntimeError(
                        "canceled replay flow byte accounting differs"
                    )

    if pending_completed:
        raise TransferRuntimeError(
            "completed flow is missing its terminal runtime journal record"
        )
    return model


def transfer_flow_replay_byte_identical(
    journal: EventJournal,
    online_model: FlowContentionModel,
) -> bool:
    """Compare pristine rate replay with the complete online flow model."""

    replayed = replay_transfer_flow_state(journal, online_model.resources)
    return replayed.snapshot_bytes() == online_model.snapshot_bytes()


def _replay_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise TransferRuntimeError(f"{key} must be a non-empty string")
    return value


def _replay_integer(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TransferRuntimeError(f"{key} must be an integer")
    return value


def _replay_number(data: Mapping[str, Any], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TransferRuntimeError(f"{key} must be numeric")
    return float(value)


def _replay_string_tuple(data: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise TransferRuntimeError(f"{key} must contain non-empty strings")
    return tuple(value)
