# Shared-filesystem extension of sparse Prefill measurements

User direction, 2026-09-20: add storage reuse; after local SSD discovery was
inconclusive, the user proposed filesystem/shared storage. This is a fourth
**Shared FS reuse** baseline, not a verified SSD/NVMe measurement or a fourth
AegisKV protection tier. DRAM and storage use no transfer/compute overlap.

## Same request and endpoint

Retain Qwen2.5-7B-Instruct-1M, pinned weights/config, SGLang sparse adapter,
BF16, batch one and TP2 on A100-PCIe-40GB. Contexts C are 8,192 / 65,536 /
262,144 / 1,010,000; historical KV covers M=C-1 tokens, including partial pages.
The complete four-path matrix must come from one allocation and implementation.
Keep the previous allocation 1517055 and its paper figure until new validation
passes. The current cost panel is Figure 1(c), `recovery-cost.pdf`.

- Full Prefill starts with empty KV, computes M in chunks up to 8,192, then
  the same final one-token EXTEND. One full sample per context.
- HBM starts with that exact sparse-generated historical KV resident on GPU.
  Three samples and one warmup per context.
- DRAM transfers all M-token KV from pinned host buffers, synchronizes the
  copy stream, and executes the final token. Three samples and one warmup.
- Shared FS opens and reads a per-rank checkpoint into the same pinned host
  buffers, closes the file, then executes the complete serialized DRAM path.
  **One complete sample per context, no file-read warmup**, to bound paid GPU
  time. Storage read, H2D and forward do not overlap. Do not report a storage
  repeat range or infer statistical significance from its single sample.

The common endpoint is synchronized model-body completion with all C-token KV
ready, excluding `lm_head`. Report maximum elapsed time over TP ranks. Storage
checkpoint creation, fsync, cache eviction, zeroing, source/read-back hashes
and output validation are outside the latency timer. Include open/read/close
and any read scheduling overhead inside the storage timer. CUDA timelines for
Shared FS begin after the file read; their offset is separately recorded.

## Storage and cache state

Each TP rank writes its own 56-buffer checkpoint on the actual shared
filesystem mounted at the experiment directory. All historical KV is stored,
without compression, tensor deduplication or selective loading. Each buffer
is padded to 64 KiB; separately record logical KV bytes and actual file bytes.
At 1,010,000 tokens the two ranks contain 57,917,382,656 logical KV bytes
(53.94 GiB), before alignment padding.

`sharedfs_io.py` uses aligned pinned buffers, `O_DIRECT` and 16 MiB `preadv` /
`pwritev` chunks. Writes finish with fsync. File-specific `POSIX_FADV_DONTNEED`
is followed by a `mincore` check; require zero resident Linux file pages before
and after the timed direct read. Never drop machine-wide caches. Before each
storage trial, overwrite the destination buffers outside the timer; verify
the entire restored file's SHA-256 against the original, then verify GPU
historical KV, hidden state, new KV and greedy output.

These checks address the client's Linux file page cache. They do not control
the DPC internal cache, remote service cache, or identify physical media. Label the result
**shared-filesystem reuse with uncontrolled server cache**, not cold SSD
latency. The actual compute-node mount and a small direct-I/O correctness and
residency probe are required before model loading. A login-node NFS result
alone does not establish compute-node filesystem type or throughput. Actual
allocation 1517208 exposes `/paraai_n32_h_01` with filesystem type `dpc`; its
64 MiB direct-I/O preflight also passed with zero Linux file-page residency.
Linux documents the server-cache limitation of direct I/O on NFS in
[open(2)](https://man7.org/linux/man-pages/man2/open.2.html).

## Feasibility and budget evidence

Read-only allocation 1517166 completed in 3 GPU-seconds on
`paraai-n32-h-01-agent-1`. It exposed a Huawei `VBS fileIO` virtual block
device, no identifiable NVMe device, and only 3.11 GiB free in job `/tmp`.
This does not prove every node lacks SSD. The login node mounts the home
directory over NFS. The 64 MiB login-node CPU probe passed exact round-trip
and zero page-residency checks; those times are preparation data, not plotted
model latencies. Raw audits remain in `blsc/` and `blsc/results/1517166/`.

After the inventory, actual usage is 15,885 GPU-seconds of the authorized
19,800; 3,915 seconds remain. A complete run may reserve 2 GPUs for at most
30 minutes plus the existing 60-second-per-GPU accounting margin, requiring
3,720 seconds. The user subsequently authorized further GPU-hours if needed;
use the remaining existing cap first and record any necessary increase before
submission. No untracked GPU run is permitted.
Each context removes only its own checkpoint after validation; failed-run
checkpoints may be removed after the job is terminal and their identity is
recorded. The user explicitly requested removal of all shared-storage KV after
measurement. A batch exit finalizer removes generated checkpoint files after
the worker exits; an independent terminal-state cleanup audit is also required
to cover hard-kill or node-failure cases. Never remove model weights or
unrelated files to make space. The six explicitly approved old pip download
files were removed with identity checks in `blsc/sharedfs-cache-cleanup.json`.
