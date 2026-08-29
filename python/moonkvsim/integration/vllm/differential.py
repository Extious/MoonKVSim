"""Pinned-vLLM CPU scheduler/block semantic differential.

The checked-in golden is captured by a separately installed, source-hash
verified vLLM interpreter.  This module reproduces the same small scenarios
with MoonKVSim and compares scheduling order, semantic origin, vLLM wire
group, phase, token counts, block ownership, reverse-order release, reuse, and
preemption/recompute state.

This is E2 CPU semantic evidence only.  It does not import vLLM, execute a
model, allocate CUDA memory, predict duration, or establish physical parity.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from moonkvsim.common.hash import canonical_json_bytes, sha256_json
from moonkvsim.integration.vllm.block_hash import hash_full_blocks
from moonkvsim.integration.vllm.block_pool import BlockPool
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
from moonkvsim.integration.vllm.request import Request, RequestStatus
from moonkvsim.integration.vllm.scheduler import (
    VLLM_SCHEDULER_SHA256,
    VLLM_SOURCE_COMMIT,
    ContinuousBatchScheduler,
    ScheduledRequest,
    SchedulerOutput,
    SchedulingOrigin,
)

GOLDEN_SCHEMA = "moonkvsim.vllm-scheduler-golden.v1"
GOLDEN_EVIDENCE_CLASS = "E2_cpu_semantics_only"
GOLDEN_RELATIVE_PATH = Path("reference/goldens/vllm-v1.2.2-qwen3-8b-scheduler.json")
GENERATOR_RELATIVE_PATH = Path("scripts/generate_vllm_scheduler_golden.py")
SOURCE_LOCK_RELATIVE_PATH = Path("reference/source-lock.json")
EXPECTED_VLLM_VERSION = "1.2.2+aegiskv.sm89"
EXPECTED_MODEL_ID = "Qwen/Qwen3-8B"
EXPECTED_MODEL_REVISION = "b968826d9c46dd6066d109eabc6255188de91218"
EXPECTED_INTERPRETER = Path("/home/comp/zhanzhao/Mooncake/aegiskv/.venv-vllm-sm89/bin/python")
REQUIRED_CLAIM_EXCLUSIONS = (
    "cuda",
    "model_execution",
    "performance",
    "physical_validation",
    "timing_calibration",
)
CONNECTOR_TRANSITIVE_SHA256 = {
    "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/data.py": (
        "acab2e80024c86d0f9a666e1125a7834559d5bba8bd1ac0848097a9843d5dc27"
    ),
    "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/scheduler.py": (
        "c8bf83fb0a11666cd4936e0fdb3897af5ced5ac34f81d49087c8eb80afcff2ef"
    ),
    "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/worker.py": (
        "dd5765efc936adac88a942773a2ed01fbe0652965906fa2bcedc4bca91ef4128"
    ),
}


class VLLMDifferentialError(RuntimeError):
    """Raised when provenance or any compared semantic field drifts."""


@dataclass(frozen=True, slots=True)
class VLLMDifferentialReport:
    """Successful exact comparison summary."""

    scenario_names: tuple[str, ...]
    operation_count: int
    golden_fingerprint: str
    evidence_class: str = GOLDEN_EVIDENCE_CLASS

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_names": list(self.scenario_names),
            "operation_count": self.operation_count,
            "golden_fingerprint": self.golden_fingerprint,
            "evidence_class": self.evidence_class,
            "claim_exclusions": list(REQUIRED_CLAIM_EXCLUSIONS),
        }


def repository_root() -> Path:
    """Return the checkout root from this installed/editable source file."""

    return Path(__file__).resolve().parents[4]


def load_vllm_scheduler_golden(
    path: Path | None = None,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Load and fail-closed audit the checked-in golden and local bindings."""

    resolved_root = (root or repository_root()).resolve()
    resolved_path = (path or resolved_root / GOLDEN_RELATIVE_PATH).resolve()
    try:
        raw = resolved_path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VLLMDifferentialError(f"cannot load vLLM scheduler golden: {error}") from error
    if not isinstance(document, dict):
        raise VLLMDifferentialError("vLLM scheduler golden root must be an object")
    typed = cast(dict[str, Any], document)
    if raw != canonical_golden_bytes(typed):
        raise VLLMDifferentialError("vLLM scheduler golden is not canonical JSON")
    _audit_golden_document(typed, root=resolved_root)
    return typed


