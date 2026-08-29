# Pinned Mooncake Transfer Engine notes

Transfer Engine uses the same vanilla Mooncake commit as Store. The locked
source default is `slice_size = 65536` bytes in `include/config.h`; `config.cpp`
also exposes the `MC_SLICE_SIZE` override. A resolved MoonKVSim deployment must
record the final value and provenance.

MoonKVSim preserves BatchID/task/slice lifecycle, topology and protocol path
selection. It replaces real CUDA/RDMA/TCP execution with shared DES resources.
GDR and TCP host staging remain distinct paths. No source peak bandwidth is a
calibrated effective rate, and Master RPC is never treated as a byte path.

The current Mooncake worktree modifies TCP transport. Baseline TCP semantics
must be read from blob `9cf906a0cdb4d6600c9c235bd1a2bd0865a81b1c`, not the
worktree file.

The pinned batch API is
`allocateBatchID(batch_size) -> submitTransfer -> getTransferStatus ->
freeBatchID`. `submitTransfer` rejects entries beyond the allocation-time
capacity, and `freeBatchID` returns `BatchBusy` while any submitted task is
unfinished. The opaque upstream `BatchID` carries a `BatchDesc` pointer;
MoonKVSim deliberately uses stable IDs and does not claim binary handle parity.

Pinned task statuses are `WAITING`, `PENDING`, `INVALID`, `CANCELED`,
`COMPLETED`, `TIMEOUT`, and `FAILED`; pinned slice statuses omit cancellation
and are `PENDING`, `POSTED`, `SUCCESS`, `TIMEOUT`, and `FAILED`. MoonKVSim's
explicit `CANCELED` slice status is a DES failure-audit extension. Similarly,
its deterministic resource-path priority replaces upstream retry-zero
random/round-robin HCA choice; preferred/available ordering and disabled-path
rejection are the preserved semantics.

The Vanilla simulator path is now a complete directional binding: source and
destination endpoint strings, node IDs, NUMA IDs, and both HCA IDs must match
the two `MemoryLocation` objects exactly. Retry zero deterministically chooses
the lowest `(priority, path_id)` preferred candidate and uses available only
when preferred is empty; positive retry counts enumerate preferred followed by
available with the pinned `(retry_count - 1) % N` rule. `LOCAL_COPY` and
`NVLINK` cannot cross nodes and never carry HCA IDs. These are configured E2
semantics, not sysfs/CUDA discovery or physical HCA-distance parity.

Pooled endpoint preparation is an independent GlobalDES lifecycle. A cold key
reserves a named registration-worker lane and emits registration start,
completion, and endpoint-ready events; concurrent cold waiters join that one
generation, while a warm lookup emits its own delayed ready event. Cancellation
releases an unused worker reservation and failure teardown invalidates the warm
generation. Assumed registration/lookup delays are never aggregated into GPU
forward. Real memory-region registration, transport connect/QP handshake,
reconnect, pool eviction, and their physical timing remain unmodeled.

These facts and their official test blobs are bound by
`reference/goldens/mooncake-f161118-store-te-source-api.json`. In a Git-object
only isolated archive, the pinned `transfer_engine` and `mooncake_store`
targets built with the local dependency prefix and `USE_HTTP=ON`. The selected
official `topology_test`, `memory_location_test`, `transfer_task_test`, and four
Store test binaries passed; the exact local record and binary hashes are in
`reference/goldens/mooncake-f161118-official-test-validation.json`.

That result is E2 external official-unit evidence only. No RDMA device or CUDA
kernel ran, the dependency prefix is not hash-locked, and no MoonKVSim versus
official BatchTransfer trace was compared. Real TCP/RDMA execution, overlap,
endpoint/NUMA differential behavior, and C0-C4 calibration remain open.
