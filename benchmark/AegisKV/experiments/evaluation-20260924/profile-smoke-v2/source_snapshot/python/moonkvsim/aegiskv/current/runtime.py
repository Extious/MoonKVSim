"""Current AegisKV on MoonKVSim's shared clock, flow model and byte ledgers.

The foreground model is FCFS per DP/TP worker, with token-batched forwards and
explicit layer recovery. It is NOT the legacy vLLM continuous-batching adapter.
All costs are configured assumptions; no GPU code executes here.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from math import ceil

from moonkvsim.simulation.event import EventHandle, EventKind, ScheduledEvent
from moonkvsim.simulation.flow_des import FlowDESController
from moonkvsim.simulation.global_des import GlobalDES
from moonkvsim.simulation.journal import EventJournal
from moonkvsim.simulation.ledger import CapacityLedger, CapacityResourceKind
from moonkvsim.simulation.network import ActiveFlow, FlowContentionModel
from moonkvsim.simulation.resource import RateResource
from moonkvsim.simulation.transaction import AllocationDelta, ResourceTransaction

from . import DESIGN_VERSION
from .model import Agent, Config, Failure, Invocation
from .policy import Adapter, demand, hbm_gain, top_blocks
from .tracker import Context, Predictor, Tracker, prior_predictor

Block = tuple[int, int]
DemandProvider = Callable[[Config, Invocation, int, int, int], Iterable[int]]
DurationProfile = Callable[[Config, Invocation, int, int, str], int]


class SummaryJournal(EventJournal):
    """Retain event-type counts only; explicitly not an event replay artifact."""

    def __init__(self):
        super().__init__()
        self.counts = Counter()

    def append(self, timestamp_ns, record_type, data):
        if timestamp_ns < self._last_timestamp_ns:
            raise ValueError("journal timestamp cannot move backwards")
        self._last_timestamp_ns = timestamp_ns
        self.counts[record_type] += 1


class DiscardIntervals(list):
    def append(self, interval):
        pass


@dataclass
class LoadBatch:
    objects: tuple[Block, ...]
    remaining: tuple[float, ...] | None = None
    urgent: bool = False


@dataclass
class Checkpoint:
    key: str
    identity: int
    source: int
    peer: int
    frontier: int = 0
    pending: bool = False
    pending_bytes: int = 0
    counts: Counter[Block] = field(default_factory=Counter)
    hot_sets: dict[int, tuple[int, ...]] = field(default_factory=dict)
    gain_ns: int = 0
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
    count_snapshots: dict[int, Counter[Block]] = field(default_factory=dict)
    checkpoint: Checkpoint | None = None
    recovering: Checkpoint | None = None
    available: set[Block] = field(default_factory=set)
    loading: set[Block] = field(default_factory=set)
    load_queue: deque[LoadBatch] = field(default_factory=deque)
    load_active: bool = False
    load_group: str | None = None
    load_current: LoadBatch | None = None
    waiting: Callable[[], None] | None = None
    compute_event: EventHandle | None = None
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
    initial_remaining: tuple[float, ...] = ()


class CurrentRuntime:
    def __init__(
        self,
        config: Config,
        agents: tuple[Agent, ...],
        *,
        policy: str = "aegiskv",
        failure: Failure | None = None,
        predictor: Predictor = prior_predictor,
        demand_provider: DemandProvider | None = None,
        duration_profile: DurationProfile | None = None,
        retain_detailed_logs: bool = True,
    ):
        if policy not in {"none", "dram", "aegiskv", "all_dram", "static_hbm"}:
            raise ValueError("unknown current-design policy")
        self.config, self.policy, self.failure, self.predictor = config, policy, failure, predictor
        self.demand_provider = demand_provider
        self.duration_profile = duration_profile
        self.retain_detailed_logs = retain_detailed_logs
        self.des = GlobalDES(journal=None if retain_detailed_logs else SummaryJournal())
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
        if not retain_detailed_logs:
            self.flow_model.intervals = DiscardIntervals()
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
        if self.retain_detailed_logs or kind not in {
            "policy_sample",
            "recovery_layer",
            "topk_update",
        }:
            self.events.append({"time_ns": self.des.now_ns, "kind": kind, **data})

    def _duration(self, state: State, start: int, end: int, stage: str) -> int:
        if self.duration_profile is None:
            cost = (
                self.config.prefill_ns_per_token
                if stage == "prefill"
                else self.config.decode_ns_per_token
            )
            return (end - start) * cost
        value = self.duration_profile(self.config, state.invocation, start, end, stage)
        if type(value) is not int or value < 0:
            raise ValueError("duration_profile must return a nonnegative integer number of ns")
        return value

    def _compute_delay(self, state: State, duration: int) -> int:
        """Optional start-of-event DMA interference sensitivity, not calibration."""
        c = self.config
        if c.compute_dma_slowdown and any(
            any(
                f"{direction}:{state.worker}:{r}" in flow.path_resource_ids
                for r in range(c.tp)
                for direction in ("h2d", "d2h")
            )
            for flow in self.flow_model.flows.values()
        ):
            delay = ceil(duration * c.compute_dma_slowdown)
            self.metrics["modeled_dma_compute_slowdown_ns"] += delay
            return duration + delay
        return duration

    def _demand(self, state: State, layer: int, query: int, blocks: int) -> set[int]:
        if self.demand_provider is None:
            return demand(self.config, layer, query, blocks)
        selected = set(self.demand_provider(self.config, state.invocation, layer, query, blocks))
        visible = min(blocks, query // self.config.block_tokens + 1)
        if any(type(b) is not int or not 0 <= b < visible for b in selected):
            raise ValueError("demand_provider selected an invalid or causally invisible KV block")
        return selected

    def _object_bytes(self, block: Block) -> int:
        # Negative block IDs represent an atomic, versioned metadata snapshot.
        return (
            self.config.metadata_layer_bytes(-block[1]) if block[1] < 0 else self.config.block_bytes
        )

    def _hot_bytes(self, objects: Iterable[Block]) -> int:
        return sum(self._object_bytes(b) for b in objects)

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

    def _dram_move(self, cp: Checkpoint, source: str, target: str, size: int) -> None:
        self._move(
            [
                (
                    f"dram:{self.config.hosts[cp.peer]}",
                    source,
                    target,
                    size * self.config.tp,
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
        remaining: tuple[float, ...] | None = None,
    ) -> str:
        group_id = self._id("copy")
        sizes = remaining if remaining is not None else (float(size),) * self.config.tp
        ids = {f"{group_id}:rank:{r}" for r in range(self.config.tp) if sizes[r] > 0}
        group = CopyGroup(owner, source, target, host, ids, done)
        group.initial_remaining = sizes
        self.groups[group_id] = group

        def completed(flow: ActiveFlow, _des: GlobalDES) -> None:
            if group.canceled:
                return
            group.remaining.remove(flow.flow_id)
            rank = int(flow.flow_id.rsplit(":", 1)[-1])
            self.metrics[f"{cause}_bytes"] += sizes[rank]
            if not group.remaining:
                self.groups.pop(group_id, None)
                group.done()  # publication follows the last TP rank ACK

        for rank in range(self.config.tp):
            if sizes[rank] <= 0:
                continue
            fid = f"{group_id}:rank:{rank}"
            flow = ActiveFlow(
                flow_id=fid,
                transfer_id=group_id,
                slice_id=fid,
                cause=cause,
                path_resource_ids=paths[rank],
                payload_bytes=size,
                remaining_bytes=float(size),
            )
            # Resuming a paused fluid transfer retains already-served bytes.
            flow.remaining_bytes = sizes[rank]
            self.flows.start_flow(flow, on_complete=completed)
        if not ids:
            self.groups.pop(group_id, None)
            self._at(self.des.now_ns, EventKind.DIRECTORY_PUBLISH, done)
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
            self._dram_move(cp, cp.account, "FREE", cp.pending_bytes)
            cp.pending = False
            cp.pending_bytes = 0
        for block in list(cp.pending_hot):
            self._hbm_move(cp.peer, cp.account, "FREE", self._object_bytes(block), "HOT_ABORT")
            del cp.pending_hot[block]
        if cp.readers:
            return
        self._dram_move(cp, cp.account, "FREE", self.config.checkpoint_bytes(cp.frontier))
        self._hbm_move(cp.peer, cp.account, "FREE", self._hot_bytes(cp.hbm), "HOT_RELEASE")
        cp.frontier = 0
        cp.hbm.clear()
        cp.desired_hot.clear()
        cp.counts.clear()
        cp.hot_sets.clear()

    def _checkpoint(self, state: State) -> None:
        cp, c = state.checkpoint, self.config
        if cp is None or cp.retired or cp.pending or state.recovering is not None:
            return
        if cp.source not in self.alive or cp.frontier + c.checkpoint_tokens > state.computed:
            return
        next_frontier = cp.frontier + c.checkpoint_tokens
        # A new version carries all counters/selector metadata. The old version
        # stays charged until all TP shards acknowledge the new manifest.
        pending_bytes = c.prefix_bytes(c.checkpoint_tokens) + c.layers * c.metadata_layer_bytes(
            next_frontier
        )
        ledger = self.ledgers[f"dram:{c.hosts[cp.peer]}"]
        if ledger.bytes_in("FREE") < pending_bytes * c.tp:
            self.metrics["dram_append_capacity_waits"] += 1
            return
        self._dram_move(cp, "FREE", cp.account, pending_bytes)
        cp.pending = True
        cp.pending_bytes = pending_bytes
        counts = state.count_snapshots.get(next_frontier, Counter()).copy()
        source_host, target_host = c.hosts[cp.source], c.hosts[cp.peer]

        def committed() -> None:
            if cp.retired or state.checkpoint is not cp:
                return
            cp.pending = False
            cp.pending_bytes = 0
            self._dram_move(cp, cp.account, "FREE", c.layers * c.metadata_layer_bytes(cp.frontier))
            cp.frontier = next_frontier
            cp.counts = counts
            for layer in range(c.depth):
                before = cp.hot_sets.get(layer, ())
                cp.hot_sets[layer] = top_blocks(
                    counts,
                    layer,
                    cp.frontier // c.block_tokens,
                    c.top_k,
                    incumbent=before,
                    hysteresis=c.topk_hysteresis,
                )
                self.metrics["topk_layer_reranks"] += 1
            for frontier in tuple(state.count_snapshots):
                if frontier <= next_frontier:
                    del state.count_snapshots[frontier]
            self._record(
                "topk_update",
                agent=state.spec.key,
                frontier=cp.frontier,
                layers=c.depth,
                count_decay=c.count_decay,
                hysteresis=c.topk_hysteresis,
            )
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
            size=pending_bytes,
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
            self._hbm_move(cp.peer, cp.account, "FREE", self._object_bytes(block), "HOT_ABORT")
        for block in sorted(cp.hbm - cp.desired_hot):
            size = self._object_bytes(block)
            self._hbm_move(cp.peer, cp.account, "FREE", size, "HOT_RELEASE")
            cp.hbm.remove(block)
            self.metrics["hbm_released_bytes"] += size * c.tp
        for block in sorted(cp.desired_hot - cp.hbm - set(cp.pending_hot)):
            size = self._object_bytes(block)
            if any(self.ledgers[f"hbm:{cp.peer}:{r}"].bytes_in("FREE") < size for r in range(c.tp)):
                self.deferred.add(cp.peer)
                break
            self._hbm_move(cp.peer, "FREE", cp.account, size, "HOT_RESERVE")

            def committed(b=block) -> None:
                if cp.retired:
                    return
                cp.pending_hot.pop(b)
                cp.hbm.add(b)
                self.metrics["hot_metadata_commits" if b[1] < 0 else "hot_block_commits"] += 1

            cp.pending_hot[block] = self._start_copy(
                owner=cp.account,
                source=None,
                target=cp.peer,
                size=size,
                cause="hot",
                host=c.hosts[cp.peer],
                paths=[(f"dram-bw:{c.hosts[cp.peer]}", f"h2d:{cp.peer}:{r}") for r in range(c.tp)],
                done=committed,
            )

    def _recovery_estimate(self, state: State, *, hbm: bool = False) -> int:
        """Offline-profile surrogate, not an oracle for future native misses.

        This no-contention estimate uses all blocks for dense attention and
        configured synthetic demand cardinality otherwise. Actual recovery
        separately reveals demand and competes for shared physical links.
        """
        c = self.config
        cp = state.checkpoint
        blocks = (cp.frontier if cp else state.computed) // c.block_tokens
        required = (
            blocks if c.attention == "dense" else min(blocks, c.synthetic_selected_blocks + 1)
        )
        tail_ns = self._duration(
            state, max(0, state.durable - c.checkpoint_tokens), state.durable, "prefill"
        )
        compute = ceil(tail_ns / c.layers)
        gpu = transfer_done = 0
        for layer in range(c.layers):
            resident = min(required, c.top_k) if hbm and layer < c.depth else 0
            metadata = (
                0 if hbm and layer < c.depth else c.metadata_layer_bytes(blocks * c.block_tokens)
            )
            transfer_done += ceil(
                ((required - resident) * c.block_bytes + metadata) / c.h2d_bytes_per_second * 1e9
            )
            gpu = max(gpu, transfer_done) + compute
        return gpu

    def _dram_estimate(self, state: State) -> int:
        return self._recovery_estimate(state)

    def _hbm_gain(self, state: State, slack: int) -> int:
        return hbm_gain(
            self._recovery_estimate(state), self._recovery_estimate(state, hbm=True), slack
        )

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
            if state.recovering is not None or state.computed < c.checkpoint_tokens:
                continue
            if state.peer not in self.alive or c.hosts[state.peer] == c.hosts[state.worker]:
                state.peer = self._choose_peer(state.worker)
            if state.peer is None:
                continue
            exposed = max(0, self._duration(state, 0, state.durable, "prefill") - slack[key])
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
            size = (
                c.checkpoint_bytes(state.computed // c.checkpoint_tokens * c.checkpoint_tokens)
                * c.tp
            )
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
                hbm_budget[cp.peer] -= self._hot_bytes(cp.hbm)
        hot_candidates = []
        for key, state in self.states.items():
            cp = state.checkpoint
            if cp is None:
                continue
            cp.desired_hot = set()
            score = self._hbm_gain(state, slack[key])
            cp.gain_ns = score
            if self.policy in {"aegiskv", "static_hbm"} and score and cp.frontier:
                hot_candidates.append((-score, key, state))
        self.deferred.clear()
        for _, _, state in sorted(hot_candidates):
            cp = state.checkpoint
            desired = {(layer, b) for layer in range(c.depth) for b in cp.hot_sets.get(layer, ())}
            if c.metadata_layer_bytes(cp.frontier):
                desired.update((layer, -cp.frontier) for layer in range(c.depth))
            size = self._hot_bytes(desired)
            if size <= hbm_budget[cp.peer]:
                cp.desired_hot = desired
                hbm_budget[cp.peer] -= size
            else:
                self.deferred.add(cp.peer)
        # Release low-value copies before admitting replacements; leases still win.
        for cp in sorted(self.checkpoints, key=lambda cp: (cp.gain_ns, cp.key)):
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
                    full_reconstruction_ns=self._duration(state, 0, state.durable, "prefill"),
                    dram_recovery_estimate_ns=self._dram_estimate(state),
                    hbm_recovery_estimate_ns=self._recovery_estimate(state, hbm=True),
                    hbm_gain_ns=self._hbm_gain(state, slack[key]),
                    protected=cp is not None,
                    checkpoint_tokens=cp.frontier if cp else 0,
                    hbm_blocks=sum(b >= 0 for _, b in cp.hbm) if cp else 0,
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
        inv = state.invocation
        compatible = (
            state.model_layout == (inv.model, inv.layout)
            and inv.prompt[: len(state.primary_tokens)] == state.primary_tokens
        )
        if not compatible:
            self._release_primary(state)
            state.counts.clear()
            state.count_snapshots.clear()
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
        if (
            state.peer not in self.alive
            or self.config.hosts[state.peer] == self.config.hosts[worker]
        ):
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
        inv = state.invocation
        output_reservation = (
            len(inv.output) if inv.output_limit_tokens is None else inv.output_limit_tokens
        )
        required = c.checkpoint_bytes(len(inv.prompt) + output_reservation)
        if required > c.hbm_bytes_per_rank - c.reserve_bytes:
            raise ValueError(f"invocation {state.spec.key} cannot fit the configured working HBM")
        cp = state.recovering
        if cp and cp.hbm:
            # Adopt resident blocks in place, never charge a second physical copy.
            state.available.update(cp.hbm)
            self._hbm_move(
                worker, cp.account, account, self._hot_bytes(cp.hbm), "PEER_HBM_ADOPT_IN_PLACE"
            )
            self.metrics["hbm_adopted_bytes"] += self._hot_bytes(cp.hbm) * c.tp
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
                    self._hbm_gain(self.states[p.key], slack[p.key]),
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
            state.recovery_row["queue_ns"] = (
                self.des.now_ns - state.recovery_row["retry_enqueued_ns"]
            )
        if state.recovering:
            self._restore(state)
        self._rebalance()
        if not self._maybe_fail(state):
            self._step(state)

    def _restore(self, state: State) -> None:
        cp, c = state.recovering, self.config
        blocks = cp.frontier // c.block_tokens
        state.computed = cp.frontier
        state.counts = cp.counts.copy()
        state.count_snapshots.clear()
        state.count_snapshots[cp.frontier] = cp.counts.copy()
        hot = []
        for layer in range(c.layers):
            # Only layers beyond L are ranked here: first-L rankings were
            # frozen with the published checkpoint, including hysteresis.
            selected = cp.hot_sets.get(layer)
            if selected is None:
                selected = top_blocks(cp.counts, layer, blocks, c.top_k)
                self.metrics["recovery_layer_reranks"] += 1
            hot.append({(layer, b) for b in selected})
            if c.metadata_layer_bytes(cp.frontier):
                meta = (layer, -cp.frontier)
                if meta not in state.available:
                    state.load_queue.append(LoadBatch((meta,)))
            missing_hot = tuple(sorted(hot[layer] - state.available))
            if missing_hot:
                state.load_queue.append(LoadBatch(missing_hot))
        for layer in range(c.layers):
            rest = tuple(
                (layer, b)
                for b in range(blocks)
                if (layer, b) not in hot[layer] and (layer, b) not in state.available
            )
            if rest:
                state.load_queue.append(LoadBatch(rest))
        # _layer_step first reveals layer-zero demand; do not start a later
        # prefetch before the engine can enqueue its immediate misses.

    def _load_next(self, state: State) -> None:
        if state.load_active or state.recovering is None:
            return
        if not state.load_queue:
            cp = state.recovering
            c = self.config
            expected = cp.frontier // c.block_tokens * c.layers
            if sum(b >= 0 for _, b in state.available) != expected:
                raise RuntimeError("restore completed with missing checkpoint blocks")
            if c.metadata_layer_bytes(cp.frontier) and any(
                (layer, -cp.frontier) not in state.available for layer in range(c.layers)
            ):
                raise RuntimeError("restore completed with missing selection metadata")
            if state.recovery_row is not None:
                state.recovery_row["restore_done_ns"] = self.des.now_ns
            state.recovering = None
            cp.readers -= 1
            self._retire(cp)
            self._rebalance()
            return
        batch = state.load_queue.popleft()
        blocks = batch.objects
        if not blocks:
            self._load_next(state)
            return
        state.load_active = True
        state.loading = set(blocks)
        state.load_current = batch
        epoch = state.epoch
        c, worker = self.config, state.worker

        def completed() -> None:
            if state.epoch != epoch:
                return
            state.available.update(blocks)
            state.loading.clear()
            state.load_active = False
            state.load_group = None
            state.load_current = None
            # Demand revealed by a just-unblocked layer precedes new prefetch.
            if state.waiting is not None:
                wake, state.waiting = state.waiting, None
                wake()
            self._load_next(state)

        state.load_group = self._start_copy(
            owner=f"restore:{state.spec.key}:{epoch}",
            source=None,
            target=worker,
            host=c.hosts[worker],
            size=self._hot_bytes(blocks),
            remaining=batch.remaining,
            cause="restore",
            paths=[(f"dram-bw:{c.hosts[worker]}", f"h2d:{worker}:{r}") for r in range(c.tp)],
            done=completed,
        )

    def _pause_prefetch(self, state: State) -> None:
        """Byte-preserving fluid preemption; not a measured DMA preemption cost."""
        identity = state.load_group
        if identity is None or state.load_current is None:
            return
        group = self.groups.pop(identity)
        group.canceled = True
        remaining = [0.0] * self.config.tp
        for fid in sorted(group.remaining):
            rank = int(fid.rsplit(":", 1)[-1])
            canceled = self.flows.cancel_flow(fid, reason="RECOVERY_MISS_PRIORITY")
            remaining[rank] = canceled.aborted_bytes
            self.metrics["restore_bytes"] += group.initial_remaining[rank] - canceled.aborted_bytes
        state.load_current.remaining = tuple(remaining)
        state.load_queue.appendleft(state.load_current)
        state.load_current = None
        state.load_group = None
        state.loading.clear()
        state.load_active = False
        self.metrics["recovery_prefetch_preemptions"] += 1

    def _require(self, state: State, required: set[Block], callback: Callable[[], None]) -> None:
        missing = required - state.available
        if not missing:
            callback()
            self._load_next(state)
            return
        # Only demand objects retain priority. A mixed predictive batch is
        # split below, distributing its partial service proportionally by
        # object size (the same explicit fluid-transfer abstraction).
        if state.load_active and not state.loading <= missing:
            self._pause_prefetch(state)
        if state.load_current is not None:
            state.load_current.urgent = True
        promoted = missing - state.loading
        if promoted:
            urgent = []
            rest = deque()
            for batch in state.load_queue:
                overlap = set(batch.objects) & promoted
                if not overlap:
                    rest.append(batch)
                elif batch.remaining is not None:
                    keep = tuple(b for b in batch.objects if b not in overlap)
                    fraction = self._hot_bytes(overlap) / self._hot_bytes(batch.objects)
                    need_remaining = tuple(n * fraction for n in batch.remaining)
                    urgent.append(LoadBatch(tuple(sorted(overlap)), need_remaining, urgent=True))
                    if keep:
                        rest.append(
                            LoadBatch(
                                keep,
                                tuple(
                                    n - urgent_n
                                    for n, urgent_n in zip(
                                        batch.remaining, need_remaining, strict=True
                                    )
                                ),
                            )
                        )
                    promoted.difference_update(overlap)
                else:
                    keep = tuple(b for b in batch.objects if b not in promoted)
                    if keep:
                        rest.append(LoadBatch(keep, urgent=batch.urgent))
            if promoted:
                urgent.append(LoadBatch(tuple(sorted(promoted)), urgent=True))
            state.load_queue = deque(urgent + list(rest))
            self.metrics["demand_promoted_blocks"] += sum(b >= 0 for _, b in promoted)
        state.waiting = lambda: self._require(state, required, callback)
        self._load_next(state)

    def _query_groups(self, start: int, end: int):
        while start < end:
            # Built-in dense/fixture selections are constant over a physical
            # block. External native traces retain per-query granularity.
            stop = (
                start + 1
                if self.demand_provider
                else min(end, (start // self.config.block_tokens + 1) * self.config.block_tokens)
            )
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
            end = min(
                start + c.prefill_chunk_tokens,
                (start // c.checkpoint_tokens + 1) * c.checkpoint_tokens,
                prefill_end,
            )
            stage = "prefill"
        else:
            end = min(
                total,
                start + c.decode_batch_tokens,
                (start // c.checkpoint_tokens + 1) * c.checkpoint_tokens,
            )
            if state.recovery_row is not None and "first_new_token_ns" not in state.recovery_row:
                end = min(end, start + 1)
            stage = "decode"
        if (
            self.failure
            and not self.fault_fired
            and state.spec.key == self.failure.agent
            and state.call == self.failure.invocation
        ):
            trigger = ceil(total * self.failure.progress)
            if start < trigger < end:
                end = trigger
        duration = self._duration(state, start, end, stage)
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
                self.des.now_ns + self._compute_delay(state, duration),
                EventKind.FORWARD_COMPLETE,
                finished,
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
        epoch = state.epoch
        # Integer division preserves the configured total compute duration.
        layer_ns = duration * (layer + 1) // c.layers - duration * layer // c.layers

        def reveal() -> None:
            if state.epoch != epoch:
                return
            cp = state.recovering
            required = set()
            hit_references = references = 0
            if cp:
                for query, weight in self._query_groups(start, end):
                    selected = {
                        (layer, b)
                        for b in self._demand(state, layer, query, cp.frontier // c.block_tokens)
                    }
                    required.update(selected)
                    references += len(selected) * weight
                    hit_references += len(selected & state.available) * weight
            # Metadata-only timing model: proportional hit work overlaps
            # transfer. No QK/softmax/LSE numerical kernel executes here.
            hit_ns = layer_ns * hit_references // references if references else layer_ns
            missing = required - state.available
            self.metrics["recovery_demand_miss_blocks"] += len(missing)
            self.metrics["recovery_hit_compute_ns"] += hit_ns
            self._record(
                "recovery_layer",
                agent=state.spec.key,
                layer=layer,
                query_start=start,
                query_end=end,
                selected_blocks=len(required),
                missing_blocks=len(missing),
                hit_compute_ns=hit_ns,
                layer_compute_ns=layer_ns,
            )
            ready = {"hits": hit_ns == 0, "misses": not missing, "scheduled": False}
            hit_done_at = self.des.now_ns

            def maybe_advance() -> None:
                if (
                    state.epoch != epoch
                    or ready["scheduled"]
                    or not (ready["hits"] and ready["misses"])
                ):
                    return
                ready["scheduled"] = True
                self.metrics["recovery_exposed_miss_wait_ns"] += max(
                    0, self.des.now_ns - hit_done_at
                )

                def next_layer() -> None:
                    if state.epoch == epoch:
                        self._layer_step(state, start, end, layer + 1, duration, finished)

                state.compute_event = self._at(
                    self.des.now_ns + self._compute_delay(state, layer_ns - hit_ns),
                    EventKind.FORWARD_COMPLETE,
                    next_layer,
                )

            def hits_finished() -> None:
                nonlocal hit_done_at
                hit_done_at = self.des.now_ns
                ready["hits"] = True
                maybe_advance()

            def misses_finished() -> None:
                ready["misses"] = True
                maybe_advance()

            # Start miss recall first so the optional DMA sensitivity sees it.
            self._require(state, required, misses_finished)
            if hit_ns:
                state.compute_event = self._at(
                    self.des.now_ns + self._compute_delay(state, hit_ns),
                    EventKind.FORWARD_COMPLETE,
                    hits_finished,
                )
            else:
                maybe_advance()

        cp = state.recovering
        metadata = {(layer, -cp.frontier)} if cp and c.metadata_layer_bytes(cp.frontier) else set()
        self._require(state, metadata, reveal)

    def _forward_done(self, state: State, start: int, end: int, replaying: bool) -> None:
        old_durable = state.durable
        state.computed = end
        state.durable = max(state.durable, end)
        state.primary_tokens = state.invocation.tokens[:end]
        c = self.config
        # Native per-query indices are deduplicated across heads. Built-in
        # selectors can safely aggregate equal selections within a 64-token
        # block; external providers always retain query-level observations.
        if state.checkpoint is not None or state.recovering is not None:
            for query, weight in self._query_groups(start, end):
                for layer in range(c.layers):
                    selected = self._demand(state, layer, query, ceil(end / c.block_tokens))
                    for b in selected:
                        state.counts[layer, b] += weight
                    self.metrics["count_query_block_updates"] += len(selected) * weight
        if end % c.checkpoint_tokens == 0:
            for block in state.counts:
                state.counts[block] *= c.count_decay
            if state.checkpoint is None and state.recovering is None:
                state.count_snapshots.clear()
            state.count_snapshots[end] = state.counts.copy()
            self.metrics["counter_checkpoint_decays"] += 1
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
                row["service_ns"] = self.des.now_ns - row["admitted_ns"]
        if self._maybe_fail(state):
            return
        if end % c.checkpoint_tokens == 0:
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
        source_workers = {s.spec.key: s.worker for s in affected}
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
                "tail_exceeds_256": bool(cp and state.durable - frontier > 256),
                "tail_exceeds_checkpoint_z": bool(
                    cp and state.durable - frontier > c.checkpoint_tokens
                ),
                "hbm_blocks": sum(b >= 0 for _, b in cp.hbm) if cp else 0,
                "hbm_metadata_bytes_per_rank": sum(
                    self._object_bytes(b) for b in cp.hbm if b[1] < 0
                )
                if cp
                else 0,
                "source_worker": source_workers[state.spec.key],
            }
            self.recoveries.append(row)
            state.recovery_row = row
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
        state.recovery_row["retry_enqueued_ns"] = self.des.now_ns
        state.recovery_row["detection_ns"] = self.des.now_ns - state.recovery_row["failure_ns"]
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
            state.counts.clear()
            state.count_snapshots.clear()
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
            if self.config.hosts[cp.source] == self.config.hosts[cp.peer]:
                raise RuntimeError("execution and checkpoint share a protected failure domain")
            if cp.frontier % self.config.checkpoint_tokens:
                raise RuntimeError("checkpoint is not a complete chunk frontier")
            if cp.frontier < 0 or any(
                b >= cp.frontier // self.config.block_tokens or -b > cp.frontier for _, b in cp.hbm
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
            "oracle_reservation_count": sum(
                inv.output_limit_tokens is None
                for state in self.states.values()
                for inv in state.spec.calls
            ),
            "foreground_reservation_model": (
                "prompt plus declared output limit; legacy None uses recorded output length"
            ),
            "predictor": getattr(
                self.predictor,
                "name",
                self.predictor.__name__
                if hasattr(self.predictor, "__name__")
                else type(self.predictor).__name__,
            ),
            "attention_demand_provider": (
                getattr(self.demand_provider, "name", type(self.demand_provider).__name__)
                if self.demand_provider
                else self.config.attention
            ),
            "duration_profile": (
                getattr(self.duration_profile, "name", type(self.duration_profile).__name__)
                if self.duration_profile
                else "configured-linear-token-costs"
            ),
            "detailed_event_and_flow_logs_retained": self.retain_detailed_logs,
            "recovery_compute_model": (
                "selected-reference-proportional hit/miss timing; no numerical LSE kernel"
            ),
            "dma_compute_interference_model": (
                "configured slowdown sampled at each compute-event start"
            ),
            "prefetch_preemption_model": (
                "byte-preserving fluid preemption without DMA switching latency"
            ),
        }
