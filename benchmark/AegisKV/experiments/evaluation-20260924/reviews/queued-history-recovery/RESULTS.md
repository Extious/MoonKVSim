# Queued continuation history recovery

**PASS; live source edits complete.** Final application and source hashes are in
`../QUEUED_HISTORY_APPLICATION.json`, with `freeze_ready=true`.

A real, unmodified scheduling path reproduces the issue. Agent `a/history` finishes
its first call, then submits a compatible continuation behind `c/victim` on worker0.
At the victim's fault at84.8 ms the continuation has durable520, complete peer CP512,
and has not begun its new forward. The old handler leased checkpoints only for busy
invocations; it cleared this queued history and retired its valid CP. No artificial
state assignment or scheduling monkeypatch is needed for this reproduction.

The corrected handler acquires the surviving CP's read lease before releasing the
failed execution history, then queues restoration on its peer after detection.
Frozen CP counters are restored on admission; lost live counters and unpublished
snapshots are cleared. Existing full-restore/EOS paths release the lease. A queued
continuation with no committed checkpoint falls back to reconstructing its history.
Displaced first calls also receive a destination wake-up rather than depending on
an unrelated worker's future completion.

`summary.recoveries` continues to identify **busy interrupted invocations**.
`summary.history_restores` separately records queued histories with
`kind=queued_history`; readers must not union it into active co-victim counts.
Its service interval runs from admission to first new output and can include
remaining ordinary prompt work, so it is not a pure incremental recovery penalty.

The matched linear-cost reproduction retains config, workload, failure identity,
and exactly the same active-victim recovery record. History Workflow WCT changes
from269.000000 to217.800096 ms; restored CP512 leaves eight old tokens to rebuild.
This example establishes the behavioral correction, not an effect-size estimate
for any frozen campaign.

Six initial new regressions failed on the previous implementation. The expanded
eight tests pass, including TP1/2, DRAM, HBM adoption, no checkpoint, a host failure
with two busy victims and one queued continuation, sparse EOS cancellation followed
by a third invocation, unpublished CP/counter rejection, and a displaced first
call routed to another idle destination. All **74 current tests pass**; physical
ledger invariants, exact emitted counts, zero oracle reservations, and terminal
allocation/read-lease cleanup are checked. Ruff and diff checks pass.

The runtime has no natural idle gap between calls: it submits the next invocation
inside the same completion handler. Unfinished history-owning requests are busy,
queued, or awaiting a retry event. The conformance case above is a naturally queued
continuation; it should not be described as a modeled Tool/think-time gap.

Version: `checkpoint-decay-hysteresis-incremental-g-20260924-eosfix1-causal-domain1-queued-history1`.
Prior frozen sources/results remain unchanged and must not be relabeled with it.
