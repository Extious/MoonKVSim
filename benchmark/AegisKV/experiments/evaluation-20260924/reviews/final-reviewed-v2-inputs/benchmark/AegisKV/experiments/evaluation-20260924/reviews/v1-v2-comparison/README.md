# Frozen v1 to corrected v2: read-only comparison

Status: **PASS**, checked 2026-09-23T19:58:59.205148+00:00. Zero simulations.

| Group | Compared / planned | F0 exact numeric summary | F1 with changed WCT | New queued-history rows | Status |
|---|---:|---:|---:|---:|---|
| formal | 180 / 180 | 30 / 30 | 84 / 150 | 0 | PASS |
| structural | 135 / 135 | 45 / 45 | 90 / 90 | 279 | PASS |
| sensitivity | 126 / 126 | 63 / 63 | 38 / 63 | 0 | PASS |
| capacity | 32 / 32 | 16 / 16 | 12 / 16 | 0 | PASS |
| posthoc | 10 / 10 | 5 / 5 | 3 / 5 | 0 | PASS |

All counts cover completed pairs at the time of this read, not pending jobs.
F0 equality includes all request/workflow endpoints, emitted counts, every metric and peak allocation. Ignored fields are listed per run and below.

- Missing old config.slack_mode is verified equivalent to explicit dag before ignoring config SHA.
- Decompressed workload and profile bytes must be identical; regenerated gzip containers can have different hashes.
- Source/version, config/workload SHA and added recovery_eos_model text are separately recorded, not numeric endpoints.
- Absent history_restores equals only an explicitly empty array; nonempty rows remain semantic differences.

`COMPARISON.json` contains bound source/input/summary hashes, all numerical metric changes, and separate full active recovery and queued history records. `paired-workflows.csv` includes every old/new workflow endpoint, including zeros and adverse changes. `run-comparison.csv` summarizes all completed runs.

- Read-only comparison of completed runs only; partial is never campaign-wide PASS.
- Token replay exactness is the runtime assertion plus identical workload IDs and emitted counts; no native answer generation is rerun.
- Summary-only resource fields rely on in-run invariants; this is not independent byte-flow integration.
- F1 changes combine version fixes and resulting scheduling effects; paired differences are not an isolated queue-free causal decomposition.
- Active interrupted recoveries and queued history_restores are reported separately, never merged into co-victim counts.
- No bootstrap intervals: fixed fault scenarios and paired policies are not independent repetitions.

Re-run `reviews/compare_corrected_campaigns.py` after additional COMPLETE markers arrive. It only reads frozen campaign files and updates this review output.
