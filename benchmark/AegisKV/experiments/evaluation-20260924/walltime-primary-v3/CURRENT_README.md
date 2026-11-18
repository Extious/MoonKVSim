# Current execution and postprocessing status

This outer status note does not replace the sealed `PROTOCOL.json`, its source
snapshot, or the original descriptive README. The original protocol's two-worker
execution ceiling was amended in the separate
[`execution-amendment-16workers/AMENDMENT.json`](execution-amendment-16workers/AMENDMENT.json).
Its SHA-256 is
`a17e1ab7ab42be2fb8523728bc7d05e2548cffaca56f257cce1cf21d4ed9edbe`.

The amended detached executor uses at most 16 workers. Its one prespecified
repeat of the already-complete All-DRAM healthy condition is a transparency
validation, not an additional experimental sample. The initial 16 completed
conditions and all their recorded artifacts are retained; the two interrupted
partial directories were archived. `STOPPED_STATE.json` binds those artifacts.
The 164 source files, original protocol/seal, workloads, models, priors, guards,
profiles, faults and 180 condition identities are unchanged. The original
two-worker launch command in `README.md` describes that initial execution.

`STATUS.json`, the amendment's launcher/log/verification artifacts, and per-run
`COMPLETE.json` records supply the changing execution state. Completion requires
all 180 conditions, preserved original artifacts, and the prespecified parallel
validation. Completion order, host elapsed times, UTC timestamps and gzip
container metadata can differ after this amendment. Host `wall_seconds` must not
be compared between the two execution modes as simulator-overhead evidence.

The independent numeric watcher (`POSTPROCESS_LAUNCH.json`) waits for all 180
conditions before auditing and extracting the original identity endpoints. A
separate, exclusively locked paper-data/figure watcher (PID 2532287;
`PAPER_POSTPROCESS_LAUNCH.json`) requires that audit,
the endpoint provenance, and the v3 model/prior/guard binding before generating
the full figure and paper summary. Its metadata links this execution amendment.
The six completed healthy predictor-error rows can be exported beforehand;
they do not establish fault-condition prediction accuracy. Final-size visual
review remains a separate gate after figure generation. Its sealed sources and
protocol are recorded in `PAPER_POSTPROCESS_SEAL.json`; the six healthy rows are
already available in `paper-summary/healthy-predictor-error.csv`.

The later summary also recomputes fallback denominator/reason counts from the
two predeclared detailed AegisKV F1/load0.65 traces. These are logged
unfinished-workflow/control-window observations, not a continuous-time fraction.
It reports the 180-condition v2-to-v3 endpoint and saved placement changes,
separating active recoveries from queued/idle history restores; summary fields
do not reconstruct an unlogged ordinary-admission routing chain.

No old v2 result is relabeled. This v3 comparison jointly changes the wall-time
regressor, role priors and training-only guard; it does not isolate them. No
paper edits or new simulation conditions are part of this postprocessing.
