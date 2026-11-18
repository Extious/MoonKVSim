> **Historical record — superseded for the revised paper.** This file describes
> the September 5 legacy-model campaign. Its results are excluded from the
> Mooncake-aligned manuscript. See `MOONCAKE_ALIGNMENT.md`, `COMPLETION_REPORT.md`
> and `data/aligned-statistics.json` for the revised study.

# Sensitivity audit correction

The original V3 sensitivity producer stopped at F=4, C=16, seed 3 because its
formal checker required a later multiplicative decrease for every observed
pressure event. The failure is retained in
`output/paper-simulation-8b/20260905/runs-v3/sensitivity/FAILURE.json`.

The complete raw record proves a legitimate unavailable-device window:

| Event on gpu-0 | Virtual time, seconds |
| --- | ---: |
| Last healthy control decision | 252.735000000 |
| Two primary-headroom pressure observations | 252.835349731 |
| GPU failure and full HBM unavailability | 255.300179866 |
| Next periodic control window | 258.752500000 |
| GPU repair with empty reusable HBM | 375.300179866 |
| First post-repair control decision | 379.102500000 |

`_on_aimd_control_window` clears its pressure latch before checking whether the
GPU is failed. It skips quota mutation while the device is unavailable.
Consequently this old pressure correctly does not produce a later decrease.
The repaired checker requires the preceding cadence, an outage covering the
next window, matching complete physical HBM loss and repair, and evidence that
the workload continued beyond the skipped window. A failure label alone cannot
excuse a missed healthy-window decrease.

The original full raw now passes the corrected formal audit. The hash-bound
diagnostic is `output/paper-simulation-8b/20260905/pressure-gap-recheck.json`;
the compact chronology is `pressure-gap-diagnostic.json` in the same directory.
This diagnostic does not accept the unfinished sensitivity matrix.

No simulation transition, routing, policy, duration, configuration or workload
file changed. The new execution snapshot `source-v3-auditfix`, commit
`d3e1e7357e00f35a79fd63f1b91e81778dfadf4d`, differs from source-v3 only in the
formal checker and a new regression file. The independent analysis-v3 commit
is `0b7995e457c9cb7c45b1ecd397c1ccbd99b6fd8f`. Both frozen snapshots passed
111 targeted tests; the changed checker also passes Ruff and mypy. Tests reject
late or earlier failures, early repair, wrong GPUs, incomplete physical loss,
missing repair, capacity mismatch, missing cadence, and a workload ending
before the purported skipped window.

All 70 measured sensitivity executions run afresh in `runs-auditfix`.
Only the 20 pre-existing canonical schedules are reused. These were selected by
the unchanged Store-only oracle, which does not execute this AegisKV checker.
`import_sensitivity_plans.py` verifies every old source binding, proves the sole
changed bound code file is the checker, validates both envelope versions, and
requires identical schedule content. It preserves the original envelopes
verbatim. `runs-auditfix/CANONICAL_PLAN_IMPORT.json` records every original and
new hash; its copies are retained with checkpoint proof. No measured result is
imported, and no focus or seed is selected again after observing effects.

The original V3 primary, F0, ablation and timing runs retain their original
provenance and analysis. Sensitivity's corrected acceptance is independently
bound to its new source and analysis snapshots. Final figures may be generated
only after the complete new sensitivity study becomes VALID.

## Final outcome

The corrected sensitivity study completed all 70 fresh measured runs and
independent acceptance is VALID. Figures 5/6 and the final manuscript are
reviewed. The earlier diagnostic alone did not accept the study; final
evidence is `runs-auditfix/acceptance-sensitivity.json`.
