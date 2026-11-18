"""Paired three-system experiments on the shared continuous-batching DES.

This adapter owns revision-3 protection; the historical experiment runner does
not. GPU service remains an uncalibrated model. CPU samples are thread CPU time
of the Python policy implementation, never CPU utilization of a native server.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from time import thread_time_ns
from typing import Any

from moonkvsim.aegiskv import experiment as base
from moonkvsim.aegiskv.foreground_budget import (
    ForegroundBudget,
    MemoryEnvelope,
    Observation,
    QoSCertificate,
)
from moonkvsim.aegiskv.prefix_frontier import Consumer, KVObject, PrefixPool
from moonkvsim.simulation.event import EventKind

SYSTEM_LABELS = {
    "mooncake": "Mooncake",
    "dram": "DRAM-only AegisKV",
    "aegis": "AegisKV",
}


@dataclass(frozen=True)
class MechanismConfig:
    retention_ns: int = 120_000_000_000
    staging_bytes: int = 2 * 1024**3
    max_group: int = 2
    cpu_service_ns: int = 0
    foreground_cpu_service_ns: int = 0
    slack_enabled: bool = True
    foreground_reserve_bytes: int = 1024**3
    # A positive exploratory quota is an experimental control, not a QoS cert.
    peer_mode: str = "capacity_guarded_exploration"
    certificate: QoSCertificate | None = None
    source_version: str = "prefix-frontier-r3-continuous-des-v1"


class RevisionPool(base._ModeledPool):
    """Revision-3 planner plus the existing transfer/physical-byte ledger.

    Old copies remain charged and readable while replacements copy. A stale
    plan aborts. Physical free follows the simulator's synchronous fenced DMA
    cancellation; this boundary is recorded, not called a native ACK model.
    """

    def __init__(self, *, runtime: MechanismRuntime, original: base._ModeledPool):
        super().__init__(
            pool_id=original.pool_id,
            capacity_bytes=original.capacity_bytes,
            physical_capacity_bytes=original.physical_capacity_bytes,
            eviction=base.EvictionKind.LRU,
            seed=original.seed,
        )
        self.runtime = runtime
        config = runtime.mechanism_config
        staging = min(config.staging_bytes, max(1, original.capacity_bytes // 2))
        self.policy = PrefixPool(
            max(1, original.capacity_bytes), staging, max_group=config.max_group
        )
        self.copy_transactions: dict[str, int] = {}
        self.context: base._PendingPutStart | None = None
        self.commit_outcomes: dict[str, str] = {}

    def register(self, execution: base._SpanExecution) -> None:
        parent = None
        for chunk in execution.chunks:
            self.policy.register_object(KVObject(chunk.key, parent, "qwen3-8b-shared", chunk.bytes))
            parent = chunk.key
        duration_ms = execution.base_duration_ns / 1e6
        prompt = execution.metadata.prompt_tokens
        # Same observed-trace estimator for all variants; no learned predictor
        # is implied by these modeled recovery costs.
        curve = [duration_ms]
        rate = (
            self.runtime.parameters.peer_bandwidth_bytes_per_second
            if self.pool_id.startswith("PEER_HBM")
            else self.runtime.parameters.store_bandwidth_bytes_per_second
        )
        copied_bytes = 0
        for chunk in execution.chunks:
            copied_bytes += chunk.bytes
            prefix = chunk.token_start + chunk.token_count
            recompute = duration_ms * max(0, prompt - prefix) / max(1, prompt)
            restore = copied_bytes / rate * 1000
            curve.append(min(curve[-1], recompute + restore))
        slack = self.runtime.algorithm1_cpm.timings[execution.metadata.span_id].slack_ns / 1e6
        if not self.runtime.mechanism_config.slack_enabled:
            slack = 0.0
        self.policy.update_consumer(
            Consumer(
                execution.metadata.span_id,
                "qwen3-8b-shared",
                tuple(c.key for c in execution.chunks),
                tuple(curve),
                slack,
                ticket_ns=self.runtime.des.now_ns,
                route_epoch=execution.route_version,
                expires_ns=self.runtime.des.now_ns + 3600 * 10**9,
            )
        )

    def retire(self, span_id: str, now_ns: int) -> None:
        consumer = self.policy.consumers.get(span_id)
        if consumer is not None and consumer.active:
            self.policy.update_consumer(
                replace(
                    consumer,
                    active=False,
                    weight=0.0,
                    expires_ns=now_ns + self.runtime.mechanism_config.retention_ns,
                )
            )

    def reserve(self, reservation_id, chunks, scores, *, now_ns, cause):
        context = self.context
        if context is None:
            raise base.ExperimentError("revision pool lost its sealed-source context")
        started = thread_time_ns()
        source_available = {c.key for c in chunks}
        consumer = self.policy.consumers.get(context.span_id)
        if (
            consumer is None
            or consumer.route_epoch != self.runtime.executions[context.span_id].route_version
        ):
            self.register(self.runtime.executions[context.span_id])
        rate = (
            self.runtime.parameters.peer_bandwidth_bytes_per_second
            if context.path == "PEER_HBM"
            else self.runtime.parameters.store_bandwidth_bytes_per_second
        )
        plan = self.policy.plan(
            context.span_id,
            now_ns=now_ns,
            source_available=source_available,
            copy_budget_bytes=self.policy.staging_bytes,
            copy_ns_per_byte=1e9 / rate,
            setup_ns=self.runtime.parameters.transfer_setup_ns,
        )
        observation = {
            "timestamp_ns": now_ns,
            "span_id": context.span_id,
            "pool_id": self.pool_id,
            "operation": "prefix_admission",
            "cpu_ns": 0,
            "resident_objects": len(self.policy.committed),
            "consumers": len(self.policy.consumers),
            "source_objects": len(source_available),
            "accepted": plan is not None,
        }
        if plan is None:
            observation["cpu_ns"] = thread_time_ns() - started
            self.runtime.policy_cpu.append(observation)
            self.last_reserve_outcome = "REVISION3_PAUSE"
            return None
        selected = tuple(c for c in chunks if c.key in plan.add)
        if len(selected) != len(plan.add):
            raise base.ExperimentError("planner attempted to copy unsealed content")
        tx = self.policy.begin(plan, now_ns)
        # Staging is inside quota. No victim is removed at reservation time.
        result = super().reserve(
            reservation_id,
            selected,
            tuple(Fraction(now_ns) for _ in selected),
            now_ns=now_ns,
            cause=cause,
        )
        if result is None:
            raise base.ExperimentError("physical mirror rejected a feasible staged group")
        if set(self.entries) != self.policy.committed:
            raise base.ExperimentError("replacement evicted old protection before copy ACK")
        self.copy_transactions[reservation_id] = tx
        observation["cpu_ns"] = thread_time_ns() - started
        self.runtime.policy_cpu.append(observation)
        return result

    def prepare_commit(self, reservation_id: str, now_ns: int) -> bool:
        txid = self.copy_transactions[reservation_id]
        tx = self.policy.transactions[txid]
        for key in tx.plan.add:
            self.policy.acknowledge_shard(txid, key, 0)
        outcome = self.policy.finish(txid, now_ns)
        self.commit_outcomes[reservation_id] = outcome
        return outcome == "COMMITTED"

    def _free_acknowledged(self) -> None:
        for key, generation in self.policy.reclaim_tasks():
            self.policy.acknowledge_free(key, generation)

    def expire(self, now_ns: int):
        if self.failed:
            return
        self._sync_read_pins(now_ns)
        self.policy.collect_expired(now_ns)
        victims = set(self.entries) - self.policy.committed
        if victims:
            super().set_capacity_exact(
                self.capacity_bytes,
                victim_keys=tuple(sorted(victims)),
                proposed_rent=self.rent,
                now_ns=now_ns,
                cause="REVISION3_RETENTION_TTL",
            )
        self._free_acknowledged()

    def resize(self, quota: int, now_ns: int):
        if self.pending:
            raise base.ExperimentError("quota change requires fenced pending copies")
        self._sync_read_pins(now_ns)
        self.policy.set_quota(quota, now_ns)
        victims = set(self.entries) - self.policy.committed
        # Physical readers can keep debt above a desired quota until release.
        physical_cap = max(quota, self.policy.physical_bytes - self.policy.nbytes(victims))
        super().set_capacity_exact(
            physical_cap,
            victim_keys=tuple(sorted(victims)),
            proposed_rent=self.rent,
            now_ns=now_ns,
            cause="REVISION3_FOREGROUND_QUOTA",
        )
        self._free_acknowledged()
        self.check_revision()

    def commit_reservation(self, reservation_id, *, now_ns, cause):
        if self.commit_outcomes.pop(reservation_id, None) != "COMMITTED":
            raise base.ExperimentError("physical commit lacks revision-3 validation")
        tx = self.policy.transactions[self.copy_transactions.pop(reservation_id)]
        result = super().commit_reservation(reservation_id, now_ns=now_ns, cause=cause)
        super().set_capacity_exact(
            self.capacity_bytes,
            victim_keys=tuple(sorted(tx.plan.victims)),
            proposed_rent=self.rent,
            now_ns=now_ns,
            cause="REVISION3_COPY_ACK_ATOMIC_REPLACEMENT",
        )
        self._free_acknowledged()
        self.check_revision()
        return result

    def abort_reservation(self, reservation_id, *, now_ns, cause):
        txid = self.copy_transactions.pop(reservation_id)
        self.policy.finish(txid, now_ns, success=False)
        self.commit_outcomes.pop(reservation_id, None)
        result = super().abort_reservation(reservation_id, now_ns=now_ns, cause=cause)
        self._free_acknowledged()
        self.check_revision()
        return result

    def evict_at_least(self, required_bytes, *, now_ns, cause):
        if required_bytes <= 0:
            return 0
        if self.pending:
            raise base.ExperimentError("foreground reclaim must fence copies first")
        old = self.occupied_bytes
        old_quota = self.policy.quota
        self._sync_read_pins(now_ns)
        self.policy.set_quota(max(0, old - required_bytes) + self.policy.staging_bytes, now_ns)
        victims = set(self.entries) - self.policy.committed
        super().set_capacity_exact(
            self.capacity_bytes,
            victim_keys=tuple(sorted(victims)),
            proposed_rent=self.rent,
            now_ns=now_ns,
            cause=cause,
        )
        self._free_acknowledged()
        self.policy.quota = old_quota
        self.check_revision()
        return old - self.occupied_bytes

    def _sync_read_pins(self, now_ns):
        # The lower transfer layer owns and fences these physical source pins.
        self.policy.leases = (
            {"physical-readers": (frozenset(self.pinned_entry_keys), now_ns + 10**18)}
            if self.pinned_entry_keys
            else {}
        )

    def fail(self, *, now_ns, cause):
        result = super().fail(now_ns=now_ns, cause=cause)
        self.policy.committed.clear()
        self.policy.allocations.clear()
        self.policy.reclaiming.clear()
        self.policy.leases.clear()
        self.policy.pending = None
        self.policy.epoch += 1
        return result

    def check_revision(self):
        self.policy.check()
        if set(self.entries) != self.policy.committed:
            raise base.ExperimentError("revision committed content and physical directory differ")
        if self.occupied_bytes + self.pending_bytes != self.policy.physical_bytes:
            raise base.ExperimentError("revision physical bytes and transfer ledger differ")


class InstrumentedLRUPool(base._ModeledPool):
    def __init__(self, *, runtime, original):
        super().__init__(
            pool_id=original.pool_id,
            capacity_bytes=original.capacity_bytes,
            physical_capacity_bytes=original.physical_capacity_bytes,
            eviction=base.EvictionKind.LRU,
            seed=original.seed,
        )
        self.runtime = runtime
        self.context = None
        self.expirations = {}

    def expire(self, now_ns):
        victims = tuple(
            k
            for k, expiry in self.expirations.items()
            if expiry <= now_ns and k in self.entries and k not in self.pinned_entry_keys
        )
        if victims:
            self.set_capacity_exact(
                self.capacity_bytes,
                victim_keys=victims,
                proposed_rent=self.rent,
                now_ns=now_ns,
                cause="STORE_RETENTION_TTL",
            )
            for k in victims:
                del self.expirations[k]

    def reserve(self, reservation_id, chunks, scores, *, now_ns, cause):
        start = thread_time_ns()
        result = super().reserve(reservation_id, chunks, scores, now_ns=now_ns, cause=cause)
        elapsed = thread_time_ns() - start
        self.runtime.policy_cpu.append(
            {
                "timestamp_ns": now_ns,
                "span_id": self.context.span_id,
                "pool_id": self.pool_id,
                "operation": "lru_admission",
                "cpu_ns": elapsed,
                "resident_objects": len(self.entries),
                "consumers": 0,
                "source_objects": len(chunks),
                "accepted": result is not None,
            }
        )
        return result


DEFAULT_MECHANISM_CONFIG = MechanismConfig()


from moonkvsim.aegiskv.foreground_connector import ForegroundConnectorAdmission


class MechanismRuntime(base._StudyRuntime):
    protection_pool_class = RevisionPool
    baseline_pool_class = InstrumentedLRUPool

    def __init__(self, *, system: str, mechanism_config=DEFAULT_MECHANISM_CONFIG, **kwargs):
        if system not in SYSTEM_LABELS:
            raise ValueError("unknown three-system comparison member")
        self.foreground_connector = ForegroundConnectorAdmission(self)
        self.system = system
        self.mechanism_config = mechanism_config
        self.policy_cpu: list[dict[str, Any]] = []
        self.allocation_observations: list[dict[str, Any]] = []
        self.request_observations: dict[str, dict[str, Any]] = {}
        self.token_emission_times: dict[str, list[int]] = {}
        self.sealed_frontiers: dict[tuple[str, int], int] = {}
        self.cpu_available_ns = 0
        self.cpu_queue: list[dict[str, Any]] = []
        self.pending_releases = {}
        self.store_waiting = {}
        self.store_retry_pending = False
        self.store_wait_events = []
        self.budget_observations = []
        self.governors = {}
        self.budget_sequence = Counter()
        super().__init__(**kwargs)
        self.des.register_handler(EventKind.ROUTE_REQUEST, self._on_cpu_release)
        self.des.register_handler(EventKind.STORE_QUERY, self._retry_store_waiters)
        if not self.continuous_batch_enabled:
            raise ValueError("mechanism study requires exact token IDs and continuous batching")
        if self.parameters.runtime_semantics != "shared_prefix_v3":
            raise ValueError("mechanism study requires shared_prefix_v3")
        if self.formal_landlords:
            raise ValueError("legacy Landlord cannot own the revision-3 path")
        identities = {}
        for execution in self.executions.values():
            parent = None
            for chunk in execution.chunks:
                identity = (parent, chunk.bytes)
                if identities.setdefault(chunk.key, identity) != identity:
                    raise ValueError(
                        "shared KV identity lost preceding context or allocation geometry"
                    )
                parent = chunk.key
        if system != "mooncake":
            self.store_pools = {
                k: self.protection_pool_class(runtime=self, original=p) for k, p in self.store_pools.items()
            }
        else:
            self.store_pools = {
                k: self.baseline_pool_class(runtime=self, original=p)
                for k, p in self.store_pools.items()
            }
        if system == "aegis":
            self.peer_pools = {
                k: self.protection_pool_class(runtime=self, original=p) for k, p in self.peer_pools.items()
            }
            for gpu_id, pool in self.peer_pools.items():
                self.governors[gpu_id] = ForegroundBudget(
                    epoch=0,
                    registered_bytes=self.parameters.physical_hbm_bytes_per_gpu,
                    policy_cap_bytes=self.parameters.peer_hbm_quota_bytes_per_gpu,
                    allow_modeled=True,
                )
                if mechanism_config.peer_mode == "guarded":
                    pool.resize(0, 0)
            if mechanism_config.peer_mode not in {"guarded", "capacity_guarded_exploration"}:
                raise ValueError("invalid Peer budget mode")

    def _observe_budget(self, gpu_id, next_primary_bytes=0):
        if self.system != "aegis" or gpu_id in self.failed_gpu_ids:
            return
        pool = self.peer_pools[gpu_id]
        ledger = self.hbm_ledgers[gpu_id]
        peer = pool.occupied_bytes + pool.pending_bytes
        free = ledger.bytes_in(base.FREE_ACCOUNT)
        inactive = ledger.bytes_in(base.HBM_INACTIVE_REUSABLE_ACCOUNT)
        primary = ledger.bytes_in(base.HBM_ACTIVE_PRIMARY_ACCOUNT)
        total = self.parameters.physical_hbm_bytes_per_gpu
        self.budget_sequence[gpu_id] += 1
        memory = MemoryEnvelope(
            total,
            total - free - inactive - primary - peer,
            primary + inactive - self.primary_pools[gpu_id].evictable_bytes,
            next_primary_bytes,
            self.mechanism_config.foreground_reserve_bytes,
            128 * 1024**2,
            free + peer + self.primary_pools[gpu_id].evictable_bytes,
        )
        demand = sum(
            base._tokens_to_allocated_bytes(e.metadata.prompt_tokens)
            for e in self.executions.values()
            if e.designated_peer_gpu_id == gpu_id
            and e.released_ns is not None
            and e.completed_ns is None
        )
        decision = self.governors[gpu_id].observe(
            Observation(
                0,
                self.budget_sequence[gpu_id],
                self.des.now_ns,
                self.des.now_ns,
                "qwen3-8b-mechanism",
                "frozen-workload-region",
                memory,
                peer,
                0,
                demand,
                certificate=self.mechanism_config.certificate,
            )
        )
        quota = decision.quota_bytes
        reason = decision.reason
        if self.mechanism_config.peer_mode == "capacity_guarded_exploration":
            quota = min(memory.backup_limit, self.parameters.peer_hbm_quota_bytes_per_gpu)
            reason = "UNCERTIFIED_CAPACITY_GUARDED_PROBE"
        self.budget_observations.append(
            {
                "timestamp_ns": self.des.now_ns,
                "gpu_id": gpu_id,
                "decision": asdict(decision),
                "applied_quota_bytes": quota,
                "applied_reason": reason,
                "memory": asdict(memory),
            }
        )
        if quota < pool.occupied_bytes + pool.pending_bytes:
            self._abort_pending_peer_puts_for_pressure(gpu_id, reason="REVISION3_FOREGROUND_SHRINK")
        if not pool.pending and (
            pool.policy.quota != quota
            or pool.occupied_bytes > max(0, quota - pool.policy.staging_bytes)
        ):
            pool.resize(quota, self.des.now_ns)
            self._sync_peer_hbm_ledger(gpu_id, cause="REVISION3_FOREGROUND_BUDGET")

    def _on_aimd_control_window(self, event, des):
        if self.system != "aegis":
            raise base.ExperimentError("non-Peer arm received a Peer control event")
        for gpu_id in self.gpu_ids:
            self._observe_budget(gpu_id)
        if len(self._completed_span_ids) < len(self.executions):
            self.des.schedule_after(50_000_000, EventKind.CONTROL_WINDOW)

    def _protection_chunks(self, execution, *, path):
        return execution.chunks

    def _scheduler_waits_for_store_materialization(self, gpu_id):
        # A destination reserved by an asynchronous GET is not a deadlock.
        # Its completion admits the restored request and wakes this GPU. Do
        # not swallow a no-progress condition without a concrete future owner.
        pending = any(
            group.target_gpu_id == gpu_id
            and (
                group.completed_transfer_ids != group.transfer_ids
                or group.completion_handle is not None
            )
            for group in self.foreground_store_restore_by_span.values()
        ) or any(
            r.pending_target_id == gpu_id and r.admission_handle is not None
            for r in self.continuous_batch_driver._requests.values()
        )
        if not pending:
            raise base.ExperimentError(
                f"unexplained scheduler stall: {gpu_id}; "
                f"accounts={self.hbm_ledgers[gpu_id].accounts}; "
                f"store_waiters={list(self.store_waiting)}"
            )
        return True

    def _new_continuous_bridge(self, gpu_id, authority):
        bridge = super()._new_continuous_bridge(gpu_id, authority)
        # Default of the pinned engine's vllm/config/scheduler.py. All three
        # systems use this gate before starting a new prefill or Store GET.
        bridge.scheduler.scheduler_reserve_full_isl = True
        bridge.scheduler.waiting_prefix_provider = (
            lambda request, budget: self.foreground_connector.prepare(gpu_id, request, budget)
        )
        return bridge

    def _schedule_compute(self, execution, *, gpu_id, ready_ns, duration_ns):
        if not self.continuous_batch_enabled or execution.route_version > 0:
            return super()._schedule_compute(
                execution, gpu_id=gpu_id, ready_ns=ready_ns, duration_ns=duration_ns
            )
        # Routing estimates cannot reserve or materialize a prefix before the
        # engine reaches this request. It will re-query on ordinary admission.
        self.primary_pools[gpu_id].release_pin(execution.metadata.span_id)
        primary, store = execution.reused_primary_tokens, execution.reused_store_tokens
        execution.reused_primary_tokens = execution.reused_store_tokens = 0
        try:
            return super()._schedule_compute(
                execution, gpu_id=gpu_id, ready_ns=ready_ns, duration_ns=duration_ns
            )
        finally:
            execution.reused_primary_tokens, execution.reused_store_tokens = primary, store

    def _store_progress_headroom(self):
        return base._tokens_to_allocated_bytes(self.parameters.policy_chunk_tokens)

    def _wake_store_waiters(self):
        if self.store_waiting and not self.store_retry_pending:
            self.store_retry_pending = True
            self.des.schedule_at(self.des.now_ns, EventKind.STORE_QUERY)

    def _record_continuous_hbm_commit(self, gpu_id, cause):
        super()._record_continuous_hbm_commit(gpu_id, cause)
        self._wake_store_waiters()

    def _commit_hbm_moves(self, gpu_id, moves, *, cause, **kwargs):
        result = super()._commit_hbm_moves(gpu_id, moves, cause=cause, **kwargs)
        if any(target == base.FREE_ACCOUNT for _, target, _ in moves):
            self._wake_store_waiters()
        return result

    def _start_foreground_store_restore(self, execution, *, gpu_id, duration_ns, route_estimate_ns):
        if execution.metadata.span_id not in self.foreground_connector.starting:
            return self._schedule_compute(
                execution, gpu_id=gpu_id, ready_ns=self.des.now_ns,
                duration_ns=duration_ns,
            )
        return super()._start_foreground_store_restore(
            execution, gpu_id=gpu_id, duration_ns=duration_ns,
            route_estimate_ns=route_estimate_ns,
        )

    def _retry_store_waiters(self, event, des):
        self.store_retry_pending = False
        for span_id, (gpu_id, duration, estimate) in tuple(self.store_waiting.items()):
            execution = self.executions[span_id]
            if gpu_id in self.failed_gpu_ids or execution.route_version > 0:
                continue
            available = self._store_lookup_prefix_tokens(
                execution.chunks, now_ns=des.now_ns, mutate_signals=False
            )
            available = base._source_chunk_page_aligned_prefix(
                execution.chunks, available, logical_page_tokens=16
            )
            execution.reused_store_tokens = max(0, available - execution.reused_primary_tokens)
            self.request_observations[span_id]["dram_hit_tokens"] = execution.reused_store_tokens
            duration = base._duration_after_prefix_reuse(
                execution.metadata,
                execution.base_duration_ns,
                execution.reused_primary_tokens + execution.reused_store_tokens,
            )
            if execution.reused_store_tokens == 0:
                del self.store_waiting[span_id]
                # Keep the already registered arrival/WCT origin. Cache loss
                # changes the amount of work, not when the request arrived;
                # admission must happen at this retry's current DES time.
                execution.scheduled_duration_ns = max(1, duration)
                self.continuous_batch_driver.schedule_registered_initial_admission(
                    request_id=span_id,
                    target_id=gpu_id,
                    ready_ns=des.now_ns,
                    restored_tokens=base._logical_page_aligned_prefix(
                        execution.reused_primary_tokens, logical_page_tokens=16
                    ),
                )
                self.store_wait_events.append(
                    {
                        "timestamp_ns": des.now_ns,
                        "span_id": span_id,
                        "event": "CACHE_EXPIRED_OR_EVICTED_RECOMPUTE",
                    }
                )
                continue
            layout = self._foreground_store_layout_by_segment(
                execution,
                start_token=execution.reused_primary_tokens,
                token_count=execution.reused_store_tokens,
            )
            needed = sum(x[0] for x in layout.values())
            if (
                self.hbm_ledgers[gpu_id].bytes_in(base.FREE_ACCOUNT)
                + self.primary_pools[gpu_id].evictable_bytes
                < needed + self._store_progress_headroom()
            ):
                continue
            del self.store_waiting[span_id]
            self.continuous_batch_driver.unregister_pristine_suspended(span_id)
            self._start_foreground_store_restore(
                execution, gpu_id=gpu_id, duration_ns=duration, route_estimate_ns=estimate
            )
            if span_id not in self.store_waiting:
                self.store_wait_events.append(
                    {"timestamp_ns": des.now_ns, "span_id": span_id, "event": "HBM_GRANTED"}
                )

    def _complete_runtime_protection(self, span_id):
        execution = self.executions[span_id]
        if execution.completed_ns is None:
            return
        for pool in (*self.store_pools.values(), *self.peer_pools.values()):
            if isinstance(pool, RevisionPool):
                pool.retire(span_id, self.des.now_ns)
            elif isinstance(pool, InstrumentedLRUPool):
                for chunk in execution.chunks:
                    if chunk.key in pool.entries:
                        pool.expirations[chunk.key] = (
                            self.des.now_ns + self.mechanism_config.retention_ns
                        )

    def _store_lookup_prefix_tokens(self, chunks, *, now_ns, mutate_signals):
        for pool in self.store_pools.values():
            if isinstance(pool, (RevisionPool, InstrumentedLRUPool)):
                pool.expire(now_ns)
        return super()._store_lookup_prefix_tokens(
            chunks, now_ns=now_ns, mutate_signals=mutate_signals
        )

    def _on_failure_inject(self, event, des):
        super()._on_failure_inject(event, des)
        for span_id, (gpu_id, _, _) in tuple(self.store_waiting.items()):
            if gpu_id in self.failed_gpu_ids:
                del self.store_waiting[span_id]
                self.store_wait_events.append(
                    {
                        "timestamp_ns": des.now_ns,
                        "span_id": span_id,
                        "event": "GPU_FAILURE_INTERRUPTED",
                    }
                )

    def _schedule_continuous_sealed_protection_puts(
        self,
        execution,
        *,
        source_gpu_id,
        computed_prompt_tokens_before,
        computed_prompt_tokens_after,
        step_start_ns,
        step_end_ns,
    ):
        chunks = tuple(
            c
            for c in execution.chunks
            if c.token_start + c.token_count <= computed_prompt_tokens_after
        )
        if not chunks:
            return
        for path in ("STORE_DRAM", "PEER_HBM"):
            if path == "PEER_HBM" and self.system != "aegis":
                continue
            target = execution.designated_peer_gpu_id if path == "PEER_HBM" else None
            if path == "PEER_HBM" and (target is None or target in self.failed_gpu_ids):
                continue
            plan_id = self._next_id(f"r3-sealed:{path}:{execution.metadata.span_id}")
            # Seals become readable after the atomic scheduler forward completes.
            produced_ns = step_end_ns
            handle = self.des.schedule_at(
                produced_ns, EventKind.PUT_START, event_id=plan_id, payload={"plan_id": plan_id}
            )
            self.pending_put_starts[plan_id] = base._PendingPutStart(
                plan_id,
                execution.metadata.span_id,
                path,
                source_gpu_id,
                target,
                "store-0:segment-0" if path == "STORE_DRAM" else None,
                chunks,
                handle,
                produced_ns,
            )

    def _pool_for_plan(self, plan):
        return (
            self.peer_pools[plan.target_gpu_id]
            if plan.path == "PEER_HBM"
            else self.store_pools[plan.target_store_id]
        )

    def _on_put_start(self, event, des):
        plan = self.pending_put_starts[event.payload["plan_id"]]
        execution = self.executions[plan.span_id]
        if (
            execution.status in {base._ExecutionStatus.FENCED, base._ExecutionStatus.COMPLETED}
            or plan.source_gpu_id in self.failed_gpu_ids
        ):
            del self.pending_put_starts[plan.plan_id]
            return
        if self.mechanism_config.cpu_service_ns and not event.payload.get("cpu_ready"):
            ready = self._reserve_cpu(
                plan.span_id, "admission", self.mechanism_config.cpu_service_ns
            )
            plan.handle = self.des.schedule_at(
                ready,
                EventKind.PUT_START,
                event_id=self._next_id("cpu-admission"),
                payload={"plan_id": plan.plan_id, "cpu_ready": True},
            )
            return
        pool = self._pool_for_plan(plan)
        if plan.path == "PEER_HBM":
            self._observe_budget(plan.target_gpu_id)
            if pool.policy.quota == 0:
                del self.pending_put_starts[plan.plan_id]
                return
        if isinstance(pool, (RevisionPool, InstrumentedLRUPool)):
            pool.context = plan
        if isinstance(pool, RevisionPool):
            pool.expire(self.des.now_ns)
            if plan.path == "PEER_HBM":
                # Expiration releases physical copies even if the subsequent
                # admission is rejected. Publish that release before any early
                # return in the inherited admission path.
                self._sync_peer_hbm_ledger(
                    plan.target_gpu_id, cause="REVISION3_PEER_RETENTION_TTL"
                )
            pool._sync_read_pins(self.des.now_ns)
        super()._on_put_start(event, des)

    def _on_put_commit(self, event, des):
        pending = self.pending_puts[event.payload["transfer_id"]]
        pool = self._pool_for_plan(pending)
        if isinstance(pool, RevisionPool):
            pool._sync_read_pins(self.des.now_ns)
            valid = all(
                pool.prepare_commit(r, self.des.now_ns) for r in pending.pool_reservation_ids
            )
            if not valid:
                for reservation_id in pending.pool_reservation_ids:
                    pool.abort_reservation(
                        reservation_id, now_ns=self.des.now_ns, cause="REVISION3_STALE_COPY_ABORT"
                    )
                self._abort_transfer_from_task(
                    pending.transfer_id, task=pending.task, reason="REVISION3_STALE_COPY_ABORT"
                )
                del self.pending_puts[pending.transfer_id]
                if pending.path == "PEER_HBM":
                    self._sync_peer_hbm_ledger(
                        pending.target_gpu_id, cause="REVISION3_STALE_COPY_ABORT"
                    )
                return
        super()._on_put_commit(event, des)

    def _on_release(self, metadata, des):
        if self.mechanism_config.foreground_cpu_service_ns:
            self.pending_releases[metadata.span_id] = (metadata, des.now_ns)
            ready = self._reserve_cpu(
                metadata.span_id,
                "foreground_lookup",
                self.mechanism_config.foreground_cpu_service_ns,
            )
            self.des.schedule_at(
                ready, EventKind.ROUTE_REQUEST, payload={"span_id": metadata.span_id}
            )
            return
        self._release_after_cpu(metadata, des, des.now_ns)

    def _reserve_cpu(self, span_id, operation, service_ns):
        start = max(self.des.now_ns, self.cpu_available_ns)
        finish = start + service_ns
        self.cpu_available_ns = finish
        self.cpu_queue.append(
            {
                "span_id": span_id,
                "operation": operation,
                "arrival_ns": self.des.now_ns,
                "start_ns": start,
                "end_ns": finish,
                "service_ns": service_ns,
                "queue_ns": start - self.des.now_ns,
            }
        )
        return finish

    def _on_cpu_release(self, event, des):
        metadata, arrival = self.pending_releases.pop(event.payload["span_id"])
        self._release_after_cpu(metadata, des, arrival)

    def _release_after_cpu(self, metadata, des, arrival):
        super()._on_release(metadata, des)
        execution = self.executions[metadata.span_id]
        execution.released_ns = arrival
        self.request_observations[metadata.span_id] = {
            "span_id": metadata.span_id,
            "workflow_id": metadata.workflow_id,
            "released_ns": execution.released_ns,
            "prompt_tokens": metadata.prompt_tokens,
            "local_hit_tokens": execution.reused_primary_tokens,
            "dram_hit_tokens": execution.reused_store_tokens,
            "peer_hit_tokens": execution.reused_peer_tokens,
            "source_gpu_id": execution.gpu_id,
        }

    def _on_continuous_step_completed(self, gpu_id, step, completion, completed_ns, snapshot):
        for span_id, position in completion.output_positions:
            times = self.token_emission_times.setdefault(span_id, [])
            if position > len(times):
                if position != len(times) + 1:
                    raise base.ExperimentError("output token observer skipped a position")
                times.append(completed_ns)
        super()._on_continuous_step_completed(gpu_id, step, completion, completed_ns, snapshot)

    def _continuous_reclaim(self, gpu_id, required_bytes):
        ledger = self.hbm_ledgers[gpu_id]
        before = ledger.bytes_in(base.FREE_ACCOUNT)
        self._observe_budget(gpu_id, required_bytes)
        result = super()._continuous_reclaim(gpu_id, required_bytes)
        self.allocation_observations.append(
            {
                "timestamp_ns": self.des.now_ns,
                "gpu_id": gpu_id,
                "requested_bytes": required_bytes,
                "free_before_bytes": before,
                "free_after_bytes": ledger.bytes_in(base.FREE_ACCOUNT),
                "succeeded": result,
                "active_requests": self._active_request_count(gpu_id),
            }
        )
        return result

    def _on_continuous_step_started(self, gpu_id, step, start_ns, planned_end_ns):
        for p in step.participants:
            row = self.request_observations.get(p.request_id)
            if row is not None:
                row.setdefault("first_compute_ns", start_ns)
        super()._on_continuous_step_started(gpu_id, step, start_ns, planned_end_ns)

    def run(self):
        self.continuous_batch_driver._on_blocked_step_callback = (
            self._scheduler_waits_for_store_materialization
        )
        if self.system == "aegis":
            self.des.schedule_at(0, EventKind.CONTROL_WINDOW)
        result = super().run()
        for detail in result.span_details:
            row = self.request_observations[detail["span_id"]]
            row["completed_ns"] = detail["completed_ns"]
            row["precompute_wait_ns"] = row["first_compute_ns"] - row["released_ns"]
            times = self.token_emission_times[detail["span_id"]]
            row["ttft_ns"] = times[0] - row["released_ns"]
            row["request_tpot_ns"] = (
                (times[-1] - times[0]) / (len(times) - 1) if len(times) > 1 else None
            )
        result.representative["mechanism"] = {
            "system": self.system,
            "label": SYSTEM_LABELS[self.system],
            "configuration": asdict(self.mechanism_config),
            "requests": list(self.request_observations.values()),
            "allocation_attempts": self.allocation_observations,
            "policy_cpu": self.policy_cpu,
            "cpu_queue": self.cpu_queue,
            "foreground_budget": self.budget_observations,
            "store_hbm_wait_events": self.store_wait_events,
            "foreground_connector_events": self.foreground_connector.events,
            "foreground_admission_semantics": "queue_owned_GET_and_preemption_relookup_v1",
            "token_emission_times_ns": self.token_emission_times,
            "cpu_scope": "local_python_policy_thread_cpu_time_not_native_serving_cpu",
            "reclaim_scope": "synchronous_fenced_DES_free_not_physical_ACK_latency",
        }
        return result


def mechanism_variant(system: str, parameters: base.ModelParameters):
    ids = {
        "mooncake": base.SystemId.VANILLA_MOONCAKE_DRAM,
        "dram": base.SystemId.AEGIS_DRAM_ONLY,
        "aegis": base.SystemId.AEGIS_UNIFIED,
    }
    profile = replace(
        base.SYSTEM_PROFILES[ids[system]],
        label=SYSTEM_LABELS[system],
        store_fraction=Fraction(1),
        peer_replication_fraction=Fraction(int(system == "aegis")),
        store_cache_reuse=True,
        peer_cache_reuse=system == "aegis",
        eviction=(
            base.EvictionKind.LRU if system == "mooncake" else base.EvictionKind.PREFIX_FRONTIER
        ),
        unified_manager=False,
        aimd_enabled=False,
        cache_aware_routing=False,
    )
    return base.ExperimentVariant(
        "mechanism-v3",
        system,
        profile,
        parameters,
        interpretation="revision3_adapter_modeled_exploration",
    )
