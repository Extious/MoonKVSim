# Post-hoc DRAM / Slack mechanism diagnostic

Read `RESULTS.md` for the five paired outcomes and limits; `PROTOCOL.md` is the immutable, pre-execution ten-run construction. The initial 1.125 GiB proposal was rejected by metadata-inclusive arithmetic before any simulation, and the frozen experiment uses 1.25/4 GiB.

`INDEPENDENT_AUDIT.json` recomputes all ten DRAM byte-time integrals and peaks, frozen bindings, at-fault selection evidence and two observation-transparency controls. `RETIREMENT_WITNESS.json` contains the exact before/after checkpoint retirement snapshots. `endpoint-results.csv` and `resource-results.csv` preserve all cases. Raw summaries and full events/flows/journals/observer snapshots are in `runs/`.

The ten formal experiments are unchanged. Two separate base-runtime validation executions live in `validation/`; they are not additional samples. The first Restart control has empty flow logs; the second tight DAG DRAM failure has 158 nonempty flow records and matches its observed formal summary/events/flows byte-for-byte after decompression. Scope and hashes are in `OBSERVATION_TRANSPARENCY.json`, `VALIDATION_EXTENSION.md`, and `NONEMPTY_OBSERVATION_TRANSPARENCY.json`.

`TIMING_METADATA_ERRATUM.md` corrects the inherited manifest timing label without changing the seal: executed timing comes from the pinned AIC GridDurationProfile, not the linear Config fallback. It is not end-to-end serving calibration. The complete 32-run capacity/zero-Slack study remains a separate null-WCT result; this diagnostic does not replace it.

`RECOVERY_DOMAIN_ERRATUM.md` records the subsequently diagnosed recovery-selector domain issue. These frozen results and accounting audits do not validate the corrected implementation; matched corrected runs are required for new numerical claims.
