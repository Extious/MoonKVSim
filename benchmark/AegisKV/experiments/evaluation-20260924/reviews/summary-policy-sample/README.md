# Summary-only policy-sample computation

The isolated prototype changes only the iterator in `CurrentRuntime._control`:

```python
slack = self._slack()
for key, state in (self.states.items() if self.retain_detailed_logs else ()):
    ...
```

The `_slack()` call remains unconditional. Its Tracker side effects and all quota updates, rebalance calls, admissions, control-window scheduling, and event ordering remain in place. The Top-K optimization prototype is not included.

## Why the removed work does not change this model

The loop writes only its local variable `cp`. Its other operations read State/Checkpoint values and calculate sample fields. `_dram_estimate` delegates to `_recovery_estimate`; `_hbm_gain` makes two recovery estimates and calls arithmetic `hbm_gain`. These routines update no simulation state, allocate no resources, and schedule no events. `_record('policy_sample', ...)` discards this category when detailed logging is disabled, without incrementing counters or identifiers.

The default linear duration function and the campaign's `GridDurationProfile` are deterministic functions of their arguments. The latter mutates only its CPU LRU caches. Removing redundant accesses can change cache entries/statistics, but does not change the returned modeled durations. This argument does not cover an arbitrary externally supplied duration callable whose output depends on call order or whose calls mutate simulation state.

Detailed mode executes the same loop as before. The new regression uses a pure fixed profile with prefill-forward overhead and compares every summary field except the intended logging-retention flag, for both healthy execution and a token-aligned failure. It also checks that detailed logs are present only in detailed mode.

## Source and input provenance

`SOURCE.json` identifies the two isolated package trees and hashes all 143 Python files in each. Exactly `python/moonkvsim/aegiskv/current/runtime.py` differs. `prototype.patch` contains the one-line change. The live source was not edited while these differential runs executed. Structural campaign workloads, failure descriptors, configuration and profile are read without modifying the original campaign. These are new validation executions, not replacements for old frozen results.

`run_comparison.py` constructs each case from the original structural PLAN and uses the isolated current runtime. The source version includes EOSfix1 and the zero-Slack option, with `slack_mode='dag'` for these controls; both compared variants have those same semantics. Because the old structural freeze predates those changes, comparison is between the two new isolated variants, not an assertion that the old campaign source hash is identical.

Each variant writes a full serialized summary, configuration, failure, and compressed event/flow outputs. `compare_results.py` requires byte-for-byte summary/config/failure equality, and equal decompressed event/flow contents. `RESULTS.json` preserves every timing result, including regressions. Wall and process CPU times are single executions on a host concurrently running other campaigns; they are descriptive, not a controlled throughput measurement or a confidence interval.

## Validation record

- Initial isolated current-runtime suite: 57 passed; the sole CLI-manifest test could not find the absent paper/AGENTS fixture files in the package-only copy.
- Supplying those two unchanged fixtures and read-only Git metadata to the isolated CLI test yielded three passes: that CLI test plus the two new logging-parity regressions. No source change was needed to resolve the fixture issue.
- Four intended differential pairs are 8/32-workflow history reuse, seed 7, AegisKV, healthy and `left.decode` failure. `RESULTS.json` records whether all four have finished and their exact hashes.
- Ruff passes for the comparison harness and regression.

Only after all four differential pairs complete and the regression suite passes should the one-line change be applied to live source and a new scale campaign be frozen. Existing campaign snapshots, running workers, partial directories and results must remain intact.

## Completed differential and application

All four pairs passed exact summary/config/failure and decompressed event/flow equality. The one-line change was applied to live runtime after these checks; `APPLICATION.json` records before/after hashes. All 60 current-runtime tests pass, including the two new logging-parity cases. Existing frozen campaigns were not changed, and no new scale campaign was started.

| Workflows / condition | Old wall (s) | Optimized wall (s) | Speedup |
|---|---:|---:|---:|
| history_reuse-n8-s7-aegiskv-F0 | 41.43 | 45.45 | 0.912x |
| history_reuse-n8-s7-aegiskv-left.decode | 59.15 | 32.36 | 1.828x |
| history_reuse-n32-s7-aegiskv-F0 | 316.46 | 254.42 | 1.244x |
| history_reuse-n32-s7-aegiskv-left.decode | 391.12 | 304.40 | 1.285x |
