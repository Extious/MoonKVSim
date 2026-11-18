"""Exact-byte layerwise restore with stream dependencies and event evidence."""


def intersection_ms(left, right):
    """Intervals on two serialized device streams; return their intersection."""
    a = b = 0
    total = 0.0
    while a < len(left) and b < len(right):
        x, y = left[a], right[b]
        total += max(0.0, min(x[1], y[1])-max(x[0], y[0]))
        if x[1] <= y[1]:
            a += 1
        else:
            b += 1
    return total


class LayerwiseRestore:
    def __init__(self, adapter, caches):
        import torch
        self.torch = torch
        self.caches = caches
        self.layers = list(adapter.runner.model.model.layers)
        assert len(self.layers) == 28 and len(caches) == 56
        self.copy_stream = torch.cuda.Stream()
        self.active = False
        self.handles = []
        for i, layer in enumerate(self.layers):
            self.handles.append(layer.register_forward_pre_hook(self._pre(i)))
            self.handles.append(layer.register_forward_hook(self._post(i)))

    def _pre(self, i):
        def hook(module, args):
            if self.active:
                stream = self.torch.cuda.current_stream()
                if self.path == "DRAM_overlap":
                    stream.wait_event(self.ready[i])
                self.compute_start[i].record(stream)
                self.visited.append(i)
        return hook

    def _post(self, i):
        def hook(module, args, output):
            if self.active:
                self.compute_end[i].record()
        return hook

    def prepare(self, path):
        # Allocate event objects outside the timer, shared instrumentation for
        # all reuse paths. Events are recorded only while the measured work runs.
        torch = self.torch
        event = lambda: torch.cuda.Event(enable_timing=True)
        self.path = path
        self.origin = event()
        self.copy_start, self.ready = [event() for _ in self.layers], [event() for _ in self.layers]
        self.compute_start, self.compute_end = [event() for _ in self.layers], [event() for _ in self.layers]
        self.visited = []
        self.active = True

    def begin(self, host, history):
        torch = self.torch
        self.origin.record()
        if self.path == "HBM":
            return
        assert self.path in ("DRAM_overlap", "DRAM_no_overlap")
        self.copy_stream.wait_event(self.origin)
        with torch.cuda.stream(self.copy_stream):
            for i in range(len(self.layers)):
                self.copy_start[i].record()
                for j in (2*i, 2*i+1):
                    assert host[j].shape == self.caches[j][:history].shape
                    self.caches[j][:history].copy_(host[j], non_blocking=True)
                self.ready[i].record()
        if self.path == "DRAM_no_overlap":
            self.copy_stream.synchronize()

    def finish(self):
        # Caller has synchronized the measured endpoint before collecting this.
        self.active = False
        assert self.visited == list(range(28)), self.visited
        intervals = lambda starts, ends: [[self.origin.elapsed_time(a), self.origin.elapsed_time(b)]
                                           for a, b in zip(starts, ends)]
        compute = intervals(self.compute_start, self.compute_end)
        copies = intervals(self.copy_start, self.ready) if self.path != "HBM" else []
        if copies:
            assert all(compute[i][0] + .05 >= copies[i][1] for i in range(28)), (compute, copies)
        shared = intersection_ms(copies, compute)
        if self.path == "DRAM_no_overlap":
            assert shared < .05, shared
        return {"path": self.path, "visited_layers": self.visited,
                "copy_intervals_ms": copies, "compute_intervals_ms": compute,
                "concurrent_interval_ms": shared,
                "sum_copy_interval_ms": sum(b-a for a, b in copies),
                "sum_compute_interval_ms": sum(b-a for a, b in compute),
                "layer_dependencies_satisfied": True}
