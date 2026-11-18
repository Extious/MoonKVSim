# Isolated causal-domain prototype validation

**PASS.** The initial draft was applied only to two isolated package trees under
`/home/comp/zhanzhao/.tmp/aegiskv-causal-domain-0hz0922o/{old,fixed}`. At this review
stage live runtime, paper, frozen campaigns and their manifests were unchanged.
`PROTOTYPE_SOURCE.json` binds all copied Python source files; only runtime.py differs.
The copied CLI test uses an empty local Git fixture and copied paper/AGENTS files.
It does not borrow live package imports or pretend the fixture commit is project history.

- Old runtime: `9afc8e74ec1e206cca9b05ae75ae1ffee757a2d0e3e4e76498dbc7addef0d98a`.
- Fixed runtime: `fbb643bbe040bb65c4f410941095182272d8cc2e134cc24057ecb850dda0c973`.
- New domain regressions on old runtime: **5 failed, 1 passed**. The passing case
  rejects future KV, which the old runtime already handled correctly.
- Existing five current test files on old runtime: **60 passed**.
- New domain tests plus the five existing files on fixed runtime: **66 passed**.
  This includes metadata-before-demand, TP publication, byte-preserving preemption,
  layer overlap, EOS cancellation/next invocation, reservation, Slack and summary parity.
- Every imported `moonkvsim` module path and file hash is recorded in
  `OLD_DOMAIN_IMPORTS.json`, `OLD_EXISTING_IMPORTS.json`, `FIXED_ALL_IMPORTS.json`,
  and each small-case directory's `IMPORTS.json`; paths must lie within its isolated tree.

The patch also updates one old assertion that encoded checkpoint-only hit fraction:
3/4 of 200 ms becomes 4/5 when local self KV is included; the layer still finishes at
200 ms. The independent new domain tests establish why that arithmetic changes.

## Small-case effect size, not a campaign estimate

`run_isolated_cases.py` fixed the inputs before execution: two layers, TP1, 64-token
blocks, Z256, CP512 at failure, one 1024-token prompt plus 8-token output, declared
output cap16, DRAM policy, logical fault600, H2D2 MB/s, linear 100 µs/prefill token
and 1 ms/decode token. This deliberately slow link exposes event-model differences;
these are not calibrated timings or representative primary-study conditions.

| Single-Agent case | Old F1 WCT (ms) | Fixed F1 WCT (ms) | Fixed minus old (ms) | Old → fixed miss count |
|---|---:|---:|---:|---:|
| dense | 1156.168000 | 1153.120381 | −3.047619 | 16 → 16 |
| synthetic_sparse | 1119.190223 | 697.416000 | −421.774223 | 16 → 9 |

F0 WCT is 110.4 ms for both cases and both implementations; F0 summary, events and
flows are byte-identical. F1 config/workload/failure identity, fault wall60 ms,
retry admission61 ms, CP512, rebuilt tail88 and emitted output8 are matched.
All eight workflow executions complete with zero terminal allocations and no
oracle reservations. Dense full restore stays at1109.768 ms; first-new-token moves
from1149.168 to1146.120381 ms. The sparse corrected case reaches accepted EOS at
697.416 ms and exercises the existing EOS cancellation path, cancelling unused
cold restore. Its larger change therefore includes demand identity, transfer
ordering, overlap and EOS cleanup interaction; it is not a pure overlap-only gain.

Four additional initialized layer microcases use layer1/query600/CP512, 200 ms
layer compute and explicit resident sets. They are not normal HBM-selection or
complete-workflow experiments:

| Layer case | Resident CP blocks | Old → fixed hit compute | Old → fixed misses | Old → fixed layer finish |
|---|---|---:|---:|---:|
| dense | {0,1,2,3} | 100 → 120 ms | 4 → 4 | 362.144 → 342.144 ms |
| synthetic_sparse | {0,3,4,5} | 120 → 160 ms | 2 → 1 | 211.072 → 200 ms |

The microcase field `full_restore_or_drain_ns` is the time of the final DES event,
not a measured `restore_done_ns`; use `layer_finish_ns` for the table. Raw configs,
summaries, events and flows are retained under `cases-old/` and `cases-fixed/`.
`summarize_validation.py` rechecks input pairing, source/import hashes, outputs,
and these values without executing a simulation, writing `PROTOTYPE_VALIDATION.json`.

Eight small workflow executions plus four initialized layer executions were run.
No primary/structural/sensitivity/post-hoc campaign was rerun. Their old numeric
results remain tied to old source, and these small-case deltas cannot be used as
correction factors for them.
