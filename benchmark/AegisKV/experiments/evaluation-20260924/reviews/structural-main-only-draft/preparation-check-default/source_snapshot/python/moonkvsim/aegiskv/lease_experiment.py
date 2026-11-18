"""Agent-sublease Algorithm 2 and independent windowed Algorithm 3 in GlobalDES.

The adapter shares foreground scheduling, routing, byte ledgers and transfer
resources with Mooncake. Release is synchronously fenced in this DES. Physical
DMA/free acknowledgement latency requires the separate native microbenchmark.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from fractions import Fraction
from functools import wraps
from time import thread_time_ns

from moonkvsim.aegiskv import experiment as base
from moonkvsim.aegiskv.agent_lease import AgentLeasePolicy
from moonkvsim.aegiskv.guarded_aimd import AIMDObservation, GuardedAIMD
from moonkvsim.aegiskv.lease_value import (
    RecoveryAgent,
    RecoveryNode,
    WorkflowRecoveryValue,
    execution_branches,
)
from moonkvsim.aegiskv.mechanism_experiment import (
    InstrumentedLRUPool,
    MechanismConfig,
    MechanismRuntime,
    RevisionPool,
)
from moonkvsim.simulation.event import EventKind


def measured_pool(operation):
    """Exclusive Python thread CPU; nested measured calls are not counted twice."""

    def decorate(method):
        @wraps(method)
        def wrapped(self, *args, **kwargs):
            rows = self.runtime.policy_cpu
            first, start = len(rows), thread_time_ns()
            span = "__controller__"
            if operation == "copy_commit":
                rid = args[0] if args else kwargs["reservation_id"]
                if hasattr(self, "copy_transactions"):
                    span = self.copy_transactions[rid][1]
                else:
                    span = self.copy_owners.pop(rid)
            try:
                return method(self, *args, **kwargs)
            finally:
                elapsed = max(0, thread_time_ns() - start - sum(x["cpu_ns"] for x in rows[first:]))
                rows.append(
                    {
                        "timestamp_ns": self.runtime.des.now_ns,
                        "span_id": span,
                        "pool_id": self.pool_id,
                        "operation": operation,
                        "cpu_ns": elapsed,
                        "resident_objects": len(self.entries),
                        "consumers": 0,
                        "source_objects": 0,
                        "accepted": False,
                    }
                )

        return wrapped

    return decorate


@dataclass(frozen=True)
class LeaseConfig(MechanismConfig):
    source_version: str = "agent-subleases-tail-rent-guarded-aimd-20260908"
    peer_mode: str = "guarded"
    eager_refresh: bool = False
    strict_free_gain: bool = False
    static_peer: bool = False
    additive_bytes: int = 1024**3
    stable_windows: int = 4
    window_ns: int = 50_000_000
    warning_threshold: float = 0.05
    # Optional measured-microbenchmark coefficient; otherwise zero is an
    # explicit omitted-contention assumption, never a zero-overhead result.
    dma_slowdown: float = 0.0


class ChunkLRUPool(InstrumentedLRUPool):
    """Same sealed-chunk copy granularity in all three systems."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.copy_owners = {}

    def reserve(self, reservation_id, chunks, scores, *, now_ns, cause):
        for chunk, score in zip(chunks, scores, strict=True):
            if chunk.key not in self.entries and chunk.key not in self._pending_keys:
                result = super().reserve(
                    reservation_id, (chunk,), (score,), now_ns=now_ns, cause=cause
                )
                if result is not None:
                    self.copy_owners[reservation_id] = self.context.span_id
                return result
        self.last_reserve_outcome = "ALIAS_ONLY"
        return None

    @measured_pool("copy_commit")
    def commit_reservation(self, *args, **kwargs):
        return super().commit_reservation(*args, **kwargs)


