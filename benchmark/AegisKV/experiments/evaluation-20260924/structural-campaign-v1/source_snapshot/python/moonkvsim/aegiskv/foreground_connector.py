"""Queue-owned foreground prefix admission for the three-system DES.

The engine, rather than the router, decides when a waiting request can allocate
and start a Store GET. This models the pinned connector lifecycle; it does not
claim native timing or full upstream-engine equivalence.
"""

from __future__ import annotations

from moonkvsim.aegiskv import experiment as base


class ForegroundConnectorAdmission:
    def __init__(self, runtime):
        self.runtime = runtime
        self.starting: set[str] = set()
        self.events: list[dict] = []

    def prepare(self, gpu_id, request, token_budget):
        runtime = self.runtime
        execution = runtime.executions[request.request_id]
        if execution.route_version > 0:
            # Failure recovery has its own explicit reservation/fence protocol.
            return True
        scheduler = runtime.continuous_batch_driver._targets[gpu_id].bridge.scheduler
        pool = runtime.primary_pools[gpu_id]
        local = runtime._local_hbm_prefix_breakdown(
            gpu_id, execution, mutate_signals=False, include_active_primary=False
        )
        local_tokens = base._source_chunk_page_aligned_prefix(
            execution.chunks, local["inactive_reusable_prefix_tokens"],
            logical_page_tokens=16,
        )
        store_tokens = runtime._store_lookup_prefix_tokens(
            execution.chunks, now_ns=runtime.des.now_ns, mutate_signals=False
        ) if runtime._reuse_visible("STORE_DRAM") else 0
        total = base._source_chunk_page_aligned_prefix(
            execution.chunks, max(local_tokens, store_tokens), logical_page_tokens=16
        )
        remote_tokens = max(0, total - local_tokens)
        execution.reused_primary_tokens = local_tokens
        execution.reused_store_tokens = remote_tokens
        execution.reused_peer_tokens = 0
        if local_tokens:
            pool.pin_interval(
                execution.chunks, start_token=0, token_count=local_tokens,
                pin_id=request.request_id,
            )
        if remote_tokens:
            layout = runtime._foreground_store_layout_by_segment(
                execution, start_token=local_tokens, token_count=remote_tokens
            )
            required_bytes = sum(item[0] for item in layout.values())
            required_pages = (total + 15) // 16
        else:
            effective = total - 1 if total == request.num_tokens else total
            remaining = request.num_tokens - effective
            work = min(token_budget, remaining)
            if effective < request.prompt_tokens:
                work = min(work, request.prompt_tokens - effective)
            else:
                work = min(work, 1)
            required_pages = (effective + work + 15) // 16
            required_bytes = max(
                0, base._tokens_to_allocated_bytes(effective + work)
                - base._tokens_to_allocated_bytes(local_tokens)
            )
        if scheduler.scheduler_reserve_full_isl:
            required_pages = max(required_pages, (request.num_tokens + 15) // 16)
            required_bytes = max(required_bytes, (
                base._tokens_to_allocated_bytes(request.num_tokens)
                - base._tokens_to_allocated_bytes(local_tokens)
            ))
        # Like the source engine's waiting allocate_slots failure, stop at the
        # head. Newer requests cannot start GETs around this capacity failure.
        admitted = (
            required_pages <= scheduler.available_logical_pages(request.request_id)
            and runtime._preempt_peer_puts_for_foreground_hbm(gpu_id, required_bytes)
        )
        event = {
            "timestamp_ns": runtime.des.now_ns, "span_id": request.request_id,
            "gpu_id": gpu_id, "num_preemptions": request.num_preemptions,
            "local_tokens": local_tokens, "store_tokens": remote_tokens,
            "required_bytes": required_bytes, "required_pages": required_pages,
            "scheduler_reserve_full_isl": scheduler.scheduler_reserve_full_isl,
            "event": "PREFIX_LOOKUP_ADMITTED" if admitted else "PREFIX_CAPACITY_WAIT",
        }
        self.events.append(event)
        if not admitted:
            pool.release_pin(request.request_id)
            return False
        # Only successful admission touches cache policy. A queued lookup is
        # an estimate, not a cache hit or permission to keep a stale prefix.
        if local_tokens:
            runtime._local_hbm_prefix_breakdown(
                gpu_id, execution, mutate_signals=True, include_active_primary=False
            )
        if remote_tokens:
            runtime._store_lookup_prefix_tokens(
                execution.chunks, now_ns=runtime.des.now_ns, mutate_signals=True
            )
        row = runtime.request_observations.get(request.request_id)
        if row is not None and request.num_preemptions == 0:
            row["local_hit_tokens"] = local_tokens
            row["dram_hit_tokens"] = remote_tokens
        if remote_tokens:
            scheduler.reserve_external_pages(request.request_id, total)
            scheduler.mark_waiting_for_remote_kv(request.request_id)
            self.starting.add(request.request_id)
            try:
                runtime._start_foreground_store_restore(
                    execution, gpu_id=gpu_id,
                    duration_ns=execution.base_duration_ns, route_estimate_ns=0,
                )
            finally:
                self.starting.remove(request.request_id)
        elif local_tokens:
            self.bind_ready(gpu_id, request.request_id, total, external=False)
        return True

    def bind_ready(self, gpu_id, request_id, tokens, *, external):
        runtime = self.runtime
        driver = runtime.continuous_batch_driver
        state = driver._requests[request_id]
        scheduler = driver._targets[gpu_id].bridge.scheduler
        runtime._on_continuous_before_admit(
            gpu_id, state.spec, state.route_version, "CONNECTOR_PREFIX_READY", tokens
        )
        if not external:
            scheduler.mark_waiting_for_remote_kv(request_id, external=False)
        scheduler.restore_waiting_request_prefix(request_id, restored_tokens=tokens)
        driver._invalidate_target_load(gpu_id)