def compare_moonkvsim_to_vllm_golden(
    golden: Mapping[str, Any] | None = None,
    *,
    root: Path | None = None,
) -> VLLMDifferentialReport:
    """Require byte-semantic equality with the captured pinned-vLLM scenarios."""

    document = dict(golden) if golden is not None else load_vllm_scheduler_golden(root=root)
    _audit_golden_document(document, root=(root or repository_root()).resolve())
    expected = _require_list(document.get("scenarios"), "scenarios")
    actual = capture_moonkvsim_scheduler_scenarios()
    if actual != expected:
        mismatch = _first_mismatch(expected, actual, path="scenarios")
        raise VLLMDifferentialError(f"MoonKVSim/pinned-vLLM semantic drift: {mismatch}")
    expected_connector = _require_mapping(
        document.get("connector_lifecycle"),
        "connector_lifecycle",
    )
    actual_connector = capture_moonkvsim_connector_lifecycle()
    if actual_connector != expected_connector:
        mismatch = _first_mismatch(
            expected_connector,
            actual_connector,
            path="connector_lifecycle",
        )
        raise VLLMDifferentialError(f"MoonKVSim/pinned-vLLM connector semantic drift: {mismatch}")
    names = tuple(
        _require_string(_require_mapping(item, "scenario").get("name"), "scenario.name")
        for item in actual
    )
    operation_count = sum(
        len(_require_list(_require_mapping(item, "scenario").get("operations"), "operations"))
        for item in actual
    )
    return VLLMDifferentialReport(
        scenario_names=names,
        operation_count=operation_count,
        golden_fingerprint=sha256_json(document),
    )


def capture_moonkvsim_scheduler_scenarios() -> list[dict[str, object]]:
    """Run the exact tensor-free scenarios encoded by the pinned-vLLM golden."""

    return [
        _capture_continuous_scenario(),
        _capture_pressure_scenario(),
        _capture_prefix_cache_scenario(),
    ]


def capture_moonkvsim_connector_lifecycle() -> dict[str, object]:
    """Capture the tensor-free adapter in the normalized pinned Store shape."""

    hashes = hash_full_blocks(tuple(range(1, 9)), block_size=4)
    load_request = ConnectorRequest("load", tuple(range(1, 9)), hashes)
    load_scheduler = TensorFreeStoreConnectorScheduler(
        block_size_tokens=4,
        role=StoreRole.BOTH,
        lookup=lambda _tokens, _hashes: 8,
    )
    load_match = load_scheduler.get_num_new_matched_tokens(load_request, 0)
    load_scheduler.update_state_after_alloc(load_request, ((1, 2),), load_match[0])
    load_scheduled = ConnectorScheduledRequest(
        request=load_request,
        block_ids=((1, 2),),
        num_computed_tokens=load_match[0],
        num_scheduled_tokens=4,
    )
    load_meta = load_scheduler.build_connector_meta(
        ConnectorScheduleStep(new_requests=(load_scheduled,))
    )

    save_request = ConnectorRequest("save", tuple(range(1, 9)), hashes)
    save_scheduler = TensorFreeStoreConnectorScheduler(
        block_size_tokens=4,
        role=StoreRole.BOTH,
        lookup=lambda _tokens, _hashes: 0,
    )
    save_match = save_scheduler.get_num_new_matched_tokens(save_request, 0)
    save_scheduler.update_state_after_alloc(save_request, ((1, 2),), save_match[0])
    save_scheduled = ConnectorScheduledRequest(
        request=save_request,
        block_ids=((1, 2),),
        num_computed_tokens=0,
        num_scheduled_tokens=8,
    )
    save_meta = save_scheduler.build_connector_meta(
        ConnectorScheduleStep(new_requests=(save_scheduled,))
    )
    delay_free = save_scheduler.request_finished("save", ((1, 2),))

    metadata_worker = TensorFreeStoreConnectorWorker(role=StoreRole.BOTH)
    metadata_worker.bind_connector_metadata(load_meta)
    metadata_bound = metadata_worker.has_connector_metadata
    metadata_worker.clear_connector_metadata()
    metadata_cleared = not metadata_worker.has_connector_metadata

    send_worker = TensorFreeStoreConnectorWorker(role=StoreRole.BOTH)
    send_worker.bind_connector_metadata(save_meta)
    sending_before = send_worker.get_finished(frozenset({"save"})).finished_sending
    send_worker.clear_connector_metadata()
    send_worker.complete_transfers(sending=frozenset({"save"}))
    empty_meta = ConnectorMetadata((), frozenset(), frozenset())
    send_worker.bind_connector_metadata(empty_meta)
    sending_after = send_worker.get_finished(frozenset()).finished_sending
    send_worker.clear_connector_metadata()

    recv_worker = TensorFreeStoreConnectorWorker(role=StoreRole.BOTH)
    recv_worker.bind_connector_metadata(load_meta)
    initial_receive = recv_worker.get_finished(frozenset())
    recv_worker.clear_connector_metadata()
    if initial_receive != ConnectorCompletion():
        raise VLLMDifferentialError("adapter completed an unissued Store receive")
    recv_worker.complete_transfers(receiving=frozenset({"load"}))
    recv_worker.bind_connector_metadata(empty_meta)
    receive_completion = recv_worker.get_finished(frozenset())
    recv_worker.clear_connector_metadata()

    return {
        "name": "store_scheduler_worker_metadata_completion",
        "scheduler": {
            "full_prompt_lookup": [load_match[0], load_match[1]],
            "miss_lookup": [save_match[0], save_match[1]],
            "load_metadata": load_meta.to_dict(),
            "save_metadata": save_meta.to_dict(),
            "request_finished_delays_free": delay_free,
        },
        "worker": {
            "metadata_bound_then_cleared": metadata_bound and metadata_cleared,
            "send_before_transfer_completion": sorted(sending_before),
            "send_after_transfer_completion": sorted(sending_after),
            "receive_completion": sorted(receive_completion.finished_receiving),
            "unexpected_send_completion": sorted(receive_completion.finished_sending),
        },
    }


