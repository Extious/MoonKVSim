# Reproduction and delivery

The numerical matrix is sealed by PREPARED.json and COMPLETE.json. V1 is a preserved prepared-only snapshot; v2 is the executed revision with unchanged conditions.

Run the copied source, passing this output directory explicitly:

```
.venv/bin/python source_snapshot/benchmark/AegisKV/experiments/scripts/current_design/run_native_transfer_component.py verify --out /absolute/path/to/native-transfer-postreview-v2
.venv/bin/python analysis_snapshot/audit_native_transfer_component.py --out /absolute/path/to/native-transfer-postreview-v2
.venv/bin/python analysis_snapshot/summarize_native_transfer_component.py --out /absolute/path/to/native-transfer-postreview-v2
```

The last two commands only verify/summarize saved arrays; no simulation runs. The completed numerical runner refuses overwriting the matrix. For a fresh matrix, prepare a new directory from the supplied source with the bound original native files available, then run its source snapshot.

Nine synthetic component tests passed; all five added sources pass Ruff. An independent agent reviewed the engine and declared assumptions before execution. Its two findings (false all-hit preemption counts and missing per-case JSON/identity reuse binding) were corrected in v2. Independent artifact audit reconstructs all 10,538,701 transfer segments, 7,077,888 query-ready records and 27,648 layer records without importing the simulation engine; all 216 zero-compute byte/time identities pass.

Read RESULTS.md for the negative as well as positive findings. The experiment changes first-L prepared residency only, under a common prefetch order and explicitly assumed release/compute timing. No existing runtime, frozen 483-point campaigns, walltime-predictor files, paper, or previous native results were edited. REVISION_AUDIT.json verifies the original current runtime matches the frozen formal-v2 source and all nine extracted native input artifacts match between v1 and v2.
