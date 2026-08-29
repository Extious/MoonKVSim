# Mooncake TCP Store physical calibration input 66924

This bundle preserves the three successful I/O observations from Slurm job
`66924`.  They were produced by Qwen3-8B under SGLang 0.5.16 with DP=2 and
TP=1 on two RTX 4090 GPUs on host `gpu12`.  Both SGLang workers and the
Mooncake Store were on that host and used Mooncake's TCP path.

The two files under `raw/` are byte-identical per-process profiler output and
contain exactly three original events.  `l3_io_events.jsonl` is also
byte-identical to the source's canonical three-line projection, which adds DP
rank and derived decimal GB/s without changing the original byte, object or
duration values.  Each duration surrounds a complete synchronous SGLang
HiCache call to MooncakeStore: `batch_put_from*` for backup or
`batch_get_into*` for prefetch.  It is therefore an effective, high-level
same-host TCP Store rate, not a network-link peak, raw DRAM bandwidth, SSD/disk
bandwidth, or isolated transfer-engine rate.  The two worktree patches are
retained because the run was not produced from clean repositories and the
SGLang patch defines the measurement boundary.

This is a preliminary physical calibration input below E3.  The source uses
SGLang/RTX4090/DP=2, whereas MoonKVSim's target is pinned vLLM 1.2.2 on L40S.
There are only three observations, no held-out validation, no setup/queue/copy
decomposition, and no matched simulator run.  Consequently this bundle does
not close GAP-003, satisfy target E3, establish E4, or permit paper/formal use.

The source directory's entire `benchmark/aegiskv_mooncake/` subtree was
untracked at import time.  `provenance.json` distinguishes that live state
from the dirty status captured inside the original run.  Large torch traces,
Prometheus dumps, logs, and derived `disk_*_bandwidth_gb` overrides were
intentionally not copied.

Audit the self-contained bundle with:

```bash
uv run python scripts/audit_mooncake_tcp_calibration.py
(
  cd benchmark/physical/mooncake-tcp-store/66924-20260803-140423
  sha256sum --strict -c SHA256SUMS
)
```

Add `--verify-source` to re-read the external source artifacts when that local
checkout is available.  Source verification is read-only.