def _capture_continuous_scenario() -> dict[str, object]:
    scheduler = _make_scheduler(num_blocks=5, token_budget=8)
    visible: dict[str, Request] = {}
    a = _make_request("a", 6)
    b = _make_request("b", 6)
    for request in (a, b):
        scheduler.add_request(request)
        visible[request.request_id] = request

    operations: list[dict[str, object]] = []
    operations.append(_capture_schedule(scheduler, visible, label="step1"))
    operations.append(
        _capture_model_output(
            scheduler,
            visible,
            label="a_decode_token_b_prefill_no_sample",
            sampled_token_ids={"a": [7], "b": []},
        )
    )
    operations.append(_capture_schedule(scheduler, visible, label="step2"))
    operations.append(
        _capture_finish(
            scheduler,
            visible,
            label="finish_a",
            request_id="a",
        )
    )
    c = _make_request("c", 4)
    operations.append(_capture_add_request(scheduler, visible, c, label="add_c"))
    operations.append(_capture_schedule(scheduler, visible, label="step3_reuse"))
    return {
        "name": "continuous_chunked_prefill_decode_release_reuse",
        "config": _scenario_config(num_blocks=5, token_budget=8),
        "operations": operations,
    }


def _capture_pressure_scenario() -> dict[str, object]:
    scheduler = _make_scheduler(num_blocks=4, token_budget=12)
    visible: dict[str, Request] = {}
    head = _make_request("head", 4)
    tail = _make_request("tail", 8)
    for request in (head, tail):
        scheduler.add_request(request)
        visible[request.request_id] = request

    operations: list[dict[str, object]] = []
    operations.append(_capture_schedule(scheduler, visible, label="step1_fill_kv"))
    operations.append(
        _capture_model_output(
            scheduler,
            visible,
            label="head_decode_token_tail_prefill_no_sample",
            sampled_token_ids={"head": [9], "tail": []},
        )
    )
    operations.append(_capture_schedule(scheduler, visible, label="step2_preempt_tail"))
    operations.append(
        _capture_finish(
            scheduler,
            visible,
            label="finish_head",
            request_id="head",
        )
    )
    operations.append(_capture_schedule(scheduler, visible, label="step3_resume_recompute"))
    return {
        "name": "kv_pressure_preempt_recompute",
        "config": _scenario_config(num_blocks=4, token_budget=12),
        "operations": operations,
    }


def _capture_prefix_cache_scenario() -> dict[str, object]:
    scheduler = _make_scheduler(
        num_blocks=5,
        token_budget=8,
        enable_prefix_caching=True,
    )
    visible: dict[str, Request] = {}
    owner = _make_request("owner", 8, token_ids=list(range(1, 9)))
    scheduler.add_request(owner)
    visible[owner.request_id] = owner
    operations: list[dict[str, object]] = []
    operations.append(_capture_schedule(scheduler, visible, label="owner_populates_cache"))
    operations.append(
        _capture_finish(
            scheduler,
            visible,
            label="finish_owner_inactive_residency",
            request_id="owner",
        )
    )
    follower = _make_request("follower", 8, token_ids=list(range(1, 9)))
    operations.append(_capture_add_request(scheduler, visible, follower, label="add_follower"))
    operations.append(_capture_schedule(scheduler, visible, label="full_prompt_hit_recompute_tail"))
    sharer = _make_request("sharer", 5, token_ids=[1, 2, 3, 4, 99])
    operations.append(_capture_add_request(scheduler, visible, sharer, label="add_active_sharer"))
    operations.append(_capture_schedule(scheduler, visible, label="active_refcount_share"))
    operations.append(
        _capture_finish(
            scheduler,
            visible,
            label="finish_follower_shared_ref_survives",
            request_id="follower",
        )
    )
    operations.append(
        _capture_finish(
            scheduler,
            visible,
            label="finish_sharer_all_inactive",
            request_id="sharer",
        )
    )
    replacement = _make_request("replacement", 8, token_ids=list(range(90, 98)))
    operations.append(
        _capture_add_request(scheduler, visible, replacement, label="add_replacement")
    )
    operations.append(_capture_schedule(scheduler, visible, label="lru_cached_pages_evicted"))
    return {
        "name": "prefix_cache_hit_refcount_inactive_and_lru_eviction",
        "config": _scenario_config(
            num_blocks=5,
            token_budget=8,
            enable_prefix_caching=True,
        ),
        "operations": operations,
    }