class AgentLeasePool(RevisionPool):
    def __init__(self, *, runtime, original):
        base._ModeledPool.__init__(
            self,
            pool_id=original.pool_id,
            capacity_bytes=original.capacity_bytes,
            physical_capacity_bytes=original.physical_capacity_bytes,
            eviction=base.EvictionKind.LRU,
            seed=original.seed,
        )
        self.runtime = runtime
        self.policy = AgentLeasePolicy(
            original.capacity_bytes,
            eager_refresh=runtime.mechanism_config.eager_refresh,
            strict_free_gain=runtime.mechanism_config.strict_free_gain,
        )
        self.context = None
        self.copy_transactions = {}
        self.commit_outcomes = {}
        self.events = []
        self.registered = set()
        self.blocked_rounds = set()
        self.expires = {}

    def register(self, execution):
        span = execution.metadata.span_id
        if span in self.registered:
            return
        parent = None
        for chunk in execution.chunks:
            self.policy.register(chunk.key, parent, chunk.bytes)
            parent = chunk.key
        self.registered.add(span)

    def retire(self, span_id, now_ns):
        # Request completion does not end an Agent or replenish another one's
        # credits. Its last known references survive until its next round/end.
        for chunk in self.runtime.executions[span_id].chunks:
            self.expires[chunk.key] = now_ns + self.runtime.mechanism_config.retention_ns

    def _sync_read_pins(self, now_ns):
        pass  # The physical transfer layer is the single reader-pin owner.

    def _pins(self):
        pins = set(self.pinned_entry_keys)
        for key in self._pending_keys:
            pins.update(self.policy.ancestors(key))
        return pins

    def reserve(self, reservation_id, chunks, scores, *, now_ns, cause):
        context = self.context
        execution = self.runtime.executions[context.span_id]
        self.register(execution)
        if (context.span_id, execution.route_version) in self.blocked_rounds:
            self.last_reserve_outcome = "AGENT_LEASE_BLOCKED_SUFFIX"
            return None
        selected = next((c for c in chunks if c.key not in self.entries), None)
        if selected is None:
            self.last_reserve_outcome = "ALIAS_ONLY"
            return None
        if selected.key in self._pending_keys:
            self.last_reserve_outcome = "WAIT_FOR_PREFIX_COPY_ACK"
            return None
        start = thread_time_ns()
        values = self.runtime.recovery_values(self)
        plan = self.policy.plan(
            selected.key, values, pinned=self._pins(), pending_bytes=self.pending_bytes
        )
        elapsed = thread_time_ns() - start
        self.runtime.policy_cpu.append(
            {
                "timestamp_ns": now_ns,
                "span_id": context.span_id,
                "pool_id": self.pool_id,
                "operation": "agent_sublease_admission",
                "cpu_ns": elapsed,
                "resident_objects": len(self.entries),
                "consumers": len(values.agents),
                "source_objects": len(chunks),
                "accepted": plan.status in {"ADMIT", "REPLACE"},
                "tail_checks": plan.checks,
                "refresh_evaluations": plan.evaluations,
                "dag_evaluations": values.evaluations,
            }
        )
        self.events.append(
            {
                "timestamp_ns": now_ns,
                "span_id": context.span_id,
                "pool_id": self.pool_id,
                "chunk_key": selected.key,
                "status": plan.status,
                "gain_ms": plan.gain_ms,
                "loss_ms": plan.loss_ms,
                "victims": list(plan.victims),
                "tail_checks": plan.checks,
                "refresh_evaluations": plan.evaluations,
                "rent": plan.rent,
                "produced_tokens": self.runtime.produced.get(context.span_id, 0),
            }
        )
        if plan.status not in {"ADMIT", "REPLACE"}:
            if plan.status == "BYPASS":
                self.blocked_rounds.add((context.span_id, execution.route_version))
            self.last_reserve_outcome = plan.status
            return None
        # Victims are unpinned and frees are fenced before destination reserve.
        result = base._ModeledPool.reserve_exact(
            self,
            reservation_id,
            selected,
            score=Fraction(plan.gain_ms),
            victim_keys=plan.victims,
            proposed_rent=Fraction(plan.rent),
            now_ns=now_ns,
            cause=cause,
        )
        self.policy.apply_releases(plan)
        self.copy_transactions[reservation_id] = (
            selected.key,
            context.span_id,
            execution.route_version,
        )
        self.check_revision()
        return result

    def prepare_commit(self, reservation_id, now_ns):
        key, span, epoch = self.copy_transactions[reservation_id]
        execution = self.runtime.executions[span]
        valid = (
            execution.route_version == epoch and execution.gpu_id not in self.runtime.failed_gpu_ids
        )
        valid = valid and self.policy.ancestors(key) <= self.policy.committed
        self.commit_outcomes[reservation_id] = valid
        return valid

    @measured_pool("copy_commit")
    def commit_reservation(self, reservation_id, *, now_ns, cause):
        if not self.commit_outcomes.pop(reservation_id, False):
            raise base.ExperimentError(
                "Agent lease commit lacks source-epoch and prefix validation"
            )
        key, _, _ = self.copy_transactions.pop(reservation_id)
        values = self.runtime.recovery_values(self)
        result = base._ModeledPool.commit_reservation(
            self, reservation_id, now_ns=now_ns, cause=cause
        )
        self.policy.commit(key, values)
        self.check_revision()
        return result

    def abort_reservation(self, reservation_id, *, now_ns, cause):
        self.copy_transactions.pop(reservation_id)
        self.commit_outcomes.pop(reservation_id, None)
        result = base._ModeledPool.abort_reservation(
            self, reservation_id, now_ns=now_ns, cause=cause
        )
        self.check_revision()
        return result

    @measured_pool("tail_reclaim")
    def _reclaim(self, target, physical_capacity, now_ns, cause):
        if self.occupied_bytes <= target:
            base._ModeledPool.set_capacity_exact(
                self,
                max(physical_capacity, self.occupied_bytes + self.pending_bytes),
                victim_keys=(),
                proposed_rent=self.rent,
                now_ns=now_ns,
                cause=cause,
            )
            return 0
        values = self.runtime.recovery_values(self)
        plan = self.policy.reclaim(target, values, pinned=self._pins())
        if plan.status != "RECLAIM":
            return 0
        old = self.occupied_bytes
        base._ModeledPool.set_capacity_exact(
            self,
            max(
                physical_capacity,
                self.occupied_bytes
                - sum(self.policy.sizes[k] for k in plan.victims)
                + self.pending_bytes,
            ),
            victim_keys=plan.victims,
            proposed_rent=Fraction(plan.rent),
            now_ns=now_ns,
            cause=cause,
        )
        self.policy.apply_releases(plan)
        self.check_revision()
        return old - self.occupied_bytes

    def resize(self, quota, now_ns):
        self.policy.quota = quota
        self._reclaim(
            max(0, quota - self.pending_bytes), quota, now_ns, "AGENT_LEASE_MEMORY_CEILING"
        )

    def evict_at_least(self, required_bytes, *, now_ns, cause):
        return self._reclaim(
            max(0, self.occupied_bytes - required_bytes), self.capacity_bytes, now_ns, cause
        )

    def expire(self, now_ns):
        if self.failed:
            return
        # Expire only a releasable tail; repeat when an internal block becomes
        # a tail. Never create a prefix hole or free an in-flight reader.
        victims = []
        draft = set(self.entries)
        while True:
            expired = [
                k
                for k in self.policy.tails(draft, self._pins())
                if self.expires.get(k, 10**30) <= now_ns
            ]
            if not expired:
                break
            victims.extend(expired)
            draft.difference_update(expired)
        if victims:
            base._ModeledPool.set_capacity_exact(
                self,
                self.capacity_bytes,
                victim_keys=tuple(victims),
                proposed_rent=self.rent,
                now_ns=now_ns,
                cause="AGENT_LEASE_RETENTION_TTL",
            )
            for k in victims:
                self.policy.committed.remove(k)
                del self.policy.credits[k]
                self.expires.pop(k, None)
            self.policy.version += 1

    def fail(self, *, now_ns, cause):
        result = base._ModeledPool.fail(self, now_ns=now_ns, cause=cause)
        self.policy.committed.clear()
        self.policy.credits.clear()
        self.policy.version += 1
        self.copy_transactions.clear()
        self.commit_outcomes.clear()
        return result

    def check_revision(self):
        self.policy.check()
        if set(self.entries) != self.policy.committed:
            raise base.ExperimentError("Agent lease and physical directory disagree")
        if self.occupied_bytes != self.policy.nbytes(self.policy.committed):
            raise base.ExperimentError("shared physical capacity counted more than once")


