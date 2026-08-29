# MoonKVSim design contract

This document summarizes invariants. Detailed requirements and milestone gates
remain authoritative in `MOONKVSIM_PLAN.md`.

## Authority and scope

1. The pinned vLLM source controls scheduler, block-manager, cache-layout, and
   connector lifecycle semantics.
2. The pinned Vanilla Mooncake source controls Master, Store, replica,
   allocation, eviction, and Transfer Engine semantics.
3. The immutable final AegisKV patent is the highest authority for the later
   `aegiskv` branch. Historical Mooncake/SGLSim assets are reference-only.
4. `main` has `PRIMARY_HBM` and `STORE_DRAM`; it has no Peer-HBM policy and no
   persistent SSD/NVMe tier.

## Clock and event model

The sole clock is monotonic `now_ns`. Events are ordered by
`(timestamp_ns, priority, stable_sequence)`. Resources never own a second clock.
Failure/fence events at a timestamp precede completion, commit, or output events
at that timestamp. This conservative tie rule is frozen by tests.

## State and accounting

Logical KV objects and roles are separate from physical allocations. A physical
allocation is charged exactly once even if it has multiple logical roles.
Capacity changes occur only through atomic resource transactions with auditable
before/delta/after values. `PENDING` replicas are neither cache-hit nor recovery
eligible; all required shards and transfers must finish before `COMMITTED` is
published.

Capacity, rate, concurrency, and logical resources remain distinct. Every
capacity ledger balances at every event boundary. Any invariant failure makes a
run invalid and stops it before result aggregation.

## Data and failure boundaries

Host staging exists only for a transfer lifetime and is not a private Host L2.
Store DRAM is globally queryable by compatible DP ranks. The first release
supports only physical `GPU_FAILURE`: failed GPU compute, copy engines, and HBM
become unavailable, while committed Store DRAM remains usable.

## Prediction boundary

AIConfigurator predicts only one scheduler step's GPU forward duration (and any
model-internal collective explicitly declared in its profile). Scheduler CPU,
Mooncake RPC, KV copies, network contention, Store service, failure detection,
reroute, and replay are modeled independently.
