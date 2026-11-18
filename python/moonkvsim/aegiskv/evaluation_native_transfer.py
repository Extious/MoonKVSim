"""Raw-KV transfer component driven by frozen native query selections.

The clock is an assumed component clock, not a native kernel or output clock.
All variants share one background order; only prepared residency changes.
"""

from __future__ import annotations

from collections import deque

import numpy as np

BLOCK_BYTES = 65536
QUERY_COLUMNS = (
    "layer_entry_ns",
    "kv_ready_ns",
    "kv_wait_ns",
    "history_blocks",
    "local_tail_blocks",
    "resident_history_at_entry",
    "missing_history_at_entry",
)
LAYER_COLUMNS = (
    "entry_ns",
    "all_kv_ready_ns",
    "hit_compute_ns",
    "done_ns",
    "exposed_wait_ns",
    "history_union_blocks",
    "missing_union_blocks",
    "hit_references",
    "all_references",
    "transferred_bytes_during_layer",
)
SEGMENT_COLUMNS = (
    "layer_zero_based",
    "block",
    "start_ns",
    "end_ns",
    "bytes",
    "urgent",
    "completed",
)


def incidence_from_selected(selected: np.ndarray, stop: int) -> np.ndarray:
    """Deduplicate the two KV groups per query, retaining native query order."""
    if selected.ndim != 3 or selected.shape[0] != 2 or selected.shape[1] < stop:
        raise ValueError("expected two groups and a complete native query prefix")
    selected = selected[:, :stop]
    queries = np.arange(stop)[None, :, None]
    if selected.dtype != np.int16 or np.any(selected < -1):
        raise ValueError("invalid native block indices")
    if np.any((selected >= 0) & (selected > queries // 64)):
        raise ValueError("future KV block in native causal selection")
    valid = selected >= 0
    if np.any(valid.sum(axis=-1) == 0):
        raise ValueError("empty native selector group")
    out = np.zeros((stop, (stop + 63) // 64), dtype=np.bool_)
    query = np.broadcast_to(queries, selected.shape)
    out[query[valid], selected[valid]] = True
    return out


def topk(counts, incumbent, k, eligible, epsilon=0.0):
    def rank(b):
        return (-float(counts[b]), b)

    order = sorted(range(eligible), key=rank)
    chosen = set(sorted((b for b in incumbent if b < eligible), key=rank)[:k])
    for block in order:
        if block in chosen:
            continue
        if len(chosen) < min(k, eligible):
            chosen.add(block)
        else:
            victim = max(chosen, key=rank)
            if counts[block] > (1 + epsilon) * counts[victim]:
                chosen.remove(victim)
                chosen.add(block)
    return tuple(sorted(chosen, key=rank))


def placements(chunks: np.ndarray, future: np.ndarray, checkpoint: int, k=16, depth=4):
    """Past-only deployed lifecycle; later layers rank once at recovery."""
    layers, _, width = chunks.shape
    counts = np.zeros((layers, width), dtype=np.float64)
    incumbents = [() for _ in range(layers)]
    for step in range(checkpoint // 256):
        counts = (counts + chunks[:, step]) * 0.9
        eligible = (step + 1) * 4
        for layer in range(min(depth, layers)):
            incumbents[layer] = topk(counts[layer], incumbents[layer], k, eligible, 0.1)
    eligible = checkpoint // 64
    ranking = [
        incumbents[layer] if layer < depth else topk(counts[layer], (), k, eligible)
        for layer in range(layers)
    ]
    current = {(layer, b) for layer in range(min(depth, layers)) for b in ranking[layer]}
    recency = {
        (layer, b)
        for layer in range(min(depth, layers))
        for b in range(max(0, eligible - k), eligible)
    }
    oracle = {
        (layer, b)
        for layer in range(min(depth, layers))
        for b in topk(future[layer, :, :eligible].sum(axis=0), (), k, eligible)
    }
    # The sequence is identical for all four methods, including DRAM.
    background = [(layer, b) for layer in range(layers) for b in sorted(ranking[layer])]
    background += [
        (layer, b) for layer in range(layers) for b in range(eligible) if b not in ranking[layer]
    ]
    assert len(background) == layers * eligible and len(set(background)) == len(background)
    return (
        {"DRAM": set(), "Current": current, "Recency": recency, "Oracle": oracle},
        background,
        counts,
    )


class SerialTransfer:
    """One continuous byte-conserving H2D link, with fluid miss priority.

    Bandwidth is an integer number of bytes/ns, exactly matching 8/16/32 GB/s.
    A partially transferred background block retains all service on preemption.
    """

    def __init__(self, background, initial, bytes_per_ns, block_bytes=BLOCK_BYTES):
        if bytes_per_ns <= 0 or block_bytes <= 0 or block_bytes % bytes_per_ns:
            raise ValueError("positive integral transfer durations required")
        if len(background) != len(set(background)) or not set(initial) <= set(background):
            raise ValueError("invalid common background or prepared residency")
        self.background = deque(background)
        self.ready_at = {obj: 0 for obj in initial}
        self.remaining = {obj: block_bytes for obj in background if obj not in initial}
        self.rate, self.block_bytes = bytes_per_ns, block_bytes
        self.now = 0
        self.active = None
        self.segments = []
        self.transferred = 0
        self.preemptions = 0

    def _service(self, obj, stop, urgent):
        remaining = self.remaining[obj]
        assert remaining % self.rate == 0
        finish = self.now + remaining // self.rate
        end = min(stop, finish)
        served = (end - self.now) * self.rate
        if served:
            self.segments.append((*obj, self.now, end, served, int(urgent), int(end == finish)))
            self.remaining[obj] -= served
            self.transferred += served
        self.now = end
        if end == finish:
            self.ready_at[obj] = end
            del self.remaining[obj]
            if self.active == obj:
                self.active = None
        return end == finish

    def require(self, required):
        missing = set(required) - self.ready_at.keys()
        if missing and self.active is not None and self.active not in missing:
            self.preemptions += 1
            self.background.appendleft(self.active)
            self.active = None
        # Match the runtime's deterministic sorted-object miss promotion.
        order = sorted(missing)
        if self.active is not None and self.active in missing:
            order.remove(self.active)
            order.insert(0, self.active)
        for obj in order:
            self._service(obj, self.now + self.remaining[obj] // self.rate, True)
        assert set(required) <= self.ready_at.keys()
        return self.now

    def advance(self, target):
        if target < self.now:
            raise ValueError("transfer clock cannot move backward")
        while self.now < target:
            if self.active is None:
                while self.background and self.background[0] in self.ready_at:
                    self.background.popleft()
                if not self.background:
                    self.now = target
                    break
                self.active = self.background.popleft()
            self._service(self.active, target, False)


def simulate(
    future,
    checkpoint,
    initial,
    background,
    bandwidth_gbps,
    layer_compute_ns,
    *,
    block_bytes=BLOCK_BYTES,
):
    """Layer release -> byte transfers -> per-query ready -> assumed layer work."""
    layers, queries, _width = future.shape
    history = checkpoint // 64
    if future.dtype != np.bool_ or checkpoint % 64 or layer_compute_ns < 0:
        raise ValueError("invalid component input")
    for q in range(queries):
        if np.any(future[:, q, (checkpoint + q) // 64 + 1 :]):
            raise ValueError("future local-tail block in query demand")
    if any(layer >= layers or block >= history for layer, block in initial):
        raise ValueError("prepared object is outside the historical checkpoint")
    expected = {(layer, b) for layer in range(layers) for b in range(history)}
    if set(background) != expected:
        raise ValueError("background must cover the same complete raw-KV checkpoint")
    pipe = SerialTransfer(background, initial, bandwidth_gbps, block_bytes)
    query_rows = np.zeros((layers, queries, len(QUERY_COLUMNS)), dtype=np.int64)
    layer_rows = []
    demanded = set()
    for layer in range(layers):
        entry, before_bytes = pipe.now, pipe.transferred
        history_demand = future[layer, :, :history]
        resident = np.array([(layer, b) in pipe.ready_at for b in range(history)])
        required = {(layer, int(b)) for b in np.flatnonzero(history_demand.any(axis=0))}
        demanded.update(required)
        hit_refs = int(history_demand[:, resident].sum() + future[layer, :, history:].sum())
        all_refs = int(future[layer].sum())
        if not all_refs:
            raise ValueError("each layer needs nonempty query demand")
        hit_compute = layer_compute_ns * hit_refs // all_refs
        missing = required - pipe.ready_at.keys()
        pipe.require(required)
        all_ready = pipe.now
        ready_times = np.array([pipe.ready_at.get((layer, b), entry) for b in range(history)])
        for q in range(queries):
            ids = np.flatnonzero(history_demand[q])
            ready = max(entry, int(ready_times[ids].max()) if len(ids) else entry)
            count, hits = len(ids), int(resident[ids].sum())
            query_rows[layer, q] = (
                entry,
                ready,
                ready - entry,
                count,
                int(future[layer, q, history:].sum()),
                hits,
                count - hits,
            )
        wait = max(0, all_ready - entry - hit_compute)
        done = entry + layer_compute_ns + wait
        pipe.advance(done)
        layer_rows.append(
            (
                entry,
                all_ready,
                hit_compute,
                done,
                wait,
                len(required),
                len(missing),
                hit_refs,
                all_refs,
                pipe.transferred - before_bytes,
            )
        )
    served = {obj: block_bytes - left for obj, left in pipe.remaining.items()}
    served.update({obj: block_bytes for obj in pipe.ready_at if obj not in initial})
    unused_bytes = sum(value for obj, value in served.items() if obj not in demanded)
    partial_bytes = sum(value for obj, value in served.items() if obj in pipe.remaining)
    canceled_remaining = sum(
        pipe.remaining[obj] for obj, value in served.items() if obj in pipe.remaining and value
    )
    assert pipe.transferred == sum(served.values())
    assert pipe.transferred == sum(row[4] for row in pipe.segments)
    assert demanded <= pipe.ready_at.keys()
    assert not (set(pipe.remaining) & set(pipe.ready_at))
    assert sum(row[4] for row in layer_rows) + layer_compute_ns * layers == pipe.now
    summary = dict(
        raw_component_finish_ns=pipe.now,
        assumed_compute_ns=layer_compute_ns * layers,
        exposed_wait_ns=sum(row[4] for row in layer_rows),
        transferred_bytes=pipe.transferred,
        transferred_but_not_demanded_bytes=unused_bytes,
        partial_transfer_bytes_at_stop=partial_bytes,
        canceled_unfinished_object_remaining_bytes=canceled_remaining,
        not_transferred_checkpoint_bytes=sum(pipe.remaining.values()),
        initial_resident_bytes=len(initial) * block_bytes,
        demanded_unique_bytes=len(demanded) * block_bytes,
        resident_demanded_bytes=len(demanded & set(initial)) * block_bytes,
        preemptions=pipe.preemptions,
        transfer_segments=len(pipe.segments),
        query_ready_wait_mean_ns=float(query_rows[:, :, 2].mean()),
        query_ready_wait_max_ns=int(query_rows[:, :, 2].max()),
        local_tail_query_block_events=int(query_rows[:, :, 4].sum()),
    )
    return (
        summary,
        query_rows,
        np.asarray(layer_rows, dtype=np.int64),
        np.asarray(pipe.segments, dtype=np.int64).reshape(-1, 7),
    )