class LeaseRuntime(MechanismRuntime):
    protection_pool_class = AgentLeasePool
    baseline_pool_class = ChunkLRUPool

    def __init__(self, *, mechanism_config=LeaseConfig(), **kwargs):
        self.produced = {}
        self.agent_rounds = Counter()
        self.agent_current = {}
        self.span_agent = {}
        self.backlogs = {}
        self.backlog_queued = set()
        self.feedback = defaultdict(list)
        self.step_contention = []
        self.inflight_steps = {}
        self.lease_lifecycle = []
        self.flow_pressure = Counter()
        self.workflow_nodes = {}
        super().__init__(mechanism_config=mechanism_config, **kwargs)
        self.workflow_nodes = {}
        by_workflow = defaultdict(dict)
        for execution in self.executions.values():
            m = execution.metadata
            by_workflow[m.workflow_id][m.span_id] = RecoveryNode(
                m.span_id,
                tuple(execution.record["parent_span_ids"]),
                max(1, m.recorded_api_time_ns) / 1e6,
            )
        for workflow, nodes in by_workflow.items():
            result, seen = [], set()
            while len(result) < len(nodes):
                ready = sorted(
                    k for k, n in nodes.items() if k not in seen and set(n.parents) <= seen
                )
                if not ready:
                    raise ValueError("workflow DAG has a cycle or missing parent")
                for k in ready:
                    result.append(nodes[k])
                    seen.add(k)
            self.workflow_nodes[workflow] = tuple(result)
        self.span_branch = execution_branches(
            self.workflow_nodes, {span: e.record["agent_id"] for span, e in self.executions.items()}
        )
        if self.system == "aegis":
            for gpu, pool in self.peer_pools.items():
                self.governors[gpu] = GuardedAIMD(
                    denominator_bytes=self.parameters.kv_capacity_bytes_per_gpu,
                    policy_cap_bytes=self.parameters.peer_hbm_quota_bytes_per_gpu,
                    additive_bytes=mechanism_config.additive_bytes,
                    stable_windows=mechanism_config.stable_windows,
                    window_ns=mechanism_config.window_ns,
                )
                pool.resize(0, 0)
        self._install_contention_model()

    def recovery_values(self, pool):
        agents = []
        for aid, span in self.agent_current.items():
            e = self.executions[span]
            if e.completed_ns is not None or e.gpu_id is None:
                continue
            produced = self.produced.get(span, 0)
            m = e.metadata
            weighted = m.prompt_tokens + 8 * max(0, m.output_tokens - 1)
            agents.append(
                RecoveryAgent(
                    aid,
                    m.workflow_id,
                    span,
                    self.agent_rounds[aid],
                    e.gpu_id,
                    tuple(c.key for c in e.chunks),
                    tuple(c.token_start + c.token_count for c in e.chunks),
                    tuple(c.bytes for c in e.chunks),
                    produced,
                    m.prompt_tokens,
                    max(1, m.recorded_api_time_ns) / 1e6 / max(1, weighted),
                    e.route_version,
                )
            )
        peer_gpu = next((g for g, p in self.peer_pools.items() if p is pool), None)
        rate = (
            self.parameters.peer_bandwidth_bytes_per_second
            if peer_gpu
            else self.parameters.store_bandwidth_bytes_per_second
        )
        return WorkflowRecoveryValue(
            agents=agents,
            workflows=self.workflow_nodes,
            gpu_ids=self.gpu_ids,
            target_gpu=peer_gpu,
            rate=rate,
            setup_ms=self.parameters.transfer_setup_ns / 1e6,
            dag_enabled=self.mechanism_config.slack_enabled,
        )

    def _release_after_cpu(self, metadata, des, arrival):
        cpu_start = thread_time_ns()
        first_cpu_row = len(self.policy_cpu)
        e = self.executions[metadata.span_id]
        aid = (
            metadata.workflow_id
            + ":"
            + e.record["agent_id"]
            + ":branch-"
            + str(self.span_branch[metadata.span_id])
        )
        previous = self.agent_current.get(aid)
        if previous is not None and self.executions[previous].completed_ns is None:
            # A trace with simultaneous requests from one logical Agent needs
            # explicit branch identity; silently overwriting would lose value.
            raise base.ExperimentError("overlapping Agent requests lack separate branch identity")
        self.agent_rounds[aid] += 1
        self.agent_current[aid] = metadata.span_id
        self.span_agent[metadata.span_id] = aid
        self.lease_lifecycle.append(
            {
                "timestamp_ns": des.now_ns,
                "agent": aid,
                "span_id": metadata.span_id,
                "round": self.agent_rounds[aid],
                "original_agent_id": e.record["agent_id"],
                "branch": self.span_branch[metadata.span_id],
                "event": "REQUEST_RELEASE",
            }
        )
        super()._release_after_cpu(metadata, des, arrival)
        self.produced[metadata.span_id] = (
            e.reused_primary_tokens + e.reused_store_tokens + e.reused_peer_tokens
        )
        for pool in (*self.store_pools.values(), *self.peer_pools.values()):
            if isinstance(pool, AgentLeasePool):
                pool.register(e)
        self.policy_cpu.append(
            {
                "timestamp_ns": des.now_ns,
                "span_id": metadata.span_id,
                "pool_id": "FOREGROUND",
                "operation": "foreground_dispatch",
                "cpu_ns": max(
                    0,
                    thread_time_ns()
                    - cpu_start
                    - sum(x["cpu_ns"] for x in self.policy_cpu[first_cpu_row:]),
                ),
                "resident_objects": 0,
                "consumers": len(self.agent_current),
                "source_objects": len(e.chunks),
                "accepted": True,
            }
        )

    def _on_continuous_step_completed(self, gpu_id, step, completion, completed_ns, snapshot):
        quote = self.inflight_steps.pop(gpu_id, None)
        if quote is not None:
            # Observations become available after completion, not prediction.
            self.feedback[gpu_id].append(
                quote["normalized_excess"] if quote["peer_active"] else 0.0
            )
        for p in step.participants:
            self.produced[p.request_id] = max(
                self.produced.get(p.request_id, 0), p.num_computed_tokens_after
            )
        super()._on_continuous_step_completed(gpu_id, step, completion, completed_ns, snapshot)
        # Reads have finished before a hit-tail may enter rent competition.
        for p in step.participants:
            e = self.executions[p.request_id]
            if e.reused_store_tokens and p.request_id not in self.hit_refreshed:
                for pool in self.store_pools.values():
                    if isinstance(pool, AgentLeasePool):
                        pool.policy.refresh_hit(
                            {c.key for c in e.chunks if c.token_start < e.reused_store_tokens},
                            self.recovery_values(pool),
                            pinned=pool._pins(),
                        )
                # _SpanExecution uses slots; keep instrumentation outside it.
                self.hit_refreshed.add(p.request_id)

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
            key = (execution.metadata.span_id, path, execution.route_version)
            self.backlogs[key] = (
                source_gpu_id,
                execution.designated_peer_gpu_id if path == "PEER_HBM" else None,
                chunks,
                step_end_ns,
            )
            self._queue_backlog(key, step_end_ns)

    def _queue_backlog(self, key, at):
        if key in self.backlog_queued or key not in self.backlogs:
            return
        span, path, epoch = key
        e = self.executions[span]
        source, target, chunks, sealed = self.backlogs[key]
        if e.completed_ns is not None or e.route_version != epoch or source in self.failed_gpu_ids:
            return
        if path == "PEER_HBM" and (target is None or target in self.failed_gpu_ids):
            return
        pool = self.peer_pools[target] if target else self.store_pools["store-0:segment-0"]
        if isinstance(pool, AgentLeasePool) and (span, epoch) in pool.blocked_rounds:
            return
        # Keep one outstanding source-path decision; ACK drains remaining
        # sealed chunks instead of waiting for an unrelated future GPU step.
        if any(p.span_id == span and p.path == path for p in self.pending_puts.values()):
            return
        missing = next((c for c in chunks if c.key not in pool.entries), None)
        if missing is None or missing.key in pool._pending_keys:
            return
        plan_id = self._next_id("agent-lease-sealed")
        produced = max(at, sealed, self.des.now_ns)
        handle = self.des.schedule_at(
            produced,
            EventKind.PUT_START,
            event_id=plan_id,
            payload={"plan_id": plan_id, "lease_backlog": key},
        )
        self.pending_put_starts[plan_id] = base._PendingPutStart(
            plan_id,
            span,
            path,
            source,
            target,
            "store-0:segment-0" if path == "STORE_DRAM" else None,
            chunks,
            handle,
            produced,
        )
        self.backlog_queued.add(key)

    def _on_put_start(self, event, des):
        plan = self.pending_put_starts.get(event.payload["plan_id"])
        if plan is None:
            return
        e = self.executions[plan.span_id]
        self.produced[plan.span_id] = max(
            self.produced.get(plan.span_id, 0),
            max((c.token_start + c.token_count for c in plan.chunks), default=0),
        )
        key = (plan.span_id, plan.path, e.route_version)
        super()._on_put_start(event, des)
        if plan.plan_id not in self.pending_put_starts:
            self.backlog_queued.discard(key)

    def _on_put_commit(self, event, des):
        pending = self.pending_puts.get(event.payload["transfer_id"])
        super()._on_put_commit(event, des)
        if pending is not None:
            # Shared alias waiters also become eligible after this copy ACK.
            for key in tuple(self.backlogs):
                if key[1] == pending.path:
                    self._queue_backlog(key, des.now_ns)

    def _memory_cap(self, gpu, next_primary_bytes=0):
        pool = self.peer_pools[gpu]
        ledger = self.hbm_ledgers[gpu]
        physical = pool.occupied_bytes + pool.pending_bytes
        free = ledger.bytes_in(base.FREE_ACCOUNT)
        reserve = self.mechanism_config.foreground_reserve_bytes + next_primary_bytes
        return max(0, min(self.parameters.peer_hbm_quota_bytes_per_gpu, free + physical - reserve))

    def _apply_quota(self, gpu, quota, reason):
        pool = self.peer_pools[gpu]
        if quota < pool.occupied_bytes + pool.pending_bytes:
            self._abort_pending_peer_puts_for_pressure(gpu, reason=reason)
        if not pool.pending and (pool.policy.quota != quota or pool.occupied_bytes > quota):
            pool.resize(quota, self.des.now_ns)
            self._sync_peer_hbm_ledger(gpu, cause=reason)

    def _observe_budget(self, gpu_id, next_primary_bytes=0):
        if self.system != "aegis" or gpu_id in self.failed_gpu_ids:
            return
        governor = self.governors[gpu_id]
        if not isinstance(governor, GuardedAIMD):
            return
        cap = self._memory_cap(gpu_id, next_primary_bytes)
        quota = cap if self.mechanism_config.static_peer else governor.clip_for_foreground(cap)
        self._apply_quota(gpu_id, quota, "ALGORITHM3_FOREGROUND_MEMORY_CLIP")

    def _on_aimd_control_window(self, event, des):
        for gpu, pool in self.peer_pools.items():
            if gpu in self.failed_gpu_ids:
                continue
            cpu_start = thread_time_ns()
            first_cpu_row = len(self.policy_cpu)
            samples = self.feedback.pop(gpu, [])
            self.budget_sequence[gpu] += 1
            cap = self._memory_cap(gpu)
            physical = pool.occupied_bytes + pool.pending_bytes
            governor = self.governors[gpu]
            demand = any(
                e.completed_ns is None
                and e.released_ns is not None
                and e.designated_peer_gpu_id == gpu
                for e in self.executions.values()
            )
            inflight = self.inflight_steps.get(gpu)
            if inflight and inflight["peer_active"]:
                elapsed = des.now_ns - inflight["timestamp_ns"]
                samples.append(max(0.0, elapsed / inflight["baseline_ns"] - 1.0))
            # The DES telemetry collector emits a live heartbeat even when the
            # foreground is idle. No completed step is not a missing sensor.
            # Sensor loss is separately tested at the pure controller boundary.
            obs = AIMDObservation(
                self.budget_sequence[gpu],
                des.now_ns,
                cap,
                physical,
                max(0, physical - governor.quota),
                any(x > self.mechanism_config.warning_threshold for x in samples),
                True,
                demand,
                physical <= governor.quota,
            )
            decision = governor.observe(obs)
            quota = cap if self.mechanism_config.static_peer else decision.quota_bytes
            self._apply_quota(gpu, quota, "ALGORITHM3_WINDOW_" + decision.reason)
            self.budget_observations.append(
                {
                    "timestamp_ns": des.now_ns,
                    "gpu_id": gpu,
                    "decision": asdict(decision),
                    "applied_quota_bytes": quota,
                    "applied_reason": "STATIC_MEMORY_CAP_ABLATION"
                    if self.mechanism_config.static_peer
                    else decision.reason,
                    "observation": asdict(obs),
                    "normalized_step_excess": max(samples, default=None),
                    "physical_backup_bytes": pool.occupied_bytes + pool.pending_bytes,
                }
            )
            self.policy_cpu.append(
                {
                    "timestamp_ns": des.now_ns,
                    "span_id": "__controller__",
                    "pool_id": pool.pool_id,
                    "operation": "guarded_aimd_window",
                    "cpu_ns": max(
                        0,
                        thread_time_ns()
                        - cpu_start
                        - sum(x["cpu_ns"] for x in self.policy_cpu[first_cpu_row:]),
                    ),
                    "resident_objects": len(pool.entries),
                    "consumers": len(self.agent_current),
                    "source_objects": 0,
                    "accepted": False,
                }
            )
        for key in tuple(self.backlogs):
            if key[1] == "PEER_HBM":
                self._queue_backlog(key, des.now_ns)
        if len(self._completed_span_ids) < len(self.executions):
            des.schedule_after(self.mechanism_config.window_ns, EventKind.CONTROL_WINDOW)

    def _install_contention_model(self):
        self.hit_refreshed = set()
        for gpu, target in self.continuous_batch_driver._targets.items():
            provider = target.bridge.duration_provider
            original = provider.predict_step_duration_ns

            def predict(step, *, original=original, gpu=gpu):
                baseline = original(step)
                dma = any(
                    p.started and gpu in {p.source_gpu_id, p.target_gpu_id}
                    for p in self.pending_puts.values()
                )
                peer = any(
                    p.started and p.path == "PEER_HBM" and gpu in {p.source_gpu_id, p.target_gpu_id}
                    for p in self.pending_puts.values()
                )
                excess = self.mechanism_config.dma_slowdown if dma else 0.0
                duration = max(1, round(baseline * (1 + excess)))
                row = {
                    "timestamp_ns": self.des.now_ns,
                    "gpu_id": gpu,
                    "baseline_ns": baseline,
                    "duration_ns": duration,
                    "dma_active": dma,
                    "peer_active": peer,
                    "normalized_excess": excess,
                }
                self.step_contention.append(row)
                self.inflight_steps[gpu] = row
                return duration

            provider.predict_step_duration_ns = predict

    def run(self):
        result = super().run()
        m = result.representative["mechanism"]
        m["agent_lease_events"] = [
            event
            for pool in (*self.store_pools.values(), *self.peer_pools.values())
            if isinstance(pool, AgentLeasePool)
            for event in pool.events
        ]
        m["agent_lifecycle"] = self.lease_lifecycle
        m["step_contention"] = self.step_contention
        m["algorithm_contract"] = {
            "algorithm2": "single_chunk_agent_subleases_tail_only_rent_joint_DAG_WCT",
            "algorithm3": "independent_guarded_AIMD_memory_cap_and_normalized_step_warning",
            "free_capacity_gate": "G>=0",
            "replacement_gate": "G>D",
            "failure_value_prior": "uniform_single_GPU_failure_independent_of_injected_case",
            "recovery_endpoint": "already_generated_KV_no_unknown_future_suffix",
            "predictor": "observed_trace_prefill1_decode8_estimator_not_trained_GBDT",
            "cpu": "Python_policy_measurement_and_frozen_service_quote",
            "hardware_contention": "explicit_coefficient_sensitivity_not_native_end_to_end",
        }
        for pool in (*self.store_pools.values(), *self.peer_pools.values()):
            if isinstance(pool, AgentLeasePool):
                pool.check_revision()
        return result