def _make_scheduler(
    *,
    num_blocks: int,
    token_budget: int,
    enable_prefix_caching: bool = False,
) -> ContinuousBatchScheduler:
    return ContinuousBatchScheduler(
        block_pool=BlockPool(num_blocks, enable_caching=enable_prefix_caching),
        block_size_tokens=4,
        max_num_scheduled_tokens=token_budget,
        max_num_running_requests=2,
        enable_chunked_prefill=True,
        prefix_hash_seed="0" if enable_prefix_caching else None,
    )


def _make_request(
    request_id: str,
    prompt_tokens: int,
    *,
    token_ids: list[int] | None = None,
) -> Request:
    return Request(
        request_id=request_id,
        prompt_tokens=prompt_tokens,
        max_output_tokens=8,
        arrival_ns=0,
        max_model_len_tokens=32,
        prompt_token_ids=tuple(token_ids) if token_ids is not None else None,
    )


def _scenario_config(
    *,
    num_blocks: int,
    token_budget: int,
    enable_prefix_caching: bool = False,
) -> dict[str, object]:
    return {
        "block_size_tokens": 4,
        "num_blocks_including_null": num_blocks,
        "num_usable_blocks": num_blocks - 1,
        "null_block_id": 0,
        "max_num_batched_tokens": token_budget,
        "max_num_running_requests": 2,
        "max_model_len_tokens": 32,
        "enable_chunked_prefill": True,
        "enable_prefix_caching": enable_prefix_caching,
        "async_scheduling": False,
        "policy": "fcfs",
    }


def _capture_schedule(
    scheduler: ContinuousBatchScheduler,
    visible: Mapping[str, Request],
    *,
    label: str,
) -> dict[str, object]:
    before = _local_state(scheduler, visible)
    output = scheduler.schedule()
    after = _local_state(scheduler, visible)
    return {
        "operation": "schedule",
        "label": label,
        "state_before": before,
        "output": _normalize_local_output(output, before=before, after=after),
        "state_after": after,
    }


def _capture_model_output(
    scheduler: ContinuousBatchScheduler,
    visible: Mapping[str, Request],
    *,
    label: str,
    sampled_token_ids: Mapping[str, list[int]],
) -> dict[str, object]:
    before = _local_state(scheduler, visible)
    for request_id, token_ids in sampled_token_ids.items():
        if token_ids:
            scheduler.append_output_tokens(request_id, count=len(token_ids))
    after = _local_state(scheduler, visible)
    return {
        "operation": "model_output",
        "label": label,
        "sampled_token_ids": {key: list(value) for key, value in sampled_token_ids.items()},
        "state_before": before,
        "state_after": after,
    }


def _capture_finish(
    scheduler: ContinuousBatchScheduler,
    visible: Mapping[str, Request],
    *,
    label: str,
    request_id: str,
) -> dict[str, object]:
    before = _local_state(scheduler, visible)
    before_blocks = _state_blocks(before, request_id)
    scheduler.finish_request(request_id, RequestStatus.FINISHED_STOPPED)
    after = _local_state(scheduler, visible)
    return {
        "operation": "finish",
        "label": label,
        "request_id": request_id,
        "finish_status": "FINISHED_STOPPED",
        "released_block_ids": list(reversed(before_blocks)),
        "state_before": before,
        "state_after": after,
    }


def _capture_add_request(
    scheduler: ContinuousBatchScheduler,
    visible: dict[str, Request],
    request: Request,
    *,
    label: str,
) -> dict[str, object]:
    before = _local_state(scheduler, visible)
    scheduler.add_request(request)
    visible[request.request_id] = request
    after = _local_state(scheduler, visible)
    return {
        "operation": "add_request",
        "label": label,
        "request": _request_spec(request),
        "state_before": before,
        "state_after": after,
    }


