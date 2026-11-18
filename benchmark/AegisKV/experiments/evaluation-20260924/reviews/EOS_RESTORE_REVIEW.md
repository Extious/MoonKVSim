# EOS versus background recovery: read-only finding

The production runtime has a P1 completion deadlock when the final output token
is accepted before the remaining cold checkpoint KV finishes loading. Merely
adding the missing wake would still impose an unnecessary EOS-to-drain delay on
request latency, dependent Agents and Workflow completion.

The inspected production source hash is recorded in `eos_restore_repro.json`.
The reproduction imports that source without editing it. Its `WakeOnly`
subclass is explicitly a diagnostic counterfactual, not a delivered fix.

## Contract and code path

`paper/system_design.tex:362–431` describes layer demand and hit/transfer overlap;
lines 398–399 say the remaining KV continues to load after invocation readiness.
It does not require a completed invocation to wait for unused cold KV. A read
lease is an internal memory-lifetime obligation, not evidence that an already
accepted EOS is unavailable to the caller.

At `current/runtime.py:1415–1420`, `_complete` installs itself as `state.waiting`
and returns while `state.recovering` is set. At lines 981–993 the final flow's
completion first invokes this waiter. `_complete` sees the still-set recovery
state and installs itself again. `_load_next` then enters its empty-queue branch
(953–969), clears `recovering`, drops the read lease and returns without invoking
the newly installed waiter. There are no remaining restore flows to wake it.
The worker remains busy and the primary reservation remains allocated until the
simulation's time bound; periodic control events do not repair this state.

## Deterministic reproducer

Run from the repository root:

```sh
.venv/bin/python benchmark/AegisKV/experiments/evaluation-20260924/reviews/eos_restore_repro.py
```

The fixture is one Agent, 1,024 prompt tokens plus 32 output tokens, a declared
32-token output cap, two layers, TP1, a worker fault at logical token 1,046
(`ceil(1056*0.99)`), and 10 MB/s H2D. Sparse demand is an explicitly constructed
causal selector that always reads block zero. Configured linear compute costs
are simulator assumptions, not native sparse model or GPU measurements.

All times below are milliseconds from the same simulation origin:

| Policy / selector | First new token | EOS accepted | Restore done | Request completion |
| --- | ---: | ---: | ---: | --- |
| DRAM / dense | 524.2372 | 524.3272 | 523.1272 | 524.3272 |
| Aegis / dense | 497.87725 | 497.96725 | 496.836 | 497.96725 |
| DRAM / block zero | 131.0212 | 131.1112 | 523.1272 | stalled |
| Aegis / block zero | 105.83 | 105.92 | 496.836 | stalled |

Both stalled runs have all 32 output tokens emitted, no active transfers,
`recovering=None`, `waiting` still set, an occupied worker and an unreleased
primary reservation at the 2-second termination bound. Thus this is not a slow
transfer or too-short run limit.

The diagnostic final-wake-only subclass completes DRAM at 523.1272 ms and Aegis
at 496.836 ms: respectively 392.016 and 390.916 ms later than accepted EOS. It
demonstrates why adding a wake alone is insufficient. Dense controls require all
checkpoint blocks during the forward, so their restore completes before EOS and
their completion timestamp equals EOS. This supports a conditional dense-model
non-trigger statement; it does not silently validate every frozen campaign run.

## Minimal safe repair proposal

Cancel the remaining recovery prefetch at EOS, after the final forward has
consumed all required KV. First cancel the restore copy group through the DES
flow API, preserving already transferred bytes in cancellation accounting; then
fence the old invocation epoch and clear its queued loads, waiters and mutable
load state. Only after there can be no remaining DMA reader should the code drop
the checkpoint read lease, retire the checkpoint and release destination memory.
Record EOS as request completion, free the worker, and immediately admit queued
work or release dependent Agents using the existing completion path.

For a subsequent invocation of the same Agent, the previous `primary_tokens`
cannot describe a fully resident prefix if cold loading was canceled. The
smallest conservative implementation invalidates that local history and starts
the next call with zero prefix reuse, while preserving already emitted tokens,
request duration/output history and the logical fault position. This can forgo
legitimate partial-prefix reuse and must be recorded as a modeling limitation.
It is safer than allowing asynchronous callbacks for the old recovery to mutate
the new invocation's `State` or releasing HBM while DMA still targets it.

Retaining prefetch after EOS instead requires a separately owned recovery
cleanup object with its own epoch, lease, destination allocation and callbacks;
the reused Agent `State` and its full-prefix cache flag cannot own both calls.
That is a larger change. In either strategy, a completed-token callback must not
be delayed solely to satisfy internal cleanup, and deferred/pending checkpoint
copies must be canceled before their source primary memory can be released.

No runtime, paper, or frozen campaign source was changed by this review.

## Isolated repair prototype

`eos-prototype/runtime.patch` contains the proposed runtime change;
`eos-prototype/runtime.py` and `test_eos_prefetch_prototype.py` retain its exact
source and targeted tests. `EOS_PROTOTYPE_RESULTS.json` records the timelines.
The prototype was executed only from the separate directory recorded in
`EOS_PROTOTYPE_LOCATION.json`. The production and frozen campaign modules remain
unchanged.

All 48 existing current-runtime tests and nine targeted EOS tests pass in that
isolated copy (57 total); Ruff passes. The new cases cover timely completion,
compatible and incompatible same-Agent calls, dependent-Agent release, queued
work on the retry worker, stale callbacks, the unaffected dense path with full
prefix reuse, read-lease/allocation cleanup and physical transfer conservation.
The temporary CLI test fixture has its own empty Git repository solely because
the existing manifest test calls `git rev-parse`; it is not a campaign revision.

In the prototype, sparse DRAM and Aegis complete at their original EOS times of
131.1112 ms and 105.92 ms. Their first-new-token and accepted EOS timings are
unchanged. Unused cold loading is canceled at that time, rather than assigned a
fabricated successful `restore_done_ns`. Both dense controls retain exactly
their original EOS/completion times and retain complete-prefix reuse.

The repair also corrects cancellation accounting for a previously paused and
resumed flow: `payload_bytes - remaining_bytes` includes service from before
that resume, which was already counted by the preemption path. Cancellation
must add only `group.initial_remaining[rank] - aborted_bytes`. A dedicated test
checks that 2 MB served after resuming a 5 MB remainder of a 10 MB payload adds
2 MB, rather than 7 MB, to cancellation traffic.

This is a conservative simulator repair, with instantaneous fluid-copy
cancellation and no measured DMA cancellation cost. Nested failures during an
existing recovery remain outside the runtime's existing one-fault contract.
