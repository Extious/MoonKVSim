"""Current AegisKV on MoonKVSim's shared clock, flow model and byte ledgers.

The foreground model is FCFS per DP/TP worker, with token-batched forwards and
explicit layer recovery. It is NOT the legacy vLLM continuous-batching adapter.
All costs are configured assumptions; no GPU code executes here.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from math import ceil

from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.simulation.flow_des import FlowDESController
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.network import ActiveFlow, FlowContentionModel
from moonkvsim.simulation.resource import RateResource
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction

from . import DESIGN_VERSION
from .model import Agent, Config, Failure
from .policy import Adapter, demand, top_blocks
from .tracker import Context, Predictor, Tracker, prior_predictor

Block = tuple[int, int]


@dataclass
class Checkpoint:
    key: str
    identity: int
    source: int
    peer: int
    frontier: int = 0
    pending: bool = False
    hbm: set[Block] = field(default_factory=set)
    pending_hot: dict[Block, str] = field(default_factory=dict)
    desired_hot: set[Block] = field(default_factory=set)
    readers: int = 0
    retired: bool = False

    @property
    def account(self) -> str:
        return f"replica:{self.identity}"


@dataclass
class State:
    spec: Agent
    call: int = -1
    worker: int | None = None
    peer: int | None = None
    computed: int = 0
    durable: int = 0
    primary_tokens: tuple[int, ...] = ()
    model_layout: tuple[str, str] = ("", "")
    epoch: int = 0
    started: int | None = None
    submitted: int = 0
    finished: int | None = None
    durations: list[int] = field(default_factory=list)
    outputs: list[int] = field(default_factory=list)
    counts: Counter[Block] = field(default_factory=Counter)
    checkpoint: Checkpoint | None = None
    recovering: Checkpoint | None = None
    available: set[Block] = field(default_factory=set)
    loading: set[Block] = field(default_factory=set)
    load_queue: deque[tuple[Block, ...]] = field(default_factory=deque)
    load_active: bool = False
    waiting: Callable[[], None] | None = None
    compute_event: EventHandle | None = None
    recovering_since: int | None = None
    recovery_row: dict | None = None

    @property
    def invocation(self):
        return self.spec.calls[self.call]


@dataclass
class CopyGroup:
    owner: str
    source: int | None
    target: int
    host: int | None
    remaining: set[str]
    done: Callable[[], None]
    canceled: bool = False


class CurrentRuntime:
    def __init__(
        self,
        config: Config,
        agents: tuple[Agent, ...],
        *,
        policy: str = "aegiskv",
        failure: Failure | None = None,
        predictor: Predictor = prior_predictor,
    ):
        if policy not in {"none", "dram", "aegiskv", "all_dram", "static_hbm"}:
            raise ValueError("unknown current-design policy")
        self.config, self.policy, self.failure, self.predictor = config, policy, failure, predictor
        self.des = GlobalDES()
        self.tracker = Tracker(agents, config)
        if set(getattr(predictor, "training_workflows", ())) & {a.workflow for a in agents}:
            raise ValueError("predictor training/evaluation workflows overlap")
        self.states = {a.key: State(a) for a in agents}
        if not agents:
            raise ValueError("workload is empty")
        if failure and (
            failure.agent not in self.states
            or failure.invocation >= len(self.states[failure.agent].spec.calls)
        ):
            raise ValueError("failure target is absent from workload")
        self.alive = set(range(len(config.hosts)))
        self.busy: dict[int, str | None] = dict.fromkeys(self.alive)
        self.queues: dict[int, deque[str]] = {w: deque() for w in self.alive}
        self.adapters = {
            (w, r): Adapter(config, config.initial_quota_bytes)
            for w in self.alive
            for r in range(config.tp)
        }
        self.pressure: set[int] = set()
        self.deferred: set[int] = set()
        self.ledgers: dict[str, CapacityLedger] = {}
        for host in sorted(set(config.hosts)):
            name = f"dram:{host}"
            self.ledgers[name] = CapacityLedger(
                resource_id=name,
                resource_kind=CapacityResourceKind.HOST_DRAM,
                capacity_bytes=config.dram_bytes_per_host,
            )
        rates = [RateResource("fabric", config.network_bytes_per_second)]
        for host in sorted(set(config.hosts)):
            rates.extend(
                [
                    RateResource(f"nic:{host}", config.network_bytes_per_second),
                    RateResource(f"dram-bw:{host}", config.dram_bytes_per_second),
                ]
            )
        for w in self.alive:
            for r in range(config.tp):
                name = f"hbm:{w}:{r}"
                self.ledgers[name] = CapacityLedger(
                    resource_id=name,
                    resource_kind=CapacityResourceKind.GPU_HBM,
                    capacity_bytes=config.hbm_bytes_per_rank,
                )
                rates.extend(
                    [
                        RateResource(f"h2d:{w}:{r}", config.h2d_bytes_per_second),
                        RateResource(f"d2h:{w}:{r}", config.d2h_bytes_per_second),
                    ]
                )
        self.flow_model = FlowContentionModel(rates)
        self.flows = FlowDESController(des=self.des, model=self.flow_model)
        self.groups: dict[str, CopyGroup] = {}
        self.checkpoints: list[Checkpoint] = []
        self.sequence = 0
        self.events: list[dict] = []
        self.recoveries: list[dict] = []
        self.requests: list[dict] = []
        self.metrics: Counter = Counter()
        self.peaks: Counter = Counter()
        self._usage_time = 0
        self._usage: Counter = Counter()
        self.fault_fired = False
        self.failure_record: dict | None = None
        self._callbacks: dict[str, Callable[[], None]] = {}
        self._rebalancing = False
        for kind in (
            EventKind.REQUEST_ARRIVAL,
            EventKind.FORWARD_COMPLETE,
            EventKind.CONTROL_WINDOW,
            EventKind.FAILURE_INJECT,
            EventKind.RECOVERY_START,
            EventKind.DIRECTORY_PUBLISH,
        ):
            self.des.register_handler(kind, self._dispatch)
        self.des.register_invariant("current-design-capacity-and-frontier", self._invariants)
        for state in self.states.values():
            if not state.spec.predecessors:
                self._at(
                    state.spec.release_ns,
                    EventKind.REQUEST_ARRIVAL,
                    lambda s=state: self._submit(s),
                )
        self._at(config.control_window_ns, EventKind.CONTROL_WINDOW, self._control)

    def _id(self, prefix: str) -> str:
        self.sequence += 1
        return f"{prefix}:{self.sequence}"

    def _at(self, time: int, kind: EventKind, callback: Callable[[], None]) -> EventHandle:
        identity = self._id(kind.value)
        self._callbacks[identity] = callback
        return self.des.schedule_at(time, kind, event_id=identity)

    def _dispatch(self, event: ScheduledEvent, _des: GlobalDES) -> None:
        self._callbacks.pop(event.event_id)()

    def _record(self, kind: str, **data) -> None:
        self.events.append({"time_ns": self.des.now_ns, "kind": kind, **data})

    def _move(self, changes: list[tuple[str, str, str, int]], cause: str) -> None:
        changes = [x for x in changes if x[3]]
        if not changes:
            return
        identity = self._id("allocation")
        ResourceTransaction(
            event_id=identity,
            timestamp_ns=self.des.now_ns,
            cause=cause,
            allocation_deltas=[AllocationDelta(r, a, b, n, identity) for r, a, b, n in changes],
        ).commit(self.ledgers, journal=self.des.journal)

    def _hbm_move(self, worker: int, source: str, target: str, size: int, cause: str) -> None:
        self._move(
            [(f"hbm:{worker}:{r}", source, target, size) for r in range(self.config.tp)], cause
        )

    def _dram_move(self, cp: Checkpoint, source: str, target: str, tokens: int) -> None:
        self._move(
            [
                (
                    f"dram:{self.config.hosts[cp.peer]}",
                    source,
                    target,
                    self.config.prefix_bytes(tokens) * self.config.tp,
                )
            ],
            "DRAM_CHECKPOINT",
        )

    def _start_copy(
        self,
        *,
        owner: str,
        source: int | None,
        target: int,
        size: int,
        paths: list[tuple[str, ...]],
        done: Callable[[], None],
        cause: str,
        host: int | None = None,
    ) -> str:
        group_id = self._id("copy")
        ids = {f"{group_id}:rank:{r}" for r in range(self.config.tp)}
        group = CopyGroup(owner, source, target, host, ids, done)
        self.groups[group_id] = group

        def completed(flow: ActiveFlow, _des: GlobalDES) -> None:
            if group.canceled:
                return
            group.remaining.remove(flow.flow_id)
            self.metrics[f"{cause}_bytes"] += flow.payload_bytes
            if not group.remaining:
                self.groups.pop(group_id, None)
                group.done()  # publication follows the last TP rank ACK

        for rank in range(self.config.tp):
            fid = f"{group_id}:rank:{rank}"
            self.flows.start_flow(
                ActiveFlow(
                    flow_id=fid,
                    transfer_id=group_id,
                    slice_id=fid,
                    cause=cause,
                    path_resource_ids=paths[rank],
                    payload_bytes=size,
                    remaining_bytes=float(size),
                ),
                on_complete=completed,
            )
        return group_id

    def _cancel_group(self, identity: str) -> None:
        group = self.groups.pop(identity, None)
        if group is None:
            return
        group.canceled = True
        for fid in sorted(group.remaining):
            if fid in self.flow_model.flows:
                canceled = self.flows.cancel_flow(fid, reason="COPY_GENERATION_FENCED")
                self.metrics["canceled_copy_transferred_bytes"] += canceled.transferred_bytes

    def _cancel_owner(self, owner: str) -> None:
        for identity, group in list(self.groups.items()):
            if group.owner == owner:
                self._cancel_group(identity)

    def _choose_peer(self, source: int) -> int | None:
        candidates = [w for w in self.alive if self.config.hosts[w] != self.config.hosts[source]]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda w: (
                len(self.queues[w]) + int(self.busy[w] is not None),
                sum(cp.peer == w and not cp.retired for cp in self.checkpoints),
                -self.ledgers[f"dram:{self.config.hosts[w]}"].bytes_in("FREE"),
                w,
            ),
        )

    def _retire(self, cp: Checkpoint) -> None:
        cp.retired = True
        self._cancel_owner(cp.account)
        if cp.pending:
            self._dram_move(cp, cp.account, "FREE", self.config.block_tokens)
            cp.pending = False
        for block in list(cp.pending_hot):
            self._hbm_move(cp.peer, cp.account, "FREE", self.config.block_bytes, "HOT_ABORT")
            del cp.pending_hot[block]
        if cp.readers:
            return
        self._dram_move(cp, cp.account, "FREE", cp.frontier)
        self._hbm_move(
            cp.peer, cp.account, "FREE", len(cp.hbm) * self.config.block_bytes, "HOT_RELEASE"
        )
        cp.frontier = 0
        cp.hbm.clear()
        cp.desired_hot.clear()

    def _checkpoint(self, state: State) -> None:
        cp, c = state.checkpoint, self.config
        if cp is None or cp.retired or cp.pending or state.recovering is not None:
            return
        if cp.source not in self.alive or cp.frontier + c.block_tokens > state.computed:
            return
        ledger = self.ledgers[f"dram:{c.hosts[cp.peer]}"]
        if ledger.bytes_in("FREE") < c.prefix_bytes(c.block_tokens) * c.tp:
            self.metrics["dram_append_capacity_waits"] += 1
            return
        self._dram_move(cp, "FREE", cp.account, c.block_tokens)
        cp.pending = True
        source_host, target_host = c.hosts[cp.source], c.hosts[cp.peer]

        def committed() -> None:
            if cp.retired or state.checkpoint is not cp:
                return
            cp.pending = False
            cp.frontier += c.block_tokens
            self.metrics["checkpoint_commits"] += 1
            self._record(
                "checkpoint_commit",
                agent=state.spec.key,
                frontier=cp.frontier,
                peer=cp.peer,
                tp_acks=c.tp,
                identity=cp.identity,
            )
            self._rebalance()
            self._checkpoint(state)

        self._start_copy(
            owner=cp.account,
            source=cp.source,
            target=cp.peer,
            size=c.prefix_bytes(c.block_tokens),
            cause="checkpoint",
            paths=[
                (
                    f"d2h:{cp.source}:{r}",
                    f"nic:{source_host}",
                    "fabric",
                    f"nic:{target_host}",
                    f"dram-bw:{target_host}",
                )
                for r in range(c.tp)
            ],
            done=committed,
        )

    def _sync_hot(self, cp: Checkpoint) -> None:
        if cp.readers or cp.retired:
            return
        c = self.config
        for block in sorted(set(cp.pending_hot) - cp.desired_hot):
            self._cancel_group(cp.pending_hot.pop(block))
            self._hbm_move(cp.peer, cp.account, "FREE", c.block_bytes, "HOT_ABORT")
        for block in sorted(cp.hbm - cp.desired_hot):
            self._hbm_move(cp.peer, cp.account, "FREE", c.block_bytes, "HOT_RELEASE")
            cp.hbm.remove(block)
            self.metrics["hbm_released_bytes"] += c.block_bytes * c.tp
        for block in sorted(cp.desired_hot - cp.hbm - set(cp.pending_hot)):
            if any(
                self.ledgers[f"hbm:{cp.peer}:{r}"].bytes_in("FREE") < c.block_bytes
                for r in range(c.tp)
            ):
                self.deferred.add(cp.peer)
                break
            self._hbm_move(cp.peer, "FREE", cp.account, c.block_bytes, "HOT_RESERVE")

            def committed(b=block) -> None:
                if cp.retired:
                    return
                cp.pending_hot.pop(b)
                cp.hbm.add(b)
                self.metrics["hot_block_commits"] += 1

            cp.pending_hot[block] = self._start_copy(
                owner=cp.account,
                source=None,
                target=cp.peer,
                size=c.block_bytes,
                cause="hot",
                host=c.hosts[cp.peer],
                paths=[(f"dram-bw:{c.hosts[cp.peer]}", f"h2d:{cp.peer}:{r}") for r in range(c.tp)],
                done=committed,
            )

    def _dram_estimate(self, state: State) -> int:
        """No-contention placement estimate; actual recovery uses shared flows."""
        c = self.config
        cp = state.checkpoint
        blocks = (cp.frontier if cp else state.computed) // c.block_tokens
        required = blocks if c.attention == "dense" else min(blocks, c.top_k)
        transfer = ceil(required * c.block_bytes / c.h2d_bytes_per_second * 1e9)
        compute = ceil(c.block_tokens * c.prefill_ns_per_token / c.layers)
        gpu = 0
        for layer in range(c.layers):
            gpu = max(gpu, (layer + 1) * transfer) + compute
        return gpu

    def _rebalance(self) -> None:
        if self._rebalancing:
            return
        self._rebalancing = True
        try:
            self._rebalance_inner()
        finally:
            self._rebalancing = False

    def _rebalance_inner(self) -> None:
        c = self.config
        slack = self.tracker.slack(self.des.now_ns)
        self.metrics["slack_fallback_observations"] += len(self.tracker.fallback_workflows)
        if self.policy == "none":
            return
        candidates: list[tuple[int, str, State]] = []
        for key, state in self.states.items():
            if state.finished is not None or state.worker not in self.alive or state.call < 0:
                continue
            if state.recovering is not None or state.computed < c.block_tokens:
                continue
            if state.peer not in self.alive or state.peer == state.worker:
                state.peer = self._choose_peer(state.worker)
            if state.peer is None:
                continue
            exposed = max(0, state.durable * c.prefill_ns_per_token - slack[key])
            if exposed > c.tolerance_ns or self.policy == "all_dram":
                candidates.append((-exposed, key, state))
        # One host-wide budget, even if several DP workers share that host.
        budget = {h: c.dram_bytes_per_host for h in set(c.hosts)}
        for cp in self.checkpoints:
            if cp.retired:
                budget[c.hosts[cp.peer]] -= self.ledgers[f"dram:{c.hosts[cp.peer]}"].bytes_in(
                    cp.account
                )
        selected: set[str] = set()
        for _, key, state in sorted(candidates):
            host = c.hosts[state.peer]
            size = c.prefix_bytes(state.computed // c.block_tokens * c.block_tokens) * c.tp
            if size <= budget[host]:
                budget[host] -= size
                selected.add(key)
        for key, state in self.states.items():
            cp = state.checkpoint
            if cp and (key not in selected or cp.peer != state.peer or cp.source != state.worker):
                self._retire(cp)
                state.checkpoint = None
                self.metrics["dram_reselections"] += 1
        for _, key, state in sorted(candidates):
            if key in selected and state.checkpoint is None:
                cp = Checkpoint(key, self.sequence + 1, state.worker, state.peer)
                self._id("manifest")
                state.checkpoint = cp
                self.checkpoints.append(cp)
            if state.checkpoint:
                self._checkpoint(state)
        hbm_budget = {w: min(self.adapters[w, r].quota for r in range(c.tp)) for w in self.alive}
        for cp in self.checkpoints:
            if cp.retired and cp.peer in hbm_budget:
                hbm_budget[cp.peer] -= len(cp.hbm) * c.block_bytes
        hot_candidates = []
        for key, state in self.states.items():
            cp = state.checkpoint
            if cp is None:
                continue
            cp.desired_hot = set()
            score = max(0, self._dram_estimate(state) - slack[key])
            if self.policy in {"aegiskv", "static_hbm"} and score and cp.frontier:
                hot_candidates.append((-score, key, state))
        self.deferred.clear()
        for _, _, state in sorted(hot_candidates):
            cp = state.checkpoint
            blocks = cp.frontier // c.block_tokens
            desired = {
                (layer, b)
                for layer in range(c.depth)
                for b in top_blocks(state.counts, layer, blocks, c.top_k)
            }
            size = len(desired) * c.block_bytes
            if size <= hbm_budget[cp.peer]:
                cp.desired_hot = desired
                hbm_budget[cp.peer] -= size
            else:
                self.deferred.add(cp.peer)
        # Release low-value copies before admitting replacements; leases still win.
        for cp in self.checkpoints:
            if not cp.retired and (cp.hbm - cp.desired_hot or set(cp.pending_hot) - cp.desired_hot):
                self._sync_hot(cp)
        for _, _, state in sorted(hot_candidates):
            self._sync_hot(state.checkpoint)

    def _control(self) -> None:
        c = self.config
        for w in sorted(self.alive):
            for rank in range(c.tp):
                ledger = self.ledgers[f"hbm:{w}:{rank}"]
                serving = sum(n for a, n in ledger.accounts.items() if a.startswith("primary:"))
                adapter = self.adapters[w, rank]
                if self.policy != "static_hbm":
                    old, new = adapter.update(serving, w in self.pressure, w in self.deferred)
                    if new != old:
                        self._record(
                            "quota",
                            worker=w,
                            rank=rank,
                            before=old,
                            after=new,
                            serving_bytes=serving,
                            pressure=w in self.pressure,
                        )
        self.pressure.clear()
        self._rebalance()
        slack = self.tracker.slack(self.des.now_ns)
        for key, state in self.states.items():
            if state.call >= 0 and state.finished is None:
                cp = state.checkpoint
                self._record(
                    "policy_sample",
                    agent=key,
                    slack_ns=slack[key],
                    full_reconstruction_ns=state.durable * c.prefill_ns_per_token,
                    dram_recovery_estimate_ns=self._dram_estimate(state),
                    protected=cp is not None,
                    checkpoint_tokens=cp.frontier if cp else 0,
                    hbm_blocks=len(cp.hbm) if cp else 0,
                    worker=state.worker,
                    peer=state.peer,
                )
        for w in sorted(self.alive):
            self._admit(w)
        if any(s.finished is None for s in self.states.values()):
            self._at(self.des.now_ns + c.control_window_ns, EventKind.CONTROL_WINDOW, self._control)

    def _release_primary(self, state: State) -> None:
        account = f"primary:{state.spec.key}"
        self._move(
            [
                (name, account, "FREE", ledger.bytes_in(account))
                for name, ledger in self.ledgers.items()
                if name.startswith("hbm:") and ledger.bytes_in(account)
            ],
            "PRIMARY_RELEASE",
        )
        state.primary_tokens = ()

    def _submit(self, state: State) -> None:
        if any(not self.tracker.states[p].finished for p in self.tracker.parents[state.spec.key]):
            raise RuntimeError("invocation submitted before Agent dependencies completed")
        state.call += 1
        state.recovery_row = None
        state.recovering_since = None
        inv = state.invocation
        compatible = (
            state.model_layout == (inv.model, inv.layout)
            and inv.prompt[: len(state.primary_tokens)] == state.primary_tokens
        )
        if not compatible:
            self._release_primary(state)
            state.counts.clear()
            state.computed = 0
            if state.checkpoint:
                self._retire(state.checkpoint)
                state.checkpoint = None
        state.model_layout = (inv.model, inv.layout)
        state.computed = len(state.primary_tokens)
        state.durable = state.computed
        state.submitted = self.des.now_ns
        if state.started is None:
            state.started = state.submitted
        self.tracker.submit(state.spec.key, state.call, state.submitted)
        context = Context(
            model=inv.model,
            role=state.spec.role,
            text=inv.text,
            prompt_tokens=len(inv.prompt),
            completed_calls=len(state.durations),
            previous_durations_ns=tuple(state.durations),
            previous_output_tokens=tuple(state.outputs),
            elapsed_ns=state.submitted - state.started,
            prior_ns=state.spec.prior_ns,
        )
        prediction = self.predictor(context)
        version, submitted = state.call, state.submitted

        def publish() -> None:
            accepted = self.tracker.publish(state.spec.key, version, submitted, prediction)
            self._record(
                "prediction",
                agent=state.spec.key,
                invocation=version,
                submitted_ns=submitted,
                remaining_ns=prediction,
                accepted=accepted,
            )
            self._rebalance()

        self._at(
            self.des.now_ns + self.config.prediction_latency_ns,
            EventKind.DIRECTORY_PUBLISH,
            publish,
        )
        worker = min(
            self.alive,
            key=lambda w: (
                len(self.queues[w])
                + int(self.busy[w] is not None)
                - (0.5 if w == state.worker and state.computed else 0),
                w,
            ),
        )
        if worker != state.worker:
            self._release_primary(state)
            state.computed = state.durable = 0
        state.worker = worker
        if state.peer == worker or state.peer not in self.alive:
            state.peer = self._choose_peer(worker)
        self._record(
            "submit",
            agent=state.spec.key,
            invocation=state.call,
            worker=worker,
            local_prefix_tokens=state.computed,
        )
        self.queues[worker].append(state.spec.key)
        self._admit(worker)

    def _reserve_primary(self, state: State) -> bool:
        c, worker = self.config, state.worker
        account = f"primary:{state.spec.key}"
        required = c.prefix_bytes(len(state.invocation.tokens))
        if required > c.hbm_bytes_per_rank - c.reserve_bytes:
            raise ValueError(f"invocation {state.spec.key} cannot fit the configured working HBM")
        cp = state.recovering
        if cp and cp.hbm:
            # Adopt resident blocks in place, never charge a second physical copy.
            state.available.update(cp.hbm)
            self._hbm_move(
                worker, cp.account, account, len(cp.hbm) * c.block_bytes, "PEER_HBM_ADOPT_IN_PLACE"
            )
            self.metrics["hbm_adopted_bytes"] += len(cp.hbm) * c.block_bytes * c.tp
            cp.hbm.clear()
        needed = max(0, required - self.ledgers[f"hbm:{worker}:0"].bytes_in(account))

        def enough() -> bool:
            return all(
                self.ledgers[f"hbm:{worker}:{r}"].bytes_in("FREE") >= needed + c.reserve_bytes
                for r in range(c.tp)
            )

        if not enough():
            self.pressure.add(worker)
            slack = self.tracker.slack(self.des.now_ns)
            victims = sorted(
                (p for p in self.checkpoints if p.peer == worker and not p.retired),
                key=lambda p: (
                    max(0, self._dram_estimate(self.states[p.key]) - slack[p.key]),
                    p.key,
                ),
            )
            for victim in victims:
                victim.desired_hot.clear()
                self._sync_hot(victim)
                if enough():
                    break
        if not enough():
            # Execution histories are caches, not permanent foreground reservations.
            for other in self.states.values():
                if (
                    other is not state
                    and other.worker == worker
                    and self.busy[worker] != other.spec.key
                    and other.primary_tokens
                ):
                    if other.checkpoint and other.checkpoint.pending:
                        # Cancel before source memory is released. Keep the committed prefix.
                        cp_other = other.checkpoint
                        self._cancel_owner(cp_other.account)
                        self._retire(cp_other)
                        other.checkpoint = None
                    self._release_primary(other)
                    other.computed = 0
                    if enough():
                        break
        if not enough():
            self.metrics["foreground_admission_waits"] += 1
            return False
        self._hbm_move(worker, "FREE", account, needed, "FOREGROUND_RESERVE")
        # Account execution reservations immediately in the safety ceiling.
        for rank in range(c.tp):
            ledger = self.ledgers[f"hbm:{worker}:{rank}"]
            serving = sum(n for a, n in ledger.accounts.items() if a.startswith("primary:"))
            ceiling = max(0, min(c.hbm_cap_bytes, c.hbm_bytes_per_rank - serving - c.reserve_bytes))
            self.adapters[worker, rank].quota = min(self.adapters[worker, rank].quota, ceiling)
        return True

    def _admit(self, worker: int) -> None:
        if worker not in self.alive or self.busy[worker] is not None or not self.queues[worker]:
            return
        state = self.states[self.queues[worker][0]]
        if not self._reserve_primary(state):
            return
        self.queues[worker].popleft()
        self.busy[worker] = state.spec.key
        if state.recovery_row is not None:
            state.recovery_row["admitted_ns"] = self.des.now_ns
            state.recovery_row["queue_ns"] = self.des.now_ns - state.recovering_since
        if state.recovering:
            self._restore(state)
        self._rebalance()
        if not self._maybe_fail(state):
            self._step(state)

    def _restore(self, state: State) -> None:
        cp, c = state.recovering, self.config
        blocks = cp.frontier // c.block_tokens
        state.computed = cp.frontier
        hot = [
            {(layer, b) for b in top_blocks(state.counts, layer, blocks, c.top_k)}
            for layer in range(c.layers)
        ]
        # Top-K in layer order, then all remaining blocks. Missing actual demand
        # may be promoted ahead of this predictive prefetch order.
        for layer in range(c.layers):
            selected = tuple(sorted(hot[layer] - state.available))
            if selected:
                state.load_queue.append(selected)
        for layer in range(c.layers):
            rest = tuple(
                (layer, b)
                for b in range(blocks)
                if (layer, b) not in hot[layer] and (layer, b) not in state.available
            )
            if rest:
                state.load_queue.append(rest)
        self._load_next(state)

    def _load_next(self, state: State) -> None:
        if state.load_active or state.recovering is None:
            return
        if not state.load_queue:
            cp = state.recovering
            expected = cp.frontier // self.config.block_tokens * self.config.layers
            if len(state.available) != expected:
                raise RuntimeError("restore completed with missing checkpoint blocks")
            if state.recovery_row is not None:
                state.recovery_row["restore_done_ns"] = self.des.now_ns
            state.recovering = None
            cp.readers -= 1
            self._retire(cp)
            self._rebalance()
            return
        blocks = state.load_queue.popleft()
        if not blocks:
            self._load_next(state)
            return
        state.load_active = True
        state.loading = set(blocks)
        epoch = state.epoch
        c, worker = self.config, state.worker

        def completed() -> None:
            if state.epoch != epoch:
                return
            state.available.update(blocks)
            state.loading.clear()
            state.load_active = False
            self._load_next(state)
            if state.waiting is not None:
                wake, state.waiting = state.waiting, None
                wake()

        self._start_copy(
            owner=f"restore:{state.spec.key}:{epoch}",
            source=None,
            target=worker,
            host=c.hosts[worker],
            size=len(blocks) * c.block_bytes,
            cause="restore",
            paths=[(f"dram-bw:{c.hosts[worker]}", f"h2d:{worker}:{r}") for r in range(c.tp)],
            done=completed,
        )

    def _require(self, state: State, required: set[Block], callback: Callable[[], None]) -> None:
        missing = required - state.available
        if not missing:
            callback()
            return
        promoted = missing - state.loading
        if promoted:
            state.load_queue = deque(
                tuple(b for b in group if b not in promoted) for group in state.load_queue
            )
            state.load_queue.appendleft(tuple(sorted(promoted)))
            self.metrics["demand_promoted_blocks"] += len(promoted)
        state.waiting = lambda: self._require(state, required, callback)
        self._load_next(state)

    def _query_groups(self, start: int, end: int):
        while start < end:
            stop = min(end, (start // self.config.block_tokens + 1) * self.config.block_tokens)
            yield start, stop - start
            start = stop

    def _step(self, state: State) -> None:
        c = self.config
        start = state.computed
        total = len(state.invocation.tokens)
        if start >= total:
            self._complete(state)
            return
        replaying = start < state.durable
        prefill_end = max(len(state.invocation.prompt), state.durable)
        if start < prefill_end:
            end = min(start + c.block_tokens, prefill_end)
            duration = (end - start) * c.prefill_ns_per_token
        else:
            end = min(total, start + c.decode_batch_tokens)
            if state.recovery_row is not None and "first_new_token_ns" not in state.recovery_row:
                end = min(end, start + 1)
            duration = (end - start) * c.decode_ns_per_token
        if (
            self.failure
            and not self.fault_fired
            and state.spec.key == self.failure.agent
            and state.call == self.failure.invocation
        ):
            trigger = ceil(total * self.failure.progress)
            if start < trigger < end:
                end = trigger
                duration = (end - start) * (
                    c.prefill_ns_per_token if start < prefill_end else c.decode_ns_per_token
                )
        epoch = state.epoch

        def finished() -> None:
            if state.epoch != epoch:
                return
            state.compute_event = None
            self._forward_done(state, start, end, replaying)

        if state.recovering is not None:
            self._layer_step(state, start, end, 0, duration, finished)
        else:
            state.compute_event = self._at(
                self.des.now_ns + duration, EventKind.FORWARD_COMPLETE, finished
            )

    def _layer_step(
        self,
        state: State,
        start: int,
        end: int,
        layer: int,
        duration: int,
        finished: Callable[[], None],
    ) -> None:
        c = self.config
        if layer == c.layers:
            finished()
            return
        cp = state.recovering
        required = set()
        if cp:
            for query, _ in self._query_groups(start, end):
                required.update(
                    (layer, b) for b in demand(c, layer, query, cp.frontier // c.block_tokens)
                )
        epoch = state.epoch
        # Integer division preserves the configured total compute duration.
        layer_ns = duration * (layer + 1) // c.layers - duration * layer // c.layers

        def ready() -> None:
            if state.epoch != epoch:
                return

            def next_layer() -> None:
                if state.epoch == epoch:
                    self._layer_step(state, start, end, layer + 1, duration, finished)

            state.compute_event = self._at(
                self.des.now_ns + layer_ns, EventKind.FORWARD_COMPLETE, next_layer
            )

        self._require(state, required, ready)

    def _forward_done(self, state: State, start: int, end: int, replaying: bool) -> None:
        old_durable = state.durable
        state.computed = end
        state.durable = max(state.durable, end)
        state.primary_tokens = state.invocation.tokens[:end]
        c = self.config
        # The fixture selector is constant within these query groups; counts
        # equal per-query accumulation without peeking at future queries.
        for query, weight in self._query_groups(start, end):
            for layer in range(c.layers):
                for b in demand(c, layer, query, ceil(end / c.block_tokens)):
                    state.counts[layer, b] += weight
        if replaying:
            self.metrics["replayed_tokens"] += min(end, old_durable) - start
        self.metrics["forward_tokens"] += end - start
        emitted = max(0, end - max(old_durable, len(state.invocation.prompt)))
        self.metrics["emitted_tokens"] += emitted
        if state.recovery_row is not None:
            row = state.recovery_row
            if end >= row["durable_tokens"] and "replay_done_ns" not in row:
                row["replay_done_ns"] = self.des.now_ns
            if emitted and "first_new_token_ns" not in row:
                row["first_new_token_ns"] = self.des.now_ns
                row["latency_ns"] = self.des.now_ns - row["failure_ns"]
        if self._maybe_fail(state):
            return
        self._rebalance()
        self._step(state)

    def _maybe_fail(self, state: State) -> bool:
        failure = self.failure
        if (
            failure is None
            or self.fault_fired
            or state.spec.key != failure.agent
            or state.call != failure.invocation
        ):
            return False
        trigger = ceil(len(state.invocation.tokens) * failure.progress)
        if state.computed < trigger:
            return False
        if state.computed != trigger:
            raise ValueError(
                "logical fault point was skipped by prefix reuse; choose a later point"
            )
        self._fail(state)
        return True

    def _fail(self, target: State) -> None:
        c = self.config
        worker = target.worker
        failed = {worker}
        dead_hosts = set()
        if self.failure.scope == "host":
            dead_hosts = {c.hosts[worker]}
            failed = {w for w in self.alive if c.hosts[w] in dead_hosts}
        self.fault_fired = True
        self.failure_record = {
            "time_ns": self.des.now_ns,
            "workers": sorted(failed),
            "agent": target.spec.key,
            "invocation": target.call,
            "logical_tokens": target.computed,
            "total_tokens": len(target.invocation.tokens),
        }
        self._record("failure", **self.failure_record)
        affected = [self.states[k] for w in sorted(failed) if (k := self.busy[w]) is not None]
        queued = [self.states[k] for w in sorted(failed) for k in self.queues[w]]
        self.alive -= failed
        if not self.alive:
            raise RuntimeError("no compatible surviving execution worker")
        for identity, group in list(self.groups.items()):
            if group.source in failed or group.target in failed or group.host in dead_hosts:
                self._cancel_group(identity)
        # Hold surviving committed checkpoints before policy refresh can reclaim them.
        for state in affected:
            cp = state.checkpoint
            valid = cp and cp.peer in self.alive and c.hosts[cp.peer] not in dead_hosts
            if valid and cp.frontier:
                cp.readers += 1
                state.recovering = cp
            state.checkpoint = None
            if cp:
                self._retire(cp)
        for cp in self.checkpoints:
            if cp.peer in failed or c.hosts[cp.peer] in dead_hosts:
                if cp.readers:
                    raise RuntimeError("nested recovery failure requires a separate failure event")
                self._retire(cp)
                if self.states[cp.key].checkpoint is cp:
                    self.states[cp.key].checkpoint = None
        for w in failed:
            self.busy[w] = None
            self.queues[w].clear()
        for state in self.states.values():
            if state.worker in failed:
                self._release_primary(state)
                state.computed = 0
                state.worker = None
        for state in affected:
            state.epoch += 1
            if state.compute_event:
                self.des.cancel(state.compute_event, reason="GPU_FAILURE")
                self._callbacks.pop(state.compute_event.event_id, None)
                state.compute_event = None
            state.available.clear()
            cp = state.recovering
            frontier = cp.frontier if cp else 0
            row = {
                "agent": state.spec.key,
                "invocation": state.call,
                "failure_ns": self.des.now_ns,
                "durable_tokens": state.durable,
                "checkpoint_tokens": frontier,
                "rebuild_tokens": state.durable - frontier,
                "tail_exceeds_256": bool(cp and state.durable - frontier > c.block_tokens),
                "hbm_blocks": len(cp.hbm) if cp else 0,
                "source_worker": worker,
            }
            self.recoveries.append(row)
            state.recovery_row = row
            state.recovering_since = self.des.now_ns
            state.worker = (
                cp.peer
                if cp
                else (
                    state.peer
                    if state.peer in self.alive
                    else min(
                        self.alive,
                        key=lambda w: (len(self.queues[w]) + int(self.busy[w] is not None), w),
                    )
                )
            )
            row["retry_worker"] = state.worker
            state.peer = self._choose_peer(state.worker)
            self._at(
                self.des.now_ns + c.failure_detection_ns,
                EventKind.RECOVERY_START,
                lambda s=state: self._enqueue_retry(s),
            )
        for state in queued:
            state.worker = min(self.alive, key=lambda w: (len(self.queues[w]), w))
            self.queues[state.worker].append(state.spec.key)
        self._rebalance()

    def _enqueue_retry(self, state: State) -> None:
        self.queues[state.worker].appendleft(state.spec.key)
        self._record("retry", agent=state.spec.key, worker=state.worker, new_peer=state.peer)
        self._admit(state.worker)

    def _complete(self, state: State) -> None:
        # A request may finish while cold KV still copies. Keep its read lease
        # until that transfer drains, before releasing the execution reservation.
        if state.recovering is not None:
            state.waiting = lambda: self._complete(state)
            return
        worker = state.worker
        elapsed = self.des.now_ns - state.submitted
        state.durations.append(elapsed)
        state.outputs.append(len(state.invocation.output))
        self.requests.append(
            {
                "agent": state.spec.key,
                "invocation": state.call,
                "submit_ns": state.submitted,
                "finish_ns": self.des.now_ns,
                "latency_ns": elapsed,
                "worker": worker,
                "output_tokens": len(state.invocation.output),
            }
        )
        self.busy[worker] = None
        if state.call + 1 < len(state.spec.calls):
            self._submit(state)
        else:
            state.finished = self.des.now_ns
            self.tracker.states[state.spec.key].finished = True
            if state.checkpoint:
                self._retire(state.checkpoint)
                state.checkpoint = None
            self._release_primary(state)
            for child in self.tracker.children[state.spec.key]:
                s = self.states[child]
                if all(self.tracker.states[p].finished for p in self.tracker.parents[child]):
                    self._at(
                        max(self.des.now_ns, s.spec.release_ns),
                        EventKind.REQUEST_ARRIVAL,
                        lambda child_state=s: self._submit(child_state),
                    )
        self._rebalance()
        for w in sorted(self.alive):
            self._admit(w)

    def _invariants(self, _des: GlobalDES) -> None:
        usage: Counter = Counter()
        for name, ledger in self.ledgers.items():
            accounts = ledger.accounts
            if min(accounts.values()) < 0 or sum(accounts.values()) != ledger.capacity_bytes:
                raise RuntimeError(f"physical byte conservation failed: {name}")
            used = ledger.capacity_bytes - ledger.bytes_in("FREE")
            self.peaks[name] = max(self.peaks[name], used)
            if name.startswith("hbm:"):
                replica = sum(n for a, n in accounts.items() if a.startswith("replica:"))
                usage["replica_hbm"] += replica
                usage["primary_hbm"] += used - replica
                self.peaks[f"replica:{name}"] = max(self.peaks[f"replica:{name}"], replica)
            else:
                usage["replica_dram"] += used
        for kind in ("replica_hbm", "primary_hbm", "replica_dram"):
            self.metrics[f"{kind}_byte_ns"] += self._usage[kind] * (
                self.des.now_ns - self._usage_time
            )
            self.peaks[kind] = max(self.peaks[kind], usage[kind])
        self._usage_time = self.des.now_ns
        self._usage = usage
        for cp in self.checkpoints:
            if cp.frontier % self.config.block_tokens:
                raise RuntimeError("checkpoint is not a complete chunk frontier")
            if cp.frontier < 0 or any(
                b >= cp.frontier // self.config.block_tokens for _, b in cp.hbm
            ):
                raise RuntimeError("HBM block lacks a complete DRAM checkpoint")
        self.metrics["invariant_checks"] += 1

    def run(self) -> dict:
        self.des.run(until_ns=self.config.max_time_ns)
        incomplete = [k for k, s in self.states.items() if s.finished is None]
        if incomplete:
            raise RuntimeError(f"simulation stalled or exceeded time budget: {incomplete}")
        if self.failure and not self.fault_fired:
            raise RuntimeError("the paired failure trigger was not reached")
        if self.flow_model.flows or any(
            ledger.bytes_in("FREE") != ledger.capacity_bytes for ledger in self.ledgers.values()
        ):
            raise RuntimeError("terminal allocations/transfers leaked")
        expected = sum(len(inv.output) for s in self.states.values() for inv in s.spec.calls)
        if self.metrics["emitted_tokens"] != expected:
            raise RuntimeError("output tokens were duplicated or lost during retry")
        workflows: dict[str, dict] = {}
        for s in self.states.values():
            row = workflows.setdefault(
                s.spec.workflow, {"start_ns": s.spec.release_ns, "finish_ns": s.finished}
            )
            row["start_ns"] = min(row["start_ns"], s.spec.release_ns)
            row["finish_ns"] = max(row["finish_ns"], s.finished)
        for row in workflows.values():
            row["wct_ns"] = row["finish_ns"] - row["start_ns"]
        return {
            "design_version": DESIGN_VERSION,
            "evidence_class": "modeled_uncalibrated",
            "policy": self.policy,
            "complete": True,
            "failure": self.failure_record,
            "workflows": workflows,
            "requests": self.requests,
            "recoveries": self.recoveries,
            "metrics": dict(self.metrics),
            "peak_bytes": dict(self.peaks),
            "terminal_allocations_zero": True,
            "output_tokens_exact": True,
            "predictor": getattr(
                self.predictor,
                "name",
                self.predictor.__name__
                if hasattr(self.predictor, "__name__")
                else type(self.predictor).__name__,
            ),
        }