def _local_state(
    scheduler: ContinuousBatchScheduler,
    visible: Mapping[str, Request],
) -> dict[str, object]:
    requests: list[dict[str, object]] = []
    for request in visible.values():
        requests.append(
            {
                "request_id": request.request_id,
                "status": request.status.name,
                "prompt_tokens": request.prompt_tokens,
                "num_tokens": request.num_tokens,
                "num_computed_tokens": request.num_computed_tokens,
                "num_output_tokens": request.num_output_tokens,
                "num_preemptions": request.num_preemptions,
                "block_ids": list(scheduler.request_block_ids(request.request_id)),
            }
        )
    return {
        "running_request_ids": list(scheduler.running_request_ids),
        "waiting_request_ids": list(scheduler.waiting_request_ids),
        "free_block_ids": list(scheduler.block_pool.free_block_ids),
        "pool_blocks": [
            {
                "block_id": block.block_id,
                "ref_count": block.ref_count,
                "cache_hash": block.block_hash,
                "group_id": block.group_id,
            }
            for block in scheduler.block_pool.blocks
        ],
        "requests": requests,
    }


def _normalize_local_output(
    output: SchedulerOutput,
    *,
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> dict[str, object]:
    by_id: dict[str, ScheduledRequest] = {}
    for group in (
        output.scheduled_running_reqs,
        output.scheduled_new_reqs,
        output.scheduled_resumed_reqs,
    ):
        for item in group:
            if item.request_id in by_id:
                raise VLLMDifferentialError("local scheduler emitted a duplicate request")
            by_id[item.request_id] = item

    group_counts = {"scheduled_new_reqs": 0, "scheduled_cached_reqs": 0}
    rows: list[dict[str, object]] = []
    for order_index, request_id in enumerate(output.num_scheduled_tokens):
        item = by_id[request_id]
        wire_group = _wire_group(item.origin)
        wire_group_index = group_counts[wire_group]
        group_counts[wire_group] += 1
        before_request = _state_request(before, request_id)
        computed_before = _require_integer(
            before_request.get("num_computed_tokens"),
            "request.num_computed_tokens",
        )
        num_tokens_before = _require_integer(
            before_request.get("num_tokens"),
            "request.num_tokens",
        )
        rows.append(
            {
                "request_id": request_id,
                "order_index": order_index,
                "origin": item.origin.value,
                "wire_group": wire_group,
                "wire_group_index": wire_group_index,
                "phase": item.phase.value,
                "num_scheduled_tokens": item.num_scheduled_tokens,
                "num_computed_tokens_before": computed_before,
                "num_local_cache_hit_tokens": item.local_cache_hit_tokens,
                "num_computed_tokens_before_execution": item.num_computed_tokens_before,
                "num_computed_tokens_after": item.num_computed_tokens_after,
                "block_ids_before": list(_state_blocks(before, request_id)),
                "local_cache_hit_block_ids": list(item.local_cache_hit_block_ids),
                "new_block_ids": list(item.new_block_ids),
                "block_ids_after": list(item.block_ids),
                # Match pinned scheduler output semantics: chunking compares
                # execution tokens against the request's pre-lookup token
                # deficit, so a full-prompt prefix hit that recomputes the
                # final block remains classified as chunked.
                "chunked": (item.num_scheduled_tokens < num_tokens_before - computed_before),
                "recompute": item.recompute,
            }
        )
    releases = [
        {
            "request_id": request_id,
            "block_ids": list(reversed(_state_blocks(before, request_id))),
            "cause": "preempt_recompute",
        }
        for request_id in output.preempted_req_ids
    ]
    normalized = {
        "order": list(output.num_scheduled_tokens),
        "rows": rows,
        "num_scheduled_tokens": dict(output.num_scheduled_tokens),
        "total_num_scheduled_tokens": output.total_num_scheduled_tokens,
        "token_budget_remaining": output.token_budget_remaining,
        "preempted_request_ids": list(output.preempted_req_ids),
        "releases": releases,
    }
    _audit_normalized_schedule(normalized, before=before, after=after)
    return normalized


def _wire_group(origin: SchedulingOrigin) -> str:
    if origin in {SchedulingOrigin.NEW, SchedulingOrigin.RESUMED}:
        # Pinned vLLM sends recompute-resumed requests as NewRequestData so the
        # worker receives a complete request/block table again.
        return "scheduled_new_reqs"
    return "scheduled_cached_reqs"


def _request_spec(request: Request) -> dict[str, object]:
    return {
        "request_id": request.request_id,
        "prompt_tokens": request.prompt_tokens,
        "max_output_tokens": request.max_output_tokens,
        "arrival_ns": request.arrival_ns,
    }


def _state_blocks(state: Mapping[str, object], request_id: str) -> tuple[int, ...]:
    request = _state_request(state, request_id)
    values = _require_list(request.get("block_ids"), "request.block_ids")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise VLLMDifferentialError("request.block_ids must contain integers")
    return tuple(cast(int, value) for value in values)


def _state_request(
    state: Mapping[str, object],
    request_id: str,
) -> Mapping[str, Any]:
    for raw_request in _require_list(state.get("requests"), "state.requests"):
        request = _require_mapping(raw_request, "state request")
        if request.get("request_id") == request_id:
            return request
    raise VLLMDifferentialError(f"state is missing request: {request_id}")


def _audit_normalized_schedule(
    output: Mapping[str, object],
    *,
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> None:
    order = _require_list(output.get("order"), "output.order")
    rows = _require_list(output.get("rows"), "output.rows")
    if len(order) != len(rows):
        raise VLLMDifferentialError("schedule rows do not align with scheduling order")
    row_ids = [_require_mapping(row, "schedule row").get("request_id") for row in rows]
    if row_ids != order:
        raise VLLMDifferentialError("schedule row order drift")
    counts = _require_mapping(output.get("num_scheduled_tokens"), "num_scheduled_tokens")
    if list(counts) != order:
        raise VLLMDifferentialError("num_scheduled_tokens insertion order drift")
    total = output.get("total_num_scheduled_tokens")
    budget = output.get("token_budget_remaining")
    if isinstance(total, bool) or not isinstance(total, int):
        raise VLLMDifferentialError("total_num_scheduled_tokens must be an integer")
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise VLLMDifferentialError("token_budget_remaining must be an integer")
    if total != sum(cast(int, count) for count in counts.values()):
        raise VLLMDifferentialError("scheduled token total does not conserve")
    before_free = set(_require_list(before.get("free_block_ids"), "before.free_block_ids"))
    after_free = set(_require_list(after.get("free_block_ids"), "after.free_block_ids"))
    if 0 in before_free or 0 in after_free:
        raise VLLMDifferentialError("null block 0 must never enter the free queue")


def _audit_golden_document(document: Mapping[str, Any], *, root: Path) -> None:
    if document.get("schema") != GOLDEN_SCHEMA:
        raise VLLMDifferentialError("unexpected vLLM scheduler golden schema")
    if document.get("evidence_class") != GOLDEN_EVIDENCE_CLASS:
        raise VLLMDifferentialError("vLLM scheduler golden must remain E2 CPU semantics only")
    exclusions = _require_list(document.get("claim_exclusions"), "claim_exclusions")
    if tuple(exclusions) != REQUIRED_CLAIM_EXCLUSIONS:
        raise VLLMDifferentialError("vLLM scheduler golden claim exclusions drifted")
    provenance = _require_mapping(document.get("provenance"), "provenance")
    if provenance.get("vllm_version") != EXPECTED_VLLM_VERSION:
        raise VLLMDifferentialError("vLLM golden version drift")
    if provenance.get("vllm_source_commit") != VLLM_SOURCE_COMMIT:
        raise VLLMDifferentialError("vLLM golden commit drift")
    if provenance.get("interpreter") != str(EXPECTED_INTERPRETER.resolve()):
        raise VLLMDifferentialError("vLLM golden interpreter provenance drift")
    if provenance.get("device_execution") != "none_cpu_scheduler_only":
        raise VLLMDifferentialError("vLLM golden execution boundary drift")
    cache_spec_probe = _require_mapping(
        provenance.get("cpu_cache_spec_probe"),
        "provenance.cpu_cache_spec_probe",
    )
    if dict(cache_spec_probe) != {
        "block_size": 4,
        "class": "FullAttentionSpec",
        "dtype": "torch.float32",
        "head_size": 1,
        "head_size_v": 1,
        "num_kv_heads": 1,
        "page_size_bytes": 32,
    }:
        raise VLLMDifferentialError("pinned FullAttentionSpec CPU page-size probe drift")
    model = _require_mapping(provenance.get("model"), "provenance.model")
    if model.get("model_id") != EXPECTED_MODEL_ID:
        raise VLLMDifferentialError("vLLM golden model ID drift")
    if model.get("revision") != EXPECTED_MODEL_REVISION:
        raise VLLMDifferentialError("vLLM golden model revision drift")
    if model.get("skip_tokenizer_init") is not True:
        raise VLLMDifferentialError("golden must record skip_tokenizer_init=true")
    if model.get("model_forward_executed") is not False:
        raise VLLMDifferentialError("golden must record that no model forward executed")

    source_lock = _require_mapping(provenance.get("source_lock"), "provenance.source_lock")
    # The capture records the complete lock-file hash, but runtime comparison
    # binds only the vLLM commit/file subset below.  Unrelated later evidence
    # updates (for example calibration readiness) must not invalidate this
    # already-captured scheduler trace.
    _audit_bound_file(
        source_lock,
        expected_relative=SOURCE_LOCK_RELATIVE_PATH,
        root=root,
        enforce_current_hash=False,
    )
    generator = _require_mapping(provenance.get("generator"), "provenance.generator")
    _audit_bound_file(
        generator,
        expected_relative=GENERATOR_RELATIVE_PATH,
        root=root,
        enforce_current_hash=True,
    )

    lock_document = cast(
        dict[str, Any],
        json.loads((root / SOURCE_LOCK_RELATIVE_PATH).read_text(encoding="utf-8")),
    )
    vllm_lock = _require_mapping(
        _require_mapping(lock_document.get("repositories"), "repositories").get("vllm"),
        "repositories.vllm",
    )
    if vllm_lock.get("commit") != VLLM_SOURCE_COMMIT:
        raise VLLMDifferentialError("current source lock no longer has the golden commit")
    installed_root = provenance.get("installed_vllm_root")
    if not isinstance(installed_root, str) or not installed_root.endswith(
        "/lib/python3.12/site-packages/vllm"
    ):
        raise VLLMDifferentialError("golden installed vLLM root provenance drift")
    expected_hashes = {
        _require_string(
            _require_mapping(item, "vLLM file").get("path"), "vLLM file path"
        ): _require_string(_require_mapping(item, "vLLM file").get("sha256"), "vLLM sha256")
        for item in _require_list(vllm_lock.get("files"), "repositories.vllm.files")
    }
    installed = _require_mapping(
        provenance.get("installed_vllm_file_sha256"),
        "installed_vllm_file_sha256",
    )
    if dict(installed) != expected_hashes:
        raise VLLMDifferentialError("golden installed vLLM file hashes drifted from source lock")
    if installed.get("vllm/v1/core/sched/scheduler.py") != VLLM_SCHEDULER_SHA256:
        raise VLLMDifferentialError("golden scheduler SHA drift")
    transitive = _require_mapping(
        provenance.get("installed_store_connector_transitive_sha256"),
        "installed_store_connector_transitive_sha256",
    )
    if dict(transitive) != CONNECTOR_TRANSITIVE_SHA256:
        raise VLLMDifferentialError("golden Store connector transitive hashes drift")
    imported_paths = _require_mapping(
        provenance.get("imported_module_paths"),
        "imported_module_paths",
    )
    expected_imports = {
        "vllm.v1.request": "vllm/v1/request.py",
        "vllm.v1.core.sched.scheduler": "vllm/v1/core/sched/scheduler.py",
        "vllm.v1.core.kv_cache_manager": "vllm/v1/core/kv_cache_manager.py",
        "vllm.v1.core.block_pool": "vllm/v1/core/block_pool.py",
        "vllm.v1.kv_cache_interface": "vllm/v1/kv_cache_interface.py",
        "vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.connector": (
            "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/connector.py"
        ),
        "vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.data": (
            "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/data.py"
        ),
        "vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.scheduler": (
            "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/scheduler.py"
        ),
        "vllm.distributed.kv_transfer.kv_connector.v1.mooncake.store.worker": (
            "vllm/distributed/kv_transfer/kv_connector/v1/mooncake/store/worker.py"
        ),
    }
    installed_package_root = Path(installed_root).parent
    if dict(imported_paths) != {
        module_name: str(installed_package_root / relative)
        for module_name, relative in expected_imports.items()
    }:
        raise VLLMDifferentialError("golden imported-module provenance drift")
    generated_files = _require_list(vllm_lock.get("generated_files"), "generated_files")
    version_sha = next(
        (
            _require_mapping(item, "generated file").get("sha256")
            for item in generated_files
            if _require_mapping(item, "generated file").get("path") == "vllm/_version.py"
        ),
        None,
    )
    if provenance.get("installed_vllm_version_file_sha256") != version_sha:
        raise VLLMDifferentialError("golden vLLM version-file provenance drift")

    model_lock = _require_mapping(lock_document.get("model_tokenizer"), "model_tokenizer")
    if (
        model_lock.get("model_id") != EXPECTED_MODEL_ID
        or model_lock.get("revision") != EXPECTED_MODEL_REVISION
    ):
        raise VLLMDifferentialError("current source lock model identity drift")
    if model.get("snapshot_path") != model_lock.get("snapshot_path"):
        raise VLLMDifferentialError("golden model snapshot provenance drift")
    expected_model_hashes = {
        _require_string(
            _require_mapping(item, "model file").get("path"), "model path"
        ): _require_string(_require_mapping(item, "model file").get("sha256"), "model SHA")
        for item in _require_list(model_lock.get("files"), "model_tokenizer.files")
    }
    if dict(_require_mapping(model.get("file_sha256"), "model.file_sha256")) != (
        expected_model_hashes
    ):
        raise VLLMDifferentialError("golden model file hashes drifted from source lock")

    scenarios = _require_list(document.get("scenarios"), "scenarios")
    if [_require_mapping(item, "scenario").get("name") for item in scenarios] != [
        "continuous_chunked_prefill_decode_release_reuse",
        "kv_pressure_preempt_recompute",
        "prefix_cache_hit_refcount_inactive_and_lru_eviction",
    ]:
        raise VLLMDifferentialError("golden scenario set/order drift")
    for raw_scenario in scenarios:
        scenario = _require_mapping(raw_scenario, "scenario")
        config = _require_mapping(scenario.get("config"), "scenario.config")
        num_blocks = config.get("num_blocks_including_null")
        usable = config.get("num_usable_blocks")
        if (
            isinstance(num_blocks, bool)
            or not isinstance(num_blocks, int)
            or usable != num_blocks - 1
            or config.get("null_block_id") != 0
        ):
            raise VLLMDifferentialError("scenario null/usable block geometry drift")
        for raw_operation in _require_list(scenario.get("operations"), "operations"):
            operation = _require_mapping(raw_operation, "operation")
            if operation.get("operation") == "schedule":
                _audit_normalized_schedule(
                    _require_mapping(operation.get("output"), "operation.output"),
                    before=_require_mapping(operation.get("state_before"), "state_before"),
                    after=_require_mapping(operation.get("state_after"), "state_after"),
                )

    connector = _require_mapping(
        document.get("connector_lifecycle"),
        "connector_lifecycle",
    )
    if connector.get("name") != "store_scheduler_worker_metadata_completion":
        raise VLLMDifferentialError("golden connector lifecycle identity drift")
    scheduler_contract = _require_mapping(
        connector.get("scheduler"),
        "connector_lifecycle.scheduler",
    )
    if scheduler_contract.get("full_prompt_lookup") != [4, True]:
        raise VLLMDifferentialError("Store full-prompt tail recompute contract drift")
    if scheduler_contract.get("miss_lookup") != [0, False]:
        raise VLLMDifferentialError("Store miss contract drift")
    if scheduler_contract.get("request_finished_delays_free") is not True:
        raise VLLMDifferentialError("Store async send delayed-free contract drift")
    worker_contract = _require_mapping(
        connector.get("worker"),
        "connector_lifecycle.worker",
    )
    if worker_contract.get("send_before_transfer_completion") != []:
        raise VLLMDifferentialError("Store worker freed a send before completion")
    if worker_contract.get("send_after_transfer_completion") != ["save"]:
        raise VLLMDifferentialError("Store worker send completion contract drift")
    if worker_contract.get("receive_completion") != ["load"]:
        raise VLLMDifferentialError("Store worker receive completion contract drift")


def _audit_bound_file(
    record: Mapping[str, object],
    *,
    expected_relative: Path,
    root: Path,
    enforce_current_hash: bool,
) -> None:
    if record.get("path") != expected_relative.as_posix():
        raise VLLMDifferentialError(f"bound path drift: {expected_relative}")
    expected_sha = record.get("sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise VLLMDifferentialError(f"invalid bound SHA-256: {expected_relative}")
    if enforce_current_hash:
        try:
            actual_sha = hashlib.sha256((root / expected_relative).read_bytes()).hexdigest()
        except OSError as error:
            raise VLLMDifferentialError(
                f"cannot read bound file {expected_relative}: {error}"
            ) from error
        if actual_sha != expected_sha:
            raise VLLMDifferentialError(f"bound file hash drift: {expected_relative}")


def _first_mismatch(expected: object, actual: object, *, path: str) -> str:
    if type(expected) is not type(actual):
        return f"{path} type expected {type(expected).__name__}, got {type(actual).__name__}"
    if isinstance(expected, dict) and isinstance(actual, dict):
        if set(expected) != set(actual):
            return f"{path} keys expected {sorted(expected)!r}, got {sorted(actual)!r}"
        for key in expected:
            if expected[key] != actual[key]:
                return _first_mismatch(expected[key], actual[key], path=f"{path}.{key}")
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return f"{path} length expected {len(expected)}, got {len(actual)}"
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual, strict=True)):
            if expected_item != actual_item:
                return _first_mismatch(
                    expected_item,
                    actual_item,
                    path=f"{path}[{index}]",
                )
    return f"{path} expected {expected!r}, got {actual!r}"


def _require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise VLLMDifferentialError(f"{name} must be a string-keyed object")
    return cast(Mapping[str, Any], value)


def _require_list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise VLLMDifferentialError(f"{name} must be a list")
    return value


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise VLLMDifferentialError(f"{name} must be a non-empty string")
    return value


def _require_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VLLMDifferentialError(f"{name} must be an integer")
    return value


def canonical_golden_bytes(document: Mapping[str, Any]) -> bytes:
    """Return the single canonical JSON representation used by the generator."""

    return canonical_json_bytes(document) + b"\n"
